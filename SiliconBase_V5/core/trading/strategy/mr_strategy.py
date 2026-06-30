#!/usr/bin/env python3
"""
均值回归策略

基于RSI和布林带的均值回归策略
"""

from datetime import datetime
from typing import Any

import pandas as pd

from .base import Signal, SignalType, TradingStrategy


class MeanReversionStrategy(TradingStrategy):
    """
    均值回归策略

    逻辑:
    1. 使用RSI判断超买超卖
    2. 使用布林带确认极端价格
    3. 在价格回归均值时平仓
    """

    name = "mean_reversion"
    description = "均值回归策略 - RSI + 布林带"
    version = "1.0.0"

    default_params = {
        # RSI参数
        "rsi_period": 14,
        "oversold": 30,  # 超卖阈值
        "overbought": 70,  # 超买阈值

        # 布林带参数
        "bb_period": 20,
        "bb_std": 2.0,

        # 入场条件
        "require_bb_confirm": True,  # 是否需要布林带确认

        # 风控参数
        "atr_stop_mult": 3.0,
        "cooldown_bars": 12,
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

        for i in range(self.params['bb_period'], len(data)):
            current_bar = data.iloc[i]

            # 检查冷却期
            if i - self._last_signal_bar < self.params['cooldown_bars']:
                continue

            rsi = current_bar.get('rsi', 50)
            if pd.isna(rsi):
                continue

            # 超卖做多 (RSI < 30)
            if rsi < self.params['oversold']:
                # 检查布林带确认
                if self.params['require_bb_confirm'] and current_bar['close'] > current_bar['bb_lower']:
                    continue  # 价格不在下轨附近，不够极端

                signal = Signal(
                    timestamp=current_bar.name if isinstance(current_bar.name, datetime) else datetime.now(),
                    symbol=symbol,
                    signal_type=SignalType.BUY,
                    price=current_bar['close'],
                    strategy_name=self.name,
                    confidence=(self.params['oversold'] - rsi) / self.params['oversold'],  # RSI越低置信度越高
                    metadata={
                        'rsi': rsi,
                        'bb_lower': current_bar['bb_lower'],
                        'bb_middle': current_bar['bb_middle'],
                        'stop_loss': current_bar['close'] - current_bar['atr'] * self.params['atr_stop_mult']
                    }
                )
                signals.append(signal)
                self._last_signal_bar = i

            # 超买做空
            elif rsi > self.params['overbought']:
                # 检查布林带确认
                if self.params['require_bb_confirm'] and current_bar['close'] < current_bar['bb_upper']:
                    continue  # 价格不在上轨附近，不够极端

                signal = Signal(
                    timestamp=current_bar.name if isinstance(current_bar.name, datetime) else datetime.now(),
                    symbol=symbol,
                    signal_type=SignalType.SELL,
                    price=current_bar['close'],
                    strategy_name=self.name,
                    confidence=(rsi - self.params['overbought']) / (100 - self.params['overbought']),
                    metadata={
                        'rsi': rsi,
                        'bb_upper': current_bar['bb_upper'],
                        'bb_middle': current_bar['bb_middle'],
                        'stop_loss': current_bar['close'] + current_bar['atr'] * self.params['atr_stop_mult']
                    }
                )
                signals.append(signal)
                self._last_signal_bar = i

        return signals

    def calculate_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        """计算RSI和布林带"""
        df = data.copy()

        # 计算RSI
        df['rsi'] = self.calculate_rsi(df, self.params['rsi_period'])

        # 计算布林带
        bb_upper, bb_middle, bb_lower = self.calculate_bollinger_bands(
            df,
            self.params['bb_period'],
            self.params['bb_std']
        )
        df['bb_upper'] = bb_upper
        df['bb_middle'] = bb_middle
        df['bb_lower'] = bb_lower

        # 计算ATR用于止损
        df['atr'] = self.calculate_atr(df, 14)

        return df
