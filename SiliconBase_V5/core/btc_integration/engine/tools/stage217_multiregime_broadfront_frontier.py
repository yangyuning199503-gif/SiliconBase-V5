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

import contextlib

import tools.stage46_aggressive_lab as s46
import tools.stage59_structural_lab as s59
import tools.stage211_future_event_runtime_bridge_frontier as s211
import tools.stage212_message_sizing_overlay_frontier as s212
from src.backtest.io import read_config

from tools import message_stack_backtest as msb
from tools import research_config_baseline as rcb

ASSET_WEIGHTS = {"btc": 0.25, "eth": 0.60, "sol": 0.15}
ASSETS = ["btc", "eth", "sol"]
RECENT_WINDOW_MONTHS = 24.0
RECENT_TRADE_FLOOR = 10
WF_POSITIVE_FOLD_FLOOR = 2
PF_CAP = 6.0
RETAIN_MIN = 0.86
RETAIN_MAX = 1.18


def _clip_pf(x: float, cap: float = PF_CAP) -> float:
    return float(min(max(float(x), 0.0), float(cap)))


def _clip_retain(x: float) -> float:
    return float(min(max(float(x), RETAIN_MIN), float(RETAIN_MAX)))


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


def _infer_leg(row: dict[str, Any]) -> str:
    name = str(row.get("name", "")).lower()
    if "dual" in name:
        return "dual"
    if "_short_" in name or name.startswith("short_") or name.endswith("_short"):
        return "short"
    return "long"


def _pick_rows(stage91: dict[str, Any]) -> list[dict[str, Any]]:
    rows = list(stage91.get("rows", []) or [])
    asset_summary = list(stage91.get("asset_summary", []) or [])
    rows_by_name = {str(r.get("name", "")): r for r in rows if str(r.get("name", ""))}
    selected_names: list[str] = []

    def add_name(name: str) -> None:
        if name and name in rows_by_name and name not in selected_names:
            selected_names.append(name)

    for item in asset_summary:
        for key in ["active", "long_best", "short_best", "dual_best"]:
            row = item.get(key)
            if isinstance(row, dict):
                add_name(str(row.get("name", "")))

    for sym in ASSETS:
        sym_rows = [r for r in rows if str(r.get("symbol", "")).lower() == sym]
        by_leg: dict[str, list[dict[str, Any]]] = {"long": [], "short": [], "dual": []}
        for r in sym_rows:
            leg = _infer_leg(r)
            by_leg.setdefault(leg, []).append(r)
        for leg, bag in by_leg.items():
            bag.sort(key=lambda r: float(r.get("alpha_score", 0.0)), reverse=True)
            keep = 2 if leg != "dual" else 1
            for r in bag[:keep]:
                add_name(str(r.get("name", "")))
        extras = [r for r in sym_rows if str(r.get("name", "")) not in selected_names]
        extras.sort(key=lambda r: float(r.get("alpha_score", 0.0)), reverse=True)
        extra_keep = 2 if sym == "eth" else 1
        for r in extras[:extra_keep]:
            add_name(str(r.get("name", "")))

    selected = [rows_by_name[n] for n in selected_names if n in rows_by_name]
    selected.sort(
        key=lambda r: (
            ASSET_WEIGHTS.get(str(r.get("symbol", "")).lower(), 0.0),
            float(r.get("alpha_score", 0.0)),
        ),
        reverse=True,
    )
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


