from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest.engine import run_backtest_portfolio
from src.backtest.io import load_ohlcv_csv, read_config
from tools.raw_data_guard import validate_from_config


def _load_data(root: Path, cfg: dict[str, Any]) -> dict[str, pd.DataFrame]:
    data_cfg = cfg.get("data", {}) or {}
    symbols = [str(x).lower() for x in list(data_cfg.get("symbols", []))]
    tmpl = str(data_cfg.get("csv_template", "data/raw/{symbol}_15m.csv"))
    start = pd.to_datetime(data_cfg.get("start"), utc=True).tz_convert(None) if data_cfg.get("start") else None
    end = pd.to_datetime(data_cfg.get("end"), utc=True).tz_convert(None) if data_cfg.get("end") else None
    out: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        path = root / Path(tmpl.format(symbol=sym))
        if not path.exists():
            raise SystemExit(f"缺少原始数据：{path}")
        df = load_ohlcv_csv(path)
        if start is not None:
            df = df.loc[df.index >= start]
        if end is not None:
            df = df.loc[df.index <= end]
        out[sym] = df
    return out


def _needs_refresh(out_path: Path, root: Path, cfg: dict[str, Any], force: bool) -> bool:
    if force or (not out_path.exists()):
        return True
    base_mtime = out_path.stat().st_mtime
    deps = [
        root / "config.yml",
        root / "src" / "backtest" / "engine.py",
        root / "src" / "backtest" / "indicators.py",
        root / "src" / "main.py",
    ]
    data_cfg = cfg.get("data", {}) or {}
    symbols = [str(x).lower() for x in list(data_cfg.get("symbols", []))]
    tmpl = str(data_cfg.get("csv_template", "data/raw/{symbol}_15m.csv"))
    for sym in symbols:
        deps.append(root / Path(tmpl.format(symbol=sym)))
    return any(dep.exists() and dep.stat().st_mtime > base_mtime for dep in deps)


def main() -> None:
    ap = argparse.ArgumentParser(description="基于当前 config.yml 直接生成当前模拟盘主线的 baseline trades.csv")
    ap.add_argument("--project-dir", type=Path, default=Path("."))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    root = args.project_dir.expanduser().resolve()
    out_path = args.out.expanduser().resolve() if args.out.is_absolute() else (root / args.out).resolve()
    cfg = read_config(root / "config.yml")
    validate_from_config(root, root / "config.yml")
    if not _needs_refresh(out_path, root, cfg, bool(args.force)):
        try:
            rows = len(pd.read_csv(out_path))
        except Exception:
            rows = 0
        print(json.dumps({"ok": True, "refreshed": False, "out": str(out_path), "trades": rows}, ensure_ascii=False))
        return

    data = _load_data(root, cfg)
    _, trades, snapshot = run_backtest_portfolio(data=data, cfg=cfg)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df = trades.copy() if trades is not None else pd.DataFrame()
    df.to_csv(out_path, index=False, encoding="utf-8")
    print(json.dumps({
        "ok": True,
        "refreshed": True,
        "out": str(out_path),
        "trades": int(len(df)),
        "final_time": str(snapshot.get("final_time")) if isinstance(snapshot, dict) else "",
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
