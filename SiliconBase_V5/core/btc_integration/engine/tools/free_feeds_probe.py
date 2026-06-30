from __future__ import annotations

import argparse
import html
import math
import re
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import requests

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
TIMEOUT = 12

BLOCKBEATS_FLASH_API = "https://api.theblockbeats.news/v1/open-api/open-flash"
BLOCKBEATS_ARTICLE_API = "https://api.theblockbeats.news/v1/open-api/open-information"
BLOCKBEATS_RSS_FLASH = "https://api.theblockbeats.news/v2/rss/newsflash"
BLOCKBEATS_RSS_ARTICLE = "https://api.theblockbeats.news/v2/rss/article"

BINANCE_FAPI = "https://fapi.binance.com"
DERIBIT_API = "https://www.deribit.com/api/v2"
ALT_FNG = "https://api.alternative.me/fng/"

SEC_RSS_PRESS = "https://www.sec.gov/news/pressreleases.rss"
CFTC_RSS_PRESS = "https://www.cftc.gov/RSS/RSSGP/rssgp.xml"
DOJ_API_PRESS = "https://www.justice.gov/api/v1/press_releases.json"
DOJ_RSS_PRESS = "https://www.justice.gov/news/rss?field_component=376&require_all=0&search_api_language=en&show_public_archived=0&type%5B0%5D=image_gallery&type%5B1%5D=press_release&type%5B2%5D=speech&type%5B3%5D=youtube_video"

RISK_KEYWORDS = [
    "hack", "exploit", "attack", "security", "breach", "bankruptcy", "liquidation",
    "delist", "war", "missile", "sanction", "lawsuit", "被盗", "黑客", "攻击",
    "漏洞", "清算", "爆仓", "战争", "袭击", "制裁", "冻结", "暂停提现",
]
MACRO_KEYWORDS = [
    "fed", "fomc", "powell", "cpi", "ppi", "nfp", "nonfarm", "ecb", "boj", "pce",
    "利率", "加息", "降息", "非农", "通胀", "就业", "央行",
]
EXCHANGE_KEYWORDS = [
    "binance", "okx", "bybit", "coinbase", "kraken", "bitget", "hyperliquid", "交易所",
]

CRYPTO_CONTEXT_KEYWORDS = [
    "crypto", "cryptocurrency", "digital asset", "digital assets", "blockchain", "token", "tokens",
    "defi", "web3", "链上", "加密", "数字资产", "代币", "公链",
]
ASSET_KEYWORDS: dict[str, list[str]] = {
    "btc": ["btc", "bitcoin", "比特币"],
    "eth": ["eth", "ethereum", "以太坊"],
    "bnb": ["bnb", "binance coin", "币安币"],
    "sol": ["sol", "solana", "索拉纳"],
}
WHALE_KEYWORDS = [
    "whale", "巨鲸", "smart money", "lookonchain", "onchain lens", "arkham", "nansen", "链上侦探", "链上",
]
FLOW_KEYWORDS = [
    "withdraw", "withdrawal", "deposit", "deposited", "inflow", "outflow", "transfer", "moved", "accumulated",
    "sold", "bought", "netflow", "提币", "提现", "转入", "转出", "流入", "流出", "增持", "减持", "买入", "卖出", "累积", "累计"
]
EVENT_RELEVANCE_KEYWORDS = [
    "etf", "stablecoin", "reserve", "liquidation", "bankruptcy", "lawsuit", "doj", "sec", "cftc", "hack", "exploit",
    "sanction", "war", "missile", "attack", "tariff", "监管", "诉讼", "黑客", "被盗", "清算", "爆仓", "战争", "袭击", "制裁"
]
DISTRACTOR_TECH_KEYWORDS = [
    "tesla", "特斯拉", "nvidia", "英伟达", "chip", "chips", "芯片", "ai", "robotaxi", "机器人", "apple", "苹果",
    "microsoft", "微软", "meta", "google", "谷歌", "amazon", "亚马逊", "台积电", "tsmc"
]

FEATURE_STORY_KEYWORDS = [
    "专访", "解读", "往事", "复盘", "深度", "观察", "故事", "军备赛", "入场券",
    "生存指南", "写给", "盘点", "长文", "研报", "周报", "月报", "路线图", "简史"
]

PRICE_IMPACT_FLOW_KEYWORDS = [
    "withdraw", "withdrawal", "deposit", "deposited", "transfer", "moved", "migrate", "inflow", "outflow",
    "提币", "提现", "充币", "充值", "转入", "转出", "流入", "流出", "转移"
]
DERIV_STRESS_KEYWORDS = [
    "liquidation", "liquidated", "margin", "collateral", "top up", "added collateral", "funding", "open interest",
    "清算", "爆仓", "补保证金", "保证金", "抵押", "未平仓", "持仓量", "资金费率"
]
BALANCE_SHEET_KEYWORDS = [
    "etf", "treasury", "reserve", "buyback", "buy", "sell", "accumulate", "dump",
    "储备", "金库", "增持", "减持", "买入", "卖出", "回购", "配置"
]
LOW_SIGNAL_TOPIC_KEYWORDS = [
    "往事", "简史", "复盘", "专访", "解读", "观察", "故事", "军备赛", "入场券", "生存指南"
]

_FLOW_AMOUNT_RE = re.compile(
    r"(?:(?:\d+[\.,]?\d*)\s*(?:枚|万枚|亿美元|万美元|BTC|ETH|BNB|SOL|USDT|USD))",
    re.IGNORECASE,
)



