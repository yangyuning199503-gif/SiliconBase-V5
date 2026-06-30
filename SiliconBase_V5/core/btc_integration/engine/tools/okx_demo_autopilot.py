from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except Exception:
    pd = None  # type: ignore[assignment]
    PANDAS_AVAILABLE = False

import contextlib

import requests
import yaml

# 处理导入路径（支持直接运行和模块导入）
if __package__ in (None, ""):
    # 直接运行脚本模式
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.okx_demo_common import ensure_env_loaded, load_credentials, now_utc_text
else:
    # 模块导入模式
    from .okx_demo_common import ensure_env_loaded, load_credentials, now_utc_text

_STOP = False


def _on_stop(signum, frame):  # type: ignore[no-untyped-def]
    global _STOP
    _STOP = True


signal.signal(signal.SIGTERM, _on_stop)
signal.signal(signal.SIGINT, _on_stop)


def _utc_now() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC")


def _bar_to_seconds(bar: str) -> int:
    mapping = {
        "1m": 60,
        "3m": 180,
        "5m": 300,
        "15m": 900,
        "30m": 1800,
        "1h": 3600,
        "2h": 7200,
        "4h": 14400,
        "6h": 21600,
        "12h": 43200,
        "1d": 86400,
    }
    key = str(bar).strip().lower()
    if key not in mapping:
        raise ValueError(f"unsupported bar: {bar}")
    return mapping[key]


def _expand_path(root: Path, raw: str | Path) -> Path:
    p = Path(os.path.expanduser(str(raw)))
    if not p.is_absolute():
        p = root / p
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load_shadow_cfg(root: Path) -> dict[str, Any]:
    p = root / "shadow.yml"
    if not p.exists():
        return {}
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return data.get("shadow", data) if isinstance(data, dict) else {}
    except Exception:
        return {}


def _load_autopilot_cfg(root: Path) -> dict[str, Any]:
    shadow = _load_shadow_cfg(root)
    cfg = shadow.get("autopilot", {}) if isinstance(shadow, dict) else {}
    return cfg if isinstance(cfg, dict) else {}


