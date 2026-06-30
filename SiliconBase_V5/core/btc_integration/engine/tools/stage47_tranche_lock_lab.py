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


def _main_score(row: dict[str, Any]) -> float:
    # higher better; very simple ranking for this lab
    return float(
        row.get("pf", 0.0) * 60.0
        + row.get("ret", 0.0) * 5.0
        - abs(row.get("maxdd", 0.0)) * 120.0
        + row.get("trades", 0) * 0.15
        + row.get("monthly", {}).get("months_ge_20", 0) * 2.0
        + min(row.get("rolling12_pf_floor", 0.0), 2.0) * 10.0
    )


def _branch_score(row: dict[str, Any]) -> float:
    return float(
        row.get("pf", 0.0) * 85.0
        + row.get("ret", 0.0) * 25.0
        - abs(row.get("maxdd", 0.0)) * 90.0
        + row.get("trades", 0) * 0.35
        + row.get("monthly", {}).get("months_ge_20", 0) * 8.0
        + row.get("monthly", {}).get("monthly_p75", 0.0) * 25.0
    )


def _run_port(root: Path, base_cfg: dict[str, Any], data: dict[str, Any], name: str, mods: dict[str, Any]) -> dict[str, Any]:
    row = s46._run_portfolio_variant(root, base_cfg, data, name, mods)
    row["score"] = _main_score(row)
    return row


def _run_symbol(root: Path, base_cfg: dict[str, Any], symbol: str, name: str, mods: dict[str, Any]) -> dict[str, Any]:
    row = s46._run_symbol_variant(root, base_cfg, symbol, name, mods)
    row["score"] = _branch_score(row)
    return row


def _main_variants() -> list[tuple[str, dict[str, Any]]]:
    ref = dict(s46.REF_MAIN_MODS)
    adx26_cd6 = {**ref, "sr_entries.adx_max": 26.0, "sr_entries.cooldown_bars": 6}
    # 用户提议：固定金额分仓 + 盈利后尽快锁盈；这里只做 research，不改 live
    fix8_lock08_tp18 = {
        "money_management.capital_slices": 8,
        "money_management.stake_mode": "fixed",
        "money_management.stake_usd": 12500,
        "money_management.take_profit_pct": 1.8,
        "money_management.trailing_profit.activation_pnl_pct": 0.8,
        "money_management.trailing_profit.giveback_ratio": 0.40,
        "money_management.trailing_profit.min_lock_pnl_pct": 0.20,
    }
    fix10_lock05_tp0 = {
        "money_management.capital_slices": 10,
        "money_management.stake_mode": "fixed",
        "money_management.stake_usd": 10000,
        "money_management.take_profit_pct": 0.0,
        "money_management.trailing_profit.activation_pnl_pct": 0.5,
        "money_management.trailing_profit.giveback_ratio": 0.55,
        "money_management.trailing_profit.min_lock_pnl_pct": 0.10,
    }
    return [
        ("combo_sr_soft_ref", ref),
        ("combo_sr_soft_adx26_cd6", adx26_cd6),
        ("combo_sr_soft_ref_fix8_lock08_tp18", {**ref, **fix8_lock08_tp18}),
        ("combo_sr_soft_adx26_cd6_fix8_lock08_tp18", {**adx26_cd6, **fix8_lock08_tp18}),
        ("combo_sr_soft_ref_fix10_lock05_tp0", {**ref, **fix10_lock05_tp0}),
    ]


def _branch_variants() -> list[tuple[str, dict[str, Any]]]:
    sol_adx24 = next(mods for sym, name, mods in s46.BRANCH_VARIANTS if name == "sol_long_core_adx24")
    sol_fast = next(mods for sym, name, mods in s46.BRANCH_VARIANTS if name == "sol_long_core_fast")
    fix8_lock08_tp18 = {
        "money_management.capital_slices": 8,
        "money_management.stake_mode": "fixed",
        "money_management.stake_usd": 12500,
        "money_management.take_profit_pct": 1.8,
        "money_management.trailing_profit.activation_pnl_pct": 0.8,
        "money_management.trailing_profit.giveback_ratio": 0.40,
        "money_management.trailing_profit.min_lock_pnl_pct": 0.20,
    }
    return [
        ("sol_long_core_adx24", sol_adx24),
        ("sol_long_core_fast", sol_fast),
        ("sol_long_core_adx24_fix8_lock08_tp18", {**sol_adx24, **fix8_lock08_tp18}),
        ("sol_long_core_fast_fix8_lock08_tp18", {**sol_fast, **fix8_lock08_tp18}),
    ]


