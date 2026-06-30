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
except Exception as exc:
    raise SystemExit("缺少 stage46/stage55/stage59 模块，请先保留此前补丁。") from exc


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


def _with_side(mods: dict[str, Any], symbol: str, side: str) -> dict[str, Any]:
    out = copy.deepcopy(mods)
    if side == "long":
        out["strategy_params.allow_short"] = False
        out["strategy_params.long_symbols"] = [symbol]
        out["strategy_params.short_symbols"] = []
    elif side == "short":
        out["strategy_params.allow_short"] = True
        out["strategy_params.long_symbols"] = []
        out["strategy_params.short_symbols"] = [symbol]
    return out


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


def _candidate_items() -> list[dict[str, Any]]:
    item_map = {str(item.get("name")): copy.deepcopy(item) for item in s55._branch_candidates()}
    rows: list[dict[str, Any]] = []

    def add_existing(base_name: str, family: str, note: str) -> None:
        item = item_map.get(base_name)
        if not item:
            return
        rows.append(
            {
                "symbol": str(item.get("symbol")),
                "family": family,
                "name": str(item.get("name")),
                "note": note,
                "mods": copy.deepcopy(item.get("mods", {})),
            }
        )

    add_existing("eth_shortwave_tight_shortonly", "short", "ETH 紧致短腿，对照线")
    add_existing("sol_long_core_adx28_cd6_lb22_zone027_s038", "long", "SOL 长腿主核，对照线")
    add_existing("sol_shortwave_smooth_longonly", "long", "SOL 平滑回踩长腿，对照线")
    add_existing("sol_fast_trend_lb16_shortonly", "short", "SOL 快趋势短腿，对照线")
    add_existing("eth_long_core_adx26_cd6_lb24_zone028_s032", "long", "ETH 长腿主核，对照线")
    add_existing("eth_short_shock_lb16_adx24", "short", "ETH 事件/破位空腿原型")
    add_existing("sol_short_shock_lb16_adx22", "short", "SOL 冲击空腿原型")
    add_existing("sol_hybrid_mr_shortonly", "short", "SOL 均值回归空腿，对照线")
    add_existing("eth_fast_trend_lb16_longonly", "long", "ETH 快趋势多腿，对照线")
    add_existing("eth_fast_trend_shortonly", "short", "ETH 快趋势空腿，对照线")
    add_existing("sol_shortwave_longonly", "long", "SOL 短波多腿，对照线")
    add_existing("eth_shortwave_longonly", "long", "ETH 短波多腿，对照线")

    if "eth_fast_trend_lb16_longonly" in item_map:
        base = item_map["eth_fast_trend_lb16_longonly"]
        rows.append(
            _make_variant(
                base,
                name="eth_breakout_long_follow_lb18_atr055_adx24_s030",
                note="ETH 长腿 A：事件/趋势顺风时做 breakout-follow，不再只押回踩",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 18,
                    "strategy_params.breakout_atr_buffer": 0.55,
                    "strategy_params.cooldown_bars": 6,
                    "filters.adx_floor": 24,
                    "money_management.stake_scale.eth_long": 0.30,
                },
            )
        )
        rows.append(
            _make_variant(
                base,
                name="eth_breakout_long_guarded_lb20_atr060_adx26_s028",
                note="ETH 长腿 B：提高确认，减少无效快进快出",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 20,
                    "strategy_params.breakout_atr_buffer": 0.60,
                    "strategy_params.cooldown_bars": 6,
                    "filters.adx_floor": 26,
                    "money_management.stake_scale.eth_long": 0.28,
                },
            )
        )

    if "eth_short_shock_lb16_adx24" in item_map:
        base = item_map["eth_short_shock_lb16_adx24"]
        rows.append(
            _make_variant(
                base,
                name="eth_short_shock_control_lb18_adx26_s074",
                note="ETH 空腿控制版：保留 short，但先压回撤和噪声",
                family="short",
                patch={
                    "strategy_params.breakout_lookback": 18,
                    "strategy_params.breakout_atr_buffer": 0.58,
                    "strategy_params.cooldown_bars": 6,
                    "filters.adx_floor": 26,
                    "money_management.stake_scale.eth_short": 0.74,
                },
            )
        )

    if "sol_fast_trend_lb16_shortonly" in item_map:
        base = item_map["sol_fast_trend_lb16_shortonly"]
        rows.append(
            _make_variant(
                base,
                name="sol_fast_trend_short_guarded_lb18_atr060_adx24_s068",
                note="SOL 空腿 A：先降杠杆和噪声，留住有效 short",
                family="short",
                patch={
                    "strategy_params.breakout_lookback": 18,
                    "strategy_params.breakout_atr_buffer": 0.60,
                    "strategy_params.cooldown_bars": 7,
                    "filters.adx_floor": 24,
                    "money_management.stake_scale.sol_short": 0.68,
                },
            )
        )
        rows.append(
            _make_variant(
                base,
                name="sol_fast_trend_short_guarded_lb20_atr065_adx26_s060",
                note="SOL 空腿 B：继续压 DD，看能否保住收益曲线",
                family="short",
                patch={
                    "strategy_params.breakout_lookback": 20,
                    "strategy_params.breakout_atr_buffer": 0.65,
                    "strategy_params.cooldown_bars": 8,
                    "filters.adx_floor": 26,
                    "money_management.stake_scale.sol_short": 0.60,
                },
            )
        )

    if "sol_short_shock_lb16_adx22" in item_map:
        base = item_map["sol_short_shock_lb16_adx22"]
        rows.append(
            _make_variant(
                base,
                name="sol_short_shock_guarded_lb20_adx26_s058",
                note="SOL 冲击空腿控制版：保留事件 short，但不给超大回撤放行",
                family="short",
                patch={
                    "strategy_params.breakout_lookback": 20,
                    "strategy_params.breakout_atr_buffer": 0.62,
                    "strategy_params.cooldown_bars": 8,
                    "filters.adx_floor": 26,
                    "money_management.stake_scale.sol_short": 0.58,
                },
            )
        )

    if "eth_long_core_adx26_cd6_lb24_zone028_s032" in item_map:
        base = item_map["eth_long_core_adx26_cd6_lb24_zone028_s032"]
        rows.append(
            _make_variant(
                base,
                name="eth_pullback_long_core_adx24_cd6_lb22_zone026_s036",
                note="ETH 长腿 C：先激进开方向，再用 zone+compress 收假突破",
                family="long",
                patch={
                    "sr_entries.lookback_4h": 22,
                    "sr_entries.zone_atr_mult": 0.26,
                    "sr_entries.adx_max": 24.0,
                    "sr_entries.stake_scale": 0.36,
                    "sr_entries.cooldown_bars": 5,
                    "strategy_params.cooldown_bars": 6,
                },
            )
        )

    if "sol_long_core_adx28_cd6_lb22_zone027_s038" in item_map:
        base = item_map["sol_long_core_adx28_cd6_lb22_zone027_s038"]
        rows.append(
            _make_variant(
                base,
                name="sol_pullback_long_core_adx24_cd6_lb20_zone025_s042",
                note="SOL 长腿 B：先放方向，再让 compress+zone 去收假突破",
                family="long",
                patch={
                    "sr_entries.lookback_4h": 20,
                    "sr_entries.zone_atr_mult": 0.25,
                    "sr_entries.adx_max": 24.0,
                    "sr_entries.stake_scale": 0.42,
                    "strategy_params.cooldown_bars": 6,
                },
            )
        )

    if "eth_fast_trend_shortonly" in item_map:
        base = item_map["eth_fast_trend_shortonly"]
        rows.append(
            _make_variant(
                base,
                name="eth_retest_short_trend_lb18_atr055_adx22_s072",
                note="ETH 空腿 C：更激进开方向，靠 flow/crowding/event gate 再收",
                family="short",
                patch={
                    "strategy_params.breakout_lookback": 18,
                    "strategy_params.breakout_atr_buffer": 0.55,
                    "strategy_params.cooldown_bars": 6,
                    "filters.adx_floor": 22,
                    "money_management.stake_scale.eth_short": 0.72,
                },
            )
        )

    if "sol_fast_trend_lb16_shortonly" in item_map:
        base = item_map["sol_fast_trend_lb16_shortonly"]
        rows.append(
            _make_variant(
                base,
                name="sol_retest_short_trend_lb18_atr055_adx22_s064",
                note="SOL 空腿 C：先抢方向，再用 gate 压假跌破",
                family="short",
                patch={
                    "strategy_params.breakout_lookback": 18,
                    "strategy_params.breakout_atr_buffer": 0.55,
                    "strategy_params.cooldown_bars": 6,
                    "filters.adx_floor": 22,
                    "money_management.stake_scale.sol_short": 0.64,
                },
            )
        )

    if "sol_hybrid_mr_shortonly" in item_map:
        base = item_map["sol_hybrid_mr_shortonly"]
        rows.append(
            _make_variant(
                base,
                name="sol_hybrid_mr_short_fast_bb34_std21_s010",
                note="SOL 空腿 D：极端拥挤下做更快回归，不跟趋势硬拧",
                family="short",
                patch={
                    "mean_reversion.bb_window": 34,
                    "mean_reversion.bb_std": 2.1,
                    "mean_reversion.adx_ceiling": 18,
                    "mean_reversion.risk_fraction_of_trend": 0.10,
                    "mean_reversion.leverage_cap": 2.0,
                    "mean_reversion.atr_stop_mult": 2.3,
                    "strategy_params.cooldown_bars": 6,
                },
            )
        )

    if "eth_shortwave_longonly" in item_map:
        base = item_map["eth_shortwave_longonly"]
        rows.append(
            _make_variant(
                base,
                name="eth_shortwave_long_core_lb22_zone026_adx22_s038",
                note="ETH 长腿 D：回踩承接版，不预设 ETH long 失效",
                family="long",
                patch={
                    "sr_entries.lookback_4h": 22,
                    "sr_entries.zone_atr_mult": 0.26,
                    "sr_entries.adx_max": 22.0,
                    "sr_entries.stake_scale": 0.38,
                    "sr_entries.cooldown_bars": 6,
                },
            )
        )


    if "eth_short_shock_lb16_adx24" in item_map:
        base = item_map["eth_short_shock_lb16_adx24"]
        rows.append(
            _make_variant(
                base,
                name="eth_short_shock_fast_lb16_atr052_adx22_s078",
                note="ETH 空腿 D：更激进抢方向，再让事件/拥挤门二次过滤",
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
                name="eth_short_shock_guarded_lb20_atr062_adx28_s070",
                note="ETH 空腿 E：更保守确认，测试能否压假跌破和回撤",
                family="short",
                patch={
                    "strategy_params.breakout_lookback": 20,
                    "strategy_params.breakout_atr_buffer": 0.62,
                    "strategy_params.cooldown_bars": 7,
                    "filters.adx_floor": 28,
                    "money_management.stake_scale.eth_short": 0.70,
                },
            )
        )

    if "eth_fast_trend_shortonly" in item_map:
        base = item_map["eth_fast_trend_shortonly"]
        rows.append(
            _make_variant(
                base,
                name="eth_retest_short_trend_lb16_atr050_adx20_s076",
                note="ETH 空腿 F：更快的回抽做空版本，保留激进模板",
                family="short",
                patch={
                    "strategy_params.breakout_lookback": 16,
                    "strategy_params.breakout_atr_buffer": 0.50,
                    "strategy_params.cooldown_bars": 5,
                    "filters.adx_floor": 20,
                    "money_management.stake_scale.eth_short": 0.76,
                },
            )
        )
        rows.append(
            _make_variant(
                base,
                name="eth_retest_short_trend_lb20_atr060_adx24_s068",
                note="ETH 空腿 G：更慢更稳的回抽做空版本",
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
                name="eth_breakout_long_follow_lb16_atr050_adx22_s034",
                note="ETH 长腿 E：更快 breakout-follow，先让事件顺风单进来",
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
        rows.append(
            _make_variant(
                base,
                name="eth_breakout_long_guarded_lb22_atr065_adx28_s026",
                note="ETH 长腿 F：更保守 breakout-follow，测试过滤噪声后的质量",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 22,
                    "strategy_params.breakout_atr_buffer": 0.65,
                    "strategy_params.cooldown_bars": 7,
                    "filters.adx_floor": 28,
                    "money_management.stake_scale.eth_long": 0.26,
                },
            )
        )

    if "eth_long_core_adx26_cd6_lb24_zone028_s032" in item_map:
        base = item_map["eth_long_core_adx26_cd6_lb24_zone028_s032"]
        rows.append(
            _make_variant(
                base,
                name="eth_pullback_long_core_adx22_cd5_lb20_zone024_s040",
                note="ETH 长腿 G：更激进 pullback，保留更宽容的结构标准",
                family="long",
                patch={
                    "sr_entries.lookback_4h": 20,
                    "sr_entries.zone_atr_mult": 0.24,
                    "sr_entries.adx_max": 22.0,
                    "sr_entries.stake_scale": 0.40,
                    "sr_entries.cooldown_bars": 5,
                    "strategy_params.cooldown_bars": 5,
                },
            )
        )

    if "eth_shortwave_longonly" in item_map:
        base = item_map["eth_shortwave_longonly"]
        rows.append(
            _make_variant(
                base,
                name="eth_shortwave_long_core_lb20_zone024_adx20_s042",
                note="ETH 长腿 H：更快回踩承接，避免 ETH long 只剩一种模板",
                family="long",
                patch={
                    "sr_entries.lookback_4h": 20,
                    "sr_entries.zone_atr_mult": 0.24,
                    "sr_entries.adx_max": 20.0,
                    "sr_entries.stake_scale": 0.42,
                    "sr_entries.cooldown_bars": 5,
                },
            )
        )

    if "sol_fast_trend_lb16_shortonly" in item_map:
        base = item_map["sol_fast_trend_lb16_shortonly"]
        rows.append(
            _make_variant(
                base,
                name="sol_fast_trend_short_guarded_lb16_atr055_adx22_s072",
                note="SOL 空腿 E：更激进的快趋势 short 版本",
                family="short",
                patch={
                    "strategy_params.breakout_lookback": 16,
                    "strategy_params.breakout_atr_buffer": 0.55,
                    "strategy_params.cooldown_bars": 5,
                    "filters.adx_floor": 22,
                    "money_management.stake_scale.sol_short": 0.72,
                },
            )
        )
        rows.append(
            _make_variant(
                base,
                name="sol_fast_trend_short_guarded_lb22_atr070_adx28_s056",
                note="SOL 空腿 F：更保守的快趋势 short 版本",
                family="short",
                patch={
                    "strategy_params.breakout_lookback": 22,
                    "strategy_params.breakout_atr_buffer": 0.70,
                    "strategy_params.cooldown_bars": 8,
                    "filters.adx_floor": 28,
                    "money_management.stake_scale.sol_short": 0.56,
                },
            )
        )
        rows.append(
            _make_variant(
                base,
                name="sol_retest_short_trend_lb16_atr050_adx20_s068",
                note="SOL 空腿 G：更快回抽做空版本",
                family="short",
                patch={
                    "strategy_params.breakout_lookback": 16,
                    "strategy_params.breakout_atr_buffer": 0.50,
                    "strategy_params.cooldown_bars": 5,
                    "filters.adx_floor": 20,
                    "money_management.stake_scale.sol_short": 0.68,
                },
            )
        )

    if "sol_short_shock_lb16_adx22" in item_map:
        base = item_map["sol_short_shock_lb16_adx22"]
        rows.append(
            _make_variant(
                base,
                name="sol_short_shock_guarded_lb18_adx24_s062",
                note="SOL 空腿 H：中等强度冲击确认版，给 shock short 多一档标准",
                family="short",
                patch={
                    "strategy_params.breakout_lookback": 18,
                    "strategy_params.breakout_atr_buffer": 0.58,
                    "strategy_params.cooldown_bars": 6,
                    "filters.adx_floor": 24,
                    "money_management.stake_scale.sol_short": 0.62,
                },
            )
        )

    if "sol_hybrid_mr_shortonly" in item_map:
        base = item_map["sol_hybrid_mr_shortonly"]
        rows.append(
            _make_variant(
                base,
                name="sol_hybrid_mr_short_fast_bb30_std20_s012",
                note="SOL 空腿 I：更快均值回归 short，保留非趋势路径",
                family="short",
                patch={
                    "mean_reversion.bb_window": 30,
                    "mean_reversion.bb_std": 2.0,
                    "mean_reversion.adx_ceiling": 16,
                    "mean_reversion.risk_fraction_of_trend": 0.12,
                    "mean_reversion.leverage_cap": 2.2,
                    "mean_reversion.atr_stop_mult": 2.1,
                    "strategy_params.cooldown_bars": 5,
                },
            )
        )

    if "sol_long_core_adx28_cd6_lb22_zone027_s038" in item_map:
        base = item_map["sol_long_core_adx28_cd6_lb22_zone027_s038"]
        rows.append(
            _make_variant(
                base,
                name="sol_pullback_long_core_adx22_cd5_lb18_zone024_s046",
                note="SOL 长腿 C：更激进 pullback，先让方向感进来",
                family="long",
                patch={
                    "sr_entries.lookback_4h": 18,
                    "sr_entries.zone_atr_mult": 0.24,
                    "sr_entries.adx_max": 22.0,
                    "sr_entries.stake_scale": 0.46,
                    "strategy_params.cooldown_bars": 5,
                },
            )
        )
        rows.append(
            _make_variant(
                base,
                name="sol_pullback_long_core_adx26_cd6_lb22_zone026_s040",
                note="SOL 长腿 D：中间态 pullback，保留不同确认标准",
                family="long",
                patch={
                    "sr_entries.lookback_4h": 22,
                    "sr_entries.zone_atr_mult": 0.26,
                    "sr_entries.adx_max": 26.0,
                    "sr_entries.stake_scale": 0.40,
                    "strategy_params.cooldown_bars": 6,
                },
            )
        )

    if "sol_shortwave_longonly" in item_map:
        base = item_map["sol_shortwave_longonly"]
        rows.append(
            _make_variant(
                base,
                name="sol_shortwave_long_core_lb18_zone024_adx20_s044",
                note="SOL 长腿 E：更快回踩承接版",
                family="long",
                patch={
                    "sr_entries.lookback_4h": 18,
                    "sr_entries.zone_atr_mult": 0.24,
                    "sr_entries.adx_max": 20.0,
                    "sr_entries.stake_scale": 0.44,
                    "sr_entries.cooldown_bars": 5,
                },
            )
        )
        rows.append(
            _make_variant(
                base,
                name="sol_shortwave_long_core_lb22_zone026_adx22_s040",
                note="SOL 长腿 F：更稳的回踩承接版",
                family="long",
                patch={
                    "sr_entries.lookback_4h": 22,
                    "sr_entries.zone_atr_mult": 0.26,
                    "sr_entries.adx_max": 22.0,
                    "sr_entries.stake_scale": 0.40,
                    "sr_entries.cooldown_bars": 6,
                },
            )
        )

    dedup: dict[str, dict[str, Any]] = {}
    for row in rows:
        dedup[str(row["name"])] = row
    return list(dedup.values())

DEFAULT_CANDIDATE_NAMES = [
    "eth_short_shock_control_lb18_adx26_s074",
    "eth_short_shock_fast_lb16_atr052_adx22_s078",
    "eth_retest_short_trend_lb18_atr055_adx22_s072",
    "eth_breakout_long_follow_lb18_atr055_adx24_s030",
    "eth_pullback_long_core_adx24_cd6_lb22_zone026_s036",
    "eth_shortwave_long_core_lb20_zone024_adx20_s042",
    "sol_fast_trend_short_guarded_lb18_atr060_adx24_s068",
    "sol_short_shock_guarded_lb18_adx24_s062",
    "sol_hybrid_mr_short_fast_bb30_std20_s012",
    "sol_long_core_adx28_cd6_lb22_zone027_s038",
    "sol_pullback_long_core_adx22_cd5_lb18_zone024_s046",
    "sol_shortwave_long_core_lb18_zone024_adx20_s044",
]


def _resolve_candidate_names(raw: str, default: list[str]) -> list[str]:
    items = [x.strip() for x in str(raw or "").split(",") if x.strip()]
    return items or list(default)


# -----------------------------
# Event-state gates
# -----------------------------

def _gate_none(df: pd.DataFrame) -> pd.Series:
    return pd.Series(True, index=df.index)


def _gate_neutral_revert(df: pd.DataFrame) -> pd.Series:
    neutral = _bool_col(df, "neutral_event", True)
    wick = _bool_col(df, "wick_revert_ok", False)
    spike = _bool_col(df, "spike_fade_ok", False)
    return neutral & (wick | spike)


def _gate_event_release_follow(df: pd.DataFrame) -> pd.Series:
    side = df.get("side", pd.Series(index=df.index, dtype=str)).astype(str).str.upper()
    neutral = _bool_col(df, "neutral_event", True)
    blocked = _bool_col(df, "event_blocked", False)
    flow = _bool_col(df, "flow_aligned", True)
    crowded = _bool_col(df, "risk_crowded_long", False)
    oi_high = _bool_col(df, "risk_oi_high", False)
    range_rel = _num_col(df, "range_rel", 1.0)
    vol_rel = _num_col(df, "vol_rel", 1.0)
    bar_ret = _num_col(df, "bar_ret", 0.0)
    close_loc = _num_col(df, "close_loc", 0.5)

    identified = (~neutral) | blocked
    impulse = (range_rel >= 1.08) | (vol_rel >= 1.05) | (bar_ret.abs() >= 0.006)
    long_release = (side == "LONG") & identified & flow & ~crowded & ~oi_high & impulse & (close_loc >= 0.60) & (bar_ret >= 0.002)
    short_release = (side == "SHORT") & identified & flow & (crowded | oi_high | blocked) & impulse & (close_loc <= 0.40) & (bar_ret <= -0.002)
    return long_release | short_release


def _gate_event_state_mix(df: pd.DataFrame) -> pd.Series:
    side = df.get("side", pd.Series(index=df.index, dtype=str)).astype(str).str.upper()
    neutral = _bool_col(df, "neutral_event", True)
    blocked = _bool_col(df, "event_blocked", False)
    flow = _bool_col(df, "flow_aligned", True)
    crowded = _bool_col(df, "risk_crowded_long", False)
    oi_high = _bool_col(df, "risk_oi_high", False)
    range_rel = _num_col(df, "range_rel", 1.0)
    vol_rel = _num_col(df, "vol_rel", 1.0)
    bar_ret = _num_col(df, "bar_ret", 0.0)
    close_loc = _num_col(df, "close_loc", 0.5)
    wick = _bool_col(df, "wick_revert_ok", False)
    spike = _bool_col(df, "spike_fade_ok", False)

    identified = (~neutral) | blocked
    neutral_ok = neutral & (wick | spike)
    long_drift = (side == "LONG") & identified & flow & ~crowded & ~oi_high & (range_rel >= 0.95) & (vol_rel >= 0.98) & (close_loc >= 0.56) & (bar_ret >= 0.001)
    short_drift = (side == "SHORT") & identified & flow & (crowded | oi_high | blocked) & (range_rel >= 0.95) & (vol_rel >= 0.98) & (close_loc <= 0.44) & (bar_ret <= -0.001)
    return neutral_ok | _gate_event_release_follow(df) | long_drift | short_drift


def _gate_event_state_guarded(df: pd.DataFrame) -> pd.Series:
    side = df.get("side", pd.Series(index=df.index, dtype=str)).astype(str).str.upper()
    neutral = _bool_col(df, "neutral_event", True)
    blocked = _bool_col(df, "event_blocked", False)
    flow = _bool_col(df, "flow_aligned", True)
    crowded = _bool_col(df, "risk_crowded_long", False)
    oi_high = _bool_col(df, "risk_oi_high", False)
    range_rel = _num_col(df, "range_rel", 1.0)
    vol_rel = _num_col(df, "vol_rel", 1.0)
    bar_ret = _num_col(df, "bar_ret", 0.0)
    close_loc = _num_col(df, "close_loc", 0.5)
    wick = _bool_col(df, "wick_revert_ok", False)
    spike = _bool_col(df, "spike_fade_ok", False)

    identified = (~neutral) | blocked
    long_neutral = (side == "LONG") & neutral & flow & (wick | spike) & (range_rel >= 1.00)
    short_neutral = (side == "SHORT") & neutral & flow & (wick | spike) & (crowded | oi_high) & (range_rel >= 1.00)
    long_release = (side == "LONG") & identified & flow & ~crowded & ~oi_high & (range_rel >= 1.05) & (vol_rel >= 1.02) & (close_loc >= 0.62) & (bar_ret >= 0.003)
    short_release = (side == "SHORT") & identified & flow & (crowded | oi_high | blocked) & (range_rel >= 1.05) & (vol_rel >= 1.02) & (close_loc <= 0.38) & (bar_ret <= -0.003)
    return long_neutral | short_neutral | long_release | short_release


def _gate_impact_tiered(df: pd.DataFrame) -> pd.Series:
    side = df.get("side", pd.Series(index=df.index, dtype=str)).astype(str).str.upper()
    symbol = df.get("symbol", pd.Series(index=df.index, dtype=str)).astype(str).str.upper()
    neutral = _bool_col(df, "neutral_event", True)
    blocked = _bool_col(df, "event_blocked", False)
    wick = _bool_col(df, "wick_revert_ok", False)
    spike = _bool_col(df, "spike_fade_ok", False)
    flow = _bool_col(df, "flow_aligned", True)
    crowded = _bool_col(df, "risk_crowded_long", False)
    oi_high = _bool_col(df, "risk_oi_high", False)
    range_rel = _num_col(df, "range_rel", 1.0)
    vol_rel = _num_col(df, "vol_rel", 1.0)
    impulse = (range_rel >= 1.15) | (vol_rel >= 1.05)
    struct = wick | spike

    long_neutral = (side == "LONG") & neutral & struct & impulse
    long_event = (side == "LONG") & ((~neutral) | blocked) & flow & ~crowded & ~oi_high & impulse

    short_neutral = (side == "SHORT") & neutral & struct & (crowded | oi_high) & impulse
    short_event = (side == "SHORT") & ((~neutral) | blocked) & flow & (crowded | oi_high | blocked) & impulse

    eth_long = (symbol == "ETH") & (long_neutral | long_event)
    eth_short = (symbol == "ETH") & (short_neutral | short_event)
    sol_long = (symbol == "SOL") & (long_neutral | long_event)
    sol_short = (symbol == "SOL") & (short_neutral | short_event)
    return eth_long | eth_short | sol_long | sol_short


def _gate_impact_tiered_flow(df: pd.DataFrame) -> pd.Series:
    side = df.get("side", pd.Series(index=df.index, dtype=str)).astype(str).str.upper()
    neutral = _bool_col(df, "neutral_event", True)
    blocked = _bool_col(df, "event_blocked", False)
    wick = _bool_col(df, "wick_revert_ok", False)
    spike = _bool_col(df, "spike_fade_ok", False)
    flow = _bool_col(df, "flow_aligned", True)
    crowded = _bool_col(df, "risk_crowded_long", False)
    oi_high = _bool_col(df, "risk_oi_high", False)
    range_rel = _num_col(df, "range_rel", 1.0)
    vol_rel = _num_col(df, "vol_rel", 1.0)
    bar_ret = _num_col(df, "bar_ret", 0.0).abs()
    strong_impulse = (range_rel >= 1.20) & ((vol_rel >= 1.05) | (bar_ret >= 0.008))
    struct = wick | spike

    long_ok = (side == "LONG") & (
        (neutral & struct & flow & strong_impulse & ~crowded)
        | (((~neutral) | blocked) & flow & ~crowded & ~oi_high & strong_impulse)
    )
    short_ok = (side == "SHORT") & (
        (neutral & struct & flow & (crowded | oi_high) & strong_impulse)
        | (((~neutral) | blocked) & flow & (crowded | oi_high | blocked) & strong_impulse)
    )
    return long_ok | short_ok


def _gate_shock_confirm(df: pd.DataFrame) -> pd.Series:
    side = df.get("side", pd.Series(index=df.index, dtype=str)).astype(str).str.upper()
    neutral = _bool_col(df, "neutral_event", True)
    blocked = _bool_col(df, "event_blocked", False)
    flow = _bool_col(df, "flow_aligned", True)
    crowded = _bool_col(df, "risk_crowded_long", False)
    oi_high = _bool_col(df, "risk_oi_high", False)
    wick = _bool_col(df, "wick_revert_ok", False)
    spike = _bool_col(df, "spike_fade_ok", False)
    range_rel = _num_col(df, "range_rel", 1.0)
    vol_rel = _num_col(df, "vol_rel", 1.0)
    bar_ret = _num_col(df, "bar_ret", 0.0).abs()
    shock = (range_rel >= 1.22) | (vol_rel >= 1.12) | (bar_ret >= 0.010)

    long_event = (side == "LONG") & ((~neutral) | blocked) & flow & ~crowded & ~oi_high & shock
    short_event = (side == "SHORT") & ((~neutral) | blocked) & flow & (crowded | oi_high | blocked) & shock
    short_revert = (side == "SHORT") & neutral & (wick | spike) & flow & (crowded | oi_high) & shock
    long_revert = (side == "LONG") & neutral & (wick | spike) & flow & ~crowded & shock
    return long_event | short_event | short_revert | long_revert


GATES: list[tuple[str, Callable[[pd.DataFrame], pd.Series], str]] = [
    ("base_message_overlay", _gate_none, "只保留消息面 overlay，不加事件状态机"),
    ("neutral_revert", _gate_neutral_revert, "无重大消息时，只做插针/过冲回归"),
    ("impact_tiered", _gate_impact_tiered, "先激进开方向，再用流向/拥挤度/波动强度筛掉垃圾机会"),
    ("impact_tiered_flow", _gate_impact_tiered_flow, "先放方向，再叠加 flow + 波动强度 + 结构确认"),
    ("shock_confirm", _gate_shock_confirm, "冲击窗口下先抢方向，再靠 shock/flow/crowding 做保守确认"),
    ("event_release_follow", _gate_event_release_follow, "事件释放窗口：只做有流向/拥挤度/收盘位置确认的跟随"),
    ("event_state_mix", _gate_event_state_mix, "中性冲击做回归；已识别事件做跟随/漂移确认"),
    ("event_state_guarded", _gate_event_state_guarded, "更保守的事件状态机：所有状态都要结构或衍生品确认"),
]


def _branch_score(metrics: dict[str, Any]) -> float:
    m = metrics.get("monthly", {}) or {}
    return float(
        _safe_float(metrics.get("pf")) * 94.0
        + _safe_float(metrics.get("ret")) * 72.0
        - abs(_safe_float(metrics.get("maxdd"))) * 78.0
        + min(int(metrics.get("trades", 0) or 0), 260) * 0.28
        + int(m.get("months_ge_20", 0) or 0) * 22.0
        + _safe_float(m.get("monthly_p75")) * 170.0
        + _safe_float(metrics.get("rolling12_pf_floor")) * 18.0
    )


def _branch_gate_label(metrics: dict[str, Any]) -> str:
    m = metrics.get("monthly", {}) or {}
    if _safe_float(metrics.get("pf")) >= 1.08 and _safe_float(metrics.get("ret")) > 0 and abs(_safe_float(metrics.get("maxdd"))) <= 0.45 and (int(m.get("months_ge_20", 0) or 0) >= 1 or _safe_float(m.get("monthly_p75")) >= 0.06):
        return "pass"
    if _safe_float(metrics.get("pf")) >= 1.00 and int(metrics.get("trades", 0) or 0) >= 12 and abs(_safe_float(metrics.get("maxdd"))) <= 0.60:
        return "hold"
    return "kill"


def _pick_best_gate(gate_rows: list[dict[str, Any]]) -> dict[str, Any]:
    best = None
    best_score = -1e18
    for row in gate_rows:
        metrics = row["metrics"]
        score = _branch_score(metrics)
        gate = _branch_gate_label(metrics)
        row["score"] = score
        row["gate"] = gate
        if score > best_score:
            best_score = score
            best = row
    return best if best is not None else gate_rows[0]


def _run_branch(root: Path, cfg: dict[str, Any], item: dict[str, Any], initial_equity: float) -> dict[str, Any]:
    cfg2 = copy.deepcopy(cfg)
    sym = str(item["symbol"]).lower()
    cfg2.setdefault("data", {})["symbols"] = [sym]
    cfg2.setdefault("data", {})["weights"] = {sym: 1.0}
    cfg2.setdefault("filters", {})["macro_gate_symbols"] = [sym]
    cfg2.setdefault("filters", {})["macro_gate_reference_symbol"] = sym
    data = s46._load_portfolio_data(root, cfg2)
    trades, trades_feat = s59._run_portfolio_candidate(root, cfg2, data, item["mods"])
    base_metrics = s59._metrics_from_trades(trades, initial_equity)
    gates = [s59._evaluate_gate(trades_feat, name, fn, note, initial_equity) for name, fn, note in GATES]
    return {
        "symbol": sym,
        "family": item.get("family", "mixed"),
        "name": item["name"],
        "note": item.get("note", ""),
        "base_metrics": base_metrics,
        "gate_rows": gates,
    }


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


def _strip_gate_payload(row: dict[str, Any]) -> dict[str, Any]:
    best = dict(row.get("best_gate") or {})
    gated_df = best.pop("gated_df", None)
    if isinstance(gated_df, pd.DataFrame):
        best["gated_rows"] = int(len(gated_df))
        best["gated_columns"] = list(gated_df.columns)[:12]
    return _json_safe(best)


def _write_branch(path_txt: Path, path_json: Path, rows: list[dict[str, Any]]) -> None:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((str(row["symbol"]).upper(), str(row["family"])), []).append(row)

    lines: list[str] = []
    lines.append("Stage76 分支四腿事件状态机")
    lines.append("核心原则：ETH / SOL 都保留多空；中性冲击做回归，已识别事件做跟随/漂移确认。")
    lines.append("")
    lines.append("=== 各赛道当前最优 ===")
    order = [("ETH", "long"), ("ETH", "short"), ("SOL", "long"), ("SOL", "short")]
    for key in order:
        items = grouped.get(key, [])
        if not items:
            continue
        best_row = max(items, key=lambda r: float(r["best_gate"]["score"]))
        best = best_row["best_gate"]
        m = best["metrics"]
        mm = m.get("monthly", {}) or {}
        lines.append(
            f"- {key[0]} | {key[1]}: {best_row['name']} | best_gate={best['gate_name']} ({best['gate']}) | trades={m['trades']} | win_rate={_fmt_pct(m.get('win_rate', 0.0))} | pf={_safe_float(m['pf']):.3f} | ret={_fmt_pct(m['ret'])} | maxDD={_fmt_pct(m['maxdd'])} | months>=20%={mm.get('months_ge_20', 0)} | p75_month={_fmt_pct(mm.get('monthly_p75', 0.0))} | score={best['score']:+.2f}"
        )
        lines.append(f"  note={best_row['note']} | gate_note={best['gate_note']}")
    lines.append("")
    lines.append("=== 全部候选 ===")
    for row in rows:
        best = row["best_gate"]
        m = best["metrics"]
        mm = m.get("monthly", {}) or {}
        lines.append(
            f"- {str(row['symbol']).upper()} | family={row['family']} | {row['name']}: best_gate={best['gate_name']} ({best['gate']}) | trades={m['trades']} | win_rate={_fmt_pct(m.get('win_rate', 0.0))} | pf={_safe_float(m['pf']):.3f} | ret={_fmt_pct(m['ret'])} | maxDD={_fmt_pct(m['maxdd'])} | months>=20%={mm.get('months_ge_20', 0)} | p75_month={_fmt_pct(mm.get('monthly_p75', 0.0))} | score={best['score']:+.2f}"
        )
        base = row.get("base_metrics", {})
        lines.append(
            f"  base=trades {base.get('trades', 0)} / win_rate {_fmt_pct(base.get('win_rate', 0.0))} / pf {_safe_float(base.get('pf')):.3f} / ret {_fmt_pct(base.get('ret'))} / maxDD {_fmt_pct(base.get('maxdd'))}"
        )
        lines.append(f"  note={row['note']} | gate_note={best['gate_note']}")
    lines.append("")
    lines.append("=== 结论 ===")
    lines.append("- ETH long 重点看 breakout-follow 是否能把有效机会接住；不是再一味收紧。")
    lines.append("- SOL short 重点继续压回撤，但不提前砍掉。")
    lines.append("- 单腿先做强；等单腿质量稳住，再考虑 dual。")
    path_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    path_json.write_text(
        json.dumps({"rows": [_json_safe({**row, "best_gate": _strip_gate_payload(row)}) for row in rows]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage76 branch event-state frontier")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--candidate-names", default="", help="逗号分隔；为空则用内置短名单")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    cfg = rcb.load_research_base_config(root)
    initial_equity = float(cfg.get("portfolio", {}).get("initial_equity", 100000.0))

    candidate_order = _resolve_candidate_names(args.candidate_names, DEFAULT_CANDIDATE_NAMES)
    items_map = {str(x.get("name")): x for x in _candidate_items()}
    chosen_items = [items_map[name] for name in candidate_order if name in items_map]
    if not chosen_items:
        raise SystemExit("未找到分支候选，无法运行 stage76。")

    rows = [_run_branch(root, cfg, item, initial_equity) for item in chosen_items]
    for row in rows:
        row["best_gate"] = _pick_best_gate(row["gate_rows"])
    rows.sort(key=lambda r: float(r["best_gate"]["score"]), reverse=True)

    reports_raw = root / "reports" / "research_raw"
    reports_raw.mkdir(parents=True, exist_ok=True)
    _write_branch(
        reports_raw / "stage76_branch_event_state_latest.txt",
        reports_raw / "stage76_branch_event_state_latest.json",
        rows,
    )
    print(reports_raw / "stage76_branch_event_state_latest.txt")
    print(reports_raw / "stage76_branch_event_state_latest.json")


if __name__ == "__main__":
    main()
