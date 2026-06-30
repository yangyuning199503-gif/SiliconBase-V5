#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
BRANCH_SWITCH_RESTART=1 bash "$ROOT/run_stage91_switch_branch_demo.sh"
