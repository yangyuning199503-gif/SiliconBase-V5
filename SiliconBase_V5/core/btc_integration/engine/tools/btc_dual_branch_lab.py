from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest.engine import run_backtest_portfolio
from src.backtest.io import load_ohlcv_csv, read_config


def _summarize_metrics(initial_equity: float, equity: pd.Series, trades: pd.DataFrame) -> dict[str, Any]:
    final_equity = float(equity.iloc[-1]) if len(equity) else float(initial_equity)
    total_return = final_equity / float(initial_equity) - 1.0 if initial_equity else float("nan")
    peak = equity.cummax() if len(equity) else equity
    dd = equity / peak - 1.0 if len(equity) else equity
    max_drawdown = float(dd.min()) if len(dd) else float("nan")
    if trades is None or trades.empty:
        profit_factor = float("nan")
        trades_n = 0
    else:
        pnl = pd.to_numeric(trades["pnl"], errors="coerce").fillna(0.0)
        gp = float(pnl[pnl > 0].sum())
        gl = float(-pnl[pnl < 0].sum())
        profit_factor = (gp / gl) if gl > 0 else (float("inf") if gp > 0 else float("nan"))
        trades_n = int(len(trades))
    return {
        "final_equity": final_equity,
        "total_return": total_return,
        "max_drawdown": max_drawdown,
        "profit_factor": profit_factor,
        "trades": trades_n,
    }

def _fmt_num(x: float | int | None) -> str:
    if x is None:
        return "NA"
    try:
        return f"{float(x):+.2f}"
    except Exception:
        return "NA"


def _fmt_pct(x: float | None) -> str:
    if x is None:
        return "NA"
    try:
        if math.isnan(float(x)):
            return "NA"
        return f"{float(x) * 100:.2f}%"
    except Exception:
        return "NA"


def _set_nested(cfg: dict[str, Any], path: str, value: Any) -> None:
    cur: dict[str, Any] = cfg
    keys = path.split(".")
    for key in keys[:-1]:
        nxt = cur.get(key)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[key] = nxt
        cur = nxt
    cur[keys[-1]] = value


def _pf(df: pd.DataFrame) -> float:
    if df is None or df.empty or "pnl" not in df.columns:
        return float("nan")
    pnl = pd.to_numeric(df["pnl"], errors="coerce").fillna(0.0)
    gp = float(pnl[pnl > 0].sum())
    gl = float(-pnl[pnl < 0].sum())
    if gl <= 0:
        return float("inf") if gp > 0 else float("nan")
    return gp / gl


def _safe_float(x: Any) -> float:
    try:
        v = float(x)
    except Exception:
        return float("nan")
    return v


def _segment_pfs(trades: pd.DataFrame) -> dict[str, float]:
    if trades is None or trades.empty:
        return {"2020-2021": float("nan"), "2022-2023": float("nan"), "2024-2026": float("nan")}
    df = trades.copy()
    df["exit_time"] = pd.to_datetime(df["exit_time"], errors="coerce")
    df = df.dropna(subset=["exit_time"])
    return {
        "2020-2021": _pf(df[df["exit_time"].dt.year <= 2021]),
        "2022-2023": _pf(df[(df["exit_time"].dt.year >= 2022) & (df["exit_time"].dt.year <= 2023)]),
        "2024-2026": _pf(df[df["exit_time"].dt.year >= 2024]),
    }


def _active_months(trades: pd.DataFrame) -> int:
    if trades is None or trades.empty:
        return 0
    df = trades.copy()
    df["exit_time"] = pd.to_datetime(df["exit_time"], errors="coerce")
    df = df.dropna(subset=["exit_time"])
    if df.empty:
        return 0
    return int(df["exit_time"].dt.to_period("M").nunique())


def _side_counts(trades: pd.DataFrame) -> dict[str, int]:
    if trades is None or trades.empty:
        return {"LONG": 0, "SHORT": 0}
    vc = trades["side"].astype(str).str.upper().value_counts()
    return {"LONG": int(vc.get("LONG", 0)), "SHORT": int(vc.get("SHORT", 0))}


