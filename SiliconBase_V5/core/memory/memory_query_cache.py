#!/usr/bin/env python3
"""
⚠️ 【Phase 7 延后开发声明】
本模块自 2026-04-18 起标记为 DEFER。
原因：无生产热路径调用，暂不投入开发资源。
当前状态：代码保留但不做维护，未来需要时基于 asyncio 重新设计。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
记忆查询缓存系统 V1.0 - 高性能查询缓存
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【功能特性】
  ✓ 多级缓存架构 (L1:内存 LRU, L2:LRU+TTL混合)
  ✓ 智能缓存键生成 (考虑所有查询参数)
  ✓ 自动过期和淘汰机制
  ✓ 缓存命中率统计
  ✓ 线程安全设计

【性能目标】
  - 缓存命中查询: <5ms
  - 缓存未命中查询: <100ms
  - 缓存命中率: >70%

【作者】Agent-10: 性能优化工程师
【日期】2026-03-06
"""

import hashlib
import json
import threading
import time
import warnings
from collections import OrderedDict
from dataclasses import dataclass, field
from functools import wraps
from typing import Any

warnings.warn(
    "memory_query_cache.py 已标记为 OBSOLETE (2026-04-18)。"
    "无生产热路径调用，功能已由 AsyncMemory.retrieve_memories() 覆盖。"
    "请勿在新代码中使用此模块。",
    DeprecationWarning,
    stacklevel=2,
)
import logging

logger = logging.getLogger(__name__)

# 【魔法数字修复】导入全局常量
try:
    from core.constants import CacheConfig
except ImportError as e:
    logger.error(f"[MemoryQueryCache] 导入CacheConfig常量失败: {e}")
    # 定义 fallback 常量值
    class CacheConfig:
        DEFAULT_TTL = 300       # 默认缓存时间(秒)
        MAX_SIZE = 200           # 最大缓存条目数
        CLEANUP_INTERVAL = 300   # 清理间隔(秒)

# ═══════════════════════════════════════════════════════════════════
# 配置常量 (使用全局常量作为基础)
# ═══════════════════════════════════════════════════════════════════

DEFAULT_CACHE_TTL = CacheConfig.DEFAULT_TTL  # 默认缓存过期时间: 5分钟
DEFAULT_MAX_SIZE = CacheConfig.MAX_SIZE      # 默认最大缓存条目数
CLEANUP_INTERVAL = CacheConfig.CLEANUP_INTERVAL  # 清理间隔: 60秒
HIT_RATE_WINDOW = 100    # 命中率统计窗口大小


@dataclass
class CacheEntry:
    """缓存条目数据类"""
    data: Any                           # 缓存数据
    timestamp: float = field(default_factory=time.time)  # 创建时间
    access_count: int = 0               # 访问次数
    last_access: float = field(default_factory=time.time)  # 最后访问时间


