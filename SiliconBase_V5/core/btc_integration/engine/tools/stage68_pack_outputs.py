from __future__ import annotations

import argparse
import contextlib
import zipfile
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path


def _read_first(paths: Iterable[Path]) -> tuple[Path | None, str]:
    for p in paths:
        try:
            if p.exists() and p.is_file():
                return p, p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
    return None, ""


def _mtime_ok(p: Path, started_at: int) -> bool:
    try:
        return p.exists() and int(p.stat().st_mtime) >= int(started_at)
    except Exception:
        return False


def _top_lines(txt: str, limit: int = 12) -> list[str]:
    return [line for line in txt.splitlines() if line.startswith("- ")][:limit]


def _build_deepseek(okx_txt: str, msg_txt: str, s59_main: str, s59_branch: str, s63_main: str, s63_branch: str, s64_main: str, s64_branch: str, s65_main: str, s65_branch: str) -> str:
    lines: list[str] = []
    lines.append("DeepSeek 单文件汇总")
    lines.append("==============")
    lines.append("")
    lines.append(f"生成时间: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append("")
    lines.append("一、自动盘状态")
    if okx_txt.strip():
        for line in okx_txt.splitlines()[:18]:
            if line.strip():
                lines.append(line)
    else:
        lines.append("- okx_demo_report_latest.txt 缺失")
    lines.append("")
    lines.append("二、消息面 risk overlay")
    lines.extend(_top_lines(msg_txt, 10) or ["- message_stack_backtest_latest.txt 缺失"])
    lines.append("")
    lines.append("三、Stage59 结构门")
    lines.extend(_top_lines(s59_main, 8) or ["- stage59_mainline_structural_latest.txt 缺失"])
    lines.extend(_top_lines(s59_branch, 8) or ["- stage59_branch_structural_latest.txt 缺失"])
    lines.append("")
    lines.append("四、Stage63 价格影响 + 结构")
    lines.extend(_top_lines(s63_main, 8) or ["- stage63_mainline_price_impact_latest.txt 缺失"])
    lines.extend(_top_lines(s63_branch, 8) or ["- stage63_branch_price_impact_latest.txt 缺失"])
    lines.append("")
    lines.append("五、Stage64 相关性 + 结构混合")
    lines.extend(_top_lines(s64_main, 8) or ["- stage64_mainline_hybrid_latest.txt 缺失"])
    lines.extend(_top_lines(s64_branch, 8) or ["- stage64_branch_hybrid_latest.txt 缺失"])
    lines.append("")
    lines.append("六、Stage65 价格影响前沿")
    lines.extend(_top_lines(s65_main, 8) or ["- stage65_mainline_impact_latest.txt 缺失"])
    lines.extend(_top_lines(s65_branch, 8) or ["- stage65_branch_impact_latest.txt 缺失"])
    lines.append("")
    lines.append("七、请直接判断")
    lines.append("- 主线是否继续保留 live_base，只把消息面留在 risk layer？")
    lines.append("- ETH/SOL 应先升独立 long/short engine，还是继续追 dual？")
    lines.append("- 哪个候选先接分支模拟盘更合理？")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage68 pack outputs")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--started-at", type=int, required=True)
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    reports_raw = root / "reports" / "research_raw"
    downloads = Path.home() / "Downloads"

    required = [
        reports_raw / "stage59_mainline_structural_latest.txt",
        reports_raw / "stage59_mainline_structural_latest.json",
        reports_raw / "stage59_branch_structural_latest.txt",
        reports_raw / "stage59_branch_structural_latest.json",
        reports_raw / "stage63_mainline_price_impact_latest.txt",
        reports_raw / "stage63_mainline_price_impact_latest.json",
        reports_raw / "stage63_branch_price_impact_latest.txt",
        reports_raw / "stage63_branch_price_impact_latest.json",
        reports_raw / "stage64_mainline_hybrid_latest.txt",
        reports_raw / "stage64_mainline_hybrid_latest.json",
        reports_raw / "stage64_branch_hybrid_latest.txt",
        reports_raw / "stage64_branch_hybrid_latest.json",
        reports_raw / "stage65_mainline_impact_latest.txt",
        reports_raw / "stage65_mainline_impact_latest.json",
        reports_raw / "stage65_branch_impact_latest.txt",
        reports_raw / "stage65_branch_impact_latest.json",
    ]
    stale = [p.name for p in required if not _mtime_ok(p, args.started_at)]
    if stale:
        raise SystemExit(f"stage68 报告没有被本轮刷新：{', '.join(stale)}")

    okx_p, okx_txt = _read_first([downloads / "okx_demo_report_latest.txt", root / "reports" / "okx_demo_report_latest.txt"])
    msg_p, msg_txt = _read_first([reports_raw / "message_stack_backtest_latest.txt"])

    s59_main_p = reports_raw / "stage59_mainline_structural_latest.txt"
    s59_main_j = reports_raw / "stage59_mainline_structural_latest.json"
    s59_branch_p = reports_raw / "stage59_branch_structural_latest.txt"
    s59_branch_j = reports_raw / "stage59_branch_structural_latest.json"
    s63_main_p = reports_raw / "stage63_mainline_price_impact_latest.txt"
    s63_main_j = reports_raw / "stage63_mainline_price_impact_latest.json"
    s63_branch_p = reports_raw / "stage63_branch_price_impact_latest.txt"
    s63_branch_j = reports_raw / "stage63_branch_price_impact_latest.json"
    s64_main_p = reports_raw / "stage64_mainline_hybrid_latest.txt"
    s64_main_j = reports_raw / "stage64_mainline_hybrid_latest.json"
    s64_branch_p = reports_raw / "stage64_branch_hybrid_latest.txt"
    s64_branch_j = reports_raw / "stage64_branch_hybrid_latest.json"
    s65_main_p = reports_raw / "stage65_mainline_impact_latest.txt"
    s65_main_j = reports_raw / "stage65_mainline_impact_latest.json"
    s65_branch_p = reports_raw / "stage65_branch_impact_latest.txt"
    s65_branch_j = reports_raw / "stage65_branch_impact_latest.json"
    local_info_p = reports_raw / "local_info_sources_latest.txt"
    poly_p = reports_raw / "polymarket_probe_latest.txt"
    poly_j = reports_raw / "polymarket_probe_latest.json"

    s59_main = s59_main_p.read_text(encoding="utf-8", errors="ignore")
    s59_branch = s59_branch_p.read_text(encoding="utf-8", errors="ignore")
    s63_main = s63_main_p.read_text(encoding="utf-8", errors="ignore")
    s63_branch = s63_branch_p.read_text(encoding="utf-8", errors="ignore")
    s64_main = s64_main_p.read_text(encoding="utf-8", errors="ignore")
    s64_branch = s64_branch_p.read_text(encoding="utf-8", errors="ignore")
    s65_main = s65_main_p.read_text(encoding="utf-8", errors="ignore")
    s65_branch = s65_branch_p.read_text(encoding="utf-8", errors="ignore")

    deepseek_out = downloads / "deepseek_single_file_latest.txt"
    deepseek_out.write_text(
        _build_deepseek(okx_txt, msg_txt, s59_main, s59_branch, s63_main, s63_branch, s64_main, s64_branch, s65_main, s65_branch),
        encoding="utf-8",
    )

    files_to_add: list[Path] = []
    seen = set()
    for p in [
        okx_p,
        msg_p,
        local_info_p,
        poly_p,
        poly_j,
        s59_main_p, s59_main_j, s59_branch_p, s59_branch_j,
        s63_main_p, s63_main_j, s63_branch_p, s63_branch_j,
        s64_main_p, s64_main_j, s64_branch_p, s64_branch_j,
        s65_main_p, s65_main_j, s65_branch_p, s65_branch_j,
        reports_raw / "current_demo_strategy_trades_latest.csv",
    ]:
        if p is not None and p.exists() and p.is_file() and p.name not in seen:
            seen.add(p.name)
            files_to_add.append(p)

    bundle_out = downloads / "chatgpt_bundle_latest.zip"
    with zipfile.ZipFile(bundle_out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        readme = [
            "ChatGPT Bundle",
            "==============",
            "",
            f"generated_at_utc={datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"project_dir={root}",
            f"stage59_mainline_mtime_utc={datetime.fromtimestamp(s59_main_p.stat().st_mtime, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"stage63_mainline_mtime_utc={datetime.fromtimestamp(s63_main_p.stat().st_mtime, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"stage64_mainline_mtime_utc={datetime.fromtimestamp(s64_main_p.stat().st_mtime, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"stage65_mainline_mtime_utc={datetime.fromtimestamp(s65_main_p.stat().st_mtime, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
            "",
            "files:",
        ]
        for p in files_to_add:
            readme.append(f"- {p.name}")
        zf.writestr("README_SEND_TO_CHATGPT.txt", "\n".join(readme).rstrip() + "\n")
        for p in files_to_add:
            zf.write(p, arcname=p.name)

    with zipfile.ZipFile(bundle_out, "r") as zf:
        names = set(zf.namelist())
    must_have = {
        "README_SEND_TO_CHATGPT.txt",
        "stage59_mainline_structural_latest.txt",
        "stage63_mainline_price_impact_latest.txt",
        "stage64_mainline_hybrid_latest.txt",
        "stage65_mainline_impact_latest.txt",
        "stage59_branch_structural_latest.txt",
        "stage63_branch_price_impact_latest.txt",
        "stage64_branch_hybrid_latest.txt",
        "stage65_branch_impact_latest.txt",
    }
    missing = must_have - names
    if missing:
        with contextlib.suppress(Exception):
            bundle_out.unlink(missing_ok=True)
        raise SystemExit(f"bundle 自检失败，缺少: {sorted(missing)}")

    print(bundle_out)
    print(deepseek_out)


if __name__ == "__main__":
    main()
