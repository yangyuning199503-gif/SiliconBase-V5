from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from src.backtest.engine import run_backtest_portfolio
from src.backtest.io import load_ohlcv_csv, read_config, save_csv, save_json
from src.backtest.metrics import summarize_metrics


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yml")
    ap.add_argument("--segment-years", type=int, default=2)
    ap.add_argument("--out", default=None, help="输出目录（默认 reports/segments_<ts>）")
    args = ap.parse_args()

    cfg = read_config(args.config)
    reports_dir = Path(cfg.get("outputs", {}).get("reports_dir", "reports"))
    reports_dir.mkdir(parents=True, exist_ok=True)

    data_cfg = cfg.get("data", {})
    symbols = data_cfg.get("symbols", [])
    tmpl = data_cfg.get("csv_template", "data/raw/{symbol}_15m.csv")

    # 加载全量（不裁剪）
    data_full = {}
    for sym in symbols:
        path = Path(str(tmpl).format(symbol=sym))
        data_full[sym] = load_ohlcv_csv(path)

    # 共同区间
    common = None
    for s in symbols:
        idx = data_full[s].index
        common = idx if common is None else common.intersection(idx)
    common = common.sort_values()
    start = common[0]
    end = common[-1]

    seg_years = args.segment_years
    segs = []
    cur_start = start
    while cur_start < end:
        cur_end = cur_start + pd.DateOffset(years=seg_years)
        cur_end = min(cur_end, end)
        if cur_end <= cur_start:
            break
        segs.append((cur_start, cur_end))
        cur_start = cur_end + pd.Timedelta(minutes=15)

    ts = pd.Timestamp.utcnow().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out) if args.out else reports_dir / f"segments_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for i, (a, b) in enumerate(segs, 1):
        data = {s: df.loc[(df.index >= a) & (df.index <= b)] for s, df in data_full.items()}
        eq_df, trades_df, snapshot = run_backtest_portfolio(data=data, cfg=cfg)
        m = summarize_metrics(initial=cfg["portfolio"]["initial_equity"], equity=eq_df["equity"], trades=trades_df)
        m["segment"] = f"S{i}_{a.date()}_{b.date()}"
        rows.append(m)

    seg_df = pd.DataFrame(rows).set_index("segment")
    save_csv(seg_df, out_dir / "segment_metrics.csv")
    save_json({"segments": rows}, out_dir / "segment_metrics.json")
    print(f"OK -> {out_dir}")

if __name__ == "__main__":
    main()
