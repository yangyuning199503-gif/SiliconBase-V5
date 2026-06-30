from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import research_config_baseline as rcb
from tools import stage46_aggressive_lab as s46
from tools import stage77_mainline_dual_window_lab as s77
from tools import stage88_strategy_fusion_walkforward as s88
from tools import stage90_event_alpha_matrix as s90
from tools import stage136_regime_plateau_frontier as s136
from tools import stage141_guarded_asymmetry_shortlist as s141
from tools import stage161_mainline_risk_budget_multiasset_link_frontier as s161
from tools import stage185_target_monthly_focus_frontier as s185

TARGET_MONTHLY_MIN = float(getattr(s185, "TARGET_MONTHLY_MIN", 0.076))
TARGET_MONTHLY_MAX = float(getattr(s185, "TARGET_MONTHLY_MAX", 0.114))


SAFE_FLOAT = s185._safe_float
SAFE_INT = s185._safe_int
WITH_META = s185._with_meta
RECENT_METRICS = s185._recent_metrics
WF_METRICS = s185._wf_metrics
FULL_METRICS = s185._full_metrics
SYMBOL = s185._symbol
FAMILY = s185._family
PLAYBOOK = s185._playbook
HARD_BLACKLISTED = s185._hard_blacklisted
WRITE_SINGLE_ZIP = s185._write_single_zip


def _load_live_cfg(root: Path) -> dict[str, Any]:
    candidates = [
        root / "config.yml",
        root / "config_mainline_dynlev_fix8_lock18.yml",
    ]
    if yaml is not None:
        for path in candidates:
            try:
                if path.exists():
                    data = yaml.safe_load(path.read_text(encoding="utf-8"))
                    if isinstance(data, dict) and data:
                        return data
            except Exception:
                pass
    return rcb.load_research_base_config(root)


_RUNTIME_CANDIDATE_RE = re.compile(r"- 当前候选: (?P<name>[^\n]+)")
_RUNTIME_6Y_RE = re.compile(r"- 6年总样本: 收益=(?P<ret>-?[0-9.]+)%.*?回撤=(?P<dd>-?[0-9.]+)%.*?交易=(?P<trades>[0-9]+).*?PF=(?P<pf>-?[0-9.]+)")
_RUNTIME_2Y_RE = re.compile(r"- 近2年样本: 收益=(?P<ret>-?[0-9.]+)% \| 月化=(?P<monthly>-?[0-9.]+)%.*?回撤=(?P<dd>-?[0-9.]+)%.*?交易=(?P<trades>[0-9]+).*?PF=(?P<pf>-?[0-9.]+)")
_RUNTIME_WF_RE = re.compile(r"- WF样本外: 收益=(?P<ret>-?[0-9.]+)% \| 月化=(?P<monthly>-?[0-9.]+)%.*?回撤=(?P<dd>-?[0-9.]+)%.*?交易=(?P<trades>[0-9]+).*?PF=(?P<pf>-?[0-9.]+)")
_BRANCH_ASSET_RE = re.compile(
    r"- (?P<sym>BTC|ETH|SOL): mode=(?P<mode>[^|]+) \| active=(?P<active>[^|]+) \| 近2年 收益=(?P<recent_ret>-?[0-9.]+)% \| 交易=(?P<recent_trades>[0-9]+) \| PF=(?P<recent_pf>-?[0-9.]+) \| WF 收益=(?P<wf_ret>-?[0-9.]+)% \| 交易=(?P<wf_trades>[0-9]+) \| PF=(?P<wf_pf>-?[0-9.]+) \| 回撤=(?P<wf_dd>-?[0-9.]+)%"
)


