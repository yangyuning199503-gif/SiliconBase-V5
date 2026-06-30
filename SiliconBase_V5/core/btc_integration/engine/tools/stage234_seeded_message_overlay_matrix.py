
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tools.message_stack_backtest as msb
import tools.stage212_message_sizing_overlay_frontier as s212
import tools.stage231_seeded_confirmation_matrix as s231

SEEDS = [s for s in s231.SEED_LANES if s.get("role") == "engine"]

OVERLAY_VARIANTS: list[dict[str, Any]] = [
    {
        "name": "balanced_dual_perspective_t014",
        "perspective": "balanced",
        "event_weight": 0.55,
        "deriv_weight": 0.45,
        "phase_weights": {"pre": 0.18, "release": 0.95, "drift": 0.66, "decay": 0.18},
        "boost_soft_thr": 0.12, "boost_mid_thr": 0.18,
        "cut_soft_thr": 0.16, "cut_mid_thr": 0.24,
        "wait_thr": 0.44, "wait_net_floor": -0.16,
        "net_boost_floor": 0.03, "net_cut_floor": -0.04,
        "boost_soft_scale": 1.10, "boost_mid_scale": 1.22,
        "cut_soft_scale": 0.82, "cut_mid_scale": 0.58,
        "boost_soft_asset_thresholds": {"btc": 0.15, "bnb": 0.11, "eth": 0.12, "sol": 0.12},
        "boost_mid_asset_thresholds": {"btc": 0.23, "bnb": 0.17, "eth": 0.18, "sol": 0.18},
        "cut_soft_asset_thresholds": {"btc": 0.17, "bnb": 0.14, "eth": 0.15, "sol": 0.15},
        "cut_mid_asset_thresholds": {"btc": 0.27, "bnb": 0.22, "eth": 0.23, "sol": 0.23},
    },
    {
        "name": "institution_crowding_asym_t016",
        "perspective": "institution",
        "event_weight": 0.42,
        "deriv_weight": 0.58,
        "phase_weights": {"pre": 0.14, "release": 0.85, "drift": 0.52, "decay": 0.14},
        "boost_soft_thr": 0.14, "boost_mid_thr": 0.22,
        "cut_soft_thr": 0.14, "cut_mid_thr": 0.20,
        "wait_thr": 0.38, "wait_net_floor": -0.12,
        "net_boost_floor": 0.05, "net_cut_floor": -0.03,
        "boost_soft_scale": 1.08, "boost_mid_scale": 1.18,
        "cut_soft_scale": 0.78, "cut_mid_scale": 0.48,
        "boost_soft_asset_thresholds": {"btc": 0.17, "bnb": 0.13, "eth": 0.14, "sol": 0.14},
        "boost_mid_asset_thresholds": {"btc": 0.25, "bnb": 0.19, "eth": 0.21, "sol": 0.21},
        "cut_soft_asset_thresholds": {"btc": 0.16, "bnb": 0.13, "eth": 0.13, "sol": 0.14},
        "cut_mid_asset_thresholds": {"btc": 0.24, "bnb": 0.19, "eth": 0.20, "sol": 0.20},
    },
    {
        "name": "exchange_defensive_wait_t020",
        "perspective": "exchange",
        "event_weight": 0.38,
        "deriv_weight": 0.62,
        "phase_weights": {"pre": 0.12, "release": 0.80, "drift": 0.42, "decay": 0.12},
        "boost_soft_thr": 0.16, "boost_mid_thr": 0.24,
        "cut_soft_thr": 0.12, "cut_mid_thr": 0.18,
        "wait_thr": 0.32, "wait_net_floor": -0.10,
        "net_boost_floor": 0.06, "net_cut_floor": -0.02,
        "boost_soft_scale": 1.06, "boost_mid_scale": 1.14,
        "cut_soft_scale": 0.74, "cut_mid_scale": 0.40,
        "boost_soft_asset_thresholds": {"btc": 0.18, "bnb": 0.15, "eth": 0.15, "sol": 0.16},
        "boost_mid_asset_thresholds": {"btc": 0.27, "bnb": 0.22, "eth": 0.22, "sol": 0.24},
        "cut_soft_asset_thresholds": {"btc": 0.14, "bnb": 0.12, "eth": 0.12, "sol": 0.13},
        "cut_mid_asset_thresholds": {"btc": 0.20, "bnb": 0.17, "eth": 0.17, "sol": 0.18},
    },
    {
        "name": "retail_momentum_filtered_t012",
        "perspective": "retail",
        "event_weight": 0.66,
        "deriv_weight": 0.34,
        "phase_weights": {"pre": 0.20, "release": 1.00, "drift": 0.78, "decay": 0.24},
        "boost_soft_thr": 0.10, "boost_mid_thr": 0.16,
        "cut_soft_thr": 0.18, "cut_mid_thr": 0.27,
        "wait_thr": 0.50, "wait_net_floor": -0.18,
        "net_boost_floor": 0.02, "net_cut_floor": -0.05,
        "boost_soft_scale": 1.12, "boost_mid_scale": 1.28,
        "cut_soft_scale": 0.84, "cut_mid_scale": 0.62,
        "boost_soft_asset_thresholds": {"btc": 0.12, "bnb": 0.10, "eth": 0.10, "sol": 0.10},
        "boost_mid_asset_thresholds": {"btc": 0.20, "bnb": 0.15, "eth": 0.15, "sol": 0.15},
        "cut_soft_asset_thresholds": {"btc": 0.20, "bnb": 0.16, "eth": 0.17, "sol": 0.17},
        "cut_mid_asset_thresholds": {"btc": 0.30, "bnb": 0.24, "eth": 0.25, "sol": 0.25},
    },
    {
        "name": "hybrid_contrarian_wait_t015",
        "perspective": "hybrid_contrarian",
        "event_weight": 0.48,
        "deriv_weight": 0.52,
        "phase_weights": {"pre": 0.16, "release": 0.88, "drift": 0.58, "decay": 0.16},
        "boost_soft_thr": 0.13, "boost_mid_thr": 0.20,
        "cut_soft_thr": 0.15, "cut_mid_thr": 0.22,
        "wait_thr": 0.36, "wait_net_floor": -0.11,
        "net_boost_floor": 0.04, "net_cut_floor": -0.03,
        "boost_soft_scale": 1.09, "boost_mid_scale": 1.20,
        "cut_soft_scale": 0.80, "cut_mid_scale": 0.52,
        "boost_soft_asset_thresholds": {"btc": 0.15, "bnb": 0.12, "eth": 0.12, "sol": 0.12},
        "boost_mid_asset_thresholds": {"btc": 0.22, "bnb": 0.18, "eth": 0.18, "sol": 0.19},
        "cut_soft_asset_thresholds": {"btc": 0.16, "bnb": 0.13, "eth": 0.14, "sol": 0.14},
        "cut_mid_asset_thresholds": {"btc": 0.23, "bnb": 0.19, "eth": 0.20, "sol": 0.20},
    },
]

