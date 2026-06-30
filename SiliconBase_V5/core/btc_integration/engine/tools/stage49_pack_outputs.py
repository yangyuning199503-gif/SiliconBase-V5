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


def _top_lines(txt: str, limit: int = 24) -> list[str]:
    return [line for line in txt.splitlines() if line.startswith("- ")][:limit]


def _build_deepseek(okx_txt: str, stage49_txt: str, stage48_txt: str, stage47_txt: str) -> str:
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
    lines.append("二、Stage49 激进冲刺")
    lines.extend(_top_lines(stage49_txt, 28) or ["- stage49_aggressive_sprint_latest.txt 缺失"])
    lines.append("")
    lines.append("三、上一轮参考")
    lines.extend(_top_lines(stage48_txt, 12) or _top_lines(stage47_txt, 12) or ["- stage48/stage47 报告缺失"])
    lines.append("")
    lines.append("四、请重点给建议")
    lines.append("- 主线在 212~220 笔区间，应该优先再放松哪一个：adx、lookback、zone 还是 cooldown？")
    lines.append("- SOL 更适合继续加快信号，还是保留信号质量、只抬 stake_scale？")
    lines.append("- 若 SOL months>=20% 仍偏少，应该先接事件门控，还是先做执行层分批加仓？")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage49 pack outputs")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    downloads = Path.home() / "Downloads"
    reports_raw = root / "reports" / "research_raw"

    okx_p, okx_txt = _read_first([
        downloads / "okx_demo_report_latest.txt",
        root / "reports" / "okx_demo_report_latest.txt",
    ])
    s49_txt_p, s49_txt = _read_first([reports_raw / "stage49_aggressive_sprint_latest.txt"])
    s49_json_p = reports_raw / "stage49_aggressive_sprint_latest.json"
    s48_txt_p, s48_txt = _read_first([reports_raw / "stage48_aggressive_refine_lab_latest.txt"])
    s48_json_p = reports_raw / "stage48_aggressive_refine_lab_latest.json"
    s47_txt_p, s47_txt = _read_first([reports_raw / "stage47_tranche_lock_lab_latest.txt"])
    s47_json_p = reports_raw / "stage47_tranche_lock_lab_latest.json"

    deepseek_out = downloads / "deepseek_single_file_latest.txt"
    deepseek_out.write_text(_build_deepseek(okx_txt, s49_txt, s48_txt, s47_txt), encoding="utf-8")

    bundle_out = downloads / "chatgpt_bundle_latest.zip"
    files_to_add: list[Path] = []
    seen = set()

    for p in [okx_p, s49_txt_p, s49_json_p if s49_json_p.exists() else None, s48_txt_p, s48_json_p if s48_json_p.exists() else None, s47_txt_p, s47_json_p if s47_json_p.exists() else None]:
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
