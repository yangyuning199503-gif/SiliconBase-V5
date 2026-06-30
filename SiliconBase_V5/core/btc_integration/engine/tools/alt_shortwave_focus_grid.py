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
from src.backtest.io import read_config
from tools.alt_shortwave_lab import _load_symbol_data, _set_nested
from tools.alt_shortwave_message_overlay import (
    _attach_message_layers,
    _pick_best_variant,
    _trade_metrics_from_df,
)


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


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
    except Exception:
        return default
    if math.isnan(v):
        return default
    return v


def _side_counts(trades: pd.DataFrame) -> dict[str, int]:
    if trades is None or trades.empty or "side" not in trades.columns:
        return {"LONG": 0, "SHORT": 0}
    vc = trades["side"].astype(str).str.upper().value_counts()
    return {"LONG": int(vc.get("LONG", 0)), "SHORT": int(vc.get("SHORT", 0))}


def _run_candidate(root: Path, base_cfg: dict[str, Any], item: dict[str, Any]) -> pd.DataFrame:
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
    return trades.copy() if trades is not None else pd.DataFrame()


def _candidate(symbol: str, lb: int, zone: float, adx_max: float, sr_cd: int, note: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "name": f"{symbol}_sw_lb{lb}_z{zone:.2f}_adx{int(adx_max)}_cd{sr_cd}",
        "note": note,
        "mods": {
            "filters.adx_floor": 99,
            "strategy_params.breakout_atr_buffer": 9.0,
            "strategy_params.cooldown_bars": 8,
            "mean_reversion.enabled": False,
            "sr_entries.enabled": True,
            "sr_entries.symbols": [symbol],
            "sr_entries.lookback_4h": lb,
            "sr_entries.zone_atr_mult": zone,
            "sr_entries.use_adx_filter": True,
            "sr_entries.adx_min": 0.0,
            "sr_entries.adx_max": adx_max,
            "sr_entries.stake_scale": 0.4,
            "sr_entries.cooldown_bars": sr_cd,
            "sr_entries.require_compress_ok": True,
        },
    }


