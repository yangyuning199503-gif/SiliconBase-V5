#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

CANON="$HOME/btc_system_v1"
if [ "$ROOT" != "$CANON" ] && [ -d "$CANON" ]; then
  echo "[ERR] 请在 ~/btc_system_v1 运行。当前目录: $ROOT" >&2
  exit 1
fi

DOWNLOADS="$HOME/Downloads"
OUTDIR="$ROOT/reports/research_raw/stage118_joint_decision"
mkdir -p "$DOWNLOADS" "$OUTDIR"

ZIP_OUT="$DOWNLOADS/stage118_joint_decision_latest.zip"
SUMMARY="$OUTDIR/stage118_summary_latest.txt"
STATUS="$OUTDIR/stage118_step_status_latest.tsv"
TMPDIR="$OUTDIR/_pack"
rm -rf "$TMPDIR"
mkdir -p "$TMPDIR"
: > "$STATUS"

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$SUMMARY"
}

run_step() {
  local name="$1"
  shift
  log "$name START"
  if "$@" >> "$SUMMARY" 2>&1; then
    printf '%s\tOK\n' "$name" >> "$STATUS"
    log "$name OK"
  else
    local rc=$?
    printf '%s\tFAIL(%s)\n' "$name" "$rc" >> "$STATUS"
    log "$name FAIL($rc)"
    return 0
  fi
}

# Clean summary
cat > "$SUMMARY" <<EOF
Stage118 联合决策刷新（研究层，不动 live/demo）
生成时间: $(date '+%Y-%m-%d %H:%M:%S %Z')
项目目录: $ROOT
输出文件: $ZIP_OUT
EOF

# Use existing project scripts; tolerate partial failure.
run_step stage79 bash run_stage79_dual_window_monthlyized.sh
run_step stage81_82 bash run_stage81_82_walkforward.sh
run_step stage88 bash run_stage88_fusion_sprint.sh
run_step stage90 bash run_stage90_event_alpha_sprint.sh

# Pack the latest research files if they exist.
copy_if_exists() {
  local src="$1"
  [ -f "$src" ] || return 0
  cp -f "$src" "$TMPDIR/$(basename "$src")"
}
copy_glob_latest() {
  local pattern="$1"
  shopt -s nullglob
  local files=( $pattern )
  shopt -u nullglob
  local f
  for f in "${files[@]}"; do
    [ -f "$f" ] || continue
    cp -f "$f" "$TMPDIR/$(basename "$f")"
  done
}

copy_glob_latest "$ROOT/reports/research_raw/stage77_mainline_dual_window_latest.*"
copy_glob_latest "$ROOT/reports/research_raw/stage78_branch_dual_window_latest.*"
copy_glob_latest "$ROOT/reports/research_raw/stage81_mainline_walkforward_latest.*"
copy_glob_latest "$ROOT/reports/research_raw/stage82_branch_walkforward_latest.*"
copy_glob_latest "$ROOT/reports/research_raw/stage88_*latest.*"
copy_glob_latest "$ROOT/reports/research_raw/stage90_*latest.*"
copy_glob_latest "$ROOT/reports/research_raw/stage93_*latest.*"
copy_glob_latest "$ROOT/reports/research_raw/local_info_sources_latest.txt"
copy_if_exists "$DOWNLOADS/okx_demo_report_latest.txt"
copy_if_exists "$DOWNLOADS/branch_demo_report_latest.txt"
cp -f "$SUMMARY" "$TMPDIR/stage118_summary_latest.txt"
cp -f "$STATUS" "$TMPDIR/stage118_step_status_latest.tsv"

(
  cd "$TMPDIR"
  rm -f "$ZIP_OUT"
  zip -q -r "$ZIP_OUT" .
)

# Keep Downloads tidy: preserve only demo reports + target zip.
mkdir -p "$ROOT/reports/download_noise_archive"
for noisy in \
  "$DOWNLOADS/chatgpt_bundle_latest.zip" \
  "$DOWNLOADS/deepseek_single_file_latest.txt" \
  "$DOWNLOADS/stage77_mainline_dual_window_latest.txt" \
  "$DOWNLOADS/stage78_branch_dual_window_latest.txt" \
  "$DOWNLOADS/stage81_mainline_walkforward_latest.txt" \
  "$DOWNLOADS/stage82_branch_walkforward_latest.txt" \
  "$DOWNLOADS/stage88_strategy_fusion_latest.txt" \
  "$DOWNLOADS/stage90_mainline_event_alpha_matrix_latest.txt" \
  "$DOWNLOADS/stage93_frequency_accel_latest.txt"; do
  if [ -f "$noisy" ]; then
    mv -f "$noisy" "$ROOT/reports/download_noise_archive/$(basename "$noisy" 2>/dev/null || true).$(date +%Y%m%d_%H%M%S)" 2>/dev/null || true
  fi
done

echo "[OK] $ZIP_OUT"
