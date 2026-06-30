from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tools.stage210_common_event_message_model_frontier as s210

from tools import message_stack_backtest as msb

ASSETS = ["btc", "bnb", "eth", "sol"]


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def _load_recent_items(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(payload, dict) and isinstance(payload.get("response"), dict):
        payload = payload["response"]
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        payload = payload["data"]
    items = msb._extract_items(payload)
    return [x for x in items if isinstance(x, dict)]


CAL_CATEGORY_BY_CLASS = {
    "rates": "macro",
    "inflation": "macro",
    "labor": "macro",
    "growth": "macro",
    "confidence": "macro",
    "liquidity": "macro",
    "energy": "macro",
    "policy": "policy",
    "exchange": "exchange",
    "hack": "hack",
    "generic": "generic",
}


NEWS_CATEGORY_BY_CLASS = {
    "rates": "macro",
    "inflation": "macro",
    "labor": "macro",
    "growth": "macro",
    "confidence": "macro",
    "liquidity": "macro",
    "energy": "macro",
    "policy": "policy",
    "exchange": "exchange",
    "hack": "hack",
    "generic": "crypto",
}


def _standardize_calendar_live(project_dir: Path, now_utc: pd.Timestamp) -> tuple[pd.DataFrame, str]:
    raw_path = project_dir / "data" / "external" / "coinglass" / "economic_recent.json"
    rows: list[dict[str, Any]] = []
    for item in _load_recent_items(raw_path):
        ts = msb._extract_time(item)
        if ts is None:
            continue
        title = str(item.get("calendar_name", "") or "")
        country = str(item.get("country_code", "") or "")
        cls = s210._classify_event(title, "macro", "")
        spec = s210.CAL_CLASS_SPECS.get(cls, s210.CAL_CLASS_SPECS["generic"])
        severity = s210._severity_from_importance(item.get("importance_level"), cls)
        base = {
            "publish_utc": ts,
            "lead_start_utc": ts - pd.Timedelta(hours=float(spec["lead_h"])),
            "release_end_utc": ts + pd.Timedelta(hours=float(spec["release_h"])),
            "drift_end_utc": ts + pd.Timedelta(hours=float(spec["drift_h"])),
            "decay_end_utc": ts + pd.Timedelta(hours=float(spec["decay_h"])),
            "country": country,
            "event_class": cls,
            "severity": severity,
            "importance_level": int(item.get("importance_level") or 0),
            "title": title,
            "class_weight": float(spec["class_weight"]),
            "fallback_mode": "normal",
        }
        rows.append(base)
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=[
            "publish_utc", "lead_start_utc", "release_end_utc", "drift_end_utc", "decay_end_utc",
            "country", "event_class", "severity", "importance_level", "title", "class_weight", "fallback_mode",
        ]), "empty"
    df = df.sort_values(["publish_utc", "importance_level"], ascending=[True, False]).reset_index(drop=True)
    future_df = df[df["publish_utc"] >= now_utc].copy()
    if not future_df.empty:
        return future_df.reset_index(drop=True), "future"
    anchor = pd.to_datetime(df["publish_utc"]).max()
    fallback_df = df[df["publish_utc"] >= anchor - pd.Timedelta(days=3)].copy()
    fallback_df["fallback_mode"] = "latest_cache_window"
    return fallback_df.reset_index(drop=True), "latest_cache_window"


HIGH_QUALITY_SOURCES = {"COINTELEGRAPH", "THE BLOCK", "BLOOMBERG", "REUTERS", "DECRYPT", "BLOCKWORKS"}


