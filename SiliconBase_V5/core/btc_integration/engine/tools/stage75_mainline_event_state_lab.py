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


try:
    from tools import research_config_baseline as rcb
    from tools import stage46_aggressive_lab as s46
    from tools import stage55_broad_dual_track as s55
    from tools import stage59_structural_lab as s59
    from tools import stage64_relevance_hybrid_lab as s64
except Exception as exc:
    raise SystemExit("缺少 stage46/stage55/stage59/stage64 模块，请先保留此前补丁。") from exc


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
    out: dict[str, dict[str, Any]] = {}

    def add(name: str, note: str, mods: dict[str, Any]) -> None:
        out[name] = {"name": name, "note": note, "mods": copy.deepcopy(mods)}

    s64_map = {str(x.get("name")): x for x in s64._mainline_items()}
    for name in [
        "combo_sr_soft_adx26_cd6_lb24_zone028_ref",
        "combo_sr_soft_adx28_cd6_lb24_zone028",
        "combo_sr_soft_adx30_cd6_lb22_zone026",
        "combo_sr_soft_adx30_cd5_lb22_zone026",
        "combo_sr_soft_adx32_cd5_lb20_zone025",
    ]:
        item = s64_map.get(name)
        if item:
            add(name, str(item.get("note", "")), item.get("mods", {}))

    base_26 = s64_map.get("combo_sr_soft_adx26_cd6_lb24_zone028_ref")
    if base_26:
        mods = copy.deepcopy(base_26.get("mods", {}))
        mods["strategy_params.cooldown_bars"] = 5
        add(
            "combo_sr_soft_adx26_cd5_lb24_zone028",
            "同族快版：保持 lb24/zone028，不换结构，只把 cooldown 从 6 压到 5，看能否小幅提频而不明显伤 PF。",
            mods,
        )

    base_28 = s64_map.get("combo_sr_soft_adx28_cd6_lb24_zone028")
    if base_28:
        mods = copy.deepcopy(base_28.get("mods", {}))
        mods["strategy_params.cooldown_bars"] = 5
        add(
            "combo_sr_soft_adx28_cd5_lb24_zone028",
            "同参数不同标准：保持 lb24/zone028，只压 cooldown，和 adx28 组合做更激进但仍可解释的提频实验。",
            mods,
        )

    s55_map = {str(x.get("name")): x for x in s55._mainline_items()}
    for name in [
        "mainline_live_base",
        "mainline_split_adx26_cd6_lb24_zone028",
        "mainline_split_adx28_cd6_lb24_zone028",
        "mainline_split_adx28_cd5_lb22_zone027",
    ]:
        item = s55_map.get(name)
        if item:
            add(name, str(item.get("note", "")), item.get("mods", {}))

    add(
        "mainline_core_satellite_event30",
        "核心不砍，单独把事件跟随当 satellite，不再强行靠一套阈值把频次顶上去",
        {
            **copy.deepcopy(s46.REF_MAIN_MODS),
            "strategy_params.cooldown_bars": 6,
            "strategy_params.long_symbols": ["bnb"],
            "strategy_params.short_symbols": ["btc"],
            "filters.adx_floor": 28,
            "filters.btc_adx_floor": 28,
            "filters.btc_short_pullback_atr": 0.98,
            "filters.btc_short_macro_tf": "4h",
            "sr_entries.enabled": True,
            "sr_entries.symbols": ["bnb"],
            "sr_entries.lookback_4h": 22,
            "sr_entries.zone_atr_mult": 0.27,
            "sr_entries.use_adx_filter": True,
            "sr_entries.adx_min": 0.0,
            "sr_entries.adx_max": 30.0,
            "sr_entries.stake_scale": 0.17,
            "sr_entries.cooldown_bars": 6,
            "sr_entries.require_compress_ok": True,
        },
    )
    return list(out.values())

DEFAULT_CANDIDATE_NAMES = [
    "mainline_live_base",
    "combo_sr_soft_adx26_cd6_lb24_zone028_ref",
    "combo_sr_soft_adx28_cd6_lb24_zone028",
    "mainline_core_satellite_event30",
    "mainline_split_adx26_cd6_lb24_zone028",
]


def _resolve_candidate_names(raw: str, default: list[str]) -> list[str]:
    items = [x.strip() for x in str(raw or "").split(",") if x.strip()]
    return items or list(default)


