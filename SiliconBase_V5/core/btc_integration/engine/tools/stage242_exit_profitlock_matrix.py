from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in (None, ""):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import tools.stage230_expanded_combo_matrix as s230
except Exception:
    import importlib.util
    _p = Path(__file__).resolve().parent / 'stage230_expanded_combo_matrix.py'
    spec = importlib.util.spec_from_file_location('stage230_expanded_combo_matrix', _p)
    if spec is None or spec.loader is None:
        raise
    s230 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(s230)

REC_ORDER = {
    "promote_primary": 0,
    "keep_protective": 1,
    "keep_secondary": 2,
    "keep_research": 3,
    "audit_only": 4,
    "discard": 5,
}

PARAM_MAP: dict[str, dict[str, float]] = {p["param_id"]: dict(p) for p in s230.PARAMS}

LANES: list[dict[str, Any]] = [
    # BTC audit only
    {"symbol": "btc", "entry_tf": "5m", "filter_tf": "15m", "family": "bb_meanrev", "param_id": "p4", "mode": "short_only", "role": "audit", "why": "BTC 继续只审计，不升 live。"},
    # BNB protective
    {"symbol": "bnb", "entry_tf": "5m", "filter_tf": "15m", "family": "bb_meanrev", "param_id": "p2", "mode": "dual", "role": "protective", "why": "BNB 继续保护 current seed，只看 exit 是否还能抬升。"},
    {"symbol": "bnb", "entry_tf": "5m", "filter_tf": "15m", "family": "bb_meanrev", "param_id": "p2", "mode": "short_only", "role": "protective", "why": "BNB short_only 作为提频备选，先只做 exit 矩阵。"},
    {"symbol": "bnb", "entry_tf": "5m", "filter_tf": "15m", "family": "bb_meanrev", "param_id": "p3", "mode": "dual", "role": "protective", "why": "BNB p3 dual 作为 seed 邻域继续保留。"},
    # ETH cluster
    {"symbol": "eth", "entry_tf": "1h", "filter_tf": "4h", "family": "sweep_reclaim", "param_id": "p4", "mode": "long_only", "role": "primary", "why": "ETH 新主候选之一：1h/4h sweep_reclaim p4 long_only。"},
    {"symbol": "eth", "entry_tf": "1h", "filter_tf": "4h", "family": "sweep_reclaim", "param_id": "p3", "mode": "long_only", "role": "neighbor", "why": "ETH sweep_reclaim 邻域。"},
    {"symbol": "eth", "entry_tf": "1h", "filter_tf": "4h", "family": "bb_meanrev", "param_id": "p4", "mode": "long_only", "role": "neighbor", "why": "ETH 1h/4h bb_meanrev p4 long_only。"},
    {"symbol": "eth", "entry_tf": "1h", "filter_tf": "4h", "family": "bb_meanrev", "param_id": "p3", "mode": "long_only", "role": "neighbor", "why": "ETH 1h/4h bb_meanrev p3 long_only。"},
    {"symbol": "eth", "entry_tf": "1h", "filter_tf": "4h", "family": "bb_meanrev", "param_id": "p3", "mode": "dual", "role": "protective", "why": "ETH 旧 slow seed，继续保护性对照。"},
    {"symbol": "eth", "entry_tf": "30m", "filter_tf": "1h", "family": "bb_meanrev", "param_id": "p1", "mode": "dual", "role": "research", "why": "ETH 高胜率小样本快线，只留 research。"},
    # SOL cluster
    {"symbol": "sol", "entry_tf": "1h", "filter_tf": "4h", "family": "sweep_reclaim", "param_id": "p3", "mode": "long_only", "role": "primary", "why": "SOL 慢线新强点。"},
    {"symbol": "sol", "entry_tf": "1h", "filter_tf": "4h", "family": "sweep_reclaim", "param_id": "p2", "mode": "long_only", "role": "neighbor", "why": "SOL sweep_reclaim 邻域。"},
    {"symbol": "sol", "entry_tf": "5m", "filter_tf": "15m", "family": "bb_meanrev", "param_id": "p4", "mode": "dual", "role": "primary", "why": "SOL 高频双向主战场。"},
    {"symbol": "sol", "entry_tf": "5m", "filter_tf": "15m", "family": "bb_meanrev", "param_id": "p4", "mode": "short_only", "role": "primary", "why": "SOL 高频 short_only 强分支。"},
    {"symbol": "sol", "entry_tf": "5m", "filter_tf": "15m", "family": "bb_meanrev", "param_id": "p3", "mode": "dual", "role": "neighbor", "why": "SOL p3 dual 邻域。"},
    {"symbol": "sol", "entry_tf": "5m", "filter_tf": "15m", "family": "bb_meanrev", "param_id": "p2", "mode": "dual", "role": "neighbor", "why": "SOL p2 dual 邻域。"},
    {"symbol": "sol", "entry_tf": "1h", "filter_tf": "4h", "family": "bb_meanrev", "param_id": "p1", "mode": "long_only", "role": "primary", "why": "SOL 高胜率慢线参考。"},
]

