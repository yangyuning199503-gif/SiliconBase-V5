#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

TIME_CANDIDATES = ["time", "timestamp", "open_time", "ts", "datetime", "date"]


def parse_mixed_ts(v):
    if pd.isna(v):
        return pd.NaT
    s = str(v).strip()
    if not s:
        return pd.NaT
    try:
        if s.isdigit() or (s.startswith("-") and s[1:].isdigit()):
            x = int(s)
            ax = abs(x)
            if ax < 10**11:
                unit = "s"
            elif ax < 10**14:
                unit = "ms"
            elif ax < 10**17:
                unit = "us"
            else:
                unit = "ns"
            return pd.to_datetime(x, unit=unit, utc=True, errors="coerce")
        return pd.to_datetime(s, utc=True, errors="coerce")
    except Exception:
        return pd.NaT


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", dest="dst", required=True)
    args = ap.parse_args()

    src = Path(args.src)
    dst = Path(args.dst)
    df = pd.read_csv(src, low_memory=False)

    time_col = None
    for c in TIME_CANDIDATES:
        if c in df.columns:
            time_col = c
            break
    if time_col is None:
        raise SystemExit(f"no_time_column: checked={TIME_CANDIDATES}")

    parsed = df[time_col].map(parse_mixed_ts)
    before = len(df)
    df = df.loc[parsed.notna()].copy()
    df[time_col] = parsed.loc[parsed.notna()].dt.tz_convert("UTC").dt.strftime("%Y-%m-%d %H:%M:%S")
    df = df.sort_values(time_col).drop_duplicates(subset=[time_col], keep="last")

    dst.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(dst, index=False)

    print(f"canonicalized | file={dst} | raw_rows={before} | parsed_rows={len(df)} | time_col={time_col}")
    if len(df):
        print(f"range_utc={df[time_col].iloc[0]} -> {df[time_col].iloc[-1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
