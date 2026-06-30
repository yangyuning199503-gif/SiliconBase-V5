from __future__ import annotations

import argparse
import json
import sys
import time
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
    format_decimal,
    load_credentials,
    now_utc_text,
    parse_first_row,
    parse_last_price,
    poll_order,
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


def _row_scode_ok(data: Any) -> bool:
    row = parse_first_row(data)
    return isinstance(row, dict) and str(row.get("sCode", row.get("code", ""))) in {"0", ""}


def _extract_ord_id(data: Any) -> str | None:
    row = parse_first_row(data)
    if not isinstance(row, dict):
        return None
    x = row.get("ordId")
    return str(x) if x is not None and str(x) else None


def _extract_acc_fill_sz(order_row: dict[str, Any], fallback_sz: str) -> str:
    for key in ["accFillSz", "fillSz", "sz"]:
        val = order_row.get(key)
        if val is None:
            continue
        try:
            if Decimal(str(val)) > 0:
                return str(val)
        except Exception:
            continue
    return fallback_sz


def _best_effort_positions_check(session: requests.Session, rest_base: str, creds: Credentials, symbol: str) -> dict[str, Any]:
    st, data, meta = rest_request(session, "GET", rest_base, "/api/v5/account/positions", params={"instType": "SWAP", "instId": symbol}, creds=creds, signed=True, demo=True)
    rows = data.get("data", []) if isinstance(data, dict) else []
    has_position = False
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            for key in ["pos", "availPos"]:
                val = row.get(key)
                if val is None:
                    continue
                try:
                    if abs(Decimal(str(val))) > 0:
                        has_position = True
                        break
                except Exception:
                    continue
            if has_position:
                break
    return {"status_code": st, "meta": meta, "response": data, "ok": st == 200 and _okx_code_zero(data), "has_position": has_position}


