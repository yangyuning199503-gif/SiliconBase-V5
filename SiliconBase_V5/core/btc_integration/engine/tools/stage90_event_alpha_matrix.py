from __future__ import annotations

import argparse
import copy
import json
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


try:
    from tools import research_config_baseline as rcb
    from tools import stage46_aggressive_lab as s46
    from tools import stage59_structural_lab as s59
    from tools import stage77_mainline_dual_window_lab as s77
    from tools import stage78_branch_dual_window_lab as s78
    from tools import stage81_mainline_walkforward_lab as s81
    from tools import stage82_branch_walkforward_lab as s82
    from tools import stage88_strategy_fusion_walkforward as s88
except Exception as exc:
    raise SystemExit("缺少 stage46/59/77/78/81/82/88 模块，请先保留此前补丁。") from exc


def _pack_or(*funcs: Callable[[pd.DataFrame], pd.Series]) -> Callable[[pd.DataFrame], pd.Series]:
    def _fn(df: pd.DataFrame) -> pd.Series:
        if not funcs:
            return pd.Series(False, index=df.index)
        out = funcs[0](df)
        for fn in funcs[1:]:
            out = out | fn(df)
        return out
    return _fn


PACKS: list[tuple[str, Callable[[pd.DataFrame], pd.Series], str]] = [
    ("base_message_overlay", s88._gate_none, "只保留消息面 overlay，不加开仓条件"),
    ("event_breakout_alpha", _pack_or(s88._gate_major_event_impulse, s88._gate_post_event_drift), "重大消息的瞬时冲击 + 扩散漂移，允许直接开仓"),
    ("event_pressure_alpha", _pack_or(s88._gate_event_pressure_continuation, s88._gate_post_event_drift), "重大消息后的持续压制/延续，不要求第一根直接追"),
    ("event_reclaim_alpha", _pack_or(s88._gate_event_sweep_bridge, s88._gate_post_event_drift), "重大消息后先扫再收回关键位的二段入场"),
    ("neutral_sweep_alpha", _pack_or(s88._gate_neutral_revert, s88._gate_liquidity_sweep_reclaim), "无重大消息时的插针回归 + 扫损回收"),
    ("crowding_sweep_alpha", _pack_or(s88._gate_crowding_reversal, s88._gate_liquidity_sweep_reclaim), "拥挤反转 + 流动性扫损反转"),
    ("event_crowding_alpha", _pack_or(s88._gate_major_event_impulse, s88._gate_post_event_drift, s88._gate_crowding_reversal), "重大消息方向 + 拥挤确认"),
    ("fusion_alpha_all", s88._gate_fusion_open, "趋势/事件/拥挤/扫损的全融合开仓层"),
]


def _dominant_gate(row: dict[str, Any], branch: bool) -> dict[str, Any]:
    gate_mix = Counter({str(k): int(v) for k, v in (row.get("walkforward", {}).get("gate_mix", {}) or {}).items()})
    gate_rows = row.get("gate_rows", [])

    def _pref_score(g: dict[str, Any]) -> float:
        recent = g.get("recent_metrics", {}) or {}
        full = row.get("full_metrics", {}) or {}
        trades = int(recent.get("trades", 0) or 0)
        target = BRANCH_GATE_TARGET if branch else MAINLINE_GATE_TARGET
        pf_cap = 4.0 if branch else 4.5
        pf_adj = _pf_for_score(recent.get("pf"), trades, target, pf_cap)
        ret_adj = _ret_for_score(recent.get("ret"), trades, target)
        dd_adj = _dd_for_score(recent.get("maxdd"), trades, target, 0.06 if branch else 0.08)
        trade_bonus = min(trades, target * 2) * (1.8 if branch else 1.6)
        full_bonus = _safe_full_pf(full) * (8.0 if branch else 10.0) + _safe_full_ret(full) * (3.0 if branch else 4.0)
        sample_penalty = max(0, target - trades) * (18.0 if branch else 20.0)
        return pf_adj * (132.0 if branch else 138.0) + ret_adj * (96.0 if branch else 90.0) - dd_adj * (74.0 if branch else 68.0) + trade_bonus + full_bonus - sample_penalty

    def _key(g: dict[str, Any]) -> tuple[float, int, int, int]:
        name = str(g.get("gate_name", "-"))
        freq = gate_mix.get(name, 0)
        recent = g.get("recent_metrics", {}) or {}
        trades = int(recent.get("trades", 0) or 0)
        pref = _pref_score(g)
        nonbase = 1 if name != "base_message_overlay" else 0
        quality = pref + min(freq, 2) * 6.0 + nonbase * 4.0
        return (quality, trades, freq, nonbase)

    if not gate_rows:
        return {}
    return max(gate_rows, key=_key)


