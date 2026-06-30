#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
DOWNLOADS="$HOME/Downloads"
mkdir -p "$DOWNLOADS"
rm -f "$DOWNLOADS/chatgpt_bundle_latest.zip" "$DOWNLOADS/deepseek_single_file_latest.txt"
START_EPOCH="$(date +%s)"
export CHATGPT_BUNDLE_START_EPOCH="$START_EPOCH"
echo "[1/7] mainline density"
bash run_mainline_density_lab.sh
echo "[2/7] message stack"
COINGLASS_HISTORY_REFRESH=1 bash run_message_stack_backtest.sh
echo "[3/7] branch full research"
bash run_branch_fast_research.sh full
echo "[4/7] local info sources"
bash run_local_info_sources_test.sh
echo "[5/7] stage46 aggressive"
bash run_stage46_aggressive.sh
echo "[6/7] stage47 tranche/lock"
bash run_stage47_tranche_lock.sh
echo "[7/7] stage48 aggressive refine"
bash run_stage48_aggressive_refine.sh
echo "[OK] joint research done | outputs: ~/Downloads/deepseek_single_file_latest.txt + ~/Downloads/chatgpt_bundle_latest.zip"
