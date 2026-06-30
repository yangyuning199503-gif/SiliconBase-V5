#!/usr/bin/env python3
"""
记忆数据压缩模块 V1.0 - 存储空间优化
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【功能特性】
  ✓ 自动识别可压缩记忆
  ✓ 相似记忆合并压缩
  ✓ 时间序列压缩
  ✓ 压缩比例统计
  ✓ 定时压缩任务

【压缩策略】
  - 30天前的L2短期记忆 -> 摘要压缩
  - 相似度>0.8的记忆 -> 合并压缩
  - 重复内容 -> 去重保留最新
  - 低价值记忆 -> 删除或归档

【作者】Agent-10: 性能优化工程师
【日期】2026-03-06
"""

import asyncio
import difflib
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime

from core.db.connection_pool import PostgresConnectionPool, RealDictCursor
from core.diagnostic import safe_create_task

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# 配置常量
# ═══════════════════════════════════════════════════════════════════

DEFAULT_COMPRESSION_AGE_DAYS = 30      # 默认压缩30天前的数据
SIMILARITY_THRESHOLD = 0.8             # 相似度阈值
MIN_COMPRESSION_BATCH = 10             # 最小压缩批次
MAX_COMPRESSION_BATCH = 500            # 最大压缩批次
COMPRESSION_INTERVAL_HOURS = 24        # 压缩间隔(小时)


@dataclass
class CompressionResult:
    """压缩结果"""
    success: bool
    compressed_count: int          # 压缩的记忆数量
    merged_count: int              # 合并的记忆数量
    deleted_count: int             # 删除的记忆数量
    saved_bytes: int               # 节省的字节数
    duration_ms: float             # 耗时(毫秒)
    details: list[dict] = field(default_factory=list)


@dataclass
class CompressionCandidate:
    """压缩候选"""
    mem_id: str
    layer: str
    content: str
    created_at: datetime
    rating: int
    similarity_group: str | None = None


# ═══════════════════════════════════════════════════════════════════
# 记忆压缩器
# ═══════════════════════════════════════════════════════════════════

