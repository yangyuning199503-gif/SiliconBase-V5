from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ShadowEndpoints:
    rest_base: str
    market_ws_base: str
    market_ws_fallback_base: str
    private_ws_base: str
    private_ws_fallback_base: str
    trade_ws_base: str


def default_testnet_endpoints() -> ShadowEndpoints:
    return ShadowEndpoints(
        rest_base="https://demo-fapi.binance.com",
        market_ws_base="wss://fstream.binancefuture.com/market/stream?streams=",
        market_ws_fallback_base="wss://fstream.binancefuture.com/stream?streams=",
        private_ws_base="wss://fstream.binancefuture.com/private/ws?listenKey=",
        private_ws_fallback_base="wss://fstream.binancefuture.com/ws/",
        trade_ws_base="wss://testnet.binancefuture.com/ws-fapi/v1",
    )


def asset_to_contract(asset: str) -> str:
    return f"{str(asset).upper()}USDT"


def build_market_streams(contracts: Iterable[str], interval: str = "15m") -> list[str]:
    out: list[str] = []
    for s in contracts:
        ss = s.lower()
        out.append(f"{ss}@kline_{interval}")
        out.append(f"{ss}@markPrice@1s")
    return out


def _read_shadow_cfg(root: Path) -> dict[str, Any]:
    p = root / "shadow.yml"
    if p.exists():
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            if isinstance(data, dict):
                return data.get("shadow", data) or {}
        except Exception:
            pass
    return {}


def build_shadow_plan(project_dir: str | Path = ".", testnet: bool = True, interval: str = "15m") -> dict[str, Any]:
    root = Path(project_dir)
    cfg = yaml.safe_load((root / "config.yml").read_text(encoding="utf-8"))
    shadow_cfg = _read_shadow_cfg(root)
    assets = list(cfg.get("data", {}).get("symbols", []))
    contracts = [asset_to_contract(a) for a in assets]
    eps = default_testnet_endpoints()
    eps_cfg = shadow_cfg.get("endpoints", {}) if isinstance(shadow_cfg, dict) else {}
    if isinstance(eps_cfg, dict) and eps_cfg:
        eps = ShadowEndpoints(
            rest_base=str(eps_cfg.get("rest_base", eps.rest_base)),
            market_ws_base=str(eps_cfg.get("market_ws_base", eps.market_ws_base)),
            market_ws_fallback_base=str(eps_cfg.get("market_ws_fallback_base", eps.market_ws_fallback_base)),
            private_ws_base=str(eps_cfg.get("private_ws_base", eps.private_ws_base)),
            private_ws_fallback_base=str(eps_cfg.get("private_ws_fallback_base", eps.private_ws_fallback_base)),
            trade_ws_base=str(eps_cfg.get("trade_ws_base", eps.trade_ws_base)),
        )
    streams = build_market_streams(contracts, interval=interval)
    private_events = shadow_cfg.get("private_events", ["ORDER_TRADE_UPDATE", "ACCOUNT_UPDATE", "ALGO_UPDATE"])
    if isinstance(private_events, str):
        private_events = [x.strip() for x in private_events.split(",") if x.strip()]
    auth = shadow_cfg.get("auth", {}) if isinstance(shadow_cfg, dict) else {}
    order_test_cfg = shadow_cfg.get("order_test", {}) if isinstance(shadow_cfg, dict) else {}
    market_stream_url = eps.market_ws_base + "/".join(streams)
    market_stream_url_fallback = eps.market_ws_fallback_base + "/".join(streams)
    private_probe_mode = str(shadow_cfg.get("private_probe_mode", "listenKey")).strip() or "listenKey"
    return {
        "version": cfg.get("system", {}).get("version"),
        "strategy": cfg.get("system", {}).get("strategy"),
        "testnet": bool(testnet),
        "contracts": contracts,
        "interval": interval,
        "endpoints": asdict(eps),
        "market_streams": streams,
        "market_stream_url": market_stream_url,
        "market_stream_url_fallback": market_stream_url_fallback,
        "listen_key_rest": eps.rest_base + "/fapi/v1/listenKey",
        "private_events": private_events,
        "private_ws_probe_mode": private_probe_mode,
        "private_ws_url_template": eps.private_ws_base + "<listenKey>&events=" + "/".join(private_events),
        "private_ws_url_fallback_template": eps.private_ws_fallback_base + "<listenKey>",
        "private_ws_api_auth_method": "session.logon (Ed25519-only, optional)",
        "submit_orders": bool(shadow_cfg.get("submit_orders", False)),
        "auth": {
            "api_key_env": str(auth.get("api_key_env", "BINANCE_API_KEY")),
            "api_secret_env": str(auth.get("api_secret_env", "BINANCE_API_SECRET")),
        },
        "order_test": {
            "enabled": bool(order_test_cfg.get("enabled", True)),
            "entry_endpoint": "/fapi/v1/order/test",
            "notional_usdt": float(order_test_cfg.get("notional_usdt", 10.0)),
        },
        "order_preview": {
            "entry_type": "MARKET",
            "entry_validation_endpoint": "/fapi/v1/order/test",
            "protective_exit_submit_endpoint": "/fapi/v1/algoOrder",
            "protective_exits": ["STOP_MARKET", "TRAILING_STOP_MARKET"],
            "working_type": "MARK_PRICE",
            "price_protect": True,
            "reduce_only_exits": True,
        },
        "notes": [
            "shadow mode only computes signal/order preview; it does not submit testnet orders",
            "market websocket uses the testnet base and prefers /market route, falling back to legacy /stream during migration window",
            "private websocket probe defaults to listenKey over /private so regular HMAC testnet keys work without WebSocket API auth",
            "WebSocket API session.logon remains optional for future Ed25519-based trading flows",
            "entry orders can be validated with POST /fapi/v1/order/test",
            "STOP_MARKET / TRAILING_STOP_MARKET are now conditional algo orders; real submission path is POST /fapi/v1/algoOrder",
            "order.test probe rounds quantity up to valid lot steps and retries with a buffered minimum notional when the exchange enforces a higher floor than exchangeInfo reveals",
            "probe diagnostics redact signatures and listenKeys before writing support bundles",
            "websocket-client should use a CA bundle for TLS verification; BINANCE_WS_SSL_CA_BUNDLE can override the path if local trust store is broken",
        ],
    }


