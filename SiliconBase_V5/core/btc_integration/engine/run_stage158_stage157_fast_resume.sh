#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PY="$ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
  PY="python3"
fi

mkdir -p "$ROOT/reports/research_raw" "$HOME/Downloads"

"$PY" -m py_compile \
  "$ROOT/tools/stage157_regime_playbook_accel_frontier.py" \
  "$ROOT/tools/stage158_stage157_fast_resume.py"

MAIN_JSON="$ROOT/reports/research_raw/stage90_mainline_event_alpha_matrix_latest.json"
BRANCH_JSON="$ROOT/reports/research_raw/stage91_branch_event_alpha_matrix_latest.json"
if [ -f "$MAIN_JSON" ] && [ -f "$BRANCH_JSON" ]; then
  "$PY" -u -m tools.stage158_stage157_fast_resume --project-dir "$ROOT"
else
  "$PY" -u -m tools.stage157_regime_playbook_accel_frontier --project-dir "$ROOT"
fi

if [ -f "$ROOT/tools/stage120_event_window_frontier.py" ]; then
  "$PY" -u "$ROOT/tools/stage120_event_window_frontier.py" --project-dir "$ROOT"
fi

OUT="$HOME/Downloads/stage157_regime_playbook_accel_frontier_latest.zip"
TMPDIR="$(mktemp -d)"
cleanup() { rm -rf "$TMPDIR"; }
trap cleanup EXIT

for f in \
  "$ROOT/reports/research_raw/stage90_mainline_event_alpha_matrix_latest.txt" \
  "$ROOT/reports/research_raw/stage90_mainline_event_alpha_matrix_latest.json" \
  "$ROOT/reports/research_raw/stage91_branch_event_alpha_matrix_latest.txt" \
  "$ROOT/reports/research_raw/stage91_branch_event_alpha_matrix_latest.json" \
  "$ROOT/reports/research_raw/stage157_regime_playbook_accel_frontier_latest.txt" \
  "$ROOT/reports/research_raw/stage157_regime_playbook_accel_frontier_latest.json" \
  "$ROOT/reports/research_raw/stage157_regime_playbook_accel_frontier_manifest_latest.json" \
  "$ROOT/reports/research_raw/event_window_sweep_latest.txt" \
  "$ROOT/reports/research_raw/event_window_walkforward_latest.txt" \
  "$ROOT/reports/research_raw/stage120_event_window_frontier_latest.txt" \
  "$HOME/Downloads/okx_demo_report_latest.txt" \
  "$HOME/Downloads/branch_demo_report_latest.txt" \
  "$ROOT/okx_demo_report_latest.txt" \
  "$ROOT/branch_demo_report_latest.txt"; do
  if [ -f "$f" ]; then
    cp -f "$f" "$TMPDIR/"
  fi
done

"$PY" - "$OUT" "$TMPDIR" <<'PY2'
from pathlib import Path
import sys
import zipfile

out = Path(sys.argv[1]).expanduser()
tmpdir = Path(sys.argv[2])
out.parent.mkdir(parents=True, exist_ok=True)
files = sorted([p for p in tmpdir.iterdir() if p.is_file()])
if not files:
    empty = tmpdir / 'empty.txt'
    empty.write_text('stage157 export empty\n', encoding='utf-8')
    files = [empty]
if out.exists():
    out.unlink()
with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
    for p in files:
        zf.write(p, arcname=p.name)
print(out)
PY2

echo "stage158_stage157_fast_resume_done"
