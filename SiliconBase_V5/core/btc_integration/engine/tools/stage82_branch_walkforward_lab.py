from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


try:
    from tools import research_config_baseline as rcb
    from tools import stage59_structural_lab as s59
    from tools import stage76_branch_event_state_lab as s76
    from tools import stage78_branch_dual_window_lab as s78
except Exception as exc:
    raise SystemExit("缺少 stage59/stage76/stage78 模块，请先保留此前补丁。") from exc

CANDIDATE_ORDER = [
    "eth_short_shock_control_lb18_adx26_s074",
    "eth_shortwave_tight_shortonly",
    "eth_pullback_long_core_adx24_cd6_lb22_zone026_s036",
    "eth_breakout_long_follow_lb18_atr055_adx24_s030",
    "sol_pullback_long_core_adx24_cd6_lb20_zone025_s042",
    "sol_shortwave_smooth_longonly",
    "sol_retest_short_trend_lb18_atr055_adx22_s064",
    "sol_fast_trend_short_guarded_lb18_atr060_adx24_s068",
]


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


def _trade_time_col(df: pd.DataFrame) -> str | None:
    if df is None or df.empty:
        return None
    if "exit_time" in df.columns:
        return "exit_time"
    if "entry_time" in df.columns:
        return "entry_time"
    return None


def _normalize_trade_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    tcol = _trade_time_col(out)
    if tcol is None:
        return pd.DataFrame()
    out[tcol] = pd.to_datetime(out[tcol], errors="coerce")
    out = out.dropna(subset=[tcol]).copy()
    if tcol != "exit_time" and "exit_time" not in out.columns:
        out["exit_time"] = out[tcol]
    out["exit_time"] = pd.to_datetime(out["exit_time"], errors="coerce")
    out = out.dropna(subset=["exit_time"]).sort_values("exit_time")
    return out


def _slice_trades(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    out = _normalize_trade_df(df)
    if out.empty:
        return out
    mask = (out["exit_time"] >= start) & (out["exit_time"] < end)
    return out.loc[mask].copy()


def _build_folds(start: pd.Timestamp, end: pd.Timestamp) -> list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
    folds: list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]] = []
    train_end = start + pd.DateOffset(months=8)
    final_end = end + pd.Timedelta(seconds=1)
    while train_end < end:
        test_start = train_end
        test_end = min(test_start + pd.DateOffset(months=4), final_end)
        folds.append((start, test_start, test_end))
        train_end = test_end
    if not folds:
        mid = start + (end - start) / 2
        folds.append((start, mid, final_end))
    return folds


def _metrics_window(df: pd.DataFrame, initial_equity: float, start: pd.Timestamp, end: pd.Timestamp) -> dict[str, Any]:
    return s78._with_window_metrics(s59._metrics_from_trades(_slice_trades(df, start, end), initial_equity), start, end)


_BRANCH_FOLD_TARGET = 6
_BRANCH_FOLD_MIN_EVENT_TRADES = 3


def _trade_weight(trades: Any, target: int) -> float:
    t = max(int(trades or 0), 0)
    if t <= 0:
        return 0.0
    if target <= 0:
        return 1.0
    return max(0.0, min(1.0, t / float(target)))


def _pf_for_score(pf: Any, trades: Any, target: int, cap: float) -> float:
    t = max(int(trades or 0), 0)
    if t <= 0:
        return 0.0
    raw = max(0.0, _safe_float(pf))
    clipped = min(raw, cap)
    w = _trade_weight(t, target)
    return 1.0 + (clipped - 1.0) * w


def _ret_for_score(ret: Any, trades: Any, target: int) -> float:
    return _safe_float(ret) * _trade_weight(trades, target)


def _dd_for_score(maxdd: Any, trades: Any, target: int, floor_dd: float) -> float:
    base = abs(_safe_float(maxdd))
    w = _trade_weight(trades, target)
    return max(base, (1.0 - w) * floor_dd)


def _branch_train_quality(train_m: dict[str, Any]) -> float:
    trades = int(train_m.get("trades", 0) or 0)
    pf_adj = _pf_for_score(train_m.get("pf"), trades, _BRANCH_FOLD_TARGET, 3.5)
    ret_adj = _ret_for_score(train_m.get("ret"), trades, _BRANCH_FOLD_TARGET)
    dd_adj = _dd_for_score(train_m.get("maxdd"), trades, _BRANCH_FOLD_TARGET, 0.07)
    floor_adj = _pf_for_score(train_m.get("rolling12_pf_floor"), trades, _BRANCH_FOLD_TARGET, 2.2)
    sample_penalty = max(0, _BRANCH_FOLD_TARGET - trades) * 22.0
    return float(
        pf_adj * 146.0
        + ret_adj * 104.0
        - dd_adj * 88.0
        + floor_adj * 16.0
        + min(trades, _BRANCH_FOLD_TARGET * 3) * 2.6
        - sample_penalty
    )


