#!/usr/bin/env python3
"""
交易工具模块

包含量化交易相关的工具和脚本
"""

import sys
from pathlib import Path

# === 【P0修复】将 engine/src 加入 Python path，使 from src.backtest... 可解析 ===
_src_path = str(Path(__file__).resolve().parents[1] / "src")
if _src_path not in sys.path:
    sys.path.insert(0, _src_path)

__version__ = "1.0.0"
