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
from tools import stage138_anchor_guard_refresh as s138

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
    add(item_map.get("mainline_core_satellite_dynlev_fix8_lock18"), track="base")

    base_live = item_map.get("mainline_live_base")
    if base_live is not None:
        add(
            s88._make_mainline_variant(
                base_live,
                name="mainline_live_dynlev_fix8_lock16_cd4",
                note="围绕主线锚点做轻激进扩展：更快 cooldown + 更快锁盈，但不改基因。",
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
                    "money_management.stop_loss_pct": 0.16,
                    "money_management.take_profit_pct": 1.20,
                    "money_management.trailing_profit.enabled": True,
                    "money_management.trailing_profit.activation_pnl_pct": 0.45,
                    "money_management.trailing_profit.giveback_ratio": 0.30,
                    "money_management.trailing_profit.min_lock_pnl_pct": 0.12,
                },
            ),
            track="base",
        )
        add(
            s88._make_mainline_variant(
                base_live,
                name="mainline_live_dynlev_fix10_lock12_cd4",
                note="主线频次上探：10 切片 + 更快保本，按近2年/WF 硬过滤。",
                patch={
                    "strategy_params.cooldown_bars": 4,
                    "portfolio.dynamic_leverage.enabled": True,
                    "portfolio.dynamic_leverage.min": 5.0,
                    "portfolio.dynamic_leverage.max": 10.0,
                    "portfolio.dynamic_leverage.adx_low": 15.0,
                    "portfolio.dynamic_leverage.adx_high": 30.0,
                    "money_management.mode": "fixed",
                    "money_management.capital_slices": 10,
                    "money_management.stake_mode": "dynamic_equity",
                    "money_management.stake_min_usd": 7500,
                    "money_management.stake_max_usd": 12500,
                    "money_management.stop_loss_pct": 0.13,
                    "money_management.take_profit_pct": 1.10,
                    "money_management.trailing_profit.enabled": True,
                    "money_management.trailing_profit.activation_pnl_pct": 0.30,
                    "money_management.trailing_profit.giveback_ratio": 0.26,
                    "money_management.trailing_profit.min_lock_pnl_pct": 0.08,
                },
            ),
            track="squeeze",
        )
        add(
            s88._make_mainline_variant(
                base_live,
                name="mainline_live_dynlev_fix12_lock08_cd3",
                note="主线激进上限测试：只在当前锚点邻域内再压一档，专看近2年/WF 是否同时增厚。",
                patch={
                    "strategy_params.cooldown_bars": 3,
                    "portfolio.dynamic_leverage.enabled": True,
                    "portfolio.dynamic_leverage.min": 5.0,
                    "portfolio.dynamic_leverage.max": 12.0,
                    "portfolio.dynamic_leverage.adx_low": 14.0,
                    "portfolio.dynamic_leverage.adx_high": 28.0,
                    "money_management.mode": "fixed",
                    "money_management.capital_slices": 12,
                    "money_management.stake_mode": "dynamic_equity",
                    "money_management.stake_min_usd": 7000,
                    "money_management.stake_max_usd": 12000,
                    "money_management.stop_loss_pct": 0.11,
                    "money_management.take_profit_pct": 1.00,
                    "money_management.trailing_profit.enabled": True,
                    "money_management.trailing_profit.activation_pnl_pct": 0.22,
                    "money_management.trailing_profit.giveback_ratio": 0.24,
                    "money_management.trailing_profit.min_lock_pnl_pct": 0.06,
                },
            ),
            track="squeeze",
        )
    return list(out.values())


# no SOL in this round: keep path, save compute

