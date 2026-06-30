from __future__ import annotations

import argparse
import json
import re
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding='utf-8')) or {}


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding='utf-8')


def _safe_text(path: Path) -> str:
    try:
        return path.read_text(encoding='utf-8')
    except Exception:
        return ''


def _copy_overlays(src: dict[str, Any], dst: dict[str, Any]) -> None:
    for key in ['live_bridge', 'outputs', 'shadow', 'execution', 'autopilot']:
        if isinstance(src.get(key), dict):
            dst[key] = src[key]


def _looks_like_stage148_bad_restore(cfg: dict[str, Any]) -> bool:
    system = cfg.get('system') or {}
    mm = cfg.get('money_management') or {}
    dyn = (cfg.get('portfolio') or {}).get('dynamic_leverage') or {}
    version = str(system.get('version') or '')
    if 'restore_live_base_stage148' in version:
        return True
    return (
        str(mm.get('mode') or '') == 'fixed_tranche'
        and int(mm.get('capital_slices') or 0) == 4
        and float(dyn.get('min') or 0.0) >= 70.0
    )


def _extract_current_candidate_metrics(report_text: str) -> dict[str, str]:
    out = {
        'candidate': '-',
        'decision': '-',
        'six_year': '-',
        'two_year': '-',
        'wf': '-',
    }
    patterns = {
        'candidate': r'当前候选:\s*(.+)',
        'decision': r'评估结论:\s*([^\n]+)',
        'six_year': r'6年总样本:\s*([^\n]+)',
        'two_year': r'近2年样本:\s*([^\n]+)',
        'wf': r'WF样本外:\s*([^\n]+)',
    }
    for k, p in patterns.items():
        m = re.search(p, report_text)
        if m:
            out[k] = m.group(1).strip()
    return out


