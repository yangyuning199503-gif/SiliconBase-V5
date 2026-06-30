from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _safe(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def _pct(x: Any) -> str:
    try:
        return f"{float(x) * 100:.2f}%"
    except Exception:
        return "NA"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _event_share(row: dict[str, Any]) -> float:
    wf = row.get("walkforward", {}) or {}
    total = max(int(wf.get("total_folds", 0) or 0), 1)
    mix = wf.get("gate_mix", {}) or {}
    base_ct = int(mix.get("base_message_overlay", 0) or 0)
    return max(0.0, min(1.0, (total - base_ct) / total))


def _dom_gate(row: dict[str, Any]) -> str:
    return str((row.get("dominant_gate", {}) or {}).get("gate_name", "-"))


def _recent(row: dict[str, Any]) -> dict[str, Any]:
    return (row.get("dominant_gate", {}) or {}).get("recent_metrics", {}) or {}


def _wf(row: dict[str, Any]) -> dict[str, Any]:
    return (row.get("walkforward", {}) or {}).get("metrics", {}) or {}


def _line(name: str, row: dict[str, Any]) -> str:
    r = _recent(row)
    w = _wf(row)
    return (
        f"- {name}: gate={_dom_gate(row)} | event_share={_event_share(row):.2f} "
        f"| recent 月化={_pct(r.get('monthlyized_ret'))} PF={_safe(r.get('pf')):.3f} 收益={_pct(r.get('ret'))} "
        f"| WF 月化={_pct(w.get('monthlyized_ret'))} PF={_safe(w.get('pf')):.3f} 收益={_pct(w.get('ret'))} "
        f"| decision={row.get('decision','-')}"
    )


def _pick_branch(rows: list[dict[str, Any]], symbol: str, family: str, name: str | None = None) -> dict[str, Any] | None:
    cand = [r for r in rows if str(r.get("symbol", "")).lower() == symbol and str(r.get("family", "")).lower() == family]
    if name is not None:
        for row in cand:
            if str(row.get("name")) == name:
                return row
    if not cand:
        return None
    cand.sort(key=lambda r: (
        str(r.get("decision", "")) in {"pass", "hold"},
        _safe(_wf(r).get("pf")) + _safe(_recent(r).get("pf")),
        _safe(_wf(r).get("ret")) + _safe(_recent(r).get("ret")),
        _event_share(r),
    ), reverse=True)
    return cand[0]


def _pick_event_first(rows: list[dict[str, Any]], symbol: str, family: str, limit: int = 3) -> list[dict[str, Any]]:
    cand = [r for r in rows if str(r.get("symbol", "")).lower() == symbol and str(r.get("family", "")).lower() == family]
    cand = [r for r in cand if _event_share(r) >= 0.20 or _dom_gate(r) != "base_message_overlay"]
    cand.sort(key=lambda r: (
        _event_share(r),
        _safe(_wf(r).get("pf")) + _safe(_recent(r).get("pf")),
        _safe(_wf(r).get("ret")) + _safe(_recent(r).get("ret")),
    ), reverse=True)
    return cand[:limit]


def _extract_mainline_focus(text: str) -> list[str]:
    out: list[str] = []
    for raw in text.splitlines():
        s = raw.strip()
        if s.startswith("- shadow_") or s.startswith("- shadow") or s.startswith("- live_keep"):
            out.append(s)
    return out[:4]


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage97 multi-standard frontier summary")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    raw = root / "reports" / "research_raw"

    stage91 = _load_json(raw / "stage91_branch_event_alpha_matrix_latest.json")
    rows: list[dict[str, Any]] = list(stage91.get("rows", []) or [])
    stage96_txt = (raw / "stage96_event_bridge_latest.txt").read_text(encoding="utf-8", errors="ignore") if (raw / "stage96_event_bridge_latest.txt").exists() else ""
    stage93_txt = (raw / "stage93_frequency_accel_latest.txt").read_text(encoding="utf-8", errors="ignore") if (raw / "stage93_frequency_accel_latest.txt").exists() else ""
    stage92_txt = (raw / "stage92_eth_sol_open_frontier_latest.txt").read_text(encoding="utf-8", errors="ignore") if (raw / "stage92_eth_sol_open_frontier_latest.txt").exists() else ""

    keep_eth_short = _pick_branch(rows, "eth", "short", "eth_short_shock_fast_lb16_atr052_adx22_s078")
    keep_eth_long = _pick_branch(rows, "eth", "long")
    keep_sol_long = _pick_branch(rows, "sol", "long")
    keep_sol_short = _pick_branch(rows, "sol", "short")
    eth_event_first = _pick_event_first(rows, "eth", "short", limit=3)
    sol_event_first = _pick_event_first(rows, "sol", "short", limit=2)
    mainline_focus = _extract_mainline_focus(stage93_txt)

    lines: list[str] = []
    lines.append("Stage97 多标准前沿")
    lines.append("原则：先激进扩标准，再保守收口；不再一套参数通吃。")
    lines.append("")
    lines.append("=== 主线 keep / 提频 ===")
    if mainline_focus:
        lines.extend(mainline_focus)
    else:
        lines.append("- 未读到 stage93 主线提频摘要")
    lines.append("")
    lines.append("=== 分支 keep ===")
    if keep_eth_short is not None:
        lines.append(_line("ETH short keep", keep_eth_short))
    if keep_eth_long is not None:
        lines.append(_line("ETH long best", keep_eth_long))
    if keep_sol_long is not None:
        lines.append(_line("SOL long best", keep_sol_long))
    if keep_sol_short is not None:
        lines.append(_line("SOL short best", keep_sol_short))
    lines.append("")
    lines.append("=== ETH short 事件桥接优先 ===")
    if eth_event_first:
        for row in eth_event_first:
            lines.append(_line(str(row.get("name")), row))
    else:
        lines.append("- 当前没有 event_share>=0.20 的 ETH short 候选")
    lines.append("")
    lines.append("=== SOL 研究层 ===")
    if sol_event_first:
        for row in sol_event_first:
            lines.append(_line(str(row.get("name")), row))
    else:
        lines.append("- 当前 SOL 事件候选仍弱，维持 research_only")
    lines.append("")
    lines.append("=== 五轨执行 ===")
    lines.append("- 轨1 event_impulse：重大事件当根追随")
    lines.append("- 轨2 event_pressure：事件后 1-3 根延续")
    lines.append("- 轨3 event_reclaim：扫流动性后收回关键位")
    lines.append("- 轨4 crowding_reversal：拥挤 + funding/OI 极端反身")
    lines.append("- 轨5 neutral_mean_revert：非事件短波均值回复")
    lines.append("")
    lines.append("=== 资产分层 ===")
    lines.append("- BTC：宏观 / ETF / 期权 skew / basis / 深度")
    lines.append("- ETH：事件桥接 + perp crowding + 期权面")
    lines.append("- SOL：流动性深度 + funding 极端 + 清算压力，先留研究层")
    lines.append("")
    lines.append("=== 当前结论 ===")
    lines.append("- 主线不动，继续提频 shadow。")
    lines.append("- 分支 demo 继续 ETH short fast。")
    lines.append("- 下一轮不是继续死刷参数，而是优先提升 ETH short 的 event_share，并保留 ETH/SOL 多空四腿。")
    if stage96_txt:
        lines.append("- stage96 已出现事件优先 ETH short 候选，方向对，但还没打赢 fast keep。")
    if stage92_txt:
        lines.append("- stage92 仍显示 SOL 只适合 research_only，不推进模拟盘。")

    out_txt = raw / "stage97_multi_standard_frontier_latest.txt"
    out_json = raw / "stage97_multi_standard_frontier_latest.json"
    out_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    out_json.write_text(json.dumps({
        "mainline_focus": mainline_focus,
        "eth_short_keep": keep_eth_short,
        "eth_short_event_first": eth_event_first,
        "eth_long_best": keep_eth_long,
        "sol_long_best": keep_sol_long,
        "sol_short_best": keep_sol_short,
        "sol_event_first": sol_event_first,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out_txt)
    print(out_json)


if __name__ == "__main__":
    main()
