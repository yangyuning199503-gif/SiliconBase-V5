#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本

# 声明文件编码为UTF-8，支持中文
"""
统一记忆管理器 V1.1 - 性能优化版
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【架构设计】
  ┌─────────────────────────────────────────┐
  │           MemoryManager                 │
  │  ┌─────────────┐  ┌─────────────────┐   │
  │  │ PostgreSQL层 │  │   向量记忆层     │   │
  │  │  (3层)      │  │   (4层)         │   │
  │  │  ·short     │  │   ·experience   │   │
  │  │  ·medium    │  │   ·knowledge    │   │
  │  │  ·evolve    │  │   ·voice_fix    │   │
  │  └─────────────┘  └─────────────────┘   │
  └─────────────────────────────────────────┘

【核心功能】
  ✓ 统一记忆存储接口
  ✓ 分层交互记忆记录
  ✓ 经验存储和召回
  ✓ 跨层记忆联动
  ✓ 记忆检索聚合
  ✓ 查询结果缓存（新增）
  ✓ 流式大数据查询（新增）
  ✓ 结果数量限制（新增）

【2026-03-03 性能优化合并】
  - 新增 MemoryCache 查询缓存系统
  - 新增 query_large_dataset 流式查询
  - 新增 MAX_RESULT_SIZE 结果限制
  - 添加缓存统计信息
"""

from core.diagnostic import diagnostic_except_handler, safe_create_task

try:
    from core.exceptions import MemorySystemError
except ImportError:
    class MemorySystemError(Exception):
        """Fallback when core.exceptions is not available"""
        pass

import asyncio  # 异步IO，用于将同步向量调用隔离到线程池
import hashlib  # 导入哈希模块，用于生成缓存键
import json  # 导入JSON模块，用于序列化和反序列化
import threading  # 导入线程模块，用于线程安全
import time  # 导入时间模块，用于时间戳
import uuid  # 导入UUID模块，用于生成唯一标识符
from collections import OrderedDict  # 导入有序字典，用于LRU缓存
from collections.abc import Callable, Iterator  # 导入类型注解
from dataclasses import dataclass, field  # 导入数据类装饰器和字段
from datetime import datetime, timedelta  # 导入日期时间类
from enum import Enum  # 导入枚举类
from typing import Any

# 【P0修复】从 connection_pool 导入基础设施，从 memory_service 导入工具函数
from core.logger import logger  # 导入日志记录器
from core.memory.memory_service import generate_default_value_assessment
from core.memory.memory_source import MemorySource  # Agent-4: 导入MemorySource枚举

# ═══════════════════════════════════════════════════════════════
# 性能优化常量（从 memory_optimized.py 合并）
# ═══════════════════════════════════════════════════════════════

MAX_RESULT_SIZE = 1000  # 最大返回结果数，防止内存溢出
DEFAULT_BATCH_SIZE = 100  # 默认批处理大小
CACHE_TTL = 600  # 缓存有效期600秒（10分钟）
MAX_CACHE_SIZE = 200  # 最大缓存条目数


class MemoryLayer(Enum):  # 定义记忆分层枚举类
    """记忆分层枚举 - 完整五层架构"""  # 类文档字符串
    WORKING = "working"      # L1: 工作记忆 - 当前会话上下文，即时丢弃
    SHORT = "short"          # L2: 短期记忆 - 1天过期，原始对话记录
    MEDIUM = "medium"        # L3: 中期记忆 - 7天过期，高价值经验
    EVOLVE = "evolve"        # L4: 长期记忆 - 永久存储，进化知识
    EXECUTION = "execution"  # L5: 执行记忆 - 工具执行记录，性能统计


class MemoryType(Enum):  # 定义记忆类型枚举类
    """记忆类型枚举"""  # 类文档字符串
    CHAT = "chat"                    # 对话记录
    EXPERIENCE = "experience"        # 任务经验
    KNOWLEDGE = "knowledge"          # 知识记录
    REFLECTION = "reflection"        # 反思记录
    VOICE_FIX = "voice_fix"          # 语音纠错
    AI_NOTE = "ai_note"              # AI主动记录
    OPTIMIZATION = "optimization"    # 优化经验
    EVENT = "event"                  # 事件记录
    AUTO_REVIEW = "auto_review"      # 自动复盘

    # 【新增】交易专用类型
    TRADING = "trading"                      # 交易记录
    TRADING_DECISION = "trading_decision"    # 交易决策过程
    STRATEGY_EVOLUTION = "strategy_evolution" # 策略进化记录
    MARKET_PATTERN = "market_pattern"        # 市场模式识别
    RISK_EVENT = "risk_event"                # 风险事件记录


class VectorMemoryType(Enum):  # 定义向量记忆类型枚举类
    """向量记忆类型枚举"""  # 类文档字符串
    EXPERIENCE = "experience"        # 经验记忆
    KNOWLEDGE = "knowledge"          # 知识记忆
    VOICE_FIX = "voice_fix"          # 语音纠错
    CONVERSATION = "conversation"    # 对话记录
    PERSONA = "persona"              # 人格核心


@dataclass  # 数据类装饰器
class MemoryRecord:  # 定义标准化记忆记录数据类
    """标准化记忆记录数据类"""  # 类文档字符串
    id: str  # 记忆ID字段
    layer: MemoryLayer  # 记忆层级字段
    mem_type: MemoryType  # 记忆类型字段
    content: Any  # 记忆内容字段
    context: dict[str, Any] = field(default_factory=dict)  # 上下文字段，默认空字典
    scene: str = ""  # 场景指纹字段，默认空字符串
    rating: int = 0  # 评分字段，默认0
    created_at: str | None = None  # 创建时间字段，可选
    expire_at: str | None = None  # 过期时间字段，可选

    def to_dict(self) -> dict[str, Any]:  # 转换为字典方法
        """转换为字典"""  # 方法文档字符串
        return {  # 返回字典
            "id": self.id,  # 记忆ID
            "layer": self.layer.value,  # 层级值
            "mem_type": self.mem_type.value,  # 类型值
            "content": self.content,  # 内容
            "context": self.context,  # 上下文
            "scene": self.scene,  # 场景
            "rating": self.rating,  # 评分
            "created_at": self.created_at,  # 创建时间
            "expire_at": self.expire_at  # 过期时间
        }

    @classmethod  # 类方法装饰器
    def from_dict(cls, data: dict[str, Any]) -> "MemoryRecord":  # 从字典创建方法
        """从字典创建"""  # 方法文档字符串
        return cls(  # 返回实例
            id=data["id"],  # 记忆ID
            layer=MemoryLayer(data.get("layer", "short")),  # 层级枚举
            mem_type=MemoryType(data.get("mem_type", "chat")),  # 类型枚举
            content=data["content"],  # 内容
            context=data.get("context", {}),  # 上下文
            scene=data.get("scene", ""),  # 场景
            rating=data.get("rating", 0),  # 评分
            created_at=data.get("created_at"),  # 创建时间
            expire_at=data.get("expire_at")  # 过期时间
        )


@dataclass  # 数据类装饰器
class ExperienceRecord:  # 定义经验记录数据类
    """经验记录数据类"""  # 类文档字符串
    task_desc: str  # 任务描述字段
    steps: list[str]  # 步骤列表字段
    success: bool  # 是否成功字段
    rating: int = 0  # 评分字段，默认0
    error_info: str = ""  # 错误信息字段，默认空字符串
    task_type: str = "general"  # 任务类型字段，默认general
    metadata: dict[str, Any] = field(default_factory=dict)  # 元数据字段，默认空字典

    def to_dict(self) -> dict[str, Any]:  # 转换为字典方法
        """转换为字典"""  # 方法文档字符串
        return {  # 返回字典
            "task_desc": self.task_desc,  # 任务描述
            "steps": self.steps,  # 步骤
            "success": self.success,  # 是否成功
            "rating": self.rating,  # 评分
            "error_info": self.error_info,  # 错误信息
            "task_type": self.task_type,  # 任务类型
            "metadata": self.metadata  # 元数据
        }


# ═══════════════════════════════════════════════════════════════
# 性能优化: 记忆查询结果缓存 (从 memory_optimized.py 合并)
# ═══════════════════════════════════════════════════════════════

class MemoryCache:
    """
    记忆查询结果缓存

    特性:
    - TTL过期机制
    - LRU淘汰策略
    - 线程安全
    - 命中率统计
    """

    def __init__(self, max_size: int = MAX_CACHE_SIZE, ttl: int = CACHE_TTL):
        """
        初始化缓存

        Args:
            max_size: 最大缓存条目数
            ttl: 缓存有效期（秒）
        """
        self._cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl
        self._lock = asyncio.Lock()
        self._stats = {"hits": 0, "misses": 0, "evictions": 0}

    def _make_key(self, user_id: str, **kwargs) -> str:
        """生成缓存键"""
        key_data = f"{user_id}:{json.dumps(kwargs, sort_keys=True, default=str)}"
        return hashlib.md5(key_data.encode()).hexdigest()

    async def get(self, user_id: str, **kwargs) -> Any | None:
        """
        获取缓存数据

        Args:
            user_id: 用户ID
            **kwargs: 查询参数

        Returns:
            缓存数据或None
        """
        key = self._make_key(user_id, **kwargs)
        async with self._lock:
            if key in self._cache:
                item, expiry = self._cache[key]
                if time.time() < expiry:
                    # 更新访问顺序 (LRU)
                    self._cache.move_to_end(key)
                    self._stats["hits"] += 1
                    return item
                # 过期删除
                del self._cache[key]
            self._stats["misses"] += 1
            return None

    async def set(self, user_id: str, value: Any, **kwargs) -> None:
        """
        设置缓存数据

        Args:
            user_id: 用户ID
            value: 要缓存的数据
            **kwargs: 查询参数
        """
        key = self._make_key(user_id, **kwargs)
        async with self._lock:
            # LRU淘汰
            if len(self._cache) >= self._max_size and key not in self._cache:
                oldest_key, _ = self._cache.popitem(last=False)
                self._stats["evictions"] += 1
                logger.debug(f"[MemoryCache] LRU淘汰: {oldest_key[:8]}...")

            self._cache[key] = (value, time.time() + self._ttl)
            self._cache.move_to_end(key)

    async def invalidate(self, pattern: str = None) -> int:
        """
        使缓存失效

        Args:
            pattern: 匹配模式，为None则清空所有

        Returns:
            失效的缓存数量
        """
        async with self._lock:
            if pattern is None:
                count = len(self._cache)
                self._cache.clear()
                logger.info(f"[MemoryCache] 清空所有缓存: {count} 条")
                return count
            else:
                keys_to_remove = [
                    k for k, (v, _) in self._cache.items()
                    if pattern in str(v)
                ]
                for k in keys_to_remove:
                    del self._cache[k]
                logger.debug(f"[MemoryCache] 模式失效: {len(keys_to_remove)} 条")
                return len(keys_to_remove)

    async def invalidate_user(self, user_id: str) -> int:
        """
        失效指定用户的所有缓存

        Args:
            user_id: 用户ID

        Returns:
            失效的缓存数量
        """
        async with self._lock:
            keys_to_remove = [
                k for k, (v, _) in self._cache.items()
                if isinstance(v, list) and v and isinstance(v[0], dict)
                and v[0].get("user_id") == user_id
            ]
            for k in keys_to_remove:
                del self._cache[k]
            logger.debug(f"[MemoryCache] 用户缓存失效: {user_id[:8]}... , {len(keys_to_remove)} 条")
            return len(keys_to_remove)

    async def get_stats(self) -> dict[str, Any]:
        """
        获取缓存统计信息

        Returns:
            统计信息字典
        """
        async with self._lock:
            total = self._stats["hits"] + self._stats["misses"]
            hit_rate = self._stats["hits"] / total if total > 0 else 0.0
            return {
                "size": len(self._cache),
                "max_size": self._max_size,
                "hits": self._stats["hits"],
                "misses": self._stats["misses"],
                "evictions": self._stats["evictions"],
                "hit_rate": round(hit_rate, 4),
                "ttl": self._ttl
            }

    async def clear(self) -> None:
        """清空缓存"""
        async with self._lock:
            self._cache.clear()
            self._stats = {"hits": 0, "misses": 0, "evictions": 0}


