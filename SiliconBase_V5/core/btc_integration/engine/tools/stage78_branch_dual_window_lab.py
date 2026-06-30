from __future__ import annotations

import argparse
import contextlib
import copy
import json
import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


try:
    from tools import research_config_baseline as rcb
    from tools import stage46_aggressive_lab as s46
    from tools import stage59_structural_lab as s59
    from tools import stage76_branch_event_state_lab as s76
except Exception as exc:
    raise SystemExit("缺少 stage46/stage59/stage76 模块，请先保留此前补丁。") from exc

RECENT_START = pd.Timestamp("2024-01-01", tz=None)
DAYS_PER_MONTH = 30.4375


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
    except Exception:
        return default
    if math.isnan(v):
        return default
    return v


def _fmt_pct(x: Any) -> str:
    try:
        return f"{float(x) * 100:.2f}%"
    except Exception:
        return "NA"


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


def _window_bounds_from_data(data: dict[str, pd.DataFrame]) -> tuple[pd.Timestamp, pd.Timestamp]:
    starts: list[pd.Timestamp] = []
    ends: list[pd.Timestamp] = []
    for df in (data or {}).values():
        if df is None or df.empty:
            continue
        idx = pd.to_datetime(df.index, errors="coerce")
        try:
            idx = idx.tz_localize(None)
        except Exception:
            with contextlib.suppress(Exception):
                idx = idx.tz_convert(None)
        idx = idx[~pd.isna(idx)]
        if len(idx) == 0:
            continue
        start = _normalize_ts(idx.min())
        end = _normalize_ts(idx.max())
        if start is not None:
            starts.append(start)
        if end is not None:
            ends.append(end)
    if not starts or not ends:
        now = _normalize_ts(pd.Timestamp.utcnow()) or RECENT_START
        return RECENT_START, now
    return min(starts), max(ends)


def _month_span(start: Any, end: Any) -> float:
    start_ts = _normalize_ts(start)
    end_ts = _normalize_ts(end)
    if start_ts is None or end_ts is None or end_ts <= start_ts:
        return 0.0
    delta_days = (end_ts - start_ts).total_seconds() / 86400.0
    return max(delta_days / DAYS_PER_MONTH, 1.0 / DAYS_PER_MONTH)


def _monthlyized_return(total_ret: Any, start: Any, end: Any) -> float:
    months = _month_span(start, end)
    if months <= 0:
        return 0.0
    gross = 1.0 + _safe_float(total_ret)
    if gross <= 0:
        return -1.0
    return float(gross ** (1.0 / months) - 1.0)


def _with_window_metrics(metrics: dict[str, Any], start: Any, end: Any) -> dict[str, Any]:
    out = dict(metrics or {})
    start_ts = _normalize_ts(start)
    end_ts = _normalize_ts(end)
    out["window_start"] = start_ts.isoformat() if start_ts is not None else None
    out["window_end"] = end_ts.isoformat() if end_ts is not None else None
    out["window_months"] = _month_span(start_ts, end_ts)
    out["monthlyized_ret"] = _monthlyized_return(out.get("ret"), start_ts, end_ts)
    return out


def _symbol_window_bounds(root: Path, cfg: dict[str, Any], symbol: str, cache: dict[str, tuple[pd.Timestamp, pd.Timestamp]]) -> tuple[pd.Timestamp, pd.Timestamp]:
    sym = str(symbol).lower()
    if sym in cache:
        return cache[sym]
    cfg2 = copy.deepcopy(cfg)
    cfg2.setdefault("data", {})["symbols"] = [sym]
    bounds = _window_bounds_from_data(s46._load_portfolio_data(root, cfg2))
    cache[sym] = bounds
    return bounds


