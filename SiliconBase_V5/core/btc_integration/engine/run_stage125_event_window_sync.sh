#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
  PY="python3"
fi
"$PY" -m py_compile "$ROOT/tools/stage90_event_alpha_matrix.py"
bash "$ROOT/run_stage120_event_window_frontier.sh"
echo "stage125_event_window_sync_done"
