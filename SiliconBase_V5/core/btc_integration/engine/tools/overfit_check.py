from __future__ import annotations

import argparse
import copy
import json
import subprocess
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


def _set_nested(d: dict[str, Any], path: str, value: Any) -> None:
    keys = path.split('.')
    cur = d
    for k in keys[:-1]:
        if k not in cur or not isinstance(cur[k], dict):
            cur[k] = {}
        cur = cur[k]
    cur[keys[-1]] = value


def _metric_pf(trades: pd.DataFrame) -> float:
    if trades.empty or 'pnl' not in trades.columns:
        return 0.0
    gp = float(trades.loc[trades['pnl'] > 0, 'pnl'].sum())
    gl = float(-trades.loc[trades['pnl'] < 0, 'pnl'].sum())
    if gp <= 0:
        return 0.0
    if gl <= 0:
        return 999.0
    return gp / gl


def _segment_stats(trades: pd.DataFrame, start_year: int, end_year: int) -> tuple[float, float, int]:
    if trades.empty:
        return 0.0, 0.0, 0
    dt = pd.to_datetime(trades['exit_time'])
    mask = (dt.dt.year >= start_year) & (dt.dt.year <= end_year)
    seg = trades.loc[mask].copy()
    if seg.empty:
        return 0.0, 0.0, 0
    pnl = float(seg['pnl'].sum())
    pf = _metric_pf(seg)
    n = int(len(seg))
    return pnl, pf, n


