from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


try:
    from tools import research_config_baseline as rcb
    from tools import stage46_aggressive_lab as s46
    from tools import stage55_broad_dual_track as s55
    from tools import stage59_structural_lab as s59
    from tools import stage75_mainline_event_state_lab as s75
    from tools import stage76_branch_event_state_lab as s76
    from tools import stage77_mainline_dual_window_lab as s77
    from tools import stage78_branch_dual_window_lab as s78
    from tools import stage81_mainline_walkforward_lab as s81
    from tools import stage82_branch_walkforward_lab as s82
except Exception as exc:
    raise SystemExit("缺少 stage46/55/59/75/76/77/78/81/82 模块，请先保留此前补丁。") from exc


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
    except Exception:
        return default
    if math.isnan(v):
        return default
    return v


def _fmt_pct(x: Any) -> str:
    try:
        return f"{float(x) * 100:.2f}%"
    except Exception:
        return "NA"


def _bool_col(df: pd.DataFrame, name: str, default: bool = False) -> pd.Series:
    if name in df.columns:
        return df[name].fillna(default).astype(bool)
    return pd.Series(default, index=df.index)


def _num_col(df: pd.DataFrame, name: str, default: float = 0.0) -> pd.Series:
    if name in df.columns:
        return pd.to_numeric(df[name], errors="coerce").fillna(default)
    return pd.Series(default, index=df.index, dtype=float)


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, pd.DataFrame):
        return {"rows": int(len(obj)), "columns": list(obj.columns)}
    if isinstance(obj, pd.Series):
        return obj.tolist()
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if hasattr(obj, "isoformat"):
        try:
            return obj.isoformat()
        except Exception:
            pass
    try:
        import numpy as np  # type: ignore

        if isinstance(obj, (np.integer, np.floating, np.bool_)):
            return obj.item()
        if isinstance(obj, np.ndarray):
            return obj.tolist()
    except Exception:
        pass
    return obj


def _strip_gate_payload(best_gate: dict[str, Any]) -> dict[str, Any]:
    out = dict(best_gate or {})
    gated_df = out.pop("gated_df", None)
    if isinstance(gated_df, pd.DataFrame):
        out["gated_rows"] = int(len(gated_df))
        out["gated_columns"] = list(gated_df.columns)[:12]
    return _json_safe(out)


# -----------------------------
# Fusion gates
# -----------------------------

def _gate_none(df: pd.DataFrame) -> pd.Series:
    return pd.Series(True, index=df.index)


def _event_flags(df: pd.DataFrame) -> dict[str, pd.Series]:
    blocked = _bool_col(df, "event_blocked", False)
    identified = _bool_col(df, "event_identified", False) | blocked
    positive = _bool_col(df, "event_positive", False)
    two_sided = _bool_col(df, "event_two_sided", False)
    observation = _bool_col(df, "event_observation", False)
    negative = _bool_col(df, "event_negative", False) | blocked
    return {
        "blocked": blocked,
        "identified": identified,
        "positive": positive,
        "two_sided": two_sided,
        "observation": observation,
        "negative": negative,
    }


def _gate_neutral_revert(df: pd.DataFrame) -> pd.Series:
    neutral = _bool_col(df, "neutral_event", True)
    wick = _bool_col(df, "wick_revert_ok", False)
    spike = _bool_col(df, "spike_fade_ok", False)
    return neutral & (wick | spike)


def _gate_major_event_impulse(df: pd.DataFrame) -> pd.Series:
    side = df.get("side", pd.Series(index=df.index, dtype=str)).astype(str).str.upper()
    flags = _event_flags(df)
    flow = _bool_col(df, "flow_aligned", True)
    crowded = _bool_col(df, "risk_crowded_long", False)
    oi_high = _bool_col(df, "risk_oi_high", False)
    range_rel = _num_col(df, "range_rel", 1.0)
    vol_rel = _num_col(df, "vol_rel", 1.0)
    bar_ret = _num_col(df, "bar_ret", 0.0)
    close_loc = _num_col(df, "close_loc", 0.5)
    upper_wick = _num_col(df, "upper_wick_ratio", 0.0)
    lower_wick = _num_col(df, "lower_wick_ratio", 0.0)

    impulse = (range_rel >= 1.12) | (vol_rel >= 1.08) | (bar_ret.abs() >= 0.007)
    long_event_ok = flags["positive"] | flags["two_sided"] | (flags["observation"] & (close_loc >= 0.70) & (bar_ret >= 0.003))
    short_event_ok = flags["negative"] | flags["two_sided"] | (flags["observation"] & (close_loc <= 0.30) & (bar_ret <= -0.003))
    long_ok = (
        (side == "LONG")
        & flags["identified"]
        & long_event_ok
        & flow
        & ~crowded
        & ~oi_high
        & impulse
        & (close_loc >= 0.64)
        & (bar_ret >= 0.002)
        & (upper_wick <= 0.34)
    )
    short_ok = (
        (side == "SHORT")
        & flags["identified"]
        & short_event_ok
        & flow
        & (crowded | oi_high | flags["blocked"])
        & impulse
        & (close_loc <= 0.36)
        & (bar_ret <= -0.002)
        & (lower_wick <= 0.34)
    )
    return long_ok | short_ok


def _gate_post_event_drift(df: pd.DataFrame) -> pd.Series:
    side = df.get("side", pd.Series(index=df.index, dtype=str)).astype(str).str.upper()
    flags = _event_flags(df)
    flow = _bool_col(df, "flow_aligned", True)
    crowded = _bool_col(df, "risk_crowded_long", False)
    oi_high = _bool_col(df, "risk_oi_high", False)
    range_rel = _num_col(df, "range_rel", 1.0)
    vol_rel = _num_col(df, "vol_rel", 1.0)
    bar_ret = _num_col(df, "bar_ret", 0.0)
    close_loc = _num_col(df, "close_loc", 0.5)

    long_event_ok = flags["positive"] | flags["two_sided"] | (flags["observation"] & (close_loc >= 0.60) & (bar_ret >= 0.0))
    short_event_ok = flags["negative"] | flags["two_sided"] | (flags["observation"] & (close_loc <= 0.40) & (bar_ret <= 0.0))
    long_drift = (
        (side == "LONG")
        & flags["identified"]
        & long_event_ok
        & flow
        & ~crowded
        & ~oi_high
        & (range_rel >= 0.92)
        & (vol_rel >= 0.95)
        & (close_loc >= 0.58)
        & (bar_ret >= 0.0005)
    )
    short_drift = (
        (side == "SHORT")
        & flags["identified"]
        & short_event_ok
        & flow
        & (crowded | oi_high | flags["blocked"])
        & (range_rel >= 0.92)
        & (vol_rel >= 0.95)
        & (close_loc <= 0.42)
        & (bar_ret <= -0.0005)
    )
    return long_drift | short_drift


