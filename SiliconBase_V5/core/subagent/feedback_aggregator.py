#!/usr/bin/env python3
"""
SubAgentFeedbackAggregator - 子代理反馈聚合器

功能：
- 聚合多个子代理的实时反馈
- 提供统一的状态流
- 支持前端实时显示子代理进度
- 子代理结果汇总和冲突解决

作者: SiliconBase Team
版本: 1.0.0
"""

import threading
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.logger import logger
from core.subagent.runtime import SubAgentResult, SubAgentStatus


class SubAgentEventType(Enum):
    """子代理事件类型"""
    STARTED = "started"           # 子代理开始执行
    PROGRESS = "progress"         # 进度更新
    THINKING = "thinking"         # 思考过程
    TOOL_CALL = "tool_call"       # 工具调用
    TOOL_RESULT = "tool_result"   # 工具结果
    COMPLETED = "completed"       # 完成
    FAILED = "failed"             # 失败
    CANCELLED = "cancelled"       # 取消


@dataclass
class SubAgentEvent:
    """子代理事件"""
    event_id: str
    agent_name: str
    task_id: str
    event_type: SubAgentEventType
    timestamp: float
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            'event_id': self.event_id,
            'agent_name': self.agent_name,
            'task_id': self.task_id,
            'event_type': self.event_type.value,
            'timestamp': self.timestamp,
            'data': self.data
        }


@dataclass
class SubAgentTask:
    """子代理任务跟踪"""
    task_id: str
    agent_name: str
    description: str
    status: SubAgentStatus
    progress: float = 0.0
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None
    result: SubAgentResult | None = None
    events: list[SubAgentEvent] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            'task_id': self.task_id,
            'agent_name': self.agent_name,
            'description': self.description,
            'status': self.status.value if hasattr(self.status, 'value') else str(self.status),
            'progress': self.progress,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'result': self.result.to_dict() if self.result else None,
            'event_count': len(self.events),
            'metadata': self.metadata
        }


