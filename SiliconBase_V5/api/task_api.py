#!/usr/bin/env python3
"""
任务管理 API 模块 V1.1
━━━━━━━━━━━━━━━━━━━━━━━━
提供用户级任务管理 REST API 端点

功能：
  - 任务的 CRUD 操作
  - 依赖关系管理
  - 执行计划获取
  - 语义压缩
  - 相似任务搜索
  - 智能推荐

认证：
  - 通过依赖注入获取 user_id
  - 所有操作都是用户隔离的
  - 严格的任务所有权验证

【修复记录】
  - 2026-02-28: 修复权限漏洞 (P0-016, P0-017)
    - 修复 task_manager.store -> task_manager._task_store
    - 添加任务所有权验证
    - 防止用户访问他人任务
"""

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi import Path as FastApiPath
from pydantic import BaseModel, Field

from core.diagnostic import diagnostic_except_handler
from core.logger import logger

# 导入任务管理器
try:
    from core.task.user_task_manager import TaskCreateRequest as ManagerCreateRequest
    from core.task.user_task_manager import TaskPriority, UserTaskManager, get_user_task_manager
    TASK_API_AVAILABLE = True
except ImportError as e:
    TASK_API_AVAILABLE = False
    logging.warning(f"[TaskAPI] 任务管理模块不可用: {e}")

    # 占位符类，避免类型注解错误
    class UserTaskManager:
        pass

# 导入 cloud_api 的认证相关组件
try:
    from api.cloud_api import get_current_user, user_auth_store
    AUTH_AVAILABLE = True
except ImportError:
    try:
        from .cloud_api import get_current_user, user_auth_store
        AUTH_AVAILABLE = True
    except ImportError as e:
        AUTH_AVAILABLE = False
        user_auth_store = None
        get_current_user = None
        logger.warning(f"[TaskAPI] 无法导入cloud_api认证组件: {e}")

# 导入 CheckpointManager（断点续传功能迁移到 /api/tasks/*）
try:
    from core.agent.checkpoint_manager import checkpoint_manager
    CHECKPOINT_AVAILABLE = checkpoint_manager is not None
except ImportError as e:
    CHECKPOINT_AVAILABLE = False
    checkpoint_manager = None
    logger.warning(f"[TaskAPI] CheckpointManager 导入失败: {e}")


import time

from fastapi import status

# ═══════════════════════════════════════════════════════════
# 导入3槽位长任务模块（合并自 long_task_slots_api.py）
# ═══════════════════════════════════════════════════════════
try:
    from core.task.long_task_slots import LongTaskSlots, SlotStatus, SlotTask, get_long_task_slots
    SLOTS_AVAILABLE = True
except ImportError as e:
    SLOTS_AVAILABLE = False
    logger.warning(f"[TaskAPI] 无法导入long_task_slots模块: {e}")

# ═══════════════════════════════════════════════════════════
# 导入工作流模块（合并自 workflow_api.py）
# ═══════════════════════════════════════════════════════════
try:
    from core.workflow import (
        WorkflowDefinition,
        WorkflowEngine,
        WorkflowExecutor,
        WorkflowStep,
        get_workflow_engine,
        get_workflow_executor,
    )
    WORKFLOW_AVAILABLE = True
except ImportError as e:
    WORKFLOW_AVAILABLE = False
    logger.warning(f"[TaskAPI] 无法导入工作流模块: {e}")

# ═══════════════════════════════════════════════════════════
# 导入演示学习系统核心类（合并自 procedure_learning_api.py）
# ═══════════════════════════════════════════════════════════
try:
    from core.procedure_learning import TaskMode, get_operation_recorder, get_procedure_library, get_task_coordinator
    PROCEDURE_LEARNING_AVAILABLE = True
except ImportError as e:
    PROCEDURE_LEARNING_AVAILABLE = False
    logger.warning(f"[TaskAPI] 演示学习系统导入失败: {e}")
    TaskMode = None

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tasks", tags=["tasks"])

# ═══════════════════════════════════════════════════════════
# Pydantic 模型定义
# ═══════════════════════════════════════════════════════════

class TaskCreateRequest(BaseModel):
    """创建任务请求"""
    title: str = Field(..., min_length=1, max_length=200, description="任务标题")
    description: str = Field(default="", max_length=5000, description="任务描述")
    priority: str = Field(default="normal", description="优先级: urgent/high/normal/low")
    task_type: str = Field(default="custom", description="任务类型")
    parent_id: str | None = Field(default=None, description="父任务ID")
    depends_on: list[str] = Field(default_factory=list, description="依赖的任务ID列表")
    memory_ids: list[str] = Field(default_factory=list, description="关联的记忆ID列表")
    deadline: str | None = Field(default=None, description="截止日期 (ISO格式)")
    max_retries: int = Field(default=3, ge=0, le=10, description="最大重试次数")
    metadata: dict[str, Any] = Field(default_factory=dict, description="额外元数据")

    class Config:
        json_schema_extra = {
            "example": {
                "title": "示例任务",
                "description": "这是一个示例任务",
                "priority": "normal",
                "task_type": "custom",
                "depends_on": [],
                "memory_ids": [],
                "max_retries": 3,
                "metadata": {}
            }
        }


class TaskUpdateRequest(BaseModel):
    """更新任务请求"""
    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    priority: str | None = Field(default=None)
    status: str | None = Field(default=None, description="状态: pending/ready/running/paused/completed/failed/cancelled/archived")
    deadline: str | None = Field(default=None)
    metadata: dict[str, Any] | None = Field(default=None)


class PauseTaskRequest(BaseModel):
    """暂停任务请求"""
    reason: str | None = Field(default=None, description="暂停原因")
    new_requirements: str | None = Field(default=None, description="用户提出的新需求")


class ResumeTaskRequest(BaseModel):
    """恢复任务请求"""
    ai_confirmation: str | None = Field(default=None, description="AI对需求理解的确认内容")
    confirmed_understanding: bool = Field(default=False, description="是否已确认AI理解需求")


class TaskResponse(BaseModel):
    """任务响应"""
    id: str
    user_id: str
    title: str
    description: str
    status: str
    priority: int
    task_type: str
    parent_id: str | None
    created_at: str
    updated_at: str
    started_at: str | None
    completed_at: str | None
    deadline: str | None
    retry_count: int
    max_retries: int
    is_compressed: bool
    compressed_summary: str | None
    result: dict | None
    error: str | None
    metadata: dict[str, Any]
    progress: float | None = Field(default=None, description="任务进度百分比0-100")


class TaskWithDepsResponse(BaseModel):
    """带依赖信息的任务响应"""
    task: TaskResponse
    dependencies: list[dict[str, Any]]
    dependents: list[dict[str, Any]]
    ready_to_run: bool


class DependencyRequest(BaseModel):
    """添加依赖请求"""
    depends_on: str = Field(..., description="被依赖的任务ID")
    dependency_type: str = Field(default="blocks", description="依赖类型: blocks/relates_to/parent_child")


class CompressRequest(BaseModel):
    """压缩任务请求"""
    force: bool = Field(default=False, description="是否强制重新压缩")


class SearchRequest(BaseModel):
    """搜索请求"""
    query: str = Field(..., min_length=1, description="搜索查询")
    n_results: int = Field(default=5, ge=1, le=20)
    include_completed_only: bool = Field(default=True)


class BatchCompressRequest(BaseModel):
    """批量压缩请求"""
    task_ids: list[str] = Field(..., min_items=1)
    max_concurrent: int = Field(default=3, ge=1, le=5)


# ═══════════════════════════════════════════════════════════
# 依赖注入
# ═══════════════════════════════════════════════════════════

def get_current_user_id(request: Request) -> str:
    """
    获取当前用户ID - 强制认证版本 (与cloud_api.get_current_user保持一致)

    支持两种认证方式:
    1. JWT Bearer Token: 通过 /api/auth/login 获取的标准JWT
    2. API Key: 以sk-开头的API密钥（向后兼容）
    """
    from fastapi import HTTPException, status

    # 从 Authorization 头获取 token
    auth_header = request.headers.get('Authorization', '')

    # 检查是否有 Authorization header
    if not auth_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="需要认证",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 检查 Bearer 前缀
    if not auth_header.startswith('Bearer '):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="认证方案无效，请使用 'Bearer <token>'",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = auth_header[7:]  # 去掉 'Bearer ' 前缀

    # API Key 验证（向后兼容）
    if token.startswith("sk-"):
        # 尝试从 cloud_api 获取 API_KEYS
        try:
            from api.cloud_api import API_KEYS
        except ImportError:
            try:
                from .cloud_api import API_KEYS
            except ImportError:
                API_KEYS = {}

        if token in API_KEYS:
            return API_KEYS[token]
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API 密钥无效",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # JWT Token验证 - 使用与 cloud_api 相同的逻辑
    if AUTH_AVAILABLE and user_auth_store:
        payload = user_auth_store.verify_token(token)
        if payload:
            user_id = payload.get("sub")
            if user_id:
                # 验证用户是否仍然存在且活跃（与cloud_api一致）
                user = user_auth_store.get_user_by_id(user_id)
                # 拒绝默认/匿名用户，且要求用户存在并处于活跃状态
                if user and user.get("is_active", True) and user_id not in ('default', 'anonymous'):
                    return user_id

    # 无效token，返回401
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="令牌无效或已过期",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_task_manager(request: Request) -> "UserTaskManager":
    """获取用户的任务管理器实例"""
    if not TASK_API_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="任务管理模块不可用"
        )
    user_id = get_current_user_id(request)
    return get_user_task_manager(user_id)


# ═══════════════════════════════════════════════════════════
# 权限验证辅助函数
# ═══════════════════════════════════════════════════════════

async def verify_task_ownership(
    task_id: str,
    task_manager: UserTaskManager,
    current_user_id: str
) -> dict:
    """
    验证任务所有权

    Args:
        task_id: 任务ID
        task_manager: 任务管理器实例
        current_user_id: 当前用户ID

    Returns:
        任务数据

    Raises:
        HTTPException: 403 - 访问他人任务
        HTTPException: 404 - 任务不存在
    """
    # 获取任务
    task = await task_manager._task_store.get_task(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 验证所有权
    task_user_id = task.get('user_id')
    if task_user_id and task_user_id != current_user_id:
        logger.warning(
            f"[TaskAPI] 权限拒绝: 用户 {current_user_id} 尝试访问用户 {task_user_id} 的任务 {task_id}"
        )
        raise HTTPException(
            status_code=403,
            detail="拒绝访问：只能访问自己的任务"
        )

    return task


# ═══════════════════════════════════════════════════════════
# API 端点
# ═══════════════════════════════════════════════════════════

# ───────────────────────────────────────────────────────────
# 任务 CRUD
# ───────────────────────────────────────────────────────────

@router.post("", response_model=dict[str, str])
async def create_task(
    request: Request,
    request_data: TaskCreateRequest,
    task_manager: UserTaskManager = Depends(get_task_manager)
):
    """
    创建新任务

    支持指定依赖任务，系统会自动检查循环依赖。
    如果依赖已完成，任务会自动变为 READY 状态。
    """
    try:
        # 转换优先级（支持字符串直接传入ManagerCreateRequest）
        priority_str = (request_data.priority or "normal").lower()
        priority_map = {
            "urgent": TaskPriority.URGENT,
            "high": TaskPriority.HIGH,
            "normal": TaskPriority.NORMAL,
            "low": TaskPriority.LOW
        }
        priority = priority_map.get(priority_str, TaskPriority.NORMAL)

        # 创建请求对象 - 使用正确的priority类型
        create_req = ManagerCreateRequest(
            title=request_data.title,
            description=request_data.description,
            priority=priority,
            task_type=request_data.task_type,
            parent_id=request_data.parent_id,
            depends_on=request_data.depends_on or [],
            memory_ids=request_data.memory_ids or [],
            deadline=request_data.deadline,
            max_retries=request_data.max_retries,
            metadata=request_data.metadata or {}
        )

        task_id = await task_manager.create_task(create_req)
        return {"id": task_id, "message": "Task created successfully"}

    except ValueError as e:
        logger.error(f"[TaskAPI] 创建任务参数错误: {e}")
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 创建任务失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail=f"Failed to create task: {str(e)}") from e


