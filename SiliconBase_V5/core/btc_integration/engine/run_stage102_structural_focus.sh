#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PROGRESS="$HOME/Downloads/stage102_progress_latest.txt"
RAW="$ROOT/reports/research_raw"
KEYZIP="$HOME/Downloads/stage102_joint_key_files_latest.zip"
BUNDLE="$HOME/Downloads/chatgpt_bundle_latest.zip"
mkdir -p "$RAW" "$HOME/Downloads"
: > "$PROGRESS"

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$PROGRESS"
}

pick_python() {
  if [ -x "$ROOT/.venv/bin/python" ]; then
    printf '%s\n' "$ROOT/.venv/bin/python"
  else
    printf '%s\n' python3
  fi
}
PY="$(pick_python)"

bootstrap_venv() {
  log 'creating .venv'
  rm -rf "$ROOT/.venv"
  python3 -m venv "$ROOT/.venv"
  PY="$ROOT/.venv/bin/python"
  "$PY" -m pip install --upgrade pip >/dev/null
  "$PY" -m pip install -r "$ROOT/requirements.txt" >/dev/null
  touch "$ROOT/.venv/.deps_installed"
}

if [ ! -x "$PY" ] || ! "$PY" -c 'import sys; print(sys.executable)' >/dev/null 2>&1; then
  bootstrap_venv
elif [ -f "$ROOT/requirements.txt" ] && { [ ! -f "$ROOT/.venv/.deps_installed" ] || [ "$ROOT/requirements.txt" -nt "$ROOT/.venv/.deps_installed" ]; }; then
  log 'syncing python deps'
  "$PY" -m pip install -r "$ROOT/requirements.txt" >/dev/null
  touch "$ROOT/.venv/.deps_installed"
fi

have_module() {
  "$PY" - <<PY "$1"
import importlib.util, sys
mod = sys.argv[1]
sys.exit(0 if importlib.util.find_spec(mod) else 1)
PY
}

run_module() {
  local mod="$1"; shift || true
  if have_module "$mod"; then
    log "run module $mod $*"
    "$PY" -m "$mod" --project-dir "$ROOT" "$@"
    return 0
  fi
  return 1
}

run_script() {
  local path="$1"; shift || true
  if [ -f "$ROOT/$path" ]; then
    log "run script $path $*"
    bash "$ROOT/$path" "$@"
    return 0
  fi
  return 1
}

safe_step() {
  local label="$1"; shift
  log "$label"
  if "$@"; then
    log "ok: $label"
  else
    log "skip/fail tolerated: $label"
  fi
}

run_stage92_branch() {
  run_module tools.stage92_eth_sol_open_frontier --profile quick --wf-per-lane 2 \
    || run_script run_stage92_eth_sol_open_frontier.sh quick 2
}

run_stage93_mainline() {
  run_module tools.stage93_frequency_accel \
    || run_script run_stage93_frequency_accel.sh
}

run_stage94_priority() {
  run_module tools.stage94_priority_pipeline \
    || run_script run_stage94_priority_pipeline.sh
}

run_stage96_bridge() {
  run_script run_stage96_event_bridge.sh \
    || run_module tools.stage96_event_bridge \
    || run_script run_stage96_priority_refresh.sh \
    || run_module tools.stage96_priority_refresh
}

