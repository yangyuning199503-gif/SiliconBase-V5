#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PY="$ROOT/.venv/bin/python"
bootstrap_venv() {
  echo "[stage174] creating virtualenv .venv ..."
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
  "$PY" -m pip install -r "$ROOT/requirements.txt" >/dev/null
  touch "$ROOT/.venv/.deps_installed"
fi

RAW="$ROOT/reports/research_raw"
DL="$HOME/Downloads"
mkdir -p "$RAW" "$DL"

SUMMARY_TXT="$RAW/stage174_anchor_accel_and_runtime_sync_latest.txt"
SUMMARY_JSON="$RAW/stage174_anchor_accel_and_runtime_sync_latest.json"
STATUS_TMP="$RAW/stage174_status.tmp"
TS="$(date '+%Y-%m-%d %H:%M:%S')"

report_is_boot_placeholder() {
  local report="$1"
  [ -f "$report" ] || return 0
  if grep -q '当前状态: 启动中' "$report" 2>/dev/null; then
    return 0
  fi
  if grep -q '状态原因: waiting_for_autopilot_process' "$report" 2>/dev/null; then
    return 0
  fi
  return 1
}

run_step() {
  local name="$1"
  local cmd="$2"
  local logfile="$RAW/stage174_${name}.log"
  echo "[RUN] $name" | tee -a "$SUMMARY_TXT"
  if bash -lc "$cmd" >"$logfile" 2>&1; then
    echo "PASS|$name|$logfile" >> "$STATUS_TMP"
    echo "- $name: PASS" >> "$SUMMARY_TXT"
  else
    echo "FAIL|$name|$logfile" >> "$STATUS_TMP"
    echo "- $name: FAIL" >> "$SUMMARY_TXT"
  fi
}

: > "$SUMMARY_TXT"
: > "$STATUS_TMP"
{
  echo "Stage174 锚点加速 + runtime 真相同步"
  echo "时间: $TS"
  echo "根目录: $ROOT"
  echo
  echo "步骤状态:"
} >> "$SUMMARY_TXT"

"$PY" -m py_compile \
  "$ROOT/tools/stage90_event_alpha_matrix.py" \
  "$ROOT/tools/stage160_mainline_overlay_hold_cluster_frontier.py" \
  "$ROOT/tools/stage161_mainline_risk_budget_multiasset_link_frontier.py" \
  "$ROOT/tools/stage162_event_confirm_eth_pair_frontier.py" \
  "$ROOT/tools/stage165_composite_hedge_ladder_frontier.py"

run_step "stage160_mainline_overlay_hold_cluster_frontier" "cd '$ROOT' && '$PY' -u -m tools.stage160_mainline_overlay_hold_cluster_frontier --project-dir '$ROOT'"
run_step "stage162_event_confirm_eth_pair_frontier" "cd '$ROOT' && '$PY' -u -m tools.stage162_event_confirm_eth_pair_frontier --project-dir '$ROOT'"
run_step "stage165_composite_hedge_ladder_frontier" "cd '$ROOT' && '$PY' -u -m tools.stage165_composite_hedge_ladder_frontier --project-dir '$ROOT'"

WS_RAW="$ROOT/.branch_shortwave_demo/workspace/reports/research_raw"
mkdir -p "$WS_RAW"
for f in \
  "$RAW/stage90_mainline_event_alpha_matrix_latest.txt" \
  "$RAW/stage90_mainline_event_alpha_matrix_latest.json" \
  "$RAW/stage91_branch_event_alpha_matrix_latest.txt" \
  "$RAW/stage91_branch_event_alpha_matrix_latest.json" \
  "$RAW/stage160_mainline_overlay_hold_cluster_frontier_latest.txt" \
  "$RAW/stage160_mainline_overlay_hold_cluster_frontier_latest.json" \
  "$RAW/stage162_event_confirm_eth_pair_frontier_latest.txt" \
  "$RAW/stage162_event_confirm_eth_pair_frontier_latest.json" \
  "$RAW/stage165_composite_hedge_ladder_frontier_latest.txt" \
  "$RAW/stage165_composite_hedge_ladder_frontier_latest.json"; do
  [ -f "$f" ] && cp -f "$f" "$WS_RAW/"
done

BRANCH_START_OK=0
if bash "$ROOT/start_branch_demo_triple_book.sh" --restart >/dev/null 2>&1; then
  BRANCH_START_OK=1
elif bash "$ROOT/start_branch_demo.sh" --restart >/dev/null 2>&1; then
  BRANCH_START_OK=1
fi
if [ "$BRANCH_START_OK" = "1" ]; then
  echo "PASS|branch_runtime_restart|restart_ok" >> "$STATUS_TMP"
  echo "- branch_runtime_restart: PASS" >> "$SUMMARY_TXT"
else
  echo "FAIL|branch_runtime_restart|restart_failed" >> "$STATUS_TMP"
  echo "- branch_runtime_restart: FAIL" >> "$SUMMARY_TXT"
fi

BRANCH_REPORT="$DL/branch_demo_report_latest.txt"
for _ in $(seq 1 180); do
  if [ -f "$BRANCH_REPORT" ] && ! report_is_boot_placeholder "$BRANCH_REPORT"; then
    if grep -Fq 'source=stage91_asset_summary' "$BRANCH_REPORT" 2>/dev/null \
       && grep -Fq '[BTC]' "$BRANCH_REPORT" 2>/dev/null \
       && grep -Fq '[ETH]' "$BRANCH_REPORT" 2>/dev/null \
       && grep -Fq '[SOL]' "$BRANCH_REPORT" 2>/dev/null; then
      echo "PASS|branch_report_truth_sync|$BRANCH_REPORT" >> "$STATUS_TMP"
      echo "- branch_report_truth_sync: PASS" >> "$SUMMARY_TXT"
      break
    fi
  fi
  sleep 1
  if [ "$_" = "180" ]; then
    echo "FAIL|branch_report_truth_sync|timeout" >> "$STATUS_TMP"
    echo "- branch_report_truth_sync: FAIL" >> "$SUMMARY_TXT"
  fi
done

"$PY" - <<'PY2' "$STATUS_TMP" "$SUMMARY_JSON" "$SUMMARY_TXT" "$RAW" "$TS"
from pathlib import Path
import json, sys
status_path = Path(sys.argv[1])
out_json = Path(sys.argv[2])
summary_txt = Path(sys.argv[3])
raw = Path(sys.argv[4])
ts = sys.argv[5]
rows = []
for line in status_path.read_text(encoding='utf-8').splitlines():
    if not line.strip():
        continue
    state, name, detail = line.split('|', 2)
    rows.append({'state': state, 'name': name, 'detail': detail})

def load_json(name):
    p = raw / name
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return {}

def top_name(payload, key):
    arr = payload.get(key)
    if isinstance(arr, list) and arr:
        return str(arr[0].get('name') or '')
    return ''

stage160 = load_json('stage160_mainline_overlay_hold_cluster_frontier_latest.json')
stage162 = load_json('stage162_event_confirm_eth_pair_frontier_latest.json')
stage165 = load_json('stage165_composite_hedge_ladder_frontier_latest.json')
stage91 = load_json('stage91_branch_event_alpha_matrix_latest.json')
asset_summary = {}
for item in stage91.get('asset_summary') or []:
    if isinstance(item, dict):
        sym = str(item.get('symbol') or '').upper()
        active = item.get('active') or {}
        asset_summary[sym] = str(active.get('name') or '') if isinstance(active, dict) else str(active or '')
summary = {
    'run_ts': ts,
    'steps': rows,
    'stage160_mainline_top': top_name(stage160, 'mainline'),
    'stage162_mainline_top': top_name(stage162, 'mainline'),
    'stage162_branch_top': top_name(stage162, 'branch'),
    'stage165_mainline_top': top_name(stage165, 'mainline'),
    'stage165_branch_top': top_name(stage165, 'branch'),
    'stage91_asset_summary_active': asset_summary,
}
out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
with summary_txt.open('a', encoding='utf-8') as f:
    f.write('\n当前顶层候选:\n')
    if summary['stage160_mainline_top']:
        f.write(f"- stage160 mainline top: {summary['stage160_mainline_top']}\n")
    if summary['stage162_mainline_top']:
        f.write(f"- stage162 mainline top: {summary['stage162_mainline_top']}\n")
    if summary['stage162_branch_top']:
        f.write(f"- stage162 branch top: {summary['stage162_branch_top']}\n")
    if summary['stage165_mainline_top']:
        f.write(f"- stage165 mainline top: {summary['stage165_mainline_top']}\n")
    if summary['stage165_branch_top']:
        f.write(f"- stage165 branch top: {summary['stage165_branch_top']}\n")
    if asset_summary:
        parts = [f"{k}:{v}" for k, v in sorted(asset_summary.items()) if v]
        f.write(f"- stage91 asset summary: {' ; '.join(parts)}\n")
print(out_json)
PY2

OUTZIP="$DL/stage174_anchor_accel_and_runtime_sync_latest.zip"
TMPDIR="$(mktemp -d)"
cleanup() { rm -rf "$TMPDIR" "$STATUS_TMP"; }
trap cleanup EXIT

for f in \
  "$SUMMARY_TXT" \
  "$SUMMARY_JSON" \
  "$RAW/stage90_mainline_event_alpha_matrix_latest.txt" \
  "$RAW/stage90_mainline_event_alpha_matrix_latest.json" \
  "$RAW/stage91_branch_event_alpha_matrix_latest.txt" \
  "$RAW/stage91_branch_event_alpha_matrix_latest.json" \
  "$RAW/stage160_mainline_overlay_hold_cluster_frontier_latest.txt" \
  "$RAW/stage160_mainline_overlay_hold_cluster_frontier_latest.json" \
  "$RAW/stage160_mainline_overlay_hold_cluster_frontier_manifest_latest.json" \
  "$RAW/stage162_event_confirm_eth_pair_frontier_latest.txt" \
  "$RAW/stage162_event_confirm_eth_pair_frontier_latest.json" \
  "$RAW/stage162_event_confirm_eth_pair_frontier_manifest_latest.json" \
  "$RAW/stage165_composite_hedge_ladder_frontier_latest.txt" \
  "$RAW/stage165_composite_hedge_ladder_frontier_latest.json" \
  "$RAW/stage165_composite_hedge_ladder_frontier_manifest_latest.json" \
  "$DL/okx_demo_report_latest.txt" \
  "$DL/branch_demo_report_latest.txt"; do
  [ -f "$f" ] && cp -f "$f" "$TMPDIR/"
done
for logf in "$RAW"/stage174_*.log; do
  [ -f "$logf" ] || continue
  cp -f "$logf" "$TMPDIR/"
done

"$PY" - <<'PY3' "$OUTZIP" "$TMPDIR"
from pathlib import Path
import sys, zipfile
out = Path(sys.argv[1]).expanduser()
tmp = Path(sys.argv[2])
out.parent.mkdir(parents=True, exist_ok=True)
files = sorted([p for p in tmp.iterdir() if p.is_file()])
if out.exists():
    out.unlink()
with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
    for p in files:
        zf.write(p, arcname=p.name)
print(out)
PY3

echo "[OK] stage174_anchor_accel_and_runtime_sync_done"
