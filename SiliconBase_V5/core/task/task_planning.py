#!/usr/bin/env python3
"""
TaskPlanning - 三省六部流程透视镜 + 任务步骤推断
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
从 agent_loop.py 抽取的任务规划与前端事件发送逻辑。

职责：
- 从用户指令推断任务步骤
- 发送任务拆解事件到前端
- 发送工具链规划事件到前端
- 发送用户确认请求到前端

设计约束：
1. 所有阻塞 I/O 操作均提供 async 版本。
2. 失败降级不抛异常到主循环。
"""

from typing import Any

from core.logger import logger

try:
    from core.sync.realtime_sync import get_realtime_sync_manager
    SYNC_AVAILABLE = True
except ImportError:
    SYNC_AVAILABLE = False


def infer_task_steps(instruction: str) -> list[dict[str, Any]]:
    """从用户指令推断任务步骤"""
    steps = []

    if "打开" in instruction or "启动" in instruction:
        steps.append({"id": 1, "name": "打开应用", "tool": "launch_app", "status": "pending"})
    if "搜索" in instruction or "查找" in instruction:
        steps.append({"id": 2, "name": "搜索内容", "tool": "search", "status": "pending"})
    if "点击" in instruction or "选择" in instruction:
        steps.append({"id": 3, "name": "执行点击操作", "tool": "mouse_click", "status": "pending"})
    if "输入" in instruction or "填写" in instruction:
        steps.append({"id": 4, "name": "输入内容", "tool": "type_text", "status": "pending"})
    if "截图" in instruction or "识别" in instruction:
        steps.append({"id": 5, "name": "识别界面", "tool": "window_ocr", "status": "pending"})

    if not steps:
        steps = [
            {"id": 1, "name": "分析用户需求", "tool": "analyze", "status": "pending"},
            {"id": 2, "name": "执行任务", "tool": "execute", "status": "pending"},
            {"id": 3, "name": "返回结果", "tool": "finalize", "status": "pending"}
        ]

    return steps


def send_task_breakdown(session_id: str, task_instruction: str, steps: list[dict[str, Any]]) -> None:
    """发送任务拆解事件到前端（同步版）"""
    if not SYNC_AVAILABLE:
        return
    try:
        sync = get_realtime_sync_manager()
        sync.emit_event("task_breakdown", session_id, {
            "instruction": task_instruction,
            "steps": steps
        })
        logger.info(f"[TaskPlanning] 任务拆解已发送: {len(steps)} 步骤")
    except Exception as e:
        logger.error(f"[TaskPlanning] 发送task_breakdown事件失败: {e}")


async def send_task_breakdown_async(session_id: str, task_instruction: str, steps: list[dict[str, Any]]) -> None:
    """发送任务拆解事件到前端（异步版）"""
    if not SYNC_AVAILABLE:
        return
    try:
        sync = get_realtime_sync_manager()
        sync.emit_event("task_breakdown", session_id, {
            "instruction": task_instruction,
            "steps": steps
        })
        logger.info(f"[TaskPlanning] 任务拆解已发送(async): {len(steps)} 步骤")
    except Exception as e:
        logger.error(f"[TaskPlanning] 发送task_breakdown事件失败(async): {e}")


def send_tool_chain_planned(session_id: str, chain: list[dict[str, Any]]) -> None:
    """发送工具链规划事件到前端（同步版）"""
    if not SYNC_AVAILABLE:
        return
    try:
        sync = get_realtime_sync_manager()
        sync.emit_event("tool_chain_planned", session_id, {"chain": chain})
        logger.info(f"[TaskPlanning] 工具链规划已发送: {len(chain)} 节点")
    except Exception as e:
        logger.error(f"[TaskPlanning] 发送tool_chain_planned事件失败: {e}")


async def send_tool_chain_planned_async(session_id: str, chain: list[dict[str, Any]]) -> None:
    """发送工具链规划事件到前端（异步版）"""
    if not SYNC_AVAILABLE:
        return
    try:
        sync = get_realtime_sync_manager()
        sync.emit_event("tool_chain_planned", session_id, {"chain": chain})
        logger.info(f"[TaskPlanning] 工具链规划已发送(async): {len(chain)} 节点")
    except Exception as e:
        logger.error(f"[TaskPlanning] 发送tool_chain_planned事件失败(async): {e}")


def request_user_confirmation(
    session_id: str,
    step: str,
    tool: str,
    params: dict[str, Any],
    risk_level: str = "medium",
    timeout: int = 30,
) -> None:
    """发送用户确认请求到前端（同步版）"""
    if not SYNC_AVAILABLE:
        return
    try:
        sync = get_realtime_sync_manager()
        sync.emit_event("user_confirmation_required", session_id, {
            "step": step,
            "tool": tool,
            "params": params,
            "risk_level": risk_level,
            "timeout": timeout
        })
        logger.info(f"[TaskPlanning] 用户确认请求已发送: {step} (风险: {risk_level})")
    except Exception as e:
        logger.error(f"[TaskPlanning] 发送user_confirmation_required事件失败: {e}")


async def request_user_confirmation_async(
    session_id: str,
    step: str,
    tool: str,
    params: dict[str, Any],
    risk_level: str = "medium",
    timeout: int = 30,
) -> None:
    """发送用户确认请求到前端（异步版）"""
    if not SYNC_AVAILABLE:
        return
    try:
        sync = get_realtime_sync_manager()
        sync.emit_event("user_confirmation_required", session_id, {
            "step": step,
            "tool": tool,
            "params": params,
            "risk_level": risk_level,
            "timeout": timeout
        })
        logger.info(f"[TaskPlanning] 用户确认请求已发送(async): {step} (风险: {risk_level})")
    except Exception as e:
        logger.error(f"[TaskPlanning] 发送user_confirmation_required事件失败(async): {e}")
