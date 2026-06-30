from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest.engine import run_backtest_portfolio

try:
    from tools import research_config_baseline as rcb
    from tools import stage46_aggressive_lab as s46
    from tools import stage54_full_angle as s54
except Exception as exc:
    raise SystemExit("缺少 stage46 / stage54 模块，请先保留并应用相关补丁。") from exc

try:
    from tools import stage55_broad_dual_track as s55  # type: ignore
except Exception:
    s55 = None


# -----------------------------
# Candidate maps
# -----------------------------

def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
    except Exception:
        return default
    if math.isnan(v):
        return default
    return v


def _fmt_pct(x: Any) -> str:
    try:
        return f"{float(x) * 100:.2f}%"
    except Exception:
        return "NA"


def _fallback_mainline_items() -> list[dict[str, Any]]:
    # Anchor to the current aggressive frontier rather than old baseline-only variants.
    return [
        {
            "name": "mainline_live_base",
            "note": "当前 live 主线，对照组",
            "mods": {},
        },
        {
            "name": "mainline_split_adx26_cd6_lb24_zone028",
            "note": "当前稳健备选：提频但不硬冲",
            "mods": {
                "strategy_params.cooldown_bars": 6,
                "strategy_params.long_symbols": ["bnb"],
                "strategy_params.short_symbols": ["btc"],
                "filters.adx_floor": 26,
                "filters.btc_adx_floor": 26,
                "sr_entries.enabled": True,
                "sr_entries.symbols": ["bnb"],
                "sr_entries.lookback_4h": 24,
                "sr_entries.zone_atr_mult": 0.28,
                "sr_entries.use_adx_filter": True,
                "sr_entries.adx_min": 0.0,
                "sr_entries.adx_max": 26.0,
                "sr_entries.stake_scale": 0.16,
                "sr_entries.cooldown_bars": 6,
                "sr_entries.require_compress_ok": True,
                "filters.btc_short_pullback_atr": 0.95,
                "filters.btc_short_macro_tf": "4h",
            },
        },
        {
            "name": "mainline_split_adx28_cd6_lb24_zone028",
            "note": "当前激进一号：先冲 220+ 笔，但靠结构条件兜底",
            "mods": {
                "strategy_params.cooldown_bars": 6,
                "strategy_params.long_symbols": ["bnb"],
                "strategy_params.short_symbols": ["btc"],
                "filters.adx_floor": 28,
                "filters.btc_adx_floor": 28,
                "sr_entries.enabled": True,
                "sr_entries.symbols": ["bnb"],
                "sr_entries.lookback_4h": 24,
                "sr_entries.zone_atr_mult": 0.28,
                "sr_entries.use_adx_filter": True,
                "sr_entries.adx_min": 0.0,
                "sr_entries.adx_max": 28.0,
                "sr_entries.stake_scale": 0.16,
                "sr_entries.cooldown_bars": 6,
                "sr_entries.require_compress_ok": True,
                "filters.btc_short_pullback_atr": 0.95,
                "filters.btc_short_macro_tf": "4h",
            },
        },
        {
            "name": "mainline_split_adx30_cd5_lb22_zone029",
            "note": "更激进，但必须叠加中性事件 + 结构门控才能保留",
            "mods": {
                "strategy_params.cooldown_bars": 5,
                "strategy_params.long_symbols": ["bnb"],
                "strategy_params.short_symbols": ["btc"],
                "filters.adx_floor": 30,
                "filters.btc_adx_floor": 30,
                "sr_entries.enabled": True,
                "sr_entries.symbols": ["bnb"],
                "sr_entries.lookback_4h": 22,
                "sr_entries.zone_atr_mult": 0.29,
                "sr_entries.use_adx_filter": True,
                "sr_entries.adx_min": 0.0,
                "sr_entries.adx_max": 30.0,
                "sr_entries.stake_scale": 0.18,
                "sr_entries.cooldown_bars": 5,
                "sr_entries.require_compress_ok": True,
                "filters.btc_short_pullback_atr": 0.98,
                "filters.btc_short_macro_tf": "4h",
            },
        },
    ]