def _grid_items(profile: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if profile == "quick":
        sol_lbs = [24, 30, 36]
        sol_zones = [0.25, 0.30, 0.35]
        sol_adx = [20.0, 22.0, 25.0]
        sol_cd = [6, 8]
        eth_lbs = [18, 24]
        eth_zones = [0.20, 0.25, 0.30]
        eth_adx = [16.0, 18.0, 20.0]
        eth_cd = [4, 6]
    else:
        sol_lbs = [18, 24, 30, 36]
        sol_zones = [0.20, 0.25, 0.30, 0.35]
        sol_adx = [18.0, 20.0, 22.0, 25.0]
        sol_cd = [4, 6, 8]
        eth_lbs = [18, 24, 30]
        eth_zones = [0.20, 0.25, 0.30, 0.35]
        eth_adx = [14.0, 16.0, 18.0, 20.0, 22.0]
        eth_cd = [4, 6, 8]

    for lb in sol_lbs:
        for zone in sol_zones:
            for adx in sol_adx:
                for cd in sol_cd:
                    items.append(_candidate("sol", lb, zone, adx, cd, "SOL 短波/SR 焦点网格"))
    for lb in eth_lbs:
        for zone in eth_zones:
            for adx in eth_adx:
                for cd in eth_cd:
                    items.append(_candidate("eth", lb, zone, adx, cd, "ETH 短波/SR 焦点网格"))
    return items


def _decision(base: dict[str, Any], best: dict[str, Any], long_n: int, short_n: int) -> str:
    gated = best.get("gated", {})
    pf = _safe_float(gated.get("pf"), default=float("nan"))
    ret = _safe_float(gated.get("ret"), default=-1.0)
    maxdd = abs(_safe_float(gated.get("maxdd"), default=1.0))
    trades = int(gated.get("trades", 0) or 0)
    blocked = int(best.get("blocked", 0) or 0)
    if math.isnan(pf):
        pf = 0.0
    if pf >= 1.00 and ret > 0 and maxdd <= 0.35 and trades >= 60 and long_n >= 10 and short_n >= 10:
        return "继续深挖"
    if pf >= 0.80 and maxdd <= 0.40 and trades >= 60 and blocked >= 1:
        return "保留观察"
    if pf >= 0.65 and trades >= 60:
        return "继续研究"
    return "淘汰"


def _row_score(row: dict[str, Any]) -> float:
    gated = row["best_overlay"]["gated"]
    pf = _safe_float(gated.get("pf"))
    ret = _safe_float(gated.get("ret"), default=-1.0)
    maxdd = abs(_safe_float(gated.get("maxdd"), default=1.0))
    trades = int(gated.get("trades", 0) or 0)
    blocked = int(row["best_overlay"].get("blocked", 0) or 0)
    dd_delta = _safe_float(row["best_overlay"].get("dd_delta"))
    pnl_delta = _safe_float(row["best_overlay"].get("pnl_delta"))
    long_n = int(row.get("long_trades", 0) or 0)
    short_n = int(row.get("short_trades", 0) or 0)
    score = pf * 120.0
    score += ret * 80.0
    score -= maxdd * 60.0
    score += min(trades, 180) * 0.20
    score += blocked * 1.5
    score += dd_delta * 20.0
    score += max(min(pnl_delta / 2000.0, 15.0), -15.0)
    if long_n >= 10 and short_n >= 10:
        score += 8.0
    elif long_n >= 5 and short_n >= 5:
        score += 3.0
    return float(score)


def main() -> None:
    ap = argparse.ArgumentParser(description="ETH/SOL 短波焦点网格 + 消息面 overlay 研究")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--profile", choices=["quick", "full"], default="quick")
    ap.add_argument("--top", type=int, default=16)
    ap.add_argument("--out", default=str(Path.home() / "Downloads" / "alt_shortwave_focus_grid_latest.txt"))
    ap.add_argument("--json-out", default=str(Path.home() / "Downloads" / "alt_shortwave_focus_grid_latest.json"))
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    cfg = read_config(root / "config.yml")
    rows: list[dict[str, Any]] = []
    for item in _grid_items(args.profile):
        trades = _run_candidate(root, cfg, item)
        base = _trade_metrics_from_df(trades)
        counts = _side_counts(trades)
        trades_msg = _attach_message_layers(root, trades)
        best = _pick_best_variant(trades_msg)
        row = {
            "name": str(item["name"]),
            "symbol": str(item["symbol"]),
            "note": str(item.get("note", "")),
            "mods": item.get("mods", {}),
            "base": base,
            "best_overlay": best,
            "long_trades": counts["LONG"],
            "short_trades": counts["SHORT"],
        }
        row["decision"] = _decision(base, best, counts["LONG"], counts["SHORT"])
        row["score"] = _row_score(row)
        rows.append(row)

    def sort_key(row: dict[str, Any]) -> tuple:
        gated = row["best_overlay"]["gated"]
        pf = _safe_float(gated.get("pf"), default=-1.0)
        ret = _safe_float(gated.get("ret"), default=-1.0)
        return (
            row["decision"] == "继续深挖",
            row["decision"] == "保留观察",
            row["decision"] == "继续研究",
            pf,
            ret,
            float(row.get("score", 0.0)),
        )

    rows = sorted(rows, key=sort_key, reverse=True)
    top_rows = rows[: max(1, int(args.top))]

    best_by_symbol: dict[str, dict[str, Any]] = {}
    for row in rows:
        best_by_symbol.setdefault(str(row["symbol"]), row)

    lines: list[str] = []
    lines.append("ALT 短波焦点网格 + 消息面 overlay 研究（ETH/SOL，只做 research，不改 live）")
    lines.append(f"profile: {args.profile}")
    lines.append(f"version: {cfg.get('system', {}).get('version', 'NA')}")
    lines.append("")
    lines.append("=== 每个标的当前最优 ===")
    for sym in ["sol", "eth"]:
        row = best_by_symbol.get(sym)
        if row is None:
            continue
        gated = row["best_overlay"]["gated"]
        ov = row["best_overlay"]
        mods = row["mods"]
        lines.append(
            f"- {sym}: {row['name']} | lb={mods.get('sr_entries.lookback_4h')} zone={mods.get('sr_entries.zone_atr_mult')} adx_max={mods.get('sr_entries.adx_max')} sr_cd={mods.get('sr_entries.cooldown_bars')} | gated_pf={gated.get('pf', float('nan')):.3f} | gated_ret={_fmt_pct(gated.get('ret'))} | gated_maxDD={_fmt_pct(gated.get('maxdd'))} | trades={gated.get('trades', 0)} | long={row['long_trades']} short={row['short_trades']} | overlay={ov.get('variant')} | decision={row['decision']}"
        )
    lines.append("")
    lines.append(f"=== Top {len(top_rows)} 候选 ===")
    for row in top_rows:
        gated = row["best_overlay"]["gated"]
        ov = row["best_overlay"]
        mods = row["mods"]
        lines.append(
            f"- {row['name']}: symbol={row['symbol']} | lb={mods.get('sr_entries.lookback_4h')} zone={mods.get('sr_entries.zone_atr_mult')} adx_max={mods.get('sr_entries.adx_max')} sr_cd={mods.get('sr_entries.cooldown_bars')} | base_pf={row['base'].get('pf', float('nan')):.3f} -> gated_pf={gated.get('pf', float('nan')):.3f} | gated_ret={_fmt_pct(gated.get('ret'))} | gated_maxDD={_fmt_pct(gated.get('maxdd'))} | trades={gated.get('trades', 0)} | long={row['long_trades']} short={row['short_trades']} | overlay={ov.get('variant')} blocked={ov.get('blocked', 0)} | score={row['score']:+.2f} | decision={row['decision']}"
        )
        teg = "; ".join([str(x) for x in ov.get("top_event_groups", [])[:3]])
        if teg:
            lines.append(f"  top_event_groups={teg}")
    lines.append("")
    lines.append("=== 结论 ===")
    if rows:
        best = rows[0]
        gated = best["best_overlay"]["gated"]
        lines.append(f"- 当前总最优：{best['name']} | symbol={best['symbol']} | gated_pf={gated.get('pf', float('nan')):.3f} | gated_ret={_fmt_pct(gated.get('ret'))} | overlay={best['best_overlay'].get('variant')} | decision={best['decision']}")
    lines.append("- 当前目标不是直接并线，而是先找出 SOL 本体更稳、ETH 更吃消息面 的局部参数区间。")
    lines.append("- 消息面继续只做 risk overlay；只有 gated_pf>=1 且 gated_ret>0 时，才进入更严格 walk-forward。")

    payload = {
        "profile": args.profile,
        "version": cfg.get("system", {}).get("version", "NA"),
        "rows": rows,
        "best_by_symbol": best_by_symbol,
        "top_rows": top_rows,
    }
    out_txt = Path(args.out).expanduser().resolve()
    out_json = Path(args.json_out).expanduser().resolve()
    out_txt.parent.mkdir(parents=True, exist_ok=True)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
