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

CAL_CLASS_SPECS: dict[str, dict[str, Any]] = {
    "rates": {"lead_h": 8.0, "release_h": 2.0, "drift_h": 18.0, "decay_h": 30.0, "class_weight": 1.15},
    "inflation": {"lead_h": 6.0, "release_h": 2.0, "drift_h": 12.0, "decay_h": 24.0, "class_weight": 1.05},
    "labor": {"lead_h": 6.0, "release_h": 2.0, "drift_h": 12.0, "decay_h": 24.0, "class_weight": 0.98},
    "growth": {"lead_h": 4.0, "release_h": 2.0, "drift_h": 8.0, "decay_h": 18.0, "class_weight": 0.88},
    "confidence": {"lead_h": 3.0, "release_h": 1.5, "drift_h": 8.0, "decay_h": 18.0, "class_weight": 1.08},
    "liquidity": {"lead_h": 4.0, "release_h": 2.0, "drift_h": 10.0, "decay_h": 20.0, "class_weight": 1.02},
    "energy": {"lead_h": 2.0, "release_h": 1.5, "drift_h": 6.0, "decay_h": 12.0, "class_weight": 0.55},
    "policy": {"lead_h": 6.0, "release_h": 3.0, "drift_h": 20.0, "decay_h": 36.0, "class_weight": 1.20},
    "exchange": {"lead_h": 2.0, "release_h": 3.0, "drift_h": 16.0, "decay_h": 24.0, "class_weight": 1.10},
    "hack": {"lead_h": 0.0, "release_h": 4.0, "drift_h": 24.0, "decay_h": 48.0, "class_weight": 1.35},
    "generic": {"lead_h": 2.0, "release_h": 1.0, "drift_h": 6.0, "decay_h": 12.0, "class_weight": 0.75},
}


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
        "macro": {"btc": 1.00, "bnb": 0.58, "eth": 0.84, "sol": 0.74, "default": 0.80},
        "policy": {"btc": 0.95, "bnb": 0.82, "eth": 0.90, "sol": 0.80, "default": 0.86},
        "crypto": {"btc": 0.82, "bnb": 0.78, "eth": 0.94, "sol": 0.94, "default": 0.84},
        "exchange": {"btc": 0.72, "bnb": 1.08, "eth": 0.72, "sol": 0.72, "default": 0.76},
        "hack": {"btc": 0.80, "bnb": 0.90, "eth": 0.88, "sol": 0.88, "default": 0.84},
        "us_equity": {"btc": 0.84, "bnb": 0.52, "eth": 0.70, "sol": 0.60, "default": 0.68},
        "generic": {"default": 0.80},
        "default": {"default": 0.80},
    }
    weight = base.get(cat, base["default"]).get(sym, base.get(cat, base["default"]).get("default", 0.8))
    asset_keys = {
        "btc": ["bitcoin", " btc", "btc ", "etf", "treasury", "microstrategy", "saylor"],
        "bnb": ["binance", "bnb", "bsc", "cz"],
        "eth": ["ethereum", " ether", "eth ", "defi", "rollup", "l2"],
        "sol": ["solana", "sol ", "memecoin", "dex", "jito", "raydium"],
    }
    if any(k in text for k in asset_keys.get(sym, [])):
        weight *= 1.25
    if "binance" in text and sym == "bnb":
        weight *= 1.15
    if "etf" in text and sym == "btc":
        weight *= 1.10
    return max(0.25, min(1.50, weight))