def _fallback_branch_items() -> list[dict[str, Any]]:
    item_map = {item["name"]: copy.deepcopy(item) for item in s54._branch_items()}

    def _with_side(mods: dict[str, Any], symbol: str, side: str) -> dict[str, Any]:
        out = copy.deepcopy(mods)
        if side == "long":
            out["strategy_params.allow_short"] = False
            out["strategy_params.long_symbols"] = [symbol]
            out["strategy_params.short_symbols"] = []
        elif side == "short":
            out["strategy_params.allow_short"] = True
            out["strategy_params.long_symbols"] = []
            out["strategy_params.short_symbols"] = [symbol]
        return out

    rows: list[dict[str, Any]] = []

    def add(symbol: str, base_name: str, new_name: str, side: str, note: str) -> None:
        item = item_map.get(base_name)
        if not item:
            return
        mods = _with_side(item.get("mods", {}), symbol, side)
        rows.append({"symbol": symbol, "name": new_name, "family": side, "note": note, "mods": mods})

    add("sol", "sol_shortwave_sr_smooth", "sol_long_core_fallback", "long", "SOL 长腿保留，不预设只做空")
    add("sol", "sol_fast_trend_4h_lb16", "sol_short_shock_fallback", "short", "SOL 黑天鹅短腿保留")
    add("eth", "eth_shortwave_sr", "eth_long_core_fallback", "long", "ETH 长腿继续观察")
    add("eth", "eth_fast_trend_4h_lb16", "eth_short_shock_fallback", "short", "ETH 黑天鹅短腿保留")
    return rows


def _mainline_items() -> list[dict[str, Any]]:
    if s55 is not None and hasattr(s55, "_mainline_items"):
        wanted = {
            "mainline_live_base",
            "mainline_split_adx26_cd6_lb24_zone028",
            "mainline_split_adx28_cd6_lb24_zone028",
            "mainline_split_adx28_cd5_lb22_zone027",
            "mainline_split_adx30_cd5_lb22_zone027",
        }
        rows = [copy.deepcopy(x) for x in s55._mainline_items() if x.get("name") in wanted]
        if rows:
            return rows
    return _fallback_mainline_items()


def _branch_items() -> list[dict[str, Any]]:
    if s55 is not None and hasattr(s55, "_branch_candidates"):
        wanted = {
            "sol_long_core_adx28_cd6_lb22_zone027_s038",
            "sol_short_shock_lb16_adx22",
            "sol_dual_guarded_core_plus_shock",
            "eth_long_core_adx26_cd6_lb24_zone028_s032",
            "eth_short_shock_lb16_adx24",
            "eth_dual_guarded_core_plus_shock",
        }
        rows = []
        for x in s55._branch_candidates():
            if x.get("name") in wanted:
                fam = "dual"
                name = str(x.get("name", ""))
                if "long" in name:
                    fam = "long"
                elif "short" in name or "shock" in name:
                    fam = "short"
                rows.append(
                    {
                        "symbol": x.get("symbol"),
                        "name": x.get("name"),
                        "family": fam,
                        "note": x.get("note", ""),
                        "mods": copy.deepcopy(x.get("mods", {})),
                    }
                )
        if rows:
            return rows
    return _fallback_branch_items()


# -----------------------------
# Metrics / feature attachment
# -----------------------------

def _metrics_from_trades(trades: pd.DataFrame, initial_equity: float) -> dict[str, Any]:
    if trades is None or trades.empty:
        return {
            "trades": 0,
            "pf": 0.0,
            "ret": 0.0,
            "maxdd": 0.0,
            "win_rate": 0.0,
            "monthly": s46._monthly_stats(pd.DataFrame(), initial_equity),
            "rolling12_pf_floor": 0.0,
            "seg_pf": {"2020_2021": 0.0, "2022_2023": 0.0, "2024_2026": 0.0},
            "counts": {},
            "pnl": 0.0,
        }
    df = trades.copy()
    if "exit_time" in df.columns:
        df["exit_time"] = pd.to_datetime(df["exit_time"], errors="coerce")
        df = df.dropna(subset=["exit_time"]).sort_values("exit_time")
    pnl = pd.to_numeric(df.get("pnl"), errors="coerce").fillna(0.0)
    eq = float(initial_equity) + pnl.cumsum()
    peak = eq.cummax()
    dd = eq / peak - 1.0 if len(eq) else pd.Series(dtype=float)
    counts = {}
    if {"symbol", "side"}.issubset(df.columns):
        counts = {f"{k[0]}_{k[1]}": int(v) for k, v in df.groupby(["symbol", "side"]).size().to_dict().items()}
    return {
        "trades": int(len(df)),
        "pf": float(s46._pf_from_trades(df)),
        "ret": float(eq.iloc[-1] / float(initial_equity) - 1.0) if len(eq) else 0.0,
        "maxdd": float(dd.min()) if len(dd) else 0.0,
        "win_rate": float((pnl > 0).mean()) if len(pnl) else 0.0,
        "monthly": s46._monthly_stats(df, initial_equity),
        "rolling12_pf_floor": float(s46._rolling_12m_pf_floor(df)),
        "seg_pf": {
            "2020_2021": float(s46._segment_pf(df, 2020, 2021)),
            "2022_2023": float(s46._segment_pf(df, 2022, 2023)),
            "2024_2026": float(s46._segment_pf(df, 2024, 2026)),
        },
        "counts": counts,
        "pnl": float(pnl.sum()),
    }


