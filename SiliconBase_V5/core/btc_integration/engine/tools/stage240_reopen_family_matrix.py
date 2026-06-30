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

CURRENT_SEEDS = {
    (str(seed["symbol"]), str(seed["entry_tf"]), str(seed["filter_tf"]), str(seed["family"]), str(seed["param_id"]), str(seed["mode"])): str(seed["seed_id"])
    for seed in s231.SEED_LANES
    if seed.get("role") == "engine"
}

PLAN = {
    "btc": {
        "allow_pairings": {("5m", "15m"), ("1h", "4h")},
        "allow_families": {"bb_meanrev", "sweep_reclaim", "retest_fail"},
        "allow_params": {"p2", "p3", "p4"},
        "allow_modes": {"short_only", "dual"},
        "top_n": 3,
        "why": "BTC 继续保短空主线，同时保一条双向 research。",
    },
    "bnb": {
        "allow_pairings": {("5m", "15m"), ("30m", "1h")},
        "allow_families": {"bb_meanrev", "range_revert_grid", "sweep_reclaim"},
        "allow_params": {"p1", "p2", "p3"},
        "allow_modes": {"dual", "long_only", "short_only"},
        "top_n": 3,
        "why": "BNB 继续提频，不只押一条 dual。",
    },
    "eth": {
        "allow_pairings": {("30m", "1h"), ("1h", "4h")},
        "allow_families": {"bb_meanrev", "reclaim_atr_rsi", "sweep_reclaim", "retest_fail", "ma_macd_bb"},
        "allow_params": {"p1", "p2", "p3", "p4"},
        "allow_modes": {"dual", "long_only", "short_only"},
        "top_n": 4,
        "why": "ETH 重新开宽 family/参数/方向，但先限定在两组更靠谱周期。",
    },
    "sol": {
        "allow_pairings": {("5m", "15m"), ("1h", "4h")},
        "allow_families": {"bb_meanrev", "sweep_reclaim", "retest_fail", "range_revert_grid", "squeeze_pullback"},
        "allow_params": {"p1", "p2", "p3", "p4"},
        "allow_modes": {"dual", "long_only", "short_only"},
        "top_n": 4,
        "why": "SOL 不因一轮冲突测试就锁死，先重开高频 + 稳线两个框架。",
    },
}

FALLBACK_CANDIDATES = [
    ("btc", "5m", "15m", "bb_meanrev", "p4", "short_only"),
    ("btc", "5m", "15m", "sweep_reclaim", "p3", "short_only"),
    ("bnb", "5m", "15m", "bb_meanrev", "p2", "dual"),
    ("bnb", "5m", "15m", "range_revert_grid", "p2", "dual"),
    ("eth", "1h", "4h", "bb_meanrev", "p3", "dual"),
    ("eth", "30m", "1h", "reclaim_atr_rsi", "p2", "dual"),
    ("eth", "30m", "1h", "retest_fail", "p2", "short_only"),
    ("sol", "5m", "15m", "bb_meanrev", "p4", "dual"),
    ("sol", "5m", "15m", "range_revert_grid", "p2", "dual"),
    ("sol", "1h", "4h", "retest_fail", "p2", "long_only"),
]

REC_ORDER = {
    "promote_primary": 0,
    "keep_protective": 1,
    "keep_secondary": 2,
    "keep_research": 3,
    "discard": 4,
}


def candidate_key(row: dict[str, Any]) -> tuple[str, str, str, str, str, str]:
    return (
        str(row["symbol"]),
        str(row["entry_tf"]),
        str(row["filter_tf"]),
        str(row["family"]),
        str(row["param_id"]),
        str(row["mode"]),
    )



def classify(row: dict[str, Any]) -> str:
    recent_pf = float(row.get("recent_pf", 0.0))
    recent_ret = float(row.get("recent_ret", 0.0))
    recent_dd = float(row.get("recent_dd", 0.0))
    recent_trades = int(row.get("recent_trades", 0) or 0)
    wf_pf = float(row.get("wf_pf", 0.0))
    wf_ret = float(row.get("wf_ret", 0.0))
    wf_trades = int(row.get("wf_trades", 0) or 0)
    full_trades = int(row.get("full_trades", 0) or 0)
    full_pf = float(row.get("full_pf", 0.0))

    if recent_trades >= 8 and wf_trades >= 5 and full_trades >= 20:
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
    return (
        min(50.0, recent_ret) * 0.55
        + 16.0 * max(-1.0, recent_pf - 1.0)
        + min(35.0, wf_ret) * 0.35
        + 11.0 * max(-1.0, wf_pf - 1.0)
        + 0.10 * recent_win
        + 0.06 * wf_win
        + min(20.0, max(-20.0, full_ret)) * 0.05
        + 3.0 * max(-1.0, full_pf - 1.0)
        + sample_bonus
        - dd_penalty
    )



