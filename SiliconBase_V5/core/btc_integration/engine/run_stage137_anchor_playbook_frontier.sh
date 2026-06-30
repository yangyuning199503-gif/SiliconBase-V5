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
  "$ROOT/tools/stage137_anchor_playbook_frontier.py" \
  "$ROOT/tools/stage136_regime_plateau_frontier.py" \
  "$ROOT/tools/stage90_event_alpha_matrix.py" \
  "$ROOT/tools/stage88_strategy_fusion_walkforward.py" \
  "$ROOT/tools/okx_demo_autopilot.py"

"$PY" -u -m tools.stage137_anchor_playbook_frontier --project-dir "$ROOT"

# Mirror freshest research outputs into branch workspace if it exists, so runtime report stops reading stale stage91 files.
if [ -d "$ROOT/.branch_shortwave_demo/workspace" ]; then
  mkdir -p "$ROOT/.branch_shortwave_demo/workspace/reports/research_raw"
  for f in \
    "$ROOT/reports/research_raw/stage90_mainline_event_alpha_matrix_latest.txt" \
    "$ROOT/reports/research_raw/stage90_mainline_event_alpha_matrix_latest.json" \
    "$ROOT/reports/research_raw/stage91_branch_event_alpha_matrix_latest.txt" \
    "$ROOT/reports/research_raw/stage91_branch_event_alpha_matrix_latest.json" \
    "$ROOT/reports/research_raw/stage137_anchor_playbook_frontier_latest.txt" \
    "$ROOT/reports/research_raw/stage137_anchor_playbook_frontier_latest.json" \
    "$ROOT/reports/research_raw/stage137_anchor_playbook_manifest_latest.json"; do
    [ -f "$f" ] && cp -f "$f" "$ROOT/.branch_shortwave_demo/workspace/reports/research_raw/"
  done
fi

OUT="$HOME/Downloads/stage137_anchor_playbook_frontier_latest.zip"
TMPDIR="$(mktemp -d)"
cleanup() { rm -rf "$TMPDIR"; }
trap cleanup EXIT

for f in \
  "$ROOT/reports/research_raw/stage90_mainline_event_alpha_matrix_latest.txt" \
  "$ROOT/reports/research_raw/stage90_mainline_event_alpha_matrix_latest.json" \
  "$ROOT/reports/research_raw/stage91_branch_event_alpha_matrix_latest.txt" \
  "$ROOT/reports/research_raw/stage91_branch_event_alpha_matrix_latest.json" \
  "$ROOT/reports/research_raw/stage137_anchor_playbook_frontier_latest.txt" \
  "$ROOT/reports/research_raw/stage137_anchor_playbook_frontier_latest.json" \
  "$ROOT/reports/research_raw/stage137_anchor_playbook_manifest_latest.json" \
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
    empty.write_text('stage137 export empty\n', encoding='utf-8')
    files = [empty]
if out.exists():
    out.unlink()
with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
    for p in files:
        zf.write(p, arcname=p.name)
print(out)
PY2

echo "stage137_anchor_playbook_frontier_done"
