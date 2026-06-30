from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import stage46_aggressive_lab as s46
from tools import stage77_mainline_dual_window_lab as s77
from tools import stage88_strategy_fusion_walkforward as s88
from tools import stage90_event_alpha_matrix as s90
from tools import stage136_regime_plateau_frontier as s136
from tools import stage141_guarded_asymmetry_shortlist as s141
from tools import stage161_mainline_risk_budget_multiasset_link_frontier as s161
from tools import stage186_truth_anchor_target_lift_frontier as s186
from tools import stage193_anchor_plateau_beta_frontier as s193

TARGET_MONTHLY_MIN = float(s186.TARGET_MONTHLY_MIN)
TARGET_MONTHLY_MAX = float(s186.TARGET_MONTHLY_MAX)

SAFE_FLOAT = s186.SAFE_FLOAT
SAFE_INT = s186.SAFE_INT
WITH_META = s186.WITH_META
SYMBOL = s186.SYMBOL
FAMILY = s186.FAMILY
PLAYBOOK = s186.PLAYBOOK
WRITE_SINGLE_ZIP = s186.WRITE_SINGLE_ZIP


def _name(o: dict[str, Any] | None) -> str:
    return s193._name(o)


def _merge_item_map(base_items: list[dict[str, Any]], existing_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return s193._merge_item_map(base_items, existing_rows)


def _load_asset_summary(path: Path) -> list[dict[str, Any]]:
    return s193._load_asset_summary(path)


def _asset_active_map(asset_summary: list[dict[str, Any]]) -> dict[str, str]:
    return s193._asset_active_map(asset_summary)


def _active_bias(row: dict[str, Any], active_map: dict[str, str], *, branch: bool) -> float:
    if not branch:
        return 0.0
    sym = SYMBOL(row, branch=branch).upper()
    active = str(active_map.get(sym) or "").lower()
    pb = PLAYBOOK(row)
    name = str(row.get("name") or "").lower()
    bias = 0.0
    if sym == "ETH":
        if "reclaim_pair" in active and pb in {"eth_reclaim_pair_volfast", "eth_reclaim_pair_balance", "eth_reclaim_squeeze_hybrid"}:
            bias += 260.0
        if "reclaim_pair" in active and pb == "eth_jump_reversal_volgate":
            bias += 55.0
    if sym == "BTC":
        if "squeeze_follow" in active and pb == "btc_squeeze_voltarget":
            bias += 130.0
        if "squeeze_follow" in active and pb == "btc_breakout_voltarget":
            bias += 95.0
    if sym == "SOL":
        if "pullback_pair" in active and pb in {"sol_pullback_pair_volband", "sol_pullback_grid_rangeonly"}:
            bias += 180.0
        if "pullback_pair" in active and pb == "sol_guarded_short_volgate":
            bias += 45.0
    if active and active in name:
        bias += 60.0
    return bias


def _gate_bonus(row: dict[str, Any], *, branch: bool) -> float:
    gate = str(row.get("dominant_gate") or "")
    event_share = SAFE_FLOAT(row.get("event_fold_share"))
    sym = SYMBOL(row, branch=branch).upper()
    fam = FAMILY(row)
    bonus = 0.0
    if gate == "squeeze_followthrough_alpha":
        bonus += 35.0
        if sym in {"BTC", "SOL"} and fam == "long":
            bonus += 25.0
    elif gate == "reclaim_after_panic_alpha":
        bonus += 45.0
        if sym == "ETH":
            bonus += 35.0
    elif gate == "macro_drift_alpha":
        bonus += 25.0
        if sym == "BTC":
            bonus += 20.0
    elif gate == "base_message_overlay":
        bonus += 5.0
    if event_share >= 0.80:
        bonus += 40.0
    elif event_share >= 0.20:
        bonus += 20.0
    return bonus


def _score(row: dict[str, Any], runtime_anchor: dict[str, Any], active_map: dict[str, str], *, branch: bool) -> float:
    score = s193._score(row, runtime_anchor, active_map, branch=branch)
    score += _active_bias(row, active_map, branch=branch)
    score += _gate_bonus(row, branch=branch)
    recent, wf, _ = s186._runtime_adjusted_metrics(row, runtime_anchor, branch=branch)
    pb = PLAYBOOK(row)
    sym = SYMBOL(row, branch=branch)
    name = str(row.get("name") or "").lower()
    r_t = SAFE_INT(recent.get("trades"))
    w_t = SAFE_INT(wf.get("trades"))
    r_pf = SAFE_FLOAT(recent.get("pf"))
    w_pf = SAFE_FLOAT(wf.get("pf"))
    r_m = SAFE_FLOAT(recent.get("monthlyized_ret"))
    w_m = SAFE_FLOAT(wf.get("monthlyized_ret"))
    r_dd = abs(SAFE_FLOAT(recent.get("maxdd")))
    w_dd = abs(SAFE_FLOAT(wf.get("maxdd")))
    best_m = max(r_m, w_m)

    if not branch:
        if pb == "base":
            score += 90.0
        if pb == "mainline_bnb_volpulse":
            score += 240.0
        if pb == "mainline_bnb_volreentry":
            score += 210.0
        if best_m < 0.010:
            score -= 300.0
        if r_pf < 1.25 or w_pf < 1.10:
            score -= 220.0
        if pb != "base" and (r_t < 20 or w_t < 12):
            score -= 170.0
        if pb != "base" and (r_m <= 0.0 or w_m <= 0.0):
            score -= 420.0
        if r_dd > 0.12 or w_dd > 0.10:
            score -= 120.0
        return score

    if sym == "BTC" and "break_fail" in name:
        return score - 99999.0

    if sym == "ETH":
        if pb == "eth_reclaim_pair_volfast":
            score += 380.0
        if pb == "eth_reclaim_pair_balance":
            score += 340.0
        if pb == "eth_reclaim_squeeze_hybrid":
            score += 220.0
        if pb == "eth_jump_reversal_volgate":
            score += 95.0
        if pb in {"eth_reclaim_pair_volfast", "eth_reclaim_pair_balance", "eth_reclaim_squeeze_hybrid"}:
            if r_t >= 26 and w_t >= 18:
                score += 130.0
            if r_pf >= 1.80 and w_pf >= 1.60:
                score += 130.0
            if r_dd <= 0.060 and w_dd <= 0.060:
                score += 90.0
            if best_m >= 0.014:
                score += 120.0
            elif best_m >= 0.010:
                score += 70.0
            if min(r_t, w_t) < 10:
                score -= 260.0
        if pb == "eth_jump_reversal_volgate":
            if r_t >= 16 and w_t >= 12 and r_pf >= 1.10 and w_pf >= 1.05:
                score += 60.0
            if best_m < 0.0025:
                score -= 120.0

    if sym == "BTC":
        if pb == "btc_breakout_voltarget":
            score += 190.0
        if pb == "btc_squeeze_voltarget":
            score += 170.0
        if pb == "btc_jump_reversal_volgate":
            score += 70.0
        if pb in {"btc_breakout_voltarget", "btc_squeeze_voltarget"}:
            if r_t >= 14 and w_t >= 10:
                score += 70.0
            if r_pf >= 1.30 and w_pf >= 1.20:
                score += 60.0
            if r_dd <= 0.045 and w_dd <= 0.045:
                score += 40.0
            if best_m >= 0.0030:
                score += 30.0
        if r_t < 4 or w_t < 4:
            score -= 900.0

    if sym == "SOL":
        if pb == "sol_pullback_pair_volband":
            score += 240.0
        if pb == "sol_pullback_grid_rangeonly":
            score += 150.0
        if pb == "sol_guarded_short_volgate":
            score += 90.0
        if pb in {"sol_pullback_pair_volband", "sol_pullback_grid_rangeonly"}:
            if r_t >= 20 and w_t >= 14:
                score += 70.0
            if r_pf >= 1.15 and w_pf >= 1.10:
                score += 55.0
            if r_dd <= 0.045 and w_dd <= 0.045:
                score += 55.0
            if best_m >= 0.0015:
                score += 25.0
        if pb == "sol_guarded_short_volgate":
            if r_t >= 18 and w_t >= 14 and w_pf >= 1.05:
                score += 40.0
            if best_m < 0.0008:
                score -= 70.0
    return score


def _row_payload(row: dict[str, Any], runtime_anchor: dict[str, Any], active_map: dict[str, str], *, branch: bool) -> dict[str, Any]:
    recent, wf, full = s186._runtime_adjusted_metrics(row, runtime_anchor, branch=branch)
    best_m = max(SAFE_FLOAT(recent.get("monthlyized_ret")), SAFE_FLOAT(wf.get("monthlyized_ret")))
    return {
        "name": str(row.get("name") or ""),
        "symbol": SYMBOL(row, branch=branch),
        "family": FAMILY(row),
        "playbook": PLAYBOOK(row),
        "alpha_score": SAFE_FLOAT(row.get("alpha_score")),
        "score": _score(row, runtime_anchor, active_map, branch=branch),
        "status": s186._status(row, runtime_anchor, branch=branch),
        "recent_monthly": SAFE_FLOAT(recent.get("monthlyized_ret")),
        "wf_monthly": SAFE_FLOAT(wf.get("monthlyized_ret")),
        "recent_ret": SAFE_FLOAT(recent.get("ret")),
        "wf_ret": SAFE_FLOAT(wf.get("ret")),
        "recent_pf": SAFE_FLOAT(recent.get("pf")),
        "wf_pf": SAFE_FLOAT(wf.get("pf")),
        "recent_trades": SAFE_INT(recent.get("trades")),
        "wf_trades": SAFE_INT(wf.get("trades")),
        "recent_maxdd": SAFE_FLOAT(recent.get("maxdd")),
        "wf_maxdd": SAFE_FLOAT(wf.get("maxdd")),
        "full_ret": SAFE_FLOAT(full.get("ret")),
        "full_pf": SAFE_FLOAT(full.get("pf")),
        "full_trades": SAFE_INT(full.get("trades")),
        "gap_to_floor": TARGET_MONTHLY_MIN - best_m,
    }


def _top_payload(rows: list[dict[str, Any]], runtime_anchor: dict[str, Any], active_map: dict[str, str], *, branch: bool) -> list[dict[str, Any]]:
    payload = [_row_payload(r, runtime_anchor, active_map, branch=branch) for r in rows]
    payload.sort(key=lambda r: (r["score"], r["alpha_score"]), reverse=True)
    return payload


def _select_top(payload: list[dict[str, Any]], *, symbol: str | None = None, limit: int = 5) -> list[dict[str, Any]]:
    rows = payload
    if symbol:
        rows = [r for r in rows if r["symbol"] == symbol]
    return rows[:limit]


def _mainline_items(existing_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    item_map = _merge_item_map(s88._mainline_items(), existing_rows)
    out: list[dict[str, Any]] = []

    def add(base_name: str, *, name: str, note: str, patch: dict[str, Any], track: str, playbook: str) -> None:
        base = item_map.get(base_name)
        if base is None:
            return
        out.append(
            WITH_META(
                s88._make_mainline_variant(base, name=name, note=note, patch=patch),
                track=track,
                branch=False,
                anchor_name=base_name,
                playbook=playbook,
            )
        )

    anchor = "mainline_live_dynlev_fix8_lock18" if "mainline_live_dynlev_fix8_lock18" in item_map else "mainline_core_satellite_dynlev_fix8_lock18"
    add(
        anchor,
        name="mainline_live_dynlev_fix8_lock18_bnb_volpulse_lb20_buf042_cd4_bnb128_btc500",
        note="主线 stage194：volatility-managed BNB pulse，提频但不再靠死放宽。",
        patch={
            "strategy_params.breakout_lookback": 20,
            "strategy_params.breakout_atr_buffer": 0.42,
            "strategy_params.cooldown_bars": 4,
            "filters.adx_floor": 20,
            "execution_guard.pause_bars": 4,
            "money_management.stake_scale.bnb_long": 1.28,
            "money_management.stake_scale.btc_short": 5.00,
            "money_management.take_profit_pct": 1.12,
            "money_management.trailing_profit.activation_pnl_pct": 0.34,
            "money_management.trailing_profit.giveback_ratio": 0.18,
            "money_management.trailing_profit.min_lock_pnl_pct": 0.06,
        },
        track="mainline_bnb_volpulse",
        playbook="mainline_bnb_volpulse",
    )
    add(
        anchor,
        name="mainline_live_dynlev_fix8_lock18_bnb_volreentry_lb22_buf044_cd6_bnb122_btc520",
        note="主线 stage194：更稳一档 BNB vol-reentry，给主线只留一条平衡备用。",
        patch={
            "strategy_params.breakout_lookback": 22,
            "strategy_params.breakout_atr_buffer": 0.44,
            "strategy_params.cooldown_bars": 6,
            "filters.adx_floor": 22,
            "execution_guard.pause_bars": 5,
            "money_management.stake_scale.bnb_long": 1.22,
            "money_management.stake_scale.btc_short": 5.20,
            "money_management.take_profit_pct": 1.10,
            "money_management.trailing_profit.activation_pnl_pct": 0.32,
            "money_management.trailing_profit.giveback_ratio": 0.18,
            "money_management.trailing_profit.min_lock_pnl_pct": 0.06,
        },
        track="mainline_bnb_volreentry",
        playbook="mainline_bnb_volreentry",
    )
    return out


def _branch_items(existing_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    item_map = _merge_item_map(s88._branch_items(), existing_rows)
    out: list[dict[str, Any]] = []

    def add(item: dict[str, Any] | None, *, name: str, note: str, family: str, patch: dict[str, Any], track: str, anchor_name: str, playbook: str) -> None:
        if item is None:
            return
        out.append(
            WITH_META(
                s88._make_variant(item, name=name, note=note, family=family, patch=patch),
                track=track,
                branch=True,
                anchor_name=anchor_name,
                playbook=playbook,
            )
        )

    btc_squeeze = item_map.get("btc_squeeze_follow_long_lb16_atr050_adx20_s058") or item_map.get("btc_breakout_long_event_lb20_atr060_adx24_s050")
    btc_breakout = item_map.get("btc_breakout_long_event_lb20_atr060_adx24_s050") or btc_squeeze
    btc_short = item_map.get("btc_retest_short_event_lb20_atr060_adx24_s072") or item_map.get("btc_retest_short_trend_lb20_atr060_adx24_s072")

    eth_reclaim_pair = item_map.get("eth_reclaim_pair_long_lb10_atr040_adx15_cd1_s064") or item_map.get("eth_reclaim_pair_long_lb11_atr043_adx16_s056") or item_map.get("eth_reclaim_long_lb12_atr043_adx16_s060")
    eth_squeeze = item_map.get("eth_squeeze_follow_long_lb8_atr036_adx13_s058") or item_map.get("eth_squeeze_follow_long_lb9_atr040_adx15_s048") or eth_reclaim_pair
    eth_short = item_map.get("eth_retest_short_trend_lb12_atr044_adx16_cd1_s076") or item_map.get("eth_retest_short_trend_lb20_atr060_adx24_cd3_s068") or item_map.get("eth_retest_short_trend_lb20_atr060_adx24_s068")

    sol_pullback = item_map.get("sol_pullback_pair_long_adx24_cd4_lb20_zone024_s046") or item_map.get("sol_pullback_long_core_adx26_cd6_lb22_zone026_s040")
    sol_grid = item_map.get("sol_pullback_grid_long_adx26_cd4_lb22_zone026_s046") or sol_pullback
    sol_short = item_map.get("sol_guarded_short_accel_lb14_atr052_adx18_cd1_s076") or item_map.get("sol_retest_short_trend_lb16_atr050_adx20_s068")

    add(
        btc_breakout,
        name="btc_breakout_long_event_lb18_atr056_adx22_s054",
        note="BTC stage194：voltarget breakout，中速不再过快。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 18,
            "strategy_params.breakout_atr_buffer": 0.56,
            "strategy_params.cooldown_bars": 2,
            "filters.adx_floor": 22,
            "money_management.stake_scale.btc_long": 0.54,
            "money_management.take_profit_pct": 1.10,
            "money_management.trailing_profit.activation_pnl_pct": 0.32,
            "money_management.trailing_profit.giveback_ratio": 0.18,
        },
        track="btc_breakout_voltarget",
        anchor_name=_name(btc_breakout),
        playbook="btc_breakout_voltarget",
    )
    add(
        btc_squeeze,
        name="btc_squeeze_follow_long_lb14_atr046_adx18_s062",
        note="BTC stage194：voltarget squeeze，中速加一点频率。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 14,
            "strategy_params.breakout_atr_buffer": 0.46,
            "strategy_params.cooldown_bars": 2,
            "filters.adx_floor": 18,
            "money_management.stake_scale.btc_long": 0.56,
            "money_management.take_profit_pct": 1.08,
            "money_management.trailing_profit.activation_pnl_pct": 0.30,
            "money_management.trailing_profit.giveback_ratio": 0.18,
        },
        track="btc_squeeze_voltarget",
        anchor_name=_name(btc_squeeze),
        playbook="btc_squeeze_voltarget",
    )
    add(
        btc_short,
        name="btc_retest_short_event_lb14_atr050_adx18_s078",
        note="BTC stage194：空腿只保一条 vol-gated retest。",
        family="short",
        patch={
            "strategy_params.breakout_lookback": 14,
            "strategy_params.breakout_atr_buffer": 0.50,
            "strategy_params.cooldown_bars": 1,
            "filters.adx_floor": 18,
            "money_management.stake_scale.btc_short": 0.72,
            "money_management.take_profit_pct": 0.92,
            "money_management.trailing_profit.activation_pnl_pct": 0.28,
            "money_management.trailing_profit.giveback_ratio": 0.16,
        },
        track="btc_jump_reversal_volgate",
        anchor_name=_name(btc_short),
        playbook="btc_jump_reversal_volgate",
    )

    add(
        eth_reclaim_pair,
        name="eth_reclaim_pair_long_lb8_atr036_adx13_cd1_s070",
        note="ETH stage194：更快一档 reclaim_pair，主攻提频。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 8,
            "strategy_params.breakout_atr_buffer": 0.36,
            "strategy_params.cooldown_bars": 1,
            "filters.adx_floor": 13,
            "money_management.stake_scale.eth_long": 0.64,
            "money_management.take_profit_pct": 1.16,
            "money_management.trailing_profit.activation_pnl_pct": 0.34,
            "money_management.trailing_profit.giveback_ratio": 0.18,
        },
        track="eth_reclaim_pair_volfast",
        anchor_name=_name(eth_reclaim_pair),
        playbook="eth_reclaim_pair_volfast",
    )
    add(
        eth_reclaim_pair,
        name="eth_reclaim_pair_long_lb10_atr040_adx15_cd2_s062",
        note="ETH stage194：平衡版 reclaim_pair，保留样本厚度。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 10,
            "strategy_params.breakout_atr_buffer": 0.40,
            "strategy_params.cooldown_bars": 2,
            "filters.adx_floor": 15,
            "money_management.stake_scale.eth_long": 0.60,
            "money_management.take_profit_pct": 1.12,
            "money_management.trailing_profit.activation_pnl_pct": 0.32,
            "money_management.trailing_profit.giveback_ratio": 0.18,
        },
        track="eth_reclaim_pair_balance",
        anchor_name=_name(eth_reclaim_pair),
        playbook="eth_reclaim_pair_balance",
    )
    add(
        eth_squeeze,
        name="eth_reclaim_squeeze_long_lb9_atr038_adx14_cd1_s066",
        note="ETH stage194：reclaim + squeeze 混合，只留一条创新轨。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 9,
            "strategy_params.breakout_atr_buffer": 0.38,
            "strategy_params.cooldown_bars": 1,
            "filters.adx_floor": 14,
            "money_management.stake_scale.eth_long": 0.58,
            "money_management.take_profit_pct": 1.10,
            "money_management.trailing_profit.activation_pnl_pct": 0.30,
            "money_management.trailing_profit.giveback_ratio": 0.18,
        },
        track="eth_reclaim_squeeze_hybrid",
        anchor_name=_name(eth_squeeze),
        playbook="eth_reclaim_squeeze_hybrid",
    )
    add(
        eth_short,
        name="eth_retest_short_trend_lb10_atr042_adx14_cd1_s080",
        note="ETH stage194：jump-reversal short 继续只留一条。",
        family="short",
        patch={
            "strategy_params.breakout_lookback": 10,
            "strategy_params.breakout_atr_buffer": 0.42,
            "strategy_params.cooldown_bars": 1,
            "filters.adx_floor": 14,
            "money_management.stake_scale.eth_short": 0.72,
            "money_management.take_profit_pct": 0.88,
            "money_management.trailing_profit.activation_pnl_pct": 0.26,
            "money_management.trailing_profit.giveback_ratio": 0.16,
        },
        track="eth_jump_reversal_volgate",
        anchor_name=_name(eth_short),
        playbook="eth_jump_reversal_volgate",
    )

    add(
        sol_pullback,
        name="sol_pullback_pair_long_adx22_cd3_lb18_zone022_s052",
        note="SOL stage194：volband pullback_pair，更快一档。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 18,
            "strategy_params.breakout_atr_buffer": 0.50,
            "strategy_params.cooldown_bars": 3,
            "filters.adx_floor": 22,
            "money_management.stake_scale.sol_long": 0.50,
            "money_management.take_profit_pct": 1.10,
            "money_management.trailing_profit.activation_pnl_pct": 0.32,
            "money_management.trailing_profit.giveback_ratio": 0.18,
        },
        track="sol_pullback_pair_volband",
        anchor_name=_name(sol_pullback),
        playbook="sol_pullback_pair_volband",
    )
    add(
        sol_grid,
        name="sol_pullback_grid_long_adx24_cd3_lb20_zone024_s048",
        note="SOL stage194：只保 range-only grid，一条就够。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 20,
            "strategy_params.breakout_atr_buffer": 0.50,
            "strategy_params.cooldown_bars": 3,
            "filters.adx_floor": 24,
            "money_management.stake_scale.sol_long": 0.48,
            "money_management.take_profit_pct": 1.08,
            "money_management.trailing_profit.activation_pnl_pct": 0.30,
            "money_management.trailing_profit.giveback_ratio": 0.18,
        },
        track="sol_pullback_grid_rangeonly",
        anchor_name=_name(sol_grid),
        playbook="sol_pullback_grid_rangeonly",
    )
    add(
        sol_short,
        name="sol_guarded_short_accel_lb12_atr050_adx16_cd1_s078",
        note="SOL stage194：guarded short 只保一条 vol-gated。",
        family="short",
        patch={
            "strategy_params.breakout_lookback": 12,
            "strategy_params.breakout_atr_buffer": 0.50,
            "strategy_params.cooldown_bars": 1,
            "filters.adx_floor": 16,
            "money_management.stake_scale.sol_short": 0.64,
            "money_management.take_profit_pct": 0.92,
            "money_management.trailing_profit.activation_pnl_pct": 0.28,
            "money_management.trailing_profit.giveback_ratio": 0.16,
        },
        track="sol_guarded_short_volgate",
        anchor_name=_name(sol_short),
        playbook="sol_guarded_short_volgate",
    )
    return out


