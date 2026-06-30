#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
bash "$ROOT/run_stage91_switch_branch_demo.sh" eth_short_shock_fast_lb16_atr052_adx22_s078 --restart
