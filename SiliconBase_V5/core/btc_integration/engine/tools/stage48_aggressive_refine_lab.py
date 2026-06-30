from __future__ import annotations

import argparse
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
    floor_bonus = min(float(row.get("rolling12_pf_floor", 0.0)), 2.0) * 12.0
    return float(trade_gain * 1.55 + active_gain * 2.0 + months20_gain * 2.5 - pf_pen * 60.0 - dd_pen * 150.0 - ret_pen * 5.0 - seg_pen * 9.0 + floor_bonus)


def _branch_score(row: dict[str, Any]) -> float:
    m = row.get("monthly", {}) or {}
    return float(
        row.get("pf", 0.0) * 92.0
        + row.get("ret", 0.0) * 38.0
        - abs(row.get("maxdd", 0.0)) * 78.0
        + row.get("trades", 0) * 0.35
        + m.get("months_ge_20", 0) * 10.0
        + m.get("monthly_p75", 0.0) * 58.0
        + min(row.get("rolling12_pf_floor", 0.0), 2.0) * 12.0
    )


def _gate_main(row: dict[str, Any], ref: dict[str, Any]) -> str:
    if row["name"] == ref["name"]:
        return "ref"
    if (
        row.get("trades", 0) >= ref.get("trades", 0) + 2
        and row.get("pf", 0.0) >= max(2.15, ref.get("pf", 0.0) - 0.18)
        and row.get("ret", 0.0) >= ref.get("ret", 0.0) * 0.95
        and abs(row.get("maxdd", 0.0)) <= abs(ref.get("maxdd", 0.0)) + 0.03
        and row.get("rolling12_pf_floor", 0.0) >= 0.72
    ):
        return "pass"
    if row.get("trades", 0) > ref.get("trades", 0) and row.get("pf", 0.0) >= 2.00 and row.get("rolling12_pf_floor", 0.0) >= 0.68:
        return "hold"
    return "kill"


def _gate_branch(row: dict[str, Any]) -> str:
    if row.get("pf", 0.0) >= 1.20 and row.get("rolling12_pf_floor", 0.0) >= 1.00 and abs(row.get("maxdd", 0.0)) <= 0.30:
        return "pass"
    if row.get("pf", 0.0) >= 1.05 and row.get("trades", 0) >= 18:
        return "hold"
    return "kill"


MAIN_VARIANTS: list[tuple[str, dict[str, Any]]] = [
    (
        "combo_sr_soft_adx26_cd6_ref",
        {
            **s46.REF_MAIN_MODS,
            "sr_entries.adx_max": 26.0,
            "sr_entries.cooldown_bars": 6,
        },
    ),
    (
        "combo_sr_soft_adx26_cd6_lb26",
        {
            **s46.REF_MAIN_MODS,
            "sr_entries.adx_max": 26.0,
            "sr_entries.cooldown_bars": 6,
            "sr_entries.lookback_4h": 26,
        },
    ),
    (
        "combo_sr_soft_adx26_cd6_lb24_zone028",
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
        "combo_sr_soft_adx26_cd5_lb24_zone027",
        {
            **s46.REF_MAIN_MODS,
            "sr_entries.adx_max": 26.0,
            "sr_entries.cooldown_bars": 5,
            "sr_entries.lookback_4h": 24,
            "sr_entries.zone_atr_mult": 0.27,
        },
    ),
    (
        "combo_sr_soft_adx26_cd6_no_compress_lb24",
        {
            **s46.REF_MAIN_MODS,
            "sr_entries.adx_max": 26.0,
            "sr_entries.cooldown_bars": 6,
            "sr_entries.lookback_4h": 24,
            "sr_entries.require_compress_ok": False,
        },
    ),
    ("combo_sr_soft_ref", dict(s46.REF_MAIN_MODS)),
]


