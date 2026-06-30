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
            score += 55.0
        if pb == "mainline_volmanaged_pulse_web":
            score += 180.0
        if pb == "mainline_split_pulse_web":
            score += 120.0
        if best_m < 0.004:
            score -= 220.0
        if r_pf < 1.20 or w_pf < 1.00:
            score -= 140.0
        if pb != "base" and (r_m <= 0.0 or w_m <= 0.0):
            score -= 320.0
        return score

    # Hard blacklist old dead zones.
    if sym == "btc" and ("break_fail" in name or ("pair" in name and "event_pair" in name)):
        return score - 99999.0

    # ETH: short-horizon momentum + jump-reversal short get priority.
    if sym == "eth":
        if pb == "eth_intraday_momo_web":
            score += 420.0
        if pb == "eth_intraday_squeeze_web":
            score += 400.0
        if pb == "eth_jump_reversal_web":
            score += 210.0
        if pb == "eth_reclaim_beta_web":
            score += 80.0
        if pb in {"eth_intraday_momo_web", "eth_intraday_squeeze_web"}:
            if r_t >= 34 and w_t >= 24:
                score += 140.0
            if r_pf >= 2.00 and w_pf >= 1.80:
                score += 120.0
            if r_dd <= 0.060 and w_dd <= 0.060:
                score += 70.0
            if best_m >= 0.012:
                score += 80.0
            if min(r_t, w_t) < 18:
                score -= 200.0
        if pb == "eth_jump_reversal_web":
            if r_t >= 18 and w_t >= 14 and r_pf >= 1.30 and w_pf >= 1.25:
                score += 70.0
            if best_m < 0.004:
                score -= 80.0
        if pb == "eth_reclaim_beta_web" and best_m < 0.008:
            score -= 100.0

    # BTC: small compute on faster breakout + jump reversal.
    if sym == "btc":
        if pb == "btc_intraday_breakout_web":
            score += 260.0
        if pb == "btc_jump_reversal_web":
            score += 180.0
        if pb == "btc_volmanaged_trend_web":
            score += 150.0
        if pb in {"btc_intraday_breakout_web", "btc_volmanaged_trend_web"}:
            if r_t >= 16 and w_t >= 12:
                score += 70.0
            if r_pf >= 1.45 and w_pf >= 1.35:
                score += 60.0
            if r_dd <= 0.055 and w_dd <= 0.055:
                score += 40.0
            if best_m >= 0.004:
                score += 30.0
        if pb == "btc_jump_reversal_web" and r_t >= 14 and w_t >= 12:
            score += 45.0
        if r_t < 6 or w_t < 6:
            score -= 900.0

    # SOL: short-cycle pullback + range grid + one reversal short.
    if sym == "sol":
        if pb == "sol_shortcycle_pullback_web":
            score += 240.0
        if pb == "sol_range_grid_web":
            score += 210.0
        if pb == "sol_jump_reversal_web":
            score += 130.0
        if pb in {"sol_shortcycle_pullback_web", "sol_range_grid_web"}:
            if r_t >= 24 and w_t >= 18:
                score += 70.0
            if r_pf >= 1.15 and w_pf >= 1.10:
                score += 60.0
            if r_dd <= 0.060 and w_dd <= 0.060:
                score += 60.0
            if best_m >= 0.0025:
                score += 20.0
        if pb == "sol_jump_reversal_web" and w_t < 12:
            score -= 90.0

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


