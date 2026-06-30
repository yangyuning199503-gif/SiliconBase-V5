#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
DL="$HOME/Downloads"
RAW="$ROOT/reports/research_raw"
TMPDIR="$(mktemp -d)"
cleanup(){ rm -rf "$TMPDIR"; }
trap cleanup EXIT
OUT_DL="$DL/stage108_joint_key_files_latest.zip"
OUT_ROOT="$ROOT/reports/stage108_joint_key_files_latest.zip"
mkdir -p "$DL" "$ROOT/reports"
for f in \
  "$DL/okx_demo_report_latest.txt" \
  "$DL/branch_demo_report_latest.txt" \
  "$RAW/stage99_mainline_frequency_push_latest.txt" \
  "$RAW/stage91_branch_event_alpha_matrix_latest.txt" \
  "$RAW/stage92_eth_sol_open_frontier_latest.txt" \
  "$RAW/stage107_joint_upgrade_plan_latest.txt" \
  "$RAW/stage107_joint_upgrade_plan_latest.json" \
  "$ROOT/config_shortwave_triple_book_plan.yml" \
  "$ROOT/shadow_shortwave_triple_book_plan.yml"; do
  if [ -f "$f" ]; then cp -f "$f" "$TMPDIR/"; fi
done
(cd "$TMPDIR" && zip -qr "$OUT_DL" .)
cp -f "$OUT_DL" "$OUT_ROOT"
echo "$OUT_DL" > "$DL/stage108_joint_key_files_path_latest.txt"
echo "$OUT_ROOT" >> "$DL/stage108_joint_key_files_path_latest.txt"
echo "$OUT_DL"
