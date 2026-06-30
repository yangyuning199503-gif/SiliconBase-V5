#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
CANON="$HOME/btc_system_v1"
if [ "$ROOT" != "$CANON" ] && [ -d "$CANON" ]; then
  echo "[ERR] 请在 ~/btc_system_v1 运行。当前目录: $ROOT" >&2
  exit 1
fi
cd "$ROOT"

PROGRESS="$HOME/Downloads/stage95_progress_latest.txt"
RAW="$ROOT/reports/research_raw"
mkdir -p "$RAW"
: > "$PROGRESS"
log() {
  local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
  echo "$msg" | tee -a "$PROGRESS"
}

PY="$ROOT/.venv/bin/python"
bootstrap_venv() {
  log "Creating virtualenv .venv ..."
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
  log "Refreshing python deps ..."
  "$PY" -m pip install -r "$ROOT/requirements.txt" >/dev/null
  touch "$ROOT/.venv/.deps_installed"
fi

fresh_enough() {
  local file="$1"
  local max_age_hours="$2"
  [ -f "$file" ] || return 1
  local now ts age
  now=$(date +%s)
  ts=$(python3 - <<'PY' "$file"
from pathlib import Path
import os, sys
p=Path(sys.argv[1])
print(int(p.stat().st_mtime))
PY
)
  age=$(( (now - ts) / 3600 ))
  [ "$age" -le "$max_age_hours" ]
}

run_stage91_optional() {
  if [ -f "$ROOT/tools/stage91_branch_event_alpha_matrix.py" ]; then
    "$PY" -m tools.stage91_branch_event_alpha_matrix --project-dir "$ROOT"
  elif [ -f "$ROOT/run_stage91_branch_event_alpha_matrix.sh" ]; then
    bash "$ROOT/run_stage91_branch_event_alpha_matrix.sh"
  elif [ -f "$ROOT/run_stage91_branch_event_alpha.sh" ]; then
    bash "$ROOT/run_stage91_branch_event_alpha.sh"
  else
    log "[skip] stage91 runner not found"
  fi
}

MAX_CACHE_HOURS="${STAGE95_CACHE_HOURS:-12}"

log "Stage95 sync start"

if fresh_enough "$RAW/stage90_mainline_event_alpha_matrix_latest.txt" "$MAX_CACHE_HOURS"; then
  log "Using cached stage90 (<=${MAX_CACHE_HOURS}h)"
else
  log "Running stage90 ..."
  "$PY" -m tools.stage90_event_alpha_matrix --project-dir "$ROOT"
fi

if fresh_enough "$RAW/stage91_branch_event_alpha_matrix_latest.txt" "$MAX_CACHE_HOURS"; then
  log "Using cached stage91 (<=${MAX_CACHE_HOURS}h)"
else
  log "Running stage91 ..."
  run_stage91_optional || true
fi

if [ -f "$ROOT/tools/stage92_eth_sol_open_frontier.py" ]; then
  if fresh_enough "$RAW/stage92_eth_sol_open_frontier_latest.txt" "$MAX_CACHE_HOURS"; then
    log "Using cached stage92 (<=${MAX_CACHE_HOURS}h)"
  else
    if [ "${RUN_STAGE92:-1}" = "1" ]; then
      log "Running stage92 quick frontier ..."
      "$PY" -m tools.stage92_eth_sol_open_frontier --project-dir "$ROOT" --profile quick --wf-per-lane 2 || true
    else
      log "Skip stage92 by RUN_STAGE92=0"
    fi
  fi
fi

if fresh_enough "$RAW/stage93_frequency_accel_latest.txt" "$MAX_CACHE_HOURS"; then
  log "Using cached stage93 (<=${MAX_CACHE_HOURS}h)"
else
  log "Running stage93 ..."
  "$PY" -m tools.stage93_frequency_accel --project-dir "$ROOT"
fi

if [ "${RUN_STAGE94:-0}" = "1" ]; then
  if fresh_enough "$RAW/stage94_priority_pipeline_latest.txt" "$MAX_CACHE_HOURS"; then
    log "Using cached stage94 (<=${MAX_CACHE_HOURS}h)"
  elif [ -f "$ROOT/tools/stage94_priority_pipeline.py" ]; then
    log "Running stage94 priority pipeline ..."
    "$PY" -m tools.stage94_priority_pipeline --project-dir "$ROOT" || true
  else
    log "[skip] stage94 tool not found"
  fi
else
  log "Skip stage94 by default for speed; set RUN_STAGE94=1 when needed"
fi

log "Writing stage95 summary ..."
"$PY" - <<'PY' "$ROOT"
from __future__ import annotations
import json, re, sys
from datetime import datetime, timezone
from pathlib import Path

root = Path(sys.argv[1]).resolve()
raw = root / 'reports' / 'research_raw'
downloads = Path.home() / 'Downloads'

def read(p: Path) -> str:
    try:
        return p.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        return ''

def line_starting(text: str, prefix: str) -> str:
    for line in text.splitlines():
        if line.strip().startswith(prefix):
            return line.strip()
    return ''

def extract_overview(report: str) -> dict:
    def pull(label: str) -> str:
        m = re.search(rf"- {re.escape(label)}: (.+)", report)
        return m.group(1).strip() if m else ''
    return {
        'state': pull('当前状态'),
        'reason': pull('状态原因'),
        'version': pull('当前版本'),
        'next_run': pull('下一轮执行(UTC+8)'),
        'signal_time': pull('最近策略信号时间(UTC+8)'),
        'candidate': pull('当前候选'),
    }

okx = read(downloads / 'okx_demo_report_latest.txt')
branch = read(downloads / 'branch_demo_report_latest.txt')
msg = read(raw / 'message_stack_backtest_latest.txt')
stage93 = read(raw / 'stage93_frequency_accel_latest.txt')
stage90 = read(raw / 'stage90_mainline_event_alpha_matrix_latest.txt')
stage91 = read(raw / 'stage91_branch_event_alpha_matrix_latest.txt')
stage94 = read(raw / 'stage94_priority_pipeline_latest.txt')

out_txt = raw / 'stage95_priority_sync_latest.txt'
out_json = raw / 'stage95_priority_sync_latest.json'

main_live = line_starting(stage93, '- live_keep:')
main_bal = line_starting(stage93, '- shadow_balanced:')
main_agg = line_starting(stage93, '- shadow_aggressive:')
branch_push = line_starting(stage93, '- eth_short:')
sol_hold = line_starting(stage93, '- sol_long:')
sol_rebuild = line_starting(stage93, '- sol_short:')
msg_conclusion = line_starting(msg, '- 组合消息面比单独事件库/单独CoinGlass更值得继续保留在 risk layer；仍不升 alpha。')
main_gate = line_starting(stage90, '- mainline_live_base:')
branch_gate = line_starting(stage91, '- ETH | short | eth_short_shock_fast_lb16_atr052_adx22_s078:')

okx_info = extract_overview(okx)
branch_info = extract_overview(branch)

lines = []
lines.append('Stage95 优先级同步')
lines.append('=================')
lines.append(f'生成时间(UTC): {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}')
lines.append('策略口径: 6年总样本仅作软约束；以近2年 + WF 为主。')
lines.append('')
lines.append('【运行状态】')
lines.append(f"- 主线: state={okx_info['state']} | reason={okx_info['reason']} | version={okx_info['version']} | next={okx_info['next_run']}")
lines.append(f"- 分支: state={branch_info['state']} | reason={branch_info['reason']} | version={branch_info['version']} | next={branch_info['next_run']}")
lines.append('')
lines.append('【主线优先级】')
if main_live: lines.append(main_live)
if main_bal: lines.append(main_bal)
if main_agg: lines.append(main_agg)
if main_gate: lines.append(main_gate)
lines.append('')
lines.append('【分支优先级】')
if branch_push: lines.append(branch_push)
if branch_gate: lines.append(branch_gate)
if sol_hold: lines.append(sol_hold)
if sol_rebuild: lines.append(sol_rebuild)
lines.append('')
lines.append('【消息面/事件层】')
if msg_conclusion:
    lines.append(msg_conclusion)
else:
    lines.append('- combined_stack 继续保留在 risk layer；当前不直接升 alpha。')
lines.append('')
lines.append('【阶段判断】')
lines.append('- 主线继续保留 mainline_live_base；balanced/aggressive 只做 shadow 对照。')
lines.append('- 分支继续 ETH short fast；ETH long / SOL long / SOL short 继续研究，不轻易砍路径。')
lines.append('- 默认不重跑 stage94；如需强制刷新 priority pipeline，设置 RUN_STAGE94=1。')
if stage94.strip():
    lines.append('- stage94_priority_pipeline_latest.txt: present')
else:
    lines.append('- stage94_priority_pipeline_latest.txt: absent (本轮未强制刷新)')
text = '\n'.join(lines).rstrip() + '\n'
out_txt.write_text(text, encoding='utf-8')
out_json.write_text(json.dumps({
    'generated_at_utc': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'),
    'okx': okx_info,
    'branch': branch_info,
    'mainline_live': main_live,
    'mainline_shadow_balanced': main_bal,
    'mainline_shadow_aggressive': main_agg,
    'branch_push': branch_push,
    'message_conclusion': msg_conclusion or 'combined_stack kept in risk layer, not promoted to alpha',
    'stage94_present': bool(stage94.strip()),
}, ensure_ascii=False, indent=2), encoding='utf-8')
print(out_txt)
print(out_json)
PY

log "Packaging bundle ..."
bash "$ROOT/run_send_files.sh" | tee -a "$PROGRESS"

log "Verifying bundle ..."
"$PY" - <<'PY' "$ROOT"
import sys, zipfile
from pathlib import Path
root = Path(sys.argv[1]).resolve()
downloads = Path.home() / 'Downloads'
raw = root / 'reports' / 'research_raw'
bundle = downloads / 'chatgpt_bundle_latest.zip'
if not bundle.exists():
    raise SystemExit('chatgpt_bundle_latest.zip 未生成')
required = [
    'okx_demo_report_latest.txt',
    'branch_demo_report_latest.txt',
    'stage90_mainline_event_alpha_matrix_latest.txt',
    'stage91_branch_event_alpha_matrix_latest.txt',
    'stage92_eth_sol_open_frontier_latest.txt',
    'stage93_frequency_accel_latest.txt',
    'stage95_priority_sync_latest.txt',
]
with zipfile.ZipFile(bundle) as zf:
    names = set(zf.namelist())
missing = [name for name in required if name not in names]
if missing:
    print('bundle 缺少文件:')
    for name in missing:
        print('-', name)
    raise SystemExit(1)
print('[ok] bundle verified')
for name in required:
    print('-', name)
PY

log "Stage95 sync done"
log "Send: ~/Downloads/chatgpt_bundle_latest.zip"
