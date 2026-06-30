from __future__ import annotations

import argparse
import contextlib
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

REPORT_VERSION_RE = re.compile(r"^- 当前版本:\s*(.+)$")
REPORT_CANDIDATE_RE = re.compile(r"^- 当前候选:\s*(.+)$")
SECTION_RE = re.compile(r"^\[([A-Z]+)\]$")
ROWS_RE = re.compile(r"rows_total_after=(\d+)")
RECENT_RET_RE = re.compile(r"近2年(?:样本)?[:：]?\s*收益[=：]([-+0-9.]+)%")
WF_RET_RE = re.compile(r"WF(?:样本外)?[:：]?\s*收益[=：]([-+0-9.]+)%")
STAGE90_LINE_RE = re.compile(
    r"^-\s*(?P<name>[^:]+):.*?近2年\s*收益=(?P<recent>[-+0-9.]+)%.*?WF样本外\s*收益=(?P<wf>[-+0-9.]+)%",
    re.IGNORECASE,
)
STAGE91_LINE_RE = re.compile(
    r"^-\s*(?P<asset>[A-Z]+)\s*\|\s*(?P<side>long|short|dual)\s*\|\s*(?P<name>[^:]+):.*?近2年\s*收益=(?P<recent>[-+0-9.]+)%.*?WF样本外\s*收益=(?P<wf>[-+0-9.]+)%",
    re.IGNORECASE,
)


