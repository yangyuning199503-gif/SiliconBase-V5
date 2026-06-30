#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

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

PROFILE="${1:-quick}"
RAW_DIR="reports/research_raw"
mkdir -p "$RAW_DIR"

OUT_TXT="$RAW_DIR/alt_shortwave_message_overlay_latest.txt"
OUT_JSON="$RAW_DIR/alt_shortwave_symbol_overlay_latest.json"

echo "[info] running ALT branch fast research (${PROFILE})"
"$PY" -m tools.alt_shortwave_message_overlay --project-dir . --profile "$PROFILE" --out "$OUT_TXT" --json-out "$OUT_JSON"

echo "[ok] branch research finished: $OUT_TXT"
if [ -f "$OUT_TXT" ]; then
  echo ""
  echo "===== 分支研究结果 ====="
  sed -n '1,120p' "$OUT_TXT"
  echo "========================"
fi

"$PY" -m tools.send_files_pack --project-dir . --cleanup-downloads >/dev/null
