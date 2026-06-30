#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PY="./.venv/bin/python"

if [ ! -x "$PY" ]; then
  echo "未发现虚拟环境 .venv，开始创建..."
  python3 -m venv .venv
  "$PY" -m pip install --upgrade pip >/dev/null
fi

# 确保依赖齐全
"$PY" -m pip install -r requirements.txt >/dev/null

echo "运行矩阵回测（btc_only / bnb_only / btc_bnb）..."
"$PY" -m tools.run_matrix --base-config config.yml

echo "完成。你可以直接发送 ~/Downloads/matrix_summary_latest.txt"
