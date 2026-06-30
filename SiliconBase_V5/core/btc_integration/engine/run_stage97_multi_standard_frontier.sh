#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
  PY="$(command -v python3)"
fi
LOG="$HOME/Downloads/stage97_progress_latest.txt"
mkdir -p "$HOME/Downloads"
: > "$LOG"
log(){ printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG"; }
run(){ log "$*"; "$@" 2>&1 | tee -a "$LOG"; }
PROFILE="${1:-quick}"
WF_PER_LANE="${2:-2}"
log "stage97 start profile=$PROFILE wf_per_lane=$WF_PER_LANE"
run "$PY" -m tools.stage90_event_alpha_matrix --project-dir .
run "$PY" -m tools.stage92_eth_sol_open_frontier --project-dir . --profile "$PROFILE" --wf-per-lane "$WF_PER_LANE"
run "$PY" -m tools.stage96_event_bridge --project-dir .
run "$PY" -m tools.stage97_multi_standard_frontier --project-dir .
if [ -f "$ROOT/run_send_files.sh" ]; then
  run bash "$ROOT/run_send_files.sh"
fi
log "stage97 done"
echo "$ROOT/reports/research_raw/stage97_multi_standard_frontier_latest.txt"
