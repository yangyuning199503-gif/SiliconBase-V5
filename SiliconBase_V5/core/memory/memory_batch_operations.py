#!/usr/bin/env python3
"""
记忆批量操作模块 V1.0 - 高性能批量处理
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【功能特性】
  ✓ 批量添加记忆 (事务保证)
  ✓ 批量更新记忆
  ✓ 批量删除记忆 (支持级联删除向量)
  ✓ 异步批量处理
  ✓ 进度回调支持
  ✓ 错误隔离处理

【性能目标】
  - 批量添加100条: <500ms
  - 批量更新100条: <300ms
  - 批量删除100条: <200ms

【作者】Agent-10: 性能优化工程师
【日期】2026-03-06
"""

import atexit
import contextlib
import json
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from typing import Any

from core.db.connection_pool import Json, PostgresConnectionPool
from core.diagnostic import safe_create_task
from core.utils.dependency_utils import rwlock_dep

rwlock = rwlock_dep.get("rwlock") if rwlock_dep.available else rwlock_dep.fallback_class
if rwlock is None:
    rwlock = rwlock_dep.fallback_class
from core.memory.memory_service import get_memory_service

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# 配置常量
# ═══════════════════════════════════════════════════════════════════

DEFAULT_BATCH_SIZE = 100      # 默认批处理大小
MAX_BATCH_SIZE = 1000         # 最大批处理大小
DEFAULT_WORKERS = 4           # 默认工作线程数
ASYNC_BATCH_SIZE = 50         # 异步批处理大小


