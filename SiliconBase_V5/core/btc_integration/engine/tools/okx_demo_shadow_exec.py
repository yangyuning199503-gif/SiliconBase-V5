from __future__ import annotations

import argparse
import json
import os
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import yaml
from pandas.errors import EmptyDataError

_engine_dir = str(Path(__file__).resolve().parents[1])
if _engine_dir not in sys.path:
    sys.path.insert(0, _engine_dir)

from src.backtest.engine import run_backtest_portfolio
from src.backtest.io import load_ohlcv_csv, read_config
from src.live.okx_shadow import build_shadow_plan, write_shadow_plan
from tools.okx_demo_common import (
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
    truthy_env,
    write_json,
    write_jsonl,
)
from tools.okx_demo_sizing import parse_balance_snapshot, resolve_symbol_notionals


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


def _to_decimal(x: Any, default: str = "0") -> Decimal:
    try:
        return Decimal(str(x))
    except Exception:
        return Decimal(default)


def _runtime_dir_for_state(root: Path) -> Path:
    raw = os.environ.get("OKX_AUTOPILOT_RUNTIME_DIR", ".runtime")
    p = Path(os.path.expanduser(str(raw)))
    if not p.is_absolute():
        p = root / p
    p.mkdir(parents=True, exist_ok=True)
    return p


def _pnl_baseline_path(root: Path) -> Path:
    return _runtime_dir_for_state(root) / "okx_demo_pnl_baseline.json"


def _strategy_pnl_state_path(root: Path) -> Path:
    return _runtime_dir_for_state(root) / "okx_demo_strategy_pnl_state.json"


def _account_config_cache_path(root: Path) -> Path:
    return _runtime_dir_for_state(root) / "okx_account_config_cache.json"


