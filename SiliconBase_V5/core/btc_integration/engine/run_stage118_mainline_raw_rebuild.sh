#!/usr/bin/env bash
set -u

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PY="$ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
  PY="python3"
fi

RAW="$ROOT/data/raw"
REPORT_RAW="$ROOT/reports/research_raw"
mkdir -p "$RAW" "$REPORT_RAW"

PROG="$REPORT_RAW/stage118_progress_latest.txt"
STAT="$REPORT_RAW/stage118_step_status_latest.tsv"
SUMM="$REPORT_RAW/stage118_summary_latest.txt"
OUT="$HOME/Downloads/stage118_mainline_refresh_latest.zip"
TMPDIR="$(mktemp -d)"
cleanup() { rm -rf "$TMPDIR"; }
trap cleanup EXIT

: > "$PROG"
: > "$STAT"
: > "$SUMM"
rm -f "$OUT"

log() {
  printf '[%s] %s\n' "$(date '+%F %T')" "$*" | tee -a "$PROG"
}

csv_meta() {
  "$PY" - "$1" <<'PY'
from pathlib import Path
import pandas as pd
import sys
p = Path(sys.argv[1])
if not p.exists():
    print("rows=0 first=- last=-")
    raise SystemExit(0)
try:
    df = pd.read_csv(p, usecols=["time"])
except Exception:
    print("rows=0 first=- last=-")
    raise SystemExit(0)
if df.empty or "time" not in df.columns:
    print("rows=0 first=- last=-")
    raise SystemExit(0)
ts = pd.to_datetime(df["time"], errors="coerce")
ts = ts.dropna().sort_values()
if len(ts) == 0:
    print("rows=0 first=- last=-")
else:
    print(f"rows={len(ts)} first={ts.iloc[0]} last={ts.iloc[-1]}")
PY
}

refresh_one() {
  local base="$1"
  local symbol="$2"
  local best_rows=0
  local best_path=""
  local best_market=""
  local market
  local end_date
  end_date="$(date +%F)"

  for market in futures spot; do
    local tmp="$TMPDIR/${base}_${market}.csv"
    log "刷新 ${base} (${symbol}) market=${market} start=2020-01-01 end=${end_date}"
    if "$PY" -m tools.fetch_binance_klines --symbol "$symbol" --market "$market" --interval 15m --start 2020-01-01 --end "$end_date" --out "$tmp" >> "$PROG" 2>&1; then
      local meta rows
      meta="$(csv_meta "$tmp")"
      rows="$(printf '%s' "$meta" | sed -E 's/rows=([0-9]+).*/\1/')"
      log "${base} ${market} ${meta}"
      if [ "$rows" -gt "$best_rows" ]; then
        best_rows="$rows"
        best_path="$tmp"
        best_market="$market"
      fi
    else
      log "[WARN] ${base} ${market} 下载失败，保留继续尝试其他 market"
    fi
  done

  if [ "$best_rows" -lt 150000 ] || [ ! -f "$best_path" ]; then
    echo -e "${base}_raw\tFAIL(rows=${best_rows})" >> "$STAT"
    log "[FAIL] ${base} 可用行数不足，未替换旧文件 | best_rows=${best_rows}"
    return 1
  fi

  if [ -f "$RAW/${base}_15m.csv" ]; then
    cp -f "$RAW/${base}_15m.csv" "$TMPDIR/${base}_15m.backup.csv" || true
  fi
  cp -f "$best_path" "$RAW/${base}_15m.csv"
  echo -e "${base}_raw\tOK(rows=${best_rows},market=${best_market})" >> "$STAT"
  log "[OK] ${base} 已替换 | market=${best_market} | $(csv_meta "$RAW/${base}_15m.csv")"
  return 0
}

run_step() {
  local name="$1"
  shift
  log "运行 ${name}"
  if "$@" >> "$PROG" 2>&1; then
    echo -e "${name}\tOK" >> "$STAT"
    log "[OK] ${name}"
    return 0
  else
    local rc=$?
    echo -e "${name}\tFAIL(${rc})" >> "$STAT"
    log "[FAIL] ${name} | exit=${rc}"
    return "$rc"
  fi
}

