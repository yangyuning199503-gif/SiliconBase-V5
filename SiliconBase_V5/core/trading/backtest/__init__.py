#!/usr/bin/env python3
"""
回测引擎模块

提供策略回测和性能评估功能
"""

from .engine import BacktestEngine, BacktestResult, TradeRecord

__all__ = [
    'BacktestEngine',
    'BacktestResult',
    'TradeRecord',
]
