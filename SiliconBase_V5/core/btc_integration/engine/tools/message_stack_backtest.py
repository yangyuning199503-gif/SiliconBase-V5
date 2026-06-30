from __future__ import annotations

import argparse
import io
import json
import os
import zipfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

if __package__ in (None, ""):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import contextlib

from src.backtest.io import read_config
from tools.okx_demo_common import ensure_env_loaded

DAY = pd.Timedelta(days=1)
H4 = pd.Timedelta(hours=4)

RISK_EVENT_MODES = {"risk_off", "two_sided"}
RESEARCH_EVENT_MODES = {"risk_off", "two_sided", "positive_catalyst", "observation_only"}


def _utc_now() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC")


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def _fmt_num(x: float) -> str:
    return f"{x:+.2f}"


def _truthy(x: Any) -> bool:
    return str(x).strip().lower() in {"1", "true", "yes", "y", "on"}


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
            "equity_end": float(initial_equity),
        }
    pnl = pd.to_numeric(df["pnl"], errors="coerce").fillna(0.0)
    equity = float(initial_equity) + pnl.cumsum()
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
        "total_return": float(equity.iloc[-1] / float(initial_equity) - 1.0),
        "max_drawdown": float(dd.min()) if len(dd) else 0.0,
        "equity_end": float(equity.iloc[-1]) if len(equity) else float(initial_equity),
    }


def _score_variant(base: dict[str, Any], gated: dict[str, Any], blocked_trades: int, initial_equity: float) -> float:
    pnl_delta = float(gated.get("total_pnl", 0.0)) - float(base.get("total_pnl", 0.0))
    dd_delta = float(gated.get("max_drawdown", 0.0)) - float(base.get("max_drawdown", 0.0))
    turn_penalty = max(0, blocked_trades - 5) * 0.001
    return pnl_delta / float(initial_equity) + 2.0 * dd_delta - turn_penalty


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
        for key in [
            "ts", "t", "time", "timestamp", "publishTime", "publishedAt", "releaseTime",
            "date", "datetime", "eventTime", "actualTime", "createdAt", "updatedAt",
            "publish_timestamp", "article_release_time", "release_timestamp", "published_time",
            "publish_utc", "release_utc", "release_time", "pubTime", "article_time",
        ]:
            ts = _parse_time_value(obj.get(key))
            if ts is not None:
                return ts
    return _parse_time_value(obj)


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


def _coerce_float(val: Any) -> float | None:
    if val is None or isinstance(val, bool):
        return None
    try:
        if isinstance(val, (int, float, np.integer, np.floating)):
            return float(val)
        s = str(val).strip().replace(",", "")
        if not s:
            return None
        return float(s)
    except Exception:
        return None


