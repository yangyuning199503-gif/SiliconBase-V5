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
from tools import stage78_branch_dual_window_lab as s78
from tools import stage82_branch_walkforward_lab as s82
from tools import stage88_strategy_fusion_walkforward as s88
from tools import stage90_event_alpha_matrix as s90
from tools import stage136_regime_plateau_frontier as s136
from tools import stage141_guarded_asymmetry_shortlist as s141

TARGET_MONTHLY_MIN = s136.TARGET_MONTHLY_MIN
TARGET_MONTHLY_MAX = s136.TARGET_MONTHLY_MAX


def _with_meta(item: dict[str, Any], *, track: str, branch: bool, anchor_name: str | None = None) -> dict[str, Any]:
    out = s136._with_meta(item, track=track, branch=branch)
    out.setdefault("meta", {})
    out["meta"]["anchor_name"] = str(anchor_name or out.get("name") or "")
    return out



def _new_branch_items() -> list[dict[str, Any]]:
    item_map = {str(item.get("name")): item for item in s88._branch_items()}
    eth_long = item_map.get("eth_breakout_long_follow_lb16_atr050_adx22_s034")
    out: list[dict[str, Any]] = []

    def add(item: dict[str, Any] | None, *, track: str, anchor_name: str) -> None:
        if item is not None:
            out.append(_with_meta(item, track=track, branch=True, anchor_name=anchor_name))

    if eth_long is not None:
        anchor = "eth_reclaim_long_lb11_atr043_adx16_s044"
        variants = [
            (
                "eth_reclaim_long_lb10_atr042_adx15_s042",
                "ETH reclaim 快一档：冲击后更早接第二脚，但先用轻仓验证。",
                {"strategy_params.breakout_lookback": 10, "strategy_params.breakout_atr_buffer": 0.42, "strategy_params.cooldown_bars": 4, "filters.adx_floor": 15, "money_management.stake_scale.eth_long": 0.42},
            ),
            (
                "eth_reclaim_long_lb10_atr042_adx15_s050",
                "ETH reclaim 风险阶梯：参数不变，只上提预算看月化能否继续抬升。",
                {"strategy_params.breakout_lookback": 10, "strategy_params.breakout_atr_buffer": 0.42, "strategy_params.cooldown_bars": 4, "filters.adx_floor": 15, "money_management.stake_scale.eth_long": 0.50},
            ),
            (
                "eth_reclaim_long_lb11_atr043_adx16_s052",
                "ETH reclaim 中档风险阶梯：沿用当前最强 reclaim 骨架，只提预算。",
                {"strategy_params.breakout_lookback": 11, "strategy_params.breakout_atr_buffer": 0.43, "strategy_params.cooldown_bars": 4, "filters.adx_floor": 16, "money_management.stake_scale.eth_long": 0.52},
            ),
            (
                "eth_reclaim_long_lb12_atr044_adx17_s046",
                "ETH reclaim 慢一档：多给一层确认，检查 plateau 能否站住。",
                {"strategy_params.breakout_lookback": 12, "strategy_params.breakout_atr_buffer": 0.44, "strategy_params.cooldown_bars": 4, "filters.adx_floor": 17, "money_management.stake_scale.eth_long": 0.46},
            ),
            (
                "eth_reclaim_hold_long_lb12_atr045_adx17_s050",
                "ETH reclaim+hold：放慢一点，避免第一波后回吐过大。",
                {"strategy_params.breakout_lookback": 12, "strategy_params.breakout_atr_buffer": 0.45, "strategy_params.cooldown_bars": 5, "filters.adx_floor": 17, "money_management.stake_scale.eth_long": 0.50},
            ),
        ]
        for name, note, patch in variants:
            add(
                s88._make_variant(
                    eth_long,
                    name=name,
                    note=note,
                    family="long",
                    patch=patch,
                ),
                track="reclaim",
                anchor_name=anchor,
            )
    return out



def _frontier_score(row: dict[str, Any], rows: list[dict[str, Any]], *, branch: bool) -> float:
    base = s141._frontier_score(row, rows, branch=branch)
    if not branch:
        return base

    sym = str(row.get("symbol") or "").lower()
    fam = str(row.get("family") or "").lower()
    track = str((row.get("meta") or {}).get("track") or "base")
    dom = row.get("dominant_gate", {}) or {}
    recent = dom.get("recent_metrics", {}) or {}
    wf = (row.get("walkforward") or {}).get("metrics", {}) or {}
    plateau = row.get("plateau", {}) or {}

    recent_trades = int(recent.get("trades", 0) or 0)
    wf_trades = int(wf.get("trades", 0) or 0)
    recent_pf = s88._safe_float(recent.get("pf"))
    wf_pf = s88._safe_float(wf.get("pf"))
    recent_monthly = s88._safe_float(recent.get("monthlyized_ret"))
    wf_monthly = s88._safe_float(wf.get("monthlyized_ret"))
    plateau_q = s88._safe_float(plateau.get("plateau"))

    bonus = 0.0
    penalty = 0.0
    if sym == "eth" and fam == "long" and track == "reclaim":
        if recent_trades >= 20 and wf_trades >= 12 and recent_pf >= 2.2 and wf_pf >= 1.6:
            bonus += 18.0
        if recent_monthly >= 0.018 and wf_monthly >= 0.020:
            bonus += 16.0
        if abs(recent_monthly - wf_monthly) <= 0.008:
            bonus += 6.0
        if plateau_q >= 0.12:
            bonus += 12.0
        if recent_trades < 14 or wf_trades < 8:
            penalty += 12.0
    return float(base + bonus - penalty)



