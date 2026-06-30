#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
OUT_DIR="$ROOT/reports/research_raw"
mkdir -p "$OUT_DIR"
LOG="$OUT_DIR/stage232_sol_gate_neighborhood_full.log"
TXT="$OUT_DIR/stage232_sol_gate_neighborhood_latest.txt"
JSON="$OUT_DIR/stage232_sol_gate_neighborhood_summary.json"
CSV="$OUT_DIR/stage232_sol_gate_neighborhood_all.csv"
STEP="$OUT_DIR/stage232_sol_gate_neighborhood_step_status.tsv"
DOWNLOADS_DIR="$HOME/Downloads"
mkdir -p "$DOWNLOADS_DIR"
ZIP="$DOWNLOADS_DIR/stage232_sol_gate_neighborhood_latest.zip"

PYTHON_BIN="python3"
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT/.venv/bin/python"
fi

{
  echo -e "step\tstatus\tnote"
  echo -e "stage232_sol_gate_neighborhood\tRUNNING\tSOL gate neighborhood expansion"
} > "$STEP"

set +e
"$PYTHON_BIN" "$ROOT/tools/stage232_sol_gate_neighborhood.py" --project-dir "$ROOT" > "$LOG" 2>&1
STATUS=$?
set -e

if [[ $STATUS -eq 0 ]]; then
  echo -e "stage232_sol_gate_neighborhood\tOK\tcompleted" >> "$STEP"
else
  echo -e "stage232_sol_gate_neighborhood\tFAIL\tsee full log" >> "$STEP"
fi

rm -f "$ZIP"
python3 - <<PY
from pathlib import Path
import zipfile
files = [
    Path(r"$STEP"),
    Path(r"$LOG"),
    Path(r"$TXT"),
    Path(r"$JSON"),
    Path(r"$CSV"),
]
with zipfile.ZipFile(Path(r"$ZIP"), "w", compression=zipfile.ZIP_DEFLATED) as z:
    for p in files:
        if p.exists():
            z.write(p, arcname=p.name)
PY

echo "[stage232_sol_gate_neighborhood] zip=$ZIP"
if [[ $STATUS -ne 0 ]]; then
  exit $STATUS
fi
