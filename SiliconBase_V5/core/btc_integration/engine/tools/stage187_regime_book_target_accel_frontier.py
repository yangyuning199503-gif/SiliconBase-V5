from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import stage46_aggressive_lab as s46
from tools import stage77_mainline_dual_window_lab as s77
from tools import stage88_strategy_fusion_walkforward as s88
from tools import stage90_event_alpha_matrix as s90
from tools import stage136_regime_plateau_frontier as s136
from tools import stage141_guarded_asymmetry_shortlist as s141
from tools import stage161_mainline_risk_budget_multiasset_link_frontier as s161
from tools import stage186_truth_anchor_target_lift_frontier as s186

TARGET_MONTHLY_MIN = float(s186.TARGET_MONTHLY_MIN)
TARGET_MONTHLY_MAX = float(s186.TARGET_MONTHLY_MAX)

SAFE_FLOAT = s186.SAFE_FLOAT
SAFE_INT = s186.SAFE_INT
WITH_META = s186.WITH_META
RECENT_METRICS = s186.RECENT_METRICS
WF_METRICS = s186.WF_METRICS
FULL_METRICS = s186.FULL_METRICS
SYMBOL = s186.SYMBOL
FAMILY = s186.FAMILY
PLAYBOOK = s186.PLAYBOOK
HARD_BLACKLISTED = s186.HARD_BLACKLISTED
WRITE_SINGLE_ZIP = s186.WRITE_SINGLE_ZIP


def _score(row: dict[str, Any], runtime_anchor: dict[str, Any], *, branch: bool) -> float:
    score = s186._score(row, runtime_anchor, branch=branch)
    pb = PLAYBOOK(row)
    sym = SYMBOL(row, branch=branch)
    if pb in {"mainline_bnb_accel", "mainline_reclaim_gate"}:
        score += 180.0
    if pb in {"eth_event_drift_fast", "eth_squeeze_follow_fast", "eth_reclaim_beta_fast"}:
        score += 160.0
    if pb == "eth_retest_short_fast":
        score += 60.0
    if pb in {"btc_squeeze_follow_fast", "btc_breakout_fast", "btc_dual_mild"}:
        score += 100.0
    if pb in {"sol_pullback_pair_fast", "sol_range_ladder_fast"}:
        score += 110.0
    if pb == "sol_guarded_short_fast":
        score += 50.0
    if branch and sym == "btc" and ("break_fail" in str(row.get("name") or "").lower()):
        score -= 99999.0
    return score


def _row_payload(row: dict[str, Any], runtime_anchor: dict[str, Any], *, branch: bool) -> dict[str, Any]:
    recent, wf, full = s186._runtime_adjusted_metrics(row, runtime_anchor, branch=branch)
    best_m = max(SAFE_FLOAT(recent.get("monthlyized_ret")), SAFE_FLOAT(wf.get("monthlyized_ret")))
    return {
        "name": str(row.get("name") or ""),
        "symbol": SYMBOL(row, branch=branch),
        "family": FAMILY(row),
        "playbook": PLAYBOOK(row),
        "alpha_score": SAFE_FLOAT(row.get("alpha_score")),
        "score": _score(row, runtime_anchor, branch=branch),
        "status": s186._status(row, runtime_anchor, branch=branch),
        "recent_monthly": SAFE_FLOAT(recent.get("monthlyized_ret")),
        "wf_monthly": SAFE_FLOAT(wf.get("monthlyized_ret")),
        "recent_ret": SAFE_FLOAT(recent.get("ret")),
        "wf_ret": SAFE_FLOAT(wf.get("ret")),
        "recent_pf": SAFE_FLOAT(recent.get("pf")),
        "wf_pf": SAFE_FLOAT(wf.get("pf")),
        "recent_trades": SAFE_INT(recent.get("trades")),
        "wf_trades": SAFE_INT(wf.get("trades")),
        "recent_maxdd": SAFE_FLOAT(recent.get("maxdd")),
        "wf_maxdd": SAFE_FLOAT(wf.get("maxdd")),
        "full_ret": SAFE_FLOAT(full.get("ret")),
        "full_pf": SAFE_FLOAT(full.get("pf")),
        "full_trades": SAFE_INT(full.get("trades")),
        "gap_to_floor": TARGET_MONTHLY_MIN - best_m,
    }


