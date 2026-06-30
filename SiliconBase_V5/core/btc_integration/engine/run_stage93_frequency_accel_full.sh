#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
STAGE93_FORCE_FULL=1 bash "$ROOT/run_stage93_frequency_accel.sh"