def _render(rows_main: list[dict[str, Any]], rows_sol: list[dict[str, Any]], project_version: str) -> str:
    lines: list[str] = []
    lines.append("Stage47 固定分仓 + 盈利锁盈实验")
    lines.append(f"version: {project_version}")
    lines.append("")
    lines.append("=== 主线（用户提议：5-10 份固定金额 + 盈利后尽快上移止损） ===")
    for row in rows_main:
        m = row.get("monthly", {}) or {}
        lines.append(
            f"- {row['name']}: trades={row['trades']} | pf={row['pf']:.3f} | ret={_fmt_pct(row['ret'])} | "
            f"maxDD={_fmt_pct(row['maxdd'])} | active_months={m.get('active_months', 0)} | "
            f"months>=20%={m.get('months_ge_20', 0)} | roll12_pf_floor={row.get('rolling12_pf_floor', 0.0):.3f} | score={row.get('score', 0.0):+.2f}"
        )
        seg = row.get("seg_pf", {}) or {}
        lines.append(
            f"  seg_pf=2020-2021:{seg.get('2020_2021', 0.0):.3f} / 2022-2023:{seg.get('2022_2023', 0.0):.3f} / 2024-2026:{seg.get('2024_2026', 0.0):.3f}"
        )
    lines.append("")
    lines.append("=== 分支（SOL long core） ===")
    for row in rows_sol:
        m = row.get("monthly", {}) or {}
        lines.append(
            f"- {row['name']}: trades={row['trades']} | pf={row['pf']:.3f} | ret={_fmt_pct(row['ret'])} | "
            f"maxDD={_fmt_pct(row['maxdd'])} | months>=20%={m.get('months_ge_20', 0)} | "
            f"p75_month={_fmt_pct(m.get('monthly_p75', 0.0))} | roll12_pf_floor={row.get('rolling12_pf_floor', 0.0):.3f} | score={row.get('score', 0.0):+.2f}"
        )
    lines.append("")
    best_main = max(rows_main, key=lambda x: float(x.get("score", 0.0))) if rows_main else None
    best_sol = max(rows_sol, key=lambda x: float(x.get("score", 0.0))) if rows_sol else None
    lines.append("=== 结论 ===")
    if best_main is not None:
        lines.append(f"- 主线当前最值得继续保留的仍是：{best_main['name']}。")
    if best_sol is not None:
        lines.append(f"- SOL 当前更值得继续推进的是：{best_sol['name']}。")
    # direct conclusion for user proposal
    bad_main = [r for r in rows_main if "fix" in r["name"] and r.get("pf", 0.0) < 1.20]
    if bad_main:
        lines.append("- 固定分仓 + 早锁盈 直接套到主线，会明显压缩收益质量；这更像执行层风控，不适合直接当主线提频解法。")
    better_dd_sol = [r for r in rows_sol if "fix" in r["name"] and abs(r.get("maxdd", 0.0)) < 0.20]
    if better_dd_sol:
        lines.append("- 固定分仓 + 锁盈 在 SOL long 上能明显降回撤，但会压缩月度爆发；可留作后续 live 执行风控候选。")
    lines.append("- 下一步仍应分开做：主线继续提频；SOL 继续 long core；short shock 先不升级。")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage47 tranche/lock research")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    cfg = read_config(root / "config.yml")
    version = str(cfg.get("meta", {}).get("version", "")) or str(cfg.get("version", "unknown"))
    data = s46._load_portfolio_data(root, cfg)

    rows_main = [_run_port(root, cfg, data, name, mods) for name, mods in _main_variants()]
    rows_main.sort(key=lambda x: float(x.get("score", 0.0)), reverse=True)

    rows_sol = [_run_symbol(root, cfg, "sol", name, mods) for name, mods in _branch_variants()]
    rows_sol.sort(key=lambda x: float(x.get("score", 0.0)), reverse=True)

    out_dir = root / "reports" / "research_raw"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "stage47_tranche_lock_lab_latest.json").write_text(
        json.dumps({"mainline": rows_main, "sol": rows_sol}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_dir / "stage47_tranche_lock_lab_latest.txt").write_text(
        _render(rows_main, rows_sol, version),
        encoding="utf-8",
    )
    print(str(out_dir / "stage47_tranche_lock_lab_latest.txt"))


if __name__ == "__main__":
    main()
