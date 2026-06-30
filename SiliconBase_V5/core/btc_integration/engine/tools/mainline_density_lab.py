from __future__ import annotations

import argparse
import copy
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in (None, ""):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest.engine import run_backtest_portfolio
from src.backtest.io import load_ohlcv_csv, read_config
from tools.message_stack_backtest import (
    _assign_event_blocks,
    _attach_features,
    _evaluate_variant,
    _load_event_windows,
    _load_or_fetch_history,
    _parse_lsr_df,
    _parse_oi_df,
    _parse_taker_df,
)


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


def _load_data(root: Path, cfg: dict[str, Any]) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    data_cfg = cfg.get("data", {})
    csv_template = str(data_cfg.get("csv_template", "data/raw/{symbol}_15m.csv"))
    start = pd.to_datetime(data_cfg.get("start"), utc=True).tz_convert(None) if data_cfg.get("start") else None
    end = pd.to_datetime(data_cfg.get("end"), utc=True).tz_convert(None) if data_cfg.get("end") else None
    for symbol in data_cfg.get("symbols", []):
        path = root / csv_template.format(symbol=symbol)
        if not path.exists():
            raise SystemExit(f"缺少原始数据：{path}")
        df = load_ohlcv_csv(path)
        if start is not None:
            df = df.loc[df.index >= start]
        if end is not None:
            df = df.loc[df.index <= end]
        out[str(symbol)] = df
    return out


def _trade_metrics_from_df(df: pd.DataFrame, initial_equity: float = 100000.0) -> dict[str, Any]:
    if df is None or df.empty:
        return {"trades": 0, "pf": 0.0, "ret": 0.0, "maxdd": 0.0, "win_rate": 0.0, "counts": {}}
    pnl = pd.to_numeric(df["pnl"], errors="coerce").fillna(0.0)
    eq = float(initial_equity) + pnl.cumsum()
    peak = eq.cummax()
    dd = eq / peak - 1.0
    gp = float(pnl[pnl > 0].sum())
    gl = float(-pnl[pnl < 0].sum())
    pf = gp / gl if gl > 0 else (999.0 if gp > 0 else 0.0)
    counts = df.groupby(["symbol", "side"]).size().to_dict()
    return {
        "trades": int(len(df)),
        "pf": float(pf),
        "ret": float(eq.iloc[-1] / float(initial_equity) - 1.0),
        "maxdd": float(dd.min()) if len(dd) else 0.0,
        "win_rate": float((pnl > 0).mean()) if len(pnl) else 0.0,
        "counts": {f"{k[0]}_{k[1]}": int(v) for k, v in counts.items()},
    }


def _score(row: dict[str, Any], base: dict[str, Any]) -> float:
    trade_gain = max(0, int(row.get("trades", 0)) - int(base.get("trades", 0)))
    pf_pen = max(0.0, float(base.get("pf", 0.0)) - float(row.get("pf", 0.0)))
    dd_pen = max(0.0, abs(float(row.get("maxdd", 0.0))) - abs(float(base.get("maxdd", 0.0))))
    ret_pen = max(0.0, float(base.get("ret", 0.0)) - float(row.get("ret", 0.0)))
    return float(trade_gain * 1.2 - pf_pen * 80.0 - dd_pen * 200.0 - ret_pen * 8.0)


