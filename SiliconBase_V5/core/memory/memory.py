#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""
⚠️ DEPRECATED (2026-05-09):
本模块已废弃。所有业务逻辑已迁移至 `core/memory/memory_service.py`。

保留目的：
  - 向后兼容：部分深层调用链尚未完成异步化迁移，仍通过本模块的同步接口调用。
  - 基础设施：PostgresConnectionPool、generate_default_value_assessment 等纯函数
    仍被 `core/memory/memory_manager.py` 等模块引用，待基础设施彻底搬迁后删除。

新入口：
  - 异步业务：`from core.memory.memory_service import get_memory_service`
  - 异步连接池：`from core.memory.postgres_pool import AsyncPostgresPool`

请勿在本模块新增功能，仅接受最小化的兼容修复。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

记忆中心 V6.5 - 五层记忆系统 + PostgreSQL + 六维评分（已废弃）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【五层架构】
  L1: 工作记忆 (working) → 当前会话上下文，即时丢弃
  L2: 短期记忆 (short)   → 1天过期，原始对话记录
  L3: 中期记忆 (medium)  → 高价值经验，失败教训
  L4: 长期记忆 (evolve)  → 成功经验，进化知识
  L5: 执行记忆 (execution) → 工具执行记录，性能统计

【用户隔离】
  - 通过PostgreSQL的user_id字段实现多租户隔离
  - 所有查询自动过滤user_id

【六维评分】
  - emotional_temperature: 情感温度 (1-5)
  - ethical_safety: 伦理安全 (1-5)
  - self_growth: 自我成长 (1-5)
  - execution_effectiveness: 执行成效 (1-5)
  - sustainability: 存续保障 (1-5)
  - inspiration_innovation: 灵感创新 (1-5)

【2026-02-27 重构】
  - 从SQLite迁移至PostgreSQL
  - 新增六维评分字段 (value_assessment JSONB)
  - 支持向量检索维度加权
