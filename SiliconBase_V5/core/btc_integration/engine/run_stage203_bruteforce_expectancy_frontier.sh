#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
exec bash "$DIR/run_stage203_aggressive_winrate_risk_frontier.sh" "$@"
