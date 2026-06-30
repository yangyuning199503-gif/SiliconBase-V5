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
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
    from tools import research_config_baseline as rcb
    from tools import stage76_branch_event_state_lab as s76
    from tools import stage78_branch_dual_window_lab as s78
    from tools import stage82_branch_walkforward_lab as s82
    from tools import stage90_event_alpha_matrix as s90
except Exception as exc:
    import logging
    logging.warning(f"[stage92] 缺少依赖模块(stage76/78/82/90)，功能受限: {exc}")
    rcb = None
    s76 = None
    s78 = None
    s82 = None
    s90 = None


LANE_PACKS_FULL: dict[str, list[str]] = {
    "eth_long": [
        "eth_fast_trend_lb16_longonly",
        "eth_breakout_long_follow_lb16_atr050_adx22_s034",
        "eth_breakout_long_follow_lb18_atr055_adx24_s030",
        "eth_breakout_long_guarded_lb20_atr060_adx26_s028",
        "eth_breakout_long_guarded_lb22_atr065_adx28_s026",
        "eth_pullback_long_core_adx22_cd5_lb20_zone024_s040",
        "eth_pullback_long_core_adx24_cd6_lb22_zone026_s036",
        "eth_shortwave_long_core_lb20_zone024_adx20_s042",
        "eth_shortwave_long_core_lb22_zone026_adx22_s038",
        "eth_long_core_adx26_cd6_lb24_zone028_s032",
    ],
    "eth_short": [
        "eth_short_shock_lb16_adx24",
        "eth_short_shock_fast_lb16_atr052_adx22_s078",
        "eth_short_shock_control_lb18_adx26_s074",
        "eth_short_shock_guarded_lb20_atr062_adx28_s070",
        "eth_retest_short_trend_lb16_atr050_adx20_s076",
        "eth_retest_short_trend_lb18_atr055_adx22_s072",
        "eth_retest_short_trend_lb20_atr060_adx24_s068",
        "eth_fast_trend_shortonly",
        "eth_shortwave_tight_shortonly",
    ],
    "sol_long": [
        "sol_shortwave_smooth_longonly",
        "sol_shortwave_longonly",
        "sol_pullback_long_core_adx22_cd5_lb18_zone024_s046",
        "sol_pullback_long_core_adx24_cd6_lb20_zone025_s042",
        "sol_pullback_long_core_adx26_cd6_lb22_zone026_s040",
        "sol_shortwave_long_core_lb18_zone024_adx20_s044",
        "sol_shortwave_long_core_lb22_zone026_adx22_s040",
        "sol_long_core_adx28_cd6_lb22_zone027_s038",
    ],
    "sol_short": [
        "sol_fast_trend_lb16_shortonly",
        "sol_fast_trend_short_guarded_lb16_atr055_adx22_s072",
        "sol_fast_trend_short_guarded_lb18_atr060_adx24_s068",
        "sol_fast_trend_short_guarded_lb20_atr065_adx26_s060",
        "sol_fast_trend_short_guarded_lb22_atr070_adx28_s056",
        "sol_short_shock_lb16_adx22",
        "sol_short_shock_guarded_lb18_adx24_s062",
        "sol_short_shock_guarded_lb20_adx26_s058",
        "sol_retest_short_trend_lb16_atr050_adx20_s068",
        "sol_retest_short_trend_lb18_atr055_adx22_s064",
        "sol_hybrid_mr_short_fast_bb30_std20_s012",
        "sol_hybrid_mr_shortonly",
    ],
}

LANE_PACKS_QUICK: dict[str, list[str]] = {
    "eth_long": [
        "eth_breakout_long_follow_lb16_atr050_adx22_s034",
        "eth_breakout_long_follow_lb18_atr055_adx24_s030",
        "eth_pullback_long_core_adx22_cd5_lb20_zone024_s040",
        "eth_shortwave_long_core_lb20_zone024_adx20_s042",
    ],
    "eth_short": [
        "eth_short_shock_fast_lb16_atr052_adx22_s078",
        "eth_short_shock_control_lb18_adx26_s074",
        "eth_retest_short_trend_lb16_atr050_adx20_s076",
        "eth_retest_short_trend_lb20_atr060_adx24_s068",
    ],
    "sol_long": [
        "sol_shortwave_smooth_longonly",
        "sol_pullback_long_core_adx22_cd5_lb18_zone024_s046",
        "sol_shortwave_long_core_lb18_zone024_adx20_s044",
        "sol_pullback_long_core_adx24_cd6_lb20_zone025_s042",
    ],
    "sol_short": [
        "sol_fast_trend_short_guarded_lb16_atr055_adx22_s072",
        "sol_fast_trend_short_guarded_lb18_atr060_adx24_s068",
        "sol_retest_short_trend_lb16_atr050_adx20_s068",
        "sol_short_shock_guarded_lb18_adx24_s062",
    ],
}


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


