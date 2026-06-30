from __future__ import annotations

import argparse
import contextlib
import fnmatch
import json
import tempfile
import zipfile
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except Exception:
        return default


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        if v is None or v == "":
            return default
        return int(v)
    except Exception:
        return default


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"rows": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"rows": []}


def infer_family(name: str, row: dict[str, Any], is_branch: bool) -> str:
    lower = name.lower()
    if is_branch:
        symbol = (row.get("symbol") or "").strip().lower()
        tokens = [t for t in lower.split("_") if t]
        if symbol and tokens and tokens[0] == symbol:
            body = tokens[1:4]
            return "_".join([symbol] + body[:2]) if len(body) >= 2 else "_".join(tokens[:3])
        return "_".join(tokens[:3]) if len(tokens) >= 3 else lower
    for prefix in [
        "mainline_core_satellite",
        "mainline_split",
        "mainline_live",
        "mainline_base",
        "mainline_overlay",
        "mainline_hold",
        "mainline_event",
    ]:
        if lower.startswith(prefix):
            return prefix
    tokens = [t for t in lower.split("_") if t]
    return "_".join(tokens[:3]) if len(tokens) >= 3 else lower


def get_recent_metrics(row: dict[str, Any]) -> dict[str, Any]:
    dom = row.get("dominant_gate") or {}
    if isinstance(dom, dict):
        recent = dom.get("recent_metrics")
        if isinstance(recent, dict):
            return recent
        metrics = dom.get("metrics")
        if isinstance(metrics, dict):
            ws = metrics.get("window_start")
            if isinstance(ws, str) and ws.startswith("2024-"):
                return metrics
    for gate_row in row.get("gate_rows") or []:
        if isinstance(gate_row, dict):
            recent = gate_row.get("recent_metrics")
            if isinstance(recent, dict):
                return recent
    return {}


def get_wf_metrics(row: dict[str, Any]) -> dict[str, Any]:
    wf = row.get("walkforward") or {}
    if isinstance(wf, dict):
        metrics = wf.get("metrics")
        if isinstance(metrics, dict):
            return metrics
    return {}


def metric_summary(metrics: dict[str, Any]) -> dict[str, Any]:
    monthly = metrics.get("monthly") or {}
    return {
        "trades": _safe_int(metrics.get("trades")),
        "pf": _safe_float(metrics.get("pf")),
        "ret": _safe_float(metrics.get("ret")),
        "maxdd": _safe_float(metrics.get("maxdd")),
        "monthlyized_ret": _safe_float(metrics.get("monthlyized_ret")),
        "months_ge_20": _safe_int(monthly.get("months_ge_20")),
    }


@dataclass
class RowAudit:
    name: str
    symbol: str
    family: str
    alpha_score: float
    decision: str
    full_trades: int
    recent_trades: int
    wf_trades: int
    recent_pf: float
    wf_pf: float
    recent_ret: float
    wf_ret: float
    recent_monthlyized: float
    wf_monthlyized: float
    low_sample_high_pf: bool
    dead_recent_wf_zero: bool
    full_zero: bool
    missing_guard_fields: bool


def audit_rows(rows: Iterable[dict[str, Any]], *, is_branch: bool) -> list[RowAudit]:
    audits: list[RowAudit] = []
    for row in rows:
        name = str(row.get("name") or "")
        symbol = str(row.get("symbol") or ("main" if not is_branch else "")).lower()
        family = infer_family(name, row, is_branch)
        full = metric_summary(row.get("full_metrics") or {})
        recent = metric_summary(get_recent_metrics(row))
        wf = metric_summary(get_wf_metrics(row))
        alpha_score = _safe_float(row.get("alpha_score"))
        decision = str(row.get("decision") or "")
        missing_guard_fields = not bool(row.get("dominant_gate")) or not bool(row.get("walkforward"))
        full_zero = full["trades"] == 0 or (full["trades"] == 0 and full["pf"] == 0 and full["ret"] == 0)
        dead_recent_wf_zero = (
            recent["trades"] == 0
            and wf["trades"] == 0
            and recent["pf"] == 0
            and wf["pf"] == 0
            and recent["ret"] == 0
            and wf["ret"] == 0
        )
        low_sample_high_pf = (
            ((0 < recent["trades"] <= 3 and recent["pf"] >= 3.0) or (0 < wf["trades"] <= 3 and wf["pf"] >= 3.0))
            and (recent["monthlyized_ret"] > 0 or wf["monthlyized_ret"] > 0)
        )
        audits.append(
            RowAudit(
                name=name,
                symbol=symbol,
                family=family,
                alpha_score=alpha_score,
                decision=decision,
                full_trades=full["trades"],
                recent_trades=recent["trades"],
                wf_trades=wf["trades"],
                recent_pf=recent["pf"],
                wf_pf=wf["pf"],
                recent_ret=recent["ret"],
                wf_ret=wf["ret"],
                recent_monthlyized=recent["monthlyized_ret"],
                wf_monthlyized=wf["monthlyized_ret"],
                low_sample_high_pf=low_sample_high_pf,
                dead_recent_wf_zero=dead_recent_wf_zero,
                full_zero=full_zero,
                missing_guard_fields=missing_guard_fields,
            )
        )
    return audits


