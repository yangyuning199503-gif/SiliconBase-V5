#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "[1/4] local info sources"
bash run_local_info_sources_test.sh

echo "[2/4] message stack backtest"
COINGLASS_HISTORY_REFRESH="${COINGLASS_HISTORY_REFRESH:-1}" bash run_message_stack_backtest.sh

echo "[3/4] stage54 full angle"
bash run_stage54_full_angle.sh

echo "[4/4] stage55 broad dual track"
bash run_stage55_broad_dual_track.sh

echo "[OK] broad both-sides research done"
echo "bundle: ~/Downloads/chatgpt_bundle_latest.zip"
echo "deepseek: ~/Downloads/deepseek_single_file_latest.txt"
echo "note: do NOT run bash run_send_files.sh after this round"
