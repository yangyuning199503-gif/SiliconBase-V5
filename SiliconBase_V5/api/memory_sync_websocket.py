#!/usr/bin/env python3
"""
Memory Sync WebSocket API - 记忆同步WebSocket端点
Phase 4 Week 7 - WebSocket实时推送记忆更新

端点: /ws/memory-sync?session_id={session_id}
功能:
- WebSocket实时推送记忆更新
- 支持心跳检测
- 用户认证验证
- 连接数限制
"""

import json
import logging

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect

# 导入记忆同步管理器
try:
    from core.memory.memory_sync_manager import MemorySyncMessageType, get_memory_sync_manager
    MANAGER_AVAILABLE = True
except ImportError as e:
    MANAGER_AVAILABLE = False
    logging.warning(f"[MemorySyncWebSocket] 记忆同步管理器导入失败: {e}")

# 导入认证依赖 - 使用独立的auth_utils模块避免循环导入
try:
    from api.auth_utils import get_current_user_ws
    AUTH_AVAILABLE = True
except ImportError:
    try:
        from .auth_utils import get_current_user_ws
        AUTH_AVAILABLE = True
    except ImportError as e:
        AUTH_AVAILABLE = False
        logging.warning(f"[MemorySyncWebSocket] 认证模块导入失败: {e}")

logger = logging.getLogger(__name__)

# 创建Router
router = APIRouter(tags=["memory-sync"])


async def get_current_user_optional(websocket: WebSocket) -> str | None:
    """
    可选的用户认证

    从WebSocket连接的token参数中提取用户ID
    """
    # 尝试从query参数获取token
    token = websocket.query_params.get("token")

    if not token:
        # 尝试从headers获取
        auth_header = websocket.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

    if not token:
        return None

    # 验证token - 使用独立的auth_utils模块
    try:
        if AUTH_AVAILABLE:
            # 使用新的独立认证模块
            user_id = await get_current_user_ws(token)
            return user_id
    except Exception as e:
        logger.debug(f"[MemorySyncWebSocket] Token验证失败: {e}")

    return None


@router.websocket("/ws/memory-sync")
async def memory_sync_websocket(
    websocket: WebSocket,
    session_id: str = Query(..., description="会话ID"),
    token: str | None = Query(None, description="认证Token（可选）")
):
    """
    记忆同步WebSocket端点

    ## 连接参数
    - **session_id**: 必需，要同步的会话ID
    - **token**: 可选，认证令牌

    ## 消息格式

    ### 客户端 -> 服务器
    ```json
    {
        "type": "ping",
        "timestamp": "2026-01-15T10:30:00Z"
    }
    ```

    ### 服务器 -> 客户端
    ```json
    {
        "type": "memory_added",
        "timestamp": "2026-01-15T10:30:00Z",
        "data": {
            "memory": {...},
            "session_id": "xxx",
            "user_id": "xxx"
        }
    }
    ```

    ## 消息类型
    - **connection_ack**: 连接确认
    - **memory_added**: 新记忆添加
    - **memory_updated**: 记忆更新
    - **memory_deleted**: 记忆删除
    - **sync_required**: 需要同步
    - **heartbeat_ack**: 心跳响应
    - **error**: 错误消息
    """

    if not MANAGER_AVAILABLE:
        await websocket.close(code=1011, reason="Memory sync service unavailable")
        return

    # 验证session_id
    if not session_id:
        await websocket.close(code=1008, reason="Missing session_id")
        return

    # 获取用户ID（如果有token）
    user_id = None
    if token:
        try:
            user_id = await get_current_user_optional(websocket)
        except Exception as e:
            logger.warning(f"[MemorySyncWebSocket] 认证失败: {e}", exc_info=True)

    # 获取同步管理器
    sync_manager = get_memory_sync_manager()

    # 确保管理器已启动
    if not sync_manager._running:
        await sync_manager.start()

    # 接受连接
    connection_success = await sync_manager.connect(websocket, session_id, user_id)
    if not connection_success:
        # 连接被拒绝（可能是连接数超限）
        return

    # 获取连接ID（通过查找最新添加的连接）
    connection_id = None
    if session_id in sync_manager._connections:
        for conn_id, conn_info in sync_manager._connections[session_id].items():
            if conn_info.websocket == websocket:
                connection_id = conn_id
                break

    if not connection_id:
        logger.error("[MemorySyncWebSocket] 无法获取连接ID")
        await websocket.close(code=1011, reason="Internal error")
        return

    logger.info(f"[MemorySyncWebSocket] 连接建立: {connection_id} for session {session_id}")

    try:
        # 消息接收循环
        while True:
            try:
                # 接收消息
                raw_message = await websocket.receive_text()

                # 解析JSON
                try:
                    message = json.loads(raw_message)
                except json.JSONDecodeError:
                    await websocket.send_json({
                        "type": MemorySyncMessageType.ERROR,
                        "timestamp": sync_manager._get_timestamp(),
                        "data": {"message": "Invalid JSON format"}
                    })
                    continue

                # 处理消息
                await sync_manager.handle_client_message(connection_id, message)

            except WebSocketDisconnect:
                logger.info(f"[MemorySyncWebSocket] 客户端断开: {connection_id}")
                break
            except Exception as e:
                logger.error(f"[MemorySyncWebSocket] 消息处理异常: {e}")
                try:
                    await websocket.send_json({
                        "type": MemorySyncMessageType.ERROR,
                        "timestamp": sync_manager._get_timestamp(),
                        "data": {"message": f"Processing error: {str(e)}"}
                    })
                except Exception as e:
                    logger.warning(f"[MemorySyncWebSocket] 发送错误消息失败，连接可能已断开: {e}", exc_info=True)
                    break

    finally:
        # 清理连接
        await sync_manager.disconnect(connection_id)
        logger.info(f"[MemorySyncWebSocket] 连接清理完成: {connection_id}")


@router.get("/memory-sync/stats")
async def get_memory_sync_stats():
    """
    获取记忆同步服务统计信息

    返回当前WebSocket连接数、session分布等信息
    """
    if not MANAGER_AVAILABLE:
        raise HTTPException(status_code=503, detail="Memory sync service unavailable")

    sync_manager = get_memory_sync_manager()
    stats = sync_manager.get_connection_stats()

    return {
        "success": True,
        "data": stats
    }


# 导出router
__all__ = ['router', 'memory_sync_websocket']