EXIT_PROFILES: list[dict[str, Any]] = [
    {"exit_profile": "base_hold", "stop_mult": 1.00, "trail_mult": 1.00, "arm_add": 0.00, "hold_add": 0, "wick_ratio_add": 0.00, "wick_atr_add": 0.00},
    {"exit_profile": "strict_stop_late_lock", "stop_mult": 0.90, "trail_mult": 1.12, "arm_add": 0.35, "hold_add": 8, "wick_ratio_add": -0.02, "wick_atr_add": -0.10},
    {"exit_profile": "late_lock_loose", "stop_mult": 1.05, "trail_mult": 1.28, "arm_add": 0.60, "hold_add": 16, "wick_ratio_add": 0.00, "wick_atr_add": 0.00},
    {"exit_profile": "late_lock_wide", "stop_mult": 1.12, "trail_mult": 1.42, "arm_add": 0.90, "hold_add": 24, "wick_ratio_add": 0.01, "wick_atr_add": 0.10},
    {"exit_profile": "very_late_lock", "stop_mult": 1.18, "trail_mult": 1.58, "arm_add": 1.20, "hold_add": 32, "wick_ratio_add": 0.02, "wick_atr_add": 0.15},
    {"exit_profile": "tight_guard_control", "stop_mult": 0.82, "trail_mult": 0.95, "arm_add": 0.12, "hold_add": 0, "wick_ratio_add": -0.04, "wick_atr_add": -0.20},
]


def lane_key(row: dict[str, Any]) -> tuple[str, str, str, str, str, str]:
    return (
        str(row["symbol"]),
        str(row["entry_tf"]),
        str(row["filter_tf"]),
        str(row["family"]),
        str(row["param_id"]),
        str(row["mode"]),
    )


def maybe_has_raw(project_dir: Path, symbol: str, entry_tf: str) -> bool:
    if entry_tf != "5m":
        return True
    return (project_dir / "data" / "raw" / f"{symbol}_5m.csv").exists()


def tuned_params(param_id: str, profile: dict[str, Any]) -> dict[str, float]:
    base = dict(PARAM_MAP[param_id])
    out = dict(base)
    out["stop_atr"] = round(max(0.70, base["stop_atr"] * float(profile["stop_mult"])), 4)
    out["trail_atr"] = round(max(0.90, base["trail_atr"] * float(profile["trail_mult"])), 4)
    out["arm_rr"] = round(max(0.20, base["arm_rr"] + float(profile["arm_add"])), 4)
    out["max_hold"] = int(max(16, base["max_hold"] + int(profile["hold_add"])))
    out["wick_ratio"] = round(min(0.90, max(0.50, base["wick_ratio"] + float(profile["wick_ratio_add"]))), 4)
    out["wick_atr"] = round(min(4.50, max(1.80, base["wick_atr"] + float(profile["wick_atr_add"]))), 4)
    out["exit_profile"] = str(profile["exit_profile"])
    return out


def build_row(res: dict[str, Any], lane: dict[str, Any], p: dict[str, float]) -> dict[str, Any]:
    row = dict(res)
    row["lane_role"] = lane["role"]
    row["lane_focus_reason"] = lane["why"]
    row["exit_profile"] = p["exit_profile"]
    row["stop_atr"] = p["stop_atr"]
    row["trail_atr"] = p["trail_atr"]
    row["arm_rr"] = p["arm_rr"]
    row["max_hold"] = p["max_hold"]
    row["wick_ratio"] = p["wick_ratio"]
    row["wick_atr"] = p["wick_atr"]
    return row


