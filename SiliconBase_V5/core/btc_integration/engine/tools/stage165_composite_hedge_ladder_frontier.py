from __future__ import annotations

import argparse
import json
import sys
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

TARGET_MONTHLY_MIN = s136.TARGET_MONTHLY_MIN
TARGET_MONTHLY_MAX = s136.TARGET_MONTHLY_MAX


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
                if isinstance(active, dict):
                    out[sym] = str(active.get("name") or "")
                elif isinstance(active, str):
                    out[sym] = active
    elif isinstance(asset_summary, dict):
        for sym in out:
            row = asset_summary.get(sym) or asset_summary.get(sym.lower())
            if isinstance(row, dict):
                active = row.get("active")
                if isinstance(active, dict):
                    out[sym] = str(active.get("name") or "")
                elif isinstance(active, str):
                    out[sym] = active
    return out


def _new_mainline_items() -> list[dict[str, Any]]:
    item_map = {str(item.get("name")): item for item in s88._mainline_items()}
    out: list[dict[str, Any]] = []

    def add(base_name: str, *, name: str, note: str, patch: dict[str, Any], track: str, playbook: str) -> None:
        base = item_map.get(base_name)
        if base is None:
            return
        out.append(
            _with_meta(
                s88._make_mainline_variant(base, name=name, note=note, patch=patch),
                track=track,
                branch=False,
                anchor_name=base_name,
                playbook=playbook,
            )
        )

    add(
        "mainline_live_dynlev_fix8_lock18",
        name="mainline_live_dynlev_fix8_lock18_ladder_pyramid_lb24_buf046_cd8_add4_step18",
        note="主线 stage165：把 grid/ladder 思路收敛成 banded re-entry + 多次小加仓，不改主骨架。",
        patch={
            "strategy_params.breakout_lookback": 24,
            "strategy_params.breakout_atr_buffer": 0.46,
            "strategy_params.cooldown_bars": 8,
            "filters.adx_floor": 26,
            "execution_guard.pause_bars": 4,
            "strategy_params.pyramiding_max_adds": 4,
            "strategy_params.add_step_atr": 1.8,
            "strategy_params.add_risk_fraction": 0.18,
            "strategy_params.breakeven_atr": 1.8,
            "money_management.stake_scale.bnb_long": 1.34,
            "money_management.stake_scale.btc_short": 5.80,
            "money_management.take_profit_pct": 1.42,
            "money_management.trailing_profit.activation_pnl_pct": 0.46,
            "money_management.trailing_profit.giveback_ratio": 0.24,
            "money_management.trailing_profit.min_lock_pnl_pct": 0.08,
        },
        track="mainline_ladder_pyramid",
        playbook="mainline_ladder_pyramid",
    )
    add(
        "mainline_live_dynlev_fix8_lock18",
        name="mainline_live_dynlev_fix8_lock18_banded_reentry_lb22_buf044_cd6_add3_step16",
        note="主线 stage165：把类网格思路限定成趋势内 banded re-entry，不做全时段裸网格。",
        patch={
            "strategy_params.breakout_lookback": 22,
            "strategy_params.breakout_atr_buffer": 0.44,
            "strategy_params.cooldown_bars": 6,
            "filters.adx_floor": 24,
            "execution_guard.pause_bars": 4,
            "strategy_params.pyramiding_max_adds": 3,
            "strategy_params.add_step_atr": 1.6,
            "strategy_params.add_risk_fraction": 0.16,
            "strategy_params.breakeven_atr": 1.7,
            "money_management.stake_scale.bnb_long": 1.30,
            "money_management.stake_scale.btc_short": 5.60,
            "money_management.take_profit_pct": 1.36,
            "money_management.trailing_profit.activation_pnl_pct": 0.44,
            "money_management.trailing_profit.giveback_ratio": 0.23,
            "money_management.trailing_profit.min_lock_pnl_pct": 0.07,
        },
        track="mainline_banded_reentry",
        playbook="mainline_banded_reentry",
    )
    add(
        "mainline_live_dynlev_fix8_lock18",
        name="mainline_live_dynlev_fix8_lock18_failure_hedge_lb24_buf048_cd8_btc640",
        note="主线 stage165：把对冲腿做成失败突破 hedge，而不是只依赖被动止盈止损。",
        patch={
            "strategy_params.breakout_lookback": 24,
            "strategy_params.breakout_atr_buffer": 0.48,
            "strategy_params.cooldown_bars": 8,
            "filters.adx_floor": 26,
            "execution_guard.pause_bars": 5,
            "strategy_params.pyramiding_max_adds": 2,
            "strategy_params.add_step_atr": 2.0,
            "strategy_params.add_risk_fraction": 0.15,
            "strategy_params.breakeven_atr": 2.0,
            "money_management.stake_scale.bnb_long": 1.24,
            "money_management.stake_scale.btc_short": 6.40,
            "money_management.take_profit_pct": 1.30,
            "money_management.trailing_profit.activation_pnl_pct": 0.42,
            "money_management.trailing_profit.giveback_ratio": 0.22,
            "money_management.trailing_profit.min_lock_pnl_pct": 0.08,
        },
        track="mainline_failure_hedge",
        playbook="mainline_failure_hedge",
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
    eth_shock = item_map.get("eth_short_shock_fast_lb16_atr052_adx22_s078") or item_map.get("eth_short_shock_control_lb18_adx26_s074")
    sol_long = item_map.get("sol_pullback_long_core_adx26_cd6_lb22_zone026_s040") or item_map.get("sol_long_core_soft_lb20_zone025_s042")
    sol_short = item_map.get("sol_fast_trend_short_guarded_lb18_atr060_adx24_s068") or item_map.get("sol_fast_trend_short_aggr_lb16_atr055_adx22_s076")

    if btc_long is not None:
        add(
            s88._make_variant(
                btc_long,
                name="btc_event_reclaim_long_lb18_atr056_adx20_cd2_s064",
                note="BTC stage165：事件突破后只做二段延续/回收，不追第一脚。",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 18,
                    "strategy_params.breakout_atr_buffer": 0.56,
                    "strategy_params.cooldown_bars": 2,
                    "filters.adx_floor": 20,
                    "money_management.stake_scale.btc_long": 0.64,
                    "money_management.take_profit_pct": 1.20,
                    "money_management.trailing_profit.activation_pnl_pct": 0.46,
                    "money_management.trailing_profit.giveback_ratio": 0.25,
                },
            ),
            track="btc_event_reclaim",
            anchor_name="btc_breakout_long_event_lb20_atr060_adx24_s050",
            playbook="btc_event_reclaim",
        )
    if btc_short is not None:
        add(
            s88._make_variant(
                btc_short,
                name="btc_break_fail_short_lb18_atr056_adx20_cd2_s076",
                note="BTC stage165：失败突破 + retest short，作为 hedge 副腿保留。",
                family="short",
                patch={
                    "strategy_params.breakout_lookback": 18,
                    "strategy_params.breakout_atr_buffer": 0.56,
                    "strategy_params.cooldown_bars": 2,
                    "filters.adx_floor": 20,
                    "money_management.stake_scale.btc_short": 0.76,
                    "money_management.take_profit_pct": 1.06,
                    "money_management.trailing_profit.activation_pnl_pct": 0.40,
                    "money_management.trailing_profit.giveback_ratio": 0.24,
                },
            ),
            track="btc_break_fail_short",
            anchor_name="btc_retest_short_event_lb20_atr060_adx24_s072",
            playbook="btc_break_fail_short",
        )
    if btc_dual is not None:
        add(
            s88._make_variant(
                btc_dual,
                name="btc_dual_hedge_band_dynlev_fix9_cd2",
                note="BTC stage165：把对冲和双向保留做成 hedge-band，不让 BTC 只剩一个方向。",
                family="dual",
                patch={
                    "strategy_params.cooldown_bars": 2,
                    "filters.adx_floor": 18,
                    "money_management.stake_scale.btc_long": 0.56,
                    "money_management.stake_scale.btc_short": 0.92,
                    "money_management.take_profit_pct": 1.14,
                    "money_management.trailing_profit.activation_pnl_pct": 0.44,
                    "money_management.trailing_profit.giveback_ratio": 0.25,
                },
            ),
            track="btc_dual_hedge_band",
            anchor_name="btc_dual_fast_trend_dynlev_fix8",
            playbook="btc_dual_hedge_band",
        )

    if eth_long is not None:
        add(
            s88._make_variant(
                eth_long,
                name="eth_reclaim_ladder_long_lb11_atr043_adx16_cd2_s064",
                note="ETH stage165：围绕 reclaim 最强簇做 ladder re-entry，而不是单点追涨。",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 11,
                    "strategy_params.breakout_atr_buffer": 0.43,
                    "strategy_params.cooldown_bars": 2,
                    "filters.adx_floor": 16,
                    "money_management.stake_scale.eth_long": 0.64,
                    "money_management.take_profit_pct": 1.24,
                    "money_management.trailing_profit.activation_pnl_pct": 0.46,
                    "money_management.trailing_profit.giveback_ratio": 0.26,
                },
            ),
            track="eth_reclaim_ladder",
            anchor_name="eth_reclaim_long_lb12_atr043_adx16_s060",
            playbook="eth_reclaim_ladder",
        )
        add(
            s88._make_variant(
                eth_long,
                name="eth_reclaim_band_long_lb12_atr042_adx15_cd1_s068",
                note="ETH stage165：更激进的 banded re-entry，测试 reclaim 与高频补仓能否一起抬月化。",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 12,
                    "strategy_params.breakout_atr_buffer": 0.42,
                    "strategy_params.cooldown_bars": 1,
                    "filters.adx_floor": 15,
                    "money_management.stake_scale.eth_long": 0.68,
                    "money_management.take_profit_pct": 1.26,
                    "money_management.trailing_profit.activation_pnl_pct": 0.47,
                    "money_management.trailing_profit.giveback_ratio": 0.27,
                },
            ),
            track="eth_reclaim_band",
            anchor_name="eth_reclaim_long_lb12_atr043_adx16_s060",
            playbook="eth_reclaim_band",
        )
    if eth_short is not None:
        add(
            s88._make_variant(
                eth_short,
                name="eth_failure_pair_short_lb18_atr056_adx22_cd2_s072",
                note="ETH stage165：失败回踩 short，和 reclaim long 组合成真正的 pair book。",
                family="short",
                patch={
                    "strategy_params.breakout_lookback": 18,
                    "strategy_params.breakout_atr_buffer": 0.56,
                    "strategy_params.cooldown_bars": 2,
                    "filters.adx_floor": 22,
                    "money_management.stake_scale.eth_short": 0.72,
                    "money_management.take_profit_pct": 1.04,
                    "money_management.trailing_profit.activation_pnl_pct": 0.40,
                    "money_management.trailing_profit.giveback_ratio": 0.24,
                },
            ),
            track="eth_failure_pair_short",
            anchor_name="eth_retest_short_trend_lb20_atr060_adx24_s068",
            playbook="eth_failure_pair_short",
        )
    if eth_shock is not None:
        add(
            s88._make_variant(
                eth_shock,
                name="eth_shock_flip_short_lb16_atr052_adx24_s078",
                note="ETH stage165：保留更冲击型 flip short，只吃爆发后的承接失败。",
                family="short",
                patch={
                    "strategy_params.breakout_lookback": 16,
                    "strategy_params.breakout_atr_buffer": 0.52,
                    "strategy_params.cooldown_bars": 2,
                    "filters.adx_floor": 24,
                    "money_management.stake_scale.eth_short": 0.78,
                    "money_management.take_profit_pct": 1.06,
                    "money_management.trailing_profit.activation_pnl_pct": 0.42,
                    "money_management.trailing_profit.giveback_ratio": 0.25,
                },
            ),
            track="eth_shock_flip_short",
            anchor_name=str(eth_shock.get("name")),
            playbook="eth_shock_flip_short",
        )

    if sol_long is not None:
        add(
            s88._make_variant(
                sol_long,
                name="sol_range_ladder_long_adx24_cd4_lb20_zone024_s048",
                note="SOL stage165：把 grid 思路限制在区间/回踩 legs 上，测试更快的 range ladder。",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 20,
                    "strategy_params.breakout_atr_buffer": 0.48,
                    "strategy_params.cooldown_bars": 4,
                    "filters.adx_floor": 24,
                    "money_management.stake_scale.sol_long": 0.48,
                    "money_management.take_profit_pct": 1.18,
                    "money_management.trailing_profit.activation_pnl_pct": 0.42,
                    "money_management.trailing_profit.giveback_ratio": 0.25,
                },
            ),
            track="sol_range_ladder",
            anchor_name=str(sol_long.get("name")),
            playbook="sol_range_ladder",
        )
        add(
            s88._make_variant(
                sol_long,
                name="sol_pullback_grid_long_adx26_cd4_lb22_zone026_s046",
                note="SOL stage165：类网格的 pullback long，只在区间/回踩场景使用。",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 22,
                    "strategy_params.breakout_atr_buffer": 0.46,
                    "strategy_params.cooldown_bars": 4,
                    "filters.adx_floor": 26,
                    "money_management.stake_scale.sol_long": 0.46,
                    "money_management.take_profit_pct": 1.16,
                    "money_management.trailing_profit.activation_pnl_pct": 0.40,
                    "money_management.trailing_profit.giveback_ratio": 0.24,
                },
            ),
            track="sol_pullback_grid",
            anchor_name=str(sol_long.get("name")),
            playbook="sol_pullback_grid",
        )
    if sol_short is not None:
        add(
            s88._make_variant(
                sol_short,
                name="sol_fail_short_guarded_lb16_atr054_adx20_cd2_s072",
                note="SOL stage165：失败突破 short 保留，但继续 guarded，不做纯裸空。",
                family="short",
                patch={
                    "strategy_params.breakout_lookback": 16,
                    "strategy_params.breakout_atr_buffer": 0.54,
                    "strategy_params.cooldown_bars": 2,
                    "filters.adx_floor": 20,
                    "money_management.stake_scale.sol_short": 0.72,
                    "money_management.take_profit_pct": 1.04,
                    "money_management.trailing_profit.activation_pnl_pct": 0.40,
                    "money_management.trailing_profit.giveback_ratio": 0.24,
                },
            ),
            track="sol_fail_short_guarded",
            anchor_name=str(sol_short.get("name")),
            playbook="sol_fail_short_guarded",
        )

    return out


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
    best_by_symbol = s161._top_per_symbol(branch_rows)
    split_rec, asset_status = s161._split_recommendation(best_by_symbol)

    lines: list[str] = []
    lines.append("Stage165 组合式对冲 / 梯度 / 失败回踩前沿")
    lines.append("原则：不被单一建议框住；把 hedge、ladder、类网格、failure short、pair-book 巧妙组合，但仍以近2年+WF 防过拟合为硬过滤。")
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
            f"- {sym}: {p['name']} | {p['family']} | track={p['track']} | playbook={p.get('playbook','-')} | target_monthly={p['target_monthly']*100:.2f}% | 近2年={p['recent_monthly']*100:.2f}%/{p['recent_trades']}笔/PF{p['recent_pf']:.3f} | WF={p['wf_monthly']*100:.2f}%/{p['wf_trades']}笔/PF{p['wf_pf']:.3f} | status={asset_status.get(sym,'research_only')} | stage91_active={active_map.get(sym,'-')}"
        )
    lines.append("")
    lines.append("=== 终端拆分判断 ===")
    lines.append(f"- recommendation={split_rec}")
    if split_rec == "keep_single_branch_terminal":
        lines.append("- 结论：继续 1 个 branch 终端；先让 BTC/ETH/SOL 的组合腿真正过近2年+WF，再决定是否拆终端。")
    else:
        lines.append("- 结论：已有足够多资产接近独立提交条件，可以开始评估拆多终端。")
    lines.append("")
    lines.append("=== 结论 ===")
    if main_payload:
        top = main_payload[0]
        lines.append(f"- 主线第一名: {top['name']} | target_monthly={top['target_monthly']*100:.2f}% | gap_to_7.6={top['gap_to_floor']*100:.2f}%")
    if branch_payload:
        top = branch_payload[0]
        lines.append(f"- 分支总第一名: {top['name']} | {top.get('symbol','-')}|{top.get('family','-')} | playbook={top.get('playbook','-')} | target_monthly={top['target_monthly']*100:.2f}% | gap_to_7.6={top['gap_to_floor']*100:.2f}%")

    payload = {
        "mode": "composite_hedge_ladder_frontier",
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
    ap = argparse.ArgumentParser(description="Stage165 composite hedge/ladder frontier")
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
        raise SystemExit("missing mainline reference for stage165")
    ref_row = s136._run_mainline(root, cfg, data, _with_meta(ref_item, track="base", branch=False), initial_equity, full_start, full_end)

    main_map = {str(r.get("name")): s161._ensure_mainline_row(r, ref_row, initial_equity, full_end) for r in main_rows}
    scanned_main: list[str] = []
    for item in _new_mainline_items():
        print(f"[stage165] main {item['name']}", flush=True)
        row = s136._run_mainline(root, cfg, data, item, initial_equity, full_start, full_end)
        row = s161._ensure_mainline_row(row, ref_row, initial_equity, full_end)
        main_map[str(row.get("name"))] = row
        scanned_main.append(str(row.get("name")))
    main_rows = s161._finalize_rows(list(main_map.values()), branch=False)

    branch_map = {str(r.get("name")): s161._ensure_branch_row(r, initial_equity) for r in branch_rows}
    scanned_branch: list[str] = []
    for item in _new_branch_items():
        print(f"[stage165] branch {item['name']}", flush=True)
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

    frontier_txt = raw / "stage165_composite_hedge_ladder_frontier_latest.txt"
    frontier_json = raw / "stage165_composite_hedge_ladder_frontier_latest.json"
    _write_report(frontier_txt, frontier_json, main_rows, branch_rows, repaired_main, repaired_branch, scanned_main, scanned_branch, active_map)

    manifest = {
        "mode": "composite_hedge_ladder_frontier",
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
    manifest_path = raw / "stage165_composite_hedge_ladder_frontier_manifest_latest.json"
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
