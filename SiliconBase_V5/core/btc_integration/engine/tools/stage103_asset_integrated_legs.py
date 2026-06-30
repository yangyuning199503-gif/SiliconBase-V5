from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import research_config_baseline as rcb

DEFAULT_CFG_NAME = "config_shortwave_asset_integrated.yml"
DEFAULT_SHADOW_NAME = "shadow_shortwave_asset_integrated.yml"


def _expand(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v in (None, "", "-"):
            return default
        return float(v)
    except Exception:
        return default


def _fmt_pct(v: Any) -> str:
    if v in (None, "", "-"):
        return "-"
    try:
        return f"{float(v) * 100:.2f}%"
    except Exception:
        return "-"


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


def _read_stage91_json(root: Path) -> dict[str, Any]:
    p = root / "reports" / "research_raw" / "stage91_branch_event_alpha_matrix_latest.json"
    if not p.exists():
        raise SystemExit(f"缺少 {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def _asset_index(stage91: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item in stage91.get("asset_summary", []) or []:
        if not isinstance(item, dict):
            continue
        sym = str(item.get("symbol") or "").strip().lower()
        if sym:
            out[sym] = item
    return out


def _recent_metrics(row: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(row, dict):
        return {}
    dom = row.get("dominant_gate") or {}
    if isinstance(dom, dict):
        return dom.get("recent_metrics") or {}
    return {}


def _wf_metrics(row: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(row, dict):
        return {}
    wf = row.get("walkforward") or {}
    if isinstance(wf, dict):
        return wf.get("metrics") or {}
    return {}


def _row_trades_ok(row: dict[str, Any] | None, min_recent: int = 3, min_wf: int = 3) -> bool:
    recent = _recent_metrics(row)
    wf = _wf_metrics(row)
    return int(recent.get("trades", 0) or 0) >= min_recent and int(wf.get("trades", 0) or 0) >= min_wf


def _pick_btc_runtime_leg(asset_item: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    active = asset_item.get("active")
    dual_best = asset_item.get("dual_best")
    long_best = asset_item.get("long_best")
    short_best = asset_item.get("short_best")

    if _row_trades_ok(active):
        return active, "active_ok"
    if _row_trades_ok(dual_best, min_recent=8, min_wf=6):
        return dual_best, "active_thin_use_dual_best"
    if _row_trades_ok(short_best, min_recent=4, min_wf=4):
        return short_best, "active_thin_use_short_best"
    if _row_trades_ok(long_best, min_recent=8, min_wf=6):
        return long_best, "active_thin_use_long_best"
    return active or dual_best or short_best or long_best, "fallback_any"


def _pick_eth_runtime_leg(asset_item: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    active = asset_item.get("active")
    short_best = asset_item.get("short_best")
    return active or short_best, "eth_keep_active"


def _latest_common_end(root: Path, symbols: list[str], csv_template: str, fallback: str) -> str:
    ends: list[pd.Timestamp] = []
    for sym in symbols:
        path = root / Path(csv_template.format(symbol=sym))
        if not path.exists():
            continue
        try:
            df = pd.read_csv(path, usecols=[0])
            if df.empty:
                continue
            ts = pd.to_datetime(df.iloc[-1, 0], utc=True, errors="coerce")
            if pd.isna(ts):
                continue
            ends.append(ts)
        except Exception:
            continue
    if not ends:
        return fallback
    end = min(ends)
    return end.tz_convert("UTC").strftime("%Y-%m-%d")


def build_preview(project_dir: Path, submit_orders: bool = True) -> dict[str, Any]:
    root = project_dir.resolve()
    stage91 = _read_stage91_json(root)
    asset_map = _asset_index(stage91)

    if "btc" not in asset_map or "eth" not in asset_map:
        raise SystemExit("stage91 资产腿结果里缺 BTC 或 ETH")

    btc_item = asset_map["btc"]
    eth_item = asset_map["eth"]
    sol_item = asset_map.get("sol")

    btc_runtime, btc_reason = _pick_btc_runtime_leg(btc_item)
    eth_runtime, eth_reason = _pick_eth_runtime_leg(eth_item)

    base_cfg_path = rcb.locate_research_base_yaml(root)
    base_cfg = _load_yaml(base_cfg_path)
    shadow_path = root / "shadow.yml"
    shadow_doc = _load_yaml(shadow_path)
    shadow_base = shadow_doc.get("shadow", shadow_doc) if isinstance(shadow_doc, dict) else {}

    cfg = copy.deepcopy(base_cfg)
    cfg.setdefault("system", {})
    cfg["system"]["version"] = "r248_main_demo_pnl_split_live_base__btc_eth_asset_integrated_v1"
    cfg["system"]["strategy"] = "branch_shortwave_demo_asset_integrated"
    cfg["system"]["note"] = (
        "第二分支资产腿整体预览：BTC 多空一体 + ETH short 主导；6年总样本仅作软约束，判断以近2年 + WF 为主；"
        "重大事件不单独定方向，只和技术结构 / 资金拥挤 / 衍生品确认共同放行。"
    )

    cfg.setdefault("data", {})
    cfg["data"]["symbols"] = ["btc", "eth"]
    cfg["data"]["weights"] = {"btc": 0.35, "eth": 0.65}
    csv_template = str(cfg["data"].get("csv_template", "data/raw/{symbol}_15m.csv"))
    cfg["data"]["end"] = _latest_common_end(root, ["btc", "eth"], csv_template, str(cfg["data"].get("end", "2026-01-31")))

    sp = cfg.setdefault("strategy_params", {})
    sp["allow_short"] = True
    sp["long_symbols"] = ["btc"]
    sp["short_symbols"] = ["btc", "eth"]
    sp["pyramiding_symbols"] = []
    sp["breakout_lookback"] = 18
    sp["breakout_atr_buffer"] = 0.55
    sp["cooldown_bars"] = 6

    filters = cfg.setdefault("filters", {})
    filters["adx_floor"] = 22
    filters["macro_gate_symbols"] = ["btc", "eth"]
    macro_tf = filters.get("macro_gate_tf_by_symbol") if isinstance(filters.get("macro_gate_tf_by_symbol"), dict) else {}
    macro_tf["btc"] = "4h"
    macro_tf["eth"] = "4h"
    filters["macro_gate_tf_by_symbol"] = macro_tf
    filters["macro_gate_reference_symbol"] = "btc"
    filters["btc_adx_floor"] = 24
    filters["btc_breakout_atr_buffer"] = 0.60
    filters["btc_short_entry_mode"] = "pullback"
    filters["btc_short_pullback_atr"] = 1.00
    filters["btc_short_adx_floor"] = 24
    filters["btc_short_require_di"] = False
    filters["btc_short_sr_lookback_4h"] = 24
    filters["btc_short_macro_tf"] = "4h"

    sr = cfg.setdefault("sr_entries", {})
    sr["enabled"] = True
    sr["symbols"] = ["btc"]
    sr["lookback_4h"] = 24
    sr["zone_atr_mult"] = 0.30
    sr["take_profit_pct"] = 0.0
    sr["require_di"] = False
    sr["use_adx_filter"] = True
    sr["adx_min"] = 0.0
    sr["adx_max"] = 26.0
    sr["stake_scale"] = 0.35
    sr["cooldown_bars"] = 8
    sr["require_compress_ok"] = True

    mm = cfg.setdefault("money_management", {})
    mm["mode"] = "fixed_tranche"
    mm["capital_slices"] = 8
    mm["stake_mode"] = "dynamic_equity"
    mm["stake_min_usd"] = 2000
    mm["stake_max_usd"] = 120000
    stake_scale = mm.get("stake_scale") if isinstance(mm.get("stake_scale"), dict) else {}
    stake_scale["btc_long"] = 0.28
    stake_scale["btc_short"] = 0.42
    stake_scale["eth_short"] = 0.78
    stake_scale["eth_long"] = 0.18
    mm["stake_scale"] = stake_scale
    risk_on = mm.setdefault("risk_on", {})
    risk_on["enabled"] = False
    risk_on["symbols"] = []
    risk_on["sides"] = []

    eg = cfg.setdefault("execution_guard", {})
    eg["enabled"] = True
    eg["symbols"] = ["btc", "eth"]

    funding = cfg.setdefault("funding", {})
    fixed_bps = funding.get("fixed_bps_per_event") if isinstance(funding.get("fixed_bps_per_event"), dict) else {}
    fixed_bps.setdefault("default", 0.0)
    fixed_bps["btc"] = 0.0
    fixed_bps["eth"] = 0.0
    funding["fixed_bps_per_event"] = fixed_bps

    shadow = copy.deepcopy(shadow_base)
    shadow["submit_orders"] = bool(submit_orders)
    contracts = shadow.setdefault("contracts", {})
    contracts.setdefault("btc", "BTC-USDT-SWAP")
    contracts.setdefault("eth", "ETH-USDT-SWAP")
    exec_step = shadow.setdefault("execution_step", {})
    notional_map = exec_step.get("notional_usdt_by_symbol") if isinstance(exec_step.get("notional_usdt_by_symbol"), dict) else {}
    notional_map["btc"] = float(notional_map.get("btc", 20.0) or 20.0)
    notional_map["eth"] = float(notional_map.get("eth", 20.0) or 20.0)
    exec_step["notional_usdt_by_symbol"] = notional_map
    sizing = exec_step.setdefault("sizing", {})
    lev_by_symbol = sizing.get("leverage_by_symbol") if isinstance(sizing.get("leverage_by_symbol"), dict) else {}
    lev_by_symbol["btc"] = 7
    lev_by_symbol["eth"] = 6
    sizing["leverage_by_symbol"] = lev_by_symbol
    lev_by_signal = sizing.get("leverage_by_signal") if isinstance(sizing.get("leverage_by_signal"), dict) else {}
    lev_by_signal["btc_short"] = 8
    lev_by_signal["btc_long"] = 7
    lev_by_signal["eth_short"] = 6
    sizing["leverage_by_signal"] = lev_by_signal
    ap = shadow.setdefault("autopilot", {})
    ap["public_report_txt"] = "~/Downloads/branch_demo_report_latest.txt"

    out_cfg = root / DEFAULT_CFG_NAME
    out_shadow = root / DEFAULT_SHADOW_NAME
    _write_yaml(out_cfg, cfg)
    if isinstance(shadow_doc, dict) and "shadow" in shadow_doc:
        shadow_doc_out = copy.deepcopy(shadow_doc)
        shadow_doc_out["shadow"] = shadow
        _write_yaml(out_shadow, shadow_doc_out)
    else:
        _write_yaml(out_shadow, shadow)

    raw = root / "reports" / "research_raw"
    raw.mkdir(parents=True, exist_ok=True)
    out_txt = raw / "stage103_asset_integrated_latest.txt"
    out_json = raw / "stage103_asset_integrated_latest.json"

    btc_recent = _recent_metrics(btc_runtime)
    btc_wf = _wf_metrics(btc_runtime)
    eth_recent = _recent_metrics(eth_runtime)
    eth_wf = _wf_metrics(eth_runtime)
    sol_mode = str((sol_item or {}).get("mode") or "research_only") if sol_item else "missing"

    lines: list[str] = []
    lines.append("Stage103 资产腿整体设计")
    lines.append("原则：主线和支线一起调整；第二分支不是散腿，而是一个整体波段 book。")
    lines.append("规则：6年整体仅作软约束；判断以近2年 + WF 为主；BTC 多空都保留，ETH 先保留 short 主导，SOL 继续 research_only。")
    lines.append("")
    lines.append(f"generated_at_utc={datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append("")
    lines.append("=== 当前预览配置 ===")
    lines.append(f"- config: {out_cfg}")
    lines.append(f"- shadow: {out_shadow}")
    lines.append("- symbols: btc, eth")
    lines.append("- weights: btc=0.35 / eth=0.65")
    lines.append(f"- data.end: {cfg['data'].get('end')}")
    lines.append("")
    lines.append("=== BTC 腿 ===")
    lines.append(f"- stage91_mode={btc_item.get('mode')} | runtime_pick_reason={btc_reason}")
    lines.append(f"- runtime_leg={btc_runtime.get('name') if isinstance(btc_runtime, dict) else '-'}")
    lines.append(f"- recent: 收益={_fmt_pct(btc_recent.get('ret'))} PF={_safe_float(btc_recent.get('pf')):.3f} 交易={int(btc_recent.get('trades',0) or 0)}")
    lines.append(f"- wf: 收益={_fmt_pct(btc_wf.get('ret'))} PF={_safe_float(btc_wf.get('pf')):.3f} 交易={int(btc_wf.get('trades',0) or 0)}")
    lines.append("- runtime_design=BTC 多空一体：trend + pullback short + SR reclaim；但因当前 recent/WF 站得不够硬，先低权重接入。"
                 )
    lines.append("")
    lines.append("=== ETH 腿 ===")
    lines.append(f"- stage91_mode={eth_item.get('mode')} | runtime_pick_reason={eth_reason}")
    lines.append(f"- runtime_leg={eth_runtime.get('name') if isinstance(eth_runtime, dict) else '-'}")
    lines.append(f"- recent: 收益={_fmt_pct(eth_recent.get('ret'))} PF={_safe_float(eth_recent.get('pf')):.3f} 交易={int(eth_recent.get('trades',0) or 0)}")
    lines.append(f"- wf: 收益={_fmt_pct(eth_wf.get('ret'))} PF={_safe_float(eth_wf.get('pf')):.3f} 交易={int(eth_wf.get('trades',0) or 0)}")
    lines.append("- runtime_design=ETH 先保留 short 主导；不因为 BTC 加入就砍掉 ETH short fast。")
    lines.append("")
    lines.append("=== SOL 腿 ===")
    lines.append(f"- stage91_mode={sol_mode}")
    lines.append("- runtime_design=继续 research_only，不自动接入当前第二分支 demo。")
    lines.append("")
    lines.append("=== 结论 ===")
    lines.append("- 已把 BTC 多空策略正式接回第二分支设计链路，但默认先做 preview，不自动替换当前正在跑的 ETH branch demo。")
    lines.append("- 若你确认切 branch demo，再执行 switch_branch_demo_to_asset_integrated.sh --restart。")
    out_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "config_path": str(out_cfg),
        "shadow_path": str(out_shadow),
        "selected_symbols": ["btc", "eth"],
        "weights": {"btc": 0.35, "eth": 0.65},
        "btc": {
            "stage91_mode": btc_item.get("mode"),
            "runtime_pick_reason": btc_reason,
            "runtime_leg": btc_runtime,
            "long_best": btc_item.get("long_best"),
            "short_best": btc_item.get("short_best"),
            "dual_best": btc_item.get("dual_best"),
        },
        "eth": {
            "stage91_mode": eth_item.get("mode"),
            "runtime_pick_reason": eth_reason,
            "runtime_leg": eth_runtime,
            "long_best": eth_item.get("long_best"),
            "short_best": eth_item.get("short_best"),
            "dual_best": eth_item.get("dual_best"),
        },
        "sol": {
            "stage91_mode": sol_mode,
            "asset_summary": sol_item,
        },
    }
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "ok": True,
        "config": str(out_cfg),
        "shadow": str(out_shadow),
        "summary_txt": str(out_txt),
        "summary_json": str(out_json),
        "btc_reason": btc_reason,
        "eth_reason": eth_reason,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage103 资产腿整体设计预览")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--submit-orders", dest="submit_orders", action="store_true")
    ap.add_argument("--no-submit-orders", dest="submit_orders", action="store_false")
    ap.set_defaults(submit_orders=True)
    args = ap.parse_args()
    result = build_preview(_expand(args.project_dir), submit_orders=bool(args.submit_orders))
    print(yaml.safe_dump(result, allow_unicode=True, sort_keys=False).strip())


if __name__ == "__main__":
    main()
