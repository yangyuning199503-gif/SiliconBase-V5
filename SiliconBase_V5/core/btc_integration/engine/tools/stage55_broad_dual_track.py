from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest.engine import run_backtest_portfolio

try:
    from tools import research_config_baseline as rcb
    from tools import stage46_aggressive_lab as s46
    from tools import stage54_full_angle as s54
except Exception as exc:
    raise SystemExit("缺少 stage46 / stage54 模块，请先保留并应用相关补丁。") from exc


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
    except Exception:
        return default
    if math.isnan(v):
        return default
    return v


def _fmt_pct(x: Any) -> str:
    try:
        return f"{float(x) * 100:.2f}%"
    except Exception:
        return "NA"


def _with_side(mods: dict[str, Any], symbol: str, side: str) -> dict[str, Any]:
    out = copy.deepcopy(mods)
    if side == "long":
        out["strategy_params.allow_short"] = False
        out["strategy_params.long_symbols"] = [symbol]
        out["strategy_params.short_symbols"] = []
    elif side == "short":
        out["strategy_params.allow_short"] = True
        out["strategy_params.long_symbols"] = []
        out["strategy_params.short_symbols"] = [symbol]
    else:
        out["strategy_params.allow_short"] = True
        out.setdefault("strategy_params.long_symbols", [symbol])
        out.setdefault("strategy_params.short_symbols", [symbol])
    return out


