from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest.io import read_config

from tools import stage217_multiregime_broadfront_frontier as s217
from tools import stage218_candidate_truth_sync_frontier as s218

# Stage219：用 stage91 文本摘要锁真值，避免 stage217/stage218 继续被 JSON gate 明细漂移带偏。
FULL_RET_TOL = 0.10
RECENT_RET_TOL = 0.12
RECENT_PF_TOL = 1.60
RECENT_TRADES_TOL = 45

ASSET_KEEP = {
    "eth": {"long": 3, "short": 2, "dual": 1},
    "btc": {"long": 2, "short": 2, "dual": 1},
    "sol": {"long": 2, "short": 2, "dual": 1},
}

CANDIDATE_RE = re.compile(
    r"^- (?P<asset>[A-Z]+) \| (?P<leg>long|short|dual) \| (?P<name>[^:]+): dominant_gate=(?P<gate>[^ ]+) \((?P<decision>[^)]+)\) "
    r"\| 6年 收益=(?P<full_ret>[-+]?\d+(?:\.\d+)?)% 月化=(?P<full_month>[-+]?\d+(?:\.\d+)?)% 回撤=(?P<full_dd>[-+]?\d+(?:\.\d+)?)% 交易=(?P<full_trades>\d+) PF=(?P<full_pf>[-+]?\d+(?:\.\d+)?) "
    r"\| 近2年 收益=(?P<recent_ret>[-+]?\d+(?:\.\d+)?)% 月化=(?P<recent_month>[-+]?\d+(?:\.\d+)?)% 回撤=(?P<recent_dd>[-+]?\d+(?:\.\d+)?)% 交易=(?P<recent_trades>\d+) PF=(?P<recent_pf>[-+]?\d+(?:\.\d+)?) "
    r"\| WF样本外 收益=(?P<wf_ret>[-+]?\d+(?:\.\d+)?)% 月化=(?P<wf_month>[-+]?\d+(?:\.\d+)?)% 回撤=(?P<wf_dd>[-+]?\d+(?:\.\d+)?)% 交易=(?P<wf_trades>\d+) PF=(?P<wf_pf>[-+]?\d+(?:\.\d+)?) "
    r"\| 正收益折=(?P<pos>\d+)/(?P<folds>\d+) \| alpha_score=(?P<alpha>[-+]?\d+(?:\.\d+)?)$"
)

ASSET_SUMMARY_RE = re.compile(
    r"^- (?P<asset>[A-Z]+): mode=(?P<mode>[^ ]+) \| active=(?P<active>[^ ]+) \| 近2年 PF=(?P<recent_pf>[-+]?\d+(?:\.\d+)?) 收益=(?P<recent_ret>[-+]?\d+(?:\.\d+)?)% 交易=(?P<recent_trades>\d+) "
    r"\| WF PF=(?P<wf_pf>[-+]?\d+(?:\.\d+)?) 收益=(?P<wf_ret>[-+]?\d+(?:\.\d+)?)% 回撤=(?P<wf_dd>[-+]?\d+(?:\.\d+)?)%$"
)

ASSET_BEST_RE = re.compile(
    r"^  long_best=(?P<long_best>[^ ]+) \| short_best=(?P<short_best>[^ ]+) \| dual_best=(?P<dual_best>[^ ]+) \| note=(?P<note>.*)$"
)


def _pct(v: str) -> float:
    return float(v) / 100.0


