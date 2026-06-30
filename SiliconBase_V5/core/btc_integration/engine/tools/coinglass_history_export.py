from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import yaml

if __package__ in (None, ""):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.okx_demo_common import ensure_env_loaded


def _utc_now() -> pd.Timestamp:
    return pd.Timestamp.utcnow().tz_localize("UTC") if pd.Timestamp.utcnow().tzinfo is None else pd.Timestamp.utcnow().tz_convert("UTC")


def _fmt_ts(ts: pd.Timestamp | None) -> str:
    if ts is None:
        return "-"
    try:
        return ts.tz_convert("UTC").strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts)


def _candidate_env_files(root: Path) -> list[Path]:
    cands: list[Path] = []
    for p in [
        root / ".okx_demo_env",
        root / ".env",
        Path.home() / ".okx_demo_env",
        Path.home() / ".env",
    ]:
        if p not in cands:
            cands.append(p)
    return cands


def _load_shadow_cfg(root: Path) -> dict[str, Any]:
    p = root / "shadow.yml"
    if not p.exists():
        return {}
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return data.get("shadow", data) if isinstance(data, dict) else {}


def _coinglass_cfg(root: Path) -> dict[str, Any]:
    shadow = _load_shadow_cfg(root)
    cg = shadow.get("autopilot", {}).get("coinglass") if isinstance(shadow, dict) else None
    return cg if isinstance(cg, dict) else {}


def _coinglass_get(session: requests.Session, base_url: str, path: str, api_key: str, *, params: dict[str, Any] | None = None, timeout: int = 25) -> dict[str, Any]:
    url = base_url.rstrip("/") + path
    headers = {"accept": "application/json", "CG-API-KEY": api_key}
    out: dict[str, Any] = {"ok": False, "url": url, "path": path, "params": params or {}}
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


def _flatten_text(obj: Any) -> str:
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, (int, float, bool)):
        return str(obj)
    if isinstance(obj, dict):
        parts: list[str] = []
        for k, v in obj.items():
            if k in {"image", "img", "cover", "coverUrl", "icon", "thumb"}:
                continue
            parts.append(_flatten_text(v))
        return " | ".join([p for p in parts if p])
    if isinstance(obj, (list, tuple, set)):
        return " | ".join([_flatten_text(x) for x in obj if x is not None])
    return str(obj)


def _extract_title(obj: Any) -> str:
    if not isinstance(obj, dict):
        return str(obj)
    for key in ["title", "headline", "name", "event", "eventName", "articleTitle"]:
        val = obj.get(key)
        if val:
            return str(val)
    flat = _flatten_text(obj)
    flat = flat.replace("\n", " ").replace("\r", " ").strip()
    return flat[:180]


def _sample_lines(items: list[Any], limit: int = 3) -> list[str]:
    out: list[str] = []
    for raw in items[:limit]:
        ts = _extract_time(raw)
        title = _extract_title(raw)
        if title.startswith("http://") or title.startswith("https://"):
            title = "(url omitted)"
        out.append(f"  - {_fmt_ts(ts)} | {title[:120]}")
    return out


