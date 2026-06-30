from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import pandas as pd

try:
    from tools.fetch_binance_klines import _to_ms, fetch_klines
except Exception:  # pragma: no cover
    fetch_klines = None  # type: ignore[assignment]
    _to_ms = None  # type: ignore[assignment]

TIME_KEYS = ("time", "timestamp", "ts", "datetime", "date", "open_time")
ROWS_RE = re.compile(r"rows_total_after=(\d+)")
CAND_RE = re.compile(r"-\s*当前候选:\s*(.+)")
RET_RE = re.compile(r"收益=([-+0-9.]+)%")
WF_RE = re.compile(r"WF(?:样本外)?\s*收益=([-+0-9.]+)%")


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or not path.is_file() or path.stat().st_size <= 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def _find_time_col(df: pd.DataFrame) -> str:
    cols = {str(c).lower(): str(c) for c in df.columns}
    for key in TIME_KEYS:
        if key in cols:
            return cols[key]
    raise ValueError(f"CSV 缺少时间列 | columns={list(df.columns)}")


def _audit_csv(path: Path) -> dict[str, Any]:
    out: dict[str, Any] = {
        "exists": path.exists() and path.is_file(),
        "file": str(path),
        "rows": 0,
        "start": None,
        "end": None,
        "dupes": 0,
        "non15m_gaps": 0,
        "max_gap": None,
        "gaps": [],
    }
    if not out["exists"] or path.stat().st_size <= 0:
        return out
    try:
        df = _read_csv(path)
        if df.empty:
            return out
        time_col = _find_time_col(df)
        ts = pd.to_datetime(df[time_col], errors="coerce")
        df = df.loc[ts.notna()].copy()
        df[time_col] = pd.to_datetime(df[time_col], errors="coerce")
        if df.empty:
            return out
        idx = pd.DatetimeIndex(df[time_col]).sort_values()
        out["rows"] = int(len(idx))
        out["dupes"] = int(pd.Series(idx).duplicated().sum())
        out["start"] = idx[0].strftime("%Y-%m-%d %H:%M:%S")
        out["end"] = idx[-1].strftime("%Y-%m-%d %H:%M:%S")
        diffs = pd.Series(idx).diff().dropna()
        exp = pd.Timedelta(minutes=15)
        if not diffs.empty:
            bad = diffs[diffs != exp]
            out["non15m_gaps"] = int(len(bad))
            out["max_gap"] = str(diffs.max())
            gaps: list[dict[str, Any]] = []
            for i in bad.index.tolist():
                prev_t = idx[i - 1]
                cur_t = idx[i]
                missing = max(int((cur_t - prev_t) / exp) - 1, 0)
                gaps.append({
                    "prev_ts": prev_t.strftime("%Y-%m-%d %H:%M:%S"),
                    "next_ts": cur_t.strftime("%Y-%m-%d %H:%M:%S"),
                    "gap": str(cur_t - prev_t),
                    "missing_bars": missing,
                })
            out["gaps"] = gaps
        else:
            out["max_gap"] = "0 days 00:15:00"
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def _segment_from_rows(rows: list[list]) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for r in rows:
        if not r:
            continue
        ot = int(r[0])
        t = pd.Timestamp.utcfromtimestamp(ot / 1000).strftime("%Y-%m-%d %H:%M:%S")
        records.append(
            {
                "time": t,
                "open": float(r[1]),
                "high": float(r[2]),
                "low": float(r[3]),
                "close": float(r[4]),
                "volume": float(r[5]),
            }
        )
    if not records:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])
    df = pd.DataFrame(records).drop_duplicates("time").sort_values("time").reset_index(drop=True)
    return df


