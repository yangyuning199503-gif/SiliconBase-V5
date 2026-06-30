#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
RAW="$ROOT/reports/research_raw"
ARCHIVE="$ROOT/reports/download_noise_archive"
mkdir -p "$RAW" "$ARCHIVE" "$HOME/Downloads"
PROGRESS="$RAW/stage118_progress_latest.txt"
SUMMARY="$RAW/stage118_summary_latest.txt"
OUT="$HOME/Downloads/stage118_apply_stable_plan_latest.zip"
BRANCH_REPORT="$HOME/Downloads/branch_demo_report_latest.txt"
MAIN_REPORT="$HOME/Downloads/okx_demo_report_latest.txt"

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" | tee -a "$PROGRESS"
}

archive_old() {
  local f
  for f in "$OUT"; do
    if [ -f "$f" ]; then
      mv -f "$f" "$ARCHIVE/$(basename "$f")" 2>/dev/null || true
    fi
  done
}

wait_branch_preview() {
  local tries="${1:-80}"
  local sleep_s="${2:-1}"
  local i
  for i in $(seq 1 "$tries"); do
    if [ -f "$BRANCH_REPORT" ] && grep -Eq 'triple_book_preview|btc025_eth060_sol015|BTC / ETH / SOL|\[BTC\].*\[ETH\].*\[SOL\]' "$BRANCH_REPORT" 2>/dev/null; then
      return 0
    fi
    sleep "$sleep_s"
  done
  return 1
}

extract_summary() {
  ROOT_ENV="$ROOT" RAW_ENV="$RAW" SUMMARY_ENV="$SUMMARY" python3 - <<'PY'
from pathlib import Path
import os, re
raw = Path(os.environ['RAW_ENV'])
summary = Path(os.environ['SUMMARY_ENV'])
main_txt = (raw / 'stage81_mainline_walkforward_latest.txt').read_text(encoding='utf-8', errors='ignore') if (raw / 'stage81_mainline_walkforward_latest.txt').exists() else ''
branch_txt = (raw / 'stage82_branch_walkforward_latest.txt').read_text(encoding='utf-8', errors='ignore') if (raw / 'stage82_branch_walkforward_latest.txt').exists() else ''
okx_txt = (Path.home() / 'Downloads' / 'okx_demo_report_latest.txt').read_text(encoding='utf-8', errors='ignore') if (Path.home() / 'Downloads' / 'okx_demo_report_latest.txt').exists() else ''
br_txt = (Path.home() / 'Downloads' / 'branch_demo_report_latest.txt').read_text(encoding='utf-8', errors='ignore') if (Path.home() / 'Downloads' / 'branch_demo_report_latest.txt').exists() else ''

def pick_block(text, prefix):
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(prefix):
            return s
    return ''

def pick_field(text, label):
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(f'- {label}:'):
            return s.split(':', 1)[1].strip()
    return '-'
lines = []
lines.append('Stage118 稳定应用摘要')
lines.append('====================')
lines.append('')
ml = pick_block(main_txt, '- mainline_live_base:')
sh = pick_block(main_txt, '- combo_sr_soft_adx26_cd6_lb24_zone028_ref:')
eths = pick_block(branch_txt, '- eth_short:')
ethl = pick_block(branch_txt, '- eth_long:')
soll = pick_block(branch_txt, '- sol_long:')
sols = pick_block(branch_txt, '- sol_short:')
if ml:
    lines.append('【主线 live】')
    lines.append(ml)
if sh:
    lines.append('')
    lines.append('【主线提频 shadow 首选】')
    lines.append(sh)
if any([eths, ethl, soll, sols]):
    lines.append('')
    lines.append('【第二分支赛道】')
    for item in [eths, ethl, soll, sols]:
        if item:
            lines.append(item)
lines.append('')
lines.append('【当前 runtime】')
lines.append(f"- 主线版本: {pick_field(okx_txt, '当前版本')}")
lines.append(f"- 主线状态: {pick_field(okx_txt, '当前状态')} | {pick_field(okx_txt, '状态原因')}")
lines.append(f"- 分支版本: {pick_field(br_txt, '当前版本')}")
lines.append(f"- 分支状态: {pick_field(br_txt, '当前状态')} | {pick_field(br_txt, '状态原因')}")
summary.write_text('\n'.join(lines).rstrip() + '\n', encoding='utf-8')
PY
}

package_output() {
  ROOT_ENV="$ROOT" RAW_ENV="$RAW" OUT_ENV="$OUT" python3 - <<'PY'
from pathlib import Path
import os, zipfile
root = Path(os.environ['ROOT_ENV'])
raw = Path(os.environ['RAW_ENV'])
out = Path(os.environ['OUT_ENV'])
out.parent.mkdir(parents=True, exist_ok=True)
items = [
    raw / 'stage118_progress_latest.txt',
    raw / 'stage118_summary_latest.txt',
    raw / 'stage81_mainline_walkforward_latest.txt',
    raw / 'stage82_branch_walkforward_latest.txt',
    Path.home() / 'Downloads' / 'okx_demo_report_latest.txt',
    Path.home() / 'Downloads' / 'branch_demo_report_latest.txt',
    root / 'config_shortwave_triple_book_preview.yml',
    root / 'shadow_shortwave_triple_book_preview.yml',
]
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as zf:
    for p in items:
        if p.exists():
            zf.write(p, p.name)
print(out)
PY
}

archive_old
: > "$PROGRESS"
log 'Stage118 稳定应用：主线 live 不动，只把第二分支切到三标的 preview，并导出单文件。'

for req in \
  "$ROOT/config_shortwave_triple_book_preview.yml" \
  "$ROOT/shadow_shortwave_triple_book_preview.yml" \
  "$ROOT/start_branch_demo_triple_book.sh" \
  "$ROOT/switch_branch_demo_to_triple_book.sh"; do
  if [ ! -f "$req" ]; then
    log "[FAIL] 缺少文件: $req"
    extract_summary || true
    package_output >> "$PROGRESS" 2>&1 || true
    exit 2
  fi
done

log '主线保持不动。'
log '第二分支切到 BTC/ETH/SOL 三标的 preview。'
if bash "$ROOT/switch_branch_demo_to_triple_book.sh" >> "$PROGRESS" 2>&1; then
  log '[OK] 已发起第二分支三标的 preview 重启。'
else
  rc=$?
  log "[FAIL] 切换第二分支失败 | exit=$rc"
  extract_summary || true
  package_output >> "$PROGRESS" 2>&1 || true
  exit $rc
fi

if wait_branch_preview 90 1; then
  log '[OK] 已检测到第二分支报告切到三标的 preview。'
else
  log '[WARN] 90 秒内未在报告里读到三标的 preview 标记；已继续导出，便于定位。'
fi

extract_summary
package_output >> "$PROGRESS" 2>&1
log '[DONE] 已生成 stage118_apply_stable_plan_latest.zip'
