from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import zipfile
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

BAR_SECONDS = 15 * 60


@dataclass
class CsvScan:
    symbol: str
    file: str
    raw_rows: int
    parsed_rows: int
    min_time_utc: str | None
    max_time_utc: str | None
    ok: bool
    note: str


@dataclass
class PlanSummary:
    generated_at_utc: str
    mainline_keep_live: str
    mainline_shadow_1: str
    mainline_shadow_2: str
    branch_design: str
    branch_current_runtime: str
    branch_target_runtime: str
    branch_eth_keep: str
    branch_btc_keep: str
    branch_sol_status: str
    common_start_utc: str | None
    common_end_utc: str | None
    common_bars_15m: int
    common_days: float
    can_build_triple_book_preview: bool
    next_action: str


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _find_first_existing(paths: Iterable[Path]) -> Path | None:
    for p in paths:
        if p.exists():
            return p
    return None


def _extract_after_prefix(text: str, prefixes: Iterable[str]) -> str | None:
    for line in text.splitlines():
        s = line.strip()
        for prefix in prefixes:
            if s.startswith(prefix):
                return s.split(prefix, 1)[1].strip()
    return None


def _extract_candidate_from_line(text: str, key: str) -> str | None:
    # Supports lines like "- shadow_priority_1: xxx" and "- eth_short: xxx | ..."
    pattern = re.compile(rf"^\s*-\s*{re.escape(key)}\s*:\s*([^|\n]+)", re.MULTILINE)
    m = pattern.search(text)
    if m:
        return m.group(1).strip()
    return None


def _parse_report_value(text: str, label: str) -> str | None:
    prefix = f"- {label}:"
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(prefix):
            return s.split(":", 1)[1].strip()
    return None


def _parse_mixed_timestamps(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.strip()
    s = s.replace({"": pd.NA, "nan": pd.NA, "None": pd.NA, "NaN": pd.NA})
    out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns, UTC]")

    num = pd.to_numeric(s, errors="coerce")
    num_mask = num.notna()
    abs_num = num.abs()

    masks = {
        "ns": num_mask & (abs_num >= 1e17),
        "us": num_mask & (abs_num >= 1e14) & (abs_num < 1e17),
        "ms": num_mask & (abs_num >= 1e11) & (abs_num < 1e14),
        "s": num_mask & (abs_num < 1e11),
    }
    for unit, mask in masks.items():
        if mask.any():
            out.loc[mask] = pd.to_datetime(num.loc[mask], unit=unit, utc=True, errors="coerce")

    iso_mask = ~num_mask & s.notna()
    if iso_mask.any():
        out.loc[iso_mask] = pd.to_datetime(s.loc[iso_mask], utc=True, errors="coerce")
    return out


def _scan_csv(symbol: str, path: Path) -> CsvScan:
    if not path.exists():
        return CsvScan(symbol=symbol, file=str(path), raw_rows=0, parsed_rows=0, min_time_utc=None, max_time_utc=None, ok=False, note="missing")
    try:
        # infer time column by header first
        with path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, [])
        if not header:
            return CsvScan(symbol=symbol, file=str(path), raw_rows=0, parsed_rows=0, min_time_utc=None, max_time_utc=None, ok=False, note="empty_header")
        time_col = header[0]
        if "time" not in time_col.lower() and "date" not in time_col.lower() and "ts" not in time_col.lower():
            candidates = [c for c in header if any(k in c.lower() for k in ("time", "date", "ts"))]
            if candidates:
                time_col = candidates[0]
        df = pd.read_csv(path, usecols=[time_col], dtype=str, low_memory=False)
        ts = _parse_mixed_timestamps(df[time_col])
        parsed = ts.dropna()
        note = "ok"
        ok = not parsed.empty
        return CsvScan(
            symbol=symbol,
            file=str(path),
            raw_rows=len(df),
            parsed_rows=int(parsed.shape[0]),
            min_time_utc=parsed.min().strftime("%Y-%m-%d %H:%M:%S") if ok else None,
            max_time_utc=parsed.max().strftime("%Y-%m-%d %H:%M:%S") if ok else None,
            ok=ok,
            note=note if ok else "no_parsed_rows",
        )
    except Exception as e:  # pragma: no cover - defensive
        return CsvScan(symbol=symbol, file=str(path), raw_rows=0, parsed_rows=0, min_time_utc=None, max_time_utc=None, ok=False, note=f"scan_error:{type(e).__name__}:{e}")


