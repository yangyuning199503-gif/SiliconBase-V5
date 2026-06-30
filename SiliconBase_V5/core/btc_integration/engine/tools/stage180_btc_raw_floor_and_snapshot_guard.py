
from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import subprocess
import time
import zipfile
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import pandas as pd

try:
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore

TIME_KEYS = ("time", "timestamp", "ts", "datetime", "date", "open_time")
BAR_MS = 15 * 60 * 1000


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


def _norm_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])
    time_col = _find_time_col(df)
    df = df.copy()
    if time_col != "time":
        df = df.rename(columns={time_col: "time"})
    need = ["time", "open", "high", "low", "close", "volume"]
    for col in need:
        if col not in df.columns:
            df[col] = pd.NA
    df = df[need]
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    df = df.dropna(subset=["time"]).sort_values("time").drop_duplicates("time", keep="last").reset_index(drop=True)
    if not df.empty:
        df["time"] = df["time"].dt.strftime("%Y-%m-%d %H:%M:%S")
    return df


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
        df = _norm_df(_read_csv(path))
        if df.empty:
            return out
        idx = pd.DatetimeIndex(pd.to_datetime(df["time"], errors="coerce")).sort_values()
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
                gaps.append(
                    {
                        "prev_ts": prev_t.strftime("%Y-%m-%d %H:%M:%S"),
                        "next_ts": cur_t.strftime("%Y-%m-%d %H:%M:%S"),
                        "gap": str(cur_t - prev_t),
                        "missing_bars": missing,
                    }
                )
            out["gaps"] = gaps
        else:
            out["max_gap"] = "0 days 00:15:00"
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def _parse_ts(s: str | None) -> pd.Timestamp:
    if not s:
        return pd.Timestamp("1970-01-01 00:00:00")
    try:
        ts = pd.Timestamp(s)
        if ts.tzinfo is not None:
            ts = ts.tz_convert(None)
        return ts
    except Exception:
        return pd.Timestamp("1970-01-01 00:00:00")


def _quality(meta: dict[str, Any]) -> tuple[int, int, int, float]:
    rows = int(meta.get("rows") or 0)
    gaps = int(meta.get("non15m_gaps") or 0)
    end = int(_parse_ts(meta.get("end")).timestamp())
    score = (1 if gaps == 0 and rows > 0 else 0, rows, end, -float(gaps))
    return score


def _write_df_atomic(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", newline="", suffix=".csv", dir=str(path.parent), delete=False) as tmp:
        tmp_path = Path(tmp.name)
        df.to_csv(tmp, index=False)
    tmp_path.replace(path)


def _candidate_paths(root: Path) -> list[Path]:
    raw_path = root / "data" / "raw" / "btc_15m.csv"
    snap_path = root / "data" / "raw_snapshots" / "btc_15m.best.csv"
    raw_dir = raw_path.parent
    cands: list[Path] = []
    for p in [
        raw_path,
        snap_path,
        *sorted(raw_dir.glob("btc_15m.csv.pre_stage*")),
        *sorted(raw_dir.glob("btc_15m.csv.*backup*")),
        *sorted(raw_dir.glob("btc_15m.csv*.bak*")),
    ]:
        if p not in cands and p.exists():
            cands.append(p)
    return cands


def _union_candidates(paths: list[Path]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for p in paths:
        df = _norm_df(_read_csv(p))
        if not df.empty:
            df["_source"] = str(p)
            frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])
    merged = pd.concat(frames, ignore_index=True)
    merged["time"] = pd.to_datetime(merged["time"], errors="coerce")
    merged = merged.dropna(subset=["time"]).sort_values(["time", "_source"]).drop_duplicates("time", keep="last").reset_index(drop=True)
    merged = merged.drop(columns=["_source"], errors="ignore")
    merged["time"] = merged["time"].dt.strftime("%Y-%m-%d %H:%M:%S")
    return merged