build_summary() {
  "$PY" - <<'PY' "$ROOT" "$RAW/stage102_joint_adjust_latest.txt"
from pathlib import Path
import sys
root = Path(sys.argv[1]).resolve()
out = Path(sys.argv[2]).resolve()
raw = root / 'reports' / 'research_raw'

def read_path(p: Path) -> str:
    try:
        return p.read_text(encoding='utf-8', errors='ignore') if p.exists() else ''
    except Exception:
        return ''

def pick_line(text: str, needles):
    for line in text.splitlines():
        if all(n in line for n in needles):
            return line.strip()
    return '-'

def field(text: str, needle: str) -> str:
    for line in text.splitlines():
        if needle in line:
            return line.strip()
    return '-'

okx = read_path(Path.home() / 'Downloads' / 'okx_demo_report_latest.txt')
branch = read_path(Path.home() / 'Downloads' / 'branch_demo_report_latest.txt')
s90 = read_path(raw / 'stage90_mainline_event_alpha_matrix_latest.txt')
s91 = read_path(raw / 'stage91_branch_event_alpha_matrix_latest.txt')
s93 = read_path(raw / 'stage93_frequency_accel_latest.txt')
s94 = read_path(raw / 'stage94_priority_pipeline_latest.txt')
s96 = read_path(raw / 'stage96_event_bridge_latest.txt') or read_path(raw / 'stage96_priority_refresh_latest.txt')

lines = []
lines.append('Stage102 主线+支线联合调整摘要')
lines.append('规则：6年整体仅作软约束；判断以近2年 + WF 为主；主线和支线一起推进，但不改现有双终端 demo 规则。')
lines.append('')
lines.append('=== Runtime ===')
lines.append(f"主线状态: {field(okx, '当前状态')}")
lines.append(f"主线当前版本: {field(okx, '当前版本')}")
lines.append(f"分支状态: {field(branch, '当前状态')}")
lines.append(f"分支当前版本: {field(branch, '当前版本')}")
lines.append('')
lines.append('=== 主线 ===')
for needles in [
    ['mainline_live_base'],
    ['combo_sr_soft_adx26_cd6_lb24_zone028_ref'],
    ['combo_sr_soft_adx32_cd5_lb20_zone025'],
]:
    ln = pick_line(s94 + '\n' + s93 + '\n' + s90, needles)
    lines.append(ln)
lines.append('')
lines.append('=== 支线 ===')
for needles in [
    ['eth_short_shock_fast_lb16_atr052_adx22_s078'],
    ['eth_retest_short_trend_lb20_atr060_adx24_s068'],
    ['eth_fast_trend_shortonly'],
    ['sol_shortwave_smooth_longonly'],
    ['BTC'],
]:
    ln = pick_line(s96 + '\n' + s91, needles)
    lines.append(ln)
lines.append('')
lines.append('=== 当前联合动作 ===')
lines.append('- 主线：keep live_base；同步保留 balanced/aggressive 两档提频候选。')
lines.append('- 支线：keep ETH short fast；ETH short 事件优先候选继续观察；ETH long / SOL long / SOL short 保留路径。')
lines.append('- 事件层：继续推进 event_pressure / event_reclaim / crowding_reversal，不再只看单一 overlay。')
lines.append('- 下一步：读取 stage90/stage91/stage93/stage94/stage96，再做 stage103 资产腿整体预览。')
out.write_text('\n'.join(lines) + '\n', encoding='utf-8')
print(out)
PY
}

build_keyzip() {
  "$PY" - <<'PY' "$ROOT" "$KEYZIP"
from pathlib import Path
import sys, zipfile
root = Path(sys.argv[1]).resolve()
out = Path(sys.argv[2]).resolve()
raw = root / 'reports' / 'research_raw'
downloads = Path.home() / 'Downloads'
candidates = [
    downloads / 'okx_demo_report_latest.txt',
    downloads / 'branch_demo_report_latest.txt',
    downloads / 'chatgpt_bundle_latest.zip',
    downloads / 'stage102_progress_latest.txt',
    raw / 'stage90_mainline_event_alpha_matrix_latest.txt',
    raw / 'stage91_branch_event_alpha_matrix_latest.txt',
    raw / 'stage93_frequency_accel_latest.txt',
    raw / 'stage94_priority_pipeline_latest.txt',
    raw / 'stage96_event_bridge_latest.txt',
    raw / 'stage96_priority_refresh_latest.txt',
    raw / 'stage102_joint_adjust_latest.txt',
]
with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
    seen = set()
    for p in candidates:
        if p.exists() and p.name not in seen:
            zf.write(p, arcname=p.name)
            seen.add(p.name)
print(out)
PY
}

log 'stage102 start | mainline+branch joint adjust'

safe_step 'stage90 mainline+branch event alpha matrix' run_module tools.stage90_event_alpha_matrix
safe_step 'stage92 branch open frontier quick' run_stage92_branch
safe_step 'stage93 mainline frequency accel' run_stage93_mainline
safe_step 'stage94 joint priority pipeline' run_stage94_priority
safe_step 'stage96 event bridge / priority refresh' run_stage96_bridge

if [ -f "$ROOT/run_send_files.sh" ]; then
  safe_step 'run_send_files' run_script run_send_files.sh
fi

safe_step 'build stage102 summary' build_summary
safe_step 'build stage102 key zip' build_keyzip

log "done | keyzip=$KEYZIP"
if [ -f "$BUNDLE" ]; then
  log "bundle=$BUNDLE"
fi
printf '%s\n' "$KEYZIP"
