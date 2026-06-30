#!/usr/bin/env python3
"""
趋势跟踪策略

基于ADX趋势强度和价格突破的策略
"""

from datetime import datetime
from typing import Any

import pandas as pd

from .base import Signal, SignalType, TradingStrategy


class TrendStrategy(TradingStrategy):
    """
    趋势跟踪策略

    逻辑:
    1. 使用ADX判断趋势强度 (>30为强趋势)
    2. 使用价格突破入场 (突破N周期高点/低点)
    3. ATR倍数止损

    参考自 btc_system 的 explosion_v1 策略
    """

    name = "trend_following"
    description = "趋势跟踪策略 - ADX + 突破"
    version = "1.0.0"

    default_params = {
        # ADX参数
        "adx_period": 14,
        "adx_threshold": 30,  # ADX大于此值认为有趋势

        # 突破参数
        "breakout_lookback": 28,  # 回看周期
        "breakout_atr_buffer": 0.5,  # ATR缓冲倍数

        # ATR参数
        "atr_period": 14,
        "atr_stop_mult": 6.0,  # 止损倍数

        # 风控参数
        "cooldown_bars": 24,  # 冷却周期
        "allow_short": True,
    }

    def __init__(self, params: dict[str, Any] = None):
        super().__init__(params)
        self._last_signal_bar = -999

    def generate_signals(self, data: pd.DataFrame) -> list[Signal]:
        """生成交易信号"""
        if not self.validate_data(data):
            return []

        # 计算指标
        data = self.calculate_indicators(data)

        signals = []
        symbol = data.attrs.get('symbol', 'BTC')

        for i in range(1, len(data)):
            current_bar = data.iloc[i]
            data.iloc[i-1]

            # 检查冷却期
            if i - self._last_signal_bar < self.params['cooldown_bars']:
                continue

            # 获取当前ADX
            adx = current_bar.get('adx', 0)
            if pd.isna(adx):
                continue

            # 只在大于ADX阈值时交易
            if adx < self.params['adx_threshold']:
                continue

            # 计算突破水平
            lookback = self.params['breakout_lookback']
            if i < lookback:
                continue

            atr_buffer = current_bar['atr'] * self.params['breakout_atr_buffer']

            # 检查突破
            high_breakout = data['high'].iloc[i-lookback:i].max() + atr_buffer
            low_breakout = data['low'].iloc[i-lookback:i].min() - atr_buffer

            # 做多信号: 价格突破 + 强趋势
            if current_bar['close'] > high_breakout:
                signal = Signal(
                    timestamp=current_bar.name if isinstance(current_bar.name, datetime) else datetime.now(),
                    symbol=symbol,
                    signal_type=SignalType.BUY,
                    price=current_bar['close'],
                    strategy_name=self.name,
                    confidence=min(adx / 50, 1.0),  # ADX越高置信度越高
                    metadata={
                        'adx': adx,
                        'atr': current_bar['atr'],
                        'breakout_level': high_breakout,
                        'stop_loss': current_bar['close'] - current_bar['atr'] * self.params['atr_stop_mult']
                    }
                )
                signals.append(signal)
                self._last_signal_bar = i

            # 做空信号
            elif self.params['allow_short'] and current_bar['close'] < low_breakout:
                signal = Signal(
                    timestamp=current_bar.name if isinstance(current_bar.name, datetime) else datetime.now(),
                    symbol=symbol,
                    signal_type=SignalType.SELL,
                    price=current_bar['close'],
                    strategy_name=self.name,
                    confidence=min(adx / 50, 1.0),
                    metadata={
                        'adx': adx,
                        'atr': current_bar['atr'],
                        'breakout_level': low_breakout,
                        'stop_loss': current_bar['close'] + current_bar['atr'] * self.params['atr_stop_mult']
                    }
                )
                signals.append(signal)
                self._last_signal_bar = i

        return signals

    def calculate_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        """计算ADX和ATR指标"""
        df = data.copy()

        # 计算ATR
        df['atr'] = self.calculate_atr(df, self.params['atr_period'])

        # 计算ADX
        df['adx'] = self.calculate_adx(df, self.params['adx_period'])

        return df
