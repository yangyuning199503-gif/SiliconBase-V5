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
    if not o:
        return ""
    return str(o.get("name") or "")


def _merge_item_map(base_items: list[dict[str, Any]], existing_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for src in (base_items, existing_rows):
        for item in src:
            nm = str(item.get("name") or "")
            if nm:
                out[nm] = item
    return out


def _load_asset_summary(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return list(data.get("asset_summary") or [])
    except Exception:
        return []


def _asset_active_map(asset_summary: list[dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in asset_summary:
        sym = str(item.get("symbol") or "").upper()
        active = item.get("active") or {}
        out[sym] = str(active.get("name") or "")
    return out


def _score(row: dict[str, Any], runtime_anchor: dict[str, Any], *, branch: bool) -> float:
    score = s186._score(row, runtime_anchor, branch=branch)
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
            score += 70.0
        if pb == "mainline_bnb_reentry_web":
            score += 180.0
        if pb == "mainline_bnb_pulse_web":
            score += 140.0
        if best_m < 0.004:
            score -= 260.0
        if r_pf < 1.20 or w_pf < 1.05:
            score -= 170.0
        if pb != "base" and (r_m <= 0.0 or w_m <= 0.0):
            score -= 380.0
        if pb != "base" and (r_t < 18 or w_t < 12):
            score -= 160.0
        return score

    if sym == "btc" and ("break_fail" in name or ("pair" in name and "event_pair" in name)):
        return score - 99999.0

    if sym == "eth":
        if pb == "eth_reclaim_pair_fast_web":
            score += 460.0
        if pb == "eth_reclaim_ladder_web":
            score += 420.0
        if pb == "eth_squeeze_follow_fast_web":
            score += 230.0
        if pb == "eth_jump_reversal_web":
            score += 150.0
        if pb == "eth_event_drift_fast_web":
            score += 120.0
        if pb in {"eth_reclaim_pair_fast_web", "eth_reclaim_ladder_web", "eth_squeeze_follow_fast_web", "eth_event_drift_fast_web"}:
            if r_t >= 28 and w_t >= 18:
                score += 120.0
            if r_pf >= 2.00 and w_pf >= 2.00:
                score += 120.0
            if r_dd <= 0.055 and w_dd <= 0.055:
                score += 80.0
            if best_m >= 0.009:
                score += 90.0
            if min(r_t, w_t) < 12:
                score -= 260.0
        if pb == "eth_jump_reversal_web":
            if r_t >= 14 and w_t >= 12 and r_pf >= 1.20 and w_pf >= 1.15:
                score += 70.0
            if best_m < 0.003:
                score -= 120.0

    if sym == "btc":
        if pb == "btc_squeeze_follow_moderate":
            score += 280.0
        if pb == "btc_breakout_moderate":
            score += 240.0
        if pb == "btc_jump_reversal_moderate":
            score += 120.0
        if pb in {"btc_squeeze_follow_moderate", "btc_breakout_moderate"}:
            if r_t >= 16 and w_t >= 12:
                score += 70.0
            if r_pf >= 1.45 and w_pf >= 1.35:
                score += 70.0
            if r_dd <= 0.040 and w_dd <= 0.040:
                score += 40.0
            if best_m >= 0.003:
                score += 25.0
        if r_t < 6 or w_t < 6:
            score -= 900.0

    if sym == "sol":
        if pb == "sol_pullback_pair_fast_web":
            score += 300.0
        if pb == "sol_range_ladder_fast_web":
            score += 180.0
        if pb == "sol_guarded_short_fast_web":
            score += 170.0
        if pb == "sol_pullback_grid_fast_web":
            score += 150.0
        if pb in {"sol_pullback_pair_fast_web", "sol_range_ladder_fast_web", "sol_pullback_grid_fast_web"}:
            if r_t >= 24 and w_t >= 18:
                score += 70.0
            if r_pf >= 1.20 and w_pf >= 1.15:
                score += 60.0
            if r_dd <= 0.040 and w_dd <= 0.040:
                score += 60.0
            if best_m >= 0.0018:
                score += 20.0
        if pb == "sol_guarded_short_fast_web":
            if r_t >= 20 and w_t >= 16 and w_pf >= 1.10:
                score += 50.0
            if best_m < 0.001:
                score -= 80.0

    return score


def _row_payload(row: dict[str, Any], runtime_anchor: dict[str, Any], *, branch: bool) -> dict[str, Any]:
    recent, wf, full = s186._runtime_adjusted_metrics(row, runtime_anchor, branch=branch)
    best_m = max(SAFE_FLOAT(recent.get("monthlyized_ret")), SAFE_FLOAT(wf.get("monthlyized_ret")))
    return {
        "name": str(row.get("name") or ""),
        "symbol": SYMBOL(row, branch=branch),
        "family": FAMILY(row),
        "playbook": PLAYBOOK(row),
        "alpha_score": SAFE_FLOAT(row.get("alpha_score")),
        "score": _score(row, runtime_anchor, branch=branch),
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


def _top_payload(rows: list[dict[str, Any]], runtime_anchor: dict[str, Any], *, branch: bool) -> list[dict[str, Any]]:
    payload = [_row_payload(r, runtime_anchor, branch=branch) for r in rows]
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
        name="mainline_live_dynlev_fix8_lock18_bnb_reentry_lb22_buf044_cd6_bnb122_btc540",
        note="主线 stage192：BNB reentry + vol target，只留一条更贴近当前基线的提频线。",
        patch={
            "strategy_params.breakout_lookback": 22,
            "strategy_params.breakout_atr_buffer": 0.44,
            "strategy_params.cooldown_bars": 6,
            "filters.adx_floor": 22,
            "execution_guard.pause_bars": 5,
            "money_management.stake_scale.bnb_long": 1.22,
            "money_management.stake_scale.btc_short": 5.40,
            "money_management.take_profit_pct": 1.12,
            "money_management.trailing_profit.activation_pnl_pct": 0.38,
            "money_management.trailing_profit.giveback_ratio": 0.18,
            "money_management.trailing_profit.min_lock_pnl_pct": 0.06,
        },
        track="mainline_bnb_reentry_web",
        playbook="mainline_bnb_reentry_web",
    )
    add(
        anchor,
        name="mainline_live_dynlev_fix8_lock18_bnb_pulse_lb20_buf042_cd4_bnb126_btc520",
        note="主线 stage192：BNB pulse 只保一条较快线，用来验证提频上限。",
        patch={
            "strategy_params.breakout_lookback": 20,
            "strategy_params.breakout_atr_buffer": 0.42,
            "strategy_params.cooldown_bars": 4,
            "filters.adx_floor": 20,
            "execution_guard.pause_bars": 4,
            "money_management.stake_scale.bnb_long": 1.26,
            "money_management.stake_scale.btc_short": 5.20,
            "money_management.take_profit_pct": 1.08,
            "money_management.trailing_profit.activation_pnl_pct": 0.34,
            "money_management.trailing_profit.giveback_ratio": 0.16,
            "money_management.trailing_profit.min_lock_pnl_pct": 0.06,
        },
        track="mainline_bnb_pulse_web",
        playbook="mainline_bnb_pulse_web",
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

    eth_reclaim_pair = item_map.get("eth_reclaim_pair_long_lb11_atr043_adx16_s056") or item_map.get("eth_reclaim_long_lb12_atr043_adx16_s060")
    eth_ladder = item_map.get("eth_reclaim_ladder_long_lb11_atr043_adx16_cd2_s064") or eth_reclaim_pair
    eth_squeeze = item_map.get("eth_squeeze_follow_long_lb9_atr040_adx15_s048") or eth_reclaim_pair
    eth_short = item_map.get("eth_retest_short_trend_lb20_atr060_adx24_cd3_s068") or item_map.get("eth_retest_short_trend_lb20_atr060_adx24_s068")

    sol_pullback = item_map.get("sol_pullback_pair_long_adx24_cd4_lb20_zone024_s046") or item_map.get("sol_pullback_long_core_adx26_cd6_lb22_zone026_s040")
    sol_grid = item_map.get("sol_pullback_grid_long_adx26_cd4_lb22_zone026_s046") or sol_pullback
    sol_short = item_map.get("sol_guarded_short_accel_lb14_atr052_adx18_cd1_s076") or item_map.get("sol_retest_short_trend_lb16_atr050_adx20_s068")

    add(
        btc_squeeze,
        name="btc_squeeze_follow_long_lb14_atr046_adx18_s062",
        note="BTC stage192：回到中速 squeeze，不再追 0 交易的超快线。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 14,
            "strategy_params.breakout_atr_buffer": 0.46,
            "strategy_params.cooldown_bars": 2,
            "filters.adx_floor": 18,
            "money_management.stake_scale.btc_long": 0.60,
            "money_management.take_profit_pct": 1.10,
            "money_management.trailing_profit.activation_pnl_pct": 0.34,
            "money_management.trailing_profit.giveback_ratio": 0.18,
        },
        track="btc_squeeze_follow_moderate",
        anchor_name=_name(btc_squeeze),
        playbook="btc_squeeze_follow_moderate",
    )
    add(
        btc_breakout,
        name="btc_breakout_long_event_lb18_atr056_adx22_s054",
        note="BTC stage192：moderate breakout，保趋势不做过快漂移。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 18,
            "strategy_params.breakout_atr_buffer": 0.56,
            "strategy_params.cooldown_bars": 2,
            "filters.adx_floor": 22,
            "money_management.stake_scale.btc_long": 0.54,
            "money_management.take_profit_pct": 1.08,
            "money_management.trailing_profit.activation_pnl_pct": 0.32,
            "money_management.trailing_profit.giveback_ratio": 0.18,
        },
        track="btc_breakout_moderate",
        anchor_name=_name(btc_breakout),
        playbook="btc_breakout_moderate",
    )
    add(
        btc_short,
        name="btc_retest_short_event_lb14_atr050_adx18_s078",
        note="BTC stage192：只留一条 moderate jump-reversal short。",
        family="short",
        patch={
            "strategy_params.breakout_lookback": 14,
            "strategy_params.breakout_atr_buffer": 0.50,
            "strategy_params.cooldown_bars": 1,
            "filters.adx_floor": 18,
            "money_management.stake_scale.btc_short": 0.70,
            "money_management.take_profit_pct": 0.96,
            "money_management.trailing_profit.activation_pnl_pct": 0.28,
            "money_management.trailing_profit.giveback_ratio": 0.16,
        },
        track="btc_jump_reversal_moderate",
        anchor_name=_name(btc_short),
        playbook="btc_jump_reversal_moderate",
    )

    add(
        eth_reclaim_pair,
        name="eth_reclaim_pair_long_lb10_atr040_adx15_cd1_s064",
        note="ETH stage192：reclaim pair 快一档，主攻。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 10,
            "strategy_params.breakout_atr_buffer": 0.40,
            "strategy_params.cooldown_bars": 1,
            "filters.adx_floor": 15,
            "money_management.stake_scale.eth_long": 0.60,
            "money_management.take_profit_pct": 1.14,
            "money_management.trailing_profit.activation_pnl_pct": 0.34,
            "money_management.trailing_profit.giveback_ratio": 0.18,
        },
        track="eth_reclaim_pair_fast_web",
        anchor_name=_name(eth_reclaim_pair),
        playbook="eth_reclaim_pair_fast_web",
    )
    add(
        eth_ladder,
        name="eth_reclaim_ladder_long_lb10_atr040_adx15_cd1_s068",
        note="ETH stage192：reclaim ladder 继续保留，只改成更快一档。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 10,
            "strategy_params.breakout_atr_buffer": 0.40,
            "strategy_params.cooldown_bars": 1,
            "filters.adx_floor": 15,
            "money_management.stake_scale.eth_long": 0.56,
            "money_management.take_profit_pct": 1.10,
            "money_management.trailing_profit.activation_pnl_pct": 0.32,
            "money_management.trailing_profit.giveback_ratio": 0.18,
        },
        track="eth_reclaim_ladder_web",
        anchor_name=_name(eth_ladder),
        playbook="eth_reclaim_ladder_web",
    )
    add(
        eth_squeeze,
        name="eth_squeeze_follow_long_lb8_atr036_adx13_s058",
        note="ETH stage192：squeeze 留一条补位，不再抢主锚。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 8,
            "strategy_params.breakout_atr_buffer": 0.36,
            "strategy_params.cooldown_bars": 1,
            "filters.adx_floor": 13,
            "money_management.stake_scale.eth_long": 0.54,
            "money_management.take_profit_pct": 1.10,
            "money_management.trailing_profit.activation_pnl_pct": 0.32,
            "money_management.trailing_profit.giveback_ratio": 0.18,
        },
        track="eth_squeeze_follow_fast_web",
        anchor_name=_name(eth_squeeze),
        playbook="eth_squeeze_follow_fast_web",
    )
    add(
        eth_short,
        name="eth_retest_short_trend_lb12_atr044_adx16_cd1_s076",
        note="ETH stage192：jump-reversal short 留一条更紧的确认腿。",
        family="short",
        patch={
            "strategy_params.breakout_lookback": 12,
            "strategy_params.breakout_atr_buffer": 0.44,
            "strategy_params.cooldown_bars": 1,
            "filters.adx_floor": 16,
            "money_management.stake_scale.eth_short": 0.70,
            "money_management.take_profit_pct": 0.92,
            "money_management.trailing_profit.activation_pnl_pct": 0.26,
            "money_management.trailing_profit.giveback_ratio": 0.16,
        },
        track="eth_jump_reversal_web",
        anchor_name=_name(eth_short),
        playbook="eth_jump_reversal_web",
    )

    add(
        sol_pullback,
        name="sol_pullback_pair_long_adx22_cd3_lb18_zone022_s052",
        note="SOL stage192：pullback pair 更快一档，继续当主锚。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 18,
            "strategy_params.breakout_atr_buffer": 0.50,
            "strategy_params.cooldown_bars": 3,
            "filters.adx_floor": 22,
            "money_management.stake_scale.sol_long": 0.50,
            "money_management.take_profit_pct": 1.12,
            "money_management.trailing_profit.activation_pnl_pct": 0.34,
            "money_management.trailing_profit.giveback_ratio": 0.18,
        },
        track="sol_pullback_pair_fast_web",
        anchor_name=_name(sol_pullback),
        playbook="sol_pullback_pair_fast_web",
    )
    add(
        sol_grid,
        name="sol_pullback_grid_long_adx24_cd3_lb18_zone022_s050",
        note="SOL stage192：grid 继续只在区间赛道，不外扩到趋势腿。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 18,
            "strategy_params.breakout_atr_buffer": 0.50,
            "strategy_params.cooldown_bars": 3,
            "filters.adx_floor": 24,
            "money_management.stake_scale.sol_long": 0.48,
            "money_management.take_profit_pct": 1.08,
            "money_management.trailing_profit.activation_pnl_pct": 0.32,
            "money_management.trailing_profit.giveback_ratio": 0.18,
        },
        track="sol_pullback_grid_fast_web",
        anchor_name=_name(sol_grid),
        playbook="sol_pullback_grid_fast_web",
    )
    add(
        sol_pullback,
        name="sol_range_ladder_long_adx20_cd2_lb16_zone020_s056",
        note="SOL stage192：range ladder 只留一条更快参考。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 16,
            "strategy_params.breakout_atr_buffer": 0.48,
            "strategy_params.cooldown_bars": 2,
            "filters.adx_floor": 20,
            "money_management.stake_scale.sol_long": 0.46,
            "money_management.take_profit_pct": 1.06,
            "money_management.trailing_profit.activation_pnl_pct": 0.30,
            "money_management.trailing_profit.giveback_ratio": 0.18,
        },
        track="sol_range_ladder_fast_web",
        anchor_name=_name(sol_pullback),
        playbook="sol_range_ladder_fast_web",
    )
    add(
        sol_short,
        name="sol_guarded_short_accel_lb12_atr050_adx16_cd1_s078",
        note="SOL stage192：guarded short 稍微提频，但不放开到趋势主腿。",
        family="short",
        patch={
            "strategy_params.breakout_lookback": 12,
            "strategy_params.breakout_atr_buffer": 0.50,
            "strategy_params.cooldown_bars": 1,
            "filters.adx_floor": 16,
            "money_management.stake_scale.sol_short": 0.64,
            "money_management.take_profit_pct": 0.94,
            "money_management.trailing_profit.activation_pnl_pct": 0.28,
            "money_management.trailing_profit.giveback_ratio": 0.16,
        },
        track="sol_guarded_short_fast_web",
        anchor_name=_name(sol_short),
        playbook="sol_guarded_short_fast_web",
    )
    return out


