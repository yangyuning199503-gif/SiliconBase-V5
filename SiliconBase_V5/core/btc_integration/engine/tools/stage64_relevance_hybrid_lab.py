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
except Exception as exc:
    raise SystemExit("缺少 stage46/stage55/stage59/stage63 模块，请先保留此前补丁。") from exc


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


def _mainline_items() -> list[dict[str, Any]]:
    return [
        {
            "name": "combo_sr_soft_adx26_cd6_lb24_zone028_ref",
            "note": "稳健参考，不停提频，但先保住分段质量",
            "mods": {
                **s46.REF_MAIN_MODS,
                "sr_entries.adx_max": 26.0,
                "sr_entries.cooldown_bars": 6,
                "sr_entries.lookback_4h": 24,
                "sr_entries.zone_atr_mult": 0.28,
            },
        },
        {
            "name": "combo_sr_soft_adx28_cd6_lb24_zone028",
            "note": "激进主候选，当前已证明 210+ 笔可行",
            "mods": {
                **s46.REF_MAIN_MODS,
                "sr_entries.adx_max": 28.0,
                "sr_entries.cooldown_bars": 6,
                "sr_entries.lookback_4h": 24,
                "sr_entries.zone_atr_mult": 0.28,
            },
        },
        {
            "name": "combo_sr_soft_adx30_cd6_lb22_zone026",
            "note": "继续提频，但不用纯阈值，交给结构门做二次确认",
            "mods": {
                **s46.REF_MAIN_MODS,
                "sr_entries.adx_max": 30.0,
                "sr_entries.cooldown_bars": 6,
                "sr_entries.lookback_4h": 22,
                "sr_entries.zone_atr_mult": 0.26,
            },
        },
        {
            "name": "combo_sr_soft_adx30_cd5_lb22_zone026",
            "note": "前沿快版：冲 220~260 笔，但必须过结构门和分段门",
            "mods": {
                **s46.REF_MAIN_MODS,
                "sr_entries.adx_max": 30.0,
                "sr_entries.cooldown_bars": 5,
                "sr_entries.lookback_4h": 22,
                "sr_entries.zone_atr_mult": 0.26,
            },
        },
        {
            "name": "combo_sr_soft_adx32_cd5_lb20_zone025",
            "note": "最激进前沿，只允许留在研究层",
            "mods": {
                **s46.REF_MAIN_MODS,
                "sr_entries.adx_max": 32.0,
                "sr_entries.cooldown_bars": 5,
                "sr_entries.lookback_4h": 20,
                "sr_entries.zone_atr_mult": 0.25,
            },
        },
    ]


def _branch_items() -> list[dict[str, Any]]:
    item_map = {item["name"]: copy.deepcopy(item) for item in s55._branch_candidates()}
    wanted = [
        "sol_long_core_adx28_cd6_lb22_zone027_s038",
        "sol_fast_trend_lb16_shortonly",
        "sol_short_shock_lb16_adx22",
        "sol_dual_guarded_core_plus_shock",
        "eth_long_core_adx26_cd6_lb24_zone028_s032",
        "eth_shortwave_tight_shortonly",
        "eth_short_shock_lb16_adx24",
        "eth_dual_guarded_core_plus_shock",
    ]
    out: list[dict[str, Any]] = []
    for name in wanted:
        item = item_map.get(name)
        if not item:
            continue
        fam = "mixed"
        low = name.lower()
        if "dual" in low:
            fam = "dual"
        elif "long" in low:
            fam = "long"
        elif "short" in low or "shock" in low:
            fam = "short"
        out.append(
            {
                "symbol": item.get("symbol"),
                "family": fam,
                "name": item.get("name"),
                "note": item.get("note", ""),
                "mods": copy.deepcopy(item.get("mods", {})),
            }
        )
    return out


# structural gates

def _gate_none(df: pd.DataFrame) -> pd.Series:
    return pd.Series(True, index=df.index)


def _gate_neutral_revert(df: pd.DataFrame) -> pd.Series:
    neutral = _bool_col(df, "neutral_event", True)
    wick = _bool_col(df, "wick_revert_ok", False)
    spike = _bool_col(df, "spike_fade_ok", False)
    return neutral & (wick | spike)


def _gate_hybrid_soft(df: pd.DataFrame) -> pd.Series:
    side = df.get("side", pd.Series(index=df.index, dtype=str)).astype(str).str.upper()
    neutral = _bool_col(df, "neutral_event", True)
    wick = _bool_col(df, "wick_revert_ok", False)
    spike = _bool_col(df, "spike_fade_ok", False)
    flow_aligned = _bool_col(df, "flow_aligned", True)
    crowded_long = _bool_col(df, "risk_crowded_long", False)
    oi_high = _bool_col(df, "risk_oi_high", False)
    event_blocked = _bool_col(df, "event_blocked", False)

    long_neutral = (side == "LONG") & neutral & (wick | spike)
    long_event = (side == "LONG") & (~neutral) & flow_aligned & ~crowded_long & ~oi_high

    short_neutral = (side == "SHORT") & neutral & (wick | spike) & (crowded_long | oi_high | flow_aligned)
    short_event = (side == "SHORT") & ((~neutral) | event_blocked) & flow_aligned & (crowded_long | oi_high | event_blocked)
    return long_neutral | long_event | short_neutral | short_event


