from __future__ import annotations

from decimal import Decimal
from typing import Any

from tools.okx_demo_common import format_decimal, parse_first_row


def _dec(x: Any, default: str = "0") -> Decimal:
    try:
        return Decimal(str(x))
    except Exception:
        return Decimal(default)


def _nonzero(*vals: Decimal) -> Decimal:
    for v in vals:
        if v > 0:
            return v
    return Decimal("0")


def parse_balance_snapshot(balance_data: Any, equity_source: str = "availEq") -> dict[str, Any]:
    row = parse_first_row(balance_data) or {}
    details = row.get("details") if isinstance(row.get("details"), list) else []
    usdt = {}
    if isinstance(details, list):
        for item in details:
            if isinstance(item, dict) and str(item.get("ccy", "")).upper() == "USDT":
                usdt = item
                break

    total_eq = _dec(row.get("totalEq"))
    adj_eq = _dec(row.get("adjEq"))
    avail_eq = _dec(row.get("availEq"))
    iso_eq = _dec(row.get("isoEq"))
    notional_usd = _dec(row.get("notionalUsd"))

    usdt_eq = _nonzero(_dec(usdt.get("eq")), _dec(usdt.get("eqUsd")))
    usdt_avail = _nonzero(_dec(usdt.get("availEq")), _dec(usdt.get("availBal")), _dec(usdt.get("cashBal")))

    src = str(equity_source or "availEq").strip().lower() or "availeq"
    basis = Decimal("0")
    basis_label = src
    if src in {"availeq", "avail", "available", "available_eq"}:
        basis = _nonzero(avail_eq, usdt_avail, adj_eq, total_eq, usdt_eq)
        basis_label = "availEq"
    elif src in {"usdtavail", "usdt_avail", "avail_usdt"}:
        basis = _nonzero(usdt_avail, avail_eq, adj_eq, total_eq, usdt_eq)
        basis_label = "USDT.avail"
    elif src in {"adjeq", "adj", "adjusted"}:
        basis = _nonzero(adj_eq, total_eq, avail_eq, usdt_eq)
        basis_label = "adjEq"
    elif src in {"usdteq", "usdt_eq"}:
        basis = _nonzero(usdt_eq, total_eq, adj_eq, avail_eq)
        basis_label = "USDT.eq"
    else:
        basis = _nonzero(total_eq, adj_eq, avail_eq, usdt_eq)
        basis_label = "totalEq"

    return {
        "ok": basis > 0,
        "basis_equity": basis,
        "basis_label": basis_label,
        "equity_source_raw": src,
        "total_eq": total_eq,
        "adj_eq": adj_eq,
        "avail_eq": avail_eq,
        "iso_eq": iso_eq,
        "notional_usd": notional_usd,
        "usdt_eq": usdt_eq,
        "usdt_avail": usdt_avail,
        "row": row,
        "usdt_detail": usdt,
        "summary": {
            "basis_label": basis_label,
            "basis_equity_usdt": format_decimal(basis),
            "total_eq_usdt": format_decimal(total_eq),
            "adj_eq_usdt": format_decimal(adj_eq),
            "avail_eq_usdt": format_decimal(avail_eq),
            "usdt_eq": format_decimal(usdt_eq),
            "usdt_avail": format_decimal(usdt_avail),
            "notional_usd": format_decimal(notional_usd),
        },
    }