def _to_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def _bars_between(start: datetime | None, end: datetime | None) -> int:
    if not start or not end or end < start:
        return 0
    return int((end - start).total_seconds() // BAR_SECONDS) + 1


def _safe_copy(src: Path, dst: Path) -> Path | None:
    if not src.exists():
        return None
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst


def _build_aligned_config(src: Path, dst: Path, common_start: datetime | None, common_end: datetime | None) -> Path | None:
    if not src.exists() or not common_start or not common_end or common_end < common_start:
        return None
    text = _read_text(src)
    start_date = common_start.strftime("%Y-%m-%d")
    end_date = common_end.strftime("%Y-%m-%d")
    text = re.sub(r"(?m)^(\s*start:\s*).*$", rf"\1'{start_date}'", text)
    text = re.sub(r"(?m)^(\s*end:\s*).*$", rf"\1'{end_date}'", text)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(text, encoding="utf-8")
    return dst


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).resolve()
    downloads = Path.home() / "Downloads"
    reports_raw = root / "reports" / "research_raw"
    reports_raw.mkdir(parents=True, exist_ok=True)

    okx_report = _find_first_existing([downloads / "okx_demo_report_latest.txt", root / "reports" / "okx_demo_report_latest.txt"])
    branch_report = _find_first_existing([downloads / "branch_demo_report_latest.txt", root / "reports" / "branch_demo_report_latest.txt"])
    stage99 = _find_first_existing([
        reports_raw / "stage99_mainline_frequency_push_latest.txt",
        downloads / "stage99_mainline_frequency_push_latest.txt",
    ])
    stage92 = _find_first_existing([
        reports_raw / "stage92_eth_sol_open_frontier_latest.txt",
        downloads / "stage92_eth_sol_open_frontier_latest.txt",
    ])
    stage107 = _find_first_existing([
        reports_raw / "stage107_joint_upgrade_plan_latest.txt",
        downloads / "stage107_joint_upgrade_plan_latest.txt",
    ])

    okx_text = _read_text(okx_report) if okx_report else ""
    branch_text = _read_text(branch_report) if branch_report else ""
    stage99_text = _read_text(stage99) if stage99 else ""
    stage92_text = _read_text(stage92) if stage92 else ""
    stage107_text = _read_text(stage107) if stage107 else ""

    mainline_keep_live = (
        _extract_candidate_from_line(stage107_text, "keep_live")
        or _extract_candidate_from_line(stage99_text, "live_keep")
        or _parse_report_value(okx_text, "当前候选")
        or "mainline_live_base"
    )
    mainline_shadow_1 = (
        _extract_candidate_from_line(stage107_text, "shadow_priority_1")
        or _extract_candidate_from_line(stage99_text, "shadow_balanced")
        or "combo_sr_soft_adx26_cd6_lb24_zone028_ref"
    )
    mainline_shadow_2 = (
        _extract_candidate_from_line(stage107_text, "shadow_priority_2")
        or _extract_candidate_from_line(stage99_text, "shadow_aggressive")
        or "combo_sr_soft_adx32_cd5_lb20_zone025"
    )
    branch_current_runtime = _parse_report_value(branch_text, "当前版本") or "unknown"
    branch_eth_keep = _extract_candidate_from_line(stage92_text, "eth_short") or "eth_short_shock_fast_lb16_atr052_adx22_s078"
    branch_btc_keep = _extract_after_prefix(stage107_text, ["- pick_reason=active_keep | runtime_leg="]) or "btc_dual_fast_trend_dynlev_fix8"
    branch_sol_status = _extract_candidate_from_line(stage92_text, "sol_long") or "sol_shortwave_smooth_longonly"

    scans: dict[str, CsvScan] = {}
    for symbol in ("btc", "eth", "sol", "bnb"):
        scans[symbol] = _scan_csv(symbol, root / "data" / "raw" / f"{symbol}_15m.csv")

    triple_symbols = [scans[s] for s in ("btc", "eth", "sol") if scans[s].ok]
    common_start = None
    common_end = None
    if len(triple_symbols) == 3:
        starts = [_to_dt(s.min_time_utc) for s in triple_symbols]
        ends = [_to_dt(s.max_time_utc) for s in triple_symbols]
        if all(starts) and all(ends):
            common_start = max(starts)  # latest starting point
            common_end = min(ends)  # earliest ending point
    common_bars = _bars_between(common_start, common_end)
    common_days = round(common_bars * 15 / 60 / 24, 2) if common_bars else 0.0
    can_build_triple = common_bars >= 96  # at least 1 day of overlap to avoid total breakage

    aligned_cfg = _build_aligned_config(
        root / "config_shortwave_triple_book_plan.yml",
        reports_raw / "config_shortwave_triple_book_plan_aligned.yml",
        common_start,
        common_end,
    )
    aligned_shadow = _safe_copy(
        root / "shadow_shortwave_triple_book_plan.yml",
        reports_raw / "shadow_shortwave_triple_book_plan_aligned.yml",
    )

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    if can_build_triple:
        next_action = "先维持主线 live_base + 提频 shadow；第二分支先生成 BTC/ETH/SOL 对齐预览配置，再观察是否推进 demo。"
    else:
        next_action = "先修 BTC/ETH/SOL raw 共同区间，再谈第二分支三标的上 demo。"

    summary = PlanSummary(
        generated_at_utc=now_utc,
        mainline_keep_live=mainline_keep_live,
        mainline_shadow_1=mainline_shadow_1,
        mainline_shadow_2=mainline_shadow_2,
        branch_design="BTC + ETH + SOL",
        branch_current_runtime=branch_current_runtime,
        branch_target_runtime="triple_book_preview_aligned",
        branch_eth_keep=branch_eth_keep,
        branch_btc_keep=branch_btc_keep,
        branch_sol_status=branch_sol_status,
        common_start_utc=common_start.strftime("%Y-%m-%d %H:%M:%S") if common_start else None,
        common_end_utc=common_end.strftime("%Y-%m-%d %H:%M:%S") if common_end else None,
        common_bars_15m=common_bars,
        common_days=common_days,
        can_build_triple_book_preview=can_build_triple,
        next_action=next_action,
    )

    txt_path = reports_raw / "stage109_joint_upgrade_plan_latest.txt"
    json_path = reports_raw / "stage109_joint_upgrade_plan_latest.json"
    txt_lines = [
        "Stage109 主线提频 + 第二分支三标的联合升级规划",
        "规则：主线和支线一起调；第二分支固定 BTC/ETH/SOL；先激进扩，再保守收口；只导出 1 个回传文件。",
        f"generated_at_utc={summary.generated_at_utc}",
        "",
        "=== 主线 ===",
        f"- keep_live: {summary.mainline_keep_live}",
        f"- shadow_priority_1: {summary.mainline_shadow_1}",
        f"- shadow_priority_2: {summary.mainline_shadow_2}",
        "- action: 主线继续 live_base；提频先走 shadow 观察，不直接切 live。",
        "",
        "=== 第二分支三标的 ===",
        f"- design_book: {summary.branch_design}",
        f"- current_runtime: {summary.branch_current_runtime}",
        f"- target_runtime: {summary.branch_target_runtime}",
        f"- btc_keep: {summary.branch_btc_keep}",
        f"- eth_keep: {summary.branch_eth_keep}",
        f"- sol_status: {summary.branch_sol_status}",
        "- action: BTC/ETH/SOL 都保留；BTC 作为确认腿，ETH 继续主收益腿，SOL 先保留路径，等 recent+WF 同时转正再推进 demo。",
        "",
        "=== 共同区间扫描（BTC/ETH/SOL）===",
    ]
    for symbol in ("btc", "eth", "sol"):
        s = scans[symbol]
        txt_lines.append(
            f"- {symbol}: ok={s.ok} raw_rows={s.raw_rows} parsed_rows={s.parsed_rows} min={s.min_time_utc or '-'} max={s.max_time_utc or '-'} note={s.note}"
        )
    txt_lines.extend([
        f"- common_start_utc: {summary.common_start_utc or '-'}",
        f"- common_end_utc: {summary.common_end_utc or '-'}",
        f"- common_bars_15m: {summary.common_bars_15m}",
        f"- common_days: {summary.common_days}",
        f"- can_build_triple_book_preview: {'yes' if summary.can_build_triple_book_preview else 'no'}",
        "",
        "=== 推进门槛 ===",
        "- 主线提频切 demo：只在近2年交易数明显提升，且 PF / 回撤没有明显劣化时推进。",
        "- 第二分支三标的切 demo：先确保 BTC/ETH/SOL 共同区间稳定，再要求 SOL recent + WF 同时转正。",
        "",
        "=== 下一步 ===",
        f"- {summary.next_action}",
        "- 本轮只生成一个回传文件：~/Downloads/stage109_joint_upgrade_plan_latest.zip",
    ])
    txt_path.write_text("\n".join(txt_lines) + "\n", encoding="utf-8")
    json_path.write_text(json.dumps({
        "summary": asdict(summary),
        "scans": {k: asdict(v) for k, v in scans.items()},
        "files": {
            "okx_report": str(okx_report) if okx_report else None,
            "branch_report": str(branch_report) if branch_report else None,
            "stage99": str(stage99) if stage99 else None,
            "stage92": str(stage92) if stage92 else None,
            "stage107": str(stage107) if stage107 else None,
            "aligned_config": str(aligned_cfg) if aligned_cfg else None,
            "aligned_shadow": str(aligned_shadow) if aligned_shadow else None,
        },
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    zip_path = downloads / "stage109_joint_upgrade_plan_latest.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(txt_path, arcname=txt_path.name)
        zf.write(json_path, arcname=json_path.name)
        if aligned_cfg and aligned_cfg.exists():
            zf.write(aligned_cfg, arcname=aligned_cfg.name)
        if aligned_shadow and aligned_shadow.exists():
            zf.write(aligned_shadow, arcname=aligned_shadow.name)
        if okx_report and okx_report.exists():
            zf.write(okx_report, arcname=okx_report.name)
        if branch_report and branch_report.exists():
            zf.write(branch_report, arcname=branch_report.name)

    print(f"[OK] stage109 plan zip: {zip_path}")


if __name__ == "__main__":
    main()
