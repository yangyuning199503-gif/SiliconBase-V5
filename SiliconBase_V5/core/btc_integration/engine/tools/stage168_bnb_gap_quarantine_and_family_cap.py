#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

try:
    import pandas as pd
except Exception as exc:  # pragma: no cover
    print(f"[ERR] pandas import failed: {exc}", file=sys.stderr)
    raise


@dataclass
class GapSummary:
    exists: bool
    rows: int
    start: str | None
    end: str | None
    dupes: int
    non15m_gaps: int
    max_gap: str | None
    gaps: list[tuple[str, str, int]]


def project_root_from_here() -> Path:
    return Path(__file__).resolve().parents[1]


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def read_csv_timeframe(path: Path) -> GapSummary:
    if not path.exists() or path.stat().st_size == 0:
        return GapSummary(False, 0, None, None, 0, 0, None, [])
    df = pd.read_csv(path)
    ts_col = None
    for c in ["ts", "timestamp", "open_time", "datetime", "time"]:
        if c in df.columns:
            ts_col = c
            break
    if ts_col is None:
        # best effort: first column
        ts_col = df.columns[0]
    ts = pd.to_datetime(df[ts_col], errors="coerce", utc=False)
    ts = ts.dropna().sort_values().reset_index(drop=True)
    if ts.empty:
        return GapSummary(True, 0, None, None, 0, 0, None, [])
    dupes = int(ts.duplicated().sum())
    deltas = ts.diff().dropna()
    exp = pd.Timedelta(minutes=15)
    gaps = []
    non15 = 0
    max_gap = exp
    if not deltas.empty:
        max_gap = deltas.max()
        bad_idx = deltas[deltas != exp].index.tolist()
        non15 = len(bad_idx)
        for idx in bad_idx:
            prev_t = ts.iloc[idx - 1]
            curr_t = ts.iloc[idx]
            missing = int((curr_t - prev_t) / exp) - 1 if curr_t > prev_t else 0
            gaps.append((str(prev_t), str(curr_t), max(missing, 0)))
    return GapSummary(
        True,
        int(len(ts)),
        str(ts.iloc[0]),
        str(ts.iloc[-1]),
        dupes,
        non15,
        str(max_gap),
        gaps,
    )


def family_main(name: str) -> str:
    if name.startswith("mainline_live"):
        return "mainline_live"
    if name.startswith("mainline_core"):
        return "mainline_core"
    if name.startswith("mainline_split"):
        return "mainline_split"
    if name.startswith("combo_sr"):
        return "combo_sr"
    parts = name.split("_")
    return "_".join(parts[:2]) if len(parts) >= 2 else name


def family_branch(name: str) -> str:
    parts = name.split("_")
    if not parts:
        return name
    asset = parts[0]
    if len(parts) >= 3 and parts[1] in {"long", "short", "dual"}:
        return f"{asset}_{parts[2]}"
    if len(parts) >= 2:
        return f"{asset}_{parts[1]}"
    return asset


