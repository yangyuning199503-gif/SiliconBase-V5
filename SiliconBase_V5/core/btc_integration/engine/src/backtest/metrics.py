from __future__ import annotations

import numpy as np
import pandas as pd


def calc_drawdown(equity: pd.Series) -> pd.Series:
    peak = equity.cummax()
    dd = equity / peak - 1.0
    return dd


def max_drawdown(equity: pd.Series) -> tuple[float, pd.Timestamp | None, pd.Timestamp | None]:
    dd = calc_drawdown(equity)
    mdd = float(dd.min())
    if np.isnan(mdd):
        return np.nan, None, None
    end = dd.idxmin()
    peak = equity.loc[:end].idxmax()
    return mdd, peak, end


def cagr(initial: float, final: float, start: pd.Timestamp, end: pd.Timestamp) -> float:
    days = (end - start).days + (end - start).seconds / 86400.0
    years = days / 365.25
    if years <= 0:
        return np.nan
    return (final / initial) ** (1 / years) - 1.0


def profit_factor(trades: pd.DataFrame) -> float:
    if trades.empty:
        return np.nan
    wins = trades.loc[trades["pnl"] > 0, "pnl"].sum()
    losses = trades.loc[trades["pnl"] < 0, "pnl"].sum()
    if losses == 0:
        return np.inf
    return float(wins / abs(losses))


def win_rate(trades: pd.DataFrame) -> float:
    if trades.empty:
        return np.nan
    return float((trades["pnl"] > 0).mean())


def sharpe_daily(equity: pd.Series) -> float:
    # 日频估算：用日末权益做日收益
    daily = equity.resample("1D").last().dropna()
    rets = daily.pct_change().dropna()
    if len(rets) < 2:
        return np.nan
    mu = rets.mean()
    sd = rets.std(ddof=1)
    if sd == 0:
        return np.nan
    return float(mu / sd * np.sqrt(365))


def monthly_returns(equity: pd.Series) -> pd.Series:
    if equity.empty:
        return pd.Series(dtype=float)
    for freq in ("ME", "M"):
        try:
            m = equity.resample(freq).last().dropna()
            r = m.pct_change().dropna()
            r.index = r.index.to_period("M").to_timestamp()
            return r
        except Exception:
            continue
    return pd.Series(dtype=float)


def format_pct(x: float, digits: int = 2) -> str:
    if x is None or np.isnan(x):
        return "NA"
    return f"{x*100:.{digits}f}%"


def summarize_metrics(initial: float, equity: pd.Series, trades: pd.DataFrame) -> dict:
    start = equity.index[0]
    end = equity.index[-1]
    final = float(equity.iloc[-1])
    total_ret = final / initial - 1.0
    cagr_v = cagr(initial, final, start, end)
    mdd, dd_start, dd_end = max_drawdown(equity)
    pf = profit_factor(trades)
    wr = win_rate(trades)
    sh = sharpe_daily(equity)
    return {
        "period_start": str(start),
        "period_end": str(end),
        "initial_equity": initial,
        "final_equity": final,
        "total_return": total_ret,
        "cagr": cagr_v,
        "max_drawdown": mdd,
        "max_drawdown_start": str(dd_start) if dd_start is not None else None,
        "max_drawdown_end": str(dd_end) if dd_end is not None else None,
        "profit_factor": pf,
        "trades": int(len(trades)),
        "win_rate": wr,
        "sharpe_daily": sh,
    }
