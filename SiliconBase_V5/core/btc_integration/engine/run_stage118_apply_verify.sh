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

LIVE_REPORT="$HOME/Downloads/okx_demo_report_latest.txt"
BRANCH_REPORT="$HOME/Downloads/branch_demo_report_latest.txt"
REPORTS_RAW="$ROOT/reports/research_raw"
mkdir -p "$REPORTS_RAW"
SHADOW_REPORT="$REPORTS_RAW/mainline_shadow_demo_report_latest.txt"

BRANCH_CFG="$ROOT/config_shortwave_candidate.yml"
BRANCH_SHADOW="$ROOT/shadow_shortwave_candidate.yml"
BRANCH_WORK_ROOT="$ROOT/.branch_shortwave_demo"
BRANCH_WORK="$BRANCH_WORK_ROOT/workspace"
BRANCH_PID="$BRANCH_WORK/.runtime/okx_demo_autopilot.pid"
BRANCH_LOG="$BRANCH_WORK/.runtime/okx_demo_autopilot.log"

SHADOW_CFG="$ROOT/config_mainline_shadow_candidate.yml"
SHADOW_SHADOW="$ROOT/shadow_mainline_shadow_candidate.yml"
SHADOW_WORK_ROOT="$ROOT/.mainline_shadow_demo"
SHADOW_WORK="$SHADOW_WORK_ROOT/workspace"
SHADOW_PID="$SHADOW_WORK/.runtime/okx_demo_autopilot.pid"
SHADOW_LOG="$SHADOW_WORK/.runtime/okx_demo_autopilot.log"

EXPORT_ZIP="$HOME/Downloads/stage118_apply_verify_latest.zip"
SUMMARY_TXT="$REPORTS_RAW/stage118_apply_verify_summary_latest.txt"
MANIFEST="$REPORTS_RAW/stage118_apply_verify_manifest_latest.txt"

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

is_alive() {
  local pid_file="$1"
  [ -f "$pid_file" ] || return 1
  local pid
  pid="$(tr -d '[:space:]' < "$pid_file" 2>/dev/null || true)"
  [ -n "$pid" ] || return 1
  kill -0 "$pid" 2>/dev/null
}

