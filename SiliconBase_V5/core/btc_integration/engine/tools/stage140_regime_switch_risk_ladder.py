from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import research_config_baseline as rcb
from tools import stage46_aggressive_lab as s46
from tools import stage77_mainline_dual_window_lab as s77
from tools import stage78_branch_dual_window_lab as s78
from tools import stage81_mainline_walkforward_lab as s81
from tools import stage82_branch_walkforward_lab as s82
from tools import stage88_strategy_fusion_walkforward as s88
from tools import stage90_event_alpha_matrix as s90
from tools import stage136_regime_plateau_frontier as s136
from tools import stage138_anchor_guard_refresh as s138
from tools import stage139_microstructure_confluence_frontier as s139

TARGET_MONTHLY_MIN = s136.TARGET_MONTHLY_MIN
TARGET_MONTHLY_MAX = s136.TARGET_MONTHLY_MAX
PACKS = s136.PACKS


HISTORY_FILES = [
    "stage138_anchor_guard_refresh_latest.json",
    "stage136_regime_plateau_frontier_latest.json",
]


def _with_meta(item: dict[str, Any], *, track: str, branch: bool, risk_scale: float = 1.0, anchor_name: str | None = None) -> dict[str, Any]:
    out = s136._with_meta(item, track=track, branch=branch)
    out.setdefault("meta", {})
    out["meta"]["risk_scale"] = float(risk_scale)
    out["meta"]["anchor_name"] = str(anchor_name or item.get("name") or "")
    return out


def _add_meta(item: dict[str, Any] | None, *, track: str, branch: bool, risk_scale: float = 1.0, anchor_name: str | None = None) -> dict[str, Any] | None:
    if item is None:
        return None
    out = copy.deepcopy(item)
    out.setdefault("meta", {})
    out["meta"]["track"] = track
    out["meta"]["risk_scale"] = float(risk_scale)
    out["meta"]["anchor_name"] = str(anchor_name or out.get("name") or "")
    return out



def _mainline_items() -> list[dict[str, Any]]:
    item_map = {str(item.get("name")): item for item in s88._mainline_items()}
    out: dict[str, dict[str, Any]] = {}

    def add(item: dict[str, Any] | None, *, track: str = "base", risk_scale: float = 1.0, anchor_name: str | None = None) -> None:
        if item is not None:
            name = str(item.get("name"))
            out[name] = _with_meta(item, track=track, branch=False, risk_scale=risk_scale, anchor_name=anchor_name or name)

    anchor = item_map.get("mainline_live_dynlev_fix8_lock18")
    add(anchor, track="base", risk_scale=1.0, anchor_name="mainline_live_dynlev_fix8_lock18")
    add(item_map.get("mainline_core_satellite_dynlev_fix8_lock18"), track="base", risk_scale=1.0, anchor_name="mainline_core_satellite_dynlev_fix8_lock18")
    if anchor is not None:
        add(
            s88._make_mainline_variant(
                anchor,
                name="mainline_live_dynlev_fix8_lock18_lev10_rr032",
                note="主线风险阶梯中档：不动结构，只轻提杠杆上限并稍提 trailing 效率。",
                patch={
                    "portfolio.dynamic_leverage.max": 10.0,
                    "money_management.take_profit_pct": 1.60,
                    "money_management.trailing_profit.activation_pnl_pct": 0.60,
                    "money_management.trailing_profit.giveback_ratio": 0.32,
                    "money_management.trailing_profit.min_lock_pnl_pct": 0.16,
                },
            ),
            track="base",
            risk_scale=1.20,
            anchor_name="mainline_live_dynlev_fix8_lock18",
        )
    return list(out.values())



