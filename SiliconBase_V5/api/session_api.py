#!/usr/bin/env python3
"""
Session API 模块
Phase 1 Week 1 - 任务4

提供 Session 相关的 REST API 端点，包括：
- 会话的 CRUD 操作
- 会话消息管理
- 权限验证

认证：
  - 通过依赖注入获取 user_id
  - 所有操作都是用户隔离的
  - 严格的会话所有权验证
"""

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi import Path as FastApiPath
from pydantic import BaseModel, Field

# 导入认证相关组件
try:
    from api.cloud_api import get_current_user, user_auth_store
    AUTH_AVAILABLE = True
except ImportError:
    try:
        from .cloud_api import get_current_user, user_auth_store
        AUTH_AVAILABLE = True
    except ImportError:
        AUTH_AVAILABLE = False
        user_auth_store = None
        get_current_user = None

# 导入 SessionManager
try:
    from core.session.session_manager import (
        MessageAddError,
        Session,
        SessionCreateError,
        SessionDeleteError,
        SessionManager,
        SessionManagerError,
        SessionMessage,
        SessionMode,
        SessionNotFoundError,
        SessionStatus,
        SessionUpdateError,
        get_session_manager,
    )
    SESSION_MANAGER_AVAILABLE = True
except ImportError as e:
    SESSION_MANAGER_AVAILABLE = False
    logging.warning(f"[SessionAPI] SessionManager 导入失败: {e}")
    # 定义占位符类，避免类型注解错误
    SessionManager = object
    Session = object
    SessionMessage = object
    SessionMode = object
    SessionStatus = object
    SessionNotFoundError = Exception
    SessionCreateError = Exception
    SessionUpdateError = Exception
    SessionDeleteError = Exception
    MessageAddError = Exception
    SessionManagerError = Exception

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# Pydantic 模型定义
# ═══════════════════════════════════════════════════════════

class CreateSessionRequest(BaseModel):
    """创建会话请求"""
    title: str | None = Field(default=None, max_length=200, description="会话标题")
    mode: str = Field(default="daily", description="会话模式: daily/focus/analysis/debug")
    initial_context: dict[str, Any] | None = Field(default=None, description="初始上下文配置")

    class Config:
        json_schema_extra = {
            "example": {
                "title": "新会话",
                "mode": "daily",
                "initial_context": {"source": "web", "tags": []}
            }
        }


class UpdateSessionRequest(BaseModel):
    """更新会话请求"""
    title: str | None = Field(default=None, max_length=200, description="会话标题")
    status: str | None = Field(default=None, description="状态: active/archived/deleted")
    metadata: dict[str, Any] | None = Field(default=None, description="会话元数据")

    class Config:
        json_schema_extra = {
            "example": {
                "title": "更新后的标题",
                "status": "archived",
                "metadata": {"tags": ["important"]}
            }
        }


class AddMessageRequest(BaseModel):
    """添加消息请求"""
    role: str = Field(..., description="消息角色: user/assistant/system/tool")
    content: str = Field(..., min_length=1, max_length=50000, description="消息内容")
    content_type: str = Field(default="text", description="内容类型: text/image/audio/file/mixed")
    thinking: str | None = Field(default=None, description="AI思考过程")
    tool_calls: dict[str, Any] | None = Field(default=None, description="工具调用信息")
    memory_id: str | None = Field(default=None, description="关联的L2记忆ID")
    metadata: dict[str, Any] | None = Field(default=None, description="消息元数据")

    class Config:
        json_schema_extra = {
            "example": {
                "role": "user",
                "content": "你好，请帮我分析这个数据",
                "content_type": "text",
                "metadata": {"source": "web"}
            }
        }


