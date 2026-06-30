#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
RAW="$ROOT/reports/research_raw"
mkdir -p "$RAW"
PROGRESS="$HOME/Downloads/stage93_progress_latest.txt"
: > "$PROGRESS"

ts() { date '+[%Y-%m-%d %H:%M:%S]'; }
log() {
  local msg="$*"
  echo "$(ts) $msg" | tee -a "$PROGRESS"
}

bootstrap_venv() {
  log "Creating virtualenv .venv ..."
  rm -rf "$ROOT/.venv"
  python3 -m venv "$ROOT/.venv"
  PY="$ROOT/.venv/bin/python"
  "$PY" -m pip install --upgrade pip >/dev/null
  "$PY" -m pip install -r "$ROOT/requirements.txt" >/dev/null
  touch "$ROOT/.venv/.deps_installed"
}

need_venv=0
if [ ! -x "$PY" ] || ! "$PY" -c 'import sys; print(sys.executable)' >/dev/null 2>&1; then
  need_venv=1
elif [ ! -f "$ROOT/.venv/.deps_installed" ] || [ "$ROOT/requirements.txt" -nt "$ROOT/.venv/.deps_installed" ]; then
  need_venv=2
fi

if [ "$need_venv" -eq 1 ]; then
  bootstrap_venv
elif [ "$need_venv" -eq 2 ]; then
  log "Refreshing Python deps ..."
  "$PY" -m pip install -r "$ROOT/requirements.txt" >/dev/null
  touch "$ROOT/.venv/.deps_installed"
fi

is_fresh() {
  local p="$1"
  local max_age_min="${2:-720}"
  [ -f "$p" ] || return 1
  find "$p" -mmin -"$max_age_min" | grep -q .
}

stage90_json="$RAW/stage90_mainline_event_alpha_matrix_latest.json"
stage91_json="$RAW/stage91_branch_event_alpha_matrix_latest.json"
stage92_json="$RAW/stage92_eth_sol_open_frontier_latest.json"

log "Stage93 started"

if [ "${FORCE_STAGE90:-0}" = "1" ]; then
  log "FORCE_STAGE90=1 -> rerun stage90/91"
elif is_fresh "$stage90_json" 720 && is_fresh "$stage91_json" 720; then
  log "Using cached stage90/91 outputs (<=12h)"
else
  log "Running stage90/91 event matrix ... 这一步最慢，通常要几分钟到十几分钟"
  "$PY" -u -m tools.stage90_event_alpha_matrix --project-dir "$ROOT"
  log "stage90/91 done"
fi

if [ "${RUN_STAGE92:-0}" = "1" ]; then
  if [ "${FORCE_STAGE92:-0}" = "1" ]; then
    log "FORCE_STAGE92=1 -> rerun stage92"
  elif is_fresh "$stage92_json" 720; then
    log "Using cached stage92 output (<=12h)"
  else
    log "Running stage92 ETH/SOL frontier quick ..."
    "$PY" -u -m tools.stage92_eth_sol_open_frontier --project-dir "$ROOT" --profile quick --wf-per-lane 2 || true
    log "stage92 done"
  fi
else
  log "Skip stage92 by default for speed; set RUN_STAGE92=1 when you need ETH/SOL frontier refresh"
fi

log "Building stage93 summary ..."
"$PY" -u -m tools.stage93_frequency_accel --project-dir "$ROOT"
log "stage93 summary done"

if [ -f "$ROOT/run_send_files.sh" ]; then
  log "Packaging bundle ..."
  bash "$ROOT/run_send_files.sh" || log "run_send_files failed"
fi

log "done"
echo "$RAW/stage93_frequency_accel_latest.txt"
