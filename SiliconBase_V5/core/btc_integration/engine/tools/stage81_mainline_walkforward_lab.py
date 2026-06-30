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
    from tools import stage46_aggressive_lab as s46
    from tools import stage59_structural_lab as s59
    from tools import stage75_mainline_event_state_lab as s75
    from tools import stage77_mainline_dual_window_lab as s77
except Exception as exc:
    raise SystemExit("缺少 stage46/stage59/stage75/stage77 模块，请先保留此前补丁。") from exc

RECENT_START = pd.Timestamp("2024-01-01", tz=None)
CANDIDATE_ORDER = [
    "mainline_live_base",
    "combo_sr_soft_adx26_cd6_lb24_zone028_ref",
    "combo_sr_soft_adx28_cd6_lb24_zone028",
    "combo_sr_soft_adx30_cd5_lb22_zone026",
    "combo_sr_soft_adx32_cd5_lb20_zone025",
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
    return s77._with_window_metrics(s59._metrics_from_trades(_slice_trades(df, start, end), initial_equity), start, end)


_MAINLINE_FOLD_TARGET = 8
_MAINLINE_FOLD_MIN_EVENT_TRADES = 3


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


def _mainline_train_quality(train_m: dict[str, Any], ref_recent: dict[str, Any]) -> float:
    trades = int(train_m.get("trades", 0) or 0)
    pf_adj = _pf_for_score(train_m.get("pf"), trades, _MAINLINE_FOLD_TARGET, 4.0)
    ret_adj = _ret_for_score(train_m.get("ret"), trades, _MAINLINE_FOLD_TARGET)
    dd_adj = _dd_for_score(train_m.get("maxdd"), trades, _MAINLINE_FOLD_TARGET, 0.08)
    floor_adj = _pf_for_score(train_m.get("rolling12_pf_floor"), trades, _MAINLINE_FOLD_TARGET, 2.5)
    ref_pf = _safe_float(ref_recent.get("pf"))
    ref_dd = abs(_safe_float(ref_recent.get("maxdd")))
    pf_gap = max(0.0, ref_pf - _safe_float(train_m.get("pf")))
    dd_gap = max(0.0, abs(_safe_float(train_m.get("maxdd"))) - ref_dd)
    sample_penalty = max(0, _MAINLINE_FOLD_TARGET - trades) * 24.0
    return float(
        pf_adj * 150.0
        + ret_adj * 94.0
        - dd_adj * 102.0
        + floor_adj * 18.0
        + min(trades, _MAINLINE_FOLD_TARGET * 2) * 2.4
        - pf_gap * 28.0
        - dd_gap * 22.0
        - sample_penalty
    )


def _pick_ref_recent(row: dict[str, Any], initial_equity: float, train_start: pd.Timestamp, train_end: pd.Timestamp) -> dict[str, Any]:
    gate_rows = row.get("gate_rows", []) or []
    if not gate_rows:
        return _metrics_window(pd.DataFrame(), initial_equity, train_start, train_end)
    base_pair: tuple[dict[str, Any], dict[str, Any]] | None = None
    scored: list[tuple[float, dict[str, Any]]] = []
    for gate in gate_rows:
        train_m = _metrics_window(gate.get("gated_df"), initial_equity, train_start, train_end)
        if str(gate.get("gate_name")) == "base_message_overlay":
            base_pair = (gate, train_m)
        score = _mainline_train_quality(train_m, train_m)
        scored.append((score, train_m))
    if base_pair is not None:
        return base_pair[1]
    if not scored:
        return _metrics_window(pd.DataFrame(), initial_equity, train_start, train_end)
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


def _pick_best_gate_for_fold(
    row: dict[str, Any],
    ref_recent: dict[str, Any],
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
        score = _mainline_train_quality(train_m, ref_recent)
        name = str(gate.get("gate_name", "-"))
        if name == "base_message_overlay":
            base_gate = gate
            base_train = train_m
            base_score = score
        scored.append((score, gate, train_m))

    if base_gate is None:
        base_gate = gate_rows[0]
        base_train = _metrics_window(base_gate.get("gated_df"), initial_equity, train_start, train_end)
        base_score = _mainline_train_quality(base_train, ref_recent)

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
        min_margin = 12.0 + max(0, _MAINLINE_FOLD_TARGET - trades) * 4.0
        if trades < _MAINLINE_FOLD_MIN_EVENT_TRADES:
            continue
        if pf_v < max(1.02, base_pf - 0.12) and ret_v <= base_ret + 0.01:
            continue
        if trades < max(_MAINLINE_FOLD_MIN_EVENT_TRADES, int(base_trades * 0.35)) and ret_v <= base_ret + 0.03:
            continue
        if dd_v > 0.22 and trades < _MAINLINE_FOLD_TARGET:
            continue
        if score <= best_score + min_margin:
            continue
        best_gate = gate
        best_train = train_m
        best_score = score

    return best_gate or gate_rows[0], best_train or _metrics_window(pd.DataFrame(), initial_equity, train_start, train_end)


def _wf_result(row: dict[str, Any], ref_row: dict[str, Any], initial_equity: float, recent_start: pd.Timestamp, full_end: pd.Timestamp) -> dict[str, Any]:
    folds = _build_folds(recent_start, full_end)
    chosen_frames: list[pd.DataFrame] = []
    fold_rows: list[dict[str, Any]] = []
    gate_counter: Counter[str] = Counter()

    for train_start, test_start, test_end in folds:
        ref_recent = _pick_ref_recent(ref_row, initial_equity, train_start, test_start)
        gate, train_m = _pick_best_gate_for_fold(row, ref_recent, initial_equity, train_start, test_start)
        test_df = _slice_trades(gate.get("gated_df"), test_start, test_end)
        test_m = s77._with_window_metrics(s59._metrics_from_trades(test_df, initial_equity), test_start, test_end)
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
    oos_m = s77._with_window_metrics(s59._metrics_from_trades(oos_df, initial_equity), folds[0][1], folds[-1][2])
    pos_folds = sum(1 for x in fold_rows if _safe_float(x.get("test_ret")) > 0)
    pf_floor = min((_safe_float(x.get("test_pf")) for x in fold_rows), default=0.0)
    dd_ceiling = max((abs(_safe_float(x.get("test_maxdd"))) for x in fold_rows), default=0.0)
    score = float(
        _safe_float(oos_m.get("pf")) * 150.0
        + _safe_float(oos_m.get("ret")) * 82.0
        - abs(_safe_float(oos_m.get("maxdd"))) * 96.0
        + int(oos_m.get("trades", 0) or 0) * 0.34
        + pos_folds * 10.0
        + pf_floor * 20.0
        - dd_ceiling * 18.0
    )
    label = "pass" if (_safe_float(oos_m.get("pf")) >= 1.55 and abs(_safe_float(oos_m.get("maxdd"))) <= 0.38 and pos_folds >= max(1, len(fold_rows) - 1)) else ("hold" if (_safe_float(oos_m.get("pf")) >= 1.20 and abs(_safe_float(oos_m.get("maxdd"))) <= 0.52) else "kill")
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


def _resolve_candidate_names(raw: str, default: list[str]) -> list[str]:
    items = [x.strip() for x in str(raw or "").split(",") if x.strip()]
    return items or list(default)


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


def _write_report(path_txt: Path, path_json: Path, rows: list[dict[str, Any]], ref_row: dict[str, Any]) -> None:
    lines: list[str] = []
    lines.append("Stage81 主线滚动样本外验证（近2年优先）")
    lines.append("研究基准: research_baselines/mainline_live_base.yml（不再跟随当前 Demo 配置漂移）")
    lines.append("说明：近2年窗口按 8个月训练 + 4个月测试 做扩展式 walk-forward-lite；每折先在训练段选择 gate，再看下一折测试段。")
    lines.append("说明：仍同时展示 6年总样本与近2年窗口，老年份只作软约束。")
    lines.append("")
    lines.append("=== 候选结果 ===")
    for row in rows:
        best = row["best_gate"]
        full_m = best["metrics"]
        recent_m = best["recent_metrics"]
        wf = row["walkforward"]
        oos_m = wf["metrics"]
        lines.append(
            f"- {row['name']}: 6年 收益={_fmt_pct(full_m.get('ret'))} 月化={_fmt_pct(full_m.get('monthlyized_ret'))} 回撤={_fmt_pct(full_m.get('maxdd'))} 交易={int(full_m.get('trades',0))} PF={_safe_float(full_m.get('pf')):.3f} | 近2年 收益={_fmt_pct(recent_m.get('ret'))} 月化={_fmt_pct(recent_m.get('monthlyized_ret'))} 回撤={_fmt_pct(recent_m.get('maxdd'))} 交易={int(recent_m.get('trades',0))} PF={_safe_float(recent_m.get('pf')):.3f} | WF样本外 收益={_fmt_pct(oos_m.get('ret'))} 月化={_fmt_pct(oos_m.get('monthlyized_ret'))} 回撤={_fmt_pct(oos_m.get('maxdd'))} 交易={int(oos_m.get('trades',0))} PF={_safe_float(oos_m.get('pf')):.3f} 胜率={_fmt_pct(oos_m.get('win_rate',0.0))} | 折内正收益={wf['positive_folds']}/{wf['total_folds']} | score={wf['score']:+.2f} | {wf['label']}"
        )
        lines.append(f"  note={row['note']} | best_gate={best.get('gate_name')} | gate_mix={wf['gate_mix']} | wf_pf_floor={wf['pf_floor']:.3f} | wf_dd_ceiling={wf['dd_ceiling']:.3f}")
    lines.append("")
    lines.append("=== 折明细（前2候选） ===")
    for row in rows[:2]:
        lines.append(f"- {row['name']}")
        for fold in row["walkforward"]["folds"]:
            lines.append(
                f"  {fold['test_start']}~{fold['test_end']} | gate={fold['gate_name']} | test_trades={fold['test_trades']} | test_pf={fold['test_pf']:.3f} | test_ret={_fmt_pct(fold['test_ret'])} | test_maxDD={_fmt_pct(fold['test_maxdd'])}"
            )
    lines.append("")
    ref_best = ref_row["best_gate"]
    ref_recent = ref_best["recent_metrics"]
    ref_wf = ref_row["walkforward"]["metrics"]
    lines.append("=== 结论 ===")
    lines.append(f"- 当前生产对照组仍是 {ref_row['name']}：近2年 PF={_safe_float(ref_recent.get('pf')):.3f}，WF样本外 PF={_safe_float(ref_wf.get('pf')):.3f}。")
    lines.append("- 主线是否切换，不看单一总收益，优先看近2年 + WF样本外是否同时站住。")
    lines.append("- 如果提频候选近2年更高但 WF塌陷，就继续 shadow，不直接替换 live_base。")
    path_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    path_json.write_text(json.dumps({"rows": _json_safe(rows)}, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage81 mainline walkforward-lite")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--candidate-names", default="", help="逗号分隔；为空则用内置短名单")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    cfg = rcb.load_research_base_config(root)
    initial_equity = float(cfg.get("portfolio", {}).get("initial_equity", 100000.0))
    data = s46._load_portfolio_data(root, cfg)
    full_start, full_end = s77._window_bounds_from_data(data)
    recent_start = max(full_start, RECENT_START)

    candidate_order = _resolve_candidate_names(args.candidate_names, CANDIDATE_ORDER)
    items_map = {str(x.get("name")): x for x in s75._mainline_items()}
    chosen_items = [items_map[name] for name in candidate_order if name in items_map]
    if not chosen_items:
        raise SystemExit("未找到主线候选，无法运行 stage81。")

    rows: list[dict[str, Any]] = []
    for item in chosen_items:
        row = s75._run_mainline(root, cfg, data, item, initial_equity)
        for gate_row in row["gate_rows"]:
            gate_row["metrics"] = s77._with_window_metrics(gate_row.get("metrics", {}), full_start, full_end)
            gate_row["recent_metrics"] = s77._with_window_metrics(
                s77._recent_metrics(gate_row.get("gated_df"), initial_equity),
                recent_start,
                full_end,
            )
        row["base_metrics"] = s77._with_window_metrics(row.get("base_metrics", {}), full_start, full_end)
        rows.append(row)

    ref_row = next((r for r in rows if r["name"] == "mainline_live_base"), rows[0])
    ref_best = None
    ref_best_score = -1e18
    for gate_row in ref_row["gate_rows"]:
        score = s77._main_score_dual(gate_row["metrics"], gate_row["recent_metrics"], gate_row["recent_metrics"])
        if score > ref_best_score:
            ref_best_score = score
            ref_best = gate_row
    ref_recent = ref_best["recent_metrics"] if ref_best else rows[0]["gate_rows"][0]["recent_metrics"]

    for row in rows:
        best = None
        best_score = -1e18
        for gate_row in row["gate_rows"]:
            score = s77._main_score_dual(gate_row["metrics"], gate_row["recent_metrics"], ref_recent)
            gate_row["score"] = score
            gate_row["gate"] = s77._main_dual_label(gate_row["metrics"], gate_row["recent_metrics"], ref_recent)
            if score > best_score:
                best_score = score
                best = gate_row
        row["best_gate"] = best if best is not None else row["gate_rows"][0]
        row["walkforward"] = _wf_result(row, ref_row, initial_equity, recent_start, full_end)

    rows.sort(key=lambda r: float(r["walkforward"]["score"]), reverse=True)
    reports_raw = root / "reports" / "research_raw"
    reports_raw.mkdir(parents=True, exist_ok=True)
    _write_report(
        reports_raw / "stage81_mainline_walkforward_latest.txt",
        reports_raw / "stage81_mainline_walkforward_latest.json",
        rows,
        ref_row,
    )
    print(reports_raw / "stage81_mainline_walkforward_latest.txt")
    print(reports_raw / "stage81_mainline_walkforward_latest.json")


if __name__ == "__main__":
    main()
