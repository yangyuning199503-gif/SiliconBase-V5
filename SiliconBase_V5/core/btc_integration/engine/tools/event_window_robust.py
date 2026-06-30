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


def _narrow_profile(manual: pd.DataFrame) -> pd.DataFrame:
    allowed_categories = {"us_equity", "war", "policy", "crypto", "macro"}
    allowed_modes = {"risk_off", "two_sided"}
    out = manual[
        manual["category"].astype(str).isin(allowed_categories)
        & manual["event_mode"].astype(str).isin(allowed_modes)
    ].copy()
    # 防过拟合：默认不加入正面催化，不加入月度规则窗
    return out.sort_values(["start_utc", "end_utc"]).reset_index(drop=True)


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
        "sample": blocked_df[["entry_time", "symbol", "pnl", "block_category", "block_title"]].head(10).assign(entry_time=lambda x: x["entry_time"].astype(str)).to_dict("records"),
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
    int(max(1, ((end_utc - start_utc) // FREQ)))
    for _, row in ordered.iterrows():
        duration = row["duration"]
        latest_start = end_utc - duration
        if latest_start <= start_utc:
            s = start_utc
            e = start_utc + duration
        else:
            max_slot = int((latest_start - start_utc) // FREQ)
            placed = None
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
            "title": f"placebo:{row.get('category', 'event')}",
            "event_mode": row.get("event_mode", "risk_off"),
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


def _shift_stress(trades: pd.DataFrame, windows: pd.DataFrame, initial_equity: float, base_metrics: dict[str, Any], shift_days: list[int]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    trade_start = trades["entry_time"].min()
    trade_end = trades["entry_time"].max()
    for d in shift_days:
        shifted = windows.copy()
        delta = pd.Timedelta(days=d)
        shifted["start_utc"] = shifted["start_utc"] + delta
        shifted["end_utc"] = shifted["end_utc"] + delta
        shifted = shifted[(shifted["end_utc"] >= trade_start) & (shifted["start_utc"] <= trade_end)].copy()
        res = _evaluate_variant(trades, shifted, initial_equity)
        pnl_delta, dd_delta, score = _delta(base_metrics, res["gated"])
        out.append({
            "shift_days": d,
            "blocked_trades": int(res["blocked_trades"]),
            "pnl_delta": float(pnl_delta),
            "dd_delta": float(dd_delta),
            "score": float(score),
        })
    return out


def _leave_one_event_out(trades: pd.DataFrame, windows: pd.DataFrame, initial_equity: float, base_metrics: dict[str, Any]) -> list[dict[str, Any]]:
    observed = _evaluate_variant(trades, windows, initial_equity)
    title_hits = observed["blocked_titles"]
    if not title_hits:
        return []
    out: list[dict[str, Any]] = []
    for title in title_hits:
        reduced = windows[windows["title"].astype(str) != title].copy()
        res = _evaluate_variant(trades, reduced, initial_equity)
        pnl_delta, dd_delta, score = _delta(base_metrics, res["gated"])
        out.append({
            "removed_title": title,
            "blocked_trades": int(res["blocked_trades"]),
            "pnl_delta": float(pnl_delta),
            "dd_delta": float(dd_delta),
            "score": float(score),
        })
    return out


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    base = payload["base"]
    obs = payload["observed"]
    placebo = payload["placebo"]
    shift = payload["shift_stress"]
    loeo = payload["leave_one_event_out"]
    lines = [
        "事件窗防过拟合检查（placebo + shift stress + LOEO）",
        f"生成时间(UTC): {pd.Timestamp.now(tz='UTC').strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "【基线】",
        f"- trades: {base.get('trades', 0)}",
        f"- total_pnl: {_fmt_num(float(base.get('total_pnl', 0.0)))}",
        f"- max_drawdown(近似): {_fmt_pct(float(base.get('max_drawdown', 0.0)))}",
        f"- profit_factor: {float(base.get('profit_factor', 0.0)):.2f}",
        "",
        "【观测到的窄事件窗】",
        f"- event_rows: {payload['window'].get('event_rows', 0)}",
        f"- blocked_trades: {obs.get('blocked_trades', 0)}",
        f"- pnl_delta: {_fmt_num(float(obs.get('pnl_delta', 0.0)))}",
        f"- maxdd_delta: {_fmt_pct(float(obs.get('dd_delta', 0.0)))}",
        f"- blocked_categories: {obs.get('blocked_categories') or '-'}",
        f"- blocked_titles: {obs.get('blocked_titles') or '-'}",
        "",
        "【Placebo 随机窗】",
        f"- runs: {placebo.get('runs', 0)}",
        f"- blocked_trades_median: {placebo.get('blocked_trades_median', 0):.1f}",
        f"- pnl_delta median/p90/p95: {_fmt_num(float(placebo.get('pnl_delta_median', 0.0)))}/{_fmt_num(float(placebo.get('pnl_delta_p90', 0.0)))}/{_fmt_num(float(placebo.get('pnl_delta_p95', 0.0)))}",
        f"- dd_delta median/p90/p95: {_fmt_pct(float(placebo.get('dd_delta_median', 0.0)))}/{_fmt_pct(float(placebo.get('dd_delta_p90', 0.0)))}/{_fmt_pct(float(placebo.get('dd_delta_p95', 0.0)))}",
        f"- empirical p(pnl): {float(placebo.get('p_pnl', 1.0)):.3f}",
        f"- empirical p(dd): {float(placebo.get('p_dd', 1.0)):.3f}",
        f"- empirical p(score): {float(placebo.get('p_score', 1.0)):.3f}",
        "",
        "【Shift stress】",
    ]
    for row in shift:
        lines.append(
            f"- shift {row['shift_days']:+d}d -> blocked={row['blocked_trades']} pnl_delta={_fmt_num(float(row['pnl_delta']))} dd_delta={_fmt_pct(float(row['dd_delta']))}"
        )
    lines.append("")
    lines.append("【Leave-one-event-out】")
    if not loeo:
        lines.append("- 当前无被拦事件，LOEO 无样本。")
    else:
        for row in loeo:
            lines.append(
                f"- remove [{row['removed_title']}] -> blocked={row['blocked_trades']} pnl_delta={_fmt_num(float(row['pnl_delta']))} dd_delta={_fmt_pct(float(row['dd_delta']))}"
            )
    lines.append("")
    lines.append("【结论】")
    for c in payload.get("conclusion", []):
        lines.append(f"- {c}")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="事件窗防过拟合检查")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--events-csv", default="data/events/event_windows_v2.csv")
    ap.add_argument("--out", default="~/Downloads/event_window_robust_latest.txt")
    ap.add_argument("--trades-csv", default="")
    ap.add_argument("--placebo-runs", type=int, default=500)
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
    manual = _load_events((root / args.events_csv).resolve(), start_utc, end_utc)
    windows = _narrow_profile(manual)

    base_metrics = _trade_metrics(trades, initial_equity)
    observed_eval = _evaluate_variant(trades, windows, initial_equity)
    obs_pnl_delta, obs_dd_delta, obs_score = _delta(base_metrics, observed_eval["gated"])

    placebo = _placebo_test(trades, windows, initial_equity, base_metrics, args.placebo_runs, args.seed)
    p_pnl = (sum(1 for x in placebo["pnl_deltas"] if x >= obs_pnl_delta) + 1) / (len(placebo["pnl_deltas"]) + 1)
    p_dd = (sum(1 for x in placebo["dd_deltas"] if x >= obs_dd_delta) + 1) / (len(placebo["dd_deltas"]) + 1)
    p_score = (sum(1 for x in placebo["scores"] if x >= obs_score) + 1) / (len(placebo["scores"]) + 1)
    placebo.update({"p_pnl": float(p_pnl), "p_dd": float(p_dd), "p_score": float(p_score)})

    shift = _shift_stress(trades, windows, initial_equity, base_metrics, shift_days=[-5, -3, -2, -1, 1, 2, 3, 5])
    loeo = _leave_one_event_out(trades, windows, initial_equity, base_metrics)

    conclusion: list[str] = []
    if int(observed_eval["blocked_trades"]) < 2:
        conclusion.append("真实被拦样本 < 2，仍然不能升成 alpha。")
    if p_score > 0.10:
        conclusion.append("placebo 未显示明显超额优势，继续冻结为风险层。")
    else:
        conclusion.append("placebo 显示一定优势，但也只允许保留窄事件窗。")
    unstable_shift = [row for row in shift if row["blocked_trades"] > 0 and (row["pnl_delta"] > obs_pnl_delta * 0.5 or row["dd_delta"] > obs_dd_delta * 0.5)]
    if unstable_shift:
        conclusion.append("对 ±1~5 天平移较敏感，说明仍有时间对齐过拟合风险。")
    if loeo and any(row["blocked_trades"] == 0 for row in loeo):
        conclusion.append("移除单一关键事件后优势消失，结果依赖单事件。")
    conclusion.append("下一步只扩样本，不新增规则复杂度。")

    payload = {
        "base": base_metrics,
        "window": {
            "trades_csv": str(trades_path),
            "event_rows": int(len(windows)),
            "trade_range_utc": f"{start_utc} -> {end_utc}",
        },
        "observed": {
            "blocked_trades": int(observed_eval["blocked_trades"]),
            "blocked_categories": observed_eval["blocked_categories"],
            "blocked_titles": observed_eval["blocked_titles"],
            "pnl_delta": float(obs_pnl_delta),
            "dd_delta": float(obs_dd_delta),
            "score": float(obs_score),
            "sample": observed_eval["sample"],
        },
        "placebo": placebo,
        "shift_stress": shift,
        "leave_one_event_out": loeo,
        "conclusion": conclusion,
    }

    reports_dir = root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "event_window_robust_latest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    out_path = Path(os.path.expanduser(args.out)).resolve()
    _write_report(out_path, payload)
    print(json.dumps({"ok": True, "out": str(out_path), "blocked": payload['observed']['blocked_trades'], "p_score": p_score}, ensure_ascii=False))


if __name__ == "__main__":
    main()
