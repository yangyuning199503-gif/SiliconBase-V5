from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import ssl
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

try:
    import websocket
except ImportError:
    websocket = None


@dataclass
class Credentials:
    api_key: str
    api_secret: str
    api_passphrase: str


def now_iso_ms() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def now_utc_text() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def now_epoch_s_str() -> str:
    return str(int(time.time()))


def truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "y", "on"}


def ws_sslopt(prefix: str = "OKX") -> dict[str, Any]:
    ca_bundle = os.environ.get(f"{prefix}_WS_SSL_CA_BUNDLE") or requests.certs.where()
    insecure = truthy_env(f"{prefix}_WS_INSECURE")
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


def sign_rest(ts: str, method: str, request_path: str, body: str, secret: str) -> str:
    raw = f"{ts}{method.upper()}{request_path}{body}"
    digest = hmac.new(secret.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def sign_ws_login(ts_seconds: str, secret: str) -> str:
    raw = f"{ts_seconds}GET/users/self/verify"
    digest = hmac.new(secret.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def _request_path(path: str, params: dict[str, Any] | None = None) -> str:
    if not params:
        return path
    q = urlencode([(k, v) for k, v in params.items() if v is not None], doseq=True)
    return f"{path}?{q}" if q else path


def rest_request(
    session: requests.Session,
    method: str,
    base_url: str,
    path: str,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    creds: Credentials | None = None,
    signed: bool = False,
    demo: bool = True,
    timeout: int = 20,
) -> tuple[int, Any, dict[str, Any]]:
    method = method.upper()
    params = dict(params or {})
    body_obj = dict(body or {})
    request_path = _request_path(path, params if method == "GET" else None)
    url = base_url.rstrip("/") + request_path
    body_text = json.dumps(body_obj, ensure_ascii=False, separators=(",", ":")) if method != "GET" and body_obj else ""
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if demo:
        headers["x-simulated-trading"] = "1"
    if signed:
        if not creds:
            raise RuntimeError("signed request requires credentials")
        ts = now_iso_ms()
        headers.update({
            "OK-ACCESS-KEY": creds.api_key,
            "OK-ACCESS-SIGN": sign_rest(ts, method, request_path, body_text, creds.api_secret),
            "OK-ACCESS-TIMESTAMP": ts,
            "OK-ACCESS-PASSPHRASE": creds.api_passphrase,
        })
    try:
        if method == "GET":
            resp = session.get(url, headers=headers, timeout=timeout)
        elif method == "POST":
            resp = session.post(url, headers=headers, data=body_text or "{}", timeout=timeout)
        elif method == "DELETE":
            resp = session.delete(url, headers=headers, data=body_text or "{}", timeout=timeout)
        else:
            raise ValueError(f"unsupported method: {method}")
    except requests.RequestException as exc:
        meta = {
            "url": url,
            "request_path": request_path,
            "status_code": 0,
            "error": str(exc),
        }
        data = {"code": "network_error", "msg": str(exc), "data": []}
        return 0, data, meta

    content_type = resp.headers.get("content-type", "")
    try:
        data = resp.json() if "json" in content_type or resp.text[:1] in "[{" else resp.text
    except Exception:
        data = resp.text
    meta = {
        "url": resp.url,
        "request_path": request_path,
        "status_code": resp.status_code,
    }
    return resp.status_code, data, meta


def _parse_env_file(path: Path) -> dict[str, str]:
    loaded: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return loaded
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        key = k.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        val = v.strip()
        if len(val) >= 2 and ((val[0] == val[-1] == '"') or (val[0] == val[-1] == "'")):
            val = val[1:-1]
        loaded[key] = val
    return loaded


def _candidate_env_files(root: str | Path | None = None) -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()

    def _push(p: Path) -> None:
        rp = str(p.expanduser().resolve()) if p.exists() else str(p.expanduser())
        if rp not in seen:
            seen.add(rp)
            out.append(p.expanduser())

    if root is not None:
        root_p = Path(root).expanduser().resolve()
        _push(root_p / ".okx_demo_env")
        _push(root_p / ".okx_demo_env.sh")
    cwd = Path.cwd()
    _push(cwd / ".okx_demo_env")
    _push(cwd / ".okx_demo_env.sh")
    _push(Path.home() / ".okx_demo_env")
    _push(Path.home() / ".btc_system_v1_okx_demo_env")
    return out




def ensure_env_loaded(root: str | Path | None = None) -> dict[str, Any]:
    checked = [str(p) for p in _candidate_env_files(root)]
    loaded_from: list[str] = []
    for p in _candidate_env_files(root):
        if not p.exists() or not p.is_file():
            continue
        loaded = _parse_env_file(p)
        if not loaded:
            continue
        for k, v in loaded.items():
            os.environ.setdefault(k, v)
        loaded_from.append(str(p))
    return {
        "env_files_checked": checked,
        "env_files_loaded": loaded_from,
    }

def load_credentials(auth_cfg: dict[str, Any], root: str | Path | None = None) -> tuple[Credentials | None, dict[str, Any]]:
    envs: dict[str, Any] = {
        "api_key_env": str(auth_cfg.get("api_key_env", "OKX_API_KEY")),
        "api_secret_env": str(auth_cfg.get("api_secret_env", "OKX_API_SECRET")),
        "api_passphrase_env": str(auth_cfg.get("api_passphrase_env", "OKX_API_PASSPHRASE")),
    }

    def _read() -> tuple[str, str, str]:
        return (
            os.environ.get(str(envs["api_key_env"]), ""),
            os.environ.get(str(envs["api_secret_env"]), ""),
            os.environ.get(str(envs["api_passphrase_env"]), ""),
        )

    api_key, api_secret, api_passphrase = _read()
    loaded_from: list[str] = []
    checked = [str(p) for p in _candidate_env_files(root)]
    if not (api_key and api_secret and api_passphrase):
        for p in _candidate_env_files(root):
            if not p.exists() or not p.is_file():
                continue
            loaded = _parse_env_file(p)
            if not loaded:
                continue
            for k, v in loaded.items():
                os.environ.setdefault(k, v)
            loaded_from.append(str(p))
            api_key, api_secret, api_passphrase = _read()
            if api_key and api_secret and api_passphrase:
                break

    envs["env_files_checked"] = checked
    envs["env_files_loaded"] = loaded_from
    if api_key and api_secret and api_passphrase:
        source = "environment" if not loaded_from else f"env_file:{loaded_from[-1]}"
        envs["credential_source"] = source
        return Credentials(api_key=api_key, api_secret=api_secret, api_passphrase=api_passphrase), envs
    envs["credential_source"] = "missing"
    return None, envs


def sanitize_obj(obj: Any) -> Any:
    def _walk(x: Any) -> Any:
        x = _json_safe_scalar(x)
        if isinstance(x, dict):
            out = {}
            for k, v in x.items():
                kl = str(k).lower()
                if any(tok in kl for tok in ["secret", "signature", "passphrase", "api_key", "ok-access-sign", "ok-access-key"]):
                    out[k] = "***REDACTED***"
                else:
                    out[k] = _walk(v)
            return out
        if isinstance(x, (list, tuple, set)):
            return [_walk(i) for i in x]
        if isinstance(x, str):
            y = re.sub(r"([A-Za-z0-9_\-]{8,})", lambda m: m.group(0), x)
            return y
        return x
    return _walk(obj)


def resolve_out(root: Path, out_path: str | Path) -> Path:
    p = Path(out_path)
    if not p.is_absolute():
        p = root / p
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _json_safe_scalar(x: Any) -> Any:
    if isinstance(x, Decimal):
        return format_decimal(x)
    if isinstance(x, Path):
        return str(x)
    if isinstance(x, bytes):
        return x.decode("utf-8", errors="replace")
    if isinstance(x, (datetime,)):
        return x.isoformat()
    iso = getattr(x, "isoformat", None)
    if callable(iso):
        try:
            return iso()
        except Exception:
            pass
    item = getattr(x, "item", None)
    if callable(item):
        try:
            return _json_safe_scalar(item())
        except Exception:
            pass
    return x


def _json_safe_obj(x: Any) -> Any:
    x = _json_safe_scalar(x)
    if isinstance(x, dict):
        return {k: _json_safe_obj(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, set)):
        return [_json_safe_obj(i) for i in x]
    return x


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_safe_obj(obj), ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(_json_safe_obj(row), ensure_ascii=False) + "\n")


def decimal_places_from_str(val: str) -> int:
    s = str(val).strip()
    if "." not in s:
        return 0
    return len(s.split(".", 1)[1].rstrip("0"))


def format_decimal(d: Decimal, step: str | Decimal | None = None) -> str:
    places = max(0, -d.normalize().as_tuple().exponent) if step is None else decimal_places_from_str(str(step))
    q = f"{d:.{places}f}" if places > 0 else str(int(d))
    if "." in q:
        q = q.rstrip("0").rstrip(".")
    return q or "0"


def round_up_step(raw: Decimal, step: Decimal, minimum: Decimal) -> Decimal:
    step = step if step > 0 else Decimal("1")
    minimum = minimum if minimum > 0 else step
    q = raw if raw > minimum else minimum
    n = (q / step).to_integral_value(rounding=ROUND_CEILING)
    out = n * step
    if out < minimum:
        out = minimum
    return out


def parse_first_row(data: Any) -> dict[str, Any] | None:
    if isinstance(data, dict):
        rows = data.get("data")
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            return rows[0]
    return None


def parse_last_price(ticker_data: Any) -> Decimal | None:
    row = parse_first_row(ticker_data)
    if not row:
        return None
    try:
        return Decimal(str(row.get("last")))
    except Exception:
        return None


def contract_qty_for_notional(inst: dict[str, Any], last_price: Decimal, target_notional_usdt: Decimal) -> dict[str, Any]:
    inst_id = str(inst.get("instId", ""))
    parts = inst_id.split("-")
    base_ccy = parts[0] if len(parts) >= 1 else ""
    quote_ccy = parts[1] if len(parts) >= 2 else ""
    ct_val = Decimal(str(inst.get("ctVal") or "0"))
    ct_val_ccy = str(inst.get("ctValCcy") or "").upper()
    lot_sz = Decimal(str(inst.get("lotSz") or inst.get("minSz") or "1"))
    min_sz = Decimal(str(inst.get("minSz") or lot_sz or "1"))
    if ct_val <= 0:
        raw_contracts = min_sz
        formula = "fallback_minSz"
        est_contract_notional = Decimal("0")
    elif ct_val_ccy == base_ccy.upper():
        est_contract_notional = last_price * ct_val
        raw_contracts = target_notional_usdt / max(est_contract_notional, Decimal("1e-18"))
        formula = "contracts = target_notional / (last_price * ctVal)"
    elif ct_val_ccy in {quote_ccy.upper(), str(inst.get("settleCcy", "")).upper()}:
        est_contract_notional = ct_val
        raw_contracts = target_notional_usdt / max(est_contract_notional, Decimal("1e-18"))
        formula = "contracts = target_notional / ctVal"
    else:
        est_contract_notional = last_price * ct_val
        raw_contracts = target_notional_usdt / max(est_contract_notional, Decimal("1e-18"))
        formula = "fallback_assume_base_contract_value"
    min_notional_est = est_contract_notional * min_sz if est_contract_notional > 0 else Decimal("0")
    eff_target = target_notional_usdt
    if min_notional_est > eff_target:
        eff_target = min_notional_est * Decimal("1.01")
        if est_contract_notional > 0:
            raw_contracts = eff_target / est_contract_notional
    qty = round_up_step(raw_contracts, lot_sz, min_sz)
    return {
        "qty_decimal": qty,
        "qty": format_decimal(qty, lot_sz),
        "formula": formula,
        "ctVal": format_decimal(ct_val) if ct_val > 0 else "0",
        "ctValCcy": ct_val_ccy,
        "lotSz": format_decimal(lot_sz, lot_sz),
        "minSz": format_decimal(min_sz, lot_sz),
        "estimated_contract_notional_usdt": format_decimal(est_contract_notional),
        "effective_target_notional_usdt": format_decimal(eff_target),
        "raw_contracts": format_decimal(raw_contracts),
    }


def ws_create(url: str, timeout: float = 8.0):
    if websocket is None:
        raise RuntimeError("websocket 模块未安装，请运行: pip install websocket-client")
    sslopt = ws_sslopt()
    ssl_debug = {"ssl_verify_mode": sslopt.get("verify_mode"), "ca_bundle": sslopt.get("ca_bundle")}
    connect_sslopt = {k: v for k, v in sslopt.items() if k not in {"verify_mode", "ca_bundle"}}
    ws = websocket.create_connection(url, timeout=timeout, sslopt=connect_sslopt)
    ws.settimeout(1.5)
    return ws, ssl_debug


def ws_recv_json(ws, timeout_seconds: float = 5.0, limit: int = 50) -> list[Any]:
    deadline = time.time() + timeout_seconds
    out: list[Any] = []
    timeout_exc = websocket.WebSocketTimeoutException if websocket else Exception
    while time.time() < deadline and len(out) < limit:
        try:
            msg = ws.recv()
        except timeout_exc:
            continue
        except Exception as e:
            out.append({"type": "recv_error", "error": str(e)})
            break
        try:
            out.append(json.loads(msg))
        except Exception:
            out.append({"raw": str(msg)[:2000]})
    return out


def ws_wait_for_event(messages: list[Any], *, event: str | None = None, channel: str | None = None) -> dict[str, Any] | None:
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        if event is not None and str(msg.get("event", "")) != event:
            continue
        if channel is not None:
            arg = msg.get("arg") if isinstance(msg.get("arg"), dict) else {}
            if str(arg.get("channel", "")) != channel and str(msg.get("channel", "")) != channel:
                continue
        return msg
    return None


def ws_login(ws, creds: Credentials) -> list[Any]:
    ts = now_epoch_s_str()
    payload = {
        "op": "login",
        "args": [{
            "apiKey": creds.api_key,
            "passphrase": creds.api_passphrase,
            "timestamp": ts,
            "sign": sign_ws_login(ts, creds.api_secret),
        }],
    }
    ws.send(json.dumps(payload, ensure_ascii=False))
    return ws_recv_json(ws, timeout_seconds=4.0, limit=10)


def _sanitize_ws_request_id(request_id: str | None) -> str | None:
    if request_id is None:
        return None
    rid = re.sub(r"[^A-Za-z0-9]", "", str(request_id))[:32]
    return rid or None


def ws_subscribe(ws, args: list[dict[str, Any]], request_id: str | None = "sub1") -> list[Any]:
    rid = _sanitize_ws_request_id(request_id)
    payload = {"op": "subscribe", "args": args}
    if rid:
        payload["id"] = rid
    ws.send(json.dumps(payload, ensure_ascii=False))
    return ws_recv_json(ws, timeout_seconds=4.0, limit=max(10, len(args) * 4))


def poll_order(
    session: requests.Session,
    base_url: str,
    creds: Credentials,
    inst_id: str,
    ord_id: str,
    timeout_seconds: float = 6.0,
) -> dict[str, Any]:
    deadline = time.time() + max(1.0, timeout_seconds)
    last: dict[str, Any] = {}
    while time.time() < deadline:
        st, data, meta = rest_request(
            session,
            "GET",
            base_url,
            "/api/v5/trade/order",
            params={"instId": inst_id, "ordId": ord_id},
            creds=creds,
            signed=True,
        )
        row = parse_first_row(data)
        last = {"status_code": st, "meta": meta, "response": data, "row": row}
        if st == 200 and isinstance(data, dict) and str(data.get("code")) == "0" and isinstance(row, dict):
            state = str(row.get("state", "")).lower()
            acc_fill_sz = str(row.get("accFillSz", row.get("fillSz", "0")))
            try:
                filled = Decimal(acc_fill_sz)
            except Exception:
                filled = Decimal("0")
            if state in {"filled", "canceled", "partially_filled"} or filled > 0:
                return last
        time.sleep(0.5)
    return last
