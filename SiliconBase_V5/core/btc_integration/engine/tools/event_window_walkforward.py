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


def _fmt_num(x: float) -> str:
    return f"{x:+.2f}"


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.2f}%"


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


def _profile_filters(manual: pd.DataFrame, macro_rule: pd.DataFrame) -> list[tuple[str, str, pd.DataFrame]]:
    out: list[tuple[str, str, pd.DataFrame]] = []
    risk_off = manual[manual["event_mode"].astype(str).eq("risk_off")].copy()
    risk_off_two = manual[manual["event_mode"].astype(str).isin(["risk_off", "two_sided"])].copy()
    no_positive = manual[~manual["event_mode"].astype(str).eq("positive_catalyst")].copy()
    us_eq = manual[manual["category"].astype(str).eq("us_equity")].copy()
    crypto = manual[manual["category"].astype(str).eq("crypto")].copy()
    macro_war_policy = manual[
        manual["category"].astype(str).isin(["macro", "war", "policy", "us_equity"])
        & manual["event_mode"].astype(str).isin(["risk_off", "two_sided"])
    ].copy()

    out.append(("manual_risk_off", "仅手工高风险事件（不含正面催化）", risk_off))
    out.append(("manual_risk_off_plus_two_sided", "手工高风险事件 + 双向大波动事件", risk_off_two))
    out.append(("manual_no_positive_plus_macro_rule", "手工事件（除正面催化） + 月度宏观近似窗", pd.concat([no_positive, macro_rule], ignore_index=True, sort=False)))
    out.append(("macro_war_policy", "宏观/战争/监管/美股结构性风险", macro_war_policy))
    out.append(("us_equity_only", "仅美股/风险资产冲击窗", us_eq))
    out.append(("crypto_only", "仅加密原生黑天鹅", crypto))
    return out


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


def _evaluate_variant(trades: pd.DataFrame, windows: pd.DataFrame, initial_equity: float) -> dict[str, Any]:
    blocked_mask, cats, titles = _assign_block_reasons(trades, windows)
    tmp = trades.copy()
    tmp["block_category"] = cats
    tmp["block_title"] = titles
    blocked_df = tmp.loc[blocked_mask].copy()
    gated_df = tmp.loc[~blocked_mask].copy()
    blocked_metrics = _trade_metrics(blocked_df, initial_equity)
    gated_metrics = _trade_metrics(gated_df, initial_equity)
    return {
        "blocked_trades": int(blocked_metrics.get("trades", 0)),
        "blocked_categories": [str(x) for x in blocked_df["block_category"].replace("", pd.NA).dropna().astype(str).value_counts().head(5).index.tolist()],
        "blocked_titles": [str(x) for x in blocked_df["block_title"].replace("", pd.NA).dropna().astype(str).unique().tolist()[:5]],
        "gated": gated_metrics,
        "blocked": blocked_metrics,
    }


def _delta(base: dict[str, Any], gated: dict[str, Any]) -> tuple[float, float, float]:
    pnl_delta = float(gated.get("total_pnl", 0.0)) - float(base.get("total_pnl", 0.0))
    dd_delta = float(gated.get("max_drawdown", 0.0)) - float(base.get("max_drawdown", 0.0))
    score = dd_delta * 10000.0 + pnl_delta / 10000.0
    return pnl_delta, dd_delta, score


def _profile_score(base: dict[str, Any], gated: dict[str, Any], blocked: dict[str, Any]) -> float:
    dd_improve = float(gated.get("max_drawdown", 0.0)) - float(base.get("max_drawdown", 0.0))
    pnl_delta = float(gated.get("total_pnl", 0.0)) - float(base.get("total_pnl", 0.0))
    blocked_n = int(blocked.get("trades", 0))
    return dd_improve * 10000.0 + pnl_delta / 10000.0 + min(blocked_n, 20) * 0.5


def _calendar_year_folds(trades: pd.DataFrame, min_year: int = 2022) -> list[tuple[int, pd.Timestamp, pd.Timestamp]]:
    years = sorted(int(y) for y in trades["entry_time"].dt.year.unique() if int(y) >= min_year)
    folds: list[tuple[int, pd.Timestamp, pd.Timestamp]] = []
    for y in years:
        start = pd.Timestamp(f"{y}-01-01 00:00:00", tz="UTC")
        end = pd.Timestamp(f"{y + 1}-01-01 00:00:00", tz="UTC")
        folds.append((y, start, end))
    return folds


