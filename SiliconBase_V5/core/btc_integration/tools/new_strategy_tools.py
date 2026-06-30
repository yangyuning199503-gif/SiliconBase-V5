#!/usr/bin/env python3
from __future__ import annotations

"""
AI驱动的策略工具（新版）

使用V5原生交易引擎
"""

from typing import Any

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except Exception:
    pd = None  # type: ignore[assignment]
    PANDAS_AVAILABLE = False

from core.btc_integration.ai_strategy_generator import get_ai_strategy_generator
from core.logger import logger

from .base_btc_tool import BaseBTCTool


class AIWeightGeneratorTool(BaseBTCTool):
    """
    AI策略权重生成器

    根据市场状态自动生成最优策略权重
    """

    tool_id = "ai_generate_weights"
    name = "AI生成策略权重"
    description = """
    基于当前市场状态，使用AI生成最优的策略权重配置。

    分析维度:
    - 市场趋势（ADX指标）
    - 波动率水平
    - RSI超买超卖状态

    输出三个策略的权重分配:
    - 趋势策略: 适合强趋势市场
    - 均值回归策略: 适合震荡市场
    - 支撑阻力策略: 适合低波动市场
    """

    input_schema = {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "default": "BTC",
                "description": "分析的交易对"
            }
        }
    }

    async def _execute(self, symbol: str = "BTC", **kwargs) -> dict[str, Any]:
        """执行AI权重生成"""
        if not PANDAS_AVAILABLE:
            return self._format_error("DEPENDENCY_MISSING", "pandas 未安装，策略工具不可用")
        from core.trading.data.provider import get_market_data_provider
        try:
            # 获取市场数据
            provider = get_market_data_provider()
            df = await provider.get_historical_data(symbol, interval="1h", days=7)

            if df.empty:
                return self._format_error("DATA_NOT_AVAILABLE", "无法获取市场数据")

            # 计算市场状态
            market_state = self._analyze_market(df)

            # 调用AI生成权重
            generator = get_ai_strategy_generator()
            weights = await generator.generate_weights(market_state)

            data = {
                "symbol": symbol,
                "market_state": market_state,
                "weights": weights.to_dict(),
                "recommendation": self._get_recommendation(weights, market_state)
            }

            message = f"AI建议权重 - 趋势:{weights.trend:.1%} 均值回归:{weights.mean_reversion:.1%} SR:{weights.support_resistance:.1%}"

            return self._format_success(data, message)

        except Exception as e:
            logger.error(f"[AIWeightGeneratorTool] 错误: {e}")
            return self._format_error("EXECUTION_ERROR", str(e))

    def _analyze_market(self, df: pd.DataFrame) -> dict[str, Any]:
        """分析市场状态"""
        from core.trading.strategy.base import TradingStrategy

        # 计算指标
        df['adx'] = TradingStrategy.calculate_adx(df, 14)
        df['rsi'] = TradingStrategy.calculate_rsi(df, 14)
        df['atr'] = TradingStrategy.calculate_atr(df, 14)

        latest = df.iloc[-1]

        # 趋势判断
        adx = latest.get('adx', 0)
        if pd.isna(adx):
            adx = 0

        if adx > 30:
            trend = "strong_trend"
        elif adx > 20:
            trend = "moderate_trend"
        else:
            trend = "ranging"

        # 波动率判断
        atr = latest.get('atr', 0)
        close = latest['close']
        vol_pct = (atr / close) * 100 if close > 0 else 0

        if vol_pct > 5:
            volatility = "high"
        elif vol_pct > 2:
            volatility = "medium"
        else:
            volatility = "low"

        return {
            "trend": trend,
            "adx": round(adx, 2),
            "rsi": round(latest.get('rsi', 50), 2),
            "volatility": volatility,
            "volatility_pct": round(vol_pct, 2)
        }

    def _get_recommendation(self, weights, market_state: dict) -> str:
        """生成推荐说明"""
        max_weight = max(weights.to_dict().items(), key=lambda x: x[1])

        if max_weight[0] == 'trend':
            return f"强趋势市场(ADX={market_state['adx']})，建议以趋势策略为主"
        elif max_weight[0] == 'mean_reversion':
            return "震荡市场，建议以均值回归策略为主"
        else:
            return "低波动环境，建议关注关键支撑阻力位"


