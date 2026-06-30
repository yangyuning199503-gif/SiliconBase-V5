from __future__ import annotations

import argparse
import contextlib
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
    from tools import stage75_mainline_event_state_lab as s75
except Exception as exc:
    raise SystemExit("缺少 stage46/stage59/stage75 模块，请先保留此前补丁。") from exc

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


def _main_score_dual(full_m: dict[str, Any], recent_m: dict[str, Any], ref_recent: dict[str, Any]) -> float:
    rm = recent_m.get("monthly", {}) or {}
    fm = full_m.get("monthly", {}) or {}
    recent_trades = int(recent_m.get("trades", 0) or 0)
    full_trades = int(full_m.get("trades", 0) or 0)
    recent_pf = _safe_float(recent_m.get("pf"))
    recent_ret = _safe_float(recent_m.get("ret"))
    recent_dd = abs(_safe_float(recent_m.get("maxdd")))
    recent_floor = _safe_float(recent_m.get("rolling12_pf_floor"))
    recent_p75 = _safe_float(rm.get("monthly_p75"))
    recent_m20 = int(rm.get("months_ge_20", 0) or 0)

    full_pf = _safe_float(full_m.get("pf"))
    full_ret = _safe_float(full_m.get("ret"))
    full_dd = abs(_safe_float(full_m.get("maxdd")))
    full_floor = _safe_float(full_m.get("rolling12_pf_floor"))
    full_p75 = _safe_float(fm.get("monthly_p75"))
    full_m20 = int(fm.get("months_ge_20", 0) or 0)

    ref_pf = _safe_float(ref_recent.get("pf"))
    ref_dd = abs(_safe_float(ref_recent.get("maxdd")))

    pf_pen = max(0.0, ref_pf - recent_pf) * 24.0
    dd_pen = max(0.0, recent_dd - ref_dd) * 36.0

    return float(
        recent_pf * 128.0
        + recent_ret * 82.0
        - recent_dd * 92.0
        + min(recent_trades, 220) * 0.42
        + recent_m20 * 8.5
        + recent_p75 * 170.0
        + recent_floor * 30.0
        + full_pf * 22.0
        + full_ret * 10.0
        - full_dd * 18.0
        + min(full_trades, 260) * 0.08
        + full_m20 * 1.6
        + full_p75 * 24.0
        + full_floor * 6.0
        - pf_pen
        - dd_pen
    )


def _main_dual_label(full_m: dict[str, Any], recent_m: dict[str, Any], ref_recent: dict[str, Any]) -> str:
    recent_trades = int(recent_m.get("trades", 0) or 0)
    recent_pf = _safe_float(recent_m.get("pf"))
    recent_dd = abs(_safe_float(recent_m.get("maxdd")))
    recent_floor = _safe_float(recent_m.get("rolling12_pf_floor"))
    full_pf = _safe_float(full_m.get("pf"))
    full_dd = abs(_safe_float(full_m.get("maxdd")))
    ref_pf = _safe_float(ref_recent.get("pf"))
    if recent_trades >= 55 and recent_pf >= max(1.80, ref_pf - 0.18) and recent_dd <= 0.38 and recent_floor >= 0.62 and full_pf >= 1.85 and full_dd <= 0.42:
        return "pass"
    if recent_trades >= 35 and recent_pf >= 1.45 and recent_dd <= 0.52 and full_pf >= 1.55:
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


