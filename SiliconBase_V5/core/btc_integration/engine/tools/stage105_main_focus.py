from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding='utf-8', errors='ignore') if path.exists() else ''
    except Exception:
        return ''


def _file_info(path: Path) -> dict[str, Any]:
    return {
        'path': str(path),
        'exists': path.exists(),
        'size': int(path.stat().st_size) if path.exists() else 0,
    }


def _section_bullets(txt: str, header: str, limit: int = 6) -> list[str]:
    out: list[str] = []
    in_sec = False
    for raw in txt.splitlines():
        s = raw.rstrip('\n')
        if s.strip() == header:
            in_sec = True
            continue
        if in_sec and s.startswith('=== '):
            break
        if in_sec and s.strip().startswith('- '):
            out.append(s.strip())
            if len(out) >= limit:
                break
    return out


def _top_bullets(txt: str, limit: int = 6) -> list[str]:
    out: list[str] = []
    for raw in txt.splitlines():
        s = raw.strip()
        if s.startswith('- '):
            out.append(s)
            if len(out) >= limit:
                break
    return out


def _stage90_looks_zero(txt: str) -> bool:
    if not txt.strip():
        return True
    bullets = _section_bullets(txt, '=== 候选结果 ===', 6)
    if not bullets:
        bullets = _top_bullets(txt, 6)
    if not bullets:
        return True
    joined = ' | '.join(bullets)
    zero_tokens = ['收益=0.00%', '月化=0.00%', '交易=0', 'PF=0.000']
    return all(tok in joined for tok in zero_tokens[:3])


def main() -> None:
    ap = argparse.ArgumentParser(description='Stage105 main focus summary')
    ap.add_argument('--project-dir', default='.')
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    raw = root / 'reports' / 'research_raw'
    raw.mkdir(parents=True, exist_ok=True)

    p88 = raw / 'stage88_mainline_fusion_walkforward_latest.txt'
    p89 = raw / 'stage89_branch_fusion_walkforward_latest.txt'
    p90 = raw / 'stage90_mainline_event_alpha_matrix_latest.txt'
    p91 = raw / 'stage91_branch_event_alpha_matrix_latest.txt'
    out_txt = raw / 'stage105_main_focus_latest.txt'
    out_json = raw / 'stage105_main_focus_latest.json'

    t88 = _read(p88)
    _read(p89)
    t90 = _read(p90)
    t91 = _read(p91)

    lines: list[str] = []
    lines.append('Stage105 主线聚焦联跑')
    lines.append('')
    lines.append(f'generated_at_utc={datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}')
    lines.append('')
    lines.append('=== 文件状态 ===')
    for name, p in [('stage88', p88), ('stage89', p89), ('stage90', p90), ('stage91', p91)]:
        info = _file_info(p)
        lines.append(f"- {name}: exists={'yes' if info['exists'] else 'no'} size={info['size']} path={p}")
    lines.append('')
    lines.append('=== 主线融合(stage88) 摘要 ===')
    lines.extend(_section_bullets(t88, '=== 候选结果 ===', 4) or _top_bullets(t88, 4) or ['- 未读到 stage88'])
    lines.append('')
    lines.append('=== 主线事件(stage90) 摘要 ===')
    lines.append(f"- stage90_nonzero={'no' if _stage90_looks_zero(t90) else 'yes'}")
    lines.extend(_section_bullets(t90, '=== 候选结果 ===', 4) or _top_bullets(t90, 4) or ['- 未读到 stage90'])
    lines.append('')
    lines.append('=== 分支资产腿(stage91) 建议 ===')
    lines.extend(_section_bullets(t91, '=== 资产一体腿建议 ===', 8) or ['- 未读到 stage91 资产一体腿建议'])
    lines.append('')
    lines.append('=== 结论 ===')
    if _stage90_looks_zero(t90):
        lines.append('- stage90 仍然异常或全零，当前不要切主线 live。')
        lines.append('- 继续沿用 mainline_live_base 做 live，对 adx26_ref 只保留为 shadow/research。')
    else:
        lines.append('- stage90 已产出有效主线矩阵，可据此继续做主线提频/结构创新筛选。')
    lines.append('- 第二分支继续按 BTC/ETH/SOL 三条资产腿设计；若只有 ETH 腿达标，则只让 ETH 腿 active。')

    out_txt.write_text('\n'.join(lines).rstrip() + '\n', encoding='utf-8')
    out_json.write_text(json.dumps({
        'files': {
            'stage88': _file_info(p88),
            'stage89': _file_info(p89),
            'stage90': _file_info(p90),
            'stage91': _file_info(p91),
        },
        'stage90_nonzero': not _stage90_looks_zero(t90),
        'stage88_bullets': _section_bullets(t88, '=== 候选结果 ===', 4) or _top_bullets(t88, 4),
        'stage90_bullets': _section_bullets(t90, '=== 候选结果 ===', 4) or _top_bullets(t90, 4),
        'stage91_asset_summary': _section_bullets(t91, '=== 资产一体腿建议 ===', 8),
    }, ensure_ascii=False, indent=2), encoding='utf-8')

    print(out_txt)
    print(out_json)


if __name__ == '__main__':
    main()