def _pick_best_gate_for_fold(
    row: dict[str, Any],
    initial_equity: float,
    train_start: pd.Timestamp,
    train_end: pd.Timestamp,
) -> tuple[dict[str, Any], dict[str, Any]]:
    gate_rows = row.get("gate_rows", []) or []
    if not gate_rows:
        return {}, _metrics_window(pd.DataFrame(), initial_equity, train_start, train_end)

    scored: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
    base_gate: dict[str, Any] | None = None
    base_train: dict[str, Any] | None = None
    base_score = -1e18
    for gate in gate_rows:
        train_m = _metrics_window(gate.get("gated_df"), initial_equity, train_start, train_end)
        score = _branch_train_quality(train_m)
        name = str(gate.get("gate_name", "-"))
        if name == "base_message_overlay":
            base_gate = gate
            base_train = train_m
            base_score = score
        scored.append((score, gate, train_m))

    if base_gate is None:
        base_gate = gate_rows[0]
        base_train = _metrics_window(base_gate.get("gated_df"), initial_equity, train_start, train_end)
        base_score = _branch_train_quality(base_train)

    best_gate = base_gate
    best_train = base_train
    best_score = base_score
    base_trades = int((base_train or {}).get("trades", 0) or 0)
    base_pf = _safe_float((base_train or {}).get("pf"))
    base_ret = _safe_float((base_train or {}).get("ret"))

    for score, gate, train_m in scored:
        name = str(gate.get("gate_name", "-"))
        if name == "base_message_overlay":
            continue
        trades = int(train_m.get("trades", 0) or 0)
        pf_v = _safe_float(train_m.get("pf"))
        ret_v = _safe_float(train_m.get("ret"))
        dd_v = abs(_safe_float(train_m.get("maxdd")))
        min_margin = 10.0 + max(0, _BRANCH_FOLD_TARGET - trades) * 3.0
        if trades < _BRANCH_FOLD_MIN_EVENT_TRADES:
            continue
        if pf_v < max(1.00, base_pf - 0.08) and ret_v <= base_ret + 0.005:
            continue
        if trades < max(_BRANCH_FOLD_MIN_EVENT_TRADES, int(base_trades * 0.30)) and ret_v <= base_ret + 0.02:
            continue
        if dd_v > 0.18 and trades < _BRANCH_FOLD_TARGET:
            continue
        if score <= best_score + min_margin:
            continue
        best_gate = gate
        best_train = train_m
        best_score = score

    return best_gate or gate_rows[0], best_train or _metrics_window(pd.DataFrame(), initial_equity, train_start, train_end)


