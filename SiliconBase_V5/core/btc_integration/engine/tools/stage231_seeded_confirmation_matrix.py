from __future__ import annotations

import argparse
import json
from math import ceil
from pathlib import Path

import numpy as np
import pandas as pd

SYMBOLS_DEFAULT = ["btc", "bnb", "eth", "sol"]
PARAMS = [
    {
        "param_id": "p1",
        "adx_floor": 16,
        "f_adx_floor": 18,
        "bbw_floor": 0.010,
        "bo_atr": 0.25,
        "stop_atr": 1.15,
        "trail_atr": 1.50,
        "arm_rr": 0.70,
        "max_hold": 32,
        "wick_atr": 2.4,
        "wick_ratio": 0.65,
        "sweep_atr": 0.20,
    },
    {
        "param_id": "p2",
        "adx_floor": 18,
        "f_adx_floor": 20,
        "bbw_floor": 0.012,
        "bo_atr": 0.30,
        "stop_atr": 1.35,
        "trail_atr": 1.75,
        "arm_rr": 0.85,
        "max_hold": 40,
        "wick_atr": 2.6,
        "wick_ratio": 0.68,
        "sweep_atr": 0.25,
    },
    {
        "param_id": "p3",
        "adx_floor": 20,
        "f_adx_floor": 22,
        "bbw_floor": 0.015,
        "bo_atr": 0.40,
        "stop_atr": 1.55,
        "trail_atr": 2.10,
        "arm_rr": 1.00,
        "max_hold": 56,
        "wick_atr": 3.0,
        "wick_ratio": 0.72,
        "sweep_atr": 0.35,
    },
    {
        "param_id": "p4",
        "adx_floor": 22,
        "f_adx_floor": 24,
        "bbw_floor": 0.018,
        "bo_atr": 0.50,
        "stop_atr": 1.80,
        "trail_atr": 2.40,
        "arm_rr": 1.20,
        "max_hold": 72,
        "wick_atr": 3.2,
        "wick_ratio": 0.75,
        "sweep_atr": 0.45,
    },
]
PARAM_MAP = {p["param_id"]: p for p in PARAMS}

# 当前 stage230 之后锁定的研究主线；高胜率窄线只当 confirmation reference。
SEED_LANES = [
    {
        "seed_id": "btc_fast_short_engine",
        "role": "engine",
        "symbol": "btc",
        "entry_tf": "5m",
        "filter_tf": "15m",
        "family": "bb_meanrev",
        "param_id": "p4",
        "mode": "short_only",
    },
    {
        "seed_id": "bnb_fast_dual_engine",
        "role": "engine",
        "symbol": "bnb",
        "entry_tf": "5m",
        "filter_tf": "15m",
        "family": "bb_meanrev",
        "param_id": "p2",
        "mode": "dual",
    },
    {
        "seed_id": "eth_slow_dual_engine",
        "role": "engine",
        "symbol": "eth",
        "entry_tf": "1h",
        "filter_tf": "4h",
        "family": "bb_meanrev",
        "param_id": "p3",
        "mode": "dual",
    },
    {
        "seed_id": "sol_fast_dual_engine",
        "role": "engine",
        "symbol": "sol",
        "entry_tf": "5m",
        "filter_tf": "15m",
        "family": "bb_meanrev",
        "param_id": "p4",
        "mode": "dual",
    },
    {
        "seed_id": "eth_highwin_dual_reference",
        "role": "confirm_reference",
        "symbol": "eth",
        "entry_tf": "30m",
        "filter_tf": "1h",
        "family": "bb_meanrev",
        "param_id": "p1",
        "mode": "dual",
    },
    {
        "seed_id": "sol_highwin_long_reference",
        "role": "confirm_reference",
        "symbol": "sol",
        "entry_tf": "1h",
        "filter_tf": "4h",
        "family": "bb_meanrev",
        "param_id": "p1",
        "mode": "long_only",
    },
]

HELPER_FAMILIES = [
    "sweep_reclaim",
    "retest_fail",
    "squeeze_pullback",
    "range_revert_grid",
    "ma_macd_bb",
]

