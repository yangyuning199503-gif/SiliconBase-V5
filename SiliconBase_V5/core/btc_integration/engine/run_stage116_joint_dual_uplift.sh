#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
RAW="$ROOT/reports/research_raw"
mkdir -p "$RAW"
DOWNLOADS="$HOME/Downloads"
mkdir -p "$DOWNLOADS"
PROGRESS="$RAW/stage116_progress_latest.txt"
OUT_ZIP="$DOWNLOADS/stage116_joint_dual_uplift_latest.zip"

choose_python() {
  if [ -x "$ROOT/.venv/bin/python" ]; then
    echo "$ROOT/.venv/bin/python"
    return 0
  fi
  command -v python3
}

PY="$(choose_python)"

if [ ! -x "$PY" ]; then
  echo "python3 not found" >&2
  exit 1
fi

run_step() {
  local title="$1"
  shift
  {
    echo "[$(date '+%F %T')] $title"
    "$@"
    echo "[OK] $title"
    echo
  } | tee -a "$PROGRESS"
}

rm -f "$PROGRESS" "$OUT_ZIP"

echo "Stage116 联合推进：主线提频 + 支线三标的收益抬升（研究层，不动 live/demo）" | tee "$PROGRESS"
echo "输出文件: $OUT_ZIP" | tee -a "$PROGRESS"
echo | tee -a "$PROGRESS"

run_step "stage90 事件 alpha 矩阵" "$PY" -m tools.stage90_event_alpha_matrix --project-dir "$ROOT"
run_step "stage93 主线提频筛选" "$PY" -m tools.stage93_frequency_accel --project-dir "$ROOT"

{
  echo "[$(date '+%F %T')] BTC 双向实验室"
  if "$PY" -m tools.btc_dual_branch_lab --project-dir "$ROOT" --profile quick \
      --out "$RAW/btc_dual_branch_lab_latest.txt" \
      --json-out "$RAW/btc_dual_branch_lab_latest.json"; then
    echo "[OK] BTC 双向实验室"
  else
    echo "[WARN] BTC 双向实验室失败，已跳过；其余流程继续。"
  fi
  echo
} | tee -a "$PROGRESS"

run_step "stage92 ETH/SOL frontier" "$PY" -m tools.stage92_eth_sol_open_frontier --project-dir "$ROOT" --profile quick --wf-per-lane 2
run_step "stage116 单文件打包" "$PY" -m tools.stage116_joint_dual_uplift_pack --project-dir "$ROOT" --out-zip "$OUT_ZIP"

echo "[DONE] $OUT_ZIP" | tee -a "$PROGRESS"
