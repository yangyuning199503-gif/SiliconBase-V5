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

DEFAULT_CANDIDATE = "combo_sr_soft_adx26_cd6_lb24_zone028_ref"
DEFAULT_REPORT = "reports/research_raw/mainline_shadow_demo_report_latest.txt"
DEFAULT_PREFIX = "okxs"

CANDIDATES: dict[str, dict[str, Any]] = {
    "mainline_live_base": {
        "name": "mainline_live_base",
        "note": "当前 live 主线，对照组",
        "mods": {},
    },
    "combo_sr_soft_adx26_cd6_lb24_zone028_ref": {
        "name": "combo_sr_soft_adx26_cd6_lb24_zone028_ref",
        "note": "稳健提频 shadow：保持结构不变，只在 SR/structure 上提频。",
        "mods": {
            "sr_entries.enabled": True,
            "sr_entries.symbols": ["bnb"],
            "sr_entries.lookback_4h": 24,
            "sr_entries.zone_atr_mult": 0.28,
            "sr_entries.use_adx_filter": True,
            "sr_entries.adx_min": 0.0,
            "sr_entries.adx_max": 26.0,
            "sr_entries.stake_scale": 0.15,
            "sr_entries.cooldown_bars": 6,
            "sr_entries.require_compress_ok": True,
            "filters.btc_short_pullback_atr": 0.9,
            "filters.btc_short_macro_tf": "4h",
        },
    },
    "combo_sr_soft_adx28_cd6_lb24_zone028": {
        "name": "combo_sr_soft_adx28_cd6_lb24_zone028",
        "note": "激进但仍可解释的提频版。",
        "mods": {
            "sr_entries.enabled": True,
            "sr_entries.symbols": ["bnb"],
            "sr_entries.lookback_4h": 24,
            "sr_entries.zone_atr_mult": 0.28,
            "sr_entries.use_adx_filter": True,
            "sr_entries.adx_min": 0.0,
            "sr_entries.adx_max": 28.0,
            "sr_entries.stake_scale": 0.15,
            "sr_entries.cooldown_bars": 6,
            "sr_entries.require_compress_ok": True,
            "filters.btc_short_pullback_atr": 0.9,
            "filters.btc_short_macro_tf": "4h",
        },
    },
    "combo_sr_soft_adx32_cd5_lb20_zone025": {
        "name": "combo_sr_soft_adx32_cd5_lb20_zone025",
        "note": "最激进前沿，只放 shadow/research。",
        "mods": {
            "sr_entries.enabled": True,
            "sr_entries.symbols": ["bnb"],
            "sr_entries.lookback_4h": 20,
            "sr_entries.zone_atr_mult": 0.25,
            "sr_entries.use_adx_filter": True,
            "sr_entries.adx_min": 0.0,
            "sr_entries.adx_max": 32.0,
            "sr_entries.stake_scale": 0.15,
            "sr_entries.cooldown_bars": 5,
            "sr_entries.require_compress_ok": True,
            "filters.btc_short_pullback_atr": 0.9,
            "filters.btc_short_macro_tf": "4h",
        },
    },
}


def _expand_path(base: Path, value: str | Path) -> Path:
    raw = Path(str(value)).expanduser()
    if raw.is_absolute():
        return raw.resolve()
    return (base / raw).resolve()


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


