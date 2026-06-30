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
    base = dict(s46.REF_MAIN_MODS)

    def item(name: str, note: str, **patch: Any) -> dict[str, Any]:
        mods = {**base, **patch}
        return {"name": name, "note": note, "mods": mods}

    return [
        item("wide_ref_adx26_cd6_lb24_zone028", "参考线，不定锚，只做质量对照", **{
            "sr_entries.adx_max": 26.0,
            "sr_entries.cooldown_bars": 6,
            "sr_entries.lookback_4h": 24,
            "sr_entries.zone_atr_mult": 0.28,
            "filters.btc_short_pullback_atr": 0.95,
        }),
        item("wide_a_adx28_cd6_lb24_zone028", "温和提频", **{
            "sr_entries.adx_max": 28.0,
            "sr_entries.cooldown_bars": 6,
            "sr_entries.lookback_4h": 24,
            "sr_entries.zone_atr_mult": 0.28,
            "filters.btc_short_pullback_atr": 0.95,
        }),
        item("wide_b_adx30_cd6_lb22_zone026", "中速提频", **{
            "sr_entries.adx_max": 30.0,
            "sr_entries.cooldown_bars": 6,
            "sr_entries.lookback_4h": 22,
            "sr_entries.zone_atr_mult": 0.26,
            "filters.btc_short_pullback_atr": 0.98,
        }),
        item("wide_c_adx30_cd5_lb22_zone026", "前沿快版", **{
            "sr_entries.adx_max": 30.0,
            "sr_entries.cooldown_bars": 5,
            "sr_entries.lookback_4h": 22,
            "sr_entries.zone_atr_mult": 0.26,
            "filters.btc_short_pullback_atr": 1.00,
        }),
        item("wide_d_adx32_cd5_lb20_zone025", "更激进，但仍保留结构确认", **{
            "sr_entries.adx_max": 32.0,
            "sr_entries.cooldown_bars": 5,
            "sr_entries.lookback_4h": 20,
            "sr_entries.zone_atr_mult": 0.25,
            "filters.btc_short_pullback_atr": 1.02,
        }),
        item("wide_e_adx32_cd4_lb18_zone024", "重开前沿，不再被 233 早早定锚", **{
            "sr_entries.adx_max": 32.0,
            "sr_entries.cooldown_bars": 4,
            "sr_entries.lookback_4h": 18,
            "sr_entries.zone_atr_mult": 0.24,
            "filters.btc_short_pullback_atr": 1.05,
        }),
        item("wide_f_adx34_cd4_lb18_zone024", "高频探索带 1", **{
            "sr_entries.adx_max": 34.0,
            "sr_entries.cooldown_bars": 4,
            "sr_entries.lookback_4h": 18,
            "sr_entries.zone_atr_mult": 0.24,
            "filters.btc_short_pullback_atr": 1.08,
        }),
        item("wide_g_adx34_cd5_lb20_zone025", "高频探索带 2", **{
            "sr_entries.adx_max": 34.0,
            "sr_entries.cooldown_bars": 5,
            "sr_entries.lookback_4h": 20,
            "sr_entries.zone_atr_mult": 0.25,
            "filters.btc_short_pullback_atr": 1.05,
        }),
        item("wide_h_adx28_cd4_lb20_zone026", "结构更快但不过度放大 ADX", **{
            "sr_entries.adx_max": 28.0,
            "sr_entries.cooldown_bars": 4,
            "sr_entries.lookback_4h": 20,
            "sr_entries.zone_atr_mult": 0.26,
            "filters.btc_short_pullback_atr": 1.02,
        }),
        item("wide_i_adx30_cd4_lb20_zone025", "快版中轴", **{
            "sr_entries.adx_max": 30.0,
            "sr_entries.cooldown_bars": 4,
            "sr_entries.lookback_4h": 20,
            "sr_entries.zone_atr_mult": 0.25,
            "filters.btc_short_pullback_atr": 1.03,
        }),
    ]


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
    band_bonus = {"220_260": 8.0, "260_320": 14.0, "320_420": 18.0, "outside": 0.0}[_band(trades)]
    return float(
        pf * 88.0
        + ret * 56.0
        - dd * 82.0
        + min(trades, 420) * 0.16
        + int(m.get("months_ge_20", 0) or 0) * 2.2
        + _safe_float(m.get("monthly_p75", 0.0)) * 110.0
        + floor * 22.0
        + band_bonus
        - max(0.0, _safe_float(ref.get("pf")) - pf) * 22.0
    )


