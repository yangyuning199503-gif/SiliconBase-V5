from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

SYMBOLS_DEFAULT = ["btc", "bnb", "eth", "sol"]
FAMILIES = [
    "ma_macd_bb",
    "ma_rsi_adx",
    "breakout_atr_adx",
    "reclaim_atr_rsi",
    "macd_vwap_adx",
    "bb_meanrev",
    "sweep_reclaim",
    "retest_fail",
    "squeeze_pullback",
    "range_revert_grid",
]
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
MODES = ["dual", "long_only", "short_only"]


class ExpandedComboLab:
    def __init__(self, root: Path, symbols: list[str], recent_years: int = 2, wf_months: int = 12):
        self.root = root
        self.raw_dir = root / "data" / "raw"
        self.out_dir = root / "reports" / "research_raw"
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.symbols = symbols
        self.recent_years = recent_years
        self.wf_months = wf_months
        self.raw_cache: dict[tuple[str, str], pd.DataFrame] = {}
        self.base_cache: dict[tuple[str, str], pd.DataFrame] = {}
        self.merge_cache: dict[tuple[str, str, str], pd.DataFrame] = {}
        self.pairings = self._build_pairings()

    def _build_pairings(self) -> list[tuple[str, str]]:
        pairings: list[tuple[str, str]] = [
            ("15m", "1h"),
            ("15m", "4h"),
            ("30m", "1h"),
            ("30m", "4h"),
            ("1h", "4h"),
        ]
        if all((self.raw_dir / f"{sym}_5m.csv").exists() for sym in self.symbols):
            pairings = [("5m", "15m"), ("5m", "1h"), ("5m", "4h")] + pairings
        return pairings

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

    def get_base(self, symbol: str, entry_tf: str) -> pd.DataFrame:
        key = (symbol, entry_tf)
        if key in self.base_cache:
            return self.base_cache[key]
        base_tf = "5m" if entry_tf == "5m" else "15m"
        df = self.load_symbol(symbol, base_tf)
        if entry_tf != base_tf:
            df = self.resample_ohlcv(df, entry_tf)
        self.base_cache[key] = self.add_features(df)
        return self.base_cache[key]

    def get_merged(self, symbol: str, entry_tf: str, filter_tf: str) -> pd.DataFrame:
        key = (symbol, entry_tf, filter_tf)
        if key in self.merge_cache:
            return self.merge_cache[key]
        entry = self.get_base(symbol, entry_tf).copy()
        base_tf = "5m" if filter_tf == "5m" else "15m"
        filt_raw = self.load_symbol(symbol, base_tf)
        if filter_tf != base_tf:
            filt_raw = self.resample_ohlcv(filt_raw, filter_tf)
        filt = self.add_features(filt_raw)
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
    def signal_family(df: pd.DataFrame, family: str, p: dict[str, float]) -> tuple[np.ndarray, np.ndarray]:
        c = df["close"]
        h = df["high"]
        low = df["low"]
        o = df["open"]
        rsi_ = df["rsi"]
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
        fmacd = df["f_macd_hist"]
        fclose = df["f_close"]
        frsi = df["f_rsi"]
        trend_up = ((fef > fes) | (fclose > df["f_ema_200"]))
        trend_dn = ((fef < fes) | (fclose < df["f_ema_200"]))
        trend_strong = fadx > p["f_adx_floor"]
        adx_ok = adx_ > p["adx_floor"]
        bb_active = bbw > p["bbw_floor"]
        bb_compress = bbw < (df["bb_width_ma"] * 0.9)
        macd_up = (macdh > 0) & (macdh.shift(1) <= 0)
        macd_dn = (macdh < 0) & (macdh.shift(1) >= 0)
        rec_up = (c > ef) & (low.shift(1) < es.shift(1)) & (c.shift(1) < es.shift(1))
        rec_dn = (c < ef) & (h.shift(1) > es.shift(1)) & (c.shift(1) > es.shift(1))
        breakout_up = c > df["hh20"].shift(1) + p["bo_atr"] * atr_
        breakout_dn = c < df["ll20"].shift(1) - p["bo_atr"] * atr_
        vwap_up = c > df["vwap20"]
        vwap_dn = c < df["vwap20"]
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
        elif family == "ma_rsi_adx":
            long = (ef > es) & (rsi_ > 56) & adx_ok & trend_up & (fmacd > 0) & wick_ok
            short = (ef < es) & (rsi_ < 44) & adx_ok & trend_dn & (fmacd < 0) & wick_ok
        elif family == "breakout_atr_adx":
            long = breakout_up & adx_ok & trend_up & trend_strong & wick_ok
            short = breakout_dn & adx_ok & trend_dn & trend_strong & wick_ok
        elif family == "reclaim_atr_rsi":
            long = rec_up & (rsi_ > 52) & adx_ok & trend_up & wick_ok
            short = rec_dn & (rsi_ < 48) & adx_ok & trend_dn & wick_ok
        elif family == "macd_vwap_adx":
            long = macd_up & adx_ok & vwap_up & trend_up & wick_ok
            short = macd_dn & adx_ok & vwap_dn & trend_dn & wick_ok
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
    def backtest(df: pd.DataFrame, long_sig: np.ndarray, short_sig: np.ndarray, p: dict[str, float], mode: str, fee_bps: float = 4.0, cooldown_bars: int = 4) -> tuple[pd.DataFrame, float]:
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
                    elif (mode == "dual" and short_sig[i]) or hold >= p["max_hold"]:
                        exit_price = nxt_open
                        reason = "flip" if (mode == "dual" and short_sig[i]) else "time"
                else:
                    dyn_stop = stop if not armed else min(stop, c + p["trail_atr"] * atrv)
                    if h >= dyn_stop:
                        exit_price = dyn_stop
                        reason = "trail" if armed else "stop"
                    elif (mode == "dual" and long_sig[i]) or hold >= p["max_hold"]:
                        exit_price = nxt_open
                        reason = "flip" if (mode == "dual" and long_sig[i]) else "time"
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
            return {"trades": 0, "win_rate": 0.0, "ret_pct": 0.0, "pf": 0.0, "avg_lev": 0.0, "expectancy_bp": 0.0}
        wins = float(tdf.loc[tdf.ret > 0, "ret"].sum())
        losses = float(-tdf.loc[tdf.ret < 0, "ret"].sum())
        pf = wins / losses if losses > 0 else 999.0
        eq = float((1.0 + tdf["ret"]).prod() - 1.0)
        expectancy = float(tdf["ret"].mean() * 10000.0)
        return {
            "trades": int(len(tdf)),
            "win_rate": float(tdf["win"].mean() * 100.0),
            "ret_pct": eq * 100.0,
            "pf": pf,
            "avg_lev": float(tdf["lev"].mean()),
            "expectancy_bp": expectancy,
        }

    def evaluate(self, symbol: str, entry_tf: str, filter_tf: str, family: str, p: dict[str, float], mode: str) -> dict[str, float]:
        df = self.get_merged(symbol, entry_tf, filter_tf)
        long_sig, short_sig = self.signal_family(df, family, p)
        full_trades, full_dd = self.backtest(df, long_sig, short_sig, p, mode=mode)

        recent_start = df.index.max() - pd.DateOffset(years=self.recent_years)
        wf_start = df.index.max() - pd.DateOffset(months=self.wf_months)

        recent_df = df[df.index >= recent_start]
        rlong, rshort = self.signal_family(recent_df, family, p)
        recent_trades, recent_dd = self.backtest(recent_df, rlong, rshort, p, mode=mode)

        wf_df = df[df.index >= wf_start]
        wlong, wshort = self.signal_family(wf_df, family, p)
        wf_trades, wf_dd = self.backtest(wf_df, wlong, wshort, p, mode=mode)

        full = self.metrics_from_trades(full_trades)
        recent = self.metrics_from_trades(recent_trades)
        wf = self.metrics_from_trades(wf_trades)
        return {
            "symbol": symbol,
            "entry_tf": entry_tf,
            "filter_tf": filter_tf,
            "family": family,
            "param_id": p["param_id"],
            "mode": mode,
            "full_trades": full["trades"],
            "full_win": full["win_rate"],
            "full_ret": full["ret_pct"],
            "full_pf": full["pf"],
            "full_dd": full_dd,
            "full_lev": full["avg_lev"],
            "full_exp_bp": full["expectancy_bp"],
            "recent_trades": recent["trades"],
            "recent_win": recent["win_rate"],
            "recent_ret": recent["ret_pct"],
            "recent_pf": recent["pf"],
            "recent_dd": recent_dd,
            "recent_lev": recent["avg_lev"],
            "recent_exp_bp": recent["expectancy_bp"],
            "wf_trades": wf["trades"],
            "wf_win": wf["win_rate"],
            "wf_ret": wf["ret_pct"],
            "wf_pf": wf["pf"],
            "wf_dd": wf_dd,
            "wf_lev": wf["avg_lev"],
            "wf_exp_bp": wf["expectancy_bp"],
        }

    @staticmethod
    def hard_filter(r: pd.Series) -> bool:
        return bool(
            (r["recent_trades"] >= 8)
            and (r["wf_trades"] >= 5)
            and (r["full_trades"] >= 25)
            and (r["recent_pf"] >= 1.0)
            and (r["wf_pf"] >= 1.0)
            and (r["recent_ret"] > 0)
            and (r["wf_ret"] > -10)
        )

    def run(self) -> dict[str, object]:
        rows: list[dict[str, float]] = []
        skipped: list[dict[str, str]] = []
        for symbol in self.symbols:
            print(f"[stage230] symbol={symbol}", flush=True)
            for entry_tf, filter_tf in self.pairings:
                print(f"[stage230] pairing={symbol}:{entry_tf}/{filter_tf}", flush=True)
                if entry_tf == "5m" and not (self.raw_dir / f"{symbol}_5m.csv").exists():
                    skipped.append({"symbol": symbol, "entry_tf": entry_tf, "reason": "missing_5m_raw"})
                    continue
                for family in FAMILIES:
                    for p in PARAMS:
                        for mode in MODES:
                            rows.append(self.evaluate(symbol, entry_tf, filter_tf, family, p, mode))
                if rows:
                    pd.DataFrame(rows).to_csv(self.out_dir / "stage230_expanded_combo_matrix_all.partial.csv", index=False)
        df = pd.DataFrame(rows)
        df.to_csv(self.out_dir / "stage230_expanded_combo_matrix_all.csv", index=False)

        passed = df[df.apply(self.hard_filter, axis=1)].copy()
        passed.sort_values(
            ["symbol", "mode", "recent_win", "recent_pf", "recent_ret", "wf_win", "wf_pf", "full_pf"],
            ascending=[True, True, False, False, False, False, False, False],
            inplace=True,
        )

        summary_top: dict[str, dict[str, list[dict[str, object]]]] = {}
        for symbol in self.symbols:
            summary_top[symbol] = {}
            for mode in MODES:
                pool = passed[(passed.symbol == symbol) & (passed.mode == mode)].copy()
                if pool.empty:
                    pool = df[(df.symbol == symbol) & (df.mode == mode)].copy()
                    pool.sort_values(
                        ["recent_win", "recent_pf", "recent_ret", "wf_win", "wf_pf"],
                        ascending=[False, False, False, False, False],
                        inplace=True,
                    )
                    pool["selection_mode"] = "fallback_recent_first"
                else:
                    pool["selection_mode"] = "hard_filter_pass"
                summary_top[symbol][mode] = pool.head(5).to_dict(orient="records")

        combo_counts = (
            passed.assign(
                combo_key=lambda x: x["family"]
                + "|"
                + x["entry_tf"]
                + "|"
                + x["filter_tf"]
                + "|"
                + x["param_id"]
                + "|"
                + x["mode"]
            )
            .groupby(["family", "entry_tf", "filter_tf", "param_id", "mode"], as_index=False)
            .size()
            .rename(columns={"size": "symbols_hit"})
            .sort_values(["symbols_hit", "family", "mode"], ascending=[False, True, True])
        )
        by_family = (
            passed.groupby("family", as_index=False)
            .agg(hard_pass_count=("family", "size"), recent_ret_median=("recent_ret", "median"), wf_ret_median=("wf_ret", "median"))
            .sort_values(["hard_pass_count", "wf_ret_median", "recent_ret_median"], ascending=[False, False, False])
        )

        summary = {
            "status": "OK",
            "tested_symbols": self.symbols,
            "pairings_used": self.pairings,
            "five_min_ready": all((self.raw_dir / f"{sym}_5m.csv").exists() for sym in self.symbols),
            "tested_rows": int(len(df)),
            "hard_pass_rows": int(len(passed)),
            "skipped": skipped,
            "ranking_policy": {
                "primary": f"recent_{self.recent_years}y",
                "secondary": f"wf_{self.wf_months}m",
                "full_sample": "soft_constraint_only",
                "priority": ["recent_win", "recent_pf", "recent_ret", "wf_win", "wf_pf"],
            },
            "hard_filter": {
                "recent_trades_min": 8,
                "wf_trades_min": 5,
                "full_trades_min": 25,
                "recent_pf_min": 1.0,
                "wf_pf_min": 1.0,
                "recent_ret_positive": True,
                "wf_ret_floor": -10.0,
            },
            "params": PARAMS,
            "top_by_symbol_mode": summary_top,
            "shared_transferability": combo_counts.head(25).to_dict(orient="records"),
            "family_hard_pass_rank": by_family.to_dict(orient="records"),
        }
        (self.out_dir / "stage230_expanded_combo_matrix_summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        lines: list[str] = []
        lines.append("[stage230_expanded_combo_matrix]")
        lines.append(f"tested_symbols={','.join(self.symbols)}")
        lines.append(f"pairings={self.pairings}")
        lines.append(f"five_min_ready={summary['five_min_ready']}")
        lines.append(f"tested_rows={summary['tested_rows']}")
        lines.append(f"hard_pass_rows={summary['hard_pass_rows']}")
        if skipped:
            lines.append(f"skipped={json.dumps(skipped, ensure_ascii=False)}")
        lines.append("")
        lines.append("[recent_first_science]")
        lines.append("primary=近2年优先 | wf=近12个月样本外 | 6年仅做软约束")
        lines.append("")
        lines.append("[family_hard_pass_rank]")
        if by_family.empty:
            lines.append("- no hard-pass family yet")
        else:
            for _, r in by_family.iterrows():
                lines.append(
                    f"- {r['family']} | hard_pass={int(r['hard_pass_count'])} | recent_median={r['recent_ret_median']:.2f}% | wf_median={r['wf_ret_median']:.2f}%"
                )
        lines.append("")
        for symbol in self.symbols:
            lines.append(f"[{symbol}]")
            for mode in MODES:
                rows_mode = summary_top[symbol][mode]
                if not rows_mode:
                    continue
                lines.append(f"mode={mode}")
                for row in rows_mode[:3]:
                    lines.append(
                        f"- {row['family']} | {row['entry_tf']}/{row['filter_tf']} | {row['param_id']} | recent_win={row['recent_win']:.2f}% | recent_ret={row['recent_ret']:.2f}% | recent_pf={row['recent_pf']:.3f} | wf_ret={row['wf_ret']:.2f}% | wf_pf={row['wf_pf']:.3f} | selection={row.get('selection_mode','')}"
                    )
            lines.append("")
        lines.append("[shared_transferability]")
        for row in combo_counts.head(15).to_dict(orient="records"):
            lines.append(
                f"- {row['family']} | {row['entry_tf']}/{row['filter_tf']} | {row['param_id']} | {row['mode']} | symbols_hit={int(row['symbols_hit'])}"
            )
        (self.out_dir / "stage230_expanded_combo_matrix_latest.txt").write_text("\n".join(lines), encoding="utf-8")
        return summary


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-dir", type=Path, default=Path(__file__).resolve().parents[1])
    ap.add_argument("--symbols", type=str, default=",".join(SYMBOLS_DEFAULT))
    ap.add_argument("--recent-years", type=int, default=2)
    ap.add_argument("--wf-months", type=int, default=12)
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    symbols = [s.strip().lower() for s in args.symbols.split(",") if s.strip()]
    lab = ExpandedComboLab(args.project_dir.resolve(), symbols, args.recent_years, args.wf_months)
    summary = lab.run()
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