def _mainline_items() -> list[dict[str, Any]]:
    return [
        {"name": "mainline_live_base", "mods": {}, "note": "当前 live 主线，对照组"},
        {
            "name": "mainline_split_adx26_cd6_lb24_zone028",
            "note": "BNB 长腿 + BTC 短腿拆开测，ADX26 / cd6 / lb24 / zone028",
            "mods": {
                "strategy_params.cooldown_bars": 6,
                "strategy_params.long_symbols": ["bnb"],
                "strategy_params.short_symbols": ["btc"],
                "filters.adx_floor": 26,
                "filters.btc_adx_floor": 26,
                "sr_entries.enabled": True,
                "sr_entries.symbols": ["bnb"],
                "sr_entries.lookback_4h": 24,
                "sr_entries.zone_atr_mult": 0.28,
                "sr_entries.use_adx_filter": True,
                "sr_entries.adx_min": 0.0,
                "sr_entries.adx_max": 26.0,
                "sr_entries.stake_scale": 0.16,
                "sr_entries.cooldown_bars": 6,
                "sr_entries.require_compress_ok": True,
                "filters.btc_short_pullback_atr": 0.95,
                "filters.btc_short_macro_tf": "4h",
            },
        },
        {
            "name": "mainline_split_adx28_cd6_lb24_zone028",
            "note": "主线中速提频，先看分腿后质量",
            "mods": {
                "strategy_params.cooldown_bars": 6,
                "strategy_params.long_symbols": ["bnb"],
                "strategy_params.short_symbols": ["btc"],
                "filters.adx_floor": 28,
                "filters.btc_adx_floor": 28,
                "sr_entries.enabled": True,
                "sr_entries.symbols": ["bnb"],
                "sr_entries.lookback_4h": 24,
                "sr_entries.zone_atr_mult": 0.28,
                "sr_entries.use_adx_filter": True,
                "sr_entries.adx_min": 0.0,
                "sr_entries.adx_max": 28.0,
                "sr_entries.stake_scale": 0.16,
                "sr_entries.cooldown_bars": 6,
                "sr_entries.require_compress_ok": True,
                "filters.btc_short_pullback_atr": 0.95,
                "filters.btc_short_macro_tf": "4h",
            },
        },
        {
            "name": "mainline_split_adx28_cd5_lb22_zone027",
            "note": "激进但不硬冲 350+ 笔，先冲 220~260 区间",
            "mods": {
                "strategy_params.cooldown_bars": 5,
                "strategy_params.long_symbols": ["bnb"],
                "strategy_params.short_symbols": ["btc"],
                "filters.adx_floor": 28,
                "filters.btc_adx_floor": 28,
                "sr_entries.enabled": True,
                "sr_entries.symbols": ["bnb"],
                "sr_entries.lookback_4h": 22,
                "sr_entries.zone_atr_mult": 0.27,
                "sr_entries.use_adx_filter": True,
                "sr_entries.adx_min": 0.0,
                "sr_entries.adx_max": 28.0,
                "sr_entries.stake_scale": 0.17,
                "sr_entries.cooldown_bars": 5,
                "sr_entries.require_compress_ok": True,
                "filters.btc_short_pullback_atr": 0.98,
                "filters.btc_short_macro_tf": "4h",
            },
        },
        {
            "name": "mainline_split_adx30_cd5_lb22_zone027",
            "note": "更激进的中高频边界测试",
            "mods": {
                "strategy_params.cooldown_bars": 5,
                "strategy_params.long_symbols": ["bnb"],
                "strategy_params.short_symbols": ["btc"],
                "filters.adx_floor": 30,
                "filters.btc_adx_floor": 30,
                "sr_entries.enabled": True,
                "sr_entries.symbols": ["bnb"],
                "sr_entries.lookback_4h": 22,
                "sr_entries.zone_atr_mult": 0.27,
                "sr_entries.use_adx_filter": True,
                "sr_entries.adx_min": 0.0,
                "sr_entries.adx_max": 30.0,
                "sr_entries.stake_scale": 0.18,
                "sr_entries.cooldown_bars": 5,
                "sr_entries.require_compress_ok": True,
                "filters.btc_short_pullback_atr": 1.00,
                "filters.btc_short_macro_tf": "4h",
            },
        },
        {
            "name": "mainline_split_adx26_cd5_lb20_zone026",
            "note": "更快回看窗口 + 保守 ADX，验证是否更均衡",
            "mods": {
                "strategy_params.cooldown_bars": 5,
                "strategy_params.long_symbols": ["bnb"],
                "strategy_params.short_symbols": ["btc"],
                "filters.adx_floor": 26,
                "filters.btc_adx_floor": 26,
                "sr_entries.enabled": True,
                "sr_entries.symbols": ["bnb"],
                "sr_entries.lookback_4h": 20,
                "sr_entries.zone_atr_mult": 0.26,
                "sr_entries.use_adx_filter": True,
                "sr_entries.adx_min": 0.0,
                "sr_entries.adx_max": 26.0,
                "sr_entries.stake_scale": 0.17,
                "sr_entries.cooldown_bars": 5,
                "sr_entries.require_compress_ok": True,
                "filters.btc_short_pullback_atr": 1.00,
                "filters.btc_short_macro_tf": "4h",
            },
        },
    ]


