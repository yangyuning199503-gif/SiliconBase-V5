#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PY="./.venv/bin/python"

bootstrap_venv() {
  echo "Creating virtualenv .venv ..."
  rm -rf .venv
  python3 -m venv .venv
  PY="./.venv/bin/python"
  "$PY" -m pip install --upgrade pip >/dev/null
  "$PY" -m pip install -r requirements.txt >/dev/null
  touch .venv/.deps_installed
}

needs_install() {
  "$PY" - <<'PY' >/dev/null 2>&1
import importlib
for name in ["pandas", "requests", "websocket", "yaml", "numpy"]:
    importlib.import_module(name)
PY
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

if ! "$PY" -c 'import tools.stage46_aggressive_lab' >/dev/null 2>&1; then
  echo "[ERROR] 缺少 stage46_aggressive_lab。请先保留 stage46/49 补丁。" >&2
  exit 1
fi

DOWNLOADS="$HOME/Downloads"
mkdir -p "$DOWNLOADS"
rm -f "$DOWNLOADS/chatgpt_bundle_latest.zip" "$DOWNLOADS/deepseek_single_file_latest.txt"

START_EPOCH="$(date +%s)"
export CHATGPT_BUNDLE_START_EPOCH="$START_EPOCH"

"$PY" -m tools.stage51_aggressive_frontier_lab --project-dir .
"$PY" -m tools.stage51_pack_outputs --project-dir . --started-at "$START_EPOCH"

echo "[OK] stage51 done | outputs refreshed: ~/Downloads/deepseek_single_file_latest.txt + ~/Downloads/chatgpt_bundle_latest.zip"
