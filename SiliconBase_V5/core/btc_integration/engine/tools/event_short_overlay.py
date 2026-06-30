from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in (None, ''):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


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
    if "exit_time" in df.columns:
        df = df.sort_values("exit_time")
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
    cands: list[Path] = []
    reports = root / "reports"
    if reports.exists():
        cands.extend(sorted(reports.glob("run_*/trades.csv")))
    if (root / "run_latest" / "trades.csv").exists():
        cands.append(root / "run_latest" / "trades.csv")
    if not cands:
        raise SystemExit("未找到 trades.csv；请先执行 bash run.sh")
    cands.sort(key=lambda p: (p.stat().st_mtime, str(p)), reverse=True)
    return cands[0]


def _load_events(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    for col in ["start_utc", "end_utc"]:
        df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")
    df = df.dropna(subset=["start_utc", "end_utc"]).copy()
    if "enabled" in df.columns:
        df = df[df["enabled"].astype(str).isin(["1", "True", "true", "TRUE", "yes", "Y"])]
    if "severity" not in df.columns:
        df["severity"] = "medium"
    if "event_mode" not in df.columns:
        df["event_mode"] = "risk_off"
    if "group_id" not in df.columns:
        df["group_id"] = df["title"].astype(str)
    return df.reset_index(drop=True)


def _prepare_trades(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["entry_time"] = pd.to_datetime(df["entry_time"], utc=True, errors="coerce")
    df["exit_time"] = pd.to_datetime(df["exit_time"], utc=True, errors="coerce")
    df = df.dropna(subset=["entry_time", "exit_time"]).copy()
    df["symbol"] = df["symbol"].astype(str).str.lower()
    df["side"] = df["side"].astype(str).str.upper()
    df["pnl"] = pd.to_numeric(df["pnl"], errors="coerce").fillna(0.0)
    return df


def _profile_mask(events: pd.DataFrame, profile: str) -> pd.Series:
    cat = events["category"].astype(str)
    sev = events["severity"].astype(str).str.lower()
    mode = events["event_mode"].astype(str).str.lower()
    neg_mode = mode.isin(["risk_off", "two_sided"])
    hi = sev.isin(["high", "critical"])

    if profile == "shock_hi":
        return neg_mode & hi & cat.isin(["crypto", "policy", "us_equity", "war", "macro"])
    if profile == "crypto_policy_war":
        return neg_mode & hi & cat.isin(["crypto", "policy", "war"])
    if profile == "equity_policy":
        return neg_mode & hi & cat.isin(["us_equity", "policy", "war"])
    if profile == "all_negative":
        return neg_mode & cat.isin(["crypto", "policy", "us_equity", "war", "macro"])
    raise KeyError(profile)


def _match_entry_window(shorts: pd.DataFrame, windows: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if shorts.empty:
        return pd.DataFrame(columns=['trade_idx','matched','groups','categories','titles'])
    for idx, tr in shorts.iterrows():
        ts = tr["entry_time"]
        matched = windows[(windows["start_utc"] <= ts) & (windows["end_utc"] >= ts)]
        rows.append(
            {
                "trade_idx": idx,
                "matched": not matched.empty,
                "groups": sorted(set(matched["group_id"].astype(str).tolist())),
                "categories": sorted(set(matched["category"].astype(str).tolist())),
                "titles": matched["title"].astype(str).tolist(),
            }
        )
    return pd.DataFrame(rows)


def _apply_overlay(trades: pd.DataFrame, selected_trade_idx: set[int], scale: float) -> pd.DataFrame:
    out = trades.copy()
    mask = out.index.isin(selected_trade_idx)
    out.loc[mask, "pnl"] = out.loc[mask, "pnl"] * float(scale)
    return out


def _score(base: dict[str, Any], alt: dict[str, Any]) -> float:
    pnl_delta = float(alt.get("total_pnl", 0.0)) - float(base.get("total_pnl", 0.0))
    dd_delta = float(alt.get("max_drawdown", 0.0)) - float(base.get("max_drawdown", 0.0))
    return pnl_delta / 10000.0 + (-dd_delta * 10000.0)


def _evaluate(trades: pd.DataFrame, events: pd.DataFrame, initial_equity: float, profile: str, scale: float) -> dict[str, Any]:
    prof_events = events.loc[_profile_mask(events, profile)].copy()
    shorts = trades[(trades["symbol"] == "btc") & (trades["side"] == "SHORT")].copy()
    match = _match_entry_window(shorts, prof_events)
    selected = set(match.loc[match["matched"], "trade_idx"].astype(int).tolist())
    alt = _apply_overlay(trades, selected, scale)
    base_m = _trade_metrics(trades, initial_equity)
    alt_m = _trade_metrics(alt, initial_equity)
    return {
        "profile": profile,
        "scale": float(scale),
        "selected_trades": int(len(selected)),
        "selected_groups": sorted({g for arr in match.loc[match["matched"], "groups"].tolist() for g in arr})[:10],
        "selected_categories": sorted({g for arr in match.loc[match["matched"], "categories"].tolist() for g in arr}),
        "base": base_m,
        "alt": alt_m,
        "pnl_delta": float(alt_m["total_pnl"] - base_m["total_pnl"]),
        "dd_delta": float(alt_m["max_drawdown"] - base_m["max_drawdown"]),
        "score": float(_score(base_m, alt_m)),
    }


def _walkforward(trades: pd.DataFrame, events: pd.DataFrame, initial_equity: float, profiles: list[str], scales: list[float]) -> dict[str, Any]:
    years = sorted(y for y in trades["entry_time"].dt.year.unique() if int(y) >= 2022)
    rows: list[dict[str, Any]] = []
    total_selected = 0
    total_pnl = 0.0
    total_dd = 0.0
    chosen_any = []
    for year in years:
        train = trades[trades["entry_time"].dt.year < year].copy()
        test = trades[trades["entry_time"].dt.year == year].copy()
        if train.empty or test.empty:
            continue
        _trade_metrics(train, initial_equity)
        best: dict[str, Any] | None = None
        for p in profiles:
            for s in scales:
                res = _evaluate(train, events, initial_equity, p, s)
                # 审慎门槛：至少命中 2 笔，且收益/回撤均非负优化
                if res["selected_trades"] < 2:
                    continue
                if res["pnl_delta"] <= 0 or res["dd_delta"] < 0:
                    continue
                if best is None or res["score"] > best["score"]:
                    best = res
        if best is None:
            rows.append({"test_year": int(year), "chosen": "-", "selected": 0, "pnl_delta": 0.0, "dd_delta": 0.0})
            continue
        chosen_any.append(f"{best['profile']}@x{best['scale']}")
        test_res = _evaluate(test, events, initial_equity, str(best["profile"]), float(best["scale"]))
        total_selected += int(test_res["selected_trades"])
        total_pnl += float(test_res["pnl_delta"])
        total_dd += float(test_res["dd_delta"])
        rows.append({
            "test_year": int(year),
            "chosen": f"{best['profile']}@x{best['scale']}",
            "selected": int(test_res["selected_trades"]),
            "pnl_delta": float(test_res["pnl_delta"]),
            "dd_delta": float(test_res["dd_delta"]),
        })
    return {
        "rows": rows,
        "selected_trades": int(total_selected),
        "pnl_delta_sum": float(total_pnl),
        "dd_delta_sum": float(total_dd),
        "chosen_non_empty_folds": int(sum(1 for r in rows if r["chosen"] != "-")),
        "chosen_set": sorted(set(chosen_any)),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="黑天鹅做空 overlay A/B：只放大既有 BTC 技术空单，不新增裸空")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--events", default="data/events/event_windows_v4.csv")
    ap.add_argument("--out", default=str(Path.home() / "Downloads" / "event_short_overlay_latest.txt"))
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    out = Path(args.out).expanduser().resolve()
    trades_path = _find_latest_trades_csv(root)
    events_path = root / args.events
    if not events_path.exists():
        raise SystemExit(f"事件库不存在：{events_path}")

    trades = _prepare_trades(trades_path)
    events = _load_events(events_path)
    initial_equity = 100000.0

    base = _trade_metrics(trades, initial_equity)
    btc_shorts = trades[(trades["symbol"] == "btc") & (trades["side"] == "SHORT")].copy()

    profiles = ["shock_hi", "crypto_policy_war", "equity_policy", "all_negative"]
    scales = [1.25, 1.5, 2.0]
    full_rows = []
    for p in profiles:
        for s in scales:
            full_rows.append(_evaluate(trades, events, initial_equity, p, s))
    full_rows.sort(key=lambda x: (x["score"], x["pnl_delta"]), reverse=True)
    wf = _walkforward(trades, events, initial_equity, profiles, scales)

    lines: list[str] = []
    lines.append("黑天鹅做空 overlay A/B（只放大既有 BTC 技术空单，不新增裸空）")
    lines.append(f"生成时间(UTC): {pd.Timestamp.utcnow().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("【基线】")
    lines.append(f"- trades: {base['trades']}")
    lines.append(f"- total_pnl: {_fmt_num(base['total_pnl'])}")
    lines.append(f"- total_return(近似): {base['total_return']*100:.2f}%")
    lines.append(f"- max_drawdown(近似): {_fmt_pct(base['max_drawdown'])}")
    lines.append(f"- profit_factor: {base['profit_factor']:.2f}")
    lines.append(f"- btc_short_trades: {int(len(btc_shorts))}")
    lines.append("")
    lines.append("【全样本 Sweep（前6）】")
    for r in full_rows[:6]:
        lines.append(
            f"- {r['profile']} @ x{r['scale']}: selected={r['selected_trades']} pnl_delta={_fmt_num(r['pnl_delta'])} dd_delta={_fmt_pct(r['dd_delta'])} cats={r['selected_categories'] or '-'}"
        )
    lines.append("")
    lines.append("【严格滚动样本外】")
    lines.append(f"- selected_trades: {wf['selected_trades']}")
    lines.append(f"- pnl_delta_sum: {_fmt_num(wf['pnl_delta_sum'])}")
    lines.append(f"- dd_delta_sum: {_fmt_pct(wf['dd_delta_sum'])}")
    lines.append(f"- chosen_non_empty_folds: {wf['chosen_non_empty_folds']}")
    lines.append(f"- chosen_set: {wf['chosen_set'] or '-'}")
    lines.append("")
    lines.append("【逐年样本外】")
    for row in wf["rows"]:
        lines.append(
            f"- test_year {row['test_year']} | chosen={row['chosen']} | selected={row['selected']} | pnl_delta={_fmt_num(row['pnl_delta'])} | dd_delta={_fmt_pct(row['dd_delta'])}"
        )
    lines.append("")
    lines.append("【结论】")
    best = full_rows[0] if full_rows else None
    if best is None:
        lines.append("- 没有可评估结果。")
    elif wf["selected_trades"] <= 0:
        lines.append("- 当前证据不足以支持把黑天鹅直接升成做空 alpha；先不要新增裸空。")
        lines.append("- 更稳的方向是：仅在负面事件窗内，放大既有 BTC 技术空单；但要继续扩样本。")
    else:
        lines.append("- 事件做空 overlay 在样本外出现了有效命中，可继续扩大验证。")
    lines.append("- 当前实验目标是检验“负面事件是否值得放大 BTC 技术空单”，不是用新闻单独开空。")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
