from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import research_config_baseline as rcb
from tools import stage46_aggressive_lab as s46
from tools import stage77_mainline_dual_window_lab as s77
from tools import stage88_strategy_fusion_walkforward as s88
from tools import stage90_event_alpha_matrix as s90
from tools import stage136_regime_plateau_frontier as s136
from tools import stage141_guarded_asymmetry_shortlist as s141
from tools import stage161_mainline_risk_budget_multiasset_link_frontier as s161

TARGET_MONTHLY_MIN = float(getattr(s136, "TARGET_MONTHLY_MIN", 0.076))
TARGET_MONTHLY_MAX = float(getattr(s136, "TARGET_MONTHLY_MAX", 0.114))


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except Exception:
        return default


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        if v is None or v == "":
            return default
        return int(v)
    except Exception:
        return default


def _with_meta(item: dict[str, Any], *, track: str, branch: bool, anchor_name: str | None = None, playbook: str = "base") -> dict[str, Any]:
    return s161._with_meta(item, track=track, branch=branch, anchor_name=anchor_name, playbook=playbook)


def _stage91_active_map(branch_json: Path) -> dict[str, str]:
    try:
        payload = json.loads(branch_json.read_text(encoding="utf-8"))
    except Exception:
        return {"BTC": "", "ETH": "", "SOL": ""}
    asset_summary = payload.get("asset_summary")
    out = {"BTC": "", "ETH": "", "SOL": ""}
    if isinstance(asset_summary, list):
        for row in asset_summary:
            if not isinstance(row, dict):
                continue
            sym = str(row.get("symbol", "")).upper()
            if sym in out:
                active = row.get("active")
                if isinstance(active, str):
                    out[sym] = active
    return out


def _meta(row: dict[str, Any]) -> dict[str, Any]:
    meta = row.get("meta")
    return meta if isinstance(meta, dict) else {}


def _playbook(row: dict[str, Any]) -> str:
    meta = _meta(row)
    pb = meta.get("playbook")
    if isinstance(pb, str) and pb:
        return pb
    name = str(row.get("name") or "").lower()
    for key in [
        "main_ladder_pyramid",
        "main_banded_reentry",
        "main_overlay_hold",
        "btc_breakout_long",
        "btc_event_drift",
        "btc_squeeze_follow",
        "btc_dual_hedge",
        "btc_retest_short",
        "eth_event_drift",
        "eth_squeeze_follow",
        "eth_reclaim_pair",
        "eth_reclaim_ladder",
        "eth_retest_short",
        "eth_shock_short",
        "sol_range_ladder",
        "sol_pullback_grid",
        "sol_pullback_pair",
        "sol_guarded_short",
    ]:
        if key in name:
            return key
    return "base"


def _family(row: dict[str, Any]) -> str:
    name = str(row.get("name") or "").lower()
    pb = _playbook(row)
    if pb != "base":
        return pb
    if name.startswith("mainline_live_dynlev_fix8_lock18"):
        return "main_fix8"
    toks = [t for t in name.split("_") if t]
    return "_".join(toks[:3]) if len(toks) >= 3 else name


def _symbol(row: dict[str, Any], *, branch: bool) -> str:
    if not branch:
        return "main"
    sym = row.get("symbol")
    if isinstance(sym, str) and sym:
        return sym.lower()
    name = str(row.get("name") or "").lower()
    if name.startswith("btc_"):
        return "btc"
    if name.startswith("eth_"):
        return "eth"
    if name.startswith("sol_"):
        return "sol"
    return "branch"


def _recent_metrics(row: dict[str, Any]) -> dict[str, Any]:
    dom = row.get("dominant_gate")
    if isinstance(dom, dict):
        recent = dom.get("recent_metrics")
        if isinstance(recent, dict):
            return recent
        metrics = dom.get("metrics")
        if isinstance(metrics, dict):
            ws = metrics.get("window_start")
            if isinstance(ws, str) and ws.startswith("2024-"):
                return metrics
    for gate_row in row.get("gate_rows") or []:
        if isinstance(gate_row, dict):
            recent = gate_row.get("recent_metrics")
            if isinstance(recent, dict):
                return recent
    return {}


def _wf_metrics(row: dict[str, Any]) -> dict[str, Any]:
    wf = row.get("walkforward")
    if isinstance(wf, dict):
        metrics = wf.get("metrics")
        if isinstance(metrics, dict):
            return metrics
    return {}


def _full_metrics(row: dict[str, Any]) -> dict[str, Any]:
    fm = row.get("full_metrics")
    return fm if isinstance(fm, dict) else {}


def _hard_blacklisted(name: str) -> bool:
    n = name.lower()
    if "btc_break_fail" in n:
        return True
    return bool("btc_retest_pair" in n and ("short" in n or "pair" in n))



