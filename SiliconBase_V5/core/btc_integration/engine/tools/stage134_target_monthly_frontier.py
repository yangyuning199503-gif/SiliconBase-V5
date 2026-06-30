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

TARGET_MONTHLY_MIN = 0.076
TARGET_MONTHLY_MAX = 0.114


def _sample_q(trades: Any, target: int) -> float:
    t = max(int(trades or 0), 0)
    if t <= 0:
        return 0.0
    if target <= 0:
        return 1.0
    return max(0.0, min(1.0, t / float(target)))


def _target_monthly(row: dict[str, Any], *, branch: bool) -> float:
    dom = row.get("dominant_gate", {}) or {}
    recent = dom.get("recent_metrics", {}) or {}
    wf = (row.get("walkforward") or {}).get("metrics", {}) or {}
    recent_target = 12 if branch else 18
    wf_target = 6 if branch else 8
    rw = 0.62 * _sample_q(recent.get("trades"), recent_target)
    ww = 0.38 * _sample_q(wf.get("trades"), wf_target)
    denom = rw + ww
    if denom <= 0:
        return 0.0
    return (
        s88._safe_float(recent.get("monthlyized_ret")) * rw
        + s88._safe_float(wf.get("monthlyized_ret")) * ww
    ) / denom


def _target_score(row: dict[str, Any], *, branch: bool) -> float:
    dom = row.get("dominant_gate", {}) or {}
    recent = dom.get("recent_metrics", {}) or {}
    wf = (row.get("walkforward") or {}).get("metrics", {}) or {}
    recent_target = 12 if branch else 18
    wf_target = 6 if branch else 8
    month = _target_monthly(row, branch=branch)
    recent_q = _sample_q(recent.get("trades"), recent_target)
    wf_q = _sample_q(wf.get("trades"), wf_target)
    gap_penalty = max(0.0, TARGET_MONTHLY_MIN - month)
    return float(
        month * 2400.0
        + max(0.0, s88._safe_float(recent.get("pf")) - 1.0) * 110.0
        + max(0.0, s88._safe_float(wf.get("pf")) - 1.0) * 150.0
        + min(int(recent.get("trades", 0) or 0), recent_target * 2) * 4.0
        + min(int(wf.get("trades", 0) or 0), wf_target * 3) * 5.0
        - abs(s88._safe_float(wf.get("maxdd"))) * 120.0
        - gap_penalty * 900.0
        - max(0.0, 0.40 - recent_q) * 60.0
        - max(0.0, 0.40 - wf_q) * 80.0
    )


def _target_gap(month: float) -> float:
    return max(0.0, TARGET_MONTHLY_MIN - month)