def add_deltas(df: pd.DataFrame) -> pd.DataFrame:
    base_map: dict[tuple[str, str, str, str, str, str], dict[str, Any]] = {}
    for rec in df.to_dict(orient="records"):
        if rec.get("exit_profile") == "base_hold":
            base_map[lane_key(rec)] = rec

    dr: list[dict[str, Any]] = []
    for rec in df.to_dict(orient="records"):
        base = base_map.get(lane_key(rec), {})
        rec["delta_recent_ret"] = float(rec.get("recent_ret", 0.0)) - float(base.get("recent_ret", 0.0))
        rec["delta_recent_pf"] = float(rec.get("recent_pf", 0.0)) - float(base.get("recent_pf", 0.0))
        rec["delta_recent_dd"] = float(rec.get("recent_dd", 0.0)) - float(base.get("recent_dd", 0.0))
        rec["delta_wf_ret"] = float(rec.get("wf_ret", 0.0)) - float(base.get("wf_ret", 0.0))
        rec["delta_wf_pf"] = float(rec.get("wf_pf", 0.0)) - float(base.get("wf_pf", 0.0))
        rec["delta_wf_dd"] = float(rec.get("wf_dd", 0.0)) - float(base.get("wf_dd", 0.0))
        dr.append(rec)
    return pd.DataFrame(dr)


def improved_vs_base(row: dict[str, Any]) -> bool:
    recent_dd_ok = float(row.get("delta_recent_dd", 0.0)) >= -4.0
    wf_dd_ok = float(row.get("delta_wf_dd", 0.0)) >= -4.0
    return bool(
        recent_dd_ok
        and wf_dd_ok
        and (
            float(row.get("delta_recent_pf", 0.0)) >= 0.05
            or float(row.get("delta_recent_ret", 0.0)) >= 1.5
            or float(row.get("delta_wf_pf", 0.0)) >= 0.05
            or float(row.get("delta_wf_ret", 0.0)) >= 1.0
        )
    )


def classify(row: dict[str, Any]) -> str:
    symbol = str(row.get("symbol", ""))
    if symbol == "btc" and (int(row.get("recent_trades", 0) or 0) == 0 or int(row.get("wf_trades", 0) or 0) == 0):
        return "audit_only"

    recent_trades = int(row.get("recent_trades", 0) or 0)
    wf_trades = int(row.get("wf_trades", 0) or 0)
    full_trades = int(row.get("full_trades", 0) or 0)
    recent_ret = float(row.get("recent_ret", 0.0))
    recent_pf = float(row.get("recent_pf", 0.0))
    recent_dd = float(row.get("recent_dd", 0.0))
    wf_ret = float(row.get("wf_ret", 0.0))
    wf_pf = float(row.get("wf_pf", 0.0))
    improved = improved_vs_base(row)

    if recent_trades >= 10 and wf_trades >= 6 and full_trades >= 20:
        if recent_pf >= 1.35 and recent_ret > 0 and wf_pf >= 1.05 and wf_ret >= 0 and recent_dd >= -18 and improved:
            return "promote_primary"
        if recent_pf >= 1.20 and recent_ret > 0 and wf_pf >= 1.00 and wf_ret > -5 and recent_dd >= -22:
            return "keep_protective" if improved else "keep_secondary"
    if recent_trades >= 6 and full_trades >= 15 and ((recent_pf >= 1.0 and recent_ret > 0) or (wf_pf >= 1.0 and wf_ret > 0)):
        return "keep_research"
    return "discard"


