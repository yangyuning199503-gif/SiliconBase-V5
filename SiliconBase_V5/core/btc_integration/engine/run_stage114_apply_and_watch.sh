#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
TS="$(date +%Y%m%d_%H%M%S)"
BK="$ROOT/.runtime/stage114_apply_backup/$TS"
mkdir -p "$BK" "$ROOT/stage113" "$ROOT/.runtime"
for f in config_mainline_shadow_candidate.yml shadow_mainline_shadow_candidate.yml config_shortwave_candidate.yml shadow_shortwave_candidate.yml; do
  [ -f "$ROOT/$f" ] && cp -f "$ROOT/$f" "$BK/$f"
done
cp -f "$ROOT/stage113/config_mainline_stage113_shadow_eventbridge.yml" "$ROOT/config_mainline_shadow_candidate.yml"
cp -f "$ROOT/stage113/shadow_mainline_stage113_shadow_eventbridge.yml" "$ROOT/shadow_mainline_shadow_candidate.yml"
cp -f "$ROOT/stage113/config_shortwave_triple_book_stage113.yml" "$ROOT/config_shortwave_candidate.yml"
cp -f "$ROOT/stage113/shadow_shortwave_triple_book_stage113.yml" "$ROOT/shadow_shortwave_candidate.yml"
cat > "$ROOT/reports/research_raw/stage114_apply_latest.txt" <<EOF
Stage114 升级策略推进到模拟盘（安全版）
generated_at=$(date -u '+%Y-%m-%d %H:%M:%S UTC')
backup_dir=$BK
mainline_live=unchanged
mainline_shadow_candidate=config_mainline_shadow_candidate.yml <- stage113_eventbridge
branch_demo=restart_from_existing_candidate_config
branch_candidate=config_shortwave_candidate.yml <- stage113_triple_book
EOF
bash "$ROOT/pause_branch_demo.sh" >/dev/null 2>&1 || true
bash "$ROOT/start_shortwave_demo_existing_config.sh"
sleep 3
bash "$ROOT/export_stage114_apply_watch.sh" >/dev/null
printf '%s\n' "$HOME/Downloads/stage114_apply_watch_latest.zip"
