#!/usr/bin/env python3
"""
暂停确认状态机 (Pause Confirmation State Machine)

实现长期任务的强制确认机制：
1. 任务暂停时记录暂停原因和上下文
2. AI必须输出对需求的理解摘要
3. 用户确认理解正确后才能真正恢复
4. 如果理解不正确，继续沟通直到理解正确

状态流转：
    RUNNING -> PAUSED -> AWAITING_CONFIRMATION -> CONFIRMED -> RESUMING -> RUNNING
                          ↑                                    |
                          └────────── 理解不正确 ───────────────┘
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.logger import logger


class PauseConfirmationState(Enum):
    """暂停确认状态"""
    RUNNING = "running"
    PAUSED = "paused"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    CONFIRMED = "confirmed"
    RESUMING = "resuming"


@dataclass
class PauseRecord:
    """暂停记录 - 记录每次暂停的完整信息"""
    pause_id: str
    task_id: str
    session_id: str


    pause_reason: str
    pause_trigger: str
    paused_at: float = field(default_factory=time.time)


    original_requirement: str = ""
    modified_requirement: str = ""
    execution_context: dict[str, Any] = field(default_factory=dict)


    ai_understanding: str = ""
    user_confirmation: bool | None = None
    confirmation_round: int = 0
    communication_history: list[dict[str, Any]] = field(default_factory=list)


    resumed_at: float | None = None
    resume_success: bool | None = None


@dataclass
class UnderstandingSummary:
    """AI理解摘要结构"""
    original_task: str
    current_requirement: str
    key_points: list[str]
    implementation_plan: str
    assumptions: list[str]
    risks: list[str]

    def to_markdown(self) -> str:
        """转换为Markdown格式的理解摘要"""
        lines = [
            "## 🎯 任务理解摘要",
            "",
            f"**原始任务**: {self.original_task}",
            f"**当前需求**: {self.current_requirement}",
            "",
            "## 📋 关键需求点",
        ]
        for i, point in enumerate(self.key_points, 1):
            lines.append(f"{i}. {point}")

        lines.extend([
            "",
            "## 📝 执行计划",
            self.implementation_plan,
            "",
            "## 💡 假设条件",
        ])
        for assumption in self.assumptions:
            lines.append(f"- {assumption}")

        if self.risks:
            lines.extend(["", "## ⚠️ 潜在风险"])
            for risk in self.risks:
                lines.append(f"- {risk}")

        lines.extend([
            "",
            "---",
            "**请确认以上理解是否正确？**",
            "- 回复「确认」或「正确」→ 继续执行任务",
            "- 回复「不对」或「错误」→ 说明问题，我会重新理解",
            "- 直接修改需求 → 我会根据新需求重新理解",
        ])

        return "\n".join(lines)


class PauseConfirmationManager:
    """
    暂停确认状态机管理器

    管理长期任务的暂停-确认-恢复流程
    """


    CONFIRMATION_KEYWORDS = {
        "positive": ["确认", "正确", "对", "是的", "没问题", "继续", "ok", "yes", "正确", "准确"],
        "negative": ["不对", "错误", "不对", "有问题", "重新", "不对", "否", "no", "不准确", "错了"],
    }

    def __init__(self):
        self._pause_records: dict[str, PauseRecord] = {}
        self._current_states: dict[str, PauseConfirmationState] = {}
        self._current_task_id: str | None = None
        self._state_handlers: dict[PauseConfirmationState, Callable] = {
            PauseConfirmationState.PAUSED: self._handle_paused_state,
            PauseConfirmationState.AWAITING_CONFIRMATION: self._handle_awaiting_confirmation,
            PauseConfirmationState.CONFIRMED: self._handle_confirmed_state,
            PauseConfirmationState.RESUMING: self._handle_resuming_state,
        }
        self._max_confirmation_rounds = 5

    def pause_task(
            self,
            task_id: str,
            session_id: str,
            reason: str,
            trigger: str = "ai",
            original_requirement: str = "",
            execution_context: dict[str, Any] | None = None
    ) -> PauseRecord:
        """
        暂停任务并创建暂停记录

        Args:
            task_id: 任务ID
            session_id: 会话ID
            reason: 暂停原因
            trigger: 触发方式 (ai/user/system)
            original_requirement: 原始需求
            execution_context: 执行上下文快照

        Returns:
            PauseRecord: 暂停记录
        """
        pause_id = f"pause_{task_id}_{int(time.time())}"

        record = PauseRecord(
            pause_id=pause_id,
            task_id=task_id,
            session_id=session_id,
            pause_reason=reason,
            pause_trigger=trigger,
            original_requirement=original_requirement,
            execution_context=execution_context or {},
            confirmation_round=0
        )

        self._pause_records[task_id] = record
        self._current_states[task_id] = PauseConfirmationState.PAUSED
        self._current_task_id = task_id

        logger.info(f"[PauseConfirmation] 任务 {task_id} 已暂停，原因: {reason}")

        # 【P3】任务暂停时停止当前语音播报，避免"任务已暂停但语音还在说正在执行"
        try:
            from voice.interface import get_voice_interface
            voice = get_voice_interface()
            if voice and hasattr(voice, "stop_speaking"):
                voice.stop_speaking(clear_unprotected_only=True)
                logger.info("[PauseConfirmation] 已请求停止语音播报")
        except Exception as _voice_e:
            logger.debug(f"[PauseConfirmation] 停止语音失败: {_voice_e}")

        return record

    def submit_understanding(
            self,
            task_id: str,
            understanding: UnderstandingSummary
    ) -> bool:
        """
        提交AI的理解摘要，进入等待确认状态

        Args:
            task_id: 任务ID
            understanding: 理解摘要对象

        Returns:
            bool: 是否成功提交
        """
        if task_id not in self._pause_records:
            logger.error(f"[PauseConfirmation] 任务 {task_id} 没有暂停记录")
            return False

        record = self._pause_records[task_id]
        record.ai_understanding = understanding.to_markdown()
        record.confirmation_round += 1


        record.communication_history.append({
            "round": record.confirmation_round,
            "type": "ai_understanding",
            "content": understanding.to_markdown(),
            "timestamp": time.time()
        })


        self._current_states[task_id] = PauseConfirmationState.AWAITING_CONFIRMATION

        logger.info(f"[PauseConfirmation] 任务 {task_id} 已提交理解，等待用户确认 (第{record.confirmation_round}轮)")

        return True

    def process_user_response(
            self,
            task_id: str,
            user_response: str
    ) -> dict[str, Any]:
        """
        处理用户对理解的响应

        Args:
            task_id: 任务ID
            user_response: 用户响应文本

        Returns:
            Dict: 处理结果，包含:
                - status: "confirmed" | "rejected" | "modified" | "awaiting"
                - message: 处理消息
                - can_resume: 是否可以恢复
                - understanding: 当前理解摘要（如需重新理解）
        """
        if task_id not in self._pause_records:
            return {
                "status": "error",
                "message": "任务没有暂停记录",
                "can_resume": False
            }

        record = self._pause_records[task_id]
        self._current_states.get(task_id)


        record.communication_history.append({
            "round": record.confirmation_round,
            "type": "user_response",
            "content": user_response,
            "timestamp": time.time()
        })


        if record.confirmation_round >= self._max_confirmation_rounds:
            logger.warning(f"[PauseConfirmation] 任务 {task_id} 确认轮次超过限制，强制确认")
            record.user_confirmation = True
            self._current_states[task_id] = PauseConfirmationState.CONFIRMED
            return {
                "status": "confirmed",
                "message": "确认轮次过多，系统已自动确认理解",
                "can_resume": True,
                "forced": True
            }


        response_lower = user_response.lower()


        is_confirmed = any(kw in response_lower for kw in self.CONFIRMATION_KEYWORDS["positive"])
        is_rejected = any(kw in response_lower for kw in self.CONFIRMATION_KEYWORDS["negative"])

        if is_confirmed and not is_rejected:

            record.user_confirmation = True
            self._current_states[task_id] = PauseConfirmationState.CONFIRMED

            logger.info(f"[PauseConfirmation] 任务 {task_id} 用户确认理解正确")

            return {
                "status": "confirmed",
                "message": "理解已确认，可以恢复任务",
                "can_resume": True,
                "record": record
            }

        elif is_rejected:

            record.user_confirmation = False


            logger.info(f"[PauseConfirmation] 任务 {task_id} 用户认为理解不正确，需要重新理解")

            return {
                "status": "rejected",
                "message": "理解不正确，请AI重新理解需求",
                "can_resume": False,
                "need_re_understand": True,
                "record": record
            }

        else:

            record.modified_requirement = user_response
            record.user_confirmation = False

            logger.info(f"[PauseConfirmation] 任务 {task_id} 用户可能修改了需求，需要重新理解")

            return {
                "status": "modified",
                "message": "需求有变更，请AI重新理解",
                "can_resume": False,
                "need_re_understand": True,
                "modified_requirement": user_response,
                "record": record
            }

    def confirm_resume(self, task_id: str) -> bool:
        """
        确认恢复任务（只有用户确认后才能调用）

        Args:
            task_id: 任务ID

        Returns:
            bool: 是否成功恢复
        """
        if task_id not in self._pause_records:
            logger.error(f"[PauseConfirmation] 任务 {task_id} 没有暂停记录")
            return False

        record = self._pause_records[task_id]
        current_state = self._current_states.get(task_id)


        if current_state != PauseConfirmationState.CONFIRMED and record.user_confirmation is not True:
            logger.warning(f"[PauseConfirmation] 任务 {task_id} 未经确认，拒绝恢复")
            return False


        self._current_states[task_id] = PauseConfirmationState.RESUMING
        record.resumed_at = time.time()
        record.resume_success = True

        logger.info(f"[PauseConfirmation] 任务 {task_id} 确认恢复")

        return True

    def complete_resume(self, task_id: str) -> bool:
        """
        完成恢复，状态机回到 RUNNING

        Args:
            task_id: 任务ID

        Returns:
            bool: 是否成功
        """
        if task_id not in self._current_states:
            return False

        self._current_states[task_id] = PauseConfirmationState.RUNNING
        logger.info(f"[PauseConfirmation] 任务 {task_id} 恢复完成，状态: RUNNING")

        return True

    def get_current_state(self, task_id: str) -> PauseConfirmationState | None:
        """获取当前状态"""
        return self._current_states.get(task_id)

    @property
    def state(self) -> PauseConfirmationState:
        """
        获取当前状态（兼容单任务状态机接口）

        返回当前任务的状态，如果没有当前任务则返回 RUNNING
        """
        if self._current_task_id and self._current_task_id in self._current_states:
            return self._current_states[self._current_task_id]

        if self._current_states:
            return list(self._current_states.values())[-1]
        return PauseConfirmationState.RUNNING

    def get_pause_record(self, task_id: str) -> PauseRecord | None:
        """获取暂停记录"""
        return self._pause_records.get(task_id)

    def is_waiting_confirmation(self, task_id: str) -> bool:
        """检查是否正在等待用户确认"""
        state = self._current_states.get(task_id)
        return state == PauseConfirmationState.AWAITING_CONFIRMATION

    def get_pause_prompt(self, task_id: str = None) -> str:
        """
        获取暂停状态下的提示词（给AI的指示）

        Args:
            task_id: 任务ID，默认为None时使用当前任务

        Returns:
            str: 提示词
        """

        if task_id is None:
            task_id = self._current_task_id
        record = self._pause_records.get(task_id)
        if not record:
            return ""

        state = self._current_states.get(task_id)

        if state == PauseConfirmationState.PAUSED:
            return f"""【任务暂停】