def _branch_items() -> list[dict[str, Any]]:
    item_map = {str(item.get("name")): item for item in s88._branch_items()}
    out: dict[str, dict[str, Any]] = {}

    def add(item: dict[str, Any] | None, *, track: str) -> None:
        if item is not None:
            out[str(item.get("name"))] = _with_meta(item, track=track, branch=True)

    eth_long = item_map.get("eth_breakout_long_follow_lb16_atr050_adx22_s034")
    if eth_long is not None:
        add(
            s88._make_variant(
                eth_long,
                name="eth_squeeze_follow_long_lb10_atr042_adx16_s046",
                note="ETH 挤仓延续锚点：速度和样本目前最均衡。",
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
                name="eth_event_drift_long_lb10_atr044_adx16_s046",
                note="ETH 事件漂移锚点：不追第一根，吃 1-3 根扩散。",
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
        add(
            s88._make_variant(
                eth_long,
                name="eth_event_drift_long_lb12_atr046_adx18_s042",
                note="ETH drift 保守一档：给事件扩散更多确认。",
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
                name="eth_squeeze_follow_long_lb9_atr040_adx15_s048",
                note="ETH squeeze 快一档：只在锚点邻域提频。",
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
                note="ETH squeeze 高频上限测试：更快但仍保留 ADX 过滤。",
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
                name="eth_squeeze_follow_long_lb7_atr036_adx13_s052",
                note="ETH squeeze 极限频次测试：只作为研究层候选，不直接推 runtime。",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 7,
                    "strategy_params.breakout_atr_buffer": 0.36,
                    "strategy_params.cooldown_bars": 2,
                    "filters.adx_floor": 13,
                    "money_management.stake_scale.eth_long": 0.52,
                },
            ),
            track="squeeze",
        )
        add(
            s88._make_variant(
                eth_long,
                name="eth_event_drift_long_lb9_atr042_adx15_s048",
                note="ETH drift 快一档：事件确认后更早接第二脚。",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 9,
                    "strategy_params.breakout_atr_buffer": 0.42,
                    "strategy_params.cooldown_bars": 3,
                    "filters.adx_floor": 15,
                    "money_management.stake_scale.eth_long": 0.48,
                },
            ),
            track="drift",
        )

    eth_retest = item_map.get("eth_retest_short_trend_lb20_atr060_adx24_s068")
    eth_shock = item_map.get("eth_short_shock_fast_lb16_atr052_adx22_s078")
    add(eth_retest, track="reclaim")
    add(eth_shock, track="squeeze")
    if eth_retest is not None:
        add(
            s88._make_variant(
                eth_retest,
                name="eth_retest_short_trend_lb16_atr054_adx20_s072",
                note="ETH 空侧回踩确认快一档：只在 panic 后 reclaim 失败时开。",
                family="short",
                patch={
                    "strategy_params.breakout_lookback": 16,
                    "strategy_params.breakout_atr_buffer": 0.54,
                    "strategy_params.cooldown_bars": 4,
                    "filters.adx_floor": 20,
                    "money_management.stake_scale.eth_short": 0.72,
                },
            ),
            track="reclaim",
        )
        add(
            s88._make_variant(
                eth_retest,
                name="eth_reclaim_short_lb18_atr056_adx22_s070",
                note="ETH 空侧中速 reclaim：优先做消息后失败收回。",
                family="short",
                patch={
                    "strategy_params.breakout_lookback": 18,
                    "strategy_params.breakout_atr_buffer": 0.56,
                    "strategy_params.cooldown_bars": 4,
                    "filters.adx_floor": 22,
                    "money_management.stake_scale.eth_short": 0.70,
                },
            ),
            track="reclaim",
        )

    btc_long = item_map.get("btc_breakout_long_event_lb20_atr060_adx24_s050")
    if btc_long is not None:
        add(btc_long, track="drift")
        add(
            s88._make_variant(
                btc_long,
                name="btc_squeeze_follow_long_lb14_atr048_adx18_s060",
                note="BTC squeeze 邻域：不只做主线空腿，保留 BTC 原生多侧。",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 14,
                    "filters.btc_breakout_atr_buffer": 0.48,
                    "strategy_params.cooldown_bars": 5,
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
                note="BTC drift 邻域：事件确认后更早接第二脚。",
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
        add(
            s88._make_variant(
                btc_long,
                name="btc_event_drift_long_lb12_atr046_adx16_s064",
                note="BTC drift 快一档：追求提频，但必须过近2年+WF。",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 12,
                    "filters.btc_breakout_atr_buffer": 0.46,
                    "strategy_params.cooldown_bars": 4,
                    "filters.btc_adx_floor": 16,
                    "money_management.stake_scale.btc_long": 0.64,
                },
            ),
            track="drift",
        )

    add(item_map.get("btc_dual_fast_trend_dynlev_fix8"), track="base")
    return list(out.values())


def _frontier_score(row: dict[str, Any], rows: list[dict[str, Any]], *, branch: bool) -> float:
    score = s136._frontier_score(row, rows, branch=branch)
    dom = row.get("dominant_gate", {}) or {}
    recent = dom.get("recent_metrics", {}) or {}
    wf = (row.get("walkforward") or {}).get("metrics", {}) or {}
    full = row.get("full_metrics", {}) or {}
    month = s136._target_monthly(row, branch=branch)
    track = str((row.get("meta") or {}).get("track") or "base")
    dom_track = s136._dominant_track(str(dom.get("gate_name") or ""))
    event_share = s90._event_fold_share(row.get("walkforward") or {})
    recent_trades = int(recent.get("trades", 0) or 0)
    wf_trades = int(wf.get("trades", 0) or 0)
    recent_pf = s88._safe_float(recent.get("pf"))
    wf_pf = s88._safe_float(wf.get("pf"))
    recent_ret = s88._safe_float(recent.get("ret"))
    wf_ret = s88._safe_float(wf.get("ret"))
    plateau = row.get("plateau", {}) or {}

    bonus = 0.0
    penalty = 0.0

    if month >= 0.02:
        bonus += 22.0 if branch else 16.0
    elif month >= 0.015:
        bonus += 14.0 if branch else 10.0

    if recent_ret > 0 and wf_ret > 0:
        bonus += min(recent_trades, 36) * (3.8 if branch else 2.0)
        bonus += min(wf_trades, 24) * (4.2 if branch else 2.6)

    if track == dom_track and dom_track != "base":
        bonus += 12.0 if branch else 7.0
    if event_share >= 0.60 and dom_track != "base":
        bonus += 10.0 if branch else 6.0

    if branch:
        sym = str(row.get("symbol") or "").lower()
        fam = str(row.get("family") or "").lower()
        if sym == "eth" and fam == "long" and track in {"squeeze", "drift"}:
            if recent_trades >= 24 and wf_trades >= 16 and recent_pf >= 2.0 and wf_pf >= 1.5:
                bonus += 36.0
            if month >= 0.015 and s88._safe_float(plateau.get("plateau")) >= 0.18:
                bonus += 16.0
        if sym == "eth" and fam == "short" and track == "reclaim" and wf_trades >= 12 and wf_pf >= 1.15:
            bonus += 10.0
        if sym == "btc" and track in {"squeeze", "drift"} and recent_trades >= 14 and wf_trades >= 10 and recent_pf >= 1.3 and wf_pf >= 1.15:
            bonus += 18.0
        if sym == "btc" and fam == "dual" and recent_trades >= 6 and wf_trades >= 6 and recent_pf >= 1.15 and wf_pf >= 1.10:
            bonus += 12.0
    else:
        if track == "base" and recent_trades >= 28 and wf_trades >= 12 and recent_pf >= 1.4 and wf_pf >= 1.15:
            bonus += 24.0
        if track in {"squeeze", "drift"} and recent_trades >= 18 and wf_trades >= 8 and month >= 0.015:
            bonus += 12.0

    if s88._safe_float(full.get("ret")) < 0 and not (recent_ret > 0 and wf_ret > 0 and month >= 0.012):
        penalty += abs(s88._safe_float(full.get("ret"))) * (18.0 if branch else 14.0)

    if abs(s88._safe_float(recent.get("monthlyized_ret")) - s88._safe_float(wf.get("monthlyized_ret"))) >= 0.018:
        penalty += 18.0 if branch else 14.0
    if s88._safe_float(plateau.get("plateau")) < 0.10:
        penalty += 12.0 if branch else 9.0
    if recent_trades < (10 if branch else 14):
        penalty += 12.0 if branch else 10.0
    if wf_trades < (6 if branch else 8):
        penalty += 18.0 if branch else 12.0
    if month < 0.01:
        penalty += 26.0 if branch else 18.0

    return float(score + bonus - penalty)


def _repair_rows_from_stage138(raw: Path, main_rows: list[dict[str, Any]], branch_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], list[str]]:
    frontier_path = raw / "stage138_anchor_guard_refresh_latest.json"
    if not frontier_path.exists():
        return main_rows, branch_rows, [], []
    frontier = s138._load_json(frontier_path)
    prev_main = s138._frontier_map(frontier, "mainline")
    prev_branch = s138._frontier_map(frontier, "branch")
    fixed_main, repaired_main = s138._repair_rows(main_rows, prev_main)
    fixed_branch, repaired_branch = s138._repair_rows(branch_rows, prev_branch)
    return fixed_main, fixed_branch, repaired_main, repaired_branch


