from __future__ import annotations

import argparse
import json
import math
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
    data = _load_json(path)
    rows = data.get("rows") if isinstance(data, dict) else None
    return rows if isinstance(rows, list) else []


def _kline_stats(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "exists": False,
            "latest": None,
            "rows": 0,
            "last14_missing": None,
            "avg_range_7d": None,
            "max_range_7d": None,
            "avg_range_14d": None,
            "max_range_14d": None,
        }
    df = pd.read_csv(path)
    if df.empty or "time" not in df.columns:
        return {
            "exists": True,
            "latest": None,
            "rows": int(len(df)),
            "last14_missing": None,
            "avg_range_7d": None,
            "max_range_7d": None,
            "avg_range_14d": None,
            "max_range_14d": None,
        }
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    df = df.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)
    if df.empty:
        return {
            "exists": True,
            "latest": None,
            "rows": 0,
            "last14_missing": None,
            "avg_range_7d": None,
            "max_range_7d": None,
            "avg_range_14d": None,
            "max_range_14d": None,
        }
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
    d14 = daily.tail(14)
    return {
        "exists": True,
        "latest": latest.strftime("%Y-%m-%d %H:%M:%S"),
        "rows": int(len(df)),
        "last14_missing": missing,
        "avg_range_7d": _safe_float(d7["range"].mean()) if not d7.empty else None,
        "max_range_7d": _safe_float(d7["range"].max()) if not d7.empty else None,
        "avg_range_14d": _safe_float(d14["range"].mean()) if not d14.empty else None,
        "max_range_14d": _safe_float(d14["range"].max()) if not d14.empty else None,
    }


def _recent_metrics(row: dict[str, Any]) -> dict[str, Any]:
    return ((row.get("dominant_gate") or {}).get("recent_metrics") or {})


def _full_metrics(row: dict[str, Any]) -> dict[str, Any]:
    return (row.get("full_metrics") or {})


def _wf_metrics(row: dict[str, Any]) -> dict[str, Any]:
    return ((row.get("walkforward") or {}).get("metrics") or {})


def _mainline_row_summary(row: dict[str, Any]) -> dict[str, Any]:
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
    }


def _lane_key(row: dict[str, Any]) -> str:
    return f"{str(row.get('symbol')).lower()}_{str(row.get('family')).lower()}"


def _branch_row_summary(row: dict[str, Any]) -> dict[str, Any]:
    full_m = _full_metrics(row)
    recent_m = _recent_metrics(row)
    wf_m = _wf_metrics(row)
    return {
        "lane": _lane_key(row),
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
    }


