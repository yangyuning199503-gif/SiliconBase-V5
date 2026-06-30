#!/usr/bin/env python3
"""
统一干预协调器
【Week 5-8 架构重构】

职责: 统一处理所有干预逻辑
- 父代理干预
- 子代理干预
- 智能干预建议的执行
- 干预历史记录

不再分散在 agent_loop.py 的各个地方
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.logger import logger


class InterventionType(Enum):
    """干预类型"""
    PAUSE = "PAUSE"           # 暂停
    RESUME = "RESUME"         # 恢复
    CANCEL = "CANCEL"         # 取消
    ADJUST = "ADJUST"         # 调整
    REPLAN = "REPLAN"         # 重新规划
    SKIP = "SKIP"             # 跳过
    CONTINUE = "CONTINUE"     # 继续


class InterventionTarget(Enum):
    """干预目标"""
    PARENT = "parent"         # 父代理
    SUBAGENT = "subagent"     # 子代理
    PIPELINE = "pipeline"     # 流水线


@dataclass
class InterventionContext:
    """干预上下文"""
    intervention_type: InterventionType
    target_type: InterventionTarget
    target_id: str
    source: str                    # 来源: user, system, smart_detector
    reason: str
    user_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class InterventionResult:
    """干预结果"""
    success: bool
    message: str
    new_status: str | None = None
    error: str | None = None


class InterventionHandler:
    """干预处理器接口"""

    def can_handle(self, context: InterventionContext) -> bool:
        """是否能处理此干预"""
        raise NotImplementedError

    async def apply(self, context: InterventionContext) -> InterventionResult:
        """执行干预"""
        raise NotImplementedError


class PauseHandler(InterventionHandler):
    """暂停处理器"""

    def can_handle(self, context: InterventionContext) -> bool:
        return context.intervention_type == InterventionType.PAUSE

    async def apply(self, context: InterventionContext) -> InterventionResult:
        try:
            from core.execution.agent_runtime import runtime_manager
            runtime = runtime_manager.get_runtime(context.target_id)

            if runtime and runtime.pause():
                return InterventionResult(
                    success=True,
                    message=f"已暂停运行时: {context.target_id}",
                    new_status="paused"
                )
            else:
                return InterventionResult(
                    success=False,
                    message="无法暂停（可能不在运行状态）",
                    error="Runtime not running"
                )
        except Exception as e:
            return InterventionResult(
                success=False,
                message="暂停失败",
                error=str(e)
            )


class ResumeHandler(InterventionHandler):
    """恢复处理器"""

    def can_handle(self, context: InterventionContext) -> bool:
        return context.intervention_type == InterventionType.RESUME

    async def apply(self, context: InterventionContext) -> InterventionResult:
        try:
            from core.execution.agent_runtime import runtime_manager
            runtime = runtime_manager.get_runtime(context.target_id)

            if runtime and runtime.resume():
                return InterventionResult(
                    success=True,
                    message=f"已恢复运行时: {context.target_id}",
                    new_status="running"
                )
            else:
                return InterventionResult(
                    success=False,
                    message="无法恢复（可能不在暂停状态）",
                    error="Runtime not paused"
                )
        except Exception as e:
            return InterventionResult(
                success=False,
                message="恢复失败",
                error=str(e)
            )


class CancelHandler(InterventionHandler):
    """取消处理器"""

    def can_handle(self, context: InterventionContext) -> bool:
        return context.intervention_type == InterventionType.CANCEL

    async def apply(self, context: InterventionContext) -> InterventionResult:
        try:
            from core.execution.agent_runtime import runtime_manager
            from core.subagent.manager import subagent_manager

            # 尝试作为运行时取消
            runtime = runtime_manager.get_runtime(context.target_id)
            if runtime:
                runtime.cancel()
                return InterventionResult(
                    success=True,
                    message=f"已取消运行时: {context.target_id}",
                    new_status="cancelled"
                )

            # 尝试作为子代理取消
            if subagent_manager.cancel_runtime(context.target_id):
                return InterventionResult(
                    success=True,
                    message=f"已取消子代理: {context.target_id}",
                    new_status="cancelled"
                )

            return InterventionResult(
                success=False,
                message="找不到目标",
                error="Target not found"
            )
        except Exception as e:
            return InterventionResult(
                success=False,
                message="取消失败",
                error=str(e)
            )


class InterventionCoordinator:
    """
    统一干预协调器

    单例模式，集中管理所有干预逻辑
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # 注册处理器
        self._handlers: list[InterventionHandler] = [
            PauseHandler(),
            ResumeHandler(),
            CancelHandler(),
        ]

        # 干预历史
        self._history: list[dict[str, Any]] = []
        self._max_history = 1000

        # 监听器
        self._listeners: list[Callable[[InterventionContext, InterventionResult], None]] = []

        logger.info("[InterventionCoordinator] 干预协调器初始化")

    def register_handler(self, handler: InterventionHandler):
        """注册处理器"""
        self._handlers.append(handler)

    def register_listener(self, listener: Callable[[InterventionContext, InterventionResult], None]):
        """注册干预监听器"""
        self._listeners.append(listener)

    async def intervene(self, context: InterventionContext) -> InterventionResult:
        """
        执行干预

        Args:
            context: 干预上下文

        Returns:
            InterventionResult: 干预结果
        """
        logger.info(f"[InterventionCoordinator] 干预请求: {context.intervention_type.value} -> {context.target_id}")

        # 查找处理器
        handler = None
        for h in self._handlers:
            if h.can_handle(context):
                handler = h
                break

        if not handler:
            result = InterventionResult(
                success=False,
                message=f"未找到处理器: {context.intervention_type.value}",
                error="Handler not found"
            )
        else:
            # 执行干预
            result = await handler.apply(context)

        # 记录历史
        self._record_history(context, result)

        # 通知监听器
        for listener in self._listeners:
            try:
                listener(context, result)
            except Exception as e:
                logger.error(f"[InterventionCoordinator] 监听器错误: {e}")

        return result

    def _record_history(self, context: InterventionContext, result: InterventionResult):
        """记录干预历史"""
        record = {
            "timestamp": time.time(),
            "type": context.intervention_type.value,
            "target": context.target_id,
            "source": context.source,
            "reason": context.reason,
            "success": result.success,
            "message": result.message
        }

        self._history.append(record)

        # 限制历史大小
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

    def get_history(
        self,
        target_id: str | None = None,
        limit: int = 100
    ) -> list[dict[str, Any]]:
        """获取干预历史"""
        history = self._history

        if target_id:
            history = [h for h in history if h.get("target") == target_id]

        return history[-limit:]

    def get_stats(self) -> dict[str, Any]:
        """获取统计"""
        total = len(self._history)
        successful = sum(1 for h in self._history if h.get("success"))

        by_type = {}
        for h in self._history:
            t = h.get("type", "unknown")
            by_type[t] = by_type.get(t, 0) + 1

        return {
            "total_interventions": total,
            "successful": successful,
            "failed": total - successful,
            "by_type": by_type
        }


# 便捷函数
async def intervene(
    intervention_type: InterventionType,
    target_id: str,
    reason: str,
    source: str = "user",
    user_id: str | None = None,
    metadata: dict[str, Any] | None = None
) -> InterventionResult:
    """
    便捷干预函数

    Example:
        result = await intervene(
            InterventionType.PAUSE,
            target_id="rt_abc123",
            reason="用户需要检查进度"
        )
    """
    coordinator = InterventionCoordinator()

    context = InterventionContext(
        intervention_type=intervention_type,
        target_type=InterventionTarget.SUBAGENT,
        target_id=target_id,
        source=source,
        reason=reason,
        user_id=user_id,
        metadata=metadata or {}
    )

    return await coordinator.intervene(context)


# 全局实例
intervention_coordinator = InterventionCoordinator()