def _recent_trades(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    time_col = "exit_time" if "exit_time" in out.columns else ("entry_time" if "entry_time" in out.columns else None)
    if time_col is None:
        return pd.DataFrame()
    out[time_col] = pd.to_datetime(out[time_col], errors="coerce")
    out = out.dropna(subset=[time_col])
    out = out.loc[out[time_col] >= RECENT_START].copy()
    if time_col != "exit_time" and "exit_time" not in out.columns:
        out["exit_time"] = out[time_col]
    return out


def _recent_metrics(df: pd.DataFrame, initial_equity: float) -> dict[str, Any]:
    return s59._metrics_from_trades(_recent_trades(df), initial_equity)


def _branch_score_dual(full_m: dict[str, Any], recent_m: dict[str, Any]) -> float:
    rm = recent_m.get("monthly", {}) or {}
    fm = full_m.get("monthly", {}) or {}
    recent_trades = int(recent_m.get("trades", 0) or 0)
    full_trades = int(full_m.get("trades", 0) or 0)
    return float(
        _safe_float(recent_m.get("pf")) * 138.0
        + _safe_float(recent_m.get("ret")) * 96.0
        - abs(_safe_float(recent_m.get("maxdd"))) * 72.0
        + min(recent_trades, 180) * 0.34
        + int(rm.get("months_ge_20", 0) or 0) * 15.0
        + _safe_float(rm.get("monthly_p75")) * 180.0
        + _safe_float(recent_m.get("rolling12_pf_floor")) * 28.0
        + _safe_float(full_m.get("pf")) * 16.0
        + _safe_float(full_m.get("ret")) * 10.0
        - abs(_safe_float(full_m.get("maxdd"))) * 12.0
        + min(full_trades, 220) * 0.06
        + int(fm.get("months_ge_20", 0) or 0) * 3.0
        + _safe_float(full_m.get("rolling12_pf_floor")) * 6.0
    )


def _branch_dual_label(full_m: dict[str, Any], recent_m: dict[str, Any]) -> str:
    recent_pf = _safe_float(recent_m.get("pf"))
    recent_dd = abs(_safe_float(recent_m.get("maxdd")))
    recent_floor = _safe_float(recent_m.get("rolling12_pf_floor"))
    recent_m20 = int((recent_m.get("monthly", {}) or {}).get("months_ge_20", 0) or 0)
    full_pf = _safe_float(full_m.get("pf"))
    if recent_pf >= 1.30 and recent_dd <= 0.35 and recent_floor >= 0.48 and (recent_m20 >= 1 or int(recent_m.get("trades",0) or 0) >= 24) and full_pf >= 1.10:
        return "pass"
    if recent_pf >= 1.05 and recent_dd <= 0.50 and full_pf >= 0.95:
        return "hold"
    return "kill"


def _resolve_candidate_names(raw: str) -> list[str]:
    return [x.strip() for x in str(raw or "").split(",") if x.strip()]


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, pd.DataFrame):
        return {"rows": int(len(obj)), "columns": list(obj.columns)}
    if isinstance(obj, pd.Series):
        return obj.tolist()
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if hasattr(obj, "isoformat"):
        try:
            return obj.isoformat()
        except Exception:
            pass
    try:
        import numpy as np  # type: ignore
        if isinstance(obj, (np.integer, np.floating, np.bool_)):
            return obj.item()
        if isinstance(obj, np.ndarray):
            return obj.tolist()
    except Exception:
        pass
    return obj


def _strip_gate_payload(row: dict[str, Any]) -> dict[str, Any]:
    best = dict(row.get("best_gate") or {})
    gated_df = best.pop("gated_df", None)
    if isinstance(gated_df, pd.DataFrame):
        best["gated_rows"] = int(len(gated_df))
        best["gated_columns"] = list(gated_df.columns)[:12]
    return _json_safe(best)


