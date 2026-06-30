#!/usr/bin/env python3
"""
支撑阻力策略

基于关键价格水平的突破和回调策略
"""

from datetime import datetime
from typing import Any

import pandas as pd

from .base import Signal, SignalType, TradingStrategy


class SupportResistanceStrategy(TradingStrategy):
    """
    支撑阻力策略

    逻辑:
    1. 识别近期支撑和阻力水平
    2. 在支撑位附近做多，阻力位附近做空
    3. 使用ATR定义支撑阻力区域
    """

    name = "support_resistance"
    description = "支撑阻力策略 - 关键价格水平"
    version = "1.0.0"

    default_params = {
        # 支撑阻力参数
        "lookback": 30,  # 回看周期识别支撑阻力
        "zone_atr_mult": 0.6,  # 支撑阻力区域ATR倍数

        # ADX过滤 (低ADX时效果更好)
        "use_adx_filter": True,
        "adx_period": 14,
        "adx_max": 25,  # 只在低ADX时交易

        # 入场条件
        "require_touch": True,  # 需要价格触及区域

        # 风控参数
        "atr_stop_mult": 2.0,
        "cooldown_bars": 24,
    }

    def __init__(self, params: dict[str, Any] = None):
        super().__init__(params)
        self._last_signal_bar = -999
        self._support_levels: list[tuple[int, float]] = []  # (bar_index, price)
        self._resistance_levels: list[tuple[int, float]] = []

    def generate_signals(self, data: pd.DataFrame) -> list[Signal]:
        """生成交易信号"""
        if not self.validate_data(data):
            return []

        # 计算指标
        data = self.calculate_indicators(data)

        signals = []
        symbol = data.attrs.get('symbol', 'BTC')
        lookback = self.params['lookback']

        for i in range(lookback, len(data)):
            current_bar = data.iloc[i]

            # 检查冷却期
            if i - self._last_signal_bar < self.params['cooldown_bars']:
                continue

            # ADX过滤
            if self.params['use_adx_filter']:
                adx = current_bar.get('adx', 0)
                if pd.notna(adx) and adx > self.params['adx_max']:
                    continue  # 趋势太强，不适合SR策略

            # 识别支撑阻力
            window = data.iloc[i-lookback:i]
            support = window['low'].min()
            resistance = window['high'].max()

            # 定义区域
            atr = current_bar['atr']
            if pd.isna(atr):
                continue

            zone_size = atr * self.params['zone_atr_mult']

            # 检查是否在支撑区域
            price = current_bar['close']

            # 做多: 价格接近支撑区域
            if abs(price - support) <= zone_size:
                signal = Signal(
                    timestamp=current_bar.name if isinstance(current_bar.name, datetime) else datetime.now(),
                    symbol=symbol,
                    signal_type=SignalType.BUY,
                    price=price,
                    strategy_name=self.name,
                    confidence=1 - abs(price - support) / zone_size,  # 越接近支撑置信度越高
                    metadata={
                        'support_level': support,
                        'resistance_level': resistance,
                        'zone_size': zone_size,
                        'atr': atr,
                        'stop_loss': support - atr * 0.5
                    }
                )
                signals.append(signal)
                self._last_signal_bar = i

            # 做空: 价格接近阻力区域
            elif abs(price - resistance) <= zone_size:
                signal = Signal(
                    timestamp=current_bar.name if isinstance(current_bar.name, datetime) else datetime.now(),
                    symbol=symbol,
                    signal_type=SignalType.SELL,
                    price=price,
                    strategy_name=self.name,
                    confidence=1 - abs(price - resistance) / zone_size,
                    metadata={
                        'support_level': support,
                        'resistance_level': resistance,
                        'zone_size': zone_size,
                        'atr': atr,
                        'stop_loss': resistance + atr * 0.5
                    }
                )
                signals.append(signal)
                self._last_signal_bar = i

        return signals

    def calculate_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        """计算支撑阻力和ADX"""
        df = data.copy()

        # 计算ATR
        df['atr'] = self.calculate_atr(df, 14)

        # 计算ADX
        if self.params['use_adx_filter']:
            df['adx'] = self.calculate_adx(df, self.params['adx_period'])

        return df
