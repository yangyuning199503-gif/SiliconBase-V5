from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in (None, ""):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest.io import read_config


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def _fmt_num(x: float) -> str:
    return f"{x:+.2f}"


def _trade_metrics(trades_df: pd.DataFrame, initial_equity: float) -> dict[str, Any]:
    df = trades_df.copy() if trades_df is not None else pd.DataFrame()
    if df.empty:
        return {
            "trades": 0,
            "wins": 0,
            "win_rate": 0.0,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
            "profit_factor": 0.0,
            "total_pnl": 0.0,
            "total_return": 0.0,
            "max_drawdown": 0.0,
            "equity_end": initial_equity,
        }
    pnl = pd.to_numeric(df["pnl"], errors="coerce").fillna(0.0)
    equity = initial_equity + pnl.cumsum()
    peak = equity.cummax()
    dd = equity / peak - 1.0
    gp = float(pnl[pnl > 0].sum())
    gl = float(-pnl[pnl < 0].sum())
    pf = gp / gl if gl > 0 else (999.0 if gp > 0 else 0.0)
    trades = int(len(df))
    wins = int((pnl > 0).sum())
    return {
        "trades": trades,
        "wins": wins,
        "win_rate": float(wins / trades) if trades else 0.0,
        "gross_profit": gp,
        "gross_loss": gl,
        "profit_factor": float(pf),
        "total_pnl": float(pnl.sum()),
        "total_return": float(equity.iloc[-1] / initial_equity - 1.0),
        "max_drawdown": float(dd.min()) if len(dd) else 0.0,
        "equity_end": float(equity.iloc[-1]) if len(equity) else float(initial_equity),
    }


def _find_latest_trades_csv(root: Path) -> Path:
    candidates = sorted((root / "reports").glob("run_*/trades.csv"))
    if not candidates:
        raise SystemExit("未找到 reports/run_*/trades.csv")
    candidates.sort(key=lambda p: (p.parent.name, p.stat().st_mtime), reverse=True)
    return candidates[0]


def _load_events(path: Path, start_utc: pd.Timestamp, end_utc: pd.Timestamp) -> pd.DataFrame:
    df = pd.read_csv(path)
    if df.empty:
        raise SystemExit(f"事件库为空：{path}")
    for col in ["start_utc", "end_utc"]:
        df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")
    df = df.dropna(subset=["start_utc", "end_utc"]).copy()
    if "enabled" in df.columns:
        df = df[df["enabled"].astype(str).isin(["1", "True", "true", "TRUE", "yes", "Y"])]
    df = df[(df["end_utc"] >= start_utc) & (df["start_utc"] <= end_utc)].copy()
    return df.reset_index(drop=True)


def _generate_monthly_macro_windows(start_utc: pd.Timestamp, end_utc: pd.Timestamp) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    months = pd.period_range(start_utc.to_period("M"), end_utc.to_period("M"), freq="M")
    for period in months:
        month_start = period.start_time.tz_localize("UTC")
        nfp = month_start
        while nfp.weekday() != 4:
            nfp += pd.Timedelta(days=1)
        rows.append({
            "start_utc": nfp.normalize(),
            "end_utc": nfp.normalize() + pd.Timedelta(days=1) - pd.Timedelta(minutes=1),
            "category": "macro_sched",
            "title": "NFP approx (first Friday)",
            "severity": "medium",
            "event_mode": "risk_off",
            "profile_tags": "macro_rule",
            "source": "rule",
        })
        cpi = (month_start + pd.Timedelta(days=11)).normalize()
        rows.append({
            "start_utc": cpi,
            "end_utc": cpi + pd.Timedelta(days=1) - pd.Timedelta(minutes=1),
            "category": "macro_sched",
            "title": "CPI approx (12th UTC day)",
            "severity": "medium",
            "event_mode": "risk_off",
            "profile_tags": "macro_rule",
            "source": "rule",
        })
    out = pd.DataFrame(rows)
    out = out[(out["end_utc"] >= start_utc) & (out["start_utc"] <= end_utc)].copy()
    return out.reset_index(drop=True)