class BatchOperationStatus(Enum):
    """批量操作状态"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    PARTIAL = "partial"      # 部分成功
    FAILED = "failed"


@dataclass
class BatchResult:
    """批量操作结果"""
    success: bool
    processed: int           # 处理数量
    succeeded: int           # 成功数量
    failed: int              # 失败数量
    errors: list[dict]       # 错误详情
    duration_ms: float       # 耗时(毫秒)
    status: BatchOperationStatus
    data: Any = None         # 返回数据(如ID列表)


@dataclass
class BatchMemoryItem:
    """批量记忆条目"""
    layer: str
    content: dict
    mem_type: str = "general"
    context: dict | None = None
    scene: str = ""
    rating: int = 0
    expire_days: int | None = None
    value_assessment: dict | None = None


# ═══════════════════════════════════════════════════════════════════
# 批量操作管理器
# ═══════════════════════════════════════════════════════════════════

class MemoryBatchOperations:
    """
    记忆批量操作管理器

    提供高性能的批量CRUD操作，支持事务保证和错误隔离。
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

        self._executor = ThreadPoolExecutor(max_workers=DEFAULT_WORKERS)
        self._rw_lock = rwlock.RWLockFair()

        logger.info("[MemoryBatchOperations] 批量操作管理器初始化完成")

    async def batch_add_memories(
        self,
        user_id: str,
        items: list[BatchMemoryItem],
        batch_size: int = DEFAULT_BATCH_SIZE,
        progress_callback: Callable[[int, int], None] | None = None,
        sync_vector: bool = True
    ) -> BatchResult:
        """
        批量添加记忆

        使用事务批量插入，提高性能。

        Args:
            user_id: 用户ID
            items: 记忆条目列表
            batch_size: 每批处理数量
            progress_callback: 进度回调函数(current, total)
            sync_vector: 是否同步到向量库

        Returns:
            BatchResult: 批量操作结果
        """
        start_time = time.time()

        if not items:
            return BatchResult(
                success=True,
                processed=0,
                succeeded=0,
                failed=0,
                errors=[],
                duration_ms=0,
                status=BatchOperationStatus.COMPLETED,
                data=[]
            )

        # 限制批处理大小
        batch_size = min(batch_size, MAX_BATCH_SIZE)

        all_ids = []
        errors = []
        total = len(items)
        processed = 0

        # 分批处理
        for i in range(0, len(items), batch_size):
            batch = items[i:i + batch_size]

            try:
                batch_ids = await self._add_batch_internal(user_id, batch, sync_vector)
                all_ids.extend(batch_ids)
                processed += len(batch)

                if progress_callback:
                    progress_callback(processed, total)

            except Exception as e:
                logger.error(f"[BatchAdd] 批次 {i//batch_size + 1} 失败: {e}")
                errors.append({
                    "batch_index": i // batch_size,
                    "error": str(e),
                    "count": len(batch)
                })
                processed += len(batch)

        duration = (time.time() - start_time) * 1000

        status = BatchOperationStatus.COMPLETED
        if errors:
            status = BatchOperationStatus.PARTIAL if all_ids else BatchOperationStatus.FAILED

        return BatchResult(
            success=len(errors) == 0 or len(all_ids) > 0,
            processed=processed,
            succeeded=len(all_ids),
            failed=processed - len(all_ids),
            errors=errors,
            duration_ms=duration,
            status=status,
            data=all_ids
        )

    async def _add_batch_internal(
        self,
        user_id: str,
        items: list[BatchMemoryItem],
        sync_vector: bool
    ) -> list[str]:
        """
        内部批量添加实现（P1-Asyncify：原生 asyncpg）

        Args:
            user_id: 用户ID
            items: 记忆条目列表
            sync_vector: 是否同步向量

        Returns:
            List[str]: 记忆ID列表
        """
        import uuid
        from datetime import datetime, timedelta

        from core.memory.postgres_pool import AsyncPostgresPool

        mem_ids = []

        try:
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn, conn.transaction():
                for item in items:
                    mem_id = str(uuid.uuid4())
                    mem_ids.append(mem_id)

                    # 计算过期时间
                    expire_at = None
                    if item.expire_days:
                        expire_at = (datetime.now() + timedelta(days=item.expire_days)).strftime("%Y-%m-%d %H:%M:%S")
                    elif item.layer in ('short', 'working'):
                        expire_at = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")

                    # 序列化内容
                    content_str = json.dumps(item.content, ensure_ascii=False)

                    # 六维评分
                    value_assessment = item.value_assessment or {
                        "emotional_temperature": 3,
                        "ethical_safety": 3,
                        "self_growth": 3,
                        "execution_effectiveness": 3,
                        "sustainability": 3,
                        "inspiration_innovation": 3,
                        "overall": 3.0,
                        "grade": "C"
                    }

                    await conn.execute('''
                            INSERT INTO memories
                            (id, user_id, layer, mem_type, content, context,
                             scene, rating, expire_at, value_assessment, creator)
                            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                        ''', (
                        mem_id, user_id, item.layer, item.mem_type, content_str,
                        json.dumps(item.context) if item.context else None,
                        item.scene, item.rating, expire_at,
                        json.dumps(value_assessment), 'batch'
                    ))

            # 向量同步（异步）
            if sync_vector:
                await self._sync_batch_to_vector_async(user_id, items, mem_ids)

            return mem_ids

        except Exception as e:
            raise e

    def batch_update_memories(
        self,
        user_id: str,
        updates: list[tuple[str, dict]],  # [(mem_id, update_dict), ...]
        batch_size: int = DEFAULT_BATCH_SIZE,
        progress_callback: Callable[[int, int], None] | None = None
    ) -> BatchResult:
        """
        批量更新记忆

        Args:
            user_id: 用户ID
            updates: 更新列表 [(记忆ID, 更新字段), ...]
            batch_size: 每批处理数量
            progress_callback: 进度回调

        Returns:
            BatchResult: 批量操作结果
        """
        start_time = time.time()

        if not updates:
            return BatchResult(
                success=True, processed=0, succeeded=0, failed=0,
                errors=[], duration_ms=0, status=BatchOperationStatus.COMPLETED
            )

        batch_size = min(batch_size, MAX_BATCH_SIZE)

        succeeded = 0
        errors = []
        total = len(updates)
        processed = 0

        for i in range(0, len(updates), batch_size):
            batch = updates[i:i + batch_size]

            try:
                batch_succeeded = self._update_batch_internal(user_id, batch)
                succeeded += batch_succeeded
                processed += len(batch)

                if progress_callback:
                    progress_callback(processed, total)

            except Exception as e:
                logger.error(f"[BatchUpdate] 批次失败: {e}")
                errors.append({"batch_index": i // batch_size, "error": str(e)})
                processed += len(batch)

        duration = (time.time() - start_time) * 1000

        status = BatchOperationStatus.COMPLETED
        if errors:
            status = BatchOperationStatus.PARTIAL if succeeded > 0 else BatchOperationStatus.FAILED

        return BatchResult(
            success=len(errors) == 0 or succeeded > 0,
            processed=processed,
            succeeded=succeeded,
            failed=processed - succeeded,
            errors=errors,
            duration_ms=duration,
            status=status
        )

    async def batch_update_memories_async(
        self,
        user_id: str,
        updates: list[tuple[str, dict]],
        batch_size: int = DEFAULT_BATCH_SIZE,
        progress_callback: Callable[[int, int], None] | None = None
    ) -> BatchResult:
        """
        异步批量更新记忆（原生asyncpg）

        Args:
            user_id: 用户ID
            updates: 更新列表 [(记忆ID, 更新字段), ...]
            batch_size: 每批处理数量
            progress_callback: 进度回调

        Returns:
            BatchResult: 批量操作结果
        """
        start_time = time.time()

        if not updates:
            return BatchResult(
                success=True, processed=0, succeeded=0, failed=0,
                errors=[], duration_ms=0, status=BatchOperationStatus.COMPLETED
            )

        batch_size = min(batch_size, MAX_BATCH_SIZE)

        succeeded = 0
        errors = []
        total = len(updates)
        processed = 0

        for i in range(0, len(updates), batch_size):
            batch = updates[i:i + batch_size]

            try:
                batch_succeeded = await self._update_batch_internal_async(user_id, batch)
                succeeded += batch_succeeded
                processed += len(batch)

                if progress_callback:
                    progress_callback(processed, total)

            except Exception as e:
                logger.error(f"[BatchUpdate] 异步批次失败: {e}")
                errors.append({"batch_index": i // batch_size, "error": str(e)})
                processed += len(batch)

        duration = (time.time() - start_time) * 1000

        status = BatchOperationStatus.COMPLETED
        if errors:
            status = BatchOperationStatus.PARTIAL if succeeded > 0 else BatchOperationStatus.FAILED

        return BatchResult(
            success=len(errors) == 0 or succeeded > 0,
            processed=processed,
            succeeded=succeeded,
            failed=processed - succeeded,
            errors=errors,
            duration_ms=duration,
            status=status
        )

    def _update_batch_internal(
        self,
        user_id: str,
        updates: list[tuple[str, dict]]
    ) -> int:
        """
        内部批量更新实现

        Returns:
            int: 成功更新的数量
        """
        allowed_fields = ["content", "context", "scene", "rating",
                         "expire_at", "compressed", "value_assessment"]

        conn = None
        succeeded = 0

        try:
            conn = PostgresConnectionPool.get_connection()

            with self._rw_lock.gen_wlock(), conn.cursor() as c:
                for mem_id, update_dict in updates:
                    valid_updates = {k: v for k, v in update_dict.items()
                                   if k in allowed_fields}

                    if not valid_updates:
                        continue

                    # 序列化内容
                    if "content" in valid_updates and not isinstance(valid_updates["content"], str):
                        valid_updates["content"] = json.dumps(valid_updates["content"], ensure_ascii=False)

                    # 处理JSONB字段
                    jsonb_fields = ["context", "value_assessment"]
                    for field in jsonb_fields:
                        if field in valid_updates and valid_updates[field] is not None:
                            valid_updates[field] = Json(valid_updates[field])

                    # 【安全修复】使用参数化查询，避免SQL注入
                    # 白名单验证字段名，防止字段名注入
                    ALLOWED_FIELDS = {"content", "context", "scene", "rating",
                                     "expire_at", "compressed", "value_assessment"}

                    validated_updates = {}
                    for k, v in valid_updates.items():
                        if k in ALLOWED_FIELDS:
                            validated_updates[k] = v
                        else:
                            logger.warning(f"[SECURITY_WARNING] 忽略非法字段: {k}")

                    if not validated_updates:
                        continue

                    # 构建安全的参数化查询
                    set_clause = ", ".join([f"{k} = %s" for k in validated_updates])
                    set_clause += ", updated_at = CURRENT_TIMESTAMP"

                    sql = f"UPDATE memories SET {set_clause} WHERE id = %s AND user_id = %s"
                    c.execute(sql, list(validated_updates.values()) + [mem_id, user_id])

                    if c.rowcount > 0:
                        succeeded += 1

                conn.commit()

            return succeeded

        except Exception as e:
            if conn:
                conn.rollback()
            raise e
        finally:
            if conn:
                PostgresConnectionPool.return_connection(conn)

    async def _update_batch_internal_async(
        self,
        user_id: str,
        updates: list[tuple[str, dict]]
    ) -> int:
        """
        内部批量更新实现（异步版本，原生asyncpg）

        Returns:
            int: 成功更新的数量
        """
        allowed_fields = {"content", "context", "scene", "rating",
                          "expire_at", "compressed", "value_assessment"}

        from core.memory.postgres_pool import AsyncPostgresPool
        pool = await AsyncPostgresPool.get_pool()
        succeeded = 0

        async with pool.acquire() as conn, conn.transaction():
            for mem_id, update_dict in updates:
                valid_updates = {k: v for k, v in update_dict.items()
                                 if k in allowed_fields}

                if not valid_updates:
                    continue

                # 序列化内容
                if "content" in valid_updates and not isinstance(valid_updates["content"], str):
                    valid_updates["content"] = json.dumps(valid_updates["content"], ensure_ascii=False)

                # 处理JSONB字段（asyncpg 自动处理 dict -> jsonb）
                jsonb_fields = {"context", "value_assessment"}
                for field in jsonb_fields:
                    if field in valid_updates and valid_updates[field] is not None and not isinstance(valid_updates[field], str):
                        valid_updates[field] = json.dumps(valid_updates[field], ensure_ascii=False)

                if not valid_updates:
                    continue

                # 构建 $N 参数化查询
                set_parts = []
                params = []
                idx = 1
                for k, v in valid_updates.items():
                    set_parts.append(f"{k} = ${idx}")
                    params.append(v)
                    idx += 1

                set_parts.append("updated_at = CURRENT_TIMESTAMP")
                params.append(mem_id)
                idx += 1
                params.append(user_id)

                sql = f"UPDATE memories SET {', '.join(set_parts)} WHERE id = ${idx - 1} AND user_id = ${idx}"
                result = await conn.execute(sql, *params)

                if "UPDATE" in result:
                    count = int(result.split()[-1])
                    succeeded += count

        return succeeded

    async def batch_delete_memories(
        self,
        user_id: str,
        mem_ids: list[str],
        batch_size: int = DEFAULT_BATCH_SIZE,
        sync_vector: bool = True,
        progress_callback: Callable[[int, int], None] | None = None
    ) -> BatchResult:
        """
        批量删除记忆

        Args:
            user_id: 用户ID
            mem_ids: 记忆ID列表
            batch_size: 每批处理数量
            sync_vector: 是否同步删除向量
            progress_callback: 进度回调

        Returns:
            BatchResult: 批量操作结果
        """
        start_time = time.time()

        if not mem_ids:
            return BatchResult(
                success=True, processed=0, succeeded=0, failed=0,
                errors=[], duration_ms=0, status=BatchOperationStatus.COMPLETED
            )

        # 去重
        mem_ids = list(dict.fromkeys(mem_ids))
        batch_size = min(batch_size, MAX_BATCH_SIZE)

        deleted = 0
        errors = []
        total = len(mem_ids)
        processed = 0

        # 获取记忆信息用于向量删除
        memory_info_map = {}
        if sync_vector:
            memory_info_map = await self._get_memory_info_batch_async(user_id, mem_ids)

        for i in range(0, len(mem_ids), batch_size):
            batch = mem_ids[i:i + batch_size]

            try:
                batch_deleted = await self._delete_batch_internal_async(user_id, batch)
                deleted += batch_deleted
                processed += len(batch)

                # 向量级联删除
                if sync_vector:
                    for mem_id in batch:
                        info = memory_info_map.get(mem_id)
                        if info:
                            await self._delete_from_vector_async(user_id, mem_id, info)

                if progress_callback:
                    progress_callback(processed, total)

            except Exception as e:
                logger.error(f"[BatchDelete] 批次失败: {e}")
                errors.append({"batch_index": i // batch_size, "error": str(e)})
                processed += len(batch)

        duration = (time.time() - start_time) * 1000

        status = BatchOperationStatus.COMPLETED
        if errors:
            status = BatchOperationStatus.PARTIAL if deleted > 0 else BatchOperationStatus.FAILED

        return BatchResult(
            success=len(errors) == 0 or deleted > 0,
            processed=processed,
            succeeded=deleted,
            failed=processed - deleted,
            errors=errors,
            duration_ms=duration,
            status=status
        )


    async def _delete_batch_internal_async(self, user_id: str, mem_ids: list[str]) -> int:
        """内部批量删除实现（异步版本，原生asyncpg）"""
        from core.memory.postgres_pool import AsyncPostgresPool
        pool = await AsyncPostgresPool.get_pool()

        placeholders = ','.join([f"${i}" for i in range(1, len(mem_ids) + 1)])
        params = mem_ids + [user_id]

        async with pool.acquire() as conn:
            result = await conn.execute(
                f"DELETE FROM memories WHERE id IN ({placeholders}) AND user_id = ${len(mem_ids) + 1}",
                *params
            )
            # asyncpg execute 返回形如 "DELETE N" 的字符串
            if "DELETE" in result:
                return int(result.split()[-1])
            return 0


    async def _get_memory_info_batch_async(self, user_id: str, mem_ids: list[str]) -> dict[str, dict]:
        """批量获取记忆信息（异步版本，原生asyncpg）"""
        from core.memory.postgres_pool import AsyncPostgresPool
        info_map = {}

        try:
            pool = await AsyncPostgresPool.get_pool()
            placeholders = ','.join([f"${i}" for i in range(1, len(mem_ids) + 1)])
            params = mem_ids + [user_id]

            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    f"SELECT id, mem_type, context FROM memories WHERE id IN ({placeholders}) AND user_id = ${len(mem_ids) + 1}",
                    *params
                )

                for row in rows:
                    info_map[row["id"]] = dict(row)

            return info_map

        except Exception as e:
            logger.error(f"[BatchOps] 异步获取记忆信息失败: {e}")
            return {}

    async def _sync_batch_to_vector_async(
        self,
        user_id: str,
        items: list[BatchMemoryItem],
        mem_ids: list[str]
    ):
        """异步批量同步到向量库"""
        async def sync_task():
            try:
                ms = await get_memory_service()

                for item, mem_id in zip(items, mem_ids, strict=False):
                    text = item.content.get("text", str(item.content))
                    metadata = {
                        "mem_id": mem_id,
                        "layer": item.layer,
                        "mem_type": item.mem_type,
                        "user_id": user_id
                    }

                    collection = item.mem_type if item.mem_type in ["experience", "knowledge", "chat"] else "knowledge"
                    await ms.vector_store.add(collection, text, metadata)

            except Exception as e:
                logger.debug(f"[BatchOps] 向量同步失败: {e}")

        # 启动后台异步任务执行
        safe_create_task(sync_task(), name="sync_task")

    async def _delete_from_vector_async(self, user_id: str, mem_id: str, memory_info: dict):
        """异步从向量库删除"""
        async def delete_task():
            try:
                ms = await get_memory_service()

                context = memory_info.get("context", {})
                vector_id = context.get("_vector_id")

                if vector_id:
                    parts = vector_id.split('_')
                    collection = parts[0] if parts and parts[0] in ["experience", "knowledge", "chat"] else "knowledge"
                    await ms.vector_store.delete(collection, [vector_id])

            except Exception as e:
                logger.debug(f"[BatchOps] 向量删除失败: {e}")

        safe_create_task(delete_task(), name="delete_task")

    # ═══════════════════════════════════════════════════════════════════
    # 异步API
    # ═══════════════════════════════════════════════════════════════════

    async def async_batch_add(
        self,
        user_id: str,
        items: list[BatchMemoryItem],
        batch_size: int = ASYNC_BATCH_SIZE,
        sync_vector: bool = True
    ) -> BatchResult:
        """
        异步批量添加

        Args:
            user_id: 用户ID
            items: 记忆条目列表
            batch_size: 批处理大小
            sync_vector: 是否同步向量

        Returns:
            BatchResult: 批量操作结果
        """
        return await self.batch_add_memories(
            user_id, items, batch_size, None, sync_vector
        )

    async def async_batch_delete(
        self,
        user_id: str,
        mem_ids: list[str],
        batch_size: int = ASYNC_BATCH_SIZE,
        sync_vector: bool = True
    ) -> BatchResult:
        """异步批量删除"""
        return await self.batch_delete_memories(
            user_id, mem_ids, batch_size, sync_vector, None
        )

    def close(self):
        """关闭批量操作管理器"""
        self._executor.shutdown(wait=True)
        logger.info("[MemoryBatchOperations] 已关闭")


# ═══════════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════════

async def batch_add_memories(
    user_id: str,
    memories: list[dict],
    batch_size: int = DEFAULT_BATCH_SIZE,
    sync_vector: bool = True
) -> BatchResult:
    """
    便捷函数: 批量添加记忆

    Args:
        user_id: 用户ID
        memories: 记忆数据列表，每个元素为字典:
            {
                "layer": "short",
                "content": {"text": "..."},
                "mem_type": "chat",
                ...
            }
        batch_size: 批处理大小
        sync_vector: 是否同步向量

    Returns:
        BatchResult: 操作结果
    """
    batch_ops = MemoryBatchOperations()

    items = []
    for mem in memories:
        item = BatchMemoryItem(
            layer=mem.get("layer", "short"),
            content=mem.get("content", {}),
            mem_type=mem.get("mem_type", "general"),
            context=mem.get("context"),
            scene=mem.get("scene", ""),
            rating=mem.get("rating", 0),
            expire_days=mem.get("expire_days"),
            value_assessment=mem.get("value_assessment")
        )
        items.append(item)

    return await batch_ops.batch_add_memories(user_id, items, batch_size, None, sync_vector)


async def batch_delete_memories(
    user_id: str,
    mem_ids: list[str],
    batch_size: int = DEFAULT_BATCH_SIZE,
    sync_vector: bool = True
) -> BatchResult:
    """
    便捷函数: 批量删除记忆

    Args:
        user_id: 用户ID
        mem_ids: 记忆ID列表
        batch_size: 批处理大小
        sync_vector: 是否同步删除向量

    Returns:
        BatchResult: 操作结果
    """
    batch_ops = MemoryBatchOperations()
    return await batch_ops.batch_delete_memories(user_id, mem_ids, batch_size, sync_vector)


# ═══════════════════════════════════════════════════════════════════
# 全局实例
# ═══════════════════════════════════════════════════════════════════

batch_operations = MemoryBatchOperations()


# 内存泄漏修复: 注册atexit处理器，确保程序退出时关闭线程池
def _cleanup_batch_operations():
    """程序退出时清理批量操作管理器"""
    with contextlib.suppress(Exception):
        batch_operations.close()  # 退出时不抛出异常

atexit.register(_cleanup_batch_operations)


# ═══════════════════════════════════════════════════════════════════
# 单元测试
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("测试批量操作模块...")

    # 注意: 这些测试需要数据库连接
    # 实际测试应在测试环境中运行

    print("✓ 批量操作模块加载成功")
    print(f"默认批处理大小: {DEFAULT_BATCH_SIZE}")
    print(f"最大批处理大小: {MAX_BATCH_SIZE}")
