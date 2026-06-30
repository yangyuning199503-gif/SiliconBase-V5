from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest.io import read_config

try:
    from tools import stage46_aggressive_lab as s46
except Exception as exc:
    raise SystemExit("缺少 stage46_aggressive_lab.py，请先应用并运行 stage46 补丁。") from exc


def _fmt_pct(x: float) -> str:
    try:
        return f"{float(x) * 100:.2f}%"
    except Exception:
        return "NA"


def _main_score(row: dict[str, Any], ref: dict[str, Any]) -> float:
    m = row.get("monthly", {}) or {}
    rm = ref.get("monthly", {}) or {}
    trade_gain = max(0, int(row.get("trades", 0)) - int(ref.get("trades", 0)))
    active_gain = max(0, int(m.get("active_months", 0)) - int(rm.get("active_months", 0)))
    months20_gain = max(0, int(m.get("months_ge_20", 0)) - int(rm.get("months_ge_20", 0)))
    pf_pen = max(0.0, float(ref.get("pf", 0.0)) - float(row.get("pf", 0.0)))
    dd_pen = max(0.0, abs(float(row.get("maxdd", 0.0))) - abs(float(ref.get("maxdd", 0.0))))
    ret_pen = max(0.0, float(ref.get("ret", 0.0)) - float(row.get("ret", 0.0)))
    seg_pen = 0.0
    for k in ["2020_2021", "2022_2023", "2024_2026"]:
        seg_pen += max(0.0, float(ref.get("seg_pf", {}).get(k, 0.0)) - float(row.get("seg_pf", {}).get(k, 0.0)))
    floor_bonus = min(float(row.get("rolling12_pf_floor", 0.0)), 2.0) * 13.0
    return float(trade_gain * 1.8 + active_gain * 2.2 + months20_gain * 3.0 - pf_pen * 72.0 - dd_pen * 165.0 - ret_pen * 4.0 - seg_pen * 11.0 + floor_bonus)


def _branch_score(row: dict[str, Any]) -> float:
    m = row.get("monthly", {}) or {}
    return float(
        row.get("pf", 0.0) * 86.0
        + row.get("ret", 0.0) * 52.0
        - abs(row.get("maxdd", 0.0)) * 72.0
        + row.get("trades", 0) * 0.40
        + m.get("months_ge_20", 0) * 16.0
        + m.get("monthly_p75", 0.0) * 130.0
        + min(row.get("rolling12_pf_floor", 0.0), 2.0) * 10.0
    )


def _gate_main(row: dict[str, Any], ref: dict[str, Any]) -> str:
    if row["name"] == ref["name"]:
        return "ref"
    if (
        row.get("trades", 0) >= ref.get("trades", 0)
        and row.get("pf", 0.0) >= max(2.12, ref.get("pf", 0.0) - 0.18)
        and row.get("ret", 0.0) >= ref.get("ret", 0.0) * 0.94
        and abs(row.get("maxdd", 0.0)) <= abs(ref.get("maxdd", 0.0)) + 0.035
        and row.get("rolling12_pf_floor", 0.0) >= 0.76
    ):
        return "pass"
    if row.get("trades", 0) > ref.get("trades", 0) and row.get("pf", 0.0) >= 2.00 and row.get("rolling12_pf_floor", 0.0) >= 0.72:
        return "hold"
    return "kill"


def _gate_branch(row: dict[str, Any]) -> str:
    m = row.get("monthly", {}) or {}
    if (
        row.get("pf", 0.0) >= 1.35
        and row.get("rolling12_pf_floor", 0.0) >= 1.20
        and abs(row.get("maxdd", 0.0)) <= 0.30
        and (m.get("months_ge_20", 0) >= 2 or m.get("monthly_p75", 0.0) >= 0.08)
    ):
        return "pass"
    if row.get("pf", 0.0) >= 1.20 and row.get("trades", 0) >= 24:
        return "hold"
    return "kill"


