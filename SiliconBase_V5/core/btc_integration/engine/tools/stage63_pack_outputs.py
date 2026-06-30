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


def _mtime_ok(p: Path, started_at: int) -> bool:
    try:
        return p.exists() and int(p.stat().st_mtime) >= int(started_at)
    except Exception:
        return False


def _top_lines(txt: str, limit: int = 24) -> list[str]:
    return [line for line in txt.splitlines() if line.startswith("- ")][:limit]


def _build_deepseek(okx_txt: str, main_txt: str, branch_txt: str) -> str:
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
    lines.append("二、Stage63 主线价格影响 + 结构提频")
    lines.extend(_top_lines(main_txt, 18) or ["- stage63_mainline_price_impact_latest.txt 缺失"])
    lines.append("")
    lines.append("三、Stage63 ETH/SOL 广角结构")
    lines.extend(_top_lines(branch_txt, 26) or ["- stage63_branch_price_impact_latest.txt 缺失"])
    lines.append("")
    lines.append("四、请重点给建议")
    lines.append("- 主线应优先并哪种结构门：neutral_revert、impact_tiered、还是 impact_tiered_flow？")
    lines.append("- ETH / SOL 哪个更值得先追求月度爆发：trend、shock，还是 wick-reversion 独立子引擎？")
    lines.append("- 分支若要追求更高月化，执行层分批/锁盈应何时才值得纳入？")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage63 pack outputs")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--started-at", type=int, required=True)
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    downloads = Path.home() / "Downloads"
    reports_raw = root / "reports" / "research_raw"

    main_txt_p = reports_raw / "stage63_mainline_price_impact_latest.txt"
    main_json_p = reports_raw / "stage63_mainline_price_impact_latest.json"
    branch_txt_p = reports_raw / "stage63_branch_price_impact_latest.txt"
    branch_json_p = reports_raw / "stage63_branch_price_impact_latest.json"

    must_refresh = [main_txt_p, main_json_p, branch_txt_p, branch_json_p]
    stale = [p.name for p in must_refresh if not _mtime_ok(p, args.started_at)]
    if stale:
        raise SystemExit(f"stage63 报告没有被本轮刷新：{', '.join(stale)}")

    okx_p, okx_txt = _read_first([downloads / "okx_demo_report_latest.txt", root / "reports" / "okx_demo_report_latest.txt"])
    main_txt = main_txt_p.read_text(encoding="utf-8", errors="ignore")
    branch_txt = branch_txt_p.read_text(encoding="utf-8", errors="ignore")

    deepseek_out = downloads / "deepseek_single_file_latest.txt"
    deepseek_out.write_text(_build_deepseek(okx_txt, main_txt, branch_txt), encoding="utf-8")

    bundle_out = downloads / "chatgpt_bundle_latest.zip"
    files_to_add: list[Path] = []
    seen = set()
    candidates: list[Path | None] = [
        okx_p,
        main_txt_p,
        main_json_p,
        branch_txt_p,
        branch_json_p,
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
            f"stage63_mainline_mtime_utc={datetime.fromtimestamp(main_txt_p.stat().st_mtime, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"stage63_branch_mtime_utc={datetime.fromtimestamp(branch_txt_p.stat().st_mtime, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
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
    must_have = {"README_SEND_TO_CHATGPT.txt", "stage63_mainline_price_impact_latest.txt", "stage63_branch_price_impact_latest.txt"}
    missing = must_have - names
    if missing:
        with contextlib.suppress(Exception):
            bundle_out.unlink(missing_ok=True)
        raise SystemExit(f"bundle 自检失败，缺少: {sorted(missing)}")

    print(bundle_out)
    print(deepseek_out)


if __name__ == "__main__":
    main()
