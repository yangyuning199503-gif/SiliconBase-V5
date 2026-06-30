#!/usr/bin/env python3
"""
InterventionChecker - 实时干预系统异步化封装
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
从 agent_loop.py 抽取的实时干预检查与处理逻辑。

职责：
- 检查并应用用户实时干预
- 封装 PAUSE / ADJUST / PIVOT / REPLAN 等干预类型的完整处理链路
- 提供同步/异步双入口

设计约束：
1. 不持有 agent_loop 的状态，只通过参数接收上下文。
2. 异步版对阻塞调用使用 run_in_executor 桥接。
3. 任何步骤失败均降级处理，禁止抛异常到主循环。
"""

import contextlib
from typing import Any

from core.logger import logger

try:
    from core.agent.realtime_intervention import (
        ExecutionAdaptation,
        check_and_apply_intervention,
        realtime_intervention,
    )
    REALTIME_INTERVENTION_AVAILABLE = True
except ImportError as e:
    REALTIME_INTERVENTION_AVAILABLE = False
    logger.error(f"[InterventionChecker] 实时干预系统导入失败: {e}")


class InterventionResult:
    """干预检查结果"""

    def __init__(
        self,
        has_intervention: bool = False,
        adaptation_type: str = "",
        details: dict | None = None,
        handled: bool = False,
        should_return: bool = False,
        return_value: str | None = None,
    ):
        self.has_intervention = has_intervention
        self.adaptation_type = adaptation_type
        self.details = details or {}
        self.handled = handled
        self.should_return = should_return
        self.return_value = return_value