def score(row: dict[str, Any]) -> float:
    recent_ret = float(row.get("recent_ret", 0.0))
    recent_pf = float(row.get("recent_pf", 0.0))
    wf_ret = float(row.get("wf_ret", 0.0))
    wf_pf = float(row.get("wf_pf", 0.0))
    full_ret = float(row.get("full_ret", 0.0))
    full_pf = float(row.get("full_pf", 0.0))
    recent_win = float(row.get("recent_win", 0.0))
    wf_win = float(row.get("wf_win", 0.0))
    sample_bonus = min(int(row.get("recent_trades", 0) or 0), 24) * 0.35 + min(int(row.get("wf_trades", 0) or 0), 18) * 0.25
    recent_dd_pen = max(0.0, -float(row.get("recent_dd", 0.0)) - 10.0) * 0.45
    wf_dd_pen = max(0.0, -float(row.get("wf_dd", 0.0)) - 8.0) * 0.35
    delta_bonus = (
        11.0 * float(row.get("delta_recent_pf", 0.0))
        + 0.30 * float(row.get("delta_recent_ret", 0.0))
        + 7.5 * float(row.get("delta_wf_pf", 0.0))
        + 0.18 * float(row.get("delta_wf_ret", 0.0))
    )
    out = (
        min(80.0, recent_ret) * 0.50
        + 15.0 * max(-1.0, recent_pf - 1.0)
        + min(50.0, wf_ret) * 0.35
        + 10.0 * max(-1.0, wf_pf - 1.0)
        + min(25.0, max(-25.0, full_ret)) * 0.06
        + 2.5 * max(-1.0, full_pf - 1.0)
        + 0.10 * recent_win
        + 0.06 * wf_win
        + sample_bonus
        + delta_bonus
        - recent_dd_pen
        - wf_dd_pen
    )
    if str(row.get("symbol", "")) == "btc" and (int(row.get("recent_trades", 0) or 0) == 0 or int(row.get("wf_trades", 0) or 0) == 0):
        out -= 30.0
    return out


def format_lane(row: dict[str, Any]) -> str:
    return f"{row['entry_tf']}/{row['filter_tf']} | {row['family']} | {row['param_id']} | {row['mode']}"