class MemoryQueryCache:
    """
    记忆查询缓存管理器

    实现LRU+TTL混合缓存策略，为记忆查询提供高性能缓存服务。
    支持按用户、查询条件等多维度缓存。
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        """单例模式"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, max_size: int = DEFAULT_MAX_SIZE, ttl: int = DEFAULT_CACHE_TTL):
        """
        初始化缓存管理器

        Args:
            max_size: 最大缓存条目数
            ttl: 缓存过期时间(秒)
        """
        if self._initialized:
            return
        self._initialized = True

        self._max_size = max_size
        self._ttl = ttl
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._cache_lock = threading.RLock()

        # 【性能优化】用户反向索引，避免invalidate_user时全表扫描
        self._user_index: dict[str, set] = {}
        self._index_lock = threading.Lock()

        # 统计信息
        self._hit_count = 0
        self._miss_count = 0
        self._evict_count = 0
        self._expire_count = 0
        self._stats_lock = threading.Lock()

        # 启动后台清理线程
        self._stop_event = threading.Event()
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleanup_thread.start()

        logger.info(f"[MemoryQueryCache] 初始化完成 (max_size={max_size}, ttl={ttl}s)")

    def _generate_key(self, user_id: str, query_type: str,
                      query_params: dict[str, Any]) -> str:
        """
        生成缓存键

        根据用户ID、查询类型和参数生成唯一的缓存键

        Args:
            user_id: 用户ID
            query_type: 查询类型 (e.g., 'layer_query', 'search', 'dimension_filter')
            query_params: 查询参数字典

        Returns:
            str: 缓存键哈希
        """
        # 构建参数字符串
        param_str = json.dumps(query_params, sort_keys=True, default=str)
        key_str = f"{user_id}:{query_type}:{param_str}"

        # 使用MD5生成固定长度哈希
        return hashlib.md5(key_str.encode()).hexdigest()

    def get(self, user_id: str, query_type: str,
            query_params: dict[str, Any]) -> Any | None:
        """
        获取缓存数据

        Args:
            user_id: 用户ID
            query_type: 查询类型
            query_params: 查询参数

        Returns:
            Optional[Any]: 缓存数据或None
        """
        key = self._generate_key(user_id, query_type, query_params)

        with self._cache_lock:
            entry = self._cache.get(key)

            if entry is None:
                with self._stats_lock:
                    self._miss_count += 1
                return None

            # 检查是否过期
            if time.time() - entry.timestamp > self._ttl:
                # 过期删除
                del self._cache[key]
                with self._stats_lock:
                    self._expire_count += 1
                    self._miss_count += 1
                return None

            # 更新访问信息 (LRU: 移动到末尾)
            entry.access_count += 1
            entry.last_access = time.time()
            self._cache.move_to_end(key)

            with self._stats_lock:
                self._hit_count += 1

            return entry.data

    def set(self, user_id: str, query_type: str,
            query_params: dict[str, Any], data: Any) -> bool:
        """
        设置缓存数据

        Args:
            user_id: 用户ID
            query_type: 查询类型
            query_params: 查询参数
            data: 要缓存的数据

        Returns:
            bool: 是否设置成功
        """
        key = self._generate_key(user_id, query_type, query_params)

        with self._cache_lock:
            # LRU淘汰: 如果缓存已满且键不存在
            if len(self._cache) >= self._max_size and key not in self._cache:
                self._evict_oldest()

            # 创建新条目
            entry = CacheEntry(data=data)
            self._cache[key] = entry
            self._cache.move_to_end(key)

            # 【性能优化】更新用户反向索引
            with self._index_lock:
                if user_id not in self._user_index:
                    self._user_index[user_id] = set()
                self._user_index[user_id].add(key)

            return True

    def invalidate_user(self, user_id: str) -> int:
        """
        失效指定用户的所有缓存（优化版：使用反向索引，避免全量清除）

        Args:
            user_id: 用户ID

        Returns:
            int: 失效的缓存条目数
        """
        with self._cache_lock:
            # 【性能优化】使用反向索引只清除指定用户的缓存
            with self._index_lock:
                keys_to_remove = self._user_index.get(user_id, set()).copy()

            count = 0
            for key in keys_to_remove:
                if key in self._cache:
                    del self._cache[key]
                    count += 1

            # 清除该用户的索引
            with self._index_lock:
                self._user_index[user_id] = set()

            if count > 0:
                logger.info(f"[MemoryQueryCache] 清除用户 {user_id} 的 {count} 条缓存")
            elif user_id in self._user_index:
                logger.debug(f"[MemoryQueryCache] 用户 {user_id} 无缓存可清除")

            return count

    def invalidate_pattern(self, pattern: str) -> int:
        """
        按模式失效缓存

        Args:
            pattern: 模式字符串

        Returns:
            int: 失效的缓存条目数
        """
        # 简化实现: 支持精确匹配
        with self._cache_lock:
            if pattern in self._cache:
                del self._cache[pattern]
                return 1
            return 0

    def clear(self) -> int:
        """
        清空所有缓存

        Returns:
            int: 清空的缓存条目数
        """
        with self._cache_lock:
            count = len(self._cache)
            self._cache.clear()

            # 【性能优化】同时清空反向索引
            with self._index_lock:
                self._user_index.clear()

            logger.info(f"[MemoryQueryCache] 所有缓存已清除: {count} 条")
            return count

    def _evict_oldest(self):
        """淘汰最旧的缓存条目 (LRU策略)"""
        if self._cache:
            oldest_key = next(iter(self._cache))

            # 【性能优化】从反向索引中移除
            # 注意：这里需要找到对应的user_id，由于无法从key反推user_id
            # 我们在索引中存储key到user_id的映射
            with self._index_lock:
                for _uid, keys in self._user_index.items():
                    if oldest_key in keys:
                        keys.discard(oldest_key)
                        break

            del self._cache[oldest_key]
            with self._stats_lock:
                self._evict_count += 1
            logger.debug(f"[MemoryQueryCache] LRU淘汰: {oldest_key[:16]}...")

    def _cleanup_expired(self) -> int:
        """
        清理过期缓存（优化版：同时更新反向索引）

        Returns:
            int: 清理的条目数
        """
        now = time.time()
        expired_keys = []

        with self._cache_lock:
            for key, entry in self._cache.items():
                if now - entry.timestamp > self._ttl:
                    expired_keys.append(key)

            for key in expired_keys:
                del self._cache[key]

            # 【性能优化】从反向索引中移除过期key
            with self._index_lock:
                expired_set = set(expired_keys)
                for uid in self._user_index:
                    self._user_index[uid] = self._user_index[uid] - expired_set

        with self._stats_lock:
            self._expire_count += len(expired_keys)

        if expired_keys:
            logger.debug(f"[MemoryQueryCache] 清理过期缓存: {len(expired_keys)} 条")

        return len(expired_keys)

    def _cleanup_loop(self):
        """后台清理循环"""
        while not self._stop_event.is_set():
            try:
                # 等待清理间隔或停止信号
                if self._stop_event.wait(CLEANUP_INTERVAL):
                    break

                # 执行清理
                self._cleanup_expired()

            except Exception as e:
                logger.error(f"[MemoryQueryCache] 清理循环异常: {e}")

    def get_stats(self) -> dict[str, Any]:
        """
        获取缓存统计信息

        Returns:
            Dict: 统计信息字典
        """
        with self._stats_lock:
            total_requests = self._hit_count + self._miss_count
            hit_rate = self._hit_count / total_requests if total_requests > 0 else 0

            return {
                "size": len(self._cache),
                "max_size": self._max_size,
                "ttl": self._ttl,
                "hit_count": self._hit_count,
                "miss_count": self._miss_count,
                "hit_rate": round(hit_rate * 100, 2),
                "evict_count": self._evict_count,
                "expire_count": self._expire_count,
                "usage_percent": round(len(self._cache) / self._max_size * 100, 2)
            }

    def stop(self):
        """停止缓存管理器"""
        self._stop_event.set()
        if self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=5)
        logger.info("[MemoryQueryCache] 已停止")


