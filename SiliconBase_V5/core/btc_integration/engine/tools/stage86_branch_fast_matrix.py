from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _safe_float(x: Any, default: float = -1e18) -> float:
    try:
        return float(x)
    except Exception:
        return default


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return default


def _load_rows(project_dir: Path) -> list[dict[str, Any]]:
    path = project_dir / "reports" / "research_raw" / "stage78_branch_dual_window_latest.json"
    if not path.exists():
        raise SystemExit(f"未找到 {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("rows") or []
    if not isinstance(rows, list):
        raise SystemExit("stage78 json 结构异常")
    return rows


def _recent_metrics(row: dict[str, Any]) -> dict[str, Any]:
    return ((row.get("best_gate") or {}).get("recent_metrics") or {})


def _full_metrics(row: dict[str, Any]) -> dict[str, Any]:
    return ((row.get("best_gate") or {}).get("metrics") or {})


def _row_name(row: dict[str, Any]) -> str:
    return str(row.get("name", ""))


def _pick_max(rows: list[dict[str, Any]], key_fn, min_floor=None) -> dict[str, Any] | None:
    pool = rows
    if min_floor is not None:
        filtered = [r for r in rows if min_floor(r)]
        if filtered:
            pool = filtered
    if not pool:
        return None
    return max(pool, key=key_fn)


def _pick_min(rows: list[dict[str, Any]], key_fn, min_floor=None) -> dict[str, Any] | None:
    pool = rows
    if min_floor is not None:
        filtered = [r for r in rows if min_floor(r)]
        if filtered:
            pool = filtered
    if not pool:
        return None
    return min(pool, key=key_fn)


def _lane_summary_value(row: dict[str, Any]) -> str:
    best = row.get("best_gate") or {}
    rm = _recent_metrics(row)
    return (
        f"score={_safe_float(best.get('score'), 0.0):+.2f} "
        f"recent_pf={_safe_float(rm.get('pf'), 0.0):.3f} "
        f"recent_ret={_safe_float(rm.get('ret'), 0.0) * 100:.2f}% "
        f"recent_dd={_safe_float(rm.get('maxdd'), 0.0) * 100:.2f}% "
        f"recent_trades={_safe_int(rm.get('trades'), 0)}"
    )


def _select(rows: list[dict[str, Any]], per_lane: int) -> tuple[list[str], list[str], dict[str, Any]]:
    by_lane: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = (str(row.get("symbol", "")).lower(), str(row.get("family", "")).lower())
        by_lane.setdefault(key, []).append(row)

    picked: list[str] = []
    summary_lines: list[str] = []
    out_json: dict[str, Any] = {"lanes": [], "selected": []}

    for (sym, family), lane_rows in sorted(by_lane.items()):
        lane_rows = list(lane_rows)
        lane_rows.sort(key=lambda r: _safe_float((r.get("best_gate") or {}).get("score")), reverse=True)

        chosen: list[tuple[dict[str, Any], str]] = []
        chosen_names: set[str] = set()

        def add(row: dict[str, Any] | None, reason: str, chosen=chosen, chosen_names=chosen_names) -> None:
            if not row:
                return
            name = _row_name(row)
            if not name or name in chosen_names:
                return
            chosen.append((row, reason))
            chosen_names.add(name)

        add(lane_rows[0] if lane_rows else None, "top_score")
        add(_pick_max(lane_rows, lambda r: _safe_float(_recent_metrics(r).get("pf"))), "top_recent_pf")
        add(_pick_max(lane_rows, lambda r: _safe_float(_recent_metrics(r).get("ret"))), "top_recent_ret")
        add(
            _pick_min(
                lane_rows,
                lambda r: abs(_safe_float(_recent_metrics(r).get("maxdd"), 9e9)),
                min_floor=lambda r: _safe_float(_recent_metrics(r).get("ret"), -9e9) > 0 or _safe_float(_recent_metrics(r).get("pf"), 0.0) >= 1.0,
            ),
            "best_recent_dd",
        )
        add(
            _pick_max(
                lane_rows,
                lambda r: _safe_int(_recent_metrics(r).get("trades"), 0),
                min_floor=lambda r: _safe_float(_recent_metrics(r).get("pf"), 0.0) >= 0.9 or _safe_float(_recent_metrics(r).get("ret"), -9e9) > -0.05,
            ),
            "top_recent_trades",
        )
        add(_pick_max(lane_rows, lambda r: _safe_float(_full_metrics(r).get("pf"))), "top_full_pf")

        for row in lane_rows:
            if len(chosen) >= max(1, per_lane):
                break
            add(row, "score_fill")

        keep = chosen[: max(1, per_lane)]
        reserve_rows = [row for row in lane_rows if _row_name(row) not in { _row_name(r) for r, _ in keep }]

        summary_lines.append(f"- {sym.upper()} | {family} | 保留 {len(keep)} 组")
        lane_json = {
            "symbol": sym.upper(),
            "family": family,
            "kept": [],
            "reserve": [],
        }
        for idx, (row, reason) in enumerate(keep, start=1):
            name = _row_name(row)
            picked.append(name)
            best = row.get("best_gate") or {}
            label = str(best.get("gate", "-"))
            score = _safe_float(best.get("score"), 0.0)
            summary_lines.append(f"  {idx}. {name} | reason={reason} | label={label} | {_lane_summary_value(row)}")
            lane_json["kept"].append({
                "rank": idx,
                "name": name,
                "reason": reason,
                "label": label,
                "score": score,
                "recent_metrics": _recent_metrics(row),
                "full_metrics": _full_metrics(row),
            })
        if reserve_rows:
            reserve_names = []
            for row in reserve_rows[:6]:
                name = _row_name(row)
                reserve_names.append(name)
                lane_json["reserve"].append({
                    "name": name,
                    "label": str((row.get("best_gate") or {}).get("gate", "-")),
                    "score": _safe_float((row.get("best_gate") or {}).get("score"), 0.0),
                    "recent_metrics": _recent_metrics(row),
                })
            summary_lines.append(f"  reserve: {', '.join(reserve_names)}")
        out_json["lanes"].append(lane_json)

    dedup: list[str] = []
    seen = set()
    for name in picked:
        if name and name not in seen:
            dedup.append(name)
            seen.add(name)
    out_json["selected"] = dedup
    return dedup, summary_lines, out_json


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage86 branch fast matrix shortlist")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--per-lane", type=int, default=5)
    ap.add_argument("--print-names", action="store_true")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    rows = _load_rows(root)
    picked, summary_lines, out_json = _select(rows, max(1, int(args.per_lane)))

    out_txt = root / "reports" / "research_raw" / "stage86_branch_shortlist_latest.txt"
    out_json_path = root / "reports" / "research_raw" / "stage86_branch_shortlist_latest.json"
    out_txt.parent.mkdir(parents=True, exist_ok=True)
    out_txt.write_text(
        "Stage86 分支快速矩阵 shortlist\n"
        "原则：每个赛道按多标准保留候选，不因一轮不合格就彻底删路径。\n"
        "标准：top_score / top_recent_pf / top_recent_ret / best_recent_dd / top_recent_trades / top_full_pf。\n\n"
        + "\n".join(summary_lines)
        + "\n\nselected="
        + ",".join(picked)
        + "\n",
        encoding="utf-8",
    )
    out_json_path.write_text(json.dumps(out_json, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.print_names:
        print(",".join(picked))
    else:
        print(out_txt)
        print(out_json_path)
        for line in summary_lines:
            print(line)


if __name__ == "__main__":
    main()
