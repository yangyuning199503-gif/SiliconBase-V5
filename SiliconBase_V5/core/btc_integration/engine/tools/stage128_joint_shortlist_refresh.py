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

MAINLINE_REF = "mainline_live_base"
MAINLINE_SHORTLIST = [
    "mainline_live_dynlev_fix8_lock18",
    "mainline_live_dynlev_fix10_lock12",
    "mainline_core_satellite_dynlev_fix8_lock18",
    "mainline_split_adx28_cd5_lb22_zone027",
]
BRANCH_SHORTLIST = [
    "eth_short_shock_fast_lb16_atr052_adx22_s078",
    "eth_retest_short_trend_lb20_atr060_adx24_s068",
    "eth_breakout_long_follow_lb16_atr050_adx22_s034",
    "btc_breakout_long_event_lb20_atr060_adx24_s050",
    "btc_dual_fast_trend_dynlev_fix8",
    "btc_retest_short_event_lb20_atr060_adx24_s072",
    "sol_hybrid_mr_shortonly",
    "sol_fast_trend_short_aggr_lb16_atr055_adx22_s076",
    "sol_long_core_soft_lb20_zone025_s042",
]


def _pick_items(all_items: list[dict[str, Any]], names: list[str]) -> list[dict[str, Any]]:
    item_map = {str(item.get("name")): item for item in all_items}
    picked: list[dict[str, Any]] = []
    for name in names:
        item = item_map.get(name)
        if item is not None:
            picked.append(item)
    return picked


def _prepend_shortlist_note(path_txt: Path, kind: str) -> None:
    if not path_txt.exists():
        return
    text = path_txt.read_text(encoding="utf-8")
    lines = text.splitlines()
    note = f"注：本轮为 {kind} shortlist refresh，只刷新当前重点候选，用于联动回测提速。"
    if note in lines:
        return
    if lines:
        lines.insert(1, note)
    else:
        lines = [note]
    path_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage128 joint shortlist refresh")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    reports_raw = root / "reports" / "research_raw"
    reports_raw.mkdir(parents=True, exist_ok=True)

    cfg = rcb.load_research_base_config(root)
    initial_equity = float(cfg.get("portfolio", {}).get("initial_equity", 100000.0))

    mainline_items_all = s88._mainline_items()
    branch_items_all = s88._branch_items()
    mainline_items = _pick_items(mainline_items_all, MAINLINE_SHORTLIST)
    branch_items = _pick_items(branch_items_all, BRANCH_SHORTLIST)

    if not mainline_items:
        raise SystemExit("mainline shortlist empty")
    if not branch_items:
        raise SystemExit("branch shortlist empty")

    data = s46._load_portfolio_data(root, cfg)
    full_start, full_end = s77._window_bounds_from_data(data)

    ref_item = next((item for item in mainline_items_all if str(item.get("name")) == MAINLINE_REF), None)
    if ref_item is None:
        raise SystemExit(f"missing mainline reference: {MAINLINE_REF}")
    ref_row = s90._run_mainline(root, cfg, data, ref_item, initial_equity, full_start, full_end)

    main_rows: list[dict[str, Any]] = []
    for item in mainline_items:
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

    main_txt = reports_raw / "stage90_mainline_event_alpha_matrix_latest.txt"
    main_json = reports_raw / "stage90_mainline_event_alpha_matrix_latest.json"
    s90._write_mainline(main_txt, main_json, main_rows)
    _prepend_shortlist_note(main_txt, "mainline")

    branch_rows: list[dict[str, Any]] = []
    for item in branch_items:
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

    branch_txt = reports_raw / "stage91_branch_event_alpha_matrix_latest.txt"
    branch_json = reports_raw / "stage91_branch_event_alpha_matrix_latest.json"
    s90._write_branch(branch_txt, branch_json, branch_rows)
    _prepend_shortlist_note(branch_txt, "branch")

    manifest = {
        "mode": "shortlist_refresh",
        "mainline_reference": MAINLINE_REF,
        "mainline_names": [str(x.get("name")) for x in mainline_items],
        "branch_names": [str(x.get("name")) for x in branch_items],
        "outputs": {
            "stage90_txt": str(main_txt),
            "stage90_json": str(main_json),
            "stage91_txt": str(branch_txt),
            "stage91_json": str(branch_json),
        },
    }
    _write_manifest(reports_raw / "stage128_joint_shortlist_manifest_latest.json", manifest)

    print(main_txt)
    print(main_json)
    print(branch_txt)
    print(branch_json)
    print(reports_raw / "stage128_joint_shortlist_manifest_latest.json")


if __name__ == "__main__":
    main()
