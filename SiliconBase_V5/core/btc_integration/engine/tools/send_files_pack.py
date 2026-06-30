from __future__ import annotations

import argparse
import os
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path


def _preferred_root(root: Path) -> Path:
    home_root = Path.home() / "btc_system_v1"
    if root.resolve() != home_root.resolve() and home_root.exists():
        raise SystemExit(f"请在 ~/btc_system_v1 运行；当前目录是 {root}")
    return root


def _read_first(paths: list[Path]) -> tuple[Path | None, str]:
    for p in paths:
        try:
            if p.exists() and p.is_file():
                return p, p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
    return None, ""


def _cleanup_downloads(downloads: Path) -> None:
    remove_names = {
        "research_report_latest.txt",
        "deepseek_brief_latest.txt",
        "deepseek_strategy_report_latest.txt",
        "deepseek_strategy_data_latest.txt",
        "deepseek_strategy_data_latest.json",
        "mainline_density_lab_latest.txt",
        "mainline_density_lab_latest.json",
        "message_stack_backtest_latest.txt",
        "message_stack_backtest_latest.json",
        "current_demo_strategy_trades_latest.csv",
        "alt_shortwave_message_overlay_latest.txt",
        "alt_shortwave_symbol_overlay_latest.json",
        "chatgpt_single_file_20260315.txt",
        "deepseek_single_file_20260315.txt",
        "chatgpt_single_file_latest.txt",
        "support_bundle_latest.zip",
        "support_bundle_upload.zip",
        "stage77_mainline_dual_window_latest.txt",
        "stage77_mainline_dual_window_latest.json",
        "stage78_branch_dual_window_latest.txt",
        "stage78_branch_dual_window_latest.json",
        "stage81_mainline_walkforward_latest.txt",
        "stage81_mainline_walkforward_latest.json",
        "stage82_branch_walkforward_latest.txt",
        "stage82_branch_walkforward_latest.json",
        "stage88_mainline_fusion_walkforward_latest.txt",
        "stage88_mainline_fusion_walkforward_latest.json",
        "stage89_branch_fusion_walkforward_latest.txt",
        "stage89_branch_fusion_walkforward_latest.json",
        "stage90_mainline_event_alpha_matrix_latest.txt",
        "stage90_mainline_event_alpha_matrix_latest.json",
        "stage91_branch_event_alpha_matrix_latest.txt",
        "stage91_branch_event_alpha_matrix_latest.json",
        "stage92_eth_sol_open_frontier_latest.txt",
        "stage92_eth_sol_open_frontier_latest.json",
        "stage93_frequency_accel_latest.txt",
        "stage93_frequency_accel_latest.json",
        "stage94_priority_pipeline_latest.txt",
        "stage94_priority_pipeline_latest.json",
        "stage95_priority_sync_latest.txt",
        "stage95_priority_sync_latest.json",
        "stage96_event_bridge_latest.txt",
        "stage96_event_bridge_latest.json",
        "stage97_multi_standard_frontier_latest.txt",
        "stage97_multi_standard_frontier_latest.json",
        "local_info_sources_latest.txt",
        "polymarket_probe_latest.txt",
        "polymarket_probe_latest.json",
    }
    for name in remove_names:
        p = downloads / name
        try:
            if p.exists() and p.is_file():
                p.unlink()
        except Exception:
            pass


def _extract_line(text: str, label: str) -> str:
    m = re.search(rf"- {re.escape(label)}: (.+)", text)
    return m.group(1).strip() if m else ""


def _read_okx_brief(okx_txt: str) -> dict[str, str]:
    return {
        "heartbeat": _extract_line(okx_txt, "报告心跳(UTC+8)"),
        "state": _extract_line(okx_txt, "当前状态"),
        "reason": _extract_line(okx_txt, "状态原因"),
        "version": _extract_line(okx_txt, "当前版本"),
        "next_run": _extract_line(okx_txt, "下一轮执行(UTC+8)"),
        "risk_mode": _extract_line(okx_txt, "当前模式"),
        "trigger": _extract_line(okx_txt, "触发原因"),
    }


def _pid_alive_from_file(path: Path) -> tuple[bool, str]:
    if not path.exists() or not path.is_file():
        return False, ""
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore").strip()
        pid = int(raw)
    except Exception:
        return False, ""
    try:
        os.kill(pid, 0)
        return True, str(pid)
    except Exception:
        return False, str(pid)