def run(project_dir: Path) -> dict[str, Any]:
    out_dir = project_dir / "reports" / "research_raw"
    out_dir.mkdir(parents=True, exist_ok=True)
    lab = s230.ExpandedComboLab(project_dir, symbols=["btc", "bnb", "eth", "sol"])

    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for lane in LANES:
        if not maybe_has_raw(project_dir, lane["symbol"], lane["entry_tf"]):
            skipped.append({**lane, "reason": "missing_5m_raw"})
            continue
        for profile in EXIT_PROFILES:
            p = tuned_params(str(lane["param_id"]), profile)
            print(
                f"[stage242] eval={lane['symbol']}:{lane['entry_tf']}/{lane['filter_tf']}:{lane['family']}:{lane['param_id']}:{lane['mode']}:{profile['exit_profile']}",
                flush=True,
            )
            try:
                res = lab.evaluate(str(lane["symbol"]), str(lane["entry_tf"]), str(lane["filter_tf"]), str(lane["family"]), p, str(lane["mode"]))
            except Exception as exc:
                skipped.append({**lane, "exit_profile": profile["exit_profile"], "reason": f"eval_error:{type(exc).__name__}"})
                continue
            rows.append(build_row(res, lane, p))

    df = pd.DataFrame(rows)
    if df.empty:
        raise SystemExit("stage242 no rows evaluated")
    df = add_deltas(df)
    df["recommendation"] = df.apply(lambda r: classify(r.to_dict()), axis=1)
    df["recommendation_rank"] = df["recommendation"].map(REC_ORDER).astype(int)
    df["composite_score"] = df.apply(lambda r: score(r.to_dict()), axis=1)
    df.sort_values(
        ["recommendation_rank", "symbol", "composite_score", "recent_pf", "recent_ret", "wf_pf", "wf_ret"],
        ascending=[True, True, False, False, False, False, False],
        inplace=True,
    )

    counts = Counter(df["recommendation"].tolist())
    by_symbol: dict[str, Any] = {}
    for symbol in ["btc", "bnb", "eth", "sol"]:
        sub = df[df["symbol"] == symbol].copy()
        if sub.empty:
            by_symbol[symbol] = {"status": "none"}
            continue
        sub.sort_values(["recommendation_rank", "composite_score", "recent_pf", "recent_ret", "wf_pf"], ascending=[True, False, False, False, False], inplace=True)
        by_symbol[symbol] = {"best": sub.iloc[0].to_dict(), "top5": sub.head(5).to_dict(orient="records")}

    by_lane: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rec in df.to_dict(orient="records"):
        key = " | ".join([str(rec["symbol"]), format_lane(rec)])
        by_lane[key].append(rec)
    lane_deltas: list[dict[str, Any]] = []
    for key, items in by_lane.items():
        items = sorted(items, key=lambda x: (x["recommendation_rank"], -x["composite_score"]))
        lane_deltas.append({"lane": key, "best_exit": items[0]["exit_profile"], "best_recent_ret": items[0]["recent_ret"], "best_wf_ret": items[0]["wf_ret"], "best_recent_pf": items[0]["recent_pf"], "best_wf_pf": items[0]["wf_pf"], "recommendation": items[0]["recommendation"]})
    lane_deltas.sort(key=lambda x: (REC_ORDER[x["recommendation"]], -x["best_recent_pf"], -x["best_wf_pf"], -x["best_recent_ret"]))

    all_csv = out_dir / "stage242_exit_profitlock_matrix_all.csv"
    df.to_csv(all_csv, index=False)
    summary = {
        "goal": "continue matrix only; test stop/profitlock / dynamic stopline; live untouched",
        "candidate_lanes": len(LANES),
        "exit_profiles": [p["exit_profile"] for p in EXIT_PROFILES],
        "evaluated_rows": int(len(df)),
        "counts": {k: int(counts.get(k, 0)) for k in ["promote_primary", "keep_protective", "keep_secondary", "keep_research", "audit_only", "discard"]},
        "best_by_symbol": by_symbol,
        "best_by_lane": lane_deltas[:12],
        "skipped": skipped,
    }
    (out_dir / "stage242_exit_profitlock_matrix_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    lines: list[str] = []
    lines.append("[stage242_exit_profitlock_matrix]")
    lines.append("goal=继续矩阵，不修 live；专测 strict stop + late profit lock + dynamic stopline，验证‘盈利不早平’是否真有增益")
    lines.append(f"candidate_lanes={len(LANES)}")
    lines.append(f"exit_profiles={len(EXIT_PROFILES)}")
    lines.append(f"evaluated_rows={len(df)}")
    for key in ["promote_primary", "keep_protective", "keep_secondary", "keep_research", "audit_only", "discard"]:
        lines.append(f"{key}_total={int(counts.get(key, 0))}")
    if skipped:
        lines.append(f"skipped_total={len(skipped)}")
    lines.append("ranking=6年只作软约束；主排序继续看近2年 + WF；这轮重点看 exit profile 是否在不明显恶化回撤的前提下抬升 PF/收益")
    lines.append("")
    lines.append("[best_by_symbol]")
    for symbol in ["btc", "bnb", "eth", "sol"]:
        info = by_symbol.get(symbol, {})
        if "best" not in info:
            lines.append(f"- {symbol} | none")
            continue
        best = info["best"]
        lines.append(
            f"- {symbol} | top={format_lane(best)} | exit={best['exit_profile']} | "
            f"recent={best['recent_ret']:.2f}%/{best['recent_win']:.2f}%/PF{best['recent_pf']:.3f} | "
            f"wf={best['wf_ret']:.2f}%/{best['wf_win']:.2f}%/PF{best['wf_pf']:.3f} | "
            f"6y={best['full_ret']:.2f}%/PF{best['full_pf']:.3f} | rec={best['recommendation']} | role={best['lane_role']}"
        )
    lines.append("")
    lines.append("[best_by_lane]")
    for row in lane_deltas[:10]:
        lines.append(
            f"- {row['lane']} | best_exit={row['best_exit']} | recent={row['best_recent_ret']:.2f}%/PF{row['best_recent_pf']:.3f} | wf={row['best_wf_ret']:.2f}%/PF{row['best_wf_pf']:.3f} | rec={row['recommendation']}"
        )
    lines.append("")
    lines.append("[next_hint]")
    lines.append("- 若 ETH/SOL 的 late_lock_* 明显优于 base_hold，下一轮才把 profitlock 逻辑抽成 runtime-ready helper；当前 live 先不动。")
    lines.append("- 若 BNB 只出现小幅改善，后续只改研究 exit 层，不碰 entry。")
    lines.append("- 若 BTC 仍是 audit_only，就继续冻结 BTC fast lane。")
    (out_dir / "stage242_exit_profitlock_matrix_latest.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage242 exit/profitlock matrix")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()
    run(Path(args.project_dir).expanduser().resolve())


if __name__ == "__main__":
    main()
