#!/usr/bin/env bash
set -u

ROOT="$(cd "$(dirname "$0")" && pwd)"
DOWNLOADS="$HOME/Downloads"
if [ ! -d "$DOWNLOADS" ]; then
  DOWNLOADS="$ROOT/reports/research_raw"
fi
OUT_ZIP="$DOWNLOADS/stage219_truth_locked_seed_frontier_latest.zip"
TMP_DIR="$ROOT/reports/research_raw/stage219_truth_locked_seed_frontier_tmp"
LOG="$TMP_DIR/stage219_full_log.txt"
STATUS="$TMP_DIR/stage219_step_status.tsv"
SUMMARY="$TMP_DIR/stage219_truth_locked_seed_frontier_bundle_latest.txt"
SNAP="$TMP_DIR/reports_snapshot"
TODAY="$(date +%F)"

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

PY="$ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
  PY="python3"
fi

BRANCH_CFG="config_shortwave_triple_book_stage133.yml"
if [ ! -f "$ROOT/$BRANCH_CFG" ]; then
  BRANCH_CFG="config.yml"
fi

raw_guard_cmd() {
  bash -lc "cd '$ROOT' && '$PY' -m tools.raw_data_guard --project-dir . --config '$BRANCH_CFG'"
}

auto_fix_branch_raw_truth() {
  echo "[$(date '+%F %T')] START auto_fix_branch_raw_truth" >> "$LOG"
  {
    echo "[auto_fix] refresh_mainline_raw.sh $TODAY"
    if [ -f "$ROOT/refresh_mainline_raw.sh" ]; then
      bash "$ROOT/refresh_mainline_raw.sh" "$TODAY" || true
    else
      echo "missing refresh_mainline_raw.sh"
    fi
    echo "[auto_fix] refresh_branch_research_raw.sh $TODAY"
    if [ -f "$ROOT/refresh_branch_research_raw.sh" ]; then
      bash "$ROOT/refresh_branch_research_raw.sh" "$TODAY" || true
    else
      echo "missing refresh_branch_research_raw.sh"
    fi
    if [ -f "$ROOT/run_precheck.sh" ]; then
      echo "[auto_fix] run_precheck.sh"
      bash "$ROOT/run_precheck.sh" || true
    fi
  } >> "$LOG" 2>&1
  if raw_guard_cmd >> "$LOG" 2>&1; then
    printf '%s\tOK\n' auto_fix_branch_raw_truth >> "$STATUS"
    echo "[$(date '+%F %T')] OK    auto_fix_branch_raw_truth" >> "$LOG"
    return 0
  fi
  printf '%s\tFAIL\n' auto_fix_branch_raw_truth >> "$STATUS"
  echo "[$(date '+%F %T')] FAIL  auto_fix_branch_raw_truth" >> "$LOG"
  return 1
}

overall_status="OK"
system_gate="PASS"
rm -f "$OUT_ZIP"
cd "$ROOT" || exit 1

if ! run_step py_compile "$PY" -m py_compile \
  "$ROOT/tools/message_stack_backtest.py" \
  "$ROOT/tools/stage217_multiregime_broadfront_frontier.py" \
  "$ROOT/tools/stage218_candidate_truth_sync_frontier.py" \
  "$ROOT/tools/stage219_truth_locked_seed_frontier.py" \
  "$ROOT/tools/stage46_aggressive_lab.py" \
  "$ROOT/tools/stage59_structural_lab.py" \
  "$ROOT/tools/raw_data_guard.py"; then
  overall_status="PARTIAL_FAIL"
  system_gate="FAIL"
fi

branch_guard_ok=1
if ! run_step branch_raw_guard raw_guard_cmd; then
  overall_status="PARTIAL_FAIL"
  branch_guard_ok=0
fi

if [ "$branch_guard_ok" -eq 0 ]; then
  if auto_fix_branch_raw_truth && run_step branch_raw_guard_after_fix raw_guard_cmd; then
    system_gate="PASS"
  else
    system_gate="FAIL"
  fi
fi

OUT_TXT="$ROOT/reports/research_raw/stage219_truth_locked_seed_frontier_latest.txt"
OUT_JSON="$ROOT/reports/research_raw/stage219_truth_locked_seed_frontier_latest.json"
if [ "$system_gate" = "PASS" ]; then
  if ! run_step stage219_truth_locked_seed_frontier "$PY" -u "$ROOT/tools/stage219_truth_locked_seed_frontier.py" --project-dir "$ROOT" --out-txt "$OUT_TXT" --out-json "$OUT_JSON"; then
    overall_status="PARTIAL_FAIL"
  fi
else
  printf '%s\tSKIP\n' stage219_truth_locked_seed_frontier >> "$STATUS"
  echo "[$(date '+%F %T')] SKIP  stage219 because system_gate=FAIL" >> "$LOG"
fi

for f in \
  "$OUT_TXT" \
  "$OUT_JSON" \
  "$ROOT/reports/research_raw/stage91_branch_event_alpha_matrix_latest.txt" \
  "$HOME/Downloads/branch_demo_report_latest.txt" \
  "$HOME/Downloads/okx_demo_report_latest.txt"; do
  copy_if_exists "$f" "$SNAP" || true
done

cat > "$SUMMARY" <<EOF2
Stage219 truth-locked seed frontier bundle

- 对外只生成 1 个文件：stage219_truth_locked_seed_frontier_latest.zip
- 这版用 stage91 文本摘要锁真值，只修口径，不改 demo，不改 entry。
- overall_status=$overall_status
- system_gate=$system_gate

[step_status]
$(cat "$STATUS")

[notes]
- 6年必报，但排序先看近2年 + WF。
- branch_raw_guard 若因 BTC 覆盖不足失败，会先自动 refresh/repair 一次，再重跑 guard。
- sync FAIL 只标记 pending_resync，不删路径。
EOF2

(
  cd "$TMP_DIR" || exit 1
  zip -qr "$OUT_ZIP" .
)

echo "$OUT_ZIP"
exit 0
