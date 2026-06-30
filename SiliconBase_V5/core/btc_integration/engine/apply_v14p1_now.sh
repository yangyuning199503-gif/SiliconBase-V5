#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

bash pause_okx_demo.sh || true
bash pause_branch_demo.sh || true
sleep 1
bash start_okx_demo.sh
bash switch_branch_demo_to_fast_now.sh
