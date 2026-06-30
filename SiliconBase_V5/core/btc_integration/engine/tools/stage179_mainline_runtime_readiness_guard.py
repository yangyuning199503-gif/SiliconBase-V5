from __future__ import annotations

import argparse
import json
import os
import subprocess
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd

TIME_KEYS = ("time", "timestamp", "ts", "datetime", "date", "open_time")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        if path.exists() and path.is_file():
            data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


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
    }
    if not out["exists"] or path.stat().st_size <= 0:
        return out
    try:
        df = _read_csv(path)
        if df.empty:
            return out
        time_col = _find_time_col(df)
        ts = pd.to_datetime(df[time_col], errors="coerce")
        idx = pd.DatetimeIndex(ts[ts.notna()]).sort_values()
        if len(idx) == 0:
            return out
        out["rows"] = int(len(idx))
        out["dupes"] = int(pd.Series(idx).duplicated().sum())
        out["start"] = idx[0].strftime("%Y-%m-%d %H:%M:%S")
        out["end"] = idx[-1].strftime("%Y-%m-%d %H:%M:%S")
        diffs = pd.Series(idx).diff().dropna()
        if not diffs.empty:
            out["non15m_gaps"] = int((diffs != pd.Timedelta(minutes=15)).sum())
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def _run_precheck(root: Path, python_bin: Path) -> dict[str, Any]:
    runtime_dir = root / ".runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["OKX_PRECHECK_NO_SUBMIT"] = "1"
    env["OKX_AUTOPILOT_MODE"] = "1"
    env["OKX_AUTOPILOT_RUNTIME_DIR"] = str(runtime_dir)
    env.setdefault("OKX_COINGLASS_ENFORCEMENT", "shadow_only")
    cmd = [str(python_bin), "-u", "-m", "tools.okx_demo_shadow_exec", "--project-dir", str(root), "--confirm-demo"]
    try:
        proc = subprocess.run(cmd, cwd=str(root), env=env, capture_output=True, text=True, timeout=240, check=False)
        rep = _load_json(runtime_dir / "okx_demo_shadow_exec_latest.json")
        return {
            "cmd": cmd,
            "returncode": proc.returncode,
            "stdout_tail": "\n".join(proc.stdout.splitlines()[-20:]),
            "stderr_tail": "\n".join(proc.stderr.splitlines()[-20:]),
            "report": rep,
        }
    except subprocess.TimeoutExpired as exc:
        rep = _load_json(runtime_dir / "okx_demo_shadow_exec_latest.json")
        return {
            "cmd": cmd,
            "returncode": -9,
            "stdout_tail": str(getattr(exc, "stdout", "") or "")[-2000:],
            "stderr_tail": (str(getattr(exc, "stderr", "") or "") + "\nprecheck_timeout=240s")[-2000:],
            "report": rep,
            "timed_out": True,
        }


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage179 主线 runtime 稳定性/全面性快速预检（无下单）")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    python_bin = root / ".venv" / "bin" / "python"
    if not python_bin.exists():
        raise SystemExit("缺少 .venv/bin/python")

    raw = {
        "BTC": _audit_csv(root / "data" / "raw" / "btc_15m.csv"),
        "BNB": _audit_csv(root / "data" / "raw" / "bnb_15m.csv"),
        "ETH": _audit_csv(root / "data" / "raw" / "eth_15m.csv"),
        "SOL": _audit_csv(root / "data" / "raw" / "sol_15m.csv"),
    }
    raw_ok = all((v.get("exists") and int(v.get("rows") or 0) > 0 and int(v.get("dupes") or 0) == 0 and int(v.get("non15m_gaps") or 0) == 0) for v in raw.values())

    precheck = _run_precheck(root, python_bin)
    rep = precheck.get("report") if isinstance(precheck.get("report"), dict) else {}
    account_cfg = rep.get("account_config") if isinstance(rep.get("account_config"), dict) else {}
    symbols = rep.get("symbols") if isinstance(rep.get("symbols"), dict) else {}
    data_sync = rep.get("data_sync") if isinstance(rep.get("data_sync"), dict) else {}

    symbol_rows = {sym.upper(): int((sync or {}).get("rows_total_after") or 0) for sym, sync in data_sync.items() if isinstance(sync, dict)}
    expected_rows = {sym: int(raw[sym].get("rows") or 0) for sym in raw}
    main_rows_ok = symbol_rows.get("BTC") == expected_rows.get("BTC") and symbol_rows.get("BNB") == expected_rows.get("BNB")
    account_ok = bool(account_cfg.get("ok"))
    symbols_ok = bool(symbols)
    precheck_ok = bool(rep.get("ok")) and account_ok and symbols_ok and main_rows_ok

    summary = {
        "title": "Stage179 主线 runtime 稳定性/全面性快速预检（无下单）",
        "raw": raw,
        "precheck": {
            "returncode": precheck.get("returncode"),
            "timed_out": bool(precheck.get("timed_out")),
            "stdout_tail": precheck.get("stdout_tail", ""),
            "stderr_tail": precheck.get("stderr_tail", ""),
            "report_ok": bool(rep.get("ok")),
            "reason": str(rep.get("reason", "") or ""),
            "plan_version": str(rep.get("plan_version", "") or ""),
            "signal_time": str(rep.get("signal_time", "") or ""),
            "account_config_ok": bool(account_cfg.get("ok")),
            "account_config_endpoint_ok": bool(account_cfg.get("endpoint_ok", account_cfg.get("ok"))),
            "account_config_used_cache": bool(account_cfg.get("used_cache")),
            "position_mode": str(rep.get("position_mode", "") or ""),
            "symbols_present": sorted([str(k).upper() for k in symbols]),
            "symbol_rows": symbol_rows,
            "main_rows_ok": main_rows_ok,
        },
        "overall": {
            "raw_ok": raw_ok,
            "precheck_ok": precheck_ok,
            "system_ready_for_frontier": raw_ok and precheck_ok,
        },
        "next_actions": [],
    }

    if not raw_ok:
        summary["next_actions"].append("raw 仍有缺口/重复；先修数据，再谈策略。")
    if raw_ok and not precheck_ok:
        summary["next_actions"].append("主线 runtime 仍未完全通过；继续只修运行层，不动策略层。")
    if raw_ok and precheck_ok:
        summary["next_actions"].append("系统层已过主线快速预检；可以继续做 frontier/策略创新。")

    dl = Path.home() / "Downloads"
    txt_path = dl / "stage179_mainline_runtime_readiness_latest.txt"
    json_path = dl / "stage179_mainline_runtime_readiness_latest.json"
    zip_path = dl / "stage179_mainline_runtime_readiness_latest.zip"

    lines = [summary["title"], "", "[raw]"]
    for sym in ["BTC", "BNB", "ETH", "SOL"]:
        item = raw[sym]
        lines.append(
            f"- {sym}: rows={item.get('rows')} start={item.get('start')} end={item.get('end')} dupes={item.get('dupes')} non15m_gaps={item.get('non15m_gaps')}"
        )
    lines.extend([
        "",
        "[precheck]",
        f"- returncode: {summary['precheck']['returncode']}",
        f"- report_ok: {summary['precheck']['report_ok']}",
        f"- reason: {summary['precheck']['reason'] or '-'}",
        f"- account_config_ok: {summary['precheck']['account_config_ok']}",
        f"- account_config_endpoint_ok: {summary['precheck']['account_config_endpoint_ok']}",
        f"- account_config_used_cache: {summary['precheck']['account_config_used_cache']}",
        f"- position_mode: {summary['precheck']['position_mode'] or '-'}",
        f"- symbols_present: {','.join(summary['precheck']['symbols_present']) or '-'}",
        f"- BTC rows_total_after: {summary['precheck']['symbol_rows'].get('BTC', 0)}",
        f"- BNB rows_total_after: {summary['precheck']['symbol_rows'].get('BNB', 0)}",
        f"- main_rows_ok: {summary['precheck']['main_rows_ok']}",
        "",
        "[overall]",
        json.dumps(summary['overall'], ensure_ascii=False, indent=2),
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

    print(json.dumps({"ok": True, "zip": str(zip_path), "summary": summary["overall"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
