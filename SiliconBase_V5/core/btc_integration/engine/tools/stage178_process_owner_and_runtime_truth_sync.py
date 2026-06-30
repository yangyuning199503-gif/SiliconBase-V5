from __future__ import annotations

import argparse
import contextlib
import csv
import json
import os
import re
import shutil
import signal
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Any

TIME_KEYS = ("time", "timestamp", "ts", "datetime", "date", "open_time")
ROWS_RE = re.compile(r"rows_total_after=(\d+)")
PID_RE = re.compile(r"-\s*进程 PID:\s*(\d+)")
ROLE_RE = re.compile(r"-\s*运行角色:\s*(.+)")
STATE_RE = re.compile(r"-\s*当前状态:\s*(.+)")
VERSION_RE = re.compile(r"-\s*当前版本:\s*(.+)")


def _run_cmd(cmd: list[str], cwd: Path) -> dict[str, Any]:
    try:
        proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, check=False)
        return {
            "cmd": cmd,
            "returncode": proc.returncode,
            "stdout_tail": "\n".join(proc.stdout.splitlines()[-20:]),
            "stderr_tail": "\n".join(proc.stderr.splitlines()[-20:]),
        }
    except Exception as exc:  # pragma: no cover
        return {"cmd": cmd, "returncode": -999, "error": f"{type(exc).__name__}: {exc}"}


def _count_csv_rows(path: Path) -> int:
    if not path.exists() or not path.is_file() or path.stat().st_size <= 0:
        return 0
    try:
        with path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                return 0
            return sum(1 for _ in reader)
    except Exception:
        return 0


def _read_pid_file(path: Path) -> int | None:
    try:
        txt = path.read_text(encoding="utf-8").strip()
        return int(txt) if txt else None
    except Exception:
        return None


def _kill_pid(pid: int, sig: int) -> None:
    with contextlib.suppress(Exception):
        os.kill(pid, sig)


def _pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _pgrep(pattern: str) -> list[int]:
    try:
        proc = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True, check=False)
        if proc.returncode not in (0, 1):
            return []
        out = []
        for line in proc.stdout.splitlines():
            line = line.strip()
            if line.isdigit():
                out.append(int(line))
        return out
    except Exception:
        return []


def _hard_kill_patterns(patterns: list[str]) -> dict[str, Any]:
    seen: dict[int, str] = {}
    for pattern in patterns:
        for pid in _pgrep(pattern):
            seen[pid] = pattern
    pids = sorted(seen)
    for pid in pids:
        _kill_pid(pid, signal.SIGTERM)
    time.sleep(1.0)
    still_alive = []
    for pid in pids:
        if _pid_alive(pid):
            still_alive.append(pid)
            _kill_pid(pid, signal.SIGKILL)
    time.sleep(0.5)
    return {
        "patterns": patterns,
        "matched_pids": pids,
        "forced_kill_pids": still_alive,
    }


def _remove_paths(paths: list[Path]) -> list[str]:
    removed: list[str] = []
    for p in paths:
        try:
            if p.exists() or p.is_symlink():
                if p.is_dir() and not p.is_symlink():
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    p.unlink()
                removed.append(str(p))
        except Exception:
            pass
    return removed


def _wait_for_report(report_path: Path, timeout_s: int = 120) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if report_path.exists() and report_path.stat().st_size > 0:
            text = report_path.read_text(encoding="utf-8", errors="ignore")
            if "rows_total_after=" in text and "当前状态: 启动中" not in text and "启动失败" not in text:
                return True
        time.sleep(2)
    return False


def _parse_report(path: Path) -> dict[str, Any]:
    out: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "pid": None,
        "runner_role": None,
        "version": None,
        "state": None,
        "rows_total_after": {},
    }
    if not path.exists():
        return out
    current_sym: str | None = None
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        m = PID_RE.match(line)
        if m:
            out["pid"] = int(m.group(1))
            continue
        m = ROLE_RE.match(line)
        if m:
            out["runner_role"] = m.group(1).strip()
            continue
        m = STATE_RE.match(line)
        if m:
            out["state"] = m.group(1).strip()
            continue
        m = VERSION_RE.match(line)
        if m:
            out["version"] = m.group(1).strip()
            continue
        if line.startswith("[") and line.endswith("]"):
            current_sym = line.strip("[]")
            continue
        if current_sym and "rows_total_after=" in line:
            m = ROWS_RE.search(line)
            if m:
                out["rows_total_after"][current_sym] = int(m.group(1))
    return out