stop_pid() {
  local pid_file="$1"
  if ! [ -f "$pid_file" ]; then
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

report_is_ready() {
  local report="$1"
  local expect="$2"
  [ -f "$report" ] || return 1
  grep -Fq "$expect" "$report" 2>/dev/null || return 1
  if grep -q '当前状态: 启动中' "$report" 2>/dev/null; then
    return 1
  fi
  return 0
}

wait_for_report() {
  local report="$1"
  local expect="$2"
  local attempts="${3:-120}"
  local sleep_s="${4:-0.5}"
  local i
  for i in $(seq 1 "$attempts"); do
    if report_is_ready "$report" "$expect"; then
      return 0
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

sync_runner() {
  local cfg="$1"
  local shcfg="$2"
  local ws="$3"
  local pidf="$4"
  local logf="$5"
  local report="$6"
  local expect="$7"
  workspace_common "$ws"
  cp -f "$cfg" "$ws/config.yml"
  patch_shadow_copy "$shcfg" "$ws/shadow.yml" "$report"
  local need_restart="1"
  if is_alive "$pidf" && report_is_ready "$report" "$expect"; then
    need_restart="0"
  fi
  if [ "$need_restart" = "1" ]; then
    stop_pid "$pidf"
    start_autopilot "$ws" "$logf"
    wait_for_report "$report" "$expect" 160 0.5 || true
  fi
}

BRANCH_EXPECTED_VERSION="$(read_yaml_version "$BRANCH_CFG")"
SHADOW_EXPECTED_VERSION="$(read_yaml_version "$SHADOW_CFG")"

# 主线 live 不动；只同步 branch preview + mainline shadow
sync_runner "$BRANCH_CFG" "$BRANCH_SHADOW" "$BRANCH_WORK" "$BRANCH_PID" "$BRANCH_LOG" "$BRANCH_REPORT" "$BRANCH_EXPECTED_VERSION"
sync_runner "$SHADOW_CFG" "$SHADOW_SHADOW" "$SHADOW_WORK" "$SHADOW_PID" "$SHADOW_LOG" "$SHADOW_REPORT" "$SHADOW_EXPECTED_VERSION"

"$PY" - "$SUMMARY_TXT" "$MANIFEST" "$EXPORT_ZIP" "$LIVE_REPORT" "$BRANCH_REPORT" "$SHADOW_REPORT" "$REPORTS_RAW/stage81_mainline_walkforward_latest.txt" "$REPORTS_RAW/stage82_branch_walkforward_latest.txt" "$BRANCH_EXPECTED_VERSION" "$SHADOW_EXPECTED_VERSION" "$BRANCH_CFG" "$SHADOW_CFG" <<'PY'
import re, sys, zipfile
from pathlib import Path
summary = Path(sys.argv[1])
manifest = Path(sys.argv[2])
export_zip = Path(sys.argv[3])
live_report = Path(sys.argv[4])
branch_report = Path(sys.argv[5])
shadow_report = Path(sys.argv[6])
stage81 = Path(sys.argv[7])
stage82 = Path(sys.argv[8])
branch_expected = sys.argv[9]
shadow_expected = sys.argv[10]
branch_cfg = Path(sys.argv[11])
shadow_cfg = Path(sys.argv[12])

def read(p: Path) -> str:
    return p.read_text(encoding='utf-8', errors='ignore') if p.exists() else ''

def get_report_meta(txt: str) -> dict:
    def g(label: str) -> str:
        m = re.search(rf'^- {re.escape(label)}: (.*)$', txt, re.M)
        return m.group(1).strip() if m else '-'
    return {
        'version': g('当前版本'),
        'state': g('当前状态'),
        'reason': g('状态原因'),
        'signal_time': g('最近策略信号时间(UTC+8)'),
        'candidate': g('当前候选'),
    }

def parse_stage81(txt: str) -> dict:
    out = {}
    for name in ['mainline_live_base','combo_sr_soft_adx26_cd6_lb24_zone028_ref','combo_sr_soft_adx32_cd5_lb20_zone025']:
        m = re.search(rf'^- {re.escape(name)}: (.*)$', txt, re.M)
        if m:
            out[name] = m.group(1).strip()
    return out

def parse_stage82(txt: str) -> dict:
    out = {}
    for lane in ['eth_short','eth_long','sol_long','sol_short']:
        m = re.search(rf'^- {re.escape(lane)}: (.*)$', txt, re.M)
        if m:
            out[lane] = m.group(1).strip()
    return out

live_txt = read(live_report)
branch_txt = read(branch_report)
shadow_txt = read(shadow_report)
stage81_txt = read(stage81)
stage82_txt = read(stage82)

live = get_report_meta(live_txt)
branch = get_report_meta(branch_txt)
shadow = get_report_meta(shadow_txt)

s81 = parse_stage81(stage81_txt)
s82 = parse_stage82(stage82_txt)

lines = []
lines.append('Stage118 apply+verify')
lines.append('')
lines.append('【运行态】')
lines.append(f"- 主线 live: version={live['version']} | state={live['state']} | reason={live['reason']} | signal={live['signal_time']}")
lines.append(f"- 第二分支 preview: expected={branch_expected} | runtime={branch['version']} | state={branch['state']} | reason={branch['reason']} | signal={branch['signal_time']}")
lines.append(f"- 主线 shadow: expected={shadow_expected} | runtime={shadow['version']} | state={shadow['state']} | reason={shadow['reason']} | signal={shadow['signal_time']}")
lines.append('')
lines.append('【主线有效回测】')
for k,v in s81.items():
    lines.append(f"- {k}: {v}")
lines.append('')
lines.append('【支线有效回测】')
for k,v in s82.items():
    lines.append(f"- {k}: {v}")
lines.append('')
lines.append('【结论】')
lines.append('- 主线 live 继续保留 mainline_live_base。')
lines.append('- 主线只推进 shadow，不直接切 live。')
lines.append('- 第二分支应保持 BTC/ETH/SOL 三标的 preview；ETH short 仍是当前 active 主收益腿。')
lines.append('- BTC 继续做确认腿；SOL 暂不切 active。')
summary.write_text('\n'.join(lines).rstrip() + '\n', encoding='utf-8')

manifest_lines = [
    'stage118_apply_verify_manifest',
    f'live_version={live["version"]}',
    f'branch_expected={branch_expected}',
    f'branch_runtime={branch["version"]}',
    f'shadow_expected={shadow_expected}',
    f'shadow_runtime={shadow["version"]}',
    f'export={export_zip}',
]
manifest.write_text('\n'.join(manifest_lines) + '\n', encoding='utf-8')

if export_zip.exists():
    export_zip.unlink()
with zipfile.ZipFile(export_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
    for p in [summary, manifest, live_report, branch_report, shadow_report, stage81, stage82, branch_cfg, shadow_cfg]:
        if p.exists():
            zf.write(p, arcname=p.name)
print(export_zip)
PY

echo "[OK] ~/Downloads/stage118_apply_verify_latest.zip"
