from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

DEFAULT_FALLBACK = "eth_short_shock_fast_lb16_atr052_adx22_s078"
SEARCH_FILES = [
    "reports/research_raw/stage89_branch_fusion_walkforward_latest.json",
    "reports/research_raw/stage82_branch_walkforward_latest.json",
]


def _safe_float(x: Any, default: float = float('-inf')) -> float:
    try:
        v = float(x)
    except Exception:
        return default
    if math.isnan(v):
        return default
    return v


def _load_rows(project_dir: Path) -> list[dict[str, Any]]:
    for rel in SEARCH_FILES:
        path = project_dir / rel
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows = data.get("rows") if isinstance(data, dict) else None
        if isinstance(rows, list) and rows:
            return rows
    return []


def _pick(rows: list[dict[str, Any]], prefer_symbol: str | None, prefer_family: str | None) -> str:
    cand: list[dict[str, Any]] = []
    for row in rows:
        if prefer_symbol and str(row.get("symbol") or "").lower() != prefer_symbol:
            continue
        if prefer_family and str(row.get("family") or "").lower() != prefer_family:
            continue
        wf = row.get("walkforward") or {}
        if str(wf.get("label") or "").lower() not in {"hold", "pass"}:
            continue
        best_gate = row.get("best_gate") or {}
        recent = best_gate.get("recent_metrics") or {}
        wf_metrics = wf.get("metrics") or {}
        recent_ret = _safe_float(recent.get("ret"), -999.0)
        wf_ret = _safe_float(wf_metrics.get("ret"), -999.0)
        if recent_ret <= 0.0 or wf_ret <= 0.0:
            continue
        cand.append(
            {
                "name": str(row.get("name") or ""),
                "score": _safe_float(wf.get("score"), -999.0),
                "recent_pf": _safe_float(recent.get("pf"), -999.0),
                "wf_pf": _safe_float(wf_metrics.get("pf"), -999.0),
                "recent_ret": recent_ret,
                "wf_ret": wf_ret,
                "recent_dd": abs(_safe_float(recent.get("maxdd"), 999.0)),
                "wf_dd": abs(_safe_float(wf_metrics.get("maxdd"), 999.0)),
            }
        )
    if not cand:
        return ""
    cand.sort(
        key=lambda x: (
            x["score"],
            x["wf_pf"],
            x["recent_pf"],
            x["wf_ret"],
            x["recent_ret"],
            -x["wf_dd"],
            -x["recent_dd"],
        ),
        reverse=True,
    )
    return cand[0]["name"]


def main() -> None:
    ap = argparse.ArgumentParser(description="从最新 stage89/stage82 结果自动挑选分支 Demo 候选")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--prefer-symbol", default="eth")
    ap.add_argument("--prefer-family", default="short")
    ap.add_argument("--fallback", default=DEFAULT_FALLBACK)
    args = ap.parse_args()
    project_dir = Path(args.project_dir).expanduser().resolve()
    rows = _load_rows(project_dir)
    picked = _pick(rows, str(args.prefer_symbol or "").lower() or None, str(args.prefer_family or "").lower() or None)
    if not picked:
        picked = _pick(rows, None, str(args.prefer_family or "").lower() or None)
    if not picked:
        picked = _pick(rows, None, None)
    print(picked or str(args.fallback))


if __name__ == "__main__":
    main()