def _merge_segments(raw_path: Path, segments: list[pd.DataFrame]) -> dict[str, Any]:
    raw_df = _read_csv(raw_path)
    if raw_df.empty:
        raw_df = pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])
    frames = [raw_df] + [seg for seg in segments if not seg.empty]
    merged = pd.concat(frames, ignore_index=True)
    if merged.empty:
        return {"changed": False, "rows": 0}
    time_col = _find_time_col(merged)
    merged[time_col] = pd.to_datetime(merged[time_col], errors="coerce")
    merged = merged.dropna(subset=[time_col]).sort_values(time_col).drop_duplicates(subset=[time_col], keep="last").reset_index(drop=True)
    out_df = merged.copy()
    out_df[time_col] = out_df[time_col].dt.strftime("%Y-%m-%d %H:%M:%S")
    backup = raw_path.with_suffix(raw_path.suffix + ".pre_stage177_backup")
    if raw_path.exists() and not backup.exists():
        shutil.copy2(raw_path, backup)
    with NamedTemporaryFile("w", encoding="utf-8", newline="", suffix=".csv", dir=str(raw_path.parent), delete=False) as tmp:
        tmp_path = Path(tmp.name)
        out_df.to_csv(tmp, index=False)
    tmp_path.replace(raw_path)
    return {
        "changed": True,
        "rows": int(len(out_df)),
        "backup": str(backup) if backup.exists() else "",
        "first": str(out_df.iloc[0][time_col]) if len(out_df) else None,
        "last": str(out_df.iloc[-1][time_col]) if len(out_df) else None,
    }


def _attempt_gap_fill(root: Path, symbol: str, audit: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "attempted": False,
        "filled_segments": 0,
        "filled_bars": 0,
        "changed": False,
        "reason": "no_gap_fill_needed",
        "segment_windows": [],
    }
    if symbol.lower() != "btc":
        return out
    gaps = list(audit.get("gaps") or [])
    if not gaps:
        return out
    if fetch_klines is None or _to_ms is None:
        out["reason"] = "fetch_binance_klines_unavailable"
        return out

    segments: list[pd.DataFrame] = []
    for gap in gaps:
        prev_ts = pd.Timestamp(gap["prev_ts"])
        next_ts = pd.Timestamp(gap["next_ts"])
        start_ts = prev_ts + pd.Timedelta(minutes=15)
        end_ts = next_ts
        if end_ts <= start_ts:
            continue
        out["attempted"] = True
        try:
            rows = fetch_klines(
                "BTCUSDT",
                "futures",
                "15m",
                _to_ms(start_ts.strftime("%Y-%m-%d %H:%M:%S")),
                _to_ms(end_ts.strftime("%Y-%m-%d %H:%M:%S")),
                max_retries=6,
                page_sleep=0.12,
            )
            seg = _segment_from_rows(rows)
            segments.append(seg)
            out["filled_segments"] += 1
            out["filled_bars"] += int(len(seg))
            out["segment_windows"].append(
                {
                    "start": start_ts.strftime("%Y-%m-%d %H:%M:%S"),
                    "end": end_ts.strftime("%Y-%m-%d %H:%M:%S"),
                    "rows": int(len(seg)),
                }
            )
        except Exception as exc:
            out.setdefault("errors", []).append(f"{type(exc).__name__}: {exc}")
    if not segments:
        out["reason"] = "no_segment_fetched"
        return out
    raw_path = root / "data" / "raw" / f"{symbol.lower()}_15m.csv"
    merge = _merge_segments(raw_path, segments)
    out.update(merge)
    out["reason"] = "gap_fetch_merged" if merge.get("changed") else "gap_fetch_no_change"
    return out


def _run_cmd(cmd: list[str], cwd: Path) -> dict[str, Any]:
    try:
        proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, check=False)
        return {
            "cmd": cmd,
            "returncode": proc.returncode,
            "stdout_tail": "\n".join(proc.stdout.splitlines()[-20:]),
            "stderr_tail": "\n".join(proc.stderr.splitlines()[-20:]),
        }
    except Exception as exc:
        return {"cmd": cmd, "returncode": -999, "error": f"{type(exc).__name__}: {exc}"}


def _wait_for_report(report_path: Path, timeout_s: int = 120) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if report_path.exists():
            text = report_path.read_text(encoding="utf-8", errors="ignore")
            if "rows_total_after=" in text and "当前状态: 启动中" not in text and "启动失败" not in text:
                return True
        time.sleep(2)
    return False


