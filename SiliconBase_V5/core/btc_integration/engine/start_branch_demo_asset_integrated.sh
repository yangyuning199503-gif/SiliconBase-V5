#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
WORK_ROOT="$ROOT/.branch_shortwave_demo"
WORKSPACE="$WORK_ROOT/workspace"
CFG_PATH="$ROOT/config_shortwave_asset_integrated.yml"
SHADOW_PATH="$ROOT/shadow_shortwave_asset_integrated.yml"
PID_FILE="$WORKSPACE/.runtime/okx_demo_autopilot.pid"
LOG_FILE="$WORKSPACE/.runtime/okx_demo_autopilot.log"
REPORT_FILE="$HOME/Downloads/branch_demo_report_latest.txt"
PY="$ROOT/.venv/bin/python"
MODE="${1:-start}"
BRANCH_LABEL="BTC+ETH 第二分支预览"
ORDER_PREFIX="okxb"

mkdir -p "$ROOT/.runtime" "$WORKSPACE/.runtime" "$HOME/Downloads"

auto_ts() {
  TZ=Asia/Shanghai date '+%Y-%m-%d %H:%M:%S'
}

is_running() {
  [ -f "$PID_FILE" ] || return 1
  local pid
  pid="$(tr -d '[:space:]' < "$PID_FILE" 2>/dev/null || true)"
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

build_view_cmd_file() {
  VIEW_CMD_FILE="$ROOT/.runtime/start_asset_integrated_branch_monitor.command"
  cat > "$VIEW_CMD_FILE" <<EOF2
#!/usr/bin/env bash
set +e
printf '\033]0;第二分支(BTC+ETH) OKX Demo 监控\007'
WORKSPACE="$WORKSPACE"
PID_FILE="$PID_FILE"
REPORT_FILE="$REPORT_FILE"
LOG_FILE="$LOG_FILE"
cd "\$WORKSPACE" 2>/dev/null || cd "$ROOT"
mkdir -p "\$(dirname "\$LOG_FILE")"
touch "\$LOG_FILE"
local_ts() { TZ=Asia/Shanghai date '+%Y-%m-%d %H:%M:%S'; }
is_alive() {
  [ -f "\$PID_FILE" ] || return 1
  local pid
  pid="\$(tr -d '[:space:]' < "\$PID_FILE" 2>/dev/null || true)"
  [ -n "\$pid" ] || return 1
  kill -0 "\$pid" 2>/dev/null
}
render_report_for_monitor() {
  local report_path="\$1"
  awk '
    /^【最近错误\/日志尾部】$/ { print; print "(终端监控已隐藏详细错误；请直接打开报告文件查看)"; exit }
    /^【最近日志】$/ { print; print "(终端监控已隐藏详细日志；请直接打开报告文件查看)"; exit }
    { print }
  ' "\$report_path"
}
render() {
  clear
  printf '\033]0;第二分支(BTC+ETH) OKX Demo 监控\007'
  echo "第二分支(BTC+ETH) OKX Demo 实时监控  时间(UTC+8): \$(local_ts)"
  echo "----------------------------------------"
  if is_alive; then
    echo "后台进程: 运行中"
  else
    echo "后台进程: 未运行"
  fi
  echo
  if [ -f "\$REPORT_FILE" ]; then
    render_report_for_monitor "\$REPORT_FILE"
  else
    echo "报告文件尚未生成。"
    echo "详细错误仅写入报告文件和日志文件，不在终端展开。"
    echo "报告：\$REPORT_FILE"
    echo "日志：\$LOG_FILE"
  fi
}
while true; do
  render
  sleep 5
done
EOF2
  chmod +x "$VIEW_CMD_FILE"
}

open_terminal_monitor() {
  local cmd_file="$1"
  if [ "$(uname -s 2>/dev/null || true)" = "Darwin" ]; then
    if command -v osascript >/dev/null 2>&1; then
      local cmd_escaped="$cmd_file"
      cmd_escaped="${cmd_escaped//\\/\\\\}"
      cmd_escaped="${cmd_escaped//\"/\\\"}"
      if osascript >/dev/null 2>&1 <<EOF2
 tell application "Terminal"
   activate
   do script "bash \"$cmd_escaped\""
 end tell
EOF2
      then
        return 0
      fi
    fi
    if command -v open >/dev/null 2>&1; then
      if open -a Terminal "$cmd_file" >/dev/null 2>&1 || open "$cmd_file" >/dev/null 2>&1; then
        return 0
      fi
    fi
  fi
  return 1
}

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

if [ ! -f "$CFG_PATH" ] || [ ! -f "$SHADOW_PATH" ]; then
  echo "缺少资产一体分支配置："
  echo "- $CFG_PATH"
  echo "- $SHADOW_PATH"
  exit 2
fi

if [ "$MODE" = "--restart" ] || [ "$MODE" = "restart" ]; then
  bash "$ROOT/pause_branch_demo.sh" || true
  sleep 1
fi

if is_running; then
  build_view_cmd_file
  started_view="0"
  if open_terminal_monitor "$VIEW_CMD_FILE"; then
    started_view="1"
  fi
  echo "[UTC+8 $(auto_ts)] 分支 Demo 已在运行。"
  if [ "$started_view" = "1" ]; then
    echo "[UTC+8 $(auto_ts)] 分支监控终端已打开。"
  else
    echo "[UTC+8 $(auto_ts)] 未自动打开分支监控终端，但后台已启动。"
  fi
  echo "报告：$REPORT_FILE"
  echo "日志：$LOG_FILE"
  exit 0
fi

mkdir -p "$WORKSPACE" "$WORKSPACE/reports" "$WORKSPACE/.runtime"
ln -sfn "$ROOT/src" "$WORKSPACE/src"
ln -sfn "$ROOT/tools" "$WORKSPACE/tools"
ln -sfn "$ROOT/data" "$WORKSPACE/data"
ln -sfn "$ROOT/requirements.txt" "$WORKSPACE/requirements.txt"
ln -sfn "$ROOT/.venv" "$WORKSPACE/.venv"
cp -f "$CFG_PATH" "$WORKSPACE/config.yml"

python3 - <<PY2
from pathlib import Path
import yaml
workspace = Path(r"$WORKSPACE")
shadow_path = Path(r"$SHADOW_PATH")
out_path = workspace / "shadow.yml"
data = yaml.safe_load(shadow_path.read_text(encoding="utf-8")) or {}
shadow = data.get("shadow", data) if isinstance(data, dict) else {}
if not isinstance(shadow, dict):
    shadow = {}
autopilot = shadow.get("autopilot") if isinstance(shadow.get("autopilot"), dict) else {}
autopilot["public_report_txt"] = str(Path.home() / "Downloads" / "branch_demo_report_latest.txt")
shadow["autopilot"] = autopilot
execution_step = shadow.get("execution_step") if isinstance(shadow.get("execution_step"), dict) else {}
execution_step["clord_prefix"] = "okxb"
shadow["execution_step"] = execution_step
if isinstance(data, dict) and "shadow" in data:
    data["shadow"] = shadow
else:
    data = shadow
out_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
(workspace / "BRANCH_DEMO_README.txt").write_text(
    "asset integrated branch demo workspace\n"
    "- shared api env: ~/.okx_demo_env\n"
    "- public report: ~/Downloads/branch_demo_report_latest.txt\n"
    "- order prefix: okxb\n"
    "- book: BTC+ETH integrated preview\n",
    encoding="utf-8",
)
PY2

"$PY" -m py_compile \
  "$ROOT/src/live/okx_shadow.py" \
  "$ROOT/tools/okx_demo_common.py" \
  "$ROOT/tools/okx_demo_probe.py" \
  "$ROOT/tools/okx_demo_smoke_submit.py" \
  "$ROOT/tools/okx_demo_shadow_exec.py" \
  "$ROOT/tools/okx_demo_runner.py" \
  "$ROOT/tools/okx_demo_autopilot.py" \
  "$ROOT/tools/message_combo_ab_backtest.py"

write_boot_report() {
  local reason="$1"
  cat > "$REPORT_FILE" <<EOF2
OKX Demo 自动报告（分支独立 Demo，自动覆盖）
时区: UTC+8
生成时间(UTC+8): $(auto_ts)
生成时间(UTC): $(date -u '+%Y-%m-%d %H:%M:%S')

【概览】
- 当前状态: 启动中
- 状态原因: ${reason}
- 项目目录: $WORKSPACE
- 进程 PID: -
- 当前版本: 启动中
- 订单前缀: $ORDER_PREFIX
- 下一轮执行(UTC+8): -
- 最近影子执行成功: 否
- 最近影子执行原因: ${reason}
EOF2
}

write_fail_report() {
  local reason="$1"
  local tail_txt
  tail_txt="$(tail -n 120 "$LOG_FILE" 2>/dev/null || true)"
  cat > "$REPORT_FILE" <<EOF2
OKX Demo 自动报告（分支独立 Demo，自动覆盖）
时区: UTC+8
生成时间(UTC+8): $(auto_ts)
生成时间(UTC): $(date -u '+%Y-%m-%d %H:%M:%S')

【概览】
- 当前状态: 启动失败
- 状态原因: ${reason}
- 项目目录: $WORKSPACE
- 进程 PID: -
- 当前版本: 启动失败
- 订单前缀: $ORDER_PREFIX
- 下一轮执行(UTC+8): -
- 最近影子执行成功: 否
- 最近影子执行原因: ${reason}

【最近日志】
${tail_txt}
EOF2
}

start_background_now() {
  (
    cd "$WORKSPACE"
    nohup "$PY" -u -m tools.okx_demo_autopilot --project-dir . --confirm-demo >>"$LOG_FILE" 2>&1 &
  )
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

rm -f "$PID_FILE"
write_boot_report "waiting_for_autopilot_process"
start_background_now
if ! wait_for_pid 80 0.25; then
  write_fail_report "autopilot_process_not_alive"
  echo "[UTC+8 $(auto_ts)] 分支 Demo 启动失败。"
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
  echo "[UTC+8 $(auto_ts)] 分支 Demo 启动失败。"
  echo "日志：$LOG_FILE"
  echo "报告：$REPORT_FILE"
  exit 1
fi

build_view_cmd_file
started_view="0"
if open_terminal_monitor "$VIEW_CMD_FILE"; then
  started_view="1"
fi

pid_now="$(tr -d '[:space:]' < "$PID_FILE" 2>/dev/null || true)"
echo "[UTC+8 $(auto_ts)] $BRANCH_LABEL 已启动（后台 PID=${pid_now:-unknown}）。"
if [ "$started_view" = "1" ]; then
  echo "[UTC+8 $(auto_ts)] 分支监控终端已打开。"
else
  echo "[UTC+8 $(auto_ts)] 未自动打开分支监控终端，但后台已启动。"
fi
echo "报告：$REPORT_FILE"
echo "日志：$LOG_FILE"