def parse_mainline_txt(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    out = []
    rx = re.compile(r"^-\s+([^:]+):\s+dominant_gate=([^\s]+)\s+\(([^)]+)\)")
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = rx.match(raw.strip())
        if not m:
            continue
        name, gate, status = m.groups()
        out.append({
            "name": name.strip(),
            "gate": gate.strip(),
            "status": status.strip(),
            "raw": raw.strip(),
            "family": family_main(name.strip()),
        })
    return out


def parse_branch_txt(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    out = []
    rx = re.compile(r"^-\s+([A-Z]+)\s+\|\s+([a-z]+)\s+\|\s+([^:]+):\s+dominant_gate=([^\s]+)\s+\(([^)]+)\)")
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = rx.match(raw.strip())
        if not m:
            continue
        asset, side, name, gate, status = m.groups()
        name = name.strip()
        out.append({
            "asset": asset.strip(),
            "side": side.strip(),
            "name": name,
            "gate": gate.strip(),
            "status": status.strip(),
            "raw": raw.strip(),
            "family": family_branch(name),
        })
    return out


def apply_cap(rows: list[dict[str, str]], family_key: str, max_per_family: int, max_total: int) -> list[dict[str, str]]:
    kept: list[dict[str, str]] = []
    fam_count: dict[str, int] = {}
    for row in rows:
        fam = row[family_key]
        if fam_count.get(fam, 0) >= max_per_family:
            continue
        kept.append(row)
        fam_count[fam] = fam_count.get(fam, 0) + 1
        if len(kept) >= max_total:
            break
    return kept


def load_dead(audit_json: Path) -> dict[str, list[str]]:
    if not audit_json.exists():
        return {
            "dead_main": [],
            "dead_branch": [],
        }
    data = json.loads(audit_json.read_text(encoding="utf-8"))
    dead_main = set()
    dead_branch = set()
    for k in ["dead_full_zero", "dead_recent_wf_zero"]:
        for name in data.get("dead_main", {}).get(k, []):
            dead_main.add(name)
        for name in data.get("dead_branch", {}).get(k, []):
            dead_branch.add(name)
    return {
        "dead_main": sorted(dead_main),
        "dead_branch": sorted(dead_branch),
    }


def load_latest_audit(root: Path) -> Path | None:
    p = root / "reports" / "research_raw" / "stage167_data_repair_diversity_guard_latest.json"
    return p if p.exists() else None


def export_gap_csv(path: Path, gaps: list[tuple[str, str, int]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["prev_ts", "next_ts", "missing_bars", "quarantine_start", "quarantine_end"])
        for prev_s, next_s, missing in gaps:
            prev_dt = pd.to_datetime(prev_s)
            next_dt = pd.to_datetime(next_s)
            qstart = prev_dt - pd.Timedelta(minutes=15)
            qend = next_dt + pd.Timedelta(minutes=15)
            w.writerow([prev_s, next_s, missing, str(qstart), str(qend)])


def pack_download(zip_path: Path, files: list[Path]) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            if f.exists():
                zf.write(f, arcname=f.name)


def main() -> int:
    root = project_root_from_here()
    reports = root / "reports" / "research_raw"
    ensure_dir(reports)
    downloads = Path.home() / "Downloads"
    ensure_dir(downloads)

    raw_dir = root / "data" / "raw"
    snap_dir = root / "data" / "raw_snapshots"

    assets = {
        "btc": read_csv_timeframe(raw_dir / "btc_15m.csv"),
        "bnb": read_csv_timeframe(raw_dir / "bnb_15m.csv"),
        "eth": read_csv_timeframe(raw_dir / "eth_15m.csv"),
        "sol": read_csv_timeframe(raw_dir / "sol_15m.csv"),
    }
    snaps = {
        "btc": read_csv_timeframe(snap_dir / "btc_15m.best.csv"),
        "bnb": read_csv_timeframe(snap_dir / "bnb_15m.best.csv"),
    }

    audit_path = load_latest_audit(root)
    dead = load_dead(audit_path) if audit_path else {"dead_main": [], "dead_branch": []}

    stage90_txt = reports / "stage90_mainline_event_alpha_matrix_latest.txt"
    stage91_txt = reports / "stage91_branch_event_alpha_matrix_latest.txt"
    main_rows = parse_mainline_txt(stage90_txt)
    branch_rows = parse_branch_txt(stage91_txt)

    main_live = [r for r in main_rows if r["name"] not in set(dead["dead_main"])]
    branch_live = [r for r in branch_rows if r["name"] not in set(dead["dead_branch"])]

    main_capped = apply_cap(main_live, "family", max_per_family=2, max_total=6)
    branch_capped = apply_cap(branch_live, "family", max_per_family=3, max_total=12)

    # Ensure branch diversity across assets if possible.
    by_asset: dict[str, list[dict[str, str]]] = {}
    for r in branch_live:
        by_asset.setdefault(r.get("asset", "?"), []).append(r)
    branch_diverse = []
    seen_names = set()
    for asset in ["BTC", "ETH", "SOL"]:
        for r in by_asset.get(asset, []):
            if r["name"] in seen_names:
                continue
            if sum(1 for x in branch_diverse if x["family"] == r["family"]) >= 3:
                continue
            branch_diverse.append(r)
            seen_names.add(r["name"])
            break
    for r in branch_capped:
        if r["name"] in seen_names:
            continue
        if len(branch_diverse) >= 12:
            break
        if sum(1 for x in branch_diverse if x["family"] == r["family"]) >= 3:
            continue
        branch_diverse.append(r)
        seen_names.add(r["name"])

    gap_csv = reports / "stage168_bnb_gap_windows_latest.csv"
    export_gap_csv(gap_csv, assets["bnb"].gaps)

    blacklist_json = reports / "stage168_dead_template_blacklist_latest.json"
    blacklist_json.write_text(json.dumps(dead, ensure_ascii=False, indent=2), encoding="utf-8")

    shortlist_json = reports / "stage168_family_capped_shortlist_latest.json"
    shortlist_payload = {
        "main_kept": main_capped,
        "branch_kept": branch_diverse,
        "notes": [
            "mainline cap=max 2 per family, top 6",
            "branch cap=max 3 per family, top 12, and try to keep BTC/ETH/SOL all present",
            "dead_full_zero and recent+wf double-zero names removed if stage167 audit exists",
        ],
    }
    shortlist_json.write_text(json.dumps(shortlist_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    out_txt = reports / "stage168_bnb_gap_quarantine_and_family_cap_latest.txt"
    lines: list[str] = []
    lines.append("Stage168 BNB 缺口隔离 + 死模板剔除 + family diversity cap")
    lines.append("")
    lines.append("[raw_audit]")
    for sym in ["btc", "bnb", "eth", "sol"]:
        s = assets[sym]
        lines.append(
            f"- {sym.upper()}: rows={s.rows} start={s.start} end={s.end} dupes={s.dupes} non15m_gaps={s.non15m_gaps} max_gap={s.max_gap}"
        )
    lines.append("")
    lines.append("[bnb_diagnosis]")
    if assets["bnb"].non15m_gaps > 0:
        lines.append(f"- BNB 仍有 {assets['bnb'].non15m_gaps} 个非15m缺口，最大缺口 {assets['bnb'].max_gap}。")
        snap = snaps.get("bnb")
        if snap and snap.exists:
            lines.append(
                f"- snapshot 也不干净：rows={snap.rows} non15m_gaps={snap.non15m_gaps} max_gap={snap.max_gap}，因此这次不强行回填。"
            )
        lines.append("- 已输出 bnb gap windows，建议下一轮主线回测先做 gap quarantine，而不是继续把 BNB 缺口当连续数据用。")
    else:
        lines.append("- BNB 已无非15m缺口。")
    lines.append("")
    lines.append("[dead_template_blacklist]")
    lines.append(f"- main dead count={len(dead['dead_main'])}")
    lines.append(f"- branch dead count={len(dead['dead_branch'])}")
    lines.append("")
    lines.append("[main_shortlist_after_cap]")
    for r in main_capped:
        lines.append(f"- {r['name']} | family={r['family']} | gate={r['gate']} | status={r['status']}")
    lines.append("")
    lines.append("[branch_shortlist_after_cap]")
    for r in branch_diverse:
        lines.append(
            f"- {r['asset']} | {r['side']} | {r['name']} | family={r['family']} | gate={r['gate']} | status={r['status']}"
        )
    lines.append("")
    lines.append("[next_actions]")
    if assets["bnb"].non15m_gaps > 0:
        lines.append("- 主线先处理 BNB gap quarantine，再谈提频 ceiling。")
    lines.append("- 下一轮 frontier 先剔除死模板 blacklist。")
    lines.append("- 分支下一轮必须加 family diversity cap，不能再让 ETH reclaim 占满所有名额。")
    lines.append("- BTC/SOL 必须保路径，但先从非零触发家族里选。")
    out_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")

    zip_out = downloads / "stage168_bnb_gap_quarantine_and_family_cap_latest.zip"
    pack_download(zip_out, [out_txt, gap_csv, blacklist_json, shortlist_json])

    print(f"[OK] wrote {out_txt}")
    print(f"[OK] wrote {gap_csv}")
    print(f"[OK] wrote {blacklist_json}")
    print(f"[OK] wrote {shortlist_json}")
    print(f"[OK] wrote {zip_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
