from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        obj = json.loads(path.read_text(encoding='utf-8'))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _pct(x: Any) -> str:
    try:
        return f"{float(x) * 100:.2f}%"
    except Exception:
        return "NA"


def _num(x: Any, nd: int = 3) -> str:
    try:
        v = float(x)
        if math.isnan(v):
            return 'NA'
        return f"{v:.{nd}f}"
    except Exception:
        return "NA"


def _find_line(txt: str, prefix: str) -> str:
    for line in txt.splitlines():
        if prefix in line:
            return line.strip()
    return ''


def _parse_report(path: Path) -> dict[str, str]:
    txt = path.read_text(encoding='utf-8', errors='ignore') if path.exists() else ''
    data: dict[str, str] = {}
    keys = [
        '- 当前状态:',
        '- 状态原因:',
        '- 当前版本:',
        '- 最近影子执行成功:',
        '- 策略真实成交已开始:',
        '- 当前候选:',
        '- 评估结论:',
        '- 触发原因:',
        '- 当前模式:',
        '- 执行方式:',
    ]
    for k in keys:
        hit = _find_line(txt, k)
        if hit:
            data[k] = hit.split(k, 1)[1].strip()
    pats = {
        'next_bar': r'- 下一轮执行\(UTC\+8\):\s*(.+)',
        'done_bar': r'- 最近已完成 15m K 线开盘\(UTC\+8\):\s*(.+)',
        'signal_time': r'- 最近策略信号时间\(UTC\+8\):\s*(.+)',
    }
    for k, pat in pats.items():
        m = re.search(pat, txt)
        if m:
            data[k] = m.group(1).strip()
    return data


