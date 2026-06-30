from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import yaml
from tabulate import tabulate

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest.engine import run_backtest_portfolio
from src.backtest.io import load_ohlcv_csv, read_config, save_csv, save_json
from src.backtest.metrics import summarize_metrics
from tools.okx_demo_autopilot import (
    _coinglass_get,
    _flatten_text,
    _looks_high_importance,
    _macro_keywords_default,
    _news_keywords_default,
)
from tools.okx_demo_common import ensure_env_loaded, now_utc_text

_BAR_FREQ = {
    "1m": "1min",
    "3m": "3min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1h",
    "2h": "2h",
    "4h": "4h",
    "6h": "6h",
    "12h": "12h",
    "1d": "1d",
}
_TITLE_KEYS = [
    "title",
    "headline",
    "name",
    "event",
    "eventName",
    "event_name",
    "articleTitle",
    "article_title",
    "calendar_name",
    "news_title",
    "summary_title",
    "subject",
]
_TIME_KEY_HINTS = (
    "time",
    "date",
    "ts",
    "stamp",
    "publish",
    "published",
    "release",
    "create",
    "created",
    "update",
    "updated",
    "event",
    "start",
    "end",
)
_ITEM_KEYS = (
    "data",
    "result",
    "items",
    "list",
    "rows",
    "articles",
    "news",
    "events",
    "records",
)


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        obj = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def _shadow_cfg(root: Path) -> dict[str, Any]:
    path = root / "shadow.yml"
    loaded = _read_yaml(path)
    obj = loaded.get("shadow", loaded) if isinstance(loaded, dict) else {}
    return obj if isinstance(obj, dict) else {}


def _freq_for_bar(bar: str) -> str:
    key = str(bar or "15m").strip().lower()
    if key not in _BAR_FREQ:
        raise ValueError(f"unsupported bar: {bar}")
    return _BAR_FREQ[key]


def _ceil_bar(ts: pd.Timestamp | None, bar: str) -> pd.Timestamp | None:
    if ts is None:
        return None
    freq = _freq_for_bar(bar)
    return pd.Timestamp(ts).ceil(freq)