def _gate_crowding_reversal(df: pd.DataFrame) -> pd.Series:
    side = df.get("side", pd.Series(index=df.index, dtype=str)).astype(str).str.upper()
    neutral = _bool_col(df, "neutral_event", True)
    crowded = _bool_col(df, "risk_crowded_long", False)
    oi_high = _bool_col(df, "risk_oi_high", False)
    wick = _bool_col(df, "wick_revert_ok", False)
    spike = _bool_col(df, "spike_fade_ok", False)
    range_rel = _num_col(df, "range_rel", 1.0)
    close_loc = _num_col(df, "close_loc", 0.5)

    short_rev = (side == "SHORT") & neutral & (crowded | oi_high) & (wick | spike | (close_loc <= 0.44)) & (range_rel >= 1.02)
    long_rev = (side == "LONG") & neutral & ~(crowded | oi_high) & (wick | spike | (close_loc >= 0.56)) & (range_rel >= 1.02)
    return short_rev | long_rev


def _gate_liquidity_sweep_reclaim(df: pd.DataFrame) -> pd.Series:
    side = df.get("side", pd.Series(index=df.index, dtype=str)).astype(str).str.upper()
    neutral = _bool_col(df, "neutral_event", True)
    crowded = _bool_col(df, "risk_crowded_long", False)
    oi_high = _bool_col(df, "risk_oi_high", False)
    wick = _bool_col(df, "wick_revert_ok", False)
    spike = _bool_col(df, "spike_fade_ok", False)
    range_rel = _num_col(df, "range_rel", 1.0)
    close_loc = _num_col(df, "close_loc", 0.5)
    body_ratio = _num_col(df, "body_ratio", 0.5)

    long_reclaim = (side == "LONG") & neutral & ~crowded & ~oi_high & (wick | spike) & (range_rel >= 1.08) & (close_loc >= 0.57) & (body_ratio <= 0.58)
    short_reclaim = (side == "SHORT") & neutral & (crowded | oi_high) & (wick | spike) & (range_rel >= 1.08) & (close_loc <= 0.43) & (body_ratio <= 0.58)
    return long_reclaim | short_reclaim


def _gate_event_pressure_continuation(df: pd.DataFrame) -> pd.Series:
    side = df.get("side", pd.Series(index=df.index, dtype=str)).astype(str).str.upper()
    flags = _event_flags(df)
    flow = _bool_col(df, "flow_aligned", True)
    crowded = _bool_col(df, "risk_crowded_long", False)
    oi_high = _bool_col(df, "risk_oi_high", False)
    range_rel = _num_col(df, "range_rel", 1.0)
    vol_rel = _num_col(df, "vol_rel", 1.0)
    close_loc = _num_col(df, "close_loc", 0.5)
    bar_ret = _num_col(df, "bar_ret", 0.0)
    body_ratio = _num_col(df, "body_ratio", 0.5)

    long_event_ok = flags["positive"] | flags["two_sided"] | (flags["observation"] & (close_loc >= 0.58))
    short_event_ok = flags["negative"] | flags["two_sided"] | (flags["observation"] & (close_loc <= 0.42))
    long_ok = (
        (side == "LONG")
        & flags["identified"]
        & long_event_ok
        & flow
        & ~crowded
        & ~oi_high
        & (range_rel >= 0.88)
        & (vol_rel >= 0.88)
        & (close_loc >= 0.54)
        & (bar_ret >= -0.0010)
        & (body_ratio >= 0.22)
    )
    short_ok = (
        (side == "SHORT")
        & flags["identified"]
        & short_event_ok
        & flow
        & (crowded | oi_high | flags["blocked"])
        & (range_rel >= 0.88)
        & (vol_rel >= 0.88)
        & (close_loc <= 0.46)
        & (bar_ret <= 0.0010)
        & (body_ratio >= 0.22)
    )
    return long_ok | short_ok


def _gate_event_sweep_bridge(df: pd.DataFrame) -> pd.Series:
    side = df.get("side", pd.Series(index=df.index, dtype=str)).astype(str).str.upper()
    flags = _event_flags(df)
    flow = _bool_col(df, "flow_aligned", True)
    crowded = _bool_col(df, "risk_crowded_long", False)
    oi_high = _bool_col(df, "risk_oi_high", False)
    wick = _bool_col(df, "wick_revert_ok", False)
    spike = _bool_col(df, "spike_fade_ok", False)
    range_rel = _num_col(df, "range_rel", 1.0)
    vol_rel = _num_col(df, "vol_rel", 1.0)
    close_loc = _num_col(df, "close_loc", 0.5)
    body_ratio = _num_col(df, "body_ratio", 0.5)

    long_event_ok = flags["positive"] | flags["two_sided"] | (flags["observation"] & (close_loc >= 0.55))
    short_event_ok = flags["negative"] | flags["two_sided"] | (flags["observation"] & (close_loc <= 0.45))
    long_ok = (
        (side == "LONG")
        & flags["identified"]
        & long_event_ok
        & flow
        & ~crowded
        & ~oi_high
        & (wick | spike)
        & (range_rel >= 0.98)
        & (vol_rel >= 0.90)
        & (close_loc >= 0.52)
        & (body_ratio <= 0.68)
    )
    short_ok = (
        (side == "SHORT")
        & flags["identified"]
        & short_event_ok
        & flow
        & (crowded | oi_high | flags["blocked"])
        & (wick | spike)
        & (range_rel >= 0.98)
        & (vol_rel >= 0.90)
        & (close_loc <= 0.48)
        & (body_ratio <= 0.68)
    )
    return long_ok | short_ok


