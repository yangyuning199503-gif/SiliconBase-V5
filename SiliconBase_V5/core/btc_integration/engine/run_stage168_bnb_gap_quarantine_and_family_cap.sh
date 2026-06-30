#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ -x ./.venv/bin/python ]]; then
  PY=./.venv/bin/python
else
  PY=python3
fi
"$PY" tools/stage168_bnb_gap_quarantine_and_family_cap.py
