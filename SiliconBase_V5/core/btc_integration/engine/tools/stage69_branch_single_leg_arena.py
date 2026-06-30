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

from src.backtest.io import read_config

try:
    from tools import stage55_broad_dual_track as s55
    from tools import stage65_price_impact_frontier_lab as s65
except Exception as exc:
    raise SystemExit("缺少 stage55/stage65 模块，请先保留此前补丁。") from exc


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


def _detect_family(item_name: str, mods: dict[str, Any]) -> str:
    name = item_name.lower()
    if "dual" in name:
        return "dual"
    longs = mods.get("strategy_params.long_symbols") or []
    shorts = mods.get("strategy_params.short_symbols") or []
    if longs and not shorts:
        return "long"
    if shorts and not longs:
        return "short"
    if "long" in name:
        return "long"
    if "short" in name or "shock" in name:
        return "short"
    return "mixed"


def _base_item_map() -> dict[str, dict[str, Any]]:
    return {item["name"]: copy.deepcopy(item) for item in s55._branch_candidates()}


def _make_variant(base: dict[str, Any], *, name: str, note: str, patch: dict[str, Any]) -> dict[str, Any]:
    row = copy.deepcopy(base)
    row["name"] = name
    row["note"] = note
    mods = copy.deepcopy(row.get("mods", {}))
    # IMPORTANT: stage59/stage65 expect FLAT dotted keys, not nested dicts.
    # Previous patch mistakenly converted part of mods to nested dicts,
    # which overwrote whole config sections and caused stage69 crash.
    for k, v in patch.items():
        mods[k] = v
    row["mods"] = mods
    row["family"] = _detect_family(name, mods)
    return row


def _candidate_items() -> list[dict[str, Any]]:
    item_map = _base_item_map()
    wanted = [
        "sol_long_core_adx28_cd6_lb22_zone027_s038",
        "sol_shortwave_smooth_longonly",
        "sol_fast_trend_lb16_shortonly",
        "sol_short_shock_lb16_adx22",
        "eth_shortwave_tight_shortonly",
        "eth_fast_trend_shortonly",
        "eth_long_core_adx26_cd6_lb24_zone028_s032",
        "eth_shortwave_longonly",
        "eth_short_shock_lb16_adx24",
    ]
    rows: list[dict[str, Any]] = []
    for name in wanted:
        item = item_map.get(name)
        if not item:
            continue
        item = copy.deepcopy(item)
        item["family"] = _detect_family(item["name"], item.get("mods", {}))
        rows.append(item)

    if "eth_long_core_adx26_cd6_lb24_zone028_s032" in item_map:
        rows.append(
            _make_variant(
                item_map["eth_long_core_adx26_cd6_lb24_zone028_s032"],
                name="eth_long_core_relaxed_adx30_cd5_lb22_zone030_s036",
                note="ETH 长腿放宽版：先扩结构空间，再用消息/结构门控过滤",
                patch={
                    "strategy_params.cooldown_bars": 5,
                    "sr_entries.cooldown_bars": 5,
                    "sr_entries.lookback_4h": 22,
                    "sr_entries.zone_atr_mult": 0.30,
                    "sr_entries.adx_max": 30.0,
                    "sr_entries.stake_scale": 0.36,
                },
            )
        )
    if "eth_shortwave_longonly" in item_map:
        rows.append(
            _make_variant(
                item_map["eth_shortwave_longonly"],
                name="eth_shortwave_long_relaxed_z032_s038",
                note="ETH 回踩长腿放宽版：扩大 zone/放松 cooldown，不预设 ETH 不能做多短波",
                patch={
                    "strategy_params.cooldown_bars": 6,
                    "sr_entries.cooldown_bars": 6,
                    "sr_entries.lookback_4h": 22,
                    "sr_entries.zone_atr_mult": 0.32,
                    "sr_entries.adx_max": 28.0,
                    "sr_entries.stake_scale": 0.38,
                },
            )
        )
    if "sol_fast_trend_lb16_shortonly" in item_map:
        rows.append(
            _make_variant(
                item_map["sol_fast_trend_lb16_shortonly"],
                name="sol_fast_trend_short_relaxed_lb14_adx20",
                note="SOL 趋势短腿放宽版：缩短 breakout lookback，先拓结构，不先砍",
                patch={
                    "strategy_params.breakout_lookback": 14,
                    "strategy_params.breakout_atr_buffer": 0.45,
                    "strategy_params.cooldown_bars": 5,
                    "filters.adx_floor": 20,
                },
            )
        )
    if "sol_short_shock_lb16_adx22" in item_map:
        rows.append(
            _make_variant(
                item_map["sol_short_shock_lb16_adx22"],
                name="sol_short_shock_relaxed_lb14_adx20_s090",
                note="SOL 事件/破位短腿放宽版：先扩信号覆盖，再靠 impact gate 过滤",
                patch={
                    "strategy_params.breakout_lookback": 14,
                    "strategy_params.breakout_atr_buffer": 0.45,
                    "strategy_params.cooldown_bars": 5,
                    "filters.adx_floor": 20,
                    "money_management.stake_scale.sol_short": 0.90,
                },
            )
        )
    if "eth_short_shock_lb16_adx24" in item_map:
        rows.append(
            _make_variant(
                item_map["eth_short_shock_lb16_adx24"],
                name="eth_short_shock_relaxed_lb14_adx22_s088",
                note="ETH 事件/破位短腿放宽版：扩大 short shock 覆盖，验证 ETH 双侧空间",
                patch={
                    "strategy_params.breakout_lookback": 14,
                    "strategy_params.breakout_atr_buffer": 0.50,
                    "strategy_params.cooldown_bars": 5,
                    "filters.adx_floor": 22,
                    "money_management.stake_scale.eth_short": 0.88,
                },
            )
        )

    dedup: dict[str, dict[str, Any]] = {}
    for row in rows:
        dedup[row["name"]] = row
    return list(dedup.values())


