#!/usr/bin/env python3
"""
MemorySyncManager - WebSocket记忆同步管理器
Phase 4 Week 7 - WebSocket实时推送记忆更新

功能：
- 管理所有WebSocket连接
- 按session_id分组连接
- 提供broadcast方法推送记忆更新
- 支持心跳检测和断线重连
- 连接数限制保护
"""

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.diagnostic import safe_create_task

try:
    from fastapi import WebSocket
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False
    WebSocket = Any

logger = logging.getLogger(__name__)


class MemorySyncMessageType(str, Enum):
    """记忆同步消息类型"""
    MEMORY_ADDED = "memory_added"
    MEMORY_UPDATED = "memory_updated"
    MEMORY_DELETED = "memory_deleted"
    SYNC_REQUIRED = "sync_required"
    HEARTBEAT = "heartbeat"
    HEARTBEAT_ACK = "heartbeat_ack"
    CONNECTION_ACK = "connection_ack"
    ERROR = "error"


@dataclass
class ConnectionInfo:
    """WebSocket连接信息"""
    websocket: WebSocket
    session_id: str
    user_id: str | None = None
    connected_at: float = field(default_factory=time.time)
    last_ping: float = field(default_factory=time.time)
    is_authenticated: bool = False
    connection_id: str = field(default_factory=lambda: f"conn_{int(time.time() * 1000)}")


