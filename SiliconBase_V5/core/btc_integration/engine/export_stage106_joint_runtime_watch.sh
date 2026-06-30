#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
DL="$HOME/Downloads"
RAW_DIR="$ROOT/reports/research_raw"
mkdir -p "$DL" "$RAW_DIR"
OUT_TXT="$RAW_DIR/stage106_joint_runtime_watch_latest.txt"
OUT_ZIP_DL="$DL/stage106_joint_runtime_watch_latest.zip"
OUT_ZIP_ROOT="$ROOT/reports/stage106_joint_runtime_watch_latest.zip"
TMPDIR="$(mktemp -d)"
cleanup(){ rm -rf "$TMPDIR"; }
trap cleanup EXIT
MAIN_REPORT="$DL/okx_demo_report_latest.txt"
BRANCH_REPORT="$DL/branch_demo_report_latest.txt"
MAIN_VER="$(grep -m1 '^- 当前版本:' "$MAIN_REPORT" 2>/dev/null | sed 's/^- 当前版本: //')"
MAIN_STATUS="$(grep -m1 '^- 当前状态:' "$MAIN_REPORT" 2>/dev/null | sed 's/^- 当前状态: //')"
MAIN_SIG="$(grep -m1 '^- 最近策略信号时间' "$MAIN_REPORT" 2>/dev/null | sed 's/^- 最近策略信号时间([^)]*): //')"
BRANCH_VER="$(grep -m1 '^- 当前版本:' "$BRANCH_REPORT" 2>/dev/null | sed 's/^- 当前版本: //')"
BRANCH_STATUS="$(grep -m1 '^- 当前状态:' "$BRANCH_REPORT" 2>/dev/null | sed 's/^- 当前状态: //')"
BRANCH_SIG="$(grep -m1 '^- 最近策略信号时间' "$BRANCH_REPORT" 2>/dev/null | sed 's/^- 最近策略信号时间([^)]*): //')"
BTC_TARGET="$(awk '/^\[BTC\]/{flag=1;next}/^\[/{flag=0}flag&&/^- 策略目标:/{print; exit}' "$BRANCH_REPORT" 2>/dev/null | sed 's/^- 策略目标: //')"
ETH_TARGET="$(awk '/^\[ETH\]/{flag=1;next}/^\[/{flag=0}flag&&/^- 策略目标:/{print; exit}' "$BRANCH_REPORT" 2>/dev/null | sed 's/^- 策略目标: //')"
cat > "$OUT_TXT" <<EOF
Stage106 主线+第二分支运行观察
generated_at_utc=$(date -u '+%Y-%m-%d %H:%M:%S UTC')

=== 主线 ===
- current_version=${MAIN_VER:-unknown}
- current_status=${MAIN_STATUS:-unknown}
- latest_signal_time=${MAIN_SIG:--}
- keep_rule=mainline_live_base keep running; frequency shadow still judged by stage99/stage100, not by abnormal stage102 zeros.

=== 第二分支 ===
- current_version=${BRANCH_VER:-unknown}
- current_status=${BRANCH_STATUS:-unknown}
- latest_signal_time=${BRANCH_SIG:--}
- expected_preview=r250_branch_demo_asset_integrated__btc035_eth065_preview_v1
- book_rule=BTC+ETH integrated preview | BTC weight 0.35 | ETH weight 0.65 | SOL research_only
- btc_target=${BTC_TARGET:--}
- eth_target=${ETH_TARGET:--}

=== 判定 ===
- mainline_should_not_switch_from_stage102=yes
- branch_preview_switched=$([ "${BRANCH_VER:-}" = "r250_branch_demo_asset_integrated__btc035_eth065_preview_v1" ] && echo yes || echo no)
- next_action=keep dual terminals unchanged; observe 2 full 15m bars, then re-evaluate whether BTC leg starts producing non-flat signals.
EOF
cp -f "$OUT_TXT" "$TMPDIR/"
for f in \
  "$MAIN_REPORT" \
  "$BRANCH_REPORT" \
  "$ROOT/config_shortwave_asset_integrated.yml" \
  "$ROOT/shadow_shortwave_asset_integrated.yml" \
  "$ROOT/reports/research_raw/stage103_asset_integrated_latest.txt" \
  "$ROOT/reports/research_raw/stage105_joint_parallel_latest.txt" \
  "$ROOT/reports/research_raw/stage99_mainline_frequency_push_latest.txt"; do
  if [ -f "$f" ]; then cp -f "$f" "$TMPDIR/"; fi
done
(cd "$TMPDIR" && zip -qr "$OUT_ZIP_DL" .)
cp -f "$OUT_ZIP_DL" "$OUT_ZIP_ROOT"
echo "$OUT_ZIP_DL" > "$DL/stage106_joint_runtime_watch_path_latest.txt"
echo "$OUT_ZIP_ROOT" >> "$DL/stage106_joint_runtime_watch_path_latest.txt"
echo "[ok] $OUT_ZIP_DL"
