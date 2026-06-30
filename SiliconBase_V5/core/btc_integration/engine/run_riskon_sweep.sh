#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

mkdir -p reports logs data/raw

PY="./.venv/bin/python"
if [ ! -x "$PY" ]; then
  python3 -m venv .venv
  "$PY" -m pip install --upgrade pip >/dev/null
fi

MARKER=".venv/.deps_installed"
if [ ! -f "$MARKER" ]; then
  "$PY" -m pip install -r requirements.txt >/dev/null
  touch "$MARKER"
fi

"$PY" -m py_compile tools/sweep_riskon_hi.py

"$PY" tools/sweep_riskon_hi.py --config config.yml --objective recency --recent-months 24 --max-dd 0.35 --min-pf 1.15 --min-seg-pf 0.90

"$PY" -m tools.make_support_bundle .

"$PY" -m tools.send_files_pack --project-dir . --cleanup-downloads >/dev/null || true
echo "PUBLIC: $HOME/Downloads/okx_demo_report_latest.txt"
echo "PUBLIC: $HOME/Downloads/deepseek_single_file_latest.txt"
echo "PUBLIC: $HOME/Downloads/chatgpt_bundle_latest.zip"
