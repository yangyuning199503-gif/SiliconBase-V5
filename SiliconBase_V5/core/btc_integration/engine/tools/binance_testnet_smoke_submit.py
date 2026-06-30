from __future__ import annotations

import argparse
import json
import os
import sys
import time
from decimal import ROUND_FLOOR, Decimal
from pathlib import Path
from typing import Any

import requests
import websocket

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import contextlib

from src.live.binance_shadow import build_shadow_plan, write_shadow_plan
from tools.binance_testnet_probe import (
    _build_market_order_test_payload,
    _build_private_urls,
    _decimal_places,
    _fetch_mark_price_rest,
    _filter_map,
    _load_shadow_cfg,
    _resolve_out,
    _rest_request,
    _sanitize_obj,
    _summarize_messages,
    _symbol_rules,
    _write_json,
    _write_jsonl,
    _ws_sslopt,
)


def _read_ws_messages(ws: websocket.WebSocket, seconds: float, max_messages: int = 80) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    start = time.time()
    while time.time() - start < seconds and len(out) < max_messages:
        try:
            raw = ws.recv()
        except websocket.WebSocketTimeoutException:
            continue
        except Exception as e:
            out.append({"type": "recv_error", "error": str(e)})
            break
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"raw": str(raw)[:1000]}
        out.append(payload)
    return out


def _connect_private_ws(plan: dict[str, Any], listen_key: str, seconds_timeout: float = 6.0) -> tuple[websocket.WebSocket | None, dict[str, Any]]:
    urls = _build_private_urls(plan, listen_key)
    sslopt = _ws_sslopt()
    ssl_debug = {
        "ssl_verify_mode": sslopt.get("verify_mode"),
        "ca_bundle": sslopt.get("ca_bundle"),
    }
    connect_sslopt = {k: v for k, v in sslopt.items() if k not in {"verify_mode", "ca_bundle"}}
    last_error = None
    for url in urls:
        try:
            ws = websocket.create_connection(url, timeout=max(3.0, seconds_timeout), sslopt=connect_sslopt)
            ws.settimeout(0.5)
            return ws, {"ok": True, "used_url": url, **ssl_debug}
        except Exception as e:
            last_error = {"url": url, "connect_error": str(e), **ssl_debug}
    return None, {"ok": False, **(last_error or ssl_debug)}


def _query_position_mode(session: requests.Session, rest_base: str, api_key: str, api_secret: str) -> dict[str, Any]:
    st, data, meta = _rest_request(session, "GET", rest_base, "/fapi/v1/positionSide/dual", api_key=api_key, api_secret=api_secret, signed=True)
    dual = None
    if st == 200 and isinstance(data, dict):
        dual = bool(data.get("dualSidePosition"))
    return {"status_code": st, "ok": st == 200, "meta": meta, "response": data, "dualSidePosition": dual}


def _query_balance(session: requests.Session, rest_base: str, api_key: str, api_secret: str) -> dict[str, Any]:
    st, data, meta = _rest_request(session, "GET", rest_base, "/fapi/v3/balance", api_key=api_key, api_secret=api_secret, signed=True)
    out: dict[str, Any] = {"status_code": st, "ok": st == 200, "meta": meta}
    if st == 200 and isinstance(data, list):
        for row in data:
            if isinstance(row, dict) and str(row.get("asset", "")).upper() == "USDT":
                out["usdt"] = {
                    "balance": row.get("balance"),
                    "availableBalance": row.get("availableBalance"),
                    "crossWalletBalance": row.get("crossWalletBalance"),
                }
                break
    else:
        out["response"] = data
    return out


def _query_open_orders(session: requests.Session, rest_base: str, api_key: str, api_secret: str, symbol: str) -> dict[str, Any]:
    st, data, meta = _rest_request(session, "GET", rest_base, "/fapi/v1/openOrders", params={"symbol": symbol}, api_key=api_key, api_secret=api_secret, signed=True)
    return {"status_code": st, "ok": st == 200, "meta": meta, "count": len(data) if isinstance(data, list) else None, "orders": data if isinstance(data, list) else data}


