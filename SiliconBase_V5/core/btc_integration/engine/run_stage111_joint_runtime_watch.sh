#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
RAW_DIR="$ROOT/reports/research_raw"
mkdir -p "$RAW_DIR"
PROG="$RAW_DIR/stage111_progress_latest.txt"
BARS="${1:-2}"
GRACE="${STAGE111_GRACE_SECONDS:-25}"
log(){ printf '%s | %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" | tee -a "$PROG" >/dev/null; }
: > "$PROG"
log "stage111 start | bars=$BARS"
log "switching branch demo to triple book preview"
bash "$ROOT/switch_branch_demo_to_triple_book.sh" | tee -a "$PROG" >/dev/null
WAIT_SECONDS="$(python3 - "$BARS" "$GRACE" <<'PY'
import sys, time
bars = int(sys.argv[1])
grace = int(sys.argv[2])
now = int(time.time())
bar = 900
next_boundary = ((now // bar) + 1) * bar
wait = (next_boundary - now) + grace + max(0, bars - 1) * bar
print(wait)
PY
)"
log "waiting_seconds=$WAIT_SECONDS"
sleep "$WAIT_SECONDS"
log "wait complete; exporting single file"
bash "$ROOT/export_stage111_joint_runtime_watch.sh" | tee -a "$PROG" >/dev/null
log "stage111 done"
printf '%s\n' "[OK] 只回传这个文件: ~/Downloads/stage111_joint_runtime_watch_latest.zip"
