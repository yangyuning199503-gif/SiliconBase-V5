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

PROFILE="${1:-quick}"
WF_PER_LANE="${2:-2}"
"$PY" -m tools.stage92_eth_sol_open_frontier --project-dir "$ROOT" --profile "$PROFILE" --wf-per-lane "$WF_PER_LANE"

if [ -f "$ROOT/run_send_files.sh" ]; then
  bash "$ROOT/run_send_files.sh"
fi

echo "$ROOT/reports/research_raw/stage92_eth_sol_open_frontier_latest.txt"