def _load_symbol_ohlcv(root: Path, cfg: dict[str, Any], symbol: str) -> pd.DataFrame:
    data = s54._load_multi_data(root, cfg, [symbol])
    df = data.get(symbol)
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    out = out.reset_index().rename(columns={out.index.name or "index": "ts"})
    if "ts" not in out.columns:
        out = out.rename(columns={out.columns[0]: "ts"})
    out["ts"] = pd.to_datetime(out["ts"], errors="coerce")
    out = out.dropna(subset=["ts"]).sort_values("ts")
    return out


def _bool_series(df: pd.DataFrame, name: str, default: bool = False) -> pd.Series:
    if name not in df.columns:
        return pd.Series(default, index=df.index, dtype=bool)
    ser = df[name]
    if not isinstance(ser, pd.Series):
        return pd.Series(bool(ser), index=df.index, dtype=bool)
    ser = ser.reindex(df.index)
    if pd.api.types.is_bool_dtype(ser):
        return ser.fillna(default).astype(bool)
    if pd.api.types.is_numeric_dtype(ser):
        fill = 1.0 if default else 0.0
        return ser.fillna(fill).astype(float).ne(0.0)
    txt = ser.astype(str).str.strip().str.lower()
    mapped = txt.map({
        "true": True,
        "1": True,
        "yes": True,
        "y": True,
        "false": False,
        "0": False,
        "no": False,
        "n": False,
        "nan": default,
        "none": default,
        "": default,
    })
    return mapped.fillna(default).astype(bool)


def _coalesce_bool_columns(df: pd.DataFrame, target: str, candidates: list[str], default: bool = False) -> pd.Series:
    out = pd.Series(default, index=df.index, dtype=bool)
    found = False
    names = [target] + [name for name in candidates if name != target]
    for name in names:
        if name in df.columns:
            found = True
            out = out | _bool_series(df, name, default)
    return out if found else pd.Series(default, index=df.index, dtype=bool)


