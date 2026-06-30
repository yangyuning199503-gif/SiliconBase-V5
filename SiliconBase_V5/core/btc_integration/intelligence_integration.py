#!/usr/bin/env python3
"""
智能系统集成层
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
连接 World Model V2 和 Reflector V3 到交易系统

职责:
1. 交易前: World Model 预测决策结果
2. 交易后: Reflector 分析优化策略
3. 策略进化: 基于反思结果调整参数

作者: SiliconBase Team
日期: 2026-04-09
"""

import time
from dataclasses import dataclass, field
from typing import Any

from core.logger import logger

# World Model V2
try:
    from core.world_model.world_model import get_world_model
    WORLD_MODEL_AVAILABLE = True
except ImportError as e:
    WORLD_MODEL_AVAILABLE = False
    logger.warning(f"[IntelligenceIntegration] World Model V2 不可用: {e}")

# Reflector V3
try:
    from core.reflector.reflector import get_reflector
    REFLECTOR_AVAILABLE = True
except ImportError as e:
    REFLECTOR_AVAILABLE = False
    logger.warning(f"[IntelligenceIntegration] Reflector V3 不可用: {e}")

# Smart Quant V2
try:
    # 仅探测 SmartQuantEngine 是否可用，类本身当前未直接使用
    from core.btc_integration.smart_quant_engine import SmartQuantEngine  # noqa: F401
    SMART_QUANT_AVAILABLE = True
except ImportError as e:
    SMART_QUANT_AVAILABLE = False
    logger.warning(f"[IntelligenceIntegration] SmartQuantEngine 不可用: {e}")


@dataclass
class PredictionResult:
    """World Model 预测结果"""
    success_probability: float = 0.5      # 成功概率 0-1
    expected_pnl: float = 0.0             # 预期收益
    risk_score: float = 0.5               # 风险评分 0-1
    confidence: float = 0.5               # 预测置信度
    recommended_action: str = "monitor"   # 建议行动
    reasoning: str = ""                   # 推理过程


@dataclass
class TradeReflection:
    """交易反思结果"""
    execution_insight: str = ""           # 执行层洞察
    strategy_insight: str = ""            # 策略层洞察
    improvement_suggestion: str = ""      # 改进建议
    should_evolve: bool = False           # 是否需要进化
    new_params: dict | None = None     # 新参数建议
    quality_score: float = 0.0            # 反思质量评分


@dataclass
class StrategyEvolution:
    """策略进化记录"""
    symbol: str
    old_params: dict[str, Any]
    new_params: dict[str, Any]
    evolution_reason: str
    performance_delta: float
    timestamp: float = field(default_factory=time.time)


