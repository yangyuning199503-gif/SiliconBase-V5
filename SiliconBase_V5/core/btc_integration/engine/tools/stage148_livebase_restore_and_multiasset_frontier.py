from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import research_config_baseline as rcb
from tools import stage46_aggressive_lab as s46
from tools import stage77_mainline_dual_window_lab as s77
from tools import stage78_branch_dual_window_lab as s78
from tools import stage81_mainline_walkforward_lab as s81
from tools import stage82_branch_walkforward_lab as s82
from tools import stage88_strategy_fusion_walkforward as s88
from tools import stage90_event_alpha_matrix as s90
from tools import stage136_regime_plateau_frontier as s136
from tools import stage141_guarded_asymmetry_shortlist as s141

TARGET_MONTHLY_MIN = s136.TARGET_MONTHLY_MIN
TARGET_MONTHLY_MAX = s136.TARGET_MONTHLY_MAX


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v in (None, "", "-"):
            return default
        return float(v)
    except Exception:
        return default


def _fmt_pct(v: Any) -> str:
    try:
        return f"{float(v) * 100:.2f}%"
    except Exception:
        return "-"


def _latest_common_end(root: Path, symbols: list[str], csv_template: str, fallback: str) -> str:
    ends: list[pd.Timestamp] = []
    for sym in symbols:
        path = root / Path(csv_template.format(symbol=sym))
        if not path.exists():
            continue
        try:
            df = pd.read_csv(path, usecols=[0])
        except Exception:
            continue
        if df.empty:
            continue
        try:
            ts = pd.to_datetime(df.iloc[-1, 0], utc=True, errors="coerce")
        except Exception:
            ts = pd.NaT
        if pd.isna(ts):
            continue
        ends.append(ts)
    if not ends:
        return fallback
    return min(ends).tz_convert("UTC").strftime("%Y-%m-%d")


def _restore_mainline_livebase(root: Path) -> dict[str, Any]:
    current_path = root / "config.yml"
    restore_path = root / "config_mainline_live_base_restore_stage148.yml"
    backup_path = root / "config_stage148_pre_restore_backup.yml"

    current_cfg = _read_yaml(current_path)
    base_cfg = _read_yaml(rcb.locate_research_base_yaml(root))
    if not base_cfg:
        raise SystemExit("缺少 research_baselines/mainline_live_base.yml")

    if current_path.exists() and not backup_path.exists():
        backup_path.write_text(current_path.read_text(encoding="utf-8"), encoding="utf-8")

    restored = copy.deepcopy(base_cfg)
    restored.setdefault("system", {})
    restored["system"]["version"] = "r256_main_demo_restore_live_base_stage148"
    restored["system"]["strategy"] = "explosion_v1"
    restored["system"]["note"] = (
        "Stage148：按阶段性报告三十/三十一口径，把主线 demo 切回 old mainline_live_base；"
        "以其近24月复利月化 13.48% 为主锚，再叠消息确认与技术提频前沿。"
        "当前切回只是恢复主锚，不把消息面直接升为裸开仓层。"
    )
    restored.setdefault("data", {})
    csv_template = str(restored["data"].get("csv_template", "data/raw/{symbol}_15m.csv"))
    restored["data"]["end"] = _latest_common_end(root, ["btc", "bnb"], csv_template, str(restored["data"].get("end", "2026-01-31")))

    if isinstance(current_cfg.get("live_bridge"), dict):
        restored["live_bridge"] = copy.deepcopy(current_cfg["live_bridge"])
    if isinstance(current_cfg.get("outputs"), dict):
        restored["outputs"] = copy.deepcopy(current_cfg["outputs"])

    _write_yaml(restore_path, restored)
    _write_yaml(current_path, restored)
    return {
        "before_version": str((current_cfg.get("system") or {}).get("version") or "-"),
        "after_version": str((restored.get("system") or {}).get("version") or "-"),
        "backup_path": str(backup_path),
        "restore_path": str(restore_path),
        "current_path": str(current_path),
        "restored_end": str(restored.get("data", {}).get("end", "-")),
    }


def _with_meta(item: dict[str, Any], *, track: str, branch: bool) -> dict[str, Any]:
    out = copy.deepcopy(item)
    out["meta"] = s136._extract_branch_meta(out, track=track) if branch else s136._extract_main_meta(out.get("mods", {}) or {})
    out["meta"]["track"] = track
    return out


