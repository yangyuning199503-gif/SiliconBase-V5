#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

PY="./.venv/bin/python"
bootstrap_venv() {
  echo "Creating virtualenv .venv ..."
  rm -rf .venv
  python3 -m venv .venv
  PY="./.venv/bin/python"
  "$PY" -m pip install --upgrade pip >/dev/null
}

if [ ! -x "$PY" ] || ! "$PY" -c 'import sys; print(sys.executable)' >/dev/null 2>&1; then
  bootstrap_venv
fi

MARKER=".venv/.deps_installed"
if [ ! -f "$MARKER" ] || [ requirements.txt -nt "$MARKER" ]; then
  "$PY" -m pip install -r requirements.txt >/dev/null
  touch "$MARKER"
fi

END_DATE="${1:-$(date +%F)}"
START_DATE="2020-01-01"
mkdir -p data/raw

fetch_one() {
  local symbol="$1"
  local out="$2"
  local tmp="${out}.partial.$$"
  echo "Refreshing ${symbol} -> ${out}"
  rm -f "$tmp"
  if "$PY" -m tools.fetch_binance_klines --symbol "$symbol" --market futures --interval 15m --start "$START_DATE" --end "$END_DATE" --out "$tmp"; then
    mv -f "$tmp" "$out"
    return 0
  fi
  echo "futures failed for ${symbol}, retrying spot ..."
  rm -f "$tmp"
  if "$PY" -m tools.fetch_binance_klines --symbol "$symbol" --market spot --interval 15m --start "$START_DATE" --end "$END_DATE" --out "$tmp"; then
    mv -f "$tmp" "$out"
    return 0
  fi
  rm -f "$tmp"
  echo "[ERR] ${symbol} refresh failed; kept existing file: ${out}" >&2
  return 1
}

fetch_one BTCUSDT data/raw/btc_15m.csv
fetch_one BNBUSDT data/raw/bnb_15m.csv

"$PY" -m tools.repair_raw_from_snapshots --project-dir . --config config.yml >/dev/null || true

"$PY" -m tools.raw_data_guard --project-dir . --config config.yml

echo "OK: 主线 raw 数据已刷新并通过检查。现在执行: bash start_okx_demo.sh 或 bash run.sh"