def _gate_fusion_open(df: pd.DataFrame) -> pd.Series:
    return _gate_neutral_revert(df) | _gate_major_event_impulse(df) | _gate_post_event_drift(df) | _gate_crowding_reversal(df) | _gate_liquidity_sweep_reclaim(df) | _gate_event_pressure_continuation(df) | _gate_event_sweep_bridge(df)


FUSION_GATES: list[tuple[str, Callable[[pd.DataFrame], pd.Series], str]] = [
    ("base_message_overlay", _gate_none, "只保留消息面 overlay，不加开仓条件"),
    ("neutral_revert", _gate_neutral_revert, "无重大消息时，插针/过冲回归"),
    ("major_event_impulse", _gate_major_event_impulse, "重大消息可直接成为开仓依据，但必须有方向冲击 + 流向/拥挤确认"),
    ("post_event_drift", _gate_post_event_drift, "重大消息后的扩散/漂移继续跟随，不只盯发布当根"),
    ("crowding_reversal", _gate_crowding_reversal, "拥挤 + 结构失衡时做反身性反转"),
    ("liquidity_sweep_reclaim", _gate_liquidity_sweep_reclaim, "扫高/扫低后重新收回关键位，做流动性回收反转"),
    ("fusion_open", _gate_fusion_open, "趋势突破 + 重大消息开仓 + 事件漂移 + 拥挤反转 + 扫损回收 的融合状态机"),
]


# -----------------------------
# Candidate packs
# -----------------------------

def _make_mainline_variant(base: dict[str, Any], *, name: str, note: str, patch: dict[str, Any]) -> dict[str, Any]:
    mods = copy.deepcopy(base.get("mods", {}))
    for k, v in patch.items():
        mods[k] = v
    return {
        "name": name,
        "note": note,
        "mods": mods,
    }


def _mainline_items() -> list[dict[str, Any]]:
    dedup: dict[str, dict[str, Any]] = {}
    for item in s75._mainline_items():
        dedup[str(item.get("name"))] = copy.deepcopy(item)

    base_ref = dedup.get("combo_sr_soft_adx26_cd6_lb24_zone028_ref")
    base_fast = dedup.get("combo_sr_soft_adx28_cd6_lb24_zone028") or base_ref
    if base_ref is not None:
        for item in [
            _make_mainline_variant(
                base_ref,
                name="combo_sr_soft_adx26_cd5_lb24_zone028",
                note="同参数快版：只降 cooldown，专门检查能否不明显伤 PF 就提频",
                patch={
                    "sr_entries.adx_max": 26.0,
                    "sr_entries.cooldown_bars": 5,
                    "sr_entries.lookback_4h": 24,
                    "sr_entries.zone_atr_mult": 0.28,
                },
            ),
            _make_mainline_variant(
                base_ref,
                name="combo_sr_soft_adx26_cd6_lb22_zone026",
                note="同标准不同参数：缩短 lookback + 收窄 zone，看提频是否更干净",
                patch={
                    "sr_entries.adx_max": 26.0,
                    "sr_entries.cooldown_bars": 6,
                    "sr_entries.lookback_4h": 22,
                    "sr_entries.zone_atr_mult": 0.26,
                },
            ),
        ]:
            dedup[item["name"]] = item

    if base_fast is not None:
        for item in [
            _make_mainline_variant(
                base_fast,
                name="combo_sr_soft_adx28_cd5_lb24_zone028",
                note="同参数快版：在 adx28 基础上再降 cooldown，冲更高主线频次",
                patch={
                    "sr_entries.adx_max": 28.0,
                    "sr_entries.cooldown_bars": 5,
                    "sr_entries.lookback_4h": 24,
                    "sr_entries.zone_atr_mult": 0.28,
                },
            ),
            _make_mainline_variant(
                base_fast,
                name="combo_sr_soft_adx28_cd6_lb22_zone026",
                note="不同参数同标准：保持 cooldown=6，缩 lookback/zone 测结构化提频",
                patch={
                    "sr_entries.adx_max": 28.0,
                    "sr_entries.cooldown_bars": 6,
                    "sr_entries.lookback_4h": 22,
                    "sr_entries.zone_atr_mult": 0.26,
                },
            ),
        ]:
            dedup[item["name"]] = item

    base_live = dedup.get("mainline_live_base")
    base_sat = dedup.get("mainline_core_satellite_event30")
    if base_live is not None:
        for item in [
            _make_mainline_variant(
                base_live,
                name="mainline_live_dynlev_fix8_lock18",
                note="结构版：动态杠杆 + 8切片动态权益 + 硬止损/止盈/跟踪止盈，不再只靠参数放松提频",
                patch={
                    "portfolio.dynamic_leverage.enabled": True,
                    "portfolio.dynamic_leverage.min": 4.0,
                    "portfolio.dynamic_leverage.max": 8.0,
                    "portfolio.dynamic_leverage.adx_low": 18.0,
                    "portfolio.dynamic_leverage.adx_high": 36.0,
                    "money_management.mode": "fixed",
                    "money_management.capital_slices": 8,
                    "money_management.stake_mode": "dynamic_equity",
                    "money_management.stake_min_usd": 9000,
                    "money_management.stake_max_usd": 14000,
                    "money_management.stop_loss_pct": 0.18,
                    "money_management.take_profit_pct": 1.50,
                    "money_management.trailing_profit.enabled": True,
                    "money_management.trailing_profit.activation_pnl_pct": 0.70,
                    "money_management.trailing_profit.giveback_ratio": 0.35,
                    "money_management.trailing_profit.min_lock_pnl_pct": 0.18,
                },
            ),
            _make_mainline_variant(
                base_live,
                name="mainline_live_dynlev_fix10_lock12",
                note="结构版：更细分仓 + 更快保本，检查固定仓位投资和严格保护单是否更适合当前机构化节奏",
                patch={
                    "portfolio.dynamic_leverage.enabled": True,
                    "portfolio.dynamic_leverage.min": 4.0,
                    "portfolio.dynamic_leverage.max": 7.0,
                    "portfolio.dynamic_leverage.adx_low": 16.0,
                    "portfolio.dynamic_leverage.adx_high": 32.0,
                    "money_management.mode": "fixed",
                    "money_management.capital_slices": 10,
                    "money_management.stake_mode": "dynamic_equity",
                    "money_management.stake_min_usd": 7000,
                    "money_management.stake_max_usd": 12000,
                    "money_management.stop_loss_pct": 0.16,
                    "money_management.take_profit_pct": 1.20,
                    "money_management.trailing_profit.enabled": True,
                    "money_management.trailing_profit.activation_pnl_pct": 0.55,
                    "money_management.trailing_profit.giveback_ratio": 0.40,
                    "money_management.trailing_profit.min_lock_pnl_pct": 0.12,
                },
            ),
        ]:
            dedup[item["name"]] = item

    if base_sat is not None:
        for item in [
            _make_mainline_variant(
                base_sat,
                name="mainline_core_satellite_dynlev_fix8_lock18",
                note="结构版：core-satellite 事件骨架 + 动态杠杆 + 硬保护单，主线把事件当 satellite 补机会",
                patch={
                    "portfolio.dynamic_leverage.enabled": True,
                    "portfolio.dynamic_leverage.min": 4.0,
                    "portfolio.dynamic_leverage.max": 8.0,
                    "portfolio.dynamic_leverage.adx_low": 18.0,
                    "portfolio.dynamic_leverage.adx_high": 36.0,
                    "money_management.mode": "fixed",
                    "money_management.capital_slices": 8,
                    "money_management.stake_mode": "dynamic_equity",
                    "money_management.stake_min_usd": 9000,
                    "money_management.stake_max_usd": 14000,
                    "money_management.stop_loss_pct": 0.18,
                    "money_management.take_profit_pct": 1.50,
                    "money_management.trailing_profit.enabled": True,
                    "money_management.trailing_profit.activation_pnl_pct": 0.70,
                    "money_management.trailing_profit.giveback_ratio": 0.35,
                    "money_management.trailing_profit.min_lock_pnl_pct": 0.18,
                },
            ),
        ]:
            dedup[item["name"]] = item

    return list(dedup.values())


