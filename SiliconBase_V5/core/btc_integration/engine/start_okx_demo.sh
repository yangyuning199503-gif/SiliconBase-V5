#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
RUNTIME_DIR="$ROOT/.runtime"
PID_FILE="$RUNTIME_DIR/okx_demo_autopilot.pid"
REPORT_FILE="$HOME/Downloads/okx_demo_report_latest.txt"
LOG_FILE="$RUNTIME_DIR/okx_demo_autopilot.log"
PY="$ROOT/.venv/bin/python"

bootstrap_venv() {
  echo "Creating virtualenv .venv ..."
  rm -rf "$ROOT/.venv"
  python3 -m venv "$ROOT/.venv"
  PY="$ROOT/.venv/bin/python"
  "$PY" -m pip install --upgrade pip >/dev/null
  "$PY" -m pip install -r "$ROOT/requirements.txt" >/dev/null
  touch "$ROOT/.venv/.deps_installed"
}

if [ ! -x "$PY" ] || ! "$PY" -c 'import sys; print(sys.executable)' >/dev/null 2>&1; then
  bootstrap_venv
elif [ ! -f "$ROOT/.venv/.deps_installed" ] || [ "$ROOT/requirements.txt" -nt "$ROOT/.venv/.deps_installed" ]; then
  "$PY" -m pip install -r "$ROOT/requirements.txt" >/dev/null
  touch "$ROOT/.venv/.deps_installed"
fi

"$PY" -m py_compile \
  "$ROOT/src/live/okx_shadow.py" \
  "$ROOT/tools/okx_demo_common.py" \
  "$ROOT/tools/okx_demo_probe.py" \
  "$ROOT/tools/okx_demo_smoke_submit.py" \
  "$ROOT/tools/okx_demo_shadow_exec.py" \
  "$ROOT/tools/okx_demo_runner.py" \
  "$ROOT/tools/okx_demo_autopilot.py" \
  "$ROOT/tools/message_combo_ab_backtest.py"

mkdir -p "$RUNTIME_DIR" "$ROOT/reports" "$HOME/Downloads"
touch "$LOG_FILE"

local_ts() {
  TZ=Asia/Shanghai date '+%Y-%m-%d %H:%M:%S'
}

is_running() {
  [ -f "$PID_FILE" ] || return 1
  local pid
  pid="$(tr -d '[:space:]' < "$PID_FILE" || true)"
  [ -n "$pid" ] || return 1
  kill -0 "$pid" 2>/dev/null
}

report_is_boot_placeholder() {
  [ -f "$REPORT_FILE" ] || return 0
  if grep -q '当前状态: 启动中' "$REPORT_FILE" 2>/dev/null; then
    return 0
  fi
  if grep -q '状态原因: waiting_for_autopilot_process' "$REPORT_FILE" 2>/dev/null; then
    return 0
  fi
  return 1
}

write_boot_report() {
  local reason="$1"
  cat > "$REPORT_FILE" <<EOF2
OKX Demo 自动报告（此文件每轮自动覆盖）
时区: UTC+8
生成时间(UTC+8): $(local_ts)
生成时间(UTC): $(date -u '+%Y-%m-%d %H:%M:%S')

【概览】
- 当前状态: 启动中
- 状态原因: ${reason}
- 项目目录: $ROOT
- 进程 PID: -
- 当前版本: 启动中
- 下一轮执行(UTC+8): -
- 最近已完成 15m K 线开盘(UTC+8): -
- 最近策略信号时间(UTC+8): -
- 最近影子执行成功: 否
- 最近影子执行原因: ${reason}

EOF2
}

write_fail_report() {
  local reason="$1"
  local tail_txt
  tail_txt="$(tail -n 120 "$LOG_FILE" 2>/dev/null || true)"
  cat > "$REPORT_FILE" <<EOF2
OKX Demo 自动报告（此文件每轮自动覆盖）
时区: UTC+8
生成时间(UTC+8): $(local_ts)
生成时间(UTC): $(date -u '+%Y-%m-%d %H:%M:%S')

【概览】
- 当前状态: 启动失败
- 状态原因: ${reason}
- 项目目录: $ROOT
- 进程 PID: -
- 当前版本: 启动失败
- 下一轮执行(UTC+8): -
- 最近已完成 15m K 线开盘(UTC+8): -
- 最近策略信号时间(UTC+8): -
- 最近影子执行成功: 否
- 最近影子执行原因: ${reason}

【最近日志】
${tail_txt}
EOF2
}

