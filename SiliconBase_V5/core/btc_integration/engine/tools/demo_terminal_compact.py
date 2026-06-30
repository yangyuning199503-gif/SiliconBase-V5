from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

LABEL_RE = re.compile(r"^-\s*(.+?):\s*(.*)$")
SYMBOL_HEADER_RE = re.compile(r"^\[([A-Z0-9_\-]+)\]$")


STATUS_MAP = {
    "等待下一轮": "等待下一轮",
    "启动中": "启动中",
    "启动失败": "启动失败",
}


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def grab(text: str, label: str) -> str:
    m = re.search(rf"-\s*{re.escape(label)}:\s*(.+)", text)
    return m.group(1).strip() if m else ""


def short_time(v: str) -> str:
    if not v:
        return "-"
    m = re.search(r"(\d{2}:\d{2}:\d{2})", v)
    return m.group(1) if m else v


def parse_available_usdt(text: str) -> str:
    raw = grab(text, "账户真实可用金额参考")
    if not raw:
        return "-"
    m = re.search(r"USDT\.avail=([0-9.\-]+)", raw)
    if m:
        return f"{float(m.group(1)):.2f} USDT"
    m = re.search(r"availEq=([0-9.\-]+)\s*USDT", raw)
    if m:
        return f"{float(m.group(1)):.2f} USDT"
    return raw


def parse_symbol_sections(text: str) -> dict[str, dict[str, str]]:
    sections: dict[str, dict[str, str]] = {}
    current_symbol: str | None = None
    current_section = ""
    for raw in text.splitlines():
        line = raw.rstrip()
        header = SYMBOL_HEADER_RE.match(line.strip())
        if header:
            current_symbol = header.group(1)
            current_section = current_symbol
            sections[current_symbol] = {}
            continue
        if not current_symbol:
            continue
        if line.startswith("【"):
            current_symbol = None
            current_section = ""
            continue
        m = LABEL_RE.match(line.strip())
        if m:
            key, value = m.group(1).strip(), m.group(2).strip()
            sections[current_section][key] = value
    return sections


HOLDING_RE = re.compile(
    r"side=(?P<side>[A-Z]+)\s+signed_qty=(?P<signed_qty>[-0-9.]+)\s+abs_qty=(?P<abs_qty>[0-9.]+)\s+浮盈亏=(?P<upl>[-0-9.]+)U\s+名义价值=(?P<notional>[-0-9.]+)U"
)
SHARED_RE = re.compile(
    r"side=(?P<side>[A-Z]+)\s+signed_qty=(?P<signed_qty>[-0-9.]+).+?名义价值=(?P<notional>[-0-9.]+)U"
)


def parse_holding_line(raw: str) -> dict[str, str]:
    raw = raw or ""
    m = HOLDING_RE.search(raw)
    if not m:
        side = "FLAT" if "side=FLAT" in raw else "-"
        return {"side": side, "qty": "0", "upl": "0", "notional": "0"}
    d = m.groupdict()
    return {
        "side": d["side"],
        "qty": d["abs_qty"],
        "upl": d["upl"],
        "notional": d["notional"],
    }


def parse_shared_line(raw: str) -> dict[str, str] | None:
    raw = raw or ""
    m = SHARED_RE.search(raw)
    if not m:
        return None
    d = m.groupdict()
    return {"side": d["side"], "qty": d["signed_qty"].lstrip("-"), "notional": d["notional"]}


def side_cn(side: str) -> str:
    mapping = {
        "LONG": "多",
        "SHORT": "空",
        "FLAT": "空仓",
        "NONE": "无",
        "-": "-",
    }
    return mapping.get(side, side)


def render_symbol_line(symbol: str, sec: dict[str, str]) -> str:
    holding = parse_holding_line(sec.get("当前持仓", ""))
    parts: list[str] = [f"{symbol}: {side_cn(holding['side'])}"]
    if holding["side"] != "FLAT":
        parts.append(f"数量 {holding['qty']}")
        parts.append(f"当前收益 {holding['upl']}U")
        parts.append(f"名义 {holding['notional']}U")
    shared = parse_shared_line(sec.get("共享账户观测仓位(仅提示)", ""))
    if shared:
        parts.append(f"共享观测 {side_cn(shared['side'])} {shared['qty']}")
    note = sec.get("仓位说明", "")
    if note and note not in {"-", "none"}:
        if note == "shared_account_overlap_hidden_until_first_branch_fill":
            parts.append("说明=共享账户隐藏")
        elif note == "demo_execution_disabled_for_symbol":
            parts.append("说明=当前禁用")
        else:
            parts.append(f"说明={note}")
    return " | ".join(parts)


def print_compact(report_path: Path, title: str, mode: str, backend_alive: bool) -> int:
    txt = read_text(report_path)
    if os.environ.get("TERM"):
        os.system("clear")
    print(title)
    if not txt.strip():
        print("报告文件尚未生成。")
        print(f"报告: {report_path}")
        return 0

    status = STATUS_MAP.get(grab(txt, "当前状态"), grab(txt, "当前状态") or "-")
    next_run = short_time(grab(txt, "下一轮执行(UTC+8)"))
    heartbeat = grab(txt, "报告心跳(UTC+8)") or grab(txt, "生成时间(UTC+8)")
    avail = parse_available_usdt(txt)
    realized = grab(txt, "策略累计已实现收益") or "-"
    unrealized = grab(txt, "策略当前未实现收益") or grab(txt, "当前策略浮盈亏估计") or "-"
    total = grab(txt, "策略当前总收益") or "-"
    live_started = grab(txt, "策略真实成交已开始") or "-"

    print(f"时间: {heartbeat}")
    print(f"后台: {'运行中' if backend_alive else '未运行'} | 状态: {status} | 下一轮: {next_run}")
    print(f"剩余金额: {avail} | 已实现: {realized} | 当前收益: {unrealized} | 总收益: {total}")
    print(f"真实成交已开始: {live_started}")
    print("-" * 72)
    print("当前持仓:")

    sections = parse_symbol_sections(txt)
    preferred = ["BTC", "BNB"] if mode == "mainline" else ["BTC", "ETH", "SOL"]
    printed = False
    for symbol in preferred:
        sec = sections.get(symbol)
        if not sec:
            continue
        print(f"- {render_symbol_line(symbol, sec)}")
        printed = True
    if not printed:
        print("- 暂无持仓信息")
    print("-" * 72)
    print(f"详细报告: {report_path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="极简终端监控：只显示持仓/方向/金额/收益")
    ap.add_argument("--report-file", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--mode", choices=["mainline", "branch"], required=True)
    ap.add_argument("--pid-file", default="")
    args = ap.parse_args()

    pid_file = Path(args.pid_file).expanduser() if args.pid_file else None
    alive = False
    if pid_file and pid_file.exists():
        try:
            pid = pid_file.read_text(encoding="utf-8", errors="ignore").strip()
            if pid:
                os.kill(int(pid), 0)
                alive = True
        except Exception:
            alive = False

    return print_compact(Path(args.report_file).expanduser(), args.title, args.mode, alive)


if __name__ == "__main__":
    raise SystemExit(main())
