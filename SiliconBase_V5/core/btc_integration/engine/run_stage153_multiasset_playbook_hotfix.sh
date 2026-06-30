#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PY=python3
if [ -x ./.venv/bin/python ]; then
  PY=./.venv/bin/python
fi
"$PY" -m tools.stage152_multiasset_playbook_frontier --project-dir .
"$PY" - <<'PY'
from pathlib import Path
import zipfile
root = Path('.').resolve()
raw = root / 'reports' / 'research_raw'
want = [
    raw / 'stage90_mainline_event_alpha_matrix_latest.txt',
    raw / 'stage90_mainline_event_alpha_matrix_latest.json',
    raw / 'stage91_branch_event_alpha_matrix_latest.txt',
    raw / 'stage91_branch_event_alpha_matrix_latest.json',
    raw / 'stage152_multiasset_playbook_frontier_latest.txt',
    raw / 'stage152_multiasset_playbook_frontier_latest.json',
    raw / 'stage152_multiasset_playbook_frontier_manifest_latest.json',
]
out = Path.home() / 'Downloads' / 'stage152_multiasset_playbook_frontier_latest.zip'
out.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
    for path in want:
        if path.exists():
            zf.write(path, arcname=path.name)
print(out)
PY
