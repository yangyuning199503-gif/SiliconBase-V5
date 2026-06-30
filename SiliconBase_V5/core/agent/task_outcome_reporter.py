"""
TaskOutcomeReporter - 把 AgentLoop 的任务结果发布到 ExperienceBus。

这是 AgentLoop → ExperienceBus → FeedbackCollector 反馈闭环的“硬连接”。
直接发布到当前用户的 Consciousness 经验总线，保证用户隔离，避免与全局单例混淆。
"""
from __future__ import annotations

import time
from typing import Any


class TaskOutcome:
    """可观测的任务结果摘要"""

    def __init__(
        self,
        user_id: str,
        session_id: str,
        task_id: str | None,
        user_instruction: str,
        completed: bool,
        tool_success_rate: float = 0.0,
        duration_seconds: float = 0.0,
        error: str | None = None,
        active_goal_id: str | None = None,
        execution_history_count: int = 0,
        final_answer_length: int = 0,
    ):
        self.user_id = user_id
        self.session_id = session_id
        self.task_id = task_id
        self.user_instruction = user_instruction
        self.completed = completed
        self.tool_success_rate = tool_success_rate
        self.duration_seconds = duration_seconds
        self.error = error
        self.active_goal_id = active_goal_id
        self.execution_history_count = execution_history_count
        self.final_answer_length = final_answer_length


def _calc_tool_success_rate(execution_history: list[dict[str, Any]]) -> float:
    """从执行历史中计算工具成功率（0~1）。"""
    if not execution_history:
        return 0.0
    total = len(execution_history)
    successes = sum(1 for h in execution_history if h.get("success", False))
    return successes / total


def _compute_outcome_score(
    completed: bool,
    tool_success_rate: float,
    duration_seconds: float,
    error: str | None,
) -> float:
    """
    把可观测指标映射为 0~1 的 outcome 分数。

    - 未完成任务：0.0
    - 完成但报错：0.2
    - 完成：base = 0.5 + 0.3 * tool_success_rate
      - 长耗时（>120s）且工具未全成功：-0.1
    """
    if not completed:
        return 0.0
    if error:
        return 0.2
    base = 0.5 + 0.3 * tool_success_rate
    if duration_seconds > 120.0 and tool_success_rate < 1.0:
        base -= 0.1
    return max(0.0, min(1.0, base))


def _extract_user_instruction(task: Any) -> str:
    """从 task 对象提取用户指令。"""
    if not task:
        return ""
    if hasattr(task, "user_instruction"):
        return str(getattr(task, "user_instruction", "") or "")
    intent = getattr(task, "intent", None) or {}
    if isinstance(intent, dict):
        return str(intent.get("raw", "") or "")
    return ""


async def report_task_completed(
    actual_user_id: str,
    session_id: str,
    task: Any,
    user_instruction: str,
    active_goal: Any,
    execution_history: list[dict[str, Any]],
    loop_start_time: float,
    final_answer: str = "",
) -> None:
    """在任务正常结束时发布 outcome 事件。"""
    try:
        from core.consciousness.Consciousness import get_consciousness
        from core.consciousness.experience_bus import ExperienceEvent
        from core.strategy.goal_system import get_goal_system

        if not user_instruction:
            user_instruction = _extract_user_instruction(task)

        duration = max(0.0, time.time() - loop_start_time)
        tool_success_rate = _calc_tool_success_rate(execution_history)
        outcome = _compute_outcome_score(
            completed=True,
            tool_success_rate=tool_success_rate,
            duration_seconds=duration,
            error=None,
        )

        consciousness = get_consciousness(actual_user_id)
        bus = getattr(consciousness, "experience_bus", None) if consciousness else None
        if bus is None:
            return

        if active_goal is None:
            try:
                active_goal = get_goal_system().get_top_priority_goal()
            except Exception:
                active_goal = None

        event = ExperienceEvent(
            source="agent_loop",
            event_type="task_completed",
            context={
                "task_id": task.id if task and hasattr(task, "id") else None,
                "session_id": session_id,
                "user_id": actual_user_id,
                "user_instruction": user_instruction,
                "active_goal_id": active_goal.goal_id if active_goal and hasattr(active_goal, "goal_id") else None,
                "tool_success_rate": tool_success_rate,
                "duration_seconds": duration,
            },
            action=user_instruction[:200],
            outcome=outcome,
            weight=1.0,
            raw_data={
                "execution_history_count": len(execution_history),
                "final_answer_length": len(final_answer),
            },
        )
        await bus.publish(event)
    except Exception:
        # 经验总线失败不得影响主循环
        pass


async def report_task_failed(
    actual_user_id: str,
    session_id: str,
    task: Any,
    user_instruction: str,
    loop_error: str,
) -> None:
    """在任务异常结束时发布 outcome 事件。"""
    try:
        from core.consciousness.Consciousness import get_consciousness
        from core.consciousness.experience_bus import ExperienceEvent

        if not user_instruction:
            user_instruction = _extract_user_instruction(task)

        consciousness = get_consciousness(actual_user_id)
        bus = getattr(consciousness, "experience_bus", None) if consciousness else None
        if bus is None:
            return

        event = ExperienceEvent(
            source="agent_loop",
            event_type="task_failed",
            context={
                "task_id": task.id if task and hasattr(task, "id") else None,
                "session_id": session_id,
                "user_id": actual_user_id,
                "error_type": "AgentLoopError",
            },
            action=user_instruction[:200] if user_instruction else "",
            outcome=_compute_outcome_score(
                completed=False,
                tool_success_rate=0.0,
                duration_seconds=0.0,
                error=loop_error,
            ),
            weight=1.0,
            raw_data={"error": loop_error},
        )
        await bus.publish(event)
    except Exception:
        pass