class SessionResponse(BaseModel):
    """会话响应"""
    id: str
    user_id: str
    title: str | None
    mode: str
    status: str
    metadata: dict[str, Any]
    message_count: int
    last_message_at: str | None
    created_at: str | None
    updated_at: str | None
    last_message_preview: str | None = None

    class Config:
        json_schema_extra = {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "user_id": "user_abc123",
                "title": "测试会话",
                "mode": "daily",
                "status": "active",
                "metadata": {},
                "message_count": 10,
                "last_message_at": "2026-03-12T12:00:00",
                "created_at": "2026-03-12T10:00:00",
                "updated_at": "2026-03-12T12:00:00"
            }
        }


class SessionDetailResponse(SessionResponse):
    """会话详情响应（包含最近消息）"""
    recent_messages: list[dict[str, Any]] = Field(default_factory=list, description="最近10条消息")


class SessionListResponse(BaseModel):
    """会话列表响应"""
    items: list[SessionResponse]
    total: int
    limit: int
    offset: int

    class Config:
        json_schema_extra = {
            "example": {
                "items": [],
                "total": 0,
                "limit": 20,
                "offset": 0
            }
        }


class MessageResponse(BaseModel):
    """消息响应"""
    id: str
    session_id: str
    role: str
    content: str
    content_type: str
    metadata: dict[str, Any]
    tool_calls: dict[str, Any] | None
    thinking: str | None
    memory_id: str | None
    created_at: str | None

    class Config:
        json_schema_extra = {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440001",
                "session_id": "550e8400-e29b-41d4-a716-446655440000",
                "role": "user",
                "content": "你好",
                "content_type": "text",
                "metadata": {},
                "created_at": "2026-03-12T12:00:00"
            }
        }


class MessageListResponse(BaseModel):
    """消息列表响应"""
    items: list[MessageResponse]
    has_more: bool
    next_cursor: str | None

    class Config:
        json_schema_extra = {
            "example": {
                "items": [],
                "has_more": False,
                "next_cursor": None
            }
        }


class AddMessageResponse(BaseModel):
    """添加消息响应"""
    message_id: str  # 改名为message_id以匹配前端期望
    session_id: str  # 添加session_id字段
    created_at: str

    class Config:
        json_schema_extra = {
            "example": {
                "message_id": "550e8400-e29b-41d4-a716-446655440001",
                "session_id": "550e8400-e29b-41d4-a716-446655440000",
                "created_at": "2026-03-12T12:00:00"
            }
        }


class DeleteSessionResponse(BaseModel):
    """删除会话响应"""
    success: bool
    id: str              # 添加此字段以匹配前端期望
    deleted_messages: int  # 保留原有字段保持兼容性
    cleanup_warnings: list[str] | None = None  # 资源清理警告信息

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "deleted_messages": 10
            }
        }


class BatchDeleteRequest(BaseModel):
    """批量删除会话请求"""
    ids: list[str] = Field(..., min_length=1, description="要删除的会话ID列表")


class BatchDeleteResponse(BaseModel):
    """批量删除会话响应"""
    success: bool
    deleted: int
    errors: list[str] | None = None


class ErrorResponse(BaseModel):
    """错误响应"""
    error: str
    message: str
    code: int
    timestamp: float


# ═══════════════════════════════════════════════════════════
# 错误处理辅助函数
# ═══════════════════════════════════════════════════════════

def handle_session_exception(e: Exception, operation: str) -> HTTPException:
    """
    统一处理 SessionManager 异常

    Args:
        e: 捕获的异常
        operation: 操作名称（用于日志）

    Returns:
        HTTPException: 标准化的 HTTP 异常
    """
    if isinstance(e, SessionNotFoundError):
        logger.warning(f"[SessionAPI] {operation} 失败: 会话不存在 - {e}")
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )
    elif isinstance(e, (SessionCreateError, SessionUpdateError, SessionDeleteError, MessageAddError)):
        logger.error(f"[SessionAPI] {operation} 失败: {e}", exc_info=True)
        return HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database operation failed"
        )
    elif isinstance(e, ValueError):
        logger.warning(f"[SessionAPI] {operation} 失败: 参数错误 - {e}")
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    else:
        logger.error(f"[SessionAPI] {operation} 未预期异常: {e}", exc_info=True)
        return HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


