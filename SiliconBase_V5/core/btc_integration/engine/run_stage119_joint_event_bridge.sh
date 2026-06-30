#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
PY="$ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
  PY="python3"
fi
RAW="$ROOT/reports/research_raw"
mkdir -p "$RAW"
OUT="$HOME/Downloads/stage119_joint_event_bridge_latest.zip"
PROGRESS="$RAW/stage119_progress_latest.txt"
: > "$PROGRESS"
log() {
  echo "[$(date '+%F %T')] $*" | tee -a "$PROGRESS"
}
log "stage119 start"
if [ -f "$ROOT/tools/stage75_mainline_event_state_lab.py" ]; then
  if "$PY" -m tools.stage75_mainline_event_state_lab --project-dir "$ROOT" >>"$PROGRESS" 2>&1; then
    log "stage75 OK"
  else
    log "WARN stage75 failed; continue with existing stage90/91"
  fi
else
  log "WARN stage75 tool missing; continue"
fi
"$PY" "$ROOT/tools/stage119_joint_event_bridge.py" --project-dir "$ROOT" >>"$PROGRESS" 2>&1
log "stage119 summarize OK"
TMPDIR="$(mktemp -d)"
cleanup() { rm -rf "$TMPDIR"; }
trap cleanup EXIT
cp "$RAW/stage119_summary_latest.txt" "$TMPDIR/" 2>/dev/null || true
cp "$PROGRESS" "$TMPDIR/" 2>/dev/null || true
for f in \
  stage75_mainline_event_state_latest.txt \
  stage75_mainline_event_state_latest.json \
  stage90_mainline_event_alpha_matrix_latest.txt \
  stage90_mainline_event_alpha_matrix_latest.json \
  stage91_branch_event_alpha_matrix_latest.txt \
  stage91_branch_event_alpha_matrix_latest.json; do
  if [ -f "$RAW/$f" ]; then cp "$RAW/$f" "$TMPDIR/"; fi
done
for f in okx_demo_report_latest.txt branch_demo_report_latest.txt; do
  if [ -f "$HOME/Downloads/$f" ]; then cp "$HOME/Downloads/$f" "$TMPDIR/"; elif [ -f "$ROOT/$f" ]; then cp "$ROOT/$f" "$TMPDIR/"; fi
done
rm -f "$OUT"
(
  cd "$TMPDIR"
  zip -q "$OUT" ./*
)
log "export $OUT"
echo "$OUT"
