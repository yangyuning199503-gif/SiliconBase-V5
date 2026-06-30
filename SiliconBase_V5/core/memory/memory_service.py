#!/usr/bin/env python3
"""
记忆服务（MemoryService）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
白皮书模块：统一异步记忆入口，替代 async_memory.py
职责：负责层路由（L1-L5），统一对外接口
约束：
  - 全 async 接口
  - 底层 L1-L3 走 PostgreSQL，L4-L5 走 VectorStore
  - 禁止裸 Dict，必须使用 MemoryMetadata
"""

import asyncio
import contextlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from core.logger import logger
from core.memory.memory_schema import MemoryMetadata
from core.memory.vector_store import SearchResult, VectorStore

# ═══════════════════════════════════════════════════════════════════════════════
# 辅助函数与常量（从旧模块 memory.py 提取，避免循环依赖）
# ═══════════════════════════════════════════════════════════════════════════════

ALL_LAYERS = ["working", "short", "medium", "evolve", "execution"]


class MemoryRetrievalError(Exception):
    """记忆检索错误 - 当记忆查询失败时抛出"""
    pass


class MemoryStorageError(Exception):
    """记忆存储错误 - 当记忆保存失败时抛出"""
    pass


DEFAULT_DIMENSION_WEIGHTS = {
    "emotional_temperature": 0.25,
    "ethical_safety": 0.20,
    "self_growth": 0.20,
    "execution_effectiveness": 0.15,
    "sustainability": 0.15,
    "inspiration_innovation": 0.05,
}


def generate_default_value_assessment() -> dict[str, Any]:
    """生成默认六维评分（C级）"""
    return {
        "emotional_temperature": 3,
        "ethical_safety": 3,
        "self_growth": 3,
        "execution_effectiveness": 3,
        "sustainability": 3,
        "inspiration_innovation": 3,
        "overall": 3.0,
        "grade": "C",
    }


def calculate_overall_score(dimensions: dict[str, int]) -> Any:
    """计算综合得分和等级"""
    if not dimensions:
        return 3.0, "C"
    weighted_sum = sum(
        dimensions.get(dim, 3) * weight
        for dim, weight in DEFAULT_DIMENSION_WEIGHTS.items()
    )
    if weighted_sum >= 4.5:
        grade = "S"
    elif weighted_sum >= 4.0:
        grade = "A"
    elif weighted_sum >= 3.5:
        grade = "B"
    elif weighted_sum >= 2.5:
        grade = "C"
    else:
        grade = "D"
    return round(weighted_sum, 2), grade


def _serialize_content(content: Any) -> str:
    """内容序列化"""
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False)


def _deserialize_content(raw_content: Any) -> Any:
    """内容反序列化"""
    if raw_content is None:
        return None
    if isinstance(raw_content, str) and (
        raw_content.startswith("{") or raw_content.startswith("[")
    ):
        try:
            return json.loads(raw_content)
        except (json.JSONDecodeError, TypeError):
            pass
    return raw_content


@dataclass
class RetrievedContext:
    """
    检索到的上下文——分层结果
    """
    l1: list[Any]           # 工作记忆（PostgreSQL）
    l2: list[SearchResult]  # 语义对话记忆（VectorStore）
    l3: list[SearchResult]  # 知识记忆（VectorStore）
    l4: list[SearchResult]  # 经验记忆（VectorStore）