def _event_fold_share(wf: dict[str, Any]) -> float:
    total = max(int(wf.get("total_folds", 0) or 0), 1)
    mix = wf.get("gate_mix", {}) or {}
    base_ct = int(mix.get("base_message_overlay", 0) or 0)
    return max(0.0, min(1.0, (total - base_ct) / total))


MAINLINE_RECENT_TARGET = 18
MAINLINE_WF_TARGET = 8
BRANCH_RECENT_TARGET = 12
BRANCH_WF_TARGET = 6
MAINLINE_GATE_TARGET = 12
BRANCH_GATE_TARGET = 8


def _trade_weight(trades: Any, target: int) -> float:
    t = max(int(trades or 0), 0)
    if t <= 0:
        return 0.0
    if target <= 0:
        return 1.0
    return max(0.0, min(1.0, t / float(target)))


def _pf_for_score(pf: Any, trades: Any, target: int, cap: float) -> float:
    t = max(int(trades or 0), 0)
    if t <= 0:
        return 0.0
    raw = max(0.0, s88._safe_float(pf))
    clipped = min(raw, cap)
    w = _trade_weight(t, target)
    return 1.0 + (clipped - 1.0) * w


def _ret_for_score(ret: Any, trades: Any, target: int) -> float:
    return s88._safe_float(ret) * _trade_weight(trades, target)


def _dd_for_score(maxdd: Any, trades: Any, target: int, floor_dd: float) -> float:
    base = abs(s88._safe_float(maxdd))
    w = _trade_weight(trades, target)
    return max(base, (1.0 - w) * floor_dd)


def _safe_full_pf(full_m: dict[str, Any]) -> float:
    return min(max(0.0, s88._safe_float((full_m or {}).get("pf"))), 3.0)


def _safe_full_ret(full_m: dict[str, Any]) -> float:
    return s88._safe_float((full_m or {}).get("ret"))


def _sample_penalty(trades: int, target: int, per_trade: float) -> float:
    return max(0, int(target) - int(trades)) * per_trade


def _mainline_alpha_score(row: dict[str, Any]) -> float:
    dom = row["dominant_gate"]
    wf = row["walkforward"]
    recent_m = dom.get("recent_metrics", {}) or {}
    wf_m = wf.get("metrics", {}) or {}
    full_m = row.get("full_metrics", {}) or {}
    recent_trades = int(recent_m.get("trades", 0) or 0)
    wf_trades = int(wf_m.get("trades", 0) or 0)
    recent_pf = _pf_for_score(recent_m.get("pf"), recent_trades, MAINLINE_RECENT_TARGET, 4.5)
    wf_pf = _pf_for_score(wf_m.get("pf"), wf_trades, MAINLINE_WF_TARGET, 4.0)
    recent_ret = _ret_for_score(recent_m.get("ret"), recent_trades, MAINLINE_RECENT_TARGET)
    wf_ret = _ret_for_score(wf_m.get("ret"), wf_trades, MAINLINE_WF_TARGET)
    recent_dd = _dd_for_score(recent_m.get("maxdd"), recent_trades, MAINLINE_RECENT_TARGET, 0.08)
    wf_dd = _dd_for_score(wf_m.get("maxdd"), wf_trades, MAINLINE_WF_TARGET, 0.10)
    pf_floor = min(max(0.0, s88._safe_float(wf.get("pf_floor", 0.0))), 2.5)
    dd_ceiling = max(0.0, s88._safe_float(wf.get("dd_ceiling", 0.0)))
    return float(
        recent_pf * 168.0
        + recent_ret * 112.0
        - recent_dd * 78.0
        + min(recent_trades, MAINLINE_RECENT_TARGET * 2) * 1.6
        + wf_pf * 142.0
        + wf_ret * 90.0
        - wf_dd * 96.0
        + min(wf_trades, MAINLINE_WF_TARGET * 3) * 2.2
        + int(wf.get("positive_folds", 0) or 0) * 12.0
        + pf_floor * 18.0
        - dd_ceiling * 18.0
        + _safe_full_pf(full_m) * 10.0
        + _safe_full_ret(full_m) * 4.0
        + _event_fold_share(wf) * 24.0
        - _sample_penalty(recent_trades, MAINLINE_RECENT_TARGET, 8.0)
        - _sample_penalty(wf_trades, MAINLINE_WF_TARGET, 10.0)
    )


