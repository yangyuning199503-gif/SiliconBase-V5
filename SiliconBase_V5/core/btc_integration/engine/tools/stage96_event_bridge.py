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


def _event_share(row: dict[str, Any]) -> float:
    wf = row.get("walkforward", {}) or {}
    total = max(int(wf.get("total_folds", 0) or 0), 1)
    mix = wf.get("gate_mix", {}) or {}
    base_ct = int(mix.get("base_message_overlay", 0) or 0)
    return max(0.0, min(1.0, (total - base_ct) / total))


def _dominant_name(row: dict[str, Any]) -> str:
    return str((row.get("dominant_gate", {}) or {}).get("gate_name", "-"))


def _recent(row: dict[str, Any]) -> dict[str, Any]:
    return (row.get("dominant_gate", {}) or {}).get("recent_metrics", {}) or {}


def _wf(row: dict[str, Any]) -> dict[str, Any]:
    return (row.get("walkforward", {}) or {}).get("metrics", {}) or {}


def _row_line(row: dict[str, Any]) -> str:
    r = _recent(row)
    w = _wf(row)
    return (
        f"- {row.get('name')} | gate={_dominant_name(row)} | event_share={_event_share(row):.2f} "
        f"| recent 月化={_pct(r.get('monthlyized_ret'))} PF={_safe(r.get('pf')):.3f} 收益={_pct(r.get('ret'))} "
        f"| WF 月化={_pct(w.get('monthlyized_ret'))} PF={_safe(w.get('pf')):.3f} 收益={_pct(w.get('ret'))} "
        f"| decision={row.get('decision')}"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description='Stage96 ETH event bridge summary')
    ap.add_argument('--project-dir', default='.')
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    raw = root / 'reports' / 'research_raw'
    p = raw / 'stage91_branch_event_alpha_matrix_latest.json'
    if not p.exists():
        raise SystemExit('缺少 stage91_branch_event_alpha_matrix_latest.json')

    obj = json.loads(p.read_text(encoding='utf-8'))
    rows: list[dict[str, Any]] = list(obj.get('rows', []) or [])

    eth_short = [r for r in rows if str(r.get('symbol')) == 'eth' and str(r.get('family')) == 'short']
    sol_rows = [r for r in rows if str(r.get('symbol')) == 'sol']

    keep = next((r for r in eth_short if str(r.get('name')) == 'eth_short_shock_fast_lb16_atr052_adx22_s078'), None)
    event_first = sorted(
        [r for r in eth_short if _event_share(r) >= 0.20 or _dominant_name(r) != 'base_message_overlay'],
        key=lambda r: (_event_share(r), _safe(_wf(r).get('pf')) + _safe(_recent(r).get('pf'))),
        reverse=True,
    )[:4]
    sol_event = sorted(
        [r for r in sol_rows if _event_share(r) >= 0.20 or _dominant_name(r) != 'base_message_overlay'],
        key=lambda r: (_event_share(r), _safe(_wf(r).get('pf')) + _safe(_recent(r).get('pf'))),
        reverse=True,
    )[:4]

    lines: list[str] = []
    lines.append('Stage96 事件桥接摘要')
    lines.append('原则：不再盲目扩 SOL 参数；先把 ETH short 的“快版收益”与“事件主导开仓”桥接起来。')
    lines.append('')
    lines.append('=== 当前 keep ===')
    if keep is not None:
        lines.append(_row_line(keep))
    else:
        lines.append('- 未找到 eth_short_shock_fast_lb16_atr052_adx22_s078')
    lines.append('')
    lines.append('=== ETH short 事件优先候选 ===')
    if event_first:
        lines.extend(_row_line(r) for r in event_first)
    else:
        lines.append('- 当前没有 event_share>=0.20 的 ETH short 候选')
    lines.append('')
    lines.append('=== SOL 事件候选 ===')
    if sol_event:
        lines.extend(_row_line(r) for r in sol_event)
    else:
        lines.append('- 当前没有 event_share>=0.20 的 SOL 候选')
    lines.append('')
    lines.append('=== 结论 ===')
    lines.append('- 主线不动，分支 demo 继续 ETH short fast。')
    lines.append('- 研究重点从“继续撒网扩参数”改成“ETH short 事件桥接”：保留 fast shock 结构，同时优先观察 event_pressure_alpha / event_reclaim_alpha 是否能把 event_share 拉起来。')
    lines.append('- SOL 先保留研究，不推进模拟盘。')

    out_txt = raw / 'stage96_event_bridge_latest.txt'
    out_json = raw / 'stage96_event_bridge_latest.json'
    out_txt.write_text("\n".join(lines).rstrip() + "\n", encoding='utf-8')
    out_json.write_text(json.dumps({
        'keep': keep,
        'eth_short_event_first': event_first,
        'sol_event_candidates': sol_event,
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    print(out_txt)
    print(out_json)


if __name__ == '__main__':
    main()
