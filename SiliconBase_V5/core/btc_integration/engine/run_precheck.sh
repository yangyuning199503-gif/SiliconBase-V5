#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

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

"$PY" -m tools.repair_raw_from_snapshots --project-dir . --config config.yml >/dev/null || true

"$PY" -m tools.raw_data_guard --project-dir . --config config.yml
