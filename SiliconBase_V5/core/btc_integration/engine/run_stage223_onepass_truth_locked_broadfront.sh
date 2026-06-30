#!/usr/bin/env bash
set -u

ROOT="$(cd "$(dirname "$0")" && pwd)"
DOWNLOADS="$HOME/Downloads"
if [ ! -d "$DOWNLOADS" ]; then
  DOWNLOADS="$ROOT/reports/research_raw"
fi
OUT_ZIP="$DOWNLOADS/stage223_onepass_truth_locked_broadfront_latest.zip"
TMP_DIR="$ROOT/reports/research_raw/stage223_onepass_truth_locked_broadfront_tmp"
LOG="$TMP_DIR/stage223_full_log.txt"
STATUS="$TMP_DIR/stage223_step_status.tsv"
SUMMARY="$TMP_DIR/stage223_onepass_truth_locked_broadfront_bundle_latest.txt"
EXTRACT_DIR="$TMP_DIR/extracted"
SNAP="$TMP_DIR/reports_snapshot"

mkdir -p "$TMP_DIR" "$EXTRACT_DIR" "$SNAP"
rm -rf "$TMP_DIR"/*
mkdir -p "$EXTRACT_DIR" "$SNAP"
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
  local dst="$2"
  if [ -f "$src" ]; then
    cp -f "$src" "$dst"
    return 0
  fi
  return 1
}

PY="$ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
  PY="python3"
fi

extract_from_zip() {
  local zip_path="$1"
  local pattern="$2"
  local out_dir="$3"
  "$PY" - "$zip_path" "$pattern" "$out_dir" <<'PY'
import fnmatch, sys, zipfile
from pathlib import Path
zip_path = Path(sys.argv[1])
pattern = sys.argv[2]
out_dir = Path(sys.argv[3])
out_dir.mkdir(parents=True, exist_ok=True)
if not zip_path.exists():
    raise SystemExit(1)
with zipfile.ZipFile(zip_path) as z:
    matched = [n for n in z.namelist() if fnmatch.fnmatch(n, pattern)]
    for name in matched:
        if name.endswith('/'):
            continue
        target = out_dir / Path(name).name
        target.write_bytes(z.read(name))
PY
}

read_kv_from_text() {
  local file="$1"
  local key="$2"
  if [ ! -f "$file" ]; then
    echo ""
    return 0
  fi
  grep -E "^[[:space:]-]*${key}=" "$file" | tail -n 1 | sed -E 's/^[[:space:]-]*[^=]+=//' || true
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
pat = re.compile(rf"\[{re.escape(symbol)}\](.*?)(?:\n\[[A-Z]+\]|\Z)", re.S)
m = pat.search(text)
if m:
    mm = re.search(r"rows_total_after=(\d+)", m.group(1))
    if mm:
        print(int(mm.group(1)))
        raise SystemExit(0)
mm = re.search(r"rows_total_after=(\d+)", text)
print(int(mm.group(1)) if mm else 0)
PY
}

overall_status="OK"
stage221_truth="UNKNOWN"
stage219_status="NOT_RUN"
stage217_status="NOT_RUN"
stage217_gate="UNKNOWN"

run_optional_stage() {
  local step_name="$1"
  local script_name="$2"
  if [ ! -f "$ROOT/$script_name" ]; then
    printf '%s\tMISSING\n' "$step_name" >> "$STATUS"
    echo "[$(date '+%F %T')] MISSING $script_name" >> "$LOG"
    return 2
  fi
  if ! run_step "$step_name" bash -lc "cd '$ROOT' && bash '$script_name'"; then
    overall_status="PARTIAL_FAIL"
    return 1
  fi
  return 0
}

# stage221
run_optional_stage stage221_truth_fence run_stage221_btc_runtime_truth_fence.sh || true
STAGE221_ZIP="$HOME/Downloads/stage221_btc_runtime_truth_fence_latest.zip"
if [ ! -f "$STAGE221_ZIP" ]; then
  STAGE221_ZIP="$ROOT/reports/research_raw/stage221_btc_runtime_truth_fence_latest.zip"
fi
copy_if_exists "$STAGE221_ZIP" "$TMP_DIR/stage221_btc_runtime_truth_fence_latest.zip" || true
if [ -f "$STAGE221_ZIP" ]; then
  extract_from_zip "$STAGE221_ZIP" "*stage221_btc_runtime_truth_fence_bundle_latest.txt" "$EXTRACT_DIR" || true
  extract_from_zip "$STAGE221_ZIP" "*okx_demo_report_latest.txt" "$SNAP" || true
  extract_from_zip "$STAGE221_ZIP" "*branch_demo_report_latest.txt" "$SNAP" || true
fi
STAGE221_SUMMARY="$EXTRACT_DIR/stage221_btc_runtime_truth_fence_bundle_latest.txt"
stage221_truth="$(read_kv_from_text "$STAGE221_SUMMARY" "final_truth_status")"
[ -z "$stage221_truth" ] && stage221_truth="UNKNOWN"

# stage219
if [ "$stage221_truth" = "PASS" ]; then
  if run_optional_stage stage219_truth_locked_frontier run_stage219_truth_locked_seed_frontier.sh; then
    stage219_status="RAN"
  else
    stage219_status="FAIL"
  fi
else
  printf '%s\tSKIP\n' stage219_truth_locked_frontier >> "$STATUS"
  echo "[$(date '+%F %T')] SKIP  stage219 because stage221 final_truth_status=$stage221_truth" >> "$LOG"
  stage219_status="SKIP"
  overall_status="PARTIAL_FAIL"
fi

STAGE219_ZIP="$HOME/Downloads/stage219_truth_locked_seed_frontier_latest.zip"
if [ ! -f "$STAGE219_ZIP" ]; then
  STAGE219_ZIP="$ROOT/reports/research_raw/stage219_truth_locked_seed_frontier_latest.zip"
fi
copy_if_exists "$STAGE219_ZIP" "$TMP_DIR/stage219_truth_locked_seed_frontier_latest.zip" || true
if [ -f "$STAGE219_ZIP" ]; then
  extract_from_zip "$STAGE219_ZIP" "*stage219_truth_locked_seed_frontier_bundle_latest.txt" "$EXTRACT_DIR" || true
  extract_from_zip "$STAGE219_ZIP" "*stage219_truth_locked_seed_frontier_latest.txt" "$SNAP" || true
  extract_from_zip "$STAGE219_ZIP" "*stage91_branch_event_alpha_matrix_latest.txt" "$SNAP" || true
fi

# stage217
if [ "$stage221_truth" = "PASS" ]; then
  if run_optional_stage stage217_multiregime_broadfront run_stage217_multiregime_broadfront_frontier.sh; then
    stage217_status="RAN"
  else
    stage217_status="FAIL"
  fi
else
  printf '%s\tSKIP\n' stage217_multiregime_broadfront >> "$STATUS"
  echo "[$(date '+%F %T')] SKIP  stage217 because stage221 final_truth_status=$stage221_truth" >> "$LOG"
  stage217_status="SKIP"
  overall_status="PARTIAL_FAIL"
fi

STAGE217_ZIP="$HOME/Downloads/stage217_multiregime_broadfront_frontier_latest.zip"
if [ ! -f "$STAGE217_ZIP" ]; then
  STAGE217_ZIP="$ROOT/reports/research_raw/stage217_multiregime_broadfront_frontier_latest.zip"
fi
copy_if_exists "$STAGE217_ZIP" "$TMP_DIR/stage217_multiregime_broadfront_frontier_latest.zip" || true
if [ -f "$STAGE217_ZIP" ]; then
  extract_from_zip "$STAGE217_ZIP" "*stage217_multiregime_broadfront_frontier_bundle_latest.txt" "$EXTRACT_DIR" || true
  extract_from_zip "$STAGE217_ZIP" "*stage217_multiregime_broadfront_frontier_latest.txt" "$SNAP" || true
fi
STAGE217_SUMMARY="$EXTRACT_DIR/stage217_multiregime_broadfront_frontier_bundle_latest.txt"
stage217_gate="$(read_kv_from_text "$STAGE217_SUMMARY" "system_gate")"
[ -z "$stage217_gate" ] && stage217_gate="UNKNOWN"

MAIN_REPORT="$HOME/Downloads/okx_demo_report_latest.txt"
BRANCH_REPORT="$HOME/Downloads/branch_demo_report_latest.txt"
MAIN_BTC_ROWS="$(extract_report_rows "$MAIN_REPORT" BTC 2>/dev/null || echo 0)"
BRANCH_BTC_ROWS="$(extract_report_rows "$BRANCH_REPORT" BTC 2>/dev/null || echo 0)"
copy_if_exists "$MAIN_REPORT" "$SNAP/okx_demo_report_latest.txt" || true
copy_if_exists "$BRANCH_REPORT" "$SNAP/branch_demo_report_latest.txt" || true

cat > "$SUMMARY" <<EOF
Stage223 one-pass truth-locked broadfront bundle

- 对外只生成 1 个文件：stage223_onepass_truth_locked_broadfront_latest.zip
- 这版把“修 BTC runtime 真相 + truth-locked 审计 + broadfront frontier”合成一次执行。
- overall_status=$overall_status
- stage221_final_truth_status=$stage221_truth
- stage219_status=$stage219_status
- stage217_status=$stage217_status
- stage217_system_gate=$stage217_gate
- current_main_btc_rows_total_after=$MAIN_BTC_ROWS
- current_branch_btc_rows_total_after=$BRANCH_BTC_ROWS

[step_status]
$(cat "$STATUS")

[notes]
- 目标是减少来回上传，不是直接改 demo 锚点。
- stage221 不过，就不再盲跑 stage219 / stage217。
- 只要 stage221 过，这版会自动续跑 truth-locked 审计和 broadfront research。
EOF

(
  cd "$TMP_DIR" || exit 1
  zip -qr "$OUT_ZIP" .
)

echo "$OUT_ZIP"
exit 0
