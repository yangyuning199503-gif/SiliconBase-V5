from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd
from src.backtest.engine import run_backtest_portfolio
from src.backtest.io import load_ohlcv_csv, read_config, save_csv, save_json
from src.backtest.metrics import calc_drawdown, monthly_returns, summarize_metrics
from src.utils.logger import setup_logger
from tabulate import tabulate


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _write_monthly_stats(mrets: pd.Series, out_txt: Path) -> None:
    if mrets.empty:
        out_txt.write_text("无月度收益数据\n", encoding="utf-8")
        return
    df = mrets.to_frame("月收益")
    df["月收益"] = df["月收益"].apply(lambda v: f"{v*100:.2f}%")
    txt = tabulate(
        df.reset_index().rename(columns={"index": "月份"}),
        headers="keys",
        tablefmt="github",
        showindex=False,
    )
    out_txt.write_text(txt + "\n", encoding="utf-8")



def _engine_breakdown(trades_df: pd.DataFrame) -> dict[str, Any]:
    """按 trades.reason 前缀拆分引擎贡献：TREND / SR / MR。"""
    if trades_df is None or len(trades_df) == 0 or "reason" not in trades_df.columns:
        return {}
    df = trades_df.copy()
    df["engine"] = df["reason"].astype(str).str.split("_").str[0]

    out: dict[str, Any] = {}
    for eng in ("TREND", "SR", "MR"):
        g = df[df["engine"] == eng]
        if len(g) == 0:
            continue
        pnl = float(g["pnl"].sum())
        gp = float(g.loc[g["pnl"] > 0, "pnl"].sum())
        gl = float(-g.loc[g["pnl"] < 0, "pnl"].sum())
        pf = gp / gl if gl > 0 else 999.0
        out[f"{eng.lower()}_trades"] = int(len(g))
        out[f"{eng.lower()}_pnl"] = pnl
        out[f"{eng.lower()}_pf"] = float(pf)
    return out


def _segment_line(trades_df: pd.DataFrame) -> str | None:
    if trades_df is None or trades_df.empty or ("exit_time" not in trades_df.columns):
        return None
    df = trades_df.copy()
    df["exit_time"] = pd.to_datetime(df["exit_time"], errors="coerce")
    df = df.dropna(subset=["exit_time"])
    if df.empty:
        return None

    y = df["exit_time"].dt.year
    seg = y.apply(lambda yy: "2020-2021" if yy <= 2021 else ("2022-2023" if yy <= 2023 else "2024-2026"))
    df["_seg"] = seg

    rows = []
    for s, g in df.groupby("_seg"):
        pnl = float(g["pnl"].sum())
        gp = float(g.loc[g["pnl"] > 0, "pnl"].sum())
        gl = float(-g.loc[g["pnl"] < 0, "pnl"].sum())
        pf = gp / gl if gl > 0 else 999.0
        rows.append((s, pnl, pf, int(len(g))))

    order = {"2020-2021": 0, "2022-2023": 1, "2024-2026": 2}
    rows.sort(key=lambda x: order.get(x[0], 99))
    parts = [f"{s} {p:+.0f} PF {pf:.2f} T {t}" for s, p, pf, t in rows]
    return "【分段】" + " | ".join(parts)


def _top_drag_line(trades_df: pd.DataFrame) -> str | None:
    if trades_df is None or trades_df.empty:
        return None
    df = trades_df.copy()
    if "reason" in df.columns:
        df["engine"] = df["reason"].astype(str).str.extract(r"^(TREND|SR)", expand=False).fillna("OTHER")
    else:
        df["engine"] = "OTHER"

    keys = [k for k in ["engine", "symbol", "side"] if k in df.columns]
    if "pnl" not in df.columns or len(keys) < 1:
        return None

    g = df.groupby(keys)["pnl"].sum().sort_values()
    losers = g[g < 0].head(2)
    if losers.empty:
        return None

    parts = []
    for idx, pnl in losers.items():
        if not isinstance(idx, tuple):
            idx = (idx,)
        label = " ".join([str(x) for x in idx])
        parts.append(f"{label} {float(pnl):+.0f}")
    return "【最大拖累】" + " | ".join(parts)


