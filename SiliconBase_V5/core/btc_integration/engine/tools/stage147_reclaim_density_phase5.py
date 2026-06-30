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
from tools import stage145_reclaim_plateau_phase3 as s145

TARGET_MONTHLY_MIN = s136.TARGET_MONTHLY_MIN
TARGET_MONTHLY_MAX = s136.TARGET_MONTHLY_MAX


def _with_meta(item: dict[str, Any], *, track: str, branch: bool, anchor_name: str | None = None) -> dict[str, Any]:
    out = s136._with_meta(item, track=track, branch=branch)
    out.setdefault("meta", {})
    out["meta"]["anchor_name"] = str(anchor_name or out.get("name") or "")
    out["meta"].setdefault("risk_scale", 1.0)
    return out


def _new_branch_items() -> list[dict[str, Any]]:
    item_map = {str(item.get("name")): item for item in s88._branch_items()}
    eth_long = item_map.get("eth_breakout_long_follow_lb16_atr050_adx22_s034")
    eth_short = item_map.get("eth_retest_short_trend_lb20_atr060_adx24_s068")
    out: list[dict[str, Any]] = []
    if eth_long is None:
        return out

    anchor_long = "eth_reclaim_long_lb11_atr043_adx16_s060"
    long_variants = [
        (
            "eth_reclaim_long_lb11_atr043_adx15_cd3_s048",
            "ETH reclaim phase5：先提频再看样本外，lb11 核心上把 ADX 放松一档并改 cd3。",
            {
                "strategy_params.breakout_lookback": 11,
                "strategy_params.breakout_atr_buffer": 0.43,
                "strategy_params.cooldown_bars": 3,
                "filters.adx_floor": 15,
                "money_management.stake_scale.eth_long": 0.48,
            },
        ),
        (
            "eth_reclaim_long_lb11_atr043_adx15_cd3_s052",
            "ETH reclaim phase5：lb11+cd3 中档预算，专看提频后近2年/WF 是否还能一起站住。",
            {
                "strategy_params.breakout_lookback": 11,
                "strategy_params.breakout_atr_buffer": 0.43,
                "strategy_params.cooldown_bars": 3,
                "filters.adx_floor": 15,
                "money_management.stake_scale.eth_long": 0.52,
            },
        ),
        (
            "eth_reclaim_long_lb11_atr043_adx15_cd3_s056",
            "ETH reclaim phase5：lb11+cd3 再上提一格预算，只看 target_monthly 能否继续抬升而不过拟合。",
            {
                "strategy_params.breakout_lookback": 11,
                "strategy_params.breakout_atr_buffer": 0.43,
                "strategy_params.cooldown_bars": 3,
                "filters.adx_floor": 15,
                "money_management.stake_scale.eth_long": 0.56,
            },
        ),
        (
            "eth_reclaim_long_lb11_atr043_adx16_cd3_s052",
            "ETH reclaim phase5：不改 ADX，只把 cd3 打开，单测密度增量是否足够干净。",
            {
                "strategy_params.breakout_lookback": 11,
                "strategy_params.breakout_atr_buffer": 0.43,
                "strategy_params.cooldown_bars": 3,
                "filters.adx_floor": 16,
                "money_management.stake_scale.eth_long": 0.52,
            },
        ),
        (
            "eth_reclaim_long_lb11_atr044_adx16_cd3_s052",
            "ETH reclaim phase5：更保守缓冲 + cd3，检查提频时是否还能保住平台厚度。",
            {
                "strategy_params.breakout_lookback": 11,
                "strategy_params.breakout_atr_buffer": 0.44,
                "strategy_params.cooldown_bars": 3,
                "filters.adx_floor": 16,
                "money_management.stake_scale.eth_long": 0.52,
            },
        ),
        (
            "eth_reclaim_long_lb12_atr043_adx15_cd3_s056",
            "ETH reclaim phase5：lb12 慢半拍确认也开 cd3，避免只盯 lb11 一条路。",
            {
                "strategy_params.breakout_lookback": 12,
                "strategy_params.breakout_atr_buffer": 0.43,
                "strategy_params.cooldown_bars": 3,
                "filters.adx_floor": 15,
                "money_management.stake_scale.eth_long": 0.56,
            },
        ),
    ]
    for name, note, patch in long_variants:
        out.append(
            _with_meta(
                s88._make_variant(
                    eth_long,
                    name=name,
                    note=note,
                    family="long",
                    patch=patch,
                ),
                track="reclaim",
                branch=True,
                anchor_name=anchor_long,
            )
        )

    if eth_short is not None:
        anchor_short = "eth_retest_short_trend_lb20_atr060_adx24_s068"
        short_variants = [
            (
                "eth_retest_short_trend_lb20_atr060_adx24_cd3_s068",
                "ETH short 保留位：不改骨架，只开 cd3 看空腿频次能否补起来。",
                {
                    "strategy_params.breakout_lookback": 20,
                    "strategy_params.breakout_atr_buffer": 0.60,
                    "strategy_params.cooldown_bars": 3,
                    "filters.adx_floor": 24,
                    "money_management.stake_scale.eth_short": 0.68,
                },
            ),
            (
                "eth_retest_short_trend_lb18_atr056_adx22_cd3_s064",
                "ETH short 保留位：更快回踩确认 + cd3，只保路径不让空腿断代。",
                {
                    "strategy_params.breakout_lookback": 18,
                    "strategy_params.breakout_atr_buffer": 0.56,
                    "strategy_params.cooldown_bars": 3,
                    "filters.adx_floor": 22,
                    "money_management.stake_scale.eth_short": 0.64,
                },
            ),
        ]
        for name, note, patch in short_variants:
            out.append(
                _with_meta(
                    s88._make_variant(
                        eth_short,
                        name=name,
                        note=note,
                        family="short",
                        patch=patch,
                    ),
                    track="reclaim_short",
                    branch=True,
                    anchor_name=anchor_short,
                )
            )
    return out


