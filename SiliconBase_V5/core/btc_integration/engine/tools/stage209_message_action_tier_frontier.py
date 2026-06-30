from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import contextlib

from src.backtest.io import read_config

from tools import message_stack_backtest as msb


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def _fmt_num(x: float) -> str:
    return f"{x:+.2f}"


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


def _event_risk_for_trade(row: pd.Series, windows: pd.DataFrame, *, two_sided_mult: float, obs_mult: float, pos_short_mult: float) -> tuple[float, dict[str, Any]]:
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
    total = min(float(sum(risks)), 1.75)
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


def _score_rows(trades: pd.DataFrame, windows: pd.DataFrame, variant: dict[str, Any]) -> pd.DataFrame:
    event_scores = []
    deriv_scores = []
    total_scores = []
    groups_col = []
    for _, row in trades.iterrows():
        ev_score, meta = _event_risk_for_trade(
            row,
            windows,
            two_sided_mult=float(variant.get("two_sided_mult", 0.45)),
            obs_mult=float(variant.get("obs_mult", 0.08)),
            pos_short_mult=float(variant.get("pos_short_mult", 0.60)),
        )
        dv_score = _deriv_risk_for_trade(row)
        total = float(variant.get("event_weight", 0.55)) * ev_score + float(variant.get("deriv_weight", 0.45)) * dv_score
        event_scores.append(ev_score)
        deriv_scores.append(dv_score)
        total_scores.append(total)
        groups_col.append(meta.get("groups", []))
    t = trades.copy()
    t["msg_event_score"] = event_scores
    t["msg_deriv_score"] = deriv_scores
    t["msg_total_score"] = total_scores
    t["msg_groups"] = groups_col
    return t


def _apply_tier_variant(trades: pd.DataFrame, windows: pd.DataFrame, variant: dict[str, Any], initial_equity: float) -> dict[str, Any]:
    scored = _score_rows(trades, windows, variant)
    adjusted_rows = []
    hard = 0
    mid = 0
    soft = 0
    top_groups: list[str] = []
    for _, row in scored.iterrows():
        sym = str(row.get("symbol", "")).lower()
        total = float(row.get("msg_total_score", 0.0))
        ev = float(row.get("msg_event_score", 0.0))
        dv = float(row.get("msg_deriv_score", 0.0))
        confirm = ev >= float(variant.get("min_event_confirm", 0.35)) and dv >= float(variant.get("min_deriv_confirm", 0.20))
        soft_thr = float((variant.get("soft_asset_thresholds") or {}).get(sym, variant.get("soft_thr", 0.14)))
        mid_thr = float((variant.get("mid_asset_thresholds") or {}).get(sym, variant.get("mid_thr", 0.19)))
        hard_thr = float((variant.get("hard_asset_thresholds") or {}).get(sym, variant.get("hard_thr", 0.27)))
        scale = 1.0
        action = "PASS"
        if total >= hard_thr and (
            not bool(variant.get("hard_need_confirm", False))
            or confirm
            or ev >= float(variant.get("critical_event_cut", 0.95))
        ):
            action = "HARD_BLOCK"
            scale = 0.0
            hard += 1
        elif total >= mid_thr:
            action = "REDUCE_MID"
            scale = float(variant.get("mid_scale", 0.40))
            mid += 1
        elif total >= soft_thr:
            action = "REDUCE_SOFT"
            scale = float(variant.get("soft_scale", 0.75))
            soft += 1
        if action != "PASS":
            top_groups.extend(list(row.get("msg_groups", []) or []))
        if scale <= 0.0:
            continue
        newrow = row.copy()
        newrow["pnl"] = float(row.get("pnl", 0.0)) * scale
        if "qty" in newrow:
            with contextlib.suppress(BaseException):
                newrow["qty"] = float(row.get("qty", 0.0)) * scale
        newrow["msg_action"] = action
        newrow["msg_scale"] = scale
        adjusted_rows.append(newrow)
    adjusted = pd.DataFrame(adjusted_rows)
    base_metrics = msb._trade_metrics(trades, initial_equity)
    gated_metrics = msb._trade_metrics(adjusted, initial_equity)
    pnl_delta = float(gated_metrics["total_pnl"] - base_metrics["total_pnl"])
    dd_delta = float(gated_metrics["max_drawdown"] - base_metrics["max_drawdown"])
    qty_base = float(pd.to_numeric(trades.get("qty", 0.0), errors="coerce").fillna(0.0).sum())
    qty_adj = float(pd.to_numeric(adjusted.get("qty", 0.0), errors="coerce").fillna(0.0).sum()) if not adjusted.empty else 0.0
    retained = qty_adj / qty_base if qty_base > 0 else 0.0
    score = pnl_delta / float(initial_equity) + 2.0 * dd_delta - 0.003 * hard - 0.001 * mid - 0.0005 * soft + 0.06 * retained
    vc = pd.Series(top_groups, dtype=str).value_counts().head(5)
    return {
        "variant": str(variant["name"]),
        "params": variant,
        "base": base_metrics,
        "gated": gated_metrics,
        "hard_blocked": int(hard),
        "mid_scaled": int(mid),
        "soft_scaled": int(soft),
        "retained_notional_ratio": float(retained),
        "pnl_delta": pnl_delta,
        "dd_delta": dd_delta,
        "score": float(score),
        "top_event_groups": vc.index.tolist(),
    }


