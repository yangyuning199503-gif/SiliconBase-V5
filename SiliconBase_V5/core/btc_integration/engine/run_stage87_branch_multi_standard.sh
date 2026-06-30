#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
  PY=python3
fi

"$PY" -m tools.stage78_branch_dual_window_lab --project-dir "$ROOT"
"$PY" -m tools.stage86_branch_fast_matrix --project-dir "$ROOT" --per-lane 5
"$PY" -m tools.stage82_branch_walkforward_lab --project-dir "$ROOT"

if [ -f "$ROOT/run_send_files.sh" ]; then
  bash "$ROOT/run_send_files.sh"
fi
