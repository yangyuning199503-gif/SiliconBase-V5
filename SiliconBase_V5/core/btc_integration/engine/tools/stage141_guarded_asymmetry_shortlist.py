from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import research_config_baseline as rcb
from tools import stage46_aggressive_lab as s46
from tools import stage78_branch_dual_window_lab as s78
from tools import stage81_mainline_walkforward_lab as s81
from tools import stage82_branch_walkforward_lab as s82
from tools import stage88_strategy_fusion_walkforward as s88
from tools import stage90_event_alpha_matrix as s90
from tools import stage136_regime_plateau_frontier as s136
from tools import stage138_anchor_guard_refresh as s138
from tools import stage140_regime_switch_risk_ladder as s140

TARGET_MONTHLY_MIN = s136.TARGET_MONTHLY_MIN
TARGET_MONTHLY_MAX = s136.TARGET_MONTHLY_MAX
PACKS = s136.PACKS

MAIN_HISTORY_JSON = [
    "stage138_anchor_guard_refresh_latest.json",
    "stage136_regime_plateau_frontier_latest.json",
]
BRANCH_HISTORY_JSON = [
    "stage140_regime_switch_risk_ladder_latest.json",
    "stage139_microstructure_confluence_frontier_latest.json",
    "stage138_anchor_guard_refresh_latest.json",
    "stage136_regime_plateau_frontier_latest.json",
]
HISTORY_TEXT = [
    "stage120_event_window_frontier_latest.txt",
]

_METRIC_RE = re.compile(
    r"^- (?:(?P<sym>[A-Z]+) \| (?P<fam>[a-z]+) \| )?(?P<name>[^:]+): "
    r"dominant_gate=(?P<gate>[^ ]+) \((?P<decision>[^)]+)\) \| "
    r"6年 收益=(?P<full_ret>[-+0-9.]+)% 月化=(?P<full_monthly>[-+0-9.]+)% 回撤=(?P<full_dd>[-+0-9.]+)% 交易=(?P<full_trades>\d+) PF=(?P<full_pf>[-+0-9.]+) \| "
    r"近2年 收益=(?P<recent_ret>[-+0-9.]+)% 月化=(?P<recent_monthly>[-+0-9.]+)% 回撤=(?P<recent_dd>[-+0-9.]+)% 交易=(?P<recent_trades>\d+) PF=(?P<recent_pf>[-+0-9.]+) \| "
    r"WF样本外 收益=(?P<wf_ret>[-+0-9.]+)% 月化=(?P<wf_monthly>[-+0-9.]+)% 回撤=(?P<wf_dd>[-+0-9.]+)% 交易=(?P<wf_trades>\d+) PF=(?P<wf_pf>[-+0-9.]+) \| "
    r"正收益折=(?P<pos>\d+)/(?P<tot>\d+) \| alpha_score=(?P<score>[-+0-9.]+)$"
)


def _pct(x: str | float | int | None) -> float:
    return s88._safe_float(x) / 100.0


def _load_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    rows = payload.get("rows")
    return list(rows) if isinstance(rows, list) else []