def _binance_fetch_range(start_ms: int, end_ms: int) -> pd.DataFrame:
    if requests is None or end_ms < start_ms:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])
    base = "https://fapi.binance.com/fapi/v1/klines"
    cur = start_ms
    rows: list[dict[str, Any]] = []
    sess = requests.Session()
    while cur <= end_ms:
        params = {
            "symbol": "BTCUSDT",
            "interval": "15m",
            "startTime": cur,
            "endTime": end_ms,
            "limit": 1500,
        }
        resp = sess.get(base, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list) or not data:
            break
        last_open = None
        for r in data:
            ot = int(r[0])
            last_open = ot
            if ot < start_ms or ot > end_ms:
                continue
            rows.append(
                {
                    "time": pd.Timestamp.utcfromtimestamp(ot / 1000).strftime("%Y-%m-%d %H:%M:%S"),
                    "open": float(r[1]),
                    "high": float(r[2]),
                    "low": float(r[3]),
                    "close": float(r[4]),
                    "volume": float(r[5]),
                }
            )
        if last_open is None:
            break
        nxt = last_open + BAR_MS
        if nxt <= cur:
            break
        cur = nxt
        time.sleep(0.10)
    if not rows:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])
    df = pd.DataFrame(rows).drop_duplicates("time").sort_values("time").reset_index(drop=True)
    return df


def _fill_gaps_and_tail(df: pd.DataFrame, target_end: pd.Timestamp) -> tuple[pd.DataFrame, dict[str, Any]]:
    info: dict[str, Any] = {"gap_segments": [], "tail_fetch": None, "fetched_rows": 0, "fetch_errors": []}
    if df.empty:
        return df, info
    work = _norm_df(df)
    idx = pd.DatetimeIndex(pd.to_datetime(work["time"]))
    diffs = pd.Series(idx).diff().dropna()
    exp = pd.Timedelta(minutes=15)
    segments: list[pd.DataFrame] = []
    bad = diffs[diffs != exp]
    for i in bad.index.tolist():
        prev_t = idx[i - 1]
        cur_t = idx[i]
        start_ts = prev_t + exp
        end_ts = cur_t - exp
        if end_ts < start_ts:
            continue
        try:
            seg = _binance_fetch_range(int(start_ts.timestamp() * 1000), int(end_ts.timestamp() * 1000))
            info["gap_segments"].append(
                {
                    "start": start_ts.strftime("%Y-%m-%d %H:%M:%S"),
                    "end": end_ts.strftime("%Y-%m-%d %H:%M:%S"),
                    "rows": int(len(seg)),
                }
            )
            info["fetched_rows"] += int(len(seg))
            if not seg.empty:
                segments.append(seg)
        except Exception as exc:
            info["fetch_errors"].append(f"gap_fetch:{type(exc).__name__}:{exc}")

    cur_end = idx[-1]
    if target_end > cur_end:
        start_ts = cur_end + exp
        end_ts = target_end
        try:
            tail = _binance_fetch_range(int(start_ts.timestamp() * 1000), int(end_ts.timestamp() * 1000))
            info["tail_fetch"] = {
                "start": start_ts.strftime("%Y-%m-%d %H:%M:%S"),
                "end": end_ts.strftime("%Y-%m-%d %H:%M:%S"),
                "rows": int(len(tail)),
            }
            info["fetched_rows"] += int(len(tail))
            if not tail.empty:
                segments.append(tail)
        except Exception as exc:
            info["fetch_errors"].append(f"tail_fetch:{type(exc).__name__}:{exc}")

    if segments:
        work = _norm_df(pd.concat([work] + segments, ignore_index=True))
    return work, info


def _maybe_refresh_snapshot(root: Path, raw_path: Path) -> dict[str, Any]:
    snap_path = root / "data" / "raw_snapshots" / "btc_15m.best.csv"
    out = {"updated": False, "snapshot": str(snap_path)}
    raw_a = _audit_csv(raw_path)
    snap_a = _audit_csv(snap_path)
    if _quality(raw_a) > _quality(snap_a):
        if snap_path.exists():
            backup = snap_path.with_suffix(snap_path.suffix + ".pre_stage180_backup")
            if not backup.exists():
                shutil.copy2(snap_path, backup)
                out["backup"] = str(backup)
        shutil.copy2(raw_path, snap_path)
        out["updated"] = True
        out["snapshot_rows"] = raw_a.get("rows")
    else:
        out["snapshot_rows"] = snap_a.get("rows")
    return out


