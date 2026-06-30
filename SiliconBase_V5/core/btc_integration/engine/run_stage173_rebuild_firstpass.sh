#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

WITH_OKX=0
WITH_RESEARCH=0
for arg in "$@"; do
  case "$arg" in
    --with-okx) WITH_OKX=1 ;;
    --with-research) WITH_RESEARCH=1 ;;
  esac
done

echo "[1/3] 系统预检"
if [ "$WITH_OKX" = "1" ]; then
  bash run_stage171_system_preflight.sh --with-okx
else
  bash run_stage171_system_preflight.sh
fi

echo "[2/3] 主线回测"
bash run.sh

if [ "$WITH_RESEARCH" = "1" ]; then
  echo "[3/3] 联合前沿"
  bash run_stage172_joint_frontier_bundle.sh
else
  echo "[3/3] 跳过联合前沿（如需跑，追加 --with-research）"
fi

echo "DONE"
