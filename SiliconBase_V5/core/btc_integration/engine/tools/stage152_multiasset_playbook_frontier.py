from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

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
from tools import stage136_regime_plateau_frontier as s136
from tools import stage141_guarded_asymmetry_shortlist as s141
from tools import stage147_reclaim_density_phase5 as s147

TARGET_MONTHLY_MIN = s136.TARGET_MONTHLY_MIN
TARGET_MONTHLY_MAX = s136.TARGET_MONTHLY_MAX


def _ensure_mainline_row(row: dict[str, Any], ref_row: dict[str, Any], initial_equity: float, full_end: Any) -> dict[str, Any]:
    out = row
    wf = out.get("walkforward")
    if not isinstance(wf, dict) or "metrics" not in wf:
        out["walkforward"] = s81._wf_result(out, ref_row, initial_equity, s81.RECENT_START, full_end)
    dom = out.get("dominant_gate")
    if not isinstance(dom, dict) or not dom:
        out["dominant_gate"] = s90._dominant_gate(out, branch=False)
    return out


def _ensure_branch_row(row: dict[str, Any], initial_equity: float) -> dict[str, Any]:
    out = row
    wf = out.get("walkforward")
    full_end = out.get("full_end")
    if (not isinstance(wf, dict) or "metrics" not in wf) and full_end is not None:
        out["walkforward"] = s82._wf_result(out, initial_equity, s78.RECENT_START, full_end)
    dom = out.get("dominant_gate")
    if not isinstance(dom, dict) or not dom:
        out["dominant_gate"] = s90._dominant_gate(out, branch=True)
    return out




def _mainline_ref_row(root: Path, cfg: dict[str, Any], data: dict[str, Any], initial_equity: float, full_start: Any, full_end: Any) -> dict[str, Any]:
    item_map = {str(item.get("name")): item for item in s88._mainline_items()}
    ref_item = item_map.get("mainline_live_dynlev_fix8_lock18") or item_map.get("mainline_live_base")
    if ref_item is None:
        return {}
    return s136._run_mainline(root, cfg, data, _with_meta(ref_item, track="base", branch=False), initial_equity, full_start, full_end)


def _ensure_mainline_schema(row: dict[str, Any], *, ref_row: dict[str, Any], initial_equity: float, full_end: Any) -> dict[str, Any]:
    return _ensure_mainline_row(copy.deepcopy(row), ref_row, initial_equity, full_end)

def _with_meta(item: dict[str, Any], *, track: str, branch: bool, anchor_name: str | None = None) -> dict[str, Any]:
    out = s136._with_meta(item, track=track, branch=branch)
    out.setdefault("meta", {})
    out["meta"]["anchor_name"] = str(anchor_name or out.get("name") or "")
    out["meta"].setdefault("risk_scale", 1.0)
    return out


