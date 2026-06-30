#!/usr/bin/env bash
set -u

ROOT="$(cd "$(dirname "$0")" && pwd)"
DOWNLOADS="$HOME/Downloads"
if [ ! -d "$DOWNLOADS" ]; then
  DOWNLOADS="$ROOT/reports/research_raw"
fi
OUT_ZIP="$DOWNLOADS/stage207_web_community_playbook_accel_latest.zip"
TMP_DIR="$ROOT/reports/research_raw/stage207_web_community_playbook_accel_tmp"
LOG="$TMP_DIR/stage207_full_log.txt"
STATUS="$TMP_DIR/stage207_step_status.tsv"
SUMMARY="$TMP_DIR/stage207_web_community_playbook_accel_latest.txt"
SNAP="$TMP_DIR/reports_snapshot"

mkdir -p "$TMP_DIR"
rm -rf "$TMP_DIR"/*
mkdir -p "$SNAP"
: > "$LOG"
: > "$STATUS"

run_step() {
  local name="$1"
  shift
  echo "[$(date '+%F %T')] START $name" >> "$LOG"
  if "$@" >> "$LOG" 2>&1; then
    printf '%s\tOK\n' "$name" >> "$STATUS"
    echo "[$(date '+%F %T')] OK    $name" >> "$LOG"
    return 0
  fi
  printf '%s\tFAIL\n' "$name" >> "$STATUS"
  echo "[$(date '+%F %T')] FAIL  $name" >> "$LOG"
  return 1
}

copy_if_exists() {
  local src="$1"
  local dst_dir="$2"
  if [ -f "$src" ]; then
    cp -f "$src" "$dst_dir/"
    return 0
  fi
  return 1
}

PY="$ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
  PY="python3"
fi

MAIN_CFG="config.yml"
BRANCH_CFG="config_shortwave_triple_book_preview.yml"
if [ -f "$ROOT/config_shortwave_triple_book_stage133.yml" ]; then
  BRANCH_CFG="config_shortwave_triple_book_stage133.yml"
elif [ -f "$ROOT/config_shortwave_triple_book_stage113.yml" ]; then
  BRANCH_CFG="config_shortwave_triple_book_stage113.yml"
fi

overall_status="OK"
system_gate="PASS"
rm -f "$OUT_ZIP"
rm -f \
  "$DOWNLOADS/stage189_regime_webblend_frontier_latest.zip" \
  "$DOWNLOADS/stage190_weblearned_multi_frequency_innovation_frontier_latest.zip" \
  "$DOWNLOADS/stage191_crosssignal_volmanaged_frontier_latest.zip" \
  "$DOWNLOADS/stage192_reclaim_pair_voltarget_frontier_latest.zip"

cd "$ROOT" || exit 1

if ! run_step py_compile "$PY" -m py_compile \
  "$ROOT/tools/stage189_regime_webblend_frontier.py" \
  "$ROOT/tools/stage190_weblearned_multi_frequency_innovation_frontier.py" \
  "$ROOT/tools/stage191_crosssignal_volmanaged_frontier.py" \
  "$ROOT/tools/stage192_reclaim_pair_voltarget_frontier.py" \
  "$ROOT/tools/stage120_event_window_frontier.py" \
  "$ROOT/tools/raw_data_guard.py" \
  "$ROOT/tools/repair_raw_from_snapshots.py"; then
  overall_status="PARTIAL_FAIL"
  system_gate="FAIL"
fi

if ! run_step mainline_raw_repair_guard bash -lc "cd '$ROOT' && '$PY' -m tools.repair_raw_from_snapshots --project-dir . --config '$MAIN_CFG' >/dev/null || true && '$PY' -m tools.raw_data_guard --project-dir . --config '$MAIN_CFG'"; then
  overall_status="PARTIAL_FAIL"
  system_gate="FAIL"
fi

if ! run_step branch_raw_repair_guard bash -lc "cd '$ROOT' && '$PY' -m tools.repair_raw_from_snapshots --project-dir . --config '$BRANCH_CFG' >/dev/null || true && '$PY' -m tools.raw_data_guard --project-dir . --config '$BRANCH_CFG'"; then
  overall_status="PARTIAL_FAIL"
  system_gate="FAIL"
fi

if [ "$system_gate" = "PASS" ]; then
  if ! run_step stage189_regime_webblend_frontier "$PY" -u "$ROOT/tools/stage189_regime_webblend_frontier.py" --project-dir "$ROOT"; then
    overall_status="PARTIAL_FAIL"
  fi
  if ! run_step stage190_weblearned_multi_frequency_innovation_frontier "$PY" -u "$ROOT/tools/stage190_weblearned_multi_frequency_innovation_frontier.py" --project-dir "$ROOT"; then
    overall_status="PARTIAL_FAIL"
  fi
  if ! run_step stage191_crosssignal_volmanaged_frontier "$PY" -u "$ROOT/tools/stage191_crosssignal_volmanaged_frontier.py" --project-dir "$ROOT"; then
    overall_status="PARTIAL_FAIL"
  fi
  if ! run_step stage192_reclaim_pair_voltarget_frontier "$PY" -u "$ROOT/tools/stage192_reclaim_pair_voltarget_frontier.py" --project-dir "$ROOT"; then
    overall_status="PARTIAL_FAIL"
  fi
  if ! run_step stage120_event_window_frontier "$PY" -u "$ROOT/tools/stage120_event_window_frontier.py" --project-dir "$ROOT"; then
    overall_status="PARTIAL_FAIL"
  fi
else
  printf '%s\tSKIP\n' stage189_regime_webblend_frontier >> "$STATUS"
  printf '%s\tSKIP\n' stage190_weblearned_multi_frequency_innovation_frontier >> "$STATUS"
  printf '%s\tSKIP\n' stage191_crosssignal_volmanaged_frontier >> "$STATUS"
  printf '%s\tSKIP\n' stage192_reclaim_pair_voltarget_frontier >> "$STATUS"
  printf '%s\tSKIP\n' stage120_event_window_frontier >> "$STATUS"
  echo "[$(date '+%F %T')] SKIP  web_community_frontiers because system_gate=FAIL" >> "$LOG"
fi

for f in \
  "$ROOT/reports/research_raw/stage189_regime_webblend_frontier_latest.txt" \
  "$ROOT/reports/research_raw/stage189_regime_webblend_frontier_latest.json" \
  "$ROOT/reports/research_raw/stage189_regime_webblend_frontier_manifest_latest.json" \
  "$ROOT/reports/research_raw/stage190_weblearned_multi_frequency_innovation_frontier_latest.txt" \
  "$ROOT/reports/research_raw/stage190_weblearned_multi_frequency_innovation_frontier_latest.json" \
  "$ROOT/reports/research_raw/stage190_weblearned_multi_frequency_innovation_frontier_manifest_latest.json" \
  "$ROOT/reports/research_raw/stage191_crosssignal_volmanaged_frontier_latest.txt" \
  "$ROOT/reports/research_raw/stage191_crosssignal_volmanaged_frontier_latest.json" \
  "$ROOT/reports/research_raw/stage191_crosssignal_volmanaged_frontier_manifest_latest.json" \
  "$ROOT/reports/research_raw/stage192_reclaim_pair_voltarget_frontier_latest.txt" \
  "$ROOT/reports/research_raw/stage192_reclaim_pair_voltarget_frontier_latest.json" \
  "$ROOT/reports/research_raw/stage192_reclaim_pair_voltarget_frontier_manifest_latest.json" \
  "$ROOT/reports/research_raw/stage90_mainline_event_alpha_matrix_latest.txt" \
  "$ROOT/reports/research_raw/stage90_mainline_event_alpha_matrix_latest.json" \
  "$ROOT/reports/research_raw/stage91_branch_event_alpha_matrix_latest.txt" \
  "$ROOT/reports/research_raw/stage91_branch_event_alpha_matrix_latest.json" \
  "$ROOT/reports/research_raw/stage120_event_window_frontier_latest.txt" \
  "$ROOT/reports/research_raw/message_stack_backtest_latest.txt" \
  "$HOME/Downloads/okx_demo_report_latest.txt" \
  "$HOME/Downloads/branch_demo_report_latest.txt"; do
  copy_if_exists "$f" "$SNAP" || true
done

rm -f \
  "$DOWNLOADS/stage189_regime_webblend_frontier_latest.zip" \
  "$DOWNLOADS/stage190_weblearned_multi_frequency_innovation_frontier_latest.zip" \
  "$DOWNLOADS/stage191_crosssignal_volmanaged_frontier_latest.zip" \
  "$DOWNLOADS/stage192_reclaim_pair_voltarget_frontier_latest.zip"

cat > "$SUMMARY" <<EOF2
Stage207 web community playbook accel

- 对外只生成 1 个文件：stage207_web_community_playbook_accel_latest.zip
- 先过轻量系统门：py_compile + raw repair/guard
- 系统门通过后，再跑：stage189 + stage190 + stage191 + stage192 + stage120
- 外部经验吸收方式：不直接抄观点，只把可量化的 4 类模式压进回测
- 4 类模式：
  1) liquidation/whale sweep + reclaim
  2) OI/funding/premium 极值 + 方向确认
  3) trend/range regime 切换后的 ladder/grid
  4) multi-frequency + cross-signal + vol-managed blend
- overall_status=$overall_status
- system_gate=$system_gate

[step_status]
$(cat "$STATUS")

[notes]
- 这版不动 demo runtime，不做下单链路动作；先把网络/论坛/电报/社区里能量化的重复模式压进 research frontier。
- 中间 stage189~192 各自生成的 zip 会在本轮结束后自动删掉，Downloads 只留 stage207 这一份。
- 若 system_gate 失败，本轮只保留诊断，不继续信任 frontier 结果。
EOF2

(
  cd "$TMP_DIR" || exit 1
  zip -qr "$OUT_ZIP" .
)

echo "$OUT_ZIP"
exit 0
