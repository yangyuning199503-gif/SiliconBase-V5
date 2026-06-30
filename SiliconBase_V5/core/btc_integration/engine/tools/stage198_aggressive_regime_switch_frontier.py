from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import stage88_strategy_fusion_walkforward as s88
from tools import stage90_event_alpha_matrix as s90
from tools import stage136_regime_plateau_frontier as s136
from tools import stage141_guarded_asymmetry_shortlist as s141
from tools import stage161_mainline_risk_budget_multiasset_link_frontier as s161
from tools import stage186_truth_anchor_target_lift_frontier as s186
from tools import stage194_voltarget_hybrid_frontier as s194

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
    return s194._name(o)


def _merge_item_map(base_items: list[dict[str, Any]], existing_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return s194._merge_item_map(base_items, existing_rows)


def _load_asset_summary(path: Path) -> list[dict[str, Any]]:
    return s194._load_asset_summary(path)


def _asset_active_map(asset_summary: list[dict[str, Any]]) -> dict[str, str]:
    return s194._asset_active_map(asset_summary)


def _pick_mainline_ref(main_rows: list[dict[str, Any]], preferred_names: list[str]) -> dict[str, Any]:
    for target in preferred_names:
        for row in main_rows:
            if str(row.get("name") or "") == target:
                return copy.deepcopy(row)
    if main_rows:
        return copy.deepcopy(main_rows[0])
    return {"name": preferred_names[0] if preferred_names else "mainline_live_dynlev_fix8_lock18"}


def _coerce_full_end(ref_row: dict[str, Any]) -> Any:
    full = ref_row.get("full_metrics") if isinstance(ref_row.get("full_metrics"), dict) else {}
    return full.get("window_end") or ref_row.get("full_end")


def _score(row: dict[str, Any], runtime_anchor: dict[str, Any], active_map: dict[str, str], *, branch: bool) -> float:
    score = s194._score(row, runtime_anchor, active_map, branch=branch)
    recent, wf, _ = s186._runtime_adjusted_metrics(row, runtime_anchor, branch=branch)
    sym = SYMBOL(row, branch=branch).upper()
    pb = PLAYBOOK(row)
    name = str(row.get("name") or "").lower()
    best_m = max(SAFE_FLOAT(recent.get("monthlyized_ret")), SAFE_FLOAT(wf.get("monthlyized_ret")))
    r_pf = SAFE_FLOAT(recent.get("pf"))
    w_pf = SAFE_FLOAT(wf.get("pf"))
    r_t = SAFE_INT(recent.get("trades"))
    w_t = SAFE_INT(wf.get("trades"))
    r_dd = abs(SAFE_FLOAT(recent.get("maxdd")))
    w_dd = abs(SAFE_FLOAT(wf.get("maxdd")))

    if not branch:
        if pb == "base":
            score += 260.0
        else:
            score -= 900.0
        return score

    if sym == "BTC":
        if "break_fail" in name:
            return score - 99999.0
        if pb == "btc_breakout_gate":
            score += 90.0
        elif pb == "btc_squeeze_gate":
            score += 80.0
        elif pb == "base":
            score += 25.0
        else:
            score -= 180.0
        if r_t < 8 or w_t < 6:
            score -= 350.0
        if best_m >= 0.0040:
            score += 40.0
        elif best_m < 0.0025:
            score -= 80.0
        if w_pf >= 1.40:
            score += 30.0
        return score

    if sym == "ETH":
        if pb == "eth_ultrafast_reclaim":
            score += 380.0
        elif pb == "eth_drift_relay":
            score += 350.0
        elif pb == "eth_squeeze_relay":
            score += 330.0
        elif pb == "eth_reclaim_drift_blend":
            score += 345.0
        elif pb == "eth_jump_reversal_short":
            score += 190.0
        else:
            score -= 120.0
        if r_t >= 30 and w_t >= 22:
            score += 120.0
        elif r_t >= 24 and w_t >= 18:
            score += 70.0
        if r_pf >= 2.50 and w_pf >= 2.40:
            score += 130.0
        elif r_pf >= 2.10 and w_pf >= 2.00:
            score += 70.0
        if best_m >= 0.0160:
            score += 170.0
        elif best_m >= 0.0140:
            score += 120.0
        elif best_m >= 0.0120:
            score += 80.0
        elif best_m >= 0.0100:
            score += 45.0
        if r_dd <= 0.040 and w_dd <= 0.040:
            score += 90.0
        if pb == "eth_jump_reversal_short":
            if best_m < 0.0060:
                score -= 120.0
            if max(r_pf, w_pf) < 1.30:
                score -= 80.0
        return score

    if sym == "SOL":
        if pb == "sol_jump_reversal_short":
            score += 300.0
        elif pb == "sol_short_balance":
            score += 280.0
        elif pb == "sol_pullback_core":
            score += 220.0
        elif pb == "sol_range_only":
            score += 180.0
        elif pb == "sol_grid_range":
            score += 110.0
        else:
            score -= 80.0
        if pb in {"sol_jump_reversal_short", "sol_short_balance"}:
            if SAFE_FLOAT(wf.get("monthlyized_ret")) >= 0.0020:
                score += 110.0
            elif SAFE_FLOAT(wf.get("monthlyized_ret")) >= 0.0010:
                score += 45.0
            if w_pf >= 1.05:
                score += 70.0
            if w_t >= 20:
                score += 35.0
            if r_dd <= 0.090 and w_dd <= 0.090:
                score += 30.0
        elif pb in {"sol_pullback_core", "sol_range_only", "sol_grid_range"}:
            if r_pf >= 1.40 and w_pf >= 1.20:
                score += 65.0
            if r_dd <= 0.040 and w_dd <= 0.040:
                score += 70.0
            if best_m < 0.0010:
                score -= 30.0
        return score

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

    btc_breakout = item_map.get("btc_breakout_long_event_lb20_atr060_adx24_s050") or item_map.get("btc_squeeze_follow_long_lb16_atr050_adx20_s058")
    btc_squeeze = item_map.get("btc_squeeze_follow_long_lb16_atr050_adx20_s058") or btc_breakout

    eth_reclaim = item_map.get("eth_reclaim_pair_long_lb10_atr040_adx15_cd1_s064") or item_map.get("eth_reclaim_pair_long_lb9_atr038_adx14_cd1_s068") or item_map.get("eth_reclaim_long_lb12_atr043_adx16_s060")
    eth_drift = item_map.get("eth_event_drift_long_lb9_atr042_adx15_s050") or item_map.get("eth_event_drift_long_lb10_atr044_adx16_s046") or eth_reclaim
    eth_squeeze = item_map.get("eth_squeeze_follow_long_lb9_atr040_adx15_s048") or item_map.get("eth_squeeze_follow_long_lb8_atr036_adx13_s058") or eth_reclaim
    eth_short = item_map.get("eth_retest_short_trend_lb20_atr060_adx24_cd3_s068") or item_map.get("eth_retest_short_trend_lb20_atr060_adx24_s068")

    sol_pullback = item_map.get("sol_pullback_pair_long_adx24_cd4_lb20_zone024_s046") or item_map.get("sol_pullback_grid_long_adx26_cd4_lb22_zone026_s046")
    sol_range = item_map.get("sol_range_ladder_long_adx22_cd2_lb18_zone022_s052") or sol_pullback
    sol_short = item_map.get("sol_guarded_short_accel_lb14_atr052_adx18_cd1_s076") or item_map.get("sol_guarded_short_accel_lb10_atr048_adx15_cd1_s080")

    add(
        btc_breakout,
        name="btc_breakout_long_event_lb18_atr056_adx22_s054",
        note="BTC stage198：只留一条更快 breakout gate，当跨币确认腿，不抢主利润。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 18,
            "strategy_params.breakout_atr_buffer": 0.56,
            "filters.adx_floor": 22,
            "money_management.stake_scale.btc_long": 0.54,
            "money_management.take_profit_pct": 1.06,
            "money_management.trailing_profit.activation_pnl_pct": 0.28,
            "money_management.trailing_profit.giveback_ratio": 0.17,
        },
        track="btc_breakout_gate",
        anchor_name=_name(btc_breakout),
        playbook="btc_breakout_gate",
    )
    add(
        btc_squeeze,
        name="btc_squeeze_follow_long_lb14_atr046_adx18_s062",
        note="BTC stage198：只留一条 squeeze gate，给 ETH/SOL 做同步确认。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 14,
            "strategy_params.breakout_atr_buffer": 0.46,
            "filters.adx_floor": 18,
            "money_management.stake_scale.btc_long": 0.58,
            "money_management.take_profit_pct": 1.08,
            "money_management.trailing_profit.activation_pnl_pct": 0.28,
            "money_management.trailing_profit.giveback_ratio": 0.17,
        },
        track="btc_squeeze_gate",
        anchor_name=_name(btc_squeeze),
        playbook="btc_squeeze_gate",
    )

    add(
        eth_reclaim,
        name="eth_reclaim_pair_long_lb8_atr036_adx13_cd1_s072",
        note="ETH stage198：ultrafast reclaim，直接压更快的二段回收。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 8,
            "strategy_params.breakout_atr_buffer": 0.36,
            "strategy_params.cooldown_bars": 1,
            "filters.adx_floor": 13,
            "money_management.stake_scale.eth_long": 0.72,
            "money_management.take_profit_pct": 1.20,
            "money_management.trailing_profit.activation_pnl_pct": 0.30,
            "money_management.trailing_profit.giveback_ratio": 0.16,
        },
        track="eth_ultrafast_reclaim",
        anchor_name=_name(eth_reclaim),
        playbook="eth_ultrafast_reclaim",
    )
    add(
        eth_drift,
        name="eth_event_drift_long_lb8_atr038_adx13_s056",
        note="ETH stage198：drift relay，把事件漂移真正提速。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 8,
            "strategy_params.breakout_atr_buffer": 0.38,
            "strategy_params.cooldown_bars": 1,
            "filters.adx_floor": 13,
            "money_management.stake_scale.eth_long": 0.70,
            "money_management.take_profit_pct": 1.18,
            "money_management.trailing_profit.activation_pnl_pct": 0.29,
            "money_management.trailing_profit.giveback_ratio": 0.16,
        },
        track="eth_drift_relay",
        anchor_name=_name(eth_drift),
        playbook="eth_drift_relay",
    )
    add(
        eth_squeeze,
        name="eth_squeeze_follow_long_lb7_atr034_adx12_s062",
        note="ETH stage198：squeeze relay，专门抓挤仓二段。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 7,
            "strategy_params.breakout_atr_buffer": 0.34,
            "strategy_params.cooldown_bars": 1,
            "filters.adx_floor": 12,
            "money_management.stake_scale.eth_long": 0.68,
            "money_management.take_profit_pct": 1.14,
            "money_management.trailing_profit.activation_pnl_pct": 0.28,
            "money_management.trailing_profit.giveback_ratio": 0.16,
        },
        track="eth_squeeze_relay",
        anchor_name=_name(eth_squeeze),
        playbook="eth_squeeze_relay",
    )
    add(
        eth_reclaim,
        name="eth_reclaim_drift_blend_long_lb9_atr038_adx14_cd1_s068",
        note="ETH stage198：把 reclaim + drift 真正压成一条 blended long。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 9,
            "strategy_params.breakout_atr_buffer": 0.38,
            "strategy_params.cooldown_bars": 1,
            "filters.adx_floor": 14,
            "money_management.stake_scale.eth_long": 0.70,
            "money_management.take_profit_pct": 1.16,
            "money_management.trailing_profit.activation_pnl_pct": 0.29,
            "money_management.trailing_profit.giveback_ratio": 0.16,
        },
        track="eth_reclaim_drift_blend",
        anchor_name=_name(eth_reclaim),
        playbook="eth_reclaim_drift_blend",
    )
    add(
        eth_short,
        name="eth_retest_short_trend_lb8_atr038_adx13_cd1_s084",
        note="ETH stage198：jump-reversal short，只做冲高失败后的二次确认。",
        family="short",
        patch={
            "strategy_params.breakout_lookback": 8,
            "strategy_params.breakout_atr_buffer": 0.38,
            "strategy_params.cooldown_bars": 1,
            "filters.adx_floor": 13,
            "money_management.stake_scale.eth_short": 0.78,
            "money_management.take_profit_pct": 0.88,
            "money_management.trailing_profit.activation_pnl_pct": 0.24,
            "money_management.trailing_profit.giveback_ratio": 0.16,
        },
        track="eth_jump_reversal_short",
        anchor_name=_name(eth_short),
        playbook="eth_jump_reversal_short",
    )

    add(
        sol_pullback,
        name="sol_pullback_pair_long_adx20_cd2_lb18_zone022_s050",
        note="SOL stage198：pullback core，更快但仍守回撤。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 18,
            "strategy_params.breakout_atr_buffer": 0.50,
            "strategy_params.cooldown_bars": 2,
            "filters.adx_floor": 20,
            "money_management.stake_scale.sol_long": 0.54,
            "money_management.take_profit_pct": 1.06,
            "money_management.trailing_profit.activation_pnl_pct": 0.28,
            "money_management.trailing_profit.giveback_ratio": 0.17,
        },
        track="sol_pullback_core",
        anchor_name=_name(sol_pullback),
        playbook="sol_pullback_core",
    )
    add(
        sol_range,
        name="sol_range_ladder_long_adx18_cd1_lb16_zone020_s056",
        note="SOL stage198：range-only long，专门对应震荡区间。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 16,
            "strategy_params.breakout_atr_buffer": 0.52,
            "strategy_params.cooldown_bars": 1,
            "filters.adx_floor": 18,
            "money_management.stake_scale.sol_long": 0.50,
            "money_management.take_profit_pct": 1.04,
            "money_management.trailing_profit.activation_pnl_pct": 0.26,
            "money_management.trailing_profit.giveback_ratio": 0.17,
        },
        track="sol_range_only",
        anchor_name=_name(sol_range),
        playbook="sol_range_only",
    )
    add(
        sol_range,
        name="sol_grid_range_long_adx14_cd1_lb12_zone018_s062",
        note="SOL stage198：grid 只留在 range，不扩到 trend 腿。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 12,
            "strategy_params.breakout_atr_buffer": 0.54,
            "strategy_params.cooldown_bars": 1,
            "filters.adx_floor": 14,
            "money_management.stake_scale.sol_long": 0.46,
            "money_management.take_profit_pct": 1.00,
            "money_management.trailing_profit.activation_pnl_pct": 0.24,
            "money_management.trailing_profit.giveback_ratio": 0.17,
        },
        track="sol_grid_range",
        anchor_name=_name(sol_range),
        playbook="sol_grid_range",
    )
    add(
        sol_short,
        name="sol_guarded_short_accel_lb12_atr048_adx16_cd1_s080",
        note="SOL stage198：short balance，先吃二段失败。",
        family="short",
        patch={
            "strategy_params.breakout_lookback": 12,
            "strategy_params.breakout_atr_buffer": 0.48,
            "strategy_params.cooldown_bars": 1,
            "filters.adx_floor": 16,
            "money_management.stake_scale.sol_short": 0.70,
            "money_management.take_profit_pct": 0.86,
            "money_management.trailing_profit.activation_pnl_pct": 0.24,
            "money_management.trailing_profit.giveback_ratio": 0.15,
        },
        track="sol_short_balance",
        anchor_name=_name(sol_short),
        playbook="sol_short_balance",
    )
    add(
        sol_short,
        name="sol_guarded_short_accel_lb10_atr046_adx14_cd1_s084",
        note="SOL stage198：jump-reversal short，更快但仍保 guard。",
        family="short",
        patch={
            "strategy_params.breakout_lookback": 10,
            "strategy_params.breakout_atr_buffer": 0.46,
            "strategy_params.cooldown_bars": 1,
            "filters.adx_floor": 14,
            "money_management.stake_scale.sol_short": 0.72,
            "money_management.take_profit_pct": 0.84,
            "money_management.trailing_profit.activation_pnl_pct": 0.22,
            "money_management.trailing_profit.giveback_ratio": 0.15,
        },
        track="sol_jump_reversal_short",
        anchor_name=_name(sol_short),
        playbook="sol_jump_reversal_short",
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
        "main_top": _select_top(main_payload, limit=3),
        "branch_by_symbol": {sym: _select_top(branch_payload, symbol=sym, limit=5) for sym in ["btc", "eth", "sol"]},
    }

    lines: list[str] = []
    lines.append("Stage198 aggressive regime-switch frontier")
    lines.append("")
    lines.append("[summary]")
    lines.append(f"- target_monthly_floor={TARGET_MONTHLY_MIN*100:.2f}% target_monthly_ceiling={TARGET_MONTHLY_MAX*100:.2f}%")
    lines.append(f"- repaired_main={len(repaired_main)} repaired_branch={len(repaired_branch)}")
    lines.append(f"- scanned_main={len(scanned_main)} scanned_branch={len(scanned_branch)}")
    lines.append(f"- stage91_active={json.dumps(active_map, ensure_ascii=False)}")
    lines.append(f"- split_recommendation={split_rec}")
    lines.append("")
    lines.append("[focus]")
    lines.append("- 主线: 冻结 1 轮，不再钻 fix8 微邻域。")
    lines.append("- BTC: 只保 2 条 gate/confirm，给 ETH/SOL 做跨币确认。")
    lines.append("- ETH: reclaim + drift + squeeze 三核并行，再留 1 条 jump-reversal short。")
    lines.append("- SOL: long/short 对称，grid 只限 range。")
    lines.append("")
    lines.append("[main_top]")
    for row in summary["main_top"]:
        lines.append(
            f"- {row['name']} | playbook={row['playbook']} | status={row['status']} | 6年={row['full_ret']*100:.2f}% | 近2年月化={row['recent_monthly']*100:.2f}% | WF月化={row['wf_monthly']*100:.2f}% | gap_to_7.6={row['gap_to_floor']*100:.2f}%"
        )
    lines.append("")
    for sym in ["eth", "sol", "btc"]:
        lines.append(f"[{sym}_top]")
        for row in summary["branch_by_symbol"][sym]:
            lines.append(
                f"- {row['name']} | playbook={row['playbook']} | status={row['status']} | 近2年={row['recent_ret']*100:.2f}% | 近2年月化={row['recent_monthly']*100:.2f}% | WF={row['wf_ret']*100:.2f}% | WF月化={row['wf_monthly']*100:.2f}% | 近2年交易={row['recent_trades']} | WF交易={row['wf_trades']} | gap_to_7.6={row['gap_to_floor']*100:.2f}%"
            )
        lines.append("")
    lines.append("[conclusion]")
    lines.append("- 主线继续保持当前 anchor，不再浪费算力刷弱线。")
    lines.append("- ETH 这轮从单一 reclaim，改成 reclaim/drift/squeeze 并行竞争。")
    lines.append("- SOL 这轮把 short 真正提级，grid 只留在 range。")
    lines.append("- 继续 1 个 branch 终端。")
    txt = "\n".join(lines).rstrip() + "\n"
    path_txt.write_text(txt, encoding="utf-8")
    path_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def _run_branch_resilient(root: Path, cfg: dict[str, Any], item: dict[str, Any], initial_equity: float):
    try:
        return s136._run_branch(root, cfg, item, initial_equity), None
    except ValueError as e:
        msg = str(e)
        if "共同区间数据不足" not in msg:
            raise

    cfg2 = copy.deepcopy(cfg)
    data_cfg = cfg2.setdefault("data", {})
    old_start = data_cfg.pop("start", None)
    old_end = data_cfg.pop("end", None)
    try:
        row = s136._run_branch(root, cfg2, item, initial_equity)
        retry_note = f"retry_without_window start={old_start!r} end={old_end!r}"
        return row, retry_note
    except ValueError as e2:
        msg2 = str(e2)
        if "共同区间数据不足" not in msg2:
            raise
        return None, msg2


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage198 aggressive regime-switch frontier")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    raw = root / "reports" / "research_raw"
    raw.mkdir(parents=True, exist_ok=True)

    main_rows, branch_rows, repaired_main, repaired_branch = s141._load_stage_state(raw)
    cfg = s186._load_live_cfg(root)
    initial_equity = float(cfg.get("portfolio", {}).get("initial_equity", 100000.0))
    runtime_anchor = s186._parse_runtime_anchor(root)

    item_map = _merge_item_map(s88._mainline_items(), main_rows)
    ref_item = item_map.get("mainline_live_dynlev_fix8_lock18") or item_map.get("mainline_live_base")
    if ref_item is None:
        raise SystemExit("missing mainline reference")

    preferred_names = [str(ref_item.get("name") or ""), "mainline_live_dynlev_fix8_lock18", "mainline_live_base"]
    ref_row = _pick_mainline_ref(main_rows, preferred_names)
    full_end = _coerce_full_end(ref_row)
    ref_row = s161._ensure_mainline_row(ref_row, ref_row, initial_equity, full_end)
    print(f"[stage198] reuse mainline anchor: {ref_row.get('name')}", flush=True)

    main_map = {str(r.get("name")): s161._ensure_mainline_row(r, ref_row, initial_equity, full_end) for r in main_rows}
    main_rows = s161._finalize_rows(list(main_map.values()), branch=False)
    scanned_main: list[str] = []

    branch_map = {str(r.get("name")): s161._ensure_branch_row(r, initial_equity) for r in branch_rows}
    scanned_branch: list[str] = []
    skipped_branch: list[dict[str, str]] = []
    for item in _branch_items(branch_rows):
        print(f"[stage198] branch {item['name']}", flush=True)
        row, retry_note = _run_branch_resilient(root, cfg, item, initial_equity)
        if row is None:
            skipped_branch.append({"name": str(item.get("name") or ""), "reason": str(retry_note or "common_range_insufficient")})
            print(f"[stage198] skip {item['name']} :: {retry_note}", flush=True)
            continue
        if retry_note:
            print(f"[stage198] resume {item['name']} :: {retry_note}", flush=True)
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

    frontier_txt = raw / "stage198_aggressive_regime_switch_frontier_latest.txt"
    frontier_json = raw / "stage198_aggressive_regime_switch_frontier_latest.json"
    summary = _write_report(frontier_txt, frontier_json, main_rows, branch_rows, repaired_main, repaired_branch, scanned_main, scanned_branch, runtime_anchor, asset_summary)
    manifest = {
        "mode": "aggressive_regime_switch_frontier",
        "target_monthly_min": TARGET_MONTHLY_MIN,
        "target_monthly_max": TARGET_MONTHLY_MAX,
        "repaired_main": repaired_main,
        "repaired_branch": repaired_branch,
        "scanned_main": scanned_main,
        "scanned_branch": scanned_branch,
        "skipped_branch": skipped_branch,
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
    manifest_path = raw / "stage198_aggressive_regime_switch_frontier_manifest_latest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    s141._mirror_to_workspace(root, [main_txt, main_json, branch_txt, branch_json, frontier_txt, frontier_json, manifest_path])

    out_zip = root.parent / "Downloads" / "stage198_aggressive_regime_switch_frontier_latest.zip"
    WRITE_SINGLE_ZIP(out_zip, {
        "stage198_aggressive_regime_switch_frontier_latest.txt": frontier_txt,
        "stage198_aggressive_regime_switch_frontier_latest.json": frontier_json,
        "stage198_aggressive_regime_switch_frontier_manifest_latest.json": manifest_path,
        "stage90_mainline_event_alpha_matrix_latest.txt": main_txt,
        "stage90_mainline_event_alpha_matrix_latest.json": main_json,
        "stage91_branch_event_alpha_matrix_latest.txt": branch_txt,
        "stage91_branch_event_alpha_matrix_latest.json": branch_json,
    })
    print(out_zip)


if __name__ == "__main__":
    main()