def _resolve_leverage(sizing_cfg: dict[str, Any], sym: str, side_key: str, default_leverage: Decimal) -> tuple[Decimal, str, str]:
    leverage_mode = str(sizing_cfg.get("leverage_mode", "signal_profile") or "signal_profile").strip().lower()
    min_leverage = max(Decimal("1"), _dec(sizing_cfg.get("min_leverage", default_leverage), str(default_leverage)))
    max_leverage = max(min_leverage, _dec(sizing_cfg.get("max_leverage", default_leverage), str(default_leverage)))
    symbol_cfg = sizing_cfg.get("leverage_by_symbol", {}) if isinstance(sizing_cfg.get("leverage_by_symbol"), dict) else {}
    signal_cfg = sizing_cfg.get("leverage_by_signal", {}) if isinstance(sizing_cfg.get("leverage_by_signal"), dict) else {}

    raw = default_leverage
    reason = "account_default"
    sig_key = f"{sym}_{side_key}"
    if leverage_mode in {"signal_profile", "dynamic_signal_profile", "signal", "profile"}:
        if sig_key in signal_cfg:
            raw = _dec(signal_cfg.get(sig_key), str(default_leverage))
            reason = f"signal:{sig_key}"
        elif sym in symbol_cfg:
            raw = _dec(symbol_cfg.get(sym), str(default_leverage))
            reason = f"symbol:{sym}"
    elif leverage_mode in {"symbol_profile", "symbol"}:
        if sym in symbol_cfg:
            raw = _dec(symbol_cfg.get(sym), str(default_leverage))
            reason = f"symbol:{sym}"
    else:
        reason = f"fixed:{format_decimal(default_leverage)}"

    out = raw
    clamp_note = ""
    if out < min_leverage:
        out = min_leverage
        clamp_note = "cap=min_leverage"
    elif out > max_leverage:
        out = max_leverage
        clamp_note = "cap=max_leverage"
    return out, reason, clamp_note