任务已被暂停，原因: {record.pause_reason}

请输出对当前需求的完整理解摘要，包含以下部分：
1. 原始任务描述
2. 关键需求点（列出所有关键点）
3. 执行计划概要
4. 你的假设条件
5. 可能的风险点

使用以下格式输出：
(提交理解摘要: 你的理解摘要内容)

注意：
- 必须等待用户确认理解正确后才能输出 (恢复执行)
- 如果用户提出修改，需要重新输出理解摘要
- 只有用户明确确认后才能恢复
"""

        elif state == PauseConfirmationState.AWAITING_CONFIRMATION:
            return """【等待用户确认】

已提交理解摘要，正在等待用户确认。

请等待用户回复：
- 如果用户说"确认"/"正确" → 可以输出 (恢复执行)
- 如果用户说"不对"/"错误" → 需要重新输出理解摘要
- 如果用户修改需求 → 根据新需求重新输出理解摘要

注意：必须获得用户明确确认后才能恢复执行！
"""

        elif state == PauseConfirmationState.CONFIRMED:
            return """【理解已确认】

用户已确认理解正确，现在可以恢复任务执行。

请输出: (恢复执行)
"""

        return ""

    def _handle_paused_state(self, task_id: str, context: dict[str, Any]) -> dict[str, Any]:
        """处理 PAUSED 状态"""
        return {
            "action": "request_understanding",
            "message": "请AI输出理解摘要"
        }

    def _handle_awaiting_confirmation(self, task_id: str, context: dict[str, Any]) -> dict[str, Any]:
        """处理 AWAITING_CONFIRMATION 状态"""
        return {
            "action": "wait_user_response",
            "message": "等待用户确认理解"
        }

    _handle_confirmed_state = _handle_paused_state
    _handle_resuming_state = _handle_paused_state

    def get_resume_requirement_prompt(self, task_id: str) -> str:
        """
        获取恢复前的强制确认提示词

        Args:
            task_id: 任务ID

        Returns:
            str: 提示词
        """
        record = self._pause_records.get(task_id)
        if not record:
            return ""


        return f"""【强制确认机制】

