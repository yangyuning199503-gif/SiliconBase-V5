from __future__ import annotations

import argparse
import json
import math
import zipfile
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _pct(v: Any) -> str:
    try:
        fv = float(v)
    except Exception:
        return "-"
    if math.isnan(fv):
        return "-"
    return f"{fv * 100:.2f}%"


def _num(v: Any, digits: int = 3) -> str:
    try:
        fv = float(v)
    except Exception:
        return "-"
    if math.isnan(fv):
        return "-"
    return f"{fv:.{digits}f}"


def _trades(v: Any) -> str:
    try:
        return str(int(float(v)))
    except Exception:
        return "-"


def _recent_metrics(row: dict[str, Any]) -> dict[str, Any]:
    dg = row.get("dominant_gate") or {}
    return dg.get("recent_metrics") or row.get("recent_metrics") or {}


def _wf_metrics(row: dict[str, Any]) -> dict[str, Any]:
    wf = row.get("walkforward") or {}
    return wf.get("metrics") or {}


def _summ_main(row: dict[str, Any]) -> str:
    if not row:
        return "- 缺结果"
    recent = _recent_metrics(row)
    wf = _wf_metrics(row)
    return (
        f"- {row.get('name','-')}: 近2年 收益={_pct(recent.get('ret'))} 月化={_pct(recent.get('monthlyized_ret'))} "
        f"PF={_num(recent.get('pf'))} 交易={_trades(recent.get('trades'))} | "
        f"WF 收益={_pct(wf.get('ret'))} 月化={_pct(wf.get('monthlyized_ret'))} PF={_num(wf.get('pf'))} 交易={_trades(wf.get('trades'))}"
    )


def _summ_branch(row: dict[str, Any]) -> str:
    if not row:
        return "- 缺结果"
    recent = _recent_metrics(row)
    wf = _wf_metrics(row)
    gate = (row.get("dominant_gate") or {}).get("gate_name") or row.get("best_gate") or "-"
    return (
        f"- {row.get('name','-')}: gate={gate} | 近2年 收益={_pct(recent.get('ret'))} 月化={_pct(recent.get('monthlyized_ret'))} "
        f"PF={_num(recent.get('pf'))} 交易={_trades(recent.get('trades'))} | "
        f"WF 收益={_pct(wf.get('ret'))} 月化={_pct(wf.get('monthlyized_ret'))} PF={_num(wf.get('pf'))} 交易={_trades(wf.get('trades'))}"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Pack Stage116 single export")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--out-zip", default=str(Path.home() / "Downloads" / "stage116_joint_dual_uplift_latest.zip"))
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    raw = root / "reports" / "research_raw"
    downloads = Path.home() / "Downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    out_zip = Path(args.out_zip).expanduser().resolve()
    out_zip.parent.mkdir(parents=True, exist_ok=True)

    _load_json(raw / "stage90_mainline_event_alpha_matrix_latest.json")
    _load_json(raw / "stage91_branch_event_alpha_matrix_latest.json")
    s92 = _load_json(raw / "stage92_eth_sol_open_frontier_latest.json")
    s93 = _load_json(raw / "stage93_frequency_accel_latest.json")
    btc = _load_json(raw / "btc_dual_branch_lab_latest.json")

    mainline = s93.get("mainline") or {}
    branch = s93.get("branch") or {}
    btc_best = btc.get("best") or {}
    stage92_demo = s92.get("demo_candidates") or {}
    fusion_best = s92.get("fusion_best_by_lane") or {}

    lines = []
    lines.append("Stage116 联合推进结果")
    lines.append("口径：主线不动 live，只更新研究判断；第二分支保持 BTC/ETH/SOL 三标的。")
    lines.append("")
    lines.append("=== 主线 ===")
    lines.append(f"- live_keep: {_summ_main(mainline.get('live') or {})}")
    lines.append(f"- shadow_balanced: {_summ_main(mainline.get('balanced') or {})}")
    lines.append(f"- shadow_aggressive: {_summ_main(mainline.get('aggressive') or {})}")
    lines.append("")
    lines.append("=== 支线三标的 / 四腿 ===")
    lines.append(f"- BTC best: {btc_best.get('name','-')} | decision={btc_best.get('decision','-')} | trades={_trades(btc_best.get('trades'))} | PF={_num(btc_best.get('profit_factor'))} | ret={_pct(btc_best.get('total_return'))} | maxDD={_pct(btc_best.get('max_drawdown'))}")
    for lane in ["eth_long", "eth_short", "sol_long", "sol_short"]:
        lines.append(f"- {lane}: {_summ_branch(branch.get(lane) or {})}")
    lines.append("")
    lines.append("=== Stage92 新增 demo 候选 ===")
    if stage92_demo:
        for lane in ["eth_short", "sol_long", "eth_long", "sol_short"]:
            if lane in stage92_demo:
                lines.append(f"- {lane}: {stage92_demo[lane]}")
    else:
        lines.append("- 无新增 demo_ready 候选")
    lines.append("")
    lines.append("=== 事件优先领先候选 ===")
    for lane in ["eth_long", "eth_short", "sol_long", "sol_short"]:
        row = fusion_best.get(lane) or {}
        if not row:
            continue
        dom = row.get("dominant_gate") or {}
        wf = _wf_metrics(row)
        lines.append(
            f"- {lane}: {row.get('name','-')} | gate={dom.get('gate_name','-')} | event_share={_num(row.get('event_fold_share'),2)} | WF 月化={_pct(wf.get('monthlyized_ret'))} PF={_num(wf.get('pf'))}"
        )
    lines.append("")
    lines.append("=== 当前动作建议 ===")
    lines.append(f"- 主线 live: 保留 {((mainline.get('live') or {}).get('name')) or 'mainline_live_base'}")
    lines.append(f"- 主线提频 shadow: 继续观察 {((mainline.get('balanced') or {}).get('name')) or '-'}")
    lines.append(f"- 第二分支 BTC: {btc_best.get('decision','继续研究')}")
    lines.append(f"- 第二分支 ETH/SOL: 以 {stage92_demo.get('eth_short') or ((branch.get('eth_short') or {}).get('name')) or '-'} 为当前主收益腿，SOL 继续 frontier")

    summary_path = raw / "stage116_joint_dual_uplift_latest.txt"
    summary_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    include = [
        raw / "stage116_progress_latest.txt",
        summary_path,
        raw / "stage90_mainline_event_alpha_matrix_latest.txt",
        raw / "stage90_mainline_event_alpha_matrix_latest.json",
        raw / "stage91_branch_event_alpha_matrix_latest.txt",
        raw / "stage91_branch_event_alpha_matrix_latest.json",
        raw / "stage92_eth_sol_open_frontier_latest.txt",
        raw / "stage92_eth_sol_open_frontier_latest.json",
        raw / "stage93_frequency_accel_latest.txt",
        raw / "stage93_frequency_accel_latest.json",
        raw / "btc_dual_branch_lab_latest.txt",
        raw / "btc_dual_branch_lab_latest.json",
        root / "config_mainline_shadow_candidate.yml",
        root / "config_shortwave_candidate.yml",
        Path.home() / "Downloads" / "okx_demo_report_latest.txt",
        Path.home() / "Downloads" / "branch_demo_report_latest.txt",
    ]

    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in include:
            if path.exists() and path.is_file():
                zf.write(path, arcname=path.name)

    print(out_zip)


if __name__ == "__main__":
    main()