def _frontier_score(row: dict[str, Any], rows: list[dict[str, Any]], *, branch: bool) -> float:
    base = s145._frontier_score(row, rows, branch=branch)
    if not branch:
        return float(base)

    dom = row.get("dominant_gate", {}) or {}
    recent = dom.get("recent_metrics", {}) or {}
    wf = (row.get("walkforward") or {}).get("metrics", {}) or {}
    plateau = row.get("plateau", {}) or {}
    meta = row.get("meta", {}) or {}

    name = str(row.get("name") or "")
    sym = str(row.get("symbol") or "").lower()
    fam = str(row.get("family") or "").lower()
    track = str(meta.get("track") or "base")
    recent_trades = int(recent.get("trades", 0) or 0)
    wf_trades = int(wf.get("trades", 0) or 0)
    recent_pf = s88._safe_float(recent.get("pf"))
    wf_pf = s88._safe_float(wf.get("pf"))
    recent_monthly = s88._safe_float(recent.get("monthlyized_ret"))
    wf_monthly = s88._safe_float(wf.get("monthlyized_ret"))
    wf_dd = abs(s88._safe_float(wf.get("maxdd")))
    full_dd = abs(s88._safe_float((row.get("full_metrics") or {}).get("maxdd")))
    plateau_q = s88._safe_float(plateau.get("plateau"))
    neighbor_count = int(plateau.get("neighbor_count", 0) or 0)
    cooldown = s88._safe_float(meta.get("cooldown"))
    adx = s88._safe_float(meta.get("adx"))
    lookback = s88._safe_float(meta.get("lookback"))
    month = s136._target_monthly(row, branch=branch)

    bonus = 0.0
    penalty = 0.0

    if sym == "eth" and fam == "long" and track == "reclaim":
        if cooldown <= 3.0:
            bonus += 8.0
            if recent_trades >= 30 and wf_trades >= 20:
                bonus += 12.0
            elif recent_trades >= 28 and wf_trades >= 18:
                bonus += 6.0
        if adx <= 15.5:
            bonus += 4.0
        if lookback <= 11.0:
            bonus += 3.0
        if recent_monthly >= 0.022 and wf_monthly >= 0.025:
            bonus += 10.0
        if month >= 0.026:
            bonus += 8.0
        if plateau_q >= 0.45 and neighbor_count >= 3:
            bonus += 10.0

        if recent_trades < 24 or wf_trades < 16:
            penalty += 8.0
        if wf_dd > 0.055:
            penalty += 10.0
        if full_dd > 0.60:
            penalty += 6.0
        if recent_pf > 6.0 or wf_pf > 10.0 or "hold" in name.lower():
            penalty += 18.0
        if recent_monthly > max(0.0, wf_monthly * 1.9) and plateau_q < 0.40:
            penalty += 10.0

    if sym == "eth" and fam == "short":
        if cooldown <= 3.0:
            bonus += 4.0
        if recent_trades >= 40 and wf_trades >= 30 and recent_pf >= 1.2 and wf_pf >= 1.2:
            bonus += 8.0
        if recent_monthly > 0.0 and wf_monthly > 0.0:
            bonus += 4.0
        if wf_dd <= 0.08:
            bonus += 2.0
        if recent_trades < 20 or wf_trades < 20:
            penalty += 4.0
        if wf_pf < 1.1:
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


