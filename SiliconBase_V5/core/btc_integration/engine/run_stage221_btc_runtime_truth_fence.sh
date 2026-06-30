#!/usr/bin/env bash
set -u

ROOT="$(cd "$(dirname "$0")" && pwd)"
DOWNLOADS="$HOME/Downloads"
if [ ! -d "$DOWNLOADS" ]; then
  DOWNLOADS="$ROOT/reports/research_raw"
fi
OUT_ZIP="$DOWNLOADS/stage221_btc_runtime_truth_fence_latest.zip"
TMP_DIR="$ROOT/reports/research_raw/stage221_btc_runtime_truth_fence_tmp"
LOG="$TMP_DIR/stage221_full_log.txt"
STATUS="$TMP_DIR/stage221_step_status.tsv"
SUMMARY="$TMP_DIR/stage221_btc_runtime_truth_fence_bundle_latest.txt"
SNAP="$TMP_DIR/reports_snapshot"
INV="$TMP_DIR/btc_file_inventory.tsv"
TODAY="$(date +%F)"

mkdir -p "$TMP_DIR"
rm -rf "$TMP_DIR"/*
mkdir -p "$SNAP"
: > "$LOG"
: > "$STATUS"
: > "$INV"

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

count_rows() {
  "$PY" - "$1" <<'PY'
import sys
from pathlib import Path
p = Path(sys.argv[1])
if not p.exists():
    print(0)
    raise SystemExit(0)
with p.open('r', encoding='utf-8', errors='ignore') as f:
    n = sum(1 for _ in f)
print(max(n-1, 0))
PY
}

extract_report_rows() {
  "$PY" - "$1" "$2" <<'PY'
import re, sys
from pathlib import Path
report = Path(sys.argv[1])
symbol = sys.argv[2].upper()
if not report.exists():
    print(0)
    raise SystemExit(0)
text = report.read_text(encoding='utf-8', errors='ignore')
# Prefer rows_total_after inside the symbol section.
pat = re.compile(rf"\[{re.escape(symbol)}\](.*?)(?:\n\[[A-Z]+\]|\Z)", re.S)
m = pat.search(text)
if m:
    mm = re.search(r"rows_total_after=(\d+)", m.group(1))
    if mm:
        print(int(mm.group(1)))
        raise SystemExit(0)
# Fallback: first rows_total_after in the report.
mm = re.search(r"rows_total_after=(\d+)", text)
print(int(mm.group(1)) if mm else 0)
PY
}

inventory_btc_files() {
  : > "$INV"
  while IFS= read -r path; do
    [ -z "$path" ] && continue
    rows="$(count_rows "$path" 2>/dev/null || echo 0)"
    printf '%s\t%s\n' "$rows" "$path" >> "$INV"
  done < <(find "$ROOT" -type f -name 'btc_15m.csv' | sort)
}

sync_btc_from_lock() {
  local lock_file="$1"
  [ -f "$lock_file" ] || return 1
  while IFS= read -r path; do
    [ -z "$path" ] && continue
    cp -f "$lock_file" "$path"
  done < <(find "$ROOT" -type f -name 'btc_15m.csv' | sort)
  return 0
}

refresh_all() {
  {
    echo "[refresh] refresh_mainline_raw.sh $TODAY"
    if [ -f "$ROOT/refresh_mainline_raw.sh" ]; then
      bash "$ROOT/refresh_mainline_raw.sh" "$TODAY" || true
    fi
    echo "[refresh] refresh_branch_research_raw.sh $TODAY"
    if [ -f "$ROOT/refresh_branch_research_raw.sh" ]; then
      bash "$ROOT/refresh_branch_research_raw.sh" "$TODAY" || true
    fi
    echo "[refresh] run_precheck.sh"
    if [ -f "$ROOT/run_precheck.sh" ]; then
      bash "$ROOT/run_precheck.sh" || true
    fi
    echo "[refresh] raw_data_guard --config $BRANCH_CFG"
    "$PY" -m tools.raw_data_guard --project-dir "$ROOT" --config "$BRANCH_CFG"
  } >> "$LOG" 2>&1
}

wait_for_reports() {
  local timeout_secs="$1"
  local started="$(date +%s)"
  local now main_r branch_r
  while :; do
    main_r="$(extract_report_rows "$HOME/Downloads/okx_demo_report_latest.txt" BTC 2>/dev/null || echo 0)"
    branch_r="$(extract_report_rows "$HOME/Downloads/branch_demo_report_latest.txt" BTC 2>/dev/null || echo 0)"
    if [ "$main_r" -gt 0 ] && [ "$branch_r" -gt 0 ]; then
      echo "$main_r $branch_r"
      return 0
    fi
    now="$(date +%s)"
    if [ $((now-started)) -ge "$timeout_secs" ]; then
      echo "$main_r $branch_r"
      return 1
    fi
    sleep 2
  done
}

wait_until_floor_or_timeout() {
  local floor="$1"
  local timeout_secs="$2"
  local started="$(date +%s)"
  local now main_r branch_r
  while :; do
    main_r="$(extract_report_rows "$HOME/Downloads/okx_demo_report_latest.txt" BTC 2>/dev/null || echo 0)"
    branch_r="$(extract_report_rows "$HOME/Downloads/branch_demo_report_latest.txt" BTC 2>/dev/null || echo 0)"
    echo "[$(date '+%F %T')] verify loop: main_btc_rows=$main_r branch_btc_rows=$branch_r floor=$floor" >> "$LOG"
    if [ "$main_r" -ge "$floor" ] && [ "$branch_r" -ge "$floor" ]; then
      echo "$main_r $branch_r"
      return 0
    fi
    now="$(date +%s)"
    if [ $((now-started)) -ge "$timeout_secs" ]; then
      echo "$main_r $branch_r"
      return 1
    fi
    sleep 5
  done
}

overall_status="OK"
system_gate="PASS"
final_truth_status="PENDING"
demos_state="running"
rm -f "$OUT_ZIP"
cd "$ROOT" || exit 1

run_step pause_main bash -lc "cd '$ROOT' && bash pause_okx_demo.sh" || overall_status="PARTIAL_FAIL"
run_step pause_branch bash -lc "cd '$ROOT' && bash pause_branch_demo.sh" || overall_status="PARTIAL_FAIL"

if ! run_step refresh_and_guard_all refresh_all; then
  overall_status="PARTIAL_FAIL"
  system_gate="FAIL"
fi

BTC_CANON="$ROOT/data/raw/btc_15m.csv"
BTC_LOCK="$TMP_DIR/btc_15m.lock.csv"
LOCK_ROWS=0
FLOOR_ROWS=0
if [ -f "$BTC_CANON" ]; then
  cp -f "$BTC_CANON" "$BTC_LOCK"
  LOCK_ROWS="$(count_rows "$BTC_LOCK" 2>/dev/null || echo 0)"
  FLOOR_ROWS=$(( LOCK_ROWS * 95 / 100 ))
fi
inventory_btc_files
printf 'lock_rows\t%s\n' "$LOCK_ROWS" >> "$INV"
printf 'floor_rows\t%s\n' "$FLOOR_ROWS" >> "$INV"

run_step sync_btc_copies_prestart sync_btc_from_lock "$BTC_LOCK" || overall_status="PARTIAL_FAIL"
run_step inventory_btc_prestart inventory_btc_files || true

run_step start_main bash -lc "cd '$ROOT' && bash start_okx_demo.sh" || overall_status="PARTIAL_FAIL"
run_step start_branch bash -lc "cd '$ROOT' && bash start_branch_demo.sh" || overall_status="PARTIAL_FAIL"

initial_pair="$(wait_for_reports 60 || true)"
MAIN_INIT="${initial_pair%% *}"
BRANCH_INIT="${initial_pair##* }"
CUR_RAW_ROWS="$(count_rows "$BTC_CANON" 2>/dev/null || echo 0)"
echo "initial_main_btc_rows=$MAIN_INIT" >> "$LOG"
echo "initial_branch_btc_rows=$BRANCH_INIT" >> "$LOG"
echo "current_raw_rows_after_start=$CUR_RAW_ROWS" >> "$LOG"

truth_ok=0
if [ "$MAIN_INIT" -ge "$FLOOR_ROWS" ] && [ "$BRANCH_INIT" -ge "$FLOOR_ROWS" ]; then
  truth_ok=1
fi

if [ "$truth_ok" -eq 0 ]; then
  echo "[$(date '+%F %T')] detected runtime truth drift after start; attempting live restore" >> "$LOG"
  run_step restore_btc_after_start sync_btc_from_lock "$BTC_LOCK" || overall_status="PARTIAL_FAIL"
  run_step inventory_btc_after_restore inventory_btc_files || true
  wait_pair_one="$(wait_until_floor_or_timeout "$FLOOR_ROWS" 90 || true)"
  MAIN_AFTER1="${wait_pair_one%% *}"
  BRANCH_AFTER1="${wait_pair_one##* }"
  echo "after_restore_main_btc_rows=$MAIN_AFTER1" >> "$LOG"
  echo "after_restore_branch_btc_rows=$BRANCH_AFTER1" >> "$LOG"
  if [ "$MAIN_AFTER1" -ge "$FLOOR_ROWS" ] && [ "$BRANCH_AFTER1" -ge "$FLOOR_ROWS" ]; then
    truth_ok=1
  else
    echo "[$(date '+%F %T')] live restore insufficient; doing one hard restart" >> "$LOG"
    run_step repause_main bash -lc "cd '$ROOT' && bash pause_okx_demo.sh" || overall_status="PARTIAL_FAIL"
    run_step repause_branch bash -lc "cd '$ROOT' && bash pause_branch_demo.sh" || overall_status="PARTIAL_FAIL"
    run_step resync_btc_copies_pre_restart sync_btc_from_lock "$BTC_LOCK" || overall_status="PARTIAL_FAIL"
    run_step restart_main bash -lc "cd '$ROOT' && bash start_okx_demo.sh" || overall_status="PARTIAL_FAIL"
    run_step restart_branch bash -lc "cd '$ROOT' && bash start_branch_demo.sh" || overall_status="PARTIAL_FAIL"
    wait_pair_two="$(wait_until_floor_or_timeout "$FLOOR_ROWS" 90 || true)"
    MAIN_AFTER2="${wait_pair_two%% *}"
    BRANCH_AFTER2="${wait_pair_two##* }"
    echo "after_restart_main_btc_rows=$MAIN_AFTER2" >> "$LOG"
    echo "after_restart_branch_btc_rows=$BRANCH_AFTER2" >> "$LOG"
    if [ "$MAIN_AFTER2" -ge "$FLOOR_ROWS" ] && [ "$BRANCH_AFTER2" -ge "$FLOOR_ROWS" ]; then
      truth_ok=1
    fi
  fi
fi

if [ "$truth_ok" -eq 1 ]; then
  final_truth_status="PASS"
else
  final_truth_status="FAIL"
  overall_status="PARTIAL_FAIL"
  system_gate="FAIL"
  run_step final_pause_main bash -lc "cd '$ROOT' && bash pause_okx_demo.sh" || true
  run_step final_pause_branch bash -lc "cd '$ROOT' && bash pause_branch_demo.sh" || true
  demos_state="stopped_due_to_btc_truth_fail"
fi

for f in \
  "$HOME/Downloads/okx_demo_report_latest.txt" \
  "$HOME/Downloads/branch_demo_report_latest.txt"; do
  copy_if_exists "$f" "$SNAP" || true
done

cat > "$SUMMARY" <<EOF2
Stage221 BTC runtime truth fence bundle

- 对外只生成 1 个文件：stage221_btc_runtime_truth_fence_latest.zip
- 这版先修 BTC raw，再验证 main/branch 报告里的 BTC rows_total_after 是否跟上；若仍漂移，就自动停 demo。
- overall_status=$overall_status
- system_gate=$system_gate
- final_truth_status=$final_truth_status
- demos_state=$demos_state

[key_metrics]
- btc_lock_rows=$LOCK_ROWS
- btc_floor_rows=$FLOOR_ROWS
- initial_main_btc_rows=$MAIN_INIT
- initial_branch_btc_rows=$BRANCH_INIT

[step_status]
$(cat "$STATUS")

[notes]
- 目标不是只修 raw，而是修“raw 已好但 runtime 仍吃旧 BTC”的问题。
- 若 final_truth_status=FAIL，本包里的 reports_snapshot + btc_file_inventory.tsv + stage221_full_log.txt 就是直接证据。
EOF2

(
  cd "$TMP_DIR" || exit 1
  zip -qr "$OUT_ZIP" .
)

echo "$OUT_ZIP"
exit 0
