#!/usr/bin/env python3
"""
演示学习系统集成模块 (Procedure Learning Integration)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

将演示学习系统与 Agent Loop 集成，实现：
1. 任务执行失败时暂停并询问用户
2. 用户演示录制和学习
3. 复用已学习的流程

作者: AI Assistant
版本: 1.0.0
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from core.logger import logger
from core.sync.realtime_sync import get_realtime_sync_manager

# 演示学习系统导入
try:
    from core.procedure_learning import Procedure, ProcedureStep, get_procedure_library, get_task_coordinator
    PROCEDURE_LEARNING_AVAILABLE = True
except ImportError as e:
    logger.warning(f"[ProcedureLearning] 演示学习系统不可用: {e}")
    PROCEDURE_LEARNING_AVAILABLE = False


class ProcedureLearningState(Enum):
    """演示学习集成状态"""
    IDLE = "idle"                           # 空闲
    CHECKING_LIBRARY = "checking_library"   # 检查流程库
    EXECUTING_PROCEDURE = "executing_procedure"  # 执行学习到的流程
    PAUSED_FOR_CHAT = "paused_for_chat"     # 已暂停等待聊天
    RECORDING_DEMONSTRATION = "recording_demonstration"  # 录制演示中
    LEARNING_COMPLETED = "learning_completed"  # 学习完成


@dataclass
class ProcedureLearningContext:
    """演示学习上下文"""
    session_id: str
    task_id: str
    user_instruction: str
    state: ProcedureLearningState
    procedure_id: str | None = None
    recording_id: str | None = None
    learned_procedure: Any | None = None
    failure_count: int = 0
    max_failures_before_pause: int = 2  # 失败几次后暂停询问用户


class ProcedureLearningIntegration:
    """
    演示学习系统集成器

    负责将演示学习功能集成到 Agent Loop 中。
    """

    # 成功率阈值 - 超过此阈值的流程会被推荐使用
    SUCCESS_RATE_THRESHOLD = 0.7

    # 最大失败次数 - 超过此次数后暂停任务
    MAX_FAILURES_BEFORE_PAUSE = 2

    def __init__(self):
        self._coordinator = None
        self._procedure_library = None
        self._sync = get_realtime_sync_manager()
        self._contexts: dict[str, ProcedureLearningContext] = {}
        self._lock = threading.RLock()

        # 回调函数
        self._on_procedure_found: Callable[[str, Any], bool] | None = None
        self._on_pause_for_chat: Callable[[str, str], None] | None = None
        self._on_demonstration_start: Callable[[str], None] | None = None
        self._on_demonstration_end: Callable[[str, Any], None] | None = None

        if PROCEDURE_LEARNING_AVAILABLE:
            try:
                self._coordinator = get_task_coordinator()
                self._procedure_library = get_procedure_library()
                logger.info("[ProcedureLearning] 演示学习系统集成器初始化完成")
            except Exception as e:
                logger.error(f"[ProcedureLearning] 初始化失败: {e}")

    def register_callbacks(
        self,
        on_procedure_found: Callable[[str, Any], bool] | None = None,
        on_pause_for_chat: Callable[[str, str], None] | None = None,
        on_demonstration_start: Callable[[str], None] | None = None,
        on_demonstration_end: Callable[[str, Any], None] | None = None
    ):
        """注册回调函数"""
        self._on_procedure_found = on_procedure_found
        self._on_pause_for_chat = on_pause_for_chat
        self._on_demonstration_start = on_demonstration_start
        self._on_demonstration_end = on_demonstration_end

    def is_available(self) -> bool:
        """检查演示学习系统是否可用"""
        return PROCEDURE_LEARNING_AVAILABLE and self._coordinator is not None

    def start_task(
        self,
        session_id: str,
        task_id: str,
        user_instruction: str
    ) -> ProcedureLearningContext | None:
        """
        开始新任务，检查是否有可复用的流程

        Args:
            session_id: 会话ID
            task_id: 任务ID
            user_instruction: 用户指令

        Returns:
            演示学习上下文，如果没有可用流程返回None
        """
        if not self.is_available():
            return None

        with self._lock:
            # 创建上下文
            context = ProcedureLearningContext(
                session_id=session_id,
                task_id=task_id,
                user_instruction=user_instruction,
                state=ProcedureLearningState.IDLE
            )
            self._contexts[session_id] = context

            try:
                # 启动任务协调器
                self._coordinator.start_task(session_id, task_id, user_instruction)

                # 检查流程库
                context.state = ProcedureLearningState.CHECKING_LIBRARY
                procedures = self._procedure_library.find_by_intent(user_instruction)

                if procedures and len(procedures) > 0:
                    best_procedure = procedures[0]
                    success_rate = best_procedure.get_success_rate()

                    logger.info(f"[ProcedureLearning] 找到流程 '{best_procedure.name}' "
                               f"(成功率: {success_rate:.0%})")

                    # 检查成功率是否超过阈值
                    if success_rate >= self.SUCCESS_RATE_THRESHOLD:
                        context.procedure_id = best_procedure.procedure_id
                        context.state = ProcedureLearningState.EXECUTING_PROCEDURE

                        # 发送事件到前端
                        self._sync.emit_event("procedure_found", session_id, {
                            "procedure_id": best_procedure.procedure_id,
                            "name": best_procedure.name,
                            "success_rate": success_rate,
                            "steps_count": len(best_procedure.steps)
                        })

                        # 调用回调
                        if self._on_procedure_found:
                            should_use = self._on_procedure_found(session_id, best_procedure)
                            if not should_use:
                                # 用户选择不使用，切换到AI执行模式
                                context.procedure_id = None
                                context.state = ProcedureLearningState.IDLE
                                return None

                        return context

                # 没有找到高成功率流程
                context.state = ProcedureLearningState.IDLE
                return None

            except Exception as e:
                error_msg = f"[SILENT_FAILURE_BLOCKED] [ProcedureLearning] 启动任务失败: {e}"
                logger.error(error_msg)
                raise RuntimeError(error_msg) from e

    def check_and_handle_tool_failure(
        self,
        session_id: str,
        tool_name: str,
        failure_reason: str
    ) -> tuple[bool, str | None]:
        """
        检查工具失败并决定是否需要暂停任务

        Args:
            session_id: 会话ID
            tool_name: 失败的工具名
            failure_reason: 失败原因

        Returns:
            (是否需要暂停, 暂停提示消息)
        """
        if not self.is_available():
            return False, None

        with self._lock:
            context = self._contexts.get(session_id)
            if not context:
                return False, None

            # 增加失败计数
            context.failure_count += 1

            logger.info(f"[ProcedureLearning] 工具 '{tool_name}' 失败 "
                       f"({context.failure_count}/{context.max_failures_before_pause}): {failure_reason}")

            # 检查是否达到暂停阈值
            if context.failure_count >= context.max_failures_before_pause:
                # 暂停任务并询问用户
                return self._pause_for_chat(session_id, tool_name, failure_reason)

            return False, None

    def _pause_for_chat(
        self,
        session_id: str,
        tool_name: str,
        failure_reason: str
    ) -> tuple[bool, str | None]:
        """
        暂停任务并准备询问用户

        Args:
            session_id: 会话ID
            tool_name: 失败的工具名
            failure_reason: 失败原因

        Returns:
            (是否成功暂停, 提示消息)
        """
        context = self._contexts.get(session_id)
        if not context:
            return False, None

        try:
            # 暂停任务
            success = self._coordinator.pause_for_chat(
                session_id,
                reason=f"工具 '{tool_name}' 执行失败: {failure_reason}"
            )

            if success:
                context.state = ProcedureLearningState.PAUSED_FOR_CHAT

                # 【改进】构建更清晰的询问消息 - 告诉用户具体问题
                # 根据工具类型提供不同的自然语言描述
                tool_action_names = {
                    "launch_app": "启动应用",
                    "mouse_click": "点击操作",
                    "keyboard_input": "输入内容",
                    "web_search": "搜索信息",
                    "screenshot": "截图",
                    "file_read": "读取文件",
                    "file_write": "写入文件",
                }
                action_name = tool_action_names.get(tool_name, f"{tool_name}操作")

                # 简化失败原因，避免技术术语
                simple_reason = failure_reason
                if "not found" in failure_reason.lower() or "未找到" in failure_reason:
                    simple_reason = "找不到相关项目"
                elif "permission" in failure_reason.lower() or "权限" in failure_reason:
                    simple_reason = "没有权限"
                elif "timeout" in failure_reason.lower() or "超时" in failure_reason:
                    simple_reason = "操作超时"

                pause_message = (
                    f"【需要帮助】{action_name}没有成功：{simple_reason}\n\n"
                    f"您可以选择：\n"
                    f"• 说'继续'让我尝试其他方法\n"
                    f"• 说'我来演示'教我怎么操作\n"
                    f"• 直接告诉我您想怎么做"
                )

                # 发送事件到前端
                self._sync.emit_event("procedure_learning_pause", session_id, {
                    "tool_name": tool_name,
                    "failure_reason": failure_reason,
                    "options": ["try_other_method", "demonstrate"],
                    "message": pause_message
                })

                # 调用回调
                if self._on_pause_for_chat:
                    self._on_pause_for_chat(session_id, pause_message)

                logger.info(f"[ProcedureLearning] 任务已暂停，等待用户选择: {session_id}")
                return True, pause_message
            else:
                error_msg = f"[ProcedureLearning] 暂停任务失败: {session_id}"
                logger.error(error_msg)
                return False, None

        except Exception as e:
            error_msg = f"[SILENT_FAILURE_BLOCKED] [ProcedureLearning] 暂停任务异常: {e}"
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e

    def handle_user_choice(
        self,
        session_id: str,
        choice: str
    ) -> tuple[bool, str | None]:
        """
        处理用户在暂停时的选择

        Args:
            session_id: 会话ID
            choice: 用户选择 ("try_other_method" | "demonstrate" | "resume")

        Returns:
            (是否成功处理, 提示消息)
        """
        if not self.is_available():
            return False, None

        with self._lock:
            context = self._contexts.get(session_id)
            if not context:
                return False, None

            if choice == "demonstrate":
                # 用户选择演示
                return self._start_demonstration(session_id)
            elif choice == "try_other_method" or choice == "resume":
                # 用户选择继续尝试或恢复
                return self._resume_task(session_id)
            else:
                logger.warning(f"[ProcedureLearning] 未知的选择: {choice}")
                return False, None

    def _start_demonstration(self, session_id: str) -> tuple[bool, str | None]:
        """
        开始用户演示录制

        Args:
            session_id: 会话ID

        Returns:
            (是否成功启动, 提示消息)
        """
        context = self._contexts.get(session_id)
        if not context:
            return False, None

        try:
            success = self._coordinator.start_user_demonstration(session_id)

            if success:
                context.state = ProcedureLearningState.RECORDING_DEMONSTRATION

                message = (
                    "好的，现在开始录制您的操作。\n"
                    "请按照您希望的方式完成这个任务，我会学习您的操作步骤。\n\n"
                    "完成操作后请告诉我'录制结束'。"
                )

                # 发送事件到前端
                self._sync.emit_event("demonstration_started", session_id, {
                    "message": message,
                    "recording_id": context.recording_id
                })

                # 调用回调
                if self._on_demonstration_start:
                    self._on_demonstration_start(session_id)

                logger.info(f"[ProcedureLearning] 演示录制已启动: {session_id}")
                return True, message
            else:
                error_msg = f"[ProcedureLearning] 启动演示录制失败: {session_id}"
                logger.error(error_msg)
                return False, None

        except Exception as e:
            error_msg = f"[SILENT_FAILURE_BLOCKED] [ProcedureLearning] 启动演示异常: {e}"
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e

    def stop_demonstration(self, session_id: str) -> tuple[bool, Any | None, str | None]:
        """
        停止演示并学习流程

        Args:
            session_id: 会话ID

        Returns:
            (是否成功, 学习到的流程, 提示消息)
        """
        if not self.is_available():
            return False, None, None

        with self._lock:
            context = self._contexts.get(session_id)
            if not context:
                return False, None, None

            try:
                procedure = self._coordinator.stop_user_demonstration(session_id)

                if procedure:
                    context.learned_procedure = procedure
                    context.procedure_id = procedure.procedure_id
                    context.state = ProcedureLearningState.LEARNING_COMPLETED

                    message = (
                        f"学习完成！我已经学会了 '{procedure.name}'。\n"
                        f"共 {len(procedure.steps)} 个步骤，下次遇到类似任务时可以直接使用。\n\n"
                        f"现在让我按照学习到的流程继续执行任务。"
                    )

                    # 发送事件到前端
                    self._sync.emit_event("demonstration_completed", session_id, {
                        "procedure_id": procedure.procedure_id,
                        "name": procedure.name,
                        "steps_count": len(procedure.steps),
                        "success_rate": procedure.get_success_rate()
                    })

                    # 调用回调
                    if self._on_demonstration_end:
                        self._on_demonstration_end(session_id, procedure)

                    logger.info(f"[ProcedureLearning] 演示学习完成: {procedure.procedure_id}")
                    return True, procedure, message
                else:
                    error_msg = "学习流程失败，没有记录到有效的操作"
                    logger.error(f"[ProcedureLearning] {error_msg}")
                    return False, None, error_msg

            except Exception as e:
                error_msg = f"[SILENT_FAILURE_BLOCKED] [ProcedureLearning] 停止演示异常: {e}"
                logger.error(error_msg)
                raise RuntimeError(error_msg) from e

    def _resume_task(self, session_id: str) -> tuple[bool, str | None]:
        """
        恢复任务执行

        Args:
            session_id: 会话ID

        Returns:
            (是否成功恢复, 提示消息)
        """
        context = self._contexts.get(session_id)
        if not context:
            return False, None

        try:
            success = self._coordinator.resume_from_chat(session_id, user_confirmation=True)

            if success:
                context.state = ProcedureLearningState.IDLE
                context.failure_count = 0  # 重置失败计数

                message = "好的，我会尝试其他方法继续完成任务。"

                # 发送事件到前端
                self._sync.emit_event("procedure_learning_resumed", session_id, {
                    "message": message
                })

                logger.info(f"[ProcedureLearning] 任务已恢复: {session_id}")
                return True, message
            else:
                error_msg = f"[ProcedureLearning] 恢复任务失败: {session_id}"
                logger.error(error_msg)
                return False, None

        except Exception as e:
            error_msg = f"[SILENT_FAILURE_BLOCKED] [ProcedureLearning] 恢复任务异常: {e}"
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e

    def execute_learned_procedure(
        self,
        session_id: str,
        procedure_id: str | None = None
    ) -> bool:
        """
        执行学习到的流程

        Args:
            session_id: 会话ID
            procedure_id: 流程ID（默认使用上下文中存储的）

        Returns:
            是否成功启动
        """
        if not self.is_available():
            return False

        context = self._contexts.get(session_id)
        if not context:
            return False

        proc_id = procedure_id or context.procedure_id
        if not proc_id:
            return False

        try:
            success = self._coordinator.execute_learned_procedure(
                session_id, proc_id
            )

            if success:
                context.state = ProcedureLearningState.EXECUTING_PROCEDURE
                logger.info(f"[ProcedureLearning] 开始执行流程: {proc_id}")

            return success

        except Exception as e:
            error_msg = f"[SILENT_FAILURE_BLOCKED] [ProcedureLearning] 执行流程异常: {e}"
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e

    def get_learned_procedure_steps(self, session_id: str) -> list[dict] | None:
        """
        获取学习到的流程步骤

        Args:
            session_id: 会话ID

        Returns:
            步骤列表，如果没有则返回None
        """
        if not self.is_available():
            return None

        context = self._contexts.get(session_id)
        if not context or not context.procedure_id:
            return None

        try:
            procedure = self._procedure_library.get_procedure(context.procedure_id)
            if procedure:
                return [
                    {
                        "step_number": step.step_number,
                        "description": step.description,
                        "tool_name": step.tool_name,
                        "tool_params": step.tool_params
                    }
                    for step in procedure.steps
                ]
            return None

        except Exception as e:
            logger.error(f"[ProcedureLearning] 获取流程步骤失败: {e}")
            return None

    def end_task(self, session_id: str):
        """结束任务并清理资源"""
        with self._lock:
            context = self._contexts.get(session_id)
            if context:
                try:
                    self._coordinator.end_session(session_id)
                except Exception as e:
                    logger.warning(f"[ProcedureLearning] 结束会话失败: {e}")

                del self._contexts[session_id]
                logger.info(f"[ProcedureLearning] 任务已结束: {session_id}")

    def get_context(self, session_id: str) -> ProcedureLearningContext | None:
        """获取演示学习上下文"""
        return self._contexts.get(session_id)

    def reset_failure_count(self, session_id: str):
        """重置失败计数"""
        with self._lock:
            context = self._contexts.get(session_id)
            if context:
                context.failure_count = 0
                logger.debug(f"[ProcedureLearning] 失败计数已重置: {session_id}")

    def save_generated_procedure(self, task_description: str, steps: list[dict],
                                 success: bool = True, metadata: dict = None) -> str | None:
        """
        【新增】保存 LLM 生成的流程到 Procedure Library

        这样下次相同任务可以直接使用，无需再生成

        Args:
            task_description: 任务描述（作为流程ID）
            steps: 步骤列表，每个步骤包含 tool_id, params, description
            success: 这次执行是否成功
            metadata: 额外元数据（执行时间、用户反馈等）

        Returns:
            procedure_id: 保存的流程ID
        """
        if not PROCEDURE_LEARNING_AVAILABLE or not self._procedure_library:
            logger.warning("[ProcedureLearning] 不可用，无法保存流程")
            return None

        try:
            # 1. 创建 Procedure 步骤
            procedure_steps = []
            for i, step_data in enumerate(steps):
                step = ProcedureStep(
                    step_number=i + 1,
                    description=step_data.get('description', ''),
                    tool_name=step_data.get('tool_id', ''),
                    tool_params=step_data.get('params', {}),
                    expected_result=""
                )
                procedure_steps.append(step)

            # 2. 创建 Procedure
            procedure = Procedure(
                procedure_id=task_description,  # 用任务描述作为ID
                name=task_description,
                description=f"LLM 生成的流程: {task_description}",
                steps=procedure_steps,
                source="llm_generated",  # 标记来源
                metadata={
                    "created_at": time.time(),
                    "success": success,
                    "success_rate": 1.0 if success else 0.0,
                    "execution_count": 1,
                    **(metadata or {})
                }
            )

            # 3. 保存到 Library
            self._procedure_library.save_procedure(procedure)

            logger.info(f"[ProcedureLearning] 流程已保存: {task_description} "
                       f"({len(steps)} 步骤)")
            return procedure.procedure_id

        except Exception as e:
            logger.error(f"[ProcedureLearning] 保存流程失败: {e}")
            return None

    def update_procedure_success_rate(self, task_description: str, success: bool):
        """
        【新增】更新流程的成功率

        每次执行后调用，用于统计成功率
        """
        if not self._procedure_library:
            return

        try:
            procedure = self._procedure_library.get_procedure(task_description)
            if procedure:
                # 更新成功率（滑动平均）
                old_rate = procedure.metadata.get("success_rate", 0.5)
                old_count = procedure.metadata.get("execution_count", 0)

                new_count = old_count + 1
                new_rate = (old_rate * old_count + (1.0 if success else 0.0)) / new_count

                procedure.metadata["success_rate"] = new_rate
                procedure.metadata["execution_count"] = new_count

                self._procedure_library.save_procedure(procedure)

                logger.debug(f"[ProcedureLearning] 流程 {task_description} "
                            f"成功率更新: {old_rate:.2f} -> {new_rate:.2f}")
        except Exception as e:
            logger.error(f"[ProcedureLearning] 更新成功率失败: {e}")

    async def find_similar_procedures(self, task_description: str, top_k: int = 3) -> list[dict]:
        """
        【新增】语义搜索相似的流程

        不是精确匹配，而是找语义相似的任务

        Args:
            task_description: 任务描述
            top_k: 返回最相似的个数

        Returns:
            相似流程的元数据列表
        """
        if not self._procedure_library:
            return []

        try:
            from core.memory.memory_service import get_memory_service

            ms = await get_memory_service()

            # 1. 获取所有流程
            all_procedures = self._procedure_library.list_all() if hasattr(
                self._procedure_library, 'list_all') else []

            # 2. 存入向量（如果没有）
            for proc in all_procedures:
                desc = f"{proc.name}: {proc.description}"
                await ms.vector_store.upsert(
                    collection="procedures",
                    doc_id=f"procedure:{proc.procedure_id}",
                    text=desc,
                    metadata={
                        "id": proc.procedure_id,
                        "success_rate": proc.metadata.get("success_rate", 0.5),
                        "step_count": len(proc.steps)
                    }
                )

            # 3. 语义检索
            results = await ms.vector_store.search(
                collection="procedures",
                query=task_description,
                limit=top_k
            )

            return [r.metadata for r in results if (1.0 - (r.distance or 0.0)) > 0.7]
        except Exception as e:
            logger.error(f"[ProcedureLearning] 语义搜索失败: {e}")
            return []


# 全局实例
_integration_instance: ProcedureLearningIntegration | None = None
_integration_lock = threading.Lock()


def get_procedure_learning_integration() -> ProcedureLearningIntegration:
    """获取全局演示学习系统集成实例"""
    global _integration_instance
    if _integration_instance is None:
        with _integration_lock:
            if _integration_instance is None:
                _integration_instance = ProcedureLearningIntegration()
    return _integration_instance
