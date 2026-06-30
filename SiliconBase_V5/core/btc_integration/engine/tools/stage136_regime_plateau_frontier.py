from __future__ import annotations

import argparse
import copy
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import research_config_baseline as rcb
from tools import stage46_aggressive_lab as s46
from tools import stage77_mainline_dual_window_lab as s77
from tools import stage78_branch_dual_window_lab as s78
from tools import stage81_mainline_walkforward_lab as s81
from tools import stage82_branch_walkforward_lab as s82
from tools import stage88_strategy_fusion_walkforward as s88
from tools import stage90_event_alpha_matrix as s90

TARGET_MONTHLY_MIN = 0.076
TARGET_MONTHLY_MAX = 0.114


def _pack_or(*funcs: Callable[[pd.DataFrame], pd.Series]) -> Callable[[pd.DataFrame], pd.Series]:
    def _fn(df: pd.DataFrame) -> pd.Series:
        if not funcs:
            return pd.Series(False, index=df.index)
        out = funcs[0](df)
        for fn in funcs[1:]:
            out = out | fn(df)
        return out
    return _fn


PACKS: list[tuple[str, Callable[[pd.DataFrame], pd.Series], str]] = [
    ("base_message_overlay", s88._gate_none, "只保留消息面 overlay，不把事件单独当开仓层"),
    ("macro_drift_alpha", _pack_or(s88._gate_major_event_impulse, s88._gate_post_event_drift), "重大催化先看当根冲击，再看 1-3 根 drift，不盲追第一脚"),
    ("squeeze_followthrough_alpha", _pack_or(s88._gate_event_pressure_continuation, s88._gate_post_event_drift, s88._gate_crowding_reversal), "价格/流向/拥挤共振时做 squeeze continuation"),
    ("reclaim_after_panic_alpha", _pack_or(s88._gate_event_sweep_bridge, s88._gate_liquidity_sweep_reclaim, s88._gate_neutral_revert), "先扫流动性再 reclaim，避免情绪最差点追单"),
    ("hybrid_regime_alpha", _pack_or(s88._gate_major_event_impulse, s88._gate_event_pressure_continuation, s88._gate_event_sweep_bridge, s88._gate_liquidity_sweep_reclaim), "宏观催化 + squeeze + reclaim 的混合状态机"),
    ("fusion_alpha_all", s88._gate_fusion_open, "全融合状态机，作为上限参考"),
]


def _sample_q(trades: Any, target: int) -> float:
    t = max(int(trades or 0), 0)
    if t <= 0:
        return 0.0
    if target <= 0:
        return 1.0
    return max(0.0, min(1.0, t / float(target)))


def _weights(branch: bool) -> tuple[int, int, float, float]:
    if branch:
        return 12, 8, 0.54, 0.46
    return 18, 10, 0.52, 0.48


def _target_monthly(row: dict[str, Any], *, branch: bool) -> float:
    dom = row.get("dominant_gate", {}) or {}
    recent = dom.get("recent_metrics", {}) or {}
    wf = (row.get("walkforward") or {}).get("metrics", {}) or {}
    recent_target, wf_target, rw0, ww0 = _weights(branch)
    rw = rw0 * _sample_q(recent.get("trades"), recent_target)
    ww = ww0 * _sample_q(wf.get("trades"), wf_target)
    denom = rw + ww
    if denom <= 0:
        return 0.0
    return (
        s88._safe_float(recent.get("monthlyized_ret")) * rw
        + s88._safe_float(wf.get("monthlyized_ret")) * ww
    ) / denom


def _extract_main_meta(mods: dict[str, Any]) -> dict[str, float | str]:
    return {
        "track": "base",
        "cooldown": s88._safe_float(mods.get("strategy_params.cooldown_bars") or mods.get("sr_entries.cooldown_bars")),
        "slices": s88._safe_float(mods.get("money_management.capital_slices")),
        "stop": s88._safe_float(mods.get("money_management.stop_loss_pct")),
        "take": s88._safe_float(mods.get("money_management.take_profit_pct")),
        "trail_act": s88._safe_float(mods.get("money_management.trailing_profit.activation_pnl_pct")),
        "trail_gb": s88._safe_float(mods.get("money_management.trailing_profit.giveback_ratio")),
        "lev_min": s88._safe_float(mods.get("portfolio.dynamic_leverage.min")),
        "lev_max": s88._safe_float(mods.get("portfolio.dynamic_leverage.max")),
    }


