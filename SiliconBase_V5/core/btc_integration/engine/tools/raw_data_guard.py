from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest.io import read_config
from src.backtest.timeparse import parse_time_series

DEFAULT_MIN_COVERAGE = 0.85
DEFAULT_MAX_GAP_DAYS = 7.0


def _time_col_name(path: Path) -> str:
    try:
        head = pd.read_csv(path, nrows=0)
    except Exception as exc:
        raise SystemExit(f"无法读取 CSV 表头：{path} | {exc}") from exc
    cols = {str(c).lower(): str(c) for c in list(head.columns)}
    for key in ("time", "timestamp", "ts", "datetime", "date", "open_time"):
        if key in cols:
            return cols[key]
    raise SystemExit(f"CSV 缺少时间列：{path} | columns={list(head.columns)}")


def _parse_times(path: Path, time_col: str) -> pd.DatetimeIndex:
    try:
        s = pd.read_csv(path, usecols=[time_col], low_memory=False)[time_col]
    except Exception as exc:
        raise SystemExit(f"无法读取时间列：{path} | {exc}") from exc
    idx = pd.DatetimeIndex(parse_time_series(s).dropna())
    idx = idx.sort_values().drop_duplicates()
    return idx


def _summarize_symbol(path: Path, *, min_coverage: float, max_gap_days: float) -> dict[str, Any]:
    if not path.exists():
        return {
            "ok": False,
            "file": str(path),
            "reason": "missing_file",
        }
    try:
        size = path.stat().st_size
    except OSError as exc:
        return {"ok": False, "file": str(path), "reason": f"stat_failed:{exc}"}
    if size <= 0:
        return {"ok": False, "file": str(path), "reason": "empty_file", "size": size}

    time_col = _time_col_name(path)
    idx = _parse_times(path, time_col)
    rows = int(len(idx))
    if rows < 2:
        return {
            "ok": False,
            "file": str(path),
            "size": size,
            "rows": rows,
            "reason": "too_few_rows",
        }

    diffs = pd.Series(idx).diff().dropna()
    if diffs.empty:
        return {
            "ok": False,
            "file": str(path),
            "size": size,
            "rows": rows,
            "reason": "no_diffs",
        }
    mode_vals = diffs.mode()
    typical = mode_vals.iloc[0] if not mode_vals.empty else diffs.median()
    if pd.isna(typical) or typical <= pd.Timedelta(0):
        return {
            "ok": False,
            "file": str(path),
            "size": size,
            "rows": rows,
            "reason": "invalid_step",
        }

    span = idx[-1] - idx[0]
    expected_rows = int(span / typical) + 1 if span >= pd.Timedelta(0) else rows
    expected_rows = max(expected_rows, rows)
    coverage = float(rows / expected_rows) if expected_rows else 1.0
    max_gap = diffs.max()
    bad_reasons: list[str] = []
    if coverage < float(min_coverage):
        bad_reasons.append(f"coverage<{min_coverage:.0%}")
    if max_gap > pd.Timedelta(days=float(max_gap_days)):
        bad_reasons.append(f"max_gap>{max_gap_days:g}d")

    return {
        "ok": len(bad_reasons) == 0,
        "file": str(path),
        "size": size,
        "rows": rows,
        "first": str(idx[0]),
        "last": str(idx[-1]),
        "typical_step": str(typical),
        "expected_rows": expected_rows,
        "coverage": coverage,
        "max_gap": str(max_gap),
        "reason": ";".join(bad_reasons) if bad_reasons else "ok",
    }


def _resolve_config(root: Path, cfg_arg: str | None) -> Path:
    raw = str(cfg_arg or "config.yml")
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = (root / p).resolve()
    return p


def _symbols_from_cfg(cfg: dict[str, Any]) -> list[str]:
    data = cfg.get("data", {}) or {}
    symbols = [str(x).lower() for x in list(data.get("symbols", [])) if str(x).strip()]
    return symbols


def _coerce_ts(val: Any) -> pd.Timestamp | None:
    try:
        if val in (None, "", "-"):
            return None
        ts = pd.Timestamp(val)
        if pd.isna(ts):
            return None
        return ts
    except Exception:
        return None


