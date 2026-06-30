#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
CANON="$HOME/btc_system_v1"
if [ "$ROOT" != "$CANON" ] && [ -d "$CANON" ]; then
  echo "[ERR] 请在 ~/btc_system_v1 运行。当前目录: $ROOT" >&2
  exit 1
fi
cd "$ROOT"

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

BRANCH_CFG="$ROOT/config_shortwave_candidate.yml"
BRANCH_SHADOW="$ROOT/shadow_shortwave_candidate.yml"
BRANCH_WORK_ROOT="$ROOT/.branch_shortwave_demo"
BRANCH_WORK="$BRANCH_WORK_ROOT/workspace"
BRANCH_PID="$BRANCH_WORK/.runtime/okx_demo_autopilot.pid"
BRANCH_LOG="$BRANCH_WORK/.runtime/okx_demo_autopilot.log"
BRANCH_REPORT="$HOME/Downloads/branch_demo_report_latest.txt"
BRANCH_VIEW_CMD="$ROOT/.runtime/start_branch_stage115_monitor.command"

SHADOW_CFG="$ROOT/config_mainline_shadow_candidate.yml"
SHADOW_SHADOW="$ROOT/shadow_mainline_shadow_candidate.yml"
SHADOW_WORK_ROOT="$ROOT/.mainline_shadow_demo"
SHADOW_WORK="$SHADOW_WORK_ROOT/workspace"
SHADOW_PID="$SHADOW_WORK/.runtime/okx_demo_autopilot.pid"
SHADOW_LOG="$SHADOW_WORK/.runtime/okx_demo_autopilot.log"
SHADOW_REPORT="$ROOT/reports/research_raw/mainline_shadow_demo_report_latest.txt"

LIVE_REPORT="$HOME/Downloads/okx_demo_report_latest.txt"
EXPORT_ZIP="$HOME/Downloads/stage115_runtime_sync_latest.zip"
MANIFEST="$ROOT/reports/research_raw/stage115_runtime_sync_manifest_latest.txt"
mkdir -p "$ROOT/reports/research_raw" "$ROOT/.runtime"

read_yaml_version() {
  local cfg="$1"
  "$PY" - "$cfg" <<'PY'
import sys, yaml
from pathlib import Path
p=Path(sys.argv[1])
obj=yaml.safe_load(p.read_text(encoding='utf-8')) or {}
print(((obj.get('system') or {}).get('version') or '').strip())
PY
}

BRANCH_EXPECTED_VERSION="$(read_yaml_version "$BRANCH_CFG")"
SHADOW_EXPECTED_VERSION="$(read_yaml_version "$SHADOW_CFG")"

workspace_common() {
  local ws="$1"
  mkdir -p "$ws" "$ws/reports" "$ws/.runtime"
  ln -sfn "$ROOT/src" "$ws/src"
  ln -sfn "$ROOT/tools" "$ws/tools"
  ln -sfn "$ROOT/data" "$ws/data"
  ln -sfn "$ROOT/requirements.txt" "$ws/requirements.txt"
  ln -sfn "$ROOT/.venv" "$ws/.venv"
}

patch_shadow_copy() {
  local src="$1"
  local out="$2"
  local report_path="$3"
  "$PY" - "$src" "$out" "$report_path" <<'PY'
import sys, yaml
from pathlib import Path
src, out, report = map(Path, sys.argv[1:4])
obj = yaml.safe_load(src.read_text(encoding='utf-8')) or {}
shadow = obj.get('shadow', obj) if isinstance(obj, dict) else {}
if not isinstance(shadow, dict):
    shadow = {}
autopilot = shadow.get('autopilot') if isinstance(shadow.get('autopilot'), dict) else {}
autopilot['public_report_txt'] = str(report)
shadow['autopilot'] = autopilot
if isinstance(obj, dict) and 'shadow' in obj:
    obj['shadow'] = shadow
else:
    obj = shadow
out.write_text(yaml.safe_dump(obj, allow_unicode=True, sort_keys=False), encoding='utf-8')
PY
}

stop_pid() {
  local pid_file="$1"
  if [ ! -f "$pid_file" ]; then
    return 0
  fi
  local pid
  pid="$(tr -d '[:space:]' < "$pid_file" 2>/dev/null || true)"
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    kill -TERM "$pid" 2>/dev/null || true
    for _ in $(seq 1 40); do
      if ! kill -0 "$pid" 2>/dev/null; then
        break
      fi
      sleep 0.25
    done
    if kill -0 "$pid" 2>/dev/null; then
      kill -KILL "$pid" 2>/dev/null || true
    fi
  fi
  rm -f "$pid_file"
}

report_is_boot_placeholder() {
  local report="$1"
  [ -f "$report" ] || return 0
  if grep -q '当前状态: 启动中' "$report" 2>/dev/null; then
    return 0
  fi
  if grep -q '状态原因: waiting_for_autopilot_process' "$report" 2>/dev/null; then
    return 0
  fi
  return 1
}

wait_for_report_version() {
  local report="$1"
  local expect="$2"
  local attempts="${3:-120}"
  local sleep_s="${4:-0.5}"
  local i
  for i in $(seq 1 "$attempts"); do
    if [ -f "$report" ] && ! report_is_boot_placeholder "$report"; then
      if [ -z "$expect" ] || grep -Fq "$expect" "$report" 2>/dev/null; then
        return 0
      fi
    fi
    sleep "$sleep_s"
  done
  return 1
}

start_autopilot() {
  local ws="$1"
  local log="$2"
  (
    cd "$ws"
    nohup "$PY" -u -m tools.okx_demo_autopilot --project-dir . --confirm-demo >>"$log" 2>&1 &
  )
}