def _lane_score(metrics: dict[str, Any]) -> float:
    m = metrics.get("monthly", {}) or {}
    return float(
        _safe_float(metrics.get("pf")) * 92.0
        + _safe_float(metrics.get("ret")) * 60.0
        - abs(_safe_float(metrics.get("maxdd"))) * 72.0
        + min(int(metrics.get("trades", 0) or 0), 220) * 0.28
        + int(m.get("months_ge_20", 0) or 0) * 26.0
        + _safe_float(m.get("monthly_p75", 0.0)) * 220.0
        + _safe_float(metrics.get("rolling12_pf_floor", 0.0)) * 14.0
    )


def _lane_gate_label(metrics: dict[str, Any]) -> str:
    m = metrics.get("monthly", {}) or {}
    pf = _safe_float(metrics.get("pf"))
    ret = _safe_float(metrics.get("ret"))
    dd = abs(_safe_float(metrics.get("maxdd")))
    trades = int(metrics.get("trades", 0) or 0)
    months20 = int(m.get("months_ge_20", 0) or 0)
    p75 = _safe_float(m.get("monthly_p75", 0.0))
    if pf >= 1.10 and ret > 0.0 and dd <= 0.50 and trades >= 18 and (months20 >= 2 or p75 >= 0.09):
        return "pass"
    if pf >= 1.00 and dd <= 0.60 and trades >= 12 and (ret > -0.05 or p75 >= 0.06):
        return "hold"
    return "kill"


def _best_by_lane(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row["symbol"]).lower(), str(row["family"]).lower())
        cur = out.get(key)
        if cur is None or float(row["best_gate"]["score"]) > float(cur["best_gate"]["score"]):
            out[key] = row
    return out


def _write_txt(path_txt: Path, rows: list[dict[str, Any]], best_lane: dict[tuple[str, str], dict[str, Any]]) -> None:
    lines: list[str] = []
    lines.append("Stage69 分支四条腿广角单独赛道")
    lines.append("核心原则：ETH / SOL 都允许多空短波；先把四条单腿做强，再考虑 dual 联动")
    lines.append("")
    lines.append("=== 各赛道当前最优 ===")
    for sym in ["eth", "sol"]:
        for fam in ["long", "short"]:
            row = best_lane.get((sym, fam))
            if row is None:
                continue
            best = row["best_gate"]
            m = best["metrics"]
            mm = m.get("monthly", {}) or {}
            lines.append(
                f"- {sym.upper()} | {fam}: {row['name']} | best_gate={best['gate_name']} ({best['gate']}) | trades={m['trades']} | pf={_safe_float(m['pf']):.3f} | ret={_fmt_pct(m['ret'])} | maxDD={_fmt_pct(m['maxdd'])} | months>=20%={mm.get('months_ge_20', 0)} | p75_month={_fmt_pct(mm.get('monthly_p75', 0.0))} | score={best['score']:+.2f}"
            )
            lines.append(f"  note={row.get('note','')} | gate_note={best['gate_note']}")
    lines.append("")
    lines.append("=== 全部候选 ===")
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
        lines.append(f"  note={row.get('note','')} | gate_note={best['gate_note']}")
    lines.append("")
    lines.append("=== 结论 ===")
    lines.append("- 不再把分支问题缩成单一方向；现在只比较 ETH long / ETH short / SOL long / SOL short 四条单腿。")
    lines.append("- dual 先不升；先把单腿做到更接近‘月化 20%+’。")
    lines.append("- 若 ETH long 现有模板仍弱，不代表 ETH 不能做多，只代表当前 ETH long 模板还不对。")
    path_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage69 branch single-leg arena")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    cfg = read_config(root / "config.yml")
    initial_equity = float(cfg.get("portfolio", {}).get("initial_equity", 100000.0))

    rows = [s65._run_branch(root, cfg, item, initial_equity) for item in _candidate_items()]
    for row in rows:
        row["best_gate"] = s65._pick_best_gate(row["gate_rows"], _lane_score, _lane_gate_label)
    rows.sort(key=lambda r: float(r["best_gate"]["score"]), reverse=True)
    best_lane = _best_by_lane(rows)

    reports = root / "reports" / "research_raw"
    reports.mkdir(parents=True, exist_ok=True)
    txt_path = reports / "stage69_branch_single_leg_latest.txt"
    json_path = reports / "stage69_branch_single_leg_latest.json"
    _write_txt(txt_path, rows, best_lane)
    json_path.write_text(
        json.dumps(
            {
                "rows": [s65._json_safe({**row, "best_gate": s65._strip_gate_payload(row)}) for row in rows],
                "best_by_lane": {
                    f"{k[0]}_{k[1]}": s65._json_safe({**v, "best_gate": s65._strip_gate_payload(v)})
                    for k, v in best_lane.items()
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(txt_path)
    print(json_path)


if __name__ == "__main__":
    main()
