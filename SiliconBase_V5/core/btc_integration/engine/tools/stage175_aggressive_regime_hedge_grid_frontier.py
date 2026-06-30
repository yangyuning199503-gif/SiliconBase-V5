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
from tools import stage165_composite_hedge_ladder_frontier as s165

TARGET_MONTHLY_MIN = s136.TARGET_MONTHLY_MIN
TARGET_MONTHLY_MAX = s136.TARGET_MONTHLY_MAX


def _with_meta(item: dict[str, Any], *, track: str, branch: bool, anchor_name: str | None = None, playbook: str = "base") -> dict[str, Any]:
    return s165._with_meta(item, track=track, branch=branch, anchor_name=anchor_name, playbook=playbook)


def _stage91_active_map(branch_json: Path) -> dict[str, str]:
    return s165._stage91_active_map(branch_json)


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
        name="mainline_live_dynlev_fix8_lock18_event_ladder_lb22_buf044_cd4_add4_step14",
        note="主线 stage175：事件确认后才放大，trend 才 ladder，不把网格硬塞进趋势主线。",
        patch={
            "strategy_params.breakout_lookback": 22,
            "strategy_params.breakout_atr_buffer": 0.44,
            "strategy_params.cooldown_bars": 4,
            "filters.adx_floor": 24,
            "execution_guard.pause_bars": 4,
            "strategy_params.pyramiding_max_adds": 4,
            "strategy_params.add_step_atr": 1.4,
            "strategy_params.add_risk_fraction": 0.20,
            "strategy_params.breakeven_atr": 1.6,
            "money_management.stake_scale.bnb_long": 1.42,
            "money_management.stake_scale.btc_short": 5.90,
            "money_management.take_profit_pct": 1.20,
            "money_management.trailing_profit.activation_pnl_pct": 0.44,
            "money_management.trailing_profit.giveback_ratio": 0.24,
            "money_management.trailing_profit.min_lock_pnl_pct": 0.08,
        },
        track="mainline_event_ladder",
        playbook="mainline_event_ladder",
    )
    add(
        "mainline_live_dynlev_fix8_lock18",
        name="mainline_live_dynlev_fix8_lock18_reclaim_satellite_lb20_buf042_cd3_add5_step12",
        note="主线 stage175：更激进的 satellite 重入，只在 BNB 主腿延续时提高切片密度。",
        patch={
            "strategy_params.breakout_lookback": 20,
            "strategy_params.breakout_atr_buffer": 0.42,
            "strategy_params.cooldown_bars": 3,
            "filters.adx_floor": 22,
            "execution_guard.pause_bars": 3,
            "strategy_params.pyramiding_max_adds": 5,
            "strategy_params.add_step_atr": 1.2,
            "strategy_params.add_risk_fraction": 0.18,
            "strategy_params.breakeven_atr": 1.4,
            "money_management.stake_scale.bnb_long": 1.50,
            "money_management.stake_scale.btc_short": 6.20,
            "money_management.take_profit_pct": 1.14,
            "money_management.trailing_profit.activation_pnl_pct": 0.40,
            "money_management.trailing_profit.giveback_ratio": 0.22,
            "money_management.trailing_profit.min_lock_pnl_pct": 0.06,
        },
        track="mainline_reclaim_satellite",
        playbook="mainline_reclaim_satellite",
    )
    add(
        "mainline_live_dynlev_fix8_lock18",
        name="mainline_live_dynlev_fix8_lock18_failure_beta_hedge_lb24_buf048_cd5_btc680",
        note="主线 stage175：失败突破时加重 BTC beta hedge，避免 BNB 主腿一旦失效就完全裸露。",
        patch={
            "strategy_params.breakout_lookback": 24,
            "strategy_params.breakout_atr_buffer": 0.48,
            "strategy_params.cooldown_bars": 5,
            "filters.adx_floor": 24,
            "execution_guard.pause_bars": 4,
            "strategy_params.pyramiding_max_adds": 2,
            "strategy_params.add_step_atr": 1.8,
            "strategy_params.add_risk_fraction": 0.16,
            "strategy_params.breakeven_atr": 1.9,
            "money_management.stake_scale.bnb_long": 1.24,
            "money_management.stake_scale.btc_short": 6.80,
            "money_management.take_profit_pct": 1.28,
            "money_management.trailing_profit.activation_pnl_pct": 0.46,
            "money_management.trailing_profit.giveback_ratio": 0.23,
            "money_management.trailing_profit.min_lock_pnl_pct": 0.08,
        },
        track="mainline_failure_beta_hedge",
        playbook="mainline_failure_beta_hedge",
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
                name="btc_squeeze_follow_long_lb14_atr048_adx18_s060",
                note="BTC stage175：只在趋势/squeeze 共振时提频，不在震荡里硬追。",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 14,
                    "strategy_params.breakout_atr_buffer": 0.48,
                    "strategy_params.cooldown_bars": 3,
                    "filters.adx_floor": 18,
                    "money_management.stake_scale.btc_long": 0.60,
                    "money_management.take_profit_pct": 1.18,
                    "money_management.trailing_profit.activation_pnl_pct": 0.44,
                    "money_management.trailing_profit.giveback_ratio": 0.24,
                },
            ),
            track="btc_squeeze_follow",
            anchor_name="btc_breakout_long_event_lb20_atr060_adx24_s050",
            playbook="btc_squeeze_follow",
        )
    if btc_short is not None:
        add(
            s88._make_variant(
                btc_short,
                name="btc_break_fail_short_lb16_atr054_adx18_cd1_s080",
                note="BTC stage175：只做失败突破后的 short，不和主趋势腿抢方向。",
                family="short",
                patch={
                    "strategy_params.breakout_lookback": 16,
                    "strategy_params.breakout_atr_buffer": 0.54,
                    "strategy_params.cooldown_bars": 1,
                    "filters.adx_floor": 18,
                    "money_management.stake_scale.btc_short": 0.80,
                    "money_management.take_profit_pct": 1.04,
                    "money_management.trailing_profit.activation_pnl_pct": 0.40,
                    "money_management.trailing_profit.giveback_ratio": 0.23,
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
                name="btc_dual_hedge_band_dynlev_fix10_cd1",
                note="BTC stage175：保留双向腿，但只把对冲带放在失败/回踩情形，不做常驻双边。",
                family="dual",
                patch={
                    "strategy_params.cooldown_bars": 1,
                    "filters.adx_floor": 16,
                    "money_management.stake_scale.btc_long": 0.62,
                    "money_management.stake_scale.btc_short": 0.92,
                    "money_management.take_profit_pct": 1.18,
                    "money_management.trailing_profit.activation_pnl_pct": 0.42,
                    "money_management.trailing_profit.giveback_ratio": 0.24,
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
                name="eth_event_drift_long_lb9_atr042_adx15_s050",
                note="ETH stage175：事件后不追第一根，主打 1-3 根 drift 延续。",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 9,
                    "strategy_params.breakout_atr_buffer": 0.42,
                    "strategy_params.cooldown_bars": 2,
                    "filters.adx_floor": 15,
                    "money_management.stake_scale.eth_long": 0.50,
                    "money_management.take_profit_pct": 1.26,
                    "money_management.trailing_profit.activation_pnl_pct": 0.46,
                    "money_management.trailing_profit.giveback_ratio": 0.25,
                },
            ),
            track="eth_event_drift",
            anchor_name="eth_breakout_long_follow_lb16_atr050_adx22_s034",
            playbook="eth_event_drift",
        )
        add(
            s88._make_variant(
                eth_long,
                name="eth_squeeze_follow_long_lb9_atr040_adx15_s048",
                note="ETH stage175：拥挤/流向同向时走 squeeze follow，和 reclaim 分开验证。",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 9,
                    "strategy_params.breakout_atr_buffer": 0.40,
                    "strategy_params.cooldown_bars": 1,
                    "filters.adx_floor": 15,
                    "money_management.stake_scale.eth_long": 0.48,
                    "money_management.take_profit_pct": 1.28,
                    "money_management.trailing_profit.activation_pnl_pct": 0.44,
                    "money_management.trailing_profit.giveback_ratio": 0.24,
                },
            ),
            track="eth_squeeze_follow",
            anchor_name="eth_breakout_long_follow_lb16_atr050_adx22_s034",
            playbook="eth_squeeze_follow",
        )
        add(
            s88._make_variant(
                eth_long,
                name="eth_reclaim_beta_long_lb11_atr042_adx15_cd1_s066",
                note="ETH stage175：reclaim 继续保留，但更激进地做 beta-style 二段进场。",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 11,
                    "strategy_params.breakout_atr_buffer": 0.42,
                    "strategy_params.cooldown_bars": 1,
                    "filters.adx_floor": 15,
                    "money_management.stake_scale.eth_long": 0.66,
                    "money_management.take_profit_pct": 1.22,
                    "money_management.trailing_profit.activation_pnl_pct": 0.45,
                    "money_management.trailing_profit.giveback_ratio": 0.25,
                },
            ),
            track="eth_reclaim_beta",
            anchor_name="eth_reclaim_long_lb12_atr043_adx16_s060",
            playbook="eth_reclaim_beta",
        )
    if eth_short is not None:
        add(
            s88._make_variant(
                eth_short,
                name="eth_panic_retest_short_lb18_atr056_adx22_cd1_s072",
                note="ETH stage175：消息冲击后只做 panic retest short，不把空腿删掉。",
                family="short",
                patch={
                    "strategy_params.breakout_lookback": 18,
                    "strategy_params.breakout_atr_buffer": 0.56,
                    "strategy_params.cooldown_bars": 1,
                    "filters.adx_floor": 22,
                    "money_management.stake_scale.eth_short": 0.72,
                    "money_management.take_profit_pct": 1.05,
                    "money_management.trailing_profit.activation_pnl_pct": 0.40,
                    "money_management.trailing_profit.giveback_ratio": 0.23,
                },
            ),
            track="eth_panic_retest_short",
            anchor_name="eth_retest_short_trend_lb20_atr060_adx24_s068",
            playbook="eth_panic_retest_short",
        )
    if eth_shock is not None:
        add(
            s88._make_variant(
                eth_shock,
                name="eth_shock_flip_short_lb14_atr050_adx22_s080",
                note="ETH stage175：冲击失速后直接 flip short，作为 long 簇的失败反手。",
                family="short",
                patch={
                    "strategy_params.breakout_lookback": 14,
                    "strategy_params.breakout_atr_buffer": 0.50,
                    "strategy_params.cooldown_bars": 1,
                    "filters.adx_floor": 22,
                    "money_management.stake_scale.eth_short": 0.80,
                    "money_management.take_profit_pct": 1.04,
                    "money_management.trailing_profit.activation_pnl_pct": 0.39,
                    "money_management.trailing_profit.giveback_ratio": 0.22,
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
                name="sol_range_ladder_long_adx22_cd2_lb18_zone022_s052",
                note="SOL stage175：grid 只留在 range/pullback，趋势行情不硬开网格。",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 18,
                    "strategy_params.breakout_atr_buffer": 0.52,
                    "strategy_params.cooldown_bars": 2,
                    "filters.adx_floor": 22,
                    "money_management.stake_scale.sol_long": 0.52,
                    "money_management.take_profit_pct": 1.18,
                    "money_management.trailing_profit.activation_pnl_pct": 0.42,
                    "money_management.trailing_profit.giveback_ratio": 0.24,
                },
            ),
            track="sol_range_ladder",
            anchor_name=str(sol_long.get("name")),
            playbook="sol_range_ladder",
        )
        add(
            s88._make_variant(
                sol_long,
                name="sol_pullback_grid_long_adx24_cd3_lb20_zone024_s050",
                note="SOL stage175：更激进的 pullback-grid，只在震荡/回踩状态使用。",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 20,
                    "strategy_params.breakout_atr_buffer": 0.50,
                    "strategy_params.cooldown_bars": 3,
                    "filters.adx_floor": 24,
                    "money_management.stake_scale.sol_long": 0.50,
                    "money_management.take_profit_pct": 1.16,
                    "money_management.trailing_profit.activation_pnl_pct": 0.41,
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
                name="sol_guarded_short_accel_lb14_atr052_adx18_cd1_s076",
                note="SOL stage175：保留空腿，但只在破位失败+拥挤确认时加速。",
                family="short",
                patch={
                    "strategy_params.breakout_lookback": 14,
                    "strategy_params.breakout_atr_buffer": 0.52,
                    "strategy_params.cooldown_bars": 1,
                    "filters.adx_floor": 18,
                    "money_management.stake_scale.sol_short": 0.76,
                    "money_management.take_profit_pct": 1.02,
                    "money_management.trailing_profit.activation_pnl_pct": 0.38,
                    "money_management.trailing_profit.giveback_ratio": 0.22,
                },
            ),
            track="sol_guarded_short_accel",
            anchor_name=str(sol_short.get("name")),
            playbook="sol_guarded_short_accel",
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
    lines.append("Stage175 激进状态机 / 对冲 / 网格化前沿")
    lines.append("原则：trend 才 ladder，range/pullback 才 grid，hedge 只做 failure/beta overlay；重大事件必须和技术面/衍生品确认一起出现。")
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
        lines.append("- 结论：继续 1 个 branch 终端；先让各资产剧本过近2年+WF，再决定是否拆终端。")
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
        "mode": "aggressive_regime_hedge_grid_frontier",
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
    ap = argparse.ArgumentParser(description="Stage175 aggressive regime hedge/grid frontier")
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
        raise SystemExit("missing mainline reference for stage175")
    ref_row = s136._run_mainline(root, cfg, data, _with_meta(ref_item, track="base", branch=False), initial_equity, full_start, full_end)

    main_map = {str(r.get("name")): s161._ensure_mainline_row(r, ref_row, initial_equity, full_end) for r in main_rows}
    scanned_main: list[str] = []
    for item in _new_mainline_items():
        print(f"[stage175] main {item['name']}", flush=True)
        row = s136._run_mainline(root, cfg, data, item, initial_equity, full_start, full_end)
        row = s161._ensure_mainline_row(row, ref_row, initial_equity, full_end)
        main_map[str(row.get("name"))] = row
        scanned_main.append(str(row.get("name")))
    main_rows = s161._finalize_rows(list(main_map.values()), branch=False)

    branch_map = {str(r.get("name")): s161._ensure_branch_row(r, initial_equity) for r in branch_rows}
    scanned_branch: list[str] = []
    for item in _new_branch_items():
        print(f"[stage175] branch {item['name']}", flush=True)
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

    frontier_txt = raw / "stage175_aggressive_regime_hedge_grid_frontier_latest.txt"
    frontier_json = raw / "stage175_aggressive_regime_hedge_grid_frontier_latest.json"
    _write_report(frontier_txt, frontier_json, main_rows, branch_rows, repaired_main, repaired_branch, scanned_main, scanned_branch, active_map)

    manifest = {
        "mode": "aggressive_regime_hedge_grid_frontier",
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
    manifest_path = raw / "stage175_aggressive_regime_hedge_grid_frontier_manifest_latest.json"
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
