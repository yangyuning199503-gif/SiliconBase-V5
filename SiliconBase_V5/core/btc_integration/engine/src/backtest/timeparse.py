from __future__ import annotations

import math
import re
from typing import Any

import numpy as np
import pandas as pd

_NUMERIC_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?$")
_CALENDAR_INT_RE = re.compile(r"^\d{8}(?:\d{4}|\d{6})?$")
_NULL_WORDS = {"time", "timestamp", "ts", "datetime", "date", "nan", "none", "null", "nat"}


def _epoch_unit_from_abs(v: float) -> str:
    if v >= 1e17:
        return "ns"
    if v >= 1e14:
        return "us"
    if v >= 1e11:
        return "ms"
    return "s"


def _parse_text_mixed(value: Any) -> pd.Timestamp:
    try:
        ts = pd.to_datetime(value, utc=True, errors="coerce", format="mixed")
    except TypeError:
        ts = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(ts):
        return pd.NaT
    if isinstance(ts, pd.Series):
        raise TypeError("unexpected series")
    return ts.tz_convert(None)


def _to_naive_utc(parsed: pd.Series | pd.DatetimeIndex) -> pd.Series:
    ser = pd.Series(parsed)
    if hasattr(ser.dt, "tz") and ser.dt.tz is not None:
        ser = ser.dt.tz_convert(None)
    return ser


def _parse_one(value: Any) -> pd.Timestamp:
    if value is None or value is pd.NaT:
        return pd.NaT
    try:
        if pd.isna(value):
            return pd.NaT
    except Exception:
        pass

    if isinstance(value, pd.Timestamp):
        ts = value
        if ts.tzinfo is None:
            try:
                ts = ts.tz_localize("UTC")
            except Exception:
                return pd.NaT
        else:
            ts = ts.tz_convert("UTC")
        return ts.tz_convert(None)

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            v = float(value)
        except Exception:
            return pd.NaT
        if math.isnan(v) or math.isinf(v):
            return pd.NaT
        unit = _epoch_unit_from_abs(abs(v))
        ts = pd.to_datetime(v, unit=unit, utc=True, errors="coerce")
        return pd.NaT if pd.isna(ts) else ts.tz_convert(None)

    text = str(value).strip()
    if not text or text.lower() in _NULL_WORDS:
        return pd.NaT

    if _CALENDAR_INT_RE.fullmatch(text):
        ts = _parse_text_mixed(text)
        if not pd.isna(ts):
            return ts

    if _NUMERIC_RE.fullmatch(text):
        try:
            v = float(text)
        except Exception:
            v = None
        if v is not None and not math.isnan(v) and not math.isinf(v):
            unit = _epoch_unit_from_abs(abs(v))
            ts = pd.to_datetime(v, unit=unit, utc=True, errors="coerce")
            if not pd.isna(ts):
                return ts.tz_convert(None)

    return _parse_text_mixed(text)


def parse_time_series(s: pd.Series) -> pd.DatetimeIndex:
    ser = pd.Series(s, copy=False)
    raw = ser.astype("string")
    stripped = raw.str.strip()
    lower = stripped.str.lower()

    out = pd.Series(pd.NaT, index=ser.index, dtype="datetime64[ns]")
    null_mask = stripped.isna() | (stripped == "") | lower.isin(_NULL_WORDS)

    calendar_mask = stripped.str.fullmatch(_CALENDAR_INT_RE.pattern, na=False)
    numeric_mask = stripped.str.fullmatch(_NUMERIC_RE.pattern, na=False)
    epoch_mask = (~null_mask) & numeric_mask & (~calendar_mask)
    text_mask = (~null_mask) & (~epoch_mask)

    if epoch_mask.any():
        nums = pd.to_numeric(stripped[epoch_mask], errors="coerce")
        finite = nums.notna() & np.isfinite(nums.to_numpy())
        nums = nums[finite]
        abs_nums = nums.abs()
        unit_masks = {
            "ns": abs_nums >= 1e17,
            "us": (abs_nums >= 1e14) & (abs_nums < 1e17),
            "ms": (abs_nums >= 1e11) & (abs_nums < 1e14),
            "s": abs_nums < 1e11,
        }
        for unit, mask in unit_masks.items():
            if not mask.any():
                continue
            idx = mask.index[mask]
            parsed = pd.to_datetime(nums.loc[idx], unit=unit, utc=True, errors="coerce")
            out.loc[idx] = _to_naive_utc(parsed).to_numpy()

    if text_mask.any():
        try:
            parsed_text = pd.to_datetime(stripped[text_mask], utc=True, errors="coerce", format="mixed")
        except TypeError:
            parsed_text = pd.to_datetime(stripped[text_mask], utc=True, errors="coerce")
        out.loc[text_mask] = _to_naive_utc(parsed_text).to_numpy()

    return pd.DatetimeIndex(out)
