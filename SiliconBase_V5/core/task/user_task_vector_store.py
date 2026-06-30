#!/usr/bin/env python3
"""
任务向量存储层 - 支持语义压缩的任务摘要管理（VectorStore 重写版）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【功能设计】
  基于 VectorStore 异步接口实现任务语义存储，
  不再依赖旧 vector_memory.py 的任何内部属性。

【核心能力】
  1. 添加/更新/删除任务摘要
  2. 语义搜索相似任务
  3. 以任务找相似任务
  4. 批量操作支持
  5. 统计信息查询

【2026-05-06】重写：
  - 移除对 VectorMemoryManager / UserVectorStore 的直接依赖
  - 全部方法改为 async，内部通过 get_memory_service() → VectorStore 执行
"""

import time
from dataclasses import dataclass
from typing import Any

from core.logger import logger

# ═════════════════════════════════════════════════════════════════════════════
# 兼容性 SearchResult
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class SearchResult:
    """搜索结果——与旧接口格式兼容"""
    id: str
    document: str
    metadata: dict
    similarity: float = 0.0


# ═════════════════════════════════════════════════════════════════════════════
# 用户任务向量存储类
# ═════════════════════════════════════════════════════════════════════════════

class UserTaskVectorStore:
    """
    任务向量存储 - 基于 VectorStore 异步接口
    """

    COLLECTION_NAME = "task_summaries"
    VALID_STATUSES = ["pending", "completed", "failed", "cancelled"]

    def __init__(self, user_id: str):
        self.user_id = user_id

    def _generate_id(self, task_id: str) -> str:
        return f"task_summary_{self.user_id}_{task_id}"

    async def is_available(self) -> bool:
        """检查任务向量存储是否可用"""
        try:
            from core.memory.memory_service import get_memory_service
            ms = await get_memory_service()
            return await ms.vector_store.is_available()
        except Exception:
            return False

    async def add_task_summary(
        self,
        task_id: str,
        summary: str,
        metadata: dict | None = None
    ) -> bool:
        if not task_id or not summary:
            return False

        try:
            from core.memory.memory_service import get_memory_service
            ms = await get_memory_service()
            vs = ms.vector_store

            self._generate_id(task_id)
            doc_metadata = {
                "task_id": task_id,
                "user_id": self.user_id,
                "timestamp": str(time.time()),
                **(metadata or {})
            }
            if "status" not in doc_metadata:
                doc_metadata["status"] = "pending"
            if "compressed_at" not in doc_metadata:
                doc_metadata["compressed_at"] = str(time.time())
            if "version" not in doc_metadata:
                doc_metadata["version"] = "1.0"

            await vs.add(self.COLLECTION_NAME, summary, doc_metadata)
            return True
        except Exception as e:
            logger.warning(f"[UserTaskVectorStore] add_task_summary 失败: {e}")
            return False

    async def update_task_summary(
        self,
        task_id: str,
        summary: str,
        metadata: dict | None = None
    ) -> bool:
        if not task_id or not summary:
            return False

        try:
            from core.memory.memory_service import get_memory_service
            ms = await get_memory_service()
            vs = ms.vector_store

            doc_id = self._generate_id(task_id)
            existing = await self.get_task_summary(task_id)

            doc_metadata = {
                "task_id": task_id,
                "user_id": self.user_id,
                "timestamp": str(time.time()),
                "updated_at": str(time.time()),
                **(metadata or {})
            }

            if existing and "version" in existing.get("metadata", {}):
                try:
                    current = float(existing["metadata"]["version"])
                    doc_metadata["version"] = str(current + 0.1)
                except (ValueError, TypeError):
                    doc_metadata["version"] = "1.0"
            else:
                doc_metadata["version"] = doc_metadata.get("version", "1.0")

            if "compressed_at" not in doc_metadata:
                doc_metadata["compressed_at"] = str(time.time())

            await vs.upsert(self.COLLECTION_NAME, doc_id, summary, doc_metadata)
            return True
        except Exception as e:
            logger.warning(f"[UserTaskVectorStore] update_task_summary 失败: {e}")
            return False

    async def delete_task_summary(self, task_id: str) -> bool:
        if not task_id:
            return False

        try:
            from core.memory.memory_service import get_memory_service
            ms = await get_memory_service()
            vs = ms.vector_store

            doc_id = self._generate_id(task_id)
            return await vs.delete(self.COLLECTION_NAME, [doc_id])
        except Exception as e:
            logger.warning(f"[UserTaskVectorStore] delete_task_summary 失败: {e}")
            return False

    async def get_task_summary(self, task_id: str) -> dict | None:
        if not task_id:
            return None

        try:
            from core.memory.memory_service import get_memory_service
            ms = await get_memory_service()
            vs = ms.vector_store

            doc_id = self._generate_id(task_id)
            results = await vs.get(self.COLLECTION_NAME, [doc_id])

            if results:
                return results[0]
            return None
        except Exception as e:
            logger.warning(f"[UserTaskVectorStore] get_task_summary 失败: {e}")
            return None

    async def search_similar_tasks(
        self,
        query: str,
        n_results: int = 5,
        filter_dict: dict | None = None
    ) -> list[SearchResult]:
        if not query:
            return []

        try:
            from core.memory.memory_service import get_memory_service
            ms = await get_memory_service()
            vs = ms.vector_store

            raw_results = await vs.search(
                self.COLLECTION_NAME,
                query,
                limit=n_results
            )

            search_results = []
            for r in raw_results:
                similarity = 1.0 - (r.distance or 0.0)
                search_results.append(SearchResult(
                    id=r.id,
                    document=r.document,
                    metadata=r.metadata or {},
                    similarity=similarity
                ))

            # 客户端过滤（VectorStore 当前不支持 arbitrary where 过滤）
            if filter_dict:
                for key, value in filter_dict.items():
                    search_results = [
                        r for r in search_results
                        if r.metadata.get(key) == value
                    ]

            return search_results
        except Exception as e:
            logger.warning(f"[UserTaskVectorStore] search_similar_tasks 失败: {e}")
            return []

    async def search_by_task(
        self,
        task_id: str,
        n_results: int = 5
    ) -> list[SearchResult]:
        if not task_id:
            return []

        task_data = await self.get_task_summary(task_id)
        if not task_data or not task_data.get("document"):
            return []

        all_results = await self.search_similar_tasks(
            query=task_data["document"],
            n_results=n_results + 1
        )

        query_doc_id = self._generate_id(task_id)
        filtered = [r for r in all_results if r.id != query_doc_id]
        return filtered[:n_results]

    async def get_collection_stats(self) -> dict:
        stats = {
            "user_id": self.user_id,
            "available": await self.is_available(),
            "total_count": 0,
            "collection_name": self.COLLECTION_NAME
        }
        try:
            from core.memory.memory_service import get_memory_service
            ms = await get_memory_service()
            vs = ms.vector_store
            stats["total_count"] = await vs.count(self.COLLECTION_NAME)
        except Exception as e:
            stats["error"] = str(e)
        return stats

    async def batch_add_summaries(
        self,
        items: list[dict[str, Any]]
    ) -> bool:
        if not items:
            return True

        try:
            from core.memory.memory_service import get_memory_service
            ms = await get_memory_service()
            vs = ms.vector_store

            current_time = str(time.time())
            texts = []
            metadatas = []

            for item in items:
                task_id = item.get("task_id")
                summary = item.get("summary")
                meta = item.get("metadata", {})
                if not task_id or not summary:
                    continue

                doc_metadata = {
                    "task_id": task_id,
                    "user_id": self.user_id,
                    "timestamp": current_time,
                    **meta
                }
                if "status" not in doc_metadata:
                    doc_metadata["status"] = "pending"
                if "compressed_at" not in doc_metadata:
                    doc_metadata["compressed_at"] = current_time
                if "version" not in doc_metadata:
                    doc_metadata["version"] = "1.0"

                texts.append(summary)
                metadatas.append(doc_metadata)

            if not texts:
                return True

            await vs.add_batch(self.COLLECTION_NAME, texts, metadatas)
            return True
        except Exception as e:
            logger.warning(f"[UserTaskVectorStore] batch_add_summaries 失败: {e}")
            return False

    async def batch_delete_summaries(self, task_ids: list[str]) -> bool:
        if not task_ids:
            return True

        try:
            from core.memory.memory_service import get_memory_service
            ms = await get_memory_service()
            vs = ms.vector_store

            doc_ids = [self._generate_id(tid) for tid in task_ids if tid]
            return await vs.delete(self.COLLECTION_NAME, doc_ids)
        except Exception as e:
            logger.warning(f"[UserTaskVectorStore] batch_delete_summaries 失败: {e}")
            return False

    async def get_all_task_ids(self) -> list[str]:
        try:
            from core.memory.memory_service import get_memory_service
            ms = await get_memory_service()
            vs = ms.vector_store

            records = await vs.get_all(self.COLLECTION_NAME)
            task_ids = []
            for rec in records:
                meta = rec.get("metadata", {})
                if "task_id" in meta:
                    task_ids.append(meta["task_id"])
            return task_ids
        except Exception as e:
            logger.warning(f"[UserTaskVectorStore] get_all_task_ids 失败: {e}")
            return []

    async def get_tasks_by_status(self, status: str) -> list[dict]:
        if status not in self.VALID_STATUSES:
            return []

        try:
            records = await self._get_all_records()
            tasks = []
            for rec in records:
                meta = rec.get("metadata", {})
                if meta.get("status") == status:
                    tasks.append({
                        "id": rec.get("id"),
                        "document": rec.get("document", ""),
                        "metadata": meta
                    })
            return tasks
        except Exception as e:
            logger.warning(f"[UserTaskVectorStore] get_tasks_by_status 失败: {e}")
            return []

    async def _get_all_records(self) -> list[dict]:
        """内部辅助：获取集合所有记录"""
        from core.memory.memory_service import get_memory_service
        ms = await get_memory_service()
        vs = ms.vector_store
        return await vs.get_all(self.COLLECTION_NAME)


