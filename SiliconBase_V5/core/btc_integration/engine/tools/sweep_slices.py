from __future__ import annotations

import argparse
import contextlib
import copy
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


def _pf_from_pnls(pnls: pd.Series) -> float:
    if pnls.empty:
        return 0.0
    gp = float(pnls[pnls > 0].sum())
    gl = float((-pnls[pnls < 0]).sum())
    if gl <= 0:
        return float("inf") if gp > 0 else 0.0
    return gp / gl


def _segment_stats(trades_csv: Path) -> dict[str, float]:
    if not trades_csv.exists():
        return {"pnl_2022_2023": 0.0, "pf_2022_2023": 0.0}

    df = pd.read_csv(trades_csv)
    if df.empty or "entry_time" not in df.columns or "pnl" not in df.columns:
        return {"pnl_2022_2023": 0.0, "pf_2022_2023": 0.0}

    df["entry_time"] = pd.to_datetime(df["entry_time"], errors="coerce")
    df = df.dropna(subset=["entry_time"])

    seg = df[(df["entry_time"] >= pd.Timestamp("2022-01-01")) & (df["entry_time"] < pd.Timestamp("2024-01-01"))]
    pnl = float(seg["pnl"].sum()) if not seg.empty else 0.0
    pf = _pf_from_pnls(seg["pnl"]) if not seg.empty else 0.0
    return {"pnl_2022_2023": pnl, "pf_2022_2023": float(pf)}


def _read_equity_series(equity_curve_csv: Path) -> pd.Series:
    if not equity_curve_csv.exists():
        return pd.Series(dtype=float)
    try:
        df = pd.read_csv(equity_curve_csv, index_col=0, parse_dates=True)
    except Exception:
        return pd.Series(dtype=float)
    if df.empty or "equity" not in df.columns:
        return pd.Series(dtype=float)
    s = pd.to_numeric(df["equity"], errors="coerce").dropna()
    s.index = pd.to_datetime(s.index, errors="coerce")
    s = s.dropna()
    return s


def _monthly_returns(equity: pd.Series) -> pd.Series:
    if equity.empty:
        return pd.Series(dtype=float)
    for freq in ("ME", "M"):
        try:
            m = equity.resample(freq).last().dropna()
            r = m.pct_change().dropna()
            r.index = r.index.to_period("M").to_timestamp()
            return r
        except Exception:
            continue
    return pd.Series(dtype=float)


def _write_monthly_stats(mrets: pd.Series, out_txt: Path) -> None:
    if mrets.empty:
        out_txt.write_text("无月度收益数据\n", encoding="utf-8")
        return

    lines = []
    lines.append(f"months={len(mrets)}")
    lines.append(f"mean={mrets.mean()*100:.2f}%")
    lines.append(f"median={mrets.median()*100:.2f}%")
    lines.append(f"p90={mrets.quantile(0.90)*100:.2f}%")
    lines.append(f"min={mrets.min()*100:.2f}%")
    lines.append(f"max={mrets.max()*100:.2f}%")
    out_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_deepseek_brief(
    version: str,
    strategy: str,
    symbols: list[str],
    metrics: dict[str, Any],
    trades_csv: Path,
    mrets: pd.Series,
    out_txt: Path,
    extra_lines: list[str] | None = None,
) -> None:
    extra_lines = extra_lines or []

    last_trade = None
    try:
        if trades_csv.exists():
            tdf = pd.read_csv(trades_csv)
            if not tdf.empty and "exit_time" in tdf.columns:
                last_trade = str(pd.to_datetime(tdf["exit_time"], errors="coerce").max())
    except Exception:
        last_trade = None

    nonzero_months = int((mrets != 0).sum()) if not mrets.empty else 0

    lines = [
        f"【版本】{version} / {strategy}",
        f"【资产池】{','.join(symbols)}",
        f"【区间】{metrics.get('period_start')} -> {metrics.get('period_end')}",
        f"【总收益】{float(metrics.get('total_return', 0.0))*100:.2f}%",
        f"【年化】{float(metrics.get('cagr', 0.0))*100:.2f}%",
        f"【最大回撤】{float(metrics.get('max_drawdown', 0.0))*100:.2f}%",
        f"【PF】{float(metrics.get('profit_factor', 0.0)):.2f}",
        f"【交易数】{int(metrics.get('trades', 0))} / 胜率 {float(metrics.get('win_rate', 0.0))*100:.2f}%",
        f"【Sharpe(日频估算)】{float(metrics.get('sharpe_daily', 0.0)):.2f}",
        f"【最大回撤区间】{metrics.get('max_drawdown_start')} -> {metrics.get('max_drawdown_end')}",
        f"【最后交易】{last_trade}" if last_trade else "【最后交易】NA",
        f"【非零月份】{nonzero_months}",
    ]

    for ln in extra_lines:
        if ln:
            lines.append(ln)

    out_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")


