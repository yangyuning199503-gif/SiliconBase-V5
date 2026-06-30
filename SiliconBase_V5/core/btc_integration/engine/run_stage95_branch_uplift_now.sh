#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CANON="$HOME/btc_system_v1"
if [ "$ROOT_DIR" != "$CANON" ] && [ -d "$CANON" ]; then
  echo "[ERR] 请在 ~/btc_system_v1 运行。当前目录: $ROOT_DIR" >&2
  exit 1
fi
cd "$ROOT_DIR"

PY="./.venv/bin/python"
bootstrap_venv() {
  echo "Creating virtualenv .venv ..."
  rm -rf .venv
  python3 -m venv .venv
  PY="./.venv/bin/python"
  "$PY" -m pip install --upgrade pip >/dev/null
  "$PY" -m pip install -r requirements.txt >/dev/null
  touch .venv/.deps_installed
}
if [ ! -x "$PY" ] || ! "$PY" -c 'import sys; print(sys.executable)' >/dev/null 2>&1; then
  bootstrap_venv
elif [ ! -f .venv/.deps_installed ] || [ requirements.txt -nt .venv/.deps_installed ]; then
  "$PY" -m pip install -r requirements.txt >/dev/null
  touch .venv/.deps_installed
fi

RAW="reports/research_raw"
mkdir -p "$RAW"
DOWNLOADS="$HOME/Downloads"
mkdir -p "$DOWNLOADS"
PROGRESS="$DOWNLOADS/stage95_progress_latest.txt"
TXT="$RAW/stage95_priority_sync_latest.txt"
JSON="$RAW/stage95_priority_sync_latest.json"
KEY_ZIP="$DOWNLOADS/stage95_key_files_latest.zip"
KEY_PATH_TXT="$DOWNLOADS/stage95_key_files_path_latest.txt"

: > "$PROGRESS"
log() {
  local msg="$1"
  printf '[%s] %s\n' "$(date '+%F %T')" "$msg" | tee -a "$PROGRESS"
}

log "stage95 start"
log "refresh branch raw"
bash ./refresh_branch_raw.sh

log "align backtest end"
"$PY" -m tools.align_backtest_end --project-dir . --config config_shortwave_candidate.yml | tee -a "$PROGRESS"

log "stage91 branch event alpha"
"$PY" -m tools.stage91_branch_event_alpha_matrix --project-dir . | tee -a "$PROGRESS"

log "stage92 eth/sol frontier"
"$PY" -m tools.stage92_eth_sol_open_frontier --project-dir . --profile quick --wf-per-lane 3 | tee -a "$PROGRESS"

log "stage94 priority pipeline"
if [ -f tools/stage94_priority_pipeline.py ]; then
  "$PY" -m tools.stage94_priority_pipeline --project-dir . | tee -a "$PROGRESS"
else
  log "stage94 skipped: tools/stage94_priority_pipeline.py missing"
fi

log "write stage95 summary"
"$PY" - <<'PY' "$ROOT_DIR" "$TXT" "$JSON"
import json
import re
import sys
from pathlib import Path
root = Path(sys.argv[1])
txt_path = Path(sys.argv[2])
json_path = Path(sys.argv[3])
raw = root / 'reports' / 'research_raw'

def read(p):
    try:
        return p.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        return ''

def extract_lane(txt, lane):
    pat = re.compile(rf"^- {re.escape(lane)}: (.+)$", re.M)
    m = pat.search(txt)
    return m.group(1).strip() if m else ''

stage92 = read(raw / 'stage92_eth_sol_open_frontier_latest.txt')
stage94 = read(raw / 'stage94_priority_pipeline_latest.txt')
eth_short = extract_lane(stage94, 'eth_short') or extract_lane(stage92, 'eth_short')
eth_long = extract_lane(stage94, 'eth_long') or extract_lane(stage92, 'eth_long')
sol_long = extract_lane(stage94, 'sol_long') or extract_lane(stage92, 'sol_long')
sol_short = extract_lane(stage94, 'sol_short') or extract_lane(stage92, 'sol_short')
lines = [
    'Stage95 分支提效同步',
    '原则：只刷新 ETH/SOL 分支，不重算主线；6年只作软约束，判断看近2年 + WF。',
    '',
    '=== 当前收口 ===',
    f'- eth_short: {eth_short or "-"}',
    f'- eth_long: {eth_long or "-"}',
    f'- sol_long: {sol_long or "-"}',
    f'- sol_short: {sol_short or "-"}',
    '',
    '=== 说明 ===',
    '- 已刷新 eth/sol raw，并重跑 stage91/stage92/stage94。',
    '- 主线双终端规则未改。',
]
txt_path.write_text('\n'.join(lines).rstrip() + '\n', encoding='utf-8')
payload = {
    'eth_short': eth_short,
    'eth_long': eth_long,
    'sol_long': sol_long,
    'sol_short': sol_short,
}
json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
print(txt_path)
print(json_path)
PY

log "build bundle"
bash ./run_send_files.sh | tee -a "$PROGRESS"

log "export stage95 key zip"
rm -f "$KEY_ZIP"
python3 - <<'PY' "$ROOT_DIR" "$KEY_ZIP" "$KEY_PATH_TXT"
import sys, zipfile
from pathlib import Path
root = Path(sys.argv[1])
out = Path(sys.argv[2])
path_txt = Path(sys.argv[3])
raw = root / 'reports' / 'research_raw'
downloads = Path.home() / 'Downloads'
files = [
    downloads / 'okx_demo_report_latest.txt',
    downloads / 'branch_demo_report_latest.txt',
    downloads / 'chatgpt_bundle_latest.zip',
    downloads / 'stage95_progress_latest.txt',
    raw / 'stage91_branch_event_alpha_matrix_latest.txt',
    raw / 'stage91_branch_event_alpha_matrix_latest.json',
    raw / 'stage92_eth_sol_open_frontier_latest.txt',
    raw / 'stage92_eth_sol_open_frontier_latest.json',
    raw / 'stage94_priority_pipeline_latest.txt',
    raw / 'stage94_priority_pipeline_latest.json',
    raw / 'stage95_priority_sync_latest.txt',
    raw / 'stage95_priority_sync_latest.json',
]
with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
    for p in files:
        if p.exists() and p.is_file():
            zf.write(p, arcname=p.name)
path_txt.write_text(str(out) + '\n', encoding='utf-8')
print(out)
PY

log "stage95 done"
log "key_zip=$KEY_ZIP"
log "bundle=$DOWNLOADS/chatgpt_bundle_latest.zip"
echo "$KEY_ZIP"
