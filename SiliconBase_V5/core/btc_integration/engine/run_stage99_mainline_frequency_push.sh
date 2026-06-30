#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
PROG="$HOME/Downloads/stage99_progress_latest.txt"
ZIP_OUT="$HOME/Downloads/stage99_mainline_focus_latest.zip"
ZIP_BAK="$ROOT/reports/stage99_mainline_focus_latest.zip"
RAW="$ROOT/reports/research_raw"
mkdir -p "$RAW" "$ROOT/reports"

echo "[stage99] start $(date '+%F %T')" > "$PROG"

PY="$ROOT/.venv/bin/python"
bootstrap_venv() {
  echo "[stage99] bootstrap venv" | tee -a "$PROG"
  rm -rf "$ROOT/.venv"
  python3 -m venv "$ROOT/.venv"
  PY="$ROOT/.venv/bin/python"
  "$PY" -m pip install --upgrade pip >/dev/null
  "$PY" -m pip install -r "$ROOT/requirements.txt" >/dev/null
  touch "$ROOT/.venv/.deps_installed"
}
if [ ! -x "$PY" ] || ! "$PY" -c 'import sys; print(sys.executable)' >/dev/null 2>&1; then
  bootstrap_venv
elif [ ! -f "$ROOT/.venv/.deps_installed" ] || [ "$ROOT/requirements.txt" -nt "$ROOT/.venv/.deps_installed" ]; then
  echo "[stage99] refresh deps" | tee -a "$PROG"
  "$PY" -m pip install -r "$ROOT/requirements.txt" >/dev/null
  touch "$ROOT/.venv/.deps_installed"
fi

if [ ! -f "$RAW/stage93_frequency_accel_latest.json" ]; then
  echo "[stage99] stage93 missing" | tee -a "$PROG"
  if [ ! -f "$RAW/stage90_mainline_event_alpha_matrix_latest.json" ] || [ ! -f "$RAW/stage91_branch_event_alpha_matrix_latest.json" ]; then
    echo "[stage99] stage90/stage91 missing -> rebuild event matrix" | tee -a "$PROG"
    "$PY" -m tools.stage90_event_alpha_matrix --project-dir "$ROOT"
  fi
  echo "[stage99] build stage93" | tee -a "$PROG"
  "$PY" -m tools.stage93_frequency_accel --project-dir "$ROOT"
else
  echo "[stage99] reuse current stage93" | tee -a "$PROG"
fi

echo "[stage99] build mainline focus" | tee -a "$PROG"
"$PY" -m tools.stage99_mainline_frequency_push --project-dir "$ROOT"

echo "[stage99] export small zip" | tee -a "$PROG"
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
    raw / 'stage93_frequency_accel_latest.txt',
    raw / 'stage93_frequency_accel_latest.json',
    raw / 'stage99_mainline_frequency_push_latest.txt',
    raw / 'stage99_mainline_frequency_push_latest.json',
    root / '.runtime' / 'mainline_shadow_balanced_candidate.txt',
    root / '.runtime' / 'mainline_shadow_aggressive_candidate.txt',
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

echo "[stage99] done" | tee -a "$PROG"
echo "$ZIP_OUT" | tee -a "$PROG"