def _restore_btc(root: Path, peer_rows: int, peer_end: str | None) -> dict[str, Any]:
    raw_path = root / "data" / "raw" / "btc_15m.csv"
    before = _audit_csv(raw_path)
    cands = _candidate_paths(root)
    cand_meta = [{"path": str(p), "audit": _audit_csv(p)} for p in cands]
    union_df = _union_candidates(cands)
    if union_df.empty:
        return {
            "before": before,
            "candidates": cand_meta,
            "changed": False,
            "reason": "no_candidate_source",
            "after": before,
        }

    target_end_ts = _parse_ts(peer_end) if peer_end else _parse_ts(before.get("end"))
    if target_end_ts <= pd.Timestamp("1970-01-02"):
        target_end_ts = pd.Timestamp.utcnow().floor("15min").tz_localize(None) - pd.Timedelta(minutes=15)
    repaired_df, fetch_info = _fill_gaps_and_tail(union_df, target_end_ts)

    changed = True
    if raw_path.exists():
        old_df = _norm_df(_read_csv(raw_path))
        changed = not old_df.equals(repaired_df)

    if changed:
        backup = raw_path.with_suffix(raw_path.suffix + ".pre_stage180_backup")
        if raw_path.exists() and not backup.exists():
            shutil.copy2(raw_path, backup)
        _write_df_atomic(raw_path, repaired_df)
    after = _audit_csv(raw_path)
    snapshot_refresh = _maybe_refresh_snapshot(root, raw_path)

    floor_ok = int(after.get("rows") or 0) >= int(peer_rows or 0) - 12 if peer_rows else True
    gaps_ok = int(after.get("non15m_gaps") or 0) == 0
    return {
        "before": before,
        "candidates": cand_meta,
        "union_rows": int(len(union_df)),
        "fetch_info": fetch_info,
        "changed": changed,
        "after": after,
        "peer_rows": int(peer_rows or 0),
        "peer_end": peer_end,
        "floor_ok": floor_ok,
        "gaps_ok": gaps_ok,
        "snapshot_refresh": snapshot_refresh,
    }


def _run_cmd(cmd: list[str], cwd: Path, env: dict[str, str] | None = None, timeout: int | None = None) -> dict[str, Any]:
    try:
        proc = subprocess.run(cmd, cwd=str(cwd), env=env, capture_output=True, text=True, timeout=timeout, check=False)
        return {
            "cmd": cmd,
            "returncode": proc.returncode,
            "stdout_tail": "\n".join(proc.stdout.splitlines()[-20:]),
            "stderr_tail": "\n".join(proc.stderr.splitlines()[-20:]),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "cmd": cmd,
            "returncode": -9,
            "stdout_tail": str(getattr(exc, "stdout", "") or "")[-2000:],
            "stderr_tail": str(getattr(exc, "stderr", "") or "")[-2000:],
            "timed_out": True,
        }
    except Exception as exc:
        return {"cmd": cmd, "returncode": -999, "error": f"{type(exc).__name__}: {exc}"}


