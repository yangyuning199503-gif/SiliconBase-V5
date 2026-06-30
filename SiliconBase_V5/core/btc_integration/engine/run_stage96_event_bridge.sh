#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
CANON="$HOME/btc_system_v1"
if [ "$ROOT" != "$CANON" ] && [ -d "$CANON" ]; then
  echo "[ERR] 请在 ~/btc_system_v1 运行。当前目录: $ROOT" >&2
  exit 1
fi
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

mkdir -p "$ROOT/reports/research_raw"
echo "[1/3] stage90/stage91 event alpha matrix ..."
"$PY" -m tools.stage90_event_alpha_matrix --project-dir .
echo "[2/3] stage96 event bridge summary ..."
"$PY" -m tools.stage96_event_bridge --project-dir .
echo "[3/3] bundle ..."
bash "$ROOT/run_send_files.sh"
echo "$HOME/Downloads/chatgpt_bundle_latest.zip"
