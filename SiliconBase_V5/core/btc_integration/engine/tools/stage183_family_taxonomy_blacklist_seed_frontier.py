from __future__ import annotations

import argparse
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


def load_rows(path: Path, *, is_branch: bool) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    if isinstance(obj, dict) and isinstance(obj.get("rows"), list):
        return list(obj.get("rows") or [])

    if isinstance(obj, list):
        return obj

    if isinstance(obj, dict):
        rows: list[dict[str, Any]] = []
        keys = ["main"] if not is_branch else ["btc", "eth", "sol"]
        for key in keys:
            val = obj.get(key)
            if isinstance(val, list):
                for row in val:
                    if isinstance(row, dict):
                        row = dict(row)
                        row.setdefault("symbol", key if key != "main" else "main")
                        rows.append(row)
        return rows
    return []


def infer_family(name: str, row: dict[str, Any], is_branch: bool) -> str:
    lower = (name or "").lower()
    if not is_branch:
        if lower.startswith("mainline_core_satellite"):
            return "main_core_satellite"
        if lower.startswith("mainline_split"):
            return "main_split"
        if "ladder_pyramid" in lower:
            return "main_ladder_pyramid"
        if "overlay_hold" in lower or "_hold_" in lower:
            return "main_overlay_hold"
        if "risk_budget" in lower:
            return "main_risk_budget"
        if "message_confirm" in lower or "event_confirm" in lower or "event_alpha" in lower:
            return "main_event_confirm"
        if lower.startswith("mainline_live_dynlev_fix8_lock18"):
            return "main_live_fix8_lock18"
        if lower.startswith("mainline_live"):
            return "main_live_other"
        tokens = [t for t in lower.split("_") if t]
        return "_".join(tokens[:3]) if len(tokens) >= 3 else lower

    symbol = (row.get("symbol") or "").strip().lower()
    tokens = [t for t in lower.split("_") if t]
    if symbol and tokens and tokens[0] == symbol:
        body = tokens[1:4]
        if len(body) >= 2:
            return "_".join([symbol] + body[:2])
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
    hard_blacklisted: bool


