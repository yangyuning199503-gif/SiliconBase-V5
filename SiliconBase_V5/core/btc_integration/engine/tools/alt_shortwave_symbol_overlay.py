from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest.io import read_config
from tools.alt_shortwave_message_overlay import (
    _attach_message_layers,
    _base_candidate_items,
    _run_candidate,
    _trade_metrics_from_df,
)
from tools.message_stack_backtest import _score_variant

ETH_REG_GROUPS: set[str] = {
    "sec_suits_2023",
    "sec_etf_whipsaw_2024",
    "spot_etf_approval_2024",
    "binance_doj_2023",
    "svb_usdc_2023",
    "terra_2022",
    "ftx_2022",
}

SOL_CRYPTO_GROUPS: set[str] = {
    "terra_2022",
    "ftx_2022",
    "sec_suits_2023",
    "aug_flush_2023",
    "carry_unwind_2024",
    "mideast_escalation_2024",
    "tariff_shock_2025",
}


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


def _top_groups(df: pd.DataFrame, limit: int = 5) -> list[str]:
    if df is None or df.empty or "event_group" not in df.columns:
        return []
    return (
        df["event_group"]
        .replace("", pd.NA)
        .dropna()
        .astype(str)
        .value_counts()
        .head(limit)
        .index.tolist()
    )


def _group_tokens(val: Any) -> set[str]:
    if val is None:
        return set()
    s = str(val).strip()
    if not s:
        return set()
    return {x.strip() for x in s.split("|") if x.strip()}


def _whitelist_mask(trades: pd.DataFrame, groups: Sequence[str]) -> pd.Series:
    if trades is None or trades.empty:
        return pd.Series(dtype=bool)
    wanted = {str(x).strip() for x in groups if str(x).strip()}
    if not wanted:
        return pd.Series(False, index=trades.index)
    event_mask = trades.get("event_blocked", pd.Series(False, index=trades.index)).fillna(False).astype(bool)
    if "event_group" not in trades.columns:
        return pd.Series(False, index=trades.index)
    grp = trades["event_group"].apply(_group_tokens)
    hit = grp.apply(lambda xs: bool(xs & wanted))
    return event_mask & hit.astype(bool)


def _coinglass_mask(trades: pd.DataFrame) -> pd.Series:
    if trades is None or trades.empty:
        return pd.Series(dtype=bool)
    side = trades["side"].astype(str).str.upper()
    cg_long = trades.get("cg_long_risk", pd.Series(False, index=trades.index)).fillna(False).astype(bool)
    cg_short = trades.get("cg_short_risk", pd.Series(False, index=trades.index)).fillna(False).astype(bool)
    return ((side == "LONG") & cg_long) | ((side == "SHORT") & cg_short)


def _evaluate_mask(trades: pd.DataFrame, blocked_mask: pd.Series, variant_name: str, initial_equity: float) -> dict[str, Any]:
    blocked_df = trades.loc[blocked_mask].copy()
    gated_df = trades.loc[~blocked_mask].copy()
    base = _trade_metrics_from_df(trades, initial_equity)
    gated = _trade_metrics_from_df(gated_df, initial_equity)
    pnl_delta = float((gated.get("ret", 0.0) - base.get("ret", 0.0)) * initial_equity)
    dd_delta = float(gated.get("maxdd", 0.0) - base.get("maxdd", 0.0))
    score = _score_variant(
        {
            "total_pnl": float(base.get("ret", 0.0)) * initial_equity,
            "max_drawdown": float(base.get("maxdd", 0.0)),
        },
        {
            "total_pnl": float(gated.get("ret", 0.0)) * initial_equity,
            "max_drawdown": float(gated.get("maxdd", 0.0)),
        },
        int(blocked_mask.sum()),
        initial_equity,
    )
    return {
        "variant": variant_name,
        "blocked": int(blocked_mask.sum()),
        "pnl_delta": pnl_delta,
        "dd_delta": dd_delta,
        "score": float(score),
        "gated": gated,
        "top_event_groups": _top_groups(blocked_df),
        "blocked_long": int((blocked_df["side"].astype(str).str.upper() == "LONG").sum()) if not blocked_df.empty else 0,
        "blocked_short": int((blocked_df["side"].astype(str).str.upper() == "SHORT").sum()) if not blocked_df.empty else 0,
    }


