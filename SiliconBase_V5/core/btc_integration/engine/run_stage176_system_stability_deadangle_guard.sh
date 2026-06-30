#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

PY_BIN="python3"
if [ -x "$ROOT_DIR/.venv/bin/python" ]; then
  PY_BIN="$ROOT_DIR/.venv/bin/python"
fi

"$PY_BIN" -m py_compile \
  tools/raw_data_guard.py \
  tools/repair_raw_from_snapshots.py \
  tools/okx_demo_shadow_exec.py \
  tools/okx_demo_autopilot.py \
  tools/stage166_data_deadangle_audit.py \
  tools/stage167_data_repair_diversity_guard.py \
  tools/stage168_bnb_gap_quarantine_and_family_cap.py \
  tools/stage176_system_stability_deadangle_guard.py

bash -n start_okx_demo.sh start_branch_demo.sh start_branch_demo_triple_book.sh run.sh run_precheck.sh

"$PY_BIN" tools/stage176_system_stability_deadangle_guard.py --project-dir "$ROOT_DIR"
