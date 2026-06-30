#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "[1/4] 主线不动，只处理第二分支 ..."
bash "$ROOT/hard_stop_branch_demo_all.sh"
sleep 1

echo "[2/4] 启动 BTC+ETH 资产腿第二分支预览 ..."
bash "$ROOT/start_branch_demo_asset_integrated.sh" restart

echo "[3/4] 等待分支报告切到 asset_integrated 版本 ..."
REPORT="$HOME/Downloads/branch_demo_report_latest.txt"
ready=0
for _ in $(seq 1 120); do
  if [ -f "$REPORT" ] && grep -q 'btc035_eth065_preview_v1' "$REPORT" 2>/dev/null; then
    ready=1
    break
  fi
  sleep 1
done

if [ "$ready" = "1" ]; then
  echo "[4/4] 已切到 BTC+ETH 资产腿预览。"
else
  echo "[4/4] 分支已重启，但报告还没切到新版本；先继续等 1 根 15m 再导出。"
fi

echo "导出：bash export_stage105_joint_preview.sh"
