from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import requests

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest.engine import run_backtest_portfolio
from src.backtest.io import load_ohlcv_csv, read_config
from tools.okx_demo_common import ensure_env_loaded


def _utc_now() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC")


def _parse_time_value(val: Any) -> pd.Timestamp | None:
    if val is None:
        return None
    try:
        if isinstance(val, (int, float)):
            num = float(val)
            unit = "ms" if abs(num) > 1e11 else "s"
            return pd.to_datetime(int(num), unit=unit, utc=True)
        s = str(val).strip()
        if not s:
            return None
        if s.isdigit() or (s.startswith("-") and s[1:].isdigit()):
            num = int(s)
            unit = "ms" if abs(num) > 1e11 else "s"
            return pd.to_datetime(num, unit=unit, utc=True)
        return pd.to_datetime(s, utc=True)
    except Exception:
        return None


def _extract_time(obj: Any) -> pd.Timestamp | None:
    if isinstance(obj, dict):
        for key in ["ts", "time", "timestamp", "publishTime", "publishedAt", "releaseTime", "date", "datetime", "eventTime", "actualTime", "createdAt", "updatedAt"]:
            ts = _parse_time_value(obj.get(key))
            if ts is not None:
                return ts
    return _parse_time_value(obj)


def _flatten_scalars(obj: Any) -> list[str]:
    parts: list[str] = []

    def _walk(x: Any) -> None:
        if x is None:
            return
        if isinstance(x, (str, int, float, bool)):
            s = str(x).strip()
            if s:
                parts.append(s)
            return
        if isinstance(x, dict):
            for v in x.values():
                _walk(v)
            return
        if isinstance(x, (list, tuple, set)):
            for v in x:
                _walk(v)
            return

    _walk(obj)
    return parts


def _flatten_text(obj: Any) -> str:
    return " | ".join(_flatten_scalars(obj))


def _is_url_like(s: str) -> bool:
    s = s.strip().lower()
    return s.startswith("http://") or s.startswith("https://") or s.endswith(".jpg") or s.endswith(".png") or s.endswith(".jpeg") or s.endswith(".webp")


def _clean_text(s: str) -> str:
    s = str(s or "").replace("\n", " ").replace("\r", " ").strip()
    while "  " in s:
        s = s.replace("  ", " ")
    return s[:180]


def _extract_title(obj: Any) -> str:
    if not isinstance(obj, dict):
        return _clean_text(str(obj))
    keys = [
        "title", "headline", "name", "event", "eventName", "articleTitle",
        "summary", "description", "desc", "brief", "content",
    ]
    for key in keys:
        val = obj.get(key)
        if not val:
            continue
        txt = _clean_text(str(val))
        if txt and not _is_url_like(txt):
            return txt
    for part in _flatten_scalars(obj):
        txt = _clean_text(part)
        if len(txt) >= 8 and not _is_url_like(txt):
            return txt
    flat = _clean_text(_flatten_text(obj))
    return flat[:180]


def _extract_items(data: Any) -> list[Any]:
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for key in ["data", "result", "items", "list", "rows", "articles"]:
        val = data.get(key)
        if isinstance(val, list):
            return val
        if isinstance(val, dict):
            for sub in ["items", "list", "rows", "data", "articles"]:
                vv = val.get(sub)
                if isinstance(vv, list):
                    return vv
    return []


