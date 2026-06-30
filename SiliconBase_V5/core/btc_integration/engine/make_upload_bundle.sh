#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
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

mkdir -p reports "$HOME/Downloads"
# 分支研究先跑 fast，再跑当前主线 + 消息面联动；两条线一起进 bundle
if [ -f "run_branch_fast_research.sh" ]; then
  echo "[info] running branch fast research (with mainline bundle)"
  bash run_branch_fast_research.sh quick
fi

echo "[info] running current demo strategy + message stack backtest"
bash run_message_stack_backtest.sh

echo "[info] refreshing internal research summaries"
"$PY" -m tools.finalize_research_outputs --project-dir . --mode fast --cleanup-downloads

echo "[info] building internal support bundle"
"$PY" -m tools.make_support_bundle .

echo "[info] generating public 3-file set"
bash run_send_files.sh >/dev/null

echo ""
echo "===== 中文结果 ====="
if [ -f "reports/research_report_latest.txt" ]; then
  cat "reports/research_report_latest.txt"
else
  echo "未生成 reports/research_report_latest.txt"
fi
echo "===================="
echo "PUBLIC: $HOME/Downloads/okx_demo_report_latest.txt"
echo "PUBLIC: $HOME/Downloads/deepseek_single_file_latest.txt"
echo "PUBLIC: $HOME/Downloads/chatgpt_bundle_latest.zip"
ls -la "$HOME/Downloads/okx_demo_report_latest.txt" "$HOME/Downloads/deepseek_single_file_latest.txt" "$HOME/Downloads/chatgpt_bundle_latest.zip" 2>/dev/null || true