@router.get("", response_model=dict[str, Any])
async def list_tasks(
    request: Request,
    status: str | None = Query(None, description="按状态过滤"),
    task_type: str | None = Query(None, description="按类型过滤"),
    parent_id: str | None = Query(None, description="按父任务过滤"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    task_manager: UserTaskManager = Depends(get_task_manager)
):
    """
    获取任务列表

    支持按状态、类型、父任务过滤，支持分页。
    只返回当前用户的任务。

    【修复】添加完整的异常处理和错误日志
    """
    try:
        # 【修复】检查 task_manager 和 _task_store 是否存在
        if not task_manager:
            logger.error("[TaskAPI] task_manager 未初始化")
            raise HTTPException(status_code=500, detail="任务管理器未初始化")

        if not hasattr(task_manager, '_task_store'):
            logger.error("[TaskAPI] task_manager._task_store 不存在")
            raise HTTPException(status_code=500, detail="任务存储不可用")

        tasks = await task_manager._task_store.list_tasks(
            status=status,
            task_type=task_type,
            parent_id=parent_id,
            limit=limit,
            offset=offset
        )

        # 检查返回值
        if tasks is None:
            logger.error("[TaskAPI] list_tasks 返回 None")
            raise HTTPException(status_code=500, detail="任务列表返回为空")

        # 格式化任务数据以匹配前端期望格式
        formatted_tasks = []
        for t in tasks:
            try:
                # 【修复】使用.get()安全访问，避免KeyError
                formatted_tasks.append({
                    "id": t.get("task_id") or t.get("id", ""),  # 映射 task_id -> id
                    "title": t.get("title") or t.get("type", "未命名任务"),  # 映射 type -> title
                    "description": t.get("description") or t.get("data", {}).get("description", t.get("type", "")),
                    "status": t.get("status", "pending"),
                    "progress": t.get("progress", 0),  # 默认值
                    "priority": t.get("priority", "medium"),  # 默认值
                    "created_at": int(t.get("created_at", 0) * 1000) if t.get("created_at") else 0  # 转毫秒
                })
            except Exception as e:
                # 【修复】记录单个任务格式化错误，但继续处理其他任务
                logger.error(f"[TaskAPI] 格式化任务失败: {e}", exc_info=True)
                continue

        # 【修复】直接返回tasks数组，与前端期望格式一致
        return {
            "tasks": formatted_tasks,
            "total": len(formatted_tasks),
            "limit": limit,
            "offset": offset
        }
    except HTTPException:
        raise
    except Exception as e:
        # 【修复】记录详细错误日志
        logger.error(f"[TaskAPI] 获取任务列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list tasks: {str(e)}") from e


@router.get("/{task_id}", response_model=TaskWithDepsResponse)
async def get_task(
    request: Request,
    task_id: str = FastApiPath(..., description="任务ID"),
    task_manager: UserTaskManager = Depends(get_task_manager)
):
    """
    获取任务详情（包含依赖信息）

    只能访问当前用户自己的任务。
    """
    try:
        current_user_id = get_current_user_id(request)

        # 验证任务所有权
        await verify_task_ownership(task_id, task_manager, current_user_id)

        result = await task_manager.get_task_with_deps(task_id)
        if not result or not result.get("task"):
            raise HTTPException(status_code=404, detail="任务不存在")
        return result

    except HTTPException:
        raise
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 获取任务失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail="获取任务失败") from e


@router.patch("/{task_id}", response_model=dict[str, Any])
async def update_task(
    request: Request,
    task_id: str,
    request_data: TaskUpdateRequest,
    task_manager: UserTaskManager = Depends(get_task_manager)
):
    """
    更新任务

    支持部分更新，只更新提供的字段。
    只能更新当前用户自己的任务。
    """
    try:
        current_user_id = get_current_user_id(request)

        # 验证任务所有权
        await verify_task_ownership(task_id, task_manager, current_user_id)

        updates = request_data.dict(exclude_unset=True)
        if not updates:
            return {"success": True, "message": "No fields to update"}

        # 转换优先级
        if "priority" in updates:
            priority_map = {
                "urgent": 0, "high": 1, "normal": 2, "low": 3
            }
            updates["priority"] = priority_map.get(updates["priority"].lower(), 2)

        result = await task_manager.update_task(task_id, updates)
        if not result.get("success"):
            raise HTTPException(status_code=404, detail="任务不存在")
        return result

    except HTTPException:
        raise
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 更新任务失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail="更新任务失败") from e


@router.delete("/{task_id}", response_model=dict[str, bool])
async def delete_task(
    request: Request,
    task_id: str,
    hard_delete: bool = Query(False, description="是否硬删除"),
    task_manager: UserTaskManager = Depends(get_task_manager)
):
    """
    删除任务

    默认软删除（标记为 archived），设置 hard_delete=true 永久删除。
    只能删除当前用户自己的任务。
    """
    try:
        current_user_id = get_current_user_id(request)

        # 验证任务所有权
        await verify_task_ownership(task_id, task_manager, current_user_id)

        if hard_delete:
            success = await task_manager._task_store.delete_task(task_id)
        else:
            success = await task_manager.archive_task(task_id)

        if not success:
            raise HTTPException(status_code=404, detail="任务不存在")
        return {"success": True}

    except HTTPException:
        raise
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 删除任务失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail="删除任务失败") from e


# ───────────────────────────────────────────────────────────
# 任务状态操作
# ───────────────────────────────────────────────────────────

@router.post("/{task_id}/complete", response_model=dict[str, Any])
async def complete_task(
    request: Request,
    task_id: str,
    result: dict[str, Any] = Body(default_factory=dict),
    trigger_compression: bool = Query(True, description="完成后是否触发语义压缩"),
    task_manager: UserTaskManager = Depends(get_task_manager)
):
    """
    标记任务完成

    完成任务后可以自动触发语义压缩，生成摘要存入向量库。
    只能完成当前用户自己的任务。
    """
    try:
        current_user_id = get_current_user_id(request)

        # 验证任务所有权
        await verify_task_ownership(task_id, task_manager, current_user_id)

        success = await task_manager.complete_task(
            task_id,
            result=result,
            trigger_compression=trigger_compression
        )
        if not success:
            raise HTTPException(status_code=404, detail="任务不存在")
        return {"success": True, "message": "Task completed"}

    except HTTPException:
        raise
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 完成任务失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail="完成任务失败") from e


@router.post("/{task_id}/fail", response_model=dict[str, Any])
async def fail_task(
    request: Request,
    task_id: str,
    error: str = Body(..., embed=True),
    task_manager: UserTaskManager = Depends(get_task_manager)
):
    """
    标记任务失败

    系统会自动尝试重试（如果未达到最大重试次数）。
    只能操作当前用户自己的任务。
    """
    try:
        current_user_id = get_current_user_id(request)

        # 验证任务所有权
        await verify_task_ownership(task_id, task_manager, current_user_id)

        success = await task_manager.fail_task(task_id, error)
        if not success:
            raise HTTPException(status_code=404, detail="任务不存在")
        return {"success": True, "message": "Task marked as failed"}

    except HTTPException:
        raise
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 标记任务失败失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail="标记任务失败状态失败") from e


@router.post("/{task_id}/cancel", response_model=dict[str, bool])
async def cancel_task(
    request: Request,
    task_id: str,
    reason: str | None = Body(None),
    task_manager: UserTaskManager = Depends(get_task_manager)
):
    """
    取消任务

    只能取消当前用户自己的任务。
    """
    try:
        current_user_id = get_current_user_id(request)

        # 验证任务所有权
        await verify_task_ownership(task_id, task_manager, current_user_id)

        success = await task_manager.cancel_task(task_id, reason)
        if not success:
            raise HTTPException(status_code=404, detail="任务不存在")
        return {"success": True}

    except HTTPException:
        raise
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 取消任务失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail="取消任务失败") from e


@router.post("/{task_id}/pause", response_model=dict[str, Any])
async def pause_task(
    request: Request,
    task_id: str,
    request_data: PauseTaskRequest,
    task_manager: UserTaskManager = Depends(get_task_manager)
):
    """
    暂停任务 - 【关键修复】确保返回checkpoint_id

    暂停任务并触发AI对话询问需求变更。任务必须处于 RUNNING 或 READY 状态。
    保存完整状态到CheckpointManager，包括phase_anchors。
    只能暂停当前用户自己的任务。
    返回包含暂停结果、AI对话提示和checkpoint_id的字典。
    """
    try:
        current_user_id = get_current_user_id(request)

        # 验证任务所有权
        await verify_task_ownership(task_id, task_manager, current_user_id)

        # 【关键】从请求中获取working_memory（如果前端传递了session_id）
        working_memory = None
        try:
            from core.memory.working_memory import get_working_memory
            # 尝试从请求头或查询参数获取session_id
            session_id = request.headers.get('X-Session-Id') or request.query_params.get('session_id')
            if session_id:
                working_memory = get_working_memory(session_id)
                logger.debug(f"[TaskAPI] 获取working_memory成功: session_id={session_id}")
        except Exception as e:
            logger.debug(f"[TaskAPI] 获取working_memory失败（不影响暂停）: {e}")

        # 调用UserTaskManager暂停任务
        result = await task_manager.pause_task(
            task_id=task_id,
            reason=request_data.reason,
            new_requirements=request_data.new_requirements,
            working_memory=working_memory  # 【新增】传递working_memory以同步phase_anchors
        )

        if not result.get("success"):
            if result.get("error") == "Task not found":
                raise HTTPException(status_code=404, detail="任务不存在")
            raise HTTPException(status_code=400, detail=result.get("error"))

        # 【关键修复】确保返回checkpoint_id给前端
        response = {
            "success": True,
            "task_id": result.get("task_id"),
            "checkpoint_id": result.get("checkpoint_id"),  # 【新增】
            "phase_count": result.get("phase_count", 0),  # 【新增】
            "status": result.get("status"),
            "ai_prompt": result.get("ai_prompt"),
            "requires_ai_confirmation": result.get("requires_ai_confirmation", True),
            "message": result.get("message", "任务已暂停，所有进度已保存")  # 【新增】
        }

        logger.info(f"[TaskAPI] 任务暂停成功: task_id={task_id}, checkpoint_id={result.get('checkpoint_id')}")
        return response

    except HTTPException:
        raise
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 暂停任务失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail="暂停任务失败") from e


@router.post("/{task_id}/resume", response_model=dict[str, Any])
async def resume_task(
    request: Request,
    task_id: str,
    request_data: ResumeTaskRequest,
    task_manager: UserTaskManager = Depends(get_task_manager)
):
    """
    恢复暂停的任务

    恢复任务到暂停前的状态。如果任务有新需求，需要AI确认理解后才能恢复。
    只能恢复当前用户自己的任务。
    返回包含恢复结果的字典。
    """
    try:
        current_user_id = get_current_user_id(request)

        # 验证任务所有权
        await verify_task_ownership(task_id, task_manager, current_user_id)

        # 从请求头获取 session_id，用于恢复对话上下文
        session_id = request.headers.get('X-Session-Id')

        result = await task_manager.resume_task(
            task_id=task_id,
            ai_confirmation=request_data.ai_confirmation,
            confirmed_understanding=request_data.confirmed_understanding,
            session_id=session_id
        )
        if not result.get("success"):
            if result.get("error") == "Task not found":
                raise HTTPException(status_code=404, detail="任务不存在")
            # 如果需要AI确认，返回400错误（不是失败，是正常流程）
            if result.get("requires_ai_confirmation"):
                return result
            raise HTTPException(status_code=400, detail=result.get("error"))
        return result

    except HTTPException:
        raise
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 恢复任务失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail="恢复任务失败") from e


@router.post("/{task_id}/archive", response_model=dict[str, Any])
async def archive_task(
    request: Request,
    task_id: str,
    task_manager: UserTaskManager = Depends(get_task_manager)
):
    """
    归档任务

    归档前会检查：1) 任务已完成或失败 2) 没有未完成的依赖者
    只能归档当前用户自己的任务。
    """
    try:
        current_user_id = get_current_user_id(request)

        # 验证任务所有权
        await verify_task_ownership(task_id, task_manager, current_user_id)

        success = await task_manager.archive_task(task_id)
        if not success:
            raise HTTPException(status_code=400, detail="任务无法归档（可能存在未完成的依赖或任务未完成/失败）")
        return {"success": True, "message": "Task archived"}

    except HTTPException:
        raise
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 归档任务失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail="归档任务失败") from e


# ───────────────────────────────────────────────────────────
# 依赖管理
# ───────────────────────────────────────────────────────────

@router.post("/{task_id}/dependencies", response_model=dict[str, Any])
async def add_dependency(
    request: Request,
    task_id: str,
    request_data: DependencyRequest,
    task_manager: UserTaskManager = Depends(get_task_manager)
):
    """
    添加任务依赖

    会自动检查循环依赖，如果检测到循环返回 400 错误。
    只能操作当前用户自己的任务。
    """
    try:
        current_user_id = get_current_user_id(request)

        # 验证两个任务的所有权
        await verify_task_ownership(task_id, task_manager, current_user_id)
        await verify_task_ownership(request_data.depends_on, task_manager, current_user_id)

        success = await task_manager.add_dependency(
            task_id,
            request_data.depends_on,
            request_data.dependency_type
        )
        if not success:
            raise HTTPException(status_code=400, detail="添加依赖失败（可能形成循环依赖）")
        return {"success": True, "message": "Dependency added"}

    except HTTPException:
        raise
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 添加依赖失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail="添加依赖失败") from e


