from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tools.message_stack_backtest as msb
import tools.stage231_seeded_confirmation_matrix as s231
import tools.stage234_seeded_message_overlay_matrix as s234
import tools.stage235_seeded_multiview_risk_matrix as s235

SEEDS = [s for s in s231.SEED_LANES if s.get("role") == "engine"]
VARIANT_BY_NAME = {v["name"]: v for v in s234.OVERLAY_VARIANTS}

SEED_VIEW_PLAN: dict[str, dict[str, Any]] = {
    "btc_fast_short_engine": {
        "anchor": "hybrid_contrarian_wait_t015",
        "reserve": "institution_crowding_asym_t016",
        "note": "BTC 用反共识主视角，机构拥挤做 veto/确认",
    },
    "bnb_fast_dual_engine": {
        "anchor": "exchange_defensive_wait_t020",
        "reserve": "institution_crowding_asym_t016",
        "note": "BNB 用交易所防守主视角，机构拥挤做 veto/确认",
    },
    "eth_slow_dual_engine": {
        "anchor": "balanced_dual_perspective_t014",
        "reserve": "hybrid_contrarian_wait_t015",
        "note": "ETH 先保守，不强上多视角放大；以 no_overlay/平衡为主",
    },
    "sol_fast_dual_engine": {
        "anchor": "retail_momentum_filtered_t012",
        "reserve": "balanced_dual_perspective_t014",
        "note": "SOL 保留散户动量主视角，但平衡视角负责 veto/确认",
    },
}

RISK_POLICIES: list[dict[str, Any]] = [
    {
        "policy_name": "balanced_stop_profitlock",
        "stop_mult": 0.95,
        "trail_mult": 0.86,
        "arm_mult": 0.90,
        "hold_mult": 0.90,
        "lev_scale": 1.08,
        "label": "平衡止损/平衡锁盈",
    },
    {
        "policy_name": "strict_stop_profitlock",
        "stop_mult": 0.88,
        "trail_mult": 0.78,
        "arm_mult": 0.82,
        "hold_mult": 0.82,
        "lev_scale": 1.00,
        "label": "严格止损/快锁盈",
    },
    {
        "policy_name": "wick_guard_balanced",
        "stop_mult": 0.92,
        "trail_mult": 0.82,
        "arm_mult": 0.86,
        "hold_mult": 0.86,
        "lev_scale": 1.02,
        "label": "天地针 guard + 平衡锁盈",
    },
]

OVERLAY_MODES = ["no_overlay", "anchor_single", "reserve_veto", "consensus_only"]


def action_dir(action: str) -> int:
    a = str(action or "HOLD")
    if a == "WAIT":
        return -2
    if a.startswith("BOOST"):
        return 1
    if a.startswith("CUT"):
        return -1
    return 0


def _copy_with_scale(row: pd.Series, scale: float, action: str, mode_name: str, pair_name: str, pair_perspective: str, support: float, adverse: float, net: float) -> pd.Series:
    out = row.copy()
    base_ret = float(pd.to_numeric(row.get("ret", 0.0), errors="coerce"))
    base_lev = float(pd.to_numeric(row.get("lev", 0.0), errors="coerce") or 0.0)
    out["overlay_name"] = pair_name
    out["overlay_perspective"] = pair_perspective
    out["overlay_mode"] = mode_name
    out["msg_total_support"] = support
    out["msg_total_adverse"] = adverse
    out["msg_net_score"] = net
    out["msg_action"] = action
    out["msg_scale"] = float(scale)
    out["scaled_ret"] = max(-0.95, base_ret * float(scale))
    out["scaled_lev"] = base_lev * float(scale)
    return out


def apply_no_overlay(trades: pd.DataFrame, pair_name: str, pair_perspective: str) -> pd.DataFrame:
    rows = []
    for _, row in trades.iterrows():
        rows.append(_copy_with_scale(row, 1.0, "HOLD", "no_overlay", pair_name, pair_perspective, 0.0, 0.0, 0.0))
    return pd.DataFrame(rows)