def trade_metrics(df: pd.DataFrame) -> dict[str, float]:
    if df.empty:
        return {"trades": 0, "win_rate": 0.0, "ret_pct": 0.0, "pf": 0.0, "maxdd_pct": 0.0, "avg_lev": 0.0}
    ret = pd.to_numeric(df["scaled_ret"], errors="coerce").fillna(0.0)
    wins = float(ret[ret > 0].sum())
    losses = float(-ret[ret < 0].sum())
    pf = wins / losses if losses > 0 else (999.0 if wins > 0 else 0.0)
    eq = (1.0 + ret).cumprod()
    peak = eq.cummax()
    dd = eq / peak - 1.0
    return {
        "trades": int(len(df)),
        "win_rate": float((ret > 0).mean() * 100.0),
        "ret_pct": float((eq.iloc[-1] - 1.0) * 100.0),
        "pf": float(pf),
        "maxdd_pct": float(dd.min() * 100.0),
        "avg_lev": float(pd.to_numeric(df.get("scaled_lev", df.get("lev", 0.0)), errors="coerce").fillna(0.0).mean()),
    }

def slice_metrics(scored: pd.DataFrame, recent_years: int = 2, wf_months: int = 12) -> dict[str, float]:
    full = trade_metrics(scored)
    if scored.empty:
        recent = wf = full
    else:
        end_ts = pd.to_datetime(scored["entry_time_utc"], utc=True).max()
        recent_start = end_ts - pd.DateOffset(years=recent_years)
        wf_start = end_ts - pd.DateOffset(months=wf_months)
        recent = trade_metrics(scored[scored["entry_time_utc"] >= recent_start].copy())
        wf = trade_metrics(scored[scored["entry_time_utc"] >= wf_start].copy())
    return {
        "full_trades": full["trades"], "full_win": full["win_rate"], "full_ret": full["ret_pct"], "full_pf": full["pf"], "full_dd": full["maxdd_pct"], "full_lev": full["avg_lev"],
        "recent_trades": recent["trades"], "recent_win": recent["win_rate"], "recent_ret": recent["ret_pct"], "recent_pf": recent["pf"], "recent_dd": recent["maxdd_pct"], "recent_lev": recent["avg_lev"],
        "wf_trades": wf["trades"], "wf_win": wf["win_rate"], "wf_ret": wf["ret_pct"], "wf_pf": wf["pf"], "wf_dd": wf["maxdd_pct"], "wf_lev": wf["avg_lev"],
    }

