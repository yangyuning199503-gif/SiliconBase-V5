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
from tools import stage78_branch_dual_window_lab as s78
from tools import stage81_mainline_walkforward_lab as s81
from tools import stage82_branch_walkforward_lab as s82
from tools import stage88_strategy_fusion_walkforward as s88
from tools import stage90_event_alpha_matrix as s90
from tools import stage136_regime_plateau_frontier as s136

TARGET_MONTHLY_MIN = s136.TARGET_MONTHLY_MIN
TARGET_MONTHLY_MAX = s136.TARGET_MONTHLY_MAX
PACKS = s136.PACKS


def _with_meta(item: dict[str, Any], *, track: str, branch: bool) -> dict[str, Any]:
    return s136._with_meta(item, track=track, branch=branch)


def _mainline_items() -> list[dict[str, Any]]:
    item_map = {str(item.get("name")): item for item in s88._mainline_items()}
    out: dict[str, dict[str, Any]] = {}

    def add(item: dict[str, Any] | None, *, track: str = "base") -> None:
        if item is not None:
            out[str(item.get("name"))] = _with_meta(item, track=track, branch=False)

    add(item_map.get("mainline_live_dynlev_fix8_lock18"), track="base")
    add(item_map.get("mainline_squeeze_follow_fix10_lock08"), track="squeeze")
    add(item_map.get("mainline_core_satellite_dynlev_fix8_lock18"), track="base")

    base_live = item_map.get("mainline_live_base")
    if base_live is not None:
        add(
            s88._make_mainline_variant(
                base_live,
                name="mainline_live_dynlev_fix8_lock18_cd5",
                note="围绕当前主线锚点只放一个维度：轻降 cooldown，看能否提频而不伤 WF。",
                patch={
                    "strategy_params.cooldown_bars": 5,
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
                    "money_management.take_profit_pct": 1.50,
                    "money_management.trailing_profit.enabled": True,
                    "money_management.trailing_profit.activation_pnl_pct": 0.70,
                    "money_management.trailing_profit.giveback_ratio": 0.35,
                    "money_management.trailing_profit.min_lock_pnl_pct": 0.18,
                },
            ),
            track="base",
        )
        add(
            s88._make_mainline_variant(
                base_live,
                name="mainline_live_dynlev_fix8_lock14_cd5",
                note="围绕主线锚点做更快锁盈：只在保持 base 结构下测试更快兑现。",
                patch={
                    "strategy_params.cooldown_bars": 5,
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
                    "money_management.stop_loss_pct": 0.16,
                    "money_management.take_profit_pct": 1.30,
                    "money_management.trailing_profit.enabled": True,
                    "money_management.trailing_profit.activation_pnl_pct": 0.55,
                    "money_management.trailing_profit.giveback_ratio": 0.32,
                    "money_management.trailing_profit.min_lock_pnl_pct": 0.14,
                },
            ),
            track="base",
        )
        add(
            s88._make_mainline_variant(
                base_live,
                name="mainline_live_dynlev_fix10_lock16_cd4",
                note="主线高频探索：10 切片 + 更快 cooldown，但仍要求 WF 不塌。",
                patch={
                    "strategy_params.cooldown_bars": 4,
                    "portfolio.dynamic_leverage.enabled": True,
                    "portfolio.dynamic_leverage.min": 4.0,
                    "portfolio.dynamic_leverage.max": 10.0,
                    "portfolio.dynamic_leverage.adx_low": 16.0,
                    "portfolio.dynamic_leverage.adx_high": 32.0,
                    "money_management.mode": "fixed",
                    "money_management.capital_slices": 10,
                    "money_management.stake_mode": "dynamic_equity",
                    "money_management.stake_min_usd": 8000,
                    "money_management.stake_max_usd": 13000,
                    "money_management.stop_loss_pct": 0.16,
                    "money_management.take_profit_pct": 1.20,
                    "money_management.trailing_profit.enabled": True,
                    "money_management.trailing_profit.activation_pnl_pct": 0.48,
                    "money_management.trailing_profit.giveback_ratio": 0.30,
                    "money_management.trailing_profit.min_lock_pnl_pct": 0.16,
                },
            ),
            track="squeeze",
        )
    return list(out.values())


