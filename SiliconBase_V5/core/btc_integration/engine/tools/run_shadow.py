from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _detect_exchange(project_dir: Path) -> str:
    shadow_path = project_dir / "shadow.yml"
    if shadow_path.exists():
        try:
            data = yaml.safe_load(shadow_path.read_text(encoding="utf-8")) or {}
            if isinstance(data, dict):
                shadow = data.get("shadow", data) or {}
                ex = str(shadow.get("exchange", "")).strip().lower()
                if ex:
                    return ex
        except Exception:
            pass
    cfg_path = project_dir / "config.yml"
    if cfg_path.exists():
        try:
            cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            ex = str((cfg.get("live_bridge", {}) or {}).get("exchange", "")).strip().lower()
            if ex:
                return ex
        except Exception:
            pass
    return "okx"


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate shadow-mode plan files")
    ap.add_argument("project_dir", nargs="?", default=".")
    ap.add_argument("--out-json", default="reports/shadow_mode_plan_latest.json")
    ap.add_argument("--out-md", default="reports/shadow_mode_plan_latest.md")
    args = ap.parse_args()

    project_dir = Path(args.project_dir).resolve()
    exchange = _detect_exchange(project_dir)
    if exchange == "okx":
        from src.live.okx_shadow import write_shadow_plan
    else:
        from src.live.binance_shadow import write_shadow_plan

    plan = write_shadow_plan(project_dir, args.out_json, args.out_md)
    ex = plan.get("exchange", exchange)
    print(f"shadow plan saved for {plan['version']} [{ex}] -> {Path(args.out_json)}")


if __name__ == "__main__":
    main()
