from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest.io import read_config

try:
    from tools import stage46_aggressive_lab as s46
    from tools import stage65_price_impact_frontier_lab as s65
except Exception as exc:
    raise SystemExit("缺少 stage46/stage65 模块，请先保留此前补丁。") from exc


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


def _candidate_items() -> list[dict[str, Any]]:
    def item(name: str, note: str, **mods: Any) -> dict[str, Any]:
        return {"name": name, "note": note, "mods": mods}

    common = {
        "strategy_params.long_symbols": ["bnb"],
        "strategy_params.short_symbols": ["btc"],
        "filters.btc_short_entry_mode": "pullback",
        "filters.btc_short_macro_tf": "4h",
        "sr_entries.enabled": True,
        "sr_entries.symbols": ["bnb"],
        "sr_entries.use_adx_filter": True,
        "sr_entries.adx_min": 0.0,
        "sr_entries.require_compress_ok": True,
    }

    rows = [
        item(
            "bridge_ref_split_adx28_cd6_lb24_zone028_pull095",
            "对照线：只拆结构，不硬推频次",
            **{
                **common,
                "strategy_params.cooldown_bars": 6,
                "filters.adx_floor": 28,
                "filters.btc_adx_floor": 28,
                "sr_entries.lookback_4h": 24,
                "sr_entries.zone_atr_mult": 0.28,
                "sr_entries.adx_max": 28.0,
                "sr_entries.stake_scale": 0.16,
                "sr_entries.cooldown_bars": 6,
                "filters.btc_short_pullback_atr": 0.95,
            },
        ),
        item(
            "bridge_low_adx28_cd5_lb22_zone027_pull100",
            "先冲 240 一带：只放开一档 cooldown / pullback，不放掉 compress",
            **{
                **common,
                "strategy_params.cooldown_bars": 5,
                "filters.adx_floor": 28,
                "filters.btc_adx_floor": 28,
                "sr_entries.lookback_4h": 22,
                "sr_entries.zone_atr_mult": 0.27,
                "sr_entries.adx_max": 28.0,
                "sr_entries.stake_scale": 0.17,
                "sr_entries.cooldown_bars": 5,
                "filters.btc_short_pullback_atr": 1.00,
            },
        ),
        item(
            "bridge_mid_a_adx30_cd5_lb22_zone026_pull102",
            "目标 260-320 第一组：分腿放开，但仍保持 pullback + compress 双结构",
            **{
                **common,
                "strategy_params.cooldown_bars": 5,
                "filters.adx_floor": 30,
                "filters.btc_adx_floor": 30,
                "sr_entries.lookback_4h": 22,
                "sr_entries.zone_atr_mult": 0.26,
                "sr_entries.adx_max": 30.0,
                "sr_entries.stake_scale": 0.18,
                "sr_entries.cooldown_bars": 5,
                "filters.btc_short_pullback_atr": 1.02,
            },
        ),
        item(
            "bridge_mid_b_adx32_cd4_lb20_zone025_pull104",
            "目标 260-320 第二组：进一步缩短窗口，但不关掉结构门",
            **{
                **common,
                "strategy_params.cooldown_bars": 4,
                "filters.adx_floor": 32,
                "filters.btc_adx_floor": 32,
                "sr_entries.lookback_4h": 20,
                "sr_entries.zone_atr_mult": 0.25,
                "sr_entries.adx_max": 32.0,
                "sr_entries.stake_scale": 0.18,
                "sr_entries.cooldown_bars": 4,
                "filters.btc_short_pullback_atr": 1.04,
            },
        ),
        item(
            "bridge_mid_c_adx34_cd4_lb18_zone024_pull106",
            "中高频桥接：验证 300 左右是否能靠 split 结构站住",
            **{
                **common,
                "strategy_params.cooldown_bars": 4,
                "filters.adx_floor": 34,
                "filters.btc_adx_floor": 34,
                "sr_entries.lookback_4h": 18,
                "sr_entries.zone_atr_mult": 0.24,
                "sr_entries.adx_max": 34.0,
                "sr_entries.stake_scale": 0.19,
                "sr_entries.cooldown_bars": 4,
                "filters.btc_short_pullback_atr": 1.06,
            },
        ),
        item(
            "bridge_high_a_adx36_cd4_lb18_zone023_pull108",
            "320+ 第一组：继续开，但只让 BNB 长腿更快，BTC 空腿仍走 pullback",
            **{
                **common,
                "strategy_params.cooldown_bars": 4,
                "filters.adx_floor": 36,
                "filters.btc_adx_floor": 36,
                "sr_entries.lookback_4h": 18,
                "sr_entries.zone_atr_mult": 0.23,
                "sr_entries.adx_max": 36.0,
                "sr_entries.stake_scale": 0.19,
                "sr_entries.cooldown_bars": 4,
                "filters.btc_short_pullback_atr": 1.08,
            },
        ),
        item(
            "bridge_high_b_adx38_cd3_lb16_zone022_pull110",
            "320+ 第二组：研究上限，不直接作为主线候选",
            **{
                **common,
                "strategy_params.cooldown_bars": 3,
                "filters.adx_floor": 38,
                "filters.btc_adx_floor": 38,
                "sr_entries.lookback_4h": 16,
                "sr_entries.zone_atr_mult": 0.22,
                "sr_entries.adx_max": 38.0,
                "sr_entries.stake_scale": 0.20,
                "sr_entries.cooldown_bars": 3,
                "filters.btc_short_pullback_atr": 1.10,
            },
        ),
    ]
    return rows


