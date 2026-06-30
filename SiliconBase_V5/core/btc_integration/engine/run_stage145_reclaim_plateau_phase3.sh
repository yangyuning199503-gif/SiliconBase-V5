#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PY="$ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
  PY="python3"
fi

mkdir -p "$ROOT/reports/research_raw" "$HOME/Downloads"

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

"$PY" -m py_compile \
  "$ROOT/tools/okx_demo_autopilot.py" \
  "$ROOT/tools/stage90_event_alpha_matrix.py" \
  "$ROOT/tools/stage136_regime_plateau_frontier.py" \
  "$ROOT/tools/stage141_guarded_asymmetry_shortlist.py" \
  "$ROOT/tools/stage142_reclaim_cluster_frontier.py" \
  "$ROOT/tools/stage145_reclaim_plateau_phase3.py" \
  "$ROOT/tools/stage120_event_window_frontier.py"

"$PY" -u -m tools.stage145_reclaim_plateau_phase3 --project-dir "$ROOT"

ACTIVE_ETH="$($PY - <<'PY2'
import json
from pathlib import Path
p = Path('reports/research_raw/stage91_branch_event_alpha_matrix_latest.json')
try:
    payload = json.loads(p.read_text(encoding='utf-8'))
except Exception:
    print('')
    raise SystemExit(0)
items = payload.get('asset_summary') if isinstance(payload.get('asset_summary'), list) else []
for item in items:
    if str(item.get('symbol') or '').upper() == 'ETH':
        active = item.get('active') if isinstance(item.get('active'), dict) else {}
        print(str(active.get('name') or '').strip())
        break
else:
    print('')
PY2
)"

if [ -x "$ROOT/start_branch_demo.sh" ]; then
  bash "$ROOT/start_branch_demo.sh" --restart >/dev/null 2>&1 || true
  REPORT="$HOME/Downloads/branch_demo_report_latest.txt"
  for _ in $(seq 1 180); do
    if [ -f "$REPORT" ] && ! report_is_boot_placeholder "$REPORT"; then
      if [ -z "$ACTIVE_ETH" ] || grep -Fq "$ACTIVE_ETH" "$REPORT" 2>/dev/null; then
        break
      fi
    fi
    sleep 1
  done
fi

"$PY" -u "$ROOT/tools/stage120_event_window_frontier.py" --project-dir "$ROOT"

OUT="$HOME/Downloads/stage145_reclaim_plateau_phase3_latest.zip"
TMPDIR="$(mktemp -d)"
cleanup() { rm -rf "$TMPDIR"; }
trap cleanup EXIT

for f in \
  "$ROOT/reports/research_raw/stage90_mainline_event_alpha_matrix_latest.txt" \
  "$ROOT/reports/research_raw/stage90_mainline_event_alpha_matrix_latest.json" \
  "$ROOT/reports/research_raw/stage91_branch_event_alpha_matrix_latest.txt" \
  "$ROOT/reports/research_raw/stage91_branch_event_alpha_matrix_latest.json" \
  "$ROOT/reports/research_raw/stage145_reclaim_plateau_phase3_latest.txt" \
  "$ROOT/reports/research_raw/stage145_reclaim_plateau_phase3_latest.json" \
  "$ROOT/reports/research_raw/stage145_reclaim_plateau_phase3_manifest_latest.json" \
  "$ROOT/reports/research_raw/event_window_sweep_latest.txt" \
  "$ROOT/reports/research_raw/event_window_walkforward_latest.txt" \
  "$ROOT/reports/research_raw/stage120_event_window_frontier_latest.txt" \
  "$HOME/Downloads/okx_demo_report_latest.txt" \
  "$HOME/Downloads/branch_demo_report_latest.txt" \
  "$ROOT/okx_demo_report_latest.txt" \
  "$ROOT/branch_demo_report_latest.txt"; do
  if [ -f "$f" ]; then
    cp -f "$f" "$TMPDIR/"
  fi
done

"$PY" - "$OUT" "$TMPDIR" <<'PY3'
from pathlib import Path
import sys
import zipfile

out = Path(sys.argv[1]).expanduser()
tmpdir = Path(sys.argv[2])
out.parent.mkdir(parents=True, exist_ok=True)
files = sorted([p for p in tmpdir.iterdir() if p.is_file()])
if not files:
    empty = tmpdir / 'empty.txt'
    empty.write_text('stage145 export empty\n', encoding='utf-8')
    files = [empty]
if out.exists():
    out.unlink()
with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
    for p in files:
        zf.write(p, arcname=p.name)
print(out)
PY3

echo "stage145_reclaim_plateau_phase3_done"
