from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest.io import read_config

try:
    from tools import stage46_aggressive_lab as s46
    from tools import stage59_structural_lab as s59
    from tools import stage64_relevance_hybrid_lab as s64
except Exception as exc:
    raise SystemExit("缺少 stage46/stage59/stage64 模块，请先保留此前补丁。") from exc


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


def _bool_col(df: pd.DataFrame, name: str, default: bool = False) -> pd.Series:
    if name in df.columns:
        return df[name].fillna(default).astype(bool)
    return pd.Series(default, index=df.index)


def _num_col(df: pd.DataFrame, name: str, default: float = 0.0) -> pd.Series:
    if name in df.columns:
        return pd.to_numeric(df[name], errors="coerce").fillna(default)
    return pd.Series(default, index=df.index, dtype=float)


def _mainline_items() -> list[dict[str, Any]]:
    wanted = {
        "combo_sr_soft_adx26_cd6_lb24_zone028_ref",
        "combo_sr_soft_adx28_cd6_lb24_zone028",
        "combo_sr_soft_adx30_cd6_lb22_zone026",
        "combo_sr_soft_adx30_cd5_lb22_zone026",
        "combo_sr_soft_adx32_cd5_lb20_zone025",
    }
    rows = [copy.deepcopy(x) for x in s64._mainline_items() if x.get("name") in wanted]
    if not rows:
        rows = [copy.deepcopy(x) for x in s64._mainline_items()]
    return rows


def _branch_items() -> list[dict[str, Any]]:
    wanted = {
        "sol_long_core_adx28_cd6_lb22_zone027_s038",
        "sol_fast_trend_lb16_shortonly",
        "sol_short_shock_lb16_adx22",
        "sol_dual_guarded_core_plus_shock",
        "eth_long_core_adx26_cd6_lb24_zone028_s032",
        "eth_shortwave_tight_shortonly",
        "eth_short_shock_lb16_adx24",
        "eth_dual_guarded_core_plus_shock",
    }
    rows = [copy.deepcopy(x) for x in s64._branch_items() if x.get("name") in wanted]
    if not rows:
        rows = [copy.deepcopy(x) for x in s64._branch_items()]
    return rows


# -----------------------------
# Gates
# -----------------------------

def _gate_none(df: pd.DataFrame) -> pd.Series:
    return pd.Series(True, index=df.index)


def _gate_neutral_revert(df: pd.DataFrame) -> pd.Series:
    neutral = _bool_col(df, "neutral_event", True)
    wick = _bool_col(df, "wick_revert_ok", False)
    spike = _bool_col(df, "spike_fade_ok", False)
    return neutral & (wick | spike)


def _gate_impact_tiered(df: pd.DataFrame) -> pd.Series:
    side = df.get("side", pd.Series(index=df.index, dtype=str)).astype(str).str.upper()
    symbol = df.get("symbol", pd.Series(index=df.index, dtype=str)).astype(str).str.upper()
    neutral = _bool_col(df, "neutral_event", True)
    blocked = _bool_col(df, "event_blocked", False)
    wick = _bool_col(df, "wick_revert_ok", False)
    spike = _bool_col(df, "spike_fade_ok", False)
    flow = _bool_col(df, "flow_aligned", True)
    crowded = _bool_col(df, "risk_crowded_long", False)
    oi_high = _bool_col(df, "risk_oi_high", False)
    range_rel = _num_col(df, "range_rel", 1.0)
    vol_rel = _num_col(df, "vol_rel", 1.0)
    impulse = (range_rel >= 1.15) | (vol_rel >= 1.05)
    struct = wick | spike

    long_neutral = (side == "LONG") & neutral & struct & impulse
    long_event = (side == "LONG") & ((~neutral) | blocked) & flow & ~crowded & ~oi_high & impulse

    short_neutral = (side == "SHORT") & neutral & struct & (crowded | oi_high) & impulse
    short_event = (side == "SHORT") & ((~neutral) | blocked) & flow & (crowded | oi_high | blocked) & impulse

    bnb_long = (symbol == "BNB") & (long_neutral | long_event)
    btc_short = (symbol == "BTC") & (short_neutral | short_event)
    other_long = (symbol != "BTC") & (side == "LONG") & (long_neutral | long_event)
    other_short = (symbol != "BNB") & (side == "SHORT") & (short_neutral | short_event)
    return bnb_long | btc_short | other_long | other_short