class MemoryService:
    """
    记忆服务——统一异步入口

    替代 async_memory.py 的胶水层角色，提供清晰的层路由。
    """

    def __init__(
        self,
        pg_pool: Any,
        vector_store: VectorStore
    ) -> None:
        """
        Args:
            pg_pool: 异步 PostgreSQL 连接池（如 asyncpg）
            vector_store: VectorStore 实例（L4-L5 向量记忆）
        """
        self.pg_pool = pg_pool
        self.vector_store = vector_store

    async def save_chat_turn(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: MemoryMetadata,
        trace_id: str = "",
    ) -> str:
        """
        保存对话轮次

        双写策略：
        1. 写入 PostgreSQL（短期记忆，快速检索）
        2. 索引到 VectorStore（长期语义检索）

        【P1-1】支持 trace_id 贯穿信息闭环。
        【P3-6】双写不一致修复：VectorStore 失败时加入补偿重试队列。
        """
        # 【P1-1】自动从上下文获取 trace_id
        if not trace_id:
            try:
                from core.traceability import get_trace_id
                trace_id = get_trace_id()
            except Exception:
                pass

        # 将 trace_id 注入 metadata
        if trace_id and metadata:
            try:
                if hasattr(metadata, 'context') and metadata.context is None:
                    metadata.context = {}
                if hasattr(metadata, 'context') and isinstance(metadata.context, dict):
                    metadata.context['trace_id'] = trace_id
            except Exception:
                pass

        # 1. 写入 PostgreSQL
        mem_id = await self._insert_pg(
            layer="working",
            session_id=session_id,
            role=role,
            content=content,
            metadata=metadata
        )

        # 【P1-1】记录记忆到 trace 索引
        if trace_id:
            try:
                from core.traceability import record_memory
                record_memory(trace_id, mem_id, layer="working")
            except Exception:
                pass

        # 2. 索引到向量存储（带补偿重试）
        try:
            await self.vector_store.add("chat", content, metadata)
        except Exception as e:
            logger.error(f"[MemoryService] VectorStore 索引失败，加入补偿队列: {e}")
            # 【P3-6】补偿重试：放入后台队列异步重试
            try:
                _enqueue_vector_store_retry("chat", content, metadata)
            except Exception as retry_err:
                logger.error(f"[MemoryService] 补偿队列入队失败: {retry_err}")

        return mem_id

    async def save_execution_record(
        self,
        instruction: str,
        metadata: MemoryMetadata
    ) -> str:
        """保存工具执行记录到经验集合"""
        return await self.vector_store.add("execution", instruction, metadata)

    async def save_pattern(
        self,
        pattern_description: str,
        metadata: MemoryMetadata
    ) -> str:
        """保存提取的模式到知识集合"""
        return await self.vector_store.add("knowledge", pattern_description, metadata)

    async def add_memory(
        self,
        user_id: str,
        content: str,
        memory_type: str = "general",
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        """
        添加用户记忆（简化接口，与旧 MemoryManager.add_memory 兼容）。

        旧签名: MemoryManager.add_memory(user_id, content, memory_type="general", metadata=None, **kwargs)
        """
        layer = kwargs.get("layer", "short")
        mem_type = memory_type
        context = kwargs.get("context", metadata) if metadata else kwargs.get("context")
        scene = kwargs.get("scene", "")
        rating = kwargs.get("rating", 0)
        expire_days = kwargs.get("expire_days")
        source = kwargs.get("source", "system")
        creator = kwargs.get("creator", "memory_service")

        mem_id = str(uuid.uuid4())
        expire_at = None
        if expire_days:
            expire_at = datetime.now() + timedelta(days=expire_days)

        content_str = _serialize_content(content)
        context_json = json.dumps(context, ensure_ascii=False) if context else None

        value_assessment = kwargs.get("value_assessment")
        if value_assessment is None:
            value_assessment = generate_default_value_assessment()
        else:
            default_va = generate_default_value_assessment()
            default_va.update(value_assessment)
            dims = {k: v for k, v in default_va.items() if k not in ("overall", "grade")}
            default_va["overall"], default_va["grade"] = calculate_overall_score(dims)
            value_assessment = default_va
        va_json = json.dumps(value_assessment, ensure_ascii=False)

        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO memories
                    (id, user_id, layer, mem_type, content, context,
                     scene, rating, source, expire_at, value_assessment, creator)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                    """,
                    mem_id, user_id, layer, mem_type, content_str,
                    context_json, scene, rating, source, expire_at, va_json, creator,
                )
            return mem_id
        except Exception as e:
            logger.error(f"[MemoryService] add_memory 失败: {e}", exc_info=True)
            raise RuntimeError(f"[MemoryService] add_memory 失败: {e}") from e

    async def save_memory(
        self,
        user_id: str,
        layer: str,
        mem_type: str,
        content: str,
        metadata: MemoryMetadata,
        context: dict | None = None,
        scene: str = "",
        rating: int = 0,
        expire_days: int | None = None,
    ) -> str:
        """
        通用记忆写入——支持任意 layer/mem_type，替代 AsyncMemory.save() 的 PG 写入部分。

        写入 PostgreSQL（L1-L3），不自动同步到 VectorStore。
        如需向量索引，调用方应额外调用 save_execution_record / save_pattern / save_chat_turn。
        """
        mem_id = str(uuid.uuid4())

        expire_at = None
        if expire_days:
            expire_at = datetime.now() + timedelta(days=expire_days)

        context_json = json.dumps(context, ensure_ascii=False) if context else None
        value_assessment_json = json.dumps(
            {"overall": 3.0, "grade": "C"}, ensure_ascii=False
        )

        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO memories
                    (id, user_id, layer, mem_type, content, context,
                     scene, rating, source, expire_at, value_assessment, creator)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                    """,
                    mem_id,
                    user_id,
                    layer,
                    mem_type,
                    content,
                    context_json,
                    scene,
                    rating,
                    metadata.source,
                    expire_at,
                    value_assessment_json,
                    "memory_service",
                )
            return mem_id
        except Exception as e:
            logger.error(f"[MemoryService] save_memory PG 写入失败: {e}", exc_info=True)
            raise RuntimeError(f"[MemoryService] save_memory PG 写入失败: {e}") from e

    async def retrieve_context(
        self,
        user_id: str,
        query: str,
        task_type: str | None = None
    ) -> RetrievedContext:
        """
        分层检索上下文

        检索策略：
        - L1：工作记忆（最近 10 条 PostgreSQL 记录）
        - L2：语义对话记忆（VectorStore chat 集合，Top 5）
        - L3：知识记忆（VectorStore knowledge 集合，Top 2）
        - L4：经验记忆（VectorStore execution 集合，Top 3）
        """
        l1_results = await self._query_pg(layer="working", user_id=user_id, limit=10)
        l2_results = await self.vector_store.search("chat", query, limit=5)
        l3_results = await self.vector_store.search("knowledge", query, limit=2)
        l4_results = await self.vector_store.search("execution", query, limit=3)

        return RetrievedContext(
            l1=l1_results,
            l2=l2_results,
            l3=l3_results,
            l4=l4_results
        )

    async def _insert_pg(
        self,
        layer: str,
        session_id: str,
        role: str,
        content: str,
        metadata: MemoryMetadata
    ) -> str:
        """写入 PostgreSQL——复用 AsyncPostgresPool 真实连接池"""
        mem_id = str(uuid.uuid4())

        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO memories
                    (id, user_id, layer, mem_type, content, context,
                     scene, rating, source, expire_at, value_assessment, creator)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                    """,
                    mem_id,
                    metadata.user_id,
                    layer,
                    layer,
                    content,
                    json.dumps({"role": role, "session_id": session_id}, ensure_ascii=False),
                    "",
                    0,
                    metadata.source,
                    None,  # expire_at
                    json.dumps({"overall": 3.0, "grade": "C"}, ensure_ascii=False),
                    "memory_service",
                )
            return mem_id
        except Exception as e:
            logger.error(f"[MemoryService] PG 写入失败: {e}")
            # 非阻塞失败：返回 mock ID，保证上游不崩
            return mem_id

    def _sort_by_dimension_weights(
        self,
        results: list[dict[str, Any]],
        dimension_weights: dict[str, float],
    ) -> list[dict[str, Any]]:
        """按维度加权分数排序（复用 UserMemoryStore 逻辑）。"""
        def calc_weighted_score(mem):
            va = mem.get("value_assessment", {})
            return sum(va.get(dim, 3) * weight for dim, weight in dimension_weights.items())
        return sorted(results, key=calc_weighted_score, reverse=True)

    async def query_memories(
        self,
        user_id: str,
        layer: str | None = None,
        mem_type: str | None = None,
        scene: str | None = None,
        limit: int = 10,
        min_rating: int = -1,
        filter_dict: dict[str, Any] | None = None,
        dimension_weights: dict[str, float] | None = None,
    ) -> list[dict[str, Any]]:
        """
        查询记忆——支持多条件过滤的异步 PG 查询。

        适配旧版 memory.get() / AsyncMemory.get() / MemoryManager.query() 的查询语义，
        底层走 asyncpg，真异步，不阻塞事件循环。
        """
        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()

            conditions = ["user_id = $1", "(expire_at IS NULL OR expire_at > CURRENT_TIMESTAMP)"]
            params: list[Any] = [user_id]
            param_idx = 2

            if layer:
                conditions.append(f"layer = ${param_idx}")
                params.append(layer)
                param_idx += 1
            if mem_type:
                conditions.append(f"mem_type = ${param_idx}")
                params.append(mem_type)
                param_idx += 1
            if scene:
                conditions.append(f"scene = ${param_idx}")
                params.append(scene)
                param_idx += 1
            if min_rating > -1:
                conditions.append(f"rating >= ${param_idx}")
                params.append(min_rating)
                param_idx += 1

            # filter_dict 支持额外过滤（兼容旧 MemoryManager.query 的 filters）
            if filter_dict:
                for key, value in filter_dict.items():
                    if key in ("layer", "mem_type", "user_id", "min_rating", "scene"):
                        continue
                    if key == "since":
                        conditions.append(f"created_at >= ${param_idx}")
                        params.append(value)
                        param_idx += 1
                    elif key == "until":
                        conditions.append(f"created_at <= ${param_idx}")
                        params.append(value)
                        param_idx += 1
                    elif key == "min_overall_score":
                        conditions.append(f"(value_assessment->>'overall')::float >= ${param_idx}")
                        params.append(value)
                        param_idx += 1
                    elif key == "sources":
                        if isinstance(value, list):
                            if len(value) == 1:
                                conditions.append(f"source = ${param_idx}")
                                params.append(value[0])
                                param_idx += 1
                            elif len(value) > 1:
                                placeholders = ",".join([f"${param_idx + j}" for j in range(len(value))])
                                conditions.append(f"source IN ({placeholders})")
                                params.extend(value)
                                param_idx += len(value)
                        else:
                            conditions.append(f"source = ${param_idx}")
                            params.append(value)
                            param_idx += 1
                    elif key == "session_id":
                        if isinstance(value, str) and value.startswith("!"):
                            conditions.append(
                                f"(content::jsonb->>'session_id' IS NULL OR content::jsonb->>'session_id' != ${param_idx})"
                            )
                            params.append(value[1:])
                        else:
                            conditions.append(f"content::jsonb->>'session_id' = ${param_idx}")
                            params.append(value)
                        param_idx += 1
                    else:
                        # 默认当作 context JSONB 字段
                        conditions.append(f"(context->>'{key}' = ${param_idx})")
                        params.append(str(value))
                        param_idx += 1

            where_clause = " AND ".join(conditions)
            sql = f"""
                SELECT id, layer, mem_type, content, context, scene,
                       rating, source, value_assessment, created_at
                FROM memories
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT ${param_idx}
            """
            params.append(limit)

            rows = await pool.fetch(sql, *params)
            results = []
            for row in rows:
                record = dict(row)
                if isinstance(record.get("value_assessment"), str):
                    try:
                        record["value_assessment"] = json.loads(record["value_assessment"])
                    except Exception:
                        record["value_assessment"] = {}
                if isinstance(record.get("content"), str) and (
                    record["content"].startswith("{") or record["content"].startswith("[")
                ):
                    with contextlib.suppress(Exception):
                        record["content"] = json.loads(record["content"])
                results.append(record)
            if dimension_weights:
                results = self._sort_by_dimension_weights(results, dimension_weights)
            return results
        except Exception as e:
            logger.error(f"[MemoryService] 查询记忆失败: {e}")
            return []

    async def _query_pg(
        self,
        layer: str,
        user_id: str,
        limit: int
    ) -> list[Any]:
        """查询 PostgreSQL——复用 AsyncPostgresPool 真实连接池"""
        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            rows = await pool.fetch(
                """
                SELECT id, layer, mem_type, content, context, scene,
                       rating, source, value_assessment, created_at
                FROM memories
                WHERE user_id = $1
                  AND ($2::text IS NULL OR layer = $2)
                  AND (expire_at IS NULL OR expire_at > CURRENT_TIMESTAMP)
                ORDER BY created_at DESC
                LIMIT $3
                """,
                user_id,
                layer,
                limit,
            )
            results = []
            for row in rows:
                record = dict(row)
                if isinstance(record.get("value_assessment"), str):
                    try:
                        record["value_assessment"] = json.loads(record["value_assessment"])
                    except Exception:
                        record["value_assessment"] = {}
                if isinstance(record.get("content"), str) and (
                    record["content"].startswith("{") or record["content"].startswith("[")
                ):
                    with contextlib.suppress(Exception):
                        record["content"] = json.loads(record["content"])
                results.append(record)
            return results
        except Exception as e:
            logger.error(f"[MemoryService] PG 查询失败: {e}")
            return []

    # ═══════════════════════════════════════════════════════════════════════
    # 1.1 补充生命体征与自发行动查询（供 consciousness_api.py 使用）
    # ═══════════════════════════════════════════════════════════════════════

    async def get_vital_signs_history(
        self,
        user_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        获取用户生命体征历史记录。

        对应旧模块:
          - _PostgresUserMemoryStore.get_vital_signs_history(limit)
        """
        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, timestamp, energy, curiosity, satisfaction, stress, mood, is_hibernating, context
                    FROM vital_signs_history
                    WHERE user_id = $1
                    ORDER BY timestamp DESC
                    LIMIT $2
                    """,
                    user_id, limit,
                )
            results = []
            for row in rows:
                r = dict(row)
                if isinstance(r.get("timestamp"), datetime):
                    r["timestamp"] = r["timestamp"].isoformat()
                r["context"] = r.get("context") or {}
                results.append(r)
            return results
        except Exception as e:
            logger.error(f"[MemoryService] get_vital_signs_history 失败: {e}")
            return []

    async def get_self_actions(
        self,
        user_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        获取用户自发行动历史记录。

        对应旧模块:
          - _PostgresUserMemoryStore.get_self_actions(limit)
        """
        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, timestamp, action_type, action_content, energy_cost, satisfaction_gain, status, context
                    FROM self_actions
                    WHERE user_id = $1
                    ORDER BY timestamp DESC
                    LIMIT $2
                    """,
                    user_id, limit,
                )
            results = []
            for row in rows:
                r = dict(row)
                if isinstance(r.get("timestamp"), datetime):
                    r["timestamp"] = r["timestamp"].isoformat()
                r["context"] = r.get("context") or {}
                results.append(r)
            return results
        except Exception as e:
            logger.error(f"[MemoryService] get_self_actions 失败: {e}")
            return []

    # ═══════════════════════════════════════════════════════════════════════
    # 第一步：补齐 9 个缺失的核心方法（全 async，不依赖旧模块）
    # ═══════════════════════════════════════════════════════════════════════

    # ───────────────────────────────────────────────────────────────────
    # 1. update_memory — 对应旧模块 _PostgresUserMemoryStore.update()
    #    旧签名: update(self, mem_id: str, updates: Dict) -> bool
    #    MemoryManager 签名: update(self, user_id, mem_id, updates) -> bool
    # ───────────────────────────────────────────────────────────────────
    async def update_memory(
        self,
        memory_id: str,
        updates: dict[str, Any],
    ) -> bool:
        """
        更新记忆内容/评分/层级/六维评分等字段。

        对应旧模块:
          - _PostgresUserMemoryStore.update(mem_id, updates)
          - MemoryManager.update(user_id, mem_id, updates)
          - Memory.update(mem_id, **kwargs)
        """
        if not updates:
            return False

        allowed_fields = {"content", "context", "scene", "rating", "layer",
                          "mem_type", "expire_at", "value_assessment", "source", "compressed"}
        valid_updates = {k: v for k, v in updates.items() if k in allowed_fields}
        if not valid_updates:
            return False

        # 序列化 content
        if "content" in valid_updates and not isinstance(valid_updates["content"], str):
            valid_updates["content"] = _serialize_content(valid_updates["content"])

        # JSONB 字段序列化
        for field in ("context", "value_assessment"):
            if field in valid_updates and valid_updates[field] is not None:
                valid_updates[field] = json.dumps(valid_updates[field], ensure_ascii=False)

        # 序列化 expire_at（datetime -> ISO 字符串，asyncpg 自动识别）
        if "expire_at" in valid_updates and isinstance(valid_updates["expire_at"], datetime):
            valid_updates["expire_at"] = valid_updates["expire_at"].isoformat()

        set_parts: list[str] = []
        params: list[Any] = []
        param_idx = 0
        for key, value in valid_updates.items():
            param_idx += 1
            set_parts.append(f"{key} = ${param_idx}")
            params.append(value)

        # 追加 updated_at
        param_idx += 1
        set_parts.append("updated_at = CURRENT_TIMESTAMP")

        # WHERE id = $N
        param_idx += 1
        params.append(memory_id)

        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                result = await conn.execute(
                    f"UPDATE memories SET {', '.join(set_parts)} WHERE id = ${param_idx}",
                    *params,
                )
                return "UPDATE 1" in result
        except Exception as e:
            logger.error(f"[MemoryService] update_memory 失败: {e}")
            return False

    # ───────────────────────────────────────────────────────────────────
    # 2. delete_memory — 对应旧模块 _PostgresUserMemoryStore.delete()
    #    旧签名: delete(self, mem_id: str, sync_vector: bool = True) -> bool
    #    MemoryManager 签名: delete(self, user_id, mem_id) -> bool
    # ───────────────────────────────────────────────────────────────────
    async def delete_memory(self, memory_id: str) -> bool:
        """
        删除记忆（按全局唯一 memory_id）。

        对应旧模块:
          - _PostgresUserMemoryStore.delete(mem_id)
          - MemoryManager.delete(user_id, mem_id)
          - Memory.delete(mem_id)
        """
        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM memories WHERE id = $1",
                    memory_id,
                )
                deleted = "DELETE 1" in result
                if deleted:
                    logger.info(f"[MemoryService] 记忆已删除: {memory_id[:8]}...")
                return deleted
        except Exception as e:
            logger.error(f"[MemoryService] delete_memory 失败: {e}")
            return False

    # ───────────────────────────────────────────────────────────────────
    # 3. rate_memory — 六维评分
    #    旧签名: Memory.rate(self, mem_id: str, rating: int)
    #    底层实际调用 update(mem_id, {"rating": rating})
    # ───────────────────────────────────────────────────────────────────
    async def rate_memory(
        self,
        memory_id: str,
        rating: int,
        dimensions: dict[str, int] | None = None,
    ) -> bool:
        """
        对记忆进行评分（基础评分 + 可选六维评分）。

        对应旧模块:
          - Memory.rate(mem_id, rating)
          - _PostgresUserMemoryStore.update(mem_id, {"rating": rating, "value_assessment": {...}})
        """
        updates: dict[str, Any] = {"rating": rating}
        if dimensions:
            default_va = generate_default_value_assessment()
            default_va.update(dimensions)
            dims = {k: v for k, v in default_va.items() if k not in ("overall", "grade")}
            default_va["overall"], default_va["grade"] = calculate_overall_score(dims)
            updates["value_assessment"] = default_va
        return await self.update_memory(memory_id, updates)

    # ───────────────────────────────────────────────────────────────────
    # 4. get_memory_by_id — 对应旧模块 _PostgresUserMemoryStore.get_by_id()
    #    旧签名: get_by_id(self, mem_id: str) -> Optional[Dict]
    # ───────────────────────────────────────────────────────────────────
    async def get_memory_by_id(self, memory_id: str) -> dict[str, Any] | None:
        """
        按全局唯一 ID 查询单条记忆。

        对应旧模块:
          - _PostgresUserMemoryStore.get_by_id(mem_id)
          - MemoryManager.get_by_id(user_id, mem_id)
          - Memory.get_by_ids([mem_id])[0]
        """
        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT id, user_id, layer, mem_type, content, context, scene,
                           rating, source, value_assessment, created_at, expire_at,
                           compressed, creator
                    FROM memories
                    WHERE id = $1
                    """,
                    memory_id,
                )
                if not row:
                    return None
                record = dict(row)
                if isinstance(record.get("value_assessment"), str):
                    try:
                        record["value_assessment"] = json.loads(record["value_assessment"])
                    except Exception:
                        record["value_assessment"] = generate_default_value_assessment()
                record["content"] = _deserialize_content(record.get("content"))
                record["context"] = record.get("context") or {}
                return record
        except Exception as e:
            logger.error(f"[MemoryService] get_memory_by_id 失败: {e}")
            return None

    # ───────────────────────────────────────────────────────────────────
    # 5. get_memories_by_ids — 对应旧模块 _PostgresUserMemoryStore.get_memories_by_ids()
    #    旧签名: get_memories_by_ids(self, mem_ids: List[str], batch_size: int = 500) -> List[Dict]
    # ───────────────────────────────────────────────────────────────────
    async def get_memories_by_ids(
        self,
        memory_ids: list[str],
        batch_size: int = 500,
    ) -> list[dict[str, Any]]:
        """
        批量按 ID 查询记忆，自动分批防止 SQL 占位符溢出。

        对应旧模块:
          - _PostgresUserMemoryStore.get_memories_by_ids(mem_ids)
          - MemoryManager.get_memories_by_ids(user_id, mem_ids)
        """
        if not memory_ids:
            return []
        memory_ids = list(dict.fromkeys(memory_ids))  # 去重保持顺序
        all_results: list[dict[str, Any]] = []

        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                for i in range(0, len(memory_ids), batch_size):
                    batch = memory_ids[i:i + batch_size]
                    placeholders = ",".join([f"${j + 1}" for j in range(len(batch))])
                    rows = await conn.fetch(
                        f"""
                        SELECT id, user_id, layer, mem_type, content, context, scene,
                               rating, source, value_assessment, created_at, expire_at,
                               compressed, creator
                        FROM memories
                        WHERE id IN ({placeholders})
                        """,
                        *batch,
                    )
                    for row in rows:
                        record = dict(row)
                        if isinstance(record.get("value_assessment"), str):
                            try:
                                record["value_assessment"] = json.loads(record["value_assessment"])
                            except Exception:
                                record["value_assessment"] = generate_default_value_assessment()
                        record["content"] = _deserialize_content(record.get("content"))
                        record["context"] = record.get("context") or {}
                        all_results.append(record)
            return all_results
        except Exception as e:
            logger.error(f"[MemoryService] get_memories_by_ids 失败: {e}")
            return []

    # ───────────────────────────────────────────────────────────────────
    # 6. get_memory_stats — 对应旧模块 _PostgresUserMemoryStore.get_stats()
    #    旧签名: get_stats(self) -> Dict[str, Any]
    #    MemoryManager 签名: get_stats(self, user_id: str) -> Dict[str, Any]
    # ───────────────────────────────────────────────────────────────────
    async def get_memory_stats(self, user_id: str) -> dict[str, Any]:
        """
        获取指定用户的记忆统计信息。

        对应旧模块:
          - _PostgresUserMemoryStore.get_stats()
          - MemoryManager.get_stats(user_id)
        """
        stats: dict[str, Any] = {"user_id": user_id}
        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                # 各层数量
                for layer in ALL_LAYERS:
                    cnt = await conn.fetchval(
                        "SELECT COUNT(*) FROM memories WHERE layer = $1 AND user_id = $2",
                        layer, user_id,
                    )
                    stats[layer] = cnt or 0

                # 总数量
                total = await conn.fetchval(
                    "SELECT COUNT(*) FROM memories WHERE user_id = $1", user_id
                )
                stats["total"] = total or 0

                # 过期数量
                expired = await conn.fetchval(
                    "SELECT COUNT(*) FROM memories WHERE expire_at < CURRENT_TIMESTAMP AND user_id = $1",
                    user_id,
                )
                stats["expired"] = expired or 0

                # 压缩数量
                compressed = await conn.fetchval(
                    "SELECT COUNT(*) FROM memories WHERE compressed = 1 AND user_id = $1",
                    user_id,
                )
                stats["compressed"] = compressed or 0

                # 平均评分
                avg_rating = await conn.fetchval(
                    "SELECT AVG(rating) FROM memories WHERE user_id = $1", user_id
                )
                stats["avg_rating"] = round(avg_rating, 2) if avg_rating else 0

                # 按 source 统计
                rows = await conn.fetch(
                    "SELECT source, COUNT(*) as cnt FROM memories WHERE user_id = $1 GROUP BY source",
                    user_id,
                )
                stats["by_source"] = {row["source"] or "system": row["cnt"] for row in rows}

            return stats
        except Exception as e:
            logger.error(f"[MemoryService] get_memory_stats 失败: {e}")
            return {"user_id": user_id, "total": 0}

    # ───────────────────────────────────────────────────────────────────
    # 7. add_batch — 对应旧模块 Memory.add_batch()
    #    旧签名: add_batch(self, items: List[Dict]) -> List[str]
    # ───────────────────────────────────────────────────────────────────
    async def add_batch(self, memories: list[dict[str, Any]]) -> list[str]:
        """
        批量添加记忆。

        对应旧模块:
          - Memory.add_batch(items)
          - MemoryManager.add(user_id, ...) 的批量版本

        每条记忆字典支持字段:
          user_id, layer, mem_type, content, context, scene, rating,
          expire_days, value_assessment, source, creator
        """
        mem_ids: list[str] = []
        for item in memories:
            user_id = item.get("user_id", "default")
            layer = item.get("layer", "short")
            mem_type = item.get("mem_type", "chat")
            content = item.get("content", "")
            context = item.get("context")
            scene = item.get("scene", "")
            rating = item.get("rating", 0)
            expire_days = item.get("expire_days")
            value_assessment = item.get("value_assessment")
            source = item.get("source", "system")
            creator = item.get("creator", "memory_service")

            mem_id = str(uuid.uuid4())
            expire_at = None
            if expire_days:
                expire_at = datetime.now() + timedelta(days=expire_days)

            content_str = _serialize_content(content)
            context_json = json.dumps(context, ensure_ascii=False) if context else None

            if value_assessment is None:
                value_assessment = generate_default_value_assessment()
            else:
                default_va = generate_default_value_assessment()
                default_va.update(value_assessment)
                dims = {k: v for k, v in default_va.items() if k not in ("overall", "grade")}
                default_va["overall"], default_va["grade"] = calculate_overall_score(dims)
                value_assessment = default_va
            va_json = json.dumps(value_assessment, ensure_ascii=False)

            try:
                from core.memory.postgres_pool import AsyncPostgresPool
                pool = await AsyncPostgresPool.get_pool()
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO memories
                        (id, user_id, layer, mem_type, content, context,
                         scene, rating, source, expire_at, value_assessment, creator)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                        """,
                        mem_id, user_id, layer, mem_type, content_str,
                        context_json, scene, rating, source, expire_at, va_json, creator,
                    )
                mem_ids.append(mem_id)
            except Exception as e:
                logger.error(f"[MemoryService] add_batch 单条写入失败: {e}")
                mem_ids.append(mem_id)  # 仍返回 ID，保证上游不崩
        return mem_ids

    # ───────────────────────────────────────────────────────────────────
    # 8. cleanup_expired — 对应旧模块 _PostgresUserMemoryStore.cleanup_expired()
    #    旧签名: cleanup_expired(self, batch_size: int = 100) -> int
    # ───────────────────────────────────────────────────────────────────
    async def cleanup_expired(self) -> int:
        """
        清理所有过期记忆（不区分用户，因为 memory_id 全局唯一）。

        对应旧模块:
          - _PostgresUserMemoryStore.cleanup_expired()
          - MemoryManager._auto_cleanup_expired() 的内部循环
        """
        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                result = await conn.execute(
                    """
                    DELETE FROM memories
                    WHERE expire_at IS NOT NULL
                      AND expire_at < CURRENT_TIMESTAMP
                    """,
                )
                # asyncpg 返回形如 "DELETE 42"
                import re
                m = re.search(r"DELETE\s+(\d+)", result)
                deleted_count = int(m.group(1)) if m else 0
                if deleted_count > 0:
                    logger.info(f"[MemoryService] 清理 {deleted_count} 条过期记忆")
                return deleted_count
        except Exception as e:
            logger.error(f"[MemoryService] cleanup_expired 失败: {e}")
            return 0

    # ───────────────────────────────────────────────────────────────────
    # 9. search_by_dimension — 对应旧模块 _PostgresUserMemoryStore.search_by_dimension()
    #    旧签名: search_by_dimension(self, dimension: str, min_score: float = 3.0, limit: int = 10) -> List[Dict]
    # ───────────────────────────────────────────────────────────────────
    async def search_by_dimension(
        self,
        dimension_filters: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """
        按六维评分维度搜索记忆。

        Args:
            dimension_filters: 必须包含以下键:
                - user_id (str): 用户ID
                - dimension (str): 维度名称，如 "emotional_temperature"
                - min_score (float): 最低分数，默认 3.0
                - limit (int): 返回数量，默认 10

        对应旧模块:
          - _PostgresUserMemoryStore.search_by_dimension(dimension, min_score, limit)
          - MemoryManager 暂无直接对应，供上层 API 使用
        """
        user_id = dimension_filters.get("user_id", "default")
        dimension = dimension_filters.get("dimension")
        if not dimension:
            logger.warning("[MemoryService] search_by_dimension 缺少 dimension 参数")
            return []
        min_score = float(dimension_filters.get("min_score", 3.0))
        limit = int(dimension_filters.get("limit", 10))

        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, user_id, layer, mem_type, content, context, scene,
                           rating, source, value_assessment, created_at
                    FROM memories
                    WHERE user_id = $1
                      AND (value_assessment->>$2)::float >= $3
                      AND (expire_at IS NULL OR expire_at > CURRENT_TIMESTAMP)
                    ORDER BY (value_assessment->>$2)::float DESC
                    LIMIT $4
                    """,
                    user_id, dimension, min_score, limit,
                )
                results = []
                for row in rows:
                    record = dict(row)
                    if isinstance(record.get("value_assessment"), str):
                        try:
                            record["value_assessment"] = json.loads(record["value_assessment"])
                        except Exception:
                            record["value_assessment"] = generate_default_value_assessment()
                    record["content"] = _deserialize_content(record.get("content"))
                    record["context"] = record.get("context") or {}
                    results.append(record)
                return results
        except Exception as e:
            logger.error(f"[MemoryService] search_by_dimension 失败: {e}")
            return []


    # ═══════════════════════════════════════════════════════════════════════
    # 兼容旧版 MemoryManager / Memory 的额外公开方法
    # ═══════════════════════════════════════════════════════════════════════

    async def list_users(self) -> list[str]:
        """列出所有在 memories 表中有记录的用户 ID。"""
        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch("SELECT DISTINCT user_id FROM memories")
            return [r["user_id"] for r in rows if r["user_id"]]
        except Exception as e:
            logger.error(f"[MemoryService] list_users 失败: {e}")
            return []

    async def retrieve_memories(
        self,
        user_id: str,
        query: str = None,
        level: str = None,
        limit: int = None,
        use_semantic: bool = True,
    ) -> list[dict[str, Any]]:
        """
        兼容旧版 Memory.retrieve_memories() 的智能检索接口。
        底层优先使用 VectorStore 语义检索；若语义不可用则回退到 PostgreSQL 文本检索。
        """
        if limit is None:
            if query:
                q_len = len(query)
                limit = 3 if q_len < 10 else (5 if q_len < 30 else 8)
            else:
                limit = 5

        layer = None
        if level:
            level_lower = level.lower()
            if level_lower in ("l1", "working"):
                layer = "working"
            elif level_lower in ("l2", "short"):
                layer = "short"
            elif level_lower in ("l3", "medium"):
                layer = "medium"
            elif level_lower in ("l4", "evolve"):
                layer = "evolve"
            elif level_lower in ("l5", "execution"):
                layer = "execution"

        if use_semantic and query and self.vector_store is not None:
            try:
                ctx = await self.retrieve_context(user_id, query, task_type=None)
                results = []
                # 【P0修复】RetrievedContext 无 items 字段，改为合并 l2/l3/l4
                # SearchResult 字段: id/document/metadata/distance
                for item in ctx.l2 + ctx.l3 + ctx.l4:
                    results.append({
                        "id": item.id,
                        "content": item.document,
                        "layer": item.metadata.get("layer") if item.metadata else None,
                        "mem_type": item.metadata.get("mem_type") if item.metadata else None,
                        "score": 1.0 - (item.distance or 0.0),  # distance 越小越相似，转为 score
                        "metadata": item.metadata,
                    })
                if layer:
                    results = [r for r in results if r.get("layer") == layer]
                return results[:limit]
            except Exception as e:
                logger.warning(f"[MemoryService] 语义检索失败，回退到 PG 文本检索: {e}")

        return await self.query_memories(user_id=user_id, layer=layer, limit=limit)

    async def get_recent_memories(
        self,
        user_id: str,
        hours: int = 24,
        layer: str = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """获取最近 N 小时内的记忆。"""
        since = (datetime.now() - timedelta(hours=hours)).isoformat()
        return await self.query_memories(
            user_id=user_id, layer=layer, limit=limit, filter_dict={"since": since}
        )

    async def get_memories_by_scene(
        self,
        user_id: str,
        scene: str,
        fuzzy_match: bool = False,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """按场景指纹检索记忆。"""
        if fuzzy_match:
            all_mems = await self.query_memories(user_id=user_id, limit=limit * 3)
            return [m for m in all_mems if scene.lower() in str(m.get("scene", "")).lower()][:limit]
        return await self.query_memories(
            user_id=user_id, limit=limit, filter_dict={"scene": scene}
        )

    async def save_vital_signs(
        self,
        user_id: str,
        vital_signs: dict[str, Any],
        context: dict[str, Any] = None,
    ) -> bool:
        """保存生命体征记录到 vital_signs_history 表。"""
        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO vital_signs_history
                    (user_id, energy, curiosity, satisfaction, stress, mood, is_hibernating, context)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    user_id,
                    vital_signs.get("energy", 5.0),
                    vital_signs.get("curiosity", 5.0),
                    vital_signs.get("satisfaction", 5.0),
                    vital_signs.get("stress", 0.0),
                    vital_signs.get("mood", "neutral"),
                    vital_signs.get("is_hibernating", False),
                    json.dumps(context) if context else None,
                )
            return True
        except Exception as e:
            logger.error(f"[MemoryService] save_vital_signs 失败: {e}")
            return False

    async def save_self_action(
        self,
        user_id: str,
        action: dict[str, Any],
    ) -> bool:
        """保存自发行动记录到 self_actions 表。"""
        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO self_actions
                    (user_id, action_type, action_content, energy_cost, satisfaction_gain, status, context)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    user_id,
                    action.get("action_type", "unknown"),
                    action.get("action_content", ""),
                    action.get("energy_cost", 0.0),
                    action.get("satisfaction_gain", 0.0),
                    action.get("status", "completed"),
                    json.dumps(action.get("context")) if action.get("context") else None,
                )
            return True
        except Exception as e:
            logger.error(f"[MemoryService] save_self_action 失败: {e}")
            return False

    # ═══════════════════════════════════════════════════════════════════════════════
    # 全局工厂——延迟初始化，供调用方直接获取 MemoryService 实例
    # ═══════════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════════