class MemorySyncManager:
    """
    记忆同步管理器 - 单例模式

    管理所有WebSocket连接，按session_id分组，支持：
    - 连接管理：添加、移除、查询连接
    - 消息广播：按session_id或全局广播
    - 心跳检测：自动检测断开的连接
    - 连接限制：防止连接数过多
    """

    _instance = None
    _lock = asyncio.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # 连接存储: session_id -> {connection_id: ConnectionInfo}
        self._connections: dict[str, dict[str, ConnectionInfo]] = {}

        # 全局连接索引: connection_id -> session_id (用于快速查找)
        self._connection_index: dict[str, str] = {}

        # 配置参数
        self._max_connections_per_session = 10  # 每个session最大连接数
        self._max_total_connections = 1000      # 全局最大连接数
        self._heartbeat_interval = 30           # 心跳检测间隔(秒)
        self._heartbeat_timeout = 60            # 心跳超时时间(秒)

        # 运行状态
        self._running = False
        self._heartbeat_task: asyncio.Task | None = None

        logger.info("[MemorySyncManager] 初始化完成")

    async def start(self):
        """启动心跳检测任务"""
        if self._running:
            return

        self._running = True
        self._heartbeat_task = safe_create_task(self._heartbeat_loop(), name="_heartbeat_loop")
        logger.info("[MemorySyncManager] 心跳检测已启动")

    async def stop(self):
        """停止心跳检测并清理所有连接"""
        self._running = False

        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._heartbeat_task

        # 关闭所有连接
        await self._close_all_connections()
        logger.info("[MemorySyncManager] 已停止")

    async def connect(self, websocket: WebSocket, session_id: str, user_id: str | None = None) -> bool:
        """
        接受新的WebSocket连接

        Args:
            websocket: WebSocket连接对象
            session_id: 会话ID
            user_id: 用户ID（可选）

        Returns:
            bool: 是否成功接受连接
        """
        try:
            # 检查全局连接数限制
            total_connections = len(self._connection_index)
            if total_connections >= self._max_total_connections:
                logger.warning(f"[MemorySyncManager] 连接数超限: {total_connections}/{self._max_total_connections}")
                await websocket.close(code=1008, reason="Server connection limit reached")
                return False

            # 检查session连接数限制
            session_connections = self._connections.get(session_id, {})
            if len(session_connections) >= self._max_connections_per_session:
                logger.warning(f"[MemorySyncManager] Session连接数超限: {session_id} ({len(session_connections)})")
                await websocket.close(code=1008, reason="Session connection limit reached")
                return False

            # 接受WebSocket连接
            await websocket.accept()

            # 创建连接信息
            conn_info = ConnectionInfo(
                websocket=websocket,
                session_id=session_id,
                user_id=user_id,
                connected_at=time.time(),
                last_ping=time.time(),
                is_authenticated=True  # 简化认证，假设已通过API层验证
            )

            # 存储连接
            if session_id not in self._connections:
                self._connections[session_id] = {}
            self._connections[session_id][conn_info.connection_id] = conn_info
            self._connection_index[conn_info.connection_id] = session_id

            # 发送连接确认
            await self._send_message(websocket, {
                "type": MemorySyncMessageType.CONNECTION_ACK,
                "timestamp": self._get_timestamp(),
                "data": {
                    "connection_id": conn_info.connection_id,
                    "session_id": session_id,
                    "message": "Connected to memory sync service"
                }
            })

            logger.info(f"[MemorySyncManager] 新连接: {conn_info.connection_id} for session {session_id}")
            return True

        except Exception as e:
            logger.error(f"[MemorySyncManager] 连接处理失败: {e}")
            return False

    async def disconnect(self, connection_id: str):
        """
        断开指定连接

        Args:
            connection_id: 连接ID
        """
        session_id = self._connection_index.get(connection_id)
        if not session_id:
            return

        session_conns = self._connections.get(session_id, {})
        conn_info = session_conns.get(connection_id)

        if conn_info:
            with contextlib.suppress(Exception):
                await conn_info.websocket.close()

            # 清理连接
            del session_conns[connection_id]
            del self._connection_index[connection_id]

            # 如果session没有连接了，清理session
            if not session_conns:
                del self._connections[session_id]

            logger.info(f"[MemorySyncManager] 连接断开: {connection_id}")

    async def broadcast_to_session(self, session_id: str, message: dict) -> int:
        """
        向指定session的所有连接广播消息

        Args:
            session_id: 会话ID
            message: 要发送的消息字典

        Returns:
            int: 成功发送的连接数
        """
        if session_id not in self._connections:
            return 0

        session_conns = self._connections[session_id].copy()
        if not session_conns:
            return 0

        # 添加时间戳
        message["timestamp"] = message.get("timestamp", self._get_timestamp())

        # 并行发送消息
        tasks = []
        for conn_info in session_conns.values():
            task = self._send_message_safe(conn_info, message)
            tasks.append(task)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 统计成功发送的数量
        success_count = sum(1 for r in results if r is True)

        # 清理失败的连接
        for conn_id, result in zip(session_conns.keys(), results, strict=False):
            if isinstance(result, Exception) or result is False:
                await self.disconnect(conn_id)

        if success_count > 0:
            logger.debug(f"[MemorySyncManager] 广播到session {session_id}: {success_count}/{len(session_conns)} 成功")

        return success_count

    async def broadcast_memory_added(self, session_id: str, memory: dict, user_id: str | None = None):
        """
        广播新记忆添加事件

        Args:
            session_id: 会话ID
            memory: 记忆数据
            user_id: 用户ID（可选）
        """
        message = {
            "type": MemorySyncMessageType.MEMORY_ADDED,
            "data": {
                "memory": memory,
                "user_id": user_id,
                "session_id": session_id
            }
        }
        await self.broadcast_to_session(session_id, message)

    async def broadcast_memory_updated(self, session_id: str, memory_id: str, updates: dict, user_id: str | None = None):
        """
        广播记忆更新事件

        Args:
            session_id: 会话ID
            memory_id: 记忆ID
            updates: 更新的字段
            user_id: 用户ID（可选）
        """
        message = {
            "type": MemorySyncMessageType.MEMORY_UPDATED,
            "data": {
                "memory_id": memory_id,
                "updates": updates,
                "user_id": user_id,
                "session_id": session_id
            }
        }
        await self.broadcast_to_session(session_id, message)

    async def broadcast_memory_deleted(self, session_id: str, memory_id: str, user_id: str | None = None):
        """
        广播记忆删除事件

        Args:
            session_id: 会话ID
            memory_id: 记忆ID
            user_id: 用户ID（可选）
        """
        message = {
            "type": MemorySyncMessageType.MEMORY_DELETED,
            "data": {
                "memory_id": memory_id,
                "user_id": user_id,
                "session_id": session_id
            }
        }
        await self.broadcast_to_session(session_id, message)

    async def broadcast_sync_required(self, session_id: str, reason: str = "memory_changed", user_id: str | None = None):
        """
        广播同步请求事件（用于增量同步）

        Args:
            session_id: 会话ID
            reason: 同步原因
            user_id: 用户ID（可选）
        """
        message = {
            "type": MemorySyncMessageType.SYNC_REQUIRED,
            "data": {
                "reason": reason,
                "user_id": user_id,
                "session_id": session_id,
                "sync_timestamp": self._get_timestamp()
            }
        }
        await self.broadcast_to_session(session_id, message)

    async def handle_client_message(self, connection_id: str, message: dict):
        """
        处理客户端发送的消息

        Args:
            connection_id: 连接ID
            message: 客户端消息
        """
        msg_type = message.get("type", "unknown")

        if msg_type == "ping":
            # 更新最后ping时间
            session_id = self._connection_index.get(connection_id)
            if session_id:
                conn_info = self._connections.get(session_id, {}).get(connection_id)
                if conn_info:
                    conn_info.last_ping = time.time()

                    # 发送pong响应
                    await self._send_message(conn_info.websocket, {
                        "type": MemorySyncMessageType.HEARTBEAT_ACK,
                        "timestamp": self._get_timestamp(),
                        "data": {"connection_id": connection_id}
                    })

        elif msg_type == "subscribe":
            # 处理订阅请求（可用于扩展）
            pass

        elif msg_type == "unsubscribe":
            # 处理取消订阅请求
            pass

    def get_connection_stats(self) -> dict:
        """获取连接统计信息"""
        return {
            "total_connections": len(self._connection_index),
            "total_sessions": len(self._connections),
            "max_connections_per_session": self._max_connections_per_session,
            "max_total_connections": self._max_total_connections,
            "sessions": {
                session_id: len(conns)
                for session_id, conns in self._connections.items()
            }
        }

    # ========================================================================
    # 内部方法
    # ========================================================================

    async def _send_message(self, websocket: WebSocket, message: dict):
        """发送消息到WebSocket"""
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.debug(f"[MemorySyncManager] 发送消息失败: {e}")
            raise

    async def _send_message_safe(self, conn_info: ConnectionInfo, message: dict) -> bool:
        """安全地发送消息（不抛出异常）"""
        try:
            await conn_info.websocket.send_json(message)
            return True
        except Exception:
            return False

    async def _heartbeat_loop(self):
        """心跳检测循环"""
        while self._running:
            try:
                await asyncio.sleep(self._heartbeat_interval)
                await self._check_connections()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[MemorySyncManager] 心跳检测异常: {e}")

    async def _check_connections(self):
        """检查并清理超时连接"""
        now = time.time()
        connections_to_remove = []

        for session_id, session_conns in self._connections.items():
            for conn_id, conn_info in session_conns.items():
                # 检查心跳超时
                if now - conn_info.last_ping > self._heartbeat_timeout:
                    connections_to_remove.append((session_id, conn_id))

        # 断开超时连接
        for _session_id, conn_id in connections_to_remove:
            logger.info(f"[MemorySyncManager] 心跳超时，断开连接: {conn_id}")
            await self.disconnect(conn_id)

    async def _close_all_connections(self):
        """关闭所有连接"""
        all_connections = list(self._connection_index.keys())
        for conn_id in all_connections:
            await self.disconnect(conn_id)

    def _get_timestamp(self) -> str:
        """获取ISO格式时间戳"""
        from datetime import datetime
        return datetime.utcnow().isoformat() + "Z"


