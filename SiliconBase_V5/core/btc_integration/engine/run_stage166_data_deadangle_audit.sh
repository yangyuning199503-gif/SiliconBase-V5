#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

if [[ ! -d .venv ]]; then
  echo "[stage166] 缺少 .venv，请先在系统根目录执行。" >&2
  exit 1
fi

mkdir -p reports/research_raw

./.venv/bin/python -m tools.stage166_data_deadangle_audit --project-dir "$ROOT_DIR"

echo "[stage166] 诊断完成：~/Downloads/stage166_data_deadangle_audit_latest.zip"