def _parse_runtime_anchor(root: Path) -> dict[str, Any]:
    downloads = root.parent / "Downloads"
    out: dict[str, Any] = {"main": {}, "branch": {}}

    main_report = downloads / "okx_demo_report_latest.txt"
    if main_report.exists():
        text = main_report.read_text(encoding="utf-8", errors="ignore")
        cand = _RUNTIME_CANDIDATE_RE.search(text)
        if cand:
            out["main"]["name"] = cand.group("name").strip()
        m6 = _RUNTIME_6Y_RE.search(text)
        if m6:
            out["main"]["full_metrics"] = {
                "ret": SAFE_FLOAT(m6.group("ret")) / 100.0,
                "maxdd": SAFE_FLOAT(m6.group("dd")) / 100.0,
                "trades": SAFE_INT(m6.group("trades")),
                "pf": SAFE_FLOAT(m6.group("pf")),
            }
        m2 = _RUNTIME_2Y_RE.search(text)
        if m2:
            out["main"]["recent_metrics"] = {
                "ret": SAFE_FLOAT(m2.group("ret")) / 100.0,
                "monthlyized_ret": SAFE_FLOAT(m2.group("monthly")) / 100.0,
                "maxdd": SAFE_FLOAT(m2.group("dd")) / 100.0,
                "trades": SAFE_INT(m2.group("trades")),
                "pf": SAFE_FLOAT(m2.group("pf")),
            }
        mw = _RUNTIME_WF_RE.search(text)
        if mw:
            out["main"]["wf_metrics"] = {
                "ret": SAFE_FLOAT(mw.group("ret")) / 100.0,
                "monthlyized_ret": SAFE_FLOAT(mw.group("monthly")) / 100.0,
                "maxdd": SAFE_FLOAT(mw.group("dd")) / 100.0,
                "trades": SAFE_INT(mw.group("trades")),
                "pf": SAFE_FLOAT(mw.group("pf")),
            }

    branch_report = downloads / "branch_demo_report_latest.txt"
    if branch_report.exists():
        text = branch_report.read_text(encoding="utf-8", errors="ignore")
        branch: dict[str, Any] = {}
        for m in _BRANCH_ASSET_RE.finditer(text):
            sym = m.group("sym")
            branch[sym] = {
                "mode": m.group("mode").strip(),
                "active": m.group("active").strip(),
                "recent_ret": SAFE_FLOAT(m.group("recent_ret")) / 100.0,
                "recent_trades": SAFE_INT(m.group("recent_trades")),
                "recent_pf": SAFE_FLOAT(m.group("recent_pf")),
                "wf_ret": SAFE_FLOAT(m.group("wf_ret")) / 100.0,
                "wf_trades": SAFE_INT(m.group("wf_trades")),
                "wf_pf": SAFE_FLOAT(m.group("wf_pf")),
                "wf_dd": SAFE_FLOAT(m.group("wf_dd")) / 100.0,
            }
        out["branch"] = branch
    return out


def _runtime_adjusted_metrics(row: dict[str, Any], runtime_anchor: dict[str, Any], *, branch: bool) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    recent = dict(RECENT_METRICS(row))
    wf = dict(WF_METRICS(row))
    full = dict(FULL_METRICS(row))
    name = str(row.get("name") or "")
    if not branch:
        anchor = runtime_anchor.get("main") or {}
        if anchor.get("name") == name:
            recent.update(anchor.get("recent_metrics") or {})
            wf.update(anchor.get("wf_metrics") or {})
            full.update(anchor.get("full_metrics") or {})
        return recent, wf, full

    sym = SYMBOL(row, branch=True).upper()
    bmap = runtime_anchor.get("branch") or {}
    anchor = bmap.get(sym) if isinstance(bmap, dict) else None
    if isinstance(anchor, dict) and anchor.get("active") == name:
        recent.update({
            "ret": anchor.get("recent_ret", recent.get("ret")),
            "trades": anchor.get("recent_trades", recent.get("trades")),
            "pf": anchor.get("recent_pf", recent.get("pf")),
        })
        wf.update({
            "ret": anchor.get("wf_ret", wf.get("ret")),
            "trades": anchor.get("wf_trades", wf.get("trades")),
            "pf": anchor.get("wf_pf", wf.get("pf")),
            "maxdd": anchor.get("wf_dd", wf.get("maxdd")),
        })
    return recent, wf, full


def _score(row: dict[str, Any], runtime_anchor: dict[str, Any], *, branch: bool) -> float:
    recent, wf, full = _runtime_adjusted_metrics(row, runtime_anchor, branch=branch)
    name = str(row.get("name") or "")
    pb = PLAYBOOK(row)
    sym = SYMBOL(row, branch=branch)

    r_m = SAFE_FLOAT(recent.get("monthlyized_ret"))
    w_m = SAFE_FLOAT(wf.get("monthlyized_ret"))
    r_pf = SAFE_FLOAT(recent.get("pf"))
    w_pf = SAFE_FLOAT(wf.get("pf"))
    r_t = SAFE_INT(recent.get("trades"))
    w_t = SAFE_INT(wf.get("trades"))
    f_t = SAFE_INT(full.get("trades"))
    r_dd = abs(SAFE_FLOAT(recent.get("maxdd")))
    w_dd = abs(SAFE_FLOAT(wf.get("maxdd")))

    best_m = max(r_m, w_m)
    gap = max(TARGET_MONTHLY_MIN - best_m, 0.0)

    score = 150000.0 * r_m + 130000.0 * w_m
    score += 140.0 * min(r_pf, 8.0) + 120.0 * min(w_pf, 8.0)
    score += 10.0 * min(r_t, 120) + 8.0 * min(w_t, 90) + 1.5 * min(f_t, 500)
    score -= 135.0 * (r_dd * 100.0) + 120.0 * (w_dd * 100.0)
    score -= gap * 140000.0

    if pb in {"eth_event_drift", "eth_reclaim_beta", "eth_squeeze_follow"}:
        score += 220.0
    if pb == "eth_retest_short":
        score += 90.0
    if pb in {"btc_breakout_long", "btc_dual_hedge"}:
        score += 120.0
    if pb in {"sol_pullback_pair", "sol_range_ladder"}:
        score += 120.0
    if pb == "mainline_event_confirm":
        score += 140.0
    if pb in {"main_banded_reentry", "main_ladder_pyramid"}:
        score += 60.0

    penalty = 0.0
    if HARD_BLACKLISTED(name):
        penalty += 99999.0
    if "overlay_hold" in pb or "overlay_hold" in name.lower():
        penalty += 950.0
    if r_t < 8 or w_t < 6:
        penalty += 950.0
    if r_t <= 1 or w_t <= 1:
        penalty += 2200.0
    if r_pf < 1.0 or w_pf < 1.0:
        penalty += 380.0
    if best_m < 0.0025:
        penalty += 650.0
    if branch and sym == "btc" and ("break_fail" in name.lower() or "retest_pair" in name.lower()):
        penalty += 99999.0
    if branch and sym == "sol" and "short" in name.lower():
        penalty += 180.0
    return score - penalty


