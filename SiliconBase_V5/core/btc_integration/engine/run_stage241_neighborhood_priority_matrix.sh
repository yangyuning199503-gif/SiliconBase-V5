#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
OUT_DIR="$ROOT/reports/research_raw"
mkdir -p "$OUT_DIR"
LOG="$OUT_DIR/stage241_neighborhood_priority_matrix_full.log"
TXT="$OUT_DIR/stage241_neighborhood_priority_matrix_latest.txt"
JSON="$OUT_DIR/stage241_neighborhood_priority_matrix_summary.json"
CSV="$OUT_DIR/stage241_neighborhood_priority_matrix_all.csv"
STEP="$OUT_DIR/stage241_neighborhood_priority_matrix_step_status.tsv"
DOWNLOADS_DIR="$HOME/Downloads"
mkdir -p "$DOWNLOADS_DIR"
ZIP="$DOWNLOADS_DIR/stage241_neighborhood_priority_matrix_latest.zip"
PYTHON_BIN="python3"
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT/.venv/bin/python"
fi
{
  echo -e "step\tstatus\tnote"
  echo -e "stage241_neighborhood_priority_matrix\tRUNNING\tETH/SOL neighborhood focus; BNB protective verify; BTC audit only"
} > "$STEP"
set +e
"$PYTHON_BIN" "$ROOT/tools/stage241_neighborhood_priority_matrix.py" --project-dir "$ROOT" > "$LOG" 2>&1
STATUS=$?
set -e
if [[ $STATUS -eq 0 ]]; then
  echo -e "stage241_neighborhood_priority_matrix\tOK\tcompleted" >> "$STEP"
else
  echo -e "stage241_neighborhood_priority_matrix\tFAIL\tsee full log" >> "$STEP"
fi
rm -f "$ZIP"
export STEP LOG TXT JSON CSV ZIP
python3 - <<'EOPY'
from pathlib import Path
import zipfile, os
files = [
    Path(os.environ['STEP']),
    Path(os.environ['LOG']),
    Path(os.environ['TXT']),
    Path(os.environ['JSON']),
    Path(os.environ['CSV']),
]
with zipfile.ZipFile(Path(os.environ['ZIP']), 'w', compression=zipfile.ZIP_DEFLATED) as z:
    for p in files:
        if p.exists():
            z.write(p, arcname=p.name)
EOPY
echo "[stage241_neighborhood_priority_matrix] zip=$ZIP"
if [[ $STATUS -ne 0 ]]; then
  exit $STATUS
fi