def _looks_high_importance(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    for key in ["importance", "impact", "level", "star", "stars", "priority"]:
        val = obj.get(key)
        if val is None:
            continue
        s = str(val).strip().lower()
        if s in {"3", "high", "high impact", "important", "critical", "red", "three"}:
            return True
        try:
            if float(s) >= 3:
                return True
        except Exception:
            pass
    return False


def _coinglass_get(session: requests.Session, api_key: str, path: str, timeout: int = 18) -> dict[str, Any]:
    base_url = "https://open-api-v4.coinglass.com"
    url = base_url.rstrip("/") + path
    headers = {"accept": "application/json", "CG-API-KEY": api_key}
    out: dict[str, Any] = {"ok": False, "url": url, "path": path}
    try:
        resp = session.get(url, headers=headers, timeout=timeout)
        out["status_code"] = resp.status_code
        out["ok"] = resp.status_code == 200
        try:
            out["data"] = resp.json()
        except Exception:
            out["data"] = {"raw": resp.text[:4000]}
    except Exception as e:
        out["error"] = str(e)
    return out


def _merge_intervals(intervals: list[tuple[pd.Timestamp, pd.Timestamp]]) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    if not intervals:
        return []
    rows = sorted(intervals, key=lambda x: x[0])
    merged: list[tuple[pd.Timestamp, pd.Timestamp]] = [rows[0]]
    for start, end in rows[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def _ts_naive_utc(ts: pd.Timestamp | None) -> pd.Timestamp | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        return ts
    return ts.tz_convert("UTC").tz_localize(None)


def _trade_metrics(trades_df: pd.DataFrame, initial_equity: float) -> dict[str, Any]:
    df = trades_df.copy() if trades_df is not None else pd.DataFrame()
    if df.empty:
        return {
            "trades": 0,
            "wins": 0,
            "win_rate": 0.0,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
            "profit_factor": 0.0,
            "total_pnl": 0.0,
            "total_return": 0.0,
            "max_drawdown": 0.0,
            "equity_end": initial_equity,
        }
    df["exit_time"] = pd.to_datetime(df["exit_time"], errors="coerce")
    df = df.sort_values(["exit_time", "entry_time"]).reset_index(drop=True)
    pnl = pd.to_numeric(df["pnl"], errors="coerce").fillna(0.0)
    equity = initial_equity + pnl.cumsum()
    peak = equity.cummax()
    dd = equity / peak - 1.0
    gp = float(pnl[pnl > 0].sum())
    gl = float(-pnl[pnl < 0].sum())
    pf = gp / gl if gl > 0 else (999.0 if gp > 0 else 0.0)
    trades = int(len(df))
    wins = int((pnl > 0).sum())
    return {
        "trades": trades,
        "wins": wins,
        "win_rate": float(wins / trades) if trades else 0.0,
        "gross_profit": gp,
        "gross_loss": gl,
        "profit_factor": float(pf),
        "total_pnl": float(pnl.sum()),
        "total_return": float(equity.iloc[-1] / initial_equity - 1.0),
        "max_drawdown": float(dd.min()) if len(dd) else 0.0,
        "equity_end": float(equity.iloc[-1]) if len(equity) else float(initial_equity),
    }


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def _fmt_num(x: float) -> str:
    return f"{x:+.2f}"


def _load_data(root: Path, cfg: dict[str, Any], start: pd.Timestamp, end: pd.Timestamp) -> dict[str, pd.DataFrame]:
    data_cfg = cfg.get("data", {}) if isinstance(cfg.get("data"), dict) else {}
    symbols = data_cfg.get("symbols", [])
    tmpl = data_cfg.get("csv_template", "data/raw/{symbol}_15m.csv")
    data: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        path = root / str(tmpl).format(symbol=sym)
        df = load_ohlcv_csv(path)
        df = df.loc[(df.index >= start) & (df.index <= end)].copy()
        data[str(sym).lower()] = df
    return data


def _build_pause_windows(start: pd.Timestamp, end: pd.Timestamp, pause_min: int, macro_lead_min: int, macro_post_min: int) -> dict[str, Any]:
    ensure_env_loaded()
    api_key = os.environ.get("COINGLASS_API_KEY", "").strip()
    session = requests.Session()
    news_hits: list[dict[str, Any]] = []
    econ_hits: list[dict[str, Any]] = []
    intervals: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    note = ""
    news_keywords = [
        "war", "attack", "invasion", "missile", "tariff", "sanction", "hack", "exploit", "bankruptcy",
        "liquidation", "emergency", "rate hike", "hawkish", "fomc", "fed", "cpi", "ppi", "nfp", "nonfarm",
    ]
    macro_keywords = ["fomc", "federal reserve", "powell", "rate decision", "interest rate", "cpi", "ppi", "nfp", "nonfarm", "ecb", "boj"]

    if not api_key:
        note = "missing_COINGLASS_API_KEY"
        return {
            "ok": False,
            "note": note,
            "intervals": [],
            "merged_intervals": [],
            "news_hits": [],
            "economic_hits": [],
        }

    news_res = _coinglass_get(session, api_key, "/api/article/list")
    if news_res.get("ok"):
        rows = _extract_items(news_res.get("data"))
        for raw in rows[:120]:
            ts = _extract_time(raw)
            if ts is None:
                continue
            tsn = _ts_naive_utc(ts)
            if tsn is None:
                continue
            if tsn < start - pd.Timedelta(minutes=pause_min) or tsn > end:
                continue
            text_l = _flatten_text(raw).lower()
            if any(k in text_l for k in news_keywords):
                title = _extract_title(raw)
                news_hits.append({"title": title, "ts_utc": str(tsn)})
                intervals.append((tsn, tsn + pd.Timedelta(minutes=pause_min)))

    econ_res = _coinglass_get(session, api_key, "/api/calendar/economic-data")
    if econ_res.get("ok"):
        rows = _extract_items(econ_res.get("data"))
        for raw in rows[:200]:
            ts = _extract_time(raw)
            if ts is None:
                continue
            tsn = _ts_naive_utc(ts)
            if tsn is None:
                continue
            if tsn < start - pd.Timedelta(minutes=macro_lead_min) or tsn > end + pd.Timedelta(minutes=macro_post_min):
                continue
            text_l = _flatten_text(raw).lower()
            if _looks_high_importance(raw) or any(k in text_l for k in macro_keywords):
                title = _extract_title(raw)
                econ_hits.append({"title": title, "ts_utc": str(tsn)})
                intervals.append((tsn - pd.Timedelta(minutes=macro_lead_min), tsn + pd.Timedelta(minutes=macro_post_min)))

    merged = _merge_intervals(intervals)
    return {
        "ok": True,
        "note": note,
        "intervals": [(str(a), str(b)) for a, b in intervals],
        "merged_intervals": [(str(a), str(b)) for a, b in merged],
        "news_hits": news_hits[:20],
        "economic_hits": econ_hits[:20],
    }


def _is_blocked(ts: pd.Timestamp, merged: list[tuple[pd.Timestamp, pd.Timestamp]]) -> bool:
    for start, end in merged:
        if start <= ts <= end:
            return True
        if ts < start:
            return False
    return False


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    base = payload.get("base", {})
    gated = payload.get("gated", {})
    blocked = payload.get("blocked", {})
    window = payload.get("window", {})
    sources = payload.get("sources", {})
    lines = [
        "消息面 × 技术面 联动A/B（近期事件窗，交易级近似）",
        f"生成时间(UTC): {pd.Timestamp.utcnow().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "【窗口】",
        f"- start_utc: {window.get('start_utc', '')}",
        f"- end_utc: {window.get('end_utc', '')}",
        f"- window_days: {window.get('window_days', '')}",
        f"- pause_minutes: {window.get('pause_minutes', '')}",
        f"- macro_lead_minutes: {window.get('macro_lead_minutes', '')}",
        f"- macro_post_minutes: {window.get('macro_post_minutes', '')}",
        "",
        "【基线】",
        f"- trades: {base.get('trades', 0)}",
        f"- win_rate: {_fmt_pct(float(base.get('win_rate', 0.0)))}",
        f"- total_pnl: {_fmt_num(float(base.get('total_pnl', 0.0)))}",
        f"- total_return(近似): {_fmt_pct(float(base.get('total_return', 0.0)))}",
        f"- max_drawdown(近似): {_fmt_pct(float(base.get('max_drawdown', 0.0)))}",
        f"- profit_factor: {float(base.get('profit_factor', 0.0)):.2f}",
        "",
        "【消息暂停层】",
        f"- trades: {gated.get('trades', 0)}",
        f"- win_rate: {_fmt_pct(float(gated.get('win_rate', 0.0)))}",
        f"- total_pnl: {_fmt_num(float(gated.get('total_pnl', 0.0)))}",
        f"- total_return(近似): {_fmt_pct(float(gated.get('total_return', 0.0)))}",
        f"- max_drawdown(近似): {_fmt_pct(float(gated.get('max_drawdown', 0.0)))}",
        f"- profit_factor: {float(gated.get('profit_factor', 0.0)):.2f}",
        "",
        "【被拦截交易】",
        f"- blocked_trades: {blocked.get('trades', 0)}",
        f"- blocked_win_rate: {_fmt_pct(float(blocked.get('win_rate', 0.0)))}",
        f"- blocked_total_pnl: {_fmt_num(float(blocked.get('total_pnl', 0.0)))}",
        f"- blocked_positive_pnl_helpful: {'是' if float(blocked.get('total_pnl', 0.0)) < 0 else '否'}",
        f"- merged_pause_windows: {sources.get('merged_windows', 0)}",
        f"- news_hits: {sources.get('news_hits', 0)}",
        f"- macro_hits: {sources.get('macro_hits', 0)}",
        "",
        "【结论】",
    ]
    dpnl = float(gated.get("total_pnl", 0.0)) - float(base.get("total_pnl", 0.0))
    ddd = float(gated.get("max_drawdown", 0.0)) - float(base.get("max_drawdown", 0.0))
    if int(blocked.get("trades", 0)) == 0:
        lines.append("- 当前窗口没有拦到任何技术开仓，暂时无法证明消息层有用或无用。")
    else:
        lines.append(f"- 对比基线，消息暂停层 PnL 变化: {_fmt_num(dpnl)}")
        lines.append(f"- 对比基线，消息暂停层 MaxDD 变化: {_fmt_pct(ddd)}")
    note = str(sources.get("note", "") or "")
    if note:
        lines.append(f"- 源备注: {note}")
    lines.append("- 说明: 这是近期事件窗、交易级近似 A/B；不是完整引擎级重放。")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="消息面 × 技术面 联动A/B（近期事件窗，交易级近似）")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--window-days", type=int, default=30)
    ap.add_argument("--pause-minutes", type=int, default=120)
    ap.add_argument("--macro-lead-minutes", type=int, default=180)
    ap.add_argument("--macro-post-minutes", type=int, default=30)
    ap.add_argument("--out", default="~/Downloads/message_combo_ab_latest.txt")
    args = ap.parse_args()

    root = Path(args.project_dir).resolve()
    cfg = read_config(root / "config.yml")
    ensure_env_loaded(root=root)

    data_cfg = cfg.get("data", {}) if isinstance(cfg.get("data"), dict) else {}
    symbols = data_cfg.get("symbols", [])
    tmpl = data_cfg.get("csv_template", "data/raw/{symbol}_15m.csv")
    latest_candidates: list[pd.Timestamp] = []
    for sym in symbols:
        path = root / str(tmpl).format(symbol=sym)
        df = load_ohlcv_csv(path)
        if not df.empty:
            latest_candidates.append(pd.Timestamp(df.index.max()))
    if not latest_candidates:
        raise SystemExit("未找到可用行情数据")
    end = min(latest_candidates)
    start = end - pd.Timedelta(days=int(args.window_days))

    data = _load_data(root, cfg, start, end)
    eq_df, trades_df, _snapshot = run_backtest_portfolio(data=data, cfg=cfg)
    initial_equity = float(((cfg.get("portfolio") or {}) if isinstance(cfg.get("portfolio"), dict) else {}).get("initial_equity", 100000.0))

    pauses = _build_pause_windows(start=start, end=end, pause_min=int(args.pause_minutes), macro_lead_min=int(args.macro_lead_minutes), macro_post_min=int(args.macro_post_minutes))
    merged: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    for a, b in pauses.get("merged_intervals", []):
        ta = pd.to_datetime(a)
        tb = pd.to_datetime(b)
        merged.append((ta, tb))

    tdf = trades_df.copy()
    if not tdf.empty:
        tdf["entry_time"] = pd.to_datetime(tdf["entry_time"], errors="coerce")
        blocked_mask = tdf["entry_time"].apply(lambda x: _is_blocked(x, merged) if pd.notna(x) else False)
    else:
        blocked_mask = pd.Series([], dtype=bool)

    base_metrics = _trade_metrics(tdf, initial_equity)
    blocked_trades = tdf.loc[blocked_mask].copy() if not tdf.empty else pd.DataFrame()
    gated_trades = tdf.loc[~blocked_mask].copy() if not tdf.empty else pd.DataFrame()
    gated_metrics = _trade_metrics(gated_trades, initial_equity)
    blocked_metrics = _trade_metrics(blocked_trades, initial_equity)

    payload = {
        "window": {
            "start_utc": str(start),
            "end_utc": str(end),
            "window_days": int(args.window_days),
            "pause_minutes": int(args.pause_minutes),
            "macro_lead_minutes": int(args.macro_lead_minutes),
            "macro_post_minutes": int(args.macro_post_minutes),
        },
        "base": base_metrics,
        "gated": gated_metrics,
        "blocked": blocked_metrics,
        "sources": {
            "note": pauses.get("note", ""),
            "merged_windows": len(pauses.get("merged_intervals", [])),
            "news_hits": len(pauses.get("news_hits", [])),
            "macro_hits": len(pauses.get("economic_hits", [])),
        },
    }

    reports_dir = root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "message_combo_ab_latest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    out_path = Path(os.path.expanduser(args.out)).resolve()
    _write_report(out_path, payload)
    print(json.dumps({"ok": True, "out": str(out_path), "blocked_trades": int(blocked_metrics.get("trades", 0))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
