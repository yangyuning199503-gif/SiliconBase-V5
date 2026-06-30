from __future__ import annotations

import argparse
import copy
import json
import sys
from collections import Counter
from collections.abc import Callable
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
    from tools import stage82_branch_walkforward_lab as s82
    from tools import stage88_strategy_fusion_walkforward as s88
except Exception as exc:
    raise SystemExit("缺少 stage59/76/78/82/88 模块，请先保留此前补丁。") from exc


def _pack_or(*funcs: Callable[[pd.DataFrame], pd.Series]) -> Callable[[pd.DataFrame], pd.Series]:
    def _fn(df: pd.DataFrame) -> pd.Series:
        if not funcs:
            return pd.Series(False, index=df.index)
        out = funcs[0](df)
        for fn in funcs[1:]:
            out = out | fn(df)
        return out
    return _fn


PACKS: list[tuple[str, Callable[[pd.DataFrame], pd.Series], str]] = [
    ("base_message_overlay", s88._gate_none, "只保留消息面 overlay，不加开仓条件"),
    ("event_impulse_alpha", s88._gate_major_event_impulse, "重大事件当根追随"),
    ("event_pressure_alpha", s88._gate_post_event_drift, "重大事件后 1-3 根延续跟随"),
    ("event_reclaim_alpha", s88._gate_liquidity_sweep_reclaim, "事件或失衡后的扫流动性再收回关键位"),
    ("crowding_reversal_alpha", s88._gate_crowding_reversal, "拥挤/高 OI 失衡后的反身性反转"),
    ("neutral_mean_revert_alpha", s88._gate_neutral_revert, "非事件窗口短波均值回复"),
    ("event_pressure_reclaim_alpha", _pack_or(s88._gate_post_event_drift, s88._gate_liquidity_sweep_reclaim), "事件延续 + 回收桥接"),
    ("impulse_crowding_alpha", _pack_or(s88._gate_major_event_impulse, s88._gate_crowding_reversal), "事件冲击 + 拥挤确认"),
    ("pressure_crowding_alpha", _pack_or(s88._gate_post_event_drift, s88._gate_crowding_reversal), "事件延续 + 拥挤确认"),
    ("event_crowding_reclaim_alpha", _pack_or(s88._gate_post_event_drift, s88._gate_crowding_reversal, s88._gate_liquidity_sweep_reclaim), "事件延续 + 拥挤 + 回收"),
    ("fusion_alpha_all", s88._gate_fusion_open, "趋势/事件/拥挤/扫损的全融合开仓层"),
]

EVENT_FIRST = {
    "event_impulse_alpha",
    "event_pressure_alpha",
    "event_reclaim_alpha",
    "event_pressure_reclaim_alpha",
    "impulse_crowding_alpha",
    "pressure_crowding_alpha",
    "event_crowding_reclaim_alpha",
}

AGGRESSIVE_NAMES = [
    # ETH short
    "eth_short_shock_fast_lb16_atr052_adx22_s078",
    "eth_short_shock_lb16_adx24",
    "eth_short_shock_control_lb18_adx26_s074",
    "eth_short_shock_guarded_lb20_atr062_adx28_s070",
    "eth_retest_short_trend_lb20_atr060_adx24_s068",
    "eth_retest_short_trend_lb16_atr050_adx20_s076",
    "eth_fast_trend_shortonly",
    # ETH long
    "eth_breakout_long_follow_lb16_atr050_adx22_s034",
    "eth_breakout_long_guarded_lb20_atr060_adx26_s028",
    "eth_pullback_long_core_adx24_cd6_lb22_zone026_s036",
    "eth_fast_trend_lb16_longonly",
    # SOL short
    "sol_fast_trend_short_guarded_lb16_atr055_adx22_s072",
    "sol_fast_trend_short_guarded_lb18_atr060_adx24_s068",
    "sol_retest_short_trend_lb18_atr055_adx22_s064",
    "sol_hybrid_mr_shortonly",
    # SOL long
    "sol_shortwave_smooth_longonly",
    "sol_pullback_long_core_adx26_cd6_lb22_zone026_s040",
    "sol_shortwave_long_core_lb22_zone026_adx22_s040",
]

FULL_EXTRA = [
    "eth_retest_short_trend_lb18_atr055_adx22_s072",
    "eth_breakout_long_follow_lb18_atr055_adx24_s030",
    "eth_shortwave_long_core_lb22_zone026_adx22_s038",
    "sol_fast_trend_lb16_shortonly",
    "sol_retest_short_trend_lb16_atr050_adx20_s068",
    "sol_short_shock_guarded_lb18_adx24_s062",
    "sol_long_core_adx28_cd6_lb22_zone027_s038",
    "sol_shortwave_longonly",
]


