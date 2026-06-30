#!/usr/bin/env bash
set -u -o pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
RAW="$ROOT/reports/research_raw"
ARCHIVE="$ROOT/reports/download_noise_archive"
mkdir -p "$RAW" "$ARCHIVE"
PROGRESS="$RAW/stage117_progress_latest.txt"
SUMMARY="$RAW/stage117_summary_latest.txt"
OUT="$HOME/Downloads/stage117_joint_repair_latest.zip"
STATUS_TSV="$RAW/stage117_step_status_latest.tsv"

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" | tee -a "$PROGRESS"
}

archive_noise() {
  local f
  for f in \
    "$HOME/Downloads/chatgpt_bundle_latest.zip" \
    "$HOME/Downloads/chatgpt_bundle_path_latest.txt" \
    "$HOME/Downloads/stage117_progress_latest.txt"; do
    if [ -f "$f" ]; then
      mv -f "$f" "$ARCHIVE/$(basename "$f")" 2>/dev/null || true
    fi
  done
}

package_output() {
  ROOT_ENV="$ROOT" RAW_ENV="$RAW" PROGRESS_ENV="$PROGRESS" SUMMARY_ENV="$SUMMARY" STATUS_ENV="$STATUS_TSV" OUT_ENV="$OUT" python3 - <<'PY'
from pathlib import Path
import os, zipfile
raw = Path(os.environ['RAW_ENV'])
out = Path(os.environ['OUT_ENV'])
out.parent.mkdir(parents=True, exist_ok=True)
items = [
    Path(os.environ['PROGRESS_ENV']),
    Path(os.environ['SUMMARY_ENV']),
    Path(os.environ['STATUS_ENV']),
    raw / 'stage81_mainline_walkforward_latest.txt',
    raw / 'stage81_mainline_walkforward_latest.json',
    raw / 'stage82_branch_walkforward_latest.txt',
    raw / 'stage82_branch_walkforward_latest.json',
    raw / 'stage88_strategy_fusion_walkforward_latest.txt',
    raw / 'stage88_strategy_fusion_walkforward_latest.json',
    raw / 'stage90_mainline_event_alpha_matrix_latest.txt',
    raw / 'stage90_mainline_event_alpha_matrix_latest.json',
    raw / 'stage93_frequency_accel_latest.txt',
    raw / 'stage93_frequency_accel_latest.json',
    Path.home() / 'Downloads' / 'okx_demo_report_latest.txt',
    Path.home() / 'Downloads' / 'branch_demo_report_latest.txt',
]
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as zf:
    for p in items:
        if p.exists():
            zf.write(p, p.name)
print(out)
PY
}

finalize() {
  local rc=$?
  {
    echo "exit_code=$rc"
    echo "output=$OUT"
  } >> "$SUMMARY"
  archive_noise
  package_output >> "$PROGRESS" 2>&1 || true
  if [ -f "$OUT" ]; then
    log "[DONE] 已生成 $(basename "$OUT")"
  else
    log "[FAIL] 未生成输出包"
  fi
  exit $rc
}
trap finalize EXIT

: > "$PROGRESS"
: > "$SUMMARY"
: > "$STATUS_TSV"
log 'Stage117 主线WF修复 + 联合复核（研究层，不动 live/demo）'

run_step() {
  local key="$1"
  local label="$2"
  shift 2
  log "$label"
  if "$@" >> "$PROGRESS" 2>&1; then
    echo -e "$key\tOK" >> "$STATUS_TSV"
    log "[OK] $label"
  else
    local rc=$?
    echo -e "$key\tFAIL($rc)" >> "$STATUS_TSV"
    log "[FAIL] $label | exit=$rc"
  fi
}

run_step stage81_82 'stage81/82 walkforward' bash "$ROOT/run_stage81_82_walkforward.sh"
run_step stage88 'stage88 fusion sprint' bash "$ROOT/run_stage88_fusion_sprint.sh"
run_step stage90 'stage90 mainline event alpha' bash "$ROOT/run_stage90_event_alpha_sprint.sh"
run_step stage93 'stage93 frequency accel' bash "$ROOT/run_stage93_frequency_accel.sh"

{
  echo 'summary:'
  cat "$STATUS_TSV"
} >> "$SUMMARY"

log 'Stage117 执行结束，开始打包单文件输出'