BRANCH_VARIANTS: list[tuple[str, dict[str, Any]]] = [
    (
        "sol_long_core_adx24_ref",
        {
            "strategy_params.allow_short": False,
            "strategy_params.long_symbols": ["sol"],
            "strategy_params.short_symbols": [],
            "mean_reversion.enabled": False,
            "filters.adx_floor": 99,
            "strategy_params.breakout_atr_buffer": 9.0,
            "strategy_params.cooldown_bars": 8,
            "sr_entries.enabled": True,
            "sr_entries.symbols": ["sol"],
            "sr_entries.lookback_4h": 30,
            "sr_entries.zone_atr_mult": 0.30,
            "sr_entries.use_adx_filter": True,
            "sr_entries.adx_min": 0.0,
            "sr_entries.adx_max": 24.0,
            "sr_entries.stake_scale": 0.32,
            "sr_entries.cooldown_bars": 8,
            "sr_entries.require_compress_ok": True,
        },
    ),
    (
        "sol_long_core_fast_ref",
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
            "sr_entries.adx_max": 24.0,
            "sr_entries.stake_scale": 0.35,
            "sr_entries.cooldown_bars": 6,
            "sr_entries.require_compress_ok": True,
        },
    ),
    (
        "sol_long_core_softplus",
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
            "sr_entries.lookback_4h": 26,
            "sr_entries.zone_atr_mult": 0.29,
            "sr_entries.use_adx_filter": True,
            "sr_entries.adx_min": 0.0,
            "sr_entries.adx_max": 24.0,
            "sr_entries.stake_scale": 0.34,
            "sr_entries.cooldown_bars": 6,
            "sr_entries.require_compress_ok": True,
        },
    ),
    (
        "sol_long_core_adx26_cd6",
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
        "sol_long_core_adx26_cd5_fireguard",
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
            "sr_entries.adx_max": 26.0,
            "sr_entries.stake_scale": 0.40,
            "sr_entries.cooldown_bars": 5,
            "sr_entries.require_compress_ok": True,
        },
    ),
    (
        "sol_long_core_lb24_no_compress",
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
            "sr_entries.adx_max": 24.0,
            "sr_entries.stake_scale": 0.36,
            "sr_entries.cooldown_bars": 6,
            "sr_entries.require_compress_ok": False,
        },
    ),
]