def _extract_branch_meta(item: dict[str, Any], track: str = "base") -> dict[str, float | str]:
    mods = item.get("mods", {}) or {}
    symbol = str(item.get("symbol", "")).lower()
    family = str(item.get("family", "mixed")).lower()
    stake_key = f"money_management.stake_scale.{symbol}_{family}"
    return {
        "track": track,
        "lookback": s88._safe_float(mods.get("strategy_params.breakout_lookback") or mods.get("sr_entries.lookback_4h")),
        "atr": s88._safe_float(mods.get("strategy_params.breakout_atr_buffer") or mods.get(f"filters.{symbol}_breakout_atr_buffer") or mods.get("sr_entries.zone_atr_mult")),
        "adx": s88._safe_float(mods.get("filters.adx_floor") or mods.get(f"filters.{symbol}_adx_floor") or mods.get("sr_entries.adx_max")),
        "cooldown": s88._safe_float(mods.get("strategy_params.cooldown_bars") or mods.get("sr_entries.cooldown_bars")),
        "stake": s88._safe_float(mods.get(stake_key) or mods.get("sr_entries.stake_scale")),
    }


def _with_meta(item: dict[str, Any], *, track: str, branch: bool) -> dict[str, Any]:
    out = copy.deepcopy(item)
    out["meta"] = _extract_branch_meta(out, track=track) if branch else _extract_main_meta(out.get("mods", {}) or {})
    out["meta"]["track"] = track
    return out


def _dominant_track(gate_name: str) -> str:
    g = str(gate_name or "")
    if g == "base_message_overlay":
        return "base"
    if g == "macro_drift_alpha":
        return "drift"
    if g == "squeeze_followthrough_alpha":
        return "squeeze"
    if g == "reclaim_after_panic_alpha":
        return "reclaim"
    if g == "hybrid_regime_alpha":
        return "hybrid"
    if g == "fusion_alpha_all":
        return "fusion"
    return g or "-"


def _mainline_items() -> list[dict[str, Any]]:
    item_map = {str(item.get("name")): item for item in s88._mainline_items()}
    out: list[dict[str, Any]] = []

    def add(item: dict[str, Any] | None, *, track: str = "base") -> None:
        if item is not None:
            out.append(_with_meta(item, track=track, branch=False))

    add(item_map.get("mainline_live_dynlev_fix8_lock18"), track="base")
    add(item_map.get("mainline_core_satellite_dynlev_fix8_lock18"), track="base")
    add(item_map.get("mainline_live_dynlev_fix10_lock12"), track="squeeze")

    base_live = item_map.get("mainline_live_base")
    if base_live is not None:
        out.append(
            _with_meta(
                s88._make_mainline_variant(
                    base_live,
                    name="mainline_event_drift_fix8_lock14",
                    note="网页经验融入：重大催化先等 drift 确认，收紧冷却但不把保本压得过快。",
                    patch={
                        "strategy_params.cooldown_bars": 4,
                        "portfolio.dynamic_leverage.enabled": True,
                        "portfolio.dynamic_leverage.min": 5.0,
                        "portfolio.dynamic_leverage.max": 9.0,
                        "money_management.mode": "fixed",
                        "money_management.capital_slices": 8,
                        "money_management.stake_mode": "dynamic_equity",
                        "money_management.stake_min_usd": 6500,
                        "money_management.stake_max_usd": 12000,
                        "money_management.stop_loss_pct": 0.13,
                        "money_management.take_profit_pct": 0.92,
                        "money_management.trailing_profit.enabled": True,
                        "money_management.trailing_profit.activation_pnl_pct": 0.24,
                        "money_management.trailing_profit.giveback_ratio": 0.30,
                        "money_management.trailing_profit.min_lock_pnl_pct": 0.04,
                    },
                ),
                track="drift",
                branch=False,
            )
        )
        out.append(
            _with_meta(
                s88._make_mainline_variant(
                    base_live,
                    name="mainline_squeeze_follow_fix10_lock08",
                    note="网页经验融入：挤仓延续模板，允许更细分仓和更快锁盈。",
                    patch={
                        "strategy_params.cooldown_bars": 3,
                        "portfolio.dynamic_leverage.enabled": True,
                        "portfolio.dynamic_leverage.min": 4.0,
                        "portfolio.dynamic_leverage.max": 10.0,
                        "money_management.mode": "fixed",
                        "money_management.capital_slices": 10,
                        "money_management.stake_mode": "dynamic_equity",
                        "money_management.stake_min_usd": 6000,
                        "money_management.stake_max_usd": 11500,
                        "money_management.stop_loss_pct": 0.11,
                        "money_management.take_profit_pct": 1.06,
                        "money_management.trailing_profit.enabled": True,
                        "money_management.trailing_profit.activation_pnl_pct": 0.22,
                        "money_management.trailing_profit.giveback_ratio": 0.26,
                        "money_management.trailing_profit.min_lock_pnl_pct": 0.04,
                    },
                ),
                track="squeeze",
                branch=False,
            )
        )
        out.append(
            _with_meta(
                s88._make_mainline_variant(
                    base_live,
                    name="mainline_reclaim_fix8_lock10",
                    note="网页经验融入：panic 后 reclaim 优先，减少直追，强调收回关键位再开。",
                    patch={
                        "strategy_params.cooldown_bars": 5,
                        "portfolio.dynamic_leverage.enabled": True,
                        "portfolio.dynamic_leverage.min": 4.0,
                        "portfolio.dynamic_leverage.max": 8.0,
                        "money_management.mode": "fixed",
                        "money_management.capital_slices": 8,
                        "money_management.stake_mode": "dynamic_equity",
                        "money_management.stake_min_usd": 6500,
                        "money_management.stake_max_usd": 11000,
                        "money_management.stop_loss_pct": 0.12,
                        "money_management.take_profit_pct": 0.78,
                        "money_management.trailing_profit.enabled": True,
                        "money_management.trailing_profit.activation_pnl_pct": 0.20,
                        "money_management.trailing_profit.giveback_ratio": 0.24,
                        "money_management.trailing_profit.min_lock_pnl_pct": 0.04,
                    },
                ),
                track="reclaim",
                branch=False,
            )
        )
    return out



