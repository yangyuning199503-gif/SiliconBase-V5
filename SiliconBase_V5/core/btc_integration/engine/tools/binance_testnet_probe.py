from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import ssl
import sys
import time
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
import websocket
import yaml

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import contextlib

from src.live.binance_shadow import build_shadow_plan, write_shadow_plan


@dataclass
class ProbeResult:
    ok: bool
    detail: dict[str, Any]


def _now_ms() -> int:
    return int(time.time() * 1000)


def _sign(params: dict[str, Any], secret: str) -> str:
    payload = urlencode(params, doseq=True)
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _rest_request(
    session: requests.Session,
    method: str,
    base_url: str,
    path: str,
    params: dict[str, Any] | None = None,
    api_key: str | None = None,
    api_secret: str | None = None,
    signed: bool = False,
    timeout: int = 20,
) -> tuple[int, Any, dict[str, Any]]:
    params = dict(params or {})
    headers: dict[str, str] = {}
    if api_key:
        headers["X-MBX-APIKEY"] = api_key
    if signed:
        if not api_key or not api_secret:
            raise RuntimeError("signed request requires api key and secret")
        params.setdefault("timestamp", _now_ms())
        params.setdefault("recvWindow", 5000)
        params["signature"] = _sign(params, api_secret)
    url = base_url.rstrip("/") + path
    method = method.upper()
    if method == "GET":
        resp = session.get(url, params=params, headers=headers, timeout=timeout)
    elif method == "POST":
        resp = session.post(url, data=params, headers=headers, timeout=timeout)
    elif method == "PUT":
        resp = session.put(url, data=params, headers=headers, timeout=timeout)
    elif method == "DELETE":
        resp = session.delete(url, data=params, headers=headers, timeout=timeout)
    else:
        raise ValueError(f"unsupported method: {method}")
    content_type = resp.headers.get("content-type", "")
    try:
        data = resp.json() if "json" in content_type or resp.text[:1] in "[{" else resp.text
    except Exception:
        data = resp.text
    meta = {
        "url": resp.url,
        "headers": {k: resp.headers.get(k) for k in ["x-mbx-used-weight-1m", "x-mbx-order-count-10s", "x-mbx-order-count-1m"] if resp.headers.get(k) is not None},
    }
    return resp.status_code, data, meta


def _load_shadow_cfg(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if isinstance(data, dict):
        return data.get("shadow", data) or {}
    return {}


def _truthy_env(name: str) -> bool:
    v = os.environ.get(name, "")
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}


def _ws_sslopt() -> dict[str, Any]:
    ca_bundle = os.environ.get("BINANCE_WS_SSL_CA_BUNDLE") or requests.certs.where()
    insecure = _truthy_env("BINANCE_WS_INSECURE")
    if insecure:
        return {
            "cert_reqs": ssl.CERT_NONE,
            "check_hostname": False,
            "ca_bundle": ca_bundle,
            "verify_mode": "insecure",
        }
    return {
        "cert_reqs": ssl.CERT_REQUIRED,
        "check_hostname": True,
        "ca_certs": ca_bundle,
        "ca_bundle": ca_bundle,
        "verify_mode": "strict",
    }


def _ws_collect(url: str, seconds: float, max_messages: int = 20) -> ProbeResult:
    start = time.time()
    messages: list[dict[str, Any]] = []
    raw_count = 0
    sslopt = _ws_sslopt()
    ssl_debug = {
        "ssl_verify_mode": sslopt.get("verify_mode"),
        "ca_bundle": sslopt.get("ca_bundle"),
    }
    connect_sslopt = {k: v for k, v in sslopt.items() if k not in {"verify_mode", "ca_bundle"}}
    try:
        ws = websocket.create_connection(url, timeout=max(3.0, min(10.0, seconds)), sslopt=connect_sslopt)
        ws.settimeout(2.0)
    except Exception as e:
        return ProbeResult(False, {"connect_error": str(e), "url": url, **ssl_debug})
    try:
        while time.time() - start < seconds and raw_count < max_messages:
            try:
                msg = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            except Exception as e:
                messages.append({"type": "recv_error", "error": str(e)})
                break
            raw_count += 1
            try:
                payload = json.loads(msg)
            except Exception:
                payload = {"raw": str(msg)[:500]}
            messages.append(payload)
    finally:
        with contextlib.suppress(Exception):
            ws.close()
    return ProbeResult(True, {"url": url, "message_count": raw_count, "messages": messages, **ssl_debug})


