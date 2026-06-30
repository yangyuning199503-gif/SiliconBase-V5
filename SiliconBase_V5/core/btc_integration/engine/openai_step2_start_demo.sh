#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [ ! -f "$HOME/.okx_demo_env" ]; then
  echo "[stop] ~/.okx_demo_env not found; cannot start OKX demo."
  exit 2
fi

bash start_okx_demo.sh
bash start_branch_demo.sh
