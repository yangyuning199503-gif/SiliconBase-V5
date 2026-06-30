#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
WORKSPACE="$ROOT/.mainline_shadow_demo/workspace"
PID_FILE="$WORKSPACE/.runtime/okx_demo_autopilot.pid"
if [ ! -f "$PID_FILE" ]; then
  echo "[OK] mainline shadow demo not running"
  exit 0
fi
PID="$(tr -d '[:space:]' < "$PID_FILE" 2>/dev/null || true)"
if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
  kill "$PID" 2>/dev/null || true
  sleep 1
fi
rm -f "$PID_FILE"
echo "[OK] mainline shadow demo stopped"