@router.delete("/{task_id}/dependencies/{depends_on}", response_model=dict[str, bool])
async def remove_dependency(
    request: Request,
    task_id: str,
    depends_on: str,
    task_manager: UserTaskManager = Depends(get_task_manager)
):
    """
    移除任务依赖

    只能操作当前用户自己的任务。
    """
    try:
        current_user_id = get_current_user_id(request)

        # 验证任务所有权
        await verify_task_ownership(task_id, task_manager, current_user_id)

        success = await task_manager.remove_dependency(task_id, depends_on)
        return {"success": success}

    except HTTPException:
        raise
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 移除依赖失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail="移除依赖失败") from e


@router.get("/{task_id}/dependencies", response_model=dict[str, Any])
async def get_dependencies(
    request: Request,
    task_id: str,
    task_manager: UserTaskManager = Depends(get_task_manager)
):
    """
    获取任务的所有依赖

    只能访问当前用户自己的任务。
    """
    try:
        current_user_id = get_current_user_id(request)

        # 验证任务所有权
        await verify_task_ownership(task_id, task_manager, current_user_id)

        deps = await task_manager._task_store.get_dependencies(task_id)
        return {"dependencies": deps}

    except HTTPException:
        raise
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 获取依赖失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail="获取依赖失败") from e


# ───────────────────────────────────────────────────────────
# 执行计划
# ───────────────────────────────────────────────────────────

@router.get("/plan/execution", response_model=list[list[str]])
async def get_execution_plan(
    task_manager: UserTaskManager = Depends(get_task_manager)
):
    """
    获取任务执行计划

    使用拓扑排序生成执行顺序，返回分层级的任务ID列表。
    同一层级的任务可以并行执行。

    Example response: [["task1"], ["task2", "task3"], ["task4"]]
    """
    try:
        plan = await task_manager.get_execution_plan()
        return plan

    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 获取执行计划失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail="获取执行计划失败") from e


# ───────────────────────────────────────────────────────────
# 语义压缩
# ───────────────────────────────────────────────────────────

@router.post("/{task_id}/compress", response_model=dict[str, Any])
async def compress_task(
    request: Request,
    task_id: str,
    request_data: CompressRequest,
    task_manager: UserTaskManager = Depends(get_task_manager)
):
    """
    对任务进行语义压缩

    调用AI生成任务摘要，存入向量库用于后续相似搜索。
    只能压缩当前用户自己的任务。
    """
    try:
        current_user_id = get_current_user_id(request)

        # 验证任务所有权
        await verify_task_ownership(task_id, task_manager, current_user_id)

        summary = await task_manager.compress_task(task_id, force=request_data.force)
        if summary is None:
            raise HTTPException(status_code=404, detail="任务不存在或无法压缩")
        return {"success": True, "summary": summary}

    except HTTPException:
        raise
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 压缩任务失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail="压缩任务失败") from e


@router.post("/batch/compress", response_model=dict[str, Any])
async def batch_compress_tasks(
    request: Request,
    request_data: BatchCompressRequest,
    task_manager: UserTaskManager = Depends(get_task_manager)
):
    """
    批量压缩任务

    使用信号量控制并发数，避免过度调用AI。
    只能压缩当前用户自己的任务。
    """
    try:
        current_user_id = get_current_user_id(request)

        # 验证所有任务的所有权
        for task_id in request_data.task_ids:
            await verify_task_ownership(task_id, task_manager, current_user_id)

        results = await task_manager.batch_compress_tasks(
            request_data.task_ids,
            max_concurrent=request_data.max_concurrent
        )
        return {
            "success": True,
            "compressed": len(results),
            "compressed_count": len(results),
            "results": results
        }

    except HTTPException:
        raise
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 批量压缩失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail="批量压缩任务失败") from e


# ───────────────────────────────────────────────────────────
# 相似任务搜索
# ───────────────────────────────────────────────────────────

@router.post("/search/similar", response_model=dict[str, Any])
async def search_similar_tasks(
    request_data: SearchRequest,
    task_manager: UserTaskManager = Depends(get_task_manager)
):
    """
    搜索相似任务

    基于向量库的语义相似度搜索。
    只搜索当前用户的任务。
    """
    try:
        results = await task_manager.find_similar_tasks(
            query=request_data.query,
            n_results=request_data.n_results,
            include_completed_only=request_data.include_completed_only
        )
        return {"tasks": results}

    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 搜索相似任务失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail="搜索相似任务失败") from e


@router.get("/suggestions/next", response_model=dict[str, Any])
async def suggest_next_tasks(
    n: int = Query(3, ge=1, le=10),
    task_manager: UserTaskManager = Depends(get_task_manager)
):
    """
    智能推荐下一个任务

    策略：1) 优先 READY 状态 2) 按优先级排序 3) 考虑截止日期
    只推荐当前用户的任务。
    """
    try:
        suggestions = await task_manager.suggest_next_tasks(n_suggestions=n)
        # 兼容前端单任务推荐期望
        if suggestions:
            return {"task": suggestions[0]}
        return {"task": None}

    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 获取任务建议失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail="建议下一步任务失败") from e


# ───────────────────────────────────────────────────────────
# 任务树与统计
# ───────────────────────────────────────────────────────────

@router.get("/tree/{root_task_id}", response_model=dict[str, Any])
async def get_task_tree(
    request: Request,
    root_task_id: str = FastApiPath(..., description="根任务ID"),
    task_manager: UserTaskManager = Depends(get_task_manager)
):
    """
    获取任务树

    递归获取任务及其所有子任务、依赖关系的完整树形结构。
    只能访问当前用户自己的任务。
    """
    try:
        current_user_id = get_current_user_id(request)

        # 验证任务所有权
        await verify_task_ownership(root_task_id, task_manager, current_user_id)

        tree = await task_manager.get_task_tree(root_task_id)
        return tree

    except HTTPException:
        raise
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 获取任务树失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail="获取任务树失败") from e


@router.get("/stats/overview", response_model=dict[str, Any])
async def get_task_stats(
    task_manager: UserTaskManager = Depends(get_task_manager)
):
    """
    获取任务统计信息

    只统计当前用户的任务。
    """
    try:
        stats = await task_manager.get_stats()
        return stats

    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 获取统计信息失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail="获取任务统计失败") from e


# ───────────────────────────────────────────────────────────
# 清理操作
# ───────────────────────────────────────────────────────────

@router.post("/cleanup", response_model=dict[str, Any])
async def cleanup_old_tasks(
    days: int = Query(30, ge=1, description="清理多少天前的任务"),
    archive_first: bool = Query(True, description="是否先归档"),
    task_manager: UserTaskManager = Depends(get_task_manager)
):
    """
    清理旧任务

    返回清理的任务数量。
    只清理当前用户的任务。
    """
    try:
        count = await task_manager.cleanup_old_tasks(
            days=days,
            archive_first=archive_first
        )
        return {"success": True, "deleted": count, "cleaned_count": count}

    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 清理任务失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail="清理任务失败") from e


# ───────────────────────────────────────────────────────────
# 健康检查
# ───────────────────────────────────────────────────────────

@router.get("/health/check", response_model=dict[str, Any])
async def health_check():
    """任务API健康检查"""
    return {
        "status": "healthy" if TASK_API_AVAILABLE else "degraded",
        "module_available": TASK_API_AVAILABLE,
        "timestamp": datetime.now().isoformat()
    }


# ═══════════════════════════════════════════════════════════
# 阶段锚点 (Phase Anchors) API
# 【新增】为前端 PhaseAnchorPanel 提供基础支持
# ═══════════════════════════════════════════════════════════

# 内存存储：task_id -> list of anchors
_phase_anchor_store: dict[str, list[dict[str, Any]]] = {}


class PhaseAnchorCreate(BaseModel):
    """创建阶段锚点请求"""
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    phase: str = Field(default="planning", description="阶段: planning/execution/review")
    status: str = Field(default="pending", description="状态: pending/active/completed/failed")
    position: int = Field(default=0, description="排序位置")
    metadata: dict[str, Any] = Field(default_factory=dict)


class PhaseAnchorUpdate(BaseModel):
    """更新阶段锚点请求"""
    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    phase: str | None = Field(default=None)
    status: str | None = Field(default=None)
    position: int | None = Field(default=None)
    metadata: dict[str, Any] | None = Field(default=None)


@router.get("/{task_id}/anchors", response_model=dict[str, Any])
async def get_task_anchors(
    request: Request,
    task_id: str = FastApiPath(..., description="任务ID"),
    task_manager: UserTaskManager = Depends(get_task_manager)
):
    """获取任务的阶段锚点列表"""
    current_user_id = get_current_user_id(request)
    await verify_task_ownership(task_id, task_manager, current_user_id)
    anchors = _phase_anchor_store.get(task_id, [])
    return {
        "success": True,
        "task_id": task_id,
        "anchors": anchors,
        "total": len(anchors)
    }


@router.post("/{task_id}/anchors", response_model=dict[str, Any])
async def create_task_anchor(
    request: Request,
    task_id: str = FastApiPath(..., description="任务ID"),
    body: PhaseAnchorCreate = Body(...),
    task_manager: UserTaskManager = Depends(get_task_manager)
):
    """创建任务的阶段锚点"""
    current_user_id = get_current_user_id(request)
    await verify_task_ownership(task_id, task_manager, current_user_id)
    import uuid
    anchor = {
        "id": f"anchor_{uuid.uuid4().hex[:8]}",
        "task_id": task_id,
        "title": body.title,
        "description": body.description,
        "phase": body.phase,
        "status": body.status,
        "position": body.position,
        "metadata": body.metadata,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }
    if task_id not in _phase_anchor_store:
        _phase_anchor_store[task_id] = []
    _phase_anchor_store[task_id].append(anchor)
    _phase_anchor_store[task_id].sort(key=lambda x: x["position"])
    return {"success": True, "anchor": anchor}


# 【注意】batch 路由必须在 /{anchor_id} 之前定义，避免 FastAPI 把 "batch" 当成 anchor_id
@router.post("/{task_id}/anchors/batch", response_model=dict[str, Any])
async def batch_update_task_anchors(
    request: Request,
    task_id: str = FastApiPath(..., description="任务ID"),
    anchors: list[dict[str, Any]] = Body(...),
    task_manager: UserTaskManager = Depends(get_task_manager)
):
    """批量更新任务的阶段锚点（替换整组）"""
    current_user_id = get_current_user_id(request)
    await verify_task_ownership(task_id, task_manager, current_user_id)
    _phase_anchor_store[task_id] = anchors
    return {"success": True, "task_id": task_id, "total": len(anchors)}


@router.put("/{task_id}/anchors/{anchor_id}", response_model=dict[str, Any])
async def update_task_anchor(
    request: Request,
    task_id: str = FastApiPath(..., description="任务ID"),
    anchor_id: str = FastApiPath(..., description="锚点ID"),
    body: PhaseAnchorUpdate = Body(...),
    task_manager: UserTaskManager = Depends(get_task_manager)
):
    """更新任务的阶段锚点"""
    current_user_id = get_current_user_id(request)
    await verify_task_ownership(task_id, task_manager, current_user_id)
    anchors = _phase_anchor_store.get(task_id, [])
    for anchor in anchors:
        if anchor["id"] == anchor_id:
            if body.title is not None:
                anchor["title"] = body.title
            if body.description is not None:
                anchor["description"] = body.description
            if body.phase is not None:
                anchor["phase"] = body.phase
            if body.status is not None:
                anchor["status"] = body.status
            if body.position is not None:
                anchor["position"] = body.position
            if body.metadata is not None:
                anchor["metadata"] = body.metadata
            anchor["updated_at"] = datetime.now().isoformat()
            anchors.sort(key=lambda x: x["position"])
            return {"success": True, "anchor": anchor}
    raise HTTPException(status_code=404, detail="锚点不存在")


@router.delete("/{task_id}/anchors/{anchor_id}", response_model=dict[str, Any])
async def delete_task_anchor(
    request: Request,
    task_id: str = FastApiPath(..., description="任务ID"),
    anchor_id: str = FastApiPath(..., description="锚点ID"),
    task_manager: UserTaskManager = Depends(get_task_manager)
):
    """删除任务的阶段锚点"""
    current_user_id = get_current_user_id(request)
    await verify_task_ownership(task_id, task_manager, current_user_id)
    anchors = _phase_anchor_store.get(task_id, [])
    for i, anchor in enumerate(anchors):
        if anchor["id"] == anchor_id:
            anchors.pop(i)
            return {"success": True, "deleted_id": anchor_id}
    raise HTTPException(status_code=404, detail="锚点不存在")


@router.get("/{task_id}/anchors/{anchor_id}/history", response_model=dict[str, Any])
async def get_task_anchor_history(
    request: Request,
    task_id: str = FastApiPath(..., description="任务ID"),
    anchor_id: str = FastApiPath(..., description="锚点ID"),
    task_manager: UserTaskManager = Depends(get_task_manager)
):
    """获取阶段锚点的历史记录"""
    current_user_id = get_current_user_id(request)
    await verify_task_ownership(task_id, task_manager, current_user_id)
    return {
        "success": True,
        "anchor_id": anchor_id,
        "task_id": task_id,
        "history": []
    }


class ContinueFromAnchorRequest(BaseModel):
    """从锚点继续执行请求"""
    anchor_id: str = Field(..., description="要继续执行的锚点ID")
    params: dict[str, Any] | None = Field(default=None, description="继续执行时的附加参数")


