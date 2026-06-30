#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"
PY_BIN=""
if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PY_BIN="$ROOT_DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY_BIN="$(command -v python3)"
else
  PY_BIN="$(command -v python)"
fi
"$PY_BIN" "$ROOT_DIR/tools/stage112_joint_upgrade_gate.py"
echo "已生成: $HOME/Downloads/stage112_joint_upgrade_gate_latest.zip"
