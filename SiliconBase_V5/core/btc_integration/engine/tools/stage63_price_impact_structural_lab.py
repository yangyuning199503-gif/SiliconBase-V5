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
    from tools import stage55_broad_dual_track as s55
    from tools import stage59_structural_lab as s59
except Exception as exc:
    raise SystemExit("缺少 stage46/stage55/stage59 模块，请先保留此前补丁。") from exc


# -----------------------------
# Small helpers
# -----------------------------

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


# -----------------------------
# Candidate maps
# -----------------------------

def _mainline_items() -> list[dict[str, Any]]:
    return [
        {
            "name": "combo_sr_soft_adx26_cd6_lb24_zone028_ref",
            "note": "主线稳健基准：先保住 PF / roll floor，再靠结构门控提频",
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
            "note": "主线激进一号：频率更高，但必须叠加结构确认",
            "mods": {
                **s46.REF_MAIN_MODS,
                "sr_entries.adx_max": 28.0,
                "sr_entries.cooldown_bars": 6,
                "sr_entries.lookback_4h": 24,
                "sr_entries.zone_atr_mult": 0.28,
            },
        },
        {
            "name": "combo_sr_soft_adx28_cd5_lb22_zone027",
            "note": "更快的二次入场 / 回踩再入场边界，验证 220~260 笔区间",
            "mods": {
                **s46.REF_MAIN_MODS,
                "sr_entries.adx_max": 28.0,
                "sr_entries.cooldown_bars": 5,
                "sr_entries.lookback_4h": 22,
                "sr_entries.zone_atr_mult": 0.27,
            },
        },
        {
            "name": "combo_sr_soft_adx32_cd5_lb20_zone025",
            "note": "更激进的前沿候选，只保留在结构门控之下验证",
            "mods": {
                **s46.REF_MAIN_MODS,
                "sr_entries.adx_max": 32.0,
                "sr_entries.cooldown_bars": 5,
                "sr_entries.lookback_4h": 20,
                "sr_entries.zone_atr_mult": 0.25,
            },
        },
        {
            "name": "combo_sr_soft_adx28_cd6_lb24_zone027_btcpull100",
            "note": "主线结构型放松：BNB 回踩区略放宽，但 BTC 短腿要求更完整回抽确认",
            "mods": {
                **s46.REF_MAIN_MODS,
                "sr_entries.adx_max": 28.0,
                "sr_entries.cooldown_bars": 6,
                "sr_entries.lookback_4h": 24,
                "sr_entries.zone_atr_mult": 0.27,
                "filters.btc_short_pullback_atr": 1.00,
            },
        },
    ]


def _branch_items() -> list[dict[str, Any]]:
    rows_by_name = {str(r.get("name")): copy.deepcopy(r) for r in s55._branch_candidates()}
    wanted = [
        "sol_long_core_adx28_cd6_lb22_zone027_s038",
        "sol_short_shock_lb16_adx22",
        "sol_fast_trend_lb16_shortonly",
        "sol_shortwave_smooth_longonly",
        "eth_long_core_adx26_cd6_lb24_zone028_s032",
        "eth_short_shock_lb16_adx24",
        "eth_fast_trend_lb16_longonly",
        "eth_fast_trend_shortonly",
        "eth_shortwave_longonly",
        "eth_shortwave_tight_shortonly",
    ]
    out: list[dict[str, Any]] = []
    for name in wanted:
        row = rows_by_name.get(name)
        if not row:
            continue
        fam = "mixed"
        n = name.lower()
        if "long" in n:
            fam = "long"
        elif "short" in n or "shock" in n:
            fam = "short"
        out.append(
            {
                "symbol": row.get("symbol"),
                "family": fam,
                "name": row.get("name"),
                "note": row.get("note", ""),
                "mods": copy.deepcopy(row.get("mods", {})),
            }
        )
    return out


# -----------------------------
# Gates: structural, not threshold-only
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
    neutral = _bool_col(df, "neutral_event", True)
    wick = _bool_col(df, "wick_revert_ok", False)
    spike = _bool_col(df, "spike_fade_ok", False)
    crowded_long = _bool_col(df, "risk_crowded_long", False)
    oi_high = _bool_col(df, "risk_oi_high", False)
    event_blocked = _bool_col(df, "event_blocked", False)

    long_ok = (side == "LONG") & neutral & (wick | spike) & ~crowded_long & ~oi_high
    short_neutral_ok = (side == "SHORT") & neutral & (wick | spike) & (crowded_long | oi_high)
    short_shock_ok = (side == "SHORT") & (~neutral | event_blocked) & (wick | spike) & (crowded_long | oi_high | event_blocked)
    return long_ok | short_neutral_ok | short_shock_ok


def _gate_impact_tiered_flow(df: pd.DataFrame) -> pd.Series:
    side = df.get("side", pd.Series(index=df.index, dtype=str)).astype(str).str.upper()
    flow_aligned = _bool_col(df, "flow_aligned", True)
    crowded_long = _bool_col(df, "risk_crowded_long", False)
    oi_high = _bool_col(df, "risk_oi_high", False)
    base = _gate_impact_tiered(df)
    long_guard = (side == "LONG") & ~crowded_long & ~oi_high
    short_guard = (side == "SHORT") & flow_aligned
    return base & (long_guard | short_guard)


GATES: list[tuple[str, Callable[[pd.DataFrame], pd.Series], str]] = [
    ("base_message_overlay", _gate_none, "只保留消息面 overlay，不加结构门"),
    ("neutral_revert", _gate_neutral_revert, "无重大消息时，只做插针/过冲回归确认"),
    ("impact_tiered", _gate_impact_tiered, "结构性放松，但要求：中性回归或冲击下的方向确认"),
    ("impact_tiered_flow", _gate_impact_tiered_flow, "结构性放松 + 拥挤/持仓方向配合，不再单纯降阈值"),
]


