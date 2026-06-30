#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
DL="$HOME/Downloads"
mkdir -p "$DL"
PROG="$DL/stage106_progress_latest.txt"
BARS="${1:-2}"
GRACE="${STAGE106_GRACE_SECONDS:-25}"
log(){ printf '%s | %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" | tee -a "$PROG" >/dev/null; }
: > "$PROG"
log "stage106 start | bars=$BARS"
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
log "wait complete; exporting"
bash "$ROOT/export_stage106_joint_runtime_watch.sh" | tee -a "$PROG"
log "stage106 done"