def _branch_alpha_score(row: dict[str, Any]) -> float:
    dom = row["dominant_gate"]
    wf = row["walkforward"]
    recent_m = dom.get("recent_metrics", {}) or {}
    wf_m = wf.get("metrics", {}) or {}
    full_m = row.get("full_metrics", {}) or {}
    recent_trades = int(recent_m.get("trades", 0) or 0)
    wf_trades = int(wf_m.get("trades", 0) or 0)
    recent_pf = _pf_for_score(recent_m.get("pf"), recent_trades, BRANCH_RECENT_TARGET, 4.0)
    wf_pf = _pf_for_score(wf_m.get("pf"), wf_trades, BRANCH_WF_TARGET, 3.5)
    recent_ret = _ret_for_score(recent_m.get("ret"), recent_trades, BRANCH_RECENT_TARGET)
    wf_ret = _ret_for_score(wf_m.get("ret"), wf_trades, BRANCH_WF_TARGET)
    recent_dd = _dd_for_score(recent_m.get("maxdd"), recent_trades, BRANCH_RECENT_TARGET, 0.06)
    wf_dd = _dd_for_score(wf_m.get("maxdd"), wf_trades, BRANCH_WF_TARGET, 0.08)
    pf_floor = min(max(0.0, s88._safe_float(wf.get("pf_floor", 0.0))), 2.5)
    dd_ceiling = max(0.0, s88._safe_float(wf.get("dd_ceiling", 0.0)))
    return float(
        recent_pf * 154.0
        + recent_ret * 118.0
        - recent_dd * 84.0
        + min(recent_trades, BRANCH_RECENT_TARGET * 2) * 1.8
        + wf_pf * 138.0
        + wf_ret * 104.0
        - wf_dd * 92.0
        + min(wf_trades, BRANCH_WF_TARGET * 3) * 2.6
        + int(wf.get("positive_folds", 0) or 0) * 14.0
        + pf_floor * 22.0
        - dd_ceiling * 16.0
        + _safe_full_pf(full_m) * 8.0
        + _safe_full_ret(full_m) * 3.0
        + _event_fold_share(wf) * 28.0
        - _sample_penalty(recent_trades, BRANCH_RECENT_TARGET, 8.0)
        - _sample_penalty(wf_trades, BRANCH_WF_TARGET, 10.0)
    )


def _alpha_label(recent_m: dict[str, Any], wf_m: dict[str, Any], pos_folds: int, event_share: float, *, branch: bool) -> str:
    recent_trades = int(recent_m.get("trades", 0) or 0)
    wf_trades = int(wf_m.get("trades", 0) or 0)
    total_trades = recent_trades + wf_trades
    recent_pf = s88._safe_float(recent_m.get("pf"))
    wf_pf = s88._safe_float(wf_m.get("pf"))
    recent_ret = s88._safe_float(recent_m.get("ret"))
    wf_ret = s88._safe_float(wf_m.get("ret"))
    wf_dd = abs(s88._safe_float(wf_m.get("maxdd")))
    if branch:
        if recent_trades >= 12 and wf_trades >= 8 and total_trades >= 22 and recent_pf >= 1.25 and wf_pf >= 1.15 and recent_ret > 0 and wf_ret > 0 and wf_dd <= 0.25 and pos_folds >= 3:
            return "pass"
        if recent_trades >= 8 and wf_trades >= 5 and total_trades >= 14 and recent_pf >= 1.10 and wf_pf >= 1.05 and recent_ret > 0 and wf_ret >= 0 and wf_dd <= 0.35:
            return "hold"
        if recent_trades >= 5 and wf_trades >= 4 and total_trades >= 10 and event_share >= 0.20 and recent_pf >= 1.00 and wf_pf >= 0.95 and wf_dd <= 0.40:
            return "reserve+"
        return "reserve"
    if recent_trades >= 14 and wf_trades >= 8 and recent_pf >= 1.95 and wf_pf >= 1.40 and recent_ret > 0 and wf_ret > 0 and wf_dd <= 0.45 and pos_folds >= 3:
        return "pass"
    if recent_trades >= 10 and wf_trades >= 6 and recent_pf >= 1.50 and wf_pf >= 1.10 and wf_dd <= 0.60:
        return "hold"
    if recent_trades >= 6 and wf_trades >= 4 and event_share >= 0.20 and wf_pf >= 1.00 and wf_dd <= 0.65:
        return "reserve+"
    return "reserve"


