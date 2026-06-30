#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
  PY="python3"
fi

OUTDIR="$ROOT/reports/research_raw"
DL="$HOME/Downloads"
mkdir -p "$OUTDIR" "$DL"

SUMMARY_TXT="$OUTDIR/stage172_joint_frontier_summary_latest.txt"
SUMMARY_JSON="$OUTDIR/stage172_joint_frontier_summary_latest.json"
RUN_TS="$(date '+%Y-%m-%d %H:%M:%S')"

log_step() {
  local name="$1"
  local cmd="$2"
  local logfile="$OUTDIR/stage172_${name}.log"
  echo "[RUN] $name" | tee -a "$SUMMARY_TXT"
  if bash -lc "$cmd" >"$logfile" 2>&1; then
    echo "PASS|$name|$logfile" >> "$OUTDIR/stage172_status.tmp"
    echo "- $name: PASS" >> "$SUMMARY_TXT"
  else
    echo "FAIL|$name|$logfile" >> "$OUTDIR/stage172_status.tmp"
    echo "- $name: FAIL" >> "$SUMMARY_TXT"
  fi
}

: > "$SUMMARY_TXT"
: > "$OUTDIR/stage172_status.tmp"
{
  echo "Stage172 联合前沿摘要"
  echo "时间: $RUN_TS"
  echo "根目录: $ROOT"
  echo
  echo "步骤状态:"
} >> "$SUMMARY_TXT"

steps=(
  "stage134_target_monthly_frontier|cd '$ROOT' && bash run_stage134_target_monthly_frontier.sh"
  "stage135_web_playbook_frontier|cd '$ROOT' && bash run_stage135_web_playbook_frontier.sh"
  "stage136_regime_plateau_frontier|cd '$ROOT' && bash run_stage136_regime_plateau_frontier.sh"
  "stage137_anchor_playbook_frontier|cd '$ROOT' && bash run_stage137_anchor_playbook_frontier.sh"
)

for item in "${steps[@]}"; do
  name="${item%%|*}"
  cmd="${item#*|}"
  if [ -f "$ROOT/run_${name}.sh" ] || [ -f "$ROOT/${name}.sh" ]; then
    log_step "$name" "$cmd"
  else
    echo "SKIP|$name|missing" >> "$OUTDIR/stage172_status.tmp"
    echo "- $name: SKIP (missing)" >> "$SUMMARY_TXT"
  fi
done

"$PY" - <<'PY2' "$OUTDIR/stage172_status.tmp" "$SUMMARY_JSON" "$RUN_TS"
from pathlib import Path
import json, sys
status_path = Path(sys.argv[1])
out_json = Path(sys.argv[2])
run_ts = sys.argv[3]
rows = []
for line in status_path.read_text(encoding='utf-8').splitlines():
    if not line.strip():
        continue
    state, name, detail = line.split('|', 2)
    rows.append({'state': state, 'name': name, 'detail': detail})
out_json.write_text(json.dumps({'run_ts': run_ts, 'steps': rows}, ensure_ascii=False, indent=2), encoding='utf-8')
print(out_json)
PY2

TMPDIR="$(mktemp -d)"
cleanup() { rm -rf "$TMPDIR" "$OUTDIR/stage172_status.tmp"; }
trap cleanup EXIT

for f in \
  "$SUMMARY_TXT" \
  "$SUMMARY_JSON" \
  "$OUTDIR/stage90_mainline_event_alpha_matrix_latest.txt" \
  "$OUTDIR/stage90_mainline_event_alpha_matrix_latest.json" \
  "$OUTDIR/stage91_branch_event_alpha_matrix_latest.txt" \
  "$OUTDIR/stage91_branch_event_alpha_matrix_latest.json" \
  "$OUTDIR/stage134_target_monthly_frontier_latest.txt" \
  "$OUTDIR/stage134_target_monthly_frontier_latest.json" \
  "$OUTDIR/stage134_target_monthly_frontier_manifest_latest.json" \
  "$OUTDIR/stage135_web_playbook_frontier_latest.txt" \
  "$OUTDIR/stage135_web_playbook_frontier_latest.json" \
  "$OUTDIR/stage135_web_playbook_frontier_manifest_latest.json" \
  "$OUTDIR/stage136_regime_plateau_frontier_latest.txt" \
  "$OUTDIR/stage136_regime_plateau_frontier_latest.json" \
  "$OUTDIR/stage136_regime_plateau_manifest_latest.json" \
  "$OUTDIR/stage137_anchor_playbook_frontier_latest.txt" \
  "$OUTDIR/stage137_anchor_playbook_frontier_latest.json" \
  "$OUTDIR/stage137_anchor_playbook_manifest_latest.json" \
  "$OUTDIR/stage120_event_window_frontier_latest.txt" \
  "$OUTDIR/event_window_sweep_latest.txt" \
  "$OUTDIR/event_window_walkforward_latest.txt" \
  "$DL/okx_demo_report_latest.txt" \
  "$DL/branch_demo_report_latest.txt"; do
  [ -f "$f" ] && cp -f "$f" "$TMPDIR/"
done

for logf in "$OUTDIR"/stage172_*.log; do
  [ -f "$logf" ] || continue
  cp -f "$logf" "$TMPDIR/"
done

OUTZIP="$DL/stage172_joint_frontier_bundle_latest.zip"
"$PY" - <<'PY3' "$OUTZIP" "$TMPDIR"
from pathlib import Path
import sys, zipfile
out = Path(sys.argv[1]).expanduser()
tmp = Path(sys.argv[2])
out.parent.mkdir(parents=True, exist_ok=True)
files = sorted([p for p in tmp.iterdir() if p.is_file()])
if out.exists():
    out.unlink()
with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
    for p in files:
        zf.write(p, arcname=p.name)
print(out)
PY3

echo "[OK] stage172_joint_frontier_bundle_done"
