from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest.io import read_config

from tools import message_stack_backtest as msb


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def _fmt_num(x: float) -> str:
    return f"{x:+.2f}"


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None or (isinstance(x, float) and math.isnan(x)):
            return default
        return float(x)
    except BaseException:
        return default


def _load_trades_fallback(project_dir: Path) -> pd.DataFrame:
    try:
        return msb._load_trades(project_dir)
    except BaseException:
        candidates = [
            project_dir / "reports" / "current_demo_strategy_trades_latest.csv",
            project_dir / "reports" / "run_latest" / "trades.csv",
        ]
        for p in candidates:
            if p.exists():
                df = pd.read_csv(p)
                if not df.empty:
                    return df
        raise


def _asset_relevance(symbol: str, category: str, title: str, tags: str, group_id: str) -> float:
    sym = str(symbol).lower()
    cat = str(category).lower()
    text = " ".join([str(title).lower(), str(tags).lower(), str(group_id).lower()])
    base = {
        "macro": {"btc": 1.00, "bnb": 0.60, "eth": 0.85, "sol": 0.75, "default": 0.80},
        "policy": {"btc": 0.95, "bnb": 0.80, "eth": 0.90, "sol": 0.80, "default": 0.85},
        "crypto": {"btc": 0.85, "bnb": 0.75, "eth": 0.90, "sol": 0.90, "default": 0.82},
        "us_equity": {"btc": 0.85, "bnb": 0.50, "eth": 0.70, "sol": 0.60, "default": 0.68},
        "exchange": {"btc": 0.70, "bnb": 1.05, "eth": 0.70, "sol": 0.70, "default": 0.75},
        "default": {"default": 0.80},
    }
    weight = base.get(cat, base["default"]).get(sym, base.get(cat, base["default"]).get("default", 0.8))
    asset_keys = {
        "btc": ["bitcoin", " btc", "btc ", "etf", "treasury", "microstrategy", "saylor"],
        "bnb": ["binance", "bnb", "bsc", "cz"],
        "eth": ["ethereum", " ether", "eth ", "defi", "rollup", "l2"],
        "sol": ["solana", "sol ", " memecoin", "dex", "jito", "raydium"],
    }
    if any(k in text for k in asset_keys.get(sym, [])):
        weight *= 1.25
    if "binance" in text and sym == "bnb":
        weight *= 1.15
    if "etf" in text and sym == "btc":
        weight *= 1.10
    return max(0.25, min(1.50, weight))


SEVERITY_W = {
    "critical": 1.00,
    "high": 0.82,
    "medium": 0.55,
    "low": 0.30,
    "default": 0.45,
}

MODE_SIDE_W = {
    "LONG": {
        "risk_off": 1.00,
        "two_sided": 0.55,
        "positive_catalyst": 0.00,
        "observation_only": 0.12,
        "default": 0.20,
    },
    "SHORT": {
        "risk_off": 0.10,
        "two_sided": 0.35,
        "positive_catalyst": 0.72,
        "observation_only": 0.10,
        "default": 0.15,
    },
}


def _freshness_w(age_hours: float) -> float:
    if age_hours <= 6:
        return 1.00
    if age_hours <= 24:
        return 0.82
    if age_hours <= 72:
        return 0.58
    return 0.35


