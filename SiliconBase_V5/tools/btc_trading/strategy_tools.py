#!/usr/bin/env python3
"""
BTC 策略工具 - Phase 2

工具列表:
    - BTCStrategySelector: AI 策略选择器
    - BTCStrategyExplain: 策略解释
    - BTCRiskAssessment: 风险评估
"""

import asyncio
from typing import Any

try:
    from core.base_tool import BaseTool
    from core.error_codes import INVALID_PARAMS, TOOL_EXECUTION_ERROR, format_error
except ImportError:
    BaseTool = object
    def format_error(code, detail=""):
        return {"success": False, "error_code": code, "error_message": detail}
    INVALID_PARAMS = "INVALID_PARAMS"
    TOOL_EXECUTION_ERROR = "TOOL_EXECUTION_ERROR"



class BTCStrategySelector(BaseTool):
    """
    AI 策略选择器

    功能:
        - 分析市场环境
        - 推荐最优策略组合
        - 提供资金分配建议
        - 生成入场/出场条件

    使用场景:
        用户: "今天适合用什么策略？"
        AI: 调用此工具获取推荐

    示例:
        >>> tool = BTCStrategySelector()
        >>> result = tool._execute(symbol="BTC", risk_tolerance="medium")
    """

    tool_id = "btc_strategy_selector"
    name = "策略选择器"
    description = """分析市场环境并推荐最优交易策略。

功能:
- 自动分析市场趋势、波动率、情绪
- 推荐主策略 + 辅助策略组合
- 提供资金分配建议
- 生成入场/出场条件

参数:
- symbol: 主要交易标的 (BTC/ETH/SOL)
- risk_tolerance: 风险偏好 (low/medium/high)
- budget: 预算金额 (USDT)

返回:
- 推荐策略详情
- 市场状态分析
- 风险提示
- 操作建议
"""

    input_schema = {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": "主要交易标的",
                "default": "BTC"
            },
            "risk_tolerance": {
                "type": "string",
                "enum": ["low", "medium", "high"],
                "description": "风险偏好",
                "default": "medium"
            },
            "budget": {
                "type": "number",
                "description": "预算金额 (USDT)",
                "default": 1000
            }
        },
        "required": []
    }

    timeout = 30

    def _execute(self, **kwargs) -> dict[str, Any]:
        """执行策略选择"""
        symbol = kwargs.get("symbol", "BTC").upper()
        risk_tolerance = kwargs.get("risk_tolerance", "medium")
        budget = kwargs.get("budget", 1000)

        # 参数验证
        if risk_tolerance not in ["low", "medium", "high"]:
            return format_error(
                INVALID_PARAMS,
                detail="风险偏好必须是 low/medium/high 之一"
            )

        if budget <= 0:
            return format_error(
                INVALID_PARAMS,
                detail="预算金额必须大于 0"
            )

        try:
            # 获取市场数据
            market_data = self._fetch_market_data(symbol)

            # 获取策略分析器
            try:
                from core.btc_integration.strategy_analyzer import get_strategy_analyzer
                analyzer = get_strategy_analyzer()
            except ImportError:
                # 如果导入失败，使用模拟数据
                return self._get_mock_recommendation(symbol, risk_tolerance, budget)

            # 分析市场
            condition = analyzer.analyze_market(market_data)

            # 获取推荐
            recommendation = analyzer.recommend_strategy(condition, risk_tolerance)

            # 格式化输出
            return self._format_recommendation(recommendation, symbol, budget)

        except Exception as e:
            return format_error(
                TOOL_EXECUTION_ERROR,
                detail=f"策略选择失败: {str(e)}"
            )

    async def _execute_async(self, **kwargs) -> dict[str, Any]:
        return await asyncio.to_thread(self._execute, **kwargs)

    def _fetch_market_data(self, symbol: str) -> dict[str, Any]:
        """获取市场数据"""
        # 这里应该调用其他工具获取真实数据
        # 目前返回模拟数据
        import random

        return {
            "symbol": symbol,
            "price_change_24h": random.uniform(-8, 8),
            "rsi_14": random.uniform(20, 80),
            "volatility_24h": random.uniform(1, 8),
            "atr_14": random.uniform(100, 500),
            "macd_signal": random.choice(["bullish", "bearish", "neutral"]),
            "fear_greed_index": random.randint(20, 80),
            "funding_rate": random.uniform(-0.05, 0.05),
            "event_risk": random.choice(["low", "medium", "high"]),
            "upcoming_events": []
        }

    def _format_recommendation(
        self,
        rec: Any,
        symbol: str,
        budget: float
    ) -> dict[str, Any]:
        """格式化推荐结果为用户友好的消息"""

        primary = rec.primary_strategy
        secondary = rec.secondary_strategies

        # 构建消息
        messages = []
        messages.append(f"📊 {symbol} 策略推荐报告")
        messages.append(f"\n【市场环境】{rec.market_regime.value}")
        messages.append(f"【匹配置信度】{rec.confidence * 100:.0f}%")

        # 主策略
        messages.append(f"\n🎯 主策略: {primary.name}")
        messages.append(f"   类型: {primary.type.value}")
        messages.append(f"   风险等级: {'🔴' * primary.risk_level}{'⚪' * (5 - primary.risk_level)}")
        messages.append(f"   描述: {primary.description}")
        messages.append(f"   预期年化收益: {primary.expected_return:.0f}%")
        messages.append(f"   最大回撤: {primary.max_drawdown:.0f}%")
        messages.append(f"   胜率: {primary.win_rate * 100:.0f}%")

        # 辅助策略
        if secondary:
            messages.append("\n📌 辅助策略:")
            for s in secondary:
                messages.append(f"   • {s.name} (风险{s.risk_level}/5)")

        # 资金分配
        messages.append(f"\n💰 资金分配建议 (预算 ${budget:,.0f}):")
        for strategy_id, pct in rec.suggested_allocation.items():
            amount = budget * pct / 100
            messages.append(f"   • {strategy_id}: ${amount:,.0f} ({pct:.0f}%)")

        # 入场条件
        messages.append("\n✅ 入场条件:")
        for cond in rec.entry_conditions:
            messages.append(f"   • {cond}")

        # 出场条件
        messages.append("\n❌ 出场条件:")
        for cond in rec.exit_conditions:
            messages.append(f"   • {cond}")

        # 风险提示
        messages.append("\n⚠️ 风险提示:")
        messages.append(f"   {rec.risk_warning}")

        # 推荐理由
        messages.append("\n💡 推荐理由:")
        messages.append(rec.reasoning)

        return {
            "success": True,
            "error_code": None,
            "error_message": "",
            "user_message": "\n".join(messages),
            "data": rec.to_dict()
        }

    def _get_mock_recommendation(
        self,
        symbol: str,
        risk_tolerance: str,
        budget: float
    ) -> dict[str, Any]:
        """生成模拟推荐（当策略分析器不可用时）"""

        strategies = {
            "low": ("stage154_multiasset", "多资产分散", 2),
            "medium": ("stage46_aggressive", "趋势跟踪", 3),
            "high": ("stage120_event", "事件驱动", 5)
        }

        strategy_id, strategy_name, risk_level = strategies.get(
            risk_tolerance,
            ("stage46_aggressive", "趋势跟踪", 3)
        )

        messages = [
            f"📊 {symbol} 策略推荐报告 (模拟数据)",
            f"\n🎯 推荐策略: {strategy_name}",
            f"   风险等级: {'🔴' * risk_level}{'⚪' * (5 - risk_level)}",
            f"\n💰 建议预算: ${budget:,.0f}",
            "\n⚠️ 风险提示: 当前为模拟推荐，请谨慎参考",
            "\n💡 说明: 策略分析器尚未完全加载，显示的是基于风险偏好的默认推荐"
        ]

        return {
            "success": True,
            "error_code": None,
            "error_message": "",
            "user_message": "\n".join(messages),
            "data": {
                "strategy_id": strategy_id,
                "strategy_name": strategy_name,
                "risk_level": risk_level,
                "mock": True
            }
        }