# ═══════════════════════════════════════════════════════════
# 权限验证辅助函数
# ═══════════════════════════════════════════════════════════

async def verify_session_ownership(
    session_id: str,
    user_id: str,
    session_manager: "SessionManager"
) -> "Session":
    """
    验证会话所有权

    Args:
        session_id: 会话ID
        user_id: 当前用户ID
        session_manager: 会话管理器实例

    Returns:
        Session: 会话对象

    Raises:
        HTTPException: 404 - 会话不存在
        HTTPException: 403 - 无权限访问
    """
    try:
        session = await session_manager.get_session(session_id)

        if session is None:
            logger.warning(
                f"[SessionAPI] 访问不存在的会话: session_id={session_id}, user_id={user_id}"
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )

        # 验证所有权
        if session.user_id != user_id:
            logger.warning(
                f"[SessionAPI] 权限拒绝: 用户 {user_id} 尝试访问用户 {session.user_id} 的会话 {session_id}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: you can only access your own sessions"
            )

        return session

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f'[SILENT_FAILURE_BLOCKED] 验证会话所有权失败: {e}', exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify session ownership"
        ) from e


# ═══════════════════════════════════════════════════════════
# 路由定义
# ═══════════════════════════════════════════════════════════

router = APIRouter(prefix="/sessions", tags=["sessions"])


def get_session_manager_instance() -> "SessionManager":
    """获取 SessionManager 实例"""
    if not SESSION_MANAGER_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Session management module is not available"
        )
    return get_session_manager()


# ───────────────────────────────────────────────────────────
# 会话 CRUD
# ───────────────────────────────────────────────────────────

@router.post(
    "",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建会话",
    description="创建一个新的会话，返回会话对象"
)
async def create_session(
    request: CreateSessionRequest,
    user_id: str = Depends(get_current_user)
):
    """
    创建新会话

    - **title**: 会话标题（可选）
    - **mode**: 会话模式，可选值为 daily/focus/analysis/debug（默认 daily）
    - **initial_context**: 初始上下文配置（可选）

    需要用户认证
    """
    try:
        manager = get_session_manager_instance()

        session = await manager.create_session(
            user_id=user_id,
            title=request.title,
            mode=request.mode,
            initial_context=request.initial_context
        )

        logger.info(f"[SessionAPI] 会话创建成功: {session.id}, user_id={user_id}")
        return SessionResponse(**session.to_dict())

    except Exception as e:
        http_exc = handle_session_exception(e, "创建会话")
        raise http_exc from e


