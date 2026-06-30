#!/usr/bin/env python3
"""
记忆关联系统 - P2-1任务实现
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【功能概述】
  实现记忆之间的关联关系管理，让AI能够联想相关记忆。

【关联类型】
  - entity:    实体关联（同一人、地点、概念）
  - temporal:  时间关联（同时发生、先后顺序）
  - scene:     场景关联（同一场景、相似上下文）

【核心特性】
  1. 自动关联创建：添加新记忆时自动分析并建立关联
  2. 实体提取：从记忆内容中提取关键实体
  3. 关联评分：0-1之间的关联强度分数
  4. 双向查询：支持从任意一端查询关联记忆

【使用示例】
  manager = MemoryAssociationManager()
  manager.create_association("mem_001", "mem_002", "entity", 0.85,
                          {"entity": "张三", "type": "person"})
  related = manager.find_associated_memories("mem_001", relation_type="entity")
"""
import json
import logging
import re
import threading
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# 导入PostgreSQL连接池
from core.db.connection_pool import POSTGRES_AVAILABLE, PostgresConnectionPool

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# P0修复: 安全连接归还辅助函数（防御空指针）
# ═══════════════════════════════════════════════════════════════════

def safe_return_connection(conn) -> None:
    """
    安全归还连接到连接池 - P0修复

    防御性包装函数，确保即使在极端情况下也不会引发空指针异常。
    用于所有finally块中的连接归还。

    Args:
        conn: 数据库连接对象，可能为None
    """
    # 多重防御检查
    if conn is None:
        return

    # 检查PostgresConnectionPool类是否存在且可用
    try:
        if PostgresConnectionPool is None:
            return

        # 调用类的return_connection方法
        PostgresConnectionPool.return_connection(conn)  # P0修复: 修复递归调用
    except Exception as e:
        # 记录但不抛出，避免在finally块中引发新异常
        logger.warning(f"[safe_return_connection] 归还连接失败: {e}")
        logger.debug(f"[safe_return_connection] 调用栈: {traceback.format_exc()}")


# ═══════════════════════════════════════════════════════════════════
# 数据类定义
# ═══════════════════════════════════════════════════════════════════

@dataclass
class MemoryAssociation:
    """记忆关联数据类

    Attributes:
        id: 关联记录ID（数据库生成）
        source_mem_id: 源记忆ID
        target_mem_id: 目标记忆ID
        user_id: 用户ID（用户隔离）
        relation_type: 关联类型（entity/temporal/scene）
        relation_score: 关联强度分数（0-1）
        relation_data: 关联详细数据（JSONB）
        created_at: 创建时间
    """
    source_mem_id: str
    target_mem_id: str
    user_id: str
    relation_type: str
    relation_score: float = 0.0
    relation_data: dict[str, Any] = field(default_factory=dict)
    id: int | None = None
    created_at: datetime | None = None

    def __post_init__(self):
        """数据验证"""
        if self.relation_score < 0 or self.relation_score > 1:
            raise ValueError(f"关联分数必须在0-1之间，当前值: {self.relation_score}")

        valid_types = ["entity", "temporal", "scene", "similarity"]
        if self.relation_type not in valid_types:
            raise ValueError(f"无效的关联类型: {self.relation_type}，必须是 {valid_types}")


@dataclass
class ExtractedEntity:
    """提取的实体数据类

    Attributes:
        text: 实体文本
        entity_type: 实体类型（person/location/organization/concept/time等）
        position: 在原文中的位置
        confidence: 提取置信度
    """
    text: str
    entity_type: str
    position: int = 0
    confidence: float = 0.8


# ═══════════════════════════════════════════════════════════════════
# 记忆关联管理器（单例模式）
# ═══════════════════════════════════════════════════════════════════

