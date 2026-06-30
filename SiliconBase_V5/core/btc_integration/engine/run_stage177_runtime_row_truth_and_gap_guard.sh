#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "缺少 .venv/bin/python，请先恢复系统目录后再运行。"
  exit 2
fi
"$PY" -m py_compile "$ROOT/tools/stage177_runtime_row_truth_and_gap_guard.py"
set +e
"$PY" -m tools.stage177_runtime_row_truth_and_gap_guard --project-dir .
rc=$?
set -e
ZIP="$HOME/Downloads/stage177_runtime_row_truth_and_gap_guard_latest.zip"
if [ -f "$ZIP" ]; then
  echo "结果包：$ZIP"
fi
exit $rc