def _aggressive_score(row: dict[str, Any], *, branch: bool) -> float:
    name = str(row.get("name") or "")
    recent = _recent_metrics(row)
    wf = _wf_metrics(row)
    full = _full_metrics(row)
    r_m = _safe_float(recent.get("monthlyized_ret"))
    w_m = _safe_float(wf.get("monthlyized_ret"))
    r_pf = _safe_float(recent.get("pf"))
    w_pf = _safe_float(wf.get("pf"))
    r_t = _safe_int(recent.get("trades"))
    w_t = _safe_int(wf.get("trades"))
    r_dd = abs(_safe_float(recent.get("maxdd")))
    w_dd = abs(_safe_float(wf.get("maxdd")))
    full_t = _safe_int(full.get("trades"))

    best_m = max(r_m, w_m)
    gap = max(TARGET_MONTHLY_MIN - best_m, 0.0)

    score = 92000.0 * r_m + 78000.0 * w_m
    score += 110.0 * min(r_pf, 8.0) + 95.0 * min(w_pf, 8.0)
    score += 7.0 * min(r_t, 90) + 5.0 * min(w_t, 70) + 1.0 * min(full_t, 400)
    score -= 130.0 * (r_dd * 100.0) + 105.0 * (w_dd * 100.0)
    score -= gap * 120000.0

    pb = _playbook(row)
    bonus = 0.0
    if pb in {"main_banded_reentry", "main_ladder_pyramid"}:
        bonus += 180.0
    if pb == "eth_event_drift":
        bonus += 260.0
    if pb == "eth_squeeze_follow":
        bonus += 200.0
    if pb == "eth_reclaim_ladder":
        bonus += 130.0
    if pb == "eth_retest_short":
        bonus += 80.0
    if pb in {"btc_breakout_long", "btc_event_drift"}:
        bonus += 120.0
    if pb == "btc_squeeze_follow":
        bonus += 90.0
    if pb == "btc_dual_hedge":
        bonus += 40.0
    if pb in {"sol_pullback_pair", "sol_range_ladder"}:
        bonus += 110.0
    if pb == "sol_pullback_grid":
        bonus += 85.0
    if pb == "sol_guarded_short":
        bonus -= 40.0
    score += bonus

    penalty = 0.0
    if best_m < 0.0025:
        penalty += 420.0
    if r_t < 5 or w_t < 5:
        penalty += 320.0
    if r_pf < 1.0 or w_pf < 1.0:
        penalty += 240.0
    if _hard_blacklisted(name):
        penalty += 99999.0
    if branch and _symbol(row, branch=True) == "sol" and "short" in name.lower():
        penalty += 80.0
    if branch and _symbol(row, branch=True) == "btc" and ("break_fail" in name.lower() or r_t <= 1 or w_t <= 1):
        penalty += 320.0
    return score - penalty



def _status(row: dict[str, Any], *, branch: bool) -> str:
    recent = _recent_metrics(row)
    wf = _wf_metrics(row)
    r_m = _safe_float(recent.get("monthlyized_ret"))
    w_m = _safe_float(wf.get("monthlyized_ret"))
    r_pf = _safe_float(recent.get("pf"))
    w_pf = _safe_float(wf.get("pf"))
    r_t = _safe_int(recent.get("trades"))
    w_t = _safe_int(wf.get("trades"))
    if _hard_blacklisted(str(row.get("name") or "")):
        return "blacklist"
    if r_m >= 0.03 and w_m >= 0.025 and r_pf >= 1.6 and w_pf >= 1.4 and r_t >= 12 and w_t >= 8:
        return "accel_track"
    if r_m >= 0.015 and w_m >= 0.010 and r_pf >= 1.30 and w_pf >= 1.15 and r_t >= 8 and w_t >= 6:
        return "reserve+"
    if r_m > 0 and w_m > 0:
        return "reserve"
    return "weak"


def _row_payload(row: dict[str, Any], *, branch: bool) -> dict[str, Any]:
    recent = _recent_metrics(row)
    wf = _wf_metrics(row)
    out = {
        "name": str(row.get("name") or ""),
        "symbol": _symbol(row, branch=branch),
        "family": _family(row),
        "playbook": _playbook(row),
        "alpha_score": _safe_float(row.get("alpha_score")),
        "aggressive_score": _aggressive_score(row, branch=branch),
        "status": _status(row, branch=branch),
        "recent_monthly": _safe_float(recent.get("monthlyized_ret")),
        "wf_monthly": _safe_float(wf.get("monthlyized_ret")),
        "recent_ret": _safe_float(recent.get("ret")),
        "wf_ret": _safe_float(wf.get("ret")),
        "recent_pf": _safe_float(recent.get("pf")),
        "wf_pf": _safe_float(wf.get("pf")),
        "recent_trades": _safe_int(recent.get("trades")),
        "wf_trades": _safe_int(wf.get("trades")),
        "recent_maxdd": _safe_float(recent.get("maxdd")),
        "wf_maxdd": _safe_float(wf.get("maxdd")),
        "gap_to_floor": TARGET_MONTHLY_MIN - max(_safe_float(recent.get("monthlyized_ret")), _safe_float(wf.get("monthlyized_ret"))),
        "hard_blacklisted": _hard_blacklisted(str(row.get("name") or "")),
    }
    return out


