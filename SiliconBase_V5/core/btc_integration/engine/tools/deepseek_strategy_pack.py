from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _read_first(paths: list[Path]) -> tuple[Path | None, str]:
    for p in paths:
        try:
            if p.exists() and p.is_file():
                return p, p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
    return None, ""


def _load_json_first(paths: list[Path]) -> tuple[Path | None, dict[str, Any] | None]:
    for p in paths:
        try:
            if p.exists() and p.is_file():
                return p, json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
    return None, None


def _pct(x: Any, digits: int = 2) -> str:
    try:
        return f"{float(x) * 100:.{digits}f}%"
    except Exception:
        return "NA"


def _pct_abs(x: Any, digits: int = 2) -> str:
    try:
        return f"{abs(float(x)) * 100:.{digits}f}%"
    except Exception:
        return "NA"


def _num(x: Any, digits: int = 3) -> str:
    try:
        return f"{float(x):.{digits}f}"
    except Exception:
        return "NA"


def _parse_okx_demo(txt: str) -> dict[str, Any]:
    out: dict[str, Any] = {"free_sources": []}
    def _grab(label: str) -> str:
        m = re.search(rf"- {re.escape(label)}: (.+)", txt)
        return m.group(1).strip() if m else ""

    out["heartbeat"] = _grab("报告心跳(UTC+8)")
    out["state"] = _grab("当前状态")
    out["state_reason"] = _grab("状态原因")
    out["version"] = _grab("当前版本")
    out["next_run"] = _grab("下一轮执行(UTC+8)")
    out["shadow_ok"] = _grab("最近影子执行成功")
    out["risk_mode"] = _grab("当前模式")
    out["pause_new_entries"] = _grab("是否会暂停新开仓")
    out["trigger_reason"] = _grab("触发原因")

    for sec in ["BTC", "BNB", "ETH", "SOL"]:
        m = re.search(rf"\[{sec}\][\s\S]*?- 策略目标: side=([^\s]+) mode=([^\s]+) tag=([^\n]+)[\s\S]*?- 待处理订单: (\d+)", txt)
        if m:
            out.setdefault("targets", {})[sec] = {
                "side": m.group(1),
                "mode": m.group(2),
                "tag": m.group(3).strip(),
                "pending_orders": int(m.group(4)),
            }

    in_free = False
    for raw in txt.splitlines():
        line = raw.strip()
        if line.startswith("【免费结构化源】"):
            in_free = True
            continue
        if in_free and line.startswith("【"):
            break
        if in_free and line.startswith("- "):
            body = line[2:]
            if body.startswith("当前用途") or body.startswith("快照状态") or body.startswith("最新重点"):
                continue
            name = body.split(":", 1)[0].strip()
            if name:
                out["free_sources"].append(name)
    return out


