#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
if ! bash "$DIR/refresh_mainline_raw.sh"; then
  echo "[WARN] 主线 raw 刷新失败，继续直接启动模拟盘。"
fi
bash "$DIR/start_okx_demo.sh"
