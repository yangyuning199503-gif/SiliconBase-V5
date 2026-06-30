#!/usr/bin/env python3
"""
Workflow Events - 工作流事件系统 V1.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
提供工作流执行过程中的各类事件定义

【事件类型】
- 工作流级别: WorkflowStarted, WorkflowCompleted, WorkflowFailed
- 步骤级别: StepStarted, StepCompleted, StepFailed
- 用户干预: WorkflowPaused, WorkflowResumed, WorkflowModified

【核心特性】
1. 统一的事件基类
2. 支持事件序列化
3. 支持时间戳和元数据
4. 与 CheckpointManager 集成

【架构位置】
- 位于: core/workflow/events.py
- 调用方: WorkflowExecutor, WorkflowStateMachine
"""

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# 导入项目组件
try:
    from core.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger('workflow_events')


# ═══════════════════════════════════════════════════════════════════════════════
# 事件类型枚举
# ═══════════════════════════════════════════════════════════════════════════════

class EventType(Enum):
    """事件类型枚举"""
    # 工作流级别事件
    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"
    WORKFLOW_CANCELLED = "workflow_cancelled"

    # 步骤级别事件
    STEP_STARTED = "step_started"
    STEP_PROGRESS = "step_progress"  # 【新增】步骤进度事件
    STEP_COMPLETED = "step_completed"
    STEP_FAILED = "step_failed"
    STEP_SKIPPED = "step_skipped"
    STEP_RETRY = "step_retry"

    # 用户干预事件
    WORKFLOW_PAUSED = "workflow_paused"
    WORKFLOW_RESUMED = "workflow_resumed"
    WORKFLOW_MODIFIED = "workflow_modified"

    # 状态变更事件
    STATE_CHANGED = "state_changed"
    CHECKPOINT_SAVED = "checkpoint_saved"


