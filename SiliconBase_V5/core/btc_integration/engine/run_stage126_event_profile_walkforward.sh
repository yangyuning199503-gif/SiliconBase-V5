#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PY="$ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
  PY="python3"
fi

REPORT_RAW="$ROOT/reports/research_raw"
mkdir -p "$REPORT_RAW"

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

"$PY" -m py_compile "$ROOT/tools/event_window_sweep.py" "$ROOT/tools/event_window_walkforward.py" "$ROOT/tools/stage120_event_window_frontier.py"

TRADES_PATH="$(find_latest_trades || true)"
if [ -z "$TRADES_PATH" ] || [ ! -f "$TRADES_PATH" ]; then
  RUN_ID="stage126_$(date +%Y%m%d_%H%M%S)"
  "$PY" -m src.main --config "$ROOT/config.yml" --run-id "$RUN_ID"
  TRADES_PATH="$ROOT/reports/run_${RUN_ID}/trades.csv"
fi

"$PY" -u -m tools.event_window_sweep --project-dir "$ROOT" --trades-csv "$TRADES_PATH" --out "$REPORT_RAW/event_window_sweep_latest.txt"
"$PY" -u -m tools.event_window_walkforward --project-dir "$ROOT" --trades-csv "$TRADES_PATH" --out "$REPORT_RAW/event_window_walkforward_latest.txt"
"$PY" -u "$ROOT/tools/stage120_event_window_frontier.py" --project-dir "$ROOT"

OUT="$HOME/Downloads/stage126_event_profile_walkforward_latest.zip"
TMPDIR="$(mktemp -d)"
cleanup() { rm -rf "$TMPDIR"; }
trap cleanup EXIT

for f in \
  "$ROOT/reports/research_raw/stage90_mainline_event_alpha_matrix_latest.txt" \
  "$ROOT/reports/research_raw/stage90_mainline_event_alpha_matrix_latest.json" \
  "$ROOT/reports/research_raw/stage91_branch_event_alpha_matrix_latest.txt" \
  "$ROOT/reports/research_raw/stage91_branch_event_alpha_matrix_latest.json" \
  "$ROOT/reports/research_raw/event_window_sweep_latest.txt" \
  "$ROOT/reports/research_raw/event_window_walkforward_latest.txt" \
  "$ROOT/reports/research_raw/stage120_event_window_frontier_latest.txt" \
  "$ROOT/reports/research_raw/stage120_progress_latest.txt" \
  "$ROOT/reports/research_raw/stage75_mainline_event_state_latest.txt" \
  "$ROOT/reports/research_raw/stage75_mainline_event_state_latest.json" \
  "$HOME/Downloads/okx_demo_report_latest.txt" \
  "$HOME/Downloads/branch_demo_report_latest.txt" \
  "$ROOT/okx_demo_report_latest.txt" \
  "$ROOT/branch_demo_report_latest.txt"; do
  if [ -f "$f" ]; then
    cp -f "$f" "$TMPDIR/"
  fi
done

"$PY" - "$OUT" "$TMPDIR" <<'PY'
from pathlib import Path
import sys
import zipfile

out = Path(sys.argv[1]).expanduser()
tmpdir = Path(sys.argv[2])
out.parent.mkdir(parents=True, exist_ok=True)
files = sorted([p for p in tmpdir.iterdir() if p.is_file()])
if not files:
    empty = tmpdir / 'empty.txt'
    empty.write_text('stage126 export empty\n', encoding='utf-8')
    files = [empty]
if out.exists():
    out.unlink()
with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
    for p in files:
        zf.write(p, arcname=p.name)
print(out)
PY

echo "stage126_event_profile_walkforward_done"