def _branch_items() -> list[dict[str, Any]]:
    item_map = {str(item.get("name")): item for item in s88._branch_items()}
    out: dict[str, dict[str, Any]] = {}

    def add(item: dict[str, Any] | None, *, track: str) -> None:
        if item is not None:
            out[str(item.get("name"))] = _with_meta(item, track=track, branch=True)

    # keep current proven anchors
    add(item_map.get("eth_breakout_long_follow_lb16_atr050_adx22_s034"), track="squeeze")
    add(item_map.get("eth_retest_short_trend_lb20_atr060_adx24_s068"), track="reclaim")
    add(item_map.get("eth_short_shock_fast_lb16_atr052_adx22_s078"), track="squeeze")
    add(item_map.get("btc_breakout_long_event_lb20_atr060_adx24_s050"), track="drift")
    add(item_map.get("btc_dual_fast_trend_dynlev_fix8"), track="base")

    eth_long = item_map.get("eth_breakout_long_follow_lb16_atr050_adx22_s034")
    if eth_long is not None:
        add(
            s88._make_variant(
                eth_long,
                name="eth_event_drift_long_lb12_atr046_adx18_s042",
                note="保留已验证 drift 版，作为 ETH 事件后跟随锚点。",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 12,
                    "strategy_params.breakout_atr_buffer": 0.46,
                    "strategy_params.cooldown_bars": 3,
                    "filters.adx_floor": 18,
                    "money_management.stake_scale.eth_long": 0.42,
                },
            ),
            track="drift",
        )
        add(
            s88._make_variant(
                eth_long,
                name="eth_squeeze_follow_long_lb10_atr042_adx16_s046",
                note="保留当前 ETH 最强 squeeze 锚点。",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 10,
                    "strategy_params.breakout_atr_buffer": 0.42,
                    "strategy_params.cooldown_bars": 3,
                    "filters.adx_floor": 16,
                    "money_management.stake_scale.eth_long": 0.46,
                },
            ),
            track="squeeze",
        )
        add(
            s88._make_variant(
                eth_long,
                name="eth_squeeze_follow_long_lb9_atr040_adx15_s048",
                note="沿 ETH squeeze 锚点只放一格：更短 breakout + 更低 ADX，看能否提频。",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 9,
                    "strategy_params.breakout_atr_buffer": 0.40,
                    "strategy_params.cooldown_bars": 3,
                    "filters.adx_floor": 15,
                    "money_management.stake_scale.eth_long": 0.48,
                },
            ),
            track="squeeze",
        )
        add(
            s88._make_variant(
                eth_long,
                name="eth_squeeze_follow_long_lb8_atr038_adx14_s050",
                note="ETH squeeze 高频上限测试：只在锚点邻域内再放一格，不做远跳。",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 8,
                    "strategy_params.breakout_atr_buffer": 0.38,
                    "strategy_params.cooldown_bars": 2,
                    "filters.adx_floor": 14,
                    "money_management.stake_scale.eth_long": 0.50,
                },
            ),
            track="squeeze",
        )
        add(
            s88._make_variant(
                eth_long,
                name="eth_event_drift_long_lb10_atr044_adx16_s046",
                note="ETH drift 邻域测试：事件后漂移更快进，但不直接追第一根。",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 10,
                    "strategy_params.breakout_atr_buffer": 0.44,
                    "strategy_params.cooldown_bars": 3,
                    "filters.adx_floor": 16,
                    "money_management.stake_scale.eth_long": 0.46,
                },
            ),
            track="drift",
        )

    eth_short = item_map.get("eth_retest_short_trend_lb20_atr060_adx24_s068") or item_map.get("eth_short_shock_fast_lb16_atr052_adx22_s078")
    if eth_short is not None:
        add(
            s88._make_variant(
                eth_short,
                name="eth_reclaim_short_lb18_atr055_adx20_s074",
                note="ETH 空侧保留 reclaim 路径，避免只剩单边多腿。",
                family="short",
                patch={
                    "strategy_params.breakout_lookback": 18,
                    "strategy_params.breakout_atr_buffer": 0.55,
                    "strategy_params.cooldown_bars": 5,
                    "filters.adx_floor": 20,
                    "money_management.stake_scale.eth_short": 0.74,
                },
            ),
            track="reclaim",
        )

    btc_long = item_map.get("btc_breakout_long_event_lb20_atr060_adx24_s050")
    if btc_long is not None:
        add(
            s88._make_variant(
                btc_long,
                name="btc_squeeze_follow_long_lb16_atr050_adx20_s058",
                note="保留 BTC squeeze 锚点，作为 drift 之外的补频腿。",
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
        )
        add(
            s88._make_variant(
                btc_long,
                name="btc_squeeze_follow_long_lb14_atr048_adx18_s060",
                note="BTC squeeze 邻域测试：在已验证方向上只放一格以冲频次。",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 14,
                    "filters.btc_breakout_atr_buffer": 0.48,
                    "strategy_params.cooldown_bars": 4,
                    "filters.btc_adx_floor": 18,
                    "money_management.stake_scale.btc_long": 0.60,
                },
            ),
            track="squeeze",
        )
        add(
            s88._make_variant(
                btc_long,
                name="btc_event_drift_long_lb16_atr050_adx20_s058",
                note="BTC drift 邻域测试：在事件确认后更早接第二脚。",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 16,
                    "filters.btc_breakout_atr_buffer": 0.50,
                    "strategy_params.cooldown_bars": 5,
                    "filters.btc_adx_floor": 20,
                    "money_management.stake_scale.btc_long": 0.58,
                },
            ),
            track="drift",
        )
    return list(out.values())