class RollbackToAnchorRequest(BaseModel):
    """回滚到锚点请求"""
    anchor_id: str = Field(..., description="要回滚到的锚点ID")
    preserve_state: bool = Field(default=True, description="是否保留回滚点之后的状态")


@router.post("/{task_id}/continue", response_model=dict[str, Any])
async def continue_from_anchor(
    request: Request,
    task_id: str = FastApiPath(..., description="任务ID"),
    body: ContinueFromAnchorRequest = Body(...),
    task_manager: UserTaskManager = Depends(get_task_manager)
):
    """
    从指定阶段锚点继续执行任务

    将任务状态恢复为 ready，并记录目标锚点ID。
    """
    current_user_id = get_current_user_id(request)
    await verify_task_ownership(task_id, task_manager, current_user_id)

    anchors = _phase_anchor_store.get(task_id, [])
    anchor = next((a for a in anchors if a.get("id") == body.anchor_id), None)
    if not anchor:
        raise HTTPException(status_code=404, detail="锚点不存在")

    try:
        from core.task.task_status import TaskStatus
        updates = {
            "status": TaskStatus.READY.value,
            "updated_at": datetime.now().isoformat(),
            "continue_from_anchor": body.anchor_id,
            "continue_params": body.params or {}
        }
        success = await task_manager._task_store.update_task(task_id, updates)
        if not success:
            raise HTTPException(status_code=500, detail="更新任务状态失败")

        return {
            "success": True,
            "task_id": task_id,
            "anchor_id": body.anchor_id,
            "message": "任务已从锚点继续"
        }
    except HTTPException:
        raise
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 从锚点继续任务失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail="从锚点继续任务失败") from e


@router.post("/{task_id}/rollback", response_model=dict[str, Any])
async def rollback_to_anchor(
    request: Request,
    task_id: str = FastApiPath(..., description="任务ID"),
    body: RollbackToAnchorRequest = Body(...),
    task_manager: UserTaskManager = Depends(get_task_manager)
):
    """
    回滚到指定阶段锚点

    将任务状态重置为 paused，并标记目标锚点为 rolled_back。
    """
    current_user_id = get_current_user_id(request)
    await verify_task_ownership(task_id, task_manager, current_user_id)

    anchors = _phase_anchor_store.get(task_id, [])
    anchor = next((a for a in anchors if a.get("id") == body.anchor_id), None)
    if not anchor:
        raise HTTPException(status_code=404, detail="锚点不存在")

    try:
        from core.task.task_status import TaskStatus

        # 标记目标锚点为 rolled_back
        anchor["status"] = "rolled_back"
        anchor["updated_at"] = datetime.now().isoformat()

        # 将目标锚点之后的 active/completed 锚点重置为 failed
        if not body.preserve_state:
            for a in anchors:
                if a.get("position", 0) > anchor.get("position", 0) and a.get("status") in ("active", "completed"):
                    a["status"] = "failed"
                    a["updated_at"] = datetime.now().isoformat()

        updates = {
            "status": TaskStatus.PAUSED.value,
            "updated_at": datetime.now().isoformat(),
            "rollback_to_anchor": body.anchor_id,
            "preserve_state": body.preserve_state
        }
        success = await task_manager._task_store.update_task(task_id, updates)
        if not success:
            raise HTTPException(status_code=500, detail="更新任务状态失败")

        return {
            "success": True,
            "task_id": task_id,
            "anchor_id": body.anchor_id,
            "message": "任务已回滚到指定锚点"
        }
    except HTTPException:
        raise
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 回滚到锚点失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail="回滚到锚点失败") from e


# ═══════════════════════════════════════════════════════════
# 【断点续传】Checkpoint 相关端点（从 checkpoint_api.py 迁移）
# ═══════════════════════════════════════════════════════════

@router.get("/{task_id}/progress", response_model=dict[str, Any])
async def get_task_checkpoint_progress(
    request: Request,
    task_id: str = FastApiPath(..., description="任务ID"),
    task_manager: UserTaskManager = Depends(get_task_manager)
):
    """
    获取任务执行进度（断点续传）

    返回任务详细进度信息，包括当前状态、进度百分比、断点信息、是否可以恢复等。
    """
    if not CHECKPOINT_AVAILABLE or checkpoint_manager is None:
        raise HTTPException(status_code=503, detail="检查点服务不可用")

    try:
        current_user_id = get_current_user_id(request)

        # 验证任务存在且属于当前用户
        task = await task_manager._task_store.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        if task.get("user_id") != current_user_id:
            raise HTTPException(status_code=403, detail="无权访问此任务")

        progress = await checkpoint_manager.get_task_progress(task_id)
        if not progress:
            raise HTTPException(status_code=404, detail="任务执行状态不存在")

        return {
            "success": True,
            "task_id": progress["task_id"],
            "status": progress["status"],
            "progress": progress["progress_percentage"],
            "progress_percentage": progress["progress_percentage"],
            "completed_steps": progress["completed_steps"],
            "total_steps": progress["total_steps"],
            "current_step": progress["current_step_number"],
            "current_step_goal": progress.get("current_step_goal"),
            "last_checkpoint_step": progress.get("last_checkpoint_step"),
            "last_checkpoint_name": progress.get("last_checkpoint_name"),
            "can_resume": progress.get("can_resume", False),
            "resume_step_number": progress.get("resume_step_number"),
            "resume_count": progress.get("resume_count", 0),
            "checkpoints": checkpoint_manager.list_checkpoints(task_id),
            "created_at": progress["created_at"],
            "updated_at": progress["updated_at"],
            "resumed_at": progress.get("resumed_at")
        }
    except HTTPException:
        raise
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 获取任务进度失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail=f"获取任务进度失败: {str(e)}") from e


@router.get("/{task_id}/checkpoints", response_model=dict[str, Any])
async def list_task_checkpoints(
    request: Request,
    task_id: str = FastApiPath(..., description="任务ID"),
    task_manager: UserTaskManager = Depends(get_task_manager)
):
    """
    列出任务的所有断点

    返回任务中所有标记为断点的步骤列表，按步骤序号排序。
    """
    if not CHECKPOINT_AVAILABLE or checkpoint_manager is None:
        raise HTTPException(status_code=503, detail="检查点服务不可用")

    try:
        current_user_id = get_current_user_id(request)

        # 验证任务存在且属于当前用户
        task = await task_manager._task_store.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        if task.get("user_id") != current_user_id:
            raise HTTPException(status_code=403, detail="无权访问此任务")

        checkpoints = checkpoint_manager.list_checkpoints(task_id)
        return {
            "success": True,
            "task_id": task_id,
            "checkpoints": checkpoints,
            "total_count": len(checkpoints)
        }
    except HTTPException:
        raise
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 列出断点失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail=f"列出断点失败: {str(e)}") from e


class CreateCheckpointBody(BaseModel):
    """创建断点请求体"""
    name: str = Field(..., min_length=1, max_length=100, description="断点名称")


@router.post("/{task_id}/checkpoints", response_model=dict[str, Any])
async def create_task_checkpoint(
    request: Request,
    task_id: str = FastApiPath(..., description="任务ID"),
    body: CreateCheckpointBody = Body(...),
    task_manager: UserTaskManager = Depends(get_task_manager)
):
    """
    手动创建断点

    将当前步骤标记为断点，用于后续恢复执行。
    """
    if not CHECKPOINT_AVAILABLE or checkpoint_manager is None:
        raise HTTPException(status_code=503, detail="检查点服务不可用")

    try:
        current_user_id = get_current_user_id(request)

        # 验证任务存在且属于当前用户
        task = await task_manager._task_store.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        if task.get("user_id") != current_user_id:
            raise HTTPException(status_code=403, detail="无权访问此任务")

        # 检查是否有当前执行步骤
        task_state = await checkpoint_manager.get_task(task_id)
        if task_state is None:
            raise HTTPException(status_code=404, detail="任务执行状态不存在")

        current_step = task_state.get_current_step()
        if current_step is None:
            raise HTTPException(status_code=400, detail="任务没有当前执行步骤，无法创建断点")

        step = await checkpoint_manager.save_checkpoint(task_id, body.name)

        checkpoint_id = f"{task_id}_checkpoint_{step.step_number if step else 0}"
        return {
            "success": True,
            "status": "created",
            "task_id": task_id,
            "checkpoint_id": checkpoint_id,
            "name": body.name,
            "step_number": step.step_number if step else 0,
            "message": "断点已创建"
        }
    except HTTPException:
        raise
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 创建断点失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail=f"创建断点失败: {str(e)}") from e


# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════
# 以下代码从 long_task_slots_api.py / workflow_api.py / procedure_learning_api.py 合并
# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════

# ==========================================================
# 3槽位长任务端点（原 long_task_slots_api.py，前缀 /long-tasks -> /tasks）
# ==========================================================

class SlotCreateTaskRequest(BaseModel):
    """创建槽位任务请求"""
    task_name: str = Field(..., min_length=1, max_length=200, description="任务名称")
    task_type: str = Field(..., min_length=1, max_length=100, description="任务类型")
    params: dict[str, Any] = Field(default_factory=dict, description="任务参数")
    user_requirements: str | None = Field(default=None, description="用户需求描述")
    metadata: dict[str, Any] = Field(default_factory=dict, description="额外元数据")

class SlotCreateTaskResponse(BaseModel):
    """创建槽位任务响应"""
    success: bool
    task_id: str | None = None
    slot_id: int | None = None
    message: str
    status: str | None = None

class SlotStatusResponseModel(BaseModel):
    """槽位状态响应"""
    slot_id: int
    status: str
    task_id: str | None = None
    task_name: str | None = None
    task_type: str | None = None
    progress: float = 0.0
    created_at: float | None = None
    updated_at: float | None = None
    started_at: float | None = None
    paused_at: float | None = None
    resumed_at: float | None = None
    ai_understanding: str | None = None
    user_requirements: str | None = None
    error_message: str | None = None

class AllSlotsResponse(BaseModel):
    """所有槽位状态响应"""
    success: bool
    slots: list[SlotStatusResponseModel]
    timestamp: float

class SlotPauseTaskRequest(BaseModel):
    """暂停槽位任务请求"""
    reason: str = Field(default="用户暂停", description="暂停原因")

class SlotPauseTaskResponse(BaseModel):
    """暂停槽位任务响应"""
    success: bool
    slot_id: int
    task_id: str | None = None
    message: str

class SlotResumeTaskRequest(BaseModel):
    """恢复槽位任务请求"""
    ai_confirmation: str = Field(..., min_length=20, description="AI确认百分百理解需求的内容（必须详细）")

class SlotResumeTaskResponse(BaseModel):
    """恢复槽位任务响应"""
    success: bool
    slot_id: int
    task_id: str | None = None
    message: str
    requires_confirmation: bool = False

class SlotModifyTaskRequest(BaseModel):
    """AI修改槽位任务请求"""
    new_params: dict[str, Any] = Field(..., description="新的任务参数（会合并到现有参数）")

class SlotModifyTaskResponse(BaseModel):
    """AI修改槽位任务响应"""
    success: bool
    slot_id: int
    task_id: str | None = None
    updated_params: dict[str, Any]
    message: str

class SlotStopTaskResponse(BaseModel):
    """停止槽位任务响应"""
    success: bool
    slot_id: int
    message: str

class SlotCompleteTaskRequest(BaseModel):
    """完成任务请求"""
    result: dict[str, Any] | None = Field(default=None, description="任务执行结果")

class SlotCompleteTaskResponse(BaseModel):
    """完成任务响应"""
    success: bool
    slot_id: int
    task_id: str | None = None
    message: str

class SlotUpdateProgressRequest(BaseModel):
    """更新进度请求"""
    progress: float = Field(..., ge=0.0, le=100.0, description="进度值 0-100")

class SlotUpdateProgressResponse(BaseModel):
    """更新进度响应"""
    success: bool
    slot_id: int
    task_id: str | None = None
    progress: float
    message: str

class AIUnderstandingRequest(BaseModel):
    """AI更新理解请求"""
    understanding: str = Field(..., min_length=1, description="AI理解内容")

class AIUnderstandingResponse(BaseModel):
    """AI更新理解响应"""
    success: bool
    slot_id: int
    message: str


def get_slots_manager() -> LongTaskSlots:
    """获取3槽位管理器实例"""
    if not SLOTS_AVAILABLE:
        raise HTTPException(status_code=503, detail="长时任务槽位模块不可用")
    return get_long_task_slots()


async def get_slot_owner(slot_id: int, manager: LongTaskSlots) -> str | None:
    """获取槽位任务的所有者"""
    try:
        task = manager.get_slot_status(slot_id)
        if task:
            return task.metadata.get("user_id") if hasattr(task, "metadata") else None
    except Exception as e:
        logger.debug(f"[TaskAPI] 获取槽位{slot_id}所有者失败: {e}")
    return None


