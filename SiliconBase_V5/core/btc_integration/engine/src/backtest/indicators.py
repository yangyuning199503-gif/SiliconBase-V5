from __future__ import annotations

import numpy as np


def rma(values: np.ndarray, period: int) -> np.ndarray:
    """Wilder's RMA (类似 EMA，alpha=1/period)。"""
    out = np.full_like(values, np.nan, dtype=float)
    if period <= 0 or len(values) == 0:
        return out
    # 找到第一个非 nan
    idx0 = np.where(~np.isnan(values))[0]
    if len(idx0) == 0:
        return out
    start = idx0[0]
    if start + period > len(values):
        return out
    first = np.nanmean(values[start:start + period])
    out[start + period - 1] = first
    alpha = 1.0 / period
    prev = first
    for i in range(start + period, len(values)):
        v = values[i]
        if np.isnan(v):
            out[i] = prev
            continue
        prev = (1 - alpha) * prev + alpha * v
        out[i] = prev
    return out


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> np.ndarray:
    prev_close = np.roll(close, 1)
    prev_close[0] = np.nan
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
    return rma(tr, period)


def adx(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """返回 (adx, di_plus, di_minus)。"""
    high_prev = np.roll(high, 1)
    low_prev = np.roll(low, 1)

    high_prev[0] = np.nan
    low_prev[0] = np.nan

    up_move = high - high_prev
    down_move = low_prev - low

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    prev_close = np.roll(close, 1)
    prev_close[0] = np.nan
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))

    tr_s = rma(tr, period)
    plus_s = rma(plus_dm, period)
    minus_s = rma(minus_dm, period)

    di_plus = 100.0 * (plus_s / tr_s)
    di_minus = 100.0 * (minus_s / tr_s)

    dx = 100.0 * np.abs(di_plus - di_minus) / (di_plus + di_minus)
    adx_v = rma(dx, period)
    return adx_v, di_plus, di_minus
