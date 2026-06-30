#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
PROG="$HOME/Downloads/stage100_progress_latest.txt"
RAW="$ROOT/reports/research_raw"
mkdir -p "$RAW" "$ROOT/reports" "$ROOT/.runtime"
PY="$ROOT/.venv/bin/python"
DEFAULT_CAND="combo_sr_soft_adx26_cd6_lb24_zone028_ref"
CANDIDATE="$(tr -d '\r\n' < "$ROOT/.runtime/mainline_shadow_balanced_candidate.txt" 2>/dev/null || true)"
[ -n "$CANDIDATE" ] || CANDIDATE="$DEFAULT_CAND"
REPORT_FILE="$RAW/mainline_shadow_demo_report_latest.txt"
WAIT_FULL_BARS="${WAIT_FULL_BARS:-1}"
POLL_SECONDS="${POLL_SECONDS:-10}"
MAX_WAIT_SECONDS="${MAX_WAIT_SECONDS:-2200}"

echo "[stage100] start $(date '+%F %T')" > "$PROG"
echo "[stage100] candidate=$CANDIDATE" | tee -a "$PROG"
echo "[stage100] wait_full_bars=$WAIT_FULL_BARS" | tee -a "$PROG"

bootstrap_venv() {
  echo "[stage100] bootstrap venv" | tee -a "$PROG"
  rm -rf "$ROOT/.venv"
  python3 -m venv "$ROOT/.venv"
  PY="$ROOT/.venv/bin/python"
  "$PY" -m pip install --upgrade pip >/dev/null
  "$PY" -m pip install -r "$ROOT/requirements.txt" >/dev/null
  touch "$ROOT/.venv/.deps_installed"
}
if [ ! -x "$PY" ] || ! "$PY" -c 'import sys; print(sys.executable)' >/dev/null 2>&1; then
  bootstrap_venv
elif [ ! -f "$ROOT/.venv/.deps_installed" ] || [ "$ROOT/requirements.txt" -nt "$ROOT/.venv/.deps_installed" ]; then
  echo "[stage100] refresh deps" | tee -a "$PROG"
  "$PY" -m pip install -r "$ROOT/requirements.txt" >/dev/null
  touch "$ROOT/.venv/.deps_installed"
fi

echo "$CANDIDATE" > "$ROOT/.runtime/mainline_shadow_active_candidate.txt"

needs_restart="$($PY - <<'PY' "$REPORT_FILE" "$CANDIDATE"
import re, sys
from pathlib import Path
p = Path(sys.argv[1]); cand = sys.argv[2]
txt = p.read_text(encoding='utf-8', errors='ignore') if p.exists() else ''
if not txt:
    print('yes'); raise SystemExit(0)
state = re.search(r'- 当前状态:\s*(.+)', txt)
reason = re.search(r'- 状态原因:\s*(.+)', txt)
version = re.search(r'- 当前版本:\s*(.+)', txt)
sv = version.group(1).strip() if version else ''
ss = state.group(1).strip() if state else ''
sr = reason.group(1).strip() if reason else ''
if cand not in sv:
    print('yes')
elif ss in ('未运行', '停止'):
    print('yes')
elif sr in ('signal_stale_after_sync', 'error', 'sync_failed'):
    print('yes')
else:
    print('no')
PY
)"

echo "[stage100] needs_restart=$needs_restart" | tee -a "$PROG"
export MAINLINE_SHADOW_SUBMIT_ORDERS=0
if [ "$needs_restart" = "yes" ]; then
  echo "[stage100] restart no-order shadow monitor" | tee -a "$PROG"
  bash "$ROOT/pause_mainline_shadow_demo.sh" >> "$PROG" 2>&1 || true
  bash "$ROOT/start_mainline_shadow_demo.sh" "$CANDIDATE" >> "$PROG" 2>&1
else
  echo "[stage100] keep current shadow process" | tee -a "$PROG"
fi

for i in $(seq 1 120); do
  if [ -f "$REPORT_FILE" ]; then
    break
  fi
  sleep 0.5
done

