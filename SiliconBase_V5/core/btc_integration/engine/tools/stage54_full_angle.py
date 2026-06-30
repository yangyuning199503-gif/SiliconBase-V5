from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest.engine import run_backtest_portfolio
from src.backtest.io import load_ohlcv_csv, read_config
from tools.alt_shortwave_lab import FULL_EXTRA_CANDIDATES, QUICK_CANDIDATES, _load_symbol_data, _set_nested
from tools.alt_shortwave_message_overlay import _attach_message_layers, _pick_best_variant, _trade_metrics_from_df


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
        v = float(x)
    except Exception:
        return "NA"
    if math.isnan(v):
        return "NA"
    return f"{v * 100:.2f}%"


def _pf(df: pd.DataFrame) -> float:
    if df is None or df.empty or "pnl" not in df.columns:
        return float("nan")
    pnl = pd.to_numeric(df["pnl"], errors="coerce").fillna(0.0)
    gp = float(pnl[pnl > 0].sum())
    gl = float(-pnl[pnl < 0].sum())
    if gl <= 0:
        return float("inf") if gp > 0 else float("nan")
    return gp / gl


def _segment_pfs(trades: pd.DataFrame) -> dict[str, float]:
    if trades is None or trades.empty:
        return {"2020-2021": float("nan"), "2022-2023": float("nan"), "2024-2026": float("nan")}
    df = trades.copy()
    df["exit_time"] = pd.to_datetime(df["exit_time"], errors="coerce")
    df = df.dropna(subset=["exit_time"])
    return {
        "2020-2021": _pf(df[df["exit_time"].dt.year <= 2021]),
        "2022-2023": _pf(df[(df["exit_time"].dt.year >= 2022) & (df["exit_time"].dt.year <= 2023)]),
        "2024-2026": _pf(df[df["exit_time"].dt.year >= 2024]),
    }


def _active_months(trades: pd.DataFrame) -> int:
    if trades is None or trades.empty:
        return 0
    df = trades.copy()
    df["exit_time"] = pd.to_datetime(df["exit_time"], errors="coerce")
    df = df.dropna(subset=["exit_time"])
    if df.empty:
        return 0
    return int(df["exit_time"].dt.to_period("M").nunique())


def _side_metrics(trades: pd.DataFrame, side: str, initial_equity: float = 100000.0) -> dict[str, Any]:
    if trades is None or trades.empty:
        return {"trades": 0, "pf": float("nan"), "pnl": 0.0, "ret": 0.0}
    df = trades.copy()
    df = df[df["side"].astype(str).str.upper() == side.upper()]
    if df.empty:
        return {"trades": 0, "pf": float("nan"), "pnl": 0.0, "ret": 0.0}
    pnl = pd.to_numeric(df["pnl"], errors="coerce").fillna(0.0)
    total = float(pnl.sum())
    return {
        "trades": int(len(df)),
        "pf": float(_pf(df)),
        "pnl": total,
        "ret": float(total / float(initial_equity)),
    }


def _bias_label(long_leg: dict[str, Any], short_leg: dict[str, Any]) -> str:
    lp, sp = _safe_float(long_leg.get("pnl"), 0.0), _safe_float(short_leg.get("pnl"), 0.0)
    lpf, spf = _safe_float(long_leg.get("pf"), 0.0), _safe_float(short_leg.get("pf"), 0.0)
    if long_leg.get("trades", 0) >= 6 and short_leg.get("trades", 0) >= 6 and lp > 0 and sp > 0 and lpf >= 1.0 and spf >= 1.0:
        return "双边有效"
    if lp > 0 and sp <= 0:
        return "偏多"
    if sp > 0 and lp <= 0:
        return "偏空"
    if lp > 0 and sp > 0:
        return "双边待修"
    return "双边失效"


def _load_multi_data(root: Path, cfg: dict[str, Any], symbols: list[str]) -> dict[str, pd.DataFrame]:
    data_cfg = cfg.get("data", {})
    csv_template = str(data_cfg.get("csv_template", "data/raw/{symbol}_15m.csv"))
    start = pd.to_datetime(data_cfg.get("start"), utc=True).tz_convert(None) if data_cfg.get("start") else None
    end = pd.to_datetime(data_cfg.get("end"), utc=True).tz_convert(None) if data_cfg.get("end") else None
    out: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        path = root / csv_template.format(symbol=symbol)
        if not path.exists():
            raise SystemExit(f"缺少原始数据：{path}")
        df = load_ohlcv_csv(path)
        if start is not None:
            df = df.loc[df.index >= start]
        if end is not None:
            df = df.loc[df.index <= end]
        out[symbol] = df
    return out