# -----------------------------
# Event-state gates
# -----------------------------

def _gate_none(df: pd.DataFrame) -> pd.Series:
    return pd.Series(True, index=df.index)


def _gate_neutral_revert(df: pd.DataFrame) -> pd.Series:
    neutral = _bool_col(df, "neutral_event", True)
    wick = _bool_col(df, "wick_revert_ok", False)
    spike = _bool_col(df, "spike_fade_ok", False)
    return neutral & (wick | spike)


def _gate_event_release_follow(df: pd.DataFrame) -> pd.Series:
    side = df.get("side", pd.Series(index=df.index, dtype=str)).astype(str).str.upper()
    neutral = _bool_col(df, "neutral_event", True)
    blocked = _bool_col(df, "event_blocked", False)
    flow = _bool_col(df, "flow_aligned", True)
    crowded = _bool_col(df, "risk_crowded_long", False)
    oi_high = _bool_col(df, "risk_oi_high", False)
    range_rel = _num_col(df, "range_rel", 1.0)
    vol_rel = _num_col(df, "vol_rel", 1.0)
    bar_ret = _num_col(df, "bar_ret", 0.0)
    close_loc = _num_col(df, "close_loc", 0.5)

    identified = (~neutral) | blocked
    impulse = (range_rel >= 1.10) | (vol_rel >= 1.08) | (bar_ret.abs() >= 0.007)
    long_release = (side == "LONG") & identified & flow & ~crowded & ~oi_high & impulse & (close_loc >= 0.60) & (bar_ret >= 0.003)
    short_release = (side == "SHORT") & identified & flow & (crowded | oi_high | blocked) & impulse & (close_loc <= 0.40) & (bar_ret <= -0.003)
    return long_release | short_release


def _gate_event_drift_confirm(df: pd.DataFrame) -> pd.Series:
    side = df.get("side", pd.Series(index=df.index, dtype=str)).astype(str).str.upper()
    neutral = _bool_col(df, "neutral_event", True)
    blocked = _bool_col(df, "event_blocked", False)
    flow = _bool_col(df, "flow_aligned", True)
    crowded = _bool_col(df, "risk_crowded_long", False)
    oi_high = _bool_col(df, "risk_oi_high", False)
    range_rel = _num_col(df, "range_rel", 1.0)
    vol_rel = _num_col(df, "vol_rel", 1.0)
    bar_ret = _num_col(df, "bar_ret", 0.0)
    close_loc = _num_col(df, "close_loc", 0.5)

    identified = (~neutral) | blocked
    long_drift = (side == "LONG") & identified & flow & ~crowded & ~oi_high & (range_rel >= 0.95) & (vol_rel >= 1.00) & (close_loc >= 0.58) & (bar_ret >= 0.001)
    short_drift = (side == "SHORT") & identified & flow & (crowded | oi_high | blocked) & (range_rel >= 0.95) & (vol_rel >= 1.00) & (close_loc <= 0.42) & (bar_ret <= -0.001)
    return long_drift | short_drift


def _gate_event_state_mix(df: pd.DataFrame) -> pd.Series:
    return _gate_neutral_revert(df) | _gate_event_release_follow(df) | _gate_event_drift_confirm(df)