def _write_report(path_txt: Path, path_json: Path, main_rows: list[dict[str, Any]], branch_rows: list[dict[str, Any]], repaired_main: list[str], repaired_branch: list[str], scanned_main: list[str], scanned_branch: list[str], runtime_anchor: dict[str, Any], asset_summary: list[dict[str, Any]]) -> dict[str, Any]:
    active_map = _asset_active_map(asset_summary)
    main_payload = _top_payload(main_rows, runtime_anchor, active_map, branch=False)
    branch_payload = _top_payload(branch_rows, runtime_anchor, active_map, branch=True)
    split_rec = s186._split_recommendation(branch_payload)
    summary = {
        "target_monthly_min": TARGET_MONTHLY_MIN,
        "target_monthly_max": TARGET_MONTHLY_MAX,
        "repaired_main": repaired_main,
        "repaired_branch": repaired_branch,
        "scanned_main": scanned_main,
        "scanned_branch": scanned_branch,
        "runtime_anchor": runtime_anchor,
        "stage91_active": active_map,
        "split_recommendation": split_rec,
        "asset_summary": asset_summary,
        "main_top": _select_top(main_payload, limit=5),
        "branch_by_symbol": {sym: _select_top(branch_payload, symbol=sym, limit=5) for sym in ["btc", "eth", "sol"]},
    }

    lines: list[str] = []
    lines.append("Stage194 voltarget-hybrid frontier")
    lines.append("")
    lines.append("[summary]")
    lines.append(f"- target_monthly_floor={TARGET_MONTHLY_MIN*100:.2f}% target_monthly_ceiling={TARGET_MONTHLY_MAX*100:.2f}%")
    lines.append(f"- repaired_main={len(repaired_main)} repaired_branch={len(repaired_branch)}")
    lines.append(f"- scanned_main={len(scanned_main)} scanned_branch={len(scanned_branch)}")
    lines.append(f"- stage91_active={json.dumps(active_map, ensure_ascii=False)}")
    lines.append(f"- split_recommendation={split_rec}")
    lines.append("")
    lines.append("[focus]")
    lines.append("- 主线: 停掉低效率微调，只留 2 条 BNB vol-managed reentry/pulse。")
    lines.append("- ETH: reclaim_pair sprint + balance 主攻，再留 1 条 reclaim/squeeze 混合创新线。")
    lines.append("- BTC: 只保 breakout / squeeze / 1条 short。")
    lines.append("- SOL: 只保 pullback_pair / range-only grid / 1条 guarded short。")
    lines.append("")
    lines.append("[main_top]")
    for row in summary["main_top"]:
        lines.append(
            f"- {row['name']} | playbook={row['playbook']} | status={row['status']} | 6年={row['full_ret']*100:.2f}% | 近2年月化={row['recent_monthly']*100:.2f}% | WF月化={row['wf_monthly']*100:.2f}% | 近2年交易={row['recent_trades']} | WF交易={row['wf_trades']} | gap_to_7.6={row['gap_to_floor']*100:.2f}%"
        )
    lines.append("")
    for sym in ["eth", "btc", "sol"]:
        lines.append(f"[{sym}_top]")
        for row in summary["branch_by_symbol"][sym]:
            lines.append(
                f"- {row['name']} | playbook={row['playbook']} | status={row['status']} | 近2年={row['recent_ret']*100:.2f}% | 近2年月化={row['recent_monthly']*100:.2f}% | WF={row['wf_ret']*100:.2f}% | WF月化={row['wf_monthly']*100:.2f}% | 近2年交易={row['recent_trades']} | WF交易={row['wf_trades']} | gap_to_7.6={row['gap_to_floor']*100:.2f}%"
            )
        lines.append("")
    lines.append("[stage91_asset_summary]")
    for item in asset_summary:
        sym = str(item.get("symbol") or "")
        mode = str(item.get("mode") or "")
        active = str((item.get("active") or {}).get("name") or "")
        note = str(item.get("note") or "")
        lines.append(f"- {sym}: mode={mode} | active={active} | note={note}")
    lines.append("")
    lines.append("[conclusion]")
    lines.append("- ETH 先围绕 reclaim_pair s064 做 vol-fast / balance 两档，再看 hybrid 是否能抬月化。")
    lines.append("- BTC 继续只保 moderate breakout / squeeze，不再追超快零成交线。")
    lines.append("- SOL 继续 pullback_pair 主攻，grid 只限 range-only。")
    lines.append("- 继续 1 个 branch 终端。")
    txt = "\n".join(lines).rstrip() + "\n"
    path_txt.write_text(txt, encoding="utf-8")
    path_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage194 voltarget-hybrid frontier")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    raw = root / "reports" / "research_raw"
    raw.mkdir(parents=True, exist_ok=True)

    main_rows, branch_rows, repaired_main, repaired_branch = s141._load_stage_state(raw)
    cfg = s186._load_live_cfg(root)
    initial_equity = float(cfg.get("portfolio", {}).get("initial_equity", 100000.0))
    data = s46._load_portfolio_data(root, cfg)
    full_start, full_end = s77._window_bounds_from_data(data)
    runtime_anchor = s186._parse_runtime_anchor(root)

    item_map = _merge_item_map(s88._mainline_items(), main_rows)
    ref_item = item_map.get("mainline_live_dynlev_fix8_lock18") or item_map.get("mainline_live_base")
    if ref_item is None:
        raise SystemExit("missing mainline reference")
    ref_row = s136._run_mainline(root, cfg, data, WITH_META(ref_item, track="base", branch=False, anchor_name=str(ref_item.get("name")), playbook="base"), initial_equity, full_start, full_end)

    main_map = {str(r.get("name")): s161._ensure_mainline_row(r, ref_row, initial_equity, full_end) for r in main_rows}
    scanned_main: list[str] = []
    for item in _mainline_items(main_rows):
        print(f"[stage194] main {item['name']}", flush=True)
        row = s136._run_mainline(root, cfg, data, item, initial_equity, full_start, full_end)
        row = s161._ensure_mainline_row(row, ref_row, initial_equity, full_end)
        main_map[str(row.get("name"))] = row
        scanned_main.append(str(row.get("name")))
    main_rows = s161._finalize_rows(list(main_map.values()), branch=False)

    branch_map = {str(r.get("name")): s161._ensure_branch_row(r, initial_equity) for r in branch_rows}
    scanned_branch: list[str] = []
    for item in _branch_items(branch_rows):
        print(f"[stage194] branch {item['name']}", flush=True)
        row = s136._run_branch(root, cfg, item, initial_equity)
        row = s161._ensure_branch_row(row, initial_equity)
        branch_map[str(row.get("name"))] = row
        scanned_branch.append(str(row.get("name")))
    branch_rows = s161._finalize_rows(list(branch_map.values()), branch=True)

    main_txt = raw / "stage90_mainline_event_alpha_matrix_latest.txt"
    main_json = raw / "stage90_mainline_event_alpha_matrix_latest.json"
    branch_txt = raw / "stage91_branch_event_alpha_matrix_latest.txt"
    branch_json = raw / "stage91_branch_event_alpha_matrix_latest.json"
    s90._write_mainline(main_txt, main_json, main_rows)
    s90._write_branch(branch_txt, branch_json, branch_rows)

    asset_summary = _load_asset_summary(branch_json)

    frontier_txt = raw / "stage194_voltarget_hybrid_frontier_latest.txt"
    frontier_json = raw / "stage194_voltarget_hybrid_frontier_latest.json"
    summary = _write_report(frontier_txt, frontier_json, main_rows, branch_rows, repaired_main, repaired_branch, scanned_main, scanned_branch, runtime_anchor, asset_summary)
    manifest = {
        "mode": "voltarget_hybrid_frontier",
        "target_monthly_min": TARGET_MONTHLY_MIN,
        "target_monthly_max": TARGET_MONTHLY_MAX,
        "repaired_main": repaired_main,
        "repaired_branch": repaired_branch,
        "scanned_main": scanned_main,
        "scanned_branch": scanned_branch,
        "runtime_anchor": runtime_anchor,
        "stage91_active": summary.get("stage91_active"),
        "split_recommendation": summary.get("split_recommendation"),
        "outputs": {
            "stage90_txt": str(main_txt),
            "stage90_json": str(main_json),
            "stage91_txt": str(branch_txt),
            "stage91_json": str(branch_json),
            "frontier_txt": str(frontier_txt),
            "frontier_json": str(frontier_json),
        },
    }
    manifest_path = raw / "stage194_voltarget_hybrid_frontier_manifest_latest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    s141._mirror_to_workspace(root, [main_txt, main_json, branch_txt, branch_json, frontier_txt, frontier_json, manifest_path])

    out_zip = root.parent / "Downloads" / "stage194_voltarget_hybrid_frontier_latest.zip"
    WRITE_SINGLE_ZIP(out_zip, {
        "stage194_voltarget_hybrid_frontier_latest.txt": frontier_txt,
        "stage194_voltarget_hybrid_frontier_latest.json": frontier_json,
        "stage194_voltarget_hybrid_frontier_manifest_latest.json": manifest_path,
        "stage90_mainline_event_alpha_matrix_latest.txt": main_txt,
        "stage90_mainline_event_alpha_matrix_latest.json": main_json,
        "stage91_branch_event_alpha_matrix_latest.txt": branch_txt,
        "stage91_branch_event_alpha_matrix_latest.json": branch_json,
    })
    print(out_zip)


if __name__ == "__main__":
    main()