def _frontier_score(row: dict[str, Any], rows: list[dict[str, Any]], *, branch: bool) -> float:
    score = s136._frontier_score(row, rows, branch=branch)
    dom = row.get("dominant_gate", {}) or {}
    recent = dom.get("recent_metrics", {}) or {}
    wf = (row.get("walkforward") or {}).get("metrics", {}) or {}
    month = s136._target_monthly(row, branch=branch)
    event_share = s90._event_fold_share(row.get("walkforward") or {})
    recent_trades = int(recent.get("trades", 0) or 0)
    wf_trades = int(wf.get("trades", 0) or 0)
    recent_pf = s88._safe_float(recent.get("pf"))
    wf_pf = s88._safe_float(wf.get("pf"))
    recent_ret = s88._safe_float(recent.get("ret"))
    wf_ret = s88._safe_float(wf.get("ret"))
    track = str((row.get("meta") or {}).get("track") or "base")
    dom_track = s136._dominant_track(str(dom.get("gate_name") or ""))

    bonus = 0.0
    penalty = 0.0

    if recent_ret > 0 and wf_ret > 0:
        bonus += min(recent_trades, 36) * (4.0 if branch else 2.2)
        bonus += min(wf_trades, 24) * (4.8 if branch else 3.0)
    if month >= 0.01 and event_share >= 0.60 and recent_pf >= 1.15 and wf_pf >= 1.05:
        bonus += 28.0 if branch else 18.0
    if track == dom_track and dom_track != "base":
        bonus += 10.0 if branch else 6.0
    if branch:
        sym = str(row.get("symbol") or "").lower()
        fam = str(row.get("family") or "").lower()
        if sym == "eth" and track == "squeeze" and fam == "long" and recent_trades >= 20 and wf_trades >= 12 and recent_pf >= 2.0 and wf_pf >= 1.5:
            bonus += 22.0
        if sym == "btc" and track in {"squeeze", "drift"} and recent_trades >= 14 and wf_trades >= 10 and recent_pf >= 1.4 and wf_pf >= 1.2:
            bonus += 14.0
    else:
        if track == "base" and recent_trades >= 24 and wf_trades >= 12 and recent_pf >= 1.4 and wf_pf >= 1.15:
            bonus += 14.0

    if month < 0.01:
        penalty += 26.0 if branch else 18.0
    if recent_trades < (8 if branch else 12):
        penalty += 12.0 if branch else 8.0
    if wf_trades < (5 if branch else 8):
        penalty += 18.0 if branch else 12.0
    if track != dom_track and dom_track != "base":
        penalty += 8.0 if branch else 5.0

    return float(score + bonus - penalty)


