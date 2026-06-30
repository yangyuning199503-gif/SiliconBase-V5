from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
    except Exception:
        return default
    if math.isnan(v):
        return default
    return v


def _pct(x: Any) -> str:
    try:
        return f"{float(x) * 100:.2f}%"
    except Exception:
        return "NA"


def _num(x: Any, nd: int = 3) -> str:
    try:
        return f"{float(x):.{nd}f}"
    except Exception:
        return "NA"


def _find_line(txt: str, prefix: str) -> str:
    for line in txt.splitlines():
        if prefix in line:
            return line.strip()
    return ""


def _parse_okx_report(path: Path) -> dict[str, str]:
    txt = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
    data: dict[str, str] = {}
    keys = [
        "- 当前状态:",
        "- 状态原因:",
        "- 当前版本:",
        "- 最近影子执行成功:",
        "- 策略真实成交已开始:",
        "- 当前候选:",
        "- 评估结论:",
        "- 触发原因:",
        "- 当前模式:",
        "- 执行方式:",
    ]
    for k in keys:
        hit = _find_line(txt, k)
        if hit:
            data[k] = hit.split(k, 1)[1].strip()
    m = re.search(r"- 下一轮执行\(UTC\+8\):\s*(.+)", txt)
    if m:
        data["next_bar"] = m.group(1).strip()
    return data


def _candidate_line(name: str, row: dict[str, Any], live: dict[str, Any]) -> str:
    r_tr = int(row.get("recent_trades", 0) or 0)
    l_tr = int(live.get("recent_trades", 0) or 0)
    r_pf = _safe_float(row.get("recent_pf"))
    l_pf = _safe_float(live.get("recent_pf"))
    wf_pf = _safe_float(row.get("wf_pf"))
    return (
        f"- {name}: {row.get('name','-')} | 近2年 收益={_pct(row.get('recent_ret'))} PF={_num(r_pf)} 交易={r_tr}"
        f" | WF 收益={_pct(row.get('wf_ret'))} PF={_num(wf_pf)} 交易={int(row.get('wf_trades',0) or 0)}"
        f" | 相比 live 交易差={r_tr - l_tr:+d} PF差={r_pf - l_pf:+.3f}"
    )


