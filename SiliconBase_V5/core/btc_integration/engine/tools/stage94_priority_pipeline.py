from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any

import pandas as pd

SYMS = ["btc", "bnb", "eth", "sol"]


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
    except Exception:
        return default
    if math.isnan(v):
        return default
    return v


def _fmt_pct(x: Any) -> str:
    try:
        return f"{float(x) * 100:.2f}%"
    except Exception:
        return "NA"


def _fmt_num(x: Any, nd: int = 3) -> str:
    try:
        return f"{float(x):.{nd}f}"
    except Exception:
        return "NA"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _read_rows(path: Path) -> list[dict[str, Any]]:
    obj = _load_json(path)
    rows = obj.get("rows") if isinstance(obj, dict) else None
    return rows if isinstance(rows, list) else []


def _extract_line(text: str, label: str) -> str:
    m = re.search(rf"- {re.escape(label)}: (.+)", text)
    return m.group(1).strip() if m else ""


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _parse_demo_report(path: Path) -> dict[str, Any]:
    txt = _read_text(path)
    if not txt:
        return {}
    return {
        "path": str(path),
        "version": _extract_line(txt, "当前版本"),
        "state": _extract_line(txt, "当前状态"),
        "reason": _extract_line(txt, "状态原因"),
        "heartbeat": _extract_line(txt, "报告心跳(UTC+8)"),
        "next_run": _extract_line(txt, "下一轮执行(UTC+8)"),
        "latest_kline": _extract_line(txt, "最近已完成 15m K 线开盘(UTC+8)"),
        "signal_time": _extract_line(txt, "最近策略信号时间(UTC+8)"),
        "fills_started": _extract_line(txt, "策略真实成交已开始"),
        "realized": _extract_line(txt, "策略累计已实现收益"),
        "total_pnl": _extract_line(txt, "策略当前总收益"),
        "risk_mode": _extract_line(txt, "当前模式"),
        "risk_trigger": _extract_line(txt, "触发原因"),
    }


