from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest.io import read_config

from tools import stage217_multiregime_broadfront_frontier as s217
from tools import stage218_candidate_truth_sync_frontier as s218
from tools import stage219_truth_locked_seed_frontier as s219

ASSETS = ["btc", "eth", "sol"]
ASSET_WEIGHTS = s217.ASSET_WEIGHTS
ASSET_KEEP = s219.ASSET_KEEP


def _rank_asset_rows(rows: list[dict[str, Any]], asset: str, leg: str, keep: int) -> list[dict[str, Any]]:
    bag = [r for r in rows if str(r.get("symbol", "")).lower() == asset and s217._infer_leg(r) == leg]
    bag.sort(
        key=lambda r: (
            float(r.get("truth_score", 0.0)),
            float(r.get("truth_locked", {}).get("recent2y", {}).get("monthlyized", 0.0)),
            float(r.get("truth_locked", {}).get("wf", {}).get("monthlyized", 0.0)),
        ),
        reverse=True,
    )
    return bag[:keep]


def _dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        name = str(row.get("name", ""))
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(row)
    return out


def _build_truth_locked_seeds(project_dir: Path, initial_equity: float) -> dict[str, Any]:
    stage91_json = s217._load_stage91(project_dir)
    selected = s217._pick_rows(stage91_json)
    stage91_txt = project_dir / "reports" / "research_raw" / "stage91_branch_event_alpha_matrix_latest.txt"
    truth_by_name, asset_summary = s219._parse_stage91_txt(stage91_txt)

    audits: list[dict[str, Any]] = []
    pass_rows: list[dict[str, Any]] = []
    fail_rows: list[dict[str, Any]] = []

    for raw_row in selected:
        row = copy.deepcopy(raw_row)
        name = str(row.get("name", ""))
        json_truth = s218._truth_metrics(row)
        truth = s219._text_truth(name, truth_by_name, json_truth)
        rebuilt = s218._rebuild_baseline(project_dir, row, initial_equity)
        sync = s219._sync_eval(truth, rebuilt)
        score = s219._truth_score(row, truth)
        row["truth_locked"] = truth
        row["truth_score"] = score
        row["truth_sync_ok"] = bool(sync["ok"])
        audits.append(
            {
                "candidate": row,
                "truth": truth,
                "rebuilt": rebuilt,
                "truth_sync": sync,
                "truth_score": score,
            }
        )
        if sync["ok"]:
            pass_rows.append(row)
        else:
            fail_rows.append(row)

    audits.sort(
        key=lambda a: (
            float(a["truth_score"]),
            float(a["truth"]["recent2y"].get("monthlyized", 0.0)),
            float(a["truth"]["wf"].get("monthlyized", 0.0)),
        ),
        reverse=True,
    )

    seed_plan: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for asset, leg_keep in ASSET_KEEP.items():
        seed_plan[asset] = {"pass": [], "pending_resync": []}
        for leg, keep in leg_keep.items():
            seed_plan[asset]["pass"].extend(_rank_asset_rows(pass_rows, asset, leg, keep))
            seed_plan[asset]["pending_resync"].extend(_rank_asset_rows(fail_rows, asset, leg, keep))
        seed_plan[asset]["pass"] = _dedupe_rows(seed_plan[asset]["pass"])
        seed_plan[asset]["pending_resync"] = _dedupe_rows(seed_plan[asset]["pending_resync"])

    all_rows: list[dict[str, Any]] = []
    pass_seed_rows: list[dict[str, Any]] = []
    pending_seed_rows: list[dict[str, Any]] = []
    for asset in ASSETS:
        pass_seed_rows.extend(seed_plan.get(asset, {}).get("pass", []))
        pending_seed_rows.extend(seed_plan.get(asset, {}).get("pending_resync", []))
        all_rows.extend(seed_plan.get(asset, {}).get("pass", []))
        all_rows.extend(seed_plan.get(asset, {}).get("pending_resync", []))
    all_rows = _dedupe_rows(all_rows)
    pass_seed_rows = _dedupe_rows(pass_seed_rows)
    pending_seed_rows = _dedupe_rows(pending_seed_rows)

    return {
        "audits": audits,
        "asset_summary": asset_summary,
        "all_rows": all_rows,
        "pass_rows": pass_seed_rows,
        "pending_rows": pending_seed_rows,
        "seed_plan": seed_plan,
    }


