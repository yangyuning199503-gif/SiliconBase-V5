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
from tools import stage152_multiasset_playbook_frontier as s152

TARGET_MONTHLY_MIN = s136.TARGET_MONTHLY_MIN
TARGET_MONTHLY_MAX = s136.TARGET_MONTHLY_MAX


def _default_walkforward() -> dict[str, Any]:
    return {
        "folds": [],
        "metrics": {
            "ret": 0.0,
            "monthlyized_ret": 0.0,
            "maxdd": 0.0,
            "trades": 0,
            "pf": 0.0,
        },
        "gate_mix": {},
        "positive_folds": 0,
        "total_folds": 0,
        "pf_floor": 0.0,
        "dd_ceiling": 0.0,
        "score": 0.0,
        "label": "kill",
    }


def _compat_mainline_ref_row(root: Path, cfg: dict[str, Any], data: dict[str, Any], initial_equity: float, full_start: Any, full_end: Any) -> dict[str, Any]:
    helper = getattr(s152, "_mainline_ref_row", None)
    if callable(helper):
        return helper(root, cfg, data, initial_equity, full_start, full_end)
    item_map = {str(item.get("name")): item for item in s88._mainline_items()}
    ref_item = item_map.get("mainline_live_dynlev_fix8_lock18") or item_map.get("mainline_live_base")
    if ref_item is None:
        return {}
    return s90._run_mainline(root, cfg, data, ref_item, initial_equity, full_start, full_end)


def _compat_ensure_mainline_schema(row: dict[str, Any], *, ref_row: dict[str, Any], initial_equity: float, full_end: Any) -> dict[str, Any]:
    helper = getattr(s152, "_ensure_mainline_schema", None)
    if callable(helper):
        return helper(row, ref_row=ref_row, initial_equity=initial_equity, full_end=full_end)

    out = copy.deepcopy(row)
    dom = out.get("dominant_gate")
    if not isinstance(dom, dict) or "recent_metrics" not in dom:
        gate_rows = out.get("gate_rows") or []
        if gate_rows:
            try:
                out["dominant_gate"] = s90._dominant_gate(out, branch=False)
            except Exception:
                out["dominant_gate"] = {"gate_name": "base_message_overlay", "recent_metrics": {}}
        else:
            out["dominant_gate"] = {"gate_name": "base_message_overlay", "recent_metrics": {}}

    wf = out.get("walkforward")
    if not isinstance(wf, dict) or "metrics" not in wf:
        gate_rows = out.get("gate_rows") or []
        if gate_rows:
            try:
                out["walkforward"] = s81._wf_result(out, ref_row or out, initial_equity, s81.RECENT_START, full_end)
            except Exception:
                out["walkforward"] = _default_walkforward()
        else:
            out["walkforward"] = _default_walkforward()
    return out


def _with_meta(item: dict[str, Any], *, track: str, branch: bool, anchor_name: str | None = None, playbook: str = "base") -> dict[str, Any]:
    out = s136._with_meta(item, track=track, branch=branch)
    out.setdefault("meta", {})
    out["meta"]["anchor_name"] = str(anchor_name or out.get("name") or "")
    out["meta"]["playbook"] = playbook
    out["meta"].setdefault("risk_scale", 1.0)
    out["meta"]["bug_guard"] = True
    return out