def _top_payload(rows: list[dict[str, Any]], runtime_anchor: dict[str, Any], *, branch: bool) -> list[dict[str, Any]]:
    payload = [_row_payload(r, runtime_anchor, branch=branch) for r in rows]
    payload.sort(key=lambda r: (r["score"], r["alpha_score"]), reverse=True)
    return payload


def _select_top(payload: list[dict[str, Any]], *, symbol: str | None = None, limit: int = 5) -> list[dict[str, Any]]:
    rows = payload
    if symbol:
        rows = [r for r in rows if r["symbol"] == symbol]
    return rows[:limit]


def _mainline_items() -> list[dict[str, Any]]:
    item_map = {str(item.get("name")): item for item in s88._mainline_items()}
    base = item_map.get("mainline_live_dynlev_fix8_lock18")
    if base is None:
        raise SystemExit("missing mainline_live_dynlev_fix8_lock18 base item")
    out: list[dict[str, Any]] = []

    def add(name: str, note: str, patch: dict[str, Any], track: str, playbook: str) -> None:
        out.append(
            WITH_META(
                s88._make_mainline_variant(base, name=name, note=note, patch=patch),
                track=track,
                branch=False,
                anchor_name="mainline_live_dynlev_fix8_lock18",
                playbook=playbook,
            )
        )

    add(
        "mainline_live_dynlev_fix8_lock18_bnb118_btc520_tp112_trail046_cd8",
        "主线 stage187：BNB 主腿 mild 提频，BTC hedge 不放大，只验证能否抬月化。",
        {
            "strategy_params.cooldown_bars": 8,
            "money_management.stake_scale.bnb_long": 1.18,
            "money_management.stake_scale.btc_short": 5.20,
            "money_management.take_profit_pct": 1.12,
            "money_management.trailing_profit.activation_pnl_pct": 0.46,
            "money_management.trailing_profit.giveback_ratio": 0.23,
        },
        "mainline_bnb_accel",
        "mainline_bnb_accel",
    )
    add(
        "mainline_live_dynlev_fix8_lock18_bnb122_btc560_tp118_trail050_cd7",
        "主线 stage187：更激进的 BNB 提频邻域，只围绕 fix8_lock18 小步扩圈。",
        {
            "strategy_params.cooldown_bars": 7,
            "money_management.stake_scale.bnb_long": 1.22,
            "money_management.stake_scale.btc_short": 5.60,
            "money_management.take_profit_pct": 1.18,
            "money_management.trailing_profit.activation_pnl_pct": 0.50,
            "money_management.trailing_profit.giveback_ratio": 0.24,
        },
        "mainline_bnb_accel",
        "mainline_bnb_accel",
    )
    add(
        "mainline_live_dynlev_fix8_lock18_reclaim_gate_bnb116_btc540_tp114_trail044_cd8",
        "主线 stage187：事件/回收确认 mild 版，不改骨架，只换更积极的兑现节奏。",
        {
            "strategy_params.breakout_lookback": 26,
            "strategy_params.breakout_atr_buffer": 0.48,
            "strategy_params.cooldown_bars": 8,
            "filters.adx_floor": 28,
            "money_management.stake_scale.bnb_long": 1.16,
            "money_management.stake_scale.btc_short": 5.40,
            "money_management.take_profit_pct": 1.14,
            "money_management.trailing_profit.activation_pnl_pct": 0.44,
            "money_management.trailing_profit.giveback_ratio": 0.22,
        },
        "mainline_reclaim_gate",
        "mainline_reclaim_gate",
    )
    return out