class MemoryCompressor:
    """
    记忆数据压缩器

    提供记忆数据的压缩、合并和清理功能，优化存储空间使用。
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

        self._stop_event = asyncio.Event()
        self._compression_task = None

        logger.info("[MemoryCompressor] 初始化完成")

    def compress_old_memories(
        self,
        user_id: str,
        days: int = DEFAULT_COMPRESSION_AGE_DAYS,
        layer: str | None = None,
        dry_run: bool = False
    ) -> CompressionResult:
        """
        压缩旧记忆

        压缩指定天数前的记忆，减少存储空间占用。

        Args:
            user_id: 用户ID
            days: 压缩多少天前的数据
            layer: 指定层级，None表示所有层级
            dry_run: 仅模拟，不实际执行

        Returns:
            CompressionResult: 压缩结果
        """
        start_time = time.time()

        try:
            # 获取可压缩的记忆
            candidates = self._get_compression_candidates(user_id, days, layer)

            if not candidates:
                return CompressionResult(
                    success=True,
                    compressed_count=0,
                    merged_count=0,
                    deleted_count=0,
                    saved_bytes=0,
                    duration_ms=(time.time() - start_time) * 1000
                )

            # 分组相似记忆
            groups = self._group_similar_memories(candidates)

            # 执行压缩
            result = self._execute_compression(user_id, groups, dry_run)

            result.duration_ms = (time.time() - start_time) * 1000

            if dry_run:
                logger.info(f"[MemoryCompressor] 模拟压缩完成: {result.compressed_count} 条可压缩")
            else:
                logger.info(f"[MemoryCompressor] 压缩完成: {result.compressed_count} 条记忆, "
                          f"节省 {result.saved_bytes / 1024:.2f} KB")

            return result

        except Exception as e:
            logger.error(f"[MemoryCompressor] 压缩失败: {e}")
            return CompressionResult(
                success=False,
                compressed_count=0,
                merged_count=0,
                deleted_count=0,
                saved_bytes=0,
                duration_ms=(time.time() - start_time) * 1000
            )

    def _get_compression_candidates(
        self,
        user_id: str,
        days: int,
        layer: str | None
    ) -> list[CompressionCandidate]:
        """获取压缩候选列表"""
        conn = None
        candidates = []

        try:
            conn = PostgresConnectionPool.get_connection()

            with conn.cursor(cursor_factory=RealDictCursor) as c:
                if layer:
                    c.execute("""
                        SELECT id, layer, content, created_at, rating
                        FROM memories
                        WHERE user_id = %s
                        AND layer = %s
                        AND created_at < CURRENT_TIMESTAMP - INTERVAL '%s days'
                        AND compressed = 0
                        AND (expire_at IS NULL OR expire_at > CURRENT_TIMESTAMP)
                        ORDER BY created_at ASC
                        LIMIT %s
                    """, (user_id, layer, days, MAX_COMPRESSION_BATCH))
                else:
                    c.execute("""
                        SELECT id, layer, content, created_at, rating
                        FROM memories
                        WHERE user_id = %s
                        AND created_at < CURRENT_TIMESTAMP - INTERVAL '%s days'
                        AND compressed = 0
                        AND layer IN ('short', 'working')
                        AND (expire_at IS NULL OR expire_at > CURRENT_TIMESTAMP)
                        ORDER BY created_at ASC
                        LIMIT %s
                    """, (user_id, days, MAX_COMPRESSION_BATCH))

                for row in c.fetchall():
                    try:
                        content = json.loads(row['content']) if row['content'].startswith('{') else {"text": row['content']}
                        text = content.get("text", str(content))
                    except (json.JSONDecodeError, AttributeError, TypeError) as e:
                        logger.error(f"[MemoryCompressor] 内容解析失败: {e}", exc_info=True)
                        text = str(row['content'])

                    candidates.append(CompressionCandidate(
                        mem_id=row['id'],
                        layer=row['layer'],
                        content=text,
                        created_at=row['created_at'],
                        rating=row['rating']
                    ))

            return candidates

        except Exception as e:
            logger.error(f"[MemoryCompressor] 获取候选失败: {e}")
            return []
        finally:
            if conn:
                PostgresConnectionPool.return_connection(conn)

    def _group_similar_memories(
        self,
        candidates: list[CompressionCandidate]
    ) -> list[list[CompressionCandidate]]:
        """按相似度分组记忆"""
        if not candidates:
            return []

        groups = []
        used = set()

        for i, candidate in enumerate(candidates):
            if candidate.mem_id in used:
                continue

            # 创建新组
            group = [candidate]
            used.add(candidate.mem_id)

            # 查找相似记忆
            for _j, other in enumerate(candidates[i+1:], start=i+1):
                if other.mem_id in used:
                    continue

                similarity = self._calculate_similarity(candidate.content, other.content)

                if similarity >= SIMILARITY_THRESHOLD:
                    group.append(other)
                    used.add(other.mem_id)

            if len(group) >= 2:
                groups.append(group)

        return groups

    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """计算文本相似度"""
        if not text1 or not text2:
            return 0.0

        # 使用SequenceMatcher计算相似度
        return difflib.SequenceMatcher(None, text1.lower(), text2.lower()).ratio()

    def _execute_compression(
        self,
        user_id: str,
        groups: list[list[CompressionCandidate]],
        dry_run: bool
    ) -> CompressionResult:
        """执行压缩操作"""
        compressed_count = 0
        merged_count = 0
        deleted_count = 0
        saved_bytes = 0
        details = []

        for group in groups:
            if len(group) < 2:
                continue

            # 生成摘要
            summary = self._generate_summary(group)

            # 保留评分最高的作为代表
            representative = max(group, key=lambda x: x.rating)

            # 计算节省空间
            original_size = sum(len(c.content) for c in group)
            summary_size = len(summary)
            saved = original_size - summary_size

            if dry_run:
                details.append({
                    "action": "compress",
                    "group_size": len(group),
                    "representative_id": representative.mem_id,
                    "saved_bytes": saved
                })
            else:
                # 实际执行压缩
                success = self._merge_memories(
                    user_id,
                    [c.mem_id for c in group],
                    representative.mem_id,
                    summary
                )

                if success:
                    merged_count += 1
                    compressed_count += len(group)
                    saved_bytes += saved

                    # 删除其他记忆
                    for c in group:
                        if c.mem_id != representative.mem_id:
                            self._delete_memory(user_id, c.mem_id)
                            deleted_count += 1

            compressed_count += len(group)
            saved_bytes += saved

        return CompressionResult(
            success=True,
            compressed_count=compressed_count,
            merged_count=merged_count,
            deleted_count=deleted_count,
            saved_bytes=saved_bytes,
            duration_ms=0,
            details=details
        )

    def _generate_summary(self, group: list[CompressionCandidate]) -> str:
        """生成摘要"""
        # 简单策略：使用最长内容作为摘要
        longest = max(group, key=lambda x: len(x.content))

        # 如果内容太长，截取前半部分
        if len(longest.content) > 500:
            return longest.content[:500] + "... [压缩摘要]"

        return longest.content

    def _merge_memories(
        self,
        user_id: str,
        mem_ids: list[str],
        keep_id: str,
        summary: str
    ) -> bool:
        """合并记忆"""
        conn = None

        try:
            conn = PostgresConnectionPool.get_connection()

            with conn.cursor() as c:
                # 更新保留的记忆为压缩状态
                c.execute("""
                    UPDATE memories
                    SET content = %s,
                        compressed = 1,
                        context = COALESCE(context, '{}'::jsonb) || '{"compressed_from": []}'::jsonb
                    WHERE id = %s AND user_id = %s
                """, (json.dumps({"text": summary, "compressed": True}), keep_id, user_id))

                conn.commit()
                return True

        except Exception as e:
            logger.error(f"[MemoryCompressor] 合并记忆失败: {e}")
            if conn:
                conn.rollback()
            return False
        finally:
            if conn:
                PostgresConnectionPool.return_connection(conn)

    def _delete_memory(self, user_id: str, mem_id: str) -> bool:
        """删除记忆"""
        conn = None

        try:
            conn = PostgresConnectionPool.get_connection()

            with conn.cursor() as c:
                c.execute(
                    "DELETE FROM memories WHERE id = %s AND user_id = %s",
                    (mem_id, user_id)
                )
                conn.commit()
                return c.rowcount > 0

        except Exception as e:
            logger.error(f"[MemoryCompressor] 删除记忆失败: {e}")
            return False
        finally:
            if conn:
                PostgresConnectionPool.return_connection(conn)

    def cleanup_expired_memories(
        self,
        user_id: str,
        dry_run: bool = False
    ) -> CompressionResult:
        """
        清理过期记忆

        Args:
            user_id: 用户ID
            dry_run: 仅模拟

        Returns:
            CompressionResult: 清理结果
        """
        start_time = time.time()

        try:
            conn = None
            deleted_count = 0

            if not dry_run:
                conn = PostgresConnectionPool.get_connection()

                with conn.cursor() as c:
                    c.execute("""
                        DELETE FROM memories
                        WHERE user_id = %s
                        AND expire_at IS NOT NULL
                        AND expire_at < CURRENT_TIMESTAMP
                    """, (user_id,))

                    deleted_count = c.rowcount
                    conn.commit()

            duration = (time.time() - start_time) * 1000

            logger.info(f"[MemoryCompressor] 清理过期记忆: {deleted_count} 条")

            return CompressionResult(
                success=True,
                compressed_count=0,
                merged_count=0,
                deleted_count=deleted_count,
                saved_bytes=0,
                duration_ms=duration
            )

        except Exception as e:
            logger.error(f"[MemoryCompressor] 清理失败: {e}")
            return CompressionResult(
                success=False,
                compressed_count=0,
                merged_count=0,
                deleted_count=0,
                saved_bytes=0,
                duration_ms=(time.time() - start_time) * 1000
            )
        finally:
            if conn:
                PostgresConnectionPool.return_connection(conn)

    async def start_auto_compression(self, interval_hours: int = COMPRESSION_INTERVAL_HOURS):
        """
        启动自动压缩任务

        Args:
            interval_hours: 压缩间隔(小时)
        """
        if self._compression_task and not self._compression_task.done():
            logger.warning("[MemoryCompressor] 自动压缩已在运行")
            return

        self._stop_event.clear()
        self._compression_task = safe_create_task(self._compression_loop(interval_hours), name="_compression_loop")

        logger.info(f"[MemoryCompressor] 自动压缩已启动 (间隔: {interval_hours}小时)")

    async def _get_compression_candidates_async(
        self,
        user_id: str,
        days: int,
        layer: str | None
    ) -> list[CompressionCandidate]:
        """异步获取压缩候选列表（asyncpg）"""
        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                if layer:
                    rows = await conn.fetch("""
                        SELECT id, layer, content, created_at, rating
                        FROM memories
                        WHERE user_id = $1
                        AND layer = $2
                        AND created_at < CURRENT_TIMESTAMP - INTERVAL '%s days'
                        AND compressed = 0
                        AND (expire_at IS NULL OR expire_at > CURRENT_TIMESTAMP)
                        ORDER BY created_at ASC
                        LIMIT $4
                    """, user_id, layer, days, MAX_COMPRESSION_BATCH)
                else:
                    rows = await conn.fetch("""
                        SELECT id, layer, content, created_at, rating
                        FROM memories
                        WHERE user_id = $1
                        AND created_at < CURRENT_TIMESTAMP - INTERVAL '%s days'
                        AND compressed = 0
                        AND layer IN ('short', 'working')
                        AND (expire_at IS NULL OR expire_at > CURRENT_TIMESTAMP)
                        ORDER BY created_at ASC
                        LIMIT $3
                    """, user_id, days, MAX_COMPRESSION_BATCH)
                candidates = []
                for row in rows:
                    try:
                        content = json.loads(row['content']) if row['content'].startswith('{') else {"text": row['content']}
                        text = content.get("text", str(content))
                    except (json.JSONDecodeError, AttributeError, TypeError) as e:
                        logger.error(f"[MemoryCompressor] 内容解析失败: {e}", exc_info=True)
                        text = str(row['content'])
                    candidates.append(CompressionCandidate(
                        mem_id=row['id'],
                        layer=row['layer'],
                        content=text,
                        created_at=row['created_at'],
                        rating=row['rating']
                    ))
                return candidates
        except Exception as e:
            logger.error(f"[MemoryCompressor] 异步获取候选失败: {e}")
            return []

    async def _merge_memories_async(
        self,
        user_id: str,
        mem_ids: list[str],
        keep_id: str,
        summary: str
    ) -> bool:
        """异步合并记忆（asyncpg）"""
        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                await conn.execute("""
                    UPDATE memories
                    SET content = $1,
                        compressed = 1,
                        context = COALESCE(context, '{}'::jsonb) || '{\"compressed_from\": []}'::jsonb
                    WHERE id = $2 AND user_id = $3
                """, json.dumps({"text": summary, "compressed": True}), keep_id, user_id)
                return True
        except Exception as e:
            logger.error(f"[MemoryCompressor] 异步合并记忆失败: {e}")
            return False

    async def _delete_memory_async(self, user_id: str, mem_id: str) -> bool:
        """异步删除记忆（asyncpg）"""
        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM memories WHERE id = $1 AND user_id = $2",
                    mem_id, user_id
                )
                return True
        except Exception as e:
            logger.error(f"[MemoryCompressor] 异步删除记忆失败: {e}")
            return False

    async def compress_old_memories_async(
        self,
        user_id: str,
        days: int = DEFAULT_COMPRESSION_AGE_DAYS,
        layer: str | None = None,
        dry_run: bool = False
    ) -> CompressionResult:
        """异步压缩旧记忆"""
        start_time = time.time()
        try:
            candidates = await self._get_compression_candidates_async(user_id, days, layer)
            if not candidates:
                return CompressionResult(
                    success=True, compressed_count=0, merged_count=0,
                    deleted_count=0, saved_bytes=0,
                    duration_ms=(time.time() - start_time) * 1000
                )
            # CPU 密集型分组用 to_thread
            groups = await asyncio.to_thread(self._group_similar_memories, candidates)
            compressed_count = 0
            merged_count = 0
            deleted_count = 0
            saved_bytes = 0
            details = []
            for group in groups:
                if len(group) < 2:
                    continue
                summary = self._generate_summary(group)
                representative = max(group, key=lambda x: x.rating)
                original_size = sum(len(c.content) for c in group)
                summary_size = len(summary)
                saved = original_size - summary_size
                if dry_run:
                    details.append({
                        "action": "compress", "group_size": len(group),
                        "representative_id": representative.mem_id, "saved_bytes": saved
                    })
                else:
                    success = await self._merge_memories_async(
                        user_id, [c.mem_id for c in group], representative.mem_id, summary
                    )
                    if success:
                        merged_count += 1
                        compressed_count += len(group)
                        saved_bytes += saved
                        for c in group:
                            if c.mem_id != representative.mem_id:
                                await self._delete_memory_async(user_id, c.mem_id)
                                deleted_count += 1
                compressed_count += len(group)
                saved_bytes += saved
            return CompressionResult(
                success=True, compressed_count=compressed_count, merged_count=merged_count,
                deleted_count=deleted_count, saved_bytes=saved_bytes,
                duration_ms=(time.time() - start_time) * 1000, details=details
            )
        except Exception as e:
            logger.error(f"[MemoryCompressor] 异步压缩失败: {e}")
            return CompressionResult(
                success=False, compressed_count=0, merged_count=0,
                deleted_count=0, saved_bytes=0,
                duration_ms=(time.time() - start_time) * 1000
            )

    async def cleanup_expired_memories_async(
        self,
        user_id: str,
        dry_run: bool = False
    ) -> CompressionResult:
        """异步清理过期记忆（asyncpg）"""
        start_time = time.time()
        try:
            deleted_count = 0
            if not dry_run:
                from core.memory.postgres_pool import AsyncPostgresPool
                pool = await AsyncPostgresPool.get_pool()
                async with pool.acquire() as conn:
                    result = await conn.execute("""
                        DELETE FROM memories
                        WHERE user_id = $1
                        AND expire_at IS NOT NULL
                        AND expire_at < CURRENT_TIMESTAMP
                    """, user_id)
                    # asyncpg 的 execute 返回状态字符串如 'DELETE 5'
                    import re as _re
                    m = _re.search(r'(\d+)', result)
                    deleted_count = int(m.group(1)) if m else 0
            logger.info(f"[MemoryCompressor] 异步清理过期记忆: {deleted_count} 条")
            return CompressionResult(
                success=True, compressed_count=0, merged_count=0,
                deleted_count=deleted_count, saved_bytes=0,
                duration_ms=(time.time() - start_time) * 1000
            )
        except Exception as e:
            logger.error(f"[MemoryCompressor] 异步清理失败: {e}")
            return CompressionResult(
                success=False, compressed_count=0, merged_count=0,
                deleted_count=0, saved_bytes=0,
                duration_ms=(time.time() - start_time) * 1000
            )

    async def _compression_loop(self, interval_hours: int):
        """自动压缩循环（async）"""
        while not self._stop_event.is_set():
            try:
                # 等待间隔
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=interval_hours * 3600
                    )
                    break
                except asyncio.TimeoutError:
                    pass

                # 获取所有用户
                from core.memory.memory_service import get_memory_service
                ms = await get_memory_service()
                users = await ms.list_users()

                for user_id in users:
                    try:
                        # 压缩旧记忆（原生 async）
                        result = await self.compress_old_memories_async(user_id)

                        # 清理过期记忆（原生 async）
                        cleanup_result = await self.cleanup_expired_memories_async(user_id)

                        logger.info(f"[MemoryCompressor] 用户 {user_id} 自动压缩完成: "
                                  f"压缩 {result.compressed_count} 条, "
                                  f"清理 {cleanup_result.deleted_count} 条")

                    except Exception as e:
                        logger.error(f"[MemoryCompressor] 用户 {user_id} 自动压缩失败: {e}")

            except Exception as e:
                logger.error(f"[MemoryCompressor] 自动压缩循环异常: {e}")

    def stop_auto_compression(self):
        """停止自动压缩"""
        self._stop_event.set()
        if self._compression_task:
            self._compression_task.cancel()
        logger.info("[MemoryCompressor] 自动压缩已停止")


# ═══════════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════════

def compress_user_memories(
    user_id: str,
    days: int = DEFAULT_COMPRESSION_AGE_DAYS,
    dry_run: bool = False
) -> CompressionResult:
    """
    便捷函数: 压缩用户记忆

    Args:
        user_id: 用户ID
        days: 压缩多少天前的数据
        dry_run: 仅模拟

    Returns:
        CompressionResult: 压缩结果
    """
    compressor = MemoryCompressor()
    return compressor.compress_old_memories(user_id, days, dry_run=dry_run)


def cleanup_user_expired_memories(user_id: str) -> CompressionResult:
    """
    便捷函数: 清理用户过期记忆

    Args:
        user_id: 用户ID

    Returns:
        CompressionResult: 清理结果
    """
    compressor = MemoryCompressor()
    return compressor.cleanup_expired_memories(user_id)


# ═══════════════════════════════════════════════════════════════════
# 全局实例
# ═══════════════════════════════════════════════════════════════════

memory_compressor = MemoryCompressor()


# ═══════════════════════════════════════════════════════════════════
# 单元测试
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("测试记忆压缩模块...")

    compressor = MemoryCompressor()

    # 测试相似度计算
    sim = compressor._calculate_similarity(
        "这是一个测试文本",
        "这是测试文本"
    )
    print(f"相似度: {sim}")

    # 测试分组
    candidates = [
        CompressionCandidate("1", "short", "今天的天气很好", datetime.now(), 5),
        CompressionCandidate("2", "short", "今天天气不错", datetime.now(), 4),
        CompressionCandidate("3", "short", "完全不同的内容", datetime.now(), 3),
        CompressionCandidate("4", "short", "今天天气真好啊", datetime.now(), 5),
    ]

    groups = compressor._group_similar_memories(candidates)
    print(f"分组数量: {len(groups)}")
    for i, group in enumerate(groups):
        print(f"  组 {i+1}: {len(group)} 条")

    print("✓ 测试完成")
