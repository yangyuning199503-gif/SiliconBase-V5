from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in (None, ""):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest.engine import run_backtest_portfolio
from src.backtest.io import load_ohlcv_csv, read_config


def _set_nested(cfg: dict[str, Any], path: str, value: Any) -> None:
    cur: dict[str, Any] = cfg
    keys = path.split(".")
    for key in keys[:-1]:
        nxt = cur.get(key)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[key] = nxt
        cur = nxt
    cur[keys[-1]] = value


def _pct(x: Any) -> str:
    try:
        return f"{float(x) * 100:.2f}%"
    except Exception:
        return "NA"


def _pf_from_trades(trades: pd.DataFrame) -> float:
    if trades is None or trades.empty:
        return 0.0
    pnl = pd.to_numeric(trades["pnl"], errors="coerce").fillna(0.0)
    gp = float(pnl[pnl > 0].sum())
    gl = float(-pnl[pnl < 0].sum())
    if gl <= 0:
        return 999.0 if gp > 0 else 0.0
    return gp / gl


def _monthly_stats(trades: pd.DataFrame, initial_equity: float) -> dict[str, Any]:
    blank = {
        "active_months": 0,
        "monthly_mean": 0.0,
        "monthly_median": 0.0,
        "monthly_p75": 0.0,
        "months_ge_20": 0,
        "months_ge_10": 0,
        "best_month": 0.0,
        "worst_month": 0.0,
    }
    if trades is None or trades.empty:
        return blank
    df = trades.copy()
    df["exit_time"] = pd.to_datetime(df["exit_time"], errors="coerce")
    df = df.dropna(subset=["exit_time"])
    if df.empty:
        return blank
    monthly_pnl = df.groupby(df["exit_time"].dt.to_period("M"))["pnl"].sum().sort_index()
    monthly_ret = monthly_pnl / float(initial_equity)
    return {
        "active_months": int(monthly_ret.index.nunique()),
        "monthly_mean": float(monthly_ret.mean()) if not monthly_ret.empty else 0.0,
        "monthly_median": float(monthly_ret.median()) if not monthly_ret.empty else 0.0,
        "monthly_p75": float(monthly_ret.quantile(0.75)) if not monthly_ret.empty else 0.0,
        "months_ge_20": int((monthly_ret >= 0.20).sum()),
        "months_ge_10": int((monthly_ret >= 0.10).sum()),
        "best_month": float(monthly_ret.max()) if not monthly_ret.empty else 0.0,
        "worst_month": float(monthly_ret.min()) if not monthly_ret.empty else 0.0,
    }


def _segment_pf(trades: pd.DataFrame, start_year: int, end_year: int) -> float:
    if trades is None or trades.empty:
        return 0.0
    df = trades.copy()
    df["exit_time"] = pd.to_datetime(df["exit_time"], errors="coerce")
    df = df.dropna(subset=["exit_time"])
    seg = df[(df["exit_time"].dt.year >= start_year) & (df["exit_time"].dt.year <= end_year)]
    return _pf_from_trades(seg)


def _rolling_12m_pf_floor(trades: pd.DataFrame) -> float:
    if trades is None or trades.empty:
        return 0.0
    df = trades.copy()
    df["exit_time"] = pd.to_datetime(df["exit_time"], errors="coerce")
    df = df.dropna(subset=["exit_time"])
    if df.empty:
        return 0.0
    months = sorted(df["exit_time"].dt.to_period("M").unique())
    if len(months) < 6:
        return float(_pf_from_trades(df))
    floors: list[float] = []
    for i in range(max(1, len(months) - 11)):
        chosen = set(months[i:i + 12])
        sub = df[df["exit_time"].dt.to_period("M").isin(chosen)]
        if len(sub) >= 4:
            floors.append(float(_pf_from_trades(sub)))
    return min(floors) if floors else float(_pf_from_trades(df))


