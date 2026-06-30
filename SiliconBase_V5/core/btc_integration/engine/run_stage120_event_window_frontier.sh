#!/usr/bin/env bash
set -u

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PY="$ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
  PY="python3"
fi

RAW="$ROOT/data/raw"
RAW_SNAP="$ROOT/data/raw_snapshots"
REPORT_RAW="$ROOT/reports/research_raw"
mkdir -p "$RAW" "$RAW_SNAP" "$REPORT_RAW"

PROGRESS="$REPORT_RAW/stage120_progress_latest.txt"
OUT="$HOME/Downloads/stage120_event_window_frontier_latest.zip"
TMPDIR="$(mktemp -d)"
cleanup() { rm -rf "$TMPDIR"; }
trap cleanup EXIT

: > "$PROGRESS"
rm -f "$OUT"

log() {
  printf '[%s] %s\n' "$(date '+%F %T')" "$*" | tee -a "$PROGRESS" >&2
}

csv_meta() {
  "$PY" - "$1" <<'PY'
from pathlib import Path
import sys
import pandas as pd
p = Path(sys.argv[1])
if not p.exists():
    print('rows=0 first=- last=-')
    raise SystemExit(0)
try:
    df = pd.read_csv(p, low_memory=False)
except Exception:
    print('rows=0 first=- last=-')
    raise SystemExit(0)
cols = ['time','timestamp','open_time','ts','datetime','date']
col = next((c for c in cols if c in df.columns), None)
if col is None or df.empty:
    print('rows=0 first=- last=-')
    raise SystemExit(0)

def parse(v):
    if pd.isna(v):
        return pd.NaT
    s = str(v).strip()
    if not s:
        return pd.NaT
    try:
        if s.isdigit() or (s.startswith('-') and s[1:].isdigit()):
            x = int(s)
            ax = abs(x)
            if ax < 10**11:
                u='s'
            elif ax < 10**14:
                u='ms'
            elif ax < 10**17:
                u='us'
            else:
                u='ns'
            return pd.to_datetime(x, unit=u, utc=True, errors='coerce')
        return pd.to_datetime(s, utc=True, errors='coerce')
    except Exception:
        return pd.NaT
ser = df[col].map(parse).dropna().sort_values().drop_duplicates()
if ser.empty:
    print('rows=0 first=- last=-')
else:
    print(f"rows={len(ser)} first={ser.iloc[0]} last={ser.iloc[-1]}")
PY
}

csv_rows() {
  local meta
  meta="$(csv_meta "$1")"
  printf '%s' "$meta" | sed -E 's/rows=([0-9]+).*/\1/'
}

canon_one() {
  local src="$1"
  local dst="$2"
  if [ ! -f "$src" ]; then
    return 1
  fi
  if [ -f "$ROOT/tools/canonicalize_raw_csv.py" ]; then
    if "$PY" "$ROOT/tools/canonicalize_raw_csv.py" --in "$src" --out "$dst" >>"$PROGRESS" 2>&1; then
      return 0
    fi
  fi
  cp -f "$src" "$dst"
  return 0
}

refresh_one() {
  local base="$1"
  local symbol="$2"
  local end_date market rows meta
  local best_rows=0
  local best_path=""
  end_date="$(date +%F)"

  # current raw candidate
  if [ -f "$RAW/${base}_15m.csv" ]; then
    local cur_can="$TMPDIR/${base}_current.canon.csv"
    if canon_one "$RAW/${base}_15m.csv" "$cur_can"; then
      meta="$(csv_meta "$cur_can")"
      rows="$(printf '%s' "$meta" | sed -E 's/rows=([0-9]+).*/\1/')"
      log "${base} current ${meta}"
      if [ "$rows" -gt "$best_rows" ]; then
        best_rows="$rows"
        best_path="$cur_can"
      fi
    fi
  fi

  # pinned snapshot candidate
  if [ -f "$RAW_SNAP/${base}_15m.best.csv" ]; then
    local pin_can="$TMPDIR/${base}_pin.canon.csv"
    if canon_one "$RAW_SNAP/${base}_15m.best.csv" "$pin_can"; then
      meta="$(csv_meta "$pin_can")"
      rows="$(printf '%s' "$meta" | sed -E 's/rows=([0-9]+).*/\1/')"
      log "${base} pinned ${meta}"
      if [ "$rows" -gt "$best_rows" ]; then
        best_rows="$rows"
        best_path="$pin_can"
      fi
    fi
  fi

  for market in futures spot; do
    local tmp_raw="$TMPDIR/${base}_${market}.raw.csv"
    local tmp_can="$TMPDIR/${base}_${market}.canon.csv"
    log "刷新 ${base} (${symbol}) market=${market} start=2020-01-01 end=${end_date}"
    if "$PY" -m tools.fetch_binance_klines --symbol "$symbol" --market "$market" --interval 15m --start 2020-01-01 --end "$end_date" --out "$tmp_raw" >>"$PROGRESS" 2>&1; then
      if canon_one "$tmp_raw" "$tmp_can"; then
        meta="$(csv_meta "$tmp_can")"
        rows="$(printf '%s' "$meta" | sed -E 's/rows=([0-9]+).*/\1/')"
        log "${base} ${market} ${meta}"
        if [ "$rows" -gt "$best_rows" ]; then
          best_rows="$rows"
          best_path="$tmp_can"
        fi
      else
        log "[WARN] ${base} ${market} canonicalize failed"
      fi
    else
      log "[WARN] ${base} ${market} 下载失败"
    fi
  done

  if [ "$best_rows" -lt 150000 ] || [ ! -f "$best_path" ]; then
    log "[FAIL] ${base} 可用行数不足 | best_rows=${best_rows}"
    return 1
  fi

  cp -f "$best_path" "$RAW/${base}_15m.csv"
  cp -f "$best_path" "$RAW_SNAP/${base}_15m.best.csv"
  log "[OK] ${base} pinned | $(csv_meta "$RAW/${base}_15m.csv")"
  return 0
}

