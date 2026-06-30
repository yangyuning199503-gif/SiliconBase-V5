#!/usr/bin/env python3
"""
Agent 运行时管理
【Week 5-8 架构重构】

职责: 管理单个Agent任务的运行时状态
- 状态追踪 (pending/running/paused/completed/failed)
- 生命周期管理
- 资源统计

不处理: 干预逻辑、持久化（由编排层处理）
"""

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.logger import logger


class RuntimeStatus(Enum):
    """运行时状态"""
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class RuntimeMetrics:
    """运行时指标"""
    start_time: float | None = None
    end_time: float | None = None
    paused_duration: float = 0.0
    round_count: int = 0
    token_usage: dict[str, int] = field(default_factory=dict)
    tool_calls: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def execution_time(self) -> float:
        """执行耗时"""
        if self.start_time is None:
            return 0.0
        end = self.end_time or time.time()
        return end - self.start_time - self.paused_duration


class AgentRuntime:
    """
    Agent 运行时

    管理单个任务的完整生命周期，提供状态追踪和钩子机制。
    """

    def __init__(
        self,
        task_id: str | None = None,
        task_description: str = "",
        user_id: str | None = None,
        config: dict[str, Any] | None = None
    ):
        self.runtime_id = task_id or f"rt_{uuid.uuid4().hex[:12]}"
        self.task_description = task_description
        self.user_id = user_id
        self.config = config or {}

        # 状态
        self._status = RuntimeStatus.PENDING
        self._status_history: list[dict[str, Any]] = []

        # 指标
        self.metrics = RuntimeMetrics()

        # 上下文
        self.context: dict[str, Any] = {}
        self.working_memory: list[dict] = []

        # 状态变更监听器
        self._status_listeners: list[Callable[[RuntimeStatus, RuntimeStatus], None]] = []

        # 暂停相关
        self._pause_start: float | None = None
        self._resume_event: Any | None = None

        # 长任务状态机引用（外部注入）
        self._pausable_task_sm: Any | None = None

        logger.debug(f"[AgentRuntime] 创建运行时: {self.runtime_id}")

    @property
    def status(self) -> RuntimeStatus:
        """获取当前状态"""
        return self._status

    @status.setter
    def status(self, new_status: RuntimeStatus):
        """设置状态（自动记录历史）"""
        if new_status != self._status:
            old_status = self._status
            self._status = new_status

            # 记录历史
            self._status_history.append({
                "from": old_status.value,
                "to": new_status.value,
                "timestamp": time.time()
            })

            # 触发监听器
            for listener in self._status_listeners:
                try:
                    listener(old_status, new_status)
                except Exception as e:
                    logger.error(f"[AgentRuntime] 状态监听器错误: {e}")

            logger.info(f"[AgentRuntime] {self.runtime_id} 状态变更: {old_status.value} -> {new_status.value}")

    def register_status_listener(self, listener: Callable[[RuntimeStatus, RuntimeStatus], None]):
        """注册状态变更监听器"""
        self._status_listeners.append(listener)

    def start(self):
        """开始执行"""
        self.status = RuntimeStatus.RUNNING
        self.metrics.start_time = time.time()
        logger.info(f"[AgentRuntime] {self.runtime_id} 开始执行")

    def pause(self) -> bool:
        """
        暂停执行

        Returns:
            是否成功暂停
        """
        if self._status == RuntimeStatus.RUNNING:
            self.status = RuntimeStatus.PAUSED
            self._pause_start = time.time()
            # 通知长任务状态机真正停下来
            if self._pausable_task_sm and hasattr(self._pausable_task_sm, 'request_pause'):
                try:
                    self._pausable_task_sm.request_pause()
                except Exception as e:
                    logger.warning(f"[AgentRuntime] 通知状态机暂停失败: {e}")
            logger.info(f"[AgentRuntime] {self.runtime_id} 已暂停")
            return True
        return False

    def resume(self) -> bool:
        """
        恢复执行

        Returns:
            是否成功恢复
        """
        if self._status == RuntimeStatus.PAUSED:
            if self._pause_start:
                self.metrics.paused_duration += time.time() - self._pause_start
                self._pause_start = None
            self.status = RuntimeStatus.RUNNING
            # 通知长任务状态机恢复
            if self._pausable_task_sm and hasattr(self._pausable_task_sm, 'resume'):
                try:
                    self._pausable_task_sm.resume()
                except Exception as e:
                    logger.warning(f"[AgentRuntime] 通知状态机恢复失败: {e}")
            logger.info(f"[AgentRuntime] {self.runtime_id} 已恢复")
            return True
        return False

    def complete(self, output: str):
        """完成执行"""
        self.status = RuntimeStatus.COMPLETED
        self.metrics.end_time = time.time()
        self.context['final_output'] = output
        logger.info(f"[AgentRuntime] {self.runtime_id} 执行完成")

    def fail(self, error: str):
        """执行失败"""
        self.status = RuntimeStatus.FAILED
        self.metrics.end_time = time.time()
        self.metrics.errors.append(error)
        self.context['error'] = error
        logger.error(f"[AgentRuntime] {self.runtime_id} 执行失败: {error}")

    def cancel(self):
        """取消执行"""
        self.status = RuntimeStatus.CANCELLED
        self.metrics.end_time = time.time()
        logger.info(f"[AgentRuntime] {self.runtime_id} 已取消")

    def increment_round(self):
        """增加轮次计数"""
        self.metrics.round_count += 1

    def record_tool_call(self, tool_name: str, success: bool):
        """记录工具调用"""
        self.metrics.tool_calls += 1
        if not success:
            self.metrics.errors.append(f"工具调用失败: {tool_name}")

    def add_token_usage(self, model: str, tokens: int):
        """记录Token使用"""
        if model not in self.metrics.token_usage:
            self.metrics.token_usage[model] = 0
        self.metrics.token_usage[model] += tokens

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典"""
        return {
            "runtime_id": self.runtime_id,
            "task_description": self.task_description,
            "user_id": self.user_id,
            "status": self._status.value,
            "status_history": self._status_history,
            "metrics": {
                "start_time": self.metrics.start_time,
                "end_time": self.metrics.end_time,
                "execution_time": self.metrics.execution_time,
                "paused_duration": self.metrics.paused_duration,
                "round_count": self.metrics.round_count,
                "token_usage": self.metrics.token_usage,
                "tool_calls": self.metrics.tool_calls,
                "errors": self.metrics.errors
            },
            "context": {k: v for k, v in self.context.items() if isinstance(v, (str, int, float, bool, list, dict))}
        }

    def is_active(self) -> bool:
        """是否处于活跃状态"""
        return self._status in (RuntimeStatus.PENDING, RuntimeStatus.RUNNING, RuntimeStatus.PAUSED)

    def can_intervene(self) -> bool:
        """是否可以干预"""
        return self._status == RuntimeStatus.RUNNING


class RuntimeManager:
    """
    运行时管理器（单例）

    管理所有活跃的Agent运行时
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

        self._runtimes: dict[str, AgentRuntime] = {}
        logger.info("[RuntimeManager] 运行时管理器初始化")

    def create_runtime(
        self,
        task_description: str = "",
        user_id: str | None = None,
        config: dict[str, Any] | None = None
    ) -> AgentRuntime:
        """创建新运行时"""
        runtime = AgentRuntime(
            task_description=task_description,
            user_id=user_id,
            config=config
        )
        self._runtimes[runtime.runtime_id] = runtime
        return runtime

    def get_runtime(self, runtime_id: str) -> AgentRuntime | None:
        """获取运行时"""
        return self._runtimes.get(runtime_id)

    def remove_runtime(self, runtime_id: str) -> bool:
        """移除运行时"""
        if runtime_id in self._runtimes:
            del self._runtimes[runtime_id]
            return True
        return False

    def get_active_runtimes(self) -> list[AgentRuntime]:
        """获取所有活跃运行时"""
        return [r for r in self._runtimes.values() if r.is_active()]

    def get_user_runtimes(self, user_id: str) -> list[AgentRuntime]:
        """获取用户的所有运行时"""
        return [r for r in self._runtimes.values() if r.user_id == user_id]

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息"""
        total = len(self._runtimes)
        active = len(self.get_active_runtimes())
        by_status = {}
        for runtime in self._runtimes.values():
            status = runtime.status.value
            by_status[status] = by_status.get(status, 0) + 1

        return {
            "total_runtimes": total,
            "active_runtimes": active,
            "by_status": by_status
        }


# 全局实例
runtime_manager = RuntimeManager()