VARIANTS = [
    {"variant": "base", "helpers": [], "min_votes": 0, "window": 1},
    {"variant": "gate_sweep_2b", "helpers": ["sweep_reclaim"], "min_votes": 1, "window": 2},
    {"variant": "gate_retest_2b", "helpers": ["retest_fail"], "min_votes": 1, "window": 2},
    {"variant": "gate_squeeze_2b", "helpers": ["squeeze_pullback"], "min_votes": 1, "window": 2},
    {"variant": "gate_range_2b", "helpers": ["range_revert_grid"], "min_votes": 1, "window": 2},
    {"variant": "gate_trend_2b", "helpers": ["ma_macd_bb"], "min_votes": 1, "window": 2},
    {
        "variant": "gate_vote1_micro_2b",
        "helpers": ["sweep_reclaim", "retest_fail", "range_revert_grid"],
        "min_votes": 1,
        "window": 2,
    },
    {
        "variant": "gate_vote2_micro_2b",
        "helpers": ["sweep_reclaim", "retest_fail", "range_revert_grid"],
        "min_votes": 2,
        "window": 2,
    },
    {
        "variant": "gate_vote2_full_2b",
        "helpers": ["sweep_reclaim", "retest_fail", "squeeze_pullback", "range_revert_grid", "ma_macd_bb"],
        "min_votes": 2,
        "window": 2,
    },
]


