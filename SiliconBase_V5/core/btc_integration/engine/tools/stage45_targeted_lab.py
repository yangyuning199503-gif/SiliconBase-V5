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

# ---------- helpers ----------

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


def _load_data(root: Path, cfg: dict[str, Any], symbols: list[str], start: str = "", end: str = "") -> dict[str, pd.DataFrame]:
    data_cfg = copy.deepcopy(cfg.get("data", {}) or {})
    template = str(data_cfg.get("csv_template", "data/raw/{symbol}_15m.csv"))
    start_ts = pd.to_datetime(start, utc=True).tz_convert(None) if start else None
    end_ts = pd.to_datetime(end, utc=True).tz_convert(None) if end else None
    out: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        p = root / template.format(symbol=symbol)
        df = load_ohlcv_csv(p)
        if start_ts is not None:
            df = df.loc[df.index >= start_ts]
        if end_ts is not None:
            df = df.loc[df.index <= end_ts]
        out[str(symbol)] = df
    return out


def _monthly_stats(trades: pd.DataFrame, initial_equity: float) -> dict[str, Any]:
    blank = {
        "active_months": 0,
        "months_ge_20": 0,
        "months_ge_10": 0,
        "monthly_median": 0.0,
        "monthly_p75": 0.0,
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
    m = df.groupby(df["exit_time"].dt.to_period("M"))["pnl"].sum().sort_index() / float(initial_equity)
    return {
        "active_months": int(m.index.nunique()),
        "months_ge_20": int((m >= 0.20).sum()),
        "months_ge_10": int((m >= 0.10).sum()),
        "monthly_median": float(m.median()) if not m.empty else 0.0,
        "monthly_p75": float(m.quantile(0.75)) if not m.empty else 0.0,
        "best_month": float(m.max()) if not m.empty else 0.0,
        "worst_month": float(m.min()) if not m.empty else 0.0,
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
    monthly = df.groupby(df["exit_time"].dt.to_period("M"))["pnl"].apply(list).sort_index()
    months = list(monthly.index)
    if len(months) < 6:
        return float(_pf_from_trades(df))
    floors: list[float] = []
    for i in range(max(1, len(months) - 11)):
        chosen = months[i:i + 12]
        sub = df[df["exit_time"].dt.to_period("M").isin(chosen)]
        if len(sub) >= 4:
            floors.append(float(_pf_from_trades(sub)))
    return min(floors) if floors else float(_pf_from_trades(df))


def _year_pf_map(trades: pd.DataFrame) -> dict[str, float]:
    if trades is None or trades.empty:
        return {}
    df = trades.copy()
    df["exit_time"] = pd.to_datetime(df["exit_time"], errors="coerce")
    df = df.dropna(subset=["exit_time"])
    out: dict[str, float] = {}
    for year, g in df.groupby(df["exit_time"].dt.year):
        out[str(int(year))] = float(_pf_from_trades(g))
    return out


def _metrics(eq: pd.DataFrame, trades: pd.DataFrame, initial_equity: float) -> dict[str, Any]:
    if eq is None or eq.empty:
        return {
            "trades": 0,
            "pf": 0.0,
            "ret": 0.0,
            "maxdd": 0.0,
            "monthly": _monthly_stats(pd.DataFrame(), initial_equity),
            "seg_pf": {},
            "year_pf": {},
            "rolling12_pf_floor": 0.0,
            "counts": {},
        }
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
        "monthly": _monthly_stats(trades, initial_equity),
        "seg_pf": {
            "2020_2021": float(_segment_pf(trades, 2020, 2021)),
            "2022_2023": float(_segment_pf(trades, 2022, 2023)),
            "2024_2026": float(_segment_pf(trades, 2024, 2026)),
        },
        "year_pf": _year_pf_map(trades),
        "rolling12_pf_floor": float(_rolling_12m_pf_floor(trades)),
        "counts": counts,
    }


def _run_variant(root: Path, base_cfg: dict[str, Any], name: str, mods: dict[str, Any], symbols: list[str], start: str, end: str) -> dict[str, Any]:
    cfg = copy.deepcopy(base_cfg)
    cfg.setdefault("data", {})["symbols"] = list(symbols)
    cfg.setdefault("data", {})["weights"] = {s: 1.0 / len(symbols) for s in symbols}
    try:
        for path, value in mods.items():
            _set_nested(cfg, path, value)
        data = _load_data(root, cfg, list(symbols), start, end)
        eq, trades, _ = run_backtest_portfolio(data, cfg)
        row = _metrics(eq, trades, float(cfg.get("portfolio", {}).get("initial_equity", 100000.0)))
        row["error"] = ""
    except Exception as e:
        row = {
            "trades": 0,
            "pf": 0.0,
            "ret": 0.0,
            "maxdd": 0.0,
            "monthly": _monthly_stats(pd.DataFrame(), float(cfg.get("portfolio", {}).get("initial_equity", 100000.0))),
            "seg_pf": {"2020_2021": 0.0, "2022_2023": 0.0, "2024_2026": 0.0},
            "year_pf": {},
            "rolling12_pf_floor": 0.0,
            "counts": {},
            "error": f"{type(e).__name__}: {e}",
        }
    row["name"] = name
    row["mods"] = mods
    row["symbols"] = symbols
    return row


def _score_main(row: dict[str, Any], ref: dict[str, Any]) -> float:
    m = row.get("monthly", {}) or {}
    rm = ref.get("monthly", {}) or {}
    trade_gain = max(0, int(row.get("trades", 0)) - int(ref.get("trades", 0)))
    active_gain = max(0, int(m.get("active_months", 0)) - int(rm.get("active_months", 0)))
    pf_pen = max(0.0, float(ref.get("pf", 0.0)) - float(row.get("pf", 0.0)))
    dd_pen = max(0.0, abs(float(row.get("maxdd", 0.0))) - abs(float(ref.get("maxdd", 0.0))))
    ret_pen = max(0.0, float(ref.get("ret", 0.0)) - float(row.get("ret", 0.0)))
    seg_pen = 0.0
    for k in ["2020_2021", "2022_2023", "2024_2026"]:
        seg_pen += max(0.0, float(ref.get("seg_pf", {}).get(k, 0.0)) - float(row.get("seg_pf", {}).get(k, 0.0)))
    floor_bonus = min(float(row.get("rolling12_pf_floor", 0.0)), 2.0) * 10.0
    return float(trade_gain * 1.15 + active_gain * 1.25 - pf_pen * 85.0 - dd_pen * 190.0 - ret_pen * 8.0 - seg_pen * 12.0 + floor_bonus)


def _score_branch(row: dict[str, Any]) -> float:
    m = row.get("monthly", {}) or {}
    return float(
        row.get("pf", 0.0) * 95.0
        + row.get("ret", 0.0) * 30.0
        - abs(row.get("maxdd", 0.0)) * 90.0
        + row.get("trades", 0) * 0.20
        + m.get("months_ge_20", 0) * 6.0
        + m.get("monthly_p75", 0.0) * 24.0
        + min(row.get("rolling12_pf_floor", 0.0), 2.0) * 10.0
    )


def _gate_main(row: dict[str, Any], ref: dict[str, Any]) -> str:
    if row["name"] == ref["name"]:
        return "ref"
    if row.get("pf", 0.0) >= max(1.90, ref.get("pf", 0.0) - 0.18) and row.get("rolling12_pf_floor", 0.0) >= 1.05 and row.get("ret", 0.0) >= ref.get("ret", 0.0) * 0.92 and abs(row.get("maxdd", 0.0)) <= abs(ref.get("maxdd", 0.0)) + 0.03:
        return "pass"
    if row.get("trades", 0) > ref.get("trades", 0) and row.get("pf", 0.0) >= 1.80 and row.get("rolling12_pf_floor", 0.0) >= 0.95:
        return "hold"
    return "kill"


def _gate_branch(row: dict[str, Any]) -> str:
    if row.get("pf", 0.0) >= 1.05 and row.get("rolling12_pf_floor", 0.0) >= 1.0 and abs(row.get("maxdd", 0.0)) <= 0.35:
        return "pass"
    if row.get("pf", 0.0) >= 0.95 and row.get("trades", 0) >= 15:
        return "hold"
    return "kill"


# ---------- variants ----------

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
    (
        "combo_sr_soft_adx24",
        {
            **REF_MAIN_MODS,
            "sr_entries.adx_max": 24.0,
        },
    ),
    (
        "combo_sr_soft_adx24_cd6",
        {
            **REF_MAIN_MODS,
            "sr_entries.adx_max": 24.0,
            "sr_entries.cooldown_bars": 6,
        },
    ),
    (
        "combo_sr_soft_adx24_pb085",
        {
            **REF_MAIN_MODS,
            "sr_entries.adx_max": 24.0,
            "filters.btc_short_pullback_atr": 0.85,
        },
    ),
    (
        "combo_sr_soft_adx24_zone028",
        {
            **REF_MAIN_MODS,
            "sr_entries.adx_max": 24.0,
            "sr_entries.zone_atr_mult": 0.28,
        },
    ),
    (
        "combo_sr_soft_adx24_tripwire",
        {
            **REF_MAIN_MODS,
            "sr_entries.adx_max": 24.0,
            "sr_entries.cooldown_bars": 6,
            "filters.btc_short_pullback_atr": 0.85,
            "sr_entries.zone_atr_mult": 0.28,
        },
    ),
]

