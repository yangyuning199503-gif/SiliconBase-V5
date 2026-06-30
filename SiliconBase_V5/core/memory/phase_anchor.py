#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""  # 多行文档字符串开始
阶段锚点管理器 - 跨模式记忆基础设施  # 模块功能概述：任务执行阶段状态保存与恢复
保存和恢复任务执行的各个阶段状态  # 主要功能说明

【修复说明】2026-03-22: 添加PostgreSQL持久化支持
- 阶段锚点同时保存到内存和PostgreSQL
- 支持断点续传时恢复阶段锚点
"""  # 文档字符串结束

import json  # 导入JSON模块，用于锚点数据的序列化
import threading  # 导入线程模块，用于线程安全
import time  # 导入时间模块，用于时间戳记录
import uuid  # 导入UUID模块，用于生成唯一标识符
from dataclasses import asdict, dataclass  # 从dataclasses导入数据类装饰器和序列化函数
from pathlib import Path  # 从pathlib导入Path类，用于跨平台路径操作
from typing import Any  # 从typing模块导入类型注解

from core.exceptions import LoadError, PersistenceError  # 【高危Bug修复】导入持久化和加载错误异常
from core.logger import logger  # 从日志模块导入日志记录器

# 【新增】PostgreSQL支持（捕获所有异常包括RuntimeError）
try:
    from core.db.connection_pool import POSTGRES_AVAILABLE, PostgresConnectionPool
except Exception:
    POSTGRES_AVAILABLE = False
    PostgresConnectionPool = None


@dataclass  # 数据类装饰器
class PhaseAnchor:  # 定义阶段锚点数据类，表示任务执行的某个阶段快照
    """阶段锚点数据结构"""  # 类文档字符串
    id: str  # 锚点唯一标识符
    phase: str           # 阶段名称: init（初始化）/perception（感知）/understanding（理解）/execution（执行）/completion（完成）
    timestamp: float     # 锚点创建时间戳（Unix时间）
    data: dict[str, Any] # 阶段数据，存储该阶段的状态信息
    user_id: str = "default"  # 用户ID，默认为"default"
    session_id: str = ""  # 会话ID，默认为空字符串
    task_id: str = ""    # 【新增】任务ID，用于断点续传关联

    def to_dict(self) -> dict:  # 将锚点转换为字典的方法
        """序列化为字典"""  # 方法文档字符串
        return asdict(self)  # 使用asdict函数将数据类转换为字典

    @classmethod  # 类方法装饰器
    def from_dict(cls, data: dict) -> "PhaseAnchor":  # 从字典反序列化为PhaseAnchor对象
        """从字典反序列化"""  # 方法文档字符串
        return cls(**data)  # 使用字典解包创建PhaseAnchor实例


class PhaseAnchorManager:  # 定义阶段锚点管理器类，管理所有锚点的生命周期
    """
    阶段锚点管理器

    职责：  # 类的职责说明
    1. 保存任务执行的各个阶段快照  # 职责1：阶段快照保存
    2. 支持跨会话恢复上下文  # 职责2：上下文恢复
    3. 为弱连接、长任务恢复、模式切换提供记忆基础  # 职责3：支持高级功能
    4. 【新增】PostgreSQL持久化存储  # 职责4：持久化存储
    """

    _instance = None  # 单例模式：类变量，存储唯一实例引用
    _lock = threading.Lock()  # 单例模式：类变量，线程锁

    def __new__(cls):  # 重写__new__方法实现单例模式
        if cls._instance is None:  # 如果实例尚未创建
            with cls._lock:  # 获取线程锁
                if cls._instance is None:  # 双重检查
                    cls._instance = super().__new__(cls)  # 创建实例
        return cls._instance  # 返回单例实例

    def __init__(self):  # 初始化方法
        if '_initialized' in self.__dict__:  # 检查是否已初始化
            return  # 已初始化则直接返回
        self._initialized = True  # 标记为已初始化

        # 内存缓存（最近100个锚点）
        self._anchors: dict[str, PhaseAnchor] = {}  # 锚点内存缓存字典
        self._user_anchors: dict[str, list[str]] = {}  # 用户到锚点ID列表的索引映射
        self._task_anchors: dict[str, list[str]] = {}  # 【新增】任务到锚点ID列表的索引映射
        self._max_memory_anchors = 100  # 内存中最大缓存锚点数

        # 持久化目录
        self._persist_dir = Path("data/phase_anchors")  # 锚点持久化存储目录
        self._persist_dir.mkdir(parents=True, exist_ok=True)  # 创建目录（如果不存在）

        # 锁
        self._anchor_lock = threading.RLock()  # 创建可重入锁用于线程安全

        # 【新增】确保PostgreSQL表存在
        self._ensure_postgres_table()

        logger.info("[PhaseAnchorManager] 阶段锚点管理器初始化完成")  # 记录初始化完成日志

    # 【新增】确保PostgreSQL表结构
    def _ensure_postgres_table(self):
        """确保PostgreSQL表存在（同步版本）"""
        if not POSTGRES_AVAILABLE or PostgresConnectionPool is None:
            logger.warning("[PhaseAnchorManager] PostgreSQL不可用，阶段锚点将仅保存到本地文件")
            return

        try:
            conn = PostgresConnectionPool.get_connection()
            try:
                with conn.cursor() as cursor:
                    # 创建阶段锚点表
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS phase_anchors (
                            id VARCHAR(255) PRIMARY KEY,
                            task_id VARCHAR(255) NOT NULL,
                            phase VARCHAR(255) NOT NULL,
                            user_id VARCHAR(255) DEFAULT 'default',
                            session_id VARCHAR(255) DEFAULT '',
                            data JSONB,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)

                    # 创建索引
                    cursor.execute("""
                        CREATE INDEX IF NOT EXISTS idx_phase_anchors_task_id
                        ON phase_anchors(task_id)
                    """)
                    cursor.execute("""
                        CREATE INDEX IF NOT EXISTS idx_phase_anchors_user_id
                        ON phase_anchors(user_id)
                    """)
                    cursor.execute("""
                        CREATE INDEX IF NOT EXISTS idx_phase_anchors_created_at
                        ON phase_anchors(created_at DESC)
                    """)

                    conn.commit()
                    logger.info("[PhaseAnchorManager] PostgreSQL表已确认存在")
            finally:
                PostgresConnectionPool.return_connection(conn)
        except Exception as e:
            logger.error(f"[PhaseAnchorManager] 确保PostgreSQL表存在失败: {e}", exc_info=True)

    async def _ensure_postgres_table_async(self):
        """确保PostgreSQL表存在（异步版本，原生asyncpg）"""
        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS phase_anchors (
                        id VARCHAR(255) PRIMARY KEY,
                        task_id VARCHAR(255) NOT NULL,
                        phase VARCHAR(255) NOT NULL,
                        user_id VARCHAR(255) DEFAULT 'default',
                        session_id VARCHAR(255) DEFAULT '',
                        data JSONB,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_phase_anchors_task_id
                    ON phase_anchors(task_id)
                """)
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_phase_anchors_user_id
                    ON phase_anchors(user_id)
                """)
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_phase_anchors_created_at
                    ON phase_anchors(created_at DESC)
                """)
            logger.info("[PhaseAnchorManager] PostgreSQL异步表已确认存在")
        except Exception as e:
            logger.error(f"[PhaseAnchorManager] 确保PostgreSQL异步表存在失败: {e}", exc_info=True)

    async def save(self, phase: str, data: dict[str, Any],
             user_id: str = "default",
             session_id: str = "",
             task_id: str = "",
             anchor_id: str | None = None) -> str:  # 保存阶段锚点的方法
        """
        保存阶段锚点（同时保存到内存、本地文件和PostgreSQL）

        Args:  # 参数说明
            phase: 阶段名称  # 当前阶段标识
            data: 阶段数据  # 需要保存的状态数据
            user_id: 用户ID  # 关联用户
            session_id: 会话ID  # 关联会话
            task_id: 任务ID  # 【新增】关联任务
            anchor_id: 指定锚点ID（可选）  # 可选的自定义锚点ID

        Returns:  # 返回值说明
            anchor_id: 锚点ID  # 返回创建的锚点ID
        """
        with self._anchor_lock:  # 获取锁确保线程安全
            # 生成锚点ID
            if anchor_id is None:  # 如果没有指定锚点ID
                anchor_id = f"anchor_{uuid.uuid4().hex[:12]}"  # 生成UUID作为锚点ID（取前12位）

            # 创建锚点
            anchor = PhaseAnchor(  # 创建PhaseAnchor对象
                id=anchor_id,  # 锚点ID
                phase=phase,  # 阶段名称
                timestamp=time.time(),  # 当前时间戳
                data=data,  # 阶段数据
                user_id=user_id,  # 用户ID
                session_id=session_id,  # 会话ID
                task_id=task_id  # 【新增】任务ID
            )

            # 保存到内存
            self._anchors[anchor_id] = anchor  # 将锚点存入内存缓存

            # 添加到用户索引
            if user_id not in self._user_anchors:  # 如果用户不在索引中
                self._user_anchors[user_id] = []  # 创建该用户的锚点列表
            if anchor_id not in self._user_anchors[user_id]:  # 如果锚点ID不在用户列表中
                self._user_anchors[user_id].append(anchor_id)  # 添加到用户锚点列表

            # 【新增】添加到任务索引
            if task_id:
                if task_id not in self._task_anchors:
                    self._task_anchors[task_id] = []
                if anchor_id not in self._task_anchors[task_id]:
                    self._task_anchors[task_id].append(anchor_id)

            # 限制内存中锚点数量
            self._cleanup_old_anchors(user_id)  # 清理旧锚点

            # 异步持久化到本地文件
            self._persist_async(anchor)  # 异步保存到磁盘

            # 【新增】保存到PostgreSQL（原生asyncpg，避免to_thread）
            await self._save_to_postgres_async(anchor)

            logger.debug(f"[PhaseAnchor] 保存锚点: {anchor_id}, 阶段: {phase}, 任务: {task_id}")  # 记录调试日志
            return anchor_id  # 返回锚点ID

    # 【新增】保存到PostgreSQL - 【高危Bug修复】添加重试机制和零静默失败
    def _save_to_postgres(self, anchor: PhaseAnchor) -> bool:
        """
        保存锚点到PostgreSQL（同步版本）

        Args:
            anchor: 阶段锚点对象

        Returns:
            是否保存成功

        Raises:
            PersistenceError: 当所有重试都失败时抛出
        """
        if not POSTGRES_AVAILABLE or PostgresConnectionPool is None:
            logger.warning("[PhaseAnchorManager] PostgreSQL不可用，跳过保存")
            return False

        max_retries = 3
        last_exception = None

        for attempt in range(max_retries):
            conn = None
            try:
                conn = PostgresConnectionPool.get_connection()
                with conn.cursor() as cursor:
                    cursor.execute("""
                        INSERT INTO phase_anchors
                        (id, task_id, phase, user_id, session_id, data, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, to_timestamp(%s), to_timestamp(%s))
                        ON CONFLICT (id) DO UPDATE SET
                            data = EXCLUDED.data,
                            updated_at = CURRENT_TIMESTAMP
                    """, (
                        anchor.id,
                        anchor.task_id,
                        anchor.phase,
                        anchor.user_id,
                        anchor.session_id,
                        json.dumps(anchor.data),
                        anchor.timestamp,
                        anchor.timestamp
                    ))
                    conn.commit()
                    logger.info(f"[PhaseAnchorManager] PostgreSQL保存成功: {anchor.id}")
                    return True
            except Exception as e:
                last_exception = e
                logger.error(f"[PhaseAnchorManager] PostgreSQL保存失败(尝试{attempt+1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(0.1 * (attempt + 1))  # 指数退避
            finally:
                if conn is not None:
                    try:
                        PostgresConnectionPool.return_connection(conn)
                    except Exception as pool_e:
                        # 【静默失败修复】连接池归还失败必须是ERROR级别
                        logger.error(f"[PhaseAnchorManager] 归还连接失败: {pool_e}", exc_info=True)

        # 所有重试失败，记录ERROR并抛出异常（零静默失败原则）
        logger.error(f"[PhaseAnchorManager] PostgreSQL保存最终失败: {last_exception}", exc_info=True)
        raise PersistenceError(f"无法保存阶段锚点到PostgreSQL: {last_exception}") from last_exception

    async def _save_to_postgres_async(self, anchor: PhaseAnchor) -> bool:
        """
        保存锚点到PostgreSQL（异步版本，原生asyncpg）

        Args:
            anchor: 阶段锚点对象

        Returns:
            是否保存成功

        Raises:
            PersistenceError: 当所有重试都失败时抛出
        """
        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO phase_anchors
                    (id, task_id, phase, user_id, session_id, data, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, to_timestamp($7), to_timestamp($8))
                    ON CONFLICT (id) DO UPDATE SET
                        data = EXCLUDED.data,
                        updated_at = CURRENT_TIMESTAMP
                """,
                    anchor.id,
                    anchor.task_id,
                    anchor.phase,
                    anchor.user_id,
                    anchor.session_id,
                    json.dumps(anchor.data),
                    anchor.timestamp,
                    anchor.timestamp
                )
            logger.info(f"[PhaseAnchorManager] PostgreSQL异步保存成功: {anchor.id}")
            return True
        except Exception as e:
            logger.error(f"[PhaseAnchorManager] PostgreSQL异步保存最终失败: {e}", exc_info=True)
            raise PersistenceError(f"无法保存阶段锚点到PostgreSQL: {e}") from e

    # ═══════════════════════════════════════════════════════════════════
    # 异步 API（P1-Asyncify：原生 asyncpg，避免阻塞事件循环）
    # ═══════════════════════════════════════════════════════════════════

    async def get_by_task_async(self, task_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """异步获取任务的所有阶段锚点"""
        if not task_id:
            return []

        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT id, task_id, phase, user_id, session_id, data,
                           extract(epoch from created_at) as timestamp
                    FROM phase_anchors
                    WHERE task_id = $1
                    ORDER BY created_at ASC
                    LIMIT $2
                """, task_id, limit)

                results = []
                for row in rows:
                    results.append({
                        "id": row["id"],
                        "task_id": row["task_id"],
                        "phase": row["phase"],
                        "user_id": row["user_id"],
                        "session_id": row["session_id"],
                        "data": row["data"] if isinstance(row["data"], dict) else json.loads(row["data"]),
                        "timestamp": row["timestamp"]
                    })

                if results:
                    logger.debug(f"[PhaseAnchorManager] 从PostgreSQL异步加载任务锚点: {task_id}, 数量: {len(results)}")
                    return results
        except Exception as e:
            logger.error(f"[PhaseAnchorManager] 异步加载任务锚点失败: {e}", exc_info=True)

        # 降级到内存缓存
        with self._anchor_lock:
            anchor_ids = self._task_anchors.get(task_id, [])
            anchors = []
            for aid in anchor_ids:
                if aid in self._anchors:
                    anchors.append(self._anchors[aid].to_dict())
            anchors.sort(key=lambda x: x.get("timestamp", 0))
            return anchors[:limit]

    async def get_recent_by_user_async(self, user_id: str, phase: str | None = None,
                                       limit: int = 10) -> list[dict[str, Any]]:
        """异步获取用户最近的锚点"""
        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                if phase:
                    rows = await conn.fetch("""
                        SELECT id, task_id, phase, user_id, session_id, data,
                               extract(epoch from created_at) as timestamp
                        FROM phase_anchors
                        WHERE user_id = $1 AND phase = $2
                        ORDER BY created_at DESC
                        LIMIT $3
                    """, user_id, phase, limit)
                else:
                    rows = await conn.fetch("""
                        SELECT id, task_id, phase, user_id, session_id, data,
                               extract(epoch from created_at) as timestamp
                        FROM phase_anchors
                        WHERE user_id = $1
                        ORDER BY created_at DESC
                        LIMIT $2
                    """, user_id, limit)

                results = []
                for row in rows:
                    results.append({
                        "id": row["id"],
                        "task_id": row["task_id"],
                        "phase": row["phase"],
                        "user_id": row["user_id"],
                        "session_id": row["session_id"],
                        "data": row["data"] if isinstance(row["data"], dict) else json.loads(row["data"]),
                        "timestamp": row["timestamp"]
                    })

                if results:
                    logger.debug(f"[PhaseAnchorManager] 从PostgreSQL异步加载用户锚点: {user_id}, 数量: {len(results)}")
                    return results
        except Exception as e:
            logger.error(f"[PhaseAnchorManager] 异步加载用户锚点失败: {e}", exc_info=True)

        # 降级到内存缓存
        with self._anchor_lock:
            anchor_ids = self._user_anchors.get(user_id, [])
            anchors = []
            for aid in reversed(anchor_ids[-limit:]):
                if aid in self._anchors:
                    anchor = self._anchors[aid]
                    if phase is None or anchor.phase == phase:
                        anchors.append(anchor.to_dict())
            return anchors

    # 【新增】根据task_id获取锚点
    def get_by_task(self, task_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """
        获取任务的所有阶段锚点

        Args:
            task_id: 任务ID
            limit: 返回数量限制

        Returns:
            锚点列表（按时间排序）
        """
        if not task_id:
            return []

        # 首先尝试从PostgreSQL加载
        if POSTGRES_AVAILABLE and PostgresConnectionPool is not None:
            try:
                conn = PostgresConnectionPool.get_connection()
                try:
                    with conn.cursor() as cursor:
                        cursor.execute("""
                            SELECT id, task_id, phase, user_id, session_id, data,
                                   extract(epoch from created_at) as timestamp
                            FROM phase_anchors
                            WHERE task_id = %s
                            ORDER BY created_at ASC
                            LIMIT %s
                        """, (task_id, limit))

                        results = []
                        for row in cursor.fetchall():
                            results.append({
                                "id": row[0],
                                "task_id": row[1],
                                "phase": row[2],
                                "user_id": row[3],
                                "session_id": row[4],
                                "data": row[5] if isinstance(row[5], dict) else json.loads(row[5]),
                                "timestamp": row[6]
                            })

                        if results:
                            logger.debug(f"[PhaseAnchorManager] 从PostgreSQL加载任务锚点: {task_id}, 数量: {len(results)}")
                            return results
                finally:
                    PostgresConnectionPool.return_connection(conn)
            except Exception as e:
                logger.error(f"[PhaseAnchorManager] 从PostgreSQL加载任务锚点失败: {e}", exc_info=True)

        # 降级到内存缓存
        with self._anchor_lock:
            anchor_ids = self._task_anchors.get(task_id, [])
            anchors = []
            for aid in anchor_ids:
                if aid in self._anchors:
                    anchors.append(self._anchors[aid].to_dict())

            # 按时间戳排序
            anchors.sort(key=lambda x: x.get("timestamp", 0))
            return anchors[:limit]

    # 【新增】获取任务阶段摘要
    def get_summary(self, task_id: str) -> str:
        """
        获取任务阶段摘要（用于提示词注入）

        Args:
            task_id: 任务ID

        Returns:
            阶段摘要文本
        """
        anchors = self.get_by_task(task_id, limit=10)
        if not anchors:
            return ""

        parts = ["【阶段锚点】"]
        for anchor in anchors:
            phase = anchor.get("phase", "unknown")
            data = anchor.get("data", {})
            # 提取关键信息
            if isinstance(data, dict):
                key_info = ", ".join([f"{k}: {str(v)[:50]}" for k, v in list(data.items())[:3]])
            else:
                key_info = str(data)[:50]
            parts.append(f"  [{phase}] {key_info}")

        return "\n".join(parts)

    def load(self, anchor_id: str) -> dict[str, Any] | None:  # 加载阶段锚点的方法
        """
        加载阶段锚点

        Args:  # 参数说明
            anchor_id: 锚点ID  # 要加载的锚点标识

        Returns:  # 返回值说明
            锚点数据字典，不存在返回None  # 成功返回数据，失败返回None
        """
        with self._anchor_lock:  # 获取锁确保线程安全
            # 先查内存
            if anchor_id in self._anchors:  # 如果锚点在内存缓存中
                anchor = self._anchors[anchor_id]  # 获取锚点对象
                return anchor.to_dict()  # 返回锚点数据字典

            # 从磁盘加载
            anchor = self._load_from_disk(anchor_id)  # 调用方法从磁盘加载
            if anchor:  # 如果加载成功
                self._anchors[anchor_id] = anchor  # 存入内存缓存
                return anchor.to_dict()  # 返回锚点数据

            return None  # 锚点不存在，返回None

    async def load_async(self, anchor_id: str) -> dict[str, Any] | None:
        """
        异步加载阶段锚点（优先PostgreSQL，降级到内存/磁盘）

        Args:
            anchor_id: 锚点ID

        Returns:
            锚点数据字典，不存在返回None
        """
        # 先查内存
        with self._anchor_lock:
            if anchor_id in self._anchors:
                return self._anchors[anchor_id].to_dict()

        # 尝试从PostgreSQL异步加载
        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT id, task_id, phase, user_id, session_id, data,
                           extract(epoch from created_at) as timestamp
                    FROM phase_anchors
                    WHERE id = $1
                """, anchor_id)

                if row:
                    result = {
                        "id": row["id"],
                        "task_id": row["task_id"],
                        "phase": row["phase"],
                        "user_id": row["user_id"],
                        "session_id": row["session_id"],
                        "data": row["data"] if isinstance(row["data"], dict) else json.loads(row["data"]),
                        "timestamp": row["timestamp"]
                    }
                    # 回填内存缓存
                    with self._anchor_lock:
                        self._anchors[anchor_id] = PhaseAnchor.from_dict(result)
                    return result
        except Exception as e:
            logger.error(f"[PhaseAnchorManager] 异步加载锚点失败: {e}", exc_info=True)

        # 降级到磁盘加载
        anchor = self._load_from_disk(anchor_id)
        if anchor:
            with self._anchor_lock:
                self._anchors[anchor_id] = anchor
            return anchor.to_dict()
        return None

    def get_recent_by_user(self, user_id: str, phase: str | None = None,
                          limit: int = 10) -> list[dict[str, Any]]:  # 获取用户最近锚点的方法
        """
        获取用户最近的锚点

        Args:  # 参数说明
            user_id: 用户ID  # 目标用户
            phase: 筛选特定阶段（可选）  # 可选的阶段过滤
            limit: 返回数量  # 最多返回的锚点数量

        Returns:
            锚点列表  # 返回锚点数据字典列表
        """
        # 【新增】优先从PostgreSQL加载
        if POSTGRES_AVAILABLE and PostgresConnectionPool is not None:
            try:
                conn = PostgresConnectionPool.get_connection()
                try:
                    with conn.cursor() as cursor:
                        if phase:
                            cursor.execute("""
                                SELECT id, task_id, phase, user_id, session_id, data,
                                       extract(epoch from created_at) as timestamp
                                FROM phase_anchors
                                WHERE user_id = %s AND phase = %s
                                ORDER BY created_at DESC
                                LIMIT %s
                            """, (user_id, phase, limit))
                        else:
                            cursor.execute("""
                                SELECT id, task_id, phase, user_id, session_id, data,
                                       extract(epoch from created_at) as timestamp
                                FROM phase_anchors
                                WHERE user_id = %s
                                ORDER BY created_at DESC
                                LIMIT %s
                            """, (user_id, limit))

                        results = []
                        for row in cursor.fetchall():
                            results.append({
                                "id": row[0],
                                "task_id": row[1],
                                "phase": row[2],
                                "user_id": row[3],
                                "session_id": row[4],
                                "data": row[5] if isinstance(row[5], dict) else json.loads(row[5]),
                                "timestamp": row[6]
                            })

                        if results:
                            logger.debug(f"[PhaseAnchorManager] 从PostgreSQL加载用户锚点: {user_id}, 数量: {len(results)}")
                            return results
                finally:
                    PostgresConnectionPool.return_connection(conn)
            except Exception as e:
                logger.error(f"[PhaseAnchorManager] 从PostgreSQL加载用户锚点失败: {e}", exc_info=True)

        # 降级到内存缓存
        with self._anchor_lock:  # 获取锁确保线程安全
            anchor_ids = self._user_anchors.get(user_id, [])  # 获取用户的锚点ID列表
            anchors = []  # 初始化结果列表

            for aid in reversed(anchor_ids[-limit:]):  # 逆序遍历最近的锚点ID
                if aid in self._anchors:  # 如果锚点在内存中
                    anchor = self._anchors[aid]  # 获取锚点对象
                    if phase is None or anchor.phase == phase:  # 如果未指定阶段或阶段匹配
                        anchors.append(anchor.to_dict())  # 添加到结果列表

            return anchors  # 返回锚点列表

    def get_last_anchor_id(self, user_id: str = "default") -> str | None:  # 获取用户最后一个锚点ID的方法
        """获取用户最后一个锚点ID"""  # 方法文档字符串
        with self._anchor_lock:  # 获取锁确保线程安全
            anchor_ids = self._user_anchors.get(user_id, [])  # 获取用户锚点ID列表
            return anchor_ids[-1] if anchor_ids else None  # 返回最后一个ID，如果没有则返回None

    def get_anchor(self, anchor_id: str) -> dict[str, Any] | None:  # 获取锚点的方法（load的别名）
        """获取锚点（load的别名，便于外部使用）"""  # 方法文档字符串
        return self.load(anchor_id)  # 调用load方法

    def update(self, anchor_id: str, data: dict[str, Any]) -> bool:  # 更新锚点数据的方法
        """
        更新锚点数据

        Args:  # 参数说明
            anchor_id: 锚点ID  # 要更新的锚点
            data: 新数据（会合并到原有数据）  # 更新的数据（合并而非替换）

        Returns:  # 返回值说明
            是否成功  # True表示成功，False表示锚点不存在
        """
        with self._anchor_lock:  # 获取锁确保线程安全
            if anchor_id not in self._anchors:  # 如果锚点不存在
                return False  # 返回失败

            anchor = self._anchors[anchor_id]  # 获取锚点对象
            anchor.data.update(data)  # 更新数据（合并字典）
            anchor.timestamp = time.time()  # 更新时间戳

            # 重新持久化
            self._persist_async(anchor)  # 异步保存到磁盘
            self._save_to_postgres(anchor)  # 【新增】更新PostgreSQL

            return True  # 返回成功

    async def update_async(self, anchor_id: str, data: dict[str, Any]) -> bool:
        """
        异步更新锚点数据（原生asyncpg）

        Args:
            anchor_id: 锚点ID
            data: 新数据（会合并到原有数据）

        Returns:
            是否成功
        """
        with self._anchor_lock:
            if anchor_id not in self._anchors:
                return False

            anchor = self._anchors[anchor_id]
            anchor.data.update(data)
            anchor.timestamp = time.time()

        # 异步持久化到磁盘（fire-and-forget）
        self._persist_async(anchor)

        # 异步更新PostgreSQL（原生asyncpg）
        try:
            await self._save_to_postgres_async(anchor)
            return True
        except Exception:
            return False

    def delete(self, anchor_id: str) -> bool:  # 删除锚点的方法
        """删除锚点"""  # 方法文档字符串
        with self._anchor_lock:  # 获取锁确保线程安全
            if anchor_id not in self._anchors:  # 如果锚点不存在
                return False  # 返回失败

            anchor = self._anchors.pop(anchor_id)  # 从内存缓存中移除并获取锚点对象

            # 从用户索引中移除
            user_id = anchor.user_id  # 获取锚点的用户ID
            if user_id in self._user_anchors and anchor_id in self._user_anchors[user_id]:  # 如果用户存在且锚点ID在用户列表中
                self._user_anchors[user_id].remove(anchor_id)  # 从用户列表移除

            # 【新增】从任务索引中移除
            task_id = anchor.task_id
            if task_id and task_id in self._task_anchors and anchor_id in self._task_anchors[task_id]:
                self._task_anchors[task_id].remove(anchor_id)

            # 删除磁盘文件
            self._delete_from_disk(anchor_id)  # 调用方法删除磁盘文件

            # 【新增】从PostgreSQL删除
            self._delete_from_postgres(anchor_id)

            return True  # 返回成功

    async def delete_async(self, anchor_id: str) -> bool:
        """异步删除锚点（原生asyncpg）"""
        with self._anchor_lock:
            if anchor_id not in self._anchors:
                return False

            anchor = self._anchors.pop(anchor_id)

            user_id = anchor.user_id
            if user_id in self._user_anchors and anchor_id in self._user_anchors[user_id]:
                self._user_anchors[user_id].remove(anchor_id)

            task_id = anchor.task_id
            if task_id and task_id in self._task_anchors and anchor_id in self._task_anchors[task_id]:
                self._task_anchors[task_id].remove(anchor_id)

            self._delete_from_disk(anchor_id)

        # 异步从PostgreSQL删除（原生asyncpg）
        await self._delete_from_postgres_async(anchor_id)
        return True

    # 【新增】从PostgreSQL删除
    def _delete_from_postgres(self, anchor_id: str) -> bool:
        """从PostgreSQL删除锚点（同步版本）"""
        if not POSTGRES_AVAILABLE or PostgresConnectionPool is None:
            return False

        try:
            conn = PostgresConnectionPool.get_connection()
            try:
                with conn.cursor() as cursor:
                    cursor.execute("DELETE FROM phase_anchors WHERE id = %s", (anchor_id,))
                    conn.commit()
                    logger.debug(f"[PhaseAnchorManager] 锚点已从PostgreSQL删除: {anchor_id}")
                    return True
            finally:
                PostgresConnectionPool.return_connection(conn)
        except Exception as e:
            logger.error(f"[PhaseAnchorManager] 从PostgreSQL删除锚点失败: {e}", exc_info=True)
            return False

    async def _delete_from_postgres_async(self, anchor_id: str) -> bool:
        """从PostgreSQL删除锚点（异步版本，原生asyncpg）"""
        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                await conn.execute("DELETE FROM phase_anchors WHERE id = $1", anchor_id)
            logger.debug(f"[PhaseAnchorManager] 锚点已从PostgreSQL异步删除: {anchor_id}")
            return True
        except Exception as e:
            logger.error(f"[PhaseAnchorManager] 从PostgreSQL异步删除锚点失败: {e}", exc_info=True)
            return False

    def _cleanup_old_anchors(self, user_id: str):  # 清理用户旧锚点的私有方法
        """清理用户的旧锚点"""  # 方法文档字符串
        anchor_ids = self._user_anchors.get(user_id, [])  # 获取用户锚点ID列表
        if len(anchor_ids) > self._max_memory_anchors:  # 如果超过最大缓存数量
            # 保留最近的，移除旧的
            to_remove = anchor_ids[:-self._max_memory_anchors]  # 获取需要移除的旧锚点ID
            for aid in to_remove:  # 遍历需要移除的锚点
                if aid in self._anchors:  # 如果锚点在内存中
                    # 只从内存移除，不移除磁盘
                    del self._anchors[aid]  # 从内存缓存删除
            self._user_anchors[user_id] = anchor_ids[-self._max_memory_anchors:]  # 更新用户索引

    def _persist_async(self, anchor: PhaseAnchor):  # 异步持久化锚点的私有方法
        """异步持久化到磁盘"""  # 方法文档字符串
        def save():  # 定义内部保存函数
            try:  # 异常捕获块
                file_path = self._persist_dir / f"{anchor.id}.json"  # 构建文件路径
                with open(file_path, 'w', encoding='utf-8') as f:  # 以写入模式打开文件
                    json.dump(anchor.to_dict(), f, ensure_ascii=False, indent=2)  # 写入JSON数据
            except Exception as e:  # 捕获所有异常
                logger.error(f"[PhaseAnchor] 持久化失败: {e}")  # 记录错误日志

        threading.Thread(target=save, daemon=True).start()  # 在新线程中执行保存（守护线程）

    def _load_from_disk(self, anchor_id: str) -> PhaseAnchor | None:  # 从磁盘加载锚点的私有方法
        """
        从磁盘加载锚点

        Args:
            anchor_id: 锚点ID

        Returns:
            PhaseAnchor对象或None（文件不存在时）

        Raises:
            LoadError: 当文件读取或解析失败时抛出
        """  # 方法文档字符串
        file_path = self._persist_dir / f"{anchor_id}.json"  # 构建文件路径

        try:  # 异常捕获块
            if not file_path.exists():  # 如果文件不存在
                logger.debug(f"[PhaseAnchor] 本地文件不存在: {file_path}")
                return None  # 返回None

            with open(file_path, encoding='utf-8') as f:  # 以读取模式打开文件
                data = json.load(f)  # 解析JSON数据

            logger.debug(f"[PhaseAnchor] 本地文件加载成功: {file_path}")
            return PhaseAnchor.from_dict(data)  # 从字典创建PhaseAnchor对象并返回
        except FileNotFoundError:
            logger.warning(f"[PhaseAnchor] 本地文件不存在: {file_path}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"[PhaseAnchor] JSON解析失败 {file_path}: {e}")
            return None
        except PermissionError as e:
            logger.error(f"[PhaseAnchor] 文件权限错误 {file_path}: {e}")
            raise LoadError(f"无法读取阶段锚点文件(权限不足): {file_path}") from e
        except Exception as e:  # 其他未预期异常
            logger.error(f"[PhaseAnchor] 加载本地文件失败 {file_path}: {e}", exc_info=True)
            raise LoadError(f"无法加载阶段锚点: {e}") from e

    def _delete_from_disk(self, anchor_id: str):  # 从磁盘删除锚点的私有方法
        """从磁盘删除锚点"""  # 方法文档字符串
        try:  # 异常捕获块
            file_path = self._persist_dir / f"{anchor_id}.json"  # 构建文件路径
            if file_path.exists():  # 如果文件存在
                file_path.unlink()  # 删除文件
        except Exception as e:  # 捕获所有异常
            logger.error(f"[PhaseAnchor] 删除磁盘文件失败: {e}")  # 记录错误日志


# 全局实例
_phase_anchor_manager = None  # 初始化全局管理器实例变量为None

def get_phase_anchor_manager() -> PhaseAnchorManager:  # 获取阶段锚点管理器实例的函数
    """获取阶段锚点管理器实例"""  # 函数文档字符串
    global _phase_anchor_manager  # 声明使用全局变量
    if _phase_anchor_manager is None:  # 如果实例尚未创建
        _phase_anchor_manager = PhaseAnchorManager()  # 创建管理器实例
    return _phase_anchor_manager  # 返回全局实例


# 便捷函数
async def save_anchor(phase: str, data: dict[str, Any],
                user_id: str = "default",
                session_id: str = "",
                task_id: str = "") -> str:  # 便捷保存锚点的函数
    """便捷保存锚点（异步版本）"""  # 函数文档字符串
    return await get_phase_anchor_manager().save(phase, data, user_id, session_id, task_id)  # 调用管理器的save方法

def load_anchor(anchor_id: str) -> dict[str, Any] | None:  # 便捷加载锚点的函数
    """便捷加载锚点"""  # 函数文档字符串
    return get_phase_anchor_manager().load(anchor_id)  # 调用管理器的load方法

def get_task_anchors(task_id: str, limit: int = 100) -> list[dict[str, Any]]:
    """【新增】获取任务的所有锚点"""
    return get_phase_anchor_manager().get_by_task(task_id, limit)

def get_task_phase_summary(task_id: str) -> str:
    """【新增】获取任务阶段摘要（用于提示词注入）"""
    return get_phase_anchor_manager().get_summary(task_id)

# ═══════════════════════════════════════════════════════════════════════════════
# 【文件总结】
# ═══════════════════════════════════════════════════════════════════════════════
#
# 【文件角色】
# 本文件(phase_anchor.py)是SiliconBase V5核心模块中的阶段锚点管理器。
# 它提供任务执行过程中各个阶段状态的保存和恢复功能，是实现"跨模式记忆基础设施"
# 的核心组件。通过保存阶段快照，支持任务中断恢复、弱连接、长任务管理等功能。
#
# 【在系统中的位置】
# - 位于: SiliconBase_V5/core/phase_anchor.py
# - 上游调用: agent_loop.py（主循环保存各阶段状态）
# - 下游依赖: core/logger.py（日志记录）、core/memory.py（PostgreSQL连接）
#
# 【关联文件】
# 1. core/agent_loop.py - Agent主循环，在perception/execution等阶段调用保存锚点
# 2. core/weak_connection.py - 弱连接引擎，使用锚点ID关联上下文
# 3. core/long_running_manager.py - 长任务管理器，使用锚点恢复任务状态
# 4. data/phase_anchors/ - 锚点数据持久化目录
# 5. PostgreSQL - 阶段锚点持久化存储（新增）
#
# 【核心功能】
# 1. 阶段快照: 保存任务执行的各个阶段状态（init/perception/understanding/execution/completion）
# 2. 跨会话恢复: 通过锚点ID可以在不同会话间恢复上下文
# 3. 内存缓存: 最近100个锚点保存在内存中，快速访问
# 4. 异步持久化: 锚点数据异步保存到磁盘，不阻塞主流程
# 5. PostgreSQL持久化: 【新增】锚点数据保存到PostgreSQL，支持断点续传恢复
# 6. 用户隔离: 支持多用户，每个用户的锚点独立管理
# 7. 自动清理: 内存锚点超过100个时自动清理旧锚点
#
# 【达到的效果】
# 1. 断点续传: 任务中断后可以从锚点恢复，无需重新开始
# 2. 弱连接支持: 为弱连接引擎提供上下文关联基础
# 3. 长任务管理: 支持长时间任务的暂停和恢复
# 4. 模式切换: 支持日常模式与专注模式间的上下文传递
# 5. 审计追踪: 保留任务执行的完整历史轨迹
# 6. 单例模式: 确保系统中只有一个锚点管理器实例
#
# 【使用示例】
#   # 保存阶段锚点
#   anchor_id = save_anchor("execution", {"tool": "file_manager", "result": "success"},
#                          task_id="task_001")
#
#   # 加载阶段锚点
#   anchor_data = load_anchor(anchor_id)
#
#   # 获取任务的所有锚点
#   task_anchors = get_task_anchors("task_001")
#
# ═══════════════════════════════════════════════════════════════════════════════