def _gate_impact_tiered_flow(df: pd.DataFrame) -> pd.Series:
    side = df.get("side", pd.Series(index=df.index, dtype=str)).astype(str).str.upper()
    neutral = _bool_col(df, "neutral_event", True)
    blocked = _bool_col(df, "event_blocked", False)
    wick = _bool_col(df, "wick_revert_ok", False)
    spike = _bool_col(df, "spike_fade_ok", False)
    flow = _bool_col(df, "flow_aligned", True)
    crowded = _bool_col(df, "risk_crowded_long", False)
    oi_high = _bool_col(df, "risk_oi_high", False)
    range_rel = _num_col(df, "range_rel", 1.0)
    vol_rel = _num_col(df, "vol_rel", 1.0)
    bar_ret = _num_col(df, "bar_ret", 0.0).abs()
    strong_impulse = (range_rel >= 1.20) & ((vol_rel >= 1.05) | (bar_ret >= 0.008))
    struct = wick | spike

    long_ok = (side == "LONG") & (
        (neutral & struct & flow & strong_impulse & ~crowded)
        | (((~neutral) | blocked) & flow & ~crowded & ~oi_high & strong_impulse)
    )
    short_ok = (side == "SHORT") & (
        (neutral & struct & flow & (crowded | oi_high) & strong_impulse)
        | (((~neutral) | blocked) & flow & (crowded | oi_high | blocked) & strong_impulse)
    )
    return long_ok | short_ok


def _gate_shock_confirm(df: pd.DataFrame) -> pd.Series:
    side = df.get("side", pd.Series(index=df.index, dtype=str)).astype(str).str.upper()
    neutral = _bool_col(df, "neutral_event", True)
    blocked = _bool_col(df, "event_blocked", False)
    flow = _bool_col(df, "flow_aligned", True)
    crowded = _bool_col(df, "risk_crowded_long", False)
    oi_high = _bool_col(df, "risk_oi_high", False)
    wick = _bool_col(df, "wick_revert_ok", False)
    spike = _bool_col(df, "spike_fade_ok", False)
    range_rel = _num_col(df, "range_rel", 1.0)
    vol_rel = _num_col(df, "vol_rel", 1.0)
    bar_ret = _num_col(df, "bar_ret", 0.0).abs()
    shock = (range_rel >= 1.22) | (vol_rel >= 1.12) | (bar_ret >= 0.010)

    long_event = (side == "LONG") & ((~neutral) | blocked) & flow & ~crowded & ~oi_high & shock
    short_event = (side == "SHORT") & ((~neutral) | blocked) & flow & (crowded | oi_high | blocked) & shock
    short_revert = (side == "SHORT") & neutral & (wick | spike) & flow & (crowded | oi_high) & shock
    long_revert = (side == "LONG") & neutral & (wick | spike) & flow & ~crowded & shock
    return long_event | short_event | short_revert | long_revert


GATES: list[tuple[str, Callable[[pd.DataFrame], pd.Series], str]] = [
    ("base_message_overlay", _gate_none, "只保留消息面 overlay，不加结构门"),
    ("neutral_revert", _gate_neutral_revert, "无重大消息时，只做插针/过冲回归确认"),
    ("impact_tiered", _gate_impact_tiered, "按币价影响分层：中性时看插针回归，事件时看流向/拥挤度/波动确认"),
    ("impact_tiered_flow", _gate_impact_tiered_flow, "不是单纯放宽阈值，而是放宽后再叠加流向+波动强度+结构确认"),
    ("shock_confirm", _gate_shock_confirm, "冲击窗口下做方向确认；空腿必须有 flow/crowding/波动支撑"),
]