def _standardize_news_live(project_dir: Path, now_utc: pd.Timestamp) -> tuple[pd.DataFrame, str]:
    raw_path = project_dir / "data" / "external" / "coinglass" / "news_recent.json"
    rows: list[dict[str, Any]] = []
    for item in _load_recent_items(raw_path):
        ts = msb._extract_time(item)
        if ts is None:
            continue
        title = str(item.get("article_title", "") or "")
        source = str(item.get("source_name", "") or "")
        desc = str(item.get("article_description", "") or "")
        text = " ".join([title, desc, source]).lower()
        cls = s210._classify_event(title, "crypto", desc)
        severity = "medium"
        if any(k in text for k in ["hack", "exploit", "lawsuit", "charged", "settlement", "liquidation", "bankruptcy", "breach"]):
            severity = "high"
        elif any(k in text for k in ["approval", "launch", "partnership", "etf", "upgrade", "funding", "listing"]):
            severity = "medium"
        source_weight = 1.0 if source.upper() in HIGH_QUALITY_SOURCES else 0.8
        rows.append(
            {
                "release_utc": ts,
                "title": title,
                "source": source,
                "event_class": cls,
                "severity": severity,
                "source_weight": source_weight,
                "fallback_mode": "normal",
            }
        )
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["release_utc", "title", "source", "event_class", "severity", "source_weight", "fallback_mode"]), "empty"
    df = df.sort_values("release_utc", ascending=False).reset_index(drop=True)
    recent_df = df[df["release_utc"] >= now_utc - pd.Timedelta(days=7)].copy()
    if not recent_df.empty:
        return recent_df.reset_index(drop=True), "recent_7d"
    latest_df = df.head(12).copy()
    latest_df["fallback_mode"] = "latest_cache_window"
    return latest_df.reset_index(drop=True), "latest_cache_window"


def _attach_asset_scores(df: pd.DataFrame, kind: str) -> pd.DataFrame:
    if df.empty:
        out = df.copy()
        for a in ASSETS:
            out[f"score_{a}"] = []
        return out
    out = df.copy()
    for asset in ASSETS:
        vals = []
        for _, row in out.iterrows():
            title = str(row.get("title", "") or "")
            cls = str(row.get("event_class", "generic") or "generic")
            sev = str(row.get("severity", "default") or "default").lower()
            category = (CAL_CATEGORY_BY_CLASS if kind == "calendar" else NEWS_CATEGORY_BY_CLASS).get(cls, "generic")
            asset_rel = s210._asset_relevance(asset, category, title, str(row.get("source", "") or ""), title)
            sev_w = s210.SEVERITY_W.get(sev, s210.SEVERITY_W["default"])
            class_w = float(s210.CAL_CLASS_SPECS.get(cls, s210.CAL_CLASS_SPECS["generic"])["class_weight"])
            extra = float(row.get("source_weight", 1.0) or 1.0)
            vals.append(sev_w * class_w * asset_rel * extra)
        out[f"score_{asset}"] = vals
    return out


def _pick_asset_top(df: pd.DataFrame, asset: str, k: int = 3) -> list[dict[str, Any]]:
    col = f"score_{asset}"
    if df.empty or col not in df.columns:
        return []
    keep_cols = [c for c in ["publish_utc", "release_utc", "title", "country", "source", "event_class", "severity", "fallback_mode", col] if c in df.columns]
    tmp = df[keep_cols].sort_values(col, ascending=False).head(k).copy()
    return tmp.to_dict(orient="records")


