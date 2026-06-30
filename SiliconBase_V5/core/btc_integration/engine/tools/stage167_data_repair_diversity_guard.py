from __future__ import annotations

import argparse
import json
import re
import shutil
from collections import Counter
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import pandas as pd

_TIME_KEYS = ("time", "timestamp", "ts", "datetime", "date", "open_time")
CAND_RE = re.compile(
    r"^-\s*(?:(?P<asset>[A-Z]+)\s*\|\s*(?P<side>long|short|dual)\s*\|\s*)?(?P<name>[^:]+):.*?\|\s*6年\s*收益=(?P<full>[-+0-9.]+)%.*?\|\s*近2年\s*收益=(?P<recent>[-+0-9.]+)%.*?\|\s*WF样本外\s*收益=(?P<wf>[-+0-9.]+)%",
    re.IGNORECASE,
)


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or not path.is_file() or path.stat().st_size <= 0:
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def _find_time_col(df: pd.DataFrame) -> str:
    cols = {str(c).lower(): str(c) for c in df.columns}
    for key in _TIME_KEYS:
        if key in cols:
            return cols[key]
    raise ValueError(f"CSV 缺少时间列 | columns={list(df.columns)}")


def _align_columns(snapshot_df: pd.DataFrame, raw_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    if snapshot_df.empty and raw_df.empty:
        return snapshot_df, raw_df, "time"
    base = snapshot_df if not snapshot_df.empty else raw_df
    time_col = _find_time_col(base)
    if snapshot_df.empty:
        snapshot_df = pd.DataFrame(columns=list(raw_df.columns))
    if raw_df.empty:
        raw_df = pd.DataFrame(columns=list(snapshot_df.columns))

    snap_t = _find_time_col(snapshot_df) if not snapshot_df.empty else time_col
    raw_t = _find_time_col(raw_df) if not raw_df.empty else time_col
    if snap_t != time_col and not snapshot_df.empty:
        snapshot_df = snapshot_df.rename(columns={snap_t: time_col})
    if raw_t != time_col and not raw_df.empty:
        raw_df = raw_df.rename(columns={raw_t: time_col})

    if list(snapshot_df.columns) == list(raw_df.columns):
        return snapshot_df, raw_df, time_col

    ordered_cols: list[str] = list(dict.fromkeys([*snapshot_df.columns, *raw_df.columns]))
    snapshot_df = snapshot_df.reindex(columns=ordered_cols)
    raw_df = raw_df.reindex(columns=ordered_cols)
    return snapshot_df, raw_df, time_col


def _summarize(path: Path) -> dict[str, Any]:
    out: dict[str, Any] = {
        "exists": path.exists() and path.is_file(),
        "file": str(path),
        "rows": 0,
        "start": None,
        "end": None,
        "dupes": 0,
        "non15m_gaps": 0,
        "max_gap": None,
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
        out["rows"] = int(len(df))
        if df.empty:
            return out
        out["dupes"] = int(df.duplicated(subset=[time_col]).sum())
        idx = pd.DatetimeIndex(df[time_col]).sort_values()
        out["start"] = idx[0].strftime("%Y-%m-%d %H:%M:%S")
        out["end"] = idx[-1].strftime("%Y-%m-%d %H:%M:%S")
        diffs = pd.Series(idx).diff().dropna()
        if not diffs.empty:
            bad = diffs[diffs != pd.Timedelta(minutes=15)]
            out["non15m_gaps"] = int(len(bad))
            out["max_gap"] = str(diffs.max())
        else:
            out["max_gap"] = "0:15:00"
    except Exception as exc:
        out["error"] = str(exc)
    return out


def _dt(s: str | None) -> pd.Timestamp | None:
    if not s:
        return None
    try:
        return pd.Timestamp(s)
    except Exception:
        return None


def _needs_restore(raw: dict[str, Any], snap: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if not snap.get("exists") or int(snap.get("rows") or 0) <= 0:
        return reasons
    if not raw.get("exists") or int(raw.get("rows") or 0) <= 0:
        reasons.append("raw_missing_or_empty")
        return reasons
    raw_rows = int(raw.get("rows") or 0)
    snap_rows = int(snap.get("rows") or 0)
    if raw_rows < int(snap_rows * 0.95):
        reasons.append("rows_short")
    raw_end = _dt(raw.get("end"))
    snap_end = _dt(snap.get("end"))
    if raw_end is not None and snap_end is not None and raw_end < snap_end - pd.Timedelta(hours=1):
        reasons.append("end_older_than_snapshot")
    if int(raw.get("non15m_gaps") or 0) > int(snap.get("non15m_gaps") or 0):
        reasons.append("more_non15m_gaps_than_snapshot")
    if int(raw.get("dupes") or 0) > int(snap.get("dupes") or 0):
        reasons.append("more_dupes_than_snapshot")
    return reasons


def _merge_snapshot_with_tail(snapshot_path: Path, raw_path: Path) -> dict[str, Any]:
    snap_df = _read_csv(snapshot_path)
    raw_df = _read_csv(raw_path)
    snap_df, raw_df, time_col = _align_columns(snap_df, raw_df)

    if snap_df.empty and raw_df.empty:
        return {"changed": False, "reason": "both_empty", "rows": 0}
    if snap_df.empty:
        return {"changed": False, "reason": "snapshot_missing_or_empty", "rows": int(len(raw_df))}

    snap_ts = pd.to_datetime(snap_df[time_col], errors="coerce")
    raw_ts = pd.to_datetime(raw_df[time_col], errors="coerce") if not raw_df.empty else pd.Series(dtype="datetime64[ns]")
    snap_df = snap_df.loc[snap_ts.notna()].copy()
    snap_df[time_col] = pd.to_datetime(snap_df[time_col], errors="coerce")
    raw_df = raw_df.loc[raw_ts.notna()].copy() if not raw_df.empty else raw_df
    if not raw_df.empty:
        raw_df[time_col] = pd.to_datetime(raw_df[time_col], errors="coerce")

    if snap_df.empty:
        return {"changed": False, "reason": "snapshot_all_invalid_time", "rows": int(len(raw_df))}

    snap_max = pd.to_datetime(snap_df[time_col]).max()
    tail_df = raw_df.loc[pd.to_datetime(raw_df[time_col]) > snap_max].copy() if not raw_df.empty else raw_df
    merged = pd.concat([snap_df, tail_df], ignore_index=True)
    merged = merged.dropna(subset=[time_col]).drop_duplicates(subset=[time_col], keep="last").sort_values(time_col).reset_index(drop=True)

    out_df = merged.copy()
    out_df[time_col] = pd.to_datetime(out_df[time_col]).dt.strftime("%Y-%m-%d %H:%M:%S")

    raw_path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", newline="", suffix=".csv", dir=str(raw_path.parent), delete=False) as tmp:
        tmp_path = Path(tmp.name)
        out_df.to_csv(tmp, index=False)
    tmp_path.replace(raw_path)

    return {
        "changed": True,
        "reason": "snapshot_restored",
        "rows": int(len(out_df)),
        "snapshot_rows": int(len(snap_df)),
        "tail_rows": int(len(tail_df)),
        "first": str(out_df.iloc[0][time_col]) if len(out_df) else "-",
        "last": str(out_df.iloc[-1][time_col]) if len(out_df) else "-",
    }


def _parse_pct(text: str) -> float:
    try:
        return float(str(text).replace('%', '').strip())
    except Exception:
        return 0.0


def _family(name: str) -> str:
    low = name.strip().lower()
    parts = [p for p in low.split('_') if p]
    if len(parts) >= 2:
        return '_'.join(parts[:2])
    return low


def _scan_candidates(txt_path: Path, top_n: int) -> dict[str, Any]:
    if not txt_path.exists():
        return {
            "file": str(txt_path),
            "exists": False,
            "dead_full_zero": [],
            "dead_recent_wf_zero": [],
            "top_names": [],
            "family_counter": {},
            "dominant_family": None,
            "dominant_ratio": 0.0,
        }
    items: list[dict[str, Any]] = []
    for line in txt_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = CAND_RE.match(line.strip())
        if not m:
            continue
        name = (m.group("name") or "").strip()
        full = _parse_pct(m.group("full"))
        recent = _parse_pct(m.group("recent"))
        wf = _parse_pct(m.group("wf"))
        items.append({
            "name": name,
            "full": full,
            "recent": recent,
            "wf": wf,
            "family": _family(name),
        })
    dead_full_zero = [x["name"] for x in items if abs(x["full"]) < 1e-9 and abs(x["recent"]) < 1e-9 and abs(x["wf"]) < 1e-9]
    dead_recent_wf_zero = [x["name"] for x in items if abs(x["recent"]) < 1e-9 and abs(x["wf"]) < 1e-9]
    top = items[:top_n]
    fam = Counter(x["family"] for x in top)
    dom_family, dom_count = (None, 0)
    if fam:
        dom_family, dom_count = fam.most_common(1)[0]
    return {
        "file": str(txt_path),
        "exists": True,
        "dead_full_zero": dead_full_zero,
        "dead_recent_wf_zero": dead_recent_wf_zero,
        "top_names": [x["name"] for x in top],
        "family_counter": dict(fam),
        "dominant_family": dom_family,
        "dominant_ratio": round(dom_count / max(len(top), 1), 4),
    }


def _fmt_symbol(sym: str, summary: dict[str, Any]) -> str:
    return (
        f"- {sym.upper()}: exists={summary.get('exists')} rows={summary.get('rows')} "
        f"start={summary.get('start')} end={summary.get('end')} dupes={summary.get('dupes')} "
        f"non15m_gaps={summary.get('non15m_gaps')} max_gap={summary.get('max_gap')}"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="修数据 + 查死模板 + 查局部最优塌缩")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    reports = root / "reports" / "research_raw"
    reports.mkdir(parents=True, exist_ok=True)

    raw_dir = root / "data" / "raw"
    snap_dir = root / "data" / "raw_snapshots"
    symbols = ["btc", "bnb", "eth", "sol"]

    raw_before = {sym: _summarize(raw_dir / f"{sym}_15m.csv") for sym in symbols}
    snap_summary = {sym: _summarize(snap_dir / f"{sym}_15m.best.csv") for sym in symbols}

    repairs: dict[str, Any] = {}
    for sym in symbols:
        raw_path = raw_dir / f"{sym}_15m.csv"
        snap_path = snap_dir / f"{sym}_15m.best.csv"
        reasons = _needs_restore(raw_before[sym], snap_summary[sym])
        if reasons:
            backup = raw_path.with_suffix(raw_path.suffix + ".pre_stage167_backup")
            if raw_path.exists() and not backup.exists():
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(raw_path, backup)
            merge = _merge_snapshot_with_tail(snap_path, raw_path)
            repairs[sym] = {
                "repaired": True,
                "reason": ",".join(reasons),
                "backup": str(backup),
                "snapshot_rows": snap_summary[sym].get("rows", 0),
                "raw_rows": raw_before[sym].get("rows", 0),
                **merge,
            }
        else:
            repairs[sym] = {
                "repaired": False,
                "reason": "no_restore_needed",
                "snapshot_rows": snap_summary[sym].get("rows", 0),
                "raw_rows": raw_before[sym].get("rows", 0),
            }

    raw_after = {sym: _summarize(raw_dir / f"{sym}_15m.csv") for sym in symbols}

    main_scan = _scan_candidates(reports / "stage90_mainline_event_alpha_matrix_latest.txt", top_n=6)
    branch_scan = _scan_candidates(reports / "stage91_branch_event_alpha_matrix_latest.txt", top_n=12)

    payload = {
        "title": "Stage167 数据 / 死模板 / 局部最优 审计修复",
        "raw_before": raw_before,
        "snapshot_summary": snap_summary,
        "repairs": repairs,
        "raw_after": raw_after,
        "dead_main": {
            "dead_full_zero": main_scan.get("dead_full_zero", []),
            "dead_recent_wf_zero": main_scan.get("dead_recent_wf_zero", []),
        },
        "dead_branch": {
            "dead_full_zero": branch_scan.get("dead_full_zero", []),
            "dead_recent_wf_zero": branch_scan.get("dead_recent_wf_zero", []),
        },
        "main_collapse": {
            "top_names": main_scan.get("top_names", []),
            "family_counter": main_scan.get("family_counter", {}),
            "dominant_family": main_scan.get("dominant_family"),
            "dominant_ratio": main_scan.get("dominant_ratio", 0.0),
        },
        "branch_collapse": {
            "top_names": branch_scan.get("top_names", []),
            "family_counter": branch_scan.get("family_counter", {}),
            "dominant_family": branch_scan.get("dominant_family"),
            "dominant_ratio": branch_scan.get("dominant_ratio", 0.0),
        },
        "next_actions": [
            "主线先冻结 mainline_live_dynlev_fix8_lock18，不再回切 legacy live_base。",
            "分支先冻结 ETH reclaim 当前 active，不再继续全图乱扫。",
            "下一轮 frontier 必须先剔除 full_zero 和 recent+wf 双零模板。",
            "下一轮 frontier 必须加 family diversity cap，避免 ETH reclaim 单一盆地挤占全部名额。",
            "若 BNB snapshot 明显更干净，优先继续用 snapshot+tail，主线再刷。",
        ],
    }

    txt_lines: list[str] = []
    txt_lines.append(payload["title"])
    txt_lines.append("")
    txt_lines.append("[raw_before]")
    for sym in symbols:
        txt_lines.append(_fmt_symbol(sym, raw_before[sym]))
    txt_lines.append("")
    txt_lines.append("[repairs]")
    for sym in symbols:
        txt_lines.append(f"- {sym.upper()}: {json.dumps(repairs[sym], ensure_ascii=False)}")
    txt_lines.append("")
    txt_lines.append("[raw_after]")
    for sym in symbols:
        txt_lines.append(_fmt_symbol(sym, raw_after[sym]))
    txt_lines.append("")
    txt_lines.append("[dead_main]")
    txt_lines.append(json.dumps(payload["dead_main"], ensure_ascii=False, indent=2))
    txt_lines.append("")
    txt_lines.append("[dead_branch]")
    txt_lines.append(json.dumps(payload["dead_branch"], ensure_ascii=False, indent=2))
    txt_lines.append("")
    txt_lines.append("[main_collapse]")
    txt_lines.append(json.dumps(payload["main_collapse"], ensure_ascii=False, indent=2))
    txt_lines.append("")
    txt_lines.append("[branch_collapse]")
    txt_lines.append(json.dumps(payload["branch_collapse"], ensure_ascii=False, indent=2))
    txt_lines.append("")
    txt_lines.append("[next_actions]")
    for x in payload["next_actions"]:
        txt_lines.append(f"- {x}")
    txt_lines.append("")

    txt_path = reports / "stage167_data_repair_diversity_guard_latest.txt"
    json_path = reports / "stage167_data_repair_diversity_guard_latest.json"
    txt_path.write_text("\n".join(txt_lines), encoding="utf-8")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(txt_path)
    print(json_path)


if __name__ == "__main__":
    main()
