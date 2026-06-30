from __future__ import annotations

import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def first_existing(paths: list[Path]) -> Path | None:
    for p in paths:
        if p and p.exists():
            return p
    return None


def rx1(text: str, pattern: str, default: str = "-") -> str:
    m = re.search(pattern, text, re.MULTILINE)
    return m.group(1).strip() if m else default


def find_line_contains(text: str, needle: str, default: str = "-") -> str:
    for line in text.splitlines():
        if needle in line:
            return line.rstrip()
    return default


def replace_first_line_value(text: str, key: str, new_value: str) -> str:
    pat = re.compile(rf"^(\s*{re.escape(key)}\s*:\s*).*$", re.MULTILINE)
    if pat.search(text):
        return pat.sub(lambda m: f"{m.group(1)}{new_value}", text, count=1)
    return text


def replace_data_end(text: str, date_str: str) -> str:
    return replace_first_line_value(text, "end", f"'{date_str}'")


def ensure_prefix_okxb(shadow_text: str) -> str:
    return re.sub(r"^(\s*clord_prefix\s*:\s*).*$", r"\1okxb", shadow_text, flags=re.MULTILINE)


def latest_date_from_signal(signal_text: str) -> str:
    m = re.match(r"(\d{4}-\d{2}-\d{2})", signal_text)
    return m.group(1) if m else datetime.now(timezone.utc).strftime("%Y-%m-%d")


def cleanup_download_exports(downloads: Path, keep_file: str) -> None:
    archive = Path.home() / "btc_system_v1" / "reports" / "download_noise_archive"
    archive.mkdir(parents=True, exist_ok=True)
    keep = {
        "okx_demo_report_latest.txt",
        "branch_demo_report_latest.txt",
        keep_file,
    }
    for p in downloads.iterdir():
        if not p.is_file():
            continue
        if p.name in keep:
            continue
        if p.name.startswith("stage") or p.name.startswith("chatgpt_bundle"):
            target = archive / p.name
            try:
                if target.exists():
                    target.unlink()
                shutil.move(str(p), str(target))
            except Exception:
                pass


