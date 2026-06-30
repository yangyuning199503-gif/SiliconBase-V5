#!/usr/bin/env python3
"""
AI策略生成器

基于市场状态自动生成策略权重和参数
"""

import json
import re
from dataclasses import dataclass
from typing import Any

from core.ai.ai_client import AIClient
from core.logger import logger


@dataclass
class StrategyWeights:
    """策略权重配置"""
    trend: float = 0.4
    mean_reversion: float = 0.2
    support_resistance: float = 0.4

    def to_dict(self) -> dict[str, float]:
        return {
            'trend': self.trend,
            'mean_reversion': self.mean_reversion,
            'support_resistance': self.support_resistance
        }

    def validate(self) -> bool:
        """验证权重总和为1"""
        total = sum(self.to_dict().values())
        return abs(total - 1.0) < 0.001


class AIStrategyGenerator:
    """
    AI策略生成器

    根据市场状态生成最优策略权重
    """

    def __init__(self):
        self.ai_client = AIClient()

    async def initialize(self):
        """初始化AI客户端（如果支持）"""
        if hasattr(self.ai_client, 'initialize'):
            await self.ai_client.initialize()

    async def generate_weights(
                              self,
                              market_state: dict[str, Any],
                              sentiment_data: dict[str, Any] = None) -> StrategyWeights:
        """
        生成策略权重

        Args:
            market_state: 市场状态数据
            sentiment_data: 情绪数据（可选）

        Returns:
            StrategyWeights: 策略权重
        """
        try:
            # 构建prompt
            prompt = self._build_prompt(market_state, sentiment_data)

            # 调用AI
            response = await self.ai_client.chat(prompt)

            # 解析权重
            weights = self._parse_weights(response)

            # 验证
            if not weights.validate():
                logger.warning("[AIStrategyGenerator] AI返回权重无效，使用默认权重")
                return StrategyWeights()

            return weights

        except Exception as e:
            logger.error(f"[AIStrategyGenerator] 生成权重失败: {e}")
            return StrategyWeights()  # 返回默认权重

    def _build_prompt(self,
                     market_state: dict[str, Any],
                     sentiment_data: dict[str, Any] = None) -> str:
        """构建AI提示词"""

        # 市场状态描述
        trend = market_state.get('trend', 'unknown')
        volatility = market_state.get('volatility', 'medium')
        adx = market_state.get('adx', 0)
        rsi = market_state.get('rsi', 50)

        prompt = f"""你是一个专业的加密货币量化分析师。

## 当前市场状态
- 趋势: {trend}
- 波动率: {volatility}
- ADX(趋势强度): {adx}
- RSI: {rsi}

## 策略说明
1. 趋势策略 (trend): ADX + 突破，适合强趋势市场
2. 均值回归策略 (mean_reversion): RSI + 布林带，适合震荡市场
3. 支撑阻力策略 (support_resistance): 关键价格水平，适合低波动市场

## 任务
基于当前市场状态，为三个策略分配权重（总和必须为1.0）。

## 输出格式
请以JSON格式输出，只返回权重：
```json
{{
    "trend": 0.5,
    "mean_reversion": 0.2,
    "support_resistance": 0.3
}}
```

## 示例
- 强趋势市场(ADX>30): {{"trend": 0.7, "mean_reversion": 0.1, "support_resistance": 0.2}}
- 震荡市场(ADX<20): {{"trend": 0.2, "mean_reversion": 0.5, "support_resistance": 0.3}}

请给出当前市场的最优权重配置："""

        return prompt

    def _parse_weights(self, response: str) -> StrategyWeights:
        """解析AI返回的权重"""
        try:
            # 尝试从JSON中提取
            import re

            # 查找JSON代码块
            json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
            # 提取 JSON 代码块，否则直接解析整个响应
            json_str = json_match.group(1) if json_match else response

            data = json.loads(json_str)

            return StrategyWeights(
                trend=float(data.get('trend', 0.4)),
                mean_reversion=float(data.get('mean_reversion', 0.2)),
                support_resistance=float(data.get('support_resistance', 0.4))
            )

        except Exception as e:
            logger.error(f"[AIStrategyGenerator] 解析权重失败: {e}")
            return StrategyWeights()

    async def optimize_parameters(self,
                                  strategy_name: str,
                                  current_params: dict[str, Any],
                                  backtest_result: dict[str, Any]) -> dict[str, Any]:
        """
        优化策略参数

        Args:
            strategy_name: 策略名称
            current_params: 当前参数
            backtest_result: 回测结果

        Returns:
            优化后的参数
        """
        try:
            prompt = f"""优化交易策略参数。

## 策略
{strategy_name}

## 当前参数
{json.dumps(current_params, indent=2)}

## 回测结果
- Profit Factor: {backtest_result.get('pf', 0)}
- Sharpe Ratio: {backtest_result.get('sharpe', 0)}
- Max Drawdown: {backtest_result.get('max_dd', 0)}%
- Win Rate: {backtest_result.get('win_rate', 0)}

## 任务
基于回测结果，建议参数优化（小幅调整）。输出JSON格式的新参数。
"""

            response = await self.ai_client.chat(prompt)

            # 解析参数
            json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(1))

            return current_params

        except Exception as e:
            logger.error(f"[AIStrategyGenerator] 优化参数失败: {e}")
            return current_params


# 全局生成器实例
_generator: AIStrategyGenerator = None


def get_ai_strategy_generator() -> AIStrategyGenerator:
    """获取全局AI策略生成器"""
    global _generator
    if _generator is None:
        _generator = AIStrategyGenerator()
    return _generator
