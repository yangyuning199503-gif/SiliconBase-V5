#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
DL="$HOME/Downloads"
RAW_DIR="$ROOT/reports/research_raw"
mkdir -p "$DL" "$RAW_DIR"
OUT_TXT="$RAW_DIR/stage111_joint_runtime_watch_latest.txt"
OUT_ZIP_DL="$DL/stage111_joint_runtime_watch_latest.zip"
OUT_ZIP_ROOT="$ROOT/reports/stage111_joint_runtime_watch_latest.zip"
TMPDIR="$(mktemp -d)"
cleanup(){ rm -rf "$TMPDIR"; }
trap cleanup EXIT
MAIN_REPORT="$DL/okx_demo_report_latest.txt"
BRANCH_REPORT="$DL/branch_demo_report_latest.txt"
MAIN_VER="$(grep -m1 '^- 当前版本:' "$MAIN_REPORT" 2>/dev/null | sed 's/^- 当前版本: //')"
MAIN_STATUS="$(grep -m1 '^- 当前状态:' "$MAIN_REPORT" 2>/dev/null | sed 's/^- 当前状态: //')"
MAIN_REASON="$(grep -m1 '^- 状态原因:' "$MAIN_REPORT" 2>/dev/null | sed 's/^- 状态原因: //')"
MAIN_SIG="$(grep -m1 '^- 最近策略信号时间' "$MAIN_REPORT" 2>/dev/null | sed 's/^- 最近策略信号时间([^)]*): //')"
BRANCH_VER="$(grep -m1 '^- 当前版本:' "$BRANCH_REPORT" 2>/dev/null | sed 's/^- 当前版本: //')"
BRANCH_STATUS="$(grep -m1 '^- 当前状态:' "$BRANCH_REPORT" 2>/dev/null | sed 's/^- 当前状态: //')"
BRANCH_REASON="$(grep -m1 '^- 状态原因:' "$BRANCH_REPORT" 2>/dev/null | sed 's/^- 状态原因: //')"
BRANCH_SIG="$(grep -m1 '^- 最近策略信号时间' "$BRANCH_REPORT" 2>/dev/null | sed 's/^- 最近策略信号时间([^)]*): //')"
BTC_TARGET="$(awk '/^\[BTC\]/{flag=1;next}/^\[/{flag=0}flag&&/^- 策略目标:/{print; exit}' "$BRANCH_REPORT" 2>/dev/null | sed 's/^- 策略目标: //')"
ETH_TARGET="$(awk '/^\[ETH\]/{flag=1;next}/^\[/{flag=0}flag&&/^- 策略目标:/{print; exit}' "$BRANCH_REPORT" 2>/dev/null | sed 's/^- 策略目标: //')"
SOL_TARGET="$(awk '/^\[SOL\]/{flag=1;next}/^\[/{flag=0}flag&&/^- 策略目标:/{print; exit}' "$BRANCH_REPORT" 2>/dev/null | sed 's/^- 策略目标: //')"
cat > "$OUT_TXT" <<EOF
Stage111 主线提频观察 + 第二分支三标的 preview 观察
generated_at_utc=$(date -u '+%Y-%m-%d %H:%M:%S UTC')

=== 主线 ===
- current_version=${MAIN_VER:-unknown}
- current_status=${MAIN_STATUS:-unknown}
- current_reason=${MAIN_REASON:--}
- latest_signal_time=${MAIN_SIG:--}
- keep_rule=mainline_live_base 继续；提频仍只看 combo_sr_soft_adx26_cd6_lb24_zone028_ref / combo_sr_soft_adx32_cd5_lb20_zone025，不直接切 live。

=== 第二分支 ===
- current_version=${BRANCH_VER:-unknown}
- current_status=${BRANCH_STATUS:-unknown}
- current_reason=${BRANCH_REASON:--}
- latest_signal_time=${BRANCH_SIG:--}
- expected_preview=r251_branch_demo_triple_book_preview__btc025_eth060_sol015_v1
- book_rule=BTC + ETH + SOL | BTC 确认腿 | ETH 主收益腿 | SOL research_only_on_demo
- btc_target=${BTC_TARGET:--}
- eth_target=${ETH_TARGET:--}
- sol_target=${SOL_TARGET:--}

=== 判定 ===
- mainline_keep_live=yes
- branch_triple_book_visible=$([ -n "${SOL_TARGET:-}" ] && echo yes || echo no)
- next_action=如果三标的 preview 稳定且 SOL 段已出现在报告里，下一轮再做主线/支线联动升级门槛判定。
EOF
cp -f "$OUT_TXT" "$TMPDIR/"
for f in \
  "$MAIN_REPORT" \
  "$BRANCH_REPORT" \
  "$ROOT/config_shortwave_triple_book_preview.yml" \
  "$ROOT/shadow_shortwave_triple_book_preview.yml" \
  "$ROOT/reports/research_raw/stage110_triple_book_repair_latest.txt" \
  "$ROOT/reports/research_raw/stage99_mainline_frequency_push_latest.txt" \
  "$ROOT/reports/research_raw/stage91_branch_event_alpha_matrix_latest.txt"; do
  if [ -f "$f" ]; then cp -f "$f" "$TMPDIR/"; fi
done
( cd "$TMPDIR" && zip -qr "$OUT_ZIP_DL" . )
cp -f "$OUT_ZIP_DL" "$OUT_ZIP_ROOT"
if [[ -x "$ROOT/cleanup_download_exports.sh" ]]; then
  bash "$ROOT/cleanup_download_exports.sh" "stage111_joint_runtime_watch_latest.zip" >/dev/null 2>&1 || true
fi
echo "[ok] $OUT_ZIP_DL"