def _candidate_names(profile: str) -> list[str]:
    prof = str(profile or "aggressive").lower()
    if prof in {"full", "wide", "all"}:
        return AGGRESSIVE_NAMES + FULL_EXTRA
    return AGGRESSIVE_NAMES


def _run_branch(root: Path, cfg: dict[str, Any], item: dict[str, Any], initial_equity: float) -> dict[str, Any]:
    cfg2 = copy.deepcopy(cfg)
    sym = str(item["symbol"]).lower()
    cfg2.setdefault("data", {})["symbols"] = [sym]
    cfg2.setdefault("data", {})["weights"] = {sym: 1.0}
    cfg2.setdefault("filters", {})["macro_gate_symbols"] = [sym]
    cfg2.setdefault("filters", {})["macro_gate_reference_symbol"] = sym
    data = s76.s46._load_portfolio_data(root, cfg2)
    trades, trades_feat = s59._run_portfolio_candidate(root, cfg2, data, item["mods"])
    full_start, full_end = s78._symbol_window_bounds(root, cfg2, sym, {})
    full_m = s78._with_window_metrics(s59._metrics_from_trades(trades, initial_equity), full_start, full_end)
    gate_rows: list[dict[str, Any]] = []
    for name, fn, note in PACKS:
        gr = s59._evaluate_gate(trades_feat, name, fn, note, initial_equity)
        gr["recent_metrics"] = s78._with_window_metrics(s78._recent_metrics(gr.get("gated_df"), initial_equity), s78.RECENT_START, full_end)
        gate_rows.append(gr)
    return {
        "symbol": sym,
        "family": item.get("family", "mixed"),
        "name": item["name"],
        "note": item.get("note", ""),
        "full_metrics": full_m,
        "gate_rows": gate_rows,
        "full_end": full_end,
    }


def _event_fold_share(wf: dict[str, Any]) -> float:
    total = max(int(wf.get("total_folds", 0) or 0), 1)
    mix = wf.get("gate_mix", {}) or {}
    base_ct = int(mix.get("base_message_overlay", 0) or 0)
    return max(0.0, min(1.0, (total - base_ct) / total))


def _dominant_gate(row: dict[str, Any]) -> dict[str, Any]:
    gate_mix = Counter({str(k): int(v) for k, v in (row.get("walkforward", {}).get("gate_mix", {}) or {}).items()})
    gate_rows = row.get("gate_rows", [])

    def _key(g: dict[str, Any]) -> tuple[int, float, int, int]:
        name = str(g.get("gate_name", "-"))
        freq = gate_mix.get(name, 0)
        recent = g.get("recent_metrics", {})
        full = row.get("full_metrics", {})
        pref = float(s88._branch_gate_pref_score(recent, full))
        nonbase = 1 if name != "base_message_overlay" else 0
        event_bias = 1 if name in EVENT_FIRST else 0
        return (freq, pref + nonbase * 6.0 + event_bias * 1.5, event_bias, nonbase)

    if not gate_rows:
        return {}
    return max(gate_rows, key=_key)


def _branch_alpha_score(row: dict[str, Any]) -> float:
    dom = row["dominant_gate"]
    wf = row["walkforward"]
    recent_m = dom.get("recent_metrics", {})
    wf_m = wf.get("metrics", {})
    base = float(s88._branch_score(row["full_metrics"], recent_m, wf_m, wf.get("positive_folds", 0), wf.get("pf_floor", 0.0), wf.get("dd_ceiling", 0.0)))
    gate_name = str(dom.get("gate_name") or "")
    bonus_q = s88._event_bonus_weight(recent_m, wf_m, recent_target=10, wf_target=8)
    event_bonus = 4.0 if gate_name in EVENT_FIRST else 0.0
    return base + _event_fold_share(wf) * 34.0 * bonus_q + event_bonus * bonus_q


