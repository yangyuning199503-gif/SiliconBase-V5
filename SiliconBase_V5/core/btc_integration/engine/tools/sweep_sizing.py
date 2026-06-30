from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


@dataclass
class RunRow:
    slices: int
    run_id: str
    run_dir: Path

    total_return: float
    cagr: float
    max_dd: float
    pf: float
    trades: int
    win_rate: float
    sharpe_daily: float

    m_mean: float
    m_p90: float
    m_p95: float
    m_max: float
    m_ge20: int
    m_ge30: int
    m_cum: float

    r_mean: float
    r_p90: float
    r_p95: float
    r_max: float
    r_ge20: int
    r_ge30: int
    r_cum: float
    r_months: int

    seg_pf_2020_21: float
    seg_pf_2022_23: float
    seg_pf_2024_26: float
    seg_min_pf: float


def _read_yaml(p: Path) -> dict[str, Any]:
    return yaml.safe_load(p.read_text(encoding="utf-8", errors="ignore")) or {}


def _write_yaml(p: Path, obj: dict[str, Any]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(obj, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _pf_from_pnl(pnl: pd.Series) -> float:
    pos = float(pnl[pnl > 0].sum())
    neg = float((-pnl[pnl < 0]).sum())
    if neg <= 0:
        return float("inf") if pos > 0 else 0.0
    return pos / neg


def _segment_pf(trades: pd.DataFrame, start: str, end: str) -> tuple[float, float, int]:
    if trades.empty:
        return 0.0, 0.0, 0
    t = trades.copy()
    t["exit_time"] = pd.to_datetime(t["exit_time"], utc=True, errors="coerce")
    mask = (t["exit_time"] >= pd.Timestamp(start, tz="UTC")) & (t["exit_time"] < pd.Timestamp(end, tz="UTC"))
    seg = t.loc[mask]
    if seg.empty:
        return 0.0, 0.0, 0
    pnl = float(seg["pnl"].sum())
    pf = _pf_from_pnl(seg["pnl"])
    return pnl, pf, int(len(seg))


def _monthly_dist(mrets: pd.Series) -> tuple[float, float, float, float, int, int, float]:
    if mrets.empty:
        return 0.0, 0.0, 0.0, 0.0, 0, 0, 0.0
    m_mean = float(mrets.mean())
    m_p90 = float(mrets.quantile(0.90)) if len(mrets) >= 2 else float(mrets.iloc[0])
    m_p95 = float(mrets.quantile(0.95)) if len(mrets) >= 2 else float(mrets.iloc[0])
    m_max = float(mrets.max())
    m_ge20 = int((mrets >= 0.20).sum())
    m_ge30 = int((mrets >= 0.30).sum())
    m_cum = float((1.0 + mrets).prod() - 1.0)
    return m_mean, m_p90, m_p95, m_max, m_ge20, m_ge30, m_cum


def _run_main(py: str, config_path: Path, run_id: str) -> None:
    cmd = [py, "-m", "src.main", "--config", str(config_path), "--run-id", run_id]
    subprocess.run(cmd, check=True)


def _copy_latest_reports(reports_dir: Path, run_dir: Path) -> None:
    mapping = {
        "deepseek_brief_latest.txt": "deepseek_brief.txt",
        "monthly_returns_latest.csv": "monthly_returns.csv",
        "monthly_stats_latest.txt": "monthly_stats.txt",
        "metrics_latest.json": "metrics_latest.json",
    }
    for src_name, dst_name in mapping.items():
        src = reports_dir / src_name
        if src.exists():
            shutil.copy2(src, run_dir / dst_name)


def _touch(p: Path) -> None:
    p.touch()


def _promote_best(root: Path, reports_dir: Path, best: RunRow, best_cfg_path: Path) -> None:
    shutil.copy2(best_cfg_path, root / "config.yml")

    artifacts = {
        best.run_dir / "deepseek_brief.txt": reports_dir / "deepseek_brief_latest.txt",
        best.run_dir / "monthly_returns.csv": reports_dir / "monthly_returns_latest.csv",
        best.run_dir / "monthly_stats.txt": reports_dir / "monthly_stats_latest.txt",
        best.run_dir / "metrics_latest.json": reports_dir / "metrics_latest.json",
    }
    for src, dst in artifacts.items():
        if src.exists():
            shutil.copy2(src, dst)

    _touch(best.run_dir)


def _score_rows(
    rows: list[RunRow],
    objective: str,
    max_dd_cap: float,
    min_pf: float,
    min_seg_pf: float,
) -> tuple[RunRow, list[RunRow]]:
    eligible: list[RunRow] = []
    for r in rows:
        if r.max_dd <= -abs(max_dd_cap):
            continue
        if r.pf < min_pf:
            continue
        if r.seg_min_pf < min_seg_pf:
            continue
        eligible.append(r)

    if not eligible:
        eligible = rows[:]

    def key_bal(r: RunRow):
        return (
            r.seg_min_pf,
            r.pf,
            r.total_return,
            r.r_ge20,
            r.r_ge30,
            r.max_dd,
        )

    def key_agg(r: RunRow):
        return (
            r.r_ge20,
            r.r_ge30,
            r.r_max,
            r.r_cum,
            r.pf,
            r.total_return,
            r.max_dd,
        )

    def key_rec(r: RunRow):
        return (
            r.r_ge30,
            r.r_ge20,
            r.r_max,
            r.seg_pf_2024_26,
            r.r_cum,
            r.pf,
            r.max_dd,
        )

    if objective == "aggressive":
        key = key_agg
    elif objective == "recency":
        key = key_rec
    else:
        key = key_bal

    ranked = sorted(eligible, key=key, reverse=True)
    return ranked[0], ranked


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yml")
    ap.add_argument("--slices", default="10,8,6,4")
    ap.add_argument("--objective", choices=["balanced", "aggressive", "recency"], default="recency")
    ap.add_argument("--recent-months", type=int, default=24)
    ap.add_argument("--max-dd-cap", type=float, default=0.35)
    ap.add_argument("--min-pf", type=float, default=1.15)
    ap.add_argument("--min-seg-pf", type=float, default=0.95)
    args = ap.parse_args()

    root = Path(".").resolve()
    reports_dir = root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    base_cfg_path = (root / args.config).resolve()
    base_cfg = _read_yaml(base_cfg_path)

    candidates = [int(x.strip()) for x in str(args.slices).split(",") if x.strip()]
    run_tag = pd.Timestamp.now(tz="UTC").strftime("%Y%m%d_%H%M%S")
    cfg_out_dir = reports_dir / "sweep_sizing"
    cfg_out_dir.mkdir(parents=True, exist_ok=True)

    py = sys.executable
    rows: list[RunRow] = []
    cfg_paths: dict[int, Path] = {}

    for idx, sl in enumerate(candidates, start=1):
        cfg = json.loads(json.dumps(base_cfg))
        cfg.setdefault("system", {})["version"] = f"r153_s{sl}"
        cfg.setdefault("money_management", {})["capital_slices"] = sl

        cfg_path = cfg_out_dir / f"config_s{sl}.yml"
        _write_yaml(cfg_path, cfg)
        cfg_paths[sl] = cfg_path

        run_id = f"sizing_s{sl}_{run_tag}_{idx}"
        print(f"[{idx}/{len(candidates)}] run_id={run_id} capital_slices={sl}")
        _run_main(py, cfg_path, run_id)

        run_dir = reports_dir / f"run_{run_id}"
        _copy_latest_reports(reports_dir, run_dir)

        metrics_path = run_dir / "metrics.json"
        metrics = json.loads(metrics_path.read_text(encoding="utf-8", errors="ignore")).get("metrics", {})
        total_return = float(metrics.get("total_return", 0.0))
        cagr = float(metrics.get("cagr", 0.0))
        max_dd = float(metrics.get("max_drawdown", 0.0))
        pf = float(metrics.get("profit_factor", 0.0))
        trades_n = int(metrics.get("trades", 0))
        win_rate = float(metrics.get("win_rate", 0.0))
        sharpe_daily = float(metrics.get("sharpe_daily", 0.0))
        dd_start = str(metrics.get("max_drawdown_start", "") or "")
        dd_end = str(metrics.get("max_drawdown_end", "") or "")

        trades_df = pd.read_csv(run_dir / "trades.csv")
        mrets_df = pd.read_csv(run_dir / "monthly_returns.csv")
        mrets = pd.Series(
            mrets_df["return"].astype(float).values,
            index=pd.to_datetime(mrets_df.get("time", mrets_df.get("date")), utc=True, errors="coerce"),
        ).dropna()

        m_mean, m_p90, m_p95, m_max, m_ge20, m_ge30, m_cum = _monthly_dist(mrets)

        recent_n = int(args.recent_months)
        m_recent = mrets.tail(recent_n) if recent_n > 0 else mrets
        r_mean, r_p90, r_p95, r_max, r_ge20, r_ge30, r_cum = _monthly_dist(m_recent)
        r_months = int(len(m_recent))

        _, pf_20_21, _ = _segment_pf(trades_df, "2020-01-01", "2022-01-01")
        _, pf_22_23, _ = _segment_pf(trades_df, "2022-01-01", "2024-01-01")
        _, pf_24_26, _ = _segment_pf(trades_df, "2024-01-01", "2026-02-01")
        seg_min = min(pf_20_21, pf_22_23, pf_24_26)

        print("------------------------------------------------------------")
        print(f"RESULT run_id={run_id} capital_slices={sl}")
        print(f"TotalRet: {total_return*100:.2f}% | CAGR: {cagr*100:.2f}% | MaxDD: {max_dd*100:.2f}% | PF: {pf:.2f}")
        print(f"Trades: {trades_n} | WinRate: {win_rate*100:.2f}% | Sharpe(daily): {sharpe_daily:.2f}")
        if dd_start and dd_end:
            print(f"MaxDD Window: {dd_start} -> {dd_end}")
        print(f"Monthly(all): mean {m_mean*100:.2f}% | p90 {m_p90*100:.2f}% | p95 {m_p95*100:.2f}% | max {m_max*100:.2f}% | >=20% {m_ge20} | >=30% {m_ge30} | cum {m_cum*100:.2f}%")
        print(f"Monthly(recent {r_months}m): mean {r_mean*100:.2f}% | p90 {r_p90*100:.2f}% | p95 {r_p95*100:.2f}% | max {r_max*100:.2f}% | >=20% {r_ge20} | >=30% {r_ge30} | cum {r_cum*100:.2f}%")
        print(f"Segment PF: 2020-2021 {pf_20_21:.2f} | 2022-2023 {pf_22_23:.2f} | 2024-2026 {pf_24_26:.2f} | min {seg_min:.2f}")
        print("------------------------------------------------------------")

        rows.append(
            RunRow(
                slices=sl,
                run_id=run_id,
                run_dir=run_dir,
                total_return=total_return,
                cagr=cagr,
                max_dd=max_dd,
                pf=pf,
                trades=trades_n,
                win_rate=win_rate,
                sharpe_daily=sharpe_daily,
                m_mean=m_mean,
                m_p90=m_p90,
                m_p95=m_p95,
                m_max=m_max,
                m_ge20=m_ge20,
                m_ge30=m_ge30,
                m_cum=m_cum,
                r_mean=r_mean,
                r_p90=r_p90,
                r_p95=r_p95,
                r_max=r_max,
                r_ge20=r_ge20,
                r_ge30=r_ge30,
                r_cum=r_cum,
                r_months=r_months,
                seg_pf_2020_21=pf_20_21,
                seg_pf_2022_23=pf_22_23,
                seg_pf_2024_26=pf_24_26,
                seg_min_pf=seg_min,
            )
        )

    df = pd.DataFrame([r.__dict__ for r in rows]).sort_values("slices", ascending=False)
    out_csv = cfg_out_dir / "sizing_sweep_table.csv"
    df.to_csv(out_csv, index=False)

    best_bal, _ = _score_rows(rows, "balanced", float(args.max_dd_cap), float(args.min_pf), float(args.min_seg_pf))
    best_rec, _ = _score_rows(rows, "recency", float(args.max_dd_cap), float(args.min_pf), float(args.min_seg_pf))
    best_agg, _ = _score_rows(rows, "aggressive", float(args.max_dd_cap), max(1.05, float(args.min_pf) - 0.10), max(0.90, float(args.min_seg_pf) - 0.10))

    chosen = best_rec if args.objective == "recency" else (best_agg if args.objective == "aggressive" else best_bal)
    chosen_cfg = cfg_paths[chosen.slices]
    _promote_best(root=root, reports_dir=reports_dir, best=chosen, best_cfg_path=chosen_cfg)

    print("")
    print("BEST(balanced)")
    print(f"slices={best_bal.slices} run_id={best_bal.run_id} ret={best_bal.total_return:.4f} pf={best_bal.pf:.3f} maxdd={best_bal.max_dd:.3f} recent_ge20={best_bal.r_ge20} recent_ge30={best_bal.r_ge30} seg_min_pf={best_bal.seg_min_pf:.3f}")
    print("BEST(recency)")
    print(f"slices={best_rec.slices} run_id={best_rec.run_id} ret={best_rec.total_return:.4f} pf={best_rec.pf:.3f} maxdd={best_rec.max_dd:.3f} recent_ge20={best_rec.r_ge20} recent_ge30={best_rec.r_ge30} seg_min_pf={best_rec.seg_min_pf:.3f}")
    print("BEST(aggressive)")
    print(f"slices={best_agg.slices} run_id={best_agg.run_id} ret={best_agg.total_return:.4f} pf={best_agg.pf:.3f} maxdd={best_agg.max_dd:.3f} recent_ge20={best_agg.r_ge20} recent_ge30={best_agg.r_ge30} seg_min_pf={best_agg.seg_min_pf:.3f}")
    print("")
    print(f"PROMOTED({args.objective})")
    print(f"slices={chosen.slices} run_id={chosen.run_id} ret={chosen.total_return:.4f} pf={chosen.pf:.3f} maxdd={chosen.max_dd:.3f} recent_ge20={chosen.r_ge20} recent_ge30={chosen.r_ge30} seg_min_pf={chosen.seg_min_pf:.3f}")
    print(f"table={out_csv}")


if __name__ == "__main__":
    main()