def run(project_dir: Path, out_txt: Path, out_json: Path) -> None:
    base_txt = out_txt.with_name("stage211_base_stage210_latest.txt")
    base_json = out_json.with_name("stage211_base_stage210_latest.json")
    s210.run(project_dir, base_txt, base_json)
    payload = json.loads(base_json.read_text(encoding="utf-8"))
    recommended = payload.get("recommended")
    top = payload.get("top_variants", [])

    now_utc = pd.Timestamp.now(tz="UTC")
    cal_df, cal_mode = _standardize_calendar_live(project_dir, now_utc)
    news_df, news_mode = _standardize_news_live(project_dir, now_utc)
    cal_df = _attach_asset_scores(cal_df, "calendar")
    news_df = _attach_asset_scores(news_df, "news")

    lines: list[str] = []
    lines.append("Stage211 future event runtime bridge frontier")
    lines.append("")
    lines.append("[historical_common_model]")
    if recommended:
        full = recommended["gated_metrics_full"]
        r2 = recommended["gated_metrics_recent2y"]
        wf = recommended["wf"]
        lines.append(
            f"- recommended={recommended['name']} | 6y ret={_fmt_pct(full['total_return'])} pf={full['profit_factor']:.3f} maxdd={_fmt_pct(full['max_drawdown'])} trades={full['trades']}"
        )
        lines.append(
            f"- 2y ret={_fmt_pct(r2['total_return'])} pf={r2['profit_factor']:.3f} maxdd={_fmt_pct(r2['max_drawdown'])} trades={r2['trades']}"
        )
        lines.append(
            f"- wf pnl_delta={wf['aggregate_pnl_delta']:+.2f} dd_delta={_fmt_pct(wf['aggregate_dd_delta'])} hard={wf['aggregate_hard']} mid={wf['aggregate_mid']} soft={wf['aggregate_soft']} retain={_fmt_pct(wf['avg_retained'])}"
        )
    else:
        lines.append("- recommended=none")
    lines.append("")
    lines.append("[live_bridge_status]")
    lines.append(f"- calendar_mode={cal_mode} | standardized_events={len(cal_df)}")
    lines.append(f"- news_mode={news_mode} | standardized_messages={len(news_df)}")
    lines.append("- 这一步只修未来事件/消息桥，不改历史回测骨架。")
    lines.append("")
    lines.append("[top_calendar_by_asset]")
    for asset in ASSETS:
        rows = _pick_asset_top(cal_df, asset, 2)
        if not rows:
            lines.append(f"- {asset}: none")
            continue
        for row in rows:
            ts = row.get("publish_utc")
            lines.append(
                f"- {asset} | {ts} | {row.get('event_class','')} | {row.get('severity','')} | score={row.get(f'score_{asset}',0.0):.3f} | {row.get('title','')}"
            )
    lines.append("")
    lines.append("[top_news_by_asset]")
    for asset in ASSETS:
        rows = _pick_asset_top(news_df, asset, 2)
        if not rows:
            lines.append(f"- {asset}: none")
            continue
        for row in rows:
            ts = row.get("release_utc")
            lines.append(
                f"- {asset} | {ts} | {row.get('source','')} | {row.get('event_class','')} | {row.get('severity','')} | score={row.get(f'score_{asset}',0.0):.3f} | {row.get('title','')}"
            )
    lines.append("")
    lines.append("[conclusion]")
    if recommended:
        lines.append(f"- 公共模型先继续用 {recommended['name']}。")
    lines.append("- stage210 的硬框架保留；stage211 只把 future-event / recent-news 的时间标准化桥接上。")
    lines.append("- 下一步才把同一套 action ladder 往 branch 迁。")

    out_txt.parent.mkdir(parents=True, exist_ok=True)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    out_json.write_text(
        json.dumps(
            {
                "recommended": recommended,
                "top_variants": top,
                "calendar_mode": cal_mode,
                "news_mode": news_mode,
                "calendar_events": cal_df.head(20).to_dict(orient="records"),
                "recent_news": news_df.head(20).to_dict(orient="records"),
                "asset_top_calendar": {a: _pick_asset_top(cal_df, a, 3) for a in ASSETS},
                "asset_top_news": {a: _pick_asset_top(news_df, a, 3) for a in ASSETS},
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage211 future event runtime bridge frontier")
    ap.add_argument("--project-dir", type=Path, default=Path("."))
    ap.add_argument("--out-txt", type=Path, default=None)
    ap.add_argument("--out-json", type=Path, default=None)
    args = ap.parse_args()
    root = args.project_dir.resolve()
    out_txt = args.out_txt or (root / "reports" / "research_raw" / "stage211_future_event_runtime_bridge_frontier_latest.txt")
    out_json = args.out_json or (root / "reports" / "research_raw" / "stage211_future_event_runtime_bridge_frontier_latest.json")
    run(root, out_txt, out_json)


if __name__ == "__main__":
    main()