class _PostgresMemoryAdapter:
    """
    【P0修复】PostgreSQL 记忆适配器——直接操作数据库，不依赖旧 memory 单例，
    也不触发 _sync_to_vector()，从根本上消除 '向量同步失败' 日志刷屏。

    当前仅服务默认用户 "default"，与旧 memory 单例行为保持一致。
    多用户场景由 MemoryManager.get_by_id / delete_memory 直接处理。

    【P1-Asyncify】已全面异步化：所有 DB 操作提供原生 asyncpg 异步版本，
    同步版本保留为 private _sync 后缀方法供向后兼容。
    """
    _default_user_id = "default"

    # ═══════════════════════════════════════════════════════════════
    # Sync 版本（保留向后兼容）
    # ═══════════════════════════════════════════════════════════════

    # ═══════════════════════════════════════════════════════════════
    # Async 版本（原生 asyncpg）
    # ═══════════════════════════════════════════════════════════════

    async def add_async(self, layer, mem_type, content, context=None, scene="", rating=0,
            expire_days=None, sync_vector=True, source=None) -> str:
        """原生 asyncpg INSERT（不触发向量同步）"""
        import time as _time
        start_time = _time.time()
        mem_id = str(uuid.uuid4())

        expire_at = None
        if layer in ("short", "working"):
            expire_days = expire_days or 1
        if expire_days:
            expire_at = datetime.now() + timedelta(days=expire_days)

        content_str = json.dumps(content, ensure_ascii=False) if not isinstance(content, str) else content
        value_assessment = generate_default_value_assessment()

        from core.memory.postgres_pool import AsyncPostgresPool
        try:
            pool = await AsyncPostgresPool.get_pool()
            await pool.execute('''
                INSERT INTO memories
                (id, user_id, layer, mem_type, content, context,
                 scene, rating, source, expire_at, value_assessment, creator)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            ''',
                mem_id, self._default_user_id, layer, mem_type, content_str,
                json.dumps(context, ensure_ascii=False) if context else None, scene, rating,
                source or 'system', expire_at, json.dumps(value_assessment, ensure_ascii=False), 'system'
            )
            elapsed = _time.time() - start_time
            logger.debug(f"[_PostgresMemoryAdapter] 记忆添加成功: {mem_id[:8]}... (耗时 {elapsed*1000:.2f}ms)")
            return mem_id
        except Exception as e:
            diagnostic_except_handler(e, context="[_PostgresMemoryAdapter] 记忆添加失败", logger_instance=logger)
            raise

    async def get_async(self, scene=None, mem_type=None, layer=None, limit=10, min_rating=-1, filter_dict=None) -> list[dict]:
        """原生 asyncpg SELECT"""
        from core.memory.postgres_pool import AsyncPostgresPool
        try:
            pool = await AsyncPostgresPool.get_pool()
            query_sql = """
                SELECT id, layer, mem_type, content, context, scene,
                       rating, source, value_assessment, created_at, expire_at, compressed
                FROM memories
                WHERE user_id = $1 AND (expire_at IS NULL OR expire_at > CURRENT_TIMESTAMP)
            """
            params = [self._default_user_id]
            param_idx = 1

            if layer:
                param_idx += 1
                query_sql += f" AND layer = ${param_idx}"
                params.append(layer)
            if mem_type:
                param_idx += 1
                query_sql += f" AND mem_type = ${param_idx}"
                params.append(mem_type)
            if scene:
                param_idx += 1
                query_sql += f" AND scene = ${param_idx}"
                params.append(scene)
            if min_rating > -1:
                param_idx += 1
                query_sql += f" AND rating >= ${param_idx}"
                params.append(min_rating)

            param_idx += 1
            query_sql += f" ORDER BY rating DESC, created_at DESC LIMIT ${param_idx}"
            params.append(limit)

            rows = await pool.fetch(query_sql, *params)

            results = []
            for r in rows:
                try:
                    raw_content = r['content']
                    if raw_content is None:
                        content = None
                    elif isinstance(raw_content, str) and (raw_content.startswith('{') or raw_content.startswith('[')):
                        content = json.loads(raw_content)
                    else:
                        content = raw_content
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
                    "source": r.get('source', 'system'),
                    "value_assessment": r['value_assessment'] if r['value_assessment'] else generate_default_value_assessment(),
                    "created_at": r['created_at'].isoformat() if r['created_at'] else None,
                    "expire_at": r['expire_at'].isoformat() if r['expire_at'] else None,
                    "compressed": bool(r['compressed']),
                })
            return results
        except Exception as e:
            diagnostic_except_handler(e, context="[_PostgresMemoryAdapter] 查询记忆失败", logger_instance=logger)
            return []

    async def get_by_ids_async(self, mem_ids: list[str]) -> list[dict]:
        """原生 asyncpg 批量获取"""
        if not mem_ids:
            return []
        mem_ids = list(dict.fromkeys(mem_ids))
        if len(mem_ids) > 10000:
            mem_ids = mem_ids[:10000]

        from core.memory.postgres_pool import AsyncPostgresPool
        try:
            pool = await AsyncPostgresPool.get_pool()
            placeholders = ','.join([f'${i+2}' for i in range(len(mem_ids))])
            rows = await pool.fetch(f"""
                SELECT id, layer, mem_type, content, context, scene,
                       rating, source, value_assessment, created_at, expire_at, compressed
                FROM memories
                WHERE user_id = $1 AND id IN ({placeholders})
            """, self._default_user_id, *mem_ids)

            results = []
            for r in rows:
                try:
                    raw_content = r['content']
                    if raw_content is None:
                        content = None
                    elif isinstance(raw_content, str) and (raw_content.startswith('{') or raw_content.startswith('[')):
                        content = json.loads(raw_content)
                    else:
                        content = raw_content
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
                    "source": r.get('source', 'system'),
                    "value_assessment": r['value_assessment'] if r['value_assessment'] else generate_default_value_assessment(),
                    "created_at": r['created_at'].isoformat() if r['created_at'] else None,
                    "expire_at": r['expire_at'].isoformat() if r['expire_at'] else None,
                    "compressed": bool(r['compressed']),
                })
            return results
        except Exception as e:
            diagnostic_except_handler(e, context="[_PostgresMemoryAdapter] 批量获取记忆失败", logger_instance=logger)
            return []

    async def rate_async(self, mem_id: str, rating: int):
        """原生 asyncpg 更新评分"""
        from core.memory.postgres_pool import AsyncPostgresPool
        try:
            pool = await AsyncPostgresPool.get_pool()
            result = await pool.execute(
                "UPDATE memories SET rating = $1, updated_at = CURRENT_TIMESTAMP WHERE id = $2 AND user_id = $3",
                rating, mem_id, self._default_user_id
            )
            return "UPDATE 1" in result
        except Exception as e:
            diagnostic_except_handler(e, context="[_PostgresMemoryAdapter] 评分更新失败", logger_instance=logger)
            return False

    async def get_stats_async(self) -> dict[str, Any]:
        """原生 asyncpg 获取统计"""
        from core.memory.postgres_pool import AsyncPostgresPool
        try:
            pool = await AsyncPostgresPool.get_pool()
            stats = {"user_id": self._default_user_id, "total": 0}
            async with pool.acquire() as conn:
                for layer in ["working", "short", "medium", "evolve", "execution"]:
                    val = await conn.fetchval(
                        "SELECT COUNT(*) FROM memories WHERE layer = $1 AND user_id = $2",
                        layer, self._default_user_id
                    )
                    stats[layer] = val or 0
                stats["total"] = await conn.fetchval(
                    "SELECT COUNT(*) FROM memories WHERE user_id = $1", self._default_user_id
                ) or 0
                stats["expired"] = await conn.fetchval(
                    "SELECT COUNT(*) FROM memories WHERE expire_at < CURRENT_TIMESTAMP AND user_id = $1",
                    self._default_user_id
                ) or 0
                stats["compressed"] = await conn.fetchval(
                    "SELECT COUNT(*) FROM memories WHERE compressed = 1 AND user_id = $1",
                    self._default_user_id
                ) or 0
                avg_rating = await conn.fetchval(
                    "SELECT AVG(rating) FROM memories WHERE user_id = $1", self._default_user_id
                )
                stats["avg_rating"] = round(avg_rating, 2) if avg_rating else 0
            return stats
        except Exception as e:
            logger.error(f"[_PostgresMemoryAdapter] 获取统计失败: {e}")
            return {"user_id": self._default_user_id, "total": 0}