def _variants() -> list[dict[str, Any]]:
    inf = 9.99
    return [
        {
            "name": "tri_balance_t016",
            "event_weight": 0.58,
            "deriv_weight": 0.42,
            "phase_weights": {"pre": 0.14, "release": 0.92, "drift": 0.64, "decay": 0.20},
            "boost_soft_thr": 0.12,
            "boost_mid_thr": 0.18,
            "cut_soft_thr": 0.16,
            "cut_mid_thr": 0.24,
            "boost_soft_scale": 1.10,
            "boost_mid_scale": 1.22,
            "cut_soft_scale": 0.84,
            "cut_mid_scale": 0.62,
            "net_boost_floor": 0.02,
            "net_cut_floor": -0.03,
            "boost_soft_asset_thresholds": {"btc": 0.11, "eth": 0.10, "sol": 0.13},
            "boost_mid_asset_thresholds": {"btc": 0.17, "eth": 0.15, "sol": 0.19},
            "cut_soft_asset_thresholds": {"btc": 0.16, "eth": 0.15, "sol": 0.17},
            "cut_mid_asset_thresholds": {"btc": 0.24, "eth": 0.22, "sol": 0.25},
            "allow_boost_assets": {"btc": True, "eth": True, "sol": True},
            "allow_cut_assets": {"btc": True, "eth": True, "sol": True},
        },
        {
            "name": "tri_capture_t012",
            "event_weight": 0.64,
            "deriv_weight": 0.36,
            "phase_weights": {"pre": 0.12, "release": 1.00, "drift": 0.78, "decay": 0.18},
            "boost_soft_thr": 0.10,
            "boost_mid_thr": 0.15,
            "cut_soft_thr": 0.17,
            "cut_mid_thr": 0.26,
            "boost_soft_scale": 1.12,
            "boost_mid_scale": 1.28,
            "cut_soft_scale": 0.86,
            "cut_mid_scale": 0.64,
            "net_boost_floor": 0.01,
            "net_cut_floor": -0.03,
            "boost_soft_asset_thresholds": {"btc": 0.09, "eth": 0.08, "sol": 0.11},
            "boost_mid_asset_thresholds": {"btc": 0.14, "eth": 0.12, "sol": 0.16},
            "cut_soft_asset_thresholds": {"btc": 0.17, "eth": 0.16, "sol": 0.18},
            "cut_mid_asset_thresholds": {"btc": 0.25, "eth": 0.23, "sol": 0.26},
            "allow_boost_assets": {"btc": True, "eth": True, "sol": True},
            "allow_cut_assets": {"btc": True, "eth": True, "sol": True},
        },
        {
            "name": "btc_eth_shock_t014",
            "event_weight": 0.66,
            "deriv_weight": 0.34,
            "phase_weights": {"pre": 0.10, "release": 1.00, "drift": 0.82, "decay": 0.16},
            "boost_soft_thr": 0.11,
            "boost_mid_thr": 0.17,
            "cut_soft_thr": 0.16,
            "cut_mid_thr": 0.24,
            "boost_soft_scale": 1.10,
            "boost_mid_scale": 1.24,
            "cut_soft_scale": 0.85,
            "cut_mid_scale": 0.64,
            "net_boost_floor": 0.02,
            "net_cut_floor": -0.03,
            "boost_soft_asset_thresholds": {"btc": 0.10, "eth": 0.09, "sol": inf},
            "boost_mid_asset_thresholds": {"btc": 0.15, "eth": 0.13, "sol": inf},
            "cut_soft_asset_thresholds": {"btc": 0.17, "eth": 0.15, "sol": 0.18},
            "cut_mid_asset_thresholds": {"btc": 0.24, "eth": 0.22, "sol": 0.26},
            "allow_boost_assets": {"btc": True, "eth": True, "sol": False},
            "allow_cut_assets": {"btc": True, "eth": True, "sol": True},
        },
        {
            "name": "sol_range_t018",
            "event_weight": 0.54,
            "deriv_weight": 0.46,
            "phase_weights": {"pre": 0.18, "release": 0.82, "drift": 0.56, "decay": 0.30},
            "boost_soft_thr": 0.13,
            "boost_mid_thr": 0.20,
            "cut_soft_thr": 0.17,
            "cut_mid_thr": 0.25,
            "boost_soft_scale": 1.09,
            "boost_mid_scale": 1.18,
            "cut_soft_scale": 0.86,
            "cut_mid_scale": 0.66,
            "net_boost_floor": 0.02,
            "net_cut_floor": -0.03,
            "boost_soft_asset_thresholds": {"btc": inf, "eth": 0.12, "sol": 0.11},
            "boost_mid_asset_thresholds": {"btc": inf, "eth": 0.18, "sol": 0.15},
            "cut_soft_asset_thresholds": {"btc": 0.18, "eth": 0.16, "sol": 0.16},
            "cut_mid_asset_thresholds": {"btc": 0.26, "eth": 0.24, "sol": 0.23},
            "allow_boost_assets": {"btc": False, "eth": True, "sol": True},
            "allow_cut_assets": {"btc": True, "eth": True, "sol": True},
        },
        {
            "name": "basis_hedge_t022",
            "event_weight": 0.46,
            "deriv_weight": 0.54,
            "phase_weights": {"pre": 0.12, "release": 0.86, "drift": 0.52, "decay": 0.14},
            "boost_soft_thr": 0.14,
            "boost_mid_thr": 0.22,
            "cut_soft_thr": 0.15,
            "cut_mid_thr": 0.22,
            "boost_soft_scale": 1.08,
            "boost_mid_scale": 1.16,
            "cut_soft_scale": 0.82,
            "cut_mid_scale": 0.56,
            "net_boost_floor": 0.03,
            "net_cut_floor": -0.02,
            "boost_soft_asset_thresholds": {"btc": 0.13, "eth": 0.12, "sol": inf},
            "boost_mid_asset_thresholds": {"btc": 0.19, "eth": 0.17, "sol": inf},
            "cut_soft_asset_thresholds": {"btc": 0.14, "eth": 0.14, "sol": 0.15},
            "cut_mid_asset_thresholds": {"btc": 0.21, "eth": 0.20, "sol": 0.22},
            "allow_boost_assets": {"btc": True, "eth": True, "sol": False},
            "allow_cut_assets": {"btc": True, "eth": True, "sol": True},
        },
        {
            "name": "preserve_multi_t024",
            "event_weight": 0.52,
            "deriv_weight": 0.48,
            "phase_weights": {"pre": 0.10, "release": 0.80, "drift": 0.48, "decay": 0.14},
            "boost_soft_thr": 0.16,
            "boost_mid_thr": 0.24,
            "cut_soft_thr": 0.18,
            "cut_mid_thr": 0.27,
            "boost_soft_scale": 1.06,
            "boost_mid_scale": 1.14,
            "cut_soft_scale": 0.88,
            "cut_mid_scale": 0.68,
            "net_boost_floor": 0.04,
            "net_cut_floor": -0.04,
            "boost_soft_asset_thresholds": {"btc": 0.15, "eth": 0.14, "sol": 0.16},
            "boost_mid_asset_thresholds": {"btc": 0.22, "eth": 0.19, "sol": 0.23},
            "cut_soft_asset_thresholds": {"btc": 0.18, "eth": 0.17, "sol": 0.18},
            "cut_mid_asset_thresholds": {"btc": 0.27, "eth": 0.25, "sol": 0.27},
            "allow_boost_assets": {"btc": True, "eth": True, "sol": True},
            "allow_cut_assets": {"btc": True, "eth": True, "sol": True},
        },
    ]


