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


def _load_portfolio_data(root: Path, cfg: dict[str, Any]) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    data_cfg = cfg.get("data", {})
    start = pd.to_datetime(data_cfg.get("start"), utc=True).tz_convert(None) if data_cfg.get("start") else None
    end = pd.to_datetime(data_cfg.get("end"), utc=True).tz_convert(None) if data_cfg.get("end") else None
    template = str(data_cfg.get("csv_template", "data/raw/{symbol}_15m.csv"))
    for symbol in data_cfg.get("symbols", []):
        path = root / template.format(symbol=symbol)
        df = load_ohlcv_csv(path)
        if start is not None:
            df = df.loc[df.index >= start]
        if end is not None:
            df = df.loc[df.index <= end]
        out[str(symbol)] = df
    return out


def _load_symbol_data(root: Path, cfg: dict[str, Any], symbol: str) -> dict[str, pd.DataFrame]:
    cfg2 = copy.deepcopy(cfg)
    cfg2.setdefault("data", {})["symbols"] = [symbol]
    cfg2.setdefault("data", {})["weights"] = {symbol: 1.0}
    return _load_portfolio_data(root, cfg2)


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
    if trades is None or trades.empty:
        return {
            "active_months": 0,
            "monthly_mean": 0.0,
            "monthly_median": 0.0,
            "monthly_p75": 0.0,
            "months_ge_20": 0,
            "months_ge_10": 0,
            "best_month": 0.0,
            "worst_month": 0.0,
        }
    df = trades.copy()
    df["exit_time"] = pd.to_datetime(df["exit_time"], errors="coerce")
    df = df.dropna(subset=["exit_time"])
    if df.empty:
        return {
            "active_months": 0,
            "monthly_mean": 0.0,
            "monthly_median": 0.0,
            "monthly_p75": 0.0,
            "months_ge_20": 0,
            "months_ge_10": 0,
            "best_month": 0.0,
            "worst_month": 0.0,
        }
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
    }


def _score_mainline(row: dict[str, Any], base: dict[str, Any]) -> float:
    trade_gain = max(0, int(row.get("trades", 0)) - int(base.get("trades", 0)))
    active_gain = max(0, int(row.get("monthly", {}).get("active_months", 0)) - int(base.get("monthly", {}).get("active_months", 0)))
    pf_pen = max(0.0, float(base.get("pf", 0.0)) - float(row.get("pf", 0.0)))
    dd_pen = max(0.0, abs(float(row.get("maxdd", 0.0))) - abs(float(base.get("maxdd", 0.0))))
    ret_pen = max(0.0, float(base.get("ret", 0.0)) - float(row.get("ret", 0.0)))
    seg_pen = 0.0
    for k in ["2020_2021", "2022_2023", "2024_2026"]:
        seg_pen += max(0.0, float(base.get("seg_pf", {}).get(k, 0.0)) - float(row.get("seg_pf", {}).get(k, 0.0)))
    return float(trade_gain * 1.10 + active_gain * 1.40 - pf_pen * 80.0 - dd_pen * 220.0 - ret_pen * 8.0 - seg_pen * 10.0)


def _score_branch(row: dict[str, Any]) -> float:
    monthly = row.get("monthly", {}) or {}
    return float(
        row.get("pf", 0.0) * 90.0
        + row.get("ret", 0.0) * 30.0
        - abs(row.get("maxdd", 0.0)) * 75.0
        + row.get("trades", 0) * 0.15
        + monthly.get("months_ge_20", 0) * 2.0
        + monthly.get("months_ge_10", 0) * 0.5
        + monthly.get("monthly_p75", 0.0) * 18.0
    )


def _run_portfolio_variant(root: Path, base_cfg: dict[str, Any], data: dict[str, pd.DataFrame], name: str, mods: dict[str, Any]) -> dict[str, Any]:
    cfg = copy.deepcopy(base_cfg)
    for path, value in mods.items():
        _set_nested(cfg, path, value)
    eq, trades, _ = run_backtest_portfolio(data, cfg)
    m = _metrics(eq, trades, float(cfg.get("portfolio", {}).get("initial_equity", 100000.0)))
    m["name"] = name
    m["mods"] = mods
    return m


def _run_symbol_variant(root: Path, base_cfg: dict[str, Any], symbol: str, name: str, mods: dict[str, Any]) -> dict[str, Any]:
    cfg = copy.deepcopy(base_cfg)
    cfg.setdefault("data", {})["symbols"] = [symbol]
    cfg.setdefault("data", {})["weights"] = {symbol: 1.0}
    _set_nested(cfg, "filters.macro_gate_symbols", [symbol])
    _set_nested(cfg, "filters.macro_gate_reference_symbol", symbol)
    for path, value in mods.items():
        _set_nested(cfg, path, value)
    data = _load_symbol_data(root, cfg, symbol)
    eq, trades, _ = run_backtest_portfolio(data, cfg)
    m = _metrics(eq, trades, float(cfg.get("portfolio", {}).get("initial_equity", 100000.0)))
    m["name"] = name
    m["symbol"] = symbol
    m["mods"] = mods
    return m


