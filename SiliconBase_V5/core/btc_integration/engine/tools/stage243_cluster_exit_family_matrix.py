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

EXIT_PROFILES: dict[str, dict[str, Any]] = {
    "base_hold": {"exit_profile": "base_hold", "stop_mult": 1.00, "trail_mult": 1.00, "arm_add": 0.00, "hold_add": 0, "wick_ratio_add": 0.00, "wick_atr_add": 0.00},
    "strict_stop_late_lock": {"exit_profile": "strict_stop_late_lock", "stop_mult": 0.90, "trail_mult": 1.12, "arm_add": 0.35, "hold_add": 8, "wick_ratio_add": -0.02, "wick_atr_add": -0.10},
    "late_lock_loose": {"exit_profile": "late_lock_loose", "stop_mult": 1.05, "trail_mult": 1.28, "arm_add": 0.60, "hold_add": 16, "wick_ratio_add": 0.00, "wick_atr_add": 0.00},
    "late_lock_wide": {"exit_profile": "late_lock_wide", "stop_mult": 1.12, "trail_mult": 1.42, "arm_add": 0.90, "hold_add": 24, "wick_ratio_add": 0.01, "wick_atr_add": 0.10},
    "very_late_lock": {"exit_profile": "very_late_lock", "stop_mult": 1.18, "trail_mult": 1.58, "arm_add": 1.20, "hold_add": 32, "wick_ratio_add": 0.02, "wick_atr_add": 0.15},
    "tight_guard_control": {"exit_profile": "tight_guard_control", "stop_mult": 0.82, "trail_mult": 0.95, "arm_add": 0.12, "hold_add": 0, "wick_ratio_add": -0.04, "wick_atr_add": -0.20},
}

