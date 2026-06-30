from __future__ import annotations

import argparse
import contextlib
import json
import math
import re
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _pct(x: Any, digits: int = 2) -> str:
    try:
        v = float(x)
    except Exception:
        return "NA"
    if math.isnan(v):
        return "NA"
    return f"{v * 100:.{digits}f}%"


def _pct_abs(x: Any, digits: int = 2) -> str:
    try:
        v = abs(float(x))
    except Exception:
        return "NA"
    if math.isnan(v):
        return "NA"
    return f"{v * 100:.{digits}f}%"


def _fnum(x: Any, digits: int = 2) -> str:
    try:
        v = float(x)
    except Exception:
        return "NA"
    if math.isnan(v):
        return "NA"
    return f"{v:.{digits}f}"


def _find_main_metrics(root: Path) -> dict[str, Any] | None:
    cands = [root / "reports" / "metrics_latest.json"]
    reports = root / "reports"
    if reports.exists():
        runs = sorted(reports.glob("run_*/metrics.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        cands.extend(runs)
    for p in cands:
        if p.exists() and p.is_file():
            data = _load_json(p)
            if isinstance(data, dict):
                m = data.get("metrics") if isinstance(data.get("metrics"), dict) else data
                if isinstance(m, dict) and m.get("total_return") is not None:
                    return m
    return None


def _read_text_first(paths: list[Path]) -> str:
    for p in paths:
        try:
            if p.exists() and p.is_file():
                return p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
    return ""


def _load_json_first(paths: list[Path]) -> dict[str, Any] | None:
    for p in paths:
        data = _load_json(p)
        if isinstance(data, dict):
            return data
    return None


def _find_symbol_overlay(root: Path, downloads: Path) -> dict[str, Any] | None:
    reports_raw = root / "reports" / "research_raw"
    cands = [
        reports_raw / "alt_shortwave_symbol_overlay_latest.json",
        downloads / "alt_shortwave_symbol_overlay_latest.json",
        reports_raw / "alt_shortwave_focus_grid_latest.json",
        downloads / "alt_shortwave_focus_grid_latest.json",
        reports_raw / "alt_shortwave_lab_latest.json",
        downloads / "alt_shortwave_lab_latest.json",
    ]
    data = _load_json_first(cands)
    if isinstance(data, dict) and isinstance(data.get("best"), dict):
        return data["best"]
    return None


def _parse_message_stack(root: Path, downloads: Path) -> dict[str, Any]:
    out: dict[str, Any] = {}
    txt = _read_text_first([
        root / "reports" / "message_stack_backtest_latest.txt",
        downloads / "message_stack_backtest_latest.txt",
        root / "message_stack_backtest_latest.txt",
    ])
    if not txt:
        return out
    base = re.search(r"【基线】\s*- trades=(\d+) win_rate=([\d.]+)% pf=([\d.]+) total_ret=([+-]?[\d.]+)% maxdd=([+-]?[\d.]+)%", txt)
    if base:
        out["base_trades"] = int(base.group(1))
        out["base_win_rate"] = float(base.group(2)) / 100.0
        out["base_pf"] = float(base.group(3))
        out["base_ret"] = float(base.group(4)) / 100.0
        out["base_maxdd"] = float(base.group(5)) / 100.0
    all_comb = re.search(r"- combined_stack: blocked=(\d+).*?pnl_delta=([+-]?[\d.]+) \| maxdd_delta=([+-]?[\d.]+)%", txt, re.S)
    if all_comb:
        out["all_blocked"] = int(all_comb.group(1))
        out["all_pnl_delta"] = float(all_comb.group(2))
        out["all_dd_delta"] = float(all_comb.group(3)) / 100.0
    agg = re.search(r"- aggregate: .*?blocked=(\d+) \| pnl_delta=([+-]?[\d.]+) \| maxdd_delta=([+-]?[\d.]+)%", txt)
    if agg:
        out["oos_blocked"] = int(agg.group(1))
        out["oos_pnl_delta"] = float(agg.group(2))
        out["oos_dd_delta"] = float(agg.group(3)) / 100.0
    return out


def _research_lines(root: Path, downloads: Path, mode: str) -> tuple[list[str], list[str]]:
    main = _find_main_metrics(root) or {}
    symbol_best = _find_symbol_overlay(root, downloads)
    msg = _parse_message_stack(root, downloads)

    lines: list[str] = []
    lines.append("研究回测简报（中文精简版）")
    lines.append(f"模式：{mode}")
    lines.append("")
    lines.append("一、主线系统（BTC+BNB）")
    if main:
        lines.append(f"- 总收益：{_pct(main.get('total_return'))}")
        lines.append(f"- 年化：{_pct(main.get('cagr'))}")
        lines.append(f"- 最大回撤：{_pct_abs(main.get('max_drawdown'))}")
        lines.append(f"- 盈亏比(PF)：{_fnum(main.get('profit_factor'))}")
        lines.append(f"- 交易次数：{int(main.get('trades', 0))}")
        lines.append(f"- 胜率：{_pct(main.get('win_rate'))}")
    else:
        lines.append("- 暂未读到主线指标。")

    lines.append("")
    lines.append("二、消息面联动")
    if msg:
        lines.append(
            f"- 全样本：combined_stack 屏蔽 {int(msg.get('all_blocked', 0))} 笔，收益增量 {msg.get('all_pnl_delta', 0.0):+.2f}，回撤改善 {_pct_abs(msg.get('all_dd_delta'))}"
        )
        if "oos_blocked" in msg:
            lines.append(
                f"- 滚动样本外：屏蔽 {int(msg.get('oos_blocked', 0))} 笔，收益增量 {msg.get('oos_pnl_delta', 0.0):+.2f}，回撤改善 {_pct_abs(msg.get('oos_dd_delta'))}"
            )
        lines.append("- 结论：继续保留在风险层，不升为 Alpha。")
    else:
        lines.append("- 暂未读到最新消息面联动结果。")

    lines.append("")
    lines.append("三、第二分支（ETH/SOL 短波）")
    if isinstance(symbol_best, dict):
        base = symbol_best.get("base") if isinstance(symbol_best.get("base"), dict) else {}
        ov = symbol_best.get("best_overlay") if isinstance(symbol_best.get("best_overlay"), dict) else {}
        gated = ov.get("gated") if isinstance(ov.get("gated"), dict) else {}
        name = symbol_best.get("name", "NA")
        symbol = str(symbol_best.get("symbol", "NA")).upper()
        variant = ov.get("variant", "NA")
        decision = ov.get("decision", symbol_best.get("decision", "继续研究"))
        lines.append(f"- 当前最优方向：{symbol} | 候选：{name}")
        if base:
            lines.append(
                f"- 原始结果：收益 {_pct(base.get('ret'))}，回撤 {_pct_abs(base.get('maxdd'))}，PF {_fnum(base.get('pf'))}，交易 {int(base.get('trades', 0))}"
            )
        if gated:
            lines.append(
                f"- 叠加消息面后：收益 {_pct(gated.get('ret'))}，回撤 {_pct_abs(gated.get('maxdd'))}，PF {_fnum(gated.get('pf'))}，交易 {int(gated.get('trades', 0))}"
            )
            lines.append(
                f"- 这次消息面方案：{variant}；屏蔽 {int(ov.get('blocked', 0))} 笔；收益增量 {float(ov.get('pnl_delta', 0.0)):+.2f}"
            )
        lines.append(f"- 当前决定：{decision}，暂不并入 live。")
    else:
        lines.append("- 暂未读到最新 ETH/SOL 短波结果。")

    lines.append("")
    lines.append("四、当前执行建议")
    lines.append("- 日常先跑 fast 批次；只有需要重新扫参数时，再跑 full 批次。")
    lines.append("- Downloads 只保留：okx_demo_report_latest.txt、deepseek_single_file_latest.txt、chatgpt_bundle_latest.zip。")

    deepseek: list[str] = []
    deepseek.append(f"【模式】{mode}")
    if main:
        deepseek.append(
            f"【主线】总收益 {_pct(main.get('total_return'))} / 年化 {_pct(main.get('cagr'))} / 最大回撤 {_pct_abs(main.get('max_drawdown'))} / PF {_fnum(main.get('profit_factor'))} / 交易 {int(main.get('trades', 0))}"
        )
    if msg:
        deepseek.append(
            f"【消息面】全样本 combined_stack: 屏蔽 {int(msg.get('all_blocked', 0))} 笔 / 收益增量 {msg.get('all_pnl_delta', 0.0):+.2f} / 回撤改善 {_pct_abs(msg.get('all_dd_delta'))}"
        )
        if "oos_blocked" in msg:
            deepseek.append(
                f"【消息面OOS】屏蔽 {int(msg.get('oos_blocked', 0))} 笔 / 收益增量 {msg.get('oos_pnl_delta', 0.0):+.2f} / 回撤改善 {_pct_abs(msg.get('oos_dd_delta'))}"
            )
        deepseek.append("【消息面结论】继续保留 risk layer，不升 Alpha")
    if isinstance(symbol_best, dict):
        base = symbol_best.get("base") if isinstance(symbol_best.get("base"), dict) else {}
        ov = symbol_best.get("best_overlay") if isinstance(symbol_best.get("best_overlay"), dict) else {}
        gated = ov.get("gated") if isinstance(ov.get("gated"), dict) else {}
        deepseek.append(
            f"【第二分支】{str(symbol_best.get('symbol','NA')).upper()} / {symbol_best.get('name','NA')} / 原始收益 {_pct(base.get('ret'))} / 原始回撤 {_pct_abs(base.get('maxdd'))} / 原始PF {_fnum(base.get('pf'))} / 原始交易 {int(base.get('trades', 0))}"
        )
        if gated:
            deepseek.append(
                f"【第二分支+消息面】收益 {_pct(gated.get('ret'))} / 回撤 {_pct_abs(gated.get('maxdd'))} / PF {_fnum(gated.get('pf'))} / 交易 {int(gated.get('trades', 0))} / overlay={ov.get('variant','NA')}"
            )
        deepseek.append(f"【第二分支结论】{ov.get('decision', symbol_best.get('decision', '继续研究'))}；暂不并线")
    deepseek.append("【执行】日常跑 fast；需要重扫参数时再跑 full")
    return lines, deepseek



def _stash_raw_outputs(downloads: Path, reports: Path) -> None:
    raw_dir = reports / "research_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    patterns = [
        "alt_*_latest.txt",
        "alt_*_latest.json",
        "message_stack_backtest_latest.txt",
        "message_stack_backtest_latest.json",
        "mainline_density_lab_latest.txt",
        "mainline_density_lab_latest.json",
        "current_demo_strategy_trades_latest.csv",
        "coinglass_ab_latest.txt",
        "coinglass_ab_latest.json",
        "message_combo_ab_latest.txt",
        "message_combo_ab_latest.json",
        "btc_*_latest.txt",
        "btc_*_latest.json",
        "event_window_*_latest.txt",
        "event_window_*_latest.json",
        "frequency_trade_audit_latest.txt",
        "frequency_trade_audit_latest.json",
    ]
    seen = set()
    for pat in patterns:
        for src in downloads.glob(pat):
            if not src.is_file():
                continue
            if src.name in seen:
                continue
            seen.add(src.name)
            with contextlib.suppress(Exception):
                (raw_dir / src.name).write_bytes(src.read_bytes())

def _cleanup_downloads(downloads: Path) -> None:
    keep = {
        "okx_demo_report_latest.txt",
        "deepseek_single_file_latest.txt",
        "chatgpt_bundle_latest.zip",
    }
    stale_names = {
        "support_bundle_latest.zip",
        "support_bundle_upload.zip",
        "deepseek_brief_latest.txt",
        "research_report_latest.txt",
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
    }
    if not downloads.exists():
        return
    for p in downloads.iterdir():
        try:
            if not p.is_file():
                continue
            if p.name in keep:
                continue
            if p.name in stale_names:
                p.unlink()
                continue
            if p.name.startswith("support_bundle") and p.suffix == ".zip":
                p.unlink()
                continue
            if p.name.startswith("deepseek_brief") and p.suffix == ".txt":
                p.unlink()
                continue
            if p.name.startswith("research_report") and p.suffix == ".txt":
                p.unlink()
                continue
        except Exception:
            pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--mode", default="fast")
    ap.add_argument("--cleanup-downloads", action="store_true")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    reports = root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    downloads = Path.home() / "Downloads"
    downloads.mkdir(parents=True, exist_ok=True)

    lines, deepseek = _research_lines(root, downloads, args.mode)
    report_text = "\n".join(lines) + "\n"
    deepseek_text = "\n".join(deepseek) + "\n"

    (reports / "research_report_latest.txt").write_text(report_text, encoding="utf-8")
    (reports / "deepseek_brief_latest.txt").write_text(deepseek_text, encoding="utf-8")

    _stash_raw_outputs(downloads, reports)

    if args.cleanup_downloads:
        _cleanup_downloads(downloads)

    print(report_text)


if __name__ == "__main__":
    main()
