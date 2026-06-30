from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import stage88_strategy_fusion_walkforward as s88
from tools import stage90_event_alpha_matrix as s90
from tools import stage136_regime_plateau_frontier as s136
from tools import stage141_guarded_asymmetry_shortlist as s141
from tools import stage161_mainline_risk_budget_multiasset_link_frontier as s161
from tools import stage186_truth_anchor_target_lift_frontier as s186
from tools import stage194_voltarget_hybrid_frontier as s194

TARGET_MONTHLY_MIN = float(s186.TARGET_MONTHLY_MIN)
TARGET_MONTHLY_MAX = float(s186.TARGET_MONTHLY_MAX)

SAFE_FLOAT = s186.SAFE_FLOAT
SAFE_INT = s186.SAFE_INT
WITH_META = s186.WITH_META
SYMBOL = s186.SYMBOL
FAMILY = s186.FAMILY
PLAYBOOK = s186.PLAYBOOK
WRITE_SINGLE_ZIP = s186.WRITE_SINGLE_ZIP


def _name(o: dict[str, Any] | None) -> str:
    return s194._name(o)


def _merge_item_map(base_items: list[dict[str, Any]], existing_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return s194._merge_item_map(base_items, existing_rows)


def _load_asset_summary(path: Path) -> list[dict[str, Any]]:
    return s194._load_asset_summary(path)


def _asset_active_map(asset_summary: list[dict[str, Any]]) -> dict[str, str]:
    return s194._asset_active_map(asset_summary)


def _score(row: dict[str, Any], runtime_anchor: dict[str, Any], active_map: dict[str, str], *, branch: bool) -> float:
    score = s194._score(row, runtime_anchor, active_map, branch=branch)
    recent, wf, _ = s186._runtime_adjusted_metrics(row, runtime_anchor, branch=branch)
    sym = SYMBOL(row, branch=branch).upper()
    pb = PLAYBOOK(row)
    name = str(row.get("name") or "").lower()
    best_m = max(SAFE_FLOAT(recent.get("monthlyized_ret")), SAFE_FLOAT(wf.get("monthlyized_ret")))
    r_pf = SAFE_FLOAT(recent.get("pf"))
    w_pf = SAFE_FLOAT(wf.get("pf"))
    r_t = SAFE_INT(recent.get("trades"))
    w_t = SAFE_INT(wf.get("trades"))
    r_dd = abs(SAFE_FLOAT(recent.get("maxdd")))
    w_dd = abs(SAFE_FLOAT(wf.get("maxdd")))

    if not branch:
        if pb == "base":
            score += 240.0
        else:
            score -= 700.0
        return score

    if sym == "BTC":
        if "break_fail" in name:
            return score - 99999.0
        if pb == "btc_breakout_core":
            score += 70.0
        elif pb == "btc_squeeze_core":
            score += 60.0
        elif pb == "base":
            score += 25.0
        else:
            score -= 120.0
        if r_t < 4 or w_t < 4:
            score -= 500.0
        return score

    if sym == "ETH":
        if pb == "eth_reclaim_dense":
            score += 340.0
        elif pb == "eth_reclaim_core":
            score += 330.0
        elif pb == "eth_reclaim_ladder" or pb == "eth_reclaim_squeeze_hybrid":
            score += 300.0
        elif pb == "eth_squeeze_relay":
            score += 230.0
        elif pb == "eth_short_guard":
            score += 140.0
        if r_t >= 28 and w_t >= 20:
            score += 110.0
        if r_pf >= 2.20 and w_pf >= 2.20:
            score += 120.0
        if best_m >= 0.0140:
            score += 140.0
        elif best_m >= 0.0120:
            score += 90.0
        elif best_m >= 0.0100:
            score += 50.0
        if r_dd <= 0.040 and w_dd <= 0.040:
            score += 90.0
        if pb == "eth_short_guard" and best_m < 0.0040:
            score -= 100.0
        return score

    if sym == "SOL":
        if pb == "sol_short_balance":
            score += 260.0
        elif pb == "sol_short_relay":
            score += 250.0
        elif pb == "sol_pullback_core":
            score += 180.0
        elif pb == "sol_pullback_dense":
            score += 150.0
        if pb in {"sol_short_balance", "sol_short_relay"}:
            if w_pf >= 1.10:
                score += 90.0
            if SAFE_FLOAT(wf.get("monthlyized_ret")) >= 0.0020:
                score += 95.0
            if r_dd <= 0.090 and w_dd <= 0.090:
                score += 35.0
        if pb in {"sol_pullback_core", "sol_pullback_dense"}:
            if r_pf >= 1.45 and w_pf >= 1.35:
                score += 60.0
            if r_dd <= 0.035 and w_dd <= 0.035:
                score += 70.0
        return score

    return score


def _row_payload(row: dict[str, Any], runtime_anchor: dict[str, Any], active_map: dict[str, str], *, branch: bool) -> dict[str, Any]:
    recent, wf, full = s186._runtime_adjusted_metrics(row, runtime_anchor, branch=branch)
    best_m = max(SAFE_FLOAT(recent.get("monthlyized_ret")), SAFE_FLOAT(wf.get("monthlyized_ret")))
    return {
        "name": str(row.get("name") or ""),
        "symbol": SYMBOL(row, branch=branch),
        "family": FAMILY(row),
        "playbook": PLAYBOOK(row),
        "alpha_score": SAFE_FLOAT(row.get("alpha_score")),
        "score": _score(row, runtime_anchor, active_map, branch=branch),
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


def _top_payload(rows: list[dict[str, Any]], runtime_anchor: dict[str, Any], active_map: dict[str, str], *, branch: bool) -> list[dict[str, Any]]:
    payload = [_row_payload(r, runtime_anchor, active_map, branch=branch) for r in rows]
    payload.sort(key=lambda r: (r["score"], r["alpha_score"]), reverse=True)
    return payload


def _select_top(payload: list[dict[str, Any]], *, symbol: str | None = None, limit: int = 5) -> list[dict[str, Any]]:
    rows = payload
    if symbol:
        rows = [r for r in rows if r["symbol"] == symbol]
    return rows[:limit]


def _pick_mainline_ref(main_rows: list[dict[str, Any]], preferred_names: list[str]) -> dict[str, Any]:
    for target in preferred_names:
        for row in main_rows:
            if str(row.get("name") or "") == target:
                return copy.deepcopy(row)
    if main_rows:
        return copy.deepcopy(main_rows[0])
    return {"name": preferred_names[0] if preferred_names else "mainline_live_dynlev_fix8_lock18"}


def _coerce_full_end(ref_row: dict[str, Any]) -> Any:
    full = ref_row.get("full_metrics") if isinstance(ref_row.get("full_metrics"), dict) else {}
    return full.get("window_end") or ref_row.get("full_end")


def _mainline_items(existing_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return []


def _branch_items(existing_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    item_map = _merge_item_map(s88._branch_items(), existing_rows)
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

    eth_reclaim = item_map.get("eth_reclaim_pair_long_lb10_atr040_adx15_cd1_s064") or item_map.get("eth_reclaim_pair_long_lb9_atr038_adx14_cd1_s068") or item_map.get("eth_reclaim_long_lb12_atr043_adx16_s060")
    eth_ladder = item_map.get("eth_reclaim_ladder_long_lb11_atr043_adx16_cd2_s064") or eth_reclaim
    eth_squeeze = item_map.get("eth_squeeze_follow_long_lb8_atr036_adx13_s058") or item_map.get("eth_squeeze_follow_long_lb9_atr040_adx15_s048") or eth_reclaim
    eth_short = item_map.get("eth_retest_short_trend_lb20_atr060_adx24_cd3_s068") or item_map.get("eth_retest_short_trend_lb20_atr060_adx24_s068")

    sol_pullback = item_map.get("sol_pullback_pair_long_adx24_cd4_lb20_zone024_s046") or item_map.get("sol_pullback_grid_long_adx26_cd4_lb22_zone026_s046")
    sol_short = item_map.get("sol_guarded_short_accel_lb14_atr052_adx18_cd1_s076") or item_map.get("sol_guarded_short_accel_lb10_atr048_adx15_cd1_s080")

    add(
        eth_reclaim,
        name="eth_reclaim_pair_long_lb10_atr041_adx15_cd1_s066",
        note="ETH stage196：围绕 s064 做 core fast，先保样本外。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 10,
            "strategy_params.breakout_atr_buffer": 0.41,
            "strategy_params.cooldown_bars": 1,
            "filters.adx_floor": 15,
            "money_management.stake_scale.eth_long": 0.64,
            "money_management.take_profit_pct": 1.16,
            "money_management.trailing_profit.activation_pnl_pct": 0.32,
            "money_management.trailing_profit.giveback_ratio": 0.17,
        },
        track="eth_reclaim_core",
        anchor_name=_name(eth_reclaim),
        playbook="eth_reclaim_core",
    )
    add(
        eth_reclaim,
        name="eth_reclaim_pair_long_lb9_atr038_adx14_cd1_s070",
        note="ETH stage196：reclaim dense，更激进提频但仍守 cd1。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 9,
            "strategy_params.breakout_atr_buffer": 0.38,
            "strategy_params.cooldown_bars": 1,
            "filters.adx_floor": 14,
            "money_management.stake_scale.eth_long": 0.66,
            "money_management.take_profit_pct": 1.18,
            "money_management.trailing_profit.activation_pnl_pct": 0.34,
            "money_management.trailing_profit.giveback_ratio": 0.17,
        },
        track="eth_reclaim_dense",
        anchor_name=_name(eth_reclaim),
        playbook="eth_reclaim_dense",
    )
    add(
        eth_ladder,
        name="eth_reclaim_ladder_long_lb10_atr040_adx15_cd2_s064",
        note="ETH stage196：保留一条更稳的 ladder，防止只剩超快线。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 10,
            "strategy_params.breakout_atr_buffer": 0.40,
            "strategy_params.cooldown_bars": 2,
            "filters.adx_floor": 15,
            "money_management.stake_scale.eth_long": 0.62,
            "money_management.take_profit_pct": 1.14,
            "money_management.trailing_profit.activation_pnl_pct": 0.32,
            "money_management.trailing_profit.giveback_ratio": 0.17,
        },
        track="eth_reclaim_ladder",
        anchor_name=_name(eth_ladder),
        playbook="eth_reclaim_ladder",
    )
    add(
        eth_squeeze,
        name="eth_reclaim_squeeze_hybrid_lb8_atr036_adx13_cd1_s072",
        note="ETH stage196：把 reclaim 与 squeeze relay 真正压成一条快线。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 8,
            "strategy_params.breakout_atr_buffer": 0.36,
            "strategy_params.cooldown_bars": 1,
            "filters.adx_floor": 13,
            "money_management.stake_scale.eth_long": 0.68,
            "money_management.take_profit_pct": 1.18,
            "money_management.trailing_profit.activation_pnl_pct": 0.30,
            "money_management.trailing_profit.giveback_ratio": 0.16,
        },
        track="eth_reclaim_squeeze_hybrid",
        anchor_name=_name(eth_squeeze),
        playbook="eth_reclaim_squeeze_hybrid",
    )
    add(
        eth_squeeze,
        name="eth_squeeze_follow_long_lb7_atr034_adx12_s064",
        note="ETH stage196：单独留一条 squeeze relay，防止 reclaim 单核。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 7,
            "strategy_params.breakout_atr_buffer": 0.34,
            "strategy_params.cooldown_bars": 1,
            "filters.adx_floor": 12,
            "money_management.stake_scale.eth_long": 0.60,
            "money_management.take_profit_pct": 1.10,
            "money_management.trailing_profit.activation_pnl_pct": 0.28,
            "money_management.trailing_profit.giveback_ratio": 0.16,
        },
        track="eth_squeeze_relay",
        anchor_name=_name(eth_squeeze),
        playbook="eth_squeeze_relay",
    )
    add(
        eth_short,
        name="eth_retest_short_trend_lb10_atr042_adx14_cd1_s080",
        note="ETH stage196：空腿只留 1 条 fast guard。",
        family="short",
        patch={
            "strategy_params.breakout_lookback": 10,
            "strategy_params.breakout_atr_buffer": 0.42,
            "strategy_params.cooldown_bars": 1,
            "filters.adx_floor": 14,
            "money_management.stake_scale.eth_short": 0.72,
            "money_management.take_profit_pct": 0.90,
            "money_management.trailing_profit.activation_pnl_pct": 0.26,
            "money_management.trailing_profit.giveback_ratio": 0.16,
        },
        track="eth_short_guard",
        anchor_name=_name(eth_short),
        playbook="eth_short_guard",
    )

    add(
        sol_pullback,
        name="sol_pullback_pair_long_adx24_cd4_lb20_zone024_s044",
        note="SOL stage196：保 1 条 long core，不再给太多算力。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 20,
            "strategy_params.breakout_atr_buffer": 0.48,
            "strategy_params.cooldown_bars": 4,
            "filters.adx_floor": 24,
            "money_management.stake_scale.sol_long": 0.50,
            "money_management.take_profit_pct": 1.08,
            "money_management.trailing_profit.activation_pnl_pct": 0.30,
            "money_management.trailing_profit.giveback_ratio": 0.18,
        },
        track="sol_pullback_core",
        anchor_name=_name(sol_pullback),
        playbook="sol_pullback_core",
    )
    add(
        sol_pullback,
        name="sol_pullback_pair_long_adx22_cd3_lb18_zone022_s050",
        note="SOL stage196：dense long 只留 1 条，对照 short。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 18,
            "strategy_params.breakout_atr_buffer": 0.50,
            "strategy_params.cooldown_bars": 3,
            "filters.adx_floor": 22,
            "money_management.stake_scale.sol_long": 0.48,
            "money_management.take_profit_pct": 1.10,
            "money_management.trailing_profit.activation_pnl_pct": 0.30,
            "money_management.trailing_profit.giveback_ratio": 0.18,
        },
        track="sol_pullback_dense",
        anchor_name=_name(sol_pullback),
        playbook="sol_pullback_dense",
    )
    add(
        sol_short,
        name="sol_guarded_short_accel_lb13_atr050_adx17_cd1_s078",
        note="SOL stage196：short balance，优先看 WF。",
        family="short",
        patch={
            "strategy_params.breakout_lookback": 13,
            "strategy_params.breakout_atr_buffer": 0.50,
            "strategy_params.cooldown_bars": 1,
            "filters.adx_floor": 17,
            "money_management.stake_scale.sol_short": 0.64,
            "money_management.take_profit_pct": 0.90,
            "money_management.trailing_profit.activation_pnl_pct": 0.26,
            "money_management.trailing_profit.giveback_ratio": 0.16,
        },
        track="sol_short_balance",
        anchor_name=_name(sol_short),
        playbook="sol_short_balance",
    )
    add(
        sol_short,
        name="sol_guarded_short_accel_lb11_atr048_adx15_cd1_s082",
        note="SOL stage196：short relay，更快但仍保 guard。",
        family="short",
        patch={
            "strategy_params.breakout_lookback": 11,
            "strategy_params.breakout_atr_buffer": 0.48,
            "strategy_params.cooldown_bars": 1,
            "filters.adx_floor": 15,
            "money_management.stake_scale.sol_short": 0.66,
            "money_management.take_profit_pct": 0.88,
            "money_management.trailing_profit.activation_pnl_pct": 0.24,
            "money_management.trailing_profit.giveback_ratio": 0.16,
        },
        track="sol_short_relay",
        anchor_name=_name(sol_short),
        playbook="sol_short_relay",
    )
    return out


