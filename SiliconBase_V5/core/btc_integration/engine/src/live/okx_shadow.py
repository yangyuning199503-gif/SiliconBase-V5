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
    public_ws_base: str
    private_ws_base: str
    business_ws_base: str


def default_demo_endpoints() -> ShadowEndpoints:
    return ShadowEndpoints(
        rest_base="https://www.okx.com",
        public_ws_base="wss://wspap.okx.com:8443/ws/v5/public",
        private_ws_base="wss://wspap.okx.com:8443/ws/v5/private",
        business_ws_base="wss://wspap.okx.com:8443/ws/v5/business",
    )


def asset_to_contract(asset: str) -> str:
    return f"{str(asset).upper()}-USDT-SWAP"


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


def _build_public_subscriptions(contracts: Iterable[str]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for inst_id in contracts:
        out.append({"channel": "tickers", "instId": inst_id})
    return out


def _build_private_channels(shadow_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    raw = shadow_cfg.get("private_channels", [{"channel": "orders", "instType": "SWAP"}])
    out: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and item.get("channel"):
                out.append(dict(item))
    return out or [{"channel": "orders", "instType": "SWAP"}]


def build_shadow_plan(project_dir: str | Path = ".", interval: str = "15m") -> dict[str, Any]:
    root = Path(project_dir)
    cfg = yaml.safe_load((root / "config.yml").read_text(encoding="utf-8"))
    shadow_cfg = _read_shadow_cfg(root)

    assets = list(cfg.get("data", {}).get("symbols", []))
    contracts_cfg = shadow_cfg.get("contracts", {}) if isinstance(shadow_cfg, dict) else {}
    contract_map: dict[str, str] = {}
    contracts: list[str] = []
    for asset in assets:
        asset_l = str(asset).lower()
        inst_id = str(contracts_cfg.get(asset_l, asset_to_contract(asset_l)))
        contract_map[asset_l] = inst_id
        contracts.append(inst_id)

    eps = default_demo_endpoints()
    eps_cfg = shadow_cfg.get("endpoints", {}) if isinstance(shadow_cfg, dict) else {}
    if isinstance(eps_cfg, dict) and eps_cfg:
        eps = ShadowEndpoints(
            rest_base=str(eps_cfg.get("rest_base", eps.rest_base)),
            public_ws_base=str(eps_cfg.get("public_ws_base", eps.public_ws_base)),
            private_ws_base=str(eps_cfg.get("private_ws_base", eps.private_ws_base)),
            business_ws_base=str(eps_cfg.get("business_ws_base", eps.business_ws_base)),
        )

    auth = shadow_cfg.get("auth", {}) if isinstance(shadow_cfg, dict) else {}
    account = shadow_cfg.get("account", {}) if isinstance(shadow_cfg, dict) else {}
    preview = shadow_cfg.get("order_preview", {}) if isinstance(shadow_cfg, dict) else {}
    exec_cfg = shadow_cfg.get("execution_step", {}) if isinstance(shadow_cfg, dict) else {}
    runner_cfg = shadow_cfg.get("runner", {}) if isinstance(shadow_cfg, dict) else {}
    autopilot_cfg = shadow_cfg.get("autopilot", {}) if isinstance(shadow_cfg, dict) else {}
    public_subs = _build_public_subscriptions(contracts)
    private_channels = _build_private_channels(shadow_cfg if isinstance(shadow_cfg, dict) else {})

    return {
        "version": cfg.get("system", {}).get("version"),
        "strategy": cfg.get("system", {}).get("strategy"),
        "exchange": "okx",
        "demo": bool(shadow_cfg.get("demo", True)),
        "submit_orders": bool(shadow_cfg.get("submit_orders", False)),
        "interval": interval,
        "contracts": contracts,
        "contract_map": contract_map,
        "endpoints": asdict(eps),
        "rest_headers": {"x-simulated-trading": "1"},
        "public_ws_subscriptions": public_subs,
        "private_ws_channels": private_channels,
        "auth": {
            "api_key_env": str(auth.get("api_key_env", "OKX_API_KEY")),
            "api_secret_env": str(auth.get("api_secret_env", "OKX_API_SECRET")),
            "api_passphrase_env": str(auth.get("api_passphrase_env", "OKX_API_PASSPHRASE")),
        },
        "account": {
            "td_mode": str(account.get("td_mode", "cross")),
            "leverage": int(account.get("leverage", 6)),
        },
        "order_preview": {
            "enabled": bool(preview.get("enabled", True)),
            "notional_usdt": float(preview.get("notional_usdt", 20.0)),
            "entry_endpoint": "/api/v5/trade/order",
            "query_endpoint": "/api/v5/trade/order",
            "pending_orders_endpoint": "/api/v5/trade/orders-pending",
            "protective_algo_endpoint": "/api/v5/trade/order-algo",
            "set_leverage_endpoint": "/api/v5/account/set-leverage",
            "max_size_endpoint": "/api/v5/account/max-size",
        },
        "execution_step": {
            "enabled": bool(exec_cfg.get("enabled", True)),
            "bar": str(exec_cfg.get("bar", "15m")),
            "refresh_recent_klines": bool(exec_cfg.get("refresh_recent_klines", True)),
            "max_staleness_minutes": int(exec_cfg.get("max_staleness_minutes", 45)),
            "bootstrap_bars_when_csv_missing": int(exec_cfg.get("bootstrap_bars_when_csv_missing", 5000)),
            "default_notional_usdt": float(exec_cfg.get("default_notional_usdt", preview.get("notional_usdt", 20.0))),
            "notional_usdt_by_symbol": dict(exec_cfg.get("notional_usdt_by_symbol", {})) if isinstance(exec_cfg.get("notional_usdt_by_symbol", {}), dict) else {},
            "clord_prefix": str(exec_cfg.get("clord_prefix", "okxshd")),
            "sizing": {
                "enabled": bool((exec_cfg.get("sizing", {}) or {}).get("enabled", True)) if isinstance(exec_cfg.get("sizing", {}), dict) else True,
                "equity_source": str((exec_cfg.get("sizing", {}) or {}).get("equity_source", "availEq")) if isinstance(exec_cfg.get("sizing", {}), dict) else "availEq",
                "equity_utilization": float((exec_cfg.get("sizing", {}) or {}).get("equity_utilization", 0.85)) if isinstance(exec_cfg.get("sizing", {}), dict) else 0.85,
                "reserve_usdt": float((exec_cfg.get("sizing", {}) or {}).get("reserve_usdt", 0.0)) if isinstance(exec_cfg.get("sizing", {}), dict) else 0.0,
                "capital_slices": int((exec_cfg.get("sizing", {}) or {}).get("capital_slices", 8)) if isinstance(exec_cfg.get("sizing", {}), dict) else 8,
                "min_notional_usdt": float((exec_cfg.get("sizing", {}) or {}).get("min_notional_usdt", 0.0)) if isinstance(exec_cfg.get("sizing", {}), dict) else 0.0,
                "max_notional_usdt": float((exec_cfg.get("sizing", {}) or {}).get("max_notional_usdt", 6000.0)) if isinstance(exec_cfg.get("sizing", {}), dict) else 6000.0,
                "leverage_mode": str((exec_cfg.get("sizing", {}) or {}).get("leverage_mode", "signal_profile")) if isinstance(exec_cfg.get("sizing", {}), dict) else "signal_profile",
                "min_leverage": float((exec_cfg.get("sizing", {}) or {}).get("min_leverage", account.get("leverage", 6))) if isinstance(exec_cfg.get("sizing", {}), dict) else float(account.get("leverage", 6)),
                "max_leverage": float((exec_cfg.get("sizing", {}) or {}).get("max_leverage", account.get("leverage", 6))) if isinstance(exec_cfg.get("sizing", {}), dict) else float(account.get("leverage", 6)),
                "max_active_margin_pct": float((exec_cfg.get("sizing", {}) or {}).get("max_active_margin_pct", 0.45)) if isinstance(exec_cfg.get("sizing", {}), dict) else 0.45,
                "max_symbol_margin_pct": float((exec_cfg.get("sizing", {}) or {}).get("max_symbol_margin_pct", 0.22)) if isinstance(exec_cfg.get("sizing", {}), dict) else 0.22,
                "leverage_by_symbol": dict((exec_cfg.get("sizing", {}) or {}).get("leverage_by_symbol", {})) if isinstance((exec_cfg.get("sizing", {}) or {}).get("leverage_by_symbol", {}), dict) else {},
                "leverage_by_signal": dict((exec_cfg.get("sizing", {}) or {}).get("leverage_by_signal", {})) if isinstance((exec_cfg.get("sizing", {}) or {}).get("leverage_by_signal", {}), dict) else {},
                "symbol_scale": dict((exec_cfg.get("sizing", {}) or {}).get("symbol_scale", {})) if isinstance((exec_cfg.get("sizing", {}) or {}).get("symbol_scale", {}), dict) else {},
                "signal_scale": dict((exec_cfg.get("sizing", {}) or {}).get("signal_scale", {})) if isinstance((exec_cfg.get("sizing", {}) or {}).get("signal_scale", {}), dict) else {},
            },
            "refuse_if_pending_orders": bool(exec_cfg.get("refuse_if_pending_orders", True)),
        },
        "runner": {
            "enabled": bool(runner_cfg.get("enabled", True)),
            "bar": str(runner_cfg.get("bar", exec_cfg.get("bar", "15m"))),
            "grace_seconds": int(runner_cfg.get("grace_seconds", 20)),
            "loop_sleep_seconds": float(runner_cfg.get("loop_sleep_seconds", 2.0)),
            "bundle_every_cycles": int(runner_cfg.get("bundle_every_cycles", 4)),
            "checkin_json": str(runner_cfg.get("checkin_json", "reports/okx_demo_checkin_latest.json")),
            "checkin_txt": str(runner_cfg.get("checkin_txt", "reports/okx_demo_checkin_latest.txt")),
            "checkin_jsonl": str(runner_cfg.get("checkin_jsonl", "reports/okx_demo_checkin_history.jsonl")),
            "status_json": str(runner_cfg.get("status_json", "reports/okx_demo_runner_status_latest.json")),
        },
        "autopilot": {
            "enabled": bool(autopilot_cfg.get("enabled", True)),
            "bar": str(autopilot_cfg.get("bar", exec_cfg.get("bar", "15m"))),
            "grace_seconds": int(autopilot_cfg.get("grace_seconds", 20)),
            "public_report_txt": str(autopilot_cfg.get("public_report_txt", "~/Downloads/okx_demo_report_latest.txt")),
            "pid_file": str(autopilot_cfg.get("pid_file", ".runtime/okx_demo_autopilot.pid")),
        },
        "notes": [
            "OKX demo trading requires x-simulated-trading: 1 on REST requests and uses a separate demo API key with passphrase",
            "private websocket requires login using apiKey + passphrase + HMAC signature over timestamp + GET + /users/self/verify",
            "swap order size sz is contract count, not quote notional; ctVal/ctValCcy + last price are used to convert target notional into contracts",
            "probe stays no-submit; smoke-submit sends one tiny demo market order and then auto-flattens it",
            "shadow execution step re-syncs recent 15m candles from OKX history-candles, recomputes final local strategy state, and mirrors only tiny demo position direction/flat state",
            "autopilot uses one start command and one pause command, wakes after each completed 15m bar, and overwrites a single public report in ~/Downloads/okx_demo_report_latest.txt",
            "CoinGlass news/economic data can auto-trigger a pause_new_entries override before shadow execution; manual file overrides remain optional but are no longer required for normal operation",
            "account mode must be set on OKX web/app before the API can trade swaps; leverage can be set with POST /api/v5/account/set-leverage",
            "execution sizing can now auto-scale with live demo equity using availEq/adjEq/totalEq slices, signal-profile leverage, and margin caps instead of a fixed 20 USDT bridge",
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
        f"- exchange: {plan['exchange']}",
        f"- demo: {plan['demo']}",
        f"- submit_orders: {plan['submit_orders']}",
        f"- contracts: {', '.join(plan['contracts'])}",
        f"- rest base: `{plan['endpoints']['rest_base']}`",
        f"- public ws: `{plan['endpoints']['public_ws_base']}`",
        f"- private ws: `{plan['endpoints']['private_ws_base']}`",
        f"- td_mode: {plan['account']['td_mode']}",
        f"- leverage: {plan['account']['leverage']}",
        f"- preview notional_usdt: {plan['order_preview']['notional_usdt']}",
        f"- execution bar: {plan['execution_step']['bar']}",
        f"- execution default_notional_usdt: {plan['execution_step']['default_notional_usdt']}",
        f"- execution sizing: {plan['execution_step']['sizing']['equity_source']} * {plan['execution_step']['sizing']['equity_utilization']} / slices={plan['execution_step']['sizing']['capital_slices']} (enabled={plan['execution_step']['sizing']['enabled']})",
        f"- execution sizing max_notional_usdt: {plan['execution_step']['sizing']['max_notional_usdt']}"
        ,f"- execution sizing leverage_mode: {plan['execution_step']['sizing']['leverage_mode']} min={plan['execution_step']['sizing']['min_leverage']} max={plan['execution_step']['sizing']['max_leverage']}"
        ,f"- execution sizing margin caps: total={plan['execution_step']['sizing']['max_active_margin_pct']} symbol={plan['execution_step']['sizing']['max_symbol_margin_pct']}",
        f"- runner grace_seconds: {plan['runner']['grace_seconds']}",
        f"- runner bundle_every_cycles: {plan['runner']['bundle_every_cycles']}",
        f"- autopilot report: `{plan['autopilot']['public_report_txt']}`",
        f"- autopilot pid_file: `{plan['autopilot']['pid_file']}`",
        f"- entry endpoint: `{plan['order_preview']['entry_endpoint']}`",
        f"- pending orders endpoint: `{plan['order_preview']['pending_orders_endpoint']}`",
        f"- protective algo endpoint: `{plan['order_preview']['protective_algo_endpoint']}`",
        "",
        "## Public WS subscriptions",
    ]
    for sub in plan['public_ws_subscriptions']:
        lines.append(f"- `{json.dumps(sub, ensure_ascii=False)}`")
    lines.append("")
    lines.append("## Private WS channels")
    for sub in plan['private_ws_channels']:
        lines.append(f"- `{json.dumps(sub, ensure_ascii=False)}`")
    lines.append("")
    lines.append("## Notes")
    lines.extend([f"- {x}" for x in plan['notes']])
    Path(out_md).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return plan