# -----------------------------
# Scoring / labels
# -----------------------------

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
    target_bonus = 24.0 if 205 <= trades <= 250 else (12.0 if trades >= 190 else 0.0)
    return float(
        trade_gain * 1.8
        + active_gain * 2.2
        + months20_gain * 3.2
        - pf_pen * 65.0
        - dd_pen * 155.0
        - ret_pen * 6.0
        - floor_pen * 25.0
        + target_bonus
        + _safe_float(metrics.get("rolling12_pf_floor")) * 18.0
    )



def _main_gate_label(metrics: dict[str, Any], ref: dict[str, Any]) -> str:
    if (
        int(metrics.get("trades", 0) or 0) >= int(ref.get("trades", 0) or 0)
        and _safe_float(metrics.get("pf")) >= max(2.05, _safe_float(ref.get("pf")) - 0.18)
        and _safe_float(metrics.get("ret")) >= _safe_float(ref.get("ret")) * 0.92
        and abs(_safe_float(metrics.get("maxdd"))) <= abs(_safe_float(ref.get("maxdd"))) + 0.05
        and _safe_float(metrics.get("rolling12_pf_floor")) >= max(0.74, _safe_float(ref.get("rolling12_pf_floor")) - 0.06)
    ):
        return "pass"
    if int(metrics.get("trades", 0) or 0) >= 190 and _safe_float(metrics.get("pf")) >= 1.95 and _safe_float(metrics.get("rolling12_pf_floor")) >= 0.72:
        return "hold"
    return "kill"



def _branch_score(metrics: dict[str, Any]) -> float:
    m = metrics.get("monthly", {}) or {}
    return float(
        _safe_float(metrics.get("pf")) * 90.0
        + _safe_float(metrics.get("ret")) * 60.0
        - abs(_safe_float(metrics.get("maxdd"))) * 75.0
        + min(int(metrics.get("trades", 0) or 0), 240) * 0.35
        + int(m.get("months_ge_20", 0) or 0) * 18.0
        + _safe_float(m.get("monthly_p75")) * 150.0
        + _safe_float(metrics.get("rolling12_pf_floor")) * 16.0
    )



def _branch_gate_label(metrics: dict[str, Any]) -> str:
    m = metrics.get("monthly", {}) or {}
    if (
        _safe_float(metrics.get("pf")) >= 1.20
        and _safe_float(metrics.get("ret")) > 0.0
        and abs(_safe_float(metrics.get("maxdd"))) <= 0.38
        and (int(m.get("months_ge_20", 0) or 0) >= 1 or _safe_float(m.get("monthly_p75")) >= 0.08)
    ):
        return "pass"
    if _safe_float(metrics.get("pf")) >= 1.05 and int(metrics.get("trades", 0) or 0) >= 18 and abs(_safe_float(metrics.get("maxdd"))) <= 0.48:
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


# -----------------------------
# Run helpers
# -----------------------------

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


# -----------------------------
# JSON helpers / writers
# -----------------------------

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
    lines.append("Stage63 主线价格影响 + 结构提频研究")
    lines.append("核心原则：不再单纯调阈值；放松标准必须叠加结构确认与价格影响门控")
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
    lines.append("- 主线提频继续，但只保留‘结构放松 + 额外确认条件’：neutral reversion / impact-tiered / flow-aligned。")
    lines.append("- 不再把提频理解成单纯降 ADX/cooldown；当前重点是：回踩再入场、无消息插针回归、冲击窗口下的方向确认。")
    lines.append(
        f"- 参考基线：pf={_safe_float(ref_metrics.get('pf')):.3f} | trades={int(ref_metrics.get('trades', 0))} | roll12_pf_floor={_safe_float(ref_metrics.get('rolling12_pf_floor')):.3f}。"
    )
    path_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    path_json.write_text(json.dumps({"rows": [_json_safe({**row, "best_gate": _strip_gate_payload(row)}) for row in rows], "reference": _json_safe(ref_metrics)}, ensure_ascii=False, indent=2), encoding="utf-8")



def _write_branch(path_txt: Path, path_json: Path, rows: list[dict[str, Any]]) -> None:
    lines: list[str] = []
    lines.append("Stage63 ETH / SOL 价格影响 + 广角分支")
    lines.append("核心原则：ETH / SOL 都保留多空；新增 impact-tiered 门控，验证‘无消息插针回归’与‘冲击窗口方向确认’")
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
    lines.append("- 分支继续做广角，不预设 SOL 只能 long，也不预设 ETH 弱。")
    lines.append("- 这轮优先比较三类结构：trend / shock / wick-reversion；并把价格影响门控放到策略层，而不是只改阈值。")
    path_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    path_json.write_text(json.dumps({"rows": [_json_safe({**row, "best_gate": _strip_gate_payload(row)}) for row in rows]}, ensure_ascii=False, indent=2), encoding="utf-8")


# -----------------------------
# Main
# -----------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Stage63 price-impact structural lab")
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
    _write_mainline(reports_raw / "stage63_mainline_price_impact_latest.txt", reports_raw / "stage63_mainline_price_impact_latest.json", main_rows, ref_metrics)
    _write_branch(reports_raw / "stage63_branch_price_impact_latest.txt", reports_raw / "stage63_branch_price_impact_latest.json", branch_rows)
    print(reports_raw / "stage63_mainline_price_impact_latest.txt")
    print(reports_raw / "stage63_branch_price_impact_latest.txt")


if __name__ == "__main__":
    main()
