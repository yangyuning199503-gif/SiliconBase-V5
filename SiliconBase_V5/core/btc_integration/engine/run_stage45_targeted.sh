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

"$PY" -m tools.stage45_targeted_lab --project-dir .
"$PY" -m tools.polymarket_probe --out reports/research_raw/polymarket_probe_latest.txt --json-out reports/research_raw/polymarket_probe_latest.json || true
"$PY" -m tools.stage45_pack_outputs --project-dir .
echo "[OK] stage45 done | outputs: ~/Downloads/deepseek_single_file_latest.txt + ~/Downloads/chatgpt_bundle_latest.zip"