def _numeric_fields(obj: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for k, v in obj.items():
        num = _coerce_float(v)
        if num is not None:
            out[str(k)] = num
    return out


def _rolling_quantile(series: pd.Series, q: float, window: int, min_periods: int) -> pd.Series:
    return series.rolling(window=window, min_periods=min_periods).quantile(q)


def _candidate_payload(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and isinstance(raw.get("response"), dict):
        return raw["response"]
    return raw if isinstance(raw, dict) else {"data": raw}


def _coinglass_get(session: requests.Session, base_url: str, path: str, api_key: str, *, params: dict[str, Any] | None = None, timeout: int = 25) -> dict[str, Any]:
    url = base_url.rstrip("/") + path
    headers = {"accept": "application/json", "CG-API-KEY": api_key}
    out: dict[str, Any] = {"ok": False, "path": path, "params": params or {}}
    try:
        resp = session.get(url, headers=headers, params=params, timeout=timeout)
        out["status_code"] = resp.status_code
        out["ok"] = resp.status_code == 200
        try:
            out["data"] = resp.json()
        except Exception:
            out["data"] = {"raw": resp.text[:5000]}
    except Exception as e:
        out["error"] = str(e)
    return out


def _load_shadow_cfg(root: Path) -> dict[str, Any]:
    p = root / "shadow.yml"
    if not p.exists():
        return {}
    try:
        import yaml
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return data.get("shadow", data) if isinstance(data, dict) else {}


def _coinglass_cfg(root: Path) -> dict[str, Any]:
    shadow = _load_shadow_cfg(root)
    cg = shadow.get("autopilot", {}).get("coinglass") if isinstance(shadow, dict) else None
    return cg if isinstance(cg, dict) else {}


def _load_or_fetch_history(root: Path, *, refresh: bool = False) -> dict[str, dict[str, Any]]:
    ensure_env_loaded(root=root)
    key = os.environ.get("COINGLASS_API_KEY", "").strip()
    cg_cfg = _coinglass_cfg(root)
    base_url = str(cg_cfg.get("base_url", "https://open-api-v4.coinglass.com"))
    raw_dir = root / "data" / "external" / "coinglass"
    raw_dir.mkdir(parents=True, exist_ok=True)
    specs = {
        "oi_agg_btc_1d": {"path": "/api/futures/open-interest/aggregated-history", "params": {"symbol": "BTC", "interval": "1d", "limit": 2500}},
        "lsr_btcusdt_binance_4h": {"path": "/api/futures/global-long-short-account-ratio/history", "params": {"exchange": "Binance", "symbol": "BTCUSDT", "interval": "4h", "limit": 2500}},
        "taker_btcusdt_binance_4h": {"path": "/api/futures/v2/taker-buy-sell-volume/history", "params": {"exchange": "Binance", "symbol": "BTCUSDT", "interval": "4h", "limit": 2500}},
    }
    out: dict[str, dict[str, Any]] = {}
    session = requests.Session()
    for name, spec in specs.items():
        cache = raw_dir / f"{name}.json"
        payload: dict[str, Any] | None = None
        if cache.exists() and not refresh:
            try:
                payload = _candidate_payload(cache)
            except Exception:
                payload = None
        if payload is None:
            if not key:
                payload = {"ok": False, "error": "missing_COINGLASS_API_KEY", "data": {}}
            else:
                payload = _coinglass_get(session, base_url, str(spec["path"]), key, params=dict(spec["params"]))
                with contextlib.suppress(Exception):
                    cache.write_text(json.dumps({"spec": {"name": name, **spec}, "response": payload}, ensure_ascii=False, indent=2), encoding="utf-8")
        out[name] = payload
    return out


def _parse_oi_df(payload: dict[str, Any]) -> pd.DataFrame:
    rows = _extract_items(payload.get("data")) if isinstance(payload, dict) else []
    parsed: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ts = _extract_time(row)
        if ts is None:
            continue
        nums = _numeric_fields(row)
        for k in list(nums.keys()):
            if k.lower() in {"ts", "t", "time", "timestamp"}:
                nums.pop(k, None)
        val = None
        for key in ["c", "close", "closeOi", "closeOI", "closeOpenInterest", "openInterestClose"]:
            if key in row:
                val = _coerce_float(row.get(key))
                if val is not None:
                    break
        if val is None and all(k in row for k in ["o", "h", "l", "c"]):
            val = _coerce_float(row.get("c"))
        if val is None:
            # Prefer the last numeric field, which matches ts,o,h,l,c style payloads.
            ordered_nums = [
                _coerce_float(v) for k, v in row.items()
                if _coerce_float(v) is not None and str(k).lower() not in {"ts", "t", "time", "timestamp"}
            ]
            if ordered_nums:
                val = ordered_nums[-1]
        if val is None:
            continue
        parsed.append({"ts": ts, "oi_close": float(val)})
    df = pd.DataFrame(parsed)
    if df.empty:
        return pd.DataFrame(columns=["effective_time", "oi_close", "oi_ret1d", "oi_down_shock"])
    df = df.sort_values("ts").drop_duplicates(subset=["ts"], keep="last").reset_index(drop=True)
    df["oi_ret1d"] = pd.to_numeric(df["oi_close"], errors="coerce").pct_change()
    q15 = _rolling_quantile(df["oi_ret1d"], 0.15, window=180, min_periods=45)
    df["oi_down_shock"] = df["oi_ret1d"] <= q15
    df["effective_time"] = df["ts"] + DAY
    return df[["effective_time", "oi_close", "oi_ret1d", "oi_down_shock"]]


def _parse_lsr_df(payload: dict[str, Any]) -> pd.DataFrame:
    rows = _extract_items(payload.get("data")) if isinstance(payload, dict) else []
    parsed: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ts = _extract_time(row)
        if ts is None:
            continue
        ratio = None
        for key in ["longShortRatio", "long_short_ratio", "ratio", "lsr", "accountRatio"]:
            if key in row:
                ratio = _coerce_float(row.get(key))
                if ratio is not None:
                    break
        if ratio is None:
            nums = [
                _coerce_float(v) for k, v in row.items()
                if _coerce_float(v) is not None and str(k).lower() not in {"ts", "t", "time", "timestamp"}
            ]
            if nums:
                ratio = nums[-1]
        if ratio is None:
            continue
        parsed.append({"ts": ts, "lsr_ratio": float(ratio)})
    df = pd.DataFrame(parsed)
    if df.empty:
        return pd.DataFrame(columns=["effective_time", "lsr_ratio", "lsr_hi", "lsr_lo"])
    df = df.sort_values("ts").drop_duplicates(subset=["ts"], keep="last").reset_index(drop=True)
    q85 = _rolling_quantile(df["lsr_ratio"], 0.85, window=180, min_periods=60)
    q15 = _rolling_quantile(df["lsr_ratio"], 0.15, window=180, min_periods=60)
    df["lsr_hi"] = df["lsr_ratio"] >= q85
    df["lsr_lo"] = df["lsr_ratio"] <= q15
    df["effective_time"] = df["ts"] + H4
    return df[["effective_time", "lsr_ratio", "lsr_hi", "lsr_lo"]]


def _parse_taker_df(payload: dict[str, Any]) -> pd.DataFrame:
    rows = _extract_items(payload.get("data")) if isinstance(payload, dict) else []
    parsed: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ts = _extract_time(row)
        if ts is None:
            continue
        buy = sell = None
        lowered = {str(k).lower(): v for k, v in row.items()}
        buy_keys = [k for k in lowered if "buy" in k and ("vol" in k or "volume" in k or k == "buy")]
        sell_keys = [k for k in lowered if "sell" in k and ("vol" in k or "volume" in k or k == "sell")]
        for k in buy_keys:
            buy = _coerce_float(lowered.get(k))
            if buy is not None:
                break
        for k in sell_keys:
            sell = _coerce_float(lowered.get(k))
            if sell is not None:
                break
        if buy is None or sell is None:
            nums = [
                _coerce_float(v) for k, v in row.items()
                if _coerce_float(v) is not None and str(k).lower() not in {"ts", "t", "time", "timestamp"}
            ]
            if len(nums) >= 2:
                buy, sell = nums[0], nums[1]
        if buy is None or sell is None or float(sell) == 0.0:
            continue
        ratio = float(buy) / float(sell)
        parsed.append({"ts": ts, "taker_ratio": ratio})
    df = pd.DataFrame(parsed)
    if df.empty:
        return pd.DataFrame(columns=["effective_time", "taker_ratio", "taker_buy", "taker_sell"])
    df = df.sort_values("ts").drop_duplicates(subset=["ts"], keep="last").reset_index(drop=True)
    q85 = _rolling_quantile(df["taker_ratio"], 0.85, window=180, min_periods=60)
    q15 = _rolling_quantile(df["taker_ratio"], 0.15, window=180, min_periods=60)
    df["taker_buy"] = df["taker_ratio"] >= q85
    df["taker_sell"] = df["taker_ratio"] <= q15
    df["effective_time"] = df["ts"] + H4
    return df[["effective_time", "taker_ratio", "taker_buy", "taker_sell"]]


def _load_trades(root: Path, base_trades: Path | None = None) -> pd.DataFrame:
    reports = root / "reports"
    if base_trades is not None:
        p = base_trades if base_trades.is_absolute() else (root / base_trades)
        if not p.exists():
            raise SystemExit(f"指定的基线 trades 不存在：{p}；请先修复原始数据并重跑基线。")
        try:
            df = pd.read_csv(p)
        except Exception as exc:
            raise SystemExit(f"指定的基线 trades 无法读取：{p} | {exc}") from exc
        if df.empty:
            raise SystemExit(f"指定的基线 trades 为空：{p}；当前不会再回退到旧报告或旧 support_bundle。请先修复原始数据并重跑基线。")
        return df

    candidates: list[Path] = []
    if (reports / "run_latest" / "trades.csv").exists():
        candidates.append(reports / "run_latest" / "trades.csv")
    candidates.extend(sorted(reports.glob("run_*/trades.csv"), key=lambda p: p.stat().st_mtime, reverse=True))
    if (root / "run_latest" / "trades.csv").exists():
        candidates.append(root / "run_latest" / "trades.csv")
    seen: set[str] = set()
    for p in candidates:
        key = str(p.resolve()) if p.exists() else str(p)
        if key in seen:
            continue
        seen.add(key)
        try:
            df = pd.read_csv(p)
            if not df.empty:
                return df
        except Exception:
            continue
    bundle = reports / "support_bundle_latest.zip"
    if bundle.exists() and base_trades is None:
        with zipfile.ZipFile(bundle, "r") as zf:
            for member in ["run_latest/trades.csv", "reports/run_latest/trades.csv"]:
                if member in zf.namelist():
                    with zf.open(member) as fh:
                        return pd.read_csv(io.BytesIO(fh.read()))
    raise SystemExit("未找到基线 trades.csv；先运行一次 bash run.sh")


def _load_event_windows(
    root: Path,
    start_utc: pd.Timestamp,
    end_utc: pd.Timestamp,
    *,
    include_all_modes: bool = False,
    allowed_modes: Iterable[str] | None = None,
) -> pd.DataFrame:
    candidates = [
        root / "data" / "events" / "event_windows_v4.csv",
        root / "data" / "events" / "event_windows_v3.csv",
    ]
    path = next((p for p in candidates if p.exists()), None)
    if path is None:
        return pd.DataFrame(columns=["start_utc", "end_utc", "category", "title", "group_id", "event_mode"])
    df = pd.read_csv(path)
    if df.empty:
        return df
    df["start_utc"] = pd.to_datetime(df["start_utc"], utc=True, errors="coerce")
    df["end_utc"] = pd.to_datetime(df["end_utc"], utc=True, errors="coerce")
    df = df.dropna(subset=["start_utc", "end_utc"]).copy()
    if "enabled" in df.columns:
        df = df[df["enabled"].map(_truthy)]
    modes = {str(x) for x in (allowed_modes or (RESEARCH_EVENT_MODES if include_all_modes else RISK_EVENT_MODES))}
    if "event_mode" in df.columns and modes:
        df = df[df["event_mode"].astype(str).isin(modes)]
    if "group_id" not in df.columns:
        df["group_id"] = df.get("title", pd.Series([""] * len(df), index=df.index)).astype(str)
    df = df[(df["end_utc"] >= start_utc) & (df["start_utc"] <= end_utc)].copy()
    return df.sort_values(["start_utc", "end_utc", "title"]).reset_index(drop=True)


def _assign_event_annotations(
    trades: pd.DataFrame,
    windows: pd.DataFrame,
    *,
    block_modes: Iterable[str] | None = None,
) -> dict[str, Any]:
    blocked = pd.Series(False, index=trades.index)
    identified = pd.Series(False, index=trades.index)
    cats: list[str] = []
    titles: list[str] = []
    groups: list[str] = []
    modes_out: list[str] = []
    block_mode_set = {str(x) for x in (block_modes or RISK_EVENT_MODES)}
    if windows.empty:
        blank = [""] * len(trades)
        return {
            "blocked": blocked,
            "identified": identified,
            "categories": blank,
            "titles": blank,
            "groups": blank,
            "modes": blank,
        }
    for idx, row in trades.iterrows():
        ts = row["entry_time_utc"]
        matched = windows[(windows["start_utc"] <= ts) & (windows["end_utc"] >= ts)]
        if matched.empty:
            cats.append("")
            titles.append("")
            groups.append("")
            modes_out.append("")
            continue
        identified.loc[idx] = True
        matched_modes = sorted({str(x) for x in matched.get("event_mode", pd.Series(dtype=str)).astype(str).tolist() if str(x)})
        if any(mode in block_mode_set for mode in matched_modes):
            blocked.loc[idx] = True
        cats.append("|".join(sorted({str(x) for x in matched["category"].astype(str).tolist() if str(x)}))[:200])
        titles.append(" | ".join([str(x) for x in matched["title"].astype(str).tolist()[:3]])[:240])
        groups.append("|".join(sorted({str(x) for x in matched["group_id"].astype(str).tolist() if str(x)}))[:200])
        modes_out.append("|".join(matched_modes)[:200])
    return {
        "blocked": blocked,
        "identified": identified,
        "categories": cats,
        "titles": titles,
        "groups": groups,
        "modes": modes_out,
    }



def _assign_event_blocks(trades: pd.DataFrame, windows: pd.DataFrame) -> tuple[pd.Series, list[str], list[str], list[str]]:
    ann = _assign_event_annotations(trades, windows, block_modes=RISK_EVENT_MODES)
    return ann["blocked"], ann["categories"], ann["titles"], ann["groups"]


def _to_utc_ns(values: pd.Series | pd.Index | list | tuple) -> pd.Series:
    s = pd.to_datetime(values, utc=True, errors="coerce")
    with contextlib.suppress(TypeError, ValueError):
        s = s.astype("datetime64[ns, UTC]")
    return s


def _normalize_asof_frame(df: pd.DataFrame, time_col: str = "effective_time") -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame() if df is None else df.copy()
    out = df.copy()
    if time_col in out.columns:
        out[time_col] = _to_utc_ns(out[time_col])
        out = out.dropna(subset=[time_col]).sort_values(time_col).reset_index(drop=True)
    return out


def _attach_features(trades: pd.DataFrame, oi_df: pd.DataFrame, lsr_df: pd.DataFrame, taker_df: pd.DataFrame) -> pd.DataFrame:
    t = trades.copy()
    entry_src = t["entry_time"] if "entry_time" in t.columns else t.get("entry_time_utc")
    exit_src = t["exit_time"] if "exit_time" in t.columns else t.get("exit_time_utc")
    t["entry_time_utc"] = _to_utc_ns(entry_src)
    t["exit_time_utc"] = _to_utc_ns(exit_src)
    t = t.dropna(subset=["entry_time_utc", "exit_time_utc"]).sort_values("entry_time_utc").reset_index(drop=True)
    oi_df = _normalize_asof_frame(oi_df, "effective_time")
    lsr_df = _normalize_asof_frame(lsr_df, "effective_time")
    taker_df = _normalize_asof_frame(taker_df, "effective_time")
    if not oi_df.empty:
        t = pd.merge_asof(t, oi_df, left_on="entry_time_utc", right_on="effective_time", direction="backward")
    else:
        t["oi_close"] = np.nan
        t["oi_ret1d"] = np.nan
        t["oi_down_shock"] = False
    if not lsr_df.empty:
        t = pd.merge_asof(t, lsr_df, left_on="entry_time_utc", right_on="effective_time", direction="backward", suffixes=("", "_lsr"))
    else:
        t["lsr_ratio"] = np.nan
        t["lsr_hi"] = False
        t["lsr_lo"] = False
    if not taker_df.empty:
        t = pd.merge_asof(t, taker_df, left_on="entry_time_utc", right_on="effective_time", direction="backward", suffixes=("", "_taker"))
    else:
        t["taker_ratio"] = np.nan
        t["taker_buy"] = False
        t["taker_sell"] = False

    for col in ["oi_down_shock", "lsr_hi", "lsr_lo", "taker_buy", "taker_sell"]:
        if col not in t.columns:
            t[col] = False
        t[col] = t[col].where(t[col].notna(), False).astype(bool)

    t["cg_long_risk"] = t["oi_down_shock"] | (t["lsr_hi"] & t["taker_sell"])
    t["cg_short_risk"] = t["lsr_lo"] & t["taker_buy"]
    return t


def _variant_mask(trades: pd.DataFrame, variant: str) -> pd.Series:
    side = trades["side"].astype(str).str.upper()
    event_mask = trades.get("event_blocked", pd.Series(False, index=trades.index)).fillna(False).astype(bool)
    cg_long = trades.get("cg_long_risk", pd.Series(False, index=trades.index)).fillna(False).astype(bool)
    cg_short = trades.get("cg_short_risk", pd.Series(False, index=trades.index)).fillna(False).astype(bool)
    cg_mask = ((side == "LONG") & cg_long) | ((side == "SHORT") & cg_short)
    if variant == "no_guard":
        return pd.Series(False, index=trades.index)
    if variant == "event_only":
        return event_mask
    if variant == "coinglass_only":
        return cg_mask
    if variant == "combined_stack":
        return event_mask | cg_mask
    raise KeyError(variant)


def _evaluate_variant(trades: pd.DataFrame, variant: str, initial_equity: float) -> dict[str, Any]:
    blocked_mask = _variant_mask(trades, variant)
    blocked_df = trades.loc[blocked_mask].copy()
    gated_df = trades.loc[~blocked_mask].copy()
    base_metrics = _trade_metrics(trades, initial_equity)
    gated_metrics = _trade_metrics(gated_df, initial_equity)
    pnl_delta = float(gated_metrics["total_pnl"] - base_metrics["total_pnl"])
    dd_delta = float(gated_metrics["max_drawdown"] - base_metrics["max_drawdown"])
    return {
        "variant": variant,
        "blocked_trades": int(len(blocked_df)),
        "blocked_long": int((blocked_df["side"].astype(str).str.upper() == "LONG").sum()) if not blocked_df.empty else 0,
        "blocked_short": int((blocked_df["side"].astype(str).str.upper() == "SHORT").sum()) if not blocked_df.empty else 0,
        "top_event_groups": blocked_df.get("event_group", pd.Series(dtype=str)).replace("", pd.NA).dropna().astype(str).value_counts().head(5).index.tolist(),
        "base": base_metrics,
        "gated": gated_metrics,
        "pnl_delta": pnl_delta,
        "dd_delta": dd_delta,
        "score": _score_variant(base_metrics, gated_metrics, int(len(blocked_df)), initial_equity),
        "blocked_df": blocked_df,
        "gated_df": gated_df,
    }


def _calendar_year_folds(trades: pd.DataFrame) -> list[tuple[int, pd.Timestamp, pd.Timestamp]]:
    years = sorted(int(y) for y in trades["entry_time_utc"].dt.year.unique())
    folds: list[tuple[int, pd.Timestamp, pd.Timestamp]] = []
    for y in years[1:]:
        start = pd.Timestamp(f"{y}-01-01 00:00:00", tz="UTC")
        end = pd.Timestamp(f"{y + 1}-01-01 00:00:00", tz="UTC")
        folds.append((y, start, end))
    return folds


def _walkforward(trades: pd.DataFrame, initial_equity: float, variants: list[str]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    aggregate_blocked = 0
    aggregate_pnl_delta = 0.0
    aggregate_dd_delta = 0.0
    selected_nonbase = 0
    for year, start, end in _calendar_year_folds(trades):
        train = trades[trades["entry_time_utc"] < start].copy()
        test = trades[(trades["entry_time_utc"] >= start) & (trades["entry_time_utc"] < end)].copy()
        if train.empty or test.empty:
            continue
        train_evals = {v: _evaluate_variant(train, v, initial_equity) for v in variants}
        best = "no_guard"
        best_score = 0.0
        for v in variants:
            ev = train_evals[v]
            if ev["blocked_trades"] <= 0:
                continue
            if ev["score"] > best_score:
                best_score = float(ev["score"])
                best = v
        test_eval = _evaluate_variant(test, best, initial_equity)
        if best != "no_guard":
            selected_nonbase += 1
        aggregate_blocked += int(test_eval["blocked_trades"])
        aggregate_pnl_delta += float(test_eval["pnl_delta"])
        aggregate_dd_delta += float(test_eval["dd_delta"])
        rows.append({
            "year": year,
            "train_best": best,
            "train_score": best_score,
            "test_blocked": int(test_eval["blocked_trades"]),
            "test_pnl_delta": float(test_eval["pnl_delta"]),
            "test_dd_delta": float(test_eval["dd_delta"]),
        })
    return {
        "rows": rows,
        "aggregate_blocked": aggregate_blocked,
        "aggregate_pnl_delta": aggregate_pnl_delta,
        "aggregate_dd_delta": aggregate_dd_delta,
        "selected_nonbase_folds": selected_nonbase,
    }


def run(project_dir: Path, out: Path, *, refresh: bool = False, base_trades: Path | None = None) -> None:
    cfg = read_config(project_dir / "config.yml")
    initial_equity = float(cfg.get("portfolio", {}).get("initial_equity", 100000.0))
    trades = _load_trades(project_dir, base_trades=base_trades)
    hist = _load_or_fetch_history(project_dir, refresh=refresh)
    oi_df = _parse_oi_df(hist.get("oi_agg_btc_1d", {}))
    lsr_df = _parse_lsr_df(hist.get("lsr_btcusdt_binance_4h", {}))
    taker_df = _parse_taker_df(hist.get("taker_btcusdt_binance_4h", {}))

    trades = _attach_features(trades, oi_df, lsr_df, taker_df)
    start_utc = trades["entry_time_utc"].min().floor("15min")
    end_utc = trades["entry_time_utc"].max().ceil("15min")
    windows = _load_event_windows(project_dir, start_utc, end_utc)
    event_mask, event_cats, event_titles, event_groups = _assign_event_blocks(trades, windows)
    trades["event_blocked"] = event_mask.values
    trades["event_category"] = event_cats
    trades["event_title"] = event_titles
    trades["event_group"] = event_groups

    variants = ["no_guard", "event_only", "coinglass_only", "combined_stack"]
    evals = {v: _evaluate_variant(trades, v, initial_equity) for v in variants}

    recent_start = None
    if not lsr_df.empty and not taker_df.empty:
        recent_start = max(lsr_df["effective_time"].min(), taker_df["effective_time"].min())
    recent_evals: dict[str, dict[str, Any]] = {}
    if recent_start is not None:
        recent_trades = trades[trades["entry_time_utc"] >= recent_start].copy()
        if not recent_trades.empty:
            recent_evals = {v: _evaluate_variant(recent_trades, v, initial_equity) for v in variants}

    wf = _walkforward(trades, initial_equity, variants)

    base = evals["no_guard"]["base"]
    lines: list[str] = []
    lines.append("消息面联动回测（技术面 + 事件库 + CoinGlass历史特征）")
    lines.append(f"生成时间(UTC): {_utc_now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("【基线】")
    lines.append(f"- trades={base['trades']} win_rate={_fmt_pct(base['win_rate'])} pf={base['profit_factor']:.2f} total_ret={_fmt_pct(base['total_return'])} maxdd={_fmt_pct(base['max_drawdown'])}")
    lines.append("")
    lines.append("【消息面覆盖】")
    lines.append(f"- event_windows={len(windows)}")
    lines.append(f"- coinglass_oi_rows={len(oi_df)} range={oi_df['effective_time'].min() if not oi_df.empty else '-'} -> {oi_df['effective_time'].max() if not oi_df.empty else '-'}")
    lines.append(f"- coinglass_lsr_rows={len(lsr_df)} range={lsr_df['effective_time'].min() if not lsr_df.empty else '-'} -> {lsr_df['effective_time'].max() if not lsr_df.empty else '-'}")
    lines.append(f"- coinglass_taker_rows={len(taker_df)} range={taker_df['effective_time'].min() if not taker_df.empty else '-'} -> {taker_df['effective_time'].max() if not taker_df.empty else '-'}")
    lines.append(f"- trades_with_oi_feature={int(trades['oi_ret1d'].notna().sum())}")
    lines.append(f"- trades_with_lsr_taker_feature={int((trades['lsr_ratio'].notna() & trades['taker_ratio'].notna()).sum())}")
    lines.append("")
    lines.append("【全样本固定规则】")
    for v in ["event_only", "coinglass_only", "combined_stack"]:
        ev = evals[v]
        lines.append(
            f"- {v}: blocked={ev['blocked_trades']} (long={ev['blocked_long']}, short={ev['blocked_short']}) | "
            f"pnl_delta={_fmt_num(ev['pnl_delta'])} | maxdd_delta={_fmt_pct(ev['dd_delta'])} | score={ev['score']:+.4f}"
        )
        if ev["top_event_groups"]:
            lines.append(f"  top_event_groups={'; '.join(ev['top_event_groups'][:5])}")
    if recent_evals:
        lines.append("")
        lines.append("【近一年 CoinGlass 组合窗口】")
        lines.append(f"- recent_start={recent_start}")
        for v in ["coinglass_only", "combined_stack"]:
            ev = recent_evals[v]
            lines.append(
                f"- {v}: blocked={ev['blocked_trades']} | pnl_delta={_fmt_num(ev['pnl_delta'])} | maxdd_delta={_fmt_pct(ev['dd_delta'])} | score={ev['score']:+.4f}"
            )
    lines.append("")
    lines.append("【滚动样本外】")
    if wf["rows"]:
        for row in wf["rows"]:
            lines.append(
                f"- {row['year']}: train_best={row['train_best']} | test_blocked={row['test_blocked']} | "
                f"pnl_delta={_fmt_num(row['test_pnl_delta'])} | maxdd_delta={_fmt_pct(row['test_dd_delta'])}"
            )
        lines.append(
            f"- aggregate: selected_nonbase_folds={wf['selected_nonbase_folds']} | blocked={wf['aggregate_blocked']} | "
            f"pnl_delta={_fmt_num(wf['aggregate_pnl_delta'])} | maxdd_delta={_fmt_pct(wf['aggregate_dd_delta'])}"
        )
    else:
        lines.append("- insufficient_folds")
    lines.append("")
    lines.append("【结论】")
    combo = evals["combined_stack"]
    if wf["aggregate_blocked"] <= 0:
        lines.append("- 组合消息面样本外仍然太弱；先继续放在 risk layer，不升 alpha。")
    elif combo["score"] > 0 and wf["aggregate_pnl_delta"] >= 0 and wf["aggregate_dd_delta"] >= 0:
        lines.append("- 组合消息面比单独事件库/单独CoinGlass更值得继续保留在 risk layer；仍不升 alpha。")
    else:
        lines.append("- 组合消息面已能做 A/B，但当前证据还不够稳；继续扩样本，不增加规则复杂度。")
    lines.append("- 这版不是只测 CoinGlass，而是：事件库窗口 + CoinGlass 历史结构化特征一起联动。")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Run combined message-stack backtest using event windows plus CoinGlass historical features.")
    ap.add_argument("--project-dir", type=Path, default=Path("."))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--base-trades", type=Path, default=None)
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    base_trades = args.base_trades.resolve() if args.base_trades is not None else None
    run(args.project_dir.resolve(), args.out, refresh=bool(args.refresh), base_trades=base_trades)


if __name__ == "__main__":
    main()
