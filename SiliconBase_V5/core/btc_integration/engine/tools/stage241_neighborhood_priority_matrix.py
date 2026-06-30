from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tools.stage230_expanded_combo_matrix as s230
import tools.stage231_seeded_confirmation_matrix as s231

REC_ORDER = {
    "promote_primary": 0,
    "keep_protective": 1,
    "keep_secondary": 2,
    "keep_research": 3,
    "btc_split_issue": 4,
    "discard": 5,
}

PLAN: dict[str, dict[str, Any]] = {
    "btc": {
        "why": "BTC 这轮先不升线，只做 split audit；stage240 的 recent/WF=0 先当研究口径异常处理。",
    },
    "bnb": {
        "why": "BNB 继续保护 current seed，不急着换家族；先把 5m/15m 邻域复核清楚。",
    },
    "eth": {
        "why": "ETH 这轮明显偏离旧 slow seed，要同时复核 30m/1h 新快线和 1h/4h 长向慢线。",
    },
    "sol": {
        "why": "SOL 当前出现双峰：5m/15m 高频与 1h/4h 长向结构都强，先同时做邻域矩阵。",
    },
}

CANDIDATES: list[dict[str, Any]] = [
    # BTC audit only
    {"symbol": "btc", "entry_tf": "5m", "filter_tf": "15m", "family": "bb_meanrev", "param_id": "p4", "mode": "short_only", "role": "audit"},
    {"symbol": "btc", "entry_tf": "5m", "filter_tf": "15m", "family": "bb_meanrev", "param_id": "p3", "mode": "short_only", "role": "audit"},
    {"symbol": "btc", "entry_tf": "5m", "filter_tf": "15m", "family": "bb_meanrev", "param_id": "p4", "mode": "dual", "role": "audit"},
    {"symbol": "btc", "entry_tf": "1h", "filter_tf": "4h", "family": "bb_meanrev", "param_id": "p2", "mode": "short_only", "role": "audit"},
    # BNB protective neighborhood
    {"symbol": "bnb", "entry_tf": "5m", "filter_tf": "15m", "family": "bb_meanrev", "param_id": "p1", "mode": "dual", "role": "protective"},
    {"symbol": "bnb", "entry_tf": "5m", "filter_tf": "15m", "family": "bb_meanrev", "param_id": "p2", "mode": "dual", "role": "protective"},
    {"symbol": "bnb", "entry_tf": "5m", "filter_tf": "15m", "family": "bb_meanrev", "param_id": "p3", "mode": "dual", "role": "protective"},
    {"symbol": "bnb", "entry_tf": "5m", "filter_tf": "15m", "family": "bb_meanrev", "param_id": "p2", "mode": "long_only", "role": "protective"},
    {"symbol": "bnb", "entry_tf": "5m", "filter_tf": "15m", "family": "bb_meanrev", "param_id": "p2", "mode": "short_only", "role": "protective"},
    {"symbol": "bnb", "entry_tf": "30m", "filter_tf": "1h", "family": "bb_meanrev", "param_id": "p1", "mode": "dual", "role": "control"},
    # ETH neighborhood
    {"symbol": "eth", "entry_tf": "30m", "filter_tf": "1h", "family": "bb_meanrev", "param_id": "p1", "mode": "dual", "role": "primary"},
    {"symbol": "eth", "entry_tf": "30m", "filter_tf": "1h", "family": "bb_meanrev", "param_id": "p2", "mode": "dual", "role": "neighbor"},
    {"symbol": "eth", "entry_tf": "30m", "filter_tf": "1h", "family": "bb_meanrev", "param_id": "p1", "mode": "long_only", "role": "neighbor"},
    {"symbol": "eth", "entry_tf": "30m", "filter_tf": "1h", "family": "bb_meanrev", "param_id": "p2", "mode": "long_only", "role": "neighbor"},
    {"symbol": "eth", "entry_tf": "1h", "filter_tf": "4h", "family": "bb_meanrev", "param_id": "p2", "mode": "dual", "role": "neighbor"},
    {"symbol": "eth", "entry_tf": "1h", "filter_tf": "4h", "family": "bb_meanrev", "param_id": "p3", "mode": "dual", "role": "protective"},
    {"symbol": "eth", "entry_tf": "1h", "filter_tf": "4h", "family": "bb_meanrev", "param_id": "p3", "mode": "long_only", "role": "neighbor"},
    {"symbol": "eth", "entry_tf": "1h", "filter_tf": "4h", "family": "bb_meanrev", "param_id": "p4", "mode": "long_only", "role": "neighbor"},
    {"symbol": "eth", "entry_tf": "1h", "filter_tf": "4h", "family": "sweep_reclaim", "param_id": "p3", "mode": "long_only", "role": "primary"},
    {"symbol": "eth", "entry_tf": "1h", "filter_tf": "4h", "family": "sweep_reclaim", "param_id": "p4", "mode": "long_only", "role": "primary"},
    {"symbol": "eth", "entry_tf": "30m", "filter_tf": "1h", "family": "retest_fail", "param_id": "p1", "mode": "short_only", "role": "reserve"},
    # SOL neighborhood
    {"symbol": "sol", "entry_tf": "5m", "filter_tf": "15m", "family": "bb_meanrev", "param_id": "p2", "mode": "dual", "role": "neighbor"},
    {"symbol": "sol", "entry_tf": "5m", "filter_tf": "15m", "family": "bb_meanrev", "param_id": "p3", "mode": "dual", "role": "neighbor"},
    {"symbol": "sol", "entry_tf": "5m", "filter_tf": "15m", "family": "bb_meanrev", "param_id": "p4", "mode": "dual", "role": "primary"},
    {"symbol": "sol", "entry_tf": "5m", "filter_tf": "15m", "family": "bb_meanrev", "param_id": "p2", "mode": "short_only", "role": "neighbor"},
    {"symbol": "sol", "entry_tf": "5m", "filter_tf": "15m", "family": "bb_meanrev", "param_id": "p3", "mode": "short_only", "role": "neighbor"},
    {"symbol": "sol", "entry_tf": "5m", "filter_tf": "15m", "family": "bb_meanrev", "param_id": "p4", "mode": "short_only", "role": "primary"},
    {"symbol": "sol", "entry_tf": "1h", "filter_tf": "4h", "family": "bb_meanrev", "param_id": "p1", "mode": "long_only", "role": "primary"},
    {"symbol": "sol", "entry_tf": "1h", "filter_tf": "4h", "family": "bb_meanrev", "param_id": "p2", "mode": "long_only", "role": "neighbor"},
    {"symbol": "sol", "entry_tf": "1h", "filter_tf": "4h", "family": "sweep_reclaim", "param_id": "p2", "mode": "long_only", "role": "neighbor"},
    {"symbol": "sol", "entry_tf": "1h", "filter_tf": "4h", "family": "sweep_reclaim", "param_id": "p3", "mode": "long_only", "role": "primary"},
    {"symbol": "sol", "entry_tf": "1h", "filter_tf": "4h", "family": "sweep_reclaim", "param_id": "p4", "mode": "long_only", "role": "neighbor"},
    {"symbol": "sol", "entry_tf": "5m", "filter_tf": "15m", "family": "range_revert_grid", "param_id": "p2", "mode": "dual", "role": "reserve"},
]


