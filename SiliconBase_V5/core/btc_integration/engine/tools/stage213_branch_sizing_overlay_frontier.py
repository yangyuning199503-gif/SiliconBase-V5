from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tools.stage46_aggressive_lab as s46
import tools.stage59_structural_lab as s59
import tools.stage211_future_event_runtime_bridge_frontier as s211
import tools.stage212_message_sizing_overlay_frontier as s212
from src.backtest.io import read_config

from tools import message_stack_backtest as msb
from tools import research_config_baseline as rcb

ASSET_WEIGHTS = {"btc": 0.25, "eth": 0.60, "sol": 0.15}
ASSETS = ["btc", "eth", "sol"]


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def _fmt_num(x: float) -> str:
    return f"{x:+.2f}"


def _geom_monthly(total_return: float, months: float) -> float:
    if months <= 0:
        return 0.0
    base = 1.0 + float(total_return)
    if base <= 0:
        return -1.0
    return float(base ** (1.0 / months) - 1.0)


def _trade_span_months(trades: pd.DataFrame) -> float:
    if trades is None or trades.empty:
        return 0.0
    start = pd.to_datetime(trades["entry_time_utc"], utc=True).min()
    end_col = "exit_time_utc" if "exit_time_utc" in trades.columns else "entry_time_utc"
    end = pd.to_datetime(trades[end_col], utc=True).max()
    days = max((end - start).total_seconds() / 86400.0, 1.0)
    return float(days / 30.4375)


