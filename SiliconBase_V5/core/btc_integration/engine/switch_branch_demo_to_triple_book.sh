#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "[1/2] 主线保持不动；仅切第二分支到 BTC/ETH/SOL 三标的 preview ..."
bash "$ROOT/pause_branch_demo.sh" || true
sleep 1

echo "[2/2] 启动第二分支三标的 preview ..."
bash "$ROOT/start_branch_demo_triple_book.sh" --restart
