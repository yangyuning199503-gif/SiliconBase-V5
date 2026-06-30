#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
OUT_DIR="$ROOT/reports/research_raw"
mkdir -p "$OUT_DIR"
DOWNLOADS_DIR="$HOME/Downloads"
mkdir -p "$DOWNLOADS_DIR"
ZIP="$DOWNLOADS_DIR/stage227_five_min_combo_matrix_latest.zip"
STEP="$OUT_DIR/stage227_five_min_combo_matrix_step_status.tsv"
LOG="$OUT_DIR/stage227_five_min_combo_matrix_full.log"
TXT="$OUT_DIR/stage227_five_min_combo_matrix_latest.txt"
JSON="$OUT_DIR/stage227_five_min_combo_matrix_summary.json"
CSV="$OUT_DIR/stage227_five_min_combo_matrix_all.csv"
REFRESH_TXT="$OUT_DIR/stage227_five_min_raw_freshness_latest.txt"
END_DATE="${1:-$(date +%F)}"

{
  echo -e "step\tstatus\tnote"
  echo -e "stage227_refresh_5m\tRUNNING\trefresh btc/bnb/eth/sol 5m raw"
} > "$STEP"

set +e
bash "$ROOT/refresh_stage225_five_min_raw.sh" "$END_DATE" > "$LOG" 2>&1
STATUS=$?
set -e
if [[ $STATUS -eq 0 ]]; then
  echo -e "stage227_refresh_5m\tOK\t5m raw refreshed" >> "$STEP"
else
  echo -e "stage227_refresh_5m\tFAIL\tsee full log" >> "$STEP"
fi

if [[ $STATUS -ne 0 ]]; then
  python3 - <<PY
from pathlib import Path
import zipfile
files = [
    Path(r"$STEP"),
    Path(r"$LOG"),
    Path(r"$REFRESH_TXT"),
]
with zipfile.ZipFile(Path(r"$ZIP"), 'w', compression=zipfile.ZIP_DEFLATED) as z:
    for p in files:
        if p.exists():
            z.write(p, arcname=p.name)
PY
  echo "[stage227_five_min_combo_matrix] zip=$ZIP"
  exit $STATUS
fi

echo -e "stage227_combo_matrix\tRUNNING\trun stage225 with 5m enabled" >> "$STEP"
set +e
bash "$ROOT/run_stage225_combo_matrix_lab.sh" >> "$LOG" 2>&1
STATUS=$?
set -e
if [[ $STATUS -eq 0 ]]; then
  echo -e "stage227_combo_matrix\tOK\tstage225 completed" >> "$STEP"
else
  echo -e "stage227_combo_matrix\tFAIL\tsee full log" >> "$STEP"
fi

python3 - <<PY
from pathlib import Path
import json, shutil, zipfile
out_dir = Path(r"$OUT_DIR")
s225_txt = out_dir / 'stage225_combo_matrix_lab_latest.txt'
s225_json = out_dir / 'stage225_combo_matrix_lab_summary.json'
s225_csv = out_dir / 'stage225_combo_matrix_lab_all.csv'
s225_log = out_dir / 'stage225_combo_matrix_lab_full.log'
new_txt = Path(r"$TXT")
new_json = Path(r"$JSON")
new_csv = Path(r"$CSV")
if s225_txt.exists():
    txt = s225_txt.read_text(encoding='utf-8')
    new_txt.write_text('[stage227_five_min_combo_matrix]\nexpected_5m=true\n\n' + txt, encoding='utf-8')
if s225_csv.exists():
    shutil.copy2(s225_csv, new_csv)
summary = {}
if s225_json.exists():
    summary = json.loads(s225_json.read_text(encoding='utf-8'))
summary['stage'] = 'stage227_five_min_combo_matrix'
summary['expected_5m'] = True
pairings = summary.get('pairings_used', [])
summary['five_min_ready_after_refresh'] = any((p[0] == '5m') for p in pairings)
new_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
files = [
    Path(r"$STEP"),
    Path(r"$LOG"),
    Path(r"$REFRESH_TXT"),
    Path(r"$TXT"),
    Path(r"$JSON"),
    Path(r"$CSV"),
    s225_log,
]
with zipfile.ZipFile(Path(r"$ZIP"), 'w', compression=zipfile.ZIP_DEFLATED) as z:
    for p in files:
        if p.exists():
            z.write(p, arcname=p.name)
PY

echo "[stage227_five_min_combo_matrix] zip=$ZIP"
if [[ $STATUS -ne 0 ]]; then
  exit $STATUS
fi

python3 - <<PY
import json, sys
from pathlib import Path
summary_path = Path(r"$JSON")
if not summary_path.exists():
    sys.exit(2)
summary = json.loads(summary_path.read_text(encoding='utf-8'))
if not summary.get('five_min_ready_after_refresh'):
    print('[ERR] 5m pairings were still not enabled after refresh.', file=sys.stderr)
    sys.exit(3)
PY
