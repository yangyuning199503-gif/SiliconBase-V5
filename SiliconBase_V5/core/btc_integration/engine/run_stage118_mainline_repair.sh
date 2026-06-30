#!/usr/bin/env bash
set -u
ROOT="$(cd "$(dirname "$0")" && pwd)"
PY="$ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
  PY="python3"
fi
DL="$HOME/Downloads"
RPT="$ROOT/reports/research_raw"
OUTZIP="$DL/stage118_mainline_repair_latest.zip"
WORK="$RPT/.stage118_export"
PROG="$RPT/stage118_progress_latest.txt"
STATUS="$RPT/stage118_step_status_latest.tsv"
RAWREP="$RPT/stage118_mainline_raw_refresh_latest.txt"
TODAY="$(date +%F)"

mkdir -p "$RPT" "$WORK" "$DL"
: > "$PROG"
: > "$STATUS"
: > "$RAWREP"
rm -rf "$WORK"
mkdir -p "$WORK"

log(){ printf '[%s] %s\n' "$(date '+%F %T')" "$*" | tee -a "$PROG" >/dev/null; }
step(){
  local name="$1"; shift
  log "$name started"
  "$@" >> "$PROG" 2>&1
  local rc=$?
  if [ $rc -eq 0 ]; then
    printf '%s\tOK\n' "$name" >> "$STATUS"
    log "$name OK"
  else
    printf '%s\tFAIL(%s)\n' "$name" "$rc" >> "$STATUS"
    log "$name FAIL rc=$rc"
  fi
  return 0
}

refresh_one(){
  local symbol="$1" out="$2"
  local tmp="$out.stage118.tmp"
  local bak="$out.stage118.bak"
  rm -f "$tmp"
  if [ -f "$out" ]; then cp -f "$out" "$bak"; fi
  local done=0
  local market attempt
  for market in futures spot; do
    attempt=1
    while [ $attempt -le 2 ]; do
      log "fetch ${symbol} market=${market} attempt=${attempt}"
      rm -f "$tmp"
      "$PY" -m tools.fetch_binance_klines --symbol "${symbol}USDT" --market "$market" --interval 15m --start 2020-01-01 --end "$TODAY" --out "$tmp" >> "$PROG" 2>&1
      if [ $? -eq 0 ] && [ -s "$tmp" ]; then
        "$PY" "$ROOT/tools/canonicalize_raw_csv.py" --in "$tmp" --out "$tmp" >> "$PROG" 2>&1
        if [ $? -eq 0 ] && [ -s "$tmp" ]; then
          mv -f "$tmp" "$out"
          done=1
          printf '%s\trewritten\tmarket=%s\n' "$symbol" "$market" >> "$RAWREP"
          break 2
        fi
      fi
      attempt=$((attempt+1))
      sleep 2
    done
  done
  if [ $done -ne 1 ]; then
    printf '%s\tfailed_refresh\n' "$symbol" >> "$RAWREP"
    if [ -f "$bak" ]; then mv -f "$bak" "$out"; fi
    return 1
  fi
  rm -f "$bak" "$tmp"
  return 0
}

raw_snapshot(){
  "$PY" - <<'PY' "$ROOT" "$RAWREP"
import sys
from pathlib import Path
import pandas as pd
root = Path(sys.argv[1]); out = Path(sys.argv[2])
files = [
    ("btc", root / "data/raw/btc_15m.csv"),
    ("bnb", root / "data/raw/bnb_15m.csv"),
]
with out.open("a", encoding="utf-8") as fh:
    for name, path in files:
        if not path.exists():
            fh.write(f"{name}\tmissing\n")
            continue
        try:
            df = pd.read_csv(path, low_memory=False)
            tc = next((c for c in ["time","timestamp","open_time","ts","datetime","date"] if c in df.columns), None)
            if tc is None or df.empty:
                fh.write(f"{name}\tempty_or_no_time\trows={len(df)}\n")
                continue
            fh.write(f"{name}\trows={len(df)}\tearliest={df[tc].iloc[0]}\tlatest={df[tc].iloc[-1]}\n")
        except Exception as e:
            fh.write(f"{name}\terror={e}\n")
PY
}

copy_if(){
  local p="$1"
  if [ -f "$p" ]; then cp -f "$p" "$WORK/$(basename "$p")"; fi
}

log "Stage118 mainline raw repair + walkforward/event repair (research only)"
refresh_one BTC "$ROOT/data/raw/btc_15m.csv" || true
refresh_one BNB "$ROOT/data/raw/bnb_15m.csv" || true
raw_snapshot

step stage81_82 bash "$ROOT/run_stage81_82_walkforward.sh"
step stage88 bash "$ROOT/run_stage88_fusion_sprint.sh"
step stage90 bash "$ROOT/run_stage90_event_alpha_sprint.sh"

copy_if "$PROG"
copy_if "$STATUS"
copy_if "$RAWREP"
copy_if "$RPT/stage81_mainline_walkforward_latest.txt"
copy_if "$RPT/stage81_mainline_walkforward_latest.json"
copy_if "$RPT/stage82_branch_walkforward_latest.txt"
copy_if "$RPT/stage82_branch_walkforward_latest.json"
copy_if "$RPT/stage88_fusion_sprint_latest.txt"
copy_if "$RPT/stage88_fusion_sprint_latest.json"
copy_if "$RPT/stage90_mainline_event_alpha_matrix_latest.txt"
copy_if "$RPT/stage90_mainline_event_alpha_matrix_latest.json"
copy_if "$DL/okx_demo_report_latest.txt"
copy_if "$DL/branch_demo_report_latest.txt"

rm -f "$OUTZIP"
(
  cd "$WORK" && zip -qr "$OUTZIP" .
)
log "output=$OUTZIP"
printf '%s\n' "$OUTZIP" > "$DL/stage118_mainline_repair_path_latest.txt"
exit 0
