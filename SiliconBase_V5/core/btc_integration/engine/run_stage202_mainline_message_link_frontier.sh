#!/usr/bin/env bash
set -u -o pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
mkdir -p "$ROOT/reports/research_raw" "$HOME/Downloads"
OUT="$HOME/Downloads/stage202_mainline_message_link_frontier_latest.zip"
TMPDIR="$(mktemp -d)"
LOG="$TMPDIR/stage202_full_log.txt"
STATUS_TSV="$TMPDIR/stage202_step_status.tsv"
SUMMARY="$TMPDIR/stage202_mainline_message_link_frontier_latest.txt"
ANY_FAIL=0
cleanup() { :; }
trap cleanup EXIT

note() { printf '%s\n' "$*" | tee -a "$LOG"; }
run_step() {
  local name="$1"; shift
  note "[STEP] $name"
  if "$@" >>"$LOG" 2>&1; then
    printf '%s\tOK\n' "$name" >>"$STATUS_TSV"
  else
    printf '%s\tFAIL\n' "$name" >>"$STATUS_TSV"
    ANY_FAIL=1
  fi
}

bootstrap_venv() {
  rm -rf "$ROOT/.venv"
  python3 -m venv "$ROOT/.venv" >>"$LOG" 2>&1
  PY="$ROOT/.venv/bin/python"
  "$PY" -m pip install --upgrade pip >>"$LOG" 2>&1
  "$PY" -m pip install -r "$ROOT/requirements.txt" >>"$LOG" 2>&1
  touch "$ROOT/.venv/.deps_installed"
}

PY="$ROOT/.venv/bin/python"
: >"$LOG"
: >"$STATUS_TSV"
rm -f "$OUT"

note "stage202 export guard start"
note "ROOT=$ROOT"
note "PWD=$(pwd)"
note "DATE=$(date '+%F %T %Z')"

if [ ! -x "$PY" ] || ! "$PY" -c 'import sys; print(sys.executable)' >/dev/null 2>&1; then
  note "[INFO] bootstrap .venv"
  bootstrap_venv
elif [ ! -f "$ROOT/.venv/.deps_installed" ] || [ "$ROOT/requirements.txt" -nt "$ROOT/.venv/.deps_installed" ]; then
  note "[INFO] refresh requirements"
  "$PY" -m pip install -r "$ROOT/requirements.txt" >>"$LOG" 2>&1 || ANY_FAIL=1
  touch "$ROOT/.venv/.deps_installed"
fi
PY="$ROOT/.venv/bin/python"

REQUIRED=(
  "$ROOT/tools/repair_raw_from_snapshots.py"
  "$ROOT/tools/raw_data_guard.py"
  "$ROOT/tools/build_current_strategy_trades.py"
  "$ROOT/tools/message_stack_backtest.py"
  "$ROOT/tools/stage120_event_window_frontier.py"
  "$ROOT/tools/stage159_message_confirm_reclaim_cluster_frontier.py"
  "$ROOT/tools/stage160_mainline_overlay_hold_cluster_frontier.py"
  "$ROOT/tools/stage161_mainline_risk_budget_multiasset_link_frontier.py"
)
for f in "${REQUIRED[@]}"; do
  if [ ! -f "$f" ]; then
    note "[MISSING] $f"
    ANY_FAIL=1
  fi
done