def _status(row: dict[str, Any], runtime_anchor: dict[str, Any], *, branch: bool) -> str:
    recent, wf, _ = _runtime_adjusted_metrics(row, runtime_anchor, branch=branch)
    name = str(row.get("name") or "")
    if HARD_BLACKLISTED(name):
        return "blacklist"
    r_m = SAFE_FLOAT(recent.get("monthlyized_ret"))
    w_m = SAFE_FLOAT(wf.get("monthlyized_ret"))
    r_pf = SAFE_FLOAT(recent.get("pf"))
    w_pf = SAFE_FLOAT(wf.get("pf"))
    r_t = SAFE_INT(recent.get("trades"))
    w_t = SAFE_INT(wf.get("trades"))
    if r_m >= 0.02 and w_m >= 0.015 and r_pf >= 1.40 and w_pf >= 1.25 and r_t >= 12 and w_t >= 8:
        return "focus"
    if r_m > 0 and w_m > 0 and r_pf >= 1.0 and w_pf >= 1.0:
        return "reserve"
    return "weak"


def _row_payload(row: dict[str, Any], runtime_anchor: dict[str, Any], *, branch: bool) -> dict[str, Any]:
    recent, wf, full = _runtime_adjusted_metrics(row, runtime_anchor, branch=branch)
    best_m = max(SAFE_FLOAT(recent.get("monthlyized_ret")), SAFE_FLOAT(wf.get("monthlyized_ret")))
    return {
        "name": str(row.get("name") or ""),
        "symbol": SYMBOL(row, branch=branch),
        "family": FAMILY(row),
        "playbook": PLAYBOOK(row),
        "alpha_score": SAFE_FLOAT(row.get("alpha_score")),
        "score": _score(row, runtime_anchor, branch=branch),
        "status": _status(row, runtime_anchor, branch=branch),
        "recent_monthly": SAFE_FLOAT(recent.get("monthlyized_ret")),
        "wf_monthly": SAFE_FLOAT(wf.get("monthlyized_ret")),
        "recent_ret": SAFE_FLOAT(recent.get("ret")),
        "wf_ret": SAFE_FLOAT(wf.get("ret")),
        "recent_pf": SAFE_FLOAT(recent.get("pf")),
        "wf_pf": SAFE_FLOAT(wf.get("pf")),
        "recent_trades": SAFE_INT(recent.get("trades")),
        "wf_trades": SAFE_INT(wf.get("trades")),
        "recent_maxdd": SAFE_FLOAT(recent.get("maxdd")),
        "wf_maxdd": SAFE_FLOAT(wf.get("maxdd")),
        "full_ret": SAFE_FLOAT(full.get("ret")),
        "full_pf": SAFE_FLOAT(full.get("pf")),
        "full_trades": SAFE_INT(full.get("trades")),
        "gap_to_floor": TARGET_MONTHLY_MIN - best_m,
    }


def _top_payload(rows: list[dict[str, Any]], runtime_anchor: dict[str, Any], *, branch: bool) -> list[dict[str, Any]]:
    payload = [_row_payload(r, runtime_anchor, branch=branch) for r in rows]
    payload.sort(key=lambda r: (r["score"], r["alpha_score"]), reverse=True)
    return payload


def _select_top(payload: list[dict[str, Any]], *, symbol: str | None = None, limit: int = 5) -> list[dict[str, Any]]:
    rows = payload
    if symbol:
        rows = [r for r in rows if r["symbol"] == symbol]
    return rows[:limit]