def candidate_key(row: dict[str, Any]) -> tuple[str, str, str, str, str, str]:
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


def classify(row: dict[str, Any]) -> str:
    recent_trades = int(row.get("recent_trades", 0) or 0)
    wf_trades = int(row.get("wf_trades", 0) or 0)
    full_trades = int(row.get("full_trades", 0) or 0)
    recent_ret = float(row.get("recent_ret", 0.0))
    recent_pf = float(row.get("recent_pf", 0.0))
    recent_dd = float(row.get("recent_dd", 0.0))
    wf_ret = float(row.get("wf_ret", 0.0))
    wf_pf = float(row.get("wf_pf", 0.0))
    full_pf = float(row.get("full_pf", 0.0))
    symbol = str(row.get("symbol", ""))

    if symbol == "btc" and (recent_trades == 0 or wf_trades == 0):
        return "btc_split_issue"
    if recent_trades >= 10 and wf_trades >= 6 and full_trades >= 20:
        if recent_pf >= 1.35 and recent_ret > 0 and wf_pf >= 1.05 and wf_ret >= 0 and recent_dd >= -18:
            return "promote_primary"
        if recent_pf >= 1.20 and recent_ret > 0 and wf_pf >= 1.00 and wf_ret > -5 and recent_dd >= -22:
            return "keep_protective"
        if recent_pf >= 1.05 and recent_ret > 0 and wf_pf >= 0.95 and wf_ret > -10:
            return "keep_secondary"
    if recent_trades >= 6 and full_trades >= 15 and ((recent_pf >= 1.0 and recent_ret > 0) or (wf_pf >= 1.0 and wf_ret > 0) or full_pf >= 1.1):
        return "keep_research"
    return "discard"