def _load_json_path(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _looks_time_key(key: str) -> bool:
    s = str(key or "").strip().lower().replace("-", "_")
    return any(h in s for h in _TIME_KEY_HINTS)


def _parse_time_value(val: Any) -> pd.Timestamp | None:
    if val is None:
        return None
    try:
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            num = float(val)
            if abs(num) < 946684800:  # < 2000-01-01 in seconds
                return None
            unit = "ms" if abs(num) > 1e11 else "s"
            ts = pd.to_datetime(int(num), unit=unit, utc=True, errors="coerce")
        else:
            s = str(val).strip()
            if not s:
                return None
            if s.lower().startswith(("http://", "https://")):
                return None
            if s.endswith("%"):
                return None
            if s.isdigit() or (s.startswith("-") and s[1:].isdigit()):
                num = int(s)
                if abs(num) < 946684800:
                    return None
                unit = "ms" if abs(num) > 1e11 else "s"
                ts = pd.to_datetime(num, unit=unit, utc=True, errors="coerce")
            else:
                ts = pd.to_datetime(s, utc=True, errors="coerce")
        if ts is pd.NaT or ts is None:
            return None
        ts = pd.Timestamp(ts)
        ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
        if ts < pd.Timestamp("2000-01-01", tz="UTC") or ts > pd.Timestamp("2100-01-01", tz="UTC"):
            return None
        return ts
    except Exception:
        return None


def _iter_pairs(obj: Any, path: str = "") -> Iterable[tuple[str, str, Any]]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            ks = str(k)
            p = f"{path}.{ks}" if path else ks
            yield ks, p, v
            if isinstance(v, (dict, list, tuple)):
                yield from _iter_pairs(v, p)
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            p = f"{path}[{i}]" if path else f"[{i}]"
            yield str(i), p, v
            if isinstance(v, (dict, list, tuple)):
                yield from _iter_pairs(v, p)


def _candidate_times(obj: Any, *, now: pd.Timestamp, max_items: int = 16) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen = set()
    horizon_min = now - pd.Timedelta(days=120)
    horizon_max = now + pd.Timedelta(days=120)
    for key, path, val in _iter_pairs(obj):
        hinted = _looks_time_key(key)
        ts = None
        if hinted or isinstance(val, (int, float)) and not isinstance(val, bool):
            ts = _parse_time_value(val)
        elif isinstance(val, str):
            s = val.strip()
            if any(ch in s for ch in ["-", "/", ":", "T"]) or s.isdigit():
                ts = _parse_time_value(s)
        if ts is None:
            continue
        if ts < horizon_min or ts > horizon_max:
            continue
        stamp = ts.isoformat()
        sig = (path, stamp)
        if sig in seen:
            continue
        seen.add(sig)
        out.append({
            "key": key,
            "path": path,
            "value": str(val)[:120],
            "ts": ts,
            "hinted": hinted,
            "abs_sec_from_now": abs((ts - now).total_seconds()),
        })
    out.sort(key=lambda x: (0 if x["hinted"] else 1, x["abs_sec_from_now"], x["path"]))
    return out[:max_items]


def _extract_time(obj: Any, *, now: pd.Timestamp | None = None) -> pd.Timestamp | None:
    now = now or pd.Timestamp.now(tz="UTC")
    candidates = _candidate_times(obj, now=now, max_items=8)
    if not candidates:
        return None
    return pd.Timestamp(candidates[0]["ts"])


def _extract_title(obj: Any) -> str:
    if not isinstance(obj, dict):
        return str(obj)
    for key in _TITLE_KEYS:
        val = obj.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    # generic fallback: prefer first non-url string from title-like keys, then any non-url string
    for k, _, v in _iter_pairs(obj):
        if isinstance(v, str) and v.strip() and not v.strip().lower().startswith(("http://", "https://")):
            if _looks_time_key(k):
                continue
            return v.strip()[:180]
    flat = _flatten_text(obj)
    parts = [p.strip() for p in flat.split(" | ") if p and not str(p).strip().lower().startswith(("http://", "https://"))]
    return (parts[0] if parts else flat[:180])[:180]


def _extract_items(data: Any) -> list[Any]:
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    best: list[Any] = []
    stack: list[Any] = [data]
    seen_ids = set()
    while stack:
        cur = stack.pop()
        oid = id(cur)
        if oid in seen_ids:
            continue
        seen_ids.add(oid)
        if isinstance(cur, list):
            if cur and all(isinstance(x, dict) for x in cur[: min(len(cur), 5)]) and len(cur) > len(best):
                best = cur
            for item in cur[:10]:
                if isinstance(item, (dict, list)):
                    stack.append(item)
            continue
        if not isinstance(cur, dict):
            continue
        for key in _ITEM_KEYS:
            val = cur.get(key)
            if isinstance(val, list) and val and all(isinstance(x, dict) for x in val[: min(len(val), 5)]):
                if len(val) > len(best):
                    best = val
            elif isinstance(val, (dict, list)):
                stack.append(val)
        for val in cur.values():
            if isinstance(val, (dict, list)):
                stack.append(val)
    return best


def _find_time_bounds(rows: list[Any], *, now: pd.Timestamp) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    times = [t for t in (_extract_time(x, now=now) for x in rows) if t is not None]
    if not times:
        return None, None
    return min(times), max(times)


def _fetch_or_load_feed(
    *,
    session: requests.Session,
    base_url: str,
    path: str,
    api_key: str,
    local_json: str | None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if local_json:
        p = Path(local_json).expanduser()
        data = _load_json_path(p)
        return {"ok": True, "status_code": None, "data": data, "source": str(p)}
    return _coinglass_get(session, base_url, path, api_key, params=params)


def _build_pause_events(
    *,
    news_rows: list[Any],
    econ_rows: list[Any],
    bar: str,
    news_lookback_min: int,
    macro_lead_min: int,
    macro_post_min: int,
    news_keywords: list[str],
    macro_keywords: list[str],
    now: pd.Timestamp,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    events: list[dict[str, Any]] = []
    stats = {
        "news_total": len(news_rows),
        "economic_total": len(econ_rows),
        "news_matched": 0,
        "economic_matched": 0,
        "news_missing_ts": 0,
        "economic_missing_ts": 0,
    }

    for raw in news_rows:
        title = _extract_title(raw)
        text_l = _flatten_text(raw).lower()
        matched = any(k in text_l for k in news_keywords)
        ts = _extract_time(raw, now=now)
        if ts is None:
            if matched:
                stats["news_missing_ts"] += 1
            continue
        if not matched:
            continue
        start = _ceil_bar(ts, bar)
        end = _ceil_bar(ts + pd.Timedelta(minutes=news_lookback_min), bar)
        if start is None or end is None:
            continue
        events.append(
            {
                "source": "news",
                "title": title,
                "ts_utc": str(ts),
                "pause_start_utc": str(start),
                "pause_end_utc": str(end),
                "reason": f"news:{title[:120]}",
            }
        )
        stats["news_matched"] += 1

    for raw in econ_rows:
        title = _extract_title(raw)
        text_l = _flatten_text(raw).lower()
        matched = _looks_high_importance(raw) or any(k in text_l for k in macro_keywords)
        ts = _extract_time(raw, now=now)
        if ts is None:
            if matched:
                stats["economic_missing_ts"] += 1
            continue
        if not matched:
            continue
        start = _ceil_bar(ts - pd.Timedelta(minutes=macro_lead_min), bar)
        end = _ceil_bar(ts + pd.Timedelta(minutes=macro_post_min), bar)
        if start is None or end is None:
            continue
        events.append(
            {
                "source": "economic",
                "title": title,
                "ts_utc": str(ts),
                "pause_start_utc": str(start),
                "pause_end_utc": str(end),
                "reason": f"macro:{title[:120]}",
            }
        )
        stats["economic_matched"] += 1

    events.sort(key=lambda x: (x["pause_start_utc"], x["source"], x["title"]))
    return events, stats


def _copy_data_window(
    *,
    cfg: dict[str, Any],
    root: Path,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> dict[str, pd.DataFrame]:
    data_cfg = cfg.get("data", {}) or {}
    symbols = [str(x).strip().lower() for x in data_cfg.get("symbols", []) if str(x).strip()]
    tmpl = str(data_cfg.get("csv_template", "data/raw/{symbol}_15m.csv"))
    out: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        path = Path(tmpl.format(symbol=sym))
        if not path.is_absolute():
            path = root / path
        if not path.exists():
            raise FileNotFoundError(f"missing csv: {path}")
        df = load_ohlcv_csv(path)
        df = df.loc[(df.index >= start.tz_convert(None)) & (df.index <= end.tz_convert(None))].copy()
        if df.empty:
            raise ValueError(f"empty data window for {sym}: {start} -> {end}")
        out[sym] = df
    return out


def _common_index(data: dict[str, pd.DataFrame]) -> pd.DatetimeIndex:
    common = None
    for df in data.values():
        idx = pd.DatetimeIndex(df.index)
        common = idx if common is None else common.intersection(idx)
    if common is None or len(common) == 0:
        raise ValueError("common index empty")
    return common.sort_values()


def _build_pause_mask(common: pd.DatetimeIndex, events: list[dict[str, Any]]) -> pd.DataFrame:
    reasons: dict[pd.Timestamp, list[str]] = {}
    for event in events:
        start = pd.to_datetime(event["pause_start_utc"], utc=True).tz_convert(None)
        end = pd.to_datetime(event["pause_end_utc"], utc=True).tz_convert(None)
        mask = (common >= start) & (common <= end)
        if not mask.any():
            continue
        for ts in common[mask]:
            reasons.setdefault(pd.Timestamp(ts), []).append(str(event["reason"]))

    if not reasons:
        return pd.DataFrame(columns=["time", "symbol", "pause_new_entries", "reason", "reason_count"])

    rows = []
    for ts in sorted(reasons.keys()):
        uniq = []
        seen = set()
        for r in reasons[ts]:
            if r not in seen:
                seen.add(r)
                uniq.append(r)
        rows.append(
            {
                "time": pd.Timestamp(ts).strftime("%Y-%m-%d %H:%M:%S"),
                "symbol": "all",
                "pause_new_entries": 1,
                "reason": " | ".join(uniq[:3]),
                "reason_count": len(uniq),
            }
        )
    return pd.DataFrame(rows)


_METRIC_FIELDS = [
    ("period_start", "period_start"),
    ("period_end", "period_end"),
    ("total_return", "total_return"),
    ("cagr", "cagr"),
    ("max_drawdown", "max_drawdown"),
    ("profit_factor", "profit_factor"),
    ("trades", "trades"),
    ("win_rate", "win_rate"),
    ("sharpe_daily", "sharpe_daily"),
]


def _metric_table(base_m: dict[str, Any], cg_m: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for key, label in _METRIC_FIELDS:
        b = base_m.get(key)
        c = cg_m.get(key)
        delta = None
        try:
            if b is not None and c is not None:
                delta = float(c) - float(b)
        except Exception:
            delta = None
        rows.append({"metric": label, "base": b, "coinglass_pause": c, "delta": delta})
    return pd.DataFrame(rows)


def _fmt_metric(name: str, value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "NA"
    if name in {"total_return", "cagr", "max_drawdown", "win_rate", "delta"}:
        try:
            return f"{float(value)*100:.2f}%"
        except Exception:
            return str(value)
    if name in {"profit_factor", "sharpe_daily"}:
        try:
            return f"{float(value):.2f}"
        except Exception:
            return str(value)
    if name == "trades":
        try:
            return str(int(value))
        except Exception:
            return str(value)
    return str(value)


def _write_txt(*, path: Path, report: dict[str, Any], metric_df: pd.DataFrame | None = None) -> None:
    fetch = report.get("fetch", {}) if isinstance(report.get("fetch"), dict) else {}
    window = report.get("window", {}) if isinstance(report.get("window"), dict) else {}
    pause = report.get("pause_mask", {}) if isinstance(report.get("pause_mask"), dict) else {}
    base_m = report.get("base_metrics", {}) if isinstance(report.get("base_metrics"), dict) else {}
    cg_m = report.get("coinglass_metrics", {}) if isinstance(report.get("coinglass_metrics"), dict) else {}
    debug = report.get("debug", {}) if isinstance(report.get("debug"), dict) else {}
    lines = [
        f"status: {report.get('status', '')}",
        f"ts_utc: {report.get('ts_utc', '')}",
        f"project_dir: {report.get('project_dir', '')}",
        f"error: {report.get('error', '')}",
        f"news_source: {fetch.get('news_source', '')}",
        f"economic_source: {fetch.get('economic_source', '')}",
        f"news_rows: {fetch.get('news_rows', 0)}",
        f"economic_rows: {fetch.get('economic_rows', 0)}",
        f"news_time_min_utc: {fetch.get('news_time_min_utc', '')}",
        f"news_time_max_utc: {fetch.get('news_time_max_utc', '')}",
        f"economic_time_min_utc: {fetch.get('economic_time_min_utc', '')}",
        f"economic_time_max_utc: {fetch.get('economic_time_max_utc', '')}",
        f"run_start_utc: {window.get('run_start_utc', '')}",
        f"run_end_utc: {window.get('run_end_utc', '')}",
        f"event_start_utc: {window.get('event_start_utc', '')}",
        f"event_end_utc: {window.get('event_end_utc', '')}",
        f"pause_bars: {pause.get('pause_bars', 0)}",
        f"pause_reason_rows: {pause.get('pause_reason_rows', 0)}",
        f"blocked_base_entry_candidates: {pause.get('blocked_base_entry_candidates', 0)}",
        f"base_total_return: {base_m.get('total_return', '')}",
        f"cg_total_return: {cg_m.get('total_return', '')}",
        f"base_max_drawdown: {base_m.get('max_drawdown', '')}",
        f"cg_max_drawdown: {cg_m.get('max_drawdown', '')}",
        f"base_profit_factor: {base_m.get('profit_factor', '')}",
        f"cg_profit_factor: {cg_m.get('profit_factor', '')}",
        f"base_trades: {base_m.get('trades', '')}",
        f"cg_trades: {cg_m.get('trades', '')}",
        f"news_first_title: {debug.get('news_first_title', '')}",
        f"economic_first_title: {debug.get('economic_first_title', '')}",
        f"news_first_candidate_times: {json.dumps(debug.get('news_first_candidate_times', []), ensure_ascii=False)}",
        f"economic_first_candidate_times: {json.dumps(debug.get('economic_first_candidate_times', []), ensure_ascii=False)}",
        "",
    ]
    if metric_df is not None and not metric_df.empty:
        lines.append("=== base vs coinglass_pause ===")
        fmt = metric_df.copy()
        for col in ["base", "coinglass_pause", "delta"]:
            fmt[col] = [_fmt_metric(str(row["metric"]), row[col]) for _, row in fmt.iterrows()]
        lines.append(tabulate(fmt, headers="keys", tablefmt="github", showindex=False))
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _copy_if_exists(src: Path, dst: Path) -> None:
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)


def _persist_latest(*, root: Path, summary_json: Path, summary_txt: Path, extra_files: list[Path] | None = None) -> None:
    reports_dir = root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    latest_json = reports_dir / "coinglass_ab_latest.json"
    latest_txt = reports_dir / "coinglass_ab_latest.txt"
    shutil.copyfile(summary_json, latest_json)
    shutil.copyfile(summary_txt, latest_txt)

    dl_dir = Path.home() / "Downloads"
    dl_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(summary_txt, dl_dir / "coinglass_ab_latest.txt")


def _debug_first_row(rows: list[Any], *, now: pd.Timestamp) -> dict[str, Any]:
    row = rows[0] if rows else None
    if row is None:
        return {"title": "", "candidate_times": []}
    cands = _candidate_times(row, now=now, max_items=5)
    return {
        "title": _extract_title(row),
        "candidate_times": [
            {
                "key": x.get("key"),
                "path": x.get("path"),
                "value": x.get("value"),
                "ts_utc": str(x.get("ts")),
                "hinted": bool(x.get("hinted")),
            }
            for x in cands
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Run CoinGlass pause_new_entries A/B backtest")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--config", default="config.yml")
    ap.add_argument("--bar", default="15m")
    ap.add_argument("--warmup-days", type=int, default=30)
    ap.add_argument("--economic-days", type=int, default=15)
    ap.add_argument("--economic-forward-hours", type=int, default=0)
    ap.add_argument("--language", default="")
    ap.add_argument("--news-json", default="")
    ap.add_argument("--economic-json", default="")
    ap.add_argument("--out-dir", default="")
    args = ap.parse_args()

    root = Path(args.project_dir).resolve()
    cfg_path = Path(args.config)
    if not cfg_path.is_absolute():
        cfg_path = root / cfg_path
    cfg = read_config(cfg_path)

    shadow = _shadow_cfg(root)
    ap_cfg = shadow.get("autopilot", {}) if isinstance(shadow.get("autopilot"), dict) else {}
    cg_cfg = ap_cfg.get("coinglass", {}) if isinstance(ap_cfg.get("coinglass"), dict) else {}
    if not bool(cg_cfg.get("enabled", True)):
        raise SystemExit("CoinGlass disabled in shadow.yml")

    ensure_env_loaded(root=root)
    api_key = os.environ.get("COINGLASS_API_KEY", "").strip()
    if not api_key and not (args.news_json or args.economic_json):
        raise SystemExit("missing COINGLASS_API_KEY")

    base_url = str(cg_cfg.get("base_url", "https://open-api-v4.coinglass.com"))
    news_path = str(cg_cfg.get("news_path", "/api/article/list"))
    economic_path = str(cg_cfg.get("economic_path", "/api/calendar/economic-data"))
    news_lookback_min = int(cg_cfg.get("news_pause_lookback_minutes", 120))
    macro_lead_min = int(cg_cfg.get("macro_pause_lead_minutes", 180))
    macro_post_min = int(cg_cfg.get("macro_pause_post_minutes", 30))
    news_keywords = [str(x).lower() for x in cg_cfg.get("news_pause_keywords", _news_keywords_default())]
    macro_keywords = [str(x).lower() for x in cg_cfg.get("macro_keywords", _macro_keywords_default())]

    ts_tag = pd.Timestamp.now(tz="UTC").strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out_dir) if args.out_dir else root / "reports" / f"coinglass_ab_{ts_tag}"
    if not out_dir.is_absolute():
        out_dir = root / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    now = pd.Timestamp.now(tz="UTC")
    session = requests.Session()
    news_params = {"language": args.language} if args.language else None
    econ_params: dict[str, Any] = {}
    if args.economic_days > 0:
        econ_params["start_time"] = int((now - pd.Timedelta(days=args.economic_days)).timestamp() * 1000)
        econ_params["end_time"] = int((now + pd.Timedelta(hours=args.economic_forward_hours)).timestamp() * 1000)
    if args.language:
        econ_params["language"] = args.language

    news_res = _fetch_or_load_feed(
        session=session,
        base_url=base_url,
        path=news_path,
        api_key=api_key,
        local_json=args.news_json or None,
        params=news_params,
    )
    econ_res = _fetch_or_load_feed(
        session=session,
        base_url=base_url,
        path=economic_path,
        api_key=api_key,
        local_json=args.economic_json or None,
        params=econ_params or None,
    )

    news_raw_path = out_dir / "coinglass_news_raw.json"
    econ_raw_path = out_dir / "coinglass_economic_raw.json"
    save_json(news_res.get("data"), news_raw_path)
    save_json(econ_res.get("data"), econ_raw_path)

    news_rows = _extract_items(news_res.get("data"))
    econ_rows = _extract_items(econ_res.get("data"))
    news_min, news_max = _find_time_bounds(news_rows, now=now)
    econ_min, econ_max = _find_time_bounds(econ_rows, now=now)

    debug = {
        "news_first_title": _debug_first_row(news_rows, now=now).get("title", ""),
        "economic_first_title": _debug_first_row(econ_rows, now=now).get("title", ""),
        "news_first_candidate_times": _debug_first_row(news_rows, now=now).get("candidate_times", []),
        "economic_first_candidate_times": _debug_first_row(econ_rows, now=now).get("candidate_times", []),
    }

    report: dict[str, Any] = {
        "status": "running",
        "ts_utc": now_utc_text(),
        "project_dir": str(root),
        "error": "",
        "fetch": {
            "news_source": news_res.get("source") or news_res.get("url") or news_path,
            "economic_source": econ_res.get("source") or econ_res.get("url") or economic_path,
            "news_rows": len(news_rows),
            "economic_rows": len(econ_rows),
            "news_time_min_utc": str(news_min) if news_min is not None else None,
            "news_time_max_utc": str(news_max) if news_max is not None else None,
            "economic_time_min_utc": str(econ_min) if econ_min is not None else None,
            "economic_time_max_utc": str(econ_max) if econ_max is not None else None,
        },
        "debug": debug,
        "pause_mask": {},
        "window": {},
        "base_metrics": {},
        "coinglass_metrics": {},
    }

    try:
        if not news_res.get("ok"):
            raise SystemExit(f"news fetch failed: {news_res}")
        if not econ_res.get("ok"):
            raise SystemExit(f"economic fetch failed: {econ_res}")

        events, event_stats = _build_pause_events(
            news_rows=news_rows,
            econ_rows=econ_rows,
            bar=args.bar,
            news_lookback_min=news_lookback_min,
            macro_lead_min=macro_lead_min,
            macro_post_min=macro_post_min,
            news_keywords=news_keywords,
            macro_keywords=macro_keywords,
            now=now,
        )
        save_json({"events": events, "stats": event_stats}, out_dir / "pause_events.json")
        save_csv(pd.DataFrame(events), out_dir / "pause_events.csv")

        if events:
            event_start = min(pd.to_datetime(x["pause_start_utc"], utc=True) for x in events)
            event_end = max(pd.to_datetime(x["pause_end_utc"], utc=True) for x in events)
        else:
            fallback_times = [t for t in [news_min, news_max, econ_min, econ_max] if t is not None]
            if not fallback_times:
                raise SystemExit("CoinGlass returned no parseable timestamps")
            event_start = min(fallback_times)
            event_end = max(fallback_times)

        run_start = event_start - pd.Timedelta(days=max(0, int(args.warmup_days)))
        run_end = event_end

        data = _copy_data_window(cfg=cfg, root=root, start=run_start, end=run_end)
        common = _common_index(data)
        pause_mask_df = _build_pause_mask(common, events)
        pause_csv = out_dir / "coinglass_pause_mask.csv"
        pause_mask_df.to_csv(pause_csv, index=False, encoding="utf-8")

        base_cfg = copy.deepcopy(cfg)
        base_cfg.setdefault("system", {})["version"] = f"{cfg.get('system', {}).get('version', 'NA')}_cgab_base"
        cg_bt_cfg = copy.deepcopy(cfg)
        cg_bt_cfg.setdefault("system", {})["version"] = f"{cfg.get('system', {}).get('version', 'NA')}_cgab_pause"
        cg_bt_cfg["external_entry_pause"] = {
            "enabled": True,
            "file": str(pause_csv),
        }

        base_eq, base_trades, base_snap = run_backtest_portfolio(data={k: v.copy() for k, v in data.items()}, cfg=base_cfg)
        cg_eq, cg_trades, cg_snap = run_backtest_portfolio(data={k: v.copy() for k, v in data.items()}, cfg=cg_bt_cfg)

        initial = float(cfg.get("portfolio", {}).get("initial_equity", 0.0))
        base_metrics = summarize_metrics(initial=initial, equity=base_eq["equity"], trades=base_trades)
        cg_metrics = summarize_metrics(initial=initial, equity=cg_eq["equity"], trades=cg_trades)
        metric_df = _metric_table(base_metrics, cg_metrics)
        metric_df.to_csv(out_dir / "metrics_compare.csv", index=False, encoding="utf-8")

        blocked_base_entries = 0
        if not pause_mask_df.empty and not base_trades.empty and "entry_time" in base_trades.columns:
            paused_set = set(pd.to_datetime(pause_mask_df["time"], utc=True).dt.tz_convert(None))
            entry_times = pd.to_datetime(base_trades["entry_time"], utc=True, errors="coerce").dt.tz_convert(None)
            blocked_base_entries = int(entry_times.isin(paused_set).sum())

        report.update({
            "status": "ok",
            "event_stats": event_stats,
            "window": {
                "run_start_utc": str(run_start),
                "run_end_utc": str(run_end),
                "event_start_utc": str(event_start),
                "event_end_utc": str(event_end),
                "common_bars": int(len(common)),
            },
            "pause_mask": {
                "pause_bars": int(len(pause_mask_df)),
                "pause_reason_rows": int(len(pause_mask_df)),
                "blocked_base_entry_candidates": blocked_base_entries,
                "pause_mask_csv": str(pause_csv),
            },
            "base_metrics": base_metrics,
            "coinglass_metrics": cg_metrics,
            "base_snapshot": base_snap,
            "coinglass_snapshot": cg_snap,
        })
        metric_for_txt = metric_df
    except SystemExit as e:
        report["status"] = "failed"
        report["error"] = str(e)
        metric_for_txt = None
    except Exception as e:
        report["status"] = "failed"
        report["error"] = f"{type(e).__name__}: {e}"
        metric_for_txt = None

    summary_json = out_dir / "summary.json"
    summary_txt = out_dir / "summary.txt"
    save_json(report, summary_json)
    _write_txt(path=summary_txt, report=report, metric_df=metric_for_txt)
    _persist_latest(root=root, summary_json=summary_json, summary_txt=summary_txt, extra_files=[news_raw_path, econ_raw_path])

    print(json.dumps({
        "ok": report.get("status") == "ok",
        "status": report.get("status"),
        "out_dir": str(out_dir),
        "summary_json": str(summary_json),
        "summary_txt": str(summary_txt),
        "downloads_json": str(Path.home() / "Downloads" / "coinglass_ab_latest.json"),
        "downloads_txt": str(Path.home() / "Downloads" / "coinglass_ab_latest.txt"),
        "error": report.get("error"),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