def _branch_items() -> list[dict[str, Any]]:
    item_map = {str(item.get("name")): item for item in s88._branch_items()}
    out: list[dict[str, Any]] = []

    def add(item: dict[str, Any] | None, *, name: str, note: str, family: str, patch: dict[str, Any], track: str, anchor_name: str, playbook: str) -> None:
        if item is None:
            return
        out.append(
            WITH_META(
                s88._make_variant(item, name=name, note=note, family=family, patch=patch),
                track=track,
                branch=True,
                anchor_name=anchor_name,
                playbook=playbook,
            )
        )

    btc_squeeze = item_map.get("btc_squeeze_follow_long_lb16_atr050_adx20_s058") or item_map.get("btc_breakout_long_event_lb20_atr060_adx24_s050")
    btc_breakout = item_map.get("btc_breakout_long_event_lb20_atr060_adx24_s050") or btc_squeeze
    btc_dual = item_map.get("btc_dual_fast_trend_dynlev_fix8")
    btc_short = item_map.get("btc_retest_short_event_lb20_atr060_adx24_s072") or item_map.get("btc_retest_short_event_lb18_atr056_adx22_s074")

    eth_anchor = item_map.get("eth_reclaim_long_lb12_atr043_adx16_s060") or item_map.get("eth_reclaim_long_lb11_atr043_adx16_s060") or item_map.get("eth_breakout_long_event_lb16_atr050_adx22_s034")
    eth_short = item_map.get("eth_retest_short_trend_lb20_atr060_adx24_s068") or item_map.get("eth_retest_short_trend_lb18_atr055_adx22_s072")

    sol_anchor = item_map.get("sol_pullback_long_core_adx26_cd6_lb22_zone026_s040") or item_map.get("sol_long_core_soft_lb20_zone025_s042")
    sol_short = item_map.get("sol_fast_trend_short_guarded_lb16_atr055_adx22_s072") or item_map.get("sol_fast_trend_short_guarded_lb18_atr060_adx24_s068")

    add(
        btc_squeeze,
        name="btc_squeeze_follow_long_lb14_atr048_adx18_s060",
        note="BTC stage187：优先围绕 squeeze follow 做更快一档提频。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 14,
            "strategy_params.breakout_atr_buffer": 0.48,
            "strategy_params.cooldown_bars": 2,
            "filters.adx_floor": 18,
            "money_management.stake_scale.btc_long": 0.60,
            "money_management.take_profit_pct": 1.14,
            "money_management.trailing_profit.activation_pnl_pct": 0.42,
            "money_management.trailing_profit.giveback_ratio": 0.22,
        },
        track="btc_squeeze_follow_fast",
        anchor_name=str(btc_squeeze.get("name")) if btc_squeeze else "",
        playbook="btc_squeeze_follow_fast",
    )
    add(
        btc_breakout,
        name="btc_breakout_long_event_lb18_atr056_adx22_s054",
        note="BTC stage187：保留 breakout 快版，不让 BTC 只剩一个方向模板。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 18,
            "strategy_params.breakout_atr_buffer": 0.56,
            "strategy_params.cooldown_bars": 2,
            "filters.adx_floor": 22,
            "money_management.stake_scale.btc_long": 0.58,
            "money_management.take_profit_pct": 1.12,
            "money_management.trailing_profit.activation_pnl_pct": 0.42,
            "money_management.trailing_profit.giveback_ratio": 0.22,
        },
        track="btc_breakout_fast",
        anchor_name=str(btc_breakout.get("name")) if btc_breakout else "",
        playbook="btc_breakout_fast",
    )
    add(
        btc_dual,
        name="btc_dual_fast_trend_dynlev_fix8_cd2",
        note="BTC stage187：dual 只留一条 mild 参考，不扩 break_fail。",
        family="dual",
        patch={
            "strategy_params.cooldown_bars": 2,
            "filters.adx_floor": 17,
            "money_management.stake_scale.btc_long": 0.54,
            "money_management.stake_scale.btc_short": 0.84,
        },
        track="btc_dual_mild",
        anchor_name="btc_dual_fast_trend_dynlev_fix8",
        playbook="btc_dual_mild",
    )
    add(
        btc_short,
        name="btc_retest_short_event_lb18_atr056_adx22_s074",
        note="BTC stage187：空腿只保留一条 retest short fast。",
        family="short",
        patch={
            "strategy_params.breakout_lookback": 18,
            "strategy_params.breakout_atr_buffer": 0.56,
            "strategy_params.cooldown_bars": 2,
            "filters.adx_floor": 22,
            "money_management.stake_scale.btc_short": 0.84,
            "money_management.take_profit_pct": 1.02,
            "money_management.trailing_profit.activation_pnl_pct": 0.34,
            "money_management.trailing_profit.giveback_ratio": 0.20,
        },
        track="btc_retest_short_fast",
        anchor_name=str(btc_short.get("name")) if btc_short else "",
        playbook="btc_retest_short_fast",
    )

    add(
        eth_anchor,
        name="eth_event_drift_long_lb9_atr042_adx15_s050",
        note="ETH stage187：event drift fast 版，优先验证更快入场是否能抬升近2年/WF。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 9,
            "strategy_params.breakout_atr_buffer": 0.42,
            "strategy_params.cooldown_bars": 2,
            "filters.adx_floor": 15,
            "money_management.stake_scale.eth_long": 0.56,
            "money_management.take_profit_pct": 1.26,
            "money_management.trailing_profit.activation_pnl_pct": 0.44,
            "money_management.trailing_profit.giveback_ratio": 0.24,
        },
        track="eth_event_drift_fast",
        anchor_name=str(eth_anchor.get("name")) if eth_anchor else "",
        playbook="eth_event_drift_fast",
    )
    add(
        eth_anchor,
        name="eth_squeeze_follow_long_lb8_atr038_adx14_s052",
        note="ETH stage187：squeeze fast 版，保留第二主攻。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 8,
            "strategy_params.breakout_atr_buffer": 0.38,
            "strategy_params.cooldown_bars": 2,
            "filters.adx_floor": 14,
            "money_management.stake_scale.eth_long": 0.54,
            "money_management.take_profit_pct": 1.24,
            "money_management.trailing_profit.activation_pnl_pct": 0.42,
            "money_management.trailing_profit.giveback_ratio": 0.23,
        },
        track="eth_squeeze_follow_fast",
        anchor_name=str(eth_anchor.get("name")) if eth_anchor else "",
        playbook="eth_squeeze_follow_fast",
    )
    add(
        eth_anchor,
        name="eth_reclaim_beta_long_lb10_atr040_adx14_cd1_s068",
        note="ETH stage187：reclaim beta fast 版，避免只剩 drift/squeeze。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 10,
            "strategy_params.breakout_atr_buffer": 0.40,
            "strategy_params.cooldown_bars": 1,
            "filters.adx_floor": 14,
            "money_management.stake_scale.eth_long": 0.52,
            "money_management.take_profit_pct": 1.22,
            "money_management.trailing_profit.activation_pnl_pct": 0.40,
            "money_management.trailing_profit.giveback_ratio": 0.22,
        },
        track="eth_reclaim_beta_fast",
        anchor_name=str(eth_anchor.get("name")) if eth_anchor else "",
        playbook="eth_reclaim_beta_fast",
    )
    add(
        eth_short,
        name="eth_retest_short_trend_lb18_atr056_adx22_cd2_s072",
        note="ETH stage187：空腿保留一条 fast retest short。",
        family="short",
        patch={
            "strategy_params.breakout_lookback": 18,
            "strategy_params.breakout_atr_buffer": 0.56,
            "strategy_params.cooldown_bars": 2,
            "filters.adx_floor": 22,
            "money_management.stake_scale.eth_short": 0.64,
            "money_management.take_profit_pct": 1.02,
            "money_management.trailing_profit.activation_pnl_pct": 0.34,
            "money_management.trailing_profit.giveback_ratio": 0.20,
        },
        track="eth_retest_short_fast",
        anchor_name=str(eth_short.get("name")) if eth_short else "",
        playbook="eth_retest_short_fast",
    )

    add(
        sol_anchor,
        name="sol_pullback_pair_long_adx22_cd2_lb18_zone022_s050",
        note="SOL stage187：pullback pair fast 版，继续作为 SOL 第一主攻。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 18,
            "strategy_params.breakout_atr_buffer": 0.50,
            "strategy_params.cooldown_bars": 2,
            "filters.adx_floor": 22,
            "money_management.stake_scale.sol_long": 0.42,
            "money_management.take_profit_pct": 1.18,
            "money_management.trailing_profit.activation_pnl_pct": 0.40,
            "money_management.trailing_profit.giveback_ratio": 0.22,
        },
        track="sol_pullback_pair_fast",
        anchor_name=str(sol_anchor.get("name")) if sol_anchor else "",
        playbook="sol_pullback_pair_fast",
    )
    add(
        sol_anchor,
        name="sol_range_ladder_long_adx20_cd1_lb18_zone020_s054",
        note="SOL stage187：range ladder fast 版，保留第二主攻。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 18,
            "strategy_params.breakout_atr_buffer": 0.54,
            "strategy_params.cooldown_bars": 1,
            "filters.adx_floor": 20,
            "money_management.stake_scale.sol_long": 0.44,
            "money_management.take_profit_pct": 1.18,
            "money_management.trailing_profit.activation_pnl_pct": 0.40,
            "money_management.trailing_profit.giveback_ratio": 0.22,
        },
        track="sol_range_ladder_fast",
        anchor_name=str(sol_anchor.get("name")) if sol_anchor else "",
        playbook="sol_range_ladder_fast",
    )
    add(
        sol_short,
        name="sol_guarded_short_accel_lb12_atr050_adx16_cd1_s078",
        note="SOL stage187：空腿只留一条更快的 guarded short。",
        family="short",
        patch={
            "strategy_params.breakout_lookback": 12,
            "strategy_params.breakout_atr_buffer": 0.50,
            "strategy_params.cooldown_bars": 1,
            "filters.adx_floor": 16,
            "money_management.stake_scale.sol_short": 0.58,
            "money_management.take_profit_pct": 1.00,
            "money_management.trailing_profit.activation_pnl_pct": 0.34,
            "money_management.trailing_profit.giveback_ratio": 0.20,
        },
        track="sol_guarded_short_fast",
        anchor_name=str(sol_short.get("name")) if sol_short else "",
        playbook="sol_guarded_short_fast",
    )
    return out


