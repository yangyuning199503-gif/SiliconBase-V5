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
  "$ROOT/tools/repair_raw_from_snapshots.py" \
  "$ROOT/tools/stage180_btc_raw_floor_and_snapshot_guard.py" \
  "$ROOT/tools/okx_demo_shadow_exec.py" \
  "$ROOT/tools/okx_demo_autopilot.py"

set +e
bash "$ROOT/pause_okx_demo.sh" >/dev/null 2>&1
bash "$ROOT/pause_branch_demo.sh" >/dev/null 2>&1
set -e

"$PY" -m tools.stage180_btc_raw_floor_and_snapshot_guard --project-dir .

SUMMARY_JSON="$HOME/Downloads/stage180_btc_raw_floor_and_snapshot_guard_latest.json"
READY="0"
if [ -f "$SUMMARY_JSON" ]; then
  READY="$("$PY" - <<'PY2'
import json, os, sys
p = os.path.expanduser("~/Downloads/stage180_btc_raw_floor_and_snapshot_guard_latest.json")
try:
    data = json.load(open(p, "r", encoding="utf-8"))
    print("1" if bool(((data or {}).get("overall") or {}).get("system_ready_for_live")) else "0")
except Exception:
    print("0")
PY2
)"
fi

if [ "$READY" = "1" ]; then
  bash "$ROOT/start_okx_demo.sh" >/dev/null 2>&1 || true
  bash "$ROOT/start_branch_demo.sh" >/dev/null 2>&1 || true
fi

ZIP="$HOME/Downloads/stage180_btc_raw_floor_and_snapshot_guard_latest.zip"
[ -f "$ZIP" ] && echo "结果包：$ZIP"
if [ "$READY" = "1" ]; then
  echo "system_ready_for_live=1"
else
  echo "system_ready_for_live=0"
fi
