#!/usr/bin/env python3
"""
向量化回测引擎

高性能回测，支持多策略组合
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd


class TradeSide(Enum):
    """交易方向"""
    LONG = "long"
    SHORT = "short"


@dataclass
class TradeRecord:
    """交易记录"""
    entry_time: datetime
    exit_time: datetime | None = None
    side: TradeSide = TradeSide.LONG
    entry_price: float = 0.0
    exit_price: float = 0.0
    quantity: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BacktestResult:
    """回测结果"""
    # 基础指标
    initial_capital: float = 100000.0
    final_equity: float = 100000.0
    total_return: float = 0.0
    total_return_pct: float = 0.0

    # 交易统计
    trades: list[TradeRecord] = field(default_factory=list)
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0

    # 盈亏指标
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    profit_factor: float = 0.0
    avg_profit: float = 0.0
    avg_loss: float = 0.0

    # 风险指标
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0

    # 时间序列
    equity_curve: pd.Series = field(default_factory=lambda: pd.Series())

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            'initial_capital': self.initial_capital,
            'final_equity': self.final_equity,
            'total_return': self.total_return,
            'total_return_pct': self.total_return_pct,
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': self.win_rate,
            'profit_factor': self.profit_factor,
            'max_drawdown': self.max_drawdown,
            'max_drawdown_pct': self.max_drawdown_pct,
            'sharpe_ratio': self.sharpe_ratio,
        }


class BacktestEngine:
    """
    向量化回测引擎

    支持:
    - 多策略权重组合
    - 向量化高性能回测
    - 实时资金曲线计算
    """

    def __init__(self,
                 initial_capital: float = 100000.0,
                 fee_rate: float = 0.0002,  # 0.02%
                 slippage: float = 0.0001):  # 0.01%
        """
        初始化回测引擎

        Args:
            initial_capital: 初始资金
            fee_rate: 手续费率
            slippage: 滑点率
        """
        self.initial_capital = initial_capital
        self.fee_rate = fee_rate
        self.slippage = slippage

    def run(self,
            data: pd.DataFrame,
            strategy,
            position_size: float = 1.0) -> BacktestResult:
        """
        执行回测

        Args:
            data: OHLCV数据
            strategy: 策略实例或策略列表
            position_size: 仓位大小 (0-1)

        Returns:
            BacktestResult: 回测结果
        """
        if isinstance(strategy, list):
            return self._run_multi_strategy(data, strategy, position_size)
        else:
            return self._run_single_strategy(data, strategy, position_size)

    def _run_single_strategy(self,
                            data: pd.DataFrame,
                            strategy,
                            position_size: float) -> BacktestResult:
        """单策略回测"""
        # 生成信号
        signals = strategy.generate_signals(data)

        if not signals:
            return BacktestResult(initial_capital=self.initial_capital)

        # 执行回测
        return self._execute_signals(data, signals, position_size)

    def _run_multi_strategy(self,
                           data: pd.DataFrame,
                           strategies: list[tuple],
                           position_size: float) -> BacktestResult:
        """
        多策略组合回测

        Args:
            strategies: [(strategy, weight), ...]
        """
        all_signals = []

        for strategy, weight in strategies:
            signals = strategy.generate_signals(data)
            # 调整信号置信度
            for signal in signals:
                signal.confidence *= weight
            all_signals.extend(signals)

        # 按时间排序
        all_signals.sort(key=lambda x: x.timestamp)

        return self._execute_signals(data, all_signals, position_size)

    def _execute_signals(self,
                        data: pd.DataFrame,
                        signals: list,
                        position_size: float) -> BacktestResult:
        """执行信号回测"""
        # 初始化
        capital = self.initial_capital

        trades = []
        position = None  # 当前持仓

        for signal in signals:
            price = signal.price * (1 + self.slippage)  # 包含滑点

            if signal.signal_type.value == 'buy':
                # 平空仓
                if position and position['side'] == TradeSide.SHORT:
                    trade = self._close_position(position, price, signal, capital)
                    trades.append(trade)
                    capital += trade.pnl
                    position = None

                # 开多仓
                if position is None:
                    position = self._open_position(TradeSide.LONG, price, capital, position_size, signal)

            elif signal.signal_type.value == 'sell':
                # 平多仓
                if position and position['side'] == TradeSide.LONG:
                    trade = self._close_position(position, price, signal, capital)
                    trades.append(trade)
                    capital += trade.pnl
                    position = None

                # 开空仓
                if position is None:
                    position = self._open_position(TradeSide.SHORT, price, capital, position_size, signal)

        # 计算最终结果
        final_equity = capital
        if position:
            # 最后一根K线平仓
            final_price = data['close'].iloc[-1]
            trade = self._close_position(position, final_price, None, capital)
            final_equity += trade.pnl
            trades.append(trade)

        # 构建结果
        return self._build_result(trades, final_equity, len(data))

    def _open_position(self,
                      side: TradeSide,
                      price: float,
                      capital: float,
                      position_size: float,
                      signal) -> dict:
        """开仓"""
        size = capital * position_size / price
        fee = size * price * self.fee_rate

        return {
            'side': side,
            'entry_price': price,
            'quantity': size,
            'entry_time': signal.timestamp,
            'entry_fee': fee,
            'signal': signal
        }

    def _close_position(self,
                       position: dict,
                       exit_price: float,
                       exit_signal,
                       capital: float) -> TradeRecord:
        """平仓并返回交易记录"""
        side = position['side']
        entry_price = position['entry_price']
        quantity = position['quantity']

        # 计算盈亏
        pnl = (exit_price - entry_price) * quantity if side == TradeSide.LONG else (entry_price - exit_price) * quantity

        # 扣除手续费
        exit_fee = quantity * exit_price * self.fee_rate
        pnl -= (position['entry_fee'] + exit_fee)

        pnl_pct = pnl / (entry_price * quantity) if quantity > 0 else 0

        return TradeRecord(
            entry_time=position['entry_time'],
            exit_time=exit_signal.timestamp if exit_signal else datetime.now(),
            side=side,
            entry_price=entry_price,
            exit_price=exit_price,
            quantity=quantity,
            pnl=pnl,
            pnl_pct=pnl_pct,
            reason=exit_signal.strategy_name if exit_signal else "end_of_data",
            metadata=exit_signal.metadata if exit_signal else {}
        )

    def _build_result(self,
                     trades: list[TradeRecord],
                     final_equity: float,
                     bar_count: int) -> BacktestResult:
        """构建回测结果"""
        if not trades:
            return BacktestResult(initial_capital=self.initial_capital)

        # 计算统计
        winning_trades = [t for t in trades if t.pnl > 0]
        losing_trades = [t for t in trades if t.pnl <= 0]

        gross_profit = sum(t.pnl for t in winning_trades)
        gross_loss = abs(sum(t.pnl for t in losing_trades))

        total_return = final_equity - self.initial_capital
        total_return_pct = (total_return / self.initial_capital) * 100

        # 计算回撤
        equity_series = self._calculate_equity_curve(trades)
        max_dd, max_dd_pct = self._calculate_max_drawdown(equity_series)

        # 计算夏普比率 (简化版)
        returns = equity_series.pct_change().dropna()
        sharpe = np.sqrt(252) * returns.mean() / returns.std() if len(returns) > 1 else 0

        return BacktestResult(
            initial_capital=self.initial_capital,
            final_equity=final_equity,
            total_return=total_return,
            total_return_pct=total_return_pct,
            trades=trades,
            total_trades=len(trades),
            winning_trades=len(winning_trades),
            losing_trades=len(losing_trades),
            win_rate=len(winning_trades) / len(trades) if trades else 0,
            gross_profit=gross_profit,
            gross_loss=gross_loss,
            profit_factor=gross_profit / gross_loss if gross_loss > 0 else float('inf'),
            avg_profit=gross_profit / len(winning_trades) if winning_trades else 0,
            avg_loss=gross_loss / len(losing_trades) if losing_trades else 0,
            max_drawdown=max_dd,
            max_drawdown_pct=max_dd_pct,
            sharpe_ratio=sharpe,
            equity_curve=equity_series
        )

    def _calculate_equity_curve(self, trades: list[TradeRecord]) -> pd.Series:
        """计算权益曲线"""
        equity = self.initial_capital
        equity_points = [equity]

        for trade in trades:
            equity += trade.pnl
            equity_points.append(equity)

        return pd.Series(equity_points)

    def _calculate_max_drawdown(self, equity_series: pd.Series) -> tuple[float, float]:
        """计算最大回撤"""
        if len(equity_series) < 2:
            return 0.0, 0.0

        peak = equity_series.expanding().max()
        drawdown = equity_series - peak
        drawdown_pct = drawdown / peak

        max_dd = drawdown.min()
        max_dd_pct = drawdown_pct.min() * 100

        return max_dd, max_dd_pct

    def run_quick_backtest(self,
                          data: pd.DataFrame,
                          strategy,
                          lookback_bars: int = 1000) -> dict[str, Any]:
        """
        快速回测（用于AI策略评估）

        只回测最近N根K线，返回简化结果
        """
        if len(data) > lookback_bars:
            data = data.iloc[-lookback_bars:]

        result = self.run(data, strategy)

        # 返回简化结果
        return {
            'pf': result.profit_factor,
            'sharpe': result.sharpe_ratio,
            'max_dd': result.max_drawdown_pct,
            'trades': result.total_trades,
            'win_rate': result.win_rate,
            'return_pct': result.total_return_pct,
            'fitness': self._calculate_fitness(result)
        }

    def _calculate_fitness(self, result: BacktestResult) -> float:
        """
        计算策略适应度分数

        综合考虑PF、夏普、回撤
        """
        if result.total_trades < 5:  # 交易太少不可靠
            return 0.0

        # 简单加权评分
        pf_score = min(result.profit_factor / 2.0, 1.0) * 0.4
        sharpe_score = min(result.sharpe_ratio / 2.0, 1.0) * 0.3
        dd_score = (1 + result.max_drawdown_pct / 100) * 0.3  # 回撤是负数

        return pf_score + sharpe_score + dd_score
