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
        "mainline_core_satellite_dynlev_fix8_lock18",
        name="mainline_core_satellite_dynlev_fix8_lock18_evtpyr_bnb124_btc560_tp126_trail044",
        note="主线 stage163：不再围着死掉的 entry 邻域打转，改刷 core-satellite 事件卫星加速版。",
        patch={
            "strategy_params.cooldown_bars": 12,
            "filters.adx_floor": 24,
            "execution_guard.pause_bars": 5,
            "money_management.stake_scale.bnb_long": 1.24,
            "money_management.stake_scale.btc_short": 5.60,
            "money_management.take_profit_pct": 1.26,
            "money_management.trailing_profit.activation_pnl_pct": 0.44,
            "money_management.trailing_profit.giveback_ratio": 0.24,
            "money_management.trailing_profit.min_lock_pnl_pct": 0.08,
        },
        track="mainline_event_satellite",
        playbook="mainline_event_satellite",
    )
    add(
        "mainline_split_adx26_cd6_lb24_zone028",
        name="mainline_split_adx24_cd4_lb20_zone024_evtconfirm_bnb120_btc580_tp112_trail040",
        note="主线 stage163：转去 split 结构做激进提频，只在事件确认后放大，不再硬刷 fix8 邻域。",
        patch={
            "strategy_params.breakout_lookback": 20,
            "strategy_params.breakout_atr_buffer": 0.42,
            "strategy_params.cooldown_bars": 4,
            "filters.adx_floor": 24,
            "execution_guard.pause_bars": 4,
            "money_management.stake_scale.bnb_long": 1.20,
            "money_management.stake_scale.btc_short": 5.80,
            "money_management.take_profit_pct": 1.12,
            "money_management.trailing_profit.activation_pnl_pct": 0.40,
            "money_management.trailing_profit.giveback_ratio": 0.23,
            "money_management.trailing_profit.min_lock_pnl_pct": 0.07,
        },
        track="mainline_split_event_confirm",
        playbook="mainline_split_event_confirm",
    )
    add(
        "mainline_split_adx28_cd6_lb24_zone028",
        name="mainline_split_adx22_cd3_lb18_zone022_evtconfirm_bnb126_btc600_tp108_trail038",
        note="主线 stage163：更激进的 split 快版，只保留研究层验证事件后二段入场能否抬频。",
        patch={
            "strategy_params.breakout_lookback": 18,
            "strategy_params.breakout_atr_buffer": 0.40,
            "strategy_params.cooldown_bars": 3,
            "filters.adx_floor": 22,
            "execution_guard.pause_bars": 4,
            "money_management.stake_scale.bnb_long": 1.26,
            "money_management.stake_scale.btc_short": 6.00,
            "money_management.take_profit_pct": 1.08,
            "money_management.trailing_profit.activation_pnl_pct": 0.38,
            "money_management.trailing_profit.giveback_ratio": 0.22,
            "money_management.trailing_profit.min_lock_pnl_pct": 0.06,
        },
        track="mainline_split_event_confirm",
        playbook="mainline_split_event_confirm",
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
    eth_long = item_map.get("eth_breakout_long_follow_lb16_atr050_adx22_s034")
    eth_short = item_map.get("eth_retest_short_trend_lb20_atr060_adx24_s068")
    eth_shock = item_map.get("eth_short_shock_fast_lb16_atr052_adx22_s078") or item_map.get("eth_short_shock_control_lb18_adx26_s074")
    sol_long = item_map.get("sol_pullback_long_core_adx26_cd6_lb22_zone026_s040") or item_map.get("sol_long_core_soft_lb20_zone025_s042")
    sol_short = item_map.get("sol_fast_trend_short_guarded_lb18_atr060_adx24_s068") or item_map.get("sol_fast_trend_short_aggr_lb16_atr055_adx22_s076")

    if btc_long is not None:
        add(
            s88._make_variant(
                btc_long,
                name="btc_macro_drift_long_lb18_atr056_adx20_cd2_s060",
                note="BTC stage163：做宏观/ETF/大消息后的第二段延续，不追第一根。",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 18,
                    "strategy_params.breakout_atr_buffer": 0.56,
                    "strategy_params.cooldown_bars": 2,
                    "filters.adx_floor": 20,
                    "money_management.stake_scale.btc_long": 0.60,
                    "money_management.take_profit_pct": 1.18,
                    "money_management.trailing_profit.activation_pnl_pct": 0.46,
                    "money_management.trailing_profit.giveback_ratio": 0.25,
                },
            ),
            track="btc_macro_drift",
            anchor_name="btc_breakout_long_event_lb20_atr060_adx24_s050",
            playbook="btc_macro_drift",
        )
    if btc_short is not None:
        add(
            s88._make_variant(
                btc_short,
                name="btc_failure_short_lb16_atr054_adx18_cd2_s076",
                note="BTC stage163：失败回踩 short，更激进但只做二次确认。",
                family="short",
                patch={
                    "strategy_params.breakout_lookback": 16,
                    "strategy_params.breakout_atr_buffer": 0.54,
                    "strategy_params.cooldown_bars": 2,
                    "filters.adx_floor": 18,
                    "money_management.stake_scale.btc_short": 0.76,
                    "money_management.take_profit_pct": 1.04,
                    "money_management.trailing_profit.activation_pnl_pct": 0.40,
                    "money_management.trailing_profit.giveback_ratio": 0.24,
                },
            ),
            track="btc_failure_short",
            anchor_name="btc_retest_short_event_lb20_atr060_adx24_s072",
            playbook="btc_failure_short",
        )

    if eth_long is not None:
        add(
            s88._make_variant(
                eth_long,
                name="eth_reclaim_beta_long_lb12_atr042_adx15_cd2_s072",
                note="ETH stage163：围绕最强 reclaim 簇做更激进二段确认，优先提频。",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 12,
                    "strategy_params.breakout_atr_buffer": 0.42,
                    "strategy_params.cooldown_bars": 2,
                    "filters.adx_floor": 15,
                    "money_management.stake_scale.eth_long": 0.72,
                    "money_management.take_profit_pct": 1.20,
                    "money_management.trailing_profit.activation_pnl_pct": 0.44,
                    "money_management.trailing_profit.giveback_ratio": 0.26,
                },
            ),
            track="eth_reclaim_beta",
            anchor_name="eth_reclaim_long_lb12_atr043_adx16_s060",
            playbook="eth_reclaim_beta",
        )
        add(
            s88._make_variant(
                eth_long,
                name="eth_reclaim_beta_long_lb11_atr043_adx15_cd2_s068",
                note="ETH stage163：lb11 核心加速版，不让 reclaim 只剩一个点。",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 11,
                    "strategy_params.breakout_atr_buffer": 0.43,
                    "strategy_params.cooldown_bars": 2,
                    "filters.adx_floor": 15,
                    "money_management.stake_scale.eth_long": 0.68,
                    "money_management.take_profit_pct": 1.18,
                    "money_management.trailing_profit.activation_pnl_pct": 0.44,
                    "money_management.trailing_profit.giveback_ratio": 0.25,
                },
            ),
            track="eth_reclaim_beta",
            anchor_name="eth_reclaim_long_lb12_atr043_adx16_s060",
            playbook="eth_reclaim_beta",
        )
        add(
            s88._make_variant(
                eth_long,
                name="eth_squeeze_follow_long_lb10_atr041_adx15_cd2_s074",
                note="ETH stage163：保留挤仓延续路线，不让 reclaim 一条路垄断。",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 10,
                    "strategy_params.breakout_atr_buffer": 0.41,
                    "strategy_params.cooldown_bars": 2,
                    "filters.adx_floor": 15,
                    "money_management.stake_scale.eth_long": 0.74,
                    "money_management.take_profit_pct": 1.24,
                    "money_management.trailing_profit.activation_pnl_pct": 0.46,
                    "money_management.trailing_profit.giveback_ratio": 0.27,
                },
            ),
            track="eth_squeeze_follow",
            anchor_name="eth_reclaim_long_lb12_atr043_adx16_s060",
            playbook="eth_squeeze_follow",
        )

    if eth_short is not None:
        add(
            s88._make_variant(
                eth_short,
                name="eth_retest_short_accel_lb18_atr056_adx22_cd2_s072",
                note="ETH stage163：更快的 retest short，专吃二次失败段。",
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
            track="eth_retest_short_accel",
            anchor_name="eth_retest_short_trend_lb20_atr060_adx24_s068",
            playbook="eth_retest_short",
        )
    if eth_shock is not None:
        add(
            s88._make_variant(
                eth_shock,
                name="eth_shock_short_aggr_lb16_atr052_adx24_s074",
                note="ETH stage163：shock short 激进版，只在冲击后承接失败时做空。",
                family="short",
                patch={
                    "strategy_params.breakout_lookback": 16,
                    "strategy_params.breakout_atr_buffer": 0.52,
                    "strategy_params.cooldown_bars": 2,
                    "filters.adx_floor": 24,
                    "money_management.stake_scale.eth_short": 0.74,
                    "money_management.take_profit_pct": 1.06,
                    "money_management.trailing_profit.activation_pnl_pct": 0.42,
                    "money_management.trailing_profit.giveback_ratio": 0.25,
                },
            ),
            track="eth_shock_short",
            anchor_name=str(eth_shock.get("name")),
            playbook="eth_shock_short",
        )

    if sol_long is not None:
        add(
            s88._make_variant(
                sol_long,
                name="sol_beta_break_long_lb18_atr050_adx20_cd2_s060",
                note="SOL stage163：高 beta breakout / reclaim 混合长腿，先激进验证。",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 18,
                    "strategy_params.breakout_atr_buffer": 0.50,
                    "strategy_params.cooldown_bars": 2,
                    "filters.adx_floor": 20,
                    "money_management.stake_scale.sol_long": 0.60,
                    "money_management.take_profit_pct": 1.20,
                    "money_management.trailing_profit.activation_pnl_pct": 0.44,
                    "money_management.trailing_profit.giveback_ratio": 0.26,
                },
            ),
            track="sol_beta_break",
            anchor_name=str(sol_long.get("name")),
            playbook="sol_beta_break",
        )
        add(
            s88._make_variant(
                sol_long,
                name="sol_reclaim_beta_long_lb16_atr048_adx18_cd2_s058",
                note="SOL stage163：panic 后 reclaim 长腿，不再只守慢回踩。",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 16,
                    "strategy_params.breakout_atr_buffer": 0.48,
                    "strategy_params.cooldown_bars": 2,
                    "filters.adx_floor": 18,
                    "money_management.stake_scale.sol_long": 0.58,
                    "money_management.take_profit_pct": 1.18,
                    "money_management.trailing_profit.activation_pnl_pct": 0.42,
                    "money_management.trailing_profit.giveback_ratio": 0.25,
                },
            ),
            track="sol_reclaim_beta",
            anchor_name=str(sol_long.get("name")),
            playbook="sol_reclaim_beta",
        )
    if sol_short is not None:
        add(
            s88._make_variant(
                sol_short,
                name="sol_guarded_short_accel_lb16_atr054_adx20_cd2_s072",
                note="SOL stage163：guarded short 加速版，只吃趋势失败后的下压段。",
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
            track="sol_guarded_short_accel",
            anchor_name=str(sol_short.get("name")),
            playbook="sol_guarded_short",
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
    lines.append("Stage163 网页经验激进多资产前沿")
    lines.append("原则：不再围着主线死 entry 邻域打转；主线改刷 core-satellite / split 两条结构线。分支按 BTC、ETH、SOL 各自剧本激进快刷。")
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
        lines.append("- 结论：继续 1 个 branch 终端；先把 BTC/ETH/SOL 三套剧本做出更强近2年+WF，再谈拆 3 终端。")
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
        "mode": "web_aggressive_multiasset_frontier",
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
    ap = argparse.ArgumentParser(description="Stage163 web aggressive multiasset frontier")
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
        raise SystemExit("missing mainline reference for stage163")
    ref_row = s136._run_mainline(root, cfg, data, _with_meta(ref_item, track="base", branch=False), initial_equity, full_start, full_end)

    main_map = {str(r.get("name")): s161._ensure_mainline_row(r, ref_row, initial_equity, full_end) for r in main_rows}
    scanned_main: list[str] = []
    for item in _new_mainline_items():
        print(f"[stage163] main {item['name']}", flush=True)
        row = s136._run_mainline(root, cfg, data, item, initial_equity, full_start, full_end)
        row = s161._ensure_mainline_row(row, ref_row, initial_equity, full_end)
        main_map[str(row.get("name"))] = row
        scanned_main.append(str(row.get("name")))
    main_rows = s161._finalize_rows(list(main_map.values()), branch=False)

    branch_map = {str(r.get("name")): s161._ensure_branch_row(r, initial_equity) for r in branch_rows}
    scanned_branch: list[str] = []
    for item in _new_branch_items():
        print(f"[stage163] branch {item['name']}", flush=True)
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

    active_map = {sym: s161._active_asset_name(branch_json, sym) for sym in ["BTC", "ETH", "SOL"]}

    frontier_txt = raw / "stage163_web_aggressive_multiasset_frontier_latest.txt"
    frontier_json = raw / "stage163_web_aggressive_multiasset_frontier_latest.json"
    _write_report(frontier_txt, frontier_json, main_rows, branch_rows, repaired_main, repaired_branch, scanned_main, scanned_branch, active_map)

    manifest = {
        "mode": "web_aggressive_multiasset_frontier",
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
    manifest_path = raw / "stage163_web_aggressive_multiasset_frontier_manifest_latest.json"
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