def _convert_slot_task_to_response(task: SlotTask) -> SlotStatusResponseModel:
    """将SlotTask转换为API响应格式"""
    return SlotStatusResponseModel(
        slot_id=task.slot_id,
        status=task.status.value,
        task_id=task.task_id,
        task_name=task.task_name,
        task_type=task.task_type,
        progress=task.progress,
        created_at=task.created_at,
        updated_at=task.updated_at,
        started_at=task.started_at,
        paused_at=task.paused_at,
        resumed_at=task.resumed_at,
        ai_understanding=task.ai_understanding,
        user_requirements=task.user_requirements,
        error_message=task.error_message
    )


def _convert_empty_slot_to_response(slot_id: int) -> SlotStatusResponseModel:
    """将空闲槽位转换为API响应格式"""
    return SlotStatusResponseModel(
        slot_id=slot_id,
        status=SlotStatus.IDLE.value,
        task_id=None,
        task_name=None,
        task_type=None,
        progress=0.0
    )


@router.get("/slots", response_model=AllSlotsResponse)
async def get_all_slots(
    manager: LongTaskSlots = Depends(get_slots_manager),
    current_user: str = Depends(get_current_user)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="认证失败：请重新登录")
    try:
        slots = manager.get_all_slots_status()
        slot_responses = []
        for i, task in enumerate(slots, start=1):
            if task:
                slot_responses.append(_convert_slot_task_to_response(task))
            else:
                slot_responses.append(_convert_empty_slot_to_response(i))
        return AllSlotsResponse(success=True, slots=slot_responses, timestamp=time.time())
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 获取所有槽位状态失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail=f"Failed to get slots status: {str(e)}") from e


@router.get("/slots/{slot_id}", response_model=SlotStatusResponseModel)
async def get_slot_status(
    slot_id: int,
    manager: LongTaskSlots = Depends(get_slots_manager),
    current_user: str = Depends(get_current_user)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="认证失败：请重新登录")
    try:
        if slot_id < 1 or slot_id > 3:
            raise HTTPException(status_code=400, detail=f"Invalid slot_id: {slot_id}. Must be 1, 2, or 3.")
        task = manager.get_slot_status(slot_id)
        if task is None:
            return _convert_empty_slot_to_response(slot_id)
        return _convert_slot_task_to_response(task)
    except HTTPException:
        raise
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 获取槽位{slot_id}状态失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail=f"Failed to get slot status: {str(e)}") from e


@router.post("/slots/{slot_id}/create", response_model=SlotCreateTaskResponse)
async def create_slot_task(
    slot_id: int,
    request: SlotCreateTaskRequest,
    manager: LongTaskSlots = Depends(get_slots_manager),
    current_user: str = Depends(get_current_user)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="认证失败：请重新登录")
    try:
        if slot_id < 1 or slot_id > 3:
            raise HTTPException(status_code=400, detail=f"Invalid slot_id: {slot_id}. Must be 1, 2, or 3.")
        task_config = {
            "task_name": request.task_name,
            "task_type": request.task_type,
            "params": request.params,
            "user_requirements": request.user_requirements,
            "metadata": {**request.metadata, "user_id": current_user}
        }
        task_id = manager.create_task(slot_id, task_config)
        return SlotCreateTaskResponse(
            success=True, task_id=task_id, slot_id=slot_id,
            message=f"Task created successfully in slot {slot_id}",
            status=SlotStatus.RUNNING.value
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 创建槽位{slot_id}任务失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail=f"Failed to create task: {str(e)}") from e


@router.post("/slots/{slot_id}/pause", response_model=SlotPauseTaskResponse)
async def pause_slot_task(slot_id: int, request: SlotPauseTaskRequest, manager: LongTaskSlots = Depends(get_slots_manager), current_user: str = Depends(get_current_user)):
    try:
        if slot_id < 1 or slot_id > 3:
            raise HTTPException(status_code=400, detail=f"Invalid slot_id: {slot_id}. Must be 1, 2, or 3.")
        if not current_user:
            raise HTTPException(status_code=401, detail="认证失败：请重新登录")
        slot_owner = await get_slot_owner(slot_id, manager)
        if slot_owner and slot_owner != current_user:
            raise HTTPException(status_code=403, detail="无权限操作此槽位")
        task = manager.get_slot_status(slot_id)
        task_id = task.task_id if task else None
        success = manager.pause_task(slot_id, request.reason)
        if not success:
            raise HTTPException(status_code=400, detail=f"Cannot pause task in slot {slot_id}. Slot may be idle or task not running.")
        return SlotPauseTaskResponse(success=True, slot_id=slot_id, task_id=task_id, message=f"Task in slot {slot_id} paused successfully")
    except HTTPException:
        raise
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 暂停槽位{slot_id}任务失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail=f"Failed to pause task: {str(e)}") from e


@router.post("/slots/{slot_id}/resume", response_model=SlotResumeTaskResponse)
async def resume_slot_task(
    slot_id: int,
    request: SlotResumeTaskRequest,
    manager: LongTaskSlots = Depends(get_slots_manager),
    current_user: str = Depends(get_current_user)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="认证失败：请重新登录")
    try:
        if slot_id < 1 or slot_id > 3:
            raise HTTPException(status_code=400, detail=f"Invalid slot_id: {slot_id}. Must be 1, 2, or 3.")
        slot_owner = await get_slot_owner(slot_id, manager)
        if slot_owner and slot_owner != current_user:
            raise HTTPException(status_code=403, detail="无权限操作此槽位")
        task = manager.get_slot_status(slot_id)
        if task is None:
            raise HTTPException(status_code=400, detail=f"No task in slot {slot_id}")
        task_id = task.task_id
        if not request.ai_confirmation or len(request.ai_confirmation.strip()) < 20:
            return SlotResumeTaskResponse(
                success=False, slot_id=slot_id, task_id=task_id,
                message="AI confirmation is required and must be at least 20 characters (大纲第5条规则)",
                requires_confirmation=True
            )
        success = manager.resume_task(slot_id, request.ai_confirmation)
        if not success:
            raise HTTPException(status_code=400, detail=f"Cannot resume task in slot {slot_id}. Task may not be paused or missing AI confirmation.")
        return SlotResumeTaskResponse(
            success=True, slot_id=slot_id, task_id=task_id,
            message=f"Task in slot {slot_id} resumed successfully with AI confirmation",
            requires_confirmation=False
        )
    except HTTPException:
        raise
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 恢复槽位{slot_id}任务失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail=f"Failed to resume task: {str(e)}") from e


@router.post("/slots/{slot_id}/modify", response_model=SlotModifyTaskResponse)
async def modify_slot_task(
    slot_id: int,
    request: SlotModifyTaskRequest,
    manager: LongTaskSlots = Depends(get_slots_manager),
    current_user: str = Depends(get_current_user)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="认证失败：请重新登录")
    try:
        if slot_id < 1 or slot_id > 3:
            raise HTTPException(status_code=400, detail=f"Invalid slot_id: {slot_id}. Must be 1, 2, or 3.")
        slot_owner = await get_slot_owner(slot_id, manager)
        if slot_owner and slot_owner != current_user:
            raise HTTPException(status_code=403, detail="无权限操作此槽位")
        task = manager.get_slot_status(slot_id)
        if task is None:
            raise HTTPException(status_code=400, detail=f"No task in slot {slot_id}")
        task_id = task.task_id
        success = manager.modify_task_params(slot_id, request.new_params)
        if not success:
            raise HTTPException(status_code=400, detail=f"Failed to modify task parameters in slot {slot_id}")
        updated_task = manager.get_slot_status(slot_id)
        return SlotModifyTaskResponse(
            success=True, slot_id=slot_id, task_id=task_id,
            updated_params=updated_task.params if updated_task else {},
            message=f"Task parameters in slot {slot_id} modified successfully"
        )
    except HTTPException:
        raise
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 修改槽位{slot_id}任务参数失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail=f"Failed to modify task: {str(e)}") from e


@router.post("/slots/{slot_id}/stop", response_model=SlotStopTaskResponse)
async def stop_slot_task(
    slot_id: int,
    manager: LongTaskSlots = Depends(get_slots_manager),
    current_user: str = Depends(get_current_user)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="认证失败：请重新登录")
    try:
        if slot_id < 1 or slot_id > 3:
            raise HTTPException(status_code=400, detail=f"Invalid slot_id: {slot_id}. Must be 1, 2, or 3.")
        slot_owner = await get_slot_owner(slot_id, manager)
        if slot_owner and slot_owner != current_user:
            raise HTTPException(status_code=403, detail="无权限操作此槽位")
        success = manager.stop_task(slot_id)
        if not success:
            raise HTTPException(status_code=400, detail=f"No task to stop in slot {slot_id}")
        return SlotStopTaskResponse(success=True, slot_id=slot_id, message=f"Task in slot {slot_id} stopped successfully")
    except HTTPException:
        raise
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 停止槽位{slot_id}任务失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail=f"Failed to stop task: {str(e)}") from e


@router.post("/slots/{slot_id}/complete", response_model=SlotCompleteTaskResponse)
async def complete_slot_task(
    slot_id: int,
    request: SlotCompleteTaskRequest,
    manager: LongTaskSlots = Depends(get_slots_manager),
    current_user: str = Depends(get_current_user)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="认证失败：请重新登录")
    try:
        if slot_id < 1 or slot_id > 3:
            raise HTTPException(status_code=400, detail=f"Invalid slot_id: {slot_id}. Must be 1, 2, or 3.")
        slot_owner = await get_slot_owner(slot_id, manager)
        if slot_owner and slot_owner != current_user:
            raise HTTPException(status_code=403, detail="无权限操作此槽位")
        task = manager.get_slot_status(slot_id)
        if task is None:
            raise HTTPException(status_code=400, detail=f"No task in slot {slot_id}")
        task_id = task.task_id
        success = await manager.complete_task(slot_id, request.result)
        if not success:
            raise HTTPException(status_code=400, detail=f"Failed to complete task in slot {slot_id}")
        return SlotCompleteTaskResponse(
            success=True, slot_id=slot_id, task_id=task_id,
            message=f"Task in slot {slot_id} completed successfully"
        )
    except HTTPException:
        raise
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 完成槽位{slot_id}任务失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail=f"Failed to complete task: {str(e)}") from e


@router.post("/slots/{slot_id}/progress", response_model=SlotUpdateProgressResponse)
async def update_slot_progress(
    slot_id: int,
    request: SlotUpdateProgressRequest,
    manager: LongTaskSlots = Depends(get_slots_manager),
    current_user: str = Depends(get_current_user)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="认证失败：请重新登录")
    try:
        if slot_id < 1 or slot_id > 3:
            raise HTTPException(status_code=400, detail=f"Invalid slot_id: {slot_id}. Must be 1, 2, or 3.")
        slot_owner = await get_slot_owner(slot_id, manager)
        if slot_owner and slot_owner != current_user:
            raise HTTPException(status_code=403, detail="无权限操作此槽位")
        task = manager.get_slot_status(slot_id)
        if task is None:
            raise HTTPException(status_code=400, detail=f"No task in slot {slot_id}")
        task_id = task.task_id
        success = await manager.update_progress(slot_id, request.progress)
        if not success:
            raise HTTPException(status_code=400, detail=f"Failed to update progress for task in slot {slot_id}")
        updated_task = manager.get_slot_status(slot_id)
        current_progress = updated_task.progress if updated_task else request.progress
        return SlotUpdateProgressResponse(
            success=True, slot_id=slot_id, task_id=task_id,
            progress=current_progress,
            message=f"Progress updated to {current_progress}%"
        )
    except HTTPException:
        raise
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 更新槽位{slot_id}进度失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail=f"Failed to update progress: {str(e)}") from e


@router.post("/slots/{slot_id}/understanding", response_model=AIUnderstandingResponse)
async def update_slot_ai_understanding(
    slot_id: int,
    request: AIUnderstandingRequest,
    manager: LongTaskSlots = Depends(get_slots_manager),
    current_user: str = Depends(get_current_user)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="认证失败：请重新登录")
    try:
        if slot_id < 1 or slot_id > 3:
            raise HTTPException(status_code=400, detail=f"Invalid slot_id: {slot_id}. Must be 1, 2, or 3.")
        slot_owner = await get_slot_owner(slot_id, manager)
        if slot_owner and slot_owner != current_user:
            raise HTTPException(status_code=403, detail="无权限操作此槽位")
        success = manager.update_ai_understanding(slot_id, request.understanding)
        if not success:
            raise HTTPException(status_code=400, detail=f"No task in slot {slot_id}")
        return AIUnderstandingResponse(success=True, slot_id=slot_id, message=f"AI understanding updated for slot {slot_id}")
    except HTTPException:
        raise
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 更新槽位{slot_id}AI理解失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail=f"Failed to update AI understanding: {str(e)}") from e


