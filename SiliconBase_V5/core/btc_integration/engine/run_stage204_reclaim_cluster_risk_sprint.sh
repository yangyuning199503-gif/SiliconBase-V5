#!/usr/bin/env bash
set -u

ROOT="$(cd "$(dirname "$0")" && pwd)"
DOWNLOADS="$HOME/Downloads"
if [ ! -d "$DOWNLOADS" ]; then
  DOWNLOADS="$ROOT/reports/research_raw"
fi
OUT_ZIP="$DOWNLOADS/stage204_reclaim_cluster_risk_sprint_latest.zip"
TMP_DIR="$ROOT/reports/research_raw/stage204_reclaim_cluster_risk_sprint_tmp"
LOG="$TMP_DIR/stage204_full_log.txt"
STATUS="$TMP_DIR/stage204_step_status.tsv"
SUMMARY="$TMP_DIR/stage204_reclaim_cluster_risk_sprint_latest.txt"

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

overall_status="OK"
rm -f "$OUT_ZIP"
cd "$ROOT"

if ! run_step py_compile "$PY" -m py_compile \
  "$ROOT/tools/stage145_reclaim_plateau_phase3.py" \
  "$ROOT/tools/stage120_event_window_frontier.py"; then
  overall_status="PARTIAL_FAIL"
fi

if ! run_step stage145_reclaim_plateau_phase3 "$PY" -u -m tools.stage145_reclaim_plateau_phase3 --project-dir "$ROOT"; then
  overall_status="PARTIAL_FAIL"
fi

if ! run_step stage120_event_window_frontier "$PY" -u "$ROOT/tools/stage120_event_window_frontier.py" --project-dir "$ROOT"; then
  overall_status="PARTIAL_FAIL"
fi

for f in \
  "$ROOT/reports/research_raw/stage90_mainline_event_alpha_matrix_latest.txt" \
  "$ROOT/reports/research_raw/stage90_mainline_event_alpha_matrix_latest.json" \
  "$ROOT/reports/research_raw/stage91_branch_event_alpha_matrix_latest.txt" \
  "$ROOT/reports/research_raw/stage91_branch_event_alpha_matrix_latest.json" \
  "$ROOT/reports/research_raw/stage145_reclaim_plateau_phase3_latest.txt" \
  "$ROOT/reports/research_raw/stage145_reclaim_plateau_phase3_latest.json" \
  "$ROOT/reports/research_raw/stage145_reclaim_plateau_phase3_manifest_latest.json" \
  "$ROOT/reports/research_raw/stage120_event_window_frontier_latest.txt" \
  "$ROOT/reports/research_raw/message_stack_backtest_latest.txt" \
  "$HOME/Downloads/okx_demo_report_latest.txt" \
  "$HOME/Downloads/branch_demo_report_latest.txt"; do
  copy_if_exists "$f" "$TMP_DIR/reports_snapshot" || true
done

cat > "$SUMMARY" <<EOF
Stage204 reclaim cluster risk sprint

- 对外只生成 1 个文件：stage204_reclaim_cluster_risk_sprint_latest.zip
- 当前目标：既然 stage203 证明 ETH reclaim_cluster 仍是最强，就不再浪费算力刷弱家族；直接围绕 reclaim 主簇做更快风险/预算邻域。
- 本轮动作：
  1) 主线冻结，继续保留 mainline_live_dynlev_fix8_lock18
  2) 分支只做 ETH reclaim_cluster plateau/risk sprint
  3) 事件/消息层继续保留为 risk layer，不升成裸 alpha
- overall_status=$overall_status

[step_status]
$(cat "$STATUS")

[notes]
- stage203 结论：drift/squeeze/reclaim_pair 都没打过 reclaim_cluster 主簇。
- 这轮只聚焦真强家族，先提效率。
EOF

(
  cd "$TMP_DIR"
  zip -qr "$OUT_ZIP" .
)

echo "$OUT_ZIP"
exit 0
