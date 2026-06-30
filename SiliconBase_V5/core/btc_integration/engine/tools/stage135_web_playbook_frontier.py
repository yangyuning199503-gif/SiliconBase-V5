from __future__ import annotations

import argparse
import copy
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd

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

TARGET_MONTHLY_MIN = 0.076
TARGET_MONTHLY_MAX = 0.114


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
    ("base_message_overlay", s88._gate_none, "只保留消息面 overlay，不把事件当独立开仓层"),
    ("event_impulse_alpha", s88._gate_major_event_impulse, "重大催化当根冲击：只在方向、结构和流向同向时放行"),
    ("event_drift_alpha", _pack_or(s88._gate_event_pressure_continuation, s88._gate_post_event_drift), "事件后 1-3 根漂移/延续：吸收专业交易员常用的 event drift 经验"),
    ("reclaim_reversal_alpha", _pack_or(s88._gate_event_sweep_bridge, s88._gate_liquidity_sweep_reclaim, s88._gate_neutral_revert), "扫流动性再收回关键位：假突破/假跌破后的 reclaim"),
    ("squeeze_continuation_alpha", _pack_or(s88._gate_crowding_reversal, s88._gate_event_pressure_continuation, s88._gate_post_event_drift), "拥挤/挤仓 + 事件延续：更贴近 perp 市场的 squeeze/continuation 经验"),
    ("macro_crowding_alpha", _pack_or(s88._gate_major_event_impulse, s88._gate_post_event_drift, s88._gate_crowding_reversal), "宏观催化 + 拥挤错配：把消息、持仓和结构连在一起"),
    ("fusion_alpha_all", s88._gate_fusion_open, "事件/延续/挤仓/扫损的全融合状态机"),
]


def _sample_q(trades: Any, target: int) -> float:
    t = max(int(trades or 0), 0)
    if t <= 0:
        return 0.0
    if target <= 0:
        return 1.0
    return max(0.0, min(1.0, t / float(target)))


def _weights(branch: bool) -> tuple[int, int, float, float]:
    if branch:
        return 12, 6, 0.54, 0.46
    return 18, 8, 0.52, 0.48


def _target_monthly(row: dict[str, Any], *, branch: bool) -> float:
    dom = row.get("dominant_gate", {}) or {}
    recent = dom.get("recent_metrics", {}) or {}
    wf = (row.get("walkforward") or {}).get("metrics", {}) or {}
    recent_target, wf_target, rw0, ww0 = _weights(branch)
    rw = rw0 * _sample_q(recent.get("trades"), recent_target)
    ww = ww0 * _sample_q(wf.get("trades"), wf_target)
    denom = rw + ww
    if denom <= 0:
        return 0.0
    return (
        s88._safe_float(recent.get("monthlyized_ret")) * rw
        + s88._safe_float(wf.get("monthlyized_ret")) * ww
    ) / denom


def _dominant_track(gate_name: str) -> str:
    g = str(gate_name or "")
    if g == "base_message_overlay":
        return "base"
    if g == "event_impulse_alpha":
        return "impulse"
    if g == "event_drift_alpha":
        return "drift"
    if g == "reclaim_reversal_alpha":
        return "reclaim"
    if g == "squeeze_continuation_alpha":
        return "squeeze"
    if g == "macro_crowding_alpha":
        return "macro+crowding"
    if g == "fusion_alpha_all":
        return "fusion"
    return g or "-"