def _request_account_config_with_retry(
    session: requests.Session,
    rest_base: str,
    creds: dict[str, Any],
    retries: int = 3,
    base_sleep_seconds: float = 0.8,
) -> tuple[int, Any, Any, list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    last_status: int = 0
    last_data: Any = {}
    last_meta: Any = {}
    total = max(1, int(retries))
    for attempt in range(1, total + 1):
        st, data_acc, meta_acc = rest_request(session, "GET", rest_base, "/api/v5/account/config", creds=creds, signed=True, demo=True)
        ok = st == 200 and _okx_code_zero(data_acc)
        attempts.append({
            "attempt": attempt,
            "status_code": st,
            "ok": ok,
            "response_code": str(data_acc.get("code", "")) if isinstance(data_acc, dict) else "",
            "response_msg": str(data_acc.get("msg", "")) if isinstance(data_acc, dict) else "",
        })
        last_status, last_data, last_meta = st, data_acc, meta_acc
        if ok:
            return last_status, last_data, last_meta, attempts
        if attempt < total:
            time.sleep(max(0.2, float(base_sleep_seconds) * attempt))
    return last_status, last_data, last_meta, attempts


def _strategy_pnl_state_template() -> dict[str, Any]:
    return {
        "scope": "local_strategy_fill_ledger",
        "version": 1,
        "initialized_at_utc": now_utc_text(),
        "first_live_order_utc": "",
        "last_update_utc": "",
        "symbols": {},
    }


def _load_strategy_pnl_state(root: Path) -> dict[str, Any]:
    data = _load_json_file(_strategy_pnl_state_path(root))
    if not data:
        data = _strategy_pnl_state_template()
    if not isinstance(data.get("symbols"), dict):
        data["symbols"] = {}
    data.setdefault("scope", "local_strategy_fill_ledger")
    data.setdefault("version", 1)
    data.setdefault("initialized_at_utc", now_utc_text())
    data.setdefault("first_live_order_utc", "")
    data.setdefault("last_update_utc", "")
    return data


def _save_strategy_pnl_state(root: Path, state: dict[str, Any]) -> None:
    payload = dict(state or {})
    if not payload.get("initialized_at_utc"):
        payload["initialized_at_utc"] = now_utc_text()
    payload["last_update_utc"] = now_utc_text()
    if not isinstance(payload.get("symbols"), dict):
        payload["symbols"] = {}
    _write_json_file(_strategy_pnl_state_path(root), payload)


def _contract_meta(inst: dict[str, Any]) -> dict[str, Any]:
    inst_id = str(inst.get("instId", "") or "")
    parts = inst_id.split("-")
    base_ccy = parts[0].upper() if len(parts) >= 1 else ""
    quote_ccy = parts[1].upper() if len(parts) >= 2 else ""
    settle_ccy = str(inst.get("settleCcy", "") or "").upper()
    ct_val = _to_decimal(inst.get("ctVal", "0"))
    ct_val_ccy = str(inst.get("ctValCcy", "") or "").upper()
    return {
        "inst_id": inst_id,
        "base_ccy": base_ccy,
        "quote_ccy": quote_ccy,
        "settle_ccy": settle_ccy,
        "ct_val": ct_val,
        "ct_val_ccy": ct_val_ccy,
    }


def _env_symbol_set(name: str) -> set[str]:
    raw = str(os.environ.get(name, "") or "").strip()
    if not raw:
        return set()
    out: set[str] = set()
    for part in raw.replace(";", ",").split(","):
        tok = str(part or "").strip().lower()
        if tok:
            out.add(tok)
    return out


def _position_snapshot_flat_copy(pos: dict[str, Any] | None, note: str = "") -> dict[str, Any]:
    base = dict(pos or {}) if isinstance(pos, dict) else {}
    base["side"] = "FLAT"
    base["signed_qty"] = "0"
    base["abs_qty"] = "0"
    base["unrealized_pnl"] = "0"
    base["notional_usd"] = "0"
    if note:
        base["note"] = note
    return base


def _skip_account_seed_for_symbol(sym: str) -> bool:
    sym_l = str(sym or "").lower()
    return sym_l in _env_symbol_set("OKX_DISABLE_ACCOUNT_POSITION_SEED_SYMBOLS")


def _hide_shared_account_position_for_symbol(sym: str) -> bool:
    sym_l = str(sym or "").lower()
    return sym_l in _env_symbol_set("OKX_HIDE_SHARED_ACCOUNT_POSITIONS_SYMBOLS")


def _force_flat_symbol(sym: str) -> bool:
    sym_l = str(sym or "").lower()
    return sym_l in _env_symbol_set("OKX_FORCE_FLAT_SYMBOLS")


def _ensure_strategy_symbol_state(state: dict[str, Any], sym: str, inst: dict[str, Any], current_pos: dict[str, Any]) -> dict[str, Any]:
    symbols = state.setdefault("symbols", {}) if isinstance(state, dict) else {}
    cur = symbols.get(sym) if isinstance(symbols.get(sym), dict) else {}
    meta = _contract_meta(inst)
    cur["symbol"] = sym
    cur["inst_id"] = meta["inst_id"]
    cur["base_ccy"] = meta["base_ccy"]
    cur["quote_ccy"] = meta["quote_ccy"]
    cur["settle_ccy"] = meta["settle_ccy"]
    cur["ct_val"] = format_decimal(meta["ct_val"]) if meta["ct_val"] > 0 else "0"
    cur["ct_val_ccy"] = meta["ct_val_ccy"]
    cur.setdefault("signed_qty", "0")
    cur.setdefault("avg_px", "0")
    cur.setdefault("realized_pnl", "0")
    cur.setdefault("seeded_from_account_position", False)
    cur.setdefault("seed_note", "")
    cur.setdefault("last_fill_px", "")
    cur.setdefault("last_fill_qty", "")
    cur.setdefault("last_fill_side", "")
    cur.setdefault("last_fill_ord_id", "")
    cur.setdefault("last_live_order_utc", "")
    cur.setdefault("last_update_utc", "")

    if _to_decimal(cur.get("signed_qty", "0")) == 0 and not _skip_account_seed_for_symbol(sym):
        acct_qty = _to_decimal((current_pos or {}).get("signed_qty", "0"))
        acct_avg = _to_decimal((current_pos or {}).get("avg_px", "0"))
        if acct_qty != 0 and acct_avg > 0:
            cur["signed_qty"] = format_decimal(acct_qty)
            cur["avg_px"] = format_decimal(acct_avg)
            cur["seeded_from_account_position"] = True
            cur["seed_note"] = "state_missing_seeded_from_account_position_avg"
            cur["last_update_utc"] = now_utc_text()

    symbols[sym] = cur
    return cur


def _filled_attempts(execution: dict[str, Any]) -> list[dict[str, Any]]:
    attempts = execution.get("attempts") if isinstance(execution.get("attempts"), list) else []
    out: list[dict[str, Any]] = []
    for attempt in attempts:
        if not isinstance(attempt, dict):
            continue
        row = ((attempt.get("order") or {}) if isinstance(attempt.get("order"), dict) else {}).get("row")
        state = str((row or {}).get("state", "")).lower() if isinstance(row, dict) else ""
        if attempt.get("filled") or state == "filled":
            out.append(attempt)
    return out


def _latest_confirmed_position(execution: dict[str, Any]) -> dict[str, Any] | None:
    attempts = execution.get("attempts") if isinstance(execution.get("attempts"), list) else []
    for attempt in reversed(attempts):
        if not isinstance(attempt, dict):
            continue
        confirm = attempt.get("position_confirm") if isinstance(attempt.get("position_confirm"), dict) else {}
        pos = confirm.get("actual_position") if isinstance(confirm.get("actual_position"), dict) else None
        if isinstance(pos, dict):
            return pos
    return None


def _contract_pnl_usdt(meta: dict[str, Any], qty_contracts: Decimal, entry_px: Decimal, exit_px: Decimal, side_sign: int) -> Decimal:
    qty = abs(qty_contracts)
    ct_val = meta.get("ct_val") if isinstance(meta.get("ct_val"), Decimal) else _to_decimal(meta.get("ct_val", "0"))
    if qty <= 0 or ct_val <= 0 or entry_px <= 0 or exit_px <= 0 or side_sign not in {1, -1}:
        return Decimal("0")
    ct_val_ccy = str(meta.get("ct_val_ccy", "") or "").upper()
    base_ccy = str(meta.get("base_ccy", "") or "").upper()
    quote_ccy = str(meta.get("quote_ccy", "") or "").upper()
    settle_ccy = str(meta.get("settle_ccy", "") or "").upper()
    sign = Decimal(str(side_sign))
    if ct_val_ccy == base_ccy:
        return qty * ct_val * (exit_px - entry_px) * sign
    if ct_val_ccy in {quote_ccy, settle_ccy}:
        base_qty = qty * ct_val / max(entry_px, Decimal("1e-18"))
        return base_qty * (exit_px - entry_px) * sign
    return qty * ct_val * (exit_px - entry_px) * sign


def _apply_exec_attempt_to_strategy_state(sym_state: dict[str, Any], attempt: dict[str, Any]) -> None:
    if not isinstance(sym_state, dict) or not isinstance(attempt, dict):
        return
    payload = attempt.get("payload") if isinstance(attempt.get("payload"), dict) else {}
    order = attempt.get("order") if isinstance(attempt.get("order"), dict) else {}
    row = order.get("row") if isinstance(order.get("row"), dict) else {}
    pos_after = ((attempt.get("position_confirm") or {}) if isinstance(attempt.get("position_confirm"), dict) else {}).get("actual_position")
    side = str(payload.get("side", "") or "").lower()
    reduce_only = bool(payload.get("reduceOnly", False))
    fill_qty = _to_decimal(row.get("fillSz") or row.get("accFillSz") or payload.get("sz") or "0")
    fill_px = _to_decimal(row.get("fillPx") or row.get("avgPx") or "0")
    prev_qty = _to_decimal(sym_state.get("signed_qty", "0"))
    prev_avg = _to_decimal(sym_state.get("avg_px", "0"))
    realized = _to_decimal(sym_state.get("realized_pnl", "0"))
    meta = {
        "ct_val": _to_decimal(sym_state.get("ct_val", "0")),
        "ct_val_ccy": sym_state.get("ct_val_ccy", ""),
        "base_ccy": sym_state.get("base_ccy", ""),
        "quote_ccy": sym_state.get("quote_ccy", ""),
        "settle_ccy": sym_state.get("settle_ccy", ""),
    }

    delta = fill_qty if side == "buy" else (-fill_qty if side == "sell" else Decimal("0"))
    if prev_qty > 0 and delta < 0 and prev_avg > 0 and fill_px > 0:
        close_qty = min(abs(prev_qty), abs(delta))
        realized += _contract_pnl_usdt(meta, close_qty, prev_avg, fill_px, 1)
    elif prev_qty < 0 and delta > 0 and prev_avg > 0 and fill_px > 0:
        close_qty = min(abs(prev_qty), abs(delta))
        realized += _contract_pnl_usdt(meta, close_qty, prev_avg, fill_px, -1)

    new_qty = prev_qty
    if fill_qty > 0:
        if reduce_only:
            tentative = prev_qty + delta
            if prev_qty > 0 and tentative < 0:
                tentative = Decimal("0")
            if prev_qty < 0 and tentative > 0:
                tentative = Decimal("0")
            new_qty = tentative
        else:
            new_qty = prev_qty + delta

    new_avg = prev_avg
    if new_qty == 0:
        new_avg = Decimal("0")
    elif prev_qty == 0 or prev_qty * delta > 0:
        prev_abs = abs(prev_qty)
        new_avg = ((prev_abs * prev_avg) + (abs(delta) * fill_px)) / max(abs(new_qty), Decimal("1e-18")) if fill_px > 0 else prev_avg
    elif prev_qty * new_qty > 0:
        new_avg = prev_avg
    else:
        new_avg = fill_px if fill_px > 0 else prev_avg

    if isinstance(pos_after, dict):
        actual_signed = _to_decimal(pos_after.get("signed_qty", new_qty))
        actual_avg = _to_decimal(pos_after.get("avg_px", new_avg))
        new_qty = actual_signed
        if actual_signed == 0:
            new_avg = Decimal("0")
        elif actual_avg > 0:
            new_avg = actual_avg

    now_txt = now_utc_text()
    sym_state["signed_qty"] = format_decimal(new_qty)
    sym_state["avg_px"] = format_decimal(new_avg) if new_qty != 0 and new_avg > 0 else "0"
    sym_state["realized_pnl"] = format_decimal(realized, "0.01")
    if fill_px > 0:
        sym_state["last_fill_px"] = format_decimal(fill_px)
    if fill_qty > 0:
        sym_state["last_fill_qty"] = format_decimal(fill_qty)
    if side:
        sym_state["last_fill_side"] = side
    sym_state["last_fill_ord_id"] = str(attempt.get("ord_id") or sym_state.get("last_fill_ord_id", ""))
    sym_state["last_live_order_utc"] = now_txt
    sym_state["last_update_utc"] = now_txt


def _apply_execution_to_strategy_state(state: dict[str, Any], sym: str, execution: dict[str, Any]) -> None:
    symbols = state.setdefault("symbols", {}) if isinstance(state, dict) else {}
    sym_state = symbols.get(sym) if isinstance(symbols.get(sym), dict) else None
    if not isinstance(sym_state, dict):
        return
    for attempt in _filled_attempts(execution):
        _apply_exec_attempt_to_strategy_state(sym_state, attempt)
        live_ts = str(sym_state.get("last_live_order_utc", "") or "")
        if live_ts and not state.get("first_live_order_utc"):
            state["first_live_order_utc"] = live_ts
    state["last_update_utc"] = now_utc_text()
    symbols[sym] = sym_state


def _load_json_file(path: Path) -> dict[str, Any]:
    try:
        if path.exists() and path.is_file():
            data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def _write_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _bar_to_ms(bar: str) -> int:
    b = str(bar).strip().lower()
    mapping = {
        "1m": 60_000,
        "3m": 180_000,
        "5m": 300_000,
        "15m": 900_000,
        "30m": 1_800_000,
        "1h": 3_600_000,
        "2h": 7_200_000,
        "4h": 14_400_000,
    }
    if b in mapping:
        return mapping[b]
    raise ValueError(f"unsupported bar: {bar}")


def _completed_bar_open_ms(bar: str) -> int:
    bar_ms = _bar_to_ms(bar)
    now_ms = int(time.time() * 1000)
    cur_open = (now_ms // bar_ms) * bar_ms
    return cur_open - bar_ms


def _parse_candle_array(row: Any) -> dict[str, Any] | None:
    if not isinstance(row, (list, tuple)) or len(row) < 6:
        return None
    try:
        ts_ms = int(str(row[0]))
    except Exception:
        return None
    confirm = str(row[-1]) if len(row) >= 7 else "1"
    return {
        "ts_ms": ts_ms,
        "time": pd.to_datetime(ts_ms, unit="ms", utc=True).tz_convert(None),
        "open": float(row[1]),
        "high": float(row[2]),
        "low": float(row[3]),
        "close": float(row[4]),
        "volume": float(row[5]),
        "confirm": confirm,
    }


def _load_existing_last_open_ms(csv_path: Path) -> int | None:
    if not csv_path.exists():
        return None
    try:
        df = load_ohlcv_csv(csv_path)
    except (EmptyDataError, ValueError, OSError):
        return None
    except Exception:
        return None
    if df.empty:
        return None
    try:
        last_idx = df.index[-1]
    except Exception:
        return None
    ts = pd.Timestamp(last_idx)
    if pd.isna(ts):
        return None
    try:
        ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts
    except Exception:
        return None
    if pd.isna(ts):
        return None
    return int(ts.timestamp() * 1000)


def _empty_sync_csv_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])


def _load_existing_sync_csv_frame(csv_path: Path) -> tuple[pd.DataFrame, str | None]:
    if not csv_path.exists():
        return _empty_sync_csv_frame(), None
    try:
        if csv_path.stat().st_size == 0:
            return _empty_sync_csv_frame(), "empty_csv_reset"
    except OSError:
        return _empty_sync_csv_frame(), "csv_stat_failed_reset"
    try:
        df_old = pd.read_csv(csv_path)
    except EmptyDataError:
        return _empty_sync_csv_frame(), "empty_csv_reset"
    except Exception as e:
        return _empty_sync_csv_frame(), f"csv_read_error_reset:{type(e).__name__}"
    if df_old.empty and len(df_old.columns) == 0:
        return _empty_sync_csv_frame(), "empty_csv_reset"
    need = {"time", "open", "high", "low", "close", "volume"}
    cols_l = {str(c).strip().lower() for c in df_old.columns}
    if df_old.empty and not need.issubset(cols_l):
        return _empty_sync_csv_frame(), "empty_schema_reset"
    return df_old, None


