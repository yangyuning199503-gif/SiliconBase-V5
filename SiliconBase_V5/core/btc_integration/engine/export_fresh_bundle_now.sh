#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CANON="$HOME/btc_system_v1"
if [ "$ROOT_DIR" != "$CANON" ] && [ -d "$CANON" ]; then
  echo "[ERR] 请在 ~/btc_system_v1 运行。当前目录: $ROOT_DIR" >&2
  exit 1
fi
cd "$ROOT_DIR"

PY="./.venv/bin/python"
if [ ! -x "$PY" ]; then
  python3 -m venv .venv
  "$PY" -m pip install --upgrade pip >/dev/null
  "$PY" -m pip install -r requirements.txt >/dev/null
fi

mkdir -p reports/research_raw "$HOME/Downloads"

# Force rebuild the standard ChatGPT bundle using current files.
"$PY" -m tools.send_files_pack --project-dir . --cleanup-downloads

# Export an unambiguous stage95 zip if those files exist.
python3 - <<'PY'
from pathlib import Path
import zipfile
root = Path.home() / 'btc_system_v1'
downloads = Path.home() / 'Downloads'
raw = root / 'reports' / 'research_raw'
out = downloads / 'stage95_key_files_latest.zip'
files = [
    downloads / 'okx_demo_report_latest.txt',
    downloads / 'branch_demo_report_latest.txt',
    downloads / 'chatgpt_bundle_latest.zip',
    raw / 'stage91_branch_event_alpha_matrix_latest.txt',
    raw / 'stage91_branch_event_alpha_matrix_latest.json',
    raw / 'stage92_eth_sol_open_frontier_latest.txt',
    raw / 'stage92_eth_sol_open_frontier_latest.json',
    raw / 'stage93_frequency_accel_latest.txt',
    raw / 'stage93_frequency_accel_latest.json',
    raw / 'stage94_priority_pipeline_latest.txt',
    raw / 'stage94_priority_pipeline_latest.json',
    raw / 'stage95_priority_sync_latest.txt',
    raw / 'stage95_priority_sync_latest.json',
]
with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
    for p in files:
        if p.exists() and p.is_file():
            zf.write(p, arcname=p.name)
print(out)
PY

ls -lh "$HOME/Downloads/chatgpt_bundle_latest.zip" || true
ls -lh "$HOME/Downloads/stage95_key_files_latest.zip" || true