def format_lane(row: dict[str, Any]) -> str:
    return f"{row['entry_tf']}/{row['filter_tf']} | {row['family']} | {row['param_id']} | {row['mode']}"



def load_stage230_candidates(project_dir: Path) -> pd.DataFrame:
    path = project_dir / "reports" / "research_raw" / "stage230_expanded_combo_matrix_all.csv"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)



def shortlist_from_stage230(stage230_df: pd.DataFrame) -> list[dict[str, Any]]:
    picks: list[dict[str, Any]] = []
    if stage230_df.empty:
        return picks
    for symbol, plan in PLAN.items():
        sub = stage230_df[stage230_df["symbol"] == symbol].copy()
        if sub.empty:
            continue
        sub = sub[
            sub.apply(
                lambda r, plan=plan: (str(r["entry_tf"]), str(r["filter_tf"])) in plan["allow_pairings"]
                and str(r["family"]) in plan["allow_families"]
                and str(r["param_id"]) in plan["allow_params"]
                and str(r["mode"]) in plan["allow_modes"],
                axis=1,
            )
        ].copy()
        if sub.empty:
            continue
        sub.sort_values(["recent_pf", "recent_ret", "wf_pf", "wf_ret", "full_pf"], ascending=[False, False, False, False, False], inplace=True)
        keep = sub.head(int(plan["top_n"])).copy()
        for _, row in keep.iterrows():
            picks.append({
                "symbol": str(row["symbol"]),
                "entry_tf": str(row["entry_tf"]),
                "filter_tf": str(row["filter_tf"]),
                "family": str(row["family"]),
                "param_id": str(row["param_id"]),
                "mode": str(row["mode"]),
                "source": "stage230_shortlist",
                "source_recent_ret": float(row.get("recent_ret", 0.0)),
                "source_recent_pf": float(row.get("recent_pf", 0.0)),
                "source_wf_ret": float(row.get("wf_ret", 0.0)),
                "source_wf_pf": float(row.get("wf_pf", 0.0)),
            })
    return picks