def _new_mainline_items() -> list[dict[str, Any]]:
    item_map = {str(item.get("name")): item for item in s88._mainline_items()}
    base = item_map.get("mainline_live_dynlev_fix8_lock18") or item_map.get("mainline_live_base")
    out: list[dict[str, Any]] = []
    if base is None:
        return out

    variants = [
        (
            "mainline_live_dynlev_fix9_tp135_cd18",
            "主线 phase152：在 fix8_lock18 基础上轻提频，不改骨架，只把冷却和 trailing 再快一档。",
            {
                "strategy_params.cooldown_bars": 18,
                "portfolio.dynamic_leverage.enabled": True,
                "portfolio.dynamic_leverage.min": 4.0,
                "portfolio.dynamic_leverage.max": 9.0,
                "portfolio.dynamic_leverage.adx_low": 17.0,
                "portfolio.dynamic_leverage.adx_high": 34.0,
                "money_management.mode": "fixed",
                "money_management.capital_slices": 8,
                "money_management.stake_mode": "dynamic_equity",
                "money_management.stake_min_usd": 9000,
                "money_management.stake_max_usd": 14500,
                "money_management.stop_loss_pct": 0.17,
                "money_management.take_profit_pct": 1.35,
                "money_management.trailing_profit.enabled": True,
                "money_management.trailing_profit.activation_pnl_pct": 0.60,
                "money_management.trailing_profit.giveback_ratio": 0.30,
                "money_management.trailing_profit.min_lock_pnl_pct": 0.15,
            },
        ),
        (
            "mainline_live_dynlev_fix10_tp125_cd16",
            "主线 phase152：进一步提频，但继续让动态杠杆和硬保护单兜底，避免只靠松门槛。",
            {
                "strategy_params.cooldown_bars": 16,
                "portfolio.dynamic_leverage.enabled": True,
                "portfolio.dynamic_leverage.min": 4.0,
                "portfolio.dynamic_leverage.max": 10.0,
                "portfolio.dynamic_leverage.adx_low": 16.0,
                "portfolio.dynamic_leverage.adx_high": 32.0,
                "money_management.mode": "fixed",
                "money_management.capital_slices": 9,
                "money_management.stake_mode": "dynamic_equity",
                "money_management.stake_min_usd": 8500,
                "money_management.stake_max_usd": 14000,
                "money_management.stop_loss_pct": 0.16,
                "money_management.take_profit_pct": 1.25,
                "money_management.trailing_profit.enabled": True,
                "money_management.trailing_profit.activation_pnl_pct": 0.55,
                "money_management.trailing_profit.giveback_ratio": 0.28,
                "money_management.trailing_profit.min_lock_pnl_pct": 0.12,
            },
        ),
        (
            "mainline_live_dynlev_fix8_tp140_cd20",
            "主线 phase152：保守提频版，留更多保护，但把出场锁盈速度再提一点。",
            {
                "strategy_params.cooldown_bars": 20,
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
                "money_management.take_profit_pct": 1.40,
                "money_management.trailing_profit.enabled": True,
                "money_management.trailing_profit.activation_pnl_pct": 0.62,
                "money_management.trailing_profit.giveback_ratio": 0.30,
                "money_management.trailing_profit.min_lock_pnl_pct": 0.16,
            },
        ),
    ]

    for name, note, patch in variants:
        out.append(_with_meta(s88._make_mainline_variant(base, name=name, note=note, patch=patch), track="mainline_freq", branch=False, anchor_name="mainline_live_dynlev_fix8_lock18"))
    return out