class TradingIntelligenceIntegration:
    """
    交易智能集成器

    将 World Model 和 Reflector 集成到交易流程:
    - 预交易: World Model 预测
    - 后交易: Reflector 反思
    - 持续: 策略进化

    单例模式实现。
    """

    _instance = None
    _lock = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self.world_model: Any | None = None
        self.reflector: Any | None = None

        # 策略进化历史
        self.evolution_history: list[StrategyEvolution] = []
        self.max_history = 100

        self._initialize_components()
        logger.info("[TradingIntelligenceIntegration] 初始化完成")

    def _initialize_components(self):
        """延迟初始化组件"""
        if WORLD_MODEL_AVAILABLE:
            try:
                self.world_model = get_world_model()
                logger.info("[TradingIntelligenceIntegration] World Model V2 已连接")
            except Exception as e:
                logger.error(f"[TradingIntelligenceIntegration] World Model 初始化失败: {e}")

        if REFLECTOR_AVAILABLE:
            try:
                self.reflector = get_reflector()
                logger.info("[TradingIntelligenceIntegration] Reflector V3 已连接")
            except Exception as e:
                logger.error(f"[TradingIntelligenceIntegration] Reflector 初始化失败: {e}")

    async def predict_trade_outcome(
        self,
        decision: Any,
        context: Any
    ) -> PredictionResult | None:
        """
        交易前预测：使用 World Model 评估决策

        Args:
            decision: AI 交易决策 (TradingDecision)
            context: 市场上下文 (MarketContext)

        Returns:
            PredictionResult 或 None（如果不可用）
        """
        if not self.world_model:
            return None

        if not SMART_QUANT_AVAILABLE:
            return None

        try:
            # 构建感知字典
            perception = self._build_perception(context)

            # 获取决策动作信息
            action_str = decision.action if hasattr(decision, 'action') else 'hold'
            strategy_params = decision.strategy_params.to_dict() if hasattr(decision, 'strategy_params') and decision.strategy_params else {}

            # 【修复】使用 predict_detailed 方法（实际接口）
            prediction = self.world_model.predict_detailed(
                perception=perception,
                tool_id=f"trade_{action_str}",
                params=strategy_params,
                task_context={"symbol": getattr(context, 'symbol', 'unknown')}
            )

            # 解析预测结果
            result = PredictionResult(
                success_probability=float(prediction.get("success_prob", 0.5)),
                expected_pnl=float(prediction.get("expected_reward", 0.0)),
                risk_score=float(prediction.get("risk", 0.5)),
                confidence=float(prediction.get("confidence", 0.5)),
                recommended_action=action_str if prediction.get("success_prob", 0.5) > 0.5 else "hold",
                reasoning=f"World Model预测成功率: {prediction.get('success_prob', 0.5):.2f}"
            )

            logger.info(
                f"[WorldModel] 预测 {action_str}: "
                f"成功概率={result.success_probability:.2f}, "
                f"预期收益={result.expected_pnl:.2f}, "
                f"风险={result.risk_score:.2f}"
            )

            return result

        except Exception as e:
            logger.error(f"[WorldModel] 预测失败: {e}")
            return None

    async def reflect_on_trade(
        self,
        execution: Any
    ) -> TradeReflection | None:
        """
        交易后反思：使用 Reflector 分析执行

        Args:
            execution: 交易执行记录 (TradeExecution)

        Returns:
            TradeReflection 或 None（如果不可用）
        """
        if not self.reflector:
            return None

        try:
            # 执行层反思
            exec_reflection = await self._reflect_execution(execution)

            # 策略层反思（仅当亏损或异常）
            strategy_reflection = None
            pnl = getattr(execution, 'pnl', None)
            status = getattr(execution, 'status', 'unknown')

            if pnl is None or pnl < 0 or status != "success":
                strategy_reflection = await self._reflect_strategy(execution)

            # 计算质量评分
            quality_score = self._calculate_reflection_quality(
                exec_reflection, strategy_reflection
            )

            # 聚合反思结果
            result = TradeReflection(
                execution_insight=exec_reflection.get("insight", ""),
                strategy_insight=strategy_reflection.get("insight", "") if strategy_reflection else "",
                improvement_suggestion=self._aggregate_suggestions(
                    exec_reflection, strategy_reflection
                ),
                should_evolve=strategy_reflection is not None and quality_score > 0.6,
                new_params=strategy_reflection.get("new_params") if strategy_reflection else None,
                quality_score=quality_score
            )

            symbol = getattr(execution, 'symbol', 'unknown')
            logger.info(
                f"[Reflector] 交易反思完成: {symbol}, "
                f"质量评分={quality_score:.2f}, "
                f"建议进化={result.should_evolve}"
            )
            return result

        except Exception as e:
            logger.error(f"[Reflector] 反思失败: {e}")
            return None

    async def _reflect_execution(self, execution: Any) -> dict[str, Any]:
        """执行层反思 - 使用 Reflector V3"""
        if not self.reflector or not REFLECTOR_AVAILABLE:
            # 降级到简化实现
            action = getattr(execution, 'action', 'unknown')
            price = getattr(execution, 'price', 0.0)
            status = getattr(execution, 'status', 'unknown')
            return {
                "observation": f"执行 {action} @ {price}",
                "insight": "执行正常" if status == "success" else "执行异常",
                "suggestion": "保持当前执行方式" if status == "success" else "检查执行逻辑",
                "confidence": 0.8 if status == "success" else 0.5
            }

        try:
            # 【修复】使用 Reflector 实际接口 reflect_after_step
            action = getattr(execution, 'action', 'unknown')
            price = getattr(execution, 'price', 0.0)
            pnl = getattr(execution, 'pnl', 0.0)
            status = getattr(execution, 'status', 'unknown')

            step_info = {
                "tool": f"trade_{action}",
                "params": {"price": price},
                "result": {"pnl": pnl, "status": status},
                "success": status == "success" and pnl >= 0
            }

            # 调用 Reflector（异步方法）
            reflection = await self.reflector.reflect_after_step(
                task=f"交易执行 {action}",
                step_info=step_info,
                trajectory=[step_info]
            )

            if reflection:
                return {
                    "observation": reflection.observation,
                    "insight": reflection.insight,
                    "suggestion": reflection.suggestion,
                    "confidence": reflection.confidence,
                    "quality_score": reflection.quality_score
                }
            else:
                # 成功时 Reflector 返回 None
                return {
                    "observation": f"执行 {action} @ {price}",
                    "insight": "执行成功",
                    "suggestion": "保持当前执行方式",
                    "confidence": 0.8
                }

        except Exception as e:
            logger.error(f"[Reflector] 执行反思失败: {e}")
            return {
                "observation": "反思失败",
                "insight": "无法获取洞察",
                "suggestion": "继续观察",
                "confidence": 0.5
            }

    async def _reflect_strategy(self, execution: Any) -> dict[str, Any]:
        """策略层反思（亏损时）- 使用 Reflector V3"""
        if not self.reflector or not REFLECTOR_AVAILABLE:
            # 降级到简化实现
            strategy = getattr(execution, 'strategy', 'unknown')
            pnl = getattr(execution, 'pnl', 0.0)
            symbol = getattr(execution, 'symbol', 'unknown')
            return {
                "observation": f"策略 {strategy} 在 {symbol} 亏损 {pnl}",
                "insight": "市场条件变化导致策略失效，建议调整参数",
                "suggestion": "降低止损阈值，减少仓位",
                "new_params": {"stop_loss_pct": 1.5, "position_size_pct": 0.8},
                "confidence": 0.7
            }

        try:
            # 【修复】使用 Reflector 实际接口 reflect_after_success（用于分析优化空间）
            strategy = getattr(execution, 'strategy', 'unknown')
            pnl = getattr(execution, 'pnl', 0.0)
            symbol = getattr(execution, 'symbol', 'unknown')

            trajectory = [{
                "strategy": strategy,
                "symbol": symbol,
                "pnl": pnl,
                "action": getattr(execution, 'action', 'unknown')
            }]

            # 调用 Reflector（即使亏损也分析如何优化）
            reflection = await self.reflector.reflect_after_success(
                task=f"策略 {strategy} 交易",
                trajectory=trajectory,
                final_result=f"亏损 {pnl}"
            )

            if reflection:
                # 提取改进建议
                new_params = {}
                suggestion_lower = reflection.suggestion.lower()

                if "止损" in suggestion_lower or "stop" in suggestion_lower:
                    new_params["stop_loss_pct"] = 1.5
                if "仓位" in suggestion_lower or "size" in suggestion_lower:
                    new_params["position_size_pct"] = 0.8
                if "rsi" in suggestion_lower:
                    new_params["rsi_threshold"] = 30

                return {
                    "observation": reflection.observation,
                    "insight": reflection.insight,
                    "suggestion": reflection.suggestion,
                    "new_params": new_params if new_params else {"stop_loss_pct": 1.5},
                    "confidence": reflection.confidence,
                    "quality_score": reflection.quality_score
                }
            else:
                return {
                    "observation": f"策略 {strategy} 亏损 {pnl}",
                    "insight": "需要优化策略参数",
                    "suggestion": "调整止损和仓位管理",
                    "new_params": {"stop_loss_pct": 1.5},
                    "confidence": 0.6
                }

        except Exception as e:
            logger.error(f"[Reflector] 策略反思失败: {e}")
            return {
                "observation": "策略反思失败",
                "insight": "无法获取策略洞察",
                "suggestion": "保持当前策略",
                "confidence": 0.5
            }

    def _calculate_reflection_quality(
        self,
        exec_reflection: dict,
        strategy_reflection: dict | None
    ) -> float:
        """计算反思质量评分"""
        scores = []

        if exec_reflection:
            scores.append(exec_reflection.get("confidence", 0.5))

        if strategy_reflection:
            scores.append(strategy_reflection.get("confidence", 0.5))

        return sum(scores) / len(scores) if scores else 0.5

    def _build_perception(self, context: Any) -> dict[str, Any]:
        """构建感知字典（用于 World Model 接口）"""
        if not context:
            return {
                "price": 0.0,
                "trend": "neutral",
                "volatility": 0.0,
                "news_count": 0
            }

        price = getattr(context, 'price', 0.0)
        trend = getattr(context, 'trend', 'neutral')
        volatility = getattr(context, 'volatility', 0.0)
        recent_news = getattr(context, 'recent_news', [])
        rsi = getattr(context, 'rsi', 50.0)
        fear_greed = getattr(context, 'fear_greed_index', 50)

        return {
            "price": price,
            "price_norm": price / 100000.0 if price > 0 else 0.0,
            "trend": trend,
            "trend_val": 1.0 if trend == "up" else (-1.0 if trend == "down" else 0.0),
            "volatility": volatility,
            "news_count": len(recent_news),
            "rsi": rsi,
            "fear_greed": fear_greed,
            "timestamp": time.time()
        }

    def _aggregate_suggestions(self, *reflections: dict | None) -> str:
        """聚合多条反思建议"""
        suggestions = []
        for r in reflections:
            if r and isinstance(r, dict) and "suggestion" in r:
                suggestions.append(str(r["suggestion"]))
        return "; ".join(suggestions) if suggestions else "无需改进"

    def record_trade_experience(
        self,
        context: Any,
        decision: Any,
        execution: Any
    ):
        """记录交易经验到 World Model"""
        if not self.world_model:
            return

        try:
            # 【修复】使用 observe_tool_execution 方法（实际接口）
            perception_before = self._build_perception(context)
            perception_after = perception_before.copy()  # 简化

            action_str = decision.action if hasattr(decision, 'action') else 'hold'
            strategy_params = decision.strategy_params.to_dict() if hasattr(decision, 'strategy_params') and decision.strategy_params else {}

            reward = getattr(execution, 'pnl', 0.0) or 0.0

            self.world_model.observe_tool_execution(
                tool_id=f"trade_{action_str}",
                params=strategy_params,
                perception_before=perception_before,
                perception_after=perception_after,
                result={
                    'success': reward > 0,
                    'reward': reward,
                    'pnl': reward
                },
                task_context={
                    'symbol': getattr(context, 'symbol', 'unknown'),
                    'task_completed': True
                }
            )

            logger.debug(f"[WorldModel] 已记录经验: reward={reward:.4f}")

        except Exception as e:
            logger.error(f"[WorldModel] 记录经验失败: {e}")

    def record_strategy_evolution(
        self,
        symbol: str,
        old_params: dict[str, Any],
        new_params: dict[str, Any],
        reason: str,
        performance_delta: float = 0.0
    ):
        """记录策略进化"""
        evolution = StrategyEvolution(
            symbol=symbol,
            old_params=old_params.copy(),
            new_params=new_params.copy(),
            evolution_reason=reason,
            performance_delta=performance_delta
        )

        self.evolution_history.append(evolution)

        # 限制历史记录数量
        if len(self.evolution_history) > self.max_history:
            self.evolution_history = self.evolution_history[-self.max_history:]

        logger.info(
            f"[StrategyEvolution] {symbol}: 参数已进化, "
            f"原因={reason}, 性能变化={performance_delta:.4f}"
        )

    def get_evolution_history(
        self,
        symbol: str | None = None,
        limit: int = 10
    ) -> list[StrategyEvolution]:
        """获取策略进化历史"""
        history = self.evolution_history

        if symbol:
            history = [e for e in history if e.symbol == symbol]

        return sorted(history, key=lambda x: x.timestamp, reverse=True)[:limit]

    def get_intelligence_status(self) -> dict[str, Any]:
        """获取智能系统状态"""
        return {
            "world_model_available": WORLD_MODEL_AVAILABLE and self.world_model is not None,
            "reflector_available": REFLECTOR_AVAILABLE and self.reflector is not None,
            "evolution_count": len(self.evolution_history),
            "last_evolution": self.evolution_history[-1].timestamp if self.evolution_history else None
        }


# ═══════════════════════════════════════════════════════════════
# 全局实例工厂
# ═══════════════════════════════════════════════════════════════

_intelligence_instance: TradingIntelligenceIntegration | None = None


def get_trading_intelligence() -> TradingIntelligenceIntegration:
    """获取交易智能集成器实例（单例）"""
    global _intelligence_instance
    if _intelligence_instance is None:
        _intelligence_instance = TradingIntelligenceIntegration()
    return _intelligence_instance


def reset_trading_intelligence():
    """重置智能集成器（主要用于测试）"""
    global _intelligence_instance
    _intelligence_instance = None
    logger.info("[TradingIntelligenceIntegration] 已重置")


# 便捷函数
async def predict_trade(decision: Any, context: Any) -> PredictionResult | None:
    """便捷函数：预测交易结果"""
    intelligence = get_trading_intelligence()
    return await intelligence.predict_trade_outcome(decision, context)


async def reflect_trade(execution: Any) -> TradeReflection | None:
    """便捷函数：反思交易"""
    intelligence = get_trading_intelligence()
    return await intelligence.reflect_on_trade(execution)