def _run(cmd: list[str], cwd: Path) -> dict[str, Any]:
    p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    return {
        "cmd": cmd,
        "returncode": p.returncode,
        "stdout": p.stdout[-4000:],
        "stderr": p.stderr[-4000:],
        "ok": p.returncode == 0,
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _parse_runtime_report(path: Path) -> dict[str, Any]:
    out: dict[str, Any] = {"path": str(path), "exists": path.exists(), "version": None, "candidate": None, "rows_total_after": {}, "recent_ret": None, "wf_ret": None}
    if not path.exists():
        return out
    current_section = None
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        m = REPORT_VERSION_RE.match(line)
        if m:
            out["version"] = m.group(1).strip()
            continue
        m = REPORT_CANDIDATE_RE.match(line)
        if m:
            out["candidate"] = m.group(1).strip()
            continue
        m = SECTION_RE.match(line)
        if m:
            current_section = m.group(1).upper()
            continue
        m = ROWS_RE.search(line)
        if m and current_section:
            with contextlib.suppress(Exception):
                out["rows_total_after"][current_section] = int(m.group(1))
        if out["recent_ret"] is None:
            m = RECENT_RET_RE.search(line)
            if m:
                with contextlib.suppress(Exception):
                    out["recent_ret"] = float(m.group(1))
        if out["wf_ret"] is None:
            m = WF_RET_RE.search(line)
            if m:
                with contextlib.suppress(Exception):
                    out["wf_ret"] = float(m.group(1))
    return out


def _parse_stage90_metrics(path: Path, candidate_name: str) -> dict[str, Any]:
    out: dict[str, Any] = {"candidate": candidate_name, "exists": path.exists(), "recent_ret": None, "wf_ret": None, "matched": False}
    if not path.exists() or not candidate_name:
        return out
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = STAGE90_LINE_RE.match(raw.strip())
        if not m:
            continue
        if m.group("name").strip() == candidate_name:
            out["matched"] = True
            out["recent_ret"] = float(m.group("recent"))
            out["wf_ret"] = float(m.group("wf"))
            return out
    return out


def _parse_stage91_metrics(path: Path, candidate_blob: str) -> dict[str, Any]:
    out: dict[str, Any] = {"exists": path.exists(), "matched": {}}
    if not path.exists() or not candidate_blob:
        return out
    # current candidate blob example: BTC:xxx ; ETH:yyy ; SOL:zzz
    wanted: dict[str, str] = {}
    for part in candidate_blob.split(";"):
        if ":" not in part:
            continue
        asset, name = part.split(":", 1)
        wanted[asset.strip().upper()] = name.strip()
    found: dict[str, Any] = {}
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = STAGE91_LINE_RE.match(raw.strip())
        if not m:
            continue
        asset = m.group("asset").upper()
        name = m.group("name").strip()
        if wanted.get(asset) == name:
            found[asset] = {
                "name": name,
                "recent_ret": float(m.group("recent")),
                "wf_ret": float(m.group("wf")),
            }
    out["matched"] = found
    return out


def _pack(zip_path: Path, files: list[Path]) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            if f.exists():
                zf.write(f, arcname=f.name)


def main() -> int:
    ap = argparse.ArgumentParser(description="系统稳定性 / 数据 / 死角确认")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    reports = root / "reports" / "research_raw"
    reports.mkdir(parents=True, exist_ok=True)
    downloads = Path.home() / "Downloads"
    downloads.mkdir(parents=True, exist_ok=True)

    stage167 = root / "tools" / "stage167_data_repair_diversity_guard.py"
    stage168 = root / "tools" / "stage168_bnb_gap_quarantine_and_family_cap.py"
    run_log: dict[str, Any] = {}

    run_log["stage167"] = _run([sys.executable, str(stage167), "--project-dir", str(root)], cwd=root)
    run_log["stage168"] = _run([sys.executable, str(stage168)], cwd=root)

    stage167_json = reports / "stage167_data_repair_diversity_guard_latest.json"
    reports / "stage168_bnb_gap_quarantine_and_family_cap_latest.txt"
    stage90_txt = reports / "stage90_mainline_event_alpha_matrix_latest.txt"
    stage91_txt = reports / "stage91_branch_event_alpha_matrix_latest.txt"

    data167 = _read_json(stage167_json)
    raw_after = data167.get("raw_after", {}) if isinstance(data167, dict) else {}
    repairs = data167.get("repairs", {}) if isinstance(data167, dict) else {}
    dead_main = data167.get("dead_main", {}) if isinstance(data167, dict) else {}
    dead_branch = data167.get("dead_branch", {}) if isinstance(data167, dict) else {}
    main_collapse = data167.get("main_collapse", {}) if isinstance(data167, dict) else {}
    branch_collapse = data167.get("branch_collapse", {}) if isinstance(data167, dict) else {}

    okx_report = _parse_runtime_report(downloads / "okx_demo_report_latest.txt")
    branch_report = _parse_runtime_report(downloads / "branch_demo_report_latest.txt")

    runtime_row_checks: dict[str, Any] = {}
    for sym in ["btc", "bnb", "eth", "sol"]:
        raw_rows = int((raw_after.get(sym) or {}).get("rows") or 0)
        runtime_rows = None
        if sym.upper() in okx_report.get("rows_total_after", {}):
            runtime_rows = okx_report["rows_total_after"][sym.upper()]
        elif sym.upper() in branch_report.get("rows_total_after", {}):
            runtime_rows = branch_report["rows_total_after"][sym.upper()]
        anomaly = bool(raw_rows and runtime_rows is not None and runtime_rows < raw_rows * 0.90)
        runtime_row_checks[sym] = {
            "raw_rows": raw_rows,
            "runtime_rows": runtime_rows,
            "anomaly": anomaly,
        }

    stage90_runtime = _parse_stage90_metrics(stage90_txt, str(okx_report.get("candidate") or ""))
    stage91_runtime = _parse_stage91_metrics(stage91_txt, str(branch_report.get("candidate") or ""))

    research_runtime_drift: dict[str, Any] = {
        "mainline": None,
        "branch": {},
    }
    if okx_report.get("candidate") and stage90_runtime.get("matched"):
        rr = abs(float(okx_report.get("recent_ret") or 0.0) - float(stage90_runtime.get("recent_ret") or 0.0))
        wr = abs(float(okx_report.get("wf_ret") or 0.0) - float(stage90_runtime.get("wf_ret") or 0.0))
        research_runtime_drift["mainline"] = {
            "candidate": okx_report.get("candidate"),
            "report_recent": okx_report.get("recent_ret"),
            "stage90_recent": stage90_runtime.get("recent_ret"),
            "report_wf": okx_report.get("wf_ret"),
            "stage90_wf": stage90_runtime.get("wf_ret"),
            "recent_gap": round(rr, 2),
            "wf_gap": round(wr, 2),
            "anomaly": rr > 30 or wr > 30,
        }
    matched_branch = stage91_runtime.get("matched", {}) if isinstance(stage91_runtime, dict) else {}
    for asset, payload in matched_branch.items():
        # crude parse from candidate lines isn't needed; use no anomaly unless asset candidates not found
        research_runtime_drift["branch"][asset] = {
            "candidate": payload.get("name"),
            "stage91_recent": payload.get("recent_ret"),
            "stage91_wf": payload.get("wf_ret"),
        }

    dead_main_count = len(set((dead_main.get("dead_full_zero") or []) + (dead_main.get("dead_recent_wf_zero") or [])))
    dead_branch_count = len(set((dead_branch.get("dead_full_zero") or []) + (dead_branch.get("dead_recent_wf_zero") or [])))

    overall = {
        "raw_ok": all(int((raw_after.get(sym) or {}).get("non15m_gaps") or 0) == 0 and int((raw_after.get(sym) or {}).get("dupes") or 0) == 0 for sym in ["btc", "bnb", "eth", "sol"]),
        "runtime_row_ok": not any(v.get("anomaly") for v in runtime_row_checks.values()),
        "main_dead_count": dead_main_count,
        "branch_dead_count": dead_branch_count,
        "main_dominant_ratio": float(main_collapse.get("dominant_ratio") or 0.0),
        "branch_dominant_ratio": float(branch_collapse.get("dominant_ratio") or 0.0),
        "research_runtime_mainline_drift": bool((research_runtime_drift.get("mainline") or {}).get("anomaly")),
    }
    overall["system_ready_for_new_frontier"] = bool(
        overall["raw_ok"]
        and overall["runtime_row_ok"]
        and not overall["research_runtime_mainline_drift"]
        and overall["branch_dominant_ratio"] < 0.80
    )

    lines: list[str] = []
    lines.append("Stage176 系统稳定性 / 数据 / 死角确认")
    lines.append("")
    lines.append("[raw_after]")
    for sym in ["btc", "bnb", "eth", "sol"]:
        item = raw_after.get(sym, {})
        lines.append(
            f"- {sym.upper()}: rows={item.get('rows', 0)} start={item.get('start', '-')} end={item.get('end', '-')} dupes={item.get('dupes', '-')} non15m_gaps={item.get('non15m_gaps', '-')}"
        )
    lines.append("")
    lines.append("[repairs]")
    lines.append(json.dumps(repairs, ensure_ascii=False, indent=2))
    lines.append("")
    lines.append("[runtime_row_check]")
    for sym in ["btc", "bnb", "eth", "sol"]:
        item = runtime_row_checks.get(sym, {})
        lines.append(f"- {sym.upper()}: raw_rows={item.get('raw_rows')} runtime_rows={item.get('runtime_rows')} anomaly={item.get('anomaly')}")
    lines.append("")
    lines.append("[dead_templates]")
    lines.append(f"- main_dead_count={dead_main_count}")
    lines.append(f"- branch_dead_count={dead_branch_count}")
    lines.append("")
    lines.append("[collapse]")
    lines.append(f"- main_dominant_family={main_collapse.get('dominant_family')} ratio={main_collapse.get('dominant_ratio')}")
    lines.append(f"- branch_dominant_family={branch_collapse.get('dominant_family')} ratio={branch_collapse.get('dominant_ratio')}")
    lines.append("")
    lines.append("[research_runtime_drift]")
    lines.append(json.dumps(research_runtime_drift, ensure_ascii=False, indent=2))
    lines.append("")
    lines.append("[runtime_reports]")
    lines.append(json.dumps({"okx": okx_report, "branch": branch_report}, ensure_ascii=False, indent=2))
    lines.append("")
    lines.append("[overall]")
    lines.append(json.dumps(overall, ensure_ascii=False, indent=2))
    lines.append("")
    lines.append("[next_actions]")
    if not overall["runtime_row_ok"]:
        lines.append("- 先修 runtime 行数异常，再继续刷 frontier；若 BTC 行数显著短于 raw，先重启 demo 并重新 sync。")
    if overall["research_runtime_mainline_drift"]:
        lines.append("- 先冻结 runtime 主线，不让新的 stage90 latest 直接覆盖当前已验证主线真相。")
    if overall["branch_dominant_ratio"] >= 0.80:
        lines.append("- 分支下一轮必须强制 family diversity cap，不能再让单一家族占满 top 名额。")
    if dead_main_count or dead_branch_count:
        lines.append("- 下一轮 frontier 先剔除 dead_full_zero / dead_recent_wf_zero 模板，再谈创新。")
    if overall["system_ready_for_new_frontier"]:
        lines.append("- 系统层通过，可以继续新 frontier。")
    else:
        lines.append("- 系统层未完全通过，先做稳定性/全面性修正，再继续策略创新。")

    txt_path = reports / "stage176_system_stability_deadangle_guard_latest.txt"
    json_path = reports / "stage176_system_stability_deadangle_guard_latest.json"
    txt_path.write_text("\n".join(lines), encoding="utf-8")
    json_path.write_text(json.dumps({
        "run_log": run_log,
        "raw_after": raw_after,
        "repairs": repairs,
        "runtime_row_checks": runtime_row_checks,
        "dead_main_count": dead_main_count,
        "dead_branch_count": dead_branch_count,
        "main_collapse": main_collapse,
        "branch_collapse": branch_collapse,
        "research_runtime_drift": research_runtime_drift,
        "runtime_reports": {"okx": okx_report, "branch": branch_report},
        "overall": overall,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    bundle = downloads / "stage176_system_stability_deadangle_guard_latest.zip"
    files = [
        txt_path,
        json_path,
        reports / "stage167_data_repair_diversity_guard_latest.txt",
        reports / "stage167_data_repair_diversity_guard_latest.json",
        reports / "stage168_bnb_gap_quarantine_and_family_cap_latest.txt",
        reports / "stage168_bnb_gap_windows_latest.csv",
        reports / "stage168_dead_template_blacklist_latest.json",
        reports / "stage168_family_capped_shortlist_latest.json",
        downloads / "okx_demo_report_latest.txt",
        downloads / "branch_demo_report_latest.txt",
    ]
    _pack(bundle, files)

    print(json.dumps({"ok": True, "report": str(txt_path), "bundle": str(bundle), "overall": overall}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