def _active_map_from_payload(branch_payload: list[dict[str, Any]], runtime_anchor: dict[str, Any]) -> dict[str, str]:
    out = {"BTC": "", "ETH": "", "SOL": ""}
    for sym in ["btc", "eth", "sol"]:
        top = next((r for r in branch_payload if r["symbol"] == sym and r["status"] != "blacklist"), None)
        if top is not None:
            out[sym.upper()] = top["name"]
    runtime_branch = runtime_anchor.get("branch") or {}
    if isinstance(runtime_branch, dict):
        for sym in ["BTC", "ETH", "SOL"]:
            if not out[sym]:
                anchor = runtime_branch.get(sym)
                if isinstance(anchor, dict):
                    out[sym] = str(anchor.get("active") or "")
    return out


def _split_recommendation(branch_payload: list[dict[str, Any]]) -> str:
    ready = 0
    for sym in ["btc", "eth", "sol"]:
        top = next((r for r in branch_payload if r["symbol"] == sym and r["status"] == "focus"), None)
        if top is not None:
            ready += 1
    return "consider_multi_terminal" if ready >= 2 else "keep_single_branch_terminal"


def _mainline_items() -> list[dict[str, Any]]:
    item_map = {str(item.get("name")): item for item in s88._mainline_items()}
    base = item_map.get("mainline_live_dynlev_fix8_lock18")
    if base is None:
        raise SystemExit("missing mainline_live_dynlev_fix8_lock18 base item")
    out: list[dict[str, Any]] = []

    def add(name: str, note: str, patch: dict[str, Any], track: str, playbook: str) -> None:
        out.append(WITH_META(s88._make_mainline_variant(base, name=name, note=note, patch=patch), track=track, branch=False, anchor_name="mainline_live_dynlev_fix8_lock18", playbook=playbook))

    add(
        "mainline_live_dynlev_fix8_lock18_cd7",
        "主线 stage186：先做轻降 cooldown 的 truth-anchor 提频验证，不先上 overlay_hold。",
        {
            "strategy_params.cooldown_bars": 7,
            "money_management.take_profit_pct": 1.14,
            "money_management.trailing_profit.activation_pnl_pct": 0.42,
            "money_management.trailing_profit.giveback_ratio": 0.23,
        },
        "mainline_cd7",
        "mainline_cd7",
    )
    add(
        "mainline_live_dynlev_fix8_lock18_ec_bnb112_btc540_tp110_trail046",
        "主线 stage186：事件确认 mild 版，围绕当前 runtime truth 轻提频。",
        {
            "strategy_params.cooldown_bars": 8,
            "money_management.stake_scale.bnb_long": 1.12,
            "money_management.stake_scale.btc_short": 5.40,
            "money_management.take_profit_pct": 1.10,
            "money_management.trailing_profit.activation_pnl_pct": 0.46,
            "money_management.trailing_profit.giveback_ratio": 0.24,
        },
        "mainline_event_confirm",
        "mainline_event_confirm",
    )
    add(
        "mainline_live_dynlev_fix8_lock18_banded_reentry_lb26_buf048_cd10_add2_step18",
        "主线 stage186：带宽再入 mild 版，避免 stage185 那种 0 交易激进变体。",
        {
            "strategy_params.breakout_lookback": 26,
            "strategy_params.breakout_atr_buffer": 0.48,
            "strategy_params.cooldown_bars": 10,
            "filters.adx_floor": 26,
            "strategy_params.pyramiding_max_adds": 2,
            "strategy_params.add_step_atr": 1.8,
            "strategy_params.add_risk_fraction": 0.14,
            "strategy_params.breakeven_atr": 1.9,
            "money_management.stake_scale.bnb_long": 1.18,
            "money_management.stake_scale.btc_short": 5.50,
            "money_management.take_profit_pct": 1.14,
            "money_management.trailing_profit.activation_pnl_pct": 0.44,
            "money_management.trailing_profit.giveback_ratio": 0.23,
        },
        "main_banded_reentry",
        "main_banded_reentry",
    )
    add(
        "mainline_live_dynlev_fix8_lock18_ladder_pyramid_lb26_buf046_cd10_add3_step18",
        "主线 stage186：阶梯加仓 mild 版，只在已有正收益盆地边缘扩圈。",
        {
            "strategy_params.breakout_lookback": 26,
            "strategy_params.breakout_atr_buffer": 0.46,
            "strategy_params.cooldown_bars": 10,
            "filters.adx_floor": 26,
            "strategy_params.pyramiding_max_adds": 3,
            "strategy_params.add_step_atr": 1.8,
            "strategy_params.add_risk_fraction": 0.15,
            "strategy_params.breakeven_atr": 1.9,
            "money_management.stake_scale.bnb_long": 1.20,
            "money_management.stake_scale.btc_short": 5.55,
            "money_management.take_profit_pct": 1.14,
            "money_management.trailing_profit.activation_pnl_pct": 0.44,
            "money_management.trailing_profit.giveback_ratio": 0.23,
        },
        "main_ladder_pyramid",
        "main_ladder_pyramid",
    )
    return out


