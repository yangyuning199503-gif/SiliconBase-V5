#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
DL="$HOME/Downloads"
PROG="$DL/stage108_progress_latest.txt"
OUT_ZIP="$DL/stage108_joint_key_files_latest.zip"
mkdir -p "$DL" "$ROOT/reports/research_raw" "$ROOT/reports"
: > "$PROG"
log(){ printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$PROG" >/dev/null; }

MAINLINE_FORCE="${MAINLINE_FORCE:-0}"
ETHSOL_PROFILE="${ETHSOL_PROFILE:-quick}"
ETHSOL_WF_PER_LANE="${ETHSOL_WF_PER_LANE:-2}"
BTC_REFRESH="${BTC_REFRESH:-1}"

log 'stage108 start | joint mainline+branch targeted refresh'

resolve_py(){
  if [ -x "$ROOT/.venv/bin/python" ]; then
    echo "$ROOT/.venv/bin/python"
  elif command -v python3 >/dev/null 2>&1; then
    command -v python3
  else
    command -v python
  fi
}
PY_BIN="$(resolve_py)"

log 'preflight repair mixed/raw time columns'
"$PY_BIN" -m tools.repair_mixed_time_csv --project-dir "$ROOT" --config config.yml --symbols btc eth sol bnb >>"$PROG" 2>&1 || true

if [ "$MAINLINE_FORCE" = "1" ] || [ ! -f "$ROOT/reports/research_raw/stage99_mainline_frequency_push_latest.txt" ]; then
  log 'refresh mainline stage99'
  bash "$ROOT/run_stage99_mainline_frequency_push.sh" >>"$PROG" 2>&1
else
  log 'reuse current stage99 mainline focus'
fi

if [ "$BTC_REFRESH" = "1" ]; then
  log 'refresh BTC dual branch quick lab'
  if bash "$ROOT/run_btc_dual_branch_lab.sh" >>"$PROG" 2>&1; then
    log 'BTC quick lab done'
  else
    log 'BTC quick lab skipped/failed -> keep prior BTC leg artifacts and continue'
  fi
else
  log 'skip BTC refresh'
fi

log "refresh ETH/SOL open frontier | profile=${ETHSOL_PROFILE} wf_per_lane=${ETHSOL_WF_PER_LANE}"
bash "$ROOT/run_stage92_eth_sol_open_frontier.sh" "$ETHSOL_PROFILE" "$ETHSOL_WF_PER_LANE" >>"$PROG" 2>&1

log 'build stage107 joint upgrade plan'
bash "$ROOT/run_stage107_joint_upgrade_plan.sh" >>"$PROG" 2>&1

log 'export stage108 zip'
bash "$ROOT/export_stage108_joint_key_files.sh" >>"$PROG" 2>&1
log 'stage108 done'
