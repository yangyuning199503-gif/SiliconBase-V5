from __future__ import annotations

import argparse
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import requests

FLASH_API = "https://api.theblockbeats.news/v1/open-api/open-flash"
ARTICLE_API = "https://api.theblockbeats.news/v1/open-api/open-information"
RSS_NEWSFLASH = "https://api.theblockbeats.news/v2/rss/newsflash"
RSS_ARTICLE = "https://api.theblockbeats.news/v2/rss/article"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
RISK_KEYWORDS = [
    "hack", "exploit", "attack", "security incident", "security breach", "breach",
    "bankruptcy", "liquidation", "outage", "downtime", "delist", "war", "missile",
    "tariff", "sanction", "lawsuit", "suspend withdrawals", "暂停提现", "被盗", "黑客",
    "攻击", "漏洞", "破产", "清算", "爆仓", "下架", "战争", "袭击", "制裁", "冻结",
]
MACRO_KEYWORDS = [
    "fed", "fomc", "powell", "cpi", "ppi", "nfp", "nonfarm", "ecb", "boj",
    "rate hike", "rate cut", "美联储", "非农", "利率", "降息", "加息",
]
EXCHANGE_KEYWORDS = [
    "binance", "okx", "bybit", "coinbase", "kraken", "bitget", "backpack", "hyperliquid", "交易所",
]


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _clean_text(s: Any) -> str:
    s = "" if s is None else str(s)
    s = s.replace("\xa0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _fmt_epoch_utc(v: Any) -> str:
    if v in (None, "", 0, "0"):
        return ""
    try:
        iv = int(float(str(v)))
        if iv > 10_000_000_000:
            iv = iv // 1000
        return datetime.fromtimestamp(iv, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S+00:00")
    except Exception:
        return _clean_text(v)


def _tags_for_text(title: str, content: str) -> list[str]:
    text = (title + " " + content).lower()
    tags: list[str] = []
    if any(k in text for k in RISK_KEYWORDS):
        tags.append("risk")
    if any(k in text for k in MACRO_KEYWORDS):
        tags.append("macro")
    if any(k in text for k in EXCHANGE_KEYWORDS):
        tags.append("exchange")
    if not tags:
        tags.append("other")
    return tags


def _get_json(session: requests.Session, url: str, *, params: dict[str, Any], timeout: int) -> dict[str, Any]:
    r = session.get(url, params=params, timeout=timeout, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    r.raise_for_status()
    obj = r.json()
    if not isinstance(obj, dict):
        raise ValueError("response_not_dict")
    return obj


def _extract_api_rows(obj: dict[str, Any]) -> list[dict[str, Any]]:
    data = obj.get("data")
    if not isinstance(data, dict):
        return []
    rows = data.get("data")
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        title = _clean_text(raw.get("title"))
        content = _clean_text(raw.get("content") or raw.get("description"))
        if not title:
            continue
        out.append({
            "title": title,
            "content": content,
            "url": _clean_text(raw.get("link") or raw.get("url")),
            "ts_utc": _fmt_epoch_utc(raw.get("create_time")),
            "tags": _tags_for_text(title, content),
        })
    return out


def _get_rss_items(session: requests.Session, url: str, timeout: int) -> list[dict[str, Any]]:
    r = session.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml"})
    r.raise_for_status()
    root = ET.fromstring(r.text)
    out: list[dict[str, Any]] = []
    for item in root.findall(".//item"):
        title = _clean_text(item.findtext("title"))
        desc = _clean_text(item.findtext("description"))
        link = _clean_text(item.findtext("link"))
        pub = _clean_text(item.findtext("pubDate"))
        if not title:
            continue
        out.append({
            "title": title,
            "content": desc,
            "url": link,
            "ts_utc": pub,
            "tags": _tags_for_text(title, desc),
        })
    return out


def _dedup(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        key = (_clean_text(row.get("title")), _clean_text(row.get("url")))
        if not key[0] or key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def build_report(project_dir: Path, timeout: int, size: int) -> str:
    session = requests.Session()
    params = {"page": 1, "size": max(3, int(size)), "type": "push", "lang": "cn"}
    notes: list[str] = []
    flash_rows: list[dict[str, Any]] = []
    article_rows: list[dict[str, Any]] = []
    flash_source = FLASH_API
    article_source = ARTICLE_API

    try:
        flash_rows = _extract_api_rows(_get_json(session, FLASH_API, params=params, timeout=timeout))
    except Exception as e:
        notes.append(f"flash_api_error={e}")
        flash_source = RSS_NEWSFLASH
        try:
            flash_rows = _get_rss_items(session, RSS_NEWSFLASH, timeout)
            notes.append("flash_fallback=rss")
        except Exception as e2:
            notes.append(f"flash_rss_error={e2}")

    try:
        article_rows = _extract_api_rows(_get_json(session, ARTICLE_API, params=params, timeout=timeout))
    except Exception as e:
        notes.append(f"article_api_error={e}")
        article_source = RSS_ARTICLE
        try:
            article_rows = _get_rss_items(session, RSS_ARTICLE, timeout)
            notes.append("article_fallback=rss")
        except Exception as e2:
            notes.append(f"article_rss_error={e2}")

    flash_rows = _dedup(flash_rows)[: max(3, int(size))]
    article_rows = _dedup(article_rows)[: max(3, int(size))]
    risk_rows = [x for x in (flash_rows + article_rows) if ("risk" in (x.get("tags") or []) or "macro" in (x.get("tags") or []))]
    status = "ok" if (flash_rows or article_rows) else "failed"

    lines: list[str] = []
    lines.append(f"status: {status}")
    lines.append(f"ts_utc: {_utc_now_text()}")
    lines.append(f"project_dir: {project_dir}")
    lines.append(f"flash_source: {flash_source}")
    lines.append(f"article_source: {article_source}")
    lines.append(f"flash_items: {len(flash_rows)}")
    lines.append(f"article_items: {len(article_rows)}")
    lines.append(f"risk_hits: {len(risk_rows)}")
    lines.append("use_decision: discovery_only")
    lines.append("system_action: do_not_trade_directly")
    lines.append("recommendation: use_for_lead_discovery_then_confirm_with_coinglass_or_jin10")
    lines.append(f"top_risk: {_clean_text(risk_rows[0].get('title')) if risk_rows else ''}")
    lines.append(f"notes: {' | '.join(notes)}")
    lines.append("")
    lines.append("[flash]")
    if flash_rows:
        for row in flash_rows:
            lines.append(f"- {'/'.join(row.get('tags') or ['other'])} | {row.get('ts_utc') or '-'} | {row.get('title')} | {row.get('url') or '-'}")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("[article]")
    if article_rows:
        for row in article_rows:
            lines.append(f"- {'/'.join(row.get('tags') or ['other'])} | {row.get('ts_utc') or '-'} | {row.get('title')} | {row.get('url') or '-'}")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("[risk_candidates]")
    if risk_rows:
        for row in risk_rows[: max(5, int(size))]:
            lines.append(f"- {'/'.join(row.get('tags') or ['other'])} | {row.get('ts_utc') or '-'} | {row.get('title')} | {row.get('url') or '-'}")
    else:
        lines.append("- none")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="BlockBeats official REST/RSS probe (no trading action)")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--timeout", type=int, default=15)
    ap.add_argument("--size", type=int, default=8)
    ap.add_argument("--out", default="~/Downloads/blockbeats_latest.txt")
    args = ap.parse_args()

    project_dir = Path(args.project_dir).expanduser().resolve()
    out_path = Path(args.out).expanduser()
    report = build_report(project_dir=project_dir, timeout=max(5, int(args.timeout)), size=max(3, int(args.size)))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print(report, end="")


if __name__ == "__main__":
    main()