def _train_select_variant(train_trades: pd.DataFrame, profiles: list[tuple[str, str, pd.DataFrame]], initial_equity: float) -> dict[str, Any]:
    base_train = _trade_metrics(train_trades, initial_equity)
    diagnostics: list[dict[str, Any]] = []
    best_any: dict[str, Any] | None = None
    best_qualified: dict[str, Any] | None = None
    for key, label, windows in profiles:
        ev = _evaluate_variant(train_trades, windows, initial_equity)
        pnl_delta, dd_delta, _ = _delta(base_train, ev["gated"])
        blocked = int(ev["blocked_trades"])
        score = _profile_score(base_train, ev["gated"], ev["blocked"])
        row = {
            "key": key,
            "label": label,
            "blocked_trades": blocked,
            "pnl_delta": float(pnl_delta),
            "dd_delta": float(dd_delta),
            "score": float(score),
            "qualified": bool(blocked >= 1 and pnl_delta >= 0.0 and dd_delta >= 0.0 and score > 0.0),
        }
        diagnostics.append(row)
        if blocked >= 1 and (best_any is None or (score, blocked, pnl_delta) > (best_any["score"], best_any["blocked_trades"], best_any["pnl_delta"])):
            best_any = row
        if row["qualified"] and (best_qualified is None or (score, blocked, pnl_delta) > (best_qualified["score"], best_qualified["blocked_trades"], best_qualified["pnl_delta"])):
            best_qualified = row
    chosen = best_qualified or best_any
    return {
        "variant_key": "" if chosen is None else str(chosen["key"]),
        "variant_label": "" if chosen is None else str(chosen["label"]),
        "selection_mode": "" if chosen is None else ("qualified" if chosen.get("qualified") else "best_blocked"),
        "diagnostics": diagnostics,
        "base_train": base_train,
    }