def _gate_event_state_guarded(df: pd.DataFrame) -> pd.Series:
    side = df.get("side", pd.Series(index=df.index, dtype=str)).astype(str).str.upper()
    neutral = _bool_col(df, "neutral_event", True)
    flow = _bool_col(df, "flow_aligned", True)
    crowded = _bool_col(df, "risk_crowded_long", False)
    oi_high = _bool_col(df, "risk_oi_high", False)
    wick = _bool_col(df, "wick_revert_ok", False)
    spike = _bool_col(df, "spike_fade_ok", False)
    range_rel = _num_col(df, "range_rel", 1.0)
    vol_rel = _num_col(df, "vol_rel", 1.0)
    bar_ret = _num_col(df, "bar_ret", 0.0)
    close_loc = _num_col(df, "close_loc", 0.5)
    blocked = _bool_col(df, "event_blocked", False)
    identified = (~neutral) | blocked

    long_neutral = (side == "LONG") & neutral & flow & (wick | spike) & (range_rel >= 1.00)
    short_neutral = (side == "SHORT") & neutral & flow & (wick | spike) & (crowded | oi_high) & (range_rel >= 1.00)
    long_release = (side == "LONG") & identified & flow & ~crowded & ~oi_high & (range_rel >= 1.08) & (vol_rel >= 1.04) & (close_loc >= 0.62) & (bar_ret >= 0.004)
    short_release = (side == "SHORT") & identified & flow & (crowded | oi_high | blocked) & (range_rel >= 1.08) & (vol_rel >= 1.04) & (close_loc <= 0.38) & (bar_ret <= -0.004)
    return long_neutral | short_neutral | long_release | short_release


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
    ("base_message_overlay", _gate_none, "只保留消息面 overlay，不加事件状态机"),
    ("neutral_revert", _gate_neutral_revert, "无重大消息时，只做插针/过冲回归"),
    ("impact_tiered", _gate_impact_tiered, "先激进开方向，再用流向/拥挤度/波动强度筛掉垃圾机会"),
    ("impact_tiered_flow", _gate_impact_tiered_flow, "先放方向，再叠加 flow + 波动强度 + 结构确认"),
    ("shock_confirm", _gate_shock_confirm, "冲击窗口下先抢方向，再靠 shock/flow/crowding 做保守确认"),
    ("event_release_follow", _gate_event_release_follow, "事件释放窗口：只做有流向/拥挤度/收盘位置确认的跟随"),
    ("event_drift_confirm", _gate_event_drift_confirm, "事件扩散/衰减窗口：保留顺着消息与成交结构的延续"),
    ("event_state_mix", _gate_event_state_mix, "中性冲击做回归；已识别事件做跟随/漂移确认，不再一刀切 veto"),
    ("event_state_guarded", _gate_event_state_guarded, "更保守的事件状态机：所有状态都要结构或衍生品确认"),
]


def _band_bonus(trades: int) -> float:
    if 180 <= trades < 220:
        return 8.0
    if 220 <= trades < 260:
        return 16.0
    if 260 <= trades <= 320:
        return 20.0
    if 320 < trades <= 420:
        return 12.0
    return 0.0


def _main_score(metrics: dict[str, Any], ref: dict[str, Any]) -> float:
    m = metrics.get("monthly", {}) or {}
    trades = int(metrics.get("trades", 0) or 0)
    pf = _safe_float(metrics.get("pf"))
    ret = _safe_float(metrics.get("ret"))
    dd = abs(_safe_float(metrics.get("maxdd")))
    floor = _safe_float(metrics.get("rolling12_pf_floor"))
    p75 = _safe_float(m.get("monthly_p75"))
    months20 = int(m.get("months_ge_20", 0) or 0)
    seg_floor = min(float(v) for v in (metrics.get("seg_pf", {}) or {}).values()) if (metrics.get("seg_pf", {}) or {}) else 0.0

    pf_pen = max(0.0, _safe_float(ref.get("pf")) - pf) * 22.0
    dd_pen = max(0.0, dd - abs(_safe_float(ref.get("maxdd")))) * 42.0
    ret_pen = max(0.0, _safe_float(ref.get("ret")) - ret) * 3.2

    return float(
        pf * 86.0
        + ret * 48.0
        - dd * 78.0
        + min(trades, 420) * 0.24
        + months20 * 4.0
        + p75 * 145.0
        + floor * 18.0
        + seg_floor * 14.0
        + _band_bonus(trades)
        - pf_pen
        - dd_pen
        - ret_pen
    )


def _main_gate_label(metrics: dict[str, Any], ref: dict[str, Any]) -> str:
    trades = int(metrics.get("trades", 0) or 0)
    pf = _safe_float(metrics.get("pf"))
    dd = abs(_safe_float(metrics.get("maxdd")))
    floor = _safe_float(metrics.get("rolling12_pf_floor"))
    if trades >= 170 and pf >= max(1.85, _safe_float(ref.get("pf")) - 0.42) and dd <= 0.48 and floor >= 0.58:
        return "pass"
    if trades >= 130 and pf >= 1.45 and dd <= 0.62 and floor >= 0.42:
        return "hold"
    return "kill"