def score(row: dict[str, Any]) -> float:
    recent_ret = float(row.get("recent_ret", 0.0))
    recent_pf = float(row.get("recent_pf", 0.0))
    recent_win = float(row.get("recent_win", 0.0))
    wf_ret = float(row.get("wf_ret", 0.0))
    wf_pf = float(row.get("wf_pf", 0.0))
    wf_win = float(row.get("wf_win", 0.0))
    full_ret = float(row.get("full_ret", 0.0))
    full_pf = float(row.get("full_pf", 0.0))
    recent_dd = float(row.get("recent_dd", 0.0))
    wf_dd = float(row.get("wf_dd", 0.0))
    sample_bonus = min(int(row.get("recent_trades", 0) or 0), 24) * 0.35 + min(int(row.get("wf_trades", 0) or 0), 18) * 0.25
    dd_penalty = max(0.0, -recent_dd - 10.0) * 0.45 + max(0.0, -wf_dd - 8.0) * 0.35
    score_val = (
        min(70.0, recent_ret) * 0.55
        + 16.0 * max(-1.0, recent_pf - 1.0)
        + min(45.0, wf_ret) * 0.35
        + 11.0 * max(-1.0, wf_pf - 1.0)
        + 0.10 * recent_win
        + 0.06 * wf_win
        + min(20.0, max(-20.0, full_ret)) * 0.05
        + 3.0 * max(-1.0, full_pf - 1.0)
        + sample_bonus
        - dd_penalty
    )
    if str(row.get("symbol", "")) == "btc" and (int(row.get("recent_trades", 0) or 0) == 0 or int(row.get("wf_trades", 0) or 0) == 0):
        score_val -= 25.0
    return score_val


def format_lane(row: dict[str, Any]) -> str:
    return f"{row['entry_tf']}/{row['filter_tf']} | {row['family']} | {row['param_id']} | {row['mode']}"


