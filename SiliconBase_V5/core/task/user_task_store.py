#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""  # 多行文档字符串开始
用户任务存储层 V5.1 (Async)  # 模块功能概述
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  # 装饰分隔线
为用户级任务管理系统提供异步持久化存储支持  # 核心职责

【设计原则】  # 设计说明
  - 使用 AsyncPostgresPool 的 asyncpg 连接池  # 原则1
  - 任务表与记忆表在同一数据库中  # 原则2
  - 支持事务操作和乐观锁  # 原则3
  - 自动记录任务变更历史  # 原则4
  - 支持任务依赖关系管理  # 原则5

【表结构】  # 数据库表说明
  - user_tasks: 任务主表  # 表1
  - task_dependencies: 任务依赖关系表  # 表2
  - task_history: 任务变更历史表  # 表3
  - task_memory_links: 任务与记忆关联表  # 表4

【2026-02-26 创建】  # 创建日期
【2026-06-01 迁移】全面 asyncpg 化
"""  # 文档字符串结束
import asyncio  # 导入异步IO模块
import json  # 导入JSON模块，用于序列化和反序列化
import logging  # 导入日志模块
import uuid  # 导入UUID模块，用于生成唯一ID
from contextlib import asynccontextmanager  # 导入异步上下文管理器装饰器
from datetime import datetime  # 导入日期时间类
from typing import Any  # 导入类型注解

# 尝试导入读写锁，如不可用则使用普通锁  # 读写锁兼容性处理
# 【async迁移】DummyRWLock 使用 asyncio.Lock
try:  # 尝试导入
    from readerwriterlock import rwlock  # 导入第三方读写锁库
except ImportError:  # 导入失败时的回退
    class _DummyRWLock:  # 定义虚拟读写锁类
        def __init__(self):  # 初始化方法
            self._lock = asyncio.Lock()  # 使用异步锁作为替代
        def gen_rlock(self):  # 生成读锁
            return self._lock  # 返回锁对象
        def gen_wlock(self):  # 生成写锁
            return self._lock  # 返回锁对象（同读锁）

    class rwlock:  # 定义兼容的rwlock类
        @staticmethod  # 静态方法装饰器
        def RWLockFair():  # 创建公平读写锁
            return _DummyRWLock()  # 返回虚拟锁实例

# 导入记忆管理器（条件导入）
try:
    from core.memory.memory_manager import MemoryManager
except ImportError:
    MemoryManager = None

# 【async迁移】导入 AsyncPostgresPool
from core.memory.postgres_pool import AsyncPostgresPool

# 【修复】导入统一的TaskStatus枚举，不重复定义
from core.task.task_status import TERMINAL_STATUSES, TaskStatus

logger = logging.getLogger(__name__)  # 获取当前模块的日志记录器

# 便捷导出：终态元组（用于SQL IN查询）  # SQL查询辅助常量
TERMINAL_STATUSES_TUPLE = tuple(TERMINAL_STATUSES)  # 转换为元组

# 依赖类型枚举  # 依赖关系常量
class DependencyType:  # 依赖类型类
    BLOCKS = "blocks"           # 阻塞关系（前置任务完成才能开始）
    RELATES_TO = "relates_to"   # 关联关系
    PARENT_CHILD = "parent_child"  # 父子关系

# 优先级常量  # 任务优先级常量定义
PRIORITY_URGENT = 0  # 紧急优先级（最高）
PRIORITY_HIGH = 1  # 高优先级
PRIORITY_NORMAL = 2  # 普通优先级（默认）
PRIORITY_LOW = 3  # 低优先级


class UserTaskStore:  # 用户任务存储类
    """  # 类文档字符串
    用户任务存储类 (Async)  # 类功能概述
    使用 asyncpg 异步连接池管理任务数据  # 技术实现
    """  # 文档字符串结束

    def __init__(self, user_id: str):
        """
        初始化用户任务存储

        Args:
            user_id: 用户唯一标识
        """
        self.user_id = user_id
        self._memory_manager = MemoryManager() if MemoryManager else None
        self._rw_lock = asyncio.Lock()
        self._init_lock = asyncio.Lock()
        self._tables_initialized = False
        if MemoryManager:
            logger.debug(f"[UserTaskStore] 用户 {user_id} 的任务存储初始化完成 (Async PostgreSQL)")
        else:
            logger.warning("[UserTaskStore] MemoryManager 不可用，任务存储功能受限")

    async def _ensure_tables(self):
        """懒加载：首次异步操作时初始化表结构"""
        if self._tables_initialized:
            return
        async with self._init_lock:
            if self._tables_initialized:
                return
            await self._init_tables()
            self._tables_initialized = True

    async def _init_tables(self):  # 初始化表结构方法
        """初始化任务相关表结构（asyncpg 版本）"""  # 方法文档字符串
        pool = await AsyncPostgresPool.get_pool()
        try:  # 异常处理
            async with pool.acquire() as conn, conn.transaction():  # 获取连接和事务
                    # 任务主表  # 创建user_tasks表
                    await conn.execute('''
                        CREATE TABLE IF NOT EXISTS user_tasks (
                            id TEXT PRIMARY KEY,
                            user_id TEXT NOT NULL,
                            title TEXT NOT NULL,
                            description TEXT,
                            status TEXT CHECK(status IN ('pending', 'ready', 'running', 'completed', 'failed', 'cancelled', 'archived')),
                            priority INTEGER DEFAULT 2,
                            task_type TEXT,
                            parent_id TEXT,
                            memory_ids TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            started_at TIMESTAMP,
                            completed_at TIMESTAMP,
                            deadline TIMESTAMP,
                            retry_count INTEGER DEFAULT 0,
                            max_retries INTEGER DEFAULT 3,
                            result TEXT,
                            error TEXT,
                            metadata TEXT,
                            version INTEGER DEFAULT 1,
                            is_compressed BOOLEAN DEFAULT FALSE,
                            compressed_summary TEXT,
                            FOREIGN KEY (parent_id) REFERENCES user_tasks(id) ON DELETE CASCADE
                        )
                    ''')

                    # 任务依赖关系表  # 创建task_dependencies表
                    await conn.execute('''
                        CREATE TABLE IF NOT EXISTS task_dependencies (
                            id TEXT PRIMARY KEY,
                            task_id TEXT NOT NULL,
                            depends_on_task_id TEXT NOT NULL,
                            dependency_type TEXT CHECK(dependency_type IN ('blocks', 'relates_to', 'parent_child')),
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            FOREIGN KEY (task_id) REFERENCES user_tasks(id) ON DELETE CASCADE,
                            FOREIGN KEY (depends_on_task_id) REFERENCES user_tasks(id) ON DELETE CASCADE,
                            UNIQUE(task_id, depends_on_task_id)
                        )
                    ''')

                    # 任务变更历史表  # 创建task_history表
                    await conn.execute('''
                        CREATE TABLE IF NOT EXISTS task_history (
                            id TEXT PRIMARY KEY,
                            task_id TEXT NOT NULL,
                            field_name TEXT NOT NULL,
                            old_value TEXT,
                            new_value TEXT,
                            changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            changed_by TEXT,
                            version INTEGER,
                            FOREIGN KEY (task_id) REFERENCES user_tasks(id) ON DELETE CASCADE
                        )
                    ''')

                    # 任务与记忆关联表  # 创建task_memory_links表
                    await conn.execute('''
                        CREATE TABLE IF NOT EXISTS task_memory_links (
                            id TEXT PRIMARY KEY,
                            task_id TEXT NOT NULL,
                            memory_id TEXT NOT NULL,
                            link_type TEXT DEFAULT 'reference',
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            FOREIGN KEY (task_id) REFERENCES user_tasks(id) ON DELETE CASCADE,
                            UNIQUE(task_id, memory_id)
                        )
                    ''')

                    # 创建索引  # 索引优化
                    await conn.execute('CREATE INDEX IF NOT EXISTS idx_tasks_user_id ON user_tasks(user_id)')
                    await conn.execute('CREATE INDEX IF NOT EXISTS idx_tasks_status ON user_tasks(status)')
                    await conn.execute('CREATE INDEX IF NOT EXISTS idx_tasks_priority ON user_tasks(priority)')
                    await conn.execute('CREATE INDEX IF NOT EXISTS idx_tasks_parent_id ON user_tasks(parent_id)')
                    await conn.execute('CREATE INDEX IF NOT EXISTS idx_tasks_deadline ON user_tasks(deadline)')
                    await conn.execute('CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON user_tasks(created_at)')
                    await conn.execute('CREATE INDEX IF NOT EXISTS idx_tasks_version ON user_tasks(version)')

                    await conn.execute('CREATE INDEX IF NOT EXISTS idx_deps_task_id ON task_dependencies(task_id)')
                    await conn.execute('CREATE INDEX IF NOT EXISTS idx_deps_depends_on ON task_dependencies(depends_on_task_id)')

                    await conn.execute('CREATE INDEX IF NOT EXISTS idx_history_task_id ON task_history(task_id)')
                    await conn.execute('CREATE INDEX IF NOT EXISTS idx_history_changed_at ON task_history(changed_at)')

                    await conn.execute('CREATE INDEX IF NOT EXISTS idx_memlinks_task_id ON task_memory_links(task_id)')
                    await conn.execute('CREATE INDEX IF NOT EXISTS idx_memlinks_memory_id ON task_memory_links(memory_id)')
        except Exception as e:  # 捕获异常
            logger.error(f"[UserTaskStore] 初始化表结构失败: {e}")  # 记录错误
            raise  # 抛出异常

    @asynccontextmanager  # 异步上下文管理器装饰器
    async def transaction(self):  # 事务上下文管理器
        """  # 方法文档字符串
        异步事务上下文管理器  # 方法功能

        Usage:  # 使用示例
            async with self.transaction() as conn:  # 使用事务
                await conn.execute("INSERT ...")  # 执行SQL
                await conn.execute("UPDATE ...")  # 执行SQL
        """  # 文档字符串结束
        pool = await AsyncPostgresPool.get_pool()
        async with pool.acquire() as conn, conn.transaction():
            yield conn

    def _generate_id(self) -> str:  # 生成唯一ID方法
        """生成唯一ID"""  # 方法文档字符串
        return str(uuid.uuid4())  # 生成UUID字符串

    def _now(self) -> str:  # 获取当前时间戳方法
        """获取当前时间戳"""  # 方法文档字符串
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")  # 格式化为字符串

    async def _record_history(self, conn, task_id: str, field_name: str,  # 记录变更历史方法
                              old_value: Any, new_value: Any, version: int, changed_by: str = "system"):  # 参数
        """记录字段变更历史（asyncpg 版本）"""  # 方法文档字符串
        history_id = self._generate_id()  # 生成历史记录ID
        await conn.execute('''  # 插入历史记录
            INSERT INTO task_history (id, task_id, field_name, old_value, new_value, version, changed_by)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
        ''',  # SQL结束
            history_id,  # 历史ID
            task_id,  # 任务ID
            field_name,  # 字段名
            json.dumps(old_value, ensure_ascii=False) if old_value is not None else None,  # 旧值（JSON序列化）
            json.dumps(new_value, ensure_ascii=False) if new_value is not None else None,  # 新值（JSON序列化）
            version,  # 版本号
            changed_by  # 变更者
        )

    async def create_task(self, task_data: dict) -> str:  # 创建任务方法
        """  # 方法文档字符串
        创建新任务  # 方法功能

        Args:  # 参数说明
            task_data: 任务数据字典，包含:  # 参数字典
                - title: 任务标题 (必需)  # 字段1
                - description: 任务描述  # 字段2
                - status: 任务状态，默认 'pending'  # 字段3
                - priority: 优先级 0-3，默认 2  # 字段4
                - task_type: 任务类型  # 字段5
                - parent_id: 父任务ID  # 字段6
                - memory_ids: 关联的记忆ID列表  # 字段7
                - deadline: 截止时间  # 字段8
                - max_retries: 最大重试次数，默认 3  # 字段9
                - metadata: 额外元数据字典  # 字段10

        Returns:  # 返回值说明
            新创建的任务ID  # 返回类型
        """  # 文档字符串结束
        await self._ensure_tables()
        task_id = self._generate_id()  # 生成任务ID

        # 提取字段，设置默认值  # 数据处理
        title = task_data.get('title')  # 获取标题
        if not title:  # 标题为空检查
            raise ValueError("任务标题 title 是必需的")  # 抛出异常

        description = task_data.get('description')  # 获取描述
        status = task_data.get('status', TaskStatus.PENDING)  # 获取状态（默认pending）
        priority = task_data.get('priority', PRIORITY_NORMAL)  # 获取优先级（默认普通）
        task_type = task_data.get('task_type')  # 获取任务类型
        parent_id = task_data.get('parent_id')  # 获取父任务ID
        memory_ids = json.dumps(task_data.get('memory_ids', []), ensure_ascii=False) if task_data.get('memory_ids') else None  # 序列化记忆ID列表
        deadline = task_data.get('deadline')  # 获取截止时间
        max_retries = task_data.get('max_retries', 3)  # 获取最大重试次数
        metadata = json.dumps(task_data.get('metadata', {}), ensure_ascii=False) if task_data.get('metadata') else None  # 序列化元数据

        pool = await AsyncPostgresPool.get_pool()
        try:  # 异常处理
            async with pool.acquire() as conn, conn.transaction():  # 获取连接和事务
                    await conn.execute('''  # 插入任务
                        INSERT INTO user_tasks (
                            id, user_id, title, description, status, priority,
                            task_type, parent_id, memory_ids, deadline,
                            max_retries, metadata, created_at, updated_at
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                    ''',  # SQL结束
                        task_id, self.user_id, title, description, status, priority,  # 基础字段
                        task_type, parent_id, memory_ids, deadline,  # 扩展字段
                        max_retries, metadata, self._now(), self._now()  # 元数据和时间
                    )

                    # 记录创建历史  # 变更历史
                    await self._record_history(conn, task_id, "created", None, {"title": title, "status": status}, 1)  # 记录创建

                    return task_id  # 返回任务ID
        except Exception as e:  # 捕获异常
            logger.error(f"[UserTaskStore] 创建任务失败: {e}")  # 记录错误
            raise  # 抛出异常

    async def get_task(self, task_id: str) -> dict | None:  # 获取任务方法
        """  # 方法文档字符串
        获取任务详情  # 方法功能

        Args:  # 参数说明
            task_id: 任务ID  # 参数

        Returns:  # 返回值说明
            任务数据字典，或 None 如果不存在  # 返回类型
        """  # 文档字符串结束
        await self._ensure_tables()
        pool = await AsyncPostgresPool.get_pool()
        try:  # 异常处理
            row = await pool.fetchrow('''  # 查询任务
                SELECT id, user_id, title, description, status, priority,
                       task_type, parent_id, memory_ids, created_at, updated_at,
                       started_at, completed_at, deadline, retry_count, max_retries,
                       result, error, metadata, version, is_compressed, compressed_summary
                FROM user_tasks WHERE id = $1 AND user_id = $2
            ''', task_id, self.user_id)  # 参数：任务ID和用户ID

            if not row:  # 结果为空
                return None  # 返回None

            return self._row_to_dict(row)  # 转换为字典并返回
        except Exception as e:  # 捕获异常
            logger.error(f"[UserTaskStore] 获取任务失败: {e}")  # 记录错误
            return None  # 返回None

    def _row_to_dict(self, row: Any) -> dict:  # 行转字典方法
        """将 asyncpg Record 转换为字典（列名访问）"""  # 方法文档字符串
        r = dict(row)
        return {  # 构建字典
            "id": r["id"],  # 任务ID
            "user_id": r["user_id"],  # 用户ID
            "title": r["title"],  # 标题
            "description": r["description"],  # 描述
            "status": r["status"],  # 状态
            "priority": r["priority"],  # 优先级
            "task_type": r["task_type"],  # 任务类型
            "parent_id": r["parent_id"],  # 父任务ID
            "memory_ids": json.loads(r["memory_ids"]) if r.get("memory_ids") else [],  # 反序列化记忆ID列表
            "created_at": r["created_at"],  # 创建时间
            "updated_at": r["updated_at"],  # 更新时间
            "started_at": r["started_at"],  # 开始时间
            "completed_at": r["completed_at"],  # 完成时间
            "deadline": r["deadline"],  # 截止时间
            "retry_count": r["retry_count"],  # 重试次数
            "max_retries": r["max_retries"],  # 最大重试次数
            "result": json.loads(r["result"]) if r.get("result") else None,  # 反序列化结果
            "error": r["error"],  # 错误信息
            "metadata": json.loads(r["metadata"]) if r.get("metadata") else {},  # 反序列化元数据
            "version": r["version"],  # 版本号
            "is_compressed": bool(r["is_compressed"]),  # 是否已压缩
            "compressed_summary": r["compressed_summary"]  # 压缩摘要
        }

    async def update_task(self, task_id: str, updates: dict, record_history: bool = True) -> bool:  # 更新任务方法
        """  # 方法文档字符串
        更新任务  # 方法功能

        Args:  # 参数说明
            task_id: 任务ID  # 参数1
            updates: 要更新的字段字典  # 参数2
            record_history: 是否记录变更历史，默认 True  # 参数3

        Returns:  # 返回值说明
            是否更新成功  # 返回类型
        """  # 文档字符串结束
        await self._ensure_tables()
        # 不可直接更新的字段  # 保护字段列表
        protected_fields = {'id', 'user_id', 'created_at', 'version'}  # ID、用户ID、创建时间、版本号不可修改

        # 过滤有效字段  # 字段过滤
        valid_updates = {k: v for k, v in updates.items() if k not in protected_fields}  # 排除保护字段

        if not valid_updates:  # 没有有效更新
            return False  # 返回失败

        pool = await AsyncPostgresPool.get_pool()
        try:  # 异常处理
            async with pool.acquire() as conn, conn.transaction():  # 获取连接和事务
                    # 获取当前任务数据（用于历史记录和乐观锁）  # 数据一致性检查
                    row = await conn.fetchrow(
                        'SELECT * FROM user_tasks WHERE id = $1 AND user_id = $2',
                        task_id, self.user_id
                    )
                    if not row:  # 任务不存在
                        return False  # 返回失败

                    current_data = self._row_to_dict(row)  # 转换为字典
                    current_version = current_data['version']  # 获取当前版本号

                    # 构建更新语句  # SQL构建
                    set_clauses = []  # SET子句列表
                    params = []  # 参数列表
                    param_idx = 0

                    for field, value in valid_updates.items():  # 遍历更新字段
                        if field in ['memory_ids', 'result', 'metadata']:  # JSON字段需要序列化
                            value = json.dumps(value, ensure_ascii=False) if value else None  # JSON序列化

                        param_idx += 1
                        set_clauses.append(f"{field} = ${param_idx}")  # 添加SET子句
                        params.append(value)  # 添加参数

                        # 记录历史  # 变更历史
                        if record_history and field in current_data:  # 如果启用历史记录且字段存在
                            old_value = current_data.get(field)  # 获取旧值
                            if old_value != value:  # 值有变化
                                await self._record_history(conn, task_id, field, old_value, value,  # 记录变更
                                                           current_version + 1)

                    # 更新版本号和时间  # 版本控制
                    param_idx += 1
                    set_clauses.append(f"version = ${param_idx}")
                    params.append(current_version + 1)

                    param_idx += 1
                    set_clauses.append(f"updated_at = ${param_idx}")
                    params.append(self._now())

                    # WHERE 条件参数索引起始位置
                    where_idx_start = param_idx + 1
                    params.extend([task_id, self.user_id, current_version])

                    sql = f"UPDATE user_tasks SET {', '.join(set_clauses)} WHERE id = ${where_idx_start} AND user_id = ${where_idx_start + 1} AND version = ${where_idx_start + 2}"
                    result = await conn.execute(sql, *params)  # 执行更新

                    if "UPDATE 1" not in result:  # 没有行受影响（版本冲突或不存在）
                        logger.warning(f"[UserTaskStore] 任务 {task_id} 更新失败，可能是版本冲突")  # 记录警告
                        return False  # 返回失败

                    return True  # 返回成功
        except Exception as e:  # 捕获异常
            logger.error(f"[UserTaskStore] 更新任务失败: {e}")  # 记录错误
            return False  # 返回失败

    async def delete_task(self, task_id: str, soft_delete: bool = False) -> bool:  # 删除任务方法
        """  # 方法文档字符串
        删除任务  # 方法功能

        Args:  # 参数说明
            task_id: 任务ID  # 参数1
            soft_delete: 是否软删除（标记为 archived），默认 False（硬删除）  # 参数2

        Returns:  # 返回值说明
            是否删除成功  # 返回类型
        """  # 文档字符串结束
        await self._ensure_tables()
        if soft_delete:  # 软删除
            return await self.update_task(task_id, {'status': TaskStatus.ARCHIVED})  # 更新状态为archived

        pool = await AsyncPostgresPool.get_pool()
        try:  # 异常处理
            async with pool.acquire() as conn, conn.transaction():  # 获取连接和事务
                    result = await conn.execute(
                        'DELETE FROM user_tasks WHERE id = $1 AND user_id = $2',
                        task_id, self.user_id
                    )
                    return "DELETE 1" in result  # 返回是否有行被删除
        except Exception as e:  # 捕获异常
            logger.error(f"[UserTaskStore] 删除任务失败: {e}")  # 记录错误
            return False  # 返回失败

    async def add_dependency(self, task_id: str, depends_on: str, dep_type: str = "blocks") -> bool:  # 添加依赖方法
        """  # 方法文档字符串
        添加任务依赖关系  # 方法功能

        Args:  # 参数说明
            task_id: 依赖方任务ID  # 参数1
            depends_on: 被依赖方任务ID  # 参数2
            dep_type: 依赖类型 ('blocks', 'relates_to', 'parent_child')，默认 'blocks'  # 参数3

        Returns:  # 返回值说明
            是否添加成功  # 返回类型
        """  # 文档字符串结束
        await self._ensure_tables()
        # 检查循环依赖  # 循环依赖检测
        if await self.check_circular_dependency(task_id, depends_on):  # 如果存在循环
            logger.warning(f"[UserTaskStore] 检测到循环依赖: {task_id} -> {depends_on}")  # 记录警告
            return False  # 返回失败

        pool = await AsyncPostgresPool.get_pool()
        try:  # 异常处理
            async with pool.acquire() as conn, conn.transaction():  # 获取连接和事务
                    # 检查任务是否存在  # 存在性检查
                    rows = await conn.fetch(
                        'SELECT id FROM user_tasks WHERE id IN ($1, $2) AND user_id = $3',
                        task_id, depends_on, self.user_id
                    )
                    existing = {row["id"] for row in rows}  # 获取存在的ID集合
                    if task_id not in existing or depends_on not in existing:  # 有任务不存在
                        logger.warning(f"[UserTaskStore] 任务不存在: {task_id} 或 {depends_on}")  # 记录警告
                        return False  # 返回失败

                    dep_id = self._generate_id()  # 生成依赖ID
                    # PostgreSQL UPSERT using ON CONFLICT  # UPSERT操作
                    await conn.execute('''
                        INSERT INTO task_dependencies (id, task_id, depends_on_task_id, dependency_type)
                        VALUES ($1, $2, $3, $4)
                        ON CONFLICT (task_id, depends_on_task_id) DO UPDATE SET
                            dependency_type = EXCLUDED.dependency_type,
                            created_at = CURRENT_TIMESTAMP
                    ''', dep_id, task_id, depends_on, dep_type)  # 执行插入或更新

                    # 更新任务状态为 pending（如果依赖未满足）  # 状态自动更新
                    await self._update_task_status_based_on_dependencies(conn, task_id)  # 检查依赖状态

                    return True  # 返回成功
        except Exception as e:  # 捕获异常
            logger.error(f"[UserTaskStore] 添加依赖失败: {e}")  # 记录错误
            return False  # 返回失败

    async def remove_dependency(self, task_id: str, depends_on: str) -> bool:  # 移除依赖方法
        """  # 方法文档字符串
        移除任务依赖关系  # 方法功能

        Args:  # 参数说明
            task_id: 依赖方任务ID  # 参数1
            depends_on: 被依赖方任务ID  # 参数2

        Returns:  # 返回值说明
            是否移除成功  # 返回类型
        """  # 文档字符串结束
        await self._ensure_tables()
        pool = await AsyncPostgresPool.get_pool()
        try:  # 异常处理
            async with pool.acquire() as conn, conn.transaction():  # 获取连接和事务
                    result = await conn.execute('''
                        DELETE FROM task_dependencies
                        WHERE task_id = $1 AND depends_on_task_id = $2
                    ''', task_id, depends_on)  # 执行删除
                    deleted = "DELETE 1" in result  # 记录是否有行被删除

                    if deleted:  # 如果删除了依赖
                        # 检查任务是否变为就绪状态  # 状态自动更新
                        await self._update_task_status_based_on_dependencies(conn, task_id)  # 检查依赖状态

                    return deleted  # 返回删除结果
        except Exception as e:  # 捕获异常
            logger.error(f"[UserTaskStore] 移除依赖失败: {e}")  # 记录错误
            return False  # 返回失败

    async def _update_task_status_based_on_dependencies(self, conn, task_id: str):  # 根据依赖更新状态方法（内部）
        """  # 方法文档字符串
        根据依赖状态更新任务状态  # 方法功能

        P0-015: 使用 TERMINAL_STATUSES 定义终态  # 版本注释
        终态（completed/failed/cancelled/archived）都视为"已完成"，可解除依赖阻塞。  # 终态说明
        """  # 文档字符串结束
        # 检查是否有未完成的阻塞依赖  # 依赖检查
        # P0-015: NOT IN 对应 TERMINAL_STATUSES = ('completed', 'failed', 'cancelled', 'archived')
        pending_deps = await conn.fetchval('''
            SELECT COUNT(*) FROM task_dependencies d
            JOIN user_tasks t ON d.depends_on_task_id = t.id
            WHERE d.task_id = $1 AND d.dependency_type = 'blocks'
            AND t.status NOT IN ('completed', 'failed', 'cancelled', 'archived')
        ''', task_id)  # 查询未完成的阻塞依赖数量

        # 获取当前任务状态  # 状态检查
        current_status = await conn.fetchval(
            'SELECT status FROM user_tasks WHERE id = $1', task_id
        )  # 查询当前状态

        if current_status:  # 如果任务存在
            if pending_deps == 0 and current_status == TaskStatus.PENDING:  # 无依赖且状态为pending
                # 所有依赖已完成，任务变为就绪  # 状态变更
                await conn.execute('''
                    UPDATE user_tasks SET status = 'ready', updated_at = $1
                    WHERE id = $2
                ''', self._now(), task_id)  # 更新为ready状态
            elif pending_deps > 0 and current_status == TaskStatus.READY:  # 有依赖且状态为ready
                # 有新依赖，任务回到等待  # 状态变更
                await conn.execute('''
                    UPDATE user_tasks SET status = 'pending', updated_at = $1
                    WHERE id = $2
                ''', self._now(), task_id)  # 更新为pending状态

    async def get_dependencies(self, task_id: str) -> list[dict]:  # 获取依赖方法
        """  # 方法文档字符串
        获取任务的所有依赖  # 方法功能

        Args:  # 参数说明
            task_id: 任务ID  # 参数

        Returns:  # 返回值说明
            依赖任务列表  # 返回类型
        """  # 文档字符串结束
        await self._ensure_tables()
        pool = await AsyncPostgresPool.get_pool()
        try:  # 异常处理
            rows = await pool.fetch('''
                SELECT t.id, t.title, t.status, t.priority, d.dependency_type
                FROM task_dependencies d
                JOIN user_tasks t ON d.depends_on_task_id = t.id
                WHERE d.task_id = $1
            ''', task_id)  # 查询依赖

            results = []  # 结果列表
            for row in rows:  # 遍历结果
                results.append({  # 构建依赖字典
                    "id": row["id"],  # 任务ID
                    "title": row["title"],  # 标题
                    "status": row["status"],  # 状态
                    "priority": row["priority"],  # 优先级
                    "dependency_type": row["dependency_type"]  # 依赖类型
                })
            return results  # 返回列表
        except Exception as e:  # 捕获异常
            logger.error(f"[UserTaskStore] 获取依赖失败: {e}")  # 记录错误
            return []  # 返回空列表

    async def get_dependents(self, task_id: str) -> list[dict]:  # 获取被依赖方法
        """  # 方法文档字符串
        获取依赖于该任务的所有任务  # 方法功能

        Args:  # 参数说明
            task_id: 任务ID  # 参数

        Returns:  # 返回值说明
            依赖该任务的任务列表  # 返回类型
        """  # 文档字符串结束
        await self._ensure_tables()
        pool = await AsyncPostgresPool.get_pool()
        try:  # 异常处理
            rows = await pool.fetch('''
                SELECT t.id, t.title, t.status, t.priority, d.dependency_type
                FROM task_dependencies d
                JOIN user_tasks t ON d.task_id = t.id
                WHERE d.depends_on_task_id = $1
            ''', task_id)  # 查询被依赖

            results = []  # 结果列表
            for row in rows:  # 遍历结果
                results.append({  # 构建依赖字典
                    "id": row["id"],  # 任务ID
                    "title": row["title"],  # 标题
                    "status": row["status"],  # 状态
                    "priority": row["priority"],  # 优先级
                    "dependency_type": row["dependency_type"]  # 依赖类型
                })
            return results  # 返回列表
        except Exception as e:  # 捕获异常
            logger.error(f"[UserTaskStore] 获取依赖者失败: {e}")  # 记录错误
            return []  # 返回空列表

    async def check_circular_dependency(self, task_id: str, depends_on: str) -> bool:  # 检查循环依赖方法
        """  # 方法文档字符串
        检查是否会形成循环依赖  # 方法功能

        使用DFS遍历依赖图，检测是否存在从 depends_on 到 task_id 的路径  # 算法说明

        Args:  # 参数说明
            task_id: 依赖方任务ID  # 参数1
            depends_on: 被依赖方任务ID  # 参数2

        Returns:  # 返回值说明
            是否会形成循环依赖  # 返回类型
        """  # 文档字符串结束
        await self._ensure_tables()
        if task_id == depends_on:  # 自己依赖自己
            return True  # 循环依赖

        pool = await AsyncPostgresPool.get_pool()
        try:  # 异常处理
            # 使用BFS检测  # 广度优先搜索
            visited: set[str] = set()  # 已访问集合
            queue = [depends_on]  # 队列初始化为被依赖任务

            while queue:  # 队列不为空
                current = queue.pop(0)  # 出队
                if current == task_id:  # 找到回到原任务的路径
                    return True  # 存在循环依赖

                if current in visited:  # 已访问过
                    continue  # 跳过
                visited.add(current)  # 标记为已访问

                # 获取 current 的所有依赖  # 查找下一层
                rows = await pool.fetch('''
                    SELECT depends_on_task_id FROM task_dependencies
                    WHERE task_id = $1
                ''', current)  # 查询current的依赖

                for row in rows:  # 遍历依赖
                    dep_id = row["depends_on_task_id"]  # 获取依赖ID
                    if dep_id not in visited:  # 未访问过
                        queue.append(dep_id)  # 入队

            return False  # 无循环依赖
        except Exception as e:  # 捕获异常
            logger.error(f"[UserTaskStore] 循环依赖检测失败: {e}")  # 记录错误
            return True  # 出错时保守处理，假设会循环

    async def get_ready_tasks(self) -> list[dict]:  # 获取就绪任务方法
        """  # 方法文档字符串
        获取所有"就绪"的任务（依赖已完成）  # 方法功能

        Returns:  # 返回值说明
            就绪状态的任务列表  # 返回类型
        """  # 文档字符串结束
        await self._ensure_tables()
        pool = await AsyncPostgresPool.get_pool()
        try:  # 异常处理
            rows = await pool.fetch('''
                SELECT id, user_id, title, description, status, priority,
                       task_type, parent_id, memory_ids, created_at, updated_at,
                       started_at, completed_at, deadline, retry_count, max_retries,
                       result, error, metadata, version, is_compressed, compressed_summary
                FROM user_tasks
                WHERE user_id = $1 AND status = 'ready'
                ORDER BY priority ASC, created_at ASC
            ''', self.user_id)  # 查询就绪任务，按优先级和创建时间排序

            results = []  # 结果列表
            for row in rows:  # 遍历结果
                results.append(self._row_to_dict(row))  # 转换为字典
            return results  # 返回列表
        except Exception as e:  # 捕获异常
            logger.error(f"[UserTaskStore] 获取就绪任务失败: {e}")  # 记录错误
            return []  # 返回空列表

    async def get_task_history(self, task_id: str) -> list[dict]:  # 获取任务历史方法
        """  # 方法文档字符串
        获取任务变更历史  # 方法功能

        Args:  # 参数说明
            task_id: 任务ID  # 参数

        Returns:  # 返回值说明
            变更历史列表  # 返回类型
        """  # 文档字符串结束
        await self._ensure_tables()
        pool = await AsyncPostgresPool.get_pool()
        try:  # 异常处理
            rows = await pool.fetch('''
                SELECT id, field_name, old_value, new_value, changed_at, changed_by, version
                FROM task_history
                WHERE task_id = $1
                ORDER BY changed_at DESC
            ''', task_id)  # 查询历史，按时间降序

            results = []  # 结果列表
            for row in rows:  # 遍历结果
                results.append({  # 构建历史字典
                    "id": row["id"],  # 历史ID
                    "field_name": row["field_name"],  # 字段名
                    "old_value": json.loads(row["old_value"]) if row["old_value"] else None,  # 反序列化旧值
                    "new_value": json.loads(row["new_value"]) if row["new_value"] else None,  # 反序列化新值
                    "changed_at": row["changed_at"],  # 变更时间
                    "changed_by": row["changed_by"],  # 变更者
                    "version": row["version"]  # 版本号
                })
            return results  # 返回列表
        except Exception as e:  # 捕获异常
            logger.error(f"[UserTaskStore] 获取任务历史失败: {e}")  # 记录错误
            return []  # 返回空列表

    async def get_task_at_version(self, task_id: str, version: int) -> dict | None:  # 获取特定版本任务方法
        """  # 方法文档字符串
        获取任务特定版本的快照  # 方法功能

        通过回放历史记录还原特定版本的状态  # 实现说明

        Args:  # 参数说明
            task_id: 任务ID  # 参数1
            version: 版本号  # 参数2

        Returns:  # 返回值说明
            该版本的任务状态，或 None  # 返回类型
        """  # 文档字符串结束
        await self._ensure_tables()
        pool = await AsyncPostgresPool.get_pool()
        try:  # 异常处理
            async with pool.acquire() as conn:  # 获取连接
                # 获取创建记录  # 初始状态
                create_record = await conn.fetchrow('''
                    SELECT new_value FROM task_history
                    WHERE task_id = $1 AND field_name = 'created'
                ''', task_id)  # 查询创建记录

                if not create_record:  # 没有创建记录
                    return None  # 返回None

                # 初始状态  # 解析创建值
                task_state = create_record["new_value"]  # 获取创建时的值
                if task_state:  # 有值
                    task_state = json.loads(task_state)  # 反序列化
                else:  # 没有值，回退到当前任务
                    # 如果没有创建记录，获取当前任务  # 回退方案
                    row = await conn.fetchrow('SELECT * FROM user_tasks WHERE id = $1', task_id)  # 查询当前任务
                    if not row:  # 任务不存在
                        return None  # 返回None
                    task_state = self._row_to_dict(row)  # 转换为字典

                # 获取该版本之前的所有变更  # 回放历史
                rows = await conn.fetch('''
                    SELECT field_name, new_value FROM task_history
                    WHERE task_id = $1 AND version <= $2 AND field_name != 'created'
                    ORDER BY version ASC, changed_at ASC
                ''', task_id, version)  # 查询历史变更

                for row in rows:  # 遍历变更
                    field_name = row["field_name"]  # 获取字段名
                    new_value = json.loads(row["new_value"]) if row["new_value"] else None  # 反序列化新值
                    task_state[field_name] = new_value  # 应用变更

                task_state['version'] = version  # 设置版本号
                return task_state  # 返回状态
        except Exception as e:  # 捕获异常
            logger.error(f"[UserTaskStore] 获取历史版本失败: {e}")  # 记录错误
            return None  # 返回None

    async def link_memory(self, task_id: str, memory_id: str, link_type: str = "reference") -> bool:  # 关联记忆方法
        """  # 方法文档字符串
        关联任务与记忆  # 方法功能

        Args:  # 参数说明
            task_id: 任务ID  # 参数1
            memory_id: 记忆ID  # 参数2
            link_type: 关联类型，默认 'reference'  # 参数3

        Returns:  # 返回值说明
            是否关联成功  # 返回类型
        """  # 文档字符串结束
        await self._ensure_tables()
        pool = await AsyncPostgresPool.get_pool()
        try:  # 异常处理
            async with pool.acquire() as conn, conn.transaction():  # 获取连接和事务
                    link_id = self._generate_id()  # 生成关联ID
                    # PostgreSQL UPSERT using ON CONFLICT  # UPSERT操作
                    await conn.execute('''
                        INSERT INTO task_memory_links (id, task_id, memory_id, link_type)
                        VALUES ($1, $2, $3, $4)
                        ON CONFLICT (task_id, memory_id) DO UPDATE SET
                            link_type = EXCLUDED.link_type,
                            created_at = CURRENT_TIMESTAMP
                    ''', link_id, task_id, memory_id, link_type)  # 执行插入或更新
                    return True  # 返回成功
        except Exception as e:  # 捕获异常
            logger.error(f"[UserTaskStore] 关联记忆失败: {e}")  # 记录错误
            return False  # 返回失败

    async def unlink_memory(self, task_id: str, memory_id: str) -> bool:  # 解除记忆关联方法
        """  # 方法文档字符串
        解除任务与记忆的关联  # 方法功能

        Args:  # 参数说明
            task_id: 任务ID  # 参数1
            memory_id: 记忆ID  # 参数2

        Returns:  # 返回值说明
            是否解除成功  # 返回类型
        """  # 文档字符串结束
        await self._ensure_tables()
        pool = await AsyncPostgresPool.get_pool()
        try:  # 异常处理
            async with pool.acquire() as conn, conn.transaction():  # 获取连接和事务
                    result = await conn.execute('''
                        DELETE FROM task_memory_links
                        WHERE task_id = $1 AND memory_id = $2
                    ''', task_id, memory_id)  # 执行删除
                    return "DELETE 1" in result  # 返回是否有行被删除
        except Exception as e:  # 捕获异常
            logger.error(f"[UserTaskStore] 解除记忆关联失败: {e}")  # 记录错误
            return False  # 返回失败

    async def get_linked_memories(self, task_id: str) -> list[dict]:  # 获取关联记忆方法
        """  # 方法文档字符串
        获取任务关联的所有记忆  # 方法功能

        Args:  # 参数说明
            task_id: 任务ID  # 参数

        Returns:  # 返回值说明
            关联的记忆列表  # 返回类型
        """  # 文档字符串结束
        await self._ensure_tables()
        pool = await AsyncPostgresPool.get_pool()
        try:  # 异常处理
            rows = await pool.fetch('''
                SELECT memory_id, link_type, created_at
                FROM task_memory_links
                WHERE task_id = $1
            ''', task_id)  # 查询关联

            results = []  # 结果列表
            for row in rows:  # 遍历结果
                results.append({  # 构建关联字典
                    "memory_id": row["memory_id"],  # 记忆ID
                    "link_type": row["link_type"],  # 关联类型
                    "linked_at": row["created_at"]  # 关联时间
                })
            return results  # 返回列表
        except Exception as e:  # 捕获异常
            logger.error(f"[UserTaskStore] 获取关联记忆失败: {e}")  # 记录错误
            return []  # 返回空列表

    async def list_tasks(  # 列出任务方法
        self,
        status: str | None = None,
        task_type: str | None = None,
        parent_id: str | None = None,
        limit: int = 100,
        offset: int = 0
    ) -> list[dict]:
        """  # 方法文档字符串
        列出任务，支持过滤和分页  # 方法功能

        Args:  # 参数说明
            status: 按状态过滤  # 参数1
            task_type: 按任务类型过滤  # 参数2
            parent_id: 按父任务ID过滤  # 参数3
            limit: 返回数量限制，默认 100  # 参数4
            offset: 分页偏移量，默认 0  # 参数5

        Returns:  # 返回值说明
            任务列表  # 返回类型
        """  # 文档字符串结束
        await self._ensure_tables()
        pool = await AsyncPostgresPool.get_pool()
        try:  # 异常处理
            # 基础查询
            query = '''
                SELECT id, user_id, title, description, status, priority,
                       task_type, parent_id, memory_ids, created_at, updated_at,
                       started_at, completed_at, deadline, retry_count, max_retries,
                       result, error, metadata, version, is_compressed, compressed_summary
                FROM user_tasks
                WHERE user_id = $1
            '''
            params = [self.user_id]  # 基础参数
            param_idx = 1

            if status:  # 如果有状态过滤
                param_idx += 1
                query += f" AND status = ${param_idx}"  # 添加状态条件
                params.append(status)  # 添加状态值

            if task_type:  # 如果有类型过滤
                param_idx += 1
                query += f" AND task_type = ${param_idx}"  # 添加类型条件
                params.append(task_type)  # 添加类型值

            if parent_id is not None:  # 如果有父任务过滤
                if parent_id == "":  # 空字符串表示根任务
                    # 查找根任务（没有父任务）  # 根任务过滤
                    query += " AND parent_id IS NULL"  # 添加NULL条件
                else:  # 指定父任务
                    param_idx += 1
                    query += f" AND parent_id = ${param_idx}"  # 添加父任务条件
                    params.append(parent_id)  # 添加父任务值

            param_idx += 1
            query += f" ORDER BY priority ASC, created_at DESC LIMIT ${param_idx} OFFSET ${param_idx + 1}"  # 排序和分页
            params.extend([limit, offset])  # 添加分页参数

            rows = await pool.fetch(query, *params)  # 执行查询

            results = []  # 结果列表
            for row in rows:  # 遍历结果
                results.append(self._row_to_dict(row))  # 转换为字典
            return results  # 返回列表
        except Exception as e:  # 捕获异常
            logger.error(f"[UserTaskStore] 列出任务失败: {e}")  # 记录错误
            return []  # 返回空列表

    async def get_task_stats(self) -> dict:  # 获取任务统计方法
        """  # 方法文档字符串
        获取用户任务统计信息  # 方法功能

        Returns:  # 返回值说明
            统计信息字典  # 返回类型
        """  # 文档字符串结束
        await self._ensure_tables()
        pool = await AsyncPostgresPool.get_pool()
        try:  # 异常处理
            stats = {"user_id": self.user_id}  # 基础统计

            # 各状态数量  # 状态统计
            for status in [TaskStatus.PENDING, TaskStatus.READY, TaskStatus.RUNNING,
                          TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED,
                          TaskStatus.ARCHIVED]:  # 遍历所有状态
                count = await pool.fetchval(
                    'SELECT COUNT(*) FROM user_tasks WHERE user_id = $1 AND status = $2',
                    self.user_id, status
                )
                stats[status] = count  # 保存数量

            # 总数  # 总数统计
            total = await pool.fetchval(
                'SELECT COUNT(*) FROM user_tasks WHERE user_id = $1', self.user_id
            )
            stats['total'] = total  # 保存总数

            # 今日创建 (PostgreSQL syntax)  # 今日统计
            created_today = await pool.fetchval('''
                SELECT COUNT(*) FROM user_tasks
                WHERE user_id = $1 AND DATE(created_at) = CURRENT_DATE
            ''', self.user_id)  # 查询今日创建
            stats['created_today'] = created_today  # 保存数量

            # 即将到期（24小时内）- 排除终态任务 (PostgreSQL syntax)
            # P0-015: NOT IN 对应 TERMINAL_STATUSES = ('completed', 'failed', 'cancelled', 'archived')
            due_soon = await pool.fetchval('''
                SELECT COUNT(*) FROM user_tasks
                WHERE user_id = $1 AND deadline IS NOT NULL
                AND deadline <= CURRENT_TIMESTAMP + INTERVAL '24 hours'
                AND status NOT IN ('completed', 'failed', 'cancelled', 'archived')
            ''', self.user_id)  # 查询即将到期
            stats['due_soon'] = due_soon  # 保存数量

            return stats  # 返回统计
        except Exception as e:  # 捕获异常
            logger.error(f"[UserTaskStore] 获取统计信息失败: {e}")  # 记录错误
            return {"user_id": self.user_id, "error": str(e)}  # 返回错误信息


class TaskStoreManager:  # 任务存储管理器类（单例）
    """  # 类文档字符串
    任务存储管理器 - 管理所有用户的任务存储  # 类功能概述
    提供用户隔离和统一接口（单例模式）  # 核心特性
    """  # 文档字符串结束

    _instance = None  # 单例实例

    def __new__(cls):  # 单例控制方法
        if cls._instance is None:  # 如果实例不存在
            cls._instance = super().__new__(cls)  # 创建实例
            cls._instance._initialized = False  # 标记未初始化
        return cls._instance  # 返回实例

    def __init__(self):  # 初始化方法
        if self._initialized:  # 如果已初始化
            return  # 直接返回
        self._initialized = True  # 标记已初始化

        self._stores: dict[str, UserTaskStore] = {}  # 用户存储字典
        self._lock = asyncio.Lock()  # 存储操作锁

        logger.info("[TaskStoreManager] 任务存储管理器初始化完成")  # 记录日志

    async def get_user_store(self, user_id: str) -> UserTaskStore:  # 获取用户存储方法
        """  # 方法文档字符串
        获取或创建用户任务存储  # 方法功能

        Args:  # 参数说明
            user_id: 用户唯一标识  # 参数

        Returns:  # 返回值说明
            用户任务存储实例  # 返回类型
        """  # 文档字符串结束
        async with self._lock:  # 获取锁
            if user_id not in self._stores:  # 如果用户存储不存在
                self._stores[user_id] = UserTaskStore(user_id)  # 创建新存储
            return self._stores[user_id]  # 返回用户存储

    async def create_task(self, user_id: str, task_data: dict) -> str:  # 创建任务方法
        """  # 方法文档字符串
        为用户创建任务  # 方法功能

        Args:  # 参数说明
            user_id: 用户ID  # 参数1
            task_data: 任务数据  # 参数2

        Returns:  # 返回值说明
            任务ID  # 返回类型
        """  # 文档字符串结束
        store = await self.get_user_store(user_id)  # 获取用户存储
        return await store.create_task(task_data)  # 创建任务

    async def get_task(self, user_id: str, task_id: str) -> dict | None:  # 获取任务方法
        """  # 方法文档字符串
        获取用户任务详情  # 方法功能

        Args:  # 参数说明
            user_id: 用户ID  # 参数1
            task_id: 任务ID  # 参数2

        Returns:  # 返回值说明
            任务数据或 None  # 返回类型
        """  # 文档字符串结束
        store = await self.get_user_store(user_id)  # 获取用户存储
        return await store.get_task(task_id)  # 获取任务

    async def update_task(self, user_id: str, task_id: str, updates: dict) -> bool:  # 更新任务方法
        """  # 方法文档字符串
        更新用户任务  # 方法功能

        Args:  # 参数说明
            user_id: 用户ID  # 参数1
            task_id: 任务ID  # 参数2
            updates: 更新内容  # 参数3

        Returns:  # 返回值说明
            是否成功  # 返回类型
        """  # 文档字符串结束
        store = await self.get_user_store(user_id)  # 获取用户存储
        return await store.update_task(task_id, updates)  # 更新任务

    async def delete_task(self, user_id: str, task_id: str, soft_delete: bool = False) -> bool:  # 删除任务方法
        """  # 方法文档字符串
        删除用户任务  # 方法功能

        Args:  # 参数说明
            user_id: 用户ID  # 参数1
            task_id: 任务ID  # 参数2
            soft_delete: 是否软删除  # 参数3

        Returns:  # 返回值说明
            是否成功  # 返回类型
        """  # 文档字符串结束
        store = await self.get_user_store(user_id)  # 获取用户存储
        return await store.delete_task(task_id, soft_delete)  # 删除任务

    async def list_tasks(self, user_id: str, **kwargs) -> list[dict]:  # 列出任务方法
        """  # 方法文档字符串
        列出用户任务  # 方法功能

        Args:  # 参数说明
            user_id: 用户ID  # 参数1
            **kwargs: 过滤参数  # 参数2

        Returns:  # 返回值说明
            任务列表  # 返回类型
        """  # 文档字符串结束
        store = await self.get_user_store(user_id)  # 获取用户存储
        return await store.list_tasks(**kwargs)  # 列出任务

    async def get_stats(self, user_id: str) -> dict:  # 获取统计方法
        """  # 方法文档字符串
        获取用户任务统计  # 方法功能

        Args:  # 参数说明
            user_id: 用户ID  # 参数

        Returns:  # 返回值说明
            统计信息  # 返回类型
        """  # 文档字符串结束
        store = await self.get_user_store(user_id)  # 获取用户存储
        return await store.get_task_stats()  # 获取统计


# 全局实例  # 模块级全局变量
try:  # 尝试初始化
    task_store_manager = TaskStoreManager()  # 创建任务存储管理器实例
    print("【成功】 Task store system initialized successfully")  # 打印成功信息
except Exception as e:  # 捕获异常
    print(f"[ERROR] Failed to initialize task store system: {e}")  # 打印错误信息
    task_store_manager = None  # 设置为空

# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase V5 系统的"用户任务存储层"，属于数据访问层（DAO）。
# 使用 PostgreSQL 数据库存储任务数据，提供CRUD操作和事务支持。
#
# 【核心功能】
# 1. 任务数据持久化：创建、查询、更新、删除任务
# 2. 依赖关系管理：添加、移除、查询任务依赖，循环依赖检测
# 3. 事务支持：提供transaction上下文管理器保证数据一致性
# 4. 乐观锁：使用version字段防止并发更新冲突
# 5. 变更历史：自动记录任务字段变更历史
# 6. 任务-记忆关联：支持任务与记忆的多对多关联
#
# 【数据库表结构】
# - user_tasks: 任务主表，存储任务基本信息
# - task_dependencies: 依赖关系表，存储任务间依赖
# - task_history: 变更历史表，记录所有字段变更
# - task_memory_links: 任务-记忆关联表
#
# 【关联文件】
# - core/user_task_manager.py: 业务层，调用本层接口
# - core/memory.py: 记忆系统，提供数据库连接池
# - core/task_status.py: 统一任务状态枚举
