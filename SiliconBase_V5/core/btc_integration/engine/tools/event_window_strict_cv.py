from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest.io import read_config

FREQ = pd.Timedelta(minutes=15)


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
            "equity_end": float(initial_equity),
        }
    pnl = pd.to_numeric(df["pnl"], errors="coerce").fillna(0.0)
    equity = float(initial_equity) + pnl.cumsum()
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
        "total_return": float(equity.iloc[-1] / float(initial_equity) - 1.0),
        "max_drawdown": float(dd.min()) if len(dd) else 0.0,
        "equity_end": float(equity.iloc[-1]) if len(equity) else float(initial_equity),
    }


def _find_latest_trades_csv(root: Path) -> Path:
    candidates = sorted((root / "reports").glob("run_*/trades.csv"))
    if not candidates:
        if (root / "run_latest" / "trades.csv").exists():
            return root / "run_latest" / "trades.csv"
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
    if "group_id" not in df.columns:
        df["group_id"] = df.get("title", pd.Series([""] * len(df), index=df.index)).astype(str)
    return df.sort_values(["start_utc", "end_utc", "title"]).reset_index(drop=True)


def _narrow_profile(events: pd.DataFrame) -> pd.DataFrame:
    allowed_categories = {"us_equity", "war", "policy", "crypto", "macro"}
    allowed_modes = {"risk_off", "two_sided"}
    out = events[
        events["category"].astype(str).isin(allowed_categories)
        & events["event_mode"].astype(str).isin(allowed_modes)
    ].copy()
    return out.sort_values(["start_utc", "end_utc", "title"]).reset_index(drop=True)


def _assign_block_reasons(trades: pd.DataFrame, windows: pd.DataFrame) -> tuple[pd.Series, list[str], list[str], list[str]]:
    blocked = pd.Series(False, index=trades.index)
    categories: list[str] = []
    titles: list[str] = []
    groups: list[str] = []
    for idx, row in trades.iterrows():
        ts = row["entry_time"]
        matched = windows[(windows["start_utc"] <= ts) & (windows["end_utc"] >= ts)]
        if matched.empty:
            categories.append("")
            titles.append("")
            groups.append("")
            continue
        blocked.loc[idx] = True
        categories.append("|".join(sorted({str(x) for x in matched.get("category", pd.Series(dtype=str)).tolist() if str(x)}))[:200])
        titles.append(" | ".join([str(x) for x in matched.get("title", pd.Series(dtype=str)).tolist()[:3]])[:240])
        groups.append("|".join(sorted({str(x) for x in matched.get("group_id", pd.Series(dtype=str)).tolist() if str(x)}))[:200])
    return blocked, categories, titles, groups


def _evaluate_variant(trades: pd.DataFrame, windows: pd.DataFrame, initial_equity: float) -> dict[str, Any]:
    blocked_mask, cats, titles, groups = _assign_block_reasons(trades, windows)
    tmp = trades.copy()
    tmp["block_category"] = cats
    tmp["block_title"] = titles
    tmp["block_group"] = groups
    blocked_df = tmp.loc[blocked_mask].copy()
    gated_df = tmp.loc[~blocked_mask].copy()
    blocked_metrics = _trade_metrics(blocked_df, initial_equity)
    gated_metrics = _trade_metrics(gated_df, initial_equity)
    return {
        "blocked_trades": int(blocked_metrics.get("trades", 0)),
        "blocked_categories": [str(x) for x in blocked_df["block_category"].replace("", pd.NA).dropna().astype(str).value_counts().head(8).index.tolist()],
        "blocked_titles": [str(x) for x in blocked_df["block_title"].replace("", pd.NA).dropna().astype(str).unique().tolist()[:8]],
        "blocked_groups": [str(x) for x in blocked_df["block_group"].replace("", pd.NA).dropna().astype(str).value_counts().head(8).index.tolist()],
        "gated": gated_metrics,
        "blocked": blocked_metrics,
        "blocked_df": blocked_df,
        "gated_df": gated_df,
    }


def _delta(base: dict[str, Any], gated: dict[str, Any]) -> tuple[float, float, float]:
    pnl_delta = float(gated.get("total_pnl", 0.0)) - float(base.get("total_pnl", 0.0))
    dd_delta = float(gated.get("max_drawdown", 0.0)) - float(base.get("max_drawdown", 0.0))
    score = dd_delta * 10000.0 + pnl_delta / 10000.0
    return pnl_delta, dd_delta, score