def _branch_candidates() -> list[dict[str, Any]]:
    item_map = {item["name"]: copy.deepcopy(item) for item in s54._branch_items()}
    rows: list[dict[str, Any]] = []

    def add_existing(symbol: str, base_name: str, new_name: str, side: str, note: str) -> None:
        item = item_map.get(base_name)
        if not item:
            return
        mods = _with_side(item.get("mods", {}), symbol, side)
        rows.append({"symbol": symbol, "name": new_name, "note": note, "mods": mods})

    # Existing broad-map families, but split by side
    add_existing("sol", "sol_fast_trend_4h_lb16", "sol_fast_trend_lb16_shortonly", "short", "延续 Stage54 里 SOL 最强短腿")
    add_existing("sol", "sol_hybrid_mr", "sol_hybrid_mr_shortonly", "short", "保留 SOL 短腿备份，不预设 dead")
    add_existing("sol", "sol_shortwave_sr_smooth", "sol_shortwave_smooth_longonly", "long", "保留 SOL 平滑回踩长腿")
    add_existing("sol", "sol_shortwave_sr", "sol_shortwave_longonly", "long", "保留 SOL 回踩长腿快版")
    add_existing("eth", "eth_fast_trend_4h_lb16", "eth_fast_trend_lb16_longonly", "long", "ETH 趋势长腿，不再一刀切判弱")
    add_existing("eth", "eth_shortwave_sr", "eth_shortwave_longonly", "long", "ETH 回踩长腿")
    add_existing("eth", "eth_shortwave_sr_tight", "eth_shortwave_tight_shortonly", "short", "ETH 紧致短腿")
    add_existing("eth", "eth_fast_trend_4h", "eth_fast_trend_shortonly", "short", "ETH 趋势短腿备份")

    # Hard-coded broad-angle engines
    rows.extend(
        [
            {
                "symbol": "sol",
                "name": "sol_long_core_adx28_cd6_lb22_zone027_s038",
                "note": "SOL 长腿主核，保留 compress，不放弃 long",
                "mods": {
                    "strategy_params.allow_short": False,
                    "strategy_params.long_symbols": ["sol"],
                    "strategy_params.short_symbols": [],
                    "mean_reversion.enabled": False,
                    "filters.adx_floor": 99,
                    "strategy_params.breakout_atr_buffer": 9.0,
                    "strategy_params.cooldown_bars": 6,
                    "sr_entries.enabled": True,
                    "sr_entries.symbols": ["sol"],
                    "sr_entries.lookback_4h": 22,
                    "sr_entries.zone_atr_mult": 0.27,
                    "sr_entries.use_adx_filter": True,
                    "sr_entries.adx_min": 0.0,
                    "sr_entries.adx_max": 28.0,
                    "sr_entries.stake_scale": 0.38,
                    "sr_entries.cooldown_bars": 6,
                    "sr_entries.require_compress_ok": True,
                },
            },
            {
                "symbol": "sol",
                "name": "sol_short_shock_lb16_adx22",
                "note": "SOL 黑天鹅/破位短腿原型",
                "mods": {
                    "strategy_params.allow_short": True,
                    "strategy_params.long_symbols": [],
                    "strategy_params.short_symbols": ["sol"],
                    "mean_reversion.enabled": False,
                    "sr_entries.enabled": False,
                    "strategy_params.cooldown_bars": 6,
                    "strategy_params.breakout_lookback": 16,
                    "strategy_params.breakout_atr_buffer": 0.5,
                    "filters.adx_floor": 22,
                    "filters.macro_gate_symbols": ["sol"],
                    "filters.macro_gate_reference_symbol": "btc",
                    "filters.macro_gate_tf_by_symbol.sol": "4h",
                    "money_management.stake_scale.sol_short": 0.85,
                },
            },
            {
                "symbol": "sol",
                "name": "sol_dual_guarded_core_plus_shock",
                "note": "SOL 双引擎守卫版，不再只看单边",
                "mods": {
                    "strategy_params.allow_short": True,
                    "strategy_params.long_symbols": ["sol"],
                    "strategy_params.short_symbols": ["sol"],
                    "mean_reversion.enabled": False,
                    "filters.adx_floor": 28,
                    "strategy_params.breakout_lookback": 20,
                    "strategy_params.breakout_atr_buffer": 0.8,
                    "strategy_params.cooldown_bars": 8,
                    "sr_entries.enabled": True,
                    "sr_entries.symbols": ["sol"],
                    "sr_entries.lookback_4h": 22,
                    "sr_entries.zone_atr_mult": 0.27,
                    "sr_entries.use_adx_filter": True,
                    "sr_entries.adx_min": 0.0,
                    "sr_entries.adx_max": 28.0,
                    "sr_entries.stake_scale": 0.26,
                    "sr_entries.cooldown_bars": 6,
                    "sr_entries.require_compress_ok": True,
                    "filters.macro_gate_symbols": ["sol"],
                    "filters.macro_gate_reference_symbol": "btc",
                    "filters.macro_gate_tf_by_symbol.sol": "4h",
                    "money_management.stake_scale.sol_short": 0.50,
                },
            },
            {
                "symbol": "eth",
                "name": "eth_long_core_adx26_cd6_lb24_zone028_s032",
                "note": "ETH 长腿主核，重新按大角度建模",
                "mods": {
                    "strategy_params.allow_short": False,
                    "strategy_params.long_symbols": ["eth"],
                    "strategy_params.short_symbols": [],
                    "mean_reversion.enabled": False,
                    "filters.adx_floor": 99,
                    "strategy_params.breakout_atr_buffer": 9.0,
                    "strategy_params.cooldown_bars": 6,
                    "sr_entries.enabled": True,
                    "sr_entries.symbols": ["eth"],
                    "sr_entries.lookback_4h": 24,
                    "sr_entries.zone_atr_mult": 0.28,
                    "sr_entries.use_adx_filter": True,
                    "sr_entries.adx_min": 0.0,
                    "sr_entries.adx_max": 26.0,
                    "sr_entries.stake_scale": 0.32,
                    "sr_entries.cooldown_bars": 6,
                    "sr_entries.require_compress_ok": True,
                },
            },
            {
                "symbol": "eth",
                "name": "eth_short_shock_lb16_adx24",
                "note": "ETH 事件/破位短腿原型",
                "mods": {
                    "strategy_params.allow_short": True,
                    "strategy_params.long_symbols": [],
                    "strategy_params.short_symbols": ["eth"],
                    "mean_reversion.enabled": False,
                    "sr_entries.enabled": False,
                    "strategy_params.cooldown_bars": 6,
                    "strategy_params.breakout_lookback": 16,
                    "strategy_params.breakout_atr_buffer": 0.6,
                    "filters.adx_floor": 24,
                    "filters.macro_gate_symbols": ["eth"],
                    "filters.macro_gate_reference_symbol": "btc",
                    "filters.macro_gate_tf_by_symbol.eth": "4h",
                    "money_management.stake_scale.eth_short": 0.80,
                },
            },
            {
                "symbol": "eth",
                "name": "eth_dual_guarded_core_plus_shock",
                "note": "ETH 双引擎守卫版，避免旧模板把 ETH 定死",
                "mods": {
                    "strategy_params.allow_short": True,
                    "strategy_params.long_symbols": ["eth"],
                    "strategy_params.short_symbols": ["eth"],
                    "mean_reversion.enabled": False,
                    "filters.adx_floor": 26,
                    "strategy_params.breakout_lookback": 18,
                    "strategy_params.breakout_atr_buffer": 0.7,
                    "strategy_params.cooldown_bars": 6,
                    "sr_entries.enabled": True,
                    "sr_entries.symbols": ["eth"],
                    "sr_entries.lookback_4h": 24,
                    "sr_entries.zone_atr_mult": 0.28,
                    "sr_entries.use_adx_filter": True,
                    "sr_entries.adx_min": 0.0,
                    "sr_entries.adx_max": 26.0,
                    "sr_entries.stake_scale": 0.24,
                    "sr_entries.cooldown_bars": 6,
                    "sr_entries.require_compress_ok": True,
                    "filters.macro_gate_symbols": ["eth"],
                    "filters.macro_gate_reference_symbol": "btc",
                    "filters.macro_gate_tf_by_symbol.eth": "4h",
                    "money_management.stake_scale.eth_short": 0.45,
                },
            },
        ]
    )
    return rows