def _write_report(path_txt: Path, path_json: Path, main_rows: list[dict[str, Any]], branch_rows: list[dict[str, Any]], repaired_main: list[str], repaired_branch: list[str], scanned_main: list[str], scanned_branch: list[str], runtime_anchor: dict[str, Any], asset_summary: list[dict[str, Any]]) -> dict[str, Any]:
    active_map = _asset_active_map(asset_summary)
    main_payload = _top_payload(main_rows, runtime_anchor, active_map, branch=False)
    branch_payload = _top_payload(branch_rows, runtime_anchor, active_map, branch=True)
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
        "asset_summary": asset_summary,
        "main_top": _select_top(main_payload, limit=3),
        "branch_by_symbol": {sym: _select_top(branch_payload, symbol=sym, limit=5) for sym in ["btc", "eth", "sol"]},
    }

    lines: list[str] = []
    lines.append("Stage196 eth-sol reclaim/short frontier")
    lines.append("")
    lines.append("[summary]")
    lines.append(f"- target_monthly_floor={TARGET_MONTHLY_MIN*100:.2f}% target_monthly_ceiling={TARGET_MONTHLY_MAX*100:.2f}%")
    lines.append(f"- repaired_main={len(repaired_main)} repaired_branch={len(repaired_branch)}")
    lines.append(f"- scanned_main={len(scanned_main)} scanned_branch={len(scanned_branch)}")
    lines.append(f"- stage91_active={json.dumps(active_map, ensure_ascii=False)}")
    lines.append(f"- split_recommendation={split_rec}")
    lines.append("")
    lines.append("[focus]")
    lines.append("- 主线: 继续冻结，不浪费算力刷弱邻域。")
    lines.append("- BTC: 只保已有参考腿，不新增扫描。")
    lines.append("- ETH: reclaim_pair + squeeze relay 主攻，short 只留 1 条。")
    lines.append("- SOL: long 缩到 2 条，short 提到 2 条，优先看 WF 月化。")
    lines.append("")
    lines.append("[main_top]")
    for row in summary["main_top"]:
        lines.append(
            f"- {row['name']} | playbook={row['playbook']} | status={row['status']} | 6年={row['full_ret']*100:.2f}% | 近2年月化={row['recent_monthly']*100:.2f}% | WF月化={row['wf_monthly']*100:.2f}% | gap_to_7.6={row['gap_to_floor']*100:.2f}%"
        )
    lines.append("")
    for sym in ["eth", "sol", "btc"]:
        lines.append(f"[{sym}_top]")
        for row in summary["branch_by_symbol"][sym]:
            lines.append(
                f"- {row['name']} | playbook={row['playbook']} | status={row['status']} | 近2年={row['recent_ret']*100:.2f}% | 近2年月化={row['recent_monthly']*100:.2f}% | WF={row['wf_ret']*100:.2f}% | WF月化={row['wf_monthly']*100:.2f}% | 近2年交易={row['recent_trades']} | WF交易={row['wf_trades']} | gap_to_7.6={row['gap_to_floor']*100:.2f}%"
            )
        lines.append("")
    lines.append("[conclusion]")
    lines.append("- 主线继续保持 fix8_lock18。")
    lines.append("- ETH 这轮只围绕 reclaim_pair 与 squeeze relay 收窄。")
    lines.append("- SOL 这轮明确让 short 与 long 并列验证。")
    lines.append("- 继续 1 个 branch 终端。")
    txt = "\n".join(lines).rstrip() + "\n"
    path_txt.write_text(txt, encoding="utf-8")
    path_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage196 eth-sol reclaim/short frontier")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    raw = root / "reports" / "research_raw"
    raw.mkdir(parents=True, exist_ok=True)

    main_rows, branch_rows, repaired_main, repaired_branch = s141._load_stage_state(raw)
    cfg = s186._load_live_cfg(root)
    initial_equity = float(cfg.get("portfolio", {}).get("initial_equity", 100000.0))
    runtime_anchor = s186._parse_runtime_anchor(root)

    item_map = _merge_item_map(s88._mainline_items(), main_rows)
    ref_item = item_map.get("mainline_live_dynlev_fix8_lock18") or item_map.get("mainline_live_base")
    if ref_item is None:
        raise SystemExit("missing mainline reference")

    # stage197 hotfix: stage196 主线本来就是冻结参考，不该在导出前再次重跑主线。
    # 之前这里重跑 mainline，会在用户本机 raw 时间范围短暂不一致时直接触发
    # 「共同区间数据不足」，把整轮 frontier 卡死。这里改为优先吃现有 stage90 行。
    preferred_names = [str(ref_item.get("name") or ""), "mainline_live_dynlev_fix8_lock18", "mainline_live_base"]
    ref_row = _pick_mainline_ref(main_rows, preferred_names)
    full_end = _coerce_full_end(ref_row)
    ref_row = s161._ensure_mainline_row(ref_row, ref_row, initial_equity, full_end)
    print(f"[stage197] reuse mainline anchor: {ref_row.get('name')}", flush=True)

    main_map = {str(r.get("name")): s161._ensure_mainline_row(r, ref_row, initial_equity, full_end) for r in main_rows}
    main_rows = s161._finalize_rows(list(main_map.values()), branch=False)
    scanned_main: list[str] = []

    branch_map = {str(r.get("name")): s161._ensure_branch_row(r, initial_equity) for r in branch_rows}
    scanned_branch: list[str] = []
    for item in _branch_items(branch_rows):
        print(f"[stage196] branch {item['name']}", flush=True)
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

    asset_summary = _load_asset_summary(branch_json)

    frontier_txt = raw / "stage196_eth_sol_reclaim_short_frontier_latest.txt"
    frontier_json = raw / "stage196_eth_sol_reclaim_short_frontier_latest.json"
    summary = _write_report(frontier_txt, frontier_json, main_rows, branch_rows, repaired_main, repaired_branch, scanned_main, scanned_branch, runtime_anchor, asset_summary)
    manifest = {
        "mode": "eth_sol_reclaim_short_frontier",
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
    manifest_path = raw / "stage196_eth_sol_reclaim_short_frontier_manifest_latest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    s141._mirror_to_workspace(root, [main_txt, main_json, branch_txt, branch_json, frontier_txt, frontier_json, manifest_path])

    out_zip = root.parent / "Downloads" / "stage196_eth_sol_reclaim_short_frontier_latest.zip"
    WRITE_SINGLE_ZIP(out_zip, {
        "stage196_eth_sol_reclaim_short_frontier_latest.txt": frontier_txt,
        "stage196_eth_sol_reclaim_short_frontier_latest.json": frontier_json,
        "stage196_eth_sol_reclaim_short_frontier_manifest_latest.json": manifest_path,
        "stage90_mainline_event_alpha_matrix_latest.txt": main_txt,
        "stage90_mainline_event_alpha_matrix_latest.json": main_json,
        "stage91_branch_event_alpha_matrix_latest.txt": branch_txt,
        "stage91_branch_event_alpha_matrix_latest.json": branch_json,
    })
    print(out_zip)


if __name__ == "__main__":
    main()