def _new_mainline_items() -> list[dict[str, Any]]:
    item_map = {str(item.get("name")): item for item in s88._mainline_items()}
    base = item_map.get("mainline_live_dynlev_fix8_lock18") or item_map.get("mainline_live_base")
    out: list[dict[str, Any]] = []
    if base is None:
        return out

    variants = [
        (
            "mainline_live_dynlev_fix8_lock18_lb24_buf044_cd12",
            "主线 phase157：事件状态只做加速器，不改单一骨架；用更快 cooldown + 更快 trailing 提频。",
            {
                "strategy_params.breakout_lookback": 24,
                "strategy_params.breakout_atr_buffer": 0.44,
                "strategy_params.cooldown_bars": 12,
                "filters.adx_floor": 26,
                "filters.btc_breakout_atr_buffer": 0.92,
                "execution_guard.pause_bars": 6,
                "money_management.stake_scale.bnb_long": 1.10,
                "money_management.take_profit_pct": 1.22,
                "money_management.trailing_profit.activation_pnl_pct": 0.52,
                "money_management.trailing_profit.giveback_ratio": 0.28,
                "money_management.trailing_profit.min_lock_pnl_pct": 0.11,
            },
        ),
        (
            "mainline_live_dynlev_fix8_lock18_lb22_buf042_cd10",
            "主线 phase157：继续加速，但仍保留 execution guard，避免只靠放宽阈值乱提频。",
            {
                "strategy_params.breakout_lookback": 22,
                "strategy_params.breakout_atr_buffer": 0.42,
                "strategy_params.cooldown_bars": 10,
                "filters.adx_floor": 24,
                "filters.btc_breakout_atr_buffer": 0.90,
                "execution_guard.pause_bars": 5,
                "money_management.stake_scale.bnb_long": 1.12,
                "money_management.take_profit_pct": 1.18,
                "money_management.trailing_profit.activation_pnl_pct": 0.48,
                "money_management.trailing_profit.giveback_ratio": 0.26,
                "money_management.trailing_profit.min_lock_pnl_pct": 0.10,
            },
        ),
        (
            "mainline_live_dynlev_fix8_lock18_lb20_buf040_cd8",
            "主线 phase157：最激进探针，只留研究层；用于验证消息面+技术面能否把机会密度真正抬起来。",
            {
                "strategy_params.breakout_lookback": 20,
                "strategy_params.breakout_atr_buffer": 0.40,
                "strategy_params.cooldown_bars": 8,
                "filters.adx_floor": 24,
                "filters.btc_breakout_atr_buffer": 0.88,
                "execution_guard.pause_bars": 4,
                "money_management.stake_scale.bnb_long": 1.14,
                "money_management.take_profit_pct": 1.14,
                "money_management.trailing_profit.activation_pnl_pct": 0.44,
                "money_management.trailing_profit.giveback_ratio": 0.25,
                "money_management.trailing_profit.min_lock_pnl_pct": 0.09,
            },
        ),
    ]

    for name, note, patch in variants:
        out.append(
            _with_meta(
                s88._make_mainline_variant(base, name=name, note=note, patch=patch),
                track="mainline_regime_accel",
                branch=False,
                anchor_name="mainline_live_dynlev_fix8_lock18",
                playbook="event_regime_accelerator",
            )
        )
    return out