def _event_risk_for_trade(row: pd.Series, windows: pd.DataFrame, *, two_sided_mult: float = 0.55, obs_mult: float = 0.12, pos_short_mult: float = 0.72) -> tuple[float, dict[str, Any]]:
    ts = row["entry_time_utc"]
    sym = str(row.get("symbol", "")).lower()
    side = str(row.get("side", "")).upper()
    matched = windows[(windows["start_utc"] <= ts) & (windows["end_utc"] >= ts)]
    if matched.empty:
        return 0.0, {"groups": [], "titles": [], "modes": []}
    risks: list[float] = []
    groups: list[str] = []
    titles: list[str] = []
    modes: list[str] = []
    seen_groups = set()
    for _, ev in matched.iterrows():
        mode = str(ev.get("event_mode", "default") or "default")
        sev = str(ev.get("severity", "default") or "default").lower()
        cat = str(ev.get("category", "default") or "default")
        tags = str(ev.get("profile_tags", "") or "")
        title = str(ev.get("title", "") or "")
        gid = str(ev.get("group_id", title) or title)
        age_hours = max(0.0, float((ts - pd.to_datetime(ev["start_utc"], utc=True)).total_seconds()) / 3600.0)
        sev_w = SEVERITY_W.get(sev, SEVERITY_W["default"])
        side_map = dict(MODE_SIDE_W.get(side, MODE_SIDE_W["LONG"]))
        side_map["two_sided"] = two_sided_mult if side == "LONG" else max(0.20, two_sided_mult - 0.10)
        side_map["observation_only"] = obs_mult
        side_map["positive_catalyst"] = 0.0 if side == "LONG" else pos_short_mult
        mode_w = side_map.get(mode, side_map["default"])
        asset_w = _asset_relevance(sym, cat, title, tags, gid)
        risk = sev_w * mode_w * _freshness_w(age_hours) * asset_w
        if gid in seen_groups:
            risk *= 0.35
        else:
            seen_groups.add(gid)
        risks.append(risk)
        groups.append(gid)
        titles.append(title)
        modes.append(mode)
    total = float(sum(risks))
    total = min(total, 1.75)
    return total, {"groups": groups[:5], "titles": titles[:3], "modes": list(dict.fromkeys(modes))}


def _deriv_risk_for_trade(row: pd.Series) -> float:
    side = str(row.get("side", "")).upper()
    risk = 0.0
    oi_down = bool(row.get("oi_down_shock", False))
    lsr_hi = bool(row.get("lsr_hi", False))
    lsr_lo = bool(row.get("lsr_lo", False))
    taker_buy = bool(row.get("taker_buy", False))
    taker_sell = bool(row.get("taker_sell", False))
    if side == "LONG":
        if oi_down:
            risk += 0.35
        if lsr_hi and taker_sell:
            risk += 0.75
        elif lsr_hi or taker_sell:
            risk += 0.25
    else:
        if lsr_lo and taker_buy:
            risk += 0.65
        elif lsr_lo or taker_buy:
            risk += 0.22
    return min(risk, 1.10)


def _apply_variant(trades: pd.DataFrame, windows: pd.DataFrame, variant: dict[str, Any], initial_equity: float) -> dict[str, Any]:
    event_scores = []
    deriv_scores = []
    total_scores = []
    blocked = []
    top_groups: list[str] = []
    for _, row in trades.iterrows():
        ev_score, meta = _event_risk_for_trade(
            row,
            windows,
            two_sided_mult=float(variant.get("two_sided_mult", 0.55)),
            obs_mult=float(variant.get("obs_mult", 0.12)),
            pos_short_mult=float(variant.get("pos_short_mult", 0.72)),
        )
        dv_score = _deriv_risk_for_trade(row)
        total = float(variant.get("event_weight", 0.65)) * ev_score + float(variant.get("deriv_weight", 0.35)) * dv_score
        if bool(variant.get("need_confirm")) and not (
            (ev_score >= float(variant.get("min_event_confirm", 0.45)) and dv_score >= float(variant.get("min_deriv_confirm", 0.25)))
            or ev_score >= float(variant.get("critical_event_cut", 0.95))
        ):
            block = False
        else:
            sym = str(row.get("symbol", "")).lower()
            thr_map = variant.get("asset_thresholds", {}) or {}
            threshold = float(thr_map.get(sym, variant.get("threshold", 0.90)))
            block = total >= threshold
        event_scores.append(ev_score)
        deriv_scores.append(dv_score)
        total_scores.append(total)
        blocked.append(block)
        if block:
            top_groups.extend(meta.get("groups", []))
    t = trades.copy()
    t["msg_event_score"] = event_scores
    t["msg_deriv_score"] = deriv_scores
    t["msg_total_score"] = total_scores
    t["msg_blocked"] = blocked
    blocked_mask = t["msg_blocked"].astype(bool)
    blocked_df = t.loc[blocked_mask].copy()
    gated_df = t.loc[~blocked_mask].copy()
    base_metrics = msb._trade_metrics(t, initial_equity)
    gated_metrics = msb._trade_metrics(gated_df, initial_equity)
    pnl_delta = float(gated_metrics["total_pnl"] - base_metrics["total_pnl"])
    dd_delta = float(gated_metrics["max_drawdown"] - base_metrics["max_drawdown"])
    score = msb._score_variant(base_metrics, gated_metrics, int(blocked_mask.sum()), initial_equity)
    vc = pd.Series(top_groups, dtype=str).value_counts().head(5)
    return {
        "variant": str(variant["name"]),
        "params": variant,
        "base": base_metrics,
        "gated": gated_metrics,
        "blocked_trades": int(blocked_mask.sum()),
        "blocked_long": int((blocked_df["side"].astype(str).str.upper() == "LONG").sum()) if not blocked_df.empty else 0,
        "blocked_short": int((blocked_df["side"].astype(str).str.upper() == "SHORT").sum()) if not blocked_df.empty else 0,
        "pnl_delta": pnl_delta,
        "dd_delta": dd_delta,
        "score": score,
        "top_event_groups": vc.index.tolist(),
        "blocked_df": blocked_df,
        "gated_df": gated_df,
        "avg_total_score": float(pd.Series(total_scores).mean()) if total_scores else 0.0,
        "avg_blocked_score": float(blocked_df["msg_total_score"].mean()) if not blocked_df.empty else 0.0,
    }


