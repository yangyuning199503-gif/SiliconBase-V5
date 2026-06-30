from __future__ import annotations

import argparse
import re
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


def _copy_if_exists(src: Path, dst: Path) -> None:
    if not src.exists() or not src.is_file():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(src.read_bytes())


def _parse_line_value(txt: str, label: str) -> str:
    m = re.search(rf"- {re.escape(label)}: (.+)", txt)
    return m.group(1).strip() if m else "-"


def _build_deepseek(okx_txt: str, stage43_txt: str, poly_txt: str) -> str:
    lines: list[str] = []
    lines.append("DeepSeek 单文件汇总")
    lines.append("==============")
    lines.append("")
    lines.append(f"生成时间: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append("")
    lines.append("一、自动盘状态")
    lines.append(f"- 状态: {_parse_line_value(okx_txt, '当前状态')} | reason={_parse_line_value(okx_txt, '状态原因')} | next={_parse_line_value(okx_txt, '下一轮执行(UTC+8)')}")
    lines.append(f"- CoinGlass: mode={_parse_line_value(okx_txt, '当前模式')} | pause_new_entries={_parse_line_value(okx_txt, '是否会暂停新开仓')} | trigger={_parse_line_value(okx_txt, '触发原因')}")
    lines.append("")
    lines.append("二、Stage43 重点")
    lines.extend([line for line in stage43_txt.splitlines() if line.startswith("- ")][:16])
    lines.append("")
    lines.append("三、Polymarket")
    lines.extend([line for line in poly_txt.splitlines() if line.startswith("- ")][:8])
    lines.append("")
    lines.append("四、请重点给建议")
    lines.append("- 如何在保持 PF / MaxDD 的前提下，继续提高主线交易频次？")
    lines.append("- SOL long-only core 之后，short shock engine 最稳的触发组合应该是什么？")
    lines.append("- ETH tactical overlay 是否值得保留，还是继续降权？")
    lines.append("- Polymarket 更适合 risk gate、regime prior，还是 tactical trigger？")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage43 pack outputs")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    downloads = Path.home() / "Downloads"
    reports = root / "reports" / "research_raw"

    okx_p, okx_txt = _read_first([
        downloads / "okx_demo_report_latest.txt",
        root / "reports" / "okx_demo_report_latest.txt",
    ])
    stage43_txt_p, stage43_txt = _read_first([reports / "stage43_efficiency_lab_latest.txt"])
    stage43_json_p = reports / "stage43_efficiency_lab_latest.json"
    poly_txt_p, poly_txt = _read_first([reports / "polymarket_probe_latest.txt"])
    poly_json_p = reports / "polymarket_probe_latest.json"

    deepseek_text = _build_deepseek(okx_txt, stage43_txt, poly_txt)
    deepseek_out = downloads / "deepseek_single_file_latest.txt"
    deepseek_out.write_text(deepseek_text, encoding="utf-8")

    bundle_out = downloads / "chatgpt_bundle_latest.zip"
    with zipfile.ZipFile(bundle_out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        readme = []
        readme.append("ChatGPT Bundle")
        readme.append("==============")
        readme.append("")
        readme.append(f"generated_at_utc={datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
        readme.append(f"project_dir={root}")
        readme.append("")
        readme.append("包含文件：")
        files_to_add = []
        for p in [okx_p, stage43_txt_p, stage43_json_p if stage43_json_p.exists() else None, poly_txt_p, poly_json_p if poly_json_p.exists() else None]:
            if p is not None and p.exists() and p.is_file():
                files_to_add.append(p)
                readme.append(f"- {p.name}")
        # keep standard research files if present
        for name in [
            "mainline_density_lab_latest.txt",
            "mainline_density_lab_latest.json",
            "message_stack_backtest_latest.txt",
            "alt_shortwave_message_overlay_latest.txt",
            "alt_shortwave_symbol_overlay_latest.json",
            "current_demo_strategy_trades_latest.csv",
        ]:
            p = reports / name
            if not p.exists():
                p = root / "reports" / name
            if p.exists() and p.is_file():
                files_to_add.append(p)
                readme.append(f"- {p.name}")
        zf.writestr("README_SEND_TO_CHATGPT.txt", "\n".join(readme).rstrip() + "\n")
        seen = set()
        for p in files_to_add:
            if p.name in seen:
                continue
            seen.add(p.name)
            zf.write(p, arcname=p.name)


if __name__ == "__main__":
    main()