def _alpha_label(recent_m: dict[str, Any], wf_m: dict[str, Any], pos_folds: int, event_share: float) -> str:
    if s88._meets_trade_floor(recent_m, wf_m, recent_floor=10, wf_floor=8) and s88._safe_float(recent_m.get("pf")) >= 1.25 and s88._safe_float(wf_m.get("pf")) >= 1.15 and s88._safe_float(recent_m.get("ret")) > 0 and s88._safe_float(wf_m.get("ret")) > 0 and abs(s88._safe_float(wf_m.get("maxdd"))) <= 0.25 and pos_folds >= 3:
        return "pass"
    if s88._meets_trade_floor(recent_m, wf_m, recent_floor=4, wf_floor=3) and s88._safe_float(recent_m.get("pf")) >= 1.10 and s88._safe_float(wf_m.get("pf")) >= 1.05 and abs(s88._safe_float(wf_m.get("maxdd"))) <= 0.35:
        return "hold"
    if event_share >= 0.20 and s88._meets_trade_floor(recent_m, wf_m, recent_floor=2, wf_floor=2) and s88._safe_float(wf_m.get("pf")) >= 0.95 and abs(s88._safe_float(wf_m.get("maxdd"))) <= 0.40:
        return "reserve+"
    return "reserve"


def _json_safe(obj: Any) -> Any:
    return s88._json_safe(obj)


def _strip_gate_payload(best_gate: dict[str, Any]) -> dict[str, Any]:
    return s88._strip_gate_payload(best_gate)


def _decision_rank(decision: str) -> int:
    return {"reserve": 0, "reserve+": 1, "hold": 2, "pass": 3}.get(str(decision), -1)


def _best_by_lane(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row.get("symbol", "")).upper(), str(row.get("family", "")))
        if key not in out:
            out[key] = row
    return out


def _fmt_line(row: dict[str, Any]) -> str:
    dom = row["dominant_gate"]
    full_m = row["full_metrics"]
    recent_m = dom.get("recent_metrics", {})
    wf = row["walkforward"]
    oos_m = wf["metrics"]
    return (
        f"- {row['symbol'].upper()} | {row['family']} | {row['name']}: dominant_gate={dom.get('gate_name')} ({row['decision']})"
        f" | 6年 收益={s88._fmt_pct(full_m.get('ret'))} 月化={s88._fmt_pct(full_m.get('monthlyized_ret'))} 回撤={s88._fmt_pct(full_m.get('maxdd'))} 交易={int(full_m.get('trades',0))} PF={s88._safe_float(full_m.get('pf')):.3f}"
        f" | 近2年 收益={s88._fmt_pct(recent_m.get('ret'))} 月化={s88._fmt_pct(recent_m.get('monthlyized_ret'))} 回撤={s88._fmt_pct(recent_m.get('maxdd'))} 交易={int(recent_m.get('trades',0))} PF={s88._safe_float(recent_m.get('pf')):.3f}"
        f" | WF 收益={s88._fmt_pct(oos_m.get('ret'))} 月化={s88._fmt_pct(oos_m.get('monthlyized_ret'))} 回撤={s88._fmt_pct(oos_m.get('maxdd'))} 交易={int(oos_m.get('trades',0))} PF={s88._safe_float(oos_m.get('pf')):.3f}"
        f" | 正收益折={wf['positive_folds']}/{wf['total_folds']} | event_fold_share={_event_fold_share(wf):.2f} | alpha_score={row['alpha_score']:+.2f}"
    )


def _pick_track(rows: list[dict[str, Any]], track: str) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        gate = str(row.get("dominant_gate", {}).get("gate_name") or "")
        if track == "event_impulse" and gate == "event_impulse_alpha" or track == "event_pressure" and gate in {"event_pressure_alpha", "event_pressure_reclaim_alpha", "pressure_crowding_alpha"} or track == "event_reclaim" and gate in {"event_reclaim_alpha", "event_pressure_reclaim_alpha", "event_crowding_reclaim_alpha"} or track == "crowding_reversal" and gate in {"crowding_reversal_alpha", "impulse_crowding_alpha", "pressure_crowding_alpha", "event_crowding_reclaim_alpha"} or track == "neutral_mean_revert" and gate == "neutral_mean_revert_alpha":
            out.append(row)
    return sorted(out, key=lambda r: float(r.get("alpha_score", 0.0)), reverse=True)[:3]


