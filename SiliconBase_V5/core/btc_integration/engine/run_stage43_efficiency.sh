#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ -x ./.venv/bin/python && ! -L ./.venv/bin/python ]]; then
  PY=./.venv/bin/python
elif [[ -x ./.venv/bin/python3 && ! -L ./.venv/bin/python3 ]]; then
  PY=./.venv/bin/python3
else
  PY="$(command -v python3)"
fi
"$PY" -m tools.stage43_efficiency_lab --project-dir .
"$PY" -m tools.polymarket_probe --out reports/research_raw/polymarket_probe_latest.txt --json-out reports/research_raw/polymarket_probe_latest.json
"$PY" -m tools.stage43_pack_outputs --project-dir .
echo "[OK] stage43 done | outputs: ~/Downloads/deepseek_single_file_latest.txt + ~/Downloads/chatgpt_bundle_latest.zip"
