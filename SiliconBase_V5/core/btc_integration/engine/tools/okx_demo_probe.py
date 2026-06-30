from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import requests

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.live.okx_shadow import build_shadow_plan, write_shadow_plan
from tools.okx_demo_common import (
    Credentials,
    contract_qty_for_notional,
    load_credentials,
    now_utc_text,
    parse_first_row,
    parse_last_price,
    resolve_out,
    rest_request,
    sanitize_obj,
    write_json,
    write_jsonl,
    ws_create,
    ws_login,
    ws_recv_json,
    ws_subscribe,
    ws_wait_for_event,
)


def _okx_code_zero(data: Any) -> bool:
    return isinstance(data, dict) and str(data.get("code", "")) == "0"


def _private_ws_probe(url: str, creds: Credentials, symbol: str) -> dict[str, Any]:
    out: dict[str, Any] = {"url": url, "ok": False}
    ws = None
    try:
        ws, ssl_debug = ws_create(url)
        out.update(ssl_debug)
        login_msgs = ws_login(ws, creds)
        out["login_messages"] = login_msgs
        login_ack = ws_wait_for_event(login_msgs, event="login")
        if not login_ack or str(login_ack.get("code", "")) != "0":
            out["reason"] = "ws_login_failed"
            return out
        sub_args = [{"channel": "orders", "instType": "SWAP", "instId": symbol}]
        sub_msgs = ws_subscribe(ws, sub_args, request_id="probe_orders")
        out["subscribe_messages"] = sub_msgs
        sub_ack = ws_wait_for_event(sub_msgs, event="subscribe", channel="orders")
        out["ok"] = sub_ack is not None
        out["subscribed"] = sub_ack is not None
        out["post_subscribe_messages"] = ws_recv_json(ws, timeout_seconds=2.0, limit=8)
        return out
    except Exception as e:
        out["reason"] = "ws_exception"
        out["error"] = str(e)
        return out
    finally:
        try:
            if ws is not None:
                ws.close()
        except Exception:
            pass


def _public_ws_probe(url: str, symbol: str) -> dict[str, Any]:
    out: dict[str, Any] = {"url": url, "ok": False}
    ws = None
    try:
        ws, ssl_debug = ws_create(url)
        out.update(ssl_debug)
        sub_args = [{"channel": "tickers", "instId": symbol}]
        sub_msgs = ws_subscribe(ws, sub_args, request_id="probe_ticker")
        out["subscribe_messages"] = sub_msgs
        ack = ws_wait_for_event(sub_msgs, event="subscribe", channel="tickers")
        out["subscribed"] = ack is not None
        extra = ws_recv_json(ws, timeout_seconds=2.0, limit=10)
        out["messages"] = extra
        out["ok"] = ack is not None
        return out
    except Exception as e:
        out["reason"] = "ws_exception"
        out["error"] = str(e)
        return out
    finally:
        try:
            if ws is not None:
                ws.close()
        except Exception:
            pass