def _branch_items() -> list[dict[str, Any]]:
    item_map = {str(item.get("name")): item for item in s88._branch_items()}
    out: list[dict[str, Any]] = []

    def add(item: dict[str, Any] | None, *, name: str, note: str, family: str, patch: dict[str, Any], track: str, anchor_name: str, playbook: str) -> None:
        if item is None:
            return
        out.append(WITH_META(s88._make_variant(item, name=name, note=note, family=family, patch=patch), track=track, branch=True, anchor_name=anchor_name, playbook=playbook))

    btc_long = item_map.get("btc_breakout_long_event_lb20_atr060_adx24_s050")
    btc_dual = item_map.get("btc_dual_fast_trend_dynlev_fix8")
    btc_short = item_map.get("btc_retest_short_event_lb20_atr060_adx24_s072")
    eth_anchor = item_map.get("eth_reclaim_long_lb12_atr043_adx16_s060") or item_map.get("eth_breakout_long_event_lb16_atr050_adx22_s034") or item_map.get("eth_breakout_long_follow_lb16_atr050_adx22_s034")
    eth_short = item_map.get("eth_retest_short_trend_lb20_atr060_adx24_s068") or item_map.get("eth_retest_short_trend_lb18_atr055_adx22_s072")
    sol_long = item_map.get("sol_pullback_long_core_adx26_cd6_lb22_zone026_s040") or item_map.get("sol_long_core_soft_lb20_zone025_s042")
    sol_short = item_map.get("sol_fast_trend_short_guarded_lb16_atr055_adx22_s072") or item_map.get("sol_fast_trend_short_guarded_lb18_atr060_adx24_s068")

    add(
        btc_long,
        name="btc_breakout_long_event_lb20_atr060_adx24_s050",
        note="BTC stage186：继续只保留 breakout 主腿。",
        family="long",
        patch={},
        track="btc_breakout_long",
        anchor_name="btc_breakout_long_event_lb20_atr060_adx24_s050",
        playbook="btc_breakout_long",
    )
    add(
        btc_dual,
        name="btc_dual_fast_trend_dynlev_fix8_cd1",
        note="BTC stage186：dual 只保留一条 hedge 参考线，不抢主位。",
        family="dual",
        patch={
            "strategy_params.cooldown_bars": 1,
            "filters.adx_floor": 16,
            "money_management.stake_scale.btc_long": 0.56,
            "money_management.stake_scale.btc_short": 0.86,
        },
        track="btc_dual_hedge",
        anchor_name="btc_dual_fast_trend_dynlev_fix8",
        playbook="btc_dual_hedge",
    )
    add(
        btc_short,
        name="btc_retest_short_event_lb20_atr060_adx24_s072",
        note="BTC stage186：空腿只留原始 retest 参考，不再扩 break_fail。",
        family="short",
        patch={},
        track="btc_retest_short",
        anchor_name="btc_retest_short_event_lb20_atr060_adx24_s072",
        playbook="btc_retest_short",
    )

    add(
        eth_anchor,
        name="eth_event_drift_long_lb12_atr046_adx18_s042",
        note="ETH stage186：继续把 event drift 作为第一主攻。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 12,
            "strategy_params.breakout_atr_buffer": 0.46,
            "strategy_params.cooldown_bars": 2,
            "filters.adx_floor": 18,
            "money_management.stake_scale.eth_long": 0.54,
            "money_management.take_profit_pct": 1.26,
            "money_management.trailing_profit.activation_pnl_pct": 0.44,
            "money_management.trailing_profit.giveback_ratio": 0.24,
        },
        track="eth_event_drift",
        anchor_name=str(eth_anchor.get("name")) if eth_anchor else "",
        playbook="eth_event_drift",
    )
    add(
        eth_anchor,
        name="eth_event_drift_long_lb10_atr044_adx16_s046",
        note="ETH stage186：事件漂移提频邻域。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 10,
            "strategy_params.breakout_atr_buffer": 0.44,
            "strategy_params.cooldown_bars": 2,
            "filters.adx_floor": 16,
            "money_management.stake_scale.eth_long": 0.52,
            "money_management.take_profit_pct": 1.24,
            "money_management.trailing_profit.activation_pnl_pct": 0.44,
            "money_management.trailing_profit.giveback_ratio": 0.24,
        },
        track="eth_event_drift",
        anchor_name=str(eth_anchor.get("name")) if eth_anchor else "",
        playbook="eth_event_drift",
    )
    add(
        eth_anchor,
        name="eth_reclaim_beta_long_lb11_atr042_adx15_cd1_s066",
        note="ETH stage186：保留 reclaim beta 长腿，避免只剩 drift。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 11,
            "strategy_params.breakout_atr_buffer": 0.42,
            "strategy_params.cooldown_bars": 1,
            "filters.adx_floor": 15,
            "money_management.stake_scale.eth_long": 0.50,
            "money_management.take_profit_pct": 1.22,
            "money_management.trailing_profit.activation_pnl_pct": 0.42,
            "money_management.trailing_profit.giveback_ratio": 0.23,
        },
        track="eth_reclaim_beta",
        anchor_name=str(eth_anchor.get("name")) if eth_anchor else "",
        playbook="eth_reclaim_beta",
    )
    add(
        eth_anchor,
        name="eth_squeeze_follow_long_lb9_atr040_adx15_s048",
        note="ETH stage186：保留 squeeze follow 作为第二长腿。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 9,
            "strategy_params.breakout_atr_buffer": 0.40,
            "strategy_params.cooldown_bars": 2,
            "filters.adx_floor": 15,
            "money_management.stake_scale.eth_long": 0.50,
            "money_management.take_profit_pct": 1.24,
            "money_management.trailing_profit.activation_pnl_pct": 0.44,
            "money_management.trailing_profit.giveback_ratio": 0.24,
        },
        track="eth_squeeze_follow",
        anchor_name=str(eth_anchor.get("name")) if eth_anchor else "",
        playbook="eth_squeeze_follow",
    )
    add(
        eth_short,
        name="eth_retest_short_trend_lb20_atr060_adx24_s068",
        note="ETH stage186：空腿继续保留 retest short。",
        family="short",
        patch={},
        track="eth_retest_short",
        anchor_name=str(eth_short.get("name")) if eth_short else "",
        playbook="eth_retest_short",
    )

    add(
        sol_long,
        name="sol_pullback_pair_long_adx26_cd6_lb22_zone026_s042",
        note="SOL stage186：pullback pair 继续第一主攻。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 22,
            "strategy_params.breakout_atr_buffer": 0.42,
            "strategy_params.cooldown_bars": 6,
            "filters.adx_floor": 26,
            "money_management.stake_scale.sol_long": 0.38,
            "money_management.take_profit_pct": 1.20,
            "money_management.trailing_profit.activation_pnl_pct": 0.42,
            "money_management.trailing_profit.giveback_ratio": 0.23,
        },
        track="sol_pullback_pair",
        anchor_name=str(sol_long.get("name")) if sol_long else "",
        playbook="sol_pullback_pair",
    )
    add(
        sol_long,
        name="sol_range_ladder_long_adx24_cd4_lb20_zone024_s048",
        note="SOL stage186：range ladder 继续第二主攻。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 20,
            "strategy_params.breakout_atr_buffer": 0.48,
            "strategy_params.cooldown_bars": 4,
            "filters.adx_floor": 24,
            "money_management.stake_scale.sol_long": 0.42,
            "money_management.take_profit_pct": 1.20,
            "money_management.trailing_profit.activation_pnl_pct": 0.42,
            "money_management.trailing_profit.giveback_ratio": 0.23,
        },
        track="sol_range_ladder",
        anchor_name=str(sol_long.get("name")) if sol_long else "",
        playbook="sol_range_ladder",
    )
    add(
        sol_long,
        name="sol_pullback_grid_long_adx24_cd3_lb20_zone024_s050",
        note="SOL stage186：grid-like long 继续保留为辅助线。",
        family="long",
        patch={
            "strategy_params.breakout_lookback": 20,
            "strategy_params.breakout_atr_buffer": 0.50,
            "strategy_params.cooldown_bars": 3,
            "filters.adx_floor": 24,
            "money_management.stake_scale.sol_long": 0.40,
            "money_management.take_profit_pct": 1.18,
            "money_management.trailing_profit.activation_pnl_pct": 0.40,
            "money_management.trailing_profit.giveback_ratio": 0.22,
        },
        track="sol_pullback_grid",
        anchor_name=str(sol_long.get("name")) if sol_long else "",
        playbook="sol_pullback_grid",
    )
    add(
        sol_short,
        name="sol_guarded_short_accel_lb14_atr052_adx18_cd1_s076",
        note="SOL stage186：空腿只留一条 guarded short。",
        family="short",
        patch={
            "strategy_params.breakout_lookback": 14,
            "strategy_params.breakout_atr_buffer": 0.52,
            "strategy_params.cooldown_bars": 1,
            "filters.adx_floor": 18,
            "money_management.stake_scale.sol_short": 0.56,
            "money_management.take_profit_pct": 1.04,
            "money_management.trailing_profit.activation_pnl_pct": 0.36,
            "money_management.trailing_profit.giveback_ratio": 0.21,
        },
        track="sol_guarded_short",
        anchor_name=str(sol_short.get("name")) if sol_short else "",
        playbook="sol_guarded_short",
    )
    return out


