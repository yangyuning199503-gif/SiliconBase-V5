#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

resolve_py() {
  if [[ -x "$ROOT/.venv/bin/python" ]]; then
    printf '%s\n' "$ROOT/.venv/bin/python"
    return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    printf '%s\n' "$(command -v python3)"
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    printf '%s\n' "$(command -v python)"
    return 0
  fi
  echo '[ERR] python/python3 not found' >&2
  exit 127
}

PY="$(resolve_py)"
"$PY" -m tools.build_clean_package --project-dir "$ROOT" "$@"