def _write_report(path_txt: Path, path_json: Path, main_rows: list[dict[str, Any]], branch_rows: list[dict[str, Any]], repaired_main: list[str], repaired_branch: list[str], scanned_main: list[str], scanned_branch: list[str], runtime_anchor: dict[str, Any]) -> dict[str, Any]:
    main_payload = _top_payload(main_rows, runtime_anchor, branch=False)
    branch_payload = _top_payload(branch_rows, runtime_anchor, branch=True)
    active_map = s186._active_map_from_payload(branch_payload, runtime_anchor)
    split_rec = s186._split_recommendation(branch_payload)
    summary = {
        "target_monthly_min": TARGET_MONTHLY_MIN,
        "target_monthly_max": TARGET_MONTHLY_MAX,
        "repaired_main": repaired_main,
        "repaired_branch": repaired_branch,
        "scanned_main": scanned_main,
        "scanned_branch": scanned_branch,
        "runtime_anchor": runtime_anchor,
        "stage91_active": active_map,
        "split_recommendation": split_rec,
        "main_top": _select_top(main_payload, limit=6),
        "branch_by_symbol": {sym: _select_top(branch_payload, symbol=sym, limit=5) for sym in ["btc", "eth", "sol"]},
    }

    lines: list[str] = []
    lines.append("Stage187 regime-book target accel frontier")
    lines.append("")
    lines.append("[summary]")
    lines.append(f"- target_monthly_floor={TARGET_MONTHLY_MIN*100:.2f}% target_monthly_ceiling={TARGET_MONTHLY_MAX*100:.2f}%")
    lines.append(f"- repaired_main={len(repaired_main)} repaired_branch={len(repaired_branch)}")
    lines.append(f"- scanned_main={len(scanned_main)} scanned_branch={len(scanned_branch)}")
    lines.append(f"- stage91_active={json.dumps(active_map, ensure_ascii=False)}")
    lines.append(f"- split_recommendation={split_rec}")
    lines.append("")

    lines.append("[main_top]")
    for row in summary["main_top"]:
        lines.append(
            f"- {row['name']} | playbook={row['playbook']} | status={row['status']} | 6年={row['full_ret']*100:.2f}% | 近2年月化={row['recent_monthly']*100:.2f}% | WF月化={row['wf_monthly']*100:.2f}% | 近2年交易={row['recent_trades']} | WF交易={row['wf_trades']} | gap_to_7.6={row['gap_to_floor']*100:.2f}%"
        )
    lines.append("")

    for sym in ["eth", "btc", "sol"]:
        lines.append(f"[{sym}_top]")
        for row in summary["branch_by_symbol"][sym]:
            lines.append(
                f"- {row['name']} | playbook={row['playbook']} | status={row['status']} | 近2年={row['recent_ret']*100:.2f}% | 近2年月化={row['recent_monthly']*100:.2f}% | WF={row['wf_ret']*100:.2f}% | WF月化={row['wf_monthly']*100:.2f}% | 近2年交易={row['recent_trades']} | WF交易={row['wf_trades']} | gap_to_7.6={row['gap_to_floor']*100:.2f}%"
            )
        lines.append("")

    lines.append("[conclusion]")
    if summary["main_top"]:
        top = summary["main_top"][0]
        lines.append(f"- 主线第一候选: {top['name']} | 近2年月化={top['recent_monthly']*100:.2f}% | WF月化={top['wf_monthly']*100:.2f}%")
    eth_top = summary["branch_by_symbol"]["eth"][0] if summary["branch_by_symbol"]["eth"] else None
    btc_top = summary["branch_by_symbol"]["btc"][0] if summary["branch_by_symbol"]["btc"] else None
    sol_top = summary["branch_by_symbol"]["sol"][0] if summary["branch_by_symbol"]["sol"] else None
    if eth_top:
        lines.append(f"- ETH 第一候选: {eth_top['name']} | 近2年月化={eth_top['recent_monthly']*100:.2f}% | WF月化={eth_top['wf_monthly']*100:.2f}%")
    if btc_top:
        lines.append(f"- BTC 第一候选: {btc_top['name']} | 近2年月化={btc_top['recent_monthly']*100:.2f}% | WF月化={btc_top['wf_monthly']*100:.2f}%")
    if sol_top:
        lines.append(f"- SOL 第一候选: {sol_top['name']} | 近2年月化={sol_top['recent_monthly']*100:.2f}% | WF月化={sol_top['wf_monthly']*100:.2f}%")
    lines.append("- 这版不动 demo / 下单链路，只把研究层推进到更清晰的 BTC/ETH/SOL 一体腿 book。")
    lines.append("- 主线继续锚定 fix8_lock18；ETH 主攻 drift_fast + squeeze_fast + reclaim_beta_fast；BTC 主攻 squeeze/breakout；SOL 主攻 pullback_pair/range_ladder。")
    txt = "\n".join(lines).rstrip() + "\n"
    path_txt.write_text(txt, encoding="utf-8")
    path_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage187 regime-book target accel frontier")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    raw = root / "reports" / "research_raw"
    raw.mkdir(parents=True, exist_ok=True)

    main_rows, branch_rows, repaired_main, repaired_branch = s141._load_stage_state(raw)
    cfg = s186._load_live_cfg(root)
    initial_equity = float(cfg.get("portfolio", {}).get("initial_equity", 100000.0))
    data = s46._load_portfolio_data(root, cfg)
    full_start, full_end = s77._window_bounds_from_data(data)
    runtime_anchor = s186._parse_runtime_anchor(root)

    item_map = {str(item.get("name")): item for item in s88._mainline_items()}
    ref_item = item_map.get("mainline_live_dynlev_fix8_lock18") or item_map.get("mainline_live_base")
    if ref_item is None:
        raise SystemExit("missing mainline reference")
    ref_row = s136._run_mainline(root, cfg, data, WITH_META(ref_item, track="base", branch=False, anchor_name=str(ref_item.get("name")), playbook="base"), initial_equity, full_start, full_end)

    main_map = {str(r.get("name")): s161._ensure_mainline_row(r, ref_row, initial_equity, full_end) for r in main_rows}
    scanned_main: list[str] = []
    for item in _mainline_items():
        print(f"[stage187] main {item['name']}", flush=True)
        row = s136._run_mainline(root, cfg, data, item, initial_equity, full_start, full_end)
        row = s161._ensure_mainline_row(row, ref_row, initial_equity, full_end)
        main_map[str(row.get("name"))] = row
        scanned_main.append(str(row.get("name")))
    main_rows = s161._finalize_rows(list(main_map.values()), branch=False)

    branch_map = {str(r.get("name")): s161._ensure_branch_row(r, initial_equity) for r in branch_rows}
    scanned_branch: list[str] = []
    for item in _branch_items():
        print(f"[stage187] branch {item['name']}", flush=True)
        row = s136._run_branch(root, cfg, item, initial_equity)
        row = s161._ensure_branch_row(row, initial_equity)
        branch_map[str(row.get("name"))] = row
        scanned_branch.append(str(row.get("name")))
    branch_rows = s161._finalize_rows(list(branch_map.values()), branch=True)

    main_txt = raw / "stage90_mainline_event_alpha_matrix_latest.txt"
    main_json = raw / "stage90_mainline_event_alpha_matrix_latest.json"
    branch_txt = raw / "stage91_branch_event_alpha_matrix_latest.txt"
    branch_json = raw / "stage91_branch_event_alpha_matrix_latest.json"
    s90._write_mainline(main_txt, main_json, main_rows)
    s90._write_branch(branch_txt, branch_json, branch_rows)

    frontier_txt = raw / "stage187_regime_book_target_accel_frontier_latest.txt"
    frontier_json = raw / "stage187_regime_book_target_accel_frontier_latest.json"
    summary = _write_report(frontier_txt, frontier_json, main_rows, branch_rows, repaired_main, repaired_branch, scanned_main, scanned_branch, runtime_anchor)
    manifest = {
        "mode": "regime_book_target_accel_frontier",
        "target_monthly_min": TARGET_MONTHLY_MIN,
        "target_monthly_max": TARGET_MONTHLY_MAX,
        "repaired_main": repaired_main,
        "repaired_branch": repaired_branch,
        "scanned_main": scanned_main,
        "scanned_branch": scanned_branch,
        "runtime_anchor": runtime_anchor,
        "stage91_active": summary.get("stage91_active"),
        "split_recommendation": summary.get("split_recommendation"),
        "outputs": {
            "stage90_txt": str(main_txt),
            "stage90_json": str(main_json),
            "stage91_txt": str(branch_txt),
            "stage91_json": str(branch_json),
            "frontier_txt": str(frontier_txt),
            "frontier_json": str(frontier_json),
        },
    }
    manifest_path = raw / "stage187_regime_book_target_accel_manifest_latest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    s141._mirror_to_workspace(root, [main_txt, main_json, branch_txt, branch_json, frontier_txt, frontier_json, manifest_path])

    out_zip = root.parent / "Downloads" / "stage187_regime_book_target_accel_frontier_latest.zip"
    WRITE_SINGLE_ZIP(out_zip, {
        "stage187_regime_book_target_accel_frontier_latest.txt": frontier_txt,
        "stage187_regime_book_target_accel_frontier_latest.json": frontier_json,
        "stage187_regime_book_target_accel_manifest_latest.json": manifest_path,
        "stage90_mainline_event_alpha_matrix_latest.txt": main_txt,
        "stage90_mainline_event_alpha_matrix_latest.json": main_json,
        "stage91_branch_event_alpha_matrix_latest.txt": branch_txt,
        "stage91_branch_event_alpha_matrix_latest.json": branch_json,
    })
    print(out_zip)


if __name__ == "__main__":
    main()
