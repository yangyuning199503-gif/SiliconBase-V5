#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PY3="$(command -v python3 || true)"
if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  if [[ -z "$PY3" ]]; then
    echo '[ERR] python3 not found' >&2
    exit 127
  fi
  "$PY3" -m venv .venv
fi

PY="$ROOT/.venv/bin/python"
"$PY" -m pip -q install -r requirements.txt >/dev/null
mkdir -p reports/research_raw
"$PY" -m tools.event_window_strict_cv --project-dir . --out reports/research_raw/event_window_strict_cv_latest.txt
echo "reports/research_raw/event_window_strict_cv_latest.txt"