def _write_report(path_txt: Path, path_json: Path, main_rows: list[dict[str, Any]], branch_rows: list[dict[str, Any]]) -> None:
    main_payload = [s136._payload_row(r, branch=False) for r in main_rows]
    branch_payload = [s136._payload_row(r, branch=True) for r in branch_rows]
    lines: list[str] = []
    lines.append("Stage137 锚点邻域前沿")
    lines.append("原则：不再全图乱扫，只围绕当前已验证锚点做邻域扩展；同时修复 branch runtime 读取旧 research 文件的偏差。")
    lines.append(f"目标区间：{TARGET_MONTHLY_MIN*100:.1f}% - {TARGET_MONTHLY_MAX*100:.1f}% / 月")
    lines.append("")
    lines.append("=== 主线 ===")
    for row in main_payload:
        lines.append(
            f"- {row['name']}: track={row['track']} | dom={row['dominant_track']} | target_monthly={row['target_monthly']*100:.2f}% | 近2年={row['recent_monthly']*100:.2f}%/{row['recent_trades']}笔/PF{row['recent_pf']:.3f} | WF={row['wf_monthly']*100:.2f}%/{row['wf_trades']}笔/PF{row['wf_pf']:.3f} | plateau={row['plateau']:.2f}/{row['neighbor_count']} | decision={row['decision']}"
        )
    lines.append("")
    lines.append("=== 分支（BTC/ETH） ===")
    for row in branch_payload:
        sym = row.get('symbol') or '-'
        fam = row.get('family') or '-'
        lines.append(
            f"- {sym}|{fam}|{row['name']}: track={row['track']} | dom={row['dominant_track']} | target_monthly={row['target_monthly']*100:.2f}% | 近2年={row['recent_monthly']*100:.2f}%/{row['recent_trades']}笔/PF{row['recent_pf']:.3f} | WF={row['wf_monthly']*100:.2f}%/{row['wf_trades']}笔/PF{row['wf_pf']:.3f} | plateau={row['plateau']:.2f}/{row['neighbor_count']} | decision={row['decision']}"
        )
    lines.append("")
    lines.append("=== 结论 ===")
    if main_payload:
        top = main_payload[0]
        lines.append(f"- 主线当前锚点: {top['name']} | target_monthly={top['target_monthly']*100:.2f}% | gap_to_7.6={top['gap_to_floor']*100:.2f}%")
    if branch_payload:
        top = branch_payload[0]
        lines.append(f"- 分支当前锚点: {top['name']} | target_monthly={top['target_monthly']*100:.2f}% | gap_to_7.6={top['gap_to_floor']*100:.2f}%")
    lines.append("- ETH 继续以 squeeze/drift 双多腿 + reclaim 空腿并行，不提前砍路。")
    lines.append("- BTC 继续保留 drift/squeeze/dual 三轨，但只在锚点邻域内试提频。")
    lines.append("- runtime 读取 research 文件改成优先最新版本，避免 workspace 里的旧 stage91 覆盖掉新结论。")

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
    ap = argparse.ArgumentParser(description="Stage137 anchor playbook frontier")
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
    ref_row = s136._run_mainline(root, cfg, data, _with_meta(ref_item, track="base", branch=False), initial_equity, full_start, full_end)

    main_rows: list[dict[str, Any]] = []
    main_items = _mainline_items()
    for i, item in enumerate(main_items, 1):
        print(f"[stage137] mainline {i}/{len(main_items)} {item['name']}", flush=True)
        row = s136._run_mainline(root, cfg, data, item, initial_equity, full_start, full_end)
        row["walkforward"] = s81._wf_result(row, ref_row, initial_equity, s81.RECENT_START, full_end)
        row["dominant_gate"] = s90._dominant_gate(row, branch=False)
        main_rows.append(row)
    for row in main_rows:
        row["plateau"] = s136._plateau_summary(row, main_rows, branch=False)
    for row in main_rows:
        row["alpha_score"] = _frontier_score(row, main_rows, branch=False)
        row["decision"] = s136._frontier_label(row, branch=False)
    main_rows.sort(key=lambda r: float(r.get("alpha_score", 0.0)), reverse=True)

    branch_rows: list[dict[str, Any]] = []
    branch_items = _branch_items()
    for i, item in enumerate(branch_items, 1):
        print(f"[stage137] branch {i}/{len(branch_items)} {item['name']}", flush=True)
        row = s136._run_branch(root, cfg, item, initial_equity)
        row["walkforward"] = s82._wf_result(row, initial_equity, s78.RECENT_START, row["full_end"])
        row["dominant_gate"] = s90._dominant_gate(row, branch=True)
        branch_rows.append(row)
    for row in branch_rows:
        row["plateau"] = s136._plateau_summary(row, branch_rows, branch=True)
    for row in branch_rows:
        row["alpha_score"] = _frontier_score(row, branch_rows, branch=True)
        row["decision"] = s136._frontier_label(row, branch=True)
    branch_rows.sort(key=lambda r: float(r.get("alpha_score", 0.0)), reverse=True)

    main_txt = reports_raw / "stage90_mainline_event_alpha_matrix_latest.txt"
    main_json = reports_raw / "stage90_mainline_event_alpha_matrix_latest.json"
    branch_txt = reports_raw / "stage91_branch_event_alpha_matrix_latest.txt"
    branch_json = reports_raw / "stage91_branch_event_alpha_matrix_latest.json"
    s90._write_mainline(main_txt, main_json, main_rows)
    s90._write_branch(branch_txt, branch_json, branch_rows)

    frontier_txt = reports_raw / "stage137_anchor_playbook_frontier_latest.txt"
    frontier_json = reports_raw / "stage137_anchor_playbook_frontier_latest.json"
    _write_report(frontier_txt, frontier_json, main_rows, branch_rows)

    manifest = {
        "mode": "anchor_playbook_frontier",
        "packs": [x[0] for x in PACKS],
        "mainline_names": [str(x.get("name")) for x in main_items],
        "branch_names": [str(x.get("name")) for x in branch_items],
        "runtime_fix": "prefer_fresh_research_json",
        "outputs": {
            "stage90_txt": str(main_txt),
            "stage90_json": str(main_json),
            "stage91_txt": str(branch_txt),
            "stage91_json": str(branch_json),
            "frontier_txt": str(frontier_txt),
            "frontier_json": str(frontier_json),
        },
    }
    (reports_raw / "stage137_anchor_playbook_manifest_latest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(frontier_txt)
    print(frontier_json)
    print(reports_raw / "stage137_anchor_playbook_manifest_latest.json")


if __name__ == "__main__":
    main()
