#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"

bootstrap_venv() {
  echo "Creating virtualenv .venv ..."
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
  "$PY" -m pip install -r "$ROOT/requirements.txt" >/dev/null
  touch "$ROOT/.venv/.deps_installed"
fi

run_stage91_optional() {
  if [ -f "$ROOT/tools/stage91_branch_event_alpha_matrix.py" ]; then
    "$PY" -m tools.stage91_branch_event_alpha_matrix --project-dir "$ROOT"
  elif [ -f "$ROOT/run_stage91_branch_event_alpha_matrix.sh" ]; then
    bash "$ROOT/run_stage91_branch_event_alpha_matrix.sh"
  elif [ -f "$ROOT/run_stage91_branch_event_alpha.sh" ]; then
    bash "$ROOT/run_stage91_branch_event_alpha.sh"
  else
    echo "[skip] stage91 runner not found"
  fi
}

RAW="$ROOT/reports/research_raw"
mkdir -p "$RAW"

"$PY" -m tools.stage90_event_alpha_matrix --project-dir "$ROOT"
run_stage91_optional || true
if [ -f "$ROOT/tools/stage92_eth_sol_open_frontier.py" ]; then
  "$PY" -m tools.stage92_eth_sol_open_frontier --project-dir "$ROOT" --profile quick --wf-per-lane 2 || true
fi
if [ -f "$ROOT/tools/stage93_frequency_accel.py" ]; then
  "$PY" -m tools.stage93_frequency_accel --project-dir "$ROOT"
fi
"$PY" -m tools.stage94_priority_pipeline --project-dir "$ROOT"

if [ -f "$ROOT/run_send_files.sh" ]; then
  bash "$ROOT/run_send_files.sh"
fi

echo "[ok] stage94 done"
echo "$RAW/stage94_priority_pipeline_latest.txt"