def _make_variant(base: dict[str, Any], *, name: str, note: str, patch: dict[str, Any], family: str) -> dict[str, Any]:
    mods = copy.deepcopy(base.get("mods", {}))
    for k, v in patch.items():
        mods[k] = v
    return {
        "symbol": str(base.get("symbol")),
        "family": family,
        "name": name,
        "note": note,
        "mods": mods,
    }


def _manual_branch_item(*, symbol: str, family: str, name: str, note: str, mods: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": str(symbol),
        "family": family,
        "name": name,
        "note": note,
        "mods": copy.deepcopy(mods),
    }


def _branch_items() -> list[dict[str, Any]]:
    rows = [copy.deepcopy(x) for x in s76._candidate_items()]
    item_map = {str(item.get("name")): copy.deepcopy(item) for item in s55._branch_candidates()}

    if "eth_short_shock_lb16_adx24" in item_map:
        base = item_map["eth_short_shock_lb16_adx24"]
        rows.append(
            _make_variant(
                base,
                name="eth_short_shock_fast_lb16_atr052_adx22_s078",
                note="ETH 空腿快版：重大消息方向明确时直接进场，优先近2年 + WF",
                family="short",
                patch={
                    "strategy_params.breakout_lookback": 16,
                    "strategy_params.breakout_atr_buffer": 0.52,
                    "strategy_params.cooldown_bars": 5,
                    "filters.adx_floor": 22,
                    "money_management.stake_scale.eth_short": 0.78,
                },
            )
        )
        rows.append(
            _make_variant(
                base,
                name="eth_retest_short_trend_lb20_atr060_adx24_s068",
                note="ETH 空腿回踩确认版：消息冲击后等二次确认，不追第一脚",
                family="short",
                patch={
                    "strategy_params.breakout_lookback": 20,
                    "strategy_params.breakout_atr_buffer": 0.60,
                    "strategy_params.cooldown_bars": 7,
                    "filters.adx_floor": 24,
                    "money_management.stake_scale.eth_short": 0.68,
                },
            )
        )

    if "eth_fast_trend_lb16_longonly" in item_map:
        base = item_map["eth_fast_trend_lb16_longonly"]
        rows.append(
            _make_variant(
                base,
                name="eth_breakout_long_event_lb16_atr050_adx22_s034",
                note="ETH 长腿事件版：趋势 + 消息释放同向时放行 breakout",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 16,
                    "strategy_params.breakout_atr_buffer": 0.50,
                    "strategy_params.cooldown_bars": 5,
                    "filters.adx_floor": 22,
                    "money_management.stake_scale.eth_long": 0.34,
                },
            )
        )

    if "sol_fast_trend_lb16_shortonly" in item_map:
        base = item_map["sol_fast_trend_lb16_shortonly"]
        rows.append(
            _make_variant(
                base,
                name="sol_fast_trend_short_aggr_lb16_atr055_adx22_s076",
                note="SOL 空腿激进版：先激进找边，再让 WF 收口",
                family="short",
                patch={
                    "strategy_params.breakout_lookback": 16,
                    "strategy_params.breakout_atr_buffer": 0.55,
                    "strategy_params.cooldown_bars": 6,
                    "filters.adx_floor": 22,
                    "money_management.stake_scale.sol_short": 0.76,
                },
            )
        )

    if "sol_short_shock_lb16_adx22" in item_map:
        base = item_map["sol_short_shock_lb16_adx22"]
        rows.append(
            _make_variant(
                base,
                name="sol_short_shock_fast_lb18_adx24_s066",
                note="SOL 冲击空腿快版：重大消息/破位下的直推空单",
                family="short",
                patch={
                    "strategy_params.breakout_lookback": 18,
                    "strategy_params.breakout_atr_buffer": 0.58,
                    "strategy_params.cooldown_bars": 6,
                    "filters.adx_floor": 24,
                    "money_management.stake_scale.sol_short": 0.66,
                },
            )
        )

    base_long = next((r for r in rows if str(r.get("name")) == "sol_long_core_adx28_cd6_lb22_zone027_s038"), None)
    if base_long is not None:
        rows.append(
            _make_variant(
                base_long,
                name="sol_long_core_soft_lb20_zone025_s042",
                note="SOL 长腿软化版：保留 long 路径，但不再只押一种 zone",
                family="long",
                patch={
                    "sr_entries.lookback_4h": 20,
                    "sr_entries.zone_atr_mult": 0.25,
                    "sr_entries.stake_scale": 0.42,
                },
            )
        )

    rows.extend([
        _manual_branch_item(
            symbol="btc",
            family="long",
            name="btc_breakout_long_event_lb20_atr060_adx24_s050",
            note="BTC 长腿事件突破版：宏观/ETF/大额流向共振时跟随，不再只让 BTC 出现在主线空腿里",
            mods={
                "strategy_params.allow_short": False,
                "strategy_params.long_symbols": ["btc"],
                "strategy_params.short_symbols": [],
                "strategy_params.cooldown_bars": 8,
                "strategy_params.breakout_lookback": 20,
                "filters.btc_breakout_atr_buffer": 0.60,
                "filters.btc_adx_floor": 24,
                "filters.macro_gate_tf_by_symbol.btc": "4h",
                "money_management.stake_scale.btc_long": 0.50,
            },
        ),
        _manual_branch_item(
            symbol="btc",
            family="short",
            name="btc_retest_short_event_lb20_atr060_adx24_s072",
            note="BTC 空腿回踩确认版：重大消息后不追第一脚，等回踩失败再放行空单",
            mods={
                "strategy_params.allow_short": True,
                "strategy_params.long_symbols": [],
                "strategy_params.short_symbols": ["btc"],
                "strategy_params.cooldown_bars": 7,
                "strategy_params.breakout_lookback": 20,
                "filters.btc_breakout_atr_buffer": 0.60,
                "filters.btc_adx_floor": 24,
                "filters.btc_short_pullback_atr": 1.00,
                "filters.btc_short_macro_tf": "4h",
                "money_management.stake_scale.btc_short": 0.72,
            },
        ),
        _manual_branch_item(
            symbol="btc",
            family="dual",
            name="btc_dual_shortwave_sr_lb24_zone030_s055",
            note="BTC 双向短波/SR：趋势和回踩并行，不把 BTC 波段限制成单侧",
            mods={
                "strategy_params.allow_short": True,
                "strategy_params.long_symbols": ["btc"],
                "strategy_params.short_symbols": ["btc"],
                "filters.btc_breakout_atr_buffer": 9.0,
                "filters.btc_adx_floor": 99,
                "sr_entries.enabled": True,
                "sr_entries.symbols": ["btc"],
                "sr_entries.lookback_4h": 24,
                "sr_entries.zone_atr_mult": 0.30,
                "sr_entries.use_adx_filter": True,
                "sr_entries.adx_min": 0.0,
                "sr_entries.adx_max": 26.0,
                "sr_entries.stake_scale": 0.55,
                "sr_entries.cooldown_bars": 8,
                "sr_entries.require_compress_ok": True,
                "money_management.stake_scale.btc_long": 0.55,
                "money_management.stake_scale.btc_short": 0.55,
            },
        ),
        _manual_branch_item(
            symbol="btc",
            family="dual",
            name="btc_dual_fast_trend_dynlev_fix8",
            note="BTC 双向快趋势结构版：动态杠杆 + 动态权益切片 + 严格止盈止损",
            mods={
                "strategy_params.allow_short": True,
                "strategy_params.long_symbols": ["btc"],
                "strategy_params.short_symbols": ["btc"],
                "strategy_params.cooldown_bars": 8,
                "strategy_params.breakout_lookback": 20,
                "filters.btc_breakout_atr_buffer": 0.60,
                "filters.btc_adx_floor": 24,
                "filters.macro_gate_tf_by_symbol.btc": "4h",
                "filters.btc_short_macro_tf": "4h",
                "portfolio.dynamic_leverage.enabled": True,
                "portfolio.dynamic_leverage.min": 4.0,
                "portfolio.dynamic_leverage.max": 8.0,
                "portfolio.dynamic_leverage.adx_low": 18.0,
                "portfolio.dynamic_leverage.adx_high": 36.0,
                "money_management.mode": "fixed",
                "money_management.capital_slices": 8,
                "money_management.stake_mode": "dynamic_equity",
                "money_management.stake_min_usd": 9000,
                "money_management.stake_max_usd": 14000,
                "money_management.stop_loss_pct": 0.18,
                "money_management.take_profit_pct": 1.35,
                "money_management.trailing_profit.enabled": True,
                "money_management.trailing_profit.activation_pnl_pct": 0.60,
                "money_management.trailing_profit.giveback_ratio": 0.35,
                "money_management.trailing_profit.min_lock_pnl_pct": 0.15,
                "money_management.stake_scale.btc_long": 0.50,
                "money_management.stake_scale.btc_short": 0.70,
            },
        ),
    ])

    dedup: dict[str, dict[str, Any]] = {}
    for row in rows:
        dedup[str(row["name"])] = row
    return list(dedup.values())


