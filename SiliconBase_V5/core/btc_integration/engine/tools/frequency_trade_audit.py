from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _median_or_zero(values: list[float]) -> float:
    return float(median(values)) if values else 0.0


def _mean_or_zero(values: list[float]) -> float:
    return float(mean(values)) if values else 0.0


def _period_month(dt: datetime) -> str:
    return dt.strftime("%Y-%m")


def _months_between(start: datetime, end: datetime) -> list[str]:
    months: list[str] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append(f"{y:04d}-{m:02d}")
        if m == 12:
            y += 1
            m = 1
        else:
            m += 1
    return months


def _load_yaml(path: Path) -> dict[str, Any]:
    if yaml is None:
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


@dataclass
class TradeRow:
    symbol: str
    side: str
    entry_time: datetime
    exit_time: datetime | None
    pnl: float
    bars_held: float


def _load_trades(path: Path) -> list[TradeRow]:
    rows: list[TradeRow] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            entry_time = _parse_dt(r.get("entry_time"))
            if entry_time is None:
                continue
            exit_time = _parse_dt(r.get("exit_time"))
            try:
                pnl = float(r.get("pnl", "0") or 0)
            except Exception:
                pnl = 0.0
            try:
                bars_held = float(r.get("bars_held", "0") or 0)
            except Exception:
                bars_held = 0.0
            rows.append(
                TradeRow(
                    symbol=(r.get("symbol") or "").strip().lower(),
                    side=(r.get("side") or "").strip().upper(),
                    entry_time=entry_time,
                    exit_time=exit_time,
                    pnl=pnl,
                    bars_held=bars_held,
                )
            )
    rows.sort(key=lambda x: x.entry_time)
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("project_dir", nargs="?", default=".", help="项目根目录")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    reports = root / "reports"
    reports.mkdir(parents=True, exist_ok=True)

    metrics_path = reports / "metrics_latest.json"
    if not metrics_path.exists():
        metrics_path = root / "metrics_latest.json"

    candidate_run_dirs = [reports / "run_latest", root / "run_latest"]
    candidate_run_dirs.extend(sorted(reports.glob("run_*"), key=lambda p: p.stat().st_mtime, reverse=True))
    candidate_run_dirs.extend(sorted(root.glob("run_*"), key=lambda p: p.stat().st_mtime, reverse=True))

    trades_path = None
    for cand in candidate_run_dirs:
        cand_trades = cand / "trades.csv"
        if cand_trades.exists():
            trades_path = cand_trades
            break
    if trades_path is None:
        raise SystemExit("missing trades.csv in reports/run_* or run_latest")

    cfg = _load_yaml(root / "config.yml")
    metrics: dict[str, Any] = {}
    if metrics_path.exists():
        try:
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        except Exception:
            metrics = {}

    trades = _load_trades(trades_path)
    if not trades:
        raise SystemExit("no trades found")

    trade_count = len(trades)
    entry_month_counts = Counter(_period_month(t.entry_time) for t in trades)
    entry_year_counts = Counter(str(t.entry_time.year) for t in trades)
    symbol_counts = Counter(t.symbol for t in trades)
    side_counts = Counter(f"{t.symbol}_{t.side}" for t in trades)
    pnl_by_symbol_side: dict[str, float] = defaultdict(float)
    for t in trades:
        pnl_by_symbol_side[f"{t.symbol}_{t.side}"] += t.pnl

    start_dt = trades[0].entry_time
    end_dt = trades[-1].entry_time
    period_start = metrics.get("metrics", {}).get("period_start") or start_dt.strftime("%Y-%m-%d %H:%M:%S")
    period_end = metrics.get("metrics", {}).get("period_end") or end_dt.strftime("%Y-%m-%d %H:%M:%S")
    parsed_period_start = _parse_dt(str(period_start)) or start_dt
    parsed_period_end = _parse_dt(str(period_end)) or end_dt
    months_all = _months_between(parsed_period_start, parsed_period_end)
    zero_trade_months = [m for m in months_all if m not in entry_month_counts]

    gaps_hours: list[float] = []
    for prev, cur in zip(trades, trades[1:], strict=False):
        gaps_hours.append((cur.entry_time - prev.entry_time).total_seconds() / 3600.0)
    bars_held = [t.bars_held for t in trades]

    strategy_params = cfg.get("strategy_params", {}) if isinstance(cfg.get("strategy_params"), dict) else {}
    filters = cfg.get("filters", {}) if isinstance(cfg.get("filters"), dict) else {}
    money = cfg.get("money_management", {}) if isinstance(cfg.get("money_management"), dict) else {}
    money.get("risk_on", {}) if isinstance(money.get("risk_on"), dict) else {}
    sr_entries = cfg.get("sr_entries", {}) if isinstance(cfg.get("sr_entries"), dict) else {}
    symbols = cfg.get("data", {}).get("symbols", []) if isinstance(cfg.get("data"), dict) else []

    likely_bottlenecks: list[str] = []
    if int(strategy_params.get("cooldown_bars", 0) or 0) >= 24:
        likely_bottlenecks.append(f"cooldown_bars={strategy_params.get('cooldown_bars')}")
    if float(filters.get("adx_floor", 0) or 0) >= 30:
        likely_bottlenecks.append(f"adx_floor={filters.get('adx_floor')}")
    expand_filter = filters.get("expand_filter", {}) if isinstance(filters.get("expand_filter"), dict) else {}
    if bool(expand_filter.get("enabled", False)):
        likely_bottlenecks.append("expand_filter=enabled")
    short_symbols = strategy_params.get("short_symbols", []) if isinstance(strategy_params.get("short_symbols"), list) else []
    if short_symbols == ["btc"] or short_symbols == ["BTC"]:
        likely_bottlenecks.append("only_btc_short=true")
    if not bool(sr_entries.get("enabled", False)):
        likely_bottlenecks.append("sr_entries=disabled")
    if isinstance(symbols, list) and len(symbols) <= 2:
        likely_bottlenecks.append(f"symbols={','.join(str(x) for x in symbols)}")

    findings: list[str] = []
    if len(zero_trade_months) > len(months_all) * 0.4:
        findings.append("zero_trade_months_high")
    if _median_or_zero(bars_held) <= 4:
        findings.append("holding_not_main_problem")
    if pnl_by_symbol_side.get("btc_LONG", pnl_by_symbol_side.get("btc_LONG".lower(), 0.0)) < 0:
        findings.append("btc_long_drag")
    # normalized lowercase keys too
    btc_long_pnl = pnl_by_symbol_side.get("btc_LONG", 0.0) + pnl_by_symbol_side.get("btc_long", 0.0)
    if btc_long_pnl < 0:
        findings.append("btc_long_drag")

    decision = [
        "交易频率偏低是真问题，但当前证据更支持先做 entry-density 研究，不支持直接放松 live 过滤。",
        "先查 no-trade 原因，再开 isolated 频率分支；优先方向应是 BNB LONG 再入场 / BTC SHORT continuation，不是放大 BTC LONG。",
    ]

    out = {
        "status": "ok",
        "ts_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "project_dir": str(root),
        "version": cfg.get("system", {}).get("version") if isinstance(cfg.get("system"), dict) else None,
        "strategy": cfg.get("system", {}).get("strategy") if isinstance(cfg.get("system"), dict) else None,
        "period_start": period_start,
        "period_end": period_end,
        "trade_count": trade_count,
        "active_trade_months": len(entry_month_counts),
        "total_months": len(months_all),
        "zero_trade_months": len(zero_trade_months),
        "zero_trade_ratio": round((len(zero_trade_months) / max(len(months_all), 1)), 4),
        "median_gap_hours": round(_median_or_zero(gaps_hours), 2),
        "mean_gap_hours": round(_mean_or_zero(gaps_hours), 2),
        "median_bars_held": round(_median_or_zero(bars_held), 2),
        "mean_bars_held": round(_mean_or_zero(bars_held), 2),
        "trades_by_symbol": dict(sorted(symbol_counts.items())),
        "trades_by_symbol_side": dict(sorted(side_counts.items())),
        "pnl_by_symbol_side": {k: round(v, 2) for k, v in sorted(pnl_by_symbol_side.items())},
        "year_counts": dict(sorted(entry_year_counts.items())),
        "likely_bottlenecks": likely_bottlenecks,
        "findings": sorted(set(findings)),
        "decision": decision,
        "next_tests": [
            "add no-trade veto reason logging",
            "BNB long re-entry overlay (isolated branch)",
            "BTC short continuation overlay (isolated branch)",
        ],
    }

    json_path = reports / "frequency_trade_audit_latest.json"
    txt_path = reports / "frequency_trade_audit_latest.txt"
    json_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"status: {out['status']}",
        f"ts_utc: {out['ts_utc']}",
        f"project_dir: {out['project_dir']}",
        f"version: {out['version']}",
        f"strategy: {out['strategy']}",
        f"period_start: {out['period_start']}",
        f"period_end: {out['period_end']}",
        f"trade_count: {out['trade_count']}",
        f"active_trade_months: {out['active_trade_months']}",
        f"total_months: {out['total_months']}",
        f"zero_trade_months: {out['zero_trade_months']}",
        f"zero_trade_ratio: {out['zero_trade_ratio']}",
        f"median_gap_hours: {out['median_gap_hours']}",
        f"mean_gap_hours: {out['mean_gap_hours']}",
        f"median_bars_held: {out['median_bars_held']}",
        f"mean_bars_held: {out['mean_bars_held']}",
        f"trades_by_symbol: {json.dumps(out['trades_by_symbol'], ensure_ascii=False)}",
        f"trades_by_symbol_side: {json.dumps(out['trades_by_symbol_side'], ensure_ascii=False)}",
        f"pnl_by_symbol_side: {json.dumps(out['pnl_by_symbol_side'], ensure_ascii=False)}",
        f"year_counts: {json.dumps(out['year_counts'], ensure_ascii=False)}",
        f"likely_bottlenecks: {json.dumps(out['likely_bottlenecks'], ensure_ascii=False)}",
        f"findings: {json.dumps(out['findings'], ensure_ascii=False)}",
        "",
        "=== decision ===",
    ]
    for item in decision:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("=== next_tests ===")
    for item in out["next_tests"]:
        lines.append(f"- {item}")
    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(txt_path)


if __name__ == "__main__":
    main()