def _main_score(metrics: dict[str, Any], ref: dict[str, Any]) -> float:
    m = metrics.get("monthly", {}) or {}
    rm = ref.get("monthly", {}) or {}
    trades = int(metrics.get("trades", 0) or 0)
    ref_trades = int(ref.get("trades", 0) or 0)
    trade_gain = max(0, trades - ref_trades)
    active_gain = max(0, int(m.get("active_months", 0)) - int(rm.get("active_months", 0)))
    months20_gain = max(0, int(m.get("months_ge_20", 0)) - int(rm.get("months_ge_20", 0)))
    pf_pen = max(0.0, _safe_float(ref.get("pf")) - _safe_float(metrics.get("pf")))
    dd_pen = max(0.0, abs(_safe_float(metrics.get("maxdd"))) - abs(_safe_float(ref.get("maxdd"))))
    ret_pen = max(0.0, _safe_float(ref.get("ret")) - _safe_float(metrics.get("ret")))
    floor_pen = max(0.0, _safe_float(ref.get("rolling12_pf_floor")) - _safe_float(metrics.get("rolling12_pf_floor")))
    seg_floor = min(float(v) for v in (metrics.get("seg_pf", {}) or {}).values()) if (metrics.get("seg_pf", {}) or {}) else 0.0
    target_bonus = 30.0 if 215 <= trades <= 250 else (18.0 if trades >= 205 else 0.0)
    return float(
        trade_gain * 1.9
        + active_gain * 2.6
        + months20_gain * 3.8
        - pf_pen * 66.0
        - dd_pen * 165.0
        - ret_pen * 6.2
        - floor_pen * 30.0
        + target_bonus
        + _safe_float(metrics.get("rolling12_pf_floor")) * 20.0
        + seg_floor * 18.0
    )


def _main_gate_label(metrics: dict[str, Any], ref: dict[str, Any]) -> str:
    if (
        int(metrics.get("trades", 0) or 0) >= max(205, int(ref.get("trades", 0) or 0) - 4)
        and _safe_float(metrics.get("pf")) >= max(2.05, _safe_float(ref.get("pf")) - 0.16)
        and _safe_float(metrics.get("ret")) >= _safe_float(ref.get("ret")) * 0.90
        and abs(_safe_float(metrics.get("maxdd"))) <= abs(_safe_float(ref.get("maxdd"))) + 0.04
        and _safe_float(metrics.get("rolling12_pf_floor")) >= max(0.74, _safe_float(ref.get("rolling12_pf_floor")) - 0.05)
    ):
        return "pass"
    if int(metrics.get("trades", 0) or 0) >= 200 and _safe_float(metrics.get("pf")) >= 1.95 and _safe_float(metrics.get("rolling12_pf_floor")) >= 0.72:
        return "hold"
    return "kill"


def _branch_score(metrics: dict[str, Any]) -> float:
    m = metrics.get("monthly", {}) or {}
    return float(
        _safe_float(metrics.get("pf")) * 92.0
        + _safe_float(metrics.get("ret")) * 64.0
        - abs(_safe_float(metrics.get("maxdd"))) * 80.0
        + min(int(metrics.get("trades", 0) or 0), 240) * 0.40
        + int(m.get("months_ge_20", 0) or 0) * 24.0
        + _safe_float(m.get("monthly_p75")) * 180.0
        + _safe_float(metrics.get("rolling12_pf_floor")) * 18.0
    )


def _branch_gate_label(metrics: dict[str, Any]) -> str:
    m = metrics.get("monthly", {}) or {}
    if (
        _safe_float(metrics.get("pf")) >= 1.12
        and _safe_float(metrics.get("ret")) > 0.0
        and abs(_safe_float(metrics.get("maxdd"))) <= 0.48
        and (int(m.get("months_ge_20", 0) or 0) >= 1 or _safe_float(m.get("monthly_p75")) >= 0.07)
    ):
        return "pass"
    if _safe_float(metrics.get("pf")) >= 1.00 and int(metrics.get("trades", 0) or 0) >= 18 and abs(_safe_float(metrics.get("maxdd"))) <= 0.60:
        return "hold"
    return "kill"


def _pick_best_gate(gate_rows: list[dict[str, Any]], score_fn: Callable[..., float], label_fn: Callable[..., str], ref_metrics: dict[str, Any] | None = None) -> dict[str, Any]:
    best = None
    best_score = -1e18
    for row in gate_rows:
        metrics = row["metrics"]
        if ref_metrics is None:
            score = score_fn(metrics)
            gate = label_fn(metrics)
        else:
            score = score_fn(metrics, ref_metrics)
            gate = label_fn(metrics, ref_metrics)
        row["score"] = score
        row["gate"] = gate
        if score > best_score:
            best_score = score
            best = row
    return best if best is not None else gate_rows[0]