def _run_mainline(root: Path, cfg: dict[str, Any], data: dict[str, pd.DataFrame], item: dict[str, Any], initial_equity: float, full_start: pd.Timestamp, full_end: pd.Timestamp) -> dict[str, Any]:
    trades, trades_feat = s59._run_portfolio_candidate(root, cfg, data, item["mods"])
    full_m = s77._with_window_metrics(s59._metrics_from_trades(trades, initial_equity), full_start, full_end)
    gate_rows: list[dict[str, Any]] = []
    for name, fn, note in PACKS:
        gr = s59._evaluate_gate(trades_feat, name, fn, note, initial_equity)
        gr["recent_metrics"] = s77._with_window_metrics(s78._recent_metrics(gr.get("gated_df"), initial_equity), s78.RECENT_START, full_end)
        gate_rows.append(gr)
    return {"name": item["name"], "note": item["note"], "full_metrics": full_m, "gate_rows": gate_rows}


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
    for name, fn, note in PACKS:
        gr = s59._evaluate_gate(trades_feat, name, fn, note, initial_equity)
        gr["recent_metrics"] = s78._with_window_metrics(s78._recent_metrics(gr.get("gated_df"), initial_equity), s78.RECENT_START, full_end)
        gate_rows.append(gr)
    return {"symbol": sym, "family": item.get("family", "mixed"), "name": item["name"], "note": item.get("note", ""), "full_metrics": full_m, "gate_rows": gate_rows, "full_end": full_end}


def _json_safe(obj: Any) -> Any:
    return s88._json_safe(obj)


def _strip_gate_payload(best_gate: dict[str, Any]) -> dict[str, Any]:
    return s88._strip_gate_payload(best_gate)


def _write_mainline(path_txt: Path, path_json: Path, rows: list[dict[str, Any]]) -> None:
    lines: list[str] = []
    lines.append("Stage90 主线事件 alpha 矩阵")
    lines.append("核心原则：重大消息不再只做 veto；开始测试事件冲击 / 漂移 / 扫损 / 拥挤 是否可以成为开仓层。")
    lines.append("方法：base、event_breakout_alpha、event_pressure_alpha、event_reclaim_alpha、neutral_sweep_alpha、crowding_sweep_alpha、event_crowding_alpha、fusion_alpha_all。")
    lines.append("")
    lines.append("=== 候选结果 ===")
    for row in rows:
        dom = row["dominant_gate"]
        full_m = row["full_metrics"]
        recent_m = dom.get("recent_metrics", {})
        wf = row["walkforward"]
        oos_m = wf["metrics"]
        lines.append(
            f"- {row['name']}: dominant_gate={dom.get('gate_name')} ({row['decision']}) | 6年 收益={s88._fmt_pct(full_m.get('ret'))} 月化={s88._fmt_pct(full_m.get('monthlyized_ret'))} 回撤={s88._fmt_pct(full_m.get('maxdd'))} 交易={int(full_m.get('trades',0))} PF={s88._safe_float(full_m.get('pf')):.3f} | 近2年 收益={s88._fmt_pct(recent_m.get('ret'))} 月化={s88._fmt_pct(recent_m.get('monthlyized_ret'))} 回撤={s88._fmt_pct(recent_m.get('maxdd'))} 交易={int(recent_m.get('trades',0))} PF={s88._safe_float(recent_m.get('pf')):.3f} | WF样本外 收益={s88._fmt_pct(oos_m.get('ret'))} 月化={s88._fmt_pct(oos_m.get('monthlyized_ret'))} 回撤={s88._fmt_pct(oos_m.get('maxdd'))} 交易={int(oos_m.get('trades',0))} PF={s88._safe_float(oos_m.get('pf')):.3f} | 正收益折={wf['positive_folds']}/{wf['total_folds']} | alpha_score={row['alpha_score']:+.2f}"
        )
        lines.append(f"  note={row['note']} | gate_mix={wf['gate_mix']} | event_fold_share={_event_fold_share(wf):.2f} | wf_pf_floor={wf['pf_floor']:.3f} | wf_dd_ceiling={wf['dd_ceiling']:.3f}")
    lines.append("")
    lines.append("=== 结论 ===")
    lines.append("- 主线先看事件 alpha 是否能在 WF 折里真实占据折内最优，而不是只看全样本总收益。")
    lines.append("- 如果 dominant_gate 仍长期是 base_message_overlay，说明消息层还没科学到能独立当开仓层。")
    path_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    path_json.write_text(json.dumps({"rows": [_json_safe({**r, "dominant_gate": _strip_gate_payload(r["dominant_gate"])}) for r in rows]}, ensure_ascii=False, indent=2), encoding="utf-8")