def _branch_items() -> list[dict[str, Any]]:
    item_map = {str(item.get("name")): item for item in s88._branch_items()}
    out: list[dict[str, Any]] = []

    def add(name: str, *, track: str) -> None:
        item = item_map.get(name)
        if item is not None:
            out.append(_with_meta(item, track=track, branch=True))

    add("eth_breakout_long_follow_lb16_atr050_adx22_s034", track="squeeze")
    add("eth_retest_short_trend_lb20_atr060_adx24_s068", track="reclaim")
    add("eth_short_shock_fast_lb16_atr052_adx22_s078", track="squeeze")
    add("btc_breakout_long_event_lb20_atr060_adx24_s050", track="drift")
    add("btc_retest_short_event_lb20_atr060_adx24_s072", track="reclaim")
    add("btc_dual_fast_trend_dynlev_fix8", track="base")

    eth_long = item_map.get("eth_breakout_long_follow_lb16_atr050_adx22_s034")
    if eth_long is not None:
        out.append(
            _with_meta(
                s88._make_variant(
                    eth_long,
                    name="eth_event_drift_long_lb12_atr046_adx18_s042",
                    note="事件后漂移版本：缩短突破窗，不把 alpha 全压在第一根上。",
                    family="long",
                    patch={
                        "strategy_params.breakout_lookback": 12,
                        "strategy_params.breakout_atr_buffer": 0.46,
                        "strategy_params.cooldown_bars": 3,
                        "filters.adx_floor": 18,
                        "money_management.stake_scale.eth_long": 0.42,
                    },
                ),
                track="drift",
                branch=True,
            )
        )
        out.append(
            _with_meta(
                s88._make_variant(
                    eth_long,
                    name="eth_squeeze_follow_long_lb10_atr042_adx16_s046",
                    note="挤仓延续版本：更快 breakout + 更低 ADX 门槛，但保留样本惩罚。",
                    family="long",
                    patch={
                        "strategy_params.breakout_lookback": 10,
                        "strategy_params.breakout_atr_buffer": 0.42,
                        "strategy_params.cooldown_bars": 3,
                        "filters.adx_floor": 16,
                        "money_management.stake_scale.eth_long": 0.46,
                    },
                ),
                track="squeeze",
                branch=True,
            )
        )

    eth_short = item_map.get("eth_retest_short_trend_lb20_atr060_adx24_s068") or item_map.get("eth_short_shock_fast_lb16_atr052_adx22_s078")
    if eth_short is not None:
        out.append(
            _with_meta(
                s88._make_variant(
                    eth_short,
                    name="eth_reclaim_short_lb18_atr055_adx20_s074",
                    note="panic 后 reclaim 空腿：不追第一脚，优先二次确认。",
                    family="short",
                    patch={
                        "strategy_params.breakout_lookback": 18,
                        "strategy_params.breakout_atr_buffer": 0.55,
                        "strategy_params.cooldown_bars": 5,
                        "filters.adx_floor": 20,
                        "money_management.stake_scale.eth_short": 0.74,
                    },
                ),
                track="reclaim",
                branch=True,
            )
        )

    btc_long = item_map.get("btc_breakout_long_event_lb20_atr060_adx24_s050")
    if btc_long is not None:
        out.append(
            _with_meta(
                s88._make_variant(
                    btc_long,
                    name="btc_event_drift_long_lb18_atr055_adx22_s054",
                    note="BTC 宏观/流向 drift 版本：等确认，不追最急那一脚。",
                    family="long",
                    patch={
                        "strategy_params.breakout_lookback": 18,
                        "filters.btc_breakout_atr_buffer": 0.55,
                        "strategy_params.cooldown_bars": 6,
                        "filters.btc_adx_floor": 22,
                        "money_management.stake_scale.btc_long": 0.54,
                    },
                ),
                track="drift",
                branch=True,
            )
        )
        out.append(
            _with_meta(
                s88._make_variant(
                    btc_long,
                    name="btc_squeeze_follow_long_lb16_atr050_adx20_s058",
                    note="BTC squeeze 版本：短 lookback + 中等 buffer，靠样本/WF 防过拟合。",
                    family="long",
                    patch={
                        "strategy_params.breakout_lookback": 16,
                        "filters.btc_breakout_atr_buffer": 0.50,
                        "strategy_params.cooldown_bars": 5,
                        "filters.btc_adx_floor": 20,
                        "money_management.stake_scale.btc_long": 0.58,
                    },
                ),
                track="squeeze",
                branch=True,
            )
        )

    btc_short = item_map.get("btc_retest_short_event_lb20_atr060_adx24_s072")
    if btc_short is not None:
        out.append(
            _with_meta(
                s88._make_variant(
                    btc_short,
                    name="btc_reclaim_short_lb18_atr055_adx22_s076",
                    note="BTC panic/reclaim 空腿：强调回踩失败再空。",
                    family="short",
                    patch={
                        "strategy_params.breakout_lookback": 18,
                        "filters.btc_breakout_atr_buffer": 0.55,
                        "strategy_params.cooldown_bars": 5,
                        "filters.btc_adx_floor": 22,
                        "money_management.stake_scale.btc_short": 0.76,
                    },
                ),
                track="reclaim",
                branch=True,
            )
        )
    return out



