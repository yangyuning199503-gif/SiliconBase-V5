#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "缺少 .venv，请先在项目根目录执行 bash run_precheck.sh"
  exit 2
fi
"$PY" -m py_compile \
  "$ROOT/tools/okx_demo_shadow_exec.py" \
  "$ROOT/tools/okx_demo_autopilot.py"

echo "[stage154] py_compile: OK"
echo "[stage154] 共享账户重叠标的保护: BTC"
echo "[stage154] 动作: 重启分支 demo，使 BTC 继续 research_only_on_demo，且不再把主线 BTC 持仓映射成分支持仓"

bash "$ROOT/pause_branch_demo.sh" || true
sleep 1
bash "$ROOT/start_branch_demo.sh" --restart