def _classify_event(title: str, category: str, tags: str = "") -> str:
    text = " ".join([str(title).lower(), str(category).lower(), str(tags).lower()])
    if any(k in text for k in ["fomc", "fed", "rate decision", "interest rate", "dot plot", "powell", "ecb", "boj", "rate cut", "rate hike"]):
        return "rates"
    if any(k in text for k in ["cpi", "ppi", "inflation", "cpi m/m", "pce"]):
        return "inflation"
    if any(k in text for k in ["nonfarm", "payroll", "nfp", "unemployment", "jobless", "labor", "employment"]):
        return "labor"
    if any(k in text for k in ["gdp", "retail sales", "industrial production", "durable goods", "growth"]):
        return "growth"
    if any(k in text for k in ["consumer confidence", "pmi", "ism", "sentiment", "expectations"]):
        return "confidence"
    if any(k in text for k in ["liquidity", "qt", "qe", "tga", "rrp"]):
        return "liquidity"
    if any(k in text for k in ["eia", "crude", "gasoline", "oil inventory"]):
        return "energy"
    if any(k in text for k in ["sec", "cftc", "doj", "regulation", "lawsuit", "approval", "tariff", "sanction", "policy"]):
        return "policy"
    if any(k in text for k in ["binance", "kraken", "coinbase", "bybit", "okx", "exchange"]):
        return "exchange"
    if any(k in text for k in ["hack", "exploit", "breach", "liquidation shock", "bankruptcy"]):
        return "hack"
    return "generic"


def _phase_name(ts: pd.Timestamp, start_utc: pd.Timestamp, end_utc: pd.Timestamp, cls: str) -> str | None:
    spec = CAL_CLASS_SPECS.get(cls, CAL_CLASS_SPECS["generic"])
    lead_start = start_utc - pd.Timedelta(hours=float(spec["lead_h"]))
    release_end = start_utc + pd.Timedelta(hours=float(spec["release_h"]))
    drift_end = start_utc + pd.Timedelta(hours=float(spec["drift_h"]))
    decay_end = max(end_utc, start_utc + pd.Timedelta(hours=float(spec["decay_h"])))
    if lead_start <= ts < start_utc:
        return "pre"
    if start_utc <= ts <= release_end:
        return "release"
    if release_end < ts <= drift_end:
        return "drift"
    if drift_end < ts <= decay_end:
        return "decay"
    return None


def _load_recent_items(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(payload, dict) and isinstance(payload.get("response"), dict):
        payload = payload["response"]
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        payload = payload["data"]
    items = msb._extract_items(payload)
    out: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            out.append(item)
    return out


def _severity_from_importance(level: Any, cls: str) -> str:
    try:
        lvl = int(level)
    except Exception:
        lvl = 0
    if cls in {"hack", "policy"} and lvl >= 2:
        lvl += 1
    if lvl >= 4:
        return "critical"
    if lvl >= 3:
        return "high"
    if lvl >= 2:
        return "medium"
    if lvl >= 1:
        return "low"
    return "default"


def _standardize_upcoming_calendar(project_dir: Path, now_utc: pd.Timestamp) -> pd.DataFrame:
    raw_path = project_dir / "data" / "external" / "coinglass" / "economic_recent.json"
    rows: list[dict[str, Any]] = []
    for item in _load_recent_items(raw_path):
        ts = msb._extract_time(item)
        if ts is None or ts < now_utc:
            continue
        title = str(item.get("calendar_name", "") or "")
        country = str(item.get("country_code", "") or "")
        cls = _classify_event(title, "macro", "")
        spec = CAL_CLASS_SPECS.get(cls, CAL_CLASS_SPECS["generic"])
        severity = _severity_from_importance(item.get("importance_level"), cls)
        lead_start = ts - pd.Timedelta(hours=float(spec["lead_h"]))
        release_end = ts + pd.Timedelta(hours=float(spec["release_h"]))
        drift_end = ts + pd.Timedelta(hours=float(spec["drift_h"]))
        decay_end = ts + pd.Timedelta(hours=float(spec["decay_h"]))
        rows.append(
            {
                "publish_utc": ts,
                "lead_start_utc": lead_start,
                "release_end_utc": release_end,
                "drift_end_utc": drift_end,
                "decay_end_utc": decay_end,
                "country": country,
                "event_class": cls,
                "severity": severity,
                "importance_level": int(item.get("importance_level") or 0),
                "title": title,
                "forecast_value": str(item.get("forecast_value", "") or ""),
                "previous_value": str(item.get("previous_value", "") or ""),
                "has_exact_publish_time": int(item.get("has_exact_publish_time") or 0),
                "class_weight": float(spec["class_weight"]),
            }
        )
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=[
            "publish_utc", "lead_start_utc", "release_end_utc", "drift_end_utc", "decay_end_utc",
            "country", "event_class", "severity", "importance_level", "title", "forecast_value",
            "previous_value", "has_exact_publish_time", "class_weight",
        ])
    return df.sort_values(["publish_utc", "importance_level"], ascending=[True, False]).reset_index(drop=True)


