#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

PY="./.venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "未发现虚拟环境 .venv，请先运行一次 bash run.sh" >&2
  exit 1
fi

mkdir -p reports logs reports/research_raw

# 语法预检，避免浪费时间
"$PY" -m py_compile tools/overfit_check.py

echo "开始过拟合检查（robustness perturbation）..."
"$PY" tools/overfit_check.py --config config.yml

echo
if [ -f reports/overfit_check/overfit_check_table.csv ]; then
  echo "结果表：reports/overfit_check/overfit_check_table.csv"
fi
if [ -d reports/overfit_check ]; then
  cp -f reports/overfit_check/overfit_check_table.csv reports/research_raw/overfit_check_table_latest.csv 2>/dev/null || true
  cp -f reports/overfit_check/overfit_check_summary.txt reports/research_raw/overfit_check_summary_latest.txt 2>/dev/null || true
  echo "已复制：reports/research_raw/overfit_check_table_latest.csv"
  echo "已复制：reports/research_raw/overfit_check_summary_latest.txt"
fi