_DECISION_RANK = {"reserve": 0.0, "reserve+": 0.5, "hold": 1.0, "pass": 2.0}


def _branch_lane_stats(row: dict[str, Any]) -> dict[str, Any]:
    recent_m = row.get("dominant_gate", {}).get("recent_metrics", {}) or {}
    wf_m = row.get("walkforward", {}).get("metrics", {}) or {}
    recent_trades = int(recent_m.get("trades", 0) or 0)
    wf_trades = int(wf_m.get("trades", 0) or 0)
    recent_pf = _pf_for_score(recent_m.get("pf"), recent_trades, BRANCH_RECENT_TARGET, 4.0)
    wf_pf = _pf_for_score(wf_m.get("pf"), wf_trades, BRANCH_WF_TARGET, 3.5)
    recent_ret = _ret_for_score(recent_m.get("ret"), recent_trades, BRANCH_RECENT_TARGET)
    wf_ret = _ret_for_score(wf_m.get("ret"), wf_trades, BRANCH_WF_TARGET)
    recent_monthly = s88._safe_float(recent_m.get("monthlyized_ret"))
    wf_monthly = s88._safe_float(wf_m.get("monthlyized_ret"))
    recent_dd = _dd_for_score(recent_m.get("maxdd"), recent_trades, BRANCH_RECENT_TARGET, 0.06)
    wf_dd = _dd_for_score(wf_m.get("maxdd"), wf_trades, BRANCH_WF_TARGET, 0.08)
    total_trades = recent_trades + wf_trades
    thin_penalty = _sample_penalty(recent_trades, 8, 18.0) + _sample_penalty(wf_trades, 5, 22.0)
    score = float(
        _DECISION_RANK.get(str(row.get("decision")), -1) * 180.0
        + recent_pf * 120.0
        + wf_pf * 128.0
        + recent_ret * 90.0
        + wf_ret * 108.0
        + recent_monthly * 2500.0
        + wf_monthly * 3000.0
        - recent_dd * 52.0
        - wf_dd * 68.0
        + min(recent_trades, BRANCH_RECENT_TARGET * 2) * 6.0
        + min(wf_trades, BRANCH_WF_TARGET * 3) * 7.0
        - thin_penalty
    )
    return {
        "recent_trades": recent_trades,
        "wf_trades": wf_trades,
        "total_trades": total_trades,
        "recent_ret": recent_ret,
        "wf_ret": wf_ret,
        "recent_monthly": recent_monthly,
        "wf_monthly": wf_monthly,
        "recent_pf": recent_pf,
        "wf_pf": wf_pf,
        "recent_dd": recent_dd,
        "wf_dd": wf_dd,
        "score": score,
    }


def _side_pick(rows: list[dict[str, Any]], family: str) -> dict[str, Any] | None:
    cand = [r for r in rows if str(r.get("family")) == family]
    if not cand:
        return None

    def _key(row: dict[str, Any]) -> tuple[float, float, float, float, float, float, float, float]:
        stats = _branch_lane_stats(row)
        return (
            float(stats.get("score", 0.0)),
            float(stats.get("wf_monthly", 0.0)),
            float(stats.get("recent_monthly", 0.0)),
            float(_DECISION_RANK.get(str(row.get("decision")), -1)),
            int(stats.get("total_trades", 0)),
            float(stats.get("wf_ret", 0.0)),
            float(stats.get("recent_ret", 0.0)),
            float(row.get("alpha_score", 0.0)),
        )

    return max(cand, key=_key)


