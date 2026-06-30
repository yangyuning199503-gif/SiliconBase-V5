from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import zipfile
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
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
class FetchResult:
    symbol: str
    market_used: str | None
    ok: bool
    kept_existing: bool
    rows_after: int
    note: str


@dataclass
class Summary:
    generated_at_utc: str
    mainline_keep_live: str
    mainline_shadow_1: str
    mainline_shadow_2: str
    branch_design: str
    branch_current_runtime: str
    common_start_utc: str | None
    common_end_utc: str | None
    common_bars_15m: int
    common_days: float
    can_build_triple_book_preview: bool
    next_action: str


MIN_ROWS = {
    "btc": 100000,
    "eth": 100000,
    "sol": 100000,
    "bnb": 20000,
}

START_DATES = {
    "btc": "2020-01-01",
    "eth": "2020-01-01",
    "sol": "2020-09-01",
    "bnb": "2020-01-01",
}

BINANCE_SYMBOL = {
    "btc": "BTCUSDT",
    "eth": "ETHUSDT",
    "sol": "SOLUSDT",
    "bnb": "BNBUSDT",
}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _find_first_existing(paths: Iterable[Path]) -> Path | None:
    for p in paths:
        if p.exists():
            return p
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
        return CsvScan(symbol, str(path), 0, 0, None, None, False, "missing")
    try:
        with path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, [])
        if not header:
            return CsvScan(symbol, str(path), 0, 0, None, None, False, "empty_header")
        time_col = header[0]
        if not any(k in time_col.lower() for k in ("time", "date", "ts")):
            candidates = [c for c in header if any(k in c.lower() for k in ("time", "date", "ts"))]
            if candidates:
                time_col = candidates[0]
        df = pd.read_csv(path, usecols=[time_col], dtype=str, low_memory=False)
        ts = _parse_mixed_timestamps(df[time_col]).dropna()
        if ts.empty:
            return CsvScan(symbol, str(path), len(df), 0, None, None, False, "no_parsed_rows")
        return CsvScan(
            symbol=symbol,
            file=str(path),
            raw_rows=len(df),
            parsed_rows=int(ts.shape[0]),
            min_time_utc=ts.min().strftime("%Y-%m-%d %H:%M:%S"),
            max_time_utc=ts.max().strftime("%Y-%m-%d %H:%M:%S"),
            ok=True,
            note="ok",
        )
    except Exception as e:
        return CsvScan(symbol, str(path), 0, 0, None, None, False, f"scan_error:{type(e).__name__}:{e}")


