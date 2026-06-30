#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

MODE="${1:-fast}"
PY=""
if [[ -x ".venv/bin/python" ]]; then
  PY=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="$(command -v python3)"
else
  PY="$(command -v python)"
fi

run_if_exists() {
  local f="$1"
  if [[ -f "$f" ]]; then
    bash "$f"
  else
    echo "[skip] $f 不存在"
  fi
}

case "$MODE" in
  fast)
    run_if_exists run_alt_shortwave_symbol_overlay.sh
    run_if_exists run_message_stack_backtest.sh
    ;;
  full)
    run_if_exists run_alt_shortwave_lab.sh
    run_if_exists run_alt_shortwave_message_overlay.sh
    run_if_exists run_alt_shortwave_symbol_overlay.sh
    run_if_exists run_alt_shortwave_focus_grid.sh
    run_if_exists run_message_stack_backtest.sh
    ;;
  *)
    echo "用法: bash run_alt_shortwave_research_batch.sh [fast|full]" >&2
    exit 2
    ;;
esac

"$PY" -m tools.finalize_research_outputs --project-dir . --mode "$MODE" --cleanup-downloads
