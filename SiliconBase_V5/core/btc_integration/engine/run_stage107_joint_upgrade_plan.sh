#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
DL="$HOME/Downloads"
PROG="$DL/stage107_progress_latest.txt"
mkdir -p "$DL" "$ROOT/reports/research_raw" "$ROOT/reports"
: > "$PROG"
log(){ printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$PROG" >/dev/null; }

bootstrap_venv() {
  log 'bootstrap .venv'
  rm -rf "$ROOT/.venv"
  python3 -m venv "$ROOT/.venv"
  PY="$ROOT/.venv/bin/python"
  "$PY" -m pip install --upgrade pip >/dev/null
  "$PY" -m pip install -r "$ROOT/requirements.txt" >/dev/null
  touch "$ROOT/.venv/.deps_installed"
}

if [ ! -x "$PY" ] || ! "$PY" -c 'import sys; print(sys.executable)' >/dev/null 2>&1; then
  bootstrap_venv
elif [ ! -f "$ROOT/.venv/.deps_installed" ] || [ "$ROOT/requirements.txt" -nt "$ROOT/.venv/.deps_installed" ]; then
  log 'refresh deps'
  "$PY" -m pip install -r "$ROOT/requirements.txt" >/dev/null
  touch "$ROOT/.venv/.deps_installed"
fi

if [ ! -f "$ROOT/reports/research_raw/stage91_branch_event_alpha_matrix_latest.json" ]; then
  echo '缺少 stage91_branch_event_alpha_matrix_latest.json' | tee -a "$PROG"
  exit 2
fi
if [ ! -f "$ROOT/reports/research_raw/stage99_mainline_frequency_push_latest.txt" ]; then
  log 'stage99 missing -> reuse current mainline report only'
fi

log 'build stage107 joint upgrade plan'
"$PY" -m tools.stage107_joint_upgrade_plan --project-dir "$ROOT" | tee -a "$PROG"

log 'export stage107 zip'
bash "$ROOT/export_stage107_joint_upgrade_plan.sh" | tee -a "$PROG"
log 'done'
