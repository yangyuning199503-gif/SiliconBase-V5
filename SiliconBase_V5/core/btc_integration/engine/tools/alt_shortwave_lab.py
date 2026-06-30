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


def _safe_float(x: Any) -> float:
    try:
        v = float(x)
    except Exception:
        return float("nan")
    return v


def _fmt_pct(x: float | None) -> str:
    if x is None:
        return "NA"
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


def _side_counts(trades: pd.DataFrame) -> dict[str, int]:
    if trades is None or trades.empty:
        return {"LONG": 0, "SHORT": 0}
    vc = trades["side"].astype(str).str.upper().value_counts()
    return {"LONG": int(vc.get("LONG", 0)), "SHORT": int(vc.get("SHORT", 0))}


def _load_symbol_data(root: Path, cfg: dict[str, Any], symbol: str) -> dict[str, pd.DataFrame]:
    data_cfg = cfg.get("data", {})
    csv_template = str(data_cfg.get("csv_template", "data/raw/{symbol}_15m.csv"))
    start = pd.to_datetime(data_cfg.get("start"), utc=True).tz_convert(None) if data_cfg.get("start") else None
    end = pd.to_datetime(data_cfg.get("end"), utc=True).tz_convert(None) if data_cfg.get("end") else None
    path = root / csv_template.format(symbol=symbol)
    if not path.exists():
        raise SystemExit(f"缺少原始数据：{path}")
    df = load_ohlcv_csv(path)
    if start is not None:
        df = df.loc[df.index >= start]
    if end is not None:
        df = df.loc[df.index <= end]
    return {symbol: df}


def _summarize_row(symbol: str, name: str, note: str, equity: pd.DataFrame, trades: pd.DataFrame, snapshot: dict[str, Any]) -> dict[str, Any]:
    eq = equity["equity"]
    initial_equity = 100000.0
    final_equity = float(eq.iloc[-1]) if len(eq) else initial_equity
    total_return = final_equity / initial_equity - 1.0 if initial_equity else float("nan")
    peak = eq.cummax() if len(eq) else eq
    dd = eq / peak - 1.0 if len(eq) else eq
    max_drawdown = float(dd.min()) if len(dd) else float("nan")
    counts = _side_counts(trades)
    total_trades = int(len(trades)) if trades is not None else 0
    short_share = float(counts["SHORT"] / total_trades) if total_trades > 0 else 0.0
    seg = _segment_pfs(trades)
    finite_seg = [v for v in seg.values() if not math.isnan(v)]
    seg_min_pf = min(finite_seg) if finite_seg else float("nan")
    return {
        "symbol": symbol,
        "name": name,
        "note": note,
        "trades": total_trades,
        "long_trades": counts["LONG"],
        "short_trades": counts["SHORT"],
        "short_share": short_share,
        "profit_factor": _pf(trades),
        "total_return": total_return,
        "max_drawdown": max_drawdown,
        "active_months": _active_months(trades),
        "seg_pf": seg,
        "seg_min_pf": seg_min_pf,
        "final_equity": final_equity,
        "snapshot_final_positions": snapshot.get("final_positions", {}),
    }


def _score_row(row: dict[str, Any]) -> float:
    pf = _safe_float(row.get("profit_factor"))
    trades = int(row.get("trades", 0) or 0)
    mdd = abs(_safe_float(row.get("max_drawdown")))
    short_share = _safe_float(row.get("short_share"))
    total_return = _safe_float(row.get("total_return"))
    seg_min_pf = _safe_float(row.get("seg_min_pf"))
    if math.isnan(pf):
        pf = 0.0
    if math.isnan(short_share):
        short_share = 0.0
    if math.isnan(seg_min_pf):
        seg_min_pf = 0.0
    if math.isnan(total_return):
        total_return = -1.0
    score = pf * 120.0
    score += min(trades, 140) * 0.25
    score += short_share * 10.0
    score += seg_min_pf * 12.0
    score -= mdd * 90.0
    if total_return <= 0:
        score -= 10.0
    return float(score)


def _decision(row: dict[str, Any]) -> str:
    pf = _safe_float(row.get("profit_factor"))
    total_return = _safe_float(row.get("total_return"))
    mdd = abs(_safe_float(row.get("max_drawdown")))
    trades = int(row.get("trades", 0) or 0)
    short_share = _safe_float(row.get("short_share"))
    if math.isnan(pf):
        return "淘汰"
    if pf >= 1.00 and total_return > 0 and mdd <= 0.40 and trades >= 60:
        return "继续深挖"
    if pf >= 0.70 and mdd <= 0.40 and trades >= 70 and short_share >= 0.45:
        return "保留观察"
    if pf >= 0.60 and mdd <= 0.40 and trades >= 70:
        return "继续研究"
    return "淘汰"