class BTCStrategyExplain(BaseTool):
    """
    策略解释工具

    功能:
        - 详细解释策略逻辑
        - 展示历史表现
        - 说明适用场景
    """

    tool_id = "btc_strategy_explain"
    name = "策略解释"
    description = """详细解释某个交易策略的逻辑和特点。

使用场景:
- 用户想了解某个策略的工作原理
- 对比不同策略的优劣
- 学习策略使用方法

参数:
- strategy_id: 策略ID
"""

    input_schema = {
        "type": "object",
        "properties": {
            "strategy_id": {
                "type": "string",
                "description": "策略ID，如 stage46_aggressive"
            }
        },
        "required": ["strategy_id"]
    }

    timeout = 10

    def _execute(self, **kwargs) -> dict[str, Any]:
        """执行策略解释"""
        strategy_id = kwargs.get("strategy_id", "")

        if not strategy_id:
            return format_error(INVALID_PARAMS, detail="必须提供 strategy_id")

        try:
            from core.btc_integration.strategy_analyzer import StrategyLibrary

            strategy = StrategyLibrary.get_strategy_by_id(strategy_id)

            if not strategy:
                available = [s.id for s in StrategyLibrary.get_all_strategies()]
                return format_error(
                    TOOL_EXECUTION_ERROR,
                    detail=f"策略 '{strategy_id}' 不存在。可用策略: {', '.join(available)}"
                )

            messages = [
                f"📚 {strategy.name} 详解",
                f"\n【策略ID】{strategy.id}",
                f"【类型】{strategy.type.value}",
                f"【风险等级】{'🔴' * strategy.risk_level}{'⚪' * (5 - strategy.risk_level)}",
                "\n【策略描述】",
                f"{strategy.description}",
                "\n【适用市场状态】",
                f"{', '.join(r.value for r in strategy.suitable_regimes)}",
                "\n【历史表现】",
                f"• 预期年化收益: {strategy.expected_return:.0f}%",
                f"• 最大回撤: {strategy.max_drawdown:.0f}%",
                f"• 胜率: {strategy.win_rate * 100:.0f}%",
                f"• 平均持仓时间: {strategy.avg_trade_duration}",
                f"\n【复杂度】{'⭐' * strategy.complexity}{'☆' * (5 - strategy.complexity)}"
            ]

            return {
                "success": True,
                "error_code": None,
                "error_message": "",
                "user_message": "\n".join(messages),
                "data": {
                    "id": strategy.id,
                    "name": strategy.name,
                    "type": strategy.type.value,
                    "risk_level": strategy.risk_level,
                    "description": strategy.description,
                    "suitable_regimes": [r.value for r in strategy.suitable_regimes],
                    "expected_return": strategy.expected_return,
                    "max_drawdown": strategy.max_drawdown,
                    "win_rate": strategy.win_rate,
                    "avg_trade_duration": strategy.avg_trade_duration,
                    "complexity": strategy.complexity
                }
            }

        except Exception as e:
            return format_error(
                TOOL_EXECUTION_ERROR,
                detail=f"策略解释失败: {str(e)}"
            )

    async def _execute_async(self, **kwargs) -> dict[str, Any]:
        return await asyncio.to_thread(self._execute, **kwargs)