def _apply_overlay_variant(trades_msg: pd.DataFrame, best: dict[str, Any]) -> pd.DataFrame:
    if trades_msg is None or trades_msg.empty:
        return pd.DataFrame()
    variant = str(best.get("variant", "no_guard"))
    if variant == "no_guard":
        return trades_msg.copy()
    if variant == "event_only":
        if "event_blocked" in trades_msg.columns:
            return trades_msg.loc[~trades_msg["event_blocked"].astype(bool)].copy()
        return trades_msg.copy()
    if variant == "coinglass_only":
        gate = pd.Series(True, index=trades_msg.index)
        for col in ["risk_oi_high", "risk_crowded_long"]:
            if col in trades_msg.columns:
                gate &= ~trades_msg[col].astype(bool)
        return trades_msg.loc[gate].copy()
    gate = pd.Series(True, index=trades_msg.index)
    for col in ["event_blocked", "risk_oi_high", "risk_crowded_long"]:
        if col in trades_msg.columns:
            gate &= ~trades_msg[col].astype(bool)
    return trades_msg.loc[gate].copy()


def _overlay_bundle(root: Path, trades: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame]:
    if trades is None or trades.empty:
        return ({"variant": "no_guard", "blocked": 0, "gated": _trade_metrics_from_df(trades)}, pd.DataFrame())
    try:
        trades_msg = _attach_message_layers(root, trades)
        best = _pick_best_variant(trades_msg)
        gated_df = _apply_overlay_variant(trades_msg, best)
        return best, gated_df
    except Exception as e:
        base = _trade_metrics_from_df(trades)
        return ({
            "variant": "overlay_error",
            "blocked": 0,
            "pnl_delta": 0.0,
            "dd_delta": 0.0,
            "score": 0.0,
            "gated": base,
            "top_event_groups": [f"overlay_error:{e.__class__.__name__}"],
            "decision": "继续研究",
        }, trades.copy())


MAINLINE_CANDIDATES: list[dict[str, Any]] = [
    {"name": "mainline_live_base", "mods": {}, "note": "当前 live 主线，对照组"},
    {
        "name": "mainline_combo_sr_soft_adx26_cd6_lb24_zone028",
        "note": "主线提频候选：soft SR + ADX26 + cd6",
        "mods": {
            "strategy_params.cooldown_bars": 6,
            "filters.adx_floor": 26,
            "filters.btc_adx_floor": 26,
            "sr_entries.enabled": True,
            "sr_entries.symbols": ["btc", "bnb"],
            "sr_entries.lookback_4h": 24,
            "sr_entries.zone_atr_mult": 0.28,
            "sr_entries.use_adx_filter": True,
            "sr_entries.adx_min": 0.0,
            "sr_entries.adx_max": 26.0,
            "sr_entries.stake_scale": 0.16,
            "sr_entries.cooldown_bars": 6,
            "sr_entries.require_compress_ok": True,
        },
    },
    {
        "name": "mainline_combo_sr_soft_adx28_cd6_lb24_zone028",
        "note": "主线提频候选：soft SR + ADX28 + cd6",
        "mods": {
            "strategy_params.cooldown_bars": 6,
            "filters.adx_floor": 28,
            "filters.btc_adx_floor": 28,
            "sr_entries.enabled": True,
            "sr_entries.symbols": ["btc", "bnb"],
            "sr_entries.lookback_4h": 24,
            "sr_entries.zone_atr_mult": 0.28,
            "sr_entries.use_adx_filter": True,
            "sr_entries.adx_min": 0.0,
            "sr_entries.adx_max": 28.0,
            "sr_entries.stake_scale": 0.16,
            "sr_entries.cooldown_bars": 6,
            "sr_entries.require_compress_ok": True,
        },
    },
    {
        "name": "mainline_combo_sr_soft_adx32_cd5_lb20_zone025",
        "note": "主线激进候选：更快 lookback / 更紧 zone",
        "mods": {
            "strategy_params.cooldown_bars": 5,
            "filters.adx_floor": 32,
            "filters.btc_adx_floor": 32,
            "sr_entries.enabled": True,
            "sr_entries.symbols": ["btc", "bnb"],
            "sr_entries.lookback_4h": 20,
            "sr_entries.zone_atr_mult": 0.25,
            "sr_entries.use_adx_filter": True,
            "sr_entries.adx_min": 0.0,
            "sr_entries.adx_max": 32.0,
            "sr_entries.stake_scale": 0.18,
            "sr_entries.cooldown_bars": 5,
            "sr_entries.require_compress_ok": True,
        },
    },
]