def _variant_specs(symbol: str) -> list[dict[str, Any]]:
    symbol = str(symbol).lower()
    if symbol == "eth":
        groups = sorted(ETH_REG_GROUPS)
        return [
            {"name": "event_reg", "kind": "event_whitelist", "groups": groups},
            {"name": "combined_reg", "kind": "combined_whitelist", "groups": groups},
            {"name": "event_only", "kind": "event_all", "groups": []},
            {"name": "coinglass_only", "kind": "coinglass", "groups": []},
            {"name": "combined_stack", "kind": "combined_all", "groups": []},
        ]
    groups = sorted(SOL_CRYPTO_GROUPS)
    return [
        {"name": "event_crypto", "kind": "event_whitelist", "groups": groups},
        {"name": "combined_crypto", "kind": "combined_whitelist", "groups": groups},
        {"name": "event_only", "kind": "event_all", "groups": []},
        {"name": "coinglass_only", "kind": "coinglass", "groups": []},
        {"name": "combined_stack", "kind": "combined_all", "groups": []},
    ]


def _eval_variants(trades: pd.DataFrame, symbol: str, initial_equity: float) -> list[dict[str, Any]]:
    if trades is None or trades.empty:
        return []
    event_all = trades.get("event_blocked", pd.Series(False, index=trades.index)).fillna(False).astype(bool)
    cg = _coinglass_mask(trades)
    rows: list[dict[str, Any]] = []
    for spec in _variant_specs(symbol):
        kind = spec["kind"]
        groups = spec.get("groups", [])
        if kind == "event_whitelist":
            mask = _whitelist_mask(trades, groups)
        elif kind == "combined_whitelist":
            mask = _whitelist_mask(trades, groups) | cg
        elif kind == "event_all":
            mask = event_all
        elif kind == "coinglass":
            mask = cg
        elif kind == "combined_all":
            mask = event_all | cg
        else:
            mask = pd.Series(False, index=trades.index)
        row = _evaluate_mask(trades, mask, str(spec["name"]), initial_equity)
        row["groups"] = list(groups)
        rows.append(row)
    return rows


def _best_variant(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "variant": "no_guard",
            "blocked": 0,
            "pnl_delta": 0.0,
            "dd_delta": 0.0,
            "score": 0.0,
            "gated": {"trades": 0, "pf": float("nan"), "ret": 0.0, "maxdd": 0.0},
            "top_event_groups": [],
            "decision": "无结果",
            "groups": [],
            "blocked_long": 0,
            "blocked_short": 0,
        }
    def sort_key(row: dict[str, Any]) -> tuple:
        gated = row["gated"]
        pf = _safe_float(gated.get("pf"), default=-1.0)
        ret = _safe_float(gated.get("ret"), default=-1.0)
        dd = -abs(_safe_float(gated.get("maxdd"), default=1.0))
        score = _safe_float(row.get("score"), default=-999.0)
        blocked = int(row.get("blocked", 0) or 0)
        return (pf >= 1.0 and ret > 0, score > 0, pf, ret, dd, blocked, score)
    best = sorted(rows, key=sort_key, reverse=True)[0]
    gated = best["gated"]
    pf = _safe_float(gated.get("pf"))
    ret = _safe_float(gated.get("ret"), default=-1.0)
    mdd = abs(_safe_float(gated.get("maxdd"), default=1.0))
    trades = int(gated.get("trades", 0) or 0)
    decision = "继续研究"
    if pf >= 1.0 and ret > 0 and mdd <= 0.35 and trades >= 60:
        decision = "继续深挖"
    elif _safe_float(best.get("pnl_delta")) > 0 and _safe_float(best.get("dd_delta")) >= 0 and trades >= 60:
        decision = "保留观察"
    best = dict(best)
    best["decision"] = decision
    return best