def _new_branch_items() -> list[dict[str, Any]]:
    item_map = {str(item.get("name")): item for item in s88._branch_items()}
    out: list[dict[str, Any]] = []

    def add(item: dict[str, Any] | None, *, track: str, anchor_name: str | None = None, playbook: str = "base") -> None:
        if item is not None:
            out.append(_with_meta(item, track=track, branch=True, anchor_name=anchor_name or str(item.get("name")), playbook=playbook))

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
                name="btc_squeeze_follow_long_lb16_atr050_adx18_cd3_s062",
                note="BTC phase157：宏观/ETF/流向共振时，做第二段 squeeze-follow，不追第一根。",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 16,
                    "filters.btc_breakout_atr_buffer": 0.50,
                    "strategy_params.cooldown_bars": 3,
                    "filters.btc_adx_floor": 18,
                    "money_management.stake_scale.btc_long": 0.62,
                },
            ),
            track="btc_squeeze_follow",
            anchor_name="btc_breakout_long_event_lb20_atr060_adx24_s050",
            playbook="btc_event_plus_squeeze",
        )
    if btc_short is not None:
        add(
            s88._make_variant(
                btc_short,
                name="btc_reclaim_short_lb16_atr054_adx18_cd3_s070",
                note="BTC phase157：回踩失败 short，保留空腿，但只做二次确认后的失败段。",
                family="short",
                patch={
                    "strategy_params.breakout_lookback": 16,
                    "filters.btc_breakout_atr_buffer": 0.54,
                    "strategy_params.cooldown_bars": 3,
                    "filters.btc_adx_floor": 18,
                    "filters.btc_short_pullback_atr": 0.86,
                    "money_management.stake_scale.btc_short": 0.72,
                },
            ),
            track="btc_reclaim_short",
            anchor_name="btc_retest_short_event_lb20_atr060_adx24_s072",
            playbook="btc_reclaim_failure",
        )
    if btc_dual is not None:
        add(
            s88._make_variant(
                btc_dual,
                name="btc_dual_squeeze_reclaim_dynlev_fix9_cd3",
                note="BTC phase157：dual 路径不删，但压缩为 squeeze + reclaim 的双向组合。",
                family="dual",
                patch={
                    "strategy_params.cooldown_bars": 3,
                    "portfolio.dynamic_leverage.enabled": True,
                    "portfolio.dynamic_leverage.min": 4.0,
                    "portfolio.dynamic_leverage.max": 9.0,
                    "money_management.capital_slices": 9,
                    "money_management.take_profit_pct": 1.08,
                    "money_management.trailing_profit.activation_pnl_pct": 0.42,
                    "money_management.trailing_profit.giveback_ratio": 0.27,
                    "money_management.trailing_profit.min_lock_pnl_pct": 0.10,
                    "money_management.stake_scale.btc_long": 0.60,
                    "money_management.stake_scale.btc_short": 0.74,
                },
            ),
            track="btc_dual_regime",
            anchor_name="btc_dual_fast_trend_dynlev_fix8",
            playbook="btc_dual_macro",
        )

    if eth_long is not None:
        add(
            s88._make_variant(
                eth_long,
                name="eth_reclaim_long_lb10_atr041_adx14_cd1_s078",
                note="ETH phase157：继续主攻 reclaim，进一步前提第二脚确认，先提密度再看收口。",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 10,
                    "strategy_params.breakout_atr_buffer": 0.41,
                    "strategy_params.cooldown_bars": 1,
                    "filters.adx_floor": 14,
                    "money_management.stake_scale.eth_long": 0.78,
                },
            ),
            track="eth_reclaim_accel",
            anchor_name="eth_reclaim_long_lb12_atr043_adx16_s060",
            playbook="eth_reclaim",
        )
        add(
            s88._make_variant(
                eth_long,
                name="eth_squeeze_follow_long_lb9_atr040_adx14_cd1_s082",
                note="ETH phase157：保留 squeeze-follow，不让 reclaim 单线独大。",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 9,
                    "strategy_params.breakout_atr_buffer": 0.40,
                    "strategy_params.cooldown_bars": 1,
                    "filters.adx_floor": 14,
                    "money_management.stake_scale.eth_long": 0.82,
                },
            ),
            track="eth_squeeze_accel",
            anchor_name="eth_reclaim_long_lb12_atr043_adx16_s060",
            playbook="eth_squeeze_follow",
        )
    if eth_short is not None:
        add(
            s88._make_variant(
                eth_short,
                name="eth_retest_short_trend_lb16_atr052_adx18_cd2_s072",
                note="ETH phase157：空腿继续保留，主打事件后反抽失败与拥挤多头挤压回落。",
                family="short",
                patch={
                    "strategy_params.breakout_lookback": 16,
                    "strategy_params.breakout_atr_buffer": 0.52,
                    "strategy_params.cooldown_bars": 2,
                    "filters.adx_floor": 18,
                    "money_management.stake_scale.eth_short": 0.72,
                },
            ),
            track="eth_retest_short_accel",
            anchor_name="eth_retest_short_trend_lb20_atr060_adx24_s068",
            playbook="eth_retest_short",
        )

    if sol_long is not None:
        add(
            s88._make_variant(
                sol_long,
                name="sol_reclaim_long_core_adx18_cd3_lb16_zone022_s058",
                note="SOL phase157：多腿不删，优先做更快 reclaim/pullback。",
                family="long",
                patch={
                    "sr_entries.lookback_4h": 16,
                    "sr_entries.zone_atr_mult": 0.22,
                    "sr_entries.stake_scale": 0.58,
                    "sr_entries.cooldown_bars": 3,
                },
            ),
            track="sol_reclaim_accel",
            anchor_name="sol_pullback_long_core_adx26_cd6_lb22_zone026_s040",
            playbook="sol_reclaim",
        )
        add(
            s88._make_variant(
                sol_long,
                name="sol_pullback_long_core_adx18_cd3_lb14_zone020_s060",
                note="SOL phase157：再给一条更快的 pullback long，防止只剩一种慢长腿。",
                family="long",
                patch={
                    "sr_entries.lookback_4h": 14,
                    "sr_entries.zone_atr_mult": 0.20,
                    "sr_entries.stake_scale": 0.60,
                    "sr_entries.cooldown_bars": 3,
                },
            ),
            track="sol_pullback_accel",
            anchor_name="sol_pullback_long_core_adx26_cd6_lb22_zone026_s040",
            playbook="sol_pullback",
        )
    if sol_short is not None:
        add(
            s88._make_variant(
                sol_short,
                name="sol_fast_trend_short_guarded_lb14_atr052_adx18_cd3_s072",
                note="SOL phase157：空腿保留，主打 blow-off 后失败段，但继续 guarded。",
                family="short",
                patch={
                    "strategy_params.breakout_lookback": 14,
                    "strategy_params.breakout_atr_buffer": 0.52,
                    "strategy_params.cooldown_bars": 3,
                    "filters.adx_floor": 18,
                    "money_management.stake_scale.sol_short": 0.72,
                },
            ),
            track="sol_short_guarded_accel",
            anchor_name="sol_fast_trend_short_guarded_lb18_atr060_adx24_s068",
            playbook="sol_guarded_short",
        )
        add(
            s88._make_variant(
                sol_short,
                name="sol_retest_short_trend_lb16_atr054_adx20_cd3_s070",
                note="SOL phase157：给 short 再补一条 retest 失败版，不预设 SOL 只能 long。",
                family="short",
                patch={
                    "strategy_params.breakout_lookback": 16,
                    "strategy_params.breakout_atr_buffer": 0.54,
                    "strategy_params.cooldown_bars": 3,
                    "filters.adx_floor": 20,
                    "money_management.stake_scale.sol_short": 0.70,
                },
            ),
            track="sol_retest_short_accel",
            anchor_name="sol_fast_trend_short_guarded_lb18_atr060_adx24_s068",
            playbook="sol_retest_short",
        )
    return out


