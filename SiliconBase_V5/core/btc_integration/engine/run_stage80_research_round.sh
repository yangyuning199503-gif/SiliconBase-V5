#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
CANON="$HOME/btc_system_v1"
if [ "$ROOT" != "$CANON" ] && [ -d "$CANON" ]; then
  echo "[ERR] 请在 ~/btc_system_v1 运行。当前目录: $ROOT" >&2
  exit 1
fi
cd "$ROOT"

bash run_stage79_dual_window_monthlyized.sh
./.venv/bin/python -m tools.stage80_console_summary --project-dir .

echo ""
echo "[CHECK] bundle 内容："
unzip -l "$HOME/Downloads/chatgpt_bundle_latest.zip" | egrep 'stage77_mainline_dual_window_latest|stage78_branch_dual_window_latest|message_stack_backtest_latest|okx_demo_report_latest' || true

echo ""
echo "[OK] 请发这个：~/Downloads/chatgpt_bundle_latest.zip"