def _monthly_stats(eq: pd.DataFrame) -> dict[str, Any]:
    if eq.empty:
        return {'recent_mean': 0.0, 'recent_p90': 0.0, 'recent_p95': 0.0, 'recent_max': 0.0, 'recent_ge20': 0, 'recent_ge30': 0}
    eq = eq.copy()
    eq['time'] = pd.to_datetime(eq['time'])
    eq = eq.sort_values('time').set_index('time')
    monthly = pd.Series(dtype=float)
    for freq in ("ME", "M"):
        try:
            monthly = eq['equity'].resample(freq).last().pct_change().fillna(0.0)
            break
        except Exception:
            continue
    recent = monthly.tail(24)
    return {
        'recent_mean': float(recent.mean()) if not recent.empty else 0.0,
        'recent_p90': float(recent.quantile(0.90)) if not recent.empty else 0.0,
        'recent_p95': float(recent.quantile(0.95)) if not recent.empty else 0.0,
        'recent_max': float(recent.max()) if not recent.empty else 0.0,
        'recent_ge20': int((recent >= 0.20).sum()) if not recent.empty else 0,
        'recent_ge30': int((recent >= 0.30).sum()) if not recent.empty else 0,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default='config.yml')
    args = ap.parse_args()

    root = Path('.').resolve()
    py = root / '.venv' / 'bin' / 'python'
    reports = root / 'reports'
    scan_dir = reports / 'overfit_check'
    cfg_dir = scan_dir / 'configs'
    scan_dir.mkdir(parents=True, exist_ok=True)
    cfg_dir.mkdir(parents=True, exist_ok=True)

    with open(args.config, encoding='utf-8') as f:
        base_cfg = yaml.safe_load(f)

    variants: list[tuple[str, dict[str, Any]]] = [
        ('base', {}),
        ('lookback_20', {'strategy_params.breakout_lookback': 20}),
        ('lookback_28', {'strategy_params.breakout_lookback': 28}),
        ('buffer_045', {'strategy_params.breakout_atr_buffer': 0.45}),
        ('buffer_055', {'strategy_params.breakout_atr_buffer': 0.55}),
    ]

    rows: list[dict[str, Any]] = []
    print("\n====== 过拟合检查（robustness perturbation）======")
    for name, mods in variants:
        cfg = copy.deepcopy(base_cfg)
        base_ver = cfg.get('system', {}).get('version', 'NA')
        cfg.setdefault('system', {})['version'] = f'{base_ver}_{name}'
        for path, value in mods.items():
            _set_nested(cfg, path, value)
        cfg_path = cfg_dir / f'{name}.yml'
        cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding='utf-8')
        run_id = f'overfit_{name}'
        subprocess.run([str(py), '-m', 'src.main', '--config', str(cfg_path), '--run-id', run_id], check=True)

        run_dir = reports / f'run_{run_id}'
        metrics = json.loads((run_dir / 'metrics.json').read_text(encoding='utf-8'))['metrics']
        trades = pd.read_csv(run_dir / 'trades.csv') if (run_dir / 'trades.csv').exists() else pd.DataFrame()
        eq = pd.read_csv(run_dir / 'equity_curve.csv') if (run_dir / 'equity_curve.csv').exists() else pd.DataFrame()

        _, s1_pf, _ = _segment_stats(trades, 2020, 2021)
        _, s2_pf, _ = _segment_stats(trades, 2022, 2023)
        _, s3_pf, _ = _segment_stats(trades, 2024, 2026)
        seg_values = [v for v in [s1_pf, s2_pf, s3_pf] if v > 0]
        seg_min_pf = min(seg_values) if seg_values else 0.0
        m = _monthly_stats(eq)
        row = {
            'variant': name,
            'total_ret_pct': float(metrics['total_return']) * 100,
            'cagr_pct': float(metrics['cagr']) * 100,
            'maxdd_pct': float(metrics['max_drawdown']) * 100,
            'pf': float(metrics['profit_factor']),
            'trades': int(metrics['trades']),
            'win_rate_pct': float(metrics['win_rate']) * 100,
            'seg2020_21_pf': s1_pf,
            'seg2022_23_pf': s2_pf,
            'seg2024_26_pf': s3_pf,
            'seg_min_pf': seg_min_pf,
            'recent24_mean_pct': m['recent_mean'] * 100,
            'recent24_p90_pct': m['recent_p90'] * 100,
            'recent24_p95_pct': m['recent_p95'] * 100,
            'recent24_max_pct': m['recent_max'] * 100,
            'recent24_ge20': m['recent_ge20'],
            'recent24_ge30': m['recent_ge30'],
        }
        rows.append(row)
        print(
            f"{name:>10} | 收益 {row['total_ret_pct']:.2f}% | 年化 {row['cagr_pct']:.2f}% | "
            f"MaxDD {row['maxdd_pct']:.2f}% | PF {row['pf']:.2f} | T {row['trades']} | "
            f"seg_min_pf {row['seg_min_pf']:.2f} | recent>=20 {row['recent24_ge20']} | recent>=30 {row['recent24_ge30']}"
        )

    df = pd.DataFrame(rows)
    robust = df.sort_values(['seg_min_pf', 'pf', 'total_ret_pct'], ascending=[False, False, False]).iloc[0]
    recency = df.sort_values(['recent24_ge30', 'recent24_ge20', 'recent24_max_pct', 'pf'], ascending=[False, False, False, False]).iloc[0]

    df.to_csv(scan_dir / 'overfit_check_table.csv', index=False)
    summary_lines = [
        f"BEST_ROBUST: {robust['variant']} | PF {robust['pf']:.2f} | seg_min_pf {robust['seg_min_pf']:.2f} | 收益 {robust['total_ret_pct']:.2f}% | MaxDD {robust['maxdd_pct']:.2f}%",
        f"BEST_RECENT: {recency['variant']} | recent>=20 {int(recency['recent24_ge20'])} | recent>=30 {int(recency['recent24_ge30'])} | recent_max {recency['recent24_max_pct']:.2f}% | PF {recency['pf']:.2f}",
        '',
        '说明：主线升级建议同时满足：总PF>=1.25 且 seg_min_pf>=1.10，且 recent24 >=20% 月份次数不低于基线。',
    ]
    (scan_dir / 'overfit_check_summary.txt').write_text("\n".join(summary_lines) + "\n", encoding='utf-8')
    print('---------------------------------------------')
    print(summary_lines[0])
    print(summary_lines[1])
    print('结果表已写入 reports/overfit_check/overfit_check_table.csv')
    print('=============================================\n')


if __name__ == '__main__':
    main()
