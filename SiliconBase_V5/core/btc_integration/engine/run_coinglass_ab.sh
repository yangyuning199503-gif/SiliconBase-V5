#!/usr/bin/env bash
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

mkdir -p reports logs

PY="./.venv/bin/python"
bootstrap_venv() {
  echo "Creating virtualenv .venv ..."
  rm -rf .venv
  python3 -m venv .venv
  PY="./.venv/bin/python"
  "$PY" -m pip install --upgrade pip >/dev/null
}

if [ ! -x "$PY" ] || ! "$PY" -c 'import sys; print(sys.executable)' >/dev/null 2>&1; then
  bootstrap_venv
fi

MARKER=".venv/.deps_installed"
if [ ! -f "$MARKER" ] || [ requirements.txt -nt "$MARKER" ]; then
  "$PY" -m pip install -r requirements.txt >/dev/null
  touch "$MARKER"
fi

"$PY" -m py_compile tools/coinglass_ab_backtest.py >/dev/null
code=0
mkdir -p reports/research_raw
"$PY" -m tools.coinglass_ab_backtest --project-dir . --out-dir reports/research_raw/coinglass_ab_latest "$@" || code=$?
echo "已生成(无论成功/失败都会覆盖): reports/research_raw/coinglass_ab_latest/"
exit "$code"