def _parse_stage91_txt(path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    if not path.exists():
        raise FileNotFoundError(f"missing {path}")
    text = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    by_name: dict[str, dict[str, Any]] = {}
    asset_summary: dict[str, dict[str, Any]] = {}
    in_asset_summary = False
    pending_asset: str | None = None
    for raw in text:
        line = raw.rstrip("\n")
        m = CANDIDATE_RE.match(line)
        if m:
            gd = m.groupdict()
            name = gd["name"]
            by_name[name] = {
                "asset": gd["asset"].lower(),
                "leg": gd["leg"],
                "name": name,
                "dominant_gate": gd["gate"],
                "decision": gd["decision"],
                "alpha_score": float(gd["alpha"]),
                "full": {
                    "ret": _pct(gd["full_ret"]),
                    "monthlyized": _pct(gd["full_month"]),
                    "dd": _pct(gd["full_dd"]),
                    "trades": int(gd["full_trades"]),
                    "pf": float(gd["full_pf"]),
                },
                "recent2y": {
                    "ret": _pct(gd["recent_ret"]),
                    "monthlyized": _pct(gd["recent_month"]),
                    "dd": _pct(gd["recent_dd"]),
                    "trades": int(gd["recent_trades"]),
                    "pf": float(gd["recent_pf"]),
                },
                "wf": {
                    "ret": _pct(gd["wf_ret"]),
                    "monthlyized": _pct(gd["wf_month"]),
                    "dd": _pct(gd["wf_dd"]),
                    "trades": int(gd["wf_trades"]),
                    "pf": float(gd["wf_pf"]),
                    "positive_folds": int(gd["pos"]),
                    "total_folds": int(gd["folds"]),
                },
            }
            continue
        if line.startswith("=== 资产一体腿建议 ==="):
            in_asset_summary = True
            continue
        if not in_asset_summary:
            continue
        m = ASSET_SUMMARY_RE.match(line)
        if m:
            gd = m.groupdict()
            asset = gd["asset"].lower()
            asset_summary[asset] = {
                "asset": asset,
                "mode": gd["mode"],
                "active": gd["active"],
                "recent2y": {
                    "ret": _pct(gd["recent_ret"]),
                    "trades": int(gd["recent_trades"]),
                    "pf": float(gd["recent_pf"]),
                },
                "wf": {
                    "ret": _pct(gd["wf_ret"]),
                    "dd": _pct(gd["wf_dd"]),
                    "pf": float(gd["wf_pf"]),
                },
            }
            pending_asset = asset
            continue
        m = ASSET_BEST_RE.match(line)
        if m and pending_asset:
            gd = m.groupdict()
            asset_summary[pending_asset].update(gd)
            pending_asset = None
            continue
    return by_name, asset_summary


def _text_truth(name: str, truth_by_name: dict[str, dict[str, Any]], fallback: dict[str, Any]) -> dict[str, Any]:
    base = truth_by_name.get(name)
    if not base:
        return fallback
    return {
        "full": dict(base["full"]),
        "recent2y": dict(base["recent2y"]),
        "wf": dict(base["wf"]),
    }


def _sync_eval(truth: dict[str, Any], rebuilt: dict[str, Any]) -> dict[str, Any]:
    full_ret_diff = float(rebuilt["full"]["ret"] - truth["full"]["ret"])
    recent_ret_diff = float(rebuilt["recent2y"]["ret"] - truth["recent2y"]["ret"])
    recent_pf_diff = float(rebuilt["recent2y"]["pf"] - truth["recent2y"]["pf"])
    recent_trades_diff = int(rebuilt["recent2y"]["trades"] - truth["recent2y"]["trades"])
    ok = (
        abs(full_ret_diff) <= FULL_RET_TOL
        and abs(recent_ret_diff) <= RECENT_RET_TOL
        and abs(recent_pf_diff) <= RECENT_PF_TOL
        and abs(recent_trades_diff) <= RECENT_TRADES_TOL
    )
    return {
        "ok": bool(ok),
        "full_ret_diff": full_ret_diff,
        "recent_ret_diff": recent_ret_diff,
        "recent_pf_diff": recent_pf_diff,
        "recent_trades_diff": int(recent_trades_diff),
    }


def _clip_pf(x: float, cap: float) -> float:
    return min(max(float(x), 0.0), cap)


def _truth_score(row: dict[str, Any], truth: dict[str, Any]) -> float:
    leg = s217._infer_leg(row)
    recent = truth["recent2y"]
    wf = truth["wf"]
    full = truth["full"]
    score = (
        1.55 * float(recent.get("monthlyized", 0.0) or 0.0)
        + 1.20 * float(wf.get("monthlyized", 0.0) or 0.0)
        + 0.08 * _clip_pf(recent.get("pf", 0.0), 8.0)
        + 0.05 * _clip_pf(wf.get("pf", 0.0), 8.0)
        + 0.02 * _clip_pf(full.get("pf", 0.0), 4.0)
        - 0.015 * abs(float(recent.get("dd", 0.0) or 0.0))
        - 0.010 * abs(float(wf.get("dd", 0.0) or 0.0))
        + 0.002 * min(int(recent.get("trades", 0) or 0), 40) / 40.0
    )
    if leg == "dual":
        score += 0.010
    if leg == "short":
        score += 0.006
    return float(score)


def _fmt_pct(x: float) -> str:
    return f"{float(x) * 100:.2f}%"


def _parse_mainline_report(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    out: dict[str, Any] = {}
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if line.startswith("- 当前候选:"):
            out["active"] = line.split(":", 1)[1].strip()
        elif line.startswith("- 6年总样本:"):
            out["full_line"] = line
        elif line.startswith("- 近2年样本:"):
            out["recent_line"] = line
        elif line.startswith("- WF样本外:"):
            out["wf_line"] = line
    return out


def _rank_asset_rows(rows: list[dict[str, Any]], asset: str, leg: str, keep: int) -> list[dict[str, Any]]:
    bag = [r for r in rows if str(r.get("symbol", "")).lower() == asset and s217._infer_leg(r) == leg]
    bag.sort(key=lambda r: (float(r.get("truth_score", 0.0)), float(r.get("truth_locked", {}).get("recent2y", {}).get("monthlyized", 0.0))), reverse=True)
    return bag[:keep]


def run(project_dir: Path, out_txt: Path, out_json: Path) -> None:
    cfg = read_config(project_dir / "config.yml")
    initial_equity = float(cfg.get("portfolio", {}).get("initial_equity", 100000.0))
    stage91_json = s217._load_stage91(project_dir)
    selected = s217._pick_rows(stage91_json)

    stage91_txt = project_dir / "reports" / "research_raw" / "stage91_branch_event_alpha_matrix_latest.txt"
    truth_by_name, asset_summary = _parse_stage91_txt(stage91_txt)

    audits: list[dict[str, Any]] = []
    pass_rows: list[dict[str, Any]] = []
    fail_rows: list[dict[str, Any]] = []

    for row in selected:
        name = str(row.get("name", ""))
        json_truth = s218._truth_metrics(row)
        truth = _text_truth(name, truth_by_name, json_truth)
        rebuilt = s218._rebuild_baseline(project_dir, row, initial_equity)
        sync = _sync_eval(truth, rebuilt)
        score = _truth_score(row, truth)
        row["truth_locked"] = truth
        row["truth_score"] = score
        row["truth_sync_ok"] = sync["ok"]
        audits.append({
            "candidate": row,
            "truth": truth,
            "rebuilt": rebuilt,
            "truth_sync": sync,
            "truth_score": score,
        })
        if sync["ok"]:
            pass_rows.append(row)
        else:
            fail_rows.append(row)

    audits.sort(key=lambda a: (a["truth_score"], a["truth"]["recent2y"]["monthlyized"], a["truth"]["wf"]["monthlyized"]), reverse=True)

    seed_plan: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for asset, leg_keep in ASSET_KEEP.items():
        seed_plan[asset] = {"pass": [], "pending_resync": []}
        for leg, keep in leg_keep.items():
            seed_plan[asset]["pass"].extend(_rank_asset_rows(pass_rows, asset, leg, keep))
            seed_plan[asset]["pending_resync"].extend(_rank_asset_rows(fail_rows, asset, leg, keep))

    mainline_report = _parse_mainline_report(Path.home() / "Downloads" / "okx_demo_report_latest.txt")

    lines: list[str] = []
    lines.append("Stage219 truth-locked seed frontier")
    lines.append("")
    lines.append("[core_rule]")
    lines.append("- stage218 之后，先用 stage91 文本摘要锁真值，再评估重建 trades。")
    lines.append("- 6年必报，但排序先看近2年 + WF；当前只修口径，不动 demo，不动 entry。")
    lines.append("- sync FAIL 的候选不删除，只标记 pending_resync，防止误砍路径。")
    lines.append("")
    if mainline_report:
        lines.append("[mainline_runtime]")
        lines.append(f"- active={mainline_report.get('active','-')}")
        if mainline_report.get("full_line"):
            lines.append(mainline_report["full_line"])
        if mainline_report.get("recent_line"):
            lines.append(mainline_report["recent_line"])
        if mainline_report.get("wf_line"):
            lines.append(mainline_report["wf_line"])
        lines.append("")

    lines.append("[truth_locked_sync_audit]")
    for audit in audits:
        row = audit["candidate"]
        truth = audit["truth"]
        rebuilt = audit["rebuilt"]
        sync = audit["truth_sync"]
        lines.append(
            f"- {str(row.get('symbol','')).upper()} | leg={s217._infer_leg(row)} | {row.get('name','')} | sync={'PASS' if sync['ok'] else 'FAIL'} | 6年={_fmt_pct(truth['full']['ret'])} PF={truth['full']['pf']:.3f} | 近2年={_fmt_pct(truth['recent2y']['ret'])} 月化={_fmt_pct(truth['recent2y']['monthlyized'])} PF={truth['recent2y']['pf']:.3f} 交易={truth['recent2y']['trades']} | WF={_fmt_pct(truth['wf']['ret'])} 月化={_fmt_pct(truth['wf']['monthlyized'])} PF={truth['wf']['pf']:.3f} | rebuilt_2y={_fmt_pct(rebuilt['recent2y']['ret'])} PF={rebuilt['recent2y']['pf']:.3f} | diff_2y={_fmt_pct(sync['recent_ret_diff'])} diff_pf={sync['recent_pf_diff']:+.3f} | score={audit['truth_score']:+.4f}"
        )
    lines.append("")

    lines.append("[asset_runtime_freeze]")
    for asset in ["btc", "eth", "sol"]:
        item = asset_summary.get(asset, {})
        if not item:
            continue
        lines.append(
            f"- {asset.upper()}: mode={item.get('mode','-')} | active={item.get('active','-')} | long_best={item.get('long_best','-')} | short_best={item.get('short_best','-')} | dual_best={item.get('dual_best','-')}"
        )
    lines.append("")

    lines.append("[truth_locked_seed_plan]")
    for asset in ["eth", "btc", "sol"]:
        lines.append(f"- {asset.upper()}")
        for row in seed_plan[asset]["pass"]:
            truth = row.get("truth_locked", {})
            lines.append(
                f"  - PASS | {s217._infer_leg(row)} | {row.get('name','')} | 6年={_fmt_pct(truth['full']['ret'])} | 近2年={_fmt_pct(truth['recent2y']['ret'])} 月化={_fmt_pct(truth['recent2y']['monthlyized'])} PF={truth['recent2y']['pf']:.3f} | WF={_fmt_pct(truth['wf']['ret'])} 月化={_fmt_pct(truth['wf']['monthlyized'])} PF={truth['wf']['pf']:.3f}"
            )
        for row in seed_plan[asset]["pending_resync"]:
            truth = row.get("truth_locked", {})
            lines.append(
                f"  - PENDING_RESYNC | {s217._infer_leg(row)} | {row.get('name','')} | 6年={_fmt_pct(truth['full']['ret'])} | 近2年={_fmt_pct(truth['recent2y']['ret'])} 月化={_fmt_pct(truth['recent2y']['monthlyized'])} PF={truth['recent2y']['pf']:.3f} | WF={_fmt_pct(truth['wf']['ret'])} 月化={_fmt_pct(truth['wf']['monthlyized'])} PF={truth['wf']['pf']:.3f}"
            )
    lines.append("")

    lines.append("[conclusion]")
    lines.append(f"- truth_locked_sync: pass={len(pass_rows)} fail={len(fail_rows)}")
    lines.append("- ETH 主簇继续扩，但以 hold/reclaim 主簇为先；BTC/SOL 先保路，不砍。")
    lines.append("- 这轮不切 runtime，不拿 sync FAIL 候选做排名决策。")
    lines.append("- 下一步应该在 truth_locked 基础上重跑 broadfront，而不是继续直接信 stage217 排序。")

    payload = {
        "pass_count": len(pass_rows),
        "fail_count": len(fail_rows),
        "audits": [
            {
                "name": a["candidate"].get("name"),
                "symbol": a["candidate"].get("symbol"),
                "leg": s217._infer_leg(a["candidate"]),
                "truth_sync_ok": a["truth_sync"]["ok"],
                "truth_score": a["truth_score"],
                "truth_locked": a["truth"],
                "rebuilt": a["rebuilt"],
                "truth_sync": a["truth_sync"],
            }
            for a in audits
        ],
        "asset_runtime_freeze": asset_summary,
        "seed_plan": {
            asset: {
                "pass": [r.get("name") for r in seed_plan[asset]["pass"]],
                "pending_resync": [r.get("name") for r in seed_plan[asset]["pending_resync"]],
            }
            for asset in seed_plan
        },
    }

    out_txt.parent.mkdir(parents=True, exist_ok=True)
    out_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-dir", required=True)
    ap.add_argument("--out-txt", required=True)
    ap.add_argument("--out-json", required=True)
    args = ap.parse_args()
    run(Path(args.project_dir).expanduser().resolve(), Path(args.out_txt).expanduser().resolve(), Path(args.out_json).expanduser().resolve())


if __name__ == "__main__":
    main()
