#!/usr/bin/env python3
"""
视觉描述缓存管理器 - 带LRU淘汰机制
"""
import time
from collections import OrderedDict

from core.logger import logger


class VisionCache:
    """
    视觉描述缓存
    - 最大条目数限制（默认10条）
    - TTL过期机制（默认5分钟）
    - LRU淘汰策略
    """

    def __init__(self, max_size: int = 10, ttl: int = 300):
        """
        Args:
            max_size: 最大缓存条目数
            ttl: 缓存过期时间（秒）
        """
        if max_size < 1:
            error_msg = f"[VisionCache] max_size必须>=1, 当前={max_size}"
            logger.error(error_msg)
            raise ValueError(error_msg)
        if ttl < 1:
            error_msg = f"[VisionCache] ttl必须>=1, 当前={ttl}"
            logger.error(error_msg)
            raise ValueError(error_msg)

        self.max_size = max_size
        self.ttl = ttl
        self._cache: OrderedDict[str, tuple[str, float]] = OrderedDict()
        self._hit_count = 0
        self._miss_count = 0

    def get(self, key: str) -> str | None:
        """
        获取缓存，带TTL检查

        无效返回=明确报错+打日志（返回None时记录debug）
        """
        if not isinstance(key, str):
            error_msg = f"[VisionCache] key类型错误: {type(key)}"
            logger.error(error_msg)
            raise TypeError(error_msg)

        if key not in self._cache:
            self._miss_count += 1
            logger.debug(f"[VisionCache] 缓存未命中: key={key[:20]}...")
            return None

        value, timestamp = self._cache[key]
        age = time.time() - timestamp

        if age > self.ttl:
            # 过期，删除并返回None
            del self._cache[key]
            self._miss_count += 1
            logger.debug(f"[VisionCache] 缓存过期: key={key[:20]}..., age={age:.0f}s")
            return None

        # 命中，移到队尾（LRU）
        self._cache.move_to_end(key)
        self._hit_count += 1
        logger.debug(f"[VisionCache] 缓存命中: key={key[:20]}..., age={age:.0f}s")
        return value

    def set(self, key: str, value: str) -> None:
        """
        设置缓存
        """
        if not isinstance(key, str):
            error_msg = f"[VisionCache] key类型错误: {type(key)}"
            logger.error(error_msg)
            raise TypeError(error_msg)
        if not isinstance(value, str):
            error_msg = f"[VisionCache] value类型错误: {type(value)}"
            logger.error(error_msg)
            raise TypeError(error_msg)

        # 如果已存在，更新并移到队尾
        if key in self._cache:
            self._cache.move_to_end(key)

        # 如果超过最大大小，淘汰最旧的
        while len(self._cache) >= self.max_size:
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]
            logger.debug(f"[VisionCache] LRU淘汰: key={oldest_key[:20]}...")

        self._cache[key] = (value, time.time())
        logger.debug(f"[VisionCache] 缓存已设置: key={key[:20]}...")

    def get_stats(self) -> dict[str, int]:
        """获取缓存统计"""
        total = self._hit_count + self._miss_count
        hit_rate = self._hit_count / total if total > 0 else 0
        return {
            "size": len(self._cache),
            "max_size": self.max_size,
            "hits": self._hit_count,
            "misses": self._miss_count,
            "hit_rate": round(hit_rate, 3)
        }

    def clear(self) -> None:
        """清空缓存"""
        self._cache.clear()
        logger.info("[VisionCache] 缓存已清空")


# 全局缓存实例
_vision_cache: VisionCache | None = None

def get_vision_cache() -> VisionCache:
    """获取全局缓存实例"""
    global _vision_cache
    if _vision_cache is None:
        from core.config import config
        max_size = config.get("vision.cache.max_size", 10)
        ttl = config.get("vision.cache.ttl", 300)
        _vision_cache = VisionCache(max_size=max_size, ttl=ttl)
        logger.info(f"[VisionCache] 初始化: max_size={max_size}, ttl={ttl}")
    return _vision_cache