if [ -x "$PY" ]; then
  run_step py_compile "$PY" -m py_compile \
    "$ROOT/tools/repair_raw_from_snapshots.py" \
    "$ROOT/tools/raw_data_guard.py" \
    "$ROOT/tools/build_current_strategy_trades.py" \
    "$ROOT/tools/message_stack_backtest.py" \
    "$ROOT/tools/stage120_event_window_frontier.py" \
    "$ROOT/tools/stage159_message_confirm_reclaim_cluster_frontier.py" \
    "$ROOT/tools/stage160_mainline_overlay_hold_cluster_frontier.py" \
    "$ROOT/tools/stage161_mainline_risk_budget_multiasset_link_frontier.py"

  run_step repair_raw "$PY" -m tools.repair_raw_from_snapshots --project-dir "$ROOT" --config config.yml
  run_step raw_guard "$PY" -m tools.raw_data_guard --project-dir "$ROOT" --config config.yml

  BASE_TRADES="$ROOT/reports/research_raw/current_demo_strategy_trades_latest.csv"
  MSG_TXT="$ROOT/reports/research_raw/message_stack_backtest_latest.txt"
  run_step build_current_strategy_trades "$PY" -m tools.build_current_strategy_trades --project-dir "$ROOT" --out "$BASE_TRADES" --force
  run_step message_stack_backtest "$PY" -m tools.message_stack_backtest --project-dir "$ROOT" --base-trades "$BASE_TRADES" --out "$MSG_TXT"

  [ -f "$BASE_TRADES" ] && cp -f "$BASE_TRADES" "$ROOT/reports/current_demo_strategy_trades_latest.csv" 2>/dev/null || true
  [ -f "$MSG_TXT" ] && cp -f "$MSG_TXT" "$ROOT/reports/message_stack_backtest_latest.txt" 2>/dev/null || true

  run_step stage120 "$PY" -u "$ROOT/tools/stage120_event_window_frontier.py" --project-dir "$ROOT"
  run_step stage159 "$PY" -u -m tools.stage159_message_confirm_reclaim_cluster_frontier --project-dir "$ROOT"
  run_step stage160 "$PY" -u -m tools.stage160_mainline_overlay_hold_cluster_frontier --project-dir "$ROOT"
  run_step stage161 "$PY" -u -m tools.stage161_mainline_risk_budget_multiasset_link_frontier --project-dir "$ROOT"
else
  note "[FAIL] python env unavailable"
  ANY_FAIL=1
fi

{
  echo "Stage202 mainline message-link frontier"
  echo "- 对外只会生成 1 个文件：stage202_mainline_message_link_frontier_latest.zip"
  echo "- 这不是单独 txt 报告任务。"
  echo "- 若本次中途失败，zip 内会带 full log。"
  echo "- overall_status=$([ "$ANY_FAIL" -eq 0 ] && echo OK || echo FAIL)"
  echo
  echo "[step_status]"
  if [ -s "$STATUS_TSV" ]; then
    cat "$STATUS_TSV"
  else
    echo "no steps recorded"
  fi
  echo
  echo "[key_outputs]"
  for f in \
    "$ROOT/reports/research_raw/message_stack_backtest_latest.txt" \
    "$ROOT/reports/research_raw/current_demo_strategy_trades_latest.csv" \
    "$ROOT/reports/research_raw/stage120_event_window_frontier_latest.txt" \
    "$ROOT/reports/research_raw/stage120_event_window_frontier_latest.json" \
    "$ROOT/reports/research_raw/event_window_sweep_latest.txt" \
    "$ROOT/reports/research_raw/event_window_sweep_latest.json" \
    "$ROOT/reports/research_raw/event_window_walkforward_latest.txt" \
    "$ROOT/reports/research_raw/event_window_walkforward_latest.json" \
    "$ROOT/reports/research_raw/stage90_mainline_event_alpha_matrix_latest.txt" \
    "$ROOT/reports/research_raw/stage90_mainline_event_alpha_matrix_latest.json" \
    "$ROOT/reports/research_raw/stage91_branch_event_alpha_matrix_latest.txt" \
    "$ROOT/reports/research_raw/stage91_branch_event_alpha_matrix_latest.json" \
    "$ROOT/reports/research_raw/stage159_message_confirm_reclaim_cluster_frontier_latest.txt" \
    "$ROOT/reports/research_raw/stage159_message_confirm_reclaim_cluster_frontier_latest.json" \
    "$ROOT/reports/research_raw/stage159_message_confirm_reclaim_cluster_frontier_manifest_latest.json" \
    "$ROOT/reports/research_raw/stage160_mainline_overlay_hold_cluster_frontier_latest.txt" \
    "$ROOT/reports/research_raw/stage160_mainline_overlay_hold_cluster_frontier_latest.json" \
    "$ROOT/reports/research_raw/stage160_mainline_overlay_hold_cluster_frontier_manifest_latest.json" \
    "$ROOT/reports/research_raw/stage161_mainline_risk_budget_multiasset_link_frontier_latest.txt" \
    "$ROOT/reports/research_raw/stage161_mainline_risk_budget_multiasset_link_frontier_latest.json" \
    "$ROOT/reports/research_raw/stage161_mainline_risk_budget_multiasset_link_frontier_manifest_latest.json" \
    "$HOME/Downloads/okx_demo_report_latest.txt" \
    "$HOME/Downloads/branch_demo_report_latest.txt" \
    "$ROOT/okx_demo_report_latest.txt" \
    "$ROOT/branch_demo_report_latest.txt"; do
    if [ -f "$f" ]; then
      printf 'OK\t%s\n' "$f"
    else
      printf 'MISS\t%s\n' "$f"
    fi
  done
} > "$SUMMARY"