def _parse_report(report_path: Path) -> dict[str, Any]:
    out: dict[str, Any] = {
        "path": str(report_path),
        "exists": report_path.exists(),
        "version": None,
        "candidate": None,
        "rows_total_after": {},
        "recent_ret": None,
        "wf_ret": None,
        "state": None,
    }
    if not report_path.exists():
        return out
    lines = report_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    current_sym: str | None = None
    in_summary = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- 当前状态:"):
            out["state"] = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("- 当前版本:"):
            out["version"] = stripped.split(":", 1)[1].strip()
        elif stripped == "【策略评估摘要】":
            in_summary = True
        elif stripped.startswith("【") and stripped != "【策略评估摘要】":
            in_summary = False
        if in_summary and stripped.startswith("- 当前候选:"):
            out["candidate"] = stripped.split(":", 1)[1].strip()
        if in_summary and stripped.startswith("- 近2年样本:"):
            m = RET_RE.search(stripped)
            if m:
                out["recent_ret"] = float(m.group(1))
        elif in_summary and stripped.startswith("- WF样本外:"):
            m = WF_RE.search(stripped)
            if m:
                out["wf_ret"] = float(m.group(1))
        if stripped.startswith("[") and stripped.endswith("]"):
            current_sym = stripped.strip("[]")
        elif "rows_total_after=" in stripped and current_sym:
            m = ROWS_RE.search(stripped)
            if m:
                out["rows_total_after"][current_sym] = int(m.group(1))
    return out


def _parse_stage90_candidate_metrics(path: Path, candidate: str | None) -> dict[str, Any]:
    out = {"candidate": candidate, "stage90_recent": None, "stage90_wf": None, "anomaly": False}
    if not path.exists() or not candidate:
        return out
    prefix = f"- {candidate}:"
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.startswith(prefix):
            continue
        recent_m = re.search(r"近2年\s*收益=([-+0-9.]+)%", line)
        wf_m = re.search(r"WF样本外\s*收益=([-+0-9.]+)%", line)
        if recent_m:
            out["stage90_recent"] = float(recent_m.group(1))
        if wf_m:
            out["stage90_wf"] = float(wf_m.group(1))
        break
    return out


def _remove_stale_runtime(root: Path) -> dict[str, Any]:
    removed: list[str] = []
    paths = [
        root / ".runtime" / "okx_demo_autopilot_state.json",
        root / ".runtime" / "okx_demo_shadow_exec_latest.json",
        root / ".runtime" / "okx_demo_shadow_exec_latest.jsonl",
        root / ".runtime" / "okx_demo_shadow_exec_latest.txt",
        root / ".branch_shortwave_demo" / "workspace" / ".runtime" / "okx_demo_autopilot_state.json",
        root / ".branch_shortwave_demo" / "workspace" / ".runtime" / "okx_demo_shadow_exec_latest.json",
        root / ".branch_shortwave_demo" / "workspace" / ".runtime" / "okx_demo_shadow_exec_latest.jsonl",
        root / ".branch_shortwave_demo" / "workspace" / ".runtime" / "okx_demo_shadow_exec_latest.txt",
        Path.home() / "Downloads" / "okx_demo_report_latest.txt",
        Path.home() / "Downloads" / "branch_demo_report_latest.txt",
    ]
    for p in paths:
        try:
            if p.exists() or p.is_symlink():
                p.unlink()
                removed.append(str(p))
        except IsADirectoryError:
            shutil.rmtree(p, ignore_errors=True)
            removed.append(str(p))
        except Exception:
            pass
    return {"removed": removed}


def _fmt_symbol(sym: str, summary: dict[str, Any]) -> str:
    return (
        f"- {sym.upper()}: rows={summary.get('rows')} start={summary.get('start')} end={summary.get('end')} "
        f"dupes={summary.get('dupes')} non15m_gaps={summary.get('non15m_gaps')} max_gap={summary.get('max_gap')}"
    )