def _okx_report_is_boot_placeholder(txt: str) -> bool:
    s = txt or ""
    return ("当前状态: 启动中" in s) or ("状态原因: waiting_for_autopilot_process" in s)


def _tail_text(path: Path, max_lines: int = 120) -> str:
    if not path.exists() or not path.is_file():
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return ""
    tail = lines[-max_lines:]
    return "\n".join(tail).rstrip() + ("\n" if tail else "")


def _build_okx_runtime_diag(root: Path, okx_p: Path | None, okx_txt: str) -> str:
    runtime_dir = root / ".runtime"
    pid_p = runtime_dir / "okx_demo_autopilot.pid"
    log_p = runtime_dir / "okx_demo_autopilot.log"
    pid_alive, pid_text = _pid_alive_from_file(pid_p)
    placeholder = _okx_report_is_boot_placeholder(okx_txt)
    log_tail = _tail_text(log_p, max_lines=160)

    lines: list[str] = []
    lines.append("OKX Runtime Diag")
    lines.append("================")
    lines.append("")
    lines.append(f"report_path={okx_p if okx_p else ''}")
    lines.append(f"report_exists={'yes' if okx_p and okx_p.exists() else 'no'}")
    lines.append(f"report_boot_placeholder={'yes' if placeholder else 'no'}")
    lines.append(f"pid_file={pid_p}")
    lines.append(f"pid_present={'yes' if pid_p.exists() else 'no'}")
    lines.append(f"pid_value={pid_text or '-'}")
    lines.append(f"pid_alive={'yes' if pid_alive else 'no'}")
    lines.append(f"log_file={log_p}")
    lines.append(f"log_exists={'yes' if log_p.exists() else 'no'}")
    if log_tail:
        lines.append("")
        lines.append("【log tail】")
        lines.append(log_tail.rstrip())
    return "\n".join(lines).rstrip() + "\n"


def _top_bullets(txt: str, limit: int = 10) -> list[str]:
    out: list[str] = []
    for line in txt.splitlines():
        s = line.strip()
        if s.startswith("- "):
            out.append(s)
            if len(out) >= limit:
                break
    return out


def _find_section_bullets(txt: str, section_header: str, limit: int = 10) -> list[str]:
    out: list[str] = []
    in_sec = False
    for raw in txt.splitlines():
        s = raw.rstrip()
        if s.strip() == section_header:
            in_sec = True
            continue
        if in_sec and (s.startswith("=== ") or s.startswith("【")):
            break
        if in_sec and s.strip().startswith("- "):
            out.append(s.strip())
            if len(out) >= limit:
                break
    return out


