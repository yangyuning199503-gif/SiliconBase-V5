from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tools.message_stack_backtest as msb
import tools.stage231_seeded_confirmation_matrix as s231
import tools.stage234_seeded_message_overlay_matrix as s234

SEEDS = [s for s in s231.SEED_LANES if s.get("role") == "engine"]
VARIANT_BY_NAME = {v["name"]: v for v in s234.OVERLAY_VARIANTS}

SEED_OVERLAY_PLAN: dict[str, dict[str, Any]] = {
    "btc_fast_short_engine": {
        "anchor": "hybrid_contrarian_wait_t015",
        "reserve": "institution_crowding_asym_t016",
        "note": "BTC 更偏反共识 + 拥挤/清算反身性",
    },
    "bnb_fast_dual_engine": {
        "anchor": "exchange_defensive_wait_t020",
        "reserve": "institution_crowding_asym_t016",
        "note": "BNB 更偏交易所视角先防守，再看拥挤",
    },
    "eth_slow_dual_engine": {
        "anchor": "hybrid_contrarian_wait_t015",
        "reserve": "balanced_dual_perspective_t014",
        "note": "ETH 仍偏慢线，用折中/反共识，不硬追催化",
    },
    "sol_fast_dual_engine": {
        "anchor": "retail_momentum_filtered_t012",
        "reserve": "balanced_dual_perspective_t014",
        "note": "SOL 允许更强催化追随，但保留平衡兜底",
    },
}

RISK_POLICIES: list[dict[str, Any]] = [
    {"policy_name": "strict_stop_profitlock", "stop_mult": 0.88, "trail_mult": 0.78, "arm_mult": 0.82, "hold_mult": 0.82, "lev_scale": 1.00, "label": "严格止损/快锁盈"},
    {"policy_name": "balanced_stop_profitlock", "stop_mult": 0.95, "trail_mult": 0.86, "arm_mult": 0.90, "hold_mult": 0.90, "lev_scale": 1.08, "label": "平衡止损/平衡锁盈"},
    {"policy_name": "aggressive_profitlock_research", "stop_mult": 1.02, "trail_mult": 0.74, "arm_mult": 0.78, "hold_mult": 0.88, "lev_scale": 1.16, "label": "激进研究层锁盈"},
    {"policy_name": "extreme_research_not_runtime", "stop_mult": 0.94, "trail_mult": 0.68, "arm_mult": 0.72, "hold_mult": 0.82, "lev_scale": 1.24, "label": "更激进研究层，不上 runtime"},
]


def adjusted_params(base_p: dict[str, float], policy: dict[str, Any]) -> dict[str, float]:
    p = dict(base_p)
    p["stop_atr"] = float(base_p["stop_atr"]) * float(policy["stop_mult"])
    p["trail_atr"] = float(base_p["trail_atr"]) * float(policy["trail_mult"])
    p["arm_rr"] = float(base_p["arm_rr"]) * float(policy["arm_mult"])
    p["max_hold"] = max(10, int(round(float(base_p["max_hold"]) * float(policy["hold_mult"]))))
    return p