def _branch_items() -> list[dict[str, Any]]:
    item_map = {str(item.get("name")): item for item in s139._branch_items()}
    out: dict[str, dict[str, Any]] = {}

    def add(item: dict[str, Any] | None, *, track: str, risk_scale: float = 1.0, anchor_name: str | None = None) -> None:
        if item is None:
            return
        name = str(item.get("name"))
        out[name] = _add_meta(item, track=track, branch=True, risk_scale=risk_scale, anchor_name=anchor_name or name)  # type: ignore[assignment]

    eth_squeeze = item_map.get("eth_squeeze_follow_long_lb10_atr042_adx16_s046")
    eth_drift = item_map.get("eth_event_drift_long_lb10_atr044_adx16_s046")
    eth_drift_cons = item_map.get("eth_event_drift_long_lb12_atr046_adx18_s042")
    eth_short = item_map.get("eth_retest_short_trend_lb20_atr060_adx24_s068")
    btc_long = item_map.get("btc_breakout_long_event_lb20_atr060_adx24_s050")
    btc_dual = item_map.get("btc_dual_fast_trend_dynlev_fix8")

    add(eth_squeeze, track="squeeze", risk_scale=1.0, anchor_name="eth_squeeze_follow_long_lb10_atr042_adx16_s046")
    add(eth_drift, track="drift", risk_scale=1.0, anchor_name="eth_event_drift_long_lb10_atr044_adx16_s046")
    add(eth_drift_cons, track="drift", risk_scale=0.91, anchor_name="eth_event_drift_long_lb10_atr044_adx16_s046")
    add(eth_short, track="reclaim", risk_scale=1.0, anchor_name="eth_retest_short_trend_lb20_atr060_adx24_s068")
    add(btc_long, track="drift", risk_scale=1.0, anchor_name="btc_breakout_long_event_lb20_atr060_adx24_s050")
    add(btc_dual, track="base", risk_scale=1.0, anchor_name="btc_dual_fast_trend_dynlev_fix8")

    if eth_squeeze is not None:
        add(
            s88._make_variant(
                eth_squeeze,
                name="eth_squeeze_follow_long_lb10_atr042_adx16_s058",
                note="ETH squeeze 中档风险阶梯：信号不变，只提升 stake。",
                family="long",
                patch={"money_management.stake_scale.eth_long": 0.58},
            ),
            track="squeeze",
            risk_scale=0.58 / 0.46,
            anchor_name="eth_squeeze_follow_long_lb10_atr042_adx16_s046",
        )
        add(
            s88._make_variant(
                eth_squeeze,
                name="eth_squeeze_follow_long_lb10_atr042_adx16_s070",
                note="ETH squeeze 激进风险阶梯：只看近2年/WF 能否同步抬升。",
                family="long",
                patch={"money_management.stake_scale.eth_long": 0.70},
            ),
            track="squeeze",
            risk_scale=0.70 / 0.46,
            anchor_name="eth_squeeze_follow_long_lb10_atr042_adx16_s046",
        )

    if eth_drift is not None:
        add(
            s88._make_variant(
                eth_drift,
                name="eth_event_drift_long_lb10_atr044_adx16_s058",
                note="ETH drift 中档风险阶梯：保留 1-3 根扩散逻辑，只提预算。",
                family="long",
                patch={"money_management.stake_scale.eth_long": 0.58},
            ),
            track="drift",
            risk_scale=0.58 / 0.46,
            anchor_name="eth_event_drift_long_lb10_atr044_adx16_s046",
        )
        add(
            s88._make_variant(
                eth_drift,
                name="eth_event_drift_long_lb10_atr044_adx16_s070",
                note="ETH drift 激进风险阶梯：只在样本不塌时允许上提。",
                family="long",
                patch={"money_management.stake_scale.eth_long": 0.70},
            ),
            track="drift",
            risk_scale=0.70 / 0.46,
            anchor_name="eth_event_drift_long_lb10_atr044_adx16_s046",
        )

    if eth_short is not None:
        add(
            s88._make_variant(
                eth_short,
                name="eth_retest_short_trend_lb20_atr060_adx24_s078",
                note="ETH 空腿风险阶梯：不改 reclaim 逻辑，只提 stake 做检验。",
                family="short",
                patch={"money_management.stake_scale.eth_short": 0.78},
            ),
            track="reclaim",
            risk_scale=0.78 / 0.68,
            anchor_name="eth_retest_short_trend_lb20_atr060_adx24_s068",
        )

    if btc_long is not None:
        add(
            s88._make_variant(
                btc_long,
                name="btc_breakout_long_event_lb20_atr060_adx24_s062",
                note="BTC 长腿中档风险阶梯：保持事件突破逻辑，只提预算。",
                family="long",
                patch={"money_management.stake_scale.btc_long": 0.62},
            ),
            track="drift",
            risk_scale=0.62 / 0.50,
            anchor_name="btc_breakout_long_event_lb20_atr060_adx24_s050",
        )
        add(
            s88._make_variant(
                btc_long,
                name="btc_breakout_long_event_lb20_atr060_adx24_s074",
                note="BTC 长腿激进风险阶梯：只看月化能否抬起且 DD 不穿。",
                family="long",
                patch={"money_management.stake_scale.btc_long": 0.74},
            ),
            track="drift",
            risk_scale=0.74 / 0.50,
            anchor_name="btc_breakout_long_event_lb20_atr060_adx24_s050",
        )

    return list(out.values())