def build_report(root: Path) -> tuple[Path, Path]:
    home = Path.home()
    downloads = home / "Downloads"
    reports_dir = root / "reports" / "research_raw"
    reports_dir.mkdir(parents=True, exist_ok=True)

    okx_report = first_existing([
        downloads / "okx_demo_report_latest.txt",
        root / "reports" / "okx_demo_report_latest.txt",
    ])
    branch_report = first_existing([
        downloads / "branch_demo_report_latest.txt",
        root / "reports" / "branch_demo_report_latest.txt",
    ])
    stage99 = first_existing([
        reports_dir / "stage99_mainline_frequency_push_latest.txt",
        downloads / "stage99_mainline_frequency_push_latest.txt",
    ])
    stage91 = first_existing([
        reports_dir / "stage91_branch_event_alpha_matrix_latest.txt",
        downloads / "stage91_branch_event_alpha_matrix_latest.txt",
    ])
    stage112 = first_existing([
        reports_dir / "stage112_joint_upgrade_gate_latest.txt",
        downloads / "stage112_joint_upgrade_gate_latest.txt",
    ])
    cfg_main = first_existing([root / "config_mainline_shadow_candidate.yml"])
    shadow_main = first_existing([root / "shadow_mainline_shadow_candidate.yml"])
    cfg_preview = first_existing([
        root / "config_shortwave_triple_book_preview.yml",
        root / "config_shortwave_asset_integrated.yml",
    ])
    shadow_preview = first_existing([
        root / "shadow_shortwave_triple_book_preview.yml",
        root / "shadow_shortwave_asset_integrated.yml",
    ])

    missing = [
        name for name, p in [
            ("okx_demo_report_latest.txt", okx_report),
            ("branch_demo_report_latest.txt", branch_report),
            ("stage99_mainline_frequency_push_latest.txt", stage99),
            ("stage91_branch_event_alpha_matrix_latest.txt", stage91),
            ("config_mainline_shadow_candidate.yml", cfg_main),
            ("shadow_mainline_shadow_candidate.yml", shadow_main),
            ("config_shortwave_triple_book_preview.yml", cfg_preview),
            ("shadow_shortwave_triple_book_preview.yml", shadow_preview),
        ] if p is None
    ]
    if missing:
        raise SystemExit("缺少必要文件: " + ", ".join(missing))

    okx_text = read_text(okx_report)
    branch_text = read_text(branch_report)
    stage99_text = read_text(stage99)
    stage91_text = read_text(stage91)
    stage112_text = read_text(stage112) if stage112 else ""
    cfg_main_text = read_text(cfg_main)
    shadow_main_text = read_text(shadow_main)
    cfg_preview_text = read_text(cfg_preview)
    shadow_preview_text = read_text(shadow_preview)

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    main_signal = rx1(okx_text, r"- 最近策略信号时间\(UTC\+8\):\s*(.+)")
    branch_signal = rx1(branch_text, r"- 最近策略信号时间\(UTC\+8\):\s*(.+)")
    latest_date = latest_date_from_signal(main_signal if main_signal != "-" else branch_signal)

    # Mainline
    main_runtime = rx1(okx_text, r"- 当前版本:\s*(.+)")
    main_status = rx1(okx_text, r"- 当前状态:\s*(.+)")
    main_live_keep = find_line_contains(stage99_text, "- live_keep:")
    main_shadow_bal = find_line_contains(stage99_text, "- shadow_balanced:")
    main_shadow_aggr = find_line_contains(stage99_text, "- shadow_aggressive:")
    main_recent = find_line_contains(okx_text, "- 近2年样本:")
    main_wf = find_line_contains(okx_text, "- WF样本外:")
    main_6y = find_line_contains(okx_text, "- 6年总样本:")
    main_gate = find_line_contains(okx_text, "- 评估结论:")

    # Branch
    branch_runtime = rx1(branch_text, r"- 当前版本:\s*(.+)")
    branch_status = rx1(branch_text, r"- 当前状态:\s*(.+)")
    branch_book_rule = find_line_contains(stage112_text, "- decision=第二分支保持三标的整体 book")
    branch_weights = find_line_contains(stage112_text, "- current_weights=")
    branch_demo_notional = find_line_contains(stage112_text, "- current_demo_notional=")
    branch_sol_mode = find_line_contains(stage112_text, "- sol_demo_mode=")

    btc_dual = find_line_contains(stage91_text, "- BTC | dual | btc_dual_fast_trend_dynlev_fix8:")
    btc_long = find_line_contains(stage91_text, "- BTC | long | btc_breakout_long_event_lb20_atr060_adx24_s050:")
    btc_short = find_line_contains(stage91_text, "- BTC | short | btc_retest_short_event_lb20_atr060_adx24_s072:")
    eth_active = find_line_contains(stage91_text, "- ETH | short | eth_short_shock_fast_lb16_atr052_adx22_s078:")
    eth_event1 = find_line_contains(stage91_text, "- ETH | short | eth_retest_short_trend_lb20_atr060_adx24_s068:")
    eth_event2 = find_line_contains(stage91_text, "- ETH | short | eth_fast_trend_shortonly:")
    sol_long = find_line_contains(stage91_text, "- SOL | long | sol_shortwave_smooth_longonly:")
    sol_short = find_line_contains(stage91_text, "- SOL | short | sol_hybrid_mr_shortonly:")

    # Proposed config files, no auto-switch
    main_cfg_out = root / "config_mainline_stage113_shadow_eventbridge.yml"
    main_shadow_out = root / "shadow_mainline_stage113_shadow_eventbridge.yml"
    branch_cfg_out = root / "config_shortwave_triple_book_stage113.yml"
    branch_shadow_out = root / "shadow_shortwave_triple_book_stage113.yml"
    manifest_out = reports_dir / "stage113_joint_apply_manifest_latest.txt"

    main_cfg_new = cfg_main_text
    main_cfg_new = replace_first_line_value(
        main_cfg_new,
        "version",
        "mainline_shadow_demo__combo_sr_soft_adx26_cd6_lb24_zone028_ref__stage113_eventbridge_v1",
    )
    main_cfg_new = replace_data_end(main_cfg_new, latest_date)

    main_shadow_new = shadow_main_text
    main_shadow_new = re.sub(
        r"^(\s*public_report_txt\s*:\s*).*$",
        r"\1~/Downloads/mainline_shadow_stage113_demo_report_latest.txt",
        main_shadow_new,
        flags=re.MULTILINE,
    )

    branch_cfg_new = cfg_preview_text
    branch_cfg_new = replace_first_line_value(
        branch_cfg_new,
        "version",
        "r252_branch_demo_triple_book_preview__btc025_eth060_sol015_stage113_v1",
    )
    branch_cfg_new = replace_data_end(branch_cfg_new, latest_date)

    branch_shadow_new = ensure_prefix_okxb(shadow_preview_text)

    write_text(main_cfg_out, main_cfg_new)
    write_text(main_shadow_out, main_shadow_new)
    write_text(branch_cfg_out, branch_cfg_new)
    write_text(branch_shadow_out, branch_shadow_new)

    manifest_lines = [
        "Stage113 联动应用清单",
        f"generated_at_utc={generated}",
        "",
        "主线：继续 live_base；提频只升 shadow，不直接替换 live。",
        "- 主线 shadow 首选: combo_sr_soft_adx26_cd6_lb24_zone028_ref",
        "- 第二顺位: combo_sr_soft_adx32_cd5_lb20_zone025",
        "- 事件桥接原则: 消息面只做放行/抑制，不裸触发；必须与结构/拥挤/波动确认联动。",
        "",
        "第二分支：保持 BTC / ETH / SOL 三标的整体 book。",
        "- BTC: dual_active / confirm leg",
        "- ETH: short_dominant / active PnL leg",
        "- SOL: observe_only on demo / research leg",
        "- 运行端不自动切当前 demo；只生成 stage113 规划配置。",
        "",
        "本轮生成文件：",
        f"- {main_cfg_out.name}",
        f"- {main_shadow_out.name}",
        f"- {branch_cfg_out.name}",
        f"- {branch_shadow_out.name}",
        "",
        "下一步：确认 stage113 包后，再决定是否把升级后的 preview 推到模拟盘。",
    ]
    write_text(manifest_out, "\n".join(manifest_lines) + "\n")

    report_lines = [
        "Stage113 主线事件桥接 + 支线三标的收益提效联动",
        "规则：只生成 1 个回传文件；不自动切当前 Demo；不改双终端规则。",
        f"generated_at_utc={generated}",
        "",
        "=== 主线当前有效结果 ===",
        f"- runtime_version={main_runtime}",
        f"- runtime_status={main_status}",
        f"- latest_signal_time={main_signal}",
        main_6y,
        main_recent,
        main_wf,
        main_gate,
        main_live_keep,
        main_shadow_bal,
        main_shadow_aggr,
        "- decision=继续 live_base；提频继续只升 shadow，先看 balanced，再看 aggressive。",
        "",
        "=== 第二分支三标的当前有效结果 ===",
        f"- runtime_version={branch_runtime}",
        f"- runtime_status={branch_status}",
        f"- latest_signal_time={branch_signal}",
        branch_weights if branch_weights != "-" else "- current_weights=btc:0.25 eth:0.60 sol:0.15",
        branch_demo_notional if branch_demo_notional != "-" else "- current_demo_notional=btc:20.0 eth:20.0 sol:0.0",
        branch_sol_mode if branch_sol_mode != "-" else "- sol_demo_mode=observe_only",
        btc_dual,
        btc_long,
        btc_short,
        eth_active,
        eth_event1,
        eth_event2,
        sol_long,
        sol_short,
        branch_book_rule if branch_book_rule != "-" else "- decision=第二分支保持三标的整体 book；BTC/ETH 继续 active/confirm，SOL 先留观察位。",
        "",
        "=== Stage113 联动优化规划 ===",
        "- mainline_track=结构放松 + 事件桥接；war / 宏观冲击阶段先看 1h 结构突破后的 15m 延续，不裸追新闻。",
        "- branch_track=BTC / ETH / SOL 分标的建模；BTC 继续 dual_active，ETH 保持 short_dominant 并保留 event-first 空腿，SOL 继续扩 observe/research，不贸然切 active。",
        "- update_demo_now=no",
        "- why=主线 live_base 仍优于直接替换；第二分支三标的 preview 已稳定，但 SOL 还未达 active 门槛。",
        "",
        "=== 已生成的 Stage113 规划文件 ===",
        f"- {main_cfg_out.name}",
        f"- {main_shadow_out.name}",
        f"- {branch_cfg_out.name}",
        f"- {branch_shadow_out.name}",
        f"- {manifest_out.name}",
        "",
        "=== 下一步 ===",
        "- 先确认 Stage113 包；下一轮再决定是否把 Stage113 preview 推到模拟盘。",
    ]
    report_path = reports_dir / "stage113_joint_event_tech_upgrade_latest.txt"
    write_text(report_path, "\n".join(report_lines) + "\n")

    zip_path = downloads / "stage113_joint_event_tech_upgrade_latest.zip"
    tmp_zip = downloads / ".stage113_joint_event_tech_upgrade_latest.tmp.zip"
    with ZipFile(tmp_zip, "w", compression=ZIP_DEFLATED) as zf:
        zf.write(report_path, arcname=report_path.name)
        zf.write(manifest_out, arcname=manifest_out.name)
        zf.write(okx_report, arcname=okx_report.name)
        zf.write(branch_report, arcname=branch_report.name)
        zf.write(main_cfg_out, arcname=main_cfg_out.name)
        zf.write(main_shadow_out, arcname=main_shadow_out.name)
        zf.write(branch_cfg_out, arcname=branch_cfg_out.name)
        zf.write(branch_shadow_out, arcname=branch_shadow_out.name)
    shutil.move(tmp_zip, zip_path)
    cleanup_download_exports(downloads, zip_path.name)
    return report_path, zip_path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    report_path, zip_path = build_report(root)
    print(f"[OK] report={report_path}")
    print(f"[OK] export={zip_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
