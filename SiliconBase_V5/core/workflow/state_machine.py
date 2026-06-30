#!/usr/bin/env python3
"""
WorkflowStateMachine - 工作流状态机 V1.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
支持动态修改、分支、人机协作的状态管理

【核心特性】
1. 完整状态图定义（PENDING -> RUNNING -> [PAUSED|VERIFY|ERROR] -> COMPLETED）
2. 用户干预支持（暂停、修改、恢复）
3. 状态转换钩子（进入/退出状态执行动作）
4. 与 CheckpointManager 集成（状态变更自动保存）
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

try:
    from core.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger('workflow_state_machine')

# 导入 StepStatus 用于类型检查
try:
    from .workflow_engine import StepStatus
except ImportError:
    # 备用定义（当独立运行时使用）
    from enum import Enum
    class StepStatus(Enum):
        PENDING = "pending"
        READY = "ready"
        RUNNING = "running"
        COMPLETED = "completed"
        FAILED = "failed"
        SKIPPED = "skipped"
        PAUSED = "paused"
        VERIFYING = "verifying"


# ═══════════════════════════════════════════════════════════════════════════════
# 事件与状态定义
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class StateEvent:
    """状态事件"""
    type: str  # start, complete, pause, resume, error, verify, modify, skip, cancel
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    @classmethod
    def start(cls, **kwargs) -> 'StateEvent':
        return cls(type="start", payload=kwargs)

    @classmethod
    def complete(cls, **kwargs) -> 'StateEvent':
        return cls(type="complete", payload=kwargs)

    @classmethod
    def pause(cls, reason: str = "", **kwargs) -> 'StateEvent':
        return cls(type="pause", payload={"reason": reason, **kwargs})

    @classmethod
    def resume(cls, **kwargs) -> 'StateEvent':
        return cls(type="resume", payload=kwargs)

    @classmethod
    def error(cls, error: str, **kwargs) -> 'StateEvent':
        return cls(type="error", payload={"error": error, **kwargs})

    @classmethod
    def modify(cls, modifications: dict[str, Any], **kwargs) -> 'StateEvent':
        return cls(type="modify", payload={"modifications": modifications, **kwargs})


@dataclass
class State:
    """状态定义"""
    name: str
    allowed_transitions: list[str] = field(default_factory=list)
    description: str = ""

    def can_transition_to(self, target_state: str) -> bool:
        """检查是否可以转换到目标状态"""
        return target_state in self.allowed_transitions


# ═══════════════════════════════════════════════════════════════════════════════
# 状态机主类
# ═══════════════════════════════════════════════════════════════════════════════

class WorkflowStateMachine:
    """
    工作流状态机

    状态转换图：

    ┌─────────┐  start   ┌─────────┐
    │ PENDING │ ───────> │ RUNNING │
    └─────────┘          └────┬────┘
                              │
           ┌──────────────────┼──────────────────┐
           │                  │                  │
           ▼                  ▼                  ▼
    ┌─────────┐       ┌─────────┐        ┌─────────┐
    │ PAUSED  │<────->│ VERIFY  │        │  ERROR  │
    │(可修改) │       │(验证中) │        │(可重试) │
    └────┬────┘       └────┬────┘        └────┬────┘
         │                 │                  │
         │ modify          │ verify_ok        │ retry
         ▼                 ▼                  ▼
    ┌─────────┐       ┌─────────┐        ┌─────────┐
    │MODIFIED │──────>│COMPLETED│        │ RUNNING │
    └─────────┘       └─────────┘        └─────────┘

    特殊转换：
    - RUNNING -> PAUSED: 用户主动暂停
    - PAUSED -> MODIFIED: 用户修改工作流
    - ANY -> CANCELLED: 用户取消
    """

    # 状态定义
    STATES = {
        "PENDING": State(
            name="PENDING",
            allowed_transitions=["RUNNING", "CANCELLED"],
            description="等待开始执行"
        ),
        "RUNNING": State(
            name="RUNNING",
            allowed_transitions=["PAUSED", "VERIFY", "ERROR", "COMPLETED", "CANCELLED"],
            description="执行中"
        ),
        "PAUSED": State(
            name="PAUSED",
            allowed_transitions=["RUNNING", "MODIFIED", "CANCELLED"],
            description="暂停（等待用户）"
        ),
        "MODIFIED": State(
            name="MODIFIED",
            allowed_transitions=["RUNNING", "PENDING"],
            description="已修改，准备重新执行"
        ),
        "VERIFY": State(
            name="VERIFY",
            allowed_transitions=["COMPLETED", "ERROR", "PAUSED"],
            description="验证执行结果"
        ),
        "ERROR": State(
            name="ERROR",
            allowed_transitions=["RUNNING", "PAUSED", "CANCELLED"],
            description="执行出错"
        ),
        "COMPLETED": State(
            name="COMPLETED",
            allowed_transitions=["PENDING"],  # 可以重新启动
            description="已完成"
        ),
        "CANCELLED": State(
            name="CANCELLED",
            allowed_transitions=["PENDING"],  # 可以重新启动
            description="已取消"
        )
    }

    def __init__(self, execution_id: str, workflow_execution=None):
        """
        初始化状态机

        Args:
            execution_id: 执行实例ID
            workflow_execution: 工作流执行实例（可选）
        """
        self.execution_id = execution_id
        self._execution = workflow_execution

        # 当前状态
        self._state = self.STATES["PENDING"]
        self._state_history: list[dict[str, Any]] = []

        # 状态处理器
        self._handlers: dict[str, Callable] = {
            "PENDING": self._on_pending,
            "RUNNING": self._on_running,
            "PAUSED": self._on_paused,
            "MODIFIED": self._on_modified,
            "VERIFY": self._on_verify,
            "ERROR": self._on_error,
            "COMPLETED": self._on_completed,
            "CANCELLED": self._on_cancelled
        }

        # 进入/退出钩子
        self._enter_hooks: dict[str, list[Callable]] = {name: [] for name in self.STATES}
        self._exit_hooks: dict[str, list[Callable]] = {name: [] for name in self.STATES}

        # 锁
        self._lock = threading.RLock()

        # 延迟加载的依赖
        self._checkpoint_manager = None

        logger.info(f"[WorkflowStateMachine] 初始化: {execution_id}")

    @property
    def state(self) -> State:
        """当前状态"""
        return self._state

    @property
    def state_name(self) -> str:
        """当前状态名"""
        return self._state.name

    def _get_checkpoint_manager(self):
        """延迟加载 CheckpointManager"""
        if self._checkpoint_manager is None:
            try:
                from core.agent.checkpoint_manager import checkpoint_manager
                self._checkpoint_manager = checkpoint_manager
            except ImportError:
                pass
        return self._checkpoint_manager

    # ═══════════════════════════════════════════════════════════════════════════
    # 状态转换
    # ═══════════════════════════════════════════════════════════════════════════

    def transition(self, event: StateEvent) -> bool:
        """
        状态转换

        Args:
            event: 状态事件

        Returns:
            bool: 是否成功转换
        """
        with self._lock:
            # 计算目标状态
            target_state = self._calculate_target_state(event)

            if not target_state:
                logger.warning(f"[WorkflowStateMachine] 无法确定目标状态: {event.type}")
                return False

            # 检查转换是否允许
            if not self._state.can_transition_to(target_state):
                logger.warning(
                    f"[WorkflowStateMachine] 非法状态转换: "
                    f"{self._state.name} -> {target_state}"
                )
                return False

            # 执行退出当前状态的动作
            self._on_exit_state(self._state.name, event)

            # 转换状态
            old_state = self._state.name
            self._state = self.STATES[target_state]

            # 记录历史
            self._state_history.append({
                "from": old_state,
                "to": target_state,
                "event": event.type,
                "timestamp": time.time(),
                "payload": event.payload
            })

            # 执行进入新状态的动作
            self._on_enter_state(target_state, event)

            # 调用状态处理器
            handler = self._handlers.get(target_state)
            if handler:
                try:
                    handler(event)
                except Exception as e:
                    logger.error(f"[WorkflowStateMachine] 状态处理器异常: {e}")

            logger.info(
                f"[WorkflowStateMachine] 状态转换: "
                f"{old_state} -> {target_state} (事件: {event.type})"
            )

            return True

    def _calculate_target_state(self, event: StateEvent) -> str | None:
        """根据事件计算目标状态"""
        transitions = {
            # 当前状态 -> 事件 -> 目标状态
            ("PENDING", "start"): "RUNNING",
            ("PENDING", "cancel"): "CANCELLED",

            ("RUNNING", "pause"): "PAUSED",
            ("RUNNING", "verify"): "VERIFY",
            ("RUNNING", "error"): "ERROR",
            ("RUNNING", "complete"): "COMPLETED",
            ("RUNNING", "cancel"): "CANCELLED",

            ("PAUSED", "resume"): "RUNNING",
            ("PAUSED", "modify"): "MODIFIED",
            ("PAUSED", "cancel"): "CANCELLED",

            ("MODIFIED", "resume"): "RUNNING",
            ("MODIFIED", "reset"): "PENDING",

            ("VERIFY", "verify_ok"): "COMPLETED",
            ("VERIFY", "verify_fail"): "ERROR",
            ("VERIFY", "pause"): "PAUSED",

            ("ERROR", "retry"): "RUNNING",
            ("ERROR", "pause"): "PAUSED",
            ("ERROR", "cancel"): "CANCELLED",

            ("COMPLETED", "restart"): "PENDING",
            ("CANCELLED", "restart"): "PENDING",
        }

        key = (self._state.name, event.type)
        return transitions.get(key)

    def can_transition(self, event_type: str) -> bool:
        """检查是否可以执行指定类型的事件转换"""
        target = self._calculate_target_state(StateEvent(type=event_type))
        if not target:
            return False
        return self._state.can_transition_to(target)

    # ═══════════════════════════════════════════════════════════════════════════
    # 状态处理器
    # ═══════════════════════════════════════════════════════════════════════════

    def _on_pending(self, event: StateEvent):
        """PENDING 状态处理"""
        pass

    def _on_running(self, event: StateEvent):
        """RUNNING 状态处理"""
        pass

    def _on_paused(self, event: StateEvent):
        """PAUSED 状态处理 - 支持用户修改"""
        # 保存检查点
        checkpoint_mgr = self._get_checkpoint_manager()
        if checkpoint_mgr:
            try:
                checkpoint_mgr.save_checkpoint(
                    task_id=self.execution_id,
                    checkpoint_name=f"暂停: {event.payload.get('reason', '')}"
                )
            except Exception as e:
                logger.warning(f"[WorkflowStateMachine] 保存检查点失败: {e}")

        # 获取可修改元素信息
        if self._execution:
            modifiables = self._get_modifiable_elements()
            logger.info(f"[WorkflowStateMachine] 可修改元素: {modifiables}")

    def _on_modified(self, event: StateEvent):
        """MODIFIED 状态处理 - 应用用户修改"""
        if not self._execution:
            return

        modifications = event.payload.get("modifications", {})

        # 应用修改
        if "skip_steps" in modifications:
            for step_id in modifications["skip_steps"]:
                self._execution.skip_step(step_id)

        if "modify_params" in modifications:
            for step_id, params in modifications["modify_params"].items():
                self._execution.modify_step_params(step_id, params)

        if "add_steps" in modifications:
            for step_def in modifications["add_steps"]:
                from .workflow_engine import WorkflowStep
                step = WorkflowStep.from_dict(step_def["step"])
                self._execution.insert_step(step_def["index"], step)

        if "update_variables" in modifications:
            self._execution.variables.update(modifications["update_variables"])

        # 保存修改后的检查点
        checkpoint_mgr = self._get_checkpoint_manager()
        if checkpoint_mgr:
            try:
                checkpoint_mgr.save_checkpoint(
                    task_id=self.execution_id,
                    checkpoint_name="应用用户修改"
                )
            except Exception as e:
                logger.warning(f"[WorkflowStateMachine] 保存修改检查点失败: {e}")

        # 自动转换到 RUNNING
        self.transition(StateEvent.resume())

    def _on_verify(self, event: StateEvent):
        """VERIFY 状态处理"""
        pass

    def _on_error(self, event: StateEvent):
        """ERROR 状态处理"""
        error_msg = event.payload.get("error", "未知错误")
        logger.error(f"[WorkflowStateMachine] 执行错误: {error_msg}")

    def _on_completed(self, event: StateEvent):
        """COMPLETED 状态处理"""
        logger.info(f"[WorkflowStateMachine] 执行完成: {self.execution_id}")

    def _on_cancelled(self, event: StateEvent):
        """CANCELLED 状态处理"""
        logger.info(f"[WorkflowStateMachine] 执行取消: {self.execution_id}")

    # ═══════════════════════════════════════════════════════════════════════════
    # 钩子机制
    # ═══════════════════════════════════════════════════════════════════════════

    def _on_enter_state(self, state_name: str, event: StateEvent):
        """进入状态钩子"""
        for hook in self._enter_hooks.get(state_name, []):
            try:
                hook(self, state_name, event)
            except Exception as e:
                logger.error(f"[WorkflowStateMachine] 进入钩子异常: {e}")

    def _on_exit_state(self, state_name: str, event: StateEvent):
        """退出状态钩子"""
        for hook in self._exit_hooks.get(state_name, []):
            try:
                hook(self, state_name, event)
            except Exception as e:
                logger.error(f"[WorkflowStateMachine] 退出钩子异常: {e}")

    def on_enter(self, state_name: str, handler: Callable):
        """注册进入状态钩子"""
        if state_name in self._enter_hooks:
            self._enter_hooks[state_name].append(handler)

    def on_exit(self, state_name: str, handler: Callable):
        """注册退出状态钩子"""
        if state_name in self._exit_hooks:
            self._exit_hooks[state_name].append(handler)

    # ═══════════════════════════════════════════════════════════════════════════
    # 辅助方法
    # ═══════════════════════════════════════════════════════════════════════════

    def _get_modifiable_elements(self) -> dict[str, Any]:
        """获取当前可修改的元素"""
        if not self._execution or not self._execution.workflow:
            return {}

        execution = self._execution
        workflow = execution.workflow

        # 当前步骤
        current_step = execution.get_current_step()
        current_step_info = None
        if current_step:
            current_step_info = {
                "id": current_step.step_id,
                "name": current_step.name,
                "description": current_step.description,
                "params": current_step.tool_params,
                "can_skip": not current_step.is_critical,
                "can_modify_params": current_step.allow_modification,
                "status": current_step.status.value
            }

        # 待执行步骤
        pending_steps = [
            {
                "id": s.step_id,
                "name": s.name,
                "can_skip": not s.is_critical,
                "status": s.status.value
            }
            for s in workflow.steps[execution.current_step_idx:]
            if s.status in [StepStatus.PENDING, StepStatus.READY]
        ]

        return {
            "current_step": current_step_info,
            "pending_steps": pending_steps,
            "variables": dict(execution.variables),  # 复制
            "current_step_idx": execution.current_step_idx,
            "total_steps": len(workflow.steps),
            "can_add_steps": True,
            "can_change_goal": execution.current_step_idx < 2,
            "execution_id": execution.execution_id,
            "status": execution.status.value
        }

    def get_state_history(self) -> list[dict[str, Any]]:
        """获取状态历史"""
        return self._state_history.copy()

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "execution_id": self.execution_id,
            "current_state": self._state.name,
            "state_history": self._state_history
        }


# ═══════════════════════════════════════════════════════════════════════════════
# 便捷方法
# ═══════════════════════════════════════════════════════════════════════════════

def create_state_machine(execution_id: str, workflow_execution=None) -> WorkflowStateMachine:
    """创建状态机实例"""
    return WorkflowStateMachine(execution_id, workflow_execution)