def _apply_snapshot_floor(row: dict[str, Any], snapshot_meta: dict[str, Any]) -> dict[str, Any]:
    if not bool(snapshot_meta.get("ok")):
        return row
    step = pd.Timedelta(minutes=15)
    first = _coerce_ts(row.get("first"))
    last = _coerce_ts(row.get("last"))
    snap_first = _coerce_ts(snapshot_meta.get("first"))
    snap_last = _coerce_ts(snapshot_meta.get("last"))
    reasons = [r for r in str(row.get("reason") or "").split(";") if r and r != "ok"]

    if snap_first is not None and first is not None and first > snap_first + step:
        reasons.append("missing_head_vs_snapshot")
    if snap_last is not None and last is not None and last + step < snap_last:
        reasons.append("missing_tail_vs_snapshot")

    row["snapshot_rows"] = int(snapshot_meta.get("rows") or 0)
    row["snapshot_first"] = snapshot_meta.get("first")
    row["snapshot_last"] = snapshot_meta.get("last")
    if reasons:
        row["ok"] = False
        row["reason"] = ";".join(dict.fromkeys(reasons))
    return row


def validate_from_config(
    project_dir: Path,
    config_path: Path,
    *,
    min_coverage: float = DEFAULT_MIN_COVERAGE,
    max_gap_days: float = DEFAULT_MAX_GAP_DAYS,
) -> dict[str, Any]:
    root = project_dir.expanduser().resolve()
    cfg = read_config(config_path)
    data_cfg = cfg.get("data", {}) or {}
    tmpl = str(data_cfg.get("csv_template", "data/raw/{symbol}_15m.csv"))
    symbols = _symbols_from_cfg(cfg)
    if not symbols:
        raise SystemExit(f"配置里没有 data.symbols：{config_path}")
    rows: list[dict[str, Any]] = []
    for sym in symbols:
        path = root / Path(tmpl.format(symbol=sym))
        row = _summarize_symbol(path, min_coverage=min_coverage, max_gap_days=max_gap_days)
        snapshot_path = root / "data" / "raw_snapshots" / f"{sym}_15m.best.csv"
        if snapshot_path.exists():
            snapshot_meta = _summarize_symbol(snapshot_path, min_coverage=min_coverage, max_gap_days=max_gap_days)
            row = _apply_snapshot_floor(row, snapshot_meta)
        row["symbol"] = sym
        rows.append(row)
    return {
        "ok": all(bool(x.get("ok")) for x in rows),
        "project_dir": str(root),
        "config": str(config_path),
        "min_coverage": float(min_coverage),
        "max_gap_days": float(max_gap_days),
        "rows": rows,
    }


def _fmt(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("原始数据连续性检查")
    lines.append(f"config={payload.get('config')}")
    lines.append(f"min_coverage={payload.get('min_coverage'):.0%} | max_gap_days={payload.get('max_gap_days')}")
    lines.append("")
    for row in payload.get("rows", []):
        if row.get("ok"):
            lines.append(
                f"- {row.get('symbol')}: OK | rows={row.get('rows')} | {row.get('first')} -> {row.get('last')} | coverage={float(row.get('coverage', 0.0)):.2%} | max_gap={row.get('max_gap')}"
            )
        else:
            lines.append(
                f"- {row.get('symbol')}: FAIL | reason={row.get('reason')} | rows={row.get('rows', 0)} | file={row.get('file')} | coverage={float(row.get('coverage', 0.0)):.2%} | max_gap={row.get('max_gap', '-') }"
            )
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="检查原始 15m CSV 是否存在严重断层/覆盖不足")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--config", default="config.yml")
    ap.add_argument("--min-coverage", type=float, default=DEFAULT_MIN_COVERAGE)
    ap.add_argument("--max-gap-days", type=float, default=DEFAULT_MAX_GAP_DAYS)
    ap.add_argument("--print-json", action="store_true")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    cfg_path = _resolve_config(root, args.config)
    payload = validate_from_config(
        root,
        cfg_path,
        min_coverage=float(args.min_coverage),
        max_gap_days=float(args.max_gap_days),
    )
    if args.print_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(_fmt(payload), end="")
    if not payload.get("ok"):
        raise SystemExit(
            "检测到原始数据存在严重断层/覆盖不足；请先在你的电脑刷新对应 raw CSV，再继续回测或启动 Demo。"
        )


if __name__ == "__main__":
    main()
