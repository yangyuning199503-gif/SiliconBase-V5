#!/usr/bin/env python3
"""
模型升级编排器 - Model Upgrade Orchestrator

协调模型路由、成本控制和降级管理的统一接口。

这是模型升级方案的核心入口，提供：
1. 智能模型选择
2. 成本监控和限制
3. 自动降级处理
4. 统一API接口

使用示例：
    orchestrator = ModelUpgradeOrchestrator()

    # 简单调用
    result = await orchestrator.chat("你好")

    # 高级调用
    result = await orchestrator.chat_with_smart_upgrade(
        message="帮我分析这个复杂问题",
        task_type="analysis",
        strategy=RoutingStrategy.QUALITY_FIRST
    )
"""

import asyncio
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from core.ai.model_profile import TaskType
from core.logger import logger
from core.providers.ai_provider_factory import AIProviderFactory

from .cost_controller import BudgetLimit, CostAlert, CostController, CostRecord
from .enhanced_router import EnhancedModelRouter, RoutingResult, RoutingStrategy, TaskRequirements
from .fallback_manager import FallbackManager, FallbackReason


@dataclass
class ChatResult:
    """聊天结果"""
    content: str
    provider: str
    model: str
    cost: float
    latency_ms: int
    input_tokens: int
    output_tokens: int
    routing_info: dict[str, Any]
    success: bool
    error: str | None = None


