#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"
DOWNLOADS="$HOME/Downloads"
RAW="$ROOT_DIR/reports/research_raw"
KEY_ZIP="$DOWNLOADS/stage95_key_files_latest.zip"
KEY_PATH_TXT="$DOWNLOADS/stage95_key_files_path_latest.txt"
python3 - <<'PY' "$ROOT_DIR" "$KEY_ZIP" "$KEY_PATH_TXT"
import sys, zipfile
from pathlib import Path
root = Path(sys.argv[1])
out = Path(sys.argv[2])
path_txt = Path(sys.argv[3])
raw = root / 'reports' / 'research_raw'
downloads = Path.home() / 'Downloads'
files = [
    downloads / 'okx_demo_report_latest.txt',
    downloads / 'branch_demo_report_latest.txt',
    downloads / 'chatgpt_bundle_latest.zip',
    downloads / 'stage95_progress_latest.txt',
    raw / 'stage91_branch_event_alpha_matrix_latest.txt',
    raw / 'stage91_branch_event_alpha_matrix_latest.json',
    raw / 'stage92_eth_sol_open_frontier_latest.txt',
    raw / 'stage92_eth_sol_open_frontier_latest.json',
    raw / 'stage94_priority_pipeline_latest.txt',
    raw / 'stage94_priority_pipeline_latest.json',
    raw / 'stage95_priority_sync_latest.txt',
    raw / 'stage95_priority_sync_latest.json',
]
with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
    for p in files:
        if p.exists() and p.is_file():
            zf.write(p, arcname=p.name)
path_txt.write_text(str(out) + '\n', encoding='utf-8')
print(out)
PY