def _score_row(row: dict[str, Any]) -> float:
    pf = _safe_float(row.get("profit_factor"))
    trades = int(row.get("trades", 0) or 0)
    mdd = abs(_safe_float(row.get("max_drawdown")))
    short_share = _safe_float(row.get("short_share"))
    total_return = _safe_float(row.get("total_return"))
    seg_min_pf = _safe_float(row.get("seg_min_pf"))
    if math.isnan(pf):
        pf = 0.0
    if math.isnan(short_share):
        short_share = 0.0
    if math.isnan(seg_min_pf):
        seg_min_pf = 0.0
    if math.isnan(total_return):
        total_return = -1.0
    score = pf * 100.0
    score += min(trades, 220) * 0.25
    score -= mdd * 80.0
    score += short_share * 20.0
    score += seg_min_pf * 10.0
    if total_return <= 0:
        score -= 15.0
    return float(score)


def _decision(row: dict[str, Any], base_trades: int) -> str:
    pf = _safe_float(row.get("profit_factor"))
    total_return = _safe_float(row.get("total_return"))
    seg_min_pf = _safe_float(row.get("seg_min_pf"))
    trades = int(row.get("trades", 0) or 0)
    short_share = _safe_float(row.get("short_share"))
    if math.isnan(pf):
        return "淘汰"
    if pf >= 1.10 and total_return > 0 and seg_min_pf >= 0.95 and trades >= max(base_trades + 20, 90):
        if short_share >= 0.15:
            return "继续深挖"
        return "继续研究"
    if pf >= 0.90 and trades > base_trades:
        return "保留观察"
    return "淘汰"


def _load_btc_data(root: Path, cfg: dict[str, Any]) -> dict[str, pd.DataFrame]:
    data_cfg = cfg.get("data", {})
    csv_template = str(data_cfg.get("csv_template", "data/raw/{symbol}_15m.csv"))
    start = pd.to_datetime(data_cfg.get("start"), utc=True).tz_convert(None) if data_cfg.get("start") else None
    end = pd.to_datetime(data_cfg.get("end"), utc=True).tz_convert(None) if data_cfg.get("end") else None
    path = root / csv_template.format(symbol="btc")
    if not path.exists():
        raise SystemExit(f"缺少 BTC 原始数据：{path}")
    df = load_ohlcv_csv(path)
    if start is not None:
        df = df.loc[df.index >= start]
    if end is not None:
        df = df.loc[df.index <= end]
    return {"btc": df}


def _run_candidate(root: Path, base_cfg: dict[str, Any], btc_data: dict[str, pd.DataFrame], name: str, mods: dict[str, Any]) -> dict[str, Any]:
    cfg = copy.deepcopy(base_cfg)
    cfg["data"]["symbols"] = ["btc"]
    cfg["data"]["weights"] = {"btc": 1.0}
    for path, value in mods.items():
        _set_nested(cfg, path, value)

    equity, trades, snapshot = run_backtest_portfolio(btc_data, cfg)
    metrics = _summarize_metrics(float(cfg["portfolio"]["initial_equity"]), equity["equity"], trades)
    counts = _side_counts(trades)
    total_trades = int(metrics.get("trades", 0) or 0)
    short_share = float(counts["SHORT"] / total_trades) if total_trades > 0 else 0.0
    seg = _segment_pfs(trades)
    finite_seg = [v for v in seg.values() if not math.isnan(v)]
    seg_min_pf = min(finite_seg) if finite_seg else float("nan")
    row = {
        "name": name,
        "trades": total_trades,
        "long_trades": counts["LONG"],
        "short_trades": counts["SHORT"],
        "short_share": short_share,
        "profit_factor": _safe_float(metrics.get("profit_factor")),
        "total_return": _safe_float(metrics.get("total_return")),
        "max_drawdown": _safe_float(metrics.get("max_drawdown")),
        "active_months": _active_months(trades),
        "seg_pf": seg,
        "seg_min_pf": seg_min_pf,
        "final_equity": _safe_float(metrics.get("final_equity")),
    }
    row["score"] = _score_row(row)
    row["snapshot_final_positions"] = snapshot.get("final_positions", {})
    return row