def base_trades_for_seed(lab: s231.SeededConfirmationMatrix, oi_df: pd.DataFrame, lsr_df: pd.DataFrame, taker_df: pd.DataFrame, seed: dict[str, Any]) -> pd.DataFrame:
    df = lab.get_merged(seed["symbol"], seed["entry_tf"], seed["filter_tf"])
    p = s231.PARAM_MAP[seed["param_id"]]
    long_sig, short_sig = lab.family_signals(df, seed["family"], p)
    trades, _ = lab.backtest(df, long_sig, short_sig, p, seed["mode"])
    if trades.empty:
        return trades
    out = trades.copy()
    out["symbol"] = str(seed["symbol"])
    out["seed_id"] = str(seed["seed_id"])
    out["entry_tf"] = str(seed["entry_tf"])
    out["filter_tf"] = str(seed["filter_tf"])
    out["family"] = str(seed["family"])
    out["param_id"] = str(seed["param_id"])
    out["mode"] = str(seed["mode"])
    out["entry_time_utc"] = pd.to_datetime(out["entry_time"], utc=True)
    out["exit_time_utc"] = pd.to_datetime(out["exit_time"], utc=True)
    out["side_label"] = np.where(out["side"] > 0, "LONG", "SHORT")
    out["scaled_ret"] = pd.to_numeric(out["ret"], errors="coerce").fillna(0.0)
    out["scaled_lev"] = pd.to_numeric(out["lev"], errors="coerce").fillna(0.0)
    return msb._attach_features(out, oi_df, lsr_df, taker_df)