LANES: list[dict[str, Any]] = [
    # BTC: 保留旧窗口 s050 / s058 / s074 / s082 + dual，对 fast lane 只审计不升 live
    {"cluster": "btc_old_cluster", "symbol": "btc", "entry_tf": "5m", "filter_tf": "15m", "family": "bb_meanrev", "param_id": "p4", "mode": "short_only", "role": "audit", "profiles": ["base_hold", "very_late_lock", "tight_guard_control"], "why": "BTC fast short 继续只审计，不升 live。"},
    {"cluster": "btc_old_cluster", "symbol": "btc", "entry_tf": "1h", "filter_tf": "4h", "family": "bb_meanrev", "param_id": "p2", "mode": "dual", "role": "reserve", "profiles": ["base_hold", "late_lock_loose", "very_late_lock"], "why": "BTC 稳定 dual 线，用来对照 fast lane。"},
    {"cluster": "btc_old_cluster", "symbol": "btc", "entry_tf": "5m", "filter_tf": "15m", "family": "breakout_atr_adx", "param_id": "p4", "mode": "short_only", "role": "reserve", "profiles": ["base_hold", "strict_stop_late_lock", "tight_guard_control"], "why": "BTC breakout / retest short reserve。"},
    {"cluster": "btc_old_cluster", "symbol": "btc", "entry_tf": "5m", "filter_tf": "15m", "family": "retest_fail", "param_id": "p4", "mode": "short_only", "role": "reserve", "profiles": ["base_hold", "strict_stop_late_lock", "tight_guard_control"], "why": "BTC retest short reserve。"},
    {"cluster": "btc_old_cluster", "symbol": "btc", "entry_tf": "5m", "filter_tf": "15m", "family": "squeeze_pullback", "param_id": "p4", "mode": "dual", "role": "reserve", "profiles": ["base_hold", "late_lock_loose", "tight_guard_control"], "why": "BTC squeeze / dual reserve。"},

    # BNB: stage242 证明 strict_stop_late_lock 更适合 protectives；同时保留共识指标家族邻域测试
    {"cluster": "bnb_fast_cluster", "symbol": "bnb", "entry_tf": "5m", "filter_tf": "15m", "family": "bb_meanrev", "param_id": "p2", "mode": "dual", "role": "protective", "profiles": ["base_hold", "strict_stop_late_lock", "very_late_lock"], "why": "BNB current seed，继续保护。"},
    {"cluster": "bnb_fast_cluster", "symbol": "bnb", "entry_tf": "5m", "filter_tf": "15m", "family": "bb_meanrev", "param_id": "p2", "mode": "short_only", "role": "protective", "profiles": ["base_hold", "strict_stop_late_lock", "tight_guard_control"], "why": "BNB short_only 提频备选。"},
    {"cluster": "bnb_fast_cluster", "symbol": "bnb", "entry_tf": "5m", "filter_tf": "15m", "family": "bb_meanrev", "param_id": "p3", "mode": "dual", "role": "neighbor", "profiles": ["base_hold", "strict_stop_late_lock", "very_late_lock"], "why": "BNB p3 dual 邻域。"},
    {"cluster": "bnb_fast_cluster", "symbol": "bnb", "entry_tf": "5m", "filter_tf": "15m", "family": "ma_macd_bb", "param_id": "p2", "mode": "dual", "role": "research", "profiles": ["base_hold", "strict_stop_late_lock", "late_lock_loose"], "why": "BNB 共识指标组合验证，不直接删除。"},
    {"cluster": "bnb_fast_cluster", "symbol": "bnb", "entry_tf": "5m", "filter_tf": "15m", "family": "range_revert_grid", "param_id": "p2", "mode": "dual", "role": "research", "profiles": ["base_hold", "strict_stop_late_lock", "tight_guard_control"], "why": "BNB range/grid 候选，不照搬，只留研究。"},

    # ETH: 对齐旧窗口 s056 / s060 / s072 + short s068，并把 stage242 赢的 exit 放进去
    {"cluster": "eth_old_cluster", "symbol": "eth", "entry_tf": "1h", "filter_tf": "4h", "family": "bb_meanrev", "param_id": "p4", "mode": "long_only", "role": "primary", "profiles": ["base_hold", "late_lock_loose", "late_lock_wide", "very_late_lock"], "why": "ETH long 主候选之一，stage242 已明显受益。"},
    {"cluster": "eth_old_cluster", "symbol": "eth", "entry_tf": "1h", "filter_tf": "4h", "family": "sweep_reclaim", "param_id": "p4", "mode": "long_only", "role": "primary", "profiles": ["base_hold", "late_lock_loose", "late_lock_wide", "very_late_lock"], "why": "ETH reclaim/sweep 主候选，对齐旧窗口主簇。"},
    {"cluster": "eth_old_cluster", "symbol": "eth", "entry_tf": "1h", "filter_tf": "4h", "family": "reclaim_atr_rsi", "param_id": "p4", "mode": "long_only", "role": "primary", "profiles": ["base_hold", "late_lock_loose", "late_lock_wide", "very_late_lock"], "why": "ETH 直接回看 reclaim 家族，不提前删路。"},
    {"cluster": "eth_old_cluster", "symbol": "eth", "entry_tf": "1h", "filter_tf": "4h", "family": "bb_meanrev", "param_id": "p3", "mode": "long_only", "role": "neighbor", "profiles": ["base_hold", "late_lock_loose", "very_late_lock"], "why": "ETH p3 long 邻域。"},
    {"cluster": "eth_old_cluster", "symbol": "eth", "entry_tf": "1h", "filter_tf": "4h", "family": "sweep_reclaim", "param_id": "p3", "mode": "long_only", "role": "neighbor", "profiles": ["base_hold", "late_lock_loose", "late_lock_wide"], "why": "ETH sweep 邻域。"},
    {"cluster": "eth_old_cluster", "symbol": "eth", "entry_tf": "1h", "filter_tf": "4h", "family": "reclaim_atr_rsi", "param_id": "p3", "mode": "long_only", "role": "neighbor", "profiles": ["base_hold", "late_lock_loose", "late_lock_wide"], "why": "ETH reclaim 邻域。"},
    {"cluster": "eth_old_cluster", "symbol": "eth", "entry_tf": "1h", "filter_tf": "4h", "family": "bb_meanrev", "param_id": "p3", "mode": "dual", "role": "protective", "profiles": ["base_hold", "strict_stop_late_lock", "late_lock_loose"], "why": "ETH 旧 slow dual seed，继续保留。"},
    {"cluster": "eth_old_cluster", "symbol": "eth", "entry_tf": "30m", "filter_tf": "1h", "family": "bb_meanrev", "param_id": "p1", "mode": "dual", "role": "research", "profiles": ["base_hold", "late_lock_loose", "very_late_lock"], "why": "ETH 高胜率小样本快线，只留研究。"},
    {"cluster": "eth_old_cluster", "symbol": "eth", "entry_tf": "1h", "filter_tf": "4h", "family": "retest_fail", "param_id": "p4", "mode": "short_only", "role": "reserve", "profiles": ["base_hold", "strict_stop_late_lock", "tight_guard_control", "late_lock_wide"], "why": "ETH short s068 映射，必须保留。"},
    {"cluster": "eth_old_cluster", "symbol": "eth", "entry_tf": "30m", "filter_tf": "1h", "family": "retest_fail", "param_id": "p3", "mode": "short_only", "role": "reserve", "profiles": ["base_hold", "strict_stop_late_lock", "tight_guard_control"], "why": "ETH short 快线 reserve。"},

    # SOL: 对齐旧窗口 s046 / s044 / s076 / s080，并沿 stage242 胜出的 exit 继续扩
    {"cluster": "sol_old_cluster", "symbol": "sol", "entry_tf": "5m", "filter_tf": "15m", "family": "bb_meanrev", "param_id": "p4", "mode": "dual", "role": "primary", "profiles": ["base_hold", "late_lock_loose", "very_late_lock", "tight_guard_control"], "why": "SOL 高频双向主战场。"},
    {"cluster": "sol_old_cluster", "symbol": "sol", "entry_tf": "5m", "filter_tf": "15m", "family": "bb_meanrev", "param_id": "p4", "mode": "short_only", "role": "primary", "profiles": ["base_hold", "tight_guard_control", "very_late_lock"], "why": "SOL 高频 short 分支。"},
    {"cluster": "sol_old_cluster", "symbol": "sol", "entry_tf": "5m", "filter_tf": "15m", "family": "bb_meanrev", "param_id": "p3", "mode": "dual", "role": "neighbor", "profiles": ["base_hold", "late_lock_loose", "very_late_lock"], "why": "SOL p3 dual 邻域。"},
    {"cluster": "sol_old_cluster", "symbol": "sol", "entry_tf": "5m", "filter_tf": "15m", "family": "bb_meanrev", "param_id": "p2", "mode": "dual", "role": "neighbor", "profiles": ["base_hold", "late_lock_loose", "very_late_lock"], "why": "SOL p2 dual 邻域。"},
    {"cluster": "sol_old_cluster", "symbol": "sol", "entry_tf": "1h", "filter_tf": "4h", "family": "bb_meanrev", "param_id": "p1", "mode": "long_only", "role": "primary", "profiles": ["base_hold", "late_lock_loose", "tight_guard_control"], "why": "SOL 高胜率慢线参考。"},
    {"cluster": "sol_old_cluster", "symbol": "sol", "entry_tf": "1h", "filter_tf": "4h", "family": "sweep_reclaim", "param_id": "p3", "mode": "long_only", "role": "primary", "profiles": ["base_hold", "late_lock_loose", "tight_guard_control"], "why": "SOL 慢线 sweep 主候选。"},
    {"cluster": "sol_old_cluster", "symbol": "sol", "entry_tf": "1h", "filter_tf": "4h", "family": "sweep_reclaim", "param_id": "p2", "mode": "long_only", "role": "neighbor", "profiles": ["base_hold", "strict_stop_late_lock", "tight_guard_control"], "why": "SOL sweep 邻域。"},
    {"cluster": "sol_old_cluster", "symbol": "sol", "entry_tf": "5m", "filter_tf": "15m", "family": "range_revert_grid", "param_id": "p2", "mode": "dual", "role": "research", "profiles": ["base_hold", "strict_stop_late_lock", "tight_guard_control"], "why": "SOL grid/range 候选，不提前删。"},
    {"cluster": "sol_old_cluster", "symbol": "sol", "entry_tf": "5m", "filter_tf": "15m", "family": "retest_fail", "param_id": "p4", "mode": "short_only", "role": "reserve", "profiles": ["base_hold", "strict_stop_late_lock", "tight_guard_control"], "why": "SOL short reserve，对齐旧窗口 s076/s080 思路。"},
    {"cluster": "sol_old_cluster", "symbol": "sol", "entry_tf": "5m", "filter_tf": "15m", "family": "squeeze_pullback", "param_id": "p4", "mode": "dual", "role": "reserve", "profiles": ["base_hold", "late_lock_loose", "tight_guard_control"], "why": "SOL squeeze/pullback reserve。"},
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
    row["cluster"] = lane["cluster"]
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
    rows: list[dict[str, Any]] = []
    for rec in df.to_dict(orient="records"):
        base = base_map.get(lane_key(rec), {})
        rec["delta_recent_ret"] = float(rec.get("recent_ret", 0.0)) - float(base.get("recent_ret", 0.0))
        rec["delta_recent_pf"] = float(rec.get("recent_pf", 0.0)) - float(base.get("recent_pf", 0.0))
        rec["delta_recent_dd"] = float(rec.get("recent_dd", 0.0)) - float(base.get("recent_dd", 0.0))
        rec["delta_wf_ret"] = float(rec.get("wf_ret", 0.0)) - float(base.get("wf_ret", 0.0))
        rec["delta_wf_pf"] = float(rec.get("wf_pf", 0.0)) - float(base.get("wf_pf", 0.0))
        rec["delta_wf_dd"] = float(rec.get("wf_dd", 0.0)) - float(base.get("wf_dd", 0.0))
        rows.append(rec)
    return pd.DataFrame(rows)


def improved_vs_base(row: dict[str, Any]) -> bool:
    recent_dd_ok = float(row.get("delta_recent_dd", 0.0)) >= -4.5
    wf_dd_ok = float(row.get("delta_wf_dd", 0.0)) >= -4.5
    return bool(
        recent_dd_ok and wf_dd_ok and (
            float(row.get("delta_recent_pf", 0.0)) >= 0.06
            or float(row.get("delta_recent_ret", 0.0)) >= 1.5
            or float(row.get("delta_wf_pf", 0.0)) >= 0.06
            or float(row.get("delta_wf_ret", 0.0)) >= 1.0
        )
    )


def classify(row: dict[str, Any]) -> str:
    symbol = str(row.get("symbol", ""))
    role = str(row.get("lane_role", ""))
    if symbol == "btc" and role == "audit" and (int(row.get("recent_trades", 0) or 0) == 0 or int(row.get("wf_trades", 0) or 0) == 0):
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

    if role in {"primary", "protective", "neighbor"} and recent_trades >= 8 and wf_trades >= 5 and full_trades >= 20:
        if recent_pf >= 1.30 and recent_ret > 0 and wf_pf >= 1.05 and wf_ret >= 0 and recent_dd >= -20 and improved:
            return "promote_primary"
        if recent_pf >= 1.18 and recent_ret > 0 and wf_pf >= 1.00 and wf_ret > -6 and recent_dd >= -24:
            return "keep_protective" if role == "protective" and improved else "keep_secondary"
    if role in {"reserve", "research", "audit"}:
        if recent_trades >= 5 and full_trades >= 15 and ((recent_pf >= 1.0 and recent_ret > 0) or (wf_pf >= 1.0 and wf_ret > 0)):
            return "keep_research"
        if recent_trades >= 4 and recent_pf >= 1.1 and recent_ret > 0:
            return "keep_secondary"
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
    role_bonus = {"primary": 14.0, "protective": 10.0, "neighbor": 6.0, "reserve": 3.0, "research": 1.0, "audit": -4.0}.get(str(row.get("lane_role", "")), 0.0)
    out = (
        min(85.0, recent_ret) * 0.48
        + 15.0 * max(-1.0, recent_pf - 1.0)
        + min(55.0, wf_ret) * 0.34
        + 10.5 * max(-1.0, wf_pf - 1.0)
        + min(30.0, max(-30.0, full_ret)) * 0.05
        + 2.5 * max(-1.0, full_pf - 1.0)
        + 0.10 * recent_win
        + 0.06 * wf_win
        + sample_bonus
        + delta_bonus
        + role_bonus
        - recent_dd_pen
        - wf_dd_pen
    )
    if str(row.get("symbol", "")) == "btc" and str(row.get("lane_role", "")) == "audit" and (int(row.get("recent_trades", 0) or 0) == 0 or int(row.get("wf_trades", 0) or 0) == 0):
        out -= 40.0
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
        for profile_name in lane["profiles"]:
            profile = EXIT_PROFILES[profile_name]
            p = tuned_params(str(lane["param_id"]), profile)
            print(
                f"[stage243] eval={lane['cluster']}:{lane['symbol']}:{lane['entry_tf']}/{lane['filter_tf']}:{lane['family']}:{lane['param_id']}:{lane['mode']}:{profile_name}",
                flush=True,
            )
            try:
                res = lab.evaluate(str(lane["symbol"]), str(lane["entry_tf"]), str(lane["filter_tf"]), str(lane["family"]), p, str(lane["mode"]))
            except Exception as exc:
                skipped.append({**lane, "exit_profile": profile_name, "reason": f"eval_error:{type(exc).__name__}"})
                continue
            rows.append(build_row(res, lane, p))

    df = pd.DataFrame(rows)
    if df.empty:
        raise SystemExit("stage243 no rows evaluated")
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

    by_cluster: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rec in df.to_dict(orient="records"):
        by_cluster[str(rec["cluster"])].append(rec)
    cluster_best: list[dict[str, Any]] = []
    for cluster, items in by_cluster.items():
        items = sorted(items, key=lambda x: (x["recommendation_rank"], -x["composite_score"], -x["recent_pf"], -x["wf_pf"]))
        best = items[0]
        cluster_best.append({
            "cluster": cluster,
            "symbol": best["symbol"],
            "lane": format_lane(best),
            "best_exit": best["exit_profile"],
            "recent_ret": best["recent_ret"],
            "recent_pf": best["recent_pf"],
            "wf_ret": best["wf_ret"],
            "wf_pf": best["wf_pf"],
            "recommendation": best["recommendation"],
        })
    cluster_best.sort(key=lambda x: (REC_ORDER[x["recommendation"]], -x["recent_pf"], -x["wf_pf"], -x["recent_ret"]))

    all_csv = out_dir / "stage243_cluster_exit_family_matrix_all.csv"
    df.to_csv(all_csv, index=False)
    summary = {
        "goal": "continue matrix only; respect old-window clusters; widen family neighbors with lane-specific exit winners; live untouched",
        "candidate_lanes": len(LANES),
        "evaluated_rows": int(len(df)),
        "counts": {k: int(counts.get(k, 0)) for k in ["promote_primary", "keep_protective", "keep_secondary", "keep_research", "audit_only", "discard"]},
        "clusters": cluster_best,
        "best_by_symbol": by_symbol,
        "skipped": skipped,
    }
    (out_dir / "stage243_cluster_exit_family_matrix_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    lines: list[str] = []
    lines.append("[stage243_cluster_exit_family_matrix]")
    lines.append("goal=继续矩阵，不修 live；按旧窗口 cluster + stage242 胜出 exit 做 family 邻域扩测")
    lines.append("old_window_lock=ETH:s056/s060/s072 + short s068 ; BTC:s050/s058/s074/s082 + dual ; SOL:s046/s044/s076/s080")
    lines.append(f"candidate_lanes={len(LANES)}")
    lines.append(f"evaluated_rows={len(df)}")
    for key in ["promote_primary", "keep_protective", "keep_secondary", "keep_research", "audit_only", "discard"]:
        lines.append(f"{key}_total={int(counts.get(key, 0))}")
    if skipped:
        lines.append(f"skipped_total={len(skipped)}")
    lines.append("ranking=6年只作软约束；主排序继续看近2年 + WF；这轮重点看 cluster 内 family 是否在 lane-specific exit 下得到抬升")
    lines.append("")
    lines.append("[best_by_cluster]")
    for row in cluster_best:
        lines.append(
            f"- {row['cluster']} | {row['symbol']} | lane={row['lane']} | exit={row['best_exit']} | recent={row['recent_ret']:.2f}%/PF{row['recent_pf']:.3f} | wf={row['wf_ret']:.2f}%/PF{row['wf_pf']:.3f} | rec={row['recommendation']}"
        )
    lines.append("")
    lines.append("[best_by_symbol]")
    for symbol in ["btc", "bnb", "eth", "sol"]:
        info = by_symbol.get(symbol, {})
        if "best" not in info:
            lines.append(f"- {symbol} | none")
            continue
        best = info["best"]
        lines.append(
            f"- {symbol} | top={format_lane(best)} | cluster={best['cluster']} | exit={best['exit_profile']} | recent={best['recent_ret']:.2f}%/{best['recent_win']:.2f}%/PF{best['recent_pf']:.3f} | wf={best['wf_ret']:.2f}%/{best['wf_win']:.2f}%/PF{best['wf_pf']:.3f} | 6y={best['full_ret']:.2f}%/PF{best['full_pf']:.3f} | rec={best['recommendation']} | role={best['lane_role']}"
        )
    lines.append("")
    lines.append("[next_hint]")
    lines.append("- 若 ETH reclaim / short cluster 在 lane-specific exit 下继续抬升，就下一轮再做消息仓位层叠加；当前仍不碰 live。")
    lines.append("- 若 SOL fast cluster 继续稳定，就只把 exit helper 抽象到研究层模板，不直接改 runtime。")
    lines.append("- 若 BNB 共识 family 邻域仍弱，就继续保 bb_meanrev 为主，其它只留 reserve/research。")
    lines.append("- 若 BTC old cluster 仍跑不出近2年/WF，就继续保路但冻结为 audit/reserve。")
    (out_dir / "stage243_cluster_exit_family_matrix_latest.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage243 old-window cluster + exit family matrix")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()
    run(Path(args.project_dir).expanduser().resolve())


if __name__ == "__main__":
    main()
