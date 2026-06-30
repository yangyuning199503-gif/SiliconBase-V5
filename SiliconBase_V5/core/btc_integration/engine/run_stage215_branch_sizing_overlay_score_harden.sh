#!/usr/bin/env bash
set -u

ROOT="$(cd "$(dirname "$0")" && pwd)"
DOWNLOADS="$HOME/Downloads"
if [ ! -d "$DOWNLOADS" ]; then
  DOWNLOADS="$ROOT/reports/research_raw"
fi
OUT_ZIP="$DOWNLOADS/stage215_branch_sizing_overlay_score_harden_latest.zip"
TMP_DIR="$ROOT/reports/research_raw/stage215_branch_sizing_overlay_score_harden_tmp"
LOG="$TMP_DIR/stage215_full_log.txt"
STATUS="$TMP_DIR/stage215_step_status.tsv"
SUMMARY="$TMP_DIR/stage215_branch_sizing_overlay_score_harden_bundle_latest.txt"
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
rm -f "$OUT_ZIP"
cd "$ROOT" || exit 1

if ! run_step py_compile "$PY" -m py_compile \
  "$ROOT/tools/message_stack_backtest.py" \
  "$ROOT/tools/stage211_future_event_runtime_bridge_frontier.py" \
  "$ROOT/tools/stage212_message_sizing_overlay_frontier.py" \
  "$ROOT/tools/stage213_branch_sizing_overlay_frontier.py" \
  "$ROOT/tools/stage215_branch_sizing_overlay_score_harden.py" \
  "$ROOT/tools/stage46_aggressive_lab.py" \
  "$ROOT/tools/stage59_structural_lab.py" \
  "$ROOT/tools/stage90_event_alpha_matrix.py" \
  "$ROOT/tools/raw_data_guard.py" \
  "$ROOT/tools/repair_raw_from_snapshots.py"; then
  overall_status="PARTIAL_FAIL"
  system_gate="FAIL"
fi

if ! run_step branch_raw_repair_guard bash -lc "cd '$ROOT' && '$PY' -m tools.repair_raw_from_snapshots --project-dir . --config '$BRANCH_CFG' >/dev/null || true && '$PY' -m tools.raw_data_guard --project-dir . --config '$BRANCH_CFG'"; then
  overall_status="PARTIAL_FAIL"
  system_gate="FAIL"
fi

OUT_TXT="$ROOT/reports/research_raw/stage215_branch_sizing_overlay_score_harden_latest.txt"
OUT_JSON="$ROOT/reports/research_raw/stage215_branch_sizing_overlay_score_harden_latest.json"
if [ "$system_gate" = "PASS" ]; then
  if ! run_step stage215_branch_sizing_overlay_score_harden "$PY" -u "$ROOT/tools/stage215_branch_sizing_overlay_score_harden.py" --project-dir "$ROOT" --out-txt "$OUT_TXT" --out-json "$OUT_JSON"; then
    overall_status="PARTIAL_FAIL"
  fi
else
  printf '%s\tSKIP\n' stage215_branch_sizing_overlay_score_harden >> "$STATUS"
  echo "[$(date '+%F %T')] SKIP  stage215 because system_gate=FAIL" >> "$LOG"
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
Stage215 branch sizing overlay score harden bundle

- 对外只生成 1 个文件：stage215_branch_sizing_overlay_score_harden_latest.zip
- 这版不改 entry，也不改 demo；只修 branch overlay 评分器的样本扭曲。
- overall_status=$overall_status
- system_gate=$system_gate

[step_status]
$(cat "$STATUS")

[notes]
- 修 3 个问题：recent 月化按极短交易跨度爆表、PF=999 小样本拉歪排序、leaderboard 只汇总“每个候选自己的 best”而不是全局聚合。
- 这版改成：24个月固定窗口月化 + PF上限 + 样本惩罚 + 全局聚合再决定是否推荐 runtime preview。
EOF2

(
  cd "$TMP_DIR" || exit 1
  zip -qr "$OUT_ZIP" .
)

echo "$OUT_ZIP"
exit 0
