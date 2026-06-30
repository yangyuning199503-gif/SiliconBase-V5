#!/usr/bin/env python3
"""
向量索引优化模块 V1.0 - HNSW加速检索
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【功能特性】
  ✓ HNSW索引配置优化
  ✓ 向量搜索参数调优
  ✓ 多线程并行搜索
  ✓ 搜索结果重排序
  ✓ 索引预热机制

【性能目标】
  - 向量搜索延迟: <50ms (10万条)
  - 索引构建时间: <5分钟 (10万条)
  - 召回率: >95%

【作者】Agent-10: 性能优化工程师
【日期】2026-03-06
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

import numpy as np

from core.memory.memory_schema import MemoryFilter
from core.memory.memory_service import get_memory_service

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# 配置常量
# ═══════════════════════════════════════════════════════════════════

# HNSW索引参数
HNSW_M = 16                    # 每个节点的最大连接数
HNSW_EF_CONSTRUCTION = 200     # 构建时的搜索深度
HNSW_EF_SEARCH = 128           # 搜索时的搜索深度

# 搜索参数
DEFAULT_TOP_K = 10             # 默认返回结果数
MAX_TOP_K = 100                # 最大返回结果数
SEARCH_TIMEOUT = 5.0           # 搜索超时(秒)

# 并行搜索参数
PARALLEL_SEARCH_WORKERS = 4    # 并行搜索工作线程
BATCH_SEARCH_SIZE = 10         # 批量搜索大小


@dataclass
class SearchConfig:
    """搜索配置"""
    top_k: int = DEFAULT_TOP_K
    ef_search: int = HNSW_EF_SEARCH
    nprobe: int = 10             # IVF索引的聚类搜索数
    rerank: bool = True          # 是否重排序
    timeout: float = SEARCH_TIMEOUT


@dataclass
class VectorSearchResult:
    """向量搜索结果"""
    id: str
    score: float                 # 相似度分数
    vector: np.ndarray | None = None
    metadata: dict | None = None


# ═══════════════════════════════════════════════════════════════════
# HNSW索引管理器
# ═══════════════════════════════════════════════════════════════════

class HNSWIndexManager:
    """
    HNSW索引管理器

    管理HNSW索引的配置和优化，提供高性能向量搜索。
    注: 实际HNSW索引由ChromaDB底层管理，此类提供参数优化和搜索优化。
    """

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

        # 索引缓存
        self._index_cache: dict[str, Any] = {}
        self._cache_lock = threading.RLock()

        # 搜索配置
        self._search_config = SearchConfig()

        # 线程池
        self._executor = ThreadPoolExecutor(max_workers=PARALLEL_SEARCH_WORKERS)

        logger.info("[HNSWIndexManager] 初始化完成")

    def get_optimal_hnsw_params(self, collection_size: int) -> dict[str, int]:
        """
        获取最优HNSW参数

        根据集合大小动态调整HNSW参数。

        Args:
            collection_size: 集合大小

        Returns:
            Dict: HNSW参数
        """
        # 根据集合大小调整参数
        if collection_size < 1000:
            return {
                "M": 8,
                "efConstruction": 64,
                "efSearch": 32
            }
        elif collection_size < 10000:
            return {
                "M": 12,
                "efConstruction": 100,
                "efSearch": 64
            }
        elif collection_size < 100000:
            return {
                "M": 16,
                "efConstruction": 200,
                "efSearch": 128
            }
        else:
            return {
                "M": 24,
                "efConstruction": 300,
                "efSearch": 200
            }

    def optimize_search(
        self,
        query_vector: np.ndarray,
        index: Any,
        config: SearchConfig | None = None
    ) -> list[VectorSearchResult]:
        """
        优化的向量搜索

        Args:
            query_vector: 查询向量
            index: 向量索引
            config: 搜索配置

        Returns:
            List[VectorSearchResult]: 搜索结果
        """
        config = config or self._search_config

        start_time = time.time()

        # 执行搜索
        results = self._do_search(query_vector, index, config)

        # 重排序优化
        if config.rerank and len(results) > config.top_k:
            results = self._rerank_results(query_vector, results, config.top_k)

        duration = (time.time() - start_time) * 1000

        if duration > 100:
            logger.warning(f"[HNSW] 慢查询: {duration:.2f}ms")

        return results

    def _do_search(
        self,
        query_vector: np.ndarray,
        index: Any,
        config: SearchConfig
    ) -> list[VectorSearchResult]:
        """
        执行搜索

        Args:
            query_vector: 查询向量
            index: 向量索引
            config: 搜索配置

        Returns:
            List[VectorSearchResult]: 搜索结果
        """
        # 这里使用ChromaDB的搜索接口
        # 实际实现依赖于ChromaDB的内部机制

        results = []

        try:
            # 尝试使用ChromaDB的query方法
            if hasattr(index, 'query'):
                chroma_results = index.query(
                    query_embeddings=[query_vector.tolist()],
                    n_results=min(config.top_k * 2, MAX_TOP_K),  # 获取更多用于重排序
                    include=['distances', 'metadatas', 'embeddings']
                )

                if chroma_results and chroma_results.get('ids'):
                    for i, mem_id in enumerate(chroma_results['ids'][0]):
                        distance = chroma_results['distances'][0][i] if chroma_results.get('distances') else 1.0
                        # 距离转相似度
                        score = 1 - distance

                        metadata = None
                        if chroma_results.get('metadatas') and chroma_results['metadatas'][0]:
                            metadata = chroma_results['metadatas'][0][i]

                        vector = None
                        if chroma_results.get('embeddings') and chroma_results['embeddings'][0]:
                            vector = np.array(chroma_results['embeddings'][0][i])

                        results.append(VectorSearchResult(
                            id=mem_id,
                            score=score,
                            vector=vector,
                            metadata=metadata
                        ))

        except Exception as e:
            logger.error(f"[HNSW] 搜索失败: {e}")

        return results

    def _rerank_results(
        self,
        query_vector: np.ndarray,
        results: list[VectorSearchResult],
        top_k: int
    ) -> list[VectorSearchResult]:
        """
        重排序结果

        使用精确相似度计算对初步搜索结果进行重排序。

        Args:
            query_vector: 查询向量
            results: 初步搜索结果
            top_k: 返回数量

        Returns:
            List[VectorSearchResult]: 重排序后的结果
        """
        # 计算精确相似度
        scored_results = []

        for result in results:
            if result.vector is not None:
                # 使用余弦相似度
                similarity = self._cosine_similarity(query_vector, result.vector)
                result.score = similarity

            scored_results.append(result)

        # 按分数排序
        scored_results.sort(key=lambda x: x.score, reverse=True)

        return scored_results[:top_k]

    def _cosine_similarity(self, v1: np.ndarray, v2: np.ndarray) -> float:
        """计算余弦相似度"""
        norm1 = np.linalg.norm(v1)
        norm2 = np.linalg.norm(v2)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return float(np.dot(v1, v2) / (norm1 * norm2))

    def parallel_search(
        self,
        query_vectors: list[np.ndarray],
        index: Any,
        config: SearchConfig | None = None
    ) -> list[list[VectorSearchResult]]:
        """
        并行搜索多个查询

        Args:
            query_vectors: 查询向量列表
            index: 向量索引
            config: 搜索配置

        Returns:
            List[List[VectorSearchResult]]: 每组查询的结果
        """
        config = config or self._search_config

        # 提交并行任务
        futures = []
        for query_vector in query_vectors:
            future = self._executor.submit(
                self.optimize_search,
                query_vector,
                index,
                config
            )
            futures.append(future)

        # 收集结果
        results = []
        for future in as_completed(futures):
            try:
                result = future.result(timeout=config.timeout)
                results.append(result)
            except Exception as e:
                logger.error(f"[HNSW] 并行搜索失败: {e}")
                results.append([])

        return results

    async def warmup_index(self, user_id: str, collection: str):
        """
        预热索引

        通过执行虚拟查询预热索引，提高后续查询性能。

        Args:
            user_id: 用户ID
            collection: 集合名称
        """
        try:
            ms = await get_memory_service()

            if not await ms.vector_store.is_available():
                return

            # 执行虚拟查询预热
            await ms.vector_store.search(collection, "warmup", limit=1)

            logger.debug(f"[HNSW] 索引预热完成: {user_id}/{collection}")

        except Exception as e:
            logger.debug(f"[HNSW] 索引预热失败: {e}")


# ═══════════════════════════════════════════════════════════════════
# 向量搜索优化器
# ═══════════════════════════════════════════════════════════════════

class VectorSearchOptimizer:
    """
    向量搜索优化器

    提供向量搜索的性能优化功能。
    """

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

        self._hnsw_manager = HNSWIndexManager()

        # 搜索统计
        self._search_stats = {
            "total_searches": 0,
            "total_time_ms": 0,
            "slow_searches": 0
        }
        self._stats_lock = threading.Lock()

        logger.info("[VectorSearchOptimizer] 初始化完成")

    async def optimized_search(
        self,
        user_id: str,
        collection: str,
        query: str,
        n_results: int = 10,
        filters: dict | None = None,
        use_rerank: bool = True
    ) -> list[dict]:
        """
        优化的向量搜索

        Args:
            user_id: 用户ID
            collection: 集合名称
            query: 查询文本
            n_results: 返回结果数
            filters: 过滤条件
            use_rerank: 是否使用重排序

        Returns:
            List[Dict]: 搜索结果
        """
        start_time = time.time()

        try:
            ms = await get_memory_service()

            # 预热索引（首次查询）
            await self._hnsw_manager.warmup_index(user_id, collection)

            # 获取更多结果用于重排序
            search_n = n_results * 2 if use_rerank else n_results

            # 转换 filters
            memory_filter = None
            if filters:
                try:
                    memory_filter = MemoryFilter(**filters)
                except Exception:
                    logger.warning(f"[VectorSearchOptimizer] 无法转换 filters: {filters}")

            # 执行搜索
            results = await ms.vector_store.search(
                collection=collection,
                query=query,
                filters=memory_filter,
                limit=min(search_n, MAX_TOP_K)
            )

            # 重排序（如果需要）
            if use_rerank and len(results) > n_results:
                results = self._apply_reranking(results, query, n_results)

            # 更新统计
            duration = (time.time() - start_time) * 1000
            self._update_stats(duration)

            # 转换为字典列表
            return [
                {
                    "id": r.id,
                    "document": r.document,
                    "metadata": r.metadata,
                    "similarity": 1.0 - (r.distance or 0.0)
                }
                for r in results[:n_results]
            ]

        except Exception as e:
            logger.error(f"[VectorSearchOptimizer] 搜索失败: {e}")
            return []

    def _apply_reranking(
        self,
        results: list[Any],
        query: str,
        top_k: int
    ) -> list[Any]:
        """
        应用重排序

        结合向量相似度和文本相关性进行重排序。

        Args:
            results: 初步结果
            query: 查询文本
            top_k: 返回数量

        Returns:
            List: 重排序后的结果
        """
        query_lower = query.lower()
        scored_results = []

        for result in results:
            # 基础分数（向量相似度）
            if hasattr(result, 'similarity'):
                base_score = result.similarity
            elif hasattr(result, 'distance'):
                base_score = 1.0 - (result.distance or 0.0)
            else:
                base_score = 0.5

            # 文本匹配加分
            text_bonus = 0.0
            document = result.document if hasattr(result, 'document') else str(result)
            document_lower = document.lower()

            # 完全匹配
            if query_lower in document_lower:
                text_bonus += 0.1

            # 词匹配
            query_words = set(query_lower.split())
            doc_words = set(document_lower.split())
            common_words = query_words & doc_words
            if query_words:
                text_bonus += len(common_words) / len(query_words) * 0.05

            # 最终分数
            final_score = base_score + text_bonus

            scored_results.append((result, final_score))

        # 排序
        scored_results.sort(key=lambda x: x[1], reverse=True)

        return [r[0] for r in scored_results[:top_k]]

    def _update_stats(self, duration_ms: float):
        """更新搜索统计"""
        with self._stats_lock:
            self._search_stats["total_searches"] += 1
            self._search_stats["total_time_ms"] += duration_ms

            if duration_ms > 100:
                self._search_stats["slow_searches"] += 1

    def get_stats(self) -> dict[str, Any]:
        """获取搜索统计"""
        with self._stats_lock:
            stats = dict(self._search_stats)

            if stats["total_searches"] > 0:
                stats["avg_time_ms"] = stats["total_time_ms"] / stats["total_searches"]
            else:
                stats["avg_time_ms"] = 0

            return stats

    def get_search_config(self) -> SearchConfig:
        """获取搜索配置"""
        return self._hnsw_manager._search_config

    def update_search_config(self, **kwargs):
        """
        更新搜索配置

        Args:
            **kwargs: 配置项
        """
        for key, value in kwargs.items():
            if hasattr(self._hnsw_manager._search_config, key):
                setattr(self._hnsw_manager._search_config, key, value)

        logger.info(f"[VectorSearchOptimizer] 搜索配置已更新: {kwargs}")


# ═══════════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════════

async def optimized_vector_search(
    user_id: str,
    collection: str,
    query: str,
    n_results: int = 10,
    filters: dict | None = None
) -> list[dict]:
    """
    便捷函数: 优化的向量搜索

    Args:
        user_id: 用户ID
        collection: 集合名称
        query: 查询文本
        n_results: 返回结果数
        filters: 过滤条件

    Returns:
        List[Dict]: 搜索结果
    """
    optimizer = VectorSearchOptimizer()
    return await optimizer.optimized_search(user_id, collection, query, n_results, filters)


async def warmup_vector_index(user_id: str, collection: str):
    """
    便捷函数: 预热向量索引

    Args:
        user_id: 用户ID
        collection: 集合名称
    """
    hnsw_manager = HNSWIndexManager()
    await hnsw_manager.warmup_index(user_id, collection)


def get_vector_search_stats() -> dict[str, Any]:
    """获取向量搜索统计"""
    optimizer = VectorSearchOptimizer()
    return optimizer.get_stats()


# ═══════════════════════════════════════════════════════════════════
# 全局实例
# ═══════════════════════════════════════════════════════════════════

hnsw_index_manager = HNSWIndexManager()
vector_search_optimizer = VectorSearchOptimizer()


# ═══════════════════════════════════════════════════════════════════
# 单元测试
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("测试向量索引优化模块...")

    # 测试HNSW参数计算
    manager = HNSWIndexManager()

    for size in [500, 5000, 50000, 500000]:
        params = manager.get_optimal_hnsw_params(size)
        print(f"集合大小 {size}: M={params['M']}, efConstruction={params['efConstruction']}")

    # 测试余弦相似度
    v1 = np.array([1.0, 0.0, 0.0])
    v2 = np.array([0.9, 0.1, 0.0])
    sim = manager._cosine_similarity(v1, v2)
    print(f"余弦相似度: {sim:.4f}")

    print("✓ 测试完成")