def _write_report(path_txt: Path, path_json: Path, main_rows: list[dict[str, Any]], branch_rows: list[dict[str, Any]], repaired_main: list[str], repaired_branch: list[str], scanned_main: list[str], scanned_branch: list[str], runtime_anchor: dict[str, Any]) -> dict[str, Any]:
    main_payload = _top_payload(main_rows, runtime_anchor, branch=False)
    branch_payload = _top_payload(branch_rows, runtime_anchor, branch=True)
    active_map = _active_map_from_payload(branch_payload, runtime_anchor)
    split_rec = _split_recommendation(branch_payload)
    summary = {
        "target_monthly_min": TARGET_MONTHLY_MIN,
        "target_monthly_max": TARGET_MONTHLY_MAX,
        "repaired_main": repaired_main,
        "repaired_branch": repaired_branch,
        "scanned_main": scanned_main,
        "scanned_branch": scanned_branch,
        "runtime_anchor": runtime_anchor,
        "stage91_active": active_map,
        "split_recommendation": split_rec,
        "main_top": _select_top(main_payload, limit=6),
        "branch_by_symbol": {sym: _select_top(branch_payload, symbol=sym, limit=4) for sym in ["btc", "eth", "sol"]},
    }

    lines: list[str] = []
    lines.append("Stage186 truth-anchor target lift frontier")
    lines.append("")
    lines.append("[summary]")
    lines.append(f"- target_monthly_floor={TARGET_MONTHLY_MIN*100:.2f}% target_monthly_ceiling={TARGET_MONTHLY_MAX*100:.2f}%")
    lines.append(f"- repaired_main={len(repaired_main)} repaired_branch={len(repaired_branch)}")
    lines.append(f"- scanned_main={len(scanned_main)} scanned_branch={len(scanned_branch)}")
    lines.append(f"- stage91_active={json.dumps(active_map, ensure_ascii=False)}")
    lines.append(f"- split_recommendation={split_rec}")
    if runtime_anchor.get("main"):
        lines.append(f"- runtime_anchor_main={json.dumps(runtime_anchor.get('main'), ensure_ascii=False)}")
    lines.append("")

    lines.append("[main_top]")
    for row in summary["main_top"]:
        lines.append(
            f"- {row['name']} | playbook={row['playbook']} | status={row['status']} | 6年={row['full_ret']*100:.2f}% | 近2年月化={row['recent_monthly']*100:.2f}% | WF月化={row['wf_monthly']*100:.2f}% | 近2年交易={row['recent_trades']} | WF交易={row['wf_trades']} | gap_to_7.6={row['gap_to_floor']*100:.2f}%"
        )
    lines.append("")

    for sym in ["eth", "btc", "sol"]:
        lines.append(f"[{sym}_top]")
        for row in summary["branch_by_symbol"][sym]:
            lines.append(
                f"- {row['name']} | playbook={row['playbook']} | status={row['status']} | 近2年={row['recent_ret']*100:.2f}% | 近2年月化={row['recent_monthly']*100:.2f}% | WF={row['wf_ret']*100:.2f}% | WF月化={row['wf_monthly']*100:.2f}% | 近2年交易={row['recent_trades']} | WF交易={row['wf_trades']} | gap_to_7.6={row['gap_to_floor']*100:.2f}%"
            )
        lines.append("")

    lines.append("[conclusion]")
    if summary["main_top"]:
        top = summary["main_top"][0]
        lines.append(f"- 主线第一候选: {top['name']} | 近2年月化={top['recent_monthly']*100:.2f}% | WF月化={top['wf_monthly']*100:.2f}%")
    eth_top = summary["branch_by_symbol"]["eth"][0] if summary["branch_by_symbol"]["eth"] else None
    btc_top = summary["branch_by_symbol"]["btc"][0] if summary["branch_by_symbol"]["btc"] else None
    sol_top = summary["branch_by_symbol"]["sol"][0] if summary["branch_by_symbol"]["sol"] else None
    if eth_top:
        lines.append(f"- ETH 第一候选: {eth_top['name']} | 近2年月化={eth_top['recent_monthly']*100:.2f}% | WF月化={eth_top['wf_monthly']*100:.2f}%")
    if btc_top:
        lines.append(f"- BTC 第一候选: {btc_top['name']} | 近2年月化={btc_top['recent_monthly']*100:.2f}% | WF月化={btc_top['wf_monthly']*100:.2f}%")
    if sol_top:
        lines.append(f"- SOL 第一候选: {sol_top['name']} | 近2年月化={sol_top['recent_monthly']*100:.2f}% | WF月化={sol_top['wf_monthly']*100:.2f}%")
    lines.append("- 这版先修 truth-anchor，再做 target-lift frontier；不动 demo / 下单链路。")
    lines.append("- overlay_hold 降权；BTC break_fail 继续硬黑；ETH 主攻 drift+reclaim_beta；SOL 主攻 pullback_pair+range_ladder。")
    txt = "\n".join(lines).rstrip() + "\n"
    path_txt.write_text(txt, encoding="utf-8")
    path_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage186 truth-anchor target lift frontier")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    raw = root / "reports" / "research_raw"
    raw.mkdir(parents=True, exist_ok=True)

    main_rows, branch_rows, repaired_main, repaired_branch = s141._load_stage_state(raw)
    cfg = _load_live_cfg(root)
    initial_equity = float(cfg.get("portfolio", {}).get("initial_equity", 100000.0))
    data = s46._load_portfolio_data(root, cfg)
    full_start, full_end = s77._window_bounds_from_data(data)
    runtime_anchor = _parse_runtime_anchor(root)

    item_map = {str(item.get("name")): item for item in s88._mainline_items()}
    ref_item = item_map.get("mainline_live_dynlev_fix8_lock18") or item_map.get("mainline_live_base")
    if ref_item is None:
        raise SystemExit("missing mainline reference")
    ref_row = s136._run_mainline(root, cfg, data, WITH_META(ref_item, track="base", branch=False, anchor_name=str(ref_item.get("name")), playbook="base"), initial_equity, full_start, full_end)

    main_map = {str(r.get("name")): s161._ensure_mainline_row(r, ref_row, initial_equity, full_end) for r in main_rows}
    scanned_main: list[str] = []
    for item in _mainline_items():
        print(f"[stage186] main {item['name']}", flush=True)
        row = s136._run_mainline(root, cfg, data, item, initial_equity, full_start, full_end)
        row = s161._ensure_mainline_row(row, ref_row, initial_equity, full_end)
        main_map[str(row.get("name"))] = row
        scanned_main.append(str(row.get("name")))
    main_rows = s161._finalize_rows(list(main_map.values()), branch=False)

    branch_map = {str(r.get("name")): s161._ensure_branch_row(r, initial_equity) for r in branch_rows}
    scanned_branch: list[str] = []
    for item in _branch_items():
        print(f"[stage186] branch {item['name']}", flush=True)
        row = s136._run_branch(root, cfg, item, initial_equity)
        row = s161._ensure_branch_row(row, initial_equity)
        branch_map[str(row.get("name"))] = row
        scanned_branch.append(str(row.get("name")))
    branch_rows = s161._finalize_rows(list(branch_map.values()), branch=True)

    main_txt = raw / "stage90_mainline_event_alpha_matrix_latest.txt"
    main_json = raw / "stage90_mainline_event_alpha_matrix_latest.json"
    branch_txt = raw / "stage91_branch_event_alpha_matrix_latest.txt"
    branch_json = raw / "stage91_branch_event_alpha_matrix_latest.json"
    s90._write_mainline(main_txt, main_json, main_rows)
    s90._write_branch(branch_txt, branch_json, branch_rows)

    frontier_txt = raw / "stage186_truth_anchor_target_lift_frontier_latest.txt"
    frontier_json = raw / "stage186_truth_anchor_target_lift_frontier_latest.json"
    summary = _write_report(frontier_txt, frontier_json, main_rows, branch_rows, repaired_main, repaired_branch, scanned_main, scanned_branch, runtime_anchor)
    manifest = {
        "mode": "truth_anchor_target_lift_frontier",
        "target_monthly_min": TARGET_MONTHLY_MIN,
        "target_monthly_max": TARGET_MONTHLY_MAX,
        "repaired_main": repaired_main,
        "repaired_branch": repaired_branch,
        "scanned_main": scanned_main,
        "scanned_branch": scanned_branch,
        "runtime_anchor": runtime_anchor,
        "stage91_active": summary.get("stage91_active"),
        "split_recommendation": summary.get("split_recommendation"),
        "outputs": {
            "stage90_txt": str(main_txt),
            "stage90_json": str(main_json),
            "stage91_txt": str(branch_txt),
            "stage91_json": str(branch_json),
            "frontier_txt": str(frontier_txt),
            "frontier_json": str(frontier_json),
        },
    }
    manifest_path = raw / "stage186_truth_anchor_target_lift_manifest_latest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    s141._mirror_to_workspace(root, [main_txt, main_json, branch_txt, branch_json, frontier_txt, frontier_json, manifest_path])

    out_zip = root.parent / "Downloads" / "stage186_truth_anchor_target_lift_frontier_latest.zip"
    WRITE_SINGLE_ZIP(out_zip, {
        "stage186_truth_anchor_target_lift_frontier_latest.txt": frontier_txt,
        "stage186_truth_anchor_target_lift_frontier_latest.json": frontier_json,
        "stage186_truth_anchor_target_lift_manifest_latest.json": manifest_path,
        "stage90_mainline_event_alpha_matrix_latest.txt": main_txt,
        "stage90_mainline_event_alpha_matrix_latest.json": main_json,
        "stage91_branch_event_alpha_matrix_latest.txt": branch_txt,
        "stage91_branch_event_alpha_matrix_latest.json": branch_json,
    })
    print(out_zip)


if __name__ == "__main__":
    main()