def _mainline_scan_items() -> list[dict[str, Any]]:
    item_map = {str(item.get("name")): item for item in s88._mainline_items()}
    out: list[dict[str, Any]] = []

    def add(name: str, track: str) -> None:
        item = item_map.get(name)
        if item is not None:
            out.append(_with_meta(item, track=track, branch=False))

    add("mainline_live_base", "livebase_restore")
    add("combo_sr_soft_adx26_cd6_lb24_zone028_ref", "shadow_ref")
    add("combo_sr_soft_adx28_cd6_lb24_zone028", "shadow_ref")

    base_live = item_map.get("mainline_live_base")
    if base_live is not None:
        out.append(
            _with_meta(
                s88._make_mainline_variant(
                    base_live,
                    name="mainline_live_base_lb26_cd18_eventconfirm",
                    note="old live_base 上做技术提频：缩短 lookback、缩短 cooldown，但保留消息确认层与 BTC short 对冲。",
                    patch={
                        "strategy_params.breakout_lookback": 26,
                        "strategy_params.cooldown_bars": 18,
                        "filters.adx_floor": 28,
                        "money_management.risk_on.mult": 1.55,
                    },
                ),
                track="eventconfirm",
                branch=False,
            )
        )
        out.append(
            _with_meta(
                s88._make_mainline_variant(
                    base_live,
                    name="mainline_live_base_lb24_cd14_eventconfirm",
                    note="old live_base 上做更激进的技术提频：进一步缩短 lookback/cooldown，但不取消 execution_guard。",
                    patch={
                        "strategy_params.breakout_lookback": 24,
                        "strategy_params.cooldown_bars": 14,
                        "filters.adx_floor": 26,
                        "money_management.risk_on.mult": 1.60,
                    },
                ),
                track="eventconfirm",
                branch=False,
            )
        )
    return out


def _branch_scan_items() -> list[dict[str, Any]]:
    item_map = {str(item.get("name")): item for item in s88._branch_items()}
    out: list[dict[str, Any]] = []

    def add(item: dict[str, Any] | None, *, track: str) -> None:
        if item is not None:
            out.append(_with_meta(item, track=track, branch=True))

    btc_long = item_map.get("btc_breakout_long_event_lb20_atr060_adx24_s050")
    btc_short = item_map.get("btc_retest_short_event_lb20_atr060_adx24_s072")
    btc_dual = item_map.get("btc_dual_fast_trend_dynlev_fix8")
    eth_long = item_map.get("eth_breakout_long_follow_lb16_atr050_adx22_s034")
    eth_short = item_map.get("eth_retest_short_trend_lb20_atr060_adx24_s068")
    sol_long = item_map.get("sol_pullback_long_core_adx26_cd6_lb22_zone026_s040")
    sol_short = item_map.get("sol_fast_trend_short_guarded_lb18_atr060_adx24_s068")

    add(btc_long, track="btc_event_drift")
    add(btc_short, track="btc_reclaim_short")
    add(btc_dual, track="btc_dual")
    add(eth_short, track="eth_panic_short")
    add(sol_long, track="sol_pullback_long")
    add(sol_short, track="sol_guarded_short")

    if btc_long is not None:
        out.append(
            _with_meta(
                s88._make_variant(
                    btc_long,
                    name="btc_breakout_long_event_lb18_atr055_adx22_s056",
                    note="BTC 用 continuation + event drift，不套 ETH/SOL reclaim 模板。",
                    family="long",
                    patch={
                        "strategy_params.breakout_lookback": 18,
                        "strategy_params.breakout_atr_buffer": 0.55,
                        "strategy_params.cooldown_bars": 5,
                        "filters.adx_floor": 22,
                        "money_management.stake_scale.btc_long": 0.56,
                    },
                ),
                track="btc_event_drift",
                branch=True,
            )
        )
    if btc_short is not None:
        out.append(
            _with_meta(
                s88._make_variant(
                    btc_short,
                    name="btc_retest_short_event_lb18_atr055_adx22_s068",
                    note="BTC 空腿只做冲击后的 retest short，不拿 SOL 快趋势短腿硬套。",
                    family="short",
                    patch={
                        "strategy_params.breakout_lookback": 18,
                        "strategy_params.breakout_atr_buffer": 0.55,
                        "strategy_params.cooldown_bars": 4,
                        "filters.adx_floor": 22,
                        "money_management.stake_scale.btc_short": 0.68,
                    },
                ),
                track="btc_reclaim_short",
                branch=True,
            )
        )
    if eth_long is not None:
        out.append(
            _with_meta(
                s88._make_variant(
                    eth_long,
                    name="eth_event_drift_long_lb10_atr044_adx16_s070",
                    note="ETH 保留事件漂移长腿：不只盯 reclaim，一并看 drift。",
                    family="long",
                    patch={
                        "strategy_params.breakout_lookback": 10,
                        "strategy_params.breakout_atr_buffer": 0.44,
                        "strategy_params.cooldown_bars": 4,
                        "filters.adx_floor": 16,
                        "money_management.stake_scale.eth_long": 0.70,
                    },
                ),
                track="eth_drift",
                branch=True,
            )
        )
        out.append(
            _with_meta(
                s88._make_variant(
                    eth_long,
                    name="eth_squeeze_follow_long_lb10_atr042_adx16_s070",
                    note="ETH 保留 squeeze follow：挤仓延续单独成路，不和 BTC/SOL 通吃一套。",
                    family="long",
                    patch={
                        "strategy_params.breakout_lookback": 10,
                        "strategy_params.breakout_atr_buffer": 0.42,
                        "strategy_params.cooldown_bars": 4,
                        "filters.adx_floor": 16,
                        "money_management.stake_scale.eth_long": 0.70,
                    },
                ),
                track="eth_squeeze",
                branch=True,
            )
        )
    if sol_long is not None:
        out.append(
            _with_meta(
                s88._make_variant(
                    sol_long,
                    name="sol_pullback_long_core_adx24_cd4_lb20_zone024_s050",
                    note="SOL 长腿用更快的 pullback/reclaim，专门给高弹性币提频。",
                    family="long",
                    patch={
                        "strategy_params.breakout_lookback": 20,
                        "strategy_params.cooldown_bars": 4,
                        "filters.adx_floor": 24,
                        "sr_entries.cooldown_bars": 4,
                        "sr_entries.adx_max": 24,
                        "sr_entries.zone_atr_mult": 0.24,
                        "money_management.stake_scale.sol_long": 0.50,
                    },
                ),
                track="sol_pullback_long",
                branch=True,
            )
        )
    if sol_short is not None:
        out.append(
            _with_meta(
                s88._make_variant(
                    sol_short,
                    name="sol_fast_trend_short_guarded_lb16_atr055_adx22_s072",
                    note="SOL 空腿独立保 guarded short：快，但必须 guarded，不能把 ETH retest 套过来。",
                    family="short",
                    patch={
                        "strategy_params.breakout_lookback": 16,
                        "strategy_params.breakout_atr_buffer": 0.55,
                        "strategy_params.cooldown_bars": 4,
                        "filters.adx_floor": 22,
                        "money_management.stake_scale.sol_short": 0.72,
                    },
                ),
                track="sol_guarded_short",
                branch=True,
            )
        )
    return out


