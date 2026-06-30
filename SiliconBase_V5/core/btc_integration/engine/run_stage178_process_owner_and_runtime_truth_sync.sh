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
  "$ROOT/tools/stage178_process_owner_and_runtime_truth_sync.py"
set +e
"$PY" -m tools.stage178_process_owner_and_runtime_truth_sync --project-dir .
rc=$?
set -e
ZIP="$HOME/Downloads/stage178_process_owner_and_runtime_truth_sync_latest.zip"
if [ -f "$ZIP" ]; then
  echo "结果包：$ZIP"
fi
exit $rc
