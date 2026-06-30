from __future__ import annotations

import argparse
import contextlib
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


def _mtime_ok(p: Path, started_at: int) -> bool:
    try:
        return p.exists() and int(p.stat().st_mtime) >= int(started_at)
    except Exception:
        return False


def _build_deepseek(okx_txt: str, s51_txt: str, s49_txt: str) -> str:
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
    lines.append("二、Stage51 激进前沿")
    lines.extend(_top_lines(s51_txt, 30) or ["- stage51_aggressive_frontier_latest.txt 缺失"])
    lines.append("")
    lines.append("三、上一轮对照")
    lines.extend(_top_lines(s49_txt, 14) or ["- stage49_aggressive_sprint_latest.txt 缺失"])
    lines.append("")
    lines.append("四、请重点给建议")
    lines.append("- 主线若 220+ 笔版本 PF 略降，应优先保留 trades 还是保留 rolling12_pf_floor？")
    lines.append("- SOL 若去掉 compress 才能显著提高 months>=20，是否值得保留为单独激进子分支？")
    lines.append("- 执行层分批进场/锁盈，应该现在并入 SOL，还是继续只留作后置风控？")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage51 pack outputs")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--started-at", type=int, required=True)
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    downloads = Path.home() / "Downloads"
    reports_raw = root / "reports" / "research_raw"

    s51_txt_p = reports_raw / "stage51_aggressive_frontier_latest.txt"
    s51_json_p = reports_raw / "stage51_aggressive_frontier_latest.json"
    if not _mtime_ok(s51_txt_p, args.started_at) or not _mtime_ok(s51_json_p, args.started_at):
        raise SystemExit("stage51 报告没有被本轮刷新；已阻止继续打包，避免把旧 bundle 当成新结果。")

    okx_p, okx_txt = _read_first([downloads / "okx_demo_report_latest.txt", root / "reports" / "okx_demo_report_latest.txt"])
    s51_txt = s51_txt_p.read_text(encoding="utf-8", errors="ignore")
    _, s49_txt = _read_first([reports_raw / "stage49_aggressive_sprint_latest.txt"])

    deepseek_out = downloads / "deepseek_single_file_latest.txt"
    deepseek_out.write_text(_build_deepseek(okx_txt, s51_txt, s49_txt), encoding="utf-8")

    bundle_out = downloads / "chatgpt_bundle_latest.zip"
    files_to_add: list[Path] = []
    seen = set()
    candidates: list[Path | None] = [
        okx_p,
        s51_txt_p,
        s51_json_p,
        reports_raw / "stage49_aggressive_sprint_latest.txt",
        reports_raw / "stage49_aggressive_sprint_latest.json",
        reports_raw / "stage48_aggressive_refine_lab_latest.txt",
        reports_raw / "stage48_aggressive_refine_lab_latest.json",
        reports_raw / "stage47_tranche_lock_lab_latest.txt",
        reports_raw / "stage47_tranche_lock_lab_latest.json",
        reports_raw / "polymarket_probe_latest.txt",
        reports_raw / "polymarket_probe_latest.json",
        reports_raw / "message_stack_backtest_latest.txt",
        reports_raw / "local_info_sources_latest.txt",
        reports_raw / "current_demo_strategy_trades_latest.csv",
    ]
    for p in candidates:
        if p is not None and p.exists() and p.is_file() and p.name not in seen:
            seen.add(p.name)
            files_to_add.append(p)

    with zipfile.ZipFile(bundle_out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        readme = [
            "ChatGPT Bundle",
            "==============",
            "",
            f"generated_at_utc={datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"project_dir={root}",
            f"stage51_txt_mtime_utc={datetime.fromtimestamp(s51_txt_p.stat().st_mtime, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
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
    must_have = {"README_SEND_TO_CHATGPT.txt", "stage51_aggressive_frontier_latest.txt", "stage51_aggressive_frontier_latest.json"}
    missing = must_have - names
    if missing:
        with contextlib.suppress(Exception):
            bundle_out.unlink(missing_ok=True)
        raise SystemExit(f"bundle 自检失败，缺少: {sorted(missing)}")

    print(bundle_out)
    print(deepseek_out)


if __name__ == "__main__":
    main()
