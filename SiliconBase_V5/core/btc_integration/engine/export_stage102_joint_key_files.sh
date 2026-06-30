#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
PY=./.venv/bin/python
[ -x "$PY" ] || PY=python3
RAW="$ROOT/reports/research_raw"
OUT="$HOME/Downloads/stage102_joint_key_files_latest.zip"
"$PY" - <<'PY' "$ROOT" "$OUT"
from pathlib import Path
import sys, zipfile
root = Path(sys.argv[1]).resolve()
out = Path(sys.argv[2]).resolve()
raw = root / 'reports' / 'research_raw'
downloads = Path.home() / 'Downloads'
files = [
    downloads / 'okx_demo_report_latest.txt',
    downloads / 'branch_demo_report_latest.txt',
    downloads / 'stage102_progress_latest.txt',
    raw / 'stage90_mainline_event_alpha_matrix_latest.txt',
    raw / 'stage91_branch_event_alpha_matrix_latest.txt',
    raw / 'stage93_frequency_accel_latest.txt',
    raw / 'stage94_priority_pipeline_latest.txt',
    raw / 'stage96_event_bridge_latest.txt',
    raw / 'stage96_priority_refresh_latest.txt',
    raw / 'stage102_joint_adjust_latest.txt',
]
with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
    for p in files:
        if p.exists():
            zf.write(p, arcname=p.name)
print(out)
PY