def _metrics(eq: pd.DataFrame, trades: pd.DataFrame, initial_equity: float) -> dict[str, Any]:
    if eq is None or eq.empty:
        return {
            "trades": 0,
            "pf": 0.0,
            "ret": 0.0,
            "maxdd": 0.0,
            "win_rate": 0.0,
            "monthly": _monthly_stats(pd.DataFrame(), initial_equity),
            "counts": {},
            "seg_pf": {"2020_2021": 0.0, "2022_2023": 0.0, "2024_2026": 0.0},
            "rolling12_pf_floor": 0.0,
        }
    pnl = pd.to_numeric(trades["pnl"], errors="coerce").fillna(0.0) if trades is not None and not trades.empty else pd.Series(dtype=float)
    peak = eq["equity"].cummax()
    dd = eq["equity"] / peak - 1.0
    counts = {}
    if trades is not None and not trades.empty:
        counts = {f"{k[0]}_{k[1]}": int(v) for k, v in trades.groupby(["symbol", "side"]).size().to_dict().items()}
    return {
        "trades": int(len(trades)) if trades is not None else 0,
        "pf": float(_pf_from_trades(trades)),
        "ret": float(eq["equity"].iloc[-1] / float(initial_equity) - 1.0),
        "maxdd": float(dd.min()) if len(dd) else 0.0,
        "win_rate": float((pnl > 0).mean()) if len(pnl) else 0.0,
        "monthly": _monthly_stats(trades, initial_equity),
        "counts": counts,
        "seg_pf": {
            "2020_2021": float(_segment_pf(trades, 2020, 2021)),
            "2022_2023": float(_segment_pf(trades, 2022, 2023)),
            "2024_2026": float(_segment_pf(trades, 2024, 2026)),
        },
        "rolling12_pf_floor": float(_rolling_12m_pf_floor(trades)),
    }


def _load_portfolio_data(root: Path, cfg: dict[str, Any], start: str = "", end: str = "") -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    data_cfg = cfg.get("data", {})
    start_ts = pd.to_datetime(start, utc=True).tz_convert(None) if start else (pd.to_datetime(data_cfg.get("start"), utc=True).tz_convert(None) if data_cfg.get("start") else None)
    end_ts = pd.to_datetime(end, utc=True).tz_convert(None) if end else (pd.to_datetime(data_cfg.get("end"), utc=True).tz_convert(None) if data_cfg.get("end") else None)
    template = str(data_cfg.get("csv_template", "data/raw/{symbol}_15m.csv"))
    for symbol in data_cfg.get("symbols", []):
        path = root / template.format(symbol=symbol)
        df = load_ohlcv_csv(path)
        if start_ts is not None:
            df = df.loc[df.index >= start_ts]
        if end_ts is not None:
            df = df.loc[df.index <= end_ts]
        out[str(symbol)] = df
    return out


def _run_portfolio_variant(root: Path, base_cfg: dict[str, Any], data: dict[str, pd.DataFrame], name: str, mods: dict[str, Any]) -> dict[str, Any]:
    cfg = copy.deepcopy(base_cfg)
    for path, value in mods.items():
        _set_nested(cfg, path, value)
    eq, trades, _ = run_backtest_portfolio(data, cfg)
    m = _metrics(eq, trades, float(cfg.get("portfolio", {}).get("initial_equity", 100000.0)))
    m["name"] = name
    m["mods"] = mods
    return m


def _run_symbol_variant(root: Path, base_cfg: dict[str, Any], symbol: str, name: str, mods: dict[str, Any], start: str = "", end: str = "") -> dict[str, Any]:
    cfg = copy.deepcopy(base_cfg)
    cfg.setdefault("data", {})["symbols"] = [symbol]
    cfg.setdefault("data", {})["weights"] = {symbol: 1.0}
    for path, value in mods.items():
        _set_nested(cfg, path, value)
    data = _load_portfolio_data(root, cfg, start=start, end=end)
    eq, trades, _ = run_backtest_portfolio(data, cfg)
    m = _metrics(eq, trades, float(cfg.get("portfolio", {}).get("initial_equity", 100000.0)))
    m["name"] = name
    m["symbol"] = symbol
    m["mods"] = mods
    return m


def _score_main(row: dict[str, Any], ref: dict[str, Any]) -> float:
    m = row.get("monthly", {}) or {}
    rm = ref.get("monthly", {}) or {}
    trade_gain = max(0, int(row.get("trades", 0)) - int(ref.get("trades", 0)))
    active_gain = max(0, int(m.get("active_months", 0)) - int(rm.get("active_months", 0)))
    months20_gain = max(0, int(m.get("months_ge_20", 0)) - int(rm.get("months_ge_20", 0)))
    pf_pen = max(0.0, float(ref.get("pf", 0.0)) - float(row.get("pf", 0.0)))
    dd_pen = max(0.0, abs(float(row.get("maxdd", 0.0))) - abs(float(ref.get("maxdd", 0.0))))
    ret_pen = max(0.0, float(ref.get("ret", 0.0)) - float(row.get("ret", 0.0)))
    seg_pen = 0.0
    for k in ["2020_2021", "2022_2023", "2024_2026"]:
        seg_pen += max(0.0, float(ref.get("seg_pf", {}).get(k, 0.0)) - float(row.get("seg_pf", {}).get(k, 0.0)))
    floor_bonus = min(float(row.get("rolling12_pf_floor", 0.0)), 2.0) * 9.0
    return float(trade_gain * 1.20 + active_gain * 1.50 + months20_gain * 2.0 - pf_pen * 70.0 - dd_pen * 180.0 - ret_pen * 7.0 - seg_pen * 10.0 + floor_bonus)