class EventPriority(Enum):
    """事件优先级枚举"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


# ═══════════════════════════════════════════════════════════════════════════════
# 事件基类
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class WorkflowEvent:
    """工作流事件基类"""
    event_id: str = field(default_factory=lambda: f"evt_{uuid.uuid4().hex[:12]}")
    event_type: EventType = EventType.STATE_CHANGED
    timestamp: float = field(default_factory=time.time)
    execution_id: str | None = None
    workflow_id: str | None = None
    user_id: str = "default"
    priority: EventPriority = EventPriority.NORMAL
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp,
            "execution_id": self.execution_id,
            "workflow_id": self.workflow_id,
            "user_id": self.user_id,
            "priority": self.priority.value,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'WorkflowEvent':
        """从字典创建实例"""
        event = cls()
        event.event_id = data.get("event_id", event.event_id)
        event.event_type = EventType(data.get("event_type", "state_changed"))
        event.timestamp = data.get("timestamp", time.time())
        event.execution_id = data.get("execution_id")
        event.workflow_id = data.get("workflow_id")
        event.user_id = data.get("user_id", "default")
        event.priority = EventPriority(data.get("priority", 2))
        event.metadata = data.get("metadata", {})
        return event

    def __str__(self) -> str:
        return f"[{self.event_type.value}] {self.event_id} @ {self.timestamp}"


# ═══════════════════════════════════════════════════════════════════════════════
# 工作流级别事件
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class WorkflowStarted(WorkflowEvent):
    """工作流开始事件"""
    step_count: int = 0
    initial_variables: dict[str, Any] = field(default_factory=dict)

    def __init__(self, execution_id: str, workflow_id: str, user_id: str = "default",
                 step_count: int = 0, initial_variables: dict[str, Any] | None = None,
                 **kwargs):
        super().__init__(
            event_type=EventType.WORKFLOW_STARTED,
            execution_id=execution_id,
            workflow_id=workflow_id,
            user_id=user_id,
            priority=EventPriority.HIGH
        )
        self.step_count = step_count
        self.initial_variables = initial_variables or {}
        self.metadata.update({
            "step_count": step_count,
            "initial_variables": self.initial_variables
        })

    def to_dict(self) -> dict[str, Any]:
        base = super().to_dict()
        base.update({
            "step_count": self.step_count,
            "initial_variables": self.initial_variables
        })
        return base


@dataclass
class WorkflowCompleted(WorkflowEvent):
    """工作流完成事件"""
    total_steps: int = 0
    completed_steps: int = 0
    execution_time: float = 0.0
    final_variables: dict[str, Any] = field(default_factory=dict)

    def __init__(self, execution_id: str, workflow_id: str,
                 total_steps: int = 0, completed_steps: int = 0,
                 execution_time: float = 0.0,
                 final_variables: dict[str, Any] | None = None,
                 user_id: str = "default", **kwargs):
        super().__init__(
            event_type=EventType.WORKFLOW_COMPLETED,
            execution_id=execution_id,
            workflow_id=workflow_id,
            user_id=user_id,
            priority=EventPriority.HIGH
        )
        self.total_steps = total_steps
        self.completed_steps = completed_steps
        self.execution_time = execution_time
        self.final_variables = final_variables or {}
        self.metadata.update({
            "total_steps": total_steps,
            "completed_steps": completed_steps,
            "execution_time": execution_time,
            "final_variables": self.final_variables
        })

    def to_dict(self) -> dict[str, Any]:
        base = super().to_dict()
        base.update({
            "total_steps": self.total_steps,
            "completed_steps": self.completed_steps,
            "execution_time": self.execution_time,
            "final_variables": self.final_variables
        })
        return base


@dataclass
class WorkflowFailed(WorkflowEvent):
    """工作流失败事件"""
    error: str = ""
    step_id: str | None = None
    failure_stage: str = ""  # 失败阶段: preparation/execution/verification

    def __init__(self, execution_id: str, error: str,
                 workflow_id: str | None = None,
                 step_id: str | None = None,
                 failure_stage: str = "execution",
                 user_id: str = "default", **kwargs):
        super().__init__(
            event_type=EventType.WORKFLOW_FAILED,
            execution_id=execution_id,
            workflow_id=workflow_id,
            user_id=user_id,
            priority=EventPriority.CRITICAL
        )
        self.error = error
        self.step_id = step_id
        self.failure_stage = failure_stage
        self.metadata.update({
            "error": error,
            "step_id": step_id,
            "failure_stage": failure_stage
        })

    def to_dict(self) -> dict[str, Any]:
        base = super().to_dict()
        base.update({
            "error": self.error,
            "step_id": self.step_id,
            "failure_stage": self.failure_stage
        })
        return base


@dataclass
class WorkflowCancelled(WorkflowEvent):
    """工作流取消事件"""
    cancelled_at_step: int | None = None
    reason: str = ""

    def __init__(self, execution_id: str,
                 workflow_id: str | None = None,
                 cancelled_at_step: int | None = None,
                 reason: str = "",
                 user_id: str = "default", **kwargs):
        super().__init__(
            event_type=EventType.WORKFLOW_CANCELLED,
            execution_id=execution_id,
            workflow_id=workflow_id,
            user_id=user_id,
            priority=EventPriority.HIGH
        )
        self.cancelled_at_step = cancelled_at_step
        self.reason = reason
        self.metadata.update({
            "cancelled_at_step": cancelled_at_step,
            "reason": reason
        })

    def to_dict(self) -> dict[str, Any]:
        base = super().to_dict()
        base.update({
            "cancelled_at_step": self.cancelled_at_step,
            "reason": self.reason
        })
        return base


# ═══════════════════════════════════════════════════════════════════════════════
# 步骤级别事件
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class StepStarted(WorkflowEvent):
    """步骤开始事件"""
    step_id: str = ""
    step_name: str = ""
    step_category: str = ""
    step_index: int = 0
    total_steps: int = 0

    def __init__(self, execution_id: str, step_id: str,
                 step_name: str = "", step_category: str = "",
                 step_index: int = 0, total_steps: int = 0,
                 workflow_id: str | None = None,
                 user_id: str = "default", **kwargs):
        super().__init__(
            event_type=EventType.STEP_STARTED,
            execution_id=execution_id,
            workflow_id=workflow_id,
            user_id=user_id,
            priority=EventPriority.NORMAL
        )
        self.step_id = step_id
        self.step_name = step_name
        self.step_category = step_category
        self.step_index = step_index
        self.total_steps = total_steps
        self.metadata.update({
            "step_id": step_id,
            "step_name": step_name,
            "step_category": step_category,
            "step_index": step_index,
            "total_steps": total_steps
        })

    def to_dict(self) -> dict[str, Any]:
        base = super().to_dict()
        base.update({
            "step_id": self.step_id,
            "step_name": self.step_name,
            "step_category": self.step_category,
            "step_index": self.step_index,
            "total_steps": self.total_steps
        })
        return base


@dataclass
class StepProgress(WorkflowEvent):
    """步骤进度事件 - 用于实时进度推送"""
    step_id: str = ""
    step_name: str = ""
    step_index: int = 0
    total_steps: int = 0
    progress_percent: float = 0.0  # 当前步骤进度（0-100）
    overall_percent: float = 0.0   # 整体进度（0-100）
    status: str = "running"        # running/paused/completed/failed
    message: str = ""              # 进度消息

    def __init__(self, execution_id: str, step_id: str,
                 step_name: str = "", step_index: int = 0, total_steps: int = 0,
                 progress_percent: float = 0.0, overall_percent: float = 0.0,
                 status: str = "running", message: str = "",
                 workflow_id: str | None = None,
                 user_id: str = "default", **kwargs):
        super().__init__(
            event_type=EventType.STEP_PROGRESS,
            execution_id=execution_id,
            workflow_id=workflow_id,
            user_id=user_id,
            priority=EventPriority.NORMAL
        )
        self.step_id = step_id
        self.step_name = step_name
        self.step_index = step_index
        self.total_steps = total_steps
        self.progress_percent = progress_percent
        self.overall_percent = overall_percent
        self.status = status
        self.message = message
        self.metadata.update({
            "step_id": step_id,
            "step_name": step_name,
            "step_index": step_index,
            "total_steps": total_steps,
            "progress_percent": progress_percent,
            "overall_percent": overall_percent,
            "status": status,
            "message": message
        })

    def to_dict(self) -> dict[str, Any]:
        base = super().to_dict()
        base.update({
            "step_id": self.step_id,
            "step_name": self.step_name,
            "step_index": self.step_index,
            "total_steps": self.total_steps,
            "progress_percent": self.progress_percent,
            "overall_percent": self.overall_percent,
            "status": self.status,
            "message": self.message
        })
        return base


@dataclass
class StepCompleted(WorkflowEvent):
    """步骤完成事件"""
    step_id: str = ""
    step_index: int = 0
    execution_time: float = 0.0
    has_output: bool = False
    output_keys: list[str] = field(default_factory=list)

    def __init__(self, execution_id: str, step_id: str,
                 step_index: int = 0, execution_time: float = 0.0,
                 has_output: bool = False, output_keys: list[str] | None = None,
                 workflow_id: str | None = None,
                 user_id: str = "default", **kwargs):
        super().__init__(
            event_type=EventType.STEP_COMPLETED,
            execution_id=execution_id,
            workflow_id=workflow_id,
            user_id=user_id,
            priority=EventPriority.NORMAL
        )
        self.step_id = step_id
        self.step_index = step_index
        self.execution_time = execution_time
        self.has_output = has_output
        self.output_keys = output_keys or []
        self.metadata.update({
            "step_id": step_id,
            "step_index": step_index,
            "execution_time": execution_time,
            "has_output": has_output,
            "output_keys": self.output_keys
        })

    def to_dict(self) -> dict[str, Any]:
        base = super().to_dict()
        base.update({
            "step_id": self.step_id,
            "step_index": self.step_index,
            "execution_time": self.execution_time,
            "has_output": self.has_output,
            "output_keys": self.output_keys
        })
        return base


@dataclass
class StepFailed(WorkflowEvent):
    """步骤失败事件"""
    step_id: str = ""
    step_index: int = 0
    error: str = ""
    is_critical: bool = True
    retry_count: int = 0
    max_retries: int = 3

    def __init__(self, execution_id: str, step_id: str,
                 error: str, step_index: int = 0,
                 is_critical: bool = True, retry_count: int = 0,
                 max_retries: int = 3,
                 workflow_id: str | None = None,
                 user_id: str = "default", **kwargs):
        super().__init__(
            event_type=EventType.STEP_FAILED,
            execution_id=execution_id,
            workflow_id=workflow_id,
            user_id=user_id,
            priority=EventPriority.HIGH
        )
        self.step_id = step_id
        self.step_index = step_index
        self.error = error
        self.is_critical = is_critical
        self.retry_count = retry_count
        self.max_retries = max_retries
        self.metadata.update({
            "step_id": step_id,
            "step_index": step_index,
            "error": error,
            "is_critical": is_critical,
            "retry_count": retry_count,
            "max_retries": max_retries
        })

    def to_dict(self) -> dict[str, Any]:
        base = super().to_dict()
        base.update({
            "step_id": self.step_id,
            "step_index": self.step_index,
            "error": self.error,
            "is_critical": self.is_critical,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries
        })
        return base


@dataclass
class StepSkipped(WorkflowEvent):
    """步骤跳过事件"""
    step_id: str = ""
    step_index: int = 0
    reason: str = ""

    def __init__(self, execution_id: str, step_id: str,
                 step_index: int = 0, reason: str = "",
                 workflow_id: str | None = None,
                 user_id: str = "default", **kwargs):
        super().__init__(
            event_type=EventType.STEP_SKIPPED,
            execution_id=execution_id,
            workflow_id=workflow_id,
            user_id=user_id,
            priority=EventPriority.LOW
        )
        self.step_id = step_id
        self.step_index = step_index
        self.reason = reason
        self.metadata.update({
            "step_id": step_id,
            "step_index": step_index,
            "reason": reason
        })

    def to_dict(self) -> dict[str, Any]:
        base = super().to_dict()
        base.update({
            "step_id": self.step_id,
            "step_index": self.step_index,
            "reason": self.reason
        })
        return base


@dataclass
class StepRetry(WorkflowEvent):
    """步骤重试事件"""
    step_id: str = ""
    step_index: int = 0
    retry_count: int = 0
    max_retries: int = 3
    previous_error: str = ""

    def __init__(self, execution_id: str, step_id: str,
                 retry_count: int = 0, max_retries: int = 3,
                 previous_error: str = "", step_index: int = 0,
                 workflow_id: str | None = None,
                 user_id: str = "default", **kwargs):
        super().__init__(
            event_type=EventType.STEP_RETRY,
            execution_id=execution_id,
            workflow_id=workflow_id,
            user_id=user_id,
            priority=EventPriority.NORMAL
        )
        self.step_id = step_id
        self.step_index = step_index
        self.retry_count = retry_count
        self.max_retries = max_retries
        self.previous_error = previous_error
        self.metadata.update({
            "step_id": step_id,
            "step_index": step_index,
            "retry_count": retry_count,
            "max_retries": max_retries,
            "previous_error": previous_error
        })

    def to_dict(self) -> dict[str, Any]:
        base = super().to_dict()
        base.update({
            "step_id": self.step_id,
            "step_index": self.step_index,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "previous_error": self.previous_error
        })
        return base


# ═══════════════════════════════════════════════════════════════════════════════
# 用户干预事件
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class WorkflowPaused(WorkflowEvent):
    """工作流暂停事件"""
    step_idx: int = 0
    step_id: str | None = None
    reason: str = ""
    can_resume: bool = True

    def __init__(self, execution_id: str, step_idx: int = 0,
                 step_id: str | None = None, reason: str = "",
                 can_resume: bool = True,
                 workflow_id: str | None = None,
                 user_id: str = "default", **kwargs):
        super().__init__(
            event_type=EventType.WORKFLOW_PAUSED,
            execution_id=execution_id,
            workflow_id=workflow_id,
            user_id=user_id,
            priority=EventPriority.HIGH
        )
        self.step_idx = step_idx
        self.step_id = step_id
        self.reason = reason
        self.can_resume = can_resume
        self.metadata.update({
            "step_idx": step_idx,
            "step_id": step_id,
            "reason": reason,
            "can_resume": can_resume
        })

    def to_dict(self) -> dict[str, Any]:
        base = super().to_dict()
        base.update({
            "step_idx": self.step_idx,
            "step_id": self.step_id,
            "reason": self.reason,
            "can_resume": self.can_resume
        })
        return base


@dataclass
class WorkflowResumed(WorkflowEvent):
    """工作流恢复事件"""
    from_step_idx: int = 0
    step_id: str | None = None
    ai_understanding: str = ""

    def __init__(self, execution_id: str, from_step_idx: int = 0,
                 step_id: str | None = None, ai_understanding: str = "",
                 workflow_id: str | None = None,
                 user_id: str = "default", **kwargs):
        super().__init__(
            event_type=EventType.WORKFLOW_RESUMED,
            execution_id=execution_id,
            workflow_id=workflow_id,
            user_id=user_id,
            priority=EventPriority.HIGH
        )
        self.from_step_idx = from_step_idx
        self.step_id = step_id
        self.ai_understanding = ai_understanding
        self.metadata.update({
            "from_step_idx": from_step_idx,
            "step_id": step_id,
            "ai_understanding": ai_understanding
        })

    def to_dict(self) -> dict[str, Any]:
        base = super().to_dict()
        base.update({
            "from_step_idx": self.from_step_idx,
            "step_id": self.step_id,
            "ai_understanding": self.ai_understanding
        })
        return base


@dataclass
class WorkflowModified(WorkflowEvent):
    """工作流修改事件"""
    modifications: dict[str, Any] = field(default_factory=dict)
    modification_types: list[str] = field(default_factory=list)

    def __init__(self, execution_id: str,
                 modifications: dict[str, Any] | None = None,
                 modification_types: list[str] | None = None,
                 workflow_id: str | None = None,
                 user_id: str = "default", **kwargs):
        super().__init__(
            event_type=EventType.WORKFLOW_MODIFIED,
            execution_id=execution_id,
            workflow_id=workflow_id,
            user_id=user_id,
            priority=EventPriority.HIGH
        )
        self.modifications = modifications or {}
        self.modification_types = modification_types or []
        self.metadata.update({
            "modifications": self.modifications,
            "modification_types": self.modification_types
        })

    def to_dict(self) -> dict[str, Any]:
        base = super().to_dict()
        base.update({
            "modifications": self.modifications,
            "modification_types": self.modification_types
        })
        return base


# ═══════════════════════════════════════════════════════════════════════════════
# 状态变更事件
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class StateChanged(WorkflowEvent):
    """状态变更事件"""
    from_state: str = ""
    to_state: str = ""
    triggered_by: str = ""  # 触发原因

    def __init__(self, execution_id: str, from_state: str, to_state: str,
                 triggered_by: str = "", workflow_id: str | None = None,
                 user_id: str = "default", **kwargs):
        super().__init__(
            event_type=EventType.STATE_CHANGED,
            execution_id=execution_id,
            workflow_id=workflow_id,
            user_id=user_id,
            priority=EventPriority.NORMAL
        )
        self.from_state = from_state
        self.to_state = to_state
        self.triggered_by = triggered_by
        self.metadata.update({
            "from_state": from_state,
            "to_state": to_state,
            "triggered_by": triggered_by
        })

    def to_dict(self) -> dict[str, Any]:
        base = super().to_dict()
        base.update({
            "from_state": self.from_state,
            "to_state": self.to_state,
            "triggered_by": self.triggered_by
        })
        return base


@dataclass
class CheckpointSaved(WorkflowEvent):
    """检查点保存事件"""
    checkpoint_name: str = ""
    step_id: str | None = None
    step_status: str = ""
    can_restore: bool = True

    def __init__(self, execution_id: str, checkpoint_name: str,
                 step_id: str | None = None, step_status: str = "",
                 can_restore: bool = True,
                 workflow_id: str | None = None,
                 user_id: str = "default", **kwargs):
        super().__init__(
            event_type=EventType.CHECKPOINT_SAVED,
            execution_id=execution_id,
            workflow_id=workflow_id,
            user_id=user_id,
            priority=EventPriority.LOW
        )
        self.checkpoint_name = checkpoint_name
        self.step_id = step_id
        self.step_status = step_status
        self.can_restore = can_restore
        self.metadata.update({
            "checkpoint_name": checkpoint_name,
            "step_id": step_id,
            "step_status": step_status,
            "can_restore": can_restore
        })

    def to_dict(self) -> dict[str, Any]:
        base = super().to_dict()
        base.update({
            "checkpoint_name": self.checkpoint_name,
            "step_id": self.step_id,
            "step_status": self.step_status,
            "can_restore": self.can_restore
        })
        return base


# ═══════════════════════════════════════════════════════════════════════════════
# 事件处理器接口
# ═══════════════════════════════════════════════════════════════════════════════

class EventHandler:
    """事件处理器接口"""

    def handle(self, event: WorkflowEvent) -> bool:
        """
        处理事件

        Args:
            event: 工作流事件

        Returns:
            bool: 是否成功处理
        """
        raise NotImplementedError

    def can_handle(self, event: WorkflowEvent) -> bool:
        """
        检查是否能处理该事件

        Args:
            event: 工作流事件

        Returns:
            bool: 是否能处理
        """
        return True


# ═══════════════════════════════════════════════════════════════════════════════
# 事件总线
# ═══════════════════════════════════════════════════════════════════════════════

class EventBus:
    """事件总线 - 用于事件的发布和订阅"""

    def __init__(self):
        self._handlers: list[EventHandler] = []
        self._subscribers: dict[EventType, list[Callable]] = {}

    def register_handler(self, handler: EventHandler):
        """注册事件处理器"""
        self._handlers.append(handler)

    def unregister_handler(self, handler: EventHandler):
        """注销事件处理器"""
        if handler in self._handlers:
            self._handlers.remove(handler)

    def subscribe(self, event_type: EventType, callback: Callable):
        """订阅特定类型的事件"""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)

    def unsubscribe(self, event_type: EventType, callback: Callable):
        """取消订阅"""
        if event_type in self._subscribers and callback in self._subscribers[event_type]:
            self._subscribers[event_type].remove(callback)

    def publish(self, event: WorkflowEvent):
        """发布事件"""
        # 调用注册的处理器
        for handler in self._handlers:
            try:
                if handler.can_handle(event):
                    handler.handle(event)
            except Exception as e:
                logger.error(f"[EventBus] 处理器执行失败: {e}")

        # 调用订阅者
        if event.event_type in self._subscribers:
            for callback in self._subscribers[event.event_type]:
                try:
                    callback(event)
                except Exception as e:
                    logger.error(f"[EventBus] 订阅者执行失败: {e}")


# 全局事件总线实例
_event_bus = None


def get_event_bus() -> EventBus:
    """获取全局事件总线实例"""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus


def publish_event(event: WorkflowEvent):
    """便捷函数：发布事件到全局总线"""
    get_event_bus().publish(event)