def _new_branch_items() -> list[dict[str, Any]]:
    item_map = {str(item.get("name")): item for item in s88._branch_items()}
    out: list[dict[str, Any]] = []

    def add(item: dict[str, Any] | None, *, track: str, anchor_name: str | None = None) -> None:
        if item is not None:
            out.append(_with_meta(item, track=track, branch=True, anchor_name=anchor_name or str(item.get("name"))))

    btc_long = item_map.get("btc_breakout_long_event_lb20_atr060_adx24_s050")
    btc_short = item_map.get("btc_retest_short_event_lb20_atr060_adx24_s072")
    btc_dual = item_map.get("btc_dual_fast_trend_dynlev_fix8")
    eth_long = item_map.get("eth_breakout_long_follow_lb16_atr050_adx22_s034")
    eth_short = item_map.get("eth_retest_short_trend_lb20_atr060_adx24_s068")
    sol_long = item_map.get("sol_long_core_soft_lb20_zone025_s042")
    sol_short = item_map.get("sol_fast_trend_short_aggr_lb16_atr055_adx22_s076") or item_map.get("sol_fast_trend_short_guarded_lb18_atr060_adx24_s068")

    if btc_long is not None:
        add(
            s88._make_variant(
                btc_long,
                name="btc_event_drift_long_lb18_atr054_adx20_cd4_s058",
                note="BTC 事件漂移 long：不追第一根，优先做宏观/ETF/流向共振后的第二段。",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 18,
                    "filters.btc_breakout_atr_buffer": 0.54,
                    "strategy_params.cooldown_bars": 4,
                    "filters.btc_adx_floor": 20,
                    "money_management.stake_scale.btc_long": 0.58,
                },
            ),
            track="btc_drift",
            anchor_name="btc_breakout_long_event_lb20_atr060_adx24_s050",
        )
    if btc_short is not None:
        add(
            s88._make_variant(
                btc_short,
                name="btc_reclaim_short_lb18_atr056_adx20_cd4_s068",
                note="BTC 回踩失败 short：保留空腿，但强调二次确认而不是硬追第一脚。",
                family="short",
                patch={
                    "strategy_params.breakout_lookback": 18,
                    "filters.btc_breakout_atr_buffer": 0.56,
                    "strategy_params.cooldown_bars": 4,
                    "filters.btc_adx_floor": 20,
                    "filters.btc_short_pullback_atr": 0.90,
                    "money_management.stake_scale.btc_short": 0.68,
                },
            ),
            track="btc_reclaim_short",
            anchor_name="btc_retest_short_event_lb20_atr060_adx24_s072",
        )
    if btc_dual is not None:
        add(
            s88._make_variant(
                btc_dual,
                name="btc_dual_reclaim_dynlev_fix9",
                note="BTC 双向结构 phase152：保留 dual，不让 BTC 被挤回单侧逻辑。",
                family="dual",
                patch={
                    "strategy_params.cooldown_bars": 5,
                    "portfolio.dynamic_leverage.enabled": True,
                    "portfolio.dynamic_leverage.min": 4.0,
                    "portfolio.dynamic_leverage.max": 9.0,
                    "money_management.capital_slices": 9,
                    "money_management.take_profit_pct": 1.12,
                    "money_management.trailing_profit.activation_pnl_pct": 0.46,
                    "money_management.trailing_profit.giveback_ratio": 0.28,
                    "money_management.trailing_profit.min_lock_pnl_pct": 0.11,
                    "money_management.stake_scale.btc_long": 0.58,
                    "money_management.stake_scale.btc_short": 0.70,
                },
            ),
            track="btc_dual",
            anchor_name="btc_dual_fast_trend_dynlev_fix8",
        )

    if eth_long is not None:
        add(
            s88._make_variant(
                eth_long,
                name="eth_reclaim_long_lb11_atr042_adx15_cd2_s064",
                note="ETH reclaim 激进版：继续扩最强簇，但把第二脚确认再前提半档。",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 11,
                    "strategy_params.breakout_atr_buffer": 0.42,
                    "strategy_params.cooldown_bars": 2,
                    "filters.adx_floor": 15,
                    "money_management.stake_scale.eth_long": 0.64,
                },
            ),
            track="eth_reclaim",
            anchor_name="eth_reclaim_long_lb11_atr043_adx16_s060",
        )
        add(
            s88._make_variant(
                eth_long,
                name="eth_squeeze_follow_long_lb10_atr041_adx15_cd2_s072",
                note="ETH 挤仓延续激进版：把 follow 和 reclaim 并行，不再只押单一模板。",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 10,
                    "strategy_params.breakout_atr_buffer": 0.41,
                    "strategy_params.cooldown_bars": 2,
                    "filters.adx_floor": 15,
                    "money_management.stake_scale.eth_long": 0.72,
                },
            ),
            track="eth_squeeze",
            anchor_name="eth_squeeze_follow_long_lb10_atr042_adx16_s070",
        )
    if eth_short is not None:
        add(
            s88._make_variant(
                eth_short,
                name="eth_retest_short_trend_lb18_atr055_adx20_cd2_s070",
                note="ETH 空腿激进保留位：不让 short 断代，但只接受回踩失败后的方向确认。",
                family="short",
                patch={
                    "strategy_params.breakout_lookback": 18,
                    "strategy_params.breakout_atr_buffer": 0.55,
                    "strategy_params.cooldown_bars": 2,
                    "filters.adx_floor": 20,
                    "money_management.stake_scale.eth_short": 0.70,
                },
            ),
            track="eth_short_confirm",
            anchor_name="eth_retest_short_trend_lb20_atr060_adx24_s068",
        )

    if sol_long is not None:
        add(
            s88._make_variant(
                sol_long,
                name="sol_pullback_long_core_adx22_cd4_lb18_zone024_s050",
                note="SOL pullback long：继续保留多腿，但把 lookback/zone/cd 一起前提看提频。",
                family="long",
                patch={
                    "sr_entries.lookback_4h": 18,
                    "sr_entries.zone_atr_mult": 0.24,
                    "sr_entries.stake_scale": 0.50,
                    "sr_entries.cooldown_bars": 4,
                },
            ),
            track="sol_pullback",
            anchor_name="sol_long_core_soft_lb20_zone025_s042",
        )
        add(
            s88._make_variant(
                sol_long,
                name="sol_reclaim_long_core_adx20_cd4_lb18_zone024_s054",
                note="SOL reclaim long：尝试把 SOL 做成事件后回收，而不是只做慢回踩。",
                family="long",
                patch={
                    "sr_entries.lookback_4h": 18,
                    "sr_entries.zone_atr_mult": 0.24,
                    "sr_entries.stake_scale": 0.54,
                    "sr_entries.cooldown_bars": 4,
                },
            ),
            track="sol_reclaim",
            anchor_name="sol_long_core_soft_lb20_zone025_s042",
        )
    if sol_short is not None:
        add(
            s88._make_variant(
                sol_short,
                name="sol_fast_trend_short_guarded_lb16_atr055_adx20_cd4_s070",
                note="SOL guarded short：保留空腿，但要求更快确认和更轻仓的共振破位。",
                family="short",
                patch={
                    "strategy_params.breakout_lookback": 16,
                    "strategy_params.breakout_atr_buffer": 0.55,
                    "strategy_params.cooldown_bars": 4,
                    "filters.adx_floor": 20,
                    "money_management.stake_scale.sol_short": 0.70,
                },
            ),
            track="sol_short_guarded",
            anchor_name="sol_fast_trend_short_aggr_lb16_atr055_adx22_s076",
        )
    return out


