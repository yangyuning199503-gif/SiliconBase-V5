#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


@dataclass
class SegmentStat:
    pnl: float
    pf: float
    trades: int


@dataclass
class CandidateResult:
    mult_hi: float
    run_id: str
    run_dir: Path

    total_return: float
    cagr: float
    max_drawdown: float
    profit_factor: float
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

    seg_2020_21: SegmentStat
    seg_2022_23: SegmentStat
    seg_2024_26: SegmentStat
    min_seg_pf: float


def _load_cfg(p: Path) -> dict[str, Any]:
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _dump_cfg(cfg: dict[str, Any], p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _normalize_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    c = json.loads(json.dumps(cfg))
    c.setdefault("system", {})
    c["system"].pop("version", None)
    c.setdefault("outputs", {})
    c["outputs"].pop("copy_to_downloads", None)
    c.setdefault("money_management", {})
    mm = c["money_management"]
    mm.setdefault("risk_on", {})
    mm["risk_on"].pop("mult_hi", None)
    return c


def _cfg_hash(cfg: dict[str, Any]) -> str:
    norm = _normalize_cfg(cfg)
    blob = json.dumps(norm, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _pf_from_pnl(pnl: pd.Series) -> float:
    pos = float(pnl[pnl > 0].sum())
    neg = float((-pnl[pnl < 0]).sum())
    if neg <= 0:
        return float("inf") if pos > 0 else 0.0
    return pos / neg


def _segment_stat(trades: pd.DataFrame, start: str, end: str) -> SegmentStat:
    if trades.empty:
        return SegmentStat(0.0, 0.0, 0)
    t = trades.copy()
    t["exit_time"] = pd.to_datetime(t["exit_time"], utc=True, errors="coerce")
    mask = (t["exit_time"] >= pd.Timestamp(start, tz="UTC")) & (t["exit_time"] < pd.Timestamp(end, tz="UTC"))
    seg = t.loc[mask]
    if seg.empty:
        return SegmentStat(0.0, 0.0, 0)
    pnl = float(seg["pnl"].sum())
    pf = _pf_from_pnl(seg["pnl"])
    return SegmentStat(pnl=pnl, pf=pf, trades=int(len(seg)))


def _monthly_dist(mrets: pd.Series) -> tuple[float, float, float, float, int, int, float]:
    if mrets.empty:
        return 0.0, 0.0, 0.0, 0.0, 0, 0, 0.0
    mean = float(mrets.mean())
    p90 = float(mrets.quantile(0.90)) if len(mrets) >= 2 else float(mrets.iloc[0])
    p95 = float(mrets.quantile(0.95)) if len(mrets) >= 2 else float(mrets.iloc[0])
    mx = float(mrets.max())
    ge20 = int((mrets >= 0.20).sum())
    ge30 = int((mrets >= 0.30).sum())
    cum = float((1.0 + mrets).prod() - 1.0)
    return mean, p90, p95, mx, ge20, ge30, cum


def _run_backtest(py: Path, cfg_path: Path, run_id: str) -> None:
    cmd = [str(py), "-m", "src.main", "--config", str(cfg_path), "--run-id", run_id]
    subprocess.run(cmd, check=True)


def _ensure_run_artifacts(reports_dir: Path, run_dir: Path) -> None:
    mapping = {
        "deepseek_brief_latest.txt": "deepseek_brief_latest.txt",
        "monthly_returns_latest.csv": "monthly_returns_latest.csv",
        "monthly_stats_latest.txt": "monthly_stats_latest.txt",
        "metrics_latest.json": "metrics_latest.json",
        "trades_latest.csv": "trades_latest.csv",
    }
    for src_name, dst_name in mapping.items():
        src = reports_dir / src_name
        if src.exists():
            shutil.copy2(src, run_dir / dst_name)


def _read_monthly_returns(run_dir: Path) -> pd.Series:
    p = run_dir / "monthly_returns_latest.csv"
    if not p.exists():
        p = run_dir / "monthly_returns.csv"
    if not p.exists():
        raise FileNotFoundError(f"monthly returns not found in {run_dir}")
    df = pd.read_csv(p)
    if "return" not in df.columns:
        raise ValueError(f"'return' column missing in {p}")
    idx_col = "time" if "time" in df.columns else ("date" if "date" in df.columns else None)
    if idx_col:
        idx = pd.to_datetime(df[idx_col], utc=True, errors="coerce")
    else:
        idx = pd.to_datetime(df.index, utc=True, errors="coerce")
    s = pd.Series(df["return"].astype(float).values, index=idx).dropna()
    return s


def _read_trades(run_dir: Path) -> pd.DataFrame:
    p = run_dir / "trades.csv"
    if not p.exists():
        p = run_dir / "trades_latest.csv"
    if not p.exists():
        raise FileNotFoundError(f"trades not found in {run_dir}")
    return pd.read_csv(p)


def _parse_metrics(run_dir: Path) -> dict[str, Any]:
    p = run_dir / "metrics.json"
    if not p.exists():
        p = run_dir / "metrics_latest.json"
    if not p.exists():
        raise FileNotFoundError(f"metrics not found in {run_dir}")
    payload = json.loads(p.read_text(encoding="utf-8", errors="ignore"))
    return payload.get("metrics", payload.get("run_metrics", {})) or {}


def _score_key_balanced(r: CandidateResult) -> tuple[float, float, float, int, int, float]:
    return (r.min_seg_pf, r.profit_factor, r.total_return, r.r_ge20, r.r_ge30, r.max_drawdown)


def _score_key_aggressive(r: CandidateResult) -> tuple[int, int, float, float, float, float]:
    return (r.r_ge20, r.r_ge30, r.r_max, r.profit_factor, r.total_return, r.max_drawdown)


def _score_key_recency(r: CandidateResult) -> tuple[int, int, float, float, float, float]:
    return (r.r_ge30, r.r_ge20, r.r_max, r.seg_2024_26.pf, r.r_cum, r.max_drawdown)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yml")
    ap.add_argument("--mult-hi", nargs="+", type=float, default=[3.0, 3.5, 4.0, 4.5])
    ap.add_argument("--objective", choices=["balanced", "aggressive", "recency"], default="recency")
    ap.add_argument("--recent-months", type=int, default=24)
    ap.add_argument("--max-dd", type=float, default=0.35)
    ap.add_argument("--min-pf", type=float, default=1.15)
    ap.add_argument("--min-seg-pf", type=float, default=0.90)
    ap.add_argument("--reports-dir", default="reports")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    base_cfg_path = Path(args.config)
    reports_dir = Path(args.reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)

    base_cfg = _load_cfg(base_cfg_path)
    base_hash = _cfg_hash(base_cfg)

    py = Path("./.venv/bin/python")
    if not py.exists():
        raise SystemExit("missing ./.venv/bin/python, run ./run.sh first")

    sweep_dir = reports_dir / "sweep_riskon"
    sweep_dir.mkdir(parents=True, exist_ok=True)

    results: list[CandidateResult] = []
    for idx, mh in enumerate(args.mult_hi, start=1):
        tok = int(round(float(mh) * 10))
        run_id = f"riskon_mh{tok:02d}"
        run_dir = reports_dir / f"run_{run_id}"
        cfg_path = sweep_dir / f"config_mh{tok:02d}.yml"

        cfg = json.loads(json.dumps(base_cfg))
        cfg.setdefault("system", {})["version"] = f"r153_mh{tok:02d}"
        cfg.setdefault("money_management", {}).setdefault("risk_on", {})["mult_hi"] = float(mh)
        _dump_cfg(cfg, cfg_path)

        need_run = args.force
        if run_dir.exists() and (run_dir / "metrics.json").exists() and (run_dir / "CFG_HASH.txt").exists():
            old_hash = (run_dir / "CFG_HASH.txt").read_text(encoding="utf-8", errors="ignore").strip()
            if old_hash == base_hash and not args.force:
                need_run = False
        else:
            need_run = True

        if need_run:
            print(f"[{idx}/{len(args.mult_hi)}] RUN mult_hi={mh} run_id={run_id}")
            _run_backtest(py, cfg_path, run_id)
            run_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(cfg_path, run_dir / "config_used.yml")
            (run_dir / "CFG_HASH.txt").write_text(base_hash, encoding="utf-8")
            _ensure_run_artifacts(reports_dir, run_dir)
        else:
            print(f"[{idx}/{len(args.mult_hi)}] REUSE mult_hi={mh} run_id={run_id}")

        m = _parse_metrics(run_dir)
        total_return = float(m.get("total_return", 0.0))
        cagr = float(m.get("cagr", 0.0))
        max_drawdown = float(m.get("max_drawdown", 0.0))
        profit_factor = float(m.get("profit_factor", 0.0))
        trades = int(m.get("trades", 0))
        win_rate = float(m.get("win_rate", 0.0))
        sharpe_daily = float(m.get("sharpe_daily", 0.0))

        mrets = _read_monthly_returns(run_dir)
        m_mean, m_p90, m_p95, m_max, m_ge20, m_ge30, m_cum = _monthly_dist(mrets)

        recent_n = int(args.recent_months)
        m_recent = mrets.tail(recent_n) if recent_n > 0 else mrets
        r_mean, r_p90, r_p95, r_max, r_ge20, r_ge30, r_cum = _monthly_dist(m_recent)
        r_months = int(len(m_recent))

        trades_df = _read_trades(run_dir)
        seg1 = _segment_stat(trades_df, "2020-01-01", "2022-01-01")
        seg2 = _segment_stat(trades_df, "2022-01-01", "2024-01-01")
        seg3 = _segment_stat(trades_df, "2024-01-01", "2026-02-01")
        min_seg_pf = float(min(seg1.pf, seg2.pf, seg3.pf))

        res = CandidateResult(
            mult_hi=float(mh),
            run_id=run_id,
            run_dir=run_dir,
            total_return=total_return,
            cagr=cagr,
            max_drawdown=max_drawdown,
            profit_factor=profit_factor,
            trades=trades,
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
            seg_2020_21=seg1,
            seg_2022_23=seg2,
            seg_2024_26=seg3,
            min_seg_pf=min_seg_pf,
        )
        results.append(res)

        print("------------------------------------------------------------")
        print(f"RESULT mult_hi={mh} run_id={run_id}")
        print(f"TotalRet: {total_return*100:.2f}% | CAGR: {cagr*100:.2f}% | MaxDD: {max_drawdown*100:.2f}% | PF: {profit_factor:.2f}")
        print(f"Trades: {trades} | WinRate: {win_rate*100:.2f}% | Sharpe(daily): {sharpe_daily:.2f}")
        print(f"Monthly(all): mean {m_mean*100:.2f}% | p90 {m_p90*100:.2f}% | p95 {m_p95*100:.2f}% | max {m_max*100:.2f}% | >=20% {m_ge20} | >=30% {m_ge30} | cum {m_cum*100:.2f}%")
        print(f"Monthly(recent {r_months}m): mean {r_mean*100:.2f}% | p90 {r_p90*100:.2f}% | p95 {r_p95*100:.2f}% | max {r_max*100:.2f}% | >=20% {r_ge20} | >=30% {r_ge30} | cum {r_cum*100:.2f}%")
        print(f"Segment PF: 2020-2021 {seg1.pf:.2f} | 2022-2023 {seg2.pf:.2f} | 2024-2026 {seg3.pf:.2f} | min {min_seg_pf:.2f}")
        print("------------------------------------------------------------")

    # selection stages
    stage1 = [r for r in results if (r.max_drawdown > -abs(args.max_dd)) and (r.profit_factor >= args.min_pf) and (r.min_seg_pf >= args.min_seg_pf)]
    stage2 = [r for r in results if (r.max_drawdown > -abs(args.max_dd)) and (r.profit_factor >= args.min_pf)]
    stage3 = [r for r in results if (r.max_drawdown > -abs(args.max_dd))]
    pick_pool = stage1 or stage2 or stage3 or results

    if stage1:
        print(f"SELECT: stage1(dd<= {args.max_dd}, pf>= {args.min_pf}, min_seg_pf>= {args.min_seg_pf})")
    elif stage2:
        print(f"SELECT: stage2(dd<= {args.max_dd}, pf>= {args.min_pf})")
    elif stage3:
        print(f"SELECT: stage3(dd<= {args.max_dd})")
    else:
        print("SELECT: no filters")

    key = _score_key_recency if args.objective == "recency" else (_score_key_aggressive if args.objective == "aggressive" else _score_key_balanced)
    best = sorted(pick_pool, key=key, reverse=True)[0]

    best_bal = sorted(pick_pool, key=_score_key_balanced, reverse=True)[0]
    best_rec = sorted(pick_pool, key=_score_key_recency, reverse=True)[0]
    best_agg = sorted(pick_pool, key=_score_key_aggressive, reverse=True)[0]

    print("")
    print("BEST(balanced)")
    print(f"mult_hi={best_bal.mult_hi} run_id={best_bal.run_id} ret={best_bal.total_return*100:.2f}% pf={best_bal.profit_factor:.2f} maxdd={best_bal.max_drawdown*100:.2f}% recent_ge20={best_bal.r_ge20} recent_ge30={best_bal.r_ge30} min_seg_pf={best_bal.min_seg_pf:.2f}")
    print("BEST(recency)")
    print(f"mult_hi={best_rec.mult_hi} run_id={best_rec.run_id} ret={best_rec.total_return*100:.2f}% pf={best_rec.profit_factor:.2f} maxdd={best_rec.max_drawdown*100:.2f}% recent_ge20={best_rec.r_ge20} recent_ge30={best_rec.r_ge30} min_seg_pf={best_rec.min_seg_pf:.2f}")
    print("BEST(aggressive)")
    print(f"mult_hi={best_agg.mult_hi} run_id={best_agg.run_id} ret={best_agg.total_return*100:.2f}% pf={best_agg.profit_factor:.2f} maxdd={best_agg.max_drawdown*100:.2f}% recent_ge20={best_agg.r_ge20} recent_ge30={best_agg.r_ge30} min_seg_pf={best_agg.min_seg_pf:.2f}")
    print("")
    print(f"PROMOTED({args.objective})")
    print(f"mult_hi={best.mult_hi} run_id={best.run_id} ret={best.total_return*100:.2f}% pf={best.profit_factor:.2f} maxdd={best.max_drawdown*100:.2f}% recent_ge20={best.r_ge20} recent_ge30={best.r_ge30} min_seg_pf={best.min_seg_pf:.2f}")
    print("")

    # promote config + artifacts
    best_cfg_path = best.run_dir / "config_used.yml"
    if not best_cfg_path.exists():
        raise SystemExit(f"missing config_used.yml in {best.run_dir}")
    shutil.copy2(best_cfg_path, base_cfg_path)

    for fn in ["deepseek_brief_latest.txt", "monthly_returns_latest.csv", "monthly_stats_latest.txt", "metrics_latest.json"]:
        src = best.run_dir / fn
        if src.exists():
            shutil.copy2(src, reports_dir / fn)

    with contextlib.suppress(Exception):
        os.utime(best.run_dir, times=None)

    (best.run_dir / "SELECTED_BEST.txt").write_text(
        f"objective={args.objective}\nmult_hi={best.mult_hi}\nrun_id={best.run_id}\n",
        encoding="utf-8",
    )

    print("DONE")


if __name__ == "__main__":
    main()