# 【P3-6】VectorStore 补偿重试队列
# ═══════════════════════════════════════════════════════════════════════════════

_vector_store_retry_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)  # 【CRIT-2】限制队列大小防内存泄漏
_vector_store_retry_task: asyncio.Task | None = None
_VECTOR_STORE_RETRY_INTERVAL = 30  # 秒
_VECTOR_STORE_RETRY_MAX_ATTEMPTS = 3
_VECTOR_STORE_EMPTY_TIMEOUT_COUNT = 10  # 空队列连续超时多少次后退出 worker


class _VectorStoreRetryItem:
    """补偿重试队列项"""
    def __init__(self, collection: str, text: str, metadata: Any, attempts: int = 0):
        self.collection = collection
        self.text = text
        self.metadata = metadata
        self.attempts = attempts
        self.created_at = datetime.now()


async def _vector_store_retry_worker():
    """后台补偿重试工作线程"""
    empty_timeout_count = 0
    while True:
        try:
            item: _VectorStoreRetryItem = await asyncio.wait_for(
                _vector_store_retry_queue.get(), timeout=_VECTOR_STORE_RETRY_INTERVAL
            )
            empty_timeout_count = 0  # 拿到项，重置空队列计数
        except asyncio.TimeoutError:
            # 【CRIT-2】空队列连续超时次数过多则退出 worker，避免僵尸任务
            empty_timeout_count += 1
            if empty_timeout_count >= _VECTOR_STORE_EMPTY_TIMEOUT_COUNT:
                logger.info(
                    f"[MemoryService] VectorStore 补偿重试 worker 因空队列连续超时 "
                    f"({_VECTOR_STORE_EMPTY_TIMEOUT_COUNT}次) 而优雅退出"
                )
                break
            continue
        except Exception:
            await asyncio.sleep(_VECTOR_STORE_RETRY_INTERVAL)
            continue

        if item.attempts >= _VECTOR_STORE_RETRY_MAX_ATTEMPTS:
            logger.error(
                f"[MemoryService] VectorStore 补偿重试耗尽 ({_VECTOR_STORE_RETRY_MAX_ATTEMPTS}次)，"
                f"放弃 collection={item.collection}, text={item.text[:50]}..."
            )
            continue

        try:
            if _memory_service_instance is not None and _memory_service_instance.vector_store is not None:
                await _memory_service_instance.vector_store.add(
                    item.collection, item.text, item.metadata
                )
                logger.info(
                    f"[MemoryService] VectorStore 补偿重试成功 "
                    f"(第{item.attempts + 1}次): {item.collection}"
                )
            else:
                # 【HIGH-5】MemoryService 未初始化时不消耗重试次数
                logger.debug(
                    f"[MemoryService] VectorStore 尚未就绪，"
                    f"collection={item.collection} 不消耗重试次数，稍后重试"
                )
                await _vector_store_retry_queue.put(item)
        except Exception as e:
            logger.warning(
                f"[MemoryService] VectorStore 补偿重试失败 "
                f"(第{item.attempts + 1}次): {e}"
            )
            item.attempts += 1
            await _vector_store_retry_queue.put(item)


