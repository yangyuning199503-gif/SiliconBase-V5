#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "缺少 .venv/bin/python，请先恢复系统目录后再运行。"
  exit 2
fi
"$PY" -m py_compile \
  "$ROOT/tools/okx_demo_autopilot.py" \
  "$ROOT/tools/okx_demo_shadow_exec.py" \
  "$ROOT/tools/stage179_mainline_runtime_readiness_guard.py"
set +e
bash "$ROOT/pause_okx_demo.sh" >/dev/null 2>&1
set -e
"$PY" -m tools.stage179_mainline_runtime_readiness_guard --project-dir .
set +e
bash "$ROOT/start_okx_demo.sh" >/dev/null 2>&1
set -e
ZIP="$HOME/Downloads/stage179_mainline_runtime_readiness_latest.zip"
[ -f "$ZIP" ] && echo "结果包：$ZIP"
