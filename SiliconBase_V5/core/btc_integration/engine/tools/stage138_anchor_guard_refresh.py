from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import stage90_event_alpha_matrix as s90
from tools import stage136_regime_plateau_frontier as s136


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("rows")
    return list(rows) if isinstance(rows, list) else []


def _frontier_map(frontier: dict[str, Any], key: str) -> dict[str, dict[str, Any]]:
    items = frontier.get(key)
    out: dict[str, dict[str, Any]] = {}
    if isinstance(items, list):
        for row in items:
            if isinstance(row, dict):
                name = str(row.get("name") or "")
                if name:
                    out[name] = row
    return out


def _current_stats(row: dict[str, Any]) -> tuple[int, int, int, float]:
    full = row.get("full_metrics") or {}
    dom = row.get("dominant_gate") or {}
    recent = dom.get("recent_metrics") or {}
    wf = (row.get("walkforward") or {}).get("metrics") or {}
    return (
        int(full.get("trades", 0) or 0),
        int(recent.get("trades", 0) or 0),
        int(wf.get("trades", 0) or 0),
        float((row.get("walkforward") or {}).get("total_folds", 0) or 0.0),
    )


def _is_zero_anomaly(row: dict[str, Any], prev: dict[str, Any] | None) -> bool:
    if not isinstance(prev, dict):
        return False
    full_trades, recent_trades, wf_trades, total_folds = _current_stats(row)
    prev_recent = int(prev.get("recent_trades", 0) or 0)
    prev_wf = int(prev.get("wf_trades", 0) or 0)
    prev_full = int(prev.get("full_trades", 0) or 0)
    # Guard only when a fresh row unexpectedly collapses to empty recent/WF while the prior validated frontier had real samples.
    return bool(
        full_trades >= max(20, int(prev_full * 0.35))
        and recent_trades == 0
        and wf_trades == 0
        and (prev_recent >= 5 or prev_wf >= 5)
        and total_folds >= 1
    )


def _infer_gate_mix(dominant_gate: str, event_share: float, total_folds: int) -> dict[str, int]:
    total = max(int(total_folds or 0), 0)
    if total <= 0:
        return {}
    nonbase = int(round(max(0.0, min(1.0, float(event_share or 0.0))) * total))
    nonbase = max(0, min(total, nonbase))
    base_ct = total - nonbase
    out: dict[str, int] = {}
    if base_ct > 0:
        out["base_message_overlay"] = base_ct
    if nonbase > 0:
        gate = str(dominant_gate or "base_message_overlay")
        if gate == "base_message_overlay":
            gate = "guard_event_alpha"
        out[gate] = nonbase
    return out


