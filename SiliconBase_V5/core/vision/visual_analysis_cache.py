#!/usr/bin/env python3
"""
视觉分析缓存管理器 - 带LRU淘汰和用户隔离

功能特性:
- 用户隔离：每个用户有独立的缓存空间
- LRU淘汰：用户数和每用户缓存数都有上限，超出时淘汰最久未使用的
- TTL过期：支持自定义缓存过期时间
- 线程安全：使用RLock保证并发安全
- 零静默失败：所有错误都记录日志
"""

import logging
import threading
import time
from collections import OrderedDict

# 配置日志
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        '[%(asctime)s] [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class VisualAnalysisCache:
    """视觉分析缓存（LRU淘汰 + 用户隔离）"""

    # 配置常量
    MAX_USERS = 100              # 最大用户数
    MAX_CACHE_PER_USER = 50      # 每用户最大缓存数
    DEFAULT_TTL_SECONDS = 5      # 默认TTL（秒）

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

        self._user_caches: dict[str, OrderedDict] = {}
        self._user_locks: dict[str, threading.RLock] = {}
        self._user_last_access: dict[str, float] = {}
        self._initialized = True

        logger.info("[VisualAnalysisCache] 初始化完成")

    def _get_or_create_user_cache(self, user_id: str) -> OrderedDict:
        """获取或创建用户缓存

        包含LRU淘汰逻辑：如果用户数超限，淘汰最久未使用的用户

        Args:
            user_id: 用户ID

        Returns:
            用户的缓存OrderedDict
        """
        if user_id in self._user_caches:
            # 更新最后访问时间
            self._user_last_access[user_id] = time.time()
            return self._user_caches[user_id]

        # 检查用户数限制
        if len(self._user_caches) >= self.MAX_USERS:
            # LRU淘汰：找到最久未使用的用户
            try:
                oldest_user = min(
                    self._user_last_access.keys(),
                    key=lambda u: self._user_last_access.get(u, 0)
                )

                with self._user_locks.get(oldest_user, threading.Lock()):
                    if oldest_user in self._user_caches:
                        del self._user_caches[oldest_user]
                        del self._user_last_access[oldest_user]
                        if oldest_user in self._user_locks:
                            del self._user_locks[oldest_user]

                        logger.info(f"[VisualAnalysisCache] LRU淘汰用户: {oldest_user}")
            except Exception as e:
                logger.error(f"[VisualAnalysisCache] LRU淘汰失败: {e}")
                # 不阻止新用户创建

        # 创建新用户缓存
        self._user_caches[user_id] = OrderedDict()
        self._user_locks[user_id] = threading.RLock()
        self._user_last_access[user_id] = time.time()

        logger.debug(f"[VisualAnalysisCache] 创建用户缓存: {user_id}")
        return self._user_caches[user_id]

    def get_analysis(self, user_id: str, screenshot_hash: str) -> dict | None:
        """获取缓存的视觉分析结果

        Args:
            user_id: 用户ID
            screenshot_hash: 截图哈希值

        Returns:
            缓存的分析结果，未命中或过期返回None

        错误处理:
            - user_id为None: ERROR日志，返回None
            - screenshot_hash为None: ERROR日志，返回None
            - 缓存过期: 返回None，删除过期缓存
        """
        if not user_id:
            logger.error("[VisualAnalysisCache] user_id为空")
            return None

        if not screenshot_hash:
            logger.error("[VisualAnalysisCache] screenshot_hash为空")
            return None

        try:
            user_cache = self._get_or_create_user_cache(user_id)
            user_lock = self._user_locks.get(user_id)

            if not user_lock:
                logger.error(f"[VisualAnalysisCache] 用户锁不存在: {user_id}")
                return None

            with user_lock:
                if screenshot_hash not in user_cache:
                    return None

                cached = user_cache[screenshot_hash]

                # 检查TTL
                timestamp = cached.get("timestamp", 0)
                ttl = cached.get("ttl", self.DEFAULT_TTL_SECONDS)

                if time.time() - timestamp > ttl:
                    # 过期，删除
                    del user_cache[screenshot_hash]
                    logger.debug(f"[VisualAnalysisCache] 缓存过期删除: {screenshot_hash[:8]}...")
                    return None

                # 命中，移动到末尾（最新）
                result = cached["result"]
                user_cache.move_to_end(screenshot_hash)

                logger.debug(f"[VisualAnalysisCache] 缓存命中: {screenshot_hash[:8]}...")
                return result

        except Exception as e:
            logger.error(f"[VisualAnalysisCache] 获取缓存失败: {e}", exc_info=True)
            return None

    def cache_analysis(self, user_id: str, screenshot_hash: str,
                      result: dict, ttl: int = None) -> bool:
        """缓存视觉分析结果

        Args:
            user_id: 用户ID
            screenshot_hash: 截图哈希值
            result: 分析结果字典
            ttl: 过期时间（秒），默认使用DEFAULT_TTL_SECONDS

        Returns:
            是否成功缓存

        错误处理:
            - 任何参数为None: ERROR日志，返回False
            - 缓存已满: LRU淘汰最旧的
            - 写入失败: ERROR日志，返回False
        """
        if not user_id:
            logger.error("[VisualAnalysisCache] user_id为空")
            return False

        if not screenshot_hash:
            logger.error("[VisualAnalysisCache] screenshot_hash为空")
            return False

        if not result:
            logger.error("[VisualAnalysisCache] result为空")
            return False

        try:
            user_cache = self._get_or_create_user_cache(user_id)
            user_lock = self._user_locks.get(user_id)

            if not user_lock:
                logger.error(f"[VisualAnalysisCache] 用户锁不存在: {user_id}")
                return False

            with user_lock:
                # LRU淘汰
                while len(user_cache) >= self.MAX_CACHE_PER_USER:
                    try:
                        oldest_hash, _ = user_cache.popitem(last=False)
                        logger.debug(f"[VisualAnalysisCache] LRU淘汰缓存: {oldest_hash[:8]}...")
                    except Exception as e:
                        logger.error(f"[VisualAnalysisCache] LRU淘汰失败: {e}")
                        break

                # 添加新缓存
                user_cache[screenshot_hash] = {
                    "result": result,
                    "timestamp": time.time(),
                    "ttl": ttl if ttl is not None else self.DEFAULT_TTL_SECONDS
                }

                logger.debug(f"[VisualAnalysisCache] 缓存添加成功: {screenshot_hash[:8]}...")
                return True

        except Exception as e:
            logger.error(f"[VisualAnalysisCache] 缓存添加失败: {e}", exc_info=True)
            return False

    def invalidate_user_cache(self, user_id: str) -> bool:
        """使某个用户的所有缓存失效

        用于用户登出或配置变更时

        Args:
            user_id: 用户ID

        Returns:
            是否成功清除
        """
        if not user_id:
            logger.error("[VisualAnalysisCache] user_id为空")
            return False

        try:
            if user_id in self._user_caches:
                with self._user_locks.get(user_id, threading.Lock()):
                    del self._user_caches[user_id]
                    del self._user_last_access[user_id]
                    if user_id in self._user_locks:
                        del self._user_locks[user_id]

                logger.info(f"[VisualAnalysisCache] 用户缓存已清除: {user_id}")
                return True

            return True  # 用户不存在也算成功

        except Exception as e:
            logger.error(f"[VisualAnalysisCache] 清除用户缓存失败: {e}")
            return False

    def get_stats(self) -> dict:
        """获取缓存统计信息

        Returns:
            包含统计信息的字典
        """
        try:
            total_users = len(self._user_caches)
            total_entries = sum(len(cache) for cache in self._user_caches.values())

            return {
                "total_users": total_users,
                "total_entries": total_entries,
                "max_users": self.MAX_USERS,
                "max_cache_per_user": self.MAX_CACHE_PER_USER,
                "avg_entries_per_user": total_entries / total_users if total_users > 0 else 0
            }
        except Exception as e:
            logger.error(f"[VisualAnalysisCache] 获取统计失败: {e}")
            return {}

    def get_user_stats(self, user_id: str) -> dict | None:
        """获取指定用户的缓存统计

        Args:
            user_id: 用户ID

        Returns:
            用户统计信息，用户不存在返回None
        """
        if not user_id:
            logger.error("[VisualAnalysisCache] user_id为空")
            return None

        try:
            if user_id not in self._user_caches:
                return None

            user_cache = self._user_caches[user_id]
            last_access = self._user_last_access.get(user_id, 0)

            return {
                "user_id": user_id,
                "cache_count": len(user_cache),
                "max_cache": self.MAX_CACHE_PER_USER,
                "last_access": last_access,
                "last_access_ago": time.time() - last_access if last_access > 0 else None
            }
        except Exception as e:
            logger.error(f"[VisualAnalysisCache] 获取用户统计失败: {e}")
            return None

    def get_latest(self, user_id: str, key: str = "_global_latest", max_age: float = 5.0) -> dict | None:
        """
        获取最新缓存结果（固定 key，不依赖 screenshot_hash）。
        用于全局感知缓存，供 AgentLoop 快速读取最新视觉分析结果。
        """
        if not user_id:
            logger.error("[VisualAnalysisCache] user_id为空")
            return None

        try:
            user_cache = self._get_or_create_user_cache(user_id)
            user_lock = self._user_locks.get(user_id)
            if not user_lock:
                return None

            with user_lock:
                if key not in user_cache:
                    return None

                cached = user_cache[key]
                if time.time() - cached.get("timestamp", 0) > max_age:
                    del user_cache[key]
                    return None

                return cached["result"]
        except Exception as e:
            logger.error(f"[VisualAnalysisCache] 获取最新缓存失败: {e}")
            return None

    def cache_latest(self, user_id: str, key: str, result: dict, ttl: float = 10.0) -> bool:
        """
        缓存最新结果（固定 key）。
        供后台感知刷新任务写入，AgentLoop 快速读取。
        """
        return self.cache_analysis(user_id, key, result, ttl=int(ttl))

    def clear_all(self) -> bool:
        """清除所有缓存

        Returns:
            是否成功清除
        """
        try:
            self._user_caches.clear()
            self._user_last_access.clear()
            self._user_locks.clear()

            logger.info("[VisualAnalysisCache] 所有缓存已清除")
            return True
        except Exception as e:
            logger.error(f"[VisualAnalysisCache] 清除所有缓存失败: {e}")
            return False


# 全局单例实例
_global_cache: VisualAnalysisCache | None = None
_global_cache_lock = threading.Lock()


def get_visual_analysis_cache() -> VisualAnalysisCache:
    """获取全局视觉分析缓存实例

    Returns:
        VisualAnalysisCache单例
    """
    global _global_cache
    if _global_cache is None:
        with _global_cache_lock:
            if _global_cache is None:
                _global_cache = VisualAnalysisCache()
    return _global_cache