def _top_payload(rows: list[dict[str, Any]], *, branch: bool) -> list[dict[str, Any]]:
    payload = [_row_payload(r, branch=branch) for r in rows]
    payload.sort(key=lambda r: (r["aggressive_score"], r["alpha_score"]), reverse=True)
    return payload



def _mainline_items() -> list[dict[str, Any]]:
    item_map = {str(item.get("name")): item for item in s88._mainline_items()}
    base = item_map.get("mainline_live_dynlev_fix8_lock18")
    if base is None:
        raise SystemExit("missing mainline_live_dynlev_fix8_lock18 base item")
    out: list[dict[str, Any]] = []

    def add(name: str, note: str, patch: dict[str, Any], track: str, playbook: str) -> None:
        out.append(_with_meta(s88._make_mainline_variant(base, name=name, note=note, patch=patch), track=track, branch=False, anchor_name="mainline_live_dynlev_fix8_lock18", playbook=playbook))

    add(
        "mainline_live_dynlev_fix8_lock18_banded_reentry_lb22_buf044_cd6_add3_step16",
        "主线 stage185：围绕现有最好 banded re-entry，先提频再保守收口。",
        {
            "strategy_params.breakout_lookback": 22,
            "strategy_params.breakout_atr_buffer": 0.44,
            "strategy_params.cooldown_bars": 6,
            "filters.adx_floor": 23,
            "execution_guard.pause_bars": 4,
            "strategy_params.pyramiding_max_adds": 3,
            "strategy_params.add_step_atr": 1.6,
            "strategy_params.add_risk_fraction": 0.16,
            "strategy_params.breakeven_atr": 1.7,
            "money_management.stake_scale.bnb_long": 1.48,
            "money_management.stake_scale.btc_short": 6.00,
            "money_management.take_profit_pct": 1.18,
            "money_management.trailing_profit.activation_pnl_pct": 0.42,
            "money_management.trailing_profit.giveback_ratio": 0.23,
            "money_management.trailing_profit.min_lock_pnl_pct": 0.07,
        },
        "main_banded_reentry",
        "main_banded_reentry",
    )
    add(
        "mainline_live_dynlev_fix8_lock18_ladder_pyramid_lb24_buf046_cd8_add4_step18",
        "主线 stage185：围绕当前 ladder pyramiding 最优邻域，避免 overlay_hold 误判成第一。",
        {
            "strategy_params.breakout_lookback": 24,
            "strategy_params.breakout_atr_buffer": 0.46,
            "strategy_params.cooldown_bars": 8,
            "filters.adx_floor": 24,
            "execution_guard.pause_bars": 4,
            "strategy_params.pyramiding_max_adds": 4,
            "strategy_params.add_step_atr": 1.8,
            "strategy_params.add_risk_fraction": 0.17,
            "strategy_params.breakeven_atr": 1.8,
            "money_management.stake_scale.bnb_long": 1.52,
            "money_management.stake_scale.btc_short": 6.10,
            "money_management.take_profit_pct": 1.20,
            "money_management.trailing_profit.activation_pnl_pct": 0.44,
            "money_management.trailing_profit.giveback_ratio": 0.23,
            "money_management.trailing_profit.min_lock_pnl_pct": 0.08,
        },
        "main_ladder_pyramid",
        "main_ladder_pyramid",
    )
    add(
        "mainline_live_dynlev_fix8_lock18_banded_reentry_lb24_buf046_cd5_add4_step18",
        "主线 stage185：banded re-entry 稍激进版，验证 cd5 能否提频而不伤 WF。",
        {
            "strategy_params.breakout_lookback": 24,
            "strategy_params.breakout_atr_buffer": 0.46,
            "strategy_params.cooldown_bars": 5,
            "filters.adx_floor": 24,
            "execution_guard.pause_bars": 4,
            "strategy_params.pyramiding_max_adds": 4,
            "strategy_params.add_step_atr": 1.8,
            "strategy_params.add_risk_fraction": 0.17,
            "strategy_params.breakeven_atr": 1.8,
            "money_management.stake_scale.bnb_long": 1.54,
            "money_management.stake_scale.btc_short": 6.15,
            "money_management.take_profit_pct": 1.18,
            "money_management.trailing_profit.activation_pnl_pct": 0.42,
            "money_management.trailing_profit.giveback_ratio": 0.23,
            "money_management.trailing_profit.min_lock_pnl_pct": 0.07,
        },
        "main_banded_reentry",
        "main_banded_reentry",
    )
    add(
        "mainline_live_dynlev_fix8_lock18_ladder_pyramid_lb22_buf044_cd6_add5_step16",
        "主线 stage185：ladder 稠密版，只围绕已有正收益盆地扩圈。",
        {
            "strategy_params.breakout_lookback": 22,
            "strategy_params.breakout_atr_buffer": 0.44,
            "strategy_params.cooldown_bars": 6,
            "filters.adx_floor": 22,
            "execution_guard.pause_bars": 4,
            "strategy_params.pyramiding_max_adds": 5,
            "strategy_params.add_step_atr": 1.6,
            "strategy_params.add_risk_fraction": 0.17,
            "strategy_params.breakeven_atr": 1.7,
            "money_management.stake_scale.bnb_long": 1.56,
            "money_management.stake_scale.btc_short": 6.20,
            "money_management.take_profit_pct": 1.18,
            "money_management.trailing_profit.activation_pnl_pct": 0.42,
            "money_management.trailing_profit.giveback_ratio": 0.23,
            "money_management.trailing_profit.min_lock_pnl_pct": 0.07,
        },
        "main_ladder_pyramid",
        "main_ladder_pyramid",
    )
    return out



