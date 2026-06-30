#!/usr/bin/env python3
"""
vector_memory 兼容层（Thin Wrapper）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
职责：为“可批量替换”的旧调用方提供与 vector_memory 完全一致的同步接口，
      内部通过 MemoryService 桥接到 VectorStore。

设计约束：
  - 零业务逻辑，只做格式转换 + sync/async 桥接
  - 异常时降级返回空结果，不抛异常（保持与旧 vector_memory 相同的容错风格）
  - 线程安全：支持在有/无 running loop 的线程中被调用
"""

from typing import Any

from core.logger import logger


async def _get_vector_store():
    """通过 MemoryService 获取 VectorStore"""
    from core.memory.memory_service import get_memory_service
    ms = await get_memory_service()
    return ms.vector_store


def _results_to_old_format(results):
    """将 VectorStore SearchResult 列表转为旧 vector_memory 的字典格式"""
    old_results = []
    for r in results:
        old_results.append({
            "id": r.id,
            "document": r.document,
            "content": r.document,  # 别名，兼容访问 "content" 的调用方
            "metadata": r.metadata,
            "similarity": 1.0 - (r.distance or 0.0),
        })
    return old_results


class _VectorMemoryCompat:
    """与旧 vector_memory 全局实例接口完全一致的兼容对象"""

    async def search_knowledge(self, query: str, user_id: str | None = None, limit: int = 5) -> list[dict[str, Any]]:
        """兼容旧接口：搜索知识集合"""
        try:
            vs = await _get_vector_store()
            if not await vs.is_available():
                return []
            results = await vs.search("knowledge", query, limit=limit)
            return _results_to_old_format(results)
        except Exception as e:
            logger.debug(f"[VectorMemoryCompat] search_knowledge 降级: {e}")
            return []

    async def search_experience(
        self,
        task_desc: str,
        user_id: str | None = None,
        only_success: bool = True,
        limit: int = 3
    ) -> list[dict[str, Any]]:
        """兼容旧接口：搜索经验集合"""
        try:
            vs = await _get_vector_store()
            if not await vs.is_available():
                return []
            # 同时搜索 experience 和 knowledge，合并后过滤
            grouped = await vs.search_multi(
                query=task_desc,
                collections=["experience", "knowledge"],
                n_results=limit
            )
            merged = []
            for coll, results in grouped.items():
                for r in results:
                    merged.append({
                        "id": r.id,
                        "document": r.document,
                        "content": r.document,
                        "metadata": {**r.metadata, "collection": coll},
                        "similarity": 1.0 - (r.distance or 0.0),
                    })
            # 按 similarity 降序排序
            merged.sort(key=lambda x: x["similarity"], reverse=True)
            # 若 only_success=True，过滤 metadata.success 标记
            if only_success:
                merged = [m for m in merged if m.get("metadata", {}).get("success") in (True, "true", "True")]
            return merged[:limit]
        except Exception as e:
            logger.debug(f"[VectorMemoryCompat] search_experience 降级: {e}")
            return []

    async def search_best_experience(self, task_desc: str, limit: int = 1) -> list[dict[str, Any]]:
        """兼容旧接口：搜索最佳经验"""
        return await self.search_experience(task_desc, only_success=True, limit=limit)

    async def search_similar(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """兼容旧接口：语义相似搜索（搜索 knowledge + experience）"""
        try:
            vs = await _get_vector_store()
            if not await vs.is_available():
                return []
            grouped = await vs.search_multi(
                query=query,
                collections=["knowledge", "experience"],
                n_results=top_k
            )
            merged = []
            for _coll, results in grouped.items():
                for r in results:
                    merged.append({
                        "id": r.id,
                        "document": r.document,
                        "content": r.document,
                        "metadata": r.metadata,
                        "similarity": 1.0 - (r.distance or 0.0),
                    })
            merged.sort(key=lambda x: x["similarity"], reverse=True)
            return merged[:top_k]
        except Exception as e:
            logger.debug(f"[VectorMemoryCompat] search_similar 降级: {e}")
            return []

    async def search_voice_correction(self, wrong_text: str) -> str | None:
        """兼容旧接口：搜索语音纠错"""
        try:
            vs = await _get_vector_store()
            if not await vs.is_available():
                return None
            results = await vs.search("voice_fix", wrong_text, limit=1)
            if results:
                return results[0].document
            return None
        except Exception as e:
            logger.debug(f"[VectorMemoryCompat] search_voice_correction 降级: {e}")
            return None

    async def get_stats(self, user_id: str | None = None) -> dict[str, Any]:
        """兼容旧接口：获取统计信息"""
        try:
            vs = await _get_vector_store()
            if not await vs.is_available():
                return {}
            raw = await vs.get_stats()
            # 扁平化统计：按 collection 聚合 count
            collections = raw.get("collections", {})
            sum(
                c.get("count", 0) for name, c in collections.items()
                if name in ("experience", "knowledge")
            )
            return {
                "total_users": 1,
                "experience_count": collections.get("experience", {}).get("count", 0),
                "knowledge_count": collections.get("knowledge", {}).get("count", 0),
                "total_memories": sum(c.get("count", 0) for c in collections.values() if isinstance(c, dict)),
                "collections": {name: info.get("count", 0) for name, info in collections.items()},
            }
        except Exception as e:
            logger.debug(f"[VectorMemoryCompat] get_stats 降级: {e}")
            return {}


# 全局兼容实例（与旧 vector_memory 导出方式一致）
vector_memory = _VectorMemoryCompat()