def _finalize_rows(rows: list[dict[str, Any]], *, branch: bool) -> list[dict[str, Any]]:
    for row in rows:
        row["plateau"] = s136._plateau_summary(row, rows, branch=branch)
    for row in rows:
        row["alpha_score"] = s136._frontier_score(row, rows, branch=branch)
        row["decision"] = s136._frontier_label(row, branch=branch)
    rows.sort(key=lambda r: float(r.get("alpha_score", 0.0)), reverse=True)
    return rows


def _terminal_assessment(branch_rows: list[dict[str, Any]]) -> dict[str, Any]:
    assets = s90._asset_summaries(branch_rows)
    symbols = [str(x.get("symbol") or "").upper() for x in assets]
    mode_map = {str(x.get("symbol") or "").upper(): str(x.get("mode") or "-") for x in assets}
    return {
        "recommendation": "one_branch_terminal_now",
        "symbols": symbols,
        "modes": mode_map,
        "reason": [
            "当前 tri-book 已能给 BTC/ETH/SOL 各自不同 active/long_best/short_best/dual_best；一个终端不等于一套模板。",
            "不单独开三个终端的主要影响是运行、日志、暂停、PnL 记账耦合；不是策略参数被迫通吃。",
            "现阶段先保留 1 个 branch 终端；等至少两个资产从 watch/research_only 升到独立 submit_orders，再拆成多终端。",
        ],
    }