QUICK_CANDIDATES: list[dict[str, Any]] = [
    {
        "name": "btc_base_mainline",
        "mods": {},
        "note": "当前 BTC 主线（对照组）",
    },
    {
        "name": "btc_dual_fast_trend_4h",
        "mods": {
            "strategy_params.cooldown_bars": 8,
            "strategy_params.breakout_lookback": 20,
            "filters.btc_breakout_atr_buffer": 0.6,
            "filters.btc_adx_floor": 24,
            "filters.macro_gate_tf_by_symbol.btc": "4h",
            "filters.btc_short_macro_tf": "4h",
        },
        "note": "短频双向 trend 分支（更快，但仍复用当前 TREND 逻辑）",
    },
    {
        "name": "btc_dual_shortwave_sr",
        "mods": {
            "filters.btc_breakout_atr_buffer": 9.0,
            "filters.btc_adx_floor": 99,
            "sr_entries.enabled": True,
            "sr_entries.symbols": ["btc"],
            "sr_entries.lookback_4h": 24,
            "sr_entries.zone_atr_mult": 0.4,
            "sr_entries.use_adx_filter": True,
            "sr_entries.adx_min": 0.0,
            "sr_entries.adx_max": 25.0,
            "sr_entries.stake_scale": 0.6,
            "sr_entries.cooldown_bars": 12,
            "sr_entries.require_compress_ok": True,
        },
        "note": "短波/SR 双向分支（压制 TREND，只看 4H 支撑阻力回拉）",
    },
]

FULL_EXTRA_CANDIDATES: list[dict[str, Any]] = [
    {
        "name": "btc_long_fast_4h",
        "mods": {
            "strategy_params.allow_short": False,
            "strategy_params.cooldown_bars": 8,
            "strategy_params.breakout_lookback": 20,
            "filters.btc_breakout_atr_buffer": 0.6,
            "filters.btc_adx_floor": 24,
            "filters.macro_gate_tf_by_symbol.btc": "4h",
        },
        "note": "更快的 BTC long-only 趋势腿（第二引擎候选）",
    },
    {
        "name": "btc_dual_mid_trend_4h",
        "mods": {
            "strategy_params.cooldown_bars": 12,
            "strategy_params.breakout_lookback": 24,
            "filters.btc_breakout_atr_buffer": 0.7,
            "filters.btc_adx_floor": 24,
            "filters.macro_gate_tf_by_symbol.btc": "4h",
            "filters.btc_short_macro_tf": "4h",
        },
        "note": "稍慢一点的 BTC 双向 trend 变体",
    },
]


