#!/usr/bin/env bash
set -u

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

DOWNLOADS="$HOME/Downloads"
if [ ! -d "$DOWNLOADS" ]; then
  DOWNLOADS="$ROOT/reports/research_raw"
fi
OUT_ZIP="$DOWNLOADS/stage205_btc_truth_and_dual_rerun_latest.zip"
TMP_DIR="$ROOT/reports/research_raw/stage205_btc_truth_and_dual_rerun_tmp"
LOG="$TMP_DIR/stage205_full_log.txt"
STATUS="$TMP_DIR/stage205_step_status.tsv"
SUMMARY="$TMP_DIR/stage205_btc_truth_and_dual_rerun_latest.txt"

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
bootstrap_venv() {
  echo "Creating virtualenv .venv ..." >> "$LOG"
  rm -rf "$ROOT/.venv"
  python3 -m venv "$ROOT/.venv"
  PY="$ROOT/.venv/bin/python"
  "$PY" -m pip install --upgrade pip >/dev/null 2>&1
}
if [ ! -x "$PY" ] || ! "$PY" -c 'import sys; print(sys.executable)' >/dev/null 2>&1; then
  bootstrap_venv
fi
MARKER="$ROOT/.venv/.deps_installed"
if [ ! -f "$MARKER" ] || [ "$ROOT/requirements.txt" -nt "$MARKER" ]; then
  "$PY" -m pip install -r "$ROOT/requirements.txt" >/dev/null 2>&1 && touch "$MARKER"
fi

overall_status="OK"
rm -f "$OUT_ZIP"
rm -f "$DOWNLOADS/stage202_mainline_message_link_frontier_latest.zip" "$DOWNLOADS/stage204_reclaim_cluster_risk_sprint_latest.zip"

END_DATE="${1:-$(date +%F)}"

if ! run_step refresh_mainline_raw bash "$ROOT/refresh_mainline_raw.sh" "$END_DATE"; then
  overall_status="PARTIAL_FAIL"
fi
if ! run_step refresh_branch_raw bash "$ROOT/refresh_branch_research_raw.sh" "$END_DATE"; then
  overall_status="PARTIAL_FAIL"
fi
if ! run_step stage171_system_preflight bash "$ROOT/run_stage171_system_preflight.sh"; then
  overall_status="PARTIAL_FAIL"
fi

# raw rows snapshot
RAW_SUMMARY="$TMP_DIR/reports_snapshot/raw_rows_latest.txt"
if ! "$PY" - "$ROOT" > "$RAW_SUMMARY" 2>> "$LOG" <<'PY2'
from pathlib import Path
import pandas as pd
import sys
root = Path(sys.argv[1])
paths = {
    'btc': root/'data/raw/btc_15m.csv',
    'bnb': root/'data/raw/bnb_15m.csv',
    'eth': root/'data/raw/eth_15m.csv',
    'sol': root/'data/raw/sol_15m.csv',
}
print('raw_rows_latest')
print('===============')
for sym, path in paths.items():
    if not path.exists():
        print(f'- {sym}: missing | file={path}')
        continue
    try:
        df = pd.read_csv(path)
    except Exception as exc:
        print(f'- {sym}: read_failed | err={exc}')
        continue
    rows = len(df)
    if rows == 0:
        print(f'- {sym}: rows=0')
        continue
    col = 'time' if 'time' in df.columns else df.columns[0]
    ts = pd.to_datetime(df[col], errors='coerce')
    ts = ts.dropna()
    first = ts.iloc[0] if not ts.empty else None
    last = ts.iloc[-1] if not ts.empty else None
    print(f'- {sym}: rows={rows} first={first} last={last}')
PY2
then
  overall_status="PARTIAL_FAIL"
fi

# only rerun research if preflight summary says PASS
SYSTEM_PASS="0"
PRE_TXT="$ROOT/reports/research_raw/stage171_system_preflight_latest.txt"
if [ -f "$PRE_TXT" ] && grep -q '总状态: PASS' "$PRE_TXT"; then
  SYSTEM_PASS="1"