def _pick_mainline(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary_rows = [_mainline_row_summary(r) for r in rows]
    base = next((r for r in summary_rows if r["name"] == "mainline_live_base"), summary_rows[0] if summary_rows else {})
    others = [r for r in summary_rows if r.get("name") != "mainline_live_base"]
    balanced_pool = [
        r for r in others
        if r["recent_trades"] > int(base.get("recent_trades", 0))
        and r["recent_pf"] >= float(base.get("recent_pf", 0.0)) - 0.28
        and r["wf_pf"] >= 1.65
    ]
    aggressive_pool = [
        r for r in others
        if r["recent_trades"] >= int(base.get("recent_trades", 0)) + 20
        and r["recent_pf"] >= 2.10
        and r["wf_pf"] >= 1.60
    ]
    balanced = sorted(balanced_pool or others, key=lambda r: (r["alpha_score"], r["recent_pf"], r["wf_pf"]), reverse=True)[0] if others else {}
    aggressive = sorted(aggressive_pool or others, key=lambda r: (r["recent_trades"], r["recent_pf"], r["wf_pf"]), reverse=True)[0] if others else {}
    return {"live": base, "balanced": balanced, "aggressive": aggressive, "rows": summary_rows}


def _branch_status(row: dict[str, Any]) -> str:
    if row["recent_ret"] > 0 and row["wf_ret"] > 0 and row["wf_pf"] >= 1.15 and row["decision"] in {"pass", "hold"}:
        return "push"
    if row["recent_ret"] > 0 and row["recent_pf"] >= 1.0:
        return "hold"
    return "rebuild"


def _pick_branch(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    summary_rows = [_branch_row_summary(r) for r in rows]
    by_lane: dict[str, list[dict[str, Any]]] = {}
    for row in summary_rows:
        by_lane.setdefault(row["lane"], []).append(row)
    out: dict[str, dict[str, Any]] = {}
    for lane, lane_rows in by_lane.items():
        lane_rows = sorted(lane_rows, key=lambda r: (r["alpha_score"], r["recent_pf"], r["wf_pf"]), reverse=True)
        lead = lane_rows[0]
        lead["status"] = _branch_status(lead)
        lead["reserve"] = [r["name"] for r in lane_rows[1:4]]
        out[lane] = lead
    return out


def _line_main(row: dict[str, Any]) -> str:
    return (
        f"{row.get('name','-')} | 6年 收益={_fmt_pct(row.get('full_ret'))} PF={_fmt_num(row.get('full_pf'))} 交易={int(row.get('full_trades',0))}"
        f" | 近2年 收益={_fmt_pct(row.get('recent_ret'))} PF={_fmt_num(row.get('recent_pf'))} 交易={int(row.get('recent_trades',0))}"
        f" | WF 收益={_fmt_pct(row.get('wf_ret'))} PF={_fmt_num(row.get('wf_pf'))} 交易={int(row.get('wf_trades',0))}"
    )


def _line_branch(row: dict[str, Any]) -> str:
    return (
        f"{row.get('name','-')} | status={row.get('status','-')} | 6年 收益={_fmt_pct(row.get('full_ret'))} PF={_fmt_num(row.get('full_pf'))}"
        f" | 近2年 收益={_fmt_pct(row.get('recent_ret'))} PF={_fmt_num(row.get('recent_pf'))} 交易={int(row.get('recent_trades',0))}"
        f" | WF 收益={_fmt_pct(row.get('wf_ret'))} PF={_fmt_num(row.get('wf_pf'))} 交易={int(row.get('wf_trades',0))}"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage93 频率推进摘要")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    raw = root / "reports" / "research_raw"
    raw.mkdir(parents=True, exist_ok=True)

    stage90_rows = _read_rows(raw / "stage90_mainline_event_alpha_matrix_latest.json")
    stage91_rows = _read_rows(raw / "stage91_branch_event_alpha_matrix_latest.json")
    if not stage90_rows or not stage91_rows:
        raise SystemExit("缺少 stage90/stage91 输出，请先跑主线/分支事件矩阵。")

    main_pick = _pick_mainline(stage90_rows)
    branch_pick = _pick_branch(stage91_rows)
    kstats = {sym: _kline_stats(root / "data" / "raw" / f"{sym}_15m.csv") for sym in SYMS}
    latest_values = [pd.Timestamp(v.get("latest")) for v in kstats.values() if v.get("latest")]
    global_latest = max(latest_values) if latest_values else None
    for st in kstats.values():
        if global_latest is not None and st.get("latest"):
            lag_hours = max((global_latest - pd.Timestamp(st["latest"])).total_seconds() / 3600.0, 0.0)
            st["lag_hours_vs_max"] = lag_hours
        else:
            st["lag_hours_vs_max"] = None

    lines: list[str] = []
    lines.append("Stage93 提频推进")
    lines.append("原则：6年必跑但只作软约束；判断以近2年 + WF 为主；主线先提频 shadow，再决定是否切 live；分支四腿都保留。")
    lines.append("")
    lines.append("=== 最近 K 线健康度 ===")
    for sym in SYMS:
        st = kstats[sym]
        if not st.get("exists"):
            lines.append(f"- {sym.upper()}: 缺数据")
            continue
        lag_hours = st.get("lag_hours_vs_max")
        lag_note = f" | 相对最新滞后={int(lag_hours)}h" if lag_hours is not None and lag_hours >= 1.0 else ""
        lines.append(
            f"- {sym.upper()}: latest={st.get('latest') or '-'} | rows={st.get('rows',0)} | 近14天缺口={st.get('last14_missing')}"
            f" | 7天平均振幅={_fmt_pct(st.get('avg_range_7d'))} | 7天最大振幅={_fmt_pct(st.get('max_range_7d'))}"
            f" | 14天平均振幅={_fmt_pct(st.get('avg_range_14d'))}{lag_note}"
        )
    lines.append("")
    lines.append("=== 主线 ===")
    lines.append(f"- live_keep: {_line_main(main_pick['live'])}")
    lines.append(f"- shadow_balanced: {_line_main(main_pick['balanced'])}")
    lines.append(f"- shadow_aggressive: {_line_main(main_pick['aggressive'])}")
    lines.append("- 结论: live 继续保留 mainline_live_base；提频 shadow 先同时跑 balanced 与 aggressive 两档，不直接替 live。")
    lines.append("")
    lines.append("=== 分支四腿 ===")
    for lane in ["eth_long", "eth_short", "sol_long", "sol_short"]:
        row = branch_pick.get(lane, {})
        if not row:
            lines.append(f"- {lane}: 缺结果")
            continue
        reserve = ",".join(row.get("reserve") or [])
        lines.append(f"- {lane}: {_line_branch(row)}")
        if reserve:
            lines.append(f"  reserve={reserve}")
    lines.append("")
    lines.append("=== 当前动作 ===")
    lines.append(f"- 主线 production: {main_pick['live'].get('name','mainline_live_base')}")
    lines.append(f"- 主线 shadow1: {main_pick['balanced'].get('name','-')}")
    lines.append(f"- 主线 shadow2: {main_pick['aggressive'].get('name','-')}")
    lines.append(f"- 分支优先推进: {branch_pick.get('eth_short',{}).get('name','-')}")
    lines.append(f"- ETH long: {branch_pick.get('eth_long',{}).get('status','rebuild')} | 不砍路径，继续 breakout-follow + pullback-confirm")
    lines.append(f"- SOL long: {branch_pick.get('sol_long',{}).get('status','hold')} | 保留 smooth/core 两族")
    lines.append(f"- SOL short: {branch_pick.get('sol_short',{}).get('status','rebuild')} | 继续 shock/retest/hybrid 三族，不轻易砍")
    lines.append("- 事件层: 继续做确认/放行/缩仓；重大事件可作为开仓依据，但仍必须和结构 + OI/funding/流动性一起确认。")

    payload = {
        "kline_health": kstats,
        "mainline": main_pick,
        "branch": branch_pick,
    }
    txt = raw / "stage93_frequency_accel_latest.txt"
    js = raw / "stage93_frequency_accel_latest.json"
    txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    js.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(txt)
    print(js)


if __name__ == "__main__":
    main()