def _band(trades: int) -> str:
    if 220 <= trades < 260:
        return "220_260"
    if 260 <= trades < 320:
        return "260_320"
    if 320 <= trades <= 420:
        return "320_420"
    return "outside"


def _score(metrics: dict[str, Any], ref: dict[str, Any]) -> float:
    m = metrics.get("monthly", {}) or {}
    trades = int(metrics.get("trades", 0) or 0)
    pf = _safe_float(metrics.get("pf"))
    dd = abs(_safe_float(metrics.get("maxdd")))
    ret = _safe_float(metrics.get("ret"))
    floor = _safe_float(metrics.get("rolling12_pf_floor"))
    p75 = _safe_float(m.get("monthly_p75", 0.0))
    months20 = int(m.get("months_ge_20", 0) or 0)
    band_bonus = {"220_260": 8.0, "260_320": 22.0, "320_420": 16.0, "outside": 0.0}[_band(trades)]
    pf_pen = max(0.0, _safe_float(ref.get("pf")) - pf) * 26.0
    dd_pen = max(0.0, dd - abs(_safe_float(ref.get("maxdd")))) * 55.0
    return float(
        pf * 96.0
        + ret * 55.0
        - dd * 95.0
        + min(trades, 420) * 0.22
        + months20 * 4.0
        + p75 * 155.0
        + floor * 22.0
        + band_bonus
        - pf_pen
        - dd_pen
    )


def _gate_label(metrics: dict[str, Any], ref: dict[str, Any]) -> str:
    trades = int(metrics.get("trades", 0) or 0)
    pf = _safe_float(metrics.get("pf"))
    dd = abs(_safe_float(metrics.get("maxdd")))
    floor = _safe_float(metrics.get("rolling12_pf_floor"))
    if trades >= 240 and pf >= 1.85 and dd <= 0.45 and floor >= 0.65:
        return "pass"
    if trades >= 220 and pf >= 1.60 and dd <= 0.56 and floor >= 0.54:
        return "hold"
    return "kill"


