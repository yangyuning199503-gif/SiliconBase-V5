"""
WebSocket Redis Pub/Sub 补丁 - 用于多实例部署

使用方法：
1. 在 cloud_api.py 中导入此模块
2. 调用 patch_connection_manager() 函数

环境变量：
- WEBSOCKET_BROADCAST=redis  # 启用Redis广播
- REDIS_URL=redis://localhost:6379/0  # Redis连接URL
"""

import asyncio
import contextlib
import json
import logging
import os
import time
from collections.abc import Callable
from typing import Any

from core.diagnostic import safe_create_task

logger = logging.getLogger(__name__)


class RedisPubSubManager:
    """
    Redis Pub/Sub 管理器 - 实现跨实例 WebSocket 消息广播
    """

    _instance = None

    # Redis频道前缀
    CHANNEL_PREFIX = "sb:ws:broadcast:"

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._redis = None
        self._pubsub = None
        self._task = None
        self._message_handlers: list[Callable] = []
        self._enabled = os.environ.get("WEBSOCKET_BROADCAST", "memory").lower() == "redis"

        if self._enabled:
            try:
                self._connect()
            except Exception as e:
                logger.error(f"[RedisPubSub] 初始化失败，禁用广播: {e}")
                self._enabled = False

        self._initialized = True

    def _connect(self):
        """连接Redis"""
        try:
            import redis.asyncio as aioredis
            redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
            self._redis = aioredis.from_url(redis_url)
            logger.info(f"[RedisPubSub] 已连接到Redis: {redis_url}")
        except ImportError:
            logger.error("[RedisPubSub] 缺少redis依赖，请安装: pip install redis")
            raise

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def start(self):
        """启动Pub/Sub监听"""
        if not self._enabled or self._pubsub:
            return

        try:
            self._pubsub = self._redis.pubsub()
            await self._pubsub.subscribe(f"{self.CHANNEL_PREFIX}*")

            # 启动监听任务
            self._task = safe_create_task(self._listener(), name="_listener")
            logger.info("[RedisPubSub] 广播监听已启动")
        except Exception as e:
            logger.error(f"[RedisPubSub] 启动失败: {e}")
            self._enabled = False

    async def stop(self):
        """停止Pub/Sub监听"""
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

        if self._pubsub:
            await self._pubsub.unsubscribe()
            await self._pubsub.close()

        if self._redis:
            await self._redis.close()

        logger.info("[RedisPubSub] 广播监听已停止")

    async def _listener(self):
        """监听Redis消息"""
        try:
            async for message in self._pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        # 调用所有注册的消息处理器
                        for handler in self._message_handlers:
                            try:
                                await handler(data)
                            except Exception as e:
                                logger.error(f"[RedisPubSub] 消息处理器错误: {e}")
                    except json.JSONDecodeError:
                        logger.error(f"[RedisPubSub] 消息解析失败: {message['data']}")
        except asyncio.CancelledError:
            logger.debug("[RedisPubSub] 监听任务已取消")
        except Exception as e:
            logger.error(f"[RedisPubSub] 监听错误: {e}")

    async def broadcast(self, user_id: str, message: dict[str, Any]):
        """广播消息给所有实例"""
        if not self._enabled or not self._redis:
            return

        try:
            channel = f"{self.CHANNEL_PREFIX}{user_id}"
            data = json.dumps({
                "user_id": user_id,
                "message": message,
                "timestamp": time.time(),
                "instance_id": os.environ.get("HOSTNAME", "unknown")
            })
            await self._redis.publish(channel, data)
            logger.debug(f"[RedisPubSub] 消息已广播到频道 {channel}")
        except Exception as e:
            logger.error(f"[RedisPubSub] 广播失败: {e}")

    def register_handler(self, handler: Callable):
        """注册消息处理器"""
        self._message_handlers.append(handler)
        logger.debug(f"[RedisPubSub] 注册消息处理器，当前数量: {len(self._message_handlers)}")

    def unregister_handler(self, handler: Callable):
        """注销消息处理器"""
        if handler in self._message_handlers:
            self._message_handlers.remove(handler)


# 全局Pub/Sub管理器实例
pubsub_manager = RedisPubSubManager()


def patch_connection_manager(connection_manager_class):
    """
    为 ConnectionManager 添加 Redis Pub/Sub 支持

    使用方法：
        from api.websocket_redis_patch import patch_connection_manager
        patch_connection_manager(ConnectionManager)
    """
    connection_manager_class.__init__ if hasattr(connection_manager_class, '__init__') else lambda self: None
    original_send_to_user = connection_manager_class.send_to_user

    def new_init(self):
        """新的初始化方法（同步版本）"""
        if hasattr(self, '_init_complete') and self._init_complete:
            return
        self._init_complete = True

        # 启动Redis Pub/Sub监听
        if pubsub_manager.enabled:
            async def handle_broadcast_message(data):
                user_id = data.get("user_id")
                message = data.get("message")
                if user_id and message:
                    await self._send_to_local_user(user_id, message)

            pubsub_manager.register_handler(handle_broadcast_message)
            # 使用 asyncio.create_task 启动后台任务
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(pubsub_manager.start())
            except RuntimeError:
                # 如果没有运行中的事件循环，稍后再启动
                pass
            logger.info("[ConnectionManager] Redis Pub/Sub 广播已启用")

    async def new_send_to_user(self, user_id, message):
        """增强的 send_to_user 方法，添加Redis广播"""
        # 调用原始方法
        result = await original_send_to_user(self, user_id, message)

        # 通过Redis广播给其他实例
        if pubsub_manager.enabled:
            await pubsub_manager.broadcast(user_id, message)

        return result

    async def _send_to_local_user(self, user_id, message):
        """只发送给本地连接的客户端"""
        from starlette.websockets import WebSocketState

        # 标准化消息格式
        normalized_message = self._normalize_message(message.copy()) if hasattr(self, '_normalize_message') else message

        connection_ids = self._user_connections.get(user_id, set()).copy()
        sent_count = 0
        disconnected = []

        for conn_id in connection_ids:
            websocket = self._connections.get(conn_id)
            if not websocket:
                disconnected.append((conn_id, user_id))
                continue

            try:
                if (hasattr(websocket, 'client_state') and
                    websocket.client_state != WebSocketState.CONNECTED):
                    disconnected.append((conn_id, user_id))
                    continue

                if (hasattr(websocket, 'application_state') and
                    websocket.application_state != WebSocketState.CONNECTED):
                    disconnected.append((conn_id, user_id))
                    continue

                await websocket.send_json(normalized_message)
                sent_count += 1

            except Exception as e:
                logger.debug(f"[ConnectionManager] 发送消息失败: {e}")
                disconnected.append((conn_id, user_id))

        # 批量清理断开的连接
        for conn_id, uid in disconnected:
            if hasattr(self, 'disconnect'):
                self.disconnect(conn_id, uid)

        if sent_count > 0:
            logger.debug(f"[ConnectionManager] 从Redis广播接收到消息，发送给 {sent_count} 个本地连接")

        return sent_count

    # 应用补丁
    connection_manager_class.__init__ = new_init
    connection_manager_class.send_to_user = new_send_to_user
    connection_manager_class._send_to_local_user = _send_to_local_user

    logger.info("[WebSocketRedisPatch] ConnectionManager 补丁已应用")


# 自动应用补丁（如果环境变量已设置）
if os.environ.get("WEBSOCKET_BROADCAST", "memory").lower() == "redis":
    logger.info("[WebSocketRedisPatch] 检测到 WEBSOCKET_BROADCAST=redis，准备应用补丁")
    # 补丁将在 cloud_api.py 导入时应用