def _run_candidate(root: Path, base_cfg: dict[str, Any], symbol: str, name: str, note: str, mods: dict[str, Any]) -> dict[str, Any]:
    cfg = copy.deepcopy(base_cfg)
    cfg.setdefault("data", {})["symbols"] = [symbol]
    cfg.setdefault("data", {})["weights"] = {symbol: 1.0}
    _set_nested(cfg, "strategy_params.short_symbols", [symbol])
    _set_nested(cfg, "filters.macro_gate_symbols", [symbol])
    _set_nested(cfg, "filters.macro_gate_reference_symbol", symbol)
    for path, value in mods.items():
        _set_nested(cfg, path, value)
    data = _load_symbol_data(root, cfg, symbol)
    equity, trades, snapshot = run_backtest_portfolio(data, cfg)
    row = _summarize_row(symbol, name, note, equity, trades, snapshot)
    row["score"] = _score_row(row)
    row["decision"] = _decision(row)
    return row


QUICK_CANDIDATES: list[dict[str, Any]] = [
    {
        "symbol": "eth",
        "name": "eth_fast_trend_4h",
        "note": "ETH 快速双向 trend（4H gate）",
        "mods": {
            "strategy_params.cooldown_bars": 8,
            "strategy_params.breakout_lookback": 20,
            "strategy_params.breakout_atr_buffer": 0.6,
            "filters.adx_floor": 24,
            "filters.macro_gate_tf_by_symbol.eth": "4h",
            "mean_reversion.enabled": False,
            "sr_entries.enabled": False,
        },
    },
    {
        "symbol": "eth",
        "name": "eth_shortwave_sr",
        "note": "ETH 短波/SR（当前主候选）",
        "mods": {
            "filters.adx_floor": 99,
            "strategy_params.breakout_atr_buffer": 9.0,
            "strategy_params.cooldown_bars": 8,
            "mean_reversion.enabled": False,
            "sr_entries.enabled": True,
            "sr_entries.symbols": ["eth"],
            "sr_entries.lookback_4h": 24,
            "sr_entries.zone_atr_mult": 0.35,
            "sr_entries.use_adx_filter": True,
            "sr_entries.adx_min": 0.0,
            "sr_entries.adx_max": 25.0,
            "sr_entries.stake_scale": 0.4,
            "sr_entries.cooldown_bars": 8,
            "sr_entries.require_compress_ok": True,
        },
    },
    {
        "symbol": "sol",
        "name": "sol_fast_trend_4h",
        "note": "SOL 快速双向 trend（4H gate）",
        "mods": {
            "strategy_params.cooldown_bars": 8,
            "strategy_params.breakout_lookback": 20,
            "strategy_params.breakout_atr_buffer": 0.6,
            "filters.adx_floor": 24,
            "filters.macro_gate_tf_by_symbol.sol": "4h",
            "mean_reversion.enabled": False,
            "sr_entries.enabled": False,
        },
    },
    {
        "symbol": "sol",
        "name": "sol_shortwave_sr",
        "note": "SOL 短波/SR（当前主候选）",
        "mods": {
            "filters.adx_floor": 99,
            "strategy_params.breakout_atr_buffer": 9.0,
            "strategy_params.cooldown_bars": 8,
            "mean_reversion.enabled": False,
            "sr_entries.enabled": True,
            "sr_entries.symbols": ["sol"],
            "sr_entries.lookback_4h": 24,
            "sr_entries.zone_atr_mult": 0.35,
            "sr_entries.use_adx_filter": True,
            "sr_entries.adx_min": 0.0,
            "sr_entries.adx_max": 25.0,
            "sr_entries.stake_scale": 0.4,
            "sr_entries.cooldown_bars": 8,
            "sr_entries.require_compress_ok": True,
        },
    },
]