def _parse_message_stack(txt: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    m = re.search(r"【基线】\s*- trades=(\d+) win_rate=([\d.]+)% pf=([\d.]+) total_ret=([+-]?[\d.]+)% maxdd=([+-]?[\d.]+)%", txt)
    if m:
        out["baseline"] = {
            "trades": int(m.group(1)),
            "win_rate": float(m.group(2)) / 100.0,
            "pf": float(m.group(3)),
            "ret": float(m.group(4)) / 100.0,
            "maxdd": float(m.group(5)) / 100.0,
        }
    m = re.search(r"- combined_stack: blocked=(\d+) .*?pnl_delta=([+-]?[\d.]+) \| maxdd_delta=([+-]?[\d.]+)%", txt, re.S)
    if m:
        out["combined_all"] = {
            "blocked": int(m.group(1)),
            "pnl_delta": float(m.group(2)),
            "maxdd_delta": float(m.group(3)) / 100.0,
        }
    m = re.search(r"- aggregate: .*?blocked=(\d+) \| pnl_delta=([+-]?[\d.]+) \| maxdd_delta=([+-]?[\d.]+)%", txt)
    if m:
        out["combined_oos"] = {
            "blocked": int(m.group(1)),
            "pnl_delta": float(m.group(2)),
            "maxdd_delta": float(m.group(3)) / 100.0,
        }
    m = re.search(r"- event_windows=(\d+)", txt)
    if m:
        out["event_windows"] = int(m.group(1))
    return out


def _parse_mainline_density(json_obj: dict[str, Any] | None, txt: str) -> dict[str, Any]:
    out: dict[str, Any] = {"top_candidates": []}
    if isinstance(json_obj, dict):
        rows = list(json_obj.get("rows") or [])
        if rows:
            rows_sorted = sorted(rows, key=lambda r: (float(r.get("score", 0.0)), int(r.get("trades", 0)), float(r.get("pf", 0.0)), float(r.get("ret", 0.0))), reverse=True)
            out["top_candidates"] = rows_sorted[:3]
            for row in rows_sorted:
                if row.get("name") == "baseline":
                    out["baseline"] = row
                    break
        overlay = json_obj.get("overlay") or {}
        if isinstance(overlay, dict):
            out["overlay"] = overlay
    if not out["top_candidates"] and txt:
        for line in txt.splitlines():
            m = re.match(r"- ([\w_]+): trades=(\d+) .*?pf=([\d.]+) .*?ret=([+-]?[\d.]+)% .*?maxDD=([+-]?[\d.]+)% .*?score=([+-]?[\d.]+)", line.strip())
            if m:
                out["top_candidates"].append({
                    "name": m.group(1),
                    "trades": int(m.group(2)),
                    "pf": float(m.group(3)),
                    "ret": float(m.group(4)) / 100.0,
                    "maxdd": float(m.group(5)) / 100.0,
                    "score": float(m.group(6)),
                })
        if out["top_candidates"]:
            out["top_candidates"] = out["top_candidates"][:3]
    return out


def _parse_branch_overlay(txt: str) -> dict[str, Any]:
    out: dict[str, Any] = {"candidates": []}
    for line in txt.splitlines():
        m = re.match(
            r"- ([\w_]+): symbol=(\w+) \| base_trades=(\d+) \| base_pf=([\d.]+) \| base_ret=([+-]?[\d.]+)% \| base_maxDD=([+-]?[\d.]+)%",
            line.strip(),
        )
        if m:
            out["candidates"].append({
                "name": m.group(1),
                "symbol": m.group(2).lower(),
                "base_trades": int(m.group(3)),
                "base_pf": float(m.group(4)),
                "base_ret": float(m.group(5)) / 100.0,
                "base_maxdd": float(m.group(6)) / 100.0,
            })
    best = re.search(r"- 当前最优：([\w_]+) \| symbol=(\w+) \| overlay=([^|]+) \| decision=(.+)", txt)
    if best:
        out["best"] = {
            "name": best.group(1),
            "symbol": best.group(2).lower(),
            "overlay": best.group(3).strip(),
            "decision": best.group(4).strip(),
        }
    return out


def _safe_copy(src: Path | None, dst: Path) -> None:
    if not src:
        return
    try:
        if src.exists() and src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    except Exception:
        pass


def main() -> None:
    ap = argparse.ArgumentParser(description="为 DeepSeek 生成策略报告、数据 JSON 和 zip 打包。")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    downloads = Path.home() / "Downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    reports = root / "reports"
    raw_dir = reports / "research_raw"

    msg_p, msg_txt = _read_first([
        downloads / "message_stack_backtest_latest.txt",
        raw_dir / "message_stack_backtest_latest.txt",
        reports / "message_stack_backtest_latest.txt",
    ])
    main_json_p, main_json = _load_json_first([
        downloads / "mainline_density_lab_latest.json",
        raw_dir / "mainline_density_lab_latest.json",
    ])
    main_txt_p, main_txt = _read_first([
        downloads / "mainline_density_lab_latest.txt",
        raw_dir / "mainline_density_lab_latest.txt",
    ])
    branch_txt_p, branch_txt = _read_first([
        downloads / "alt_shortwave_message_overlay_latest.txt",
        raw_dir / "alt_shortwave_message_overlay_latest.txt",
    ])
    okx_p, okx_txt = _read_first([
        downloads / "okx_demo_report_latest.txt",
        reports / "okx_demo_report_latest.txt",
    ])
    trades_csv = downloads / "current_demo_strategy_trades_latest.csv"
    if not trades_csv.exists():
        alt_csv = reports / "current_demo_strategy_trades_latest.csv"
        trades_csv = alt_csv if alt_csv.exists() else Path()

    okx = _parse_okx_demo(okx_txt)
    msg = _parse_message_stack(msg_txt)
    mainline = _parse_mainline_density(main_json, main_txt)
    branch = _parse_branch_overlay(branch_txt)

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    summary: dict[str, Any] = {
        "generated_at_utc": ts,
        "project_dir": str(root),
        "runtime": okx,
        "message_stack": msg,
        "mainline_density": mainline,
        "branch_overlay": branch,
        "goals": {
            "mainline": [
                "把消息面继续融入主线，但优先作为 risk layer / overlay，而不是粗暴升 alpha",
                "在不明显伤害 PF 和回撤的前提下，把主线交易频次从 6 年 144 笔提高到更合理水平",
                "把免费信息源继续补齐到可持续运维状态",
            ],
            "branch": [
                "继续做 SOL-first、ETH-second 的短波分支联动回测和策略优化",
                "达到合格标准后再接 OKX 模拟盘，且与主线分终端运行，避免冲突",
            ],
        },
        "questions_for_deepseek": [
            "如何在保住 PF/回撤的前提下，提高主线交易频次，而不是简单放松全局过滤？",
            "消息面更适合做 risk gate、regime switch、position sizing 还是 intraday overlay？",
            "对加息/降息、美股开盘、战争、监管、巨鲸、黑天鹅这几类事件，怎样设计分层响应最稳？",
            "对 SOL/ETH 分支，哪些结构更适合短波：事件窗、波动状态、盘口拥挤、对冲腿还是分时段过滤？",
            "是否有更优的免费数据源组合，能提升实时性和稳定性，同时便于长期维护？",
            "主线与分支是否应该共享一套风险预算与暂停新开仓逻辑，还是拆成资产/策略级风险层？",
        ],
    }

    lines: list[str] = []
    lines.append("策略报告（发 DeepSeek）")
    lines.append(f"生成时间: {ts}")
    lines.append("")
    lines.append("一、当前系统状态")
    if okx:
        lines.append(f"- 自动盘状态: {okx.get('state') or 'NA'} | reason={okx.get('state_reason') or 'NA'} | 版本={okx.get('version') or 'NA'}")
        lines.append(f"- 最近影子执行: {okx.get('shadow_ok') or 'NA'} | 下一轮: {okx.get('next_run') or 'NA'}")
        lines.append(f"- CoinGlass 风险层: mode={okx.get('risk_mode') or 'NA'} | pause_new_entries={okx.get('pause_new_entries') or 'NA'} | trigger={okx.get('trigger_reason') or 'NA'}")
        if okx.get("targets"):
            tgt_bits = []
            for sym, info in okx["targets"].items():
                tgt_bits.append(f"{sym}:{info.get('side','NA')}/{info.get('mode','NA')}/pending={info.get('pending_orders', 'NA')}")
            lines.append(f"- 当前策略目标: {' ; '.join(tgt_bits)}")
        if okx.get("free_sources"):
            lines.append("- 当前已接入免费结构化源: " + " / ".join(okx["free_sources"]))
        lines.append("- 付费核心源: CoinGlass（继续保留）")
    else:
        lines.append("- 未读到最新自动盘报告。")

    lines.append("")
    lines.append("二、主线（BTC+BNB）现状")
    base = msg.get("baseline") or {}
    if base:
        lines.append(
            f"- 基线回测: trades={base.get('trades')} | PF={_num(base.get('pf'))} | total_ret={_pct(base.get('ret'))} | maxDD={_pct_abs(base.get('maxdd'))} | win_rate={_pct(base.get('win_rate'))}"
        )
        lines.append("- 核心问题: 主线交易频次过低，6 年仅 144 笔，漏掉了太多机会。")
    else:
        lines.append("- 未读到主线基线回测。")

    combined_all = msg.get("combined_all") or {}
    combined_oos = msg.get("combined_oos") or {}
    if combined_all:
        lines.append(
            f"- 消息面联动(全样本): combined_stack 屏蔽 {combined_all.get('blocked')} 笔坏单，收益增量 {combined_all.get('pnl_delta', 0.0):+.2f}，回撤改善 {_pct_abs(combined_all.get('maxdd_delta'))}。"
        )
    if combined_oos:
        lines.append(
            f"- 消息面联动(滚动样本外): 屏蔽 {combined_oos.get('blocked')} 笔，收益增量 {combined_oos.get('pnl_delta', 0.0):+.2f}，回撤改善 {_pct_abs(combined_oos.get('maxdd_delta'))}。"
        )
    lines.append("- 当前原则: 消息面继续保留在 risk layer / overlay，不直接升 alpha。")

    lines.append("")
    lines.append("三、主线提频实验")
    top = mainline.get("top_candidates") or []
    if top:
        for i, row in enumerate(top[:3], 1):
            lines.append(
                f"- 候选{i}: {row.get('name')} | trades={row.get('trades')} | PF={_num(row.get('pf'))} | ret={_pct(row.get('ret'))} | maxDD={_pct_abs(row.get('maxdd'))}"
            )
        overlay = (mainline.get("overlay") or {}).get("combo_sr_soft") if isinstance(mainline.get("overlay"), dict) else None
        if isinstance(overlay, dict):
            gated = overlay.get("gated") or {}
            lines.append(
                f"- 当前最优候选 combo_sr_soft 叠加 combined_stack 后: gated_trades={gated.get('trades')} | gated_PF={_num(gated.get('pf'))} | gated_ret={_pct(gated.get('ret'))} | gated_maxDD={_pct_abs(gated.get('maxdd'))}"
            )
        lines.append("- 当前判断: combo_sr_soft 方向对，但仍需 walk-forward / overfit check；暂不改 live。")
    else:
        lines.append("- 未读到主线提频实验结果。")

    lines.append("")
    lines.append("四、分支（SOL / ETH 短波）")
    best_branch = branch.get("best") or {}
    if best_branch:
        lines.append(
            f"- 当前 quick research 最优记分候选: {best_branch.get('name')} | symbol={str(best_branch.get('symbol','NA')).upper()} | overlay={best_branch.get('overlay')} | decision={best_branch.get('decision')}"
        )
    if branch.get("candidates"):
        for row in branch.get("candidates", [])[:4]:
            lines.append(
                f"- 候选: {row.get('name')} | symbol={str(row.get('symbol','NA')).upper()} | trades={row.get('base_trades')} | PF={_num(row.get('base_pf'))} | ret={_pct(row.get('base_ret'))} | maxDD={_pct_abs(row.get('base_maxdd'))}"
            )
    lines.append("- 当前口径仍是 SOL-first、ETH-second；两条都还没达到并线/接模拟盘标准。")

    lines.append("")
    lines.append("五、希望 DeepSeek 重点给建议的方向")
    for q in summary["questions_for_deepseek"]:
        lines.append(f"- {q}")

    lines.append("")
    lines.append("六、我这边当前倾向")
    lines.append("- 主线提频优先做『轻量再入场 overlay + continuation overlay』，而不是一刀切放松全局过滤。")
    lines.append("- 消息面优先做分层：黑天鹅/战争/监管做强风险门；宏观/美股开盘做时段或 regime 门；巨鲸/拥挤/波动做仓位或二级过滤。")
    lines.append("- 分支可重点尝试：事件窗 + 波动状态 + 拥挤度 + 对冲腿 的组合，而不是只堆参数。")
    lines.append("- 主线与分支共用同一 OKX 交易所 API，但分终端运行、分策略文件、分持仓确认与纠错。")

    report_text = "\n".join(lines) + "\n"
    data_json_text = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"

    data_lines: list[str] = []
    data_lines.append("策略数据（发 DeepSeek）")
    data_lines.append(f"生成时间: {ts}")
    data_lines.append("")
    data_lines.append("【运行状态】")
    data_lines.append(f"state={okx.get('state', 'NA')} | reason={okx.get('state_reason', 'NA')} | version={okx.get('version', 'NA')}")
    data_lines.append(f"shadow_ok={okx.get('shadow_ok', 'NA')} | next_run={okx.get('next_run', 'NA')}")
    data_lines.append(f"risk_mode={okx.get('risk_mode', 'NA')} | pause_new_entries={okx.get('pause_new_entries', 'NA')} | trigger={okx.get('trigger_reason', 'NA')}")
    if okx.get('free_sources'):
        data_lines.append("free_sources=" + " | ".join(okx.get('free_sources', [])))
    if okx.get('targets'):
        for sym, info in okx['targets'].items():
            data_lines.append(f"target_{sym}=side:{info.get('side','NA')} mode:{info.get('mode','NA')} pending:{info.get('pending_orders','NA')}")
    data_lines.append("")
    data_lines.append("【主线基线】")
    if base:
        data_lines.append(f"trades={base.get('trades')} | pf={_num(base.get('pf'))} | ret={_pct(base.get('ret'))} | maxdd={_pct_abs(base.get('maxdd'))} | win_rate={_pct(base.get('win_rate'))}")
    data_lines.append("")
    data_lines.append("【消息面联动】")
    if combined_all:
        data_lines.append(f"combined_all=blocked:{combined_all.get('blocked')} pnl_delta:{combined_all.get('pnl_delta', 0.0):+.2f} maxdd_delta:{_pct_abs(combined_all.get('maxdd_delta'))}")
    if combined_oos:
        data_lines.append(f"combined_oos=blocked:{combined_oos.get('blocked')} pnl_delta:{combined_oos.get('pnl_delta', 0.0):+.2f} maxdd_delta:{_pct_abs(combined_oos.get('maxdd_delta'))}")
    data_lines.append("")
    data_lines.append("【主线提频候选】")
    for row in top[:5]:
        data_lines.append(f"{row.get('name')} | trades={row.get('trades')} | pf={_num(row.get('pf'))} | ret={_pct(row.get('ret'))} | maxdd={_pct_abs(row.get('maxdd'))}")
    overlay = (mainline.get("overlay") or {}).get("combo_sr_soft") if isinstance(mainline.get("overlay"), dict) else None
    if isinstance(overlay, dict):
        gated = overlay.get("gated") or {}
        data_lines.append(f"combo_sr_soft_gated | trades={gated.get('trades')} | pf={_num(gated.get('pf'))} | ret={_pct(gated.get('ret'))} | maxdd={_pct_abs(gated.get('maxdd'))}")
    data_lines.append("")
    data_lines.append("【分支候选】")
    if best_branch:
        data_lines.append(f"best={best_branch.get('name')} | symbol={str(best_branch.get('symbol','NA')).upper()} | overlay={best_branch.get('overlay')} | decision={best_branch.get('decision')}")
    for row in branch.get('candidates', [])[:6]:
        data_lines.append(f"{row.get('name')} | symbol={str(row.get('symbol','NA')).upper()} | trades={row.get('base_trades')} | pf={_num(row.get('base_pf'))} | ret={_pct(row.get('base_ret'))} | maxdd={_pct_abs(row.get('base_maxdd'))}")
    data_lines.append("")
    data_lines.append("【给 DeepSeek 的问题】")
    for q in summary['questions_for_deepseek']:
        data_lines.append(f"- {q}")
    data_text = "\n".join(data_lines) + "\n"

    report_path = downloads / "deepseek_strategy_report_latest.txt"
    data_txt_path = downloads / "deepseek_strategy_data_latest.txt"
    data_json_path = downloads / "deepseek_strategy_data_latest.json"
    report_path.write_text(report_text, encoding="utf-8")
    data_txt_path.write_text(data_text, encoding="utf-8")
    data_json_path.write_text(data_json_text, encoding="utf-8")

    print(report_text)
    print(f"[ok] wrote {report_path}")
    print(f"[ok] wrote {data_txt_path}")
    print(f"[ok] wrote {data_json_path}")


if __name__ == "__main__":
    main()