find_latest_trades() {
  "$PY" - "$ROOT" <<'PY'
from pathlib import Path
import sys
root = Path(sys.argv[1])
runs = sorted((root / 'reports').glob('run_*/trades.csv'), key=lambda p: p.stat().st_mtime, reverse=True)
if runs:
    print(runs[0])
    raise SystemExit(0)
run_latest = root / 'reports' / 'run_latest' / 'trades.csv'
if run_latest.exists():
    print(run_latest)
PY
}

ensure_baseline_trades() {
  local trades_path
  trades_path="$(find_latest_trades || true)"
  if [ -n "$trades_path" ] && [ -f "$trades_path" ]; then
    log "using existing trades: $trades_path"
    printf '%s' "$trades_path"
    return 0
  fi

  local run_id="stage120_$(date +%Y%m%d_%H%M%S)"
  log "生成 baseline trades | run_id=${run_id}"
  if "$PY" -m src.main --config "$ROOT/config.yml" --run-id "$run_id" >>"$PROGRESS" 2>&1; then
    trades_path="$ROOT/reports/run_${run_id}/trades.csv"
    if [ -f "$trades_path" ]; then
      log "baseline trades ready: $trades_path"
      printf '%s' "$trades_path"
      return 0
    fi
  fi

  trades_path="$(find_latest_trades || true)"
  if [ -n "$trades_path" ] && [ -f "$trades_path" ]; then
    log "fallback trades: $trades_path"
    printf '%s' "$trades_path"
    return 0
  fi

  log "[FAIL] 无法生成 trades.csv"
  return 1
}

run_optional() {
  local name="$1"
  shift
  if "$@" >>"$PROGRESS" 2>&1; then
    log "$name OK"
    return 0
  else
    log "WARN $name failed; continue"
    return 1
  fi
}

log "stage120 start"
raw_fail=0
refresh_one btc BTCUSDT || raw_fail=1
refresh_one bnb BNBUSDT || raw_fail=1

TRADES_PATH=""
if [ "$raw_fail" -eq 0 ]; then
  TRADES_PATH="$(ensure_baseline_trades || true)"
  if [ -n "$TRADES_PATH" ] && [ -f "$TRADES_PATH" ]; then
    run_optional event_window_sweep "$PY" -u -m tools.event_window_sweep --project-dir "$ROOT" --trades-csv "$TRADES_PATH" --out "$REPORT_RAW/event_window_sweep_latest.txt"
    run_optional event_window_walkforward "$PY" -u -m tools.event_window_walkforward --project-dir "$ROOT" --trades-csv "$TRADES_PATH" --out "$REPORT_RAW/event_window_walkforward_latest.txt"
  else
    log "WARN event_window skipped: trades.csv unavailable"
  fi
  if [ -f "$ROOT/tools/stage90_event_alpha_matrix.py" ]; then
    run_optional stage90 "$PY" -m tools.stage90_event_alpha_matrix --project-dir "$ROOT"
  else
    log "WARN stage90 missing"
  fi
  if [ -f "$ROOT/tools/stage91_branch_event_alpha_matrix.py" ]; then
    run_optional stage91 "$PY" -m tools.stage91_branch_event_alpha_matrix --project-dir "$ROOT"
  else
    log "WARN stage91 missing"
  fi
else
  log "WARN raw refresh failed; skip event-window and stage90/91 rerun"
fi

if "$PY" "$ROOT/tools/stage120_event_window_frontier.py" --project-dir "$ROOT" >>"$PROGRESS" 2>&1; then
  log "stage120 summarize OK"
else
  log "WARN stage120 summarize failed"
fi

STAGE_TXT="$REPORT_RAW/stage120_event_window_frontier_latest.txt"
TMP_EXPORT="$TMPDIR/export"
mkdir -p "$TMP_EXPORT"
for f in \
  "$STAGE_TXT" \
  "$PROGRESS" \
  "$REPORT_RAW/event_window_sweep_latest.txt" \
  "$REPORT_RAW/event_window_walkforward_latest.txt" \
  "$REPORT_RAW/stage75_mainline_event_state_latest.txt" \
  "$REPORT_RAW/stage75_mainline_event_state_latest.json" \
  "$REPORT_RAW/stage90_mainline_event_alpha_matrix_latest.txt" \
  "$REPORT_RAW/stage90_mainline_event_alpha_matrix_latest.json" \
  "$REPORT_RAW/stage91_branch_event_alpha_matrix_latest.txt" \
  "$REPORT_RAW/stage91_branch_event_alpha_matrix_latest.json" \
  "$HOME/Downloads/okx_demo_report_latest.txt" \
  "$HOME/Downloads/branch_demo_report_latest.txt"; do
  if [ -f "$f" ]; then cp -f "$f" "$TMP_EXPORT/"; fi
done

rm -f "$OUT"
(
  cd "$TMP_EXPORT"
  if [ "$(find . -maxdepth 1 -type f | wc -l | tr -d ' ')" -gt 0 ]; then
    zip -q "$OUT" ./*
  else
    printf 'stage120 export empty\n' > empty.txt
    zip -q "$OUT" empty.txt
  fi
)
log "export $OUT"
printf '%s\n' "$OUT"
