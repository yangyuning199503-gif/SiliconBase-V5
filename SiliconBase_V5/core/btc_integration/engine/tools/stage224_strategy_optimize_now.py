from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        obj = json.loads(_read_text(path))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _parse_runtime(path: Path) -> dict[str, Any]:
    txt = _read_text(path)
    out: dict[str, Any] = {"path": str(path)}
    for prefix, key in [
        ("- 当前状态:", "status"),
        ("- 状态原因:", "reason"),
        ("- 当前版本:", "version"),
        ("- 策略真实成交已开始:", "live_fill_started"),
        ("- 当前模式:", "risk_mode"),
        ("- 执行方式:", "exec_mode"),
    ]:
        m = re.search(rf"^{re.escape(prefix)}\s*(.+)$", txt, re.M)
        if m:
            out[key] = m.group(1).strip()
    return out


def _parse_stage99(path: Path) -> dict[str, Any]:
    txt = _read_text(path)
    out: dict[str, Any] = {"path": str(path)}
    for key in ["live_keep", "shadow_balanced", "shadow_aggressive"]:
        m = re.search(rf"^- {re.escape(key)}: (.+)$", txt, re.M)
        if m:
            out[key] = m.group(1).strip()
    for key in ["balanced_ready", "aggressive_ready"]:
        m = re.search(rf"^- {re.escape(key)}=(.+)$", txt, re.M)
        if m:
            out[key] = m.group(1).strip()
    return out


def _parse_stage212(path: Path) -> dict[str, Any]:
    txt = _read_text(path)
    out: dict[str, Any] = {"path": str(path)}
    patterns = {
        "baseline": r"(?i)baseline.*?6年[:：].+",
        "best": r"(?i)(?:最优|best).*",
        "recent": r"(?i)近2年.*",
        "wf": r"(?i)WF.*",
    }
    for key, pat in patterns.items():
        m = re.search(pat, txt)
        if m:
            out[key] = m.group(0).strip()
    if not out.get("best"):
        m = re.search(r"sizing_[^\n]+", txt)
        if m:
            out["best"] = m.group(0).strip()
    return out


def _parse_stage223(path: Path) -> dict[str, Any]:
    txt = _read_text(path)
    out: dict[str, Any] = {"path": str(path)}
    sections = {}
    for block in ["mainline_runtime", "truth_locked_sync", "conclusion"]:
        m = re.search(rf"\[{re.escape(block)}\](.*?)(?:\n\[[^\n]+\]|\Z)", txt, re.S)
        if m:
            sections[block] = m.group(1).strip()
    out.update(sections)
    for seed in [
        "eth_reclaim_hold_long_lb11_atr044_adx16_s056",
        "eth_reclaim_long_lb11_atr044_adx16_s060",
        "eth_reclaim_long_lb11_atr043_adx16_s072",
        "btc_breakout_long_event_lb20_atr060_adx24_s050",
        "btc_squeeze_follow_long_lb16_atr050_adx20_s058",
        "btc_retest_short_event_lb16_atr052_adx20_s074",
        "btc_retest_short_event_lb10_atr044_adx16_s082",
        "sol_pullback_link_long_adx26_cd6_lb22_zone026_s044",
        "sol_pullback_pair_long_adx24_cd4_lb20_zone024_s046",
        "sol_guarded_short_accel_lb14_atr052_adx18_cd1_s076",
        "sol_guarded_short_accel_lb10_atr048_adx15_cd1_s080",
    ]:
        if seed in txt:
            out.setdefault("seed_hits", []).append(seed)
    return out