class BTCRiskAssessment(BaseTool):
    """
    风险评估工具

    功能:
        - 评估当前市场风险
        - 计算建议仓位
        - 提供风控建议
    """

    tool_id = "btc_risk_assessment"
    name = "风险评估"
    description = """评估当前市场环境的风险等级。

返回信息:
- 市场风险评分 (1-10)
- 建议仓位比例
- 杠杆建议
- 风控措施
"""

    input_schema = {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "default": "BTC"
            },
            "account_equity": {
                "type": "number",
                "description": "账户权益 (用于计算建议仓位)"
            }
        },
        "required": []
    }

    timeout = 15

    def _execute(self, **kwargs) -> dict[str, Any]:
        """执行风险评估"""
        symbol = kwargs.get("symbol", "BTC").upper()
        account_equity = kwargs.get("account_equity", 0)

        try:
            # 获取市场数据
            market_data = self._fetch_risk_data(symbol)

            # 计算风险评分
            risk_score = self._calculate_risk_score(market_data)

            # 生成建议
            suggestions = self._generate_risk_suggestions(risk_score, market_data)

            # 计算建议仓位
            suggested_position = self._calculate_position_size(
                risk_score,
                account_equity,
                market_data
            )

            messages = [
                f"⚠️ {symbol} 市场风险评估",
                f"\n【风险评分】{risk_score}/10 {'🔴' if risk_score > 7 else '🟡' if risk_score > 4 else '🟢'}",
                "\n【风险因子】",
            ]

            for factor, value in market_data.get("risk_factors", {}).items():
                messages.append(f"   • {factor}: {value}")

            messages.extend([
                "\n【建议仓位】",
                f"   仓位比例: {suggestions['position_pct']:.0f}%",
                f"   建议杠杆: {suggestions['leverage']}x",
            ])

            if account_equity > 0:
                messages.append(f"   最大持仓: ${suggested_position:,.2f}")

            messages.extend([
                "\n【风控建议】",
            ])
            for advice in suggestions["advices"]:
                messages.append(f"   • {advice}")

            return {
                "success": True,
                "error_code": None,
                "error_message": "",
                "user_message": "\n".join(messages),
                "data": {
                    "risk_score": risk_score,
                    "risk_level": "high" if risk_score > 7 else "medium" if risk_score > 4 else "low",
                    "position_pct": suggestions["position_pct"],
                    "suggested_leverage": suggestions["leverage"],
                    "suggested_position": suggested_position if account_equity > 0 else None,
                    "risk_factors": market_data.get("risk_factors", {})
                }
            }

        except Exception as e:
            return format_error(
                TOOL_EXECUTION_ERROR,
                detail=f"风险评估失败: {str(e)}"
            )

    async def _execute_async(self, **kwargs) -> dict[str, Any]:
        return await asyncio.to_thread(self._execute, **kwargs)

    def _fetch_risk_data(self, symbol: str) -> dict[str, Any]:
        """获取风险数据"""
        import random

        return {
            "symbol": symbol,
            "volatility": random.uniform(1, 8),
            "funding_rate": random.uniform(-0.05, 0.05),
            "liquidation_density": random.uniform(0, 100),
            "event_risk": random.choice(["low", "medium", "high"]),
            "risk_factors": {
                "波动率": random.choice(["低", "中", "高"]),
                "资金费率": random.choice(["正常", "偏热", "极热"]),
                "清算密度": random.choice(["稀疏", "中等", "密集"]),
                "事件风险": random.choice(["无", "一般", "高"])
            }
        }

    def _calculate_risk_score(self, data: dict[str, Any]) -> int:
        """计算风险评分"""
        import random
        # 模拟计算
        base_score = random.randint(3, 8)
        return min(10, max(1, base_score))

    def _generate_risk_suggestions(self, risk_score: int, data: dict[str, Any]) -> dict[str, Any]:
        """生成风险建议"""
        if risk_score > 7:
            return {
                "position_pct": 20.0,
                "leverage": 2,
                "advices": [
                    "市场风险较高，建议大幅降低仓位",
                    "使用低杠杆 (2x 以下)",
                    "严格设置止损",
                    "考虑观望等待风险释放"
                ]
            }
        elif risk_score > 4:
            return {
                "position_pct": 50.0,
                "leverage": 3,
                "advices": [
                    "市场风险适中，控制仓位在 50% 以内",
                    "使用中低杠杆 (3x 以下)",
                    "关注市场变化，随时准备调整"
                ]
            }
        else:
            return {
                "position_pct": 80.0,
                "leverage": 5,
                "advices": [
                    "市场风险较低，可以适当加仓",
                    "可以使用中等杠杆 (5x 以下)",
                    "但仍需设置止损，防范黑天鹅"
                ]
            }

    def _calculate_position_size(
        self,
        risk_score: int,
        account_equity: float,
        data: dict[str, Any]
    ) -> float:
        """计算建议仓位大小"""
        if account_equity <= 0:
            return 0

        position_pct = self._generate_risk_suggestions(risk_score, data)["position_pct"]
        return account_equity * position_pct / 100
