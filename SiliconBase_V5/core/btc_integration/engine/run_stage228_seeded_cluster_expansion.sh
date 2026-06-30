#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
OUT_DIR="$ROOT/reports/research_raw"
mkdir -p "$OUT_DIR"
LOG="$OUT_DIR/stage228_seeded_cluster_expansion_full.log"
TXT="$OUT_DIR/stage228_seeded_cluster_expansion_latest.txt"
JSON="$OUT_DIR/stage228_seeded_cluster_expansion_summary.json"
CSV="$OUT_DIR/stage228_seeded_cluster_expansion_all.csv"
STEP="$OUT_DIR/stage228_seeded_cluster_expansion_step_status.tsv"
DOWNLOADS_DIR="$HOME/Downloads"
mkdir -p "$DOWNLOADS_DIR"
ZIP="$DOWNLOADS_DIR/stage228_seeded_cluster_expansion_latest.zip"

PYTHON_BIN="python3"
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT/.venv/bin/python"
fi

{
  echo -e "step\tstatus\tnote"
  echo -e "stage228_seeded_cluster_expansion\tRUNNING\tseeded broad family expansion"
} > "$STEP"

set +e
"$PYTHON_BIN" "$ROOT/tools/stage228_seeded_cluster_expansion.py" --project-dir "$ROOT" > "$LOG" 2>&1
STATUS=$?
set -e

if [[ $STATUS -eq 0 ]]; then
  echo -e "stage228_seeded_cluster_expansion\tOK\tcompleted" >> "$STEP"
else
  echo -e "stage228_seeded_cluster_expansion\tFAIL\tsee full log" >> "$STEP"
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
with zipfile.ZipFile(Path(r"$ZIP"), 'w', compression=zipfile.ZIP_DEFLATED) as z:
    for p in files:
        if p.exists():
            z.write(p, arcname=p.name)
PY

echo "[stage228_seeded_cluster_expansion] zip=$ZIP"
if [[ $STATUS -ne 0 ]]; then
  exit $STATUS
fi