class InterventionChecker:
    """实时干预检查器（同步/异步双入口）"""

    def __init__(self):
        pass

    def _check(
        self,
        task_id: str | None,
        current_working_memory: list[dict],
        current_plan: list | None,
    ) -> tuple[bool, str, dict]:
        """底层检查：调用 realtime_intervention。"""
        if not REALTIME_INTERVENTION_AVAILABLE or not task_id:
            return False, "", {}
        try:
            return check_and_apply_intervention(
                task_id=task_id,
                current_working_memory=current_working_memory,
                current_plan=current_plan,
            )
        except Exception as e:
            logger.warning(f"[InterventionChecker] 干预检查失败: {e}")
            return False, "", {}

    def check_and_apply(
        self,
        task_id: str | None,
        working_memory: Any,
        session_id: str,
        current_plan: list | None = None,
        pausable_task_sm: Any = None,
        state_persistence: Any = None,
        state: Any = None,
    ) -> InterventionResult:
        """
        同步版：检查并应用干预。

        返回 InterventionResult：
        - should_return=True 时，主循环应立即返回 return_value。
        - handled=True 表示干预已被处理（如注入工作记忆、发送事件等）。
        """
        has_intervention, adaptation_type, details = self._check(
            task_id=task_id,
            current_working_memory=getattr(working_memory, "_message_history", []) if working_memory else [],
            current_plan=current_plan,
        )

        if not has_intervention:
            return InterventionResult(has_intervention=False)

        logger.info(f"[InterventionChecker] 检测到干预: {adaptation_type}")
        result = InterventionResult(
            has_intervention=True,
            adaptation_type=adaptation_type,
            details=details,
            handled=True,
        )

        try:
            from core.sync.realtime_sync import get_realtime_sync_manager
            sync = get_realtime_sync_manager()
        except Exception:
            sync = None

        # ── PAUSE ────────────────────────────────────────────────────────────
        if adaptation_type == ExecutionAdaptation.PAUSE.name:
            if pausable_task_sm is not None:
                try:
                    pausable_task_sm.pause(reason=details.get("reason", "用户请求暂停"), trigger="user")
                except Exception as e:
                    logger.warning(f"[InterventionChecker] 暂停任务失败: {e}")
            if state_persistence is not None and state is not None:
                try:
                    state_persistence.save(state)
                except Exception as e:
                    logger.warning(f"[InterventionChecker] 保存状态失败: {e}")
            if sync is not None:
                try:
                    sync.emit_event("intervention_applied", session_id, {
                        "type": "PAUSE",
                        "message": "任务已暂停",
                    })
                except Exception as e:
                    logger.warning(f"[InterventionChecker] 发送事件失败: {e}")
            result.should_return = True
            result.return_value = "任务已暂停"
            return result

        # ── ADJUST_APPROACH ──────────────────────────────────────────────────
        if adaptation_type == ExecutionAdaptation.ADJUST_APPROACH.name:
            intervention_msg = details.get("reason", "")
            if working_memory is not None:
                working_memory.append({
                    "role": "system",
                    "content": f"【用户反馈】{intervention_msg}\n请根据用户反馈调整执行方式。",
                })
            if sync is not None:
                with contextlib.suppress(Exception):
                    sync.emit_event("intervention_applied", session_id, {
                        "type": "ADJUST",
                        "message": "已调整执行方式",
                    })
            self._record_adaptation(task_id, adaptation_type, details)
            return result

        # ── PIVOT ────────────────────────────────────────────────────────────
        if adaptation_type == ExecutionAdaptation.PIVOT.name:
            new_goal = details.get("new_goal", "")
            if working_memory is not None:
                working_memory.append({
                    "role": "system",
                    "content": f"【目标调整】{new_goal}\n目标已调整，请重新规划执行步骤。",
                })
                if hasattr(working_memory, "ai_plan"):
                    working_memory.ai_plan = None
            if sync is not None:
                with contextlib.suppress(Exception):
                    sync.emit_event("intervention_applied", session_id, {
                        "type": "PIVOT",
                        "message": "目标已切换",
                    })
            self._record_adaptation(task_id, adaptation_type, details)
            return result

        # ── REPLAN ───────────────────────────────────────────────────────────
        if adaptation_type == ExecutionAdaptation.REPLAN.name:
            intervention_msg = details.get("reason", "")
            if working_memory is not None:
                working_memory.append({
                    "role": "system",
                    "content": f"【重新规划】{intervention_msg}\n请基于已完成的工作，重新规划后续步骤。",
                })
                if hasattr(working_memory, "execution_plan"):
                    working_memory.execution_plan = None
                if hasattr(working_memory, "ai_plan"):
                    working_memory.ai_plan = None
            if sync is not None:
                with contextlib.suppress(Exception):
                    sync.emit_event("intervention_applied", session_id, {
                        "type": "REPLAN",
                        "message": "已重新规划",
                    })
            self._record_adaptation(task_id, adaptation_type, details)
            return result

        # 其他类型仅记录
        self._record_adaptation(task_id, adaptation_type, details)
        return result

    async def check_and_apply_async(
        self,
        task_id: str | None,
        working_memory: Any,
        session_id: str,
        current_plan: list | None = None,
        pausable_task_sm: Any = None,
        state_persistence: Any = None,
        state: Any = None,
    ) -> InterventionResult:
        """异步版：直接调用（check_and_apply 是纯内存操作，无需线程池）"""
        return self.check_and_apply(
            task_id,
            working_memory,
            session_id,
            current_plan,
            pausable_task_sm,
            state_persistence,
            state,
        )

    def _record_adaptation(
        self,
        task_id: str | None,
        adaptation_type: str,
        details: dict,
    ) -> None:
        """记录变更历史到 realtime_intervention。"""
        if not REALTIME_INTERVENTION_AVAILABLE or not task_id:
            return
        try:
            adaptation_enum = getattr(ExecutionAdaptation, adaptation_type, None)
            if adaptation_enum is not None:
                realtime_intervention.apply_adaptation(
                    task_id=task_id,
                    adaptation=adaptation_enum,
                    details=details,
                )
        except Exception as e:
            logger.debug(f"[InterventionChecker] 记录变更历史失败: {e}")


# 全局实例
intervention_checker = InterventionChecker()