@router.get(
    "",
    response_model=SessionListResponse,
    summary="获取会话列表",
    description="获取当前用户的会话列表，支持分页和状态过滤"
)
async def list_sessions(
    limit: int = Query(default=20, ge=1, le=100, description="每页数量"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
    status: str | None = Query(default=None, description="状态过滤: active/archived/deleted"),
    user_id: str = Depends(get_current_user)
):
    """
    获取会话列表

    - **limit**: 每页数量（默认20，最大100）
    - **offset**: 偏移量（默认0）
    - **status**: 状态过滤（可选）

    需要用户认证
    """
    try:
        manager = get_session_manager_instance()

        total, sessions = await manager.list_sessions(
            user_id=user_id,
            limit=limit,
            offset=offset,
            status=status
        )

        items = [SessionResponse(**session.to_dict()) for session in sessions]

        logger.debug(
            f"[SessionAPI] 获取会话列表: user_id={user_id}, total={total}, limit={limit}, offset={offset}"
        )

        return SessionListResponse(
            items=items,
            total=total,
            limit=limit,
            offset=offset
        )

    except Exception as e:
        http_exc = handle_session_exception(e, "获取会话列表")
        raise http_exc from e


@router.get(
    "/{session_id}",
    response_model=SessionDetailResponse,
    summary="获取会话详情",
    description="获取指定会话的详细信息，包含最近10条消息"
)
async def get_session(
    session_id: str = FastApiPath(..., description="会话ID"),
    user_id: str = Depends(get_current_user)
):
    """
    获取会话详情

    - **session_id**: 会话ID（路径参数）

    需要用户认证 + 会话权限检查
    """
    try:
        manager = get_session_manager_instance()

        # 验证所有权
        session = await verify_session_ownership(session_id, user_id, manager)

        # 获取最近10条消息
        try:
            has_more, next_cursor, messages = await manager.get_messages(
                session_id=session_id,
                limit=10
            )
            recent_messages = [
                {
                    "id": msg.id,
                    "role": msg.role,
                    "content": msg.content[:200] + "..." if len(msg.content) > 200 else msg.content,
                    "content_type": msg.content_type,
                    "created_at": msg.created_at.isoformat() if msg.created_at else None
                }
                for msg in messages[:10]
            ]
        except Exception as msg_e:
            logger.error(f'[SILENT_FAILURE_BLOCKED] 获取会话消息失败: {msg_e}')
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve session messages"
            ) from msg_e

        session_dict = session.to_dict()
        session_dict["recent_messages"] = recent_messages

        logger.debug(f"[SessionAPI] 获取会话详情: session_id={session_id}")

        return SessionDetailResponse(**session_dict)

    except HTTPException:
        raise
    except Exception as e:
        http_exc = handle_session_exception(e, "获取会话详情")
        raise http_exc from e


@router.put(
    "/{session_id}",
    response_model=SessionResponse,
    summary="更新会话",
    description="更新指定会话的信息"
)
async def update_session(
    session_id: str = FastApiPath(..., description="会话ID"),
    request: UpdateSessionRequest = ...,
    user_id: str = Depends(get_current_user)
):
    """
    更新会话

    - **session_id**: 会话ID（路径参数）
    - **title**: 新的会话标题（可选）
    - **status**: 新的状态（可选，值为 active/archived/deleted）
    - **metadata**: 新的元数据（可选）

    需要用户认证 + 会话权限检查
    """
    try:
        manager = get_session_manager_instance()

        # 验证所有权
        await verify_session_ownership(session_id, user_id, manager)

        # 构建更新字段
        updates = {}
        if request.title is not None:
            updates["title"] = request.title
        if request.status is not None:
            updates["status"] = request.status
        if request.metadata is not None:
            updates["metadata"] = request.metadata

        if not updates:
            # 没有更新字段，直接返回当前会话
            session = await manager.get_session(session_id)
            return SessionResponse(**session.to_dict())

        session = await manager.update_session(session_id, updates)

        logger.info(f"[SessionAPI] 会话更新成功: session_id={session_id}, updates={list(updates.keys())}")

        return SessionResponse(**session.to_dict())

    except HTTPException:
        raise
    except Exception as e:
        http_exc = handle_session_exception(e, "更新会话")
        raise http_exc from e