def _run_mainline(root: Path, cfg: dict[str, Any], data: dict[str, pd.DataFrame], item: dict[str, Any], initial_equity: float, full_start: pd.Timestamp, full_end: pd.Timestamp) -> dict[str, Any]:
    from tools import stage59_structural_lab as s59
    trades, trades_feat = s59._run_portfolio_candidate(root, cfg, data, item["mods"])
    full_m = s77._with_window_metrics(s59._metrics_from_trades(trades, initial_equity), full_start, full_end)
    gate_rows: list[dict[str, Any]] = []
    for name, fn, note in PACKS:
        gr = s59._evaluate_gate(trades_feat, name, fn, note, initial_equity)
        gr["recent_metrics"] = s77._with_window_metrics(s78._recent_metrics(gr.get("gated_df"), initial_equity), s78.RECENT_START, full_end)
        gate_rows.append(gr)
    return {"name": item["name"], "note": item.get("note", ""), "meta": copy.deepcopy(item.get("meta", {})), "mods": copy.deepcopy(item.get("mods", {})), "full_metrics": full_m, "gate_rows": gate_rows}



def _run_branch(root: Path, cfg: dict[str, Any], item: dict[str, Any], initial_equity: float) -> dict[str, Any]:
    from tools import stage59_structural_lab as s59
    cfg2 = copy.deepcopy(cfg)
    sym = str(item["symbol"]).lower()
    cfg2.setdefault("data", {})["symbols"] = [sym]
    cfg2.setdefault("data", {})["weights"] = {sym: 1.0}
    cfg2.setdefault("filters", {})["macro_gate_symbols"] = [sym]
    cfg2.setdefault("filters", {})["macro_gate_reference_symbol"] = sym
    data = s46._load_portfolio_data(root, cfg2)
    trades, trades_feat = s59._run_portfolio_candidate(root, cfg2, data, item["mods"])
    full_start, full_end = s78._symbol_window_bounds(root, cfg2, sym, {})
    full_m = s78._with_window_metrics(s59._metrics_from_trades(trades, initial_equity), full_start, full_end)
    gate_rows: list[dict[str, Any]] = []
    for name, fn, note in PACKS:
        gr = s59._evaluate_gate(trades_feat, name, fn, note, initial_equity)
        gr["recent_metrics"] = s78._with_window_metrics(s78._recent_metrics(gr.get("gated_df"), initial_equity), s78.RECENT_START, full_end)
        gate_rows.append(gr)
    return {"symbol": sym, "family": item.get("family", "mixed"), "name": item["name"], "note": item.get("note", ""), "meta": copy.deepcopy(item.get("meta", {})), "mods": copy.deepcopy(item.get("mods", {})), "full_metrics": full_m, "gate_rows": gate_rows, "full_end": full_end}



def _norm_delta(a: float, b: float) -> float:
    aa = abs(float(a))
    bb = abs(float(b))
    scale = max(1e-9, aa, bb)
    return abs(float(a) - float(b)) / scale