def _apply_variant_local(trades: pd.DataFrame, windows: pd.DataFrame, variant: dict[str, Any], initial_equity: float) -> dict[str, Any]:
    scored = s212._score_rows(trades, windows, variant)
    adjusted_rows = []
    boost_soft = boost_mid = cut_soft = cut_mid = 0
    phase_counter: dict[str, int] = {"pre": 0, "release": 0, "drift": 0, "decay": 0}
    top_groups: list[str] = []
    allow_boost_assets = variant.get("allow_boost_assets", {}) or {}
    allow_cut_assets = variant.get("allow_cut_assets", {}) or {}
    for _, row in scored.iterrows():
        sym = str(row.get("symbol", "") or "").lower()
        sup = float(row.get("msg_total_support", 0.0))
        adv = float(row.get("msg_total_adverse", 0.0))
        net = float(row.get("msg_net_score", 0.0))
        allow_boost = bool(allow_boost_assets.get(sym, True))
        allow_cut = bool(allow_cut_assets.get(sym, True))
        boost_soft_thr = float((variant.get("boost_soft_asset_thresholds") or {}).get(sym, variant.get("boost_soft_thr", 0.12)))
        boost_mid_thr = float((variant.get("boost_mid_asset_thresholds") or {}).get(sym, variant.get("boost_mid_thr", 0.18)))
        cut_soft_thr = float((variant.get("cut_soft_asset_thresholds") or {}).get(sym, variant.get("cut_soft_thr", 0.16)))
        cut_mid_thr = float((variant.get("cut_mid_asset_thresholds") or {}).get(sym, variant.get("cut_mid_thr", 0.24)))
        if not allow_boost:
            boost_soft_thr = boost_mid_thr = 9.99
        if not allow_cut:
            cut_soft_thr = cut_mid_thr = 9.99
        net_boost_floor = float(variant.get("net_boost_floor", 0.03))
        net_cut_floor = float(variant.get("net_cut_floor", -0.03))
        action = "HOLD"
        scale = 1.0
        if adv >= cut_mid_thr and net <= net_cut_floor:
            action = "CUT_MID"
            scale = float(variant.get("cut_mid_scale", 0.60))
            cut_mid += 1
        elif adv >= cut_soft_thr and net < 0.0:
            action = "CUT_SOFT"
            scale = float(variant.get("cut_soft_scale", 0.84))
            cut_soft += 1
        elif sup >= boost_mid_thr and net >= net_boost_floor:
            action = "BOOST_MID"
            scale = float(variant.get("boost_mid_scale", 1.22))
            boost_mid += 1
        elif sup >= boost_soft_thr and net > 0.0:
            action = "BOOST_SOFT"
            scale = float(variant.get("boost_soft_scale", 1.10))
            boost_soft += 1
        if action != "HOLD":
            for phase in str(row.get("msg_phases", "")).split(","):
                phase = phase.strip()
                if phase in phase_counter:
                    phase_counter[phase] += 1
            top_groups.extend(list(row.get("msg_groups", []) or []))
        newrow = row.copy()
        newrow["pnl"] = float(row.get("pnl", 0.0)) * scale
        if "qty" in newrow:
            with contextlib.suppress(BaseException):
                newrow["qty"] = float(row.get("qty", 0.0)) * scale
        newrow["msg_action"] = action
        newrow["msg_scale"] = scale
        adjusted_rows.append(newrow)
    adjusted = pd.DataFrame(adjusted_rows)
    base_metrics = msb._trade_metrics(trades, initial_equity)
    gated_metrics = msb._trade_metrics(adjusted, initial_equity)
    pnl_delta = float(gated_metrics["total_pnl"] - base_metrics["total_pnl"])
    dd_delta = float(gated_metrics["max_drawdown"] - base_metrics["max_drawdown"])
    qty_base = float(pd.to_numeric(trades.get("qty", 0.0), errors="coerce").fillna(0.0).sum())
    qty_adj = float(pd.to_numeric(adjusted.get("qty", 0.0), errors="coerce").fillna(0.0).sum()) if not adjusted.empty else 0.0
    retained = qty_adj / qty_base if qty_base > 0 else 1.0
    exposure_drift = abs(retained - 1.0)
    score = (
        pnl_delta / float(initial_equity)
        + 2.2 * dd_delta
        - 0.018 * exposure_drift
        - 0.0005 * cut_mid
        - 0.0002 * cut_soft
        + 0.0002 * boost_soft
        + 0.0003 * boost_mid
    )
    vc = pd.Series(top_groups, dtype=str).value_counts().head(5)
    return {
        "variant": str(variant["name"]),
        "params": variant,
        "base": base_metrics,
        "gated": gated_metrics,
        "boost_soft": int(boost_soft),
        "boost_mid": int(boost_mid),
        "cut_soft": int(cut_soft),
        "cut_mid": int(cut_mid),
        "retained_notional_ratio": float(retained),
        "pnl_delta": pnl_delta,
        "dd_delta": dd_delta,
        "score": float(score),
        "top_event_groups": vc.index.tolist(),
        "phase_hits": phase_counter,
    }


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
        ev = _apply_variant_local(fold, windows, variant, initial_equity)
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
            "variants": [],
        }
    start_utc = pd.to_datetime(trades["entry_time_utc"], utc=True).min().floor("15min")
    end_utc = pd.to_datetime(trades["entry_time_utc"], utc=True).max().ceil("15min")
    windows = msb._load_event_windows(root, start_utc, end_utc, include_all_modes=True)
    recent = s212._two_year_slice(trades)
    base_full = msb._trade_metrics(trades, initial_equity)
    base_full["monthlyized"] = _geom_monthly(base_full["total_return"], max(_trade_span_months(trades), 12.0))
    base_recent = msb._trade_metrics(recent, initial_equity)
    base_recent["monthlyized"] = _geom_monthly(base_recent["total_return"], RECENT_WINDOW_MONTHS if not recent.empty else 0.0)

    scored: list[dict[str, Any]] = []
    for variant in _variants():
        full_ev = _apply_variant_local(trades, windows, variant, initial_equity)
        recent_ev = _apply_variant_local(recent, windows, variant, initial_equity) if not recent.empty else {
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
        gm_full["monthlyized"] = _geom_monthly(gm_full["total_return"], max(_trade_span_months(trades), 12.0))
        gm_r2 = dict(recent_ev["gated"])
        gm_r2["monthlyized"] = _geom_monthly(gm_r2["total_return"], RECENT_WINDOW_MONTHS if not recent.empty else 0.0)
        recent_trades = int(gm_r2.get("trades", 0) or 0)
        recent_pf_c = _clip_pf(gm_r2.get("profit_factor", 0.0))
        full_pf_c = _clip_pf(gm_full.get("profit_factor", 0.0))
        wf_pf_c = _clip_pf(wf.get("avg_pf", 0.0), cap=4.0)
        retain_c = _clip_retain(full_ev.get("retained_notional_ratio", 1.0))
        sample_penalty = float(
            0.020 * max(0, RECENT_TRADE_FLOOR - recent_trades)
            + 0.015 * max(0, WF_POSITIVE_FOLD_FLOOR - int(wf.get("positive_folds", 0) or 0))
            + 0.008 * max(0, 4 - int(wf.get("total_folds", 0) or 0))
        )
        sign_penalty = 0.045 if float(gm_r2.get("total_return", 0.0)) < 0 else 0.0
        full_soft_penalty = 0.0
        if float(gm_full.get("total_return", 0.0)) < -0.25:
            full_soft_penalty += 0.020
        if float(gm_full.get("max_drawdown", 0.0)) < -0.65:
            full_soft_penalty += 0.010
        wf_score = float(
            wf["aggregate_pnl_delta"] / initial_equity
            + 2.1 * wf["aggregate_dd_delta"]
            + 0.12 * wf["avg_ret"]
            + 0.08 * wf_pf_c
            - 0.010 * abs(retain_c - 1.0)
            - sample_penalty
        )
        composite = float(
            0.16 * full_ev["score"]
            + 1.04 * recent_ev["score"]
            + 0.96 * wf_score
            + 0.18 * gm_r2["monthlyized"]
            + 0.05 * recent_pf_c
            + 0.01 * full_pf_c
            - sign_penalty
            - full_soft_penalty
        )
        scored.append({
            "name": variant["name"],
            "params": variant,
            "full": full_ev,
            "recent2y": recent_ev,
            "wf": wf,
            "gated_metrics_full": gm_full,
            "gated_metrics_recent2y": gm_r2,
            "composite_score": composite,
            "recent_pf_capped": recent_pf_c,
            "full_pf_capped": full_pf_c,
            "wf_pf_capped": wf_pf_c,
            "retain_clipped": retain_c,
            "sample_penalty": sample_penalty + sign_penalty + full_soft_penalty,
            "top_event_groups": full_ev["top_event_groups"],
        })
    scored.sort(key=lambda x: (x["composite_score"], x["gated_metrics_recent2y"]["total_return"], x["gated_metrics_recent2y"]["profit_factor"]), reverse=True)
    return {
        "candidate": row,
        "baseline": base_full,
        "recent2y": base_recent,
        "best": scored[0] if scored else None,
        "variants": scored,
        "top_variants": scored[:4],
    }


def run(project_dir: Path, out_txt: Path, out_json: Path) -> None:
    cfg = read_config(project_dir / "config.yml")
    initial_equity = float(cfg.get("portfolio", {}).get("initial_equity", 100000.0))
    stage91 = _load_stage91(project_dir)
    selected = _pick_rows(stage91)
    hist = msb._load_or_fetch_history(project_dir, refresh=False)
    candidate_results = [_candidate_eval(project_dir, row, hist, initial_equity) for row in selected]

    candidate_weight_map = {str(r.get("name", "")): ASSET_WEIGHTS.get(str(r.get("symbol", "")).lower(), 0.0) / max(sum(1 for x in selected if str(x.get("symbol", "")).lower() == str(r.get("symbol", "")).lower()), 1) for r in selected}
    aggregate_rows: dict[str, dict[str, Any]] = {}
    for cr in candidate_results:
        row = cr["candidate"]
        sym = str(row.get("symbol", "")).lower()
        row_name = str(row.get("name", ""))
        candidate_weight = float(candidate_weight_map.get(row_name, 0.0))
        for vr in cr.get("variants", []):
            bucket = aggregate_rows.setdefault(vr["name"], {
                "name": vr["name"],
                "weighted_score": 0.0,
                "weighted_recent_monthly": 0.0,
                "weighted_recent_ret": 0.0,
                "weighted_recent_pf": 0.0,
                "weighted_full_ret": 0.0,
                "weighted_full_pf": 0.0,
                "weighted_wf_pnl_delta": 0.0,
                "weighted_retain": 0.0,
                "weighted_recent_trades": 0.0,
                "weighted_positive_folds": 0.0,
                "weighted_sample_penalty": 0.0,
                "weighted_negative_recent": 0.0,
                "weighted_negative_full": 0.0,
                "members": [],
            })
            gm_full = vr["gated_metrics_full"]
            gm_r2 = vr["gated_metrics_recent2y"]
            wf = vr["wf"]
            bucket["weighted_score"] += candidate_weight * float(vr["composite_score"])
            bucket["weighted_recent_monthly"] += candidate_weight * float(gm_r2.get("monthlyized", 0.0))
            bucket["weighted_recent_ret"] += candidate_weight * float(gm_r2.get("total_return", 0.0))
            bucket["weighted_recent_pf"] += candidate_weight * float(vr.get("recent_pf_capped", 0.0))
            bucket["weighted_full_ret"] += candidate_weight * float(gm_full.get("total_return", 0.0))
            bucket["weighted_full_pf"] += candidate_weight * float(vr.get("full_pf_capped", 0.0))
            bucket["weighted_wf_pnl_delta"] += candidate_weight * float(wf.get("aggregate_pnl_delta", 0.0))
            bucket["weighted_retain"] += candidate_weight * float(vr.get("retain_clipped", 1.0))
            bucket["weighted_recent_trades"] += candidate_weight * float(gm_r2.get("trades", 0.0) or 0.0)
            bucket["weighted_positive_folds"] += candidate_weight * float(wf.get("positive_folds", 0.0) or 0.0)
            bucket["weighted_sample_penalty"] += candidate_weight * float(vr.get("sample_penalty", 0.0))
            if float(gm_r2.get("total_return", 0.0)) < 0:
                bucket["weighted_negative_recent"] += candidate_weight
            if float(gm_full.get("total_return", 0.0)) < 0:
                bucket["weighted_negative_full"] += candidate_weight
            bucket["members"].append({
                "symbol": sym,
                "candidate": row_name,
                "leg": _infer_leg(row),
                "decision": row.get("decision", "-"),
            })
    variant_leaderboard = sorted(
        aggregate_rows.values(),
        key=lambda x: (x["weighted_score"], x["weighted_recent_monthly"], x["weighted_recent_ret"], -x["weighted_negative_recent"]),
        reverse=True,
    )
    recommended_variant = None
    for v in variant_leaderboard:
        if (
            float(v.get("weighted_recent_ret", 0.0)) > 0
            and float(v.get("weighted_recent_pf", 0.0)) >= 1.05
            and float(v.get("weighted_wf_pnl_delta", 0.0)) >= 0.0
            and float(v.get("weighted_negative_recent", 0.0)) <= 0.40
        ):
            recommended_variant = v
            break

    now_utc = pd.Timestamp.now(tz="UTC")
    live_calendar, cal_mode = s211._standardize_calendar_live(project_dir, now_utc)
    live_news, news_mode = s211._standardize_news_live(project_dir, now_utc)
    live_calendar = s211._attach_asset_scores(live_calendar, "calendar")
    live_news = s211._attach_asset_scores(live_news, "news")

    lines: list[str] = []
    lines.append("Stage217 multiregime broadfront frontier")
    lines.append("")
    lines.append("[scoring_rule]")
    lines.append("- 6年总样本必须报，但只作软约束；近2年 + WF 继续作硬过滤。")
    lines.append("- 不再把 overlay 过早收缩到 ETH 单核；BTC/ETH/SOL 都保留 long/short/dual。")
    lines.append("- 研究层先激进扩候选，再用样本惩罚 / PF上限 / WF 正收益折收口。")
    lines.append("")
    lines.append("[selected_candidates]")
    for row in selected:
        lines.append(f"- {str(row.get('symbol','')).upper()} | leg={_infer_leg(row)} | {row.get('name','')} | decision={row.get('decision','-')} | alpha_score={float(row.get('alpha_score',0.0)):+.2f}")
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
            f"- {str(row.get('symbol','')).upper()} | leg={_infer_leg(row)} | {row.get('name','')} | best={best['name']} | full ret={_fmt_pct(gm_full['total_return'])} month={_fmt_pct(gm_full['monthlyized'])} pf={gm_full['profit_factor']:.3f} dd={_fmt_pct(gm_full['max_drawdown'])} | delta={_fmt_num(best['full']['pnl_delta'])} retain={_fmt_pct(best['full']['retained_notional_ratio'])}"
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
    for v in variant_leaderboard[:6]:
        lines.append(
            f"- {v['name']} | weighted_score={v['weighted_score']:+.4f} | weighted_2y_month={_fmt_pct(v['weighted_recent_monthly'])} weighted_2y_ret={_fmt_pct(v['weighted_recent_ret'])} weighted_2y_pf_cap={v['weighted_recent_pf']:.3f} | weighted_wf_pnl_delta={_fmt_num(v['weighted_wf_pnl_delta'])} | neg_recent={_fmt_pct(v['weighted_negative_recent'])} neg_full={_fmt_pct(v['weighted_negative_full'])}"
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
        lines.append(f"- 推荐先用 {recommended_variant['name']} 做多资产多路径 sizing research 基线。")
        lines.append("- 原因：它在近2年/WF 没有把搜索空间过早压死，同时比 ETH-core 单收缩更符合当前分支结构。")
        lines.append("- 这轮仍只做 research，不直接同步到 branch runtime。")
    else:
        lines.append("- 这轮先不把任何 overlay 同步到 branch runtime。")
        lines.append("- 原因：虽然多路径重新打开了，但全局近2年/WF 还没形成稳定正增益。")
        lines.append("- 下一步继续保留多资产多方向，再做 entry family frontier，不再先缩成单核。")

    out_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    out_json.write_text(json.dumps({
        "recommended_variant": recommended_variant,
        "candidate_results": candidate_results,
        "variant_leaderboard": variant_leaderboard,
        "candidate_weight_map": candidate_weight_map,
        "live_bridge": {
            "calendar_mode": cal_mode,
            "standardized_events": int(len(live_calendar)),
            "news_mode": news_mode,
            "standardized_messages": int(len(live_news)),
        },
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