"""
import asyncio  # 导入异步IO模块
import json  # 导入JSON模块，用于序列化和反序列化
import logging  # 导入日志模块
import threading  # 导入线程模块，用于并发控制
import uuid  # 导入UUID模块，用于生成唯一标识符
from dataclasses import dataclass  # 导入数据类装饰器
from datetime import datetime, timedelta  # 从datetime导入日期时间和时间差类
from enum import Enum  # 导入枚举类
from typing import Any  # 导入类型注解工具

from core.memory.memory_service import get_memory_service  # 新向量存储服务
from core.memory.postgres_pool import AsyncPostgresPool

logger = logging.getLogger(__name__)

# P0-基础设施迁移：从 core/db 重新导出，保持向后兼容
from core.db.connection_pool import (
    Json,
    PostgresConnectionPool,
    RealDictCursor,
    init_postgres_tables,
    safe_return_connection,
)

# ═══════════════════════════════════════════════════════════════════
# AsyncPG 兼容层（P1-Asyncify）
# ═══════════════════════════════════════════════════════════════════
try:
    import asyncpg
except ImportError:
    asyncpg = None


async def _execute_async(
    sql: str,
    params: list[Any] | None = None,
    fetch: bool = False,
    fetchone: bool = False,
    fetchval: bool = False,
) -> Any:
    """
    使用 asyncpg 连接池执行 SQL。

    Args:
        sql: 使用 $1, $2... 占位符的 SQL 语句（asyncpg 语法）
        params: 查询参数列表
        fetch: 为 True 时返回所有行（list[dict]）
        fetchone: 为 True 时返回单行（dict | None）
        fetchval: 为 True 时返回单个标量值

    Raises:
        RuntimeError: 若 asyncpg 未安装或连接池未初始化
    """
    if asyncpg is None:
        raise RuntimeError(
            "[memory.py] asyncpg 未安装。异步内存操作需要 asyncpg。 "
            "请运行: pip install asyncpg"
        )
    from core.memory.postgres_pool import AsyncPostgresPool
    pool = await AsyncPostgresPool.get_pool()
    async with pool.acquire() as conn:
        if fetchval:
            return await conn.fetchval(sql, *(params or []))
        if fetchone:
            row = await conn.fetchrow(sql, *(params or []))
            return dict(row) if row else None
        if fetch:
            rows = await conn.fetch(sql, *(params or []))
            return [dict(r) for r in rows]
        return await conn.execute(sql, *(params or []))


# ═══════════════════════════════════════════════════════════════════
# 异常定义
# ═══════════════════════════════════════════════════════════════════

class MemoryRetrievalError(Exception):
    """记忆检索错误 - 当记忆查询失败时抛出"""
    pass


class MemoryStorageError(Exception):
    """记忆存储错误 - 当记忆保存失败时抛出"""
    pass


# 导入MemorySource枚举
try:
    from core.memory.memory_source import DEFAULT_MEMORY_SOURCE, MemorySource, validate_source
except ImportError:
    class MemorySource(str, Enum):
        """记忆来源枚举（fallback定义）"""
        AI = "ai"
        SYSTEM = "system"
        USER = "user"
        REFLECTION = "reflection"
        EVOLUTION = "evolution"

    def validate_source(source):
        """验证source的fallback函数"""
        if isinstance(source, MemorySource):
            return source
        if isinstance(source, str):
            try:
                return MemorySource(source.lower())
            except ValueError:
                return MemorySource.SYSTEM
        return MemorySource.SYSTEM

    DEFAULT_MEMORY_SOURCE = MemorySource.SYSTEM

# 读写锁依赖（使用依赖管理工具）  # 注释
from ..utils.dependency_utils import rwlock_dep  # 从依赖工具导入读写锁

# P0-005修复: 确保rwlock永远不会为None，即使模块属性获取失败也使用FallbackRWLock  # 修复说明
rwlock = rwlock_dep.get("rwlock") if rwlock_dep.available else rwlock_dep.fallback_class  # 获取读写锁
if rwlock is None:  # 如果仍然为None
    rwlock = rwlock_dep.fallback_class  # 使用FallbackRWLock

# 尝试导入配置，如不可用则使用默认  # 注释
config = None  # 初始化配置为None
try:  # 尝试导入配置
    from core.config import config  # 从core.config导入配置
except ImportError:  # 如果导入失败
    class _DummyConfig:  # 定义虚拟配置类
        def get(self, key, default=None):  # 定义get方法
            return default  # 返回默认值
    config = _DummyConfig()  # 创建虚拟配置实例

# 五层记忆定义  # 五层记忆常量定义
LAYER_WORKING = "working"       # L1: 工作记忆  # L1层常量
LAYER_SHORT = "short"           # L2: 短期记忆  # L2层常量
LAYER_MEDIUM = "medium"         # L3: 中期记忆  # L3层常量
LAYER_EVOLVE = "evolve"         # L4: 长期记忆  # L4层常量
LAYER_EXECUTION = "execution"   # L5: 执行记忆  # L5层常量

ALL_LAYERS = [LAYER_WORKING, LAYER_SHORT, LAYER_MEDIUM, LAYER_EVOLVE, LAYER_EXECUTION]  # 所有层级列表

# 六维评分默认值 - 与value_system_v2.py保持一致  # 六维评分权重定义
DEFAULT_DIMENSION_WEIGHTS = {  # 默认维度权重字典
    "emotional_temperature": 0.25,    # 25% - 最高权重  # 情感温度权重
    "ethical_safety": 0.20,           # 20%  # 伦理安全权重
    "self_growth": 0.20,              # 20%  # 自我成长权重
    "execution_effectiveness": 0.15,  # 15%  # 执行成效权重
    "sustainability": 0.15,           # 15%  # 存续保障权重
    "inspiration_innovation": 0.05    # 5% - 最低权重  # 灵感创新权重
}


def generate_default_value_assessment() -> dict[str, Any]:  # 定义生成默认六维评分函数
    """生成默认六维评分（C级）"""  # 函数文档字符串
    return {  # 返回默认评分字典
        "emotional_temperature": 3,  # 情感温度默认值3
        "ethical_safety": 3,  # 伦理安全默认值3
        "self_growth": 3,  # 自我成长默认值3
        "execution_effectiveness": 3,  # 执行成效默认值3
        "sustainability": 3,  # 存续保障默认值3
        "inspiration_innovation": 3,  # 灵感创新默认值3
        "overall": 3.0,  # 综合得分默认值3.0
        "grade": "C"  # 等级默认值C
    }


def calculate_overall_score(dimensions: dict[str, int]) -> tuple[float, str]:  # 定义计算综合得分函数
    """计算综合得分和等级"""  # 函数文档字符串
    if not dimensions:  # 如果维度字典为空
        return 3.0, "C"  # 返回默认得分和等级

    weighted_sum = sum(  # 计算加权总和
        dimensions.get(dim, 3) * weight  # 获取维度值乘以权重
        for dim, weight in DEFAULT_DIMENSION_WEIGHTS.items()  # 遍历所有维度和权重
    )

    # 确定等级  # 等级判断注释
    if weighted_sum >= 4.5:  # 如果加权总和>=4.5
        grade = "S"  # S级
    elif weighted_sum >= 4.0:  # 如果加权总和>=4.0
        grade = "A"  # A级
    elif weighted_sum >= 3.5:  # 如果加权总和>=3.5
        grade = "B"  # B级
    elif weighted_sum >= 2.5:  # 如果加权总和>=2.5
        grade = "C"  # C级
    else:  # 否则
        grade = "D"  # D级

    return round(weighted_sum, 2), grade  # 返回四舍五入的得分和等级


@dataclass  # 使用数据类装饰器
class MemoryQuery:  # 定义记忆查询参数数据类
    """记忆查询参数数据类"""  # 类文档字符串
    scene: str | None = None  # 场景指纹（可选）
    mem_type: str | None = None  # 记忆类型（可选）
    layer: str | None = None  # 记忆层级（可选）
    limit: int = 10  # 返回数量限制，默认10
    min_rating: int = -1  # 最低评分，默认-1（无限制）
    since: str | None = None  # 开始时间（可选）
    until: str | None = None  # 结束时间（可选）
    min_overall_score: float | None = None  # 最低综合评分（可选）
    dimension_weights: dict[str, float] | None = None  # 维度权重（可选）
    sources: list[str] | None = None  # 来源筛选（Agent-4新增）

    def to_sql_conditions(self) -> tuple[str, list]:  # 定义转换为SQL条件方法
        """转换为SQL条件和参数"""  # 方法文档字符串
        conditions = ["1=1"]  # 初始化条件列表，1=1用于简化AND连接
        params = []  # 初始化参数列表

        if self.scene:  # 如果指定了场景
            conditions.append("scene = %s")  # 添加场景条件
            params.append(self.scene)  # 添加场景参数
        if self.mem_type:  # 如果指定了记忆类型
            conditions.append("mem_type = %s")  # 添加类型条件
            params.append(self.mem_type)  # 添加类型参数
        if self.layer:  # 如果指定了层级
            conditions.append("layer = %s")  # 添加层级条件
            params.append(self.layer)  # 添加层级参数
        if self.min_rating > -1:  # 如果指定了最低评分
            conditions.append("rating >= %s")  # 添加评分条件
            params.append(self.min_rating)  # 添加评分参数
        if self.since:  # 如果指定了开始时间
            conditions.append("created_at >= %s")  # 添加开始时间条件
            params.append(self.since)  # 添加开始时间参数
        if self.until:  # 如果指定了结束时间
            conditions.append("created_at <= %s")  # 添加结束时间条件
            params.append(self.until)  # 添加结束时间参数

        # 新增: 最低综合评分  # 最低综合评分条件注释
        if self.min_overall_score is not None:  # 如果指定了最低综合评分
            conditions.append("(value_assessment->>'overall')::float >= %s")  # 添加JSONB字段条件
            params.append(self.min_overall_score)  # 添加综合评分参数

        # Agent-4: 新增source筛选支持
        if self.sources:  # 如果指定了来源筛选
            if len(self.sources) == 1:  # 单个来源
                conditions.append("source = %s")
                params.append(self.sources[0])
            else:  # 多个来源
                placeholders = ','.join(['%s'] * len(self.sources))
                conditions.append(f"source IN ({placeholders})")
                params.extend(self.sources)

        return " AND ".join(conditions), params  # 返回条件字符串和参数列表


# ═══════════════════════════════════════════════════════════════════  # 分隔线：SQLite降级已移除
# SQLite 降级模式已移除 - PostgreSQL 强制使用  # 注释
# ═══════════════════════════════════════════════════════════════════  # 分隔线

# SQLiteMemoryStore 类已移除 - 项目必须使用 PostgreSQL  # 类移除注释


class UserMemoryStore:  # 定义用户记忆存储类
    """单个用户的记忆存储 - 强制使用 PostgreSQL"""  # 类文档字符串

    def __init__(self, user_id: str):  # 初始化方法
        """  # 方法文档字符串开始
        初始化用户记忆存储  # 方法标题

        Args:  # 参数说明
            user_id: 用户唯一标识  # 参数
        """  # 方法文档字符串结束
        self.user_id = user_id  # 设置用户ID
        self._backend = _PostgresUserMemoryStore(user_id)  # 创建PostgreSQL后端实例
        logger.debug(f"[UserMemoryStore] 用户 {user_id} 的记忆存储初始化完成 (PostgreSQL)")  # 记录调试日志

    def __getattr__(self, name):  # 定义属性代理方法
        """代理所有方法调用到后端"""  # 方法文档字符串
        return getattr(self._backend, name)  # 获取后端属性


class _PostgresUserMemoryStore:  # 定义PostgreSQL用户记忆存储实现类
    """PostgreSQL用户记忆存储实现（原UserMemoryStore代码）"""  # 类文档字符串

    def __init__(self, user_id: str):  # 初始化方法
        self.user_id = user_id  # 设置用户ID
        self._rw_lock = rwlock.RWLockFair()  # 创建公平读写锁
        init_postgres_tables()  # 初始化PostgreSQL表

    def _get_timestamp(self, days: int = 0) -> str:  # 定义获取时间戳方法
        """获取时间戳"""  # 方法文档字符串
        if days:  # 如果指定了天数
            return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")  # 返回未来时间
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")  # 返回当前时间

    async def add(self, layer: str, content: dict, expire_days: int | None = None,
            mem_type: str = "general", context: dict = None, scene: str = "",
            rating: int = 0, sync_vector: bool = True,
            value_assessment: dict = None,
            source: str = "system",
            creator: str = "system") -> str:
        """  # 方法文档字符串开始
        添加记忆（性能优化：使用PostgreSQL行级锁替代全局应用锁）  # 方法标题

        Args:  # 参数说明
            layer: 记忆层级 (L1-L5)  # 参数1
            content: 记忆内容  # 参数2
            expire_days: 过期天数  # 参数3
            mem_type: 记忆类型  # 参数4
            context: 上下文信息  # 参数5
            scene: 场景指纹  # 参数6
            rating: 评分 (0-10)  # 参数7
            sync_vector: 是否同步到向量记忆  # 参数8
            value_assessment: 六维评分（如未提供则自动生成）  # 参数9
            source: 记忆来源（如未提供则使用默认值system）  # 参数10（Agent-4新增）
            creator: 创建者（'AI', 'user', 'system'）  # 参数11（Agent-1新增）

        Returns:  # 返回值说明
            记忆ID  # 返回类型

        【性能优化说明】
        - 使用数据库行级锁（通过事务隔离）替代应用层全局写锁
        - 写操作不阻塞读操作，提升并发性能
        - 保留事务回滚机制确保数据一致性
        """  # 方法文档字符串结束
        import time
        start_time = time.time()

        mem_id = str(uuid.uuid4())  # 生成UUID作为记忆ID

        # 设置过期时间  # 过期时间设置注释
        expire_at = None  # 初始化过期时间为None
        if layer in (LAYER_SHORT, LAYER_WORKING):  # 如果是短期记忆
            expire_days = expire_days or 1  # 默认1天
        if expire_days:  # 如果有过期天数
            expire_at = self._get_timestamp(expire_days)  # 计算过期时间

        # 序列化内容  # 内容序列化注释
        content_str = json.dumps(content, ensure_ascii=False) if not isinstance(content, str) else content  # 转为JSON字符串

        # 六维评分处理  # 六维评分处理注释
        if value_assessment is None:  # 如果未提供评分
            value_assessment = generate_default_value_assessment()  # 生成默认评分
        else:  # 如果提供了评分
            # 确保所有维度存在  # 确保维度完整注释
            default_va = generate_default_value_assessment()  # 获取默认评分
            default_va.update(value_assessment)  # 更新评分
            # 重新计算综合得分和等级  # 重新计算注释
            dimensions = {k: v for k, v in default_va.items() if k not in ['overall', 'grade']}  # 提取维度
            default_va['overall'], default_va['grade'] = calculate_overall_score(dimensions)  # 计算综合得分
            value_assessment = default_va  # 设置评分

        # 【P1-Asyncify】使用 asyncpg 真异步执行（替代 psycopg2 SYNC-BLOCK）
        try:
            await _execute_async(
                """
                INSERT INTO memories
                (id, user_id, layer, mem_type, content, context,
                 scene, rating, source, expire_at, value_assessment, creator)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                """,
                [
                    mem_id, self.user_id, layer, mem_type, content_str,
                    json.dumps(context, ensure_ascii=False) if context else None,
                    scene, rating, source, expire_at,
                    json.dumps(value_assessment, ensure_ascii=False),
                    creator,
                ],
            )
            elapsed = time.time() - start_time
            logger.info(f"[UserMemoryStore] 记忆添加成功: {mem_id[:8]}... (耗时 {elapsed*1000:.2f}ms)")
        except Exception as e:
            logger.error(f"[UserMemoryStore] 用户 {self.user_id} 记忆添加失败: {e}", exc_info=True)
            raise MemoryStorageError(f"插入记忆失败: {e}") from e

        # 同步到向量记忆层  # 向量同步注释
        if sync_vector:  # 如果需要同步向量
            await self._sync_to_vector(layer, mem_type, content, context, mem_id, rating, value_assessment)  # 同步到向量

        # P2-1: 自动创建记忆关联
        try:
            from core.memory.memory_associations import memory_association_manager
            if memory_association_manager:
                full_content = content if isinstance(content, dict) else {"text": str(content)}
                # 原生异步创建关联（不阻塞主流程）
                asyncio.create_task(
                    memory_association_manager.auto_create_associations_async(
                        mem_id, self.user_id, full_content, scene
                    )
                )
        except Exception as e:
            logger.error(f"[SILENT_FAILURE_BLOCKED] 自动创建记忆关联失败: {e}")

        return mem_id  # 返回记忆ID



    async def query(self, layer: str | None = None, filters: dict | None = None,
              limit: int = 10, dimension_weights: dict[str, float] | None = None,
              query_text: str | None = None,
              use_semantic_search: bool = True,
              semantic_weight: float = 0.6) -> list[dict]:  # 参数，返回记忆列表
        """
        【P0修复】查询记忆，支持语义向量检索和维度加权排序

        Args:
            layer: 记忆层级过滤
            filters: 额外过滤条件
            limit: 返回数量限制
            dimension_weights: 维度权重，用于结果排序
            query_text: 【新增】查询文本，用于语义向量检索
            use_semantic_search: 【新增】是否使用语义检索（默认True）
            semantic_weight: 【新增】语义相似度权重（0-1），默认0.6

        Returns:
            记忆记录列表（按相关性排序）
        """
        # ═════════════════════════════════════════════════════════════════════════════
        # 【P0修复】语义向量检索集成
        # 当提供query_text时，同时使用向量相似度检索
        # ═════════════════════════════════════════════════════════════════════════════
        semantic_results = {}
        if use_semantic_search and query_text:
            try:
                async def _semantic_search():
                    ms = await get_memory_service()
                    results = {}
                    # 将layer映射到对应的集合名称
                    collection_map = {
                        "short": "chat",
                        "medium": "knowledge",
                        "long": "knowledge",
                        "evolve": "experience",
                        "working": "chat"
                    }

                    # 确定要搜索的集合
                    collections_to_search = []
                    if layer and layer in collection_map:
                        collections_to_search = [collection_map[layer]]
                    else:
                        # 搜索所有相关集合
                        collections_to_search = ["knowledge", "chat", "experience"]

                    # 执行向量检索
                    for collection in collections_to_search:
                        try:
                            vector_results = await ms.vector_store.search(
                                collection=collection,
                                query=query_text,
                                limit=min(limit * 2, 20)  # 获取更多候选结果
                            )

                            # 保存语义相似度分数
                            for result in vector_results:
                                mem_id = result.id
                                results[mem_id] = {
                                    "similarity": 1.0 - (result.distance or 0.0),
                                    "document": result.document,
                                    "metadata": result.metadata
                                }
                        except Exception as e:
                            logger.debug(f"[UserMemoryStore] 向量检索失败({collection}): {e}")

                    return results

                semantic_results = await _semantic_search()
                logger.info(f"[UserMemoryStore] 语义检索找到 {len(semantic_results)} 条相关记忆")
            except Exception as e:
                logger.warning(f"[UserMemoryStore] 语义检索初始化失败: {e}")

        # ═════════════════════════════════════════════════════════════════════════════
        # 原有的SQL查询逻辑 —— 【P1-Asyncify】迁移至 asyncpg
        # ═════════════════════════════════════════════════════════════════════════════
        try:
            conditions = ["user_id = $1", "(expire_at IS NULL OR expire_at > CURRENT_TIMESTAMP)"]
            params: list[Any] = [self.user_id]
            param_idx = 2

            if layer:
                conditions.append(f"layer = ${param_idx}")
                params.append(layer)
                param_idx += 1

            if filters:
                if filters.get("mem_type"):
                    conditions.append(f"mem_type = ${param_idx}")
                    params.append(filters["mem_type"])
                    param_idx += 1
                if filters.get("scene"):
                    conditions.append(f"scene = ${param_idx}")
                    params.append(filters["scene"])
                    param_idx += 1
                if filters.get("min_rating"):
                    conditions.append(f"rating >= ${param_idx}")
                    params.append(filters["min_rating"])
                    param_idx += 1
                if filters.get("since"):
                    conditions.append(f"created_at >= ${param_idx}")
                    params.append(filters["since"])
                    param_idx += 1
                if filters.get("min_overall_score"):
                    conditions.append(f"(value_assessment->>'overall')::float >= ${param_idx}")
                    params.append(filters["min_overall_score"])
                    param_idx += 1
                if filters.get("session_id"):
                    session_id_val = filters["session_id"]
                    if isinstance(session_id_val, str) and session_id_val.startswith("!"):
                        conditions.append(f"(content::jsonb->>'session_id' IS NULL OR content::jsonb->>'session_id' != ${param_idx})")
                        params.append(session_id_val[1:])
                    else:
                        conditions.append(f"content::jsonb->>'session_id' = ${param_idx}")
                        params.append(session_id_val)
                    param_idx += 1

            # 【P0修复】如果语义检索有结果，优先查询这些ID
            if semantic_results:
                memory_ids = list(semantic_results.keys())
                # 限制IN子句的数量
                if len(memory_ids) <= 100:
                    placeholders = ','.join([f'${param_idx + j}' for j in range(len(memory_ids))])
                    conditions.append(f"id IN ({placeholders})")
                    params.extend(memory_ids)
                    param_idx += len(memory_ids)

            effective_limit = max(limit * 3, 50) if semantic_results else limit

            where_clause = " AND ".join(conditions)
            sql = f"""
                SELECT id, layer, mem_type, content, context, scene,
                       rating, source, value_assessment, created_at, expire_at, compressed
                FROM memories
                WHERE {where_clause}
                ORDER BY rating DESC, created_at DESC
                LIMIT ${param_idx}
            """
            params.append(effective_limit)

            rows = await _execute_async(sql, params, fetch=True)

            results = []
            for r in rows:
                try:
                    raw_content = r['content']
                    if raw_content is None:
                        content = None
                    elif isinstance(raw_content, str):
                        content = json.loads(raw_content)
                    else:
                        content = raw_content
                except (json.JSONDecodeError, TypeError):
                    content = r['content']

                # 【P0修复】计算语义相似度分数
                semantic_score = 0.0
                if r['id'] in semantic_results:
                    semantic_score = semantic_results[r['id']]["similarity"]

                results.append({
                    "id": r['id'],
                    "layer": r['layer'],
                    "mem_type": r['mem_type'],
                    "content": content,
                    "context": r['context'] if r['context'] else {},
                    "scene": r['scene'],
                    "rating": r['rating'],
                    "source": r.get('source', 'system'),
                    "value_assessment": r['value_assessment'] if r['value_assessment'] else generate_default_value_assessment(),
                    "created_at": r['created_at'].isoformat() if r['created_at'] else None,
                    "expire_at": r['expire_at'].isoformat() if r['expire_at'] else None,
                    "compressed": bool(r['compressed']),
                    "_semantic_score": semantic_score  # 内部使用，不返回给调用方
                })

            # ═════════════════════════════════════════════════════════════════════════════
            # 【P0修复】混合排序：语义相似度 + 维度权重 + 时间/评分
            # ═════════════════════════════════════════════════════════════════════════════
            if semantic_results or dimension_weights:
                results = self._hybrid_sort(results, dimension_weights, semantic_weight)

            # 限制返回数量
            results = results[:limit]

            # 清理内部字段
            for r in results:
                r.pop("_semantic_score", None)

            return results

        except Exception as e:
            logger.error(f"[UserMemoryStore] 查询记忆失败: {e}")
            return []

    def _hybrid_sort(self, results: list[dict],
                     dimension_weights: dict[str, float] | None,
                     semantic_weight: float) -> list[dict]:
        """
        【P0修复】混合排序：语义相似度 + 维度权重 + 基础评分

        排序公式：
        final_score = semantic_weight * semantic_score +
                     (1 - semantic_weight) * (base_score + dimension_bonus)
        """
        def calc_score(mem):
            # 语义相似度分数 (0-1)
            semantic_score = mem.get("_semantic_score", 0)

            # 基础分数（评分归一化到0-1）
            base_score = min(mem.get("rating", 0) / 10.0, 1.0)

            # 维度权重加分
            dimension_bonus = 0.0
            if dimension_weights:
                va = mem.get("value_assessment", {})
                weighted_sum = sum(va.get(dim, 3) * weight for dim, weight in dimension_weights.items())
                max_possible = sum(5 * weight for weight in dimension_weights.values())  # 最大可能值
                dimension_bonus = (weighted_sum / max_possible - 0.6) * 0.2 if max_possible > 0 else 0

            # 时效性加分（越新越高，最多+0.1）
            try:
                created = datetime.fromisoformat(mem.get("created_at", "").replace("Z", "+00:00"))
                days_old = (datetime.now() - created).days
                recency_bonus = max(0, 0.1 - days_old * 0.001)  # 每天衰减0.001
            except (ValueError, TypeError, AttributeError) as e:
                logger.error(f"[Memory] 日期解析失败，使用默认值0: {e}")
                recency_bonus = 0

            # 综合分数
            non_semantic_score = base_score + dimension_bonus + recency_bonus
            final_score = semantic_weight * semantic_score + (1 - semantic_weight) * non_semantic_score

            return final_score

        return sorted(results, key=calc_score, reverse=True)



    def _sort_by_dimension_weights(self, results: list[dict],   # 定义按维度权重排序方法
                                    dimension_weights: dict[str, float]) -> list[dict]:  # 参数，返回排序后列表
        """按维度加权分数排序"""  # 方法文档字符串
        def calc_weighted_score(mem):  # 定义计算加权分数内部函数
            va = mem.get('value_assessment', {})  # 获取六维评分
            score = 0.0  # 初始化分数
            for dim, weight in dimension_weights.items():  # 遍历维度权重
                score += va.get(dim, 3) * weight  # 累加加权分数
            return score  # 返回分数

        return sorted(results, key=calc_weighted_score, reverse=True)  # 按分数降序排序

    async def update(self, mem_id: str, updates: dict) -> bool:
        """
        更新记忆——异步版本（【P1-Asyncify】使用 asyncpg）。

        Args:
            mem_id: 记忆ID
            updates: 要更新的字段

        Returns:
            是否成功
        """
        allowed_fields = ["content", "context", "scene", "rating", "expire_at",
                         "compressed", "value_assessment", "source"]
        valid_updates = {k: v for k, v in updates.items() if k in allowed_fields}

        if not valid_updates:
            return False

        # 序列化内容
        if "content" in valid_updates and not isinstance(valid_updates["content"], str):
            valid_updates["content"] = json.dumps(valid_updates["content"], ensure_ascii=False)

        # 处理JSONB字段（asyncpg 需要字符串而非 psycopg2 的 Json 对象）
        jsonb_fields = ["context", "value_assessment"]
        for field in jsonb_fields:
            if field in valid_updates and valid_updates[field] is not None:
                valid_updates[field] = json.dumps(valid_updates[field], ensure_ascii=False)

        try:
            set_parts = []
            params = []
            for idx, (k, v) in enumerate(valid_updates.items(), start=1):
                params.append(v)
                set_parts.append(f"{k} = ${idx}")
            set_clause = ", ".join(set_parts)
            sql = f"""
                UPDATE memories
                SET {set_clause}, updated_at = CURRENT_TIMESTAMP
                WHERE id = ${len(params) + 1} AND user_id = ${len(params) + 2}
                RETURNING id
            """
            params.extend([mem_id, self.user_id])
            row = await _execute_async(sql, params, fetchone=True)
            return row is not None
        except Exception as e:
            logger.error(f"[UserMemoryStore] 更新记忆失败: {e}")
            return False

    def update_sync(self, mem_id: str, updates: dict) -> bool:
        """
        更新记忆——同步包装器（向后兼容）。
        【P1-Asyncify】底层调用 update() 的同步桥接。
        优先使用异步 update() 以避免阻塞事件循环。

        ⚠️ 注意：此方法仅在无事件循环运行时可用。
        在异步上下文中请直接 await self.update(mem_id, updates)。
        """
        try:
            asyncio.get_running_loop()
            # 已有事件循环，不能调用 asyncio.run，返回协程对象让调用方处理
            raise RuntimeError(
                "update_sync() 不能在已有事件循环中调用。"
                "请在异步上下文中使用 await self.update(mem_id, updates)"
            )
        except RuntimeError as e:
            if "no running event loop" in str(e):
                return asyncio.run(self.update(mem_id, updates))
            raise

    async def delete(self, mem_id: str, sync_vector: bool = True) -> bool:
        """
        删除记忆（支持级联删除向量）——【P1-Asyncify】使用 asyncpg。

        Args:
            mem_id: 记忆ID
            sync_vector: 是否同步删除向量库

        Returns:
            是否成功
        """
        # 1. 先获取记忆信息（用于向量删除）
        memory_info = None
        if sync_vector:
            memory_info = await self.get_by_id_async(mem_id)

        deleted = False
        try:
            row = await _execute_async(
                "DELETE FROM memories WHERE id = $1 AND user_id = $2 RETURNING id",
                [mem_id, self.user_id],
                fetchone=True,
            )
            deleted = row is not None
            if deleted:
                logger.info(f"[UserMemoryStore] 记忆已删除: {mem_id[:8]}...")
        except Exception as e:
            logger.error(f"[UserMemoryStore] 删除记忆失败: {e}")
            return False

        # 3. 级联删除向量库
        if deleted and sync_vector and memory_info:
            await self._delete_from_vector(mem_id, memory_info)

        return deleted



    async def _delete_from_vector(self, mem_id: str, memory_info: dict = None):  # 定义从向量库删除方法
        """从向量库删除对应向量，使用保存的vector_id（P0-002修复）"""  # 方法文档字符串
        try:  # 尝试删除
            async def _do_delete():
                ms = await get_memory_service()

                # P0-002修复：优先使用保存的向量ID进行删除
                vector_id = None
                if memory_info:
                    context = memory_info.get("context", {})
                    vector_id = context.get("_vector_id")

                if vector_id:
                    # 使用向量ID直接删除（准确）
                    parts = vector_id.split('_')
                    collection = parts[0] if parts and parts[0] in ["experience", "knowledge", "chat"] else "knowledge"
                    success = await ms.vector_store.delete(collection, [vector_id])
                    if success:
                        logger.debug(f"[UserMemoryStore] 向量级联删除完成: {vector_id[:20]}...")
                    else:
                        logger.warning(f"[UserMemoryStore] 向量删除失败: {vector_id[:20]}...")
                else:
                    # 降级方案：尝试使用mem_id和collection删除（向后兼容）
                    logger.warning(f"[UserMemoryStore] 未找到向量ID映射，尝试降级删除: {mem_id[:8]}...")
                    mem_type = memory_info.get("mem_type", "knowledge") if memory_info else "knowledge"
                    collection_map = {
                        "experience": "experience",
                        "knowledge": "knowledge",
                        "chat": "chat",
                        "execution": "execution"
                    }
                    collection = collection_map.get(mem_type, "knowledge")

                    try:
                        # 尝试使用mem_id作为vector_id删除（旧数据兼容）
                        await ms.vector_store.delete(collection, [mem_id])
                        logger.debug(f"[UserMemoryStore] 降级删除完成: {mem_id[:8]}...")
                    except Exception as e:
                        logger.warning(f"[UserMemoryStore] 降级删除失败: {e}")

            await _do_delete()
        except Exception as e:
            logger.warning(f"[UserMemoryStore] 向量级联删除异常: {e}")

    async def get_by_id_async(self, mem_id: str) -> dict | None:
        """根据ID异步获取单条记忆（asyncpg）"""
        try:
            row = await _execute_async(
                """
                SELECT id, layer, mem_type, content, context, scene,
                       rating, source, value_assessment, created_at, expire_at, compressed, creator
                FROM memories WHERE id = $1 AND user_id = $2
                """,
                [mem_id, self.user_id],
                fetchone=True,
            )
            if not row:
                return None
            try:
                content = json.loads(row['content'])
            except (json.JSONDecodeError, TypeError):
                content = row['content']
            return {
                "id": row['id'],
                "layer": row['layer'],
                "mem_type": row['mem_type'],
                "content": content,
                "context": row['context'] if row['context'] else {},
                "scene": row['scene'],
                "rating": row['rating'],
                "source": row.get('source', 'system'),
                "value_assessment": row['value_assessment'] if row['value_assessment'] else generate_default_value_assessment(),
                "created_at": row['created_at'].isoformat() if row['created_at'] else None,
                "expire_at": row['expire_at'].isoformat() if row['expire_at'] else None,
                "compressed": bool(row['compressed']),
                "creator": row.get('creator', 'system')
            }
        except Exception as e:
            logger.error(f"[UserMemoryStore] 异步获取记忆失败: {e}")
            return None

    def get_by_id(self, mem_id: str) -> dict | None:  # 定义根据ID获取记忆方法
        """根据ID获取单条记忆（sync，保留向后兼容）"""  # 方法文档字符串
        conn = None  # 初始化连接为None
        try:  # 尝试获取
            conn = PostgresConnectionPool.get_connection()  # 获取连接
            with self._rw_lock.gen_rlock(), conn.cursor(cursor_factory=RealDictCursor) as c:  # 获取读锁并创建真实字典游标
                c.execute("""
                    SELECT id, layer, mem_type, content, context, scene,
                           rating, source, value_assessment, created_at, expire_at, compressed, creator
                    FROM memories WHERE id = %s AND user_id = %s
                """, (mem_id, self.user_id))
                r = c.fetchone()  # 获取单条结果

            if not r:  # 如果没有结果
                return None  # 返回None

            try:  # 尝试解析内容
                content = json.loads(r['content'])  # 解析JSON
            except (json.JSONDecodeError, TypeError):  # 如果解析失败
                content = r['content']  # 使用原始内容

            return {  # 返回记忆字典
                "id": r['id'],  # 记忆ID
                "layer": r['layer'],  # 层级
                "mem_type": r['mem_type'],  # 类型
                "content": content,  # 内容
                "context": r['context'] if r['context'] else {},  # 上下文
                "scene": r['scene'],  # 场景
                "rating": r['rating'],  # 评分
                "source": r.get('source', 'system'),  # 来源（Agent-4新增）
                "value_assessment": r['value_assessment'] if r['value_assessment'] else generate_default_value_assessment(),  # 六维评分
                "created_at": r['created_at'].isoformat() if r['created_at'] else None,  # 创建时间
                "expire_at": r['expire_at'].isoformat() if r['expire_at'] else None,  # 过期时间
                "compressed": bool(r['compressed']),  # 压缩标记
                "creator": r.get('creator', 'system')  # 创建者（Agent-1新增）
            }
        except Exception as e:  # 捕获异常
            logger.error(f"[UserMemoryStore] 获取记忆失败: {e}")  # 记录错误
            return None  # 返回None
        finally:  # 最终执行
            if conn:  # 如果连接存在
                safe_return_connection(conn)  # P0修复: 使用安全函数归还连接


    def get_stats(self) -> dict[str, Any]:  # 定义获取统计方法
        """获取用户记忆统计"""  # 方法文档字符串
        conn = None  # 初始化连接为None
        try:  # 尝试获取
            conn = PostgresConnectionPool.get_connection()  # 获取连接
            stats = {"user_id": self.user_id}  # 初始化统计字典

            with self._rw_lock.gen_rlock(), conn.cursor() as c:  # 获取读锁并创建游标
                # 各层数量  # 各层统计注释
                    for layer in ALL_LAYERS:  # 遍历所有层级
                        c.execute("SELECT COUNT(*) FROM memories WHERE layer = %s AND user_id = %s",   # 查询数量
                                 (layer, self.user_id))  # 传入参数
                        stats[layer] = c.fetchone()[0]  # 获取数量

                    # 总数量  # 总数统计注释
                    c.execute("SELECT COUNT(*) FROM memories WHERE user_id = %s", (self.user_id,))  # 查询总数
                    stats["total"] = c.fetchone()[0]  # 获取总数

                    # 过期数量  # 过期统计注释
                    c.execute("SELECT COUNT(*) FROM memories WHERE expire_at < CURRENT_TIMESTAMP AND user_id = %s",  # 查询过期数
                             (self.user_id,))  # 传入参数
                    stats["expired"] = c.fetchone()[0]  # 获取过期数

                    # 压缩数量  # 压缩统计注释
                    c.execute("SELECT COUNT(*) FROM memories WHERE compressed = 1 AND user_id = %s",  # 查询压缩数
                             (self.user_id,))  # 传入参数
                    stats["compressed"] = c.fetchone()[0]  # 获取压缩数

                    # 平均评分  # 平均评分注释
                    c.execute("SELECT AVG(rating) FROM memories WHERE user_id = %s", (self.user_id,))  # 查询平均分
                    avg_rating = c.fetchone()[0]  # 获取平均分
                    stats["avg_rating"] = round(avg_rating, 2) if avg_rating else 0  # 四舍五入

                    # Agent-4: 新增各source来源统计
                    c.execute("""
                        SELECT source, COUNT(*) as count
                        FROM memories
                        WHERE user_id = %s
                        GROUP BY source
                    """, (self.user_id,))
                    source_stats = {}
                    for row in c.fetchall():
                        source_val, count = row
                        source_stats[source_val or 'system'] = count
                    stats["by_source"] = source_stats

            return stats  # 返回统计字典
        except Exception as e:  # 捕获异常
            logger.error(f"[UserMemoryStore] 获取统计失败: {e}")  # 记录错误
            return {"user_id": self.user_id, "total": 0}  # 返回默认统计
        finally:  # 最终执行
            if conn:  # 如果连接存在
                safe_return_connection(conn)  # P0修复: 使用安全函数归还连接

    def cleanup_expired(self, batch_size: int = 100) -> int:  # 定义清理过期数据方法
        """清理过期数据——【P1-1】引入 rating 权重，高 rating 延长保留，低 rating 提前淘汰"""  # 方法文档字符串
        conn = None  # 初始化连接为None
        try:  # 尝试清理
            conn = PostgresConnectionPool.get_connection()  # 获取连接
            with self._rw_lock.gen_wlock(), conn.cursor() as c:  # 获取写锁并创建游标
                # 【P1-1】按 rating 加权调整过期阈值
                # rating < 3：提前 50% 淘汰（30天→15天）
                # rating >= 4：延长 50% 保留（30天→45天）
                c.execute("""
                    DELETE FROM memories
                    WHERE expire_at IS NOT NULL
                    AND user_id = %s
                    AND (
                        (COALESCE(rating, 3) < 3 AND expire_at < CURRENT_TIMESTAMP - INTERVAL '15 days')
                        OR (COALESCE(rating, 3) >= 4 AND expire_at < CURRENT_TIMESTAMP - INTERVAL '45 days')
                        OR (COALESCE(rating, 3) = 3 AND expire_at < CURRENT_TIMESTAMP)
                    )
                """, (self.user_id,))
                deleted_count = c.rowcount  # 获取删除数量
                conn.commit()  # 提交事务
                return deleted_count  # 返回删除数量
        except Exception as e:  # 捕获异常
            logger.error(f"[UserMemoryStore] 清理过期数据失败: {e}")  # 记录错误
            if conn:  # 如果连接存在
                conn.rollback()  # 回滚事务
            return 0  # 返回0
        finally:  # 最终执行
            if conn:  # 如果连接存在
                safe_return_connection(conn)  # P0修复: 使用安全函数归还连接


    async def _sync_to_vector(self, layer: str, mem_type: str, content: Any,  # 定义同步到向量方法
                        context: dict, mem_id: str, rating: int, value_assessment: dict = None):  # 参数
        """同步到向量记忆层，并保存向量ID映射（P0-002修复）"""  # 方法文档字符串
        try:  # 尝试同步
            async def _do_sync():
                ms = await get_memory_service()

                # 提取文本内容用于向量索引
                if isinstance(content, dict):
                    text_content = content.get("text", content.get("summary", str(content)))
                elif isinstance(content, str):
                    text_content = content
                else:
                    text_content = str(content)

                # 添加用户命名空间和六维评分
                metadata = {
                    "mem_id": mem_id,
                    "layer": layer,
                    "mem_type": mem_type,
                    "rating": rating,
                    "user_id": self.user_id,
                    **(context or {})
                }

                # 添加六维评分到元数据
                if value_assessment:
                    for dim in ["emotional_temperature", "ethical_safety", "self_growth",
                               "execution_effectiveness", "sustainability", "inspiration_innovation"]:
                        metadata[dim] = value_assessment.get(dim, 3)

                collection_map = {
                    "experience": "experience",
                    "knowledge": "knowledge",
                    "chat": "chat",
                    "execution": "execution"
                }
                collection = collection_map.get(mem_type, "knowledge")
                vector_id = await ms.vector_store.add(collection, text_content, metadata)

                # P0-002修复：保存向量ID到PostgreSQL，建立双向映射
                if vector_id:
                    updated_context = {**(context or {}), "_vector_id": vector_id}
                    await self.update(mem_id, {"context": updated_context})
                    logger.debug(f"[UserMemoryStore] 向量同步完成，ID映射已保存: {mem_id[:8]}... -> {vector_id[:20]}...")

            await _do_sync()
        except Exception as e:
            logger.error(f"[SILENT_FAILURE_BLOCKED] 向量同步失败: {e}")

    async def delete_user_data(self) -> bool:
        """
        删除用户所有记忆数据（P1-Asyncify：改用 asyncpg）

        Returns:
            bool: 是否删除成功
        """
        try:
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                # 获取所有记忆ID用于向量删除
                rows = await conn.fetch(
                    "SELECT id, mem_type FROM memories WHERE user_id = $1",
                    self.user_id
                )
                mem_ids = [(r["id"], r["mem_type"]) for r in rows]

                # 删除所有记忆
                result = await conn.execute(
                    "DELETE FROM memories WHERE user_id = $1",
                    self.user_id
                )
                deleted = "DELETE" in result
                logger.info(f"[UserMemoryStore] 用户 {self.user_id} 记忆已删除")

            # 清理向量库
            if mem_ids:
                try:
                    ms = await get_memory_service()
                    ids_by_collection = {}
                    for mem_id, mem_type in mem_ids:
                        collection = mem_type if mem_type in ["experience", "knowledge", "chat", "execution"] else "knowledge"
                        if collection not in ids_by_collection:
                            ids_by_collection[collection] = []
                        ids_by_collection[collection].append(mem_id)

                    for collection, ids in ids_by_collection.items():
                        try:
                            await ms.vector_store.delete(collection, ids)
                        except Exception as e:
                            logger.warning(f"[UserMemoryStore] 向量删除失败 [{collection}]: {e}")

                    logger.info(f"[UserMemoryStore] 用户 {self.user_id} 向量库级联清理完成")
                except Exception as e:
                    logger.warning(f"[UserMemoryStore] 向量级联清理异常: {e}")

            return deleted
        except Exception as e:
            logger.error(f"[UserMemoryStore] 删除用户数据失败: {e}")
            return False

    def search_by_dimension(self, dimension: str, min_score: float = 3.0, limit: int = 10) -> list[dict]:  # 定义按维度搜索方法
        """  # 方法文档字符串开始
        按六维评分搜索记忆  # 方法标题

        Args:  # 参数说明
            dimension: 维度名称  # 参数1
            min_score: 最低分数  # 参数2
            limit: 返回数量  # 参数3

        Returns:  # 返回值说明
            记忆列表  # 返回类型
        """  # 方法文档字符串结束
        conn = None  # 初始化连接为None
        try:  # 尝试搜索
            conn = PostgresConnectionPool.get_connection()  # 获取连接
            with conn.cursor(cursor_factory=RealDictCursor) as c:  # 创建真实字典游标
                c.execute("""
                    SELECT id, layer, mem_type, content, context, scene,
                           rating, value_assessment, created_at
                    FROM memories
                    WHERE user_id = %s
                    AND (value_assessment->>%s)::float >= %s
                    ORDER BY (value_assessment->>%s)::float DESC
                    LIMIT %s
                """, (self.user_id, dimension, min_score, dimension, limit))
                rows = c.fetchall()  # 获取所有结果

            results = []  # 初始化结果列表
            for r in rows:  # 遍历查询结果
                try:  # 尝试解析内容
                    content = json.loads(r['content'])  # 解析JSON
                except (json.JSONDecodeError, TypeError):
                    content = r['content']  # 使用原始内容

                results.append({  # 添加结果字典
                    "id": r['id'],  # 记忆ID
                    "layer": r['layer'],  # 层级
                    "mem_type": r['mem_type'],  # 类型
                    "content": content,  # 内容
                    "context": r['context'] if r['context'] else {},  # 上下文
                    "scene": r['scene'],  # 场景
                    "rating": r['rating'],  # 评分
                    "value_assessment": r['value_assessment'] if r['value_assessment'] else generate_default_value_assessment(),  # 六维评分
                    "created_at": r['created_at'].isoformat() if r['created_at'] else None  # 创建时间
                })

            return results  # 返回结果列表
        except Exception as e:  # 捕获异常
            logger.error(f"[UserMemoryStore] 按维度搜索失败: {e}")  # 记录错误
            return []  # 返回空列表
        finally:  # 最终执行
            if conn:  # 如果连接存在
                safe_return_connection(conn)  # P0修复: 使用安全函数归还连接

    # 最大支持的ID数量限制  # 常量注释
    MAX_IDS_LIMIT = 10000  # 最大ID数量限制

    def get_memories_by_ids(self, mem_ids: list[str], batch_size: int = 500) -> list[dict]:  # 定义批量获取记忆方法
        """  # 方法文档字符串开始
        根据ID列表批量获取记忆，支持分批查询防止性能问题  # 方法标题

        Args:  # 参数说明
            mem_ids: 记忆ID列表  # 参数1
            batch_size: 每批查询数量，默认500  # 参数2

        Returns:  # 返回值说明
            记忆列表  # 返回类型
        """  # 方法文档字符串结束
        if not mem_ids:  # 如果ID列表为空
            return []  # 返回空列表

        # 去重保持顺序  # 去重注释
        mem_ids = list(dict.fromkeys(mem_ids))  # 使用字典去重但保持顺序

        # 检查最大限制  # 限制检查注释
        if len(mem_ids) > self.MAX_IDS_LIMIT:  # 如果超过最大限制
            logger.warning(f"[UserMemoryStore] ID数量({len(mem_ids)})超过限制({self.MAX_IDS_LIMIT})，只处理前{self.MAX_IDS_LIMIT}个")  # 记录警告
            mem_ids = mem_ids[:self.MAX_IDS_LIMIT]  # 截取前MAX_IDS_LIMIT个

        # 分批查询  # 分批查询注释
        all_results = []  # 初始化结果列表
        for i in range(0, len(mem_ids), batch_size):  # 按批次遍历
            batch = mem_ids[i:i + batch_size]  # 获取当前批次
            batch_results = self._get_memories_by_ids_batch(batch)  # 查询批次
            all_results.extend(batch_results)  # 添加到总结果

        return all_results  # 返回所有结果

    async def _get_memories_by_ids_batch_async(self, mem_ids: list[str]) -> list[dict]:
        """
        单批查询——异步版本（【P1-Asyncify】使用 asyncpg）。

        Args:
            mem_ids: 单批记忆ID列表（数量已控制）

        Returns:
            记忆列表
        """
        if not mem_ids:
            return []

        try:
            placeholders = ','.join([f'${i+1}' for i in range(len(mem_ids))])
            sql = f"""
                SELECT id, layer, mem_type, content, context, scene,
                       rating, value_assessment, created_at, expire_at, compressed, creator
                FROM memories
                WHERE id IN ({placeholders}) AND user_id = ${len(mem_ids) + 1}
            """
            rows = await _execute_async(sql, mem_ids + [self.user_id], fetch=True)

            results = []
            for r in rows:
                try:
                    content = json.loads(r['content'])
                except (json.JSONDecodeError, TypeError):
                    content = r['content']

                results.append({
                    "id": r['id'],
                    "layer": r['layer'],
                    "mem_type": r['mem_type'],
                    "content": content,
                    "context": r['context'] if r['context'] else {},
                    "scene": r['scene'],
                    "rating": r['rating'],
                    "value_assessment": r['value_assessment'] if r['value_assessment'] else generate_default_value_assessment(),
                    "created_at": r['created_at'].isoformat() if r['created_at'] else None,
                    "expire_at": r['expire_at'].isoformat() if r['expire_at'] else None,
                    "compressed": bool(r['compressed'])
                })

            return results
        except Exception as e:
            logger.error(f"[UserMemoryStore] 批量获取记忆失败: {e}")
            return []

    def _get_memories_by_ids_batch(self, mem_ids: list[str]) -> list[dict]:
        """
        单批查询（内部方法）——【P1-Asyncify】保留原始同步实现以确保向后兼容。
        异步版本请使用 _get_memories_by_ids_batch_async()。
        """
        if not mem_ids:
            return []

        conn = None
        try:
            conn = PostgresConnectionPool.get_connection()
            with self._rw_lock.gen_rlock(), conn.cursor(cursor_factory=RealDictCursor) as c:
                placeholders = ','.join(['%s'] * len(mem_ids))
                c.execute(f"""
                        SELECT id, layer, mem_type, content, context, scene,
                               rating, value_assessment, created_at, expire_at, compressed, creator
                        FROM memories
                        WHERE id IN ({placeholders}) AND user_id = %s
                    """, mem_ids + [self.user_id])
                rows = c.fetchall()

            results = []
            for r in rows:
                try:
                    content = json.loads(r['content'])
                except (json.JSONDecodeError, TypeError):
                    content = r['content']

                results.append({
                    "id": r['id'],
                    "layer": r['layer'],
                    "mem_type": r['mem_type'],
                    "content": content,
                    "context": r['context'] if r['context'] else {},
                    "scene": r['scene'],
                    "rating": r['rating'],
                    "value_assessment": r['value_assessment'] if r['value_assessment'] else generate_default_value_assessment(),
                    "created_at": r['created_at'].isoformat() if r['created_at'] else None,
                    "expire_at": r['expire_at'].isoformat() if r['expire_at'] else None,
                    "compressed": bool(r['compressed'])
                })

            return results
        except Exception as e:
            logger.error(f"[UserMemoryStore] 批量获取记忆失败: {e}")
            return []
        finally:
            if conn:
                safe_return_connection(conn)

    # ═══════════════════════════════════════════════════════════════════
    # P2-1: 记忆关联辅助方法
    # ═══════════════════════════════════════════════════════════════════

    def get_memories_by_entity(
        self,
        entity_text: str,
        entity_type: str | None = None,
        limit: int = 20
    ) -> list[dict]:
        """根据实体查询记忆

        通过分析记忆内容，查找包含指定实体的记忆。

        Args:
            entity_text: 实体文本
            entity_type: 实体类型（可选，如person/location/concept等）
            limit: 返回数量限制

        Returns:
            List[Dict]: 记忆列表
        """
        conn = None
        try:
            conn = PostgresConnectionPool.get_connection()
            with self._rw_lock.gen_rlock(), conn.cursor(cursor_factory=RealDictCursor) as c:
                # 使用ILIKE进行不区分大小写的模糊匹配
                search_pattern = f'%{entity_text}%'
                c.execute("""
                        SELECT id, layer, mem_type, content, context, scene,
                               rating, value_assessment, created_at, expire_at, compressed, creator
                        FROM memories
                        WHERE user_id = %s
                        AND (content ILIKE %s OR scene ILIKE %s)
                        AND (expire_at IS NULL OR expire_at > CURRENT_TIMESTAMP)
                        ORDER BY created_at DESC
                        LIMIT %s
                    """, (self.user_id, search_pattern, search_pattern, limit))
                rows = c.fetchall()

            results = []
            for r in rows:
                try:
                    content = json.loads(r['content'])
                except (json.JSONDecodeError, TypeError):
                    content = r['content']

                results.append({
                    "id": r['id'],
                    "layer": r['layer'],
                    "mem_type": r['mem_type'],
                    "content": content,
                    "context": r['context'] if r['context'] else {},
                    "scene": r['scene'],
                    "rating": r['rating'],
                    "value_assessment": r['value_assessment'] if r['value_assessment'] else generate_default_value_assessment(),
                    "created_at": r['created_at'].isoformat() if r['created_at'] else None,
                    "expire_at": r['expire_at'].isoformat() if r['expire_at'] else None,
                    "compressed": bool(r['compressed']),
                    "creator": r.get('creator', 'system')
                })

            return results
        except Exception as e:
            logger.error(f"[UserMemoryStore] 根据实体查询记忆失败: {e}")
            return []
        finally:
            if conn:
                safe_return_connection(conn)  # P0修复: 使用安全函数

    def get_recent_memories(
        self,
        hours: int = 24,
        layer: str | None = None,
        limit: int = 50
    ) -> list[dict]:
        """获取近期记忆

        查询指定时间范围内创建的记忆。

        Args:
            hours: 时间范围（小时），默认24小时
            layer: 记忆层级过滤（可选）
            limit: 返回数量限制

        Returns:
            List[Dict]: 记忆列表
        """
        conn = None
        try:
            conn = PostgresConnectionPool.get_connection()
            with self._rw_lock.gen_rlock(), conn.cursor(cursor_factory=RealDictCursor) as c:
                if layer:
                    c.execute("""
                            SELECT id, layer, mem_type, content, context, scene,
                                   rating, value_assessment, created_at, expire_at, compressed, creator
                            FROM memories
                            WHERE user_id = %s
                            AND layer = %s
                            AND created_at > CURRENT_TIMESTAMP - INTERVAL '%s hours'
                            AND (expire_at IS NULL OR expire_at > CURRENT_TIMESTAMP)
                            ORDER BY created_at DESC
                            LIMIT %s
                        """, (self.user_id, layer, hours, limit))
                else:
                    c.execute("""
                            SELECT id, layer, mem_type, content, context, scene,
                                   rating, value_assessment, created_at, expire_at, compressed, creator
                            FROM memories
                            WHERE user_id = %s
                            AND created_at > CURRENT_TIMESTAMP - INTERVAL '%s hours'
                            AND (expire_at IS NULL OR expire_at > CURRENT_TIMESTAMP)
                            ORDER BY created_at DESC
                            LIMIT %s
                        """, (self.user_id, hours, limit))
                rows = c.fetchall()

            results = []
            for r in rows:
                try:
                    content = json.loads(r['content'])
                except (json.JSONDecodeError, TypeError):
                    content = r['content']

                results.append({
                    "id": r['id'],
                    "layer": r['layer'],
                    "mem_type": r['mem_type'],
                    "content": content,
                    "context": r['context'] if r['context'] else {},
                    "scene": r['scene'],
                    "rating": r['rating'],
                    "value_assessment": r['value_assessment'] if r['value_assessment'] else generate_default_value_assessment(),
                    "created_at": r['created_at'].isoformat() if r['created_at'] else None,
                    "expire_at": r['expire_at'].isoformat() if r['expire_at'] else None,
                    "compressed": bool(r['compressed']),
                    "creator": r.get('creator', 'system')
                })

            return results
        except Exception as e:
            logger.error(f"[UserMemoryStore] 获取近期记忆失败: {e}")
            return []
        finally:
            if conn:
                safe_return_connection(conn)  # P0修复: 使用安全函数

    def get_memories_by_scene(
        self,
        scene: str,
        fuzzy_match: bool = False,
        limit: int = 20
    ) -> list[dict]:
        """根据场景查询记忆

        Args:
            scene: 场景指纹
            fuzzy_match: 是否使用模糊匹配（部分匹配）
            limit: 返回数量限制

        Returns:
            List[Dict]: 记忆列表
        """
        conn = None
        try:
            conn = PostgresConnectionPool.get_connection()
            with self._rw_lock.gen_rlock(), conn.cursor(cursor_factory=RealDictCursor) as c:
                if fuzzy_match:
                    c.execute("""
                            SELECT id, layer, mem_type, content, context, scene,
                                   rating, value_assessment, created_at, expire_at, compressed, creator
                            FROM memories
                            WHERE user_id = %s
                            AND scene ILIKE %s
                            AND (expire_at IS NULL OR expire_at > CURRENT_TIMESTAMP)
                            ORDER BY created_at DESC
                            LIMIT %s
                        """, (self.user_id, f'%{scene}%', limit))
                else:
                    c.execute("""
                            SELECT id, layer, mem_type, content, context, scene,
                                   rating, value_assessment, created_at, expire_at, compressed, creator
                            FROM memories
                            WHERE user_id = %s
                            AND scene = %s
                            AND (expire_at IS NULL OR expire_at > CURRENT_TIMESTAMP)
                            ORDER BY created_at DESC
                            LIMIT %s
                        """, (self.user_id, scene, limit))
                rows = c.fetchall()

            results = []
            for r in rows:
                try:
                    content = json.loads(r['content'])
                except (json.JSONDecodeError, TypeError):
                    content = r['content']

                results.append({
                    "id": r['id'],
                    "layer": r['layer'],
                    "mem_type": r['mem_type'],
                    "content": content,
                    "context": r['context'] if r['context'] else {},
                    "scene": r['scene'],
                    "rating": r['rating'],
                    "value_assessment": r['value_assessment'] if r['value_assessment'] else generate_default_value_assessment(),
                    "created_at": r['created_at'].isoformat() if r['created_at'] else None,
                    "expire_at": r['expire_at'].isoformat() if r['expire_at'] else None,
                    "compressed": bool(r['compressed']),
                    "creator": r.get('creator', 'system')
                })

            return results
        except Exception as e:
            logger.error(f"[UserMemoryStore] 根据场景查询记忆失败: {e}")
            return []
        finally:
            if conn:
                safe_return_connection(conn)  # P0修复: 使用安全函数

    # ═══════════════════════════════════════════════════════════════════
    # P3: 硅基生命体征相关方法
    # ═══════════════════════════════════════════════════════════════════

    def save_vital_signs(self, vital_signs: dict, context: dict = None) -> bool:
        """
        保存生命体征

        Args:
            vital_signs: 生命体征字典，包含 energy, curiosity, satisfaction, stress, mood
            context: 上下文信息（可选）

        Returns:
            bool: 是否保存成功
        """
        conn = None
        try:
            conn = PostgresConnectionPool.get_connection()
            with self._rw_lock.gen_wlock(), conn.cursor() as c:
                c.execute('''
                        INSERT INTO vital_signs_history
                        (user_id, energy, curiosity, satisfaction, stress, mood, is_hibernating, context)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ''', (
                    self.user_id,
                    vital_signs.get('energy', 5.0),
                    vital_signs.get('curiosity', 5.0),
                    vital_signs.get('satisfaction', 5.0),
                    vital_signs.get('stress', 0.0),
                    vital_signs.get('mood', '平静'),
                    vital_signs.get('is_hibernating', False),
                    Json(context) if context else None
                ))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"[UserMemoryStore] 保存生命体征失败: {e}")
            if conn:
                conn.rollback()
            return False
        finally:
            if conn:
                safe_return_connection(conn)  # P0修复: 使用安全函数

    def get_vital_signs_history(self, limit: int = 100) -> list[dict]:
        """
        获取生命体征历史

        Args:
            limit: 返回记录数量限制

        Returns:
            List[Dict]: 生命体征历史记录列表
        """
        conn = None
        try:
            conn = PostgresConnectionPool.get_connection()
            with self._rw_lock.gen_rlock(), conn.cursor(cursor_factory=RealDictCursor) as c:
                c.execute('''
                        SELECT id, timestamp, energy, curiosity, satisfaction, stress, mood, is_hibernating, context
                        FROM vital_signs_history
                        WHERE user_id = %s
                        ORDER BY timestamp DESC
                        LIMIT %s
                    ''', (self.user_id, limit))
                rows = c.fetchall()

            results = []
            for r in rows:
                results.append({
                    "id": r['id'],
                    "timestamp": r['timestamp'].isoformat() if r['timestamp'] else None,
                    "energy": r['energy'],
                    "curiosity": r['curiosity'],
                    "satisfaction": r['satisfaction'],
                    "stress": r['stress'],
                    "mood": r['mood'],
                    "is_hibernating": r['is_hibernating'],
                    "context": r['context'] if r['context'] else {}
                })
            return results
        except Exception as e:
            logger.error(f"[UserMemoryStore] 获取生命体征历史失败: {e}")
            return []
        finally:
            if conn:
                safe_return_connection(conn)  # P0修复: 使用安全函数

    def save_self_action(self, action: dict) -> bool:
        """
        保存自发行动

        Args:
            action: 行动字典，包含 action_type, action_content, energy_cost, satisfaction_gain, status, context

        Returns:
            bool: 是否保存成功
        """
        conn = None
        try:
            conn = PostgresConnectionPool.get_connection()
            with self._rw_lock.gen_wlock(), conn.cursor() as c:
                c.execute('''
                        INSERT INTO self_actions
                        (user_id, action_type, action_content, energy_cost, satisfaction_gain, status, context)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ''', (
                    self.user_id,
                    action.get('action_type', 'explore'),
                    action.get('action_content', ''),
                    action.get('energy_cost', 0.0),
                    action.get('satisfaction_gain', 0.0),
                    action.get('status', 'pending'),
                    Json(action.get('context')) if action.get('context') else None
                ))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"[UserMemoryStore] 保存自发行动失败: {e}")
            if conn:
                conn.rollback()
            return False
        finally:
            if conn:
                safe_return_connection(conn)  # P0修复: 使用安全函数

    def get_self_actions(self, limit: int = 100) -> list[dict]:
        """
        获取自发行动历史

        Args:
            limit: 返回记录数量限制

        Returns:
            List[Dict]: 自发行动历史记录列表
        """
        conn = None
        try:
            conn = PostgresConnectionPool.get_connection()
            with self._rw_lock.gen_rlock(), conn.cursor(cursor_factory=RealDictCursor) as c:
                c.execute('''
                    SELECT id, timestamp, action_type, action_content, energy_cost, satisfaction_gain, status, context
                    FROM self_actions
                    WHERE user_id = %s
                    ORDER BY timestamp DESC
                    LIMIT %s
                ''', (self.user_id, limit))
                rows = c.fetchall()

            results = []
            for r in rows:
                results.append({
                    "id": r['id'],
                    "timestamp": r['timestamp'].isoformat() if r['timestamp'] else None,
                    "action_type": r['action_type'],
                    "action_content": r['action_content'],
                    "energy_cost": r['energy_cost'],
                    "satisfaction_gain": r['satisfaction_gain'],
                    "status": r['status'],
                    "context": r['context'] if r['context'] else {}
                })
            return results
        except Exception as e:
            logger.error(f"[UserMemoryStore] 获取自发行动历史失败: {e}")
            return []
        finally:
            if conn:
                safe_return_connection(conn)  # P0修复: 使用安全函数


class MemoryManager:  # 定义记忆管理器类
    """  # 类文档字符串开始
    记忆管理器 - 管理所有用户的记忆存储  # 类标题
    提供用户隔离和统一接口  # 类功能
    """  # 类文档字符串结束

    _instance = None  # 单例实例
    _instance_lock = threading.Lock()  # 单例锁

    def __new__(cls):  # 定义创建实例方法
        if cls._instance is None:  # 如果实例不存在
            with cls._instance_lock:  # 获取锁
                if cls._instance is None:  # 双重检查
                    cls._instance = super().__new__(cls)  # 创建实例
                    cls._instance._initialized = False  # 标记未初始化
        return cls._instance  # 返回实例

    def __init__(self, storage_type: str = None):  # 初始化方法
        if self._initialized:  # 如果已初始化
            return  # 直接返回
        self._initialized = True  # 标记已初始化

        # 强制使用 PostgreSQL - SQLite 降级已移除  # 存储模式注释
        self.storage_type = "postgres"  # 设置存储类型为PostgreSQL
        self._stores: dict[str, UserMemoryStore] = {}  # 初始化用户存储字典
        self._lock = threading.RLock()  # 创建可重入锁

        # 初始化 PostgreSQL  # 初始化注释
        init_postgres_tables()  # 初始化PostgreSQL表
        logger.info("[MemoryManager] 记忆管理器初始化完成（PostgreSQL模式）")  # 记录日志

        # P2-003修复：添加停止事件用于优雅退出  # 修复注释
        self._cleanup_stop_event = threading.Event()  # 创建停止事件
        self._cleanup_thread = threading.Thread(target=self._auto_cleanup_expired, daemon=True)  # 创建清理线程
        self._cleanup_thread.start()  # 启动清理线程

    def get_user_store(self, user_id: str) -> UserMemoryStore:  # 定义获取用户存储方法
        """  # 方法文档字符串开始
        获取或创建用户存储  # 方法标题

        Args:  # 参数说明
            user_id: 用户唯一标识  # 参数

        Returns:  # 返回值说明
            用户记忆存储实例  # 返回类型
        """  # 方法文档字符串结束
        with self._lock:  # 获取锁
            if user_id not in self._stores:  # 如果用户存储不存在
                self._stores[user_id] = UserMemoryStore(user_id)  # 创建用户存储
            return self._stores[user_id]  # 返回用户存储

    async def add(self, user_id: str, layer: str, content: dict, source: MemorySource | str = None, **kwargs) -> str:  # 定义添加记忆方法
        """添加记忆（自动路由到对应用户存储）"""  # 方法文档字符串
        store = self.get_user_store(user_id)  # 获取用户存储
        return await store.add(layer=layer, content=content, source=source, **kwargs)  # 调用添加方法

    async def add_memory(self, user_id: str, content: str, memory_type: str = "general",
                   metadata: dict = None, **kwargs) -> str:
        """
        添加用户记忆（简化接口，供上层调用）

        Args:
            user_id: 用户ID
            content: 记忆内容
            memory_type: 记忆类型
            metadata: 元数据字典
            **kwargs: 额外参数

        Returns:
            记忆ID
        """
        # 构建内容字典
        content_dict = {"text": content, "memory_type": memory_type}
        if metadata:
            content_dict.update(metadata)

        # 调用add方法
        return await self.add(
            user_id=user_id,
            layer=kwargs.get('layer', 'short'),
            content=content_dict,
            **kwargs
        )

    async def query(self, user_id: str, layer: str | None = None, **kwargs) -> list[dict]:  # 定义查询记忆方法
        """查询记忆（自动路由到对应用户存储）"""  # 方法文档字符串
        store = self.get_user_store(user_id)  # 获取用户存储
        return await store.query(layer=layer, **kwargs)  # 调用查询方法

    async def update(self, user_id: str, mem_id: str, updates: dict) -> bool:  # 定义更新记忆方法
        """更新记忆"""  # 方法文档字符串
        store = self.get_user_store(user_id)  # 获取用户存储
        return await store.update(mem_id, updates)  # 调用更新方法

    async def delete(self, user_id: str, mem_id: str, sync_vector: bool = True) -> bool:  # 定义删除记忆方法
        """删除记忆"""  # 方法文档字符串
        store = self.get_user_store(user_id)  # 获取用户存储
        return await store.delete(mem_id, sync_vector=sync_vector)  # 调用删除方法

    async def delete_memory(self, user_id: str, mem_id: str) -> bool:  # 定义删除记忆方法（别名）
        """删除用户记忆"""  # 方法文档字符串
        try:  # 尝试删除
            store = self.get_user_store(user_id)  # 获取用户存储
            return await store.delete(mem_id, sync_vector=True)  # 调用删除方法
        except Exception as e:  # 捕获异常
            logger.error(f"[MemoryManager] 删除记忆失败: {e}")  # 记录错误
            return False  # 返回失败

    async def get_by_id(self, user_id: str, mem_id: str) -> dict | None:  # 定义根据ID获取记忆方法
        """根据ID获取记忆"""  # 方法文档字符串
        store = self.get_user_store(user_id)  # 获取用户存储
        return await store.get_by_id(mem_id)  # 调用获取方法

    def get_stats(self, user_id: str) -> dict[str, Any]:  # 定义获取用户统计方法
        """获取用户记忆统计"""  # 方法文档字符串
        store = self.get_user_store(user_id)  # 获取用户存储
        return store.get_stats()  # 调用统计方法

    def get_global_stats(self) -> dict[str, Any]:  # 定义获取全局统计方法
        """获取全局统计"""  # 方法文档字符串
        with self._lock:  # 获取锁
            total_users = len(self._stores)  # 获取用户数量
            all_stats = {  # 构建统计字典
                "total_users": total_users,  # 用户总数
                "users": {}  # 用户统计字典
            }

            for user_id, store in self._stores.items():  # 遍历用户存储
                all_stats["users"][user_id] = store.get_stats()  # 获取用户统计

            return all_stats  # 返回全局统计

    def list_users(self) -> list[str]:  # 定义列出用户方法
        """获取所有用户ID列表"""  # 方法文档字符串
        with self._lock:  # 获取锁
            return list(self._stores.keys())  # 返回用户ID列表

    async def retrieve_memory(self, user_id: str, layer: str = None, mem_type: str = None,
                        limit: int = 10, min_rating: int = None) -> list[dict]:
        """检索记忆（用于工具层）"""
        store = self.get_user_store(user_id)
        filters = {}
        if mem_type:
            filters["mem_type"] = mem_type
        if min_rating:
            filters["min_rating"] = min_rating
        return await store.query(layer=layer, filters=filters, limit=limit)

    async def retrieve_memories(self, user_id: str, query: str = None, level: str = None,
                          limit: int = None) -> list[dict]:
        """智能检索记忆（供AgentLoop调用）"""
        try:
            if limit is None:
                if query:
                    query_len = len(query)
                    if query_len < 10:
                        limit = 3
                    elif query_len < 30:
                        limit = 5
                    else:
                        limit = 8
                else:
                    limit = 5

            layer_map = {
                "L1": "working",
                "L2": "short",
                "L3": "medium",
                "L4": "evolve",
                "L5": "execution"
            }
            layer = layer_map.get(level)

            store = self.get_user_store(user_id)
            filters = {}
            if query:
                filters["query"] = query

            results = await store.query(layer=layer, filters=filters, limit=limit)
            logger.info(f"[Memory] retrieve_memories: user={user_id}, level={level}, query='{query[:30] if query else None}...', returned={len(results)}")
            return results
        except Exception as e:
            logger.error(f"[Memory] retrieve_memories 失败: user={user_id}, level={level}, error={e}")
            raise MemoryRetrievalError(f"检索记忆失败: {e}") from e

    def get_memories_by_ids(self, user_id: str, mem_ids: list[str]) -> list[dict]:  # 定义根据ID列表获取记忆方法
        """根据ID列表获取记忆"""  # 方法文档字符串
        store = self.get_user_store(user_id)  # 获取用户存储
        return store.get_memories_by_ids(mem_ids)  # 调用批量获取方法

    def get_memories_by_entity(self, user_id: str, entity_text: str,
                               entity_type: str | None = None, limit: int = 20) -> list[dict]:
        """根据实体查询记忆（P2-1）"""
        store = self.get_user_store(user_id)
        return store.get_memories_by_entity(entity_text, entity_type, limit)

    def get_recent_memories(self, user_id: str, hours: int = 24,
                           layer: str | None = None, limit: int = 50) -> list[dict]:
        """获取近期记忆（P2-1）"""
        store = self.get_user_store(user_id)
        return store.get_recent_memories(hours, layer, limit)

    def get_memories_by_scene(self, user_id: str, scene: str,
                             fuzzy_match: bool = False, limit: int = 20) -> list[dict]:
        """根据场景查询记忆（P2-1）"""
        store = self.get_user_store(user_id)
        return store.get_memories_by_scene(scene, fuzzy_match, limit)

    def _auto_cleanup_expired(self):  # 定义自动清理过期数据方法
        """自动清理过期数据"""  # 方法文档字符串
        # P2-003修复：使用可中断的等待机制实现优雅退出  # 修复注释
        # 停止信号：通过_cleanup_stop_event设置停止标志  # 信号说明
        # 安全特性：内部try-except捕获异常，确保循环继续运行  # 安全说明
        while not self._cleanup_stop_event.is_set():  # 循环直到收到停止信号
            try:  # 尝试执行
                # 可中断的等待：10分钟或直到停止信号  # 等待说明
                if self._cleanup_stop_event.wait(600):  # 等待10分钟或停止信号
                    break  # 如果收到停止信号，跳出循环

                with self._lock:  # 获取锁
                    for store in self._stores.values():  # 遍历用户存储
                        try:  # 尝试清理
                            count = store.cleanup_expired(batch_size=100)  # 清理过期数据
                            if count > 0:  # 如果有清理数据
                                logger.info(f"[MemoryManager] 清理 {count} 条过期记忆")  # 记录日志
                        except Exception as e:  # 捕获异常
                            logger.error(f"[MemoryManager] 清理失败: {e}")  # 记录错误

            except Exception as e:  # 捕获异常
                logger.error(f"[MemoryManager] 自动清理线程异常: {e}")  # 记录错误

    def close_all(self):  # 定义关闭所有方法
        """关闭所有用户存储 - CORE-001修复: 添加异常处理和关闭状态标记"""  # 方法文档字符串
        # P2-003修复：优雅停止清理线程  # 修复注释
        if hasattr(self, '_cleanup_stop_event'):  # 如果有停止事件
            logger.info("[MemoryManager] 发送清理线程停止信号...")  # 记录日志
            self._cleanup_stop_event.set()  # 设置停止信号

            # 等待线程结束（最多5秒）  # 等待注释
            if self._cleanup_thread and self._cleanup_thread.is_alive():  # 如果线程存活
                self._cleanup_thread.join(timeout=5)  # 等待线程结束
                if self._cleanup_thread.is_alive():  # 如果线程仍在运行
                    logger.warning("[MemoryManager] 清理线程未能及时停止")  # 记录警告
                else:  # 如果线程已停止
                    logger.info("[MemoryManager] 清理线程已优雅停止")  # 记录日志

        try:  # 尝试关闭
            with self._lock:  # 获取锁
                self._stores.clear()  # 清空用户存储
                PostgresConnectionPool.close_all()  # 关闭连接池
                logger.info("[MemoryManager] 所有用户存储已关闭")  # 记录日志
        except Exception as e:  # 捕获异常
            logger.error(f"[MemoryManager] 关闭用户存储失败: {e}")  # 记录错误
            raise  # 重新抛出
        finally:  # 最终执行
            # 确保状态标记  # 状态标记注释
            self._closed = True  # 标记已关闭

    # P2-003修复：支持上下文管理器  # 修复注释
    def __enter__(self):  # 定义上下文管理器入口
        """上下文管理器入口"""  # 方法文档字符串
        return self  # 返回自身

    def __exit__(self, exc_type, exc_val, exc_tb):  # 定义上下文管理器出口
        """上下文管理器出口 - 自动调用close_all"""  # 方法文档字符串
        self.close_all()  # 调用关闭方法
        return False  # 不抑制异常


# 兼容旧接口的 Memory 类（单例模式）  # 兼容类注释
class Memory:  # 定义兼容旧接口的记忆类
    """兼容旧接口的记忆类 - 使用默认用户"""  # 类文档字符串

    _instance = None  # 单例实例
    _default_user_id = "default"  # 默认用户ID

    def __new__(cls):  # 定义创建实例方法
        if cls._instance is None:  # 如果实例不存在
            cls._instance = super().__new__(cls)  # 创建实例
            cls._instance._manager = None  # 初始化管理器为None
        return cls._instance  # 返回实例

    def __init__(self):  # 初始化方法
        if self._manager is None:  # 如果管理器未初始化
            try:
                self._manager = MemoryManager()  # 创建记忆管理器
            except Exception as e:
                logger.error(f"[Memory] 初始化MemoryManager失败: {e}")
                self._manager = None  # 确保失败时标记为None

    def _get_manager(self) -> MemoryManager:
        """
        安全获取MemoryManager - P0修复

        Returns:
            MemoryManager: 记忆管理器实例

        Raises:
            RuntimeError: 如果管理器未初始化
        """
        if self._manager is None:
            # 尝试重新初始化
            try:
                self._manager = MemoryManager()
            except Exception as e:
                raise RuntimeError(f"[Memory] MemoryManager未初始化且无法重新初始化: {e}") from e
        return self._manager

    async def add(self, layer: str, mem_type: str, content: Any, context: dict = None,  # 定义添加方法
            scene: str = "", rating: int = 0, expire_days: int = None,   # 参数
            sync_vector: bool = True, value_assessment: dict = None,
            source: MemorySource | str = None) -> str:  # 参数，返回记忆ID（Agent-4: 使用source替代creator）
        """兼容旧接口的添加方法"""  # 方法文档字符串
        return await self._get_manager().add(  # P0修复: 使用安全方法获取管理器
            user_id=self._default_user_id,  # 使用默认用户ID
            layer=layer,  # 层级
            content=content if isinstance(content, dict) else {"text": content},  # 内容
            mem_type=mem_type,  # 类型
            context=context,  # 上下文
            scene=scene,  # 场景
            rating=rating,  # 评分
            expire_days=expire_days,  # 过期天数
            sync_vector=sync_vector,  # 同步向量
            value_assessment=value_assessment,  # 六维评分
            source=source  # 来源（Agent-4: 使用source替代creator）
        )

    async def get_async(self, scene: str = None, mem_type: str = None, layer: str = None,
                        limit: int = 10, min_rating: int = -1, filter_dict: dict = None) -> list[dict]:
        """异步查询记忆（兼容旧接口）"""
        filters = {}
        if mem_type:
            filters["mem_type"] = mem_type
        if scene:
            filters["scene"] = scene
        if min_rating > -1:
            filters["min_rating"] = min_rating
        if filter_dict:
            filters.update(filter_dict)
        return await self._get_manager().query(
            user_id=self._default_user_id,
            layer=layer,
            filters=filters,
            limit=limit
        )

    def get(self, scene: str = None, mem_type: str = None, layer: str = None,
            limit: int = 10, min_rating: int = -1, filter_dict: dict = None) -> list[dict]:
        """兼容旧接口的同步查询方法（已弃用，请使用 get_async）"""
        import asyncio
        filters = {}
        if mem_type:
            filters["mem_type"] = mem_type
        if scene:
            filters["scene"] = scene
        if min_rating > -1:
            filters["min_rating"] = min_rating
        if filter_dict:
            filters.update(filter_dict)
        try:
            asyncio.get_running_loop()
            raise RuntimeError(
                "get() 不能在已有事件循环中调用。请在异步上下文中使用 await get_async()"
            )
        except RuntimeError as e:
            if "no running event loop" in str(e):
                return asyncio.run(self._get_manager().query(
                    user_id=self._default_user_id, layer=layer, filters=filters, limit=limit
                ))
            raise

    async def update(self, mem_id: str, **kwargs) -> bool:  # 定义更新方法
        """兼容旧接口的更新方法"""  # 方法文档字符串
        return await self._get_manager().update(self._default_user_id, mem_id, kwargs)  # P0修复: 使用安全方法获取管理器

    async def delete(self, mem_id: str) -> bool:  # 定义删除方法
        """兼容旧接口的删除方法"""  # 方法文档字符串
        return await self._get_manager().delete(self._default_user_id, mem_id)  # P0修复: 使用安全方法获取管理器

    async def rate(self, mem_id: str, rating: int):  # 定义评分方法
        """兼容旧接口的评分方法"""  # 方法文档字符串
        return await self._get_manager().update(self._default_user_id, mem_id, {"rating": rating})  # P0修复: 使用安全方法获取管理器

    def get_stats(self) -> dict[str, Any]:  # 定义获取统计方法
        """兼容旧接口的统计方法"""  # 方法文档字符串
        return self._get_manager().get_stats(self._default_user_id)  # P0修复: 使用安全方法获取管理器

    async def add_ai_memory(self, task_name: str, decision_func: str, reason: str, effect: str, remark: str = ""):  # 定义添加AI记忆方法
        """添加AI自主记忆"""  # 方法文档字符串
        content = {  # 构建内容字典
            "task_name": task_name,  # 任务名称
            "decision_func": decision_func,  # 决策函数
            "reason": reason,  # 原因
            "effect": effect,  # 效果
            "remark": remark  # 备注
        }
        return await self.add("evolve", "ai_autonomy", content, {"task_name": task_name}, rating=0)  # 调用添加方法

    async def add_event_memory(self, task_name: str, task_count: int, reason: str, effect: str, remark: str = ""):  # 定义添加事件记忆方法
        """添加事件记忆"""  # 方法文档字符串
        content = {  # 构建内容字典
            "task_name": task_name,  # 任务名称
            "task_count": task_count,  # 任务数量
            "reason": reason,  # 原因
            "effect": effect,  # 效果
            "remark": remark  # 备注
        }
        return await self.add("evolve", "event", content, {"task_name": task_name}, rating=0)  # 调用添加方法

    async def save_reflection(self, session_id: str, user_instruction: str, task_result: dict, task_type: str = "general"):  # 定义保存反思方法
        """保存反思结果"""  # 方法文档字符串
        scene = f"reflection_{task_type}_{user_instruction[:20]}"  # 构建场景指纹
        return await self.add("evolve", "reflection", task_result, {  # 调用添加方法
            "session_id": session_id,  # 会话ID
            "user_instruction": user_instruction,  # 用户指令
            "task_type": task_type  # 任务类型
        }, scene=scene)  # 场景

    def load_reflections(self, task_type: str = None, limit: int = 5) -> list[dict]:  # 定义加载反思方法
        """加载反思记录"""  # 方法文档字符串
        return self.get(mem_type="reflection", layer="evolve", limit=limit)  # 调用查询方法

    async def add_batch(self, items: list[dict]) -> list[str]:  # 定义批量添加方法
        """批量添加"""  # 方法文档字符串
        mem_ids = []  # 初始化记忆ID列表
        for item in items:  # 遍历项目
            mem_id = await self.add(  # 调用添加方法
                layer=item.get("layer", "short"),  # 层级
                mem_type=item.get("mem_type", "chat"),  # 类型
                content=item.get("content", ""),  # 内容
                context=item.get("context", {}),  # 上下文
                scene=item.get("scene", ""),  # 场景
                rating=item.get("rating", 0),  # 评分
                expire_days=item.get("expire_days"),  # 过期天数
                value_assessment=item.get("value_assessment")  # 六维评分
            )
            mem_ids.append(mem_id)  # 添加记忆ID
        return mem_ids  # 返回记忆ID列表

    async def get_by_ids(self, mem_ids: list[str]) -> list[dict]:  # 定义根据ID列表获取方法
        """根据ID列表获取记忆"""  # 方法文档字符串
        results = []  # 初始化结果列表
        for mem_id in mem_ids:  # 遍历记忆ID
            mem = await self._get_manager().get_by_id(self._default_user_id, mem_id)  # P0修复: 使用安全方法获取管理器
            if mem:  # 如果记忆存在
                results.append(mem)  # 添加到结果
        return results  # 返回结果列表

    async def query_advanced(self, query_params: MemoryQuery) -> list[dict]:  # 定义高级查询方法
        """高级查询"""  # 方法文档字符串
        filters = {}  # 初始化过滤条件
        if query_params.mem_type:  # 如果指定了类型
            filters["mem_type"] = query_params.mem_type  # 添加类型过滤
        if query_params.scene:  # 如果指定了场景
            filters["scene"] = query_params.scene  # 添加场景过滤
        if query_params.min_rating > -1:  # 如果指定了最低评分
            filters["min_rating"] = query_params.min_rating  # 添加评分过滤
        if query_params.since:  # 如果指定了开始时间
            filters["since"] = query_params.since  # 添加开始时间过滤

        return self._get_manager().query(  # P0修复: 使用安全方法获取管理器
            user_id=self._default_user_id,  # 使用默认用户ID
            layer=query_params.layer,  # 层级
            filters=filters,  # 过滤条件
            limit=query_params.limit  # 限制数量
        )

    def retrieve_memories(self, user_id: str = None, query: str = None, level: str = None,
                          limit: int = None, use_semantic: bool = True) -> list[dict]:
        """
        【P0修复】智能检索记忆（支持语义向量检索）

        Args:
            user_id: 用户ID，默认使用default用户
            query: 查询文本（用于语义匹配）
            level: 记忆层级（"L2", "L3"等）
            limit: 返回数量限制，None则自动计算
            use_semantic: 【新增】是否使用语义检索（默认True）

        Returns:
            List[Dict]: 记忆列表（按语义相关性排序）
        """
        try:
            # 使用传入的user_id或默认用户
            actual_user_id = user_id if user_id else self._default_user_id

            # 自动计算limit（基于查询复杂度）
            if limit is None:
                if query:
                    # 简单启发式：查询越长，返回越多记忆
                    query_len = len(query)
                    if query_len < 10:
                        limit = 3
                    elif query_len < 30:
                        limit = 5
                    else:
                        limit = 8
                else:
                    limit = 5

            # 映射level到layer
            layer_map = {
                "L1": "working",
                "L2": "short",
                "L3": "medium",
                "L4": "evolve",
                "L5": "execution"
            }
            layer = layer_map.get(level)

            # 【P0修复】使用语义检索（当提供query时）
            results = self._get_manager().query(
                user_id=actual_user_id,
                layer=layer,
                limit=limit,
                query_text=query if use_semantic else None,
                use_semantic_search=use_semantic and query is not None,
                semantic_weight=0.6
            )

            logger.info(
                f"[Memory] retrieve_memories: user={actual_user_id}, level={level}, "
                f"query={'有' if query else '无'}, returned={len(results)}"
            )
            return results
        except Exception as e:
            logger.error(f"[Memory] retrieve_memories 失败: user={user_id}, level={level}, error={e}")
            raise MemoryRetrievalError(f"检索记忆失败: {e}") from e


# 全局实例初始化  # 全局实例注释
memory_manager = None  # 记忆管理器全局实例
memory = None  # 记忆类全局实例

try:  # 尝试初始化�    memory_manager = MemoryManager()  # 创建记忆管理器实例
    memory = Memory()  # 创建记忆类实例
    print("【成功】 PostgreSQL Memory system initialized successfully")  # 打印成功消息
except Exception as e:  # 捕获异常
    print(f"[ERROR] Failed to initialize memory system: {e}")  # 打印错误消息
    memory_manager = None  # 清空管理器
    memory = None  # 清空记忆


# =============================================================================
# 总结性注释：文件角色、关联关系与核心效果
# =============================================================================
#
# 【文件角色】
# 本文件（memory.py）是 SiliconBase V5 系统的"记忆中心"核心模块，负责全系统的记忆存储、
# 查询和管理。实现五层记忆架构（L1-L5），支持PostgreSQL持久化存储和六维评分体系。
# 是系统的"记忆大脑"，为AI Agent提供长期和短期记忆能力。
#
# 【五层记忆架构】
# - L1 (working): 工作记忆，当前会话上下文，即时丢弃，默认1天过期
# - L2 (short):   短期记忆，原始对话记录，默认1天过期
# - L3 (medium):  中期记忆，高价值经验、失败教训，持久存储
# - L4 (evolve):  长期记忆，成功经验、进化知识，持久存储
# - L5 (execution): 执行记忆，工具执行记录、性能统计，持久存储
#
# 【六维评分体系】
# 每条记忆都有六维评分（1-5分），用于评估记忆价值：
# - emotional_temperature (25%): 情感温度
# - ethical_safety (20%): 伦理安全
# - self_growth (20%): 自我成长
# - execution_effectiveness (15%): 执行成效
# - sustainability (15%): 存续保障
# - inspiration_innovation (5%): 灵感创新
# 综合得分计算加权平均值，等级分为S/A/B/C/D五级。
#
# 【核心类说明】
# 1. PostgresConnectionPool: PostgreSQL连接池管理（单例模式）
#    - 支持动态配置更新
#    - 连接池状态监控
#    - 异常安全关闭
#
# 2. _PostgresUserMemoryStore: PostgreSQL用户记忆存储实现
#    - 单用户隔离存储
#    - 读写锁保护并发安全
#    - CRUD操作（增删改查）
#    - 向量同步（与vector_memory集成）
#    - 批量查询优化
#
# 3. UserMemoryStore: 用户存储代理类
#    - 代理到_PostgresUserMemoryStore
#    - 向后兼容接口
#
# 4. MemoryManager: 记忆管理器（单例模式）
#    - 多用户管理
#    - 自动清理过期数据（后台线程）
#    - 优雅退出支持
#    - 上下文管理器支持
#
# 5. Memory: 兼容旧接口的记忆类
#    - 使用默认用户
#    - 简化接口供旧代码使用
#    - 特殊方法（add_ai_memory, save_reflection等）
#
# 【关联文件】
# 1. core/vector_memory.py            - 向量记忆系统
#    * 关系：双向同步
#    * 交互：_sync_to_vector(), _delete_from_vector()
#
# 2. core/dependency_utils.py         - 依赖管理工具
#    * 关系：读写锁依赖
#    * 交互：rwlock_dep.get("rwlock")
#
# 3. core/config.py                   - 配置系统
#    * 关系：配置读取
#    * 交互：数据库连接配置
#
# 4. core/logger.py                   - 日志系统
#    * 关系：操作日志
#    * 交互：logger.info/debug/error/warning
#
# 5. core/data_lifecycle.py           - 数据生命周期管理
#    * 关系：数据压缩/归档/清理
#    * 交互：存储统计、过期数据清理
#
# 【数据库表结构】
# 表名: memories
# - id: VARCHAR(64) 主键
# - user_id: VARCHAR(64) 非空，用户隔离
# - layer: VARCHAR(20) 非空，记忆层级
# - mem_type: VARCHAR(50) 非空，记忆类型
# - content: TEXT 非空，记忆内容（JSON）
# - scene: VARCHAR(255)，场景指纹
# - rating: INTEGER，评分0-10
# - value_assessment: JSONB，六维评分
# - context: JSONB，上下文信息
# - created_at: TIMESTAMP，创建时间
# - expire_at: TIMESTAMP，过期时间
# - compressed: INTEGER，压缩标记
# - updated_at: TIMESTAMP，更新时间
#
# 【达到的效果】
# 1. 五层记忆管理：清晰区分不同生命周期的记忆数据
# 2. 多租户隔离：通过user_id实现用户数据隔离
# 3. 六维评分：量化记忆价值，支持智能检索
# 4. 向量同步：与向量记忆系统双向同步，支持语义检索
# 5. 自动清理：后台线程自动清理过期数据
# 6. 连接池管理：高效管理PostgreSQL连接资源
# 7. 向后兼容：保留旧接口支持平滑过渡
# 8. 线程安全：读写锁保护并发操作
#
# 【使用场景】
# - 存储AI Agent的对话历史（L2短期记忆）
# - 记录成功经验供未来学习（L4长期记忆）
# - 保存工具执行记录用于分析（L5执行记忆）
# - 根据六维评分检索高价值记忆
# - 多用户环境下的记忆隔离管理
#
# =============================================================================