def _branch_items() -> list[dict[str, Any]]:
    item_map = {str(item.get("name")): item for item in s88._branch_items()}
    out: list[dict[str, Any]] = []

    def add(item: dict[str, Any] | None, *, name: str, note: str, family: str, patch: dict[str, Any], track: str, anchor_name: str, playbook: str) -> None:
        if item is None:
            return
        out.append(_with_meta(s88._make_variant(item, name=name, note=note, family=family, patch=patch), track=track, branch=True, anchor_name=anchor_name, playbook=playbook))

    btc_long = item_map.get("btc_breakout_long_event_lb20_atr060_adx24_s050")
    btc_short = item_map.get("btc_retest_short_event_lb20_atr060_adx24_s072")
    btc_dual = item_map.get("btc_dual_fast_trend_dynlev_fix8")
    eth_long = item_map.get("eth_breakout_long_event_lb16_atr050_adx22_s034") or item_map.get("eth_breakout_long_follow_lb16_atr050_adx22_s034")
    eth_short = item_map.get("eth_retest_short_trend_lb20_atr060_adx24_s068") or item_map.get("eth_retest_short_trend_lb18_atr055_adx22_s072")
    sol_long = item_map.get("sol_pullback_long_core_adx26_cd6_lb22_zone026_s040") or item_map.get("sol_pullback_long_core_adx24_cd6_lb20_zone025_s042")
    sol_long_alt = item_map.get("sol_long_core_soft_lb20_zone025_s042") or item_map.get("sol_shortwave_long_core_lb22_zone026_adx22_s040")
    sol_short = item_map.get("sol_fast_trend_short_guarded_lb16_atr055_adx22_s072") or item_map.get("sol_fast_trend_short_guarded_lb18_atr060_adx24_s068")

    add(
        btc_long,
        name="btc_breakout_long_event_lb18_atr056_adx22_s054",
        note="BTC stage185：保留 breakout 主腿，优先看 2 年/WF 都为正的候选。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 18,
            "strategy_params.breakout_atr_buffer": 0.56,
            "strategy_params.cooldown_bars": 2,
            "filters.adx_floor": 22,
            "money_management.stake_scale.btc_long": 0.58,
            "money_management.take_profit_pct": 1.20,
            "money_management.trailing_profit.activation_pnl_pct": 0.42,
            "money_management.trailing_profit.giveback_ratio": 0.23,
        },
        track="btc_breakout_long",
        anchor_name="btc_breakout_long_event_lb20_atr060_adx24_s050",
        playbook="btc_breakout_long",
    )
    add(
        btc_long,
        name="btc_event_drift_long_lb16_atr050_adx20_s058",
        note="BTC stage185：事件后 drift 只作为第二主腿，不再让假优先 short 抢位。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 16,
            "strategy_params.breakout_atr_buffer": 0.50,
            "strategy_params.cooldown_bars": 2,
            "filters.adx_floor": 20,
            "money_management.stake_scale.btc_long": 0.56,
            "money_management.take_profit_pct": 1.18,
            "money_management.trailing_profit.activation_pnl_pct": 0.40,
            "money_management.trailing_profit.giveback_ratio": 0.22,
        },
        track="btc_event_drift",
        anchor_name="btc_breakout_long_event_lb20_atr060_adx24_s050",
        playbook="btc_event_drift",
    )
    add(
        btc_long,
        name="btc_squeeze_follow_long_lb16_atr050_adx20_s058",
        note="BTC stage185：拥挤延续保留，但排序低于 breakout / drift。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 16,
            "strategy_params.breakout_atr_buffer": 0.50,
            "strategy_params.cooldown_bars": 2,
            "filters.adx_floor": 20,
            "money_management.stake_scale.btc_long": 0.54,
            "money_management.take_profit_pct": 1.16,
            "money_management.trailing_profit.activation_pnl_pct": 0.40,
            "money_management.trailing_profit.giveback_ratio": 0.22,
        },
        track="btc_squeeze_follow",
        anchor_name="btc_breakout_long_event_lb20_atr060_adx24_s050",
        playbook="btc_squeeze_follow",
    )
    add(
        btc_short,
        name="btc_retest_short_event_lb18_atr056_adx22_cd2_s074",
        note="BTC stage185：空腿只保留 retest short，继续黑 break_fail。",
        family="short",
        patch={
            "strategy_params.breakout_lookback": 18,
            "strategy_params.breakout_atr_buffer": 0.56,
            "strategy_params.cooldown_bars": 2,
            "filters.adx_floor": 22,
            "money_management.stake_scale.btc_short": 0.88,
            "money_management.take_profit_pct": 1.10,
            "money_management.trailing_profit.activation_pnl_pct": 0.38,
            "money_management.trailing_profit.giveback_ratio": 0.22,
        },
        track="btc_retest_short",
        anchor_name="btc_retest_short_event_lb20_atr060_adx24_s072",
        playbook="btc_retest_short",
    )
    add(
        btc_dual,
        name="btc_dual_hedge_band_dynlev_fix9_cd2",
        note="BTC stage185：保留 dual hedge band，但不让它压过已经转正的 long 主腿。",
        family="dual",
        patch={
            "strategy_params.cooldown_bars": 2,
            "filters.adx_floor": 16,
            "money_management.stake_scale.btc_long": 0.58,
            "money_management.stake_scale.btc_short": 0.90,
            "money_management.take_profit_pct": 1.16,
            "money_management.trailing_profit.activation_pnl_pct": 0.40,
            "money_management.trailing_profit.giveback_ratio": 0.23,
        },
        track="btc_dual_hedge",
        anchor_name="btc_dual_fast_trend_dynlev_fix8",
        playbook="btc_dual_hedge",
    )

    add(
        eth_long,
        name="eth_event_drift_long_lb12_atr046_adx18_s042",
        note="ETH stage185：本轮主攻 event drift，把 stage184 真正最好的一组钉成主锚。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 12,
            "strategy_params.breakout_atr_buffer": 0.46,
            "strategy_params.cooldown_bars": 2,
            "filters.adx_floor": 18,
            "money_management.stake_scale.eth_long": 0.54,
            "money_management.take_profit_pct": 1.26,
            "money_management.trailing_profit.activation_pnl_pct": 0.44,
            "money_management.trailing_profit.giveback_ratio": 0.24,
        },
        track="eth_event_drift",
        anchor_name=str(eth_long.get("name")) if eth_long else "",
        playbook="eth_event_drift",
    )
    add(
        eth_long,
        name="eth_event_drift_long_lb10_atr044_adx16_s046",
        note="ETH stage185：事件漂移提频版，只围绕已有正收益盆地扩圈。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 10,
            "strategy_params.breakout_atr_buffer": 0.44,
            "strategy_params.cooldown_bars": 2,
            "filters.adx_floor": 16,
            "money_management.stake_scale.eth_long": 0.52,
            "money_management.take_profit_pct": 1.24,
            "money_management.trailing_profit.activation_pnl_pct": 0.44,
            "money_management.trailing_profit.giveback_ratio": 0.24,
        },
        track="eth_event_drift",
        anchor_name=str(eth_long.get("name")) if eth_long else "",
        playbook="eth_event_drift",
    )
    add(
        eth_long,
        name="eth_squeeze_follow_long_lb9_atr040_adx15_s048",
        note="ETH stage185：squeeze follow 作为第二主攻，不再让 reclaim 单核霸榜。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 9,
            "strategy_params.breakout_atr_buffer": 0.40,
            "strategy_params.cooldown_bars": 2,
            "filters.adx_floor": 15,
            "money_management.stake_scale.eth_long": 0.50,
            "money_management.take_profit_pct": 1.24,
            "money_management.trailing_profit.activation_pnl_pct": 0.44,
            "money_management.trailing_profit.giveback_ratio": 0.24,
        },
        track="eth_squeeze_follow",
        anchor_name=str(eth_long.get("name")) if eth_long else "",
        playbook="eth_squeeze_follow",
    )
    add(
        eth_long,
        name="eth_reclaim_ladder_long_lb11_atr043_adx16_cd2_s064",
        note="ETH stage185：reclaim 不删，但只保留一条 ladder 参考线。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 11,
            "strategy_params.breakout_atr_buffer": 0.43,
            "strategy_params.cooldown_bars": 2,
            "filters.adx_floor": 16,
            "money_management.stake_scale.eth_long": 0.48,
            "money_management.take_profit_pct": 1.22,
            "money_management.trailing_profit.activation_pnl_pct": 0.42,
            "money_management.trailing_profit.giveback_ratio": 0.23,
        },
        track="eth_reclaim_ladder",
        anchor_name=str(eth_long.get("name")) if eth_long else "",
        playbook="eth_reclaim_ladder",
    )
    add(
        eth_short,
        name="eth_retest_short_trend_lb20_atr060_adx24_s068",
        note="ETH stage185：空腿继续保留 retest short，防止多头单边思维。",
        family="short",
        patch={
            "strategy_params.breakout_lookback": 20,
            "strategy_params.breakout_atr_buffer": 0.60,
            "strategy_params.cooldown_bars": 3,
            "filters.adx_floor": 24,
            "money_management.stake_scale.eth_short": 0.74,
            "money_management.take_profit_pct": 1.10,
            "money_management.trailing_profit.activation_pnl_pct": 0.38,
            "money_management.trailing_profit.giveback_ratio": 0.22,
        },
        track="eth_retest_short",
        anchor_name=str(eth_short.get("name")) if eth_short else "",
        playbook="eth_retest_short",
    )
    add(
        eth_short,
        name="eth_retest_short_trend_lb18_atr056_adx22_cd2_s072",
        note="ETH stage185：更密一点的 retest short 备份，和 drift/squeeze 做反手对照。",
        family="short",
        patch={
            "strategy_params.breakout_lookback": 18,
            "strategy_params.breakout_atr_buffer": 0.56,
            "strategy_params.cooldown_bars": 2,
            "filters.adx_floor": 22,
            "money_management.stake_scale.eth_short": 0.72,
            "money_management.take_profit_pct": 1.08,
            "money_management.trailing_profit.activation_pnl_pct": 0.38,
            "money_management.trailing_profit.giveback_ratio": 0.22,
        },
        track="eth_retest_short",
        anchor_name=str(eth_short.get("name")) if eth_short else "",
        playbook="eth_retest_short",
    )

    add(
        sol_long_alt,
        name="sol_pullback_pair_long_adx26_cd6_lb22_zone026_s042",
        note="SOL stage185：pair/pullback 长腿保留为第一主攻。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 22,
            "strategy_params.breakout_atr_buffer": 0.42,
            "strategy_params.cooldown_bars": 4,
            "filters.adx_floor": 26,
            "money_management.stake_scale.sol_long": 0.38,
            "money_management.take_profit_pct": 1.20,
            "money_management.trailing_profit.activation_pnl_pct": 0.42,
            "money_management.trailing_profit.giveback_ratio": 0.23,
        },
        track="sol_pullback_pair",
        anchor_name=str(sol_long_alt.get("name")) if sol_long_alt else "",
        playbook="sol_pullback_pair",
    )
    add(
        sol_long,
        name="sol_range_ladder_long_adx24_cd4_lb20_zone024_s048",
        note="SOL stage185：range ladder 作为第二主攻。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 20,
            "strategy_params.breakout_atr_buffer": 0.48,
            "strategy_params.cooldown_bars": 4,
            "filters.adx_floor": 24,
            "money_management.stake_scale.sol_long": 0.42,
            "money_management.take_profit_pct": 1.20,
            "money_management.trailing_profit.activation_pnl_pct": 0.42,
            "money_management.trailing_profit.giveback_ratio": 0.23,
        },
        track="sol_range_ladder",
        anchor_name=str(sol_long.get("name")) if sol_long else "",
        playbook="sol_range_ladder",
    )
    add(
        sol_long,
        name="sol_pullback_grid_long_adx24_cd3_lb20_zone024_s050",
        note="SOL stage185：grid-like pullback 只作为 long 辅助线。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 20,
            "strategy_params.breakout_atr_buffer": 0.50,
            "strategy_params.cooldown_bars": 3,
            "filters.adx_floor": 24,
            "money_management.stake_scale.sol_long": 0.40,
            "money_management.take_profit_pct": 1.18,
            "money_management.trailing_profit.activation_pnl_pct": 0.40,
            "money_management.trailing_profit.giveback_ratio": 0.22,
        },
        track="sol_pullback_grid",
        anchor_name=str(sol_long.get("name")) if sol_long else "",
        playbook="sol_pullback_grid",
    )
    add(
        sol_long_alt,
        name="sol_pullback_pair_long_adx24_cd4_lb20_zone024_s046",
        note="SOL stage185：再给一条更密一点的 pullback pair 扩圈。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 20,
            "strategy_params.breakout_atr_buffer": 0.46,
            "strategy_params.cooldown_bars": 4,
            "filters.adx_floor": 24,
            "money_management.stake_scale.sol_long": 0.39,
            "money_management.take_profit_pct": 1.18,
            "money_management.trailing_profit.activation_pnl_pct": 0.40,
            "money_management.trailing_profit.giveback_ratio": 0.22,
        },
        track="sol_pullback_pair",
        anchor_name=str(sol_long_alt.get("name")) if sol_long_alt else "",
        playbook="sol_pullback_pair",
    )
    add(
        sol_short,
        name="sol_guarded_short_accel_lb14_atr052_adx18_cd1_s076",
        note="SOL stage185：空腿只留一条 guarded short，继续保路不抢主算力。",
        family="short",
        patch={
            "strategy_params.breakout_lookback": 14,
            "strategy_params.breakout_atr_buffer": 0.52,
            "strategy_params.cooldown_bars": 1,
            "filters.adx_floor": 18,
            "money_management.stake_scale.sol_short": 0.56,
            "money_management.take_profit_pct": 1.04,
            "money_management.trailing_profit.activation_pnl_pct": 0.36,
            "money_management.trailing_profit.giveback_ratio": 0.21,
        },
        track="sol_guarded_short",
        anchor_name=str(sol_short.get("name")) if sol_short else "",
        playbook="sol_guarded_short",
    )
    return out


