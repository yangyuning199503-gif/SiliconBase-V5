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

mkdir -p reports/research_raw

"$PY" -m tools.stage90_event_alpha_matrix --project-dir .

cat > reports/research_raw/stage96_priority_refresh_latest.txt <<EOF
Stage96 优先级刷新
=================
生成时间(UTC): $(date -u '+%Y-%m-%d %H:%M:%S UTC')
动作:
- 仅重跑 stage90/stage91
- 继续固定 6年 / 近2年 / WF 口径
- 当前目标: 主线提频优先, 分支继续 ETH short fast / 保留 ETH long / SOL long / SOL short
EOF

bash run_send_files.sh

echo ""
echo "[CHECK] bundle 内容："
unzip -l "$HOME/Downloads/chatgpt_bundle_latest.zip" | egrep 'stage81_mainline_walkforward_latest|stage82_branch_walkforward_latest|stage90_mainline_event_alpha_matrix_latest|stage91_branch_event_alpha_matrix_latest|branch_demo_report_latest|okx_demo_report_latest' || true

echo ""
echo "[TOP] 主线："
grep -E 'mainline_live_base|combo_sr_soft_adx26_cd6_lb24_zone028_ref|combo_sr_soft_adx32_cd5_lb20_zone025' reports/research_raw/stage90_mainline_event_alpha_matrix_latest.txt || true

echo ""
echo "[TOP] 分支："
grep -E 'eth_short_shock_fast_lb16_atr052_adx22_s078|eth_short_shock_lb16_adx24|eth_retest_short_trend_lb20_atr060_adx24_s068|=== 各赛道当前最优 ===|ETH \| short|ETH \| long|SOL \| long|SOL \| short' reports/research_raw/stage91_branch_event_alpha_matrix_latest.txt || true

echo ""
echo "[OK] 只回传: ~/Downloads/chatgpt_bundle_latest.zip"