def load_stage240(project_dir: Path) -> pd.DataFrame:
    path = project_dir / "reports" / "research_raw" / "stage240_reopen_family_matrix_all.csv"
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def run(project_dir: Path) -> dict[str, Any]:
    out_dir = project_dir / "reports" / "research_raw"
    out_dir.mkdir(parents=True, exist_ok=True)
    stage240_df = load_stage240(project_dir)
    prev_lookup: dict[tuple[str, str, str, str, str, str], dict[str, Any]] = {}
    if not stage240_df.empty:
        prev_lookup = {candidate_key(rec): dict(rec) for rec in stage240_df.to_dict(orient="records")}

    lab = s230.ExpandedComboLab(project_dir, symbols=["btc", "bnb", "eth", "sol"])
    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for pick in CANDIDATES:
        symbol = str(pick["symbol"])
        entry_tf = str(pick["entry_tf"])
        filter_tf = str(pick["filter_tf"])
        family = str(pick["family"])
        param_id = str(pick["param_id"])
        mode = str(pick["mode"])
        if not maybe_has_raw(project_dir, symbol, entry_tf):
            skipped.append({**pick, "reason": "missing_5m_raw"})
            continue
        print(f"[stage241] eval={symbol}:{entry_tf}/{filter_tf}:{family}:{param_id}:{mode}", flush=True)
        params = dict(s231.PARAM_MAP[param_id])
        try:
            res = lab.evaluate(symbol, entry_tf, filter_tf, family, params, mode)
        except Exception as exc:
            skipped.append({**pick, "reason": f"eval_error:{type(exc).__name__}"})
            continue
        row = dict(res)
        prev = prev_lookup.get(candidate_key(row), {})
        row["role"] = str(pick.get("role", ""))
        row["focus_reason"] = PLAN[symbol]["why"]
        row["previous_stage240_recent_ret"] = float(prev.get("recent_ret", 0.0))
        row["previous_stage240_recent_pf"] = float(prev.get("recent_pf", 0.0))
        row["previous_stage240_wf_ret"] = float(prev.get("wf_ret", 0.0))
        row["previous_stage240_wf_pf"] = float(prev.get("wf_pf", 0.0))
        row["recommendation"] = classify(row)
        row["recommendation_rank"] = REC_ORDER[row["recommendation"]]
        row["composite_score"] = score(row)
        rows.append(row)

    df = pd.DataFrame(rows)
    if not df.empty:
        df.sort_values(
            ["recommendation_rank", "symbol", "composite_score", "recent_pf", "recent_ret", "wf_pf", "wf_ret"],
            ascending=[True, True, False, False, False, False, False],
            inplace=True,
        )
    all_csv = out_dir / "stage241_neighborhood_priority_matrix_all.csv"
    df.to_csv(all_csv, index=False)

    counts = Counter(df["recommendation"].tolist()) if not df.empty else Counter()
    best_by_symbol: dict[str, Any] = {}
    for symbol in ["btc", "bnb", "eth", "sol"]:
        sub = df[df["symbol"] == symbol].copy() if not df.empty else pd.DataFrame()
        if sub.empty:
            best_by_symbol[symbol] = {"status": "none"}
            continue
        sub.sort_values(["recommendation_rank", "composite_score", "recent_pf", "recent_ret", "wf_pf"], ascending=[True, False, False, False, False], inplace=True)
        best_by_symbol[symbol] = {"best": sub.iloc[0].to_dict(), "top5": sub.head(5).to_dict(orient="records")}

    lines: list[str] = []
    lines.append("[stage241_neighborhood_priority_matrix]")
    lines.append("goal=先继续矩阵，不修 live；围绕 stage240 结果只做邻域扩测，ETH/SOL 优先，BNB 保护复核，BTC 只做 split audit")
    lines.append(f"candidate_rows={len(CANDIDATES)}")
    lines.append(f"evaluated_rows={len(df)}")
    for key in ["promote_primary", "keep_protective", "keep_secondary", "keep_research", "btc_split_issue", "discard"]:
        lines.append(f"{key}_total={int(counts.get(key, 0))}")
    lines.append("ranking=6年继续只做软约束；先看近2年 PF/收益/样本，再看 WF PF/收益；ETH/SOL 若继续过线，下一轮直接接 stop/profitlock / 动态止损线矩阵")
    if skipped:
        lines.append(f"skipped_total={len(skipped)}")
    lines.append("")
    lines.append("[best_by_symbol]")
    for symbol in ["btc", "bnb", "eth", "sol"]:
        info = best_by_symbol.get(symbol, {})
        best = info.get("best") if isinstance(info, dict) else None
        if not best:
            lines.append(f"- {symbol} | none")
            continue
        lines.append(
            f"- {symbol} | top={format_lane(best)} | recent={best['recent_ret']:.2f}%/{best['recent_win']:.2f}%/PF{best['recent_pf']:.3f} | wf={best['wf_ret']:.2f}%/{best['wf_win']:.2f}%/PF{best['wf_pf']:.3f} | 6y={best['full_ret']:.2f}%/PF{best['full_pf']:.3f} | rec={best['recommendation']} | role={best['role']}"
        )
    lines.append("")
    lines.append("[next_hint]")
    lines.append("- 这轮还是只做 base matrix，不把消息/机构/交易所 overlay 叠回去。")
    lines.append("- 若 ETH 30m/1h 与 SOL 1h/4h / 5m/15m 继续同时过线，下一轮直接接 stop/profitlock / 动态止损线矩阵。")
    lines.append("- 若 BTC 仍是 btc_split_issue，就先冻结 BTC fast lane，不让它污染 live 方向判断。")
    latest_txt = out_dir / "stage241_neighborhood_priority_matrix_latest.txt"
    latest_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")

    summary = {
        "goal": "continue matrix only; no live fix yet",
        "candidate_rows": int(len(CANDIDATES)),
        "evaluated_rows": int(len(df)),
        "counts": {k: int(v) for k, v in counts.items()},
        "best_by_symbol": best_by_symbol,
        "skipped": skipped,
        "top_rows": df.head(25).to_dict(orient="records") if not df.empty else [],
    }
    summary_json = out_dir / "stage241_neighborhood_priority_matrix_summary.json"
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage241 neighborhood priority matrix")
    ap.add_argument("--project-dir", type=Path, default=Path("."))
    args = ap.parse_args()
    run(args.project_dir.resolve())


if __name__ == "__main__":
    main()