def audit_rows(rows: Iterable[dict[str, Any]], *, is_branch: bool) -> list[RowAudit]:
    audits: list[RowAudit] = []
    for row in rows:
        name = str(row.get("name") or "")
        symbol = str(row.get("symbol") or ("main" if not is_branch else "")).lower()
        family = infer_family(name, row, is_branch)

        if "recent_monthlyized" in row or "recent_monthly" in row:
            full_trades = _safe_int(row.get("full_trades"))
            recent_trades = _safe_int(row.get("recent_trades"))
            wf_trades = _safe_int(row.get("wf_trades"))
            recent_pf = _safe_float(row.get("recent_pf"))
            wf_pf = _safe_float(row.get("wf_pf"))
            recent_ret = _safe_float(row.get("recent_ret"))
            wf_ret = _safe_float(row.get("wf_ret"))
            recent_monthlyized = _safe_float(row.get("recent_monthlyized") or row.get("recent_monthly"))
            wf_monthlyized = _safe_float(row.get("wf_monthlyized") or row.get("wf_monthly"))
            alpha_score = _safe_float(row.get("alpha_score"))
            decision = str(row.get("decision") or "")
            missing_guard_fields = bool(row.get("missing_guard_fields", False))
            full_zero = bool(row.get("full_zero", full_trades == 0))
            dead_recent_wf_zero = bool(
                row.get(
                    "dead_recent_wf_zero",
                    recent_trades == 0 and wf_trades == 0 and recent_pf == 0 and wf_pf == 0 and recent_ret == 0 and wf_ret == 0,
                )
            )
            low_sample_high_pf = bool(
                row.get(
                    "low_sample_high_pf",
                    ((0 < recent_trades <= 3 and recent_pf >= 3.0) or (0 < wf_trades <= 3 and wf_pf >= 3.0))
                    and (recent_monthlyized > 0 or wf_monthlyized > 0),
                )
            )
        else:
            full = metric_summary(row.get("full_metrics") or {})
            recent = metric_summary(get_recent_metrics(row))
            wf = metric_summary(get_wf_metrics(row))
            full_trades = full["trades"]
            recent_trades = recent["trades"]
            wf_trades = wf["trades"]
            recent_pf = recent["pf"]
            wf_pf = wf["pf"]
            recent_ret = recent["ret"]
            wf_ret = wf["ret"]
            recent_monthlyized = recent["monthlyized_ret"]
            wf_monthlyized = wf["monthlyized_ret"]
            alpha_score = _safe_float(row.get("alpha_score"))
            decision = str(row.get("decision") or "")
            missing_guard_fields = not bool(row.get("dominant_gate")) or not bool(row.get("walkforward"))
            full_zero = full_trades == 0
            dead_recent_wf_zero = (
                recent_trades == 0 and wf_trades == 0 and recent_pf == 0 and wf_pf == 0 and recent_ret == 0 and wf_ret == 0
            )
            low_sample_high_pf = (
                ((0 < recent_trades <= 3 and recent_pf >= 3.0) or (0 < wf_trades <= 3 and wf_pf >= 3.0))
                and (recent_monthlyized > 0 or wf_monthlyized > 0)
            )

        hard_blacklisted = False
        if is_branch:
            if family == "btc_break_fail":
                hard_blacklisted = True
            if family == "btc_retest_pair" and max(recent_trades, wf_trades) <= 1:
                hard_blacklisted = True

        audits.append(
            RowAudit(
                name=name,
                symbol=symbol,
                family=family,
                alpha_score=alpha_score,
                decision=decision,
                full_trades=full_trades,
                recent_trades=recent_trades,
                wf_trades=wf_trades,
                recent_pf=recent_pf,
                wf_pf=wf_pf,
                recent_ret=recent_ret,
                wf_ret=wf_ret,
                recent_monthlyized=recent_monthlyized,
                wf_monthlyized=wf_monthlyized,
                low_sample_high_pf=low_sample_high_pf,
                dead_recent_wf_zero=dead_recent_wf_zero,
                full_zero=full_zero,
                missing_guard_fields=missing_guard_fields,
                hard_blacklisted=hard_blacklisted,
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
        fam_cap = 1
        picked: list[RowAudit] = []
        fam_counts: Counter = Counter()
        for row in rows:
            if row.dead_recent_wf_zero or row.full_zero or row.low_sample_high_pf or row.hard_blacklisted:
                continue
            if fam_counts[row.family] >= fam_cap:
                continue
            picked.append(row)
            fam_counts[row.family] += 1
            if len(picked) >= 5:
                break
        return {"main": [asdict(r) for r in picked]}

    result: dict[str, list[dict[str, Any]]] = {}
    per_symbol: dict[str, list[RowAudit]] = defaultdict(list)
    for row in rows:
        per_symbol[row.symbol].append(row)
    for symbol, subrows in per_symbol.items():
        fam_cap = 2 if symbol == "eth" else 1
        picked: list[RowAudit] = []
        fam_counts: Counter = Counter()
        for row in subrows:
            if row.dead_recent_wf_zero or row.full_zero or row.low_sample_high_pf or row.hard_blacklisted:
                continue
            if fam_counts[row.family] >= fam_cap:
                continue
            picked.append(row)
            fam_counts[row.family] += 1
            if len(picked) >= 5:
                break
        result[symbol] = [asdict(r) for r in picked]
    return result


def build_seed_queue(main_audits: list[RowAudit], branch_audits: list[RowAudit]) -> dict[str, Any]:
    shortlist = capped_shortlist(main_audits, is_branch=False)
    b_short = capped_shortlist(branch_audits, is_branch=True)
    queue = {
        "main": [
            {
                "family": row["family"],
                "anchor": row["name"],
                "focus": "keep runtime anchor fixed; only explore one adjacent family bucket at a time",
            }
            for row in shortlist.get("main", [])
        ],
        "btc": [
            {
                "family": row["family"],
                "anchor": row["name"],
                "focus": "prefer breakout/event_drift/squeeze/dual; skip break_fail",
            }
            for row in b_short.get("btc", [])
        ],
        "eth": [
            {
                "family": row["family"],
                "anchor": row["name"],
                "focus": "prioritize drift + squeeze; keep one reclaim and one short track",
            }
            for row in b_short.get("eth", [])
        ],
        "sol": [
            {
                "family": row["family"],
                "anchor": row["name"],
                "focus": "long families first; keep one guarded short family only",
            }
            for row in b_short.get("sol", [])
        ],
    }
    return queue


def build_summary(main_audits: list[RowAudit], branch_audits: list[RowAudit]) -> dict[str, Any]:
    main_dom_family, main_dom_ratio, main_counts = dominant_ratio(main_audits, 8)
    branch_dom_family, branch_dom_ratio, branch_counts = dominant_ratio(branch_audits, 12)

    def count_if(audits: list[RowAudit], attr: str) -> int:
        return sum(1 for a in audits if getattr(a, attr))

    summary = {
        "main": {
            "rows": len(main_audits),
            "dead_recent_wf_zero": count_if(main_audits, "dead_recent_wf_zero"),
            "full_zero": count_if(main_audits, "full_zero"),
            "dominant_family": main_dom_family,
            "dominant_ratio": main_dom_ratio,
            "top8_family_counts": dict(main_counts),
        },
        "branch": {
            "rows": len(branch_audits),
            "dead_recent_wf_zero": count_if(branch_audits, "dead_recent_wf_zero"),
            "full_zero": count_if(branch_audits, "full_zero"),
            "dominant_family": branch_dom_family,
            "dominant_ratio": branch_dom_ratio,
            "top12_family_counts": dict(branch_counts),
            "symbol_counts": dict(Counter(a.symbol for a in branch_audits)),
        },
        "guard_gaps": count_if(main_audits + branch_audits, "missing_guard_fields"),
        "low_sample_high_pf": count_if(main_audits + branch_audits, "low_sample_high_pf"),
        "hard_blacklisted": count_if(main_audits + branch_audits, "hard_blacklisted"),
    }
    summary["system_ready_for_strategy_frontier"] = (
        summary["guard_gaps"] == 0
        and summary["main"]["full_zero"] == 0
        and summary["branch"]["full_zero"] == 0
        and summary["branch"]["dead_recent_wf_zero"] <= 1
        and summary["main"]["dominant_ratio"] <= 0.75
        and summary["branch"]["dominant_ratio"] <= 0.4
    )
    return summary


def render_txt(summary: dict[str, Any], shortlist: dict[str, Any], dead: dict[str, Any], seed_queue: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("Stage183 family-taxonomy + blacklist + seed frontier")
    lines.append("")
    lines.append("[summary]")
    lines.append(
        f"- main_rows={summary['main']['rows']} main_dead={summary['main']['dead_recent_wf_zero']} main_full_zero={summary['main']['full_zero']}"
    )
    lines.append(
        f"- main_dominant_family={summary['main']['dominant_family']} dominant_ratio={summary['main']['dominant_ratio']:.2f}"
    )
    lines.append(
        f"- branch_rows={summary['branch']['rows']} branch_dead={summary['branch']['dead_recent_wf_zero']} branch_full_zero={summary['branch']['full_zero']}"
    )
    lines.append(
        f"- branch_dominant_family={summary['branch']['dominant_family']} dominant_ratio={summary['branch']['dominant_ratio']:.2f}"
    )
    lines.append(f"- branch_symbol_counts={json.dumps(summary['branch']['symbol_counts'], ensure_ascii=False)}")
    lines.append(f"- guard_gaps={summary['guard_gaps']} low_sample_high_pf={summary['low_sample_high_pf']} hard_blacklisted={summary['hard_blacklisted']}")
    lines.append(f"- system_ready_for_strategy_frontier={summary['system_ready_for_strategy_frontier']}")
    lines.append("")

    for key in ["main", "btc", "eth", "sol"]:
        rows = shortlist.get(key, [])
        lines.append(f"[curated_{key}]")
        if not rows:
            lines.append("- none")
        for row in rows:
            lines.append(
                f"- {row['name']} | family={row['family']} | recent_monthly={row['recent_monthlyized']*100:.2f}% | wf_monthly={row['wf_monthlyized']*100:.2f}% | recent_trades={row['recent_trades']} | wf_trades={row['wf_trades']}"
            )
        lines.append("")

    lines.append("[hard_blacklist]")
    for row in dead.get("hard_blacklisted", []):
        lines.append(f"- {row['name']} | family={row['family']} | symbol={row['symbol']}")
    if not dead.get("hard_blacklisted"):
        lines.append("- none")
    lines.append("")

    lines.append("[seed_queue]")
    for key in ["main", "btc", "eth", "sol"]:
        lines.append(f"- {key}:")
        for row in seed_queue.get(key, []):
            lines.append(f"  - {row['anchor']} | family={row['family']} | focus={row['focus']}")
    lines.append("")
    lines.append("[next]")
    lines.append("- 主线不再把 ladder_pyramid / overlay_hold 都误记成同一家族")
    lines.append("- BTC break_fail 直接黑名单化；1笔高PF 假优先不再进 shortlist")
    lines.append("- Downloads 仍只保留 1 个可上传 zip")
    return "\n".join(lines) + "\n"


def write_zip(out_zip: Path, files: dict[str, str]) -> None:
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for name, content in files.items():
            p = root / name
            p.write_text(content, encoding="utf-8")
        with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for p in sorted(root.iterdir()):
                zf.write(p, arcname=p.name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--main-json", default="")
    parser.add_argument("--branch-json", default="")
    args = parser.parse_args()

    project_dir = Path(args.project_dir).expanduser().resolve()
    reports_dir = project_dir / "reports" / "research_raw"
    main_json = Path(args.main_json).expanduser() if args.main_json else reports_dir / "stage90_mainline_event_alpha_matrix_latest.json"
    branch_json = Path(args.branch_json).expanduser() if args.branch_json else reports_dir / "stage91_branch_event_alpha_matrix_latest.json"

    main_rows = load_rows(main_json, is_branch=False)
    branch_rows = load_rows(branch_json, is_branch=True)
    main_audits = audit_rows(main_rows, is_branch=False)
    branch_audits = audit_rows(branch_rows, is_branch=True)

    summary = build_summary(main_audits, branch_audits)
    shortlist: dict[str, Any] = {}
    shortlist.update(capped_shortlist(main_audits, is_branch=False))
    shortlist.update(capped_shortlist(branch_audits, is_branch=True))
    dead = {
        "hard_blacklisted": [asdict(r) for r in sorted([a for a in main_audits + branch_audits if a.hard_blacklisted], key=lambda x: (x.symbol, x.name))],
        "dead_recent_wf_zero": [asdict(r) for r in sorted([a for a in main_audits + branch_audits if a.dead_recent_wf_zero], key=lambda x: (x.symbol, x.name))],
        "low_sample_high_pf": [asdict(r) for r in sorted([a for a in main_audits + branch_audits if a.low_sample_high_pf], key=lambda x: (x.symbol, x.name))],
    }
    seed_queue = build_seed_queue(main_audits, branch_audits)
    txt = render_txt(summary, shortlist, dead, seed_queue)

    out_zip = project_dir.parent / "Downloads" / "stage183_family_taxonomy_blacklist_seed_frontier_latest.zip"
    files = {
        "stage183_family_taxonomy_blacklist_seed_frontier_latest.txt": txt,
        "stage183_summary_latest.json": json.dumps(summary, ensure_ascii=False, indent=2),
        "stage183_curated_shortlist_latest.json": json.dumps(shortlist, ensure_ascii=False, indent=2),
        "stage183_dead_blacklist_latest.json": json.dumps(dead, ensure_ascii=False, indent=2),
        "stage183_seed_queue_latest.json": json.dumps(seed_queue, ensure_ascii=False, indent=2),
    }
    write_zip(out_zip, files)
    print(str(out_zip))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