def _frontier_score(row: dict[str, Any], *, branch: bool) -> float:
    base = s90._branch_alpha_score(row) if branch else s90._mainline_alpha_score(row)
    dom = row.get("dominant_gate", {}) or {}
    recent = dom.get("recent_metrics", {}) or {}
    wf = (row.get("walkforward") or {}).get("metrics", {}) or {}
    full = row.get("full_metrics", {}) or {}
    month = _target_monthly(row, branch=branch)
    recent_target, wf_target, _, _ = _weights(branch)
    recent_trades = int(recent.get("trades", 0) or 0)
    wf_trades = int(wf.get("trades", 0) or 0)
    recent_pf = s90._pf_for_score(recent.get("pf"), recent_trades, recent_target, 4.0 if branch else 4.5)
    wf_pf = s90._pf_for_score(wf.get("pf"), wf_trades, wf_target, 3.5 if branch else 4.0)
    gap = max(0.0, TARGET_MONTHLY_MIN - month)
    divergence = abs(s88._safe_float(recent.get("monthlyized_ret")) - s88._safe_float(wf.get("monthlyized_ret")))
    sign_penalty = 0.0
    if s88._safe_float(recent.get("ret")) > 0 and s88._safe_float(wf.get("ret")) < 0:
        sign_penalty += 18.0 if branch else 22.0
    if s88._safe_float(recent.get("ret")) < 0 and s88._safe_float(wf.get("ret")) > 0:
        sign_penalty += 8.0 if branch else 10.0
    innovation_bonus = 0.0
    if str(dom.get("gate_name")) != "base_message_overlay" and recent_trades >= max(6, int(recent_target * 0.6)) and wf_trades >= max(4, int(wf_target * 0.6)):
        innovation_bonus += 28.0 if branch else 24.0
    if row.get("walkforward", {}).get("positive_folds", 0) >= 3:
        innovation_bonus += 18.0 if branch else 14.0
    sixy_soft_penalty = 0.0
    if s88._safe_float(full.get("ret")) < 0 and month < 0.03:
        sixy_soft_penalty = abs(s88._safe_float(full.get("ret"))) * (42.0 if branch else 28.0)
    return float(
        base
        + month * 2400.0
        + recent_pf * (68.0 if branch else 54.0)
        + wf_pf * (88.0 if branch else 76.0)
        + innovation_bonus
        - gap * 1200.0
        - divergence * (260.0 if branch else 220.0)
        - abs(s88._safe_float(wf.get("maxdd"))) * (96.0 if branch else 84.0)
        - max(0.0, 0.55 - _sample_q(recent_trades, recent_target)) * (96.0 if branch else 72.0)
        - max(0.0, 0.60 - _sample_q(wf_trades, wf_target)) * (132.0 if branch else 108.0)
        - sign_penalty
        - sixy_soft_penalty
    )