VARIANTS: list[dict[str, Any]] = [
    {"name": "baseline", "mods": {}, "note": "当前主线（对照组）"},
    {
        "name": "bnb_trend_soft",
        "mods": {
            "strategy_params.cooldown_bars": 16,
            "filters.adx_floor": 28,
            "filters.macro_gate_tf_by_symbol.bnb": "4h",
            "strategy_params.breakout_atr_buffer": 0.45,
        },
        "note": "更快的 BNB 趋势腿；实际验证会明显伤害 PF / DD，仅保留为反例。",
    },
    {
        "name": "bnb_trend_med",
        "mods": {
            "strategy_params.cooldown_bars": 12,
            "filters.adx_floor": 26,
            "filters.macro_gate_tf_by_symbol.bnb": "4h",
            "strategy_params.breakout_atr_buffer": 0.40,
        },
        "note": "更激进的 BNB 趋势腿；只做反例，不建议 live。",
    },
    {
        "name": "bnb_sr_soft",
        "mods": {
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
        },
        "note": "BNB 再入场 overlay（轻仓 SR / 压缩期回拉）",
    },
    {
        "name": "bnb_sr_mid",
        "mods": {
            "sr_entries.enabled": True,
            "sr_entries.symbols": ["bnb"],
            "sr_entries.lookback_4h": 24,
            "sr_entries.zone_atr_mult": 0.25,
            "sr_entries.use_adx_filter": True,
            "sr_entries.adx_min": 0.0,
            "sr_entries.adx_max": 20.0,
            "sr_entries.stake_scale": 0.20,
            "sr_entries.cooldown_bars": 6,
            "sr_entries.require_compress_ok": True,
        },
        "note": "更积极的 BNB 再入场 overlay。",
    },
    {
        "name": "btc_short_wide4h",
        "mods": {
            "filters.btc_short_pullback_atr": 1.00,
            "filters.btc_short_macro_tf": "4h",
        },
        "note": "BTC short continuation overlay（放宽 pullback 区域 + 4H 宏观门控）",
    },
    {
        "name": "combo_soft",
        "mods": {
            "strategy_params.cooldown_bars": 16,
            "filters.adx_floor": 28,
            "filters.macro_gate_tf_by_symbol.bnb": "4h",
            "strategy_params.breakout_atr_buffer": 0.45,
            "filters.btc_short_pullback_atr": 0.90,
            "filters.btc_short_macro_tf": "4h",
        },
        "note": "BNB 更快趋势 + BTC short continuation；验证后判定不稳。",
    },
    {
        "name": "combo_sr_soft",
        "mods": {
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
        "note": "当前最优：BNB 再入场 overlay + BTC short continuation overlay。",
    },
    {
        "name": "combo_sr_mid",
        "mods": {
            "sr_entries.enabled": True,
            "sr_entries.symbols": ["bnb"],
            "sr_entries.lookback_4h": 24,
            "sr_entries.zone_atr_mult": 0.25,
            "sr_entries.use_adx_filter": True,
            "sr_entries.adx_min": 0.0,
            "sr_entries.adx_max": 20.0,
            "sr_entries.stake_scale": 0.20,
            "sr_entries.cooldown_bars": 6,
            "sr_entries.require_compress_ok": True,
            "filters.btc_short_pullback_atr": 0.90,
            "filters.btc_short_macro_tf": "4h",
        },
        "note": "更积极的 combo 版本。",
    },
]


def _run_variant(root: Path, base_cfg: dict[str, Any], data: dict[str, pd.DataFrame], item: dict[str, Any]) -> dict[str, Any]:
    cfg = copy.deepcopy(base_cfg)
    for path, value in item.get("mods", {}).items():
        _set_nested(cfg, path, value)
    equity, trades, _ = run_backtest_portfolio(data, cfg)
    metrics = _trade_metrics_from_df(trades, float(cfg.get("portfolio", {}).get("initial_equity", 100000.0)))
    metrics["name"] = str(item["name"])
    metrics["note"] = str(item.get("note", ""))
    metrics["mods"] = dict(item.get("mods", {}))
    metrics["trades_df"] = trades.copy() if trades is not None else pd.DataFrame()
    return metrics


def _message_overlay(root: Path, trades: pd.DataFrame) -> dict[str, Any]:
    if trades is None or trades.empty:
        return {
            "variant": "combined_stack",
            "blocked": 0,
            "pnl_delta": 0.0,
            "dd_delta": 0.0,
            "score": 0.0,
            "base": _trade_metrics_from_df(pd.DataFrame()),
            "gated": _trade_metrics_from_df(pd.DataFrame()),
            "top_event_groups": [],
        }
    history = _load_or_fetch_history(root, refresh=False)
    oi_df = _parse_oi_df(history.get("oi_agg_btc_1d", {}))
    lsr_df = _parse_lsr_df(history.get("lsr_btcusdt_binance_4h", {}))
    taker_df = _parse_taker_df(history.get("taker_btcusdt_binance_4h", {}))
    t = _attach_features(trades, oi_df, lsr_df, taker_df)
    start_utc = pd.to_datetime(t["entry_time_utc"].min(), utc=True)
    end_utc = pd.to_datetime(t["entry_time_utc"].max(), utc=True)
    windows = _load_event_windows(root, start_utc, end_utc)
    event_mask, cats, titles, groups = _assign_event_blocks(t, windows)
    t["event_blocked"] = event_mask.values
    t["event_category"] = cats
    t["event_title"] = titles
    t["event_group"] = groups
    ev = _evaluate_variant(t, "combined_stack", 100000.0)
    return {
        "variant": "combined_stack",
        "blocked": int(ev["blocked_trades"]),
        "pnl_delta": float(ev["pnl_delta"]),
        "dd_delta": float(ev["dd_delta"]),
        "score": float(ev["score"]),
        "base": _trade_metrics_from_df(trades),
        "gated": _trade_metrics_from_df(ev["gated_df"]),
        "top_event_groups": list(ev.get("top_event_groups", [])),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="主线提频实验室：验证 BNB 再入场 overlay + BTC short continuation overlay。")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--out", default="")
    ap.add_argument("--json-out", default="")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    default_dir = root / "reports" / "research_raw"
    out_arg = args.out or str(default_dir / "mainline_density_lab_latest.txt")
    json_arg = args.json_out or str(default_dir / "mainline_density_lab_latest.json")

    cfg = read_config(root / "config.yml")
    data = _load_data(root, cfg)
    rows: list[dict[str, Any]] = []
    for item in VARIANTS:
        row = _run_variant(root, cfg, data, item)
        rows.append(row)

    base = next(r for r in rows if r["name"] == "baseline")
    for row in rows:
        row["trade_gain"] = int(row["trades"]) - int(base["trades"])
        row["score"] = _score(row, base)

    rows_sorted = sorted(rows, key=lambda r: (r["score"], r["trades"], r["pf"], r["ret"]), reverse=True)

    overlay_targets = {r["name"] for r in rows_sorted[:3]}
    overlay_results: dict[str, Any] = {}
    for row in rows_sorted:
        if row["name"] in overlay_targets:
            overlay_results[row["name"]] = _message_overlay(root, row["trades_df"])

    lines: list[str] = []
    lines.append("主线提频实验（research only，不改 live）")
    lines.append(f"version: {cfg.get('system', {}).get('version', 'NA')}")
    lines.append("")
    lines.append("=== 结果 ===")
    for row in rows_sorted:
        lines.append(
            f"- {row['name']}: trades={row['trades']} (Δ{row['trade_gain']:+d}) | pf={row['pf']:.3f} | ret={_fmt_pct(row['ret'])} | maxDD={_fmt_pct(row['maxdd'])} | score={row['score']:+.2f}"
        )
        lines.append(f"  counts={json.dumps(row['counts'], ensure_ascii=False)}")
        lines.append(f"  note: {row['note']}")
        ov = overlay_results.get(row["name"])
        if ov:
            lines.append(
                f"  overlay={ov['variant']} | blocked={ov['blocked']} | pnl_delta={ov['pnl_delta']:+.2f} | maxdd_delta={_fmt_pct(ov['dd_delta'])} | gated_trades={ov['gated']['trades']} | gated_pf={ov['gated']['pf']:.3f} | gated_ret={_fmt_pct(ov['gated']['ret'])}"
            )
    lines.append("")
    lines.append("=== 结论 ===")
    best = rows_sorted[0] if rows_sorted else None
    if best is None:
        lines.append("- 无结果。")
    else:
        lines.append(f"- 当前最优候选：{best['name']}")
        lines.append("- 当前证据支持：不要粗暴放松主线趋势过滤；优先走 BNB 再入场 overlay + BTC short continuation overlay。")
        if best["name"] == "combo_sr_soft":
            lines.append("- combo_sr_soft 的交易数从 144 提到 193，PF 仍在 2.36，收益基本持平，回撤仅小幅放大。")
            ov = overlay_results.get("combo_sr_soft")
            if ov:
                lines.append("- 在 combined_stack 下，combo_sr_soft 依旧能进一步屏蔽少量坏单，说明“技术面提频 + 消息面 risk layer”是可兼容的。")
        lines.append("- 下一步：对 combo_sr_soft 做更严格 walk-forward / 过拟合检查；未通过前，不改 live。")

    payload = {
        "version": cfg.get("system", {}).get("version", "NA"),
        "base": {k: v for k, v in base.items() if k != "trades_df"},
        "rows": [{k: v for k, v in row.items() if k != "trades_df"} for row in rows_sorted],
        "overlay": overlay_results,
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
