#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
bash start_okx_demo.sh
bash start_branch_demo.sh
