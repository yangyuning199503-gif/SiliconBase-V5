#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# Stage121: make the default branch launcher point to the BTC/ETH/SOL triple-book demo.
exec bash "$DIR/start_branch_demo_triple_book.sh" "$@"