class SeededConfirmationMatrix:
    def __init__(self, root: Path, recent_years: int = 2, wf_months: int = 12):
        self.root = root
        self.raw_dir = root / "data" / "raw"
        self.out_dir = root / "reports" / "research_raw"
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.recent_years = recent_years
        self.wf_months = wf_months
        self.raw_cache: dict[tuple[str, str], pd.DataFrame] = {}
        self.base_cache: dict[tuple[str, str], pd.DataFrame] = {}
        self.merge_cache: dict[tuple[str, str, str], pd.DataFrame] = {}

    def load_symbol(self, symbol: str, base_tf: str) -> pd.DataFrame:
        key = (symbol, base_tf)
        if key in self.raw_cache:
            return self.raw_cache[key]
        path = self.raw_dir / f"{symbol}_{base_tf}.csv"
        if not path.exists():
            raise FileNotFoundError(path)
        df = pd.read_csv(path, parse_dates=["time"]).sort_values("time").set_index("time")
        self.raw_cache[key] = df
        return df

    @staticmethod
    def resample_ohlcv(df: pd.DataFrame, tf: str) -> pd.DataFrame:
        rule = {"5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h", "4h": "4h"}[tf]
        out = pd.DataFrame(index=df.resample(rule).last().index)
        out["open"] = df["open"].resample(rule).first()
        out["high"] = df["high"].resample(rule).max()
        out["low"] = df["low"].resample(rule).min()
        out["close"] = df["close"].resample(rule).last()
        out["volume"] = df["volume"].resample(rule).sum()
        return out.dropna()

    @staticmethod
    def ema(s: pd.Series, span: int) -> pd.Series:
        return s.ewm(span=span, adjust=False).mean()

    @staticmethod
    def rsi(close: pd.Series, n: int = 14) -> pd.Series:
        d = close.diff()
        up = d.clip(lower=0)
        down = -d.clip(upper=0)
        rs = up.ewm(alpha=1 / n, adjust=False).mean() / down.ewm(alpha=1 / n, adjust=False).mean()
        return 100 - 100 / (1 + rs)

    @staticmethod
    def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
        prev = df["close"].shift(1)
        tr = pd.concat(
            [
                (df["high"] - df["low"]).abs(),
                (df["high"] - prev).abs(),
                (df["low"] - prev).abs(),
            ],
            axis=1,
        ).max(axis=1)
        return tr.ewm(alpha=1 / n, adjust=False).mean()

    @staticmethod
    def adx(df: pd.DataFrame, n: int = 14) -> tuple[pd.Series, pd.Series, pd.Series]:
        high, low, close = df["high"], df["low"], df["close"]
        up = high.diff()
        down = -low.diff()
        plus_dm = np.where((up > down) & (up > 0), up, 0.0)
        minus_dm = np.where((down > up) & (down > 0), down, 0.0)
        tr = pd.concat(
            [
                (high - low).abs(),
                (high - close.shift()).abs(),
                (low - close.shift()).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atrv = tr.ewm(alpha=1 / n, adjust=False).mean()
        plus_di = 100 * (pd.Series(plus_dm, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / atrv)
        minus_di = 100 * (pd.Series(minus_dm, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / atrv)
        dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di))
        adxv = dx.ewm(alpha=1 / n, adjust=False).mean()
        return adxv, plus_di, minus_di

    @staticmethod
    def bollinger(close: pd.Series, n: int = 20, k: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
        ma = close.rolling(n).mean()
        sd = close.rolling(n).std()
        width = (2 * k * sd / ma).replace([np.inf, -np.inf], np.nan)
        return ma, ma + k * sd, ma - k * sd, width

    def macd(self, close: pd.Series, fast: int = 12, slow: int = 26, sig: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
        line = self.ema(close, fast) - self.ema(close, slow)
        signal = self.ema(line, sig)
        return line, signal, line - signal

    def add_features(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        out["ema_fast"] = self.ema(out["close"], 12)
        out["ema_slow"] = self.ema(out["close"], 36)
        out["ema_200"] = self.ema(out["close"], 200)
        out["rsi"] = self.rsi(out["close"], 14)
        out["atr"] = self.atr(out, 14)
        adxv, plus_di, minus_di = self.adx(out, 14)
        out["adx"] = adxv
        out["plus_di"] = plus_di
        out["minus_di"] = minus_di
        out["macd"], out["macd_signal"], out["macd_hist"] = self.macd(out["close"])
        out["bb_mid"], out["bb_up"], out["bb_dn"], out["bb_width"] = self.bollinger(out["close"], 20, 2)
        pv = (out["close"] * out["volume"]).rolling(20).sum()
        vv = out["volume"].rolling(20).sum()
        out["vwap20"] = pv / vv
        out["hh20"] = out["high"].rolling(20).max()
        out["ll20"] = out["low"].rolling(20).min()
        out["hh10"] = out["high"].rolling(10).max()
        out["ll10"] = out["low"].rolling(10).min()
        out["bb_width_ma"] = out["bb_width"].rolling(40).mean()

        rng = (out["high"] - out["low"]).replace(0, np.nan)
        upper = out["high"] - out[["open", "close"]].max(axis=1)
        lower = out[["open", "close"]].min(axis=1) - out["low"]
        out["wick_max_ratio"] = pd.concat([upper / rng, lower / rng], axis=1).max(axis=1)
        out["range_atr"] = rng / out["atr"]
        return out

    def get_base(self, symbol: str, tf: str) -> pd.DataFrame:
        key = (symbol, tf)
        if key in self.base_cache:
            return self.base_cache[key]
        base_tf = "5m" if tf == "5m" else "15m"
        raw = self.load_symbol(symbol, base_tf)
        if tf != base_tf:
            raw = self.resample_ohlcv(raw, tf)
        self.base_cache[key] = self.add_features(raw)
        return self.base_cache[key]

    def get_merged(self, symbol: str, entry_tf: str, filter_tf: str) -> pd.DataFrame:
        key = (symbol, entry_tf, filter_tf)
        if key in self.merge_cache:
            return self.merge_cache[key]
        entry = self.get_base(symbol, entry_tf).copy()
        base_tf = "5m" if filter_tf == "5m" else "15m"
        filt = self.load_symbol(symbol, base_tf)
        if filter_tf != base_tf:
            filt = self.resample_ohlcv(filt, filter_tf)
        filt = self.add_features(filt)
        cols = [
            "close",
            "ema_fast",
            "ema_slow",
            "ema_200",
            "rsi",
            "adx",
            "plus_di",
            "minus_di",
            "macd_hist",
            "bb_mid",
            "bb_up",
            "bb_dn",
            "bb_width",
            "vwap20",
        ]
        filt = filt[cols].copy()
        filt.columns = [f"f_{c}" for c in filt.columns]
        merged = entry.join(filt.reindex(entry.index, method="ffill")).dropna()
        self.merge_cache[key] = merged
        return merged

    @staticmethod
    def family_signals(df: pd.DataFrame, family: str, p: dict[str, float]) -> tuple[np.ndarray, np.ndarray]:
        o = df["open"]
        c = df["close"]
        h = df["high"]
        low = df["low"]
        rsi_ = df["rsi"]
        frsi = df["f_rsi"]
        adx_ = df["adx"]
        macdh = df["macd_hist"]
        ef = df["ema_fast"]
        es = df["ema_slow"]
        bbm = df["bb_mid"]
        bbu = df["bb_up"]
        bbd = df["bb_dn"]
        bbw = df["bb_width"]
        atr_ = df["atr"]
        fef = df["f_ema_fast"]
        fes = df["f_ema_slow"]
        fadx = df["f_adx"]
        df["f_macd_hist"]
        fclose = df["f_close"]

        trend_up = ((fef > fes) | (fclose > df["f_ema_200"]))
        trend_dn = ((fef < fes) | (fclose < df["f_ema_200"]))
        trend_strong = fadx > p["f_adx_floor"]
        adx_ok = adx_ > p["adx_floor"]
        bb_active = bbw > p["bbw_floor"]
        bb_compress = bbw < (df["bb_width_ma"] * 0.9)
        macd_up = (macdh > 0) & (macdh.shift(1) <= 0)
        macd_dn = (macdh < 0) & (macdh.shift(1) >= 0)
        # 保留原策略筛选占位，避免无意义布尔表达式
        wick_ok = (df["range_atr"] < p["wick_atr"]) & (df["wick_max_ratio"] < p["wick_ratio"])
        sweep_low = (low < (df["ll20"].shift(1) - p["sweep_atr"] * atr_)) & (c > df["ll20"].shift(1))
        sweep_high = (h > (df["hh20"].shift(1) + p["sweep_atr"] * atr_)) & (c < df["hh20"].shift(1))
        retest_fail_long = (low.shift(1) < df["hh10"].shift(2)) & (c > df["hh10"].shift(2)) & (c > ef)
        retest_fail_short = (h.shift(1) > df["ll10"].shift(2)) & (c < df["ll10"].shift(2)) & (c < ef)
        pullback_long = trend_up & trend_strong & (low <= ef) & (c > ef) & (rsi_ > 50)
        pullback_short = trend_dn & trend_strong & (h >= ef) & (c < ef) & (rsi_ < 50)
        range_regime = fadx < max(18, p["f_adx_floor"] - 2)

        if family == "ma_macd_bb":
            long = macd_up & (ef > es) & adx_ok & trend_up & (c > bbm) & bb_active & wick_ok
            short = macd_dn & (ef < es) & adx_ok & trend_dn & (c < bbm) & bb_active & wick_ok
        elif family == "bb_meanrev":
            long = (c < bbd) & (rsi_ < 34) & (frsi > 48) & wick_ok
            short = (c > bbu) & (rsi_ > 66) & (frsi < 52) & wick_ok
        elif family == "sweep_reclaim":
            long = sweep_low & (frsi > 46) & ((trend_up & ~trend_strong) | range_regime) & wick_ok
            short = sweep_high & (frsi < 54) & ((trend_dn & ~trend_strong) | range_regime) & wick_ok
        elif family == "retest_fail":
            long = retest_fail_long & (frsi >= 50) & (adx_ok | trend_strong) & wick_ok
            short = retest_fail_short & (frsi <= 50) & (adx_ok | trend_strong) & wick_ok
        elif family == "squeeze_pullback":
            long = bb_compress.shift(1).fillna(False) & pullback_long & wick_ok
            short = bb_compress.shift(1).fillna(False) & pullback_short & wick_ok
        elif family == "range_revert_grid":
            long = range_regime & (c < bbd) & (rsi_ < 38) & (o > c) & wick_ok
            short = range_regime & (c > bbu) & (rsi_ > 62) & (o < c) & wick_ok
        else:
            raise KeyError(family)
        return long.fillna(False).to_numpy(), short.fillna(False).to_numpy()

    @staticmethod
    def apply_vote_gate(
        df: pd.DataFrame,
        base_long: np.ndarray,
        base_short: np.ndarray,
        helper_pairs: list[tuple[np.ndarray, np.ndarray]],
        min_votes: int,
        window: int,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        if not helper_pairs or min_votes <= 0:
            zeros = np.zeros(len(df), dtype=int)
            return base_long.copy(), base_short.copy(), zeros, zeros

        long_votes = np.zeros(len(df), dtype=int)
        short_votes = np.zeros(len(df), dtype=int)
        for long_sig, short_sig in helper_pairs:
            long_series = pd.Series(long_sig.astype(int), index=df.index).rolling(window, min_periods=1).max().fillna(0).astype(int).to_numpy()
            short_series = pd.Series(short_sig.astype(int), index=df.index).rolling(window, min_periods=1).max().fillna(0).astype(int).to_numpy()
            long_votes += long_series
            short_votes += short_series
        gated_long = base_long & (long_votes >= min_votes)
        gated_short = base_short & (short_votes >= min_votes)
        return gated_long, gated_short, long_votes, short_votes

    @staticmethod
    def backtest(
        df: pd.DataFrame,
        long_sig: np.ndarray,
        short_sig: np.ndarray,
        p: dict[str, float],
        mode: str,
        fee_bps: float = 4.0,
        cooldown_bars: int = 4,
    ) -> tuple[pd.DataFrame, float]:
        arr = df[["open", "high", "low", "close", "atr", "adx", "f_adx"]].to_numpy()
        idx = df.index.to_numpy()
        fee = fee_bps / 10000.0
        pos = 0
        entry = 0.0
        stop = 0.0
        lev = 1
        hold = 0
        mfe = 0.0
        entry_time = None
        cooldown = 0
        eq = 1.0
        peak = 1.0
        maxdd = 0.0
        trades: list[tuple[object, object, int, int, float, float, float, str, int]] = []

        if mode == "long_only":
            short_sig = np.zeros_like(short_sig, dtype=bool)
        elif mode == "short_only":
            long_sig = np.zeros_like(long_sig, dtype=bool)

        for i in range(1, len(df) - 1):
            _o, h, low, c, atrv, adxv, fadxv = arr[i]
            nxt_open = arr[i + 1][0]
            if pos != 0:
                hold += 1
                pnl_unlev = pos * ((c - entry) / entry)
                if pnl_unlev > mfe:
                    mfe = pnl_unlev
                armed = mfe >= p["arm_rr"] * (abs(entry - stop) / entry)
                exit_price = None
                reason = None
                if pos == 1:
                    dyn_stop = stop if not armed else max(stop, c - p["trail_atr"] * atrv)
                    if low <= dyn_stop:
                        exit_price = dyn_stop
                        reason = "trail" if armed else "stop"
                    elif short_sig[i] or hold >= p["max_hold"]:
                        exit_price = nxt_open
                        reason = "flip" if short_sig[i] else "time"
                else:
                    dyn_stop = stop if not armed else min(stop, c + p["trail_atr"] * atrv)
                    if h >= dyn_stop:
                        exit_price = dyn_stop
                        reason = "trail" if armed else "stop"
                    elif long_sig[i] or hold >= p["max_hold"]:
                        exit_price = nxt_open
                        reason = "flip" if long_sig[i] else "time"
                if exit_price is not None:
                    ret = pos * ((exit_price - entry) / entry) * lev - 2 * fee * lev
                    eq *= max(1e-9, 1.0 + ret)
                    peak = max(peak, eq)
                    maxdd = min(maxdd, eq / peak - 1.0)
                    trades.append((entry_time, idx[i], pos, lev, entry, exit_price, ret, reason, hold))
                    pos = 0
                    cooldown = cooldown_bars
            else:
                if cooldown > 0:
                    cooldown -= 1
                    continue
                if long_sig[i]:
                    pos = 1
                    entry = nxt_open
                    lev = 1 + int((adxv > 24) and (fadxv > 24))
                    stop = entry - p["stop_atr"] * atrv
                    entry_time = idx[i + 1]
                    hold = 0
                    mfe = 0.0
                elif short_sig[i]:
                    pos = -1
                    entry = nxt_open
                    lev = 1 + int((adxv > 24) and (fadxv > 24))
                    stop = entry + p["stop_atr"] * atrv
                    entry_time = idx[i + 1]
                    hold = 0
                    mfe = 0.0
        tdf = pd.DataFrame(
            trades,
            columns=["entry_time", "exit_time", "side", "lev", "entry", "exit", "ret", "reason", "bars"],
        )
        if not tdf.empty:
            tdf["win"] = tdf["ret"] > 0
        return tdf, maxdd * 100.0

    @staticmethod
    def metrics_from_trades(tdf: pd.DataFrame) -> dict[str, float]:
        if tdf.empty:
            return {"trades": 0, "win_rate": 0.0, "ret_pct": 0.0, "pf": 0.0, "avg_lev": 0.0}
        wins = float(tdf.loc[tdf.ret > 0, "ret"].sum())
        losses = float(-tdf.loc[tdf.ret < 0, "ret"].sum())
        pf = wins / losses if losses > 0 else 999.0
        eq = float((1.0 + tdf["ret"]).prod() - 1.0)
        return {
            "trades": int(len(tdf)),
            "win_rate": float(tdf["win"].mean() * 100.0),
            "ret_pct": eq * 100.0,
            "pf": pf,
            "avg_lev": float(tdf["lev"].mean()),
        }

    def metrics_windows(self, df: pd.DataFrame, long_sig: np.ndarray, short_sig: np.ndarray, p: dict[str, float], mode: str) -> dict[str, float]:
        full_trades, full_dd = self.backtest(df, long_sig, short_sig, p, mode)
        recent_start = df.index.max() - pd.DateOffset(years=self.recent_years)
        wf_start = df.index.max() - pd.DateOffset(months=self.wf_months)

        recent_df = df[df.index >= recent_start]
        r_mask = df.index >= recent_start
        recent_trades, recent_dd = self.backtest(recent_df, long_sig[r_mask], short_sig[r_mask], p, mode)

        wf_df = df[df.index >= wf_start]
        w_mask = df.index >= wf_start
        wf_trades, wf_dd = self.backtest(wf_df, long_sig[w_mask], short_sig[w_mask], p, mode)

        full = self.metrics_from_trades(full_trades)
        recent = self.metrics_from_trades(recent_trades)
        wf = self.metrics_from_trades(wf_trades)
        return {
            "full_trades": full["trades"],
            "full_win": full["win_rate"],
            "full_ret": full["ret_pct"],
            "full_pf": full["pf"],
            "full_dd": full_dd,
            "full_lev": full["avg_lev"],
            "recent_trades": recent["trades"],
            "recent_win": recent["win_rate"],
            "recent_ret": recent["ret_pct"],
            "recent_pf": recent["pf"],
            "recent_dd": recent_dd,
            "recent_lev": recent["avg_lev"],
            "wf_trades": wf["trades"],
            "wf_win": wf["win_rate"],
            "wf_ret": wf["ret_pct"],
            "wf_pf": wf["pf"],
            "wf_dd": wf_dd,
            "wf_lev": wf["avg_lev"],
        }

    def evaluate_seed(self, seed: dict[str, str]) -> tuple[list[dict[str, object]], dict[str, object]]:
        entry_tf = seed["entry_tf"]
        filter_tf = seed["filter_tf"]
        symbol = seed["symbol"]
        seed_id = seed["seed_id"]
        if entry_tf == "5m" and not (self.raw_dir / f"{symbol}_5m.csv").exists():
            return [], {"seed_id": seed_id, "status": "SKIP", "reason": "missing_5m_raw"}

        p = PARAM_MAP[seed["param_id"]]
        df = self.get_merged(symbol, entry_tf, filter_tf)
        base_long, base_short = self.family_signals(df, seed["family"], p)
        helper_signal_map: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        for fam in HELPER_FAMILIES:
            helper_signal_map[fam] = self.family_signals(df, fam, p)

        results: list[dict[str, object]] = []
        base_recent_trades = None
        base_wf_trades = None
        base_recent_pf = None
        base_recent_win = None
        for spec in VARIANTS:
            gated_long, gated_short, long_votes, short_votes = self.apply_vote_gate(
                df=df,
                base_long=base_long,
                base_short=base_short,
                helper_pairs=[helper_signal_map[h] for h in spec["helpers"]],
                min_votes=spec["min_votes"],
                window=spec["window"],
            )
            metrics = self.metrics_windows(df, gated_long, gated_short, p, seed["mode"])
            row: dict[str, object] = {
                "seed_id": seed_id,
                "role": seed["role"],
                "symbol": symbol,
                "entry_tf": entry_tf,
                "filter_tf": filter_tf,
                "family": seed["family"],
                "param_id": seed["param_id"],
                "mode": seed["mode"],
                "variant": spec["variant"],
                "helper_set": ",".join(spec["helpers"]),
                "min_votes": spec["min_votes"],
                "confirm_window_bars": spec["window"],
                "helper_count": len(spec["helpers"]),
                "signal_long_count": int(gated_long.sum()),
                "signal_short_count": int(gated_short.sum()),
                "avg_long_votes": float(long_votes[base_long].mean()) if base_long.any() else 0.0,
                "avg_short_votes": float(short_votes[base_short].mean()) if base_short.any() else 0.0,
            }
            row.update(metrics)
            if spec["variant"] == "base":
                base_recent_trades = metrics["recent_trades"]
                base_wf_trades = metrics["wf_trades"]
                base_recent_pf = metrics["recent_pf"]
                base_recent_win = metrics["recent_win"]
                row["recommendation"] = "base_reference"
            results.append(row)

        base_recent_trades = int(base_recent_trades or 0)
        base_wf_trades = int(base_wf_trades or 0)
        base_recent_pf = float(base_recent_pf or 0.0)
        base_recent_win = float(base_recent_win or 0.0)
        for row in results:
            row["base_recent_trades"] = base_recent_trades
            row["base_wf_trades"] = base_wf_trades
            row["win_delta_recent"] = float(row["recent_win"] - base_recent_win)
            row["pf_delta_recent"] = float(row["recent_pf"] - base_recent_pf)
            row["trade_keep_ratio_recent"] = float(row["recent_trades"] / base_recent_trades) if base_recent_trades else 0.0
            is_candidate = (
                row["variant"] != "base"
                and row["recent_trades"] >= max(4, ceil(base_recent_trades * 0.15))
                and row["wf_trades"] >= max(3, ceil(base_wf_trades * 0.15))
                and row["recent_pf"] >= max(1.0, base_recent_pf * 0.75)
                and row["wf_pf"] >= 1.0
                and row["recent_ret"] > 0
            )
            if row.get("recommendation") != "base_reference":
                if is_candidate and row["win_delta_recent"] >= 5.0 and row["pf_delta_recent"] >= -0.15:
                    row["recommendation"] = "promote_confirmation_gate"
                elif is_candidate:
                    row["recommendation"] = "keep_research_gate"
                else:
                    row["recommendation"] = "discard_gate"

        status = {"seed_id": seed_id, "status": "OK", "reason": "evaluated", "variants": len(results)}
        return results, status

    def run(self) -> dict[str, object]:
        rows: list[dict[str, object]] = []
        seed_status: list[dict[str, object]] = []
        for seed in SEED_LANES:
            print(f"[stage231] seed={seed['seed_id']}", flush=True)
            seed_rows, status = self.evaluate_seed(seed)
            rows.extend(seed_rows)
            seed_status.append(status)
            if rows:
                pd.DataFrame(rows).to_csv(self.out_dir / "stage231_seeded_confirmation_matrix_all.partial.csv", index=False)

        df = pd.DataFrame(rows)
        if not df.empty:
            df.to_csv(self.out_dir / "stage231_seeded_confirmation_matrix_all.csv", index=False)
        else:
            pd.DataFrame().to_csv(self.out_dir / "stage231_seeded_confirmation_matrix_all.csv", index=False)

        summary_by_seed: dict[str, object] = {}
        promote_total = 0
        for seed in SEED_LANES:
            sid = seed["seed_id"]
            sub = df[df["seed_id"] == sid].copy() if not df.empty else pd.DataFrame()
            if sub.empty:
                summary_by_seed[sid] = {"status": "SKIP", "reason": "no_rows"}
                continue
            base = sub[sub["variant"] == "base"].iloc[0].to_dict()
            candidates = sub[sub["variant"] != "base"].copy()
            candidates.sort_values(
                ["recommendation", "recent_win", "recent_pf", "recent_ret", "wf_win", "wf_pf"],
                ascending=[True, False, False, False, False, False],
                inplace=True,
            )
            promoted = candidates[candidates["recommendation"] == "promote_confirmation_gate"].copy()
            promote_total += int(len(promoted))
            summary_by_seed[sid] = {
                "seed_meta": seed,
                "base": {k: base[k] for k in [
                    "recent_trades", "recent_win", "recent_ret", "recent_pf", "wf_trades", "wf_win", "wf_ret", "wf_pf", "full_ret", "full_pf"
                ]},
                "top_confirmation": candidates.head(5).to_dict(orient="records"),
                "promoted_confirmation": promoted.head(5).to_dict(orient="records"),
            }

        summary = {
            "status": "OK",
            "ranking_policy": {
                "primary": f"recent_{self.recent_years}y_win_then_pf",
                "secondary": f"wf_{self.wf_months}m_pf",
                "full_sample": "soft_constraint_only",
            },
            "seed_status": seed_status,
            "seed_lanes": SEED_LANES,
            "helper_families": HELPER_FAMILIES,
            "variants": VARIANTS,
            "tested_rows": int(len(df)),
            "promote_total": promote_total,
            "summary_by_seed": summary_by_seed,
        }
        (self.out_dir / "stage231_seeded_confirmation_matrix_summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        lines: list[str] = []
        lines.append("[stage231_seeded_confirmation_matrix]")
        lines.append("goal=seed lanes -> confirmation gates / no runtime switch")
        lines.append(f"tested_rows={len(df)}")
        lines.append(f"promote_total={promote_total}")
        lines.append("ranking=近2年胜率优先 -> 近2年PF -> 近2年收益 -> WF PF | 6年仅软约束")
        lines.append("")
        for seed in SEED_LANES:
            sid = seed["seed_id"]
            lines.append(f"[{sid}]")
            sub = df[df["seed_id"] == sid].copy() if not df.empty else pd.DataFrame()
            if sub.empty:
                reason = next((x["reason"] for x in seed_status if x["seed_id"] == sid), "no_rows")
                lines.append(f"status=SKIP | reason={reason}")
                lines.append("")
                continue
            base = sub[sub["variant"] == "base"].iloc[0]
            lines.append(
                "base="
                f"{seed['symbol']} | {seed['entry_tf']}/{seed['filter_tf']} | {seed['family']} | {seed['param_id']} | {seed['mode']} "
                f"| recent={base['recent_ret']:.2f}%/{base['recent_win']:.2f}%/PF{base['recent_pf']:.3f} "
                f"| wf={base['wf_ret']:.2f}%/{base['wf_win']:.2f}%/PF{base['wf_pf']:.3f}"
            )
            promoted = sub[sub["recommendation"] == "promote_confirmation_gate"].copy()
            if promoted.empty:
                keep = sub[sub["variant"] != "base"].sort_values(
                    ["recent_win", "recent_pf", "recent_ret", "wf_pf"],
                    ascending=[False, False, False, False],
                ).head(3)
                lines.append("promoted=none")
                lines.append("top_research=")
                for _, r in keep.iterrows():
                    lines.append(
                        f"- {r['variant']} | recent={r['recent_ret']:.2f}%/{r['recent_win']:.2f}%/PF{r['recent_pf']:.3f} "
                        f"| wf={r['wf_ret']:.2f}%/PF{r['wf_pf']:.3f} | keep_ratio={r['trade_keep_ratio_recent']:.2f}"
                    )
            else:
                lines.append("promoted=")
                promoted = promoted.sort_values(
                    ["recent_win", "recent_pf", "recent_ret", "wf_pf"],
                    ascending=[False, False, False, False],
                ).head(3)
                for _, r in promoted.iterrows():
                    lines.append(
                        f"- {r['variant']} | recent={r['recent_ret']:.2f}%/{r['recent_win']:.2f}%/PF{r['recent_pf']:.3f} "
                        f"| wf={r['wf_ret']:.2f}%/PF{r['wf_pf']:.3f} | win_delta={r['win_delta_recent']:.2f} | keep_ratio={r['trade_keep_ratio_recent']:.2f}"
                    )
            lines.append("")
        (self.out_dir / "stage231_seeded_confirmation_matrix_latest.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return summary


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-dir", required=True)
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    lab = SeededConfirmationMatrix(Path(args.project_dir))
    lab.run()


if __name__ == "__main__":
    main()
