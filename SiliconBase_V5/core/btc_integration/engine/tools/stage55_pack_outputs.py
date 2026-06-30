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


def _mtime_ok(p: Path, started_at: int) -> bool:
    try:
        return p.exists() and int(p.stat().st_mtime) >= int(started_at)
    except Exception:
        return False


def _top_lines(txt: str, limit: int = 28) -> list[str]:
    return [line for line in txt.splitlines() if line.startswith("- ")][:limit]


def _build_deepseek(okx_txt: str, main_txt: str, branch_txt: str, prev_txt: str) -> str:
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
    lines.append("二、Stage55 主线双线提频")
    lines.extend(_top_lines(main_txt, 18) or ["- stage55_mainline_dualtrack_latest.txt 缺失"])
    lines.append("")
    lines.append("三、Stage55 ETH + SOL 双引擎广角")
    lines.extend(_top_lines(branch_txt, 32) or ["- stage55_branch_dual_engines_latest.txt 缺失"])
    lines.append("")
    lines.append("四、上一轮参考")
    lines.extend(_top_lines(prev_txt, 12) or ["- stage54_branch_broad_map_latest.txt 缺失"])
    lines.append("")
    lines.append("五、请重点给建议")
    lines.append("- 主线提频若要继续上到 220~260，应该继续放松 BNB 长腿，还是继续单独收紧 BTC 短腿？")
    lines.append("- SOL 是否应长期保留双引擎（long core + short shock），还是先分别推进再并线？")
    lines.append("- ETH 若 long/short 分拆后仍一般，应该先加事件门控，还是先换时段/波动结构？")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage55 pack outputs")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--started-at", type=int, required=True)
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    downloads = Path.home() / "Downloads"
    reports_raw = root / "reports" / "research_raw"

    main_txt = reports_raw / "stage55_mainline_dualtrack_latest.txt"
    main_json = reports_raw / "stage55_mainline_dualtrack_latest.json"
    branch_txt = reports_raw / "stage55_branch_dual_engines_latest.txt"
    branch_json = reports_raw / "stage55_branch_dual_engines_latest.json"
    must_refresh = [main_txt, main_json, branch_txt, branch_json]
    stale = [p.name for p in must_refresh if not _mtime_ok(p, args.started_at)]
    if stale:
        raise SystemExit(f"stage55 报告没有被本轮刷新：{', '.join(stale)}")

    okx_p, okx_txt = _read_first([downloads / "okx_demo_report_latest.txt", root / "reports" / "okx_demo_report_latest.txt"])
    _, prev_txt = _read_first([reports_raw / "stage54_branch_broad_map_latest.txt"])

    deepseek_out = downloads / "deepseek_single_file_latest.txt"
    deepseek_out.write_text(
        _build_deepseek(
            okx_txt,
            main_txt.read_text(encoding="utf-8", errors="ignore"),
            branch_txt.read_text(encoding="utf-8", errors="ignore"),
            prev_txt,
        ),
        encoding="utf-8",
    )

    files_to_add: list[Path] = []
    seen = set()
    for p in [
        okx_p,
        main_txt,
        main_json,
        branch_txt,
        branch_json,
        reports_raw / "stage54_mainline_angle_latest.txt",
        reports_raw / "stage54_mainline_angle_latest.json",
        reports_raw / "stage54_branch_broad_map_latest.txt",
        reports_raw / "stage54_branch_broad_map_latest.json",
        reports_raw / "message_stack_backtest_latest.txt",
        reports_raw / "local_info_sources_latest.txt",
    ]:
        if p is not None and p.exists() and p.is_file() and p.name not in seen:
            files_to_add.append(p)
            seen.add(p.name)

    bundle_out = downloads / "chatgpt_bundle_latest.zip"
    with zipfile.ZipFile(bundle_out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        readme = [
            "ChatGPT Bundle",
            "==============",
            "",
            f"generated_at_utc={datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"project_dir={root}",
            f"stage55_mainline_txt_mtime_utc={datetime.fromtimestamp(main_txt.stat().st_mtime, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"stage55_branch_txt_mtime_utc={datetime.fromtimestamp(branch_txt.stat().st_mtime, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
            "",
            "files:",
        ]
        for p in files_to_add:
            readme.append(f"- {p.name}")
            zf.write(p, arcname=p.name)
        zf.writestr("README_SEND_TO_CHATGPT.txt", "\n".join(readme).rstrip() + "\n")


if __name__ == "__main__":
    main()
