from __future__ import annotations

import contextlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .indicators import adx as adx_func
from .indicators import atr as atr_func
from .timeparse import parse_time_series


def _to_bool(v: Any, default: bool = False) -> bool:
    """把 YAML/JSON 里的 bool/str/int 统一解析为 bool，避免 bool("false")==True 这类坑。"""
    if isinstance(v, bool):
        return v
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("1", "true", "yes", "y", "on"):
            return True
        if s in ("0", "false", "no", "n", "off", ""):
            return False
    return bool(v)


@dataclass
class Trade:
    symbol: str
    side: str  # LONG / SHORT
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    qty: float
    pnl: float
    pnl_pct: float
    fees: float
    funding: float
    reason: str
    bars_held: int



def _parse_time_like(s: pd.Series) -> pd.DatetimeIndex:
    return parse_time_series(s)


def _funding_event_mask(index: pd.Index, interval_hours: int = 8, event_hours: list[int] | None = None) -> pd.Series:
    ts = pd.DatetimeIndex(index)
    if event_hours:
        hours = sorted({int(h) % 24 for h in event_hours})
    else:
        interval_hours = max(1, int(interval_hours))
        hours = list(range(0, 24, interval_hours))
    mask = np.isin(ts.hour, hours) & (ts.minute == 0) & (ts.second == 0)
    return pd.Series(mask.astype(float), index=index)


def _load_funding_series(symbol: str, index: pd.Index, funding_cfg: dict[str, Any]) -> pd.Series:
    idx = pd.DatetimeIndex(index)
    zero = pd.Series(0.0, index=idx)
    if not _to_bool(funding_cfg.get("enabled", False)):
        return zero

    mode = str(funding_cfg.get("mode", "fixed_bps_per_event")).strip().lower()
    interval_hours = max(1, int(funding_cfg.get("interval_hours", 8)))
    event_hours = funding_cfg.get("event_hours_utc")
    event_mask = _funding_event_mask(idx, interval_hours=interval_hours, event_hours=event_hours)

    if mode in ("fixed", "fixed_bps", "fixed_bps_per_event", "fixed_bps_per_8h"):
        fixed = funding_cfg.get("fixed_bps_per_event", {}) or {}
        if isinstance(fixed, dict):
            rate_bps = float(fixed.get(symbol, fixed.get(str(symbol).lower(), fixed.get("default", 0.0))))
        else:
            rate_bps = float(fixed)
        return (event_mask * (rate_bps / 10000.0)).astype(float)

    if mode != "csv":
        return zero

    template = str(funding_cfg.get("csv_template", "data/funding/{symbol}_funding.csv"))
    path = Path(template.format(symbol=symbol))
    if not path.exists():
        return zero

    df = pd.read_csv(path)
    if df.empty:
        return zero

    cols = {c.lower(): c for c in df.columns}
    tcol = str(funding_cfg.get("csv_time_col", "time")).lower()
    rcol = str(funding_cfg.get("csv_rate_col", "fundingRate")).lower()
    tcol = cols.get(tcol, cols.get("fundingtime", cols.get("time", cols.get("timestamp"))))
    rcol = cols.get(rcol, cols.get("fundingrate", cols.get("rate")))
    if tcol is None or rcol is None:
        return zero

    sdf = df[[tcol, rcol]].rename(columns={tcol: "time", rcol: "rate"}).copy()
    sdf["time"] = _parse_time_like(sdf["time"])
    sdf["rate"] = pd.to_numeric(sdf["rate"], errors="coerce")
    sdf = sdf.dropna(subset=["time", "rate"]).sort_values("time")
    if sdf.empty:
        return zero
    unit = str(funding_cfg.get("csv_rate_unit", "fraction")).strip().lower()
    if unit in ("bps", "bp"):
        sdf["rate"] = sdf["rate"] / 10000.0
    s = sdf.drop_duplicates("time", keep="last").set_index("time")["rate"].astype(float)
    return s.reindex(idx).fillna(0.0).astype(float)


def _load_external_entry_pause(common: pd.Index, symbols: list[str], cfg: dict[str, Any]) -> tuple[dict[str, pd.Series], dict[str, Any]]:
    """加载外部“暂停新开仓”遮罩。CSV 支持：
    - time: 时间戳（ISO / s / ms）
    - symbol: 可选；缺省或 all/* 表示全资产生效
    - pause_new_entries / paused / block: 0/1 或 true/false
    - reason: 可选，仅用于报告
    """
    base = {s: pd.Series(0.0, index=common) for s in symbols}
    meta: dict[str, Any] = {
        "enabled": False,
        "loaded": False,
        "file": None,
        "bars_blocked_by_symbol": dict.fromkeys(symbols, 0),
        "rows_loaded": 0,
    }

    pause_cfg = cfg.get("external_entry_pause", {}) or {}
    if not isinstance(pause_cfg, dict):
        return base, meta
    enabled = _to_bool(pause_cfg.get("enabled", False), False)
    meta["enabled"] = enabled
    if not enabled:
        return base, meta

    file_raw = str(pause_cfg.get("file", "")).strip()
    if not file_raw:
        return base, meta
    path = Path(file_raw).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    meta["file"] = str(path)
    if not path.exists() or not path.is_file():
        return base, meta

    try:
        df = pd.read_csv(path)
    except Exception:
        return base, meta
    if df.empty:
        return base, meta

    cols = {str(c).lower(): c for c in df.columns}
    time_col = cols.get("time") or cols.get("ts") or cols.get("timestamp")
    if time_col is None:
        return base, meta
    pause_col = cols.get("pause_new_entries") or cols.get("paused") or cols.get("block") or cols.get("pause")
    if pause_col is None:
        df["_pause"] = 1
        pause_col = "_pause"
    symbol_col = cols.get("symbol") or cols.get("asset") or cols.get("ticker")

    sdf = df.copy()
    sdf["_time"] = _parse_time_like(sdf[time_col])
    sdf["_pause"] = sdf[pause_col].apply(lambda v: 1.0 if _to_bool(v, False) else 0.0)
    sdf = sdf.dropna(subset=["_time"])
    sdf = sdf.loc[sdf["_pause"] > 0.0].copy()
    if sdf.empty:
        meta["loaded"] = True
        return base, meta

    sdf["_symbol"] = "all"
    if symbol_col is not None:
        sdf["_symbol"] = sdf[symbol_col].astype(str).str.strip().str.lower().replace({"": "all", "*": "all"})
        sdf.loc[sdf["_symbol"].isin(["nan", "none"]), "_symbol"] = "all"
    sdf = sdf.sort_values("_time")

    for sym in symbols:
        subset = sdf.loc[(sdf["_symbol"] == "all") | (sdf["_symbol"] == sym), ["_time", "_pause"]].copy()
        if subset.empty:
            continue
        subset = subset.groupby("_time", as_index=True)["_pause"].max()
        base[sym] = subset.reindex(common).fillna(0.0).astype(float)
        meta["bars_blocked_by_symbol"][sym] = int((base[sym] >= 0.5).sum())

    meta["loaded"] = True
    meta["rows_loaded"] = int(len(sdf))
    return base, meta


def _resample_4h(df15: pd.DataFrame) -> pd.DataFrame:
    # df15 index 为 15m bar 的 open_time（UTC naive）
    ohlc = df15.resample("4h", label="left", closed="left").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    )
    return ohlc.dropna(subset=["open", "high", "low", "close"])


def _resample_1d(df15: pd.DataFrame) -> pd.DataFrame:
    # df15 index 为 15m bar 的 open_time（UTC naive）
    ohlc = df15.resample("1D", label="left", closed="left").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    )
    return ohlc.dropna(subset=["open", "high", "low", "close"])