def _score_branch(row: dict[str, Any]) -> float:
    m = row.get("monthly", {}) or {}
    return float(
        row.get("pf", 0.0) * 95.0
        + row.get("ret", 0.0) * 35.0
        - abs(row.get("maxdd", 0.0)) * 85.0
        + row.get("trades", 0) * 0.25
        + m.get("months_ge_20", 0) * 6.0
        + m.get("monthly_p75", 0.0) * 22.0
        + min(row.get("rolling12_pf_floor", 0.0), 2.0) * 8.0
    )


def _gate_main(row: dict[str, Any], ref: dict[str, Any]) -> str:
    if row["name"] == ref["name"]:
        return "ref"
    if row.get("trades", 0) >= ref.get("trades", 0) and row.get("pf", 0.0) >= max(2.00, ref.get("pf", 0.0) - 0.22) and row.get("ret", 0.0) >= ref.get("ret", 0.0) * 0.93 and abs(row.get("maxdd", 0.0)) <= abs(ref.get("maxdd", 0.0)) + 0.04 and row.get("rolling12_pf_floor", 0.0) >= 1.00:
        return "pass"
    if row.get("trades", 0) > ref.get("trades", 0) and row.get("pf", 0.0) >= 1.90 and row.get("rolling12_pf_floor", 0.0) >= 0.90:
        return "hold"
    return "kill"


def _gate_branch(row: dict[str, Any]) -> str:
    if row.get("pf", 0.0) >= 1.05 and row.get("rolling12_pf_floor", 0.0) >= 0.95 and abs(row.get("maxdd", 0.0)) <= 0.35:
        return "pass"
    if row.get("pf", 0.0) >= 0.95 and row.get("trades", 0) >= 15:
        return "hold"
    return "kill"


REF_MAIN_MODS: dict[str, Any] = {
    "sr_entries.enabled": True,
    "sr_entries.symbols": ["bnb"],
    "sr_entries.lookback_4h": 30,
    "sr_entries.zone_atr_mult": 0.30,
    "sr_entries.use_adx_filter": True,
    "sr_entries.adx_min": 0.0,
    "sr_entries.adx_max": 22.0,
    "sr_entries.stake_scale": 0.15,
    "sr_entries.cooldown_bars": 8,
    "sr_entries.require_compress_ok": True,
    "filters.btc_short_pullback_atr": 0.90,
    "filters.btc_short_macro_tf": "4h",
}

MAINLINE_VARIANTS: list[tuple[str, dict[str, Any]]] = [
    ("combo_sr_soft_ref", REF_MAIN_MODS),
    ("combo_sr_soft_adx24", {**REF_MAIN_MODS, "sr_entries.adx_max": 24.0}),
    ("combo_sr_soft_adx26", {**REF_MAIN_MODS, "sr_entries.adx_max": 26.0}),
    ("combo_sr_soft_adx24_cd6", {**REF_MAIN_MODS, "sr_entries.adx_max": 24.0, "sr_entries.cooldown_bars": 6}),
    ("combo_sr_soft_adx26_cd6", {**REF_MAIN_MODS, "sr_entries.adx_max": 26.0, "sr_entries.cooldown_bars": 6}),
    ("combo_sr_soft_adx24_zone028", {**REF_MAIN_MODS, "sr_entries.adx_max": 24.0, "sr_entries.zone_atr_mult": 0.28}),
    ("combo_sr_soft_adx26_zone028", {**REF_MAIN_MODS, "sr_entries.adx_max": 26.0, "sr_entries.zone_atr_mult": 0.28}),
    ("combo_sr_soft_aggr_balanced", {**REF_MAIN_MODS, "sr_entries.adx_max": 24.0, "sr_entries.zone_atr_mult": 0.28, "sr_entries.cooldown_bars": 6, "sr_entries.stake_scale": 0.18, "filters.btc_short_pullback_atr": 0.95}),
    ("combo_sr_soft_aggr_fire", {**REF_MAIN_MODS, "sr_entries.adx_max": 26.0, "sr_entries.zone_atr_mult": 0.25, "sr_entries.cooldown_bars": 4, "sr_entries.stake_scale": 0.20, "filters.btc_short_pullback_atr": 1.00}),
]

