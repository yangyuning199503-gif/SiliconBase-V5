#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PY=""
if [[ -x ".venv/bin/python" ]]; then
  PY=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="$(command -v python3)"
else
  PY="$(command -v python)"
fi
"$PY" -m tools.alt_shortwave_lab --project-dir . --profile quick
