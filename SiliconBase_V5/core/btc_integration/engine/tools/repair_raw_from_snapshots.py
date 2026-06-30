
from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections.abc import Iterable
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest.io import read_config
from tools.raw_data_guard import _summarize_symbol

_TIME_KEYS = ("time", "timestamp", "ts", "datetime", "date", "open_time")


def _find_time_col(df: pd.DataFrame) -> str:
    cols = {str(c).lower(): str(c) for c in df.columns}
    for key in _TIME_KEYS:
        if key in cols:
            return cols[key]
    raise ValueError(f"CSV 缺少时间列 | columns={list(df.columns)}")


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or not path.is_file() or path.stat().st_size <= 0:
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def _align_columns(snapshot_df: pd.DataFrame, raw_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    if snapshot_df.empty and raw_df.empty:
        return snapshot_df, raw_df, "time"
    base = snapshot_df if not snapshot_df.empty else raw_df
    time_col = _find_time_col(base)
    if snapshot_df.empty:
        snapshot_df = pd.DataFrame(columns=list(raw_df.columns))
    if raw_df.empty:
        raw_df = pd.DataFrame(columns=list(snapshot_df.columns))

    snap_t = _find_time_col(snapshot_df) if not snapshot_df.empty else time_col
    raw_t = _find_time_col(raw_df) if not raw_df.empty else time_col
    if snap_t != time_col and not snapshot_df.empty:
        snapshot_df = snapshot_df.rename(columns={snap_t: time_col})
    if raw_t != time_col and not raw_df.empty:
        raw_df = raw_df.rename(columns={raw_t: time_col})

    if list(snapshot_df.columns) == list(raw_df.columns):
        return snapshot_df, raw_df, time_col

    if len(snapshot_df.columns) == len(raw_df.columns) and list(snapshot_df.columns[1:]) == list(raw_df.columns[1:]):
        raw_df = raw_df.rename(columns={raw_df.columns[0]: snapshot_df.columns[0]})
        return snapshot_df, raw_df, time_col

    ordered_cols: list[str] = list(dict.fromkeys([*snapshot_df.columns, *raw_df.columns]))
    snapshot_df = snapshot_df.reindex(columns=ordered_cols)
    raw_df = raw_df.reindex(columns=ordered_cols)
    return snapshot_df, raw_df, time_col


def _merge_snapshot_with_tail(snapshot_path: Path, raw_path: Path) -> dict[str, Any]:
    snap_df = _read_csv(snapshot_path)
    raw_df = _read_csv(raw_path)
    snap_df, raw_df, time_col = _align_columns(snap_df, raw_df)

    if snap_df.empty and raw_df.empty:
        return {"changed": False, "reason": "both_empty", "rows": 0}
    if snap_df.empty:
        return {"changed": False, "reason": "snapshot_missing_or_empty", "rows": int(len(raw_df))}

    snap_ts = pd.to_datetime(snap_df[time_col], errors="coerce")
    raw_ts = pd.to_datetime(raw_df[time_col], errors="coerce") if not raw_df.empty else pd.Series(dtype="datetime64[ns]")
    snap_df = snap_df.loc[snap_ts.notna()].copy()
    snap_df[time_col] = pd.to_datetime(snap_df[time_col], errors="coerce")
    raw_df = raw_df.loc[raw_ts.notna()].copy() if not raw_df.empty else raw_df
    if not raw_df.empty:
        raw_df[time_col] = pd.to_datetime(raw_df[time_col], errors="coerce")

    if snap_df.empty:
        return {"changed": False, "reason": "snapshot_all_invalid_time", "rows": int(len(raw_df))}

    snap_max = pd.to_datetime(snap_df[time_col]).max()
    tail_df = raw_df.loc[pd.to_datetime(raw_df[time_col]) > snap_max].copy() if not raw_df.empty else raw_df
    merged = pd.concat([snap_df, tail_df], ignore_index=True)
    merged = merged.dropna(subset=[time_col]).drop_duplicates(subset=[time_col], keep="last").sort_values(time_col).reset_index(drop=True)

    out_df = merged.copy()
    out_df[time_col] = pd.to_datetime(out_df[time_col]).dt.strftime("%Y-%m-%d %H:%M:%S")

    changed = True
    if raw_path.exists() and raw_path.is_file() and raw_path.stat().st_size > 0:
        try:
            existing = _read_csv(raw_path)
            existing_t = _find_time_col(existing) if not existing.empty else time_col
            if not existing.empty and existing_t != time_col:
                existing = existing.rename(columns={existing_t: time_col})
            existing_cmp = existing.copy()
            if not existing_cmp.empty and time_col in existing_cmp.columns:
                existing_cmp[time_col] = pd.to_datetime(existing_cmp[time_col], errors="coerce").dt.strftime("%Y-%m-%d %H:%M:%S")
                existing_cmp = existing_cmp.dropna(subset=[time_col]).drop_duplicates(subset=[time_col], keep="last").sort_values(time_col).reset_index(drop=True)
                changed = not existing_cmp.equals(out_df)
        except Exception:
            changed = True

    if changed:
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile("w", encoding="utf-8", newline="", suffix=".csv", dir=str(raw_path.parent), delete=False) as tmp:
            tmp_path = Path(tmp.name)
            out_df.to_csv(tmp, index=False)
        tmp_path.replace(raw_path)

    return {
        "changed": changed,
        "reason": "merged_snapshot_plus_tail",
        "rows": int(len(out_df)),
        "first": str(out_df.iloc[0][time_col]) if len(out_df) else "-",
        "last": str(out_df.iloc[-1][time_col]) if len(out_df) else "-",
        "snapshot_rows": int(len(snap_df)),
        "tail_rows": int(len(tail_df)),
    }


def _iter_symbols(cfg: dict[str, Any]) -> Iterable[tuple[str, Path]]:
    data = cfg.get("data", {}) or {}
    tmpl = str(data.get("csv_template", "data/raw/{symbol}_15m.csv"))
    for sym in [str(x).lower() for x in list(data.get("symbols", [])) if str(x).strip()]:
        yield sym, Path(tmpl.format(symbol=sym))


def _ts_score(s: str | None) -> int:
    if not s:
        return 0
    try:
        return int(pd.Timestamp(s).timestamp())
    except Exception:
        return 0


def _metric_tuple(meta: dict[str, Any]) -> tuple[int, float, float, int, int]:
    ok = 1 if bool(meta.get("ok")) else 0
    coverage = float(meta.get("coverage") or 0.0)
    max_gap = meta.get("max_gap")
    try:
        gap_seconds = pd.Timedelta(str(max_gap)).total_seconds() if max_gap is not None else float("inf")
    except Exception:
        gap_seconds = float("inf")
    rows = int(meta.get("rows") or 0)
    last_ts = _ts_score(meta.get("last") or meta.get("end") or meta.get("first"))
    return (ok, coverage, -gap_seconds, rows, last_ts)


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


def _needs_snapshot_repair(before: dict[str, Any], snapshot_meta: dict[str, Any]) -> bool:
    if not bool(before.get("ok")):
        return True
    if not bool(snapshot_meta.get("ok")):
        return False

    before_first = _coerce_ts(before.get("first"))
    before_last = _coerce_ts(before.get("last"))
    snap_first = _coerce_ts(snapshot_meta.get("first"))
    snap_last = _coerce_ts(snapshot_meta.get("last"))
    step = pd.Timedelta(minutes=15)

    if snap_first is not None and before_first is not None and before_first > snap_first + step:
        return True
    if snap_last is not None and before_last is not None and before_last + step < snap_last:
        return True
    return int(before.get("rows") or 0) < int(snapshot_meta.get("rows") or 0)


def _copy_if_better(src: Path, dst: Path, *, min_coverage: float, max_gap_days: float) -> dict[str, Any]:
    src_meta = _summarize_symbol(src, min_coverage=min_coverage, max_gap_days=max_gap_days) if src.exists() else {"ok": False}
    dst_meta = _summarize_symbol(dst, min_coverage=min_coverage, max_gap_days=max_gap_days) if dst.exists() else {"ok": False}
    if _metric_tuple(src_meta) > _metric_tuple(dst_meta):
        if dst.exists():
            backup = dst.with_suffix(dst.suffix + ".repair_guard_backup")
            if not backup.exists():
                shutil.copy2(dst, backup)
        shutil.copy2(src, dst)
        return {"updated": True, "src": str(src), "dst": str(dst), "rows": src_meta.get("rows")}
    return {"updated": False, "src": str(src), "dst": str(dst), "rows": dst_meta.get("rows")}


def _repair_one(root: Path, symbol: str, raw_rel: Path, min_coverage: float, max_gap_days: float) -> dict[str, Any]:
    raw_path = raw_rel if raw_rel.is_absolute() else (root / raw_rel)
    snapshot_path = root / "data" / "raw_snapshots" / f"{symbol}_15m.best.csv"
    before = _summarize_symbol(raw_path, min_coverage=min_coverage, max_gap_days=max_gap_days)
    action = "skip"
    merge = None
    restore = None
    snapshot_meta = _summarize_symbol(snapshot_path, min_coverage=min_coverage, max_gap_days=max_gap_days) if snapshot_path.exists() else {"ok": False, "rows": 0, "reason": "missing_snapshot"}

    if snapshot_path.exists() and snapshot_path.is_file():
        needs_repair = (not raw_path.exists()) or raw_path.stat().st_size <= 0 or _needs_snapshot_repair(before, snapshot_meta)
        if needs_repair:
            backup = raw_path.with_suffix(raw_path.suffix + ".pre_repair_guard")
            if raw_path.exists() and not backup.exists():
                shutil.copy2(raw_path, backup)
            merge = _merge_snapshot_with_tail(snapshot_path, raw_path)
            action = "repaired" if merge.get("changed") else "validated"
            after_tmp = _summarize_symbol(raw_path, min_coverage=min_coverage, max_gap_days=max_gap_days)
            after_first = _coerce_ts(after_tmp.get("first"))
            after_last = _coerce_ts(after_tmp.get("last"))
            snap_first = _coerce_ts(snapshot_meta.get("first"))
            snap_last = _coerce_ts(snapshot_meta.get("last"))
            step = pd.Timedelta(minutes=15)
            preserves_head = (snap_first is None) or (after_first is not None and after_first <= snap_first + step)
            extends_latest = (snap_last is None) or (after_last is not None and after_last >= snap_last)
            keep_after = bool(after_tmp.get("ok")) and preserves_head and extends_latest
            if (not keep_after) and _metric_tuple(after_tmp) < max(_metric_tuple(before), _metric_tuple(snapshot_meta)):
                if backup.exists():
                    shutil.copy2(backup, raw_path)
                    restore = {"reverted": True, "reason": "repair_worse_than_before_or_snapshot", "backup": str(backup)}
                    action = "reverted"
                else:
                    restore = {"reverted": False, "reason": "repair_worse_but_no_backup"}
    after = _summarize_symbol(raw_path, min_coverage=min_coverage, max_gap_days=max_gap_days)

    snapshot_refresh = None
    if raw_path.exists() and raw_path.is_file() and after.get("rows"):
        snapshot_refresh = _copy_if_better(raw_path, snapshot_path, min_coverage=min_coverage, max_gap_days=max_gap_days)

    return {
        "symbol": symbol,
        "raw": str(raw_path),
        "snapshot": str(snapshot_path),
        "before": before,
        "snapshot_before": snapshot_meta,
        "action": action,
        "merge": merge,
        "restore": restore,
        "after": after,
        "snapshot_refresh": snapshot_refresh,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="当 raw 断层时，优先用 data/raw_snapshots/*.best.csv 回填，并拼接 raw 尾部新 bar；若修复反而更差，则自动回滚。")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--config", default="config.yml")
    ap.add_argument("--min-coverage", type=float, default=0.85)
    ap.add_argument("--max-gap-days", type=float, default=7.0)
    ap.add_argument("--print-json", action="store_true")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    cfg_path = Path(args.config).expanduser()
    if not cfg_path.is_absolute():
        cfg_path = (root / cfg_path).resolve()
    cfg = read_config(cfg_path)

    rows = [_repair_one(root, sym, raw_rel, float(args.min_coverage), float(args.max_gap_days)) for sym, raw_rel in _iter_symbols(cfg)]
    payload = {"project_dir": str(root), "config": str(cfg_path), "rows": rows}

    if args.print_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("原始数据快照修复")
        print(f"config={cfg_path}")
        print("")
        for row in rows:
            b = row.get("before", {}) or {}
            a = row.get("after", {}) or {}
            merge = row.get("merge", {}) or {}
            print(
                f"- {row['symbol']}: action={row.get('action')} | before={b.get('reason')} rows={b.get('rows', 0)} | after={a.get('reason')} rows={a.get('rows', 0)} | tail_rows={merge.get('tail_rows', 0)}"
            )


if __name__ == "__main__":
    main()