BRANCH_VARIANTS: list[tuple[str, str, dict[str, Any]]] = [
    ("sol", "sol_long_core_ref", {
        "strategy_params.allow_short": False,
        "strategy_params.long_symbols": ["sol"],
        "strategy_params.short_symbols": [],
        "mean_reversion.enabled": False,
        "filters.adx_floor": 99,
        "strategy_params.breakout_atr_buffer": 9.0,
        "strategy_params.cooldown_bars": 8,
        "sr_entries.enabled": True,
        "sr_entries.symbols": ["sol"],
        "sr_entries.lookback_4h": 30,
        "sr_entries.zone_atr_mult": 0.30,
        "sr_entries.use_adx_filter": True,
        "sr_entries.adx_min": 0.0,
        "sr_entries.adx_max": 22.0,
        "sr_entries.stake_scale": 0.30,
        "sr_entries.cooldown_bars": 8,
        "sr_entries.require_compress_ok": True,
    }),
    ("sol", "sol_long_core_adx24", {
        "strategy_params.allow_short": False,
        "strategy_params.long_symbols": ["sol"],
        "strategy_params.short_symbols": [],
        "mean_reversion.enabled": False,
        "filters.adx_floor": 99,
        "strategy_params.breakout_atr_buffer": 9.0,
        "strategy_params.cooldown_bars": 8,
        "sr_entries.enabled": True,
        "sr_entries.symbols": ["sol"],
        "sr_entries.lookback_4h": 30,
        "sr_entries.zone_atr_mult": 0.30,
        "sr_entries.use_adx_filter": True,
        "sr_entries.adx_min": 0.0,
        "sr_entries.adx_max": 24.0,
        "sr_entries.stake_scale": 0.32,
        "sr_entries.cooldown_bars": 8,
        "sr_entries.require_compress_ok": True,
    }),
    ("sol", "sol_long_core_fast", {
        "strategy_params.allow_short": False,
        "strategy_params.long_symbols": ["sol"],
        "strategy_params.short_symbols": [],
        "mean_reversion.enabled": False,
        "filters.adx_floor": 99,
        "strategy_params.breakout_atr_buffer": 9.0,
        "strategy_params.cooldown_bars": 6,
        "sr_entries.enabled": True,
        "sr_entries.symbols": ["sol"],
        "sr_entries.lookback_4h": 24,
        "sr_entries.zone_atr_mult": 0.28,
        "sr_entries.use_adx_filter": True,
        "sr_entries.adx_min": 0.0,
        "sr_entries.adx_max": 24.0,
        "sr_entries.stake_scale": 0.35,
        "sr_entries.cooldown_bars": 6,
        "sr_entries.require_compress_ok": True,
    }),
    ("sol", "sol_long_core_fire", {
        "strategy_params.allow_short": False,
        "strategy_params.long_symbols": ["sol"],
        "strategy_params.short_symbols": [],
        "mean_reversion.enabled": False,
        "filters.adx_floor": 99,
        "strategy_params.breakout_atr_buffer": 9.0,
        "strategy_params.cooldown_bars": 4,
        "sr_entries.enabled": True,
        "sr_entries.symbols": ["sol"],
        "sr_entries.lookback_4h": 20,
        "sr_entries.zone_atr_mult": 0.25,
        "sr_entries.use_adx_filter": True,
        "sr_entries.adx_min": 0.0,
        "sr_entries.adx_max": 26.0,
        "sr_entries.stake_scale": 0.40,
        "sr_entries.cooldown_bars": 4,
        "sr_entries.require_compress_ok": True,
    }),
    ("sol", "sol_short_shock_b_ref", {
        "strategy_params.allow_short": True,
        "strategy_params.long_symbols": [],
        "strategy_params.short_symbols": ["sol"],
        "mean_reversion.enabled": False,
        "sr_entries.enabled": False,
        "strategy_params.cooldown_bars": 8,
        "strategy_params.breakout_lookback": 24,
        "strategy_params.breakout_atr_buffer": 1.0,
        "filters.adx_floor": 30,
        "filters.macro_gate_symbols": ["sol"],
        "filters.macro_gate_reference_symbol": "btc",
        "filters.macro_gate_tf_by_symbol.sol": "1d",
        "money_management.stake_scale.sol_short": 0.70,
    }),
    ("sol", "sol_short_shock_c_ref", {
        "strategy_params.allow_short": True,
        "strategy_params.long_symbols": [],
        "strategy_params.short_symbols": ["sol"],
        "mean_reversion.enabled": False,
        "sr_entries.enabled": False,
        "strategy_params.cooldown_bars": 10,
        "strategy_params.breakout_lookback": 20,
        "strategy_params.breakout_atr_buffer": 1.10,
        "filters.adx_floor": 32,
        "filters.macro_gate_symbols": ["sol"],
        "filters.macro_gate_reference_symbol": "btc",
        "filters.macro_gate_tf_by_symbol.sol": "1d",
        "money_management.stake_scale.sol_short": 0.60,
    }),
    ("sol", "sol_short_shock_fast", {
        "strategy_params.allow_short": True,
        "strategy_params.long_symbols": [],
        "strategy_params.short_symbols": ["sol"],
        "mean_reversion.enabled": False,
        "sr_entries.enabled": False,
        "strategy_params.cooldown_bars": 6,
        "strategy_params.breakout_lookback": 18,
        "strategy_params.breakout_atr_buffer": 0.90,
        "filters.adx_floor": 28,
        "filters.macro_gate_symbols": ["sol"],
        "filters.macro_gate_reference_symbol": "btc",
        "filters.macro_gate_tf_by_symbol.sol": "4h",
        "money_management.stake_scale.sol_short": 0.45,
    }),
    ("sol", "sol_short_shock_mid", {
        "strategy_params.allow_short": True,
        "strategy_params.long_symbols": [],
        "strategy_params.short_symbols": ["sol"],
        "mean_reversion.enabled": False,
        "sr_entries.enabled": False,
        "strategy_params.cooldown_bars": 8,
        "strategy_params.breakout_lookback": 20,
        "strategy_params.breakout_atr_buffer": 1.00,
        "filters.adx_floor": 30,
        "filters.macro_gate_symbols": ["sol"],
        "filters.macro_gate_reference_symbol": "btc",
        "filters.macro_gate_tf_by_symbol.sol": "4h",
        "money_management.stake_scale.sol_short": 0.50,
    }),
    ("sol", "sol_core_plus_shock_micro", {
        "strategy_params.allow_short": True,
        "strategy_params.long_symbols": ["sol"],
        "strategy_params.short_symbols": ["sol"],
        "mean_reversion.enabled": False,
        "strategy_params.cooldown_bars": 8,
        "strategy_params.breakout_lookback": 20,
        "strategy_params.breakout_atr_buffer": 1.05,
        "filters.adx_floor": 30,
        "filters.macro_gate_symbols": ["sol"],
        "filters.macro_gate_reference_symbol": "btc",
        "filters.macro_gate_tf_by_symbol.sol": "1d",
        "money_management.stake_scale.sol_short": 0.15,
        "sr_entries.enabled": True,
        "sr_entries.symbols": ["sol"],
        "sr_entries.lookback_4h": 24,
        "sr_entries.zone_atr_mult": 0.28,
        "sr_entries.use_adx_filter": True,
        "sr_entries.adx_min": 0.0,
        "sr_entries.adx_max": 24.0,
        "sr_entries.stake_scale": 0.30,
        "sr_entries.cooldown_bars": 6,
        "sr_entries.require_compress_ok": True,
    }),
]


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage46 aggressive-first lab")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--txt-out", default="")
    ap.add_argument("--json-out", default="")
    ap.add_argument("--start", default="")
    ap.add_argument("--end", default="")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    cfg = read_config(root / "config.yml")
    reports_raw = root / "reports" / "research_raw"
    txt_out = Path(args.txt_out).expanduser().resolve() if args.txt_out else reports_raw / "stage46_aggressive_lab_latest.txt"
    json_out = Path(args.json_out).expanduser().resolve() if args.json_out else reports_raw / "stage46_aggressive_lab_latest.json"

    portfolio_cfg = copy.deepcopy(cfg)
    portfolio_cfg.setdefault("data", {})["symbols"] = ["btc", "bnb"]
    portfolio_data = _load_portfolio_data(root, portfolio_cfg, start=args.start, end=args.end)

    main_rows: list[dict[str, Any]] = []
    for name, mods in MAINLINE_VARIANTS:
        row = _run_portfolio_variant(root, portfolio_cfg, portfolio_data, name, mods)
        main_rows.append(row)
    ref_main = next((r for r in main_rows if r["name"] == "combo_sr_soft_ref"), main_rows[0])
    for row in main_rows:
        row["score"] = _score_main(row, ref_main)
        row["gate"] = _gate_main(row, ref_main)
    main_sorted = sorted(main_rows, key=lambda r: (r["gate"] == "pass", r["gate"] == "hold", r["score"], r["pf"], r["ret"]), reverse=True)
    best_main = next((r for r in main_sorted if r["gate"] in {"pass", "hold"} and r["name"] != ref_main["name"]), ref_main)

    branch_rows: list[dict[str, Any]] = []
    for symbol, name, mods in BRANCH_VARIANTS:
        row = _run_symbol_variant(root, cfg, symbol, name, mods, start=args.start, end=args.end)
        row["score"] = _score_branch(row)
        row["gate"] = _gate_branch(row)
        branch_rows.append(row)
    branch_sorted = sorted(branch_rows, key=lambda r: (r["gate"] == "pass", r["gate"] == "hold", r["score"], r["pf"], r["ret"]), reverse=True)
    best_branch = next((r for r in branch_sorted if r["gate"] in {"pass", "hold"}), branch_sorted[0] if branch_sorted else None)

    lines: list[str] = []
    lines.append("Stage46 激进优先实验（先提速，再回头保守微调）")
    lines.append(f"version: {cfg.get('system', {}).get('version', 'NA')}")
    if args.start or args.end:
        lines.append(f"range: {args.start or '-'} -> {args.end or '-'}")
    lines.append("")
    lines.append("=== 主线 ===")
    for row in main_sorted:
        m = row.get("monthly", {}) or {}
        lines.append(
            f"- {row['name']}: gate={row['gate']} | trades={row['trades']} | pf={row['pf']:.3f} | ret={_pct(row['ret'])} | maxDD={_pct(row['maxdd'])} | active_months={m.get('active_months',0)} | months>=20%={m.get('months_ge_20',0)} | roll12_pf_floor={row.get('rolling12_pf_floor',0.0):.3f} | score={row['score']:+.2f}"
        )
        lines.append(
            f"  seg_pf=2020-2021:{row['seg_pf']['2020_2021']:.3f} / 2022-2023:{row['seg_pf']['2022_2023']:.3f} / 2024-2026:{row['seg_pf']['2024_2026']:.3f} | counts={json.dumps(row.get('counts', {}), ensure_ascii=False)}"
        )
    lines.append("")
    lines.append("=== 分支（SOL 优先） ===")
    for row in branch_sorted:
        m = row.get("monthly", {}) or {}
        lines.append(
            f"- {row['name']}: gate={row['gate']} | trades={row['trades']} | pf={row['pf']:.3f} | ret={_pct(row['ret'])} | maxDD={_pct(row['maxdd'])} | median_month={_pct(m.get('monthly_median',0.0))} | p75_month={_pct(m.get('monthly_p75',0.0))} | months>=20%={m.get('months_ge_20',0)} | roll12_pf_floor={row.get('rolling12_pf_floor',0.0):.3f} | score={row['score']:+.2f}"
        )
        lines.append(f"  counts={json.dumps(row.get('counts', {}), ensure_ascii=False)}")
    lines.append("")
    lines.append("=== 结论 ===")
    lines.append(f"- 主线先按激进优先推进：{best_main['name']}；保留 {ref_main['name']} 做回撤/过拟合对照。")
    if best_branch is not None:
        lines.append(f"- 分支当前优先继续：{best_branch['name']}。若 short 仍不过 gate，就只保留 long core。")
    lines.append("- ETH 继续降级为 overlay，不抢资源。")
    lines.append("- Polymarket 继续只做 regime prior / risk gate，不直接做 trigger。")
    lines.append("- 当前口径允许先激进，再回头保守微调；这轮仍只做 research，不改 live。")

    payload = {
        "system_version": cfg.get("system", {}).get("version", "NA"),
        "range": {"start": args.start, "end": args.end},
        "mode": "aggressive_first_then_tighten",
        "mainline": {"reference": ref_main, "best": best_main, "rows": main_sorted},
        "branch": {"best": best_branch, "rows": branch_sorted},
        "note": {
            "mainline_goal": "raise trade frequency first, tighten later",
            "branch_goal": "find SOL engine with better monthly bursts without breaking PF/DD",
            "eth_status": "overlay_only",
            "polymarket_role": "regime_prior_only",
        },
    }

    _write_text(txt_out, "\n".join(lines))
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
