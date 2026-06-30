#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PY="./.venv/bin/python"

bootstrap_venv() {
  python3 -m venv .venv
  PY="./.venv/bin/python"
  "$PY" -m pip install --upgrade pip >/dev/null
  "$PY" -m pip install -r requirements.txt >/dev/null
  touch .venv/.deps_installed
}

needs_install() {
  "$PY" - <<'PYEOF' >/dev/null 2>&1
import importlib
for name in ["pandas", "numpy", "yaml", "requests"]:
    importlib.import_module(name)
PYEOF
}

if [ ! -x "$PY" ] || ! "$PY" -c 'import sys; print(sys.executable)' >/dev/null 2>&1; then
  bootstrap_venv
elif [ ! -f .venv/.deps_installed ] || [ requirements.txt -nt .venv/.deps_installed ]; then
  "$PY" -m pip install -r requirements.txt >/dev/null
  touch .venv/.deps_installed
elif ! needs_install; then
  "$PY" -m pip install -r requirements.txt >/dev/null
  touch .venv/.deps_installed
fi

DOWNLOADS="$HOME/Downloads"
mkdir -p "$DOWNLOADS"
rm -f "$DOWNLOADS/chatgpt_bundle_latest.zip" "$DOWNLOADS/deepseek_single_file_latest.txt"

START_EPOCH="$(date +%s)"
export CHATGPT_BUNDLE_START_EPOCH="$START_EPOCH"

bash run_local_info_sources_test.sh
COINGLASS_HISTORY_REFRESH=1 bash run_message_stack_backtest.sh
"$PY" -m tools.stage75_mainline_event_state_lab --project-dir .
"$PY" -m tools.stage76_branch_event_state_lab --project-dir .
"$PY" -m tools.stage76_pack_outputs --project-dir . --started-at "$START_EPOCH"

echo "[OK] stage75/76 done | bundle refreshed: ~/Downloads/chatgpt_bundle_latest.zip"
