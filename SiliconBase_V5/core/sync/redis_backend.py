#!/usr/bin/env python3
"""
Redis存储后端 - 原生异步版本 V6.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
全部方法改为 async def，基于 redis.asyncio，彻底消除同步阻塞。

向后兼容说明：
- 同步调用方必须改为 await
- 如需内存回退，fakeredis.aioredis.FakeRedis 提供完全相同的 async API
"""
import asyncio
import contextlib
import json
import logging
import os
import threading
from typing import Any
from urllib.parse import urlparse

from redis.asyncio import ConnectionPool, Redis

logger = logging.getLogger(__name__)


class RedisConfig:
    """Redis配置管理 - 优先从配置文件读取，其次环境变量"""

    _initialized = False
    _config_lock = asyncio.Lock()

    REDIS_URL = "redis://localhost:6379/0"
    REDIS_HOST = "localhost"
    REDIS_PORT = 6379
    REDIS_DB = 0
    REDIS_PASSWORD = None
    REDIS_SOCKET_TIMEOUT = 5.0
    REDIS_SOCKET_CONNECT_TIMEOUT = 5.0
    REDIS_HEALTH_CHECK_INTERVAL = 30
    KEY_PREFIX = "siliconbase"
    STORAGE_BACKEND = "redis"

    @classmethod
    async def _load_from_config(cls):
        """从配置文件加载Redis配置"""
        try:
            from core.config import config
            redis_config = config.get("services.redis", {})

            def get_config(key, env_key, default):
                value = redis_config.get(key)
                if value is None or value == "" or value == "~":
                    value = os.getenv(env_key)
                if value is None or value == "" or value == "~":
                    value = default
                return value

            cls.REDIS_HOST = get_config("host", "REDIS_HOST", "localhost")
            cls.REDIS_PORT = int(get_config("port", "REDIS_PORT", "6379"))
            cls.REDIS_DB = int(get_config("db", "REDIS_DB", "0"))

            password = redis_config.get("password")
            if password is None or password == "" or password == "~":
                password = os.getenv("REDIS_PASSWORD")
            cls.REDIS_PASSWORD = password if password else None

            url = redis_config.get("url")
            if url is None or url == "" or url == "~":
                url = os.getenv("REDIS_URL")
            if url:
                cls.REDIS_URL = url
                parsed = urlparse(url)
                cls.REDIS_HOST = parsed.hostname or cls.REDIS_HOST
                cls.REDIS_PORT = parsed.port or cls.REDIS_PORT
                if parsed.password:
                    cls.REDIS_PASSWORD = parsed.password
                if parsed.path:
                    cls.REDIS_DB = int(parsed.path.lstrip("/")) if parsed.path.strip("/") else 0

            cls.STORAGE_BACKEND = get_config("backend", "STORAGE_BACKEND", "redis")
            cls.KEY_PREFIX = get_config("key_prefix", "REDIS_KEY_PREFIX", "siliconbase")
            cls.REDIS_SOCKET_TIMEOUT = float(get_config("socket_timeout", "REDIS_SOCKET_TIMEOUT", "5"))
            cls.REDIS_SOCKET_CONNECT_TIMEOUT = float(get_config("connect_timeout", "REDIS_SOCKET_CONNECT_TIMEOUT", "5"))

            cls._initialized = True
            logger.info(f"[RedisConfig] 配置加载完成: {cls.REDIS_HOST}:{cls.REDIS_PORT}/{cls.REDIS_DB}")
        except Exception as e:
            logger.warning(f"[RedisConfig] 从配置文件加载失败，使用默认配置: {e}")
            cls._load_from_env()

    @classmethod
    def _load_from_env(cls):
        """从环境变量加载（向后兼容）"""
        cls.STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "redis")
        cls.REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        cls.REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
        cls.REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
        cls.REDIS_DB = int(os.getenv("REDIS_DB", "0"))
        cls.REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")
        cls.REDIS_SOCKET_TIMEOUT = float(os.getenv("REDIS_SOCKET_TIMEOUT", "5"))
        cls.REDIS_SOCKET_CONNECT_TIMEOUT = float(os.getenv("REDIS_SOCKET_CONNECT_TIMEOUT", "5"))
        cls.REDIS_HEALTH_CHECK_INTERVAL = int(os.getenv("REDIS_HEALTH_CHECK_INTERVAL", "30"))
        cls.KEY_PREFIX = os.getenv("REDIS_KEY_PREFIX", "siliconbase")

    @classmethod
    async def initialize(cls):
        """初始化配置（协程安全）"""
        if not cls._initialized:
            async with cls._config_lock:
                if not cls._initialized:
                    await cls._load_from_config()

    @classmethod
    def is_redis_enabled(cls) -> bool:
        """检查是否启用Redis"""
        # 同步路径不触发配置加载，避免在 sync 上下文中意外阻塞
        return cls.STORAGE_BACKEND.lower() == "redis"

    @classmethod
    def get_connection_params(cls) -> dict[str, Any]:
        """获取连接参数"""
        return {
            "host": cls.REDIS_HOST,
            "port": cls.REDIS_PORT,
            "db": cls.REDIS_DB,
            "password": cls.REDIS_PASSWORD,
            "socket_timeout": cls.REDIS_SOCKET_TIMEOUT,
            "socket_connect_timeout": cls.REDIS_SOCKET_CONNECT_TIMEOUT,
            "health_check_interval": cls.REDIS_HEALTH_CHECK_INTERVAL,
            "decode_responses": True,
        }