def _run_mainline(root: Path, cfg: dict[str, Any], data: dict[str, pd.DataFrame], item: dict[str, Any], initial_equity: float) -> dict[str, Any]:
    trades, trades_feat = s59._run_portfolio_candidate(root, cfg, data, item["mods"])
    base_metrics = s59._metrics_from_trades(trades, initial_equity)
    gates = [s59._evaluate_gate(trades_feat, name, fn, note, initial_equity) for name, fn, note in GATES]
    return {"name": item["name"], "note": item["note"], "base_metrics": base_metrics, "gate_rows": gates}


def _run_branch(root: Path, cfg: dict[str, Any], item: dict[str, Any], initial_equity: float) -> dict[str, Any]:
    cfg2 = copy.deepcopy(cfg)
    sym = str(item["symbol"]).lower()
    cfg2.setdefault("data", {})["symbols"] = [sym]
    cfg2.setdefault("data", {})["weights"] = {sym: 1.0}
    cfg2.setdefault("filters", {})["macro_gate_symbols"] = [sym]
    cfg2.setdefault("filters", {})["macro_gate_reference_symbol"] = sym
    data = s46._load_portfolio_data(root, cfg2)
    trades, trades_feat = s59._run_portfolio_candidate(root, cfg2, data, item["mods"])
    base_metrics = s59._metrics_from_trades(trades, initial_equity)
    gates = [s59._evaluate_gate(trades_feat, name, fn, note, initial_equity) for name, fn, note in GATES]
    return {
        "symbol": sym,
        "family": item.get("family", "mixed"),
        "name": item["name"],
        "note": item.get("note", ""),
        "base_metrics": base_metrics,
        "gate_rows": gates,
    }


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, pd.DataFrame):
        return {"rows": int(len(obj)), "columns": list(obj.columns)}
    if isinstance(obj, pd.Series):
        return obj.tolist()
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if hasattr(obj, "isoformat"):
        try:
            return obj.isoformat()
        except Exception:
            pass
    try:
        import numpy as np  # type: ignore
        if isinstance(obj, (np.integer, np.floating, np.bool_)):
            return obj.item()
        if isinstance(obj, np.ndarray):
            return obj.tolist()
    except Exception:
        pass
    return obj


def _strip_gate_payload(row: dict[str, Any]) -> dict[str, Any]:
    best = dict(row.get("best_gate") or {})
    gated_df = best.pop("gated_df", None)
    if isinstance(gated_df, pd.DataFrame):
        best["gated_rows"] = int(len(gated_df))
        best["gated_columns"] = list(gated_df.columns)[:12]
    return _json_safe(best)