def apply_reserve_veto(anchor_df: pd.DataFrame, reserve_df: pd.DataFrame, pair_name: str, pair_perspective: str) -> pd.DataFrame:
    rows = []
    for (_, ra), (_, rb) in zip(anchor_df.iterrows(), reserve_df.iterrows(), strict=False):
        aa = str(ra.get("msg_action", "HOLD"))
        ba = str(rb.get("msg_action", "HOLD"))
        da = action_dir(aa)
        db = action_dir(ba)
        scale_a = float(ra.get("msg_scale", 1.0))
        scale_b = float(rb.get("msg_scale", 1.0))
        support = max(float(ra.get("msg_total_support", 0.0)), float(rb.get("msg_total_support", 0.0)))
        adverse = max(float(ra.get("msg_total_adverse", 0.0)), float(rb.get("msg_total_adverse", 0.0)))
        net = float(ra.get("msg_net_score", 0.0)) + 0.5 * float(rb.get("msg_net_score", 0.0))

        if aa == "WAIT" or ba == "WAIT":
            action, scale = "WAIT", 0.0
        elif db == -1 and da == 1:
            # 主视角想冲，但保留视角明确反对 -> 先收掉一档
            action = "CUT_MID" if ba == "CUT_MID" else "CUT_SOFT"
            scale = min(scale_a, scale_b)
        elif db == -1 and da in (0, -1):
            action = ba if ba != "HOLD" else aa
            scale = min(scale_a, scale_b)
        else:
            action = aa
            scale = scale_a
        rows.append(_copy_with_scale(ra, scale, action, "reserve_veto", pair_name, pair_perspective, support, adverse, net))
    return pd.DataFrame(rows)


def apply_consensus_only(anchor_df: pd.DataFrame, reserve_df: pd.DataFrame, pair_name: str, pair_perspective: str) -> pd.DataFrame:
    rows = []
    for (_, ra), (_, rb) in zip(anchor_df.iterrows(), reserve_df.iterrows(), strict=False):
        aa = str(ra.get("msg_action", "HOLD"))
        ba = str(rb.get("msg_action", "HOLD"))
        da = action_dir(aa)
        db = action_dir(ba)
        scale_a = float(ra.get("msg_scale", 1.0))
        scale_b = float(rb.get("msg_scale", 1.0))
        support = 0.5 * (float(ra.get("msg_total_support", 0.0)) + float(rb.get("msg_total_support", 0.0)))
        adverse = 0.5 * (float(ra.get("msg_total_adverse", 0.0)) + float(rb.get("msg_total_adverse", 0.0)))
        net = 0.5 * (float(ra.get("msg_net_score", 0.0)) + float(rb.get("msg_net_score", 0.0)))

        if aa == "WAIT" or ba == "WAIT":
            action, scale = "WAIT", 0.0
        elif da == 1 and db == 1:
            scale = min(1.18, 0.5 * (scale_a + scale_b))
            action = "BOOST_MID" if (aa == "BOOST_MID" or ba == "BOOST_MID" or scale >= 1.15) else "BOOST_SOFT"
        elif da == -1 and db == -1:
            scale = min(scale_a, scale_b)
            action = "CUT_MID" if (aa == "CUT_MID" or ba == "CUT_MID") else "CUT_SOFT"
        elif {da, db} == {1, -1}:
            action, scale = "WAIT", 0.0
        elif (da, db) in [(1, 0), (0, 1)]:
            action, scale = "HOLD", 1.0
        elif (da, db) in [(-1, 0), (0, -1)]:
            action, scale = "CUT_SOFT", min(scale_a, scale_b)
        else:
            action, scale = "HOLD", 1.0
        rows.append(_copy_with_scale(ra, scale, action, "consensus_only", pair_name, pair_perspective, support, adverse, net))
    return pd.DataFrame(rows)