def _standardize_recent_news(project_dir: Path, now_utc: pd.Timestamp) -> pd.DataFrame:
    raw_path = project_dir / "data" / "external" / "coinglass" / "news_recent.json"
    rows: list[dict[str, Any]] = []
    for item in _load_recent_items(raw_path):
        ts = msb._extract_time(item)
        if ts is None or ts < now_utc - pd.Timedelta(days=5):
            continue
        title = str(item.get("article_title", "") or "")
        source = str(item.get("source_name", "") or "")
        desc = str(item.get("article_description", "") or "")
        text = " ".join([title, desc, source]).lower()
        cls = _classify_event(title, "crypto", desc)
        severity = "medium"
        if any(k in text for k in ["hack", "exploit", "lawsuit", "charged", "settlement", "liquidation", "bankruptcy"]):
            severity = "high"
        elif any(k in text for k in ["approval", "launch", "partnership", "etf", "upgrade", "funding"]):
            severity = "medium"
        source_weight = 1.0 if source in {"COINTELEGRAPH", "THE BLOCK", "BLOOMBERG", "REUTERS"} else 0.8
        rows.append(
            {
                "release_utc": ts,
                "title": title,
                "source": source,
                "event_class": cls,
                "severity": severity,
                "source_weight": source_weight,
            }
        )
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["release_utc", "title", "source", "event_class", "severity", "source_weight"])
    return df.sort_values("release_utc", ascending=False).reset_index(drop=True)


def _event_risk_for_trade_phase(row: pd.Series, windows: pd.DataFrame, variant: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    ts = row["entry_time_utc"]
    sym = str(row.get("symbol", "")).lower()
    side = str(row.get("side", "")).upper()
    risks: list[float] = []
    meta_rows: list[dict[str, Any]] = []
    seen_groups: set[str] = set()
    phase_weights = variant.get("phase_weights", {}) or {}
    for _, ev in windows.iterrows():
        start_utc = pd.to_datetime(ev["start_utc"], utc=True)
        end_utc = pd.to_datetime(ev["end_utc"], utc=True)
        cls = _classify_event(str(ev.get("title", "") or ""), str(ev.get("category", "") or "generic"), str(ev.get("profile_tags", "") or ""))
        phase = _phase_name(ts, start_utc, end_utc, cls)
        if phase is None:
            continue
        sev = str(ev.get("severity", "default") or "default").lower()
        cat = str(ev.get("category", "generic") or "generic")
        title = str(ev.get("title", "") or "")
        tags = str(ev.get("profile_tags", "") or "")
        gid = str(ev.get("group_id", title) or title)
        mode = str(ev.get("event_mode", "default") or "default")
        side_map = dict(MODE_SIDE_W.get(side, MODE_SIDE_W["LONG"]))
        side_map["two_sided"] = float(variant.get("two_sided_mult", 0.45)) if side == "LONG" else max(0.20, float(variant.get("two_sided_mult", 0.45)) - 0.10)
        side_map["observation_only"] = float(variant.get("obs_mult", 0.08))
        side_map["positive_catalyst"] = 0.0 if side == "LONG" else float(variant.get("pos_short_mult", 0.60))
        sev_w = SEVERITY_W.get(sev, SEVERITY_W["default"])
        mode_w = side_map.get(mode, side_map["default"])
        asset_w = _asset_relevance(sym, cat, title, tags, gid)
        class_w = float(CAL_CLASS_SPECS.get(cls, CAL_CLASS_SPECS["generic"])["class_weight"])
        phase_w = float(phase_weights.get(phase, 0.0))
        risk = sev_w * mode_w * asset_w * class_w * phase_w
        if gid in seen_groups:
            risk *= 0.35
        else:
            seen_groups.add(gid)
        risks.append(risk)
        meta_rows.append({"group": gid, "phase": phase, "class": cls, "title": title})
    total = min(float(sum(risks)), 1.90)
    return total, {"matches": meta_rows[:6]}


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
    phases = []
    top_groups = []
    for _, row in trades.iterrows():
        ev_score, meta = _event_risk_for_trade_phase(row, windows, variant)
        dv_score = _deriv_risk_for_trade(row)
        total = float(variant.get("event_weight", 0.60)) * ev_score + float(variant.get("deriv_weight", 0.40)) * dv_score
        event_scores.append(ev_score)
        deriv_scores.append(dv_score)
        total_scores.append(total)
        matches = list(meta.get("matches", []) or [])
        phases.append(",".join(dict.fromkeys([m.get("phase", "") for m in matches if m.get("phase")])) or "-")
        top_groups.append([m.get("group", "") for m in matches if m.get("group")])
    t = trades.copy()
    t["msg_event_score"] = event_scores
    t["msg_deriv_score"] = deriv_scores
    t["msg_total_score"] = total_scores
    t["msg_phases"] = phases
    t["msg_groups"] = top_groups
    return t


def _apply_variant(trades: pd.DataFrame, windows: pd.DataFrame, variant: dict[str, Any], initial_equity: float) -> dict[str, Any]:
    scored = _score_rows(trades, windows, variant)
    adjusted_rows = []
    hard = 0
    mid = 0
    soft = 0
    phase_counter: dict[str, int] = {"pre": 0, "release": 0, "drift": 0, "decay": 0}
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
        if total >= hard_thr and (not bool(variant.get("hard_need_confirm", False)) or confirm or ev >= float(variant.get("critical_event_cut", 0.95))):
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
            for phase in str(row.get("msg_phases", "")).split(","):
                phase = phase.strip()
                if phase in phase_counter:
                    phase_counter[phase] += 1
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
        "phase_hits": phase_counter,
    }