def _write_outputs(lines: list[str], payload: dict[str, Any], out_txt: Path, out_json: Path) -> None:
    out_txt.parent.mkdir(parents=True, exist_ok=True)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="BTC 第二分支研究：先做 research，不改 live")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--profile", choices=["quick", "full"], default="quick")
    ap.add_argument("--out", default=str(Path.home() / "Downloads" / "btc_dual_branch_lab_latest.txt"))
    ap.add_argument("--json-out", default=str(Path.home() / "Downloads" / "btc_dual_branch_lab_latest.json"))
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    out_txt = Path(args.out).expanduser().resolve()
    out_json = Path(args.json_out).expanduser().resolve()

    cfg = read_config(root / "config.yml")
    version = cfg.get("system", {}).get("version", "NA")
    btc_rows = 0
    btc_start = None
    btc_end = None

    try:
        btc_data = _load_btc_data(root, cfg)
        btc_df = btc_data.get("btc", pd.DataFrame())
        btc_rows = int(len(btc_df))
        if btc_rows:
            btc_start = str(btc_df.index.min())
            btc_end = str(btc_df.index.max())

        candidates = list(QUICK_CANDIDATES)
        if args.profile == "full":
            candidates.extend(FULL_EXTRA_CANDIDATES)

        rows: list[dict[str, Any]] = []
        notes: dict[str, str] = {}
        for item in candidates:
            row = _run_candidate(root, cfg, btc_data, item["name"], item["mods"])
            rows.append(row)
            notes[item["name"]] = item.get("note", "")

        base_row = next((r for r in rows if r["name"] == "btc_base_mainline"), rows[0])
        base_trades = int(base_row.get("trades", 0) or 0)

        for row in rows:
            row["decision"] = _decision(row, base_trades=base_trades)
            row["note"] = notes.get(row["name"], "")

        rows_sorted = sorted(rows, key=lambda r: (r["decision"] == "继续深挖", r["decision"] == "继续研究", r["score"]), reverse=True)
        best = rows_sorted[0] if rows_sorted else None

        lines: list[str] = []
        lines.append("BTC 第二分支实验室（只做 research，不改 live）")
        lines.append(f"profile: {args.profile}")
        lines.append(f"version: {version}")
        lines.append(f"btc_rows: {btc_rows}")
        lines.append(f"btc_range: {btc_start or 'NA'} -> {btc_end or 'NA'}")
        lines.append("")

        lines.append("=== 候选结果 ===")
        for row in rows_sorted:
            seg_min_text = 'NA' if math.isnan(row['seg_min_pf']) else f"{row['seg_min_pf']:.3f}"
            lines.append(
                f"- {row['name']}: trades={row['trades']} | long={row['long_trades']} | short={row['short_trades']} "
                f"| short_share={_fmt_pct(row['short_share'])} | PF={row['profit_factor']:.3f} | "
                f"ret={_fmt_pct(row['total_return'])} | maxDD={_fmt_pct(row['max_drawdown'])} | "
                f"seg_min_pf={seg_min_text} | active_months={row['active_months']} | decision={row['decision']}"
            )
            lines.append(f"  note: {row['note']}")
            lines.append(
                f"  seg_pf: 2020-2021={row['seg_pf']['2020-2021']}, "
                f"2022-2023={row['seg_pf']['2022-2023']}, 2024-2026={row['seg_pf']['2024-2026']}"
            )

        lines.append("")
        lines.append("=== 结论 ===")
        if best is None:
            lines.append("- 无结果。")
        else:
            lines.append(f"- 当前最优候选：{best['name']} | decision={best['decision']}")
            if best["decision"] in ("淘汰", "保留观察"):
                lines.append("- 说明：当前 BTC 快速双向/短波分支还没有达到可并入标准。继续保留为 research。")
            if best["name"] == "btc_dual_fast_trend_4h" and best["short_trades"] <= 5:
                lines.append("- 关键问题：所谓‘双向短频’实际上仍几乎全是 LONG，SHORT 参与度太低，说明当前 TREND 逻辑不适合作为双向短波第二引擎。")
            if best["name"] == "btc_dual_shortwave_sr" and best["profit_factor"] < 1.0:
                lines.append("- 关键问题：SR/短波方向虽然双向更平衡，但收益质量明显不达标，当前不能并入。")
            lines.append("- 下一步建议：保留消息面联动回测；第二分支继续做 BTC 专属短波研究，但必须改为独立 entry logic，而不是简单复用主线 TREND。")

        payload = {
            "status": "ok",
            "profile": args.profile,
            "version": version,
            "btc_rows": btc_rows,
            "btc_start": btc_start,
            "btc_end": btc_end,
            "rows": rows_sorted,
            "best": best,
        }
        _write_outputs(lines, payload, out_txt, out_json)
        print("\n".join(lines))
    except Exception as exc:
        lines = [
            "BTC 第二分支实验室（只做 research，不改 live）",
            f"profile: {args.profile}",
            f"version: {version}",
            "status: skipped",
            f"reason: {exc}",
            f"btc_rows: {btc_rows}",
            f"btc_range: {btc_start or 'NA'} -> {btc_end or 'NA'}",
            "",
            "=== 结论 ===",
            "- 本轮 BTC quick lab 已跳过，不中断主线/ETH/SOL 联合优化。",
            "- 优先检查 btc_15m.csv 的时间列是否混有秒/ms/us/ns，或时间范围是否偏短。",
            "- 本轮 stage108 会继续导出其余联合结果。",
        ]
        payload = {
            "status": "skipped",
            "profile": args.profile,
            "version": version,
            "reason": str(exc),
            "btc_rows": btc_rows,
            "btc_start": btc_start,
            "btc_end": btc_end,
        }
        _write_outputs(lines, payload, out_txt, out_json)
        print("\n".join(lines))
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
