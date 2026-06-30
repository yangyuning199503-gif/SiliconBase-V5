#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
CANON="$HOME/btc_system_v1"
if [ "$ROOT" != "$CANON" ] && [ -d "$CANON" ]; then
  echo "[ERR] 请在 ~/btc_system_v1 运行。当前目录: $ROOT" >&2
  exit 1
fi
cd "$ROOT"

PY="./.venv/bin/python"
"$PY" -m tools.align_backtest_end --project-dir . --config config.yml --config config_shortwave_candidate.yml

bash run_stage79_dual_window_monthlyized.sh
"$PY" -m tools.repair_raw_from_snapshots --project-dir . --config config.yml >/dev/null || true

"$PY" -m tools.raw_data_guard --project-dir . --config config.yml
if [ -f config_shortwave_candidate.yml ]; then
"$PY" -m tools.repair_raw_from_snapshots --project-dir . --config config_shortwave_candidate.yml >/dev/null || true

  "$PY" -m tools.raw_data_guard --project-dir . --config config_shortwave_candidate.yml
fi
"$PY" -m tools.stage81_mainline_walkforward_lab --project-dir .
"$PY" -m tools.stage82_branch_walkforward_lab --project-dir .
"$PY" -m tools.stage83_console_summary --project-dir .

for f in \
  reports/research_raw/stage81_mainline_walkforward_latest.txt \
  reports/research_raw/stage81_mainline_walkforward_latest.json \
  reports/research_raw/stage82_branch_walkforward_latest.txt \
  reports/research_raw/stage82_branch_walkforward_latest.json; do
  if [ ! -s "$f" ]; then
    echo "[ERR] 缺少 $f" >&2
    exit 2
  fi
done

bash run_send_files.sh

echo ""
echo "[CHECK] bundle 内容："
unzip -l "$HOME/Downloads/chatgpt_bundle_latest.zip" | egrep 'stage77_mainline_dual_window_latest|stage78_branch_dual_window_latest|stage81_mainline_walkforward_latest|stage82_branch_walkforward_latest|message_stack_backtest_latest|okx_demo_report_latest' || true

echo ""
echo "[OK] 请发这个：~/Downloads/chatgpt_bundle_latest.zip"