def _variant_grid() -> list[dict[str, Any]]:
    return [
        {
            "name": "weighted_preserve_t022",
            "event_weight": 0.55,
            "deriv_weight": 0.45,
            "threshold": 0.22,
            "need_confirm": False,
            "two_sided_mult": 0.55,
            "obs_mult": 0.08,
            "pos_short_mult": 0.60,
            "asset_thresholds": {"btc": 0.24, "bnb": 0.20, "eth": 0.22, "sol": 0.22},
        },
        {
            "name": "weighted_balance_t015",
            "event_weight": 0.55,
            "deriv_weight": 0.45,
            "threshold": 0.15,
            "need_confirm": False,
            "two_sided_mult": 0.45,
            "obs_mult": 0.08,
            "pos_short_mult": 0.60,
            "asset_thresholds": {"btc": 0.17, "bnb": 0.13, "eth": 0.15, "sol": 0.15},
        },
        {
            "name": "weighted_capture_t010",
            "event_weight": 0.62,
            "deriv_weight": 0.38,
            "threshold": 0.10,
            "need_confirm": False,
            "two_sided_mult": 0.45,
            "obs_mult": 0.08,
            "pos_short_mult": 0.60,
            "asset_thresholds": {"btc": 0.12, "bnb": 0.08, "eth": 0.10, "sol": 0.10},
        },
        {
            "name": "weighted_capture_plus_t008",
            "event_weight": 0.55,
            "deriv_weight": 0.45,
            "threshold": 0.08,
            "need_confirm": False,
            "two_sided_mult": 0.55,
            "obs_mult": 0.08,
            "pos_short_mult": 0.60,
            "asset_thresholds": {"btc": 0.10, "bnb": 0.06, "eth": 0.08, "sol": 0.08},
        },
        {
            "name": "weighted_strict_confirm_t090",
            "event_weight": 0.68,
            "deriv_weight": 0.32,
            "threshold": 0.90,
            "need_confirm": True,
            "min_event_confirm": 0.38,
            "min_deriv_confirm": 0.20,
            "critical_event_cut": 0.88,
            "two_sided_mult": 0.35,
            "obs_mult": 0.05,
            "pos_short_mult": 0.52,
            "asset_thresholds": {"btc": 0.98, "bnb": 0.72, "eth": 0.90, "sol": 0.84},
        },
    ]


def _two_year_slice(trades: pd.DataFrame) -> pd.DataFrame:
    end = trades["entry_time_utc"].max()
    start = end - pd.Timedelta(days=365*2)
    return trades[trades["entry_time_utc"] >= start].copy()


