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


def _top_lines(txt: str, limit: int = 18) -> list[str]:
    return [line for line in txt.splitlines() if line.startswith("- ")][:limit]


def _build_deepseek(okx_txt: str, stage45_txt: str, poly_txt: str) -> str:
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
    lines.append("二、Stage45 重点")
    lines.extend(_top_lines(stage45_txt, 24) or ["- stage45_targeted_lab_latest.txt 缺失"])
    if poly_txt.strip():
        lines.append("")
        lines.append("三、Polymarket")
        lines.extend(_top_lines(poly_txt, 10))
    lines.append("")
    lines.append("四、请重点给建议")
    lines.append("- 主线是保留 combo_sr_soft_ref，还是改走新的 stage45 第一候选？")
    lines.append("- SOL short shock 哪个变体最值得继续做，不和 long core 硬混？")
    lines.append("- 主线提频还有没有更稳的精准补漏方式？")
    lines.append("- Polymarket 作为 regime prior，还能补哪些低成本高信息密度特征？")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage45 pack outputs")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    downloads = Path.home() / "Downloads"
    reports_raw = root / "reports" / "research_raw"

    okx_p, okx_txt = _read_first([
        downloads / "okx_demo_report_latest.txt",
        root / "reports" / "okx_demo_report_latest.txt",
    ])
    s45_txt_p, s45_txt = _read_first([reports_raw / "stage45_targeted_lab_latest.txt"])
    s45_json_p = reports_raw / "stage45_targeted_lab_latest.json"
    poly_txt_p, poly_txt = _read_first([reports_raw / "polymarket_probe_latest.txt"])
    poly_json_p = reports_raw / "polymarket_probe_latest.json"

    deepseek_out = downloads / "deepseek_single_file_latest.txt"
    deepseek_out.write_text(_build_deepseek(okx_txt, s45_txt, poly_txt), encoding="utf-8")

    bundle_out = downloads / "chatgpt_bundle_latest.zip"
    files_to_add: list[Path] = []
    seen = set()
    for p in [okx_p, s45_txt_p, s45_json_p if s45_json_p.exists() else None, poly_txt_p, poly_json_p if poly_json_p.exists() else None]:
        if p is not None and p.exists() and p.is_file() and p.name not in seen:
            seen.add(p.name)
            files_to_add.append(p)
    for name in [
        "mainline_density_lab_latest.txt",
        "mainline_density_lab_latest.json",
        "message_stack_backtest_latest.txt",
        "alt_shortwave_message_overlay_latest.txt",
        "alt_shortwave_symbol_overlay_latest.json",
        "local_info_sources_latest.txt",
        "current_demo_strategy_trades_latest.csv",
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
