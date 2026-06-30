#!/usr/bin/env bash
set -u

ROOT="$(cd "$(dirname "$0")" && pwd)"
DOWNLOADS="$HOME/Downloads"
if [ ! -d "$DOWNLOADS" ]; then
  DOWNLOADS="$ROOT/reports/research_raw"
fi
OUT_ZIP="$DOWNLOADS/stage224_strategy_optimize_now_latest.zip"
TMP_DIR="$ROOT/reports/research_raw/stage224_strategy_optimize_now_tmp"
LOG="$TMP_DIR/stage224_full_log.txt"
STATUS="$TMP_DIR/stage224_step_status.tsv"
SUMMARY="$TMP_DIR/stage224_strategy_optimize_now_bundle_latest.txt"
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

overall_status="OK"
system_gate="PASS"
cd "$ROOT" || exit 1

if ! run_step py_compile "$PY" -m py_compile \
  "$ROOT/tools/stage93_frequency_accel.py" \
  "$ROOT/tools/stage99_mainline_frequency_push.py" \
  "$ROOT/tools/stage224_strategy_optimize_now.py" \
  "$ROOT/tools/stage223_truth_locked_broadfront_frontier.py" \
  "$ROOT/tools/stage212_message_sizing_overlay_frontier.py"; then
  overall_status="PARTIAL_FAIL"
  system_gate="FAIL"
fi

RAW="$ROOT/reports/research_raw"
mkdir -p "$RAW"
STAGE90_JSON="$RAW/stage90_mainline_event_alpha_matrix_latest.json"
STAGE91_JSON="$RAW/stage91_branch_event_alpha_matrix_latest.json"
STAGE93_JSON="$RAW/stage93_frequency_accel_latest.json"

if [ "$system_gate" = "PASS" ]; then
  if [ ! -f "$STAGE90_JSON" ] || [ ! -f "$STAGE91_JSON" ]; then
    if ! run_step stage90_stage91_matrix "$PY" -u -m tools.stage90_event_alpha_matrix --project-dir "$ROOT"; then
      overall_status="PARTIAL_FAIL"
      system_gate="FAIL"
    fi
  else
    printf '%s\tREUSE\n' stage90_stage91_matrix >> "$STATUS"
  fi
fi

if [ "$system_gate" = "PASS" ]; then
  if [ ! -f "$STAGE93_JSON" ]; then
    if ! run_step stage93_frequency_accel "$PY" -u -m tools.stage93_frequency_accel --project-dir "$ROOT"; then
      overall_status="PARTIAL_FAIL"
      system_gate="FAIL"
    fi
  else
    printf '%s\tREUSE\n' stage93_frequency_accel >> "$STATUS"
  fi
fi

if [ "$system_gate" = "PASS" ]; then
  if ! run_step stage99_mainline_frequency_push "$PY" -u -m tools.stage99_mainline_frequency_push --project-dir "$ROOT"; then
    overall_status="PARTIAL_FAIL"
  fi
  if ! run_step stage212_message_sizing_overlay bash -lc "cd '$ROOT' && bash run_stage212_message_sizing_overlay_frontier.sh"; then
    overall_status="PARTIAL_FAIL"
  fi
  STAGE223_TXT="$ROOT/reports/research_raw/stage223_truth_locked_broadfront_frontier_latest.txt"
  if [ "${FORCE_STAGE223:-0}" = "1" ] || [ ! -f "$STAGE223_TXT" ]; then
    if ! run_step stage223_truth_locked_broadfront bash -lc "cd '$ROOT' && bash run_stage223_truth_locked_broadfront_frontier.sh"; then
      overall_status="PARTIAL_FAIL"
    fi
  else
    printf '%s	REUSE
' stage223_truth_locked_broadfront >> "$STATUS"
    echo "[$(date '+%F %T')] REUSE stage223_truth_locked_broadfront_frontier_latest.txt" >> "$LOG"
  fi
  if ! run_step stage224_summary "$PY" -u "$ROOT/tools/stage224_strategy_optimize_now.py" --project-dir "$ROOT"; then
    overall_status="PARTIAL_FAIL"
  fi
else
  printf '%s\tSKIP\n' stage99_mainline_frequency_push >> "$STATUS"
  printf '%s\tSKIP\n' stage212_message_sizing_overlay >> "$STATUS"
  printf '%s\tSKIP\n' stage223_truth_locked_broadfront >> "$STATUS"
  printf '%s\tSKIP\n' stage224_summary >> "$STATUS"
  echo "[$(date '+%F %T')] SKIP  optimize because system_gate=FAIL" >> "$LOG"
fi

for f in \
  "$ROOT/reports/research_raw/stage99_mainline_frequency_push_latest.txt" \
  "$ROOT/reports/research_raw/stage99_mainline_frequency_push_latest.json" \
  "$ROOT/reports/research_raw/stage212_message_sizing_overlay_frontier_latest.txt" \
  "$ROOT/reports/research_raw/stage212_message_sizing_overlay_frontier_latest.json" \
  "$ROOT/reports/research_raw/stage223_truth_locked_broadfront_frontier_latest.txt" \
  "$ROOT/reports/research_raw/stage223_truth_locked_broadfront_frontier_latest.json" \
  "$ROOT/reports/research_raw/stage224_strategy_optimize_now_latest.txt" \
  "$ROOT/reports/research_raw/stage224_strategy_optimize_now_latest.json" \
  "$HOME/Downloads/okx_demo_report_latest.txt" \
  "$HOME/Downloads/branch_demo_report_latest.txt"; do
  copy_if_exists "$f" "$SNAP" || true
done

cat > "$SUMMARY" <<EOF
Stage224 strategy optimize now bundle

- 对外只生成 1 个文件：stage224_strategy_optimize_now_latest.zip
- 这版把“主线提频 + 主线消息仓位层 + 分支 truth-locked broadfront”合成一次回测。
- overall_status=$overall_status
- system_gate=$system_gate

[step_status]
$(cat "$STATUS")

[notes]
- 6年必报，但排序继续先看近2年 + WF。
- 主线继续提频，但不靠纯放阈值；消息面只做仓位覆盖层。
- 分支保持 BTC / ETH / SOL 多路径，不因为一轮不达标就删路。
- 这版不改 demo，不改下单链路，只做优化回测和统一摘要。
EOF

(
  cd "$TMP_DIR" || exit 1
  zip -qr "$OUT_ZIP" .
)

echo "$OUT_ZIP"
exit 0
