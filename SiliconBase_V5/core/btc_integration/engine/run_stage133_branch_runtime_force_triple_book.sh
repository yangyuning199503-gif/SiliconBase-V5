#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PY="$ROOT/.venv/bin/python"
bootstrap_venv() {
  echo "Creating virtualenv .venv ..."
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

pick_cfg() {
  if [ -f "$ROOT/config_shortwave_triple_book_stage133.yml" ] && [ -f "$ROOT/shadow_shortwave_triple_book_stage133.yml" ]; then
    printf '%s\n' "$ROOT/config_shortwave_triple_book_stage133.yml"
    return 0
  fi
  if [ -f "$ROOT/config_shortwave_triple_book_stage113.yml" ] && [ -f "$ROOT/shadow_shortwave_triple_book_stage113.yml" ]; then
    printf '%s\n' "$ROOT/config_shortwave_triple_book_stage113.yml"
    return 0
  fi
  printf '%s\n' "$ROOT/config_shortwave_triple_book_preview.yml"
}

EXPECTED_CFG="$(pick_cfg)"
EXPECTED_VERSION="$($PY - "$EXPECTED_CFG" <<'PY2'
import sys, yaml
from pathlib import Path
p = Path(sys.argv[1])
obj = yaml.safe_load(p.read_text(encoding='utf-8')) or {}
print(((obj.get('system') or {}).get('version') or '').strip())
PY2
)"

"$PY" -m py_compile \
  "$ROOT/tools/okx_demo_autopilot.py" \
  "$ROOT/tools/stage120_event_window_frontier.py"

bash "$ROOT/start_branch_demo_triple_book.sh" --restart

REPORT="$HOME/Downloads/branch_demo_report_latest.txt"
for _ in $(seq 1 180); do
  if [ -f "$REPORT" ] && ! report_is_boot_placeholder "$REPORT"; then
    if { [ -z "$EXPECTED_VERSION" ] || grep -Fq "$EXPECTED_VERSION" "$REPORT"; } \
       && grep -Fq '[BTC]' "$REPORT" \
       && grep -Fq '[ETH]' "$REPORT" \
       && grep -Fq '[SOL]' "$REPORT"; then
      break
    fi
  fi
  sleep 1
 done

if [ ! -f "$REPORT" ] || report_is_boot_placeholder "$REPORT"; then
  echo "branch report not ready after stage133 restart" >&2
  exit 1
fi
if ! grep -Fq '[BTC]' "$REPORT" || ! grep -Fq '[ETH]' "$REPORT" || ! grep -Fq '[SOL]' "$REPORT"; then
  echo "branch runtime is still not triple-book after stage133 restart" >&2
  exit 1
fi
if [ -n "$EXPECTED_VERSION" ] && ! grep -Fq "$EXPECTED_VERSION" "$REPORT"; then
  echo "branch runtime version mismatch after stage133 restart" >&2
  exit 1
fi

"$PY" -u "$ROOT/tools/stage120_event_window_frontier.py" --project-dir "$ROOT"

OUT="$HOME/Downloads/stage133_branch_runtime_force_triple_book_latest.zip"
TMPDIR="$(mktemp -d)"
cleanup() { rm -rf "$TMPDIR"; }
trap cleanup EXIT

for f in \
  "$HOME/Downloads/branch_demo_report_latest.txt" \
  "$HOME/Downloads/okx_demo_report_latest.txt" \
  "$ROOT/reports/research_raw/stage120_event_window_frontier_latest.txt" \
  "$ROOT/reports/research_raw/stage91_branch_event_alpha_matrix_latest.txt" \
  "$ROOT/reports/research_raw/stage91_branch_event_alpha_matrix_latest.json" \
  "$ROOT/reports/research_raw/event_window_sweep_latest.txt" \
  "$ROOT/reports/research_raw/event_window_walkforward_latest.txt"; do
  if [ -f "$f" ]; then
    cp -f "$f" "$TMPDIR/"
  fi
done

"$PY" - "$OUT" "$TMPDIR" <<'PY2'
from pathlib import Path
import sys, zipfile
out = Path(sys.argv[1]).expanduser()
tmpdir = Path(sys.argv[2])
out.parent.mkdir(parents=True, exist_ok=True)
if out.exists():
    out.unlink()
with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
    for p in sorted(tmpdir.iterdir()):
        if p.is_file():
            zf.write(p, arcname=p.name)
print(out)
PY2

echo "stage133_branch_runtime_force_triple_book_done"
