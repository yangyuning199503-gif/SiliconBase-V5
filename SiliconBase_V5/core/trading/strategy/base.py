#!/usr/bin/env python3
"""
交易策略基类

定义所有策略的通用接口和数据结构
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd


class SignalType(Enum):
    """信号类型"""
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
    CLOSE = "close"


@dataclass
class Signal:
    """交易信号"""
    timestamp: datetime
    symbol: str
    signal_type: SignalType
    price: float
    strategy_name: str
    confidence: float = 1.0  # 0-1之间的置信度
    metadata: dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class TradingStrategy(ABC):
    """
    交易策略基类

    所有策略必须继承此类并实现必要的方法
    """

    # 策略基本信息
    name: str = "base"
    description: str = "基础策略"
    version: str = "1.0.0"

    # 默认参数（子类可以覆盖）
    default_params: dict[str, Any] = {}

    def __init__(self, params: dict[str, Any] | None = None):
        """
        初始化策略

        Args:
            params: 策略参数字典，覆盖默认参数
        """
        self.params = self.default_params.copy()
        if params:
            self.params.update(params)
        self.name = self.__class__.name

    @abstractmethod
    def generate_signals(self, data: pd.DataFrame) -> list[Signal]:
        """
        生成交易信号

        Args:
            data: OHLCV数据，列名为 open, high, low, close, volume

        Returns:
            信号列表
        """
        pass

    def get_parameters(self) -> dict[str, Any]:
        """获取当前参数"""
        return self.params.copy()

    def update_parameters(self, params: dict[str, Any]) -> None:
        """更新参数"""
        self.params.update(params)

    def calculate_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        计算技术指标（可选重写）

        Args:
            data: OHLCV数据

        Returns:
            添加了指标列的数据框
        """
        return data.copy()

    def validate_data(self, data: pd.DataFrame) -> bool:
        """
        验证数据有效性

        Args:
            data: 待验证的数据

        Returns:
            数据是否有效
        """
        required_cols = ['open', 'high', 'low', 'close', 'volume']
        return all(col in data.columns for col in required_cols)

    @staticmethod
    def calculate_atr(data: pd.DataFrame, period: int = 14) -> pd.Series:
        """计算ATR指标"""
        high_low = data['high'] - data['low']
        high_close = np.abs(data['high'] - data['close'].shift())
        low_close = np.abs(data['low'] - data['close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = ranges.max(axis=1)
        return true_range.rolling(window=period).mean()

    @staticmethod
    def calculate_adx(data: pd.DataFrame, period: int = 14) -> pd.Series:
        """计算ADX指标"""
        plus_dm = data['high'].diff()
        minus_dm = data['low'].diff(-1).abs()

        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm < 0] = 0

        atr = TradingStrategy.calculate_atr(data, period)

        plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr)
        minus_di = 100 * (minus_dm.rolling(window=period).mean() / atr)

        dx = (np.abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
        adx = dx.rolling(window=period).mean()

        return adx

    @staticmethod
    def calculate_rsi(data: pd.DataFrame, period: int = 14) -> pd.Series:
        """计算RSI指标"""
        delta = data['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    @staticmethod
    def calculate_bollinger_bands(data: pd.DataFrame, period: int = 20, std_dev: float = 2.0):
        """计算布林带"""
        middle = data['close'].rolling(window=period).mean()
        std = data['close'].rolling(window=period).std()
        upper = middle + (std * std_dev)
        lower = middle - (std * std_dev)
        return upper, middle, lower

    def __repr__(self) -> str:
        return f"{self.name}(params={self.params})"
