#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PY="$PROJECT_DIR/.venv/bin/python"
if [ ! -x "$PY" ]; then
  PY="$(command -v python3 || command -v python)"
fi
if [ -z "${PY:-}" ]; then
  echo "python not found" >&2
  exit 1
fi
cd "$PROJECT_DIR"
"$PY" -m tools.stage192_reclaim_pair_voltarget_frontier --project-dir "$PROJECT_DIR"
