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
    for k, v in patch.items():
        mods[k] = v
    row["mods"] = mods
    row["family"] = _detect_family(name, mods)
    return row


def _candidate_items() -> list[dict[str, Any]]:
    item_map = _base_item_map()
    rows: list[dict[str, Any]] = []

    def push_existing(name: str) -> None:
        item = item_map.get(name)
        if not item:
            return
        item = copy.deepcopy(item)
        item["family"] = _detect_family(item["name"], item.get("mods", {}))
        rows.append(item)

    # keep working controls on table
    for name in [
        "sol_long_core_adx28_cd6_lb22_zone027_s038",
        "sol_shortwave_smooth_longonly",
        "sol_fast_trend_lb16_shortonly",
        "eth_shortwave_tight_shortonly",
    ]:
        push_existing(name)

    if "eth_fast_trend_lb16_longonly" in item_map:
        rows.append(
            _make_variant(
                item_map["eth_fast_trend_lb16_longonly"],
                name="eth_breakout_long_follow_lb18_atr055_adx24_s030",
                note="ETH 长腿重建 A：不是继续放松，而是改成跟随型 breakout long",
                patch={
                    "strategy_params.breakout_lookback": 18,
                    "strategy_params.breakout_atr_buffer": 0.55,
                    "strategy_params.cooldown_bars": 5,
                    "filters.adx_floor": 24,
                    "money_management.stake_scale.eth_long": 0.30,
                },
            )
        )
        rows.append(
            _make_variant(
                item_map["eth_fast_trend_lb16_longonly"],
                name="eth_breakout_long_guarded_lb20_atr060_adx26_s028",
                note="ETH 长腿重建 B：提高趋势确认，压掉无效快进快出",
                patch={
                    "strategy_params.breakout_lookback": 20,
                    "strategy_params.breakout_atr_buffer": 0.60,
                    "strategy_params.cooldown_bars": 6,
                    "filters.adx_floor": 26,
                    "money_management.stake_scale.eth_long": 0.28,
                },
            )
        )

    if "eth_shortwave_longonly" in item_map:
        rows.append(
            _make_variant(
                item_map["eth_shortwave_longonly"],
                name="eth_pullback_long_reset_lb20_zone031_adx24_s030",
                note="ETH 长腿重建 C：保留回踩，但按更大结构重新建模",
                patch={
                    "sr_entries.cooldown_bars": 5,
                    "strategy_params.cooldown_bars": 5,
                    "sr_entries.lookback_4h": 20,
                    "sr_entries.zone_atr_mult": 0.31,
                    "sr_entries.adx_max": 24.0,
                    "sr_entries.stake_scale": 0.30,
                },
            )
        )

    if "eth_long_core_adx26_cd6_lb24_zone028_s032" in item_map:
        rows.append(
            _make_variant(
                item_map["eth_long_core_adx26_cd6_lb24_zone028_s032"],
                name="eth_core_long_reset_adx28_cd5_lb22_zone029_s028",
                note="ETH 长腿重建 D：核心长腿不砍掉，但换成更清晰的中轴结构",
                patch={
                    "sr_entries.adx_max": 28.0,
                    "sr_entries.cooldown_bars": 5,
                    "strategy_params.cooldown_bars": 5,
                    "sr_entries.lookback_4h": 22,
                    "sr_entries.zone_atr_mult": 0.29,
                    "sr_entries.stake_scale": 0.28,
                },
            )
        )

    if "eth_short_shock_lb16_adx24" in item_map:
        rows.append(
            _make_variant(
                item_map["eth_short_shock_lb16_adx24"],
                name="eth_short_shock_control_lb18_adx26_s074",
                note="ETH 空腿控制版：保留 short，但先把噪声回撤压回去",
                patch={
                    "strategy_params.breakout_lookback": 18,
                    "strategy_params.breakout_atr_buffer": 0.58,
                    "strategy_params.cooldown_bars": 6,
                    "filters.adx_floor": 26,
                    "money_management.stake_scale.eth_short": 0.74,
                },
            )
        )

    if "sol_fast_trend_lb16_shortonly" in item_map:
        rows.append(
            _make_variant(
                item_map["sol_fast_trend_lb16_shortonly"],
                name="sol_fast_trend_short_guarded_lb18_atr060_adx24_s068",
                note="SOL 空腿控制 A：先降杠杆和噪声，留住有效 short",
                patch={
                    "strategy_params.breakout_lookback": 18,
                    "strategy_params.breakout_atr_buffer": 0.60,
                    "strategy_params.cooldown_bars": 7,
                    "filters.adx_floor": 24,
                    "money_management.stake_scale.sol_short": 0.68,
                },
            )
        )
        rows.append(
            _make_variant(
                item_map["sol_fast_trend_lb16_shortonly"],
                name="sol_fast_trend_short_guarded_lb20_atr065_adx26_s060",
                note="SOL 空腿控制 B：进一步压 DD，看能否保留收益曲线",
                patch={
                    "strategy_params.breakout_lookback": 20,
                    "strategy_params.breakout_atr_buffer": 0.65,
                    "strategy_params.cooldown_bars": 8,
                    "filters.adx_floor": 26,
                    "money_management.stake_scale.sol_short": 0.60,
                },
            )
        )

    if "sol_short_shock_lb16_adx22" in item_map:
        rows.append(
            _make_variant(
                item_map["sol_short_shock_lb16_adx22"],
                name="sol_short_shock_guarded_lb20_adx26_s058",
                note="SOL 冲击空腿控制版：保留事件 short，但不给超大回撤放行",
                patch={
                    "strategy_params.breakout_lookback": 20,
                    "strategy_params.breakout_atr_buffer": 0.62,
                    "strategy_params.cooldown_bars": 8,
                    "filters.adx_floor": 26,
                    "money_management.stake_scale.sol_short": 0.58,
                },
            )
        )

    dedup: dict[str, dict[str, Any]] = {}
    for row in rows:
        row.setdefault("symbol", (row.get("mods", {}).get("strategy_params.long_symbols") or row.get("mods", {}).get("strategy_params.short_symbols") or [""])[0])
        dedup[row["name"]] = row
    return list(dedup.values())