def _select_top(payload: list[dict[str, Any]], *, symbol: str | None = None, limit: int = 5) -> list[dict[str, Any]]:
    rows = payload
    if symbol:
        rows = [r for r in payload if r["symbol"] == symbol]
    return rows[:limit]


def _split_recommendation(branch_payload: list[dict[str, Any]]) -> str:
    ready = 0
    for sym in ["btc", "eth", "sol"]:
        top = next((r for r in branch_payload if r["symbol"] == sym and r["status"] in {"demo_ready", "accel_track"}), None)
        if top is not None:
            ready += 1
    return "consider_multi_terminal" if ready >= 2 else "keep_single_branch_terminal"


def _write_report(path_txt: Path, path_json: Path, main_rows: list[dict[str, Any]], branch_rows: list[dict[str, Any]], repaired_main: list[str], repaired_branch: list[str], scanned_main: list[str], scanned_branch: list[str], active_map: dict[str, str]) -> dict[str, Any]:
    main_payload = _top_payload(main_rows, branch=False)
    branch_payload = _top_payload(branch_rows, branch=True)
    split_rec = _split_recommendation(branch_payload)

    summary = {
        "target_monthly_min": TARGET_MONTHLY_MIN,
        "target_monthly_max": TARGET_MONTHLY_MAX,
        "repaired_main": repaired_main,
        "repaired_branch": repaired_branch,
        "scanned_main": scanned_main,
        "scanned_branch": scanned_branch,
        "stage91_active": active_map,
        "split_recommendation": split_rec,
        "main_top": _select_top(main_payload, limit=8),
        "branch_top": _select_top(branch_payload, limit=15),
        "branch_by_symbol": {sym: _select_top(branch_payload, symbol=sym, limit=5) for sym in ["btc", "eth", "sol"]},
    }

    lines: list[str] = []
    lines.append("Stage185 target monthly focus frontier")
    lines.append("")
    lines.append("[summary]")
    lines.append(f"- target_monthly_floor={TARGET_MONTHLY_MIN*100:.2f}% target_monthly_ceiling={TARGET_MONTHLY_MAX*100:.2f}%")
    lines.append(f"- repaired_main={len(repaired_main)} repaired_branch={len(repaired_branch)}")
    lines.append(f"- scanned_main={len(scanned_main)} scanned_branch={len(scanned_branch)}")
    lines.append(f"- stage91_active={json.dumps(active_map, ensure_ascii=False)}")
    lines.append(f"- split_recommendation={split_rec}")
    lines.append("")

    lines.append("[main_top]")
    for row in summary["main_top"]:
        lines.append(f"- {row['name']} | playbook={row['playbook']} | status={row['status']} | recent_monthly={row['recent_monthly']*100:.2f}% | wf_monthly={row['wf_monthly']*100:.2f}% | recent_trades={row['recent_trades']} | wf_trades={row['wf_trades']} | gap_to_7.6={row['gap_to_floor']*100:.2f}%")
    lines.append("")

    for sym in ["eth", "btc", "sol"]:
        lines.append(f"[{sym}_top]")
        for row in summary["branch_by_symbol"][sym]:
            lines.append(f"- {row['name']} | playbook={row['playbook']} | status={row['status']} | recent_monthly={row['recent_monthly']*100:.2f}% | wf_monthly={row['wf_monthly']*100:.2f}% | recent_trades={row['recent_trades']} | wf_trades={row['wf_trades']} | gap_to_7.6={row['gap_to_floor']*100:.2f}%")
        lines.append("")

    lines.append("[conclusion]")
    if summary["main_top"]:
        top = summary["main_top"][0]
        lines.append(f"- 主线加速第一候选: {top['name']} | recent_monthly={top['recent_monthly']*100:.2f}% | wf_monthly={top['wf_monthly']*100:.2f}% | gap_to_7.6={top['gap_to_floor']*100:.2f}%")
    eth_top = summary["branch_by_symbol"]["eth"][0] if summary["branch_by_symbol"]["eth"] else None
    if eth_top:
        lines.append(f"- ETH 第一候选: {eth_top['name']} | recent_monthly={eth_top['recent_monthly']*100:.2f}% | wf_monthly={eth_top['wf_monthly']*100:.2f}% | gap_to_7.6={eth_top['gap_to_floor']*100:.2f}%")
    btc_top = summary["branch_by_symbol"]["btc"][0] if summary["branch_by_symbol"]["btc"] else None
    if btc_top:
        lines.append(f"- BTC 第一候选: {btc_top['name']} | recent_monthly={btc_top['recent_monthly']*100:.2f}% | wf_monthly={btc_top['wf_monthly']*100:.2f}% | gap_to_7.6={btc_top['gap_to_floor']*100:.2f}%")
    sol_top = summary["branch_by_symbol"]["sol"][0] if summary["branch_by_symbol"]["sol"] else None
    if sol_top:
        lines.append(f"- SOL 第一候选: {sol_top['name']} | recent_monthly={sol_top['recent_monthly']*100:.2f}% | wf_monthly={sol_top['wf_monthly']*100:.2f}% | gap_to_7.6={sol_top['gap_to_floor']*100:.2f}%")
    lines.append("- 这版不动 demo / 下单链路；只做研究层 target-monthly frontier。")
    lines.append("- BTC 继续黑 break_fail；主线从 overlay_hold 回到 banded/ladder 主攻；ETH 主攻 drift，squeeze 补位；SOL 继续 long 优先。")
    txt = "\n".join(lines).rstrip() + "\n"
    path_txt.write_text(txt, encoding="utf-8")
    path_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def _write_single_zip(out_zip: Path, files: dict[str, Path]) -> None:
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for arcname, path in files.items():
            if path.exists():
                zf.write(path, arcname=arcname)


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage185 target monthly focus frontier")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    raw = root / "reports" / "research_raw"
    raw.mkdir(parents=True, exist_ok=True)

    main_rows, branch_rows, repaired_main, repaired_branch = s141._load_stage_state(raw)
    cfg = rcb.load_research_base_config(root)
    initial_equity = float(cfg.get("portfolio", {}).get("initial_equity", 100000.0))
    data = s46._load_portfolio_data(root, cfg)
    full_start, full_end = s77._window_bounds_from_data(data)

    item_map = {str(item.get("name")): item for item in s88._mainline_items()}
    ref_item = item_map.get("mainline_live_dynlev_fix8_lock18") or item_map.get("mainline_live_base")
    if ref_item is None:
        raise SystemExit("missing mainline reference")
    ref_row = s136._run_mainline(root, cfg, data, _with_meta(ref_item, track="base", branch=False, anchor_name=str(ref_item.get("name")), playbook="base"), initial_equity, full_start, full_end)

    main_map = {str(r.get("name")): s161._ensure_mainline_row(r, ref_row, initial_equity, full_end) for r in main_rows}
    scanned_main: list[str] = []
    for item in _mainline_items():
        print(f"[stage185] main {item['name']}", flush=True)
        row = s136._run_mainline(root, cfg, data, item, initial_equity, full_start, full_end)
        row = s161._ensure_mainline_row(row, ref_row, initial_equity, full_end)
        main_map[str(row.get("name"))] = row
        scanned_main.append(str(row.get("name")))
    main_rows = s161._finalize_rows(list(main_map.values()), branch=False)

    branch_map = {str(r.get("name")): s161._ensure_branch_row(r, initial_equity) for r in branch_rows}
    scanned_branch: list[str] = []
    for item in _branch_items():
        print(f"[stage185] branch {item['name']}", flush=True)
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

    active_map = _stage91_active_map(branch_json)
    frontier_txt = raw / "stage185_target_monthly_focus_frontier_latest.txt"
    frontier_json = raw / "stage185_target_monthly_focus_frontier_latest.json"
    summary = _write_report(frontier_txt, frontier_json, main_rows, branch_rows, repaired_main, repaired_branch, scanned_main, scanned_branch, active_map)
    manifest = {
        "mode": "target_monthly_focus_frontier",
        "target_monthly_min": TARGET_MONTHLY_MIN,
        "target_monthly_max": TARGET_MONTHLY_MAX,
        "repaired_main": repaired_main,
        "repaired_branch": repaired_branch,
        "scanned_main": scanned_main,
        "scanned_branch": scanned_branch,
        "stage91_active": active_map,
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
    manifest_path = raw / "stage185_target_monthly_focus_manifest_latest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    s141._mirror_to_workspace(root, [main_txt, main_json, branch_txt, branch_json, frontier_txt, frontier_json, manifest_path])

    out_zip = root.parent / "Downloads" / "stage185_target_monthly_focus_frontier_latest.zip"
    _write_single_zip(out_zip, {
        "stage185_target_monthly_focus_frontier_latest.txt": frontier_txt,
        "stage185_target_monthly_focus_frontier_latest.json": frontier_json,
        "stage185_target_monthly_focus_manifest_latest.json": manifest_path,
        "stage90_mainline_event_alpha_matrix_latest.txt": main_txt,
        "stage90_mainline_event_alpha_matrix_latest.json": main_json,
        "stage91_branch_event_alpha_matrix_latest.txt": branch_txt,
        "stage91_branch_event_alpha_matrix_latest.json": branch_json,
    })
    print(out_zip)


if __name__ == "__main__":
    main()