def prepare_indicators(
    df15: pd.DataFrame,
    breakout_lookback: int,
    breakout_atr_buffer: float,
    atr_period: int,
    adx_period: int,
    expand_enabled: bool,
    expand_pctl: float,
    compress_pctl: float,
    expand_window_4h: int,
    atr_period_4h: int,
    bb_window: int,
    bb_std: float,
    sr_lookback_4h: int,
) -> dict[str, Any]:
    """为单一资产准备 15m + 4H 的指标，并对齐到 15m index（避免前视）。"""
    idx = df15.index

    high = df15["high"].to_numpy(dtype=float)
    low = df15["low"].to_numpy(dtype=float)
    close = df15["close"].to_numpy(dtype=float)

    atr15 = atr_func(high, low, close, atr_period)
    atr15_s = pd.Series(atr15, index=idx)

    donch_high = df15["high"].rolling(breakout_lookback).max().shift(1)
    donch_low = df15["low"].rolling(breakout_lookback).min().shift(1)

    # Bollinger（用于震荡期均值回归；整体 shift(1) 避免前视）
    bb_mid = df15["close"].rolling(bb_window).mean().shift(1)
    bb_std_s = df15["close"].rolling(bb_window).std(ddof=0).shift(1)
    bb_upper = bb_mid + bb_std * bb_std_s
    bb_lower = bb_mid - bb_std * bb_std_s

    # 4H
    df4 = _resample_4h(df15)
    # 4H 支撑/阻力（更稳定的阻力位/支撑位；整体 shift(1) 避免前视）
    sr_high4 = df4["high"].rolling(sr_lookback_4h).max().shift(1)
    sr_low4 = df4["low"].rolling(sr_lookback_4h).min().shift(1)
    sr_high4_15 = sr_high4.reindex(idx, method="ffill")
    sr_low4_15 = sr_low4.reindex(idx, method="ffill")

    h4 = df4["high"].to_numpy(dtype=float)
    l4 = df4["low"].to_numpy(dtype=float)
    c4 = df4["close"].to_numpy(dtype=float)

    adx4, di_p4, di_m4 = adx_func(h4, l4, c4, adx_period)

    atr4 = atr_func(h4, l4, c4, atr_period_4h)
    atr4_s = pd.Series(atr4, index=df4.index)

    if expand_enabled:
        # 波动状态：ATR / rolling_mean(ATR)
        ratio = atr4_s / atr4_s.rolling(expand_window_4h).mean()
        expand_thr = ratio.rolling(expand_window_4h).quantile(expand_pctl)
        compress_thr = ratio.rolling(expand_window_4h).quantile(compress_pctl)

        # expand_ok：用于趋势交易；warmup 阶段（expand_thr 不可用）默认放行，避免前期完全不交易
        expand_ok = ((ratio >= expand_thr) | expand_thr.isna()).astype(float)

        # compress_ok：用于震荡/SR；仅在阈值可用且处于“低波动压缩”时启用
        compress_ok = ((ratio <= compress_thr) & compress_thr.notna()).astype(float)
    else:
        expand_ok = pd.Series(1.0, index=df4.index)
        compress_ok = pd.Series(1.0, index=df4.index)

    df4_ind = pd.DataFrame(
        {
            "adx": adx4,
            "di_plus": di_p4,
            "di_minus": di_m4,
            "expand_ok": expand_ok,
            "compress_ok": compress_ok,
        },
        index=df4.index,
    )

    # 避免前视：4H 指标整体后移 1 根 4H bar，再向前填充到 15m
    df4_ind = df4_ind.shift(1)

    # ✅ 修复：ADX“上升”必须按 4H bar 比较（不能在 15m ffill 序列上用 i-2 比较）
    df4_ind["adx_rise"] = (df4_ind["adx"] > df4_ind["adx"].shift(1)).astype(float)

    df4_ind_15 = df4_ind.reindex(idx, method="ffill")


    # 4H 宏观趋势门控（MA200 + 斜率）：用于 BTC 等“共识资产”的噪声过滤
    ma200_4h = df4["close"].rolling(200).mean()
    slope_4h = ma200_4h - ma200_4h.shift(20)
    macro_long_ok = ((df4["close"] > ma200_4h) & (slope_4h > 0)).astype(float)
    macro_short_ok = ((df4["close"] < ma200_4h) & (slope_4h < 0)).astype(float)
    df4_macro = pd.DataFrame(
        {"macro_long_ok": macro_long_ok, "macro_short_ok": macro_short_ok},
        index=df4.index,
    ).shift(1)
    df4_macro_15 = df4_macro.reindex(idx, method="ffill")

    # 1D 宏观趋势门控（更慢、更稳）：用于避免 BTC 在牛市短暂回撤时误触发做空
    df1d = _resample_1d(df15)
    ma200_1d = df1d["close"].rolling(200).mean()
    slope_1d = ma200_1d - ma200_1d.shift(20)
    macro_long_ok_1d = ((df1d["close"] > ma200_1d) & (slope_1d > 0)).astype(float)
    macro_short_ok_1d = ((df1d["close"] < ma200_1d) & (slope_1d < 0)).astype(float)
    df1d_macro = pd.DataFrame(
        {"macro_long_ok": macro_long_ok_1d, "macro_short_ok": macro_short_ok_1d},
        index=df1d.index,
    ).shift(1)
    df1d_macro_15 = df1d_macro.reindex(idx, method="ffill")

    return {
        "atr15": atr15_s,
        "donch_high": donch_high,
        "donch_low": donch_low,
        "sr_high4": sr_high4_15,
        "sr_low4": sr_low4_15,
        "adx4": df4_ind_15["adx"],
        "di_plus4": df4_ind_15["di_plus"],
        "di_minus4": df4_ind_15["di_minus"],
        "adx_rise4": df4_ind_15["adx_rise"].fillna(0.0),
        "expand_ok4": df4_ind_15["expand_ok"].fillna(0.0),
        "compress_ok4": df4_ind_15["compress_ok"].fillna(0.0),
        "macro_long_ok4": df4_macro_15["macro_long_ok"].fillna(0.0),
        "macro_short_ok4": df4_macro_15["macro_short_ok"].fillna(0.0),
        "macro_long_ok1d": df1d_macro_15["macro_long_ok"].fillna(0.0),
        "macro_short_ok1d": df1d_macro_15["macro_short_ok"].fillna(0.0),
        "bb_mid": bb_mid,
        "bb_upper": bb_upper,
        "bb_lower": bb_lower,
    }


def _breakeven_price(avg_entry: float, side: int, fee_rate: float, slip_rate: float) -> float:
    # 近似：进出各一次成本
    cost = 2.0 * (fee_rate + slip_rate)
    if side > 0:
        return avg_entry * (1.0 + cost)
    else:
        return avg_entry * (1.0 - cost)


