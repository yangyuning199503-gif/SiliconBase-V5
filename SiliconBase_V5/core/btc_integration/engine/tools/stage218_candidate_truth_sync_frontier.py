from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest.io import read_config

from tools import message_stack_backtest as msb
from tools import stage212_message_sizing_overlay_frontier as s212
from tools import stage217_multiregime_broadfront_frontier as s217

FULL_RET_TOL = 0.08
RECENT_RET_TOL = 0.10
RECENT_PF_TOL = 1.40
RECENT_TRADES_TOL = 40

ASSET_PLAN = {
    "eth": {"long": 3, "short": 2, "dual": 1},
    "btc": {"long": 2, "short": 2, "dual": 1},
    "sol": {"long": 2, "short": 1, "dual": 1},
}


def _fmt_pct(x: float) -> str:
    return f"{float(x) * 100:.2f}%"


def _metric_pack(m: dict[str, Any]) -> dict[str, Any]:
    return {
        "ret": float(m.get("ret", 0.0) or 0.0),
        "pf": float(m.get("pf", 0.0) or 0.0),
        "dd": float(m.get("maxdd", 0.0) or 0.0),
        "trades": int(m.get("trades", 0) or 0),
        "monthlyized": float(m.get("monthlyized_ret", 0.0) or 0.0),
    }


def _dominant_gate_row(row: dict[str, Any]) -> dict[str, Any]:
    dom = str(row.get("dominant_gate", "") or "")
    gate_rows = list(row.get("gate_rows", []) or [])
    for g in gate_rows:
        if str(g.get("gate_name", "") or "") == dom:
            return g
    return gate_rows[0] if gate_rows else {}


def _truth_metrics(row: dict[str, Any]) -> dict[str, Any]:
    gate_row = _dominant_gate_row(row)
    full = _metric_pack(gate_row.get("metrics") or row.get("full_metrics") or {})
    recent = _metric_pack(gate_row.get("recent_metrics") or {})
    wf_block = (gate_row.get("walkforward") or {})
    wf = _metric_pack(wf_block.get("metrics") or {})
    wf["positive_folds"] = int(wf_block.get("positive_folds", 0) or 0)
    wf["total_folds"] = int(wf_block.get("total_folds", 0) or 0)
    return {"full": full, "recent2y": recent, "wf": wf}


def _rebuild_baseline(project_dir: Path, row: dict[str, Any], initial_equity: float) -> dict[str, Any]:
    trades = s217._rebuild_candidate_trades(project_dir, row)
    if trades is not None and not trades.empty:
        trades = trades.copy()
        if "entry_time_utc" not in trades.columns and "entry_time" in trades.columns:
            trades["entry_time_utc"] = pd.to_datetime(trades["entry_time"], utc=True, errors="coerce")
        if "exit_time_utc" not in trades.columns and "exit_time" in trades.columns:
            trades["exit_time_utc"] = pd.to_datetime(trades["exit_time"], utc=True, errors="coerce")
    if trades is None or trades.empty:
        return {
            "full": {"ret": 0.0, "pf": 0.0, "dd": 0.0, "trades": 0, "monthlyized": 0.0},
            "recent2y": {"ret": 0.0, "pf": 0.0, "dd": 0.0, "trades": 0, "monthlyized": 0.0},
        }
    full = msb._trade_metrics(trades, initial_equity)
    full = {
        "ret": float(full.get("total_return", 0.0) or 0.0),
        "pf": float(full.get("profit_factor", 0.0) or 0.0),
        "dd": float(full.get("max_drawdown", 0.0) or 0.0),
        "trades": int(full.get("trades", 0) or 0),
        "monthlyized": s217._geom_monthly(float(full.get("total_return", 0.0) or 0.0), max(s217._trade_span_months(trades), 12.0)),
    }
    recent = s212._two_year_slice(trades)
    recent_m = msb._trade_metrics(recent, initial_equity)
    recent2y = {
        "ret": float(recent_m.get("total_return", 0.0) or 0.0),
        "pf": float(recent_m.get("profit_factor", 0.0) or 0.0),
        "dd": float(recent_m.get("max_drawdown", 0.0) or 0.0),
        "trades": int(recent_m.get("trades", 0) or 0),
        "monthlyized": s217._geom_monthly(float(recent_m.get("total_return", 0.0) or 0.0), 24.0 if not recent.empty else 0.0),
    }
    return {"full": full, "recent2y": recent2y}


