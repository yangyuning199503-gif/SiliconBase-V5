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
bootstrap_venv() {
  python3 -m venv .venv
  PY="./.venv/bin/python"
  "$PY" -m pip install --upgrade pip >/dev/null
  "$PY" -m pip install -r requirements.txt >/dev/null
  touch .venv/.deps_installed
}
needs_install() {
  "$PY" - <<'PYEOF' >/dev/null 2>&1
import importlib
for name in ["pandas", "numpy", "yaml", "requests"]:
    importlib.import_module(name)
PYEOF
}
if [ ! -x "$PY" ] || ! "$PY" -c 'import sys; print(sys.executable)' >/dev/null 2>&1; then
  bootstrap_venv
elif [ ! -f .venv/.deps_installed ] || [ requirements.txt -nt .venv/.deps_installed ]; then
  "$PY" -m pip install -r requirements.txt >/dev/null
  touch .venv/.deps_installed
elif ! needs_install; then
  "$PY" -m pip install -r requirements.txt >/dev/null
  touch .venv/.deps_installed
fi

echo "[1/5] 刷新免费源 + 消息面"
bash run_local_info_sources_test.sh
COINGLASS_HISTORY_REFRESH=1 bash run_message_stack_backtest.sh

echo "[2/5] Stage75 主线事件状态机（激进初筛）"
"$PY" -m tools.stage75_mainline_event_state_lab --project-dir . --candidate-names mainline_live_base,combo_sr_soft_adx26_cd6_lb24_zone028_ref,combo_sr_soft_adx28_cd6_lb24_zone028,mainline_core_satellite_event30,mainline_split_adx26_cd6_lb24_zone028

echo "[3/5] Stage76 分支事件状态机（激进初筛）"
"$PY" -m tools.stage76_branch_event_state_lab --project-dir . --candidate-names eth_shortwave_tight_shortonly,eth_short_shock_control_lb18_adx26_s074,eth_breakout_long_follow_lb18_atr055_adx24_s030,sol_fast_trend_lb16_shortonly,sol_fast_trend_short_guarded_lb18_atr060_adx24_s068,sol_short_shock_guarded_lb20_adx26_s058,sol_long_core_adx28_cd6_lb22_zone027_s038

echo "[4/5] Stage81/82 样本外复核（保守收口）"
"$PY" -m tools.stage81_mainline_walkforward_lab --project-dir . --candidate-names mainline_live_base,combo_sr_soft_adx26_cd6_lb24_zone028_ref,combo_sr_soft_adx28_cd6_lb24_zone028
"$PY" -m tools.stage82_branch_walkforward_lab --project-dir . --candidate-names eth_shortwave_tight_shortonly,eth_short_shock_control_lb18_adx26_s074,eth_breakout_long_follow_lb18_atr055_adx24_s030,sol_fast_trend_short_guarded_lb18_atr060_adx24_s068,sol_short_shock_guarded_lb20_adx26_s058,sol_long_core_adx28_cd6_lb22_zone027_s038

echo "[5/5] 刷新打包"
bash run_send_files.sh