class InstantBacktestTool(BaseBTCTool):
    """
    即时回测工具

    快速回测策略，评估性能
    """

    tool_id = "instant_backtest"
    name = "即时策略回测"
    description = """
    对策略进行快速回测，评估最近N天的表现。

    支持:
    - 单策略回测
    - 多策略组合回测（加权）

    返回关键指标:
    - Profit Factor (盈亏比)
    - Sharpe Ratio (夏普比率)
    - Max Drawdown (最大回撤)
    - Win Rate (胜率)
    """

    input_schema = {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "default": "BTC"
            },
            "strategy": {
                "type": "string",
                "enum": ["trend", "mean_reversion", "support_resistance", "combined"],
                "default": "combined",
                "description": "回测的策略类型"
            },
            "days": {
                "type": "integer",
                "default": 30,
                "minimum": 7,
                "maximum": 90,
                "description": "回测天数"
            },
            "weights": {
                "type": "object",
                "description": "多策略组合时的权重（仅combined模式）",
                "properties": {
                    "trend": {"type": "number", "default": 0.4},
                    "mean_reversion": {"type": "number", "default": 0.3},
                    "support_resistance": {"type": "number", "default": 0.3}
                }
            }
        }
    }

    async def _execute(self,
                      symbol: str = "BTC",
                      strategy: str = "combined",
                      days: int = 30,
                      weights: dict = None,
                      **kwargs) -> dict[str, Any]:
        """执行回测"""
        if not PANDAS_AVAILABLE:
            return self._format_error("DEPENDENCY_MISSING", "pandas 未安装，回测工具不可用")
        from core.trading import MeanReversionStrategy, SupportResistanceStrategy, TrendStrategy
        from core.trading.backtest.engine import BacktestEngine
        from core.trading.data.provider import get_market_data_provider
        try:
            # 获取历史数据
            provider = get_market_data_provider()
            df = await provider.get_historical_data(symbol, interval="1h", days=days)

            if df.empty or len(df) < 100:
                return self._format_error("DATA_INSUFFICIENT", "数据不足，无法回测")

            # 准备策略
            engine = BacktestEngine(initial_capital=10000)

            if strategy == "combined":
                # 多策略组合
                w = weights or {"trend": 0.4, "mean_reversion": 0.3, "support_resistance": 0.3}
                strategies = [
                    (TrendStrategy(), w.get("trend", 0.4)),
                    (MeanReversionStrategy(), w.get("mean_reversion", 0.3)),
                    (SupportResistanceStrategy(), w.get("support_resistance", 0.3))
                ]
                result = engine.run(df, strategies)
            else:
                # 单策略
                strategy_map = {
                    "trend": TrendStrategy(),
                    "mean_reversion": MeanReversionStrategy(),
                    "support_resistance": SupportResistanceStrategy()
                }
                s = strategy_map.get(strategy, TrendStrategy())
                result = engine.run(df, s)

            # 返回简化结果
            data = {
                "symbol": symbol,
                "strategy": strategy,
                "test_period_days": days,
                "metrics": {
                    "profit_factor": round(result.profit_factor, 2),
                    "sharpe_ratio": round(result.sharpe_ratio, 2),
                    "max_drawdown_pct": round(result.max_drawdown_pct, 2),
                    "total_trades": result.total_trades,
                    "win_rate": round(result.win_rate * 100, 1),
                    "total_return_pct": round(result.total_return_pct, 2)
                },
                "assessment": self._assess_performance(result)
            }

            m = data["metrics"]
            message = f"回测完成 | PF:{m['profit_factor']} Sharpe:{m['sharpe_ratio']} MaxDD:{m['max_drawdown_pct']}% WinRate:{m['win_rate']}%"

            return self._format_success(data, message)

        except Exception as e:
            logger.error(f"[InstantBacktestTool] 错误: {e}")
            return self._format_error("EXECUTION_ERROR", str(e))

    def _assess_performance(self, result) -> str:
        """评估性能"""
        if result.total_trades < 5:
            return "交易次数太少，结果不可靠"

        score = 0
        if result.profit_factor > 1.5:
            score += 2
        elif result.profit_factor > 1.2:
            score += 1

        if result.sharpe_ratio > 1.5:
            score += 2
        elif result.sharpe_ratio > 1.0:
            score += 1

        if result.max_drawdown_pct > -10:
            score += 1

        if score >= 4:
            return "优秀策略，值得实盘测试"
        elif score >= 2:
            return "策略可行，建议进一步优化"
        else:
            return "策略表现一般，建议调整参数"


class StrategyOptimizerTool(BaseBTCTool):
    """
    策略优化工具

    使用AI优化策略参数
    """

    tool_id = "strategy_optimizer"
    name = "策略参数优化"
    description = "基于回测结果，使用AI优化策略参数"

    input_schema = {
        "type": "object",
        "properties": {
            "strategy": {
                "type": "string",
                "enum": ["trend", "mean_reversion", "support_resistance"],
                "description": "要优化的策略"
            },
            "target_metric": {
                "type": "string",
                "enum": ["profit_factor", "sharpe", "win_rate"],
                "default": "profit_factor",
                "description": "优化目标指标"
            }
        }
    }

    async def _execute(self,
                      strategy: str = "trend",
                      target_metric: str = "profit_factor",
                      **kwargs) -> dict[str, Any]:
        """执行优化"""
        if not PANDAS_AVAILABLE:
            return self._format_error("DEPENDENCY_MISSING", "pandas 未安装，优化工具不可用")
        from core.trading import MeanReversionStrategy, SupportResistanceStrategy, TrendStrategy
        from core.trading.backtest.engine import BacktestEngine
        from core.trading.data.provider import get_market_data_provider
        try:
            # 获取策略默认参数
            strategy_map = {
                "trend": TrendStrategy(),
                "mean_reversion": MeanReversionStrategy(),
                "support_resistance": SupportResistanceStrategy()
            }

            s = strategy_map.get(strategy)
            if not s:
                return self._format_error("INVALID_STRATEGY", "无效的策略名称")

            current_params = s.get_parameters()

            # 先回测获取当前性能
            provider = get_market_data_provider()
            df = await provider.get_historical_data("BTC", interval="1h", days=30)

            engine = BacktestEngine()
            result = engine.run_quick_backtest(df, s)

            # 调用AI优化参数
            generator = get_ai_strategy_generator()
            optimized_params = await generator.optimize_parameters(
                strategy,
                current_params,
                result
            )

            data = {
                "strategy": strategy,
                "original_params": current_params,
                "optimized_params": optimized_params,
                "original_performance": result,
                "target_metric": target_metric
            }

            message = f"{strategy} 策略参数已优化，建议测试新参数效果"

            return self._format_success(data, message)

        except Exception as e:
            logger.error(f"[StrategyOptimizerTool] 错误: {e}")
            return self._format_error("EXECUTION_ERROR", str(e))