def _parse_frontier_text(path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    main: dict[str, dict[str, Any]] = {}
    branch: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return main, branch
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        m = _METRIC_RE.match(line)
        if not m:
            continue
        gd = m.groupdict()
        payload = {
            "name": gd["name"],
            "symbol": (gd.get("sym") or "").lower() or None,
            "family": gd.get("fam") or None,
            "track": s136._dominant_track(gd["gate"]),
            "dominant_gate": gd["gate"],
            "decision": gd["decision"],
            "frontier_score": s88._safe_float(gd["score"]),
            "target_monthly": 0.0,
            "full_ret": _pct(gd["full_ret"]),
            "full_monthly": _pct(gd["full_monthly"]),
            "full_trades": int(gd["full_trades"]),
            "full_pf": s88._safe_float(gd["full_pf"]),
            "recent_ret": _pct(gd["recent_ret"]),
            "recent_monthly": _pct(gd["recent_monthly"]),
            "recent_trades": int(gd["recent_trades"]),
            "recent_pf": s88._safe_float(gd["recent_pf"]),
            "wf_ret": _pct(gd["wf_ret"]),
            "wf_monthly": _pct(gd["wf_monthly"]),
            "wf_trades": int(gd["wf_trades"]),
            "wf_pf": s88._safe_float(gd["wf_pf"]),
            "wf_dd": _pct(gd["wf_dd"]),
            "positive_folds": int(gd["pos"]),
            "total_folds": int(gd["tot"]),
            "event_fold_share": 0.0 if gd["gate"] == "base_message_overlay" else 1.0,
        }
        target = main if not gd.get("sym") else branch
        target[payload["name"]] = payload
    return main, branch



def _history_maps(raw: Path, *, branch: bool) -> list[dict[str, dict[str, Any]]]:
    out: list[dict[str, dict[str, Any]]] = []
    json_files = BRANCH_HISTORY_JSON if branch else MAIN_HISTORY_JSON
    key = "branch" if branch else "mainline"
    for fname in json_files:
        p = raw / fname
        if not p.exists():
            continue
        try:
            payload = s138._load_json(p)
            mp = s138._frontier_map(payload, key)
        except Exception:
            continue
        if mp:
            out.append(mp)
    for fname in HISTORY_TEXT:
        p = raw / fname
        mp_main, mp_branch = _parse_frontier_text(p)
        mp = mp_branch if branch else mp_main
        if mp:
            out.append(mp)
    return out



def _current_stats(row: dict[str, Any]) -> tuple[int, int, int, float, float, float]:
    full = row.get("full_metrics") or {}
    dom = row.get("dominant_gate") or {}
    recent = dom.get("recent_metrics") or {}
    wf = (row.get("walkforward") or {}).get("metrics") or {}
    return (
        int(full.get("trades", 0) or 0),
        int(recent.get("trades", 0) or 0),
        int(wf.get("trades", 0) or 0),
        float((row.get("walkforward") or {}).get("total_folds", 0) or 0.0),
        s88._safe_float(full.get("ret")),
        s136._target_monthly(row, branch=bool(row.get("symbol"))),
    )



def _is_collapse_anomaly(row: dict[str, Any], prev: dict[str, Any] | None) -> bool:
    if not isinstance(prev, dict):
        return False
    full_trades, recent_trades, wf_trades, total_folds, full_ret, month = _current_stats(row)
    prev_recent = int(prev.get("recent_trades", 0) or 0)
    prev_wf = int(prev.get("wf_trades", 0) or 0)
    prev_full = int(prev.get("full_trades", 0) or 0)
    prev_full_ret = s88._safe_float(prev.get("full_ret"))
    prev_month = s88._safe_float(prev.get("target_monthly"))

    zero_anomaly = s138._is_zero_anomaly(row, prev)
    severe_sample_collapse = bool(
        prev_full >= 30
        and full_trades <= max(8, int(prev_full * 0.25))
        and recent_trades <= max(2, int(prev_recent * 0.25))
        and wf_trades <= max(2, int(prev_wf * 0.25))
    )
    sign_flip_collapse = bool(
        prev_full_ret > 0.10
        and full_ret < 0.0
        and full_trades <= max(10, int(prev_full * 0.55))
    )
    month_collapse = bool(
        prev_month >= 0.010
        and month <= max(0.0, prev_month * 0.18)
        and recent_trades <= max(2, int(prev_recent * 0.35))
        and wf_trades <= max(2, int(prev_wf * 0.35))
    )
    return bool((prev_recent >= 5 or prev_wf >= 5) and total_folds >= 1 and (zero_anomaly or severe_sample_collapse or sign_flip_collapse or month_collapse))



def _repair_rows(rows: list[dict[str, Any]], sources: list[dict[str, dict[str, Any]]]) -> tuple[list[dict[str, Any]], list[str]]:
    fixed: list[dict[str, Any]] = []
    repaired: list[str] = []
    for row in rows:
        name = str(row.get("name") or "")
        prev = None
        for mp in sources:
            cand = mp.get(name)
            if isinstance(cand, dict) and (int(cand.get("recent_trades", 0) or 0) > 0 or int(cand.get("wf_trades", 0) or 0) > 0):
                prev = cand
                break
        if _is_collapse_anomaly(row, prev):
            patched = s138._patch_row_from_payload(row, prev)
            patched["guard_source"] = "stage141_history_guard"
            fixed.append(patched)
            repaired.append(name)
        else:
            fixed.append(copy.deepcopy(row))
    return fixed, repaired



def _with_meta(item: dict[str, Any], *, track: str, branch: bool, anchor_name: str | None = None) -> dict[str, Any]:
    out = s136._with_meta(item, track=track, branch=branch)
    out.setdefault("meta", {})
    out["meta"]["anchor_name"] = str(anchor_name or out.get("name") or "")
    out["meta"].setdefault("risk_scale", 1.0)
    return out



def _new_mainline_items() -> list[dict[str, Any]]:
    item_map = {str(item.get("name")): item for item in s88._mainline_items()}
    base_live = item_map.get("mainline_live_base")
    out: list[dict[str, Any]] = []
    if base_live is None:
        return out
    out.append(
        _with_meta(
            s88._make_mainline_variant(
                base_live,
                name="mainline_live_dynlev_fix8_lock16_cd4_rr030",
                note="主线快一档：不改主骨架，只压 cooldown 和 trailing giveback，专看近2年/WF 是否同步提频。",
                patch={
                    "strategy_params.cooldown_bars": 4,
                    "portfolio.dynamic_leverage.enabled": True,
                    "portfolio.dynamic_leverage.min": 4.0,
                    "portfolio.dynamic_leverage.max": 8.0,
                    "portfolio.dynamic_leverage.adx_low": 17.0,
                    "portfolio.dynamic_leverage.adx_high": 34.0,
                    "money_management.mode": "fixed",
                    "money_management.capital_slices": 8,
                    "money_management.stake_mode": "dynamic_equity",
                    "money_management.stake_min_usd": 8500,
                    "money_management.stake_max_usd": 13500,
                    "money_management.stop_loss_pct": 0.17,
                    "money_management.take_profit_pct": 1.30,
                    "money_management.trailing_profit.enabled": True,
                    "money_management.trailing_profit.activation_pnl_pct": 0.50,
                    "money_management.trailing_profit.giveback_ratio": 0.30,
                    "money_management.trailing_profit.min_lock_pnl_pct": 0.12,
                },
            ),
            track="drift",
            branch=False,
            anchor_name="mainline_live_dynlev_fix8_lock18",
        )
    )
    return out



def _new_branch_items() -> list[dict[str, Any]]:
    item_map = {str(item.get("name")): item for item in s88._branch_items()}
    out: list[dict[str, Any]] = []

    def add(item: dict[str, Any] | None, *, track: str, anchor_name: str | None = None) -> None:
        if item is not None:
            out.append(_with_meta(item, track=track, branch=True, anchor_name=anchor_name or str(item.get("name"))))

    eth_long = item_map.get("eth_breakout_long_follow_lb16_atr050_adx22_s034")
    eth_short = item_map.get("eth_retest_short_trend_lb20_atr060_adx24_s068")
    btc_long = item_map.get("btc_breakout_long_event_lb20_atr060_adx24_s050")
    btc_dual = item_map.get("btc_dual_fast_trend_dynlev_fix8")

    if eth_long is not None:
        add(
            s88._make_variant(
                eth_long,
                name="eth_reclaim_long_lb11_atr043_adx16_s044",
                note="ETH 回收 long：事件冲击后等第二脚确认，不追第一根。",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 11,
                    "strategy_params.breakout_atr_buffer": 0.43,
                    "strategy_params.cooldown_bars": 4,
                    "filters.adx_floor": 16,
                    "money_management.stake_scale.eth_long": 0.44,
                },
            ),
            track="reclaim",
            anchor_name="eth_event_drift_long_lb10_atr044_adx16_s046",
        )
        add(
            s88._make_variant(
                eth_long,
                name="eth_drift_hold_long_lb13_atr047_adx18_s040",
                note="ETH 漂移慢一档：给扩散更多确认，减少首波噪声。",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 13,
                    "strategy_params.breakout_atr_buffer": 0.47,
                    "strategy_params.cooldown_bars": 4,
                    "filters.adx_floor": 18,
                    "money_management.stake_scale.eth_long": 0.40,
                },
            ),
            track="drift",
            anchor_name="eth_event_drift_long_lb10_atr044_adx16_s046",
        )
        add(
            s88._make_variant(
                eth_long,
                name="eth_squeeze_follow_long_lb11_atr044_adx17_s044",
                note="ETH 挤仓延续中速版：降低首段噪声，保留事件后连续性。",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 11,
                    "strategy_params.breakout_atr_buffer": 0.44,
                    "strategy_params.cooldown_bars": 3,
                    "filters.adx_floor": 17,
                    "money_management.stake_scale.eth_long": 0.44,
                },
            ),
            track="squeeze",
            anchor_name="eth_squeeze_follow_long_lb10_atr042_adx16_s046",
        )

    if eth_short is not None:
        add(
            s88._make_variant(
                eth_short,
                name="eth_panic_short_confirm_lb18_atr056_adx21_s070",
                note="ETH panic 空腿确认版：只在反抽失败时接空。",
                family="short",
                patch={
                    "strategy_params.breakout_lookback": 18,
                    "strategy_params.breakout_atr_buffer": 0.56,
                    "strategy_params.cooldown_bars": 6,
                    "filters.adx_floor": 21,
                    "money_management.stake_scale.eth_short": 0.70,
                },
            ),
            track="reclaim",
            anchor_name="eth_retest_short_trend_lb20_atr060_adx24_s068",
        )

    if btc_long is not None:
        add(
            s88._make_variant(
                btc_long,
                name="btc_reclaim_long_lb18_atr054_adx22_s054",
                note="BTC 恐慌后回收 long：先等失衡修复，不追第一脚。",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 18,
                    "filters.btc_breakout_atr_buffer": 0.54,
                    "strategy_params.cooldown_bars": 6,
                    "filters.btc_adx_floor": 22,
                    "money_management.stake_scale.btc_long": 0.54,
                },
            ),
            track="reclaim",
            anchor_name="btc_breakout_long_event_lb20_atr060_adx24_s050",
        )
        add(
            s88._make_variant(
                btc_long,
                name="btc_squeeze_follow_long_lb16_atr050_adx20_s058",
                note="BTC 挤仓延续中速版：事件/流向共振后跟第二段。",
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
            anchor_name="btc_breakout_long_event_lb20_atr060_adx24_s050",
        )

    if btc_dual is not None:
        add(
            s88._make_variant(
                btc_dual,
                name="btc_dual_squeeze_dynlev_fix10",
                note="BTC 双向结构快一档：保留 dual，但把切片和 trailing 再压一档。",
                family="dual",
                patch={
                    "portfolio.dynamic_leverage.enabled": True,
                    "portfolio.dynamic_leverage.min": 4.0,
                    "portfolio.dynamic_leverage.max": 10.0,
                    "portfolio.dynamic_leverage.adx_low": 16.0,
                    "portfolio.dynamic_leverage.adx_high": 34.0,
                    "money_management.capital_slices": 10,
                    "money_management.take_profit_pct": 1.15,
                    "money_management.trailing_profit.activation_pnl_pct": 0.48,
                    "money_management.trailing_profit.giveback_ratio": 0.32,
                    "money_management.trailing_profit.min_lock_pnl_pct": 0.12,
                    "money_management.stake_scale.btc_long": 0.54,
                    "money_management.stake_scale.btc_short": 0.66,
                },
            ),
            track="squeeze",
            anchor_name="btc_dual_fast_trend_dynlev_fix8",
        )

    add(item_map.get("sol_long_core_soft_lb20_zone025_s042"), track="drift", anchor_name="sol_long_core_soft_lb20_zone025_s042")
    add(item_map.get("sol_fast_trend_short_aggr_lb16_atr055_adx22_s076"), track="reclaim", anchor_name="sol_fast_trend_short_aggr_lb16_atr055_adx22_s076")
    return out



def _frontier_score(row: dict[str, Any], rows: list[dict[str, Any]], *, branch: bool) -> float:
    base = s140._frontier_score(row, rows, branch=branch)
    dom = row.get("dominant_gate", {}) or {}
    recent = dom.get("recent_metrics", {}) or {}
    wf = (row.get("walkforward") or {}).get("metrics", {}) or {}
    track = str((row.get("meta") or {}).get("track") or "base")
    month = s136._target_monthly(row, branch=branch)
    recent_trades = int(recent.get("trades", 0) or 0)
    wf_trades = int(wf.get("trades", 0) or 0)
    recent_pf = s88._safe_float(recent.get("pf"))
    wf_pf = s88._safe_float(wf.get("pf"))
    plateau = s88._safe_float((row.get("plateau") or {}).get("plateau"))

    bonus = 0.0
    penalty = 0.0
    if not branch:
        if month >= 0.020 and recent_trades >= 26 and wf_trades >= 10 and recent_pf >= 1.35 and wf_pf >= 1.10:
            bonus += 18.0
        if "cd4" in str(row.get("name") or "") and recent_trades >= 18 and wf_trades >= 8 and month > 0.015:
            bonus += 6.0
        if month < 0.010:
            penalty += 16.0
        return float(base + bonus - penalty)

    sym = str(row.get("symbol") or "").lower()
    fam = str(row.get("family") or "").lower()
    if sym == "eth" and fam == "long" and track in {"squeeze", "drift", "reclaim"}:
        if recent_trades >= 24 and wf_trades >= 16 and recent_pf >= 2.0 and wf_pf >= 1.5:
            bonus += 22.0
        if month >= 0.017 and plateau >= 0.15:
            bonus += 12.0
    if sym == "eth" and fam == "short" and track == "reclaim" and wf_trades >= 10 and wf_pf >= 1.10:
        bonus += 8.0
    if sym == "btc" and fam == "long" and track in {"drift", "squeeze", "reclaim"} and recent_trades >= 12 and wf_trades >= 10 and recent_pf >= 1.25 and wf_pf >= 1.10:
        bonus += 12.0
    if sym == "btc" and fam == "dual" and recent_trades >= 6 and wf_trades >= 6 and recent_pf >= 1.10 and wf_pf >= 1.05:
        bonus += 8.0
    if sym == "sol" and recent_trades >= 8 and wf_trades >= 5 and recent_pf >= 1.05 and wf_pf >= 0.95:
        bonus += 8.0
    if month < 0.006 and track in {"reclaim", "squeeze", "drift"}:
        penalty += 8.0
    return float(base + bonus - penalty)



def _finalize_rows(rows: list[dict[str, Any]], *, branch: bool) -> list[dict[str, Any]]:
    for row in rows:
        row["plateau"] = s136._plateau_summary(row, rows, branch=branch)
    for row in rows:
        row["alpha_score"] = _frontier_score(row, rows, branch=branch)
        row["decision"] = s136._frontier_label(row, branch=branch)
    rows.sort(key=lambda r: float(r.get("alpha_score", 0.0)), reverse=True)
    return rows



def _load_stage_state(raw: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], list[str]]:
    main_rows = _load_rows(raw / "stage90_mainline_event_alpha_matrix_latest.json")
    branch_rows = _load_rows(raw / "stage91_branch_event_alpha_matrix_latest.json")
    if not main_rows or not branch_rows:
        raise SystemExit("缺少当前 stage90/stage91 json")
    fixed_main, repaired_main = _repair_rows(main_rows, _history_maps(raw, branch=False))
    fixed_branch, repaired_branch = _repair_rows(branch_rows, _history_maps(raw, branch=True))
    return fixed_main, fixed_branch, repaired_main, repaired_branch



