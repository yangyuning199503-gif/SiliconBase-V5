from __future__ import annotations

import argparse
from pathlib import Path


def read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8", errors="ignore").splitlines()


def first_line_starting(lines: list[str], prefix: str) -> str | None:
    for line in lines:
        if line.startswith(prefix):
            return line
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage119 joint event-tech bridge summary")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    raw = root / "reports" / "research_raw"
    raw.mkdir(parents=True, exist_ok=True)

    s75 = read_lines(raw / "stage75_mainline_event_state_latest.txt")
    s90 = read_lines(raw / "stage90_mainline_event_alpha_matrix_latest.txt")
    s91 = read_lines(raw / "stage91_branch_event_alpha_matrix_latest.txt")
    okx = read_lines(Path.home() / "Downloads" / "okx_demo_report_latest.txt") or read_lines(root / "okx_demo_report_latest.txt")
    br = read_lines(Path.home() / "Downloads" / "branch_demo_report_latest.txt") or read_lines(root / "branch_demo_report_latest.txt")

    lines: list[str] = []
    lines.append("Stage119 主线/支线 消息面×技术面 联动摘要")
    lines.append("原则：不动当前两条模拟盘；先把消息面从 veto 提升到放行/确认层，再决定升级。")
    lines.append("")

    lines.append("=== 主线 ===")
    for p in [
        "- mainline_live_dynlev_fix8_lock18:",
        "- mainline_core_satellite_dynlev_fix8_lock18:",
        "- combo_sr_soft_adx26_cd6_lb24_zone028_ref:",
        "- mainline_live_base:",
    ]:
        hit = first_line_starting(s90, p)
        if hit:
            lines.append(hit)
    if s75:
        lines.append("- stage75 已补充事件状态机前沿（见附带文件），用于判断消息面是否能从 veto 升级成放行层。")
    else:
        lines.append("- stage75 本轮未成功生成；先沿用 stage90 结论。")
    lines.append("- 当前判断：主线仍不直接切 live；优先观察结构版 dynlev_fix8_lock18，频次型候选继续留研究层。")
    lines.append("")

    lines.append("=== 第二分支（BTC / ETH / SOL）===")
    for p in [
        "- BTC | short:",
        "- BTC | dual:",
        "- ETH | short:",
        "- ETH | long:",
        "- SOL | long:",
        "- SOL | short:",
    ]:
        hit = first_line_starting(s91, p)
        if hit:
            lines.append(hit)
    lines.append("- 当前判断：ETH short 继续 active 观察；BTC 保留 short/dual 双路径；SOL 继续 research_only，不直接推 active。")
    lines.append("")

    lines.append("=== 当前模拟盘运行态 ===")
    for prefix in ["- 当前版本:", "- 当前状态:", "- 当前候选:"]:
        hit = first_line_starting(okx, prefix)
        if hit:
            lines.append("主线 " + hit)
    for prefix in ["- 当前版本:", "- 当前状态:", "- 当前候选:"]:
        hit = first_line_starting(br, prefix)
        if hit:
            lines.append("分支 " + hit)
    lines.append("")

    lines.append("=== 结论 ===")
    lines.append("- 主线：先不升 live；先把事件放行层做实，再决定是否把 dynlev_fix8_lock18 升 shadow 常驻。")
    lines.append("- 支线：继续三标的框架，但当前仍以 ETH short 为主收益腿，BTC/SOL 继续补样本与事件桥接。")
    lines.append("- 下一步：只做一轮更窄的 event-state / bridge frontier，不再重复大包全跑。")

    out = raw / "stage119_summary_latest.txt"
    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
