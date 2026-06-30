#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PY="./.venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "未发现虚拟环境，请先运行一次：bash run.sh"
  exit 1
fi

"$PY" -m tools.portfolio_retest --base-config config.yml

DL="$HOME/Downloads"
if [ -d "$DL" ]; then
  cp -f reports/portfolio_retest_latest.txt "$DL/portfolio_retest_latest.txt" 2>/dev/null || true
  cp -f reports/portfolio_retest_latest.csv "$DL/portfolio_retest_latest.csv" 2>/dev/null || true
fi

echo "OK -> $DL/portfolio_retest_latest.txt"
