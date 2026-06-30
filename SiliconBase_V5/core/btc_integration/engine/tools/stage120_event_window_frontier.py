from __future__ import annotations

import argparse
import csv
from pathlib import Path

import pandas as pd


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def read_lines(path: Path) -> list[str]:
    return read_text(path).splitlines()


def find_line(lines: list[str], prefix: str) -> str | None:
    for line in lines:
        if line.startswith(prefix):
            return line
    return None


def capture_candidate_lines(lines: list[str], limit: int = 6) -> list[str]:
    out: list[str] = []
    in_block = False
    for line in lines:
        if line.startswith("=== 候选结果") or line.startswith("=== 主线候选") or line.startswith("=== 分支候选"):
            in_block = True
            continue
        if in_block and line.startswith("=== "):
            break
        if in_block and line.startswith("- "):
            out.append(line)
            if len(out) >= limit:
                break
    return out


def raw_meta(path: Path) -> str:
    if not path.exists():
        return "missing"
    try:
        with path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if not header:
                return "rows=0 first=- last=-"
            idx = next((i for i, c in enumerate(header) if str(c).strip() in {"time", "timestamp", "open_time", "ts", "datetime", "date"}), None)
            if idx is None:
                return "rows=0 first=- last=-"
            count = 0
            first_val = ""
            last_val = ""
            for row in reader:
                if idx >= len(row):
                    continue
                v = str(row[idx]).strip()
                if not v:
                    continue
                if not first_val:
                    first_val = v
                last_val = v
                count += 1
    except Exception as exc:
        return f"read_fail({exc})"
    if count <= 0:
        return "rows=0 first=- last=-"

    def parse(v: str):
        s = str(v).strip()
        if not s:
            return pd.NaT
        if s.isdigit() or (s.startswith("-") and s[1:].isdigit()):
            x = int(s)
            ax = abs(x)
            unit = "s" if ax < 10**11 else "ms" if ax < 10**14 else "us" if ax < 10**17 else "ns"
            return pd.to_datetime(x, unit=unit, utc=True, errors="coerce")
        return pd.to_datetime(s, utc=True, errors="coerce")

    first_ts = parse(first_val)
    last_ts = parse(last_val)
    return f"rows={count} first={first_ts if pd.notna(first_ts) else '-'} last={last_ts if pd.notna(last_ts) else '-'}"


def _section(lines: list[str], limit: int = 40) -> list[str]:
    return lines[:limit] if lines else ["- 未生成"]


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage120 event-window frontier summary")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    raw = root / "reports" / "research_raw"
    raw.mkdir(parents=True, exist_ok=True)

    s90_txt = raw / "stage90_mainline_event_alpha_matrix_latest.txt"
    s91_txt = raw / "stage91_branch_event_alpha_matrix_latest.txt"
    evs_txt = raw / "event_window_sweep_latest.txt"
    evw_txt = raw / "event_window_walkforward_latest.txt"

    okx = Path.home() / "Downloads" / "okx_demo_report_latest.txt"
    branch = Path.home() / "Downloads" / "branch_demo_report_latest.txt"
    if not okx.exists():
        okx = root / "okx_demo_report_latest.txt"
    if not branch.exists():
        branch = root / "branch_demo_report_latest.txt"

    s90_lines = read_lines(s90_txt)
    s91_lines = read_lines(s91_txt)
    evs_lines = read_lines(evs_txt)
    evw_lines = read_lines(evw_txt)
    okx_lines = read_lines(okx)
    branch_lines = read_lines(branch)

    lines: list[str] = []
    lines.append("Stage120 消息窗 / 事件桥接 前沿摘要")
    lines.append("原则：不动当前模拟盘；先让 sweep 与 walk-forward 口径同步，再看事件层能否从风险筛走向确认层。")
    lines.append("")

    lines.append("=== raw 状态 ===")
    lines.append(f"- BTC: {raw_meta(root / 'data' / 'raw' / 'btc_15m.csv')}")
    lines.append(f"- BNB: {raw_meta(root / 'data' / 'raw' / 'bnb_15m.csv')}")
    lines.append("")

    lines.append("=== 当前运行态 ===")
    for prefix in ["- 当前版本:", "- 当前状态:", "- 当前候选:"]:
        hit = find_line(okx_lines, prefix)
        if hit:
            lines.append("主线 " + hit)
    for prefix in ["- 当前版本:", "- 当前状态:", "- 当前候选:"]:
        hit = find_line(branch_lines, prefix)
        if hit:
            lines.append("分支 " + hit)
    lines.append("")

    lines.append("=== 主线候选（截取）===")
    lines.extend(capture_candidate_lines(s90_lines, limit=6) or ["- stage90 主线矩阵未生成"])
    lines.append("")

    lines.append("=== 分支候选（截取）===")
    lines.extend(capture_candidate_lines(s91_lines, limit=8) or ["- stage91 分支矩阵未生成"])
    lines.append("")

    lines.append("=== event_window_sweep ===")
    lines.extend(_section(evs_lines, limit=40))
    lines.append("")

    lines.append("=== event_window_walkforward ===")
    lines.extend(_section(evw_lines, limit=40))
    lines.append("")

    lines.append("=== 结论 ===")
    if any("blocked_trades: 0" in x for x in evw_lines[:20]):
        lines.append("- WF 仍未真正拦到单，事件层继续只保留研究属性。")
    elif any("fallback" in x for x in evw_lines):
        lines.append("- WF 已开始真实拦单，但当前主要还是 macro schedule fallback，不升 runtime alpha。")
    elif evw_lines:
        lines.append("- WF 已开始真实拦单，可以继续扩事件覆盖并细化 profile。")
    else:
        lines.append("- walk-forward 结果缺失，先补研究产物再谈联动。")
    if any("manual_no_positive_plus_macro_rule" in x for x in evw_lines):
        lines.append("- 当前最先起作用的是 manual_no_positive_plus_macro_rule，说明月度宏观近似窗比手工事件库更先覆盖到主线 trades。")
    lines.append("- 主线仍先看 dynlev_fix8_lock18，不回退到纯提频快版。")
    lines.append("- 分支继续保留 BTC/ETH/SOL 多空路径，但是否推模拟盘仍看近2年 + WF。")

    out = raw / "stage120_event_window_frontier_latest.txt"
    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