FULL_EXTRA_CANDIDATES: list[dict[str, Any]] = [
    {
        "symbol": "eth",
        "name": "eth_fast_trend_4h_lb16",
        "note": "ETH 更快的双向 trend（LB16）",
        "mods": {
            "strategy_params.cooldown_bars": 6,
            "strategy_params.breakout_lookback": 16,
            "strategy_params.breakout_atr_buffer": 0.5,
            "filters.adx_floor": 22,
            "filters.macro_gate_tf_by_symbol.eth": "4h",
            "mean_reversion.enabled": False,
            "sr_entries.enabled": False,
        },
    },
    {
        "symbol": "sol",
        "name": "sol_fast_trend_4h_lb16",
        "note": "SOL 更快的双向 trend（LB16）",
        "mods": {
            "strategy_params.cooldown_bars": 6,
            "strategy_params.breakout_lookback": 16,
            "strategy_params.breakout_atr_buffer": 0.5,
            "filters.adx_floor": 22,
            "filters.macro_gate_tf_by_symbol.sol": "4h",
            "mean_reversion.enabled": False,
            "sr_entries.enabled": False,
        },
    },
    {
        "symbol": "eth",
        "name": "eth_shortwave_sr_tight",
        "note": "ETH 短波/SR 更紧版本（18/0.25/18/4）",
        "mods": {
            "filters.adx_floor": 99,
            "strategy_params.breakout_atr_buffer": 9.0,
            "strategy_params.cooldown_bars": 8,
            "mean_reversion.enabled": False,
            "sr_entries.enabled": True,
            "sr_entries.symbols": ["eth"],
            "sr_entries.lookback_4h": 18,
            "sr_entries.zone_atr_mult": 0.25,
            "sr_entries.use_adx_filter": True,
            "sr_entries.adx_min": 0.0,
            "sr_entries.adx_max": 18.0,
            "sr_entries.stake_scale": 0.4,
            "sr_entries.cooldown_bars": 4,
            "sr_entries.require_compress_ok": True,
        },
    },
    {
        "symbol": "sol",
        "name": "sol_shortwave_sr_tight",
        "note": "SOL 短波/SR 更紧版本（18/0.25/18/4）",
        "mods": {
            "filters.adx_floor": 99,
            "strategy_params.breakout_atr_buffer": 9.0,
            "strategy_params.cooldown_bars": 8,
            "mean_reversion.enabled": False,
            "sr_entries.enabled": True,
            "sr_entries.symbols": ["sol"],
            "sr_entries.lookback_4h": 18,
            "sr_entries.zone_atr_mult": 0.25,
            "sr_entries.use_adx_filter": True,
            "sr_entries.adx_min": 0.0,
            "sr_entries.adx_max": 18.0,
            "sr_entries.stake_scale": 0.4,
            "sr_entries.cooldown_bars": 4,
            "sr_entries.require_compress_ok": True,
        },
    },
    {
        "symbol": "sol",
        "name": "sol_shortwave_sr_mid",
        "note": "SOL 短波/SR 中间版本（24/0.25/20/6）",
        "mods": {
            "filters.adx_floor": 99,
            "strategy_params.breakout_atr_buffer": 9.0,
            "strategy_params.cooldown_bars": 8,
            "mean_reversion.enabled": False,
            "sr_entries.enabled": True,
            "sr_entries.symbols": ["sol"],
            "sr_entries.lookback_4h": 24,
            "sr_entries.zone_atr_mult": 0.25,
            "sr_entries.use_adx_filter": True,
            "sr_entries.adx_min": 0.0,
            "sr_entries.adx_max": 20.0,
            "sr_entries.stake_scale": 0.4,
            "sr_entries.cooldown_bars": 6,
            "sr_entries.require_compress_ok": True,
        },
    },
    {
        "symbol": "sol",
        "name": "sol_shortwave_sr_smooth",
        "note": "SOL 短波/SR 平滑版本（30/0.30/22/8）",
        "mods": {
            "filters.adx_floor": 99,
            "strategy_params.breakout_atr_buffer": 9.0,
            "strategy_params.cooldown_bars": 8,
            "mean_reversion.enabled": False,
            "sr_entries.enabled": True,
            "sr_entries.symbols": ["sol"],
            "sr_entries.lookback_4h": 30,
            "sr_entries.zone_atr_mult": 0.30,
            "sr_entries.use_adx_filter": True,
            "sr_entries.adx_min": 0.0,
            "sr_entries.adx_max": 22.0,
            "sr_entries.stake_scale": 0.4,
            "sr_entries.cooldown_bars": 8,
            "sr_entries.require_compress_ok": True,
        },
    },
    {
        "symbol": "eth",
        "name": "eth_hybrid_mr",
        "note": "ETH trend + MR 混合试探",
        "mods": {
            "strategy_params.cooldown_bars": 6,
            "strategy_params.breakout_lookback": 20,
            "strategy_params.breakout_atr_buffer": 0.6,
            "filters.adx_floor": 24,
            "filters.macro_gate_tf_by_symbol.eth": "4h",
            "mean_reversion.enabled": True,
            "mean_reversion.bb_window": 36,
            "mean_reversion.bb_std": 2.2,
            "mean_reversion.adx_ceiling": 16,
            "mean_reversion.max_hold_bars": 1,
            "mean_reversion.risk_fraction_of_trend": 0.08,
            "mean_reversion.leverage_cap": 1.8,
            "mean_reversion.atr_stop_mult": 2.5,
            "mean_reversion.exit_on_mid": True,
            "mean_reversion.cooldown_bars": 8,
            "sr_entries.enabled": False,
        },
    },
    {
        "symbol": "sol",
        "name": "sol_hybrid_mr",
        "note": "SOL trend + MR 混合试探",
        "mods": {
            "strategy_params.cooldown_bars": 6,
            "strategy_params.breakout_lookback": 20,
            "strategy_params.breakout_atr_buffer": 0.6,
            "filters.adx_floor": 24,
            "filters.macro_gate_tf_by_symbol.sol": "4h",
            "mean_reversion.enabled": True,
            "mean_reversion.bb_window": 36,
            "mean_reversion.bb_std": 2.2,
            "mean_reversion.adx_ceiling": 16,
            "mean_reversion.max_hold_bars": 1,
            "mean_reversion.risk_fraction_of_trend": 0.08,
            "mean_reversion.leverage_cap": 1.8,
            "mean_reversion.atr_stop_mult": 2.5,
            "mean_reversion.exit_on_mid": True,
            "mean_reversion.cooldown_bars": 8,
            "sr_entries.enabled": False,
        },
    },
]