# 便捷函数：获取单例实例
_sync_manager = None

def get_memory_sync_manager() -> MemorySyncManager:
    """获取MemorySyncManager单例"""
    global _sync_manager
    if _sync_manager is None:
        _sync_manager = MemorySyncManager()
    return _sync_manager


# 便捷函数：同步接口（供非异步代码调用）
def broadcast_memory_added_sync(session_id: str, memory: dict, user_id: str | None = None):
    """
    同步接口：广播新记忆添加事件

    供非异步代码（如MemoryAutoTrigger）调用
    """
    try:
        manager = get_memory_sync_manager()
        # 使用 asyncio.run_coroutine_threadsafe 在事件循环中执行
        try:
            loop = asyncio.get_running_loop()
            asyncio.run_coroutine_threadsafe(
                manager.broadcast_memory_added(session_id, memory, user_id),
                loop
            )
        except RuntimeError:
            # 没有正在运行的事件循环
            pass
    except Exception as e:
        logger.debug(f"[MemorySyncManager] 同步广播失败: {e}")


def broadcast_memory_updated_sync(session_id: str, memory_id: str, updates: dict, user_id: str | None = None):
    """同步接口：广播记忆更新事件"""
    try:
        manager = get_memory_sync_manager()
        try:
            loop = asyncio.get_running_loop()
            asyncio.run_coroutine_threadsafe(
                manager.broadcast_memory_updated(session_id, memory_id, updates, user_id),
                loop
            )
        except RuntimeError:
            pass
    except Exception as e:
        logger.debug(f"[MemorySyncManager] 同步广播失败: {e}")


def broadcast_sync_required_sync(session_id: str, reason: str = "memory_changed", user_id: str | None = None):
    """同步接口：广播同步请求事件"""
    try:
        manager = get_memory_sync_manager()
        try:
            loop = asyncio.get_running_loop()
            asyncio.run_coroutine_threadsafe(
                manager.broadcast_sync_required(session_id, reason, user_id),
                loop
            )
        except RuntimeError:
            pass
    except Exception as e:
        logger.debug(f"[MemorySyncManager] 同步广播失败: {e}")


__all__ = [
    'MemorySyncManager',
    'MemorySyncMessageType',
    'get_memory_sync_manager',
    'broadcast_memory_added_sync',
    'broadcast_memory_updated_sync',
    'broadcast_sync_required_sync',
]