def build_mainline_shadow_candidate(project_dir: Path, candidate_name: str, report_txt: str, order_prefix: str, submit_orders: bool) -> dict[str, Any]:
    project_dir = project_dir.resolve()
    cfg_path = rcb.locate_research_base_yaml(project_dir)
    shadow_path = project_dir / "shadow.yml"
    out_cfg_path = project_dir / "config_mainline_shadow_candidate.yml"
    out_shadow_path = project_dir / "shadow_mainline_shadow_candidate.yml"

    item = copy.deepcopy(CANDIDATES.get(candidate_name))
    if not item:
        raise SystemExit(f"未找到主线 shadow 候选: {candidate_name}")

    cfg = _load_yaml(cfg_path)
    shadow_doc = _load_yaml(shadow_path)
    shadow = shadow_doc.get("shadow", shadow_doc) if isinstance(shadow_doc, dict) else {}

    cfg_out = copy.deepcopy(cfg)
    cfg_out.setdefault("system", {})
    cfg_out["system"]["version"] = f"mainline_shadow_demo__{candidate_name}"
    cfg_out["system"]["strategy"] = "mainline_shadow_demo"
    cfg_out["system"]["note"] = (
        "主线 shadow 独立 Demo；production 仍保留 mainline_live_base；"
        "提频只沿 SR/structure 微调，不做全局放松；6年总样本只作软约束，判断以近2年 + WF 为主。"
    )
    cfg_out.setdefault("data", {})
    cfg_out["data"]["symbols"] = ["btc", "bnb"]
    cfg_out["data"]["weights"] = {"btc": 0.015, "bnb": 0.985}
    for dotted, value in (item.get("mods") or {}).items():
        _set_dotted(cfg_out, str(dotted), value)

    shadow_out = copy.deepcopy(shadow)
    shadow_out["submit_orders"] = bool(submit_orders)
    exec_step = shadow_out.setdefault("execution_step", {})
    exec_step["clord_prefix"] = ("".join(ch for ch in str(order_prefix) if ch.isalnum()).lower()[:12] or DEFAULT_PREFIX)
    notional_map = exec_step.get("notional_usdt_by_symbol") if isinstance(exec_step.get("notional_usdt_by_symbol"), dict) else {}
    notional_map.setdefault("btc", float(exec_step.get("default_notional_usdt", 20.0) or 20.0))
    notional_map.setdefault("bnb", float(exec_step.get("default_notional_usdt", 20.0) or 20.0))
    exec_step["notional_usdt_by_symbol"] = notional_map

    report_path = _expand_path(project_dir, report_txt)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    ap = shadow_out.setdefault("autopilot", {})
    ap["public_report_txt"] = str(report_path)
    ap.setdefault("display_timezone", "Asia/Shanghai")
    ap.setdefault("display_tz_label", "UTC+8")
    cg = ap.setdefault("coinglass", {})
    cg.setdefault("enabled", True)
    cg.setdefault("enforcement", "shadow_only")
    cg.setdefault("fomc_pause_lead_minutes", 360)
    cg.setdefault("fomc_pause_post_minutes", 180)

    _write_yaml(out_cfg_path, cfg_out)
    if isinstance(shadow_doc, dict) and "shadow" in shadow_doc:
        shadow_doc["shadow"] = shadow_out
        _write_yaml(out_shadow_path, shadow_doc)
    else:
        _write_yaml(out_shadow_path, shadow_out)

    return {
        "ok": True,
        "candidate": candidate_name,
        "config": str(out_cfg_path),
        "shadow": str(out_shadow_path),
        "report": str(report_path),
        "order_prefix": exec_step["clord_prefix"],
        "submit_orders": bool(submit_orders),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="生成主线 shadow 独立 Demo 候选配置")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--candidate", default=DEFAULT_CANDIDATE)
    ap.add_argument("--report-txt", default=DEFAULT_REPORT)
    ap.add_argument("--order-prefix", default=DEFAULT_PREFIX)
    ap.add_argument("--submit-orders", dest="submit_orders", action="store_true")
    ap.add_argument("--no-submit-orders", dest="submit_orders", action="store_false")
    ap.set_defaults(submit_orders=True)
    args = ap.parse_args()
    result = build_mainline_shadow_candidate(
        project_dir=_expand_path(Path.cwd(), args.project_dir),
        candidate_name=str(args.candidate),
        report_txt=str(args.report_txt),
        order_prefix=str(args.order_prefix),
        submit_orders=bool(args.submit_orders),
    )
    print(yaml.safe_dump(result, allow_unicode=True, sort_keys=False).strip())


if __name__ == "__main__":
    main()