def write_shadow_plan(project_dir: str | Path = ".", out_json: str | Path = "reports/shadow_mode_plan_latest.json", out_md: str | Path = "reports/shadow_mode_plan_latest.md") -> dict[str, Any]:
    plan = build_shadow_plan(project_dir=project_dir)
    out_json = Path(out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        f"# Shadow Mode Plan ({plan['version']})",
        "",
        f"- testnet: {plan['testnet']}",
        f"- contracts: {', '.join(plan['contracts'])}",
        f"- market stream url: `{plan['market_stream_url']}`",
        f"- market stream fallback: `{plan['market_stream_url_fallback']}`",
        f"- listen key REST: `{plan['listen_key_rest']}`",
        f"- private ws probe mode: {plan['private_ws_probe_mode']}",
        f"- private ws template: `{plan['private_ws_url_template']}`",
        f"- private ws fallback: `{plan['private_ws_url_fallback_template']}`",
        f"- private ws api base (optional): `{plan['endpoints']['trade_ws_base']}` ({plan['private_ws_api_auth_method']})",
        f"- entry validation endpoint: `{plan['order_preview']['entry_validation_endpoint']}`",
        f"- protective submit endpoint: `{plan['order_preview']['protective_exit_submit_endpoint']}`",
        f"- entry order type: {plan['order_preview']['entry_type']}",
        f"- protective exits: {', '.join(plan['order_preview']['protective_exits'])}",
        f"- working type: {plan['order_preview']['working_type']}",
        f"- price protect: {plan['order_preview']['price_protect']}",
        f"- reduce only exits: {plan['order_preview']['reduce_only_exits']}",
        "",
        "## Notes",
    ]
    lines.extend([f"- {x}" for x in plan["notes"]])
    Path(out_md).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return plan