def _truth_sync_eval(truth: dict[str, Any], rebuilt: dict[str, Any]) -> dict[str, Any]:
    full_ret_diff = float(rebuilt["full"]["ret"] - truth["full"]["ret"])
    recent_ret_diff = float(rebuilt["recent2y"]["ret"] - truth["recent2y"]["ret"])
    recent_pf_diff = float(rebuilt["recent2y"]["pf"] - truth["recent2y"]["pf"])
    recent_trades_diff = int(rebuilt["recent2y"]["trades"] - truth["recent2y"]["trades"])
    ok = (
        abs(full_ret_diff) <= FULL_RET_TOL
        and abs(recent_ret_diff) <= RECENT_RET_TOL
        and abs(recent_pf_diff) <= RECENT_PF_TOL
        and abs(recent_trades_diff) <= RECENT_TRADES_TOL
    )
    return {
        "ok": bool(ok),
        "full_ret_diff": full_ret_diff,
        "recent_ret_diff": recent_ret_diff,
        "recent_pf_diff": recent_pf_diff,
        "recent_trades_diff": int(recent_trades_diff),
    }


def _truth_score(row: dict[str, Any], truth: dict[str, Any]) -> float:
    leg = s217._infer_leg(row)
    recent = truth["recent2y"]
    wf = truth["wf"]
    full = truth["full"]
    recent_pf = min(max(recent["pf"], 0.0), 6.0)
    wf_pf = min(max(wf["pf"], 0.0), 6.0)
    full_pf = min(max(full["pf"], 0.0), 4.0)
    score = (
        1.45 * recent["monthlyized"]
        + 1.15 * wf["monthlyized"]
        + 0.08 * recent_pf
        + 0.05 * wf_pf
        + 0.02 * full_pf
        - 0.14 * max(0.0, -full["monthlyized"])
        - 0.05 * max(0.0, -recent["ret"])
        - 0.015 * abs(recent["dd"])
        - 0.010 * abs(wf["dd"])
        + 0.002 * min(recent["trades"], 40) / 40.0
    )
    if leg == "dual":
        score += 0.012
    if leg == "short":
        score += 0.006
    return float(score)