make_branch_view_cmd() {
  cat > "$BRANCH_VIEW_CMD" <<EOF
#!/usr/bin/env bash
set +e
WORKSPACE="$BRANCH_WORK"
PID_FILE="$BRANCH_PID"
REPORT_FILE="$BRANCH_REPORT"
LOG_FILE="$BRANCH_LOG"
cd "\$WORKSPACE"
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
set_title() { printf "\033]0;%s\007" "$1"; }
render() {
  local title="【第二分支】BTC/ETH/SOL | okxb | stage115"
  set_title "$title"
  clear
  echo "$title"
  echo "Shortwave Demo 实时监控  时间(UTC+8): \$(local_ts)"
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
EOF
  chmod +x "$BRANCH_VIEW_CMD"
}

# 1) 分支：强制按当前 candidate config 重启到 workspace
workspace_common "$BRANCH_WORK"
cp -f "$BRANCH_CFG" "$BRANCH_WORK/config.yml"
patch_shadow_copy "$BRANCH_SHADOW" "$BRANCH_WORK/shadow.yml" "$BRANCH_REPORT"
echo "branch stage115 runtime sync" > "$BRANCH_WORK/BRANCH_DEMO_README.txt"
stop_pid "$BRANCH_PID"
start_autopilot "$BRANCH_WORK" "$BRANCH_LOG"
make_branch_view_cmd
if [ "$(uname -s 2>/dev/null || true)" = "Darwin" ] && command -v open >/dev/null 2>&1; then
  open -a Terminal "$BRANCH_VIEW_CMD" >/dev/null 2>&1 || open "$BRANCH_VIEW_CMD" >/dev/null 2>&1 || true
fi

# 2) 主线 shadow：按当前 candidate config 后台重启（不加第三终端）
workspace_common "$SHADOW_WORK"
cp -f "$SHADOW_CFG" "$SHADOW_WORK/config.yml"
patch_shadow_copy "$SHADOW_SHADOW" "$SHADOW_WORK/shadow.yml" "$SHADOW_REPORT"
echo "mainline shadow stage115 runtime sync" > "$SHADOW_WORK/MAINLINE_SHADOW_DEMO_README.txt"
stop_pid "$SHADOW_PID"
start_autopilot "$SHADOW_WORK" "$SHADOW_LOG"

# 3) 等待报告就绪
wait_for_report_version "$BRANCH_REPORT" "$BRANCH_EXPECTED_VERSION" 120 0.5 || true
wait_for_report_version "$SHADOW_REPORT" "$SHADOW_EXPECTED_VERSION" 120 0.5 || true

# 4) 生成 manifest + 单文件导出
"$PY" - "$MANIFEST" "$EXPORT_ZIP" "$LIVE_REPORT" "$BRANCH_REPORT" "$SHADOW_REPORT" "$BRANCH_CFG" "$SHADOW_CFG" "$BRANCH_SHADOW" "$SHADOW_SHADOW" "$BRANCH_EXPECTED_VERSION" "$SHADOW_EXPECTED_VERSION" <<'PY'
import sys, zipfile, re
from pathlib import Path
manifest_path = Path(sys.argv[1])
export_zip = Path(sys.argv[2])
live_report = Path(sys.argv[3])
branch_report = Path(sys.argv[4])
shadow_report = Path(sys.argv[5])
branch_cfg = Path(sys.argv[6])
shadow_cfg = Path(sys.argv[7])
branch_shadow = Path(sys.argv[8])
shadow_shadow = Path(sys.argv[9])
branch_expected = sys.argv[10]
shadow_expected = sys.argv[11]

def extract(path, label):
    txt = path.read_text(encoding='utf-8', errors='ignore') if path.exists() else ''
    def get(prefix):
        m = re.search(rf'^- {re.escape(prefix)}: (.*)$', txt, re.M)
        return m.group(1).strip() if m else '-'
    return {
        'label': label,
        'exists': path.exists(),
        'version': get('当前版本'),
        'state': get('当前状态'),
        'reason': get('状态原因'),
        'signal_time': get('最近策略信号时间(UTC+8)'),
        'next_run': get('下一轮执行(UTC+8)'),
    }

live = extract(live_report, 'mainline_live')
branch = extract(branch_report, 'branch_demo')
shadow = extract(shadow_report, 'mainline_shadow')
lines = []
lines.append('Stage115 runtime sync summary')
lines.append(f'live_version={live["version"]}')
lines.append(f'branch_expected={branch_expected}')
lines.append(f'branch_runtime={branch["version"]}')
lines.append(f'shadow_expected={shadow_expected}')
lines.append(f'shadow_runtime={shadow["version"]}')
lines.append('')
for row in (live, branch, shadow):
    lines.append(f'[{row["label"]}]')
    lines.append(f'exists={row["exists"]}')
    lines.append(f'version={row["version"]}')
    lines.append(f'state={row["state"]}')
    lines.append(f'reason={row["reason"]}')
    lines.append(f'signal_time={row["signal_time"]}')
    lines.append(f'next_run={row["next_run"]}')
    lines.append('')
manifest_path.write_text('\n'.join(lines), encoding='utf-8')
export_zip.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(export_zip, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
    for p in [live_report, branch_report, shadow_report, branch_cfg, shadow_cfg, branch_shadow, shadow_shadow, manifest_path]:
        if p.exists():
            zf.write(p, arcname=p.name)
print(export_zip)
PY

echo "[OK] stage115 runtime sync done"
echo "$EXPORT_ZIP"