log "Stage118 主线 raw 全量修复 + blocked stages 重跑（研究层，不动 live/demo）"
log "python=${PY}"

raw_fail=0
refresh_one btc BTCUSDT || raw_fail=1
refresh_one bnb BNBUSDT || raw_fail=1

if [ "$raw_fail" -eq 0 ]; then
  run_step stage77 "$PY" -m tools.stage77_mainline_dual_window_lab --project-dir "$ROOT" || true
  run_step stage78 "$PY" -m tools.stage78_branch_dual_window_lab --project-dir "$ROOT" || true
  run_step stage81 "$PY" -m tools.stage81_mainline_walkforward_lab --project-dir "$ROOT" || true
  run_step stage82 "$PY" -m tools.stage82_branch_walkforward_lab --project-dir "$ROOT" || true
  run_step stage88 "$PY" -m tools.stage88_strategy_fusion_walkforward --project-dir "$ROOT" || true
  run_step stage90 "$PY" -m tools.stage90_event_alpha_matrix --project-dir "$ROOT" || true
  if [ -f "$ROOT/tools/stage91_branch_event_alpha_matrix.py" ]; then
    run_step stage91 "$PY" -m tools.stage91_branch_event_alpha_matrix --project-dir "$ROOT" || true
  else
    echo -e "stage91\tSKIP(no_file)" >> "$STAT"
    log "[SKIP] stage91 | tools/stage91_branch_event_alpha_matrix.py 不存在"
  fi
  if [ -f "$ROOT/tools/stage93_frequency_accel.py" ] && [ -f "$REPORT_RAW/stage90_mainline_event_alpha_matrix_latest.json" ] && [ -f "$REPORT_RAW/stage91_branch_event_alpha_matrix_latest.json" ]; then
    run_step stage93 "$PY" -m tools.stage93_frequency_accel --project-dir "$ROOT" || true
  else
    echo -e "stage93\tSKIP(missing_stage90_or_91)" >> "$STAT"
    log "[SKIP] stage93 | 缺少 stage90/stage91 输出"
  fi
else
  log "[WARN] mainline raw 仍未修好，跳过 blocked stages 重跑"
fi

{
  echo "summary:"
  cat "$STAT"
  echo ""
  echo "btc=$(csv_meta "$RAW/btc_15m.csv")"
  echo "bnb=$(csv_meta "$RAW/bnb_15m.csv")"
  echo "output=$OUT"
} > "$SUMM"

zip_args=("$OUT" "$SUMM" "$PROG" "$STAT")
for f in \
  "$REPORT_RAW/stage77_mainline_dual_window_latest.txt" \
  "$REPORT_RAW/stage77_mainline_dual_window_latest.json" \
  "$REPORT_RAW/stage78_branch_dual_window_latest.txt" \
  "$REPORT_RAW/stage78_branch_dual_window_latest.json" \
  "$REPORT_RAW/stage81_mainline_walkforward_latest.txt" \
  "$REPORT_RAW/stage81_mainline_walkforward_latest.json" \
  "$REPORT_RAW/stage82_branch_walkforward_latest.txt" \
  "$REPORT_RAW/stage82_branch_walkforward_latest.json" \
  "$REPORT_RAW/stage88_mainline_fusion_walkforward_latest.txt" \
  "$REPORT_RAW/stage88_mainline_fusion_walkforward_latest.json" \
  "$REPORT_RAW/stage90_mainline_event_alpha_matrix_latest.txt" \
  "$REPORT_RAW/stage90_mainline_event_alpha_matrix_latest.json" \
  "$REPORT_RAW/stage91_branch_event_alpha_matrix_latest.txt" \
  "$REPORT_RAW/stage91_branch_event_alpha_matrix_latest.json" \
  "$REPORT_RAW/stage93_frequency_accel_latest.txt" \
  "$REPORT_RAW/stage93_frequency_accel_latest.json" \
  "$HOME/Downloads/okx_demo_report_latest.txt" \
  "$HOME/Downloads/branch_demo_report_latest.txt"; do
  if [ -f "$f" ]; then
    zip_args+=("$f")
  fi
done

/usr/bin/zip -jq "$OUT" "${zip_args[@]:1}" >/dev/null
log "[OK] 导出完成 -> $OUT"
echo "$OUT"
