#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

bash run_stage171_system_preflight.sh
bash run.sh

if [ -f "$HOME/.okx_demo_env" ]; then
  ./.venv/bin/python -m tools.okx_demo_probe --project-dir .
  ./.venv/bin/python -m tools.okx_demo_smoke_submit --project-dir . --symbol BTC-USDT-SWAP --side buy --notional-usdt 20 --confirm-demo
else
  echo "[skip] ~/.okx_demo_env not found; OKX demo probe/smoke not executed."
fi
