#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ $# -lt 2 ]]; then
  echo "用法: bash run_with_single_export.sh <仅保留的Downloads文件名> <命令...>"
  echo "例子: bash run_with_single_export.sh stage108_joint_key_files_latest.zip bash run_stage108_joint_dual_track_opt.sh"
  exit 2
fi
KEEP_FILE="$(basename "$1")"
shift
STATUS=0
"$@" || STATUS=$?
bash "$ROOT/cleanup_download_exports.sh" "$KEEP_FILE" || true
if [[ -f "$HOME/Downloads/$KEEP_FILE" ]]; then
  echo "[OK] 本轮 Downloads 仅保留回传文件: ~/Downloads/$KEEP_FILE"
else
  echo "[WARN] 目标文件未在 Downloads 生成: ~/Downloads/$KEEP_FILE"
fi
exit "$STATUS"
