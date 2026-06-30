#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
PY="./.venv/bin/python"
if [ ! -x "$PY" ]; then
  PY="python3"
fi
"$PY" -m tools.align_backtest_end --project-dir . --config config.yml
"$PY" -m tools.repair_raw_from_snapshots --project-dir . --config config.yml >/dev/null || true

"$PY" -m tools.raw_data_guard --project-dir . --config config.yml
"$PY" -m tools.stage88_strategy_fusion_walkforward --project-dir .

for f in \
  reports/research_raw/stage88_mainline_fusion_walkforward_latest.txt \
  reports/research_raw/stage88_mainline_fusion_walkforward_latest.json; do
  if [ ! -s "$f" ]; then
    echo "[ERR] 缺少 $f" >&2
    exit 2
  fi
done
