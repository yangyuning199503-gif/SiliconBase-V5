#!/usr/bin/env python3
"""
搜索缓存管理模块
提供搜索结果的缓存功能，按内容类型设置不同的缓存时间
"""
import hashlib
import json
import os
import time
from dataclasses import dataclass
from typing import Any

from core.logger import logger


@dataclass
class CacheEntry:
    """缓存条目"""
    query: str                    # 搜索关键词
    results: dict[str, Any]       # 搜索结果
    created_at: float             # 创建时间戳
    expires_at: float             # 过期时间戳
    content_type: str             # 内容类型 (weather, news, knowledge, etc.)
    hit_count: int = 0            # 命中次数

    def is_expired(self) -> bool:
        """检查是否过期"""
        return time.time() > self.expires_at

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "query": self.query,
            "results": self.results,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "content_type": self.content_type,
            "hit_count": self.hit_count
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CacheEntry":
        """从字典创建"""
        return cls(
            query=data["query"],
            results=data["results"],
            created_at=data["created_at"],
            expires_at=data["expires_at"],
            content_type=data.get("content_type", "general"),
            hit_count=data.get("hit_count", 0)
        )


class SearchCache:
    """
    搜索缓存管理器

    支持:
    - 内存缓存 (快速访问)
    - 磁盘缓存 (持久化)
    - 按内容类型设置TTL
    - 缓存统计
    """

    # 默认TTL配置 (秒)
    DEFAULT_TTL = {
        "weather": 300,        # 5分钟 - 天气实时变化
        "stock": 60,           # 1分钟 - 股价高实时性
        "news": 3600,          # 1小时 - 新闻半实时
        "knowledge": 86400,    # 24小时 - 百科知识相对稳定
        "general": 1800,       # 30分钟 - 默认
    }

    # 最大缓存条目数
    MAX_MEMORY_ENTRIES = 100

    def __init__(self, cache_dir: str = None):
        """
        初始化缓存管理器

        Args:
            cache_dir: 磁盘缓存目录，默认使用项目目录下的 cache/search
        """
        self._memory_cache: dict[str, CacheEntry] = {}

        # 设置缓存目录
        if cache_dir is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            cache_dir = os.path.join(base_dir, "cache", "search")

        self._cache_dir = cache_dir
        os.makedirs(self._cache_dir, exist_ok=True)

        # 统计信息
        self._stats = {
            "memory_hits": 0,
            "disk_hits": 0,
            "misses": 0,
            "saves": 0,
            "evictions": 0
        }

        # 加载磁盘缓存
        self._load_disk_cache()

        logger.info(f"[SearchCache] 初始化完成，缓存目录: {self._cache_dir}")

    def _get_cache_key(self, query: str, **kwargs) -> str:
        """
        生成缓存键

        Args:
            query: 搜索关键词
            **kwargs: 其他影响结果的参数

        Returns:
            缓存键字符串
        """
        # 组合查询和参数
        key_data = {
            "query": query.lower().strip(),
            "params": kwargs
        }
        key_str = json.dumps(key_data, sort_keys=True)
        return hashlib.md5(key_str.encode()).hexdigest()

    def _get_cache_file(self, key: str) -> str:
        """获取缓存文件路径"""
        return os.path.join(self._cache_dir, f"{key}.json")

    def _detect_content_type(self, query: str) -> str:
        """
        检测查询内容类型

        Args:
            query: 搜索关键词

        Returns:
            内容类型字符串
        """
        query_lower = query.lower()

        # 天气相关
        weather_keywords = ["天气", "气温", "温度", "下雨", "晴天", "forecast", "weather"]
        if any(kw in query_lower for kw in weather_keywords):
            return "weather"

        # 股价相关
        stock_keywords = ["股价", "股票", "行情", "stock", "price", "涨跌幅"]
        if any(kw in query_lower for kw in stock_keywords):
            return "stock"

        # 新闻相关
        news_keywords = ["新闻", "最新", "报道", "news", "latest"]
        if any(kw in query_lower for kw in news_keywords):
            return "news"

        # 百科/知识
        knowledge_keywords = ["是什么", "为什么", "怎么样", "wiki", "百科"]
        if any(kw in query_lower for kw in knowledge_keywords):
            return "knowledge"

        return "general"

    def get(self, query: str, **kwargs) -> dict[str, Any] | None:
        """
        获取缓存的搜索结果

        Args:
            query: 搜索关键词
            **kwargs: 影响结果的参数

        Returns:
            缓存的结果，不存在或已过期返回 None
        """
        key = self._get_cache_key(query, **kwargs)

        # 1. 检查内存缓存
        if key in self._memory_cache:
            entry = self._memory_cache[key]
            if not entry.is_expired():
                entry.hit_count += 1
                self._stats["memory_hits"] += 1
                logger.debug(f"[SearchCache] 内存缓存命中: {query[:30]}...")
                return entry.results
            else:
                # 过期，从内存移除
                del self._memory_cache[key]

        # 2. 检查磁盘缓存
        cache_file = self._get_cache_file(key)
        if os.path.exists(cache_file):
            try:
                with open(cache_file, encoding='utf-8') as f:
                    entry = CacheEntry.from_dict(json.load(f))

                if not entry.is_expired():
                    # 加载到内存
                    self._memory_cache[key] = entry
                    entry.hit_count += 1
                    self._stats["disk_hits"] += 1
                    logger.debug(f"[SearchCache] 磁盘缓存命中: {query[:30]}...")
                    return entry.results
                else:
                    # 过期，删除磁盘文件
                    os.remove(cache_file)
            except Exception as e:
                logger.warning(f"[SearchCache] 读取磁盘缓存失败: {e}")

        self._stats["misses"] += 1
        return None

    def set(self, query: str, results: dict[str, Any],
            content_type: str = None, ttl: int = None, **kwargs):
        """
        设置缓存

        Args:
            query: 搜索关键词
            results: 搜索结果
            content_type: 内容类型，自动检测
            ttl: 自定义TTL(秒)，默认按内容类型
            **kwargs: 影响结果的参数
        """
        key = self._get_cache_key(query, **kwargs)

        # 检测内容类型
        if content_type is None:
            content_type = self._detect_content_type(query)

        # 确定TTL
        if ttl is None:
            ttl = self.DEFAULT_TTL.get(content_type, self.DEFAULT_TTL["general"])

        now = time.time()
        entry = CacheEntry(
            query=query,
            results=results,
            created_at=now,
            expires_at=now + ttl,
            content_type=content_type
        )

        # 保存到内存
        self._memory_cache[key] = entry

        # 检查内存缓存大小，如果超过限制，移除最旧的
        if len(self._memory_cache) > self.MAX_MEMORY_ENTRIES:
            self._evict_oldest()

        # 保存到磁盘
        try:
            cache_file = self._get_cache_file(key)
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(entry.to_dict(), f, ensure_ascii=False, indent=2)
            self._stats["saves"] += 1
        except Exception as e:
            logger.warning(f"[SearchCache] 保存磁盘缓存失败: {e}")

        logger.debug(f"[SearchCache] 缓存已设置: {query[:30]}... (类型: {content_type}, TTL: {ttl}s)")

    def _evict_oldest(self):
        """移除最旧的缓存条目"""
        if not self._memory_cache:
            return

        # 找到最少使用的条目
        oldest_key = min(
            self._memory_cache.keys(),
            key=lambda k: self._memory_cache[k].hit_count
        )

        del self._memory_cache[oldest_key]
        self._stats["evictions"] += 1
        logger.debug(f"[SearchCache] 内存缓存淘汰: {oldest_key}")

    def _load_disk_cache(self):
        """加载磁盘缓存到内存"""
        if not os.path.exists(self._cache_dir):
            return

        loaded = 0
        for filename in os.listdir(self._cache_dir):
            if not filename.endswith('.json'):
                continue

            filepath = os.path.join(self._cache_dir, filename)
            try:
                with open(filepath, encoding='utf-8') as f:
                    entry = CacheEntry.from_dict(json.load(f))

                # 只加载未过期的
                if not entry.is_expired():
                    key = filename[:-5]  # 去掉 .json
                    self._memory_cache[key] = entry
                    loaded += 1
                else:
                    # 删除过期文件
                    os.remove(filepath)
            except Exception as e:
                logger.warning(f"[SearchCache] 加载缓存文件失败 {filename}: {e}")

        if loaded > 0:
            logger.info(f"[SearchCache] 从磁盘加载 {loaded} 条缓存")

    def clear(self, content_type: str = None):
        """
        清除缓存

        Args:
            content_type: 指定内容类型清除，None表示全部
        """
        if content_type:
            # 清除指定类型
            keys_to_remove = [
                k for k, v in self._memory_cache.items()
                if v.content_type == content_type
            ]
            for key in keys_to_remove:
                del self._memory_cache[key]
                cache_file = self._get_cache_file(key)
                if os.path.exists(cache_file):
                    os.remove(cache_file)
            logger.info(f"[SearchCache] 清除 {content_type} 类型缓存: {len(keys_to_remove)} 条")
        else:
            # 清除全部
            self._memory_cache.clear()
            for filename in os.listdir(self._cache_dir):
                if filename.endswith('.json'):
                    os.remove(os.path.join(self._cache_dir, filename))
            logger.info("[SearchCache] 清除全部缓存")

    def get_stats(self) -> dict[str, Any]:
        """获取缓存统计信息"""
        total_hits = self._stats["memory_hits"] + self._stats["disk_hits"]
        total_requests = total_hits + self._stats["misses"]

        hit_rate = total_hits / total_requests if total_requests > 0 else 0

        # 统计各类型缓存数量
        type_counts = {}
        for entry in self._memory_cache.values():
            type_counts[entry.content_type] = type_counts.get(entry.content_type, 0) + 1

        return {
            "memory_entries": len(self._memory_cache),
            "memory_hits": self._stats["memory_hits"],
            "disk_hits": self._stats["disk_hits"],
            "total_hits": total_hits,
            "misses": self._stats["misses"],
            "hit_rate": f"{hit_rate:.2%}",
            "saves": self._stats["saves"],
            "evictions": self._stats["evictions"],
            "type_distribution": type_counts
        }

    def cleanup_expired(self):
        """清理过期缓存"""
        expired_keys = [
            k for k, v in self._memory_cache.items()
            if v.is_expired()
        ]

        for key in expired_keys:
            del self._memory_cache[key]
            cache_file = self._get_cache_file(key)
            if os.path.exists(cache_file):
                os.remove(cache_file)

        if expired_keys:
            logger.info(f"[SearchCache] 清理过期缓存: {len(expired_keys)} 条")

        return len(expired_keys)


# 全局缓存实例
_search_cache: SearchCache | None = None


def get_search_cache() -> SearchCache:
    """获取全局搜索缓存实例"""
    global _search_cache
    if _search_cache is None:
        _search_cache = SearchCache()
    return _search_cache


def init_search_cache(cache_dir: str = None) -> SearchCache:
    """初始化搜索缓存"""
    global _search_cache
    _search_cache = SearchCache(cache_dir)
    return _search_cache