def _gate_label(metrics: dict[str, Any], ref: dict[str, Any]) -> str:
    trades = int(metrics.get("trades", 0) or 0)
    pf = _safe_float(metrics.get("pf"))
    dd = abs(_safe_float(metrics.get("maxdd")))
    floor = _safe_float(metrics.get("rolling12_pf_floor"))
    if trades >= 220 and pf >= 1.95 and dd <= 0.42 and floor >= 0.70:
        return "pass"
    if trades >= 200 and pf >= 1.75 and dd <= 0.48 and floor >= 0.64:
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
    lines.append("Stage70 主线重新开前沿")
    lines.append("核心原则：233 不是终点，只是参考。主线先看多个频次带，不做过早定锚。")
    lines.append("")
    lines.append("=== 各频次带当前最优 ===")
    for band in ["220_260", "260_320", "320_420", "outside"]:
        row = best_by_band.get(band)
        if row is None:
            continue
        best = row["best_gate"]
        m = best["metrics"]
        mm = m.get("monthly", {}) or {}
        lines.append(
            f"- band={band} | {row['name']}: best_gate={best['gate_name']} ({best['gate']}) | trades={m['trades']} | pf={_safe_float(m['pf']):.3f} | ret={_fmt_pct(m['ret'])} | maxDD={_fmt_pct(m['maxdd'])} | months>=20%={mm.get('months_ge_20', 0)} | roll12_pf_floor={_safe_float(m.get('rolling12_pf_floor')):.3f} | score={best['score']:+.2f}"
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
    lines.append("- 主线不再只盯 233；至少同时保留 220-260 / 260-320 / 320-420 三个前沿带。")
    lines.append("- 先比较不同频次带下的质量和消息门兼容性，再决定下一步收口。")
    lines.append("- 这一步只为重新打开前沿，不代表直接上 live。")
    path_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage70 mainline wide frontier")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    cfg = read_config(root / "config.yml")
    initial_equity = float(cfg.get("portfolio", {}).get("initial_equity", 100000.0))
    data = s46._load_portfolio_data(root, cfg)

    items = _candidate_items()
    rows = [s65._run_mainline(root, cfg, data, item, initial_equity) for item in items]
    ref_row = next((r for r in rows if r["name"] == "wide_ref_adx26_cd6_lb24_zone028"), rows[0])
    ref_metrics = ref_row.get("base_metrics", {})
    for row in rows:
        row["trade_band"] = _band(int(row.get("base_metrics", {}).get("trades", 0) or 0))
        row["best_gate"] = s65._pick_best_gate(row["gate_rows"], _score, _gate_label, ref_metrics)
    rows.sort(key=lambda r: float(r["best_gate"]["score"]), reverse=True)

    reports = root / "reports" / "research_raw"
    reports.mkdir(parents=True, exist_ok=True)
    txt_path = reports / "stage70_mainline_wide_frontier_latest.txt"
    json_path = reports / "stage70_mainline_wide_frontier_latest.json"
    _write_txt(txt_path, rows)
    json_path.write_text(json.dumps({
        "rows": [s65._json_safe({**row, "best_gate": s65._strip_gate_payload(row)}) for row in rows],
        "reference": s65._json_safe(ref_metrics),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(txt_path)
    print(json_path)


if __name__ == "__main__":
    main()