def _candidate_items(profile: str) -> tuple[dict[str, list[str]], dict[str, dict[str, Any]]]:
    packs = copy.deepcopy(LANE_PACKS_FULL if str(profile).lower() == "full" else LANE_PACKS_QUICK)
    item_map = {str(item.get("name")): copy.deepcopy(item) for item in s76._candidate_items()}
    clean: dict[str, list[str]] = {}
    for lane, names in packs.items():
        clean[lane] = [name for name in names if name in item_map]
    return clean, item_map


def _lane_of_row(row: dict[str, Any]) -> str:
    return f"{str(row.get('symbol')).lower()}_{str(row.get('family')).lower()}"


def _dual_window_row(root: Path, cfg: dict[str, Any], item: dict[str, Any], initial_equity: float, bounds_cache: dict[str, tuple[pd.Timestamp, pd.Timestamp]]) -> dict[str, Any]:
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
        gate_row["score"] = s78._branch_score_dual(gate_row["metrics"], gate_row["recent_metrics"])
        gate_row["gate"] = s78._branch_dual_label(gate_row["metrics"], gate_row["recent_metrics"])
    row["base_metrics"] = s78._with_window_metrics(row.get("base_metrics", {}), full_start, full_end)
    best = max(row["gate_rows"], key=lambda g: float(g.get("score", -1e18)))
    row["best_gate"] = best
    row["full_start"] = full_start
    row["full_end"] = full_end
    row["recent_start"] = recent_start
    row["dual_label"] = str(best.get("gate") or "-")
    row["dual_score"] = float(best.get("score", -1e18))
    return row


def _select_wf_names(dual_rows: list[dict[str, Any]], per_lane: int) -> list[str]:
    out: list[str] = []
    seen = set()
    lanes = ["eth_long", "eth_short", "sol_long", "sol_short"]
    for lane in lanes:
        lane_rows = [r for r in dual_rows if _lane_of_row(r) == lane]
        lane_rows.sort(key=lambda r: float(r.get("dual_score", -1e18)), reverse=True)
        for row in lane_rows[: max(1, per_lane)]:
            name = str(row.get("name"))
            if name and name not in seen:
                seen.add(name)
                out.append(name)
    return out


def _fusion_row(root: Path, cfg: dict[str, Any], item: dict[str, Any], initial_equity: float) -> dict[str, Any]:
    row = s90._run_branch(root, cfg, item, initial_equity)
    recent_start = max(s78.RECENT_START, pd.to_datetime(row.get("full_metrics", {}).get("start", s78.RECENT_START), errors="coerce"))
    row["walkforward"] = s82._wf_result(row, initial_equity, recent_start, row["full_end"])
    row["dominant_gate"] = s90._dominant_gate(row, branch=True)
    row["alpha_score"] = s90._branch_alpha_score(row)
    row["decision"] = s90._alpha_label(
        row["dominant_gate"].get("recent_metrics", {}),
        row["walkforward"].get("metrics", {}),
        int(row["walkforward"].get("positive_folds", 0) or 0),
        s90._event_fold_share(row["walkforward"]),
        branch=True,
    )
    return row