def _history_candles_page(session: requests.Session, rest_base: str, inst_id: str, bar: str, *, after: int | None, limit: int) -> tuple[int, Any, dict[str, Any]]:
    params: dict[str, Any] = {"instId": inst_id, "bar": bar, "limit": limit}
    if after is not None:
        params["after"] = str(after)
    return rest_request(session, "GET", rest_base, "/api/v5/market/history-candles", params=params, demo=False)


def sync_recent_klines(
    session: requests.Session,
    rest_base: str,
    inst_id: str,
    bar: str,
    csv_path: Path,
    *,
    bootstrap_bars_when_csv_missing: int = 5000,
    limit: int = 100,
    max_pages: int = 200,
) -> dict[str, Any]:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    last_open_ms = _load_existing_last_open_ms(csv_path)
    bar_ms = _bar_to_ms(bar)
    last_complete_open_ms = _completed_bar_open_ms(bar)

    if last_open_ms is not None and last_open_ms >= last_complete_open_ms:
        try:
            df_existing = load_ohlcv_csv(csv_path)
            rows_total_after = len(df_existing)
            last_time_after = None
            if rows_total_after > 0:
                try:
                    last_idx = df_existing.index[-1]
                    if getattr(last_idx, "tzinfo", None) is not None:
                        last_idx = last_idx.tz_convert("UTC").tz_localize(None)
                    last_time_after = pd.Timestamp(last_idx).strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    last_time_after = None
        except Exception:
            rows_total_after = 0
            last_time_after = None
        return {
            "ok": True,
            "inst_id": inst_id,
            "csv_path": str(csv_path),
            "last_open_ms_before": last_open_ms,
            "last_complete_open_ms": last_complete_open_ms,
            "rows_added": 0,
            "rows_total_after": rows_total_after,
            "last_time_after": last_time_after,
            "no_sync_needed": True,
        }

    if last_open_ms is None:
        last_open_ms = last_complete_open_ms - bootstrap_bars_when_csv_missing * bar_ms

    collected: dict[int, dict[str, Any]] = {}
    pages: list[dict[str, Any]] = []
    cursor_after: int | None = None
    reached_old_boundary = False

    for page_idx in range(max_pages):
        st, data, meta = _history_candles_page(session, rest_base, inst_id, bar, after=cursor_after, limit=limit)
        rows = data.get("data", []) if isinstance(data, dict) else []
        page_rec = {
            "page": page_idx + 1,
            "status_code": st,
            "ok": st == 200 and _okx_code_zero(data),
            "request_path": meta.get("request_path"),
            "rows": len(rows) if isinstance(rows, list) else 0,
        }
        pages.append(page_rec)
        if not (st == 200 and _okx_code_zero(data) and isinstance(rows, list) and rows):
            break

        ts_values: list[int] = []
        for raw in rows:
            parsed = _parse_candle_array(raw)
            if not parsed:
                continue
            ts_ms = int(parsed["ts_ms"])
            ts_values.append(ts_ms)
            if ts_ms <= last_open_ms:
                reached_old_boundary = True
            if parsed["confirm"] != "1":
                continue
            if ts_ms > last_complete_open_ms:
                continue
            if ts_ms > last_open_ms:
                collected[ts_ms] = parsed

        if not ts_values:
            break
        oldest = min(ts_values)
        if reached_old_boundary:
            break
        if cursor_after is not None and oldest >= cursor_after:
            break
        cursor_after = oldest
        time.sleep(0.12)

    rows_new = sorted(collected.values(), key=lambda x: x["ts_ms"])
    df_old, csv_reset_reason = _load_existing_sync_csv_frame(csv_path)
    rows_before = int(len(df_old))
    df_new = pd.DataFrame([
        {
            "time": x["time"].strftime("%Y-%m-%d %H:%M:%S"),
            "open": x["open"],
            "high": x["high"],
            "low": x["low"],
            "close": x["close"],
            "volume": x["volume"],
        }
        for x in rows_new
    ])
    df_all = pd.concat([df_old, df_new], ignore_index=True) if not df_new.empty else df_old.copy()
    if not df_all.empty:
        df_all["time"] = pd.to_datetime(df_all["time"], utc=True, errors="coerce")
        df_all = df_all.dropna(subset=["time"])
        df_all = df_all.sort_values("time").drop_duplicates("time", keep="last")
        df_all["time"] = df_all["time"].dt.strftime("%Y-%m-%d %H:%M:%S")
        df_all.to_csv(csv_path, index=False, encoding="utf-8")
    rows_after = int(len(df_all))
    last_time_after = str(df_all["time"].iloc[-1]) if rows_after > 0 else None
    out = {
        "ok": True,
        "inst_id": inst_id,
        "csv_path": str(csv_path),
        "last_open_ms_before": last_open_ms,
        "last_complete_open_ms": last_complete_open_ms,
        "rows_added": max(0, rows_after - rows_before),
        "rows_total_after": rows_after,
        "last_time_after": last_time_after,
        "pages": pages,
    }
    if csv_reset_reason:
        out["csv_reset_reason"] = csv_reset_reason
    return out


def _load_data_no_end_clip(root: Path, cfg: dict[str, Any]) -> dict[str, pd.DataFrame]:
    data_cfg = cfg.get("data", {}) or {}
    symbols = list(data_cfg.get("symbols", []))
    tmpl = str(data_cfg.get("csv_template", "data/raw/{symbol}_15m.csv"))
    start = pd.to_datetime(data_cfg.get("start"), utc=True).tz_convert(None) if data_cfg.get("start") else None

    data: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        path = root / Path(tmpl.format(symbol=sym))
        df = load_ohlcv_csv(path)
        if start is not None:
            df = df.loc[df.index >= start]
        data[str(sym).lower()] = df
    return data