def score_trade(row: pd.Series, windows: pd.DataFrame, variant: dict[str, Any]) -> tuple[float, str, float, float, float]:
    local = row.copy()
    local["side"] = row.get("side_label", row.get("side", "LONG"))
    support_ev, adverse_ev, meta = s212._event_support_adverse_for_trade(local, windows, variant)
    support_dv, adverse_dv = s212._deriv_support_adverse(local)
    support = float(variant.get("event_weight", 0.5)) * float(support_ev) + float(variant.get("deriv_weight", 0.5)) * float(support_dv)
    adverse = float(variant.get("event_weight", 0.5)) * float(adverse_ev) + float(variant.get("deriv_weight", 0.5)) * float(adverse_dv)
    net = support - adverse
    sym = str(row.get("symbol", "")).lower()
    boost_soft_thr = float((variant.get("boost_soft_asset_thresholds") or {}).get(sym, variant.get("boost_soft_thr", 0.12)))
    boost_mid_thr = float((variant.get("boost_mid_asset_thresholds") or {}).get(sym, variant.get("boost_mid_thr", 0.18)))
    cut_soft_thr = float((variant.get("cut_soft_asset_thresholds") or {}).get(sym, variant.get("cut_soft_thr", 0.16)))
    cut_mid_thr = float((variant.get("cut_mid_asset_thresholds") or {}).get(sym, variant.get("cut_mid_thr", 0.24)))
    wait_thr = float(variant.get("wait_thr", cut_mid_thr * 1.6))
    wait_net_floor = float(variant.get("wait_net_floor", -0.16))
    net_boost_floor = float(variant.get("net_boost_floor", 0.03))
    net_cut_floor = float(variant.get("net_cut_floor", -0.03))
    action = "HOLD"
    scale = 1.0
    if adverse >= wait_thr and net <= wait_net_floor:
        action, scale = "WAIT", 0.0
    elif adverse >= cut_mid_thr and net <= net_cut_floor:
        action, scale = "CUT_MID", float(variant.get("cut_mid_scale", 0.58))
    elif adverse >= cut_soft_thr and net < 0.0:
        action, scale = "CUT_SOFT", float(variant.get("cut_soft_scale", 0.80))
    elif support >= boost_mid_thr and net >= net_boost_floor and adverse < cut_soft_thr:
        action, scale = "BOOST_MID", float(variant.get("boost_mid_scale", 1.24))
    elif support >= boost_soft_thr and net > 0.0:
        action, scale = "BOOST_SOFT", float(variant.get("boost_soft_scale", 1.10))
    return scale, action, support, adverse, net

def apply_overlay(trades: pd.DataFrame, windows: pd.DataFrame, variant: dict[str, Any]) -> pd.DataFrame:
    if trades.empty:
        return trades.copy()
    start_utc = trades["entry_time_utc"].min().floor("15min")
    end_utc = trades["entry_time_utc"].max().ceil("15min")
    local_windows = windows[(windows["end_utc"] >= start_utc) & (windows["start_utc"] <= end_utc)].copy()
    rows = []
    for _, row in trades.iterrows():
        scale, action, support, adverse, net = score_trade(row, local_windows, variant)
        out = row.copy()
        base_ret = float(pd.to_numeric(row.get("ret", 0.0), errors="coerce"))
        out["overlay_name"] = variant["name"]
        out["overlay_perspective"] = variant["perspective"]
        out["msg_total_support"] = support
        out["msg_total_adverse"] = adverse
        out["msg_net_score"] = net
        out["msg_action"] = action
        out["msg_scale"] = scale
        out["scaled_ret"] = max(-0.95, base_ret * float(scale))
        out["scaled_lev"] = float(pd.to_numeric(row.get("lev", 0.0), errors="coerce") or 0.0) * float(scale)
        rows.append(out)
    return pd.DataFrame(rows)

def rec_rank(name: str) -> int:
    order = {
        "promote_overlay_primary": 0,
        "promote_overlay_protective": 1,
        "keep_overlay_secondary": 2,
        "keep_overlay_research": 3,
        "discard_overlay": 4,
    }
    return order.get(name, 9)