def _frontier_label(row: dict[str, Any], *, branch: bool) -> str:
    dom = row.get("dominant_gate", {}) or {}
    recent = dom.get("recent_metrics", {}) or {}
    wf = (row.get("walkforward") or {}).get("metrics", {}) or {}
    month = _target_monthly(row, branch=branch)
    recent_target, wf_target, _, _ = _weights(branch)
    recent_trades = int(recent.get("trades", 0) or 0)
    wf_trades = int(wf.get("trades", 0) or 0)
    recent_pf = s88._safe_float(recent.get("pf"))
    wf_pf = s88._safe_float(wf.get("pf"))
    wf_dd = abs(s88._safe_float(wf.get("maxdd")))
    pos_folds = int(row.get("walkforward", {}).get("positive_folds", 0) or 0)
    event_share = s90._event_fold_share(row.get("walkforward", {}) or {})
    if month >= TARGET_MONTHLY_MIN and recent_trades >= recent_target and wf_trades >= max(wf_target, 8 if branch else 10) and recent_pf >= 1.15 and wf_pf >= 1.08 and wf_dd <= 0.28 and pos_folds >= 3:
        return "pass"
    if month >= 0.03 and recent_trades >= max(8, recent_target // 2) and wf_trades >= max(5, wf_target // 2) and recent_pf >= 1.02 and wf_pf >= 0.98 and wf_dd <= 0.38:
        return "hold"
    if event_share >= 0.20 and wf_trades >= 4 and wf_pf >= 0.95 and wf_dd <= 0.45:
        return "reserve+"
    return "reserve"


def _mainline_items() -> list[dict[str, Any]]:
    item_map = {str(item.get("name")): item for item in s88._mainline_items()}
    out: dict[str, dict[str, Any]] = {}

    def add(item: dict[str, Any] | None) -> None:
        if item is not None:
            out[str(item.get("name"))] = item

    for name in [
        "mainline_live_dynlev_fix8_lock18",
        "mainline_core_satellite_dynlev_fix8_lock18",
    ]:
        add(item_map.get(name))

    base_live = item_map.get("mainline_live_base")
    if base_live is not None:
        add(
            s88._make_mainline_variant(
                base_live,
                name="mainline_event_drift_fix10_lock10",
                note="网页经验融入：事件漂移 + 更快保本；不追单根，吃 1-3 根扩散。",
                patch={
                    "strategy_params.cooldown_bars": 4,
                    "portfolio.dynamic_leverage.enabled": True,
                    "portfolio.dynamic_leverage.min": 5.0,
                    "portfolio.dynamic_leverage.max": 10.0,
                    "portfolio.dynamic_leverage.adx_low": 14.0,
                    "portfolio.dynamic_leverage.adx_high": 28.0,
                    "money_management.mode": "fixed",
                    "money_management.capital_slices": 10,
                    "money_management.stake_mode": "dynamic_equity",
                    "money_management.stake_min_usd": 6500,
                    "money_management.stake_max_usd": 11500,
                    "money_management.stop_loss_pct": 0.14,
                    "money_management.take_profit_pct": 0.96,
                    "money_management.trailing_profit.enabled": True,
                    "money_management.trailing_profit.activation_pnl_pct": 0.34,
                    "money_management.trailing_profit.giveback_ratio": 0.36,
                    "money_management.trailing_profit.min_lock_pnl_pct": 0.06,
                },
            )
        )
        add(
            s88._make_mainline_variant(
                base_live,
                name="mainline_squeeze_break_fix12_lock06",
                note="网页经验融入：挤仓/波动压缩后加速模板；更细分仓 + 更快锁盈。",
                patch={
                    "strategy_params.cooldown_bars": 3,
                    "portfolio.dynamic_leverage.enabled": True,
                    "portfolio.dynamic_leverage.min": 4.0,
                    "portfolio.dynamic_leverage.max": 9.0,
                    "portfolio.dynamic_leverage.adx_low": 13.0,
                    "portfolio.dynamic_leverage.adx_high": 26.0,
                    "money_management.mode": "fixed",
                    "money_management.capital_slices": 12,
                    "money_management.stake_mode": "dynamic_equity",
                    "money_management.stake_min_usd": 6000,
                    "money_management.stake_max_usd": 11000,
                    "money_management.stop_loss_pct": 0.12,
                    "money_management.take_profit_pct": 1.12,
                    "money_management.trailing_profit.enabled": True,
                    "money_management.trailing_profit.activation_pnl_pct": 0.28,
                    "money_management.trailing_profit.giveback_ratio": 0.30,
                    "money_management.trailing_profit.min_lock_pnl_pct": 0.05,
                },
            )
        )
    return list(out.values())


def _branch_items() -> list[dict[str, Any]]:
    item_map = {str(item.get("name")): item for item in s88._branch_items()}
    out: dict[str, dict[str, Any]] = {}

    def add(item: dict[str, Any] | None) -> None:
        if item is not None:
            out[str(item.get("name"))] = item

    for name in [
        "eth_short_shock_fast_lb16_atr052_adx22_s078",
        "eth_retest_short_trend_lb20_atr060_adx24_s068",
        "btc_breakout_long_event_lb20_atr060_adx24_s050",
        "btc_dual_shortwave_sr_lb24_zone030_s055",
    ]:
        add(item_map.get(name))

    eth_long = item_map.get("eth_breakout_long_follow_lb16_atr050_adx22_s034")
    if eth_long is not None:
        add(
            s88._make_variant(
                eth_long,
                name="eth_event_drift_long_lb12_atr046_adx18_s042",
                note="网页经验融入：ETH 事件后漂移/续涨模板，缩短突破窗口，不只押回踩。",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 12,
                    "strategy_params.breakout_atr_buffer": 0.46,
                    "strategy_params.cooldown_bars": 3,
                    "filters.adx_floor": 18,
                    "money_management.stake_scale.eth_long": 0.42,
                },
            )
        )

    btc_short = item_map.get("btc_retest_short_event_lb20_atr060_adx24_s072")
    if btc_short is not None:
        add(
            s88._make_variant(
                btc_short,
                name="btc_retest_short_event_lb18_atr055_adx22_s076",
                note="网页经验融入：BTC 重大催化后回踩失败空单，更快确认，不追第一脚。",
                family="short",
                patch={
                    "strategy_params.breakout_lookback": 18,
                    "strategy_params.breakout_atr_buffer": 0.55,
                    "strategy_params.cooldown_bars": 4,
                    "filters.btc_breakout_atr_buffer": 0.55,
                    "filters.btc_adx_floor": 22,
                    "money_management.stake_scale.btc_short": 0.76,
                },
            )
        )
    return list(out.values())


def _run_mainline(root: Path, cfg: dict[str, Any], data: dict[str, pd.DataFrame], item: dict[str, Any], initial_equity: float, full_start: pd.Timestamp, full_end: pd.Timestamp) -> dict[str, Any]:
    from tools import stage59_structural_lab as s59
    trades, trades_feat = s59._run_portfolio_candidate(root, cfg, data, item["mods"])
    full_m = s77._with_window_metrics(s59._metrics_from_trades(trades, initial_equity), full_start, full_end)
    gate_rows: list[dict[str, Any]] = []
    for name, fn, note in PACKS:
        gr = s59._evaluate_gate(trades_feat, name, fn, note, initial_equity)
        gr["recent_metrics"] = s77._with_window_metrics(s78._recent_metrics(gr.get("gated_df"), initial_equity), s78.RECENT_START, full_end)
        gate_rows.append(gr)
    return {"name": item["name"], "note": item.get("note", ""), "full_metrics": full_m, "gate_rows": gate_rows}


