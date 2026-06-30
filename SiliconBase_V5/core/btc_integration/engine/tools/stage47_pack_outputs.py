from __future__ import annotations

import argparse
import zipfile
from datetime import datetime, timezone
from pathlib import Path


def _read_first(paths: list[Path]) -> tuple[Path | None, str]:
    for p in paths:
        try:
            if p.exists() and p.is_file():
                return p, p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
    return None, ""


def _top_lines(txt: str, limit: int = 20) -> list[str]:
    return [line for line in txt.splitlines() if line.startswith("- ")][:limit]


def _build_deepseek(okx_txt: str, stage47_txt: str) -> str:
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
    lines.append("二、Stage47 固定分仓 + 盈利锁盈实验")
    lines.extend(_top_lines(stage47_txt, 24) or ["- stage47_tranche_lock_lab_latest.txt 缺失"])
    lines.append("")
    lines.append("三、请重点给建议")
    lines.append("- 固定分仓 + 盈利锁盈更适合主线还是 SOL long core？")
    lines.append("- 如果只保留一种执行风控，是 8 份固定仓更合适，还是继续 dynamic_equity 更稳？")
    lines.append("- 锁盈触发点和最小锁盈比例应该怎么设，才不至于把趋势利润切掉？")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage47 pack outputs")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    downloads = Path.home() / "Downloads"
    reports_raw = root / "reports" / "research_raw"

    okx_p, okx_txt = _read_first([
        downloads / "okx_demo_report_latest.txt",
        root / "reports" / "okx_demo_report_latest.txt",
    ])
    s47_txt_p, s47_txt = _read_first([reports_raw / "stage47_tranche_lock_lab_latest.txt"])
    s47_json_p = reports_raw / "stage47_tranche_lock_lab_latest.json"

    deepseek_out = downloads / "deepseek_single_file_latest.txt"
    deepseek_out.write_text(_build_deepseek(okx_txt, s47_txt), encoding="utf-8")

    bundle_out = downloads / "chatgpt_bundle_latest.zip"
    files_to_add: list[Path] = []
    seen = set()

    for p in [okx_p, s47_txt_p, s47_json_p if s47_json_p.exists() else None]:
        if p is not None and p.exists() and p.is_file() and p.name not in seen:
            seen.add(p.name)
            files_to_add.append(p)

    for name in [
        "stage46_aggressive_lab_latest.txt",
        "stage46_aggressive_lab_latest.json",
        "polymarket_probe_latest.txt",
        "polymarket_probe_latest.json",
        "mainline_density_lab_latest.txt",
        "mainline_density_lab_latest.json",
        "message_stack_backtest_latest.txt",
        "alt_shortwave_message_overlay_latest.txt",
        "alt_shortwave_symbol_overlay_latest.json",
        "local_info_sources_latest.txt",
        "current_demo_strategy_trades_latest.csv",
        "stage45_targeted_lab_latest.txt",
        "stage45_targeted_lab_latest.json",
        "stage44_priority_lab_latest.txt",
        "stage44_priority_lab_latest.json",
        "stage43_efficiency_lab_latest.txt",
        "stage43_efficiency_lab_latest.json",
    ]:
        p = reports_raw / name
        if not p.exists():
            p = root / "reports" / name
        if p.exists() and p.is_file() and p.name not in seen:
            seen.add(p.name)
            files_to_add.append(p)

    with zipfile.ZipFile(bundle_out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        readme = [
            "ChatGPT Bundle",
            "==============",
            "",
            f"generated_at_utc={datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"project_dir={root}",
            "",
            "包含文件：",
        ]
        for p in files_to_add:
            readme.append(f"- {p.name}")
        zf.writestr("README_SEND_TO_CHATGPT.txt", "\n".join(readme).rstrip() + "\n")
        for p in files_to_add:
            zf.write(p, arcname=p.name)


if __name__ == "__main__":
    main()