def apply_overlay_mode(mode_name: str, policy_trades: pd.DataFrame, windows: pd.DataFrame, anchor_variant: dict[str, Any], reserve_variant: dict[str, Any]) -> pd.DataFrame:
    pair_name = f"{anchor_variant['name']}__x__{reserve_variant['name']}"
    pair_perspective = f"{anchor_variant['perspective']}+{reserve_variant['perspective']}"
    if mode_name == "no_overlay":
        return apply_no_overlay(policy_trades, pair_name, pair_perspective)
    anchor_df = s234.apply_overlay(policy_trades, windows, anchor_variant)
    if mode_name == "anchor_single":
        anchor_df = anchor_df.copy()
        anchor_df["overlay_mode"] = mode_name
        return anchor_df
    reserve_df = s234.apply_overlay(policy_trades, windows, reserve_variant)
    if mode_name == "reserve_veto":
        return apply_reserve_veto(anchor_df, reserve_df, pair_name, pair_perspective)
    if mode_name == "consensus_only":
        return apply_consensus_only(anchor_df, reserve_df, pair_name, pair_perspective)
    raise ValueError(f"unknown mode: {mode_name}")


def run(project_dir: Path) -> dict[str, Any]:
    out_dir = project_dir / "reports" / "research_raw"
    out_dir.mkdir(parents=True, exist_ok=True)
    lab = s231.SeededConfirmationMatrix(project_dir)
    hist = msb._load_or_fetch_history(project_dir, refresh=False)
    oi_df = msb._parse_oi_df(hist.get("oi_agg_btc_1d", {}))
    lsr_df = msb._parse_lsr_df(hist.get("lsr_btcusdt_binance_4h", {}))
    taker_df = msb._parse_taker_df(hist.get("taker_btcusdt_binance_4h", {}))
    windows = msb._load_event_windows(
        project_dir,
        pd.Timestamp("2019-01-01", tz="UTC"),
        pd.Timestamp.now(tz="UTC") + pd.Timedelta(days=7),
        include_all_modes=True,
    )

    rows: list[dict[str, Any]] = []
    base_by_seed: dict[str, dict[str, float]] = {}

    for seed in SEEDS:
        sid = str(seed["seed_id"])
        if seed["entry_tf"] == "5m" and not (project_dir / "data" / "raw" / f"{seed['symbol']}_5m.csv").exists():
            continue
        base_p = dict(s231.PARAM_MAP[seed["param_id"]])
        df = lab.get_merged(seed["symbol"], seed["entry_tf"], seed["filter_tf"])
        long_sig, short_sig = lab.family_signals(df, seed["family"], base_p)
        base_trades_raw, _ = lab.backtest(df, long_sig, short_sig, base_p, seed["mode"])
        if base_trades_raw.empty:
            continue
        base_trades = s235.attach_trade_features(base_trades_raw, seed, oi_df, lsr_df, taker_df)
        base_metrics = s234.slice_metrics(base_trades)
        base_by_seed[sid] = base_metrics

        plan = SEED_VIEW_PLAN[sid]
        anchor_variant = VARIANT_BY_NAME[plan["anchor"]]
        reserve_variant = VARIANT_BY_NAME[plan["reserve"]]

        for overlay_mode in OVERLAY_MODES:
            for policy in RISK_POLICIES:
                rp = s235.adjusted_params(base_p, policy)
                policy_trades_raw, _ = s235.backtest_with_policy(
                    df, long_sig, short_sig, rp, seed["mode"], float(policy["lev_scale"])
                )
                if policy_trades_raw.empty:
                    continue
                policy_trades = s235.attach_trade_features(policy_trades_raw, seed, oi_df, lsr_df, taker_df)
                scored = apply_overlay_mode(overlay_mode, policy_trades, windows, anchor_variant, reserve_variant)
                if scored.empty:
                    continue
                metrics = s234.slice_metrics(scored)
                recent_start = pd.to_datetime(scored["entry_time_utc"], utc=True).max() - pd.DateOffset(years=2)
                counts_recent = scored[scored["entry_time_utc"] >= recent_start]["msg_action"].value_counts()
                counts_all = scored["msg_action"].value_counts()

                row: dict[str, Any] = {
                    "seed_id": sid,
                    "symbol": seed["symbol"],
                    "entry_tf": seed["entry_tf"],
                    "filter_tf": seed["filter_tf"],
                    "family": seed["family"],
                    "param_id": seed["param_id"],
                    "mode": seed["mode"],
                    "anchor_overlay": anchor_variant["name"],
                    "reserve_overlay": reserve_variant["name"],
                    "overlay_mode": overlay_mode,
                    "overlay_note": plan["note"],
                    "policy_name": policy["policy_name"],
                    "policy_label": policy["label"],
                    "stop_mult": policy["stop_mult"],
                    "trail_mult": policy["trail_mult"],
                    "arm_mult": policy["arm_mult"],
                    "hold_mult": policy["hold_mult"],
                    "lev_scale": policy["lev_scale"],
                    "full_boost_soft": int(counts_all.get("BOOST_SOFT", 0)),
                    "full_boost_mid": int(counts_all.get("BOOST_MID", 0)),
                    "full_cut_soft": int(counts_all.get("CUT_SOFT", 0)),
                    "full_cut_mid": int(counts_all.get("CUT_MID", 0)),
                    "full_wait": int(counts_all.get("WAIT", 0)),
                    "recent_boost_soft": int(counts_recent.get("BOOST_SOFT", 0)),
                    "recent_boost_mid": int(counts_recent.get("BOOST_MID", 0)),
                    "recent_cut_soft": int(counts_recent.get("CUT_SOFT", 0)),
                    "recent_cut_mid": int(counts_recent.get("CUT_MID", 0)),
                    "recent_wait": int(counts_recent.get("WAIT", 0)),
                    **metrics,
                    "base_full_ret": base_metrics["full_ret"],
                    "base_full_pf": base_metrics["full_pf"],
                    "base_full_dd": base_metrics["full_dd"],
                    "base_recent_ret": base_metrics["recent_ret"],
                    "base_recent_pf": base_metrics["recent_pf"],
                    "base_recent_dd": base_metrics["recent_dd"],
                    "base_recent_win": base_metrics["recent_win"],
                    "base_recent_trades": base_metrics["recent_trades"],
                    "base_wf_ret": base_metrics["wf_ret"],
                    "base_wf_pf": base_metrics["wf_pf"],
                    "base_wf_dd": base_metrics["wf_dd"],
                    "base_wf_trades": base_metrics["wf_trades"],
                }
                row["recent_keep_ratio"] = float(metrics["recent_trades"] / max(1, base_metrics["recent_trades"]))
                row["wait_ratio_recent"] = float(row["recent_wait"] / max(1, base_metrics["recent_trades"]))
                row["pf_delta_recent"] = float(metrics["recent_pf"] - base_metrics["recent_pf"])
                row["ret_delta_recent"] = float(metrics["recent_ret"] - base_metrics["recent_ret"])
                row["win_delta_recent"] = float(metrics["recent_win"] - base_metrics["recent_win"])
                row["dd_improve_recent"] = float(base_metrics["recent_dd"] - metrics["recent_dd"])
                row["pf_delta_wf"] = float(metrics["wf_pf"] - base_metrics["wf_pf"])
                row["dd_improve_wf"] = float(base_metrics["wf_dd"] - metrics["wf_dd"])
                row["recommendation"] = s235.classify(base_metrics, row)
                row["recommendation_rank"] = s235.rec_rank(row["recommendation"])
                row["composite_score"] = s235.composite_score(base_metrics, row)
                rows.append(row)

    df = pd.DataFrame(rows)
    if not df.empty:
        df.sort_values(
            ["seed_id", "recommendation_rank", "composite_score", "recent_pf", "wf_pf"],
            ascending=[True, True, False, False, False],
            inplace=True,
        )
    (out_dir / "stage236_multiview_conflict_matrix_all.csv").write_text(df.to_csv(index=False), encoding="utf-8")

    best_by_seed: dict[str, Any] = {}
    lines: list[str] = []
    lines.append("[stage236_multiview_conflict_matrix]")
    lines.append("goal=不再简单平均散户/机构/交易所视角；改测 主视角单独、保留视角 veto、只在共识时加码，并把 天地针 guard 放进风险层")
    lines.append(f"tested_rows={len(df)}")
    for key in ["promote_policy_primary", "promote_policy_protective", "keep_policy_secondary", "keep_policy_research"]:
        lines.append(f"{key}_total={int((df['recommendation'] == key).sum()) if not df.empty else 0}")
    lines.append("ranking=先看近2年 PF/收益/保留比，再看 WF PF；6年继续只做软约束；这轮重点判断 多视角应不应该做 veto/共识，而不是简单 paired_blend")
    lines.append("")
    lines.append("[best_by_seed]")
    for seed in SEEDS:
        sid = seed["seed_id"]
        sub = df[df["seed_id"] == sid].copy()
        if sub.empty:
            lines.append(f"- {sid} | none")
            best_by_seed[sid] = {"status": "skip", "reason": "no_rows"}
            continue
        sub.sort_values(["recommendation_rank", "composite_score", "recent_pf", "wf_pf"], ascending=[True, False, False, False], inplace=True)
        best = sub.iloc[0].to_dict()
        base = base_by_seed[sid]
        lines.append(
            f"- {sid} | base={seed['entry_tf']}/{seed['filter_tf']} {seed['family']} {seed['param_id']} {seed['mode']} | recent={base['recent_ret']:.2f}%/{base['recent_win']:.2f}%/PF{base['recent_pf']:.3f} | wf={base['wf_ret']:.2f}%/PF{base['wf_pf']:.3f}"
        )
        lines.append(
            f"  -> top={best['recommendation']} {best['overlay_mode']} + {best['policy_name']} | anchor={best['anchor_overlay']} reserve={best['reserve_overlay']} | recent={best['recent_ret']:.2f}%/{best['recent_win']:.2f}%/PF{best['recent_pf']:.3f} | wf={best['wf_ret']:.2f}%/PF{best['wf_pf']:.3f} | keep={best['recent_keep_ratio']:.2f} | wait={best['wait_ratio_recent']:.2f}"
        )
        best_by_seed[sid] = {"seed_meta": seed, "base": base, "best_policy": best}
    lines.append("")
    lines.append("[conflict_hint]")
    lines.append("- reserve_veto = 主视角负责方向，第二视角只在明显反对时 CUT/WAIT。")
    lines.append("- consensus_only = 只有两种视角都支持同一方向才 BOOST；若一正一反，直接 WAIT。")
    lines.append("- no_overlay 也保留进矩阵，防止 ETH 这种其实不该硬上多视角的标的被误伤。")
    (out_dir / "stage236_multiview_conflict_matrix_latest.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    summary = {
        "goal": "multiview conflict-aware overlay matrix with veto/consensus modes",
        "tested_rows": int(len(df)),
        "best_by_seed": best_by_seed,
        "top_rows": df.sort_values(["recommendation_rank", "composite_score"], ascending=[True, False]).head(12).to_dict(orient="records") if not df.empty else [],
    }
    (out_dir / "stage236_multiview_conflict_matrix_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage236 multiview conflict matrix")
    ap.add_argument("--project-dir", type=Path, default=Path("."))
    args = ap.parse_args()
    run(args.project_dir.resolve())


if __name__ == "__main__":
    main()