# -----------------------------
# Scoring
# -----------------------------

def _trade_count(metrics: dict[str, Any], key: str = "trades") -> int:
    try:
        return max(0, int(metrics.get(key, 0) or 0))
    except Exception:
        return 0


def _sample_quality(trades: int, target: int) -> float:
    t = max(0, int(trades or 0))
    if t <= 0:
        return 0.0
    return min(1.0, t / max(int(target or 1), 1)) ** 0.65


def _bounded_pf(value: Any, trades: int, *, cap: float, target: int) -> float:
    return min(_safe_float(value), float(cap)) * _sample_quality(trades, target)


def _bounded_ret(value: Any, trades: int, *, target: int) -> float:
    return _safe_float(value) * _sample_quality(trades, target)


def _event_bonus_weight(recent_m: dict[str, Any], wf_m: dict[str, Any], *, recent_target: int, wf_target: int) -> float:
    rq = _sample_quality(_trade_count(recent_m), recent_target)
    wq = _sample_quality(_trade_count(wf_m), wf_target)
    return (rq + wq) / 2.0


def _meets_trade_floor(recent_m: dict[str, Any], wf_m: dict[str, Any], *, recent_floor: int, wf_floor: int) -> bool:
    return _trade_count(recent_m) >= int(recent_floor) and _trade_count(wf_m) >= int(wf_floor)