def _load_json(path: Path) -> dict[str, Any]:
    try:
        if path.exists() and path.is_file():
            data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def _run_precheck(root: Path, python_bin: Path) -> dict[str, Any]:
    runtime_dir = root / ".runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["OKX_PRECHECK_NO_SUBMIT"] = "1"
    env["OKX_AUTOPILOT_MODE"] = "1"
    env["OKX_AUTOPILOT_RUNTIME_DIR"] = str(runtime_dir)
    env.setdefault("OKX_COINGLASS_ENFORCEMENT", "shadow_only")
    cmd = [str(python_bin), "-u", "-m", "tools.okx_demo_shadow_exec", "--project-dir", str(root), "--confirm-demo"]
    rep_before = runtime_dir / "okx_demo_shadow_exec_latest.json"
    if rep_before.exists():
        with contextlib.suppress(Exception):
            rep_before.unlink()
    proc = _run_cmd(cmd, root, env=env, timeout=300)
    rep = _load_json(runtime_dir / "okx_demo_shadow_exec_latest.json")
    account_cfg = rep.get("account_config") if isinstance(rep.get("account_config"), dict) else {}
    data_sync = rep.get("data_sync") if isinstance(rep.get("data_sync"), dict) else {}
    symbol_rows = {sym.upper(): int((sync or {}).get("rows_total_after") or 0) for sym, sync in data_sync.items() if isinstance(sync, dict)}
    return {
        **proc,
        "report": rep,
        "account_config_ok": bool(account_cfg.get("ok")),
        "symbol_rows": symbol_rows,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage180 BTC raw 地板保护 + 快照防回退 + 主线运行预检")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    python_bin = root / ".venv" / "bin" / "python"
    if not python_bin.exists():
        raise SystemExit("缺少 .venv/bin/python")

    raw_before = {
        "BTC": _audit_csv(root / "data" / "raw" / "btc_15m.csv"),
        "BNB": _audit_csv(root / "data" / "raw" / "bnb_15m.csv"),
        "ETH": _audit_csv(root / "data" / "raw" / "eth_15m.csv"),
        "SOL": _audit_csv(root / "data" / "raw" / "sol_15m.csv"),
    }
    peer_rows = int(raw_before["ETH"].get("rows") or 0)
    peer_end = raw_before["ETH"].get("end") or raw_before["BNB"].get("end")

    restore = _restore_btc(root, peer_rows=peer_rows, peer_end=peer_end)

    repair_main = _run_cmd([str(python_bin), "-m", "tools.repair_raw_from_snapshots", "--project-dir", ".", "--config", "config.yml"], root)
    repair_branch = _run_cmd([str(python_bin), "-m", "tools.repair_raw_from_snapshots", "--project-dir", ".", "--config", "config_shortwave_triple_book_stage133.yml"], root)
    guard_main = _run_cmd([str(python_bin), "-m", "tools.raw_data_guard", "--project-dir", ".", "--config", "config.yml"], root)
    guard_branch = _run_cmd([str(python_bin), "-m", "tools.raw_data_guard", "--project-dir", ".", "--config", "config_shortwave_triple_book_stage133.yml"], root)

    raw_after = {
        "BTC": _audit_csv(root / "data" / "raw" / "btc_15m.csv"),
        "BNB": _audit_csv(root / "data" / "raw" / "bnb_15m.csv"),
        "ETH": _audit_csv(root / "data" / "raw" / "eth_15m.csv"),
        "SOL": _audit_csv(root / "data" / "raw" / "sol_15m.csv"),
    }

    precheck = _run_precheck(root, python_bin)
    rep = precheck.get("report") if isinstance(precheck.get("report"), dict) else {}
    main_symbol_rows = precheck.get("symbol_rows") or {}
    main_rows_ok = main_symbol_rows.get("BTC") == int(raw_after["BTC"].get("rows") or 0) and main_symbol_rows.get("BNB") == int(raw_after["BNB"].get("rows") or 0)

    overall = {
        "btc_floor_ok": bool(restore.get("floor_ok")),
        "btc_gapfree_ok": bool(restore.get("gaps_ok")),
        "guard_main_ok": guard_main.get("returncode") == 0,
        "guard_branch_ok": guard_branch.get("returncode") == 0,
        "precheck_ok": bool(rep.get("ok")) and bool(precheck.get("account_config_ok")) and main_rows_ok,
    }
    overall["system_ready_for_live"] = all(overall.values())

    summary = {
        "title": "Stage180 BTC raw 地板保护 + 快照防回退 + 主线运行预检",
        "raw_before": raw_before,
        "restore": restore,
        "repair_main": repair_main,
        "repair_branch": repair_branch,
        "guard_main": guard_main,
        "guard_branch": guard_branch,
        "raw_after": raw_after,
        "precheck": {
            "returncode": precheck.get("returncode"),
            "account_config_ok": precheck.get("account_config_ok"),
            "report_ok": bool(rep.get("ok")),
            "reason": str(rep.get("reason", "") or ""),
            "plan_version": str(rep.get("plan_version", "") or ""),
            "signal_time": str(rep.get("signal_time", "") or ""),
            "main_symbol_rows": main_symbol_rows,
            "main_rows_ok": main_rows_ok,
            "stdout_tail": precheck.get("stdout_tail", ""),
            "stderr_tail": precheck.get("stderr_tail", ""),
        },
        "overall": overall,
        "next_actions": [],
    }

    if not overall["system_ready_for_live"]:
        if not overall["btc_floor_ok"] or not overall["btc_gapfree_ok"]:
            summary["next_actions"].append("BTC raw 仍未恢复到完整连续状态；先停在系统层。")
        if overall["btc_floor_ok"] and overall["btc_gapfree_ok"] and not overall["precheck_ok"]:
            summary["next_actions"].append("数据层已恢复，但主线 precheck 仍未完全通过；继续只修运行层。")
    else:
        summary["next_actions"].append("系统层已恢复；可以继续回测/模拟盘。")

    dl = Path.home() / "Downloads"
    txt_path = dl / "stage180_btc_raw_floor_and_snapshot_guard_latest.txt"
    json_path = dl / "stage180_btc_raw_floor_and_snapshot_guard_latest.json"
    zip_path = dl / "stage180_btc_raw_floor_and_snapshot_guard_latest.zip"

    lines = [summary["title"], "", "[raw_before]"]
    for sym in ["BTC", "BNB", "ETH", "SOL"]:
        item = raw_before[sym]
        lines.append(f"- {sym}: rows={item.get('rows')} start={item.get('start')} end={item.get('end')} dupes={item.get('dupes')} non15m_gaps={item.get('non15m_gaps')}")
    lines.extend([
        "",
        "[restore]",
        f"- changed: {restore.get('changed')}",
        f"- peer_rows(ETH): {restore.get('peer_rows')}",
        f"- union_rows: {restore.get('union_rows')}",
        f"- floor_ok: {restore.get('floor_ok')}",
        f"- gaps_ok: {restore.get('gaps_ok')}",
        f"- snapshot_updated: {((restore.get('snapshot_refresh') or {}).get('updated'))}",
    ])
    for item in (restore.get("candidates") or []):
        aud = item.get("audit") or {}
        lines.append(f"  - candidate: {item.get('path')} | rows={aud.get('rows')} end={aud.get('end')} gaps={aud.get('non15m_gaps')}")
    if (restore.get("fetch_info") or {}).get("gap_segments"):
        lines.append("  - gap_segments:")
        for seg in restore["fetch_info"]["gap_segments"]:
            lines.append(f"    * {seg['start']} -> {seg['end']} | rows={seg['rows']}")
    if (restore.get("fetch_info") or {}).get("tail_fetch"):
        tail = restore["fetch_info"]["tail_fetch"]
        lines.append(f"  - tail_fetch: {tail['start']} -> {tail['end']} | rows={tail['rows']}")
    if (restore.get("fetch_info") or {}).get("fetch_errors"):
        lines.append("  - fetch_errors:")
        for err in restore["fetch_info"]["fetch_errors"]:
            lines.append(f"    * {err}")
    lines.extend([
        "",
        "[raw_after]",
    ])
    for sym in ["BTC", "BNB", "ETH", "SOL"]:
        item = raw_after[sym]
        lines.append(f"- {sym}: rows={item.get('rows')} start={item.get('start')} end={item.get('end')} dupes={item.get('dupes')} non15m_gaps={item.get('non15m_gaps')}")
    lines.extend([
        "",
        "[precheck]",
        f"- returncode: {summary['precheck']['returncode']}",
        f"- account_config_ok: {summary['precheck']['account_config_ok']}",
        f"- report_ok: {summary['precheck']['report_ok']}",
        f"- reason: {summary['precheck']['reason'] or '-'}",
        f"- plan_version: {summary['precheck']['plan_version'] or '-'}",
        f"- signal_time: {summary['precheck']['signal_time'] or '-'}",
        f"- BTC rows_total_after: {summary['precheck']['main_symbol_rows'].get('BTC', 0)}",
        f"- BNB rows_total_after: {summary['precheck']['main_symbol_rows'].get('BNB', 0)}",
        f"- main_rows_ok: {summary['precheck']['main_rows_ok']}",
        "",
        "[overall]",
        json.dumps(summary["overall"], ensure_ascii=False, indent=2),
        "",
        "[next_actions]",
    ])
    for item in summary["next_actions"]:
        lines.append(f"- {item}")

    txt_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    runtime_json = root / ".runtime" / "okx_demo_shadow_exec_latest.json"
    runtime_txt = root / ".runtime" / "okx_demo_shadow_exec_latest.txt"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(txt_path, arcname=txt_path.name)
        zf.write(json_path, arcname=json_path.name)
        if runtime_json.exists():
            zf.write(runtime_json, arcname=runtime_json.name)
        if runtime_txt.exists():
            zf.write(runtime_txt, arcname=runtime_txt.name)

    print(json.dumps({"ok": True, "zip": str(zip_path), "overall": overall}, ensure_ascii=False))


if __name__ == "__main__":
    main()