def _walkforward_variant(trades: pd.DataFrame, windows: pd.DataFrame, initial_equity: float, variant: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    agg_blocked = 0
    agg_pnl = 0.0
    agg_dd = 0.0
    for year, start, end in msb._calendar_year_folds(trades):
        train = trades[trades["entry_time_utc"] < start].copy()
        test = trades[(trades["entry_time_utc"] >= start) & (trades["entry_time_utc"] < end)].copy()
        if train.empty or test.empty:
            continue
        # Variant is fixed by design; measure it out-of-sample.
        ev = _apply_variant(test, windows, variant, initial_equity)
        agg_blocked += int(ev["blocked_trades"])
        agg_pnl += float(ev["pnl_delta"])
        agg_dd += float(ev["dd_delta"])
        rows.append({
            "year": int(year),
            "blocked": int(ev["blocked_trades"]),
            "pnl_delta": float(ev["pnl_delta"]),
            "dd_delta": float(ev["dd_delta"]),
            "score": float(ev["score"]),
        })
    return {
        "rows": rows,
        "aggregate_blocked": agg_blocked,
        "aggregate_pnl_delta": agg_pnl,
        "aggregate_dd_delta": agg_dd,
        "selected_nonbase_folds": len(rows),
    }


def run(project_dir: Path, out_txt: Path, out_json: Path) -> None:
    cfg = read_config(project_dir / "config.yml")
    initial_equity = float(cfg.get("portfolio", {}).get("initial_equity", 100000.0))
    trades = _load_trades_fallback(project_dir)
    hist = msb._load_or_fetch_history(project_dir, refresh=False)
    oi_df = msb._parse_oi_df(hist.get("oi_agg_btc_1d", {}))
    lsr_df = msb._parse_lsr_df(hist.get("lsr_btcusdt_binance_4h", {}))
    taker_df = msb._parse_taker_df(hist.get("taker_btcusdt_binance_4h", {}))

    trades = msb._attach_features(trades, oi_df, lsr_df, taker_df)
    start_utc = trades["entry_time_utc"].min().floor("15min")
    end_utc = trades["entry_time_utc"].max().ceil("15min")
    windows = msb._load_event_windows(project_dir, start_utc, end_utc, include_all_modes=True)

    uniform_event_mask, cats, titles, groups = msb._assign_event_blocks(trades, windows)
    trades["event_blocked"] = uniform_event_mask.values
    trades["event_category"] = cats
    trades["event_title"] = titles
    trades["event_group"] = groups

    # legacy references
    legacy_combined = msb._evaluate_variant(trades, "combined_stack", initial_equity)
    legacy_event = msb._evaluate_variant(trades, "event_only", initial_equity)
    recent2y = _two_year_slice(trades)

    results: list[dict[str, Any]] = []
    for variant in _variant_grid():
        full_ev = _apply_variant(trades, windows, variant, initial_equity)
        recent_ev = _apply_variant(recent2y, windows, variant, initial_equity) if not recent2y.empty else {
            "blocked_trades": 0, "pnl_delta": 0.0, "dd_delta": 0.0, "score": 0.0, "gated": {"trades": 0, "profit_factor": 0.0, "total_return": 0.0, "max_drawdown": 0.0}
        }
        wf = _walkforward_variant(trades, windows, initial_equity, variant)
        wf_score = float(wf["aggregate_pnl_delta"] / initial_equity + 2.0 * wf["aggregate_dd_delta"])
        composite = float(0.80 * full_ev["score"] + 1.00 * recent_ev["score"] + 0.90 * wf_score - 0.004 * full_ev["blocked_trades"])
        results.append({
            "name": variant["name"],
            "params": variant,
            "full": {k: v for k, v in full_ev.items() if k not in {"blocked_df", "gated_df", "base"}},
            "recent2y": {k: v for k, v in recent_ev.items() if k not in {"blocked_df", "gated_df", "base"}},
            "wf": wf,
            "composite_score": composite,
            "gated_metrics_full": full_ev["gated"],
            "gated_metrics_recent2y": recent_ev["gated"],
            "top_event_groups": full_ev["top_event_groups"],
        })

    results.sort(key=lambda r: (r["composite_score"], r["recent2y"]["score"], r["full"]["score"]), reverse=True)
    top = results[:6]

    best = top[0] if top else None
    recommended = best
    if best is not None:
        near_best = [r for r in top if r["composite_score"] >= best["composite_score"] * 0.90]
        if near_best:
            recommended = min(near_best, key=lambda r: (r["full"]["blocked_trades"], -r["composite_score"]))
    lines: list[str] = []
    lines.append("Stage208 message quantization frontier")
    lines.append("")
    lines.append("[why]")
    lines.append("- 先做消息标准化，再决定是否拦单；不再拿统一规则覆盖所有消息和所有币。")
    lines.append("- 这版只做 research，不动 demo runtime。")
    lines.append("- 消息分值 = 严重度 × 事件模式 × 币种映射 × 时效衰减 × 衍生品确认。")
    lines.append("")
    lines.append("[legacy_baseline]")
    lines.append(f"- event_only: blocked={legacy_event['blocked_trades']} | pnl_delta={_fmt_num(legacy_event['pnl_delta'])} | maxdd_delta={_fmt_pct(legacy_event['dd_delta'])} | score={legacy_event['score']:+.4f}")
    lines.append(f"- combined_stack: blocked={legacy_combined['blocked_trades']} | pnl_delta={_fmt_num(legacy_combined['pnl_delta'])} | maxdd_delta={_fmt_pct(legacy_combined['dd_delta'])} | score={legacy_combined['score']:+.4f}")
    lines.append("")
    lines.append(f"- baseline_trades={len(trades)} | recent2y_trades={len(recent2y)}")
    lines.append("")
    lines.append("[top_weighted_variants]")
    for row in top:
        full = row["full"]
        r2 = row["recent2y"]
        wf = row["wf"]
        gm_full = row["gated_metrics_full"]
        gm_r2 = row["gated_metrics_recent2y"]
        lines.append(
            f"- {row['name']} | composite={row['composite_score']:+.4f} | full blocked={full['blocked_trades']} pnl_delta={_fmt_num(full['pnl_delta'])} dd_delta={_fmt_pct(full['dd_delta'])} | 近2y blocked={r2['blocked_trades']} pnl_delta={_fmt_num(r2['pnl_delta'])} dd_delta={_fmt_pct(r2['dd_delta'])} | wf blocked={wf['aggregate_blocked']} pnl_delta={_fmt_num(wf['aggregate_pnl_delta'])} dd_delta={_fmt_pct(wf['aggregate_dd_delta'])}"
        )
        lines.append(
            f"  gated_full: trades={gm_full['trades']} pf={gm_full['profit_factor']:.3f} ret={_fmt_pct(gm_full['total_return'])} maxdd={_fmt_pct(gm_full['max_drawdown'])}"
        )
        lines.append(
            f"  gated_2y: trades={gm_r2['trades']} pf={gm_r2['profit_factor']:.3f} ret={_fmt_pct(gm_r2['total_return'])} maxdd={_fmt_pct(gm_r2['max_drawdown'])} | top_groups={'; '.join(row['top_event_groups'][:4]) if row['top_event_groups'] else '-'}"
        )
    lines.append("")
    lines.append("[standardization_rules]")
    lines.append("- 负面 risk_off 对 LONG 权重大于正面 positive_catalyst 对 SHORT。")
    lines.append("- two_sided 只给中等权重，避免‘有消息就一刀切’。")
    lines.append("- 观察类消息 observation_only 只保留很轻权重。")
    lines.append("- BTC 更吃宏观/ETF/资金主线；BNB 更吃交易所/政策；ETH/SOL 更吃 crypto/生态类。")
    lines.append("- 若事件风险和衍生品风险同时共振，才允许更激进拦单。")
    lines.append("")
    lines.append("[conclusion]")
    if recommended:
        lines.append(f"- 推荐先用 {recommended['name']} 做下一轮消息面标准化基线。")
        if best and recommended["name"] != best["name"]:
            lines.append(f"- {recommended['name']} 不是收益最高，但在接近最优收益下拦单更少。")
        lines.append("- 目标不是拦更多单，而是更少误杀、更少统一标准误判。")
    else:
        lines.append("- 本轮没有跑出可推荐的加权消息变体。")

    out_txt.parent.mkdir(parents=True, exist_ok=True)
    out_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    payload = {
        "legacy_event_only": {
            "blocked": int(legacy_event["blocked_trades"]),
            "pnl_delta": float(legacy_event["pnl_delta"]),
            "dd_delta": float(legacy_event["dd_delta"]),
            "score": float(legacy_event["score"]),
        },
        "legacy_combined_stack": {
            "blocked": int(legacy_combined["blocked_trades"]),
            "pnl_delta": float(legacy_combined["pnl_delta"]),
            "dd_delta": float(legacy_combined["dd_delta"]),
            "score": float(legacy_combined["score"]),
        },
        "top": top,
        "recommended": recommended,
        "count_variants": len(results),
    }
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage208 message quantization frontier")
    ap.add_argument("--project-dir", type=Path, default=Path("."))
    args = ap.parse_args()
    root = args.project_dir.resolve()
    raw = root / "reports" / "research_raw"
    run(root, raw / "stage208_message_quantization_frontier_latest.txt", raw / "stage208_message_quantization_frontier_latest.json")


if __name__ == "__main__":
    main()