def _run_mainline(root: Path, cfg: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    row = s54._run_mainline(root, cfg, item)
    gated = row["best_overlay"]["gated"]
    seg_vals = [float(v) for v in row.get("seg_pf", {}).values() if not math.isnan(float(v))]
    seg_floor = min(seg_vals) if seg_vals else 0.0
    row["seg_floor"] = seg_floor
    long_pf = _safe_float(row.get("gated_long", {}).get("pf"), 0.0)
    short_pf = _safe_float(row.get("gated_short", {}).get("pf"), 0.0)
    score = (
        _safe_float(gated.get("pf"), 0.0) * 115.0
        + _safe_float(gated.get("ret"), -1.0) * 65.0
        - abs(_safe_float(gated.get("maxdd"), 1.0)) * 78.0
        + min(int(gated.get("trades", 0) or 0), 260) * 0.28
        + seg_floor * 18.0
        + long_pf * 4.0
        + min(short_pf, 1.5) * 10.0
    )
    row["score"] = float(score)
    row["decision"] = _main_decision(row)
    return row


def _main_decision(row: dict[str, Any]) -> str:
    gated = row["best_overlay"]["gated"]
    pf = _safe_float(gated.get("pf"), 0.0)
    ret = _safe_float(gated.get("ret"), -1.0)
    maxdd = abs(_safe_float(gated.get("maxdd"), 1.0))
    trades = int(gated.get("trades", 0) or 0)
    short_pf = _safe_float(row.get("gated_short", {}).get("pf"), 0.0)
    seg_floor = _safe_float(row.get("seg_floor"), 0.0)
    if row["name"] == "mainline_live_base":
        return "对照组"
    if trades >= 210 and pf >= 1.55 and ret > 0 and maxdd <= 0.42 and seg_floor >= 0.90 and short_pf >= 0.85:
        return "继续深挖"
    if trades >= 190 and pf >= 1.35 and ret > 0 and maxdd <= 0.48:
        return "保留观察"
    return "淘汰"


def _run_branch_engine(root: Path, cfg: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    symbol = str(item["symbol"])
    cfg2 = copy.deepcopy(cfg)
    cfg2.setdefault("data", {})["symbols"] = [symbol]
    cfg2.setdefault("data", {})["weights"] = {symbol: 1.0}
    for path, value in item.get("mods", {}).items():
        s46._set_nested(cfg2, path, value)
    cfg2.setdefault("filters", {}).setdefault("macro_gate_symbols", [symbol])
    cfg2.setdefault("filters", {}).setdefault("macro_gate_reference_symbol", symbol)
    data = s46._load_portfolio_data(root, cfg2)
    eq, trades, _ = run_backtest_portfolio(data, cfg2)
    base = s46._metrics(eq, trades, float(cfg2.get("portfolio", {}).get("initial_equity", 100000.0)))
    best, gated_df = s54._overlay_bundle(root, trades)
    row = {
        "name": item["name"],
        "symbol": symbol,
        "note": item.get("note", ""),
        "base": base,
        "best_overlay": best,
        "gated_long": s54._side_metrics(gated_df, "LONG"),
        "gated_short": s54._side_metrics(gated_df, "SHORT"),
        "mods": item.get("mods", {}),
    }
    row["bias"] = s54._bias_label(row["gated_long"], row["gated_short"])
    row["score"] = _branch_score(row)
    row["decision"] = _branch_decision(row)
    return row


def _branch_score(row: dict[str, Any]) -> float:
    gated = row["best_overlay"]["gated"]
    m = row.get("base", {}).get("monthly", {}) or {}
    long_pf = _safe_float(row.get("gated_long", {}).get("pf"), 0.0)
    short_pf = _safe_float(row.get("gated_short", {}).get("pf"), 0.0)
    return float(
        _safe_float(gated.get("pf"), 0.0) * 96.0
        + _safe_float(gated.get("ret"), -1.0) * 55.0
        - abs(_safe_float(gated.get("maxdd"), 1.0)) * 72.0
        + int(gated.get("trades", 0) or 0) * 0.20
        + int(m.get("months_ge_20", 0)) * 9.0
        + _safe_float(m.get("monthly_p75"), 0.0) * 120.0
        + min(_safe_float(row.get("base", {}).get("rolling12_pf_floor"), 0.0), 2.0) * 11.0
        + max(long_pf, short_pf) * 10.0
    )


def _branch_decision(row: dict[str, Any]) -> str:
    gated = row["best_overlay"]["gated"]
    pf = _safe_float(gated.get("pf"), 0.0)
    ret = _safe_float(gated.get("ret"), -1.0)
    maxdd = abs(_safe_float(gated.get("maxdd"), 1.0))
    trades = int(gated.get("trades", 0) or 0)
    floor = _safe_float(row.get("base", {}).get("rolling12_pf_floor"), 0.0)
    if pf >= 1.10 and ret > 0 and maxdd <= 0.50 and trades >= 18 and floor >= 0.95:
        return "继续深挖"
    if pf >= 0.95 and trades >= 10 and maxdd <= 0.65:
        return "保留观察"
    if trades > 0:
        return "继续研究"
    return "淘汰"


def _write_mainline(path_txt: Path, path_json: Path, rows: list[dict[str, Any]], version: str) -> None:
    best = rows[0] if rows else None
    lines: list[str] = []
    lines.append("Stage55 主线双线提频研究")
    lines.append(f"version: {version}")
    lines.append("")
    lines.append("=== 候选结果 ===")
    for row in rows:
        gated = row["best_overlay"]["gated"]
        lines.append(
            f"- {row['name']}: gated_trades={gated.get('trades', 0)} | gated_pf={_safe_float(gated.get('pf'), float('nan')):.3f} | gated_ret={_fmt_pct(gated.get('ret'))} | gated_maxDD={_fmt_pct(gated.get('maxdd'))} | seg_floor={row.get('seg_floor', 0.0):.3f} | overlay={row['best_overlay'].get('variant')} | score={row['score']:+.2f} | decision={row['decision']}"
        )
        lines.append(
            f"  long_leg: trades={row['gated_long']['trades']} pf={_safe_float(row['gated_long'].get('pf'), float('nan')):.3f} | short_leg: trades={row['gated_short']['trades']} pf={_safe_float(row['gated_short'].get('pf'), float('nan')):.3f}"
        )
    lines.append("")
    lines.append("=== 结论 ===")
    lines.append("- 主线提频不停，但不再硬冲 350+；本轮改成 BNB 长腿 / BTC 短腿拆开测，目标 220~260 笔。")
    if best is not None:
        gated = best["best_overlay"]["gated"]
        lines.append(
            f"- 当前主线第一候选：{best['name']} | trades={gated.get('trades', 0)} | gated_pf={_safe_float(gated.get('pf'), float('nan')):.3f} | gated_ret={_fmt_pct(gated.get('ret'))} | decision={best['decision']}"
        )
    lines.append("- 消息面继续只做 risk overlay；若短腿仍拖累，则下一轮继续单独收紧 BTC 短腿，而不是全局回撤。")
    path_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    path_json.write_text(json.dumps({"rows": rows, "best": best}, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_branch(path_txt: Path, path_json: Path, rows: list[dict[str, Any]], version: str) -> None:
    best_by_symbol: dict[str, dict[str, dict[str, Any]]] = {"eth": {}, "sol": {}}
    for sym in ["eth", "sol"]:
        sub = [r for r in rows if r["symbol"] == sym]
        if not sub:
            continue
        long_rows = [r for r in sub if r["gated_long"].get("trades", 0) > 0]
        short_rows = [r for r in sub if r["gated_short"].get("trades", 0) > 0]
        dual_rows = [r for r in sub if r["gated_long"].get("trades", 0) > 0 and r["gated_short"].get("trades", 0) > 0]
        if long_rows:
            best_by_symbol[sym]["long"] = sorted(long_rows, key=lambda r: (r["decision"] == "继续深挖", r["decision"] == "保留观察", r["score"]), reverse=True)[0]
        if short_rows:
            best_by_symbol[sym]["short"] = sorted(short_rows, key=lambda r: (r["decision"] == "继续深挖", r["decision"] == "保留观察", r["score"]), reverse=True)[0]
        if dual_rows:
            best_by_symbol[sym]["dual"] = sorted(dual_rows, key=lambda r: (r["decision"] == "继续深挖", r["decision"] == "保留观察", r["score"]), reverse=True)[0]

    lines: list[str] = []
    lines.append("Stage55 ETH + SOL 双引擎广角研究")
    lines.append(f"version: {version}")
    lines.append("")
    lines.append("=== 分方向最优 ===")
    for sym in ["eth", "sol"]:
        for side in ["long", "short", "dual"]:
            row = best_by_symbol.get(sym, {}).get(side)
            if row is None:
                continue
            gated = row["best_overlay"]["gated"]
            lines.append(
                f"- {sym}_{side}: {row['name']} | bias={row['bias']} | overlay={row['best_overlay'].get('variant')} | trades={gated.get('trades', 0)} | gated_pf={_safe_float(gated.get('pf'), float('nan')):.3f} | gated_ret={_fmt_pct(gated.get('ret'))} | gated_maxDD={_fmt_pct(gated.get('maxdd'))} | decision={row['decision']}"
            )
            lines.append(
                f"  long_leg: trades={row['gated_long']['trades']} pf={_safe_float(row['gated_long'].get('pf'), float('nan')):.3f} | short_leg: trades={row['gated_short']['trades']} pf={_safe_float(row['gated_short'].get('pf'), float('nan')):.3f}"
            )
    lines.append("")
    lines.append("=== 全部候选 ===")
    for row in rows:
        gated = row["best_overlay"]["gated"]
        lines.append(
            f"- {row['name']}: symbol={row['symbol']} | bias={row['bias']} | gated_pf={_safe_float(gated.get('pf'), float('nan')):.3f} | gated_ret={_fmt_pct(gated.get('ret'))} | gated_maxDD={_fmt_pct(gated.get('maxdd'))} | trades={gated.get('trades', 0)} | overlay={row['best_overlay'].get('variant')} | score={row['score']:+.2f} | decision={row['decision']}"
        )
        lines.append(
            f"  long_leg: trades={row['gated_long']['trades']} pf={_safe_float(row['gated_long'].get('pf'), float('nan')):.3f} | short_leg: trades={row['gated_short']['trades']} pf={_safe_float(row['gated_short'].get('pf'), float('nan')):.3f}"
        )
    lines.append("")
    lines.append("=== 结论 ===")
    lines.append("- 不再把 SOL 预设成 long-only；本轮直接同时评估 long / short / dual。")
    lines.append("- 不再把 ETH 预设成弱；若旧模板仍差，说明该换结构，不代表 ETH 本身差。")
    lines.append("- 消息面继续只做 risk overlay；只有结构先站住，才考虑升成更强信号层。")
    path_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    path_json.write_text(json.dumps({"rows": rows, "best_by_symbol": best_by_symbol}, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage55 broad dual-track: mainline frequency + ETH/SOL dual engines")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    cfg = rcb.load_research_base_config(root)
    reports = root / "reports" / "research_raw"
    reports.mkdir(parents=True, exist_ok=True)

    main_rows = [_run_mainline(root, cfg, item) for item in _mainline_items()]
    main_rows = sorted(main_rows, key=lambda r: (r["decision"] == "继续深挖", r["decision"] == "保留观察", r["score"]), reverse=True)

    branch_rows = [_run_branch_engine(root, cfg, item) for item in _branch_candidates()]
    branch_rows = sorted(branch_rows, key=lambda r: (r["decision"] == "继续深挖", r["decision"] == "保留观察", r["score"]), reverse=True)

    _write_mainline(
        reports / "stage55_mainline_dualtrack_latest.txt",
        reports / "stage55_mainline_dualtrack_latest.json",
        main_rows,
        str(cfg.get("system", {}).get("version", "NA")),
    )
    _write_branch(
        reports / "stage55_branch_dual_engines_latest.txt",
        reports / "stage55_branch_dual_engines_latest.json",
        branch_rows,
        str(cfg.get("system", {}).get("version", "NA")),
    )


if __name__ == "__main__":
    main()
