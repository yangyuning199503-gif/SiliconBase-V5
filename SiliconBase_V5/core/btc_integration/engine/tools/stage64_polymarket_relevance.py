from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

URL = "https://gamma-api.polymarket.com/markets?closed=false&limit=300"

POSITIVE_TERMS = [
    "bitcoin", "btc", "ethereum", "eth", "solana", "sol", "bnb", "binance", "okx",
    "crypto", "cryptocurrency", "stablecoin", "usdt", "usdc", "defi", "etf",
    "federal reserve", "fed", "fomc", "cpi", "pce", "inflation", "rate cut", "rate hike",
    "recession", "war", "ceasefire", "israel", "iran", "ukraine", "russia",
    "tariff", "sec", "cftc", "doj", "regulation", "bitcoin reserve",
]
NEGATIVE_TERMS = [
    "fifa", "nba", "nfl", "mlb", "world cup", "oscars", "grammy", "movie", "gta", "openai",
    "hardware", "consumer product", "warriors", "raphael warnock", "jon stewart", "presidential nomination",
]


def _text(m: dict[str, Any]) -> str:
    return " ".join(
        str(m.get(k, "")) for k in ("question", "title", "description", "slug", "conditionId", "endDate", "category")
    ).lower()


def _score(m: dict[str, Any]) -> float:
    txt = _text(m)
    score = 0.0
    for t in POSITIVE_TERMS:
        if t in txt:
            score += 1.0
    for t in NEGATIVE_TERMS:
        if t in txt:
            score -= 2.0
    try:
        liq = float(m.get("liquidity") or 0.0)
    except Exception:
        liq = 0.0
    score += min(liq / 250000.0, 4.0)
    return score


def _prob(m: dict[str, Any]) -> float:
    for key in ("lastTradePrice", "price", "probability"):
        try:
            v = float(m.get(key))
            if v <= 1.0:
                return v
            if v <= 100.0:
                return v / 100.0
        except Exception:
            continue
    return 0.0


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage64 polymarket relevance filter")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    out_dir = root / "reports" / "research_raw"
    out_dir.mkdir(parents=True, exist_ok=True)

    payload: list[dict[str, Any]] = []
    status = "ok"
    try:
        resp = requests.get(URL, timeout=25)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            payload = list(data.get("data") or data.get("markets") or [])
        elif isinstance(data, list):
            payload = data
    except Exception as exc:
        status = f"error:{type(exc).__name__}:{exc}"
        payload = []

    ranked: list[dict[str, Any]] = []
    for m in payload:
        s = _score(m)
        if s <= 0.0:
            continue
        ranked.append(
            {
                "question": m.get("question") or m.get("title") or "",
                "prob": _prob(m),
                "liquidity": float(m.get("liquidity") or 0.0),
                "time": m.get("endDate") or m.get("endDateIso") or m.get("startDate") or "",
                "score": round(s, 3),
                "url": m.get("url") or m.get("slug") or "",
            }
        )
    ranked.sort(key=lambda x: (x["score"], x["liquidity"], x["prob"]), reverse=True)
    top = ranked[:20]

    txt_lines = [
        "Polymarket relevance probe（filtered public research only）",
        f"status: {status}",
        f"used_url: {URL}",
        f"matched: {len(top)}",
        "",
        "=== top_markets ===",
    ]
    for row in top:
        txt_lines.append(
            f"- {row['question']} | score={row['score']:.2f} | prob={row['prob']*100:.1f}% | liquidity={row['liquidity']:.2f} | time={row['time']}"
        )
    if not top:
        txt_lines.append("- none")
    txt_lines += [
        "",
        "=== use_policy ===",
        "- 只保留 crypto / macro / war / regulation 相关市场，过滤体育、娱乐和弱相关政治题材。",
        "- 仅作 regime prior / risk gate 候选，不直接触发交易。",
    ]

    (out_dir / "polymarket_probe_latest.txt").write_text("\n".join(txt_lines).rstrip() + "\n", encoding="utf-8")
    (out_dir / "polymarket_probe_latest.json").write_text(
        json.dumps(
            {
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "status": status,
                "used_url": URL,
                "matched": len(top),
                "rows": top,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(out_dir / "polymarket_probe_latest.txt")


if __name__ == "__main__":
    main()