def _asset_mode_note(symbol: str, mode: str) -> str:
    sym = symbol.upper()
    if mode == "dual_active":
        return f"{sym} 多空同腿都可开，但由事件/结构状态机切换方向"
    if mode == "dual_watch":
        return f"{sym} 多空同腿保留，但先放研究联动，不直接推模拟盘"
    if mode == "bi_directional_active":
        return f"{sym} 多空都保留，默认按趋势/回踩双模板分配"
    if mode == "bi_directional_watch":
        return f"{sym} 多空都保留，但先留在研究层联动回测，不直接推模拟盘"
    if mode == "short_dominant":
        return f"{sym} 当前以空侧为主，长侧只做强事件+结构确认"
    if mode == "long_dominant":
        return f"{sym} 当前以多侧为主，空侧只做失败突破/事件反身"
    if mode == "short_watch":
        return f"{sym} 空侧先保留为研究优先，等近2年/WF 样本继续增厚"
    if mode == "long_watch":
        return f"{sym} 多侧先保留为研究优先，等近2年/WF 样本继续增厚"
    return f"{sym} 暂留研究层，不推模拟盘"


def _asset_summaries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_symbol.setdefault(str(row.get("symbol", "")).upper(), []).append(row)

    def _pick_active(*items: dict[str, Any] | None) -> dict[str, Any] | None:
        valid = [item for item in items if item is not None]
        if not valid:
            return None
        return max(valid, key=lambda row: (float(_branch_lane_stats(row).get("score", 0.0)), float(row.get("alpha_score", 0.0))))

    def _dominant_ready(row: dict[str, Any] | None) -> bool:
        if row is None:
            return False
        stats = _branch_lane_stats(row)
        rank = float(_DECISION_RANK.get(str(row.get("decision")), -1))
        return bool(
            rank >= 1.0
            and int(stats.get("recent_trades", 0)) >= 8
            and int(stats.get("wf_trades", 0)) >= 5
            and int(stats.get("total_trades", 0)) >= 14
            and float(stats.get("recent_ret", 0.0)) > 0
            and float(stats.get("wf_pf", 0.0)) >= 1.0
        )

    def _watch_side_ready(row: dict[str, Any] | None) -> bool:
        if row is None:
            return False
        stats = _branch_lane_stats(row)
        return bool(
            int(stats.get("recent_trades", 0)) >= 10
            and float(stats.get("recent_ret", 0.0)) > 0
            and float(stats.get("recent_pf", 0.0)) >= 1.20
        )

    def _dual_watch_ready(row: dict[str, Any] | None) -> bool:
        if row is None:
            return False
        stats = _branch_lane_stats(row)
        rank = float(_DECISION_RANK.get(str(row.get("decision")), -1))
        return bool(
            rank >= 0.5
            and int(stats.get("recent_trades", 0)) >= 6
            and int(stats.get("wf_trades", 0)) >= 5
            and int(stats.get("total_trades", 0)) >= 12
            and float(stats.get("recent_ret", 0.0)) > 0
            and float(stats.get("wf_ret", 0.0)) >= 0
        )

    for symbol in sorted(by_symbol):
        grouped = by_symbol[symbol]
        long_best = _side_pick(grouped, "long")
        short_best = _side_pick(grouped, "short")
        dual_best = _side_pick(grouped, "dual")
        dual_rank = _DECISION_RANK.get(str((dual_best or {}).get("decision")), -1)
        long_rank = _DECISION_RANK.get(str((long_best or {}).get("decision")), -1)
        short_rank = _DECISION_RANK.get(str((short_best or {}).get("decision")), -1)

        if dual_best is not None and dual_rank >= 1.0:
            mode = "dual_active"
            active = dual_best
        elif _dual_watch_ready(dual_best):
            mode = "dual_watch"
            active = dual_best
        else:
            long_stats = _branch_lane_stats(long_best) if long_best is not None else {}
            short_stats = _branch_lane_stats(short_best) if short_best is not None else {}
            long_ready = _dominant_ready(long_best)
            short_ready = _dominant_ready(short_best)
            close_balance = False
            if long_best is not None and short_best is not None:
                score_gap = abs(float(long_stats.get("score", 0.0)) - float(short_stats.get("score", 0.0)))
                close_balance = score_gap <= 140.0
            if long_best is not None and short_best is not None and long_rank >= 1.0 and short_rank >= 1.0 and long_ready and short_ready:
                mode = "bi_directional_active"
                active = _pick_active(long_best, short_best)
            elif long_best is not None and short_best is not None and (
                (long_rank >= 0.5 and short_rank >= 0.5)
                or (close_balance and max(long_rank, short_rank) >= 0.5)
                or (long_ready and _watch_side_ready(short_best))
                or (short_ready and _watch_side_ready(long_best))
                or ((long_rank >= 0.5 and _watch_side_ready(short_best)) or (short_rank >= 0.5 and _watch_side_ready(long_best)))
            ):
                mode = "bi_directional_watch"
                active = _pick_active(long_best, short_best)
            elif short_best is not None and short_ready:
                mode = "short_dominant"
                active = short_best
            elif long_best is not None and long_ready:
                mode = "long_dominant"
                active = long_best
            elif short_best is not None and short_rank >= 0.5:
                mode = "short_watch"
                active = short_best
            elif long_best is not None and long_rank >= 0.5:
                mode = "long_watch"
                active = long_best
            else:
                mode = "research_only"
                active = _pick_active(dual_best, short_best, long_best) or grouped[0]

        out.append({
            "symbol": symbol,
            "mode": mode,
            "note": _asset_mode_note(symbol, mode),
            "active": active,
            "long_best": long_best,
            "short_best": short_best,
            "dual_best": dual_best,
        })
    return out