def backtest_with_policy(
    df: pd.DataFrame,
    long_sig: np.ndarray,
    short_sig: np.ndarray,
    p: dict[str, float],
    mode: str,
    lev_scale: float,
    fee_bps: float = 4.0,
    cooldown_bars: int = 4,
) -> tuple[pd.DataFrame, float]:
    arr = df[["open", "high", "low", "close", "atr", "adx", "f_adx"]].to_numpy()
    idx = df.index.to_numpy()
    fee = fee_bps / 10000.0
    pos = 0
    entry = 0.0
    stop = 0.0
    lev = 1.0
    hold = 0
    mfe = 0.0
    entry_time = None
    cooldown = 0
    eq = 1.0
    peak = 1.0
    maxdd = 0.0
    trades: list[tuple[object, object, int, float, float, float, float, str, int]] = []

    if mode == "long_only":
        short_sig = np.zeros_like(short_sig, dtype=bool)
    elif mode == "short_only":
        long_sig = np.zeros_like(long_sig, dtype=bool)

    for i in range(1, len(df) - 1):
        _o, h, low, c, atrv, adxv, fadxv = arr[i]
        nxt_open = arr[i + 1][0]
        if pos != 0:
            hold += 1
            pnl_unlev = pos * ((c - entry) / entry)
            if pnl_unlev > mfe:
                mfe = pnl_unlev
            armed = mfe >= p["arm_rr"] * (abs(entry - stop) / entry)
            exit_price = None
            reason = None
            if pos == 1:
                dyn_stop = stop if not armed else max(stop, c - p["trail_atr"] * atrv)
                if low <= dyn_stop:
                    exit_price = dyn_stop
                    reason = "trail" if armed else "stop"
                elif short_sig[i] or hold >= p["max_hold"]:
                    exit_price = nxt_open
                    reason = "flip" if short_sig[i] else "time"
            else:
                dyn_stop = stop if not armed else min(stop, c + p["trail_atr"] * atrv)
                if h >= dyn_stop:
                    exit_price = dyn_stop
                    reason = "trail" if armed else "stop"
                elif long_sig[i] or hold >= p["max_hold"]:
                    exit_price = nxt_open
                    reason = "flip" if long_sig[i] else "time"
            if exit_price is not None:
                ret = pos * ((exit_price - entry) / entry) * lev - 2 * fee * lev
                eq *= max(1e-9, 1.0 + ret)
                peak = max(peak, eq)
                maxdd = min(maxdd, eq / peak - 1.0)
                trades.append((entry_time, idx[i], pos, lev, entry, exit_price, ret, reason, hold))
                pos = 0
                cooldown = cooldown_bars
        else:
            if cooldown > 0:
                cooldown -= 1
                continue
            if long_sig[i]:
                pos = 1
                entry = nxt_open
                base_lev = 1 + int((adxv > 24) and (fadxv > 24))
                lev = float(base_lev) * float(lev_scale)
                stop = entry - p["stop_atr"] * atrv
                entry_time = idx[i + 1]
                hold = 0
                mfe = 0.0
            elif short_sig[i]:
                pos = -1
                entry = nxt_open
                base_lev = 1 + int((adxv > 24) and (fadxv > 24))
                lev = float(base_lev) * float(lev_scale)
                stop = entry + p["stop_atr"] * atrv
                entry_time = idx[i + 1]
                hold = 0
                mfe = 0.0

    tdf = pd.DataFrame(
        trades,
        columns=["entry_time", "exit_time", "side", "lev", "entry", "exit", "ret", "reason", "bars"],
    )
    if not tdf.empty:
        tdf["win"] = tdf["ret"] > 0
    return tdf, maxdd * 100.0