def _pick_best_gate(
    gate_rows: list[dict[str, Any]],
    score_fn: Callable[..., float],
    label_fn: Callable[..., str],
    ref_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
    lines.append("Stage75 主线事件状态机前沿")
    lines.append("核心原则：主线不再硬拧频次；保留 core，再让事件/信息驱动的 satellite 去补机会。")
    lines.append("")
    lines.append("=== 候选结果 ===")
    for row in rows:
        best = row["best_gate"]
        m = best["metrics"]
        mm = m.get("monthly", {}) or {}
        lines.append(
            f"- {row['name']}: best_gate={best['gate_name']} ({best['gate']}) | trades={m['trades']} | win_rate={_fmt_pct(m.get('win_rate', 0.0))} | pf={_safe_float(m['pf']):.3f} | ret={_fmt_pct(m['ret'])} | maxDD={_fmt_pct(m['maxdd'])} | months>=20%={mm.get('months_ge_20', 0)} | p75_month={_fmt_pct(mm.get('monthly_p75', 0.0))} | score={best['score']:+.2f}"
        )
        base = row.get("base_metrics", {})
        lines.append(
            f"  base=trades {base.get('trades', 0)} / win_rate {_fmt_pct(base.get('win_rate', 0.0))} / pf {_safe_float(base.get('pf')):.3f} / ret {_fmt_pct(base.get('ret'))} / maxDD {_fmt_pct(base.get('maxdd'))}"
        )
        lines.append(
            f"  note={row['note']} | gate_note={best['gate_note']} | roll12_pf_floor={_safe_float(m.get('rolling12_pf_floor')):.3f}"
        )
    lines.append("")
    lines.append("=== 结论 ===")
    lines.append("- 不是再把同一套参数一起放宽，而是把‘中性冲击回归’和‘事件释放后跟随’拆开。")
    lines.append("- 如果 event_release_follow / event_state_mix 明显优于 neutral_revert，说明消息面应该从 veto 升级成放行层。")
    lines.append("- 如果 split 线仍塌，说明主线高频机会要靠 satellite 引擎补，而不是继续硬拉主引擎。")
    lines.append(
        f"- 参考基线：trades={int(ref_metrics.get('trades', 0))} | win_rate={_fmt_pct(ref_metrics.get('win_rate', 0.0))} | pf={_safe_float(ref_metrics.get('pf')):.3f} | ret={_fmt_pct(ref_metrics.get('ret'))} | maxDD={_fmt_pct(ref_metrics.get('maxdd'))}。"
    )
    path_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    path_json.write_text(
        json.dumps(
            {
                "rows": [_json_safe({**row, "best_gate": _strip_gate_payload(row)}) for row in rows],
                "reference": _json_safe(ref_metrics),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage75 mainline event-state frontier")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--candidate-names", default="", help="逗号分隔；为空则用内置短名单")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    cfg = rcb.load_research_base_config(root)
    initial_equity = float(cfg.get("portfolio", {}).get("initial_equity", 100000.0))
    data = s46._load_portfolio_data(root, cfg)

    candidate_order = _resolve_candidate_names(args.candidate_names, DEFAULT_CANDIDATE_NAMES)
    items_map = {str(x.get("name")): x for x in _mainline_items()}
    chosen_items = [items_map[name] for name in candidate_order if name in items_map]
    if not chosen_items:
        raise SystemExit("未找到主线候选，无法运行 stage75。")

    rows = [_run_mainline(root, cfg, data, item, initial_equity) for item in chosen_items]
    ref_row = next((r for r in rows if r["name"] == "combo_sr_soft_adx26_cd6_lb24_zone028_ref"), rows[0])
    ref_metrics = ref_row.get("base_metrics", {})
    for row in rows:
        row["best_gate"] = _pick_best_gate(row["gate_rows"], _main_score, _main_gate_label, ref_metrics)
    rows.sort(key=lambda r: float(r["best_gate"]["score"]), reverse=True)

    reports_raw = root / "reports" / "research_raw"
    reports_raw.mkdir(parents=True, exist_ok=True)
    _write_mainline(
        reports_raw / "stage75_mainline_event_state_latest.txt",
        reports_raw / "stage75_mainline_event_state_latest.json",
        rows,
        ref_metrics,
    )
    print(reports_raw / "stage75_mainline_event_state_latest.txt")
    print(reports_raw / "stage75_mainline_event_state_latest.json")


if __name__ == "__main__":
    main()