def _write_report(
    path_txt: Path,
    path_json: Path,
    restore_meta: dict[str, Any],
    main_rows: list[dict[str, Any]],
    branch_rows: list[dict[str, Any]],
    scanned_main: list[str],
    scanned_branch: list[str],
    terminal_assessment: dict[str, Any],
) -> None:
    main_payload = [s136._payload_row(r, branch=False) for r in main_rows]
    branch_payload = [s136._payload_row(r, branch=True) for r in branch_rows]
    asset_summary = s90._asset_summaries(branch_rows)

    lines: list[str] = []
    lines.append("Stage148 livebase restore + multi-asset frontier")
    lines.append("原则：主线先切回 old mainline_live_base，再在它的基础上做消息面+技术面提频；BTC/ETH/SOL 三个标的继续各走各的 long/short playbook，不通吃一套。")
    lines.append(f"目标区间：{TARGET_MONTHLY_MIN*100:.1f}% - {TARGET_MONTHLY_MAX*100:.1f}% / 月")
    lines.append("")
    lines.append("=== 主线 Demo 切回 ===")
    lines.append(f"- before_version: {restore_meta.get('before_version')}")
    lines.append(f"- after_version: {restore_meta.get('after_version')}")
    lines.append(f"- restore_config: {restore_meta.get('restore_path')}")
    lines.append(f"- backup_config: {restore_meta.get('backup_path')}")
    lines.append(f"- restored_data_end: {restore_meta.get('restored_end')}")
    lines.append("")
    lines.append("=== 主线前5 ===")
    for row in main_payload[:5]:
        lines.append(
            f"- {row['name']}: target_monthly={row['target_monthly']*100:.2f}% | 近2年={row['recent_monthly']*100:.2f}%/{row['recent_trades']}笔/PF{row['recent_pf']:.3f} | WF={row['wf_monthly']*100:.2f}%/{row['wf_trades']}笔/PF{row['wf_pf']:.3f} | decision={row['decision']}"
        )
    lines.append("")
    lines.append("=== 分支前8 ===")
    for row in branch_payload[:8]:
        lines.append(
            f"- {row['name']}: {str(row['symbol']).upper()} {row['family']} | target_monthly={row['target_monthly']*100:.2f}% | 近2年={row['recent_monthly']*100:.2f}%/{row['recent_trades']}笔/PF{row['recent_pf']:.3f} | WF={row['wf_monthly']*100:.2f}%/{row['wf_trades']}笔/PF{row['wf_pf']:.3f} | decision={row['decision']}"
        )
    lines.append("")
    lines.append("=== 资产一体腿建议 ===")
    for item in asset_summary:
        active = item.get("active") if isinstance(item.get("active"), dict) else {}
        lines.append(
            f"- {str(item.get('symbol')).upper()}: mode={item.get('mode')} | active={active.get('name','-')}"
        )
    lines.append("")
    lines.append("=== 终端结论 ===")
    lines.append(f"- recommendation: {terminal_assessment.get('recommendation')}")
    for msg in terminal_assessment.get("reason", []) or []:
        lines.append(f"- {msg}")
    lines.append("")
    lines.append("=== 本轮新增扫描 ===")
    lines.append(f"- mainline: {', '.join(scanned_main) if scanned_main else '-'}")
    lines.append(f"- branch: {', '.join(scanned_branch) if scanned_branch else '-'}")

    def _asset_json(item: dict[str, Any]) -> dict[str, Any]:
        def _row_json(row: dict[str, Any] | None) -> Any:
            if row is None:
                return None
            return s90._json_safe({**row, "dominant_gate": s90._strip_gate_payload(row.get("dominant_gate", {}))})
        return {
            "symbol": item.get("symbol"),
            "mode": item.get("mode"),
            "note": item.get("note"),
            "active": _row_json(item.get("active")),
            "long_best": _row_json(item.get("long_best")),
            "short_best": _row_json(item.get("short_best")),
            "dual_best": _row_json(item.get("dual_best")),
        }

    payload = {
        "restore_meta": restore_meta,
        "terminal_assessment": terminal_assessment,
        "new_mainline_candidates": scanned_main,
        "new_branch_candidates": scanned_branch,
        "mainline": main_payload,
        "branch": branch_payload,
        "asset_summary": [_asset_json(x) for x in asset_summary],
    }
    path_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    path_json.write_text(json.dumps(s90._json_safe(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage148 livebase restore + multi-asset frontier")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--sync-only", action="store_true", help="只切回主线配置并生成终端建议，不跑回测")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    raw = root / "reports" / "research_raw"
    raw.mkdir(parents=True, exist_ok=True)

    restore_meta = _restore_mainline_livebase(root)

    if args.sync_only:
        path_txt = raw / "stage148_livebase_restore_and_multiasset_frontier_latest.txt"
        path_json = raw / "stage148_livebase_restore_and_multiasset_frontier_latest.json"
        terminal_assessment = {
            "recommendation": "one_branch_terminal_now",
            "reason": [
                "sync_only 模式：仅切回主线 old live_base，不跑新 frontier。",
                "当前 tri-book 仍建议 1 个 branch 终端先跑，避免过早拆分。",
            ],
        }
        _write_report(path_txt, path_json, restore_meta, [], [], [], [], terminal_assessment)
        manifest = {
            "mode": "sync_only",
            "restore_meta": restore_meta,
            "frontier_txt": str(path_txt),
            "frontier_json": str(path_json),
        }
        manifest_path = raw / "stage148_livebase_restore_and_multiasset_manifest_latest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(path_txt)
        print(path_json)
        print(manifest_path)
        return

    main_rows_prev, branch_rows_prev, repaired_main, repaired_branch = s141._load_stage_state(raw)
    cfg = rcb.load_research_base_config(root)
    initial_equity = float(cfg.get("portfolio", {}).get("initial_equity", 100000.0))

    scanned_main: list[str] = []
    main_map = {str(r.get("name")): copy.deepcopy(r) for r in main_rows_prev}
    data = s46._load_portfolio_data(root, cfg)
    full_start, full_end = s77._window_bounds_from_data(data)

    # reference row for WF against restored old live_base
    ref_candidates = {str(item.get("name")): item for item in _mainline_scan_items()}
    ref_item = ref_candidates.get("mainline_live_base")
    ref_row = None
    if ref_item is not None:
        ref_row = s136._run_mainline(root, cfg, data, ref_item, initial_equity, full_start, full_end)
    for item in _mainline_scan_items():
        print(f"[stage148] mainline {item['name']}", flush=True)
        row = s136._run_mainline(root, cfg, data, item, initial_equity, full_start, full_end)
        if ref_row is not None:
            row["walkforward"] = s81._wf_result(row, ref_row, initial_equity, s81.RECENT_START, full_end)
        row["dominant_gate"] = s90._dominant_gate(row, branch=False)
        main_map[str(row.get("name"))] = row
        scanned_main.append(str(row.get("name")))
    main_rows = _finalize_rows(list(main_map.values()), branch=False)

    scanned_branch: list[str] = []
    branch_map = {str(r.get("name")): copy.deepcopy(r) for r in branch_rows_prev}
    for item in _branch_scan_items():
        print(f"[stage148] branch {item['name']}", flush=True)
        row = s136._run_branch(root, cfg, item, initial_equity)
        row["walkforward"] = s82._wf_result(row, initial_equity, s78.RECENT_START, row["full_end"])
        row["dominant_gate"] = s90._dominant_gate(row, branch=True)
        branch_map[str(row.get("name"))] = row
        scanned_branch.append(str(row.get("name")))
    branch_rows = _finalize_rows(list(branch_map.values()), branch=True)

    main_txt = raw / "stage148_mainline_matrix_latest.txt"
    main_json = raw / "stage148_mainline_matrix_latest.json"
    branch_txt = raw / "stage148_branch_matrix_latest.txt"
    branch_json = raw / "stage148_branch_matrix_latest.json"
    s90._write_mainline(main_txt, main_json, main_rows)
    s90._write_branch(branch_txt, branch_json, branch_rows)

    terminal_assessment = _terminal_assessment(branch_rows)
    frontier_txt = raw / "stage148_livebase_restore_and_multiasset_frontier_latest.txt"
    frontier_json = raw / "stage148_livebase_restore_and_multiasset_frontier_latest.json"
    _write_report(frontier_txt, frontier_json, restore_meta, main_rows, branch_rows, scanned_main, scanned_branch, terminal_assessment)

    manifest = {
        "mode": "livebase_restore_multiasset_frontier",
        "restore_meta": restore_meta,
        "repaired_main": repaired_main,
        "repaired_branch": repaired_branch,
        "new_mainline_candidates": scanned_main,
        "new_branch_candidates": scanned_branch,
        "outputs": {
            "mainline_txt": str(main_txt),
            "mainline_json": str(main_json),
            "branch_txt": str(branch_txt),
            "branch_json": str(branch_json),
            "frontier_txt": str(frontier_txt),
            "frontier_json": str(frontier_json),
        },
    }
    manifest_path = raw / "stage148_livebase_restore_and_multiasset_manifest_latest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    s141._mirror_to_workspace(root, [main_txt, main_json, branch_txt, branch_json, frontier_txt, frontier_json, manifest_path])

    print(main_txt)
    print(main_json)
    print(branch_txt)
    print(branch_json)
    print(frontier_txt)
    print(frontier_json)
    print(manifest_path)


if __name__ == "__main__":
    main()