def _active_asset_name(branch_json: Path, symbol: str) -> str:
    try:
        payload = json.loads(branch_json.read_text(encoding="utf-8"))
    except Exception:
        return ""
    items = payload.get("asset_summary") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return ""
    for item in items:
        if str(item.get("symbol") or "").upper() == symbol.upper():
            active = item.get("active") if isinstance(item.get("active"), dict) else {}
            return str(active.get("name") or "")
    return ""


def _write_report(
    path_txt: Path,
    path_json: Path,
    main_rows: list[dict[str, Any]],
    branch_rows: list[dict[str, Any]],
    repaired_main: list[str],
    repaired_branch: list[str],
    scanned_branch: list[str],
    active_eth: str,
) -> None:
    main_payload = [s136._payload_row(r, branch=False) for r in main_rows]
    branch_payload = [s136._payload_row(r, branch=True) for r in branch_rows]

    reclaim_focus = [
        r for r in branch_payload
        if str(r.get("symbol") or "").lower() == "eth" and str(r.get("track") or "") == "reclaim"
    ]
    short_focus = [
        r for r in branch_payload
        if str(r.get("symbol") or "").lower() == "eth" and str(r.get("family") or "") == "short"
    ]

    lines: list[str] = []
    lines.append("Stage147 reclaim density phase5")
    lines.append("原则：不再刷同一圈低密度点，直接围绕 ETH reclaim 最强簇做 cd3 提频验证；ETH short 继续保留。")
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
    lines.append("=== ETH reclaim density（前8） ===")
    for row in reclaim_focus[:8]:
        lines.append(
            f"- {row['name']}: target_monthly={row['target_monthly']*100:.2f}% | plateau={row['plateau']:.2f}/{row['neighbor_count']} | 近2年={row['recent_monthly']*100:.2f}%/{row['recent_trades']}笔/PF{row['recent_pf']:.3f} | WF={row['wf_monthly']*100:.2f}%/{row['wf_trades']}笔/PF{row['wf_pf']:.3f} | decision={row['decision']}"
        )
    lines.append("")
    lines.append("=== ETH short 保留位 ===")
    for row in short_focus[:4]:
        lines.append(
            f"- {row['name']}: target_monthly={row['target_monthly']*100:.2f}% | 近2年={row['recent_monthly']*100:.2f}%/{row['recent_trades']}笔/PF{row['recent_pf']:.3f} | WF={row['wf_monthly']*100:.2f}%/{row['wf_trades']}笔/PF{row['wf_pf']:.3f} | decision={row['decision']}"
        )
    lines.append("")
    lines.append("=== 结论 ===")
    if main_payload:
        top = main_payload[0]
        lines.append(f"- 主线第一名: {top['name']} | target_monthly={top['target_monthly']*100:.2f}% | gap_to_7.6={top['gap_to_floor']*100:.2f}%")
    if reclaim_focus:
        top = reclaim_focus[0]
        lines.append(f"- ETH reclaim 第一名: {top['name']} | target_monthly={top['target_monthly']*100:.2f}% | plateau={top['plateau']:.2f} | gap_to_7.6={top['gap_to_floor']*100:.2f}%")
    if active_eth:
        lines.append(f"- stage91 ETH active: {active_eth}")
    lines.append("- 这轮只刷 reclaim 提频，不动现有模拟盘链路。")

    payload = {
        "mode": "reclaim_density_phase5",
        "target_monthly_min": TARGET_MONTHLY_MIN,
        "target_monthly_max": TARGET_MONTHLY_MAX,
        "repaired_main": repaired_main,
        "repaired_branch": repaired_branch,
        "new_branch_candidates": scanned_branch,
        "active_eth": active_eth,
        "mainline": main_payload,
        "branch": branch_payload,
        "eth_reclaim": reclaim_focus,
        "eth_short": short_focus,
    }
    path_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    path_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage147 reclaim density phase5")
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
        print(f"[stage147] branch {item['name']}", flush=True)
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

    active_eth = _active_asset_name(branch_json, "ETH")

    frontier_txt = raw / "stage147_reclaim_density_phase5_latest.txt"
    frontier_json = raw / "stage147_reclaim_density_phase5_latest.json"
    _write_report(frontier_txt, frontier_json, main_rows, branch_rows, repaired_main, repaired_branch, scanned_branch, active_eth)

    manifest = {
        "mode": "reclaim_density_phase5",
        "repaired_main": repaired_main,
        "repaired_branch": repaired_branch,
        "new_branch_candidates": scanned_branch,
        "active_eth": active_eth,
        "outputs": {
            "stage90_txt": str(main_txt),
            "stage90_json": str(main_json),
            "stage91_txt": str(branch_txt),
            "stage91_json": str(branch_json),
            "frontier_txt": str(frontier_txt),
            "frontier_json": str(frontier_json),
        },
    }
    manifest_path = raw / "stage147_reclaim_density_phase5_manifest_latest.json"
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