MAINLINE_VARIANTS: list[tuple[str, dict[str, Any]]] = [
    ("baseline", {}),
    (
        "combo_sr_soft",
        {
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
        },
    ),
    (
        "combo_sr_soft_pull1.0",
        {
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
            "filters.btc_short_pullback_atr": 1.00,
            "filters.btc_short_macro_tf": "4h",
        },
    ),
    (
        "combo_sr_soft_cd6",
        {
            "sr_entries.enabled": True,
            "sr_entries.symbols": ["bnb"],
            "sr_entries.lookback_4h": 30,
            "sr_entries.zone_atr_mult": 0.30,
            "sr_entries.use_adx_filter": True,
            "sr_entries.adx_min": 0.0,
            "sr_entries.adx_max": 22.0,
            "sr_entries.stake_scale": 0.15,
            "sr_entries.cooldown_bars": 6,
            "sr_entries.require_compress_ok": True,
            "filters.btc_short_pullback_atr": 0.90,
            "filters.btc_short_macro_tf": "4h",
        },
    ),
    (
        "combo_sr_soft_scale018",
        {
            "sr_entries.enabled": True,
            "sr_entries.symbols": ["bnb"],
            "sr_entries.lookback_4h": 30,
            "sr_entries.zone_atr_mult": 0.30,
            "sr_entries.use_adx_filter": True,
            "sr_entries.adx_min": 0.0,
            "sr_entries.adx_max": 22.0,
            "sr_entries.stake_scale": 0.18,
            "sr_entries.cooldown_bars": 8,
            "sr_entries.require_compress_ok": True,
            "filters.btc_short_pullback_atr": 0.90,
            "filters.btc_short_macro_tf": "4h",
        },
    ),
    (
        "combo_sr_soft_adx24",
        {
            "sr_entries.enabled": True,
            "sr_entries.symbols": ["bnb"],
            "sr_entries.lookback_4h": 30,
            "sr_entries.zone_atr_mult": 0.30,
            "sr_entries.use_adx_filter": True,
            "sr_entries.adx_min": 0.0,
            "sr_entries.adx_max": 24.0,
            "sr_entries.stake_scale": 0.15,
            "sr_entries.cooldown_bars": 8,
            "sr_entries.require_compress_ok": True,
            "filters.btc_short_pullback_atr": 0.90,
            "filters.btc_short_macro_tf": "4h",
        },
    ),
]


