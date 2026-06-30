from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import research_config_baseline as rcb

PLAN_CFG = "config_shortwave_triple_book_plan.yml"
PLAN_SHADOW = "shadow_shortwave_triple_book_plan.yml"


def _expand(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v in (None, "", "-"):
            return default
        return float(v)
    except Exception:
        return default


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        if v in (None, "", "-"):
            return default
        return int(float(v))
    except Exception:
        return default


def _fmt_pct(v: Any) -> str:
    if v in (None, "", "-"):
        return "-"
    try:
        return f"{float(v) * 100:.2f}%"
    except Exception:
        return "-"


def _fmt_num(v: Any, digits: int = 3) -> str:
    if v in (None, "", "-"):
        return "-"
    try:
        return f"{float(v):.{digits}f}"
    except Exception:
        return "-"


def _read_stage91(root: Path) -> dict[str, Any]:
    p = root / 'reports' / 'research_raw' / 'stage91_branch_event_alpha_matrix_latest.json'
    if not p.exists():
        raise SystemExit(f'缺少 {p}')
    return _load_json(p)


def _asset_index(stage91: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in stage91.get('asset_summary', []) or []:
        if not isinstance(row, dict):
            continue
        sym = str(row.get('symbol') or '').strip().lower()
        if sym:
            out[sym] = row
    return out


def _recent_metrics(row: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(row, dict):
        return {}
    dom = row.get('dominant_gate') or {}
    if isinstance(dom, dict):
        return dom.get('recent_metrics') or {}
    return {}


def _wf_metrics(row: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(row, dict):
        return {}
    wf = row.get('walkforward') or {}
    if isinstance(wf, dict):
        return wf.get('metrics') or {}
    return {}


def _row_name(row: dict[str, Any] | None) -> str:
    if not isinstance(row, dict):
        return '-'
    return str(row.get('name') or '-')


def _parse_stage99_txt(root: Path) -> dict[str, Any]:
    p = root / 'reports' / 'research_raw' / 'stage99_mainline_frequency_push_latest.txt'
    out = {
        'live_keep': 'mainline_live_base',
        'shadow_balanced': 'combo_sr_soft_adx26_cd6_lb24_zone028_ref',
        'shadow_aggressive': 'combo_sr_soft_adx32_cd5_lb20_zone025',
    }
    if not p.exists():
        return out
    txt = p.read_text(encoding='utf-8', errors='ignore')
    m = re.search(r'-\s*live_keep:\s*([^|\n]+)', txt)
    if m:
        out['live_keep'] = m.group(1).strip()
    m = re.search(r'-\s*shadow_balanced:\s*([^|\n]+)', txt)
    if m:
        out['shadow_balanced'] = m.group(1).strip()
    m = re.search(r'-\s*shadow_aggressive:\s*([^|\n]+)', txt)
    if m:
        out['shadow_aggressive'] = m.group(1).strip()
    return out


def _latest_common_end(root: Path, symbols: list[str], csv_template: str, fallback: str) -> str:
    ends = []
    for sym in symbols:
        p = root / Path(csv_template.format(symbol=sym))
        if not p.exists():
            continue
        try:
            last = None
            with p.open('r', encoding='utf-8', errors='ignore') as fh:
                fh.readline()
                for line in fh:
                    if line.strip():
                        last = line
            if not last:
                continue
            ts = last.split(',')[0].strip()
            m = re.match(r'(\d{4}-\d{2}-\d{2})', ts)
            if m:
                ends.append(m.group(1))
        except Exception:
            continue
    if not ends:
        return fallback
    return min(ends)


def _pick_btc_leg(asset: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    dual = asset.get('dual_best')
    short_best = asset.get('short_best')
    active = asset.get('active')
    dual_wf = _wf_metrics(dual)
    if _safe_float(dual_wf.get('pf')) >= 1.20 and _safe_int(dual_wf.get('trades')) >= 8:
        return dual, 'dual_best_wf_ok'
    if isinstance(active, dict):
        return active, 'active_keep'
    if isinstance(dual, dict):
        return dual, 'dual_best_fallback'
    if isinstance(short_best, dict):
        return short_best, 'short_best_fallback'
    return None, 'missing'


def _pick_eth_leg(asset: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    active = asset.get('active')
    short_best = asset.get('short_best')
    if isinstance(active, dict):
        return active, 'active_keep'
    if isinstance(short_best, dict):
        return short_best, 'short_best_fallback'
    return None, 'missing'


def _pick_sol_leg(asset: dict[str, Any]) -> tuple[dict[str, Any] | None, str, bool]:
    long_best = asset.get('long_best')
    short_best = asset.get('short_best')
    active = asset.get('active')
    # 当前更看重近2年 + WF 同时站住；否则只保留三标的设计，不推进 demo。
    for row, reason in ((active, 'active_check'), (long_best, 'long_best_check'), (short_best, 'short_best_check')):
        recent = _recent_metrics(row)
        wf = _wf_metrics(row)
        if _safe_float(recent.get('pf')) >= 1.20 and _safe_float(wf.get('pf')) >= 1.15 and _safe_float(recent.get('ret')) > 0 and _safe_float(wf.get('ret')) > 0:
            return row, reason + '_qualified', True
    if isinstance(long_best, dict):
        return long_best, 'long_best_reserve', False
    if isinstance(short_best, dict):
        return short_best, 'short_best_reserve', False
    if isinstance(active, dict):
        return active, 'active_reserve', False
    return None, 'missing', False


def build_plan(project_dir: Path) -> dict[str, Any]:
    root = project_dir.resolve()
    stage91 = _read_stage91(root)
    asset_map = _asset_index(stage91)
    if not {'btc', 'eth', 'sol'}.issubset(asset_map.keys()):
        raise SystemExit('stage91 缺少 BTC/ETH/SOL 资产腿结果')

    btc_asset = asset_map['btc']
    eth_asset = asset_map['eth']
    sol_asset = asset_map['sol']
    btc_leg, btc_reason = _pick_btc_leg(btc_asset)
    eth_leg, eth_reason = _pick_eth_leg(eth_asset)
    sol_leg, sol_reason, sol_ready = _pick_sol_leg(sol_asset)
    stage99 = _parse_stage99_txt(root)

    base_cfg_path = rcb.locate_research_base_yaml(root)
    base_cfg = _load_yaml(base_cfg_path)
    shadow_doc = _load_yaml(root / 'shadow.yml')
    shadow_base = shadow_doc.get('shadow', shadow_doc) if isinstance(shadow_doc, dict) else {}

    cfg = copy.deepcopy(base_cfg)
    cfg.setdefault('system', {})
    cfg['system']['version'] = 'r251_branch_triple_book_plan__btc025_eth060_sol015_v1'
    cfg['system']['strategy'] = 'branch_shortwave_demo_triple_book_plan'
    cfg['system']['note'] = (
        '第二分支设计层固定 BTC/ETH/SOL 三标的整体 book；当前 ETH 仍是主导收益腿，BTC 保留多空一体，SOL 保留路径并继续 research frontier。'
        '6年总样本仅作软约束，判断以近2年 + WF 为主；重大事件只和结构/资金/波动确认共同放行。'
    )
    cfg.setdefault('data', {})
    cfg['data']['symbols'] = ['btc', 'eth', 'sol']
    cfg['data']['weights'] = {'btc': 0.25, 'eth': 0.60, 'sol': 0.15}
    csv_template = str(cfg['data'].get('csv_template', 'data/raw/{symbol}_15m.csv'))
    cfg['data']['end'] = _latest_common_end(root, ['btc', 'eth', 'sol'], csv_template, str(cfg['data'].get('end', '2026-03-24')))

    sp = cfg.setdefault('strategy_params', {})
    sp['allow_short'] = True
    sp['long_symbols'] = ['btc', 'eth', 'sol']
    sp['short_symbols'] = ['btc', 'eth', 'sol']
    sp['pyramiding_symbols'] = []
    sp['breakout_lookback'] = 18
    sp['breakout_atr_buffer'] = 0.55
    sp['cooldown_bars'] = 6

    filters = cfg.setdefault('filters', {})
    filters['adx_floor'] = 22
    filters['macro_gate_symbols'] = ['btc', 'eth', 'sol']
    tf_map = filters.get('macro_gate_tf_by_symbol') if isinstance(filters.get('macro_gate_tf_by_symbol'), dict) else {}
    tf_map['btc'] = '4h'
    tf_map['eth'] = '4h'
    tf_map['sol'] = '4h'
    filters['macro_gate_tf_by_symbol'] = tf_map
    filters['macro_gate_reference_symbol'] = 'btc'

    mm = cfg.setdefault('money_management', {})
    mm['mode'] = 'fixed_tranche'
    mm['capital_slices'] = 8
    mm['stake_mode'] = 'dynamic_equity'
    mm['stake_min_usd'] = 2000
    mm['stake_max_usd'] = 120000
    stake_scale = mm.get('stake_scale') if isinstance(mm.get('stake_scale'), dict) else {}
    stake_scale['btc_long'] = 0.22
    stake_scale['btc_short'] = 0.28
    stake_scale['eth_short'] = 0.68
    stake_scale['eth_long'] = 0.18
    stake_scale['sol_long'] = 0.12
    stake_scale['sol_short'] = 0.10
    mm['stake_scale'] = stake_scale

    eg = cfg.setdefault('execution_guard', {})
    eg['enabled'] = True
    eg['symbols'] = ['btc', 'eth', 'sol']

    shadow = copy.deepcopy(shadow_base)
    shadow['submit_orders'] = False
    contracts = shadow.setdefault('contracts', {})
    contracts.setdefault('btc', 'BTC-USDT-SWAP')
    contracts.setdefault('eth', 'ETH-USDT-SWAP')
    contracts.setdefault('sol', 'SOL-USDT-SWAP')
    exec_step = shadow.setdefault('execution_step', {})
    notional_map = exec_step.get('notional_usdt_by_symbol') if isinstance(exec_step.get('notional_usdt_by_symbol'), dict) else {}
    notional_map['btc'] = float(notional_map.get('btc', 20.0) or 20.0)
    notional_map['eth'] = float(notional_map.get('eth', 20.0) or 20.0)
    notional_map['sol'] = float(notional_map.get('sol', 20.0) or 20.0)
    exec_step['notional_usdt_by_symbol'] = notional_map
    sizing = exec_step.setdefault('sizing', {})
    lev_by_symbol = sizing.get('leverage_by_symbol') if isinstance(sizing.get('leverage_by_symbol'), dict) else {}
    lev_by_symbol['btc'] = 7
    lev_by_symbol['eth'] = 6
    lev_by_symbol['sol'] = 6
    sizing['leverage_by_symbol'] = lev_by_symbol
    lev_by_signal = sizing.get('leverage_by_signal') if isinstance(sizing.get('leverage_by_signal'), dict) else {}
    lev_by_signal['btc_short'] = 8
    lev_by_signal['btc_long'] = 7
    lev_by_signal['eth_short'] = 6
    lev_by_signal['eth_long'] = 5
    lev_by_signal['sol_short'] = 6
    lev_by_signal['sol_long'] = 5
    sizing['leverage_by_signal'] = lev_by_signal
    exec_step['clord_prefix'] = 'okxb'

    if isinstance(shadow_doc, dict) and 'shadow' in shadow_doc:
        shadow_doc_out = copy.deepcopy(shadow_doc)
        shadow_doc_out['shadow'] = shadow
    else:
        shadow_doc_out = shadow

    out_cfg = root / PLAN_CFG
    out_shadow = root / PLAN_SHADOW
    _write_yaml(out_cfg, cfg)
    _write_yaml(out_shadow, shadow_doc_out)

    raw = root / 'reports' / 'research_raw'
    raw.mkdir(parents=True, exist_ok=True)
    out_txt = raw / 'stage107_joint_upgrade_plan_latest.txt'
    out_json = raw / 'stage107_joint_upgrade_plan_latest.json'

    btc_recent = _recent_metrics(btc_leg)
    btc_wf = _wf_metrics(btc_leg)
    eth_recent = _recent_metrics(eth_leg)
    eth_wf = _wf_metrics(eth_leg)
    sol_recent = _recent_metrics(sol_leg)
    sol_wf = _wf_metrics(sol_leg)

    lines: list[str] = []
    lines.append('Stage107 主线提频 + 第二分支三标的联合升级规划')
    lines.append('规则：6年整体仅作软约束；判断以近2年 + WF 为主；主线和支线一起推进，但不改双终端规则。')
    lines.append('三标的定义：第二分支设计层固定 BTC / ETH / SOL，一个整体 book，不再表述成散腿。')
    lines.append('')
    lines.append(f'generated_at_utc={datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}')
    lines.append('')
    lines.append('=== 主线 ===')
    lines.append(f"- keep_live: {stage99.get('live_keep')}")
    lines.append(f"- shadow_priority_1: {stage99.get('shadow_balanced')}")
    lines.append(f"- shadow_priority_2: {stage99.get('shadow_aggressive')}")
    lines.append('- strategy_focus: 提频不靠粗暴放松阈值；优先放宽结构入场，再让事件 / funding / OI / basis / skew 二次确认。')
    lines.append('- demo_rule: 主线先继续 live_base；shadow 继续观察，不直接切 live。')
    lines.append('')
    lines.append('=== 第二分支三标的 book ===')
    lines.append('- design_book: BTC + ETH + SOL')
    lines.append('- current_demo_runtime: BTC + ETH preview active | SOL reserve research')
    lines.append(f"- target_template: {out_cfg.name} | submit_orders=false")
    lines.append('')
    lines.append('=== BTC 腿 ===')
    lines.append(f"- pick_reason={btc_reason} | runtime_leg={_row_name(btc_leg)}")
    lines.append(f"- recent: 收益={_fmt_pct(btc_recent.get('ret'))} PF={_fmt_num(btc_recent.get('pf'))} 交易={_safe_int(btc_recent.get('trades'))}")
    lines.append(f"- wf: 收益={_fmt_pct(btc_wf.get('ret'))} PF={_fmt_num(btc_wf.get('pf'))} 交易={_safe_int(btc_wf.get('trades'))}")
    lines.append('- action: 保留 BTC 多空一体；当前更适合作为低权重确认腿，不轻易删除。')
    lines.append('')
    lines.append('=== ETH 腿 ===')
    lines.append(f"- pick_reason={eth_reason} | runtime_leg={_row_name(eth_leg)}")
    lines.append(f"- recent: 收益={_fmt_pct(eth_recent.get('ret'))} PF={_fmt_num(eth_recent.get('pf'))} 交易={_safe_int(eth_recent.get('trades'))}")
    lines.append(f"- wf: 收益={_fmt_pct(eth_wf.get('ret'))} PF={_fmt_num(eth_wf.get('pf'))} 交易={_safe_int(eth_wf.get('trades'))}")
    lines.append('- action: ETH 继续保留 short fast 主导，同时继续追 event_pressure / event_reclaim 候选。')
    lines.append('')
    lines.append('=== SOL 腿 ===')
    lines.append(f"- pick_reason={sol_reason} | reserve_leg={_row_name(sol_leg)}")
    lines.append(f"- recent: 收益={_fmt_pct(sol_recent.get('ret'))} PF={_fmt_num(sol_recent.get('pf'))} 交易={_safe_int(sol_recent.get('trades'))}")
    lines.append(f"- wf: 收益={_fmt_pct(sol_wf.get('ret'))} PF={_fmt_num(sol_wf.get('pf'))} 交易={_safe_int(sol_wf.get('trades'))}")
    lines.append('- action: SOL 路径保留，不走死胡同；当前先留 research frontier，不自动推进 demo。')
    lines.append('')
    lines.append('=== 推进门槛 ===')
    lines.append('- 主线提频切 demo：先看 shadow 是否在近2年 + WF 里继续维持更高交易频次，同时 PF / DD 不明显劣化。')
    lines.append('- 第二分支加 SOL 上 demo：至少要求 SOL 候选在近2年与 WF 同时转正，PF 站住，且不破坏整体 book。')
    lines.append('- 第二分支目标：复合月化 7.6%-11.4% 以上；当前这只是目标，不是假装已经达到。')
    lines.append('')
    lines.append('=== 下一步 ===')
    lines.append('- run_stage108_joint_dual_track_opt.sh: 只做主线提频 + BTC quick + ETH/SOL open frontier 的联合 targeted refresh。')
    lines.append('- 等 stage108 结果出来，再决定是否把升级后的 branch template 推进到 demo。')
    out_txt.write_text('\n'.join(lines).rstrip() + '\n', encoding='utf-8')

    payload = {
        'generated_at_utc': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'),
        'mainline': {
            'keep_live': stage99.get('live_keep'),
            'shadow_priority_1': stage99.get('shadow_balanced'),
            'shadow_priority_2': stage99.get('shadow_aggressive'),
            'focus': 'structure_relax_then_event_flow_confirm',
        },
        'branch_design_book': ['btc', 'eth', 'sol'],
        'current_demo_runtime': ['btc', 'eth'],
        'sol_demo_ready': sol_ready,
        'weights_template': {'btc': 0.25, 'eth': 0.60, 'sol': 0.15},
        'btc': {'pick_reason': btc_reason, 'leg': btc_leg},
        'eth': {'pick_reason': eth_reason, 'leg': eth_leg},
        'sol': {'pick_reason': sol_reason, 'leg': sol_leg, 'demo_ready': sol_ready},
        'plan_config': str(out_cfg),
        'plan_shadow': str(out_shadow),
        'next_script': 'run_stage108_joint_dual_track_opt.sh',
    }
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return {
        'ok': True,
        'plan_txt': str(out_txt),
        'plan_json': str(out_json),
        'plan_config': str(out_cfg),
        'plan_shadow': str(out_shadow),
        'sol_demo_ready': sol_ready,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description='Stage107 主线+支线联合升级规划')
    ap.add_argument('--project-dir', default='.')
    args = ap.parse_args()
    result = build_plan(_expand(args.project_dir))
    print(yaml.safe_dump(result, allow_unicode=True, sort_keys=False).strip())


if __name__ == '__main__':
    main()