def _frontier_score(row: dict[str, Any], rows: list[dict[str, Any]], *, branch: bool) -> float:
    if branch:
        if not isinstance(row.get("dominant_gate"), dict) or not isinstance(row.get("walkforward"), dict):
            return -1e9
    else:
        if not isinstance(row.get("dominant_gate"), dict) or not isinstance(row.get("walkforward"), dict):
            return -1e9
    base = s147._frontier_score(row, rows, branch=branch)
    dom = row.get("dominant_gate", {}) or {}
    recent = dom.get("recent_metrics", {}) or {}
    wf = (row.get("walkforward") or {}).get("metrics", {}) or {}
    meta = row.get("meta", {}) or {}

    recent_trades = int(recent.get("trades", 0) or 0)
    wf_trades = int(wf.get("trades", 0) or 0)
    recent_pf = s88._safe_float(recent.get("pf"))
    wf_pf = s88._safe_float(wf.get("pf"))
    recent_monthly = s88._safe_float(recent.get("monthlyized_ret"))
    wf_monthly = s88._safe_float(wf.get("monthlyized_ret"))
    wf_dd = abs(s88._safe_float(wf.get("maxdd")))
    abs(s88._safe_float((row.get("full_metrics") or {}).get("maxdd")))
    plateau = row.get("plateau", {}) or {}
    plateau_q = s88._safe_float(plateau.get("plateau"))
    neighbor_count = int(plateau.get("neighbor_count", 0) or 0)
    track = str(meta.get("track") or "base")
    name = str(row.get("name") or "")
    target_monthly = s136._target_monthly(row, branch=branch)

    bonus = 0.0
    penalty = 0.0

    if not branch:
        if name.startswith("mainline_live_dynlev_fix"):
            if recent_trades >= 30 and wf_trades >= 14 and recent_pf >= 3.0 and wf_pf >= 1.5:
                bonus += 8.0
            if recent_monthly >= 0.025 and wf_monthly >= 0.015:
                bonus += 8.0
            if target_monthly >= 0.026:
                bonus += 6.0
            if abs(recent_monthly - wf_monthly) <= 0.015:
                bonus += 4.0
            if wf_trades < 12 or wf_pf < 1.2 or wf_monthly <= 0.0:
                penalty += 12.0
            if wf_dd > 0.09:
                penalty += 8.0
        return float(base + bonus - penalty)

    sym = str(row.get("symbol") or "").lower()
    fam = str(row.get("family") or "").lower()

    if sym == "btc":
        if recent_monthly > 0.0 and wf_monthly > 0.0:
            bonus += 6.0
        if recent_trades >= 10 and wf_trades >= 8:
            bonus += 6.0
        if wf_dd <= 0.05:
            bonus += 4.0
        if fam == "dual" and recent_pf >= 1.2 and wf_pf >= 1.1:
            bonus += 4.0
        if target_monthly >= 0.02:
            bonus += 4.0
        if recent_trades < 6 or wf_trades < 6:
            penalty += 8.0
        if wf_monthly <= 0.0:
            penalty += 10.0
        if wf_pf < 1.0:
            penalty += 6.0

    if sym == "eth" and fam == "long":
        if recent_trades >= 24 and wf_trades >= 16:
            bonus += 10.0
        if recent_monthly >= 0.02 and wf_monthly >= 0.02:
            bonus += 12.0
        if target_monthly >= 0.025:
            bonus += 8.0
        if plateau_q >= 0.45 and neighbor_count >= 3:
            bonus += 8.0
        if track in {"eth_reclaim", "eth_squeeze"}:
            bonus += 4.0
        if wf_dd > 0.07:
            penalty += 8.0
        if recent_trades < 18 or wf_trades < 12:
            penalty += 10.0
        if recent_monthly > max(0.0, wf_monthly * 1.9) and plateau_q < 0.35:
            penalty += 10.0

    if sym == "eth" and fam == "short":
        if recent_monthly > 0.0 and wf_monthly > 0.0:
            bonus += 6.0
        if recent_trades >= 20 and wf_trades >= 18:
            bonus += 6.0
        if wf_pf >= 1.1:
            bonus += 4.0
        if wf_dd <= 0.08:
            bonus += 3.0
        if recent_trades < 8 or wf_trades < 12:
            penalty += 8.0
        if wf_monthly <= 0.0 or wf_pf < 1.0:
            penalty += 8.0

    if sym == "sol":
        if recent_monthly > 0.0 and wf_monthly > 0.0:
            bonus += 8.0
        if recent_trades >= 8 and wf_trades >= 6:
            bonus += 4.0
        if target_monthly >= 0.02:
            bonus += 4.0
        if track in {"sol_pullback", "sol_reclaim", "sol_short_guarded"}:
            bonus += 3.0
        if wf_monthly <= 0.0:
            penalty += 14.0
        if wf_pf < 1.0:
            penalty += 8.0
        if wf_dd > 0.10:
            penalty += 6.0

    return float(base + bonus - penalty)