def attach_trade_features(trades: pd.DataFrame, seed: dict[str, Any], oi_df: pd.DataFrame, lsr_df: pd.DataFrame, taker_df: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return trades.copy()
    out = trades.copy()
    out["symbol"] = str(seed["symbol"])
    out["seed_id"] = str(seed["seed_id"])
    out["entry_tf"] = str(seed["entry_tf"])
    out["filter_tf"] = str(seed["filter_tf"])
    out["family"] = str(seed["family"])
    out["param_id"] = str(seed["param_id"])
    out["mode"] = str(seed["mode"])
    out["entry_time_utc"] = pd.to_datetime(out["entry_time"], utc=True)
    out["exit_time_utc"] = pd.to_datetime(out["exit_time"], utc=True)
    out["side_label"] = np.where(out["side"] > 0, "LONG", "SHORT")
    out["scaled_ret"] = pd.to_numeric(out["ret"], errors="coerce").fillna(0.0)
    out["scaled_lev"] = pd.to_numeric(out["lev"], errors="coerce").fillna(0.0)
    return msb._attach_features(out, oi_df, lsr_df, taker_df)


def apply_paired_overlay(trades: pd.DataFrame, windows: pd.DataFrame, variant_a: dict[str, Any], variant_b: dict[str, Any], pair_name: str, pair_perspective: str) -> pd.DataFrame:
    if trades.empty:
        return trades.copy()
    a = s234.apply_overlay(trades, windows, variant_a)
    b = s234.apply_overlay(trades, windows, variant_b)
    rows = []
    for (_, ra), (_, rb) in zip(a.iterrows(), b.iterrows(), strict=False):
        out = ra.copy()
        scale_a = float(ra.get("msg_scale", 1.0))
        scale_b = float(rb.get("msg_scale", 1.0))
        if str(ra.get("msg_action", "HOLD")) == "WAIT" or str(rb.get("msg_action", "HOLD")) == "WAIT":
            scale = 0.0
            action = "WAIT"
        else:
            scale = 0.5 * (scale_a + scale_b)
            if scale <= 0.60:
                action = "CUT_MID"
            elif scale < 0.92:
                action = "CUT_SOFT"
            elif scale >= 1.18:
                action = "BOOST_MID"
            elif scale > 1.03:
                action = "BOOST_SOFT"
            else:
                action = "HOLD"
        out["overlay_name"] = pair_name
        out["overlay_perspective"] = pair_perspective
        out["msg_total_support"] = 0.5 * (float(ra.get("msg_total_support", 0.0)) + float(rb.get("msg_total_support", 0.0)))
        out["msg_total_adverse"] = 0.5 * (float(ra.get("msg_total_adverse", 0.0)) + float(rb.get("msg_total_adverse", 0.0)))
        out["msg_net_score"] = 0.5 * (float(ra.get("msg_net_score", 0.0)) + float(rb.get("msg_net_score", 0.0)))
        out["msg_action"] = action
        out["msg_scale"] = scale
        base_ret = float(pd.to_numeric(ra.get("ret", 0.0), errors="coerce"))
        base_lev = float(pd.to_numeric(ra.get("lev", 0.0), errors="coerce"))
        out["scaled_ret"] = max(-0.95, base_ret * scale)
        out["scaled_lev"] = base_lev * scale
        rows.append(out)
    return pd.DataFrame(rows)


def score_overlay_mode(mode_name: str, policy_trades: pd.DataFrame, windows: pd.DataFrame, anchor_variant: dict[str, Any], reserve_variant: dict[str, Any]) -> pd.DataFrame:
    if mode_name == "anchor_single":
        out = s234.apply_overlay(policy_trades, windows, anchor_variant)
        out["overlay_mode"] = mode_name
        return out
    out = apply_paired_overlay(
        policy_trades,
        windows,
        anchor_variant,
        reserve_variant,
        pair_name=f"{anchor_variant['name']}__plus__{reserve_variant['name']}",
        pair_perspective=f"paired:{anchor_variant['perspective']}+{reserve_variant['perspective']}",
    )
    out["overlay_mode"] = mode_name
    return out


def classify(base: dict[str, float], row: dict[str, Any]) -> str:
    recent_pf = float(row.get("recent_pf", 0.0))
    recent_ret = float(row.get("recent_ret", 0.0))
    recent_dd = float(row.get("recent_dd", 0.0))
    recent_win = float(row.get("recent_win", 0.0))
    wf_pf = float(row.get("wf_pf", 0.0))
    wf_ret = float(row.get("wf_ret", 0.0))
    keep_ratio = float(row.get("recent_keep_ratio", 1.0))
    wait_ratio = float(row.get("wait_ratio_recent", 0.0))
    base_recent_pf = float(base.get("recent_pf", 0.0))
    base_recent_ret = float(base.get("recent_ret", 0.0))
    base_recent_dd = float(base.get("recent_dd", 0.0))
    base_recent_win = float(base.get("recent_win", 0.0))
    base_wf_pf = float(base.get("wf_pf", 0.0))
    dd_improve_recent = base_recent_dd - recent_dd
    win_up = recent_win >= base_recent_win + 2.0
    if recent_pf >= max(1.15, base_recent_pf * 1.05) and recent_ret >= base_recent_ret * 0.95 and wf_pf >= max(1.0, base_wf_pf * 0.97) and keep_ratio >= 0.60 and wait_ratio <= 0.25 and dd_improve_recent >= -1.0:
        return "promote_policy_primary"
    if recent_pf >= max(1.05, base_recent_pf * 1.00) and wf_pf >= 1.0 and keep_ratio >= 0.55 and wait_ratio <= 0.30 and dd_improve_recent >= 0.5:
        return "promote_policy_protective"
    if (recent_pf >= base_recent_pf * 0.98 and wf_pf >= 1.0 and keep_ratio >= 0.45) or (win_up and recent_ret > 0):
        return "keep_policy_secondary"
    if recent_ret > 0 and wf_ret > -5.0:
        return "keep_policy_research"
    return "discard_policy"


def rec_rank(name: str) -> int:
    order = {
        "promote_policy_primary": 0,
        "promote_policy_protective": 1,
        "keep_policy_secondary": 2,
        "keep_policy_research": 3,
        "discard_policy": 4,
    }
    return order.get(name, 9)


def composite_score(base: dict[str, float], row: dict[str, Any]) -> float:
    ret_delta_recent = float(row.get("recent_ret", 0.0)) - float(base.get("recent_ret", 0.0))
    pf_delta_recent = float(row.get("recent_pf", 0.0)) - float(base.get("recent_pf", 0.0))
    pf_delta_wf = float(row.get("wf_pf", 0.0)) - float(base.get("wf_pf", 0.0))
    dd_improve_recent = float(base.get("recent_dd", 0.0)) - float(row.get("recent_dd", 0.0))
    dd_improve_wf = float(base.get("wf_dd", 0.0)) - float(row.get("wf_dd", 0.0))
    wait_ratio = float(row.get("wait_ratio_recent", 0.0))
    keep_ratio = float(row.get("recent_keep_ratio", 1.0))
    return max(-30.0, min(30.0, ret_delta_recent)) + 10.0 * pf_delta_recent + 8.0 * pf_delta_wf + 1.6 * dd_improve_recent + 1.1 * dd_improve_wf - 25.0 * wait_ratio - 6.0 * abs(keep_ratio - 1.0)


def run(project_dir: Path) -> dict[str, Any]:
    out_dir = project_dir / "reports" / "research_raw"
    out_dir.mkdir(parents=True, exist_ok=True)
    lab = s231.SeededConfirmationMatrix(project_dir)
    hist = msb._load_or_fetch_history(project_dir, refresh=False)
    oi_df = msb._parse_oi_df(hist.get("oi_agg_btc_1d", {}))
    lsr_df = msb._parse_lsr_df(hist.get("lsr_btcusdt_binance_4h", {}))
    taker_df = msb._parse_taker_df(hist.get("taker_btcusdt_binance_4h", {}))
    windows = msb._load_event_windows(project_dir, pd.Timestamp("2019-01-01", tz="UTC"), pd.Timestamp.now(tz="UTC") + pd.Timedelta(days=7), include_all_modes=True)

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
        base_trades = attach_trade_features(base_trades_raw, seed, oi_df, lsr_df, taker_df)
        base_metrics = s234.slice_metrics(base_trades)
        base_by_seed[sid] = base_metrics

        plan = SEED_OVERLAY_PLAN[sid]
        anchor_variant = VARIANT_BY_NAME[plan["anchor"]]
        reserve_variant = VARIANT_BY_NAME[plan["reserve"]]

        for overlay_mode in ["anchor_single", "paired_blend"]:
            for policy in RISK_POLICIES:
                rp = adjusted_params(base_p, policy)
                policy_trades_raw, _ = backtest_with_policy(df, long_sig, short_sig, rp, seed["mode"], float(policy["lev_scale"]))
                if policy_trades_raw.empty:
                    continue
                policy_trades = attach_trade_features(policy_trades_raw, seed, oi_df, lsr_df, taker_df)
                scored = score_overlay_mode(overlay_mode, policy_trades, windows, anchor_variant, reserve_variant)
                metrics = s234.slice_metrics(scored)
                recent_start = pd.to_datetime(scored["entry_time_utc"], utc=True).max() - pd.DateOffset(years=2)
                counts_recent = scored[scored["entry_time_utc"] >= recent_start]["msg_action"].value_counts()
                counts_all = scored["msg_action"].value_counts()
                row: dict[str, Any] = {
                    "seed_id": sid, "symbol": seed["symbol"], "entry_tf": seed["entry_tf"], "filter_tf": seed["filter_tf"], "family": seed["family"], "param_id": seed["param_id"], "mode": seed["mode"],
                    "anchor_overlay": anchor_variant["name"], "reserve_overlay": reserve_variant["name"], "overlay_mode": overlay_mode, "overlay_note": plan["note"],
                    "policy_name": policy["policy_name"], "policy_label": policy["label"], "stop_mult": policy["stop_mult"], "trail_mult": policy["trail_mult"], "arm_mult": policy["arm_mult"], "hold_mult": policy["hold_mult"], "lev_scale": policy["lev_scale"],
                    "full_boost_soft": int(counts_all.get("BOOST_SOFT", 0)), "full_boost_mid": int(counts_all.get("BOOST_MID", 0)), "full_cut_soft": int(counts_all.get("CUT_SOFT", 0)), "full_cut_mid": int(counts_all.get("CUT_MID", 0)), "full_wait": int(counts_all.get("WAIT", 0)),
                    "recent_boost_soft": int(counts_recent.get("BOOST_SOFT", 0)), "recent_boost_mid": int(counts_recent.get("BOOST_MID", 0)), "recent_cut_soft": int(counts_recent.get("CUT_SOFT", 0)), "recent_cut_mid": int(counts_recent.get("CUT_MID", 0)), "recent_wait": int(counts_recent.get("WAIT", 0)),
                    **metrics,
                    "base_full_ret": base_metrics["full_ret"], "base_full_pf": base_metrics["full_pf"], "base_full_dd": base_metrics["full_dd"],
                    "base_recent_ret": base_metrics["recent_ret"], "base_recent_pf": base_metrics["recent_pf"], "base_recent_dd": base_metrics["recent_dd"], "base_recent_win": base_metrics["recent_win"], "base_recent_trades": base_metrics["recent_trades"],
                    "base_wf_ret": base_metrics["wf_ret"], "base_wf_pf": base_metrics["wf_pf"], "base_wf_dd": base_metrics["wf_dd"], "base_wf_trades": base_metrics["wf_trades"],
                }
                row["recent_keep_ratio"] = float(metrics["recent_trades"] / max(1, base_metrics["recent_trades"]))
                row["wait_ratio_recent"] = float(row["recent_wait"] / max(1, base_metrics["recent_trades"]))
                row["pf_delta_recent"] = float(metrics["recent_pf"] - base_metrics["recent_pf"])
                row["ret_delta_recent"] = float(metrics["recent_ret"] - base_metrics["recent_ret"])
                row["win_delta_recent"] = float(metrics["recent_win"] - base_metrics["recent_win"])
                row["dd_improve_recent"] = float(base_metrics["recent_dd"] - metrics["recent_dd"])
                row["pf_delta_wf"] = float(metrics["wf_pf"] - base_metrics["wf_pf"])
                row["dd_improve_wf"] = float(base_metrics["wf_dd"] - metrics["wf_dd"])
                row["recommendation"] = classify(base_metrics, row)
                row["recommendation_rank"] = rec_rank(row["recommendation"])
                row["composite_score"] = composite_score(base_metrics, row)
                rows.append(row)

    df = pd.DataFrame(rows)
    if not df.empty:
        df.sort_values(["seed_id", "recommendation_rank", "composite_score", "recent_pf", "wf_pf"], ascending=[True, True, False, False, False], inplace=True)
    (out_dir / "stage235_seeded_multiview_risk_matrix_all.csv").write_text(df.to_csv(index=False), encoding="utf-8")

    best_by_seed: dict[str, Any] = {}
    lines: list[str] = []
    lines.append("[stage235_seeded_multiview_risk_matrix]")
    lines.append("goal=在 stage234 的多视角 overlay 之上，继续测试 严格止损 / 动态盈利止损 / 研究杠杆代理；同时把 散户视角 + 机构/交易所视角 做成单视角与配对混合 两种模式")
    lines.append(f"tested_rows={len(df)}")
    for key in ["promote_policy_primary", "promote_policy_protective", "keep_policy_secondary", "keep_policy_research"]:
        lines.append(f"{key}_total={int((df['recommendation'] == key).sum()) if not df.empty else 0}")
    lines.append("ranking=先看近2年 PF/收益/保留比，再看 WF PF；6年继续只做软约束；extreme_research_not_runtime 只算研究层，不代表 runtime 准备好")
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
        lines.append(f"- {sid} | base={seed['entry_tf']}/{seed['filter_tf']} {seed['family']} {seed['param_id']} {seed['mode']} | recent={base['recent_ret']:.2f}%/{base['recent_win']:.2f}%/PF{base['recent_pf']:.3f} | wf={base['wf_ret']:.2f}%/PF{base['wf_pf']:.3f}")
        lines.append(f"  -> top={best['recommendation']} {best['overlay_mode']} + {best['policy_name']} | anchor={best['anchor_overlay']} reserve={best['reserve_overlay']} | recent={best['recent_ret']:.2f}%/{best['recent_win']:.2f}%/PF{best['recent_pf']:.3f} | wf={best['wf_ret']:.2f}%/PF{best['wf_pf']:.3f} | keep={best['recent_keep_ratio']:.2f} | wait={best['wait_ratio_recent']:.2f}")
        best_by_seed[sid] = {"seed_meta": seed, "base": base, "best_policy": best}
    lines.append("")
    lines.append("[multiview_hint]")
    lines.append("- 不是全币统一视角：BTC 先偏 hybrid/institution；BNB 先偏 exchange/institution；ETH 先偏 hybrid/balanced；SOL 先偏 retail/balanced。")
    lines.append("- paired_blend 代表把 anchor + reserve 两个视角先平均进 sizing，再看是否比单视角更稳。")
    lines.append("- 这轮仍不改 entry，不切 runtime；只给 overlay + risk policy 结论。")
    (out_dir / "stage235_seeded_multiview_risk_matrix_latest.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    summary = {"goal": "seeded multiview overlay plus stop/trail/leverage proxy matrix", "tested_rows": int(len(df)), "best_by_seed": best_by_seed, "top_rows": df.sort_values(["recommendation_rank", "composite_score"], ascending=[True, False]).head(12).to_dict(orient="records") if not df.empty else []}
    (out_dir / "stage235_seeded_multiview_risk_matrix_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage235 seeded multiview risk matrix")
    ap.add_argument("--project-dir", type=Path, default=Path("."))
    args = ap.parse_args()
    run(args.project_dir.resolve())


if __name__ == "__main__":
    main()