在恢复任务之前，请严格按照以下步骤执行：

1️⃣ **理解摘要**
   - 原始需求: {record.original_requirement}
   - 当前需求: {record.modified_requirement or record.original_requirement}

   请输出对需求的完整理解：
   - 任务目标是什么？
   - 关键约束条件有哪些？
   - 预期产出是什么？
   - 有哪些潜在风险？

2️⃣ **用户确认**
   - 输出格式: (提交理解摘要: [你的理解])
   - 等待用户明确回复"确认"或"正确"
   - 如果用户说"不对"或"错误"，必须重新理解

3️⃣ **恢复条件**
   ⚠️ **必须满足以下条件才能输出 (恢复执行)：**
   - 用户明确说"确认"/"正确"/"没问题"等
   - 用户没有提出任何疑问或修改
   - 理解摘要已完整输出并得到确认

4️⃣ **禁止行为**
   ❌ 未经确认直接输出 (恢复执行)
   ❌ 忽略用户的修改意见
   ❌ 擅自假设用户会同意

当前状态: {self._current_states.get(task_id, 'UNKNOWN').value}
暂停原因: {record.pause_reason}
确认轮次: {record.confirmation_round}
"""

    def cleanup_task(self, task_id: str):
        """清理任务的暂停记录"""
        if task_id in self._pause_records:
            del self._pause_records[task_id]
        if task_id in self._current_states:
            del self._current_states[task_id]
        logger.info(f"[PauseConfirmation] 清理任务 {task_id} 的暂停记录")

    def get_statistics(self) -> dict[str, Any]:
        """获取统计信息"""
        total = len(self._pause_records)
        state_counts = {}
        for state in self._current_states.values():
            state_counts[state.value] = state_counts.get(state.value, 0) + 1

        return {
            "total_paused_tasks": total,
            "state_distribution": state_counts,
            "awaiting_confirmation": len([
                t for t, s in self._current_states.items()
                if s == PauseConfirmationState.AWAITING_CONFIRMATION
            ])
        }





    def register_state_change_callback(self, callback: Callable):
        """注册状态变更回调（当前为空实现，为兼容性保留）"""

        pass

    def pause(self, reason: str = "", trigger: str = "ai") -> Any:
        """
        暂停当前任务（兼容旧接口）

        Args:
            reason: 暂停原因
            trigger: 触发方式 (ai/user/system)

        Returns:
            PauseRecord: 暂停记录
        """
        if not self._current_task_id:

            self._current_task_id = f"task_{int(time.time())}"

        return self.pause_task(
            task_id=self._current_task_id,
            session_id="default_session",
            reason=reason,
            trigger=trigger
        )

    async def pause_async(self, reason: str = "", trigger: str = "ai") -> Any:
        """
        异步暂停当前任务

        Args:
            reason: 暂停原因
            trigger: 触发方式 (ai/user/system)

        Returns:
            PauseRecord: 暂停记录
        """
        return self.pause(reason, trigger)

    def resume(self, by_user: bool = True) -> dict[str, Any] | None:
        """
        恢复任务（兼容旧接口）

        Args:
            by_user: 是否由用户触发

        Returns:
            Dict: 恢复上下文，如果无法恢复则返回None
        """
        if not self._current_task_id:
            return None

        if self.confirm_resume(self._current_task_id):
            record = self.get_pause_record(self._current_task_id)
            if record:
                return {
                    "task_id": self._current_task_id,
                    "record": record,
                    "by_user": by_user
                }
        return None

    def get_resume_prompt(self, resume_context: dict[str, Any] = None) -> str:
        """
        获取恢复提示词（兼容旧接口）

        Args:
            resume_context: 恢复上下文（可选）

        Returns:
            str: 恢复提示词
        """
        task_id = self._current_task_id
        if resume_context and "task_id" in resume_context:
            task_id = resume_context["task_id"]
        return self.get_resume_requirement_prompt(task_id)

    def confirm_ai_understanding(self, understanding: Any) -> bool:
        """
        确认AI理解（兼容旧接口）

        Args:
            understanding: AI理解摘要（可以是UnderstandingSummary或字符串）

        Returns:
            bool: 是否成功提交
        """
        if not self._current_task_id:
            return False


        if isinstance(understanding, str):
            understanding = UnderstandingSummary(
                original_task=understanding,
                current_requirement=understanding,
                key_points=[],
                implementation_plan="",
                assumptions=[],
                risks=[]
            )

        return self.submit_understanding(self._current_task_id, understanding)

    async def confirm_ai_understanding_async(self, understanding: Any) -> bool:
        """
        异步确认AI理解

        Args:
            understanding: AI理解摘要（可以是UnderstandingSummary或字符串）

        Returns:
            bool: 是否成功提交
        """
        return self.confirm_ai_understanding(understanding)

    def process_user_confirmation(self, user_response: str) -> dict[str, Any]:
        """
        处理用户确认（兼容旧接口）

        Args:
            user_response: 用户响应文本

        Returns:
            Dict: 处理结果
        """
        if not self._current_task_id:
            return {
                "status": "error",
                "message": "没有当前任务",
                "can_resume": False
            }
        return self.process_user_response(self._current_task_id, user_response)

    def can_resume(self, task_id: str = None) -> bool:
        """
        检查是否可以恢复任务（兼容旧接口，task_id可选）

        Args:
            task_id: 任务ID（可选，默认使用当前任务）

        Returns:
            bool: 是否可以恢复
        """
        tid = task_id or self._current_task_id
        if not tid:
            return False

        state = self._current_states.get(tid)
        record = self._pause_records.get(tid)

        if state == PauseConfirmationState.CONFIRMED:
            return True
        return bool(record and record.user_confirmation is True)



_pause_confirmation_manager: PauseConfirmationManager | None = None


LongTaskStateMachine = PauseConfirmationManager
LongTaskState = PauseConfirmationState


LongTaskState.AWAITING_REQUIREMENTS = PauseConfirmationState.AWAITING_CONFIRMATION
LongTaskState.READY_TO_RESUME = PauseConfirmationState.CONFIRMED


def get_pause_confirmation_manager() -> PauseConfirmationManager:
    """获取全局暂停确认管理器"""
    global _pause_confirmation_manager
    if _pause_confirmation_manager is None:
        _pause_confirmation_manager = PauseConfirmationManager()
    return _pause_confirmation_manager


def reset_pause_confirmation_manager():
    """重置全局实例（主要用于测试）"""
    global _pause_confirmation_manager
    _pause_confirmation_manager = None