class MemoryAssociationManager:
    """记忆关联管理器 - 单例模式

    管理记忆之间的关联关系，支持：
    1. 创建/删除关联
    2. 查询关联记忆
    3. 自动创建关联
    4. 实体提取

    使用示例：
        manager = MemoryAssociationManager()
        # 创建关联
        manager.create_association("mem_001", "mem_002", "entity", 0.9)
        # 查询关联
        results = manager.find_associated_memories("mem_001")
    """

    _instance = None
    _lock = threading.Lock()
    _initialized = False

    def __new__(cls):
        """单例模式实现"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """初始化管理器"""
        if MemoryAssociationManager._initialized:
            return

        with self._lock:
            if MemoryAssociationManager._initialized:
                return

            self._rw_lock = threading.RLock()
            self._ensure_tables_exist()
            MemoryAssociationManager._initialized = True
            logger.info("[MemoryAssociationManager] 记忆关联管理器初始化完成")

    def _ensure_tables_exist(self):
        """确保关联表存在"""
        if not POSTGRES_AVAILABLE:
            logger.warning("[MemoryAssociationManager] PostgreSQL不可用，跳过表初始化")
            return

        conn = None
        try:
            conn = PostgresConnectionPool.get_connection()
            with conn.cursor() as c:
                # 创建关联表
                c.execute('''
                    CREATE TABLE IF NOT EXISTS memory_associations (
                        id SERIAL PRIMARY KEY,
                        source_mem_id VARCHAR(64) NOT NULL,
                        target_mem_id VARCHAR(64) NOT NULL,
                        user_id VARCHAR(64) NOT NULL,
                        relation_type VARCHAR(50) NOT NULL,
                        relation_score FLOAT DEFAULT 0.0,
                        relation_data JSONB DEFAULT '{}',
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(source_mem_id, target_mem_id, relation_type)
                    )
                ''')

                # 创建索引
                c.execute('CREATE INDEX IF NOT EXISTS idx_assoc_source ON memory_associations(source_mem_id)')
                c.execute('CREATE INDEX IF NOT EXISTS idx_assoc_target ON memory_associations(target_mem_id)')
                c.execute('CREATE INDEX IF NOT EXISTS idx_assoc_user ON memory_associations(user_id)')
                c.execute('CREATE INDEX IF NOT EXISTS idx_assoc_type_score ON memory_associations(relation_type, relation_score)')
                c.execute('CREATE INDEX IF NOT EXISTS idx_assoc_created ON memory_associations(created_at)')

                conn.commit()
                logger.debug("[MemoryAssociationManager] 关联表初始化完成")
        except Exception as e:
            logger.error(f"[MemoryAssociationManager] 表初始化失败: {e}")
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                safe_return_connection(conn)  # P0修复: 使用安全函数

    # ═══════════════════════════════════════════════════════════════════
    # 核心CRUD操作
    # ═══════════════════════════════════════════════════════════════════

    def create_association(
        self,
        source_mem_id: str,
        target_mem_id: str,
        user_id: str,
        relation_type: str,
        relation_score: float = 0.5,
        relation_data: dict[str, Any] | None = None
    ) -> bool:
        """创建记忆关联

        Args:
            source_mem_id: 源记忆ID
            target_mem_id: 目标记忆ID
            user_id: 用户ID
            relation_type: 关联类型（entity/temporal/scene/similarity）
            relation_score: 关联强度（0-1）
            relation_data: 关联详细数据

        Returns:
            bool: 是否创建成功
        """
        if not POSTGRES_AVAILABLE:
            logger.warning("[MemoryAssociationManager] PostgreSQL不可用，无法创建关联")
            return False

        # 防止自关联
        if source_mem_id == target_mem_id:
            logger.debug(f"[MemoryAssociationManager] 忽略自关联: {source_mem_id}")
            return False

        # 数据验证
        valid_types = ["entity", "temporal", "scene", "similarity"]
        if relation_type not in valid_types:
            logger.warning(f"[MemoryAssociationManager] 无效的关联类型: {relation_type}")
            return False

        relation_score = max(0.0, min(1.0, relation_score))
        relation_data = relation_data or {}

        conn = None
        try:
            conn = PostgresConnectionPool.get_connection()
            with self._rw_lock, conn.cursor() as c:
                # 使用UPSERT语义（ON CONFLICT DO UPDATE）
                    c.execute('''
                        INSERT INTO memory_associations
                        (source_mem_id, target_mem_id, user_id, relation_type,
                         relation_score, relation_data)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (source_mem_id, target_mem_id, relation_type)
                        DO UPDATE SET
                            relation_score = EXCLUDED.relation_score,
                            relation_data = EXCLUDED.relation_data,
                            created_at = CURRENT_TIMESTAMP
                    ''', (source_mem_id, target_mem_id, user_id, relation_type,
                          relation_score, json.dumps(relation_data)))
                    conn.commit()
                    logger.debug(f"[MemoryAssociationManager] 关联创建成功: {source_mem_id} -> {target_mem_id} ({relation_type})")
                    return True
        except Exception as e:
            logger.error(f"[MemoryAssociationManager] 创建关联失败: {e}")
            if conn:
                conn.rollback()
            return False
        finally:
            if conn:
                safe_return_connection(conn)  # P0修复: 使用安全函数


    def delete_memory_associations(self, mem_id: str) -> int:
        """删除记忆的所有关联（级联删除）

        Args:
            mem_id: 记忆ID

        Returns:
            int: 删除的关联数量
        """
        if not POSTGRES_AVAILABLE:
            return 0

        conn = None
        try:
            conn = PostgresConnectionPool.get_connection()
            with self._rw_lock, conn.cursor() as c:
                # 删除作为source或target的所有关联
                c.execute('''
                        DELETE FROM memory_associations
                        WHERE source_mem_id = %s OR target_mem_id = %s
                    ''', (mem_id, mem_id))
                conn.commit()
                deleted_count = c.rowcount
                if deleted_count > 0:
                    logger.debug(f"[MemoryAssociationManager] 级联删除 {deleted_count} 条关联: {mem_id}")
                return deleted_count
        except Exception as e:
            logger.error(f"[MemoryAssociationManager] 级联删除关联失败: {e}")
            if conn:
                conn.rollback()
            return 0
        finally:
            if conn:
                safe_return_connection(conn)  # P0修复: 使用安全函数

    async def delete_memory_associations_async(self, mem_id: str) -> int:
        """异步删除记忆的所有关联（级联删除，原生asyncpg）"""
        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                result = await conn.execute('''
                    DELETE FROM memory_associations
                    WHERE source_mem_id = $1 OR target_mem_id = $1
                ''', mem_id)
                # asyncpg execute 返回形如 "DELETE N" 的字符串
                deleted_count = int(result.split()[-1]) if "DELETE" in result else 0
                if deleted_count > 0:
                    logger.debug(f"[MemoryAssociationManager] 异步级联删除 {deleted_count} 条关联: {mem_id}")
                return deleted_count
        except Exception as e:
            logger.error(f"[MemoryAssociationManager] 异步级联删除关联失败: {e}")
            return 0

    async def find_associated_memories(
        self,
        mem_id: str,
        user_id: str | None = None,
        relation_type: str | None = None,
        min_score: float = 0.0,
        limit: int = 50
    ) -> list[dict[str, Any]]:
        """查询关联的记忆（异步版本）

        支持双向查询：返回与指定记忆关联的所有记忆（无论作为source还是target）

        Args:
            mem_id: 记忆ID
            user_id: 用户ID（可选）
            relation_type: 关联类型过滤（可选）
            min_score: 最低关联分数
            limit: 返回数量限制

        Returns:
            List[Dict]: 关联记忆列表，包含关联信息
                [
                    {
                        "mem_id": "关联的记忆ID",
                        "relation_type": "关联类型",
                        "score": 0.85,
                        "data": {},
                        "created_at": "..."
                    }
                ]
        """
        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                conditions = ["(source_mem_id = $1 OR target_mem_id = $1)", "relation_score >= $2"]
                params = [mem_id, min_score]
                idx = 3
                if user_id:
                    conditions.append(f"user_id = ${idx}")
                    params.append(user_id)
                    idx += 1
                if relation_type:
                    conditions.append(f"relation_type = ${idx}")
                    params.append(relation_type)
                    idx += 1

                sql = f'''
                    SELECT source_mem_id, target_mem_id, relation_type, relation_score, relation_data, created_at
                    FROM memory_associations
                    WHERE {" AND ".join(conditions)}
                    ORDER BY relation_score DESC
                    LIMIT ${idx}
                '''
                params.append(limit)
                rows = await conn.fetch(sql, *params)

                results = []
                for row in rows:
                    target = row["target_mem_id"] if row["source_mem_id"] == mem_id else row["source_mem_id"]
                    results.append({
                        "mem_id": target,
                        "relation_type": row["relation_type"],
                        "score": row["relation_score"],
                        "data": row["relation_data"] if isinstance(row["relation_data"], dict) else json.loads(row["relation_data"]),
                        "created_at": row["created_at"].isoformat() if row["created_at"] else None
                    })
                return results
        except Exception as e:
            logger.error(f"[MemoryAssociationManager] 查询关联记忆失败: {e}")
            return []


    # ═══════════════════════════════════════════════════════════════════
    # 自动关联创建
    # ═══════════════════════════════════════════════════════════════════

    def auto_create_associations(
        self,
        new_mem_id: str,
        user_id: str,
        content: dict[str, Any],
        scene: str | None = None,
        existing_memories: list[dict] | None = None
    ) -> list[dict[str, Any]]:
        """自动为新记忆创建关联

        分析新记忆的内容，自动与现有记忆建立关联。

        Args:
            new_mem_id: 新记忆ID
            user_id: 用户ID
            content: 记忆内容
            scene: 场景指纹
            existing_memories: 待比较的现有记忆列表（可选，默认查询最近100条）

        Returns:
            List[Dict]: 创建的关联列表
        """
        if not POSTGRES_AVAILABLE:
            return []

        created_associations = []

        try:
            # 1. 提取实体
            entities = self._extract_entities(content)

            # 2. 获取现有记忆进行对比
            if existing_memories is None:
                existing_memories = self._get_recent_memories(user_id, limit=100)

            # 3. 基于实体创建关联
            entity_associations = self._create_entity_associations(
                new_mem_id, user_id, entities, existing_memories
            )
            created_associations.extend(entity_associations)

            # 4. 基于时间创建关联
            temporal_associations = self._create_temporal_associations(
                new_mem_id, user_id, existing_memories
            )
            created_associations.extend(temporal_associations)

            # 5. 基于场景创建关联
            if scene:
                scene_associations = self._create_scene_associations(
                    new_mem_id, user_id, scene, existing_memories
                )
                created_associations.extend(scene_associations)

            logger.info(f"[MemoryAssociationManager] 自动创建 {len(created_associations)} 条关联: {new_mem_id}")
            return created_associations

        except Exception as e:
            logger.error(f"[MemoryAssociationManager] 自动创建关联失败: {e}")
            return []

    async def auto_create_associations_async(
        self,
        new_mem_id: str,
        user_id: str,
        content: dict[str, Any],
        scene: str | None = None,
        existing_memories: list[dict] | None = None
    ) -> list[dict[str, Any]]:
        """异步自动为新记忆创建关联（原生asyncpg）"""
        created_associations = []

        try:
            # 1. 提取实体（纯计算，无需异步）
            entities = self._extract_entities(content)

            # 2. 异步获取现有记忆进行对比
            if existing_memories is None:
                existing_memories = await self._get_recent_memories_async(user_id, limit=100)

            # 3. 基于实体异步创建关联
            entity_texts = {e.text.lower() for e in entities}
            for mem in existing_memories:
                if mem["id"] == new_mem_id:
                    continue
                existing_entities = self._extract_entities(mem["content"])
                existing_texts = {e.text.lower() for e in existing_entities}
                common_entities = entity_texts & existing_texts
                if common_entities:
                    score = min(0.9, 0.5 + len(common_entities) * 0.1)
                    success = await self.create_association_async(
                        source_mem_id=new_mem_id,
                        target_mem_id=mem["id"],
                        user_id=user_id,
                        relation_type="entity",
                        relation_score=score,
                        relation_data={
                            "common_entities": list(common_entities),
                            "entity_count": len(common_entities)
                        }
                    )
                    if success:
                        created_associations.append({
                            "target_mem_id": mem["id"],
                            "relation_type": "entity",
                            "relation_score": score,
                            "common_entities": list(common_entities)
                        })

            # 4. 基于时间异步创建关联
            recent_mems = [m for m in existing_memories if m["id"] != new_mem_id][:5]
            for idx, mem in enumerate(recent_mems):
                score = max(0.3, 0.7 - idx * 0.1)
                success = await self.create_association_async(
                    source_mem_id=new_mem_id,
                    target_mem_id=mem["id"],
                    user_id=user_id,
                    relation_type="temporal",
                    relation_score=score,
                    relation_data={"time_proximity": "consecutive", "order": idx}
                )
                if success:
                    created_associations.append({
                        "target_mem_id": mem["id"],
                        "relation_type": "temporal",
                        "relation_score": score
                    })

            # 5. 基于场景异步创建关联
            if scene:
                for mem in existing_memories:
                    if mem["id"] == new_mem_id:
                        continue
                    if mem.get("scene") == scene:
                        success = await self.create_association_async(
                            source_mem_id=new_mem_id,
                            target_mem_id=mem["id"],
                            user_id=user_id,
                            relation_type="scene",
                            relation_score=0.9,
                            relation_data={"scene": scene, "match_type": "exact"}
                        )
                        if success:
                            created_associations.append({
                                "target_mem_id": mem["id"],
                                "relation_type": "scene",
                                "relation_score": 0.9,
                                "scene": scene
                            })

            logger.info(f"[MemoryAssociationManager] 异步自动创建 {len(created_associations)} 条关联: {new_mem_id}")
            return created_associations

        except Exception as e:
            logger.error(f"[MemoryAssociationManager] 异步自动创建关联失败: {e}")
            return []

    def _get_recent_memories(
        self,
        user_id: str,
        limit: int = 100,
        hours: int = 168  # 默认7天
    ) -> list[dict]:
        """获取最近的记忆

        Args:
            user_id: 用户ID
            limit: 返回数量限制
            hours: 时间范围（小时）

        Returns:
            List[Dict]: 记忆列表
        """
        conn = None
        try:
            conn = PostgresConnectionPool.get_connection()
            with conn.cursor() as c:
                c.execute('''
                    SELECT id, content, scene, created_at
                    FROM memories
                    WHERE user_id = %s
                    AND created_at > CURRENT_TIMESTAMP - INTERVAL '%s hours'
                    ORDER BY created_at DESC
                    LIMIT %s
                ''', (user_id, hours, limit))

                rows = c.fetchall()
                results = []
                for row in rows:
                    mem_id, content, scene, created_at = row
                    # 解析内容
                    try:
                        content_dict = json.loads(content) if isinstance(content, str) else content
                    except KeyboardInterrupt:
                        raise  # 重新抛出，允许正常退出
                    except Exception as e:
                        logger.error(f"[MemoryAssociationManager] JSON解析失败: {e}", exc_info=True)
                        content_dict = {"text": str(content)}

                    results.append({
                        "id": mem_id,
                        "content": content_dict,
                        "scene": scene,
                        "created_at": created_at.isoformat() if created_at else None
                    })
                return results
        except Exception as e:
            logger.error(f"[MemoryAssociationManager] 获取最近记忆失败: {e}")
            return []
        finally:
            if conn:
                safe_return_connection(conn)  # P0修复: 使用安全函数

    async def _get_recent_memories_async(
        self,
        user_id: str,
        limit: int = 100,
        hours: int = 168
    ) -> list[dict]:
        """异步获取最近的记忆（原生asyncpg）"""
        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch('''
                    SELECT id, content, scene, created_at
                    FROM memories
                    WHERE user_id = $1
                    AND created_at > CURRENT_TIMESTAMP - ($2 || ' hours')::interval
                    ORDER BY created_at DESC
                    LIMIT $3
                ''', user_id, hours, limit)

                results = []
                for row in rows:
                    content = row["content"]
                    try:
                        content_dict = json.loads(content) if isinstance(content, str) else content
                    except Exception as e:
                        logger.error(f"[MemoryAssociationManager] JSON解析失败: {e}", exc_info=True)
                        content_dict = {"text": str(content)}

                    results.append({
                        "id": row["id"],
                        "content": content_dict,
                        "scene": row["scene"],
                        "created_at": row["created_at"].isoformat() if row["created_at"] else None
                    })
                return results
        except Exception as e:
            logger.error(f"[MemoryAssociationManager] 异步获取最近记忆失败: {e}")
            return []

    def _create_entity_associations(
        self,
        new_mem_id: str,
        user_id: str,
        entities: list[ExtractedEntity],
        existing_memories: list[dict]
    ) -> list[dict[str, Any]]:
        """基于实体创建关联

        Args:
            new_mem_id: 新记忆ID
            user_id: 用户ID
            entities: 提取的实体列表
            existing_memories: 现有记忆列表

        Returns:
            List[Dict]: 创建的关联列表
        """
        created = []
        entity_texts = {e.text.lower() for e in entities}

        for mem in existing_memories:
            if mem["id"] == new_mem_id:
                continue

            # 提取现有记忆的实体
            existing_entities = self._extract_entities(mem["content"])
            existing_texts = {e.text.lower() for e in existing_entities}

            # 计算共同实体
            common_entities = entity_texts & existing_texts

            if common_entities:
                # 根据共同实体数量计算关联分数
                score = min(0.9, 0.5 + len(common_entities) * 0.1)

                # 创建关联
                success = self.create_association(
                    source_mem_id=new_mem_id,
                    target_mem_id=mem["id"],
                    user_id=user_id,
                    relation_type="entity",
                    relation_score=score,
                    relation_data={
                        "common_entities": list(common_entities),
                        "entity_count": len(common_entities)
                    }
                )

                if success:
                    created.append({
                        "target_mem_id": mem["id"],
                        "relation_type": "entity",
                        "relation_score": score,
                        "common_entities": list(common_entities)
                    })

        return created

    def _create_temporal_associations(
        self,
        new_mem_id: str,
        user_id: str,
        existing_memories: list[dict]
    ) -> list[dict[str, Any]]:
        """基于时间创建关联

        将新记忆与最近创建的记忆建立时间关联。

        Args:
            new_mem_id: 新记忆ID
            user_id: 用户ID
            existing_memories: 现有记忆列表

        Returns:
            List[Dict]: 创建的关联列表
        """
        created = []

        # 只与最近的5条记忆建立时间关联
        recent_mems = [m for m in existing_memories if m["id"] != new_mem_id][:5]

        for idx, mem in enumerate(recent_mems):
            # 距离越远分数越低
            score = max(0.3, 0.7 - idx * 0.1)

            success = self.create_association(
                source_mem_id=new_mem_id,
                target_mem_id=mem["id"],
                user_id=user_id,
                relation_type="temporal",
                relation_score=score,
                relation_data={
                    "time_proximity": "consecutive",
                    "order": idx
                }
            )

            if success:
                created.append({
                    "target_mem_id": mem["id"],
                    "relation_type": "temporal",
                    "relation_score": score
                })

        return created

    def _create_scene_associations(
        self,
        new_mem_id: str,
        user_id: str,
        scene: str,
        existing_memories: list[dict]
    ) -> list[dict[str, Any]]:
        """基于场景创建关联

        Args:
            new_mem_id: 新记忆ID
            user_id: 用户ID
            scene: 场景指纹
            existing_memories: 现有记忆列表

        Returns:
            List[Dict]: 创建的关联列表
        """
        created = []

        for mem in existing_memories:
            if mem["id"] == new_mem_id:
                continue

            # 完全匹配场景
            if mem.get("scene") == scene:
                success = self.create_association(
                    source_mem_id=new_mem_id,
                    target_mem_id=mem["id"],
                    user_id=user_id,
                    relation_type="scene",
                    relation_score=0.9,
                    relation_data={
                        "scene": scene,
                        "match_type": "exact"
                    }
                )

                if success:
                    created.append({
                        "target_mem_id": mem["id"],
                        "relation_type": "scene",
                        "relation_score": 0.9,
                        "scene": scene
                    })

        return created

    # ═══════════════════════════════════════════════════════════════════
    # 实体提取
    # ═══════════════════════════════════════════════════════════════════

    def _extract_entities(self, content: str | dict[str, Any]) -> list[ExtractedEntity]:
        """从内容中提取实体

        使用简单的规则方法提取人名、地名、组织名等实体。

        Args:
            content: 记忆内容（字符串或字典）

        Returns:
            List[ExtractedEntity]: 提取的实体列表
        """
        entities = []

        # 统一转换为字符串
        if isinstance(content, dict):
            text_parts = []
            if "text" in content:
                text_parts.append(content["text"])
            if "summary" in content:
                text_parts.append(content["summary"])
            if "title" in content:
                text_parts.append(content["title"])
            text = " ".join(text_parts)
        else:
            text = str(content)

        if not text:
            return entities

        # 人名提取（简单的中文姓名匹配）
        # 匹配2-4个汉字，通常是人名
        person_pattern = r'[\u4e00-\u9fa5]{2,4}(?:先生|女士|老师|医生|教授|博士)'
        for match in re.finditer(person_pattern, text):
            entities.append(ExtractedEntity(
                text=match.group(),
                entity_type="person",
                position=match.start(),
                confidence=0.7
            ))

        # 地名提取
        location_keywords = ["北京", "上海", "广州", "深圳", "杭州", "南京", "成都", "武汉",
                           "中国", "美国", "日本", "学校", "公司", "医院", "公园"]
        for keyword in location_keywords:
            for match in re.finditer(keyword, text):
                entities.append(ExtractedEntity(
                    text=keyword,
                    entity_type="location",
                    position=match.start(),
                    confidence=0.6
                ))

        # 时间提取
        time_pattern = r'(\d{4}年|\d{1,2}月|\d{1,2}日|昨天|今天|明天|上午|下午|晚上)'
        for match in re.finditer(time_pattern, text):
            entities.append(ExtractedEntity(
                text=match.group(),
                entity_type="time",
                position=match.start(),
                confidence=0.8
            ))

        # 概念提取（引号中的内容）
        concept_pattern = r'["\']([^"\']+)["\']'
        for match in re.finditer(concept_pattern, text):
            entities.append(ExtractedEntity(
                text=match.group(1),
                entity_type="concept",
                position=match.start(),
                confidence=0.75
            ))

        # 去重（基于文本和位置）
        seen = set()
        unique_entities = []
        for e in entities:
            key = (e.text.lower(), e.entity_type)
            if key not in seen:
                seen.add(key)
                unique_entities.append(e)

        return unique_entities

    def extract_entities_from_memory(
        self,
        content: str | dict[str, Any]
    ) -> list[dict[str, Any]]:
        """公开接口：从记忆中提取实体

        Args:
            content: 记忆内容

        Returns:
            List[Dict]: 实体字典列表
        """
        entities = self._extract_entities(content)
        return [
            {
                "text": e.text,
                "type": e.entity_type,
                "position": e.position,
                "confidence": e.confidence
            }
            for e in entities
        ]

    # ═══════════════════════════════════════════════════════════════════
    # 高级查询功能
    # ═══════════════════════════════════════════════════════════════════




    # ═══════════════════════════════════════════════════════════════════════════
    # 异步 API（P1-Asyncify：原生 asyncpg，避免阻塞事件循环）
    # ═══════════════════════════════════════════════════════════════════════════

    async def create_association_async(
        self,
        source_mem_id: str,
        target_mem_id: str,
        user_id: str,
        relation_type: str,
        relation_score: float = 0.5,
        relation_data: dict[str, Any] | None = None
    ) -> bool:
        """异步创建记忆关联"""
        if source_mem_id == target_mem_id:
            return False
        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                await conn.execute('''
                    INSERT INTO memory_associations
                    (source_mem_id, target_mem_id, user_id, relation_type, relation_score, relation_data)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (source_mem_id, target_mem_id, relation_type) DO UPDATE SET
                        relation_score = EXCLUDED.relation_score,
                        relation_data = EXCLUDED.relation_data,
                        created_at = CURRENT_TIMESTAMP
                ''', (
                    source_mem_id, target_mem_id, user_id, relation_type,
                    relation_score, json.dumps(relation_data or {})
                ))
            return True
        except Exception as e:
            logger.error(f"[MemoryAssociationManager] 异步创建关联失败: {e}")
            return False






# ═══════════════════════════════════════════════════════════════════
# 全局实例
# ═══════════════════════════════════════════════════════════════════

memory_association_manager = None

try:
    memory_association_manager = MemoryAssociationManager()
    print("【成功】 Memory Association system initialized successfully")
except Exception as e:
    print(f"[ERROR] Failed to initialize memory association system: {e}")
    memory_association_manager = None


# =============================================================================
# 总结性注释
# =============================================================================
#
# 【文件角色】
# 本文件（memory_associations.py）是 SiliconBase V5 系统的"记忆关联"核心模块，
# 负责管理记忆之间的关系，实现AI的记忆联想能力。
#
# 【核心类说明】
# 1. MemoryAssociation: 关联数据类
#    - 封装单条关联关系的所有属性
#    - 支持数据验证
#
# 2. ExtractedEntity: 实体数据类
#    - 封装提取的实体信息
#    - 支持置信度评估
#
# 3. MemoryAssociationManager: 关联管理器（单例模式）
#    - CRUD操作：创建、删除、查询关联
#    - 自动关联：分析内容自动建立关联
#    - 实体提取：从文本中提取关键实体
#    - 关联链：查找多层关联关系
#
# 【关联类型】
# - entity:    实体关联（共同的人、地点、概念）
# - temporal:  时间关联（时序关系）
# - scene:     场景关联（同一场景）
# - similarity: 相似度关联（预留）
#
# 【数据库表结构】
# 表名: memory_associations
# - id: SERIAL 主键
# - source_mem_id: VARCHAR(64) 源记忆ID
# - target_mem_id: VARCHAR(64) 目标记忆ID
# - user_id: VARCHAR(64) 用户ID（隔离）
# - relation_type: VARCHAR(50) 关联类型
# - relation_score: FLOAT 关联强度（0-1）
# - relation_data: JSONB 关联详细数据
# - created_at: TIMESTAMP 创建时间
#
# 【索引设计】
# - idx_assoc_source: 源记忆ID索引
# - idx_assoc_target: 目标记忆ID索引
# - idx_assoc_user: 用户ID索引
# - idx_assoc_type_score: 类型+分数复合索引
#
# 【使用场景】
# - 添加新记忆时自动建立关联
# - AI联想相关记忆进行推理
# - 记忆图谱构建
# - 实体驱动的记忆检索
#
# =============================================================================
