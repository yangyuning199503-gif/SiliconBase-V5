#!/usr/bin/env python3
"""
Task Pause Manager - SiliconBase V5
[Refactored] Migrated from agent_loop.py

Responsibilities:
- Task pause with synchronization
- Phase anchors sync to task state
- Long task state machine integration
"""

from typing import Any

from core.logger import logger

try:
    from core.intervention.intervention_sync import sync
    INTERVENTION_SYNC_AVAILABLE = True
except ImportError:
    INTERVENTION_SYNC_AVAILABLE = False
    sync = None



async def pause_task_with_sync(
    task_state,
    working_memory,
    reason: str = "用户暂停",
    session_id: str = None
) -> dict:
    """
    Pause task and sync phase_anchors to task_state

    [Critical Fix] Before pausing task, sync phase_anchors from working_memory to
    task_state to ensure data integrity on resume.

    Args:
        task_state: Task execution state object
        working_memory: Working memory object
        reason: Pause reason
        session_id: Session ID (for sending events)

    Returns:
        dict: Pause result with success, task_id, checkpoint_id, etc.
    """
    try:
        if not task_state:
            logger.error("[PauseManager] No running task to pause")
            return {"success": False, "error": "没有正在运行的任务"}

        # [Critical Fix] Sync phase_anchors to task_state
        if working_memory and hasattr(working_memory, 'phase_anchors') and working_memory.phase_anchors:
            task_state.phase_anchors = working_memory.phase_anchors
            logger.info(f"[PauseManager] Synced {len(task_state.phase_anchors)} phase anchors to task_state")
        else:
            logger.debug("[PauseManager] working_memory has no phase_anchors or is empty")

        # Call checkpoint_manager to pause task
        try:
            from core.agent.checkpoint_manager import checkpoint_manager
        except ImportError:
            logger.error("[PauseManager] checkpoint_manager 模块未加载")
            return {"success": False, "error": "checkpoint_manager 模块未加载"}

        if checkpoint_manager is None:
            logger.error("[PauseManager] checkpoint_manager 未初始化")
            return {"success": False, "error": "checkpoint_manager 未初始化"}

        state = await checkpoint_manager.pause_task(
            task_id=task_state.task_id,
            reason=reason
        )

        logger.info(f"[PauseManager] Task paused: task_id={task_state.task_id}, reason={reason}")

        # Notify frontend
        if session_id and sync and INTERVENTION_SYNC_AVAILABLE:
            sync.emit_event("task_paused", session_id, {
                "task_id": task_state.task_id,
                "reason": reason,
                "current_step": state.current_step_number,
                "phase_count": len(task_state.phase_anchors) if task_state.phase_anchors else 0
            })

        return {
            "success": True,
            "task_id": task_state.task_id,
            "reason": reason,
            "current_step": state.current_step_number,
            "phase_count": len(task_state.phase_anchors) if task_state.phase_anchors else 0
        }

    except Exception as e:
        logger.error(f"[PauseManager] Failed to pause task: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


def is_long_task(task: Any) -> bool:
    """
    Check if a task is marked as a long-running task

    Args:
        task: Task object with optional metadata

    Returns:
        bool: True if task is a long task
    """
    if not hasattr(task, 'metadata'):
        return False
    return task.metadata.get("is_long_task", False)


def register_long_task_callbacks(task: Any, callbacks: dict) -> bool:
    """
    Register callbacks for long task state changes

    Args:
        task: Task object
        callbacks: Dictionary of callback functions

    Returns:
        bool: True if registration succeeded
    """
    try:
        # 真实可暂停任务状态机位于 core.task.long_running_manager
        # 当前 PausableTaskStateMachine 未提供 register_callback 能力，因此本函数仅做登记声明
        logger.info(
            f"[PauseManager] Long task callbacks registration requested for task {task.id}, "
            f"but PausableTaskStateMachine currently does not support callback registration. "
            f"Requested callbacks: {list(callbacks.keys())}"
        )
        return False

    except Exception as e:
        logger.error(f"[PauseManager] Failed to register callbacks: {e}", exc_info=True)
        return False


__all__ = [
    'pause_task_with_sync',
    'is_long_task',
    'register_long_task_callbacks',
]
