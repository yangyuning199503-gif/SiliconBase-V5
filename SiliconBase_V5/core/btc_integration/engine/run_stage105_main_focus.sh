#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [ -x ./.venv/bin/python ]; then
  PY=./.venv/bin/python
else
  PY=python3
fi

$PY -m tools.stage88_strategy_fusion_walkforward --project-dir .
$PY -m tools.stage90_event_alpha_matrix --project-dir .
$PY -m tools.stage105_main_focus --project-dir .
bash run_send_files.sh

echo "$ROOT/reports/research_raw/stage105_main_focus_latest.txt"
echo "$ROOT/reports/research_raw/stage105_main_focus_latest.json"