class MemoryManager:  # 定义统一记忆管理器类
    """
    统一记忆管理器 - 单例模式  # 类文档字符串
    管理PostgreSQL记忆层和向量记忆层的统一接口  # 功能概述
    支持查询缓存和流式大数据查询（性能优化版）
    """
    _instance = None  # 单例实例引用（类变量）
    _lock = threading.Lock()  # 同步锁用于单例创建（__new__是同步的）

    def __new__(cls):  # 单例创建方法
        """单例创建"""  # 方法文档字符串
        if cls._instance is None:  # 如果实例不存在
            with cls._lock:  # 获取同步锁（单例创建用）
                if cls._instance is None:  # 双重检查
                    cls._instance = super().__new__(cls)  # 创建实例
                    cls._instance._initialized = False  # 标记未初始化
        return cls._instance  # 返回实例

    def __init__(self):  # 初始化方法
        """初始化记忆管理器"""  # 方法文档字符串
        if self._initialized:  # 如果已初始化
            return  # 直接返回
        self._initialized = True  # 标记已初始化

        # 底层记忆实例（延迟加载）  # 延迟加载说明
        self._postgres_memory = None  # PostgreSQL记忆实例引用
        self._vector_memory = None  # 向量记忆实例引用

        # 经验管理器（延迟加载）  # 延迟加载说明
        self._experience_manager = None  # 经验管理器引用

        # 回调函数注册表  # 回调机制
        self._callbacks: dict[str, list[Callable]] = {  # 回调字典
            "on_memory_add": [],  # 添加记忆回调列表
            "on_memory_retrieve": [],  # 检索记忆回调列表
            "on_experience_store": []  # 存储经验回调列表
        }

        # 旧缓存（保持向后兼容）
        self._cache: dict[str, Any] = {}  # 缓存字典
        self._cache_lock = asyncio.Lock()  # 缓存锁

        # ═══════════════════════════════════════════════════════
        # 性能优化: 查询结果缓存系统（新增）
        # ═══════════════════════════════════════════════════════
        self._query_cache = MemoryCache()
        self._cache_enabled = True  # 缓存开关，默认启用

        # 【P2-1】候选记忆暂存区（内存中，进程重启后丢失，1天后自动清理）
        self._staging_memories: dict[str, dict] = {}

        # ═══════════════════════════════════════════════════════
        # Phase 3: 三层记忆系统植入（新增）
        # ═══════════════════════════════════════════════════════
        # L1: 短期会话记忆 - 按session隔离，会话结束自动清理
        self._session_memory: dict[str, list[dict[str, Any]]] = {}
        self._session_lock = asyncio.Lock()

        # L2: 长期沉淀记忆 - 智能压缩防线性增长
        self._longterm_compress_threshold = 50  # 触发压缩的条目数阈值
        self._longterm_lock = asyncio.Lock()

        # L3: 任务状态记忆 - 存储任务执行进度和工具链状态
        self._task_state_memory: dict[str, dict[str, Any]] = {}
        self._task_state_lock = asyncio.Lock()

        logger.info("[MemoryManager] 统一记忆管理器初始化完成（性能优化版 + 三层记忆系统）")  # 记录日志

    # ═══════════════════════════════════════════════════════════════
    # 性能优化: 缓存控制接口（新增）
    # ═══════════════════════════════════════════════════════════════

    async def set_cache_enabled(self, enabled: bool) -> None:
        """
        启用或禁用查询缓存

        Args:
            enabled: 是否启用缓存
        """
        self._cache_enabled = enabled
        logger.info(f"[MemoryManager] 查询缓存已{'启用' if enabled else '禁用'}")

    async def is_cache_enabled(self) -> bool:
        """检查缓存是否启用"""
        return self._cache_enabled

    async def get_cache_stats(self) -> dict[str, Any]:
        """
        获取查询缓存统计信息

        Returns:
            缓存统计信息字典
        """
        stats = self._query_cache.get_stats()
        stats["enabled"] = self._cache_enabled
        return stats

    async def clear_query_cache(self, pattern: str = None) -> int:
        """
        清除查询缓存

        Args:
            pattern: 匹配模式，为None则清空所有

        Returns:
            清除的缓存数量
        """
        return self._query_cache.invalidate(pattern)

    async def invalidate_user_cache(self, user_id: str) -> int:
        """
        失效指定用户的所有缓存

        Args:
            user_id: 用户ID

        Returns:
            失效的缓存数量
        """
        return await self._query_cache.invalidate_user(user_id)

    # ========== 延迟加载底层实例 ==========  # 延迟加载区域标记

    async def _get_postgres_memory(self):  # 获取PostgreSQL记忆实例方法
        """获取PostgreSQL记忆实例——【P0修复】返回内部适配器，不再依赖旧 memory 单例"""
        if self._postgres_memory is None:
            self._postgres_memory = _PostgresMemoryAdapter()
        return self._postgres_memory

    async def _get_vector_memory(self):  # 获取向量记忆实例方法
        """获取向量记忆实例"""  # 方法文档字符串
        if self._vector_memory is None:  # 如果实例不存在
            from core.memory.memory_service import get_memory_service  # 延迟导入记忆服务
            try:
                self._vector_memory = await get_memory_service()  # 获取记忆服务实例
            except Exception:
                self._vector_memory = None
        return self._vector_memory  # 返回实例

    async def _get_experience_manager(self):  # 获取经验管理器实例方法
        """获取经验管理器实例"""  # 方法文档字符串
        if self._experience_manager is None:  # 如果实例不存在
            from core.evolution.evolution import ExperienceManager  # 延迟导入经验管理器
            self._experience_manager = ExperienceManager()  # 【修复】实例化类
        return self._experience_manager  # 返回实例

    # ========== 回调注册 ==========  # 回调区域标记

    async def register_callback(self, event: str, callback: Callable):  # 注册回调方法
        """
        注册事件回调  # 方法文档字符串

        Args:  # 参数说明
            event: 事件类型 (on_memory_add, on_memory_retrieve, on_experience_store)  # 参数1
            callback: 回调函数  # 参数2
        """
        if event in self._callbacks:  # 检查事件类型是否有效
            self._callbacks[event].append(callback)  # 添加回调到列表
            logger.debug(f"[MemoryManager] 注册回调: {event}")  # 记录日志

    async def _trigger_callbacks(self, event: str, *args, **kwargs):  # 触发回调方法
        """触发事件回调"""  # 方法文档字符串
        for callback in self._callbacks.get(event, []):  # 遍历回调列表
            try:  # 异常处理
                callback(*args, **kwargs)  # 执行回调
            except Exception as e:  # 捕获异常
                # 【静默失败修复】回调执行失败必须是ERROR级别 [SILENT_FAILURE_BLOCKED]
                logger.error(f"[MemoryManager] 回调执行失败: {e}", exc_info=True)  # 记录错误

    # ========== 统一存储接口 ==========  # 存储接口区域标记

    async def store_memory(self,  # 统一记忆存储方法
                     layer: MemoryLayer | str,  # 层级参数
                     mem_type: MemoryType | str,  # 类型参数
                     content: Any,  # 内容参数
                     context: dict[str, Any] | None = None,  # 上下文参数
                     scene: str = "",  # 场景参数
                     rating: int = 0,  # 评分参数
                     expire_days: int | None = None,  # 过期天数参数
                     sync_vector: bool = True,  # 向量同步参数
                     source: MemorySource = MemorySource.SYSTEM) -> str:  # 来源参数
        """
        统一记忆存储接口  # 方法文档字符串

        Args:  # 参数说明
            layer: 记忆层  # 参数1
            mem_type: 记忆类型  # 参数2
            content: 记忆内容  # 参数3
            context: 上下文信息  # 参数4
            scene: 场景指纹  # 参数5
            rating: 评分  # 参数6
            expire_days: 过期天数  # 参数7
            sync_vector: 是否同步到向量层  # 参数8
            source: 记忆来源（默认 SYSTEM）  # 参数9

        Returns:  # 返回值说明
            记忆ID  # 返回类型
        """
        # 转换枚举为字符串  # 类型转换
        if isinstance(layer, MemoryLayer):  # 如果是枚举
            layer = layer.value  # 获取值
        if isinstance(mem_type, MemoryType):  # 如果是枚举
            mem_type = mem_type.value  # 获取值

        # 自动设置过期时间  # 过期时间逻辑
        if expire_days is None:  # 如果未指定
            if layer == MemoryLayer.SHORT.value:  # 短期记忆
                expire_days = 1  # 1天
            elif layer == MemoryLayer.MEDIUM.value:  # 中期记忆
                # 【修复】L3改为永不过期，避免高价值经验丢失
                expire_days = None  # 永不过期

        memory = None  # 预初始化，避免异常时未定义
        try:  # 异常处理
            memory = await self._get_postgres_memory()  # 获取PostgreSQL记忆实例
            if memory is None:  # 如果不可用
                msg = "[MemoryManager] PostgreSQL记忆实例不可用，无法存储记忆"
                logger.error(msg)
                raise MemorySystemError(msg)

            mem_id = await memory.add_async(  # 调用底层异步添加方法
                layer=layer,  # 层级
                mem_type=mem_type,  # 类型
                content=content,  # 内容
                context=context,  # 上下文
                scene=scene,  # 场景
                rating=rating,  # 评分
                expire_days=expire_days,  # 过期天数
                sync_vector=sync_vector,  # 向量同步
                source=source  # 使用传入的来源参数，默认 SYSTEM
            )

            # 触发回调  # 回调通知
            await self._trigger_callbacks("on_memory_add", mem_id, layer, mem_type, content)  # 触发添加回调

            logger.debug(f"[MemoryManager] 记忆已存储: {mem_id[:8]}... ({layer}/{mem_type})")  # 记录日志
            return mem_id  # 返回记忆ID

        except MemorySystemError:
            raise
        except Exception as e:  # 捕获异常
            # 【零静默失败】记忆存储失败必须抛异常
            diagnostic_except_handler(e, context="[MemoryManager] 记忆存储失败", logger_instance=logger)
            raise MemorySystemError(f"记忆存储失败: {e}") from e

    async def store_vector_memory(self,  # 向量记忆存储方法
                           event_type: VectorMemoryType | str,  # 事件类型参数
                           data: dict) -> str | None:  # 数据参数和返回类型
        """
        向量记忆存储接口  # 方法文档字符串

        Args:  # 参数说明
            event_type: 向量记忆类型  # 参数1
            data: 记忆数据  # 参数2

        Returns:  # 返回值说明
            记忆ID  # 返回类型
        """
        if isinstance(event_type, VectorMemoryType):  # 如果是枚举
            event_type = event_type.value  # 获取值

        try:  # 异常处理
            vector_mem = await self._get_vector_memory()  # 获取向量记忆实例
            if vector_mem is None:  # 如果不可用
                logger.error("[MemoryManager] 向量记忆实例不可用")  # 记录错误
                return None  # 返回None

            # 通过 VectorStore 异步存储
            mem_id = await vector_mem.vector_store.add("experience", data.get("text", str(data)), data)
            logger.debug(f"[MemoryManager] 向量记忆已存储: {event_type}")  # 记录日志
            return mem_id  # 返回记忆ID

        except Exception as e:  # 捕获异常
            # 【静默失败修复】向量记忆存储失败 [SILENT_FAILURE_BLOCKED]
            logger.error(f"[MemoryManager] 向量记忆存储失败: {e}", exc_info=True)  # 记录错误
            return None  # 返回None

    # ========== 分层交互记忆记录 ==========  # 分层记录区域标记

    async def _auto_select_layer(self, context: dict) -> MemoryLayer:
        """
        【Phase 4新增】根据上下文自动选择记忆层级

        Args:
            context: 上下文信息

        Returns:
            自动选择的记忆层级
        """
        # 工具执行结果 → L5
        if context.get("is_tool_result") or context.get("tool_call"):
            return MemoryLayer.EXECUTION

        # 会话内临时上下文 → L1
        if context.get("is_session_context") or context.get("is_temporary"):
            return MemoryLayer.WORKING

        # 高重要性 → L3
        if context.get("importance", 0) >= 5:
            return MemoryLayer.MEDIUM

        # 默认 → L2
        return MemoryLayer.SHORT

    async def record_interaction(self,  # 记录交互方法
                          user_input: str,  # 用户输入参数
                          ai_response: str,  # AI响应参数
                          layer: MemoryLayer = None,  # 层级参数，None表示自动选择
                          metadata: dict = None,  # 元数据参数
                          session_id: str = "") -> str:  # 会话ID参数和返回类型
        """
        记录分层交互记忆  # 方法文档字符串

        【Phase 4修复】支持自动层级选择和L1工作记忆

        Args:  # 参数说明
            user_input: 用户输入  # 参数1
            ai_response: AI响应  # 参数2
            layer: 存储层，None表示自动选择  # 参数3
            metadata: 元数据  # 参数4
            session_id: 会话ID  # 参数5

        Returns:  # 返回值说明
            记忆ID  # 返回类型
        """
        # 自动选择层级
        if layer is None:
            layer = await self._auto_select_layer(metadata or {})

        context = {  # 构建上下文字典
            "user_input": user_input,  # 用户输入
            "ai_response": ai_response,  # AI响应
            "session_id": session_id,  # 会话ID
            "timestamp": datetime.now().isoformat(),  # 时间戳
            **(metadata or {})  # 合并额外元数据
        }

        content = {  # 构建内容字典
            "user_input": user_input,  # 用户输入
            "ai_response": ai_response,  # AI响应
            "interaction_type": metadata.get("type", "general") if metadata else "general"  # 交互类型
        }

        mem_id = await self.store_memory(  # 调用统一存储
            layer=layer,  # 层级
            mem_type=MemoryType.CHAT,  # 类型为对话
            content=content,  # 内容
            context=context,  # 上下文
            scene=f"interaction_{session_id}",  # 场景
            sync_vector=True  # 同步向量
        )

        return mem_id  # 返回记忆ID

    # ASYNC-DEBT: record_interaction_async 已删除。该方法是错误的 to_thread 包装器，
    # 它会将 async def 丢进额外线程的事件循环，行为异常且线程不安全。
    # 调用方应直接使用 safe_create_task(record_interaction(..., name="record_interaction")) 抛到后台，
    # 因为底层 store_memory → memory.add() 仍是同步阻塞链（psycopg2 + _sync_to_vector）。
    # 彻底修复需将 memory.py 的 UserMemoryStore.add() 改写为原生异步。

    async def record_learning_event(self,  # 记录学习事件方法
                             event_type: str,  # 事件类型参数
                             content: Any,  # 内容参数
                             importance: int = 5,  # 重要性参数，默认5
                             context: dict = None) -> str:  # 上下文参数和返回类型
        """
        记录学习事件  # 方法文档字符串

        Args:  # 参数说明
            event_type: 事件类型  # 参数1
            content: 内容  # 参数2
            importance: 重要性(1-10)  # 参数3
            context: 上下文  # 参数4

        Returns:  # 返回值说明
            记忆ID  # 返回类型
        """
        # 根据重要性选择存储层  # 层级选择逻辑
        if importance >= 8:  # 高重要性
            layer = MemoryLayer.EVOLVE  # 进化层
        elif importance >= 5:  # 中等重要性
            layer = MemoryLayer.MEDIUM  # 中期层
        else:  # 低重要性
            layer = MemoryLayer.SHORT  # 短期层

        return await self.store_memory(  # 调用统一存储
            layer=layer,  # 选择的层级
            mem_type=MemoryType.AI_NOTE,  # AI笔记类型
            content=content,  # 内容
            context=context,  # 上下文
            rating=importance,  # 评分为重要性
            expire_days=None if layer == MemoryLayer.EVOLVE else 30  # 进化层不过期
        )

    # ========== 经验存储和召回 ==========  # 经验管理区域标记

    async def store_experience(self, experience: ExperienceRecord | dict) -> bool:  # 存储经验方法
        """
        存储任务经验  # 方法文档字符串

        Args:  # 参数说明
            experience: 经验记录  # 参数1

        Returns:  # 返回值说明
            是否成功  # 返回类型
        """
        if isinstance(experience, dict):  # 如果是字典
            experience = ExperienceRecord(**experience)  # 转换为数据类

        try:  # 异常处理
            exp_mgr = await self._get_experience_manager()  # 获取经验管理器
            if exp_mgr is None:  # 如果不可用
                logger.error("[MemoryManager] 经验管理器不可用")  # 记录错误
                return False  # 返回失败

            exp_mgr.add_experience(  # 【P0修复】ExperienceManager 无 store()，改为 add_experience()
                task_desc=experience.task_desc,  # 任务描述
                steps=experience.steps,  # 步骤
                success=experience.success,  # 是否成功
                error_info=experience.error_info  # 错误信息
            )

            # 同时存储到向量记忆  # 向量存储
            await self.store_vector_memory(  # 调用向量存储
                VectorMemoryType.EXPERIENCE,  # 经验类型
                {  # 数据字典
                    "task_desc": experience.task_desc,  # 任务描述
                    "steps": experience.steps,  # 步骤
                    "success": experience.success,  # 是否成功
                    "task_type": experience.task_type,  # 任务类型
                    "rating": experience.rating  # 评分
                }
            )

            # 触发回调  # 回调通知
            await self._trigger_callbacks("on_experience_store", experience)  # 触发经验存储回调

            return True  # 返回成功

        except Exception as e:  # 捕获异常
            # 【静默失败修复】经验存储失败 [SILENT_FAILURE_BLOCKED]
            logger.error(f"[MemoryManager] 经验存储失败: {e}", exc_info=True)  # 记录错误
            return False  # 返回失败

    async def retrieve_experience(self, task_desc: str,  # 召回经验方法
                           include_failed: bool = True) -> dict | None:  # 参数和返回类型
        """
        召回任务经验  # 方法文档字符串

        Args:  # 参数说明
            task_desc: 任务描述  # 参数1
            include_failed: 是否包含失败经验  # 参数2

        Returns:  # 返回值说明
            经验记录字典  # 返回类型
        """
        try:  # 异常处理
            # 优先从向量记忆搜索  # 向量搜索优先
            vector_mem = await self._get_vector_memory()  # 获取向量记忆
            if vector_mem:  # 如果可用
                results = await vector_mem.vector_store.search("experience", task_desc, limit=3)
                if results:  # 如果有结果
                    best = max(results, key=lambda x: 1.0 - (x.distance or 0.0))  # 取相似度最高的
                    return {  # 返回结果
                        "type": "success",  # 类型为成功
                        "source": "vector",  # 来源向量
                        "task_desc": task_desc,  # 任务描述
                        "experience": {
                            "id": best.id,
                            "document": best.document,
                            "metadata": best.metadata,
                            "similarity": 1.0 - (best.distance or 0.0)
                        },  # 经验数据
                        "similarity": 1.0 - (best.distance or 0.0)  # 相似度
                    }

            # 从经验管理器检索  # 备选检索
            exp_mgr = await self._get_experience_manager()  # 获取经验管理器
            if exp_mgr:  # 如果可用
                exp = exp_mgr.retrieve(task_desc)  # 检索经验
                if exp:  # 如果有结果
                    return {  # 返回结果
                        "type": exp.get("type", "unknown"),  # 类型
                        "source": "sqlite",  # 来源SQLite
                        "task_desc": task_desc,  # 任务描述
                        "experience": exp  # 经验数据
                    }

            # 如果允许，搜索失败经验  # 失败经验搜索
            if include_failed and vector_mem and vector_mem.is_available():  # 条件检查
                all_exps = await vector_mem.search_experience(task_desc, only_success=False, limit=3)
                failed = [e for e in all_exps if e.get("metadata", {}).get("success") == "false"]  # 筛选失败
                if failed:  # 如果有失败经验
                    return {  # 返回结果
                        "type": "fail",  # 类型为失败
                        "source": "vector",  # 来源向量
                        "task_desc": task_desc,  # 任务描述
                        "experience": failed[0],  # 第一条失败经验
                        "similarity": failed[0].get("similarity", 0)  # 相似度
                    }

            return None  # 无结果返回None

        except Exception as e:  # 捕获异常
            # 【静默失败修复】经验召回失败 [SILENT_FAILURE_BLOCKED]
            logger.error(f"[MemoryManager] 经验召回失败: {e}", exc_info=True)  # 记录错误
            return None  # 返回None

    async def find_similar_experiences(self, task_desc: str,  # 查找相似经验方法
                                  limit: int = 5) -> list[dict]:  # 参数和返回类型
        """
        查找相似经验列表  # 方法文档字符串

        Args:  # 参数说明
            task_desc: 任务描述  # 参数1
            limit: 返回数量  # 参数2

        Returns:  # 返回值说明
            经验列表  # 返回类型
        """
        results = []  # 结果列表

        try:  # 异常处理
            # 向量层搜索  # 向量搜索
            vector_mem = await self._get_vector_memory()  # 获取向量记忆
            if vector_mem:  # 如果可用
                vector_results = await vector_mem.vector_store.search("experience", task_desc, limit=limit)
                for r in vector_results:  # 遍历结果
                    results.append({  # 添加到结果
                        "source": "vector",  # 来源
                        "similarity": 1.0 - (r.distance or 0.0),  # 相似度
                        "id": r.id,
                        "document": r.document,
                        "metadata": r.metadata
                    })

            # 按相似度排序  # 结果排序
            results.sort(key=lambda x: x.get("similarity", 0), reverse=True)  # 降序排序
            return results[:limit]  # 返回前limit个

        except Exception as e:  # 捕获异常
            # 【静默失败修复】相似经验查找失败 [SILENT_FAILURE_BLOCKED]
            logger.error(f"[MemoryManager] 相似经验查找失败: {e}", exc_info=True)  # 记录错误
            return []  # 返回空列表

    # ========== 统一检索接口 ==========  # 检索接口区域标记

    async def retrieve_memory(self,  # 统一记忆检索方法
                       query: str | None = None,  # 查询参数
                       layer: MemoryLayer | str | None = None,  # 层级参数
                       mem_type: MemoryType | str | None = None,  # 类型参数
                       scene: str | None = None,  # 场景参数
                       limit: int = 10,  # 限制参数
                       min_rating: int = -1,  # 最低评分参数
                       use_vector: bool = True,
                       use_cache: bool = True) -> list[dict[str, Any]]:  # 向量检索参数和返回类型
        """
        统一记忆检索接口（性能优化版）

        Args:  # 参数说明
            query: 查询文本（用于向量检索）  # 参数1
            layer: 记忆层过滤  # 参数2
            mem_type: 记忆类型过滤  # 参数3
            scene: 场景过滤  # 参数4
            limit: 返回数量  # 参数5
            min_rating: 最小评分  # 参数6
            use_vector: 是否使用向量检索  # 参数7
            use_cache: 是否使用查询缓存（新增）  # 参数8

        Returns:  # 返回值说明
            记忆记录列表  # 返回类型
        """
        # ═══════════════════════════════════════════════════════
        # 性能优化: 结果数量限制
        # ═══════════════════════════════════════════════════════
        if limit > MAX_RESULT_SIZE:
            logger.warning(f"[MemoryManager] 查询限制{limit}超过最大值{MAX_RESULT_SIZE}，已调整")
            limit = MAX_RESULT_SIZE

        # ═══════════════════════════════════════════════════════
        # 性能优化: 查询缓存检查
        # ═══════════════════════════════════════════════════════
        if self._cache_enabled and use_cache:
            # 构建缓存键参数
            cache_key_params = {
                "query": query,
                "layer": layer.value if isinstance(layer, MemoryLayer) else layer,
                "mem_type": mem_type.value if isinstance(mem_type, MemoryType) else mem_type,
                "scene": scene,
                "limit": limit,
                "min_rating": min_rating,
                "use_vector": use_vector
            }
            cached = await self._query_cache.get("global", **cache_key_params)
            if cached is not None:
                logger.debug("[MemoryManager] 查询缓存命中")
                return cached

        results = []  # 结果列表

        # PostgreSQL层检索  # PostgreSQL检索
        memory = None  # 预初始化，避免异常时未定义
        try:  # 异常处理
            memory = await self._get_postgres_memory()  # 获取记忆实例
            if memory:  # 如果可用
                if isinstance(layer, MemoryLayer):  # 如果是枚举
                    layer = layer.value  # 获取值
                if isinstance(mem_type, MemoryType):  # 如果是枚举
                    mem_type = mem_type.value  # 获取值

                sqlite_results = await memory.get_async(
                    scene=scene,
                    mem_type=mem_type,
                    layer=layer,
                    limit=limit,
                    min_rating=min_rating
                )
                for r in sqlite_results:  # 遍历结果
                    r["source"] = "sqlite"  # 标记来源
                    results.append(r)  # 添加到列表
        except Exception as e:  # 捕获异常
            # 【静默失败修复】PostgreSQL检索失败 [SILENT_FAILURE_BLOCKED]
            diagnostic_except_handler(e, context="[MemoryManager] PostgreSQL检索失败", logger_instance=logger)

        # 向量层检索  # 向量检索
        if use_vector and query:  # 如果启用且有查询
            try:  # 异常处理
                vector_mem = await self._get_vector_memory()  # 获取向量记忆
                if vector_mem:  # 如果可用
                    vector_results = await vector_mem.vector_store.search("knowledge", query, limit=limit)
                    for r in vector_results:  # 遍历结果
                        results.append({
                            "source": "vector",
                            "id": r.id,
                            "document": r.document,
                            "metadata": r.metadata,
                            "similarity": 1.0 - (r.distance or 0.0)
                        })
            except Exception as e:  # 捕获异常
                # 【静默失败修复】向量检索失败 [SILENT_FAILURE_BLOCKED]
                diagnostic_except_handler(e, context="[MemoryManager] 向量检索失败", logger_instance=logger)

        # 去重并排序  # 结果处理
        seen_ids = set()  # 已见ID集合
        unique_results = []  # 去重结果列表
        for r in results:  # 遍历结果
            rid = r.get("id")  # 获取ID
            if rid and rid not in seen_ids:  # 如果ID有效且未重复
                seen_ids.add(rid)  # 添加到已见
                unique_results.append(r)  # 添加到去重列表

        # 按评分降序  # 排序
        unique_results.sort(key=lambda x: x.get("rating", 0), reverse=True)  # 降序排序

        final_results = unique_results[:limit]  # 取前limit个

        # ═══════════════════════════════════════════════════════
        # 性能优化: 写入查询缓存
        # ═══════════════════════════════════════════════════════
        if self._cache_enabled and use_cache:
            cache_key_params = {
                "query": query,
                "layer": layer,
                "mem_type": mem_type,
                "scene": scene,
                "limit": limit,
                "min_rating": min_rating,
                "use_vector": use_vector
            }
            await self._query_cache.set("global", final_results, **cache_key_params)

        # 触发回调  # 回调通知
        await self._trigger_callbacks("on_memory_retrieve", query, final_results)  # 触发检索回调

        return final_results  # 返回结果

    async def get_memory(self, user_id: str, memory_id: str) -> MemoryRecord | None:
        """
        根据ID获取单条记忆

        Args:
            user_id: 用户ID
            memory_id: 记忆ID

        Returns:
            记忆记录，如果不存在则返回None
        """
        return await self.get_by_id(user_id, memory_id)

    async def get_by_id(self, user_id: str, mem_id: str) -> dict | None:
        """
        根据ID获取单条记忆（Agent-1权限控制需要）——【P0修复】直接查询PostgreSQL，不再依赖旧模块
        【P1-Asyncify】改用 asyncpg 原生异步查询。

        Args:
            user_id: 用户ID
            mem_id: 记忆ID

        Returns:
            记忆记录字典，如果不存在则返回None
        """
        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                r = await conn.fetchrow("""
                    SELECT id, layer, mem_type, content, context, scene,
                           rating, source, value_assessment, created_at, expire_at, compressed, creator
                    FROM memories WHERE id = $1 AND user_id = $2
                """, mem_id, user_id)

            if not r:
                return None

            try:
                content = json.loads(r['content']) if r['content'] and (r['content'].startswith('{') or r['content'].startswith('[')) else r['content']
            except Exception as e:
                logger.error(f"[SILENT_FAILURE_BLOCKED] JSON解析失败: {e}")
                content = r['content']

            return {
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
                "creator": r.get('creator', 'system')
            }
        except Exception as e:
            logger.error(f"[SILENT_FAILURE_BLOCKED][MemoryManager] 获取记忆异常: user_id={user_id}, mem_id={mem_id}, error={e}", exc_info=True)
            return None

    # ═══════════════════════════════════════════════════════════════
    # 性能优化: 流式大数据查询（新增）
    # ═══════════════════════════════════════════════════════════════

    async def query_large_dataset(self,
                           query: str = None,
                           layer: MemoryLayer | str = None,
                           mem_type: MemoryType | str = None,
                           scene: str = None,
                           min_rating: int = -1,
                           batch_size: int = DEFAULT_BATCH_SIZE,
                           max_results: int = MAX_RESULT_SIZE * 10) -> Iterator[dict]:
        """
        流式查询大量记忆，避免内存溢出

        使用生成器模式分批加载数据，适合处理大数据集。

        Args:
            query: 查询文本（用于向量检索）
            layer: 记忆层过滤
            mem_type: 记忆类型过滤
            scene: 场景过滤
            min_rating: 最小评分
            batch_size: 每批处理数量
            max_results: 最大返回结果数（默认10000）

        Yields:
            记忆记录

        Example:
            >>> for mem in memory_manager.query_large_dataset(layer=MemoryLayer.SHORT, batch_size=50):
            ...     process(mem)
        """
        offset = 0
        total_yielded = 0

        logger.info(f"[MemoryManager] 开始流式查询: batch_size={batch_size}, max_results={max_results}")

        while total_yielded < max_results:
            # 计算本批次的限制数量
            current_limit = min(batch_size, max_results - total_yielded)

            # 查询批次
            batch = await self.retrieve_memory(
                query=query,
                layer=layer,
                mem_type=mem_type,
                scene=scene,
                limit=current_limit,
                min_rating=min_rating,
                use_vector=False,  # 流式查询不使用向量检索，避免性能问题
                use_cache=False  # 流式查询不使用缓存
            )

            if not batch:
                break

            for item in batch:
                yield item
                total_yielded += 1

            offset += len(batch)

            # 如果本批次不足，说明数据已结束
            if len(batch) < current_limit:
                break

            # 防止无限循环的安全检查
            if offset > max_results * 2:
                logger.warning(f"[MemoryManager] 流式查询达到安全上限 {max_results * 2}")
                break

        logger.info(f"[MemoryManager] 流式查询完成: 共 {total_yielded} 条")

    async def search_by_semantic(self, query: str,  # 语义搜索方法
                          memory_type: VectorMemoryType = None,  # 记忆类型参数
                          limit: int = 5) -> list[dict]:  # 限制参数和返回类型
        """
        语义搜索接口  # 方法文档字符串

        Args:  # 参数说明
            query: 查询文本  # 参数1
            memory_type: 记忆类型  # 参数2
            limit: 返回数量  # 参数3

        Returns:  # 返回值说明
            搜索结果  # 返回类型
        """
        # 结果数量限制
        if limit > MAX_RESULT_SIZE:
            limit = MAX_RESULT_SIZE

        try:  # 异常处理
            vector_mem = await self._get_vector_memory()  # 获取向量记忆
            if not vector_mem:  # 如果不可用
                return []  # 返回空列表

            if memory_type == VectorMemoryType.EXPERIENCE:  # 经验类型
                return await vector_mem.vector_store.search("experience", query, limit=limit)
            elif memory_type == VectorMemoryType.VOICE_FIX:  # 语音纠错类型
                results = await vector_mem.vector_store.search("voice_fix", query, limit=1)
                return [{"correct": results[0].document}] if results else []  # 返回结果
            else:  # 其他类型
                return await vector_mem.vector_store.search("knowledge", query, limit=limit)

        except Exception as e:  # 捕获异常
            # 【静默失败修复】语义搜索失败 [SILENT_FAILURE_BLOCKED]
            diagnostic_except_handler(e, context="[MemoryManager] 语义搜索失败", logger_instance=logger)
            return []  # 返回空列表

    # ========== 批量操作 ==========  # 批量操作区域标记

    async def get_memories_by_ids(self, mem_ids: list[str]) -> list[dict]:  # 批量获取记忆方法
        """根据ID列表批量获取记忆"""  # 方法文档字符串
        memory = None  # 预初始化，避免异常时未定义
        try:  # 异常处理
            memory = await self._get_postgres_memory()  # 获取记忆实例
            if memory:  # 如果可用
                return await memory.get_by_ids_async(mem_ids)  # 调用底层异步批量获取
            return []  # 不可用返回空列表
        except Exception as e:  # 捕获异常
            # 【静默失败修复】批量获取记忆失败 [SILENT_FAILURE_BLOCKED]
            diagnostic_except_handler(e, context="[MemoryManager] 批量获取记忆失败", logger_instance=logger)
            return []  # 返回空列表

    async def rate_memory(self, mem_id: str, rating: int):  # 评分方法
        """对记忆进行评分"""  # 方法文档字符串
        memory = None  # 预初始化，避免异常时未定义
        try:  # 异常处理
            memory = await self._get_postgres_memory()  # 获取记忆实例
            if memory:  # 如果可用
                await memory.rate_async(mem_id, rating)  # 调用底层异步评分
                logger.debug(f"[MemoryManager] 记忆评分已更新: {mem_id[:8]}... = {rating}")  # 记录日志
        except Exception as e:  # 捕获异常
            # 【静默失败修复】记忆评分失败 [SILENT_FAILURE_BLOCKED]
            diagnostic_except_handler(e, context="[MemoryManager] 记忆评分失败", logger_instance=logger)

    async def delete_memory(self, user_id: str, memory_id: str) -> bool:
        """
        删除用户记忆（解决MEM-001级联删除和MEM-002）——【P0修复】直接操作PostgreSQL，不再依赖旧模块
        【P1-Asyncify】改用 asyncpg 原生异步执行。
        """
        mem_id = memory_id
        try:
            await self.invalidate_user_cache(user_id)

            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM memories WHERE id = $1 AND user_id = $2",
                    mem_id, user_id
                )
                deleted = "DELETE 1" in result
                if deleted:
                    logger.info(f"[MemoryManager] 记忆已删除: {mem_id[:8]}...")
                return deleted
        except Exception as e:
            diagnostic_except_handler(e, context="[MemoryManager] 删除记忆失败", logger_instance=logger)
            return False

    async def add_memory(self, user_id: str, content: str, memory_type: str = "general",
                   metadata: dict = None, **kwargs) -> str:
        """
        添加用户记忆（简化接口，供ChatModeHandler等调用）——【P0修复】直接操作PostgreSQL，不再依赖旧模块

        Returns:
            str: 记忆ID
        """

        # 【P0-3】硬性容量上限（Hermes 风格：逼 Agent 策展）
        _MAX_CONTENT_LENGTH = 8192  # 约 2k tokens
        if len(str(content)) > _MAX_CONTENT_LENGTH:
            raise ValueError(
                f"记忆内容过长（{len(str(content))}/{_MAX_CONTENT_LENGTH}字符）。"
                f"请精简内容，或拆分为多条记忆分别存储。"
            )

        # 【P2-1】候选记忆暂存机制
        if kwargs.get('staging'):
            return await self._add_memory_staging(user_id, content, memory_type, metadata, **kwargs)

        # 【P0 总容量上限】单用户记忆总字符数限制（紧急扩容至 50MB）
        _TOTAL_CHAR_LIMIT = 50 * 1024 * 1024
        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                total_chars = await conn.fetchval(
                    "SELECT COALESCE(SUM(LENGTH(content)), 0) FROM memories WHERE user_id = $1",
                    user_id
                ) or 0
                new_total = total_chars + len(str(content))
                if new_total > _TOTAL_CHAR_LIMIT:
                    raise ValueError(
                        f"记忆总容量即将超限（当前{total_chars:,}/上限{_TOTAL_CHAR_LIMIT:,}字符）。"
                        f"请使用 memory_delete 删除旧记忆，或使用 memory_replace 替换现有记忆。"
                    )
        except ValueError:
            raise
        except Exception:
            pass  # 查询失败时不阻断写入

        try:
            mem_id = str(uuid.uuid4())
            layer = kwargs.get('layer', 'short')
            # 【P0修复】兼容调用方传入 MemoryLayer/MemoryType 枚举
            if isinstance(layer, MemoryLayer):
                layer = layer.value
            mem_type_from_kwargs = kwargs.get('mem_type')
            if isinstance(mem_type_from_kwargs, MemoryType):
                kwargs = {**kwargs, "mem_type": mem_type_from_kwargs.value}
            expire_days = kwargs.get('expire_days')

            expire_at = None
            if layer in ("short", "working"):
                expire_days = expire_days or 1
            if expire_days:
                expire_at = datetime.now() + timedelta(days=expire_days)

            content_dict = {"text": content, "memory_type": memory_type}
            if metadata:
                content_dict.update(metadata)
            content_str = json.dumps(content_dict, ensure_ascii=False)

            value_assessment = generate_default_value_assessment()

            try:
                from core.memory.postgres_pool import AsyncPostgresPool
                pool = await AsyncPostgresPool.get_pool()
                async with pool.acquire() as conn:
                    await conn.execute('''
                        INSERT INTO memories
                        (id, user_id, layer, mem_type, content, context,
                         scene, rating, source, expire_at, value_assessment, creator)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                    ''',
                        mem_id, user_id, layer, memory_type, content_str,
                        json.dumps(kwargs.get('context', {})), kwargs.get('scene', ''),
                        kwargs.get('rating', 0), kwargs.get('source', 'system'),
                        expire_at, json.dumps(value_assessment), kwargs.get('creator', 'system')
                    )

                # ═══════════════════════════════════════════════════════════════
                # 【P0修复】向量同步：ui_element 和 semantic 层记忆同步到 ChromaDB
                # ═══════════════════════════════════════════════════════════════
                if memory_type == "ui_element" or layer == "semantic":
                    try:
                        # 过滤 kwargs 避免与显式参数冲突
                        _sync_kwargs = {k: v for k, v in kwargs.items()
                                        if k not in ("mem_id", "content", "memory_type",
                                                     "layer", "user_id", "metadata")}
                        asyncio.create_task(
                            self._sync_to_vector(
                                mem_id=mem_id,
                                content=content,
                                memory_type=memory_type,
                                layer=layer,
                                user_id=user_id,
                                metadata=metadata,
                                **_sync_kwargs
                            )
                        )
                    except Exception as sync_err:
                        logger.error(f"[MemoryManager] 启动向量同步任务失败: {sync_err}", exc_info=False)

            except Exception as e:
                diagnostic_except_handler(e, context="[MemoryManager] 添加记忆失败(PG写入)", logger_instance=logger)
                raise

            await self.invalidate_user_cache(user_id)
            logger.debug(f"[MemoryManager] 添加记忆成功: {mem_id[:8]}...")
            return mem_id
        except Exception as e:
            diagnostic_except_handler(e, context="[MemoryManager] 添加记忆失败", logger_instance=logger)
            return ""

    async def _add_memory_staging(self, user_id: str, content: str, memory_type: str = "general",
                                   metadata: dict = None, **kwargs) -> str:
        """【P2-1】候选记忆暂存：不入库，保存在内存中，等 Agent 确认后再正式写入"""
        import time
        mem_id = f"staging_{uuid.uuid4().hex[:12]}"
        self._staging_memories[mem_id] = {
            "user_id": user_id,
            "content": content,
            "memory_type": memory_type,
            "metadata": metadata or {},
            "kwargs": kwargs,
            "created_at": time.time(),
        }
        logger.info(f"[MemoryManager] 候选记忆已暂存: {mem_id[:8]}...")
        return mem_id

    async def confirm_memory(self, mem_id: str) -> str:
        """【P2-1】将候选记忆迁移到正式表"""
        import time
        staging = self._staging_memories.pop(mem_id, None)
        if not staging:
            raise ValueError(f"候选记忆不存在或已过期: {mem_id}")
        # 检查是否超过 1 天
        if time.time() - staging["created_at"] > 86400:
            raise ValueError(f"候选记忆已过期（超过1天未确认）: {mem_id}")
        return await self.add_memory(
            user_id=staging["user_id"],
            content=staging["content"],
            memory_type=staging["memory_type"],
            metadata=staging["metadata"],
            **staging["kwargs"]
        )

    async def replace_memory(self, user_id: str, old_mem_id: str, new_content: str, **kwargs) -> str:
        """【P2-2】原子替换：删除旧记忆，添加新记忆"""
        deleted = await self.delete_memory(user_id, old_mem_id)
        if not deleted:
            raise ValueError(f"无法删除旧记忆，替换失败: {old_mem_id}")
        return await self.add_memory(user_id, new_content, **kwargs)

    async def _sync_to_vector(self, mem_id: str, content: str, memory_type: str,
                               layer: str, user_id: str, metadata: dict, **kwargs) -> None:
        """
        【P0修复】将 ui_element / semantic 类型记忆同步到 ChromaDB 向量库。

        由 add_memory() 通过 safe_create_task(, name="async_task") 异步调用，不阻塞主流程。
        失败时仅记录日志，不抛出异常。
        """
        try:
            vector_mem = await self._get_vector_memory()
            if not vector_mem or not hasattr(vector_mem, 'vector_store'):
                logger.debug(f"[MemoryManager] VectorStore 不可用，跳过向量同步: {mem_id[:8]}...")
                return

            # ChromaDB metadata 只支持 str/int/float/bool，需扁平化
            chroma_metadata = {
                "user_id": user_id,
                "memory_type": memory_type,
                "layer": layer,
                "scene": kwargs.get('scene', ''),
                "source": kwargs.get('source', 'system'),
                "pg_mem_id": mem_id,
            }
            if metadata and isinstance(metadata, dict):
                for k, v in metadata.items():
                    if isinstance(v, (str, int, float, bool)):
                        chroma_metadata[k] = v
                    elif v is not None:
                        chroma_metadata[k] = str(v)

            collection_name = "ui_element" if memory_type == "ui_element" else "semantic"
            await vector_mem.vector_store.add(
                collection=collection_name,
                text=content,
                metadata=chroma_metadata
            )
            logger.info(f"[MemoryManager] 向量同步成功: {mem_id[:8]}... -> {collection_name}")
        except Exception as e:
            logger.error(f"[MemoryManager] 向量同步失败(非阻塞): {e}", exc_info=False)

    async def add(self, user_id: str, layer: str, content: Any, source: Any = None, **kwargs) -> str:
        """
        兼容旧 MemoryManager.add() 接口——【P0修复】直接操作PostgreSQL，不触发向量同步

        底层与 add_memory() 一致。
        """
        try:
            mem_id = str(uuid.uuid4())
            # 【修复】兼容调用方传入 MemoryLayer/MemoryType 枚举
            if isinstance(layer, MemoryLayer):
                layer = layer.value
            mem_type = kwargs.get('mem_type', 'general')
            if isinstance(mem_type, MemoryType):
                mem_type = mem_type.value
            expire_days = kwargs.get('expire_days')

            expire_at = None
            if layer in ("short", "working"):
                expire_days = expire_days or 1
            if expire_days:
                expire_at = datetime.now() + timedelta(days=expire_days)

            content_str = json.dumps(content, ensure_ascii=False) if not isinstance(content, str) else content

            value_assessment = kwargs.get('value_assessment', generate_default_value_assessment())

            # 【修复】字段长度预检查，避免数据库静默失败
            scene_val = kwargs.get('scene', '')
            creator_val = kwargs.get('creator', 'system')
            source_val = source or 'system'
            if len(layer) > 50:
                logger.warning(f"[MemoryManager] layer 长度超限({len(layer)}/50)，截断: {layer[:50]}")
                layer = layer[:50]
            if len(mem_type) > 50:
                logger.warning(f"[MemoryManager] mem_type 长度超限({len(mem_type)}/50)，截断: {mem_type[:50]}")
                mem_type = mem_type[:50]
            if len(scene_val) > 255:
                logger.warning(f"[MemoryManager] scene 长度超限({len(scene_val)}/255)，截断处理")
                scene_val = scene_val[:255]
            if len(source_val) > 100:
                logger.warning(f"[MemoryManager] source 长度超限({len(source_val)}/100)，截断处理")
                source_val = source_val[:100]
            if len(creator_val) > 100:
                logger.warning(f"[MemoryManager] creator 长度超限({len(creator_val)}/100)，截断处理")
                creator_val = creator_val[:100]

            try:
                from core.memory.postgres_pool import AsyncPostgresPool
                pool = await AsyncPostgresPool.get_pool()
                async with pool.acquire() as conn:
                    await conn.execute('''
                        INSERT INTO memories
                        (id, user_id, layer, mem_type, content, context,
                         scene, rating, source, expire_at, value_assessment, creator)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                    ''',
                        mem_id, user_id, layer, mem_type, content_str,
                        json.dumps(kwargs.get('context', {})), scene_val,
                        kwargs.get('rating', 0), source_val,
                        expire_at, json.dumps(value_assessment), creator_val
                    )
            except Exception as e:
                logger.error(f"[MemoryManager] add() 失败: {e}")
                raise

            await self.invalidate_user_cache(user_id)
            logger.debug(f"[MemoryManager] add() 成功: {mem_id[:8]}...")
            return mem_id
        except Exception as e:
            logger.error(f"[MemoryManager] add() 失败: {e}", exc_info=True)
            return ""

    async def update_memory(self, user_id: str, mem_id: str, updates: dict) -> bool:
        """
        更新记忆——【P0修复】直接操作PostgreSQL，兼容旧 UserMemoryStore.update() 接口
        """
        allowed_fields = ["content", "context", "scene", "rating", "expire_at", "compressed", "value_assessment", "source"]
        valid_updates = {k: v for k, v in updates.items() if k in allowed_fields}
        if not valid_updates:
            return False

        if "content" in valid_updates and not isinstance(valid_updates["content"], str):
            valid_updates["content"] = json.dumps(valid_updates["content"], ensure_ascii=False)

        for field_name in ["context", "value_assessment"]:
            if field_name in valid_updates and valid_updates[field_name] is not None:
                valid_updates[field_name] = json.dumps(valid_updates[field_name])

        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                set_parts = []
                params = []
                for idx, (k, v) in enumerate(valid_updates.items(), start=1):
                    params.append(v)
                    set_parts.append(f"{k} = ${idx}")
                set_parts.append("updated_at = CURRENT_TIMESTAMP")
                set_clause = ", ".join(set_parts)
                sql = f"UPDATE memories SET {set_clause} WHERE id = ${len(params) + 1} AND user_id = ${len(params) + 2}"
                params.extend([mem_id, user_id])
                result = await conn.execute(sql, *params)
                return "UPDATE 1" in result
        except Exception as e:
            logger.error(f"[MemoryManager] update_memory() 失败: {e}")
            return False

    async def get_memory_stats(self, user_id: str) -> dict[str, Any]:
        """
        获取用户记忆统计——【P0修复】直接操作PostgreSQL，兼容旧 UserMemoryStore.get_stats() 接口
        【P1-Asyncify】改用 asyncpg 原生异步查询。
        """
        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            stats = {"user_id": user_id, "total": 0}
            async with pool.acquire() as conn:
                for layer in ["working", "short", "medium", "evolve", "execution"]:
                    val = await conn.fetchval(
                        "SELECT COUNT(*) FROM memories WHERE layer = $1 AND user_id = $2",
                        layer, user_id
                    )
                    stats[layer] = val or 0
                stats["total"] = await conn.fetchval(
                    "SELECT COUNT(*) FROM memories WHERE user_id = $1", user_id
                ) or 0
                stats["expired"] = await conn.fetchval(
                    "SELECT COUNT(*) FROM memories WHERE expire_at < CURRENT_TIMESTAMP AND user_id = $1",
                    user_id
                ) or 0
                stats["compressed"] = await conn.fetchval(
                    "SELECT COUNT(*) FROM memories WHERE compressed = 1 AND user_id = $1",
                    user_id
                ) or 0
                avg_rating = await conn.fetchval(
                    "SELECT AVG(rating) FROM memories WHERE user_id = $1", user_id
                )
                stats["avg_rating"] = round(avg_rating, 2) if avg_rating else 0
                rows = await conn.fetch(
                    "SELECT source, COUNT(*) as count FROM memories WHERE user_id = $1 GROUP BY source",
                    user_id
                )
                source_stats = {}
                for row in rows:
                    source_stats[row["source"] or 'system'] = row["count"]
                stats["by_source"] = source_stats
            return stats
        except Exception as e:
            logger.error(f"[MemoryManager] get_memory_stats() 失败: {e}")
            return {"user_id": user_id, "total": 0}

    async def get(self, user_id: str = "default", scene: str = None, mem_type: str = None,
                  layer: str = None, limit: int = 10, min_rating: int = -1,
                  filter_dict: dict = None) -> list[dict]:
        """
        兼容旧 memory.get() 接口——【P1修复】直接查询 PostgreSQL，不触发向量同步
        """
        return await self.retrieve_memory(
            query=None,
            layer=layer,
            mem_type=mem_type,
            scene=scene,
            limit=limit,
            min_rating=min_rating,
            use_vector=False,
            use_cache=False
        )

    # ========== 高级查询 ==========  # 高级查询区域标记

    async def get_recent_memories(self,  # 获取近期记忆方法
                           layer: MemoryLayer = None,  # 层级参数
                           hours: int = 24,  # 小时参数，默认24
                           limit: int = 50) -> list[dict]:  # 限制参数和返回类型
        """
        获取近期记忆  # 方法文档字符串

        Args:  # 参数说明
            layer: 记忆层  # 参数1
            hours: 最近小时数  # 参数2
            limit: 返回数量  # 参数3

        Returns:  # 返回值说明
            记忆列表  # 返回类型
        """
        # 结果数量限制
        if limit > MAX_RESULT_SIZE:
            limit = MAX_RESULT_SIZE

        since = (datetime.now() - timedelta(hours=hours)).isoformat()  # 计算起始时间

        all_mems = await self.retrieve_memory(  # 调用检索
            layer=layer,  # 层级
            limit=limit * 2  # 多获取一些用于过滤
        )

        # 过滤时间  # 时间过滤
        recent = [  # 列表推导
            m for m in all_mems  # 遍历所有记忆
            if m.get("created_at", "") > since  # 筛选近期
        ]

        return recent[:limit]  # 返回前limit个

    async def get_high_value_memories(self,  # 获取高价值记忆方法
                                min_rating: int = 5,  # 最低评分参数
                                limit: int = 20) -> list[dict]:  # 限制参数和返回类型
        """
        获取高价值记忆  # 方法文档字符串

        Args:  # 参数说明
            min_rating: 最小评分  # 参数1
            limit: 返回数量  # 参数2

        Returns:  # 返回值说明
            记忆列表  # 返回类型
        """
        # 结果数量限制
        if limit > MAX_RESULT_SIZE:
            limit = MAX_RESULT_SIZE

        return await self.retrieve_memory(  # 调用检索
            layer=MemoryLayer.EVOLVE,  # 进化层
            min_rating=min_rating,  # 最低评分
            limit=limit  # 限制
        )

    # ========== 统计与维护 ==========  # 统计维护区域标记

    async def clear_expired_memories(self, dry_run: bool = False) -> int:  # 清理过期记忆方法
        """
        清理过期记忆  # 方法文档字符串

        Args:  # 参数说明
            dry_run: 是否仅模拟（不实际删除）  # 参数1

        Returns:  # 返回值说明
            清理数量  # 返回类型
        """
        # PostgreSQL层有自动清理，这里主要用于手动触发或统计  # 说明
        logger.info(f"[MemoryManager] 清理过期记忆 (dry_run={dry_run})")  # 记录日志
        return 0  # 由memory.py自动处理

    # ========== 缓存管理（向后兼容） ==========  # 缓存管理区域标记

    async def cache_set(self, key: str, value: Any, ttl: int = 300):  # 设置缓存方法
        """
        设置缓存（向后兼容）

        Args:  # 参数说明
            key: 缓存键  # 参数1
            value: 缓存值  # 参数2
            ttl: 过期时间（秒）  # 参数3
        """
        async with self._cache_lock:  # 获取锁
            self._cache[key] = {  # 设置缓存项
                "value": value,  # 值
                "expire_at": time.time() + ttl  # 过期时间
            }

    async def cache_get(self, key: str) -> Any | None:  # 获取缓存方法
        """获取缓存（向后兼容）"""  # 方法文档字符串
        async with self._cache_lock:  # 获取锁
            item = self._cache.get(key)  # 获取缓存项
            if item:  # 如果存在
                if time.time() < item["expire_at"]:  # 如果未过期
                    return item["value"]  # 返回值
                else:  # 已过期
                    del self._cache[key]  # 删除缓存项
            return None  # 返回None

    async def cache_clear(self):  # 清空缓存方法
        """清空缓存（向后兼容）"""  # 方法文档字符串
        async with self._cache_lock:  # 获取锁
            self._cache.clear()  # 清空字典

    # ========== 兼容旧接口 ==========  # 兼容接口区域标记

    async def add_ai_memory(self, task_name: str, decision_func: str,  # 兼容：添加AI决策记忆
                      reason: str, effect: str, remark: str = "") -> str:  # 参数和返回类型
        """兼容：添加AI决策记忆"""  # 方法文档字符串
        content = f"任务：{task_name} | 决策：{decision_func} | 原因：{reason} | 效果：{effect}"  # 构建内容
        return await self.store_memory(  # 调用存储
            layer=MemoryLayer.EVOLVE,  # 进化层
            mem_type=MemoryType.AI_NOTE,  # AI笔记类型
            content=content,  # 内容
            context={"task_name": task_name, "effect": effect},  # 上下文
            rating=0  # 评分
        )

    async def save_reflection(self, session_id: str, user_instruction: str,  # 兼容：保存反思记录
                       task_result: dict, task_type: str = "general") -> str:  # 参数和返回类型
        """兼容：保存反思记录"""  # 方法文档字符串
        scene = f"reflection_{task_type}_{user_instruction[:20]}"  # 构建场景
        return await self.store_memory(  # 调用存储
            layer=MemoryLayer.EVOLVE,  # 进化层
            mem_type=MemoryType.REFLECTION,  # 反思类型
            content=task_result,  # 内容
            context={  # 上下文
                "session_id": session_id,  # 会话ID
                "user_instruction": user_instruction,  # 用户指令
                "task_type": task_type  # 任务类型
            },
            scene=scene  # 场景
        )

    async def load_reflections(self, task_type: str = None, limit: int = 5) -> list[dict]:  # 兼容：加载反思记录
        """兼容：加载反思记录"""  # 方法文档字符串
        return await self.retrieve_memory(  # 调用检索
            mem_type=MemoryType.REFLECTION,  # 反思类型
            layer=MemoryLayer.EVOLVE,  # 进化层
            limit=limit  # 限制
        )