# ═════════════════════════════════════════════════════════════════════════════
# 便捷函数
# ═════════════════════════════════════════════════════════════════════════════

def get_user_task_vector_store(user_id: str) -> UserTaskVectorStore:
    return UserTaskVectorStore(user_id)


# ═════════════════════════════════════════════════════════════════════════════
# 全局管理器
# ═════════════════════════════════════════════════════════════════════════════

class TaskVectorStoreManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._stores: dict[str, UserTaskVectorStore] = {}

    def get_store(self, user_id: str) -> UserTaskVectorStore:
        if user_id not in self._stores:
            self._stores[user_id] = UserTaskVectorStore(user_id)
        return self._stores[user_id]

    async def add_task_summary(
        self,
        user_id: str,
        task_id: str,
        summary: str,
        metadata: dict | None = None
    ) -> bool:
        store = self.get_store(user_id)
        return await store.add_task_summary(task_id, summary, metadata)

    async def search_similar_tasks(
        self,
        user_id: str,
        query: str,
        n_results: int = 5,
        filter_dict: dict | None = None
    ) -> list[SearchResult]:
        store = self.get_store(user_id)
        return await store.search_similar_tasks(query, n_results, filter_dict)

    async def get_stats(self, user_id: str | None = None) -> dict:
        if user_id:
            store = self.get_store(user_id)
            return await store.get_collection_stats()

        all_stats = {"total_users": len(self._stores), "users": {}}
        for uid, store in self._stores.items():
            all_stats["users"][uid] = await store.get_collection_stats()
        return all_stats

    def close_all(self):
        self._stores.clear()


# ═════════════════════════════════════════════════════════════════════════════
# 全局实例
# ═════════════════════════════════════════════════════════════════════════════

task_vector_store_manager = None

try:
    task_vector_store_manager = TaskVectorStoreManager()
    print("【成功】 Task vector store system (VectorStore版) initialized successfully")
except Exception as e:
    print(f"[ERROR] Failed to initialize task vector store: {e}")
    task_vector_store_manager = None