def _to_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def _bars_between(start: datetime | None, end: datetime | None) -> int:
    if not start or not end or end < start:
        return 0
    return int((end - start).total_seconds() // BAR_SECONDS) + 1


def _run_fetch(py: str, project_dir: Path, symbol_key: str, out_path: Path, end_date: str) -> FetchResult:
    existing_scan = _scan_csv(symbol_key, out_path)
    symbol = BINANCE_SYMBOL[symbol_key]
    start_date = START_DATES[symbol_key]
    min_rows = MIN_ROWS[symbol_key]
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")

    def try_market(market: str) -> tuple[bool, str, int]:
        if tmp.exists():
            tmp.unlink()
        cmd = [
            py, "-m", "tools.fetch_binance_klines",
            "--symbol", symbol,
            "--market", market,
            "--interval", "15m",
            "--start", start_date,
            "--end", end_date,
            "--out", str(tmp),
        ]
        p = subprocess.run(cmd, cwd=str(project_dir), capture_output=True, text=True)
        if p.returncode != 0:
            return False, (p.stderr or p.stdout or f"fetch_failed:{market}").strip()[-500:], 0
        scan = _scan_csv(symbol_key, tmp)
        if not scan.ok or scan.parsed_rows < min_rows:
            rows = scan.parsed_rows
            return False, f"rows_too_small:{market}:{rows}<{min_rows}", rows
        tmp.replace(out_path)
        return True, "ok", scan.parsed_rows

    for market in ("futures", "spot"):
        ok, note, rows = try_market(market)
        if ok:
            return FetchResult(symbol_key, market, True, False, rows, note)

    # keep existing if it already looks usable
    if existing_scan.ok and existing_scan.parsed_rows >= min_rows:
        return FetchResult(symbol_key, None, True, True, existing_scan.parsed_rows, "keep_existing_after_fetch_failure")
    return FetchResult(symbol_key, None, False, False, existing_scan.parsed_rows, f"fetch_failed_and_existing_unusable:{existing_scan.note}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).resolve()
    downloads = Path.home() / "Downloads"
    reports_raw = root / "reports" / "research_raw"
    reports_raw.mkdir(parents=True, exist_ok=True)
    downloads.mkdir(parents=True, exist_ok=True)

    py = str(root / ".venv" / "bin" / "python")
    if not Path(py).exists():
        py = sys.executable

    # runtime reports for context only
    okx_report = _find_first_existing([downloads / "okx_demo_report_latest.txt", root / "reports" / "okx_demo_report_latest.txt"])
    branch_report = _find_first_existing([downloads / "branch_demo_report_latest.txt", root / "reports" / "branch_demo_report_latest.txt"])
    okx_text = _read_text(okx_report) if okx_report else ""
    branch_text = _read_text(branch_report) if branch_report else ""

    before_scans: dict[str, CsvScan] = {}
    after_scans: dict[str, CsvScan] = {}
    fetch_results: dict[str, FetchResult] = {}

    raw_dir = root / "data" / "raw"
    for key in ("btc", "eth", "sol", "bnb"):
        before_scans[key] = _scan_csv(key, raw_dir / f"{key}_15m.csv")

    tomorrow_utc = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
    for key in ("btc", "eth", "sol", "bnb"):
        fetch_results[key] = _run_fetch(py, root, key, raw_dir / f"{key}_15m.csv", tomorrow_utc)
        after_scans[key] = _scan_csv(key, raw_dir / f"{key}_15m.csv")

    common_start = max(filter(None, (_to_dt(after_scans[k].min_time_utc) for k in ("btc", "eth", "sol"))), default=None)
    common_end = min(filter(None, (_to_dt(after_scans[k].max_time_utc) for k in ("btc", "eth", "sol"))), default=None)
    common_bars = _bars_between(common_start, common_end)
    common_days = round(common_bars * BAR_SECONDS / 86400.0, 2) if common_bars else 0.0
    can_build = common_bars > 50000

    mainline_keep_live = _parse_report_value(okx_text, "当前候选") or "mainline_live_base"
    mainline_shadow_1 = "combo_sr_soft_adx26_cd6_lb24_zone028_ref"
    mainline_shadow_2 = "combo_sr_soft_adx32_cd5_lb20_zone025"
    branch_runtime = _parse_report_value(branch_text, "当前版本") or "unknown"

    next_action = (
        "共同区间已恢复；下一步推进第二分支 BTC/ETH/SOL 三标的 preview，并同步主线提频观察。"
        if can_build else
        "共同区间仍不足；继续优先修 BTC/SOL raw，再谈第二分支三标的上 demo。"
    )

    summary = Summary(
        generated_at_utc=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        mainline_keep_live=mainline_keep_live,
        mainline_shadow_1=mainline_shadow_1,
        mainline_shadow_2=mainline_shadow_2,
        branch_design="BTC + ETH + SOL",
        branch_current_runtime=branch_runtime,
        common_start_utc=common_start.strftime("%Y-%m-%d %H:%M:%S") if common_start else None,
        common_end_utc=common_end.strftime("%Y-%m-%d %H:%M:%S") if common_end else None,
        common_bars_15m=common_bars,
        common_days=common_days,
        can_build_triple_book_preview=can_build,
        next_action=next_action,
    )

    txt_lines = [
        "Stage110 三标的共同区间修复",
        "规则：主线和支线一起调；第二分支固定 BTC/ETH/SOL；只导出 1 个回传文件。",
        f"generated_at_utc={summary.generated_at_utc}",
        "",
        "=== 主线 ===",
        f"- keep_live: {summary.mainline_keep_live}",
        f"- shadow_priority_1: {summary.mainline_shadow_1}",
        f"- shadow_priority_2: {summary.mainline_shadow_2}",
        "- action: 主线继续 live_base；提频先走 shadow 观察，不直接切 live。",
        "",
        "=== 第二分支三标的 ===",
        "- design_book: BTC + ETH + SOL",
        f"- current_runtime: {summary.branch_current_runtime}",
        "",
        "=== 刷新结果（after）===",
    ]
    for key in ("btc", "eth", "sol", "bnb"):
        s = after_scans[key]
        fr = fetch_results[key]
        txt_lines.append(
            f"- {key}: ok={s.ok} parsed_rows={s.parsed_rows} min={s.min_time_utc} max={s.max_time_utc} fetch_ok={fr.ok} market={fr.market_used or '-'} kept_existing={fr.kept_existing} note={fr.note}"
        )
    txt_lines += [
        "",
        "=== 共同区间扫描（BTC/ETH/SOL）===",
        f"- common_start_utc: {summary.common_start_utc}",
        f"- common_end_utc: {summary.common_end_utc}",
        f"- common_bars_15m: {summary.common_bars_15m}",
        f"- common_days: {summary.common_days}",
        f"- can_build_triple_book_preview: {'yes' if summary.can_build_triple_book_preview else 'no'}",
        "",
        "=== 当前 runtime 提示 ===",
        f"- main_recent_reason: {_parse_report_value(okx_text, '最近影子执行原因') or '-'}",
        f"- branch_recent_reason: {_parse_report_value(branch_text, '最近影子执行原因') or '-'}",
        "",
        "=== 下一步 ===",
        f"- {summary.next_action}",
        "- 本轮只生成一个回传文件：~/Downloads/stage110_triple_book_repair_latest.zip",
    ]

    txt_path = reports_raw / "stage110_triple_book_repair_latest.txt"
    json_path = reports_raw / "stage110_triple_book_repair_latest.json"
    txt_path.write_text("\n".join(txt_lines) + "\n", encoding="utf-8")
    json_path.write_text(json.dumps({
        "summary": asdict(summary),
        "before_scans": {k: asdict(v) for k, v in before_scans.items()},
        "after_scans": {k: asdict(v) for k, v in after_scans.items()},
        "fetch_results": {k: asdict(v) for k, v in fetch_results.items()},
        "files": {
            "okx_report": str(okx_report) if okx_report else None,
            "branch_report": str(branch_report) if branch_report else None,
        },
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    zip_path = downloads / "stage110_triple_book_repair_latest.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(txt_path, arcname=txt_path.name)
        zf.write(json_path, arcname=json_path.name)
        if okx_report and okx_report.exists():
            zf.write(okx_report, arcname="okx_demo_report_latest.txt")
        if branch_report and branch_report.exists():
            zf.write(branch_report, arcname="branch_demo_report_latest.txt")

    print(f"[OK] export -> {zip_path}")


if __name__ == "__main__":
    main()
