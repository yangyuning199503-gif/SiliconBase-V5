#!/usr/bin/env python3
"""
父代理干预 API

为前端提供统一的代理任务操作入口：
- POST /api/agent/intervene
- POST /api/agent/mode
- GET  /api/agent/status
- POST /api/agent/instruction

后端实际委托给 TaskQueue / TaskScheduler 等现有模块。
"""


from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core.logger import logger

# 认证依赖
try:
    from api.cloud_api import get_current_user
    AUTH_AVAILABLE = True
except ImportError:
    AUTH_AVAILABLE = False

if not AUTH_AVAILABLE:
    async def _fallback_user():
        return "default"
    get_current_user = _fallback_user

router = APIRouter(prefix="/agent", tags=["agent"])

# ============================================================================
# 数据模型
# ============================================================================

class AgentInterveneRequest(BaseModel):
    task_id: str = Field(..., description="任务ID")
    type: str = Field(..., description="干预类型: PAUSE | RESUME | CANCEL")


class AgentModeRequest(BaseModel):
    task_id: str = Field(..., description="任务ID")
    mode: str = Field(..., description="目标模式: fast | slow | interactive")


class AgentInstructionRequest(BaseModel):
    task_id: str = Field(..., description="任务ID")
    instruction: str = Field(..., description="追加指令")


class AgentInterventionResponse(BaseModel):
    success: bool
    message: str
    status: str | None = None


class AgentTaskInfo(BaseModel):
    task_id: str
    status: str
    mode: str | None = None
    progress: float | None = None
    current_step: str | None = None
    subtasks: list | None = None


# ============================================================================
# 内部辅助
# ============================================================================

def _get_task_queue():
    from core.task.task_queue import task_queue
    return task_queue


def _get_task_scheduler():
    from core.task.task_scheduler import get_task_scheduler
    return get_task_scheduler()


async def _intervene_task(task_id: str, action: str) -> dict:
    """对任务执行暂停/恢复/取消操作"""
    queue = _get_task_queue()
    scheduler = _get_task_scheduler()

    action = action.upper()
    success = False

    if action == "PAUSE":
        success = await queue.pause_task_async(task_id, reason="user_pause")
        if not success:
            success = await scheduler.pause_task(task_id)
    elif action == "RESUME":
        success = await queue.resume_task_async(task_id)
        if not success:
            success = await scheduler.resume_task(task_id)
    elif action == "CANCEL":
        success = await queue.cancel_async(task_id)
        if not success:
            success = await scheduler.cancel_task(task_id)
    else:
        raise ValueError(f"无效的干预类型: {action}")

    if not success:
        raise HTTPException(status_code=404, detail=f"未找到任务或操作无效: {task_id}")

    return {
        "success": True,
        "message": f"任务已{ {'PAUSE': '暂停', 'RESUME': '恢复', 'CANCEL': '取消'}[action] }",
        "status": action
    }


async def _get_task_info(task_id: str) -> dict:
    """获取任务状态信息"""
    queue = _get_task_queue()
    scheduler = _get_task_scheduler()

    task = await queue.current_task_async()
    if task and task.id == task_id:
        return {
            "task_id": task.id,
            "status": task.status.value if hasattr(task.status, "value") else str(task.status).lower(),
            "mode": task.metadata.get("mode", "interactive") if task.metadata else "interactive",
            "progress": task.metadata.get("progress") if task.metadata else None,
            "current_step": task.metadata.get("current_step") if task.metadata else None,
            "subtasks": task.metadata.get("subtasks") if task.metadata else None,
        }

    task = await scheduler.get_task(task_id)
    if task:
        return {
            "task_id": task.id,
            "status": task.status.value if hasattr(task.status, "value") else str(task.status).lower(),
            "mode": task.metadata.get("mode", "interactive") if task.metadata else "interactive",
            "progress": task.metadata.get("progress") if task.metadata else None,
            "current_step": task.metadata.get("current_step") if task.metadata else None,
            "subtasks": task.metadata.get("subtasks") if task.metadata else None,
        }

    raise HTTPException(status_code=404, detail=f"未找到任务: {task_id}")


# ============================================================================
# API 端点
# ============================================================================

@router.post("/intervene", response_model=AgentInterventionResponse)
async def intervene(
    request: AgentInterveneRequest,
    user_id: str = Depends(get_current_user)
):
    """提交代理干预请求（暂停/恢复/取消）"""
    try:
        result = await _intervene_task(request.task_id, request.type)
        logger.info(f"[AgentAPI] 用户 {user_id} 干预任务 {request.task_id}: {request.type}")
        return AgentInterventionResponse(**result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[AgentAPI] 干预失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"干预失败: {e}") from e


@router.post("/mode", response_model=AgentInterventionResponse)
async def switch_mode(
    request: AgentModeRequest,
    user_id: str = Depends(get_current_user)
):
    """切换代理任务模式"""
    try:
        queue = _get_task_queue()
        task = await queue.current_task_async()
        if task and task.id == request.task_id:
            if not task.metadata:
                task.metadata = {}
            task.metadata["mode"] = request.mode
            return AgentInterventionResponse(
                success=True,
                message=f"任务模式已切换为 {request.mode}",
                status=request.mode
            )

        scheduler = _get_task_scheduler()
        task = await scheduler.get_task(request.task_id)
        if task:
            if not task.metadata:
                task.metadata = {}
            task.metadata["mode"] = request.mode
            return AgentInterventionResponse(
                success=True,
                message=f"任务模式已切换为 {request.mode}",
                status=request.mode
            )

        raise HTTPException(status_code=404, detail=f"未找到任务: {request.task_id}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[AgentAPI] 切换模式失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"切换模式失败: {e}") from e


@router.get("/status", response_model=AgentTaskInfo)
async def get_status(
    task_id: str = Query(..., description="任务ID"),
    user_id: str = Depends(get_current_user)
):
    """获取代理任务状态"""
    return await _get_task_info(task_id)


@router.post("/instruction", response_model=AgentInterventionResponse)
async def append_instruction(
    request: AgentInstructionRequest,
    user_id: str = Depends(get_current_user)
):
    """向运行中的任务追加指令"""
    try:
        queue = _get_task_queue()
        task = await queue.current_task_async()
        if task and task.id == request.task_id:
            if not task.metadata:
                task.metadata = {}
            pending = task.metadata.get("pending_instructions", [])
            pending.append(request.instruction)
            task.metadata["pending_instructions"] = pending
            return AgentInterventionResponse(
                success=True,
                message="指令已追加到当前任务"
            )

        scheduler = _get_task_scheduler()
        task = await scheduler.get_task(request.task_id)
        if task:
            if not task.metadata:
                task.metadata = {}
            pending = task.metadata.get("pending_instructions", [])
            pending.append(request.instruction)
            task.metadata["pending_instructions"] = pending
            return AgentInterventionResponse(
                success=True,
                message="指令已追加到任务"
            )

        raise HTTPException(status_code=404, detail=f"未找到任务: {request.task_id}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[AgentAPI] 追加指令失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"追加指令失败: {e}") from e