def _mainline_items() -> list[dict[str, Any]]:
    item_map = {str(item.get("name")): item for item in s88._mainline_items()}
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
        name="mainline_live_dynlev_fix8_lock18_volmanaged_pulse_lb20_buf042_cd4_bnb116_btc580",
        note="主线 stage191：vol-managed pulse，只保一条更激进但仍有风控的提频线。",
        patch={
            "strategy_params.breakout_lookback": 20,
            "strategy_params.breakout_atr_buffer": 0.42,
            "strategy_params.cooldown_bars": 4,
            "filters.adx_floor": 20,
            "execution_guard.pause_bars": 4,
            "money_management.stake_scale.bnb_long": 1.16,
            "money_management.stake_scale.btc_short": 5.80,
            "money_management.take_profit_pct": 1.12,
            "money_management.trailing_profit.activation_pnl_pct": 0.38,
            "money_management.trailing_profit.giveback_ratio": 0.20,
            "money_management.trailing_profit.min_lock_pnl_pct": 0.06,
        },
        track="mainline_volmanaged_pulse_web",
        playbook="mainline_volmanaged_pulse_web",
    )
    add(
        "mainline_split_adx26_cd6_lb24_zone028",
        name="mainline_split_adx20_cd3_lb16_zone020_pulse_bnb120_btc600",
        note="主线 stage191：split pulse 只留一条备用。",
        patch={
            "strategy_params.breakout_lookback": 16,
            "strategy_params.breakout_atr_buffer": 0.40,
            "strategy_params.cooldown_bars": 3,
            "filters.adx_floor": 20,
            "execution_guard.pause_bars": 4,
            "money_management.stake_scale.bnb_long": 1.20,
            "money_management.stake_scale.btc_short": 6.00,
            "money_management.take_profit_pct": 1.10,
            "money_management.trailing_profit.activation_pnl_pct": 0.36,
            "money_management.trailing_profit.giveback_ratio": 0.18,
            "money_management.trailing_profit.min_lock_pnl_pct": 0.06,
        },
        track="mainline_split_pulse_web",
        playbook="mainline_split_pulse_web",
    )
    return out


