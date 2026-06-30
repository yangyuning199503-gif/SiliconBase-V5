#!/usr/bin/env bash
set -u

ROOT="$(cd "$(dirname "$0")" && pwd)"
DOWNLOADS="$HOME/Downloads"
if [ ! -d "$DOWNLOADS" ]; then
  DOWNLOADS="$ROOT/reports/research_raw"
fi
OUT_ZIP="$DOWNLOADS/stage206_message_reclaim_sync_frontier_latest.zip"
TMP_DIR="$ROOT/reports/research_raw/stage206_message_reclaim_sync_frontier_tmp"
LOG="$TMP_DIR/stage206_full_log.txt"
STATUS="$TMP_DIR/stage206_step_status.tsv"
SUMMARY="$TMP_DIR/stage206_message_reclaim_sync_frontier_latest.txt"

mkdir -p "$TMP_DIR"
rm -rf "$TMP_DIR"/*
mkdir -p "$TMP_DIR/reports_snapshot"
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

MAIN_CFG="config.yml"
BRANCH_CFG="config_shortwave_triple_book_preview.yml"
if [ -f "$ROOT/config_shortwave_triple_book_stage133.yml" ]; then
  BRANCH_CFG="config_shortwave_triple_book_stage133.yml"
elif [ -f "$ROOT/config_shortwave_triple_book_stage113.yml" ]; then
  BRANCH_CFG="config_shortwave_triple_book_stage113.yml"
fi

overall_status="OK"
system_gate="PASS"
rm -f "$OUT_ZIP"
cd "$ROOT"

if ! run_step py_compile "$PY" -m py_compile \
  "$ROOT/tools/stage159_message_confirm_reclaim_cluster_frontier.py" \
  "$ROOT/tools/stage120_event_window_frontier.py" \
  "$ROOT/tools/raw_data_guard.py" \
  "$ROOT/tools/repair_raw_from_snapshots.py"; then
  overall_status="PARTIAL_FAIL"
  system_gate="FAIL"
fi

if ! run_step mainline_raw_repair_guard bash -lc "cd '$ROOT' && '$PY' -m tools.repair_raw_from_snapshots --project-dir . --config '$MAIN_CFG' >/dev/null || true && '$PY' -m tools.raw_data_guard --project-dir . --config '$MAIN_CFG'"; then
  overall_status="PARTIAL_FAIL"
  system_gate="FAIL"
fi

if ! run_step branch_raw_repair_guard bash -lc "cd '$ROOT' && '$PY' -m tools.repair_raw_from_snapshots --project-dir . --config '$BRANCH_CFG' >/dev/null || true && '$PY' -m tools.raw_data_guard --project-dir . --config '$BRANCH_CFG'"; then
  overall_status="PARTIAL_FAIL"
  system_gate="FAIL"
fi

if [ "$system_gate" = "PASS" ]; then
  if ! run_step stage159_message_confirm_reclaim_cluster_frontier "$PY" -u -m tools.stage159_message_confirm_reclaim_cluster_frontier --project-dir "$ROOT"; then
    overall_status="PARTIAL_FAIL"
  fi
  if ! run_step stage120_event_window_frontier "$PY" -u "$ROOT/tools/stage120_event_window_frontier.py" --project-dir "$ROOT"; then
    overall_status="PARTIAL_FAIL"
  fi
else
  printf '%s\tSKIP\n' stage159_message_confirm_reclaim_cluster_frontier >> "$STATUS"
  printf '%s\tSKIP\n' stage120_event_window_frontier >> "$STATUS"
  echo "[$(date '+%F %T')] SKIP  research_frontier because system_gate=FAIL" >> "$LOG"
fi

for f in \
  "$ROOT/reports/research_raw/stage90_mainline_event_alpha_matrix_latest.txt" \
  "$ROOT/reports/research_raw/stage90_mainline_event_alpha_matrix_latest.json" \
  "$ROOT/reports/research_raw/stage91_branch_event_alpha_matrix_latest.txt" \
  "$ROOT/reports/research_raw/stage91_branch_event_alpha_matrix_latest.json" \
  "$ROOT/reports/research_raw/stage159_message_confirm_reclaim_cluster_frontier_latest.txt" \
  "$ROOT/reports/research_raw/stage159_message_confirm_reclaim_cluster_frontier_latest.json" \
  "$ROOT/reports/research_raw/stage159_message_confirm_reclaim_cluster_frontier_manifest_latest.json" \
  "$ROOT/reports/research_raw/stage120_event_window_frontier_latest.txt" \
  "$ROOT/reports/research_raw/message_stack_backtest_latest.txt" \
  "$HOME/Downloads/okx_demo_report_latest.txt" \
  "$HOME/Downloads/branch_demo_report_latest.txt"; do
  copy_if_exists "$f" "$TMP_DIR/reports_snapshot" || true
done

cat > "$SUMMARY" <<EOF2
Stage206 message reclaim sync frontier

- 对外只生成 1 个文件：stage206_message_reclaim_sync_frontier_latest.zip
- 先过轻量系统门：py_compile + raw repair/guard
- 系统门通过后，再跑：stage159_message_confirm_reclaim_cluster_frontier + stage120_event_window_frontier
- 主线目标：继续围绕 fix8_lock18 做温和提频与消息确认
- 分支目标：继续围绕 ETH reclaim 主簇，同时保留 squeeze / short / BTC / SOL 联动路径
- overall_status=$overall_status
- system_gate=$system_gate

[step_status]
$(cat "$STATUS")

[notes]
- 这版不改 demo runtime，不做下单链路动作；先把消息层与 reclaim 主簇的 research 口径继续刷真。
- 若 system_gate 失败，本轮只保留诊断，不继续信任 frontier 结果。
EOF2

(
  cd "$TMP_DIR"
  zip -qr "$OUT_ZIP" .
)

echo "$OUT_ZIP"
exit 0