def _tier_grid() -> list[dict[str, Any]]:
    return [
        {
            "name": "tiered_asset_bias_t015",
            "event_weight": 0.58,
            "deriv_weight": 0.42,
            "two_sided_mult": 0.45,
            "obs_mult": 0.08,
            "pos_short_mult": 0.60,
            "soft_thr": 0.15,
            "mid_thr": 0.20,
            "hard_thr": 0.28,
            "soft_scale": 0.75,
            "mid_scale": 0.40,
            "hard_need_confirm": True,
            "min_event_confirm": 0.33,
            "min_deriv_confirm": 0.18,
            "soft_asset_thresholds": {"btc": 0.18, "bnb": 0.12, "eth": 0.15, "sol": 0.16},
            "mid_asset_thresholds": {"btc": 0.24, "bnb": 0.18, "eth": 0.20, "sol": 0.22},
            "hard_asset_thresholds": {"btc": 0.32, "bnb": 0.25, "eth": 0.28, "sol": 0.30},
        },
        {
            "name": "tiered_balance_t014",
            "event_weight": 0.55,
            "deriv_weight": 0.45,
            "two_sided_mult": 0.45,
            "obs_mult": 0.08,
            "pos_short_mult": 0.60,
            "soft_thr": 0.14,
            "mid_thr": 0.19,
            "hard_thr": 0.27,
            "soft_scale": 0.72,
            "mid_scale": 0.42,
            "hard_need_confirm": True,
            "min_event_confirm": 0.35,
            "min_deriv_confirm": 0.20,
            "soft_asset_thresholds": {"btc": 0.16, "bnb": 0.12, "eth": 0.14, "sol": 0.14},
            "mid_asset_thresholds": {"btc": 0.22, "bnb": 0.17, "eth": 0.19, "sol": 0.19},
            "hard_asset_thresholds": {"btc": 0.30, "bnb": 0.24, "eth": 0.27, "sol": 0.27},
        },
        {
            "name": "tiered_preserve_t018",
            "event_weight": 0.55,
            "deriv_weight": 0.45,
            "two_sided_mult": 0.45,
            "obs_mult": 0.08,
            "pos_short_mult": 0.60,
            "soft_thr": 0.18,
            "mid_thr": 0.24,
            "hard_thr": 0.32,
            "soft_scale": 0.78,
            "mid_scale": 0.52,
            "hard_need_confirm": True,
            "min_event_confirm": 0.35,
            "min_deriv_confirm": 0.20,
            "soft_asset_thresholds": {"btc": 0.20, "bnb": 0.16, "eth": 0.18, "sol": 0.18},
            "mid_asset_thresholds": {"btc": 0.27, "bnb": 0.22, "eth": 0.24, "sol": 0.24},
            "hard_asset_thresholds": {"btc": 0.35, "bnb": 0.30, "eth": 0.32, "sol": 0.32},
        },
        {
            "name": "tiered_capture_t010",
            "event_weight": 0.60,
            "deriv_weight": 0.40,
            "two_sided_mult": 0.40,
            "obs_mult": 0.06,
            "pos_short_mult": 0.58,
            "soft_thr": 0.10,
            "mid_thr": 0.15,
            "hard_thr": 0.22,
            "soft_scale": 0.65,
            "mid_scale": 0.30,
            "hard_need_confirm": False,
            "soft_asset_thresholds": {"btc": 0.12, "bnb": 0.08, "eth": 0.10, "sol": 0.10},
            "mid_asset_thresholds": {"btc": 0.18, "bnb": 0.13, "eth": 0.15, "sol": 0.15},
            "hard_asset_thresholds": {"btc": 0.26, "bnb": 0.20, "eth": 0.22, "sol": 0.22},
        },
        {
            "name": "tiered_confirm_strict_t020",
            "event_weight": 0.62,
            "deriv_weight": 0.38,
            "two_sided_mult": 0.40,
            "obs_mult": 0.05,
            "pos_short_mult": 0.56,
            "soft_thr": 0.20,
            "mid_thr": 0.26,
            "hard_thr": 0.34,
            "soft_scale": 0.80,
            "mid_scale": 0.55,
            "hard_need_confirm": True,
            "min_event_confirm": 0.38,
            "min_deriv_confirm": 0.22,
            "soft_asset_thresholds": {"btc": 0.23, "bnb": 0.18, "eth": 0.20, "sol": 0.20},
            "mid_asset_thresholds": {"btc": 0.29, "bnb": 0.24, "eth": 0.26, "sol": 0.26},
            "hard_asset_thresholds": {"btc": 0.38, "bnb": 0.32, "eth": 0.34, "sol": 0.34},
        },
    ]


