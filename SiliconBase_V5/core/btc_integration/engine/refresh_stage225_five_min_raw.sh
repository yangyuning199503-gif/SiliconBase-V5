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
START_DATE="${START_DATE:-2020-01-01}"
mkdir -p data/raw reports/research_raw

fetch_one() {
  local symbol="$1"
  local out="$2"
  local tmp="${out}.partial.$$"
  echo "Refreshing ${symbol} 5m -> ${out}"
  rm -f "$tmp"
  if "$PY" -m tools.fetch_binance_klines --symbol "$symbol" --market futures --interval 5m --start "$START_DATE" --end "$END_DATE" --out "$tmp"; then
    mv -f "$tmp" "$out"
    return 0
  fi
  echo "futures failed for ${symbol}, retrying spot ..."
  rm -f "$tmp"
  if "$PY" -m tools.fetch_binance_klines --symbol "$symbol" --market spot --interval 5m --start "$START_DATE" --end "$END_DATE" --out "$tmp"; then
    mv -f "$tmp" "$out"
    return 0
  fi
  rm -f "$tmp"
  echo "[WARN] ${symbol} 5m refresh failed; kept existing file: ${out}" >&2
  return 1
}

status=0
fetch_one BTCUSDT data/raw/btc_5m.csv || status=1
fetch_one BNBUSDT data/raw/bnb_5m.csv || status=1
fetch_one ETHUSDT data/raw/eth_5m.csv || status=1
fetch_one SOLUSDT data/raw/sol_5m.csv || status=1

"$PY" - <<'PY' > reports/research_raw/stage227_five_min_raw_freshness_latest.txt
from __future__ import annotations
from pathlib import Path
import pandas as pd

root = Path('.')
paths = {
    'btc': root / 'data' / 'raw' / 'btc_5m.csv',
    'bnb': root / 'data' / 'raw' / 'bnb_5m.csv',
    'eth': root / 'data' / 'raw' / 'eth_5m.csv',
    'sol': root / 'data' / 'raw' / 'sol_5m.csv',
}
latest_map = {}
rows = []
for sym, path in paths.items():
    if not path.exists():
        rows.append(f"- {sym.upper()}: missing | file={path}")
        continue
    try:
        df = pd.read_csv(path)
    except Exception as exc:
        rows.append(f"- {sym.upper()}: read_failed | file={path} | err={exc}")
        continue
    if df.empty or 'time' not in df.columns:
        rows.append(f"- {sym.upper()}: empty_or_no_time | rows={len(df)} | file={path}")
        continue
    df['time'] = pd.to_datetime(df['time'], errors='coerce')
    df = df.dropna(subset=['time']).sort_values('time').reset_index(drop=True)
    if df.empty:
        rows.append(f"- {sym.upper()}: no_valid_time | file={path}")
        continue
    latest = pd.Timestamp(df['time'].iloc[-1]).tz_localize(None)
    first = pd.Timestamp(df['time'].iloc[0]).tz_localize(None)
    latest_map[sym] = latest
    rows.append(f"- {sym.upper()}: first={first.strftime('%Y-%m-%d %H:%M:%S')} | latest={latest.strftime('%Y-%m-%d %H:%M:%S')} | rows={len(df)} | file={path}")

print('5m raw 新鲜度')
print('===================')
if latest_map:
    g = max(latest_map.values())
    print(f'global_latest={g.strftime("%Y-%m-%d %H:%M:%S")}')
    for sym, ts in latest_map.items():
        lag_h = max((g - ts).total_seconds() / 3600.0, 0.0)
        print(f'{sym}_lag_hours_vs_max={lag_h:.1f}')
else:
    print('global_latest=-')
print()
for line in rows:
    print(line)
PY

echo "[OK] reports/research_raw/stage227_five_min_raw_freshness_latest.txt"
if [ "$status" -ne 0 ]; then
  echo "[WARN] 部分 5m raw 刷新失败；已尽量保留旧文件。" >&2
fi
exit "$status"