def _mainline_gate_pref_score(recent_m: dict[str, Any], full_m: dict[str, Any]) -> float:
    recent_trades = _trade_count(recent_m)
    recent_q = _sample_quality(recent_trades, 10)
    return float(
        _bounded_pf(recent_m.get("pf"), recent_trades, cap=4.0, target=10) * 156.0
        + _bounded_ret(recent_m.get("ret"), recent_trades, target=10) * 108.0
        - abs(_safe_float(recent_m.get("maxdd"))) * 78.0 * recent_q
        + min(recent_trades, 180) * 0.52
        + min(_safe_float(full_m.get("pf")), 2.0) * 12.0
        + _safe_float(full_m.get("ret")) * 5.0
    )


def _branch_gate_pref_score(recent_m: dict[str, Any], full_m: dict[str, Any]) -> float:
    recent_trades = _trade_count(recent_m)
    recent_q = _sample_quality(recent_trades, 8)
    return float(
        _bounded_pf(recent_m.get("pf"), recent_trades, cap=4.0, target=8) * 150.0
        + _bounded_ret(recent_m.get("ret"), recent_trades, target=8) * 120.0
        - abs(_safe_float(recent_m.get("maxdd"))) * 86.0 * recent_q
        + min(recent_trades, 160) * 0.56
        + min(_safe_float(full_m.get("pf")), 1.8) * 8.0
        + _safe_float(full_m.get("ret")) * 3.0
    )


def _mainline_score(full_m: dict[str, Any], recent_m: dict[str, Any], wf_m: dict[str, Any], pos_folds: int, pf_floor: float, dd_ceiling: float) -> float:
    recent_trades = _trade_count(recent_m)
    wf_trades = _trade_count(wf_m)
    recent_q = _sample_quality(recent_trades, 12)
    wf_q = _sample_quality(wf_trades, 10)
    bonus_q = (recent_q + wf_q) / 2.0
    return float(
        _bounded_pf(recent_m.get("pf"), recent_trades, cap=4.0, target=12) * 168.0
        + _bounded_ret(recent_m.get("ret"), recent_trades, target=12) * 112.0
        - abs(_safe_float(recent_m.get("maxdd"))) * 78.0 * recent_q
        + min(recent_trades, 180) * 0.78
        + _bounded_pf(wf_m.get("pf"), wf_trades, cap=3.0, target=10) * 142.0
        + _bounded_ret(wf_m.get("ret"), wf_trades, target=10) * 90.0
        - abs(_safe_float(wf_m.get("maxdd"))) * 96.0 * wf_q
        + pos_folds * 12.0 * bonus_q
        + min(_safe_float(pf_floor), 2.5) * 18.0 * wf_q
        - _safe_float(dd_ceiling) * 18.0 * wf_q
        + min(_safe_float(full_m.get("pf")), 2.0) * 10.0
        + _safe_float(full_m.get("ret")) * 4.0
        - max(0, 8 - recent_trades) * 6.0
        - max(0, 5 - wf_trades) * 8.0
    )


def _mainline_label(recent_m: dict[str, Any], wf_m: dict[str, Any], pos_folds: int) -> str:
    if _meets_trade_floor(recent_m, wf_m, recent_floor=16, wf_floor=12) and _safe_float(recent_m.get("pf")) >= 1.95 and _safe_float(wf_m.get("pf")) >= 1.40 and _safe_float(recent_m.get("ret")) > 0 and _safe_float(wf_m.get("ret")) > 0 and abs(_safe_float(wf_m.get("maxdd"))) <= 0.45 and pos_folds >= 3:
        return "pass"
    if _meets_trade_floor(recent_m, wf_m, recent_floor=8, wf_floor=5) and _safe_float(recent_m.get("pf")) >= 1.50 and _safe_float(wf_m.get("pf")) >= 1.10 and abs(_safe_float(wf_m.get("maxdd"))) <= 0.60:
        return "hold"
    if _meets_trade_floor(recent_m, wf_m, recent_floor=3, wf_floor=2) and _safe_float(wf_m.get("pf")) >= 1.00 and _safe_float(wf_m.get("ret")) >= 0:
        return "reserve+"
    return "reserve"


def _branch_score(full_m: dict[str, Any], recent_m: dict[str, Any], wf_m: dict[str, Any], pos_folds: int, pf_floor: float, dd_ceiling: float) -> float:
    recent_trades = _trade_count(recent_m)
    wf_trades = _trade_count(wf_m)
    recent_q = _sample_quality(recent_trades, 10)
    wf_q = _sample_quality(wf_trades, 8)
    bonus_q = (recent_q + wf_q) / 2.0
    return float(
        _bounded_pf(recent_m.get("pf"), recent_trades, cap=4.0, target=10) * 154.0
        + _bounded_ret(recent_m.get("ret"), recent_trades, target=10) * 118.0
        - abs(_safe_float(recent_m.get("maxdd"))) * 84.0 * recent_q
        + min(recent_trades, 160) * 0.62
        + _bounded_pf(wf_m.get("pf"), wf_trades, cap=3.0, target=8) * 138.0
        + _bounded_ret(wf_m.get("ret"), wf_trades, target=8) * 104.0
        - abs(_safe_float(wf_m.get("maxdd"))) * 92.0 * wf_q
        + pos_folds * 14.0 * bonus_q
        + min(_safe_float(pf_floor), 2.2) * 22.0 * wf_q
        - _safe_float(dd_ceiling) * 16.0 * wf_q
        + min(_safe_float(full_m.get("pf")), 1.8) * 8.0
        + _safe_float(full_m.get("ret")) * 3.0
        - max(0, 4 - recent_trades) * 8.0
        - max(0, 3 - wf_trades) * 10.0
    )