def _attach_bar_features(root: Path, cfg: dict[str, Any], trades_msg: pd.DataFrame) -> pd.DataFrame:
    if trades_msg is None or trades_msg.empty:
        return pd.DataFrame()
    feature_cols = [
        "ts",
        "symbol",
        "lower_wick_ratio",
        "upper_wick_ratio",
        "body_ratio",
        "close_loc",
        "range_rel",
        "vol_rel",
        "bar_ret",
        "bullish_wick",
        "bearish_wick",
        "bullish_spike_fade",
        "bearish_spike_fade",
    ]
    frames: list[pd.DataFrame] = []
    symbols = {str(x).strip().lower() for x in trades_msg.get("symbol", pd.Series(dtype=str)).dropna().unique()}
    for sym in sorted(symbols):
        if not sym:
            continue
        bars = _load_symbol_ohlcv(root, cfg, sym)
        if bars.empty:
            continue
        out = bars.copy()
        for col in ["open", "high", "low", "close", "volume"]:
            if col in out.columns:
                out[col] = pd.to_numeric(out[col], errors="coerce")
        rng = (out["high"] - out["low"]).replace(0.0, float("nan"))
        body = (out["close"] - out["open"]).abs()
        upper = out["high"] - out[["open", "close"]].max(axis=1)
        lower = out[["open", "close"]].min(axis=1) - out["low"]
        roll_rng = (out["high"] - out["low"]).rolling(32, min_periods=8).median().replace(0.0, float("nan"))
        if "volume" in out.columns:
            roll_vol = out["volume"].rolling(32, min_periods=8).median().replace(0.0, float("nan"))
            vol_rel = (out["volume"] / roll_vol).clip(lower=0.0).fillna(1.0)
        else:
            vol_rel = pd.Series(1.0, index=out.index, dtype=float)
        bar_ret = (out["close"] / out["open"] - 1.0).replace([float("inf"), float("-inf")], float("nan"))
        out["symbol"] = sym.upper()
        out["lower_wick_ratio"] = (lower / rng).clip(lower=0.0).fillna(0.0)
        out["upper_wick_ratio"] = (upper / rng).clip(lower=0.0).fillna(0.0)
        out["body_ratio"] = (body / rng).clip(lower=0.0).fillna(0.0)
        out["close_loc"] = ((out["close"] - out["low"]) / rng).clip(lower=0.0, upper=1.0).fillna(0.5)
        out["range_rel"] = ((out["high"] - out["low"]) / roll_rng).clip(lower=0.0).fillna(1.0)
        out["vol_rel"] = pd.to_numeric(vol_rel, errors="coerce").fillna(1.0)
        out["bar_ret"] = pd.to_numeric(bar_ret, errors="coerce").fillna(0.0)
        out["bullish_wick"] = (out["lower_wick_ratio"] >= 0.42) & (out["body_ratio"] <= 0.45) & (out["close_loc"] >= 0.58) & (out["range_rel"] >= 1.18)
        out["bearish_wick"] = (out["upper_wick_ratio"] >= 0.42) & (out["body_ratio"] <= 0.45) & (out["close_loc"] <= 0.42) & (out["range_rel"] >= 1.18)
        out["bullish_spike_fade"] = (out["bar_ret"] <= -0.010) & (out["close_loc"] >= 0.56) & (out["range_rel"] >= 1.25)
        out["bearish_spike_fade"] = (out["bar_ret"] >= 0.010) & (out["close_loc"] <= 0.44) & (out["range_rel"] >= 1.25)
        frames.append(out[feature_cols])
    trades = trades_msg.copy()
    if not frames or "entry_time" not in trades.columns or "symbol" not in trades.columns:
        return trades
    feats = pd.concat(frames, ignore_index=True).sort_values(["symbol", "ts"])
    trades["entry_time"] = pd.to_datetime(trades["entry_time"], errors="coerce")
    trades["symbol"] = trades["symbol"].astype(str).str.strip().str.upper()
    trades = trades.dropna(subset=["entry_time"])
    out_parts: list[pd.DataFrame] = []
    drop_cols = [col for col in feature_cols if col != "symbol"]
    for sym, sub in trades.groupby("symbol"):
        feat_sub = feats[feats["symbol"] == sym].copy().sort_values("ts")
        if feat_sub.empty:
            out_parts.append(sub)
            continue
        sub = sub.drop(columns=[col for col in drop_cols if col in sub.columns], errors="ignore")
        merged = pd.merge_asof(
            sub.sort_values("entry_time"),
            feat_sub,
            left_on="entry_time",
            right_on="ts",
            by="symbol",
            direction="backward",
            tolerance=pd.Timedelta(minutes=15),
        )
        out_parts.append(merged)
    out = pd.concat(out_parts, ignore_index=True, sort=False) if out_parts else trades
    out["event_blocked"] = _coalesce_bool_columns(out, "event_blocked", ["event_blocked"], False)
    out["event_identified"] = _coalesce_bool_columns(out, "event_identified", ["event_identified", "event_blocked"], False)
    out["event_positive"] = _coalesce_bool_columns(out, "event_positive", ["event_positive"], False)
    out["event_two_sided"] = _coalesce_bool_columns(out, "event_two_sided", ["event_two_sided"], False)
    out["event_observation"] = _coalesce_bool_columns(out, "event_observation", ["event_observation"], False)
    out["event_negative"] = _coalesce_bool_columns(out, "event_negative", ["event_negative"], False)
    out["risk_crowded_long"] = _coalesce_bool_columns(out, "risk_crowded_long", ["risk_crowded_long", "cg_long_risk", "lsr_hi"], False)
    out["risk_oi_high"] = _coalesce_bool_columns(out, "risk_oi_high", ["risk_oi_high", "oi_down_shock"], False)
    out["risk_crowded_short"] = _coalesce_bool_columns(out, "risk_crowded_short", ["risk_crowded_short", "cg_short_risk", "lsr_lo"], False)

    out["neutral_event"] = ~(out["event_identified"] | out["risk_oi_high"] | out["risk_crowded_long"] | out["risk_crowded_short"])
    side = out.get("side", pd.Series(index=out.index, dtype=str)).astype(str).str.upper()
    crowded_long = _bool_series(out, "risk_crowded_long", False)
    crowded_short = _bool_series(out, "risk_crowded_short", False)
    oi_high = _bool_series(out, "risk_oi_high", False)
    bullish_wick = _bool_series(out, "bullish_wick", False)
    bearish_wick = _bool_series(out, "bearish_wick", False)
    bullish_spike = _bool_series(out, "bullish_spike_fade", False)
    bearish_spike = _bool_series(out, "bearish_spike_fade", False)
    out["wick_revert_ok"] = ((side == "LONG") & bullish_wick) | ((side == "SHORT") & bearish_wick)
    out["spike_fade_ok"] = ((side == "LONG") & bullish_spike) | ((side == "SHORT") & bearish_spike)
    out["structural_ok"] = out["neutral_event"] & (out["wick_revert_ok"] | out["spike_fade_ok"])
    out["flow_aligned"] = ((side == "LONG") & ~crowded_long) | ((side == "SHORT") & (crowded_long | oi_high) & ~crowded_short)
    return out


