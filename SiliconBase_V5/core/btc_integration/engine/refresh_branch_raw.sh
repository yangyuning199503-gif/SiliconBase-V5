#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CANON="$HOME/btc_system_v1"
if [ "$ROOT_DIR" != "$CANON" ] && [ -d "$CANON" ]; then
  echo "[ERR] 请在 ~/btc_system_v1 运行。当前目录: $ROOT_DIR" >&2
  exit 1
fi
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
  local ok=0
  local tmp="${out}.partial.$$"
  rm -f "$tmp"
  echo "Refreshing ${symbol} -> ${out}"
  for market in futures spot; do
    for attempt in 1 2 3; do
      rm -f "$tmp"
      if "$PY" -m tools.fetch_binance_klines --symbol "$symbol" --market "$market" --interval 15m --start "$START_DATE" --end "$END_DATE" --out "$tmp"; then
        mv -f "$tmp" "$out"
        echo "[OK] ${symbol} ${market} attempt=${attempt}"
        ok=1
        break 2
      fi
      echo "[WARN] ${symbol} ${market} attempt=${attempt} failed; retrying ..." >&2
      sleep 2
    done
  done
  rm -f "$tmp"
  if [ "$ok" -eq 1 ]; then
    return 0
  fi
  if [ -f "$out" ]; then
    echo "[WARN] ${symbol} refresh failed; kept existing file: ${out}" >&2
    return 0
  fi
  echo "[ERR] ${symbol} refresh failed and no existing file remains: ${out}" >&2
  return 1
}

fetch_one ETHUSDT data/raw/eth_15m.csv
fetch_one SOLUSDT data/raw/sol_15m.csv

"$PY" -m tools.align_backtest_end --project-dir . --config config_shortwave_candidate.yml >/dev/null
"$PY" -m tools.repair_raw_from_snapshots --project-dir . --config config_shortwave_candidate.yml >/dev/null || true

"$PY" -m tools.raw_data_guard --project-dir . --config config_shortwave_candidate.yml >/dev/null

"$PY" - <<'PY'
from pathlib import Path
import pandas as pd
for sym in ['eth','sol']:
    p = Path('data/raw') / f'{sym}_15m.csv'
    if not p.exists():
        print(f'{sym.upper()}: missing')
        continue
    try:
        df = pd.read_csv(p, usecols=['time'])
        ts = pd.to_datetime(df['time'], errors='coerce').dropna()
        latest = ts.iloc[-1] if not ts.empty else None
        print(f'{sym.upper()}: rows={len(df)} latest={latest}')
    except Exception as exc:
        print(f'{sym.upper()}: read_failed {exc}')
PY

echo "OK: 分支 raw 已刷新。现在可执行: bash run_stage95_branch_uplift_now.sh"
