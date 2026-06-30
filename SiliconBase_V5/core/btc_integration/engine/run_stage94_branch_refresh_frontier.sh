#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
PROGRESS="$HOME/Downloads/stage94_progress_latest.txt"
REPORT="$ROOT/reports/research_raw/stage94_branch_refresh_frontier_latest.txt"

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
: > "$PROGRESS"
log() {
  local msg="$1"
  local ts
  ts="$(TZ=Asia/Shanghai date '+%Y-%m-%d %H:%M:%S')"
  echo "[$ts] $msg" | tee -a "$PROGRESS"
}

log "stage94 start"
log "step1 refresh ETH/SOL raw"
bash "$ROOT/refresh_branch_research_raw.sh" | tee -a "$PROGRESS"
log "step2 rerun stage91 branch event alpha"
"$PY" -m tools.stage91_branch_event_alpha_matrix --project-dir "$ROOT" | tee -a "$PROGRESS"
log "step3 rerun stage92 frontier"
"$PY" -m tools.stage92_eth_sol_open_frontier --project-dir "$ROOT" --profile quick --wf-per-lane 2 | tee -a "$PROGRESS"
log "step4 rerun stage93 summary"
"$PY" -m tools.stage93_frequency_accel --project-dir "$ROOT" | tee -a "$PROGRESS"
cat > "$REPORT" <<EOF
Stage94 分支刷新 + Frontier
===========================
生成时间(UTC+8): $(TZ=Asia/Shanghai date '+%Y-%m-%d %H:%M:%S')

已执行：
1. refresh_branch_research_raw.sh
2. tools.stage91_branch_event_alpha_matrix
3. tools.stage92_eth_sol_open_frontier --profile quick --wf-per-lane 2
4. tools.stage93_frequency_accel

关键输出：
- $ROOT/reports/research_raw/branch_raw_freshness_latest.txt
- $ROOT/reports/research_raw/stage91_branch_event_alpha_matrix_latest.txt
- $ROOT/reports/research_raw/stage92_eth_sol_open_frontier_latest.txt
- $ROOT/reports/research_raw/stage93_frequency_accel_latest.txt
- $HOME/Downloads/stage94_progress_latest.txt
EOF
log "step5 export key files"
bash "$ROOT/export_research_stage94_now.sh" | tee -a "$PROGRESS"
log "stage94 done"
echo "$REPORT"