def _kline_stats(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False}
    try:
        df = pd.read_csv(path)
    except Exception:
        return {"exists": True, "error": True}
    if df.empty or "time" not in df.columns:
        return {"exists": True, "rows": int(len(df)), "latest": None}
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    df = df.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)
    if df.empty:
        return {"exists": True, "rows": 0, "latest": None}
    latest = pd.Timestamp(df["time"].iloc[-1]).tz_localize(None)
    start14 = latest - pd.Timedelta(days=14)
    recent = df.loc[df["time"] >= start14].copy()
    expected = pd.date_range(start=recent["time"].min(), end=latest, freq="15min") if not recent.empty else pd.DatetimeIndex([])
    actual = pd.DatetimeIndex(pd.to_datetime(recent["time"], errors="coerce")).dropna().unique().sort_values()
    missing = int(max(len(expected) - len(actual), 0)) if len(expected) else None
    for c in ("open", "high", "low", "close"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    daily = df.set_index("time").resample("1D").agg({"high": "max", "low": "min", "close": "last"}).dropna()
    daily["range"] = (daily["high"] - daily["low"]) / daily["close"].replace(0, pd.NA)
    d7 = daily.tail(7)
    return {
        "exists": True,
        "rows": int(len(df)),
        "latest": latest.strftime("%Y-%m-%d %H:%M:%S"),
        "last14_missing": missing,
        "max_range_7d": _safe_float(d7["range"].max()) if not d7.empty else None,
        "avg_range_7d": _safe_float(d7["range"].mean()) if not d7.empty else None,
    }


def _full_metrics(row: dict[str, Any]) -> dict[str, Any]:
    return row.get("full_metrics") or {}


def _recent_metrics(row: dict[str, Any]) -> dict[str, Any]:
    dom = row.get("dominant_gate") or {}
    return dom.get("recent_metrics") or {}


def _wf_metrics(row: dict[str, Any]) -> dict[str, Any]:
    wf = row.get("walkforward") or {}
    return wf.get("metrics") or {}


def _mainline_summary(row: dict[str, Any]) -> dict[str, Any]:
    full_m = _full_metrics(row)
    recent_m = _recent_metrics(row)
    wf_m = _wf_metrics(row)
    return {
        "name": str(row.get("name") or ""),
        "decision": str(row.get("decision") or ""),
        "alpha_score": _safe_float(row.get("alpha_score")),
        "full_ret": _safe_float(full_m.get("ret")),
        "full_pf": _safe_float(full_m.get("pf")),
        "full_trades": int(full_m.get("trades") or 0),
        "recent_ret": _safe_float(recent_m.get("ret")),
        "recent_pf": _safe_float(recent_m.get("pf")),
        "recent_trades": int(recent_m.get("trades") or 0),
        "wf_ret": _safe_float(wf_m.get("ret")),
        "wf_pf": _safe_float(wf_m.get("pf")),
        "wf_trades": int(wf_m.get("trades") or 0),
        "wf_maxdd": _safe_float(wf_m.get("maxdd")),
    }


def _branch_summary(row: dict[str, Any]) -> dict[str, Any]:
    full_m = _full_metrics(row)
    recent_m = _recent_metrics(row)
    wf_m = _wf_metrics(row)
    return {
        "symbol": str(row.get("symbol") or "").lower(),
        "family": str(row.get("family") or "").lower(),
        "lane": f"{str(row.get('symbol') or '').lower()}_{str(row.get('family') or '').lower()}",
        "name": str(row.get("name") or ""),
        "decision": str(row.get("decision") or ""),
        "alpha_score": _safe_float(row.get("alpha_score")),
        "full_ret": _safe_float(full_m.get("ret")),
        "full_pf": _safe_float(full_m.get("pf")),
        "full_trades": int(full_m.get("trades") or 0),
        "recent_ret": _safe_float(recent_m.get("ret")),
        "recent_pf": _safe_float(recent_m.get("pf")),
        "recent_trades": int(recent_m.get("trades") or 0),
        "wf_ret": _safe_float(wf_m.get("ret")),
        "wf_pf": _safe_float(wf_m.get("pf")),
        "wf_trades": int(wf_m.get("trades") or 0),
        "wf_maxdd": _safe_float(wf_m.get("maxdd")),
    }


def _pick_mainline(rows: list[dict[str, Any]]) -> dict[str, Any]:
    items = [_mainline_summary(r) for r in rows]
    if not items:
        return {"live": {}, "balanced": {}, "aggressive": {}, "rows": []}
    live = next((x for x in items if x["name"] == "mainline_live_base"), items[0])
    others = [x for x in items if x["name"] != live["name"]]
    balanced_pool = [
        x for x in others
        if x["recent_trades"] >= live["recent_trades"] + 20
        and x["recent_pf"] >= live["recent_pf"] - 0.30
        and x["wf_pf"] >= 1.70
    ]
    aggressive_pool = [
        x for x in others
        if x["recent_trades"] >= live["recent_trades"] + 35
        and x["recent_pf"] >= 2.15
        and x["wf_pf"] >= 1.60
    ]
    def _rank_bal(x: dict[str, Any]) -> tuple[float, float, float, int]:
        return (x["alpha_score"], x["recent_pf"], x["wf_pf"], x["recent_trades"])
    def _rank_aggr(x: dict[str, Any]) -> tuple[int, float, float, float]:
        return (x["recent_trades"], x["recent_pf"], x["wf_pf"], x["alpha_score"])
    balanced = sorted(balanced_pool or others, key=_rank_bal, reverse=True)[0] if others else {}
    aggressive = sorted(aggressive_pool or others, key=_rank_aggr, reverse=True)[0] if others else {}
    return {"live": live, "balanced": balanced, "aggressive": aggressive, "rows": items}


def _lane_status(x: dict[str, Any]) -> str:
    if x["recent_ret"] > 0 and x["wf_ret"] > 0 and x["wf_pf"] >= 1.15 and x["decision"] in {"pass", "hold"}:
        return "push"
    if x["recent_pf"] >= 0.95 or x["wf_pf"] >= 0.95:
        return "hold"
    return "rebuild"


def _lane_rank(x: dict[str, Any]) -> tuple[float, float, float, int, int]:
    positive = 0
    if x["recent_ret"] > 0:
        positive += 1
    if x["wf_ret"] > 0:
        positive += 1
    return (
        positive,
        x["wf_pf"] * 10.0 + x["recent_pf"] * 6.0 + x["alpha_score"] * 0.001,
        x["recent_ret"] + x["wf_ret"],
        x["wf_trades"],
        x["recent_trades"],
    )


def _pick_branch(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    items = [_branch_summary(r) for r in rows]
    out: dict[str, dict[str, Any]] = {}
    by_lane: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        by_lane.setdefault(item["lane"], []).append(item)
    for lane, lane_rows in by_lane.items():
        ranked = sorted(lane_rows, key=_lane_rank, reverse=True)
        lead = dict(ranked[0])
        lead["status"] = _lane_status(lead)
        reserves = [r["name"] for r in ranked[1:4]]
        lead["reserves"] = reserves
        out[lane] = lead
    return out


def _load_stage93(path: Path) -> dict[str, Any]:
    data = _load_json(path)
    return data if isinstance(data, dict) else {}


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage94 priority pipeline")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    raw = root / "reports" / "research_raw"
    raw.mkdir(parents=True, exist_ok=True)

    stage90_rows = _read_rows(raw / "stage90_mainline_event_alpha_matrix_latest.json")
    stage91_rows = _read_rows(raw / "stage91_branch_event_alpha_matrix_latest.json")
    if not stage90_rows or not stage91_rows:
        raise SystemExit("缺少 stage90/stage91 输出，请先跑 stage90_event_alpha_matrix。")

    main_pick = _pick_mainline(stage90_rows)
    branch_pick = _pick_branch(stage91_rows)
    stage93 = _load_stage93(raw / "stage93_frequency_accel_latest.json")
    okx_report = _parse_demo_report(Path.home() / "Downloads" / "okx_demo_report_latest.txt")
    branch_report = _parse_demo_report(Path.home() / "Downloads" / "branch_demo_report_latest.txt")

    kstats = {}
    for sym in SYMS:
        path = root / "data" / "raw" / f"{sym}_15m.csv"
        kstats[sym] = _kline_stats(path)

    lines: list[str] = []
    lines.append("Stage94 优先级收口")
    lines.append("规则：主线 live 先稳住；6年总样本只作软约束，判断以近2年 + WF 为主；Downloads 只保留 4 个固定文件。")
    lines.append("")
    lines.append("=== 当前 live 状态 ===")
    if okx_report:
        lines.append(
            f"- mainline: version={okx_report.get('version','-')} | state={okx_report.get('state','-')} | reason={okx_report.get('reason','-')} | latest_kline={okx_report.get('latest_kline','-')} | fills_started={okx_report.get('fills_started','-')}"
        )
    if branch_report:
        lines.append(
            f"- branch: version={branch_report.get('version','-')} | state={branch_report.get('state','-')} | reason={branch_report.get('reason','-')} | latest_kline={branch_report.get('latest_kline','-')} | fills_started={branch_report.get('fills_started','-')}"
        )
    lines.append("")
    lines.append("=== 主线优先级 ===")
    live = main_pick.get("live") or {}
    bal = main_pick.get("balanced") or {}
    aggr = main_pick.get("aggressive") or {}
    if live:
        lines.append(f"- keep_live: {live['name']} | 6年 PF={_fmt_num(live['full_pf'])} 交易={live['full_trades']} | 近2年 PF={_fmt_num(live['recent_pf'])} 交易={live['recent_trades']} | WF PF={_fmt_num(live['wf_pf'])} | {live['decision']}")
    if bal:
        lines.append(f"- shadow_balanced: {bal['name']} | 6年 PF={_fmt_num(bal['full_pf'])} 交易={bal['full_trades']} | 近2年 PF={_fmt_num(bal['recent_pf'])} 交易={bal['recent_trades']} | WF PF={_fmt_num(bal['wf_pf'])} | {bal['decision']}")
    if aggr:
        lines.append(f"- shadow_aggressive: {aggr['name']} | 6年 PF={_fmt_num(aggr['full_pf'])} 交易={aggr['full_trades']} | 近2年 PF={_fmt_num(aggr['recent_pf'])} 交易={aggr['recent_trades']} | WF PF={_fmt_num(aggr['wf_pf'])} | {aggr['decision']}")
    lines.append("- 结论: 主线先不切 live；先用 balanced/aggressive 两档 shadow 提频，消息面继续做 overlay/risk layer。")
    lines.append("")
    lines.append("=== 分支优先级 ===")
    lane_order = ["eth_short", "eth_long", "sol_long", "sol_short"]
    for lane in lane_order:
        row = branch_pick.get(lane)
        if not row:
            continue
        lines.append(
            f"- {lane}: {row['name']} | status={row['status']} | 6年 PF={_fmt_num(row['full_pf'])} 交易={row['full_trades']} | 近2年 PF={_fmt_num(row['recent_pf'])} 交易={row['recent_trades']} | WF PF={_fmt_num(row['wf_pf'])} | {row['decision']} | reserves={','.join(row.get('reserves') or []) or '-'}"
        )
    lines.append("- 结论: branch demo 继续 ETH short fast；ETH long / SOL long / SOL short 保留路径，不轻易砍路。")
    lines.append("")
    lines.append("=== K线与频率检查 ===")
    for sym in SYMS:
        st = kstats.get(sym) or {}
        if not st.get("exists"):
            lines.append(f"- {sym.upper()}: missing")
            continue
        lines.append(
            f"- {sym.upper()}: latest={st.get('latest','-')} | rows={st.get('rows','-')} | missing_14d={st.get('last14_missing','-')} | avg_range_7d={_fmt_pct(st.get('avg_range_7d'))} | max_range_7d={_fmt_pct(st.get('max_range_7d'))}"
        )
    lines.append("- 结论: 若 live/branch 仍长期 0 成交，而 7d 振幅不低，则问题优先归因于门槛过严，不是 K 线停更。")
    lines.append("")
    lines.append("=== 下一步 ===")
    lines.append(f"- mainline: keep {live.get('name','mainline_live_base')} ; shadow 重点看 {bal.get('name','-')} / {aggr.get('name','-')}")
    lines.append(f"- branch_demo: keep {branch_pick.get('eth_short',{}).get('name','eth_short_shock_fast_lb16_atr052_adx22_s078')}")
    lines.append(f"- rebuild_lanes: eth_long={branch_pick.get('eth_long',{}).get('name','-')} | sol_long={branch_pick.get('sol_long',{}).get('name','-')} | sol_short={branch_pick.get('sol_short',{}).get('name','-')}")
    if stage93:
        mainline = stage93.get("mainline") or {}
        if mainline:
            lines.append(f"- stage93_hint: balanced={((mainline.get('balanced') or {}).get('name')) or '-'} | aggressive={((mainline.get('aggressive') or {}).get('name')) or '-'}")
    txt_path = raw / "stage94_priority_pipeline_latest.txt"
    json_path = raw / "stage94_priority_pipeline_latest.json"
    txt_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    payload = {
        "mainline": main_pick,
        "branch": branch_pick,
        "okx_report": okx_report,
        "branch_report": branch_report,
        "kstats": kstats,
        "stage93": stage93,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(txt_path)
    print(json_path)


if __name__ == "__main__":
    main()
