#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
echo "[1/2] 启动主线模拟盘"
bash "$DIR/start_okx_demo.sh"
echo "[2/2] 启动分支模拟盘"
bash "$DIR/start_branch_demo_now.sh"
echo "完成。"
echo "主线报告: ~/Downloads/okx_demo_report_latest.txt"
echo "分支报告: ~/Downloads/branch_demo_report_latest.txt"