def _assign_block_reasons(trades: pd.DataFrame, windows: pd.DataFrame) -> tuple[pd.Series, list[str], list[str]]:
    blocked = pd.Series(False, index=trades.index)
    categories: list[str] = []
    titles: list[str] = []
    for idx, row in trades.iterrows():
        ts = row["entry_time"]
        matched = windows[(windows["start_utc"] <= ts) & (windows["end_utc"] >= ts)]
        if matched.empty:
            categories.append("")
            titles.append("")
            continue
        blocked.loc[idx] = True
        categories.append("|".join(sorted({str(x) for x in matched.get("category", pd.Series(dtype=str)).tolist() if str(x)}))[:200])
        titles.append(" | ".join([str(x) for x in matched.get("title", pd.Series(dtype=str)).tolist()[:3]])[:240])
    return blocked, categories, titles


def _profile_filters(manual: pd.DataFrame, macro_rule: pd.DataFrame) -> list[tuple[str, str, pd.DataFrame]]:
    out: list[tuple[str, str, pd.DataFrame]] = []
    risk_off = manual[manual["event_mode"].astype(str).eq("risk_off")].copy()
    risk_off_two = manual[manual["event_mode"].astype(str).isin(["risk_off", "two_sided"])].copy()
    no_positive = manual[~manual["event_mode"].astype(str).eq("positive_catalyst")].copy()
    us_eq = manual[manual["category"].astype(str).eq("us_equity")].copy()
    crypto = manual[manual["category"].astype(str).eq("crypto")].copy()
    macro_war_policy = manual[manual["category"].astype(str).isin(["macro", "war", "policy", "us_equity"]) & manual["event_mode"].astype(str).isin(["risk_off", "two_sided"])].copy()

    out.append(("manual_risk_off", "仅手工高风险事件（不含正面催化）", risk_off))
    out.append(("manual_risk_off_plus_two_sided", "手工高风险事件 + 双向大波动事件", risk_off_two))
    out.append(("manual_no_positive_plus_macro_rule", "手工事件（除正面催化） + 月度宏观近似窗", pd.concat([no_positive, macro_rule], ignore_index=True, sort=False)))
    out.append(("macro_war_policy", "宏观/战争/监管/美股结构性风险", macro_war_policy))
    out.append(("us_equity_only", "仅美股/风险资产冲击窗", us_eq))
    out.append(("crypto_only", "仅加密原生黑天鹅", crypto))
    return out