MAIN_VARIANTS: list[tuple[str, dict[str, Any]]] = [
    (
        "combo_sr_soft_adx26_cd6_lb24_zone028_ref",
        {
            **s46.REF_MAIN_MODS,
            "sr_entries.adx_max": 26.0,
            "sr_entries.cooldown_bars": 6,
            "sr_entries.lookback_4h": 24,
            "sr_entries.zone_atr_mult": 0.28,
        },
    ),
    (
        "combo_sr_soft_adx28_cd6_lb24_zone028",
        {
            **s46.REF_MAIN_MODS,
            "sr_entries.adx_max": 28.0,
            "sr_entries.cooldown_bars": 6,
            "sr_entries.lookback_4h": 24,
            "sr_entries.zone_atr_mult": 0.28,
        },
    ),
    (
        "combo_sr_soft_adx28_cd5_lb24_zone027",
        {
            **s46.REF_MAIN_MODS,
            "sr_entries.adx_max": 28.0,
            "sr_entries.cooldown_bars": 5,
            "sr_entries.lookback_4h": 24,
            "sr_entries.zone_atr_mult": 0.27,
        },
    ),
    (
        "combo_sr_soft_adx28_cd5_lb22_zone027",
        {
            **s46.REF_MAIN_MODS,
            "sr_entries.adx_max": 28.0,
            "sr_entries.cooldown_bars": 5,
            "sr_entries.lookback_4h": 22,
            "sr_entries.zone_atr_mult": 0.27,
        },
    ),
    (
        "combo_sr_soft_adx30_cd5_lb22_zone026",
        {
            **s46.REF_MAIN_MODS,
            "sr_entries.adx_max": 30.0,
            "sr_entries.cooldown_bars": 5,
            "sr_entries.lookback_4h": 22,
            "sr_entries.zone_atr_mult": 0.26,
        },
    ),
    (
        "combo_sr_soft_adx28_cd6_lb22_zone027",
        {
            **s46.REF_MAIN_MODS,
            "sr_entries.adx_max": 28.0,
            "sr_entries.cooldown_bars": 6,
            "sr_entries.lookback_4h": 22,
            "sr_entries.zone_atr_mult": 0.27,
        },
    ),
    (
        "combo_sr_soft_adx26_cd6_lb24_zone028_btcpull100",
        {
            **s46.REF_MAIN_MODS,
            "sr_entries.adx_max": 26.0,
            "sr_entries.cooldown_bars": 6,
            "sr_entries.lookback_4h": 24,
            "sr_entries.zone_atr_mult": 0.28,
            "filters.btc_short_pullback_atr": 1.00,
        },
    ),
    (
        "combo_sr_soft_adx28_cd6_lb24_zone028_btcpull100",
        {
            **s46.REF_MAIN_MODS,
            "sr_entries.adx_max": 28.0,
            "sr_entries.cooldown_bars": 6,
            "sr_entries.lookback_4h": 24,
            "sr_entries.zone_atr_mult": 0.28,
            "filters.btc_short_pullback_atr": 1.00,
        },
    ),
]