def _anchor_name(row: dict[str, Any]) -> str:
    return str((row.get("meta") or {}).get("anchor_name") or row.get("name") or "")



def _risk_scale(row: dict[str, Any]) -> float:
    return max(0.0, s88._safe_float((row.get("meta") or {}).get("risk_scale") or 1.0))



def _row_by_name(rows: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for row in rows:
        if str(row.get("name") or "") == name:
            return row
    return None



def _repair_rows_from_history(raw: Path, rows: list[dict[str, Any]], *, key: str) -> tuple[list[dict[str, Any]], list[str]]:
    source_maps: list[dict[str, dict[str, Any]]] = []
    for fname in HISTORY_FILES:
        p = raw / fname
        if p.exists():
            try:
                payload = s138._load_json(p)
                source_maps.append(s138._frontier_map(payload, key))
            except Exception:
                continue
    fixed: list[dict[str, Any]] = []
    repaired: list[str] = []
    for row in rows:
        name = str(row.get("name") or "")
        prev = None
        for mp in source_maps:
            cand = mp.get(name)
            if isinstance(cand, dict) and (int(cand.get("recent_trades", 0) or 0) > 0 or int(cand.get("wf_trades", 0) or 0) > 0):
                prev = cand
                break
        if s138._is_zero_anomaly(row, prev):
            fixed.append(s138._patch_row_from_payload(row, prev))
            repaired.append(name)
        else:
            fixed.append(copy.deepcopy(row))
    return fixed, repaired



def _frontier_score(row: dict[str, Any], rows: list[dict[str, Any]], *, branch: bool) -> float:
    score = s139._frontier_score(row, rows, branch=branch)
    dom = row.get("dominant_gate", {}) or {}
    recent = dom.get("recent_metrics", {}) or {}
    wf = (row.get("walkforward") or {}).get("metrics", {}) or {}
    track = str((row.get("meta") or {}).get("track") or "base")
    month = s136._target_monthly(row, branch=branch)
    recent_trades = int(recent.get("trades", 0) or 0)
    wf_trades = int(wf.get("trades", 0) or 0)
    recent_pf = s88._safe_float(recent.get("pf"))
    wf_pf = s88._safe_float(wf.get("pf"))
    wf_dd = abs(s88._safe_float(wf.get("maxdd")))
    risk_scale = _risk_scale(row)
    anchor = _row_by_name(rows, _anchor_name(row))

    bonus = 0.0
    penalty = 0.0

    if month >= 0.02 and recent_trades >= (18 if branch else 24) and wf_trades >= (12 if branch else 10):
        bonus += 28.0 if branch else 16.0
    if month >= 0.03 and recent_pf >= 1.6 and wf_pf >= 1.3:
        bonus += 20.0 if branch else 12.0

    if branch:
        sym = str(row.get("symbol") or "").lower()
        fam = str(row.get("family") or "").lower()
        if sym == "eth" and fam == "long" and track in {"squeeze", "drift"}:
            if recent_trades >= 24 and wf_trades >= 16 and recent_pf >= 2.2 and wf_pf >= 1.6:
                bonus += month * 12000.0
            if risk_scale > 1.0 and month >= 0.018 and wf_dd <= 0.05:
                bonus += 8.0 * min(risk_scale, 1.7)
        if sym == "btc" and fam == "long" and recent_trades >= 14 and wf_trades >= 10 and recent_pf >= 1.3 and wf_pf >= 1.15:
            bonus += month * 9000.0
        if sym == "eth" and fam == "short" and wf_trades >= 10 and wf_pf >= 1.1:
            bonus += month * 5000.0

    if anchor is not None and str(anchor.get("name")) != str(row.get("name")):
        a_dom = anchor.get("dominant_gate", {}) or {}
        a_recent = a_dom.get("recent_metrics", {}) or {}
        a_wf = (anchor.get("walkforward") or {}).get("metrics", {}) or {}
        a_month = s136._target_monthly(anchor, branch=branch)
        a_recent_trades = int(a_recent.get("trades", 0) or 0)
        a_wf_trades = int(a_wf.get("trades", 0) or 0)
        a_recent_pf = max(0.01, s88._safe_float(a_recent.get("pf")))
        a_wf_pf = max(0.01, s88._safe_float(a_wf.get("pf")))
        a_wf_dd = abs(s88._safe_float(a_wf.get("maxdd")))
        month_delta = month - a_month
        trade_ok = recent_trades >= max(4, int(a_recent_trades * 0.75)) and wf_trades >= max(4, int(a_wf_trades * 0.75))
        pf_ok = recent_pf >= a_recent_pf * 0.72 and wf_pf >= a_wf_pf * 0.72
        dd_ok = wf_dd <= a_wf_dd + (0.03 if branch else 0.04)
        if month_delta > 0 and trade_ok and pf_ok and dd_ok:
            bonus += month_delta * (18000.0 if branch else 12000.0)
            bonus += 10.0 * max(0.0, risk_scale - 1.0)
        else:
            if month_delta < -0.001:
                penalty += abs(month_delta) * (14000.0 if branch else 9000.0)
            if risk_scale > 1.10 and (not pf_ok or not dd_ok):
                penalty += 22.0 if branch else 12.0
            if risk_scale > 1.40 and (wf_pf < 1.10 or wf_dd > a_wf_dd + 0.02):
                penalty += 28.0 if branch else 16.0

    if risk_scale > 1.50 and month < 0.012:
        penalty += 18.0 if branch else 12.0

    return float(score + bonus - penalty)



def _finalize_rows(rows: list[dict[str, Any]], *, branch: bool) -> list[dict[str, Any]]:
    for row in rows:
        row["plateau"] = s136._plateau_summary(row, rows, branch=branch)
    for row in rows:
        row["alpha_score"] = _frontier_score(row, rows, branch=branch)
        row["decision"] = s136._frontier_label(row, branch=branch)
    rows.sort(key=lambda r: float(r.get("alpha_score", 0.0)), reverse=True)
    return rows



def _write_report(path_txt: Path, path_json: Path, main_rows: list[dict[str, Any]], branch_rows: list[dict[str, Any]], repaired_main: list[str], repaired_branch: list[str]) -> None:
    main_payload = [s136._payload_row(r, branch=False) for r in main_rows]
    branch_payload = [s136._payload_row(r, branch=True) for r in branch_rows]
    lines: list[str] = []
    lines.append("Stage140 状态切换 + 风险阶梯前沿")
    lines.append("原则：主信号不变，只围绕已验证锚点做风险阶梯；funding/OI/波动率/put-skew 只做状态机输入，不单独硬开仓。")
    lines.append(f"目标区间：{TARGET_MONTHLY_MIN*100:.1f}% - {TARGET_MONTHLY_MAX*100:.1f}% / 月")
    lines.append("")
    if repaired_main or repaired_branch:
        lines.append(f"- 异常回退: main={len(repaired_main)} | branch={len(repaired_branch)}")
        if repaired_main:
            lines.append(f"- 主线回退: {', '.join(repaired_main)}")
        if repaired_branch:
            lines.append(f"- 分支回退: {', '.join(repaired_branch)}")
        lines.append("")
    lines.append("=== 主线 ===")
    for row in main_rows:
        p = s136._payload_row(row, branch=False)
        lines.append(
            f"- {p['name']}: track={p['track']} | risk={_risk_scale(row):.2f} | target_monthly={p['target_monthly']*100:.2f}% | 近2年={p['recent_monthly']*100:.2f}%/{p['recent_trades']}笔/PF{p['recent_pf']:.3f} | WF={p['wf_monthly']*100:.2f}%/{p['wf_trades']}笔/PF{p['wf_pf']:.3f} | decision={p['decision']}"
        )
    lines.append("")
    lines.append("=== 分支（BTC/ETH） ===")
    for row in branch_rows:
        p = s136._payload_row(row, branch=True)
        sym = p.get("symbol") or "-"
        fam = p.get("family") or "-"
        lines.append(
            f"- {sym}|{fam}|{p['name']}: track={p['track']} | risk={_risk_scale(row):.2f} | anchor={_anchor_name(row)} | target_monthly={p['target_monthly']*100:.2f}% | 近2年={p['recent_monthly']*100:.2f}%/{p['recent_trades']}笔/PF{p['recent_pf']:.3f} | WF={p['wf_monthly']*100:.2f}%/{p['wf_trades']}笔/PF{p['wf_pf']:.3f} | decision={p['decision']}"
        )
    lines.append("")
    lines.append("=== 结论 ===")
    if main_payload:
        top = main_payload[0]
        lines.append(f"- 主线当前第一名: {top['name']} | target_monthly={top['target_monthly']*100:.2f}% | gap_to_7.6={top['gap_to_floor']*100:.2f}%")
    if branch_payload:
        top = branch_payload[0]
        lines.append(f"- 分支当前第一名: {top['name']} | target_monthly={top['target_monthly']*100:.2f}% | gap_to_7.6={top['gap_to_floor']*100:.2f}%")
    lines.append("- 先看风险阶梯能否把 ETH/BTC 月化抬起来；抬不起来再换信号，不先乱砍路径。")
    lines.append("- 主线继续把 6 年当软约束，近 2 年 + WF 当硬约束。")

    path_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    path_json.write_text(
        json.dumps(
            {
                "mode": "regime_switch_risk_ladder",
                "target_monthly_min": TARGET_MONTHLY_MIN,
                "target_monthly_max": TARGET_MONTHLY_MAX,
                "repaired_main": repaired_main,
                "repaired_branch": repaired_branch,
                "packs": [x[0] for x in PACKS],
                "mainline": main_payload,
                "branch": branch_payload,
                "notes": {
                    "history_guard": HISTORY_FILES,
                    "focus": "risk_ladder_around_validated_anchors",
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )



def _mirror_to_workspace(root: Path, files: list[Path]) -> None:
    ws_raw = root / ".branch_shortwave_demo" / "workspace" / "reports" / "research_raw"
    if not ws_raw.parent.exists():
        return
    ws_raw.mkdir(parents=True, exist_ok=True)
    for p in files:
        if p.exists() and p.is_file():
            (ws_raw / p.name).write_bytes(p.read_bytes())



def main() -> None:
    ap = argparse.ArgumentParser(description="Stage140 regime switch risk ladder frontier")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    raw = root / "reports" / "research_raw"
    raw.mkdir(parents=True, exist_ok=True)

    cfg = rcb.load_research_base_config(root)
    initial_equity = float(cfg.get("portfolio", {}).get("initial_equity", 100000.0))

    data = s46._load_portfolio_data(root, cfg)
    full_start, full_end = s77._window_bounds_from_data(data)

    item_map_main = {str(item.get("name")): item for item in s88._mainline_items()}
    ref_item = item_map_main.get("mainline_live_base")
    if ref_item is None:
        raise SystemExit("missing mainline reference: mainline_live_base")
    ref_row = s136._run_mainline(root, cfg, data, _with_meta(ref_item, track="base", branch=False), initial_equity, full_start, full_end)

    main_rows: list[dict[str, Any]] = []
    main_items = _mainline_items()
    for i, item in enumerate(main_items, 1):
        print(f"[stage140] mainline {i}/{len(main_items)} {item['name']}", flush=True)
        row = s136._run_mainline(root, cfg, data, item, initial_equity, full_start, full_end)
        row["walkforward"] = s81._wf_result(row, ref_row, initial_equity, s81.RECENT_START, full_end)
        row["dominant_gate"] = s90._dominant_gate(row, branch=False)
        main_rows.append(row)

    branch_rows: list[dict[str, Any]] = []
    branch_items = _branch_items()
    for i, item in enumerate(branch_items, 1):
        print(f"[stage140] branch {i}/{len(branch_items)} {item['name']}", flush=True)
        row = s136._run_branch(root, cfg, item, initial_equity)
        row["walkforward"] = s82._wf_result(row, initial_equity, s78.RECENT_START, row["full_end"])
        row["dominant_gate"] = s90._dominant_gate(row, branch=True)
        branch_rows.append(row)

    main_rows, repaired_main = _repair_rows_from_history(raw, main_rows, key="mainline")
    branch_rows, repaired_branch = _repair_rows_from_history(raw, branch_rows, key="branch")
    main_rows = _finalize_rows(main_rows, branch=False)
    branch_rows = _finalize_rows(branch_rows, branch=True)

    main_txt = raw / "stage90_mainline_event_alpha_matrix_latest.txt"
    main_json = raw / "stage90_mainline_event_alpha_matrix_latest.json"
    branch_txt = raw / "stage91_branch_event_alpha_matrix_latest.txt"
    branch_json = raw / "stage91_branch_event_alpha_matrix_latest.json"
    s90._write_mainline(main_txt, main_json, main_rows)
    s90._write_branch(branch_txt, branch_json, branch_rows)

    frontier_txt = raw / "stage140_regime_switch_risk_ladder_latest.txt"
    frontier_json = raw / "stage140_regime_switch_risk_ladder_latest.json"
    _write_report(frontier_txt, frontier_json, main_rows, branch_rows, repaired_main, repaired_branch)

    manifest = {
        "mode": "regime_switch_risk_ladder",
        "packs": [x[0] for x in PACKS],
        "history_guard": HISTORY_FILES,
        "mainline_names": [str(x.get("name")) for x in main_items],
        "branch_names": [str(x.get("name")) for x in branch_items],
        "repaired_main": repaired_main,
        "repaired_branch": repaired_branch,
        "outputs": {
            "stage90_txt": str(main_txt),
            "stage90_json": str(main_json),
            "stage91_txt": str(branch_txt),
            "stage91_json": str(branch_json),
            "frontier_txt": str(frontier_txt),
            "frontier_json": str(frontier_json),
        },
    }
    manifest_path = raw / "stage140_regime_switch_risk_ladder_manifest_latest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    _mirror_to_workspace(root, [main_txt, main_json, branch_txt, branch_json, frontier_txt, frontier_json, manifest_path])

    print(main_txt)
    print(main_json)
    print(branch_txt)
    print(branch_json)
    print(frontier_txt)
    print(frontier_json)
    print(manifest_path)


if __name__ == "__main__":
    main()
