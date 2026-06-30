#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
exec bash "$DIR/start_branch_demo.sh" "$@"