BRANCH_VARIANTS: list[tuple[str, str, dict[str, Any]]] = [
    (
        "sol",
        "sol_long_sr_soft",
        {
            "strategy_params.allow_short": False,
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
        "sol",
        "sol_long_sr_mid",
        {
            "strategy_params.allow_short": False,
            "mean_reversion.enabled": False,
            "filters.adx_floor": 99,
            "strategy_params.breakout_atr_buffer": 9.0,
            "strategy_params.cooldown_bars": 8,
            "sr_entries.enabled": True,
            "sr_entries.symbols": ["sol"],
            "sr_entries.lookback_4h": 24,
            "sr_entries.zone_atr_mult": 0.25,
            "sr_entries.use_adx_filter": True,
            "sr_entries.adx_min": 0.0,
            "sr_entries.adx_max": 20.0,
            "sr_entries.stake_scale": 0.35,
            "sr_entries.cooldown_bars": 6,
            "sr_entries.require_compress_ok": True,
        },
    ),
    (
        "sol",
        "sol_long_trend_4h",
        {
            "strategy_params.allow_short": False,
            "mean_reversion.enabled": False,
            "sr_entries.enabled": False,
            "strategy_params.cooldown_bars": 8,
            "strategy_params.breakout_lookback": 20,
            "strategy_params.breakout_atr_buffer": 0.6,
            "filters.adx_floor": 24,
            "filters.macro_gate_tf_by_symbol.sol": "4h",
        },
    ),
    (
        "sol",
        "sol_long_trend_lb16",
        {
            "strategy_params.allow_short": False,
            "mean_reversion.enabled": False,
            "sr_entries.enabled": False,
            "strategy_params.cooldown_bars": 6,
            "strategy_params.breakout_lookback": 16,
            "strategy_params.breakout_atr_buffer": 0.5,
            "filters.adx_floor": 22,
            "filters.macro_gate_tf_by_symbol.sol": "4h",
        },
    ),
    (
        "eth",
        "eth_long_sr_soft",
        {
            "strategy_params.allow_short": False,
            "mean_reversion.enabled": False,
            "filters.adx_floor": 99,
            "strategy_params.breakout_atr_buffer": 9.0,
            "strategy_params.cooldown_bars": 8,
            "sr_entries.enabled": True,
            "sr_entries.symbols": ["eth"],
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
        "eth",
        "eth_long_trend_4h",
        {
            "strategy_params.allow_short": False,
            "mean_reversion.enabled": False,
            "sr_entries.enabled": False,
            "strategy_params.cooldown_bars": 8,
            "strategy_params.breakout_lookback": 20,
            "strategy_params.breakout_atr_buffer": 0.6,
            "filters.adx_floor": 24,
            "filters.macro_gate_tf_by_symbol.eth": "4h",
        },
    ),
]


def _write_txt(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage43 efficiency lab")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--txt-out", default="")
    ap.add_argument("--json-out", default="")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    cfg = read_config(root / "config.yml")
    reports_raw = root / "reports" / "research_raw"
    txt_out = Path(args.txt_out).expanduser().resolve() if args.txt_out else reports_raw / "stage43_efficiency_lab_latest.txt"
    json_out = Path(args.json_out).expanduser().resolve() if args.json_out else reports_raw / "stage43_efficiency_lab_latest.json"
    float(cfg.get("portfolio", {}).get("initial_equity", 100000.0))

    data = _load_portfolio_data(root, cfg)
    main_rows: list[dict[str, Any]] = []
    for name, mods in MAINLINE_VARIANTS:
        row = _run_portfolio_variant(root, cfg, data, name, mods)
        main_rows.append(row)
    base = next((r for r in main_rows if r["name"] == "baseline"), main_rows[0])
    for row in main_rows:
        row["score"] = _score_mainline(row, base)
    main_sorted = sorted(main_rows, key=lambda r: (r["name"] != "baseline", r["score"], r["pf"], r["ret"]), reverse=True)
    best_main = next((r for r in main_sorted if r["name"] != "baseline"), None)

    branch_rows: list[dict[str, Any]] = []
    for symbol, name, mods in BRANCH_VARIANTS:
        row = _run_symbol_variant(root, cfg, symbol, name, mods)
        row["score"] = _score_branch(row)
        branch_rows.append(row)
    branch_sorted = sorted(branch_rows, key=lambda r: (r["score"], r["pf"], r["ret"]), reverse=True)
    best_branch = branch_sorted[0] if branch_sorted else None

    lines: list[str] = []
    lines.append("Stage43 效率实验（主线提频 + 分支重构）")
    lines.append(f"version: {cfg.get('system', {}).get('version', 'NA')}")
    lines.append("")
    lines.append("=== 主线提频 ===")
    for row in main_sorted:
        m = row.get("monthly", {}) or {}
        lines.append(
            f"- {row['name']}: trades={row['trades']} | pf={row['pf']:.3f} | ret={_pct(row['ret'])} | maxDD={_pct(row['maxdd'])} | active_months={m.get('active_months',0)} | months>=20%={m.get('months_ge_20',0)} | score={row['score']:+.2f}"
        )
        lines.append(
            f"  seg_pf=2020-2021:{row['seg_pf']['2020_2021']:.3f} / 2022-2023:{row['seg_pf']['2022_2023']:.3f} / 2024-2026:{row['seg_pf']['2024_2026']:.3f} | counts={json.dumps(row.get('counts', {}), ensure_ascii=False)}"
        )
    lines.append("")
    lines.append("=== 分支重构 ===")
    for row in branch_sorted:
        m = row.get("monthly", {}) or {}
        lines.append(
            f"- {row['name']}: symbol={row['symbol'].upper()} | trades={row['trades']} | pf={row['pf']:.3f} | ret={_pct(row['ret'])} | maxDD={_pct(row['maxdd'])} | median_month={_pct(m.get('monthly_median',0.0))} | p75_month={_pct(m.get('monthly_p75',0.0))} | months>=20%={m.get('months_ge_20',0)} | score={row['score']:+.2f}"
        )
    lines.append("")
    lines.append("=== 结论 ===")
    if best_main is not None:
        lines.append(f"- 主线当前首选仍看 {best_main['name']}；目标是先把交易频次拉高，再看 PF/分段稳定性是否还守得住。")
    lines.append("- 主线不做粗暴全局放松，只围绕 BNB 再入场 overlay 和 BTC short continuation 做微调。")
    if best_branch is not None:
        lines.append(f"- 分支当前先围绕 {best_branch['name']} 所在方向推进；若月化 20% 命中率仍差，就继续拆结构，不直接接 demo。")
    lines.append("- SOL 优先 long-only core；short shock engine 继续作为下一层，不和 long core 混在一起硬调。")
    lines.append("- ETH 继续降级为 tactical overlay 研究，不抢主资源。")

    payload = {
        "system_version": cfg.get("system", {}).get("version", "NA"),
        "mainline": {"baseline": base, "best": best_main, "rows": main_sorted},
        "branch": {"best": best_branch, "rows": branch_sorted},
        "note": {
            "monthly_target_branch": ">20%",
            "mainline_target": "raise trade frequency without obvious PF/DD damage",
        },
    }

    _write_txt(txt_out, "\n".join(lines))
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