def _random_windows_like(windows: pd.DataFrame, start_utc: pd.Timestamp, end_utc: pd.Timestamp, rng: np.random.Generator) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    busy: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    ordered = windows.copy()
    ordered["duration"] = ordered["end_utc"] - ordered["start_utc"]
    ordered = ordered.sort_values(["duration", "start_utc"], ascending=[False, True]).reset_index(drop=True)
    for _, row in ordered.iterrows():
        duration = row["duration"]
        latest_start = end_utc - duration
        if latest_start <= start_utc:
            s = start_utc
            e = start_utc + duration
        else:
            max_slot = int(max(0, (latest_start - start_utc) // FREQ))
            placed: tuple[pd.Timestamp, pd.Timestamp] | None = None
            for _attempt in range(200):
                slot = int(rng.integers(0, max_slot + 1)) if max_slot > 0 else 0
                s = start_utc + slot * FREQ
                e = s + duration
                overlap = False
                for bs, be in busy:
                    if not (e < bs or s > be):
                        overlap = True
                        break
                if not overlap:
                    placed = (s, e)
                    break
            if placed is None:
                slot = int(rng.integers(0, max_slot + 1)) if max_slot > 0 else 0
                s = start_utc + slot * FREQ
                e = s + duration
            else:
                s, e = placed
        busy.append((s, e))
        rows.append({
            "start_utc": s,
            "end_utc": e,
            "category": row.get("category", ""),
            "title": f"placebo:{row.get('group_id', row.get('category', 'event'))}",
            "event_mode": row.get("event_mode", "risk_off"),
            "group_id": f"placebo:{row.get('group_id', row.get('category', 'event'))}",
        })
    return pd.DataFrame(rows)


def _placebo_test(trades: pd.DataFrame, windows: pd.DataFrame, initial_equity: float, base_metrics: dict[str, Any], runs: int, seed: int) -> dict[str, Any]:
    start_utc = trades["entry_time"].min().floor("15min")
    end_utc = trades["entry_time"].max().ceil("15min")
    rng = np.random.default_rng(seed)
    pnl_deltas: list[float] = []
    dd_deltas: list[float] = []
    scores: list[float] = []
    blocked_n: list[int] = []
    for _ in range(runs):
        fake = _random_windows_like(windows, start_utc, end_utc, rng)
        res = _evaluate_variant(trades, fake, initial_equity)
        pnl_delta, dd_delta, score = _delta(base_metrics, res["gated"])
        pnl_deltas.append(pnl_delta)
        dd_deltas.append(dd_delta)
        scores.append(score)
        blocked_n.append(res["blocked_trades"])
    return {
        "runs": runs,
        "pnl_delta_median": float(np.median(pnl_deltas)) if pnl_deltas else 0.0,
        "pnl_delta_p90": float(np.quantile(pnl_deltas, 0.90)) if pnl_deltas else 0.0,
        "pnl_delta_p95": float(np.quantile(pnl_deltas, 0.95)) if pnl_deltas else 0.0,
        "dd_delta_median": float(np.median(dd_deltas)) if dd_deltas else 0.0,
        "dd_delta_p90": float(np.quantile(dd_deltas, 0.90)) if dd_deltas else 0.0,
        "dd_delta_p95": float(np.quantile(dd_deltas, 0.95)) if dd_deltas else 0.0,
        "score_median": float(np.median(scores)) if scores else 0.0,
        "blocked_trades_median": float(np.median(blocked_n)) if blocked_n else 0.0,
        "pnl_deltas": pnl_deltas,
        "dd_deltas": dd_deltas,
        "scores": scores,
        "blocked_counts": blocked_n,
    }


def _calendar_year_folds(trades: pd.DataFrame, min_year: int = 2022) -> list[tuple[int, pd.Timestamp, pd.Timestamp]]:
    years = sorted(int(y) for y in trades["entry_time"].dt.year.unique() if int(y) >= min_year)
    folds: list[tuple[int, pd.Timestamp, pd.Timestamp]] = []
    for y in years:
        start = pd.Timestamp(f"{y}-01-01 00:00:00", tz="UTC")
        end = pd.Timestamp(f"{y + 1}-01-01 00:00:00", tz="UTC")
        folds.append((y, start, end))
    return folds


def _event_dominance(blocked_df: pd.DataFrame) -> float:
    if blocked_df.empty:
        return 0.0
    grp = blocked_df.copy()
    grp["block_group"] = grp["block_group"].replace("", pd.NA)
    grp = grp.dropna(subset=["block_group"])
    if grp.empty:
        return 0.0
    abs_by_group = grp.groupby("block_group")["pnl"].apply(lambda s: float(pd.to_numeric(s, errors="coerce").fillna(0.0).abs().sum()))
    total_abs = float(abs_by_group.sum())
    if total_abs <= 0:
        return 0.0
    return float(abs_by_group.max() / total_abs)


def _category_train_selection(
    train_trades: pd.DataFrame,
    windows: pd.DataFrame,
    initial_equity: float,
    *,
    min_blocked: int,
    min_nonneg_share: float,
    max_dd_worsen: float,
    max_dominance: float,
) -> dict[str, Any]:
    categories = sorted({str(x) for x in windows["category"].astype(str).tolist() if str(x)})
    chosen: list[str] = []
    diagnostics: list[dict[str, Any]] = []
    train_years = sorted(int(y) for y in train_trades["entry_time"].dt.year.unique())
    for cat in categories:
        win_cat = windows[windows["category"].astype(str) == cat].copy()
        all_eval = _evaluate_variant(train_trades, win_cat, initial_equity)
        all_blocked = int(all_eval["blocked_trades"])
        dom = _event_dominance(all_eval["blocked_df"])
        year_stats: list[dict[str, Any]] = []
        for y in train_years:
            t = train_trades[train_trades["entry_time"].dt.year == y].copy()
            if t.empty:
                continue
            base_y = _trade_metrics(t, initial_equity)
            ev_y = _evaluate_variant(t, win_cat, initial_equity)
            pnl_delta, dd_delta, score = _delta(base_y, ev_y["gated"])
            year_stats.append({
                "year": int(y),
                "blocked_trades": int(ev_y["blocked_trades"]),
                "pnl_delta": float(pnl_delta),
                "dd_delta": float(dd_delta),
                "score": float(score),
            })
        non_empty = [r for r in year_stats if int(r["blocked_trades"]) > 0]
        nonneg_share = float(sum(1 for r in non_empty if float(r["pnl_delta"]) >= 0.0 and float(r["dd_delta"]) >= 0.0) / len(non_empty)) if non_empty else 0.0
        median_score = float(np.median([r["score"] for r in non_empty])) if non_empty else 0.0
        worst_dd = float(min([r["dd_delta"] for r in non_empty])) if non_empty else 0.0
        chosen_flag = (
            all_blocked >= int(min_blocked)
            and nonneg_share >= float(min_nonneg_share)
            and median_score >= 0.0
            and worst_dd >= -abs(float(max_dd_worsen))
            and dom <= float(max_dominance)
        )
        diagnostics.append({
            "category": cat,
            "blocked_trades": all_blocked,
            "nonneg_share": float(nonneg_share),
            "median_score": float(median_score),
            "worst_dd_delta": float(worst_dd),
            "dominance": float(dom),
            "choose": bool(chosen_flag),
            "year_stats": year_stats,
        })
        if chosen_flag:
            chosen.append(cat)
    return {"categories": chosen, "diagnostics": diagnostics}


def _aggregate_fold_metrics(folds: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "folds": len(folds),
        "test_trades": sum(int(f["base_test"]["trades"]) for f in folds),
        "blocked_trades": sum(int(f["selected_test"]["blocked_trades"]) for f in folds),
        "pnl_delta": sum(float(f["selected_test"]["pnl_delta"]) for f in folds),
        "dd_delta": sum(float(f["selected_test"]["dd_delta"]) for f in folds),
        "non_negative_folds": sum(1 for f in folds if float(f["selected_test"]["pnl_delta"]) >= 0.0 and float(f["selected_test"]["dd_delta"]) >= 0.0),
        "chosen_non_empty_folds": sum(1 for f in folds if f["chosen_categories"]),
        "chosen_categories_union": sorted({c for f in folds for c in f["chosen_categories"]}),
    }


def _leave_one_group_out(trades: pd.DataFrame, windows: pd.DataFrame, initial_equity: float, base_metrics: dict[str, Any], full_fixed: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    full_pnl_delta, full_dd_delta, full_score = _delta(base_metrics, full_fixed["gated"])
    for gid in sorted({str(x) for x in windows["group_id"].astype(str).tolist() if str(x)}):
        reduced = windows[windows["group_id"].astype(str) != gid].copy()
        ev = _evaluate_variant(trades, reduced, initial_equity)
        pnl_delta, dd_delta, score = _delta(base_metrics, ev["gated"])
        out.append({
            "group_id": gid,
            "blocked_trades": int(ev["blocked_trades"]),
            "pnl_delta": float(pnl_delta),
            "dd_delta": float(dd_delta),
            "score_delta_vs_full": float(score - full_score),
            "pnl_delta_vs_full": float(pnl_delta - full_pnl_delta),
            "dd_delta_vs_full": float(dd_delta - full_dd_delta),
        })
    out.sort(key=lambda r: (abs(float(r["score_delta_vs_full"])), abs(float(r["pnl_delta_vs_full"]))), reverse=True)
    return out


def _coverage(events: pd.DataFrame, windows: pd.DataFrame, trades: pd.DataFrame, initial_equity: float) -> dict[str, Any]:
    by_year = events.assign(year=events["start_utc"].dt.year.astype(int)).groupby("year").size().to_dict()
    by_cat = events.groupby("category").size().to_dict()
    fixed_eval = _evaluate_variant(trades, windows, initial_equity)
    blocked_df = fixed_eval["blocked_df"].copy()
    blocked_by_cat: dict[str, int] = {}
    blocked_by_year: dict[int, int] = {}
    if not blocked_df.empty:
        for raw in blocked_df["block_category"].astype(str).tolist():
            for cat in [c for c in raw.split("|") if c]:
                blocked_by_cat[cat] = blocked_by_cat.get(cat, 0) + 1
        blocked_by_year = blocked_df.assign(year=blocked_df["entry_time"].dt.year.astype(int)).groupby("year").size().astype(int).to_dict()
    return {
        "event_rows": int(len(events)),
        "rows_by_year": {int(k): int(v) for k, v in by_year.items()},
        "rows_by_category": {str(k): int(v) for k, v in by_cat.items()},
        "blocked_by_category": {str(k): int(v) for k, v in blocked_by_cat.items()},
        "blocked_by_year": {int(k): int(v) for k, v in blocked_by_year.items()},
    }


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    lines: list[str] = [
        "扩展事件库严格交叉验证（purged walk-forward + placebo + leave-one-group-out）",
        f"生成时间(UTC): {pd.Timestamp.now(tz='UTC').strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "【基线】",
        f"- trades: {payload['base_all']['trades']}",
        f"- total_pnl: {_fmt_num(float(payload['base_all']['total_pnl']))}",
        f"- max_drawdown(近似): {_fmt_pct(float(payload['base_all']['max_drawdown']))}",
        f"- profit_factor: {float(payload['base_all']['profit_factor']):.2f}",
        "",
        "【事件库覆盖】",
        f"- event_rows: {payload['coverage']['event_rows']}",
        f"- rows_by_year: {payload['coverage']['rows_by_year']}",
        f"- rows_by_category: {payload['coverage']['rows_by_category']}",
        f"- blocked_by_year(full_fixed): {payload['coverage']['blocked_by_year']}",
        f"- blocked_by_category(full_fixed): {payload['coverage']['blocked_by_category']}",
        "",
        "【固定窄事件窗（全样本，仅观察）】",
        f"- blocked_trades: {payload['fixed_full']['blocked_trades']}",
        f"- pnl_delta: {_fmt_num(float(payload['fixed_full']['pnl_delta']))}",
        f"- dd_delta: {_fmt_pct(float(payload['fixed_full']['dd_delta']))}",
        f"- blocked_categories: {payload['fixed_full']['blocked_categories'] or '-'}",
        f"- dominance(max single group share): {payload['fixed_full']['dominance']:.2f}",
        "",
        "【严格滚动样本外】",
        f"- folds: {payload['oos_summary']['folds']}",
        f"- test_trades: {payload['oos_summary']['test_trades']}",
        f"- blocked_trades: {payload['oos_summary']['blocked_trades']}",
        f"- pnl_delta_sum: {_fmt_num(float(payload['oos_summary']['pnl_delta']))}",
        f"- dd_delta_sum: {_fmt_pct(float(payload['oos_summary']['dd_delta']))}",
        f"- chosen_non_empty_folds: {payload['oos_summary']['chosen_non_empty_folds']}",
        f"- chosen_categories_union: {payload['oos_summary']['chosen_categories_union'] or '-'}",
        "",
        "【逐年样本外】",
    ]
    for fold in payload["folds"]:
        lines.append(
            f"- test_year {fold['test_year']} | chosen={fold['chosen_categories'] or '-'} | test_trades={fold['base_test']['trades']} | blocked={fold['selected_test']['blocked_trades']} | pnl_delta={_fmt_num(float(fold['selected_test']['pnl_delta']))} | dd_delta={_fmt_pct(float(fold['selected_test']['dd_delta']))}"
        )
    lines.extend([
        "",
        "【Placebo】",
        f"- runs: {payload['placebo']['runs']}",
        f"- blocked_trades_median: {payload['placebo']['blocked_trades_median']}",
        f"- pnl_delta median/p90/p95: {_fmt_num(float(payload['placebo']['pnl_delta_median']))}/{_fmt_num(float(payload['placebo']['pnl_delta_p90']))}/{_fmt_num(float(payload['placebo']['pnl_delta_p95']))}",
        f"- dd_delta median/p90/p95: {_fmt_pct(float(payload['placebo']['dd_delta_median']))}/{_fmt_pct(float(payload['placebo']['dd_delta_p90']))}/{_fmt_pct(float(payload['placebo']['dd_delta_p95']))}",
        f"- empirical p(score): {payload['placebo_p']['score']:.3f}",
        f"- empirical p(pnl): {payload['placebo_p']['pnl']:.3f}",
        f"- empirical p(dd): {payload['placebo_p']['dd']:.3f}",
        "",
        "【Leave-one-group-out（前5个最敏感）】",
    ])
    for row in payload["logo_top5"]:
        lines.append(
            f"- remove [{row['group_id']}] -> blocked={row['blocked_trades']} pnl_delta={_fmt_num(float(row['pnl_delta']))} dd_delta={_fmt_pct(float(row['dd_delta']))} score_delta_vs_full={row['score_delta_vs_full']:+.4f}"
        )
    lines.extend(["", "【结论】"])
    for item in payload["conclusion"]:
        lines.append(f"- {item}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="扩展事件库严格交叉验证")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--events-csv", default="data/events/event_windows_v3.csv")
    ap.add_argument("--trades-csv", default="")
    ap.add_argument("--out", default="~/Downloads/event_window_strict_cv_latest.txt")
    ap.add_argument("--min-test-year", type=int, default=2022)
    ap.add_argument("--min-blocked", type=int, default=2)
    ap.add_argument("--min-nonneg-share", type=float, default=0.60)
    ap.add_argument("--max-dd-worsen", type=float, default=0.0025)
    ap.add_argument("--max-dominance", type=float, default=0.80)
    ap.add_argument("--placebo-runs", type=int, default=300)
    ap.add_argument("--seed", type=int, default=42)
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
    events = _load_events((root / args.events_csv).resolve(), start_utc, end_utc)
    windows = _narrow_profile(events)
    base_all = _trade_metrics(trades, initial_equity)

    coverage = _coverage(events, windows, trades, initial_equity)
    fixed_eval = _evaluate_variant(trades, windows, initial_equity)
    fixed_pnl_delta, fixed_dd_delta, fixed_score = _delta(base_all, fixed_eval["gated"])
    fixed_dominance = _event_dominance(fixed_eval["blocked_df"])

    folds_payload: list[dict[str, Any]] = []
    for test_year, test_start, test_end in _calendar_year_folds(trades, min_year=args.min_test_year):
        train = trades[trades["entry_time"] < test_start].copy()
        test = trades[(trades["entry_time"] >= test_start) & (trades["entry_time"] < test_end)].copy()
        if test.empty or train.empty:
            continue
        base_test = _trade_metrics(test, initial_equity)
        selection = _category_train_selection(
            train,
            windows,
            initial_equity,
            min_blocked=int(args.min_blocked),
            min_nonneg_share=float(args.min_nonneg_share),
            max_dd_worsen=float(args.max_dd_worsen),
            max_dominance=float(args.max_dominance),
        )
        chosen = selection["categories"]
        selected_windows = windows[windows["category"].astype(str).isin(chosen)].copy() if chosen else windows.iloc[0:0].copy()
        selected_eval = _evaluate_variant(test, selected_windows, initial_equity)
        selected_pnl_delta, selected_dd_delta, _selected_score = _delta(base_test, selected_eval["gated"])
        fixed_test_eval = _evaluate_variant(test, windows, initial_equity)
        fixed_test_pnl_delta, fixed_test_dd_delta, _fixed_test_score = _delta(base_test, fixed_test_eval["gated"])
        folds_payload.append({
            "test_year": int(test_year),
            "chosen_categories": chosen,
            "selection_diag": selection["diagnostics"],
            "base_test": base_test,
            "selected_test": {
                "blocked_trades": int(selected_eval["blocked_trades"]),
                "pnl_delta": float(selected_pnl_delta),
                "dd_delta": float(selected_dd_delta),
            },
            "fixed_test": {
                "blocked_trades": int(fixed_test_eval["blocked_trades"]),
                "pnl_delta": float(fixed_test_pnl_delta),
                "dd_delta": float(fixed_test_dd_delta),
            },
        })

    oos_summary = _aggregate_fold_metrics(folds_payload)
    placebo = _placebo_test(trades, windows, initial_equity, base_all, runs=int(args.placebo_runs), seed=int(args.seed))
    placebo_p = {
        "score": float(np.mean(np.array(placebo["scores"]) >= fixed_score)) if placebo["scores"] else 1.0,
        "pnl": float(np.mean(np.array(placebo["pnl_deltas"]) >= fixed_pnl_delta)) if placebo["pnl_deltas"] else 1.0,
        "dd": float(np.mean(np.array(placebo["dd_deltas"]) >= fixed_dd_delta)) if placebo["dd_deltas"] else 1.0,
    }
    logo = _leave_one_group_out(trades, windows, initial_equity, base_all, fixed_eval)

    conclusion: list[str] = []
    if int(oos_summary.get("blocked_trades", 0)) < 3:
        conclusion.append("滚动样本外被拦样本仍然过少，继续冻结为风险层。")
    if float(placebo_p["score"]) > 0.20:
        conclusion.append("placebo 经验 p 值仍不显著，不能把当前优势视为稳定超额。")
    if float(fixed_dominance) > 0.80:
        conclusion.append("固定窄事件窗仍存在单事件/单组主导，需继续扩样本。")
    if not oos_summary.get("chosen_categories_union"):
        conclusion.append("严格训练门槛下没有稳定类别入选，说明现有事件库仍不足以驱动 alpha。")
    if not conclusion:
        conclusion.append("样本外结果开始改善，但当前仍建议先留在风险层，等待更多历史事件覆盖。")
    conclusion.append("下一步优先补充：加密原生黑天鹅、监管执法、宏观冲击、美股结构性风险的官方/人工时间戳。")

    payload = {
        "base_all": base_all,
        "coverage": coverage,
        "fixed_full": {
            "blocked_trades": int(fixed_eval["blocked_trades"]),
            "pnl_delta": float(fixed_pnl_delta),
            "dd_delta": float(fixed_dd_delta),
            "blocked_categories": fixed_eval["blocked_categories"],
            "dominance": float(fixed_dominance),
        },
        "folds": folds_payload,
        "oos_summary": oos_summary,
        "placebo": {
            "runs": int(placebo["runs"]),
            "blocked_trades_median": float(placebo["blocked_trades_median"]),
            "pnl_delta_median": float(placebo["pnl_delta_median"]),
            "pnl_delta_p90": float(placebo["pnl_delta_p90"]),
            "pnl_delta_p95": float(placebo["pnl_delta_p95"]),
            "dd_delta_median": float(placebo["dd_delta_median"]),
            "dd_delta_p90": float(placebo["dd_delta_p90"]),
            "dd_delta_p95": float(placebo["dd_delta_p95"]),
        },
        "placebo_p": placebo_p,
        "logo_top5": logo[:5],
        "conclusion": conclusion,
    }

    reports_dir = root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "event_window_strict_cv_latest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    out_path = Path(os.path.expanduser(args.out)).resolve()
    _write_report(out_path, payload)
    print(json.dumps({"ok": True, "out": str(out_path), "blocked_trades": int(payload['fixed_full']['blocked_trades'])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