def _write_deepseek_brief(
    cfg: dict[str, Any],
    metrics: dict[str, Any],
    out_txt: Path,
    extra: dict[str, Any] | None = None,
) -> None:
    extra = extra or {}
    sys = cfg.get("system", {})
    symbols = cfg.get("data", {}).get("symbols", [])
    version = sys.get("version", "NA")
    sname = sys.get("strategy", "NA")

    lines = [
        f"【版本】{version} / {sname}",
        f"【资产池】{','.join(symbols)}",
        f"【区间】{metrics.get('period_start')} -> {metrics.get('period_end')}",
        f"【总收益】{metrics.get('total_return')*100:.2f}%",
        f"【年化】{metrics.get('cagr')*100:.2f}%",
        f"【最大回撤】{metrics.get('max_drawdown')*100:.2f}%",
        f"【PF】{metrics.get('profit_factor'):.2f}",
        f"【交易数】{metrics.get('trades')} / 胜率 {metrics.get('win_rate')*100:.2f}%",
        f"【Sharpe(日频估算)】{metrics.get('sharpe_daily'):.2f}",
        f"【最大回撤区间】{metrics.get('max_drawdown_start')} -> {metrics.get('max_drawdown_end')}",
        "【结论】优先看：分段(2020-21/2022-23/2024-26) + 引擎拆分(TREND/SR) + 最大拖累(bucket)；先把 PF 提到 >1.15，再谈风险放大冲月化。",
        "【下一步动作】先跑主线消息面联动与分支快扫，再执行 bash run_send_files.sh 生成对外三文件。",
    ]

    last_trade = extra.get("last_trade_time")
    if last_trade:
        lines.append(f"【最后交易】{last_trade}")
    nzm = extra.get("nonzero_months")
    if nzm is not None:
        lines.append(f"【非零月份】{nzm}")
    md = extra.get("monthly_dist_line")
    if md:
        lines.append(md)
    r24_cmgr = extra.get("recent24_cmgr")
    r24_ann = extra.get("recent24_ann")
    r24_mean = extra.get("recent24_mean")
    if r24_cmgr is not None and r24_ann is not None:
        lines.append(f"【近24月复利月化】{r24_cmgr*100:.2f}% / 月 | 复利年化 {r24_ann*100:.2f}%")
    if r24_mean is not None:
        lines.append(f"【近24月月均(算术)】{r24_mean*100:.2f}%")
    funding_line = extra.get("funding_line")
    if funding_line:
        lines.append(str(funding_line))
    ddg = extra.get("dd_guard_triggers")
    if ddg is not None:
        lines.append(f"【DD_GUARD触发】{ddg} 次")

    t_trades = extra.get("trend_trades")
    s_trades = extra.get("sr_trades")
    if t_trades is not None or s_trades is not None:
        tp = extra.get("trend_pnl", 0.0)
        tpf = extra.get("trend_pf", 0.0)
        sp = extra.get("sr_pnl", 0.0)
        spf = extra.get("sr_pf", 0.0)
        lines.append(f"【引擎拆分】TREND PnL {tp:+.0f} PF {tpf:.2f} Trades {t_trades or 0} | SR PnL {sp:+.0f} PF {spf:.2f} Trades {s_trades or 0}")
    seg_line = extra.get("segment_line")
    if seg_line:
        lines.append(str(seg_line))
    drag_line = extra.get("top_drag_line")
    if drag_line:
        lines.append(str(drag_line))


    out_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yml")
    ap.add_argument("--run-id", default=None)
    args = ap.parse_args()

    cfg = read_config(args.config)
    reports_dir = Path(cfg.get("outputs", {}).get("reports_dir", "reports"))
    _ensure_dir(reports_dir)
    _ensure_dir(Path("logs"))

    run_id = args.run_id or pd.Timestamp.utcnow().strftime("%Y%m%d_%H%M%S")
    run_dir = reports_dir / f"run_{run_id}"
    _ensure_dir(run_dir)

    logger = setup_logger(Path("logs") / f"run_{run_id}.log")
    logger.info("加载配置完成：%s", args.config)

    data_cfg = cfg.get("data", {})
    symbols = data_cfg.get("symbols", [])
    tmpl = data_cfg.get("csv_template", "data/raw/{symbol}_15m.csv")
    start = pd.to_datetime(data_cfg.get("start"), utc=True).tz_convert(None) if data_cfg.get("start") else None
    end = pd.to_datetime(data_cfg.get("end"), utc=True).tz_convert(None) if data_cfg.get("end") else None

    data: dict[str, pd.DataFrame] = {}
    missing: list[str] = []
    for sym in symbols:
        path = Path(str(tmpl).format(symbol=sym))
        if not path.exists():
            missing.append(str(path))
            continue
        df = load_ohlcv_csv(path)
        if start is not None:
            df = df.loc[df.index >= start]
        if end is not None:
            df = df.loc[df.index <= end]
        data[sym] = df

    if missing:
        msg = "\n".join(missing)
        raise SystemExit(
            "缺少数据文件：\n" + msg + "\n\n"
            "你可以用下载脚本补齐（示例）：\n"
            "./.venv/bin/python -m tools.fetch_binance_klines --symbol BTCUSDT --market futures --interval 15m --start 2020-01-01 --end 2026-01-31 --out data/raw/btc_15m.csv\n"
            "./.venv/bin/python -m tools.fetch_binance_klines --symbol BNBUSDT --market futures --interval 15m --start 2020-01-01 --end 2026-01-31 --out data/raw/bnb_15m.csv\n"
        )

    logger.info("数据加载完成：%s", ",".join([f"{k}({len(v)})" for k, v in data.items()]))

    eq_df, trades_df, snapshot = run_backtest_portfolio(data=data, cfg=cfg)

    metrics = summarize_metrics(initial=cfg["portfolio"]["initial_equity"], equity=eq_df["equity"], trades=trades_df)
    dd = calc_drawdown(eq_df["equity"])
    eq_out = eq_df.copy()
    eq_out["drawdown"] = dd

    # 保存 run 目录
    save_json({"metrics": metrics, "snapshot": snapshot}, run_dir / "metrics.json")
    save_csv(eq_out, run_dir / "equity_curve.csv")
    save_csv(trades_df, run_dir / "trades.csv")

    # latest 输出
    save_json({"metrics": metrics, "snapshot": snapshot}, reports_dir / "metrics_latest.json")
    mrets = monthly_returns(eq_df["equity"])
    save_csv(mrets.to_frame("return"), reports_dir / "monthly_returns_latest.csv")
    _write_monthly_stats(mrets, reports_dir / "monthly_stats_latest.txt")

    # deepseek brief
    last_trade_time = None
    if not trades_df.empty and "exit_time" in trades_df.columns:
        try:
            last_trade_time = str(pd.to_datetime(trades_df["exit_time"]).max())
        except Exception:
            last_trade_time = None

    nonzero_months = int((mrets != 0).sum()) if not mrets.empty else 0
    dd_guard_triggers = snapshot.get("dd_guard", {}).get("triggers") if isinstance(snapshot, dict) else None
    extra = {
        "last_trade_time": last_trade_time,
        "nonzero_months": nonzero_months,
        "dd_guard_triggers": dd_guard_triggers,
    }
    if not mrets.empty:
        m_mean = float(mrets.mean())
        m_p90 = float(mrets.quantile(0.90))
        m_p95 = float(mrets.quantile(0.95))
        m_max = float(mrets.max())
        m_ge20 = int((mrets >= 0.20).sum())
        m_ge30 = int((mrets >= 0.30).sum())
        extra["monthly_dist_line"] = (
            f"【月分布】均值 {m_mean*100:.2f}% | P90 {m_p90*100:.2f}% | P95 {m_p95*100:.2f}% | "
            f"Max {m_max*100:.2f}% | >=20% {m_ge20} | >=30% {m_ge30}"
        )
    extra.update(_engine_breakdown(trades_df))
    funding_snapshot = snapshot.get("funding", {}) if isinstance(snapshot, dict) else {}
    if isinstance(funding_snapshot, dict) and funding_snapshot.get("enabled"):
        total = float(funding_snapshot.get("net_cost_total", 0.0))
        by_symbol = funding_snapshot.get("net_cost_by_symbol", {}) or {}
        parts = [f"{str(k).upper()} {float(v):+.0f}" for k, v in by_symbol.items()]
        extra["funding_line"] = f"【Funding净成本】{total:+.0f} | 按资产：" + " | ".join(parts)
    seg_line = _segment_line(trades_df)
    if seg_line:
        extra["segment_line"] = seg_line
    drag_line = _top_drag_line(trades_df)
    if drag_line:
        extra["top_drag_line"] = drag_line
    _write_deepseek_brief(cfg, metrics, reports_dir / "deepseek_brief_latest.txt", extra=extra)

    # 中文摘要输出到终端
    print("\n====== 回测结果（中文关键指标）======")
    print(f"版本：{cfg.get('system', {}).get('version')} | 资产池：{','.join(symbols)}")
    print(f"区间：{metrics['period_start']} -> {metrics['period_end']}")
    print(f"总收益：{metrics['total_return']*100:.2f}%")
    print(f"年化：{metrics['cagr']*100:.2f}%")
    print(f"最大回撤：{metrics['max_drawdown']*100:.2f}%")
    print(f"PF：{metrics['profit_factor']:.2f}")
    print(f"交易数：{metrics['trades']} | 胜率：{metrics['win_rate']*100:.2f}%")
    print(f"Sharpe（日频估算）：{metrics['sharpe_daily']:.2f}")
    print(f"最大回撤区间：{metrics['max_drawdown_start']} -> {metrics['max_drawdown_end']}")
    print("====================================\n")

    logger.info("回测完成：run_dir=%s", run_dir)


if __name__ == "__main__":
    main()