def _write_txt(path_txt: Path, rows: list[dict[str, Any]]) -> None:
    best_by_band: dict[str, dict[str, Any]] = {}
    for row in rows:
        b = row["trade_band"]
        cur = best_by_band.get(b)
        if cur is None or float(row["best_gate"]["score"]) > float(cur["best_gate"]["score"]):
            best_by_band[b] = row

    lines: list[str] = []
    lines.append("Stage73 主线桥接频次前沿")
    lines.append("核心原则：不是继续粗暴放宽，而是用 split 结构去桥接 240-320。")
    lines.append("")
    lines.append("=== 各频次带当前最优 ===")
    for band in ["220_260", "260_320", "320_420", "outside"]:
        row = best_by_band.get(band)
        if row is None:
            lines.append(f"- band={band} | 本轮暂无候选落在该带")
            continue
        best = row["best_gate"]
        m = best["metrics"]
        mm = m.get("monthly", {}) or {}
        lines.append(
            f"- band={band} | {row['name']}: best_gate={best['gate_name']} ({best['gate']}) | trades={m['trades']} | pf={_safe_float(m['pf']):.3f} | ret={_fmt_pct(m['ret'])} | maxDD={_fmt_pct(m['maxdd'])} | months>=20%={mm.get('months_ge_20', 0)} | p75_month={_fmt_pct(mm.get('monthly_p75', 0.0))} | roll12_pf_floor={_safe_float(m.get('rolling12_pf_floor')):.3f} | score={best['score']:+.2f}"
        )
        lines.append(f"  note={row['note']} | gate_note={best['gate_note']}")
    lines.append("")
    lines.append("=== 全部候选 ===")
    for row in rows:
        best = row["best_gate"]
        m = best["metrics"]
        mm = m.get("monthly", {}) or {}
        lines.append(
            f"- band={row['trade_band']} | {row['name']}: best_gate={best['gate_name']} ({best['gate']}) | trades={m['trades']} | pf={_safe_float(m['pf']):.3f} | ret={_fmt_pct(m['ret'])} | maxDD={_fmt_pct(m['maxdd'])} | months>=20%={mm.get('months_ge_20', 0)} | p75_month={_fmt_pct(mm.get('monthly_p75', 0.0))} | roll12_pf_floor={_safe_float(m.get('rolling12_pf_floor')):.3f} | score={best['score']:+.2f}"
        )
        base = row.get("base_metrics", {})
        lines.append(f"  base=trades {base.get('trades', 0)} / pf {_safe_float(base.get('pf')):.3f} / ret {_fmt_pct(base.get('ret'))} / maxDD {_fmt_pct(base.get('maxdd'))}")
        lines.append(f"  note={row['note']} | gate_note={best['gate_note']}")
    lines.append("")
    lines.append("=== 结论 ===")
    lines.append("- 这一轮不再用同一把尺子粗暴加速，而是把 BNB 长腿和 BTC 空腿拆开去桥接更高频次。")
    lines.append("- 如果 260-320 仍站不住，说明问题不在阈值，而在需要新的主线结构引擎。")
    lines.append("- 仍然只在研究层，不直接上 live。")
    path_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage73 mainline bridge frontier")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    cfg = read_config(root / "config.yml")
    initial_equity = float(cfg.get("portfolio", {}).get("initial_equity", 100000.0))
    data = s46._load_portfolio_data(root, cfg)

    items = _candidate_items()
    rows = [s65._run_mainline(root, cfg, data, item, initial_equity) for item in items]
    ref_row = next((r for r in rows if r["name"] == "bridge_ref_split_adx28_cd6_lb24_zone028_pull095"), rows[0])
    ref_metrics = ref_row.get("base_metrics", {})
    for row in rows:
        row["trade_band"] = _band(int(row.get("base_metrics", {}).get("trades", 0) or 0))
        row["best_gate"] = s65._pick_best_gate(row["gate_rows"], _score, _gate_label, ref_metrics)
    rows.sort(key=lambda r: float(r["best_gate"]["score"]), reverse=True)

    reports = root / "reports" / "research_raw"
    reports.mkdir(parents=True, exist_ok=True)
    txt_path = reports / "stage73_mainline_bridge_frontier_latest.txt"
    json_path = reports / "stage73_mainline_bridge_frontier_latest.json"
    _write_txt(txt_path, rows)
    json_path.write_text(
        json.dumps(
            {
                "rows": [s65._json_safe({**row, "best_gate": s65._strip_gate_payload(row)}) for row in rows],
                "reference": s65._json_safe(ref_metrics),
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
