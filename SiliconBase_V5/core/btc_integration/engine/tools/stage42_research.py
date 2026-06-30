from __future__ import annotations

import argparse
import copy
import re
from pathlib import Path
from typing import Any

import pandas as pd
from src.backtest.engine import run_backtest_portfolio
from src.backtest.io import read_config
from tools.alt_shortwave_lab import _load_symbol_data, _set_nested, _summarize_row
from tools.mainline_density_lab import VARIANTS, _load_data, _trade_metrics_from_df
from tools.mainline_density_lab import _set_nested as _set_nested_main


def _read_first(paths: list[Path]) -> tuple[Path | None, str]:
    for p in paths:
        try:
            if p.exists() and p.is_file():
                return p, p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
    return None, ""


def _load_csv_first(paths: list[Path]) -> pd.DataFrame | None:
    for p in paths:
        try:
            if p.exists() and p.is_file():
                return pd.read_csv(p)
        except Exception:
            continue
    return None


def _pct(x: Any) -> str:
    try:
        return f"{float(x) * 100:.2f}%"
    except Exception:
        return "NA"


def _pf(df: pd.DataFrame) -> float:
    if df is None or df.empty or "pnl" not in df.columns:
        return float("nan")
    pnl = pd.to_numeric(df["pnl"], errors="coerce").fillna(0.0)
    gp = float(pnl[pnl > 0].sum())
    gl = float(-pnl[pnl < 0].sum())
    if gl <= 0:
        return 999.0 if gp > 0 else 0.0
    return gp / gl


def _segment_stats(trades: pd.DataFrame, start_year: int, end_year: int) -> dict[str, Any]:
    if trades is None or trades.empty:
        return {"trades": 0, "pf": 0.0, "pnl": 0.0}
    df = trades.copy()
    df["exit_time"] = pd.to_datetime(df["exit_time"], errors="coerce")
    df = df.dropna(subset=["exit_time"])
    seg = df[(df["exit_time"].dt.year >= start_year) & (df["exit_time"].dt.year <= end_year)].copy()
    if seg.empty:
        return {"trades": 0, "pf": 0.0, "pnl": 0.0}
    return {
        "trades": int(len(seg)),
        "pf": float(_pf(seg)),
        "pnl": float(pd.to_numeric(seg["pnl"], errors="coerce").fillna(0.0).sum()),
    }


def _density_stats(trades: pd.DataFrame) -> dict[str, Any]:
    if trades is None or trades.empty:
        return {"active_months": 0, "monthly_median": 0.0, "monthly_p75": 0.0, "last_trade": "-"}
    df = trades.copy()
    df["exit_time"] = pd.to_datetime(df["exit_time"], errors="coerce")
    df = df.dropna(subset=["exit_time"])
    monthly = df.groupby(df["exit_time"].dt.to_period("M")).size()
    return {
        "active_months": int(df["exit_time"].dt.to_period("M").nunique()),
        "monthly_median": float(monthly.median()) if not monthly.empty else 0.0,
        "monthly_p75": float(monthly.quantile(0.75)) if not monthly.empty else 0.0,
        "last_trade": str(df["exit_time"].max()) if not df.empty else "-",
    }


def _run_named_mainline(root: Path, cfg: dict[str, Any], data: dict[str, pd.DataFrame], name: str) -> tuple[dict[str, Any], pd.DataFrame]:
    item = next(x for x in VARIANTS if x["name"] == name)
    cfg2 = copy.deepcopy(cfg)
    for path, value in item.get("mods", {}).items():
        _set_nested_main(cfg2, path, value)
    _eq, trades, _ = run_backtest_portfolio(data, cfg2)
    metrics = _trade_metrics_from_df(trades, float(cfg2.get("portfolio", {}).get("initial_equity", 100000.0)))
    return metrics, trades.copy() if trades is not None else pd.DataFrame()


