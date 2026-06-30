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
  echo "Creating virtualenv .venv ..."
  rm -rf .venv
  python3 -m venv .venv
  PY="./.venv/bin/python"
  "$PY" -m pip install --upgrade pip >/dev/null
  "$PY" -m pip install -r requirements.txt >/dev/null
  touch .venv/.deps_installed
}
if [ ! -x "$PY" ] || ! "$PY" -c 'import sys; print(sys.executable)' >/dev/null 2>&1; then
  bootstrap_venv
elif [ ! -f .venv/.deps_installed ] || [ requirements.txt -nt .venv/.deps_installed ]; then
  "$PY" -m pip install -r requirements.txt >/dev/null
  touch .venv/.deps_installed
fi

echo "[1/5] Stage77 主线激进首轮（短名单）"
"$PY" -m tools.stage77_mainline_dual_window_lab --project-dir . --candidate-names \
mainline_live_base,combo_sr_soft_adx26_cd6_lb24_zone028_ref,combo_sr_soft_adx28_cd6_lb24_zone028,mainline_split_adx26_cd6_lb24_zone028,mainline_core_satellite_event30

echo "[2/5] Stage78 分支激进首轮（短名单）"
"$PY" -m tools.stage78_branch_dual_window_lab --project-dir . --candidate-names \
eth_short_shock_control_lb18_adx26_s074,eth_retest_short_trend_lb18_atr055_adx22_s072,sol_fast_trend_short_guarded_lb18_atr060_adx24_s068,sol_short_shock_guarded_lb20_adx26_s058,eth_breakout_long_guarded_lb20_atr060_adx26_s028,sol_pullback_long_core_adx24_cd6_lb20_zone025_s042

echo "[3/5] Stage81 主线保守复核（WF）"
"$PY" -m tools.stage81_mainline_walkforward_lab --project-dir . --candidate-names \
mainline_live_base,combo_sr_soft_adx26_cd6_lb24_zone028_ref,mainline_split_adx26_cd6_lb24_zone028,mainline_core_satellite_event30

echo "[4/5] Stage82 分支保守复核（WF）"
"$PY" -m tools.stage82_branch_walkforward_lab --project-dir . --candidate-names \
eth_short_shock_control_lb18_adx26_s074,eth_retest_short_trend_lb18_atr055_adx22_s072,sol_fast_trend_short_guarded_lb18_atr060_adx24_s068,sol_short_shock_guarded_lb20_adx26_s058,eth_breakout_long_guarded_lb20_atr060_adx26_s028,sol_pullback_long_core_adx24_cd6_lb20_zone025_s042

echo "[5/5] 刷新打包"
bash run_send_files.sh
