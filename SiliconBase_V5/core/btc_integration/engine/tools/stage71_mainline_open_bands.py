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
        item(
            "open_ref_adx26_cd6_lb24_zone028",
            "参考线，只做质量对照，不做定锚",
            **{
                "sr_entries.adx_max": 26.0,
                "sr_entries.cooldown_bars": 6,
                "sr_entries.lookback_4h": 24,
                "sr_entries.zone_atr_mult": 0.28,
                "filters.btc_short_pullback_atr": 0.95,
                "sr_entries.require_compress_ok": True,
            },
        ),
        item(
            "open_233_anchor_adx32_cd5_lb20_zone025",
            "保留 233 一带作对照，不再把它当终点",
            **{
                "sr_entries.adx_max": 32.0,
                "sr_entries.cooldown_bars": 5,
                "sr_entries.lookback_4h": 20,
                "sr_entries.zone_atr_mult": 0.25,
                "filters.btc_short_pullback_atr": 1.02,
                "sr_entries.require_compress_ok": True,
            },
        ),
        item(
            "open_mid_a_adx36_cd4_lb18_zone023_pull108_nc",
            "打开 260-320 第一组：放开压缩约束，但保留结构区间",
            **{
                "sr_entries.adx_max": 36.0,
                "sr_entries.cooldown_bars": 4,
                "sr_entries.lookback_4h": 18,
                "sr_entries.zone_atr_mult": 0.23,
                "filters.btc_short_pullback_atr": 1.08,
                "sr_entries.require_compress_ok": False,
            },
        ),
        item(
            "open_mid_b_adx38_cd4_lb16_zone022_pull110_nc",
            "打开 260-320 第二组：再放开 lookback/cooldown",
            **{
                "sr_entries.adx_max": 38.0,
                "sr_entries.cooldown_bars": 4,
                "sr_entries.lookback_4h": 16,
                "sr_entries.zone_atr_mult": 0.22,
                "filters.btc_short_pullback_atr": 1.10,
                "sr_entries.require_compress_ok": False,
            },
        ),
        item(
            "open_mid_c_adx40_cd3_lb16_zone022_pull112_nc",
            "中高频交界：开始验证 300 左右是否还能守住质量",
            **{
                "sr_entries.adx_max": 40.0,
                "sr_entries.cooldown_bars": 3,
                "sr_entries.lookback_4h": 16,
                "sr_entries.zone_atr_mult": 0.22,
                "filters.btc_short_pullback_atr": 1.12,
                "sr_entries.require_compress_ok": False,
            },
        ),
        item(
            "open_high_a_adx42_cd3_lb14_zone021_pull115_nc",
            "打开 320-420 第一组：更快，不直接收口",
            **{
                "sr_entries.adx_max": 42.0,
                "sr_entries.cooldown_bars": 3,
                "sr_entries.lookback_4h": 14,
                "sr_entries.zone_atr_mult": 0.21,
                "filters.btc_short_pullback_atr": 1.15,
                "sr_entries.require_compress_ok": False,
            },
        ),
        item(
            "open_high_b_adx44_cd3_lb12_zone020_pull118_nc",
            "打开 320-420 第二组：进一步压缩 lookback/zone",
            **{
                "sr_entries.adx_max": 44.0,
                "sr_entries.cooldown_bars": 3,
                "sr_entries.lookback_4h": 12,
                "sr_entries.zone_atr_mult": 0.20,
                "filters.btc_short_pullback_atr": 1.18,
                "sr_entries.require_compress_ok": False,
            },
        ),
        item(
            "open_high_c_adx46_cd2_lb12_zone019_pull120_nc",
            "高频极限探索：只放研究层，用来看上限而不是直接实盘",
            **{
                "sr_entries.adx_max": 46.0,
                "sr_entries.cooldown_bars": 2,
                "sr_entries.lookback_4h": 12,
                "sr_entries.zone_atr_mult": 0.19,
                "filters.btc_short_pullback_atr": 1.20,
                "sr_entries.require_compress_ok": False,
            },
        ),
        item(
            "open_high_d_adx48_cd2_lb10_zone018_pull122_nc",
            "更极限的 320+ 检查点：确认是不是已经明显过度",
            **{
                "sr_entries.adx_max": 48.0,
                "sr_entries.cooldown_bars": 2,
                "sr_entries.lookback_4h": 10,
                "sr_entries.zone_atr_mult": 0.18,
                "filters.btc_short_pullback_atr": 1.22,
                "sr_entries.require_compress_ok": False,
            },
        ),
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
    band_bonus = {"220_260": 10.0, "260_320": 22.0, "320_420": 34.0, "outside": 0.0}[_band(trades)]
    penalty = max(0.0, _safe_float(ref.get("pf")) - pf) * 16.0
    return float(
        pf * 84.0
        + ret * 50.0
        - dd * 82.0
        + min(trades, 420) * 0.18
        + int(m.get("months_ge_20", 0) or 0) * 3.0
        + _safe_float(m.get("monthly_p75", 0.0)) * 120.0
        + floor * 18.0
        + band_bonus
        - penalty
    )


def _gate_label(metrics: dict[str, Any], ref: dict[str, Any]) -> str:
    trades = int(metrics.get("trades", 0) or 0)
    pf = _safe_float(metrics.get("pf"))
    dd = abs(_safe_float(metrics.get("maxdd")))
    floor = _safe_float(metrics.get("rolling12_pf_floor"))
    if trades >= 220 and pf >= 1.80 and dd <= 0.55 and floor >= 0.58:
        return "pass"
    if trades >= 200 and pf >= 1.55 and dd <= 0.68 and floor >= 0.48:
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
    lines.append("Stage71 主线频次带重新打开")
    lines.append("核心原则：不再过早定锚 233；这轮必须把 260-320 / 320-420 真正跑出来。")
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
    lines.append("- 这一轮的目标不是立刻选主线，而是把三个频次带都真正跑出来。")
    lines.append("- 如果 260-320 或 320-420 质量明显崩，就再回退；如果还能站住，就保留更宽前沿。")
    lines.append("- 仍然只在研究层，不直接上 live。")
    path_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage71 mainline open bands")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    cfg = read_config(root / "config.yml")
    initial_equity = float(cfg.get("portfolio", {}).get("initial_equity", 100000.0))
    data = s46._load_portfolio_data(root, cfg)

    items = _candidate_items()
    rows = [s65._run_mainline(root, cfg, data, item, initial_equity) for item in items]
    ref_row = next((r for r in rows if r["name"] == "open_ref_adx26_cd6_lb24_zone028"), rows[0])
    ref_metrics = ref_row.get("base_metrics", {})
    for row in rows:
        row["trade_band"] = _band(int(row.get("base_metrics", {}).get("trades", 0) or 0))
        row["best_gate"] = s65._pick_best_gate(row["gate_rows"], _score, _gate_label, ref_metrics)
    rows.sort(key=lambda r: float(r["best_gate"]["score"]), reverse=True)

    reports = root / "reports" / "research_raw"
    reports.mkdir(parents=True, exist_ok=True)
    txt_path = reports / "stage71_mainline_open_bands_latest.txt"
    json_path = reports / "stage71_mainline_open_bands_latest.json"
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
