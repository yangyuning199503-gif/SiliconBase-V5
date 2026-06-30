#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
bash "$ROOT/run_branch_fusion_pick_now.sh"
bash "$ROOT/pause_okx_demo.sh" || true
sleep 1
bash "$ROOT/start_okx_demo.sh"