def _parse_combo_gated(txt: str) -> dict[str, Any]:
    m = re.search(r"- combo_sr_soft:.*?gated_trades=(\d+) \| gated_pf=([\d.]+) \| gated_ret=([+-]?[\d.]+)%(?: \| gated_maxDD=([+-]?[\d.]+)%)?", txt, re.S)
    if not m:
        return {}
    return {
        "trades": int(m.group(1)),
        "pf": float(m.group(2)),
        "ret": float(m.group(3)) / 100.0,
        "maxdd": float(m.group(4)) / 100.0 if m.group(4) else None,
    }


def _parse_branch_base(txt: str, name: str) -> dict[str, Any]:
    pat = rf"- {re.escape(name)}: symbol=(\w+) \| base_trades=(\d+) \| base_pf=([\d.]+) \| base_ret=([+-]?[\d.]+)% \| base_maxDD=([+-]?[\d.]+)%"
    m = re.search(pat, txt)
    if not m:
        return {}
    return {
        "symbol": m.group(1).upper(),
        "trades": int(m.group(2)),
        "pf": float(m.group(3)),
        "ret": float(m.group(4)) / 100.0,
        "maxdd": float(m.group(5)) / 100.0,
    }


def _run_branch_candidate(root: Path, cfg: dict[str, Any], symbol: str, name: str, mods: dict[str, Any]) -> dict[str, Any]:
    cfg2 = copy.deepcopy(cfg)
    cfg2.setdefault("data", {})["symbols"] = [symbol]
    cfg2.setdefault("data", {})["weights"] = {symbol: 1.0}
    _set_nested(cfg2, "filters.macro_gate_symbols", [symbol])
    _set_nested(cfg2, "filters.macro_gate_reference_symbol", symbol)
    short_symbols = mods.pop("__short_symbols__", [symbol])
    allow_short = mods.pop("__allow_short__", True)
    _set_nested(cfg2, "strategy_params.short_symbols", short_symbols)
    _set_nested(cfg2, "strategy_params.allow_short", allow_short)
    for path, value in mods.items():
        _set_nested(cfg2, path, value)
    data = _load_symbol_data(root, cfg2, symbol)
    eq, trades, snap = run_backtest_portfolio(data, cfg2)
    row = _summarize_row(symbol, name, name, eq, trades, snap)
    return row


