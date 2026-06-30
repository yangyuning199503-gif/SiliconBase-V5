from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def _run(cmd: list[str], cwd: Path) -> tuple[int, str, str]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        text=True,
        capture_output=True,
        env=os.environ.copy(),
    )
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def _read_text(path: Path) -> str:
    try:
        if path.exists() and path.is_file():
            return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        pass
    return ""


def _grab_scalar(txt: str, label: str) -> str:
    m = re.search(rf"^{re.escape(label)}:\s*(.+)$", txt, flags=re.M)
    return m.group(1).strip() if m else ""


def _grab_section_lines(txt: str, header: str, *, limit: int = 6) -> list[str]:
    out: list[str] = []
    in_sec = False
    for raw in txt.splitlines():
        line = raw.rstrip()
        if line.strip() == header:
            in_sec = True
            continue
        if in_sec and line.startswith("["):
            break
        if in_sec and line.strip().startswith("-"):
            out.append(line.strip())
            if len(out) >= limit:
                break
    return out


def _truthy_text(v: str) -> bool:
    return str(v).strip().lower() in {"1", "true", "yes", "y", "on"}


def build_summary(
    *,
    root: Path,
    diag_txt: str,
    free_txt: str,
    hist_txt: str,
    diag_rc: int,
    free_rc: int,
    hist_rc: int,
) -> str:
    okx_ok = _truthy_text(_grab_scalar(diag_txt, "okx_account_config_ok"))
    cg_news_ok = _truthy_text(_grab_scalar(diag_txt, "coinglass_news_ok"))
    cg_econ_ok = _truthy_text(_grab_scalar(diag_txt, "coinglass_economic_ok"))
    env_loaded = _grab_scalar(diag_txt, "env_files_loaded")
    diag_reason = _grab_scalar(diag_txt, "coinglass_reason") or _grab_scalar(diag_txt, "okx_reason")

    free_status = _grab_scalar(free_txt, "status") or "unknown"
    free_preview = _grab_section_lines(free_txt, "[summary]", limit=5)

    hist_ready = "已具备做“历史特征增强回测”的基础条件" in hist_txt
    hist_partial = "Recent 新闻/宏观已确认可用" in hist_txt
    hist_missing_key = "未找到 COINGLASS_API_KEY" in hist_txt
    hist_conclusion = "ready" if hist_ready else ("partial" if hist_partial else ("missing_key" if hist_missing_key else "not_ready"))

    mainline_backtest_ready = cg_news_ok and cg_econ_ok
    enhanced_backtest_ready = hist_ready

    lines: list[str] = []
    lines.append("本地信息源联调报告")
    lines.append("================")
    lines.append(f"生成时间(UTC): {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append(f"project_dir: {root}")
    lines.append("")
    lines.append("【摘要】")
    lines.append(f"- OKX Demo 鉴权: {'ok' if okx_ok else 'failed'}")
    lines.append(f"- CoinGlass recent 新闻: {'ok' if cg_news_ok else 'failed'}")
    lines.append(f"- CoinGlass 宏观日历: {'ok' if cg_econ_ok else 'failed'}")
    lines.append(f"- CoinGlass 历史增强回测条件: {hist_conclusion}")
    lines.append(f"- 免费结构化源状态: {free_status}")
    if env_loaded:
        lines.append(f"- 本地 env 已加载: {env_loaded}")
    if diag_reason:
        lines.append(f"- 当前诊断原因: {diag_reason}")
    lines.append(f"- 主线消息面联动回测: {'可以本地跑' if mainline_backtest_ready else '先修 CoinGlass recent 端点'}")
    lines.append(f"- 历史增强消息面回测: {'可以本地跑' if enhanced_backtest_ready else '先补 CoinGlass 历史覆盖'}")
    lines.append("- 下一步命令 1: COINGLASS_HISTORY_REFRESH=1 bash run_message_stack_backtest.sh")
    lines.append("- 下一步命令 2: bash run_send_files.sh")
    lines.append("")
    lines.append("【探针执行状态】")
    lines.append(f"- okx_coinglass_diag.py rc={diag_rc}")
    lines.append(f"- free_feeds_probe.py rc={free_rc}")
    lines.append(f"- coinglass_history_export.py rc={hist_rc}")
    lines.append("")
    lines.append("【免费结构化源快照摘要】")
    if free_preview:
        lines.extend(free_preview)
    else:
        lines.append("- none")
    lines.append("")
    lines.append("【OKX+CoinGlass 基础诊断】")
    lines.append(diag_txt.strip() if diag_txt.strip() else "(empty)")
    lines.append("")
    lines.append("【CoinGlass 历史覆盖审计】")
    lines.append(hist_txt.strip() if hist_txt.strip() else "(empty)")
    lines.append("")
    lines.append("【免费结构化源原始报告】")
    lines.append(free_txt.strip() if free_txt.strip() else "(empty)")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Run local keyed info-source probes and generate one summary report.")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--out", default="reports/research_raw/local_info_sources_latest.txt")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    out = Path(args.out).expanduser()
    if not out.is_absolute():
        out = root / out
    out.parent.mkdir(parents=True, exist_ok=True)

    raw_dir = root / "reports" / "research_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    py = sys.executable

    diag_json = raw_dir / "okx_coinglass_diag_latest.json"
    diag_txt_path = raw_dir / "okx_coinglass_diag_latest.txt"
    free_txt_path = raw_dir / "free_sources_latest.txt"
    hist_txt_path = raw_dir / "coinglass_history_export_latest.txt"

    diag_rc, diag_stdout, diag_stderr = _run(
        [py, "-m", "tools.okx_coinglass_diag", "--project-dir", str(root), "--out-json", str(diag_json), "--out-txt", str(diag_txt_path)],
        cwd=root,
    )
    free_rc, free_stdout, free_stderr = _run(
        [py, "-m", "tools.free_feeds_probe", "--project-dir", str(root), "--out", str(free_txt_path)],
        cwd=root,
    )
    hist_rc, hist_stdout, hist_stderr = _run(
        [py, "-m", "tools.coinglass_history_export", "--project-dir", str(root), "--out", str(hist_txt_path)],
        cwd=root,
    )

    diag_txt = _read_text(diag_txt_path)
    free_txt = _read_text(free_txt_path)
    hist_txt = _read_text(hist_txt_path)

    summary = build_summary(
        root=root,
        diag_txt=diag_txt,
        free_txt=free_txt,
        hist_txt=hist_txt,
        diag_rc=diag_rc,
        free_rc=free_rc,
        hist_rc=hist_rc,
    )

    if diag_stdout.strip() or diag_stderr.strip() or free_stdout.strip() or free_stderr.strip() or hist_stdout.strip() or hist_stderr.strip():
        summary += "\n【子进程 stdout/stderr】\n"
        for name, rc, so, se in [
            ("okx_coinglass_diag", diag_rc, diag_stdout, diag_stderr),
            ("free_feeds_probe", free_rc, free_stdout, free_stderr),
            ("coinglass_history_export", hist_rc, hist_stdout, hist_stderr),
        ]:
            summary += f"- {name} rc={rc}\n"
            if so.strip():
                summary += "  stdout:\n"
                for line in so.strip().splitlines()[:20]:
                    summary += f"    {line}\n"
            if se.strip():
                summary += "  stderr:\n"
                for line in se.strip().splitlines()[:20]:
                    summary += f"    {line}\n"

    out.write_text(summary, encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
