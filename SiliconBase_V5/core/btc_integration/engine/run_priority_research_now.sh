#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
CANON="$HOME/btc_system_v1"
if [ "$ROOT" != "$CANON" ] && [ -d "$CANON" ]; then
  echo "[ERR] 请在 ~/btc_system_v1 运行。当前目录: $ROOT" >&2
  exit 1
fi
cd "$ROOT"

PY="./.venv/bin/python"
bootstrap_venv() {
  echo "Creating virtualenv .venv ..."
  rm -rf .venv
  python3 -m venv .venv
  PY="./.venv/bin/python"
  "$PY" -m pip install --upgrade pip >/dev/null
  "$PY" -m pip install -r requirements.txt >/dev/null
  touch .venv/.deps_installed
}
if [ ! -x "$PY" ] || ! "$PY" -c 'import sys; print(sys.executable)' >/dev/null 2>&1; then
  bootstrap_venv
elif [ ! -f .venv/.deps_installed ] || [ requirements.txt -nt .venv/.deps_installed ]; then
  "$PY" -m pip install -r requirements.txt >/dev/null
  touch .venv/.deps_installed
fi

"$PY" -m tools.align_backtest_end --project-dir . --config config.yml --config config_shortwave_candidate.yml

echo "[1/3] 主线回测"
bash run.sh

echo "[2/3] 主线消息面联动回测"
bash run_message_stack_backtest.sh

echo "[3/3] WF + 融合 + bundle"
bash run_gapfill_wf_fusion_now.sh

echo ""
echo "[OK] 上传这个：~/Downloads/chatgpt_bundle_latest.zip"
echo "[RAW] 主线双窗口：~/btc_system_v1/reports/research_raw/stage77_mainline_dual_window_latest.txt"
echo "[RAW] 主线WF：~/btc_system_v1/reports/research_raw/stage81_mainline_walkforward_latest.txt"
echo "[RAW] 分支WF：~/btc_system_v1/reports/research_raw/stage82_branch_walkforward_latest.txt"
echo "[RAW] 主线融合：~/btc_system_v1/reports/research_raw/stage88_mainline_fusion_walkforward_latest.txt"
