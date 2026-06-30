#!/usr/bin/env python3
"""
Redis后端兼容性导入

为了保持向后兼容，从此模块导入实际使用core.sync.redis_backend
"""

from core.sync.redis_backend import (
    RedisConfig,
    RedisConnectionPool,
    RedisKeyBuilder,
    RedisStorageBackend,
    get_redis_storage,
    is_redis_available,
)

__all__ = [
    "RedisConfig",
    "RedisConnectionPool",
    "RedisStorageBackend",
    "RedisKeyBuilder",
    "get_redis_storage",
    "is_redis_available",
]