def _enqueue_vector_store_retry(collection: str, text: str, metadata: Any) -> None:
    """将失败的 VectorStore 写入加入补偿重试队列"""
    global _vector_store_retry_task
    item = _VectorStoreRetryItem(collection, text, metadata)
    try:
        _vector_store_retry_queue.put_nowait(item)
    except asyncio.QueueFull:
        logger.error("[MemoryService] VectorStore 补偿队列已满，丢弃最旧项")
        return

    # 启动后台重试任务（如果尚未启动）
    if _vector_store_retry_task is None or _vector_store_retry_task.done():
        try:
            loop = asyncio.get_running_loop()
            _vector_store_retry_task = loop.create_task(_vector_store_retry_worker())
            logger.info("[MemoryService] VectorStore 补偿重试 worker 已启动")
        except RuntimeError:
            pass


_memory_service_instance: MemoryService | None = None
_memory_service_lock = asyncio.Lock()


async def get_memory_service() -> MemoryService:
    """
    获取全局 MemoryService 实例（延迟初始化）。

    初始化策略：
    1. PG 连接池复用 AsyncPostgresPool（与 AsyncMemory 共享）
    2. VectorStore 复用 vector_memory.py 的 embedder + collections
    """
    global _memory_service_instance
    if _memory_service_instance is not None:
        return _memory_service_instance

    async with _memory_service_lock:
        if _memory_service_instance is not None:
            return _memory_service_instance

        from core.memory.postgres_pool import AsyncPostgresPool
        pg_pool = await AsyncPostgresPool.get_pool()

    # VectorStore 延迟构造：首次调用时才从旧架构提取组件
    # 使用一个轻量包装器，在第一次 add/search 时才真正初始化 collections
    class _LazyVectorStore(VectorStore):
        """延迟初始化 VectorStore——避免模块导入时触发 heavy init"""

        def __init__(self):
            # 不调用 super().__init__，延迟到首次访问
            self._initialized = False
            self._real_store: VectorStore | None = None
            self._embedder = None  # 【P0修复】兼容 VectorStore.get_embedding_function() 同步调用
            self._init_retry_count = 0
            self._init_max_retries = 3
            self._init_retry_delay = 5
            self._next_retry_time = 0.0
            self._init_lock: asyncio.Lock | None = None

        async def _ensure_init(self):
            if self._initialized:
                return
            import asyncio
            import time
            now = time.time()
            if now < self._next_retry_time:
                return
            if self._init_lock is None:
                self._init_lock = asyncio.Lock()
            async with self._init_lock:
                if self._initialized:
                    return
                try:
                    from pathlib import Path

                    import torch
                    from sentence_transformers import SentenceTransformer

                    from core.config import config

                    # 查找本地模型路径（复用 vector_memory.py 的搜索路径，但不依赖该模块）
                    base_dir = Path(__file__).parent.parent.parent
                    possible_paths = [
                        base_dir / "checkpoints" / "hf_cache" / "models--sentence-transformers--all-MiniLM-L6-v2" / "snapshots" / "c9745ed1d9f207416be6d2e6f8de32d1f16199bf",
                        base_dir / "core" / "checkpoints" / "hf_cache" / "models--sentence-transformers--all-MiniLM-L6-v2" / "snapshots" / "c9745ed1d9f207416be6d2e6f8de32d1f16199bf",
                    ]
                    config_path = config.get("vector.local_model_path")
                    model_path = str(config_path) if config_path else None
                    for p in possible_paths:
                        if p.exists():
                            model_path = str(p).replace('\\', '/')
                            break

                    if not model_path:
                        raise FileNotFoundError("本地嵌入模型未找到于任何已知路径")

                    # CPU 密集型模型加载，使用 to_thread 隔离
                    # 【P0修复】PyTorch 2.7 默认 mmap=True 导致 meta tensor 拷贝失败，
                    # 临时 patch torch.load 强制 mmap=False（与 vision/realtime_detector.py 保持一致）
                    start_time = time.monotonic()
                    _orig_torch_load = torch.load
                    def _safe_torch_load(*args, **kwargs):
                        kwargs.setdefault("mmap", False)
                        return _orig_torch_load(*args, **kwargs)
                    torch.load = _safe_torch_load
                    try:
                        embedder = await asyncio.to_thread(
                            SentenceTransformer,
                            model_path,
                            device="cpu",
                            trust_remote_code=False,
                            local_files_only=True,
                            model_kwargs={"low_cpu_mem_usage": False},
                        )
                    finally:
                        torch.load = _orig_torch_load

                    elapsed = time.monotonic() - start_time
                    logger.info(f"[MemoryService] VectorStore 嵌入模型加载成功，耗时 {elapsed:.1f} 秒")

                    self._real_store = VectorStore(
                        embedder=embedder,
                        host=config.get("chromadb_host", "127.0.0.1"),
                        port=config.get("chromadb_port", 8000),
                    )
                    self._embedder = embedder  # 【P0修复】同步暴露 embedder，供 get_embedding_function() 同步调用
                    self._init_retry_count = 0
                    self._initialized = True
                except Exception as e:
                    self._init_retry_count += 1
                    if self._init_retry_count < self._init_max_retries:
                        self._next_retry_time = time.time() + self._init_retry_delay
                        logger.info(
                            f"[MemoryService] VectorStore 初始化失败，将在 {self._init_retry_delay} 秒后重试"
                            f"（第 {self._init_retry_count}/{self._init_max_retries} 次）: {e}"
                        )
                    else:
                        self._initialized = True
                        logger.error(
                            f"[MemoryService] VectorStore 初始化永久失败，向量功能已禁用: {e}"
                        )

        def get_embedding_function(self):
            """【P0修复】同步获取 embedder，若未初始化则返回 None（Consciousness 会降级到零向量）"""
            if self._real_store is not None:
                return self._real_store.get_embedding_function()
            return self._embedder

        async def add(self, collection: str, text: str, metadata: MemoryMetadata) -> str:
            await self._ensure_init()
            if self._real_store is None:
                raise RuntimeError("VectorStore 未初始化")
            return await self._real_store.add(collection, text, metadata)

        async def search(self, collection: str, query: str, filters=None, limit: int = 5):
            await self._ensure_init()
            if self._real_store is None:
                raise RuntimeError("VectorStore 未初始化")
            return await self._real_store.search(collection, query, filters, limit)

        async def search_multi(self, query: str, collections: list, n_results: int = 5):
            await self._ensure_init()
            if self._real_store is None:
                raise RuntimeError("VectorStore 未初始化")
            return await self._real_store.search_multi(query, collections, n_results)

        async def upsert(self, collection: str, doc_id: str, text: str, metadata: Any) -> str:
            await self._ensure_init()
            if self._real_store is None:
                raise RuntimeError("VectorStore 未初始化")
            return await self._real_store.upsert(collection, doc_id, text, metadata)

        async def is_available(self) -> bool:
            await self._ensure_init()
            if self._real_store is None:
                return False
            return await self._real_store.is_available()

    _memory_service_instance = MemoryService(
        pg_pool=pg_pool,
        vector_store=_LazyVectorStore(),
    )
    return _memory_service_instance