def _candidate_weight_map(rows: list[dict[str, Any]]) -> dict[str, float]:
    per_asset_count: dict[str, int] = {}
    for row in rows:
        sym = str(row.get("symbol", "")).lower()
        per_asset_count[sym] = per_asset_count.get(sym, 0) + 1
    weights: dict[str, float] = {}
    for row in rows:
        name = str(row.get("name", ""))
        sym = str(row.get("symbol", "")).lower()
        denom = max(per_asset_count.get(sym, 1), 1)
        weights[name] = float(ASSET_WEIGHTS.get(sym, 0.0)) / float(denom)
    return weights


def _aggregate_variants(rows: list[dict[str, Any]], candidate_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    row_names = {str(r.get("name", "")) for r in rows}
    if not row_names:
        return []
    weights = _candidate_weight_map(rows)
    aggregate_rows: dict[str, dict[str, Any]] = {}
    for cr in candidate_results:
        row = cr.get("candidate", {}) or {}
        row_name = str(row.get("name", ""))
        if row_name not in row_names:
            continue
        sym = str(row.get("symbol", "")).lower()
        candidate_weight = float(weights.get(row_name, 0.0))
        for vr in cr.get("variants", []):
            bucket = aggregate_rows.setdefault(
                str(vr["name"]),
                {
                    "name": vr["name"],
                    "weighted_score": 0.0,
                    "weighted_recent_monthly": 0.0,
                    "weighted_recent_ret": 0.0,
                    "weighted_recent_pf": 0.0,
                    "weighted_full_ret": 0.0,
                    "weighted_full_pf": 0.0,
                    "weighted_wf_pnl_delta": 0.0,
                    "weighted_retain": 0.0,
                    "weighted_recent_trades": 0.0,
                    "weighted_positive_folds": 0.0,
                    "weighted_sample_penalty": 0.0,
                    "weighted_negative_recent": 0.0,
                    "weighted_negative_full": 0.0,
                    "members": [],
                },
            )
            gm_full = vr["gated_metrics_full"]
            gm_r2 = vr["gated_metrics_recent2y"]
            wf = vr["wf"]
            bucket["weighted_score"] += candidate_weight * float(vr.get("composite_score", 0.0))
            bucket["weighted_recent_monthly"] += candidate_weight * float(gm_r2.get("monthlyized", 0.0))
            bucket["weighted_recent_ret"] += candidate_weight * float(gm_r2.get("total_return", 0.0))
            bucket["weighted_recent_pf"] += candidate_weight * float(vr.get("recent_pf_capped", 0.0))
            bucket["weighted_full_ret"] += candidate_weight * float(gm_full.get("total_return", 0.0))
            bucket["weighted_full_pf"] += candidate_weight * float(vr.get("full_pf_capped", 0.0))
            bucket["weighted_wf_pnl_delta"] += candidate_weight * float(wf.get("aggregate_pnl_delta", 0.0))
            bucket["weighted_retain"] += candidate_weight * float(vr.get("retain_clipped", 1.0))
            bucket["weighted_recent_trades"] += candidate_weight * float(gm_r2.get("trades", 0.0) or 0.0)
            bucket["weighted_positive_folds"] += candidate_weight * float(wf.get("positive_folds", 0.0) or 0.0)
            bucket["weighted_sample_penalty"] += candidate_weight * float(vr.get("sample_penalty", 0.0))
            if float(gm_r2.get("total_return", 0.0)) < 0:
                bucket["weighted_negative_recent"] += candidate_weight
            if float(gm_full.get("total_return", 0.0)) < 0:
                bucket["weighted_negative_full"] += candidate_weight
            bucket["members"].append(
                {
                    "symbol": sym,
                    "candidate": row_name,
                    "leg": s217._infer_leg(row),
                    "truth_sync": "PASS" if bool(row.get("truth_sync_ok", False)) else "PENDING_RESYNC",
                }
            )
    leaderboard = sorted(
        aggregate_rows.values(),
        key=lambda x: (
            float(x.get("weighted_score", 0.0)),
            float(x.get("weighted_recent_monthly", 0.0)),
            float(x.get("weighted_recent_ret", 0.0)),
            -float(x.get("weighted_negative_recent", 0.0)),
        ),
        reverse=True,
    )
    return leaderboard


def _recommend_variant(leaderboard: list[dict[str, Any]]) -> dict[str, Any] | None:
    for v in leaderboard:
        if (
            float(v.get("weighted_recent_ret", 0.0)) > 0
            and float(v.get("weighted_recent_pf", 0.0)) >= 1.05
            and float(v.get("weighted_wf_pnl_delta", 0.0)) >= 0.0
            and float(v.get("weighted_negative_recent", 0.0)) <= 0.40
        ):
            return v
    return None


def _fmt_pct(x: float) -> str:
    return f"{float(x) * 100:.2f}%"


def _fmt_num(x: float) -> str:
    return f"{float(x):+.2f}"


def _parse_report_summary(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
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


def run(project_dir: Path, out_txt: Path, out_json: Path) -> None:
    cfg = read_config(project_dir / "config.yml")
    initial_equity = float(cfg.get("portfolio", {}).get("initial_equity", 100000.0))
    truth_locked = _build_truth_locked_seeds(project_dir, initial_equity)

    hist = s217.msb._load_or_fetch_history(project_dir, refresh=False)
    candidate_results = [s217._candidate_eval(project_dir, row, hist, initial_equity) for row in truth_locked["all_rows"]]

    pass_leaderboard = _aggregate_variants(truth_locked["pass_rows"], candidate_results)
    all_leaderboard = _aggregate_variants(truth_locked["all_rows"], candidate_results)
    pass_recommended = _recommend_variant(pass_leaderboard)
    all_recommended = _recommend_variant(all_leaderboard)

    main_report = _parse_report_summary(project_dir / "reports" / "research_raw" / "okx_demo_report_latest.txt")
    if not main_report:
        main_report = _parse_report_summary(Path.home() / "Downloads" / "okx_demo_report_latest.txt")

    lines: list[str] = []
    lines.append("Stage223 truth-locked broadfront frontier")
    lines.append("")
    lines.append("[mainline_runtime]")
    lines.append(f"- active={main_report.get('active','mainline_live_dynlev_fix8_lock18')}")
    if main_report.get("full_line"):
        lines.append(main_report["full_line"])
    if main_report.get("recent_line"):
        lines.append(main_report["recent_line"])
    if main_report.get("wf_line"):
        lines.append(main_report["wf_line"])
    lines.append("")
    lines.append("[truth_locked_sync]")
    lines.append(f"- pass={len(truth_locked['pass_rows'])} | pending_resync={len(truth_locked['pending_rows'])}")
    lines.append("- 规则：6年必报，但排序仍先看近2年 + WF；sync FAIL 不删路，只留 research。")
    lines.append("")
    lines.append("[seed_plan]")
    for asset in ["eth", "btc", "sol"]:
        lines.append(f"- {asset.upper()}")
        for tag in ["pass", "pending_resync"]:
            bag = truth_locked["seed_plan"].get(asset, {}).get(tag, [])
            if not bag:
                lines.append(f"  - {tag}: none")
                continue
            for row in bag:
                truth = row.get("truth_locked", {})
                recent = truth.get("recent2y", {})
                wf = truth.get("wf", {})
                lines.append(
                    f"  - {tag.upper()} | {s217._infer_leg(row)} | {row.get('name','')} | 近2年={_fmt_pct(recent.get('ret',0.0))} 月化={_fmt_pct(recent.get('monthlyized',0.0))} PF={float(recent.get('pf',0.0)):.3f} | WF={_fmt_pct(wf.get('ret',0.0))} 月化={_fmt_pct(wf.get('monthlyized',0.0))} PF={float(wf.get('pf',0.0)):.3f}")
        lines.append("")
    lines.append("[top_variant_by_seed]")
    for cr in candidate_results:
        row = cr.get("candidate", {}) or {}
        best = cr.get("best")
        truth = row.get("truth_locked", {}) or {}
        recent_truth = truth.get("recent2y", {})
        wf_truth = truth.get("wf", {})
        if not best:
            lines.append(f"- {row.get('name','')} | no_result")
            continue
        gm_full = best["gated_metrics_full"]
        gm_r2 = best["gated_metrics_recent2y"]
        wf = best["wf"]
        sync_tag = "PASS" if bool(row.get("truth_sync_ok", False)) else "PENDING_RESYNC"
        lines.append(
            f"- {str(row.get('symbol','')).upper()} | {sync_tag} | leg={s217._infer_leg(row)} | {row.get('name','')} | best={best['name']} | 6年={_fmt_pct(gm_full.get('total_return',0.0))} 月化={_fmt_pct(gm_full.get('monthlyized',0.0))} PF={float(gm_full.get('profit_factor',0.0)):.3f} | 近2年={_fmt_pct(gm_r2.get('total_return',0.0))} 月化={_fmt_pct(gm_r2.get('monthlyized',0.0))} PF={float(gm_r2.get('profit_factor',0.0)):.3f} | WF代理={_fmt_num(wf.get('aggregate_pnl_delta',0.0))}"
        )
        lines.append(
            f"  truth_locked: 近2年={_fmt_pct(recent_truth.get('ret',0.0))} 月化={_fmt_pct(recent_truth.get('monthlyized',0.0))} PF={float(recent_truth.get('pf',0.0)):.3f} | WF={_fmt_pct(wf_truth.get('ret',0.0))} 月化={_fmt_pct(wf_truth.get('monthlyized',0.0))} PF={float(wf_truth.get('pf',0.0)):.3f}"
        )
    lines.append("")
    lines.append("[pass_only_variant_leaderboard]")
    if pass_leaderboard:
        for v in pass_leaderboard[:6]:
            lines.append(
                f"- {v['name']} | weighted_2y_month={_fmt_pct(v['weighted_recent_monthly'])} weighted_2y_ret={_fmt_pct(v['weighted_recent_ret'])} weighted_2y_pf_cap={float(v['weighted_recent_pf']):.3f} | weighted_wf_pnl_delta={_fmt_num(v['weighted_wf_pnl_delta'])} | neg_recent={_fmt_pct(v['weighted_negative_recent'])}"
            )
    else:
        lines.append("- none")
    lines.append("")
    lines.append("[all_seed_variant_leaderboard]")
    for v in all_leaderboard[:6]:
        lines.append(
            f"- {v['name']} | weighted_2y_month={_fmt_pct(v['weighted_recent_monthly'])} weighted_2y_ret={_fmt_pct(v['weighted_recent_ret'])} weighted_2y_pf_cap={float(v['weighted_recent_pf']):.3f} | weighted_wf_pnl_delta={_fmt_num(v['weighted_wf_pnl_delta'])} | neg_recent={_fmt_pct(v['weighted_negative_recent'])}"
        )
    lines.append("")
    lines.append("[conclusion]")
    if pass_recommended:
        lines.append(f"- PASS seeds 推荐先看 {pass_recommended['name']}。")
        lines.append("- 但当前仍只做 research，不直接切 branch runtime。")
    elif all_recommended:
        lines.append(f"- 全种子里先看 {all_recommended['name']}，但它含 pending_resync 候选，不能直接切 runtime。")
        lines.append("- 下一步重点不是删路，而是继续补 ETH reclaim/hold 与 BTC/SOL 的 resync。")
    else:
        lines.append("- 这轮先不切 runtime。")
        lines.append("- 下一步继续 truth-locked seed + broadfront，不回头重修 system。")

    out_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    out_json.write_text(
        json.dumps(
            {
                "truth_locked": truth_locked,
                "candidate_results": candidate_results,
                "pass_only_variant_leaderboard": pass_leaderboard,
                "all_seed_variant_leaderboard": all_leaderboard,
                "pass_recommended_variant": pass_recommended,
                "all_recommended_variant": all_recommended,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-dir", required=True)
    ap.add_argument("--out-txt", required=True)
    ap.add_argument("--out-json", required=True)
    args = ap.parse_args()
    run(Path(args.project_dir).resolve(), Path(args.out_txt).resolve(), Path(args.out_json).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