@router.get("/slots/{slot_id}/ai-summary")
async def get_slot_summary_for_ai(
    slot_id: int,
    manager: LongTaskSlots = Depends(get_slots_manager),
    current_user: str = Depends(get_current_user)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="认证失败：请重新登录")
    try:
        if slot_id < 1 or slot_id > 3:
            raise HTTPException(status_code=400, detail=f"Invalid slot_id: {slot_id}. Must be 1, 2, or 3.")
        slot_owner = await get_slot_owner(slot_id, manager)
        if slot_owner and slot_owner != current_user:
            raise HTTPException(status_code=403, detail="无权限访问此槽位")
        summary = manager.get_slot_summary_for_ai(slot_id)
        if summary is None:
            raise HTTPException(status_code=500, detail=f"Failed to get summary for slot {slot_id}")
        return {"success": True, "data": summary}
    except HTTPException:
        raise
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 获取槽位{slot_id}AI摘要失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail=f"Failed to get AI summary: {str(e)}") from e


@router.get("/slots/ai-summary")
async def get_all_slots_summary_for_ai(
    manager: LongTaskSlots = Depends(get_slots_manager),
    current_user: str = Depends(get_current_user)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="认证失败：请重新登录")
    try:
        summary = manager.get_all_slots_summary_for_ai()
        return {"success": True, "data": summary}
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 获取所有槽位AI摘要失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail=f"Failed to get AI summary: {str(e)}") from e


# ==========================================================
# 工作流端点（原 workflow_api.py，前缀 /workflows -> /tasks/workflows）
# ==========================================================

class WorkflowStepModel(BaseModel):
    """工作流步骤模型"""
    step_id: str | None = Field(default=None, description="步骤ID（可选，自动生成）")
    name: str = Field(..., min_length=1, max_length=200, description="步骤名称")
    description: str = Field(default="", max_length=1000, description="步骤描述")
    tool_id: str = Field(..., min_length=1, description="工具ID")
    tool_params: dict[str, Any] = Field(default_factory=dict, description="工具参数")
    inputs: dict[str, str] = Field(default_factory=dict, description="输入变量映射")
    outputs: dict[str, str] = Field(default_factory=dict, description="输出变量映射")
    output_mapping: dict[str, str] = Field(default_factory=dict, description="结果字段映射")
    is_critical: bool = Field(default=True, description="是否为关键步骤")
    step_category: str = Field(default="action", description="步骤类别: check/launch/action/transform/verify/save")
    execution_mode: str = Field(default="sequential", description="执行模式: sequential/parallel/conditional")
    condition: str | None = Field(default=None, description="执行条件表达式")
    on_success: str | None = Field(default=None, description="成功时跳转步骤ID")
    on_failure: str | None = Field(default=None, description="失败时跳转步骤ID")
    requires_confirmation: bool = Field(default=False, description="是否需要用户确认")
    confirmation_message: str = Field(default="", description="确认提示消息")
    allow_modification: bool = Field(default=True, description="是否允许用户修改")
    timeout: int = Field(default=60, ge=1, le=3600, description="超时时间（秒）")
    max_retries: int = Field(default=3, ge=0, le=10, description="最大重试次数")


class WorkflowCreateRequest(BaseModel):
    """创建工作流请求"""
    workflow_id: str | None = Field(default=None, description="工作流ID（可选，自动生成）")
    name: str = Field(..., min_length=1, max_length=200, description="工作流名称")
    description: str = Field(default="", max_length=2000, description="工作流描述")
    steps: list[WorkflowStepModel] = Field(..., min_items=1, description="工作流步骤列表")
    variables: dict[str, Any] = Field(default_factory=dict, description="全局变量默认值")
    execution_strategy: str = Field(default="sequential", description="执行策略: sequential/parallel/adaptive")
    max_retries: int = Field(default=3, ge=0, le=10, description="最大重试次数")
    timeout_per_step: int = Field(default=60, ge=1, le=3600, description="每步超时时间（秒）")
    perception_config: dict[str, Any] | None = Field(default=None, description="感知配置")


class WorkflowResponse(BaseModel):
    """工作流响应"""
    workflow_id: str
    name: str
    description: str
    step_count: int
    created_at: float
    created_by: str
    version: str


class WorkflowDetailResponse(BaseModel):
    """工作流详情响应"""
    workflow_id: str
    name: str
    description: str
    steps: list[dict[str, Any]]
    variables: dict[str, Any]
    execution_strategy: str
    max_retries: int
    timeout_per_step: int
    perception_config: dict[str, Any]
    created_at: float
    created_by: str
    version: str


class WorkflowListResponse(BaseModel):
    """工作流列表响应"""
    success: bool
    workflows: list[WorkflowResponse]
    total: int


class WorkflowExecuteRequest(BaseModel):
    """执行工作流请求"""
    initial_vars: dict[str, Any] = Field(default_factory=dict, description="初始变量")
    mode: str = Field(default="slot", description="执行模式: default/slot/agent_loop")


class WorkflowExecuteResponse(BaseModel):
    """执行工作流响应"""
    success: bool
    execution_id: str
    workflow_id: str
    status: str
    message: str
    slot_id: int | None = None


class ExecutionStatusResponse(BaseModel):
    """执行状态响应"""
    execution_id: str
    workflow_id: str
    status: str
    current_step: int
    total_steps: int
    progress: float
    variables: dict[str, Any]
    current_step_info: dict[str, Any] | None
    can_modify: bool
    created_at: float
    started_at: float | None
    completed_at: float | None


class ExecutionModifyRequest(BaseModel):
    """修改执行请求"""
    skip_steps: list[str] = Field(default_factory=list, description="要跳过的步骤ID列表")
    modify_params: dict[str, dict[str, Any]] = Field(default_factory=dict, description="修改的步骤参数")
    add_steps: list[dict[str, Any]] = Field(default_factory=list, description="要添加的步骤")
    update_variables: dict[str, Any] = Field(default_factory=dict, description="更新的变量")


class ExecutionModifyResponse(BaseModel):
    """修改执行响应"""
    success: bool
    execution_id: str
    message: str
    modifications_applied: list[str]


class ExecutionActionResponse(BaseModel):
    """执行操作响应（暂停/恢复/取消）"""
    success: bool
    execution_id: str
    status: str
    message: str


def get_workflow_engine_dep() -> WorkflowEngine:
    """获取工作流引擎实例"""
    if not WORKFLOW_AVAILABLE:
        raise HTTPException(status_code=503, detail="工作流模块不可用")
    try:
        return get_workflow_engine()
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 获取工作流引擎失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail="初始化工作流引擎失败") from e


def get_workflow_executor_dep() -> WorkflowExecutor:
    """获取工作流执行器实例"""
    if not WORKFLOW_AVAILABLE:
        raise HTTPException(status_code=503, detail="工作流模块不可用")
    try:
        return get_workflow_executor()
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 获取工作流执行器失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail="初始化工作流执行器失败") from e


def _convert_step_to_model(step: WorkflowStep) -> dict[str, Any]:
    """将 WorkflowStep 转换为字典"""
    return {
        "step_id": step.step_id,
        "name": step.name,
        "description": step.description,
        "tool_id": step.tool_id,
        "tool_params": step.tool_params,
        "inputs": step.inputs,
        "outputs": step.outputs,
        "output_mapping": step.output_mapping,
        "is_critical": step.is_critical,
        "step_category": step.step_category,
        "execution_mode": step.execution_mode,
        "condition": step.condition,
        "on_success": step.on_success,
        "on_failure": step.on_failure,
        "requires_confirmation": step.requires_confirmation,
        "confirmation_message": step.confirmation_message,
        "allow_modification": step.allow_modification,
        "timeout": step.timeout,
        "max_retries": step.max_retries,
        "status": step.status.value if step.status else None
    }


def _convert_step_model_to_workflow(step_model: WorkflowStepModel) -> WorkflowStep:
    """将 Pydantic 模型转换为 WorkflowStep"""
    return WorkflowStep(
        step_id=step_model.step_id or f"step_{int(time.time() * 1000)}",
        name=step_model.name,
        description=step_model.description,
        tool_id=step_model.tool_id,
        tool_params=step_model.tool_params,
        inputs=step_model.inputs,
        outputs=step_model.outputs,
        output_mapping=step_model.output_mapping,
        is_critical=step_model.is_critical,
        step_category=step_model.step_category,
        execution_mode=step_model.execution_mode,
        condition=step_model.condition,
        on_success=step_model.on_success,
        on_failure=step_model.on_failure,
        requires_confirmation=step_model.requires_confirmation,
        confirmation_message=step_model.confirmation_message,
        allow_modification=step_model.allow_modification,
        timeout=step_model.timeout,
        max_retries=step_model.max_retries
    )


def verify_workflow_ownership(workflow_id: str, engine: WorkflowEngine, current_user_id: str):
    """验证工作流所有权，返回工作流定义或抛出 403/404"""
    workflow = engine.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail=f"工作流不存在: {workflow_id}")
    if workflow.created_by != current_user_id:
        raise HTTPException(status_code=403, detail="无权访问该工作流")
    return workflow


def verify_execution_ownership(execution_id: str, engine: WorkflowEngine, current_user_id: str):
    """验证工作流执行实例所有权，返回执行实例或抛出 403/404"""
    execution = engine.get_execution(execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail=f"执行实例不存在: {execution_id}")
    if execution.user_id != current_user_id:
        raise HTTPException(status_code=403, detail="无权访问该执行实例")
    return execution


@router.get("/workflows", response_model=WorkflowListResponse)
async def list_workflows(request: Request, engine: WorkflowEngine = Depends(get_workflow_engine_dep), user_id: str = Depends(get_current_user_id)):
    try:
        workflows = engine.list_workflows()
        workflow_list = []
        for wf in workflows:
            full_wf = engine.get_workflow(wf["workflow_id"])
            if not full_wf or full_wf.created_by != user_id:
                continue
            workflow_list.append(
                WorkflowResponse(
                    workflow_id=wf["workflow_id"],
                    name=wf["name"],
                    description=wf["description"],
                    step_count=wf["step_count"],
                    created_at=wf["created_at"],
                    created_by=full_wf.created_by,
                    version=full_wf.version
                )
            )
        return WorkflowListResponse(success=True, workflows=workflow_list, total=len(workflow_list))
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 获取工作流列表失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail=f"获取工作流列表失败: {str(e)}") from e


@router.post("/workflows", response_model=WorkflowResponse)
async def create_workflow(request: Request, request_data: WorkflowCreateRequest, engine: WorkflowEngine = Depends(get_workflow_engine_dep), user_id: str = Depends(get_current_user_id)):
    try:
        steps = [_convert_step_model_to_workflow(s) for s in request_data.steps]
        workflow = WorkflowDefinition(
            workflow_id=request_data.workflow_id or f"wf_{int(time.time() * 1000)}",
            name=request_data.name,
            description=request_data.description,
            steps=steps,
            variables=request_data.variables,
            execution_strategy=request_data.execution_strategy,
            max_retries=request_data.max_retries,
            timeout_per_step=request_data.timeout_per_step,
            perception_config=request_data.perception_config or {
                "enable_visual": True,
                "enable_system": False,
                "screenshot_before_step": [],
                "screenshot_after_step": [],
                "verification_required": ["transform", "save"]
            },
            created_by=user_id
        )
        workflow_id = engine.create_workflow(workflow)
        return WorkflowResponse(
            workflow_id=workflow_id,
            name=workflow.name,
            description=workflow.description,
            step_count=len(workflow.steps),
            created_at=workflow.created_at,
            created_by=user_id,
            version=workflow.version
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 创建工作流失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail=f"Failed to create workflow: {str(e)}") from e


@router.get("/workflows/{workflow_id}", response_model=WorkflowDetailResponse)
async def get_workflow(request: Request, workflow_id: str, engine: WorkflowEngine = Depends(get_workflow_engine_dep), user_id: str = Depends(get_current_user_id)):
    try:
        workflow = verify_workflow_ownership(workflow_id, engine, user_id)
        return WorkflowDetailResponse(
            workflow_id=workflow.workflow_id,
            name=workflow.name,
            description=workflow.description,
            steps=[_convert_step_to_model(s) for s in workflow.steps],
            variables=workflow.variables,
            execution_strategy=workflow.execution_strategy,
            max_retries=workflow.max_retries,
            timeout_per_step=workflow.timeout_per_step,
            perception_config=workflow.perception_config,
            created_at=workflow.created_at,
            created_by=workflow.created_by,
            version=workflow.version
        )
    except HTTPException:
        raise
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 获取工作流详情失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail=f"Failed to get workflow: {str(e)}") from e


@router.delete("/workflows/{workflow_id}", response_model=dict[str, Any])
async def delete_workflow(request: Request, workflow_id: str, engine: WorkflowEngine = Depends(get_workflow_engine_dep), user_id: str = Depends(get_current_user_id)):
    try:
        verify_workflow_ownership(workflow_id, engine, user_id)
        success = engine.delete_workflow(workflow_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"工作流不存在: {workflow_id}")
        return {"success": True, "message": f"工作流 {workflow_id} 已删除"}
    except HTTPException:
        raise
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 删除工作流失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail=f"删除工作流失败: {str(e)}") from e


