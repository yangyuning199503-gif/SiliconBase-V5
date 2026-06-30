#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
CANON="$HOME/btc_system_v1"
if [ "$ROOT" != "$CANON" ] && [ -d "$CANON" ]; then
  echo "[ERR] 请在 ~/btc_system_v1 运行。当前目录: $ROOT" >&2
  exit 1
fi
cd "$ROOT"

PROFILE="${1:-aggressive}"
PROG="$HOME/Downloads/stage98_progress_latest.txt"
mkdir -p "$HOME/Downloads"

write_prog() {
  printf '%s\n' "$1" > "$PROG"
}

PY="./.venv/bin/python"
bootstrap_venv() {
  echo "Creating virtualenv .venv ..."
  rm -rf .venv
  python3 -m venv .venv
  PY="./.venv/bin/python"
  "$PY" -m pip install --upgrade pip >/dev/null
  "$PY" -m pip install -r requirements.txt >/dev/null
  touch .venv/.deps_installed
}
if [ ! -x "$PY" ] || ! "$PY" -c 'import sys; print(sys.executable)' >/dev/null 2>&1; then
  bootstrap_venv
elif [ ! -f .venv/.deps_installed ] || [ requirements.txt -nt .venv/.deps_installed ]; then
  "$PY" -m pip install -r requirements.txt >/dev/null
  touch .venv/.deps_installed
fi

write_prog "stage98: start | profile=$PROFILE"
"$PY" -m tools.stage98_branch_expert_playbook --project-dir . --profile "$PROFILE"
write_prog "stage98: matrix done | exporting zip"

"$PY" - <<'PY'
from pathlib import Path
import zipfile
root = Path('.').resolve()
raw = root / 'reports' / 'research_raw'
downloads = Path.home() / 'Downloads'
downloads.mkdir(parents=True, exist_ok=True)
out = downloads / 'stage98_key_files_latest.zip'
files = [
    downloads / 'okx_demo_report_latest.txt',
    downloads / 'branch_demo_report_latest.txt',
    raw / 'stage97_multi_standard_frontier_latest.txt',
    raw / 'stage97_multi_standard_frontier_latest.json',
    raw / 'stage98_branch_expert_playbook_latest.txt',
    raw / 'stage98_branch_expert_playbook_latest.json',
    raw / 'stage91_branch_event_alpha_matrix_latest.txt',
    raw / 'stage91_branch_event_alpha_matrix_latest.json',
]
with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
    for p in files:
        if p.exists() and p.is_file():
            zf.write(p, arcname=p.name)
print(out)
PY
write_prog "stage98: done | ~/Downloads/stage98_key_files_latest.zip"
echo "[OK] ~/Downloads/stage98_key_files_latest.zip"
