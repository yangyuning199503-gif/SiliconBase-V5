from __future__ import annotations

import argparse
from collections.abc import Iterable
from pathlib import Path


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _pick_line(text: str, keyword: str) -> str:
    for line in text.splitlines():
        if keyword in line:
            return line.strip()
    return ""


def _extract_field(txt: str, label: str) -> str:
    for line in txt.splitlines():
        s = line.strip()
        if s.startswith(f"- {label}:"):
            return s.split(":", 1)[1].strip()
    return ""


def _extract_state(txt: str) -> str:
    state = _extract_field(txt, "当前状态")
    reason = _extract_field(txt, "状态原因")
    latest_kline = _extract_field(txt, "最近已完成 15m K 线开盘(UTC+8)")
    fills = _extract_field(txt, "策略真实成交已开始")
    parts = [x for x in [state, reason, f"latest={latest_kline}" if latest_kline else "", f"fills={fills}" if fills else ""] if x]
    return " | ".join(parts) if parts else "未读到状态"


def _first_existing(paths: Iterable[Path]) -> Path | None:
    for p in paths:
        if p.exists() and p.is_file():
            return p
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage98 三线模拟盘接线摘要")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--mainline-shadow-candidate", default="combo_sr_soft_adx26_cd6_lb24_zone028_ref")
    ap.add_argument("--branch-candidate", default="eth_short_shock_fast_lb16_atr052_adx22_s078")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    raw = root / "reports" / "research_raw"
    raw.mkdir(parents=True, exist_ok=True)
    out_txt = raw / "stage98_triple_demo_wire_latest.txt"

    stage90 = _read_text(raw / "stage90_mainline_event_alpha_matrix_latest.txt")
    stage91 = _read_text(raw / "stage91_branch_event_alpha_matrix_latest.txt")
    stage81 = _read_text(raw / "stage81_mainline_walkforward_latest.txt")
    okx_txt = _read_text(Path.home() / "Downloads" / "okx_demo_report_latest.txt")
    branch_txt = _read_text(Path.home() / "Downloads" / "branch_demo_report_latest.txt")
    shadow_report_p = _first_existing([
        raw / "mainline_shadow_demo_report_latest.txt",
        root / "reports" / "mainline_shadow_demo_report_latest.txt",
    ])
    shadow_txt = _read_text(shadow_report_p) if shadow_report_p else ""

    lines: list[str] = []
    lines.append("Stage98 三线模拟盘接线")
    lines.append("====================")
    lines.append("")
    lines.append("【三条线】")
    lines.append("- 主线 live: mainline_live_base")
    lines.append(f"- 主线 shadow: {args.mainline_shadow_candidate}")
    lines.append(f"- 分支 demo: {args.branch_candidate}")
    lines.append("")
    lines.append("【主线回测】")
    live_line = _pick_line(stage90, "mainline_live_base:") or _pick_line(stage81, "mainline_live_base:")
    shadow_line = _pick_line(stage90, f"{args.mainline_shadow_candidate}:") or _pick_line(stage81, f"{args.mainline_shadow_candidate}:")
    if live_line:
        lines.append(f"- {live_line}")
    if shadow_line:
        lines.append(f"- {shadow_line}")
    lines.append("")
    lines.append("【分支回测】")
    branch_line = _pick_line(stage91, f"{args.branch_candidate}:")
    if branch_line:
        lines.append(f"- {branch_line}")
    lines.append("")
    lines.append("【当前状态】")
    lines.append(f"- 主线 live: {_extract_state(okx_txt)}")
    lines.append(f"- 主线 shadow: {_extract_state(shadow_txt)}")
    lines.append(f"- 分支 demo: {_extract_state(branch_txt)}")
    lines.append("")
    lines.append("【执行结论】")
    lines.append("- live 继续 mainline_live_base，不切生产。")
    lines.append("- shadow 先接 combo_sr_soft_adx26_cd6_lb24_zone028_ref，目标是提频验证，不替生产。")
    lines.append("- 分支先接 ETH short fast；ETH/SOL 其余路径继续留在研究层并跑。")
    out_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(out_txt)


if __name__ == "__main__":
    main()