# -----------------------------
# Gates
# -----------------------------

def _gate_none(df: pd.DataFrame) -> pd.Series:
    return pd.Series(True, index=df.index)


def _gate_neutral_wick(df: pd.DataFrame) -> pd.Series:
    return _bool_series(df, "neutral_event", False) & _bool_series(df, "wick_revert_ok", False)


def _gate_neutral_spike(df: pd.DataFrame) -> pd.Series:
    return _bool_series(df, "neutral_event", False) & _bool_series(df, "spike_fade_ok", False)


def _gate_neutral_combo(df: pd.DataFrame) -> pd.Series:
    return _bool_series(df, "structural_ok", False)


def _gate_neutral_combo_flow(df: pd.DataFrame) -> pd.Series:
    return _bool_series(df, "structural_ok", False) & _bool_series(df, "flow_aligned", True)


GATES: list[tuple[str, Callable[[pd.DataFrame], pd.Series], str]] = [
    ("base_message_overlay", _gate_none, "只保留消息面 overlay，不加结构门"),
    ("neutral_wick", _gate_neutral_wick, "无明显消息时，插针回归"),
    ("neutral_spike_fade", _gate_neutral_spike, "无明显消息时，过冲回吐"),
    ("neutral_wick_or_spike", _gate_neutral_combo, "放松标准，但必须满足中性消息 + 结构回归"),
    ("neutral_struct_flow_aligned", _gate_neutral_combo_flow, "放松标准，但同时满足中性消息 + 结构回归 + 拥挤/持仓方向配合"),
]


def _evaluate_gate(trades_feat: pd.DataFrame, gate_name: str, gate_fn: Callable[[pd.DataFrame], pd.Series], note: str, initial_equity: float) -> dict[str, Any]:
    if trades_feat is None or trades_feat.empty:
        gated_df = pd.DataFrame()
    else:
        mask = gate_fn(trades_feat).fillna(False)
        gated_df = trades_feat.loc[mask].copy()
    metrics = _metrics_from_trades(gated_df, initial_equity)
    return {"gate_name": gate_name, "gate_note": note, "metrics": metrics, "gated_df": gated_df}


# -----------------------------
# Scoring
# -----------------------------

def _main_score(metrics: dict[str, Any], ref: dict[str, Any]) -> float:
    m = metrics.get("monthly", {}) or {}
    rm = ref.get("monthly", {}) or {}
    trades = int(metrics.get("trades", 0) or 0)
    target_bonus = 18.0 if 220 <= trades <= 260 else (10.0 if trades >= 200 else 0.0)
    return float(
        _safe_float(metrics.get("pf")) * 88.0
        + _safe_float(metrics.get("ret")) * 58.0
        - abs(_safe_float(metrics.get("maxdd"))) * 86.0
        + min(trades, 260) * 0.30
        + max(0, int(m.get("months_ge_20", 0)) - int(rm.get("months_ge_20", 0))) * 2.4
        + _safe_float(metrics.get("rolling12_pf_floor")) * 22.0
        + target_bonus
    )


