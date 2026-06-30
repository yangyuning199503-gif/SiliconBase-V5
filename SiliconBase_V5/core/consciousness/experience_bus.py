#!/usr/bin/env python3
"""
ExperienceBus - 统一经验总线

设计目标：
- 所有模块的经验事件统一格式、统一汇聚
- 支持事件驱动（实时publish）和轮询（定期flush）双模式
- 缓冲区 maxlen=2000，防止内存爆炸
- 异步安全，不阻塞任何模块

使用方式：
    bus = ExperienceBus()
    bus.subscribe(my_handler)
    await bus.publish(ExperienceEvent(source="tool", event_type="executed", ...))
"""

import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, cast

from core.diagnostic import safe_create_task as _safe_create_task  # type: ignore
from core.logger import logger as _logger

logger: logging.Logger = cast(logging.Logger, _logger)


def _empty_dict() -> dict[str, Any]:
    return {}


@dataclass
class ExperienceEvent:
    """
    统一经验事件格式。

    所有模块的经验数据都必须转换成这个格式才能进入总线。
    """
    source: str              # 模块名：tool / rlhf / sensor / memory / evolution / reflect / trade / agent / voice / safety / consciousness
    event_type: str          # 事件类型：executed / feedback / perception / accessed / learned / reflected / traded / thought
    timestamp: float = field(default_factory=time.time)
    context: dict[str, Any] = field(default_factory=_empty_dict)   # 产生时的上下文（动机、视觉、目标等）
    action: str = ""         # 行动描述（工具ID、用户输入、思考方向等）
    outcome: float = 0.5     # 结果评分（0~1，1.0极好，0.0极差，0.5中性）
    weight: float = 1.0      # 该事件在融合时的权重
    raw_data: dict[str, Any] = field(default_factory=_empty_dict)  # 原始数据（适配器解析用）


# 经验事件订阅者类型
class ExperienceHandler(Protocol):
    def __call__(self, event: ExperienceEvent) -> Any:
        ...


safe_create_task = cast(Callable[..., Any], _safe_create_task)


