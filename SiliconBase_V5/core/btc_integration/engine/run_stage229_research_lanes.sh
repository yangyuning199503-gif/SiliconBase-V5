#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
OUT_DIR="$ROOT/reports/research_raw"
mkdir -p "$OUT_DIR"
DOWNLOADS_DIR="$HOME/Downloads"
mkdir -p "$DOWNLOADS_DIR"
LOG="$OUT_DIR/stage229_research_lanes_full.log"
STEP="$OUT_DIR/stage229_research_lanes_step_status.tsv"
TXT="$OUT_DIR/stage229_research_lanes_latest.txt"
JSON="$OUT_DIR/stage229_research_lanes_summary.json"
ZIP="$DOWNLOADS_DIR/stage229_research_lanes_latest.zip"
END_DATE="${1:-$(date +%F)}"

{
  echo -e "step\tstatus\tnote"
  echo -e "stage227_refresh_and_matrix\tRUNNING\trefresh 5m raw + combo matrix"
} > "$STEP"

set +e
bash "$ROOT/run_stage227_five_min_combo_matrix.sh" "$END_DATE" > "$LOG" 2>&1
S1=$?
set -e
if [[ $S1 -eq 0 ]]; then
  echo -e "stage227_refresh_and_matrix\tOK\tstage227 completed" >> "$STEP"
else
  echo -e "stage227_refresh_and_matrix\tFAIL\tsee full log" >> "$STEP"
fi

if [[ $S1 -eq 0 ]]; then
  echo -e "stage228_seeded_cluster_expansion\tRUNNING\tseeded family expansion" >> "$STEP"
  set +e
  bash "$ROOT/run_stage228_seeded_cluster_expansion.sh" >> "$LOG" 2>&1
  S2=$?
  set -e
  if [[ $S2 -eq 0 ]]; then
    echo -e "stage228_seeded_cluster_expansion\tOK\tstage228 completed" >> "$STEP"
  else
    echo -e "stage228_seeded_cluster_expansion\tFAIL\tsee full log" >> "$STEP"
  fi
else
  S2=99
fi

python3 - <<PY
from pathlib import Path
import json, zipfile
out_dir = Path(r"$OUT_DIR")
zip_path = Path(r"$ZIP")
files = [
    Path(r"$STEP"),
    Path(r"$LOG"),
    out_dir / 'stage227_five_min_raw_freshness_latest.txt',
    out_dir / 'stage227_five_min_combo_matrix_latest.txt',
    out_dir / 'stage227_five_min_combo_matrix_summary.json',
    out_dir / 'stage227_five_min_combo_matrix_all.csv',
    out_dir / 'stage228_seeded_cluster_expansion_latest.txt',
    out_dir / 'stage228_seeded_cluster_expansion_summary.json',
    out_dir / 'stage228_seeded_cluster_expansion_all.csv',
]
summary = {
    'stage': 'stage229_research_lanes',
    'stage227_status': 'OK' if $S1 == 0 else 'FAIL',
    'stage228_status': 'OK' if $S2 == 0 else ('SKIPPED' if $S1 != 0 else 'FAIL'),
    'zip_members': [p.name for p in files if p.exists()],
}
Path(r"$JSON").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
lines = [
    '[stage229_research_lanes]',
    f'stage227_status={summary["stage227_status"]}',
    f'stage228_status={summary["stage228_status"]}',
    '',
    '[notes]',
    '- 先刷新 5m raw，再跑多周期组合矩阵，再跑 seeded 扩簇。',
    '- 仍按 6年必报、近2年+WF 主排序、不同标的分开定参数。',
]
Path(r"$TXT").write_text('\n'.join(lines) + '\n', encoding='utf-8')
files.extend([Path(r"$TXT"), Path(r"$JSON")])
with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as z:
    for p in files:
        if p.exists():
            z.write(p, arcname=p.name)
PY

echo "[stage229_research_lanes] zip=$ZIP"
if [[ $S1 -ne 0 ]]; then
  exit $S1
fi
if [[ $S2 -ne 0 ]]; then
  exit $S2
fi
