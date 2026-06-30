#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
WORK_ROOT="$ROOT/.branch_shortwave_demo"
WORKSPACE="$WORK_ROOT/workspace"
CAND_CFG="$ROOT/config_shortwave_candidate.yml"
CAND_SHADOW="$ROOT/shadow_shortwave_candidate.yml"
PID_FILE="$WORKSPACE/.runtime/okx_demo_autopilot.pid"
LOG_FILE="$WORKSPACE/.runtime/okx_demo_autopilot.log"
REPORT_FILE="$HOME/Downloads/branch_demo_report_latest.txt"
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

if [ ! -f "$CAND_CFG" ] || [ ! -f "$CAND_SHADOW" ]; then
  echo "缺少分支候选配置："
  echo "- $CAND_CFG"
  echo "- $CAND_SHADOW"
  exit 2
fi

mkdir -p "$WORKSPACE" "$WORKSPACE/reports" "$WORKSPACE/.runtime"
ln -sfn "$ROOT/src" "$WORKSPACE/src"
ln -sfn "$ROOT/tools" "$WORKSPACE/tools"
ln -sfn "$ROOT/data" "$WORKSPACE/data"
ln -sfn "$ROOT/requirements.txt" "$WORKSPACE/requirements.txt"
ln -sfn "$ROOT/.venv" "$WORKSPACE/.venv"
cp -f "$CAND_CFG" "$WORKSPACE/config.yml"

python3 - <<PY
from pathlib import Path
import yaml
workspace = Path(r"$WORKSPACE")
shadow_path = Path(r"$CAND_SHADOW")
out_path = workspace / "shadow.yml"
data = yaml.safe_load(shadow_path.read_text(encoding="utf-8")) or {}
shadow = data.get("shadow", data) if isinstance(data, dict) else {}
if not isinstance(shadow, dict):
    shadow = {}
autopilot = shadow.get("autopilot") if isinstance(shadow.get("autopilot"), dict) else {}
autopilot["public_report_txt"] = str(Path.home() / "Downloads" / "branch_demo_report_latest.txt")
shadow["autopilot"] = autopilot
if isinstance(data, dict) and "shadow" in data:
    data["shadow"] = shadow
else:
    data = shadow
out_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
(workspace / "BRANCH_DEMO_README.txt").write_text(
    "shortwave demo workspace\n"
    "- shared api env: ~/.okx_demo_env\n"
    "- public report: ~/Downloads/branch_demo_report_latest.txt\n"
    "- shared API, separate runtime/log/pid/report/order-prefix\n",
    encoding="utf-8",
)
PY

"$PY" -m py_compile \
  "$ROOT/src/live/okx_shadow.py" \
  "$ROOT/tools/okx_demo_common.py" \
  "$ROOT/tools/okx_demo_probe.py" \
  "$ROOT/tools/okx_demo_smoke_submit.py" \
  "$ROOT/tools/okx_demo_shadow_exec.py" \
  "$ROOT/tools/okx_demo_runner.py" \
  "$ROOT/tools/okx_demo_autopilot.py" \
  "$ROOT/tools/message_combo_ab_backtest.py"

local_ts() {
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

write_boot_report() {
  local reason="$1"
  cat > "$REPORT_FILE" <<EOF2
OKX Demo 自动报告（分支独立 Demo，自动覆盖）
时区: UTC+8
生成时间(UTC+8): $(local_ts)
生成时间(UTC): $(date -u '+%Y-%m-%d %H:%M:%S')

【概览】
- 当前状态: 启动中
- 状态原因: ${reason}
- 项目目录: $WORKSPACE
- 进程 PID: -
- 当前版本: 启动中
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
生成时间(UTC+8): $(local_ts)
生成时间(UTC): $(date -u '+%Y-%m-%d %H:%M:%S')

【概览】
- 当前状态: 启动失败
- 状态原因: ${reason}
- 项目目录: $WORKSPACE
- 进程 PID: -
- 当前版本: 启动失败
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

already_running="0"
if is_running; then
  already_running="1"
fi

if [ "$already_running" != "1" ]; then
  rm -f "$PID_FILE"
  write_boot_report "waiting_for_autopilot_process"
  start_background_now
  if ! wait_for_pid 80 0.25; then
    write_fail_report "autopilot_process_not_alive"
    echo "[UTC+8 $(local_ts)] 分支 Demo 启动失败。"
    echo "日志：$LOG_FILE"
    exit 1
  fi
  set +e
  wait_for_report_ready 80 0.25
  report_rc=$?
  set -e
  if [ "$report_rc" = "1" ]; then
    write_fail_report "autopilot_process_exited_before_report_ready"
    echo "[UTC+8 $(local_ts)] 分支 Demo 启动失败。"
    echo "日志：$LOG_FILE"
    exit 1
  fi
fi

echo "[OK] branch demo started from existing candidate config"
echo "workspace: $WORKSPACE"
echo "report: $REPORT_FILE"
