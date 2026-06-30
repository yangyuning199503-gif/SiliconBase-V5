#!/usr/bin/env bash
set -u

ROOT="$(cd "$(dirname "$0")" && pwd)"
DOWNLOADS="$HOME/Downloads"
if [ ! -d "$DOWNLOADS" ]; then
  DOWNLOADS="$ROOT/reports/research_raw"
fi
OUT_ZIP="$DOWNLOADS/stage223_truth_locked_broadfront_frontier_latest.zip"
TMP_DIR="$ROOT/reports/research_raw/stage223_truth_locked_broadfront_frontier_tmp"
LOG="$TMP_DIR/stage223_full_log.txt"
STATUS="$TMP_DIR/stage223_step_status.tsv"
SUMMARY="$TMP_DIR/stage223_truth_locked_broadfront_frontier_bundle_latest.txt"
SNAP="$TMP_DIR/reports_snapshot"

mkdir -p "$TMP_DIR"
rm -rf "$TMP_DIR"/*
mkdir -p "$SNAP"
: > "$LOG"
: > "$STATUS"
rm -f "$OUT_ZIP"

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

overall_status="OK"
system_gate="PASS"
cd "$ROOT" || exit 1

if ! run_step py_compile "$PY" -m py_compile \
  "$ROOT/tools/message_stack_backtest.py" \
  "$ROOT/tools/stage217_multiregime_broadfront_frontier.py" \
  "$ROOT/tools/stage218_candidate_truth_sync_frontier.py" \
  "$ROOT/tools/stage219_truth_locked_seed_frontier.py" \
  "$ROOT/tools/stage223_truth_locked_broadfront_frontier.py" \
  "$ROOT/tools/raw_data_guard.py" \
  "$ROOT/tools/repair_raw_from_snapshots.py"; then
  overall_status="PARTIAL_FAIL"
  system_gate="FAIL"
fi

if ! run_step branch_raw_repair_guard bash -lc "cd '$ROOT' && '$PY' -m tools.repair_raw_from_snapshots --project-dir . --config '$BRANCH_CFG' >/dev/null || true && '$PY' -m tools.raw_data_guard --project-dir . --config '$BRANCH_CFG'"; then
  overall_status="PARTIAL_FAIL"
  system_gate="FAIL"
fi

OUT_TXT="$ROOT/reports/research_raw/stage223_truth_locked_broadfront_frontier_latest.txt"
OUT_JSON="$ROOT/reports/research_raw/stage223_truth_locked_broadfront_frontier_latest.json"
if [ "$system_gate" = "PASS" ]; then
  if ! run_step stage223_truth_locked_broadfront_frontier "$PY" -u "$ROOT/tools/stage223_truth_locked_broadfront_frontier.py" --project-dir "$ROOT" --out-txt "$OUT_TXT" --out-json "$OUT_JSON"; then
    overall_status="PARTIAL_FAIL"
  fi
else
  printf '%s\tSKIP\n' stage223_truth_locked_broadfront_frontier >> "$STATUS"
  echo "[$(date '+%F %T')] SKIP  stage223 because system_gate=FAIL" >> "$LOG"
fi

for f in \
  "$OUT_TXT" \
  "$OUT_JSON" \
  "$ROOT/reports/research_raw/stage91_branch_event_alpha_matrix_latest.txt" \
  "$HOME/Downloads/branch_demo_report_latest.txt" \
  "$HOME/Downloads/okx_demo_report_latest.txt"; do
  copy_if_exists "$f" "$SNAP" || true
done

cat > "$SUMMARY" <<EOF
Stage223 truth-locked broadfront frontier bundle

- 对外只生成 1 个文件：stage223_truth_locked_broadfront_frontier_latest.zip
- 这版不再来回跑 system / truth / broadfront；直接在已通过的 system_gate 上做 truth-locked broadfront。
- overall_status=$overall_status
- system_gate=$system_gate

[step_status]
$(cat "$STATUS")

[notes]
- 6年必报，但排序继续先看近2年 + WF。
- sync FAIL 候选不删，只保留 research，不直接切 runtime。
- 这版不改 demo，不改 entry，不碰下单链路。
EOF

(
  cd "$TMP_DIR" || exit 1
  zip -qr "$OUT_ZIP" .
)

echo "$OUT_ZIP"
exit 0
