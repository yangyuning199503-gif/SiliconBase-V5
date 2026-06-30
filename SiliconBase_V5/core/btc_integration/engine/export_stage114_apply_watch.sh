#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
OUT="$HOME/Downloads/stage114_apply_watch_latest.zip"
TMP_DIR="$ROOT/reports/research_raw/stage114_apply_watch"
mkdir -p "$TMP_DIR"
cp -f "$HOME/Downloads/okx_demo_report_latest.txt" "$TMP_DIR/okx_demo_report_latest.txt" 2>/dev/null || true
cp -f "$HOME/Downloads/branch_demo_report_latest.txt" "$TMP_DIR/branch_demo_report_latest.txt" 2>/dev/null || true
cp -f "$ROOT/stage113/stage113_joint_apply_manifest_latest.txt" "$TMP_DIR/stage113_joint_apply_manifest_latest.txt" 2>/dev/null || true
cp -f "$ROOT/config_mainline_shadow_candidate.yml" "$TMP_DIR/config_mainline_shadow_candidate.yml" 2>/dev/null || true
cp -f "$ROOT/config_shortwave_candidate.yml" "$TMP_DIR/config_shortwave_candidate.yml" 2>/dev/null || true
( cd "$TMP_DIR" && zip -qr "$OUT" . )
echo "$OUT"
