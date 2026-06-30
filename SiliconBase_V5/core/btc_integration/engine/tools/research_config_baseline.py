from __future__ import annotations

from pathlib import Path
from typing import Any

from src.backtest.io import read_config

BASELINE_RELATIVE = Path("research_baselines/mainline_live_base.yml")


def locate_research_base_yaml(root: Path) -> Path:
    root = Path(root).expanduser().resolve()
    candidate = root / BASELINE_RELATIVE
    if candidate.exists():
        return candidate
    return root / "config.yml"


def load_research_base_config(root: Path) -> dict[str, Any]:
    return read_config(locate_research_base_yaml(root))
