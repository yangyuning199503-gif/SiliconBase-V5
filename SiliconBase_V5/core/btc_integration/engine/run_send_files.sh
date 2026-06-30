#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
CANON="$HOME/btc_system_v1"
if [ "$ROOT" != "$CANON" ] && [ -d "$CANON" ]; then
  echo "[ERR] 请在 ~/btc_system_v1 运行。当前目录: $ROOT" >&2
  exit 1
fi
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
if [ ! -x "$PY" ] || ! "$PY" -c 'import sys; print(sys.executable)' >/dev/null 2>&1; then
  bootstrap_venv
elif [ ! -f .venv/.deps_installed ] || [ requirements.txt -nt .venv/.deps_installed ]; then
  "$PY" -m pip install -r requirements.txt >/dev/null
  touch .venv/.deps_installed
fi

"$PY" -m tools.send_files_pack --project-dir . --cleanup-downloads

if [ ! -f "$HOME/Downloads/chatgpt_bundle_latest.zip" ] || [ ! -f "$ROOT/reports/chatgpt_bundle_latest.zip" ]; then
  echo "[ERR] bundle 未生成成功" >&2
  exit 2
fi

echo "[OK] bundle=~/Downloads/chatgpt_bundle_latest.zip"
echo "[OK] backup=~/btc_system_v1/reports/chatgpt_bundle_latest.zip"