def _score_variant(base: dict[str, Any], gated: dict[str, Any], blocked: dict[str, Any]) -> float:
    # positive is better: reward dd improvement, small reward for pnl, punish no samples
    dd_improve = float(gated.get("max_drawdown", 0.0)) - float(base.get("max_drawdown", 0.0))
    pnl_delta = float(gated.get("total_pnl", 0.0)) - float(base.get("total_pnl", 0.0))
    blocked_n = int(blocked.get("trades", 0))
    return dd_improve * 10000.0 + pnl_delta / 10000.0 + min(blocked_n, 20) * 0.5


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    base = payload["base"]
    variants = payload["variants"]
    top = payload.get("top_recommendations", [])
    lines = [
        "长窗口事件库 Sweep（技术基线 vs 技术+事件暂停层）",
        f"生成时间(UTC): {pd.Timestamp.now(tz='UTC').strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "【基线】",
        f"- trades: {base.get('trades', 0)}",
        f"- win_rate: {_fmt_pct(float(base.get('win_rate', 0.0)))}",
        f"- total_pnl: {_fmt_num(float(base.get('total_pnl', 0.0)))}",
        f"- total_return(近似): {_fmt_pct(float(base.get('total_return', 0.0)))}",
        f"- max_drawdown(近似): {_fmt_pct(float(base.get('max_drawdown', 0.0)))}",
        f"- profit_factor: {float(base.get('profit_factor', 0.0)):.2f}",
        "",
        "【候选结果】",
    ]
    for row in variants:
        lines.extend([
            f"- {row['key']} | {row['label']}",
            f"  blocked_trades={row['blocked_trades']} pnl_delta={_fmt_num(float(row['pnl_delta']))} maxdd_delta={_fmt_pct(float(row['maxdd_delta']))} gated_pf={float(row['gated']['profit_factor']):.2f}",
            f"  blocked_categories={row['blocked_categories'] or '-'}",
        ])
    lines.append("")
    lines.append("【建议】")
    if not top:
        lines.append("- 当前没有拿到足够样本，不建议把消息面升成真实 veto。")
    else:
        for row in top:
            lines.append(f"- {row['key']}: blocked={row['blocked_trades']} pnl_delta={_fmt_num(float(row['pnl_delta']))} maxdd_delta={_fmt_pct(float(row['maxdd_delta']))}")
    lines.append("- 说明: 月度宏观近似窗仍然是近似规则，不是官方逐条历史新闻重放。")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="长窗口事件库 Sweep")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--events-csv", default="data/events/event_windows_v2.csv")
    ap.add_argument("--out", default="~/Downloads/event_window_sweep_latest.txt")
    ap.add_argument("--trades-csv", default="")
    args = ap.parse_args()

    root = Path(args.project_dir).resolve()
    cfg = read_config(root / "config.yml")
    initial_equity = float(((cfg.get("portfolio") or {}) if isinstance(cfg.get("portfolio"), dict) else {}).get("initial_equity", 100000.0))

    trades_path = Path(args.trades_csv).expanduser().resolve() if args.trades_csv else _find_latest_trades_csv(root)
    trades = pd.read_csv(trades_path)
    if trades.empty:
        raise SystemExit(f"交易文件为空：{trades_path}")
    trades["entry_time"] = pd.to_datetime(trades["entry_time"], utc=True, errors="coerce")
    trades["exit_time"] = pd.to_datetime(trades["exit_time"], utc=True, errors="coerce")
    trades = trades.dropna(subset=["entry_time"]).sort_values(["entry_time", "exit_time"]).reset_index(drop=True)

    start_utc = trades["entry_time"].min()
    end_utc = trades["entry_time"].max()
    event_csv = (root / args.events_csv).resolve()
    manual = _load_events(event_csv, start_utc, end_utc)
    macro_rule = _generate_monthly_macro_windows(start_utc, end_utc)

    base_metrics = _trade_metrics(trades, initial_equity)
    variant_rows: list[dict[str, Any]] = []
    for key, label, windows in _profile_filters(manual, macro_rule):
        windows = windows.sort_values(["start_utc", "end_utc"]).reset_index(drop=True)
        blocked_mask, cats, titles = _assign_block_reasons(trades, windows)
        tmp = trades.copy()
        tmp["block_category"] = cats
        tmp["block_title"] = titles
        blocked_df = tmp.loc[blocked_mask].copy()
        gated_df = tmp.loc[~blocked_mask].copy()
        gated_metrics = _trade_metrics(gated_df, initial_equity)
        blocked_metrics = _trade_metrics(blocked_df, initial_equity)
        cat_counts = []
        if not blocked_df.empty:
            cser = blocked_df["block_category"].fillna("")
            cat_counts = [str(x) for x in cser.replace("", pd.NA).dropna().astype(str).value_counts().head(4).index.tolist()]
        variant_rows.append({
            "key": key,
            "label": label,
            "window_rows": int(len(windows)),
            "blocked_trades": int(blocked_metrics.get("trades", 0)),
            "pnl_delta": float(gated_metrics.get("total_pnl", 0.0)) - float(base_metrics.get("total_pnl", 0.0)),
            "maxdd_delta": float(gated_metrics.get("max_drawdown", 0.0)) - float(base_metrics.get("max_drawdown", 0.0)),
            "gated": gated_metrics,
            "blocked": blocked_metrics,
            "blocked_categories": cat_counts,
            "sample": blocked_df[["entry_time", "symbol", "pnl", "block_category", "block_title"]].head(8).assign(entry_time=lambda x: x["entry_time"].astype(str)).to_dict("records"),
            "score": _score_variant(base_metrics, gated_metrics, blocked_metrics),
        })

    ranked = sorted(variant_rows, key=lambda x: (x["score"], x["blocked_trades"]), reverse=True)
    top = [r for r in ranked if r["blocked_trades"] > 0][:3]
    payload = {
        "base": base_metrics,
        "window": {
            "trades_csv": str(trades_path),
            "event_csv": str(event_csv),
            "manual_events": int(len(manual)),
            "macro_rule_events": int(len(macro_rule)),
            "trade_range_utc": f"{start_utc} -> {end_utc}",
        },
        "variants": variant_rows,
        "top_recommendations": [{k: v for k, v in row.items() if k not in {"sample", "gated", "blocked", "score"}} for row in top],
    }
    reports_dir = root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "event_window_sweep_latest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    out_path = Path(os.path.expanduser(args.out)).resolve()
    _write_report(out_path, payload)
    print(json.dumps({"ok": True, "out": str(out_path), "top": payload["top_recommendations"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