def _render(rows_main: list[dict[str, Any]], rows_sol: list[dict[str, Any]], version: str, start: str, end: str) -> str:
    lines: list[str] = []
    lines.append("Stage48 激进提频精修实验")
    lines.append(f"version: {version}")
    if start or end:
        lines.append(f"range: {start or '-'} -> {end or '-'}")
    lines.append("")
    lines.append("=== 主线（围绕 combo_sr_soft_adx26_cd6 继续提频） ===")
    for row in rows_main:
        m = row.get("monthly", {}) or {}
        lines.append(
            f"- {row['name']}: gate={row['gate']} | trades={row['trades']} | pf={row['pf']:.3f} | ret={_fmt_pct(row['ret'])} | maxDD={_fmt_pct(row['maxdd'])} | active_months={m.get('active_months', 0)} | months>=20%={m.get('months_ge_20', 0)} | roll12_pf_floor={row.get('rolling12_pf_floor', 0.0):.3f} | score={row.get('score', 0.0):+.2f}"
        )
        seg = row.get("seg_pf", {}) or {}
        lines.append(
            f"  seg_pf=2020-2021:{seg.get('2020_2021', 0.0):.3f} / 2022-2023:{seg.get('2022_2023', 0.0):.3f} / 2024-2026:{seg.get('2024_2026', 0.0):.3f} | counts={json.dumps(row.get('counts', {}), ensure_ascii=False)}"
        )
    lines.append("")
    lines.append("=== 分支（SOL long core 冲效率） ===")
    for row in rows_sol:
        m = row.get("monthly", {}) or {}
        lines.append(
            f"- {row['name']}: gate={row['gate']} | trades={row['trades']} | pf={row['pf']:.3f} | ret={_fmt_pct(row['ret'])} | maxDD={_fmt_pct(row['maxdd'])} | median_month={_fmt_pct(m.get('monthly_median', 0.0))} | p75_month={_fmt_pct(m.get('monthly_p75', 0.0))} | months>=20%={m.get('months_ge_20', 0)} | roll12_pf_floor={row.get('rolling12_pf_floor', 0.0):.3f} | score={row.get('score', 0.0):+.2f}"
        )
        lines.append(f"  counts={json.dumps(row.get('counts', {}), ensure_ascii=False)}")
    lines.append("")
    best_main = next((r for r in rows_main if r.get("gate") in {"pass", "hold"}), rows_main[0] if rows_main else None)
    best_sol = next((r for r in rows_sol if r.get("gate") in {"pass", "hold"}), rows_sol[0] if rows_sol else None)
    lines.append("=== 结论 ===")
    if best_main is not None:
        lines.append(f"- 主线当前第一候选：{best_main['name']}。")
    if best_sol is not None:
        lines.append(f"- SOL 当前第一候选：{best_sol['name']}。")
    lines.append("- 固定分仓 + 早锁盈继续只留在执行层风控，不把它当主线提频主解。")
    lines.append("- 若 SOL aggressive 版本仍上不去，就保留 long core，不强行冲 short shock。")
    lines.append("- 这轮仍只做 research，不改 live。")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage48 aggressive refine lab")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--start", default="")
    ap.add_argument("--end", default="")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    cfg = read_config(root / "config.yml")
    version = str(cfg.get("system", {}).get("version", "NA"))

    portfolio_cfg = dict(cfg)
    portfolio_cfg.setdefault("data", {})["symbols"] = ["btc", "bnb"]
    portfolio_data = s46._load_portfolio_data(root, portfolio_cfg, start=args.start, end=args.end)

    main_rows: list[dict[str, Any]] = []
    for name, mods in MAIN_VARIANTS:
        row = s46._run_portfolio_variant(root, portfolio_cfg, portfolio_data, name, mods)
        main_rows.append(row)
    ref_main = next((r for r in main_rows if r["name"] == "combo_sr_soft_adx26_cd6_ref"), main_rows[0])
    for row in main_rows:
        row["score"] = _main_score(row, ref_main)
        row["gate"] = _gate_main(row, ref_main)
    main_rows.sort(key=lambda r: (r["gate"] == "pass", r["gate"] == "hold", r["score"], r["pf"], r["ret"]), reverse=True)

    sol_rows: list[dict[str, Any]] = []
    for name, mods in BRANCH_VARIANTS:
        row = s46._run_symbol_variant(root, cfg, "sol", name, mods, start=args.start, end=args.end)
        row["score"] = _branch_score(row)
        row["gate"] = _gate_branch(row)
        sol_rows.append(row)
    sol_rows.sort(key=lambda r: (r["gate"] == "pass", r["gate"] == "hold", r["score"], r["pf"], r["ret"]), reverse=True)

    out_dir = root / "reports" / "research_raw"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "stage48_aggressive_refine_lab_latest.json").write_text(
        json.dumps(
            {
                "system_version": version,
                "range": {"start": args.start, "end": args.end},
                "mainline": {"reference": ref_main, "rows": main_rows},
                "sol": {"rows": sol_rows},
                "notes": {
                    "goal": "aggressive first, but keep PF/DD usable",
                    "fixed_tranche_lock": "execution layer only",
                    "eth": "overlay_only",
                    "polymarket": "risk_gate_only",
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (out_dir / "stage48_aggressive_refine_lab_latest.txt").write_text(
        _render(main_rows, sol_rows, version, args.start, args.end),
        encoding="utf-8",
    )
    print(str(out_dir / "stage48_aggressive_refine_lab_latest.txt"))


if __name__ == "__main__":
    main()