def dominant_ratio(audits: list[RowAudit], top_n: int) -> tuple[str, float, Counter]:
    top = sorted(audits, key=lambda x: x.alpha_score, reverse=True)[:top_n]
    counts = Counter(a.family for a in top)
    if not counts:
        return "", 0.0, counts
    fam, c = counts.most_common(1)[0]
    return fam, c / max(len(top), 1), counts


def capped_shortlist(audits: list[RowAudit], *, is_branch: bool) -> dict[str, list[dict[str, Any]]]:
    rows = sorted(audits, key=lambda x: x.alpha_score, reverse=True)
    if not is_branch:
        fam_cap = 2
        picked: list[RowAudit] = []
        fam_counts: Counter = Counter()
        for row in rows:
            if row.dead_recent_wf_zero or row.full_zero or row.low_sample_high_pf:
                continue
            if fam_counts[row.family] >= fam_cap:
                continue
            picked.append(row)
            fam_counts[row.family] += 1
            if len(picked) >= 6:
                break
        return {"main": [asdict(r) for r in picked]}

    result: dict[str, list[dict[str, Any]]] = {}
    per_symbol = defaultdict(list)
    for row in rows:
        per_symbol[row.symbol].append(row)
    for symbol, subrows in per_symbol.items():
        fam_cap = 2
        picked: list[RowAudit] = []
        fam_counts: Counter = Counter()
        for row in subrows:
            if row.dead_recent_wf_zero or row.full_zero or row.low_sample_high_pf:
                continue
            if fam_counts[row.family] >= fam_cap:
                continue
            picked.append(row)
            fam_counts[row.family] += 1
            if len(picked) >= 6:
                break
        result[symbol] = [asdict(r) for r in picked]
    return result


def percent(v: float) -> str:
    return f"{v * 100:.2f}%"


def build_summary(main_audits: list[RowAudit], branch_audits: list[RowAudit]) -> dict[str, Any]:
    main_dom_family, main_dom_ratio, main_counts = dominant_ratio(main_audits, 8)
    branch_dom_family, branch_dom_ratio, branch_counts = dominant_ratio(branch_audits, 12)
    main_dead = [a for a in main_audits if a.dead_recent_wf_zero]
    branch_dead = [a for a in branch_audits if a.dead_recent_wf_zero]
    main_full_zero = [a for a in main_audits if a.full_zero]
    branch_full_zero = [a for a in branch_audits if a.full_zero]
    guard_gaps = [a for a in main_audits + branch_audits if a.missing_guard_fields]
    low_sample = [a for a in main_audits + branch_audits if a.low_sample_high_pf]
    return {
        "main": {
            "rows": len(main_audits),
            "dead_recent_wf_zero": len(main_dead),
            "full_zero": len(main_full_zero),
            "dominant_family": main_dom_family,
            "dominant_ratio": round(main_dom_ratio, 4),
            "top8_family_counts": dict(main_counts),
        },
        "branch": {
            "rows": len(branch_audits),
            "dead_recent_wf_zero": len(branch_dead),
            "full_zero": len(branch_full_zero),
            "dominant_family": branch_dom_family,
            "dominant_ratio": round(branch_dom_ratio, 4),
            "top12_family_counts": dict(branch_counts),
            "symbol_counts": dict(Counter(a.symbol for a in branch_audits)),
        },
        "guard_gaps": len(guard_gaps),
        "low_sample_high_pf": len(low_sample),
        "system_ready_for_strategy_frontier": (
            main_dom_ratio <= 0.5 and branch_dom_ratio <= 0.5 and len(guard_gaps) == 0
        ),
    }