def _aggregate_fold_metrics(folds: list[dict[str, Any]]) -> dict[str, Any]:
    out = {
        "folds": len(folds),
        "test_trades": sum(int(f["base_test"]["trades"]) for f in folds),
        "blocked_trades": sum(int(f["selected_test"]["blocked_trades"]) for f in folds),
        "pnl_delta": sum(float(f["selected_test"]["pnl_delta"]) for f in folds),
        "dd_delta": sum(float(f["selected_test"]["dd_delta"]) for f in folds),
        "non_negative_folds": sum(1 for f in folds if float(f["selected_test"]["pnl_delta"]) >= 0.0 and float(f["selected_test"]["dd_delta"]) >= 0.0),
        "chosen_non_empty_folds": sum(1 for f in folds if f["chosen_variant_key"]),
        "fallback_folds": sum(1 for f in folds if f.get("selection_mode") == "best_blocked"),
        "chosen_variant_union": sorted({str(f["chosen_variant_key"]) for f in folds if f["chosen_variant_key"]}),
    }
    return out


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    lines: list[str] = [
        "事件窗滚动样本外验证（expanding walk-forward）",
        f"生成时间(UTC): {pd.Timestamp.now(tz='UTC').strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "【全样本基线】",
        f"- trades: {payload['base_all']['trades']}",
        f"- total_pnl: {_fmt_num(float(payload['base_all']['total_pnl']))}",
        f"- max_drawdown(近似): {_fmt_pct(float(payload['base_all']['max_drawdown']))}",
        f"- profit_factor: {float(payload['base_all']['profit_factor']):.2f}",
        "",
        "【滚动样本外汇总】",
        f"- folds: {payload['oos_summary']['folds']}",
        f"- test_trades: {payload['oos_summary']['test_trades']}",
        f"- blocked_trades: {payload['oos_summary']['blocked_trades']}",
        f"- pnl_delta_sum: {_fmt_num(float(payload['oos_summary']['pnl_delta']))}",
        f"- dd_delta_sum: {_fmt_pct(float(payload['oos_summary']['dd_delta']))}",
        f"- non_negative_folds: {payload['oos_summary']['non_negative_folds']}",
        f"- chosen_non_empty_folds: {payload['oos_summary']['chosen_non_empty_folds']}",
        f"- fallback_folds: {payload['oos_summary']['fallback_folds']}",
        f"- chosen_variant_union: {payload['oos_summary']['chosen_variant_union'] or '-'}",
        "",
        "【逐年样本外】",
    ]
    for fold in payload['folds']:
        chosen_disp = fold['chosen_variant_key'] or '-'
        if fold.get('selection_mode') == 'best_blocked' and chosen_disp != '-':
            chosen_disp = f"{chosen_disp}(fallback)"
        lines.extend([
            f"- test_year {fold['test_year']} | chosen={chosen_disp} | test_trades={fold['base_test']['trades']} | blocked={fold['selected_test']['blocked_trades']} | pnl_delta={_fmt_num(float(fold['selected_test']['pnl_delta']))} | dd_delta={_fmt_pct(float(fold['selected_test']['dd_delta']))}",
        ])
    lines.extend(["", "【固定月度宏观近似窗（仅作参考）】"])
    for fold in payload['folds']:
        lines.append(
            f"- test_year {fold['test_year']} | fixed_blocked={fold['fixed_test']['blocked_trades']} | fixed_pnl_delta={_fmt_num(float(fold['fixed_test']['pnl_delta']))} | fixed_dd_delta={_fmt_pct(float(fold['fixed_test']['dd_delta']))}"
        )
    lines.extend(["", "【结论】"])
    for item in payload['conclusion']:
        lines.append(f"- {item}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="事件窗滚动样本外验证")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--events-csv", default="data/events/event_windows_v2.csv")
    ap.add_argument("--trades-csv", default="")
    ap.add_argument("--out", default="~/Downloads/event_window_walkforward_latest.txt")
    ap.add_argument("--min-test-year", type=int, default=2022)
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
    manual = _load_events((root / args.events_csv).resolve(), start_utc, end_utc)
    macro_rule = _generate_monthly_macro_windows(start_utc, end_utc)
    profiles = _profile_filters(manual, macro_rule)
    profile_map = {key: (label, windows.sort_values(["start_utc", "end_utc"]).reset_index(drop=True)) for key, label, windows in profiles}
    fixed_key = "manual_no_positive_plus_macro_rule"
    fixed_windows = profile_map.get(fixed_key, ("", manual.iloc[0:0].copy()))[1]
    base_all = _trade_metrics(trades, initial_equity)

    folds_payload: list[dict[str, Any]] = []
    for test_year, test_start, test_end in _calendar_year_folds(trades, min_year=args.min_test_year):
        train = trades[trades["entry_time"] < test_start].copy()
        test = trades[(trades["entry_time"] >= test_start) & (trades["entry_time"] < test_end)].copy()
        if test.empty or train.empty:
            continue
        base_test = _trade_metrics(test, initial_equity)

        train_selection = _train_select_variant(train, profiles, initial_equity)
        chosen_key = str(train_selection["variant_key"])
        chosen_label, selected_windows = profile_map.get(chosen_key, ("", manual.iloc[0:0].copy()))
        selected_eval = _evaluate_variant(test, selected_windows, initial_equity)
        sel_pnl_delta, sel_dd_delta, sel_score = _delta(base_test, selected_eval["gated"])

        fixed_eval = _evaluate_variant(test, fixed_windows, initial_equity)
        fixed_pnl_delta, fixed_dd_delta, fixed_score = _delta(base_test, fixed_eval["gated"])

        folds_payload.append({
            "test_year": int(test_year),
            "train_trades": int(len(train)),
            "test_trades": int(len(test)),
            "chosen_variant_key": chosen_key,
            "chosen_variant_label": str(chosen_label),
            "selection_mode": str(train_selection.get("selection_mode", "")),
            "train_profile_diagnostics": train_selection["diagnostics"],
            "base_test": base_test,
            "selected_test": {
                "blocked_trades": int(selected_eval["blocked_trades"]),
                "blocked_categories": selected_eval["blocked_categories"],
                "blocked_titles": selected_eval["blocked_titles"],
                "pnl_delta": float(sel_pnl_delta),
                "dd_delta": float(sel_dd_delta),
                "score": float(sel_score),
            },
            "fixed_test": {
                "blocked_trades": int(fixed_eval["blocked_trades"]),
                "blocked_categories": fixed_eval["blocked_categories"],
                "blocked_titles": fixed_eval["blocked_titles"],
                "pnl_delta": float(fixed_pnl_delta),
                "dd_delta": float(fixed_dd_delta),
                "score": float(fixed_score),
            },
        })

    oos_summary = _aggregate_fold_metrics(folds_payload)
    conclusion: list[str] = []
    if oos_summary["blocked_trades"] < 2:
        conclusion.append("滚动样本外真实被拦样本仍然 < 2，继续冻结为风险层。")
    if oos_summary["non_negative_folds"] < max(1, oos_summary["folds"] // 2):
        conclusion.append("滚动样本外没有显示跨年份稳定优势，不能升成 alpha。")
    if not oos_summary["chosen_variant_union"]:
        conclusion.append("训练端仍未形成稳定 profile，说明手工事件库对当前主线 trades 覆盖偏稀。")
    elif oos_summary["fallback_folds"] == oos_summary["chosen_non_empty_folds"]:
        conclusion.append("训练端目前只能回退到 best-blocked profile，说明事件窗仍像粗粒度风险筛而不是稳定 alpha。")
    elif oos_summary["chosen_variant_union"] == [fixed_key]:
        conclusion.append("训练端目前主要只会选到月度宏观近似窗；事件桥接仍停留在粗粒度 schedule 层。")
    else:
        conclusion.append("训练端已经开始在 profile 之间切换，但还不足以直接升成 runtime alpha。")
    conclusion.append("下一步继续扩事件覆盖，但优先保持 profile 口径与 sweep 一致。")

    payload = {
        "base_all": base_all,
        "folds": folds_payload,
        "oos_summary": oos_summary,
        "conclusion": conclusion,
        "inputs": {
            "trades_csv": str(trades_path),
            "events_csv": str((root / args.events_csv).resolve()),
            "min_test_year": int(args.min_test_year),
            "fixed_key": fixed_key,
        },
    }

    reports_dir = root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "event_window_walkforward_latest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    out_path = Path(os.path.expanduser(args.out)).resolve()
    _write_report(out_path, payload)
    print(json.dumps({"ok": True, "out": str(out_path), "folds": len(folds_payload), "blocked": oos_summary["blocked_trades"], "chosen": oos_summary["chosen_variant_union"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
