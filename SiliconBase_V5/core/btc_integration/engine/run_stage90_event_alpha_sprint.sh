#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"
PY="./.venv/bin/python"
if [ ! -x "$PY" ]; then
  PY="python3"
fi
"$PY" -m tools.repair_raw_from_snapshots --project-dir . --config config.yml >/dev/null || true
"$PY" -m tools.raw_data_guard --project-dir . --config config.yml
"$PY" -m tools.stage90_event_alpha_matrix --project-dir .