def _write_report(path_txt: Path, path_json: Path, rows: list[dict[str, Any]], ref_full: dict[str, Any], ref_recent: dict[str, Any]) -> None:
    lines: list[str] = []
    lines.append("Stage77 主线双窗口前沿（6年总样本 + 近2年优先）")
    lines.append("核心原则：6年保留做软约束；排序与取舍以近2年质量优先。")
    lines.append("说明：月化收益率=按样本时间跨度折算的几何月化，不等于简单月均收益。")
    lines.append("")
    lines.append("=== 候选结果 ===")
    for row in rows:
        best = row["best_gate"]
        full_m = best["metrics"]
        recent_m = best["recent_metrics"]
        full_mm = full_m.get("monthly", {}) or {}
        recent_mm = recent_m.get("monthly", {}) or {}
        lines.append(
            f"- {row['name']}: best_gate={best['gate_name']} ({best['gate']}) | 6年 收益={_fmt_pct(full_m.get('ret'))} 月化={_fmt_pct(full_m.get('monthlyized_ret'))} 回撤={_fmt_pct(full_m.get('maxdd'))} 交易={int(full_m.get('trades',0))} PF={_safe_float(full_m.get('pf')):.3f} | 近2年 收益={_fmt_pct(recent_m.get('ret'))} 月化={_fmt_pct(recent_m.get('monthlyized_ret'))} 回撤={_fmt_pct(recent_m.get('maxdd'))} 交易={int(recent_m.get('trades',0))} PF={_safe_float(recent_m.get('pf')):.3f} | score={best['score']:+.2f}"
        )
        lines.append(
            f"  6年胜率={_fmt_pct(full_m.get('win_rate',0.0))} | 6年月度>=20%={int(full_mm.get('months_ge_20',0))} | 近2年胜率={_fmt_pct(recent_m.get('win_rate',0.0))} | 近2年月度>=20%={int(recent_mm.get('months_ge_20',0))}"
        )
        lines.append(
            f"  note={row['note']} | gate_note={best['gate_note']} | 近2年roll12_pf_floor={_safe_float(recent_m.get('rolling12_pf_floor')):.3f}"
        )
    lines.append("")
    lines.append("=== 结论 ===")
    lines.append("- 先看近2年，再看6年是否只是软性失真，而不是一票否决。")
    lines.append("- 如果近2年明显强于6年，说明老年份正在稀释当前结构，不应强行压回旧状态。")
    lines.append(
        f"- 参考基线 6年: 收益={_fmt_pct(ref_full.get('ret'))} | 月化={_fmt_pct(ref_full.get('monthlyized_ret'))} | 回撤={_fmt_pct(ref_full.get('maxdd'))} | 交易={int(ref_full.get('trades',0))} | PF={_safe_float(ref_full.get('pf')):.3f}。"
    )
    lines.append(
        f"- 参考基线 近2年: 收益={_fmt_pct(ref_recent.get('ret'))} | 月化={_fmt_pct(ref_recent.get('monthlyized_ret'))} | 回撤={_fmt_pct(ref_recent.get('maxdd'))} | 交易={int(ref_recent.get('trades',0))} | PF={_safe_float(ref_recent.get('pf')):.3f}。"
    )
    path_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    path_json.write_text(
        json.dumps(
            {
                "rows": [_json_safe({**row, "best_gate": _strip_gate_payload(row)}) for row in rows],
                "reference_full": _json_safe(ref_full),
                "reference_recent": _json_safe(ref_recent),
                "recent_start": str(RECENT_START.date()),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage77 mainline dual-window frontier")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--candidate-names", default="", help="逗号分隔；为空则跑全部")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    cfg = rcb.load_research_base_config(root)
    initial_equity = float(cfg.get("portfolio", {}).get("initial_equity", 100000.0))
    data = s46._load_portfolio_data(root, cfg)
    full_start, full_end = _window_bounds_from_data(data)
    recent_start = max(full_start, RECENT_START)

    selected_names = set(_resolve_candidate_names(args.candidate_names))
    items = [item for item in s75._mainline_items() if (not selected_names or str(item.get("name")) in selected_names)]
    rows: list[dict[str, Any]] = []
    for item in items:
        row = s75._run_mainline(root, cfg, data, item, initial_equity)
        for gate_row in row["gate_rows"]:
            gate_row["metrics"] = _with_window_metrics(gate_row.get("metrics", {}), full_start, full_end)
            gate_row["recent_metrics"] = _with_window_metrics(
                _recent_metrics(gate_row.get("gated_df"), initial_equity),
                recent_start,
                full_end,
            )
        row["base_metrics"] = _with_window_metrics(row.get("base_metrics", {}), full_start, full_end)
        rows.append(row)

    ref_row = next((r for r in rows if r["name"] == "mainline_live_base"), rows[0])
    ref_best = None
    best_score = -1e18
    for gate_row in ref_row["gate_rows"]:
        score = _main_score_dual(gate_row["metrics"], gate_row["recent_metrics"], gate_row["recent_metrics"])
        if score > best_score:
            best_score = score
            ref_best = gate_row
    ref_full = ref_best["metrics"] if ref_best else ref_row["base_metrics"]
    ref_recent = ref_best["recent_metrics"] if ref_best else _with_window_metrics(_recent_metrics(pd.DataFrame(), initial_equity), recent_start, full_end)

    for row in rows:
        best = None
        best_score = -1e18
        for gate_row in row["gate_rows"]:
            score = _main_score_dual(gate_row["metrics"], gate_row["recent_metrics"], ref_recent)
            gate = _main_dual_label(gate_row["metrics"], gate_row["recent_metrics"], ref_recent)
            gate_row["score"] = score
            gate_row["gate"] = gate
            if score > best_score:
                best_score = score
                best = gate_row
        row["best_gate"] = best if best is not None else row["gate_rows"][0]

    rows.sort(key=lambda r: float(r["best_gate"]["score"]), reverse=True)

    reports_raw = root / "reports" / "research_raw"
    reports_raw.mkdir(parents=True, exist_ok=True)
    _write_report(
        reports_raw / "stage77_mainline_dual_window_latest.txt",
        reports_raw / "stage77_mainline_dual_window_latest.json",
        rows,
        ref_full,
        ref_recent,
    )
    print(reports_raw / "stage77_mainline_dual_window_latest.txt")
    print(reports_raw / "stage77_mainline_dual_window_latest.json")


if __name__ == "__main__":
    main()