fi

if [ "$SYSTEM_PASS" = "1" ]; then
  if ! run_step stage202_mainline_message_link_frontier bash "$ROOT/run_stage202_mainline_message_link_frontier.sh"; then
    overall_status="PARTIAL_FAIL"
  fi
  if ! run_step stage204_reclaim_cluster_risk_sprint bash "$ROOT/run_stage204_reclaim_cluster_risk_sprint.sh"; then
    overall_status="PARTIAL_FAIL"
  fi
else
  printf '%s\tSKIP\n' 'stage202_mainline_message_link_frontier' >> "$STATUS"
  printf '%s\tSKIP\n' 'stage204_reclaim_cluster_risk_sprint' >> "$STATUS"
  echo "[$(date '+%F %T')] SKIP  stage202/stage204 because preflight not PASS" >> "$LOG"
  overall_status="REPAIR_FIRST"
fi

for f in \
  "$ROOT/reports/research_raw/stage171_system_preflight_latest.txt" \
  "$ROOT/reports/research_raw/stage90_mainline_event_alpha_matrix_latest.txt" \
  "$ROOT/reports/research_raw/stage90_mainline_event_alpha_matrix_latest.json" \
  "$ROOT/reports/research_raw/stage91_branch_event_alpha_matrix_latest.txt" \
  "$ROOT/reports/research_raw/stage91_branch_event_alpha_matrix_latest.json" \
  "$ROOT/reports/research_raw/stage120_event_window_frontier_latest.txt" \
  "$ROOT/reports/research_raw/stage145_reclaim_plateau_phase3_latest.txt" \
  "$ROOT/reports/research_raw/stage145_reclaim_plateau_phase3_latest.json" \
  "$ROOT/reports/research_raw/stage145_reclaim_plateau_phase3_manifest_latest.json" \
  "$ROOT/reports/research_raw/message_stack_backtest_latest.txt" \
  "$HOME/Downloads/okx_demo_report_latest.txt" \
  "$HOME/Downloads/branch_demo_report_latest.txt"; do
  copy_if_exists "$f" "$TMP_DIR/reports_snapshot" || true
done

copy_if_exists "$ROOT/reports/research_raw/stage171_system_preflight_artifacts/mainline_raw_guard.txt" "$TMP_DIR/reports_snapshot" || true
copy_if_exists "$ROOT/reports/research_raw/stage171_system_preflight_artifacts/branch_raw_guard.txt" "$TMP_DIR/reports_snapshot" || true
copy_if_exists "$ROOT/reports/research_raw/stage171_system_preflight_artifacts/bash_syntax.txt" "$TMP_DIR/reports_snapshot" || true
copy_if_exists "$ROOT/reports/research_raw/stage171_system_preflight_artifacts/py_compile.txt" "$TMP_DIR/reports_snapshot" || true

cat > "$SUMMARY" <<EOF2
Stage205 BTC truth + dual rerun

- 对外只生成 1 个文件：stage205_btc_truth_and_dual_rerun_latest.zip
- 先修 BTC raw 真相，再重跑：
  1) stage202 主线消息/技术联动
  2) stage204 ETH reclaim cluster sprint
- overall_status=$overall_status
- preflight_pass=$SYSTEM_PASS

[step_status]
$(cat "$STATUS")

[notes]
- 这版先把 BTC rows 缩短问题修真；主线和 BTC 分支口径没修真前，不继续相信它们的 frontier 结果。
- 若 preflight 仍非 PASS，本轮只输出修复诊断，不输出新的策略结论。
EOF2

(
  cd "$TMP_DIR"
  zip -qr "$OUT_ZIP" .
)

rm -f "$DOWNLOADS/stage202_mainline_message_link_frontier_latest.zip" "$DOWNLOADS/stage204_reclaim_cluster_risk_sprint_latest.zip"

echo "$OUT_ZIP"
exit 0