def run_backtest_portfolio(
    data: dict[str, pd.DataFrame],
    cfg: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """多资产组合回测（同一时间轴，组合权益）。"""
    symbols = list(data.keys())
    n = len(symbols)

    weights_cfg = cfg["data"].get("weights", "equal")
    if isinstance(weights_cfg, dict):
        weights = {s: float(weights_cfg.get(s, 0.0)) for s in symbols}
        wsum = sum(weights.values())
        weights = dict.fromkeys(symbols, 1.0 / n) if wsum <= 0 else {s: w / wsum for s, w in weights.items()}
    else:
        weights = dict.fromkeys(symbols, 1.0 / n)

    # 取共同区间（避免 NaN）
    common = None
    for s in symbols:
        idx = data[s].index
        common = idx if common is None else common.intersection(idx)
    common = common.sort_values()
    for s in symbols:
        data[s] = data[s].reindex(common).dropna(subset=["open", "high", "low", "close"])

    common = None
    for s in symbols:
        idx = data[s].index
        common = idx if common is None else common.intersection(idx)
    common = common.sort_values()
    for s in symbols:
        data[s] = data[s].reindex(common).dropna(subset=["open", "high", "low", "close"])

    if len(common) < 10:
        raise ValueError("共同区间数据不足（请检查 CSV 时间范围是否一致）。")

    costs = cfg["costs"]
    fee_rate = float(costs.get("fee_bps", 2)) / 10000.0
    slip_rate = float(costs.get("slippage_bps", 2)) / 10000.0

    funding_cfg = cfg.get("funding", {}) or {}
    funding_enabled = _to_bool(funding_cfg.get("enabled", False))
    funding_charge_mode = str(funding_cfg.get("charge_mode", "adverse_only")).strip().lower()

    port = cfg["portfolio"]
    risk_cfg = cfg["risk"]
    sp = cfg["strategy_params"]
    flt = cfg["filters"]

    mr_cfg = cfg.get("mean_reversion", {}) or {}
    mr_enabled = bool(mr_cfg.get("enabled", False))
    mr_bb_window = int(mr_cfg.get("bb_window", 20))
    mr_bb_std = float(mr_cfg.get("bb_std", 2.0))
    mr_adx_ceiling = float(mr_cfg.get("adx_ceiling", 20))
    mr_max_hold_bars = int(mr_cfg.get("max_hold_bars", 2))
    mr_risk_frac_of_trend = float(mr_cfg.get("risk_fraction_of_trend", 1.0 / 3.0))
    mr_leverage_cap = float(mr_cfg.get("leverage_cap", 3.0))
    mr_atr_stop_mult = float(mr_cfg.get("atr_stop_mult", 2.0))
    mr_exit_on_mid = bool(mr_cfg.get("exit_on_mid", True))
    mr_cooldown_bars = int(mr_cfg.get("cooldown_bars", 0))
    sr_cfg = cfg.get("sr_entries", {}) or {}
    sr_enabled = _to_bool(sr_cfg.get("enabled", False))
    sr_symbols = sr_cfg.get("symbols", symbols)
    if not isinstance(sr_symbols, (list, tuple)):
        sr_symbols = list(symbols)
    sr_symbols = [str(x).strip().lower() for x in sr_symbols if str(x).strip()]
    sr_zone_atr = float(sr_cfg.get("zone_atr_mult", 0.6))
    sr_take_profit_pct = float(sr_cfg.get("take_profit_pct", 0.0))
    sr_require_di = _to_bool(sr_cfg.get("require_di", False))
    sr_require_compress_ok = _to_bool(sr_cfg.get("require_compress_ok", False))
    sr_use_adx_filter = _to_bool(sr_cfg.get("use_adx_filter", False))
    sr_adx_min = float(sr_cfg.get("adx_min", 0.0))
    sr_adx_max = float(sr_cfg.get("adx_max", 1e9))
    sr_lookback_4h = int(sr_cfg.get("lookback_4h", 30))
    sr_lookback_4h = max(5, sr_lookback_4h)
    sr_stake_scale = float(sr_cfg.get("stake_scale", 1.0))
    sr_cooldown_bars = int(sr_cfg.get("cooldown_bars", int(cfg.get("strategy_params", {}).get("cooldown_bars", 6))))
    sr_cooldown_bars = max(0, sr_cooldown_bars)



    initial_equity = float(port["initial_equity"])
    leverage = float(port.get("leverage", 1.0))
    exposure_fraction = float(port.get("exposure_fraction", 1.0))

    # === 动态杠杆（可选）：以 4H ADX 作为信号强度 proxy，在 20-25x 之间映射（只在开仓时确定） ===
    dyn_lev_cfg = port.get("dynamic_leverage", {}) or {}
    dyn_lev_enabled = bool(dyn_lev_cfg.get("enabled", False))
    dyn_lev_min = float(dyn_lev_cfg.get("min", leverage))
    dyn_lev_max = float(dyn_lev_cfg.get("max", leverage))
    dyn_lev_adx_low = float(dyn_lev_cfg.get("adx_low", 20.0))
    dyn_lev_adx_high = float(dyn_lev_cfg.get("adx_high", 40.0))
    # 安全钳制：不允许超过全局 leverage cap
    dyn_lev_min = max(0.0, min(dyn_lev_min, leverage))
    dyn_lev_max = max(0.0, min(dyn_lev_max, leverage))
    if dyn_lev_max < dyn_lev_min:
        dyn_lev_min, dyn_lev_max = dyn_lev_max, dyn_lev_min

    def _entry_leverage(adx_val: float) -> float:
        if (not dyn_lev_enabled) or np.isnan(adx_val):
            return leverage
        if dyn_lev_adx_high <= dyn_lev_adx_low:
            return dyn_lev_max
        x = (adx_val - dyn_lev_adx_low) / (dyn_lev_adx_high - dyn_lev_adx_low)
        x = float(np.clip(x, 0.0, 1.0))
        return dyn_lev_min + (dyn_lev_max - dyn_lev_min) * x

    # === 资金管理：固定金额分仓（10份） + 强制止损（20-30%） + 盈利回撤止盈（提高胜率） ===
    mm_cfg = cfg.get("money_management", {}) or {}
    mm_mode = str(mm_cfg.get("mode", "risk")).lower()
    mm_fixed = mm_mode in ("fixed_tranche", "fixed", "tranche")
    capital_slices = int(mm_cfg.get("capital_slices", 10))
    stake_usd = float(mm_cfg.get("stake_usd", initial_equity / max(1, capital_slices)))
    stake_mode = str(mm_cfg.get("stake_mode", "fixed")).strip().lower()
    stake_min_usd = float(mm_cfg.get("stake_min_usd", 0.0))
    stake_max_usd = float(mm_cfg.get("stake_max_usd", 0.0))
    stake_scale_cfg = mm_cfg.get("stake_scale", {}) or {}
    risk_on_cfg = mm_cfg.get("risk_on", {}) or {}
    risk_on_enabled = _to_bool(risk_on_cfg.get("enabled", False), default=False)
    risk_on_mult = float(risk_on_cfg.get("mult", 1.0))
    risk_on_adx_min = float(risk_on_cfg.get("adx_min", 35.0))
    risk_on_mult_hi = float(risk_on_cfg.get("mult_hi", risk_on_mult))
    risk_on_adx_hi = float(risk_on_cfg.get("adx_hi", 999.0))
    risk_on_dd_hi_disable = float(risk_on_cfg.get("dd_hi_disable", 0.18))
    risk_on_pyramiding_hi_only = _to_bool(risk_on_cfg.get("pyramiding_hi_only", False), default=False)
    risk_on_require_expand = _to_bool(risk_on_cfg.get("require_expand_ok", True), default=True)
    risk_on_require_adx_rise = _to_bool(risk_on_cfg.get("require_adx_rise", True), default=True)
    risk_on_symbols_cfg = risk_on_cfg.get("symbols", None)
    if risk_on_symbols_cfg is None:
        risk_on_symbols = set()
    elif isinstance(risk_on_symbols_cfg, str):
        risk_on_symbols = {s.strip().lower() for s in risk_on_symbols_cfg.split(",") if s.strip()}
    else:
        risk_on_symbols = {str(x).lower() for x in risk_on_symbols_cfg}
    risk_on_sides_cfg = risk_on_cfg.get("sides", ["LONG", "SHORT"])
    if isinstance(risk_on_sides_cfg, str):
        risk_on_sides = {s.strip().upper() for s in risk_on_sides_cfg.split(",") if s.strip()}
    else:
        risk_on_sides = {str(x).upper() for x in risk_on_sides_cfg}
    stop_loss_pct = float(mm_cfg.get("stop_loss_pct", 0.25))  # 亏损占保证金的比例
    take_profit_pct = float(mm_cfg.get("take_profit_pct", 0.0))  # 盈利目标（保证金口径）；0=关闭
    tp_enabled = take_profit_pct > 0.0
    trail_cfg = mm_cfg.get("trailing_profit", {}) or {}
    trail_enabled = bool(trail_cfg.get("enabled", True))
    trail_activation = float(trail_cfg.get("activation_pnl_pct", 0.06))
    trail_giveback = float(trail_cfg.get("giveback_ratio", 0.30))
    trail_min_lock = float(trail_cfg.get("min_lock_pnl_pct", 0.02))
    slices_free = capital_slices if mm_fixed else 10**9

    def _stake_base(eq_val: float) -> float:
        """Return base margin (USD) per tranche.
        stake_mode:
          - fixed: use stake_usd from config
          - dynamic_equity/equity: eq_prev / capital_slices (with optional min/max caps)
        """
        if not mm_fixed:
            return stake_usd
        if stake_mode in ("dynamic_equity", "equity", "equity_slices", "dynamic", "auto"):
            base = float(eq_val) / max(1, capital_slices)
            if stake_min_usd > 0:
                base = max(stake_min_usd, base)
            if stake_max_usd > 0:
                base = min(stake_max_usd, base)
            return base
        return stake_usd

    def _price_from_pnl_pct(entry_px: float, side: int, lev: float, pnl_pct: float) -> float:
        # pnl_pct 以“保证金收益率”为口径（例如 -0.25 = 亏损 25%）
        if side == 0 or lev <= 0:
            return entry_px
        return entry_px * (1.0 + pnl_pct / (side * lev))

    risk_per_trade_total = float(risk_cfg.get("risk_per_trade", 0.01))
    max_dd_halt = float(risk_cfg.get("max_drawdown_halt", 0.99))

    dd_scale_cfg = risk_cfg.get("dd_risk_scaling", {}) or {}
    dd_scale_enabled = bool(dd_scale_cfg.get("enabled", False))
    dd_start = float(dd_scale_cfg.get("start", 0.18))
    dd_end = float(dd_scale_cfg.get("end", 0.28))
    dd_min_scale = float(dd_scale_cfg.get("min_scale", 0.1))

    # 关键修复：当 max_drawdown_halt 调得更小（例如 0.25）时，若仍保持 dd_end=0.28，
    # 风险缩放永远达不到最小值就先触发 HALT，导致“早停机、后面全程 0 交易”。
    # 强制保证 dd_end < max_dd_halt（留出 1% 缓冲），确保缩放在触发 HALT 前生效。
    if dd_scale_enabled:
        if dd_end >= max_dd_halt:
            dd_end = max(0.0, max_dd_halt - 0.01)
        if dd_start >= dd_end:
            dd_start = max(0.0, dd_end - 0.10)

    breakout_lookback = int(sp["breakout_lookback"])
    breakout_atr_buffer = float(sp.get("breakout_atr_buffer", 0.0))
    atr_period = int(sp.get("atr_period", 56))
    atr_stop_mult = float(sp.get("atr_stop_mult", 6.0))
    atr_trail_mult = float(sp.get("atr_trail_mult", 6.0))
    cooldown_bars = int(sp.get("cooldown_bars", 6))
    loss_cooldown_default = int(sp.get("loss_cooldown_default", cooldown_bars))
    loss_cooldown_by_symbol_cfg = sp.get("loss_cooldown_by_symbol", {}) or {}
    loss_cooldown_by_symbol: dict[str, int] = {}
    if isinstance(loss_cooldown_by_symbol_cfg, dict):
        for k, v in loss_cooldown_by_symbol_cfg.items():
            with contextlib.suppress(Exception):
                loss_cooldown_by_symbol[str(k).strip().lower()] = int(v)
    loss_cluster_window_default = int(sp.get("loss_cluster_window_bars", 0))
    loss_cluster_threshold_default = int(sp.get("loss_cluster_threshold_default", 0))
    loss_cluster_cooldown_default = int(sp.get("loss_cluster_cooldown_default", 0))
    loss_cluster_threshold_by_symbol_cfg = sp.get("loss_cluster_threshold_by_symbol", {}) or {}
    loss_cluster_threshold_by_symbol: dict[str, int] = {}
    if isinstance(loss_cluster_threshold_by_symbol_cfg, dict):
        for k, v in loss_cluster_threshold_by_symbol_cfg.items():
            with contextlib.suppress(Exception):
                loss_cluster_threshold_by_symbol[str(k).strip().lower()] = int(v)
    loss_cluster_cooldown_by_symbol_cfg = sp.get("loss_cluster_cooldown_by_symbol", {}) or {}
    loss_cluster_cooldown_by_symbol: dict[str, int] = {}
    if isinstance(loss_cluster_cooldown_by_symbol_cfg, dict):
        for k, v in loss_cluster_cooldown_by_symbol_cfg.items():
            with contextlib.suppress(Exception):
                loss_cluster_cooldown_by_symbol[str(k).strip().lower()] = int(v)

    allow_short = _to_bool(sp.get("allow_short", True), default=True)
    # LONG 允许范围：默认全资产允许；可在 config.yml 的 strategy_params.long_symbols 指定（例如仅 bnb）
    long_symbols_cfg = sp.get("long_symbols", None)
    if long_symbols_cfg is None:
        long_symbols = set(symbols)
    else:
        if isinstance(long_symbols_cfg, str):
            parts = [p.strip().lower() for p in long_symbols_cfg.replace(",", " ").split() if p.strip()]
            long_symbols = set(parts)
        else:
            long_symbols = {str(x).lower() for x in long_symbols_cfg}
        long_symbols = {s for s in long_symbols if s in symbols}

    # SHORT 允许范围：默认全资产允许；可在 config.yml 的 strategy_params.short_symbols 指定（例如仅 bnb）
    short_symbols_cfg = sp.get("short_symbols", None)
    if short_symbols_cfg is None:
        short_symbols = set(symbols)
    else:
        if isinstance(short_symbols_cfg, str):
            parts = [p.strip().lower() for p in short_symbols_cfg.replace(",", " ").split() if p.strip()]
            short_symbols = set(parts)
        else:
            short_symbols = {str(x).lower() for x in short_symbols_cfg}
        short_symbols = {s for s in short_symbols if s in symbols}

    pyramiding_max_adds = int(sp.get("pyramiding_max_adds", 1))
    add_step_atr = float(sp.get("add_step_atr", 3.0))
    add_risk_fraction = float(sp.get("add_risk_fraction", 0.35))
    breakeven_atr = float(sp.get("breakeven_atr", 2.5))
    pyramiding_symbols_cfg = sp.get("pyramiding_symbols", None)
    if pyramiding_symbols_cfg is None:
        pyramiding_symbols = set(symbols)
    elif isinstance(pyramiding_symbols_cfg, str):
        pyramiding_symbols = {s.strip().lower() for s in pyramiding_symbols_cfg.split(",") if s.strip()}
    else:
        pyramiding_symbols = {str(x).lower() for x in pyramiding_symbols_cfg}

    adx_period = int(flt.get("adx_period", 14))
    adx_floor = float(flt.get("adx_floor", 15))
    btc_adx_floor = float(flt.get("btc_adx_floor", adx_floor))
    btc_breakout_atr_buffer = float(flt.get("btc_breakout_atr_buffer", breakout_atr_buffer))
    btc_short_entry_mode = str(flt.get("btc_short_entry_mode", "breakout")).strip().lower()
    btc_short_pullback_atr = float(flt.get("btc_short_pullback_atr", 0.5))
    btc_short_sr_lookback_4h = int(flt.get("btc_short_sr_lookback_4h", 30))
    btc_short_sr_lookback_4h = max(5, btc_short_sr_lookback_4h)
    sr_lookback_used_4h = btc_short_sr_lookback_4h
    if sr_enabled:
        sr_lookback_used_4h = sr_lookback_4h


    btc_short_adx_floor = float(flt.get("btc_short_adx_floor", btc_adx_floor))
    btc_short_require_di = bool(flt.get("btc_short_require_di", True))
    btc_short_macro_tf = str(flt.get("btc_short_macro_tf", "4h")).strip().lower()
    btc_short_macro_tf = "1d" if btc_short_macro_tf in ("1d", "d", "1day", "day") else "4h"

    use_rise_and_di = bool(flt.get("use_rise_and_di", True))

    # 天地针/异常长影线执行防护：仅阻止新开仓，不影响持仓保护单
    exg = cfg.get("execution_guard", {}) or {}
    wick_guard_enabled = _to_bool(exg.get("enabled", False), False)
    wick_pause_bars = max(0, int(exg.get("pause_bars", 8)))
    wick_range_atr = float(exg.get("range_atr", 3.0))
    wick_frac_min = float(exg.get("wick_frac_min", 0.60))
    wick_body_atr_max = float(exg.get("body_atr_max", 0.80))
    wick_symbols = exg.get("symbols", symbols)
    if isinstance(wick_symbols, str):
        s = wick_symbols.strip().lower()
        wick_symbols = symbols if s in ("all", "*") else [s]
    wick_symbols = [str(x).strip().lower() for x in wick_symbols if str(x).strip()]

    # 宏观趋势门控作用范围（默认仅 BTC；可在 config.yml 的 filters.macro_gate_symbols 扩展）
    macro_gate_symbols = flt.get("macro_gate_symbols", ["btc"])
    if isinstance(macro_gate_symbols, str):
        s = macro_gate_symbols.strip().lower()
        if s in ("all", "*"):
            macro_gate_symbols = symbols
        elif s:
            macro_gate_symbols = [macro_gate_symbols]
        else:
            macro_gate_symbols = ["btc"]
    if not isinstance(macro_gate_symbols, (list, tuple)):
        macro_gate_symbols = ["btc"]
    macro_gate_symbols = [str(x).strip().lower() for x in macro_gate_symbols if str(x).strip()]
    if not macro_gate_symbols:
        macro_gate_symbols = ["btc"]
    # 宏观趋势门控参考标的（可选）：用于让其他资产（如 BNB）参考 BTC 的宏观趋势门控
    macro_gate_ref_symbol = flt.get("macro_gate_reference_symbol", None)
    macro_gate_ref_symbol = str(macro_gate_ref_symbol).strip().lower() if macro_gate_ref_symbol is not None else ""
    if macro_gate_ref_symbol and macro_gate_ref_symbol in symbols:
        pass
    else:
        macro_gate_ref_symbol = ""

    # 宏观门控时间框架（可选）：允许按标的指定使用 4h/1d 的宏观门控（默认 4h）。
    macro_gate_tf_by_symbol = flt.get("macro_gate_tf_by_symbol", {}) or {}
    if not isinstance(macro_gate_tf_by_symbol, dict):
        macro_gate_tf_by_symbol = {}
    _tf_norm = {}
    for k, v in macro_gate_tf_by_symbol.items():
        ks = str(k).strip().lower()
        vs = str(v).strip().lower()
        vs = "1d" if vs in ("1d", "d", "1day", "day") else "4h"
        if ks:
            _tf_norm[ks] = vs
    macro_gate_tf_by_symbol = _tf_norm



    expand = flt.get("expand_filter", {}) or {}
    expand_enabled = bool(expand.get("enabled", True))
    expand_pctl = float(expand.get("expand_pctl", 0.25))
    compress_pctl = float(expand.get("compress_pctl", 0.25))
    expand_window_4h = int(expand.get("window_4h", 540))
    atr_period_4h = int(expand.get("atr_period_4h", 14))

    # 预计算指标
    ind: dict[str, dict[str, Any]] = {}
    for s in symbols:
        ind[s] = prepare_indicators(
            data[s],
            breakout_lookback=breakout_lookback,
            breakout_atr_buffer=breakout_atr_buffer,
            atr_period=atr_period,
            adx_period=adx_period,
            expand_enabled=expand_enabled,
            expand_pctl=expand_pctl,
            compress_pctl=compress_pctl,
            expand_window_4h=expand_window_4h,
            atr_period_4h=atr_period_4h,
            bb_window=mr_bb_window,
            bb_std=mr_bb_std,
            sr_lookback_4h=sr_lookback_used_4h,
        )

    # 同步指标到 common
    for s in symbols:
        for k in list(ind[s].keys()):
            ind[s][k] = ind[s][k].reindex(common)

    # 预计算 funding 序列
    funding_rates: dict[str, pd.Series] = {}
    for s in symbols:
        funding_rates[s] = _load_funding_series(s, common, funding_cfg) if funding_enabled else pd.Series(0.0, index=common)

    # 预计算“天地针/异常长影线”开仓阻断序列：任一异常 bar 触发后，后续若干 bar 禁止新开仓
    wick_block: dict[str, pd.Series] = {}
    for s in symbols:
        if (not wick_guard_enabled) or (s not in wick_symbols) or (wick_pause_bars <= 0):
            wick_block[s] = pd.Series(0.0, index=common)
            continue
        o_s = data[s]["open"]
        h_s = data[s]["high"]
        l_s = data[s]["low"]
        c_s = data[s]["close"]
        atr_s = ind[s]["atr15"]
        rng_s = (h_s - l_s).clip(lower=0.0)
        body_s = (c_s - o_s).abs()
        upper_wick_s = (h_s - pd.concat([o_s, c_s], axis=1).max(axis=1)).clip(lower=0.0)
        lower_wick_s = (pd.concat([o_s, c_s], axis=1).min(axis=1) - l_s).clip(lower=0.0)
        wick_frac_s = pd.concat([upper_wick_s, lower_wick_s], axis=1).max(axis=1) / rng_s.replace(0.0, np.nan)
        range_atr_s = rng_s / atr_s.replace(0.0, np.nan)
        body_atr_s = body_s / atr_s.replace(0.0, np.nan)
        abnormal_s = ((range_atr_s >= wick_range_atr) & (wick_frac_s >= wick_frac_min) & (body_atr_s <= wick_body_atr_max)).astype(float)
        block_s = abnormal_s.shift(1).rolling(wick_pause_bars, min_periods=1).max().fillna(0.0)
        wick_block[s] = block_s.reindex(common).fillna(0.0)

    external_pause_block, external_pause_meta = _load_external_entry_pause(common=common, symbols=symbols, cfg=cfg)
    entry_pause_block: dict[str, pd.Series] = {}
    for s in symbols:
        entry_pause_block[s] = pd.concat([wick_block[s], external_pause_block.get(s, pd.Series(0.0, index=common))], axis=1).max(axis=1).fillna(0.0)

    # 账户状态
    cash = initial_equity
    positions: dict[str, dict[str, Any]] = {}
    for s in symbols:
        positions[s] = {
            "mode": "NONE",  # NONE / TREND / MR
            "side": 0,  # 1 long, -1 short
            "qty": 0.0,
            "avg_entry": 0.0,
            "entry_time": None,
            "entry_price": 0.0,
            "stop": np.nan,
            "tp": np.nan,
            "trail": np.nan,
            "breakeven": np.nan,
            "adds": 0,
            "cooldown": 0,
            "entry_i": None,
            "fees_paid": 0.0,
            "funding_paid": 0.0,
            "stake": 0.0,
            "lev": leverage,
            "peak_pnl_pct": 0.0,
        }

    trades: list[Trade] = []
    funding_net_total = 0.0
    funding_net_by_symbol: dict[str, float] = dict.fromkeys(symbols, 0.0)
    funding_events_by_symbol: dict[str, int] = dict.fromkeys(symbols, 0)
    recent_loss_stop_exit_i: dict[str, list[int]] = {sym: [] for sym in symbols}
    equity_curve = []
    peak_equity = initial_equity
    # DD Guard：用“软退出 + 冷却 + 低风险恢复”替代永久停机（避免后续全 0 交易）
    dd_guard_cfg = risk_cfg.get("dd_guard", {}) or {}
    dd_guard_enabled = bool(dd_guard_cfg.get("enabled", True))
    dd_guard_buffer = float(dd_guard_cfg.get("buffer", 0.002))
    dd_guard_cooldown_bars = int(dd_guard_cfg.get("cooldown_bars", 1920))  # 15m 下约 20 天
    dd_recovery_scale = float(dd_guard_cfg.get("recovery_scale", 0.05))  # 恢复期风险上限（相对正常风险）
    dd_recovery_exit_pct = float(dd_guard_cfg.get("recovery_exit_pct", 0.05))  # 从低点回升阈值（5%）
    dd_recovery_exit_dd = float(dd_guard_cfg.get("recovery_exit_dd", max(0.0, max_dd_halt - 0.05)))  # drawdown 回到 <20% 左右
    dd_hard_kill = float(dd_guard_cfg.get("hard_kill", max_dd_halt + 0.10))  # 极端保护（仍可永久停机）

    dd_guard_cooldown = 0
    dd_recovery_mode = False
    dd_guard_low_equity: float | None = None
    dd_guard_last_trigger_dd: float | None = None  # 上次触发时的回撤幅度（dd_abs）
    # 防止“drawdown 常驻阈值上方”导致循环冷却：只有 dd 进一步恶化到一定步长才允许重触发
    dd_guard_step_dd = max(0.001, dd_guard_buffer / 10.0)  # 默认 0.1% DD 步进
    dd_guard_triggers = 0

    # 触发阈值略早于 max_dd_halt，避免离散 bar 导致轻微超线
    dd_trigger = max(0.0, max_dd_halt - (dd_guard_buffer if dd_guard_enabled else 0.0))

    def current_unrealized(i: int) -> float:
        u = 0.0
        for sym in symbols:
            pos = positions[sym]
            if pos["side"] == 0:
                continue
            price = float(data[sym]["close"].iloc[i])
            u += pos["side"] * pos["qty"] * (price - pos["avg_entry"])
        return u

    def _close_position(sym: str, i: int, exit_px: float, reason: str) -> None:
        nonlocal cash
        nonlocal slices_free
        pos = positions[sym]
        tag = str(pos.get("tag", "")).upper()
        if tag == "SR" and (reason.startswith("TREND_") or reason.startswith("MR_")):
            reason = "SR_" + reason.split("_", 1)[1]
        notional = abs(pos["qty"]) * exit_px
        fee = notional * fee_rate
        pnl_raw = pos["side"] * pos["qty"] * (exit_px - pos["avg_entry"])
        cash += pnl_raw
        cash -= fee
        total_fees = pos["fees_paid"] + fee
        total_funding = float(pos.get("funding_paid", 0.0))
        net_pnl = pnl_raw - total_fees - total_funding
        trades.append(
            Trade(
                symbol=sym,
                side="LONG" if pos["side"] > 0 else "SHORT",
                entry_time=pos["entry_time"],
                exit_time=common[i],
                entry_price=pos["avg_entry"],
                exit_price=exit_px,
                qty=pos["qty"],
                pnl=net_pnl,
                pnl_pct=net_pnl / max(1e-9, float(pos.get('stake', initial_equity))),
                fees=total_fees,
                funding=total_funding,
                reason=reason,
                bars_held=int(i - pos["entry_i"]),
            )
        )
        # 释放资金份额（固定分仓模式）
        if mm_fixed and float(pos.get('stake', 0.0)) > 0:
            slices_free = min(capital_slices, slices_free + 1)
        # cooldown（SR 单独冷却；否则按 mode 选择 TREND/MR 冷却）
        if tag == "SR":
            cd_bars = sr_cooldown_bars
        else:
            if pos.get("mode") == "TREND":
                pnl_net = net_pnl
                if pnl_net < 0:
                    cd_bars = loss_cooldown_by_symbol.get(sym, loss_cooldown_default)
                    if "STOP" in str(reason).upper():
                        win_bars = max(0, int(loss_cluster_window_default))
                        if win_bars > 0:
                            recent = [j for j in recent_loss_stop_exit_i.get(sym, []) if (i - j) <= win_bars]
                            recent.append(i)
                            recent_loss_stop_exit_i[sym] = recent
                            threshold = int(loss_cluster_threshold_by_symbol.get(sym, loss_cluster_threshold_default))
                            cluster_cd = int(loss_cluster_cooldown_by_symbol.get(sym, loss_cluster_cooldown_default))
                            if threshold > 0 and cluster_cd > 0 and len(recent) >= threshold:
                                cd_bars = max(cd_bars, cluster_cd)
                else:
                    recent_loss_stop_exit_i[sym] = []
                    cd_bars = cooldown_bars
            else:
                cd_bars = mr_cooldown_bars
        # 清空
        positions[sym] = {
            "mode": "NONE",
            "side": 0,
            "qty": 0.0,
            "avg_entry": 0.0,
            "entry_time": None,
            "entry_price": 0.0,
            "stop": np.nan,
            "trail": np.nan,
            "breakeven": np.nan,
            "adds": 0,
            "cooldown": cd_bars,
            "entry_i": None,
            "fees_paid": 0.0,
            "funding_paid": 0.0,
            "stake": 0.0,
            "lev": leverage,
            "peak_pnl_pct": 0.0,
        }

    for i in range(1, len(common)):
        t = common[i]

        # 1) cooldown 递减
        for sym in symbols:
            if positions[sym]["cooldown"] > 0:
                positions[sym]["cooldown"] -= 1

        # DD Guard 全局冷却递减
        if dd_guard_cooldown > 0:
            dd_guard_cooldown -= 1

        # 1.5) funding 结算：只对上一 bar 已持有到当前 funding 时点的仓位生效
        if funding_enabled:
            for sym in symbols:
                pos = positions[sym]
                if pos["side"] == 0:
                    continue
                rate = float(funding_rates[sym].iloc[i]) if not np.isnan(funding_rates[sym].iloc[i]) else 0.0
                if rate == 0.0:
                    continue
                ref_px = float(data[sym]["open"].iloc[i])
                notional = abs(pos["qty"]) * ref_px
                if notional <= 0:
                    continue
                if funding_charge_mode in ("signed", "net", "historical"):
                    funding_cost = pos["side"] * notional * rate
                else:
                    funding_cost = abs(notional * rate)
                cash -= funding_cost
                pos["funding_paid"] = float(pos.get("funding_paid", 0.0)) + funding_cost
                funding_net_total += funding_cost
                funding_net_by_symbol[sym] += funding_cost
                funding_events_by_symbol[sym] += 1

        # 2) 止损/追踪止损（用本 bar 的 high/low）
        for sym in symbols:
            pos = positions[sym]
            if pos["side"] == 0:
                continue

            high = float(data[sym]["high"].iloc[i])
            low = float(data[sym]["low"].iloc[i])

            if pos["mode"] == "MR":
                eff_stop = pos["stop"]
            else:
                eff_stop = pos["stop"]
                if not np.isnan(pos["trail"]):
                    eff_stop = max(eff_stop, pos["trail"]) if pos["side"] > 0 else min(eff_stop, pos["trail"])
                if not np.isnan(pos["breakeven"]):
                    eff_stop = max(eff_stop, pos["breakeven"]) if pos["side"] > 0 else min(eff_stop, pos["breakeven"])
            hit_stop = False
            if pos["side"] > 0 and low <= eff_stop:
                hit_stop = True
            if pos["side"] < 0 and high >= eff_stop:
                hit_stop = True

            hit_tp = False
            eff_tp = float(pos.get("tp", np.nan))
            if tp_enabled and pos["mode"] == "TREND" and not np.isnan(eff_tp):
                if pos["side"] > 0 and high >= eff_tp:
                    hit_tp = True
                if pos["side"] < 0 and low <= eff_tp:
                    hit_tp = True

            # 同一根 K 线同时触发止损和止盈：按更差（先止损）处理，避免高估
            if hit_stop:
                # 跳空：按更差价格成交（以 open 与 stop 取更差）
                if pos["side"] > 0:
                    exit_px = min(float(data[sym]["open"].iloc[i]), eff_stop) * (1.0 - slip_rate)
                else:
                    exit_px = max(float(data[sym]["open"].iloc[i]), eff_stop) * (1.0 + slip_rate)
                _close_position(sym, i, exit_px, "MR_STOP" if pos["mode"] == "MR" else "TREND_STOP")

            elif hit_tp:
                # 止盈：跳空按更差（以 open 与 tp 取更差；对盈利单更保守）
                if pos["side"] > 0:
                    exit_px = max(float(data[sym]["open"].iloc[i]), eff_tp) * (1.0 - slip_rate)
                else:
                    exit_px = min(float(data[sym]["open"].iloc[i]), eff_tp) * (1.0 + slip_rate)
                _close_position(sym, i, exit_px, "TREND_TP")


        # 3) bar open：先处理 MR 主动出场（时间/回归中轨），再处理加仓/开仓
        eq_prev = cash + current_unrealized(i - 1)
        dd = eq_prev / peak_equity - 1.0
        dd_abs = -dd  # 正数
        # DD Guard：恢复模式退出条件（跟踪 recovery 期间的最低权益）
        if dd_recovery_mode:
            # 记录 recovery 期间的最低权益，恢复判断以“低点回升”口径更准确
            if dd_guard_low_equity is not None:
                dd_guard_low_equity = min(dd_guard_low_equity, eq_prev)

            # 退出条件：
            # - 从低点回升 >= X%，且回撤已回到触发线之上（避免退出后立刻再次触发）
            # - 或回撤回到更安全区间（dd_abs <= recovery_exit_dd）
            hit_recover_pct = (
                (dd_guard_low_equity is not None)
                and (eq_prev >= dd_guard_low_equity * (1.0 + dd_recovery_exit_pct))
                and (dd_abs <= dd_trigger)
            )
            hit_recover_dd = dd_abs <= dd_recovery_exit_dd

            if hit_recover_pct or hit_recover_dd:
                dd_recovery_mode = False
                dd_guard_low_equity = None
                dd_guard_last_trigger_dd = None

        # 风险缩放
        if dd_scale_enabled:
            if dd_abs <= dd_start:
                dd_scale = 1.0
            elif dd_abs >= dd_end:
                dd_scale = dd_min_scale
            else:
                dd_scale = 1.0 - (dd_abs - dd_start) / (dd_end - dd_start) * (1.0 - dd_min_scale)
        else:
            dd_scale = 1.0

        # DD Guard：恢复模式时进一步压低风险（在 dd_risk_scaling 基础上再做上限）
        if dd_recovery_mode:
            dd_scale = min(dd_scale, dd_recovery_scale)

        for sym in symbols:
            pos = positions[sym]
            w = weights[sym]

            open_px = float(data[sym]["open"].iloc[i])
            close_prev = float(data[sym]["close"].iloc[i - 1])

            # --- MR 出场（open） ---
            if pos["side"] != 0 and pos["mode"] == "MR":
                hold = int(i - pos["entry_i"])
                bb_mid_prev = float(ind[sym]["bb_mid"].iloc[i - 1]) if not np.isnan(ind[sym]["bb_mid"].iloc[i - 1]) else np.nan

                exit_sig = False
                reason = ""
                if hold >= mr_max_hold_bars:
                    exit_sig = True
                    reason = "MR_TIME"
                elif mr_exit_on_mid and not np.isnan(bb_mid_prev):
                    if pos["side"] > 0 and close_prev >= bb_mid_prev:
                        exit_sig = True
                        reason = "MR_MID"
                    if pos["side"] < 0 and close_prev <= bb_mid_prev:
                        exit_sig = True
                        reason = "MR_MID"

                if exit_sig:
                    exit_px = open_px * (1.0 - slip_rate) if pos["side"] > 0 else open_px * (1.0 + slip_rate)
                    _close_position(sym, i, exit_px, reason)
                    # 出场后本 bar 不再开新仓（避免同 bar 翻手）
                    continue

            # 风险与敞口（按权重分配）
            risk_frac = risk_per_trade_total * w * dd_scale
            max_notional_trend = eq_prev * leverage * exposure_fraction * w

            atr_prev = float(ind[sym]["atr15"].iloc[i - 1]) if not np.isnan(ind[sym]["atr15"].iloc[i - 1]) else np.nan
            if np.isnan(atr_prev) or atr_prev <= 0:
                continue

            # --- TREND 加仓 ---
            allowed_adds = pyramiding_max_adds
            if risk_on_pyramiding_hi_only:
                hi_ok = False
                if (risk_on_enabled and (pos["side"] > 0)
                        and ((not risk_on_symbols) or (sym in risk_on_symbols))
                        and ((not risk_on_sides) or ("LONG" in risk_on_sides))):
                    adx_v_p = float(ind[sym]["adx4"].iloc[i - 1]) if not np.isnan(ind[sym]["adx4"].iloc[i - 1]) else np.nan
                    if (not np.isnan(adx_v_p)) and (adx_v_p >= risk_on_adx_hi) and (dd_abs <= risk_on_dd_hi_disable):
                        ok = True
                        if risk_on_require_expand and float(ind[sym]["expand_ok4"].iloc[i - 1]) < 0.5:
                            ok = False
                        if ok and risk_on_require_adx_rise and float(ind[sym]["adx_rise4"].iloc[i - 1]) < 0.5:
                            ok = False
                        if ok:
                            hi_ok = True
                allowed_adds = pyramiding_max_adds if hi_ok else 0
            if (not dd_recovery_mode) and (sym in pyramiding_symbols) and pos["side"] != 0 and pos["mode"] == "TREND" and pos["adds"] < allowed_adds:
                stop_dist = atr_stop_mult * atr_prev
                if stop_dist > 0:
                    if pos["side"] > 0:
                        add_ok = close_prev >= pos["avg_entry"] + add_step_atr * atr_prev
                    else:
                        add_ok = close_prev <= pos["avg_entry"] - add_step_atr * atr_prev

                    if add_ok:
                        add_risk = eq_prev * risk_frac * add_risk_fraction
                        add_qty = add_risk / stop_dist
                        cur_notional = abs(pos["qty"]) * open_px
                        allow_notional = max(0.0, max_notional_trend - cur_notional)
                        max_add_qty = allow_notional / open_px if open_px > 0 else 0.0
                        add_qty = max(0.0, min(add_qty, max_add_qty))
                        if add_qty > 0:
                            add_px = open_px * (1.0 + slip_rate) if pos["side"] > 0 else open_px * (1.0 - slip_rate)
                            fee = abs(add_qty) * add_px * fee_rate
                            cash -= fee
                            pos["fees_paid"] += fee

                            new_qty = pos["qty"] + add_qty
                            pos["avg_entry"] = (pos["avg_entry"] * pos["qty"] + add_px * add_qty) / new_qty
                            pos["qty"] = new_qty
                            pos["adds"] += 1

                            # r035：每次加仓后必须重新锚定含费保本价
                            pos["stop"] = pos["avg_entry"] - pos["side"] * atr_stop_mult * atr_prev
                            pos["trail"] = pos["avg_entry"] - pos["side"] * atr_trail_mult * atr_prev
                            pos["breakeven"] = _breakeven_price(pos["avg_entry"], pos["side"], fee_rate, slip_rate)

            # --- 开仓：TREND 优先 ---
            if pos["side"] == 0 and pos["cooldown"] == 0 and float(entry_pause_block[sym].iloc[i]) < 0.5:
                stop_dist = atr_stop_mult * atr_prev
                if stop_dist <= 0:
                    continue

                donch_h = float(ind[sym]["donch_high"].iloc[i - 1]) if not np.isnan(ind[sym]["donch_high"].iloc[i - 1]) else np.nan
                donch_l = float(ind[sym]["donch_low"].iloc[i - 1]) if not np.isnan(ind[sym]["donch_low"].iloc[i - 1]) else np.nan

                adx_v = float(ind[sym]["adx4"].iloc[i - 1]) if not np.isnan(ind[sym]["adx4"].iloc[i - 1]) else np.nan
                di_p = float(ind[sym]["di_plus4"].iloc[i - 1]) if not np.isnan(ind[sym]["di_plus4"].iloc[i - 1]) else np.nan
                di_m = float(ind[sym]["di_minus4"].iloc[i - 1]) if not np.isnan(ind[sym]["di_minus4"].iloc[i - 1]) else np.nan
                exp_ok = float(ind[sym]["expand_ok4"].iloc[i - 1]) if not np.isnan(ind[sym]["expand_ok4"].iloc[i - 1]) else 0.0

                adx_floor_sym = btc_adx_floor if sym == "btc" else adx_floor
                brk_buf_sym = btc_breakout_atr_buffer if sym == "btc" else breakout_atr_buffer

                # TREND 过滤器
                if (dd_guard_cooldown == 0) and (not np.isnan(adx_v)) and adx_v >= adx_floor_sym and exp_ok >= 0.5:
                    trend_entry_ok = True
                    if use_rise_and_di:
                        rise = float(ind[sym]["adx_rise4"].iloc[i - 1]) if not np.isnan(ind[sym]["adx_rise4"].iloc[i - 1]) else 0.0
                        if rise < 0.5:
                            # ADX 未上升：TREND 不开仓
                            trend_entry_ok = False
                    if trend_entry_ok:
                        long_sig = (sym in long_symbols) and (not np.isnan(donch_h)) and (close_prev > donch_h + brk_buf_sym * atr_prev) and (di_p > di_m)
                        if allow_short and (sym in short_symbols):
                            if sym == "btc" and btc_short_entry_mode == "pullback":
                                # BTC 做空：回拉到阻力位附近入场（避免 breakdown short 反复打脸）
                                sr_series = ind[sym].get("sr_high4", None)
                                sr_h = float(sr_series.iloc[i - 1]) if sr_series is not None else np.nan
                                level = sr_h if not np.isnan(sr_h) else donch_h
                                di_ok = (di_m > di_p) if btc_short_require_di else True
                                short_sig = (not np.isnan(level)) and (close_prev >= level - btc_short_pullback_atr * atr_prev) and (close_prev <= level) and di_ok and (adx_v >= btc_short_adx_floor)
                            else:
                                # 其他资产：沿用 Donchian breakdown 做空
                                short_sig = (not np.isnan(donch_l)) and (close_prev < donch_l - brk_buf_sym * atr_prev) and (di_m > di_p)
                        else:
                            short_sig = False


                                                        # 宏观趋势门控：默认使用“自身”宏观门控；如设置了 filters.macro_gate_reference_symbol，则统一参考该标的（常用：btc）
                            if sym in macro_gate_symbols:
                                src_sym = macro_gate_ref_symbol if macro_gate_ref_symbol else sym

                                tf_long = macro_gate_tf_by_symbol.get(sym, "4h")
                                tf_short = macro_gate_tf_by_symbol.get(sym, "4h")
                                if sym == "btc" and short_sig and btc_short_macro_tf == "1d":
                                    tf_short = "1d"

                                if tf_long == "1d":
                                    mlong = float(ind[src_sym]["macro_long_ok1d"].iloc[i - 1]) if ("macro_long_ok1d" in ind.get(src_sym, {})) else 0.0
                                else:
                                    mlong = float(ind[src_sym]["macro_long_ok4"].iloc[i - 1]) if ("macro_long_ok4" in ind.get(src_sym, {})) else 0.0

                                if tf_short == "1d":
                                    mshort = float(ind[src_sym]["macro_short_ok1d"].iloc[i - 1]) if ("macro_short_ok1d" in ind.get(src_sym, {})) else 0.0
                                else:
                                    mshort = float(ind[src_sym]["macro_short_ok4"].iloc[i - 1]) if ("macro_short_ok4" in ind.get(src_sym, {})) else 0.0

                                if long_sig and mlong < 0.5:
                                    long_sig = False
                                if short_sig and mshort < 0.5:
                                    short_sig = False

                            if long_sig or short_sig:
                                side = 1 if long_sig else -1

                                # 固定），不再按 risk_per_trade 缩放。
                                if mm_fixed:
                                    # 必须有空余份额，且当前权益足以覆盖 1 份保证金
                                    stake_key = f"{sym}_{'short' if side < 0 else 'long'}"
                                    stake_scale = float(stake_scale_cfg.get(stake_key, 1.0)) if isinstance(stake_scale_cfg, dict) else 1.0
                                    stake_base = _stake_base(eq_prev)
                                    stake_used = stake_base * stake_scale * dd_scale
                                    side_tag = "LONG" if side > 0 else "SHORT"
                                    if (risk_on_enabled and (risk_on_mult > 1.0)
                                            and ((not risk_on_symbols) or (sym in risk_on_symbols))
                                            and ((not risk_on_sides) or (side_tag in risk_on_sides))
                                            and adx_v >= risk_on_adx_min):
                                        ok = True
                                        if risk_on_require_expand and float(ind[sym]["expand_ok4"].iloc[i - 1]) < 0.5:
                                            ok = False
                                        if ok and risk_on_require_adx_rise and float(ind[sym]["adx_rise4"].iloc[i - 1]) < 0.5:
                                            ok = False
                                        if ok:
                                            use_hi = (adx_v >= risk_on_adx_hi)
                                            if use_hi and (dd_abs > risk_on_dd_hi_disable):
                                                use_hi = False
                                            stake_used *= (risk_on_mult_hi if use_hi else risk_on_mult)
                                    if slices_free <= 0 or eq_prev < stake_used:
                                        pass
                                    else:
                                        lev_entry = float(_entry_leverage(adx_v))
                                        desired_notional = stake_used * lev_entry * exposure_fraction
                                        allow_notional = max_notional_trend
                                        notional = min(desired_notional, allow_notional)
                                        qty = notional / open_px if open_px > 0 else 0.0
                                        if qty > 0:
                                            entry_px = open_px * (1.0 + slip_rate) if side > 0 else open_px * (1.0 - slip_rate)
                                            fee = qty * entry_px * fee_rate
                                            cash -= fee
                                            # 强制止损：亏损达到 stop_loss_pct（保证金口径）即出场
                                            stop_px = _price_from_pnl_pct(entry_px, side, lev_entry, -stop_loss_pct)
                                            tp_px = _price_from_pnl_pct(entry_px, side, lev_entry, take_profit_pct) if tp_enabled else np.nan
                                            positions[sym] = {
                                                "mode": "TREND",
                                                "side": side,
                                                "qty": qty,
                                                "avg_entry": entry_px,
                                                "entry_time": t,
                                                "entry_price": entry_px,
                                                "stop": stop_px,
                                                "tp": tp_px,
                                                "trail": np.nan,
                                                "breakeven": np.nan,
                                                "adds": 0,
                                                "cooldown": 0,
                                                "entry_i": i,
                                                "fees_paid": fee,
                                                "stake": stake_used,
                                                "lev": lev_entry,
                                                "peak_pnl_pct": 0.0,
                                            }
                                            slices_free -= 1
                                            # 入场 bar 内立即检查 STOP/TP（修复“下一根 bar 才止损”导致超额亏损）
                                            hi = float(data[sym]["high"].iloc[i])
                                            lo = float(data[sym]["low"].iloc[i])
                                            hit_stop0 = (side > 0 and lo <= stop_px) or (side < 0 and hi >= stop_px)
                                            hit_tp0 = False
                                            if tp_enabled and (not np.isnan(tp_px)):
                                                hit_tp0 = (side > 0 and hi >= tp_px) or (side < 0 and lo <= tp_px)

                                            # 同一根 K 线同时触发：按更差（先止损）处理
                                            if hit_stop0:
                                                exit_px0 = (stop_px * (1.0 - slip_rate)) if side > 0 else (stop_px * (1.0 + slip_rate))
                                                _close_position(sym, i, exit_px0, "TREND_STOP")
                                                continue
                                            if hit_tp0:
                                                exit_px0 = (tp_px * (1.0 - slip_rate)) if side > 0 else (tp_px * (1.0 + slip_rate))
                                                _close_position(sym, i, exit_px0, "TREND_TP")
                                                continue
                                            continue  # 本 bar 不再尝试 MR

                                if not mm_fixed:
                                    # 旧模式：按风险预算（ATR 止损距离）计算仓位
                                    risk_dollars = eq_prev * risk_frac
                                    qty = risk_dollars / stop_dist
                                    max_qty = max_notional_trend / open_px if open_px > 0 else 0.0
                                    qty = max(0.0, min(qty, max_qty))
                                    if qty > 0:
                                        entry_px = open_px * (1.0 + slip_rate) if side > 0 else open_px * (1.0 - slip_rate)
                                        fee = qty * entry_px * fee_rate
                                        cash -= fee
                                        positions[sym] = {
                                            "mode": "TREND",
                                            "side": side,
                                            "qty": qty,
                                            "avg_entry": entry_px,
                                            "entry_time": t,
                                            "entry_price": entry_px,
                                            "stop": entry_px - side * atr_stop_mult * atr_prev,
                                            "trail": entry_px - side * atr_trail_mult * atr_prev,
                                            "breakeven": np.nan,
                                            "adds": 0,
                                            "cooldown": 0,
                                            "entry_i": i,
                                            "fees_paid": fee,
                                            "stake": max(1e-9, abs(qty) * entry_px / max(1e-9, leverage)),
                                            "lev": leverage,
                                            "peak_pnl_pct": 0.0,
                                        }
                                        continue  # 本 bar 不再尝试 MR


                # --- SR Pullback 开仓（支撑做多 / 阻力做空，突破后不强制平仓；与 TREND breakout 并行） ---
                if sr_enabled and (sym in sr_symbols) and (dd_guard_cooldown == 0) and (not dd_recovery_mode):
                    sr_h = float(ind[sym]["sr_high4"].iloc[i - 1]) if not np.isnan(ind[sym]["sr_high4"].iloc[i - 1]) else np.nan
                    sr_l = float(ind[sym]["sr_low4"].iloc[i - 1]) if not np.isnan(ind[sym]["sr_low4"].iloc[i - 1]) else np.nan                    # 宏观门控：与 TREND 逻辑一致（支持 reference_symbol；可按标的选择 4h/1d；BTC short 可按 1D 门控）
                    src_sym_sr = macro_gate_ref_symbol if (macro_gate_ref_symbol and sym in macro_gate_symbols) else sym

                    tf_long_sr = macro_gate_tf_by_symbol.get(sym, "4h")
                    tf_short_sr = macro_gate_tf_by_symbol.get(sym, "4h")
                    if sym == "btc" and btc_short_macro_tf == "1d":
                        tf_short_sr = "1d"

                    if tf_long_sr == "1d":
                        mlong_sr = float(ind[src_sym_sr]["macro_long_ok1d"].iloc[i - 1]) if ("macro_long_ok1d" in ind.get(src_sym_sr, {})) else 0.0
                    else:
                        mlong_sr = float(ind[src_sym_sr]["macro_long_ok4"].iloc[i - 1]) if ("macro_long_ok4" in ind.get(src_sym_sr, {})) else 0.0

                    if tf_short_sr == "1d":
                        mshort_sr = float(ind[src_sym_sr]["macro_short_ok1d"].iloc[i - 1]) if ("macro_short_ok1d" in ind.get(src_sym_sr, {})) else 0.0
                    else:
                        mshort_sr = float(ind[src_sym_sr]["macro_short_ok4"].iloc[i - 1]) if ("macro_short_ok4" in ind.get(src_sym_sr, {})) else 0.0

                    adx_ok_sr = True
                    if sr_use_adx_filter and (not np.isnan(adx_v)):
                        adx_ok_sr = (adx_v >= sr_adx_min) and (adx_v <= sr_adx_max)

                    comp_ok_sr = True
                    if sr_require_compress_ok:
                        comp_v = float(ind[sym]["compress_ok4"].iloc[i - 1]) if not np.isnan(ind[sym]["compress_ok4"].iloc[i - 1]) else 0.0
                        comp_ok_sr = (comp_v >= 0.5)

                    if (not np.isnan(sr_h)) and (not np.isnan(sr_l)) and adx_ok_sr and comp_ok_sr:
                        zone = sr_zone_atr * atr_prev
                        long_sr = (sym in long_symbols) and (mlong_sr >= 0.5) and (close_prev <= sr_l + zone)
                        short_sr = allow_short and (sym in short_symbols) and (mshort_sr >= 0.5) and (close_prev >= sr_h - zone)
                        if sr_require_di:
                            long_sr = long_sr and (di_p > di_m)
                            short_sr = short_sr and (di_m > di_p)

                        if long_sr or short_sr:
                            side = 1 if long_sr else -1
                            if mm_fixed:
                                stake_key = f"{sym}_{'short' if side < 0 else 'long'}"
                                stake_scale = float(stake_scale_cfg.get(stake_key, 1.0)) if isinstance(stake_scale_cfg, dict) else 1.0
                                stake_base = _stake_base(eq_prev)
                                stake_used = stake_base * stake_scale * dd_scale * sr_stake_scale
                                if slices_free > 0 and eq_prev >= stake_used:
                                    lev_entry = float(_entry_leverage(adx_v)) if not np.isnan(adx_v) else float(dyn_lev_min)
                                    desired_notional = stake_used * lev_entry * exposure_fraction
                                    allow_notional = max_notional_trend
                                    notional = min(desired_notional, allow_notional)
                                    qty = notional / open_px if open_px > 0 else 0.0
                                    if qty > 0:
                                        entry_px = open_px * (1.0 + slip_rate) if side > 0 else open_px * (1.0 - slip_rate)
                                        fee = qty * entry_px * fee_rate
                                        cash -= fee
                                        stop_px = _price_from_pnl_pct(entry_px, side, lev_entry, -stop_loss_pct)
                                        tp_px = _price_from_pnl_pct(entry_px, side, lev_entry, sr_take_profit_pct) if (sr_take_profit_pct > 0) else np.nan
                                        positions[sym] = {
                                            "mode": "TREND",
                                            "tag": "SR",
                                            "side": side,
                                            "qty": qty,
                                            "avg_entry": entry_px,
                                            "entry_time": t,
                                            "entry_price": entry_px,
                                            "stop": stop_px,
                                            "tp": tp_px,
                                            "trail": np.nan,
                                            "breakeven": np.nan,
                                            "adds": 0,
                                            "cooldown": 0,
                                            "entry_i": i,
                                            "fees_paid": fee,
                                            "funding_paid": 0.0,
                                            "stake": stake_base,
                                            "lev": lev_entry,
                                            "peak_pnl_pct": 0.0,
                                        }
                                        slices_free -= 1

                                        # 入场 bar 内立即检查 STOP/TP（避免下一根 bar 才止损/止盈）
                                        hi = float(data[sym]["high"].iloc[i])
                                        lo = float(data[sym]["low"].iloc[i])
                                        hit_stop0 = (side > 0 and lo <= stop_px) or (side < 0 and hi >= stop_px)
                                        hit_tp0 = False
                                        if tp_enabled and (not np.isnan(tp_px)):
                                            hit_tp0 = (side > 0 and hi >= tp_px) or (side < 0 and lo <= tp_px)

                                        if hit_stop0:
                                            exit_px0 = (stop_px * (1.0 - slip_rate)) if side > 0 else (stop_px * (1.0 + slip_rate))
                                            _close_position(sym, i, exit_px0, "TREND_STOP")
                                            continue
                                        if hit_tp0:
                                            exit_px0 = (tp_px * (1.0 - slip_rate)) if side > 0 else (tp_px * (1.0 + slip_rate))
                                            _close_position(sym, i, exit_px0, "TREND_TP")
                                            continue
                                        continue  # 本 bar 不再尝试 MR
                # --- MR 开仓（在 TREND 未开仓的情况下） ---
                if mr_enabled and (dd_guard_cooldown == 0) and (not dd_recovery_mode):
                    adx_v = float(ind[sym]["adx4"].iloc[i - 1]) if not np.isnan(ind[sym]["adx4"].iloc[i - 1]) else np.nan
                    comp_ok = float(ind[sym]["compress_ok4"].iloc[i - 1]) if not np.isnan(ind[sym]["compress_ok4"].iloc[i - 1]) else 0.0
                    if (not np.isnan(adx_v)) and adx_v <= mr_adx_ceiling and comp_ok >= 0.5:
                        bb_u = float(ind[sym]["bb_upper"].iloc[i - 1]) if not np.isnan(ind[sym]["bb_upper"].iloc[i - 1]) else np.nan
                        bb_l = float(ind[sym]["bb_lower"].iloc[i - 1]) if not np.isnan(ind[sym]["bb_lower"].iloc[i - 1]) else np.nan

                        long_mr = (sym in long_symbols) and (not np.isnan(bb_l)) and (close_prev <= bb_l)
                        short_mr = allow_short and (sym in short_symbols) and (not np.isnan(bb_u)) and (close_prev >= bb_u)

                        if long_mr or short_mr:
                            side = 1 if long_mr else -1
                            stop_dist_mr = mr_atr_stop_mult * atr_prev
                            if stop_dist_mr > 0:
                                risk_dollars = eq_prev * risk_frac * mr_risk_frac_of_trend
                                qty = risk_dollars / stop_dist_mr

                                # MR 独立杠杆上限（更低）
                                max_notional_mr = eq_prev * min(leverage, mr_leverage_cap) * exposure_fraction * w
                                max_qty = max_notional_mr / open_px if open_px > 0 else 0.0
                                qty = max(0.0, min(qty, max_qty))

                                if qty > 0:
                                    entry_px = open_px * (1.0 + slip_rate) if side > 0 else open_px * (1.0 - slip_rate)
                                    fee = qty * entry_px * fee_rate
                                    cash -= fee
                                    positions[sym] = {
                                        "mode": "MR",
                                        "side": side,
                                        "qty": qty,
                                        "avg_entry": entry_px,
                                        "entry_time": t,
                                        "entry_price": entry_px,
                                        "stop": entry_px - side * stop_dist_mr,
                                        "trail": np.nan,
                                        "breakeven": np.nan,
                                        "adds": 0,
                                        "cooldown": 0,
                                        "entry_i": i,
                                        "fees_paid": fee,
                                    }

        # 4) bar close：更新 TREND 追踪止损 / 保本
        for sym in symbols:
            pos = positions[sym]
            if pos["side"] == 0 or pos["mode"] != "TREND":
                continue

            close_px = float(data[sym]["close"].iloc[i])

            # 固定分仓模式：盈利回撤止盈（以“保证金收益率”作为 trailing stop 口径）
            if mm_fixed:
                lev_pos = float(pos.get("lev", leverage))
                pnl_pct_now = pos["side"] * lev_pos * (close_px / pos["avg_entry"] - 1.0)
                pos["peak_pnl_pct"] = max(float(pos.get("peak_pnl_pct", 0.0)), pnl_pct_now)
                peak = float(pos["peak_pnl_pct"])
                if trail_enabled and peak >= trail_activation:
                    lock = max(trail_min_lock, peak * (1.0 - trail_giveback))
                    lock = min(lock, peak)
                    if lock > 0:
                        trail_px = _price_from_pnl_pct(pos["avg_entry"], pos["side"], lev_pos, lock)
                        if pos["side"] > 0:
                            pos["trail"] = max(pos["trail"], trail_px) if not np.isnan(pos["trail"]) else trail_px
                        else:
                            pos["trail"] = min(pos["trail"], trail_px) if not np.isnan(pos["trail"]) else trail_px
                # 固定分仓模式不再使用 ATR trail / breakeven
                continue

            # 旧模式：ATR trailing + breakeven
            atr_now = float(ind[sym]["atr15"].iloc[i]) if not np.isnan(ind[sym]["atr15"].iloc[i]) else np.nan
            if np.isnan(atr_now) or atr_now <= 0:
                continue

            if pos["side"] > 0:
                cand = close_px - atr_trail_mult * atr_now
                pos["trail"] = max(pos["trail"], cand) if not np.isnan(pos["trail"]) else cand
                if close_px >= pos["avg_entry"] + breakeven_atr * atr_now:
                    pos["breakeven"] = _breakeven_price(pos["avg_entry"], pos["side"], fee_rate, slip_rate)
            else:
                cand = close_px + atr_trail_mult * atr_now
                pos["trail"] = min(pos["trail"], cand) if not np.isnan(pos["trail"]) else cand
                if close_px <= pos["avg_entry"] - breakeven_atr * atr_now:
                    pos["breakeven"] = _breakeven_price(pos["avg_entry"], pos["side"], fee_rate, slip_rate)

        # 5) 记录权益曲线（mark-to-market）
        eq = cash + current_unrealized(i)
        equity_curve.append((t, eq))

        if eq > peak_equity:
            peak_equity = eq

        dd_now = eq / peak_equity - 1.0
        dd_abs_now = -dd_now  # 正数

        # DD Guard：触发时进入“冷却/恢复”状态；如有持仓则平仓。
        # ✅ 修复：r064/r065 的“buffer 步进重触发”会让权益在高回撤区间持续下滑（可漂移到 >30%）。
        # 正确口径：
        # - 正常模式：dd_abs_now >= dd_trigger 即触发（提前于 max_dd_halt）
        # - 恢复模式：仅当 dd_abs_now >= max_dd_halt 才允许重触发（把 MaxDD 卡在 25% 左右）
        if dd_guard_enabled and (dd_guard_cooldown == 0):
            has_pos = any(positions[sym]["side"] != 0 for sym in symbols)

            # 触发口径（关键修复）：
            # - 进入 recovery：dd_abs_now >= dd_trigger 触发一次（可无持仓）
            # - recovery 内重触发：只有 dd 进一步恶化超过 step 才允许重触发，避免“阈值上方循环冷却 -> 永久无交易”
            should_trigger = False
            base = max_dd_halt if dd_recovery_mode else dd_trigger
            if dd_abs_now >= base:
                if dd_guard_last_trigger_dd is None:
                    should_trigger = True
                else:
                    should_trigger = dd_abs_now >= (dd_guard_last_trigger_dd + dd_guard_step_dd)

            if should_trigger:
                eq_after = eq

                # 1) 若有持仓：立刻平仓（软退出）
                if has_pos:
                    for sym in symbols:
                        pos = positions[sym]
                        if pos["side"] == 0:
                            continue
                        close_px = float(data[sym]["close"].iloc[i])
                        exit_px = close_px * (1.0 - slip_rate) if pos["side"] > 0 else close_px * (1.0 + slip_rate)
                        _close_position(sym, i, exit_px, "DD_GUARD")

                    # 平仓后重新记录该 bar 的权益（扣除平仓费用）
                    eq_after = cash + current_unrealized(i)
                    equity_curve[-1] = (t, eq_after)

                # 2) 无论是否有持仓：进入冷却（绝对禁止新开仓）
                dd_guard_triggers += 1
                dd_guard_cooldown = dd_guard_cooldown_bars

                # 3) 进入/保持 recovery 模式，并维护低点/锚点
                if not dd_recovery_mode:
                    dd_recovery_mode = True
                    dd_guard_low_equity = eq_after
                else:
                    if dd_guard_low_equity is None:
                        dd_guard_low_equity = eq_after
                    else:
                        dd_guard_low_equity = min(dd_guard_low_equity, eq_after)

                # 记录本次触发时的回撤幅度（用于 step 重触发判断）
                dd_guard_last_trigger_dd = -(eq_after / peak_equity - 1.0)

                # 4) 极端保护：hard_kill
                dd_post = eq_after / peak_equity - 1.0
                if dd_post <= -dd_hard_kill:
                    dd_guard_cooldown = 10**9
    if not equity_curve:
        equity_curve = [(common[-1], cash)]

    eq_df = pd.DataFrame(equity_curve, columns=["time", "equity"]).set_index("time")
    eq_df = eq_df.reindex(common).ffill()

    if trades:
        tdf = pd.DataFrame([t.__dict__ for t in trades])
    else:
        tdf = pd.DataFrame(columns=[f.name for f in Trade.__dataclass_fields__.values()])

    def _safe_num(v: Any) -> float | None:
        try:
            fv = float(v)
        except Exception:
            return None
        return None if np.isnan(fv) else fv

    final_positions = {}
    open_positions_count = 0
    for sym in symbols:
        pos = positions.get(sym, {})
        side_num = int(pos.get("side", 0) or 0)
        if side_num != 0:
            open_positions_count += 1
        final_positions[sym] = {
            "mode": str(pos.get("mode", "NONE")),
            "tag": str(pos.get("tag", "")),
            "side_num": side_num,
            "side": "LONG" if side_num > 0 else ("SHORT" if side_num < 0 else "FLAT"),
            "qty": _safe_num(pos.get("qty", 0.0)) or 0.0,
            "avg_entry": _safe_num(pos.get("avg_entry", 0.0)) or 0.0,
            "entry_time": str(pos.get("entry_time")) if pos.get("entry_time") is not None else None,
            "entry_price": _safe_num(pos.get("entry_price", 0.0)) or 0.0,
            "stop": _safe_num(pos.get("stop", np.nan)),
            "tp": _safe_num(pos.get("tp", np.nan)),
            "trail": _safe_num(pos.get("trail", np.nan)),
            "breakeven": _safe_num(pos.get("breakeven", np.nan)),
            "adds": int(pos.get("adds", 0) or 0),
            "cooldown": int(pos.get("cooldown", 0) or 0),
            "stake": _safe_num(pos.get("stake", 0.0)) or 0.0,
            "lev": _safe_num(pos.get("lev", leverage)) or float(leverage),
            "peak_pnl_pct": _safe_num(pos.get("peak_pnl_pct", 0.0)) or 0.0,
        }

    snapshot = {
        "symbols": symbols,
        "weights": weights,
        "leverage": leverage,
        "exposure_fraction": exposure_fraction,
        "risk_per_trade_total": risk_per_trade_total,
        "max_drawdown_halt": max_dd_halt,
        "dd_guard": {
            "enabled": dd_guard_enabled,
            "trigger": dd_trigger,
            "buffer": dd_guard_buffer,
            "step_dd": dd_guard_step_dd,
            "cooldown_bars": dd_guard_cooldown_bars,
            "recovery_scale": dd_recovery_scale,
            "recovery_exit_pct": dd_recovery_exit_pct,
            "recovery_exit_dd": dd_recovery_exit_dd,
            "hard_kill": dd_hard_kill,
            "triggers": dd_guard_triggers,
        },
        "money_management": {
            "mode": mm_mode,
            "capital_slices": capital_slices,
            "stake_usd": stake_usd,
            "stop_loss_pct": stop_loss_pct,
            "trailing_profit": {
                "enabled": trail_enabled,
                "activation_pnl_pct": trail_activation,
                "giveback_ratio": trail_giveback,
                "min_lock_pnl_pct": trail_min_lock,
            },
        },
        "dynamic_leverage": {
            "enabled": dyn_lev_enabled,
            "min": dyn_lev_min,
            "max": dyn_lev_max,
            "adx_low": dyn_lev_adx_low,
            "adx_high": dyn_lev_adx_high,
        },
        "mr_enabled": mr_enabled,
        "funding": {
            "enabled": funding_enabled,
            "charge_mode": funding_charge_mode,
            "net_cost_total": funding_net_total,
            "net_cost_by_symbol": funding_net_by_symbol,
            "events_by_symbol": funding_events_by_symbol,
        },
        "external_entry_pause": external_pause_meta,
        "final_time": str(common[-1]) if len(common) else None,
        "final_equity": float(eq_df["equity"].iloc[-1]) if not eq_df.empty else float(cash),
        "open_positions_count": open_positions_count,
        "final_positions": final_positions,
    }

    return eq_df, tdf, snapshot