def _wf_result(row: dict[str, Any], initial_equity: float, recent_start: pd.Timestamp, full_end: pd.Timestamp) -> dict[str, Any]:
    folds = _build_folds(recent_start, full_end)
    chosen_frames: list[pd.DataFrame] = []
    fold_rows: list[dict[str, Any]] = []
    gate_counter: Counter[str] = Counter()

    for train_start, test_start, test_end in folds:
        gate, train_m = _pick_best_gate_for_fold(row, initial_equity, train_start, test_start)
        test_df = _slice_trades(gate.get("gated_df"), test_start, test_end)
        test_m = s78._with_window_metrics(s59._metrics_from_trades(test_df, initial_equity), test_start, test_end)
        chosen_frames.append(test_df)
        gate_name = str(gate.get("gate_name", "-"))
        gate_counter[gate_name] += 1
        fold_rows.append(
            {
                "train_start": str(train_start.date()),
                "test_start": str(test_start.date()),
                "test_end": str((test_end - pd.Timedelta(seconds=1)).date()),
                "gate_name": gate_name,
                "train_pf": _safe_float(train_m.get("pf")),
                "train_ret": _safe_float(train_m.get("ret")),
                "test_pf": _safe_float(test_m.get("pf")),
                "test_ret": _safe_float(test_m.get("ret")),
                "test_maxdd": _safe_float(test_m.get("maxdd")),
                "test_trades": int(test_m.get("trades", 0) or 0),
                "test_metrics": test_m,
            }
        )

    oos_df = pd.concat([x for x in chosen_frames if x is not None and not x.empty], ignore_index=True) if any(x is not None and not x.empty for x in chosen_frames) else pd.DataFrame()
    oos_m = s78._with_window_metrics(s59._metrics_from_trades(oos_df, initial_equity), folds[0][1], folds[-1][2])
    pos_folds = sum(1 for x in fold_rows if _safe_float(x.get("test_ret")) > 0)
    pf_floor = min((_safe_float(x.get("test_pf")) for x in fold_rows), default=0.0)
    dd_ceiling = max((abs(_safe_float(x.get("test_maxdd"))) for x in fold_rows), default=0.0)
    score = float(
        _safe_float(oos_m.get("pf")) * 162.0
        + _safe_float(oos_m.get("ret")) * 88.0
        - abs(_safe_float(oos_m.get("maxdd"))) * 72.0
        + int(oos_m.get("trades", 0) or 0) * 0.28
        + pos_folds * 12.0
        + pf_floor * 18.0
        - dd_ceiling * 14.0
    )
    label = "pass" if (_safe_float(oos_m.get("pf")) >= 1.30 and abs(_safe_float(oos_m.get("maxdd"))) <= 0.30 and pos_folds >= max(1, len(fold_rows) - 1)) else ("hold" if (_safe_float(oos_m.get("pf")) >= 1.05 and abs(_safe_float(oos_m.get("maxdd"))) <= 0.45) else "kill")
    return {
        "folds": fold_rows,
        "metrics": oos_m,
        "gate_mix": dict(gate_counter),
        "positive_folds": pos_folds,
        "total_folds": len(fold_rows),
        "pf_floor": pf_floor,
        "dd_ceiling": dd_ceiling,
        "score": score,
        "label": label,
    }


def _load_stage86_selected(root: Path) -> list[str]:
    json_path = root / "reports" / "research_raw" / "stage86_branch_shortlist_latest.json"
    txt_path = root / "reports" / "research_raw" / "stage86_branch_shortlist_latest.txt"
    if json_path.exists():
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            selected = [str(x).strip() for x in (data.get("selected") or []) if str(x).strip()]
            if selected:
                return selected
        except Exception:
            pass
    if txt_path.exists():
        try:
            txt = txt_path.read_text(encoding="utf-8", errors="ignore")
            for line in txt.splitlines():
                if line.startswith("selected="):
                    return [x.strip() for x in line.split("=", 1)[1].split(",") if x.strip()]
        except Exception:
            pass
    return []


def _resolve_candidate_names(raw: str, default: list[str], root: Path) -> list[str]:
    items = [x.strip() for x in str(raw or "").split(",") if x.strip()]
    if items:
        return items
    stage86_selected = _load_stage86_selected(root)
    if stage86_selected:
        return stage86_selected
    return list(default)


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


