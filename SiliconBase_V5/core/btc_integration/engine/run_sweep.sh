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

"$PY" -m pip install -r requirements.txt >/dev/null

# Run a quick sizing sweep and select the best run as the latest.
"$PY" -m tools.sweep_slices --config config.yml --slices 10,6,4,3,2 --objective ret --max-dd 0.45 --min-pf 1.05

# Package the latest run (selected by sweep_slices).
"$PY" -m tools.make_support_bundle .

"$PY" -m tools.send_files_pack --project-dir . --cleanup-downloads >/dev/null || true
echo "PUBLIC: $HOME/Downloads/okx_demo_report_latest.txt"
echo "PUBLIC: $HOME/Downloads/deepseek_single_file_latest.txt"
echo "PUBLIC: $HOME/Downloads/chatgpt_bundle_latest.zip"
