#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
RAW="$ROOT/reports/research_raw"
ZIP_OUT="$HOME/Downloads/stage100_mainline_shadow_watch_latest.zip"
ZIP_BAK="$ROOT/reports/stage100_mainline_shadow_watch_latest.zip"
PY="$ROOT/.venv/bin/python"

if [ ! -x "$PY" ]; then
  python3 -m venv "$ROOT/.venv"
  PY="$ROOT/.venv/bin/python"
  "$PY" -m pip install --upgrade pip >/dev/null
  "$PY" -m pip install -r "$ROOT/requirements.txt" >/dev/null
  touch "$ROOT/.venv/.deps_installed"
fi

CANDIDATE="$(tr -d '\r\n' < "$ROOT/.runtime/mainline_shadow_active_candidate.txt" 2>/dev/null || true)"
"$PY" -m tools.stage100_mainline_shadow_monitor --project-dir "$ROOT" --candidate "${CANDIDATE:-combo_sr_soft_adx26_cd6_lb24_zone028_ref}" >/dev/null

"$PY" - <<'PY' "$ROOT" "$ZIP_OUT" "$ZIP_BAK"
import sys, zipfile
from pathlib import Path
root = Path(sys.argv[1]).resolve()
zip_out = Path(sys.argv[2]).expanduser().resolve()
zip_bak = Path(sys.argv[3]).resolve()
raw = root / 'reports' / 'research_raw'
downloads = Path.home() / 'Downloads'
files = [
    downloads / 'okx_demo_report_latest.txt',
    raw / 'mainline_shadow_demo_report_latest.txt',
    raw / 'stage99_mainline_frequency_push_latest.txt',
    raw / 'stage99_mainline_frequency_push_latest.json',
    raw / 'stage100_mainline_shadow_monitor_latest.txt',
    raw / 'stage100_mainline_shadow_monitor_latest.json',
    downloads / 'stage100_progress_latest.txt',
    root / '.runtime' / 'mainline_shadow_balanced_candidate.txt',
    root / '.runtime' / 'mainline_shadow_aggressive_candidate.txt',
    root / '.runtime' / 'mainline_shadow_active_candidate.txt',
]
for dest in (zip_out, zip_bak):
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            if p.exists():
                zf.write(p, arcname=p.name)
print(zip_out)
print(zip_bak)
PY

echo "$ZIP_OUT"