def _write_report(path_txt: Path, path_json: Path, main_rows: list[dict[str, Any]], branch_rows: list[dict[str, Any]], repaired_main: list[str], repaired_branch: list[str], scanned_main: list[str], scanned_branch: list[str]) -> None:
    main_payload = [s136._payload_row(r, branch=False) for r in main_rows]
    branch_payload = [s136._payload_row(r, branch=True) for r in branch_rows]
    lines: list[str] = []
    lines.append("Stage141 守卫 + 非对称 shortlist 前沿")
    lines.append("原则：先把主线坏统计彻底挡住，再围绕 ETH/BTC/SOL 小样本创新腿快刷；6年只作软约束，近2年 + WF 继续硬过滤。")
    lines.append(f"目标区间：{TARGET_MONTHLY_MIN*100:.1f}% - {TARGET_MONTHLY_MAX*100:.1f}% / 月")
    lines.append("")
    lines.append(f"- 修复对象: main={len(repaired_main)} | branch={len(repaired_branch)}")
    if repaired_main:
        lines.append(f"- 主线回退: {', '.join(repaired_main)}")
    if repaired_branch:
        lines.append(f"- 分支回退: {', '.join(repaired_branch)}")
    lines.append(f"- 新刷主线候选: {', '.join(scanned_main) if scanned_main else '-'}")
    lines.append(f"- 新刷分支候选: {', '.join(scanned_branch) if scanned_branch else '-'}")
    lines.append("")
    lines.append("=== 主线 ===")
    for row in main_payload:
        lines.append(
            f"- {row['name']}: track={row['track']} | dom={row['dominant_track']} | target_monthly={row['target_monthly']*100:.2f}% | 近2年={row['recent_monthly']*100:.2f}%/{row['recent_trades']}笔/PF{row['recent_pf']:.3f} | WF={row['wf_monthly']*100:.2f}%/{row['wf_trades']}笔/PF{row['wf_pf']:.3f} | decision={row['decision']}"
        )
    lines.append("")
    lines.append("=== 分支（BTC/ETH/SOL） ===")
    for row in branch_payload:
        sym = row.get("symbol") or "-"
        fam = row.get("family") or "-"
        lines.append(
            f"- {sym}|{fam}|{row['name']}: track={row['track']} | dom={row['dominant_track']} | target_monthly={row['target_monthly']*100:.2f}% | 近2年={row['recent_monthly']*100:.2f}%/{row['recent_trades']}笔/PF{row['recent_pf']:.3f} | WF={row['wf_monthly']*100:.2f}%/{row['wf_trades']}笔/PF{row['wf_pf']:.3f} | decision={row['decision']}"
        )
    lines.append("")
    lines.append("=== 结论 ===")
    if main_payload:
        top = main_payload[0]
        lines.append(f"- 主线当前第一名: {top['name']} | target_monthly={top['target_monthly']*100:.2f}% | gap_to_7.6={top['gap_to_floor']*100:.2f}%")
    if branch_payload:
        top = branch_payload[0]
        lines.append(f"- 分支当前第一名: {top['name']} | target_monthly={top['target_monthly']*100:.2f}% | gap_to_7.6={top['gap_to_floor']*100:.2f}%")
    lines.append("- 这轮先不重跑主线大矩阵；先把主线统计稳定住，再用 ETH/BTC/SOL shortlist 快筛创新腿。\n")

    path_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    path_json.write_text(
        json.dumps(
            {
                "mode": "guarded_asymmetry_shortlist",
                "target_monthly_min": TARGET_MONTHLY_MIN,
                "target_monthly_max": TARGET_MONTHLY_MAX,
                "repaired_main": repaired_main,
                "repaired_branch": repaired_branch,
                "new_mainline_candidates": scanned_main,
                "new_branch_candidates": scanned_branch,
                "packs": [x[0] for x in PACKS],
                "mainline": main_payload,
                "branch": branch_payload,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )



def _mirror_to_workspace(root: Path, files: Iterable[Path]) -> None:
    ws_raw = root / ".branch_shortwave_demo" / "workspace" / "reports" / "research_raw"
    if not ws_raw.parent.exists():
        return
    ws_raw.mkdir(parents=True, exist_ok=True)
    for p in files:
        if p.exists() and p.is_file():
            (ws_raw / p.name).write_bytes(p.read_bytes())



def main() -> None:
    ap = argparse.ArgumentParser(description="Stage141 guarded asymmetry shortlist frontier")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    raw = root / "reports" / "research_raw"
    raw.mkdir(parents=True, exist_ok=True)

    main_rows, branch_rows, repaired_main, repaired_branch = _load_stage_state(raw)

    cfg = rcb.load_research_base_config(root)
    initial_equity = float(cfg.get("portfolio", {}).get("initial_equity", 100000.0))

    scanned_main: list[str] = []
    main_map = {str(r.get("name")): copy.deepcopy(r) for r in main_rows}
    mainline_items_all = {str(item.get("name")): item for item in s88._mainline_items()}
    ref_item = mainline_items_all.get("mainline_live_base")
    data = None
    full_start = full_end = None
    ref_row = None
    if ref_item is not None and _new_mainline_items():
        data = s46._load_portfolio_data(root, cfg)
        from tools import stage77_mainline_dual_window_lab as s77
        full_start, full_end = s77._window_bounds_from_data(data)
        ref_row = s136._run_mainline(root, cfg, data, _with_meta(ref_item, track="base", branch=False), initial_equity, full_start, full_end)
        for item in _new_mainline_items():
            print(f"[stage141] mainline {item['name']}", flush=True)
            row = s136._run_mainline(root, cfg, data, item, initial_equity, full_start, full_end)
            row["walkforward"] = s81._wf_result(row, ref_row, initial_equity, s81.RECENT_START, full_end)
            row["dominant_gate"] = s90._dominant_gate(row, branch=False)
            main_map[str(row.get("name"))] = row
            scanned_main.append(str(row.get("name")))

    scanned_branch: list[str] = []
    branch_map = {str(r.get("name")): copy.deepcopy(r) for r in branch_rows}
    for item in _new_branch_items():
        print(f"[stage141] branch {item['name']}", flush=True)
        row = s136._run_branch(root, cfg, item, initial_equity)
        row["walkforward"] = s82._wf_result(row, initial_equity, s78.RECENT_START, row["full_end"])
        row["dominant_gate"] = s90._dominant_gate(row, branch=True)
        branch_map[str(row.get("name"))] = row
        scanned_branch.append(str(row.get("name")))

    main_rows = _finalize_rows(list(main_map.values()), branch=False)
    branch_rows = _finalize_rows(list(branch_map.values()), branch=True)

    main_txt = raw / "stage90_mainline_event_alpha_matrix_latest.txt"
    main_json = raw / "stage90_mainline_event_alpha_matrix_latest.json"
    branch_txt = raw / "stage91_branch_event_alpha_matrix_latest.txt"
    branch_json = raw / "stage91_branch_event_alpha_matrix_latest.json"
    s90._write_mainline(main_txt, main_json, main_rows)
    s90._write_branch(branch_txt, branch_json, branch_rows)

    frontier_txt = raw / "stage141_guarded_asymmetry_shortlist_latest.txt"
    frontier_json = raw / "stage141_guarded_asymmetry_shortlist_latest.json"
    _write_report(frontier_txt, frontier_json, main_rows, branch_rows, repaired_main, repaired_branch, scanned_main, scanned_branch)

    manifest = {
        "mode": "guarded_asymmetry_shortlist",
        "repaired_main": repaired_main,
        "repaired_branch": repaired_branch,
        "new_mainline_candidates": scanned_main,
        "new_branch_candidates": scanned_branch,
        "outputs": {
            "stage90_txt": str(main_txt),
            "stage90_json": str(main_json),
            "stage91_txt": str(branch_txt),
            "stage91_json": str(branch_json),
            "frontier_txt": str(frontier_txt),
            "frontier_json": str(frontier_json),
        },
    }
    manifest_path = raw / "stage141_guarded_asymmetry_shortlist_manifest_latest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    _mirror_to_workspace(root, [main_txt, main_json, branch_txt, branch_json, frontier_txt, frontier_json, manifest_path])

    print(main_txt)
    print(main_json)
    print(branch_txt)
    print(branch_json)
    print(frontier_txt)
    print(frontier_json)
    print(manifest_path)


if __name__ == "__main__":
    main()