def _finalize_rows(rows: list[dict[str, Any]], *, branch: bool) -> list[dict[str, Any]]:
    for row in rows:
        row["plateau"] = s136._plateau_summary(row, rows, branch=branch)
    for row in rows:
        row["alpha_score"] = _frontier_score(row, rows, branch=branch)
        row["decision"] = s136._frontier_label(row, branch=branch)
    rows.sort(key=lambda r: float(r.get("alpha_score", 0.0)), reverse=True)
    return rows



def _write_report(path_txt: Path, path_json: Path, main_rows: list[dict[str, Any]], branch_rows: list[dict[str, Any]], repaired_main: list[str], repaired_branch: list[str], scanned_branch: list[str]) -> None:
    main_payload = [s136._payload_row(r, branch=False) for r in main_rows]
    branch_payload = [s136._payload_row(r, branch=True) for r in branch_rows]

    lines: list[str] = []
    lines.append("Stage142 reclaim cluster frontier")
    lines.append("原则：主线先只做守卫；算力集中到 ETH reclaim 邻域，目标是把单点最优变成可验证的平台。")
    lines.append(f"目标区间：{TARGET_MONTHLY_MIN*100:.1f}% - {TARGET_MONTHLY_MAX*100:.1f}% / 月")
    lines.append("")
    lines.append(f"- 修复对象: main={len(repaired_main)} | branch={len(repaired_branch)}")
    lines.append(f"- 新刷分支候选: {', '.join(scanned_branch) if scanned_branch else '-'}")
    lines.append("")
    lines.append("=== 主线 ===")
    for row in main_payload[:4]:
        lines.append(
            f"- {row['name']}: target_monthly={row['target_monthly']*100:.2f}% | 近2年={row['recent_monthly']*100:.2f}%/{row['recent_trades']}笔/PF{row['recent_pf']:.3f} | WF={row['wf_monthly']*100:.2f}%/{row['wf_trades']}笔/PF{row['wf_pf']:.3f} | decision={row['decision']}"
        )
    lines.append("")
    lines.append("=== 分支重点（前12） ===")
    for row in branch_payload[:12]:
        sym = row.get("symbol") or "-"
        fam = row.get("family") or "-"
        lines.append(
            f"- {sym}|{fam}|{row['name']}: track={row['track']} | target_monthly={row['target_monthly']*100:.2f}% | plateau={row['plateau']:.2f}/{row['neighbor_count']} | 近2年={row['recent_monthly']*100:.2f}%/{row['recent_trades']}笔/PF{row['recent_pf']:.3f} | WF={row['wf_monthly']*100:.2f}%/{row['wf_trades']}笔/PF{row['wf_pf']:.3f} | decision={row['decision']}"
        )
    lines.append("")
    lines.append("=== 结论 ===")
    if main_payload:
        top = main_payload[0]
        lines.append(f"- 主线第一名: {top['name']} | target_monthly={top['target_monthly']*100:.2f}% | gap_to_7.6={top['gap_to_floor']*100:.2f}%")
    if branch_payload:
        top = branch_payload[0]
        lines.append(f"- 分支第一名: {top['name']} | target_monthly={top['target_monthly']*100:.2f}% | plateau={top['plateau']:.2f} | gap_to_7.6={top['gap_to_floor']*100:.2f}%")
    lines.append("- 这轮不重刷 BTC/SOL 新腿，先看 ETH reclaim 是否能从单点优变成 plateau。")

    path_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    path_json.write_text(
        json.dumps(
            {
                "mode": "reclaim_cluster_frontier",
                "target_monthly_min": TARGET_MONTHLY_MIN,
                "target_monthly_max": TARGET_MONTHLY_MAX,
                "repaired_main": repaired_main,
                "repaired_branch": repaired_branch,
                "new_branch_candidates": scanned_branch,
                "mainline": main_payload,
                "branch": branch_payload,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )



def main() -> None:
    ap = argparse.ArgumentParser(description="Stage142 reclaim cluster frontier")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    raw = root / "reports" / "research_raw"
    raw.mkdir(parents=True, exist_ok=True)

    main_rows, branch_rows, repaired_main, repaired_branch = s141._load_stage_state(raw)

    cfg = rcb.load_research_base_config(root)
    initial_equity = float(cfg.get("portfolio", {}).get("initial_equity", 100000.0))

    main_rows = _finalize_rows(list(main_rows), branch=False)

    scanned_branch: list[str] = []
    branch_map = {str(r.get("name")): copy.deepcopy(r) for r in branch_rows}
    for item in _new_branch_items():
        print(f"[stage142] branch {item['name']}", flush=True)
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

    frontier_txt = raw / "stage142_reclaim_cluster_frontier_latest.txt"
    frontier_json = raw / "stage142_reclaim_cluster_frontier_latest.json"
    _write_report(frontier_txt, frontier_json, main_rows, branch_rows, repaired_main, repaired_branch, scanned_branch)

    manifest = {
        "mode": "reclaim_cluster_frontier",
        "repaired_main": repaired_main,
        "repaired_branch": repaired_branch,
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
    manifest_path = raw / "stage142_reclaim_cluster_frontier_manifest_latest.json"
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