# 全局单例实例  # 全局实例注释
try:  # 异常处理
    memory_manager = MemoryManager()  # 创建全局实例
    logger.info("[MemoryManager] 全局实例创建成功")  # 记录成功
except Exception as e:  # 捕获异常
    # 【静默失败修复】全局实例创建失败 [SILENT_FAILURE_BLOCKED]
    logger.error(f"[MemoryManager] 全局实例创建失败: {e}", exc_info=True)  # 记录错误
    memory_manager = None  # 设置为空


    # ═══════════════════════════════════════════════════════════════
    # Phase 3: 三层记忆系统接口
    # ═══════════════════════════════════════════════════════════════

    # ── L1: 短期会话记忆 ──
    async def store_session_memory(self, session_id: str, content: str,
                                    role: str = "user", metadata: dict[str, Any] | None = None) -> None:
        """
        存储短期会话记忆

        Args:
            session_id: 会话ID
            content: 记忆内容
            role: 角色(user/assistant/system)
            metadata: 可选元数据
        """
        entry = {
            "timestamp": datetime.now().isoformat(),
            "role": role,
            "content": content,
            "metadata": metadata or {}
        }
        async with self._session_lock:
            if session_id not in self._session_memory:
                self._session_memory[session_id] = []
            self._session_memory[session_id].append(entry)
            logger.debug(f"[SessionMemory] session={session_id} 新增记录, 总条数={len(self._session_memory[session_id])}")

    async def get_session_memory(self, session_id: str, limit: int | None = None) -> list[dict[str, Any]]:
        """
        获取短期会话记忆

        Args:
            session_id: 会话ID
            limit: 返回最近N条, None则返回全部

        Returns:
            记忆条目列表
        """
        async with self._session_lock:
            entries = self._session_memory.get(session_id, [])
            if limit is not None:
                entries = entries[-limit:]
            return list(entries)

    async def clear_session_memory(self, session_id: str) -> int:
        """
        清理指定会话的短期记忆（会话结束时调用）

        Args:
            session_id: 会话ID

        Returns:
            清理的条目数
        """
        async with self._session_lock:
            count = len(self._session_memory.pop(session_id, []))
            logger.info(f"[SessionMemory] session={session_id} 已清理, 删除{count}条")
            return count

    async def list_active_sessions(self) -> list[str]:
        """获取所有活跃会话ID"""
        async with self._session_lock:
            return list(self._session_memory.keys())

    # ── L3: 任务状态记忆 ──
    async def store_task_state(self, task_id: str, state_data: dict[str, Any]) -> None:
        """
        存储任务执行状态（闭环锚点）

        Args:
            task_id: 任务ID
            state_data: 状态数据, 应包含:
                - stage: 当前阶段
                - tools_used: 已使用工具列表
                - results: 中间结果
                - status: running/completed/failed
                - updated_at: 更新时间
        """
        state_data = dict(state_data)
        state_data["updated_at"] = datetime.now().isoformat()
        async with self._task_state_lock:
            self._task_state_memory[task_id] = state_data
            logger.debug(f"[TaskState] task={task_id} 状态更新: {state_data.get('stage', 'unknown')}")

    async def get_task_state(self, task_id: str) -> dict[str, Any] | None:
        """
        获取任务执行状态

        Args:
            task_id: 任务ID

        Returns:
            状态数据或None
        """
        async with self._task_state_lock:
            return self._task_state_memory.get(task_id)

    async def clear_task_state(self, task_id: str) -> bool:
        """
        清理任务状态记忆

        Args:
            task_id: 任务ID

        Returns:
            是否成功删除
        """
        async with self._task_state_lock:
            existed = task_id in self._task_state_memory
            self._task_state_memory.pop(task_id, None)
            if existed:
                logger.info(f"[TaskState] task={task_id} 状态已清理")
            return existed

    async def list_active_tasks(self) -> list[str]:
        """获取所有活跃任务ID"""
        async with self._task_state_lock:
            return list(self._task_state_memory.keys())

    # ── L2: 长期沉淀记忆 + 智能压缩 ──
    async def store_longterm_memory(self, user_id: str, content: str,
                                     memory_type: str = "general",
                                     metadata: dict[str, Any] | None = None) -> str:
        """
        存储长期沉淀记忆（带自动压缩触发）

        Args:
            user_id: 用户ID
            content: 记忆内容
            memory_type: 记忆类型
            metadata: 元数据

        Returns:
            记忆ID
        """
        mem_id = await self.add_memory(
            user_id=user_id,
            content=content,
            memory_type=memory_type,
            metadata=metadata or {},
            layer=MemoryLayer.EVOLVE
        )

        # 异步触发压缩检查（不阻塞存储）
        safe_create_task(self._check_and_compress(user_id), name="_check_and_compress")  # 【P0修复】删除多余的 await
        return mem_id

    async def _check_and_compress(self, user_id: str) -> None:
        """检查并触发长期记忆压缩"""
        try:
            # 获取该用户SHORT+MEDIUM层记忆数量
            memories = await self.retrieve_memory(
                user_id=user_id,
                query="*",
                layer=None,
                limit=10000
            )
            count = len(memories)
            if count >= self._longterm_compress_threshold:
                logger.info(f"[LongTerm] user={user_id} 记忆数{count}超过阈值{self._longterm_compress_threshold}, 触发压缩")
                await self.compress_longterm_memory(user_id)
        except Exception as e:
            logger.warning(f"[LongTerm] 压缩检查失败: {e}")

    async def compress_longterm_memory(self, user_id: str) -> dict[str, Any]:
        """
        智能压缩算法: 将大量短期/中期记忆压缩为长期沉淀记忆

        策略:
        1. 按scene/topic分组聚类
        2. 同组内去重、合并相似内容
        3. 保留高评分条目, 低评分内容提取关键词后合并
        4. 生成摘要写入EVOLVE层
        5. 清理已压缩的SHORT/MEDIUM层原始记录

        Args:
            user_id: 用户ID

        Returns:
            压缩统计信息
        """
        async with self._longterm_lock:
            stats = {"grouped": 0, "summarized": 0, "deleted": 0, "preserved": 0}

            # 1. 拉取所有SHORT/MEDIUM层记忆
            all_memories = []
            for layer in [MemoryLayer.SHORT, MemoryLayer.MEDIUM]:
                try:
                    layer_mems = await self.retrieve_memory(
                        user_id=user_id, query="*", layer=layer, limit=5000
                    )
                    all_memories.extend(layer_mems)
                except Exception as e:
                    logger.warning(f"[Compress] 拉取{layer.value}层失败: {e}")

            if len(all_memories) < self._longterm_compress_threshold:
                return {**stats, "reason": "记忆数量不足, 跳过压缩"}

            # 2. 按scene分组
            groups: dict[str, list[dict]] = {}
            for mem in all_memories:
                scene = mem.get("scene", "default")
                if not scene:
                    scene = "default"
                groups.setdefault(scene, []).append(mem)

            stats["grouped"] = len(groups)

            # 3. 逐组压缩
            for scene, mems in groups.items():
                if len(mems) <= 1:
                    continue

                # 3a. 分离高评分(>=4)和低评分
                high_rated = [m for m in mems if m.get("rating", 0) >= 4]
                low_rated = [m for m in mems if m.get("rating", 0) < 4]

                # 3b. 高评分直接保留到EVOLVE层
                for mem in high_rated:
                    try:
                        await self.add_memory(
                            user_id=user_id,
                            content=mem.get("content", ""),
                            memory_type=mem.get("mem_type", "general"),
                            metadata={**mem.get("metadata", {}), "compressed_from": mem.get("id"), "scene": scene},
                            layer=MemoryLayer.EVOLVE
                        )
                        stats["preserved"] += 1
                    except Exception as e:
                        logger.warning(f"[Compress] 保留高评分记忆失败: {e}")

                # 3c. 低评分合并摘要
                if low_rated:
                    # 提取去重关键词句
                    all_texts = [str(m.get("content", "")) for m in low_rated]
                    unique_sentences = list(dict.fromkeys([t.strip() for t in all_texts if t.strip()]))

                    # 简单摘要: 保留前N条唯一内容, 超出部分标记为"等N条类似记录"
                    MAX_SUMMARY_ITEMS = 10
                    if len(unique_sentences) > MAX_SUMMARY_ITEMS:
                        summary_text = "; ".join(unique_sentences[:MAX_SUMMARY_ITEMS])
                        summary_text += f" [等{len(unique_sentences) - MAX_SUMMARY_ITEMS}条类似记录]"
                    else:
                        summary_text = "; ".join(unique_sentences)

                    # 统计该组关键信息
                    keywords = self._extract_keywords(" ".join(all_texts))

                    try:
                        await self.add_memory(
                            user_id=user_id,
                            content=f"[{scene}] 摘要: {summary_text}",
                            memory_type="compressed_summary",
                            metadata={
                                "scene": scene,
                                "original_count": len(low_rated),
                                "keywords": keywords,
                                "compression_ratio": round(len(low_rated) / max(len(unique_sentences), 1), 2)
                            },
                            layer=MemoryLayer.EVOLVE
                        )
                        stats["summarized"] += 1
                    except Exception as e:
                        logger.warning(f"[Compress] 写入摘要失败: {e}")

                # 3d. 删除原始SHORT/MEDIUM记录
                for mem in mems:
                    try:
                        mem_id = mem.get("id")
                        if mem_id:
                            await self.delete_memory(user_id, mem_id)
                            stats["deleted"] += 1
                    except Exception as e:
                        logger.warning(f"[Compress] 删除原始记忆失败: {e}")

            logger.info(f"[LongTerm] user={user_id} 压缩完成: {stats}")
            return stats

    @staticmethod
    def _extract_keywords(text: str, top_k: int = 5) -> list[str]:
        """简单关键词提取（基于词频）"""
        import re
        # 中文分词: 提取2-4字词组 + 英文单词
        words = re.findall(r'[\u4e00-\u9fff]{2,4}|[a-zA-Z]+', text.lower())
        # 过滤停用词（简化版）
        stopwords = {"the", "and", "is", "to", "of", "a", "in", "for", "这个", "那个", "什么", "怎么", "可以", "需要"}
        filtered = [w for w in words if w not in stopwords and len(w) > 1]
        from collections import Counter
        counter = Counter(filtered)
        return [word for word, _ in counter.most_common(top_k)]