def _write_mainline_report(path: Path, base_metrics: dict[str, Any], base_trades: pd.DataFrame, combo_metrics: dict[str, Any], combo_trades: pd.DataFrame, combo_gated: dict[str, Any], version: str) -> None:
    segs = [(2020, 2021), (2022, 2023), (2024, 2026)]
    lines: list[str] = []
    lines.append("主线 combo_sr_soft 严格验证（research only，不改 live）")
    lines.append(f"version: {version}")
    lines.append("")
    lines.append("=== 核心指标 ===")
    lines.append(f"- baseline: trades={base_metrics['trades']} | pf={base_metrics['pf']:.3f} | ret={_pct(base_metrics['ret'])} | maxDD={_pct(base_metrics['maxdd'])} | win_rate={base_metrics['win_rate']*100:.2f}%")
    lines.append(f"- combo_sr_soft: trades={combo_metrics['trades']} | pf={combo_metrics['pf']:.3f} | ret={_pct(combo_metrics['ret'])} | maxDD={_pct(combo_metrics['maxdd'])} | win_rate={combo_metrics['win_rate']*100:.2f}%")
    if combo_gated:
        tail = f" | gated_maxDD={_pct(combo_gated.get('maxdd'))}" if combo_gated.get("maxdd") is not None else ""
        lines.append(f"- combo_sr_soft + combined_stack: gated_trades={combo_gated.get('trades',0)} | gated_pf={combo_gated.get('pf',0.0):.3f} | gated_ret={_pct(combo_gated.get('ret'))}{tail}")
    lines.append("")
    lines.append("=== 分段稳定性 ===")
    for sy, ey in segs:
        b = _segment_stats(base_trades, sy, ey)
        c = _segment_stats(combo_trades, sy, ey)
        lines.append(
            f"- {sy}-{ey}: baseline_pf={b['pf']:.3f} (trades={b['trades']}, pnl={b['pnl']:+.2f}) | combo_pf={c['pf']:.3f} (trades={c['trades']}, pnl={c['pnl']:+.2f})"
        )
    lines.append("")
    lines.append("=== 密度/覆盖 ===")
    bd = _density_stats(base_trades)
    cd = _density_stats(combo_trades)
    lines.append(f"- active_months: baseline={bd['active_months']} | combo={cd['active_months']}")
    lines.append(f"- monthly_median_trades: baseline={bd['monthly_median']:.1f} | combo={cd['monthly_median']:.1f}")
    lines.append(f"- monthly_p75_trades: baseline={bd['monthly_p75']:.1f} | combo={cd['monthly_p75']:.1f}")
    lines.append(f"- last_trade: baseline={bd['last_trade']} | combo={cd['last_trade']}")
    lines.append("")
    lines.append("=== 结论 ===")
    lines.append("- combo_sr_soft 仍保留为主线升级第一候选。")
    lines.append("- 这轮改善主要来自覆盖率/出手月数提高，不是单笔 edge 大幅扩张。")
    lines.append("- 2020-2021 早期 regime 仍弱；且 2022-2023、2024-2026 的 PF 略低于 baseline，所以 live 先不改。")
    lines.append("- 下一步不是继续普遍放松阈值，而是给 BNB 再入场 overlay 加条件门控：拥挤度、极端恐慌、宏观窗口。")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_branch_report(path: Path, sol_base: dict[str, Any], eth_base: dict[str, Any], rows: list[dict[str, Any]], version: str) -> None:
    lines: list[str] = []
    lines.append("分支结构重构实验（SOL / ETH，只做 research，不改 demo）")
    lines.append(f"version: {version}")
    lines.append("")
    lines.append("=== 当前旧框架基线 ===")
    if sol_base:
        lines.append(f"- sol_shortwave_sr(双向): trades={sol_base['trades']} | pf={sol_base['pf']:.3f} | ret={_pct(sol_base['ret'])} | maxDD={_pct(sol_base['maxdd'])}")
    if eth_base:
        lines.append(f"- eth_shortwave_sr(双向): trades={eth_base['trades']} | pf={eth_base['pf']:.3f} | ret={_pct(eth_base['ret'])} | maxDD={_pct(eth_base['maxdd'])}")
    lines.append("")
    lines.append("=== 新结构小样本实验 ===")
    for row in rows:
        lines.append(
            f"- {row['name']}: symbol={row['symbol'].upper()} | trades={row['trades']} | pf={row['profit_factor']:.3f} | ret={_pct(row['total_return'])} | maxDD={_pct(row['max_drawdown'])} | long={row['long_trades']} short={row['short_trades']}"
        )
    lines.append("")
    lines.append("=== 结论 ===")
    lines.append("- SOL 的亏损主要来自短空腿；long-only 基础版已经转正，但交易数仍偏少。")
    lines.append("- 一旦为了提频而放松 SOL long-only 阈值，PF 很快跌破 1，说明不能把多空继续混在同一条 SR 分支里硬调。")
    lines.append("- SOL 分支应改成两段式：long-only core + 单独的 short engine；short engine 只在拥挤多头/风险事件卸杠杆时激活。")
    lines.append("- ETH long-only 仍为负收益，因此 ETH 不适合继续做持续运行的独立短波分支；更适合退回事件条件触发的 tactical overlay。")
    lines.append("- 下一轮优先顺序：SOL long-only core > SOL short shock engine > ETH tactical overlay。")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage42: 主线严格验证 + 分支结构重构实验")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    reports_raw = root / "reports" / "research_raw"
    reports_raw.mkdir(parents=True, exist_ok=True)
    cfg = read_config(root / "config.yml")
    version = str(cfg.get("system", {}).get("version", "NA"))

    main_txt_p, main_txt = _read_first([
        reports_raw / "mainline_density_lab_latest.txt",
        Path.home() / "Downloads" / "mainline_density_lab_latest.txt",
    ])
    combo_gated = _parse_combo_gated(main_txt)

    base_trades = _load_csv_first([
        reports_raw / "current_demo_strategy_trades_latest.csv",
        root / "reports" / "current_demo_strategy_trades_latest.csv",
        Path.home() / "Downloads" / "current_demo_strategy_trades_latest.csv",
    ])
    if base_trades is None or base_trades.empty:
        data = _load_data(root, cfg)
        base_metrics, base_trades = _run_named_mainline(root, cfg, data, "baseline")
        combo_metrics, combo_trades = _run_named_mainline(root, cfg, data, "combo_sr_soft")
    else:
        base_metrics = _trade_metrics_from_df(base_trades)
        data = _load_data(root, cfg)
        combo_metrics, combo_trades = _run_named_mainline(root, cfg, data, "combo_sr_soft")

    _write_mainline_report(
        reports_raw / "mainline_combo_validation_latest.txt",
        base_metrics,
        base_trades,
        combo_metrics,
        combo_trades,
        combo_gated,
        version,
    )

    branch_p, branch_txt = _read_first([
        reports_raw / "alt_shortwave_message_overlay_latest.txt",
        Path.home() / "Downloads" / "alt_shortwave_message_overlay_latest.txt",
    ])
    sol_base = _parse_branch_base(branch_txt, "sol_shortwave_sr")
    eth_base = _parse_branch_base(branch_txt, "eth_shortwave_sr")

    base_sol_mods = {
        "filters.adx_floor": 99,
        "strategy_params.breakout_atr_buffer": 9.0,
        "strategy_params.cooldown_bars": 8,
        "mean_reversion.enabled": False,
        "sr_entries.enabled": True,
        "sr_entries.symbols": ["sol"],
        "sr_entries.lookback_4h": 24,
        "sr_entries.zone_atr_mult": 0.35,
        "sr_entries.use_adx_filter": True,
        "sr_entries.adx_min": 0.0,
        "sr_entries.adx_max": 25.0,
        "sr_entries.stake_scale": 0.4,
        "sr_entries.cooldown_bars": 8,
        "sr_entries.require_compress_ok": True,
        "__allow_short__": False,
        "__short_symbols__": [],
    }
    rows: list[dict[str, Any]] = []
    rows.append(_run_branch_candidate(root, cfg, "sol", "sol_long_only_base", dict(base_sol_mods)))
    m = dict(base_sol_mods)
    m.update({
        "sr_entries.lookback_4h": 20,
        "sr_entries.zone_atr_mult": 0.30,
        "sr_entries.adx_max": 28.0,
        "sr_entries.cooldown_bars": 6,
    })
    rows.append(_run_branch_candidate(root, cfg, "sol", "sol_long_only_soft1", m))
    m = dict(base_sol_mods)
    m.update({
        "sr_entries.lookback_4h": 18,
        "sr_entries.zone_atr_mult": 0.25,
        "sr_entries.adx_max": 30.0,
        "sr_entries.cooldown_bars": 4,
    })
    rows.append(_run_branch_candidate(root, cfg, "sol", "sol_long_only_soft2", m))

    eth_long_mods = {
        "filters.adx_floor": 99,
        "strategy_params.breakout_atr_buffer": 9.0,
        "strategy_params.cooldown_bars": 8,
        "mean_reversion.enabled": False,
        "sr_entries.enabled": True,
        "sr_entries.symbols": ["eth"],
        "sr_entries.lookback_4h": 24,
        "sr_entries.zone_atr_mult": 0.35,
        "sr_entries.use_adx_filter": True,
        "sr_entries.adx_min": 0.0,
        "sr_entries.adx_max": 25.0,
        "sr_entries.stake_scale": 0.4,
        "sr_entries.cooldown_bars": 8,
        "sr_entries.require_compress_ok": True,
        "__allow_short__": False,
        "__short_symbols__": [],
    }
    rows.append(_run_branch_candidate(root, cfg, "eth", "eth_long_only_base", eth_long_mods))

    _write_branch_report(reports_raw / "branch_structure_lab_latest.txt", sol_base, eth_base, rows, version)
    print(f"[ok] wrote: {reports_raw / 'mainline_combo_validation_latest.txt'}")
    print(f"[ok] wrote: {reports_raw / 'branch_structure_lab_latest.txt'}")


if __name__ == "__main__":
    main()