def _branch_items() -> list[dict[str, Any]]:
    item_map = {str(item.get("name")): item for item in s88._branch_items()}
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

    btc_long = item_map.get("btc_breakout_long_event_lb20_atr060_adx24_s050")
    btc_short = item_map.get("btc_retest_short_event_lb20_atr060_adx24_s072") or item_map.get("btc_retest_short_trend_lb20_atr060_adx24_s072")
    eth_anchor = (
        item_map.get("eth_breakout_long_event_lb16_atr050_adx22_s034")
        or item_map.get("eth_breakout_long_follow_lb16_atr050_adx22_s034")
        or item_map.get("eth_pullback_long_core_adx22_cd5_lb20_zone024_s040")
    )
    eth_short = item_map.get("eth_retest_short_trend_lb20_atr060_adx24_s068") or item_map.get("eth_retest_short_trend_lb16_atr050_adx20_s076")
    sol_anchor = item_map.get("sol_pullback_long_core_adx26_cd6_lb22_zone026_s040") or item_map.get("sol_pullback_long_core_adx22_cd5_lb18_zone024_s046")
    sol_short = item_map.get("sol_retest_short_trend_lb16_atr050_adx20_s068") or item_map.get("sol_short_shock_fast_lb18_adx24_s066")

    add(
        btc_long,
        name="btc_breakout_long_event_lb14_atr048_adx18_s062",
        note="BTC stage191：更快的 intraday breakout。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 14,
            "strategy_params.breakout_atr_buffer": 0.48,
            "strategy_params.cooldown_bars": 1,
            "filters.adx_floor": 18,
            "money_management.stake_scale.btc_long": 0.62,
            "money_management.take_profit_pct": 1.12,
            "money_management.trailing_profit.activation_pnl_pct": 0.34,
            "money_management.trailing_profit.giveback_ratio": 0.18,
        },
        track="btc_intraday_breakout_web",
        anchor_name="btc_breakout_long_event_lb20_atr060_adx24_s050",
        playbook="btc_intraday_breakout_web",
    )
    add(
        btc_long,
        name="btc_squeeze_follow_long_lb10_atr040_adx16_s070",
        note="BTC stage191：vol-managed squeeze trend 备用。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 10,
            "strategy_params.breakout_atr_buffer": 0.40,
            "strategy_params.cooldown_bars": 1,
            "filters.adx_floor": 16,
            "money_management.stake_scale.btc_long": 0.58,
            "money_management.take_profit_pct": 1.08,
            "money_management.trailing_profit.activation_pnl_pct": 0.32,
            "money_management.trailing_profit.giveback_ratio": 0.18,
        },
        track="btc_volmanaged_trend_web",
        anchor_name="btc_breakout_long_event_lb20_atr060_adx24_s050",
        playbook="btc_volmanaged_trend_web",
    )
    add(
        btc_short,
        name="btc_retest_short_event_lb10_atr044_adx16_s082",
        note="BTC stage191：jump-reversal short 保留一条。",
        family="short",
        patch={
            "strategy_params.breakout_lookback": 10,
            "strategy_params.breakout_atr_buffer": 0.44,
            "strategy_params.cooldown_bars": 1,
            "filters.adx_floor": 16,
            "money_management.stake_scale.btc_short": 0.68,
            "money_management.take_profit_pct": 0.98,
            "money_management.trailing_profit.activation_pnl_pct": 0.30,
            "money_management.trailing_profit.giveback_ratio": 0.16,
        },
        track="btc_jump_reversal_web",
        anchor_name=str(btc_short.get("name")) if btc_short else "",
        playbook="btc_jump_reversal_web",
    )

    add(
        eth_anchor,
        name="eth_event_drift_long_lb7_atr034_adx12_s062",
        note="ETH stage191：short-horizon intraday momentum 主攻。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 7,
            "strategy_params.breakout_atr_buffer": 0.34,
            "strategy_params.cooldown_bars": 1,
            "filters.adx_floor": 12,
            "money_management.stake_scale.eth_long": 0.60,
            "money_management.take_profit_pct": 1.16,
            "money_management.trailing_profit.activation_pnl_pct": 0.36,
            "money_management.trailing_profit.giveback_ratio": 0.20,
        },
        track="eth_intraday_momo_web",
        anchor_name=str(eth_anchor.get("name")) if eth_anchor else "",
        playbook="eth_intraday_momo_web",
    )
    add(
        eth_anchor,
        name="eth_squeeze_follow_long_lb6_atr032_adx11_s066",
        note="ETH stage191：更快的 squeeze follow 主攻。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 6,
            "strategy_params.breakout_atr_buffer": 0.32,
            "strategy_params.cooldown_bars": 1,
            "filters.adx_floor": 11,
            "money_management.stake_scale.eth_long": 0.58,
            "money_management.take_profit_pct": 1.12,
            "money_management.trailing_profit.activation_pnl_pct": 0.34,
            "money_management.trailing_profit.giveback_ratio": 0.18,
        },
        track="eth_intraday_squeeze_web",
        anchor_name=str(eth_anchor.get("name")) if eth_anchor else "",
        playbook="eth_intraday_squeeze_web",
    )
    add(
        eth_anchor,
        name="eth_reclaim_beta_long_lb7_atr034_adx12_cd1_s076",
        note="ETH stage191：reclaim beta 只保一条备用。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 7,
            "strategy_params.breakout_atr_buffer": 0.34,
            "strategy_params.cooldown_bars": 1,
            "filters.adx_floor": 12,
            "money_management.stake_scale.eth_long": 0.50,
            "money_management.take_profit_pct": 1.06,
            "money_management.trailing_profit.activation_pnl_pct": 0.30,
            "money_management.trailing_profit.giveback_ratio": 0.16,
        },
        track="eth_reclaim_beta_web",
        anchor_name=str(eth_anchor.get("name")) if eth_anchor else "",
        playbook="eth_reclaim_beta_web",
    )
    add(
        eth_short,
        name="eth_retest_short_trend_lb10_atr040_adx14_s082",
        note="ETH stage191：jump-reversal short 一条。",
        family="short",
        patch={
            "strategy_params.breakout_lookback": 10,
            "strategy_params.breakout_atr_buffer": 0.40,
            "strategy_params.cooldown_bars": 1,
            "filters.adx_floor": 14,
            "money_management.stake_scale.eth_short": 0.72,
            "money_management.take_profit_pct": 0.94,
            "money_management.trailing_profit.activation_pnl_pct": 0.28,
            "money_management.trailing_profit.giveback_ratio": 0.16,
        },
        track="eth_jump_reversal_web",
        anchor_name=str(eth_short.get("name")) if eth_short else "",
        playbook="eth_jump_reversal_web",
    )

    add(
        sol_anchor,
        name="sol_pullback_pair_long_adx18_cd2_lb16_zone020_s054",
        note="SOL stage191：short-cycle pullback 主攻。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 16,
            "strategy_params.breakout_atr_buffer": 0.50,
            "strategy_params.cooldown_bars": 2,
            "filters.adx_floor": 18,
            "money_management.stake_scale.sol_long": 0.52,
            "money_management.take_profit_pct": 1.16,
            "money_management.trailing_profit.activation_pnl_pct": 0.36,
            "money_management.trailing_profit.giveback_ratio": 0.20,
        },
        track="sol_shortcycle_pullback_web",
        anchor_name=str(sol_anchor.get("name")) if sol_anchor else "",
        playbook="sol_shortcycle_pullback_web",
    )
    add(
        sol_anchor,
        name="sol_grid_range_long_adx14_cd1_lb12_zone018_s062",
        note="SOL stage191：只在 range 赛道试更快 grid。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 12,
            "strategy_params.breakout_atr_buffer": 0.52,
            "strategy_params.cooldown_bars": 1,
            "filters.adx_floor": 14,
            "money_management.stake_scale.sol_long": 0.48,
            "money_management.take_profit_pct": 1.08,
            "money_management.trailing_profit.activation_pnl_pct": 0.32,
            "money_management.trailing_profit.giveback_ratio": 0.18,
        },
        track="sol_range_grid_web",
        anchor_name=str(sol_anchor.get("name")) if sol_anchor else "",
        playbook="sol_range_grid_web",
    )
    add(
        sol_short,
        name="sol_guarded_short_accel_lb8_atr044_adx12_cd1_s084",
        note="SOL stage191：jump-reversal guarded short。",
        family="short",
        patch={
            "strategy_params.breakout_lookback": 8,
            "strategy_params.breakout_atr_buffer": 0.44,
            "strategy_params.cooldown_bars": 1,
            "filters.adx_floor": 12,
            "money_management.stake_scale.sol_short": 0.66,
            "money_management.take_profit_pct": 0.96,
            "money_management.trailing_profit.activation_pnl_pct": 0.28,
            "money_management.trailing_profit.giveback_ratio": 0.16,
        },
        track="sol_jump_reversal_web",
        anchor_name=str(sol_short.get("name")) if sol_short else "",
        playbook="sol_jump_reversal_web",
    )
    return out