def main() -> None:
    ap = argparse.ArgumentParser(description="ALT 短波实验室：ETH/SOL 为主，只做 research，不改 live")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--profile", choices=["quick", "full"], default="quick")
    ap.add_argument("--out", default="")
    ap.add_argument("--json-out", default="")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    default_dir = root / "reports" / "research_raw"
    out_arg = args.out or str(default_dir / "alt_shortwave_lab_latest.txt")
    json_arg = args.json_out or str(default_dir / "alt_shortwave_lab_latest.json")
    cfg = read_config(root / "config.yml")
    candidates = list(QUICK_CANDIDATES)
    if args.profile == "full":
        candidates.extend(FULL_EXTRA_CANDIDATES)

    rows: list[dict[str, Any]] = []
    for item in candidates:
        row = _run_candidate(root, cfg, item["symbol"], item["name"], item.get("note", ""), item["mods"])
        rows.append(row)

    rows_sorted = sorted(rows, key=lambda r: (r["decision"] == "继续深挖", r["decision"] == "保留观察", r["decision"] == "继续研究", r["score"]), reverse=True)
    best = rows_sorted[0] if rows_sorted else None

    lines: list[str] = []
    lines.append("ALT 短波实验室（ETH/SOL 为主，只做 research，不改 live）")
    lines.append(f"profile: {args.profile}")
    lines.append(f"version: {cfg.get('system', {}).get('version', 'NA')}")
    lines.append("")
    lines.append("=== 候选结果 ===")
    for row in rows_sorted:
        seg_min_text = "NA" if math.isnan(row["seg_min_pf"]) else f"{row['seg_min_pf']:.3f}"
        lines.append(
            f"- {row['name']}: symbol={row['symbol']} | trades={row['trades']} | long={row['long_trades']} | short={row['short_trades']} "
            f"| short_share={_fmt_pct(row['short_share'])} | PF={row['profit_factor']:.3f} | ret={_fmt_pct(row['total_return'])} "
            f"| maxDD={_fmt_pct(row['max_drawdown'])} | seg_min_pf={seg_min_text} | active_months={row['active_months']} | decision={row['decision']}"
        )
        lines.append(f"  note: {row['note']}")
        lines.append(
            f"  seg_pf: 2020-2021={row['seg_pf']['2020-2021']}, "
            f"2022-2023={row['seg_pf']['2022-2023']}, 2024-2026={row['seg_pf']['2024-2026']}"
        )
    lines.append("")
    lines.append("=== 结论 ===")
    if best is None:
        lines.append("- 无结果。")
    else:
        lines.append(f"- 当前最优候选：{best['name']} | symbol={best['symbol']} | decision={best['decision']}")
        lines.append("- 现有结果表明：ETH/SOL 短波想法整体优于 BTC 双向短波原型，但仍未达到可并线标准。")
        if str(best.get("symbol", "")).lower() == "sol":
            lines.append("- 当前优先级：SOL-first，ETH-second，BTC-third。")
        if best["decision"] in ("继续研究", "保留观察"):
            lines.append("- 当前仍只保留为 research；消息面继续只做 risk layer / overlay，不直接升 alpha。")
        if best["max_drawdown"] <= -0.40 or best["profit_factor"] < 1.0:
            lines.append("- 关键约束：PF 仍未过线，且风险收益比还不够硬；第二分支暂不并入 live。")
        lines.append("- 下一步建议：优先继续深挖 SOL 短波/SR，再扩 ETH；同时保留 message_stack 联动回测。")

    payload = {
        "profile": args.profile,
        "version": cfg.get("system", {}).get("version", "NA"),
        "rows": rows_sorted,
        "best": best,
    }

    out_txt = Path(out_arg).expanduser().resolve()
    out_json = Path(json_arg).expanduser().resolve()
    out_txt.parent.mkdir(parents=True, exist_ok=True)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