def resolve_symbol_notionals(plan: dict[str, Any], balance_data: Any, desired_signal_map: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    exec_cfg = plan.get("execution_step", {}) if isinstance(plan.get("execution_step"), dict) else {}
    sizing_cfg = exec_cfg.get("sizing", {}) if isinstance(exec_cfg.get("sizing"), dict) else {}
    fixed_map = exec_cfg.get("notional_usdt_by_symbol", {}) if isinstance(exec_cfg.get("notional_usdt_by_symbol"), dict) else {}
    fallback_default = _dec(exec_cfg.get("default_notional_usdt", 20.0), "20")

    enabled = bool(sizing_cfg.get("enabled", True))
    equity_source = str(sizing_cfg.get("equity_source", "availEq"))
    equity_utilization = max(Decimal("0"), _dec(sizing_cfg.get("equity_utilization", 0.85), "0.85"))
    reserve_usdt = max(Decimal("0"), _dec(sizing_cfg.get("reserve_usdt", 0.0), "0"))
    capital_slices = max(1, int(sizing_cfg.get("capital_slices", 8) or 8))
    min_notional = max(Decimal("0"), _dec(sizing_cfg.get("min_notional_usdt", 0.0), "0"))
    max_notional = max(Decimal("0"), _dec(sizing_cfg.get("max_notional_usdt", 6000.0), "6000"))
    symbol_scale_cfg = sizing_cfg.get("symbol_scale", {}) if isinstance(sizing_cfg.get("symbol_scale"), dict) else {}
    signal_scale_cfg = sizing_cfg.get("signal_scale", {}) if isinstance(sizing_cfg.get("signal_scale"), dict) else {}
    default_leverage = max(Decimal("1"), _dec((plan.get("account") or {}).get("leverage", 6), "6"))
    leverage_mode = str(sizing_cfg.get("leverage_mode", "signal_profile") or "signal_profile")
    min_leverage = max(Decimal("1"), _dec(sizing_cfg.get("min_leverage", default_leverage), str(default_leverage)))
    max_leverage = max(min_leverage, _dec(sizing_cfg.get("max_leverage", default_leverage), str(default_leverage)))
    max_active_margin_pct = max(Decimal("0"), _dec(sizing_cfg.get("max_active_margin_pct", 0.45), "0.45"))
    max_symbol_margin_pct = max(Decimal("0"), _dec(sizing_cfg.get("max_symbol_margin_pct", 0.22), "0.22"))

    snap = parse_balance_snapshot(balance_data, equity_source=equity_source)
    basis_eq = snap.get("basis_equity", Decimal("0")) if isinstance(snap.get("basis_equity"), Decimal) else Decimal("0")
    usable_eq = max(Decimal("0"), basis_eq * equity_utilization - reserve_usdt)
    base_margin = usable_eq / Decimal(str(capital_slices)) if usable_eq > 0 else Decimal("0")
    per_symbol_margin_cap = usable_eq * max_symbol_margin_pct if max_symbol_margin_pct > 0 else Decimal("0")
    total_margin_cap = usable_eq * max_active_margin_pct if max_active_margin_pct > 0 else Decimal("0")

    mode = "dynamic_equity_slices" if enabled and basis_eq > 0 else "fixed_notional"
    summary = {
        "enabled": enabled,
        "mode": mode,
        "equity_source": equity_source,
        "basis_label": snap.get("basis_label"),
        "basis_equity_usdt": format_decimal(basis_eq),
        "usable_equity_usdt": format_decimal(usable_eq),
        "equity_utilization": str(equity_utilization),
        "reserve_usdt": format_decimal(reserve_usdt),
        "capital_slices": capital_slices,
        "base_margin_per_slice_usdt": format_decimal(base_margin),
        "account_leverage": format_decimal(default_leverage),
        "default_account_leverage": format_decimal(default_leverage),
        "leverage_mode": leverage_mode,
        "min_leverage": format_decimal(min_leverage),
        "max_leverage": format_decimal(max_leverage),
        "max_active_margin_pct": str(max_active_margin_pct),
        "max_symbol_margin_pct": str(max_symbol_margin_pct),
        "per_symbol_margin_cap_usdt": format_decimal(per_symbol_margin_cap),
        "total_margin_cap_usdt": format_decimal(total_margin_cap),
        "min_notional_usdt": format_decimal(min_notional),
        "max_notional_usdt": format_decimal(max_notional),
        "fallback_default_notional_usdt": format_decimal(fallback_default),
        "balance": snap.get("summary", {}),
    }

    prelim: dict[str, dict[str, Any]] = {}
    active_symbols = []
    pre_active_margin_sum = Decimal("0")

    for sym_raw, desired in (desired_signal_map or {}).items():
        sym = str(sym_raw).lower()
        fixed = _dec(fixed_map.get(sym, fallback_default), str(fallback_default))
        desired_side_num = 0
        if isinstance(desired, dict):
            try:
                desired_side_num = int(desired.get("side_num", 0) or 0)
            except Exception:
                desired_side_num = 0
        side_key = "long" if desired_side_num > 0 else ("short" if desired_side_num < 0 else "flat")
        sig_key = f"{sym}_{side_key}"
        symbol_scale = _dec(symbol_scale_cfg.get(sym, 1.0), "1")
        signal_scale = _dec(signal_scale_cfg.get(sig_key, 1.0), "1")
        total_scale = max(Decimal("0"), symbol_scale * signal_scale)
        target_leverage, leverage_reason, leverage_clamp_note = _resolve_leverage(sizing_cfg, sym, side_key, default_leverage)

        active = enabled and basis_eq > 0 and desired_side_num != 0 and total_scale > 0
        target_margin_pre = Decimal("0")
        margin_cap_note = ""
        if active:
            target_margin_pre = base_margin * total_scale
            if per_symbol_margin_cap > 0 and target_margin_pre > per_symbol_margin_cap:
                target_margin_pre = per_symbol_margin_cap
                margin_cap_note = "cap=max_symbol_margin_pct"
            pre_active_margin_sum += target_margin_pre
            active_symbols.append(sym)

        prelim[sym] = {
            "fixed": fixed,
            "desired_side_num": desired_side_num,
            "side_key": side_key,
            "symbol_scale": symbol_scale,
            "signal_scale": signal_scale,
            "total_scale": total_scale,
            "target_leverage": target_leverage,
            "leverage_reason": leverage_reason,
            "leverage_clamp_note": leverage_clamp_note,
            "active": active,
            "target_margin_pre": target_margin_pre,
            "margin_cap_note": margin_cap_note,
        }

    portfolio_margin_scale = Decimal("1")
    if total_margin_cap > 0 and pre_active_margin_sum > total_margin_cap:
        portfolio_margin_scale = total_margin_cap / pre_active_margin_sum

    summary["active_signal_count"] = len(active_symbols)
    summary["active_symbols"] = active_symbols
    summary["pre_cap_total_active_margin_usdt"] = format_decimal(pre_active_margin_sum)
    summary["portfolio_margin_scale_factor"] = format_decimal(portfolio_margin_scale)

    out: dict[str, dict[str, Any]] = {}
    total_target_margin = Decimal("0")
    total_target_notional = Decimal("0")

    for sym, info in prelim.items():
        fixed = info["fixed"]
        side_key = info["side_key"]
        desired_side_num = info["desired_side_num"]
        symbol_scale = info["symbol_scale"]
        signal_scale = info["signal_scale"]
        total_scale = info["total_scale"]
        target_leverage = info["target_leverage"]
        leverage_reason = info["leverage_reason"]
        leverage_clamp_note = info["leverage_clamp_note"]
        active = bool(info["active"])

        clamp_note_parts = []
        margin_cap_note = str(info["margin_cap_note"] or "")
        if margin_cap_note:
            clamp_note_parts.append(margin_cap_note)

        if desired_side_num == 0:
            target_margin = Decimal("0")
            target_notional = Decimal("0")
            resolved_mode = "flat_target_zero"
        elif active:
            target_margin = info["target_margin_pre"] * portfolio_margin_scale
            if portfolio_margin_scale < Decimal("0.999999"):
                clamp_note_parts.append("scale=portfolio_margin_cap")
            target_notional = target_margin * target_leverage
            if max_notional > 0 and target_notional > max_notional:
                target_notional = max_notional
                target_margin = target_notional / max(target_leverage, Decimal("1"))
                clamp_note_parts.append("cap=max_notional")
            if min_notional > 0 and target_notional < min_notional:
                target_notional = min_notional
                target_margin = target_notional / max(target_leverage, Decimal("1"))
                clamp_note_parts.append("cap=min_notional")
            resolved_mode = "dynamic_equity_slices"
        else:
            target_notional = fixed
            target_margin = target_notional / max(target_leverage, Decimal("1"))
            resolved_mode = "fixed_notional"

        clamp_note = ";".join([x for x in clamp_note_parts if x])
        total_target_margin += target_margin
        total_target_notional += target_notional

        out[sym] = {
            "mode": resolved_mode,
            "desired_side": side_key.upper(),
            "fallback_notional_usdt": format_decimal(fixed),
            "symbol_scale": format_decimal(symbol_scale),
            "signal_scale": format_decimal(signal_scale),
            "total_scale": format_decimal(total_scale),
            "target_margin_usdt": format_decimal(target_margin),
            "target_notional_usdt": format_decimal(target_notional),
            "capital_slices": capital_slices,
            "basis_label": snap.get("basis_label"),
            "basis_equity_usdt": format_decimal(basis_eq),
            "usable_equity_usdt": format_decimal(usable_eq),
            "account_leverage": format_decimal(default_leverage),
            "target_leverage": format_decimal(target_leverage),
            "leverage_mode": leverage_mode,
            "leverage_reason": leverage_reason,
            "leverage_clamp_note": leverage_clamp_note,
            "portfolio_margin_scale_factor": format_decimal(portfolio_margin_scale),
            "per_symbol_margin_cap_usdt": format_decimal(per_symbol_margin_cap),
            "total_margin_cap_usdt": format_decimal(total_margin_cap),
            "clamp_note": clamp_note,
        }

    summary["total_target_margin_usdt"] = format_decimal(total_target_margin)
    summary["total_target_notional_usdt"] = format_decimal(total_target_notional)
    return out, summary
