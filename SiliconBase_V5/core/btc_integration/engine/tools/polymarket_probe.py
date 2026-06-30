from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import requests

DEFAULT_KEYWORDS = [
    "bitcoin",
    "btc",
    "crypto",
    "fed",
    "fomc",
    "rate",
    "cpi",
    "inflation",
    "war",
    "iran",
    "israel",
    "russia",
    "ukraine",
    "sec",
    "etf",
    "recession",
    "tariff",
]


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def _safe_float(x: Any) -> float | None:
    try:
        return float(x)
    except Exception:
        return None


def _pick_title(item: dict[str, Any]) -> str:
    for k in ["question", "title", "name", "slug"]:
        v = item.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return "-"


def _pick_probability(item: dict[str, Any]) -> float | None:
    candidates: list[float] = []
    for key in ["lastTradePrice", "probability", "yesPrice", "bestAsk", "bestBid", "marketPrice"]:
        v = _safe_float(item.get(key))
        if v is not None:
            candidates.append(v)
    prices = item.get("outcomePrices")
    if isinstance(prices, list) and prices:
        vals = [_safe_float(x) for x in prices]
        vals = [x for x in vals if x is not None]
        if vals:
            candidates.append(vals[0])
    for v in candidates:
        if v is None:
            continue
        if 0.0 <= v <= 1.0:
            return v
        if 1.0 < v <= 100.0:
            return v / 100.0
    return None


def _pick_liquidity(item: dict[str, Any]) -> float:
    for key in ["liquidity", "liquidityNum", "volume", "volumeNum", "volume24hr", "totalVolume"]:
        v = _safe_float(item.get(key))
        if v is not None:
            return float(v)
    return 0.0


def _pick_time(item: dict[str, Any]) -> str:
    for key in ["endDate", "end_date", "startDate", "createdAt", "created_at"]:
        v = item.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return "-"


def _fetch_json(url: str, timeout: int = 20) -> Any:
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "btc_system_v1/1.0"})
    r.raise_for_status()
    return r.json()


def _iter_market_like(payload: Any) -> Iterable[dict[str, Any]]:
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                yield item
        return
    if isinstance(payload, dict):
        for key in ["markets", "data", "events"]:
            val = payload.get(key)
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        yield item
                return
        yield payload


def _filter_items(items: list[dict[str, Any]], keywords: list[str], limit: int) -> list[dict[str, Any]]:
    kws = [k.lower() for k in keywords if k.strip()]
    picked: list[tuple[float, dict[str, Any]]] = []
    for item in items:
        title = _pick_title(item).lower()
        if kws and not any(k in title for k in kws):
            tags = " ".join(str(x).lower() for x in item.get("tags", []) if x)
            cat = str(item.get("category", "")).lower()
            if not any(k in tags or k in cat for k in kws):
                continue
        picked.append((_pick_liquidity(item), item))
    picked.sort(key=lambda x: x[0], reverse=True)
    return [x[1] for x in picked[:limit]]


def main() -> None:
    ap = argparse.ArgumentParser(description="Polymarket public probe")
    ap.add_argument("--out", default="")
    ap.add_argument("--json-out", default="")
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--keywords", default=",".join(DEFAULT_KEYWORDS))
    args = ap.parse_args()

    out = Path(args.out).expanduser().resolve() if args.out else Path("reports/research_raw/polymarket_probe_latest.txt").resolve()
    json_out = Path(args.json_out).expanduser().resolve() if args.json_out else Path("reports/research_raw/polymarket_probe_latest.json").resolve()
    keywords = [x.strip() for x in str(args.keywords).split(",") if x.strip()]

    urls = [
        "https://gamma-api.polymarket.com/markets?closed=false&limit=200",
        "https://gamma-api.polymarket.com/events?closed=false&limit=200",
    ]
    raw_items: list[dict[str, Any]] = []
    errors: list[str] = []
    used_url = ""
    for url in urls:
        try:
            payload = _fetch_json(url)
            raw_items = list(_iter_market_like(payload))
            used_url = url
            if raw_items:
                break
        except Exception as e:
            errors.append(f"{url} -> {type(e).__name__}: {e}")
    selected = _filter_items(raw_items, keywords, max(1, int(args.limit))) if raw_items else []

    lines: list[str] = []
    lines.append("Polymarket probe（public research only）")
    lines.append(f"status: {'ok' if selected else 'empty'}")
    lines.append(f"used_url: {used_url or '-'}")
    lines.append(f"matched: {len(selected)}")
    if errors:
        lines.append("errors:")
        for err in errors[:4]:
            lines.append(f"- {err}")
    lines.append("")
    lines.append("=== top_markets ===")
    serial: list[dict[str, Any]] = []
    for item in selected:
        row = {
            "title": _pick_title(item),
            "probability": _pick_probability(item),
            "liquidity": _pick_liquidity(item),
            "time": _pick_time(item),
        }
        serial.append(row)
        prob = f"{row['probability'] * 100:.1f}%" if row["probability"] is not None else "NA"
        lines.append(f"- {row['title']} | prob={prob} | liquidity={row['liquidity']:.2f} | time={row['time']}")

    payload = {
        "status": "ok" if selected else "empty",
        "used_url": used_url,
        "matched": len(selected),
        "keywords": keywords,
        "rows": serial,
        "errors": errors,
    }
    _write(out, "\n".join(lines))
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
