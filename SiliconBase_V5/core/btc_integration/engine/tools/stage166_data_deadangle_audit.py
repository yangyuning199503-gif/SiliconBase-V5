from __future__ import annotations

import argparse
import csv
import json
import shutil
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

FMT_CANDIDATE_KEYS = ["name", "candidate"]


@dataclass
class RawAudit:
    symbol: str
    path: Path
    exists: bool
    rows: int = 0
    start: str = ""
    end: str = ""
    dupes: int = 0
    non15m_gaps: int = 0
    max_gap: str = ""


def _parse_ts(text: str) -> datetime | None:
    text = (text or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def audit_raw_csv(path: Path, symbol: str) -> RawAudit:
    audit = RawAudit(symbol=symbol.upper(), path=path, exists=path.exists())
    if not path.exists():
        return audit
    expected = timedelta(minutes=15)
    prev: datetime | None = None
    seen = set()
    max_gap = timedelta(0)
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        ts_idx = 0
        if header:
            lower = [str(x).strip().lower() for x in header]
            for cand in ("ts", "time", "timestamp", "datetime", "date"):
                if cand in lower:
                    ts_idx = lower.index(cand)
                    break
            else:
                # first row might actually be data
                row = header
                ts = _parse_ts(row[ts_idx] if ts_idx < len(row) else "")
                if ts is not None:
                    audit.rows += 1
                    audit.start = ts.strftime("%Y-%m-%d %H:%M:%S")
                    audit.end = audit.start
                    seen.add(ts)
                    prev = ts
        for row in reader:
            if not row:
                continue
            ts = _parse_ts(row[ts_idx] if ts_idx < len(row) else "")
            if ts is None:
                continue
            audit.rows += 1
            if not audit.start:
                audit.start = ts.strftime("%Y-%m-%d %H:%M:%S")
            audit.end = ts.strftime("%Y-%m-%d %H:%M:%S")
            if ts in seen:
                audit.dupes += 1
            else:
                seen.add(ts)
            if prev is not None:
                gap = ts - prev
                if gap != expected:
                    audit.non15m_gaps += 1
                if gap > max_gap:
                    max_gap = gap
            prev = ts
    audit.max_gap = str(max_gap if audit.rows else timedelta(0))
    return audit


def read_json_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    rows = data.get("rows") if isinstance(data, dict) else None
    return rows if isinstance(rows, list) else []


def candidate_name(row: dict[str, Any]) -> str:
    for key in FMT_CANDIDATE_KEYS:
        value = row.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def trade_triplet(row: dict[str, Any]) -> tuple[int, int, int]:
    full = int((row.get("full_metrics") or {}).get("trades") or 0)
    recent = int(((row.get("dominant_gate") or {}).get("recent_metrics") or {}).get("trades") or 0)
    wf = int(((row.get("walkforward") or {}).get("metrics") or {}).get("trades") or 0)
    return full, recent, wf


def classify_dead_templates(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    dead_full_zero: list[str] = []
    dead_recent_wf_zero: list[str] = []
    for row in rows:
        name = candidate_name(row)
        if not name:
            continue
        full, recent, wf = trade_triplet(row)
        if full == 0:
            dead_full_zero.append(name)
        elif recent == 0 and wf == 0:
            dead_recent_wf_zero.append(name)
    return {
        "dead_full_zero": sorted(dead_full_zero),
        "dead_recent_wf_zero": sorted(dead_recent_wf_zero),
    }


def family_prefix(name: str) -> str:
    parts = name.split("_")
    if not parts:
        return name
    if parts[0] in {"btc", "eth", "sol"} and len(parts) >= 3:
        return "_".join(parts[:2])
    if parts[0] == "mainline" and len(parts) >= 3:
        return "_".join(parts[:2])
    return "_".join(parts[:2]) if len(parts) >= 2 else name


def collapse_stats(rows: list[dict[str, Any]], top_n: int = 12) -> dict[str, Any]:
    usable = []
    for row in rows:
        name = candidate_name(row)
        if not name:
            continue
        decision = str(row.get("decision") or "")
        if decision not in {"hold", "reserve+", "watch"}:
            continue
        recent = (((row.get("dominant_gate") or {}).get("recent_metrics") or {}).get("monthlyized_ret") or 0.0)
        wf = (((row.get("walkforward") or {}).get("metrics") or {}).get("monthlyized_ret") or 0.0)
        usable.append((name, float(recent), float(wf)))
    usable.sort(key=lambda x: (x[1], x[2]), reverse=True)
    top = usable[:top_n]
    families = Counter(family_prefix(name) for name, _, _ in top)
    return {
        "top_names": [name for name, _, _ in top],
        "family_counter": dict(families),
        "dominant_family": families.most_common(1)[0][0] if families else "",
        "dominant_ratio": (families.most_common(1)[0][1] / len(top)) if top and families else 0.0,
    }


def maybe_restore_btc(project_dir: Path) -> dict[str, Any]:
    raw = project_dir / "data/raw/btc_15m.csv"
    snap = project_dir / "data/raw_snapshots/btc_15m.best.csv"
    out = {"repaired": False, "reason": "", "backup": "", "snapshot_rows": 0, "raw_rows": 0}
    if not raw.exists() or not snap.exists():
        out["reason"] = "raw_or_snapshot_missing"
        return out
    raw_a = audit_raw_csv(raw, "BTC")
    snap_a = audit_raw_csv(snap, "BTC")
    out["raw_rows"] = raw_a.rows
    out["snapshot_rows"] = snap_a.rows
    if snap_a.rows <= raw_a.rows:
        out["reason"] = "snapshot_not_longer"
        return out
    if raw_a.rows >= 100000:
        out["reason"] = "raw_not_short_enough"
        return out
    backup = raw.with_suffix(raw.suffix + ".pre_stage166_backup")
    shutil.copy2(raw, backup)
    shutil.copy2(snap, raw)
    out.update({"repaired": True, "reason": "snapshot_restored", "backup": str(backup)})
    return out


def write_report(project_dir: Path, text: str) -> Path:
    out = project_dir / "reports/research_raw/stage166_data_deadangle_audit_latest.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return out


def build_bundle(project_dir: Path, report_path: Path) -> Path:
    downloads = Path.home() / "Downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    bundle = downloads / "stage166_data_deadangle_audit_latest.zip"
    extras = [
        report_path,
        project_dir / "reports/research_raw/stage90_mainline_event_alpha_matrix_latest.txt",
        project_dir / "reports/research_raw/stage91_branch_event_alpha_matrix_latest.txt",
    ]
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in extras:
            if path.exists():
                zf.write(path, arcname=path.name)
    return bundle


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", default=".")
    args = parser.parse_args()
    project_dir = Path(args.project_dir).expanduser().resolve()

    raw_symbols = ["btc", "bnb", "eth", "sol"]
    audits: dict[str, RawAudit] = {}
    for sym in raw_symbols:
        audits[sym.upper()] = audit_raw_csv(project_dir / f"data/raw/{sym}_15m.csv", sym)

    btc_restore = maybe_restore_btc(project_dir)
    if btc_restore.get("repaired"):
        audits["BTC"] = audit_raw_csv(project_dir / "data/raw/btc_15m.csv", "BTC")

    stage90_rows = read_json_rows(project_dir / "reports/research_raw/stage90_mainline_event_alpha_matrix_latest.json")
    stage91_rows = read_json_rows(project_dir / "reports/research_raw/stage91_branch_event_alpha_matrix_latest.json")
    dead_main = classify_dead_templates(stage90_rows)
    dead_branch = classify_dead_templates(stage91_rows)
    main_collapse = collapse_stats(stage90_rows)
    branch_collapse = collapse_stats(stage91_rows)

    lines: list[str] = []
    lines.append("Stage166 数据 / 死模板 / 局部最优 审计")
    lines.append("")
    lines.append("[raw_audit]")
    for sym in ["BTC", "BNB", "ETH", "SOL"]:
        a = audits[sym]
        lines.append(
            f"- {sym}: exists={a.exists} rows={a.rows} start={a.start or '-'} end={a.end or '-'} dupes={a.dupes} non15m_gaps={a.non15m_gaps} max_gap={a.max_gap or '-'}"
        )
    lines.append("")
    lines.append("[btc_restore]")
    lines.append(json.dumps(btc_restore, ensure_ascii=False))
    lines.append("")
    lines.append("[dead_main]")
    lines.append(json.dumps(dead_main, ensure_ascii=False, indent=2))
    lines.append("")
    lines.append("[dead_branch]")
    lines.append(json.dumps(dead_branch, ensure_ascii=False, indent=2))
    lines.append("")
    lines.append("[main_collapse]")
    lines.append(json.dumps(main_collapse, ensure_ascii=False, indent=2))
    lines.append("")
    lines.append("[branch_collapse]")
    lines.append(json.dumps(branch_collapse, ensure_ascii=False, indent=2))

    report_path = write_report(project_dir, "\n".join(lines) + "\n")
    bundle = build_bundle(project_dir, report_path)
    print(json.dumps({"ok": True, "report": str(report_path), "bundle": str(bundle)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
