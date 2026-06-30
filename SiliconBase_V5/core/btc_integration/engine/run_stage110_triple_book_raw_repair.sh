#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY="$(command -v python3)"
fi
"$PY" -m tools.stage110_triple_book_raw_repair --project-dir .
if [[ -x "$ROOT/cleanup_download_exports.sh" ]]; then
  bash "$ROOT/cleanup_download_exports.sh" "stage110_triple_book_repair_latest.zip" || true
fi
printf '%s\n' "[OK] 只回传这个文件: ~/Downloads/stage110_triple_book_repair_latest.zip"