def _candidate_metrics(name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    for row in rows:
        if str(row.get('name', '')) == name:
            return row
    return {}


def _parse_dt(v: str) -> datetime | None:
    try:
        return datetime.strptime(v, '%Y-%m-%d %H:%M:%S')
    except Exception:
        return None


def _compare_ready(live_report: dict[str, str], shadow_report: dict[str, str]) -> bool:
    live_done = _parse_dt(live_report.get('done_bar', ''))
    shadow_done = _parse_dt(shadow_report.get('done_bar', ''))
    if not live_done or not shadow_done:
        return False
    if shadow_done < live_done:
        return False
    reason = shadow_report.get('- 状态原因:', '')
    exec_ok = shadow_report.get('- 最近影子执行成功:', '')
    state = shadow_report.get('- 当前状态:', '')
    if exec_ok == '是':
        return True
    return bool(reason == 'waiting_next_bar' or state == '等待下一轮')


def main() -> None:
    ap = argparse.ArgumentParser(description='Stage100 主线提频 shadow 监控')
    ap.add_argument('--project-dir', default='.')
    ap.add_argument('--candidate', default='combo_sr_soft_adx26_cd6_lb24_zone028_ref')
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    raw = root / 'reports' / 'research_raw'
    raw.mkdir(parents=True, exist_ok=True)

    p99 = raw / 'stage99_mainline_frequency_push_latest.json'
    okx_p = Path.home() / 'Downloads' / 'okx_demo_report_latest.txt'
    shadow_p = raw / 'mainline_shadow_demo_report_latest.txt'
    out_txt = raw / 'stage100_mainline_shadow_monitor_latest.txt'
    out_json = raw / 'stage100_mainline_shadow_monitor_latest.json'

    p99j = _load_json(p99)
    mainline = p99j.get('mainline') if isinstance(p99j.get('mainline'), dict) else {}
    rows = mainline.get('rows') if isinstance(mainline.get('rows'), list) else []
    live = mainline.get('live') if isinstance(mainline.get('live'), dict) else {}
    balanced_name = str((root / '.runtime' / 'mainline_shadow_balanced_candidate.txt').read_text(encoding='utf-8', errors='ignore').strip()) if (root / '.runtime' / 'mainline_shadow_balanced_candidate.txt').exists() else 'combo_sr_soft_adx26_cd6_lb24_zone028_ref'
    aggressive_name = str((root / '.runtime' / 'mainline_shadow_aggressive_candidate.txt').read_text(encoding='utf-8', errors='ignore').strip()) if (root / '.runtime' / 'mainline_shadow_aggressive_candidate.txt').exists() else 'combo_sr_soft_adx32_cd5_lb20_zone025'

    active_name = str(args.candidate or balanced_name)
    active_row = _candidate_metrics(active_name, rows)
    live_report = _parse_report(okx_p)
    shadow_report = _parse_report(shadow_p)
    compare_ready = _compare_ready(live_report, shadow_report)

    lines: list[str] = []
    lines.append('Stage100 主线提频 shadow 监控')
    lines.append('目标：不改当前双终端规则，不切 live；先把主线提频首选挂成后台无下单 shadow，观察战争/宏观冲击期是否能补足 missed opportunities。')
    lines.append('口径：只要 shadow 完成可比 bar 且回到 waiting_next_bar / 最近影子执行成功，即可导出；不再强依赖 signal_time。')
    lines.append('')
    lines.append(f"generated_at_utc={datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append('')
    lines.append('=== live ===')
    lines.append(f"- runtime_candidate={live_report.get('- 当前候选:','mainline_live_base')} | version={live_report.get('- 当前版本:','-')}")
    lines.append(f"- status={live_report.get('- 当前状态:','-')} | reason={live_report.get('- 状态原因:','-')} | next={live_report.get('next_bar','-')}")
    lines.append(f"- done_bar={live_report.get('done_bar','-')} | signal_time={live_report.get('signal_time','-')}")
    lines.append(f"- risk_mode={live_report.get('- 当前模式:','-')} | exec_mode={live_report.get('- 执行方式:','-')} | live_fill_started={live_report.get('- 策略真实成交已开始:','-')}")
    trig = live_report.get('- 触发原因:','')
    if trig:
        lines.append(f"- current_risk_trigger={trig}")
    lines.append('')
    lines.append('=== shadow ===')
    lines.append(f"- active_candidate={active_name}")
    if active_row:
        lines.append(
            f"- metrics: 近2年 收益={_pct(active_row.get('recent_ret'))} PF={_num(active_row.get('recent_pf'))} 交易={int(active_row.get('recent_trades',0) or 0)}"
            f" | WF 收益={_pct(active_row.get('wf_ret'))} PF={_num(active_row.get('wf_pf'))} 交易={int(active_row.get('wf_trades',0) or 0)}"
        )
    lines.append('- submit_orders=no（仅后台监控，不新增真实模拟盘订单）')
    if shadow_p.exists():
        lines.append(f"- shadow_status={shadow_report.get('- 当前状态:','-')} | reason={shadow_report.get('- 状态原因:','-')} | next={shadow_report.get('next_bar','-')}")
        lines.append(f"- shadow_done_bar={shadow_report.get('done_bar','-')} | shadow_signal_time={shadow_report.get('signal_time','-')}")
        lines.append(f"- shadow_version={shadow_report.get('- 当前版本:','-')} | shadow_exec_ok={shadow_report.get('- 最近影子执行成功:','-')}")
        lines.append(f"- compare_ready={'yes' if compare_ready else 'no'}")
    else:
        lines.append('- shadow_report=missing')
    lines.append('')
    lines.append('=== promote order ===')
    lines.append(f'- promote_order_1={balanced_name}')
    lines.append(f'- promote_order_2={aggressive_name}')
    lines.append('')
    lines.append('=== 当前动作 ===')
    lines.append('- keep live=mainline_live_base')
    lines.append(f'- run background no-order shadow={active_name}')
    if compare_ready:
        lines.append('- 当前已具备 live/shadow 同步比较条件，可据此判断是否把 balanced 从 shadow 提升到更高优先级。')
    else:
        lines.append('- 当前仍未形成可比样本，继续观察 15m。')

    out_txt.write_text('\n'.join(lines).rstrip() + '\n', encoding='utf-8')
    out_json.write_text(json.dumps({
        'active_candidate': active_name,
        'balanced_candidate': balanced_name,
        'aggressive_candidate': aggressive_name,
        'live_report': live_report,
        'shadow_report': shadow_report,
        'live_metrics': live,
        'active_metrics': active_row,
        'compare_ready': compare_ready,
    }, ensure_ascii=False, indent=2), encoding='utf-8')

    print(out_txt)
    print(out_json)


if __name__ == '__main__':
    main()