def _query_open_algo_orders(session: requests.Session, rest_base: str, api_key: str, api_secret: str, symbol: str) -> dict[str, Any]:
    st, data, meta = _rest_request(session, "GET", rest_base, "/fapi/v1/openAlgoOrders", params={"symbol": symbol}, api_key=api_key, api_secret=api_secret, signed=True)
    return {"status_code": st, "ok": st == 200, "meta": meta, "count": len(data) if isinstance(data, list) else None, "orders": data if isinstance(data, list) else data}


def _query_position_rows(session: requests.Session, rest_base: str, api_key: str, api_secret: str, symbol: str) -> dict[str, Any]:
    st, data, meta = _rest_request(session, "GET", rest_base, "/fapi/v2/positionRisk", params={"symbol": symbol}, api_key=api_key, api_secret=api_secret, signed=True)
    rows = data if isinstance(data, list) else []
    return {"status_code": st, "ok": st == 200, "meta": meta, "rows": rows, "response": None if isinstance(data, list) else data}


def _query_order(session: requests.Session, rest_base: str, api_key: str, api_secret: str, symbol: str, *, order_id: Any | None = None, client_order_id: str | None = None) -> dict[str, Any]:
    params: dict[str, Any] = {"symbol": symbol}
    if order_id is not None:
        params["orderId"] = order_id
    elif client_order_id:
        params["origClientOrderId"] = client_order_id
    else:
        raise ValueError("order_id or client_order_id required")
    st, data, meta = _rest_request(session, "GET", rest_base, "/fapi/v1/order", params=params, api_key=api_key, api_secret=api_secret, signed=True)
    return {"status_code": st, "ok": st == 200, "meta": meta, "response": data}


def _position_qty_from_rows(rows: list[dict[str, Any]], symbol: str, dual_side: bool, entry_position_side: str | None) -> tuple[Decimal, dict[str, Any] | None]:
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("symbol", "")).upper() != symbol.upper():
            continue
        ps = str(row.get("positionSide", "BOTH")).upper()
        if dual_side and entry_position_side and ps != entry_position_side.upper():
            continue
        try:
            amt = Decimal(str(row.get("positionAmt", "0")))
        except Exception:
            continue
        if abs(amt) > Decimal("0"):
            return abs(amt), row
    return Decimal("0"), None


def _lot_rules(sym_info: dict[str, Any]) -> tuple[float, float]:
    fmap = _filter_map(sym_info)
    lot = fmap.get("MARKET_LOT_SIZE") or fmap.get("LOT_SIZE") or {}
    min_qty = float(lot.get("minQty", "0") or 0)
    step = float(lot.get("stepSize", "0") or 0)
    return min_qty, step


def _normalize_qty_str(value: Any, step: float) -> str | None:
    if value is None:
        return None
    try:
        d = Decimal(str(value)).copy_abs()
    except Exception:
        return None
    if d <= 0:
        return None
    if step > 0:
        st = Decimal(str(step))
        n = (d / st).to_integral_value(rounding=ROUND_FLOOR)
        d = n * st
    if d <= 0:
        return None
    dp = _decimal_places(step) if step > 0 else max(0, -d.as_tuple().exponent)
    return f"{d:.{dp}f}" if dp > 0 else str(int(d))


def _poll_order_or_position(
    session: requests.Session,
    rest_base: str,
    api_key: str,
    api_secret: str,
    symbol: str,
    *,
    order_id: Any | None,
    client_order_id: str | None,
    dual_side: bool,
    entry_position_side: str | None,
    timeout_seconds: float = 4.0,
) -> dict[str, Any]:
    deadline = time.time() + max(0.5, timeout_seconds)
    last_order = None
    last_pos = None
    while time.time() < deadline:
        try:
            if order_id is not None or client_order_id:
                last_order = _query_order(session, rest_base, api_key, api_secret, symbol, order_id=order_id, client_order_id=client_order_id)
                resp = last_order.get("response")
                if isinstance(resp, dict):
                    try:
                        exec_qty = Decimal(str(resp.get("executedQty", "0")))
                    except Exception:
                        exec_qty = Decimal("0")
                    status = str(resp.get("status", ""))
                    if exec_qty > 0 and status in {"FILLED", "PARTIALLY_FILLED", "NEW"}:
                        return {"order": last_order, "position": last_pos}
        except Exception:
            pass
        try:
            last_pos = _query_position_rows(session, rest_base, api_key, api_secret, symbol)
            rows = last_pos.get("rows", []) if isinstance(last_pos, dict) else []
            qty, _row = _position_qty_from_rows(rows, symbol, dual_side, entry_position_side)
            if qty > 0:
                return {"order": last_order, "position": last_pos}
        except Exception:
            pass
        time.sleep(0.4)
    return {"order": last_order, "position": last_pos}