def format_report(summary: dict[str, Any], curated: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("Stage182 single-export diversity frontier")
    lines.append("")
    lines.append("[summary]")
    lines.append(f"- main_rows={summary['main']['rows']} main_dead={summary['main']['dead_recent_wf_zero']} main_full_zero={summary['main']['full_zero']}")
    lines.append(f"- main_dominant_family={summary['main']['dominant_family']} dominant_ratio={summary['main']['dominant_ratio']}")
    lines.append(f"- branch_rows={summary['branch']['rows']} branch_dead={summary['branch']['dead_recent_wf_zero']} branch_full_zero={summary['branch']['full_zero']}")
    lines.append(f"- branch_dominant_family={summary['branch']['dominant_family']} dominant_ratio={summary['branch']['dominant_ratio']}")
    lines.append(f"- branch_symbol_counts={json.dumps(summary['branch']['symbol_counts'], ensure_ascii=False)}")
    lines.append(f"- missing_guard_fields={summary['guard_gaps']}")
    lines.append(f"- low_sample_high_pf={summary['low_sample_high_pf']}")
    for key in ["main", "btc", "eth", "sol"]:
        rows = curated.get(key, [])
        if not rows:
            continue
        lines.append("")
        lines.append(f"[curated_{key}]")
        for row in rows:
            lines.append(
                f"- {row['name']} | family={row['family']} | recent_monthly={percent(row['recent_monthlyized'])} | wf_monthly={percent(row['wf_monthlyized'])} | recent_trades={row['recent_trades']} | wf_trades={row['wf_trades']}"
            )
    lines.append("")
    lines.append("[next]")
    lines.append("- 已加 family diversity cap")
    lines.append("- 已剔除 dead_recent_wf_zero / full_zero")
    lines.append("- 已压掉 low-sample high-PF 假优先")
    lines.append("- Downloads 只保留 1 个可上传 zip")
    return "\n".join(lines) + "\n"


def cleanup_previous_outputs(downloads_dir: Path) -> None:
    patterns = [
        "stage181_*_latest.json",
        "stage181_*_latest.txt",
        "stage182_*_latest.json",
        "stage182_*_latest.txt",
    ]
    for p in downloads_dir.iterdir():
        if not p.is_file():
            continue
        if any(fnmatch.fnmatch(p.name, pat) for pat in patterns):
            with contextlib.suppress(Exception):
                p.unlink()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-dir", required=True)
    args = ap.parse_args()

    project_dir = Path(args.project_dir).resolve()
    research_dir = project_dir / "reports" / "research_raw"
    downloads_dir = Path.home() / "Downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)

    stage90 = load_json(research_dir / "stage90_mainline_event_alpha_matrix_latest.json")
    stage91 = load_json(research_dir / "stage91_branch_event_alpha_matrix_latest.json")
    main_rows = stage90.get("rows") or []
    branch_rows = stage91.get("rows") or []
    if not main_rows and not branch_rows:
        raise SystemExit(f"missing or unreadable stage90/stage91 under {research_dir}")

    main_audits = audit_rows(main_rows, is_branch=False)
    branch_audits = audit_rows(branch_rows, is_branch=True)
    summary = build_summary(main_audits, branch_audits)
    curated = capped_shortlist(main_audits, is_branch=False)
    curated.update(capped_shortlist(branch_audits, is_branch=True))

    bundle = downloads_dir / "stage182_single_export_diversity_frontier_latest.zip"
    cleanup_previous_outputs(downloads_dir)
    with tempfile.TemporaryDirectory(prefix="stage182_") as td:
        td_path = Path(td)
        report_path = td_path / "stage182_single_export_diversity_frontier_latest.txt"
        shortlist_path = td_path / "stage182_curated_shortlist_latest.json"
        dead_path = td_path / "stage182_dead_blacklist_latest.json"
        summary_path = td_path / "stage182_summary_latest.json"
        report_path.write_text(format_report(summary, curated), encoding="utf-8")
        shortlist_path.write_text(json.dumps(curated, ensure_ascii=False, indent=2), encoding="utf-8")
        dead_payload = {
            "main": {
                "dead_recent_wf_zero": [asdict(x) for x in main_audits if x.dead_recent_wf_zero],
                "full_zero": [asdict(x) for x in main_audits if x.full_zero],
                "low_sample_high_pf": [asdict(x) for x in main_audits if x.low_sample_high_pf],
            },
            "branch": {
                "dead_recent_wf_zero": [asdict(x) for x in branch_audits if x.dead_recent_wf_zero],
                "full_zero": [asdict(x) for x in branch_audits if x.full_zero],
                "low_sample_high_pf": [asdict(x) for x in branch_audits if x.low_sample_high_pf],
            },
        }
        dead_path.write_text(json.dumps(dead_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for p in [report_path, summary_path, shortlist_path, dead_path]:
                zf.write(p, arcname=p.name)

    print(format_report(summary, curated))
    print(f"[bundle] {bundle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
