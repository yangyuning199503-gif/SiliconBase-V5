from __future__ import annotations

import math
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from pandas.errors import EmptyDataError

from .timeparse import parse_time_series


def read_config(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _parse_time_col(s: pd.Series) -> pd.DatetimeIndex:
    return parse_time_series(s)


def _empty_ohlcv_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["open", "high", "low", "close", "volume"],
        index=pd.DatetimeIndex([], name="time"),
    )


def load_ohlcv_csv(path: str | Path) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        return _empty_ohlcv_frame()
    try:
        if p.stat().st_size == 0:
            return _empty_ohlcv_frame()
    except OSError:
        return _empty_ohlcv_frame()

    try:
        df = pd.read_csv(p, low_memory=False)
    except EmptyDataError:
        return _empty_ohlcv_frame()

    # 兼容字段名大小写
    cols = {c.lower(): c for c in df.columns}
    need = ["time", "open", "high", "low", "close", "volume"]
    missing = [k for k in need if k not in cols]
    if missing:
        if df.empty:
            return _empty_ohlcv_frame()
        raise ValueError(f"CSV 缺少字段: {missing} | file={p}")

    df = df[[cols[k] for k in need]].rename(columns={cols[k]: k for k in need})
    df["time"] = _parse_time_col(df["time"])
    df = df.dropna(subset=["time"])
    df = df.sort_values("time")
    df = df.drop_duplicates("time", keep="last")
    df = df.set_index("time")

    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.dropna(subset=["open", "high", "low", "close"])
    return df


def save_csv(df: pd.DataFrame, path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(p, index=True, encoding="utf-8")


def _json_safe(obj: Any) -> Any:
    if obj is None or isinstance(obj, (str, bool, int)):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, complex):
        if abs(obj.imag) < 1e-12:
            real = float(obj.real)
            return real if math.isfinite(real) else None
        return {"real": float(obj.real), "imag": float(obj.imag)}
    if isinstance(obj, (np.generic,)):
        return _json_safe(obj.item())
    if isinstance(obj, (pd.Timestamp, datetime, date)):
        try:
            return obj.isoformat()
        except Exception:
            return str(obj)
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, pd.Series):
        return {str(k): _json_safe(v) for k, v in obj.to_dict().items()}
    if isinstance(obj, pd.DataFrame):
        return [_json_safe(row) for row in obj.to_dict(orient="records")]
    return str(obj)


def save_json(obj: Any, path: str | Path) -> None:
    import json
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + '.tmp')
    safe = _json_safe(obj)
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(safe, f, ensure_ascii=False, indent=2)
    tmp.replace(p)