@router.delete(
    "/{session_id}",
    response_model=DeleteSessionResponse,
    summary="删除会话",
    description="删除指定会话及其所有消息"
)
async def delete_session(
    session_id: str = FastApiPath(..., description="会话ID"),
    user_id: str = Depends(get_current_user)
):
    """
    删除会话

    - **session_id**: 会话ID（路径参数）

    会级联删除该会话的所有消息。
    需要用户认证 + 会话权限检查
    """
    try:
        manager = get_session_manager_instance()

        # 验证所有权
        await verify_session_ownership(session_id, user_id, manager)

        # 【新增】清理会话关联的资源
        cleanup_errors = []

        # 1. 清理关联的任务
        try:
            from core.task.user_task_manager import get_task_manager
            task_manager = get_task_manager(user_id)
            # 获取会话关联的所有任务
            session_tasks = task_manager.list_tasks(session_id=session_id)
            for task in session_tasks:
                if task.get("status") in ["running", "pending"]:
                    # 取消正在运行的任务
                    try:
                        task_manager.cancel_task(task["task_id"])
                        logger.info(f"[SessionAPI] 取消会话关联任务: session_id={session_id}, task_id={task['task_id']}")
                    except Exception as e:
                        cleanup_errors.append(f"取消任务失败: {task['task_id']}: {e}")
                        logger.error(f"[SessionAPI] 取消任务失败: session_id={session_id}, task_id={task['task_id']}, error={e}")
        except Exception as e:
            cleanup_errors.append(f"清理任务失败: {e}")
            logger.error(f"[SessionAPI] 清理任务失败: session_id={session_id}, error={e}")

        # 2. 清理长任务槽位
        try:
            from core.task.long_task_slots import get_long_task_slots
            slots_manager = get_long_task_slots()
            for slot_id in range(1, 4):  # 3个槽位
                slot_task = slots_manager.get_slot_task(slot_id)
                if slot_task and slot_task.metadata.get("session_id") == session_id:
                    try:
                        slots_manager.stop_task(slot_id)
                        logger.info(f"[SessionAPI] 停止槽位任务: session_id={session_id}, slot_id={slot_id}")
                    except Exception as e:
                        cleanup_errors.append(f"停止槽位任务失败: slot_id={slot_id}: {e}")
                        logger.error(f"[SessionAPI] 停止槽位任务失败: session_id={session_id}, slot_id={slot_id}, error={e}")
        except Exception as e:
            cleanup_errors.append(f"清理槽位失败: {e}")
            logger.error(f"[SessionAPI] 清理槽位失败: session_id={session_id}, error={e}")

        # 3. 清理中断状态
        try:
            from core.agent.interrupt_handler import interrupt_handler

            # 获取当前任务
            from core.task.task_queue import task_queue
            current_task = task_queue.current_task()
            if current_task and current_task.session_id == session_id:
                interrupt_handler.interrupt(current_task.id, "会话已删除")
                logger.info(f"[SessionAPI] 中断会话任务: session_id={session_id}, task_id={current_task.id}")
        except Exception as e:
            cleanup_errors.append(f"清理中断状态失败: {e}")
            logger.error(f"[SessionAPI] 清理中断状态失败: session_id={session_id}, error={e}")

        # 4. 清理WebSocket连接
        try:
            from api.cloud_api import connection_manager
            # 断开该会话的所有WebSocket连接
            if hasattr(connection_manager, 'disconnect_session'):
                connection_manager.disconnect_session(session_id)
                logger.info(f"[SessionAPI] 断开WebSocket连接: session_id={session_id}")
        except Exception as e:
            cleanup_errors.append(f"断开WebSocket失败: {e}")
            logger.error(f"[SessionAPI] 断开WebSocket失败: session_id={session_id}, error={e}")

        # 记录清理结果
        if cleanup_errors:
            logger.warning(f"[SessionAPI] 会话资源清理部分失败: session_id={session_id}, errors={cleanup_errors}")

        deleted_count = await manager.delete_session(session_id)

        logger.info(f"[SessionAPI] 会话删除成功: session_id={session_id}, deleted_messages={deleted_count}")

        return DeleteSessionResponse(
            success=True,
            id=session_id,           # 添加id字段
            deleted_messages=deleted_count,
            cleanup_warnings=cleanup_errors if cleanup_errors else None  # 添加清理警告
        )

    except HTTPException:
        raise
    except Exception as e:
        http_exc = handle_session_exception(e, "删除会话")
        raise http_exc from e


