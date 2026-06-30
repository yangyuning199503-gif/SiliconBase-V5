#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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

"$PY" -m tools.repair_raw_from_snapshots --project-dir . --config config.yml >/dev/null || true

"$PY" -m tools.raw_data_guard --project-dir . --config config.yml

mkdir -p reports reports/research_raw
BASE_TRADES="reports/research_raw/current_demo_strategy_trades_latest.csv"
BASE_FORCE=""
if [ "${MESSAGE_STACK_FORCE_BASE_REFRESH:-0}" = "1" ]; then
  BASE_FORCE="--force"
fi

if [ -n "$BASE_FORCE" ]; then
  "$PY" -m tools.build_current_strategy_trades --project-dir . --out "$BASE_TRADES" --force
else
  "$PY" -m tools.build_current_strategy_trades --project-dir . --out "$BASE_TRADES"
fi

OUT_TXT="reports/research_raw/message_stack_backtest_latest.txt"
if [ "${COINGLASS_HISTORY_REFRESH:-0}" = "1" ]; then
  "$PY" -m tools.message_stack_backtest --project-dir . --base-trades "$BASE_TRADES" --out "$OUT_TXT" --refresh
else
  "$PY" -m tools.message_stack_backtest --project-dir . --base-trades "$BASE_TRADES" --out "$OUT_TXT"
fi

cp -f "$BASE_TRADES" reports/current_demo_strategy_trades_latest.csv 2>/dev/null || true
cp -f "$OUT_TXT" reports/message_stack_backtest_latest.txt 2>/dev/null || true

echo "[ok] message stack backtest finished: $OUT_TXT"

"$PY" -m tools.send_files_pack --project-dir . --cleanup-downloads >/dev/null