def _load_stage91(project_dir: Path) -> dict[str, Any]:
    p = project_dir / "reports" / "research_raw" / "stage91_branch_event_alpha_matrix_latest.json"
    if not p.exists():
        raise FileNotFoundError(f"missing {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def _pick_rows(stage91: dict[str, Any]) -> list[dict[str, Any]]:
    rows = list(stage91.get("rows", []) or [])
    asset_summary = list(stage91.get("asset_summary", []) or [])
    rows_by_name = {str(r.get("name", "")): r for r in rows if str(r.get("name", ""))}
    selected_names: list[str] = []
    for item in asset_summary:
        for key in ["active", "long_best", "short_best", "dual_best"]:
            row = item.get(key)
            if isinstance(row, dict):
                name = str(row.get("name", ""))
                if name and name not in selected_names and name in rows_by_name:
                    selected_names.append(name)
    for sym in ASSETS:
        extras = [r for r in rows if str(r.get("symbol", "")).lower() == sym and str(r.get("name", "")) not in selected_names]
        extras.sort(key=lambda r: float(r.get("alpha_score", 0.0)), reverse=True)
        for r in extras[:2]:
            name = str(r.get("name", ""))
            if name and name not in selected_names:
                selected_names.append(name)
    selected = [rows_by_name[n] for n in selected_names if n in rows_by_name]
    selected.sort(key=lambda r: (ASSET_WEIGHTS.get(str(r.get("symbol", "")).lower(), 0.0), float(r.get("alpha_score", 0.0))), reverse=True)
    return selected


def _candidate_cfg(root: Path, row: dict[str, Any]) -> dict[str, Any]:
    cfg = copy.deepcopy(rcb.load_research_base_config(root))
    sym = str(row.get("symbol", "")).lower()
    cfg.setdefault("data", {})["symbols"] = [sym]
    cfg.setdefault("data", {})["weights"] = {sym: 1.0}
    cfg.setdefault("filters", {})["macro_gate_symbols"] = [sym]
    cfg.setdefault("filters", {})["macro_gate_reference_symbol"] = sym
    return cfg


def _rebuild_candidate_trades(root: Path, row: dict[str, Any]) -> pd.DataFrame:
    cfg = _candidate_cfg(root, row)
    data = s46._load_portfolio_data(root, cfg)
    trades, _ = s59._run_portfolio_candidate(root, cfg, data, row.get("mods", {}) or {})
    if trades is None or trades.empty:
        return pd.DataFrame(columns=["entry_time_utc", "pnl", "symbol", "side", "qty"])
    return trades.copy()


def _branch_variants() -> list[dict[str, Any]]:
    return [
        {
            "name": "branch_balance_t018",
            "event_weight": 0.60,
            "deriv_weight": 0.40,
            "phase_weights": {"pre": 0.18, "release": 0.98, "drift": 0.68, "decay": 0.20},
            "boost_soft_thr": 0.12,
            "boost_mid_thr": 0.18,
            "cut_soft_thr": 0.16,
            "cut_mid_thr": 0.25,
            "boost_soft_scale": 1.10,
            "boost_mid_scale": 1.24,
            "cut_soft_scale": 0.82,
            "cut_mid_scale": 0.60,
            "net_boost_floor": 0.03,
            "net_cut_floor": -0.04,
            "boost_soft_asset_thresholds": {"btc": 0.15, "eth": 0.10, "sol": 0.12},
            "boost_mid_asset_thresholds": {"btc": 0.23, "eth": 0.15, "sol": 0.18},
            "cut_soft_asset_thresholds": {"btc": 0.18, "eth": 0.15, "sol": 0.17},
            "cut_mid_asset_thresholds": {"btc": 0.28, "eth": 0.22, "sol": 0.25},
        },
        {
            "name": "branch_eth_aggr_t013",
            "event_weight": 0.62,
            "deriv_weight": 0.38,
            "phase_weights": {"pre": 0.16, "release": 1.00, "drift": 0.74, "decay": 0.22},
            "boost_soft_thr": 0.10,
            "boost_mid_thr": 0.16,
            "cut_soft_thr": 0.17,
            "cut_mid_thr": 0.26,
            "boost_soft_scale": 1.12,
            "boost_mid_scale": 1.30,
            "cut_soft_scale": 0.84,
            "cut_mid_scale": 0.62,
            "net_boost_floor": 0.02,
            "net_cut_floor": -0.05,
            "boost_soft_asset_thresholds": {"btc": 0.16, "eth": 0.08, "sol": 0.13},
            "boost_mid_asset_thresholds": {"btc": 0.24, "eth": 0.13, "sol": 0.19},
            "cut_soft_asset_thresholds": {"btc": 0.19, "eth": 0.16, "sol": 0.18},
            "cut_mid_asset_thresholds": {"btc": 0.30, "eth": 0.23, "sol": 0.26},
        },
        {
            "name": "branch_systemic_cut_t021",
            "event_weight": 0.65,
            "deriv_weight": 0.35,
            "phase_weights": {"pre": 0.20, "release": 1.00, "drift": 0.70, "decay": 0.26},
            "boost_soft_thr": 0.14,
            "boost_mid_thr": 0.22,
            "cut_soft_thr": 0.15,
            "cut_mid_thr": 0.22,
            "boost_soft_scale": 1.08,
            "boost_mid_scale": 1.18,
            "cut_soft_scale": 0.80,
            "cut_mid_scale": 0.56,
            "net_boost_floor": 0.04,
            "net_cut_floor": -0.03,
            "boost_soft_asset_thresholds": {"btc": 0.18, "eth": 0.12, "sol": 0.14},
            "boost_mid_asset_thresholds": {"btc": 0.26, "eth": 0.18, "sol": 0.20},
            "cut_soft_asset_thresholds": {"btc": 0.16, "eth": 0.14, "sol": 0.15},
            "cut_mid_asset_thresholds": {"btc": 0.23, "eth": 0.20, "sol": 0.21},
        },
        {
            "name": "branch_preserve_t024",
            "event_weight": 0.56,
            "deriv_weight": 0.44,
            "phase_weights": {"pre": 0.16, "release": 0.90, "drift": 0.56, "decay": 0.16},
            "boost_soft_thr": 0.16,
            "boost_mid_thr": 0.24,
            "cut_soft_thr": 0.18,
            "cut_mid_thr": 0.28,
            "boost_soft_scale": 1.08,
            "boost_mid_scale": 1.18,
            "cut_soft_scale": 0.86,
            "cut_mid_scale": 0.66,
            "net_boost_floor": 0.04,
            "net_cut_floor": -0.04,
            "boost_soft_asset_thresholds": {"btc": 0.18, "eth": 0.13, "sol": 0.15},
            "boost_mid_asset_thresholds": {"btc": 0.28, "eth": 0.20, "sol": 0.22},
            "cut_soft_asset_thresholds": {"btc": 0.20, "eth": 0.17, "sol": 0.19},
            "cut_mid_asset_thresholds": {"btc": 0.30, "eth": 0.24, "sol": 0.26},
        },
    ]


def _wf_branch(trades: pd.DataFrame, windows: pd.DataFrame, initial_equity: float, variant: dict[str, Any]) -> dict[str, Any]:
    years = sorted(pd.to_datetime(trades["entry_time_utc"], utc=True).dt.year.unique().tolist())
    folds: list[dict[str, Any]] = []
    agg_pnl = 0.0
    agg_dd = 0.0
    pos = 0
    retained: list[float] = []
    for year in years:
        fold = trades[pd.to_datetime(trades["entry_time_utc"], utc=True).dt.year == year].copy()
        if fold.empty:
            continue
        ev = s212._apply_variant(fold, windows, variant, initial_equity)
        gm = ev["gated"]
        agg_pnl += float(ev["pnl_delta"])
        agg_dd += float(ev["dd_delta"])
        retained.append(float(ev["retained_notional_ratio"]))
        if float(gm.get("total_return", 0.0)) > 0:
            pos += 1
        folds.append({
            "year": int(year),
            "ret": float(gm.get("total_return", 0.0)),
            "pf": float(gm.get("profit_factor", 0.0)),
            "maxdd": float(gm.get("max_drawdown", 0.0)),
            "trades": int(gm.get("trades", 0) or 0),
            "pnl_delta": float(ev["pnl_delta"]),
            "dd_delta": float(ev["dd_delta"]),
        })
    avg_ret = float(np.mean([x["ret"] for x in folds])) if folds else 0.0
    avg_pf = float(np.mean([x["pf"] for x in folds])) if folds else 0.0
    avg_dd = float(np.mean([x["maxdd"] for x in folds])) if folds else 0.0
    avg_trades = float(np.mean([x["trades"] for x in folds])) if folds else 0.0
    return {
        "folds": folds,
        "aggregate_pnl_delta": float(agg_pnl),
        "aggregate_dd_delta": float(agg_dd),
        "avg_ret": avg_ret,
        "avg_pf": avg_pf,
        "avg_maxdd": avg_dd,
        "avg_trades": avg_trades,
        "positive_folds": int(pos),
        "total_folds": int(len(folds)),
        "avg_retained": float(np.mean(retained)) if retained else 1.0,
    }


def _candidate_eval(root: Path, row: dict[str, Any], hist: dict[str, Any], initial_equity: float) -> dict[str, Any]:
    trades = _rebuild_candidate_trades(root, row)
    oi_df = msb._parse_oi_df(hist.get("oi_agg_btc_1d", {}))
    lsr_df = msb._parse_lsr_df(hist.get("lsr_btcusdt_binance_4h", {}))
    taker_df = msb._parse_taker_df(hist.get("taker_btcusdt_binance_4h", {}))
    trades = msb._attach_features(trades, oi_df, lsr_df, taker_df)
    if trades.empty:
        return {
            "candidate": row,
            "baseline": {"trades": 0, "profit_factor": 0.0, "total_return": 0.0, "max_drawdown": 0.0, "monthlyized": 0.0},
            "recent2y": {"trades": 0, "profit_factor": 0.0, "total_return": 0.0, "max_drawdown": 0.0, "monthlyized": 0.0},
            "best": None,
        }
    start_utc = pd.to_datetime(trades["entry_time_utc"], utc=True).min().floor("15min")
    end_utc = pd.to_datetime(trades["entry_time_utc"], utc=True).max().ceil("15min")
    windows = msb._load_event_windows(root, start_utc, end_utc, include_all_modes=True)
    recent = s212._two_year_slice(trades)
    base_full = msb._trade_metrics(trades, initial_equity)
    base_full["monthlyized"] = _geom_monthly(base_full["total_return"], _trade_span_months(trades))
    base_recent = msb._trade_metrics(recent, initial_equity)
    base_recent["monthlyized"] = _geom_monthly(base_recent["total_return"], _trade_span_months(recent))

    scored: list[dict[str, Any]] = []
    for variant in _branch_variants():
        full_ev = s212._apply_variant(trades, windows, variant, initial_equity)
        recent_ev = s212._apply_variant(recent, windows, variant, initial_equity) if not recent.empty else {
            "gated": {"trades": 0, "profit_factor": 0.0, "total_return": 0.0, "max_drawdown": 0.0},
            "pnl_delta": 0.0,
            "dd_delta": 0.0,
            "score": 0.0,
            "boost_soft": 0,
            "boost_mid": 0,
            "cut_soft": 0,
            "cut_mid": 0,
            "retained_notional_ratio": 1.0,
            "phase_hits": {"pre": 0, "release": 0, "drift": 0, "decay": 0},
            "top_event_groups": [],
        }
        wf = _wf_branch(trades, windows, initial_equity, variant)
        gm_full = dict(full_ev["gated"])
        gm_full["monthlyized"] = _geom_monthly(gm_full["total_return"], _trade_span_months(trades))
        gm_r2 = dict(recent_ev["gated"])
        gm_r2["monthlyized"] = _geom_monthly(gm_r2["total_return"], _trade_span_months(recent))
        wf_score = float(
            wf["aggregate_pnl_delta"] / initial_equity
            + 2.0 * wf["aggregate_dd_delta"]
            + 0.12 * wf["avg_ret"]
            + 0.08 * wf["avg_pf"]
            - 0.012 * abs(wf["avg_retained"] - 1.0)
        )
        composite = float(0.30 * full_ev["score"] + 1.15 * recent_ev["score"] + 0.95 * wf_score + 0.22 * gm_r2["monthlyized"])
        scored.append({
            "name": variant["name"],
            "params": variant,
            "full": full_ev,
            "recent2y": recent_ev,
            "wf": wf,
            "gated_metrics_full": gm_full,
            "gated_metrics_recent2y": gm_r2,
            "composite_score": composite,
            "top_event_groups": full_ev["top_event_groups"],
        })
    scored.sort(key=lambda x: (x["composite_score"], x["recent2y"]["score"], x["full"]["score"]), reverse=True)
    return {
        "candidate": row,
        "baseline": base_full,
        "recent2y": base_recent,
        "best": scored[0] if scored else None,
        "top_variants": scored[:4],
    }


def run(project_dir: Path, out_txt: Path, out_json: Path) -> None:
    cfg = read_config(project_dir / "config.yml")
    initial_equity = float(cfg.get("portfolio", {}).get("initial_equity", 100000.0))
    stage91 = _load_stage91(project_dir)
    selected = _pick_rows(stage91)
    hist = msb._load_or_fetch_history(project_dir, refresh=False)
    candidate_results = [_candidate_eval(project_dir, row, hist, initial_equity) for row in selected]

    aggregate_rows: dict[str, dict[str, Any]] = {}
    for cr in candidate_results:
        best = cr.get("best")
        row = cr["candidate"]
        sym = str(row.get("symbol", "")).lower()
        if not best:
            continue
        bucket = aggregate_rows.setdefault(best["name"], {
            "name": best["name"],
            "weighted_score": 0.0,
            "weighted_recent_monthly": 0.0,
            "weighted_recent_ret": 0.0,
            "weighted_recent_pf": 0.0,
            "weighted_full_ret": 0.0,
            "weighted_full_pf": 0.0,
            "weighted_wf_pnl_delta": 0.0,
            "weighted_retain": 0.0,
            "members": [],
        })
        w = float(ASSET_WEIGHTS.get(sym, 0.0))
        gm_full = best["gated_metrics_full"]
        gm_r2 = best["gated_metrics_recent2y"]
        wf = best["wf"]
        bucket["weighted_score"] += w * float(best["composite_score"])
        bucket["weighted_recent_monthly"] += w * float(gm_r2.get("monthlyized", 0.0))
        bucket["weighted_recent_ret"] += w * float(gm_r2.get("total_return", 0.0))
        bucket["weighted_recent_pf"] += w * float(gm_r2.get("profit_factor", 0.0))
        bucket["weighted_full_ret"] += w * float(gm_full.get("total_return", 0.0))
        bucket["weighted_full_pf"] += w * float(gm_full.get("profit_factor", 0.0))
        bucket["weighted_wf_pnl_delta"] += w * float(wf.get("aggregate_pnl_delta", 0.0))
        bucket["weighted_retain"] += w * float(best["full"].get("retained_notional_ratio", 1.0))
        bucket["members"].append({
            "symbol": sym,
            "candidate": str(row.get("name", "")),
            "family": str(row.get("family", "")),
        })
    variant_leaderboard = sorted(aggregate_rows.values(), key=lambda x: (x["weighted_score"], x["weighted_recent_monthly"]), reverse=True)
    recommended_variant = variant_leaderboard[0] if variant_leaderboard else None

    now_utc = pd.Timestamp.now(tz="UTC")
    live_calendar, cal_mode = s211._standardize_calendar_live(project_dir, now_utc)
    live_news, news_mode = s211._standardize_news_live(project_dir, now_utc)
    live_calendar = s211._attach_asset_scores(live_calendar, "calendar")
    live_news = s211._attach_asset_scores(live_news, "news")

    lines: list[str] = []
    lines.append("Stage213 branch sizing overlay frontier")
    lines.append("")
    lines.append("[model]")
    lines.append("- 分支继续：技术面决定 entry；消息面/事件面只做加仓/减仓 sizing overlay。")
    lines.append("- 当前只评估 BTC/ETH/SOL 分支候选，不动主线 entry，也不把消息层升成 veto。")
    lines.append("- 目标：把 stage212 的 sizing overlay 迁到 branch，并按币种分权。")
    lines.append("")
    lines.append("[selected_candidates]")
    for row in selected:
        lines.append(f"- {str(row.get('symbol','')).upper()} | {row.get('family','')} | {row.get('name','')} | decision={row.get('decision','-')} | alpha_score={float(row.get('alpha_score',0.0)):+.2f}")
    lines.append("")
    lines.append("[top_variant_by_candidate]")
    for cr in candidate_results:
        row = cr["candidate"]
        base = cr["baseline"]
        base2 = cr["recent2y"]
        best = cr.get("best")
        if not best:
            lines.append(f"- {row.get('name','')} | no_result")
            continue
        gm_full = best["gated_metrics_full"]
        gm_r2 = best["gated_metrics_recent2y"]
        wf = best["wf"]
        lines.append(
            f"- {str(row.get('symbol','')).upper()} | {row.get('name','')} | best={best['name']} | full ret={_fmt_pct(gm_full['total_return'])} month={_fmt_pct(gm_full['monthlyized'])} pf={gm_full['profit_factor']:.3f} dd={_fmt_pct(gm_full['max_drawdown'])} | delta={_fmt_num(best['full']['pnl_delta'])} retain={_fmt_pct(best['full']['retained_notional_ratio'])}"
        )
        lines.append(
            f"  baseline_full: ret={_fmt_pct(base['total_return'])} month={_fmt_pct(base['monthlyized'])} pf={base['profit_factor']:.3f} dd={_fmt_pct(base['max_drawdown'])} trades={base['trades']}"
        )
        lines.append(
            f"  sized_2y: ret={_fmt_pct(gm_r2['total_return'])} month={_fmt_pct(gm_r2['monthlyized'])} pf={gm_r2['profit_factor']:.3f} dd={_fmt_pct(gm_r2['max_drawdown'])} trades={gm_r2['trades']} | baseline_2y={_fmt_pct(base2['total_return'])}"
        )
        lines.append(
            f"  wf_proxy: pnl_delta={_fmt_num(wf['aggregate_pnl_delta'])} avg_ret={_fmt_pct(wf['avg_ret'])} avg_pf={wf['avg_pf']:.3f} pos={wf['positive_folds']}/{wf['total_folds']} | top_groups={'; '.join(best['top_event_groups'][:4]) if best['top_event_groups'] else '-'}"
        )
    lines.append("")
    lines.append("[variant_leaderboard]")
    for v in variant_leaderboard[:4]:
        lines.append(
            f"- {v['name']} | weighted_score={v['weighted_score']:+.4f} | weighted_2y_month={_fmt_pct(v['weighted_recent_monthly'])} weighted_2y_ret={_fmt_pct(v['weighted_recent_ret'])} weighted_2y_pf={v['weighted_recent_pf']:.3f} | weighted_wf_pnl_delta={_fmt_num(v['weighted_wf_pnl_delta'])} | weighted_retain={_fmt_pct(v['weighted_retain'])}"
        )
    lines.append("")
    lines.append("[live_bridge_status]")
    lines.append(f"- calendar_mode={cal_mode} | standardized_events={len(live_calendar)}")
    lines.append(f"- news_mode={news_mode} | standardized_messages={len(live_news)}")
    lines.append("- live bridge 继续只做 sizing overlay，不改 entry gate。")
    lines.append("")
    lines.append("[top_news_by_asset]")
    for asset in ASSETS:
        rows = s211._pick_asset_top(live_news, asset, 2)
        if not rows:
            lines.append(f"- {asset}: none")
            continue
        for row in rows:
            ts = row.get("release_utc") or row.get("publish_utc")
            lines.append(f"- {asset} | {ts} | {row.get('source','')} | {row.get('event_class','')} | {row.get('severity','')} | score={row.get(f'score_{asset}',0.0):.3f} | {row.get('title','')}")
    lines.append("")
    lines.append("[conclusion]")
    if recommended_variant:
        lines.append(f"- 推荐先用 {recommended_variant['name']} 做分支 sizing overlay 基线。")
        lines.append("- 原因：按 BTC/ETH/SOL 权重汇总后，近2年月化/收益与 WF 代理增量最平衡。")
    else:
        lines.append("- 推荐=none")
    lines.append("- 下一步只做一件事：把推荐 variant 同步成 branch runtime 的仓位覆盖预览，不改 entry。")

    out_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    out_json.write_text(json.dumps({
        "recommended_variant": recommended_variant,
        "candidate_results": candidate_results,
        "variant_leaderboard": variant_leaderboard,
        "live_bridge": {
            "calendar_mode": cal_mode,
            "standardized_events": int(len(live_calendar)),
            "news_mode": news_mode,
            "standardized_messages": int(len(live_news)),
        },
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--out-txt", default=None)
    ap.add_argument("--out-json", default=None)
    args = ap.parse_args()
    root = Path(args.project_dir).expanduser().resolve()
    out_txt = Path(args.out_txt) if args.out_txt else root / "reports" / "research_raw" / "stage213_branch_sizing_overlay_frontier_latest.txt"
    out_json = Path(args.out_json) if args.out_json else root / "reports" / "research_raw" / "stage213_branch_sizing_overlay_frontier_latest.json"
    out_txt.parent.mkdir(parents=True, exist_ok=True)
    run(root, out_txt, out_json)


if __name__ == "__main__":
    main()