class ExperienceBus:
    """
    经验事件总线。

    - publish: 任何模块都可以异步发布经验事件
    - subscribe: 消费者可以订阅事件（如 FeedbackCollector）
    - get_recent: 按时间段/来源查询历史事件
    - flush_to_collector: 批量把事件推给 FeedbackCollector
    """

    def __init__(self, max_buffer: int = 2000):
        self._events: deque[ExperienceEvent] = deque(maxlen=max_buffer)
        self._handlers: list[ExperienceHandler] = []
        self._lock = asyncio.Lock()
        self._publish_count = 0
        self._drop_count = 0

    async def publish(self, event: ExperienceEvent) -> bool:
        """
        发布一个经验事件。

        Args:
            event: 经验事件

        Returns:
            bool: 是否成功加入缓冲区（False表示缓冲区已满被丢弃）
        """
        try:
            # 校验 outcome 范围
            event.outcome = max(0.0, min(1.0, float(event.outcome)))

            async with self._lock:
                before_len = len(self._events)
                self._events.append(event)
                after_len = len(self._events)

                maxlen = self._events.maxlen
                if after_len == before_len and maxlen is not None and before_len >= maxlen:
                    self._drop_count += 1
                    return False

                self._publish_count += 1

            # 异步通知所有订阅者（不阻塞发布方）
            for handler in self._handlers:
                safe_create_task(self._safe_notify(handler, event), name="_safe_notify")

            return True
        except Exception as e:
            logger.debug(f"[ExperienceBus] publish异常: {e}")
            return False

    async def _safe_notify(self, handler: ExperienceHandler, event: ExperienceEvent):
        """安全调用订阅者，异常不传播"""
        try:
            if asyncio.iscoroutinefunction(handler):
                await handler(event)
            else:
                handler(event)
        except Exception as e:
            logger.debug(f"[ExperienceBus] handler异常: {e}")

    def subscribe(self, handler: ExperienceHandler):
        """订阅经验事件"""
        self._handlers.append(handler)

    def unsubscribe(self, handler: ExperienceHandler):
        """取消订阅"""
        if handler in self._handlers:
            self._handlers.remove(handler)

    def get_recent(
        self,
        seconds: float = 300,
        source: str | None = None,
        event_type: str | None = None,
        limit: int = 100
    ) -> list[ExperienceEvent]:
        """
        获取最近的经验事件。

        Args:
            seconds: 时间窗口（秒）
            source: 过滤来源模块（None表示不过滤）
            event_type: 过滤事件类型（None表示不过滤）
            limit: 最大返回数量
        """
        cutoff = time.time() - seconds
        results: list[ExperienceEvent] = []

        # 从后往前遍历（最新的在前面）
        for event in reversed(self._events):
            if event.timestamp < cutoff:
                break
            if source and event.source != source:
                continue
            if event_type and event.event_type != event_type:
                continue
            results.append(event)
            if len(results) >= limit:
                break

        return list(reversed(results))  # 恢复时间顺序

    def get_stats(self) -> dict[str, Any]:
        """返回总线统计信息"""
        sources: dict[str, int] = {}
        for e in self._events:
            sources[e.source] = sources.get(e.source, 0) + 1

        return {
            "buffer_size": len(self._events),
            "buffer_max": self._events.maxlen,
            "publish_count": self._publish_count,
            "drop_count": self._drop_count,
            "handler_count": len(self._handlers),
            "source_distribution": sources,
        }

    def clear_old(self, max_age_seconds: float = 3600):
        """清理过期事件（通常不需要手动调用，deque自动管理）"""
        # deque不支持中间删除，这里只是做个标记，实际由maxlen控制
        _ = max_age_seconds  # 保留参数供未来实现
        pass

    async def flush_to_collector(
        self,
        collector: Any,
        context: dict[str, Any],
        seconds: float = 60,
        min_outcome_delta: float = 0.1
    ) -> list[ExperienceEvent]:
        """
        把最近的经验事件flush给 FeedbackCollector。

        Args:
            collector: FeedbackCollector 实例
            context: 当前状态上下文
            seconds: 时间窗口
            min_outcome_delta: 只有当outcome差异>此值时才认为有价值

        Returns:
            被flush的事件列表
        """
        events = self.get_recent(seconds=seconds)
        if not events:
            return []

        # 按source分组，取每个source的加权平均outcome
        source_outcomes: dict[str, float] = {}
        source_weights: dict[str, float] = {}
        for e in events:
            src = e.source
            if src not in source_outcomes:
                source_outcomes[src] = 0.0
                source_weights[src] = 0.0
            source_outcomes[src] += e.outcome * e.weight
            source_weights[src] += e.weight

        # 计算各source的加权平均
        for src in source_outcomes:
            if source_weights[src] > 0:
                source_outcomes[src] /= source_weights[src]

        # 根据source类型记录到collector的不同维度
        for src, avg_outcome in source_outcomes.items():
            if src == "tool":
                collector._tool_outcome = avg_outcome
            elif src == "rlhf":
                collector._rlhf_outcome = avg_outcome
            elif src == "sensor":
                collector._sensor_outcome = avg_outcome
            elif src == "memory":
                collector._memory_outcome = avg_outcome
            elif src in ("evolution", "reflect"):
                collector._learning_outcome = avg_outcome
            elif src == "trade":
                collector._trade_outcome = avg_outcome

        return events


# ============================================================================
# 全局单例
# ============================================================================

_experience_bus_instance: ExperienceBus | None = None


def get_experience_bus(max_buffer: int = 2000) -> ExperienceBus:
    """获取全局 ExperienceBus 单例"""
    global _experience_bus_instance
    if _experience_bus_instance is None:
        _experience_bus_instance = ExperienceBus(max_buffer=max_buffer)
    return _experience_bus_instance
