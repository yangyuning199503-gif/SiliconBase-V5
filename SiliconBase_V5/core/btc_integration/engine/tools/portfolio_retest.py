from __future__ import annotations

import argparse
import copy
from pathlib import Path
from typing import Any

import pandas as pd
from src.backtest.engine import run_backtest_portfolio
from src.backtest.io import load_ohlcv_csv, read_config
from src.backtest.metrics import summarize_metrics
from tabulate import tabulate

SEGMENTS: list[tuple[str, str, str]] = [
    ("ret_2020_2021", "2020-02-10 08:00:00", "2021-12-31 23:59:59"),
    ("ret_2022_2023", "2022-01-01 00:00:00", "2023-12-31 23:59:59"),
    ("ret_2024_2026", "2024-01-01 00:00:00", "2026-01-31 00:00:00"),
]


def _equity_at(eq: pd.Series, t: pd.Timestamp) -> float | None:
    # last value at or before t
    s = eq.loc[eq.index <= t]
    if s.empty:
        return None
    return float(s.iloc[-1])


def _segment_return(eq: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> float | None:
    s = _equity_at(eq, start)
    e = _equity_at(eq, end)
    if s is None or e is None or s == 0:
        return None
    return e / s - 1.0


def _last_trade_time(trades: pd.DataFrame) -> str | None:
    if trades is None or trades.empty:
        return None
    for col in ("exit_time", "exit_ts", "exit_datetime"):
        if col in trades.columns:
            try:
                return str(pd.to_datetime(trades[col]).max())
            except Exception:
                return None
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-config", default="config.yml")
    ap.add_argument("--out", default="reports/portfolio_retest_latest.txt")
    ap.add_argument("--csv-out", default="reports/portfolio_retest_latest.csv")
    args = ap.parse_args()

    base_cfg: dict[str, Any] = read_config(args.base_config)
    data_cfg = base_cfg.get("data", {})
    tmpl = data_cfg.get("csv_template", "data/raw/{symbol}_15m.csv")
    start = pd.to_datetime(data_cfg.get("start"), utc=True).tz_convert(None) if data_cfg.get("start") else None
    end = pd.to_datetime(data_cfg.get("end"), utc=True).tz_convert(None) if data_cfg.get("end") else None

    portfolios: list[tuple[str, list[str], dict[str, float]]] = [
        ("btc_only", ["btc"], {"btc": 1.0}),
        ("sol_only", ["sol"], {"sol": 1.0}),
        ("trx_only", ["trx"], {"trx": 1.0}),
        ("btc_bnb", ["btc", "bnb"], {"btc": 0.5, "bnb": 0.5}),
        ("btc_bnb_sol", ["btc", "bnb", "sol"], {"btc": 1 / 3, "bnb": 1 / 3, "sol": 1 / 3}),
        ("btc_bnb_trx", ["btc", "bnb", "trx"], {"btc": 1 / 3, "bnb": 1 / 3, "trx": 1 / 3}),
    ]

    # Load all required data once
    symbols_all = sorted({sym for _, syms, _ in portfolios for sym in syms})
    missing: list[str] = []
    data_all: dict[str, pd.DataFrame] = {}

    for sym in symbols_all:
        path = Path(str(tmpl).format(symbol=sym))
        if not path.exists():
            missing.append(str(path))
            continue
        df = load_ohlcv_csv(path)
        if start is not None:
            df = df.loc[df.index >= start]
        if end is not None:
            df = df.loc[df.index <= end]
        data_all[sym] = df

    if missing:
        msg = "\n".join(missing)
        raise SystemExit(
            "缺少数据文件：\n"
            + msg
            + "\n\n请用下载脚本补齐（示例）：\n"
            + "./.venv/bin/python -m tools.fetch_binance_klines --symbol SOLUSDT --market futures --interval 15m "
            + "--start 2020-01-01 --end 2026-01-31 --out data/raw/sol_15m.csv\n"
            + "./.venv/bin/python -m tools.fetch_binance_klines --symbol TRXUSDT --market futures --interval 15m "
            + "--start 2020-01-01 --end 2026-01-31 --out data/raw/trx_15m.csv\n"
        )

    rows: list[dict[str, Any]] = []
    for name, syms, w in portfolios:
        cfg = copy.deepcopy(base_cfg)
        cfg.setdefault("system", {})["version"] = f"{base_cfg.get('system', {}).get('version','NA')}_{name}"
        cfg.setdefault("data", {})["symbols"] = list(syms)
        cfg["data"]["weights"] = dict(w)

        data = {s: data_all[s] for s in syms}
        eq_df, trades_df, snapshot = run_backtest_portfolio(data=data, cfg=cfg)
        eq = eq_df["equity"]

        metrics = summarize_metrics(initial=cfg["portfolio"]["initial_equity"], equity=eq, trades=trades_df)

        row: dict[str, Any] = {
            "variant": name,
            "symbols": ",".join(syms),
            "total_return": metrics["total_return"],
            "cagr": metrics["cagr"],
            "max_drawdown": metrics["max_drawdown"],
            "profit_factor": metrics["profit_factor"],
            "trades": metrics["trades"],
            "dd_guard_triggers": (snapshot.get("dd_guard", {}) or {}).get("triggers") if isinstance(snapshot, dict) else None,
            "last_trade": _last_trade_time(trades_df),
        }

        for seg_name, seg_start, seg_end in SEGMENTS:
            ss = pd.to_datetime(seg_start)
            ee = pd.to_datetime(seg_end)
            s0 = ss if start is None else max(ss, start)
            e0 = ee if end is None else min(ee, end)
            r = _segment_return(eq, s0, e0)
            row[seg_name] = r

        rows.append(row)

    df = pd.DataFrame(rows)

    # pretty format for txt
    def fmt_pct(x: Any) -> str:
        if x is None or (isinstance(x, float) and pd.isna(x)):
            return "NA"
        return f"{float(x)*100:.2f}%"

    df_fmt = df.copy()
    for c in ("total_return", "cagr", "max_drawdown", "ret_2020_2021", "ret_2022_2023", "ret_2024_2026"):
        if c in df_fmt.columns:
            df_fmt[c] = df_fmt[c].apply(fmt_pct)

    txt = tabulate(df_fmt, headers="keys", tablefmt="github", showindex=False)

    out_txt = Path(args.out)
    out_txt.parent.mkdir(parents=True, exist_ok=True)
    out_txt.write_text(txt + "\n", encoding="utf-8")

    out_csv = Path(args.csv_out)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)

    print("OK ->", str(out_txt), "| rows=", len(df))


if __name__ == "__main__":
    main()