@router.delete(
    "/batch",
    response_model=BatchDeleteResponse,
    summary="批量删除会话",
    description="批量删除指定会话及其消息"
)
async def delete_sessions_batch(
    request: BatchDeleteRequest,
    user_id: str = Depends(get_current_user)
):
    """
    批量删除会话

    - **ids**: 会话ID列表

    会级联删除这些会话的所有消息。
    """
    manager = get_session_manager_instance()
    deleted = 0
    errors = []
    for session_id in request.ids:
        try:
            await verify_session_ownership(session_id, user_id, manager)
            await manager.delete_session(session_id)
            deleted += 1
        except Exception as e:
            errors.append(f"{session_id}: {e}")
            logger.warning(f"[SessionAPI] 批量删除会话失败: {session_id}, error={e}")
    return BatchDeleteResponse(success=True, deleted=deleted, errors=errors or None)


# ───────────────────────────────────────────────────────────
# 消息管理
# ───────────────────────────────────────────────────────────

@router.get(
    "/{session_id}/messages",
    response_model=MessageListResponse,
    summary="获取会话消息",
    description="分页获取指定会话的消息列表"
)
async def get_messages(
    session_id: str = FastApiPath(..., description="会话ID"),
    limit: int = Query(default=50, ge=1, le=100, description="每页数量"),
    before_id: str | None = Query(default=None, description="游标（上一页最后一条消息的ID）"),
    user_id: str = Depends(get_current_user)
):
    """
    获取会话消息

    - **session_id**: 会话ID（路径参数）
    - **limit**: 每页数量（默认50，最大100）
    - **before_id**: 游标，用于分页（可选）

    需要用户认证 + 会话权限检查
    """
    try:
        manager = get_session_manager_instance()

        # 验证所有权
        await verify_session_ownership(session_id, user_id, manager)

        has_more, next_cursor, messages = await manager.get_messages(
            session_id=session_id,
            limit=limit,
            before_id=before_id
        )

        items = [MessageResponse(**msg.to_dict()) for msg in messages]

        logger.debug(
            f"[SessionAPI] 获取消息列表: session_id={session_id}, count={len(items)}, has_more={has_more}"
        )

        return MessageListResponse(
            items=items,
            has_more=has_more,
            next_cursor=next_cursor
        )

    except HTTPException:
        raise
    except Exception as e:
        http_exc = handle_session_exception(e, "获取消息列表")
        raise http_exc from e


@router.post(
    "/{session_id}/messages",
    response_model=AddMessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="添加消息",
    description="向指定会话添加一条消息（内部API）"
)
async def add_message(
    session_id: str = FastApiPath(..., description="会话ID"),
    request: AddMessageRequest = ...,
    user_id: str = Depends(get_current_user)
):
    """
    添加消息（内部API）

    - **session_id**: 会话ID（路径参数）
    - **role**: 消息角色（必需，值为 user/assistant/system/tool）
    - **content**: 消息内容（必需）
    - **content_type**: 内容类型（默认 text）
    - **thinking**: AI思考过程（可选）
    - **tool_calls**: 工具调用信息（可选）
    - **memory_id**: 关联的L2记忆ID（可选）
    - **metadata**: 消息元数据（可选）

    需要用户认证 + 会话权限检查
    """
    try:
        manager = get_session_manager_instance()

        # 验证所有权
        await verify_session_ownership(session_id, user_id, manager)

        # 构建 kwargs
        kwargs = {
            "content_type": request.content_type,
            "metadata": request.metadata or {}
        }
        if request.thinking is not None:
            kwargs["thinking"] = request.thinking
        if request.tool_calls is not None:
            kwargs["tool_calls"] = request.tool_calls
        if request.memory_id is not None:
            kwargs["memory_id"] = request.memory_id

        message_id = await manager.add_message(
            session_id=session_id,
            role=request.role,
            content=request.content,
            **kwargs
        )

        now = datetime.now().isoformat()

        logger.debug(
            f"[SessionAPI] 消息添加成功: message_id={message_id}, session_id={session_id}, role={request.role}"
        )

        return AddMessageResponse(
            message_id=message_id,
            session_id=session_id,  # 从参数获取
            created_at=now
        )

    except HTTPException:
        raise
    except Exception as e:
        http_exc = handle_session_exception(e, "添加消息")
        raise http_exc from e