def _write_report(path_txt: Path, path_json: Path, main_rows: list[dict[str, Any]], branch_rows: list[dict[str, Any]], repaired_main: list[str], repaired_branch: list[str], scanned_main: list[str], scanned_branch: list[str], runtime_anchor: dict[str, Any], asset_summary: list[dict[str, Any]]) -> dict[str, Any]:
    main_payload = _top_payload(main_rows, runtime_anchor, branch=False)
    branch_payload = _top_payload(branch_rows, runtime_anchor, branch=True)
    active_map = _asset_active_map(asset_summary)
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
        "main_top": _select_top(main_payload, limit=6),
        "branch_by_symbol": {sym: _select_top(branch_payload, symbol=sym, limit=6) for sym in ["btc", "eth", "sol"]},
    }

    lines: list[str] = []
    lines.append("Stage192 reclaim-pair vol-target frontier")
    lines.append("")
    lines.append("[summary]")
    lines.append(f"- target_monthly_floor={TARGET_MONTHLY_MIN*100:.2f}% target_monthly_ceiling={TARGET_MONTHLY_MAX*100:.2f}%")
    lines.append(f"- repaired_main={len(repaired_main)} repaired_branch={len(repaired_branch)}")
    lines.append(f"- scanned_main={len(scanned_main)} scanned_branch={len(scanned_branch)}")
    lines.append(f"- stage91_active={json.dumps(active_map, ensure_ascii=False)}")
    lines.append(f"- split_recommendation={split_rec}")
    lines.append("")
    lines.append("[web_patterns]")
    lines.append("- vol-managed sizing: 高波动时降风险，先保留有效趋势")
    lines.append("- nonlinear trend blend: 不再只压单一超快动量，改成中速+快档混合")
    lines.append("- crypto faster reversal: 超过短窗口后更容易反转，所以 hold 不再拉长")
    lines.append("- grid still range-only: grid 继续只留 SOL 区间赛道")
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
    lines.append("- ETH 主攻改成 reclaim_pair + reclaim_ladder，squeeze 退到补位。")
    lines.append("- BTC 回到中速 squeeze / breakout，不再继续超快零交易线。")
    lines.append("- SOL 继续 pullback_pair 主攻，guarded short 只做辅助。")
    lines.append("- 主线继续只保 2 条 BNB reentry/pulse 候选；继续保持 1 个 branch 终端。")
    txt = "\n".join(lines).rstrip() + "\n"
    path_txt.write_text(txt, encoding="utf-8")
    path_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage192 reclaim-pair vol-target frontier")
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
        print(f"[stage192] main {item['name']}", flush=True)
        row = s136._run_mainline(root, cfg, data, item, initial_equity, full_start, full_end)
        row = s161._ensure_mainline_row(row, ref_row, initial_equity, full_end)
        main_map[str(row.get("name"))] = row
        scanned_main.append(str(row.get("name")))
    main_rows = s161._finalize_rows(list(main_map.values()), branch=False)

    branch_map = {str(r.get("name")): s161._ensure_branch_row(r, initial_equity) for r in branch_rows}
    scanned_branch: list[str] = []
    for item in _branch_items(branch_rows):
        print(f"[stage192] branch {item['name']}", flush=True)
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

    frontier_txt = raw / "stage192_reclaim_pair_voltarget_frontier_latest.txt"
    frontier_json = raw / "stage192_reclaim_pair_voltarget_frontier_latest.json"
    summary = _write_report(frontier_txt, frontier_json, main_rows, branch_rows, repaired_main, repaired_branch, scanned_main, scanned_branch, runtime_anchor, asset_summary)
    manifest = {
        "mode": "reclaim_pair_voltarget_frontier",
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
    manifest_path = raw / "stage192_reclaim_pair_voltarget_frontier_manifest_latest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    s141._mirror_to_workspace(root, [main_txt, main_json, branch_txt, branch_json, frontier_txt, frontier_json, manifest_path])

    out_zip = root.parent / "Downloads" / "stage192_reclaim_pair_voltarget_frontier_latest.zip"
    WRITE_SINGLE_ZIP(out_zip, {
        "stage192_reclaim_pair_voltarget_frontier_latest.txt": frontier_txt,
        "stage192_reclaim_pair_voltarget_frontier_latest.json": frontier_json,
        "stage192_reclaim_pair_voltarget_frontier_manifest_latest.json": manifest_path,
        "stage90_mainline_event_alpha_matrix_latest.txt": main_txt,
        "stage90_mainline_event_alpha_matrix_latest.json": main_json,
        "stage91_branch_event_alpha_matrix_latest.txt": branch_txt,
        "stage91_branch_event_alpha_matrix_latest.json": branch_json,
    })
    print(out_zip)


if __name__ == "__main__":
    main()