def classify(base: dict[str, float], row: dict[str, Any]) -> str:
    base_recent_ret = float(base.get("recent_ret", 0.0))
    base_recent_pf = float(base.get("recent_pf", 0.0))
    base_recent_win = float(base.get("recent_win", 0.0))
    base_recent_dd = float(base.get("recent_dd", 0.0))
    base_wf_pf = float(base.get("wf_pf", 0.0))
    base_wf_dd = float(base.get("wf_dd", 0.0))
    recent_ret = float(row.get("recent_ret", 0.0))
    recent_pf = float(row.get("recent_pf", 0.0))
    recent_win = float(row.get("recent_win", 0.0))
    recent_dd = float(row.get("recent_dd", 0.0))
    wf_pf = float(row.get("wf_pf", 0.0))
    wf_ret = float(row.get("wf_ret", 0.0))
    wf_dd = float(row.get("wf_dd", 0.0))
    wait_ratio_recent = float(row.get("wait_ratio_recent", 0.0))
    keep_ratio_recent = float(row.get("recent_keep_ratio", 1.0))
    dd_improve_recent = base_recent_dd - recent_dd
    dd_improve_wf = base_wf_dd - wf_dd
    pf_up = recent_pf >= max(1.10, base_recent_pf * 1.06)
    wf_ok = wf_pf >= max(1.00, base_wf_pf * 0.96)
    ret_ok = recent_ret >= base_recent_ret * 0.60 if base_recent_ret > 0 else recent_ret > 0
    protective = dd_improve_recent >= 1.2 and dd_improve_wf >= 0.5 and keep_ratio_recent >= 0.55
    win_up = recent_win >= base_recent_win + 4.0
    if pf_up and wf_ok and ret_ok and wait_ratio_recent <= 0.28 and keep_ratio_recent >= 0.65 and (recent_ret >= base_recent_ret * 0.90 or (protective and win_up)):
        return "promote_overlay_primary"
    if protective and wf_ok and wait_ratio_recent <= 0.36:
        return "promote_overlay_protective"
    if (recent_pf >= base_recent_pf * 0.96 and wf_pf >= 1.0 and keep_ratio_recent >= 0.50) or (win_up and recent_ret > 0):
        return "keep_overlay_secondary"
    if wf_ret > -5.0 and recent_pf >= 1.0:
        return "keep_overlay_research"
    return "discard_overlay"

def composite_score(base: dict[str, float], row: dict[str, Any]) -> float:
    ret_delta_recent = float(row.get("recent_ret", 0.0)) - float(base.get("recent_ret", 0.0))
    pf_delta_recent = float(row.get("recent_pf", 0.0)) - float(base.get("recent_pf", 0.0))
    pf_delta_wf = float(row.get("wf_pf", 0.0)) - float(base.get("wf_pf", 0.0))
    dd_improve_recent = float(base.get("recent_dd", 0.0)) - float(row.get("recent_dd", 0.0))
    dd_improve_wf = float(base.get("wf_dd", 0.0)) - float(row.get("wf_dd", 0.0))
    wait_ratio = float(row.get("wait_ratio_recent", 0.0))
    keep_ratio = float(row.get("recent_keep_ratio", 1.0))
    ret_component = max(-25.0, min(25.0, ret_delta_recent))
    return ret_component + 10.0 * pf_delta_recent + 8.0 * pf_delta_wf + 1.5 * dd_improve_recent + 1.0 * dd_improve_wf - 25.0 * wait_ratio - 6.0 * abs(keep_ratio - 1.0)