def _write_branch(path_txt: Path, path_json: Path, rows: list[dict[str, Any]]) -> None:
    lines: list[str] = []
    lines.append("Stage91 分支事件 alpha 矩阵")
    lines.append("核心原则：BTC/ETH/SOL 各自多空一体成腿；每个资产内部用 breakout / retest / shock / shortwave 模板切换方向。")
    lines.append("方法：先保留多空双模板，再用近2年 + WF 决定当前主开仓侧；不因一轮不合格就永久砍路径。")
    lines.append("")
    lines.append("=== 候选结果 ===")
    for row in rows:
        dom = row["dominant_gate"]
        full_m = row["full_metrics"]
        recent_m = dom.get("recent_metrics", {})
        wf = row["walkforward"]
        oos_m = wf["metrics"]
        lines.append(
            f"- {row['symbol'].upper()} | {row['family']} | {row['name']}: dominant_gate={dom.get('gate_name')} ({row['decision']}) | 6年 收益={s88._fmt_pct(full_m.get('ret'))} 月化={s88._fmt_pct(full_m.get('monthlyized_ret'))} 回撤={s88._fmt_pct(full_m.get('maxdd'))} 交易={int(full_m.get('trades',0))} PF={s88._safe_float(full_m.get('pf')):.3f} | 近2年 收益={s88._fmt_pct(recent_m.get('ret'))} 月化={s88._fmt_pct(recent_m.get('monthlyized_ret'))} 回撤={s88._fmt_pct(recent_m.get('maxdd'))} 交易={int(recent_m.get('trades',0))} PF={s88._safe_float(recent_m.get('pf')):.3f} | WF样本外 收益={s88._fmt_pct(oos_m.get('ret'))} 月化={s88._fmt_pct(oos_m.get('monthlyized_ret'))} 回撤={s88._fmt_pct(oos_m.get('maxdd'))} 交易={int(oos_m.get('trades',0))} PF={s88._safe_float(oos_m.get('pf')):.3f} | 正收益折={wf['positive_folds']}/{wf['total_folds']} | alpha_score={row['alpha_score']:+.2f}"
        )
        lines.append(f"  note={row['note']} | gate_mix={wf['gate_mix']} | event_fold_share={_event_fold_share(wf):.2f} | wf_pf_floor={wf['pf_floor']:.3f} | wf_dd_ceiling={wf['dd_ceiling']:.3f}")
    lines.append("")
    lines.append("=== 各赛道当前最优 ===")
    best_by_lane: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row['symbol']).upper(), str(row['family']))
        if key not in best_by_lane:
            best_by_lane[key] = row
    for (sym, family), row in best_by_lane.items():
        m = row['walkforward']['metrics']
        lines.append(f"- {sym} | {family}: {row['name']} | dominant_gate={row['dominant_gate'].get('gate_name')} | event_fold_share={_event_fold_share(row['walkforward']):.2f} | WF 收益={s88._fmt_pct(m.get('ret'))} | WF PF={s88._safe_float(m.get('pf')):.3f} | WF MaxDD={s88._fmt_pct(m.get('maxdd'))} | {row['decision']}")

    lines.append("")
    lines.append("=== 资产一体腿建议 ===")
    asset_summary = _asset_summaries(rows)
    for item in asset_summary:
        active = item["active"] or {}
        active_recent = active.get("dominant_gate", {}).get("recent_metrics", {}) or {}
        active_wf = active.get("walkforward", {}).get("metrics", {}) or {}
        long_best = item.get("long_best")
        short_best = item.get("short_best")
        dual_best = item.get("dual_best")
        lines.append(
            f"- {item['symbol']}: mode={item['mode']} | active={active.get('name','-')} | 近2年 PF={s88._safe_float(active_recent.get('pf')):.3f} 收益={s88._fmt_pct(active_recent.get('ret'))} 交易={int(active_recent.get('trades',0))} | WF PF={s88._safe_float(active_wf.get('pf')):.3f} 收益={s88._fmt_pct(active_wf.get('ret'))} 回撤={s88._fmt_pct(active_wf.get('maxdd'))}"
        )
        lines.append(
            f"  long_best={(long_best or {}).get('name','-')} | short_best={(short_best or {}).get('name','-')} | dual_best={(dual_best or {}).get('name','-')} | note={item['note']}"
        )
    asset_summary = _asset_summaries(rows)
    def _asset_json(item: dict[str, Any]) -> dict[str, Any]:
        def _row_json(row: dict[str, Any] | None) -> Any:
            if row is None:
                return None
            return _json_safe({**row, "dominant_gate": _strip_gate_payload(row.get("dominant_gate", {}))})
        return {
            "symbol": item.get("symbol"),
            "mode": item.get("mode"),
            "note": item.get("note"),
            "active": _row_json(item.get("active")),
            "long_best": _row_json(item.get("long_best")),
            "short_best": _row_json(item.get("short_best")),
            "dual_best": _row_json(item.get("dual_best")),
        }
    path_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    path_json.write_text(json.dumps({"rows": [_json_safe({**r, "dominant_gate": _strip_gate_payload(r["dominant_gate"])}) for r in rows], "asset_summary": [_asset_json(x) for x in asset_summary]}, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage90/91 event alpha matrix")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    cfg = rcb.load_research_base_config(root)
    initial_equity = float(cfg.get("portfolio", {}).get("initial_equity", 100000.0))
    reports_raw = root / "reports" / "research_raw"
    reports_raw.mkdir(parents=True, exist_ok=True)

    data = s46._load_portfolio_data(root, cfg)
    full_start, full_end = s77._window_bounds_from_data(data)
    main_rows = [_run_mainline(root, cfg, data, item, initial_equity, full_start, full_end) for item in s88._mainline_items()]
    ref_row = next((r for r in main_rows if r["name"] == "mainline_live_base"), main_rows[0])
    for row in main_rows:
        row["walkforward"] = s81._wf_result(row, ref_row, initial_equity, s81.RECENT_START, full_end)
        row["dominant_gate"] = _dominant_gate(row, branch=False)
        row["alpha_score"] = _mainline_alpha_score(row)
        row["decision"] = _alpha_label(row["dominant_gate"].get("recent_metrics", {}), row["walkforward"].get("metrics", {}), row["walkforward"].get("positive_folds", 0), _event_fold_share(row["walkforward"]), branch=False)
    main_rows.sort(key=lambda r: float(r["alpha_score"]), reverse=True)
    _write_mainline(reports_raw / "stage90_mainline_event_alpha_matrix_latest.txt", reports_raw / "stage90_mainline_event_alpha_matrix_latest.json", main_rows)

    branch_rows = [_run_branch(root, cfg, item, initial_equity) for item in s88._branch_items()]
    for row in branch_rows:
        row["walkforward"] = s82._wf_result(row, initial_equity, s78.RECENT_START, row["full_end"])
        row["dominant_gate"] = _dominant_gate(row, branch=True)
        row["alpha_score"] = _branch_alpha_score(row)
        row["decision"] = _alpha_label(row["dominant_gate"].get("recent_metrics", {}), row["walkforward"].get("metrics", {}), row["walkforward"].get("positive_folds", 0), _event_fold_share(row["walkforward"]), branch=True)
    branch_rows.sort(key=lambda r: float(r["alpha_score"]), reverse=True)
    _write_branch(reports_raw / "stage91_branch_event_alpha_matrix_latest.txt", reports_raw / "stage91_branch_event_alpha_matrix_latest.json", branch_rows)

    print(reports_raw / "stage90_mainline_event_alpha_matrix_latest.txt")
    print(reports_raw / "stage90_mainline_event_alpha_matrix_latest.json")
    print(reports_raw / "stage91_branch_event_alpha_matrix_latest.txt")
    print(reports_raw / "stage91_branch_event_alpha_matrix_latest.json")


if __name__ == "__main__":
    main()