BRANCH_VARIANTS: list[tuple[str, dict[str, Any]]] = [
    (
        "sol_long_core_adx26_cd6_s038_ref",
        {
            "strategy_params.allow_short": False,
            "strategy_params.long_symbols": ["sol"],
            "strategy_params.short_symbols": [],
            "mean_reversion.enabled": False,
            "filters.adx_floor": 99,
            "strategy_params.breakout_atr_buffer": 9.0,
            "strategy_params.cooldown_bars": 6,
            "sr_entries.enabled": True,
            "sr_entries.symbols": ["sol"],
            "sr_entries.lookback_4h": 24,
            "sr_entries.zone_atr_mult": 0.28,
            "sr_entries.use_adx_filter": True,
            "sr_entries.adx_min": 0.0,
            "sr_entries.adx_max": 26.0,
            "sr_entries.stake_scale": 0.38,
            "sr_entries.cooldown_bars": 6,
            "sr_entries.require_compress_ok": True,
        },
    ),
    (
        "sol_long_core_adx26_cd6_s045",
        {
            "strategy_params.allow_short": False,
            "strategy_params.long_symbols": ["sol"],
            "strategy_params.short_symbols": [],
            "mean_reversion.enabled": False,
            "filters.adx_floor": 99,
            "strategy_params.breakout_atr_buffer": 9.0,
            "strategy_params.cooldown_bars": 6,
            "sr_entries.enabled": True,
            "sr_entries.symbols": ["sol"],
            "sr_entries.lookback_4h": 24,
            "sr_entries.zone_atr_mult": 0.28,
            "sr_entries.use_adx_filter": True,
            "sr_entries.adx_min": 0.0,
            "sr_entries.adx_max": 26.0,
            "sr_entries.stake_scale": 0.45,
            "sr_entries.cooldown_bars": 6,
            "sr_entries.require_compress_ok": True,
        },
    ),
    (
        "sol_long_core_adx26_cd6_s050",
        {
            "strategy_params.allow_short": False,
            "strategy_params.long_symbols": ["sol"],
            "strategy_params.short_symbols": [],
            "mean_reversion.enabled": False,
            "filters.adx_floor": 99,
            "strategy_params.breakout_atr_buffer": 9.0,
            "strategy_params.cooldown_bars": 6,
            "sr_entries.enabled": True,
            "sr_entries.symbols": ["sol"],
            "sr_entries.lookback_4h": 24,
            "sr_entries.zone_atr_mult": 0.28,
            "sr_entries.use_adx_filter": True,
            "sr_entries.adx_min": 0.0,
            "sr_entries.adx_max": 26.0,
            "sr_entries.stake_scale": 0.50,
            "sr_entries.cooldown_bars": 6,
            "sr_entries.require_compress_ok": True,
        },
    ),
    (
        "sol_long_core_adx28_cd6_lb22_zone027_s038",
        {
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
    ),
    (
        "sol_long_core_adx28_cd6_lb22_zone027_s045",
        {
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
            "sr_entries.stake_scale": 0.45,
            "sr_entries.cooldown_bars": 6,
            "sr_entries.require_compress_ok": True,
        },
    ),
    (
        "sol_long_core_adx28_cd5_lb22_zone027_s050",
        {
            "strategy_params.allow_short": False,
            "strategy_params.long_symbols": ["sol"],
            "strategy_params.short_symbols": [],
            "mean_reversion.enabled": False,
            "filters.adx_floor": 99,
            "strategy_params.breakout_atr_buffer": 9.0,
            "strategy_params.cooldown_bars": 5,
            "sr_entries.enabled": True,
            "sr_entries.symbols": ["sol"],
            "sr_entries.lookback_4h": 22,
            "sr_entries.zone_atr_mult": 0.27,
            "sr_entries.use_adx_filter": True,
            "sr_entries.adx_min": 0.0,
            "sr_entries.adx_max": 28.0,
            "sr_entries.stake_scale": 0.50,
            "sr_entries.cooldown_bars": 5,
            "sr_entries.require_compress_ok": True,
        },
    ),
    (
        "sol_long_core_adx30_cd5_lb20_zone026_s055",
        {
            "strategy_params.allow_short": False,
            "strategy_params.long_symbols": ["sol"],
            "strategy_params.short_symbols": [],
            "mean_reversion.enabled": False,
            "filters.adx_floor": 99,
            "strategy_params.breakout_atr_buffer": 9.0,
            "strategy_params.cooldown_bars": 5,
            "sr_entries.enabled": True,
            "sr_entries.symbols": ["sol"],
            "sr_entries.lookback_4h": 20,
            "sr_entries.zone_atr_mult": 0.26,
            "sr_entries.use_adx_filter": True,
            "sr_entries.adx_min": 0.0,
            "sr_entries.adx_max": 30.0,
            "sr_entries.stake_scale": 0.55,
            "sr_entries.cooldown_bars": 5,
            "sr_entries.require_compress_ok": True,
        },
    ),
]


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage49 aggressive sprint lab")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--txt-out", default="")
    ap.add_argument("--json-out", default="")
    ap.add_argument("--start", default="")
    ap.add_argument("--end", default="")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    cfg = read_config(root / "config.yml")
    reports_raw = root / "reports" / "research_raw"
    txt_out = Path(args.txt_out).expanduser().resolve() if args.txt_out else reports_raw / "stage49_aggressive_sprint_latest.txt"
    json_out = Path(args.json_out).expanduser().resolve() if args.json_out else reports_raw / "stage49_aggressive_sprint_latest.json"

    portfolio_cfg = copy.deepcopy(cfg)
    portfolio_cfg.setdefault("data", {})["symbols"] = ["btc", "bnb"]
    portfolio_data = s46._load_portfolio_data(root, portfolio_cfg, start=args.start, end=args.end)

    main_rows: list[dict[str, Any]] = []
    for name, mods in MAIN_VARIANTS:
        row = s46._run_portfolio_variant(root, portfolio_cfg, portfolio_data, name, mods)
        row["score"] = 0.0
        row["gate"] = ""
        main_rows.append(row)
    ref_main = next((r for r in main_rows if r["name"] == "combo_sr_soft_adx26_cd6_lb24_zone028_ref"), main_rows[0])
    for row in main_rows:
        row["score"] = _main_score(row, ref_main)
        row["gate"] = _gate_main(row, ref_main)
    main_sorted = sorted(main_rows, key=lambda r: (r["gate"] == "pass", r["gate"] == "hold", r["score"], r["trades"], r["pf"], r["ret"]), reverse=True)
    best_main = next((r for r in main_sorted if r["gate"] in {"pass", "hold"} and r["name"] != ref_main["name"]), ref_main)

    branch_rows: list[dict[str, Any]] = []
    for name, mods in BRANCH_VARIANTS:
        row = s46._run_symbol_variant(root, cfg, "sol", name, mods, start=args.start, end=args.end)
        row["score"] = _branch_score(row)
        row["gate"] = _gate_branch(row)
        branch_rows.append(row)
    branch_sorted = sorted(branch_rows, key=lambda r: (r["gate"] == "pass", r["gate"] == "hold", r["score"], r["pf"], r["ret"]), reverse=True)
    best_branch = next((r for r in branch_sorted if r["gate"] in {"pass", "hold"}), branch_sorted[0] if branch_sorted else None)

    lines: list[str] = []
    lines.append("Stage49 激进冲刺实验")
    lines.append(f"version: {cfg.get('system', {}).get('version', 'NA')}")
    if args.start or args.end:
        lines.append(f"range: {args.start or '-'} -> {args.end or '-'}")
    lines.append("")
    lines.append("=== 主线（围绕 stage48 平衡候选继续冲频次） ===")
    for row in main_sorted:
        m = row.get("monthly", {}) or {}
        lines.append(
            f"- {row['name']}: gate={row['gate']} | trades={row['trades']} | pf={row['pf']:.3f} | ret={_fmt_pct(row['ret'])} | maxDD={_fmt_pct(row['maxdd'])} | active_months={m.get('active_months',0)} | months>=20%={m.get('months_ge_20',0)} | roll12_pf_floor={row.get('rolling12_pf_floor',0.0):.3f} | score={row['score']:+.2f}"
        )
        lines.append(
            f"  seg_pf=2020-2021:{row['seg_pf']['2020_2021']:.3f} / 2022-2023:{row['seg_pf']['2022_2023']:.3f} / 2024-2026:{row['seg_pf']['2024_2026']:.3f} | counts={json.dumps(row.get('counts', {}), ensure_ascii=False)}"
        )
    lines.append("")
    lines.append("=== SOL long core（结构提速 + 仓位梯度） ===")
    for row in branch_sorted:
        m = row.get("monthly", {}) or {}
        lines.append(
            f"- {row['name']}: gate={row['gate']} | trades={row['trades']} | pf={row['pf']:.3f} | ret={_fmt_pct(row['ret'])} | maxDD={_fmt_pct(row['maxdd'])} | median_month={_fmt_pct(m.get('monthly_median',0.0))} | p75_month={_fmt_pct(m.get('monthly_p75',0.0))} | months>=20%={m.get('months_ge_20',0)} | roll12_pf_floor={row.get('rolling12_pf_floor',0.0):.3f} | score={row['score']:+.2f}"
        )
        lines.append(f"  counts={json.dumps(row.get('counts', {}), ensure_ascii=False)}")
    lines.append("")
    lines.append("=== 结论 ===")
    lines.append(f"- 主线当前第一候选：{best_main['name']}。")
    if best_branch is not None:
        lines.append(f"- SOL 当前第一候选：{best_branch['name']}。")
    lines.append("- 这轮把重点从 short shock 暂时移开，先验证 long core 能否靠结构 + 仓位梯度把月度爆发抬起来。")
    lines.append("- 若主线 220 笔附近仍守住 PF / DD，再考虑做更严格 walk-forward；未通过前不改 live。")
    lines.append("- 若 SOL aggressive 版本仍无法明显增加 months>=20%，就把月化 20% 继续视作挑战目标，不为它硬冲过拟合。")

    payload = {
        "system_version": cfg.get("system", {}).get("version", "NA"),
        "range": {"start": args.start, "end": args.end},
        "mainline": {"reference": ref_main, "best": best_main, "rows": main_sorted},
        "sol": {"best": best_branch, "rows": branch_sorted},
        "notes": {
            "goal": "aggressive first, then tighten",
            "mainline_target": "push toward 220+ trades while keeping PF/DD acceptable",
            "sol_target": "raise monthly bursts via structure plus stake ladder",
            "eth": "overlay_only",
            "polymarket": "regime_prior_only",
        },
    }

    _write_text(txt_out, "\n".join(lines))
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
