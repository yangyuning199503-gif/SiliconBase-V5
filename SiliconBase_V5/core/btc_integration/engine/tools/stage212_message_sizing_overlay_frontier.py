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

import tools.stage210_common_event_message_model_frontier as s210
import tools.stage211_future_event_runtime_bridge_frontier as s211
from src.backtest.io import read_config

from tools import message_stack_backtest as msb

ASSETS = ["btc", "bnb", "eth", "sol"]


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def _fmt_num(x: float) -> str:
    return f"{x:+.2f}"


def _two_year_slice(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return trades.copy()
    end_ts = pd.to_datetime(trades["entry_time_utc"], utc=True).max()
    start_ts = end_ts - pd.DateOffset(years=2)
    return trades[pd.to_datetime(trades["entry_time_utc"], utc=True) >= start_ts].copy()


SUPPORT_MODE_W = {
    "LONG": {
        "positive_catalyst": 1.00,
        "risk_off": 0.00,
        "two_sided": 0.18,
        "observation_only": 0.05,
        "default": 0.10,
    },
    "SHORT": {
        "positive_catalyst": 0.00,
        "risk_off": 1.00,
        "two_sided": 0.18,
        "observation_only": 0.05,
        "default": 0.10,
    },
}

ADVERSE_MODE_W = {
    "LONG": {
        "positive_catalyst": 0.00,
        "risk_off": 1.00,
        "two_sided": 0.48,
        "observation_only": 0.08,
        "default": 0.20,
    },
    "SHORT": {
        "positive_catalyst": 1.00,
        "risk_off": 0.00,
        "two_sided": 0.42,
        "observation_only": 0.08,
        "default": 0.18,
    },
}


def _event_support_adverse_for_trade(row: pd.Series, windows: pd.DataFrame, variant: dict[str, Any]) -> tuple[float, float, dict[str, Any]]:
    ts = row["entry_time_utc"]
    sym = str(row.get("symbol", "") or "").lower()
    side = str(row.get("side", "LONG") or "LONG").upper()
    phase_weights = variant.get("phase_weights", {}) or {}
    support_scores: list[float] = []
    adverse_scores: list[float] = []
    meta_rows: list[dict[str, Any]] = []
    seen_groups: set[str] = set()
    for _, ev in windows.iterrows():
        start_utc = pd.to_datetime(ev["start_utc"], utc=True)
        end_utc = pd.to_datetime(ev["end_utc"], utc=True)
        cls = s210._classify_event(str(ev.get("title", "") or ""), str(ev.get("category", "generic") or "generic"), str(ev.get("profile_tags", "") or ""))
        phase = s210._phase_name(ts, start_utc, end_utc, cls)
        if phase is None:
            continue
        sev = str(ev.get("severity", "default") or "default").lower()
        cat = str(ev.get("category", "generic") or "generic")
        title = str(ev.get("title", "") or "")
        tags = str(ev.get("profile_tags", "") or "")
        gid = str(ev.get("group_id", title) or title)
        mode = str(ev.get("event_mode", "default") or "default")
        sev_w = s210.SEVERITY_W.get(sev, s210.SEVERITY_W["default"])
        asset_w = s210._asset_relevance(sym, cat, title, tags, gid)
        class_w = float(s210.CAL_CLASS_SPECS.get(cls, s210.CAL_CLASS_SPECS["generic"])["class_weight"])
        phase_w = float(phase_weights.get(phase, 0.0))
        support = sev_w * float(SUPPORT_MODE_W.get(side, SUPPORT_MODE_W["LONG"]).get(mode, 0.0)) * asset_w * class_w * phase_w
        adverse = sev_w * float(ADVERSE_MODE_W.get(side, ADVERSE_MODE_W["LONG"]).get(mode, 0.0)) * asset_w * class_w * phase_w
        if gid in seen_groups:
            support *= 0.35
            adverse *= 0.35
        else:
            seen_groups.add(gid)
        support_scores.append(support)
        adverse_scores.append(adverse)
        meta_rows.append({"group": gid, "phase": phase, "class": cls, "title": title, "mode": mode})
    support_total = min(float(sum(support_scores)), 1.60)
    adverse_total = min(float(sum(adverse_scores)), 1.60)
    return support_total, adverse_total, {"matches": meta_rows[:6]}


def _deriv_support_adverse(row: pd.Series) -> tuple[float, float]:
    side = str(row.get("side", "LONG") or "LONG").upper()
    support = 0.0
    adverse = 0.0
    oi_down = bool(row.get("oi_down_shock", False))
    lsr_hi = bool(row.get("lsr_hi", False))
    lsr_lo = bool(row.get("lsr_lo", False))
    taker_buy = bool(row.get("taker_buy", False))
    taker_sell = bool(row.get("taker_sell", False))
    if side == "LONG":
        if oi_down:
            adverse += 0.28
        if lsr_hi and taker_sell:
            adverse += 0.72
        elif lsr_hi or taker_sell:
            adverse += 0.24
        if lsr_lo and taker_buy:
            support += 0.58
        elif lsr_lo or taker_buy:
            support += 0.18
    else:
        if lsr_lo and taker_buy:
            adverse += 0.64
        elif lsr_lo or taker_buy:
            adverse += 0.22
        if lsr_hi and taker_sell:
            support += 0.62
        elif lsr_hi or taker_sell:
            support += 0.20
        if oi_down:
            support += 0.12
    return min(support, 1.00), min(adverse, 1.00)


def _score_rows(trades: pd.DataFrame, windows: pd.DataFrame, variant: dict[str, Any]) -> pd.DataFrame:
    ev_supports = []
    ev_adverses = []
    dv_supports = []
    dv_adverses = []
    total_supports = []
    total_adverses = []
    net_scores = []
    phases = []
    top_groups = []
    for _, row in trades.iterrows():
        ev_sup, ev_adv, meta = _event_support_adverse_for_trade(row, windows, variant)
        dv_sup, dv_adv = _deriv_support_adverse(row)
        sup = float(variant.get("event_weight", 0.56)) * ev_sup + float(variant.get("deriv_weight", 0.44)) * dv_sup
        adv = float(variant.get("event_weight", 0.56)) * ev_adv + float(variant.get("deriv_weight", 0.44)) * dv_adv
        ev_supports.append(ev_sup)
        ev_adverses.append(ev_adv)
        dv_supports.append(dv_sup)
        dv_adverses.append(dv_adv)
        total_supports.append(sup)
        total_adverses.append(adv)
        net_scores.append(sup - adv)
        matches = list(meta.get("matches", []) or [])
        phases.append(",".join(dict.fromkeys([m.get("phase", "") for m in matches if m.get("phase")])) or "-")
        top_groups.append([m.get("group", "") for m in matches if m.get("group")])
    t = trades.copy()
    t["msg_event_support"] = ev_supports
    t["msg_event_adverse"] = ev_adverses
    t["msg_deriv_support"] = dv_supports
    t["msg_deriv_adverse"] = dv_adverses
    t["msg_total_support"] = total_supports
    t["msg_total_adverse"] = total_adverses
    t["msg_net_score"] = net_scores
    t["msg_phases"] = phases
    t["msg_groups"] = top_groups
    return t


def _apply_variant(trades: pd.DataFrame, windows: pd.DataFrame, variant: dict[str, Any], initial_equity: float) -> dict[str, Any]:
    scored = _score_rows(trades, windows, variant)
    adjusted_rows = []
    boost_soft = 0
    boost_mid = 0
    cut_soft = 0
    cut_mid = 0
    phase_counter: dict[str, int] = {"pre": 0, "release": 0, "drift": 0, "decay": 0}
    top_groups: list[str] = []
    for _, row in scored.iterrows():
        sym = str(row.get("symbol", "") or "").lower()
        sup = float(row.get("msg_total_support", 0.0))
        adv = float(row.get("msg_total_adverse", 0.0))
        net = float(row.get("msg_net_score", 0.0))
        boost_soft_thr = float((variant.get("boost_soft_asset_thresholds") or {}).get(sym, variant.get("boost_soft_thr", 0.12)))
        boost_mid_thr = float((variant.get("boost_mid_asset_thresholds") or {}).get(sym, variant.get("boost_mid_thr", 0.18)))
        cut_soft_thr = float((variant.get("cut_soft_asset_thresholds") or {}).get(sym, variant.get("cut_soft_thr", 0.16)))
        cut_mid_thr = float((variant.get("cut_mid_asset_thresholds") or {}).get(sym, variant.get("cut_mid_thr", 0.24)))
        net_boost_floor = float(variant.get("net_boost_floor", 0.03))
        net_cut_floor = float(variant.get("net_cut_floor", -0.03))
        action = "HOLD"
        scale = 1.0
        if adv >= cut_mid_thr and net <= net_cut_floor:
            action = "CUT_MID"
            scale = float(variant.get("cut_mid_scale", 0.58))
            cut_mid += 1
        elif adv >= cut_soft_thr and net < 0.0:
            action = "CUT_SOFT"
            scale = float(variant.get("cut_soft_scale", 0.78))
            cut_soft += 1
        elif sup >= boost_mid_thr and net >= net_boost_floor:
            action = "BOOST_MID"
            scale = float(variant.get("boost_mid_scale", 1.28))
            boost_mid += 1
        elif sup >= boost_soft_thr and net > 0.0:
            action = "BOOST_SOFT"
            scale = float(variant.get("boost_soft_scale", 1.12))
            boost_soft += 1
        if action != "HOLD":
            for phase in str(row.get("msg_phases", "")).split(","):
                phase = phase.strip()
                if phase in phase_counter:
                    phase_counter[phase] += 1
            top_groups.extend(list(row.get("msg_groups", []) or []))
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
    retained = qty_adj / qty_base if qty_base > 0 else 1.0
    exposure_drift = abs(retained - 1.0)
    score = (
        pnl_delta / float(initial_equity)
        + 2.2 * dd_delta
        - 0.015 * exposure_drift
        - 0.0005 * cut_mid
        - 0.0002 * cut_soft
        + 0.0002 * boost_soft
        + 0.0003 * boost_mid
    )
    vc = pd.Series(top_groups, dtype=str).value_counts().head(5)
    return {
        "variant": str(variant["name"]),
        "params": variant,
        "base": base_metrics,
        "gated": gated_metrics,
        "boost_soft": int(boost_soft),
        "boost_mid": int(boost_mid),
        "cut_soft": int(cut_soft),
        "cut_mid": int(cut_mid),
        "retained_notional_ratio": float(retained),
        "pnl_delta": pnl_delta,
        "dd_delta": dd_delta,
        "score": float(score),
        "top_event_groups": vc.index.tolist(),
        "phase_hits": phase_counter,
    }


def _walkforward_variant(trades: pd.DataFrame, windows: pd.DataFrame, initial_equity: float, variant: dict[str, Any]) -> dict[str, Any]:
    years = sorted(pd.to_datetime(trades["entry_time_utc"], utc=True).dt.year.unique().tolist())
    rows: list[dict[str, Any]] = []
    agg_pnl = 0.0
    agg_dd = 0.0
    agg_boost_soft = 0
    agg_boost_mid = 0
    agg_cut_soft = 0
    agg_cut_mid = 0
    retained_list: list[float] = []
    for year in years:
        fold = trades[pd.to_datetime(trades["entry_time_utc"], utc=True).dt.year == year].copy()
        if fold.empty:
            continue
        ev = _apply_variant(fold, windows, variant, initial_equity)
        agg_pnl += float(ev["pnl_delta"])
        agg_dd += float(ev["dd_delta"])
        agg_boost_soft += int(ev["boost_soft"])
        agg_boost_mid += int(ev["boost_mid"])
        agg_cut_soft += int(ev["cut_soft"])
        agg_cut_mid += int(ev["cut_mid"])
        retained_list.append(float(ev["retained_notional_ratio"]))
        rows.append(
            {
                "year": int(year),
                "pnl_delta": float(ev["pnl_delta"]),
                "dd_delta": float(ev["dd_delta"]),
                "boost_soft": int(ev["boost_soft"]),
                "boost_mid": int(ev["boost_mid"]),
                "cut_soft": int(ev["cut_soft"]),
                "cut_mid": int(ev["cut_mid"]),
                "retained": float(ev["retained_notional_ratio"]),
            }
        )
    return {
        "rows": rows,
        "aggregate_pnl_delta": float(agg_pnl),
        "aggregate_dd_delta": float(agg_dd),
        "aggregate_boost_soft": int(agg_boost_soft),
        "aggregate_boost_mid": int(agg_boost_mid),
        "aggregate_cut_soft": int(agg_cut_soft),
        "aggregate_cut_mid": int(agg_cut_mid),
        "avg_retained": float(np.mean(retained_list)) if retained_list else 1.0,
        "selected_nonbase_folds": len(rows),
    }


def _variant_grid() -> list[dict[str, Any]]:
    return [
        {
            "name": "sizing_balance_t016",
            "event_weight": 0.58,
            "deriv_weight": 0.42,
            "phase_weights": {"pre": 0.22, "release": 0.95, "drift": 0.62, "decay": 0.18},
            "boost_soft_thr": 0.12,
            "boost_mid_thr": 0.18,
            "cut_soft_thr": 0.16,
            "cut_mid_thr": 0.24,
            "boost_soft_scale": 1.10,
            "boost_mid_scale": 1.22,
            "cut_soft_scale": 0.82,
            "cut_mid_scale": 0.60,
            "net_boost_floor": 0.03,
            "net_cut_floor": -0.04,
            "boost_soft_asset_thresholds": {"btc": 0.14, "bnb": 0.10, "eth": 0.12, "sol": 0.12},
            "boost_mid_asset_thresholds": {"btc": 0.22, "bnb": 0.16, "eth": 0.18, "sol": 0.18},
            "cut_soft_asset_thresholds": {"btc": 0.18, "bnb": 0.14, "eth": 0.16, "sol": 0.16},
            "cut_mid_asset_thresholds": {"btc": 0.28, "bnb": 0.22, "eth": 0.24, "sol": 0.24},
        },
        {
            "name": "sizing_capture_t012",
            "event_weight": 0.60,
            "deriv_weight": 0.40,
            "phase_weights": {"pre": 0.18, "release": 1.00, "drift": 0.72, "decay": 0.22},
            "boost_soft_thr": 0.10,
            "boost_mid_thr": 0.16,
            "cut_soft_thr": 0.18,
            "cut_mid_thr": 0.28,
            "boost_soft_scale": 1.12,
            "boost_mid_scale": 1.28,
            "cut_soft_scale": 0.84,
            "cut_mid_scale": 0.62,
            "net_boost_floor": 0.02,
            "net_cut_floor": -0.05,
            "boost_soft_asset_thresholds": {"btc": 0.12, "bnb": 0.10, "eth": 0.11, "sol": 0.11},
            "boost_mid_asset_thresholds": {"btc": 0.20, "bnb": 0.15, "eth": 0.16, "sol": 0.16},
            "cut_soft_asset_thresholds": {"btc": 0.20, "bnb": 0.15, "eth": 0.17, "sol": 0.17},
            "cut_mid_asset_thresholds": {"btc": 0.30, "bnb": 0.24, "eth": 0.26, "sol": 0.26},
        },
        {
            "name": "sizing_preserve_t020",
            "event_weight": 0.56,
            "deriv_weight": 0.44,
            "phase_weights": {"pre": 0.18, "release": 0.90, "drift": 0.55, "decay": 0.15},
            "boost_soft_thr": 0.14,
            "boost_mid_thr": 0.22,
            "cut_soft_thr": 0.17,
            "cut_mid_thr": 0.26,
            "boost_soft_scale": 1.08,
            "boost_mid_scale": 1.18,
            "cut_soft_scale": 0.86,
            "cut_mid_scale": 0.66,
            "net_boost_floor": 0.04,
            "net_cut_floor": -0.04,
            "boost_soft_asset_thresholds": {"btc": 0.16, "bnb": 0.12, "eth": 0.14, "sol": 0.14},
            "boost_mid_asset_thresholds": {"btc": 0.24, "bnb": 0.18, "eth": 0.20, "sol": 0.20},
            "cut_soft_asset_thresholds": {"btc": 0.19, "bnb": 0.15, "eth": 0.17, "sol": 0.17},
            "cut_mid_asset_thresholds": {"btc": 0.29, "bnb": 0.23, "eth": 0.25, "sol": 0.25},
        },
        {
            "name": "sizing_asym_btc_eth_t014",
            "event_weight": 0.57,
            "deriv_weight": 0.43,
            "phase_weights": {"pre": 0.20, "release": 1.00, "drift": 0.68, "decay": 0.20},
            "boost_soft_thr": 0.12,
            "boost_mid_thr": 0.18,
            "cut_soft_thr": 0.16,
            "cut_mid_thr": 0.24,
            "boost_soft_scale": 1.10,
            "boost_mid_scale": 1.24,
            "cut_soft_scale": 0.80,
            "cut_mid_scale": 0.58,
            "net_boost_floor": 0.03,
            "net_cut_floor": -0.04,
            "boost_soft_asset_thresholds": {"btc": 0.15, "bnb": 0.11, "eth": 0.11, "sol": 0.13},
            "boost_mid_asset_thresholds": {"btc": 0.23, "bnb": 0.17, "eth": 0.16, "sol": 0.19},
            "cut_soft_asset_thresholds": {"btc": 0.17, "bnb": 0.14, "eth": 0.15, "sol": 0.17},
            "cut_mid_asset_thresholds": {"btc": 0.27, "bnb": 0.22, "eth": 0.22, "sol": 0.25},
        },
    ]


def run(project_dir: Path, out_txt: Path, out_json: Path) -> None:
    cfg = read_config(project_dir / "config.yml")
    initial_equity = float(cfg.get("portfolio", {}).get("initial_equity", 100000.0))
    trades = s210._load_trades_fallback(project_dir)
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
    for variant in _variant_grid():
        full_ev = _apply_variant(trades, windows, variant, initial_equity)
        recent_ev = _apply_variant(recent2y, windows, variant, initial_equity) if not recent2y.empty else {
            "boost_soft": 0,
            "boost_mid": 0,
            "cut_soft": 0,
            "cut_mid": 0,
            "retained_notional_ratio": 1.0,
            "pnl_delta": 0.0,
            "dd_delta": 0.0,
            "score": 0.0,
            "gated": {"trades": 0, "profit_factor": 0.0, "total_return": 0.0, "max_drawdown": 0.0},
            "phase_hits": {"pre": 0, "release": 0, "drift": 0, "decay": 0},
        }
        wf = _walkforward_variant(trades, windows, initial_equity, variant)
        wf_score = float(wf["aggregate_pnl_delta"] / initial_equity + 2.1 * wf["aggregate_dd_delta"] - 0.010 * abs(wf["avg_retained"] - 1.0))
        composite = float(0.68 * full_ev["score"] + 1.00 * recent_ev["score"] + 0.90 * wf_score)
        results.append(
            {
                "name": variant["name"],
                "params": variant,
                "full": full_ev,
                "recent2y": recent_ev,
                "wf": wf,
                "composite_score": composite,
                "gated_metrics_full": full_ev["gated"],
                "gated_metrics_recent2y": recent_ev["gated"],
                "top_event_groups": full_ev["top_event_groups"],
            }
        )

    results.sort(key=lambda r: (r["composite_score"], r["recent2y"]["score"], r["full"]["score"]), reverse=True)
    top = results[:6]
    best = top[0] if top else None
    recommended = best
    if best is not None:
        near_best = [r for r in top if r["composite_score"] >= best["composite_score"] * 0.80]
        low_cut = [r for r in near_best if r["full"]["cut_mid"] <= 1]
        if low_cut:
            recommended = min(low_cut, key=lambda r: (abs(r["full"]["retained_notional_ratio"] - 1.0), -r["composite_score"]))

    base_metrics = msb._trade_metrics(trades, initial_equity)
    now_utc = pd.Timestamp.now(tz="UTC")
    live_calendar, cal_mode = s211._standardize_calendar_live(project_dir, now_utc)
    live_news, news_mode = s211._standardize_news_live(project_dir, now_utc)
    live_calendar = s211._attach_asset_scores(live_calendar, "calendar")
    live_news = s211._attach_asset_scores(live_news, "news")

    lines: list[str] = []
    lines.append("Stage212 message sizing overlay frontier")
    lines.append("")
    lines.append("[model]")
    lines.append("- 技术面继续负责 entry alpha；消息面/事件面不再决定是否开仓。")
    lines.append("- 动作层改成纯仓位层：BOOST_SOFT / BOOST_MID / HOLD / CUT_SOFT / CUT_MID。")
    lines.append("- 原则：消息只加仓/减仓，不做 veto；是否开仓仍由技术骨架决定。")
    lines.append("- 未来事件继续四态：pre / release / drift / decay；衍生品层继续只做确认与仓位微调。")
    lines.append("")
    lines.append("[baseline]")
    lines.append(f"- baseline_trades={len(trades)} | baseline_ret={_fmt_pct(base_metrics['total_return'])} | baseline_pf={base_metrics['profit_factor']:.3f} | baseline_maxdd={_fmt_pct(base_metrics['max_drawdown'])}")
    lines.append("")
    lines.append("[top_sizing_variants]")
    for row in top:
        full = row["full"]
        r2 = row["recent2y"]
        wf = row["wf"]
        gm_full = row["gated_metrics_full"]
        gm_r2 = row["gated_metrics_recent2y"]
        lines.append(
            f"- {row['name']} | composite={row['composite_score']:+.4f} | full pnl_delta={_fmt_num(full['pnl_delta'])} dd_delta={_fmt_pct(full['dd_delta'])} boost={full['boost_soft']}/{full['boost_mid']} cut={full['cut_soft']}/{full['cut_mid']} retain={_fmt_pct(full['retained_notional_ratio'])}"
        )
        lines.append(
            f"  sized_full: trades={gm_full['trades']} pf={gm_full['profit_factor']:.3f} ret={_fmt_pct(gm_full['total_return'])} maxdd={_fmt_pct(gm_full['max_drawdown'])} | phase_hits={json.dumps(full['phase_hits'], ensure_ascii=False, separators=(',', ':'))}"
        )
        lines.append(
            f"  sized_2y: trades={gm_r2['trades']} pf={gm_r2['profit_factor']:.3f} ret={_fmt_pct(gm_r2['total_return'])} maxdd={_fmt_pct(gm_r2['max_drawdown'])} | pnl_delta={_fmt_num(r2['pnl_delta'])} dd_delta={_fmt_pct(r2['dd_delta'])}"
        )
        lines.append(
            f"  wf: pnl_delta={_fmt_num(wf['aggregate_pnl_delta'])} dd_delta={_fmt_pct(wf['aggregate_dd_delta'])} boost={wf['aggregate_boost_soft']}/{wf['aggregate_boost_mid']} cut={wf['aggregate_cut_soft']}/{wf['aggregate_cut_mid']} retain={_fmt_pct(wf['avg_retained'])} | top_groups={'; '.join(row['top_event_groups'][:4]) if row['top_event_groups'] else '-'}"
        )
    lines.append("")
    lines.append("[live_bridge_status]")
    lines.append(f"- calendar_mode={cal_mode} | standardized_events={len(live_calendar)}")
    lines.append(f"- news_mode={news_mode} | standardized_messages={len(live_news)}")
    lines.append("- 这一步开始把 live bridge 明确当成仓位覆盖层，不再往 entry 层走。")
    lines.append("")
    lines.append("[top_calendar_by_asset]")
    for asset in ASSETS:
        rows = s211._pick_asset_top(live_calendar, asset, 2)
        if not rows:
            lines.append(f"- {asset}: none")
            continue
        for row in rows:
            ts = row.get("publish_utc")
            lines.append(
                f"- {asset} | {ts} | {row.get('event_class','')} | {row.get('severity','')} | score={row.get(f'score_{asset}',0.0):.3f} | {row.get('title','')}"
            )
    lines.append("")
    lines.append("[top_news_by_asset]")
    for asset in ASSETS:
        rows = s211._pick_asset_top(live_news, asset, 2)
        if not rows:
            lines.append(f"- {asset}: none")
            continue
        for row in rows:
            ts = row.get("release_utc")
            lines.append(
                f"- {asset} | {ts} | {row.get('source','')} | {row.get('event_class','')} | {row.get('severity','')} | score={row.get(f'score_{asset}',0.0):.3f} | {row.get('title','')}"
            )
    lines.append("")
    lines.append("[conclusion]")
    if recommended:
        lines.append(f"- 推荐先用 {recommended['name']} 做消息仓位覆盖基线。")
        lines.append(f"- 原因：full boost={recommended['full']['boost_soft']}/{recommended['full']['boost_mid']} cut={recommended['full']['cut_soft']}/{recommended['full']['cut_mid']}，且 retain={_fmt_pct(recommended['full']['retained_notional_ratio'])}。")
        lines.append("- 下一步把同一套 sizing overlay 往 branch 迁；entry 仍只归技术面。")

    out_txt.parent.mkdir(parents=True, exist_ok=True)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    payload = {
        "baseline": base_metrics,
        "top_variants": top,
        "recommended": recommended,
        "calendar_mode": cal_mode,
        "news_mode": news_mode,
        "asset_top_calendar": {a: s211._pick_asset_top(live_calendar, a, 3) for a in ASSETS},
        "asset_top_news": {a: s211._pick_asset_top(live_news, a, 3) for a in ASSETS},
        "model_layers": [
            "technical_entry_alpha",
            "scheduled_event_engine",
            "unscheduled_message_scoring",
            "derivatives_confirm",
            "position_sizing_overlay",
        ],
    }
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage212 message sizing overlay frontier")
    ap.add_argument("--project-dir", type=Path, default=Path("."))
    ap.add_argument("--out-txt", type=Path, default=None)
    ap.add_argument("--out-json", type=Path, default=None)
    args = ap.parse_args()
    root = args.project_dir.resolve()
    out_txt = args.out_txt or (root / "reports" / "research_raw" / "stage212_message_sizing_overlay_frontier_latest.txt")
    out_json = args.out_json or (root / "reports" / "research_raw" / "stage212_message_sizing_overlay_frontier_latest.json")
    run(root, out_txt, out_json)


if __name__ == "__main__":
    main()
