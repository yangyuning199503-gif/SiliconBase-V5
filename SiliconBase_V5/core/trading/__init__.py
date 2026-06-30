#!/usr/bin/env python3
"""
V5 交易核心模块

提供策略定义、回测引擎和实时交易功能
"""

from .backtest.engine import BacktestEngine, BacktestResult
from .strategy.base import Signal, SignalType, TradingStrategy
from .strategy.mr_strategy import MeanReversionStrategy
from .strategy.sr_strategy import SupportResistanceStrategy
from .strategy.trend_strategy import TrendStrategy

__all__ = [
    'TradingStrategy',
    'Signal',
    'SignalType',
    'TrendStrategy',
    'MeanReversionStrategy',
    'SupportResistanceStrategy',
    'BacktestEngine',
    'BacktestResult',
]
