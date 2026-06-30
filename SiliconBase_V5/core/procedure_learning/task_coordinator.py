#!/usr/bin/env python3
"""
任务协调器 (Task Coordinator)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

整合任务执行、暂停聊天、演示学习和流程复用的完整协调器。

功能：
1. 任务执行与暂停管理
2. 用户接管和演示录制
3. 学习用户操作并保存流程
4. 复用学习到的流程
5. 对话与任务的无缝切换
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.agent.checkpoint_manager import CheckpointManager
from core.agent.pause_confirmation_state_machine import PauseConfirmationManager

from .adaptive_executor import get_adaptive_executor
from .demonstration_learner import get_demonstration_learner
from .operation_recorder import UserOperation, get_operation_recorder
from .procedure_library import Procedure, get_procedure_library


class TaskMode(Enum):
    """任务模式"""
    AI_EXECUTING = "ai_executing"           # AI执行任务
    USER_DEMONSTRATING = "user_demonstrating" # 用户演示
    CHATTING = "chatting"                    # 聊天对齐
    PAUSED = "paused"                        # 暂停等待


@dataclass
class TaskSession:
    """任务会话"""
    session_id: str
    task_id: str
    original_intent: str
    mode: TaskMode
    context: dict[str, Any] = field(default_factory=dict)
    procedure_id: str | None = None  # 关联的流程ID
    recording_id: str | None = None  # 录制ID
    created_at: float = field(default_factory=time.time)


class ProcedureLearningTaskCoordinator:
    """
    演示学习任务协调器

    实现完整的任务暂停-聊天-恢复-学习流程。
    """

    def __init__(self):
        self.checkpoint_manager = CheckpointManager()
        self.pause_manager = PauseConfirmationManager()
        self.operation_recorder = get_operation_recorder()
        self.procedure_library = get_procedure_library()
        self.learner = get_demonstration_learner()
        self.executor = get_adaptive_executor()

        self._active_sessions: dict[str, TaskSession] = {}
        self._current_session: TaskSession | None = None

        # 回调
        self._on_mode_changed: Callable[[TaskMode, TaskMode], None] | None = None
        self._on_recording_started: Callable[[], None] | None = None
        self._on_recording_stopped: Callable[[list[UserOperation]], None] | None = None
        self._on_procedure_learned: Callable[[Procedure], None] | None = None

    def register_callbacks(
        self,
        on_mode_changed: Callable[[TaskMode, TaskMode], None] | None = None,
        on_recording_started: Callable[[], None] | None = None,
        on_recording_stopped: Callable[[list[UserOperation]], None] | None = None,
        on_procedure_learned: Callable[[Procedure], None] | None = None
    ):
        """注册回调"""
        self._on_mode_changed = on_mode_changed
        self._on_recording_started = on_recording_started
        self._on_recording_stopped = on_recording_stopped
        self._on_procedure_learned = on_procedure_learned

    def start_task(self, session_id: str, task_id: str, intent: str) -> TaskSession:
        """
        开始新任务

        Args:
            session_id: 会话ID
            task_id: 任务ID
            intent: 用户意图

        Returns:
            任务会话
        """
        # 检查是否有已学习的流程可以复用
        existing_procedures = self.procedure_library.find_by_intent(intent)

        if existing_procedures and existing_procedures[0].get_success_rate() > 0.7:
            # 有高成功率的流程，建议复用
            procedure = existing_procedures[0]
            return self._start_with_procedure(session_id, task_id, intent, procedure)

        # 创建新会话
        session = TaskSession(
            session_id=session_id,
            task_id=task_id,
            original_intent=intent,
            mode=TaskMode.AI_EXECUTING
        )

        self._active_sessions[session_id] = session
        self._current_session = session

        return session

    def _start_with_procedure(
        self,
        session_id: str,
        task_id: str,
        intent: str,
        procedure: Procedure
    ) -> TaskSession:
        """使用已有流程开始任务"""
        session = TaskSession(
            session_id=session_id,
            task_id=task_id,
            original_intent=intent,
            mode=TaskMode.AI_EXECUTING,
            procedure_id=procedure.procedure_id
        )

        self._active_sessions[session_id] = session
        self._current_session = session

        return session

    def pause_for_chat(self, session_id: str, reason: str = "") -> bool:
        """
        暂停任务，进入聊天模式

        Args:
            session_id: 会话ID
            reason: 暂停原因

        Returns:
            是否成功暂停
        """
        session = self._active_sessions.get(session_id)
        if not session:
            return False

        old_mode = session.mode
        session.mode = TaskMode.CHATTING

        # 暂停执行器
        self.executor.pause(message=reason)

        # 暂停确认状态机
        self.pause_manager.pause_task(
            task_id=session.task_id,
            session_id=session_id,
            reason=reason,
            original_requirement=session.original_intent
        )

        if self._on_mode_changed:
            self._on_mode_changed(old_mode, TaskMode.CHATTING)

        return True

    def resume_from_chat(self, session_id: str, user_confirmation: bool = True) -> bool:
        """
        从聊天模式恢复任务

        Args:
            session_id: 会话ID
            user_confirmation: 用户是否确认继续

        Returns:
            是否成功恢复
        """
        session = self._active_sessions.get(session_id)
        if not session:
            return False

        if not user_confirmation:
            # 用户不想继续，可以询问是否需要演示
            return False

        old_mode = session.mode
        session.mode = TaskMode.AI_EXECUTING

        # 恢复执行器
        self.executor.resume()

        # 完成暂停状态机
        self.pause_manager.confirm_resume(session.task_id)

        if self._on_mode_changed:
            self._on_mode_changed(old_mode, TaskMode.AI_EXECUTING)

        return True

    def start_user_demonstration(self, session_id: str) -> bool:
        """
        开始用户演示模式

        Args:
            session_id: 会话ID

        Returns:
            是否成功启动
        """
        session = self._active_sessions.get(session_id)
        if not session:
            return False

        old_mode = session.mode
        session.mode = TaskMode.USER_DEMONSTRATING

        # 开始录制
        recording_id = self.operation_recorder.start_recording(
            context={
                "task": session.original_intent,
                "session_id": session_id
            }
        )
        session.recording_id = recording_id

        if self._on_mode_changed:
            self._on_mode_changed(old_mode, TaskMode.USER_DEMONSTRATING)

        if self._on_recording_started:
            self._on_recording_started()

        return True

    def stop_user_demonstration(self, session_id: str) -> Procedure | None:
        """
        停止用户演示，并学习流程

        Args:
            session_id: 会话ID

        Returns:
            学习到的Procedure，如果失败返回None
        """
        session = self._active_sessions.get(session_id)
        if not session:
            return None

        # 停止录制
        operations = self.operation_recorder.stop_recording()

        if self._on_recording_stopped:
            self._on_recording_stopped(operations)

        if not operations:
            return None

        # 学习流程
        try:
            procedure = self.learner.learn_from_recording(
                operations=operations,
                task_description=session.original_intent,
                context={"recording_id": session.recording_id}
            )

            # 保存到流程库
            procedure_id = self.procedure_library.add_procedure(procedure)
            session.procedure_id = procedure_id

            # 切换回AI执行模式
            old_mode = session.mode
            session.mode = TaskMode.AI_EXECUTING

            if self._on_mode_changed:
                self._on_mode_changed(old_mode, TaskMode.AI_EXECUTING)

            if self._on_procedure_learned:
                self._on_procedure_learned(procedure)

            return procedure

        except Exception as e:
            print(f"[TaskCoordinator] 学习流程失败: {e}")
            return None

    def execute_learned_procedure(
        self,
        session_id: str,
        procedure_id: str | None = None,
        parameters: dict[str, Any] | None = None
    ) -> bool:
        """
        执行学习到的流程

        Args:
            session_id: 会话ID
            procedure_id: 流程ID（默认使用会话关联的流程）
            parameters: 运行时参数

        Returns:
            是否成功启动执行
        """
        session = self._active_sessions.get(session_id)
        if not session:
            return False

        proc_id = procedure_id or session.procedure_id
        if not proc_id:
            return False

        procedure = self.procedure_library.get_procedure(proc_id)
        # 使用自适应执行器执行
        # 注意：这里应该是异步执行
        # 简化起见，存在procedure即返回True表示启动成功
        return bool(procedure)

    def get_session_status(self, session_id: str) -> dict[str, Any] | None:
        """获取会话状态"""
        session = self._active_sessions.get(session_id)
        if not session:
            return None

        return {
            "session_id": session.session_id,
            "task_id": session.task_id,
            "intent": session.original_intent,
            "mode": session.mode.value,
            "procedure_id": session.procedure_id,
            "recording_id": session.recording_id,
            "created_at": session.created_at
        }

    def suggest_action(self, session_id: str) -> dict[str, Any]:
        """
        根据当前状态建议下一步操作

        Returns:
            建议信息
        """
        session = self._active_sessions.get(session_id)
        if not session:
            return {"error": "会话不存在"}

        if session.mode == TaskMode.AI_EXECUTING:
            # 检查是否有可用流程
            procedures = self.procedure_library.find_by_intent(session.original_intent)
            if procedures:
                best = procedures[0]
                return {
                    "suggestion": "use_procedure",
                    "message": f"发现可用流程 '{best.name}' (成功率: {best.get_success_rate():.0%})",
                    "procedure_id": best.procedure_id
                }
            else:
                return {
                    "suggestion": "continue_ai",
                    "message": "AI继续执行任务"
                }

        elif session.mode == TaskMode.CHATTING:
            return {
                "suggestion": "chat_or_resume",
                "message": "可以聊天对齐需求，或恢复任务执行",
                "options": ["resume", "demonstrate", "modify_requirement"]
            }

        elif session.mode == TaskMode.USER_DEMONSTRATING:
            return {
                "suggestion": "recording",
                "message": "正在录制用户操作",
                "options": ["stop_recording"]
            }

        return {"suggestion": "unknown"}

    def end_session(self, session_id: str):
        """结束会话"""
        if session_id in self._active_sessions:
            del self._active_sessions[session_id]
            if self._current_session and self._current_session.session_id == session_id:
                self._current_session = None


# 全局实例
_coordinator_instance: ProcedureLearningTaskCoordinator | None = None

def get_task_coordinator() -> ProcedureLearningTaskCoordinator:
    """获取全局任务协调器实例"""
    global _coordinator_instance
    if _coordinator_instance is None:
        _coordinator_instance = ProcedureLearningTaskCoordinator()
    return _coordinator_instance