# ═══════════════════════════════════════════════════════════
# 标题生成
# ═══════════════════════════════════════════════════════════

class GenerateTitleRequest(BaseModel):
    """生成标题请求"""
    session_id: str = Field(..., description="会话ID")
    messages: list[dict[str, Any]] | None = Field(default=None, description="消息列表（可选，不传则从session读取）")


class GenerateTitleResponse(BaseModel):
    """生成标题响应"""
    title: str
    success: bool
    message: str | None = None


def _generate_title_from_messages(messages: list[dict[str, Any]]) -> str:
    """基于消息内容生成会话标题"""
    if not messages:
        return "新会话"

    # 提取最近用户消息
    user_contents = [m.get("content", "") for m in messages if m.get("role") == "user"]
    if not user_contents:
        user_contents = [m.get("content", "") for m in messages if m.get("content")]

    if not user_contents:
        return "新会话"

    latest = str(user_contents[-1]).strip()
    # 取前30个字符作为标题
    title = latest[:30]
    if len(latest) > 30:
        title += "..."
    return title


@router.post(
    "/generate-title",
    response_model=GenerateTitleResponse,
    summary="生成会话标题",
    description="根据会话最近消息自动生成标题"
)
async def generate_session_title(
    request: GenerateTitleRequest,
    user_id: str = Depends(get_current_user)
):
    """
    自动生成会话标题

    - **session_id**: 会话ID
    - **messages**: 消息列表（可选，不传则从session读取最近5条）
    """
    try:
        manager = get_session_manager_instance()

        # 验证所有权
        await verify_session_ownership(request.session_id, user_id, manager)

        # 获取消息
        messages = request.messages
        if not messages:
            has_more, next_cursor, msgs = await manager.get_messages(
                session_id=request.session_id, limit=5
            )
            messages = [{"role": msg.role, "content": msg.content} for msg in msgs]

        # 生成标题
        title = _generate_title_from_messages(messages)

        logger.info(f"[SessionAPI] 生成标题: session_id={request.session_id}, title={title}")
        return GenerateTitleResponse(title=title, success=True)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[SessionAPI] 生成标题失败: {e}")
        return GenerateTitleResponse(title="新会话", success=False, message=str(e))


# ═══════════════════════════════════════════════════════════
# 模块导出
# ═══════════════════════════════════════════════════════════

__all__ = [
    "router",
    "SESSION_MANAGER_AVAILABLE",
    # 请求模型
    "CreateSessionRequest",
    "UpdateSessionRequest",
    "AddMessageRequest",
    # 响应模型
    "SessionResponse",
    "SessionDetailResponse",
    "SessionListResponse",
    "MessageResponse",
    "MessageListResponse",
    "AddMessageResponse",
    "DeleteSessionResponse",
]


# ═══════════════════════════════════════════════════════════
# 循环中断端点（原 interrupt_api.py 合并至此）
# ═══════════════════════════════════════════════════════════

from core.agent.interrupt_handler import interrupt_handler
from core.diagnostic import diagnostic_except_handler
from core.dialog.dialogue_manager import dialogue_manager


class InterruptRequest(BaseModel):
    reason: str = "用户请求中断"
    graceful: bool = True


class InterruptResponse(BaseModel):
    success: bool
    message: str
    session_id: str
    action_taken: str