@dataclass
class Row:
    slices: int
    total_return: float
    cagr: float
    max_drawdown: float
    profit_factor: float
    trades: int
    win_rate: float
    pnl_2022_2023: float
    pf_2022_2023: float
    run_id: str


def _objective_key(row: Row, objective: str) -> tuple[float, float]:
    if objective == "ret":
        return (row.total_return, row.profit_factor)
    if objective == "cagr":
        return (row.cagr, row.profit_factor)
    return (row.profit_factor, row.total_return)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yml")
    ap.add_argument("--slices", default="10,6,4")
    ap.add_argument("--objective", default="pf", choices=["pf", "ret", "cagr"])
    ap.add_argument("--max-dd", default="0.35", help="Max allowed drawdown (absolute, e.g. 0.35 for 35%%)")
    ap.add_argument("--min-pf", default="0.0", help="Minimum profit factor to be considered (e.g. 1.05)")
    ap.add_argument("--rerun-best", action="store_true", help="Rerun the best candidate once.")
    args = ap.parse_args()

    cfg_path = Path(args.config)
    if not cfg_path.exists():
        raise SystemExit(f"config not found: {cfg_path}")

    cfg_base = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    reports_dir = Path(cfg_base.get("outputs", {}).get("reports_dir", "reports"))
    reports_dir.mkdir(parents=True, exist_ok=True)

    base_version = str(cfg_base.get("system", {}).get("version", "rXXX"))
    base_strategy = str(cfg_base.get("system", {}).get("strategy", "NA"))
    symbols = list(cfg_base.get("data", {}).get("symbols", []) or [])

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    slices_list: list[int] = []
    for x in str(args.slices).split(","):
        x = x.strip()
        if not x:
            continue
        try:
            v = int(x)
            if v > 0:
                slices_list.append(v)
        except Exception:
            pass
    if not slices_list:
        slices_list = [10, 6, 4]

    max_dd_allowed = float(args.max_dd)
    min_pf = float(args.min_pf)

    sweep_dir = reports_dir / "_sweep"
    sweep_dir.mkdir(parents=True, exist_ok=True)

    rows: list[Row] = []
    py = sys.executable

    print(f"SWEEP: candidates={','.join(str(x) for x in slices_list)} (rerun_best={'YES' if args.rerun_best else 'NO'})")

    for i, s in enumerate(slices_list, 1):
        run_id = f"sweep_s{s}_{ts}"
        print(f"[{i}/{len(slices_list)}] running slices={s} run_id={run_id}")

        cfg = copy.deepcopy(cfg_base)
        cfg.setdefault("system", {})
        cfg["system"]["version"] = f"{base_version}_s{s}"
        cfg.setdefault("filters", {})
        cfg["filters"]["macro_gate_reference_symbol"] = "btc"
        cfg.setdefault("money_management", {})
        cfg["money_management"]["capital_slices"] = int(s)

        tmp_cfg = sweep_dir / f"config_s{s}.yml"
        tmp_cfg.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")

        subprocess.run([py, "-m", "src.main", "--config", str(tmp_cfg), "--run-id", run_id], check=True)

        run_dir = reports_dir / f"run_{run_id}"
        metrics_path = run_dir / "metrics.json"
        trades_path = run_dir / "trades.csv"
        if not metrics_path.exists():
            raise SystemExit(f"metrics not found: {metrics_path}")

        m = json.loads(metrics_path.read_text(encoding="utf-8")).get("metrics", {})
        seg = _segment_stats(trades_path)

        rows.append(
            Row(
                slices=int(s),
                total_return=float(m.get("total_return", 0.0)),
                cagr=float(m.get("cagr", 0.0)),
                max_drawdown=float(m.get("max_drawdown", 0.0)),
                profit_factor=float(m.get("profit_factor", 0.0)),
                trades=int(m.get("trades", 0)),
                win_rate=float(m.get("win_rate", 0.0)),
                pnl_2022_2023=float(seg["pnl_2022_2023"]),
                pf_2022_2023=float(seg["pf_2022_2023"]),
                run_id=run_id,
            )
        )

    df = pd.DataFrame([r.__dict__ for r in rows])
    df["total_return_pct"] = df["total_return"] * 100.0
    df["cagr_pct"] = df["cagr"] * 100.0
    df["max_drawdown_pct"] = df["max_drawdown"] * 100.0
    df["win_rate_pct"] = df["win_rate"] * 100.0

    view = df[
        [
            "slices",
            "total_return_pct",
            "cagr_pct",
            "max_drawdown_pct",
            "profit_factor",
            "trades",
            "win_rate_pct",
            "pnl_2022_2023",
            "pf_2022_2023",
            "run_id",
        ]
    ].copy()
    view = view.sort_values(by=["profit_factor", "total_return_pct"], ascending=False)

    filtered = [r for r in rows if (abs(r.max_drawdown) <= max_dd_allowed) and (r.profit_factor >= min_pf)]
    if filtered:
        pool = filtered
    else:
        dd_ok = [r for r in rows if abs(r.max_drawdown) <= max_dd_allowed]
        pool = dd_ok if dd_ok else rows
    best = max(pool, key=lambda r: _objective_key(r, args.objective))

    if args.rerun_best:
        best_run_id = f"sweep_best_s{best.slices}_{ts}"
        best_cfg = copy.deepcopy(cfg_base)
        best_cfg.setdefault("system", {})
        best_cfg["system"]["version"] = f"{base_version}_best_s{best.slices}"
        best_cfg.setdefault("filters", {})
        best_cfg["filters"]["macro_gate_reference_symbol"] = "btc"
        best_cfg.setdefault("money_management", {})
        best_cfg["money_management"]["capital_slices"] = int(best.slices)

        best_cfg_path = sweep_dir / f"config_best_s{best.slices}.yml"
        best_cfg_path.write_text(yaml.safe_dump(best_cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")

        subprocess.run([py, "-m", "src.main", "--config", str(best_cfg_path), "--run-id", best_run_id], check=True)

        best_final_run_id = best_run_id
        best_final_run_dir = reports_dir / f"run_{best_final_run_id}"
    else:
        best_final_run_id = best.run_id
        best_final_run_dir = reports_dir / f"run_{best_final_run_id}"
        if not best_final_run_dir.exists():
            raise SystemExit(f"best run dir not found: {best_final_run_dir}")

        with contextlib.suppress(Exception):
            os.utime(best_final_run_dir, None)

        metrics_src = best_final_run_dir / "metrics.json"
        if metrics_src.exists():
            (reports_dir / "metrics_latest.json").write_bytes(metrics_src.read_bytes())

        eq_src = best_final_run_dir / "equity_curve.csv"
        equity = _read_equity_series(eq_src)
        mrets = _monthly_returns(equity)
        (reports_dir / "monthly_returns_latest.csv").write_text(mrets.to_frame("return").to_csv(index=True), encoding="utf-8")
        _write_monthly_stats(mrets, reports_dir / "monthly_stats_latest.txt")

        metrics_obj = json.loads(metrics_src.read_text(encoding="utf-8")).get("metrics", {}) if metrics_src.exists() else {}
        trades_src = best_final_run_dir / "trades.csv"

        extra_lines = [
            f"【sweep_slices】candidates={','.join(str(x) for x in slices_list)} objective={args.objective} max_dd<={max_dd_allowed:.2f} min_pf>={min_pf:.2f}",
            f"【sweep_best】slices={best.slices} run_id=run_{best_final_run_id}",
        ]
        _write_deepseek_brief(
            version=f"{base_version}_s{best.slices}",
            strategy=base_strategy,
            symbols=symbols,
            metrics=metrics_obj,
            trades_csv=trades_src,
            mrets=mrets,
            out_txt=reports_dir / "deepseek_brief_latest.txt",
            extra_lines=extra_lines,
        )

    brief_path = reports_dir / "deepseek_brief_latest.txt"
    sweep_txt: list[str] = []
    sweep_txt.append("")
    sweep_txt.append(f"【sweep_table】candidates={','.join(str(x) for x in slices_list)} objective={args.objective} max_dd<={max_dd_allowed:.2f} min_pf>={min_pf:.2f}")
    sweep_txt.append("slices | TotalRet% | CAGR% | MaxDD% | PF | Trades | WinRate% | PnL_2022_23 | PF_2022_23")
    for _, r in view.iterrows():
        sweep_txt.append(
            f"{int(r['slices'])} | {r['total_return_pct']:.2f} | {r['cagr_pct']:.2f} | {r['max_drawdown_pct']:.2f} | {r['profit_factor']:.2f} | {int(r['trades'])} | {r['win_rate_pct']:.2f} | {r['pnl_2022_2023']:.0f} | {r['pf_2022_2023']:.2f}"
        )
    sweep_txt.append(f"【sweep_best】slices={best.slices} run_id=run_{best_final_run_id}")
    sweep_txt.append("")

    try:
        prev = brief_path.read_text(encoding="utf-8") if brief_path.exists() else ""
        brief_path.write_text(prev + "\n" + "\n".join(sweep_txt), encoding="utf-8")
    except Exception:
        pass

    print(view.to_string(index=False))
    print(f"BEST: slices={best.slices} objective={args.objective} latest_run_id={best_final_run_id}")


if __name__ == "__main__":
    main()
