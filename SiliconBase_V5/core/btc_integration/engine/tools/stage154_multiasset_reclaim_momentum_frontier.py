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
from tools import stage82_branch_walkforward_lab as s82
from tools import stage88_strategy_fusion_walkforward as s88
from tools import stage90_event_alpha_matrix as s90
from tools import stage136_regime_plateau_frontier as s136
from tools import stage141_guarded_asymmetry_shortlist as s141
from tools import stage152_multiasset_playbook_frontier as s152

TARGET_MONTHLY_MIN = s136.TARGET_MONTHLY_MIN
TARGET_MONTHLY_MAX = s136.TARGET_MONTHLY_MAX


def _with_meta(item: dict[str, Any], *, track: str, branch: bool, anchor_name: str | None = None) -> dict[str, Any]:
    out = s152._with_meta(item, track=track, branch=branch, anchor_name=anchor_name)
    out.setdefault("meta", {})
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
            "mainline_live_dynlev_fix8_lock18_lb26_buf048_cd18",
            "主线 phase154：在 fix8_lock18 上做小步结构放松，优先测技术面提频，不硬改 runtime。",
            {
                "strategy_params.breakout_lookback": 26,
                "strategy_params.breakout_atr_buffer": 0.48,
                "strategy_params.cooldown_bars": 18,
                "filters.adx_floor": 28,
                "filters.btc_breakout_atr_buffer": 0.95,
                "money_management.stake_scale.bnb_long": 1.05,
                "money_management.take_profit_pct": 1.30,
                "money_management.trailing_profit.activation_pnl_pct": 0.58,
                "money_management.trailing_profit.giveback_ratio": 0.30,
                "money_management.trailing_profit.min_lock_pnl_pct": 0.14,
            },
        ),
        (
            "mainline_live_dynlev_fix8_lock18_lb24_buf046_cd16",
            "主线 phase154：继续提频，但仍用硬保护单和动态杠杆兜底，不走纯松门槛。",
            {
                "strategy_params.breakout_lookback": 24,
                "strategy_params.breakout_atr_buffer": 0.46,
                "strategy_params.cooldown_bars": 16,
                "filters.adx_floor": 26,
                "filters.btc_breakout_atr_buffer": 0.92,
                "money_management.stake_scale.bnb_long": 1.08,
                "money_management.take_profit_pct": 1.24,
                "money_management.trailing_profit.activation_pnl_pct": 0.54,
                "money_management.trailing_profit.giveback_ratio": 0.28,
                "money_management.trailing_profit.min_lock_pnl_pct": 0.12,
            },
        ),
        (
            "mainline_live_dynlev_fix8_lock18_lb24_buf044_cd14",
            "主线 phase154：更激进的消息面+技术面提频探针，只保留在研究层。",
            {
                "strategy_params.breakout_lookback": 24,
                "strategy_params.breakout_atr_buffer": 0.44,
                "strategy_params.cooldown_bars": 14,
                "filters.adx_floor": 26,
                "filters.btc_breakout_atr_buffer": 0.90,
                "execution_guard.pause_bars": 6,
                "money_management.stake_scale.bnb_long": 1.10,
                "money_management.take_profit_pct": 1.20,
                "money_management.trailing_profit.activation_pnl_pct": 0.50,
                "money_management.trailing_profit.giveback_ratio": 0.27,
                "money_management.trailing_profit.min_lock_pnl_pct": 0.10,
            },
        ),
    ]

    for name, note, patch in variants:
        out.append(
            _with_meta(
                s88._make_mainline_variant(base, name=name, note=note, patch=patch),
                track="mainline_event_freq",
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
                name="btc_breakout_long_event_lb18_atr054_adx20_cd3_s060",
                note="BTC phase154：保留事件 long，但把确认前提半档，测试能否在近2年/WF里真正起量。",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 18,
                    "filters.btc_breakout_atr_buffer": 0.54,
                    "strategy_params.cooldown_bars": 3,
                    "filters.btc_adx_floor": 20,
                    "money_management.stake_scale.btc_long": 0.60,
                },
            ),
            track="btc_event_breakout_fast",
            anchor_name="btc_breakout_long_event_lb20_atr060_adx24_s050",
        )
    if btc_short is not None:
        add(
            s88._make_variant(
                btc_short,
                name="btc_retest_short_event_lb18_atr056_adx20_cd3_s070",
                note="BTC phase154：空腿不删，但继续走回踩失败确认，不追第一脚。",
                family="short",
                patch={
                    "strategy_params.breakout_lookback": 18,
                    "filters.btc_breakout_atr_buffer": 0.56,
                    "strategy_params.cooldown_bars": 3,
                    "filters.btc_adx_floor": 20,
                    "filters.btc_short_pullback_atr": 0.88,
                    "money_management.stake_scale.btc_short": 0.70,
                },
            ),
            track="btc_retest_short_fast",
            anchor_name="btc_retest_short_event_lb20_atr060_adx24_s072",
        )
    if btc_dual is not None:
        add(
            s88._make_variant(
                btc_dual,
                name="btc_dual_fast_trend_dynlev_fix9_cd3",
                note="BTC phase154：dual 路径继续保留，只做更快重算和更轻止盈。",
                family="dual",
                patch={
                    "strategy_params.cooldown_bars": 3,
                    "portfolio.dynamic_leverage.enabled": True,
                    "portfolio.dynamic_leverage.min": 4.0,
                    "portfolio.dynamic_leverage.max": 9.0,
                    "money_management.capital_slices": 9,
                    "money_management.take_profit_pct": 1.08,
                    "money_management.trailing_profit.activation_pnl_pct": 0.44,
                    "money_management.trailing_profit.giveback_ratio": 0.28,
                    "money_management.trailing_profit.min_lock_pnl_pct": 0.10,
                    "money_management.stake_scale.btc_long": 0.60,
                    "money_management.stake_scale.btc_short": 0.72,
                },
            ),
            track="btc_dual_fast",
            anchor_name="btc_dual_fast_trend_dynlev_fix8",
        )

    if eth_long is not None:
        add(
            s88._make_variant(
                eth_long,
                name="eth_reclaim_long_lb11_atr042_adx15_cd1_s076",
                note="ETH phase154：继续围绕 reclaim 最强簇，先提密度，再让近2年/WF收口。",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 11,
                    "strategy_params.breakout_atr_buffer": 0.42,
                    "strategy_params.cooldown_bars": 1,
                    "filters.adx_floor": 15,
                    "money_management.stake_scale.eth_long": 0.76,
                },
            ),
            track="eth_reclaim_density",
            anchor_name="eth_reclaim_long_lb12_atr043_adx16_s060",
        )
        add(
            s88._make_variant(
                eth_long,
                name="eth_reclaim_long_lb10_atr041_adx14_cd1_s080",
                note="ETH phase154：更激进的 reclaim second-leg，专门测能否提频但不把 WF 打坏。",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 10,
                    "strategy_params.breakout_atr_buffer": 0.41,
                    "strategy_params.cooldown_bars": 1,
                    "filters.adx_floor": 14,
                    "money_management.stake_scale.eth_long": 0.80,
                },
            ),
            track="eth_reclaim_aggressive",
            anchor_name="eth_reclaim_long_lb12_atr043_adx16_s060",
        )
        add(
            s88._make_variant(
                eth_long,
                name="eth_reclaim_long_lb12_atr042_adx15_cd1_s072",
                note="ETH phase154：保留 lb12 慢半拍确认，但同步提密度，防止只押 lb11。",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 12,
                    "strategy_params.breakout_atr_buffer": 0.42,
                    "strategy_params.cooldown_bars": 1,
                    "filters.adx_floor": 15,
                    "money_management.stake_scale.eth_long": 0.72,
                },
            ),
            track="eth_reclaim_density",
            anchor_name="eth_reclaim_long_lb12_atr043_adx16_s060",
        )
    if eth_short is not None:
        add(
            s88._make_variant(
                eth_short,
                name="eth_retest_short_trend_lb18_atr054_adx18_cd1_s072",
                note="ETH phase154：short 只保留回踩失败确认版，不让空腿断代。",
                family="short",
                patch={
                    "strategy_params.breakout_lookback": 18,
                    "strategy_params.breakout_atr_buffer": 0.54,
                    "strategy_params.cooldown_bars": 1,
                    "filters.adx_floor": 18,
                    "money_management.stake_scale.eth_short": 0.72,
                },
            ),
            track="eth_short_confirm",
            anchor_name="eth_retest_short_trend_lb20_atr060_adx24_s068",
        )

    if sol_long is not None:
        add(
            s88._make_variant(
                sol_long,
                name="sol_reclaim_long_core_adx18_cd3_lb16_zone022_s058",
                note="SOL phase154：long 不删，改成更快的 reclaim/pullback 混合版。",
                family="long",
                patch={
                    "sr_entries.lookback_4h": 16,
                    "sr_entries.zone_atr_mult": 0.22,
                    "sr_entries.stake_scale": 0.58,
                    "sr_entries.cooldown_bars": 3,
                },
            ),
            track="sol_reclaim_density",
            anchor_name="sol_pullback_long_core_adx26_cd6_lb22_zone026_s040",
        )
        add(
            s88._make_variant(
                sol_long,
                name="sol_pullback_long_core_adx20_cd3_lb16_zone022_s054",
                note="SOL phase154：继续 pullback long，但要求更快回收与更窄 zone。",
                family="long",
                patch={
                    "sr_entries.lookback_4h": 16,
                    "sr_entries.zone_atr_mult": 0.22,
                    "sr_entries.stake_scale": 0.54,
                    "sr_entries.cooldown_bars": 3,
                },
            ),
            track="sol_pullback_density",
            anchor_name="sol_pullback_long_core_adx26_cd6_lb22_zone026_s040",
        )
    if sol_short is not None:
        add(
            s88._make_variant(
                sol_short,
                name="sol_fast_trend_short_guarded_lb14_atr053_adx18_cd3_s072",
                note="SOL phase154：short 路径继续保留，只做更快确认与更轻仓。",
                family="short",
                patch={
                    "strategy_params.breakout_lookback": 14,
                    "strategy_params.breakout_atr_buffer": 0.53,
                    "strategy_params.cooldown_bars": 3,
                    "filters.adx_floor": 18,
                    "money_management.stake_scale.sol_short": 0.72,
                },
            ),
            track="sol_short_guarded_fast",
            anchor_name="sol_fast_trend_short_guarded_lb18_atr060_adx24_s068",
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
    name = str(row.get("name") or "")
    target_monthly = s136._target_monthly(row, branch=branch)

    bonus = 0.0
    penalty = 0.0

    if not branch:
        if recent_trades >= 24 and wf_trades >= 12:
            bonus += 8.0
        if recent_monthly >= 0.020 and wf_monthly >= 0.015:
            bonus += 8.0
        if target_monthly >= 0.026:
            bonus += 8.0
        if 0.10 <= event_share <= 0.70:
            bonus += 3.0
        if name.startswith("mainline_live_dynlev_fix8_lock18_lb"):
            bonus += 4.0
        if recent_trades == 0 or wf_trades == 0:
            penalty += 20.0
        if wf_monthly <= 0.0 or wf_pf < 1.2:
            penalty += 14.0
        if recent_monthly <= 0.0 or recent_pf < 1.2:
            penalty += 10.0
        return float(base + bonus - penalty)

    sym = str(row.get("symbol") or "").lower()
    fam = str(row.get("family") or "").lower()

    if sym == "eth" and fam == "long":
        if recent_trades >= 24 and wf_trades >= 18:
            bonus += 10.0
        if recent_monthly >= 0.020 and wf_monthly >= 0.020:
            bonus += 12.0
        if target_monthly >= 0.026:
            bonus += 10.0
        if plateau_q >= 0.45 and neighbor_count >= 3:
            bonus += 8.0
        if track in {"eth_reclaim_density", "eth_reclaim_aggressive"}:
            bonus += 4.0
        if wf_dd > 0.06:
            penalty += 8.0
        if recent_trades < 18 or wf_trades < 12:
            penalty += 10.0
        if recent_monthly > max(0.0, wf_monthly * 2.2) and plateau_q < 0.35:
            penalty += 10.0

    if sym == "eth" and fam == "short":
        if recent_monthly > 0.0 and wf_monthly > 0.0:
            bonus += 6.0
        if recent_trades >= 10 and wf_trades >= 10:
            bonus += 5.0
        if wf_pf >= 1.1:
            bonus += 4.0
        if wf_dd <= 0.08:
            bonus += 3.0
        if recent_trades < 6 or wf_trades < 8:
            penalty += 8.0
        if wf_monthly <= 0.0 or wf_pf < 1.0:
            penalty += 8.0

    if sym == "btc":
        if recent_monthly > 0.0 and wf_monthly > 0.0:
            bonus += 6.0
        if recent_trades >= 8 and wf_trades >= 8:
            bonus += 5.0
        if fam == "dual" and recent_pf >= 1.2 and wf_pf >= 1.1:
            bonus += 4.0
        if target_monthly >= 0.01:
            bonus += 3.0
        if recent_trades == 0 or wf_trades == 0:
            penalty += 14.0
        if wf_monthly <= 0.0:
            penalty += 8.0
        if wf_pf < 1.0:
            penalty += 6.0

    if sym == "sol":
        if recent_monthly > 0.0 and wf_monthly > 0.0:
            bonus += 8.0
        if recent_trades >= 8 and wf_trades >= 6:
            bonus += 4.0
        if target_monthly >= 0.015:
            bonus += 3.0
        if track in {"sol_reclaim_density", "sol_pullback_density", "sol_short_guarded_fast"}:
            bonus += 3.0
        if wf_monthly <= 0.0:
            penalty += 12.0
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
    best_by_symbol = s152._top_per_symbol(branch_rows)
    split_rec, asset_status = s152._split_recommendation(best_by_symbol)

    lines: list[str] = []
    lines.append("Stage154 多资产前沿（主线消息面提频 + ETH reclaim 密度 + BTC/SOL 保路）")
    lines.append("原则：主线继续稳在 fix8_lock18；分支围绕 ETH reclaim 做密度快刷，同时保留 BTC/SOL 多空路径；并把 schema guard 固化，减少重复报错。")
    lines.append(f"目标区间：{TARGET_MONTHLY_MIN*100:.1f}% - {TARGET_MONTHLY_MAX*100:.1f}% / 月")
    lines.append("")
    lines.append(f"- bug_guard=enabled | 修复对象: main={len(repaired_main)} | branch={len(repaired_branch)}")
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
        lines.append("- 结论：现在仍不拆 3 个模拟盘终端；先把资产剧本分开、执行终端保持一个。")
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
    lines.append("- 这轮不动 runtime；只做主线消息面提频快刷 + ETH reclaim 密度扩圈 + BTC/SOL 保路。")

    payload = {
        "mode": "multiasset_reclaim_momentum_frontier",
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
    ap = argparse.ArgumentParser(description="Stage154 multiasset reclaim momentum frontier")
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

    ref_row = s152._mainline_ref_row(root, cfg, data, initial_equity, full_start, full_end)
    main_map = {str(r.get("name")): s152._ensure_mainline_schema(copy.deepcopy(r), ref_row=ref_row, initial_equity=initial_equity, full_end=full_end) for r in main_rows}
    scanned_main: list[str] = []
    for item in _new_mainline_items():
        print(f"[stage154] main {item['name']}", flush=True)
        row = s90._run_mainline(root, cfg, data, item, initial_equity, full_start, full_end)
        row = s152._ensure_mainline_schema(row, ref_row=ref_row, initial_equity=initial_equity, full_end=full_end)
        main_map[str(row.get("name"))] = row
        scanned_main.append(str(row.get("name")))
    main_rows = _finalize_rows(list(main_map.values()), branch=False)

    branch_map = {str(r.get("name")): copy.deepcopy(r) for r in branch_rows}
    scanned_branch: list[str] = []
    for item in _new_branch_items():
        print(f"[stage154] branch {item['name']}", flush=True)
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

    frontier_txt = raw / "stage154_multiasset_reclaim_momentum_frontier_latest.txt"
    frontier_json = raw / "stage154_multiasset_reclaim_momentum_frontier_latest.json"
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
        "mode": "multiasset_reclaim_momentum_frontier",
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
    manifest_path = raw / "stage154_multiasset_reclaim_momentum_frontier_manifest_latest.json"
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