def _build_asset_plan(selected_rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    plan: dict[str, list[dict[str, Any]]] = {k: [] for k in ASSET_PLAN}
    for sym in ASSET_PLAN:
        bag = [r for r in selected_rows if str(r.get("symbol", "")).lower() == sym]
        by_leg: dict[str, list[dict[str, Any]]] = {"long": [], "short": [], "dual": []}
        for r in bag:
            by_leg.setdefault(s217._infer_leg(r), []).append(r)
        for leg, keep in ASSET_PLAN[sym].items():
            for r in by_leg.get(leg, [])[:keep]:
                plan[sym].append(r)
    return plan


def run(project_dir: Path, out_txt: Path, out_json: Path) -> None:
    cfg = read_config(project_dir / "config.yml")
    initial_equity = float(cfg.get("portfolio", {}).get("initial_equity", 100000.0))
    stage91 = s217._load_stage91(project_dir)
    selected = s217._pick_rows(stage91)

    candidate_audits: list[dict[str, Any]] = []
    truth_ok_rows: list[dict[str, Any]] = []
    for row in selected:
        truth = _truth_metrics(row)
        rebuilt = _rebuild_baseline(project_dir, row, initial_equity)
        sync = _truth_sync_eval(truth, rebuilt)
        score = _truth_score(row, truth)
        audit = {
            "candidate": row,
            "truth": truth,
            "rebuilt": rebuilt,
            "truth_sync": sync,
            "truth_score": score,
        }
        candidate_audits.append(audit)
        row["truth_score"] = score
        row["truth_sync_ok"] = sync["ok"]
        if sync["ok"]:
            truth_ok_rows.append(row)

    truth_ranked = sorted(candidate_audits, key=lambda x: (x["truth_score"], x["truth"]["recent2y"]["monthlyized"], x["truth"]["wf"]["monthlyized"]), reverse=True)
    truth_ok_ranked = [a for a in truth_ranked if a["truth_sync"]["ok"]]
    asset_plan = _build_asset_plan([a["candidate"] for a in truth_ok_ranked] if truth_ok_ranked else [a["candidate"] for a in truth_ranked])

    live_bridge = {}
    try:
        now_utc = pd.Timestamp.now(tz="UTC")
        live_calendar, cal_mode = s217.s211._standardize_calendar_live(project_dir, now_utc)
        live_news, news_mode = s217.s211._standardize_news_live(project_dir, now_utc)
        live_bridge = {
            "calendar_mode": cal_mode,
            "standardized_events": int(len(live_calendar)),
            "news_mode": news_mode,
            "standardized_messages": int(len(live_news)),
        }
    except Exception as exc:
        live_bridge = {"error": str(exc)}

    lines: list[str] = []
    lines.append("Stage218 candidate truth sync frontier")
    lines.append("")
    lines.append("[core_rule]")
    lines.append("- stage217 的 broadfront 方向保留，但先修 truth sync。")
    lines.append("- 6年必报，但排序先看近2年 + WF；overlay 结论必须建立在候选真值对齐之后。")
    lines.append("- 若 stage91 真值 与 stage218 重建口径明显漂移，本轮不允许用该结果砍路径。")
    lines.append("")
    lines.append("[truth_sync_audit]")
    for audit in truth_ranked:
        row = audit["candidate"]
        truth = audit["truth"]
        rebuilt = audit["rebuilt"]
        sync = audit["truth_sync"]
        lines.append(
            f"- {str(row.get('symbol','')).upper()} | leg={s217._infer_leg(row)} | {row.get('name','')} | truth_sync={'PASS' if sync['ok'] else 'FAIL'} | truth_2y={_fmt_pct(truth['recent2y']['ret'])} / {truth['recent2y']['pf']:.3f} / trades={truth['recent2y']['trades']} | rebuilt_2y={_fmt_pct(rebuilt['recent2y']['ret'])} / {rebuilt['recent2y']['pf']:.3f} / trades={rebuilt['recent2y']['trades']} | diff_ret={_fmt_pct(sync['recent_ret_diff'])} diff_pf={sync['recent_pf_diff']:+.3f}"
        )
        lines.append(
            f"  truth_full={_fmt_pct(truth['full']['ret'])} / {truth['full']['pf']:.3f} | rebuilt_full={_fmt_pct(rebuilt['full']['ret'])} / {rebuilt['full']['pf']:.3f} | diff_full={_fmt_pct(sync['full_ret_diff'])} | truth_WF={_fmt_pct(truth['wf']['ret'])} / {truth['wf']['pf']:.3f} pos={truth['wf'].get('positive_folds',0)}/{truth['wf'].get('total_folds',0)} | truth_score={audit['truth_score']:+.4f}"
        )
    lines.append("")
    lines.append("[asset_priority_from_truth]")
    for sym in ["eth", "btc", "sol"]:
        lines.append(f"- {sym.upper()}")
        sub = [a for a in truth_ranked if str(a['candidate'].get('symbol','')).lower() == sym]
        for audit in sub[:5]:
            row = audit["candidate"]
            truth = audit["truth"]
            lines.append(
                f"  - {s217._infer_leg(row)} | {row.get('name','')} | 6年={_fmt_pct(truth['full']['ret'])} | 近2年={_fmt_pct(truth['recent2y']['ret'])} 月化={_fmt_pct(truth['recent2y']['monthlyized'])} PF={truth['recent2y']['pf']:.3f} | WF={_fmt_pct(truth['wf']['ret'])} 月化={_fmt_pct(truth['wf']['monthlyized'])} PF={truth['wf']['pf']:.3f} | sync={'PASS' if audit['truth_sync']['ok'] else 'FAIL'}"
            )
    lines.append("")
    lines.append("[frontier_plan]")
    for sym in ["eth", "btc", "sol"]:
        picks = asset_plan.get(sym, [])
        if not picks:
            lines.append(f"- {sym.upper()}: none")
            continue
        lines.append(f"- {sym.upper()}:")
        for row in picks:
            lines.append(f"  - {s217._infer_leg(row)} | {row.get('name','')} | decision={row.get('decision','-')} | truth_score={float(row.get('truth_score',0.0)):+.4f}")
    lines.append("")
    lines.append("[live_bridge_status]")
    if live_bridge.get("error"):
        lines.append(f"- live_bridge_error={live_bridge['error']}")
    else:
        lines.append(f"- calendar_mode={live_bridge.get('calendar_mode')} | standardized_events={live_bridge.get('standardized_events')} | news_mode={live_bridge.get('news_mode')} | standardized_messages={live_bridge.get('standardized_messages')}")
    lines.append("")
    lines.append("[conclusion]")
    pass_count = sum(1 for a in candidate_audits if a['truth_sync']['ok'])
    fail_count = len(candidate_audits) - pass_count
    lines.append(f"- truth_sync: pass={pass_count} fail={fail_count}")
    if fail_count > 0:
        lines.append("- 这轮不采信 stage217 的 overlay 排名去砍路径，也不把它同步到 branch runtime。")
        lines.append("- 下一步先修 candidate trade truth：让 stage91 真值、重建 trades、frontier 评分三套口径一致。")
    else:
        lines.append("- truth sync 已通过，后续才允许继续做 asset-first overlay / entry frontier。")
    lines.append("- 这轮只输出真值审计和多资产下一步种子，不改 demo。")

    out_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    out_json.write_text(json.dumps({
        "candidate_audits": candidate_audits,
        "asset_plan": asset_plan,
        "live_bridge": live_bridge,
        "truth_sync_pass": pass_count,
        "truth_sync_fail": fail_count,
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-dir", required=True)
    ap.add_argument("--out-txt", required=True)
    ap.add_argument("--out-json", required=True)
    args = ap.parse_args()
    run(Path(args.project_dir).resolve(), Path(args.out_txt).resolve(), Path(args.out_json).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
