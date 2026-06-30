from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests


def _to_ms(s: str) -> int:
    return int(pd.Timestamp(s, tz="UTC").timestamp() * 1000)


def _fetch_page(base_url: str, endpoint: str, symbol: str, start_ms: int, end_ms: int, limit: int = 1000) -> list[dict[str, Any]]:
    resp = requests.get(
        base_url.rstrip("/") + endpoint,
        params={"symbol": symbol.upper(), "startTime": start_ms, "endTime": end_ms, "limit": limit},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        raise RuntimeError(f"unexpected response: {data}")
    return data


def fetch_all(symbol: str, market: str, start: str, end: str, base_url: str | None = None) -> pd.DataFrame:
    market = market.strip().lower()
    if market in ("um", "usdsm", "usdm", "fapi"):
        endpoint = "/fapi/v1/fundingRate"
        base_url = base_url or "https://fapi.binance.com"
    elif market in ("cm", "coinm", "dapi"):
        endpoint = "/dapi/v1/fundingRate"
        base_url = base_url or "https://dapi.binance.com"
    else:
        raise ValueError("market must be one of: um/usdsm/usdm/fapi/cm/coinm/dapi")

    start_ms = _to_ms(start)
    end_ms = _to_ms(end)
    rows: list[dict[str, Any]] = []
    cursor = start_ms
    while cursor <= end_ms:
        page = _fetch_page(base_url, endpoint, symbol, cursor, end_ms)
        if not page:
            break
        rows.extend(page)
        last = int(page[-1]["fundingTime"])
        cursor = last + 1
        if len(page) < 1000:
            break
        time.sleep(0.15)

    if not rows:
        return pd.DataFrame(columns=["time", "fundingTime", "fundingRate", "symbol"])

    df = pd.DataFrame(rows)
    df["fundingTime"] = pd.to_numeric(df["fundingTime"], errors="coerce").astype("Int64")
    df["fundingRate"] = pd.to_numeric(df["fundingRate"], errors="coerce")
    df["time"] = pd.to_datetime(df["fundingTime"], unit="ms", utc=True).dt.tz_convert(None)
    keep = [c for c in ["time", "fundingTime", "fundingRate", "symbol"] if c in df.columns]
    df = df[keep].dropna(subset=["time", "fundingRate"]).sort_values("time").drop_duplicates("time", keep="last")
    return df


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch Binance futures funding history to CSV")
    ap.add_argument("--symbol", required=True, help="e.g. BTCUSDT")
    ap.add_argument("--market", default="um", help="um/usdsm/usdm/fapi or cm/coinm/dapi")
    ap.add_argument("--start", required=True, help="UTC date, e.g. 2020-01-01")
    ap.add_argument("--end", required=True, help="UTC date, e.g. 2026-01-31")
    ap.add_argument("--base-url", default=None, help="override base URL")
    ap.add_argument("--out", required=True, help="output CSV path")
    args = ap.parse_args()

    df = fetch_all(args.symbol, args.market, args.start, args.end, args.base_url)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"saved {len(df)} rows -> {out}")


if __name__ == "__main__":
    main()
