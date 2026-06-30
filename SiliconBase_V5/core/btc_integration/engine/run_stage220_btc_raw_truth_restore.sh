#!/usr/bin/env bash
set -u

ROOT="$(cd "$(dirname "$0")" && pwd)"
DOWNLOADS="$HOME/Downloads"
if [ ! -d "$DOWNLOADS" ]; then
  DOWNLOADS="$ROOT/reports/research_raw"
fi
OUT_ZIP="$DOWNLOADS/stage220_btc_raw_truth_restore_latest.zip"
TMP_DIR="$ROOT/reports/research_raw/stage220_btc_raw_truth_restore_tmp"
LOG="$TMP_DIR/stage220_full_log.txt"
STATUS="$TMP_DIR/stage220_step_status.tsv"
SUMMARY="$TMP_DIR/stage220_btc_raw_truth_restore_bundle_latest.txt"
SNAP="$TMP_DIR/reports_snapshot"

mkdir -p "$TMP_DIR"
rm -rf "$TMP_DIR"/*
mkdir -p "$SNAP"
: > "$LOG"
: > "$STATUS"

run_step() {
  local name="$1"
  shift
  echo "[$(date '+%F %T')] START $name" >> "$LOG"
  if "$@" >> "$LOG" 2>&1; then
    printf '%s\tOK\n' "$name" >> "$STATUS"
    echo "[$(date '+%F %T')] OK    $name" >> "$LOG"
    return 0
  fi
  printf '%s\tFAIL\n' "$name" >> "$STATUS"
  echo "[$(date '+%F %T')] FAIL  $name" >> "$LOG"
  return 1
}

copy_if_exists() {
  local src="$1"
  local dst_dir="$2"
  if [ -f "$src" ]; then
    cp -f "$src" "$dst_dir/"
    return 0
  fi
  return 1
}

overall_status="OK"
rm -f "$OUT_ZIP"
cd "$ROOT" || exit 1

run_step pause_main bash -lc "cd '$ROOT' && bash pause_okx_demo.sh" || overall_status="PARTIAL_FAIL"
run_step pause_branch bash -lc "cd '$ROOT' && bash pause_branch_demo.sh" || overall_status="PARTIAL_FAIL"

if ! run_step stage219_rerun_with_autofix bash -lc "cd '$ROOT' && bash run_stage219_truth_locked_seed_frontier.sh"; then
  overall_status="PARTIAL_FAIL"
fi

run_step start_main bash -lc "cd '$ROOT' && bash start_okx_demo.sh" || overall_status="PARTIAL_FAIL"
run_step start_branch bash -lc "cd '$ROOT' && bash start_branch_demo.sh" || overall_status="PARTIAL_FAIL"

for f in \
  "$HOME/Downloads/stage219_truth_locked_seed_frontier_latest.zip" \
  "$HOME/Downloads/branch_demo_report_latest.txt" \
  "$HOME/Downloads/okx_demo_report_latest.txt"; do
  copy_if_exists "$f" "$SNAP" || true
done

cat > "$SUMMARY" <<EOF2
Stage220 BTC raw truth restore bundle

- 对外只生成 1 个文件：stage220_btc_raw_truth_restore_latest.zip
- 这版先暂停 main/branch，再调用带 auto-fix 的 stage219 重跑，最后恢复 demo。
- overall_status=$overall_status

[step_status]
$(cat "$STATUS")

[notes]
- 核心目标：修 BTC raw 真相，再让 stage219 真正跑到 frontier。
- 若 stage219 仍失败，先看同包里的 stage219_truth_locked_seed_frontier_latest.zip 和 stage220_full_log.txt。
EOF2

(
  cd "$TMP_DIR" || exit 1
  zip -qr "$OUT_ZIP" .
)

echo "$OUT_ZIP"
exit 0