def _desired_signal_map(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    final_positions = snapshot.get("final_positions", {}) if isinstance(snapshot, dict) else {}
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(final_positions, dict):
        return out
    for sym, pos in final_positions.items():
        if not isinstance(pos, dict):
            continue
        side_num = int(pos.get("side_num", 0) or 0)
        out[str(sym).lower()] = {
            "side_num": side_num,
            "side": "LONG" if side_num > 0 else ("SHORT" if side_num < 0 else "FLAT"),
            "mode": str(pos.get("mode", "NONE")),
            "tag": str(pos.get("tag", "")),
            "strategy_position": pos,
        }
    return out


def _best_effort_position(session: requests.Session, rest_base: str, creds: Any, inst_id: str) -> dict[str, Any]:
    st, data, meta = rest_request(session, "GET", rest_base, "/api/v5/account/positions", params={"instType": "SWAP", "instId": inst_id}, creds=creds, signed=True, demo=True)
    signed_qty = Decimal("0")
    unrealized_pnl = Decimal("0")
    reported_realized_pnl = Decimal("0")
    notional_usd = Decimal("0")
    avg_px = ""
    mark_px = ""
    rows = data.get("data", []) if isinstance(data, dict) else []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            pos = _to_decimal(row.get("pos", "0"))
            pos_side = str(row.get("posSide", "")).lower()
            if pos_side == "short" and pos > 0:
                signed_qty -= pos
            elif pos_side == "long" and pos > 0:
                signed_qty += pos
            else:
                signed_qty += pos
            unrealized_pnl += _to_decimal(row.get("upl") or row.get("uplLastPx") or "0")
            reported_realized_pnl += _to_decimal(row.get("realizedPnl") or row.get("pnl") or "0")
            notional_usd += abs(_to_decimal(row.get("notionalUsd") or "0"))
            if not avg_px and row.get("avgPx") not in {None, ""}:
                avg_px = str(row.get("avgPx"))
            if not mark_px and row.get("markPx") not in {None, ""}:
                mark_px = str(row.get("markPx"))
    return {
        "status_code": st,
        "meta": meta,
        "response": data,
        "ok": st == 200 and _okx_code_zero(data),
        "signed_qty": str(signed_qty),
        "side": "LONG" if signed_qty > 0 else ("SHORT" if signed_qty < 0 else "FLAT"),
        "abs_qty": format_decimal(abs(signed_qty)),
        "unrealized_pnl": format_decimal(unrealized_pnl, "0.01"),
        "reported_realized_pnl": format_decimal(reported_realized_pnl, "0.01"),
        "notional_usd": format_decimal(notional_usd, "0.01"),
        "avg_px": avg_px,
        "mark_px": mark_px,
    }


def _account_positions_summary(session: requests.Session, rest_base: str, creds: Any) -> dict[str, Any]:
    st, data, meta = rest_request(session, "GET", rest_base, "/api/v5/account/positions", params={"instType": "SWAP"}, creds=creds, signed=True, demo=True)
    unrealized_pnl = Decimal("0")
    inst_ids: list[str] = []
    rows = data.get("data", []) if isinstance(data, dict) else []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            unrealized_pnl += _to_decimal(row.get("upl") or row.get("uplLastPx") or "0")
            inst_id = str(row.get("instId", "") or "").strip()
            if inst_id:
                inst_ids.append(inst_id)
    return {
        "status_code": st,
        "meta": meta,
        "response": data,
        "ok": st == 200 and _okx_code_zero(data),
        "positions_count": len(rows) if isinstance(rows, list) else 0,
        "unrealized_pnl": format_decimal(unrealized_pnl, "0.01"),
        "inst_ids": inst_ids,
    }


def _pending_order_guard(session: requests.Session, rest_base: str, creds: Any, inst_id: str) -> dict[str, Any]:
    st, data, meta = rest_request(session, "GET", rest_base, "/api/v5/trade/orders-pending", params={"instType": "SWAP", "instId": inst_id}, creds=creds, signed=True, demo=True)
    rows = data.get("data", []) if isinstance(data, dict) else []
    cnt = len(rows) if isinstance(rows, list) else None
    return {
        "status_code": st,
        "meta": meta,
        "response": data,
        "ok": st == 200 and _okx_code_zero(data),
        "pending_count": cnt,
    }


def _submit_market_order(
    session: requests.Session,
    rest_base: str,
    creds: Any,
    *,
    inst_id: str,
    td_mode: str,
    side: str,
    qty: Decimal,
    lot_sz: str,
    reduce_only: bool,
    clord_prefix: str,
    poll_seconds: float = 6.0,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "instId": inst_id,
        "tdMode": td_mode,
        "side": side,
        "ordType": "market",
        "sz": format_decimal(abs(qty), lot_sz),
        "clOrdId": f"{clord_prefix}{int(time.time())}",
        "reduceOnly": bool(reduce_only),
    }
    st, data, meta = rest_request(session, "POST", rest_base, "/api/v5/trade/order", body=payload, creds=creds, signed=True, demo=True)
    out = {
        "submit": {"status_code": st, "meta": meta, "response": data, "ok": st == 200 and _okx_code_zero(data) and _row_scode_ok(data)},
        "payload": payload,
    }
    ord_id = _extract_ord_id(data)
    out["ord_id"] = ord_id
    if out["submit"]["ok"] and ord_id:
        out["order"] = poll_order(session, rest_base, creds, inst_id, ord_id, timeout_seconds=poll_seconds)
        row = out["order"].get("row") if isinstance(out.get("order"), dict) else None
        out["filled"] = isinstance(row, dict) and str(row.get("state", "")).lower() == "filled"
    else:
        out["filled"] = False
    return out




def _signed_delta_for_side(side: str, qty: Decimal) -> Decimal:
    return qty if str(side).lower() == "buy" else -qty


def _expected_signed_after(current_signed: Decimal, *, side: str, qty: Decimal, reduce_only: bool) -> Decimal:
    delta = _signed_delta_for_side(side, qty)
    if not reduce_only:
        return current_signed + delta
    if current_signed > 0 and delta < 0:
        nxt = current_signed + delta
        return nxt if nxt > 0 else Decimal("0")
    if current_signed < 0 and delta > 0:
        nxt = current_signed + delta
        return nxt if nxt < 0 else Decimal("0")
    return current_signed


def _signed_qty_from_position_snapshot(pos: dict[str, Any] | None) -> Decimal:
    if not isinstance(pos, dict):
        return Decimal("0")
    return _to_decimal(pos.get("signed_qty", "0"))


def _position_matches(actual_signed: Decimal, expected_signed: Decimal, lot_tol: Decimal) -> bool:
    tol = abs(lot_tol) / Decimal("2") if lot_tol > 0 else Decimal("0")
    return abs(actual_signed - expected_signed) <= tol


def _confirm_position_transition(
    session: requests.Session,
    rest_base: str,
    creds: Any,
    inst_id: str,
    *,
    expected_signed: Decimal,
    lot_tol: Decimal,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> dict[str, Any]:
    deadline = time.time() + max(0.5, float(timeout_seconds))
    snaps: list[dict[str, Any]] = []
    last_pos: dict[str, Any] | None = None
    while True:
        pos = _best_effort_position(session, rest_base, creds, inst_id)
        signed = _signed_qty_from_position_snapshot(pos)
        snap = {
            "ts": now_utc_text(),
            "signed_qty": format_decimal(signed),
            "side": pos.get("side"),
            "ok": bool(pos.get("ok")),
        }
        snaps.append(snap)
        last_pos = pos
        if _position_matches(signed, expected_signed, lot_tol):
            return {
                "ok": True,
                "expected_signed_qty": format_decimal(expected_signed),
                "actual_signed_qty": format_decimal(signed),
                "actual_position": pos,
                "polls": snaps,
            }
        if time.time() >= deadline:
            return {
                "ok": False,
                "expected_signed_qty": format_decimal(expected_signed),
                "actual_signed_qty": format_decimal(signed),
                "actual_position": last_pos,
                "polls": snaps,
            }
        time.sleep(max(0.2, float(poll_interval_seconds)))


def _remaining_action_from_target(actual_signed: Decimal, target_signed: Decimal) -> dict[str, Any] | None:
    remaining = target_signed - actual_signed
    if remaining == 0:
        return None
    side = "buy" if remaining > 0 else "sell"
    qty = abs(remaining)
    if target_signed == 0:
        reduce_only = True
    elif actual_signed == 0:
        reduce_only = False
    elif actual_signed * target_signed > 0:
        reduce_only = abs(actual_signed) > abs(target_signed)
    else:
        reduce_only = False
    return {
        "side": side,
        "qty": qty,
        "reduce_only": reduce_only,
    }


def _execute_action_with_retry(
    session: requests.Session,
    rest_base: str,
    creds: Any,
    *,
    inst_id: str,
    td_mode: str,
    lot_sz: str,
    lot_tol: Decimal,
    action: dict[str, Any],
    start_signed: Decimal,
    clord_prefix: str,
    poll_seconds: float,
    confirm_timeout_seconds: float,
    confirm_poll_seconds: float,
    retry_attempts: int,
    retry_sleep_seconds: float,
) -> dict[str, Any]:
    target_signed = _expected_signed_after(
        start_signed,
        side=str(action.get("side")),
        qty=_to_decimal(action.get("qty", "0")),
        reduce_only=bool(action.get("reduce_only", False)),
    )
    attempts: list[dict[str, Any]] = []
    actual_signed = start_signed
    max_attempts = max(1, int(retry_attempts) + 1)
    for attempt_no in range(1, max_attempts + 1):
        remaining = _remaining_action_from_target(actual_signed, target_signed)
        if remaining is None or _position_matches(actual_signed, target_signed, lot_tol):
            return {
                "ok": True,
                "filled": True,
                "confirmed": True,
                "attempts": attempts,
                "target_signed_qty": format_decimal(target_signed),
                "final_signed_qty": format_decimal(actual_signed),
            }
        res = _submit_market_order(
            session,
            rest_base,
            creds,
            inst_id=inst_id,
            td_mode=td_mode,
            side=str(remaining.get("side")),
            qty=_to_decimal(remaining.get("qty", "0")),
            lot_sz=lot_sz,
            reduce_only=bool(remaining.get("reduce_only", False)),
            clord_prefix=f"{clord_prefix}r{attempt_no}",
            poll_seconds=poll_seconds,
        )
        confirm = _confirm_position_transition(
            session,
            rest_base,
            creds,
            inst_id,
            expected_signed=target_signed,
            lot_tol=lot_tol,
            timeout_seconds=confirm_timeout_seconds,
            poll_interval_seconds=confirm_poll_seconds,
        )
        res["attempt_no"] = attempt_no
        res["requested_remaining_qty"] = format_decimal(_to_decimal(remaining.get("qty", "0")), lot_sz)
        res["requested_remaining_side"] = str(remaining.get("side"))
        res["requested_reduce_only"] = bool(remaining.get("reduce_only", False))
        res["position_confirm"] = confirm
        actual_signed = _to_decimal(confirm.get("actual_signed_qty", "0"))
        res["confirmed"] = bool(confirm.get("ok"))
        res["filled"] = bool(res.get("filled")) or bool(confirm.get("ok"))
        if not confirm.get("ok"):
            pending = _pending_order_guard(session, rest_base, creds, inst_id)
            res["pending_after_unconfirmed"] = pending
        attempts.append(res)
        if confirm.get("ok"):
            return {
                "ok": True,
                "ord_id": res.get("ord_id"),
                "filled": True,
                "confirmed": True,
                "attempts": attempts,
                "target_signed_qty": format_decimal(target_signed),
                "final_signed_qty": format_decimal(actual_signed),
            }
        pending = res.get("pending_after_unconfirmed") if isinstance(res.get("pending_after_unconfirmed"), dict) else None
        if pending and pending.get("ok") and int(pending.get("pending_count") or 0) > 0:
            break
        if attempt_no < max_attempts:
            time.sleep(max(0.2, float(retry_sleep_seconds)))
    return {
        "ok": False,
        "ord_id": attempts[-1].get("ord_id") if attempts else None,
        "filled": bool(attempts[-1].get("filled")) if attempts else False,
        "confirmed": False,
        "attempts": attempts,
        "target_signed_qty": format_decimal(target_signed),
        "final_signed_qty": format_decimal(actual_signed),
    }



def _read_risk_override(root: Path) -> dict[str, Any]:
    base = {
        "found": False,
        "path": None,
        "enabled": False,
        "active": False,
        "mode": "normal",
        "until_utc": None,
        "note": "",
        "raw": {},
    }
    env_mode = str(os.environ.get("OKX_RISK_OVERRIDE_MODE", "")).strip().lower()
    if env_mode:
        if env_mode not in {"normal", "pause_new_entries", "force_flat"}:
            env_mode = "normal"
        until_txt = os.environ.get("OKX_RISK_OVERRIDE_UNTIL_UTC", "").strip() or None
        parsed_until = None
        active = env_mode != "normal"
        if until_txt:
            try:
                parsed_until = pd.to_datetime(until_txt, utc=True)
                active = active and pd.Timestamp.now(tz="UTC") <= parsed_until
            except Exception:
                parsed_until = None
        return {
            "found": True,
            "path": "env:OKX_RISK_OVERRIDE_MODE",
            "enabled": env_mode != "normal",
            "active": active,
            "mode": env_mode,
            "until_utc": parsed_until.isoformat() if parsed_until is not None else until_txt,
            "note": str(os.environ.get("OKX_RISK_OVERRIDE_NOTE", "")),
            "raw": {
                "mode": env_mode,
                "until_utc": until_txt,
                "note": os.environ.get("OKX_RISK_OVERRIDE_NOTE", ""),
            },
        }
    for cand in [root / "risk_override.yml", root / "risk_override.yaml"]:
        if not cand.exists() or not cand.is_file():
            continue
        try:
            loaded = yaml.safe_load(cand.read_text(encoding="utf-8")) or {}
        except Exception as e:
            bad = dict(base)
            bad.update({"found": True, "path": str(cand), "error": str(e)})
            return bad
        obj = loaded.get("risk_override", loaded) if isinstance(loaded, dict) else {}
        if not isinstance(obj, dict):
            obj = {}
        mode = str(obj.get("mode", "normal")).strip().lower() or "normal"
        if mode not in {"normal", "pause_new_entries", "force_flat"}:
            mode = "normal"
        enabled = bool(obj.get("enabled", False))
        until_txt = obj.get("until_utc")
        active = enabled
        parsed_until = None
        if until_txt:
            try:
                parsed_until = pd.to_datetime(until_txt, utc=True)
                active = enabled and pd.Timestamp.now(tz="UTC") <= parsed_until
            except Exception:
                parsed_until = None
        return {
            "found": True,
            "path": str(cand),
            "enabled": enabled,
            "active": active,
            "mode": mode,
            "until_utc": parsed_until.isoformat() if parsed_until is not None else (str(until_txt) if until_txt else None),
            "note": str(obj.get("note", "")),
            "raw": obj,
        }
    return base


def _apply_pause_new_entries(action_plan: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    out: list[dict[str, Any]] = []
    blocked: list[str] = []
    for action in action_plan:
        kind = str(action.get("kind", "")).lower()
        if kind in {"open", "add", "flip_open"}:
            blocked.append(kind)
            continue
        out.append(action)
    if not out:
        out = [{"kind": "noop_risk_pause", "qty": "0"}]
    return out, blocked


def _read_coinglass_context() -> dict[str, Any]:
    mode = str(os.environ.get("OKX_COINGLASS_MODE", "normal") or "normal").strip().lower() or "normal"
    reason = str(os.environ.get("OKX_COINGLASS_REASON", "") or "")
    until_utc = str(os.environ.get("OKX_COINGLASS_UNTIL_UTC", "") or "") or None
    enforcement = str(os.environ.get("OKX_COINGLASS_ENFORCEMENT", "shadow_only") or "shadow_only").strip().lower() or "shadow_only"
    return {
        "mode": mode,
        "reason": reason,
        "until_utc": until_utc,
        "enforcement": enforcement,
        "would_pause_new_entries": mode == "pause_new_entries",
    }

def _write_txt_summary(path: Path, report: dict[str, Any]) -> None:
    lines = [
        f"okx_demo_shadow_exec_ok: {bool(report.get('ok'))}",
        f"reason: {report.get('reason', '')}",
        f"plan_version: {report.get('plan_version', '')}",
        f"signal_time: {report.get('signal_time', '')}",
        f"coinglass_mode: {(report.get('coinglass') or {}).get('mode', '') if isinstance(report.get('coinglass'), dict) else ''}",
        f"coinglass_reason: {(report.get('coinglass') or {}).get('reason', '') if isinstance(report.get('coinglass'), dict) else ''}",
        f"coinglass_enforcement: {(report.get('coinglass') or {}).get('enforcement', '') if isinstance(report.get('coinglass'), dict) else ''}",
    ]
    sizing = report.get("execution_sizing", {}) if isinstance(report.get("execution_sizing"), dict) else {}
    if sizing:
        lines.extend([
            f"execution_sizing_mode: {sizing.get('mode', '')}",
            f"execution_sizing_basis: {sizing.get('basis_label', '')}",
            f"execution_sizing_basis_equity_usdt: {sizing.get('basis_equity_usdt', '')}",
            f"execution_sizing_usable_equity_usdt: {sizing.get('usable_equity_usdt', '')}",
            f"execution_sizing_slices: {sizing.get('capital_slices', '')}",
            f"execution_sizing_leverage: {sizing.get('account_leverage', '')}",
            f"execution_sizing_leverage_mode: {sizing.get('leverage_mode', '')}",
            f"execution_sizing_total_target_margin_usdt: {sizing.get('total_target_margin_usdt', '')}",
            f"execution_sizing_total_target_notional_usdt: {sizing.get('total_target_notional_usdt', '')}",
        ])
    pnl = report.get("pnl_snapshot", {}) if isinstance(report.get("pnl_snapshot"), dict) else {}
    if pnl:
        lines.extend([
            f"strategy_scope: {pnl.get('strategy_scope', '')}",
            f"strategy_live_started: {pnl.get('strategy_live_started', '')}",
            f"strategy_note: {pnl.get('strategy_note', '')}",
            f"strategy_realized_pnl: {pnl.get('strategy_realized_pnl', '')}",
            f"strategy_unrealized_pnl: {pnl.get('strategy_unrealized_pnl', '')}",
            f"strategy_total_pnl: {pnl.get('strategy_total_pnl', '')}",
            f"shared_account_total_equity_usdt: {pnl.get('shared_account_total_equity_usdt', '')}",
            f"shared_account_total_pnl_observed: {pnl.get('shared_account_total_pnl_observed', '')}",
            f"shared_account_return_pct_observed: {pnl.get('shared_account_return_pct_observed', '')}",
        ])
    per_symbol = report.get("symbols", {}) if isinstance(report.get("symbols"), dict) else {}
    for sym, item in per_symbol.items():
        if not isinstance(item, dict):
            continue
        desired = item.get("desired_signal", {}) if isinstance(item.get("desired_signal"), dict) else {}
        current = item.get("current_position", {}) if isinstance(item.get("current_position"), dict) else {}
        action = item.get("action_plan", [])
        execs = item.get("executions", []) if isinstance(item.get("executions"), list) else []
        action_kinds = ",".join([str(x.get("kind")) for x in action if isinstance(x, dict)]) or "none"
        ords = ",".join([str(x.get("ord_id")) for x in execs if isinstance(x, dict) and x.get("ord_id")]) or "none"
        lines.append(
            f"{sym}: desired={desired.get('side')} current={current.get('side')} target_notional_usdt={item.get('target_notional_usdt','')} target_margin_usdt={item.get('target_margin_usdt','')} target_leverage={item.get('target_leverage','')} lev_reason={item.get('target_leverage_reason','')} unrealized_pnl={current.get('unrealized_pnl','')} notional_usd={current.get('notional_usd','')} actions={action_kinds} ords={ords}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")



def _build_pnl_snapshot(root: Path, report: dict[str, Any]) -> dict[str, Any]:
    balance_obj = ((report.get("balance") or {}) if isinstance(report.get("balance"), dict) else {}).get("response")
    snap = parse_balance_snapshot(balance_obj, equity_source="availEq") if balance_obj else {}
    total_eq = snap.get("total_eq") if isinstance(snap.get("total_eq"), Decimal) else Decimal("0")
    basis_eq = snap.get("basis_equity") if isinstance(snap.get("basis_equity"), Decimal) else Decimal("0")
    equity_now = total_eq if total_eq > 0 else basis_eq

    baseline_path = _pnl_baseline_path(root)
    baseline_state = _load_json_file(baseline_path)
    baseline_eq = _to_decimal(baseline_state.get("baseline_equity_usdt", "0"))
    initialized_at = str(baseline_state.get("initialized_at_utc", "") or "")
    if equity_now > 0 and (baseline_eq <= 0 or truthy_env("OKX_RESET_PNL_BASELINE")):
        baseline_state = {
            "baseline_equity_usdt": format_decimal(equity_now, "0.01"),
            "initialized_at_utc": now_utc_text(),
            "source": "auto_first_observation_or_reset",
        }
        _write_json_file(baseline_path, baseline_state)
        baseline_eq = equity_now
        initialized_at = str(baseline_state.get("initialized_at_utc", "") or "")

    account_positions = report.get("account_positions_summary", {}) if isinstance(report.get("account_positions_summary"), dict) else {}
    account_unrealized = _to_decimal(account_positions.get("unrealized_pnl", "0"))
    shared_total_pnl = equity_now - baseline_eq if (equity_now > 0 and baseline_eq > 0) else Decimal("0")
    shared_realized_pnl = shared_total_pnl - account_unrealized
    shared_return_pct = (shared_total_pnl / baseline_eq * Decimal("100")) if baseline_eq > 0 else Decimal("0")

    strategy_state = _load_strategy_pnl_state(root)
    strategy_symbols_state = strategy_state.get("symbols", {}) if isinstance(strategy_state.get("symbols"), dict) else {}
    strategy_realized = Decimal("0")
    for sym_state in strategy_symbols_state.values():
        if not isinstance(sym_state, dict):
            continue
        strategy_realized += _to_decimal(sym_state.get("realized_pnl", "0"))

    strategy_unrealized = Decimal("0")
    syms = report.get("symbols", {}) if isinstance(report.get("symbols"), dict) else {}
    for item in syms.values():
        if not isinstance(item, dict):
            continue
        cur = item.get("current_position", {}) if isinstance(item.get("current_position"), dict) else {}
        strategy_unrealized += _to_decimal(cur.get("unrealized_pnl", "0"))

    first_live_order_utc = str(strategy_state.get("first_live_order_utc", "") or "")
    strategy_live_started = bool(first_live_order_utc)
    seeded_without_live = any(
        isinstance(sym_state, dict) and _to_decimal(sym_state.get("signed_qty", "0")) != 0
        for sym_state in strategy_symbols_state.values()
    ) and not strategy_live_started
    strategy_note = ""
    if not strategy_live_started:
        strategy_realized = Decimal("0")
        strategy_unrealized = Decimal("0")
        if seeded_without_live:
            strategy_note = "state_seeded_from_account_position_without_confirmed_strategy_live_fill_forced_zero"
        else:
            strategy_note = "no_confirmed_strategy_live_fill_yet_forced_zero"
    strategy_total = strategy_realized + strategy_unrealized

    return {
        "strategy_scope": "local_strategy_fill_ledger + live_position_upl",
        "strategy_state_path": str(_strategy_pnl_state_path(root)),
        "strategy_first_live_order_utc": first_live_order_utc,
        "strategy_live_started": strategy_live_started,
        "strategy_note": strategy_note,
        "strategy_realized_pnl": format_decimal(strategy_realized, "0.01"),
        "strategy_unrealized_pnl": format_decimal(strategy_unrealized, "0.01"),
        "strategy_total_pnl": format_decimal(strategy_total, "0.01"),
        "strategy_symbols": sorted(syms.keys()),
        "shared_account_scope": "shared_demo_account_observation",
        "shared_account_baseline_path": str(baseline_path),
        "shared_account_baseline_equity_usdt": format_decimal(baseline_eq, "0.01"),
        "shared_account_baseline_initialized_at_utc": initialized_at,
        "shared_account_total_equity_usdt": format_decimal(equity_now, "0.01"),
        "shared_account_realized_pnl_observed": format_decimal(shared_realized_pnl, "0.01"),
        "shared_account_unrealized_pnl_observed": format_decimal(account_unrealized, "0.01"),
        "shared_account_total_pnl_observed": format_decimal(shared_total_pnl, "0.01"),
        "shared_account_return_pct_observed": f"{format_decimal(shared_return_pct, '0.01')}%",
    }


def _autopilot_output_base(root: Path) -> Path | None:
    if not truthy_env("OKX_AUTOPILOT_MODE"):
        return None
    raw = os.environ.get("OKX_AUTOPILOT_RUNTIME_DIR", ".runtime")
    p = Path(os.path.expanduser(str(raw)))
    if not p.is_absolute():
        p = root / p
    p.mkdir(parents=True, exist_ok=True)
    return p


def _resolve_output_paths(root: Path, args: argparse.Namespace) -> tuple[Path, Path, Path]:
    base = _autopilot_output_base(root)
    if base is None:
        return (
            resolve_out(root, args.out_json),
            resolve_out(root, args.out_jsonl),
            resolve_out(root, args.out_txt),
        )
    return (
        resolve_out(root, base / "okx_demo_shadow_exec_latest.json"),
        resolve_out(root, base / "okx_demo_shadow_exec_latest.jsonl"),
        resolve_out(root, base / "okx_demo_shadow_exec_latest.txt"),
    )

def main() -> None:
    ap = argparse.ArgumentParser(description="OKX Demo one-step shadow executor: sync recent 15m candles, recompute latest strategy state, then align tiny demo positions to the latest signal")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--out-json", default="reports/okx_demo_shadow_exec_latest.json")
    ap.add_argument("--out-jsonl", default="reports/okx_demo_shadow_exec_latest.jsonl")
    ap.add_argument("--out-txt", default="reports/okx_demo_shadow_exec_latest.txt")
    ap.add_argument("--confirm-demo", action="store_true", help="确认这一步可能会在 OKX Demo 上真实提交模拟单")
    ap.add_argument("--skip-sync", action="store_true", help="调试用：跳过 recent kline 同步")
    args = ap.parse_args()

    root = Path(args.project_dir).resolve()
    out_json, out_jsonl, out_txt = _resolve_output_paths(root, args)

    plan_base = _autopilot_output_base(root) or (root / "reports")
    write_shadow_plan(project_dir=root, out_json=plan_base / "shadow_mode_plan_latest.json", out_md=plan_base / "shadow_mode_plan_latest.md")
    plan = build_shadow_plan(project_dir=root)
    cfg = read_config(root / "config.yml")

    rest_base = str(plan.get("endpoints", {}).get("rest_base", ""))
    private_ws_url = str(plan.get("endpoints", {}).get("private_ws_base", ""))
    td_mode = str(plan.get("account", {}).get("td_mode", "cross"))
    leverage = str(plan.get("account", {}).get("leverage", 6))
    exec_cfg = plan.get("execution_step", {}) if isinstance(plan.get("execution_step"), dict) else {}
    bar = str(exec_cfg.get("bar", "15m"))
    bootstrap_bars_when_csv_missing = int(exec_cfg.get("bootstrap_bars_when_csv_missing", 5000))
    max_staleness_minutes = int(exec_cfg.get("max_staleness_minutes", 45))
    refuse_if_pending = bool(exec_cfg.get("refuse_if_pending_orders", True))
    submit_retry_attempts = int(exec_cfg.get("submit_retry_attempts", 2))
    submit_retry_sleep_seconds = float(exec_cfg.get("submit_retry_sleep_seconds", 0.8))
    submit_poll_seconds = float(exec_cfg.get("submit_poll_seconds", 6.0))
    confirm_position_timeout_seconds = float(exec_cfg.get("confirm_position_timeout_seconds", 8.0))
    confirm_position_poll_seconds = float(exec_cfg.get("confirm_position_poll_seconds", 0.5))
    default_notional = Decimal(str(exec_cfg.get("default_notional_usdt", 20.0)))
    per_symbol_notional = exec_cfg.get("notional_usdt_by_symbol", {}) if isinstance(exec_cfg.get("notional_usdt_by_symbol"), dict) else {}
    clord_base_prefix = ''.join(ch for ch in str(exec_cfg.get("clord_prefix", "okxshd")) if ch.isalnum()).lower()[:12] or "okxshd"
    precheck_no_submit = truthy_env("OKX_PRECHECK_NO_SUBMIT") or truthy_env("OKX_NO_SUBMIT_ORDERS")

    report: dict[str, Any] = {
        "ok": False,
        "ts_utc": now_utc_text(),
        "mode": "okx_demo_shadow_exec",
        "plan_version": plan.get("version"),
        "exchange": plan.get("exchange"),
        "demo": bool(plan.get("demo")),
        "confirm_demo": bool(args.confirm_demo),
        "rest_base": rest_base,
        "private_ws_url": private_ws_url,
        "execution_bar": bar,
        "notes": [
            "this step mirrors only the latest local strategy position state onto OKX Demo with equity-aware notional sizing",
            "it refreshes recent 15m candles from OKX public history-candles before recomputing the current strategy state locally",
            "protective stop/tp/trailing are preview-only in this step; actual submit path only aligns direction/flat state",
        ],
        "execution_confirm": {
            "submit_retry_attempts": submit_retry_attempts,
            "submit_retry_sleep_seconds": submit_retry_sleep_seconds,
            "submit_poll_seconds": submit_poll_seconds,
            "confirm_position_timeout_seconds": confirm_position_timeout_seconds,
            "confirm_position_poll_seconds": confirm_position_poll_seconds,
        },
        "order_id_prefix": clord_base_prefix,
        "precheck_no_submit": bool(precheck_no_submit),
    }
    raw_rows: list[Any] = []

    if not args.confirm_demo:
        report["reason"] = "missing --confirm-demo"
        report["how_to_run"] = "./.venv/bin/python -m tools.okx_demo_shadow_exec --project-dir . --confirm-demo"
        write_json(out_json, sanitize_obj(report))
        write_jsonl(out_jsonl, [])
        _write_txt_summary(out_txt, report)
        print(json.dumps({"ok": False, "reason": report["reason"], "out_json": str(out_json)}, ensure_ascii=False))
        return

    allowed_demo_rest_prefixes = ("https://www.okx.com", "https://eea.okx.com", "https://us.okx.com")
    if not rest_base.startswith(allowed_demo_rest_prefixes):
        report["reason"] = "refused_non_okx_demo_endpoint"
        write_json(out_json, sanitize_obj(report))
        write_jsonl(out_jsonl, [])
        _write_txt_summary(out_txt, report)
        print(json.dumps({"ok": False, "reason": report["reason"], "out_json": str(out_json)}, ensure_ascii=False))
        return

    creds, envs = load_credentials(plan.get("auth", {}), root=root)
    report["auth_envs"] = envs
    if creds is None:
        report["reason"] = "missing_credentials"
        write_json(out_json, sanitize_obj(report))
        write_jsonl(out_jsonl, [])
        _write_txt_summary(out_txt, report)
        print(json.dumps({"ok": False, "reason": report["reason"], "out_json": str(out_json)}, ensure_ascii=False))
        return

    session = requests.Session()

    # 1) sync recent candles into existing CSVs
    contract_map = plan.get("contract_map", {}) if isinstance(plan.get("contract_map"), dict) else {}
    symbols = list((cfg.get("data", {}) or {}).get("symbols", []))
    csv_template = str((cfg.get("data", {}) or {}).get("csv_template", "data/raw/{symbol}_15m.csv"))
    sync_reports: dict[str, Any] = {}
    if not args.skip_sync and bool(exec_cfg.get("refresh_recent_klines", True)):
        for sym in symbols:
            sym_l = str(sym).lower()
            inst_id = str(contract_map.get(sym_l, f"{sym_l.upper()}-USDT-SWAP"))
            csv_path = root / Path(csv_template.format(symbol=sym_l))
            sync_info = sync_recent_klines(
                session,
                rest_base,
                inst_id,
                bar,
                csv_path,
                bootstrap_bars_when_csv_missing=bootstrap_bars_when_csv_missing,
            )
            sync_reports[sym_l] = sync_info
            raw_rows.append({"step": f"sync_{sym_l}", "data": sync_info})
    report["data_sync"] = sync_reports

    # 2) recompute current signal state locally using the refreshed CSVs
    data = _load_data_no_end_clip(root, cfg)
    eq_df, trades_df, snapshot = run_backtest_portfolio(data=data, cfg=cfg)
    signal_time = str(snapshot.get("final_time")) if isinstance(snapshot, dict) else None
    report["signal_time"] = signal_time
    report["signal_snapshot"] = {
        "final_equity": snapshot.get("final_equity") if isinstance(snapshot, dict) else None,
        "open_positions_count": snapshot.get("open_positions_count") if isinstance(snapshot, dict) else None,
        "final_positions": snapshot.get("final_positions") if isinstance(snapshot, dict) else None,
    }
    desired_signal_map = _desired_signal_map(snapshot if isinstance(snapshot, dict) else {})
    risk_override = _read_risk_override(root)
    report["risk_override"] = risk_override
    report["coinglass"] = _read_coinglass_context()

    # 3) staleness guard
    stale_limit = pd.Timestamp.now(tz="UTC").tz_localize(None) - pd.Timedelta(minutes=max_staleness_minutes)
    if signal_time:
        try:
            signal_ts = pd.to_datetime(signal_time, utc=False)
            if signal_ts < stale_limit:
                report["reason"] = "signal_stale_after_sync"
                report["stale_limit_utc"] = str(stale_limit)
                write_json(out_json, sanitize_obj(report))
                write_jsonl(out_jsonl, [sanitize_obj(r) for r in raw_rows])
                _write_txt_summary(out_txt, report)
                print(json.dumps({"ok": False, "reason": report["reason"], "out_json": str(out_json)}, ensure_ascii=False))
                return
        except Exception:
            pass

    # 4) account config: prefer live endpoint, but allow autopilot cache fallback on transient failure
    cache_path = _account_config_cache_path(root)
    st, data_acc, meta_acc, account_attempts = _request_account_config_with_retry(
        session,
        rest_base,
        creds,
        retries=3,
        base_sleep_seconds=0.8,
    )
    endpoint_ok = st == 200 and _okx_code_zero(data_acc)
    report["account_config"] = {
        "status_code": st,
        "meta": meta_acc,
        "response": data_acc,
        "endpoint_ok": endpoint_ok,
        "ok": endpoint_ok,
        "attempts": account_attempts,
        "cache_path": str(cache_path),
    }
    raw_rows.append({"step": "account_config", "data": report["account_config"]})
    acc_row = parse_first_row(data_acc) or {}
    pos_mode = str(acc_row.get("posMode", "")) if isinstance(acc_row, dict) else ""
    if endpoint_ok:
        if pos_mode:
            _write_json_file(cache_path, {
                "ts_utc": now_utc_text(),
                "status_code": st,
                "posMode": pos_mode,
                "row": acc_row,
            })
    else:
        cache = _load_json_file(cache_path)
        cached_pos_mode = str(((cache.get("row") or {}) if isinstance(cache.get("row"), dict) else {}).get("posMode") or cache.get("posMode") or "")
        if truthy_env("OKX_AUTOPILOT_MODE") and cached_pos_mode == "net_mode":
            report["account_config"]["used_cache"] = True
            report["account_config"]["soft_fail"] = True
            report["account_config"]["ok"] = True
            report["account_config"]["cached_ts_utc"] = cache.get("ts_utc")
            report["account_config"]["cached_pos_mode"] = cached_pos_mode
            pos_mode = "net_mode"
        else:
            report["reason"] = "account_config_failed"
            write_json(out_json, sanitize_obj(report))
            write_jsonl(out_jsonl, [sanitize_obj(r) for r in raw_rows])
            _write_txt_summary(out_txt, report)
            print(json.dumps({"ok": False, "reason": report["reason"], "out_json": str(out_json)}, ensure_ascii=False))
            return
    if not pos_mode:
        pos_mode = "net_mode"
    report["position_mode"] = pos_mode
    if pos_mode != "net_mode":
        report["reason"] = "unsupported_pos_mode_for_shadow_exec"
        write_json(out_json, sanitize_obj(report))
        write_jsonl(out_jsonl, [sanitize_obj(r) for r in raw_rows])
        _write_txt_summary(out_txt, report)
        print(json.dumps({"ok": False, "reason": report["reason"], "out_json": str(out_json)}, ensure_ascii=False))
        return

    # 4.5) account balance snapshot for dynamic execution sizing
    st, data_bal, meta_bal = rest_request(session, "GET", rest_base, "/api/v5/account/balance", creds=creds, signed=True, demo=True)
    report["balance"] = {"status_code": st, "meta": meta_bal, "response": data_bal, "ok": st == 200 and _okx_code_zero(data_bal)}
    raw_rows.append({"step": "balance", "data": report["balance"]})
    per_symbol_sizing, sizing_summary = resolve_symbol_notionals(plan, data_bal if report["balance"]["ok"] else None, desired_signal_map)
    if not report["balance"]["ok"]:
        sizing_summary["mode"] = "fixed_notional_balance_failed"
        sizing_summary["balance_error"] = True
    report["execution_sizing"] = sizing_summary
    report["account_balance_summary"] = sizing_summary.get("balance", {}) if isinstance(sizing_summary, dict) else {}
    report["account_positions_summary"] = _account_positions_summary(session, rest_base, creds)
    raw_rows.append({"step": "account_positions_summary", "data": report["account_positions_summary"]})
    strategy_pnl_state = _load_strategy_pnl_state(root)

    # 5) align each symbol to desired demo state
    report["symbols"] = {}
    failures: list[str] = []
    executed_rows: list[Any] = []
    for sym in symbols:
        sym_l = str(sym).lower()
        inst_id = str(contract_map.get(sym_l, f"{sym_l.upper()}-USDT-SWAP"))
        desired_raw = desired_signal_map.get(sym_l, {"side_num": 0, "side": "FLAT", "mode": "NONE", "tag": "", "strategy_position": {}})
        desired = dict(desired_raw)
        shared_overlap_guard = False
        if _force_flat_symbol(sym_l):
            desired["side_num"] = 0
            desired["side"] = "FLAT"
            desired["mode"] = "NONE"
            desired["override_applied"] = "shared_account_symbol_overlap_guard"
            shared_overlap_guard = True
        if risk_override.get("active") and str(risk_override.get("mode")) == "force_flat":
            desired["side_num"] = 0
            desired["side"] = "FLAT"
            desired["override_applied"] = "force_flat"
        sizing_info = per_symbol_sizing.get(sym_l, {}) if isinstance(per_symbol_sizing, dict) else {}
        target_notional = Decimal(str((sizing_info or {}).get("target_notional_usdt", per_symbol_notional.get(sym_l, default_notional))))
        symbol_leverage = str((sizing_info or {}).get("target_leverage", leverage))
        item: dict[str, Any] = {
            "inst_id": inst_id,
            "desired_signal_raw": desired_raw,
            "desired_signal": desired,
            "sizing": sizing_info,
            "target_notional_usdt": str(target_notional),
            "target_margin_usdt": str((sizing_info or {}).get("target_margin_usdt", "")),
            "target_leverage": symbol_leverage,
            "target_leverage_reason": str((sizing_info or {}).get("leverage_reason", "")),
        }

        # instrument + ticker
        st, inst_data, meta = rest_request(session, "GET", rest_base, "/api/v5/public/instruments", params={"instType": "SWAP", "instId": inst_id}, demo=False)
        item["instrument"] = {"status_code": st, "meta": meta, "response": inst_data, "ok": st == 200 and _okx_code_zero(inst_data)}
        inst_row = parse_first_row(inst_data) or {}
        st, ticker_data, meta = rest_request(session, "GET", rest_base, "/api/v5/market/ticker", params={"instId": inst_id}, demo=False)
        item["ticker"] = {"status_code": st, "meta": meta, "response": ticker_data, "ok": st == 200 and _okx_code_zero(ticker_data)}
        last_price = parse_last_price(ticker_data)
        if not inst_row or last_price is None:
            item["reason"] = "instrument_or_ticker_failed"
            report["symbols"][sym_l] = item
            failures.append(f"{sym_l}:instrument_or_ticker_failed")
            continue

        lot_sz = str(inst_row.get("lotSz") or inst_row.get("minSz") or "1")
        target_qty_info = contract_qty_for_notional(inst_row, last_price, target_notional)
        target_abs_qty = _to_decimal(target_qty_info.get("qty", "0"))
        item["target_qty_info"] = target_qty_info
        item["protective_preview"] = {
            "stop": desired.get("strategy_position", {}).get("stop"),
            "tp": desired.get("strategy_position", {}).get("tp"),
            "trail": desired.get("strategy_position", {}).get("trail"),
            "breakeven": desired.get("strategy_position", {}).get("breakeven"),
            "note": "preview only; not submitted in r239",
        }

        observed_account_position = _best_effort_position(session, rest_base, creds, inst_id)
        current_pos = observed_account_position
        raw_rows.append({"step": f"current_position_{sym_l}", "data": observed_account_position})
        sym_state = _ensure_strategy_symbol_state(strategy_pnl_state, sym_l, inst_row, observed_account_position)
        if shared_overlap_guard:
            item["shared_account_overlap_guard"] = True
            item["shared_account_overlap_note"] = "same_okx_demo_account_symbol_overlap_guard"
        if _hide_shared_account_position_for_symbol(sym_l) and not str((sym_state or {}).get("last_live_order_utc") or ""):
            current_pos = _position_snapshot_flat_copy(observed_account_position, note="shared_account_overlap_hidden_until_first_branch_fill")
            item["account_position_observed"] = observed_account_position
            item["position_note"] = "shared_account_overlap_hidden_until_first_branch_fill"
        elif _force_flat_symbol(sym_l):
            item["position_note"] = item.get("position_note") or "demo_execution_disabled_for_symbol"
        item["current_position"] = current_pos
        item["current_position_before"] = current_pos
        current_signed = _to_decimal(current_pos.get("signed_qty", "0"))

        if refuse_if_pending:
            pending = _pending_order_guard(session, rest_base, creds, inst_id)
            item["orders_pending"] = pending
            raw_rows.append({"step": f"orders_pending_{sym_l}", "data": pending})
            if pending.get("ok") and int(pending.get("pending_count") or 0) > 0:
                item["reason"] = "existing_pending_orders"
                report["symbols"][sym_l] = item
                failures.append(f"{sym_l}:existing_pending_orders")
                continue

        desired_sign = int(desired.get("side_num", 0) or 0)
        action_plan: list[dict[str, Any]] = []
        tol = _to_decimal(lot_sz)
        if desired_sign == 0:
            if abs(current_signed) > 0:
                action_plan.append({"kind": "flatten", "side": "sell" if current_signed > 0 else "buy", "qty": format_decimal(abs(current_signed), lot_sz), "reduce_only": True})
            else:
                action_plan.append({"kind": "noop_flat", "qty": "0"})
        else:
            target_signed = target_abs_qty if desired_sign > 0 else -target_abs_qty
            if current_signed == 0:
                action_plan.append({"kind": "open", "side": "buy" if desired_sign > 0 else "sell", "qty": format_decimal(target_abs_qty, lot_sz), "reduce_only": False})
            elif current_signed * desired_sign < 0:
                action_plan.append({"kind": "flip_flatten", "side": "sell" if current_signed > 0 else "buy", "qty": format_decimal(abs(current_signed), lot_sz), "reduce_only": True})
                action_plan.append({"kind": "flip_open", "side": "buy" if desired_sign > 0 else "sell", "qty": format_decimal(target_abs_qty, lot_sz), "reduce_only": False})
            else:
                delta = target_signed - current_signed
                if abs(delta) <= tol / Decimal("2"):
                    action_plan.append({"kind": "hold", "qty": format_decimal(abs(current_signed), lot_sz)})
                elif delta * desired_sign > 0:
                    action_plan.append({"kind": "add", "side": "buy" if desired_sign > 0 else "sell", "qty": format_decimal(abs(delta), lot_sz), "reduce_only": False})
                else:
                    action_plan.append({"kind": "trim", "side": "sell" if current_signed > 0 else "buy", "qty": format_decimal(abs(delta), lot_sz), "reduce_only": True})
        item["action_plan_raw"] = list(action_plan)
        if risk_override.get("active") and str(risk_override.get("mode")) == "pause_new_entries":
            action_plan, blocked_actions = _apply_pause_new_entries(action_plan)
            item["risk_override_blocked_actions"] = blocked_actions
        item["action_plan"] = action_plan

        # set leverage only when there is a real order to submit
        has_real_order = any(str(a.get("kind", "")).lower() not in {"hold", "noop_flat", "noop_risk_pause"} for a in action_plan)
        if has_real_order and precheck_no_submit:
            item["precheck_no_submit"] = True
            item["reason"] = item.get("reason") or "precheck_no_submit"
            item["executions"] = []
            report["symbols"][sym_l] = item
            continue
        if has_real_order:
            st, data_lev, meta_lev = rest_request(session, "POST", rest_base, "/api/v5/account/set-leverage", body={"instId": inst_id, "lever": symbol_leverage, "mgnMode": td_mode}, creds=creds, signed=True, demo=True)
            item["set_leverage"] = {"status_code": st, "meta": meta_lev, "response": data_lev, "ok": st == 200 and _okx_code_zero(data_lev)}
            raw_rows.append({"step": f"set_leverage_{sym_l}", "data": item["set_leverage"]})
            if not item["set_leverage"]["ok"]:
                item["reason"] = "set_leverage_failed"
                report["symbols"][sym_l] = item
                failures.append(f"{sym_l}:set_leverage_failed")
                continue

        item["executions"] = []
        live_signed = current_signed
        for idx_action, action in enumerate(action_plan, start=1):
            kind = str(action.get("kind", "")).lower()
            if kind in {"hold", "noop_flat", "noop_risk_pause"}:
                continue
            qty = _to_decimal(action.get("qty", "0"))
            if qty <= 0:
                continue
            res = _execute_action_with_retry(
                session,
                rest_base,
                creds,
                inst_id=inst_id,
                td_mode=td_mode,
                lot_sz=lot_sz,
                lot_tol=tol,
                action=action,
                start_signed=live_signed,
                clord_prefix=f"{clord_base_prefix}{sym_l[:3]}{idx_action}",
                poll_seconds=submit_poll_seconds,
                confirm_timeout_seconds=confirm_position_timeout_seconds,
                confirm_poll_seconds=confirm_position_poll_seconds,
                retry_attempts=submit_retry_attempts,
                retry_sleep_seconds=submit_retry_sleep_seconds,
            )
            item["executions"].append(res)
            executed_rows.append({"step": f"submit_{sym_l}_{idx_action}", "data": res})
            if res.get("ok"):
                live_signed = _to_decimal(res.get("final_signed_qty", "0"))
            else:
                item["reason"] = f"submit_failed_{kind}"
                failures.append(f"{sym_l}:submit_failed_{kind}")
                break

        latest_pos_after: dict[str, Any] | None = None
        for ex in item.get("executions", []):
            if not isinstance(ex, dict):
                continue
            if ex.get("ok"):
                _apply_execution_to_strategy_state(strategy_pnl_state, sym_l, ex)
            pos_after = _latest_confirmed_position(ex)
            if isinstance(pos_after, dict):
                latest_pos_after = pos_after
        if isinstance(latest_pos_after, dict):
            item["current_position"] = latest_pos_after

        report["symbols"][sym_l] = item

    raw_rows.extend(executed_rows)
    _save_strategy_pnl_state(root, strategy_pnl_state)
    report["pnl_snapshot"] = _build_pnl_snapshot(root, report)
    report["ok"] = len(failures) == 0
    report["reason"] = "" if report["ok"] else ";".join(failures)
    write_json(out_json, sanitize_obj(report))
    write_jsonl(out_jsonl, [sanitize_obj(r) for r in raw_rows])
    _write_txt_summary(out_txt, report)
    print(json.dumps({"ok": report["ok"], "reason": report.get("reason", ""), "out_json": str(out_json)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