def _write_outputs(root: Path, payload: dict[str, Any]) -> tuple[Path, Path, Path]:
    reports = root / "reports" / "research_raw"
    reports.mkdir(parents=True, exist_ok=True)
    downloads = Path.home() / "Downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    txt_path = reports / "stage177_runtime_row_truth_and_gap_guard_latest.txt"
    json_path = reports / "stage177_runtime_row_truth_and_gap_guard_latest.json"
    zip_path = downloads / "stage177_runtime_row_truth_and_gap_guard_latest.zip"

    lines: list[str] = []
    lines.append("Stage177 runtime 行数真相同步 + BTC 缺口补齐 + 系统稳定性确认")
    lines.append("")
    lines.append("[raw_after]")
    for sym in ["btc", "bnb", "eth", "sol"]:
        lines.append(_fmt_symbol(sym, payload["raw_after"][sym]))
    lines.append("")
    lines.append("[btc_gap_fill]")
    lines.append(json.dumps(payload.get("btc_gap_fill", {}), ensure_ascii=False, indent=2))
    lines.append("")
    lines.append("[runtime_reports]")
    lines.append(json.dumps(payload.get("runtime_reports", {}), ensure_ascii=False, indent=2))
    lines.append("")
    lines.append("[research_runtime_mainline_drift]")
    lines.append(json.dumps(payload.get("research_runtime_mainline_drift", {}), ensure_ascii=False, indent=2))
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
        okx = Path.home() / "Downloads" / "okx_demo_report_latest.txt"
        branch = Path.home() / "Downloads" / "branch_demo_report_latest.txt"
        if okx.exists():
            zf.write(okx, arcname=okx.name)
        if branch.exists():
            zf.write(branch, arcname=branch.name)
    return txt_path, json_path, zip_path


