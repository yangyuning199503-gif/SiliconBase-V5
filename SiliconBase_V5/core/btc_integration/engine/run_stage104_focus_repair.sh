#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [ -x ./.venv/bin/python ]; then
  PY=./.venv/bin/python
else
  PY=python3
fi

$PY -m tools.stage90_event_alpha_matrix --project-dir .
bash run_send_files.sh

echo "$ROOT/reports/research_raw/stage90_mainline_event_alpha_matrix_latest.txt"
echo "$ROOT/reports/research_raw/stage91_branch_event_alpha_matrix_latest.txt"
