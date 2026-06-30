#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  python3 -m venv "$ROOT/.venv"
  "$ROOT/.venv/bin/python" -m pip install -U pip >/dev/null
  "$ROOT/.venv/bin/pip" install -r requirements.txt >/dev/null
fi

mkdir -p "$ROOT/reports/research_raw"
"$ROOT/.venv/bin/python" -m tools.free_feeds_probe --project-dir "$ROOT" --out "$ROOT/reports/research_raw/free_sources_latest.txt"
echo "$ROOT/reports/research_raw/free_sources_latest.txt"