def _audit_raw_rows(root: Path) -> dict[str, int]:
    data_raw = root / "data" / "raw"
    return {
        "BTC": _count_csv_rows(data_raw / "btc_15m.csv"),
        "BNB": _count_csv_rows(data_raw / "bnb_15m.csv"),
        "ETH": _count_csv_rows(data_raw / "eth_15m.csv"),
        "SOL": _count_csv_rows(data_raw / "sol_15m.csv"),
    }


def _write_outputs(root: Path, payload: dict[str, Any]) -> tuple[Path, Path, Path]:
    reports = root / "reports" / "research_raw"
    reports.mkdir(parents=True, exist_ok=True)
    downloads = Path.home() / "Downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    txt_path = reports / "stage178_process_owner_and_runtime_truth_sync_latest.txt"
    json_path = reports / "stage178_process_owner_and_runtime_truth_sync_latest.json"
    zip_path = downloads / "stage178_process_owner_and_runtime_truth_sync_latest.zip"

    lines: list[str] = []
    lines.append("Stage178 进程归属硬重启 + runtime 真相同步")
    lines.append("")
    lines.append("[raw_rows]")
    for sym in ["BTC", "BNB", "ETH", "SOL"]:
        lines.append(f"- {sym}: {payload['raw_rows'].get(sym, 0)}")
    lines.append("")
    lines.append("[process_check]")
    lines.append(json.dumps(payload.get("process_check", {}), ensure_ascii=False, indent=2))
    lines.append("")
    lines.append("[row_check]")
    lines.append(json.dumps(payload.get("row_check", {}), ensure_ascii=False, indent=2))
    lines.append("")
    lines.append("[overall]")
    lines.append(json.dumps(payload.get("overall", {}), ensure_ascii=False, indent=2))
    lines.append("")
    lines.append("[next_actions]")
    for item in payload.get("next_actions", []):
        lines.append(f"- {item}")
    txt_path.write_text("\n".join(lines), encoding="utf-8")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(txt_path, arcname=txt_path.name)
        zf.write(json_path, arcname=json_path.name)
        for rp in [downloads / "okx_demo_report_latest.txt", downloads / "branch_demo_report_latest.txt"]:
            if rp.exists():
                zf.write(rp, arcname=rp.name)
    return txt_path, json_path, zip_path