def _variant_grid() -> list[dict[str, Any]]:
    return [
        {
            "name": "phase_balance_t014",
            "event_weight": 0.58,
            "deriv_weight": 0.42,
            "two_sided_mult": 0.45,
            "obs_mult": 0.08,
            "pos_short_mult": 0.60,
            "phase_weights": {"pre": 0.28, "release": 1.00, "drift": 0.62, "decay": 0.18},
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
            "name": "phase_preserve_t018",
            "event_weight": 0.56,
            "deriv_weight": 0.44,
            "two_sided_mult": 0.45,
            "obs_mult": 0.08,
            "pos_short_mult": 0.60,
            "phase_weights": {"pre": 0.22, "release": 0.94, "drift": 0.52, "decay": 0.14},
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
            "name": "phase_capture_t010",
            "event_weight": 0.62,
            "deriv_weight": 0.38,
            "two_sided_mult": 0.40,
            "obs_mult": 0.06,
            "pos_short_mult": 0.58,
            "phase_weights": {"pre": 0.35, "release": 1.08, "drift": 0.70, "decay": 0.22},
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
            "name": "phase_macro_guard_t012",
            "event_weight": 0.64,
            "deriv_weight": 0.36,
            "two_sided_mult": 0.42,
            "obs_mult": 0.05,
            "pos_short_mult": 0.58,
            "phase_weights": {"pre": 0.34, "release": 1.12, "drift": 0.58, "decay": 0.16},
            "soft_thr": 0.12,
            "mid_thr": 0.17,
            "hard_thr": 0.24,
            "soft_scale": 0.68,
            "mid_scale": 0.36,
            "hard_need_confirm": True,
            "min_event_confirm": 0.34,
            "min_deriv_confirm": 0.18,
            "soft_asset_thresholds": {"btc": 0.13, "bnb": 0.10, "eth": 0.12, "sol": 0.12},
            "mid_asset_thresholds": {"btc": 0.19, "bnb": 0.15, "eth": 0.17, "sol": 0.17},
            "hard_asset_thresholds": {"btc": 0.27, "bnb": 0.22, "eth": 0.24, "sol": 0.24},
        },
    ]