SOL_VARIANTS: list[tuple[str, dict[str, Any]]] = [
    (
        "sol_long_core_ref",
        {
            "strategy_params.allow_short": False,
            "strategy_params.long_symbols": ["sol"],
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
        },
    ),
    (
        "sol_short_shock_b_ref",
        {
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
        },
    ),
    (
        "sol_short_shock_c_ref",
        {
            "strategy_params.allow_short": True,
            "strategy_params.long_symbols": [],
            "strategy_params.short_symbols": ["sol"],
            "mean_reversion.enabled": False,
            "sr_entries.enabled": False,
            "strategy_params.cooldown_bars": 10,
            "strategy_params.breakout_lookback": 20,
            "strategy_params.breakout_atr_buffer": 1.1,
            "filters.adx_floor": 32,
            "filters.macro_gate_symbols": ["sol"],
            "filters.macro_gate_reference_symbol": "btc",
            "filters.macro_gate_tf_by_symbol.sol": "1d",
            "money_management.stake_scale.sol_short": 0.60,
        },
    ),
    (
        "sol_short_shock_b_4h_fast",
        {
            "strategy_params.allow_short": True,
            "strategy_params.long_symbols": [],
            "strategy_params.short_symbols": ["sol"],
            "mean_reversion.enabled": False,
            "sr_entries.enabled": False,
            "strategy_params.cooldown_bars": 6,
            "strategy_params.breakout_lookback": 22,
            "strategy_params.breakout_atr_buffer": 0.95,
            "filters.adx_floor": 30,
            "filters.macro_gate_symbols": ["sol"],
            "filters.macro_gate_reference_symbol": "btc",
            "filters.macro_gate_tf_by_symbol.sol": "4h",
            "money_management.stake_scale.sol_short": 0.55,
        },
    ),
    (
        "sol_short_shock_c_tight",
        {
            "strategy_params.allow_short": True,
            "strategy_params.long_symbols": [],
            "strategy_params.short_symbols": ["sol"],
            "mean_reversion.enabled": False,
            "sr_entries.enabled": False,
            "strategy_params.cooldown_bars": 10,
            "strategy_params.breakout_lookback": 22,
            "strategy_params.breakout_atr_buffer": 1.15,
            "filters.adx_floor": 34,
            "filters.macro_gate_symbols": ["sol"],
            "filters.macro_gate_reference_symbol": "btc",
            "filters.macro_gate_tf_by_symbol.sol": "1d",
            "money_management.stake_scale.sol_short": 0.50,
        },
    ),
    (
        "sol_combo_guarded",
        {
            "strategy_params.allow_short": True,
            "strategy_params.long_symbols": ["sol"],
            "strategy_params.short_symbols": ["sol"],
            "mean_reversion.enabled": False,
            "strategy_params.cooldown_bars": 10,
            "strategy_params.breakout_lookback": 22,
            "strategy_params.breakout_atr_buffer": 1.15,
            "filters.adx_floor": 34,
            "filters.macro_gate_symbols": ["sol"],
            "filters.macro_gate_reference_symbol": "btc",
            "filters.macro_gate_tf_by_symbol.sol": "1d",
            "money_management.stake_scale.sol_short": 0.25,
            "sr_entries.enabled": True,
            "sr_entries.symbols": ["sol"],
            "sr_entries.lookback_4h": 30,
            "sr_entries.zone_atr_mult": 0.30,
            "sr_entries.use_adx_filter": True,
            "sr_entries.adx_min": 0.0,
            "sr_entries.adx_max": 22.0,
            "sr_entries.stake_scale": 0.25,
            "sr_entries.cooldown_bars": 8,
            "sr_entries.require_compress_ok": True,
        },
    ),
]


