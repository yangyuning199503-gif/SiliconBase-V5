#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
if [[ -x ./.venv/bin/python ]]; then
  PY=./.venv/bin/python
else
  PY=python3
fi
"$PY" -m tools.stage151_mainline_runtime_resync --project-dir "$ROOT"
