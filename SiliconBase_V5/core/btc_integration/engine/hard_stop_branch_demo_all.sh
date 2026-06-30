#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
WORKSPACE="$ROOT/.branch_shortwave_demo/workspace"
PID_FILE="$WORKSPACE/.runtime/okx_demo_autopilot.pid"
LOG_PREFIX='[branch-hard-stop]'

echo "$LOG_PREFIX stopping old branch demo ..."

kill_pid_if_alive() {
  local pid="$1"
  [ -n "$pid" ] || return 0
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    sleep 1
    kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
  fi
}

if [ -f "$PID_FILE" ]; then
  pid="$(tr -d '[:space:]' < "$PID_FILE" 2>/dev/null || true)"
  kill_pid_if_alive "$pid"
fi

if command -v pgrep >/dev/null 2>&1; then
  while IFS= read -r line; do
    pid="$(printf '%s\n' "$line" | awk '{print $1}')"
    cmd="$(printf '%s\n' "$line" | cut -d' ' -f2-)"
    case "$cmd" in
      *".branch_shortwave_demo/workspace"*"tools.okx_demo_autopilot"*|*".branch_shortwave_demo/workspace"*"tools.okx_demo_runner"*|*".branch_shortwave_demo/workspace"*"tools.okx_demo_shadow_exec"*)
        kill_pid_if_alive "$pid"
        ;;
    esac
  done < <(pgrep -af "btc_system_v1.*(okx_demo_autopilot|okx_demo_runner|okx_demo_shadow_exec)" || true)
fi

rm -f "$PID_FILE"
rm -f "$WORKSPACE/.runtime/okx_demo_autopilot_state.json" "$WORKSPACE/.runtime/okx_demo_runner_status_latest.json" 2>/dev/null || true

echo "$LOG_PREFIX done."