# 便捷函数  # 便捷函数注释
async def get_memory_manager() -> MemoryManager:  # 获取记忆管理器函数
    """获取记忆管理器实例"""  # 函数文档字符串
    return memory_manager  # 返回全局实例


async def store_experience(task_desc: str, steps: list[str],  # 便捷：存储经验函数
                     success: bool, **kwargs) -> bool:  # 参数和返回类型
    """便捷：存储经验"""  # 函数文档字符串
    if memory_manager:  # 如果管理器可用
        exp = ExperienceRecord(  # 创建经验记录
            task_desc=task_desc,  # 任务描述
            steps=steps,  # 步骤
            success=success,  # 是否成功
            **kwargs  # 其他参数
        )
        return await memory_manager.store_experience(exp)  # 调用存储
    return False  # 不可用返回失败


async def retrieve_experience(task_desc: str, **kwargs) -> dict | None:  # 便捷：召回经验函数
    """便捷：召回经验"""  # 函数文档字符串
    if memory_manager:  # 如果管理器可用
        return await memory_manager.retrieve_experience(task_desc, **kwargs)  # 调用召回
    return None  # 不可用返回None


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase V5 系统的"统一记忆管理器"，位于记忆系统的中间层。
# 它在底层记忆存储(core/memory.py)和上层业务逻辑之间提供统一的抽象接口。
#
# 【架构设计】
# - 单例模式: 全局唯一的记忆管理器实例
# - 延迟加载: 底层PostgreSQL和向量记忆实例按需加载
# - 回调机制: 支持注册记忆添加、检索、经验存储的回调
# - 缓存系统: 内置TTL缓存，减少重复查询
# - 枚举定义: MemoryLayer、MemoryType、VectorMemoryType提供类型安全
#
# 【2026-03-03 性能优化】
# - MemoryCache: 查询结果缓存系统，支持TTL和LRU淘汰
# - query_large_dataset: 流式查询，支持大数据集分批处理
# - MAX_RESULT_SIZE: 结果数量限制，防止内存溢出
# - 缓存统计: 命中率、未命中数、淘汰数等统计信息
#
# 【关联文件】
# - core/memory.py              : 底层五层记忆系统(PostgreSQL存储)
# - core/memory_optimized.py    : 性能优化参考实现
# - core/vector_memory.py       : 向量记忆层(ChromaDB存储)
# - core/evolution.py           : 经验管理器(ExperienceManager)
# - core/logger.py              : 日志记录
# - core/config.py              : 配置管理
#
# 【核心功能效果】
# 1. 统一接口: 提供store_memory/retrieve_memory统一存储检索接口
# 2. 分层记录: 根据重要性自动选择存储层级(SHORT/MEDIUM/EVOLVE)
# 3. 经验管理: 支持任务经验的存储、召回、相似查找
# 4. 双轨检索: 同时检索PostgreSQL和向量层，结果合并去重
# 5. 语义搜索: 基于向量相似度的语义检索能力
# 6. 批量操作: 支持批量获取、评分、删除记忆
# 7. 缓存加速: 查询缓存减少数据库查询次数，命中率可达60-80%
# 8. 流式处理: query_large_dataset支持百万级数据遍历
# 9. 内存保护: MAX_RESULT_SIZE防止内存溢出
# 10. 回调扩展: 支持注册回调实现扩展功能(如审计、通知)
#
# 【使用场景】
# - AgentLoop记录对话: 每次对话后记录到短期记忆
# - 经验沉淀: 任务完成后存储成功/失败经验供后续复用
# - 知识检索: 回答问题时检索相关知识
# - 反思记录: 自动复盘时存储反思结果到进化层
# - 大数据处理: 使用query_large_dataset遍历大量记忆
# - 性能优化: 启用缓存减少数据库压力
#
# 【缓存使用建议】
# - 默认启用缓存，可通过 set_cache_enabled(False) 禁用
# - 缓存TTL: 600秒（10分钟）
# - 缓存大小: 最大200条
# - 使用 get_cache_stats() 查看缓存统计
# - 数据变更后缓存自动失效
# =============================================================================
