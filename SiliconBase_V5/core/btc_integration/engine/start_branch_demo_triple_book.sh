#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
WORK_ROOT="$ROOT/.branch_shortwave_demo"
WORKSPACE="$WORK_ROOT/workspace"
CFG_PATH_STAGE133="$ROOT/config_shortwave_triple_book_stage133.yml"
SHADOW_PATH_STAGE133="$ROOT/shadow_shortwave_triple_book_stage133.yml"
CFG_PATH_STAGE113="$ROOT/config_shortwave_triple_book_stage113.yml"
SHADOW_PATH_STAGE113="$ROOT/shadow_shortwave_triple_book_stage113.yml"
CFG_PATH_PREVIEW="$ROOT/config_shortwave_triple_book_preview.yml"
SHADOW_PATH_PREVIEW="$ROOT/shadow_shortwave_triple_book_preview.yml"
CFG_PATH="$CFG_PATH_PREVIEW"
SHADOW_PATH="$SHADOW_PATH_PREVIEW"
if [ -f "$CFG_PATH_STAGE133" ] && [ -f "$SHADOW_PATH_STAGE133" ]; then
  CFG_PATH="$CFG_PATH_STAGE133"
  SHADOW_PATH="$SHADOW_PATH_STAGE133"
elif [ -f "$CFG_PATH_STAGE113" ] && [ -f "$SHADOW_PATH_STAGE113" ]; then
  CFG_PATH="$CFG_PATH_STAGE113"
  SHADOW_PATH="$SHADOW_PATH_STAGE113"
fi
PID_FILE="$WORKSPACE/.runtime/okx_demo_autopilot.pid"
LOG_FILE="$WORKSPACE/.runtime/okx_demo_autopilot.log"
REPORT_FILE="$HOME/Downloads/branch_demo_report_latest.txt"
PY="$ROOT/.venv/bin/python"
MODE="${1:-start}"
ORDER_PREFIX="okxb"
SHARED_ACCOUNT_FORCE_FLAT_SYMBOLS="btc,sol"
SHARED_ACCOUNT_HIDE_POS_SYMBOLS="btc"
SHARED_ACCOUNT_DISABLE_SEED_SYMBOLS="btc,sol"
ROLE_TAG="branch_triple_book"

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
  VIEW_CMD_FILE="$ROOT/.runtime/start_triple_book_branch_monitor.command"
  cat > "$VIEW_CMD_FILE" <<EOF2
#!/usr/bin/env bash
set +e
WORKSPACE="$WORKSPACE"
PID_FILE="$PID_FILE"
REPORT_FILE="$REPORT_FILE"
PY="$PY"
cd "$WORKSPACE" 2>/dev/null || cd "$ROOT"
while true; do
  "$PY" "$ROOT/tools/demo_terminal_compact.py"     --report-file "$REPORT_FILE"     --title "【分支 LIVE 极简】BTC/ETH/SOL | okxb"     --mode branch     --pid-file "$PID_FILE"
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
  echo "缺少三标的运行配置："
  echo "- $CFG_PATH"
  echo "- $SHADOW_PATH"
  echo "（会优先使用 stage133，其次 stage113，再回退 preview）"
  exit 2
fi

if [ "$MODE" = "--restart" ] || [ "$MODE" = "restart" ]; then
  bash "$ROOT/pause_branch_demo.sh" || true
  sleep 1
  rm -f "$WORKSPACE/config.yml" "$WORKSPACE/shadow.yml"
  rm -f "$WORKSPACE/.runtime/okx_demo_autopilot.pid" \
        "$WORKSPACE/.runtime/okx_demo_autopilot_state.json" \
        "$WORKSPACE/.runtime/okx_demo_shadow_exec_latest.json" \
        "$WORKSPACE/.runtime/okx_demo_shadow_exec_latest.jsonl" \
        "$WORKSPACE/.runtime/okx_demo_shadow_exec_latest.txt"
  rm -f "$REPORT_FILE"
fi

if is_running; then
  build_view_cmd_file
  started_view="0"
  if open_terminal_monitor "$VIEW_CMD_FILE"; then
    started_view="1"
  fi
  echo "[UTC+8 $(auto_ts)] 第二分支三标的 Demo 已在运行。"
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
    "triple book branch demo workspace\n"
    "- shared api env: ~/.okx_demo_env\n"
    "- public report: ~/Downloads/branch_demo_report_latest.txt\n"
    "- order prefix: okxb\n"
    "- book: BTC+ETH+SOL preview (SOL research_only_on_demo)\n"
    "- shared_account_overlap_guard: btc stays research_only_on_demo while mainline also uses BTC\n",
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

ensure_branch_raw_ready() {
  mkdir -p "$(dirname "$LOG_FILE")"
  touch "$LOG_FILE"
  "$PY" -m tools.repair_raw_from_snapshots --project-dir "$ROOT" --config "$CFG_PATH" >/dev/null 2>&1 || true
  if ! "$PY" -m tools.raw_data_guard --project-dir "$ROOT" --config "$CFG_PATH" >>"$LOG_FILE" 2>&1; then
    write_fail_report "branch_raw_data_guard_failed"
    echo "[UTC+8 $(auto_ts)] 分支 raw guard 未通过，已阻止启动。"
    echo "日志：$LOG_FILE"
    echo "报告：$REPORT_FILE"
    exit 1
  fi
}

start_background_now() {
  (
    cd "$WORKSPACE"
    export OKX_FORCE_FLAT_SYMBOLS="$SHARED_ACCOUNT_FORCE_FLAT_SYMBOLS"
    export OKX_HIDE_SHARED_ACCOUNT_POSITIONS_SYMBOLS="$SHARED_ACCOUNT_HIDE_POS_SYMBOLS"
    export OKX_DISABLE_ACCOUNT_POSITION_SEED_SYMBOLS="$SHARED_ACCOUNT_DISABLE_SEED_SYMBOLS"
    nohup "$PY" -u -m tools.okx_demo_autopilot --project-dir . --confirm-demo --role-tag "$ROLE_TAG" >>"$LOG_FILE" 2>&1 &
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

ensure_branch_raw_ready
rm -f "$PID_FILE"
write_boot_report "waiting_for_autopilot_process"
start_background_now
if ! wait_for_pid 80 0.25; then
  write_fail_report "autopilot_process_not_alive"
  echo "[UTC+8 $(auto_ts)] 第二分支三标的 Demo 启动失败。"
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
  echo "[UTC+8 $(auto_ts)] 第二分支三标的 Demo 启动失败。"
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
echo "[UTC+8 $(auto_ts)] 第二分支三标的 Demo 已启动（后台 PID=${pid_now:-unknown}）。"
if [ "$started_view" = "1" ]; then
  echo "[UTC+8 $(auto_ts)] 分支监控终端已打开。"
else
  echo "[UTC+8 $(auto_ts)] 未自动打开分支监控终端，但后台已启动。"
fi
if report_is_boot_placeholder; then
  echo "[UTC+8 $(auto_ts)] 分支报告仍在启动占位态。"
fi

echo "开始命令：bash start_branch_demo_triple_book.sh [--restart]"
echo "暂停命令：bash pause_branch_demo.sh"
echo "报告：$REPORT_FILE"
echo "日志：$LOG_FILE"
