from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in (None, ""):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import contextlib

from src.backtest.metrics import monthly_returns, summarize_metrics

DAYS_PER_MONTH = 30.4375


def _normalize_ts(ts: Any) -> pd.Timestamp | None:
    try:
        out = pd.Timestamp(ts)
    except Exception:
        return None
    if pd.isna(out):
        return None
    try:
        out = out.tz_localize(None)
    except Exception:
        with contextlib.suppress(Exception):
            out = out.tz_convert(None)
    return out


def _month_span(start: pd.Timestamp | None, end: pd.Timestamp | None) -> float:
    if start is None or end is None or end <= start:
        return 0.0
    return max((end - start).total_seconds() / 86400.0 / DAYS_PER_MONTH, 1.0 / DAYS_PER_MONTH)


def _pct(x: Any) -> str:
    try:
        v = float(x)
    except Exception:
        return "NA"
    if math.isnan(v):
        return "NA"
    return f"{v * 100:.2f}%"


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
    except Exception:
        return default
    if math.isnan(v):
        return default
    return v


def _find_latest_run_dir(root: Path) -> Path:
    latest = root / "reports" / "run_latest"
    if (latest / "equity_curve.csv").exists() and (latest / "trades.csv").exists():
        return latest
    runs = sorted((root / "reports").glob("run_*/metrics.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not runs:
        raise SystemExit("未找到 reports/run_latest 或 reports/run_*/metrics.json；请先执行 bash run.sh")
    return runs[0].parent


def _load_equity(path: Path) -> pd.Series:
    df = pd.read_csv(path)
    if df.empty:
        raise SystemExit(f"equity_curve.csv 为空: {path}")
    time_col = df.columns[0]
    if "time" in df.columns:
        time_col = "time"
    df[time_col] = pd.to_datetime(df[time_col], errors="coerce")
    df = df.dropna(subset=[time_col])
    df = df.sort_values(time_col)
    df = df.drop_duplicates(subset=[time_col], keep="last")
    if "equity" not in df.columns:
        raise SystemExit(f"equity_curve.csv 缺少 equity 列: {path}")
    eq = pd.to_numeric(df["equity"], errors="coerce")
    out = pd.Series(eq.to_numpy(), index=df[time_col])
    out = out.dropna()
    if out.empty:
        raise SystemExit(f"equity_curve.csv 无有效 equity 数据: {path}")
    try:
        out.index = out.index.tz_localize(None)
    except Exception:
        with contextlib.suppress(Exception):
            out.index = out.index.tz_convert(None)
    out.name = "equity"
    return out


def _load_trades(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    for c in ["entry_time", "exit_time"]:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce")
            try:
                df[c] = df[c].dt.tz_localize(None)
            except Exception:
                with contextlib.suppress(Exception):
                    df[c] = df[c].dt.tz_convert(None)
    if "pnl" in df.columns:
        df["pnl"] = pd.to_numeric(df["pnl"], errors="coerce").fillna(0.0)
    return df


def _slice_recent_equity(eq: pd.Series, recent_months: int) -> tuple[pd.Series, pd.Timestamp]:
    end = _normalize_ts(eq.index.max())
    start = _normalize_ts(eq.index.min())
    if end is None or start is None:
        return eq.copy(), pd.Timestamp("1970-01-01")
    recent_start = max(start, end - pd.DateOffset(months=int(recent_months)))
    sliced = eq.loc[eq.index >= recent_start].copy()
    if sliced.empty:
        sliced = eq.copy()
        recent_start = start
    return sliced, recent_start


def _slice_recent_trades(df: pd.DataFrame, recent_start: pd.Timestamp) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=list(df.columns) if df is not None else None)
    time_col = "exit_time" if "exit_time" in df.columns else ("entry_time" if "entry_time" in df.columns else None)
    if time_col is None:
        return df.copy()
    out = df.dropna(subset=[time_col]).copy()
    out = out.loc[out[time_col] >= recent_start].copy()
    return out


def _monthly_stats(eq: pd.Series) -> dict[str, Any]:
    m = monthly_returns(eq)
    if m.empty:
        return {
            "months": 0,
            "mean": 0.0,
            "p90": 0.0,
            "p95": 0.0,
            "max": 0.0,
            "cum": 0.0,
            "comp_month": 0.0,
            "comp_ann": 0.0,
            "ge20": 0,
            "ge30": 0,
        }
    vals = m.astype(float)
    cum = float((1.0 + vals).prod() - 1.0)
    months = int(len(vals))
    comp_month = float((1.0 + cum) ** (1.0 / months) - 1.0) if months > 0 and (1.0 + cum) > 0 else -1.0
    comp_ann = float((1.0 + comp_month) ** 12 - 1.0) if (1.0 + comp_month) > 0 else -1.0
    return {
        "months": months,
        "mean": float(vals.mean()),
        "p90": float(vals.quantile(0.90)),
        "p95": float(vals.quantile(0.95)),
        "max": float(vals.max()),
        "cum": cum,
        "comp_month": comp_month,
        "comp_ann": comp_ann,
        "ge20": int((vals >= 0.20).sum()),
        "ge30": int((vals >= 0.30).sum()),
    }


def _window_report(eq: pd.Series, trades: pd.DataFrame) -> dict[str, Any]:
    start = _normalize_ts(eq.index.min())
    end = _normalize_ts(eq.index.max())
    initial = float(eq.iloc[0])
    metrics = summarize_metrics(initial=initial, equity=eq, trades=trades)
    total_ret = _safe_float(metrics.get("total_return"))
    months = _month_span(start, end)
    monthlyized = float((1.0 + total_ret) ** (1.0 / months) - 1.0) if months > 0 and (1.0 + total_ret) > 0 else -1.0
    payload = {
        "window_start": start.isoformat() if start is not None else None,
        "window_end": end.isoformat() if end is not None else None,
        "window_months": months,
        "monthlyized_return": monthlyized,
        "metrics": metrics,
        "monthly": _monthly_stats(eq),
    }
    return payload


def _judgement(full: dict[str, Any], recent: dict[str, Any]) -> dict[str, Any]:
    fm = full.get("metrics", {})
    rm = recent.get("metrics", {})
    full_pf = _safe_float(fm.get("profit_factor"))
    recent_pf = _safe_float(rm.get("profit_factor"))
    full_dd = abs(_safe_float(fm.get("max_drawdown")))
    recent_dd = abs(_safe_float(rm.get("max_drawdown")))
    full_trades = int(fm.get("trades", 0) or 0)
    recent_trades = int(rm.get("trades", 0) or 0)
    full_months = _safe_float(full.get("window_months"))
    dilution = recent_pf > full_pf and recent_dd <= full_dd + 1e-9
    status = "hold"
    if full_months >= 72 and recent_trades >= 35 and recent_pf >= 1.45 and recent_dd <= 0.45:
        status = "pass"
    elif recent_trades < 20 or recent_pf < 1.05 or recent_dd > 0.60:
        status = "kill"
    return {
        "status": status,
        "full_window_ge_6y": bool(full_months >= 72.0),
        "old_years_may_dilute_recent": bool(dilution),
        "full_trades": full_trades,
        "recent_trades": recent_trades,
        "full_pf": full_pf,
        "recent_pf": recent_pf,
        "full_maxdd": full_dd,
        "recent_maxdd": recent_dd,
    }


def _section_lines(title: str, payload: dict[str, Any]) -> list[str]:
    m = payload.get("metrics", {})
    mm = payload.get("monthly", {})
    return [
        title,
        f"- 窗口: {payload.get('window_start','')} -> {payload.get('window_end','')} | 月数={_safe_float(payload.get('window_months')):.2f}",
        f"- 总收益={_pct(m.get('total_return'))} | CAGR={_pct(m.get('cagr'))} | 几何月化={_pct(payload.get('monthlyized_return'))} | MaxDD={_pct(m.get('max_drawdown'))}",
        f"- 交易={int(m.get('trades',0) or 0)} | PF={_safe_float(m.get('profit_factor')):.3f} | 胜率={_pct(m.get('win_rate'))} | Sharpe(daily)={_safe_float(m.get('sharpe_daily')):.3f}",
        f"- 月分布: mean={_pct(mm.get('mean'))} | p90={_pct(mm.get('p90'))} | p95={_pct(mm.get('p95'))} | max={_pct(mm.get('max'))} | >=20%={int(mm.get('ge20',0) or 0)} | >=30%={int(mm.get('ge30',0) or 0)}",
        f"- 月复利: cum={_pct(mm.get('cum'))} | comp_month={_pct(mm.get('comp_month'))} | comp_ann={_pct(mm.get('comp_ann'))}",
    ]


def _build_text(full: dict[str, Any], recent: dict[str, Any], judge: dict[str, Any], run_dir: Path, recent_months: int) -> str:
    lines: list[str] = []
    lines.append("双窗口主回测摘要")
    lines.append("================")
    lines.append("")
    lines.append("原则：6年整体只做软约束；近2年质量做强判断。")
    lines.append(f"最近窗口：按最新权益终点向前取 {recent_months} 个月。")
    lines.append(f"来源: {run_dir}")
    lines.append("")
    lines.extend(_section_lines("=== 6年整体 / 全样本 ===", full))
    lines.append("")
    lines.extend(_section_lines("=== 近2年重点 ===", recent))
    lines.append("")
    lines.append("=== 判断 ===")
    lines.append(f"- 状态: {judge.get('status','hold')}")
    lines.append(f"- 满足6年以上覆盖: {'yes' if judge.get('full_window_ge_6y') else 'no'}")
    lines.append(f"- 老年份可能在稀释近2年: {'yes' if judge.get('old_years_may_dilute_recent') else 'no'}")
    lines.append(f"- PF: 全样本 {judge.get('full_pf',0.0):.3f} | 近2年 {judge.get('recent_pf',0.0):.3f}")
    lines.append(f"- MaxDD: 全样本 {_pct(judge.get('full_maxdd'))} | 近2年 {_pct(judge.get('recent_maxdd'))}")
    lines.append(f"- 交易数: 全样本 {int(judge.get('full_trades',0) or 0)} | 近2年 {int(judge.get('recent_trades',0) or 0)}")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="生成 6年整体 + 近2年重点 的双窗口主回测摘要")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--recent-months", type=int, default=24)
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    run_dir = _find_latest_run_dir(root)
    eq = _load_equity(run_dir / "equity_curve.csv")
    trades = _load_trades(run_dir / "trades.csv")

    recent_eq, recent_start = _slice_recent_equity(eq, max(int(args.recent_months), 1))
    recent_trades = _slice_recent_trades(trades, recent_start)

    full = _window_report(eq, trades)
    recent = _window_report(recent_eq, recent_trades)
    judge = _judgement(full, recent)

    payload = {
        "run_dir": str(run_dir),
        "policy": {
            "full_window": "soft_constraint",
            "recent_window": "strong_judgement",
            "recent_months": int(args.recent_months),
        },
        "full": full,
        "recent": recent,
        "judgement": judge,
    }

    reports = root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    research_raw = reports / "research_raw"
    research_raw.mkdir(parents=True, exist_ok=True)

    txt = _build_text(full, recent, judge, run_dir, int(args.recent_months))
    js = json.dumps(payload, ensure_ascii=False, indent=2)

    outputs = [
        reports / "dual_window_backtest_latest.txt",
        reports / "dual_window_backtest_latest.json",
        reports / "stage77_mainline_dual_window_latest.txt",
        reports / "stage77_mainline_dual_window_latest.json",
        research_raw / "dual_window_backtest_latest.txt",
        research_raw / "dual_window_backtest_latest.json",
        research_raw / "stage77_mainline_dual_window_latest.txt",
        research_raw / "stage77_mainline_dual_window_latest.json",
    ]
    for dst in outputs:
        if dst.suffix.lower() == ".json":
            dst.write_text(js, encoding="utf-8")
        else:
            dst.write_text(txt, encoding="utf-8")

    for dst in outputs:
        print(dst)


if __name__ == "__main__":
    main()