def _write_deepseek_text(
    path: Path,
    okx_txt: str,
    msg_txt: str,
    main_txt: str,
    branch_txt: str,
    local_txt: str,
    now_utc: str,
) -> None:
    okx = _read_okx_brief(okx_txt)
    lines: list[str] = []
    lines.append("DeepSeek 单文件汇总")
    lines.append("==============")
    lines.append("")
    lines.append(f"生成时间: {now_utc}")
    lines.append("")
    lines.append("一、当前系统状态")
    if okx_txt.strip():
        lines.append(f"- 自动盘状态: {okx.get('state','')} | reason={okx.get('reason','')} | 版本={okx.get('version','')}")
        lines.append(f"- 心跳: {okx.get('heartbeat','')} | 下一轮: {okx.get('next_run','')}")
        lines.append(f"- 风险层: mode={okx.get('risk_mode','')} | trigger={okx.get('trigger','')}")
    else:
        lines.append("- 未读到 okx_demo_report_latest.txt")

    lines.append("")
    lines.append("二、消息面联动")
    bullets = _find_section_bullets(msg_txt, "【全样本固定规则】", 6)
    lines.extend(bullets or ["- 未读到 message_stack_backtest_latest.txt"])

    lines.append("")
    lines.append("三、主线回测")
    if main_txt.strip():
        main_lines = _find_section_bullets(main_txt, "=== 候选结果 ===", 6) or _top_bullets(main_txt, 6)
        lines.extend(main_lines)
    else:
        lines.append("- 未读到主线回测报告")

    lines.append("")
    lines.append("四、分支回测")
    if branch_txt.strip():
        branch_lines = _find_section_bullets(branch_txt, "=== 各赛道当前最优 ===", 8) or _top_bullets(branch_txt, 8)
        lines.extend(branch_lines)
    else:
        lines.append("- 未读到分支回测报告")

    lines.append("")
    lines.append("五、信息源状态")
    local_lines = _find_section_bullets(local_txt, "【摘要】", 10) or _top_bullets(local_txt, 10)
    lines.extend(local_lines or ["- 未读到 local_info_sources_latest.txt"])
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="生成给 DeepSeek 的 txt 与给 ChatGPT 的 zip。")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--cleanup-downloads", action="store_true")
    args = ap.parse_args()

    root = _preferred_root(Path(args.project_dir).expanduser().resolve())
    downloads = Path.home() / "Downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    reports = root / "reports"
    raw = reports / "research_raw"
    raw.mkdir(parents=True, exist_ok=True)

    if args.cleanup_downloads:
        _cleanup_downloads(downloads)

    okx_p, okx_txt = _read_first([
        downloads / "okx_demo_report_latest.txt",
        reports / "okx_demo_report_latest.txt",
        root / "okx_demo_report_latest.txt",
    ])
    branch_demo_p, branch_demo_txt = _read_first([
        downloads / "branch_demo_report_latest.txt",
        reports / "branch_demo_report_latest.txt",
        root / "branch_demo_report_latest.txt",
    ])
    shadow_demo_p, shadow_demo_txt = _read_first([
        raw / "mainline_shadow_demo_report_latest.txt",
        reports / "mainline_shadow_demo_report_latest.txt",
        root / "mainline_shadow_demo_report_latest.txt",
    ])
    msg_p, msg_txt = _read_first([
        raw / "message_stack_backtest_latest.txt",
        downloads / "message_stack_backtest_latest.txt",
        reports / "message_stack_backtest_latest.txt",
    ])
    local_p, local_txt = _read_first([
        raw / "local_info_sources_latest.txt",
        downloads / "local_info_sources_latest.txt",
    ])

    main_txt_p, main_txt = _read_first([
        raw / "stage90_mainline_event_alpha_matrix_latest.txt",
        raw / "stage88_mainline_fusion_walkforward_latest.txt",
        raw / "stage81_mainline_walkforward_latest.txt",
        raw / "stage77_mainline_dual_window_latest.txt",
        raw / "mainline_density_lab_latest.txt",
        downloads / "stage81_mainline_walkforward_latest.txt",
        downloads / "stage77_mainline_dual_window_latest.txt",
        downloads / "mainline_density_lab_latest.txt",
    ])
    main_json_p, _ = _read_first([
        raw / "stage90_mainline_event_alpha_matrix_latest.json",
        raw / "stage88_mainline_fusion_walkforward_latest.json",
        raw / "stage81_mainline_walkforward_latest.json",
        raw / "stage77_mainline_dual_window_latest.json",
        raw / "mainline_density_lab_latest.json",
        downloads / "stage81_mainline_walkforward_latest.json",
        downloads / "stage77_mainline_dual_window_latest.json",
        downloads / "mainline_density_lab_latest.json",
    ])
    branch_txt_p, branch_txt = _read_first([
        raw / "stage91_branch_event_alpha_matrix_latest.txt",
        raw / "stage89_branch_fusion_walkforward_latest.txt",
        raw / "stage82_branch_walkforward_latest.txt",
        raw / "stage78_branch_dual_window_latest.txt",
        raw / "alt_shortwave_message_overlay_latest.txt",
        downloads / "stage82_branch_walkforward_latest.txt",
        downloads / "stage78_branch_dual_window_latest.txt",
        downloads / "alt_shortwave_message_overlay_latest.txt",
    ])
    branch_json_p, _ = _read_first([
        raw / "stage91_branch_event_alpha_matrix_latest.json",
        raw / "stage89_branch_fusion_walkforward_latest.json",
        raw / "stage82_branch_walkforward_latest.json",
        raw / "stage78_branch_dual_window_latest.json",
        raw / "alt_shortwave_symbol_overlay_latest.json",
        downloads / "stage82_branch_walkforward_latest.json",
        downloads / "stage78_branch_dual_window_latest.json",
        downloads / "alt_shortwave_symbol_overlay_latest.json",
    ])
    poly_txt_p, _ = _read_first([
        raw / "polymarket_probe_latest.txt",
        downloads / "polymarket_probe_latest.txt",
    ])
    poly_json_p, _ = _read_first([
        raw / "polymarket_probe_latest.json",
        downloads / "polymarket_probe_latest.json",
    ])
    trades_csv_p, _ = _read_first([
        raw / "current_demo_strategy_trades_latest.csv",
        reports / "current_demo_strategy_trades_latest.csv",
        downloads / "current_demo_strategy_trades_latest.csv",
    ])

    okx_runtime_diag_txt = _build_okx_runtime_diag(root, okx_p, okx_txt)
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    deepseek_path = downloads / "deepseek_single_file_latest.txt"
    _write_deepseek_text(deepseek_path, okx_txt, msg_txt, main_txt, branch_txt, local_txt, now_utc)

    files_to_add: list[Path] = []
    seen: set[str] = set()
    candidates = [
        okx_p,
        branch_demo_p,
        shadow_demo_p,
        msg_p,
        local_p,
        poly_txt_p,
        poly_json_p,
        main_txt_p,
        main_json_p,
        branch_txt_p,
        branch_json_p,
        trades_csv_p,
        raw / "stage81_mainline_walkforward_latest.txt",
        raw / "stage81_mainline_walkforward_latest.json",
        raw / "stage82_branch_walkforward_latest.txt",
        raw / "stage82_branch_walkforward_latest.json",
        raw / "stage88_mainline_fusion_walkforward_latest.txt",
        raw / "stage88_mainline_fusion_walkforward_latest.json",
        raw / "stage89_branch_fusion_walkforward_latest.txt",
        raw / "stage89_branch_fusion_walkforward_latest.json",
        raw / "stage90_mainline_event_alpha_matrix_latest.txt",
        raw / "stage90_mainline_event_alpha_matrix_latest.json",
        raw / "stage91_branch_event_alpha_matrix_latest.txt",
        raw / "stage91_branch_event_alpha_matrix_latest.json",
        raw / "stage92_eth_sol_open_frontier_latest.txt",
        raw / "stage92_eth_sol_open_frontier_latest.json",
        raw / "stage93_frequency_accel_latest.txt",
        raw / "stage93_frequency_accel_latest.json",
        raw / "stage94_priority_pipeline_latest.txt",
        raw / "stage94_priority_pipeline_latest.json",
        raw / "stage95_priority_sync_latest.txt",
        raw / "stage95_priority_sync_latest.json",
        raw / "stage96_event_bridge_latest.txt",
        raw / "stage96_event_bridge_latest.json",
        raw / "stage97_multi_standard_frontier_latest.txt",
        raw / "stage97_multi_standard_frontier_latest.json",
        root / "TRADER_EVENT_PLAYBOOK_20260323.txt",
        raw / "stage105_main_focus_latest.txt",
        raw / "stage105_main_focus_latest.json",
    ]
    for p in candidates:
        if p is not None and p.exists() and p.is_file() and p.name not in seen:
            seen.add(p.name)
            files_to_add.append(p)

    bundle_out = downloads / "chatgpt_bundle_latest.zip"
    with zipfile.ZipFile(bundle_out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        okx = _read_okx_brief(okx_txt)
        readme_lines: list[str] = []
        readme_lines.append("ChatGPT Bundle")
        readme_lines.append("==============")
        readme_lines.append("")
        readme_lines.append(f"generated_at_utc={now_utc}")
        readme_lines.append(f"project_dir={root}")
        if okx:
            readme_lines.append(f"runtime_state={okx.get('state','')} | next_run={okx.get('next_run','')} | risk_mode={okx.get('risk_mode','')} | trigger={okx.get('trigger','')}")
        if branch_demo_txt.strip():
            readme_lines.append("branch_demo_report=present")
        if shadow_demo_txt.strip():
            readme_lines.append("mainline_shadow_demo_report=present")
        readme_lines.append("")
        readme_lines.append("包含文件：")
        for p in files_to_add:
            readme_lines.append(f"- {p.name}")
        zf.writestr("README_SEND_TO_CHATGPT.txt", "\n".join(readme_lines).rstrip() + "\n")
        zf.writestr("okx_runtime_diag_latest.txt", okx_runtime_diag_txt)
        for p in files_to_add:
            zf.write(p, arcname=p.name)

    print(bundle_out)
    print(deepseek_path)


if __name__ == "__main__":
    main()