def main() -> int:
    ap = argparse.ArgumentParser(description="Hard-restart main/branch autopilot and verify report owner + runtime rows")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()
    root = Path(args.project_dir).expanduser().resolve()
    downloads = Path.home() / "Downloads"
    downloads.mkdir(parents=True, exist_ok=True)

    pause_main = _run_cmd(["bash", "pause_okx_demo.sh"], root)
    pause_branch = _run_cmd(["bash", "pause_branch_demo.sh"], root)

    kill_all = _hard_kill_patterns([
        r"tools\.okx_demo_autopilot",
        r"start_okx_demo_autopilot\.command",
        r"start_triple_book_branch_monitor\.command",
    ])

    removed = _remove_paths([
        root / ".runtime" / "okx_demo_autopilot.pid",
        root / ".runtime" / "okx_demo_autopilot_state.json",
        root / ".runtime" / "okx_demo_shadow_exec_latest.json",
        root / ".runtime" / "okx_demo_shadow_exec_latest.jsonl",
        root / ".runtime" / "okx_demo_shadow_exec_latest.txt",
        root / ".branch_shortwave_demo" / "workspace" / ".runtime" / "okx_demo_autopilot.pid",
        root / ".branch_shortwave_demo" / "workspace" / ".runtime" / "okx_demo_autopilot_state.json",
        root / ".branch_shortwave_demo" / "workspace" / ".runtime" / "okx_demo_shadow_exec_latest.json",
        root / ".branch_shortwave_demo" / "workspace" / ".runtime" / "okx_demo_shadow_exec_latest.jsonl",
        root / ".branch_shortwave_demo" / "workspace" / ".runtime" / "okx_demo_shadow_exec_latest.txt",
        downloads / "okx_demo_report_latest.txt",
        downloads / "branch_demo_report_latest.txt",
    ])

    start_main = _run_cmd(["bash", "start_okx_demo.sh"], root)
    start_branch = _run_cmd(["bash", "start_branch_demo.sh"], root)
    wait_main = _wait_for_report(downloads / "okx_demo_report_latest.txt", timeout_s=120)
    wait_branch = _wait_for_report(downloads / "branch_demo_report_latest.txt", timeout_s=120)

    main_pid_file = _read_pid_file(root / ".runtime" / "okx_demo_autopilot.pid")
    branch_pid_file = _read_pid_file(root / ".branch_shortwave_demo" / "workspace" / ".runtime" / "okx_demo_autopilot.pid")
    main_report = _parse_report(downloads / "okx_demo_report_latest.txt")
    branch_report = _parse_report(downloads / "branch_demo_report_latest.txt")
    raw_rows = _audit_raw_rows(root)

    process_check = {
        "main": {
            "pid_file": main_pid_file,
            "report_pid": main_report.get("pid"),
            "report_role": main_report.get("runner_role"),
            "pid_match": bool(main_pid_file and main_report.get("pid") == main_pid_file),
            "wait_ready": wait_main,
        },
        "branch": {
            "pid_file": branch_pid_file,
            "report_pid": branch_report.get("pid"),
            "report_role": branch_report.get("runner_role"),
            "pid_match": bool(branch_pid_file and branch_report.get("pid") == branch_pid_file),
            "wait_ready": wait_branch,
        },
    }
    row_check = {
        "main": {
            "BTC": {"raw": raw_rows["BTC"], "report": int((main_report.get("rows_total_after") or {}).get("BTC") or 0)},
            "BNB": {"raw": raw_rows["BNB"], "report": int((main_report.get("rows_total_after") or {}).get("BNB") or 0)},
        },
        "branch": {
            "BTC": {"raw": raw_rows["BTC"], "report": int((branch_report.get("rows_total_after") or {}).get("BTC") or 0)},
            "ETH": {"raw": raw_rows["ETH"], "report": int((branch_report.get("rows_total_after") or {}).get("ETH") or 0)},
            "SOL": {"raw": raw_rows["SOL"], "report": int((branch_report.get("rows_total_after") or {}).get("SOL") or 0)},
        },
    }
    for group in row_check.values():
        for item in group.values():
            item["anomaly"] = item["raw"] != item["report"]

    overall = {
        "process_owner_ok": process_check["main"]["pid_match"] and process_check["branch"]["pid_match"],
        "runtime_rows_ok": not any(item["anomaly"] for group in row_check.values() for item in group.values()),
        "reports_ready": wait_main and wait_branch,
    }
    overall["system_ready_for_frontier"] = bool(overall["process_owner_ok"] and overall["runtime_rows_ok"] and overall["reports_ready"])

    next_actions: list[str] = []
    if not overall["process_owner_ok"]:
        next_actions.append("报告 PID 仍未对齐 PID 文件；继续只修运行层，不动策略层。")
    if not overall["runtime_rows_ok"]:
        next_actions.append("rows_total_after 仍与 raw 不一致；继续只修 runtime 同步，不动策略层。")
    if overall["system_ready_for_frontier"]:
        next_actions.append("系统层通过；下一轮才继续 frontier / 回测创新。")
    else:
        next_actions.append("系统层仍未完全通过；先稳定，再创新。")

    payload: dict[str, Any] = {
        "title": "Stage178 进程归属硬重启 + runtime 真相同步",
        "pause_main": pause_main,
        "pause_branch": pause_branch,
        "kill_all": kill_all,
        "removed": removed,
        "start_main": start_main,
        "start_branch": start_branch,
        "raw_rows": raw_rows,
        "main_report": main_report,
        "branch_report": branch_report,
        "process_check": process_check,
        "row_check": row_check,
        "overall": overall,
        "next_actions": next_actions,
    }
    _, _, zip_path = _write_outputs(root, payload)
    print(f"OK -> {zip_path}")
    return 0 if overall["system_ready_for_frontier"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