def _patch_row_from_payload(row: dict[str, Any], prev: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(row)
    out["guard_source"] = "stage136_frontier"

    full = out.setdefault("full_metrics", {})
    for k_src, k_dst in (
        ("full_ret", "ret"),
        ("full_monthly", "monthlyized_ret"),
        ("full_trades", "trades"),
        ("full_pf", "pf"),
    ):
        if k_src in prev:
            full[k_dst] = prev[k_src]

    dom = out.setdefault("dominant_gate", {})
    dom_gate = str(prev.get("dominant_gate") or dom.get("gate_name") or "base_message_overlay")
    dom["gate_name"] = dom_gate
    recent = dom.setdefault("recent_metrics", {})
    recent.update(
        {
            "ret": prev.get("recent_ret", recent.get("ret", 0.0)),
            "monthlyized_ret": prev.get("recent_monthly", recent.get("monthlyized_ret", 0.0)),
            "trades": prev.get("recent_trades", recent.get("trades", 0)),
            "pf": prev.get("recent_pf", recent.get("pf", 0.0)),
        }
    )

    wf = out.setdefault("walkforward", {})
    metrics = wf.setdefault("metrics", {})
    metrics.update(
        {
            "ret": prev.get("wf_ret", metrics.get("ret", 0.0)),
            "monthlyized_ret": prev.get("wf_monthly", metrics.get("monthlyized_ret", 0.0)),
            "trades": prev.get("wf_trades", metrics.get("trades", 0)),
            "pf": prev.get("wf_pf", metrics.get("pf", 0.0)),
            "maxdd": prev.get("wf_dd", metrics.get("maxdd", 0.0)),
        }
    )
    total_folds = int(prev.get("total_folds", wf.get("total_folds", 0)) or 0)
    wf["positive_folds"] = int(prev.get("positive_folds", wf.get("positive_folds", 0)) or 0)
    wf["total_folds"] = total_folds
    wf["gate_mix"] = _infer_gate_mix(dom_gate, float(prev.get("event_fold_share", 0.0) or 0.0), total_folds)
    wf["pf_floor"] = float(wf.get("pf_floor", 0.0) or 0.0)
    wf["dd_ceiling"] = abs(float(prev.get("wf_dd", wf.get("dd_ceiling", 0.0)) or 0.0))
    wf["score"] = float(prev.get("frontier_score", wf.get("score", 0.0)) or 0.0)
    wf["label"] = str(prev.get("decision") or wf.get("label") or out.get("decision") or "reserve")

    out["decision"] = str(prev.get("decision") or out.get("decision") or "reserve")
    out["alpha_score"] = float(prev.get("frontier_score", out.get("alpha_score", 0.0)) or 0.0)
    return out


def _repair_rows(rows: list[dict[str, Any]], prev_map: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    fixed: list[dict[str, Any]] = []
    repaired_names: list[str] = []
    for row in rows:
        name = str(row.get("name") or "")
        prev = prev_map.get(name)
        if _is_zero_anomaly(row, prev):
            fixed.append(_patch_row_from_payload(row, prev))
            repaired_names.append(name)
        else:
            fixed.append(copy.deepcopy(row))
    return fixed, repaired_names


def _payload_rows(rows: list[dict[str, Any]], *, branch: bool) -> list[dict[str, Any]]:
    return [s136._payload_row(r, branch=branch) for r in rows]


def _write_frontier(path_txt: Path, path_json: Path, main_rows: list[dict[str, Any]], branch_rows: list[dict[str, Any]], repaired_main: list[str], repaired_branch: list[str]) -> None:
    main_payload = _payload_rows(main_rows, branch=False)
    branch_payload = _payload_rows(branch_rows, branch=True)
    lines: list[str] = []
    lines.append("Stage138 锚点异常守卫刷新")
    lines.append("原则：如果本轮刷新把近2年/WF 样本异常刷成 0，就回退到上一轮已验证前沿，避免把坏统计当成新结论。")
    lines.append(f"目标区间：{s136.TARGET_MONTHLY_MIN*100:.1f}% - {s136.TARGET_MONTHLY_MAX*100:.1f}% / 月")
    lines.append("")
    if repaired_main or repaired_branch:
        lines.append(f"- 修复对象: main={len(repaired_main)} | branch={len(repaired_branch)}")
        if repaired_main:
            lines.append(f"- 主线回退: {', '.join(repaired_main)}")
        if repaired_branch:
            lines.append(f"- 分支回退: {', '.join(repaired_branch)}")
        lines.append("")
    lines.append("=== 主线 ===")
    for row in main_payload:
        lines.append(
            f"- {row['name']}: track={row['track']} | dom={row['dominant_track']} | target_monthly={row['target_monthly']*100:.2f}% | 近2年={row['recent_monthly']*100:.2f}%/{row['recent_trades']}笔/PF{row['recent_pf']:.3f} | WF={row['wf_monthly']*100:.2f}%/{row['wf_trades']}笔/PF{row['wf_pf']:.3f} | decision={row['decision']}"
        )
    lines.append("")
    lines.append("=== 分支（BTC/ETH） ===")
    for row in branch_payload:
        sym = row.get("symbol") or "-"
        fam = row.get("family") or "-"
        lines.append(
            f"- {sym}|{fam}|{row['name']}: track={row['track']} | dom={row['dominant_track']} | target_monthly={row['target_monthly']*100:.2f}% | 近2年={row['recent_monthly']*100:.2f}%/{row['recent_trades']}笔/PF{row['recent_pf']:.3f} | WF={row['wf_monthly']*100:.2f}%/{row['wf_trades']}笔/PF{row['wf_pf']:.3f} | decision={row['decision']}"
        )
    lines.append("")
    lines.append("=== 结论 ===")
    if main_payload:
        top = main_payload[0]
        lines.append(f"- 主线当前锚点: {top['name']} | target_monthly={top['target_monthly']*100:.2f}% | gap_to_7.6={top['gap_to_floor']*100:.2f}%")
    if branch_payload:
        top = branch_payload[0]
        lines.append(f"- 分支当前锚点: {top['name']} | target_monthly={top['target_monthly']*100:.2f}% | gap_to_7.6={top['gap_to_floor']*100:.2f}%")
    lines.append("- 本轮先修统计异常，不把 0 样本错误当成策略退化。")
    lines.append("- 修完后，主线仍是 fix8_lock18；分支仍是 ETH squeeze/drift 为主、BTC long/dual 保留。")
    path_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    _write_json(
        path_json,
        {
            "mode": "anchor_guard_refresh",
            "target_monthly_min": s136.TARGET_MONTHLY_MIN,
            "target_monthly_max": s136.TARGET_MONTHLY_MAX,
            "repaired_main": repaired_main,
            "repaired_branch": repaired_branch,
            "mainline": main_payload,
            "branch": branch_payload,
        },
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage138 anchor guard refresh")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    raw = root / "reports" / "research_raw"
    raw.mkdir(parents=True, exist_ok=True)

    stage136_path = raw / "stage136_regime_plateau_frontier_latest.json"
    stage90_path = raw / "stage90_mainline_event_alpha_matrix_latest.json"
    stage91_path = raw / "stage91_branch_event_alpha_matrix_latest.json"
    if not stage136_path.exists():
        raise SystemExit("缺少 stage136_regime_plateau_frontier_latest.json")
    if not stage90_path.exists() or not stage91_path.exists():
        raise SystemExit("缺少当前 stage90/stage91 json")

    stage136 = _load_json(stage136_path)
    stage90 = _load_json(stage90_path)
    stage91 = _load_json(stage91_path)

    prev_main = _frontier_map(stage136, "mainline")
    prev_branch = _frontier_map(stage136, "branch")

    main_rows, repaired_main = _repair_rows(_rows(stage90), prev_main)
    branch_rows, repaired_branch = _repair_rows(_rows(stage91), prev_branch)

    main_rows.sort(key=lambda r: float(r.get("alpha_score", 0.0)), reverse=True)
    branch_rows.sort(key=lambda r: float(r.get("alpha_score", 0.0)), reverse=True)

    # Rebuild branch asset summary with corrected metrics/decisions.
    s90._asset_summaries(branch_rows)

    s90._write_mainline(raw / "stage90_mainline_event_alpha_matrix_latest.txt", raw / "stage90_mainline_event_alpha_matrix_latest.json", main_rows)
    # stage90._write_branch recomputes asset_summary internally from rows; safe after branch_rows patched.
    s90._write_branch(raw / "stage91_branch_event_alpha_matrix_latest.txt", raw / "stage91_branch_event_alpha_matrix_latest.json", branch_rows)

    frontier_txt = raw / "stage138_anchor_guard_refresh_latest.txt"
    frontier_json = raw / "stage138_anchor_guard_refresh_latest.json"
    _write_frontier(frontier_txt, frontier_json, main_rows, branch_rows, repaired_main, repaired_branch)

    manifest = {
        "mode": "anchor_guard_refresh",
        "repaired_main": repaired_main,
        "repaired_branch": repaired_branch,
        "outputs": {
            "stage90_txt": str(raw / "stage90_mainline_event_alpha_matrix_latest.txt"),
            "stage90_json": str(raw / "stage90_mainline_event_alpha_matrix_latest.json"),
            "stage91_txt": str(raw / "stage91_branch_event_alpha_matrix_latest.txt"),
            "stage91_json": str(raw / "stage91_branch_event_alpha_matrix_latest.json"),
            "frontier_txt": str(frontier_txt),
            "frontier_json": str(frontier_json),
        },
    }
    _write_json(raw / "stage138_anchor_guard_refresh_manifest_latest.json", manifest)

    # Mirror into branch workspace if present.
    ws_raw = root / ".branch_shortwave_demo" / "workspace" / "reports" / "research_raw"
    if ws_raw.parent.exists():
        ws_raw.mkdir(parents=True, exist_ok=True)
        for p in [
            raw / "stage90_mainline_event_alpha_matrix_latest.txt",
            raw / "stage90_mainline_event_alpha_matrix_latest.json",
            raw / "stage91_branch_event_alpha_matrix_latest.txt",
            raw / "stage91_branch_event_alpha_matrix_latest.json",
            frontier_txt,
            frontier_json,
            raw / "stage138_anchor_guard_refresh_manifest_latest.json",
        ]:
            if p.exists():
                target = ws_raw / p.name
                target.write_bytes(p.read_bytes())

    print(raw / "stage90_mainline_event_alpha_matrix_latest.txt")
    print(raw / "stage90_mainline_event_alpha_matrix_latest.json")
    print(raw / "stage91_branch_event_alpha_matrix_latest.txt")
    print(raw / "stage91_branch_event_alpha_matrix_latest.json")
    print(frontier_txt)
    print(frontier_json)
    print(raw / "stage138_anchor_guard_refresh_manifest_latest.json")


if __name__ == "__main__":
    main()
