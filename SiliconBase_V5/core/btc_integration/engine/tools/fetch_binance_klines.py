from __future__ import annotations

import argparse
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from tqdm import tqdm
from urllib3.util.retry import Retry

SPOT_URL = "https://api.binance.com/api/v3/klines"
FUTURES_URL = "https://fapi.binance.com/fapi/v1/klines"
INTERVAL_MS = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "8h": 28_800_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
}


def _to_ms(dt_str: str) -> int:
    dt = pd.to_datetime(dt_str, utc=True)
    return int(dt.value // 10**6)


def _session() -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=0,
        connect=0,
        read=0,
        status=0,
        backoff_factor=0,
        allowed_methods=frozenset(["GET"]),
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers.update({"User-Agent": "btc_system_v1/14p4"})
    return s


def _interval_ms(interval: str) -> int:
    if interval not in INTERVAL_MS:
        raise SystemExit(f"Unsupported interval: {interval}")
    return INTERVAL_MS[interval]


def _expected_total(start_ms: int, end_ms: int, interval_ms: int) -> int:
    if end_ms <= start_ms:
        return 0
    return max(int(math.ceil((end_ms - start_ms) / interval_ms)), 0)


def fetch_klines(
    symbol: str,
    market: str,
    interval: str,
    start_ms: int,
    end_ms: int,
    max_retries: int,
    page_sleep: float,
) -> list[list]:
    url = FUTURES_URL if market == "futures" else SPOT_URL
    limit = 1500 if market == "futures" else 1000
    step_ms = _interval_ms(interval)

    sess = _session()
    out: list[list] = []
    cur = start_ms
    expected = _expected_total(start_ms, end_ms, step_ms)
    pbar = tqdm(total=expected, unit="bars")
    last_count = 0

    while cur < end_ms:
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": cur,
            "endTime": end_ms,
            "limit": limit,
        }

        rows = None
        last_err: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                r = sess.get(url, params=params, timeout=30)
                r.raise_for_status()
                rows = r.json()
                last_err = None
                break
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                if attempt >= max_retries:
                    break
                wait_s = min(2 ** attempt, 15)
                print(
                    f"[WARN] {symbol} {market} page fetch failed; retry {attempt + 1}/{max_retries} in {wait_s}s | err={type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
                time.sleep(wait_s)

        if rows is None:
            pbar.close()
            raise RuntimeError(f"fetch failed for {symbol} {market} at startTime={cur}: {last_err}")

        if not rows:
            break

        out.extend(rows)
        delta = len(out) - last_count
        if delta > 0:
            pbar.update(delta)
            last_count = len(out)

        last_open = int(rows[-1][0])
        next_cur = last_open + step_ms
        if next_cur <= cur:
            next_cur = cur + step_ms
        cur = next_cur

        if page_sleep > 0:
            time.sleep(page_sleep)

    pbar.close()
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True, help="如 BTCUSDT")
    ap.add_argument("--market", choices=["futures", "spot"], default="futures")
    ap.add_argument("--interval", default="15m")
    ap.add_argument("--start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD")
    ap.add_argument("--out", required=True, help="输出 CSV 路径，如 data/raw/btc_15m.csv")
    ap.add_argument("--max-retries", type=int, default=8)
    ap.add_argument("--page-sleep", type=float, default=0.15)
    args = ap.parse_args()

    start_ms = _to_ms(args.start)
    end_ms = _to_ms(args.end)

    rows = fetch_klines(
        args.symbol,
        args.market,
        args.interval,
        start_ms,
        end_ms,
        max_retries=max(args.max_retries, 0),
        page_sleep=max(args.page_sleep, 0.0),
    )

    records = []
    for r in rows:
        ot = int(r[0])
        t = datetime.fromtimestamp(ot / 1000, tz=timezone.utc).replace(tzinfo=None)
        records.append(
            {
                "time": t.strftime("%Y-%m-%d %H:%M:%S"),
                "open": float(r[1]),
                "high": float(r[2]),
                "low": float(r[3]),
                "close": float(r[4]),
                "volume": float(r[5]),
            }
        )

    df = pd.DataFrame(records).drop_duplicates("time").sort_values("time")
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False, encoding="utf-8")
    print(f"OK -> {out_path} rows={len(df)}")


if __name__ == "__main__":
    main()
