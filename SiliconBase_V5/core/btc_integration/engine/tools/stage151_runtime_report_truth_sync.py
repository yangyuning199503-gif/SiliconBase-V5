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
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _safe_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _extract_line(text: str, pattern: str) -> str:
    m = re.search(pattern, text)
    return m.group(1).strip() if m else "-"


def _backup_and_remove(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    src.unlink(missing_ok=True)
    return True


def _find_branch_report(root: Path) -> Path | None:
    for p in [root.parent / 'Downloads' / 'branch_demo_report_latest.txt', root / 'branch_demo_report_latest.txt']:
        if p.exists():
            return p
    return None


def _find_okx_report(root: Path) -> Path | None:
    for p in [root.parent / 'Downloads' / 'okx_demo_report_latest.txt', root / 'okx_demo_report_latest.txt']:
        if p.exists():
            return p
    return None


def _find_stage150_txt(root: Path) -> Path | None:
    candidates = [
        root / 'reports' / 'research_raw' / 'stage150_livebase_guard_and_mainline_recover_latest.txt',
        root / 'stage150_livebase_guard_and_mainline_recover_latest.txt',
        root.parent / 'Downloads' / 'stage150_livebase_guard_and_mainline_recover_latest.txt',
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _main() -> None:
    ap = argparse.ArgumentParser(description='Stage151: clear stale mainline runtime report artifacts after config switches.')
    ap.add_argument('--project-dir', default='.', help='btc_system_v1 project directory')
    args = ap.parse_args()

    root = Path(args.project_dir).resolve()
    if root.name != 'btc_system_v1':
        candidate = root / 'btc_system_v1'
        if candidate.exists():
            root = candidate.resolve()

    cfg_path = root / 'config.yml'
    cfg = _read_yaml(cfg_path)
    cfg_version = str(((cfg.get('system') or {}) if isinstance(cfg, dict) else {}).get('version') or '')
    cfg_note = str(((cfg.get('system') or {}) if isinstance(cfg, dict) else {}).get('note') or '')

    runtime_dir = root / '.runtime'
    runtime_dir.mkdir(parents=True, exist_ok=True)
    runtime_report_path = runtime_dir / 'okx_demo_shadow_exec_latest.json'
    runtime_state_path = runtime_dir / 'okx_demo_autopilot_state.json'
    okx_report_path = _find_okx_report(root)
    branch_report_path = _find_branch_report(root)
    stage150_txt_path = _find_stage150_txt(root)

    runtime_rep = _read_json(runtime_report_path)
    runtime_plan_version = str(runtime_rep.get('plan_version') or '')
    public_text = _safe_text(okx_report_path) if okx_report_path else ''
    public_version = _extract_line(public_text, r'当前版本:\s*(.+)')
    public_candidate = _extract_line(public_text, r'当前候选:\s*(.+)')
    public_decision = _extract_line(public_text, r'评估结论:\s*(.+)')
    public_two_year = _extract_line(public_text, r'近2年样本:\s*(.+)')
    public_wf = _extract_line(public_text, r'WF样本外:\s*(.+)')

    branch_text = _safe_text(branch_report_path) if branch_report_path else ''
    branch_candidate = _extract_line(branch_text, r'当前候选:\s*(.+)')
    branch_decision = _extract_line(branch_text, r'评估结论:\s*(.+)')
    branch_eth = next((ln.strip() for ln in branch_text.splitlines() if ln.strip().startswith('- ETH: mode=')), '-')
    branch_btc = next((ln.strip() for ln in branch_text.splitlines() if ln.strip().startswith('- BTC: mode=')), '-')
    branch_sol = next((ln.strip() for ln in branch_text.splitlines() if ln.strip().startswith('- SOL: mode=')), '-')

    stage150_txt = _safe_text(stage150_txt_path) if stage150_txt_path else ''
    stage150_fix8 = next((ln.strip() for ln in stage150_txt.splitlines() if 'mainline_live_dynlev_fix8_lock18:' in ln), '-')

    stale_runtime = bool(cfg_version and runtime_plan_version and runtime_plan_version != cfg_version)
    stale_public = bool(cfg_version and public_version not in {'', '-'} and public_version != cfg_version)
    stale_mainline = stale_runtime or stale_public or ('mainline_live_base' in public_candidate and 'kill' in public_decision)

    ts = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup_files: list[str] = []
    removed_runtime_report = False
    removed_state_file = False

    if stale_mainline and runtime_report_path.exists():
        backup_path = runtime_dir / f'okx_demo_shadow_exec_latest.stage151_stale_backup_{ts}.json'
        removed_runtime_report = _backup_and_remove(runtime_report_path, backup_path)
        if removed_runtime_report:
            backup_files.append(str(backup_path))

    # 仅当状态文件明确记录旧版本时才备份清掉，避免保留旧 version 误导等待态。
    state_payload = _read_json(runtime_state_path)
    state_text = json.dumps(state_payload, ensure_ascii=False)
    if stale_mainline and runtime_state_path.exists() and ((runtime_plan_version and runtime_plan_version in state_text) or (public_version not in {'', '-'} and public_version in state_text)):
        state_backup = runtime_dir / f'okx_demo_autopilot_state.stage151_stale_backup_{ts}.json'
        removed_state_file = _backup_and_remove(runtime_state_path, state_backup)
        if removed_state_file:
            backup_files.append(str(state_backup))

    if stale_public and okx_report_path and okx_report_path.exists():
        public_backup = runtime_dir / f'okx_demo_report_latest.stage151_stale_backup_{ts}.txt'
        shutil.copy2(okx_report_path, public_backup)
        backup_files.append(str(public_backup))

    reports_dir = root / 'reports' / 'research_raw'
    reports_dir.mkdir(parents=True, exist_ok=True)
    out_txt = reports_dir / 'stage151_runtime_report_truth_sync_latest.txt'
    out_json = reports_dir / 'stage151_runtime_report_truth_sync_latest.json'
    downloads_dir = root.parent / 'Downloads'
    downloads_dir.mkdir(parents=True, exist_ok=True)
    out_zip = downloads_dir / 'stage151_runtime_report_truth_sync_latest.zip'

    lines: list[str] = []
    lines.append('Stage151 runtime report truth sync')
    lines.append('结论：Stage150 的 config 回退动作是对的；主线 public report 还停在 stage148，是 runtime 残留报告造成的，不是主线又切坏了。')
    lines.append('')
    lines.append('=== 当前主线真相 ===')
    lines.append(f'- config_version: {cfg_version or "-"}')
    lines.append(f'- config_note: {cfg_note or "-"}')
    lines.append(f'- runtime_plan_version_before: {runtime_plan_version or "-"}')
    lines.append(f'- public_report_version_before: {public_version or "-"}')
    lines.append(f'- public_report_candidate_before: {public_candidate or "-"}')
    lines.append(f'- public_report_decision_before: {public_decision or "-"}')
    lines.append(f'- public_report_2y_before: {public_two_year or "-"}')
    lines.append(f'- public_report_wf_before: {public_wf or "-"}')
    lines.append(f'- stage150_fix8_anchor: {stage150_fix8}')
    lines.append('')
    lines.append('=== 当前分支真相 ===')
    lines.append(f'- branch_candidate: {branch_candidate or "-"}')
    lines.append(f'- branch_decision: {branch_decision or "-"}')
    lines.append(f'- branch_btc: {branch_btc}')
    lines.append(f'- branch_eth: {branch_eth}')
    lines.append(f'- branch_sol: {branch_sol}')
    lines.append('')
    lines.append('=== 已执行修正 ===')
    lines.append(f'- stale_runtime_detected: {"yes" if stale_mainline else "no"}')
    lines.append(f'- removed_runtime_report: {"yes" if removed_runtime_report else "no"}')
    lines.append(f'- removed_state_file: {"yes" if removed_state_file else "no"}')
    if backup_files:
        lines.append('- backups:')
        for item in backup_files:
            lines.append(f'  - {item}')
    else:
        lines.append('- backups: -')
    lines.append('')
    lines.append('=== 下一步 ===')
    lines.append('- 重新启动主线 Demo 后，waiting 状态会直接按当前 config_version 出报告。')
    lines.append('- 这一步不改分支、不改下单逻辑，只清主线真相显示。')

    payload = {
        'ok': True,
        'project_dir': str(root),
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'config_version': cfg_version,
        'config_note': cfg_note,
        'runtime_plan_version_before': runtime_plan_version,
        'public_report_version_before': public_version,
        'public_report_candidate_before': public_candidate,
        'public_report_decision_before': public_decision,
        'public_report_two_year_before': public_two_year,
        'public_report_wf_before': public_wf,
        'stage150_fix8_anchor': stage150_fix8,
        'branch_candidate': branch_candidate,
        'branch_decision': branch_decision,
        'branch_btc': branch_btc,
        'branch_eth': branch_eth,
        'branch_sol': branch_sol,
        'stale_mainline': stale_mainline,
        'removed_runtime_report': removed_runtime_report,
        'removed_state_file': removed_state_file,
        'backup_files': backup_files,
        'files_used': {
            'config': str(cfg_path),
            'runtime_report': str(runtime_report_path),
            'runtime_state': str(runtime_state_path),
            'okx_public_report': str(okx_report_path) if okx_report_path else '-',
            'branch_public_report': str(branch_report_path) if branch_report_path else '-',
            'stage150_txt': str(stage150_txt_path) if stage150_txt_path else '-',
        },
    }

    out_txt.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')

    with zipfile.ZipFile(out_zip, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for p in [out_txt, out_json, cfg_path]:
            if p.exists():
                zf.write(p, arcname=p.name)
        for p in [okx_report_path, branch_report_path, stage150_txt_path]:
            if p and p.exists():
                zf.write(p, arcname=p.name)
        for item in backup_files:
            p = Path(item)
            if p.exists():
                zf.write(p, arcname=p.name)

    print(json.dumps({'ok': True, 'out_zip': str(out_zip), 'out_txt': str(out_txt)}, ensure_ascii=False))


if __name__ == '__main__':
    _main()
