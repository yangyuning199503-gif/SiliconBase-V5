#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
OUT="$HOME/Downloads/stage104_joint_preview_latest.zip"
TMP_DIR="$(mktemp -d)"
cleanup() { rm -rf "$TMP_DIR"; }
trap cleanup EXIT

cp -f "$HOME/Downloads/okx_demo_report_latest.txt" "$TMP_DIR/" 2>/dev/null || true
cp -f "$HOME/Downloads/branch_demo_report_latest.txt" "$TMP_DIR/" 2>/dev/null || true
cp -f "$ROOT/config_shortwave_asset_integrated.yml" "$TMP_DIR/" 2>/dev/null || true
cp -f "$ROOT/shadow_shortwave_asset_integrated.yml" "$TMP_DIR/" 2>/dev/null || true
cp -f "$ROOT/reports/research_raw/stage102_joint_adjust_latest.txt" "$TMP_DIR/" 2>/dev/null || true
cp -f "$ROOT/reports/research_raw/stage103_asset_integrated_latest.txt" "$TMP_DIR/" 2>/dev/null || true

( cd "$TMP_DIR" && zip -qr "$OUT" . )
echo "$OUT"