def _param_distance(a: dict[str, Any], b: dict[str, Any], *, branch: bool) -> float:
    ma = a.get("meta", {}) or {}
    mb = b.get("meta", {}) or {}
    if branch:
        keys = ["lookback", "atr", "adx", "cooldown", "stake"]
    else:
        keys = ["cooldown", "slices", "stop", "take", "trail_act", "trail_gb", "lev_min", "lev_max"]
    vals = []
    for k in keys:
        vals.append(_norm_delta(s88._safe_float(ma.get(k)), s88._safe_float(mb.get(k))))
    return sum(vals) / max(1, len(vals))



def _cluster_bucket(row: dict[str, Any], *, branch: bool) -> tuple[str, ...]:
    meta = row.get("meta", {}) or {}
    track = str(meta.get("track") or "base")
    if branch:
        return (str(row.get("symbol") or "-"), str(row.get("family") or "-"), track)
    return (track,)



def _plateau_summary(row: dict[str, Any], rows: list[dict[str, Any]], *, branch: bool) -> dict[str, Any]:
    bucket = _cluster_bucket(row, branch=branch)
    peers = []
    for other in rows:
        if other is row:
            continue
        if _cluster_bucket(other, branch=branch) != bucket:
            continue
        dist = _param_distance(row, other, branch=branch)
        if dist <= (0.42 if branch else 0.48):
            peers.append((dist, other))
    peers.sort(key=lambda x: x[0])
    peers = peers[:4]
    if not peers:
        return {"neighbor_count": 0, "plateau": 0.0, "peer_target_monthly": 0.0}
    vals = []
    for _, other in peers:
        vals.append(_target_monthly(other, branch=branch))
    peer_mean = sum(vals) / len(vals)
    own = _target_monthly(row, branch=branch)
    quality = max(0.0, min(1.0, peer_mean / max(TARGET_MONTHLY_MIN, 1e-9)))
    similarity = max(0.0, min(1.0, 1.0 - sum(d for d, _ in peers) / len(peers)))
    own_alignment = max(0.0, min(1.0, min(own, peer_mean) / max(abs(own), abs(peer_mean), TARGET_MONTHLY_MIN, 1e-9)))
    plateau = (0.46 * quality) + (0.34 * similarity) + (0.20 * own_alignment)
    plateau *= max(0.35, min(1.0, len(peers) / 2.0))
    return {"neighbor_count": len(peers), "plateau": plateau, "peer_target_monthly": peer_mean}



def _overfit_penalty(row: dict[str, Any], *, branch: bool) -> float:
    dom = row.get("dominant_gate", {}) or {}
    recent = dom.get("recent_metrics", {}) or {}
    wf = (row.get("walkforward") or {}).get("metrics", {}) or {}
    recent_trades = int(recent.get("trades", 0) or 0)
    wf_trades = int(wf.get("trades", 0) or 0)
    recent_pf = s88._safe_float(recent.get("pf"))
    wf_pf = s88._safe_float(wf.get("pf"))
    penalty = 0.0
    if recent_trades < (6 if branch else 10) and recent_pf >= 3.0:
        penalty += 34.0 if branch else 28.0
    if wf_trades < (5 if branch else 8) and wf_pf >= 2.5:
        penalty += 38.0 if branch else 32.0
    if recent_trades <= 2 or wf_trades <= 2:
        penalty += 44.0 if branch else 36.0
    if s88._safe_float(recent.get("ret")) > 0 and s88._safe_float(wf.get("ret")) < 0:
        penalty += 30.0 if branch else 26.0
    if abs(s88._safe_float(recent.get("monthlyized_ret")) - s88._safe_float(wf.get("monthlyized_ret"))) >= 0.02:
        penalty += 14.0 if branch else 12.0
    return penalty



def _track_bonus(row: dict[str, Any]) -> float:
    track = str((row.get("meta") or {}).get("track") or "base")
    dom_track = _dominant_track(str((row.get("dominant_gate") or {}).get("gate_name") or ""))
    if track == dom_track:
        return 20.0
    if track == "base" and dom_track == "base":
        return 12.0
    if track == "reclaim" and dom_track in {"hybrid", "fusion"}:
        return 8.0
    if track == "drift" and dom_track in {"hybrid", "fusion"}:
        return 8.0
    if track == "squeeze" and dom_track in {"hybrid", "fusion"}:
        return 8.0
    return -6.0 if dom_track != "base" and track == "base" else 0.0