def run(project_dir: Path) -> dict[str, Any]:
    out_dir = project_dir / "reports" / "research_raw"
    out_dir.mkdir(parents=True, exist_ok=True)
    lab = s231.SeededConfirmationMatrix(project_dir)
    hist = msb._load_or_fetch_history(project_dir, refresh=False)
    oi_df = msb._parse_oi_df(hist.get("oi_agg_btc_1d", {}))
    lsr_df = msb._parse_lsr_df(hist.get("lsr_btcusdt_binance_4h", {}))
    taker_df = msb._parse_taker_df(hist.get("taker_btcusdt_binance_4h", {}))
    windows = msb._load_event_windows(project_dir, pd.Timestamp("2019-01-01", tz="UTC"), pd.Timestamp.now(tz="UTC") + pd.Timedelta(days=7), include_all_modes=True)

    rows: list[dict[str, Any]] = []
    base_by_seed: dict[str, dict[str, float]] = {}
    for seed in SEEDS:
        print(f"[stage234] seed={seed['seed_id']}", flush=True)
        trades = base_trades_for_seed(lab, oi_df, lsr_df, taker_df, seed)
        if trades.empty:
            continue
        base_metrics = slice_metrics(trades)
        base_by_seed[seed["seed_id"]] = base_metrics
        recent_start = pd.to_datetime(trades["entry_time_utc"], utc=True).max() - pd.DateOffset(years=2)
        for variant in OVERLAY_VARIANTS:
            scored = apply_overlay(trades, windows, variant)
            metrics = slice_metrics(scored)
            counts_recent = scored[scored["entry_time_utc"] >= recent_start]["msg_action"].value_counts()
            counts_all = scored["msg_action"].value_counts()
            row = {
                "seed_id": seed["seed_id"], "symbol": seed["symbol"], "entry_tf": seed["entry_tf"], "filter_tf": seed["filter_tf"],
                "family": seed["family"], "param_id": seed["param_id"], "mode": seed["mode"],
                "overlay_name": variant["name"], "overlay_perspective": variant["perspective"],
                "full_boost_soft": int(counts_all.get("BOOST_SOFT", 0)),
                "full_boost_mid": int(counts_all.get("BOOST_MID", 0)),
                "full_cut_soft": int(counts_all.get("CUT_SOFT", 0)),
                "full_cut_mid": int(counts_all.get("CUT_MID", 0)),
                "full_wait": int(counts_all.get("WAIT", 0)),
                "recent_boost_soft": int(counts_recent.get("BOOST_SOFT", 0)),
                "recent_boost_mid": int(counts_recent.get("BOOST_MID", 0)),
                "recent_cut_soft": int(counts_recent.get("CUT_SOFT", 0)),
                "recent_cut_mid": int(counts_recent.get("CUT_MID", 0)),
                "recent_wait": int(counts_recent.get("WAIT", 0)),
                **metrics,
                "base_full_ret": base_metrics["full_ret"], "base_full_pf": base_metrics["full_pf"], "base_full_dd": base_metrics["full_dd"],
                "base_recent_ret": base_metrics["recent_ret"], "base_recent_pf": base_metrics["recent_pf"], "base_recent_dd": base_metrics["recent_dd"], "base_recent_win": base_metrics["recent_win"], "base_recent_trades": base_metrics["recent_trades"],
                "base_wf_ret": base_metrics["wf_ret"], "base_wf_pf": base_metrics["wf_pf"], "base_wf_dd": base_metrics["wf_dd"], "base_wf_trades": base_metrics["wf_trades"],
            }
            row["recent_keep_ratio"] = float(metrics["recent_trades"] / max(1, base_metrics["recent_trades"]))
            row["wait_ratio_recent"] = float(row["recent_wait"] / max(1, base_metrics["recent_trades"]))
            row["pf_delta_recent"] = float(metrics["recent_pf"] - base_metrics["recent_pf"])
            row["ret_delta_recent"] = float(metrics["recent_ret"] - base_metrics["recent_ret"])
            row["win_delta_recent"] = float(metrics["recent_win"] - base_metrics["recent_win"])
            row["dd_improve_recent"] = float(base_metrics["recent_dd"] - metrics["recent_dd"])
            row["pf_delta_wf"] = float(metrics["wf_pf"] - base_metrics["wf_pf"])
            row["dd_improve_wf"] = float(base_metrics["wf_dd"] - metrics["wf_dd"])
            row["recommendation"] = classify(base_metrics, row)
            row["recommendation_rank"] = rec_rank(row["recommendation"])
            row["composite_score"] = composite_score(base_metrics, row)
            rows.append(row)

    df = pd.DataFrame(rows)
    if not df.empty:
        df.sort_values(["seed_id", "recommendation_rank", "composite_score"], ascending=[True, True, False], inplace=True)
    (out_dir / "stage234_seeded_message_overlay_matrix_all.csv").write_text(df.to_csv(index=False), encoding="utf-8")
    best_by_seed: dict[str, Any] = {}
    lines = []
    lines.append("[stage234_seeded_message_overlay_matrix]")
    lines.append("goal=四条 seed lanes 继续只测消息/事件 sizing overlay；同时把散户视角 / 机构视角 / 交易所视角做成可回测矩阵，entry 仍保持技术面")
    lines.append(f"tested_rows={len(df)}")
    for key in ["promote_overlay_primary", "promote_overlay_protective", "keep_overlay_secondary", "keep_overlay_research"]:
        lines.append(f"{key}_total={int((df['recommendation'] == key).sum()) if not df.empty else 0}")
    lines.append("ranking=先看近2年 PF/收益/保留比，再看 WF PF；6年继续只做软约束")
    lines.append("")
    lines.append("[best_by_seed]")
    for seed in SEEDS:
        sid = seed["seed_id"]
        sub = df[df["seed_id"] == sid].copy()
        if sub.empty:
            lines.append(f"- {sid} | none")
            best_by_seed[sid] = {"status": "skip", "reason": "no_rows"}
            continue
        sub.sort_values(["recommendation_rank", "composite_score", "recent_pf", "wf_pf"], ascending=[True, False, False, False], inplace=True)
        best = sub.iloc[0].to_dict()
        base = base_by_seed[sid]
        lines.append(
            f"- {sid} | base={seed['entry_tf']}/{seed['filter_tf']} {seed['family']} {seed['param_id']} {seed['mode']} | recent={base['recent_ret']:.2f}%/{base['recent_win']:.2f}%/PF{base['recent_pf']:.3f} | wf={base['wf_ret']:.2f}%/PF{base['wf_pf']:.3f}"
        )
        lines.append(
            f"  -> top={best['recommendation']} {best['overlay_name']} ({best['overlay_perspective']}) | recent={best['recent_ret']:.2f}%/{best['recent_win']:.2f}%/PF{best['recent_pf']:.3f} | wf={best['wf_ret']:.2f}%/PF{best['wf_pf']:.3f} | keep={best['recent_keep_ratio']:.2f} | wait={best['wait_ratio_recent']:.2f}"
        )
        best_by_seed[sid] = {"seed_meta": seed, "base": base, "best_overlay": best}
    lines.append("")
    lines.append("[institution_vs_retail_hint]")
    lines.append("- retail_momentum_filtered 更偏催化追随；institution_crowding_asym 更偏拥挤/清算反身性；exchange_defensive_wait 更偏风控和等待；balanced/hybrid 负责折中。")
    lines.append("- 这轮只给 sizing overlay 结论，不改 entry，不切 runtime。")
    (out_dir / "stage234_seeded_message_overlay_matrix_latest.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    summary = {
        "goal": "seeded message/event sizing overlay matrix with retail/institution/exchange perspectives",
        "tested_rows": int(len(df)),
        "best_by_seed": best_by_seed,
        "top_rows": df.sort_values(["recommendation_rank", "composite_score"], ascending=[True, False]).head(12).to_dict(orient="records") if not df.empty else [],
    }
    (out_dir / "stage234_seeded_message_overlay_matrix_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return summary

def main() -> None:
    ap = argparse.ArgumentParser(description="Stage234 seeded message overlay matrix")
    ap.add_argument("--project-dir", type=Path, default=Path("."))
    args = ap.parse_args()
    run(args.project_dir.resolve())

if __name__ == "__main__":
    main()