def _two_year_slice(trades: pd.DataFrame) -> pd.DataFrame:
    end = trades["entry_time_utc"].max()
    start = end - pd.Timedelta(days=365 * 2)
    return trades[trades["entry_time_utc"] >= start].copy()


def _walkforward_tier(trades: pd.DataFrame, windows: pd.DataFrame, initial_equity: float, variant: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    agg_pnl = 0.0
    agg_dd = 0.0
    agg_hard = 0
    agg_mid = 0
    agg_soft = 0
    retained_list: list[float] = []
    for year, start, end in msb._calendar_year_folds(trades):
        train = trades[trades["entry_time_utc"] < start].copy()
        test = trades[(trades["entry_time_utc"] >= start) & (trades["entry_time_utc"] < end)].copy()
        if train.empty or test.empty:
            continue
        ev = _apply_tier_variant(test, windows, variant, initial_equity)
        agg_pnl += float(ev["pnl_delta"])
        agg_dd += float(ev["dd_delta"])
        agg_hard += int(ev["hard_blocked"])
        agg_mid += int(ev["mid_scaled"])
        agg_soft += int(ev["soft_scaled"])
        retained_list.append(float(ev["retained_notional_ratio"]))
        rows.append({
            "year": int(year),
            "pnl_delta": float(ev["pnl_delta"]),
            "dd_delta": float(ev["dd_delta"]),
            "hard": int(ev["hard_blocked"]),
            "mid": int(ev["mid_scaled"]),
            "soft": int(ev["soft_scaled"]),
            "retained": float(ev["retained_notional_ratio"]),
        })
    return {
        "rows": rows,
        "aggregate_pnl_delta": float(agg_pnl),
        "aggregate_dd_delta": float(agg_dd),
        "aggregate_hard": int(agg_hard),
        "aggregate_mid": int(agg_mid),
        "aggregate_soft": int(agg_soft),
        "avg_retained": float(np.mean(retained_list)) if retained_list else 0.0,
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
    recent2y = _two_year_slice(trades)

    results: list[dict[str, Any]] = []
    for variant in _tier_grid():
        full_ev = _apply_tier_variant(trades, windows, variant, initial_equity)
        recent_ev = _apply_tier_variant(recent2y, windows, variant, initial_equity) if not recent2y.empty else {
            "hard_blocked": 0,
            "mid_scaled": 0,
            "soft_scaled": 0,
            "retained_notional_ratio": 0.0,
            "pnl_delta": 0.0,
            "dd_delta": 0.0,
            "score": 0.0,
            "gated": {"trades": 0, "profit_factor": 0.0, "total_return": 0.0, "max_drawdown": 0.0},
        }
        wf = _walkforward_tier(trades, windows, initial_equity, variant)
        wf_score = float(wf["aggregate_pnl_delta"] / initial_equity + 2.0 * wf["aggregate_dd_delta"] + 0.04 * wf["avg_retained"])
        composite = float(0.70 * full_ev["score"] + 1.00 * recent_ev["score"] + 0.90 * wf_score)
        results.append({
            "name": variant["name"],
            "params": variant,
            "full": full_ev,
            "recent2y": recent_ev,
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
        near_best = [r for r in top if r["composite_score"] >= best["composite_score"] * 0.70]
        if near_best:
            recommended = max(
                near_best,
                key=lambda r: (
                    -r["full"]["hard_blocked"],
                    r["full"]["retained_notional_ratio"],
                    r["composite_score"],
                ),
            )
            # Then pick the zero-hard variant with the highest retention and acceptable score.
            zero_hard = [r for r in near_best if r["full"]["hard_blocked"] == 0]
            if zero_hard:
                recommended = max(zero_hard, key=lambda r: (r["full"]["retained_notional_ratio"], r["composite_score"]))

    lines: list[str] = []
    lines.append("Stage209 message action tier frontier")
    lines.append("")
    lines.append("[why]")
    lines.append("- 这版把消息层从‘二元拦单’改成‘通过 / 轻降仓 / 中降仓 / 硬拦截’四态。")
    lines.append("- 目标不是多拦单，而是减少误杀：低确定性消息不再直接 veto。")
    lines.append("- 这版只做 research，不动 demo runtime。")
    lines.append("")
    lines.append("[baseline]")
    lines.append(f"- baseline_trades={len(trades)} | baseline_ret={_fmt_pct(msb._trade_metrics(trades, initial_equity)['total_return'])} | baseline_pf={msb._trade_metrics(trades, initial_equity)['profit_factor']:.3f} | baseline_maxdd={_fmt_pct(msb._trade_metrics(trades, initial_equity)['max_drawdown'])}")
    lines.append("")
    lines.append("[top_tier_variants]")
    for row in top:
        full = row["full"]
        r2 = row["recent2y"]
        wf = row["wf"]
        gm_full = row["gated_metrics_full"]
        gm_r2 = row["gated_metrics_recent2y"]
        lines.append(
            f"- {row['name']} | composite={row['composite_score']:+.4f} | full pnl_delta={_fmt_num(full['pnl_delta'])} dd_delta={_fmt_pct(full['dd_delta'])} hard={full['hard_blocked']} mid={full['mid_scaled']} soft={full['soft_scaled']} retain={_fmt_pct(full['retained_notional_ratio'])}"
        )
        lines.append(
            f"  gated_full: trades={gm_full['trades']} pf={gm_full['profit_factor']:.3f} ret={_fmt_pct(gm_full['total_return'])} maxdd={_fmt_pct(gm_full['max_drawdown'])}"
        )
        lines.append(
            f"  gated_2y: trades={gm_r2['trades']} pf={gm_r2['profit_factor']:.3f} ret={_fmt_pct(gm_r2['total_return'])} maxdd={_fmt_pct(gm_r2['max_drawdown'])} | pnl_delta={_fmt_num(r2['pnl_delta'])} dd_delta={_fmt_pct(r2['dd_delta'])} hard={r2['hard_blocked']} mid={r2['mid_scaled']} soft={r2['soft_scaled']} retain={_fmt_pct(r2['retained_notional_ratio'])}"
        )
        lines.append(
            f"  wf: pnl_delta={_fmt_num(wf['aggregate_pnl_delta'])} dd_delta={_fmt_pct(wf['aggregate_dd_delta'])} hard={wf['aggregate_hard']} mid={wf['aggregate_mid']} soft={wf['aggregate_soft']} retain={_fmt_pct(wf['avg_retained'])} | top_groups={'; '.join(row['top_event_groups'][:4]) if row['top_event_groups'] else '-'}"
        )
    lines.append("")
    lines.append("[action_rules]")
    lines.append("- hard_block 只留给‘事件高危 + 衍生品确认共振’或临界极值。")
    lines.append("- mid_reduce 处理高分但还没到必须 veto 的情况。")
    lines.append("- soft_reduce 处理低确定性消息，避免统一阈值误伤。")
    lines.append("- BTC 阈值更高；BNB 对交易所/政策更敏感；ETH/SOL 对 crypto/生态消息更敏感。")
    lines.append("")
    lines.append("[conclusion]")
    if recommended:
        lines.append(f"- 推荐先用 {recommended['name']} 做下一轮消息动作层基线。")
        lines.append(f"- 它的 full hard={recommended['full']['hard_blocked']} / mid={recommended['full']['mid_scaled']} / soft={recommended['full']['soft_scaled']} / retain={_fmt_pct(recommended['full']['retained_notional_ratio'])}。")
        lines.append("- 先把‘统一 veto’改成‘分层动作’，再看主线提频和消息共振。")
    else:
        lines.append("- 本轮没有跑出可推荐的消息动作层方案。")

    out_txt.parent.mkdir(parents=True, exist_ok=True)
    out_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    payload = {
        "top": top,
        "recommended": recommended,
        "count_variants": len(results),
    }
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage209 message action tier frontier")
    ap.add_argument("--project-dir", type=Path, default=Path("."))
    args = ap.parse_args()
    root = args.project_dir.resolve()
    raw = root / "reports" / "research_raw"
    run(root, raw / "stage209_message_action_tier_frontier_latest.txt", raw / "stage209_message_action_tier_frontier_latest.json")


if __name__ == "__main__":
    main()
