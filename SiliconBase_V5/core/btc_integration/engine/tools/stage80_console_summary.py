from __future__ import annotations

import argparse
import re
from pathlib import Path


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _grab(text: str, label: str) -> str:
    m = re.search(rf"- {re.escape(label)}: (.+)", text)
    return m.group(1).strip() if m else ""


def _bullet_groups(txt: str, section_header: str, limit: int) -> list[list[str]]:
    groups: list[list[str]] = []
    in_sec = False
    current: list[str] = []
    for raw in txt.splitlines():
        line = raw.rstrip()
        if line.strip() == section_header:
            in_sec = True
            current = []
            continue
        if not in_sec:
            continue
        if line.startswith("=== ") or line.startswith("【"):
            if current:
                groups.append(current)
            break
        if line.strip().startswith("- "):
            if current:
                groups.append(current)
                if len(groups) >= limit:
                    break
            current = [line.strip()]
        elif current and line.startswith("  "):
            current.append(line.rstrip())
    if in_sec and current and len(groups) < limit:
        groups.append(current)
    return groups[:limit]


def _print_block(title: str, rows: list[list[str]]) -> None:
    print(title)
    if not rows:
        print("- 无")
        return
    for group in rows:
        for line in group:
            print(line)


def main() -> None:
    ap = argparse.ArgumentParser(description="打印 stage77/78 中文摘要到终端")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    raw = root / "reports" / "research_raw"
    downloads = Path.home() / "Downloads"

    okx_txt = _read_text(downloads / "okx_demo_report_latest.txt") or _read_text(root / "reports" / "okx_demo_report_latest.txt")
    main_txt = _read_text(raw / "stage77_mainline_dual_window_latest.txt")
    branch_txt = _read_text(raw / "stage78_branch_dual_window_latest.txt")

    print("=== 当前自动盘 ===")
    if okx_txt.strip():
        print(f"- 状态: {_grab(okx_txt, '当前状态')} | reason={_grab(okx_txt, '状态原因')} | 版本={_grab(okx_txt, '当前版本')}")
        print(f"- 心跳: {_grab(okx_txt, '报告心跳(UTC+8)')} | 下一轮: {_grab(okx_txt, '下一轮执行(UTC+8)')}")
        print(f"- 风险层: {_grab(okx_txt, '当前模式')} | 触发原因={_grab(okx_txt, '触发原因')}")
    else:
        print("- 未读到 okx_demo_report_latest.txt")

    print("")
    _print_block("=== 主线前2 ===", _bullet_groups(main_txt, "=== 候选结果 ===", 2))
    print("")
    _print_block("=== 分支赛道最优 ===", _bullet_groups(branch_txt, "=== 各赛道当前最优 ===", 4))


if __name__ == "__main__":
    main()