def _write_report(path_txt: Path, path_json: Path, rows: list[dict[str, Any]]) -> None:
    lines: list[str] = []
    lines.append("Stage82 分支滚动样本外验证（近2年优先）")
    lines.append("研究基准: research_baselines/mainline_live_base.yml（不再跟随当前 Demo 配置漂移）")
    lines.append("说明：近2年窗口按 8个月训练 + 4个月测试 做扩展式 walk-forward-lite；每折先选 gate，再看下一折测试段。")
    lines.append("说明：分支先看单腿能否在样本外站住，再决定是否接模拟盘。")
    lines.append("")
    lines.append("=== 候选结果 ===")
    for row in rows:
        best = row["best_gate"]
        full_m = best["metrics"]
        recent_m = best["recent_metrics"]
        wf = row["walkforward"]
        oos_m = wf["metrics"]
        lines.append(
            f"- {row['symbol'].upper()} | {row['family']} | {row['name']}: 6年 收益={_fmt_pct(full_m.get('ret'))} 月化={_fmt_pct(full_m.get('monthlyized_ret'))} 回撤={_fmt_pct(full_m.get('maxdd'))} 交易={int(full_m.get('trades',0))} PF={_safe_float(full_m.get('pf')):.3f} | 近2年 收益={_fmt_pct(recent_m.get('ret'))} 月化={_fmt_pct(recent_m.get('monthlyized_ret'))} 回撤={_fmt_pct(recent_m.get('maxdd'))} 交易={int(recent_m.get('trades',0))} PF={_safe_float(recent_m.get('pf')):.3f} | WF样本外 收益={_fmt_pct(oos_m.get('ret'))} 月化={_fmt_pct(oos_m.get('monthlyized_ret'))} 回撤={_fmt_pct(oos_m.get('maxdd'))} 交易={int(oos_m.get('trades',0))} PF={_safe_float(oos_m.get('pf')):.3f} 胜率={_fmt_pct(oos_m.get('win_rate',0.0))} | 折内正收益={wf['positive_folds']}/{wf['total_folds']} | score={wf['score']:+.2f} | {wf['label']}"
        )
        lines.append(f"  note={row['note']} | best_gate={best.get('gate_name')} | gate_mix={wf['gate_mix']} | wf_pf_floor={wf['pf_floor']:.3f} | wf_dd_ceiling={wf['dd_ceiling']:.3f}")
    lines.append("")
    lines.append("=== 各赛道当前最优 ===")
    by_lane: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row.get("symbol")).upper(), str(row.get("family")))
        if key not in by_lane:
            by_lane[key] = row
    for key, row in by_lane.items():
        wf = row["walkforward"]
        oos_m = wf["metrics"]
        lines.append(
            f"- {key[0]} | {key[1]}: {row['name']} | WF样本外 收益={_fmt_pct(oos_m.get('ret'))} 月化={_fmt_pct(oos_m.get('monthlyized_ret'))} 回撤={_fmt_pct(oos_m.get('maxdd'))} 交易={int(oos_m.get('trades',0))} PF={_safe_float(oos_m.get('pf')):.3f} | 折内正收益={wf['positive_folds']}/{wf['total_folds']} | {wf['label']}"
        )
    lines.append("")
    lines.append("=== 结论 ===")
    lines.append("- 分支接模拟盘前，优先看近2年 + WF样本外是否同时为正，且回撤可控。")
    lines.append("- 如果近2年好看但 WF塌陷，就继续研究，不接 demo。")
    path_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    path_json.write_text(json.dumps({"rows": _json_safe(rows)}, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage82 branch walkforward-lite")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--candidate-names", default="", help="逗号分隔；为空则用内置短名单")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    cfg = rcb.load_research_base_config(root)
    initial_equity = float(cfg.get("portfolio", {}).get("initial_equity", 100000.0))
    bounds_cache: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {}

    candidate_order = _resolve_candidate_names(args.candidate_names, CANDIDATE_ORDER, root)
    items_map = {str(x.get("name")): x for x in s76._candidate_items()}
    chosen_items = [items_map[name] for name in candidate_order if name in items_map]
    if not chosen_items:
        raise SystemExit("未找到分支候选，无法运行 stage82。")

    rows: list[dict[str, Any]] = []
    for item in chosen_items:
        row = s76._run_branch(root, cfg, item, initial_equity)
        full_start, full_end = s78._symbol_window_bounds(root, cfg, str(row.get("symbol", item.get("symbol", ""))), bounds_cache)
        recent_start = max(full_start, s78.RECENT_START)
        for gate_row in row["gate_rows"]:
            gate_row["metrics"] = s78._with_window_metrics(gate_row.get("metrics", {}), full_start, full_end)
            gate_row["recent_metrics"] = s78._with_window_metrics(
                s78._recent_metrics(gate_row.get("gated_df"), initial_equity),
                recent_start,
                full_end,
            )
        row["base_metrics"] = s78._with_window_metrics(row.get("base_metrics", {}), full_start, full_end)
        best = None
        best_score = -1e18
        for gate_row in row["gate_rows"]:
            score = s78._branch_score_dual(gate_row["metrics"], gate_row["recent_metrics"])
            gate_row["score"] = score
            gate_row["gate"] = s78._branch_dual_label(gate_row["metrics"], gate_row["recent_metrics"])
            if score > best_score:
                best_score = score
                best = gate_row
        row["best_gate"] = best if best is not None else row["gate_rows"][0]
        row["walkforward"] = _wf_result(row, initial_equity, recent_start, full_end)
        rows.append(row)

    rows.sort(key=lambda r: float(r["walkforward"]["score"]), reverse=True)
    reports_raw = root / "reports" / "research_raw"
    reports_raw.mkdir(parents=True, exist_ok=True)
    _write_report(
        reports_raw / "stage82_branch_walkforward_latest.txt",
        reports_raw / "stage82_branch_walkforward_latest.json",
        rows,
    )
    print(reports_raw / "stage82_branch_walkforward_latest.txt")
    print(reports_raw / "stage82_branch_walkforward_latest.json")


if __name__ == "__main__":
    main()
