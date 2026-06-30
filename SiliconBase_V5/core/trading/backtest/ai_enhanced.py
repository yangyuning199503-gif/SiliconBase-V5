#!/usr/bin/env python3
"""
AI 增强型回测引擎

在原有 BacktestEngine 基础上添加 AI 友好功能：
1. 极速批量回测 - 支持 AI 快速测试数百个策略
2. AI 反馈生成 - 结构化提示词，直接给 AI 使用
3. 交易归因分析 - 告诉 AI 为什么成功/失败
4. 流式结果 - 实时反馈给 AI
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd

from .engine import BacktestEngine, BacktestResult, TradeRecord


@dataclass
class AIAnalysisContext:
    """AI 分析上下文 - 给 AI 看的完整信息"""
    # 基础性能
    summary: dict[str, Any] = field(default_factory=dict)

    # 详细交易记录（带上下文）
    trades_with_context: list[dict] = field(default_factory=list)

    # 失败分析
    failure_analysis: dict[str, Any] = field(default_factory=dict)

    # 市场状态映射
    market_regime_performance: dict[str, float] = field(default_factory=dict)

    # 改进建议模板
    improvement_hints: list[str] = field(default_factory=list)


class AIEnhancedBacktester(BacktestEngine):
    """
    AI 增强型回测引擎

    继承原有引擎，添加 AI 专用功能
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._progress_callback: Callable | None = None

    def set_progress_callback(self, callback: Callable[[dict], None]):
        """设置进度回调（用于流式反馈给 AI）"""
        self._progress_callback = callback

    def run_batch(self,
                  data: pd.DataFrame,
                  strategies: list,
                  time_limit_ms: int = 5000) -> list[dict]:
        """
        批量回测多个策略

        Args:
            data: 市场数据
            strategies: 策略列表 [(strategy, name), ...]
            time_limit_ms: 时间限制（毫秒），超时返回部分结果

        Returns:
            简化结果列表，按 fitness 排序
        """
        import time
        start_time = time.time()
        results = []

        for strategy, name in strategies:
            # 检查时间限制
            if (time.time() - start_time) * 1000 > time_limit_ms:
                break

            # 快速回测
            result = self.run_quick_backtest(data, strategy)
            result['name'] = name
            result['strategy'] = strategy
            results.append(result)

            # 流式反馈
            if self._progress_callback:
                self._progress_callback({
                    'completed': len(results),
                    'total': len(strategies),
                    'current_result': result
                })

        # 按 fitness 排序
        results.sort(key=lambda x: x.get('fitness', 0), reverse=True)
        return results

    def generate_ai_report(self,
                          result: BacktestResult,
                          strategy_name: str = "unknown",
                          market_context: dict = None) -> str:
        """
        生成 AI 友好的回测报告（提示词格式）

        直接用于给 AI 分析和反思
        """
        # 构建详细分析
        self._analyze_trades(result)

        report = f"""# 回测结果分析报告

## 策略信息
- 策略名称: {strategy_name}
- 回测时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}

## 整体表现
```
总收益率: {result.total_return_pct:.2f}%
盈亏比(PF): {result.profit_factor:.2f}
夏普比率: {result.sharpe_ratio:.2f}
最大回撤: {result.max_drawdown_pct:.2f}%
胜率: {result.win_rate*100:.1f}%
交易次数: {result.total_trades}
```

## 详细分析

### 1. 盈利交易分析 (共{len([t for t in result.trades if t.pnl > 0])}笔)
{self._format_winning_trades(result.trades)}

### 2. 亏损交易分析 (共{len([t for t in result.trades if t.pnl <= 0])}笔)
{self._format_losing_trades(result.trades)}

### 3. 主要问题
{self._identify_problems(result)}

### 4. 市场适应性
{self._analyze_market_regime(result, market_context)}

## 改进建议方向
基于以上分析，建议从以下方向优化策略：
{self._generate_improvement_hints(result)}

## 任务
请分析以上回测结果，识别策略的核心问题，并提出具体的参数调整或逻辑改进建议。
重点关注：
1. 为什么亏损交易会发生？
2. 哪些市场条件下策略表现差？
3. 如何改进入场/出场逻辑？
"""
        return report

    def generate_structured_feedback(self,
                                    result: BacktestResult) -> dict[str, Any]:
        """
        生成结构化反馈（给程序使用）

        用于自动化策略进化
        """
        return {
            'performance': {
                'pf': result.profit_factor,
                'sharpe': result.sharpe_ratio,
                'max_dd': result.max_drawdown_pct,
                'win_rate': result.win_rate,
                'total_return': result.total_return_pct,
                'fitness': self._calculate_fitness(result)
            },
            'trade_analysis': {
                'total': result.total_trades,
                'winning': result.winning_trades,
                'losing': result.losing_trades,
                'avg_profit': result.avg_profit,
                'avg_loss': result.avg_loss,
                'profit_factor': result.profit_factor
            },
            'problems': self._identify_problems_list(result),
            'risk_flags': self._check_risk_flags(result),
            'recommendation': self._generate_recommendation(result)
        }

    def _analyze_trades(self, result: BacktestResult) -> dict:
        """深度分析交易记录"""
        if not result.trades:
            return {}

        # 按盈亏分组
        winning = [t for t in result.trades if t.pnl > 0]
        losing = [t for t in result.trades if t.pnl <= 0]

        analysis = {
            'avg_win': sum(t.pnl for t in winning) / len(winning) if winning else 0,
            'avg_loss': sum(t.pnl for t in losing) / len(losing) if losing else 0,
            'best_trade': max((t.pnl for t in result.trades), default=0),
            'worst_trade': min((t.pnl for t in result.trades), default=0),
            'consecutive_wins': self._max_consecutive(result.trades, lambda t: t.pnl > 0),
            'consecutive_losses': self._max_consecutive(result.trades, lambda t: t.pnl <= 0),
        }

        # 计算盈亏比
        if analysis['avg_loss'] != 0:
            analysis['risk_reward_ratio'] = abs(analysis['avg_win'] / analysis['avg_loss'])
        else:
            analysis['risk_reward_ratio'] = float('inf')

        return analysis

    def _format_winning_trades(self, trades: list[TradeRecord]) -> str:
        """格式化盈利交易"""
        winning = [t for t in trades if t.pnl > 0]
        if not winning:
            return "无盈利交易"

        lines = []
        for i, t in enumerate(winning[-3:], 1):  # 只显示最近3笔
            lines.append(f"  {i}. {t.side.value} | 收益: {t.pnl_pct*100:.2f}% | "
                        f"持仓: {(t.exit_time - t.entry_time).total_seconds()/3600:.1f}h | "
                        f"原因: {t.reason}")
        return '\n'.join(lines)

    def _format_losing_trades(self, trades: list[TradeRecord]) -> str:
        """格式化亏损交易"""
        losing = [t for t in trades if t.pnl <= 0]
        if not losing:
            return "无亏损交易"

        lines = []
        # 按亏损大小排序，显示最大的3笔
        sorted_losses = sorted(losing, key=lambda t: t.pnl)[:3]
        for i, t in enumerate(sorted_losses, 1):
            lines.append(f"  {i}. {t.side.value} | 亏损: {t.pnl_pct*100:.2f}% | "
                        f"入场: {t.entry_price:.2f} | 出场: {t.exit_price:.2f}")
            if t.metadata:
                lines.append(f"     信号元数据: {t.metadata}")
        return '\n'.join(lines)

    def _identify_problems(self, result: BacktestResult) -> str:
        """识别策略问题"""
        problems = []

        if result.total_trades < 10:
            problems.append("- 交易次数过少，信号频率过低")

        if result.win_rate < 0.3:
            problems.append("- 胜率过低(<30%)，入场条件可能过于宽松")
        elif result.win_rate > 0.8:
            problems.append("- 胜率过高(>80%)，可能存在过拟合风险")

        if result.profit_factor < 1.0:
            problems.append("- 盈亏比<1，策略整体亏损")
        elif result.profit_factor < 1.5:
            problems.append("- 盈亏比偏低，盈利效率不足")

        if result.max_drawdown_pct < -20:
            problems.append(f"- 最大回撤过大({result.max_drawdown_pct:.1f}%)，风控不足")

        if result.sharpe_ratio < 0.5:
            problems.append("- 夏普比率过低，风险调整后收益差")

        if not problems:
            problems.append("- 整体表现良好，可微调参数优化")

        return '\n'.join(problems)

    def _identify_problems_list(self, result: BacktestResult) -> list[str]:
        """返回问题列表（结构化）"""
        problems = []

        if result.total_trades < 10:
            problems.append('low_trade_frequency')
        if result.win_rate < 0.3:
            problems.append('low_win_rate')
        if result.profit_factor < 1.0:
            problems.append('negative_pf')
        if result.max_drawdown_pct < -20:
            problems.append('high_drawdown')
        if result.sharpe_ratio < 0.5:
            problems.append('low_sharpe')

        return problems

    def _analyze_market_regime(self,
                              result: BacktestResult,
                              context: dict = None) -> str:
        """分析市场适应性"""
        if not context:
            return "无市场状态数据"

        regime = context.get('market_regime', 'unknown')
        adx = context.get('avg_adx', 0)

        return f"""- 测试市场状态: {regime}
- 平均ADX: {adx:.1f}
- 策略在该状态下的适应性: {'良好' if result.profit_factor > 1.5 else '一般' if result.profit_factor > 1 else '较差'}"""

    def _generate_improvement_hints(self, result: BacktestResult) -> str:
        """生成改进建议"""
        hints = []

        if result.win_rate < 0.4:
            hints.append("1. 收紧入场条件，提高信号质量")

        if result.profit_factor < 1.5:
            hints.append("2. 优化出场逻辑，让利润奔跑")

        if result.max_drawdown_pct < -15:
            hints.append("3. 添加更严格的止损规则")

        if result.total_trades < 20:
            hints.append("4. 放宽入场条件，增加交易频率")

        if not hints:
            hints.append("1. 微调参数优化收益风险比")
            hints.append("2. 测试不同时间周期的表现")

        return '\n'.join(hints)

    def _check_risk_flags(self, result: BacktestResult) -> list[str]:
        """检查风险标志"""
        flags = []

        if result.max_drawdown_pct < -30:
            flags.append('extreme_drawdown')
        if result.sharpe_ratio < 0:
            flags.append('negative_sharpe')
        if result.profit_factor < 0.8:
            flags.append('poor_pf')
        if result.total_trades > 0 and result.win_rate < 0.2:
            flags.append('extremely_low_winrate')

        return flags

    def _generate_recommendation(self, result: BacktestResult) -> str:
        """生成总体建议"""
        fitness = self._calculate_fitness(result)

        if fitness > 0.8:
            return 'excellent'
        elif fitness > 0.6:
            return 'good_with_tweaks'
        elif fitness > 0.4:
            return 'needs_improvement'
        else:
            return 'major_revision_needed'

    def _max_consecutive(self, trades: list, condition) -> int:
        """计算最大连续满足条件的次数"""
        max_count = 0
        current = 0
        for t in trades:
            if condition(t):
                current += 1
                max_count = max(max_count, current)
            else:
                current = 0
        return max_count


# 便捷函数
def quick_backtest_for_ai(data: pd.DataFrame,
                          strategy,
                          strategy_name: str = "unnamed") -> dict[str, Any]:
    """
    快速回测并返回 AI 友好格式

    一行代码完成：回测 → 分析 → 生成反馈
    """
    engine = AIEnhancedBacktester()
    result = engine.run(data, strategy)

    return {
        'summary': engine.run_quick_backtest(data, strategy),
        'ai_report': engine.generate_ai_report(result, strategy_name),
        'structured': engine.generate_structured_feedback(result)
    }
