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
from tools.alt_shortwave_lab import FULL_EXTRA_CANDIDATES, QUICK_CANDIDATES, _load_symbol_data, _set_nested
from tools.message_stack_backtest import (
    _assign_event_annotations,
    _attach_features,
    _evaluate_variant,
    _load_event_windows,
    _load_or_fetch_history,
    _parse_lsr_df,
    _parse_oi_df,
    _parse_taker_df,
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


def _pf(df: pd.DataFrame) -> float:
    if df is None or df.empty or "pnl" not in df.columns:
        return float("nan")
    pnl = pd.to_numeric(df["pnl"], errors="coerce").fillna(0.0)
    gp = float(pnl[pnl > 0].sum())
    gl = float(-pnl[pnl < 0].sum())
    if gl <= 0:
        return float("inf") if gp > 0 else float("nan")
    return gp / gl


def _trade_metrics_from_df(df: pd.DataFrame, initial_equity: float = 100000.0) -> dict[str, Any]:
    if df is None or df.empty:
        return {
            "trades": 0,
            "pf": float("nan"),
            "ret": 0.0,
            "maxdd": 0.0,
        }
    pnl = pd.to_numeric(df["pnl"], errors="coerce").fillna(0.0)
    equity = float(initial_equity) + pnl.cumsum()
    peak = equity.cummax()
    dd = equity / peak - 1.0
    return {
        "trades": int(len(df)),
        "pf": _pf(df),
        "ret": float(equity.iloc[-1] / float(initial_equity) - 1.0),
        "maxdd": float(dd.min()) if len(dd) else 0.0,
    }


def _base_candidate_items(profile: str) -> list[dict[str, Any]]:
    all_items = {item["name"]: item for item in list(QUICK_CANDIDATES) + list(FULL_EXTRA_CANDIDATES)}
    if profile == "quick":
        focus_names = [
            "sol_shortwave_sr",
            "sol_shortwave_sr_smooth",
            "eth_shortwave_sr",
            "eth_shortwave_sr_tight",
        ]
    else:
        focus_names = [
            name for name in all_items
            if "shortwave" in name and (name.startswith("sol_") or name.startswith("eth_"))
        ]
    out: list[dict[str, Any]] = []
    for name in focus_names:
        item = all_items.get(name)
        if item is not None:
            out.append(item)
    return out


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


def _attach_message_layers(root: Path, trades: pd.DataFrame) -> pd.DataFrame:
    if trades is None or trades.empty:
        return pd.DataFrame()
    history = _load_or_fetch_history(root, refresh=False)
    oi_df = _parse_oi_df(history.get("oi_agg_btc_1d", {}))
    lsr_df = _parse_lsr_df(history.get("lsr_btcusdt_binance_4h", {}))
    taker_df = _parse_taker_df(history.get("taker_btcusdt_binance_4h", {}))
    t = _attach_features(trades, oi_df, lsr_df, taker_df)
    start_utc = pd.to_datetime(t["entry_time_utc"].min(), utc=True)
    end_utc = pd.to_datetime(t["entry_time_utc"].max(), utc=True)
    windows = _load_event_windows(root, start_utc, end_utc, include_all_modes=True)
    ann = _assign_event_annotations(t, windows)
    t["event_blocked"] = ann["blocked"].values
    t["event_identified"] = ann["identified"].values
    t["event_category"] = ann["categories"]
    t["event_title"] = ann["titles"]
    t["event_group"] = ann["groups"]
    t["event_mode"] = ann["modes"]
    mode_ser = t["event_mode"].astype(str)
    t["event_positive"] = mode_ser.str.contains("positive_catalyst", na=False)
    t["event_two_sided"] = mode_ser.str.contains("two_sided", na=False)
    t["event_observation"] = mode_ser.str.contains("observation_only", na=False)
    t["event_negative"] = mode_ser.str.contains("risk_off", na=False)
    return t


def _pick_best_variant(trades: pd.DataFrame) -> dict[str, Any]:
    variants = ["event_only", "coinglass_only", "combined_stack"]
    initial_equity = 100000.0
    evals = {v: _evaluate_variant(trades, v, initial_equity) for v in variants}
    best_name = "no_guard"
    best = None
    best_score = 0.0
    for name in variants:
        ev = evals[name]
        if int(ev["blocked_trades"]) <= 0:
            continue
        score = float(ev["score"])
        if score > best_score:
            best_score = score
            best_name = name
            best = ev
    base_metrics = _trade_metrics_from_df(trades, initial_equity)
    if best is None:
        return {
            "variant": "no_guard",
            "blocked": 0,
            "pnl_delta": 0.0,
            "dd_delta": 0.0,
            "score": 0.0,
            "gated": base_metrics,
            "top_event_groups": [],
            "decision": "继续研究",
        }
    gated_df = best["gated_df"]
    gated_metrics = _trade_metrics_from_df(gated_df, initial_equity)
    decision = "继续研究"
    if gated_metrics["pf"] >= 1.0 and gated_metrics["ret"] > 0 and gated_metrics["maxdd"] >= -0.35:
        decision = "继续深挖"
    elif float(best["pnl_delta"]) > 0 and float(best["dd_delta"]) >= 0:
        decision = "保留观察"
    return {
        "variant": best_name,
        "blocked": int(best["blocked_trades"]),
        "pnl_delta": float(best["pnl_delta"]),
        "dd_delta": float(best["dd_delta"]),
        "score": float(best["score"]),
        "gated": gated_metrics,
        "top_event_groups": list(best.get("top_event_groups", [])),
        "decision": decision,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="ALT 短波 + 消息面 overlay 研究（ETH/SOL 为主，只做 research）")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--profile", choices=["quick", "full"], default="quick")
    ap.add_argument("--out", default="")
    ap.add_argument("--json-out", default="")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    default_dir = root / "reports" / "research_raw"
    out_arg = args.out or str(default_dir / "alt_shortwave_message_overlay_latest.txt")
    json_arg = args.json_out or str(default_dir / "alt_shortwave_symbol_overlay_latest.json")
    cfg = read_config(root / "config.yml")
    rows: list[dict[str, Any]] = []
    for item in _base_candidate_items(args.profile):
        trades = _run_candidate(root, cfg, item)
        base = _trade_metrics_from_df(trades)
        trades_msg = _attach_message_layers(root, trades)
        best = _pick_best_variant(trades_msg)
        rows.append({
            "name": str(item["name"]),
            "symbol": str(item["symbol"]),
            "note": str(item.get("note", "")),
            "base": base,
            "best_overlay": best,
        })

    def sort_key(row: dict[str, Any]) -> tuple:
        gated = row["best_overlay"]["gated"]
        return (
            row["best_overlay"]["decision"] == "继续深挖",
            row["best_overlay"]["decision"] == "保留观察",
            float(gated.get("pf") or 0.0),
            float(gated.get("ret") or -1.0),
            float(row["best_overlay"].get("score") or 0.0),
        )

    rows = sorted(rows, key=sort_key, reverse=True)
    best = rows[0] if rows else None

    lines: list[str] = []
    lines.append("ALT 短波 + 消息面 overlay 研究（ETH/SOL 为主，只做 research，不改 live）")
    lines.append(f"profile: {args.profile}")
    lines.append(f"version: {cfg.get('system', {}).get('version', 'NA')}")
    lines.append("")
    lines.append("=== 候选结果 ===")
    for row in rows:
        base = row["base"]
        ov = row["best_overlay"]
        gated = ov["gated"]
        lines.append(
            f"- {row['name']}: symbol={row['symbol']} | base_trades={base['trades']} | base_pf={base['pf']:.3f} | base_ret={_fmt_pct(base['ret'])} | base_maxDD={_fmt_pct(base['maxdd'])}"
        )
        lines.append(
            f"  overlay={ov['variant']} | blocked={ov['blocked']} | pnl_delta={ov['pnl_delta']:+.2f} | maxdd_delta={_fmt_pct(ov['dd_delta'])} | score={ov['score']:+.4f} | decision={ov['decision']}"
        )
        lines.append(
            f"  gated_trades={gated['trades']} | gated_pf={gated['pf']:.3f} | gated_ret={_fmt_pct(gated['ret'])} | gated_maxDD={_fmt_pct(gated['maxdd'])}"
        )
        teg = "; ".join([str(x) for x in ov.get("top_event_groups", [])[:3]])
        if teg:
            lines.append(f"  top_event_groups={teg}")
        lines.append(f"  note: {row['note']}")
    lines.append("")
    lines.append("=== 结论 ===")
    if best is None:
        lines.append("- 无结果。")
    else:
        lines.append(f"- 当前最优：{best['name']} | symbol={best['symbol']} | overlay={best['best_overlay']['variant']} | decision={best['best_overlay']['decision']}")
        lines.append("- 消息面继续只作为 risk overlay；第二分支仍不直接升 alpha。")
        lines.append("- 优先级仍是：SOL-first，ETH-second，BTC-third。")
        gated_pf = float(best["best_overlay"]["gated"].get("pf") or 0.0)
        gated_ret = float(best["best_overlay"]["gated"].get("ret") or 0.0)
        if gated_pf < 1.0 or gated_ret <= 0:
            lines.append("- 当前 overlay 仍未把候选推到可并线标准；继续 research，不动 live。")
        else:
            lines.append("- overlay 已明显改善候选质量；进入下一轮更严格 walk-forward。")

    payload = {
        "profile": args.profile,
        "version": cfg.get("system", {}).get("version", "NA"),
        "rows": rows,
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
