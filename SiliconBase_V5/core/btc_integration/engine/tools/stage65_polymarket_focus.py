from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

URL = "https://gamma-api.polymarket.com/markets?closed=false&limit=400"

CORE_TERMS = [
    "bitcoin", "btc", "ethereum", "eth", "solana", "sol", "bnb", "binance", "okx",
    "crypto", "cryptocurrency", "stablecoin", "usdt", "usdc", "defi", "etf",
    "federal reserve", "fed", "fomc", "cpi", "pce", "inflation", "rate cut", "rate hike",
    "recession", "war", "ceasefire", "israel", "iran", "ukraine", "russia",
    "tariff", "sec", "cftc", "doj", "regulation", "bitcoin reserve", "strategic reserve",
]
HARD_TERMS = [
    "bitcoin", "btc", "ethereum", "eth", "solana", "sol", "bnb", "crypto", "stablecoin", "etf",
    "federal reserve", "fed", "fomc", "cpi", "pce", "inflation", "rate cut", "rate hike",
    "war", "ceasefire", "israel", "iran", "ukraine", "russia", "sec", "cftc", "doj", "regulation",
]
NEGATIVE_TERMS = [
    "presidential election", "win the 2028 us presidential election", "2028 us presidential election",
    "nba", "nfl", "mlb", "fifa", "oscars", "grammys", "movie", "celebrity", "kim kardashian",
    "lebron", "openai", "gta", "world cup", "super bowl", "tim walz", "michelle obama", "elon musk win",
]


def _parse_time(v: str) -> datetime | None:
    if not v:
        return None
    try:
        if v.endswith("Z"):
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        return datetime.fromisoformat(v)
    except Exception:
        return None


def _text(m: dict[str, Any]) -> str:
    parts = [
        str(m.get("question") or ""),
        str(m.get("title") or ""),
        str(m.get("description") or ""),
        str(m.get("slug") or ""),
        str(m.get("category") or ""),
    ]
    return " ".join(parts).lower()


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


def _score(m: dict[str, Any]) -> dict[str, Any] | None:
    txt = _text(m)
    if not any(t in txt for t in HARD_TERMS):
        return None
    if any(t in txt for t in NEGATIVE_TERMS):
        return None

    end_time = _parse_time(str(m.get("endDate") or m.get("endDateIso") or ""))
    now = datetime.now(timezone.utc)
    horizon_days = None
    if end_time is not None:
        horizon_days = (end_time - now).total_seconds() / 86400.0
        if horizon_days < -2:
            return None
        if horizon_days > 550:
            return None

    score = 0.0
    for t in CORE_TERMS:
        if t in txt:
            score += 1.0
    for t in HARD_TERMS:
        if t in txt:
            score += 0.6

    try:
        liq = float(m.get("liquidity") or 0.0)
    except Exception:
        liq = 0.0
    score += min(liq / 300000.0, 3.0)

    prob = _prob(m)
    if 0.05 <= prob <= 0.95:
        score += 0.6
    if horizon_days is not None:
        if horizon_days <= 45:
            score += 1.2
        elif horizon_days <= 120:
            score += 0.7
        elif horizon_days <= 240:
            score += 0.2

    question = (m.get("question") or m.get("title") or "").strip()
    return {
        "question": question,
        "prob": prob,
        "liquidity": liq,
        "time": m.get("endDate") or m.get("endDateIso") or m.get("startDate") or "",
        "score": round(score, 3),
        "url": m.get("url") or m.get("slug") or "",
        "category": m.get("category") or "",
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage65 polymarket focus filter")
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

    rows: list[dict[str, Any]] = []
    seen = set()
    for m in payload:
        row = _score(m)
        if row is None:
            continue
        key = (row["question"].lower(), row["time"])
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)

    rows.sort(key=lambda x: (x["score"], x["liquidity"], x["prob"]), reverse=True)
    top = rows[:16]

    txt_lines = [
        "Polymarket relevance probe（focused public research only）",
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
        "- 只保留 crypto / macro / war / regulation 相关市场，并限制远期时长。",
        "- 明确过滤 2028 大选、体育、娱乐、弱相关名人题材。",
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