def _write_report(path_txt: Path, path_json: Path, rows: list[dict[str, Any]]) -> None:
    lines: list[str] = []
    lines.append("Stage78 分支双窗口前沿（6年总样本 + 近2年优先）")
    lines.append("核心原则：ETH/SOL 多空都保留，但排序先看近2年，6年只做软约束。")
    lines.append("说明：月化收益率=按样本时间跨度折算的几何月化，不等于简单月均收益。")
    lines.append("")
    lines.append("=== 各赛道当前最优 ===")
    by_lane: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row.get("symbol")), str(row.get("family")))
        if key not in by_lane:
            by_lane[key] = row
    for (sym, family), row in by_lane.items():
        best = row["best_gate"]
        full_m = best["metrics"]
        recent_m = best["recent_metrics"]
        full_mm = full_m.get("monthly", {}) or {}
        recent_mm = recent_m.get("monthly", {}) or {}
        lines.append(
            f"- {sym.upper()} | {family} | {row['name']}: best_gate={best['gate_name']} ({best['gate']}) | 6年 收益={_fmt_pct(full_m.get('ret'))} 月化={_fmt_pct(full_m.get('monthlyized_ret'))} 回撤={_fmt_pct(full_m.get('maxdd'))} 交易={int(full_m.get('trades',0))} PF={_safe_float(full_m.get('pf')):.3f} | 近2年 收益={_fmt_pct(recent_m.get('ret'))} 月化={_fmt_pct(recent_m.get('monthlyized_ret'))} 回撤={_fmt_pct(recent_m.get('maxdd'))} 交易={int(recent_m.get('trades',0))} PF={_safe_float(recent_m.get('pf')):.3f} | score={best['score']:+.2f}"
        )
        lines.append(
            f"  6年胜率={_fmt_pct(full_m.get('win_rate',0.0))} | 6年月度>=20%={int(full_mm.get('months_ge_20',0))} | 近2年胜率={_fmt_pct(recent_m.get('win_rate',0.0))} | 近2年月度>=20%={int(recent_mm.get('months_ge_20',0))}"
        )
        lines.append(f"  note={row['note']} | gate_note={best['gate_note']}")
    lines.append("")
    lines.append("=== 全部候选 ===")
    for row in rows:
        best = row["best_gate"]
        full_m = best["metrics"]
        recent_m = best["recent_metrics"]
        full_mm = full_m.get("monthly", {}) or {}
        recent_mm = recent_m.get("monthly", {}) or {}
        lines.append(
            f"- {row['symbol'].upper()} | family={row['family']} | {row['name']}: best_gate={best['gate_name']} ({best['gate']}) | 6年 收益={_fmt_pct(full_m.get('ret'))} 月化={_fmt_pct(full_m.get('monthlyized_ret'))} 回撤={_fmt_pct(full_m.get('maxdd'))} 交易={int(full_m.get('trades',0))} PF={_safe_float(full_m.get('pf')):.3f} 胜率={_fmt_pct(full_m.get('win_rate',0.0))} 月度>=20%={int(full_mm.get('months_ge_20',0))} | 近2年 收益={_fmt_pct(recent_m.get('ret'))} 月化={_fmt_pct(recent_m.get('monthlyized_ret'))} 回撤={_fmt_pct(recent_m.get('maxdd'))} 交易={int(recent_m.get('trades',0))} PF={_safe_float(recent_m.get('pf')):.3f} 胜率={_fmt_pct(recent_m.get('win_rate',0.0))} 月度>=20%={int(recent_mm.get('months_ge_20',0))} | score={best['score']:+.2f}"
        )
        lines.append(f"  note={row['note']} | gate_note={best['gate_note']} | 近2年roll12_pf_floor={_safe_float(recent_m.get('rolling12_pf_floor')):.3f}")
    lines.append("")
    lines.append("=== 结论 ===")
    lines.append("- 先看近2年是否能独立站住；老年份拖累不直接一票否决。")
    lines.append("- 单腿先做强，再考虑 dual，不急着合并。")
    path_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    path_json.write_text(
        json.dumps(
            {
                "rows": [_json_safe({**row, "best_gate": _strip_gate_payload(row)}) for row in rows],
                "recent_start": str(RECENT_START.date()),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage78 branch dual-window frontier")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--candidate-names", default="", help="逗号分隔；为空则跑全部")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    cfg = rcb.load_research_base_config(root)
    initial_equity = float(cfg.get("portfolio", {}).get("initial_equity", 100000.0))
    bounds_cache: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {}

    selected_names = set(_resolve_candidate_names(args.candidate_names))
    items = [item for item in s76._candidate_items() if (not selected_names or str(item.get("name")) in selected_names)]
    rows: list[dict[str, Any]] = []
    for item in items:
        row = s76._run_branch(root, cfg, item, initial_equity)
        full_start, full_end = _symbol_window_bounds(root, cfg, str(row.get("symbol", item.get("symbol", ""))), bounds_cache)
        recent_start = max(full_start, RECENT_START)
        for gate_row in row["gate_rows"]:
            gate_row["metrics"] = _with_window_metrics(gate_row.get("metrics", {}), full_start, full_end)
            gate_row["recent_metrics"] = _with_window_metrics(
                _recent_metrics(gate_row.get("gated_df"), initial_equity),
                recent_start,
                full_end,
            )
        row["base_metrics"] = _with_window_metrics(row.get("base_metrics", {}), full_start, full_end)
        best = None
        best_score = -1e18
        for gate_row in row["gate_rows"]:
            score = _branch_score_dual(gate_row["metrics"], gate_row["recent_metrics"])
            gate = _branch_dual_label(gate_row["metrics"], gate_row["recent_metrics"])
            gate_row["score"] = score
            gate_row["gate"] = gate
            if score > best_score:
                best_score = score
                best = gate_row
        row["best_gate"] = best if best is not None else row["gate_rows"][0]
        rows.append(row)

    rows.sort(key=lambda r: float(r["best_gate"]["score"]), reverse=True)

    reports_raw = root / "reports" / "research_raw"
    reports_raw.mkdir(parents=True, exist_ok=True)
    _write_report(
        reports_raw / "stage78_branch_dual_window_latest.txt",
        reports_raw / "stage78_branch_dual_window_latest.json",
        rows,
    )
    print(reports_raw / "stage78_branch_dual_window_latest.txt")
    print(reports_raw / "stage78_branch_dual_window_latest.json")


if __name__ == "__main__":
    main()
