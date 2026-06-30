#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"

bootstrap_venv() {
  echo "Creating virtualenv .venv ..."
  rm -rf "$ROOT/.venv"
  python3 -m venv "$ROOT/.venv"
  PY="$ROOT/.venv/bin/python"
  "$PY" -m pip install --upgrade pip >/dev/null
  "$PY" -m pip install -r "$ROOT/requirements.txt" >/dev/null
  touch "$ROOT/.venv/.deps_installed"
}

if [ ! -x "$PY" ] || ! "$PY" -c 'import sys; print(sys.executable)' >/dev/null 2>&1; then
  bootstrap_venv
elif [ ! -f "$ROOT/.venv/.deps_installed" ] || [ "$ROOT/requirements.txt" -nt "$ROOT/.venv/.deps_installed" ]; then
  "$PY" -m pip install -r "$ROOT/requirements.txt" >/dev/null
  touch "$ROOT/.venv/.deps_installed"
fi

CANDIDATE_NAME="${1:-}"
RESTART_FLAG="${2:-}"
if [ -z "$CANDIDATE_NAME" ]; then
  CANDIDATE_NAME="$($PY -m tools.pick_branch_demo_candidate --project-dir . --prefer-symbol eth --prefer-family short 2>/dev/null || true)"
fi
CANDIDATE_NAME="${CANDIDATE_NAME:-eth_short_shock_fast_lb16_atr052_adx22_s078}"
SUBMIT_FLAG="${BRANCH_SUBMIT_ORDERS:-1}"
SUBMIT_ARG="--submit-orders"
if [ "$SUBMIT_FLAG" = "0" ]; then
  SUBMIT_ARG="--no-submit-orders"
fi

$PY -m tools.build_branch_demo_candidate \
  --project-dir . \
  --candidate "$CANDIDATE_NAME" \
  --report-txt "~/Downloads/branch_demo_report_latest.txt" \
  --order-prefix "${BRANCH_ORDER_PREFIX:-okxb}" \
  "$SUBMIT_ARG"

echo "[OK] branch candidate switched: $CANDIDATE_NAME"
echo "config: $ROOT/config_shortwave_candidate.yml"
echo "shadow: $ROOT/shadow_shortwave_candidate.yml"
echo "report: ~/Downloads/branch_demo_report_latest.txt"

if [ "${BRANCH_SWITCH_RESTART:-0}" = "1" ] || [ "$RESTART_FLAG" = "--restart" ]; then
  bash "$ROOT/pause_branch_demo.sh" || true
  bash "$ROOT/start_branch_demo.sh" "$CANDIDATE_NAME"
fi