def _write_outputs(path_txt: Path, path_json: Path, rows: list[dict[str, Any]], profile: str) -> None:
    lines: list[str] = []
    lines.append("Stage98 分支专家打法前沿")
    lines.append("原则：先激进扩路，再保守收口；不走单一路径，不一套参数通吃。")
    lines.append(f"profile={profile} | candidates={len(rows)} | packs={len(PACKS)}")
    lines.append("")
    lines.append("=== 当前 keep / 对照 ===")
    for row in rows:
        if row["name"] in {"eth_short_shock_fast_lb16_atr052_adx22_s078", "sol_shortwave_smooth_longonly"}:
            lines.append(_fmt_line(row))
    lines.append("")
    lines.append("=== 五轨当前领先 ===")
    for track in ["event_impulse", "event_pressure", "event_reclaim", "crowding_reversal", "neutral_mean_revert"]:
        picks = _pick_track(rows, track)
        if not picks:
            lines.append(f"- {track}: 暂无领先候选")
            continue
        lines.append(f"- {track}:")
        for row in picks:
            dom = row.get("dominant_gate", {})
            wf = row.get("walkforward", {}).get("metrics", {})
            recent = dom.get("recent_metrics", {})
            lines.append(
                f"  - {row['symbol'].upper()}|{row['family']}|{row['name']} | gate={dom.get('gate_name')} | recent 月化={s88._fmt_pct(recent.get('monthlyized_ret'))} PF={s88._safe_float(recent.get('pf')):.3f} | WF 月化={s88._fmt_pct(wf.get('monthlyized_ret'))} PF={s88._safe_float(wf.get('pf')):.3f} | decision={row['decision']}"
            )
    lines.append("")
    lines.append("=== 分支各赛道当前最优 ===")
    for (_sym, _family), row in _best_by_lane(rows).items():
        lines.append(_fmt_line(row))
        lines.append(f"  note={row['note']} | gate_mix={row['walkforward']['gate_mix']}")
    lines.append("")
    lines.append("=== 当前结论 ===")
    lines.append("- 分支 demo 继续 ETH short fast，不直接切。")
    lines.append("- 下一轮优先看 ETH short 的 event_pressure / event_reclaim 是否能在近2年 + WF 同时提升，而不是只让 event_share 变好看。")
    lines.append("- ETH long / SOL long / SOL short 都继续保留，不因当前不合格就删路径。")
    lines.append("- 只有当近2年与 WF 同时转正、PF 站稳、回撤受控，才推进新分支到 demo。")
    path_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    path_json.write_text(
        json.dumps(
            {
                "profile": profile,
                "rows": [_json_safe({**r, "dominant_gate": _strip_gate_payload(r["dominant_gate"])}) for r in rows],
                "best_by_lane": {
                    f"{sym.lower()}_{family}": _json_safe({**row, "dominant_gate": _strip_gate_payload(row["dominant_gate"])})
                    for (sym, family), row in _best_by_lane(rows).items()
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage98 分支专家打法前沿")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--profile", default="aggressive")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    cfg = rcb.load_research_base_config(root)
    initial_equity = float(cfg.get("portfolio", {}).get("initial_equity", 100000.0))
    reports_raw = root / "reports" / "research_raw"
    reports_raw.mkdir(parents=True, exist_ok=True)

    items_map = {str(x.get("name")): x for x in s76._candidate_items()}
    selected = [items_map[name] for name in _candidate_names(args.profile) if name in items_map]
    if not selected:
        raise SystemExit("未找到任何 stage98 分支候选。")

    rows = [_run_branch(root, cfg, item, initial_equity) for item in selected]
    for row in rows:
        row["walkforward"] = s82._wf_result(row, initial_equity, s78.RECENT_START, row["full_end"])
        row["dominant_gate"] = _dominant_gate(row)
        row["alpha_score"] = _branch_alpha_score(row)
        row["decision"] = _alpha_label(
            row["dominant_gate"].get("recent_metrics", {}),
            row["walkforward"].get("metrics", {}),
            row["walkforward"].get("positive_folds", 0),
            _event_fold_share(row["walkforward"]),
        )
    rows.sort(
        key=lambda r: (
            _decision_rank(str(r.get("decision"))),
            float(r.get("alpha_score", 0.0)),
            s88._safe_float((r.get("walkforward", {}).get("metrics", {}) or {}).get("pf")),
            s88._safe_float((r.get("dominant_gate", {}).get("recent_metrics", {}) or {}).get("pf")),
        ),
        reverse=True,
    )

    _write_outputs(
        reports_raw / "stage98_branch_expert_playbook_latest.txt",
        reports_raw / "stage98_branch_expert_playbook_latest.json",
        rows,
        str(args.profile),
    )
    print(reports_raw / "stage98_branch_expert_playbook_latest.txt")
    print(reports_raw / "stage98_branch_expert_playbook_latest.json")


if __name__ == "__main__":
    main()