def _finalize_rows(rows: list[dict[str, Any]], *, branch: bool) -> list[dict[str, Any]]:
    for row in rows:
        row["plateau"] = s136._plateau_summary(row, rows, branch=branch)
    for row in rows:
        row["alpha_score"] = _frontier_score(row, rows, branch=branch)
        row["decision"] = s136._frontier_label(row, branch=branch)
    rows.sort(key=lambda r: float(r.get("alpha_score", 0.0)), reverse=True)
    return rows


def _write_report(path_txt: Path, path_json: Path, main_rows: list[dict[str, Any]], branch_rows: list[dict[str, Any]], repaired_main: list[str], repaired_branch: list[str]) -> None:
    main_payload = [s136._payload_row(r, branch=False) for r in main_rows]
    branch_payload = [s136._payload_row(r, branch=True) for r in branch_rows]

    lines: list[str] = []
    lines.append("Stage139 微结构联动前沿")
    lines.append("原则：旧样本只作软约束；围绕已验证锚点，只扩 squeeze / drift / reclaim 三轨，并用近2年 + WF 压过拟合。")
    lines.append(f"目标区间：{TARGET_MONTHLY_MIN*100:.1f}% - {TARGET_MONTHLY_MAX*100:.1f}% / 月")
    lines.append("")
    if repaired_main or repaired_branch:
        lines.append(f"- 异常回退: main={len(repaired_main)} | branch={len(repaired_branch)}")
        if repaired_main:
            lines.append(f"- 主线回退: {', '.join(repaired_main)}")
        if repaired_branch:
            lines.append(f"- 分支回退: {', '.join(repaired_branch)}")
        lines.append("")
    lines.append("=== 主线 ===")
    for row in main_payload:
        lines.append(
            f"- {row['name']}: track={row['track']} | dom={row['dominant_track']} | target_monthly={row['target_monthly']*100:.2f}% | 近2年={row['recent_monthly']*100:.2f}%/{row['recent_trades']}笔/PF{row['recent_pf']:.3f} | WF={row['wf_monthly']*100:.2f}%/{row['wf_trades']}笔/PF{row['wf_pf']:.3f} | plateau={row['plateau']:.2f}/{row['neighbor_count']} | decision={row['decision']}"
        )
    lines.append("")
    lines.append("=== 分支（BTC/ETH） ===")
    for row in branch_payload:
        sym = row.get("symbol") or "-"
        fam = row.get("family") or "-"
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
    lines.append("- ETH 继续保留 squeeze/drift 双多腿 + reclaim 空腿，不提前砍路。")
    lines.append("- BTC 继续保留 drift/squeeze/dual 三轨；本轮不再让 workspace 旧 research 覆盖 root 最新结论。")
    lines.append("- SOL 本轮不耗算力，但路径保留，继续只放 research_only。")

    path_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    path_json.write_text(
        json.dumps(
            {
                "mode": "microstructure_confluence_frontier",
                "target_monthly_min": TARGET_MONTHLY_MIN,
                "target_monthly_max": TARGET_MONTHLY_MAX,
                "repaired_main": repaired_main,
                "repaired_branch": repaired_branch,
                "packs": [x[0] for x in PACKS],
                "mainline": main_payload,
                "branch": branch_payload,
                "notes": {
                    "sol": "kept_research_only_not_scanned_this_round",
                    "report_sync": "prefer_root_research_for_stage90_91_120",
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _mirror_to_workspace(root: Path, files: list[Path]) -> None:
    ws_raw = root / ".branch_shortwave_demo" / "workspace" / "reports" / "research_raw"
    if not ws_raw.parent.exists():
        return
    ws_raw.mkdir(parents=True, exist_ok=True)
    for p in files:
        if p.exists() and p.is_file():
            (ws_raw / p.name).write_bytes(p.read_bytes())


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage139 microstructure confluence frontier")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    raw = root / "reports" / "research_raw"
    raw.mkdir(parents=True, exist_ok=True)

    cfg = rcb.load_research_base_config(root)
    initial_equity = float(cfg.get("portfolio", {}).get("initial_equity", 100000.0))

    data = s46._load_portfolio_data(root, cfg)
    full_start, full_end = s77._window_bounds_from_data(data)

    item_map_main = {str(item.get("name")): item for item in s88._mainline_items()}
    ref_item = item_map_main.get("mainline_live_base")
    if ref_item is None:
        raise SystemExit("missing mainline reference: mainline_live_base")
    ref_row = s136._run_mainline(root, cfg, data, _with_meta(ref_item, track="base", branch=False), initial_equity, full_start, full_end)

    main_rows: list[dict[str, Any]] = []
    main_items = _mainline_items()
    for i, item in enumerate(main_items, 1):
        print(f"[stage139] mainline {i}/{len(main_items)} {item['name']}", flush=True)
        row = s136._run_mainline(root, cfg, data, item, initial_equity, full_start, full_end)
        row["walkforward"] = s81._wf_result(row, ref_row, initial_equity, s81.RECENT_START, full_end)
        row["dominant_gate"] = s90._dominant_gate(row, branch=False)
        main_rows.append(row)

    branch_rows: list[dict[str, Any]] = []
    branch_items = _branch_items()
    for i, item in enumerate(branch_items, 1):
        print(f"[stage139] branch {i}/{len(branch_items)} {item['name']}", flush=True)
        row = s136._run_branch(root, cfg, item, initial_equity)
        row["walkforward"] = s82._wf_result(row, initial_equity, s78.RECENT_START, row["full_end"])
        row["dominant_gate"] = s90._dominant_gate(row, branch=True)
        branch_rows.append(row)

    main_rows, branch_rows, repaired_main, repaired_branch = _repair_rows_from_stage138(raw, main_rows, branch_rows)
    main_rows = _finalize_rows(main_rows, branch=False)
    branch_rows = _finalize_rows(branch_rows, branch=True)

    main_txt = raw / "stage90_mainline_event_alpha_matrix_latest.txt"
    main_json = raw / "stage90_mainline_event_alpha_matrix_latest.json"
    branch_txt = raw / "stage91_branch_event_alpha_matrix_latest.txt"
    branch_json = raw / "stage91_branch_event_alpha_matrix_latest.json"
    s90._write_mainline(main_txt, main_json, main_rows)
    s90._write_branch(branch_txt, branch_json, branch_rows)

    frontier_txt = raw / "stage139_microstructure_confluence_frontier_latest.txt"
    frontier_json = raw / "stage139_microstructure_confluence_frontier_latest.json"
    _write_report(frontier_txt, frontier_json, main_rows, branch_rows, repaired_main, repaired_branch)

    manifest = {
        "mode": "microstructure_confluence_frontier",
        "packs": [x[0] for x in PACKS],
        "mainline_names": [str(x.get("name")) for x in main_items],
        "branch_names": [str(x.get("name")) for x in branch_items],
        "repaired_main": repaired_main,
        "repaired_branch": repaired_branch,
        "report_sync_fix": "prefer_root_research_for_stage90_91_120",
        "outputs": {
            "stage90_txt": str(main_txt),
            "stage90_json": str(main_json),
            "stage91_txt": str(branch_txt),
            "stage91_json": str(branch_json),
            "frontier_txt": str(frontier_txt),
            "frontier_json": str(frontier_json),
        },
    }
    manifest_path = raw / "stage139_microstructure_confluence_frontier_manifest_latest.json"
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
