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


def _section(lines: list[str], title: str, body: str, limit: int = 30) -> None:
    lines.append(title)
    if body.strip():
        for line in body.splitlines()[:limit]:
            if line.strip():
                lines.append(line)
    else:
        lines.append("- 缺失")
    lines.append("")


def _build_deepseek(okx_txt: str, main_txt: str, branch_txt: str, msg_txt: str) -> str:
    lines: list[str] = []
    lines.append("DeepSeek 单文件汇总")
    lines.append("==============")
    lines.append("")
    lines.append(f"生成时间: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append("")
    _section(lines, "一、自动盘状态", okx_txt, 18)
    _section(lines, "二、主线提频研究", main_txt, 28)
    _section(lines, "三、ETH + SOL 广角图谱", branch_txt, 36)
    _section(lines, "四、消息面风险层摘要", msg_txt, 12)
    lines.append("五、请重点给建议")
    lines.append("- 主线提频应优先守哪条底线：PF、分段 PF 还是 12M floor？")
    lines.append("- ETH 与 SOL 各自是否该继续保留双边，还是拆成独立 long / short engine？")
    lines.append("- 消息面 / Polymarket 继续只做 risk overlay，还是可选一部分升到 weak alpha？")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage54 pack outputs")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--started-at", type=int, required=True)
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    downloads = Path.home() / "Downloads"
    reports_raw = root / "reports" / "research_raw"

    main_txt = reports_raw / "stage54_mainline_angle_latest.txt"
    main_json = reports_raw / "stage54_mainline_angle_latest.json"
    branch_txt = reports_raw / "stage54_branch_broad_map_latest.txt"
    branch_json = reports_raw / "stage54_branch_broad_map_latest.json"
    must_refresh = [main_txt, main_json, branch_txt, branch_json]
    stale = [p.name for p in must_refresh if not _mtime_ok(p, args.started_at)]
    if stale:
        raise SystemExit(f"stage54 报告没有被本轮刷新：{', '.join(stale)}")

    okx_p, okx_txt = _read_first([downloads / "okx_demo_report_latest.txt", root / "reports" / "okx_demo_report_latest.txt"])
    _, msg_txt = _read_first([reports_raw / "message_stack_backtest_latest.txt"])

    deepseek_out = downloads / "deepseek_single_file_latest.txt"
    deepseek_out.write_text(
        _build_deepseek(
            okx_txt,
            main_txt.read_text(encoding="utf-8", errors="ignore"),
            branch_txt.read_text(encoding="utf-8", errors="ignore"),
            msg_txt,
        ),
        encoding="utf-8",
    )

    files_to_add: list[Path] = []
    seen = set()
    for p in [okx_p, main_txt, main_json, branch_txt, branch_json, reports_raw / "message_stack_backtest_latest.txt", reports_raw / "local_info_sources_latest.txt"]:
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
            f"mainline_txt_mtime_utc={datetime.fromtimestamp(main_txt.stat().st_mtime, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"branch_txt_mtime_utc={datetime.fromtimestamp(branch_txt.stat().st_mtime, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
            "",
            "包含文件：",
        ]
        for p in files_to_add:
            readme.append(f"- {p.name}")
        zf.writestr("README_SEND_TO_CHATGPT.txt", "\n".join(readme).rstrip() + "\n")
        for p in files_to_add:
            zf.write(p, arcname=p.name)

    with zipfile.ZipFile(bundle_out, "r") as zf:
        names = set(zf.namelist())
    must_have = {"README_SEND_TO_CHATGPT.txt", "stage54_mainline_angle_latest.txt", "stage54_branch_broad_map_latest.txt"}
    missing = must_have - names
    if missing:
        raise SystemExit(f"bundle 缺文件：{sorted(missing)}")

    print(bundle_out)
    print(deepseek_out)


if __name__ == "__main__":
    main()