def _find_stage148_frontier(root: Path) -> Path | None:
    candidates = [
        root / 'reports' / 'research_raw' / 'stage148_livebase_restore_and_multiasset_frontier_latest.txt',
        root / 'stage148_livebase_restore_and_multiasset_frontier_latest.txt',
        root.parent / 'Downloads' / 'stage148_livebase_restore_and_multiasset_frontier_latest.txt',
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _find_branch_report(root: Path) -> Path | None:
    candidates = [
        root.parent / 'Downloads' / 'branch_demo_report_latest.txt',
        root / 'branch_demo_report_latest.txt',
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _find_okx_report(root: Path) -> Path | None:
    candidates = [
        root.parent / 'Downloads' / 'okx_demo_report_latest.txt',
        root / 'okx_demo_report_latest.txt',
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _find_stage148_mainline(root: Path) -> Path | None:
    candidates = [
        root / 'reports' / 'research_raw' / 'stage148_mainline_matrix_latest.txt',
        root / 'stage148_mainline_matrix_latest.txt',
        root.parent / 'Downloads' / 'stage148_mainline_matrix_latest.txt',
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _find_stage148_branch(root: Path) -> Path | None:
    candidates = [
        root / 'reports' / 'research_raw' / 'stage148_branch_matrix_latest.txt',
        root / 'stage148_branch_matrix_latest.txt',
        root.parent / 'Downloads' / 'stage148_branch_matrix_latest.txt',
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _summarize_first_match(text: str, needle: str) -> str:
    for line in text.splitlines():
        if needle in line:
            return line.strip()
    return '-'


def _main() -> None:
    parser = argparse.ArgumentParser(description='Stage150: guard bad live_base restore and recover mainline runtime.')
    parser.add_argument('--project-dir', default='.', help='btc_system_v1 project directory')
    args = parser.parse_args()

    root = Path(args.project_dir).resolve()
    if root.name != 'btc_system_v1':
        candidate = root / 'btc_system_v1'
        if candidate.exists():
            root = candidate.resolve()

    cfg_path = root / 'config.yml'
    good_cfg_path = root / 'config_mainline_dynlev_fix8_lock18.yml'
    legacy_cfg_path = root / 'research_baselines' / 'mainline_live_base.yml'
    backup_path = root / 'config_stage150_pre_recover_backup.yml'
    research_only_path = root / 'config_mainline_legacy_research_only_anchor_stage150.yml'

    current_cfg = _read_yaml(cfg_path)
    good_cfg = _read_yaml(good_cfg_path)
    legacy_cfg = _read_yaml(legacy_cfg_path)
    if not good_cfg:
        raise SystemExit('缺少 config_mainline_dynlev_fix8_lock18.yml，无法恢复主线。')

    if cfg_path.exists() and not backup_path.exists():
        shutil.copy2(cfg_path, backup_path)

    recovered_cfg = json.loads(json.dumps(good_cfg))
    recovered_cfg.setdefault('system', {})
    recovered_cfg['system']['version'] = 'r257_main_demo_guard_restore_fix8_lock18_stage150'
    recovered_cfg['system']['note'] = (
        'Stage150：Stage148 已证明当前 mainline_live_base 名称路径并不等于阶段性报告三十/三十二里的历史高月化主线；'
        '现回退到已验证稳定的 mainline_live_dynlev_fix8_lock18 作为 runtime 主线。'
        '历史 live_base 仅保留 research_only，不再误切回 live。'
    )
    _copy_overlays(current_cfg, recovered_cfg)
    _write_yaml(cfg_path, recovered_cfg)

    research_only_cfg = json.loads(json.dumps(legacy_cfg)) if legacy_cfg else {}
    if research_only_cfg:
        research_only_cfg.setdefault('system', {})
        research_only_cfg['system']['version'] = 'r257_legacy_livebase_research_only_anchor_stage150'
        research_only_cfg['system']['note'] = (
            'Stage150：历史 mainline_live_base 只保留为研究锚点，不再直接切到 runtime。'
        )
        research_only_cfg.setdefault('live_bridge', {})
        research_only_cfg['live_bridge']['submit_orders'] = False
        _write_yaml(research_only_path, research_only_cfg)

    okx_report_path = _find_okx_report(root)
    branch_report_path = _find_branch_report(root)
    stage148_frontier_path = _find_stage148_frontier(root)
    stage148_main_path = _find_stage148_mainline(root)
    stage148_branch_path = _find_stage148_branch(root)

    okx_text = _safe_text(okx_report_path) if okx_report_path else ''
    branch_text = _safe_text(branch_report_path) if branch_report_path else ''
    _safe_text(stage148_frontier_path) if stage148_frontier_path else ''
    main_text = _safe_text(stage148_main_path) if stage148_main_path else ''
    branch_matrix_text = _safe_text(stage148_branch_path) if stage148_branch_path else ''

    current_metrics = _extract_current_candidate_metrics(okx_text)
    main_fix8_line = _summarize_first_match(main_text, 'mainline_live_dynlev_fix8_lock18:')
    eth_anchor_line = _summarize_first_match(branch_matrix_text, 'eth_reclaim_long_lb12_atr043_adx16_s060')
    btc_line = _summarize_first_match(branch_text, 'BTC: mode=')
    sol_line = _summarize_first_match(branch_text, 'SOL: mode=')

    reports_dir = root / 'reports' / 'research_raw'
    reports_dir.mkdir(parents=True, exist_ok=True)
    out_txt = reports_dir / 'stage150_livebase_guard_and_mainline_recover_latest.txt'
    out_json = reports_dir / 'stage150_livebase_guard_and_mainline_recover_latest.json'
    manifest = reports_dir / 'stage150_livebase_guard_and_mainline_recover_manifest_latest.json'

    downloads_dir = root.parent / 'Downloads'
    downloads_dir.mkdir(parents=True, exist_ok=True)
    out_zip = downloads_dir / 'stage150_livebase_guard_and_mainline_recover_latest.zip'

    payload = {
        'ok': True,
        'project_dir': str(root),
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'recovered': True,
        'current_before_recover': {
            'version': str((current_cfg.get('system') or {}).get('version') or '-'),
            'looks_like_stage148_bad_restore': _looks_like_stage148_bad_restore(current_cfg),
        },
        'runtime_after_recover': {
            'version': str((recovered_cfg.get('system') or {}).get('version') or '-'),
            'config_path': str(cfg_path),
            'backup_path': str(backup_path),
            'good_cfg_path': str(good_cfg_path),
            'legacy_research_only_path': str(research_only_path) if research_only_cfg else '-',
        },
        'current_bad_restore_report_metrics': current_metrics,
        'stage148_fix8_summary_line': main_fix8_line,
        'stage148_eth_anchor_line': eth_anchor_line,
        'branch_runtime_btc_line': btc_line,
        'branch_runtime_sol_line': sol_line,
        'files_used': {
            'okx_report': str(okx_report_path) if okx_report_path else '-',
            'branch_report': str(branch_report_path) if branch_report_path else '-',
            'stage148_frontier': str(stage148_frontier_path) if stage148_frontier_path else '-',
            'stage148_mainline': str(stage148_main_path) if stage148_main_path else '-',
            'stage148_branch': str(stage148_branch_path) if stage148_branch_path else '-',
        },
    }

    lines = []
    lines.append('Stage150 livebase guard + mainline recover')
    lines.append('结论：Stage148 已证明“按 mainline_live_base 名称直接切回”是错的；当前 runtime 必须回退到 mainline_live_dynlev_fix8_lock18。')
    lines.append('')
    lines.append('=== 原因 ===')
    lines.append(f"- Stage148 当前主线 runtime 报告：{current_metrics.get('candidate','-')} | {current_metrics.get('decision','-')}")
    lines.append(f"- 6年: {current_metrics.get('six_year','-')}")
    lines.append(f"- 近2年: {current_metrics.get('two_year','-')}")
    lines.append(f"- WF: {current_metrics.get('wf','-')}")
    lines.append('- 这说明“现在代码里的 mainline_live_base”已经不是阶段性报告三十/三十二里那条历史高月化主线。')
    lines.append('')
    lines.append('=== 已执行动作 ===')
    lines.append(f"- runtime config 回退到: {(recovered_cfg.get('system') or {}).get('version','-')}")
    lines.append(f"- 当前 live config: {cfg_path}")
    lines.append(f"- 回退前备份: {backup_path}")
    if research_only_cfg:
        lines.append(f"- 历史 live_base 只保留为 research_only: {research_only_path}")
    lines.append('')
    lines.append('=== 当前继续沿用的已验证真相 ===')
    lines.append(f"- 主线稳定基线: {main_fix8_line}")
    lines.append(f"- ETH 当前最强锚点: {eth_anchor_line}")
    lines.append(f"- 分支 BTC: {btc_line}")
    lines.append(f"- 分支 SOL: {sol_line}")
    lines.append('')
    lines.append('=== 终端结论 ===')
    lines.append('- 主线：先用 fix8_lock18 继续跑 runtime，不再把 legacy live_base 误切回 live。')
    lines.append('- 分支：继续 1 个 triple-book 终端，不拆 3 个终端。')
    lines.append('- 下一步：单独重建“historical livebase reconstruction”研究线，但不影响当前 demo。')

    out_txt.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    manifest.write_text(json.dumps({
        'txt': str(out_txt),
        'json': str(out_json),
        'zip': str(out_zip),
    }, ensure_ascii=False, indent=2), encoding='utf-8')

    with zipfile.ZipFile(out_zip, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for p in [out_txt, out_json, cfg_path, backup_path]:
            if p.exists():
                zf.write(p, arcname=p.name)
        if research_only_cfg and research_only_path.exists():
            zf.write(research_only_path, arcname=research_only_path.name)
        for p in [okx_report_path, branch_report_path, stage148_frontier_path]:
            if p and p.exists():
                zf.write(p, arcname=p.name)

    print(json.dumps({'ok': True, 'out_zip': str(out_zip), 'out_txt': str(out_txt)}, ensure_ascii=False))


if __name__ == '__main__':
    _main()