def _frontier_score(row: dict[str, Any], rows: list[dict[str, Any]], *, branch: bool) -> float:
    base = s90._branch_alpha_score(row) if branch else s90._mainline_alpha_score(row)
    dom = row.get("dominant_gate", {}) or {}
    recent = dom.get("recent_metrics", {}) or {}
    wf = (row.get("walkforward") or {}).get("metrics", {}) or {}
    full = row.get("full_metrics", {}) or {}
    month = _target_monthly(row, branch=branch)
    recent_target, wf_target, _, _ = _weights(branch)
    recent_trades = int(recent.get("trades", 0) or 0)
    wf_trades = int(wf.get("trades", 0) or 0)
    recent_pf = s90._pf_for_score(recent.get("pf"), recent_trades, recent_target, 4.0 if branch else 4.5)
    wf_pf = s90._pf_for_score(wf.get("pf"), wf_trades, wf_target, 3.5 if branch else 4.0)
    gap = max(0.0, TARGET_MONTHLY_MIN - month)
    divergence = abs(s88._safe_float(recent.get("monthlyized_ret")) - s88._safe_float(wf.get("monthlyized_ret")))
    plateau = row.get("plateau", {}) or {}
    sixy_soft_penalty = 0.0
    if s88._safe_float(full.get("ret")) < 0 and month < 0.03:
        sixy_soft_penalty = abs(s88._safe_float(full.get("ret"))) * (36.0 if branch else 26.0)
    innovation_bonus = 0.0
    if str(dom.get("gate_name")) != "base_message_overlay" and recent_trades >= max(6, int(recent_target * 0.6)) and wf_trades >= max(4, int(wf_target * 0.6)):
        innovation_bonus += 24.0 if branch else 20.0
    if (row.get("walkforward") or {}).get("positive_folds", 0) >= 3:
        innovation_bonus += 16.0 if branch else 12.0
    return float(
        base
        + month * 2600.0
        + recent_pf * (62.0 if branch else 54.0)
        + wf_pf * (86.0 if branch else 78.0)
        + s88._safe_float(plateau.get("plateau")) * (140.0 if branch else 118.0)
        + innovation_bonus
        + _track_bonus(row)
        - gap * 1380.0
        - divergence * (280.0 if branch else 240.0)
        - abs(s88._safe_float(wf.get("maxdd"))) * (94.0 if branch else 84.0)
        - max(0.0, 0.55 - _sample_q(recent_trades, recent_target)) * (102.0 if branch else 78.0)
        - max(0.0, 0.60 - _sample_q(wf_trades, wf_target)) * (126.0 if branch else 112.0)
        - _overfit_penalty(row, branch=branch)
        - sixy_soft_penalty
    )