def _frontier_score(row: dict[str, Any], rows: list[dict[str, Any]], *, branch: bool) -> float:
    base = s152._frontier_score(row, rows, branch=branch)
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
    plateau = row.get("plateau", {}) or {}
    plateau_q = s88._safe_float(plateau.get("plateau"))
    neighbor_count = int(plateau.get("neighbor_count", 0) or 0)
    event_share = s88._safe_float(row.get("event_fold_share"))
    track = str(meta.get("track") or "base")
    playbook = str(meta.get("playbook") or "base")
    target_monthly = s136._target_monthly(row, branch=branch)

    bonus = 0.0
    penalty = 0.0

    if not branch:
        if recent_trades >= 30 and wf_trades >= 14:
            bonus += 8.0
        if recent_monthly >= 0.022 and wf_monthly >= 0.016:
            bonus += 10.0
        if target_monthly >= 0.030:
            bonus += 12.0
        if 0.10 <= event_share <= 0.80:
            bonus += 4.0
        if track == "mainline_regime_accel":
            bonus += 4.0
        if recent_trades == 0 or wf_trades == 0:
            penalty += 18.0
        if wf_monthly <= 0.0 or wf_pf < 1.2:
            penalty += 14.0
        if recent_monthly <= 0.0 or recent_pf < 1.2:
            penalty += 10.0
        return float(base + bonus - penalty)

    sym = str(row.get("symbol") or "").lower()
    fam = str(row.get("family") or "").lower()

    if sym == "eth" and fam == "long":
        if recent_trades >= 24 and wf_trades >= 16:
            bonus += 10.0
        if recent_monthly >= 0.020 and wf_monthly >= 0.020:
            bonus += 12.0
        if target_monthly >= 0.030:
            bonus += 14.0
        if plateau_q >= 0.40 and neighbor_count >= 3:
            bonus += 8.0
        if playbook in {"eth_reclaim", "eth_squeeze_follow"}:
            bonus += 4.0
        if recent_trades < 16 or wf_trades < 10:
            penalty += 8.0
        if wf_dd > 0.08:
            penalty += 8.0
        if wf_monthly <= 0.0 or wf_pf < 1.1:
            penalty += 10.0

    if sym == "eth" and fam == "short":
        if recent_monthly > 0.0 and wf_monthly > 0.0:
            bonus += 7.0
        if recent_trades >= 10 and wf_trades >= 10:
            bonus += 5.0
        if wf_pf >= 1.2:
            bonus += 4.0
        if wf_dd <= 0.08:
            bonus += 3.0
        if recent_trades < 6 or wf_trades < 8:
            penalty += 8.0
        if wf_monthly <= 0.0 or wf_pf < 1.0:
            penalty += 8.0

    if sym == "sol" and fam == "long":
        if recent_monthly > 0.0 and wf_monthly > 0.0:
            bonus += 8.0
        if recent_trades >= 8 and wf_trades >= 4:
            bonus += 4.0
        if target_monthly >= 0.018:
            bonus += 4.0
        if playbook in {"sol_reclaim", "sol_pullback"}:
            bonus += 4.0
        if wf_monthly <= 0.0:
            penalty += 12.0
        if wf_pf < 1.0:
            penalty += 8.0
        if wf_dd > 0.12:
            penalty += 6.0

    if sym == "sol" and fam == "short":
        if recent_monthly > 0.0 and wf_monthly > 0.0:
            bonus += 8.0
        if recent_trades >= 8 and wf_trades >= 6:
            bonus += 4.0
        if wf_pf >= 1.05:
            bonus += 4.0
        if playbook in {"sol_guarded_short", "sol_retest_short"}:
            bonus += 4.0
        if wf_monthly <= 0.0:
            penalty += 12.0
        if wf_pf < 1.0:
            penalty += 8.0

    if sym == "btc":
        if recent_monthly > 0.0 and wf_monthly > 0.0:
            bonus += 5.0
        if recent_trades >= 8 and wf_trades >= 8:
            bonus += 4.0
        if fam == "dual" and recent_pf >= 1.2 and wf_pf >= 1.1:
            bonus += 4.0
        if target_monthly >= 0.010:
            bonus += 3.0
        if recent_trades == 0 or wf_trades == 0:
            penalty += 14.0
        if wf_monthly <= 0.0:
            penalty += 8.0
        if wf_pf < 1.0:
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


