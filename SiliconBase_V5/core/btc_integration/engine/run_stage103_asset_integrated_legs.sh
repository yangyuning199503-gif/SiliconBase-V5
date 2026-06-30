#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PROGRESS="$HOME/Downloads/stage103_progress_latest.txt"
KEYZIP="$HOME/Downloads/stage103_joint_key_files_latest.zip"
mkdir -p "$HOME/Downloads" "$ROOT/reports/research_raw"
: > "$PROGRESS"

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$PROGRESS"
}

if [ -x "$ROOT/.venv/bin/python" ]; then
  PY="$ROOT/.venv/bin/python"
else
  PY="$(command -v python3)"
fi

log 'stage103 start | joint adjust + asset integrated preview'

if [ -f "$ROOT/run_stage102_structural_focus.sh" ]; then
  log 'run stage102 joint adjust'
  bash "$ROOT/run_stage102_structural_focus.sh" | tee -a "$PROGRESS"
else
  log 'stage102 script missing; skip'
fi

log 'build stage103 asset integrated preview'
"$PY" -m tools.stage103_asset_integrated_legs --project-dir "$ROOT" | tee -a "$PROGRESS"

if [ -f "$ROOT/export_stage103_joint_key_files.sh" ]; then
  log 'export stage103 key files'
  bash "$ROOT/export_stage103_joint_key_files.sh" | tee -a "$PROGRESS"
fi

log "done | keyzip=$KEYZIP"
printf '%s\n' "$KEYZIP"
