from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path
from typing import Any

import yaml

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import research_config_baseline as rcb
from tools import stage76_branch_event_state_lab as s76

DEFAULT_CANDIDATE = "eth_short_shock_fast_lb16_atr052_adx22_s078"
DEFAULT_REPORT = "~/Downloads/branch_demo_report_latest.txt"
DEFAULT_PREFIX = "okxb"


def _expand_path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _set_dotted(root: dict[str, Any], dotted: str, value: Any) -> None:
    keys = [x for x in str(dotted).split(".") if x]
    if not keys:
        return
    cur: dict[str, Any] = root
    for key in keys[:-1]:
        nxt = cur.get(key)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[key] = nxt
        cur = nxt
    cur[keys[-1]] = copy.deepcopy(value)


def _candidate_map() -> dict[str, dict[str, Any]]:
    return {str(item.get("name")): copy.deepcopy(item) for item in s76._candidate_items()}


def build_branch_candidate(project_dir: Path, candidate_name: str, report_txt: str, order_prefix: str, submit_orders: bool) -> dict[str, Any]:
    project_dir = project_dir.resolve()
    cfg_path = rcb.locate_research_base_yaml(project_dir)
    shadow_path = project_dir / "shadow.yml"
    out_cfg_path = project_dir / "config_shortwave_candidate.yml"
    out_shadow_path = project_dir / "shadow_shortwave_candidate.yml"

    candidates = _candidate_map()
    item = candidates.get(candidate_name)
    if not item:
        raise SystemExit(f"未找到分支候选: {candidate_name}")

    symbol = str(item.get("symbol") or "eth").lower()
    family = str(item.get("family") or "short").lower()
    side_key = f"{symbol}_{family}"

    cfg = _load_yaml(cfg_path)
    shadow_doc = _load_yaml(shadow_path)
    shadow = shadow_doc.get("shadow", shadow_doc)

    cfg_out = copy.deepcopy(cfg)
    cfg_out.setdefault("system", {})
    base_version = str(cfg_out["system"].get("version") or "branch_demo")
    cfg_out["system"]["version"] = f"{base_version}__{candidate_name}"
    cfg_out["system"]["strategy"] = "branch_shortwave_demo"
    cfg_out["system"]["note"] = (
        "分支独立 Demo 候选；6年总样本仅作软约束，判断以近2年 + walk-forward 为主；"
        "消息面/FOMC 仅做 risk layer / overlay，不直接当方向 alpha。"
    )
    cfg_out.setdefault("data", {})
    cfg_out["data"]["symbols"] = [symbol]
    cfg_out["data"]["weights"] = {symbol: 1.0}
    cfg_out.setdefault("filters", {})
    cfg_out["filters"]["macro_gate_symbols"] = [symbol]
    macro_tf = cfg_out["filters"].get("macro_gate_tf_by_symbol")
    if not isinstance(macro_tf, dict):
        macro_tf = {}
    macro_tf.setdefault(symbol, "4h")
    cfg_out["filters"]["macro_gate_tf_by_symbol"] = macro_tf
    cfg_out["filters"].setdefault("macro_gate_reference_symbol", "btc")

    for dotted, value in (item.get("mods") or {}).items():
        _set_dotted(cfg_out, str(dotted), value)

    mm = cfg_out.setdefault("money_management", {})
    stake_scale = mm.get("stake_scale") if isinstance(mm.get("stake_scale"), dict) else {}
    if side_key not in stake_scale:
        stake_scale[side_key] = 0.74 if family == "short" else 0.38
    mm["stake_scale"] = stake_scale

    shadow_out = copy.deepcopy(shadow)
    shadow_out["submit_orders"] = bool(submit_orders)
    shadow_out.setdefault("contracts", {})
    for sym in ["btc", "bnb", "eth", "sol", "xrp", "ada", "doge", "dot"]:
        shadow_out["contracts"].setdefault(sym, f"{sym.upper()}-USDT-SWAP")
    exec_step = shadow_out.setdefault("execution_step", {})
    notional_map = exec_step.get("notional_usdt_by_symbol") if isinstance(exec_step.get("notional_usdt_by_symbol"), dict) else {}
    notional_map.setdefault(symbol, float(exec_step.get("default_notional_usdt", 20.0) or 20.0))
    exec_step["notional_usdt_by_symbol"] = notional_map
    exec_step["clord_prefix"] = ("".join(ch for ch in str(order_prefix) if ch.isalnum()).lower()[:12] or DEFAULT_PREFIX)

    ap = shadow_out.setdefault("autopilot", {})
    ap["public_report_txt"] = report_txt
    ap.setdefault("display_timezone", "Asia/Shanghai")
    ap.setdefault("display_tz_label", "UTC+8")
    cg = ap.setdefault("coinglass", {})
    cg.setdefault("enabled", True)
    cg.setdefault("enforcement", "shadow_only")
    cg.setdefault("fomc_pause_lead_minutes", 360)
    cg.setdefault("fomc_pause_post_minutes", 180)
    macro_keywords = list(cg.get("macro_keywords") or [])
    for kw in ["fomc", "federal reserve", "jerome powell", "powell", "rate decision", "dot plot", "interest rate"]:
        if kw not in macro_keywords:
            macro_keywords.append(kw)
    cg["macro_keywords"] = macro_keywords
    news_keywords = list(cg.get("news_pause_keywords") or [])
    for kw in ["fomc", "fed", "powell", "dot plot", "rate decision"]:
        if kw not in news_keywords:
            news_keywords.append(kw)
    cg["news_pause_keywords"] = news_keywords

    _write_yaml(out_cfg_path, cfg_out)
    if isinstance(shadow_doc, dict) and "shadow" in shadow_doc:
        shadow_doc["shadow"] = shadow_out
        _write_yaml(out_shadow_path, shadow_doc)
    else:
        _write_yaml(out_shadow_path, shadow_out)

    return {
        "ok": True,
        "candidate": candidate_name,
        "symbol": symbol,
        "family": family,
        "config": str(out_cfg_path),
        "shadow": str(out_shadow_path),
        "report": str(_expand_path(report_txt)),
        "order_prefix": exec_step["clord_prefix"],
        "submit_orders": bool(submit_orders),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="生成分支独立 Demo 候选配置")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--candidate", default=DEFAULT_CANDIDATE)
    ap.add_argument("--report-txt", default=DEFAULT_REPORT)
    ap.add_argument("--order-prefix", default=DEFAULT_PREFIX)
    ap.add_argument("--submit-orders", dest="submit_orders", action="store_true")
    ap.add_argument("--no-submit-orders", dest="submit_orders", action="store_false")
    ap.set_defaults(submit_orders=True)
    args = ap.parse_args()
    result = build_branch_candidate(
        project_dir=_expand_path(args.project_dir),
        candidate_name=str(args.candidate),
        report_txt=str(args.report_txt),
        order_prefix=str(args.order_prefix),
        submit_orders=bool(args.submit_orders),
    )
    print(yaml.safe_dump(result, allow_unicode=True, sort_keys=False).strip())


if __name__ == "__main__":
    main()