def add_seed_and_fallbacks(picks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = {candidate_key(x) for x in picks}
    for key, seed_id in CURRENT_SEEDS.items():
        if key not in seen:
            symbol, entry_tf, filter_tf, family, param_id, mode = key
            picks.append({
                "symbol": symbol,
                "entry_tf": entry_tf,
                "filter_tf": filter_tf,
                "family": family,
                "param_id": param_id,
                "mode": mode,
                "source": f"seed:{seed_id}",
            })
            seen.add(key)
    for symbol, entry_tf, filter_tf, family, param_id, mode in FALLBACK_CANDIDATES:
        key = (symbol, entry_tf, filter_tf, family, param_id, mode)
        if key not in seen:
            picks.append({
                "symbol": symbol,
                "entry_tf": entry_tf,
                "filter_tf": filter_tf,
                "family": family,
                "param_id": param_id,
                "mode": mode,
                "source": "fallback",
            })
            seen.add(key)
    return picks



def maybe_has_raw(project_dir: Path, symbol: str, entry_tf: str) -> bool:
    if entry_tf != "5m":
        return True
    return (project_dir / "data" / "raw" / f"{symbol}_5m.csv").exists()



def run(project_dir: Path) -> dict[str, Any]:
    out_dir = project_dir / "reports" / "research_raw"
    out_dir.mkdir(parents=True, exist_ok=True)
    stage230_df = load_stage230_candidates(project_dir)
    picks = add_seed_and_fallbacks(shortlist_from_stage230(stage230_df))

    lab = s230.ExpandedComboLab(project_dir, symbols=list(PLAN.keys()))
    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for pick in picks:
        symbol = str(pick["symbol"])
        entry_tf = str(pick["entry_tf"])
        filter_tf = str(pick["filter_tf"])
        family = str(pick["family"])
        param_id = str(pick["param_id"])
        mode = str(pick["mode"])
        if not maybe_has_raw(project_dir, symbol, entry_tf):
            skipped.append({**pick, "reason": "missing_5m_raw"})
            continue
        print(f"[stage240] refresh={symbol}:{entry_tf}/{filter_tf}:{family}:{param_id}:{mode}", flush=True)
        p = dict(s231.PARAM_MAP[param_id])
        try:
            res = lab.evaluate(symbol, entry_tf, filter_tf, family, p, mode)
        except Exception as exc:
            skipped.append({**pick, "reason": f"eval_error:{type(exc).__name__}"})
            continue
        row = dict(res)
        row["source"] = str(pick.get("source", ""))
        row["seed_id_match"] = CURRENT_SEEDS.get(candidate_key(row), "")
        row["focus_reason"] = PLAN[symbol]["why"]
        row["recommendation"] = classify(row)
        row["recommendation_rank"] = REC_ORDER[row["recommendation"]]
        row["composite_score"] = score(row)
        row["stage230_recent_ret"] = float(pick.get("source_recent_ret", 0.0))
        row["stage230_recent_pf"] = float(pick.get("source_recent_pf", 0.0))
        row["stage230_wf_ret"] = float(pick.get("source_wf_ret", 0.0))
        row["stage230_wf_pf"] = float(pick.get("source_wf_pf", 0.0))
        rows.append(row)

    df = pd.DataFrame(rows)
    if not df.empty:
        df.sort_values(
            ["recommendation_rank", "symbol", "composite_score", "recent_pf", "recent_ret", "wf_pf", "wf_ret"],
            ascending=[True, True, False, False, False, False, False],
            inplace=True,
        )
    all_csv = out_dir / "stage240_reopen_family_matrix_all.csv"
    df.to_csv(all_csv, index=False)

    counts = Counter(df["recommendation"].tolist()) if not df.empty else Counter()
    best_by_symbol: dict[str, Any] = {}
    for symbol in ["btc", "bnb", "eth", "sol"]:
        sub = df[df["symbol"] == symbol].copy() if not df.empty else pd.DataFrame()
        if sub.empty:
            best_by_symbol[symbol] = {"status": "none"}
            continue
        sub.sort_values(["recommendation_rank", "composite_score", "recent_pf", "recent_ret", "wf_pf"], ascending=[True, False, False, False, False], inplace=True)
        best_by_symbol[symbol] = {
            "best": sub.iloc[0].to_dict(),
            "top5": sub.head(5).to_dict(orient="records"),
        }

    lines: list[str] = []
    lines.append("[stage240_reopen_family_matrix]")
    lines.append("goal=先继续矩阵，不动 live；直接复用 stage230 结果做 shortlist，只刷新当前最该复核的 lanes，避免再全图乱扫")
    lines.append(f"shortlisted_candidates={len(picks)}")
    lines.append(f"refreshed_rows={len(df)}")
    lines.append(f"promote_primary_total={int(counts.get('promote_primary', 0))}")
    lines.append(f"keep_protective_total={int(counts.get('keep_protective', 0))}")
    lines.append(f"keep_secondary_total={int(counts.get('keep_secondary', 0))}")
    lines.append(f"keep_research_total={int(counts.get('keep_research', 0))}")
    lines.append(f"discard_total={int(counts.get('discard', 0))}")
    lines.append("ranking=6年继续只做软约束；主排序先看近2年 PF/收益/样本，再看 WF PF/收益；先复核 current lanes，再决定下一轮是否继续开宽")
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
            f"- {symbol} | top={format_lane(best)} | recent={best['recent_ret']:.2f}%/{best['recent_win']:.2f}%/PF{best['recent_pf']:.3f} | wf={best['wf_ret']:.2f}%/{best['wf_win']:.2f}%/PF{best['wf_pf']:.3f} | 6y={best['full_ret']:.2f}%/PF{best['full_pf']:.3f} | rec={best['recommendation']} | source={best['source']}"
        )
        if best.get("seed_id_match"):
            lines.append(f"  seed_match={best['seed_id_match']}")
    lines.append("")
    lines.append("[next_hint]")
    lines.append("- 这一轮先做 refreshed shortlist matrix，不先把消息/机构/交易所 overlay 再叠回去。")
    lines.append("- 若 ETH / SOL 的 top 已偏离 current seed，就下一轮只围它们做邻域矩阵；旧路降级 reserve/research，不删除。")
    lines.append("- 若 BTC / BNB 仍稳在 current seed 附近，下一轮才接 stop/profitlock/overlay 二次矩阵。")
    latest_txt = out_dir / "stage240_reopen_family_matrix_latest.txt"
    latest_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")

    summary = {
        "goal": "refresh shortlist matrix before any new live patch",
        "shortlisted_candidates": int(len(picks)),
        "refreshed_rows": int(len(df)),
        "counts": {k: int(v) for k, v in counts.items()},
        "best_by_symbol": best_by_symbol,
        "skipped": skipped,
        "top_rows": df.head(20).to_dict(orient="records") if not df.empty else [],
    }
    summary_json = out_dir / "stage240_reopen_family_matrix_summary.json"
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return summary



def main() -> None:
    ap = argparse.ArgumentParser(description="Stage240 reopen family matrix")
    ap.add_argument("--project-dir", type=Path, default=Path("."))
    args = ap.parse_args()
    run(args.project_dir.resolve())


if __name__ == "__main__":
    main()