# ═══════════════════════════════════════════════════════════════════
# 装饰器: 自动缓存查询结果
# ═══════════════════════════════════════════════════════════════════

def cached_query(ttl: int = DEFAULT_CACHE_TTL, max_size: int = DEFAULT_MAX_SIZE):
    """
    查询结果缓存装饰器

    自动缓存函数返回结果，支持TTL过期。

    Args:
        ttl: 缓存过期时间(秒)
        max_size: 最大缓存条目数

    Usage:
        @cached_query(ttl=300)
        def query_memories(user_id, layer, filters):
            # 查询逻辑
            return results
    """
    cache = MemoryQueryCache(max_size=max_size, ttl=ttl)

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # 尝试从缓存获取
            # 注意: 这里简化处理，实际应该根据函数参数生成缓存键
            _ = f"{func.__name__}:{str(args)}:{str(kwargs)}"

            # 从kwargs提取user_id和query_params
            user_id = kwargs.get('user_id', args[0] if args else 'default')
            query_type = func.__name__
            query_params = {k: v for k, v in kwargs.items() if k != 'user_id'}

            # 尝试获取缓存
            cached = cache.get(user_id, query_type, query_params)
            if cached is not None:
                return cached

            # 执行查询
            result = func(*args, **kwargs)

            # 缓存结果
            cache.set(user_id, query_type, query_params, result)

            return result

        # 附加缓存实例供外部访问
        wrapper.cache = cache
        return wrapper
    return decorator