def _run_branch(root: Path, cfg: dict[str, Any], item: dict[str, Any], initial_equity: float) -> dict[str, Any]:
    from tools import stage59_structural_lab as s59
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


def _payload_row(row: dict[str, Any], *, branch: bool) -> dict[str, Any]:
    dom = row.get("dominant_gate", {}) or {}
    recent = dom.get("recent_metrics", {}) or {}
    wf = (row.get("walkforward") or {}).get("metrics", {}) or {}
    full = row.get("full_metrics", {}) or {}
    month = _target_monthly(row, branch=branch)
    return {
        "name": row.get("name"),
        "symbol": row.get("symbol"),
        "family": row.get("family"),
        "dominant_gate": dom.get("gate_name"),
        "dominant_track": _dominant_track(str(dom.get("gate_name") or "")),
        "decision": row.get("decision"),
        "frontier_score": s88._safe_float(row.get("alpha_score")),
        "target_monthly": month,
        "gap_to_floor": max(0.0, TARGET_MONTHLY_MIN - month),
        "full_ret": s88._safe_float(full.get("ret")),
        "full_monthly": s88._safe_float(full.get("monthlyized_ret")),
        "full_trades": int(full.get("trades", 0) or 0),
        "full_pf": s88._safe_float(full.get("pf")),
        "recent_ret": s88._safe_float(recent.get("ret")),
        "recent_monthly": s88._safe_float(recent.get("monthlyized_ret")),
        "recent_trades": int(recent.get("trades", 0) or 0),
        "recent_pf": s88._safe_float(recent.get("pf")),
        "wf_ret": s88._safe_float(wf.get("ret")),
        "wf_monthly": s88._safe_float(wf.get("monthlyized_ret")),
        "wf_trades": int(wf.get("trades", 0) or 0),
        "wf_pf": s88._safe_float(wf.get("pf")),
        "wf_dd": s88._safe_float(wf.get("maxdd")),
        "positive_folds": int((row.get("walkforward") or {}).get("positive_folds", 0) or 0),
        "total_folds": int((row.get("walkforward") or {}).get("total_folds", 0) or 0),
        "event_fold_share": s90._event_fold_share(row.get("walkforward") or {}),
    }


