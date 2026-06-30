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


def first_existing(paths: list[Path]) -> Path | None:
    for p in paths:
        if p.exists():
            return p
    return None


def rx1(text: str, pattern: str, default: str = "-") -> str:
    m = re.search(pattern, text, re.MULTILINE)
    return m.group(1).strip() if m else default


def section_line(text: str, prefix: str) -> str:
    for line in text.splitlines():
        if line.strip().startswith(prefix):
            return line.strip()
    return f"{prefix}-"


def contains_all(text: str, needles: list[str]) -> bool:
    return all(n in text for n in needles)


def parse_weights(cfg_text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    in_weights = False
    for raw in cfg_text.splitlines():
        line = raw.rstrip()
        if re.match(r"^\s*weights:\s*$", line):
            in_weights = True
            continue
        if in_weights:
            m = re.match(r"^\s{2,}([a-zA-Z0-9_]+):\s*([0-9.]+)\s*$", line)
            if m:
                out[m.group(1)] = m.group(2)
                continue
            if line and not line.startswith("  "):
                break
    return out


def parse_notional_by_symbol(shadow_text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    in_block = False
    for raw in shadow_text.splitlines():
        line = raw.rstrip()
        if re.match(r"^\s*notional_usdt_by_symbol:\s*$", line):
            in_block = True
            continue
        if in_block:
            m = re.match(r"^\s{6,}([a-zA-Z0-9_]+):\s*([0-9.]+)\s*$", line)
            if m:
                out[m.group(1)] = m.group(2)
                continue
            if line and not line.startswith("      "):
                break
    return out


def extract_stage91_asset_block(text: str, asset_prefix: str) -> list[str]:
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip() == f"- {asset_prefix}:" or line.strip().startswith(f"- {asset_prefix}: "):
            start = i
            break
    if start is None:
        return [f"- {asset_prefix}: -"]
    out = [lines[start].strip()]
    for j in range(start + 1, min(start + 4, len(lines))):
        if lines[j].startswith("- "):
            break
        out.append(lines[j].strip())
    return out


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
    cfg_preview = first_existing([
        root / "config_shortwave_triple_book_preview.yml",
    ])
    shadow_preview = first_existing([
        root / "shadow_shortwave_triple_book_preview.yml",
    ])

    missing = [
        name for name, p in [
            ("okx_demo_report_latest.txt", okx_report),
            ("branch_demo_report_latest.txt", branch_report),
            ("stage99_mainline_frequency_push_latest.txt", stage99),
            ("stage91_branch_event_alpha_matrix_latest.txt", stage91),
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
    cfg_text = read_text(cfg_preview)
    shadow_text = read_text(shadow_preview)

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    mainline_version = rx1(okx_text, r"- 当前版本:\s*(.+)")
    mainline_status = rx1(okx_text, r"- 当前状态:\s*(.+)")
    mainline_signal = rx1(okx_text, r"- 最近策略信号时间\(UTC\+8\):\s*(.+)")

    branch_version = rx1(branch_text, r"- 当前版本:\s*(.+)")
    branch_status = rx1(branch_text, r"- 当前状态:\s*(.+)")
    branch_signal = rx1(branch_text, r"- 最近策略信号时间\(UTC\+8\):\s*(.+)")

    live_keep = section_line(stage99_text, "- live_keep:")
    shadow_bal = section_line(stage99_text, "- shadow_balanced:")
    shadow_aggr = section_line(stage99_text, "- shadow_aggressive:")

    weights = parse_weights(cfg_text)
    notionals = parse_notional_by_symbol(shadow_text)

    triple_visible = contains_all(branch_text, ["[BTC]", "[ETH]", "[SOL]"])

    btc_block = extract_stage91_asset_block(stage91_text, "BTC")
    eth_block = extract_stage91_asset_block(stage91_text, "ETH")
    sol_block = extract_stage91_asset_block(stage91_text, "SOL")

    # Decisions
    mainline_keep_live = "yes"
    mainline_promote_now = "no"
    branch_design_fixed = "BTC / ETH / SOL"
    branch_preview_stable = "yes" if triple_visible and "triple_book_preview" in branch_version else "no"
    branch_demo_update_now = "preview_keep" if branch_preview_stable == "yes" else "hold"
    sol_demo_mode = "observe_only" if notionals.get("sol", "0") in {"0", "0.0"} else "active"

    report = []
    report.append("Stage112 主线/支线联动升级门槛判定")
    report.append("规则：主线提频与第二分支三标的一起规划；只导出 1 个回传文件。")
    report.append(f"generated_at_utc={generated}")
    report.append("")
    report.append("=== 主线 ===")
    report.append(f"- runtime_version={mainline_version}")
    report.append(f"- runtime_status={mainline_status}")
    report.append(f"- latest_signal_time={mainline_signal}")
    report.append(f"- keep_live={mainline_keep_live}")
    report.append(f"- promote_live_now={mainline_promote_now}")
    report.append(live_keep)
    report.append(shadow_bal)
    report.append(shadow_aggr)
    report.append("- decision=继续 live_base；提频仍只升 shadow，不直接替换 live。")
    report.append("")
    report.append("=== 第二分支三标的 ===")
    report.append(f"- runtime_version={branch_version}")
    report.append(f"- runtime_status={branch_status}")
    report.append(f"- latest_signal_time={branch_signal}")
    report.append(f"- design_book={branch_design_fixed}")
    report.append(f"- triple_book_visible={str(triple_visible).lower()}")
    report.append(f"- preview_stable={branch_preview_stable}")
    report.append(f"- current_weights=btc:{weights.get('btc','-')} eth:{weights.get('eth','-')} sol:{weights.get('sol','-')}")
    report.append(f"- current_demo_notional=btc:{notionals.get('btc','-')} eth:{notionals.get('eth','-')} sol:{notionals.get('sol','-')}")
    report.append(f"- sol_demo_mode={sol_demo_mode}")
    report.append(f"- demo_update_now={branch_demo_update_now}")
    report.append("- decision=第二分支保持三标的整体 book；BTC/ETH 继续作为 active/confirm 组合，SOL 先留观察位，不贸然给单。")
    report.append("")
    report.append("=== Stage91 资产建议摘录 ===")
    report.extend(btc_block)
    report.extend(eth_block)
    report.extend(sol_block)
    report.append("")
    report.append("=== 联动升级门槛 ===")
    report.append("- gate_mainline=shadow 候选在近2年提高频次且 WF 不明显劣化，才考虑下一步。")
    report.append("- gate_branch=三标的 preview 稳定 + BTC/ETH 可持续出信号 + SOL 至少出现可用观察路径，再考虑更进一步。")
    report.append("- gate_event_tech=消息面只做放行/抑制，不单独裸触发；必须与结构/拥挤/波动确认联动。")
    report.append("")
    report.append("=== 下一步 ===")
    report.append("- 主线：继续 live_base，shadow 继续盯 combo_sr_soft_adx26_cd6_lb24_zone028_ref / combo_sr_soft_adx32_cd5_lb20_zone025。")
    report.append("- 支线：继续 BTC/ETH/SOL 三标的 preview；先不把 SOL 从 observe_only 强行切成 active。")
    report.append("- 下一轮直接做 Stage113：主线事件桥接 + 支线三标的收益提效联动。")

    report_path = reports_dir / "stage112_joint_upgrade_gate_latest.txt"
    report_path.write_text("\n".join(report) + "\n", encoding="utf-8")

    zip_path = downloads / "stage112_joint_upgrade_gate_latest.zip"
    tmp_zip = downloads / ".stage112_joint_upgrade_gate_latest.tmp.zip"
    with ZipFile(tmp_zip, "w", compression=ZIP_DEFLATED) as zf:
        zf.write(report_path, arcname=report_path.name)
        zf.write(okx_report, arcname=okx_report.name)
        zf.write(branch_report, arcname=branch_report.name)
        zf.write(cfg_preview, arcname=cfg_preview.name)
        zf.write(shadow_preview, arcname=shadow_preview.name)
    shutil.move(tmp_zip, zip_path)
    return report_path, zip_path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    report_path, zip_path = build_report(root)
    print(f"[OK] report={report_path}")
    print(f"[OK] export={zip_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
