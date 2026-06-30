#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
DL="$HOME/Downloads"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT_TXT="$DL/stage121_runtime_event_sync_latest.txt"
OUT_ZIP="$DL/stage121_runtime_event_sync_latest.zip"
BACKUP_DIR="$ROOT/.runtime/stage121_backup_$STAMP"
mkdir -p "$DL" "$ROOT/.runtime" "$BACKUP_DIR"

backup_if_exists() {
  local path="$1"
  if [ -f "$path" ]; then
    cp -f "$path" "$BACKUP_DIR/$(basename "$path")"
  fi
}

backup_if_exists "$ROOT/config.yml"
backup_if_exists "$ROOT/config_shortwave_triple_book_preview.yml"
backup_if_exists "$ROOT/shadow_shortwave_triple_book_preview.yml"
backup_if_exists "$ROOT/start_branch_demo.sh"
backup_if_exists "$ROOT/start_branch_demo_triple_book.sh"

cp -f "$ROOT/config_mainline_dynlev_fix8_lock18.yml" "$ROOT/config.yml"
if [ -f "$ROOT/config_shortwave_triple_book_stage113.yml" ]; then
  cp -f "$ROOT/config_shortwave_triple_book_stage113.yml" "$ROOT/config_shortwave_triple_book_preview.yml"
fi
if [ -f "$ROOT/shadow_shortwave_triple_book_stage113.yml" ]; then
  cp -f "$ROOT/shadow_shortwave_triple_book_stage113.yml" "$ROOT/shadow_shortwave_triple_book_preview.yml"
fi

python3 - <<'PY'
from pathlib import Path
import yaml, zipfile
root = Path(__file__).resolve().parent if '__file__' in globals() else Path.cwd()
dl = Path.home() / 'Downloads'
out_txt = dl / 'stage121_runtime_event_sync_latest.txt'
out_zip = dl / 'stage121_runtime_event_sync_latest.zip'

def load_yaml(path: Path):
    try:
        return yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    except Exception:
        return {}

main_cfg = load_yaml(root / 'config.yml')
branch_cfg = load_yaml(root / 'config_shortwave_triple_book_preview.yml')
main_ver = (((main_cfg.get('system') or {}).get('version')) or '-')
branch_ver = (((branch_cfg.get('system') or {}).get('version')) or '-')
branch_syms = (((branch_cfg.get('data') or {}).get('symbols')) or [])
branch_weights = (((branch_cfg.get('data') or {}).get('weights')) or {})
text = f'''Stage121 runtime/event sync
===========================

generated_at_local={Path.home()}
mainline_config_version={main_ver}
branch_config_version={branch_ver}
branch_symbols={branch_syms}
branch_weights={branch_weights}

Applied:
- config.yml <= config_mainline_dynlev_fix8_lock18.yml
- config_shortwave_triple_book_preview.yml <= config_shortwave_triple_book_stage113.yml (if present)
- shadow_shortwave_triple_book_preview.yml <= shadow_shortwave_triple_book_stage113.yml (if present)
- start_branch_demo.sh now defaults to start_branch_demo_triple_book.sh
- start_branch_demo_triple_book.sh now prefers stage113 config over preview

Manual next step (do not run if you want to keep current terminals untouched):
- bash start_okx_demo.sh
- bash start_branch_demo.sh
'''
out_txt.write_text(text, encoding='utf-8')
with zipfile.ZipFile(out_zip, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
    for name in [
        'stage121_runtime_event_sync_latest.txt',
    ]:
        zf.write(dl / name, arcname=name)
    for path in [
        root / 'config.yml',
        root / 'config_mainline_dynlev_fix8_lock18.yml',
        root / 'config_shortwave_triple_book_preview.yml',
        root / 'config_shortwave_triple_book_stage113.yml',
        root / 'shadow_shortwave_triple_book_preview.yml',
        root / 'shadow_shortwave_triple_book_stage113.yml',
        root / 'start_branch_demo.sh',
        root / 'start_branch_demo_triple_book.sh',
    ]:
        if path.exists():
            zf.write(path, arcname=path.name)
PY

echo "$OUT_TXT"
echo "$OUT_ZIP"