for f in \
  "$SUMMARY" \
  "$LOG" \
  "$STATUS_TSV" \
  "$ROOT/reports/research_raw/message_stack_backtest_latest.txt" \
  "$ROOT/reports/research_raw/current_demo_strategy_trades_latest.csv" \
  "$ROOT/reports/research_raw/stage120_event_window_frontier_latest.txt" \
  "$ROOT/reports/research_raw/stage120_event_window_frontier_latest.json" \
  "$ROOT/reports/research_raw/event_window_sweep_latest.txt" \
  "$ROOT/reports/research_raw/event_window_sweep_latest.json" \
  "$ROOT/reports/research_raw/event_window_walkforward_latest.txt" \
  "$ROOT/reports/research_raw/event_window_walkforward_latest.json" \
  "$ROOT/reports/research_raw/stage90_mainline_event_alpha_matrix_latest.txt" \
  "$ROOT/reports/research_raw/stage90_mainline_event_alpha_matrix_latest.json" \
  "$ROOT/reports/research_raw/stage91_branch_event_alpha_matrix_latest.txt" \
  "$ROOT/reports/research_raw/stage91_branch_event_alpha_matrix_latest.json" \
  "$ROOT/reports/research_raw/stage159_message_confirm_reclaim_cluster_frontier_latest.txt" \
  "$ROOT/reports/research_raw/stage159_message_confirm_reclaim_cluster_frontier_latest.json" \
  "$ROOT/reports/research_raw/stage159_message_confirm_reclaim_cluster_frontier_manifest_latest.json" \
  "$ROOT/reports/research_raw/stage160_mainline_overlay_hold_cluster_frontier_latest.txt" \
  "$ROOT/reports/research_raw/stage160_mainline_overlay_hold_cluster_frontier_latest.json" \
  "$ROOT/reports/research_raw/stage160_mainline_overlay_hold_cluster_frontier_manifest_latest.json" \
  "$ROOT/reports/research_raw/stage161_mainline_risk_budget_multiasset_link_frontier_latest.txt" \
  "$ROOT/reports/research_raw/stage161_mainline_risk_budget_multiasset_link_frontier_latest.json" \
  "$ROOT/reports/research_raw/stage161_mainline_risk_budget_multiasset_link_frontier_manifest_latest.json" \
  "$HOME/Downloads/okx_demo_report_latest.txt" \
  "$HOME/Downloads/branch_demo_report_latest.txt" \
  "$ROOT/okx_demo_report_latest.txt" \
  "$ROOT/branch_demo_report_latest.txt"; do
  [ -f "$f" ] && cp -f "$f" "$TMPDIR/" 2>/dev/null || true
done

"$PY" - "$OUT" "$TMPDIR" <<'PY2' >>"$LOG" 2>&1
from pathlib import Path
import sys
import zipfile
out = Path(sys.argv[1]).expanduser()
tmpdir = Path(sys.argv[2])
out.parent.mkdir(parents=True, exist_ok=True)
files = sorted(p for p in tmpdir.iterdir() if p.is_file())
if out.exists():
    out.unlink()
with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
    for p in files:
        zf.write(p, arcname=p.name)
print(out)
PY2

note "OUTPUT=$OUT"
if [ "$ANY_FAIL" -eq 0 ]; then
  note "stage202_mainline_message_link_frontier_exported_ok"
else
  note "stage202_mainline_message_link_frontier_exported_with_failures"
fi
exit 0