def main() -> None:
    ap = argparse.ArgumentParser(description="Probe OKX Demo Trading connectivity without placing orders")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--symbol", default="BTC-USDT-SWAP")
    ap.add_argument("--out-json", default="reports/okx_demo_probe_latest.json")
    ap.add_argument("--out-jsonl", default="reports/okx_demo_probe_latest.jsonl")
    ap.add_argument("--out-txt", default="reports/okx_demo_probe_latest.txt")
    args = ap.parse_args()

    root = Path(args.project_dir).resolve()
    write_shadow_plan(project_dir=root, out_json=root / "reports/shadow_mode_plan_latest.json", out_md=root / "reports/shadow_mode_plan_latest.md")
    plan = build_shadow_plan(project_dir=root)

    symbol = str(args.symbol).upper()
    rest_base = str(plan.get("endpoints", {}).get("rest_base", ""))
    public_ws_url = str(plan.get("endpoints", {}).get("public_ws_base", ""))
    private_ws_url = str(plan.get("endpoints", {}).get("private_ws_base", ""))

    report: dict[str, Any] = {
        "ok": False,
        "ts_utc": now_utc_text(),
        "mode": "okx_demo_probe",
        "plan_version": plan.get("version"),
        "exchange": plan.get("exchange"),
        "demo": bool(plan.get("demo")),
        "symbol": symbol,
        "rest_base": rest_base,
        "public_ws_url": public_ws_url,
        "private_ws_url": private_ws_url,
        "notes": [
            "no real order is submitted in this probe",
            "REST uses x-simulated-trading: 1 and private WS uses login + subscribe",
            "order preview converts target USDT notional into swap contract quantity",
        ],
    }
    raw_rows: list[Any] = []

    session = requests.Session()

    st, time_data, meta = rest_request(session, "GET", rest_base, "/api/v5/public/time", demo=True)
    report["public_time"] = {"status_code": st, "meta": meta, "response": time_data, "ok": st == 200 and _okx_code_zero(time_data)}
    raw_rows.append({"step": "public_time", "data": report["public_time"]})

    st, inst_data, meta = rest_request(session, "GET", rest_base, "/api/v5/public/instruments", params={"instType": "SWAP", "instId": symbol}, demo=True)
    if not (st == 200 and _okx_code_zero(inst_data) and parse_first_row(inst_data)):
        st2, inst_data2, meta2 = rest_request(session, "GET", rest_base, "/api/v5/account/instruments", params={"instType": "SWAP", "instId": symbol}, demo=True)
        if st2 == 200 and _okx_code_zero(inst_data2):
            st, inst_data, meta = st2, inst_data2, meta2
    report["instrument"] = {"status_code": st, "meta": meta, "response": inst_data, "ok": st == 200 and _okx_code_zero(inst_data)}
    raw_rows.append({"step": "instrument", "data": report["instrument"]})
    inst_row = parse_first_row(inst_data) or {}

    st, ticker_data, meta = rest_request(session, "GET", rest_base, "/api/v5/market/ticker", params={"instId": symbol}, demo=True)
    report["ticker"] = {"status_code": st, "meta": meta, "response": ticker_data, "ok": st == 200 and _okx_code_zero(ticker_data)}
    raw_rows.append({"step": "ticker", "data": report["ticker"]})
    last_price = parse_last_price(ticker_data)

    report["public_ws"] = _public_ws_probe(public_ws_url, symbol)
    raw_rows.append({"step": "public_ws", "data": report["public_ws"]})

    creds, envs = load_credentials(plan.get("auth", {}), root=root)
    report["auth_envs"] = envs
    report["credentials_present"] = creds is not None

    if creds is not None:
        st, data, meta = rest_request(session, "GET", rest_base, "/api/v5/account/config", creds=creds, signed=True, demo=True)
        report["account_config"] = {"status_code": st, "meta": meta, "response": data, "ok": st == 200 and _okx_code_zero(data)}
        raw_rows.append({"step": "account_config", "data": report["account_config"]})

        st, data, meta = rest_request(session, "GET", rest_base, "/api/v5/account/balance", creds=creds, signed=True, demo=True)
        report["balance"] = {"status_code": st, "meta": meta, "response": data, "ok": st == 200 and _okx_code_zero(data)}
        raw_rows.append({"step": "balance", "data": report["balance"]})

        td_mode = str(plan.get("account", {}).get("td_mode", "cross"))
        st, data, meta = rest_request(session, "GET", rest_base, "/api/v5/account/max-size", params={"instId": symbol, "tdMode": td_mode}, creds=creds, signed=True, demo=True)
        report["max_size"] = {"status_code": st, "meta": meta, "response": data, "ok": st == 200 and _okx_code_zero(data)}
        raw_rows.append({"step": "max_size", "data": report["max_size"]})

        st, data, meta = rest_request(session, "GET", rest_base, "/api/v5/account/leverage-info", params={"instId": symbol, "mgnMode": td_mode}, creds=creds, signed=True, demo=True)
        report["leverage_info"] = {"status_code": st, "meta": meta, "response": data, "ok": st == 200 and _okx_code_zero(data)}
        raw_rows.append({"step": "leverage_info", "data": report["leverage_info"]})

        report["private_ws"] = _private_ws_probe(private_ws_url, creds, symbol)
        raw_rows.append({"step": "private_ws", "data": report["private_ws"]})
    else:
        report["reason"] = "missing_credentials"
        report["how_to_run"] = "可临时 export 三个 OKX 变量，或在项目根目录创建 .okx_demo_env 后重跑 ./.venv/bin/python -m tools.okx_demo_probe --project-dir ."

    if inst_row and last_price is not None:
        preview_target = Decimal(str(plan.get("order_preview", {}).get("notional_usdt", 20.0)))
        sizing = contract_qty_for_notional(inst_row, last_price, preview_target)
        account_cfg_row = parse_first_row(report.get("account_config", {}).get("response")) if isinstance(report.get("account_config"), dict) else None
        pos_mode = str((account_cfg_row or {}).get("posMode", "net_mode"))
        entry_payload: dict[str, Any] = {
            "instId": symbol,
            "tdMode": str(plan.get("account", {}).get("td_mode", "cross")),
            "side": "buy",
            "ordType": "market",
            "sz": sizing["qty"],
        }
        if pos_mode == "long_short_mode":
            entry_payload["posSide"] = "long"
        report["order_preview"] = {
            "last_price": str(last_price),
            "position_mode": pos_mode,
            "entry_payload": entry_payload,
            "sizing": {k: (str(v) if isinstance(v, Decimal) else v) for k, v in sizing.items()},
            "protective_preview": {
                "endpoint": "/api/v5/trade/order-algo",
                "note": "leave protective algo orders in preview only at this stage",
            },
        }
        raw_rows.append({"step": "order_preview", "data": report["order_preview"]})

    public_ok = bool(report.get("public_time", {}).get("ok")) and bool(report.get("ticker", {}).get("ok")) and bool(report.get("instrument", {}).get("ok"))
    private_ok = False
    if creds is not None:
        private_ok = bool(report.get("account_config", {}).get("ok")) and bool(report.get("balance", {}).get("ok")) and bool(report.get("private_ws", {}).get("ok"))
    report["ok"] = public_ok and (private_ok if creds is not None else False)

    sanitized_report = sanitize_obj(report)
    sanitized_rows = [sanitize_obj(r) for r in raw_rows]
    out_json = resolve_out(root, args.out_json)
    out_jsonl = resolve_out(root, args.out_jsonl)
    out_txt = resolve_out(root, args.out_txt)
    write_json(out_json, sanitized_report)
    write_jsonl(out_jsonl, sanitized_rows)
    out_txt.write_text("\n".join([
            f"okx_demo_probe_ok: {sanitized_report['ok']}",
            f"symbol: {symbol}",
            f"public_time_ok: {report.get('public_time', {}).get('ok')}",
            f"instrument_ok: {report.get('instrument', {}).get('ok')}",
            f"ticker_ok: {report.get('ticker', {}).get('ok')}",
            f"public_ws_ok: {report.get('public_ws', {}).get('ok')}",
            f"credentials_present: {report.get('credentials_present')}",
            f"private_ws_ok: {report.get('private_ws', {}).get('ok') if isinstance(report.get('private_ws'), dict) else False}",
            f"out_json: {out_json}",
        ]) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"ok": sanitized_report["ok"], "out_json": str(out_json)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