initial_done="$($PY - <<'PY' "$REPORT_FILE"
import re, sys
from pathlib import Path
p = Path(sys.argv[1])
txt = p.read_text(encoding='utf-8', errors='ignore') if p.exists() else ''
m = re.search(r'最近已完成 15m K 线开盘\(UTC\+8\):\s*(.+)', txt)
print(m.group(1).strip() if m else '')
PY
)"

target_done="$($PY - <<'PY' "$initial_done" "$WAIT_FULL_BARS"
import sys
from datetime import datetime, timedelta
start = sys.argv[1].strip()
wait_bars = int(sys.argv[2])
if not start:
    print('')
    raise SystemExit(0)
dt = datetime.strptime(start, '%Y-%m-%d %H:%M:%S') + timedelta(minutes=15*wait_bars)
print(dt.strftime('%Y-%m-%d %H:%M:%S'))
PY
)"

echo "[stage100] initial_done=${initial_done:-NA}" | tee -a "$PROG"
echo "[stage100] target_done=${target_done:-NA}" | tee -a "$PROG"

if [ -n "$target_done" ]; then
  start_ts=$(date +%s)
  while true; do
    readout="$($PY - <<'PY' "$REPORT_FILE" "$target_done"
import re, sys
from datetime import datetime
from pathlib import Path
p = Path(sys.argv[1]); target = sys.argv[2]
txt = p.read_text(encoding='utf-8', errors='ignore') if p.exists() else ''
md = re.search(r'最近已完成 15m K 线开盘\(UTC\+8\):\s*(.+)', txt)
ms = re.search(r'最近策略信号时间\(UTC\+8\):\s*(.+)', txt)
mr = re.search(r'- 状态原因:\s*(.+)', txt)
mx = re.search(r'- 最近影子执行成功:\s*(.+)', txt)
cur_done = md.group(1).strip() if md else ''
cur_sig = ms.group(1).strip() if ms else ''
reason = mr.group(1).strip() if mr else ''
exec_ok = mx.group(1).strip() if mx else ''
ready = 'no'
if cur_done:
    try:
        if datetime.strptime(cur_done, '%Y-%m-%d %H:%M:%S') >= datetime.strptime(target, '%Y-%m-%d %H:%M:%S') and (reason == 'waiting_next_bar' or exec_ok == '是'):
            ready = 'yes'
    except Exception:
        pass
print(cur_done)
print(cur_sig)
print(reason)
print(exec_ok)
print(ready)
PY
)"
    cur_done=$(printf '%s\n' "$readout" | sed -n '1p')
    cur_sig=$(printf '%s\n' "$readout" | sed -n '2p')
    reason=$(printf '%s\n' "$readout" | sed -n '3p')
    exec_ok=$(printf '%s\n' "$readout" | sed -n '4p')
    ready=$(printf '%s\n' "$readout" | sed -n '5p')
    echo "[stage100] waiting cur_done=${cur_done:-NA} cur_sig=${cur_sig:-NA} reason=${reason:-NA} exec_ok=${exec_ok:-NA} ready=${ready:-no}" | tee -a "$PROG"
    if [ "$ready" = "yes" ]; then
      break
    fi
    now_ts=$(date +%s)
    if [ $((now_ts - start_ts)) -ge "$MAX_WAIT_SECONDS" ]; then
      echo "[stage100] wait timeout, export current snapshot" | tee -a "$PROG"
      break
    fi
    sleep "$POLL_SECONDS"
  done
else
  echo "[stage100] no initial_done found; export current snapshot" | tee -a "$PROG"
fi

echo "[stage100] build monitor summary" | tee -a "$PROG"
"$PY" -m tools.stage100_mainline_shadow_monitor --project-dir "$ROOT" --candidate "$CANDIDATE" >> "$PROG"

echo "[stage100] export watch zip" | tee -a "$PROG"
bash "$ROOT/export_stage100_mainline_shadow_watch.sh" >> "$PROG"

echo "[stage100] done" | tee -a "$PROG"
echo "$HOME/Downloads/stage100_mainline_shadow_watch_latest.zip" | tee -a "$PROG"
