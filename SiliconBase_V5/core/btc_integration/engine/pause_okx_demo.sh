#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$ROOT/.runtime/okx_demo_autopilot.pid"
REPORT_FILE="$HOME/Downloads/okx_demo_report_latest.txt"

local_ts() {
  TZ=Asia/Shanghai date '+%Y-%m-%d %H:%M:%S'
}

hard_kill_role() {
  local pattern="$1"
  local pids
  pids="$(pgrep -f -- "$pattern" 2>/dev/null | tr '\n' ' ' || true)"
  [ -n "${pids// /}" ] || return 0
  for pid in $pids; do
    kill -TERM "$pid" 2>/dev/null || true
  done
  sleep 1
  for pid in $pids; do
    if kill -0 "$pid" 2>/dev/null; then
      kill -KILL "$pid" 2>/dev/null || true
    fi
  done
}

if [ ! -f "$PID_FILE" ]; then
  hard_kill_role "tools.okx_demo_autopilot.*--role-tag mainline"
  echo "[UTC+8 $(local_ts)] OKX Demo 当前未运行。"
  echo "报告：$REPORT_FILE"
  exit 0
fi

PID="$(tr -d '[:space:]' < "$PID_FILE" || true)"
if [ -z "$PID" ]; then
  hard_kill_role "tools.okx_demo_autopilot.*--role-tag mainline"
  rm -f "$PID_FILE"
  echo "[UTC+8 $(local_ts)] OKX Demo 当前未运行。"
  echo "报告：$REPORT_FILE"
  exit 0
fi

if kill -0 "$PID" 2>/dev/null; then
  kill -TERM "$PID" 2>/dev/null || true
  for _ in $(seq 1 40); do
    if ! kill -0 "$PID" 2>/dev/null; then
      break
    fi
    sleep 0.25
  done
  if kill -0 "$PID" 2>/dev/null; then
    kill -KILL "$PID" 2>/dev/null || true
  fi
  echo "[UTC+8 $(local_ts)] 已暂停。"
  echo "开始命令：bash start_okx_demo.sh"
  echo "暂停命令：bash pause_okx_demo.sh"
  echo "报告：$REPORT_FILE"
else
  echo "[UTC+8 $(local_ts)] OKX Demo 当前未运行。"
  echo "报告：$REPORT_FILE"
fi
hard_kill_role "tools.okx_demo_autopilot.*--role-tag mainline"
rm -f "$PID_FILE"
