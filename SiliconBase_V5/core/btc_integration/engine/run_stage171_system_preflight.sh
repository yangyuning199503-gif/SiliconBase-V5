#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

WITH_OKX="0"
if [ "${1:-}" = "--with-okx" ]; then
  WITH_OKX="1"
fi

mkdir -p reports/research_raw logs "$HOME/Downloads"

PY="./.venv/bin/python"
bootstrap_venv() {
  echo "Creating virtualenv .venv ..."
  rm -rf .venv
  python3 -m venv .venv
  PY="./.venv/bin/python"
  "$PY" -m pip install --upgrade pip >/dev/null
}

if [ ! -x "$PY" ] || ! "$PY" -c 'import sys; print(sys.executable)' >/dev/null 2>&1; then
  bootstrap_venv
fi

MARKER=".venv/.deps_installed"
if [ ! -f "$MARKER" ] || [ requirements.txt -nt "$MARKER" ]; then
  "$PY" -m pip install -r requirements.txt >/dev/null
  touch "$MARKER"
fi

MAIN_CFG="config.yml"
BRANCH_CFG="config_shortwave_triple_book_preview.yml"
if [ -f "config_shortwave_triple_book_stage133.yml" ]; then
  BRANCH_CFG="config_shortwave_triple_book_stage133.yml"
elif [ -f "config_shortwave_triple_book_stage113.yml" ]; then
  BRANCH_CFG="config_shortwave_triple_book_stage113.yml"
fi

OUT_DIR="reports/research_raw/stage171_system_preflight_artifacts"
rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"
SUMMARY_TXT="reports/research_raw/stage171_system_preflight_latest.txt"
ZIP_OUT="$HOME/Downloads/stage171_system_preflight_latest.zip"

ok_main="PASS"
ok_branch="PASS"
ok_bash="PASS"
ok_py="PASS"
ok_okx_env="SKIP"
ok_okx_probe="SKIP"

echo "[1/6] bash syntax check"
{
  bash -n run_precheck.sh
  bash -n run.sh
  bash -n run_message_stack_backtest.sh
  bash -n start_okx_demo.sh
  bash -n start_branch_demo.sh
  bash -n start_branch_demo_triple_book.sh
} > "$OUT_DIR/bash_syntax.txt" 2>&1 || ok_bash="FAIL"

echo "[2/6] python compile check"
{
  "$PY" -m py_compile \
    src/main.py \
    src/backtest/engine.py \
    src/backtest/indicators.py \
    src/live/okx_shadow.py \
    tools/okx_demo_common.py \
    tools/okx_demo_probe.py \
    tools/okx_demo_smoke_submit.py \
    tools/okx_demo_shadow_exec.py \
    tools/okx_demo_runner.py \
    tools/okx_demo_autopilot.py \
    tools/message_combo_ab_backtest.py \
    tools/raw_data_guard.py \
    tools/repair_raw_from_snapshots.py
} > "$OUT_DIR/py_compile.txt" 2>&1 || ok_py="FAIL"

echo "[3/6] mainline raw repair + guard"
{
  "$PY" -m tools.repair_raw_from_snapshots --project-dir . --config "$MAIN_CFG" >/dev/null || true
  "$PY" -m tools.raw_data_guard --project-dir . --config "$MAIN_CFG"
} > "$OUT_DIR/mainline_raw_guard.txt" 2>&1 || ok_main="FAIL"

echo "[4/6] branch raw repair + guard"
{
  "$PY" -m tools.repair_raw_from_snapshots --project-dir . --config "$BRANCH_CFG" >/dev/null || true
  "$PY" -m tools.raw_data_guard --project-dir . --config "$BRANCH_CFG"
} > "$OUT_DIR/branch_raw_guard.txt" 2>&1 || ok_branch="FAIL"

if [ -f "$HOME/.okx_demo_env" ]; then
  ok_okx_env="PRESENT"
else
  ok_okx_env="MISSING"
fi

if [ "$WITH_OKX" = "1" ]; then
  echo "[5/6] okx demo probe"
  if [ "$ok_okx_env" = "PRESENT" ]; then
    {
      "$PY" -m tools.okx_demo_probe --project-dir .
    } > "$OUT_DIR/okx_probe_stdout.txt" 2>&1 || true
    cp -f reports/okx_demo_probe_latest.json "$OUT_DIR/okx_demo_probe_latest.json" 2>/dev/null || true
    if grep -q '"ok": true' "$OUT_DIR/okx_demo_probe_latest.json" 2>/dev/null; then
      ok_okx_probe="PASS"
    else
      ok_okx_probe="FAIL"
    fi
  else
    ok_okx_probe="SKIP_NO_ENV"
  fi
fi

echo "[6/6] write summary"
SYSTEM_GATE="PASS"
if [ "$ok_bash" != "PASS" ] || [ "$ok_py" != "PASS" ] || [ "$ok_main" != "PASS" ] || [ "$ok_branch" != "PASS" ]; then
  SYSTEM_GATE="FAIL"
fi
if [ "$WITH_OKX" = "1" ] && [ "$ok_okx_probe" = "FAIL" ]; then
  SYSTEM_GATE="FAIL"
fi

cat > "$SUMMARY_TXT" <<EOF2
Stage171 系统总检
时间: $(TZ=Asia/Shanghai date '+%Y-%m-%d %H:%M:%S')
根目录: $ROOT_DIR
主线配置: $MAIN_CFG
分支配置: $BRANCH_CFG

总状态: $SYSTEM_GATE
- bash syntax: $ok_bash
- python compile: $ok_py
- mainline raw guard: $ok_main
- branch raw guard: $ok_branch
- ~/.okx_demo_env: $ok_okx_env
- okx demo probe: $ok_okx_probe

说明:
- 这版先过系统，再谈策略。
- 默认不跑 OKX probe；若要连 API 一起测，用：bash run_stage171_system_preflight.sh --with-okx
- 上传我时，只传一个文件：~/Downloads/stage171_system_preflight_latest.zip
EOF2

cp -f "$SUMMARY_TXT" "$OUT_DIR/stage171_system_preflight_latest.txt"
rm -f "$ZIP_OUT"
(
  cd "$OUT_DIR/.."
  zip -qr "$ZIP_OUT" "$(basename "$OUT_DIR")"
)

echo "完成：$SUMMARY_TXT"
echo "上传文件：$ZIP_OUT"

if [ "$SYSTEM_GATE" != "PASS" ]; then
  exit 2
fi