def _write_report(path_txt: Path, path_json: Path, main_rows: list[dict[str, Any]], branch_rows: list[dict[str, Any]]) -> None:
    main_payload = [_payload_row(r, branch=False) for r in main_rows]
    branch_payload = [_payload_row(r, branch=True) for r in branch_rows]
    lines: list[str] = []
    lines.append("Stage135 网页经验前沿快筛")
    lines.append("原则：吸收事件漂移 / 挤仓延续 / reclaim / 宏观催化经验，但排序必须对低样本和过拟合敏感。")
    lines.append(f"目标区间：{TARGET_MONTHLY_MIN*100:.1f}% - {TARGET_MONTHLY_MAX*100:.1f}% / 月")
    lines.append("")
    lines.append("=== 主线 ===")
    for row in main_payload:
        lines.append(
            f"- {row['name']}: track={row['dominant_track']} | target_monthly={row['target_monthly']*100:.2f}% | 6年={row['full_monthly']*100:.2f}%/{row['full_trades']}笔/PF{row['full_pf']:.3f} | 近2年={row['recent_monthly']*100:.2f}%/{row['recent_trades']}笔/PF{row['recent_pf']:.3f} | WF={row['wf_monthly']*100:.2f}%/{row['wf_trades']}笔/PF{row['wf_pf']:.3f} | decision={row['decision']}"
        )
    lines.append("")
    lines.append("=== 分支 ===")
    for row in branch_payload:
        fam = row.get("family") or "-"
        sym = row.get("symbol") or "-"
        lines.append(
            f"- {sym}|{fam}|{row['name']}: track={row['dominant_track']} | target_monthly={row['target_monthly']*100:.2f}% | 6年={row['full_monthly']*100:.2f}%/{row['full_trades']}笔/PF{row['full_pf']:.3f} | 近2年={row['recent_monthly']*100:.2f}%/{row['recent_trades']}笔/PF{row['recent_pf']:.3f} | WF={row['wf_monthly']*100:.2f}%/{row['wf_trades']}笔/PF{row['wf_pf']:.3f} | decision={row['decision']}"
        )
    lines.append("")
    lines.append("=== 结论 ===")
    if main_payload:
        top = main_payload[0]
        lines.append(f"- 主线第一名: {top['name']} | target_monthly={top['target_monthly']*100:.2f}% | track={top['dominant_track']} | gap_to_7.6={top['gap_to_floor']*100:.2f}%")
    if branch_payload:
        top = branch_payload[0]
        lines.append(f"- 分支第一名: {top['name']} | target_monthly={top['target_monthly']*100:.2f}% | track={top['dominant_track']} | gap_to_7.6={top['gap_to_floor']*100:.2f}%")
    lines.append("- 低样本高 PF 不再优先；近2年和 WF 若明显背离，会被主动降权。")

    path_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    path_json.write_text(
        json.dumps(
            {
                "target_monthly_min": TARGET_MONTHLY_MIN,
                "target_monthly_max": TARGET_MONTHLY_MAX,
                "packs": [x[0] for x in PACKS],
                "mainline": main_payload,
                "branch": branch_payload,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage135 web playbook frontier")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    reports_raw = root / "reports" / "research_raw"
    reports_raw.mkdir(parents=True, exist_ok=True)

    cfg = rcb.load_research_base_config(root)
    initial_equity = float(cfg.get("portfolio", {}).get("initial_equity", 100000.0))

    data = s46._load_portfolio_data(root, cfg)
    full_start, full_end = s77._window_bounds_from_data(data)

    mainline_items_all = {str(item.get("name")): item for item in s88._mainline_items()}
    ref_item = mainline_items_all.get("mainline_live_base")
    if ref_item is None:
        raise SystemExit("missing mainline reference: mainline_live_base")
    ref_row = _run_mainline(root, cfg, data, ref_item, initial_equity, full_start, full_end)

    main_rows: list[dict[str, Any]] = []
    main_items = _mainline_items()
    for i, item in enumerate(main_items, 1):
        print(f"[stage135] mainline {i}/{len(main_items)} {item['name']}", flush=True)
        row = _run_mainline(root, cfg, data, item, initial_equity, full_start, full_end)
        row["walkforward"] = s81._wf_result(row, ref_row, initial_equity, s81.RECENT_START, full_end)
        row["dominant_gate"] = s90._dominant_gate(row, branch=False)
        row["alpha_score"] = _frontier_score(row, branch=False)
        row["decision"] = _frontier_label(row, branch=False)
        main_rows.append(row)
    main_rows.sort(key=lambda r: float(r.get("alpha_score", 0.0)), reverse=True)

    branch_rows: list[dict[str, Any]] = []
    branch_items = _branch_items()
    for i, item in enumerate(branch_items, 1):
        print(f"[stage135] branch {i}/{len(branch_items)} {item['name']}", flush=True)
        row = _run_branch(root, cfg, item, initial_equity)
        row["walkforward"] = s82._wf_result(row, initial_equity, s78.RECENT_START, row["full_end"])
        row["dominant_gate"] = s90._dominant_gate(row, branch=True)
        row["alpha_score"] = _frontier_score(row, branch=True)
        row["decision"] = _frontier_label(row, branch=True)
        branch_rows.append(row)
    branch_rows.sort(key=lambda r: float(r.get("alpha_score", 0.0)), reverse=True)

    main_txt = reports_raw / "stage90_mainline_event_alpha_matrix_latest.txt"
    main_json = reports_raw / "stage90_mainline_event_alpha_matrix_latest.json"
    branch_txt = reports_raw / "stage91_branch_event_alpha_matrix_latest.txt"
    branch_json = reports_raw / "stage91_branch_event_alpha_matrix_latest.json"
    s90._write_mainline(main_txt, main_json, main_rows)
    s90._write_branch(branch_txt, branch_json, branch_rows)

    frontier_txt = reports_raw / "stage135_web_playbook_frontier_latest.txt"
    frontier_json = reports_raw / "stage135_web_playbook_frontier_latest.json"
    _write_report(frontier_txt, frontier_json, main_rows, branch_rows)

    manifest = {
        "mode": "web_playbook_frontier",
        "packs": [x[0] for x in PACKS],
        "mainline_names": [str(x.get("name")) for x in _mainline_items()],
        "branch_names": [str(x.get("name")) for x in _branch_items()],
        "outputs": {
            "stage90_txt": str(main_txt),
            "stage90_json": str(main_json),
            "stage91_txt": str(branch_txt),
            "stage91_json": str(branch_json),
            "frontier_txt": str(frontier_txt),
            "frontier_json": str(frontier_json),
        },
    }
    (reports_raw / "stage135_web_playbook_frontier_manifest_latest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(frontier_txt)
    print(frontier_json)
    print(reports_raw / "stage135_web_playbook_frontier_manifest_latest.json")


if __name__ == "__main__":
    main()