def _readiness(row: dict[str, Any], live: dict[str, Any], mode: str) -> dict[str, Any]:
    recent_trades_gain = int(row.get("recent_trades", 0) or 0) - int(live.get("recent_trades", 0) or 0)
    recent_pf = _safe_float(row.get("recent_pf"))
    live_pf = _safe_float(live.get("recent_pf"))
    wf_pf = _safe_float(row.get("wf_pf"))
    recent_ret = _safe_float(row.get("recent_ret"))
    wf_ret = _safe_float(row.get("wf_ret"))
    if mode == "balanced":
        ready = recent_trades_gain >= 20 and recent_pf >= live_pf - 0.25 and wf_pf >= 1.70 and recent_ret > 0 and wf_ret > 0
    else:
        ready = recent_trades_gain >= 35 and recent_pf >= 2.10 and wf_pf >= 1.60 and recent_ret > 0 and wf_ret > 0
    return {
        "ready": ready,
        "recent_trades_gain": recent_trades_gain,
        "recent_pf_gap": recent_pf - live_pf,
        "wf_pf": wf_pf,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage99 主线提频聚焦")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    raw = root / "reports" / "research_raw"
    raw.mkdir(parents=True, exist_ok=True)

    p93 = raw / "stage93_frequency_accel_latest.json"
    if not p93.exists():
        raise SystemExit("缺少 stage93_frequency_accel_latest.json，请先生成 stage93 输出。")

    payload = _load_json(p93)
    mainline = payload.get("mainline") if isinstance(payload.get("mainline"), dict) else {}
    live = mainline.get("live") if isinstance(mainline.get("live"), dict) else {}
    balanced = mainline.get("balanced") if isinstance(mainline.get("balanced"), dict) else {}
    aggressive = mainline.get("aggressive") if isinstance(mainline.get("aggressive"), dict) else {}
    if not live:
        raise SystemExit("stage93 主线结果为空。")

    okx = _parse_okx_report(Path.home() / "Downloads" / "okx_demo_report_latest.txt")
    b_ready = _readiness(balanced, live, "balanced") if balanced else {"ready": False}
    a_ready = _readiness(aggressive, live, "aggressive") if aggressive else {"ready": False}

    lines: list[str] = []
    lines.append("Stage99 主线提频聚焦")
    lines.append("原则：先激进扩机会，再保守收口；6年只作软约束，判断以近2年 + WF 为主。")
    lines.append("")
    lines.append(f"generated_at_utc={datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append("")
    lines.append("=== 当前主线运行态 ===")
    lines.append(f"- current_status={okx.get('- 当前状态:','-')} | reason={okx.get('- 状态原因:','-')} | next={okx.get('next_bar','-')}")
    lines.append(f"- runtime_candidate={okx.get('- 当前候选:','-')} | runtime_version={okx.get('- 当前版本:','-')}")
    lines.append(f"- risk_mode={okx.get('- 当前模式:','-')} | exec_mode={okx.get('- 执行方式:','-')} | live_fill_started={okx.get('- 策略真实成交已开始:','-')}")
    trig = okx.get('- 触发原因:','')
    if trig:
        lines.append(f"- current_risk_trigger={trig}")
    lines.append("")
    lines.append("=== 当前 shortlist ===")
    lines.append(_candidate_line("live_keep", live, live))
    if balanced:
        lines.append(_candidate_line("shadow_balanced", balanced, live))
    if aggressive:
        lines.append(_candidate_line("shadow_aggressive", aggressive, live))
    lines.append("")
    lines.append("=== readiness ===")
    if balanced:
        lines.append(
            f"- balanced_ready={'yes' if b_ready['ready'] else 'no'} | trade_gain={b_ready['recent_trades_gain']:+d} | recent_pf_gap={b_ready['recent_pf_gap']:+.3f} | wf_pf={_num(b_ready['wf_pf'])}"
        )
    if aggressive:
        lines.append(
            f"- aggressive_ready={'yes' if a_ready['ready'] else 'no'} | trade_gain={a_ready['recent_trades_gain']:+d} | recent_pf_gap={a_ready['recent_pf_gap']:+.3f} | wf_pf={_num(a_ready['wf_pf'])}"
        )
    lines.append("")
    lines.append("=== 当前动作 ===")
    lines.append(f"- keep live: {live.get('name','mainline_live_base')}")
    if balanced:
        lines.append(f"- promote_order_1: {balanced.get('name','-')}  （先作为主线提频首选）")
    if aggressive:
        lines.append(f"- promote_order_2: {aggressive.get('name','-')}  （更激进，只做第二顺位）")
    lines.append("- geo/event regime: 不靠单纯放松阈值提频；优先放宽结构入场，再用事件/拥挤/流动性二次确认。")
    lines.append("- 如果 war / 宏观冲击持续，优先观察 1h 结构突破后的 15m 延续，而不是无条件追单。")

    out_txt = raw / "stage99_mainline_frequency_push_latest.txt"
    out_json = raw / "stage99_mainline_frequency_push_latest.json"
    out_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    out_json.write_text(json.dumps({
        "mainline": mainline,
        "okx_runtime": okx,
        "balanced_readiness": b_ready,
        "aggressive_readiness": a_ready,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    runtime_dir = root / ".runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    if balanced:
        (runtime_dir / "mainline_shadow_balanced_candidate.txt").write_text(str(balanced.get("name","")) + "\n", encoding="utf-8")
    if aggressive:
        (runtime_dir / "mainline_shadow_aggressive_candidate.txt").write_text(str(aggressive.get("name","")) + "\n", encoding="utf-8")

    print(out_txt)
    print(out_json)


if __name__ == "__main__":
    main()