def _best_entry(row_like: Any) -> dict[str, Any]:
    if isinstance(row_like, dict):
        if any(k in row_like for k in ("name", "symbol", "family", "recent_metrics", "full_metrics")):
            return row_like
        first = row_like.get(0) if 0 in row_like else None
        if isinstance(first, dict):
            return first
        return {}
    if isinstance(row_like, (list, tuple)) and row_like:
        first = row_like[0]
        return first if isinstance(first, dict) else {}
    return {}


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
    raw_best_by_symbol = s152._top_per_symbol(branch_rows)
    best_by_symbol = {sym: row for sym, row in ((sym, _best_entry(v)) for sym, v in raw_best_by_symbol.items()) if row}
    split_rec, asset_status = s152._split_recommendation(best_by_symbol)

    lines: list[str] = []
    lines.append("Stage157 资产分剧本加速前沿")
    lines.append("原则：不再一套模板通吃。主线继续 fix8_lock18，只做事件状态加速器；ETH 主攻 reclaim+squeeze，SOL 做 long/short 对称快刷，BTC 保留 event/reclaim/dual。")
    lines.append(f"目标区间：{TARGET_MONTHLY_MIN*100:.1f}% - {TARGET_MONTHLY_MAX*100:.1f}% / 月")
    lines.append("")
    lines.append(f"- bug_guard=enabled | 修复对象: main={len(repaired_main)} | branch={len(repaired_branch)}")
    lines.append(f"- 新刷主线候选: {', '.join(scanned_main) if scanned_main else '-'}")
    lines.append(f"- 新刷分支候选: {', '.join(scanned_branch) if scanned_branch else '-'}")
    lines.append("")
    lines.append("=== 建设性策略框架 ===")
    lines.append("- funding 继续只做拥挤过滤，不单独当开仓按钮。")
    lines.append("- OI/成交密度只做趋势确认：追第二段，不追第一条新闻第一根。")
    lines.append("- skew/DVOL 只做追涨还是等 reclaim 的切换器，不做裸方向。")
    lines.append("")
    lines.append("=== 主线重点 ===")
    for row in main_payload[:6]:
        lines.append(
            f"- {row['name']}: target_monthly={row['target_monthly']*100:.2f}% | 近2年={row['recent_monthly']*100:.2f}%/{row['recent_trades']}笔/PF{row['recent_pf']:.3f} | WF={row['wf_monthly']*100:.2f}%/{row['wf_trades']}笔/PF{row['wf_pf']:.3f} | decision={row['decision']}"
        )
    lines.append("")
    lines.append("=== 分资产第一名 ===")
    for sym in ["BTC", "ETH", "SOL"]:
        row_obj = _best_entry(best_by_symbol.get(sym))
        if not row_obj:
            continue
        row = s136._payload_row(row_obj, branch=True)
        lines.append(
            f"- {sym}: {row['name']} | {row['family']} | track={row['track']} | playbook={row.get('playbook','-')} | target_monthly={row['target_monthly']*100:.2f}% | 近2年={row['recent_monthly']*100:.2f}%/{row['recent_trades']}笔/PF{row['recent_pf']:.3f} | WF={row['wf_monthly']*100:.2f}%/{row['wf_trades']}笔/PF{row['wf_pf']:.3f} | status={row['decision']} | stage91_active={active_map.get(sym, '-') }"
        )
    lines.append("")
    lines.append("=== 终端拆分判断 ===")
    lines.append(f"- recommendation={split_rec}")
    lines.append("- 结论：现在仍先保留 1 个 branch 终端；如果后面要隔离同一标的真实仓位，再上子账户，不靠多开终端硬隔离。")
    lines.append("")
    lines.append("=== 结论 ===")
    if main_payload:
        top = main_payload[0]
        lines.append(f"- 主线第一名: {top['name']} | target_monthly={top['target_monthly']*100:.2f}% | gap_to_7.6={top['gap_to_floor']*100:.2f}%")
    if branch_payload:
        top = branch_payload[0]
        lines.append(f"- 分支总第一名: {top['name']} | {top.get('symbol','-')}|{top.get('family','-')} | playbook={top.get('playbook','-')} | target_monthly={top['target_monthly']*100:.2f}% | gap_to_7.6={top['gap_to_floor']*100:.2f}%")
    lines.append("- 这轮不动 runtime；只做主线加速器快刷 + ETH reclaim/squeeze 扩圈 + SOL 多空对称快刷 + BTC event/reclaim/dual 保路。")

    payload = {
        "mode": "regime_playbook_accel_frontier",
        "target_monthly_min": TARGET_MONTHLY_MIN,
        "target_monthly_max": TARGET_MONTHLY_MAX,
        "bug_guard": True,
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
    ap = argparse.ArgumentParser(description="Stage157 regime playbook accel frontier")
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

    ref_row = _compat_mainline_ref_row(root, cfg, data, initial_equity, full_start, full_end)
    main_map = {
        str(r.get("name")): _compat_ensure_mainline_schema(copy.deepcopy(r), ref_row=ref_row, initial_equity=initial_equity, full_end=full_end)
        for r in main_rows
    }
    scanned_main: list[str] = []
    for item in _new_mainline_items():
        print(f"[stage157] main {item['name']}", flush=True)
        row = s90._run_mainline(root, cfg, data, item, initial_equity, full_start, full_end)
        row = _compat_ensure_mainline_schema(row, ref_row=ref_row, initial_equity=initial_equity, full_end=full_end)
        main_map[str(row.get("name"))] = row
        scanned_main.append(str(row.get("name")))
    main_rows = _finalize_rows(list(main_map.values()), branch=False)

    branch_map = {str(r.get("name")): copy.deepcopy(r) for r in branch_rows}
    scanned_branch: list[str] = []
    for item in _new_branch_items():
        print(f"[stage157] branch {item['name']}", flush=True)
        row = s136._run_branch(root, cfg, item, initial_equity)
        row["walkforward"] = s82._wf_result(row, initial_equity, s78.RECENT_START, row["full_end"])
        row["dominant_gate"] = s90._dominant_gate(row, branch=True)
        branch_map[str(row.get("name"))] = row
        scanned_branch.append(str(row.get("name")))
    branch_rows = _finalize_rows(list(branch_map.values()), branch=True)

    main_txt = raw / "stage90_mainline_event_alpha_matrix_latest.txt"
    main_json = raw / "stage90_mainline_event_alpha_matrix_latest.json"
    branch_txt = raw / "stage91_branch_event_alpha_matrix_latest.txt"
    branch_json = raw / "stage91_branch_event_alpha_matrix_latest.json"
    s90._write_mainline(main_txt, main_json, main_rows)
    s90._write_branch(branch_txt, branch_json, branch_rows)

    active_map = {sym: s152._active_asset_name(branch_json, sym) for sym in ["BTC", "ETH", "SOL"]}

    frontier_txt = raw / "stage157_regime_playbook_accel_frontier_latest.txt"
    frontier_json = raw / "stage157_regime_playbook_accel_frontier_latest.json"
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
        "mode": "regime_playbook_accel_frontier",
        "bug_guard": True,
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
    manifest_path = raw / "stage157_regime_playbook_accel_frontier_manifest_latest.json"
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