ensure_mainline_raw_ready() {
  "$PY" -m tools.repair_raw_from_snapshots --project-dir . --config config.yml >/dev/null 2>&1 || true
  if ! "$PY" -m tools.raw_data_guard --project-dir . --config config.yml >>"$LOG_FILE" 2>&1; then
    write_fail_report "raw_data_guard_failed"
    echo "[UTC+8 $(local_ts)] 主线 raw guard 未通过，已阻止启动。"
    echo "日志：$LOG_FILE"
    echo "报告：$REPORT_FILE"
    exit 1
  fi
}

ROLE_TAG="mainline"

start_background_now() {
  nohup "$PY" -u -m tools.okx_demo_autopilot --project-dir . --confirm-demo --role-tag "$ROLE_TAG" >>"$LOG_FILE" 2>&1 &
}

wait_for_pid() {
  local attempts="${1:-80}"
  local sleep_s="${2:-0.25}"
  local i
  for i in $(seq 1 "$attempts"); do
    if is_running; then
      return 0
    fi
    sleep "$sleep_s"
  done
  return 1
}

wait_for_report_ready() {
  local attempts="${1:-80}"
  local sleep_s="${2:-0.25}"
  local i
  for i in $(seq 1 "$attempts"); do
    if ! report_is_boot_placeholder; then
      return 0
    fi
    if ! is_running; then
      return 1
    fi
    sleep "$sleep_s"
  done
  return 2
}

already_running="0"
if is_running; then
  already_running="1"
fi

if [ "$already_running" != "1" ]; then
  ensure_mainline_raw_ready
  rm -f "$PID_FILE"
  write_boot_report "waiting_for_autopilot_process"
  start_background_now
  if ! wait_for_pid 80 0.25; then
    write_fail_report "autopilot_process_not_alive"
    echo "[UTC+8 $(local_ts)] OKX Demo 启动失败。"
    echo "日志：$LOG_FILE"
    echo "报告：$REPORT_FILE"
    exit 1
  fi
  set +e
  wait_for_report_ready 80 0.25
  report_rc=$?
  set -e
  if [ "$report_rc" = "1" ]; then
    write_fail_report "autopilot_process_exited_before_report_ready"
    echo "[UTC+8 $(local_ts)] OKX Demo 启动失败。"
    echo "日志：$LOG_FILE"
    echo "报告：$REPORT_FILE"
    exit 1
  fi
fi

RUN_CMD_FILE="$RUNTIME_DIR/run_okx_demo_autopilot.command"
cat > "$RUN_CMD_FILE" <<EOF2
#!/usr/bin/env bash
cd "$ROOT"
export PYTHONUNBUFFERED=1
exec "$PY" -u -m tools.okx_demo_autopilot --project-dir . --confirm-demo --role-tag "$ROLE_TAG"
EOF2
chmod +x "$RUN_CMD_FILE"

VIEW_CMD_FILE="$RUNTIME_DIR/start_okx_demo_autopilot.command"
cat > "$VIEW_CMD_FILE" <<EOF2
#!/usr/bin/env bash
set +e
ROOT="$ROOT"
PID_FILE="$PID_FILE"
REPORT_FILE="$REPORT_FILE"
PY="$PY"
cd "$ROOT"
while true; do
  "$PY" "$ROOT/tools/demo_terminal_compact.py"     --report-file "$REPORT_FILE"     --title "【主线 LIVE 极简】BTC/BNB | okxm"     --mode mainline     --pid-file "$PID_FILE"
  sleep 5
done
EOF2
chmod +x "$VIEW_CMD_FILE"

started_view="0"
if [ "$(uname -s 2>/dev/null || true)" = "Darwin" ] && command -v open >/dev/null 2>&1; then
  if open -a Terminal "$VIEW_CMD_FILE" >/dev/null 2>&1 || open "$VIEW_CMD_FILE" >/dev/null 2>&1; then
    started_view="1"
  fi
fi

if [ "$already_running" = "1" ]; then
  echo "[UTC+8 $(local_ts)] OKX Demo 已在运行。"
else
  pid_now="$(tr -d '[:space:]' < "$PID_FILE" 2>/dev/null || true)"
  echo "[UTC+8 $(local_ts)] OKX Demo 已启动（后台 PID=${pid_now:-unknown}）。"
fi
if [ "$started_view" = "1" ]; then
  echo "[UTC+8 $(local_ts)] 监控窗口已打开。"
else
  echo "[UTC+8 $(local_ts)] 未自动打开监控窗口，但后台已启动。"
fi
if report_is_boot_placeholder; then
  echo "[UTC+8 $(local_ts)] 报告仍在启动占位态；run_send_files.sh 会在打包前自动等待刷新。"
fi

echo "开始命令：bash start_okx_demo.sh"
echo "暂停命令：bash pause_okx_demo.sh"
echo "报告：$REPORT_FILE"
echo "日志：$LOG_FILE"
