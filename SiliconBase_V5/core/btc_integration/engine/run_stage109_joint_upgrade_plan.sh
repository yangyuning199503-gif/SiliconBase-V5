#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY="$(command -v python3)"
fi
"$PY" -m tools.stage109_joint_upgrade_plan --project-dir .
if [[ -x "$ROOT/cleanup_download_exports.sh" ]]; then
  bash "$ROOT/cleanup_download_exports.sh" "stage109_joint_upgrade_plan_latest.zip" || true
fi
printf '%s\n' "[OK] 只回传这个文件: ~/Downloads/stage109_joint_upgrade_plan_latest.zip"