@router.post("/workflows/{workflow_id}/execute", response_model=WorkflowExecuteResponse)
async def execute_workflow(request: Request, workflow_id: str, request_data: WorkflowExecuteRequest, engine: WorkflowEngine = Depends(get_workflow_engine_dep), user_id: str = Depends(get_current_user_id)):
    try:
        verify_workflow_ownership(workflow_id, engine, user_id)
        execution_id = await engine.execute_workflow(
            workflow_id=workflow_id,
            initial_vars=request_data.initial_vars,
            user_id=user_id,
            mode=request_data.mode
        )
        execution = engine.get_execution(execution_id)
        return WorkflowExecuteResponse(
            success=True,
            execution_id=execution_id,
            workflow_id=workflow_id,
            status=execution.status.value if execution else "unknown",
            message="工作流执行已启动",
            slot_id=execution.slot_id if execution else None
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 执行工作流失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail=f"执行工作流失败: {str(e)}") from e


@router.get("/workflows/executions/{execution_id}", response_model=ExecutionStatusResponse)
async def get_execution_status(request: Request, execution_id: str, engine: WorkflowEngine = Depends(get_workflow_engine_dep), user_id: str = Depends(get_current_user_id)):
    try:
        verify_execution_ownership(execution_id, engine, user_id)
        status = engine.get_execution_status(execution_id)
        if "error" in status:
            raise HTTPException(status_code=404, detail=status["error"])
        return ExecutionStatusResponse(
            execution_id=status["execution_id"],
            workflow_id=status.get("workflow_id", ""),
            status=status["status"],
            current_step=status["current_step"],
            total_steps=status["total_steps"],
            progress=status["progress"],
            variables=status["variables"],
            current_step_info=status.get("current_step_info"),
            can_modify=status["can_modify"],
            created_at=status["created_at"],
            started_at=status.get("started_at"),
            completed_at=status.get("completed_at")
        )
    except HTTPException:
        raise
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 获取执行状态失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail=f"获取执行状态失败: {str(e)}") from e


@router.post("/workflows/executions/{execution_id}/pause", response_model=ExecutionActionResponse)
async def pause_execution(request: Request, execution_id: str, reason: str = "用户暂停", engine: WorkflowEngine = Depends(get_workflow_engine_dep), user_id: str = Depends(get_current_user_id)):
    try:
        verify_execution_ownership(execution_id, engine, user_id)
        success = engine.pause_execution(execution_id, reason)
        if not success:
            raise HTTPException(status_code=400, detail="无法暂停执行，该执行可能未运行或不存在")
        return ExecutionActionResponse(success=True, execution_id=execution_id, status="paused", message=f"执行已暂停: {reason}")
    except HTTPException:
        raise
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 暂停执行失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail=f"Failed to pause execution: {str(e)}") from e


@router.post("/workflows/executions/{execution_id}/resume", response_model=ExecutionActionResponse)
async def resume_execution(request: Request, execution_id: str, engine: WorkflowEngine = Depends(get_workflow_engine_dep), user_id: str = Depends(get_current_user_id)):
    try:
        verify_execution_ownership(execution_id, engine, user_id)
        success = engine.resume_execution(execution_id)
        if not success:
            raise HTTPException(status_code=400, detail="无法恢复执行，该执行可能未暂停或不存在")
        return ExecutionActionResponse(success=True, execution_id=execution_id, status="running", message="执行已恢复")
    except HTTPException:
        raise
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 恢复执行失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail=f"恢复执行失败: {str(e)}") from e


@router.post("/workflows/executions/{execution_id}/modify", response_model=ExecutionModifyResponse)
async def modify_execution(request: Request, execution_id: str, request_data: ExecutionModifyRequest, engine: WorkflowEngine = Depends(get_workflow_engine_dep), user_id: str = Depends(get_current_user_id)):
    try:
        verify_execution_ownership(execution_id, engine, user_id)
        modifications = {
            "skip_steps": request_data.skip_steps,
            "modify_params": request_data.modify_params,
            "add_steps": request_data.add_steps,
            "update_variables": request_data.update_variables
        }
        modifications = {k: v for k, v in modifications.items() if v}
        success = engine.modify_execution(execution_id, modifications)
        if not success:
            raise HTTPException(status_code=400, detail="无法修改执行，该执行可能不在可修改状态或不存在")
        return ExecutionModifyResponse(success=True, execution_id=execution_id, message="执行已修改", modifications_applied=list(modifications.keys()))
    except HTTPException:
        raise
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 修改执行失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail=f"修改执行失败: {str(e)}") from e


@router.post("/workflows/executions/{execution_id}/cancel", response_model=ExecutionActionResponse)
async def cancel_execution(request: Request, execution_id: str, engine: WorkflowEngine = Depends(get_workflow_engine_dep), user_id: str = Depends(get_current_user_id)):
    try:
        verify_execution_ownership(execution_id, engine, user_id)
        success = engine.cancel_execution(execution_id)
        if not success:
            raise HTTPException(status_code=400, detail="无法取消执行，该执行可能已完成/失败或不存在")
        return ExecutionActionResponse(success=True, execution_id=execution_id, status="cancelled", message="执行已取消")
    except HTTPException:
        raise
    except Exception as e:
        diagnostic_except_handler(e, context="[TaskAPI] 取消执行失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail=f"取消执行失败: {str(e)}") from e


# ==========================================================
# 演示学习端点（原 procedure_learning_api.py，前缀 /procedures -> /tasks/procedures）
# ==========================================================

class ProcStartRecordingResponse(BaseModel):
    success: bool = Field(..., description="是否成功")
    recording_id: str = Field(..., description="录制会话ID")
    message: str = Field(..., description="状态消息")
    started_at: str = Field(..., description="开始时间(ISO格式)")

class ProcStopRecordingResponse(BaseModel):
    success: bool = Field(..., description="是否成功")
    recording_id: str = Field(..., description="录制会话ID")
    procedure_id: str | None = Field(default=None, description="学习到的流程ID")
    operation_count: int = Field(..., description="录制的操作数量")
    message: str = Field(..., description="状态消息")
    stopped_at: str = Field(..., description="停止时间(ISO格式)")

class ProcRecordingStatusResponse(BaseModel):
    is_recording: bool = Field(..., description="是否正在录制")
    recording_id: str | None = Field(default=None, description="当前录制ID")
    operation_count: int = Field(..., description="已录制操作数量")
    duration_seconds: float = Field(..., description="录制时长（秒）")

class ProcProcedureStepInfo(BaseModel):
    step_id: str = Field(..., description="步骤ID")
    step_number: int = Field(..., description="步骤序号")
    description: str = Field(..., description="步骤描述")
    tool_name: str = Field(..., description="使用的工具名")
    expected_result: str | None = Field(default=None, description="预期结果")

class ProcProcedureInfo(BaseModel):
    procedure_id: str = Field(..., description="流程ID")
    name: str = Field(..., description="流程名称")
    intent: str = Field(..., description="意图关键词")
    description: str = Field(..., description="流程描述")
    step_count: int = Field(..., description="步骤数量")
    success_rate: float = Field(..., description="成功率(0-1)")
    usage_count: int = Field(..., description="使用次数")
    is_active: bool = Field(..., description="是否激活")
    tags: list[str] = Field(default_factory=list, description="标签列表")
    created_at: str = Field(..., description="创建时间(ISO格式)")
    updated_at: str = Field(..., description="更新时间(ISO格式)")

class ProcProcedureDetailResponse(BaseModel):
    procedure_id: str = Field(..., description="流程ID")
    name: str = Field(..., description="流程名称")
    intent: str = Field(..., description="意图关键词")
    description: str = Field(..., description="流程描述")
    steps: list[ProcProcedureStepInfo] = Field(default_factory=list, description="步骤列表")
    success_rate: float = Field(..., description="成功率")
    usage_count: int = Field(..., description="使用次数")
    success_count: int = Field(..., description="成功次数")
    avg_execution_time: float = Field(..., description="平均执行时间(秒)")
    is_active: bool = Field(..., description="是否激活")
    tags: list[str] = Field(default_factory=list, description="标签列表")
    parameters: dict[str, Any] = Field(default_factory=dict, description="可配置参数")
    created_at: str = Field(..., description="创建时间(ISO格式)")
    updated_at: str = Field(..., description="更新时间(ISO格式)")

class ProcProcedureListResponse(BaseModel):
    procedures: list[ProcProcedureInfo] = Field(default_factory=list, description="流程列表")
    total_count: int = Field(..., description="流程总数")

class ProcExecuteProcedureRequest(BaseModel):
    session_id: str = Field(..., description="任务会话ID")
    parameters: dict[str, Any] | None = Field(default=None, description="运行时参数")

class ProcExecuteProcedureResponse(BaseModel):
    success: bool = Field(..., description="是否成功启动")
    session_id: str = Field(..., description="任务会话ID")
    procedure_id: str = Field(..., description="流程ID")
    message: str = Field(..., description="状态消息")
    started_at: str = Field(..., description="开始时间(ISO格式)")

class ProcProcedureSearchResponse(BaseModel):
    intent: str = Field(..., description="搜索意图")
    procedures: list[ProcProcedureInfo] = Field(default_factory=list, description="匹配的流程列表")
    total_count: int = Field(..., description="匹配数量")

class ProcSessionStatusResponse(BaseModel):
    session_id: str = Field(..., description="会话ID")
    task_id: str | None = Field(default=None, description="任务ID")
    intent: str | None = Field(default=None, description="原始意图")
    mode: str = Field(..., description="当前模式: ai_executing/user_demonstrating/chatting/paused")
    procedure_id: str | None = Field(default=None, description="关联的流程ID")
    recording_id: str | None = Field(default=None, description="录制ID")
    created_at: str | None = Field(default=None, description="创建时间(ISO格式)")

class ProcPauseSessionRequest(BaseModel):
    reason: str = Field(default="用户请求暂停", description="暂停原因")

class ProcPauseSessionResponse(BaseModel):
    success: bool = Field(..., description="是否成功")
    session_id: str = Field(..., description="会话ID")
    mode: str = Field(..., description="当前模式")
    reason: str | None = Field(default=None, description="暂停原因")
    message: str = Field(..., description="状态消息")

class ProcResumeSessionResponse(BaseModel):
    success: bool = Field(..., description="是否成功")
    session_id: str = Field(..., description="会话ID")
    mode: str = Field(..., description="当前模式")
    message: str = Field(..., description="状态消息")

class ProcStandardErrorResponse(BaseModel):
    detail: str = Field(..., description="错误详情")


def verify_procedure_learning_available():
    """验证演示学习系统是否可用"""
    if not PROCEDURE_LEARNING_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="演示学习服务不可用"
        )


def _get_connection_manager():
    """延迟导入WebSocket连接管理器（避免循环导入）"""
    try:
        from api.cloud_api import connection_manager
        return connection_manager
    except ImportError:
        try:
            from .cloud_api import connection_manager
            return connection_manager
        except ImportError:
            return None


async def broadcast_procedure_event(event_type: str, data: dict[str, Any]):
    """广播演示学习相关事件到WebSocket客户端"""
    cm = _get_connection_manager()
    if not cm:
        return
    try:
        message = {
            "type": "procedure_learning_event",
            "event": event_type,
            "data": data,
            "timestamp": datetime.now().isoformat()
        }
        await cm.broadcast(message)
    except Exception as e:
        logger.warning(f"[TaskAPI] WebSocket广播失败: {e}")


@router.post("/procedures/recordings/start", response_model=ProcStartRecordingResponse, responses={503: {"model": ProcStandardErrorResponse, "description": "服务不可用"}, 500: {"model": ProcStandardErrorResponse, "description": "服务器错误"}})
async def start_recording(current_user: str = Depends(get_current_user)):
    verify_procedure_learning_available()
    try:
        recorder = get_operation_recorder()
        recording_id = recorder.start_recording(context={"user_id": current_user, "action": "manual_start"})
        await broadcast_procedure_event("recording_started", {"recording_id": recording_id, "user_id": current_user})
        return ProcStartRecordingResponse(success=True, recording_id=recording_id, message="录制已开始", started_at=datetime.now().isoformat())
    except Exception as e:
        diagnostic_except_handler(e, context="[SILENT_FAILURE_BLOCKED] 开始录制失败", logger_instance=logger)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"开始录制失败: {str(e)}") from e