def _summarize_payload(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    rows = _extract_items(payload.get("data")) if isinstance(payload, dict) else []
    ts_values = [t for t in (_extract_time(x) for x in rows) if t is not None]
    earliest = min(ts_values) if ts_values else None
    latest = max(ts_values) if ts_values else None
    return {
        "name": name,
        "ok": bool(payload.get("ok")),
        "status_code": payload.get("status_code"),
        "path": payload.get("path"),
        "params": payload.get("params") or {},
        "row_count": len(rows),
        "earliest_utc": _fmt_ts(earliest),
        "latest_utc": _fmt_ts(latest),
        "error": payload.get("error", ""),
        "samples": _sample_lines(rows),
    }


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _endpoint_specs(root: Path) -> list[dict[str, Any]]:
    cg_cfg = _coinglass_cfg(root)
    news_path = str(cg_cfg.get("news_path", "/api/article/list"))
    economic_path = str(cg_cfg.get("economic_path", "/api/calendar/economic-data"))
    return [
        {"name": "news_recent", "path": news_path, "params": {}},
        {"name": "economic_recent", "path": economic_path, "params": {}},
        {"name": "oi_agg_btc_1d", "path": "/api/futures/open-interest/aggregated-history", "params": {"symbol": "BTC", "interval": "1d", "limit": 2500}},
        {"name": "lsr_btcusdt_binance_4h", "path": "/api/futures/global-long-short-account-ratio/history", "params": {"exchange": "Binance", "symbol": "BTCUSDT", "interval": "4h", "limit": 2500}},
        {"name": "taker_btcusdt_binance_4h", "path": "/api/futures/v2/taker-buy-sell-volume/history", "params": {"exchange": "Binance", "symbol": "BTCUSDT", "interval": "4h", "limit": 2500}},
        {"name": "liq_agg_btc_4h", "path": "/api/futures/liquidation/aggregated-history", "params": {"symbol": "BTC", "interval": "4h", "limit": 2500}},
    ]


def run(project_dir: Path, out: Path) -> None:
    env_info = ensure_env_loaded(root=project_dir)
    key = os.environ.get("COINGLASS_API_KEY", "").strip()
    cg_cfg = _coinglass_cfg(project_dir)
    base_url = str(cg_cfg.get("base_url", "https://open-api-v4.coinglass.com"))
    raw_dir = project_dir / "data" / "external" / "coinglass"
    raw_dir.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    lines.append("CoinGlass 历史数据导出/覆盖审计")
    lines.append(f"生成时间(UTC): {_fmt_ts(_utc_now())}")
    lines.append("")
    lines.append("【连通性】")
    lines.append(f"- base_url: {base_url}")
    lines.append(f"- api_key_present: {'yes' if bool(key) else 'no'}")
    loaded = env_info.get("env_files_loaded") if isinstance(env_info, dict) else []
    lines.append(f"- env_loaded: {', '.join(loaded) if loaded else '-'}")
    lines.append("")
    if not key:
        lines.append("【结论】")
        lines.append("- 未找到 COINGLASS_API_KEY；本次未执行导出。")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return

    session = requests.Session()
    summaries: list[dict[str, Any]] = []
    ok_hist = 0
    ok_recent = 0
    for spec in _endpoint_specs(project_dir):
        res = _coinglass_get(session, base_url, str(spec["path"]), key, params=dict(spec.get("params") or {}))
        _write_json(raw_dir / f"{spec['name']}.json", {"spec": spec, "response": res})
        sm = _summarize_payload(str(spec["name"]), res)
        summaries.append(sm)
        is_recent = spec["name"].endswith("recent")
        if sm["ok"]:
            if is_recent:
                ok_recent += 1
            else:
                ok_hist += 1

    lines.append("【端点审计】")
    for sm in summaries:
        lines.append(f"- {sm['name']}: {'ok' if sm['ok'] else 'failed'} | http={sm['status_code'] or '-'} | rows={sm['row_count']} | {sm['earliest_utc']} -> {sm['latest_utc']}")
        lines.append(f"  path={sm['path']} params={json.dumps(sm['params'], ensure_ascii=False, separators=(',', ':'))}")
        if sm["error"]:
            lines.append(f"  error={sm['error']}")
        for s in sm["samples"]:
            lines.append(s)
    lines.append("")
    lines.append("【结论】")
    if ok_recent == 2 and ok_hist >= 3:
        lines.append("- 你电脑端的 CoinGlass 已具备做“历史特征增强回测”的基础条件。")
        lines.append("- 下一步应把这些历史序列并入严格交叉验证，而不是继续只看手工事件窗。")
    elif ok_recent == 2 and ok_hist > 0:
        lines.append("- Recent 新闻/宏观已确认可用，但历史特征端点覆盖仍不完整；先修通失败端点，再做增强回测。")
    else:
        lines.append("- 当前 CoinGlass 历史导出覆盖不足；先以 recent 风险层 + 手工事件库为主。")
    lines.append(f"- raw_cache_dir: {raw_dir}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Export and audit CoinGlass history coverage on the user's machine.")
    ap.add_argument("--project-dir", type=Path, default=Path("."))
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    run(args.project_dir.resolve(), args.out)


if __name__ == "__main__":
    main()