class AsyncRedisConnectionPool:
    """Redis异步连接池管理 - 单例模式"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._client: Redis | None = None
        self._connection_error_count = 0
        self._last_error_time = 0.0

    async def _create_client(self) -> Redis | None:
        """创建异步Redis客户端（支持fakeredis回退）"""
        try:
            params = RedisConfig.get_connection_params()
            pool = ConnectionPool(
                host=params["host"],
                port=params["port"],
                db=params["db"],
                password=params["password"],
                socket_timeout=params["socket_timeout"],
                socket_connect_timeout=params["socket_connect_timeout"],
                health_check_interval=params["health_check_interval"],
                max_connections=50,
                retry_on_timeout=True,
            )
            client = Redis(connection_pool=pool)
            await client.ping()
            logger.info(f"[AsyncRedisConnectionPool] Redis连接成功: {params['host']}:{params['port']}")
            self._connection_error_count = 0
            return client
        except Exception as e:
            self._connection_error_count += 1
            self._last_error_time = asyncio.get_event_loop().time()
            if self._connection_error_count <= 3:
                logger.warning(f"[AsyncRedisConnectionPool] Redis连接失败({self._connection_error_count}/3): {e}")
            # fakeredis 回退
            try:
                from fakeredis.aioredis import FakeRedis
                logger.info("[AsyncRedisConnectionPool] 使用fakeredis作为替代")
                return FakeRedis(decode_responses=True)
            except ImportError:
                logger.warning("[AsyncRedisConnectionPool] fakeredis未安装")
                return None

    async def get_client(self) -> Redis | None:
        """获取Redis客户端（协程安全）"""
        if self._client is None:
            self._client = await self._create_client()
        return self._client

    async def reconnect(self) -> Redis | None:
        """重新连接"""
        if self._client:
            with contextlib.suppress(Exception):
                await self._client.close()
        self._client = None
        self._connection_error_count = 0
        return await self.get_client()


class AsyncRedisStorageBackend:
    """Redis异步存储后端实现"""

    def __init__(self):
        self._pool = AsyncRedisConnectionPool()
        self._key_prefix = RedisConfig.KEY_PREFIX

    def _make_key(self, *parts: str) -> str:
        """生成带前缀的key"""
        return f"{self._key_prefix}:{':'.join(parts)}"

    async def is_available(self) -> bool:
        """检查Redis是否可用"""
        client = await self._pool.get_client()
        if not client:
            return False
        try:
            await client.ping()
            return True
        except Exception:
            return False

    async def get(self, key: str) -> Any | None:
        """获取值"""
        client = await self._pool.get_client()
        if not client:
            return None
        try:
            data = await client.get(key)
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.warning(f"[AsyncRedisStorageBackend] get失败: {e}")
            return None

    async def set(self, key: str, value: Any, expire: int = None) -> bool:
        """设置值"""
        client = await self._pool.get_client()
        if not client:
            return False
        try:
            data = json.dumps(value, ensure_ascii=False)
            if expire:
                await client.setex(key, expire, data)
            else:
                await client.set(key, data)
            return True
        except Exception as e:
            logger.warning(f"[AsyncRedisStorageBackend] set失败: {e}")
            return False

    async def delete(self, key: str) -> bool:
        """删除key"""
        client = await self._pool.get_client()
        if not client:
            return False
        try:
            await client.delete(key)
            return True
        except Exception as e:
            logger.warning(f"[AsyncRedisStorageBackend] delete失败: {e}")
            return False

    async def hget(self, key: str, field: str) -> Any | None:
        """获取hash字段"""
        client = await self._pool.get_client()
        if not client:
            return None
        try:
            data = await client.hget(key, field)
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.warning(f"[AsyncRedisStorageBackend] hget失败: {e}")
            return None

    async def hset(self, key: str, field: str, value: Any) -> bool:
        """设置hash字段"""
        client = await self._pool.get_client()
        if not client:
            return False
        try:
            data = json.dumps(value, ensure_ascii=False)
            await client.hset(key, field, data)
            return True
        except Exception as e:
            logger.warning(f"[AsyncRedisStorageBackend] hset失败: {e}")
            return False

    async def hgetall(self, key: str) -> dict[str, Any]:
        """获取所有hash字段"""
        client = await self._pool.get_client()
        if not client:
            return {}
        try:
            data = await client.hgetall(key)
            return {k: json.loads(v) for k, v in data.items()}
        except Exception as e:
            logger.warning(f"[AsyncRedisStorageBackend] hgetall失败: {e}")
            return {}

    async def hdel(self, key: str, field: str) -> bool:
        """删除hash字段"""
        client = await self._pool.get_client()
        if not client:
            return False
        try:
            await client.hdel(key, field)
            return True
        except Exception as e:
            logger.warning(f"[AsyncRedisStorageBackend] hdel失败: {e}")
            return False

    async def publish(self, channel: str, message: str) -> bool:
        """发布消息到频道"""
        client = await self._pool.get_client()
        if not client:
            return False
        try:
            await client.publish(channel, message)
            return True
        except Exception as e:
            logger.warning(f"[AsyncRedisStorageBackend] publish失败: {e}")
            return False

    async def subscribe(self, channel: str):
        """订阅频道，返回PubSub对象"""
        client = await self._pool.get_client()
        if not client:
            return None
        try:
            pubsub = client.pubsub()
            await pubsub.subscribe(channel)
            return pubsub
        except Exception as e:
            logger.warning(f"[AsyncRedisStorageBackend] subscribe失败: {e}")
            return None

    async def zadd(self, key: str, score: float, member: str) -> bool:
        """添加到有序集合"""
        client = await self._pool.get_client()
        if not client:
            return False
        try:
            await client.zadd(key, {member: score})
            return True
        except Exception as e:
            logger.warning(f"[AsyncRedisStorageBackend] zadd失败: {e}")
            return False

    async def zrange(self, key: str, start: int, end: int) -> list[str]:
        """获取有序集合范围"""
        client = await self._pool.get_client()
        if not client:
            return []
        try:
            return await client.zrange(key, start, end)
        except Exception as e:
            logger.warning(f"[AsyncRedisStorageBackend] zrange失败: {e}")
            return []

    async def zrem(self, key: str, member: str) -> bool:
        """从有序集合移除成员"""
        client = await self._pool.get_client()
        if not client:
            return False
        try:
            await client.zrem(key, member)
            return True
        except Exception as e:
            logger.warning(f"[AsyncRedisStorageBackend] zrem失败: {e}")
            return False


class RedisKeyBuilder:
    """Redis Key构建器（纯工具类，无需async）"""
    PREFIX = "siliconbase"

    @classmethod
    def user_context(cls, user_id: str) -> str:
        return f"{cls.PREFIX}:user_context:{user_id}"

    @classmethod
    def session(cls, user_id: str, session_id: str) -> str:
        return f"{cls.PREFIX}:session:{user_id}:{session_id}"

    @classmethod
    def events(cls, user_id: str) -> str:
        return f"{cls.PREFIX}:events:{user_id}"

    @classmethod
    def task_queue(cls, user_id: str) -> str:
        return f"{cls.PREFIX}:task_queue:{user_id}"

    @classmethod
    def pubsub(cls, user_id: str) -> str:
        return f"{cls.PREFIX}:pubsub:{user_id}"


# ═══════════════════════════════════════════════════════════════
# 全局单例与工厂函数
# ═══════════════════════════════════════════════════════════════

_async_redis_storage: AsyncRedisStorageBackend | None = None
_storage_lock = asyncio.Lock()


async def get_async_redis_storage() -> AsyncRedisStorageBackend | None:
    """获取异步Redis存储后端实例（懒加载）"""
    global _async_redis_storage
    if _async_redis_storage is None:
        async with _storage_lock:
            if _async_redis_storage is None:
                await RedisConfig.initialize()
                if RedisConfig.is_redis_enabled():
                    _async_redis_storage = AsyncRedisStorageBackend()
                    if not await _async_redis_storage.is_available():
                        logger.warning("[get_async_redis_storage] Redis不可用，将使用内存存储")
                        _async_redis_storage = None
                else:
                    logger.info("[get_async_redis_storage] Redis未启用，使用内存存储")
    return _async_redis_storage


async def is_async_redis_available() -> bool:
    """检查Redis是否可用"""
    storage = await get_async_redis_storage()
    return storage is not None and await storage.is_available()


# ═══════════════════════════════════════════════════════════════
# 向后兼容别名（提醒调用方迁移到 async 版本）
# ═══════════════════════════════════════════════════════════════

# 旧名称直接指向新类，保持 import 兼容
RedisStorageBackend = AsyncRedisStorageBackend
RedisConnectionPool = AsyncRedisConnectionPool
get_redis_storage = get_async_redis_storage
is_redis_available = is_async_redis_available