def _best_by_lane(rows: list[dict[str, Any]], key_name: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    ordered = sorted(rows, key=lambda r: float(r.get(key_name, -1e18)), reverse=True)
    for row in ordered:
        lane = _lane_of_row(row)
        out.setdefault(lane, row)
    return out


def _demo_candidates(wf_by_lane: dict[str, dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for lane, row in wf_by_lane.items():
        wf = row.get("walkforward", {}) or {}
        best = row.get("best_gate", {}) or {}
        wf_m = wf.get("metrics", {}) or {}
        recent_m = best.get("recent_metrics", {}) or {}
        if str(wf.get("label", "")).lower() not in {"hold", "pass"}:
            continue
        if _safe_float(wf_m.get("ret")) <= 0 or _safe_float(recent_m.get("ret")) <= 0:
            continue
        out[lane] = str(row.get("name") or "")
    return out


def _write_stage82_txt(wf_best: dict[str, dict[str, Any]], demo_map: dict[str, str]) -> str:
    lines: list[str] = []
    lines.append("Stage82 Branch Walkforward（由 Stage92 开放式前沿回测刷新）")
    lines.append("判断口径：6年必看但只作软约束，优先看近2年 + WF。")
    lines.append("")
    lines.append("=== 各赛道当前最优 ===")
    for lane in ["eth_long", "eth_short", "sol_long", "sol_short"]:
        row = wf_best.get(lane)
        if not row:
            continue
        recent_m = (row.get("best_gate") or {}).get("recent_metrics", {}) or {}
        wf = row.get("walkforward", {}) or {}
        oos_m = wf.get("metrics", {}) or {}
        lines.append(
            f"- {lane}: {row['name']} | recent 收益={_fmt_pct(recent_m.get('ret'))} 月化={_fmt_pct(recent_m.get('monthlyized_ret'))} PF={_safe_float(recent_m.get('pf')):.3f} | WF 收益={_fmt_pct(oos_m.get('ret'))} 月化={_fmt_pct(oos_m.get('monthlyized_ret'))} PF={_safe_float(oos_m.get('pf')):.3f} MaxDD={_fmt_pct(oos_m.get('maxdd'))} | 正收益折={wf.get('positive_folds',0)}/{wf.get('total_folds',0)} | {wf.get('label')}"
        )
    lines.append("")
    lines.append("=== Demo 候选 ===")
    if demo_map:
        for lane in ["eth_short", "sol_long", "eth_long", "sol_short"]:
            name = demo_map.get(lane)
            if name:
                lines.append(f"- {lane}: {name}")
    else:
        lines.append("- 当前没有新增 demo_ready；继续 research。")
    return "\n".join(lines).rstrip() + "\n"


def _write_outputs(
    reports_raw: Path,
    profile: str,
    packs: dict[str, list[str]],
    dual_rows: list[dict[str, Any]],
    wf_rows: list[dict[str, Any]],
    fusion_rows: list[dict[str, Any]],
) -> None:
    dual_best = _best_by_lane(dual_rows, "dual_score")
    wf_best = _best_by_lane(wf_rows, "wf_score")
    fusion_best = _best_by_lane(fusion_rows, "alpha_score")
    demo_map = _demo_candidates(wf_best)

    txt_lines: list[str] = []
    txt_lines.append("Stage92 ETH/SOL 开放式分支前沿")
    txt_lines.append("原则：ETH/SOL 多空四条腿都继续；6年总样本必看但只作软约束，判断以近2年 + WF 为主。")
    txt_lines.append("原则：先激进开方向，再用 walk-forward / event-alpha 收口；不因一轮失利就砍路径。")
    txt_lines.append(f"profile={profile} | dual_candidates={sum(len(v) for v in packs.values())} | wf_candidates={len(wf_rows)} | fusion_candidates={len(fusion_rows)}")
    txt_lines.append("")
    txt_lines.append("=== 双窗口每条腿当前领先 ===")
    for lane in ["eth_long", "eth_short", "sol_long", "sol_short"]:
        row = dual_best.get(lane)
        if not row:
            continue
        m1 = row["best_gate"]["metrics"]
        m2 = row["best_gate"]["recent_metrics"]
        txt_lines.append(
            f"- {lane}: {row['name']} | best_gate={row['best_gate'].get('gate_name')} ({row.get('dual_label')}) | 6年 收益={_fmt_pct(m1.get('ret'))} 月化={_fmt_pct(m1.get('monthlyized_ret'))} PF={_safe_float(m1.get('pf')):.3f} | 近2年 收益={_fmt_pct(m2.get('ret'))} 月化={_fmt_pct(m2.get('monthlyized_ret'))} PF={_safe_float(m2.get('pf')):.3f} | dual_score={float(row.get('dual_score',0.0)):+.2f}"
        )
    txt_lines.append("")
    txt_lines.append("=== WF 每条腿当前领先 ===")
    for lane in ["eth_long", "eth_short", "sol_long", "sol_short"]:
        row = wf_best.get(lane)
        if not row:
            continue
        recent_m = (row.get("best_gate") or {}).get("recent_metrics", {}) or {}
        wf = row.get("walkforward", {}) or {}
        oos_m = wf.get("metrics", {}) or {}
        txt_lines.append(
            f"- {lane}: {row['name']} | recent 收益={_fmt_pct(recent_m.get('ret'))} 月化={_fmt_pct(recent_m.get('monthlyized_ret'))} PF={_safe_float(recent_m.get('pf')):.3f} | WF 收益={_fmt_pct(oos_m.get('ret'))} 月化={_fmt_pct(oos_m.get('monthlyized_ret'))} PF={_safe_float(oos_m.get('pf')):.3f} MaxDD={_fmt_pct(oos_m.get('maxdd'))} | 正收益折={wf.get('positive_folds',0)}/{wf.get('total_folds',0)} | {wf.get('label')}"
        )
    txt_lines.append("")
    txt_lines.append("=== 事件/融合 alpha 每条腿当前领先 ===")
    for lane in ["eth_long", "eth_short", "sol_long", "sol_short"]:
        row = fusion_best.get(lane)
        if not row:
            continue
        dom = row.get("dominant_gate", {}) or {}
        wf = row.get("walkforward", {}) or {}
        m = wf.get("metrics", {}) or {}
        txt_lines.append(
            f"- {lane}: {row['name']} | dominant_gate={dom.get('gate_name')} | event_fold_share={s90._event_fold_share(wf):.2f} | WF 收益={_fmt_pct(m.get('ret'))} 月化={_fmt_pct(m.get('monthlyized_ret'))} PF={_safe_float(m.get('pf')):.3f} MaxDD={_fmt_pct(m.get('maxdd'))} | decision={row.get('decision')} | alpha_score={float(row.get('alpha_score',0.0)):+.2f}"
        )
    txt_lines.append("")
    txt_lines.append("=== Demo 候选（只挑近2年 + WF 同时为正且 hold/pass） ===")
    if demo_map:
        for lane in ["eth_short", "sol_long", "eth_long", "sol_short"]:
            name = demo_map.get(lane)
            if name:
                txt_lines.append(f"- {lane}: {name}")
    else:
        txt_lines.append("- 当前没有新增 demo_ready；继续 research。")

    payload = {
        "profile": profile,
        "packs": packs,
        "dual_rows": _json_safe(dual_rows),
        "wf_rows": _json_safe(wf_rows),
        "fusion_rows": _json_safe(fusion_rows),
        "dual_best_by_lane": {k: _json_safe(v) for k, v in dual_best.items()},
        "wf_best_by_lane": {k: _json_safe(v) for k, v in wf_best.items()},
        "fusion_best_by_lane": {k: _json_safe(v) for k, v in fusion_best.items()},
        "demo_candidates": demo_map,
    }

    stage92_txt = "\n".join(txt_lines).rstrip() + "\n"
    (reports_raw / "stage92_eth_sol_open_frontier_latest.txt").write_text(stage92_txt, encoding="utf-8")
    (reports_raw / "stage92_eth_sol_open_frontier_latest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    stage82_txt = _write_stage82_txt(wf_best, demo_map)
    (reports_raw / "stage82_branch_walkforward_latest.txt").write_text(stage82_txt, encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage92 ETH/SOL open frontier")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--profile", choices=["quick", "full"], default="quick")
    ap.add_argument("--wf-per-lane", type=int, default=2)
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    cfg = rcb.load_research_base_config(root)
    initial_equity = float(cfg.get("portfolio", {}).get("initial_equity", 100000.0))
    reports_raw = root / "reports" / "research_raw"
    reports_raw.mkdir(parents=True, exist_ok=True)

    packs, item_map = _candidate_items(str(args.profile))
    bounds_cache: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {}
    dual_rows: list[dict[str, Any]] = []
    print(f"[1/3] dual-window profile={args.profile}")
    for lane in ["eth_long", "eth_short", "sol_long", "sol_short"]:
        print(f"  - lane={lane} candidates={len(packs.get(lane, []))}")
        for name in packs.get(lane, []):
            dual_rows.append(_dual_window_row(root, cfg, item_map[name], initial_equity, bounds_cache))
    dual_rows.sort(key=lambda r: float(r.get("dual_score", -1e18)), reverse=True)

    wf_names = _select_wf_names(dual_rows, max(1, int(args.wf_per_lane)))
    print(f"[2/3] walk-forward shortlisted={len(wf_names)}")
    wf_rows: list[dict[str, Any]] = []
    for name in wf_names:
        row = next((copy.deepcopy(r) for r in dual_rows if str(r.get("name")) == name), None)
        if row is None:
            continue
        row["walkforward"] = s82._wf_result(row, initial_equity, row["recent_start"], row["full_end"])
        row["wf_score"] = float((row.get("walkforward") or {}).get("score", -1e18))
        wf_rows.append(row)
    wf_rows.sort(key=lambda r: float(r.get("wf_score", -1e18)), reverse=True)

    print(f"[3/3] fusion/event-alpha shortlisted={len(wf_rows)}")
    fusion_rows: list[dict[str, Any]] = []
    for row in wf_rows:
        name = str(row.get("name"))
        item = item_map.get(name)
        if not item:
            continue
        fusion_rows.append(_fusion_row(root, cfg, item, initial_equity))
    fusion_rows.sort(key=lambda r: float(r.get("alpha_score", -1e18)), reverse=True)

    _write_outputs(reports_raw, str(args.profile), packs, dual_rows, wf_rows, fusion_rows)

    # keep stage82 current shortlist aligned for downstream demo selection
    if wf_rows:
        stage82_payload = {"rows": _json_safe(wf_rows)}
        (reports_raw / "stage82_branch_walkforward_latest.json").write_text(json.dumps(stage82_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(reports_raw / "stage92_eth_sol_open_frontier_latest.txt")
    print(reports_raw / "stage92_eth_sol_open_frontier_latest.json")


if __name__ == "__main__":
    main()