def _gate_shock_confirm(df: pd.DataFrame) -> pd.Series:
    side = df.get("side", pd.Series(index=df.index, dtype=str)).astype(str).str.upper()
    flow_aligned = _bool_col(df, "flow_aligned", True)
    crowded_long = _bool_col(df, "risk_crowded_long", False)
    oi_high = _bool_col(df, "risk_oi_high", False)
    neutral = _bool_col(df, "neutral_event", True)
    event_blocked = _bool_col(df, "event_blocked", False)
    wick = _bool_col(df, "wick_revert_ok", False)
    spike = _bool_col(df, "spike_fade_ok", False)

    long_ok = (side == "LONG") & (~neutral) & flow_aligned & ~crowded_long & ~oi_high
    short_ok = (side == "SHORT") & (((~neutral) | event_blocked) & flow_aligned & (crowded_long | oi_high | event_blocked))
    revert_short = (side == "SHORT") & neutral & (wick | spike) & (crowded_long | oi_high) & flow_aligned
    return long_ok | short_ok | revert_short


GATES: list[tuple[str, Callable[[pd.DataFrame], pd.Series], str]] = [
    ("base_message_overlay", _gate_none, "只保留消息面 overlay，不加结构门"),
    ("neutral_revert", _gate_neutral_revert, "无重大消息时，只做插针/过冲回归确认"),
    ("hybrid_soft", _gate_hybrid_soft, "中性时做回归；事件时要流向/拥挤度确认，不再只是降阈值"),
    ("shock_confirm", _gate_shock_confirm, "冲击窗口下做方向确认；空腿必须有 flow / crowding 支持"),
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
    target_bonus = 28.0 if 220 <= trades <= 260 else (16.0 if trades >= 205 else 0.0)
    return float(
        trade_gain * 1.9
        + active_gain * 2.4
        + months20_gain * 3.4
        - pf_pen * 64.0
        - dd_pen * 160.0
        - ret_pen * 6.0
        - floor_pen * 28.0
        + target_bonus
        + _safe_float(metrics.get("rolling12_pf_floor")) * 18.0
        + seg_floor * 16.0
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
        - abs(_safe_float(metrics.get("maxdd"))) * 78.0
        + min(int(metrics.get("trades", 0) or 0), 240) * 0.38
        + int(m.get("months_ge_20", 0) or 0) * 20.0
        + _safe_float(m.get("monthly_p75")) * 160.0
        + _safe_float(metrics.get("rolling12_pf_floor")) * 18.0
    )


def _branch_gate_label(metrics: dict[str, Any]) -> str:
    m = metrics.get("monthly", {}) or {}
    if (
        _safe_float(metrics.get("pf")) >= 1.15
        and _safe_float(metrics.get("ret")) > 0.0
        and abs(_safe_float(metrics.get("maxdd"))) <= 0.45
        and (int(m.get("months_ge_20", 0) or 0) >= 1 or _safe_float(m.get("monthly_p75")) >= 0.07)
    ):
        return "pass"
    if _safe_float(metrics.get("pf")) >= 1.00 and int(metrics.get("trades", 0) or 0) >= 18 and abs(_safe_float(metrics.get("maxdd"))) <= 0.55:
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
    lines.append("Stage64 主线相关性 + 结构混合提频")
    lines.append("核心原则：主线提频不停，但只接受‘更高频 + 额外确认条件’；不做纯阈值松绑")
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
    lines.append("- 主线继续提频，但只走‘回踩再入场 / 无消息插针回归 / 冲击窗口方向确认’三类结构门。")
    lines.append("- 本轮重点比较 hybrid_soft 与 shock_confirm；如果只是降 ADX/cooldown 而无结构确认，一律不升。")
    lines.append(
        f"- 参考基线：pf={_safe_float(ref_metrics.get('pf')):.3f} | trades={int(ref_metrics.get('trades', 0))} | roll12_pf_floor={_safe_float(ref_metrics.get('rolling12_pf_floor')):.3f}。"
    )
    path_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    path_json.write_text(json.dumps({"rows": [_json_safe({**row, "best_gate": _strip_gate_payload(row)}) for row in rows], "reference": _json_safe(ref_metrics)}, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_branch(path_txt: Path, path_json: Path, rows: list[dict[str, Any]]) -> None:
    lines: list[str] = []
    lines.append("Stage64 ETH / SOL 广角双轨")
    lines.append("核心原则：ETH / SOL 都保留多空；不只调阈值，而是比较 long / short / dual 在结构门下的真实质量")
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
    lines.append("- 分支继续广角，不预设 SOL 只能 long，也不预设 ETH 差；重点看 dual 是否真的比单腿更稳。")
    lines.append("- 本轮优先比较：SOL dual vs short-only；ETH dual vs short-only。")
    path_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    path_json.write_text(json.dumps({"rows": [_json_safe({**row, "best_gate": _strip_gate_payload(row)}) for row in rows]}, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage64 relevance hybrid lab")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    cfg = rcb.load_research_base_config(root)
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
    _write_mainline(reports_raw / "stage64_mainline_hybrid_latest.txt", reports_raw / "stage64_mainline_hybrid_latest.json", main_rows, ref_metrics)
    _write_branch(reports_raw / "stage64_branch_hybrid_latest.txt", reports_raw / "stage64_branch_hybrid_latest.json", branch_rows)
    print(reports_raw / "stage64_mainline_hybrid_latest.txt")
    print(reports_raw / "stage64_branch_hybrid_latest.txt")


if __name__ == "__main__":
    main()