def _write_report(path_txt: Path, path_json: Path, main_rows: list[dict[str, Any]], branch_rows: list[dict[str, Any]], repaired_main: list[str], repaired_branch: list[str], scanned_main: list[str], scanned_branch: list[str], runtime_anchor: dict[str, Any]) -> dict[str, Any]:
    main_payload = _top_payload(main_rows, runtime_anchor, branch=False)
    branch_payload = _top_payload(branch_rows, runtime_anchor, branch=True)
    active_map = s186._active_map_from_payload(branch_payload, runtime_anchor)
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
        "main_top": _select_top(main_payload, limit=6),
        "branch_by_symbol": {sym: _select_top(branch_payload, symbol=sym, limit=6) for sym in ["btc", "eth", "sol"]},
    }

    lines: list[str] = []
    lines.append("Stage191 cross-signal vol-managed frontier")
    lines.append("")
    lines.append("[summary]")
    lines.append(f"- target_monthly_floor={TARGET_MONTHLY_MIN*100:.2f}% target_monthly_ceiling={TARGET_MONTHLY_MAX*100:.2f}%")
    lines.append(f"- repaired_main={len(repaired_main)} repaired_branch={len(repaired_branch)}")
    lines.append(f"- scanned_main={len(scanned_main)} scanned_branch={len(scanned_branch)}")
    lines.append(f"- stage91_active={json.dumps(active_map, ensure_ascii=False)}")
    lines.append(f"- split_recommendation={split_rec}")
    lines.append("")
    lines.append("[web_patterns]")
    lines.append("- vol-managed trend: 高波动时降风险，低波动时放大有效趋势")
    lines.append("- short-horizon crypto momentum: 更短 lookback + 更快 cooldown")
    lines.append("- jump-reversal short: 大波动后反抽失败才给 short")
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

    lines.append("[conclusion]")
    lines.append("- ETH 先押 short-horizon drift + squeeze，reclaim 退到 beta 备用。")
    lines.append("- BTC 只保更快 breakout + 1条 jump-reversal short。")
    lines.append("- SOL 先押 short-cycle pullback，grid 继续只留 range。")
    lines.append("- 继续保持 1 个 branch 终端。")
    txt = "\n".join(lines).rstrip() + "\n"
    path_txt.write_text(txt, encoding="utf-8")
    path_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage191 cross-signal vol-managed frontier")
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

    item_map = {str(item.get("name")): item for item in s88._mainline_items()}
    ref_item = item_map.get("mainline_live_dynlev_fix8_lock18") or item_map.get("mainline_live_base")
    if ref_item is None:
        raise SystemExit("missing mainline reference")
    ref_row = s136._run_mainline(root, cfg, data, WITH_META(ref_item, track="base", branch=False, anchor_name=str(ref_item.get("name")), playbook="base"), initial_equity, full_start, full_end)

    main_map = {str(r.get("name")): s161._ensure_mainline_row(r, ref_row, initial_equity, full_end) for r in main_rows}
    scanned_main: list[str] = []
    for item in _mainline_items():
        print(f"[stage191] main {item['name']}", flush=True)
        row = s136._run_mainline(root, cfg, data, item, initial_equity, full_start, full_end)
        row = s161._ensure_mainline_row(row, ref_row, initial_equity, full_end)
        main_map[str(row.get("name"))] = row
        scanned_main.append(str(row.get("name")))
    main_rows = s161._finalize_rows(list(main_map.values()), branch=False)

    branch_map = {str(r.get("name")): s161._ensure_branch_row(r, initial_equity) for r in branch_rows}
    scanned_branch: list[str] = []
    for item in _branch_items():
        print(f"[stage191] branch {item['name']}", flush=True)
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

    frontier_txt = raw / "stage191_crosssignal_volmanaged_frontier_latest.txt"
    frontier_json = raw / "stage191_crosssignal_volmanaged_frontier_latest.json"
    summary = _write_report(frontier_txt, frontier_json, main_rows, branch_rows, repaired_main, repaired_branch, scanned_main, scanned_branch, runtime_anchor)
    manifest = {
        "mode": "crosssignal_volmanaged_frontier",
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
    manifest_path = raw / "stage191_crosssignal_volmanaged_frontier_manifest_latest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    s141._mirror_to_workspace(root, [main_txt, main_json, branch_txt, branch_json, frontier_txt, frontier_json, manifest_path])

    out_zip = root.parent / "Downloads" / "stage191_crosssignal_volmanaged_frontier_latest.zip"
    WRITE_SINGLE_ZIP(out_zip, {
        "stage191_crosssignal_volmanaged_frontier_latest.txt": frontier_txt,
        "stage191_crosssignal_volmanaged_frontier_latest.json": frontier_json,
        "stage191_crosssignal_volmanaged_frontier_manifest_latest.json": manifest_path,
        "stage90_mainline_event_alpha_matrix_latest.txt": main_txt,
        "stage90_mainline_event_alpha_matrix_latest.json": main_json,
        "stage91_branch_event_alpha_matrix_latest.txt": branch_txt,
        "stage91_branch_event_alpha_matrix_latest.json": branch_json,
    })
    print(out_zip)


if __name__ == "__main__":
    main()