def main() -> None:
    ap = argparse.ArgumentParser(description="ALT 短波按标的分层消息面 overlay 研究（ETH/SOL）")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--profile", choices=["quick", "full"], default="quick")
    ap.add_argument("--out", default=str(Path.home() / "Downloads" / "alt_shortwave_symbol_overlay_latest.txt"))
    ap.add_argument("--json-out", default=str(Path.home() / "Downloads" / "alt_shortwave_symbol_overlay_latest.json"))
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    cfg = read_config(root / "config.yml")
    initial_equity = float(cfg.get("portfolio", {}).get("initial_equity", 100000.0))
    rows: list[dict[str, Any]] = []
    items = _base_candidate_items(args.profile)
    for item in items:
        trades = _run_candidate(root, cfg, item)
        base = _trade_metrics_from_df(trades, initial_equity)
        trades_msg = _attach_message_layers(root, trades)
        variants = _eval_variants(trades_msg, str(item["symbol"]), initial_equity)
        best = _best_variant(variants)
        rows.append({
            "name": str(item["name"]),
            "symbol": str(item["symbol"]),
            "note": str(item.get("note", "")),
            "base": base,
            "variants": variants,
            "best_overlay": best,
        })

    def sort_key(row: dict[str, Any]) -> tuple:
        ov = row["best_overlay"]
        gated = ov["gated"]
        return (
            ov["decision"] == "继续深挖",
            ov["decision"] == "保留观察",
            _safe_float(gated.get("pf"), default=-1.0),
            _safe_float(gated.get("ret"), default=-1.0),
            _safe_float(ov.get("score"), default=-999.0),
        )

    rows = sorted(rows, key=sort_key, reverse=True)
    best = rows[0] if rows else None

    lines: list[str] = []
    lines.append("ALT 短波按标的分层消息面 overlay 研究（ETH/SOL，只做 research，不改 live）")
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
            f"  overlay={ov['variant']} | blocked={ov['blocked']} (long={ov['blocked_long']}, short={ov['blocked_short']}) | pnl_delta={ov['pnl_delta']:+.2f} | maxdd_delta={_fmt_pct(ov['dd_delta'])} | score={ov['score']:+.4f} | decision={ov['decision']}"
        )
        lines.append(
            f"  gated_trades={gated['trades']} | gated_pf={gated['pf']:.3f} | gated_ret={_fmt_pct(gated['ret'])} | gated_maxDD={_fmt_pct(gated['maxdd'])}"
        )
        if ov.get("groups"):
            lines.append(f"  overlay_groups={'; '.join([str(x) for x in ov.get('groups', [])[:8]])}")
        if ov.get("top_event_groups"):
            lines.append(f"  top_event_groups={'; '.join([str(x) for x in ov.get('top_event_groups', [])[:5]])}")
        lines.append(f"  note: {row['note']}")
    lines.append("")
    lines.append("=== 结论 ===")
    if best is None:
        lines.append("- 无结果。")
    else:
        lines.append(f"- 当前总最优：{best['name']} | symbol={best['symbol']} | overlay={best['best_overlay']['variant']} | decision={best['best_overlay']['decision']}")
        lines.append("- ETH 重点看监管/ETF 事件组；SOL 重点看加密原生冲击事件组。")
        lines.append("- 消息面仍只做 risk overlay；只有 gated_pf>=1 且 gated_ret>0，才进入更严格 walk-forward。")

    payload = {
        "profile": args.profile,
        "version": cfg.get("system", {}).get("version", "NA"),
        "rows": rows,
        "best": best,
        "eth_groups": sorted(ETH_REG_GROUPS),
        "sol_groups": sorted(SOL_CRYPTO_GROUPS),
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