def _branch_score(metrics: dict[str, Any]) -> float:
    m = metrics.get("monthly", {}) or {}
    return float(
        _safe_float(metrics.get("pf")) * 94.0
        + _safe_float(metrics.get("ret")) * 66.0
        - abs(_safe_float(metrics.get("maxdd"))) * 74.0
        + min(int(metrics.get("trades", 0) or 0), 220) * 0.22
        + int(m.get("months_ge_20", 0) or 0) * 11.0
        + _safe_float(m.get("monthly_p75")) * 125.0
        + _safe_float(metrics.get("rolling12_pf_floor")) * 14.0
    )


def _main_gate_label(metrics: dict[str, Any], ref: dict[str, Any]) -> str:
    if (
        int(metrics.get("trades", 0) or 0) >= max(170, int(ref.get("trades", 0) or 0))
        and _safe_float(metrics.get("pf")) >= max(1.85, _safe_float(ref.get("pf")) - 0.28)
        and abs(_safe_float(metrics.get("maxdd"))) <= abs(_safe_float(ref.get("maxdd"))) + 0.10
        and _safe_float(metrics.get("rolling12_pf_floor")) >= max(0.70, _safe_float(ref.get("rolling12_pf_floor")) - 0.12)
    ):
        return "pass"
    if _safe_float(metrics.get("pf")) >= 1.08 and int(metrics.get("trades", 0) or 0) >= 80:
        return "hold"
    return "kill"


def _branch_gate_label(metrics: dict[str, Any]) -> str:
    if _safe_float(metrics.get("pf")) >= 1.02 and _safe_float(metrics.get("ret")) > 0 and abs(_safe_float(metrics.get("maxdd"))) <= 0.48 and int(metrics.get("trades", 0) or 0) >= 8:
        return "pass"
    if _safe_float(metrics.get("pf")) >= 0.95 and int(metrics.get("trades", 0) or 0) >= 6:
        return "hold"
    return "kill"


def _pick_best_gate(gate_rows: list[dict[str, Any]], score_fn: Callable[..., float], label_fn: Callable[..., str], ref_metrics: dict[str, Any] | None = None) -> dict[str, Any]:
    best = None
    best_score = -1e18
    for row in gate_rows:
        metrics = row["metrics"]
        if ref_metrics is None:
            score = score_fn(metrics)
            gate = label_fn(metrics)
        else:
            score = score_fn(metrics, ref_metrics)
            gate = label_fn(metrics, ref_metrics)
        row["score"] = score
        row["gate"] = gate
        if score > best_score:
            best_score = score
            best = row
    return best if best is not None else gate_rows[0]


# -----------------------------
# Run helpers
# -----------------------------