def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_text() -> str:
    return _utc_now().strftime("%Y-%m-%d %H:%M:%S")


def _clean_text(v: Any) -> str:
    s = "" if v is None else str(v)
    s = s.replace("\xa0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _strip_html(v: Any) -> str:
    s = "" if v is None else str(v)
    s = html.unescape(s)
    s = re.sub(r"<[^>]+>", " ", s)
    return _clean_text(s)




def _clip_preview(v: Any, limit: int = 220) -> str:
    s = _strip_html(v)
    return s[:limit].strip()

def _fmt_epoch_utc(v: Any) -> str:
    if v in (None, "", 0, "0"):
        return ""
    try:
        iv = int(float(str(v)))
        if iv > 10_000_000_000:
            iv //= 1000
        return datetime.fromtimestamp(iv, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S+00:00")
    except Exception:
        return _clean_text(v)


def _safe_float(v: Any) -> float | None:
    try:
        if v in (None, "", "null"):
            return None
        return float(str(v))
    except Exception:
        return None


def _fmt_num(v: float | None, digits: int = 4) -> str:
    if v is None or not math.isfinite(v):
        return ""
    return f"{v:.{digits}f}"


def _http_get(session: requests.Session, url: str, *, params: dict[str, Any] | None = None, accept: str | None = None) -> requests.Response:
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    r = session.get(url, params=params or {}, timeout=TIMEOUT, headers=headers)
    r.raise_for_status()
    return r


def _json_get(session: requests.Session, url: str, *, params: dict[str, Any] | None = None) -> Any:
    return _http_get(session, url, params=params, accept="application/json").json()


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


# ---------- BlockBeats ----------

def _extract_blockbeats_rows(obj: Any) -> list[dict[str, Any]]:
    if not isinstance(obj, dict):
        return []
    data = obj.get("data")
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        title = _clean_text(raw.get("title"))
        content = _clip_preview(raw.get("content") or raw.get("description"), 220)
        if not title:
            continue
        out.append(
            {
                "title": title,
                "content": content,
                "url": _clean_text(raw.get("link") or raw.get("url")),
                "ts_utc": _fmt_epoch_utc(raw.get("create_time")),
                "tags": _tags_for_text(title, content),
            }
        )
    return out


def _rss_rows(session: requests.Session, url: str) -> list[dict[str, Any]]:
    try:
        text = _http_get(session, url, accept="application/rss+xml, application/xml, text/xml").text
        root = ET.fromstring(text)
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for item in root.findall(".//item"):
        title = _clean_text(item.findtext("title"))
        if not title:
            continue
        desc = _clip_preview(item.findtext("description"), 220)
        out.append(
            {
                "title": title,
                "content": desc,
                "url": _clean_text(item.findtext("link")),
                "ts_utc": _clean_text(item.findtext("pubDate")),
                "tags": _tags_for_text(title, desc),
            }
        )
    return out


def _contains_any(text: str, keywords: Iterable[str]) -> bool:
    blob = text.lower()
    return any(k in blob for k in keywords)


def _parse_maybe_ts(text: str) -> float:
    try:
        ts = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.timestamp()
    except Exception:
        pass
    for fmt in ["%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%d %H:%M:%S+00:00", "%Y-%m-%d %H:%M:%S"]:
        try:
            dt = datetime.strptime(str(text), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except Exception:
            continue
    return 0.0


def _dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        key = _clean_text(row.get("title")).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _blockbeats_score(row: dict[str, Any]) -> tuple[float, list[str]]:
    title = _clean_text(row.get("title"))
    content = _clean_text(row.get("content"))
    title_l = title.lower()
    content_short = _clip_preview(content, 120)
    text = f"{title} {content_short}".lower()
    score = 0.0
    signals: list[str] = []

    asset_hits = []
    for asset, kws in ASSET_KEYWORDS.items():
        if _contains_any(text, kws):
            asset_hits.append(asset)
    title_asset_hits = []
    for asset, kws in ASSET_KEYWORDS.items():
        if _contains_any(title_l, kws):
            title_asset_hits.append(asset)
    if asset_hits:
        score += 2.8 + 0.8 * min(len(asset_hits), 2)
        signals.append("asset:" + "/".join(asset_hits[:3]))
    if title_asset_hits:
        score += 1.4
        signals.append("title_asset")

    crypto_context = _contains_any(text, CRYPTO_CONTEXT_KEYWORDS) or bool(asset_hits)
    whale_hit = _contains_any(text, WHALE_KEYWORDS)
    flow_hit = _contains_any(text, FLOW_KEYWORDS)
    exchange_hit = _contains_any(text, EXCHANGE_KEYWORDS)
    event_hit = _contains_any(text, EVENT_RELEVANCE_KEYWORDS)
    macro_hit = _contains_any(text, MACRO_KEYWORDS)
    risk_hit = _contains_any(text, RISK_KEYWORDS)
    price_flow_hit = _contains_any(text, PRICE_IMPACT_FLOW_KEYWORDS)
    deriv_stress_hit = _contains_any(text, DERIV_STRESS_KEYWORDS)
    balance_sheet_hit = _contains_any(text, BALANCE_SHEET_KEYWORDS)

    title_whale = _contains_any(title_l, WHALE_KEYWORDS)
    title_flow = _contains_any(title_l, FLOW_KEYWORDS)
    title_exchange = _contains_any(title_l, EXCHANGE_KEYWORDS)
    title_risk = _contains_any(title_l, RISK_KEYWORDS)
    title_macro = _contains_any(title_l, MACRO_KEYWORDS)
    title_feature_story = _contains_any(title_l, FEATURE_STORY_KEYWORDS)
    title_has_flow_amount = bool(_FLOW_AMOUNT_RE.search(title))
    title_price_flow = _contains_any(title_l, PRICE_IMPACT_FLOW_KEYWORDS)
    title_deriv_stress = _contains_any(title_l, DERIV_STRESS_KEYWORDS)
    title_balance_sheet = _contains_any(title_l, BALANCE_SHEET_KEYWORDS)

    asset_flow_dominant = False
    if whale_hit and flow_hit:
        score += 6.5
        signals.append("whale_flow")
        if asset_hits:
            score += 3.4
            signals.append("asset_whale_flow")
            asset_flow_dominant = True
        if exchange_hit:
            score += 1.4
            signals.append("exchange_confirm")
    elif whale_hit:
        score += 4.8
        signals.append("whale")
        if asset_hits:
            score += 2.2
            signals.append("asset_whale")
            asset_flow_dominant = True
    elif flow_hit and exchange_hit:
        score += 4.0
        signals.append("exchange_flow")
        if asset_hits:
            score += 2.8
            signals.append("asset_exchange_flow")
            asset_flow_dominant = True
    elif flow_hit:
        score += 2.4
        signals.append("flow")
        if asset_hits:
            score += 1.2
            signals.append("asset_flow")

    if title_whale and title_flow:
        score += 4.2
        signals.append("title_whale_flow")
        if title_asset_hits:
            score += 2.4
            signals.append("title_asset_whale_flow")
            asset_flow_dominant = True
    elif title_whale:
        score += 2.6
        signals.append("title_whale")
        if title_asset_hits:
            score += 1.4
            signals.append("title_asset_whale")
            asset_flow_dominant = True
    elif title_flow and title_exchange:
        score += 2.2
        signals.append("title_exchange_flow")
        if title_asset_hits:
            score += 1.8
            signals.append("title_asset_exchange_flow")
            asset_flow_dominant = True
    elif title_flow:
        score += 1.0
        signals.append("title_flow")
    if title_risk:
        score += 1.4
        signals.append("title_risk")
    if title_has_flow_amount and (title_flow or title_whale or title_exchange or bool(title_asset_hits)):
        score += 2.6
        signals.append("title_amount_flow")
    if title_macro:
        score += 0.4
        signals.append("title_macro")

    if exchange_hit:
        score += 1.6
        signals.append("exchange")
    if risk_hit:
        score += 2.2
        if asset_flow_dominant and not asset_hits:
            score += 0.0
        signals.append("risk")
    if event_hit:
        score += 2.2
        signals.append("event")
    if macro_hit:
        score += 1.2 if crypto_context else 0.3
        if asset_flow_dominant and not crypto_context:
            score -= 0.3
        signals.append("macro")

    if crypto_context and _contains_any(text, ["etf", "stablecoin", "liquidation", "lawsuit", "hack", "exploit", "doj", "sec", "cftc", "监管", "诉讼", "清算", "被盗"]):
        score += 1.8

    # Price-impact first: exchange flow / derivative stress / direct balance-sheet action
    title_direct_market_action = bool(title_asset_hits or title_whale or title_flow or title_exchange or title_risk or title_macro or title_deriv_stress or title_balance_sheet)
    if title_exchange and title_price_flow and title_has_flow_amount and title_asset_hits:
        score += 12.0
        signals.append("title_exchange_asset_amount")
    elif title_exchange and title_price_flow and title_asset_hits:
        score += 9.0
        signals.append("title_exchange_asset_flow")
    elif title_whale and title_has_flow_amount and title_asset_hits:
        score += 9.0
        signals.append("title_whale_amount")
    elif title_deriv_stress and title_has_flow_amount:
        score += 8.0
        signals.append("title_deriv_stress_amount")
    elif title_deriv_stress and (title_asset_hits or title_exchange):
        score += 6.4
        signals.append("title_deriv_stress")
    elif title_balance_sheet and title_asset_hits:
        score += 5.0
        signals.append("title_balance_sheet")

    if exchange_hit and price_flow_hit and asset_hits:
        score += 6.0
        signals.append("asset_exchange_flow_confirm")
    if deriv_stress_hit and (asset_hits or exchange_hit):
        score += 5.2
        signals.append("deriv_stress_confirm")
    if balance_sheet_hit and asset_hits:
        score += 3.4
        signals.append("balance_sheet_confirm")

    distractor = _contains_any(text, DISTRACTOR_TECH_KEYWORDS)
    distractor_title = _contains_any(title_l, DISTRACTOR_TECH_KEYWORDS)
    core_market_signal = bool(asset_hits) or whale_hit or flow_hit or exchange_hit or risk_hit or event_hit
    if asset_flow_dominant:
        score += 1.0
        signals.append("dominant_asset_flow")
    if distractor and not core_market_signal:
        score -= 9.0
        signals.append("generic_tech_penalty")
    elif distractor_title and not core_market_signal:
        score -= 5.0
        signals.append("title_generic_tech_penalty")
    elif distractor and crypto_context and not asset_hits and not whale_hit and not flow_hit:
        score -= 3.2
        signals.append("weak_crypto_context")

    if not crypto_context and not risk_hit and not macro_hit and not exchange_hit and not whale_hit and not flow_hit:
        score -= 3.0
        signals.append("low_market_relevance")

    title_concrete_market = bool(title_asset_hits or title_whale or title_flow or title_exchange or title_risk or title_macro)
    if title_feature_story and not title_concrete_market:
        score -= 4.2
        signals.append("feature_story_penalty")
    elif title_feature_story and not (title_whale or title_flow or title_exchange):
        score -= 1.6
        signals.append("soft_feature_penalty")

    if title_feature_story and not (title_whale or title_flow or title_exchange or bool(title_asset_hits)) and (whale_hit or flow_hit or exchange_hit):
        score -= 16.0
        signals.append("feature_content_downgrade")
    elif (whale_hit or flow_hit or exchange_hit or event_hit) and not title_concrete_market and _clean_text(row.get("source")) != "flash":
        score -= 12.0
        signals.append("content_only_market_penalty")

    if _contains_any(title_l, LOW_SIGNAL_TOPIC_KEYWORDS) and not title_direct_market_action:
        score -= 5.0
        signals.append("low_signal_topic_penalty")

    if title and len(title) <= 80:
        score += 0.2
    source = _clean_text(row.get("source") or "")
    if source == "flash":
        score += 2.2 if title_direct_market_action else 0.8
        signals.append("flash_fresh")
    return score, signals[:6]

def _rank_blockbeats_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for row in _dedupe_rows(rows):
        score, signals = _blockbeats_score(row)
        new_row = dict(row)
        new_row["score"] = round(score, 3)
        new_row["signals"] = signals
        signal_set = set(signals)
        hard_relevant = bool({"whale_flow", "whale", "exchange_flow", "exchange", "risk", "event", "title_whale_flow", "title_whale", "title_exchange_flow", "title_asset", "title_risk", "asset_whale_flow", "asset_exchange_flow", "title_asset_whale_flow", "dominant_asset_flow"}.intersection(signal_set))
        if score >= 2.0 or hard_relevant or {"risk", "macro", "exchange"}.intersection(set(new_row.get("tags", []))):
            ranked.append(new_row)
    ranked.sort(key=lambda r: (float(r.get("score", 0.0)), _parse_maybe_ts(_clean_text(r.get("ts_utc")))), reverse=True)
    return ranked

def probe_blockbeats(session: requests.Session) -> tuple[dict[str, Any], list[str]]:
    notes: list[str] = []
    try:
        flash_obj = _json_get(session, BLOCKBEATS_FLASH_API, params={"size": 10, "page": 1, "type": "push", "lang": "cn"})
        article_obj = _json_get(session, BLOCKBEATS_ARTICLE_API, params={"size": 10, "page": 1, "lang": "cn"})
        flash_rows = _extract_blockbeats_rows(flash_obj)
        for row in flash_rows:
            row["source"] = "flash"
        article_rows = _extract_blockbeats_rows(article_obj)
        for row in article_rows:
            row["source"] = "article"
    except Exception as e:
        notes.append(f"api_error={type(e).__name__}:{e}")
        flash_rows = []
        article_rows = []
    if not flash_rows:
        flash_rows = _rss_rows(session, BLOCKBEATS_RSS_FLASH)
        for row in flash_rows:
            row["source"] = "flash_rss"
        if flash_rows:
            notes.append("flash_fallback=rss")
    if not article_rows:
        article_rows = _rss_rows(session, BLOCKBEATS_RSS_ARTICLE)
        for row in article_rows:
            row["source"] = "article_rss"
        if article_rows:
            notes.append("article_fallback=rss")
    ranked = _rank_blockbeats_rows(flash_rows + article_rows)
    top = ranked[:5]
    out = {
        "status": "ok" if (flash_rows or article_rows) else "failed",
        "flash_items": len(flash_rows),
        "article_items": len(article_rows),
        "risk_hits": len(ranked),
        "top_risk": top[0]["title"] if top else "",
        "top_signals": top[0].get("signals", []) if top else [],
        "use": "discovery_only",
        "recommendation": "按资产相关性/巨鲸链上/监管宏观排序，压低泛科技标题；先发现，再由CoinGlass/结构化源确认；不直接交易",
        "preview": top,
    }
    return out, notes


# ---------- Binance ----------

def _latest_list_row(obj: Any) -> dict[str, Any]:
    if isinstance(obj, list) and obj:
        row = obj[-1]
        return row if isinstance(row, dict) else {}
    if isinstance(obj, dict):
        # some endpoints may return dict directly
        return obj
    return {}


def _binance_metric(session: requests.Session, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
    obj = _json_get(session, BINANCE_FAPI + endpoint, params=params)
    row = _latest_list_row(obj)
    if row:
        return row
    if isinstance(obj, list) and obj:
        return obj[-1] if isinstance(obj[-1], dict) else {}
    return {}


def _crowding_state(global_ls: float | None, top_acc_ls: float | None, top_pos_ls: float | None, taker_ls: float | None) -> str:
    long_score = 0
    short_score = 0
    checks = [
        (global_ls, 1.20, 1 / 1.20),
        (top_acc_ls, 1.20, 1 / 1.20),
        (top_pos_ls, 1.25, 1 / 1.25),
        (taker_ls, 1.15, 1 / 1.15),
    ]
    for v, hi, lo in checks:
        if v is None:
            continue
        if v >= hi:
            long_score += 1
        elif v <= lo:
            short_score += 1
    if long_score >= 2 and long_score >= short_score + 1:
        return "crowded_long"
    if short_score >= 2 and short_score >= long_score + 1:
        return "crowded_short"
    return "neutral"


def probe_binance_crowding(session: requests.Session, symbol: str) -> tuple[dict[str, Any], list[str]]:
    notes: list[str] = []
    try:
        common = {"symbol": symbol, "period": "15m", "limit": 2}
        global_row = _binance_metric(session, "/futures/data/globalLongShortAccountRatio", common)
        top_acc_row = _binance_metric(session, "/futures/data/topLongShortAccountRatio", common)
        top_pos_row = _binance_metric(session, "/futures/data/topLongShortPositionRatio", common)
        taker_row = _binance_metric(session, "/futures/data/takerlongshortRatio", common)
        oi_row = _binance_metric(session, "/futures/data/openInterestHist", common)
        funding_row = _binance_metric(session, "/fapi/v1/fundingRate", {"symbol": symbol, "limit": 2})
        mark_row = _json_get(session, BINANCE_FAPI + "/fapi/v1/premiumIndex", params={"symbol": symbol})
    except Exception as e:
        return {"status": "failed", "symbol": symbol, "error": f"{type(e).__name__}:{e}"}, notes

    global_ls = _safe_float(global_row.get("longShortRatio"))
    top_acc_ls = _safe_float(top_acc_row.get("longShortRatio"))
    top_pos_ls = _safe_float(top_pos_row.get("longShortRatio"))
    taker_ls = _safe_float(taker_row.get("buySellRatio") or taker_row.get("longShortRatio"))
    oi = _safe_float(oi_row.get("sumOpenInterest") or oi_row.get("openInterest"))
    oi_value = _safe_float(oi_row.get("sumOpenInterestValue"))
    funding = _safe_float(funding_row.get("fundingRate"))
    mark_price = _safe_float(mark_row.get("markPrice") if isinstance(mark_row, dict) else None)
    crowding = _crowding_state(global_ls, top_acc_ls, top_pos_ls, taker_ls)

    return (
        {
            "status": "ok",
            "symbol": symbol,
            "global_ls": global_ls,
            "top_acc_ls": top_acc_ls,
            "top_pos_ls": top_pos_ls,
            "taker_ls": taker_ls,
            "oi": oi,
            "oi_value": oi_value,
            "funding": funding,
            "mark_price": mark_price,
            "crowding": crowding,
            "use": "risk_layer_candidate",
        },
        notes,
    )


# ---------- Deribit ----------

def _deribit_get(session: requests.Session, method: str, params: dict[str, Any]) -> Any:
    obj = _json_get(session, f"{DERIBIT_API}/{method}", params=params)
    if isinstance(obj, dict) and "result" in obj:
        return obj.get("result")
    return obj


def _extract_deribit_last_close(result: Any) -> float | None:
    # expected often: {"data": [[ts, open, high, low, close], ...]}
    if isinstance(result, dict):
        data = result.get("data")
        if isinstance(data, list) and data:
            last = data[-1]
            if isinstance(last, (list, tuple)) and len(last) >= 5:
                return _safe_float(last[4])
            if isinstance(last, dict):
                for k in ("close", "c", "value"):
                    v = _safe_float(last.get(k))
                    if v is not None:
                        return v
    if isinstance(result, list) and result:
        last = result[-1]
        if isinstance(last, (list, tuple)) and len(last) >= 5:
            return _safe_float(last[4])
        if isinstance(last, dict):
            for k in ("close", "c", "value"):
                v = _safe_float(last.get(k))
                if v is not None:
                    return v
    return None


def _sum_open_interest(rows: Any) -> tuple[int, float | None]:
    if not isinstance(rows, list):
        return 0, None
    total = 0.0
    count = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        v = _safe_float(row.get("open_interest"))
        if v is None:
            continue
        total += v
        count += 1
    return count, (total if count else None)


def probe_deribit(session: requests.Session) -> tuple[dict[str, Any], list[str]]:
    notes: list[str] = []
    try:
        end_ms = int(_utc_now().timestamp() * 1000)
        start_ms = int((_utc_now() - timedelta(hours=24)).timestamp() * 1000)
        vix_res = _deribit_get(
            session,
            "public/get_volatility_index_data",
            {
                "currency": "BTC",
                "start_timestamp": start_ms,
                "end_timestamp": end_ms,
                "resolution": "60",
            },
        )
        dvol_last = _extract_deribit_last_close(vix_res)
        perp = _deribit_get(session, "public/ticker", {"instrument_name": "BTC-PERPETUAL"})
        option_rows = _deribit_get(session, "public/get_book_summary_by_currency", {"currency": "BTC", "kind": "option"})
        fut_rows = _deribit_get(session, "public/get_book_summary_by_currency", {"currency": "BTC", "kind": "future"})
    except Exception as e:
        return {"status": "failed", "error": f"{type(e).__name__}:{e}"}, notes

    option_count, option_oi = _sum_open_interest(option_rows)
    future_count, future_oi = _sum_open_interest(fut_rows)
    perp_mark = None
    perp_oi = None
    if isinstance(perp, dict):
        perp_mark = _safe_float(perp.get("mark_price"))
        perp_oi = _safe_float(perp.get("open_interest"))

    if dvol_last is not None and dvol_last >= 75:
        vol_regime = "very_high_vol"
    elif dvol_last is not None and dvol_last >= 55:
        vol_regime = "elevated_vol"
    else:
        vol_regime = "normal_vol"

    return (
        {
            "status": "ok",
            "btc_dvol_last": dvol_last,
            "btc_perp_mark": perp_mark,
            "btc_perp_oi": perp_oi,
            "btc_option_instruments": option_count,
            "btc_option_oi_sum": option_oi,
            "btc_future_instruments": future_count,
            "btc_future_oi_sum": future_oi,
            "vol_regime": vol_regime,
            "use": "regime_risk_candidate",
        },
        notes,
    )


# ---------- Alternative.me Fear & Greed ----------

def probe_fng(session: requests.Session) -> tuple[dict[str, Any], list[str]]:
    notes: list[str] = []
    try:
        obj = _json_get(session, ALT_FNG, params={"limit": 1, "format": "json"})
        data = obj.get("data") if isinstance(obj, dict) else None
        row = data[0] if isinstance(data, list) and data else {}
        value = _safe_float(row.get("value")) if isinstance(row, dict) else None
        label = _clean_text(row.get("value_classification")) if isinstance(row, dict) else ""
        ts = _fmt_epoch_utc(row.get("timestamp")) if isinstance(row, dict) else ""
    except Exception as e:
        return {"status": "failed", "error": f"{type(e).__name__}:{e}"}, notes
    if value is not None and value <= 20:
        regime = "extreme_fear"
    elif value is not None and value >= 80:
        regime = "extreme_greed"
    else:
        regime = "mid"
    return (
        {
            "status": "ok",
            "value": value,
            "label": label,
            "ts_utc": ts,
            "regime": regime,
            "use": "slow_regime_only",
        },
        notes,
    )



# ---------- Official regulatory feeds ----------

REGULATORY_CRYPTO_KEYWORDS = [
    "crypto", "cryptocurrency", "digital asset", "digital assets", "stablecoin", "stablecoins",
    "bitcoin", "btc", "ether", "eth", "solana", "sol", "xrp", "bnb", "binance", "coinbase",
    "kraken", "exchange", "etf", "etps", "token", "tokens", "blockchain", "defi", "web3",
]


def _regulatory_tags(title: str, content: str) -> list[str]:
    tags = _tags_for_text(title, content)
    if "regulatory" not in tags:
        tags.append("regulatory")
    return tags


def _filter_regulatory_rows(rows: list[dict[str, Any]], source_name: str) -> tuple[list[dict[str, Any]], int]:
    matched: list[dict[str, Any]] = []
    hits = 0
    for row in rows:
        title = _clean_text(row.get("title"))
        content = _clean_text(row.get("content"))
        blob = f"{title} {content}".lower()
        keep = any(k in blob for k in REGULATORY_CRYPTO_KEYWORDS)
        if keep:
            hits += 1
            new_row = dict(row)
            new_row["tags"] = _regulatory_tags(title, content)
            new_row["source"] = source_name
            matched.append(new_row)
    return matched, hits


def _regulatory_probe(session: requests.Session, source_name: str, url: str) -> tuple[dict[str, Any], list[str]]:
    notes: list[str] = []
    rows = _rss_rows(session, url)
    filtered, hits = _filter_regulatory_rows(rows, source_name)
    return (
        {
            "status": "ok" if rows else "failed",
            "source": source_name,
            "items": len(rows),
            "crypto_reg_hits": hits,
            "use": "discovery_only",
            "recommendation": "先做监管/执法发现层，再由事件库或人工确认；不直接交易",
            "preview": filtered[:5],
        },
        notes,
    )


def probe_sec(session: requests.Session) -> tuple[dict[str, Any], list[str]]:
    return _regulatory_probe(session, "SEC", SEC_RSS_PRESS)


def probe_cftc(session: requests.Session) -> tuple[dict[str, Any], list[str]]:
    return _regulatory_probe(session, "CFTC", CFTC_RSS_PRESS)


def _doj_api_rows(session: requests.Session, pages: int = 2) -> tuple[list[dict[str, Any]], list[str]]:
    notes: list[str] = []
    rows: list[dict[str, Any]] = []
    for page in range(max(1, pages)):
        try:
            obj = _json_get(
                session,
                DOJ_API_PRESS,
                params={
                    "sort": "date",
                    "direction": "DESC",
                    "pagesize": 50,
                    "page": page,
                    "fields": "title,url,date,body,teaser,topic,component",
                },
            )
        except Exception as e:
            notes.append(f"doj_api_error={type(e).__name__}:{e}")
            break
        data = obj.get("results") if isinstance(obj, dict) else None
        if not isinstance(data, list) or not data:
            if page == 0:
                notes.append("doj_api_empty")
            break
        for raw in data:
            if not isinstance(raw, dict):
                continue
            title = _clean_text(raw.get("title"))
            teaser = _strip_html(raw.get("teaser"))
            body = _strip_html(raw.get("body"))
            topic = _strip_html(raw.get("topic"))
            comps = raw.get("component")
            comp_names = []
            if isinstance(comps, list):
                for comp in comps:
                    if isinstance(comp, dict):
                        nm = _clean_text(comp.get("name"))
                        if nm:
                            comp_names.append(nm)
            content = _clean_text(" ".join([teaser, body, topic, " ".join(comp_names)]))
            if not title and not content:
                continue
            rows.append(
                {
                    "title": title,
                    "content": content,
                    "url": _clean_text(raw.get("url")),
                    "ts_utc": _fmt_epoch_utc(raw.get("date")),
                    "tags": _regulatory_tags(title, content),
                }
            )
        if len(data) < 50:
            break
    return rows, notes


def probe_doj(session: requests.Session) -> tuple[dict[str, Any], list[str]]:
    notes: list[str] = []
    rows, api_notes = _doj_api_rows(session)
    notes.extend(api_notes)
    source_detail = "api"
    if not rows:
        rows = _rss_rows(session, DOJ_RSS_PRESS)
        if rows:
            notes.append("doj_fallback=rss")
            source_detail = "rss"
    filtered, hits = _filter_regulatory_rows(rows, "DOJ")
    return (
        {
            "status": "ok" if rows else "failed",
            "source": "DOJ",
            "items": len(rows),
            "crypto_reg_hits": hits,
            "use": "discovery_only",
            "recommendation": "先做监管/执法发现层，再由事件库或人工确认；不直接交易",
            "preview": filtered[:5],
            "transport": source_detail,
        },
        notes,
    )


# ---------- Report ----------

def _render_preview_rows(rows: Iterable[dict[str, Any]], max_rows: int = 5) -> list[str]:
    out: list[str] = []
    for row in list(rows)[:max_rows]:
        tags = "/".join(row.get("tags", []))
        score = row.get("score")
        score_txt = "" if score in (None, "") else f" | score={score}"
        signals = row.get("signals") if isinstance(row.get("signals"), list) else []
        sig_txt = "" if not signals else f" | signals={'/'.join(str(x) for x in signals[:4])}"
        out.append(f"- {tags} | {row.get('ts_utc','')} | {row.get('title','')}{score_txt}{sig_txt} | {row.get('url','')}")
    return out


def build_report(project_dir: Path) -> str:
    lines: list[str] = []
    with requests.Session() as session:
        session.headers.update({"User-Agent": USER_AGENT})

        blockbeats, bb_notes = probe_blockbeats(session)
        btc_binance, btc_notes = probe_binance_crowding(session, "BTCUSDT")
        bnb_binance, bnb_notes = probe_binance_crowding(session, "BNBUSDT")
        deribit, deribit_notes = probe_deribit(session)
        fng, fng_notes = probe_fng(session)
        sec, sec_notes = probe_sec(session)
        cftc, cftc_notes = probe_cftc(session)
        doj, doj_notes = probe_doj(session)

    source_states = [
        blockbeats.get("status") == "ok",
        btc_binance.get("status") == "ok",
        bnb_binance.get("status") == "ok",
        deribit.get("status") == "ok",
        fng.get("status") == "ok",
        sec.get("status") == "ok",
        cftc.get("status") == "ok",
        doj.get("status") == "ok",
    ]
    if all(source_states):
        overall = "ok"
    elif any(source_states):
        overall = "partial"
    else:
        overall = "failed"

    jin10_needed_now = "no"
    jin10_buy_when = [
        "要把宏观事件暂停窗口自动化到分钟级",
        "A/B 证明免费源漏掉关键宏观/地缘快讯",
        "确定要用官方 API，而不是网页抓取",
    ]

    lines.append(f"status: {overall}")
    lines.append(f"ts_utc: {_utc_now_text()}")
    lines.append(f"project_dir: {project_dir}")
    lines.append(f"jin10_needed_now: {jin10_needed_now}")
    lines.append("use_now: BlockBeats=discovery_only | Binance=风险候选 | Deribit=波动/期权风险候选 | FNG=慢周期情绪 | SEC/CFTC/DOJ=监管发现层")
    lines.append("")

    lines.append("[summary]")
    lines.append(
        f"- BlockBeats | status={blockbeats.get('status')} | flash_items={blockbeats.get('flash_items')} | "
        f"article_items={blockbeats.get('article_items')} | risk_hits={blockbeats.get('risk_hits')} | use={blockbeats.get('use')}"
    )
    lines.append(
        f"- Binance BTCUSDT | status={btc_binance.get('status')} | crowding={btc_binance.get('crowding','')} | "
        f"global_ls={_fmt_num(_safe_float(btc_binance.get('global_ls')))} | top_pos_ls={_fmt_num(_safe_float(btc_binance.get('top_pos_ls')))} | "
        f"taker_ls={_fmt_num(_safe_float(btc_binance.get('taker_ls')))} | funding={_fmt_num(_safe_float(btc_binance.get('funding')), 6)}"
    )
    lines.append(
        f"- Binance BNBUSDT | status={bnb_binance.get('status')} | crowding={bnb_binance.get('crowding','')} | "
        f"global_ls={_fmt_num(_safe_float(bnb_binance.get('global_ls')))} | top_pos_ls={_fmt_num(_safe_float(bnb_binance.get('top_pos_ls')))} | "
        f"taker_ls={_fmt_num(_safe_float(bnb_binance.get('taker_ls')))} | funding={_fmt_num(_safe_float(bnb_binance.get('funding')), 6)}"
    )
    lines.append(
        f"- Deribit BTC | status={deribit.get('status')} | dvol={_fmt_num(_safe_float(deribit.get('btc_dvol_last')),2)} | "
        f"vol_regime={deribit.get('vol_regime','')} | option_oi_sum={_fmt_num(_safe_float(deribit.get('btc_option_oi_sum')),2)}"
    )
    lines.append(
        f"- Alternative FNG | status={fng.get('status')} | value={_fmt_num(_safe_float(fng.get('value')),0)} | label={fng.get('label','')} | regime={fng.get('regime','')}"
    )
    lines.append(
        f"- SEC Official | status={sec.get('status')} | items={sec.get('items')} | crypto_reg_hits={sec.get('crypto_reg_hits')} | use={sec.get('use')}"
    )
    lines.append(
        f"- CFTC Official | status={cftc.get('status')} | items={cftc.get('items')} | crypto_reg_hits={cftc.get('crypto_reg_hits')} | use={cftc.get('use')}"
    )
    lines.append(
        f"- DOJ Official | status={doj.get('status')} | items={doj.get('items')} | crypto_reg_hits={doj.get('crypto_reg_hits')} | use={doj.get('use')}"
    )
    lines.append("")

    lines.append("[decision]")
    lines.append("- 现在先不买 Jin10。")
    lines.append("- 先把免费结构化源接进来：Binance crowding + Deribit vol + Alternative FNG + SEC/CFTC/DOJ 官方发布。")
    lines.append("- BlockBeats 继续只做发现层，不直接触发交易。")
    lines.append("- Jin10 只有在免费源 A/B 仍漏宏观窗口时再买。")
    lines.append("")

    lines.append("[jin10_buy_when]")
    for row in jin10_buy_when:
        lines.append(f"- {row}")
    lines.append("")

    lines.append("[blockbeats_preview]")
    preview = blockbeats.get("preview") if isinstance(blockbeats, dict) else None
    if isinstance(preview, list) and preview:
        lines.extend(_render_preview_rows(preview, max_rows=5))
    else:
        lines.append("- none")
    lines.append("")

    lines.append("[binance_detail]")
    for row in [btc_binance, bnb_binance]:
        symbol = row.get("symbol", "")
        lines.append(
            f"- {symbol} | mark={_fmt_num(_safe_float(row.get('mark_price')),2)} | oi={_fmt_num(_safe_float(row.get('oi')),2)} | "
            f"oi_value={_fmt_num(_safe_float(row.get('oi_value')),2)} | global_ls={_fmt_num(_safe_float(row.get('global_ls')))} | "
            f"top_acc_ls={_fmt_num(_safe_float(row.get('top_acc_ls')))} | top_pos_ls={_fmt_num(_safe_float(row.get('top_pos_ls')))} | "
            f"taker_ls={_fmt_num(_safe_float(row.get('taker_ls')))} | funding={_fmt_num(_safe_float(row.get('funding')),6)} | crowding={row.get('crowding','')}"
        )
    lines.append("")

    lines.append("[deribit_detail]")
    lines.append(
        f"- BTC | dvol={_fmt_num(_safe_float(deribit.get('btc_dvol_last')),2)} | perp_mark={_fmt_num(_safe_float(deribit.get('btc_perp_mark')),2)} | "
        f"perp_oi={_fmt_num(_safe_float(deribit.get('btc_perp_oi')),2)} | option_instruments={deribit.get('btc_option_instruments','')} | "
        f"option_oi_sum={_fmt_num(_safe_float(deribit.get('btc_option_oi_sum')),2)} | future_oi_sum={_fmt_num(_safe_float(deribit.get('btc_future_oi_sum')),2)} | "
        f"vol_regime={deribit.get('vol_regime','')}"
    )
    lines.append("")

    lines.append("[fear_greed_detail]")
    lines.append(
        f"- value={_fmt_num(_safe_float(fng.get('value')),0)} | label={fng.get('label','')} | ts_utc={fng.get('ts_utc','')} | use={fng.get('use','')}"
    )
    lines.append("")

    lines.append("[regulatory_preview]")
    for src_name, row in [("SEC", sec), ("CFTC", cftc), ("DOJ", doj)]:
        preview = row.get("preview") if isinstance(row, dict) else None
        if isinstance(preview, list) and preview:
            lines.append(f"- {src_name}")
            lines.extend(_render_preview_rows(preview, max_rows=3))
        else:
            lines.append(f"- {src_name} | none")
    lines.append("")

    lines.append("[notes]")
    all_notes = bb_notes + btc_notes + bnb_notes + deribit_notes + fng_notes + sec_notes + cftc_notes + doj_notes
    if all_notes:
        for note in all_notes:
            lines.append(f"- {note}")
    else:
        lines.append("- none")
    lines.append("- 以上 crowding / vol / 情绪阈值都是启发式，只用于接源与初筛，不直接下单。")
    lines.append("- 后续若要进入风险层，先做 A/B；若要升 alpha，再做更严格回测。")
    return "\n".join(lines).strip() + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    project_dir = Path(args.project_dir).expanduser().resolve()
    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        text = build_report(project_dir)
    except Exception as e:
        text = (
            f"status: failed\n"
            f"ts_utc: {_utc_now_text()}\n"
            f"project_dir: {project_dir}\n"
            f"fatal_error: {type(e).__name__}:{e}\n"
            f"jin10_needed_now: no\n"
        )
    out.write_text(text, encoding="utf-8")
    print(str(out))


if __name__ == "__main__":
    main()