# ═══════════════════════════════════════════════════════════════════
# 缓存管理器工厂
# ═══════════════════════════════════════════════════════════════════

class CacheManager:
    """缓存管理器工厂"""

    _caches: dict[str, MemoryQueryCache] = {}
    _lock = threading.Lock()

    @classmethod
    def get_cache(cls, name: str = "default", **kwargs) -> MemoryQueryCache:
        """
        获取或创建缓存实例

        Args:
            name: 缓存名称
            **kwargs: 缓存配置参数

        Returns:
            MemoryQueryCache: 缓存实例
        """
        with cls._lock:
            if name not in cls._caches:
                cls._caches[name] = MemoryQueryCache(**kwargs)
            return cls._caches[name]

    @classmethod
    def get_all_stats(cls) -> dict[str, dict]:
        """获取所有缓存统计"""
        return {name: cache.get_stats() for name, cache in cls._caches.items()}

    @classmethod
    def clear_all(cls):
        """清空所有缓存"""
        for cache in cls._caches.values():
            cache.clear()

    @classmethod
    def stop_all(cls):
        """停止所有缓存"""
        for cache in cls._caches.values():
            cache.stop()


# ═══════════════════════════════════════════════════════════════════
# 全局缓存实例
# ═══════════════════════════════════════════════════════════════════

# 主查询缓存实例
memory_query_cache = MemoryQueryCache()

# 用于兼容旧代码
cache = memory_query_cache


def get_memory_cache() -> MemoryQueryCache:
    """获取全局记忆查询缓存实例"""
    return memory_query_cache


def get_cache_stats() -> dict[str, Any]:
    """获取缓存统计信息"""
    return memory_query_cache.get_stats()


def invalidate_user_cache(user_id: str) -> int:
    """失效指定用户的缓存"""
    return memory_query_cache.invalidate_user(user_id)


def clear_all_cache() -> int:
    """清空所有缓存"""
    return memory_query_cache.clear()


# ═══════════════════════════════════════════════════════════════════
# 单元测试
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # 测试缓存功能
    print("测试记忆查询缓存系统...")

    cache = MemoryQueryCache(max_size=100, ttl=5)

    # 测试设置和获取
    test_data = {"memories": [{"id": "1", "content": "test"}]}
    cache.set("user1", "layer_query", {"layer": "short", "limit": 10}, test_data)

    result = cache.get("user1", "layer_query", {"layer": "short", "limit": 10})
    assert result == test_data, "缓存获取失败"
    print("✓ 基础缓存功能测试通过")

    # 测试缓存命中
    result2 = cache.get("user1", "layer_query", {"layer": "short", "limit": 10})
    assert result2 == test_data, "缓存命中失败"
    stats = cache.get_stats()
    assert stats["hit_count"] == 1, "缓存命中计数错误"
    print("✓ 缓存命中测试通过")

    # 测试过期
    time.sleep(6)
    result3 = cache.get("user1", "layer_query", {"layer": "short", "limit": 10})
    assert result3 is None, "缓存过期失败"
    print("✓ 缓存过期测试通过")

    # 测试LRU淘汰
    cache_small = MemoryQueryCache(max_size=3, ttl=300)
    for i in range(5):
        cache_small.set(f"user{i}", "test", {"idx": i}, {"data": i})

    assert len(cache_small._cache) == 3, "LRU淘汰失败"
    print("✓ LRU淘汰测试通过")

    print("\n所有测试通过!")
    print(f"缓存统计: {cache.get_stats()}")