def _finalize_rows(rows: list[dict[str, Any]], *, branch: bool) -> list[dict[str, Any]]:
    for row in rows:
        row["plateau"] = s136._plateau_summary(row, rows, branch=branch)
    for row in rows:
        row["alpha_score"] = _frontier_score(row, rows, branch=branch)
        row["decision"] = s136._frontier_label(row, branch=branch)
    rows.sort(key=lambda r: float(r.get("alpha_score", 0.0)), reverse=True)
    return rows


def _active_asset_name(branch_json: Path, symbol: str) -> str:
    try:
        payload = json.loads(branch_json.read_text(encoding="utf-8"))
    except Exception:
        return ""
    items = payload.get("asset_summary") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return ""
    for item in items:
        if str(item.get("symbol") or "").upper() == symbol.upper():
            active = item.get("active") if isinstance(item.get("active"), dict) else {}
            return str(active.get("name") or "")
    return ""


def _top_per_symbol(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    for row in rows:
        sym = str(row.get("symbol") or "").upper()
        if not sym:
            continue
        if sym not in best:
            best[sym] = row
    return best


def _readiness(row: dict[str, Any]) -> str:
    p = s136._payload_row(row, branch=True)
    target = float(p.get("target_monthly") or 0.0)
    recent_m = float(p.get("recent_monthly") or 0.0)
    wf_m = float(p.get("wf_monthly") or 0.0)
    recent_t = int(p.get("recent_trades") or 0)
    wf_t = int(p.get("wf_trades") or 0)
    wf_pf = float(p.get("wf_pf") or 0.0)

    if target >= TARGET_MONTHLY_MIN and recent_m >= 0.05 and wf_m >= 0.04 and recent_t >= 20 and wf_t >= 15 and wf_pf >= 1.4:
        return "candidate_submit"
    if target >= 0.03 and recent_m > 0 and wf_m > 0 and recent_t >= 10 and wf_t >= 8 and wf_pf >= 1.1:
        return "watch_plus"
    if recent_m > 0 or wf_m > 0:
        return "watch"
    return "research_only"


def _split_recommendation(best_rows: dict[str, dict[str, Any]]) -> tuple[str, dict[str, str]]:
    status = {sym: _readiness(row) for sym, row in best_rows.items()}
    submit_like = sum(1 for v in status.values() if v == "candidate_submit")
    plus_like = sum(1 for v in status.values() if v in {"candidate_submit", "watch_plus"})
    rec = "consider_multi_terminal_split" if submit_like >= 2 or plus_like >= 3 else "keep_single_branch_terminal"
    return rec, status


def _write_report(
    path_txt: Path,
    path_json: Path,
    main_rows: list[dict[str, Any]],
    branch_rows: list[dict[str, Any]],
    repaired_main: list[str],
    repaired_branch: list[str],
    scanned_main: list[str],
    scanned_branch: list[str],
    active_map: dict[str, str],
) -> None:
    main_payload = [s136._payload_row(r, branch=False) for r in main_rows]
    branch_payload = [s136._payload_row(r, branch=True) for r in branch_rows]
    best_by_symbol = _top_per_symbol(branch_rows)
    split_rec, asset_status = _split_recommendation(best_by_symbol)

    lines: list[str] = []
    lines.append("Stage152 多资产剧本前沿 + 终端拆分判断")
    lines.append("原则：主线继续稳在 fix8_lock18，不动 runtime；研究层直接按 BTC/ETH/SOL 各自剧本快刷，并明确是否需要拆多终端。")
    lines.append(f"目标区间：{TARGET_MONTHLY_MIN*100:.1f}% - {TARGET_MONTHLY_MAX*100:.1f}% / 月")
    lines.append("")
    lines.append(f"- 修复对象: main={len(repaired_main)} | branch={len(repaired_branch)}")
    lines.append(f"- 新刷主线候选: {', '.join(scanned_main) if scanned_main else '-'}")
    lines.append(f"- 新刷分支候选: {', '.join(scanned_branch) if scanned_branch else '-'}")
    lines.append("")
    lines.append("=== 主线重点 ===")
    for row in main_payload[:6]:
        lines.append(
            f"- {row['name']}: target_monthly={row['target_monthly']*100:.2f}% | 近2年={row['recent_monthly']*100:.2f}%/{row['recent_trades']}笔/PF{row['recent_pf']:.3f} | WF={row['wf_monthly']*100:.2f}%/{row['wf_trades']}笔/PF{row['wf_pf']:.3f} | decision={row['decision']}"
        )
    lines.append("")
    lines.append("=== 分资产第一名 ===")
    for sym in sorted(best_by_symbol):
        row = best_by_symbol[sym]
        p = s136._payload_row(row, branch=True)
        lines.append(
            f"- {sym}: {p['name']} | {p['family']} | track={p['track']} | target_monthly={p['target_monthly']*100:.2f}% | 近2年={p['recent_monthly']*100:.2f}%/{p['recent_trades']}笔/PF{p['recent_pf']:.3f} | WF={p['wf_monthly']*100:.2f}%/{p['wf_trades']}笔/PF{p['wf_pf']:.3f} | status={asset_status.get(sym,'research_only')} | stage91_active={active_map.get(sym,'-')}"
        )
    lines.append("")
    lines.append("=== 终端拆分判断 ===")
    lines.append(f"- recommendation={split_rec}")
    if split_rec == "keep_single_branch_terminal":
        lines.append("- 结论：现在不拆 3 个模拟盘终端；策略模板已经按资产分开，但提交执行仍先放在 1 个 branch 终端里。")
    else:
        lines.append("- 结论：已有足够多资产接近独立提交条件，可以开始评估拆多终端。")
    lines.append("")
    lines.append("=== 结论 ===")
    if main_payload:
        top = main_payload[0]
        lines.append(f"- 主线第一名: {top['name']} | target_monthly={top['target_monthly']*100:.2f}% | gap_to_7.6={top['gap_to_floor']*100:.2f}%")
    if branch_payload:
        top = branch_payload[0]
        lines.append(f"- 分支总第一名: {top['name']} | {top.get('symbol','-')}|{top.get('family','-')} | track={top['track']} | target_monthly={top['target_monthly']*100:.2f}% | gap_to_7.6={top['gap_to_floor']*100:.2f}%")
    lines.append("- 这轮目的不是直接切 runtime，而是先验证：主线能否提频、BTC/ETH/SOL 是否真的需要分终端、以及 SOL 多空是否开始站住。")

    payload = {
        "mode": "multiasset_playbook_frontier",
        "target_monthly_min": TARGET_MONTHLY_MIN,
        "target_monthly_max": TARGET_MONTHLY_MAX,
        "repaired_main": repaired_main,
        "repaired_branch": repaired_branch,
        "new_mainline_candidates": scanned_main,
        "new_branch_candidates": scanned_branch,
        "stage91_active": active_map,
        "split_recommendation": split_rec,
        "asset_status": asset_status,
        "mainline": main_payload,
        "branch": branch_payload,
    }
    path_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    path_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage152 multiasset playbook frontier")
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

    mainline_items_all = {str(item.get("name")): item for item in s88._mainline_items()}
    ref_item = mainline_items_all.get("mainline_live_base") or mainline_items_all.get("mainline_live_dynlev_fix8_lock18")
    if ref_item is None:
        raise SystemExit("missing mainline reference for stage152")
    ref_row = s136._run_mainline(root, cfg, data, _with_meta(ref_item, track="base", branch=False), initial_equity, full_start, full_end)

    main_map = {str(r.get("name")): _ensure_mainline_row(copy.deepcopy(r), ref_row, initial_equity, full_end) for r in main_rows}
    scanned_main: list[str] = []
    for item in _new_mainline_items():
        print(f"[stage152] main {item['name']}", flush=True)
        row = s136._run_mainline(root, cfg, data, item, initial_equity, full_start, full_end)
        row = _ensure_mainline_row(row, ref_row, initial_equity, full_end)
        main_map[str(row.get("name"))] = row
        scanned_main.append(str(row.get("name")))
    main_rows = _finalize_rows(list(main_map.values()), branch=False)

    branch_map = {str(r.get("name")): _ensure_branch_row(copy.deepcopy(r), initial_equity) for r in branch_rows}
    scanned_branch: list[str] = []
    for item in _new_branch_items():
        print(f"[stage152] branch {item['name']}", flush=True)
        row = s136._run_branch(root, cfg, item, initial_equity)
        row = _ensure_branch_row(row, initial_equity)
        branch_map[str(row.get("name"))] = row
        scanned_branch.append(str(row.get("name")))
    branch_rows = _finalize_rows(list(branch_map.values()), branch=True)

    main_txt = raw / "stage90_mainline_event_alpha_matrix_latest.txt"
    main_json = raw / "stage90_mainline_event_alpha_matrix_latest.json"
    branch_txt = raw / "stage91_branch_event_alpha_matrix_latest.txt"
    branch_json = raw / "stage91_branch_event_alpha_matrix_latest.json"
    s90._write_mainline(main_txt, main_json, main_rows)
    s90._write_branch(branch_txt, branch_json, branch_rows)

    active_map = {sym: _active_asset_name(branch_json, sym) for sym in ["BTC", "ETH", "SOL"]}

    frontier_txt = raw / "stage152_multiasset_playbook_frontier_latest.txt"
    frontier_json = raw / "stage152_multiasset_playbook_frontier_latest.json"
    _write_report(
        frontier_txt,
        frontier_json,
        main_rows,
        branch_rows,
        repaired_main,
        repaired_branch,
        scanned_main,
        scanned_branch,
        active_map,
    )

    manifest = {
        "mode": "multiasset_playbook_frontier",
        "repaired_main": repaired_main,
        "repaired_branch": repaired_branch,
        "new_mainline_candidates": scanned_main,
        "new_branch_candidates": scanned_branch,
        "stage91_active": active_map,
        "outputs": {
            "stage90_txt": str(main_txt),
            "stage90_json": str(main_json),
            "stage91_txt": str(branch_txt),
            "stage91_json": str(branch_json),
            "frontier_txt": str(frontier_txt),
            "frontier_json": str(frontier_json),
        },
    }
    manifest_path = raw / "stage152_multiasset_playbook_frontier_manifest_latest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    s141._mirror_to_workspace(root, [main_txt, main_json, branch_txt, branch_json, frontier_txt, frontier_json, manifest_path])

    print(main_txt)
    print(main_json)
    print(branch_txt)
    print(branch_json)
    print(frontier_txt)
    print(frontier_json)
    print(manifest_path)


if __name__ == "__main__":
    main()