@router.post("/{session_id}/interrupt")
async def interrupt_session_loop(session_id: str, request: InterruptRequest) -> InterruptResponse:
    """
    中断指定会话的AgentLoop循环
    """
    try:
        logger.info(f"[InterruptAPI] 收到中断请求: session={session_id}, graceful={request.graceful}")
        user_id = None
        try:
            if hasattr(dialogue_manager, '_sessions'):
                for uid, session in dialogue_manager._sessions.items():
                    if hasattr(session, 'session_id') and session.session_id == session_id:
                        user_id = uid
                        break
            if not user_id:
                user_id = session_id
        except Exception as e:
            logger.warning(f"[InterruptAPI] 查找 user_id 失败: {e}")
            user_id = session_id

        from core.task.task_queue import task_queue
        current_task = task_queue.current_task()
        action_taken = []

        try:
            stopped = dialogue_manager.stop_user_loop(user_id)
            if stopped:
                logger.info(f"[InterruptAPI] 已通过 DialogueManager 终止用户 {user_id} 的循环")
                action_taken.append("stop_user_loop")
        except Exception as e:
            logger.warning(f"[InterruptAPI] stop_user_loop 失败: {e}")

        try:
            interrupt_handler.set_global_interrupt(True)
            logger.info("[InterruptAPI] 已设置全局中断标志")
            action_taken.append("global_interrupt")
        except Exception as e:
            logger.warning(f"[InterruptAPI] 设置全局中断标志失败: {e}")

        if current_task:
            task_session_match = True
            if hasattr(current_task, 'session_id') and current_task.session_id != session_id:
                task_session_match = False
                logger.warning(f"[InterruptAPI] 当前任务属于其他会话: task_session={current_task.session_id}, target_session={session_id}")
            if task_session_match:
                if not interrupt_handler.get_status(current_task.id):
                    interrupt_handler.register_task(current_task.id)
                if request.graceful:
                    interrupt_handler.interrupt(current_task.id, reason=request.reason)
                    action_taken.append("graceful_interrupt")
                    logger.info(f"[InterruptAPI] 已标记优雅退出: task={current_task.id}")
                else:
                    interrupt_handler.interrupt(current_task.id, reason=request.reason)
                    await interrupt_handler.cancel_all_futures(current_task.id)
                    action_taken.append("force_interrupt")
                    logger.warning(f"[InterruptAPI] 强制中断: task={current_task.id}")

        # 【诊断断言】确保 on_work_end 方法存在且可调用
        assert hasattr(dialogue_manager, 'on_work_end'), "[DIAGNOSTIC] DialogueManager 缺少 on_work_end 方法"
        try:
            dialogue_manager.on_work_end(user_id)
            action_taken.append("on_work_end")
        except Exception as e:
            diagnostic_except_handler(e, context="[InterruptAPI] on_work_end 失败", logger_instance=logger)

        try:
            if hasattr(dialogue_manager, '_pause_requests') and user_id in dialogue_manager._pause_requests:
                dialogue_manager._pause_requests.pop(user_id, None)
                logger.info(f"[InterruptAPI] 已清理用户 {user_id} 的暂停请求标记")
        except Exception as e:
            logger.warning(f"[InterruptAPI] 清理暂停请求失败: {e}")

        action_str = ",".join(action_taken) if action_taken else "none"
        if not action_taken:
            return InterruptResponse(success=True, message="当前没有运行中的循环", session_id=session_id, action_taken="none")
        return InterruptResponse(
            success=True,
            message="已请求中断循环，当前操作完成后将停止" if request.graceful else "已强制中断当前循环",
            session_id=session_id,
            action_taken=action_str
        )
    except Exception as e:
        logger.error(f"[InterruptAPI] 中断请求失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"中断失败: {str(e)}") from e


@router.get("/{session_id}/status")
async def get_interrupt_session_status(session_id: str):
    """获取会话状态：是否正在运行AgentLoop"""
    from core.task.task_queue import task_queue
    current_task = task_queue.current_task()
    is_running = current_task is not None
    return {
        "session_id": session_id,
        "is_running": is_running,
        "task_id": current_task.id if current_task else None,
        "can_interrupt": is_running
    }
