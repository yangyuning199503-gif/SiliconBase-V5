#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
  python3 -m venv "$ROOT/.venv"
  "$PY" -m pip install --upgrade pip >/dev/null
  "$PY" -m pip install -r "$ROOT/requirements.txt" >/dev/null
fi
mkdir -p "$HOME/Downloads/stage94_key_files"
cp -f "$ROOT/reports/research_raw/stage92_eth_sol_open_frontier_latest.txt" "$HOME/Downloads/stage94_key_files/" 2>/dev/null || true
cp -f "$ROOT/reports/research_raw/stage92_eth_sol_open_frontier_latest.json" "$HOME/Downloads/stage94_key_files/" 2>/dev/null || true
cp -f "$ROOT/reports/research_raw/stage93_frequency_accel_latest.txt" "$HOME/Downloads/stage94_key_files/" 2>/dev/null || true
cp -f "$ROOT/reports/research_raw/stage93_frequency_accel_latest.json" "$HOME/Downloads/stage94_key_files/" 2>/dev/null || true
cp -f "$ROOT/reports/research_raw/stage94_branch_refresh_frontier_latest.txt" "$HOME/Downloads/stage94_key_files/" 2>/dev/null || true
cp -f "$ROOT/reports/research_raw/branch_raw_freshness_latest.txt" "$HOME/Downloads/stage94_key_files/" 2>/dev/null || true
cp -f "$HOME/Downloads/okx_demo_report_latest.txt" "$HOME/Downloads/stage94_key_files/" 2>/dev/null || true
cp -f "$HOME/Downloads/branch_demo_report_latest.txt" "$HOME/Downloads/stage94_key_files/" 2>/dev/null || true
if [ -f "$ROOT/run_send_files.sh" ]; then
  bash "$ROOT/run_send_files.sh" >/dev/null
fi
cd "$HOME/Downloads"
rm -f stage94_key_files_latest.zip
zip -qr stage94_key_files_latest.zip stage94_key_files
ls -lh "$HOME/Downloads/stage94_key_files_latest.zip"
ls -lh "$HOME/Downloads/chatgpt_bundle_latest.zip" 2>/dev/null || true