def _cancel_open_orders(session: requests.Session, rest_base: str, api_key: str, api_secret: str, symbol: str) -> dict[str, Any]:
    st, data, meta = _rest_request(session, "DELETE", rest_base, "/fapi/v1/allOpenOrders", params={"symbol": symbol}, api_key=api_key, api_secret=api_secret, signed=True)
    return {"status_code": st, "ok": st == 200, "meta": meta, "response": data}


def _cancel_open_algo_orders(session: requests.Session, rest_base: str, api_key: str, api_secret: str, symbol: str) -> dict[str, Any]:
    st, data, meta = _rest_request(session, "DELETE", rest_base, "/fapi/v1/algoOpenOrders", params={"symbol": symbol}, api_key=api_key, api_secret=api_secret, signed=True)
    return {"status_code": st, "ok": st == 200, "meta": meta, "response": data}


def _cleanup_listen_key(session: requests.Session, rest_base: str, api_key: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        st, data, meta = _rest_request(session, "PUT", rest_base, "/fapi/v1/listenKey", api_key=api_key)
        out["keepalive"] = {"status_code": st, "ok": st == 200, "meta": meta, "response": data}
    except Exception as e:
        out["keepalive"] = {"ok": False, "error": str(e)}
    try:
        st, data, meta = _rest_request(session, "DELETE", rest_base, "/fapi/v1/listenKey", api_key=api_key)
        out["delete"] = {"status_code": st, "ok": st == 200, "meta": meta, "response": data}
    except Exception as e:
        out["delete"] = {"ok": False, "error": str(e)}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Submit one tiny Binance Futures Demo MARKET order, capture private callbacks, then auto-flatten")
    ap.add_argument("--config", default="shadow.yml")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--symbol", default="BNBUSDT")
    ap.add_argument("--side", default="BUY", choices=["BUY", "SELL"])
    ap.add_argument("--notional-usdt", type=float, default=15.0)
    ap.add_argument("--entry-wait", type=float, default=3.0)
    ap.add_argument("--exit-wait", type=float, default=3.0)
    ap.add_argument("--out-json", default="reports/testnet_smoke_submit_latest.json")
    ap.add_argument("--out-jsonl", default="reports/testnet_smoke_submit_latest.jsonl")
    ap.add_argument("--out-txt", default="reports/testnet_smoke_submit_latest.txt")
    ap.add_argument("--confirm-demo", action="store_true", help="确认这会在 Binance Futures Demo 上提交一笔真实的模拟单并自动平仓")
    args = ap.parse_args()

    root = Path(args.project_dir).resolve()
    shadow_cfg = _load_shadow_cfg(root / args.config)
    with contextlib.suppress(Exception):
        write_shadow_plan(project_dir=root, out_json=root / "reports/shadow_mode_plan_latest.json", out_md=root / "reports/shadow_mode_plan_latest.md")
    plan = build_shadow_plan(project_dir=root)

    report: dict[str, Any] = {
        "ok": False,
        "ts_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        "mode": "demo_smoke_submit",
        "plan_version": plan.get("version"),
        "symbol": str(args.symbol).upper(),
        "side": str(args.side).upper(),
        "notional_usdt": float(args.notional_usdt),
        "confirm_demo": bool(args.confirm_demo),
        "notes": [
            "this tool is for Binance Futures Demo only and refuses to run on non-demo REST endpoints",
            "it submits one tiny MARKET entry order, waits for user-data callbacks, then auto-flattens the position",
            "it aborts if the chosen symbol already has open orders, open algo orders, or a non-zero position",
            "protective algo orders remain outside this smoke path; they still use /fapi/v1/algoOrder",
        ],
    }
    raw_records: list[dict[str, Any]] = []

    if not args.confirm_demo:
        report["reason"] = "missing --confirm-demo"
        report["how_to_run"] = "./.venv/bin/python -m tools.binance_testnet_smoke_submit --project-dir . --confirm-demo"
        sanitized_report = _sanitize_obj(report)
        _write_json(_resolve_out(root, args.out_json), sanitized_report)
        _write_jsonl(_resolve_out(root, args.out_jsonl), [])
        _resolve_out(root, args.out_txt).write_text(
            "testnet_smoke_submit_ok: False\nreason: missing --confirm-demo\n" +
            "how_to_run: ./.venv/bin/python -m tools.binance_testnet_smoke_submit --project-dir . --confirm-demo\n",
            encoding="utf-8",
        )
        print(json.dumps({"ok": False, "reason": "missing --confirm-demo", "out_json": str(_resolve_out(root, args.out_json))}, ensure_ascii=False))
        return

    rest_base = str(plan.get("endpoints", {}).get("rest_base", ""))
    report["rest_base"] = rest_base
    report["testnet"] = bool(plan.get("testnet"))
    if not plan.get("testnet") or "demo-fapi.binance.com" not in rest_base:
        report["reason"] = "refused_non_demo_endpoint"
        sanitized_report = _sanitize_obj(report)
        _write_json(_resolve_out(root, args.out_json), sanitized_report)
        _write_jsonl(_resolve_out(root, args.out_jsonl), [])
        _resolve_out(root, args.out_txt).write_text(
            f"testnet_smoke_submit_ok: False\nreason: {report['reason']}\nrest_base: {rest_base}\n",
            encoding="utf-8",
        )
        print(json.dumps({"ok": False, "reason": report["reason"], "rest_base": rest_base, "out_json": str(_resolve_out(root, args.out_json))}, ensure_ascii=False))
        return

    session = requests.Session()
    symbol = str(args.symbol).upper()
    side = str(args.side).upper()

    status, exchange_info, meta = _rest_request(session, "GET", rest_base, "/fapi/v1/exchangeInfo")
    report["exchange_info"] = {"status_code": status, "ok": status == 200, "meta": meta}
    if status != 200 or not isinstance(exchange_info, dict):
        report["reason"] = "exchange_info_failed"
        report["exchange_info"]["response"] = exchange_info
        sanitized_report = _sanitize_obj(report)
        _write_json(_resolve_out(root, args.out_json), sanitized_report)
        _write_jsonl(_resolve_out(root, args.out_jsonl), [])
        _resolve_out(root, args.out_txt).write_text(
            f"testnet_smoke_submit_ok: False\nreason: {report['reason']}\n",
            encoding="utf-8",
        )
        print(json.dumps({"ok": False, "reason": report["reason"], "out_json": str(_resolve_out(root, args.out_json))}, ensure_ascii=False))
        return

    try:
        sym_info = _symbol_rules(exchange_info, symbol)
    except Exception as e:
        report["reason"] = "symbol_not_found"
        report["error"] = str(e)
        sanitized_report = _sanitize_obj(report)
        _write_json(_resolve_out(root, args.out_json), sanitized_report)
        _write_jsonl(_resolve_out(root, args.out_jsonl), [])
        _resolve_out(root, args.out_txt).write_text(
            f"testnet_smoke_submit_ok: False\nreason: {report['reason']}\nerror: {e}\n",
            encoding="utf-8",
        )
        print(json.dumps({"ok": False, "reason": report["reason"], "error": str(e), "out_json": str(_resolve_out(root, args.out_json))}, ensure_ascii=False))
        return

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
    if not api_key or not api_secret:
        report["reason"] = "missing_api_credentials"
        sanitized_report = _sanitize_obj(report)
        _write_json(_resolve_out(root, args.out_json), sanitized_report)
        _write_jsonl(_resolve_out(root, args.out_jsonl), [])
        _resolve_out(root, args.out_txt).write_text(
            f"testnet_smoke_submit_ok: False\nreason: {report['reason']}\n",
            encoding="utf-8",
        )
        print(json.dumps({"ok": False, "reason": report["reason"], "out_json": str(_resolve_out(root, args.out_json))}, ensure_ascii=False))
        return

    report["balance"] = _query_balance(session, rest_base, api_key, api_secret)
    report["position_mode"] = _query_position_mode(session, rest_base, api_key, api_secret)
    dual_side = bool(report["position_mode"].get("dualSidePosition"))
    entry_position_side = "LONG" if side == "BUY" else "SHORT"

    mark_price, mark_meta = _fetch_mark_price_rest(session, rest_base, symbol)
    report["mark_price"] = {"symbol": symbol, "price": mark_price, "source": "rest_premiumIndex", "detail": mark_meta}
    if not mark_price:
        report["reason"] = "mark_price_unavailable"
        sanitized_report = _sanitize_obj(report)
        _write_json(_resolve_out(root, args.out_json), sanitized_report)
        _write_jsonl(_resolve_out(root, args.out_jsonl), [])
        _resolve_out(root, args.out_txt).write_text(
            f"testnet_smoke_submit_ok: False\nreason: {report['reason']}\n",
            encoding="utf-8",
        )
        print(json.dumps({"ok": False, "reason": report["reason"], "out_json": str(_resolve_out(root, args.out_json))}, ensure_ascii=False))
        return

    report["pre_open_orders"] = _query_open_orders(session, rest_base, api_key, api_secret, symbol)
    report["pre_open_algo_orders"] = _query_open_algo_orders(session, rest_base, api_key, api_secret, symbol)
    report["pre_positions"] = _query_position_rows(session, rest_base, api_key, api_secret, symbol)
    pre_qty, pre_row = _position_qty_from_rows(report["pre_positions"].get("rows", []), symbol, dual_side, entry_position_side if dual_side else None)
    report["pre_positions"]["active_qty"] = str(pre_qty)
    if pre_row is not None:
        report["pre_positions"]["active_row"] = pre_row
    if (report["pre_open_orders"].get("count") or 0) > 0 or (report["pre_open_algo_orders"].get("count") or 0) > 0 or pre_qty > 0:
        report["reason"] = "symbol_not_clean"
        sanitized_report = _sanitize_obj(report)
        _write_json(_resolve_out(root, args.out_json), sanitized_report)
        _write_jsonl(_resolve_out(root, args.out_jsonl), [])
        _resolve_out(root, args.out_txt).write_text(
            "testnet_smoke_submit_ok: False\n"
            f"reason: {report['reason']}\n"
            f"symbol: {symbol}\n"
            f"pre_open_orders: {report['pre_open_orders'].get('count')}\n"
            f"pre_open_algo_orders: {report['pre_open_algo_orders'].get('count')}\n"
            f"pre_active_qty: {report['pre_positions'].get('active_qty')}\n",
            encoding="utf-8",
        )
        print(json.dumps({"ok": False, "reason": report["reason"], "symbol": symbol, "out_json": str(_resolve_out(root, args.out_json))}, ensure_ascii=False))
        return

    listen_key = None
    ws = None
    ws_meta: dict[str, Any] = {}
    all_private_messages: list[dict[str, Any]] = []

    try:
        st, lk_payload, meta = _rest_request(session, "POST", rest_base, "/fapi/v1/listenKey", api_key=api_key)
        listen_key = lk_payload.get("listenKey") if isinstance(lk_payload, dict) else None
        report["listen_key"] = {"status_code": st, "ok": bool(st == 200 and listen_key), "meta": meta}
        if not listen_key:
            report["reason"] = "listen_key_failed"
            report["listen_key"]["response"] = lk_payload
            raise RuntimeError("listen key unavailable")

        ws, ws_meta = _connect_private_ws(plan, listen_key)
        report["private_ws"] = dict(ws_meta)
        if not ws:
            report["reason"] = "private_ws_connect_failed"
            raise RuntimeError(report["private_ws"].get("connect_error") or "private ws connect failed")

        entry_payload = _build_market_order_test_payload(symbol, side, float(mark_price), sym_info, float(args.notional_usdt))
        entry_payload["newClientOrderId"] = f"smoke_entry_{symbol.lower()}_{side.lower()}_{int(time.time())}"
        entry_payload["newOrderRespType"] = "RESULT"
        if dual_side:
            entry_payload["positionSide"] = entry_position_side
        report["entry_payload"] = entry_payload

        entry_st, entry_data, entry_meta = _rest_request(session, "POST", rest_base, "/fapi/v1/order", params=entry_payload, api_key=api_key, api_secret=api_secret, signed=True)
        report["entry_order"] = {"status_code": entry_st, "ok": entry_st == 200, "meta": entry_meta, "response": entry_data}
        raw_records.append({"channel": "entry_order_response", "status_code": entry_st, "meta": entry_meta, "response": entry_data})
        if entry_st != 200:
            report["reason"] = "entry_order_failed"
            raise RuntimeError(str(entry_data))

        entry_private = _read_ws_messages(ws, float(args.entry_wait), max_messages=80)
        all_private_messages.extend(entry_private)
        raw_records.extend({"channel": "private_ws", "phase": "after_entry", "message": m} for m in entry_private)

        entry_order_id = entry_data.get("orderId") if isinstance(entry_data, dict) else None
        entry_client_order_id = entry_payload.get("newClientOrderId")
        report["entry_followup"] = _poll_order_or_position(
            session,
            rest_base,
            api_key,
            api_secret,
            symbol,
            order_id=entry_order_id,
            client_order_id=entry_client_order_id,
            dual_side=dual_side,
            entry_position_side=entry_position_side if dual_side else None,
            timeout_seconds=4.0,
        )

        min_qty, step = _lot_rules(sym_info)
        exit_qty_str = None
        entry_follow_order = report["entry_followup"].get("order")
        if isinstance(entry_follow_order, dict) and entry_follow_order.get("ok"):
            od = entry_follow_order.get("response")
            if isinstance(od, dict):
                exit_qty_str = _normalize_qty_str(od.get("executedQty"), step)
        if not exit_qty_str:
            pos_follow = report["entry_followup"].get("position")
            pos_rows = pos_follow.get("rows", []) if isinstance(pos_follow, dict) else []
            qty, _row = _position_qty_from_rows(pos_rows, symbol, dual_side, entry_position_side if dual_side else None)
            exit_qty_str = _normalize_qty_str(qty, step)
        report["entry_effective_qty"] = exit_qty_str
        if not exit_qty_str:
            report["reason"] = "entry_qty_unresolved"
            raise RuntimeError("entry filled quantity unresolved")

        exit_side = "SELL" if side == "BUY" else "BUY"
        exit_payload: dict[str, Any] = {
            "symbol": symbol,
            "side": exit_side,
            "type": "MARKET",
            "quantity": exit_qty_str,
            "newClientOrderId": f"smoke_exit_{symbol.lower()}_{exit_side.lower()}_{int(time.time())}",
            "newOrderRespType": "RESULT",
        }
        if dual_side:
            exit_payload["positionSide"] = entry_position_side
        else:
            exit_payload["reduceOnly"] = "true"
        report["exit_payload"] = exit_payload

        exit_st, exit_data, exit_meta = _rest_request(session, "POST", rest_base, "/fapi/v1/order", params=exit_payload, api_key=api_key, api_secret=api_secret, signed=True)
        report["exit_order"] = {"status_code": exit_st, "ok": exit_st == 200, "meta": exit_meta, "response": exit_data}
        raw_records.append({"channel": "exit_order_response", "status_code": exit_st, "meta": exit_meta, "response": exit_data})
        if exit_st != 200:
            report["reason"] = "exit_order_failed"
        exit_private = _read_ws_messages(ws, float(args.exit_wait), max_messages=80)
        all_private_messages.extend(exit_private)
        raw_records.extend({"channel": "private_ws", "phase": "after_exit", "message": m} for m in exit_private)

        if exit_st == 200:
            exit_order_id = exit_data.get("orderId") if isinstance(exit_data, dict) else None
            exit_client_order_id = exit_payload.get("newClientOrderId")
            report["exit_followup"] = _poll_order_or_position(
                session,
                rest_base,
                api_key,
                api_secret,
                symbol,
                order_id=exit_order_id,
                client_order_id=exit_client_order_id,
                dual_side=dual_side,
                entry_position_side=entry_position_side if dual_side else None,
                timeout_seconds=4.0,
            )
        else:
            report["exit_followup"] = None

        post_positions = _query_position_rows(session, rest_base, api_key, api_secret, symbol)
        post_qty, post_row = _position_qty_from_rows(post_positions.get("rows", []), symbol, dual_side, entry_position_side if dual_side else None)
        post_positions["active_qty"] = str(post_qty)
        if post_row is not None:
            post_positions["active_row"] = post_row
        report["post_positions_before_cleanup"] = post_positions

        report["cleanup"] = {
            "cancel_open_orders": _cancel_open_orders(session, rest_base, api_key, api_secret, symbol),
            "cancel_open_algo_orders": _cancel_open_algo_orders(session, rest_base, api_key, api_secret, symbol),
        }
        report["post_open_orders"] = _query_open_orders(session, rest_base, api_key, api_secret, symbol)
        report["post_open_algo_orders"] = _query_open_algo_orders(session, rest_base, api_key, api_secret, symbol)
        report["post_positions"] = _query_position_rows(session, rest_base, api_key, api_secret, symbol)
        final_qty, final_row = _position_qty_from_rows(report["post_positions"].get("rows", []), symbol, dual_side, entry_position_side if dual_side else None)
        report["post_positions"]["active_qty"] = str(final_qty)
        if final_row is not None:
            report["post_positions"]["active_row"] = final_row

        summary = _summarize_messages(all_private_messages)
        report["private_ws"].update({
            "message_count": len(all_private_messages),
            **summary,
        })
        report["private_events_preview"] = all_private_messages[:30]

        report["ok"] = bool(
            report.get("entry_order", {}).get("ok")
            and report.get("exit_order", {}).get("ok")
            and (report.get("post_open_orders", {}).get("count") or 0) == 0
            and (report.get("post_open_algo_orders", {}).get("count") or 0) == 0
            and Decimal(str(report.get("post_positions", {}).get("active_qty", "0"))) == 0
        )
        if report["ok"]:
            report["reason"] = "demo_smoke_submit_ok"
        elif not report.get("reason"):
            report["reason"] = "post_cleanup_not_flat_or_orders_remaining"
    except Exception as e:
        if not report.get("reason"):
            report["reason"] = "exception"
        report["error"] = str(e)
    finally:
        if ws is not None:
            with contextlib.suppress(Exception):
                ws.close()
        if listen_key and api_key:
            report["listen_key_cleanup"] = _cleanup_listen_key(session, rest_base, api_key)

    sanitized_report = _sanitize_obj(report)
    sanitized_raw_records = _sanitize_obj(raw_records)
    _write_json(_resolve_out(root, args.out_json), sanitized_report)
    _write_jsonl(_resolve_out(root, args.out_jsonl), sanitized_raw_records)
    lines = [
        f"testnet_smoke_submit_ok: {sanitized_report.get('ok')}",
        f"reason: {sanitized_report.get('reason')}",
        f"version: {sanitized_report.get('plan_version')}",
        f"symbol: {sanitized_report.get('symbol')}",
        f"side: {sanitized_report.get('side')}",
        f"notional_usdt: {sanitized_report.get('notional_usdt')}",
        f"entry_status: {sanitized_report.get('entry_order', {}).get('status_code')}",
        f"exit_status: {sanitized_report.get('exit_order', {}).get('status_code')}",
        f"private_ws_connected: {sanitized_report.get('private_ws', {}).get('ok')}",
        f"private_ws_messages: {sanitized_report.get('private_ws', {}).get('message_count')}",
        f"private_ws_events: {sanitized_report.get('private_ws', {}).get('event_counts')}",
        f"post_open_orders: {sanitized_report.get('post_open_orders', {}).get('count')}",
        f"post_open_algo_orders: {sanitized_report.get('post_open_algo_orders', {}).get('count')}",
        f"post_active_qty: {sanitized_report.get('post_positions', {}).get('active_qty')}",
    ]
    _resolve_out(root, args.out_txt).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({
        "ok": sanitized_report.get("ok"),
        "reason": sanitized_report.get("reason"),
        "entry_status": sanitized_report.get("entry_order", {}).get("status_code"),
        "exit_status": sanitized_report.get("exit_order", {}).get("status_code"),
        "private_ws_messages": sanitized_report.get("private_ws", {}).get("message_count"),
        "out_json": str(_resolve_out(root, args.out_json)),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