class SubAgentFeedbackAggregator:
    """
    子代理反馈聚合器

    单例模式，管理所有子代理的反馈流：
    1. 实时事件收集
    2. 状态聚合
    3. WebSocket 推送
    4. 结果汇总
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # 任务跟踪：task_id -> SubAgentTask
        self._tasks: dict[str, SubAgentTask] = {}

        # 父任务到子任务的映射：parent_task_id -> [task_ids]
        self._parent_child_map: dict[str, set[str]] = defaultdict(set)

        # WebSocket 回调列表
        self._websocket_callbacks: list[Callable[[str, dict], None]] = []

        # 事件历史（用于审计）
        self._event_history: list[SubAgentEvent] = []
        self._max_history_size = 1000

        # 锁
        self._tasks_lock = threading.RLock()

        logger.info("[SubAgentFeedbackAggregator] 子代理反馈聚合器初始化完成")

    def register_websocket_callback(self, callback: Callable[[str, dict], None]):
        """
        注册 WebSocket 推送回调

        Args:
            callback: 回调函数(event_type, data)
        """
        if callback not in self._websocket_callbacks:
            self._websocket_callbacks.append(callback)
            logger.debug(f"[FeedbackAggregator] 注册WebSocket回调，当前共{len(self._websocket_callbacks)}个")

    def unregister_websocket_callback(self, callback: Callable[[str, dict], None]):
        """注销 WebSocket 回调"""
        if callback in self._websocket_callbacks:
            self._websocket_callbacks.remove(callback)

    def _notify_websocket(self, event_type: str, data: dict):
        """通知所有 WebSocket 回调"""
        for callback in self._websocket_callbacks:
            try:
                callback(event_type, data)
            except Exception as e:
                logger.warning(f"[FeedbackAggregator] WebSocket回调失败: {e}")

    def start_task(self, task_id: str, agent_name: str, description: str,
                   parent_task_id: str = None, metadata: dict = None) -> SubAgentTask:
        """
        开始跟踪一个子代理任务

        Args:
            task_id: 任务ID
            agent_name: 代理名称
            description: 任务描述
            parent_task_id: 父任务ID（可选）
            metadata: 元数据（可选）

        Returns:
            SubAgentTask 对象
        """
        with self._tasks_lock:
            task = SubAgentTask(
                task_id=task_id,
                agent_name=agent_name,
                description=description,
                status=SubAgentStatus.RUNNING,
                metadata=metadata or {}
            )
            self._tasks[task_id] = task

            if parent_task_id:
                self._parent_child_map[parent_task_id].add(task_id)
                task.metadata['parent_task_id'] = parent_task_id

            # 创建开始事件
            event = SubAgentEvent(
                event_id=f"{task_id}_start",
                agent_name=agent_name,
                task_id=task_id,
                event_type=SubAgentEventType.STARTED,
                timestamp=time.time(),
                data={'description': description}
            )
            self._add_event(event)
            task.events.append(event)

            # WebSocket 通知
            self._notify_websocket('subagent_started', {
                'task_id': task_id,
                'agent_name': agent_name,
                'description': description,
                'parent_task_id': parent_task_id
            })

            logger.info(f"[FeedbackAggregator] 子代理任务开始: {agent_name} ({task_id})")
            return task

    def update_progress(self, task_id: str, progress: float, message: str = None):
        """
        更新任务进度

        Args:
            task_id: 任务ID
            progress: 进度（0-100）
            message: 进度消息（可选）
        """
        with self._tasks_lock:
            if task_id not in self._tasks:
                logger.warning(f"[FeedbackAggregator] 更新进度失败：未知任务 {task_id}")
                return

            task = self._tasks[task_id]
            task.progress = max(0, min(100, progress))

            event = SubAgentEvent(
                event_id=f"{task_id}_progress_{int(time.time()*1000)}",
                agent_name=task.agent_name,
                task_id=task_id,
                event_type=SubAgentEventType.PROGRESS,
                timestamp=time.time(),
                data={'progress': progress, 'message': message}
            )
            self._add_event(event)
            task.events.append(event)

            # WebSocket 通知
            self._notify_websocket('subagent_progress', {
                'task_id': task_id,
                'agent_name': task.agent_name,
                'progress': progress,
                'message': message
            })

    def add_thinking(self, task_id: str, thinking_content: str):
        """
        添加思考过程

        Args:
            task_id: 任务ID
            thinking_content: 思考内容
        """
        with self._tasks_lock:
            if task_id not in self._tasks:
                return

            task = self._tasks[task_id]

            event = SubAgentEvent(
                event_id=f"{task_id}_thinking_{int(time.time()*1000)}",
                agent_name=task.agent_name,
                task_id=task_id,
                event_type=SubAgentEventType.THINKING,
                timestamp=time.time(),
                data={'content': thinking_content[:500]}  # 限制长度
            )
            self._add_event(event)
            task.events.append(event)

            # WebSocket 通知
            self._notify_websocket('subagent_thinking', {
                'task_id': task_id,
                'agent_name': task.agent_name,
                'content': thinking_content[:200]  # 限制长度
            })

    def add_tool_call(self, task_id: str, tool_name: str, tool_params: dict):
        """
        添加工具调用记录

        Args:
            task_id: 任务ID
            tool_name: 工具名称
            tool_params: 工具参数
        """
        with self._tasks_lock:
            if task_id not in self._tasks:
                return

            task = self._tasks[task_id]

            event = SubAgentEvent(
                event_id=f"{task_id}_tool_{int(time.time()*1000)}",
                agent_name=task.agent_name,
                task_id=task_id,
                event_type=SubAgentEventType.TOOL_CALL,
                timestamp=time.time(),
                data={'tool_name': tool_name, 'params': tool_params}
            )
            self._add_event(event)
            task.events.append(event)

            # WebSocket 通知
            self._notify_websocket('subagent_tool_call', {
                'task_id': task_id,
                'agent_name': task.agent_name,
                'tool_name': tool_name
            })

    def complete_task(self, task_id: str, result: SubAgentResult):
        """
        完成任务

        Args:
            task_id: 任务ID
            result: 执行结果
        """
        with self._tasks_lock:
            if task_id not in self._tasks:
                return

            task = self._tasks[task_id]
            task.status = SubAgentStatus.COMPLETED if result.success else SubAgentStatus.FAILED
            task.progress = 100.0 if result.success else task.progress
            task.end_time = time.time()
            task.result = result

            event = SubAgentEvent(
                event_id=f"{task_id}_completed",
                agent_name=task.agent_name,
                task_id=task_id,
                event_type=SubAgentEventType.COMPLETED if result.success else SubAgentEventType.FAILED,
                timestamp=time.time(),
                data={
                    'success': result.success,
                    'output': result.output[:500] if result.output else None,
                    'error': result.error
                }
            )
            self._add_event(event)
            task.events.append(event)

            # WebSocket 通知
            self._notify_websocket('subagent_completed', {
                'task_id': task_id,
                'agent_name': task.agent_name,
                'success': result.success,
                'output_preview': result.output[:200] if result.output else None
            })

            logger.info(f"[FeedbackAggregator] 子代理任务完成: {task.agent_name} ({task_id}), 成功={result.success}")

    def cancel_task(self, task_id: str, reason: str = None):
        """
        取消任务

        Args:
            task_id: 任务ID
            reason: 取消原因
        """
        with self._tasks_lock:
            if task_id not in self._tasks:
                return

            task = self._tasks[task_id]
            task.status = SubAgentStatus.CANCELLED
            task.end_time = time.time()

            event = SubAgentEvent(
                event_id=f"{task_id}_cancelled",
                agent_name=task.agent_name,
                task_id=task_id,
                event_type=SubAgentEventType.CANCELLED,
                timestamp=time.time(),
                data={'reason': reason}
            )
            self._add_event(event)
            task.events.append(event)

            # WebSocket 通知
            self._notify_websocket('subagent_cancelled', {
                'task_id': task_id,
                'agent_name': task.agent_name,
                'reason': reason
            })

    def get_task(self, task_id: str) -> SubAgentTask | None:
        """获取任务信息"""
        with self._tasks_lock:
            return self._tasks.get(task_id)

    def get_parent_children(self, parent_task_id: str) -> list[SubAgentTask]:
        """获取父任务的所有子任务"""
        with self._tasks_lock:
            child_ids = self._parent_child_map.get(parent_task_id, set())
            return [self._tasks[tid] for tid in child_ids if tid in self._tasks]

    def get_active_tasks(self) -> list[SubAgentTask]:
        """获取所有活跃任务"""
        with self._tasks_lock:
            return [
                task for task in self._tasks.values()
                if task.status == SubAgentStatus.RUNNING
            ]

    def get_all_tasks_summary(self) -> dict[str, Any]:
        """获取所有任务摘要"""
        with self._tasks_lock:
            total = len(self._tasks)
            running = sum(1 for t in self._tasks.values() if t.status == SubAgentStatus.RUNNING)
            completed = sum(1 for t in self._tasks.values() if t.status == SubAgentStatus.COMPLETED)
            failed = sum(1 for t in self._tasks.values() if t.status == SubAgentStatus.FAILED)

            return {
                'total': total,
                'running': running,
                'completed': completed,
                'failed': failed,
                'tasks': [t.to_dict() for t in list(self._tasks.values())[-20:]]  # 最近20个
            }

    def _add_event(self, event: SubAgentEvent):
        """添加事件到历史"""
        self._event_history.append(event)
        # 限制历史大小
        if len(self._event_history) > self._max_history_size:
            self._event_history = self._event_history[-self._max_history_size:]

    def get_recent_events(self, limit: int = 50) -> list[dict]:
        """获取最近事件"""
        return [e.to_dict() for e in self._event_history[-limit:]]

    def clear_completed_tasks(self, max_age: float = 3600):
        """
        清理已完成的任务

        Args:
            max_age: 最大保留时间（秒）
        """
        with self._tasks_lock:
            current_time = time.time()
            to_remove = [
                tid for tid, task in self._tasks.items()
                if task.status in [SubAgentStatus.COMPLETED, SubAgentStatus.FAILED, SubAgentStatus.CANCELLED]
                and task.end_time
                and (current_time - task.end_time) > max_age
            ]
            for tid in to_remove:
                del self._tasks[tid]

            if to_remove:
                logger.info(f"[FeedbackAggregator] 清理{len(to_remove)}个已完成任务")


# 便捷函数
def get_feedback_aggregator() -> SubAgentFeedbackAggregator:
    """获取反馈聚合器实例"""
    return SubAgentFeedbackAggregator()


def register_subagent_websocket(ws_callback: Callable[[str, dict], None]):
    """注册子代理WebSocket回调"""
    aggregator = get_feedback_aggregator()
    aggregator.register_websocket_callback(ws_callback)


def unregister_subagent_websocket(ws_callback: Callable[[str, dict], None]):
    """注销子代理WebSocket回调"""
    aggregator = get_feedback_aggregator()
    aggregator.unregister_websocket_callback(ws_callback)