def _branch_label(recent_m: dict[str, Any], wf_m: dict[str, Any], pos_folds: int) -> str:
    if _meets_trade_floor(recent_m, wf_m, recent_floor=10, wf_floor=8) and _safe_float(recent_m.get("pf")) >= 1.25 and _safe_float(wf_m.get("pf")) >= 1.15 and _safe_float(recent_m.get("ret")) > 0 and _safe_float(wf_m.get("ret")) > 0 and abs(_safe_float(wf_m.get("maxdd"))) <= 0.25 and pos_folds >= 3:
        return "pass"
    if _meets_trade_floor(recent_m, wf_m, recent_floor=4, wf_floor=3) and _safe_float(recent_m.get("pf")) >= 1.05 and _safe_float(wf_m.get("pf")) >= 1.00 and abs(_safe_float(wf_m.get("maxdd"))) <= 0.45:
        return "hold"
    if _meets_trade_floor(recent_m, wf_m, recent_floor=2, wf_floor=2) and _safe_float(wf_m.get("pf")) >= 0.95 and _safe_float(wf_m.get("ret")) >= 0:
        return "reserve+"
    return "reserve"


# -----------------------------
# Mainline flow
# -----------------------------

def _run_mainline(root: Path, cfg: dict[str, Any], data: dict[str, pd.DataFrame], item: dict[str, Any], initial_equity: float, full_start: pd.Timestamp, full_end: pd.Timestamp) -> dict[str, Any]:
    trades, trades_feat = s59._run_portfolio_candidate(root, cfg, data, item["mods"])
    full_m = s77._with_window_metrics(s59._metrics_from_trades(trades, initial_equity), full_start, full_end)
    gate_rows: list[dict[str, Any]] = []
    for name, fn, note in FUSION_GATES:
        gr = s59._evaluate_gate(trades_feat, name, fn, note, initial_equity)
        gr["recent_metrics"] = s77._with_window_metrics(s78._recent_metrics(gr.get("gated_df"), initial_equity), s78.RECENT_START, full_end)
        gate_rows.append(gr)
    return {"name": item["name"], "note": item["note"], "full_metrics": full_m, "gate_rows": gate_rows}


def _write_mainline(path_txt: Path, path_json: Path, rows: list[dict[str, Any]]) -> None:
    lines: list[str] = []
    lines.append("Stage88 主线融合式滚动验证")
    lines.append("核心原则：重大消息可以成为开仓依据，但必须与成交结构 / 拥挤度 / 波动状态共同确认。")
    lines.append("采纳框架：A 趋势突破 + D 事件突破 + E 扫损反转，并把 C 拥挤反转留作确认层。")
    lines.append("方法：neutral_revert + major_event_impulse + post_event_drift + crowding_reversal + liquidity_sweep_reclaim。")
    lines.append("")
    lines.append("=== 候选结果 ===")
    for row in rows:
        best = row["best_gate"]
        full_m = row["full_metrics"]
        recent_m = best["recent_metrics"]
        wf = row["walkforward"]
        oos_m = wf["metrics"]
        lines.append(
            f"- {row['name']}: best_gate={best['gate_name']} ({row['decision']}) | 6年 收益={_fmt_pct(full_m.get('ret'))} 月化={_fmt_pct(full_m.get('monthlyized_ret'))} 回撤={_fmt_pct(full_m.get('maxdd'))} 交易={int(full_m.get('trades',0))} PF={_safe_float(full_m.get('pf')):.3f} | 近2年 收益={_fmt_pct(recent_m.get('ret'))} 月化={_fmt_pct(recent_m.get('monthlyized_ret'))} 回撤={_fmt_pct(recent_m.get('maxdd'))} 交易={int(recent_m.get('trades',0))} PF={_safe_float(recent_m.get('pf')):.3f} | WF样本外 收益={_fmt_pct(oos_m.get('ret'))} 月化={_fmt_pct(oos_m.get('monthlyized_ret'))} 回撤={_fmt_pct(oos_m.get('maxdd'))} 交易={int(oos_m.get('trades',0))} PF={_safe_float(oos_m.get('pf')):.3f} | 正收益折={wf['positive_folds']}/{wf['total_folds']} | score={row['fusion_score']:+.2f}"
        )
        lines.append(f"  note={row['note']} | gate_mix={wf['gate_mix']} | wf_pf_floor={wf['pf_floor']:.3f} | wf_dd_ceiling={wf['dd_ceiling']:.3f}")
    path_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    path_json.write_text(json.dumps({"rows": [_json_safe({**r, "best_gate": _strip_gate_payload(r["best_gate"])}) for r in rows]}, ensure_ascii=False, indent=2), encoding="utf-8")


# -----------------------------
# Branch flow
# -----------------------------

def _run_branch(root: Path, cfg: dict[str, Any], item: dict[str, Any], initial_equity: float) -> dict[str, Any]:
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
    for name, fn, note in FUSION_GATES:
        gr = s59._evaluate_gate(trades_feat, name, fn, note, initial_equity)
        gr["recent_metrics"] = s78._with_window_metrics(s78._recent_metrics(gr.get("gated_df"), initial_equity), s78.RECENT_START, full_end)
        gate_rows.append(gr)
    return {"symbol": sym, "family": item.get("family", "mixed"), "name": item["name"], "note": item.get("note", ""), "full_metrics": full_m, "gate_rows": gate_rows, "full_end": full_end}