def _write_mainline(path_txt: Path, path_json: Path, rows: list[dict[str, Any]], ref_metrics: dict[str, Any]) -> None:
    lines: list[str] = []
    lines.append("Stage65 主线价格影响 + 结构前沿")
    lines.append("核心原则：主线提频不停，但不靠纯降门槛；放松后必须叠加流向/拥挤度/波动/结构确认")
    lines.append("")
    lines.append("=== 候选结果 ===")
    for row in rows:
        best = row["best_gate"]
        m = best["metrics"]
        mm = m.get("monthly", {}) or {}
        lines.append(
            f"- {row['name']}: best_gate={best['gate_name']} ({best['gate']}) | trades={m['trades']} | pf={_safe_float(m['pf']):.3f} | ret={_fmt_pct(m['ret'])} | maxDD={_fmt_pct(m['maxdd'])} | months>=20%={mm.get('months_ge_20', 0)} | roll12_pf_floor={_safe_float(m.get('rolling12_pf_floor')):.3f} | score={best['score']:+.2f}"
        )
        base = row.get("base_metrics", {})
        lines.append(
            f"  base=trades {base.get('trades', 0)} / pf {_safe_float(base.get('pf')):.3f} / ret {_fmt_pct(base.get('ret'))} / maxDD {_fmt_pct(base.get('maxdd'))}"
        )
        lines.append(
            f"  note={row['note']} | gate_note={best['gate_note']} | seg_pf=2020-2021:{_safe_float(m['seg_pf'].get('2020_2021')):.3f} / 2022-2023:{_safe_float(m['seg_pf'].get('2022_2023')):.3f} / 2024-2026:{_safe_float(m['seg_pf'].get('2024_2026')):.3f}"
        )
    lines.append("")
    lines.append("=== 结论 ===")
    lines.append("- 主线继续提频，但只走两条结构线：BNB 长腿回踩再入场；BTC 短腿冲击确认后入场。")
    lines.append("- neutral_revert 若继续最优，说明‘无重大消息时的插针/过冲回归’值得保留为长期结构门。")
    lines.append("- 若 impact_tiered / impact_tiered_flow 过线，才考虑把价格影响排序真正接到主线放行层。")
    lines.append(
        f"- 参考基线：pf={_safe_float(ref_metrics.get('pf')):.3f} | trades={int(ref_metrics.get('trades', 0))} | roll12_pf_floor={_safe_float(ref_metrics.get('rolling12_pf_floor')):.3f}。"
    )
    path_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    path_json.write_text(json.dumps({"rows": [_json_safe({**row, "best_gate": _strip_gate_payload(row)}) for row in rows], "reference": _json_safe(ref_metrics)}, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_branch(path_txt: Path, path_json: Path, rows: list[dict[str, Any]]) -> None:
    lines: list[str] = []
    lines.append("Stage65 ETH / SOL 价格影响双轨")
    lines.append("核心原则：ETH / SOL 都保留多空；不只调阈值，而是看 long / short / dual 在价格影响门下是否真变强")
    lines.append("")
    lines.append("=== 候选结果 ===")
    for row in rows:
        best = row["best_gate"]
        m = best["metrics"]
        mm = m.get("monthly", {}) or {}
        lines.append(
            f"- {str(row['symbol']).upper()} | family={row['family']} | {row['name']}: best_gate={best['gate_name']} ({best['gate']}) | trades={m['trades']} | pf={_safe_float(m['pf']):.3f} | ret={_fmt_pct(m['ret'])} | maxDD={_fmt_pct(m['maxdd'])} | months>=20%={mm.get('months_ge_20', 0)} | p75_month={_fmt_pct(mm.get('monthly_p75', 0.0))} | score={best['score']:+.2f}"
        )
        base = row.get("base_metrics", {})
        lines.append(
            f"  base=trades {base.get('trades', 0)} / pf {_safe_float(base.get('pf')):.3f} / ret {_fmt_pct(base.get('ret'))} / maxDD {_fmt_pct(base.get('maxdd'))}"
        )
        lines.append(f"  note={row['note']} | gate_note={best['gate_note']}")
    lines.append("")
    lines.append("=== 结论 ===")
    lines.append("- 分支继续广角，不预设 SOL 只能 long，也不预设 ETH 差。")
    lines.append("- 本轮重点看：SOL short 是否能在价格影响门下把回撤压住；ETH short 是否能进一步稳住质量。")
    lines.append("- 若 dual 仍明显弱于单腿，就继续先把 single-leg 做强，再考虑联动。")
    path_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    path_json.write_text(json.dumps({"rows": [_json_safe({**row, "best_gate": _strip_gate_payload(row)}) for row in rows]}, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage65 price impact frontier lab")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    cfg = read_config(root / "config.yml")
    initial_equity = float(cfg.get("portfolio", {}).get("initial_equity", 100000.0))
    data = s46._load_portfolio_data(root, cfg)

    main_rows = [_run_mainline(root, cfg, data, item, initial_equity) for item in _mainline_items()]
    ref_row = next((r for r in main_rows if r["name"] == "combo_sr_soft_adx26_cd6_lb24_zone028_ref"), main_rows[0])
    ref_metrics = ref_row.get("base_metrics", {})
    for row in main_rows:
        row["best_gate"] = _pick_best_gate(row["gate_rows"], _main_score, _main_gate_label, ref_metrics)
    main_rows.sort(key=lambda r: float(r["best_gate"]["score"]), reverse=True)

    branch_rows = [_run_branch(root, cfg, item, initial_equity) for item in _branch_items()]
    for row in branch_rows:
        row["best_gate"] = _pick_best_gate(row["gate_rows"], _branch_score, _branch_gate_label)
    branch_rows.sort(key=lambda r: float(r["best_gate"]["score"]), reverse=True)

    reports_raw = root / "reports" / "research_raw"
    reports_raw.mkdir(parents=True, exist_ok=True)
    _write_mainline(reports_raw / "stage65_mainline_impact_latest.txt", reports_raw / "stage65_mainline_impact_latest.json", main_rows, ref_metrics)
    _write_branch(reports_raw / "stage65_branch_impact_latest.txt", reports_raw / "stage65_branch_impact_latest.json", branch_rows)
    print(reports_raw / "stage65_mainline_impact_latest.txt")
    print(reports_raw / "stage65_branch_impact_latest.txt")


if __name__ == "__main__":
    main()