@router.post("/procedures/recordings/stop", response_model=ProcStopRecordingResponse, responses={400: {"model": ProcStandardErrorResponse, "description": "当前没有录制"}, 503: {"model": ProcStandardErrorResponse, "description": "服务不可用"}, 500: {"model": ProcStandardErrorResponse, "description": "服务器错误"}})
async def stop_recording(current_user: str = Depends(get_current_user)):
    verify_procedure_learning_available()
    try:
        recorder = get_operation_recorder()
        if not recorder.is_recording:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前没有正在进行的录制")
        recording_id = recorder.recording_id
        operations = recorder.stop_recording()
        procedure_id = None
        if operations:
            try:
                from core.procedure_learning import get_demonstration_learner
                learner = get_demonstration_learner()
                procedure = learner.learn_from_recording(
                    operations=operations,
                    task_description=f"录制于 {datetime.now().isoformat()}",
                    context={"recording_id": recording_id, "user_id": current_user}
                )
                library = get_procedure_library()
                procedure_id = library.add_procedure(procedure)
            except Exception as learn_error:
                logger.warning(f"[TaskAPI] 学习流程失败: {learn_error}")
        await broadcast_procedure_event("recording_stopped", {
            "recording_id": recording_id, "procedure_id": procedure_id,
            "operation_count": len(operations), "user_id": current_user
        })
        return ProcStopRecordingResponse(
            success=True, recording_id=recording_id, procedure_id=procedure_id,
            operation_count=len(operations), message="录制已停止" + ("，流程已学习" if procedure_id else ""),
            stopped_at=datetime.now().isoformat()
        )
    except HTTPException:
        raise
    except Exception as e:
        diagnostic_except_handler(e, context="[SILENT_FAILURE_BLOCKED] 停止录制失败", logger_instance=logger)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"停止录制失败: {str(e)}") from e


@router.get("/procedures/recordings/status", response_model=ProcRecordingStatusResponse, responses={503: {"model": ProcStandardErrorResponse, "description": "服务不可用"}})
async def get_recording_status(current_user: str = Depends(get_current_user)):
    verify_procedure_learning_available()
    try:
        recorder = get_operation_recorder()
        duration = 0.0
        if recorder.is_recording and recorder.start_time:
            duration = datetime.now().timestamp() - recorder.start_time
        return ProcRecordingStatusResponse(
            is_recording=recorder.is_recording,
            recording_id=recorder.recording_id,
            operation_count=len(recorder.operations),
            duration_seconds=round(duration, 2)
        )
    except Exception as e:
        diagnostic_except_handler(e, context="[SILENT_FAILURE_BLOCKED] 获取录制状态失败", logger_instance=logger)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"获取录制状态失败: {str(e)}") from e


@router.get("/procedures", response_model=ProcProcedureListResponse, responses={503: {"model": ProcStandardErrorResponse, "description": "服务不可用"}})
async def list_procedures(active_only: bool = Query(True, description="仅显示激活的流程"), sort_by: str = Query("usage_count", description="排序字段: usage_count/success_rate/updated_at"), current_user: str = Depends(get_current_user)):
    verify_procedure_learning_available()
    try:
        library = get_procedure_library()
        procedures = library.list_procedures(active_only=active_only, sort_by=sort_by)
        procedure_infos = []
        for p in procedures:
            procedure_infos.append(ProcProcedureInfo(
                procedure_id=p.procedure_id, name=p.name, intent=p.intent,
                description=p.description, step_count=len(p.steps),
                success_rate=p.get_success_rate(), usage_count=p.usage_count,
                is_active=p.is_active, tags=p.tags,
                created_at=datetime.fromtimestamp(p.created_at).isoformat(),
                updated_at=datetime.fromtimestamp(p.updated_at).isoformat()
            ))
        return ProcProcedureListResponse(procedures=procedure_infos, total_count=len(procedure_infos))
    except Exception as e:
        diagnostic_except_handler(e, context="[SILENT_FAILURE_BLOCKED] 列出流程失败", logger_instance=logger)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"列出流程失败: {str(e)}") from e


@router.get("/procedures/search", response_model=ProcProcedureSearchResponse, responses={503: {"model": ProcStandardErrorResponse, "description": "服务不可用"}})
async def search_procedures(intent: str = Query(..., description="意图关键词，如'定机票'"), limit: int = Query(5, ge=1, le=20, description="返回数量限制"), current_user: str = Depends(get_current_user)):
    verify_procedure_learning_available()
    try:
        library = get_procedure_library()
        procedures = library.find_by_intent(intent, limit=limit)
        procedure_infos = []
        for p in procedures:
            procedure_infos.append(ProcProcedureInfo(
                procedure_id=p.procedure_id, name=p.name, intent=p.intent,
                description=p.description, step_count=len(p.steps),
                success_rate=p.get_success_rate(), usage_count=p.usage_count,
                is_active=p.is_active, tags=p.tags,
                created_at=datetime.fromtimestamp(p.created_at).isoformat(),
                updated_at=datetime.fromtimestamp(p.updated_at).isoformat()
            ))
        return ProcProcedureSearchResponse(intent=intent, procedures=procedure_infos, total_count=len(procedure_infos))
    except Exception as e:
        diagnostic_except_handler(e, context="[SILENT_FAILURE_BLOCKED] 搜索流程失败", logger_instance=logger)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"搜索流程失败: {str(e)}") from e


@router.get("/procedures/{procedure_id}", response_model=ProcProcedureDetailResponse, responses={404: {"model": ProcStandardErrorResponse, "description": "流程不存在"}, 503: {"model": ProcStandardErrorResponse, "description": "服务不可用"}})
async def get_procedure_detail(procedure_id: str, current_user: str = Depends(get_current_user)):
    verify_procedure_learning_available()
    try:
        library = get_procedure_library()
        procedure = library.get_procedure(procedure_id)
        if not procedure:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="流程不存在")
        step_infos = []
        for step in procedure.steps:
            step_infos.append(ProcProcedureStepInfo(
                step_id=step.step_id, step_number=step.step_number,
                description=step.description, tool_name=step.tool_name,
                expected_result=step.expected_result
            ))
        return ProcProcedureDetailResponse(
            procedure_id=procedure.procedure_id, name=procedure.name,
            intent=procedure.intent, description=procedure.description,
            steps=step_infos, success_rate=procedure.get_success_rate(),
            usage_count=procedure.usage_count, success_count=procedure.success_count,
            avg_execution_time=procedure.avg_execution_time, is_active=procedure.is_active,
            tags=procedure.tags, parameters=procedure.parameters,
            created_at=datetime.fromtimestamp(procedure.created_at).isoformat(),
            updated_at=datetime.fromtimestamp(procedure.updated_at).isoformat()
        )
    except HTTPException:
        raise
    except Exception as e:
        diagnostic_except_handler(e, context="[SILENT_FAILURE_BLOCKED] 获取流程详情失败", logger_instance=logger)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"获取流程详情失败: {str(e)}") from e


@router.post("/procedures/{procedure_id}/execute", response_model=ProcExecuteProcedureResponse, responses={404: {"model": ProcStandardErrorResponse, "description": "流程不存在"}, 400: {"model": ProcStandardErrorResponse, "description": "请求参数错误"}, 503: {"model": ProcStandardErrorResponse, "description": "服务不可用"}})
async def execute_procedure(procedure_id: str, request: ProcExecuteProcedureRequest, current_user: str = Depends(get_current_user)):
    verify_procedure_learning_available()
    try:
        library = get_procedure_library()
        procedure = library.get_procedure(procedure_id)
        if not procedure:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="流程不存在")
        coordinator = get_task_coordinator()
        success = coordinator.execute_learned_procedure(
            session_id=request.session_id, procedure_id=procedure_id, parameters=request.parameters
        )
        if not success:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="流程执行启动失败")
        await broadcast_procedure_event("procedure_executed", {
            "procedure_id": procedure_id, "session_id": request.session_id, "user_id": current_user
        })
        return ProcExecuteProcedureResponse(
            success=True, session_id=request.session_id, procedure_id=procedure_id,
            message="流程执行已启动", started_at=datetime.now().isoformat()
        )
    except HTTPException:
        raise
    except Exception as e:
        diagnostic_except_handler(e, context="[SILENT_FAILURE_BLOCKED] 执行流程失败", logger_instance=logger)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"执行流程失败: {str(e)}") from e


@router.delete("/procedures/{procedure_id}", responses={404: {"model": ProcStandardErrorResponse, "description": "流程不存在"}, 503: {"model": ProcStandardErrorResponse, "description": "服务不可用"}})
async def delete_procedure(procedure_id: str, current_user: str = Depends(get_current_user)):
    verify_procedure_learning_available()
    try:
        library = get_procedure_library()
        procedure = library.get_procedure(procedure_id)
        if not procedure:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="流程不存在")
        success = library.delete_procedure(procedure_id)
        if not success:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="删除流程失败")
        await broadcast_procedure_event("procedure_deleted", {"procedure_id": procedure_id, "user_id": current_user})
        return {"success": True, "procedure_id": procedure_id, "message": "流程已删除"}
    except HTTPException:
        raise
    except Exception as e:
        diagnostic_except_handler(e, context="[SILENT_FAILURE_BLOCKED] 删除流程失败", logger_instance=logger)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"删除流程失败: {str(e)}") from e


@router.post("/procedures/sessions/{session_id}/pause", response_model=ProcPauseSessionResponse, responses={404: {"model": ProcStandardErrorResponse, "description": "会话不存在"}, 503: {"model": ProcStandardErrorResponse, "description": "服务不可用"}})
async def pause_procedure_session(session_id: str, request: ProcPauseSessionRequest, current_user: str = Depends(get_current_user)):
    verify_procedure_learning_available()
    try:
        coordinator = get_task_coordinator()
        session_status = coordinator.get_session_status(session_id)
        if not session_status:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
        success = coordinator.pause_for_chat(session_id, reason=request.reason)
        if not success:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="暂停任务失败")
        await broadcast_procedure_event("session_paused", {"session_id": session_id, "reason": request.reason, "user_id": current_user})
        return ProcPauseSessionResponse(success=True, session_id=session_id, mode="chatting", reason=request.reason, message="任务已暂停，进入聊天模式")
    except HTTPException:
        raise
    except Exception as e:
        diagnostic_except_handler(e, context="[SILENT_FAILURE_BLOCKED] 暂停会话失败", logger_instance=logger)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"暂停会话失败: {str(e)}") from e


@router.post("/procedures/sessions/{session_id}/resume", response_model=ProcResumeSessionResponse, responses={404: {"model": ProcStandardErrorResponse, "description": "会话不存在"}, 400: {"model": ProcStandardErrorResponse, "description": "无法恢复任务"}, 503: {"model": ProcStandardErrorResponse, "description": "服务不可用"}})
async def resume_procedure_session(session_id: str, current_user: str = Depends(get_current_user)):
    verify_procedure_learning_available()
    try:
        coordinator = get_task_coordinator()
        session_status = coordinator.get_session_status(session_id)
        if not session_status:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
        success = coordinator.resume_from_chat(session_id, user_confirmation=True)
        if not success:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="恢复任务失败，可能用户未确认继续")
        await broadcast_procedure_event("session_resumed", {"session_id": session_id, "user_id": current_user})
        return ProcResumeSessionResponse(success=True, session_id=session_id, mode="ai_executing", message="任务已恢复，AI将继续执行")
    except HTTPException:
        raise
    except Exception as e:
        diagnostic_except_handler(e, context="[SILENT_FAILURE_BLOCKED] 恢复会话失败", logger_instance=logger)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"恢复会话失败: {str(e)}") from e


@router.get("/procedures/sessions/{session_id}/status", response_model=ProcSessionStatusResponse, responses={404: {"model": ProcStandardErrorResponse, "description": "会话不存在"}, 503: {"model": ProcStandardErrorResponse, "description": "服务不可用"}})
async def get_procedure_session_status(session_id: str, current_user: str = Depends(get_current_user)):
    verify_procedure_learning_available()
    try:
        coordinator = get_task_coordinator()
        session_status = coordinator.get_session_status(session_id)
        if not session_status:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
        return ProcSessionStatusResponse(
            session_id=session_status["session_id"],
            task_id=session_status.get("task_id"),
            intent=session_status.get("intent"),
            mode=session_status.get("mode", "unknown"),
            procedure_id=session_status.get("procedure_id"),
            recording_id=session_status.get("recording_id"),
            created_at=datetime.fromtimestamp(session_status["created_at"]).isoformat() if session_status.get("created_at") else None
        )
    except HTTPException:
        raise
    except Exception as e:
        diagnostic_except_handler(e, context="[SILENT_FAILURE_BLOCKED] 获取会话状态失败", logger_instance=logger)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"获取会话状态失败: {str(e)}") from e


# ═══════════════════════════════════════════════════════════════════
# 路由顺序修复：确保静态路由在动态路径参数路由之前匹配
# 避免 /slots 被匹配为 task_id='slots'、/workflows 被匹配为 task_id='workflows'
# ═══════════════════════════════════════════════════════════════════
def _reorder_task_routes(router):
    """把静态路由排在动态路径参数路由之前"""
    prefix = getattr(router, 'prefix', '')
    static_routes = []
    dynamic_routes = []
    for route in router.routes:
        path = getattr(route, 'path', '')
        # 去掉 router prefix 后再判断是否为动态路由
        relative_path = path[len(prefix):] if prefix and path.startswith(prefix) else path
        parts = relative_path.strip('/').split('/')
        is_dynamic = parts and parts[0].startswith('{')
        if is_dynamic:
            dynamic_routes.append(route)
        else:
            static_routes.append(route)
    router.routes = static_routes + dynamic_routes

_reorder_task_routes(router)
logger.info("[TaskAPI] 路由顺序已修复：静态路由优先于动态路由")
