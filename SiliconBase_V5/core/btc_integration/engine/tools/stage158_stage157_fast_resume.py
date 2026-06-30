from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import contextlib

from tools import stage141_guarded_asymmetry_shortlist as s141
from tools import stage152_multiasset_playbook_frontier as s152
from tools import stage157_regime_playbook_accel_frontier as s157


def _load_rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        rows = payload.get("rows")
        if isinstance(rows, list):
            return rows
    return []


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage158 fast resume for stage157 report export")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    raw = root / "reports" / "research_raw"
    raw.mkdir(parents=True, exist_ok=True)

    main_json = raw / "stage90_mainline_event_alpha_matrix_latest.json"
    branch_json = raw / "stage91_branch_event_alpha_matrix_latest.json"
    if not main_json.exists() or not branch_json.exists():
        raise SystemExit("missing stage90/stage91 latest json for fast resume")

    main_rows = _load_rows(main_json)
    branch_rows = _load_rows(branch_json)
    if not main_rows or not branch_rows:
        raise SystemExit("stage90/stage91 latest json has no rows for fast resume")

    repaired_main: list[str] = []
    repaired_branch: list[str] = []
    with contextlib.suppress(Exception):
        _, _, repaired_main, repaired_branch = s141._load_stage_state(raw)

    scanned_main = [str(item.get("name")) for item in s157._new_mainline_items() if item.get("name")]
    scanned_branch = [str(item.get("name")) for item in s157._new_branch_items() if item.get("name")]
    active_map = {sym: s152._active_asset_name(branch_json, sym) for sym in ["BTC", "ETH", "SOL"]}

    frontier_txt = raw / "stage157_regime_playbook_accel_frontier_latest.txt"
    frontier_json = raw / "stage157_regime_playbook_accel_frontier_latest.json"
    s157._write_report(
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
        "mode": "regime_playbook_accel_frontier_fast_resume",
        "bug_guard": True,
        "resume_only": True,
        "repaired_main": repaired_main,
        "repaired_branch": repaired_branch,
        "new_mainline_candidates": scanned_main,
        "new_branch_candidates": scanned_branch,
        "stage91_active": active_map,
        "outputs": {
            "stage90_json": str(main_json),
            "stage91_json": str(branch_json),
            "frontier_txt": str(frontier_txt),
            "frontier_json": str(frontier_json),
        },
    }
    manifest_path = raw / "stage157_regime_playbook_accel_frontier_manifest_latest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    s141._mirror_to_workspace(root, [frontier_txt, frontier_json, manifest_path])

    print(frontier_txt)
    print(frontier_json)
    print(manifest_path)


if __name__ == "__main__":
    main()
