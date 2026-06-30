#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOWNLOADS="$HOME/Downloads"
ARCHIVE_ROOT="$ROOT/reports/download_noise_archive"
KEEP_EXTRA="${1:-}"
mkdir -p "$DOWNLOADS" "$ARCHIVE_ROOT"
STAMP="$(date +%Y%m%d_%H%M%S)"
DEST="$ARCHIVE_ROOT/$STAMP"
mkdir -p "$DEST"

should_keep() {
  local base="$1"
  case "$base" in
    okx_demo_report_latest.txt|branch_demo_report_latest.txt)
      return 0
      ;;
  esac
  if [[ -n "$KEEP_EXTRA" && "$base" == "$KEEP_EXTRA" ]]; then
    return 0
  fi
  return 1
}

moved=0
while IFS= read -r -d '' path; do
  base="$(basename "$path")"
  if should_keep "$base"; then
    continue
  fi
  mv -f "$path" "$DEST/"
  moved=$((moved+1))
done < <(
  find "$DOWNLOADS" -maxdepth 1 -type f \(
    -name 'stage*_latest.txt' -o
    -name 'stage*_latest.zip' -o
    -name 'stage*_latest.json' -o
    -name 'stage*_path_latest.txt' -o
    -name 'chatgpt_bundle_latest.zip' -o
    -name 'deepseek_single_file_latest.txt' -o
    -name '*_lab_latest.txt' -o
    -name '*_lab_latest.json' -o
    -name 'stage*_progress_latest.txt' -o
    -name 'stage*_focus_latest.zip' -o
    -name 'stage*_watch_latest.zip' -o
    -name 'stage*_key_files_latest.zip' -o
    -name 'stage*_joint_*_latest.zip' -o
    -name 'stage*_joint_*_latest.txt' -o
    -name 'stage*_plan_latest.zip' -o
    -name 'stage*_plan_latest.txt' -o
    -name 'stage*_upgrade_*_latest.zip' -o
    -name 'stage*_upgrade_*_latest.txt' -o
    -name 'btc_dual_branch_lab_latest.txt' -o
    -name 'btc_dual_branch_lab_latest.json'
  \) -print0
)

if [[ $moved -eq 0 ]]; then
  rmdir "$DEST" 2>/dev/null || true
  echo "[OK] Downloads 研究导出已清理 | 未发现需要归档的额外文件"
else
  echo "[OK] Downloads 研究导出已清理 | 已归档 $moved 个文件 -> $DEST"
fi