def _two_year_slice(trades: pd.DataFrame) -> pd.DataFrame:
    end = trades["entry_time_utc"].max()
    start = end - pd.Timedelta(days=365 * 2)
    return trades[trades["entry_time_utc"] >= start].copy()


def _walkforward_variant(trades: pd.DataFrame, windows: pd.DataFrame, initial_equity: float, variant: dict[str, Any]) -> dict[str, Any]:
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
        ev = _apply_variant(test, windows, variant, initial_equity)
        agg_pnl += float(ev["pnl_delta"])
        agg_dd += float(ev["dd_delta"])
        agg_hard += int(ev["hard_blocked"])
        agg_mid += int(ev["mid_scaled"])
        agg_soft += int(ev["soft_scaled"])
        retained_list.append(float(ev["retained_notional_ratio"]))
        rows.append(
            {
                "year": int(year),
                "pnl_delta": float(ev["pnl_delta"]),
                "dd_delta": float(ev["dd_delta"]),
                "hard": int(ev["hard_blocked"]),
                "mid": int(ev["mid_scaled"]),
                "soft": int(ev["soft_scaled"]),
                "retained": float(ev["retained_notional_ratio"]),
            }
        )
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
    now_utc = pd.Timestamp.now(tz="UTC")
    upcoming = _standardize_upcoming_calendar(project_dir, now_utc)
    recent_news = _standardize_recent_news(project_dir, now_utc)

    results: list[dict[str, Any]] = []
    for variant in _variant_grid():
        full_ev = _apply_variant(trades, windows, variant, initial_equity)
        recent_ev = _apply_variant(recent2y, windows, variant, initial_equity) if not recent2y.empty else {
            "hard_blocked": 0,
            "mid_scaled": 0,
            "soft_scaled": 0,
            "retained_notional_ratio": 0.0,
            "pnl_delta": 0.0,
            "dd_delta": 0.0,
            "score": 0.0,
            "gated": {"trades": 0, "profit_factor": 0.0, "total_return": 0.0, "max_drawdown": 0.0},
            "phase_hits": {"pre": 0, "release": 0, "drift": 0, "decay": 0},
        }
        wf = _walkforward_variant(trades, windows, initial_equity, variant)
        wf_score = float(wf["aggregate_pnl_delta"] / initial_equity + 2.0 * wf["aggregate_dd_delta"] + 0.04 * wf["avg_retained"])
        composite = float(0.70 * full_ev["score"] + 1.00 * recent_ev["score"] + 0.90 * wf_score)
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
        near_best = [r for r in top if r["composite_score"] >= best["composite_score"] * 0.72]
        zero_hard = [r for r in near_best if r["full"]["hard_blocked"] == 0]
        if zero_hard:
            recommended = max(zero_hard, key=lambda r: (r["full"]["retained_notional_ratio"], r["composite_score"]))

    base_metrics = msb._trade_metrics(trades, initial_equity)
    lines: list[str] = []
    lines.append("Stage210 common event + message model frontier")
    lines.append("")
    lines.append("[model]")
    lines.append("- 技术面只负责给 entry alpha；消息面和事件面不再裸 veto，也不再和技术面抢同一层。")
    lines.append("- 统一改成 5 层：technical alpha / scheduled event engine / unscheduled message scoring / derivatives confirm / action ladder。")
    lines.append("- scheduled event engine 固定四态：pre / release / drift / decay。未来事件先量化时间窗，再决定动作。")
    lines.append("- unscheduled message 固定五因子：severity / source / asset map / event class / derivatives confirm。")
    lines.append("- 动作层固定四态：PASS / REDUCE_SOFT / REDUCE_MID / HARD_BLOCK。")
    lines.append("")
    lines.append("[baseline]")
    lines.append(f"- baseline_trades={len(trades)} | baseline_ret={_fmt_pct(base_metrics['total_return'])} | baseline_pf={base_metrics['profit_factor']:.3f} | baseline_maxdd={_fmt_pct(base_metrics['max_drawdown'])}")
    lines.append("")
    lines.append("[top_phase_variants]")
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
            f"  gated_full: trades={gm_full['trades']} pf={gm_full['profit_factor']:.3f} ret={_fmt_pct(gm_full['total_return'])} maxdd={_fmt_pct(gm_full['max_drawdown'])} | phase_hits={json.dumps(full['phase_hits'], ensure_ascii=False, separators=(',', ':'))}"
        )
        lines.append(
            f"  gated_2y: trades={gm_r2['trades']} pf={gm_r2['profit_factor']:.3f} ret={_fmt_pct(gm_r2['total_return'])} maxdd={_fmt_pct(gm_r2['max_drawdown'])} | pnl_delta={_fmt_num(r2['pnl_delta'])} dd_delta={_fmt_pct(r2['dd_delta'])}"
        )
        lines.append(
            f"  wf: pnl_delta={_fmt_num(wf['aggregate_pnl_delta'])} dd_delta={_fmt_pct(wf['aggregate_dd_delta'])} hard={wf['aggregate_hard']} mid={wf['aggregate_mid']} soft={wf['aggregate_soft']} retain={_fmt_pct(wf['avg_retained'])} | top_groups={'; '.join(row['top_event_groups'][:4]) if row['top_event_groups'] else '-'}"
        )
    lines.append("")
    lines.append("[upcoming_standardized_schedule]")
    if upcoming.empty:
        lines.append("- no_upcoming_calendar_events_in_cache")
    else:
        for _, row in upcoming.head(10).iterrows():
            lines.append(
                f"- {pd.to_datetime(row['publish_utc'], utc=True)} | {row['country']} | {row['event_class']} | {row['severity']} | {row['title']} | pre={pd.to_datetime(row['lead_start_utc'], utc=True)} -> release_end={pd.to_datetime(row['release_end_utc'], utc=True)} -> drift_end={pd.to_datetime(row['drift_end_utc'], utc=True)}"
            )
    lines.append("")
    lines.append("[recent_standardized_messages]")
    if recent_news.empty:
        lines.append("- no_recent_news_in_cache")
    else:
        for _, row in recent_news.head(8).iterrows():
            lines.append(f"- {pd.to_datetime(row['release_utc'], utc=True)} | {row['source']} | {row['event_class']} | {row['severity']} | {row['title']}")
    lines.append("")
    lines.append("[conclusion]")
    if recommended:
        lines.append(f"- 推荐先用 {recommended['name']} 做公共模型基线。")
        lines.append(f"- 原因：full hard={recommended['full']['hard_blocked']} / mid={recommended['full']['mid_scaled']} / soft={recommended['full']['soft_scaled']} / retain={_fmt_pct(recommended['full']['retained_notional_ratio'])}。")
        lines.append("- 下一步不再统一阈值，而是把 branch 也迁到同一套 event-state + message-score + action-ladder 上。")

    out_txt.parent.mkdir(parents=True, exist_ok=True)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    payload = {
        "baseline": base_metrics,
        "top_variants": top,
        "recommended": recommended,
        "upcoming_standardized_schedule": upcoming.head(20).to_dict(orient="records"),
        "recent_standardized_messages": recent_news.head(20).to_dict(orient="records"),
        "model_layers": [
            "technical_alpha",
            "scheduled_event_engine",
            "unscheduled_message_scoring",
            "derivatives_confirm",
            "action_ladder",
        ],
    }
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage210 common event+message model frontier")
    ap.add_argument("--project-dir", type=Path, default=Path("."))
    ap.add_argument("--out-txt", type=Path, default=None)
    ap.add_argument("--out-json", type=Path, default=None)
    args = ap.parse_args()
    root = args.project_dir.resolve()
    out_txt = args.out_txt or (root / "reports" / "research_raw" / "stage210_common_event_message_model_frontier_latest.txt")
    out_json = args.out_json or (root / "reports" / "research_raw" / "stage210_common_event_message_model_frontier_latest.json")
    run(root, out_txt, out_json)


if __name__ == "__main__":
    main()