def _write_txt(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage45 targeted refine lab")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--txt-out", default="")
    ap.add_argument("--json-out", default="")
    ap.add_argument("--start", default="")
    ap.add_argument("--end", default="")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    cfg = read_config(root / "config.yml")
    reports_raw = root / "reports" / "research_raw"
    txt_out = Path(args.txt_out).expanduser().resolve() if args.txt_out else reports_raw / "stage45_targeted_lab_latest.txt"
    json_out = Path(args.json_out).expanduser().resolve() if args.json_out else reports_raw / "stage45_targeted_lab_latest.json"

    main_rows: list[dict[str, Any]] = []
    for name, mods in MAINLINE_VARIANTS:
        row = _run_variant(root, cfg, name, mods, ["btc", "bnb"], args.start, args.end)
        main_rows.append(row)
    ref_main = next((r for r in main_rows if r["name"] == "combo_sr_soft_ref"), main_rows[0])
    for row in main_rows:
        row["score"] = _score_main(row, ref_main)
        row["gate"] = _gate_main(row, ref_main)
    main_sorted = sorted(main_rows, key=lambda r: (r["gate"] == "pass", r["gate"] == "hold", r["score"], r["pf"], r["ret"]), reverse=True)
    best_main = next((r for r in main_sorted if r["gate"] in {"pass", "hold"} and r["name"] != ref_main["name"]), ref_main)

    sol_rows: list[dict[str, Any]] = []
    for name, mods in SOL_VARIANTS:
        row = _run_variant(root, cfg, name, mods, ["sol"], args.start, args.end)
        row["score"] = _score_branch(row)
        row["gate"] = _gate_branch(row)
        sol_rows.append(row)
    sol_sorted = sorted(sol_rows, key=lambda r: (r["gate"] == "pass", r["gate"] == "hold", r["score"], r["pf"], r["ret"]), reverse=True)
    best_sol = next((r for r in sol_sorted if r["gate"] in {"pass", "hold"}), sol_sorted[0] if sol_sorted else None)

    lines: list[str] = []
    lines.append("Stage45 定向提频与 SOL shock 结构实验")
    lines.append(f"version: {cfg.get('system', {}).get('version', 'NA')}")
    if args.start or args.end:
        lines.append(f"range: {args.start or '-'} -> {args.end or '-'}")
    lines.append("")
    lines.append("=== 主线（参考=combo_sr_soft_ref）===")
    for row in main_sorted:
        m = row.get("monthly", {}) or {}
        lines.append(
            f"- {row['name']}: gate={row['gate']} | trades={row['trades']} | pf={row['pf']:.3f} | ret={_pct(row['ret'])} | maxDD={_pct(row['maxdd'])} | active_months={m.get('active_months',0)} | months>=20%={m.get('months_ge_20',0)} | roll12_pf_floor={row.get('rolling12_pf_floor',0.0):.3f} | score={row['score']:+.2f}"
        )
        lines.append(
            f"  seg_pf=2020-2021:{row['seg_pf']['2020_2021']:.3f} / 2022-2023:{row['seg_pf']['2022_2023']:.3f} / 2024-2026:{row['seg_pf']['2024_2026']:.3f} | counts={json.dumps(row.get('counts', {}), ensure_ascii=False)}"
        )
        if row.get("error"):
            lines.append(f"  error={row['error']}")
    lines.append("")
    lines.append("=== SOL（long core / short shock）===")
    for row in sol_sorted:
        m = row.get("monthly", {}) or {}
        lines.append(
            f"- {row['name']}: gate={row['gate']} | trades={row['trades']} | pf={row['pf']:.3f} | ret={_pct(row['ret'])} | maxDD={_pct(row['maxdd'])} | median_month={_pct(m.get('monthly_median',0.0))} | p75_month={_pct(m.get('monthly_p75',0.0))} | months>=20%={m.get('months_ge_20',0)} | roll12_pf_floor={row.get('rolling12_pf_floor',0.0):.3f} | score={row['score']:+.2f}"
        )
        lines.append(f"  counts={json.dumps(row.get('counts', {}), ensure_ascii=False)}")
        if row.get("error"):
            lines.append(f"  error={row['error']}")
    lines.append("")
    lines.append("=== 结论 ===")
    lines.append(f"- 主线第一研究候选：{best_main['name']}（参考线保留 {ref_main['name']}，live 暂不改）。")
    if best_sol is not None:
        lines.append(f"- SOL 当前继续推进：{best_sol['name']}。若 short 仍不过 gate，则保留 long core，不接 demo。")
    lines.append("- ETH 继续只保留 tactical overlay，不再做常驻分支。")
    lines.append("- Polymarket 继续只做 regime prior / risk gate，不做直接 trigger。")
    lines.append("- 分支月化 20% 仍视为挑战目标，不以牺牲 PF/DD 为代价硬冲。")

    payload = {
        "system_version": cfg.get("system", {}).get("version", "NA"),
        "range": {"start": args.start, "end": args.end},
        "mainline": {"reference": ref_main, "best": best_main, "rows": main_sorted},
        "sol": {"best": best_sol, "rows": sol_sorted},
        "note": {
            "target_branch_monthly": ">20% challenge, not hard gate",
            "target_mainline": "higher trade frequency with controlled PF/DD",
            "polymarket_role": "regime_prior_only",
            "eth_status": "overlay_only",
        },
    }

    _write_txt(txt_out, "\n".join(lines))
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
