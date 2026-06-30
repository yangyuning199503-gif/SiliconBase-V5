#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if bash run_btc_dual_branch_lab.sh; then
  :
else
  echo '[BTC batch] btc_dual_branch_lab skipped/failed -> continue message stack backtest' >&2
fi
bash run_message_stack_backtest.sh