def _run_portfolio_candidate(root: Path, cfg: dict[str, Any], data: dict[str, pd.DataFrame], mods: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    cfg2 = copy.deepcopy(cfg)
    for path, value in mods.items():
        s46._set_nested(cfg2, path, value)
    _, trades, _ = run_backtest_portfolio(data, cfg2)
    try:
        trades_msg = s54._attach_message_layers(root, trades)
    except Exception:
        trades_msg = trades.copy()
    trades_feat = _attach_bar_features(root, cfg2, trades_msg)
    return trades, trades_feat


def _run_mainline(root: Path, cfg: dict[str, Any], data: dict[str, pd.DataFrame], item: dict[str, Any], initial_equity: float) -> dict[str, Any]:
    trades, trades_feat = _run_portfolio_candidate(root, cfg, data, item["mods"])
    base_metrics = _metrics_from_trades(trades, initial_equity)
    gates = [_evaluate_gate(trades_feat, name, fn, note, initial_equity) for name, fn, note in GATES]
    return {"name": item["name"], "note": item["note"], "base_metrics": base_metrics, "gate_rows": gates}


def _run_branch(root: Path, cfg: dict[str, Any], item: dict[str, Any], initial_equity: float) -> dict[str, Any]:
    cfg2 = copy.deepcopy(cfg)
    sym = str(item["symbol"]).lower()
    cfg2.setdefault("data", {})["symbols"] = [sym]
    cfg2.setdefault("data", {})["weights"] = {sym: 1.0}
    cfg2.setdefault("filters", {})["macro_gate_symbols"] = [sym]
    cfg2.setdefault("filters", {})["macro_gate_reference_symbol"] = sym
    data = s46._load_portfolio_data(root, cfg2)
    trades, trades_feat = _run_portfolio_candidate(root, cfg2, data, item["mods"])
    base_metrics = _metrics_from_trades(trades, initial_equity)
    gates = [_evaluate_gate(trades_feat, name, fn, note, initial_equity) for name, fn, note in GATES]
    return {
        "symbol": sym,
        "family": item.get("family", "mixed"),
        "name": item["name"],
        "note": item.get("note", ""),
        "base_metrics": base_metrics,
        "gate_rows": gates,
    }


# -----------------------------
# JSON-safe helpers
# -----------------------------

def _json_safe(obj: Any) -> Any:
    if isinstance(obj, pd.DataFrame):
        return {"rows": int(len(obj)), "columns": list(obj.columns)}
    if isinstance(obj, pd.Series):
        return obj.tolist()
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if hasattr(obj, "isoformat"):
        try:
            return obj.isoformat()
        except Exception:
            pass
    try:
        import numpy as np  # type: ignore
        if isinstance(obj, (np.integer, np.floating, np.bool_)):
            return obj.item()
        if isinstance(obj, np.ndarray):
            return obj.tolist()
    except Exception:
        pass
    return obj

def _strip_gate_payload(row: dict[str, Any]) -> dict[str, Any]:
    best = dict(row.get("best_gate") or {})
    gated_df = best.pop("gated_df", None)
    if isinstance(gated_df, pd.DataFrame):
        best["gated_rows"] = int(len(gated_df))
        best["gated_columns"] = list(gated_df.columns)[:12]
    return _json_safe(best)

# -----------------------------
# Writers
# -----------------------------

def _write_mainline(path_txt: Path, path_json: Path, rows: list[dict[str, Any]], ref_metrics: dict[str, Any]) -> None:
    lines: list[str] = []
    lines.append("Stage59 主线结构化提频研究")
    lines.append("核心原则：不再只降阈值；放松标准必须叠加新条件")
    lines.append("")
    lines.append("=== 候选结果 ===")
    for row in rows:
        best = row["best_gate"]
        m = best["metrics"].get("monthly", {}) or {}
        lines.append(
            f"- {row['name']}: best_gate={best['gate_name']} ({best['gate']}) | trades={best['metrics'].get('trades', 0)} | pf={_safe_float(best['metrics'].get('pf')):.3f} | ret={_fmt_pct(best['metrics'].get('ret'))} | maxDD={_fmt_pct(best['metrics'].get('maxdd'))} | months>=20%={m.get('months_ge_20', 0)} | roll12_pf_floor={_safe_float(best['metrics'].get('rolling12_pf_floor')):.3f} | score={best['score']:+.2f}"
        )
        lines.append(
            f"  gate_note={best['gate_note']} | seg_pf=2020-2021:{_safe_float(best['metrics']['seg_pf'].get('2020_2021')):.3f} / 2022-2023:{_safe_float(best['metrics']['seg_pf'].get('2022_2023')):.3f} / 2024-2026:{_safe_float(best['metrics']['seg_pf'].get('2024_2026')):.3f}"
        )
    lines.append("")
    lines.append("=== 结论 ===")
    lines.append("- 主线提频不停，但改成‘条件性放松 + 结构确认’，不再粗暴降 ADX / zone / cooldown。")
    lines.append("- 当前重点看 neutral_wick_or_spike 与 neutral_struct_flow_aligned：更符合‘无重大消息时，插针/过冲后回归’的假设。")
    lines.append(f"- 参考底线：pf={_safe_float(ref_metrics.get('pf')):.3f} | roll12_pf_floor={_safe_float(ref_metrics.get('rolling12_pf_floor')):.3f}。")
    path_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    serializable = []
    for row in rows:
        serializable.append({"name": row["name"], "note": row["note"], "best_gate": _strip_gate_payload(row)})
    path_json.write_text(json.dumps({"rows": _json_safe(serializable), "reference": _json_safe(ref_metrics)}, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_branch(path_txt: Path, path_json: Path, rows: list[dict[str, Any]]) -> None:
    lines: list[str] = []
    lines.append("Stage59 ETH / SOL 广角结构化分支")
    lines.append("核心原则：SOL / ETH 都保留多空与双向候选；加入 neutral-news wick reversion / spike fade")
    lines.append("")
    lines.append("=== 候选结果 ===")
    for row in rows:
        best = row["best_gate"]
        m = best["metrics"].get("monthly", {}) or {}
        lines.append(
            f"- {row['symbol'].upper()} | family={row['family']} | {row['name']}: best_gate={best['gate_name']} ({best['gate']}) | trades={best['metrics'].get('trades', 0)} | pf={_safe_float(best['metrics'].get('pf')):.3f} | ret={_fmt_pct(best['metrics'].get('ret'))} | maxDD={_fmt_pct(best['metrics'].get('maxdd'))} | months>=20%={m.get('months_ge_20', 0)} | p75_month={_fmt_pct(m.get('monthly_p75'))} | score={best['score']:+.2f}"
        )
        if row.get("note"):
            lines.append(f"  note={row['note']} | gate_note={best['gate_note']}")
    lines.append("")
    lines.append("=== 结论 ===")
    lines.append("- 分支不再只扫参数，而是明确测试 trend / shock / wick-reversion 三种结构。")
    lines.append("- SOL / ETH 都允许 long / short / dual 继续保留，只要结构门控后还能过 gate。")
    path_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    serializable = []
    for row in rows:
        serializable.append({"symbol": row["symbol"], "family": row["family"], "name": row["name"], "best_gate": _strip_gate_payload(row), "note": row.get("note", "")})
    path_json.write_text(json.dumps({"rows": _json_safe(serializable)}, ensure_ascii=False, indent=2), encoding="utf-8")


# -----------------------------
# Main
# -----------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Stage59 structural lab")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    cfg = rcb.load_research_base_config(root)
    reports = root / "reports" / "research_raw"
    reports.mkdir(parents=True, exist_ok=True)
    initial_equity = float(cfg.get("portfolio", {}).get("initial_equity", 100000.0))

    # mainline
    main_cfg = copy.deepcopy(cfg)
    main_cfg.setdefault("data", {})["symbols"] = ["btc", "bnb"]
    main_cfg.setdefault("data", {})["weights"] = {"btc": 0.015, "bnb": 0.985}
    main_data = s46._load_portfolio_data(root, main_cfg)

    main_rows: list[dict[str, Any]] = []
    for item in _mainline_items():
        row = _run_mainline(root, main_cfg, main_data, item, initial_equity)
        main_rows.append(row)
    ref_row = next((r for r in main_rows if r["name"] == "mainline_live_base"), main_rows[0])
    ref_best = _pick_best_gate(ref_row["gate_rows"], _main_score, _main_gate_label, ref_row["base_metrics"])
    ref_metrics = ref_best["metrics"]
    for row in main_rows:
        row["best_gate"] = _pick_best_gate(row["gate_rows"], _main_score, _main_gate_label, ref_metrics)
    main_rows = sorted(main_rows, key=lambda r: (r["best_gate"]["gate"] == "pass", r["best_gate"]["gate"] == "hold", r["best_gate"]["score"]), reverse=True)

    # branches
    branch_rows: list[dict[str, Any]] = []
    for item in _branch_items():
        row = _run_branch(root, cfg, item, initial_equity)
        row["best_gate"] = _pick_best_gate(row["gate_rows"], _branch_score, _branch_gate_label)
        branch_rows.append(row)
    branch_rows = sorted(branch_rows, key=lambda r: (r["best_gate"]["gate"] == "pass", r["best_gate"]["gate"] == "hold", r["best_gate"]["score"]), reverse=True)

    main_txt = reports / "stage59_mainline_structural_latest.txt"
    main_json = reports / "stage59_mainline_structural_latest.json"
    branch_txt = reports / "stage59_branch_structural_latest.txt"
    branch_json = reports / "stage59_branch_structural_latest.json"
    _write_mainline(main_txt, main_json, main_rows, ref_metrics)
    _write_branch(branch_txt, branch_json, branch_rows)
    print(main_txt)
    print(branch_txt)


if __name__ == "__main__":
    main()