def _completed_bar_open_ms(bar: str) -> int:
    step = _bar_to_seconds(bar) * 1000
    now_ms = int(time.time() * 1000)
    cur_open = (now_ms // step) * step
    return cur_open - step


def _due_ts_for_completed_open_ms(open_ms: int, bar: str, grace_seconds: int) -> pd.Timestamp:
    step = _bar_to_seconds(bar)
    return pd.Timestamp((open_ms // 1000) + step, unit="s", tz="UTC") + pd.Timedelta(seconds=grace_seconds)


def _ts_text(ts: pd.Timestamp | None) -> str:
    if ts is None:
        return ""
    try:
        return ts.tz_convert("UTC").strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts)


def _to_utc_ts(value: Any) -> pd.Timestamp | None:
    if value is None or value == "":
        return None
    try:
        ts = value if isinstance(value, pd.Timestamp) else pd.to_datetime(value, utc=False)
        if ts.tzinfo is None:
            return ts.tz_localize("UTC")
        return ts.tz_convert("UTC")
    except Exception:
        return None


def _fmt_ts_utc(value: Any) -> str:
    ts = _to_utc_ts(value)
    if ts is None:
        return ""
    return ts.tz_convert("UTC").strftime("%Y-%m-%d %H:%M:%S")


def _fmt_ts_local(value: Any, tz_name: str) -> str:
    ts = _to_utc_ts(value)
    if ts is None:
        return ""
    try:
        return ts.tz_convert(tz_name).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ts.tz_convert("Asia/Shanghai").strftime("%Y-%m-%d %H:%M:%S")


def _now_local_text(tz_name: str) -> str:
    try:
        return pd.Timestamp.now(tz="UTC").tz_convert(tz_name).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return pd.Timestamp.now(tz="UTC").tz_convert("Asia/Shanghai").strftime("%Y-%m-%d %H:%M:%S")


def _log(display_tz: str, display_tz_label: str, message: str) -> None:
    print(f"[{display_tz_label} {_now_local_text(display_tz)}] {message}", flush=True)


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _flatten_text(x: Any) -> str:
    parts: list[str] = []

    def _walk(obj: Any) -> None:
        if obj is None:
            return
        if isinstance(obj, (str, int, float, bool)):
            s = str(obj).strip()
            if s:
                parts.append(s)
            return
        if isinstance(obj, dict):
            for v in obj.values():
                _walk(v)
            return
        if isinstance(obj, (list, tuple, set)):
            for v in obj:
                _walk(v)
            return

    _walk(x)
    return " | ".join(parts)




def _is_url_like(s: str) -> bool:
    s = str(s or "").strip().lower()
    return (
        s.startswith("http://")
        or s.startswith("https://")
        or s.endswith(".jpg")
        or s.endswith(".jpeg")
        or s.endswith(".png")
        or s.endswith(".webp")
        or s.endswith(".gif")
    )


def _clean_text(s: Any) -> str:
    txt = str(s or "").replace("\n", " ").replace("\r", " ").replace("\xa0", " ").strip()
    while "  " in txt:
        txt = txt.replace("  ", " ")
    return txt[:180]

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


def _extract_time(obj: Any) -> pd.Timestamp | None:
    if isinstance(obj, dict):
        candidates = [
            obj.get("ts"),
            obj.get("time"),
            obj.get("timestamp"),
            obj.get("publishTime"),
            obj.get("publishedAt"),
            obj.get("releaseTime"),
            obj.get("date"),
            obj.get("datetime"),
            obj.get("eventTime"),
            obj.get("actualTime"),
            obj.get("createdAt"),
            obj.get("updatedAt"),
        ]
        for val in candidates:
            ts = _parse_time_value(val)
            if ts is not None:
                return ts
    return _parse_time_value(obj)


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
        txt = _clean_text(val)
        if txt and not _is_url_like(txt):
            return txt
    flat = _clean_text(_flatten_text(obj))
    parts = [p.strip() for p in flat.split(" | ") if p.strip()]
    for part in parts:
        txt = _clean_text(part)
        if len(txt) >= 8 and not _is_url_like(txt):
            return txt
    return flat[:180]


def _coinglass_get(session: requests.Session, base_url: str, path: str, api_key: str, *, params: dict[str, Any] | None = None, timeout: int = 18) -> dict[str, Any]:
    url = base_url.rstrip("/") + path
    headers = {"accept": "application/json", "CG-API-KEY": api_key}
    out: dict[str, Any] = {"ok": False, "url": url, "path": path}
    try:
        resp = session.get(url, headers=headers, params=params, timeout=timeout)
        out["status_code"] = resp.status_code
        out["ok"] = resp.status_code == 200
        try:
            out["data"] = resp.json()
        except Exception:
            out["data"] = {"raw": resp.text[:4000]}
    except Exception as e:
        out["error"] = str(e)
    return out


def _news_keywords_default() -> list[str]:
    return [
        "war",
        "attack",
        "invasion",
        "missile",
        "tariff",
        "sanction",
        "hack",
        "exploit",
        "bankruptcy",
        "liquidation",
        "emergency",
        "rate hike",
        "hawkish",
        "fomc",
        "fed",
        "cpi",
        "ppi",
        "nfp",
        "nonfarm",
    ]


def _macro_keywords_default() -> list[str]:
    return [
        "fomc",
        "federal reserve",
        "powell",
        "jerome powell",
        "rate decision",
        "dot plot",
        "interest rate",
        "cpi",
        "ppi",
        "nfp",
        "nonfarm",
        "ecb",
        "boj",
    ]


def _fomc_keywords_default() -> list[str]:
    return [
        "fomc",
        "federal reserve",
        "powell",
        "jerome powell",
        "rate decision",
        "dot plot",
        "interest rate",
    ]


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


def _coinglass_snapshot(root: Path, session: requests.Session, cfg: dict[str, Any]) -> dict[str, Any]:
    auth_cfg = _load_shadow_cfg(root).get("auth", {}) if isinstance(_load_shadow_cfg(root), dict) else {}
    # Load env file first so COINGLASS_API_KEY is available even if OKX vars were already exported elsewhere.
    ensure_env_loaded(root=root)
    load_credentials(auth_cfg if isinstance(auth_cfg, dict) else {}, root=root)

    api_key = os.environ.get("COINGLASS_API_KEY", "").strip()
    cg_cfg = cfg.get("coinglass", {}) if isinstance(cfg.get("coinglass"), dict) else {}
    enabled = bool(cg_cfg.get("enabled", True))
    base_url = str(cg_cfg.get("base_url", "https://open-api-v4.coinglass.com"))
    news_path = str(cg_cfg.get("news_path", "/api/article/list"))
    economic_path = str(cg_cfg.get("economic_path", "/api/calendar/economic-data"))
    news_limit = int(cg_cfg.get("report_headlines", 5))
    news_lookback_min = int(cg_cfg.get("news_pause_lookback_minutes", 120))
    macro_lead_min = int(cg_cfg.get("macro_pause_lead_minutes", 180))
    macro_post_min = int(cg_cfg.get("macro_pause_post_minutes", 30))
    fomc_lead_min = int(cg_cfg.get("fomc_pause_lead_minutes", 360))
    fomc_post_min = int(cg_cfg.get("fomc_pause_post_minutes", 180))
    news_keywords = [str(x).lower() for x in cg_cfg.get("news_pause_keywords", _news_keywords_default())]
    macro_keywords = [str(x).lower() for x in cg_cfg.get("macro_keywords", _macro_keywords_default())]
    fomc_keywords = [str(x).lower() for x in cg_cfg.get("fomc_keywords", _fomc_keywords_default())]

    snap: dict[str, Any] = {
        "enabled": enabled,
        "api_key_present": bool(api_key),
        "mode": "normal",
        "reason": "",
        "note": "",
        "news": {"ok": False, "items": []},
        "economic": {"ok": False, "items": []},
        "matched_reasons": [],
        "until_utc": None,
        "event_type": "",
    }
    if not enabled:
        snap["note"] = "coinglass_disabled"
        return snap
    if not api_key:
        snap["note"] = "missing_COINGLASS_API_KEY"
        return snap

    now = _utc_now()
    matched: list[str] = []
    until_candidates: list[pd.Timestamp] = []

    news_res = _coinglass_get(session, base_url, news_path, api_key)
    news_items: list[dict[str, Any]] = []
    if news_res.get("ok"):
        rows = _extract_items(news_res.get("data"))
        for raw in rows[:60]:
            title = _extract_title(raw)
            ts = _extract_time(raw)
            if title and not _is_url_like(title):
                news_items.append({
                    "title": title,
                    "ts_utc": _ts_text(ts),
                    "age_minutes": float((now - ts).total_seconds() / 60.0) if ts is not None else None,
                })
            text_l = _flatten_text(raw).lower()
            recent_ok = ts is None or (now - ts) <= pd.Timedelta(minutes=news_lookback_min)
            if recent_ok and any(k in text_l for k in news_keywords):
                safe_title = title if title and not _is_url_like(title) else "matched_news_keyword"
                matched.append(f"news:{safe_title[:80]}")
                if ts is not None:
                    until_candidates.append(ts + pd.Timedelta(minutes=news_lookback_min))
        snap["news"] = {"ok": True, "status_code": news_res.get("status_code"), "items": news_items[:news_limit]}
    else:
        snap["news"] = {"ok": False, "status_code": news_res.get("status_code"), "error": news_res.get("error")}

    econ_res = _coinglass_get(session, base_url, economic_path, api_key)
    econ_items: list[dict[str, Any]] = []
    if econ_res.get("ok"):
        rows = _extract_items(econ_res.get("data"))
        for raw in rows[:80]:
            title = _extract_title(raw)
            ts = _extract_time(raw)
            econ_items.append({
                "title": title,
                "ts_utc": _ts_text(ts),
                "high_importance": _looks_high_importance(raw),
            })
            if ts is None:
                continue
            diff_min = (ts - now).total_seconds() / 60.0
            text_l = _flatten_text(raw).lower()
            is_fomc = any(k in text_l for k in fomc_keywords)
            if is_fomc and -fomc_post_min <= diff_min <= fomc_lead_min:
                matched.append(f"fomc:{title[:80]}")
                until_candidates.append(ts + pd.Timedelta(minutes=fomc_post_min))
                snap["event_type"] = snap.get("event_type") or "fomc"
            elif -macro_post_min <= diff_min <= macro_lead_min:
                if _looks_high_importance(raw) or any(k in text_l for k in macro_keywords):
                    matched.append(f"macro:{title[:80]}")
                    until_candidates.append(ts + pd.Timedelta(minutes=macro_post_min))
        snap["economic"] = {"ok": True, "status_code": econ_res.get("status_code"), "items": econ_items[:news_limit]}
    else:
        snap["economic"] = {"ok": False, "status_code": econ_res.get("status_code"), "error": econ_res.get("error")}

    if matched:
        snap["mode"] = "pause_new_entries"
        snap["reason"] = matched[0]
        snap["matched_reasons"] = matched[:8]
        if until_candidates:
            until_utc = max(until_candidates)
            snap["until_utc"] = _ts_text(until_utc)
    return snap




def _free_feeds_snapshot(root: Path) -> dict[str, Any]:
    snap: dict[str, Any] = {
        "enabled": True,
        "status": "not_loaded",
        "notes": [],
        "blockbeats": {},
        "binance": {},
        "deribit": {},
        "fng": {},
        "use": "observe_only",
    }
    try:
        from tools.free_feeds_probe import probe_binance_crowding, probe_blockbeats, probe_deribit, probe_fng
    except Exception as e:
        snap["status"] = "module_unavailable"
        snap["notes"] = [f"free_feeds_import_error={type(e).__name__}:{e}"]
        return snap

    notes: list[str] = []
    session = requests.Session()
    try:
        bb, bb_notes = probe_blockbeats(session)
        btc, btc_notes = probe_binance_crowding(session, "BTCUSDT")
        bnb, bnb_notes = probe_binance_crowding(session, "BNBUSDT")
        deribit, deribit_notes = probe_deribit(session)
        fng, fng_notes = probe_fng(session)
        notes.extend(bb_notes)
        notes.extend(btc_notes)
        notes.extend(bnb_notes)
        notes.extend(deribit_notes)
        notes.extend(fng_notes)
        snap.update(
            {
                "status": "ok",
                "blockbeats": bb,
                "binance": {"BTCUSDT": btc, "BNBUSDT": bnb},
                "deribit": deribit,
                "fng": fng,
                "notes": notes[:8],
            }
        )
        return snap
    except Exception as e:
        snap["status"] = "failed"
        snap["notes"] = [f"free_feeds_runtime_error={type(e).__name__}:{e}"]
        return snap
    finally:
        with contextlib.suppress(Exception):
            session.close()


def _bool_zh(x: Any) -> str:
    return "是" if bool(x) else "否"


_KIND_ZH = {
    "open": "开仓",
    "add": "加仓",
    "flatten": "平仓",
    "trim": "减仓",
    "flip_flatten": "反手先平",
    "flip_open": "反手再开",
    "hold": "保持",
    "noop_flat": "空仓保持",
    "noop_risk_pause": "风险暂停新开仓",
}


def _status_zh(status: str) -> str:
    mapping = {
        "starting": "启动中",
        "waiting": "等待下一轮",
        "running": "运行中",
        "paused": "已暂停",
        "stopped": "已停止",
    }
    s = str(status or "").strip().lower()
    return mapping.get(s, s or "")


def _compact_text(x: Any) -> str:
    if x is None:
        return ""
    s = str(x).strip()
    return s


def _action_line(action: dict[str, Any]) -> str:
    kind = str(action.get("kind", "")).lower()
    kind_zh = _KIND_ZH.get(kind, kind or "-")
    side = _compact_text(action.get("side"))
    qty = _compact_text(action.get("qty"))
    reduce_only = action.get("reduce_only")
    extras = []
    if side:
        extras.append(f"side={side}")
    if qty:
        extras.append(f"qty={qty}")
    if reduce_only not in {None, ""}:
        extras.append(f"reduceOnly={reduce_only}")
    return f"{kind_zh}" + (f" ({', '.join(extras)})" if extras else "")


def _exec_line(ex: dict[str, Any], tz_name: str) -> str:
    payload = ex.get("payload", {}) if isinstance(ex.get("payload"), dict) else {}
    order = ex.get("order", {}) if isinstance(ex.get("order"), dict) else {}
    row = order.get("row", {}) if isinstance(order.get("row"), dict) else {}
    state = _compact_text(row.get("state"))
    avg_px = _compact_text(row.get("avgPx") or row.get("fillPx") or row.get("pxAvg"))
    fill_sz = _compact_text(row.get("fillSz") or row.get("accFillSz"))
    event_time = _fmt_ts_local(row.get("uTime") or row.get("fillTime") or row.get("cTime"), tz_name)
    parts = [
        f"ordId={_compact_text(ex.get('ord_id')) or '-'}",
        f"side={_compact_text(payload.get('side')) or '-'}",
        f"qty={_compact_text(payload.get('sz')) or '-'}",
        f"filled={_compact_text(ex.get('filled')) or '-'}",
    ]
    if state:
        parts.append(f"state={state}")
    if avg_px:
        parts.append(f"avgPx={avg_px}")
    if fill_sz:
        parts.append(f"fillSz={fill_sz}")
    if event_time:
        parts.append(f"time({tz_name})={event_time}")
    return " | ".join(parts)


def _symbol_detail_lines(report: dict[str, Any], tz_name: str) -> list[str]:
    lines: list[str] = []
    syms = report.get("symbols", {}) if isinstance(report.get("symbols"), dict) else {}
    syncs = report.get("data_sync", {}) if isinstance(report.get("data_sync"), dict) else {}
    if not syms:
        lines.append("- 暂无标的明细（尚未执行过一轮）")
        return lines
    for sym, item in syms.items():
        if not isinstance(item, dict):
            continue
        desired = item.get("desired_signal", {}) if isinstance(item.get("desired_signal"), dict) else {}
        current_before = item.get("current_position_before", {}) if isinstance(item.get("current_position_before"), dict) else {}
        current = item.get("current_position", {}) if isinstance(item.get("current_position"), dict) else {}
        lines.append(f"[{str(sym).upper()}]")
        lines.append(
            f"- 策略目标: side={_compact_text(desired.get('side')) or '-'} mode={_compact_text(desired.get('mode')) or '-'} tag={_compact_text(desired.get('tag')) or '-'}"
        )
        before_sig = (
            _compact_text(current_before.get('side')),
            _compact_text(current_before.get('signed_qty')),
            _compact_text(current_before.get('abs_qty')),
            _compact_text(current_before.get('unrealized_pnl')),
            _compact_text(current_before.get('notional_usd')),
        )
        current_sig = (
            _compact_text(current.get('side')),
            _compact_text(current.get('signed_qty')),
            _compact_text(current.get('abs_qty')),
            _compact_text(current.get('unrealized_pnl')),
            _compact_text(current.get('notional_usd')),
        )
        if any(before_sig) and before_sig != current_sig:
            lines.append(
                f"- 本轮前持仓: side={_compact_text(current_before.get('side')) or '-'} signed_qty={_compact_text(current_before.get('signed_qty')) or '-'} abs_qty={_compact_text(current_before.get('abs_qty')) or '-'} 浮盈亏={_compact_text(current_before.get('unrealized_pnl')) or '-'}U 名义价值={_compact_text(current_before.get('notional_usd')) or '-'}U"
            )
        lines.append(
            f"- 当前持仓: side={_compact_text(current.get('side')) or '-'} signed_qty={_compact_text(current.get('signed_qty')) or '-'} abs_qty={_compact_text(current.get('abs_qty')) or '-'} 浮盈亏={_compact_text(current.get('unrealized_pnl')) or '-'}U 名义价值={_compact_text(current.get('notional_usd')) or '-'}U"
        )
        pos_note = _compact_text(item.get("position_note"))
        if pos_note:
            lines.append(f"- 仓位说明: {pos_note}")
        observed = item.get("account_position_observed", {}) if isinstance(item.get("account_position_observed"), dict) else {}
        if observed and pos_note:
            lines.append(
                f"- 共享账户观测仓位(仅提示): side={_compact_text(observed.get('side')) or '-'} signed_qty={_compact_text(observed.get('signed_qty')) or '-'} 名义价值={_compact_text(observed.get('notional_usd')) or '-'}U"
            )
        sizing = item.get("sizing", {}) if isinstance(item.get("sizing"), dict) else {}
        if sizing:
            lines.append(
                f"- 执行仓位: mode={_compact_text(sizing.get('mode')) or '-'} basis={_compact_text(sizing.get('basis_label')) or '-'} target_margin={_compact_text(sizing.get('target_margin_usdt')) or '-'}U target_notional={_compact_text(sizing.get('target_notional_usdt')) or '-'}U leverage={_compact_text(sizing.get('target_leverage')) or _compact_text(sizing.get('account_leverage')) or '-'}"
            )
            lev_reason = _compact_text(sizing.get('leverage_reason'))
            clamp_note = _compact_text(sizing.get('clamp_note'))
            if lev_reason or clamp_note:
                lines.append(f"- 执行说明: lev_reason={lev_reason or '-'} clamp={clamp_note or '-'}")
        pending = item.get("orders_pending", {}) if isinstance(item.get("orders_pending"), dict) else {}
        if pending:
            lines.append(f"- 待处理订单: {pending.get('pending_count', '-')}")
        actions = item.get("action_plan", []) if isinstance(item.get("action_plan"), list) else []
        if actions:
            lines.append("- 动作计划:")
            for action in actions:
                if isinstance(action, dict):
                    lines.append(f"  - {_action_line(action)}")
        blocked = item.get("risk_override_blocked_actions", []) if isinstance(item.get("risk_override_blocked_actions"), list) else []
        if blocked:
            lines.append(f"- 被风险层阻断的新开仓动作: {', '.join(str(x) for x in blocked)}")
        execs = item.get("executions", []) if isinstance(item.get("executions"), list) else []
        if execs:
            lines.append("- 执行结果:")
            for ex in execs:
                if isinstance(ex, dict):
                    lines.append(f"  - {_exec_line(ex, tz_name)}")
        else:
            lines.append("- 执行结果: 本轮无真实下单")
        sync = syncs.get(sym) if isinstance(syncs, dict) else None
        if isinstance(sync, dict):
            latest_local = _fmt_ts_local(sync.get("last_time_after"), tz_name)
            lines.append(
                f"- 数据同步: rows_added={sync.get('rows_added', '-')}, rows_total_after={sync.get('rows_total_after', '-')}, latest_kline({tz_name})={latest_local or '-'}"
            )
        protective = item.get("protective_preview", {}) if isinstance(item.get("protective_preview"), dict) else {}
        if protective:
            lines.append(
                f"- 保护单预览: stop={_compact_text(protective.get('stop')) or '-'} tp={_compact_text(protective.get('tp')) or '-'} trail={_compact_text(protective.get('trail')) or '-'}"
            )
        reason = _compact_text(item.get("reason"))
        if reason:
            lines.append(f"- 标的备注: {reason}")
        lines.append("")
    return lines[:-1] if lines and lines[-1] == "" else lines


def _coinglass_detail_lines(snapshot: dict[str, Any], tz_name: str, tz_label: str) -> list[str]:
    lines: list[str] = []
    if not isinstance(snapshot, dict) or not snapshot:
        lines.append("- 暂无 CoinGlass 快照")
        return lines
    mode = str(snapshot.get('mode') or '').strip().lower()
    enforcement = str(snapshot.get('enforcement') or '').strip().lower()
    effective_pause = snapshot.get('effective_pause_new_entries')
    if effective_pause is None:
        effective_pause = mode == 'pause_new_entries' and enforcement in {'enforce', 'pause_new_entries'}
    signal_pause = mode == 'pause_new_entries'
    lines.append(f"- 当前模式: {_compact_text(snapshot.get('mode')) or '-'}")
    lines.append(f"- 执行方式: {_compact_text(snapshot.get('enforcement')) or '-'}")
    lines.append(f"- 风险信号命中暂停条件: {_bool_zh(signal_pause)}")
    lines.append(f"- 当前实际是否拦截新开仓: {_bool_zh(bool(effective_pause))}")
    if signal_pause and not effective_pause and enforcement == 'shadow_only':
        lines.append("- 说明: 当前仅影子观察，不拦截真实新开仓")
    if _compact_text(snapshot.get('event_type')):
        lines.append(f"- 事件类型: {_compact_text(snapshot.get('event_type'))}")
    reason = _compact_text(snapshot.get('reason'))
    if reason:
        lines.append(f"- 触发原因: {reason}")
    until_local = _fmt_ts_local(snapshot.get('until_utc'), tz_name)
    if until_local:
        lines.append(f"- 生效至({tz_label}): {until_local}")
    news = (snapshot.get('news') or {}).get('items') if isinstance(snapshot.get('news'), dict) else []
    if isinstance(news, list) and news:
        lines.append("- 新闻观察:")
        for item in news[:5]:
            if not isinstance(item, dict):
                continue
            ts_local = _fmt_ts_local(item.get('ts_utc'), tz_name)
            lines.append(f"  - {ts_local or '-'} | {item.get('title', '')}")
    macro = (snapshot.get('economic') or {}).get('items') if isinstance(snapshot.get('economic'), dict) else []
    if isinstance(macro, list) and macro:
        lines.append("- 宏观观察:")
        for item in macro[:5]:
            if not isinstance(item, dict):
                continue
            ts_local = _fmt_ts_local(item.get('ts_utc'), tz_name)
            lines.append(f"  - {ts_local or '-'} | {item.get('title', '')}")
    note = _compact_text(snapshot.get('note'))
    if note:
        lines.append(f"- 备注: {note}")
    return lines




def _free_feeds_detail_lines(snapshot: dict[str, Any], tz_name: str, tz_label: str) -> list[str]:
    lines: list[str] = []
    if not isinstance(snapshot, dict) or not snapshot:
        lines.append("- 暂无免费结构化源快照")
        return lines
    lines.append("- 当前用途: 观察/候选，不直接触发交易")
    lines.append(f"- 快照状态: {_compact_text(snapshot.get('status')) or '-'}")

    bb = snapshot.get("blockbeats") if isinstance(snapshot.get("blockbeats"), dict) else {}
    if bb:
        lines.append(
            f"- BlockBeats: status={_compact_text(bb.get('status')) or '-'} use={_compact_text(bb.get('use')) or '-'} risk_hits={bb.get('risk_hits', '-')}"
        )
        preview = bb.get("preview") if isinstance(bb.get("preview"), list) else []
        if preview:
            top = preview[0] if isinstance(preview[0], dict) else {}
            title = _compact_text(top.get("title"))
            if title:
                lines.append(f"  - 最新重点(按相关性排序): {title[:120]}")
            signals = top.get("signals") if isinstance(top.get("signals"), list) else []
            if signals:
                lines.append(f"  - 重点依据: {'/'.join([_compact_text(x) for x in signals[:4] if _compact_text(x)])}")

    binance = snapshot.get("binance") if isinstance(snapshot.get("binance"), dict) else {}
    for sym in ["BTCUSDT", "BNBUSDT"]:
        item = binance.get(sym) if isinstance(binance.get(sym), dict) else {}
        if not item:
            continue
        lines.append(
            f"- Binance {sym}: status={_compact_text(item.get('status')) or '-'} crowding={_compact_text(item.get('crowding')) or '-'} funding={_compact_text(item.get('funding')) or '-'} taker_ls={_compact_text(item.get('taker_ls')) or '-'}"
        )

    deribit = snapshot.get("deribit") if isinstance(snapshot.get("deribit"), dict) else {}
    if deribit:
        lines.append(
            f"- Deribit BTC: status={_compact_text(deribit.get('status')) or '-'} dvol={_compact_text(deribit.get('btc_dvol_last')) or '-'} vol_regime={_compact_text(deribit.get('vol_regime')) or '-'}"
        )

    fng = snapshot.get("fng") if isinstance(snapshot.get("fng"), dict) else {}
    if fng:
        lines.append(
            f"- Fear&Greed: status={_compact_text(fng.get('status')) or '-'} value={_compact_text(fng.get('value')) or '-'} label={_compact_text(fng.get('label')) or '-'} regime={_compact_text(fng.get('regime')) or '-'}"
        )

    notes = snapshot.get("notes") if isinstance(snapshot.get("notes"), list) else []
    if notes:
        lines.append(f"- 备注: { _compact_text('; '.join([str(x) for x in notes[:4]])) }")
    return lines


def _global_message_action(snapshot: dict[str, Any]) -> str:
    if not isinstance(snapshot, dict) or not snapshot:
        return "PASS"
    mode = str(snapshot.get("mode") or "").strip().lower()
    enforcement = str(snapshot.get("enforcement") or "").strip().lower()
    effective_pause = snapshot.get("effective_pause_new_entries")
    if effective_pause is None:
        effective_pause = mode == "pause_new_entries" and enforcement in {"enforce", "pause_new_entries"}
    if mode == "pause_new_entries" and bool(effective_pause):
        return "WAIT"
    if mode == "pause_new_entries" and enforcement == "shadow_only":
        return "OBSERVE_ONLY"
    if mode == "force_flat":
        return "FORCE_FLAT"
    return "PASS"


def _message_role_line() -> str:
    return "- 消息/事件角色: 状态层 + 仓位覆盖层 + 确认层（不直接翻方向）"


def _message_override_line() -> str:
    return "- 消息是否允许直接改向: 否（当前只允许 BOOST / CUT / WAIT，不直接把空翻多或把多翻空）"


def _decision_explain_lines(report: dict[str, Any], cg_snapshot: dict[str, Any], free_snapshot: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    lines.append(_message_role_line())
    lines.append(_message_override_line())
    msg_action = _global_message_action(cg_snapshot)
    reason = _compact_text(cg_snapshot.get("reason")) if isinstance(cg_snapshot, dict) else ""
    enforcement = _compact_text(cg_snapshot.get("enforcement")) if isinstance(cg_snapshot, dict) else ""
    lines.append(f"- 当前消息层动作: {msg_action} | enforcement={enforcement or '-'} | trigger={reason or '-'}")

    ff_bits: list[str] = []
    if isinstance(free_snapshot, dict):
        binance = free_snapshot.get("binance") if isinstance(free_snapshot.get("binance"), dict) else {}
        for sym in ["BTCUSDT", "BNBUSDT"]:
            item = binance.get(sym) if isinstance(binance.get(sym), dict) else {}
            crowd = _compact_text(item.get("crowding"))
            if crowd:
                ff_bits.append(f"{sym}:{crowd}")
        fng = free_snapshot.get("fng") if isinstance(free_snapshot.get("fng"), dict) else {}
        regime = _compact_text(fng.get("regime"))
        if regime:
            ff_bits.append(f"FNG:{regime}")
    if ff_bits:
        lines.append(f"- 免费结构化源摘要: {' | '.join(ff_bits[:4])}")

    syms = report.get("symbols", {}) if isinstance(report.get("symbols"), dict) else {}
    if not syms:
        lines.append("- 标的方向解释: 暂无")
        return lines

    lines.append("- 标的方向解释:")
    for sym, item in syms.items():
        if not isinstance(item, dict):
            continue
        desired = item.get("desired_signal", {}) if isinstance(item.get("desired_signal"), dict) else {}
        sizing = item.get("sizing", {}) if isinstance(item.get("sizing"), dict) else {}
        blocked = item.get("risk_override_blocked_actions", []) if isinstance(item.get("risk_override_blocked_actions"), list) else []
        side = _compact_text(desired.get("side")) or "-"
        mode = _compact_text(desired.get("mode")) or "-"
        lev_reason = _compact_text(sizing.get("leverage_reason")) or "-"
        if blocked:
            final_reason = f"消息层拦截了新开仓动作={','.join([str(x) for x in blocked])}"
        elif msg_action in {"WAIT", "FORCE_FLAT"}:
            final_reason = f"消息层动作={msg_action}，方向不新开/被压制"
        elif msg_action == "OBSERVE_ONLY":
            final_reason = f"技术面继续给 {side}，消息层只观察不改向（lev_reason={lev_reason}）"
        else:
            final_reason = f"按技术面执行 {side}（lev_reason={lev_reason}）"
        lines.append(f"  - {str(sym).upper()}: tech_side={side} | tech_mode={mode} | message_action={msg_action} | final_reason={final_reason}")
    return lines


def _find_research_json(project_dir: Path, filename: str) -> Path | None:
    candidates = [project_dir]
    candidates.extend(list(project_dir.parents)[:6])
    found: list[tuple[float, int, int, Path]] = []
    seen: set[str] = set()
    for depth, base in enumerate(candidates):
        key = str(base)
        if key in seen:
            continue
        seen.add(key)
        for priority, rel in enumerate([Path("reports") / "research_raw" / filename, Path("reports") / filename]):
            cand = base / rel
            if cand.exists() and cand.is_file():
                try:
                    mtime = cand.stat().st_mtime
                except Exception:
                    mtime = 0.0
                # Prefer newer files first. If timestamps tie, prefer research_raw over reports,
                # and prefer the higher-level project root over nested workspace copies.
                found.append((mtime, -priority, -depth, cand))
    if not found:
        return None
    found.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    return found[0][3]


def _fmt_ratio_pct(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value) * 100:.{digits}f}%"
    except Exception:
        return "-"


def _fmt_num(value: Any, digits: int = 3) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except Exception:
        return "-"


def _fmt_int_text(value: Any) -> str:
    try:
        return str(int(float(value)))
    except Exception:
        return "-"


def _wf_match_score(version_text: str, strategy_name: str, row: dict[str, Any]) -> int:
    version_l = (version_text or "").lower()
    strategy_l = (strategy_name or "").lower()
    name = _compact_text(row.get("name")) or ""
    name_l = name.lower()
    score = 0
    if name_l and name_l in version_l:
        score = max(score, len(name_l) * 10)
    if name_l == "mainline_live_base" and "live_base" in version_l:
        score = max(score, len("live_base") * 10)
    symbol = (_compact_text(row.get("symbol")) or "").lower()
    family = (_compact_text(row.get("family")) or "").lower()
    if strategy_l == "branch_shortwave_demo":
        if symbol and symbol in version_l:
            score += len(symbol) * 3
        if family and family in version_l:
            score += len(family) * 3
        if name_l and any(tok in name_l for tok in ["eth_", "sol_", "btc_"]):
            score += 5
    return score


def _eval_metrics_from_row(best_row: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], str, str, str]:
    best_gate = {}
    if isinstance(best_row.get("best_gate"), dict):
        best_gate = best_row.get("best_gate") or {}
    elif isinstance(best_row.get("dominant_gate"), dict):
        best_gate = best_row.get("dominant_gate") or {}
    base_metrics = best_gate.get("metrics") if isinstance(best_gate.get("metrics"), dict) else {}
    recent_metrics = best_gate.get("recent_metrics") if isinstance(best_gate.get("recent_metrics"), dict) else {}
    wf = best_row.get("walkforward") if isinstance(best_row.get("walkforward"), dict) else {}
    wf_metrics = wf.get("metrics") if isinstance(wf.get("metrics"), dict) else {}
    gate_mix = wf.get("gate_mix") if isinstance(wf.get("gate_mix"), dict) else {}
    gate_mix_text = ", ".join([f"{_compact_text(k)}:{_compact_text(v)}" for k, v in gate_mix.items() if _compact_text(k)]) or "-"
    best_gate_name = _compact_text(best_gate.get("gate_name")) or "-"
    note = _compact_text(best_row.get("note")) or "-"
    return best_gate, base_metrics, recent_metrics, wf_metrics, gate_mix_text, best_gate_name, note


def _asset_summary_recent_metrics(row: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(row, dict):
        return {}
    dom = row.get("dominant_gate") or {}
    if isinstance(dom, dict):
        recent = dom.get("recent_metrics")
        if isinstance(recent, dict):
            return recent
    return {}


def _asset_summary_wf_metrics(row: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(row, dict):
        return {}
    wf = row.get("walkforward") or {}
    if isinstance(wf, dict):
        metrics = wf.get("metrics")
        if isinstance(metrics, dict):
            return metrics
    return {}


def _strategy_eval_lines_branch_asset_summary(project_dir_raw: Any, strategy_name: str) -> list[str]:
    project_dir = Path(str(project_dir_raw or ".")).expanduser()
    if not project_dir.exists():
        return []
    p = _find_research_json(project_dir, "stage91_branch_event_alpha_matrix_latest.json")
    if p is None:
        return []
    payload = _load_json(p) or {}
    items = payload.get("asset_summary") if isinstance(payload.get("asset_summary"), list) else []
    if not items:
        return []

    strategy_l = (strategy_name or "").lower()
    if "triple_book" in strategy_l:
        note = "三标的联动预览：BTC 多空同腿保留，ETH 多空并存，SOL 继续研究观察，不把单一候选误当整套分支。"
    elif "asset_integrated" in strategy_l:
        note = "资产腿联动预览：BTC 多空同腿保留，ETH 多空并存；运行层按资产模式而不是单一旧候选解读。"
    else:
        note = "分支资产模式按 stage91 资产汇总解读。"

    candidate_parts: list[str] = []
    mode_parts: list[str] = []
    lines: list[str] = []
    lines.append("【策略评估摘要】")
    lines.append("- 判断口径: 6年总样本仅作软约束；以近2年 + WF样本外为主")
    for item in items:
        if not isinstance(item, dict):
            continue
        sym = (_compact_text(item.get("symbol")) or "-").upper()
        mode = _compact_text(item.get("mode")) or "-"
        active = item.get("active") if isinstance(item.get("active"), dict) else {}
        active_name = _compact_text(active.get("name")) or "-"
        candidate_parts.append(f"{sym}:{active_name}")
        mode_parts.append(f"{sym}={mode}")
    lines.append(f"- 当前候选: {' ; '.join(candidate_parts) or '-'}")
    lines.append(f"- 评估结论: {' | '.join(mode_parts) or '-'} | source=stage91_asset_summary")
    lines.append(f"- 备注: {note}")

    for item in items:
        if not isinstance(item, dict):
            continue
        sym = (_compact_text(item.get("symbol")) or "-").upper()
        mode = _compact_text(item.get("mode")) or "-"
        active = item.get("active") if isinstance(item.get("active"), dict) else {}
        active_name = _compact_text(active.get("name")) or "-"
        recent = _asset_summary_recent_metrics(active)
        wf = _asset_summary_wf_metrics(active)
        lines.append(
            f"- {sym}: mode={mode} | active={active_name} | 近2年 收益={_fmt_ratio_pct(recent.get('ret'))} | 交易={_fmt_int_text(recent.get('trades'))} | PF={_fmt_num(recent.get('pf'))} | WF 收益={_fmt_ratio_pct(wf.get('ret'))} | 交易={_fmt_int_text(wf.get('trades'))} | PF={_fmt_num(wf.get('pf'))} | 回撤={_fmt_ratio_pct(wf.get('maxdd'))}"
        )
        legs: list[str] = []
        for key, label in (("long_best", "long"), ("short_best", "short"), ("dual_best", "dual")):
            row = item.get(key) if isinstance(item.get(key), dict) else {}
            name = _compact_text(row.get("name"))
            if name:
                legs.append(f"{label}={name}")
        if legs:
            lines.append(f"  - 候选腿: {' | '.join(legs)}")
        item_note = _compact_text(item.get("note"))
        if item_note:
            lines.append(f"  - 说明: {item_note}")
    return lines


def _strategy_eval_lines(project_dir_raw: Any, version_text: str, strategy_name: str) -> list[str]:
    project_dir = Path(str(project_dir_raw or ".")).expanduser()
    if not project_dir.exists():
        return []
    strategy_l = (strategy_name or "").lower()
    if "triple_book" in strategy_l or "asset_integrated" in strategy_l:
        asset_lines = _strategy_eval_lines_branch_asset_summary(project_dir_raw, strategy_name)
        if asset_lines:
            return asset_lines
    prefer_branch = strategy_l == "branch_shortwave_demo" or ".branch_shortwave_demo" in str(project_dir)
    files: list[tuple[str, str]] = []
    if prefer_branch:
        files.extend([
            ("branch", "stage89_branch_fusion_walkforward_latest.json"),
            ("branch", "stage91_branch_event_alpha_matrix_latest.json"),
            ("branch", "stage82_branch_walkforward_latest.json"),
            ("mainline", "stage88_mainline_fusion_walkforward_latest.json"),
            ("mainline", "stage90_mainline_event_alpha_matrix_latest.json"),
            ("mainline", "stage81_mainline_walkforward_latest.json"),
        ])
    else:
        files.extend([
            ("mainline", "stage88_mainline_fusion_walkforward_latest.json"),
            ("mainline", "stage90_mainline_event_alpha_matrix_latest.json"),
            ("mainline", "stage81_mainline_walkforward_latest.json"),
            ("branch", "stage89_branch_fusion_walkforward_latest.json"),
            ("branch", "stage91_branch_event_alpha_matrix_latest.json"),
            ("branch", "stage82_branch_walkforward_latest.json"),
        ])

    best_kind = ""
    best_row: dict[str, Any] | None = None
    best_score = -1
    for kind, filename in files:
        p = _find_research_json(project_dir, filename)
        if p is None:
            continue
        payload = _load_json(p) or {}
        rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            score = _wf_match_score(version_text, strategy_name, row)
            if score > best_score:
                best_score = score
                best_row = row
                best_kind = kind
    if best_row is None or best_score <= 0:
        return []

    best_gate, base_metrics, recent_metrics, wf_metrics, gate_mix_text, best_gate_name, note = _eval_metrics_from_row(best_row)
    wf = best_row.get("walkforward") if isinstance(best_row.get("walkforward"), dict) else {}
    label = _compact_text(wf.get("label")) or _compact_text(best_row.get("decision")) or ("hold" if best_kind == "mainline" else "-")
    candidate_name = _compact_text(best_row.get("name")) or "-"
    lines: list[str] = []
    lines.append("【策略评估摘要】")
    lines.append("- 判断口径: 6年总样本仅作软约束；以近2年 + WF样本外为主")
    lines.append(f"- 当前候选: {candidate_name}")
    lines.append(f"- 评估结论: {label} | best_gate={best_gate_name} | gate_mix={gate_mix_text}")
    lines.append(f"- 备注: {note}")
    if base_metrics:
        lines.append(
            f"- 6年总样本: 收益={_fmt_ratio_pct(base_metrics.get('ret'))} | 月化={_fmt_ratio_pct(base_metrics.get('monthlyized_ret'))} | 回撤={_fmt_ratio_pct(base_metrics.get('maxdd'))} | 交易={_fmt_int_text(base_metrics.get('trades'))} | PF={_fmt_num(base_metrics.get('pf'))}"
        )
    if recent_metrics:
        lines.append(
            f"- 近2年样本: 收益={_fmt_ratio_pct(recent_metrics.get('ret'))} | 月化={_fmt_ratio_pct(recent_metrics.get('monthlyized_ret'))} | 回撤={_fmt_ratio_pct(recent_metrics.get('maxdd'))} | 交易={_fmt_int_text(recent_metrics.get('trades'))} | PF={_fmt_num(recent_metrics.get('pf'))}"
        )
    if wf_metrics:
        wf_extra = f" | 胜率={_fmt_ratio_pct(wf_metrics.get('win_rate'))}" if wf_metrics.get('win_rate') is not None else ""
        pos = _fmt_int_text(wf.get('positive_folds'))
        tot = _fmt_int_text(wf.get('total_folds'))
        lines.append(
            f"- WF样本外: 收益={_fmt_ratio_pct(wf_metrics.get('ret'))} | 月化={_fmt_ratio_pct(wf_metrics.get('monthlyized_ret'))} | 回撤={_fmt_ratio_pct(wf_metrics.get('maxdd'))} | 交易={_fmt_int_text(wf_metrics.get('trades'))} | PF={_fmt_num(wf_metrics.get('pf'))}{wf_extra} | 正收益折={pos}/{tot}"
        )
    return lines


def _write_public_report(path: Path, body: dict[str, Any]) -> None:
    display_tz = str(body.get("display_tz") or "Asia/Shanghai")
    display_tz_label = str(body.get("display_tz_label") or "UTC+8")
    rep = body.get("execution_report") if isinstance(body.get("execution_report"), dict) else {}
    cg_snapshot = body.get("coinglass_snapshot") if isinstance(body.get("coinglass_snapshot"), dict) else {}
    if isinstance(cg_snapshot, dict) and cg_snapshot:
        cg_snapshot = dict(cg_snapshot)
        if not cg_snapshot.get("enforcement") and body.get("coinglass_enforcement"):
            cg_snapshot["enforcement"] = body.get("coinglass_enforcement")
        if "effective_pause_new_entries" not in cg_snapshot:
            cg_snapshot["effective_pause_new_entries"] = body.get("coinglass_would_pause_new_entries")
    free_snapshot = body.get("free_feeds_snapshot") if isinstance(body.get("free_feeds_snapshot"), dict) else {}
    lines: list[str] = []
    lines.append("OKX Demo 自动报告（此文件每轮自动覆盖）")
    lines.append(f"时区: {display_tz_label}")
    lines.append(f"生成时间({display_tz_label}): {_fmt_ts_local(body.get('ts_utc'), display_tz)}")
    lines.append(f"生成时间(UTC): {_fmt_ts_utc(body.get('ts_utc'))}")
    lines.append("")
    lines.append("【概览】")
    lines.append(f"- 报告心跳({display_tz_label}): {_fmt_ts_local(body.get('ts_utc'), display_tz)}")
    lines.append(f"- 当前状态: {_status_zh(str(body.get('status', '')))}")
    lines.append(f"- 状态原因: {_compact_text(body.get('status_reason')) or '-'}")
    lines.append(f"- 项目目录: {_compact_text(body.get('project_dir'))}")
    lines.append(f"- 进程 PID: {_compact_text(body.get('pid')) or '-'}")
    if _compact_text(body.get('runner_role')):
        lines.append(f"- 运行角色: {_compact_text(body.get('runner_role'))}")
    lines.append(f"- 当前版本: {_compact_text(body.get('version')) or '-'}")
    lines.append(f"- 订单前缀: {_compact_text(rep.get('order_id_prefix')) or '-'}")
    lines.append(f"- 下一轮执行({display_tz_label}): {_fmt_ts_local(body.get('next_due_utc'), display_tz) or '-'}")
    lines.append(f"- 最近已完成 15m K 线开盘({display_tz_label}): {_fmt_ts_local(body.get('last_completed_bar_utc'), display_tz) or '-'}")
    lines.append(f"- 最近策略信号时间({display_tz_label}): {_fmt_ts_local(body.get('signal_time'), display_tz) or '-'}")
    lines.append(f"- 最近影子执行成功: {_bool_zh(body.get('shadow_exec_ok'))}")
    lines.append(f"- 最近影子执行原因: {_compact_text(body.get('shadow_exec_reason')) or '-'}")
    pnl = rep.get("pnl_snapshot", {}) if isinstance(rep.get("pnl_snapshot"), dict) else {}
    if pnl:
        lines.append(f"- 策略收益统计口径: {_compact_text(pnl.get('strategy_scope')) or '-'}")
        lines.append(f"- 策略真实成交已开始: {_bool_zh(pnl.get('strategy_live_started'))}")
        lines.append(f"- 策略累计已实现收益: {_compact_text(pnl.get('strategy_realized_pnl')) or '-'} U")
        lines.append(f"- 策略当前未实现收益: {_compact_text(pnl.get('strategy_unrealized_pnl')) or '-'} U")
        lines.append(f"- 策略当前总收益: {_compact_text(pnl.get('strategy_total_pnl')) or '-'} U")
        lines.append(f"- 当前策略浮盈亏估计: {_compact_text(pnl.get('strategy_unrealized_pnl')) or '-'} U")
        strategy_live_started = bool(pnl.get('strategy_live_started'))
        if strategy_live_started:
            lines.append(f"- 共享账户累计收益（仅观察，非策略）: {_compact_text(pnl.get('shared_account_total_pnl_observed')) or '-'} U")
            lines.append(f"- 共享账户累计收益率（仅观察，非策略）: {_compact_text(pnl.get('shared_account_return_pct_observed')) or '-'}")
        else:
            lines.append("- 共享账户累计收益（仅观察，非策略）: 已隐藏（首笔策略真实成交前不展示）")
            lines.append("- 共享账户累计收益率（仅观察，非策略）: 已隐藏（首笔策略真实成交前不展示）")
        if _compact_text(pnl.get('strategy_note')):
            lines.append(f"- 策略收益备注: {_compact_text(pnl.get('strategy_note'))}")
    eval_lines = _strategy_eval_lines(body.get('project_dir'), _compact_text(body.get('version')) or '', _compact_text(body.get('strategy_name')) or '')
    if eval_lines:
        lines.append("")
        lines.extend(eval_lines)
    sizing = rep.get("execution_sizing", {}) if isinstance(rep.get("execution_sizing"), dict) else {}
    if sizing:
        balance = sizing.get("balance", {}) if isinstance(sizing.get("balance"), dict) else {}
        equity_util = _compact_text(sizing.get('equity_utilization')) or '-'
        reserve_usdt = _compact_text(sizing.get('reserve_usdt')) or '-'
        basis_label = _compact_text(sizing.get('basis_label')) or '-'
        basis_equity = _compact_text(sizing.get('basis_equity_usdt')) or '-'
        basis_avail = _compact_text(balance.get('avail_eq_usdt')) or basis_equity
        usdt_avail = _compact_text(balance.get('usdt_avail')) or basis_avail
        lines.append(f"- 执行金额模型: {_compact_text(sizing.get('mode')) or '-'}")
        lines.append(f"- 账户真实可用金额参考: OKX availEq={basis_avail} USDT | USDT.avail={usdt_avail} USDT")
        lines.append(f"- 策略计仓基准: {basis_label}={basis_equity} USDT")
        lines.append(f"- 策略计仓权益（内部风控口径，非OKX可用金额）: {_compact_text(sizing.get('usable_equity_usdt')) or '-'} USDT")
        lines.append(f"- 计仓说明: equity_utilization={equity_util} | reserve={reserve_usdt} USDT | formula={basis_label}*{equity_util}-reserve")
        lines.append(f"- 分仓切片: slices={_compact_text(sizing.get('capital_slices')) or '-'} | 单片保证金={_compact_text(sizing.get('base_margin_per_slice_usdt')) or '-'}U | leverage_default={_compact_text(sizing.get('account_leverage')) or '-'}")
        lines.append(f"- 杠杆档位: mode={_compact_text(sizing.get('leverage_mode')) or '-'} min={_compact_text(sizing.get('min_leverage')) or '-'} max={_compact_text(sizing.get('max_leverage')) or '-'}")
        lines.append(f"- 保证金上限: total={_compact_text(sizing.get('total_margin_cap_usdt')) or '-'}U | per_symbol={_compact_text(sizing.get('per_symbol_margin_cap_usdt')) or '-'}U | total_target={_compact_text(sizing.get('total_target_margin_usdt')) or '-'}U")
    lines.append("")
    lines.append("【CoinGlass 风险层】")
    lines.extend(_coinglass_detail_lines(cg_snapshot, display_tz, display_tz_label))
    lines.append("")
    lines.append("【免费结构化源】")
    lines.extend(_free_feeds_detail_lines(free_snapshot, display_tz, display_tz_label))
    lines.append("")
    lines.append("【方向解释】")
    lines.extend(_decision_explain_lines(rep, cg_snapshot, free_snapshot))
    lines.append("")
    lines.append("【标的明细】")
    lines.extend(_symbol_detail_lines(rep, display_tz))
    lines.append("")
    stderr_tail = _compact_text(body.get("shadow_exec_stderr_tail"))
    stdout_tail = _compact_text(body.get("shadow_exec_stdout_tail"))
    if stderr_tail or (stdout_tail and not body.get("shadow_exec_ok")):
        lines.append("")
        lines.append("【最近错误/日志尾部】")
        if stderr_tail:
            lines.append(stderr_tail)
        elif stdout_tail:
            lines.append(stdout_tail)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _summarize_symbols(report: dict[str, Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    syms = report.get("symbols", {}) if isinstance(report.get("symbols"), dict) else {}
    for sym, item in syms.items():
        if not isinstance(item, dict):
            continue
        desired = item.get("desired_signal", {}) if isinstance(item.get("desired_signal"), dict) else {}
        current = item.get("current_position", {}) if isinstance(item.get("current_position"), dict) else {}
        action_plan = item.get("action_plan", []) if isinstance(item.get("action_plan"), list) else []
        execs = item.get("executions", []) if isinstance(item.get("executions"), list) else []
        actions = ",".join([str(a.get("kind", "")) for a in action_plan if isinstance(a, dict) and a.get("kind")]) or "none"
        ords = ",".join([str(e.get("ord_id", "")) for e in execs if isinstance(e, dict) and e.get("ord_id")]) or "none"
        out.append({
            "symbol": str(sym).upper(),
            "desired": str(desired.get("side", "")),
            "current": str(current.get("side", "")),
            "actions": actions,
            "ord_ids": ords,
        })
    return out


def _print_cycle_banner(cycle_no: int, bar_open_ms: int, next_due: pd.Timestamp, cg: dict[str, Any], enforcement: str, display_tz: str, display_tz_label: str) -> None:
    bar_ts = pd.Timestamp(bar_open_ms, unit="ms", tz="UTC")
    _log(
        display_tz,
        display_tz_label,
        f"[RUN] cycle={cycle_no} completed_bar={_fmt_ts_local(bar_ts, display_tz)} risk={cg.get('mode')} enforcement={enforcement} next_due={_fmt_ts_local(next_due, display_tz)}",
    )
    reason = str(cg.get("reason", "") or "")
    if reason:
        tag = "[RISK-SHADOW]" if enforcement == "shadow_only" else "[RISK]"
        _log(display_tz, display_tz_label, f"{tag} {reason}")


def _print_trade_events(report: dict[str, Any], display_tz: str, display_tz_label: str) -> None:
    syms = report.get("symbols", {}) if isinstance(report.get("symbols"), dict) else {}
    for sym, item in syms.items():
        if not isinstance(item, dict):
            continue
        desired = item.get("desired_signal", {}) if isinstance(item.get("desired_signal"), dict) else {}
        current = item.get("current_position", {}) if isinstance(item.get("current_position"), dict) else {}
        action_plan = item.get("action_plan", []) if isinstance(item.get("action_plan"), list) else []
        execs = item.get("executions", []) if isinstance(item.get("executions"), list) else []
        real_actions = [a for a in action_plan if isinstance(a, dict) and str(a.get("kind", "")).lower() not in {"hold", "noop_flat", "noop_risk_pause"}]
        if real_actions:
            for idx, action in enumerate(real_actions):
                ex = execs[idx] if idx < len(execs) and isinstance(execs[idx], dict) else {}
                kind = str(action.get("kind", "")).lower()
                payload = ex.get("payload", {}) if isinstance(ex.get("payload"), dict) else {}
                row = (ex.get("order") or {}).get("row") if isinstance(ex.get("order"), dict) else {}
                event_time = _fmt_ts_local((row or {}).get("uTime") or (row or {}).get("fillTime") or (row or {}).get("cTime"), display_tz) if isinstance(row, dict) else ""
                side = str(payload.get("side", action.get("side", "")))
                qty = str(payload.get("sz", action.get("qty", "")))
                ord_id = str(ex.get("ord_id", ""))
                filled = ex.get("filled")
                avg_px = _compact_text((row or {}).get("avgPx") or (row or {}).get("fillPx")) if isinstance(row, dict) else ""
                zh_kind = "开/加仓" if kind in {"open", "add", "flip_open"} else "平/减仓"
                extra = f" avgPx={avg_px}" if avg_px else ""
                extra += f" time={event_time}" if event_time else ""
                _log(display_tz, display_tz_label, f"[交易] {sym.upper()} {zh_kind} side={side} qty={qty} ordId={ord_id or '-'} filled={filled}{extra}")
        else:
            actions = ",".join([str(a.get("kind", "")) for a in action_plan if isinstance(a, dict) and a.get("kind")]) or "none"
            _log(
                display_tz,
                display_tz_label,
                f"[状态] {sym.upper()} desired={desired.get('side')} current={current.get('side')} actions={actions}",
            )


def _run_shadow_exec(
    root: Path,
    runtime_dir: Path,
    coinglass_mode: str,
    coinglass_reason: str,
    coinglass_until_utc: str | None,
    coinglass_enforcement: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    env = os.environ.copy()
    env["OKX_AUTOPILOT_MODE"] = "1"
    env["OKX_AUTOPILOT_RUNTIME_DIR"] = str(runtime_dir)
    env["OKX_COINGLASS_MODE"] = str(coinglass_mode or "normal")
    env["OKX_COINGLASS_REASON"] = str(coinglass_reason or "")
    env["OKX_COINGLASS_ENFORCEMENT"] = str(coinglass_enforcement or "shadow_only")
    if coinglass_until_utc:
        env["OKX_COINGLASS_UNTIL_UTC"] = str(coinglass_until_utc)
    else:
        env.pop("OKX_COINGLASS_UNTIL_UTC", None)

    enforce = str(coinglass_enforcement or "shadow_only").strip().lower() in {"enforce", "pause_new_entries"}
    if enforce and str(coinglass_mode or "normal").strip().lower() != "normal":
        env["OKX_RISK_OVERRIDE_MODE"] = str(coinglass_mode)
        env["OKX_RISK_OVERRIDE_NOTE"] = str(coinglass_reason or "")
        if coinglass_until_utc:
            env["OKX_RISK_OVERRIDE_UNTIL_UTC"] = str(coinglass_until_utc)
        else:
            env.pop("OKX_RISK_OVERRIDE_UNTIL_UTC", None)
    else:
        env["OKX_RISK_OVERRIDE_MODE"] = "normal"
        env["OKX_RISK_OVERRIDE_NOTE"] = str(coinglass_reason or "")
        env.pop("OKX_RISK_OVERRIDE_UNTIL_UTC", None)

    cmd = [sys.executable, "-u", "-m", "tools.okx_demo_shadow_exec", "--project-dir", str(root), "--confirm-demo"]
    rep_path = runtime_dir / "okx_demo_shadow_exec_latest.json"
    try:
        proc = subprocess.run(cmd, cwd=str(root), env=env, capture_output=True, text=True, timeout=max(30, int(timeout_seconds)))
        rep = _load_json(rep_path)
        return {
            "returncode": proc.returncode,
            "stdout": proc.stdout[-4000:],
            "stderr": proc.stderr[-4000:],
            "report": rep,
            "report_path": str(rep_path),
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as e:
        rep = _load_json(rep_path)
        return {
            "returncode": -9,
            "stdout": str(getattr(e, "stdout", "") or "")[-4000:],
            "stderr": (str(getattr(e, "stderr", "") or "") + f"\nshadow_exec_timeout={int(timeout_seconds)}s")[-4000:],
            "report": rep,
            "report_path": str(rep_path),
            "timed_out": True,
        }


def main() -> None:
    ap = argparse.ArgumentParser(description="Simple OKX demo autopilot: one start command, one pause command, one report in Downloads")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--confirm-demo", action="store_true")
    ap.add_argument("--once", action="store_true", help="调试用：只执行一轮或写入等待状态")
    ap.add_argument("--role-tag", default="", help="运行角色标签，仅用于进程识别与报告诊断")
    args = ap.parse_args()

    root = Path(args.project_dir).resolve()
    cfg = _load_autopilot_cfg(root)
    shadow_cfg = _load_shadow_cfg(root)
    auth_cfg = shadow_cfg.get("auth", {}) if isinstance(shadow_cfg, dict) else {}
    creds, creds_meta = load_credentials(auth_cfg if isinstance(auth_cfg, dict) else {}, root=root)

    bar = str(cfg.get("bar", shadow_cfg.get("runner", {}).get("bar", shadow_cfg.get("execution_step", {}).get("bar", "15m")) if isinstance(shadow_cfg, dict) else "15m"))
    grace_seconds = int(cfg.get("grace_seconds", 20))
    loop_sleep_seconds = float(cfg.get("loop_sleep_seconds", 2.0))
    shadow_exec_timeout_seconds = int(cfg.get("shadow_exec_timeout_seconds", 120))
    cg_cfg = cfg.get("coinglass", {}) if isinstance(cfg.get("coinglass"), dict) else {}
    coinglass_enforcement = str(cg_cfg.get("enforcement", "shadow_only")).strip().lower() or "shadow_only"
    if coinglass_enforcement not in {"shadow_only", "enforce", "pause_new_entries"}:
        coinglass_enforcement = "shadow_only"
    runtime_dir = _expand_path(root, cfg.get("runtime_dir", ".runtime"))
    pid_file = _expand_path(root, cfg.get("pid_file", ".runtime/okx_demo_autopilot.pid"))
    state_file = _expand_path(root, cfg.get("state_json", ".runtime/okx_demo_autopilot_state.json"))
    report_file = _expand_path(root, cfg.get("public_report_txt", "~/Downloads/okx_demo_report_latest.txt"))
    display_tz = str(cfg.get("display_timezone", "Asia/Shanghai") or "Asia/Shanghai")
    display_tz_label = str(cfg.get("display_tz_label", "UTC+8") or "UTC+8")
    try:
        cfg_all = yaml.safe_load((root / "config.yml").read_text(encoding="utf-8")) or {}
    except Exception:
        cfg_all = {}
    default_version = str(((cfg_all.get("system") or {}) if isinstance(cfg_all, dict) else {}).get("version", ""))
    runtime_report_path = runtime_dir / "okx_demo_shadow_exec_latest.json"

    if not args.confirm_demo:
        body = {
            "status": "stopped",
            "status_reason": "missing --confirm-demo",
            "ts_utc": now_utc_text(),
            "project_dir": str(root),
            "pid": "",
            "version": default_version,
            "strategy_name": str(((cfg_all.get("system") or {}) if isinstance(cfg_all, dict) else {}).get("strategy", "")),
            "display_tz": display_tz,
            "display_tz_label": display_tz_label,
            "next_due_utc": "",
            "last_completed_bar_utc": "",
            "coinglass_mode": "",
            "coinglass_reason": "",
            "coinglass_enforcement": coinglass_enforcement,
            "coinglass_would_pause_new_entries": False,
            "coinglass_snapshot": {},
            "free_feeds_snapshot": {},
            "shadow_exec_ok": False,
            "shadow_exec_reason": "missing --confirm-demo",
            "shadow_exec_stdout_tail": "",
            "shadow_exec_stderr_tail": "",
            "signal_time": "",
            "symbols": [],
            "execution_report": {},
        }
        _write_public_report(report_file, body)
        print(json.dumps({"ok": False, "reason": "missing --confirm-demo", "report": str(report_file)}, ensure_ascii=False))
        return

    # stale pid cleanup
    if pid_file.exists():
        try:
            old_pid = int(pid_file.read_text(encoding="utf-8").strip())
        except Exception:
            old_pid = 0
        if _pid_alive(old_pid):
            print(json.dumps({"ok": False, "reason": "already_running", "pid": old_pid, "report": str(report_file)}, ensure_ascii=False))
            return
        with contextlib.suppress(Exception):
            pid_file.unlink()

    pid_file.write_text(str(os.getpid()), encoding="utf-8")

    state = _load_json(state_file) or {}
    last_processed_bar_open_ms = int(state.get("last_processed_bar_open_ms", -1))
    cycle_no = int(state.get("cycle_no", 0))
    last_report = _load_json(runtime_report_path) or {}
    last_cg = state.get("last_coinglass") if isinstance(state.get("last_coinglass"), dict) else {"mode": "normal", "reason": ""}
    last_run_meta = state.get("last_run_meta") if isinstance(state.get("last_run_meta"), dict) else {}
    last_free = state.get("last_free_feeds") if isinstance(state.get("last_free_feeds"), dict) else {}

    def _current_status_body(
        status: str,
        status_reason: str,
        next_due: pd.Timestamp | None,
        cg: dict[str, Any] | None = None,
        free_snapshot: dict[str, Any] | None = None,
        rep: dict[str, Any] | None = None,
        last_bar_open_ms: int | None = None,
        run_meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        rep = rep if isinstance(rep, dict) else {}
        cg = cg if isinstance(cg, dict) else {}
        free_snapshot = free_snapshot if isinstance(free_snapshot, dict) else {}
        run_meta = run_meta if isinstance(run_meta, dict) else {}
        symbols = _summarize_symbols(rep or {})
        effective_pause = str(cg.get("mode", "normal")) == "pause_new_entries" and coinglass_enforcement in {"enforce", "pause_new_entries"}
        if isinstance(cg, dict) and cg:
            cg = dict(cg)
            cg.setdefault("enforcement", coinglass_enforcement)
            cg["effective_pause_new_entries"] = effective_pause
        return {
            "status": status,
            "status_reason": status_reason,
            "ts_utc": now_utc_text(),
            "project_dir": str(root),
            "pid": os.getpid(),
            "runner_role": str(getattr(args, "role_tag", "") or ""),
            "version": str(rep.get("plan_version", "") if isinstance(rep, dict) and rep.get("plan_version") else default_version),
            "strategy_name": str(((cfg_all.get("system") or {}) if isinstance(cfg_all, dict) else {}).get("strategy", "")),
            "display_tz": display_tz,
            "display_tz_label": display_tz_label,
            "next_due_utc": _ts_text(next_due),
            "last_completed_bar_utc": _ts_text(pd.Timestamp(last_bar_open_ms, unit="ms", tz="UTC") if last_bar_open_ms is not None and last_bar_open_ms >= 0 else None),
            "coinglass_mode": str(cg.get("mode", "")),
            "coinglass_reason": str(cg.get("reason", "")),
            "coinglass_enforcement": coinglass_enforcement,
            "coinglass_would_pause_new_entries": effective_pause,
            "coinglass_until_utc": str(cg.get("until_utc", "") or ""),
            "coinglass_snapshot": cg,
            "free_feeds_snapshot": free_snapshot,
            "shadow_exec_ok": bool(rep.get("ok")) if isinstance(rep, dict) else "",
            "shadow_exec_reason": str(rep.get("reason", "")) if isinstance(rep, dict) else "",
            "shadow_exec_stdout_tail": str(run_meta.get("stdout", "") or ""),
            "shadow_exec_stderr_tail": str(run_meta.get("stderr", "") or ""),
            "signal_time": str(rep.get("signal_time", "")) if isinstance(rep, dict) else "",
            "symbols": symbols,
            "execution_report": rep,
        }

    try:
        _log(display_tz, display_tz_label, f"[START] OKX Demo 自动运行已启动。报告：{report_file}")
        _log(display_tz, display_tz_label, f"[START] CoinGlass enforcement={coinglass_enforcement}")
        if not creds:
            _log(display_tz, display_tz_label, "[WARN] 未检测到 OKX Demo 凭证；shadow_exec 会失败，请检查 ~/.okx_demo_env")
        while not _STOP:
            current_complete_open_ms = _completed_bar_open_ms(bar)
            due_ts = _due_ts_for_completed_open_ms(current_complete_open_ms, bar, grace_seconds)
            if args.once and last_processed_bar_open_ms >= current_complete_open_ms:
                body = _current_status_body("waiting", "already_processed_current_bar", due_ts, cg=last_cg, free_snapshot=last_free, rep=last_report, last_bar_open_ms=last_processed_bar_open_ms, run_meta=last_run_meta)
                _write_public_report(report_file, body)
                break
            if current_complete_open_ms <= last_processed_bar_open_ms:
                next_due = _due_ts_for_completed_open_ms(current_complete_open_ms + (_bar_to_seconds(bar) * 1000), bar, grace_seconds)
                body = _current_status_body("waiting", "waiting_next_bar", next_due, cg=last_cg, free_snapshot=last_free, rep=last_report, last_bar_open_ms=last_processed_bar_open_ms, run_meta=last_run_meta)
                _write_public_report(report_file, body)
                sleep_seconds = min(loop_sleep_seconds, max(0.25, (next_due - _utc_now()).total_seconds()))
                time.sleep(max(0.25, sleep_seconds))
                continue
            now = _utc_now()
            if now < due_ts:
                body = _current_status_body("waiting", "waiting_bar_close", due_ts, cg=last_cg, free_snapshot=last_free, rep=last_report, last_bar_open_ms=last_processed_bar_open_ms, run_meta=last_run_meta)
                _write_public_report(report_file, body)
                sleep_seconds = min(loop_sleep_seconds, max(0.25, (due_ts - now).total_seconds()))
                time.sleep(max(0.25, sleep_seconds))
                continue

            cycle_no += 1
            cg = _coinglass_snapshot(root, requests.Session(), cfg)
            last_free = _free_feeds_snapshot(root)
            next_due = _due_ts_for_completed_open_ms(current_complete_open_ms + (_bar_to_seconds(bar) * 1000), bar, grace_seconds)
            _print_cycle_banner(cycle_no, current_complete_open_ms, next_due, cg, coinglass_enforcement, display_tz, display_tz_label)
            pre_body = _current_status_body("running", "shadow_exec_in_progress", next_due, cg=cg, free_snapshot=last_free, rep=last_report, last_bar_open_ms=current_complete_open_ms, run_meta=last_run_meta)
            _write_public_report(report_file, pre_body)
            run = _run_shadow_exec(
                root,
                runtime_dir,
                coinglass_mode=str(cg.get("mode", "normal")),
                coinglass_reason=str(cg.get("reason", "")),
                coinglass_until_utc=str(cg.get("until_utc", "") or "") or None,
                coinglass_enforcement=coinglass_enforcement,
                timeout_seconds=shadow_exec_timeout_seconds,
            )
            rep = run.get("report") if isinstance(run.get("report"), dict) else {}
            if not rep and run.get("timed_out"):
                rep = {"ok": False, "reason": f"shadow_exec_timeout_{int(shadow_exec_timeout_seconds)}s", "symbols": {}}
            prev_report = last_report if isinstance(last_report, dict) else {}
            if isinstance(rep, dict) and isinstance(prev_report, dict) and prev_report:
                prev_symbols = prev_report.get("symbols") if isinstance(prev_report.get("symbols"), dict) else {}
                prev_sync = prev_report.get("data_sync") if isinstance(prev_report.get("data_sync"), dict) else {}
                if (not isinstance(rep.get("symbols"), dict) or not rep.get("symbols")) and prev_symbols:
                    rep["symbols"] = prev_symbols
                    rep["report_cache_used"] = True
                if (not isinstance(rep.get("data_sync"), dict) or not rep.get("data_sync")) and prev_sync:
                    rep["data_sync"] = prev_sync
                    rep["report_cache_used"] = True
                if not rep.get("plan_version") and prev_report.get("plan_version"):
                    rep["plan_version"] = prev_report.get("plan_version")
                if not rep.get("signal_time") and prev_report.get("signal_time"):
                    rep["signal_time"] = prev_report.get("signal_time")
                if not rep.get("execution_sizing") and prev_report.get("execution_sizing"):
                    rep["execution_sizing"] = prev_report.get("execution_sizing")
            last_report = rep if isinstance(rep, dict) else {}
            last_cg = cg if isinstance(cg, dict) else {}
            last_run_meta = {"stdout": str(run.get("stdout", "") or ""), "stderr": str(run.get("stderr", "") or "")}
            _print_trade_events(last_report, display_tz, display_tz_label)
            status_reason = str((last_report or {}).get("reason", "") or "ok")
            if run.get("timed_out"):
                status_reason = f"shadow_exec_timeout_{int(shadow_exec_timeout_seconds)}s"
            body = _current_status_body("running", status_reason, next_due, cg=last_cg, free_snapshot=last_free, rep=last_report, last_bar_open_ms=current_complete_open_ms, run_meta=last_run_meta)
            _write_public_report(report_file, body)
            state = {
                "cycle_no": cycle_no,
                "last_processed_bar_open_ms": current_complete_open_ms,
                "last_processed_bar_utc": _ts_text(pd.Timestamp(current_complete_open_ms, unit="ms", tz="UTC")),
                "last_shadow_exec_ok": bool(last_report.get("ok")) if isinstance(last_report, dict) else False,
                "last_shadow_exec_reason": str(last_report.get("reason", "")) if isinstance(last_report, dict) else "missing_report",
                "last_coinglass": last_cg,
                "last_free_feeds": last_free,
                "last_run_meta": last_run_meta,
                "report_file": str(report_file),
                "runtime_dir": str(runtime_dir),
            }
            _write_json(state_file, state)
            last_processed_bar_open_ms = current_complete_open_ms
            if args.once:
                break
            time.sleep(max(0.5, min(loop_sleep_seconds, 2.0)))
    finally:
        final_body = _current_status_body("paused", "paused", None, cg=last_cg, free_snapshot=last_free, rep=last_report, last_bar_open_ms=last_processed_bar_open_ms, run_meta=last_run_meta)
        _write_public_report(report_file, final_body)
        try:
            if pid_file.exists():
                pid_file.unlink()
        except Exception:
            pass
        _log(display_tz, display_tz_label, f"[STOP] OKX Demo 自动运行已停止。报告：{report_file}")


if __name__ == "__main__":
    main()