def _line_or_dash(value: Any) -> str:
    return str(value).strip() if value else "-"


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage224 策略优化统一摘要")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    raw = root / "reports" / "research_raw"
    raw.mkdir(parents=True, exist_ok=True)

    stage99_txt = raw / "stage99_mainline_frequency_push_latest.txt"
    stage212_txt = raw / "stage212_message_sizing_overlay_frontier_latest.txt"
    stage223_txt = raw / "stage223_truth_locked_broadfront_frontier_latest.txt"
    okx_report = Path.home() / "Downloads" / "okx_demo_report_latest.txt"
    branch_report = Path.home() / "Downloads" / "branch_demo_report_latest.txt"
    if not okx_report.exists():
        okx_report = raw / "okx_demo_report_latest.txt"
    if not branch_report.exists():
        branch_report = raw / "branch_demo_report_latest.txt"

    stage99 = _parse_stage99(stage99_txt)
    stage212 = _parse_stage212(stage212_txt)
    stage223 = _parse_stage223(stage223_txt)
    main_rt = _parse_runtime(okx_report)
    branch_rt = _parse_runtime(branch_report)

    lines: list[str] = []
    lines.append("Stage224 strategy optimize now")
    lines.append("")
    lines.append("[mainline_runtime]")
    lines.append(f"- status={_line_or_dash(main_rt.get('status'))} | reason={_line_or_dash(main_rt.get('reason'))} | live_fill_started={_line_or_dash(main_rt.get('live_fill_started'))}")
    lines.append(f"- version={_line_or_dash(main_rt.get('version'))}")
    if stage223.get("mainline_runtime"):
        for ln in str(stage223["mainline_runtime"]).splitlines():
            lines.append(ln.strip())
    lines.append("")
    lines.append("[mainline_frequency_push]")
    lines.append(f"- live_keep={_line_or_dash(stage99.get('live_keep'))}")
    lines.append(f"- shadow_balanced={_line_or_dash(stage99.get('shadow_balanced'))}")
    lines.append(f"- shadow_aggressive={_line_or_dash(stage99.get('shadow_aggressive'))}")
    lines.append(f"- balanced_ready={_line_or_dash(stage99.get('balanced_ready'))}")
    lines.append(f"- aggressive_ready={_line_or_dash(stage99.get('aggressive_ready'))}")
    lines.append("")
    lines.append("[mainline_message_sizing]")
    lines.append(f"- best={_line_or_dash(stage212.get('best'))}")
    if stage212.get("recent"):
        lines.append(f"- recent={stage212['recent']}")
    if stage212.get("wf"):
        lines.append(f"- wf={stage212['wf']}")
    lines.append("")
    lines.append("[branch_runtime]")
    lines.append(f"- status={_line_or_dash(branch_rt.get('status'))} | reason={_line_or_dash(branch_rt.get('reason'))} | live_fill_started={_line_or_dash(branch_rt.get('live_fill_started'))}")
    lines.append(f"- version={_line_or_dash(branch_rt.get('version'))}")
    lines.append("")
    lines.append("[branch_truth_locked_broadfront]")
    if stage223.get("truth_locked_sync"):
        for ln in str(stage223["truth_locked_sync"]).splitlines():
            lines.append(ln.strip())
    lines.append(f"- key_seed_hits={', '.join(stage223.get('seed_hits', [])) if stage223.get('seed_hits') else '-'}")
    if stage223.get("conclusion"):
        for ln in str(stage223["conclusion"]).splitlines():
            lines.append(ln.strip())
    lines.append("")
    lines.append("[action]")
    lines.append("- 先跑主线提频 + 主线消息仓位层 + 分支 truth-locked broadfront，不直接切 runtime。")
    lines.append("- 主线继续围绕 fix8_lock18 的平衡/激进候选做提频；消息层只做 BOOST/CUT sizing。")
    lines.append("- 分支继续保留 BTC / ETH / SOL 多路径：ETH s056 / s060 / s072 + short s068；BTC s050 / s058 / s074 / s082 + dual；SOL s044 / s046 / s076 / s080。")

    out_txt = raw / "stage224_strategy_optimize_now_latest.txt"
    out_json = raw / "stage224_strategy_optimize_now_latest.json"
    out_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    out_json.write_text(json.dumps({
        "mainline_runtime": main_rt,
        "branch_runtime": branch_rt,
        "stage99": stage99,
        "stage212": stage212,
        "stage223": stage223,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(out_txt)
    print(out_json)


if __name__ == "__main__":
    main()