class ModelUpgradeOrchestrator:
    """
    模型升级编排器

    统一协调路由、成本和降级策略。
    """

    def __init__(self,
                 budget: BudgetLimit | None = None,
                 default_strategy: RoutingStrategy = RoutingStrategy.ADAPTIVE):
        """
        初始化编排器

        Args:
            budget: 预算限制
            default_strategy: 默认路由策略
        """
        self.router = EnhancedModelRouter()
        self.cost_controller = CostController(budget=budget)
        self.fallback_manager = FallbackManager()
        self.default_strategy = default_strategy

        # 回调函数
        self._cost_alert_callbacks: list[Callable[[CostAlert], None]] = []

        # 注册成本告警回调
        self.cost_controller.add_alert_callback(self._on_cost_alert)

        # 统计
        self._stats = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "total_cost": 0.0,
            "total_latency_ms": 0
        }

        logger.info("[ModelUpgradeOrchestrator] 初始化完成")

    async def chat(self,
                  message: str,
                  context: list[dict] | None = None,
                  task_type: str | None = None,
                  require_vision: bool = False,
                  require_tools: bool = False,
                  **kwargs) -> ChatResult:
        """
        简单聊天接口（自动路由）

        Args:
            message: 用户消息
            context: 对话上下文
            task_type: 任务类型（可选，自动检测）
            require_vision: 是否需要视觉支持
            require_tools: 是否需要工具支持

        Returns:
            ChatResult: 聊天结果
        """
        return await self.chat_with_smart_upgrade(
            message=message,
            context=context,
            task_type=task_type or "chat",
            require_vision=require_vision,
            require_tools=require_tools,
            strategy=self.default_strategy,
            **kwargs
        )

    async def chat_with_smart_upgrade(self,
                                     message: str,
                                     context: list[dict] | None = None,
                                     task_type: str = "chat",
                                     strategy: RoutingStrategy | None = None,
                                     max_budget: float | None = None,
                                     require_vision: bool = False,
                                     require_tools: bool = False,
                                     require_json: bool = False,
                                     **kwargs) -> ChatResult:
        """
        智能升级聊天接口

        Args:
            message: 用户消息
            context: 对话上下文
            task_type: 任务类型
            strategy: 路由策略
            max_budget: 最大预算
            require_vision: 是否需要视觉支持
            require_tools: 是否需要工具支持
            require_json: 是否需要JSON输出

        Returns:
            ChatResult: 聊天结果
        """
        start_time = time.time()
        request_id = str(uuid.uuid4())[:8]

        try:
            # 1. 评估任务复杂度
            complexity = self.router.evaluate_task_complexity(message, context)

            # 2. 构建任务需求
            task_enum = self._parse_task_type(task_type)
            requirements = TaskRequirements(
                task_type=task_enum,
                complexity=complexity,
                require_vision=require_vision,
                require_tools=require_tools,
                require_json=require_json,
                max_budget=max_budget or 0.1,
                preferred_language="zh"
            )

            # 3. 检查预算
            can_request, budget_reason = self.cost_controller.can_make_request()
            if not can_request:
                logger.warning(f"[{request_id}] 预算限制: {budget_reason}")
                # 强制使用本地模型
                return await self._call_local_model(
                    message, context, request_id, start_time
                )

            # 4. 路由决策
            routing = self.router.route(
                requirements,
                strategy=strategy or self.default_strategy
            )

            logger.info(f"[{request_id}] 路由决策: {routing.full_name}, "
                       f"策略={routing.strategy.value}, 预估成本=${routing.estimated_cost:.4f}")

            # 5. 执行调用（带降级）
            result = await self._execute_with_fallback(
                routing=routing,
                task_type=task_type,
                message=message,
                context=context,
                request_id=request_id,
                **kwargs
            )

            # 6. 记录成本
            latency_ms = int((time.time() - start_time) * 1000)
            cost_record = CostRecord(
                provider=result.provider,
                model=result.model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                cost=result.cost,
                task_type=task_type,
                request_id=request_id
            )
            self.cost_controller.record_cost(cost_record)

            # 7. 更新统计
            self._update_stats(result, latency_ms)

            # 8. 记录路由性能
            self.router.record_performance(
                full_name=f"{result.provider}/{result.model}",
                success=result.success,
                latency_ms=latency_ms,
                tokens_used=result.input_tokens + result.output_tokens
            )

            return result

        except Exception as e:
            logger.error(f"[{request_id}] 调用失败: {e}")
            latency_ms = int((time.time() - start_time) * 1000)

            return ChatResult(
                content="",
                provider="",
                model="",
                cost=0.0,
                latency_ms=latency_ms,
                input_tokens=0,
                output_tokens=0,
                routing_info={},
                success=False,
                error=str(e)
            )

    async def _execute_with_fallback(self,
                                    routing: RoutingResult,
                                    task_type: str,
                                    message: str,
                                    context: list[dict] | None,
                                    request_id: str,
                                    **kwargs) -> ChatResult:
        """执行调用（带降级）"""
        provider = routing.provider
        model = routing.model
        last_error = None

        for attempt in range(3):
            try:
                # 获取provider实例
                provider_instance = AIProviderFactory.create_provider(provider, {})

                # 构建消息
                messages = self._build_messages(message, context)

                # 调用
                start_time = time.time()
                response = provider_instance.chat(
                    messages=messages,
                    model=model,
                    **kwargs
                )
                latency_ms = int((time.time() - start_time) * 1000)

                # 估算token
                input_tokens = sum(len(m["content"]) for m in messages) // 4
                output_tokens = len(response) // 4 if response else 0

                # 计算实际成本
                cost = self.cost_controller.calculate_cost(
                    model, provider, input_tokens, output_tokens
                )

                return ChatResult(
                    content=response or "",
                    provider=provider,
                    model=model,
                    cost=cost,
                    latency_ms=latency_ms,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    routing_info={
                        "strategy": routing.strategy.value,
                        "confidence": routing.confidence,
                        "estimated_cost": routing.estimated_cost,
                        "attempt": attempt + 1
                    },
                    success=True
                )

            except Exception as e:
                last_error = str(e)
                logger.warning(f"[{request_id}] 尝试 {attempt + 1} 失败: {last_error}")

                # 获取降级目标
                reason = self._determine_fallback_reason(last_error)
                next_fallback = self.fallback_manager.get_next_fallback(
                    task_type, provider, model, reason, last_error
                )

                if next_fallback is None:
                    logger.error(f"[{request_id}] 无可用降级目标")
                    break

                provider, model = next_fallback
                await asyncio.sleep(1)  # 等待后重试

        # 所有尝试失败，使用本地模型
        logger.warning(f"[{request_id}] 所有云端尝试失败，降级到本地模型")
        return await self._call_local_model(
            message, context, request_id, time.time()
        )

    async def _call_local_model(self,
                               message: str,
                               context: list[dict] | None,
                               request_id: str,
                               start_time: float) -> ChatResult:
        """调用本地模型"""
        try:
            provider = AIProviderFactory.create_provider("ollama", {})
            messages = self._build_messages(message, context)

            response = provider.chat(messages=messages, model="qwen3:8b")
            latency_ms = int((time.time() - start_time) * 1000)

            input_tokens = sum(len(m["content"]) for m in messages) // 4
            output_tokens = len(response) // 4 if response else 0

            return ChatResult(
                content=response or "",
                provider="ollama",
                model="qwen3:8b",
                cost=0.0,
                latency_ms=latency_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                routing_info={"fallback": True, "reason": "cloud_failure"},
                success=True
            )

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            return ChatResult(
                content="",
                provider="ollama",
                model="qwen3:8b",
                cost=0.0,
                latency_ms=latency_ms,
                input_tokens=0,
                output_tokens=0,
                routing_info={"error": True},
                success=False,
                error=str(e)
            )

    def _build_messages(self, message: str, context: list[dict] | None) -> list[dict]:
        """构建消息列表"""
        messages = []
        if context:
            for msg in context:
                messages.append({
                    "role": msg.get("role", "user"),
                    "content": msg.get("content", "")
                })
        messages.append({"role": "user", "content": message})
        return messages

    def _parse_task_type(self, task_type: str) -> TaskType:
        """解析任务类型"""
        task_map = {
            "chat": TaskType.CHAT,
            "code": TaskType.CODE,
            "analysis": TaskType.ANALYSIS,
            "planning": TaskType.PLANNING,
            "reasoning": TaskType.REASONING,
            "vision": TaskType.VISION,
            "creative": TaskType.CREATIVE,
            "summarize": TaskType.SUMMARIZE,
            "translate": TaskType.TRANSLATE,
        }
        return task_map.get(task_type, TaskType.CHAT)

    def _determine_fallback_reason(self, error_message: str) -> FallbackReason:
        """确定降级原因"""
        error_lower = error_message.lower()

        if any(kw in error_lower for kw in ["timeout", "timed out", "超时"]):
            return FallbackReason.TIMEOUT
        elif any(kw in error_lower for kw in ["rate limit", "429", "too many"]):
            return FallbackReason.RATE_LIMIT
        elif any(kw in error_lower for kw in ["network", "connection", "网络"]):
            return FallbackReason.NETWORK
        elif any(kw in error_lower for kw in ["cost", "budget", "quota", "余额"]):
            return FallbackReason.COST_LIMIT
        else:
            return FallbackReason.ERROR

    def _on_cost_alert(self, alert: CostAlert):
        """成本告警回调"""
        logger.warning(f"[Orchestrator] 成本告警: {alert.message}")

        for callback in self._cost_alert_callbacks:
            try:
                callback(alert)
            except Exception as e:
                logger.error(f"[Orchestrator] 成本告警回调出错: {e}")

    def add_cost_alert_callback(self, callback: Callable[[CostAlert], None]):
        """添加成本告警回调"""
        self._cost_alert_callbacks.append(callback)

    def _update_stats(self, result: ChatResult, latency_ms: int):
        """更新统计"""
        self._stats["total_requests"] += 1
        if result.success:
            self._stats["successful_requests"] += 1
        else:
            self._stats["failed_requests"] += 1
        self._stats["total_cost"] += result.cost
        self._stats["total_latency_ms"] += latency_ms

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息"""
        total = self._stats["total_requests"]
        return {
            **self._stats,
            "avg_latency_ms": self._stats["total_latency_ms"] / total if total > 0 else 0,
            "success_rate": self._stats["successful_requests"] / total if total > 0 else 0,
        }

    def get_cost_report(self, days: int = 30) -> dict[str, Any]:
        """获取成本报告"""
        return self.cost_controller.generate_report(days)

    def get_health_status(self) -> dict[str, Any]:
        """获取健康状态"""
        return {
            "fallback_manager": self.fallback_manager.get_health_report(),
            "router": self.router.get_routing_stats(),
            "stats": self.get_stats()
        }

    def get_optimization_suggestions(self) -> list[dict]:
        """获取优化建议"""
        return self.cost_controller.get_optimization_suggestions()