def main() -> int:
    ap = argparse.ArgumentParser(description="修 runtime 行数真相、尝试补 BTC 历史缺口、重启 demo 并校验同步")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--no-restart", action="store_true", help="只审计/修 raw，不重启 demo")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    downloads = Path.home() / "Downloads"
    downloads.mkdir(parents=True, exist_ok=True)

    raw_before = {sym: _audit_csv(root / "data" / "raw" / f"{sym}_15m.csv") for sym in ["btc", "bnb", "eth", "sol"]}
    btc_gap_fill = _attempt_gap_fill(root, "btc", raw_before["btc"]) if int(raw_before["btc"].get("non15m_gaps") or 0) > 0 else {"attempted": False, "reason": "btc_no_gap"}

    repair_main = _run_cmd([str(root / ".venv" / "bin" / "python"), "-m", "tools.repair_raw_from_snapshots", "--project-dir", ".", "--config", "config.yml"], root)
    repair_branch = _run_cmd([str(root / ".venv" / "bin" / "python"), "-m", "tools.repair_raw_from_snapshots", "--project-dir", ".", "--config", "config_shortwave_triple_book_stage133.yml"], root)
    guard_main = _run_cmd([str(root / ".venv" / "bin" / "python"), "-m", "tools.raw_data_guard", "--project-dir", ".", "--config", "config.yml"], root)
    guard_branch = _run_cmd([str(root / ".venv" / "bin" / "python"), "-m", "tools.raw_data_guard", "--project-dir", ".", "--config", "config_shortwave_triple_book_stage133.yml"], root)

    if not args.no_restart:
        _run_cmd(["bash", "pause_okx_demo.sh"], root)
        _run_cmd(["bash", "pause_branch_demo.sh"], root)
        stale = _remove_stale_runtime(root)
        start_main = _run_cmd(["bash", "start_okx_demo.sh"], root)
        start_branch = _run_cmd(["bash", "start_branch_demo.sh"], root)
        wait_main = _wait_for_report(downloads / "okx_demo_report_latest.txt", timeout_s=120)
        wait_branch = _wait_for_report(downloads / "branch_demo_report_latest.txt", timeout_s=120)
    else:
        stale = {"removed": []}
        start_main = {"skipped": True}
        start_branch = {"skipped": True}
        wait_main = False
        wait_branch = False

    raw_after = {sym: _audit_csv(root / "data" / "raw" / f"{sym}_15m.csv") for sym in ["btc", "bnb", "eth", "sol"]}
    okx_report = _parse_report(downloads / "okx_demo_report_latest.txt")
    branch_report = _parse_report(downloads / "branch_demo_report_latest.txt")

    runtime_row_check = {
        "BTC": {
            "raw_rows": int(raw_after["btc"].get("rows") or 0),
            "runtime_rows": int((okx_report.get("rows_total_after") or {}).get("BTC") or (branch_report.get("rows_total_after") or {}).get("BTC") or 0),
        },
        "BNB": {
            "raw_rows": int(raw_after["bnb"].get("rows") or 0),
            "runtime_rows": int((okx_report.get("rows_total_after") or {}).get("BNB") or 0),
        },
        "ETH": {
            "raw_rows": int(raw_after["eth"].get("rows") or 0),
            "runtime_rows": int((branch_report.get("rows_total_after") or {}).get("ETH") or 0),
        },
        "SOL": {
            "raw_rows": int(raw_after["sol"].get("rows") or 0),
            "runtime_rows": int((branch_report.get("rows_total_after") or {}).get("SOL") or 0),
        },
    }
    for item in runtime_row_check.values():
        item["anomaly"] = item["runtime_rows"] != item["raw_rows"]

    drift = _parse_stage90_candidate_metrics(root / "reports" / "research_raw" / "stage90_mainline_event_alpha_matrix_latest.txt", okx_report.get("candidate"))
    if okx_report.get("recent_ret") is not None and drift.get("stage90_recent") is not None:
        drift["recent_gap"] = round(float(okx_report["recent_ret"]) - float(drift["stage90_recent"]), 2)
    else:
        drift["recent_gap"] = None
    if okx_report.get("wf_ret") is not None and drift.get("stage90_wf") is not None:
        drift["wf_gap"] = round(float(okx_report["wf_ret"]) - float(drift["stage90_wf"]), 2)
    else:
        drift["wf_gap"] = None
    drift["anomaly"] = bool((drift.get("recent_gap") is not None and abs(float(drift["recent_gap"])) > 20.0) or (drift.get("wf_gap") is not None and abs(float(drift["wf_gap"])) > 20.0))

    raw_ok = all(int(raw_after[s].get("dupes") or 0) == 0 for s in ["btc", "bnb", "eth", "sol"]) and all(int(raw_after[s].get("non15m_gaps") or 0) == 0 for s in ["bnb", "eth", "sol"]) and int(raw_after["btc"].get("non15m_gaps") or 0) == 0
    runtime_row_ok = not any(v["anomaly"] for v in runtime_row_check.values())

    overall = {
        "raw_ok": raw_ok,
        "runtime_row_ok": runtime_row_ok,
        "guard_main_ok": int(guard_main.get("returncode", 1)) == 0,
        "guard_branch_ok": int(guard_branch.get("returncode", 1)) == 0,
        "mainline_research_runtime_drift": drift["anomaly"],
        "system_ready_for_new_frontier": bool(raw_ok and runtime_row_ok and int(guard_main.get("returncode", 1)) == 0 and int(guard_branch.get("returncode", 1)) == 0 and not drift["anomaly"]),
        "reports_ready": {"okx": bool(wait_main), "branch": bool(wait_branch)},
    }

    next_actions: list[str] = []
    if int(raw_after["btc"].get("non15m_gaps") or 0) > 0:
        next_actions.append("BTC 历史 15m 仍有非15m缺口；先不要继续刷 frontier。")
    if runtime_row_check["BTC"]["anomaly"]:
        next_actions.append("BTC runtime rows 仍短于 raw；先只处理 runtime 同步，不继续改策略。")
    if drift["anomaly"]:
        next_actions.append("stage90 latest 与当前主线公共报告严重漂移；stage90 latest 先视为实验结果，不当运行真相。")
    if overall["system_ready_for_new_frontier"]:
        next_actions.append("系统层通过；下一轮才继续做主线/分支 frontier。")
    else:
        next_actions.append("系统层未完全通过；先修稳定性/全面性，再谈策略创新。")

    payload: dict[str, Any] = {
        "title": "Stage177 runtime 行数真相同步 + BTC 缺口补齐 + 系统稳定性确认",
        "raw_before": raw_before,
        "btc_gap_fill": btc_gap_fill,
        "repair_main": repair_main,
        "repair_branch": repair_branch,
        "guard_main": guard_main,
        "guard_branch": guard_branch,
        "stale_cleanup": stale,
        "start_main": start_main,
        "start_branch": start_branch,
        "raw_after": raw_after,
        "runtime_reports": {"okx": okx_report, "branch": branch_report},
        "runtime_row_check": runtime_row_check,
        "research_runtime_mainline_drift": drift,
        "overall": overall,
        "next_actions": next_actions,
    }
    _, _, zip_path = _write_outputs(root, payload)
    print(f"OK -> {zip_path}")
    return 0 if overall["system_ready_for_new_frontier"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
