from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest.io import load_ohlcv_csv, read_config


def _canonicalize(path: Path) -> tuple[bool, int, int, str]:
    if not path.exists():
        return False, 0, 0, 'missing'
    try:
        raw_rows = max(sum(1 for _ in path.open('r', encoding='utf-8', errors='ignore')) - 1, 0)
    except Exception:
        raw_rows = 0
    df = load_ohlcv_csv(path)
    parsed_rows = int(len(df))
    if parsed_rows < 10:
        return False, raw_rows, parsed_rows, 'too_few_rows_after_parse'
    out = df.reset_index().rename(columns={df.index.name or 'index': 'time'})
    tmp = path.with_suffix(path.suffix + '.tmp')
    out.to_csv(tmp, index=False)
    tmp.replace(path)
    return True, raw_rows, parsed_rows, 'rewritten'


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--project-dir', default='.')
    ap.add_argument('--config', default='config.yml')
    ap.add_argument('--symbols', nargs='*', default=['btc','eth','sol','bnb'])
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    cfg = read_config(root / args.config) if (root / args.config).exists() else {}
    tmpl = str((cfg.get('data', {}) or {}).get('csv_template', 'data/raw/{symbol}_15m.csv'))

    ok = True
    for sym in args.symbols:
        path = root / tmpl.format(symbol=sym)
        good, raw_rows, parsed_rows, status = _canonicalize(path)
        if not good and status != 'missing':
            ok = False
        print(f'{sym}: {status} | raw_rows={raw_rows} | parsed_rows={parsed_rows} | file={path}')
    return 0 if ok else 2


if __name__ == '__main__':
    raise SystemExit(main())