def main() -> None:
    ap = argparse.ArgumentParser(description="Submit one tiny OKX Demo SWAP market order, wait for private callbacks, then auto-flatten")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--symbol", default="BTC-USDT-SWAP")
    ap.add_argument("--side", default="buy", choices=["buy", "sell"])
    ap.add_argument("--notional-usdt", type=float, default=20.0)
    ap.add_argument("--entry-wait", type=float, default=4.0)
    ap.add_argument("--exit-wait", type=float, default=4.0)
    ap.add_argument("--out-json", default="reports/okx_demo_smoke_submit_latest.json")
    ap.add_argument("--out-jsonl", default="reports/okx_demo_smoke_submit_latest.jsonl")
    ap.add_argument("--out-txt", default="reports/okx_demo_smoke_submit_latest.txt")
    ap.add_argument("--confirm-demo", action="store_true", help="确认这会在 OKX Demo Trading 上提交一笔真实的模拟单并自动平仓")
    args = ap.parse_args()

    root = Path(args.project_dir).resolve()
    write_shadow_plan(project_dir=root, out_json=root / "reports/shadow_mode_plan_latest.json", out_md=root / "reports/shadow_mode_plan_latest.md")
    plan = build_shadow_plan(project_dir=root)

    symbol = str(args.symbol).upper()
    side = str(args.side).lower()
    rest_base = str(plan.get("endpoints", {}).get("rest_base", ""))
    private_ws_url = str(plan.get("endpoints", {}).get("private_ws_base", ""))

    report: dict[str, Any] = {
        "ok": False,
        "ts_utc": now_utc_text(),
        "mode": "okx_demo_smoke_submit",
        "plan_version": plan.get("version"),
        "exchange": plan.get("exchange"),
        "demo": bool(plan.get("demo")),
        "rest_base": rest_base,
        "private_ws_url": private_ws_url,
        "symbol": symbol,
        "side": side,
        "notional_usdt": float(args.notional_usdt),
        "confirm_demo": bool(args.confirm_demo),
        "notes": [
            "this smoke tool is for OKX Demo Trading only",
            "it submits one tiny market order on a swap instrument, listens to private order updates, then submits the opposite market order to flatten",
            "protective algo orders remain preview-only in this smoke path",
        ],
    }
    raw_rows: list[Any] = []

    out_json = resolve_out(root, args.out_json)
    out_jsonl = resolve_out(root, args.out_jsonl)
    out_txt = resolve_out(root, args.out_txt)

    if not args.confirm_demo:
        report["reason"] = "missing --confirm-demo"
        report["how_to_run"] = "./.venv/bin/python -m tools.okx_demo_smoke_submit --project-dir . --confirm-demo"
        write_json(out_json, sanitize_obj(report))
        write_jsonl(out_jsonl, [])
        out_txt.write_text("okx_demo_smoke_submit_ok: False\nreason: missing --confirm-demo\n", encoding="utf-8")
        print(json.dumps({"ok": False, "reason": report["reason"], "out_json": str(out_json)}, ensure_ascii=False))
        return

    allowed_demo_rest_prefixes = ("https://www.okx.com", "https://eea.okx.com", "https://us.okx.com")
    allowed_demo_ws_hosts = ("wspap.okx.com", "wseeapap.okx.com", "wsuspap.okx.com")
    if not rest_base.startswith(allowed_demo_rest_prefixes) or not any(h in private_ws_url for h in allowed_demo_ws_hosts):
        report["reason"] = "refused_non_okx_demo_endpoint"
        write_json(out_json, sanitize_obj(report))
        write_jsonl(out_jsonl, [])
        out_txt.write_text(f"okx_demo_smoke_submit_ok: False\nreason: {report['reason']}\nrest_base: {rest_base}\nprivate_ws_url: {private_ws_url}\n", encoding="utf-8")
        print(json.dumps({"ok": False, "reason": report["reason"], "out_json": str(out_json)}, ensure_ascii=False))
        return

    creds, envs = load_credentials(plan.get("auth", {}), root=root)
    report["auth_envs"] = envs
    if creds is None:
        report["reason"] = "missing_credentials"
        write_json(out_json, sanitize_obj(report))
        write_jsonl(out_jsonl, [])
        out_txt.write_text("okx_demo_smoke_submit_ok: False\nreason: missing_credentials\n", encoding="utf-8")
        print(json.dumps({"ok": False, "reason": report["reason"], "out_json": str(out_json)}, ensure_ascii=False))
        return

    session = requests.Session()

    st, inst_data, meta = rest_request(session, "GET", rest_base, "/api/v5/public/instruments", params={"instType": "SWAP", "instId": symbol}, demo=True)
    report["instrument"] = {"status_code": st, "meta": meta, "response": inst_data, "ok": st == 200 and _okx_code_zero(inst_data)}
    raw_rows.append({"step": "instrument", "data": report["instrument"]})
    inst_row = parse_first_row(inst_data) or {}
    if not inst_row:
        report["reason"] = "instrument_lookup_failed"
        write_json(out_json, sanitize_obj(report))
        write_jsonl(out_jsonl, [sanitize_obj(r) for r in raw_rows])
        out_txt.write_text("okx_demo_smoke_submit_ok: False\nreason: instrument_lookup_failed\n", encoding="utf-8")
        print(json.dumps({"ok": False, "reason": report["reason"], "out_json": str(out_json)}, ensure_ascii=False))
        return

    st, ticker_data, meta = rest_request(session, "GET", rest_base, "/api/v5/market/ticker", params={"instId": symbol}, demo=True)
    report["ticker"] = {"status_code": st, "meta": meta, "response": ticker_data, "ok": st == 200 and _okx_code_zero(ticker_data)}
    raw_rows.append({"step": "ticker", "data": report["ticker"]})
    last_price = parse_last_price(ticker_data)
    if last_price is None:
        report["reason"] = "ticker_failed"
        write_json(out_json, sanitize_obj(report))
        write_jsonl(out_jsonl, [sanitize_obj(r) for r in raw_rows])
        out_txt.write_text("okx_demo_smoke_submit_ok: False\nreason: ticker_failed\n", encoding="utf-8")
        print(json.dumps({"ok": False, "reason": report["reason"], "out_json": str(out_json)}, ensure_ascii=False))
        return

    st, data, meta = rest_request(session, "GET", rest_base, "/api/v5/account/config", creds=creds, signed=True, demo=True)
    report["account_config"] = {"status_code": st, "meta": meta, "response": data, "ok": st == 200 and _okx_code_zero(data)}
    raw_rows.append({"step": "account_config", "data": report["account_config"]})
    account_cfg = parse_first_row(data) or {}
    pos_mode = str(account_cfg.get("posMode", "net_mode"))
    report["position_mode"] = pos_mode

    st, data, meta = rest_request(session, "GET", rest_base, "/api/v5/trade/orders-pending", params={"instType": "SWAP", "instId": symbol}, creds=creds, signed=True, demo=True)
    report["orders_pending"] = {"status_code": st, "meta": meta, "response": data, "ok": st == 200 and _okx_code_zero(data), "pending_count": len(data.get("data", [])) if isinstance(data, dict) and isinstance(data.get("data"), list) else None}
    raw_rows.append({"step": "orders_pending", "data": report["orders_pending"]})
    if isinstance(data, dict) and isinstance(data.get("data"), list) and data.get("data"):
        report["reason"] = "existing_pending_orders"
        write_json(out_json, sanitize_obj(report))
        write_jsonl(out_jsonl, [sanitize_obj(r) for r in raw_rows])
        out_txt.write_text("okx_demo_smoke_submit_ok: False\nreason: existing_pending_orders\n", encoding="utf-8")
        print(json.dumps({"ok": False, "reason": report["reason"], "out_json": str(out_json)}, ensure_ascii=False))
        return

    positions_check = _best_effort_positions_check(session, rest_base, creds, symbol)
    report["positions_check"] = positions_check
    raw_rows.append({"step": "positions_check", "data": positions_check})
    if positions_check.get("has_position"):
        report["reason"] = "existing_open_position"
        write_json(out_json, sanitize_obj(report))
        write_jsonl(out_jsonl, [sanitize_obj(r) for r in raw_rows])
        out_txt.write_text("okx_demo_smoke_submit_ok: False\nreason: existing_open_position\n", encoding="utf-8")
        print(json.dumps({"ok": False, "reason": report["reason"], "out_json": str(out_json)}, ensure_ascii=False))
        return
    if not positions_check.get("ok"):
        report.setdefault("warnings", []).append("positions_check_not_confirmed; proceeding with best effort")

    td_mode = str(plan.get("account", {}).get("td_mode", "cross"))
    leverage = str(plan.get("account", {}).get("leverage", 5))
    st, data, meta = rest_request(session, "POST", rest_base, "/api/v5/account/set-leverage", body={"instId": symbol, "lever": leverage, "mgnMode": td_mode}, creds=creds, signed=True, demo=True)
    report["set_leverage"] = {"status_code": st, "meta": meta, "response": data, "ok": st == 200 and _okx_code_zero(data)}
    raw_rows.append({"step": "set_leverage", "data": report["set_leverage"]})
    if not report["set_leverage"]["ok"]:
        report["reason"] = "set_leverage_failed"
        write_json(out_json, sanitize_obj(report))
        write_jsonl(out_jsonl, [sanitize_obj(r) for r in raw_rows])
        out_txt.write_text("okx_demo_smoke_submit_ok: False\nreason: set_leverage_failed\n", encoding="utf-8")
        print(json.dumps({"ok": False, "reason": report["reason"], "out_json": str(out_json)}, ensure_ascii=False))
        return

    sizing = contract_qty_for_notional(inst_row, last_price, Decimal(str(args.notional_usdt)))
    report["sizing"] = {k: (str(v) if isinstance(v, Decimal) else v) for k, v in sizing.items()}
    raw_rows.append({"step": "sizing", "data": report["sizing"]})

    entry_payload: dict[str, Any] = {
        "instId": symbol,
        "tdMode": td_mode,
        "side": side,
        "ordType": "market",
        "sz": str(sizing["qty"]),
        "clOrdId": f"okxsmoke{int(time.time())}",
    }
    if pos_mode == "long_short_mode":
        entry_payload["posSide"] = "long" if side == "buy" else "short"
    else:
        entry_payload["reduceOnly"] = False
    report["entry_preview"] = entry_payload

    ws = None
    ws_messages: list[Any] = []
    try:
        ws, ssl_debug = ws_create(private_ws_url)
        report["private_ws_ssl"] = ssl_debug
        login_msgs = ws_login(ws, creds)
        report["private_ws_login"] = login_msgs
        ws_messages.extend(login_msgs)
        login_ack = ws_wait_for_event(login_msgs, event="login")
        if not login_ack or str(login_ack.get("code", "")) != "0":
            report["reason"] = "private_ws_login_failed"
            write_json(out_json, sanitize_obj(report))
            write_jsonl(out_jsonl, [sanitize_obj(m) for m in ws_messages])
            out_txt.write_text("okx_demo_smoke_submit_ok: False\nreason: private_ws_login_failed\n", encoding="utf-8")
            print(json.dumps({"ok": False, "reason": report["reason"], "out_json": str(out_json)}, ensure_ascii=False))
            return
        sub_msgs = ws_subscribe(ws, [{"channel": "orders", "instType": "SWAP", "instId": symbol}], request_id="smoke_orders")
        report["private_ws_subscribe"] = sub_msgs
        ws_messages.extend(sub_msgs)
    except Exception as e:
        report["reason"] = "private_ws_setup_failed"
        report["error"] = str(e)
        write_json(out_json, sanitize_obj(report))
        write_jsonl(out_jsonl, [sanitize_obj(m) for m in ws_messages])
        out_txt.write_text("okx_demo_smoke_submit_ok: False\nreason: private_ws_setup_failed\n", encoding="utf-8")
        print(json.dumps({"ok": False, "reason": report["reason"], "out_json": str(out_json)}, ensure_ascii=False))
        return

    st, data, meta = rest_request(session, "POST", rest_base, "/api/v5/trade/order", body=entry_payload, creds=creds, signed=True, demo=True)
    report["entry_submit"] = {"status_code": st, "meta": meta, "response": data, "ok": st == 200 and _okx_code_zero(data) and _row_scode_ok(data)}
    raw_rows.append({"step": "entry_submit", "data": report["entry_submit"]})
    entry_ord_id = _extract_ord_id(data)
    if not report["entry_submit"]["ok"] or not entry_ord_id:
        report["reason"] = "entry_submit_failed"
        write_json(out_json, sanitize_obj(report))
        write_jsonl(out_jsonl, [sanitize_obj(m) for m in ws_messages] + [sanitize_obj(r) for r in raw_rows])
        out_txt.write_text("okx_demo_smoke_submit_ok: False\nreason: entry_submit_failed\n", encoding="utf-8")
        print(json.dumps({"ok": False, "reason": report["reason"], "out_json": str(out_json)}, ensure_ascii=False))
        return

    ws_messages.extend(ws_recv_json(ws, timeout_seconds=max(1.0, args.entry_wait), limit=30))
    entry_poll = poll_order(session, rest_base, creds, symbol, entry_ord_id, timeout_seconds=max(2.0, args.entry_wait))
    report["entry_order"] = entry_poll
    raw_rows.append({"step": "entry_order", "data": entry_poll})
    entry_row = entry_poll.get("row") if isinstance(entry_poll, dict) else None
    if not isinstance(entry_row, dict):
        report["reason"] = "entry_poll_failed"
        write_json(out_json, sanitize_obj(report))
        write_jsonl(out_jsonl, [sanitize_obj(m) for m in ws_messages] + [sanitize_obj(r) for r in raw_rows])
        out_txt.write_text("okx_demo_smoke_submit_ok: False\nreason: entry_poll_failed\n", encoding="utf-8")
        print(json.dumps({"ok": False, "reason": report["reason"], "out_json": str(out_json)}, ensure_ascii=False))
        return

    filled_sz = _extract_acc_fill_sz(entry_row, entry_payload["sz"])
    try:
        filled_sz_dec = Decimal(str(filled_sz))
    except Exception:
        filled_sz_dec = Decimal("0")
    if filled_sz_dec <= 0:
        report["reason"] = "entry_not_filled"
        write_json(out_json, sanitize_obj(report))
        write_jsonl(out_jsonl, [sanitize_obj(m) for m in ws_messages] + [sanitize_obj(r) for r in raw_rows])
        out_txt.write_text("okx_demo_smoke_submit_ok: False\nreason: entry_not_filled\n", encoding="utf-8")
        print(json.dumps({"ok": False, "reason": report["reason"], "out_json": str(out_json)}, ensure_ascii=False))
        return

    close_side = "sell" if side == "buy" else "buy"
    close_payload: dict[str, Any] = {
        "instId": symbol,
        "tdMode": td_mode,
        "side": close_side,
        "ordType": "market",
        "sz": format_decimal(filled_sz_dec),
        "clOrdId": f"okxflat{int(time.time())}",
    }
    if pos_mode == "long_short_mode":
        close_payload["posSide"] = "long" if side == "buy" else "short"
    else:
        close_payload["reduceOnly"] = True
    report["close_preview"] = close_payload

    st, data, meta = rest_request(session, "POST", rest_base, "/api/v5/trade/order", body=close_payload, creds=creds, signed=True, demo=True)
    report["close_submit"] = {"status_code": st, "meta": meta, "response": data, "ok": st == 200 and _okx_code_zero(data) and _row_scode_ok(data)}
    raw_rows.append({"step": "close_submit", "data": report["close_submit"]})
    close_ord_id = _extract_ord_id(data)
    if not report["close_submit"]["ok"] or not close_ord_id:
        report["reason"] = "close_submit_failed"
        write_json(out_json, sanitize_obj(report))
        write_jsonl(out_jsonl, [sanitize_obj(m) for m in ws_messages] + [sanitize_obj(r) for r in raw_rows])
        out_txt.write_text("okx_demo_smoke_submit_ok: False\nreason: close_submit_failed\n", encoding="utf-8")
        print(json.dumps({"ok": False, "reason": report["reason"], "out_json": str(out_json)}, ensure_ascii=False))
        return

    ws_messages.extend(ws_recv_json(ws, timeout_seconds=max(1.0, args.exit_wait), limit=30))
    close_poll = poll_order(session, rest_base, creds, symbol, close_ord_id, timeout_seconds=max(2.0, args.exit_wait))
    report["close_order"] = close_poll
    raw_rows.append({"step": "close_order", "data": close_poll})

    close_row = close_poll.get("row") if isinstance(close_poll, dict) else None
    close_state = str((close_row or {}).get("state", "")).lower() if isinstance(close_row, dict) else ""
    report["private_ws_messages"] = ws_messages
    report["ok"] = close_state in {"filled", "canceled", "partially_filled"} or bool(close_row)

    sanitized_report = sanitize_obj(report)
    sanitized_rows = [sanitize_obj(m) for m in ws_messages] + [sanitize_obj(r) for r in raw_rows]
    write_json(out_json, sanitized_report)
    write_jsonl(out_jsonl, sanitized_rows)
    out_txt.write_text("\n".join([
            f"okx_demo_smoke_submit_ok: {sanitized_report['ok']}",
            f"symbol: {symbol}",
            f"entry_ord_id: {entry_ord_id}",
            f"close_ord_id: {close_ord_id}",
            f"out_json: {out_json}",
        ]) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"ok": sanitized_report["ok"], "out_json": str(out_json)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