def _frontier_label(row: dict[str, Any], *, branch: bool) -> str:
    dom = row.get("dominant_gate", {}) or {}
    recent = dom.get("recent_metrics", {}) or {}
    wf = (row.get("walkforward") or {}).get("metrics", {}) or {}
    month = _target_monthly(row, branch=branch)
    plateau = row.get("plateau", {}) or {}
    recent_target, wf_target, _, _ = _weights(branch)
    recent_trades = int(recent.get("trades", 0) or 0)
    wf_trades = int(wf.get("trades", 0) or 0)
    recent_pf = s88._safe_float(recent.get("pf"))
    wf_pf = s88._safe_float(wf.get("pf"))
    wf_dd = abs(s88._safe_float(wf.get("maxdd")))
    pos_folds = int((row.get("walkforward") or {}).get("positive_folds", 0) or 0)
    event_share = s90._event_fold_share(row.get("walkforward") or {})
    plateau_q = s88._safe_float(plateau.get("plateau"))
    overfit = _overfit_penalty(row, branch=branch)
    if month >= TARGET_MONTHLY_MIN and plateau_q >= 0.45 and recent_trades >= recent_target and wf_trades >= wf_target and recent_pf >= 1.15 and wf_pf >= 1.08 and wf_dd <= 0.28 and pos_folds >= 3 and overfit <= 24.0:
        return "pass"
    if month >= 0.02 and plateau_q >= 0.20 and recent_trades >= max(6, recent_target // 2) and wf_trades >= max(5, wf_target // 2) and recent_pf >= 1.00 and wf_pf >= 0.95 and wf_dd <= 0.40:
        return "hold"
    if event_share >= 0.20 and plateau_q >= 0.08 and wf_trades >= 4 and wf_pf >= 0.90 and wf_dd <= 0.45:
        return "reserve+"
    return "reserve"



def _payload_row(row: dict[str, Any], *, branch: bool) -> dict[str, Any]:
    dom = row.get("dominant_gate", {}) or {}
    recent = dom.get("recent_metrics", {}) or {}
    wf = (row.get("walkforward") or {}).get("metrics", {}) or {}
    full = row.get("full_metrics", {}) or {}
    plateau = row.get("plateau", {}) or {}
    month = _target_monthly(row, branch=branch)
    return {
        "name": row.get("name"),
        "symbol": row.get("symbol"),
        "family": row.get("family"),
        "track": str((row.get("meta") or {}).get("track") or "base"),
        "dominant_gate": dom.get("gate_name"),
        "dominant_track": _dominant_track(str(dom.get("gate_name") or "")),
        "decision": row.get("decision"),
        "frontier_score": s88._safe_float(row.get("alpha_score")),
        "target_monthly": month,
        "gap_to_floor": max(0.0, TARGET_MONTHLY_MIN - month),
        "full_ret": s88._safe_float(full.get("ret")),
        "full_monthly": s88._safe_float(full.get("monthlyized_ret")),
        "full_trades": int(full.get("trades", 0) or 0),
        "full_pf": s88._safe_float(full.get("pf")),
        "recent_ret": s88._safe_float(recent.get("ret")),
        "recent_monthly": s88._safe_float(recent.get("monthlyized_ret")),
        "recent_trades": int(recent.get("trades", 0) or 0),
        "recent_pf": s88._safe_float(recent.get("pf")),
        "wf_ret": s88._safe_float(wf.get("ret")),
        "wf_monthly": s88._safe_float(wf.get("monthlyized_ret")),
        "wf_trades": int(wf.get("trades", 0) or 0),
        "wf_pf": s88._safe_float(wf.get("pf")),
        "wf_dd": s88._safe_float(wf.get("maxdd")),
        "positive_folds": int((row.get("walkforward") or {}).get("positive_folds", 0) or 0),
        "total_folds": int((row.get("walkforward") or {}).get("total_folds", 0) or 0),
        "event_fold_share": s90._event_fold_share(row.get("walkforward") or {}),
        "plateau": s88._safe_float(plateau.get("plateau")),
        "neighbor_count": int(plateau.get("neighbor_count", 0) or 0),
        "peer_target_monthly": s88._safe_float(plateau.get("peer_target_monthly")),
        "overfit_penalty": _overfit_penalty(row, branch=branch),
    }



def _write_report(path_txt: Path, path_json: Path, main_rows: list[dict[str, Any]], branch_rows: list[dict[str, Any]]) -> None:
    main_payload = [_payload_row(r, branch=False) for r in main_rows]
    branch_payload = [_payload_row(r, branch=True) for r in branch_rows]
    lines: list[str] = []
    lines.append("Stage136 网页经验 + 参数平台稳健前沿")
    lines.append("原则：funding/OI/挤仓/期权波动率经验落成 drift / squeeze / reclaim 三类轨道；排序加入 plateau 稳健度，压制孤点参数。")
    lines.append(f"目标区间：{TARGET_MONTHLY_MIN*100:.1f}% - {TARGET_MONTHLY_MAX*100:.1f}% / 月")
    lines.append("")
    lines.append("=== 主线 ===")
    for row in main_payload:
        lines.append(
            f"- {row['name']}: track={row['track']} | dom={row['dominant_track']} | target_monthly={row['target_monthly']*100:.2f}% | 6年={row['full_monthly']*100:.2f}%/{row['full_trades']}笔/PF{row['full_pf']:.3f} | 近2年={row['recent_monthly']*100:.2f}%/{row['recent_trades']}笔/PF{row['recent_pf']:.3f} | WF={row['wf_monthly']*100:.2f}%/{row['wf_trades']}笔/PF{row['wf_pf']:.3f} | plateau={row['plateau']:.2f}/{row['neighbor_count']} | decision={row['decision']}"
        )
    lines.append("")
    lines.append("=== 分支（BTC/ETH） ===")
    for row in branch_payload:
        fam = row.get("family") or "-"
        sym = row.get("symbol") or "-"
        lines.append(
            f"- {sym}|{fam}|{row['name']}: track={row['track']} | dom={row['dominant_track']} | target_monthly={row['target_monthly']*100:.2f}% | 6年={row['full_monthly']*100:.2f}%/{row['full_trades']}笔/PF{row['full_pf']:.3f} | 近2年={row['recent_monthly']*100:.2f}%/{row['recent_trades']}笔/PF{row['recent_pf']:.3f} | WF={row['wf_monthly']*100:.2f}%/{row['wf_trades']}笔/PF{row['wf_pf']:.3f} | plateau={row['plateau']:.2f}/{row['neighbor_count']} | decision={row['decision']}"
        )
    lines.append("")
    lines.append("=== 结论 ===")
    if main_payload:
        top = main_payload[0]
        lines.append(f"- 主线第一名: {top['name']} | target_monthly={top['target_monthly']*100:.2f}% | track={top['track']} | plateau={top['plateau']:.2f} | gap_to_7.6={top['gap_to_floor']*100:.2f}%")
    if branch_payload:
        top = branch_payload[0]
        lines.append(f"- 分支第一名: {top['name']} | target_monthly={top['target_monthly']*100:.2f}% | track={top['track']} | plateau={top['plateau']:.2f} | gap_to_7.6={top['gap_to_floor']*100:.2f}%")
    lines.append("- 目标不是单点最优，而是找近2年/WF 同向、且邻近参数也站得住的参数平台。")
    lines.append("- SOL 路径不删除，但这轮不占算力；先把 BTC/ETH 可交易轨道做实。")

    path_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    path_json.write_text(
        json.dumps(
            {
                "target_monthly_min": TARGET_MONTHLY_MIN,
                "target_monthly_max": TARGET_MONTHLY_MAX,
                "packs": [x[0] for x in PACKS],
                "mainline": main_payload,
                "branch": branch_payload,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )



def main() -> None:
    ap = argparse.ArgumentParser(description="Stage136 regime plateau frontier")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    reports_raw = root / "reports" / "research_raw"
    reports_raw.mkdir(parents=True, exist_ok=True)

    cfg = rcb.load_research_base_config(root)
    initial_equity = float(cfg.get("portfolio", {}).get("initial_equity", 100000.0))

    data = s46._load_portfolio_data(root, cfg)
    full_start, full_end = s77._window_bounds_from_data(data)

    mainline_items_all = {str(item.get("name")): item for item in s88._mainline_items()}
    ref_item = mainline_items_all.get("mainline_live_base")
    if ref_item is None:
        raise SystemExit("missing mainline reference: mainline_live_base")
    ref_row = _run_mainline(root, cfg, data, _with_meta(ref_item, track="base", branch=False), initial_equity, full_start, full_end)

    main_rows: list[dict[str, Any]] = []
    main_items = _mainline_items()
    for i, item in enumerate(main_items, 1):
        print(f"[stage136] mainline {i}/{len(main_items)} {item['name']}", flush=True)
        row = _run_mainline(root, cfg, data, item, initial_equity, full_start, full_end)
        row["walkforward"] = s81._wf_result(row, ref_row, initial_equity, s81.RECENT_START, full_end)
        row["dominant_gate"] = s90._dominant_gate(row, branch=False)
        main_rows.append(row)
    for row in main_rows:
        row["plateau"] = _plateau_summary(row, main_rows, branch=False)
    for row in main_rows:
        row["alpha_score"] = _frontier_score(row, main_rows, branch=False)
        row["decision"] = _frontier_label(row, branch=False)
    main_rows.sort(key=lambda r: float(r.get("alpha_score", 0.0)), reverse=True)

    branch_rows: list[dict[str, Any]] = []
    branch_items = _branch_items()
    for i, item in enumerate(branch_items, 1):
        print(f"[stage136] branch {i}/{len(branch_items)} {item['name']}", flush=True)
        row = _run_branch(root, cfg, item, initial_equity)
        row["walkforward"] = s82._wf_result(row, initial_equity, s78.RECENT_START, row["full_end"])
        row["dominant_gate"] = s90._dominant_gate(row, branch=True)
        branch_rows.append(row)
    for row in branch_rows:
        row["plateau"] = _plateau_summary(row, branch_rows, branch=True)
    for row in branch_rows:
        row["alpha_score"] = _frontier_score(row, branch_rows, branch=True)
        row["decision"] = _frontier_label(row, branch=True)
    branch_rows.sort(key=lambda r: float(r.get("alpha_score", 0.0)), reverse=True)

    main_txt = reports_raw / "stage90_mainline_event_alpha_matrix_latest.txt"
    main_json = reports_raw / "stage90_mainline_event_alpha_matrix_latest.json"
    branch_txt = reports_raw / "stage91_branch_event_alpha_matrix_latest.txt"
    branch_json = reports_raw / "stage91_branch_event_alpha_matrix_latest.json"
    s90._write_mainline(main_txt, main_json, main_rows)
    s90._write_branch(branch_txt, branch_json, branch_rows)

    frontier_txt = reports_raw / "stage136_regime_plateau_frontier_latest.txt"
    frontier_json = reports_raw / "stage136_regime_plateau_frontier_latest.json"
    _write_report(frontier_txt, frontier_json, main_rows, branch_rows)

    manifest = {
        "mode": "regime_plateau_frontier",
        "packs": [x[0] for x in PACKS],
        "mainline_names": [str(x.get("name")) for x in main_items],
        "branch_names": [str(x.get("name")) for x in branch_items],
        "outputs": {
            "stage90_txt": str(main_txt),
            "stage90_json": str(main_json),
            "stage91_txt": str(branch_txt),
            "stage91_json": str(branch_json),
            "frontier_txt": str(frontier_txt),
            "frontier_json": str(frontier_json),
        },
    }
    (reports_raw / "stage136_regime_plateau_manifest_latest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(frontier_txt)
    print(frontier_json)
    print(reports_raw / "stage136_regime_plateau_manifest_latest.json")


if __name__ == "__main__":
    main()