def _mainline_score(row: dict[str, Any]) -> float:
    gated = row["best_overlay"]["gated"]
    seg = row["seg_pf"]
    seg_vals = [float(v) for v in seg.values() if not math.isnan(float(v))]
    seg_floor = min(seg_vals) if seg_vals else 0.0
    return (
        _safe_float(gated.get("pf"), 0.0) * 110.0
        + _safe_float(gated.get("ret"), -1.0) * 65.0
        - abs(_safe_float(gated.get("maxdd"), 1.0)) * 70.0
        + min(int(gated.get("trades", 0) or 0), 260) * 0.18
        + seg_floor * 10.0
    )


def _mainline_decision(row: dict[str, Any]) -> str:
    gated = row["best_overlay"]["gated"]
    pf = _safe_float(gated.get("pf"), 0.0)
    ret = _safe_float(gated.get("ret"), -1.0)
    maxdd = abs(_safe_float(gated.get("maxdd"), 1.0))
    trades = int(gated.get("trades", 0) or 0)
    seg_floor = min([float(v) for v in row["seg_pf"].values() if not math.isnan(float(v))] or [0.0])
    if pf >= 1.10 and ret > 0 and maxdd <= 0.40 and trades >= 160 and seg_floor >= 0.85:
        return "继续深挖"
    if pf >= 0.90 and trades >= 140:
        return "保留观察"
    if trades > 0:
        return "继续研究"
    return "淘汰"


