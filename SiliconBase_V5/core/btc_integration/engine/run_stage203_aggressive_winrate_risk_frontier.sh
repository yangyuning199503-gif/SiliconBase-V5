#!/usr/bin/env bash

set -u

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
DOWNLOADS="$HOME/Downloads"
if [ ! -d "$DOWNLOADS" ]; then
  DOWNLOADS="$PROJECT_DIR/reports/research_raw"
fi
OUT_ZIP="$DOWNLOADS/stage203_aggressive_winrate_risk_frontier_latest.zip"
TMP_DIR="$PROJECT_DIR/reports/research_raw/stage203_aggressive_winrate_risk_frontier_tmp"
LOG="$TMP_DIR/stage203_full_log.txt"
STATUS="$TMP_DIR/stage203_step_status.tsv"
SUMMARY="$TMP_DIR/stage203_aggressive_winrate_risk_frontier_latest.txt"

mkdir -p "$TMP_DIR"
rm -rf "$TMP_DIR"/*
mkdir -p "$TMP_DIR/exports" "$TMP_DIR/reports_snapshot"
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

rm -f \
  "$DOWNLOADS/stage191_crosssignal_volmanaged_frontier_latest.zip" \
  "$DOWNLOADS/stage192_reclaim_pair_voltarget_frontier_latest.zip" \
  "$DOWNLOADS/stage198_aggressive_regime_switch_frontier_latest.zip" \
  "$OUT_ZIP"

cd "$PROJECT_DIR"

for step in \
  run_stage191_crosssignal_volmanaged_frontier.sh \
  run_stage192_reclaim_pair_voltarget_frontier.sh \
  run_stage198_aggressive_regime_switch_frontier.sh
 do
  if [ -f "$PROJECT_DIR/$step" ]; then
    if ! run_step "$step" bash "$PROJECT_DIR/$step"; then
      overall_status="PARTIAL_FAIL"
    fi
  else
    printf '%s\tMISS\n' "$step" >> "$STATUS"
    overall_status="PARTIAL_FAIL"
  fi
 done

for f in \
  "$DOWNLOADS/stage191_crosssignal_volmanaged_frontier_latest.zip" \
  "$DOWNLOADS/stage192_reclaim_pair_voltarget_frontier_latest.zip" \
  "$DOWNLOADS/stage198_aggressive_regime_switch_frontier_latest.zip"
 do
  if [ -f "$f" ]; then
    cp -f "$f" "$TMP_DIR/exports/"
    rm -f "$f"
  fi
 done

for f in \
  "$PROJECT_DIR/reports/research_raw/stage191_crosssignal_volmanaged_frontier_latest.txt" \
  "$PROJECT_DIR/reports/research_raw/stage191_crosssignal_volmanaged_frontier_latest.json" \
  "$PROJECT_DIR/reports/research_raw/stage191_crosssignal_volmanaged_frontier_manifest_latest.json" \
  "$PROJECT_DIR/reports/research_raw/stage192_reclaim_pair_voltarget_frontier_latest.txt" \
  "$PROJECT_DIR/reports/research_raw/stage192_reclaim_pair_voltarget_frontier_latest.json" \
  "$PROJECT_DIR/reports/research_raw/stage192_reclaim_pair_voltarget_frontier_manifest_latest.json" \
  "$PROJECT_DIR/reports/research_raw/stage198_aggressive_regime_switch_frontier_latest.txt" \
  "$PROJECT_DIR/reports/research_raw/stage198_aggressive_regime_switch_frontier_latest.json" \
  "$PROJECT_DIR/reports/research_raw/stage198_aggressive_regime_switch_frontier_manifest_latest.json" \
  "$PROJECT_DIR/reports/research_raw/stage90_mainline_event_alpha_matrix_latest.txt" \
  "$PROJECT_DIR/reports/research_raw/stage90_mainline_event_alpha_matrix_latest.json" \
  "$PROJECT_DIR/reports/research_raw/stage91_branch_event_alpha_matrix_latest.txt" \
  "$PROJECT_DIR/reports/research_raw/stage91_branch_event_alpha_matrix_latest.json" \
  "$PROJECT_DIR/reports/research_raw/message_stack_backtest_latest.txt" \
  "$PROJECT_DIR/reports/research_raw/stage120_event_window_frontier_latest.txt"
 do
  copy_if_exists "$f" "$TMP_DIR/reports_snapshot" || true
 done

cat > "$SUMMARY" <<EOF
Stage203 aggressive winrate/risk frontier

- 对外只生成 1 个文件：stage203_aggressive_winrate_risk_frontier_latest.zip
- 当前目标：更激进地测试“固定开仓节奏 + 严格止损 + 浮盈回撤止盈”风格的研究层候选
- 本轮封装策略：
  1) stage191 cross-signal vol-managed
  2) stage192 reclaim-pair voltarget
  3) stage198 aggressive regime-switch
- overall_status=$overall_status

[step_status]
$(cat "$STATUS")

[notes]
- 主线：继续围绕提高频次，但先看近2年 + WF，不再被 6年弱段硬压死。
- 分支：ETH/BTC/SOL 多空路径继续保留，不因一轮弱就删路。
- 事件/消息：继续做确认层，不把单条新闻直接抬成裸 alpha。
EOF

(
  cd "$TMP_DIR"
  zip -qr "$OUT_ZIP" .
)

echo "$OUT_ZIP"
exit 0
