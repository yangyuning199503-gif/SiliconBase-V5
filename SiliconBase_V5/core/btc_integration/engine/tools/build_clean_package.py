from __future__ import annotations

import argparse
import zipfile
from datetime import datetime
from pathlib import Path

EXCLUDE_PARTS = {'.venv', '.runtime', '.branch_shortwave_demo', '.mainline_shadow_demo', '__MACOSX', '__pycache__', '.pytest_cache'}
EXCLUDE_NAMES = {
    'chatgpt_bundle_latest.zip',
    'support_bundle_latest.zip',
    'deepseek_single_file_latest.txt',
    'deepseek_brief_latest.txt',
    'chatgpt_bundle_path_latest.txt',
}
EXCLUDE_SUFFIXES = {'.pyc', '.pyo', '.tmp'}
EXCLUDE_SUFFIX_PATTERNS = (
    '.repair_guard_backup',
    '.pre_repair_guard',
)
EXCLUDE_NAME_FRAGMENTS = (
    '.pre_stage',
)
EXCLUDE_REPORT_BASENAMES = {
    'okx_demo_probe_latest.json',
    'okx_demo_probe_latest.jsonl',
    'okx_demo_probe_latest.txt',
    'okx_demo_smoke_submit_latest.json',
    'okx_demo_smoke_submit_latest.jsonl',
    'okx_demo_smoke_submit_latest.txt',
}


def _skip(rel: Path) -> bool:
    parts = set(rel.parts)
    if parts & EXCLUDE_PARTS:
        return True
    if rel.name in EXCLUDE_NAMES:
        return True
    if rel.suffix in EXCLUDE_SUFFIXES:
        return True
    if rel.name.endswith(EXCLUDE_SUFFIX_PATTERNS):
        return True
    if any(frag in rel.name for frag in EXCLUDE_NAME_FRAGMENTS):
        return True
    if rel.name.startswith('.DS_Store'):
        return True
    if rel.parts[:1] == ('logs',):
        return True
    if rel.parts[:2] == ('reports', 'download_noise_archive'):
        return True
    if rel.parts[:1] == ('reports',) and len(rel.parts) >= 2 and rel.parts[1].startswith('run_'):
        return True
    if any(part.endswith('_tmp') or part.endswith('_artifacts') for part in rel.parts):
        return True
    if rel.parts[:1] == ('reports',) and rel.suffix in {'.zip', '.jsonl'}:
        return True
    return bool(rel.parts[:1] == ('reports',) and rel.name in EXCLUDE_REPORT_BASENAMES)


def build_zip(root: Path, out_zip: Path) -> None:
    root = root.resolve()
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_zip, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(root.rglob('*')):
            if not path.is_file():
                continue
            rel = path.relative_to(root)
            if _skip(rel):
                continue
            zf.write(path, arcname=str(Path(root.name) / rel))


def main() -> None:
    ap = argparse.ArgumentParser(description='Build a clean btc_system_v1 zip without runtime/venv/log/bundle artifacts.')
    ap.add_argument('--project-dir', default='.')
    ap.add_argument('--out', default='')
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    if root.name != 'btc_system_v1':
        raise SystemExit(f'zip root must be btc_system_v1, got: {root}')
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    out = Path(args.out).expanduser() if args.out else root / 'reports' / 'clean_packages' / f'btc_system_v1_clean_{stamp}.zip'
    if not out.is_absolute():
        out = (root / out).resolve()
    build_zip(root, out)
    print(out)


if __name__ == '__main__':
    main()
