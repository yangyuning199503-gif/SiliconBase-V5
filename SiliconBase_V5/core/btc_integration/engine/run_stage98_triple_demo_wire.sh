#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
MAINLINE_SHADOW_CANDIDATE="${1:-${MAINLINE_SHADOW_CANDIDATE:-combo_sr_soft_adx26_cd6_lb24_zone028_ref}}"
BRANCH_CANDIDATE="${2:-${BRANCH_CANDIDATE:-eth_short_shock_fast_lb16_atr052_adx22_s078}}"

bootstrap_venv() {
  echo "Creating virtualenv .venv ..."
  rm -rf "$ROOT/.venv"
  python3 -m venv "$ROOT/.venv"
  PY="$ROOT/.venv/bin/python"
  "$PY" -m pip install --upgrade pip >/dev/null
  "$PY" -m pip install -r "$ROOT/requirements.txt" >/dev/null
  touch "$ROOT/.venv/.deps_installed"
}

if [ ! -x "$PY" ] || ! "$PY" -c 'import sys; print(sys.executable)' >/dev/null 2>&1; then
  bootstrap_venv
elif [ ! -f "$ROOT/.venv/.deps_installed" ] || [ "$ROOT/requirements.txt" -nt "$ROOT/.venv/.deps_installed" ]; then
  "$PY" -m pip install -r "$ROOT/requirements.txt" >/dev/null
  touch "$ROOT/.venv/.deps_installed"
fi

# 先刷新研究，再接三条线。
bash "$ROOT/run_stage81_82_walkforward.sh"
bash "$ROOT/run_stage90_event_alpha_sprint.sh"

# 确保主线 live 真正接 demo 提交。
python3 - <<'PY'
from pathlib import Path
import yaml
p = Path('shadow.yml')
obj = yaml.safe_load(p.read_text(encoding='utf-8')) or {}
shadow = obj.get('shadow', obj) if isinstance(obj, dict) else {}
if not isinstance(shadow, dict):
    shadow = {}
shadow['submit_orders'] = True
if isinstance(obj, dict) and 'shadow' in obj:
    obj['shadow'] = shadow
else:
    obj = shadow
p.write_text(yaml.safe_dump(obj, allow_unicode=True, sort_keys=False), encoding='utf-8')
print('[OK] shadow.yml submit_orders=true')
PY

bash "$ROOT/start_okx_demo.sh"

# 分支切到 ETH short fast，并重启。
export BRANCH_SUBMIT_ORDERS=1
bash "$ROOT/run_stage91_switch_branch_demo.sh" "$BRANCH_CANDIDATE" --restart

# 主线 shadow 独立 demo。
export MAINLINE_SHADOW_SUBMIT_ORDERS=1
bash "$ROOT/pause_mainline_shadow_demo.sh" || true
bash "$ROOT/start_mainline_shadow_demo.sh" "$MAINLINE_SHADOW_CANDIDATE"

"$PY" -m tools.stage98_triple_demo_wire --project-dir . --mainline-shadow-candidate "$MAINLINE_SHADOW_CANDIDATE" --branch-candidate "$BRANCH_CANDIDATE"
bash "$ROOT/run_send_files.sh"
echo "[OK] stage98 triple demo wire done"
