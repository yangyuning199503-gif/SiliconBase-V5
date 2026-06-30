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

def _fmt_mtime(p: Path | None) -> str:
    try:
        if p is None or not p.exists():
            return "NA"
        return datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    except Exception:
        return "NA"

def _top_lines(txt: str, limit: int = 24) -> list[str]:
    return [line for line in txt.splitlines() if line.startswith("- ")][:limit]

def _build_deepseek(okx_txt: str, stage48_txt: str, stage47_txt: str) -> str:
    lines: list[str] = []
    lines += ["DeepSeek 单文件汇总", "==============", "", f"生成时间: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}", "", "一、自动盘状态"]
    if okx_txt.strip():
        for line in okx_txt.splitlines()[:18]:
            if line.strip():
                lines.append(line)
    else:
        lines.append("- okx_demo_report_latest.txt 缺失")
    lines += ["", "二、Stage48 激进提频精修"]
    lines.extend(_top_lines(stage48_txt, 28) or ["- stage48_aggressive_refine_lab_latest.txt 缺失"])
    lines += ["", "三、上轮 Stage47 固定分仓+早锁盈结论"]
    lines.extend(_top_lines(stage47_txt, 12) or ["- stage47_tranche_lock_lab_latest.txt 缺失"])
    lines += ["", "四、请重点给建议", "- 主线提频更应该优先放松哪个：lookback、zone、cooldown 还是 compress？", "- SOL long core 是保留质量优先，还是接受更高频次去换月度爆发？", "- short shock 现在是否应完全冻结，等事件门控数据更成熟后再启用？"]
    return "\n".join(lines).rstrip() + "\n"

def main() -> None:
    ap = argparse.ArgumentParser(description="Stage48 pack outputs")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--started-at", type=int, default=0)
    args = ap.parse_args()
    root = Path(args.project_dir).expanduser().resolve()
    downloads = Path.home() / "Downloads"
    reports_raw = root / "reports" / "research_raw"
    okx_p, okx_txt = _read_first([downloads / "okx_demo_report_latest.txt", root / "reports" / "okx_demo_report_latest.txt"])
    s48_txt_p, s48_txt = _read_first([reports_raw / "stage48_aggressive_refine_lab_latest.txt"])
    s48_json_p = reports_raw / "stage48_aggressive_refine_lab_latest.json"
    s47_txt_p, s47_txt = _read_first([reports_raw / "stage47_tranche_lock_lab_latest.txt"])
    s47_json_p = reports_raw / "stage47_tranche_lock_lab_latest.json"
    if args.started_at:
        must_refresh = [p for p in [s48_txt_p, s48_json_p] if p is not None]
        stale = [p.name for p in must_refresh if not _mtime_ok(p, args.started_at)]
        if stale:
            raise SystemExit(f"stage48 报告没有被本轮刷新：{', '.join(stale)}")
    (downloads / "deepseek_single_file_latest.txt").write_text(_build_deepseek(okx_txt, s48_txt, s47_txt), encoding="utf-8")
    bundle_out = downloads / "chatgpt_bundle_latest.zip"
    files_to_add: list[Path] = []
    seen = set()
    for p in [okx_p, s48_txt_p, s48_json_p if s48_json_p.exists() else None, s47_txt_p, s47_json_p if s47_json_p.exists() else None]:
        if p is not None and p.exists() and p.is_file() and p.name not in seen:
            seen.add(p.name)
            files_to_add.append(p)
    for name in ["stage46_aggressive_lab_latest.txt", "stage46_aggressive_lab_latest.json", "polymarket_probe_latest.txt", "polymarket_probe_latest.json", "mainline_density_lab_latest.txt", "mainline_density_lab_latest.json", "message_stack_backtest_latest.txt", "alt_shortwave_message_overlay_latest.txt", "alt_shortwave_symbol_overlay_latest.json", "local_info_sources_latest.txt", "current_demo_strategy_trades_latest.csv", "stage45_targeted_lab_latest.txt", "stage45_targeted_lab_latest.json", "stage44_priority_lab_latest.txt", "stage44_priority_lab_latest.json", "stage43_efficiency_lab_latest.txt", "stage43_efficiency_lab_latest.json"]:
        p = reports_raw / name
        if not p.exists():
            p = root / "reports" / name
        if p.exists() and p.is_file() and p.name not in seen:
            seen.add(p.name)
            files_to_add.append(p)
    with zipfile.ZipFile(bundle_out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        readme = ["ChatGPT Bundle", "==============", "", f"generated_at_utc={datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}", f"project_dir={root}", f"stage48_mtime_utc={_fmt_mtime(s48_txt_p)}", f"stage47_mtime_utc={_fmt_mtime(s47_txt_p)}", "", "包含文件："]
        for p in files_to_add:
            readme.append(f"- {p.name}")
        zf.writestr("README_SEND_TO_CHATGPT.txt", "\n".join(readme).rstrip() + "\n")
        for p in files_to_add:
            zf.write(p, arcname=p.name)
    with zipfile.ZipFile(bundle_out, "r") as zf:
        names = set(zf.namelist())
    must_have = {"README_SEND_TO_CHATGPT.txt", "stage48_aggressive_refine_lab_latest.txt"}
    missing = must_have - names
    if missing:
        with contextlib.suppress(Exception):
            bundle_out.unlink(missing_ok=True)
        raise SystemExit(f"bundle 自检失败，缺少: {sorted(missing)}")
if __name__ == "__main__":
    main()