def _lane_score(metrics: dict[str, Any]) -> float:
    m = metrics.get("monthly", {}) or {}
    return float(
        _safe_float(metrics.get("pf")) * 102.0
        + _safe_float(metrics.get("ret")) * 66.0
        - abs(_safe_float(metrics.get("maxdd"))) * 98.0
        + min(int(metrics.get("trades", 0) or 0), 240) * 0.28
        + int(m.get("months_ge_20", 0) or 0) * 34.0
        + _safe_float(m.get("monthly_p75", 0.0)) * 260.0
        + _safe_float(metrics.get("rolling12_pf_floor", 0.0)) * 22.0
    )


def _lane_gate_label(metrics: dict[str, Any]) -> str:
    m = metrics.get("monthly", {}) or {}
    pf = _safe_float(metrics.get("pf"))
    ret = _safe_float(metrics.get("ret"))
    dd = abs(_safe_float(metrics.get("maxdd")))
    trades = int(metrics.get("trades", 0) or 0)
    months20 = int(m.get("months_ge_20", 0) or 0)
    p75 = _safe_float(m.get("monthly_p75", 0.0))
    if pf >= 1.10 and ret > 0.0 and dd <= 0.35 and trades >= 16 and (months20 >= 2 or p75 >= 0.09):
        return "pass"
    if pf >= 1.00 and dd <= 0.46 and trades >= 12 and (ret > -0.02 or p75 >= 0.06):
        return "hold"
    return "kill"


def _best_by_lane(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row.get("symbol", "")).lower(), str(row.get("family", "")).lower())
        cur = out.get(key)
        if cur is None or float(row["best_gate"]["score"]) > float(cur["best_gate"]["score"]):
            out[key] = row
    return out


def _write_txt(path_txt: Path, rows: list[dict[str, Any]], best_lane: dict[tuple[str, str], dict[str, Any]]) -> None:
    lines: list[str] = []
    lines.append("Stage74 分支重建赛道")
    lines.append("核心原则：ETH 长腿重建，SOL 空腿压 DD；不再过早砍方向。")
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
                f"- {sym.upper()} | {fam}: {row['name']} | best_gate={best['gate_name']} ({best['gate']}) | trades={m['trades']} | pf={_safe_float(m['pf']):.3f} | ret={_fmt_pct(m['ret'])} | maxDD={_fmt_pct(m['maxdd'])} | months>=20%={mm.get('months_ge_20', 0)} | p75_month={_fmt_pct(mm.get('monthly_p75', 0.0))} | roll12_pf_floor={_safe_float(m.get('rolling12_pf_floor')):.3f} | score={best['score']:+.2f}"
            )
            lines.append(f"  note={row.get('note','')} | gate_note={best['gate_note']}")
    lines.append("")
    lines.append("=== 全部候选 ===")
    for row in rows:
        best = row["best_gate"]
        m = best["metrics"]
        mm = m.get("monthly", {}) or {}
        lines.append(
            f"- {str(row.get('symbol','')).upper()} | family={row['family']} | {row['name']}: best_gate={best['gate_name']} ({best['gate']}) | trades={m['trades']} | pf={_safe_float(m['pf']):.3f} | ret={_fmt_pct(m['ret'])} | maxDD={_fmt_pct(m['maxdd'])} | months>=20%={mm.get('months_ge_20', 0)} | p75_month={_fmt_pct(mm.get('monthly_p75', 0.0))} | roll12_pf_floor={_safe_float(m.get('rolling12_pf_floor')):.3f} | score={best['score']:+.2f}"
        )
        base = row.get("base_metrics", {})
        lines.append(
            f"  base=trades {base.get('trades', 0)} / pf {_safe_float(base.get('pf')):.3f} / ret {_fmt_pct(base.get('ret'))} / maxDD {_fmt_pct(base.get('maxdd'))}"
        )
        lines.append(f"  note={row.get('note','')} | gate_note={best['gate_note']}")
    lines.append("")
    lines.append("=== 结论 ===")
    lines.append("- ETH 重点不是再放松，而是把 long 结构换成 breakout-follow / pullback-reset 两条线。")
    lines.append("- SOL 重点不是砍 short，而是继续把 DD 往下压，看能否保住收益。")
    lines.append("- dual 继续不升；先把单腿做成更像可接模拟盘的候选。")
    path_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage74 branch rebuild lanes")
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
    txt_path = reports / "stage74_branch_rebuild_latest.txt"
    json_path = reports / "stage74_branch_rebuild_latest.json"
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