def _write_branch(path_txt: Path, path_json: Path, rows: list[dict[str, Any]]) -> None:
    lines: list[str] = []
    lines.append("Stage89 分支融合式滚动验证")
    lines.append("核心原则：重大消息可以做开仓依据，但要和结构 / 拥挤 / OI / 波动一起看，不局限于 FOMC。")
    lines.append("采纳框架：A 趋势突破、C 拥挤反转、D 事件突破、E 流动性扫损反转。")
    lines.append("方法：先激进扩候选，再让近2年 + WF 把结果收口；不因单次不合格就永久砍路径。")
    lines.append("")
    lines.append("=== 候选结果 ===")
    for row in rows:
        best = row["best_gate"]
        full_m = row["full_metrics"]
        recent_m = best["recent_metrics"]
        wf = row["walkforward"]
        oos_m = wf["metrics"]
        lines.append(
            f"- {row['symbol'].upper()} | {row['family']} | {row['name']}: best_gate={best['gate_name']} ({row['decision']}) | 6年 收益={_fmt_pct(full_m.get('ret'))} 月化={_fmt_pct(full_m.get('monthlyized_ret'))} 回撤={_fmt_pct(full_m.get('maxdd'))} 交易={int(full_m.get('trades',0))} PF={_safe_float(full_m.get('pf')):.3f} | 近2年 收益={_fmt_pct(recent_m.get('ret'))} 月化={_fmt_pct(recent_m.get('monthlyized_ret'))} 回撤={_fmt_pct(recent_m.get('maxdd'))} 交易={int(recent_m.get('trades',0))} PF={_safe_float(recent_m.get('pf')):.3f} | WF样本外 收益={_fmt_pct(oos_m.get('ret'))} 月化={_fmt_pct(oos_m.get('monthlyized_ret'))} 回撤={_fmt_pct(oos_m.get('maxdd'))} 交易={int(oos_m.get('trades',0))} PF={_safe_float(oos_m.get('pf')):.3f} | 正收益折={wf['positive_folds']}/{wf['total_folds']} | score={row['fusion_score']:+.2f}"
        )
        lines.append(f"  note={row['note']} | gate_mix={wf['gate_mix']} | wf_pf_floor={wf['pf_floor']:.3f} | wf_dd_ceiling={wf['dd_ceiling']:.3f}")
    lines.append("")
    lines.append("=== 各赛道当前最优 ===")
    best_by_lane: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row["symbol"]).upper(), str(row["family"]))
        if key not in best_by_lane:
            best_by_lane[key] = row
    for (sym, family), row in best_by_lane.items():
        m = row["walkforward"]["metrics"]
        lines.append(f"- {sym} | {family}: {row['name']} | WF 收益={_fmt_pct(m.get('ret'))} | WF PF={_safe_float(m.get('pf')):.3f} | WF MaxDD={_fmt_pct(m.get('maxdd'))} | {row['decision']}")
    path_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    path_json.write_text(json.dumps({"rows": [_json_safe({**r, "best_gate": _strip_gate_payload(r["best_gate"])}) for r in rows]}, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage88/89 strategy fusion walkforward")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    cfg = rcb.load_research_base_config(root)
    initial_equity = float(cfg.get("portfolio", {}).get("initial_equity", 100000.0))
    reports_raw = root / "reports" / "research_raw"
    reports_raw.mkdir(parents=True, exist_ok=True)

    data = s46._load_portfolio_data(root, cfg)
    full_start, full_end = s77._window_bounds_from_data(data)
    main_rows = [_run_mainline(root, cfg, data, item, initial_equity, full_start, full_end) for item in _mainline_items()]
    ref_row = next((r for r in main_rows if r["name"] == "mainline_live_base"), main_rows[0])
    for row in main_rows:
        row["best_gate"] = max(row["gate_rows"], key=lambda g: _mainline_gate_pref_score(g.get("recent_metrics", {}), row["full_metrics"]))
        row["walkforward"] = s81._wf_result(row, ref_row, initial_equity, s81.RECENT_START, full_end)
        row["fusion_score"] = _mainline_score(row["full_metrics"], row["best_gate"]["recent_metrics"], row["walkforward"]["metrics"], row["walkforward"]["positive_folds"], row["walkforward"]["pf_floor"], row["walkforward"]["dd_ceiling"])
        row["decision"] = _mainline_label(row["best_gate"]["recent_metrics"], row["walkforward"]["metrics"], row["walkforward"]["positive_folds"])
    main_rows.sort(key=lambda r: float(r["fusion_score"]), reverse=True)
    _write_mainline(reports_raw / "stage88_mainline_fusion_walkforward_latest.txt", reports_raw / "stage88_mainline_fusion_walkforward_latest.json", main_rows)

    branch_rows = [_run_branch(root, cfg, item, initial_equity) for item in _branch_items()]
    for row in branch_rows:
        row["best_gate"] = max(row["gate_rows"], key=lambda g: _branch_gate_pref_score(g.get("recent_metrics", {}), row["full_metrics"]))
        row["walkforward"] = s82._wf_result(row, initial_equity, s78.RECENT_START, row["full_end"])
        row["fusion_score"] = _branch_score(row["full_metrics"], row["best_gate"]["recent_metrics"], row["walkforward"]["metrics"], row["walkforward"]["positive_folds"], row["walkforward"]["pf_floor"], row["walkforward"]["dd_ceiling"])
        row["decision"] = _branch_label(row["best_gate"]["recent_metrics"], row["walkforward"]["metrics"], row["walkforward"]["positive_folds"])
    branch_rows.sort(key=lambda r: float(r["fusion_score"]), reverse=True)
    _write_branch(reports_raw / "stage89_branch_fusion_walkforward_latest.txt", reports_raw / "stage89_branch_fusion_walkforward_latest.json", branch_rows)

    print(reports_raw / "stage88_mainline_fusion_walkforward_latest.txt")
    print(reports_raw / "stage88_mainline_fusion_walkforward_latest.json")
    print(reports_raw / "stage89_branch_fusion_walkforward_latest.txt")
    print(reports_raw / "stage89_branch_fusion_walkforward_latest.json")


if __name__ == "__main__":
    main()