def _run_mainline(root: Path, base_cfg: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    cfg = copy.deepcopy(base_cfg)
    cfg.setdefault("data", {})["symbols"] = ["btc", "bnb"]
    cfg.setdefault("data", {})["weights"] = {"btc": 0.015, "bnb": 0.985}
    for path, value in item.get("mods", {}).items():
        _set_nested(cfg, path, value)
    data = _load_multi_data(root, cfg, ["btc", "bnb"])
    _, trades, _ = run_backtest_portfolio(data, cfg)
    base = _trade_metrics_from_df(trades)
    best, gated_df = _overlay_bundle(root, trades)
    row = {
        "name": item["name"],
        "note": item.get("note", ""),
        "base": base,
        "best_overlay": best,
        "gated_long": _side_metrics(gated_df, "LONG"),
        "gated_short": _side_metrics(gated_df, "SHORT"),
        "active_months": _active_months(trades),
        "seg_pf": _segment_pfs(gated_df if gated_df is not None and not gated_df.empty else trades),
        "mods": item.get("mods", {}),
    }
    row["decision"] = _mainline_decision(row)
    row["score"] = _mainline_score(row)
    return row


def _branch_items() -> list[dict[str, Any]]:
    all_items = {item["name"]: item for item in list(QUICK_CANDIDATES) + list(FULL_EXTRA_CANDIDATES)}
    names = [
        "eth_fast_trend_4h",
        "eth_fast_trend_4h_lb16",
        "eth_shortwave_sr",
        "eth_shortwave_sr_tight",
        "eth_hybrid_mr",
        "sol_fast_trend_4h",
        "sol_fast_trend_4h_lb16",
        "sol_shortwave_sr",
        "sol_shortwave_sr_tight",
        "sol_shortwave_sr_mid",
        "sol_shortwave_sr_smooth",
        "sol_hybrid_mr",
    ]
    return [copy.deepcopy(all_items[n]) for n in names if n in all_items]


def _branch_score(row: dict[str, Any]) -> float:
    gated = row["best_overlay"]["gated"]
    score = _safe_float(gated.get("pf"), 0.0) * 115.0 + _safe_float(gated.get("ret"), -1.0) * 70.0 - abs(_safe_float(gated.get("maxdd"), 1.0)) * 70.0 + min(int(gated.get("trades", 0) or 0), 180) * 0.20
    if row["bias"] == "双边有效":
        score += 12.0
    elif row["bias"] in {"偏多", "偏空"}:
        score += 3.0
    if row["gated_long"].get("trades", 0) >= 8 and _safe_float(row["gated_long"].get("pf"), 0.0) >= 1.0:
        score += 8.0
    if row["gated_short"].get("trades", 0) >= 8 and _safe_float(row["gated_short"].get("pf"), 0.0) >= 1.0:
        score += 8.0
    return float(score)


def _branch_decision(row: dict[str, Any]) -> str:
    gated = row["best_overlay"]["gated"]
    pf = _safe_float(gated.get("pf"), 0.0)
    ret = _safe_float(gated.get("ret"), -1.0)
    maxdd = abs(_safe_float(gated.get("maxdd"), 1.0))
    trades = int(gated.get("trades", 0) or 0)
    long_ok = row["gated_long"].get("trades", 0) >= 8 and _safe_float(row["gated_long"].get("pf"), 0.0) >= 1.0
    short_ok = row["gated_short"].get("trades", 0) >= 8 and _safe_float(row["gated_short"].get("pf"), 0.0) >= 1.0
    if pf >= 1.0 and ret > 0 and maxdd <= 0.40 and trades >= 35 and (long_ok or short_ok):
        return "继续深挖"
    if pf >= 0.80 and trades >= 25:
        return "保留观察"
    if trades > 0:
        return "继续研究"
    return "淘汰"


def _run_branch(root: Path, base_cfg: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    symbol = str(item["symbol"])
    cfg = copy.deepcopy(base_cfg)
    cfg.setdefault("data", {})["symbols"] = [symbol]
    cfg.setdefault("data", {})["weights"] = {symbol: 1.0}
    _set_nested(cfg, "strategy_params.short_symbols", [symbol])
    _set_nested(cfg, "filters.macro_gate_symbols", [symbol])
    _set_nested(cfg, "filters.macro_gate_reference_symbol", symbol)
    for path, value in item.get("mods", {}).items():
        _set_nested(cfg, path, value)
    data = _load_symbol_data(root, cfg, symbol)
    _, trades, _ = run_backtest_portfolio(data, cfg)
    best, gated_df = _overlay_bundle(root, trades)
    row = {
        "name": item["name"],
        "symbol": symbol,
        "note": item.get("note", ""),
        "base": _trade_metrics_from_df(trades),
        "best_overlay": best,
        "gated_long": _side_metrics(gated_df, "LONG"),
        "gated_short": _side_metrics(gated_df, "SHORT"),
        "mods": item.get("mods", {}),
    }
    row["bias"] = _bias_label(row["gated_long"], row["gated_short"])
    row["decision"] = _branch_decision(row)
    row["score"] = _branch_score(row)
    return row


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage54 full-angle lab: mainline frequency + ETH/SOL broad branch map")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    cfg = read_config(root / "config.yml")
    reports = root / "reports" / "research_raw"
    reports.mkdir(parents=True, exist_ok=True)

    main_rows = [_run_mainline(root, cfg, item) for item in MAINLINE_CANDIDATES]
    main_rows = sorted(main_rows, key=lambda r: (r["decision"] == "继续深挖", r["decision"] == "保留观察", r["score"]), reverse=True)
    best_main = main_rows[0] if main_rows else None

    branch_rows = [_run_branch(root, cfg, item) for item in _branch_items()]
    branch_rows = sorted(branch_rows, key=lambda r: (r["decision"] == "继续深挖", r["decision"] == "保留观察", r["score"]), reverse=True)
    best_by_symbol: dict[str, dict[str, Any]] = {}
    for row in branch_rows:
        best_by_symbol.setdefault(str(row["symbol"]), row)

    main_txt = reports / "stage54_mainline_angle_latest.txt"
    main_json = reports / "stage54_mainline_angle_latest.json"
    branch_txt = reports / "stage54_branch_broad_map_latest.txt"
    branch_json = reports / "stage54_branch_broad_map_latest.json"

    ml_lines: list[str] = []
    ml_lines.append("Stage54 主线提频 + 消息面 risk overlay 研究")
    ml_lines.append(f"version: {cfg.get('system', {}).get('version', 'NA')}")
    ml_lines.append("")
    ml_lines.append("=== 候选结果 ===")
    for row in main_rows:
        base = row["base"]
        gated = row["best_overlay"]["gated"]
        ml_lines.append(
            f"- {row['name']}: base_trades={base.get('trades', 0)} -> gated_trades={gated.get('trades', 0)} | base_pf={_safe_float(base.get('pf'), float('nan')):.3f} -> gated_pf={_safe_float(gated.get('pf'), float('nan')):.3f} | gated_ret={_fmt_pct(gated.get('ret'))} | gated_maxDD={_fmt_pct(gated.get('maxdd'))} | active_months={row['active_months']} | overlay={row['best_overlay'].get('variant')} | score={row['score']:+.2f} | decision={row['decision']}"
        )
        ml_lines.append(
            f"  long_leg: trades={row['gated_long']['trades']} pf={_safe_float(row['gated_long'].get('pf'), float('nan')):.3f} | short_leg: trades={row['gated_short']['trades']} pf={_safe_float(row['gated_short'].get('pf'), float('nan')):.3f}"
        )
    ml_lines.append("")
    ml_lines.append("=== 结论 ===")
    ml_lines.append("- 主线提频不暂停；本轮继续在主线上同时评估技术面提频与消息面 risk overlay。")
    if best_main is not None:
        bg = best_main["best_overlay"]["gated"]
        ml_lines.append(
            f"- 当前主线第一候选：{best_main['name']} | trades={bg.get('trades', 0)} | gated_pf={_safe_float(bg.get('pf'), float('nan')):.3f} | gated_ret={_fmt_pct(bg.get('ret'))} | decision={best_main['decision']}"
        )
    ml_lines.append("- 消息面继续只做 risk overlay；主线是否升版，取决于频率提升后 PF / MaxDD 是否仍守住底线。")
    main_txt.write_text("\n".join(ml_lines).rstrip() + "\n", encoding="utf-8")
    main_json.write_text(json.dumps({"rows": main_rows, "best": best_main}, ensure_ascii=False, indent=2), encoding="utf-8")

    br_lines: list[str] = []
    br_lines.append("Stage54 ETH + SOL 分支广角图谱")
    br_lines.append(f"version: {cfg.get('system', {}).get('version', 'NA')}")
    br_lines.append("")
    br_lines.append("=== 各标的当前最优 ===")
    for sym in ["eth", "sol"]:
        row = best_by_symbol.get(sym)
        if row is None:
            continue
        gated = row["best_overlay"]["gated"]
        br_lines.append(
            f"- {sym}: {row['name']} | bias={row['bias']} | overlay={row['best_overlay'].get('variant')} | trades={gated.get('trades', 0)} | gated_pf={_safe_float(gated.get('pf'), float('nan')):.3f} | gated_ret={_fmt_pct(gated.get('ret'))} | gated_maxDD={_fmt_pct(gated.get('maxdd'))} | decision={row['decision']}"
        )
        br_lines.append(
            f"  long_leg: trades={row['gated_long']['trades']} pf={_safe_float(row['gated_long'].get('pf'), float('nan')):.3f} ret={_fmt_pct(row['gated_long'].get('ret'))} | short_leg: trades={row['gated_short']['trades']} pf={_safe_float(row['gated_short'].get('pf'), float('nan')):.3f} ret={_fmt_pct(row['gated_short'].get('ret'))}"
        )
    br_lines.append("")
    br_lines.append("=== 全部候选 ===")
    for row in branch_rows:
        gated = row["best_overlay"]["gated"]
        br_lines.append(
            f"- {row['name']}: symbol={row['symbol']} | bias={row['bias']} | gated_pf={_safe_float(gated.get('pf'), float('nan')):.3f} | gated_ret={_fmt_pct(gated.get('ret'))} | gated_maxDD={_fmt_pct(gated.get('maxdd'))} | trades={gated.get('trades', 0)} | overlay={row['best_overlay'].get('variant')} | score={row['score']:+.2f} | decision={row['decision']}"
        )
        br_lines.append(
            f"  long_leg: trades={row['gated_long']['trades']} pf={_safe_float(row['gated_long'].get('pf'), float('nan')):.3f} | short_leg: trades={row['gated_short']['trades']} pf={_safe_float(row['gated_short'].get('pf'), float('nan')):.3f}"
        )
    br_lines.append("")
    br_lines.append("=== 结论 ===")
    br_lines.append("- 不再先验砍掉 ETH / SOL 任一方向；先看双边拆解，再决定是否拆成独立 long engine / short engine。")
    br_lines.append("- 消息面继续只做 risk overlay，不直接升 alpha。")
    branch_txt.write_text("\n".join(br_lines).rstrip() + "\n", encoding="utf-8")
    branch_json.write_text(json.dumps({"rows": branch_rows, "best_by_symbol": best_by_symbol}, ensure_ascii=False, indent=2), encoding="utf-8")

    print(main_txt)
    print(branch_txt)


if __name__ == "__main__":
    main()