def _extract_mark_prices(messages: list[dict[str, Any]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for msg in messages:
        data = msg.get("data") if isinstance(msg, dict) and "data" in msg else msg
        if not isinstance(data, dict):
            continue
        ev = str(data.get("e", ""))
        if ev != "markPriceUpdate":
            continue
        symbol = str(data.get("s", "")).upper()
        price = data.get("p")
        try:
            out[symbol] = float(price)
        except Exception:
            continue
    return out


def _fetch_mark_price_rest(session: requests.Session, rest_base: str, symbol: str) -> tuple[float | None, dict[str, Any]]:
    status, data, meta = _rest_request(session, "GET", rest_base, "/fapi/v1/premiumIndex", params={"symbol": symbol})
    if status != 200 or not isinstance(data, dict):
        return None, {"status_code": status, "meta": meta, "response": data}
    try:
        return float(data.get("markPrice")), {"status_code": status, "meta": meta}
    except Exception:
        return None, {"status_code": status, "meta": meta, "response": data}


def _symbol_rules(exchange_info: dict[str, Any], symbol: str) -> dict[str, Any]:
    for item in exchange_info.get("symbols", []):
        if str(item.get("symbol", "")).upper() == symbol.upper():
            return item
    raise KeyError(f"symbol not found in exchangeInfo: {symbol}")


def _filter_map(sym_info: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out = {}
    for f in sym_info.get("filters", []) or []:
        if isinstance(f, dict) and f.get("filterType"):
            out[str(f["filterType"])] = f
    return out


def _decimal_places(step: float) -> int:
    s = f"{step:.16f}".rstrip("0")
    if "." not in s:
        return 0
    return len(s.split(".", 1)[1])


def _quantize_qty(raw_qty: float, step: float, min_qty: float, *, round_up: bool = False) -> float:
    if step <= 0:
        return max(raw_qty, min_qty)
    qty = max(raw_qty, min_qty)
    q = Decimal(str(qty))
    st = Decimal(str(step))
    mn = Decimal(str(min_qty))
    rounding = ROUND_CEILING if round_up else ROUND_FLOOR
    n = (q / st).to_integral_value(rounding=rounding)
    out = n * st
    if out < mn:
        out = mn
    dp = _decimal_places(step)
    return float(f"{out:.{dp}f}")


def _build_market_order_test_payload(symbol: str, side: str, mark_price: float, sym_info: dict[str, Any], notional_usdt: float) -> dict[str, Any]:
    fmap = _filter_map(sym_info)
    lot = fmap.get("MARKET_LOT_SIZE") or fmap.get("LOT_SIZE") or {}
    min_qty = float(lot.get("minQty", "0") or 0)
    step = float(lot.get("stepSize", "0") or 0)
    min_notional = 5.0
    for key in ("MIN_NOTIONAL", "NOTIONAL"):
        if key in fmap:
            with contextlib.suppress(Exception):
                min_notional = max(min_notional, float(fmap[key].get("notional", fmap[key].get("minNotional", min_notional))))
    requested_notional = float(notional_usdt)
    target_notional = max(requested_notional, min_notional)
    # When exchangeInfo understates the actual floor or the lot step is coarse (e.g. BTC 0.001),
    # we want the smoke-test quantity to clear the minimum with some room instead of flooring below it.
    if target_notional <= min_notional + 1e-12:
        target_notional = min_notional * 1.01
    raw_qty = target_notional / max(mark_price, 1e-9)
    qty = _quantize_qty(raw_qty, step, min_qty, round_up=True)
    if qty * mark_price + 1e-9 < target_notional and step > 0:
        qty = _quantize_qty(qty + step, step, min_qty, round_up=True)
    return {
        "symbol": symbol.upper(),
        "side": side.upper(),
        "type": "MARKET",
        "quantity": qty,
        "newClientOrderId": f"probe_{symbol.lower()}_{side.lower()}_{int(time.time())}",
    }


def _extract_min_notional_from_error(data: Any) -> float | None:
    if not isinstance(data, dict):
        return None
    msg = str(data.get("msg", ""))
    if not msg:
        return None
    m = re.search(r"no smaller than\s+([0-9]+(?:\.[0-9]+)?)", msg, flags=re.I)
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None


def _summarize_messages(messages: list[dict[str, Any]]) -> dict[str, Any]:
    types: dict[str, int] = {}
    streams: dict[str, int] = {}
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        if "stream" in msg:
            streams[str(msg.get("stream"))] = streams.get(str(msg.get("stream")), 0) + 1
            data = msg.get("data")
        else:
            data = msg
        if isinstance(data, dict):
            ev = str(data.get("e", data.get("event", "unknown")))
            types[ev] = types.get(ev, 0) + 1
    return {"event_counts": types, "stream_counts": streams}


def _resolve_out(root: Path, path_like: str | Path) -> Path:
    p = Path(path_like)
    return p if p.is_absolute() else (root / p)


def _redact_url(value: str) -> str:
    if not isinstance(value, str):
        return value
    if value.startswith("wss://") or value.startswith("https://") or value.startswith("http://"):
        try:
            parts = urlsplit(value)
            path = parts.path
            if "/ws/" in path:
                head, tail = path.split("/ws/", 1)
                if tail and not any(ch in tail for ch in "?&#"):
                    path = head + "/ws/redacted"
            qs = []
            for k, v in parse_qsl(parts.query, keep_blank_values=True):
                if k.lower() in {"signature", "listenkey", "apikey"}:
                    v = "redacted"
                qs.append((k, v))
            return urlunsplit((parts.scheme, parts.netloc, path, urlencode(qs, doseq=True), parts.fragment))
        except Exception:
            return value
    return value


def _sanitize_obj(obj: Any, key_hint: str | None = None) -> Any:
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            kk = str(k)
            if kk.lower() in {"signature", "listenkey", "apikey"}:
                out[k] = "redacted"
            elif kk.lower().endswith("url") or kk.lower().endswith("template"):
                out[k] = _redact_url(str(v)) if isinstance(v, str) else _sanitize_obj(v, kk)
            else:
                out[k] = _sanitize_obj(v, kk)
        return out
    if isinstance(obj, list):
        return [_sanitize_obj(x, key_hint) for x in obj]
    if isinstance(obj, str):
        if key_hint and key_hint.lower() in {"listenkey", "signature", "apikey"}:
            return "redacted"
        return _redact_url(obj)
    return obj


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _write_text_summary(path: Path, report: dict[str, Any]) -> None:
    lines = []
    lines.append(f"testnet_probe_ok: {report.get('ok')}")
    plan = report.get("plan", {})
    lines.append(f"version: {plan.get('version')}")
    lines.append(f"contracts: {','.join(plan.get('contracts', []))}")
    market = report.get("market_ws", {})
    lines.append(f"market_ws_connected: {market.get('ok')}")
    if market.get("used_url"):
        lines.append(f"market_ws_url: {market.get('used_url')}")
    if market.get("ssl_verify_mode"):
        lines.append(f"market_ws_ssl_verify: {market.get('ssl_verify_mode')}")
    if market.get("ca_bundle"):
        lines.append(f"market_ws_ca_bundle: {market.get('ca_bundle')}")
    lines.append(f"market_ws_messages: {market.get('message_count', 0)}")
    lines.append(f"mark_prices: {report.get('mark_prices', {})}")
    lines.append(f"mark_prices_source: {report.get('mark_prices_source', {})}")
    private = report.get("private_ws", {})
    lines.append(f"private_ws_connected: {private.get('ok')}")
    if private.get("used_url"):
        lines.append(f"private_ws_url: {private.get('used_url')}")
    if private.get("ssl_verify_mode"):
        lines.append(f"private_ws_ssl_verify: {private.get('ssl_verify_mode')}")
    if private.get("ca_bundle"):
        lines.append(f"private_ws_ca_bundle: {private.get('ca_bundle')}")
    lines.append(f"private_ws_messages: {private.get('message_count', 0)}")
    if private.get('error'):
        lines.append(f"private_ws_error: {private.get('error')}")
    order_tests = report.get("order_tests", [])
    if order_tests:
        for row in order_tests:
            retry_tag = ""
            if row.get("retry_min_notional_hint"):
                retry_tag = f" retry_min_notional={row.get('retry_min_notional_hint')}"
            lines.append(f"order_test: {row.get('symbol')} {row.get('side')} status={row.get('status_code')} ok={row.get('ok')}{retry_tag}")
    else:
        lines.append("order_test: skipped")
    lines.append(f"notes: {' | '.join(report.get('notes', []))}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_private_urls(plan: dict[str, Any], listen_key: str) -> list[str]:
    eps = plan.get("endpoints", {})
    events = "/".join(plan.get("private_events", []))
    urls = []
    base = str(eps.get("private_ws_base", "") or "")
    if base:
        u = f"{base}{listen_key}"
        if events:
            u += f"&events={events}"
        urls.append(u)
    fallback = str(eps.get("private_ws_fallback_base", "") or "")
    if fallback:
        urls.append(f"{fallback}{listen_key}")
    return [u for i, u in enumerate(urls) if u and u not in urls[:i]]


def _private_ws_error(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    for msg in messages:
        if isinstance(msg, dict) and msg.get("error"):
            return msg.get("error") if isinstance(msg.get("error"), dict) else {"message": str(msg.get("error"))}
        if isinstance(msg, dict) and str(msg.get("e", "")).lower() in {"error", "listenkeyexpired"}:
            return msg
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Binance USD-M testnet probe (market/private websocket + signed endpoint smoke)")
    ap.add_argument("--config", default="shadow.yml")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--seconds", type=float, default=12.0)
    ap.add_argument("--out-json", default="reports/testnet_probe_latest.json")
    ap.add_argument("--out-jsonl", default="reports/testnet_probe_latest.jsonl")
    ap.add_argument("--out-txt", default="reports/testnet_probe_latest.txt")
    args = ap.parse_args()

    root = Path(args.project_dir).resolve()
    shadow_cfg = _load_shadow_cfg(root / args.config)
    with contextlib.suppress(Exception):
        write_shadow_plan(project_dir=root, out_json=root / "reports/shadow_mode_plan_latest.json", out_md=root / "reports/shadow_mode_plan_latest.md")
    plan = build_shadow_plan(project_dir=root)
    report: dict[str, Any] = {
        "ok": False,
        "ts_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        "plan": plan,
        "notes": [
            "private websocket probe defaults to listenKey over /private; the demo web UI lives on demo.binance.com but programmatic testnet access still uses the documented futures REST/WS endpoints",
            "set BINANCE_WS_INSECURE=1 only for temporary diagnostics if local CA trust is broken",
            "entry validation uses /fapi/v1/order/test only; no actual testnet order was submitted",
            "protective exits are preview-only because STOP_MARKET/TRAILING_STOP_MARKET now route through /fapi/v1/algoOrder",
            "probe redacts signatures and listenKeys before writing JSON / support bundles",
        ],
    }
    raw_records: list[dict[str, Any]] = []

    session = requests.Session()
    rest_base = plan["endpoints"]["rest_base"]

    status, exchange_info, meta = _rest_request(session, "GET", rest_base, "/fapi/v1/exchangeInfo")
    report["exchange_info"] = {"status_code": status, "meta": meta}
    if status != 200 or not isinstance(exchange_info, dict):
        report["notes"].append("exchangeInfo failed; aborting probe")
        sanitized_report = _sanitize_obj(report)
        _write_json(_resolve_out(root, args.out_json), sanitized_report)
        _write_text_summary(_resolve_out(root, args.out_txt), sanitized_report)
        return

    market_urls = [plan["market_stream_url"], plan.get("market_stream_url_fallback")]
    market_result = None
    market_used_url = None
    for u in [x for x in market_urls if x]:
        pr = _ws_collect(u, seconds=max(3.0, args.seconds), max_messages=30)
        raw_records.append({"channel": "market_ws_attempt", "url": u, **pr.detail})
        if pr.ok and pr.detail.get("message_count", 0) > 0:
            market_result = pr
            market_used_url = u
            break
        if pr.ok and market_result is None:
            market_result = pr
            market_used_url = u
    report["market_ws"] = {
        "ok": bool(market_result and market_result.ok),
        "used_url": market_used_url,
        "message_count": int((market_result.detail.get("message_count") if market_result else 0) or 0),
        "ssl_verify_mode": (market_result.detail.get("ssl_verify_mode") if market_result else None),
        "ca_bundle": (market_result.detail.get("ca_bundle") if market_result else None),
        **(_summarize_messages(market_result.detail.get("messages", [])) if market_result else {}),
    }
    mark_prices = _extract_mark_prices(market_result.detail.get("messages", []) if market_result else [])
    mark_price_source: dict[str, str] = dict.fromkeys(mark_prices, "market_ws")

    auth_cfg = shadow_cfg.get("auth", {}) if isinstance(shadow_cfg, dict) else {}
    key_env = str(auth_cfg.get("api_key_env", "BINANCE_API_KEY"))
    secret_env = str(auth_cfg.get("api_secret_env", "BINANCE_API_SECRET"))
    api_key = os.environ.get(key_env)
    api_secret = os.environ.get(secret_env)
    report["auth"] = {
        "api_key_present": bool(api_key),
        "api_secret_present": bool(api_secret),
        "api_key_env": key_env,
        "api_secret_env": secret_env,
    }

    rest_mark_meta: dict[str, Any] = {}
    for symbol in plan.get("contracts", []):
        if symbol in mark_prices:
            continue
        price, detail = _fetch_mark_price_rest(session, rest_base, symbol)
        rest_mark_meta[symbol] = detail
        if price is not None:
            mark_prices[symbol] = price
            mark_price_source[symbol] = "rest_premiumIndex"
    report["mark_prices"] = mark_prices
    report["mark_prices_source"] = mark_price_source
    report["mark_prices_rest"] = rest_mark_meta

    if api_key and api_secret:
        status, lk_payload, meta = _rest_request(session, "POST", rest_base, "/fapi/v1/listenKey", api_key=api_key)
        listen_key = lk_payload.get("listenKey") if isinstance(lk_payload, dict) else None
        report["listen_key"] = {"status_code": status, "ok": bool(status == 200 and listen_key), "meta": meta}

        private_result = None
        private_used_url = None
        private_error = None
        if listen_key:
            for u in _build_private_urls(plan, listen_key):
                pr = _ws_collect(u, seconds=min(max(4.0, args.seconds / 2.0), 8.0), max_messages=10)
                raw_records.append({"channel": "private_ws_attempt", "url": u, **pr.detail})
                err = _private_ws_error(pr.detail.get("messages", [])) if pr.ok else None
                if pr.ok and err is None:
                    private_result = pr
                    private_used_url = u
                    private_error = None
                    break
                if pr.ok and private_result is None:
                    private_result = pr
                    private_used_url = u
                    private_error = err
                elif not pr.ok and private_result is None:
                    private_result = pr
                    private_used_url = u
                    private_error = None
        report["private_ws"] = {
            "ok": bool(private_result and private_result.ok and not private_error),
            "used_url": private_used_url,
            "message_count": int((private_result.detail.get("message_count") if private_result else 0) or 0),
            "ssl_verify_mode": private_result.detail.get("ssl_verify_mode") if private_result else None,
            "ca_bundle": private_result.detail.get("ca_bundle") if private_result else None,
            "probe_mode": plan.get("private_ws_probe_mode"),
            **(_summarize_messages(private_result.detail.get("messages", [])) if private_result else {}),
        }
        if private_error:
            report["private_ws"]["error"] = private_error
        elif private_result and not private_result.ok:
            report["private_ws"]["error"] = {"connect_error": private_result.detail.get("connect_error")}

        with contextlib.suppress(Exception):
            _rest_request(session, "PUT", rest_base, "/fapi/v1/listenKey", api_key=api_key)
        with contextlib.suppress(Exception):
            _rest_request(session, "DELETE", rest_base, "/fapi/v1/listenKey", api_key=api_key)

        q_status, q_payload, q_meta = _rest_request(session, "GET", rest_base, "/fapi/v1/openOrders", api_key=api_key, api_secret=api_secret, signed=True)
        report["open_orders_query"] = {"status_code": q_status, "ok": q_status == 200, "meta": q_meta, "count": len(q_payload) if isinstance(q_payload, list) else None}
        qa_status, qa_payload, qa_meta = _rest_request(session, "GET", rest_base, "/fapi/v1/openAlgoOrders", api_key=api_key, api_secret=api_secret, signed=True, params={"symbol": plan["contracts"][0]})
        report["open_algo_orders_query"] = {"status_code": qa_status, "ok": qa_status == 200, "meta": qa_meta, "count": len(qa_payload) if isinstance(qa_payload, list) else None}

        order_tests: list[dict[str, Any]] = []
        if plan.get("order_test", {}).get("enabled", True):
            test_notional = float(plan.get("order_test", {}).get("notional_usdt", 10.0))
            for symbol in plan.get("contracts", []):
                try:
                    sym_info = _symbol_rules(exchange_info, symbol)
                except Exception as e:
                    order_tests.append({"symbol": symbol, "ok": False, "error": str(e)})
                    continue
                mark_price = mark_prices.get(symbol)
                if not mark_price:
                    order_tests.append({"symbol": symbol, "ok": False, "error": "mark price unavailable from market ws and REST fallback; skipped"})
                    continue
                side = "SELL" if symbol.upper().startswith("BTC") else "BUY"
                payload = _build_market_order_test_payload(symbol, side, mark_price, sym_info, test_notional)
                attempts: list[dict[str, Any]] = []
                retry_hint = None
                try:
                    st, data, meta = _rest_request(session, "POST", rest_base, "/fapi/v1/order/test", params=payload, api_key=api_key, api_secret=api_secret, signed=True)
                    attempts.append({"payload": payload, "status_code": st, "response": data, "meta": meta})
                    retry_hint = _extract_min_notional_from_error(data)
                    final_payload = payload
                    final_status = st
                    final_data = data
                    final_meta = meta
                    if final_status != 200 and retry_hint is not None:
                        hinted_payload = _build_market_order_test_payload(symbol, side, mark_price, sym_info, max(test_notional, retry_hint * 1.01))
                        if hinted_payload != payload:
                            st2, data2, meta2 = _rest_request(session, "POST", rest_base, "/fapi/v1/order/test", params=hinted_payload, api_key=api_key, api_secret=api_secret, signed=True)
                            attempts.append({"payload": hinted_payload, "status_code": st2, "response": data2, "meta": meta2})
                            final_payload = hinted_payload
                            final_status = st2
                            final_data = data2
                            final_meta = meta2
                    order_tests.append({
                        "symbol": symbol,
                        "side": side,
                        "mark_price": mark_price,
                        "mark_price_source": mark_price_source.get(symbol),
                        "payload": final_payload,
                        "status_code": final_status,
                        "ok": final_status == 200,
                        "response": final_data,
                        "meta": final_meta,
                        "attempts": attempts,
                        "retry_min_notional_hint": retry_hint,
                        "protective_exit_preview": {
                            "submit_endpoint": "/fapi/v1/algoOrder",
                            "types": ["STOP_MARKET", "TRAILING_STOP_MARKET"],
                            "workingType": "MARK_PRICE",
                            "priceProtect": True,
                            "submitted": False,
                        },
                    })
                except Exception as e:
                    order_tests.append({
                        "symbol": symbol,
                        "side": side,
                        "mark_price": mark_price,
                        "mark_price_source": mark_price_source.get(symbol),
                        "payload": payload,
                        "ok": False,
                        "error": str(e),
                    })
        report["order_tests"] = order_tests
    else:
        report["listen_key"] = {"ok": False, "reason": "missing api key / secret"}
        report["private_ws"] = {"ok": False, "reason": "missing api key / secret", "probe_mode": plan.get("private_ws_probe_mode")}
        report["open_orders_query"] = {"ok": False, "reason": "missing api key / secret"}
        report["open_algo_orders_query"] = {"ok": False, "reason": "missing api key / secret"}
        report["order_tests"] = []

    market_ok = bool(report.get("market_ws", {}).get("ok"))
    private_ok = bool(report.get("private_ws", {}).get("ok")) if api_key and api_secret else True
    signed_ok = bool(report.get("open_orders_query", {}).get("ok")) if api_key and api_secret else True
    order_tests = report.get("order_tests", [])
    order_test_ok = True
    if api_key and api_secret and order_tests:
        order_test_ok = all(bool(x.get("ok")) for x in order_tests)
    report["ok"] = bool(market_ok and private_ok and signed_ok and order_test_ok)

    sanitized_report = _sanitize_obj(report)
    sanitized_raw_records = _sanitize_obj(raw_records)
    _write_json(_resolve_out(root, args.out_json), sanitized_report)
    _write_jsonl(_resolve_out(root, args.out_jsonl), sanitized_raw_records)
    _write_text_summary(_resolve_out(root, args.out_txt), sanitized_report)
    print(json.dumps({
        "ok": sanitized_report["ok"],
        "market_ws": sanitized_report.get("market_ws", {}).get("ok"),
        "private_ws": sanitized_report.get("private_ws", {}).get("ok"),
        "order_tests": [{k: r.get(k) for k in ("symbol", "ok", "status_code", "retry_min_notional_hint")} for r in sanitized_report.get("order_tests", [])],
        "out_json": str(_resolve_out(root, args.out_json)),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