def _mainline_items() -> list[dict[str, Any]]:
    item_map = {str(item.get("name")): item for item in s88._mainline_items()}
    out: dict[str, dict[str, Any]] = {}

    def add(item: dict[str, Any] | None) -> None:
        if item is not None:
            out[str(item.get("name"))] = item

    for name in [
        "mainline_live_dynlev_fix8_lock18",
        "mainline_live_dynlev_fix10_lock12",
        "mainline_split_adx28_cd5_lb22_zone027",
        "mainline_core_satellite_dynlev_fix8_lock18",
    ]:
        add(item_map.get(name))

    base_live = item_map.get("mainline_live_base")
    if base_live is not None:
        add(
            s88._make_mainline_variant(
                base_live,
                name="mainline_live_dynlev_fix12_lock08",
                note="目标月化快筛：更细分仓 + 更快保本，优先检查近2年/WF 的提频上限",
                patch={
                    "portfolio.dynamic_leverage.enabled": True,
                    "portfolio.dynamic_leverage.min": 4.0,
                    "portfolio.dynamic_leverage.max": 8.0,
                    "portfolio.dynamic_leverage.adx_low": 16.0,
                    "portfolio.dynamic_leverage.adx_high": 32.0,
                    "money_management.mode": "fixed",
                    "money_management.capital_slices": 12,
                    "money_management.stake_mode": "dynamic_equity",
                    "money_management.stake_min_usd": 6000,
                    "money_management.stake_max_usd": 11000,
                    "money_management.stop_loss_pct": 0.15,
                    "money_management.take_profit_pct": 1.05,
                    "money_management.trailing_profit.enabled": True,
                    "money_management.trailing_profit.activation_pnl_pct": 0.45,
                    "money_management.trailing_profit.giveback_ratio": 0.42,
                    "money_management.trailing_profit.min_lock_pnl_pct": 0.08,
                },
            )
        )
        add(
            s88._make_mainline_variant(
                base_live,
                name="mainline_live_dynlev_fix12_lock08_cd5",
                note="目标月化快筛：fix12_lock08 再压 cooldown，直接测主线提频极限",
                patch={
                    "strategy_params.cooldown_bars": 5,
                    "portfolio.dynamic_leverage.enabled": True,
                    "portfolio.dynamic_leverage.min": 4.0,
                    "portfolio.dynamic_leverage.max": 8.0,
                    "portfolio.dynamic_leverage.adx_low": 15.0,
                    "portfolio.dynamic_leverage.adx_high": 30.0,
                    "money_management.mode": "fixed",
                    "money_management.capital_slices": 12,
                    "money_management.stake_mode": "dynamic_equity",
                    "money_management.stake_min_usd": 5500,
                    "money_management.stake_max_usd": 10500,
                    "money_management.stop_loss_pct": 0.15,
                    "money_management.take_profit_pct": 0.98,
                    "money_management.trailing_profit.enabled": True,
                    "money_management.trailing_profit.activation_pnl_pct": 0.42,
                    "money_management.trailing_profit.giveback_ratio": 0.45,
                    "money_management.trailing_profit.min_lock_pnl_pct": 0.08,
                },
            )
        )

    split_base = item_map.get("mainline_split_adx28_cd5_lb22_zone027")
    if split_base is not None:
        add(
            s88._make_mainline_variant(
                split_base,
                name="mainline_split_adx30_cd4_lb20_zone024",
                note="目标月化快筛：更短 lookback + 更窄 zone + 更低 cooldown，测试结构化提频极限",
                patch={
                    "filters.adx_floor": 30,
                    "strategy_params.cooldown_bars": 4,
                    "sr_entries.lookback_4h": 20,
                    "sr_entries.zone_atr_mult": 0.24,
                    "sr_entries.adx_max": 30.0,
                    "sr_entries.cooldown_bars": 4,
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
        "eth_breakout_long_follow_lb16_atr050_adx22_s034",
        "eth_retest_short_trend_lb20_atr060_adx24_s068",
        "eth_short_shock_fast_lb16_atr052_adx22_s078",
        "btc_breakout_long_event_lb20_atr060_adx24_s050",
        "btc_dual_fast_trend_dynlev_fix8",
    ]:
        add(item_map.get(name))

    eth_long = item_map.get("eth_breakout_long_follow_lb16_atr050_adx22_s034")
    if eth_long is not None:
        add(
            s88._make_variant(
                eth_long,
                name="eth_breakout_long_follow_lb14_atr048_adx20_s038",
                note="ETH 多腿快版：更短突破 + 更低 ADX 门，直接测近2年提频上限",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 14,
                    "strategy_params.breakout_atr_buffer": 0.48,
                    "strategy_params.cooldown_bars": 4,
                    "filters.adx_floor": 20,
                    "money_management.stake_scale.eth_long": 0.38,
                },
            )
        )

    eth_short = item_map.get("eth_retest_short_trend_lb20_atr060_adx24_s068")
    if eth_short is not None:
        add(
            s88._make_variant(
                eth_short,
                name="eth_retest_short_trend_lb18_atr056_adx22_s072",
                note="ETH 空腿快版：保留回踩确认，但缩短等待，检查 WF 是否还能站住",
                family="short",
                patch={
                    "strategy_params.breakout_lookback": 18,
                    "strategy_params.breakout_atr_buffer": 0.56,
                    "strategy_params.cooldown_bars": 5,
                    "filters.adx_floor": 22,
                    "money_management.stake_scale.eth_short": 0.72,
                },
            )
        )

    btc_long = item_map.get("btc_breakout_long_event_lb20_atr060_adx24_s050")
    if btc_long is not None:
        add(
            s88._make_variant(
                btc_long,
                name="btc_breakout_long_event_lb16_atr055_adx22_s056",
                note="BTC 多腿快版：更短突破 + 更低 ADX 门，专门检查主线外的补充频次",
                family="long",
                patch={
                    "strategy_params.breakout_lookback": 16,
                    "filters.btc_breakout_atr_buffer": 0.55,
                    "filters.btc_adx_floor": 22,
                    "strategy_params.cooldown_bars": 6,
                    "money_management.stake_scale.btc_long": 0.56,
                },
            )
        )

    return list(out.values())


def _write_target_report(path_txt: Path, path_json: Path, main_rows: list[dict[str, Any]], branch_rows: list[dict[str, Any]]) -> None:
    def _row_payload(row: dict[str, Any], *, branch: bool) -> dict[str, Any]:
        dom = row.get("dominant_gate", {}) or {}
        recent = dom.get("recent_metrics", {}) or {}
        wf = (row.get("walkforward") or {}).get("metrics", {}) or {}
        return {
            "name": row.get("name"),
            "family": row.get("family"),
            "dominant_gate": dom.get("gate_name"),
            "decision": row.get("decision"),
            "target_monthly": _target_monthly(row, branch=branch),
            "target_gap_to_floor": _target_gap(_target_monthly(row, branch=branch)),
            "target_score": _target_score(row, branch=branch),
            "recent_monthly": s88._safe_float(recent.get("monthlyized_ret")),
            "recent_ret": s88._safe_float(recent.get("ret")),
            "recent_trades": int(recent.get("trades", 0) or 0),
            "recent_pf": s88._safe_float(recent.get("pf")),
            "wf_monthly": s88._safe_float(wf.get("monthlyized_ret")),
            "wf_ret": s88._safe_float(wf.get("ret")),
            "wf_trades": int(wf.get("trades", 0) or 0),
            "wf_pf": s88._safe_float(wf.get("pf")),
            "wf_dd": s88._safe_float(wf.get("maxdd")),
            "alpha_score": s88._safe_float(row.get("alpha_score")),
        }

    main_payload = sorted([_row_payload(r, branch=False) for r in main_rows], key=lambda x: (x["target_score"], x["alpha_score"]), reverse=True)
    branch_payload = sorted([_row_payload(r, branch=True) for r in branch_rows], key=lambda x: (x["target_score"], x["alpha_score"]), reverse=True)

    lines: list[str] = []
    lines.append("Stage134 目标复合月化快筛")
    lines.append("原则：先看近2年 + WF 的月化与样本厚度，再看 PF / DD；本轮不重跑 event-window，只做 BTC/ETH 高优先快筛。")
    lines.append(f"目标区间：{TARGET_MONTHLY_MIN*100:.1f}% - {TARGET_MONTHLY_MAX*100:.1f}% / 月")
    lines.append("说明：SOL 路径保留，不在本轮快筛里删除，只是先不占用算力。")
    lines.append("")
    lines.append("=== 主线目标快筛 ===")
    for row in main_payload:
        lines.append(
            f"- {row['name']}: target_monthly={row['target_monthly']*100:.2f}% | gap_to_7.6={row['target_gap_to_floor']*100:.2f}% | recent={row['recent_monthly']*100:.2f}%/{row['recent_trades']}笔/PF{row['recent_pf']:.3f} | WF={row['wf_monthly']*100:.2f}%/{row['wf_trades']}笔/PF{row['wf_pf']:.3f} | decision={row['decision']} | gate={row['dominant_gate']}"
        )
    lines.append("")
    lines.append("=== 分支目标快筛 ===")
    for row in branch_payload:
        fam = row.get("family") or "-"
        lines.append(
            f"- {fam} | {row['name']}: target_monthly={row['target_monthly']*100:.2f}% | gap_to_7.6={row['target_gap_to_floor']*100:.2f}% | recent={row['recent_monthly']*100:.2f}%/{row['recent_trades']}笔/PF{row['recent_pf']:.3f} | WF={row['wf_monthly']*100:.2f}%/{row['wf_trades']}笔/PF{row['wf_pf']:.3f} | decision={row['decision']} | gate={row['dominant_gate']}"
        )
    lines.append("")
    lines.append("=== 结论 ===")
    if main_payload:
        top = main_payload[0]
        lines.append(f"- 主线当前快筛第一名: {top['name']} | target_monthly={top['target_monthly']*100:.2f}% | gap_to_7.6={top['target_gap_to_floor']*100:.2f}%")
    if branch_payload:
        top = branch_payload[0]
        lines.append(f"- 分支当前快筛第一名: {top['name']} | target_monthly={top['target_monthly']*100:.2f}% | gap_to_7.6={top['target_gap_to_floor']*100:.2f}%")
    lines.append("- 如果 top 候选仍明显低于 7.6%，下一轮只扩高频模板，不再重复当前保守族。")

    path_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    path_json.write_text(
        json.dumps(
            {
                "target_monthly_min": TARGET_MONTHLY_MIN,
                "target_monthly_max": TARGET_MONTHLY_MAX,
                "mainline": main_payload,
                "branch": branch_payload,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage134 target monthly frontier")
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
    ref_row = s90._run_mainline(root, cfg, data, ref_item, initial_equity, full_start, full_end)

    main_rows: list[dict[str, Any]] = []
    for item in _mainline_items():
        row = s90._run_mainline(root, cfg, data, item, initial_equity, full_start, full_end)
        row["walkforward"] = s81._wf_result(row, ref_row, initial_equity, s81.RECENT_START, full_end)
        row["dominant_gate"] = s90._dominant_gate(row, branch=False)
        row["alpha_score"] = s90._mainline_alpha_score(row)
        row["decision"] = s90._alpha_label(
            row["dominant_gate"].get("recent_metrics", {}),
            row["walkforward"].get("metrics", {}),
            row["walkforward"].get("positive_folds", 0),
            s90._event_fold_share(row["walkforward"]),
            branch=False,
        )
        main_rows.append(row)
    main_rows.sort(key=lambda r: float(r.get("alpha_score", 0.0)), reverse=True)

    branch_rows: list[dict[str, Any]] = []
    for item in _branch_items():
        row = s90._run_branch(root, cfg, item, initial_equity)
        row["walkforward"] = s82._wf_result(row, initial_equity, s78.RECENT_START, row["full_end"])
        row["dominant_gate"] = s90._dominant_gate(row, branch=True)
        row["alpha_score"] = s90._branch_alpha_score(row)
        row["decision"] = s90._alpha_label(
            row["dominant_gate"].get("recent_metrics", {}),
            row["walkforward"].get("metrics", {}),
            row["walkforward"].get("positive_folds", 0),
            s90._event_fold_share(row["walkforward"]),
            branch=True,
        )
        branch_rows.append(row)
    branch_rows.sort(key=lambda r: float(r.get("alpha_score", 0.0)), reverse=True)

    main_txt = reports_raw / "stage90_mainline_event_alpha_matrix_latest.txt"
    main_json = reports_raw / "stage90_mainline_event_alpha_matrix_latest.json"
    branch_txt = reports_raw / "stage91_branch_event_alpha_matrix_latest.txt"
    branch_json = reports_raw / "stage91_branch_event_alpha_matrix_latest.json"
    s90._write_mainline(main_txt, main_json, main_rows)
    s90._write_branch(branch_txt, branch_json, branch_rows)

    target_txt = reports_raw / "stage134_target_monthly_frontier_latest.txt"
    target_json = reports_raw / "stage134_target_monthly_frontier_latest.json"
    _write_target_report(target_txt, target_json, main_rows, branch_rows)

    manifest = {
        "mode": "target_monthly_frontier",
        "mainline_names": [str(x.get("name")) for x in _mainline_items()],
        "branch_names": [str(x.get("name")) for x in _branch_items()],
        "outputs": {
            "stage90_txt": str(main_txt),
            "stage90_json": str(main_json),
            "stage91_txt": str(branch_txt),
            "stage91_json": str(branch_json),
            "target_txt": str(target_txt),
            "target_json": str(target_json),
        },
    }
    (reports_raw / "stage134_target_monthly_frontier_manifest_latest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(main_txt)
    print(main_json)
    print(branch_txt)
    print(branch_json)
    print(target_txt)
    print(target_json)
    print(reports_raw / "stage134_target_monthly_frontier_manifest_latest.json")


if __name__ == "__main__":
    main()
