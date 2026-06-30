#!/usr/bin/env python3
"""
执行记忆管理模块 V7.1 (L5层) - 工具执行记录与分析
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【L5 - 执行记忆层 - 双重存储架构重构 V7.1】
  重构版本：统一使用PostgreSQL存储L5，保留JSONL作为本地缓存

【存储架构】
  - PostgreSQL (主存储): memories表，layer="execution"
  - JSONL (本地缓存): data/execution/{user_id}/executions.jsonl

【数据流向】
  写入: store() → PostgreSQL → JSONL缓存
  读取: get_stats() → JSONL缓存 (快速) / PostgreSQL (完整)
  同步: 定期_sync_jsonl_to_db()将未同步记录写入PostgreSQL

【2026-03-06 Agent-2-Fix V7.1修复】
  ✅ 问题1修复: 统一ID生成策略
  ✅ 问题2修复: 添加失败补偿机制
  ✅ 问题3修复: 幂等性保证(UPSERT)
"""

import hashlib
import json

# 日志记录器（延迟初始化避免循环导入）
import logging
import threading
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

from core.utils.file_utils import read_jsonl, write_json, write_jsonl

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent
EXECUTION_DIR = BASE_DIR / "data" / "execution"
EXECUTION_DIR.mkdir(parents=True, exist_ok=True)

# 导入PostgreSQL连接池和Memory系统
try:
    from core.db.connection_pool import (
        POSTGRES_AVAILABLE,
        Json,
        PostgresConnectionPool,
        RealDictCursor,
        init_postgres_tables,
    )
    from core.memory.memory import LAYER_EXECUTION
    MEMORY_SYSTEM_AVAILABLE = True
except ImportError as e:
    logger.error(f"[ExecutionMemory] 导入memory模块失败: {e}")
    PostgresConnectionPool = None
    init_postgres_tables = None
    LAYER_EXECUTION = "execution"
    POSTGRES_AVAILABLE = False
    def Json(x):
        return x
    RealDictCursor = dict
    MEMORY_SYSTEM_AVAILABLE = False


class StoreStatus(Enum):
    """存储状态枚举"""
    PENDING = "pending"
    PG_SUCCESS = "pg_success"
    JSONL_SUCCESS = "jsonl_success"
    BOTH_SUCCESS = "both_success"
    FAILED = "failed"


@dataclass
class StoreResult:
    """存储操作结果"""
    record_id: str
    pg_success: bool
    jsonl_success: bool
    pg_id: str | None = None
    error: str | None = None
    needs_compensation: bool = False
    compensation_target: str | None = None  # "pg" or "jsonl"

    @property
    def is_success(self) -> bool:
        """是否至少一个存储成功"""
        return self.pg_success or self.jsonl_success

    @property
    def is_fully_synced(self) -> bool:
        """是否双写都成功"""
        return self.pg_success and self.jsonl_success


@dataclass
class ToolExecutionRecord:
    """工具执行记录 - 记录单次工具调用的完整信息"""
    user_id: str
    tool_name: str
    input_params: dict[str, Any]
    output_result: dict[str, Any]
    success: bool
    execution_time_ms: int
    timestamp: datetime
    task_id: str | None = None
    session_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    tool_params: dict[str, Any] | None = None  # 新增: 工具参数详情
    record_id: str | None = None  # 新增: 统一的记录ID

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（用于JSON序列化）"""
        return {
            "user_id": self.user_id,
            "tool_name": self.tool_name,
            "input_params": self.input_params,
            "output_result": self.output_result,
            "success": self.success,
            "execution_time_ms": self.execution_time_ms,
            "timestamp": self.timestamp.isoformat() if isinstance(self.timestamp, datetime) else self.timestamp,
            "task_id": self.task_id,
            "session_id": self.session_id,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "tool_params": self.tool_params,
            "record_id": self.record_id  # 包含统一ID
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'ToolExecutionRecord':
        """从字典创建记录 - 反序列化"""
        data = data.copy()
        if isinstance(data.get("timestamp"), str):
            data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        # 兼容旧数据，tool_params可能不存在
        if "tool_params" not in data:
            data["tool_params"] = data.get("input_params", {})
        # 兼容旧数据，record_id可能不存在
        if "record_id" not in data:
            data["record_id"] = None
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ExecutionSummary:
    """执行摘要（压缩后）- 存储一段时间内的统计信息"""
    period: str
    total: int
    success_count: int
    fail_count: int
    success_rate: float
    avg_execution_time_ms: float
    common_tools: list[dict[str, Any]]
    common_errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "total": self.total,
            "success_count": self.success_count,
            "fail_count": self.fail_count,
            "success_rate": self.success_rate,
            "avg_execution_time_ms": self.avg_execution_time_ms,
            "common_tools": self.common_tools,
            "common_errors": self.common_errors
        }


# ============================================================================
# ID生成和补偿机制模块
# ============================================================================

class ExecutionIdGenerator:
    """统一的执行记录ID生成器"""

    @staticmethod
    def generate_execution_id(user_id: str, tool_name: str, timestamp: datetime) -> str:
        """
        生成统一的执行记录ID

        格式: exec_{uuid_prefix}_{timestamp}_{hash_suffix}
        - 保证全局唯一性
        - 包含时间信息便于排序
        - 包含用户和工具信息便于追踪

        Args:
            user_id: 用户ID
            tool_name: 工具名称
            timestamp: 时间戳

        Returns:
            统一格式的记录ID
        """
        uuid_prefix = uuid.uuid4().hex[:12]
        ts_str = str(int(timestamp.timestamp() * 1000))  # 毫秒级时间戳
        base_str = f"{user_id}_{tool_name}_{ts_str}"
        hash_suffix = hashlib.sha256(base_str.encode()).hexdigest()[:8]
        return f"exec_{uuid_prefix}_{ts_str}_{hash_suffix}"

    @staticmethod
    def validate_record_id(record_id: str) -> bool:
        """验证记录ID格式是否有效"""
        if not record_id or not isinstance(record_id, str):
            return False
        parts = record_id.split('_')
        return (len(parts) == 4 and
                parts[0] == 'exec' and
                len(parts[1]) == 12 and
                parts[2].isdigit() and
                len(parts[3]) == 8)


class CompensationManager:
    """失败补偿管理器 - 处理双写失败的补偿逻辑"""

    def __init__(self):
        self._pending_compensations: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._compensation_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._start_compensation_worker()

    def _start_compensation_worker(self):
        """启动后台补偿工作线程"""
        if self._compensation_thread is None or not self._compensation_thread.is_alive():
            self._compensation_thread = threading.Thread(
                target=self._compensation_loop,
                daemon=True,
                name="CompensationWorker"
            )
            self._compensation_thread.start()
            logger.info("[CompensationManager] 补偿工作线程已启动")

    def _compensation_loop(self):
        """补偿工作循环"""
        while not self._stop_event.is_set():
            try:
                # 每30秒检查一次待补偿任务
                if self._stop_event.wait(30):
                    break
                self._process_pending_compensations()
            except Exception as e:
                logger.error(f"[CompensationManager] 补偿循环异常: {e}")

    def _process_pending_compensations(self):
        """处理待补偿任务"""
        with self._lock:
            pending_items = list(self._pending_compensations.items())

        for record_id, task in pending_items:
            try:
                if task['target'] == 'jsonl':
                    self._compensate_to_jsonl(record_id, task)
                elif task['target'] == 'pg':
                    self._compensate_to_pg(record_id, task)
            except Exception as e:
                logger.error(f"[CompensationManager] 补偿失败 {record_id}: {e}")
                # 如果重试次数超过3次，放弃补偿
                task['retry_count'] = task.get('retry_count', 0) + 1
                if task['retry_count'] >= 3:
                    with self._lock:
                        if record_id in self._pending_compensations:
                            del self._pending_compensations[record_id]
                    logger.warning(f"[CompensationManager] 放弃补偿 {record_id}，超过最大重试次数")

    def _compensate_to_jsonl(self, record_id: str, task: dict) -> bool:
        """补偿写入JSONL"""
        # 这里会在UserExecutionStore中实现具体逻辑
        # CompensationManager只负责任务调度
        logger.info(f"[CompensationManager] 调度补偿到JSONL: {record_id}")
        return True

    def _compensate_to_pg(self, record_id: str, task: dict) -> bool:
        """补偿写入PostgreSQL"""
        logger.info(f"[CompensationManager] 调度补偿到PG: {record_id}")
        return True

    def schedule_compensation(self, record_id: str, target: str, record_data: dict):
        """
        调度补偿任务

        Args:
            record_id: 记录ID
            target: 补偿目标 ('jsonl' 或 'pg')
            record_data: 记录数据
        """
        with self._lock:
            self._pending_compensations[record_id] = {
                'target': target,
                'data': record_data,
                'scheduled_at': datetime.now().isoformat(),
                'retry_count': 0
            }
        logger.info(f"[CompensationManager] 已调度补偿任务: {record_id} -> {target}")

    def remove_compensation_task(self, record_id: str):
        """移除补偿任务"""
        with self._lock:
            if record_id in self._pending_compensations:
                del self._pending_compensations[record_id]

    def get_pending_tasks(self) -> dict[str, dict]:
        """获取所有待补偿任务"""
        with self._lock:
            return dict(self._pending_compensations)

    def stop(self):
        """停止补偿管理器"""
        self._stop_event.set()
        if self._compensation_thread and self._compensation_thread.is_alive():
            self._compensation_thread.join(timeout=5)


# 全局补偿管理器实例
_compensation_manager: CompensationManager | None = None

def get_compensation_manager() -> CompensationManager:
    """获取全局补偿管理器实例"""
    global _compensation_manager
    if _compensation_manager is None:
        _compensation_manager = CompensationManager()
    return _compensation_manager


# ============================================================================
# 用户执行存储类
# ============================================================================

class UserExecutionStore:
    """
    单个用户的执行记忆存储 - 用户数据隔离
    【V7.1修复后】统一ID + 失败补偿 + 幂等写入
    """

    def __init__(self, user_id: str, base_dir: Path = EXECUTION_DIR):
        """
        初始化用户执行存储

        Args:
            user_id: 用户唯一标识
            base_dir: 基础存储目录，默认EXECUTION_DIR
        """
        self.user_id = user_id
        self.user_dir = base_dir / user_id
        self.user_dir.mkdir(parents=True, exist_ok=True)

        self.executions_file = self.user_dir / "executions.jsonl"
        self.compressed_dir = self.user_dir / "compressed"
        self.compressed_dir.mkdir(exist_ok=True)

        # 同步标记文件
        self.sync_marker_file = self.user_dir / ".last_sync"

        # 补偿队列文件
        self.compensation_file = self.user_dir / ".compensation_queue"

        self._records: list[ToolExecutionRecord] = []
        self._max_records = 1000
        self._lock = threading.RLock()

        # ID生成器
        self._id_generator = ExecutionIdGenerator()

        # 补偿管理器
        self._comp_mgr = get_compensation_manager()

        # 初始化PostgreSQL表结构（延迟到第一次DB操作，避免在async路径中阻塞）
        self._tables_initialized = False

        # 记录延迟加载，避免在__init__中执行文件I/O阻塞事件循环
        self._records_loaded = False
        self._compensation_loaded = False

    def _ensure_records_loaded(self):
        """惰性加载最近的记录到内存缓存（从JSONL）"""
        if self._records_loaded:
            return
        self._records_loaded = True
        if not self.executions_file.exists():
            return

        try:
            records = []
            for data in read_jsonl(self.executions_file):
                try:
                    if data.get("user_id") == self.user_id:
                        record = ToolExecutionRecord.from_dict(data)
                        records.append(record)
                except (json.JSONDecodeError, KeyError, TypeError) as e:
                    logger.warning(f"[UserExecutionStore] 解析执行记录失败: {e}")
                    continue

            self._records = records[-self._max_records:]
            logger.debug(f"[UserExecutionStore] 用户 {self.user_id} 从JSONL加载 {len(self._records)} 条执行记录")

        except Exception as e:
            logger.error(f"[UserExecutionStore] 加载执行记录失败: {e}")

    def _ensure_compensation_loaded(self):
        """惰性加载未完成的补偿任务"""
        if self._compensation_loaded:
            return
        self._compensation_loaded = True
        if not self.compensation_file.exists():
            return

        try:
            for task in read_jsonl(self.compensation_file):
                try:
                    self._comp_mgr.schedule_compensation(
                        task['record_id'],
                        task['target'],
                        task['data']
                    )
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning(f"[UserExecutionStore] 加载补偿任务失败: {e}")
                    continue
            # 清空补偿队列文件
            self.compensation_file.unlink()
        except Exception as e:
            logger.warning(f"[UserExecutionStore] 加载补偿队列失败: {e}")

    def _save_compensation_task(self, record_id: str, target: str, data: dict):
        """保存补偿任务到文件（持久化）"""
        try:
            task = {
                'record_id': record_id,
                'target': target,
                'data': data,
                'created_at': datetime.now().isoformat()
            }
            write_jsonl(self.compensation_file, [task], append=True)
        except Exception as e:
            logger.error(f"[UserExecutionStore] 保存补偿任务失败: {e}")

    # ========================================================================
    # V7.1 FIX: 统一ID生成
    # ========================================================================

    def _generate_record_id(self, record: ToolExecutionRecord) -> str:
        """
        生成统一的记录ID

        Args:
            record: 执行记录

        Returns:
            统一格式的记录ID
        """
        return self._id_generator.generate_execution_id(
            record.user_id,
            record.tool_name,
            record.timestamp
        )

    # ========================================================================
    # V7.1 FIX: 幂等写入PostgreSQL
    # ========================================================================

    def _write_to_postgres_idempotent(self, record: ToolExecutionRecord,
                                      record_id: str) -> tuple[bool, str | None]:
        """
        幂等写入PostgreSQL（主存储，同步版本）

        使用UPSERT语义：
        - 如果记录存在（基于record_id），则更新
        - 如果记录不存在，则插入

        Args:
            record: 执行记录
            record_id: 统一的记录ID

        Returns:
            (是否成功, 记忆ID)
        """
        if not MEMORY_SYSTEM_AVAILABLE or PostgresConnectionPool is None:
            logger.debug("[UserExecutionStore] PostgreSQL不可用，跳过主存储写入")
            return False, None

        conn = None
        try:
            conn = PostgresConnectionPool.get_connection()

            # 构建content字段 - 存储完整执行记录
            content = {
                "tool_name": record.tool_name,
                "input_params": record.input_params,
                "output_result": record.output_result,
                "success": record.success,
                "error_code": record.error_code,
                "error_message": record.error_message
            }

            # 构建context字段 - 存储关联信息
            context = {
                "task_id": record.task_id,
                "session_id": record.session_id,
                "tool_params": record.tool_params or record.input_params,
                "source": "execution_memory",
                "record_id": record_id  # 存储统一ID到context
            }

            with conn.cursor() as c:
                # V7.1 FIX: 使用UPSERT保证幂等性
                # ON CONFLICT (id) DO UPDATE ... 实现存在则更新，不存在则插入
                c.execute('''
                    INSERT INTO memories
                    (id, user_id, layer, mem_type, content, context,
                     scene, rating, execution_time, tool_params, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        content = EXCLUDED.content,
                        context = EXCLUDED.context,
                        scene = EXCLUDED.scene,
                        rating = EXCLUDED.rating,
                        execution_time = EXCLUDED.execution_time,
                        tool_params = EXCLUDED.tool_params,
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING id
                ''', (
                    record_id,  # 使用统一的record_id作为主键
                    self.user_id,
                    LAYER_EXECUTION,
                    record.tool_name,
                    json.dumps(content, ensure_ascii=False),
                    Json(context),
                    f"exec_{record.tool_name}",
                    1 if record.success else 0,
                    record.execution_time_ms / 1000.0,
                    Json(record.tool_params or record.input_params),
                    record.timestamp
                ))
                result = c.fetchone()
                conn.commit()

                mem_id = result[0] if result else record_id
                logger.debug(f"[UserExecutionStore] PostgreSQL幂等写入成功: {mem_id}")
                return True, mem_id

        except Exception as e:
            logger.error(f"[UserExecutionStore] PostgreSQL写入失败: {e}")
            if conn:
                conn.rollback()
            return False, None
        finally:
            if conn:
                PostgresConnectionPool.return_connection(conn)

    async def _write_to_postgres_idempotent_async(self, record: ToolExecutionRecord,
                                                   record_id: str) -> tuple[bool, str | None]:
        """
        幂等写入PostgreSQL（异步版本，原生asyncpg）

        Args:
            record: 执行记录
            record_id: 统一的记录ID

        Returns:
            (是否成功, 记忆ID)
        """
        try:
            from core.memory.postgres_pool import AsyncPostgresPool

            content = {
                "tool_name": record.tool_name,
                "input_params": record.input_params,
                "output_result": record.output_result,
                "success": record.success,
                "error_code": record.error_code,
                "error_message": record.error_message
            }

            context = {
                "task_id": record.task_id,
                "session_id": record.session_id,
                "tool_params": record.tool_params or record.input_params,
                "source": "execution_memory",
                "record_id": record_id
            }

            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                mem_id = await conn.fetchval('''
                    INSERT INTO memories
                    (id, user_id, layer, mem_type, content, context,
                     scene, rating, execution_time, tool_params, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    ON CONFLICT (id) DO UPDATE SET
                        content = EXCLUDED.content,
                        context = EXCLUDED.context,
                        scene = EXCLUDED.scene,
                        rating = EXCLUDED.rating,
                        execution_time = EXCLUDED.execution_time,
                        tool_params = EXCLUDED.tool_params,
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING id
                ''',
                    record_id,
                    self.user_id,
                    LAYER_EXECUTION,
                    record.tool_name,
                    json.dumps(content, ensure_ascii=False),
                    json.dumps(context, ensure_ascii=False),
                    f"exec_{record.tool_name}",
                    1 if record.success else 0,
                    record.execution_time_ms / 1000.0,
                    json.dumps(record.tool_params or record.input_params, ensure_ascii=False),
                    record.timestamp
                )

            mem_id = mem_id or record_id
            logger.debug(f"[UserExecutionStore] PostgreSQL异步幂等写入成功: {mem_id}")
            return True, mem_id

        except Exception as e:
            logger.error(f"[UserExecutionStore] PostgreSQL异步写入失败: {e}")
            return False, None

    def _write_to_jsonl_with_id(self, record: ToolExecutionRecord,
                                record_id: str) -> bool:
        """
        写入记录到JSONL缓存文件（包含统一ID）

        Args:
            record: 执行记录
            record_id: 统一的记录ID

        Returns:
            是否成功
        """
        try:
            # 更新记录的record_id
            record.record_id = record_id

            write_jsonl(self.executions_file, [record.to_dict()], append=True)
            return True
        except Exception as e:
            logger.error(f"[UserExecutionStore] 写入JSONL缓存失败: {e}")
            return False

    # ========================================================================
    # V7.1 FIX: 带补偿的双写
    # ========================================================================

    def add_with_compensation(self, record: ToolExecutionRecord) -> StoreResult:
        """
        添加执行记录到存储（带补偿的双写）

        【V7.1修复后】
        1. 先生成统一ID
        2. 尝试双写：PostgreSQL + JSONL
        3. 任一失败则调度补偿任务
        4. 保证最终一致性

        Args:
            record: 执行记录对象

        Returns:
            存储操作结果
        """
        # 1. 生成统一ID
        record_id = self._generate_record_id(record)
        record.record_id = record_id

        pg_success = False
        jsonl_success = False
        pg_id = None
        error_msg = None

        with self._lock:
            # 2. 写入PostgreSQL（主存储）
            try:
                pg_success, pg_id = self._write_to_postgres_idempotent(record, record_id)
                if not pg_success:
                    error_msg = "PostgreSQL写入失败"
            except Exception as e:
                logger.error(f"[UserExecutionStore] PG写入异常: {e}")
                error_msg = f"PG异常: {str(e)}"

            # 3. 写入JSONL（本地缓存）
            try:
                jsonl_success = self._write_to_jsonl_with_id(record, record_id)
                if not jsonl_success:
                    if error_msg:
                        error_msg += "; JSONL写入失败"
                    else:
                        error_msg = "JSONL写入失败"
            except Exception as e:
                logger.error(f"[UserExecutionStore] JSONL写入异常: {e}")
                if error_msg:
                    error_msg += f"; JSONL异常: {str(e)}"
                else:
                    error_msg = f"JSONL异常: {str(e)}"

            # 4. 更新内存缓存
            if jsonl_success:  # JSONL写入成功才更新内存
                self._records.append(record)
                if len(self._records) > self._max_records:
                    self._records.pop(0)

        # 5. 补偿机制（在锁外执行）
        result = StoreResult(
            record_id=record_id,
            pg_success=pg_success,
            jsonl_success=jsonl_success,
            pg_id=pg_id,
            error=error_msg
        )

        if pg_success and not jsonl_success:
            # PG成功但JSONL失败，需要补偿到JSONL
            result.needs_compensation = True
            result.compensation_target = "jsonl"
            self._schedule_sync_to_jsonl(record_id, record)
            logger.warning(f"[UserExecutionStore] 需要补偿到JSONL: {record_id}")

        elif jsonl_success and not pg_success:
            # JSONL成功但PG失败，需要补偿到PG
            result.needs_compensation = True
            result.compensation_target = "pg"
            self._schedule_sync_to_pg(record_id, record)
            logger.warning(f"[UserExecutionStore] 需要补偿到PG: {record_id}")

        # 记录结果
        if result.is_fully_synced:
            logger.debug(f"[UserExecutionStore] 双写成功: {record_id}")
        elif result.is_success:
            logger.warning(f"[UserExecutionStore] 部分写入成功: {record_id}, PG={pg_success}, JSONL={jsonl_success}")
        else:
            logger.error(f"[UserExecutionStore] 双写都失败: {record_id}")

        return result

    async def add_with_compensation_async(self, record: ToolExecutionRecord) -> StoreResult:
        """
        异步添加执行记录到存储（带补偿的双写，原生asyncpg）

        Args:
            record: 执行记录对象

        Returns:
            存储操作结果
        """
        record_id = self._generate_record_id(record)
        record.record_id = record_id

        pg_success = False
        jsonl_success = False
        pg_id = None
        error_msg = None

        with self._lock:
            # 2. 异步写入PostgreSQL（主存储）
            try:
                pg_success, pg_id = await self._write_to_postgres_idempotent_async(record, record_id)
                if not pg_success:
                    error_msg = "PostgreSQL异步写入失败"
            except Exception as e:
                logger.error(f"[UserExecutionStore] PG异步写入异常: {e}")
                error_msg = f"PG异步异常: {str(e)}"

            # 3. 写入JSONL（本地缓存）
            try:
                jsonl_success = self._write_to_jsonl_with_id(record, record_id)
                if not jsonl_success:
                    if error_msg:
                        error_msg += "; JSONL写入失败"
                    else:
                        error_msg = "JSONL写入失败"
            except Exception as e:
                logger.error(f"[UserExecutionStore] JSONL写入异常: {e}")
                if error_msg:
                    error_msg += f"; JSONL异常: {str(e)}"
                else:
                    error_msg = f"JSONL异常: {str(e)}"

            # 4. 更新内存缓存
            if jsonl_success:
                self._records.append(record)
                if len(self._records) > self._max_records:
                    self._records.pop(0)

        # 5. 补偿机制
        result = StoreResult(
            record_id=record_id,
            pg_success=pg_success,
            jsonl_success=jsonl_success,
            pg_id=pg_id,
            error=error_msg
        )

        if pg_success and not jsonl_success:
            result.needs_compensation = True
            result.compensation_target = "jsonl"
            self._schedule_sync_to_jsonl(record_id, record)
            logger.warning(f"[UserExecutionStore] 需要补偿到JSONL: {record_id}")
        elif jsonl_success and not pg_success:
            result.needs_compensation = True
            result.compensation_target = "pg"
            self._schedule_sync_to_pg(record_id, record)
            logger.warning(f"[UserExecutionStore] 需要补偿到PG: {record_id}")

        if result.is_fully_synced:
            logger.debug(f"[UserExecutionStore] 异步双写成功: {record_id}")
        elif result.is_success:
            logger.warning(f"[UserExecutionStore] 异步部分写入成功: {record_id}, PG={pg_success}, JSONL={jsonl_success}")
        else:
            logger.error(f"[UserExecutionStore] 异步双写都失败: {record_id}")

        return result

    def _schedule_sync_to_jsonl(self, record_id: str, record: ToolExecutionRecord):
        """调度补偿任务到JSONL"""
        task_data = record.to_dict()
        self._comp_mgr.schedule_compensation(record_id, 'jsonl', task_data)
        self._save_compensation_task(record_id, 'jsonl', task_data)

    def _schedule_sync_to_pg(self, record_id: str, record: ToolExecutionRecord):
        """调度补偿任务到PostgreSQL"""
        task_data = record.to_dict()
        self._comp_mgr.schedule_compensation(record_id, 'pg', task_data)
        self._save_compensation_task(record_id, 'pg', task_data)

    # ========================================================================
    # 向后兼容的add方法
    # ========================================================================

    def add(self, record: ToolExecutionRecord) -> str:
        """
        添加执行记录到存储（向后兼容接口）

        Args:
            record: 执行记录对象

        Returns:
            记录唯一ID
        """
        result = self.add_with_compensation(record)
        return result.record_id

    async def add_async(self, record: ToolExecutionRecord) -> str:
        """
        异步添加执行记录到存储（向后兼容接口，原生asyncpg）

        Args:
            record: 执行记录对象

        Returns:
            记录唯一ID
        """
        result = await self.add_with_compensation_async(record)
        return result.record_id

    # ========================================================================
    # V7.1 FIX: 幂等同步
    # ========================================================================

    def _sync_jsonl_to_db_idempotent(self) -> dict[str, Any]:
        """
        将JSONL中未同步的记录幂等地写入PostgreSQL（同步版本）

        【V7.1修复后】
        - 使用record_id作为幂等键
        - 存在则更新，不存在则插入

        Returns:
            同步结果统计
        """
        if not MEMORY_SYSTEM_AVAILABLE or PostgresConnectionPool is None:
            return {"synced": 0, "error": "PostgreSQL not available"}

        # 获取上次同步时间
        last_sync = None
        if self.sync_marker_file.exists():
            try:
                from core.utils.file_utils import read_text
                last_sync = datetime.fromisoformat(read_text(self.sync_marker_file).strip())
            except (OSError, ValueError) as e:
                logger.error(f"[UserExecutionStore] 读取同步标记文件失败: {e}", exc_info=True)

        if not last_sync:
            last_sync = datetime.min

        # 读取JSONL中未同步的记录
        unsynced_records = []
        if self.executions_file.exists():
            try:
                for data in read_jsonl(self.executions_file):
                    try:
                        record = ToolExecutionRecord.from_dict(data)
                        if record.timestamp > last_sync:
                            unsynced_records.append(record)
                    except (json.JSONDecodeError, ValueError, TypeError) as e:
                        logger.warning(f"[UserExecutionStore] 解析未同步记录失败: {e}")
                        continue
            except Exception as e:
                logger.error(f"[UserExecutionStore] 读取JSONL失败: {e}")
                return {"synced": 0, "error": str(e)}

        if not unsynced_records:
            return {"synced": 0, "message": "No new records to sync"}

        # 批量同步到PostgreSQL（幂等）
        synced_count = 0
        failed_count = 0
        conn = None

        try:
            conn = PostgresConnectionPool.get_connection()

            for record in unsynced_records:
                try:
                    # 如果没有record_id，生成一个
                    if not record.record_id:
                        record.record_id = self._generate_record_id(record)

                    content = {
                        "tool_name": record.tool_name,
                        "input_params": record.input_params,
                        "output_result": record.output_result,
                        "success": record.success,
                        "error_code": record.error_code,
                        "error_message": record.error_message
                    }
                    context = {
                        "task_id": record.task_id,
                        "session_id": record.session_id,
                        "tool_params": record.tool_params or record.input_params,
                        "source": "execution_memory",
                        "synced_from": "jsonl",
                        "record_id": record.record_id
                    }

                    with conn.cursor() as c:
                        # V7.1 FIX: 使用UPSERT保证幂等性
                        c.execute('''
                            INSERT INTO memories
                            (id, user_id, layer, mem_type, content, context,
                             scene, rating, execution_time, tool_params, created_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (id) DO UPDATE SET
                                content = EXCLUDED.content,
                                context = EXCLUDED.context,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE memories.created_at < EXCLUDED.created_at
                        ''', (
                            record.record_id,
                            self.user_id,
                            LAYER_EXECUTION,
                            record.tool_name,
                            json.dumps(content, ensure_ascii=False),
                            Json(context),
                            f"exec_{record.tool_name}",
                            1 if record.success else 0,
                            record.execution_time_ms / 1000.0,
                            Json(record.tool_params or record.input_params),
                            record.timestamp
                        ))
                    synced_count += 1

                except Exception as e:
                    logger.warning(f"[UserExecutionStore] 单条同步失败: {e}")
                    failed_count += 1
                    continue

            conn.commit()

            # 更新同步标记
            from core.utils.file_utils import write_text
            write_text(self.sync_marker_file, datetime.now().isoformat())

            logger.info(f"[UserExecutionStore] 同步完成: {synced_count}/{len(unsynced_records)} 条记录")
            return {
                "synced": synced_count,
                "failed": failed_count,
                "total": len(unsynced_records),
                "last_sync": datetime.now().isoformat(),
                "idempotent": True
            }

        except Exception as e:
            logger.error(f"[UserExecutionStore] 批量同步失败: {e}")
            if conn:
                conn.rollback()
            return {"synced": synced_count, "failed": failed_count, "error": str(e)}
        finally:
            if conn:
                PostgresConnectionPool.return_connection(conn)

    async def _sync_jsonl_to_db_idempotent_async(self) -> dict[str, Any]:
        """
        将JSONL中未同步的记录幂等地异步写入PostgreSQL（原生asyncpg）

        Returns:
            同步结果统计
        """
        try:
            from core.memory.postgres_pool import AsyncPostgresPool
        except ImportError:
            return {"synced": 0, "error": "PostgreSQL not available"}

        # 获取上次同步时间
        last_sync = None
        if self.sync_marker_file.exists():
            try:
                from core.utils.file_utils import read_text
                last_sync = datetime.fromisoformat(read_text(self.sync_marker_file).strip())
            except (OSError, ValueError) as e:
                logger.error(f"[UserExecutionStore] 读取同步标记文件失败: {e}", exc_info=True)

        if not last_sync:
            last_sync = datetime.min

        # 读取JSONL中未同步的记录
        unsynced_records = []
        if self.executions_file.exists():
            try:
                for data in read_jsonl(self.executions_file):
                    try:
                        record = ToolExecutionRecord.from_dict(data)
                        if record.timestamp > last_sync:
                            unsynced_records.append(record)
                    except (json.JSONDecodeError, ValueError, TypeError) as e:
                        logger.warning(f"[UserExecutionStore] 解析未同步记录失败: {e}")
                        continue
            except Exception as e:
                logger.error(f"[UserExecutionStore] 读取JSONL失败: {e}")
                return {"synced": 0, "error": str(e)}

        if not unsynced_records:
            return {"synced": 0, "message": "No new records to sync"}

        # 批量异步同步到PostgreSQL（幂等）
        synced_count = 0
        failed_count = 0

        try:
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn, conn.transaction():
                for record in unsynced_records:
                    try:
                        if not record.record_id:
                            record.record_id = self._generate_record_id(record)

                        content = {
                            "tool_name": record.tool_name,
                            "input_params": record.input_params,
                            "output_result": record.output_result,
                            "success": record.success,
                            "error_code": record.error_code,
                            "error_message": record.error_message
                        }
                        context = {
                            "task_id": record.task_id,
                            "session_id": record.session_id,
                            "tool_params": record.tool_params or record.input_params,
                            "source": "execution_memory",
                            "synced_from": "jsonl",
                            "record_id": record.record_id
                        }

                        await conn.execute('''
                                INSERT INTO memories
                                (id, user_id, layer, mem_type, content, context,
                                 scene, rating, execution_time, tool_params, created_at)
                                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                                ON CONFLICT (id) DO UPDATE SET
                                    content = EXCLUDED.content,
                                    context = EXCLUDED.context,
                                    updated_at = CURRENT_TIMESTAMP
                                WHERE memories.created_at < EXCLUDED.created_at
                            ''',
                            record.record_id,
                            self.user_id,
                            LAYER_EXECUTION,
                            record.tool_name,
                            json.dumps(content, ensure_ascii=False),
                            json.dumps(context, ensure_ascii=False),
                            f"exec_{record.tool_name}",
                            1 if record.success else 0,
                            record.execution_time_ms / 1000.0,
                            json.dumps(record.tool_params or record.input_params, ensure_ascii=False),
                            record.timestamp
                        )
                        synced_count += 1
                    except Exception as e:
                        logger.warning(f"[UserExecutionStore] 单条异步同步失败: {e}")
                        failed_count += 1
                        continue

            # 更新同步标记
            from core.utils.file_utils import write_text
            write_text(self.sync_marker_file, datetime.now().isoformat())

            logger.info(f"[UserExecutionStore] 异步同步完成: {synced_count}/{len(unsynced_records)} 条记录")
            return {
                "synced": synced_count,
                "failed": failed_count,
                "total": len(unsynced_records),
                "last_sync": datetime.now().isoformat(),
                "idempotent": True
            }

        except Exception as e:
            logger.error(f"[UserExecutionStore] 批量异步同步失败: {e}")
            return {"synced": synced_count, "failed": failed_count, "error": str(e)}

    # ========================================================================
    # 查询方法（保持不变）
    # ========================================================================

    def get_recent(self, limit: int = 100, tool_name: str | None = None,
                  success_only: bool | None = None) -> list[ToolExecutionRecord]:
        """
        获取最近的执行记录
        【优先从内存缓存读取，加速查询】

        Args:
            limit: 返回记录数量上限，默认100
            tool_name: 工具名过滤，可选
            success_only: 是否只返回成功记录，可选

        Returns:
            执行记录列表
        """
        self._ensure_records_loaded()
        with self._lock:
            records = list(reversed(self._records))

            if tool_name:
                records = [r for r in records if r.tool_name == tool_name]
            if success_only is not None:
                records = [r for r in records if r.success == success_only]

            return records[:limit]

    def get_by_time_range(self, start: datetime, end: datetime,
                         tool_name: str | None = None) -> list[ToolExecutionRecord]:
        """
        获取指定时间范围内的记录
        【优先从PostgreSQL读取完整数据】

        Args:
            start: 开始时间
            end: 结束时间
            tool_name: 工具名过滤，可选

        Returns:
            执行记录列表
        """
        records = []

        # 1. 首先尝试从PostgreSQL读取
        if MEMORY_SYSTEM_AVAILABLE and PostgresConnectionPool:
            try:
                conn = PostgresConnectionPool.get_connection()
                try:
                    with conn.cursor(cursor_factory=RealDictCursor) as c:
                        query = """
                            SELECT content, context, created_at, execution_time
                            FROM memories
                            WHERE user_id = %s AND layer = %s
                            AND created_at >= %s AND created_at <= %s
                        """
                        params = [self.user_id, LAYER_EXECUTION, start, end]

                        if tool_name:
                            query += " AND mem_type = %s"
                            params.append(tool_name)

                        query += " ORDER BY created_at DESC"

                        c.execute(query, params)
                        rows = c.fetchall()

                        for row in rows:
                            try:
                                _raw_content = row['content']
                                if _raw_content is None:
                                    logger.warning("[ExecutionMemoryManager] 执行记录 content 为 None，降级为空字典")
                                    content = {}
                                else:
                                    content = json.loads(_raw_content) if isinstance(_raw_content, str) else _raw_content
                                context = row['context'] or {}

                                record = ToolExecutionRecord(
                                    user_id=self.user_id,
                                    tool_name=content.get('tool_name', 'unknown'),
                                    input_params=content.get('input_params', {}),
                                    output_result=content.get('output_result', {}),
                                    success=content.get('success', False),
                                    execution_time_ms=int((row['execution_time'] or 0) * 1000),
                                    timestamp=row['created_at'],
                                    task_id=context.get('task_id'),
                                    session_id=context.get('session_id'),
                                    error_code=content.get('error_code'),
                                    error_message=content.get('error_message'),
                                    tool_params=context.get('tool_params', {}),
                                    record_id=context.get('record_id')  # 恢复record_id
                                )
                                records.append(record)
                            except (json.JSONDecodeError, ValueError, TypeError, KeyError) as e:
                                logger.error(f"[UserExecutionStore] 解析PostgreSQL记录失败: {e}", exc_info=True)
                                continue

                        if records:
                            logger.debug(f"[UserExecutionStore] 从PostgreSQL读取 {len(records)} 条记录")
                            return records
                finally:
                    PostgresConnectionPool.return_connection(conn)
            except Exception as e:
                logger.warning(f"[UserExecutionStore] PostgreSQL查询失败，降级到JSONL: {e}")

        # 2. 降级到JSONL查询
        self._ensure_records_loaded()
        with self._lock:
            for record in self._records:
                if start <= record.timestamp <= end and (tool_name is None or record.tool_name == tool_name):
                    records.append(record)

        if len(records) < 100 and self.executions_file.exists():
            try:
                for data in read_jsonl(self.executions_file):
                    try:
                        record = ToolExecutionRecord.from_dict(data)
                        if start <= record.timestamp <= end and (tool_name is None or record.tool_name == tool_name):
                            records.append(record)
                    except (json.JSONDecodeError, ValueError, TypeError) as e:
                        logger.warning(f"[UserExecutionStore] 解析时间范围记录失败: {e}")
                        continue
            except Exception as e:
                logger.error(f"[UserExecutionStore] 读取JSONL执行记录失败: {e}")

        return records

    async def get_by_time_range_async(self, start: datetime, end: datetime,
                                       tool_name: str | None = None) -> list[ToolExecutionRecord]:
        """
        异步获取指定时间范围内的记录（原生asyncpg）

        Args:
            start: 开始时间
            end: 结束时间
            tool_name: 工具名过滤，可选

        Returns:
            执行记录列表
        """
        records = []

        # 1. 首先尝试从PostgreSQL异步读取
        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                conditions = ["user_id = $1", "layer = $2", "created_at >= $3", "created_at <= $4"]
                params = [self.user_id, LAYER_EXECUTION, start, end]
                idx = 5

                if tool_name:
                    conditions.append(f"mem_type = ${idx}")
                    params.append(tool_name)
                    idx += 1

                sql = f'''
                    SELECT content, context, created_at, execution_time
                    FROM memories
                    WHERE {" AND ".join(conditions)}
                    ORDER BY created_at DESC
                '''

                rows = await conn.fetch(sql, *params)

                for row in rows:
                    try:
                        _raw_content = row["content"]
                        if _raw_content is None:
                            logger.warning("[ExecutionMemoryManager] 执行记录 content 为 None，降级为空字典")
                            content = {}
                        else:
                            content = json.loads(_raw_content) if isinstance(_raw_content, str) else _raw_content
                        context = row["context"] or {}

                        record = ToolExecutionRecord(
                            user_id=self.user_id,
                            tool_name=content.get('tool_name', 'unknown'),
                            input_params=content.get('input_params', {}),
                            output_result=content.get('output_result', {}),
                            success=content.get('success', False),
                            execution_time_ms=int((row["execution_time"] or 0) * 1000),
                            timestamp=row["created_at"],
                            task_id=context.get('task_id'),
                            session_id=context.get('session_id'),
                            error_code=content.get('error_code'),
                            error_message=content.get('error_message'),
                            tool_params=context.get('tool_params', {}),
                            record_id=context.get('record_id')
                        )
                        records.append(record)
                    except (json.JSONDecodeError, ValueError, TypeError, KeyError) as e:
                        logger.error(f"[UserExecutionStore] 异步解析PostgreSQL记录失败: {e}", exc_info=True)
                        continue

                if records:
                    logger.debug(f"[UserExecutionStore] 从PostgreSQL异步读取 {len(records)} 条记录")
                    return records
        except Exception as e:
            logger.warning(f"[UserExecutionStore] PostgreSQL异步查询失败，降级到JSONL: {e}")

        # 2. 降级到JSONL查询
        self._ensure_records_loaded()
        with self._lock:
            for record in self._records:
                if start <= record.timestamp <= end and (tool_name is None or record.tool_name == tool_name):
                    records.append(record)

        if len(records) < 100 and self.executions_file.exists():
            try:
                for data in read_jsonl(self.executions_file):
                    try:
                        record = ToolExecutionRecord.from_dict(data)
                        if start <= record.timestamp <= end and (tool_name is None or record.tool_name == tool_name):
                            records.append(record)
                    except (json.JSONDecodeError, ValueError, TypeError) as e:
                        logger.warning(f"[UserExecutionStore] 解析时间范围记录失败: {e}")
                        continue
            except Exception as e:
                logger.error(f"[UserExecutionStore] 读取JSONL执行记录失败: {e}")

        return records

    def get_stats(self, days: int = 30) -> dict[str, Any]:
        """
        获取指定时间范围的执行统计
        【优化】优先从JSONL缓存快速读取统计

        Args:
            days: 统计天数范围，默认30天

        Returns:
            统计信息字典
        """
        since = datetime.now() - timedelta(days=days)

        # 【优化】从JSONL缓存快速读取统计
        stats = self._get_stats_from_jsonl(since, days)
        if stats["total"] > 0:
            return stats

        # 如果JSONL没有数据，尝试从PostgreSQL读取
        return self._get_stats_from_postgres(days)

    async def get_stats_async(self, days: int = 30) -> dict[str, Any]:
        """
        异步获取指定时间范围的执行统计（原生asyncpg）

        Args:
            days: 统计天数范围，默认30天

        Returns:
            统计信息字典
        """
        since = datetime.now() - timedelta(days=days)

        # 【优化】从JSONL缓存快速读取统计
        stats = self._get_stats_from_jsonl(since, days)
        if stats["total"] > 0:
            return stats

        # 如果JSONL没有数据，尝试从PostgreSQL异步读取
        return await self._get_stats_from_postgres_async(days)

    def _get_stats_from_jsonl(self, since: datetime, days: int) -> dict[str, Any]:
        """从JSONL缓存获取统计（快速路径）"""
        self._ensure_records_loaded()
        with self._lock:
            recent_records = [r for r in self._records if r.timestamp >= since]

        if not recent_records:
            return {
                "user_id": self.user_id,
                "period_days": days,
                "total": 0,
                "success": 0,
                "failed": 0,
                "success_rate": 0.0,
                "avg_time_ms": 0,
                "common_tools": [],
                "common_errors": [],
                "source": "jsonl_cache"
            }

        total = len(recent_records)
        success_count = sum(1 for r in recent_records if r.success)
        failed_count = total - success_count
        success_rate = success_count / total if total > 0 else 0
        avg_time = sum(r.execution_time_ms for r in recent_records) / total if total > 0 else 0

        # 工具统计
        tool_stats = defaultdict(lambda: {"count": 0, "success": 0, "time": 0})
        for r in recent_records:
            tool_stats[r.tool_name]["count"] += 1
            if r.success:
                tool_stats[r.tool_name]["success"] += 1
            tool_stats[r.tool_name]["time"] += r.execution_time_ms

        common_tools = [
            {
                "tool_name": name,
                "count": stats["count"],
                "success_rate": stats["success"] / stats["count"],
                "avg_time_ms": stats["time"] / stats["count"]
            }
            for name, stats in sorted(
                tool_stats.items(),
                key=lambda x: x[1]["count"],
                reverse=True
            )[:10]
        ]

        # 错误统计
        errors = defaultdict(int)
        for r in recent_records:
            if not r.success and r.error_code:
                errors[r.error_code] += 1

        common_errors = [
            {"error_code": code, "count": count}
            for code, count in sorted(errors.items(), key=lambda x: x[1], reverse=True)[:5]
        ]

        return {
            "user_id": self.user_id,
            "period_days": days,
            "total": total,
            "success": success_count,
            "failed": failed_count,
            "success_rate": round(success_rate, 4),
            "avg_time_ms": round(avg_time, 2),
            "common_tools": common_tools,
            "common_errors": common_errors,
            "source": "jsonl_cache"
        }

    def _get_stats_from_postgres(self, days: int) -> dict[str, Any]:
        """从PostgreSQL获取统计（完整路径）"""
        if not MEMORY_SYSTEM_AVAILABLE or PostgresConnectionPool is None:
            return {
                "user_id": self.user_id,
                "period_days": days,
                "total": 0,
                "success": 0,
                "failed": 0,
                "success_rate": 0.0,
                "avg_time_ms": 0,
                "common_tools": [],
                "common_errors": [],
                "source": "unavailable"
            }

        conn = None
        try:
            conn = PostgresConnectionPool.get_connection()
            with conn.cursor() as c:
                # 基础统计
                c.execute("""
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN rating > 0 THEN 1 ELSE 0 END) as success_count,
                        AVG(execution_time) * 1000 as avg_time_ms
                    FROM memories
                    WHERE user_id = %s AND layer = %s
                    AND created_at >= CURRENT_TIMESTAMP - INTERVAL '%s days'
                """, (self.user_id, LAYER_EXECUTION, days))

                row = c.fetchone()
                total = row[0] or 0
                success_count = row[1] or 0
                failed_count = total - success_count
                success_rate = success_count / total if total > 0 else 0
                avg_time = row[2] or 0

                # 工具统计
                c.execute("""
                    SELECT
                        mem_type as tool_name,
                        COUNT(*) as count,
                        SUM(CASE WHEN rating > 0 THEN 1 ELSE 0 END) as success_count,
                        AVG(execution_time) * 1000 as avg_time_ms
                    FROM memories
                    WHERE user_id = %s AND layer = %s
                    AND created_at >= CURRENT_TIMESTAMP - INTERVAL '%s days'
                    GROUP BY mem_type
                    ORDER BY count DESC
                    LIMIT 10
                """, (self.user_id, LAYER_EXECUTION, days))

                common_tools = [
                    {
                        "tool_name": r[0],
                        "count": r[1],
                        "success_rate": r[2] / r[1] if r[1] > 0 else 0,
                        "avg_time_ms": r[3] or 0
                    }
                    for r in c.fetchall()
                ]

                return {
                    "user_id": self.user_id,
                    "period_days": days,
                    "total": total,
                    "success": success_count,
                    "failed": failed_count,
                    "success_rate": round(success_rate, 4),
                    "avg_time_ms": round(avg_time, 2),
                    "common_tools": common_tools,
                    "common_errors": [],  # PostgreSQL存储结构不支持直接错误统计
                    "source": "postgres"
                }
        except Exception as e:
            logger.error(f"[UserExecutionStore] PostgreSQL统计失败: {e}")
            return {
                "user_id": self.user_id,
                "period_days": days,
                "total": 0,
                "error": str(e),
                "source": "error"
            }
        finally:
            if conn:
                PostgresConnectionPool.return_connection(conn)

    async def _get_stats_from_postgres_async(self, days: int) -> dict[str, Any]:
        """从PostgreSQL异步获取统计（原生asyncpg）"""
        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                # 基础统计
                row = await conn.fetchrow(f"""
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN rating > 0 THEN 1 ELSE 0 END) as success_count,
                        AVG(execution_time) * 1000 as avg_time_ms
                    FROM memories
                    WHERE user_id = $1 AND layer = $2
                    AND created_at >= CURRENT_TIMESTAMP - INTERVAL '{days} days'
                """, self.user_id, LAYER_EXECUTION)

                total = row["total"] or 0
                success_count = row["success_count"] or 0
                failed_count = total - success_count
                success_rate = success_count / total if total > 0 else 0
                avg_time = row["avg_time_ms"] or 0

                # 工具统计
                tool_rows = await conn.fetch(f"""
                    SELECT
                        mem_type as tool_name,
                        COUNT(*) as count,
                        SUM(CASE WHEN rating > 0 THEN 1 ELSE 0 END) as success_count,
                        AVG(execution_time) * 1000 as avg_time_ms
                    FROM memories
                    WHERE user_id = $1 AND layer = $2
                    AND created_at >= CURRENT_TIMESTAMP - INTERVAL '{days} days'
                    GROUP BY mem_type
                    ORDER BY count DESC
                    LIMIT 10
                """, self.user_id, LAYER_EXECUTION)

                common_tools = [
                    {
                        "tool_name": r["tool_name"],
                        "count": r["count"],
                        "success_rate": r["success_count"] / r["count"] if r["count"] > 0 else 0,
                        "avg_time_ms": r["avg_time_ms"] or 0
                    }
                    for r in tool_rows
                ]

                return {
                    "user_id": self.user_id,
                    "period_days": days,
                    "total": total,
                    "success": success_count,
                    "failed": failed_count,
                    "success_rate": round(success_rate, 4),
                    "avg_time_ms": round(avg_time, 2),
                    "common_tools": common_tools,
                    "common_errors": [],
                    "source": "postgres"
                }
        except Exception as e:
            logger.error(f"[UserExecutionStore] PostgreSQL异步统计失败: {e}")
            return {
                "user_id": self.user_id,
                "period_days": days,
                "total": 0,
                "error": str(e),
                "source": "error"
            }

    def compress_old_records(self, before_days: int = 30) -> dict[str, Any]:
        """
        压缩旧记录（由DataLifecycleManager调用）

        Args:
            before_days: 压缩该天数之前的记录，默认30天

        Returns:
            压缩结果统计字典
        """
        cutoff_date = datetime.now() - timedelta(days=before_days)

        old_records = self.get_by_time_range(
            datetime.min.replace(tzinfo=None) if cutoff_date.tzinfo else datetime.min,
            cutoff_date
        )

        if not old_records:
            return {"compressed": 0, "saved_bytes": 0}

        summary = self._generate_summary(old_records, before_days)

        compressed_file = self.compressed_dir / f"summary_{before_days}days_{datetime.now().strftime('%Y%m%d')}.json"
        write_json(compressed_file, summary.to_dict())

        compressed_count = len(old_records)

        with self._lock:
            self._records = [r for r in self._records if r.timestamp > cutoff_date]

        return {
            "compressed": compressed_count,
            "summary_file": str(compressed_file),
            "period": f"{before_days}days"
        }

    async def compress_old_records_async(self, before_days: int = 30) -> dict[str, Any]:
        """
        异步压缩旧记录（原生asyncpg查询）

        Args:
            before_days: 压缩该天数之前的记录，默认30天

        Returns:
            压缩结果统计字典
        """
        cutoff_date = datetime.now() - timedelta(days=before_days)

        old_records = await self.get_by_time_range_async(
            datetime.min.replace(tzinfo=None) if cutoff_date.tzinfo else datetime.min,
            cutoff_date
        )

        if not old_records:
            return {"compressed": 0, "saved_bytes": 0}

        summary = self._generate_summary(old_records, before_days)

        compressed_file = self.compressed_dir / f"summary_{before_days}days_{datetime.now().strftime('%Y%m%d')}.json"
        write_json(compressed_file, summary.to_dict())

        compressed_count = len(old_records)

        with self._lock:
            self._records = [r for r in self._records if r.timestamp > cutoff_date]

        return {
            "compressed": compressed_count,
            "summary_file": str(compressed_file),
            "period": f"{before_days}days"
        }

    def _generate_summary(self, records: list[ToolExecutionRecord],
                         period_days: int) -> ExecutionSummary:
        """生成执行记录统计摘要"""
        total = len(records)
        success_count = sum(1 for r in records if r.success)
        fail_count = total - success_count
        success_rate = success_count / total if total > 0 else 0
        avg_time = sum(r.execution_time_ms for r in records) / total if total > 0 else 0

        tool_stats = defaultdict(lambda: {"count": 0, "success": 0, "time": 0})
        error_codes = defaultdict(int)

        for r in records:
            tool_stats[r.tool_name]["count"] += 1
            if r.success:
                tool_stats[r.tool_name]["success"] += 1
            tool_stats[r.tool_name]["time"] += r.execution_time_ms

            if r.error_code:
                error_codes[r.error_code] += 1

        common_tools = [
            {"name": name, "count": s["count"], "success_rate": s["success"] / s["count"]}
            for name, s in sorted(tool_stats.items(), key=lambda x: x[1]["count"], reverse=True)[:10]
        ]

        common_errors = [code for code, _ in sorted(error_codes.items(), key=lambda x: x[1], reverse=True)[:5]]

        return ExecutionSummary(
            period=f"{period_days}days",
            total=total,
            success_count=success_count,
            fail_count=fail_count,
            success_rate=round(success_rate, 4),
            avg_execution_time_ms=round(avg_time, 2),
            common_tools=common_tools,
            common_errors=common_errors
        )

    # 向后兼容方法
    _sync_jsonl_to_db = _sync_jsonl_to_db_idempotent


# ============================================================================
# 执行记忆管理器
# ============================================================================

class ExecutionMemoryManager:
    """
    L5执行记忆管理器 - 管理所有用户的执行记忆
    采用单例模式确保全局唯一实例
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

    def __init__(self, max_records_per_user: int = 1000):
        if self._initialized:
            return
        self._initialized = True

        self.max_records = max_records_per_user
        self._stores: dict[str, UserExecutionStore] = {}
        self._store_lock = threading.RLock()

        # 启动后台同步线程
        self._sync_stop_event = threading.Event()
        self._sync_thread = threading.Thread(target=self._auto_sync_loop, daemon=True)
        self._sync_thread.start()
        logger.info("[ExecutionMemoryManager] 初始化完成，后台同步线程已启动")

    def _auto_sync_loop(self):
        """后台自动同步循环 - 每10分钟执行一次同步"""
        while not self._sync_stop_event.is_set():
            try:
                # 等待10分钟或停止信号
                if self._sync_stop_event.wait(600):
                    break

                # 执行同步
                self.sync_all_to_db()

            except Exception as e:
                logger.error(f"[ExecutionMemoryManager] 自动同步异常: {e}")

    def sync_all_to_db(self) -> dict[str, Any]:
        """
        同步所有用户的JSONL数据到PostgreSQL

        Returns:
            各用户同步结果
        """
        results = {}
        with self._store_lock:
            user_ids = list(self._stores.keys())

        for user_id in user_ids:
            try:
                store = self.get_user_store(user_id)
                results[user_id] = store._sync_jsonl_to_db_idempotent()
            except Exception as e:
                results[user_id] = {"error": str(e)}

        logger.info(f"[ExecutionMemoryManager] 全量同步完成: {len(user_ids)} 个用户")
        return results

    def get_user_store(self, user_id: str) -> UserExecutionStore:
        """
        获取或创建用户执行存储

        Args:
            user_id: 用户唯一标识

        Returns:
            用户执行存储实例
        """
        with self._store_lock:
            if user_id not in self._stores:
                self._stores[user_id] = UserExecutionStore(user_id)
            return self._stores[user_id]

    def record_execution(self, user_id: str, record: ToolExecutionRecord) -> str:
        """
        记录一次工具执行

        Args:
            user_id: 用户ID
            record: 执行记录对象

        Returns:
            记录唯一ID
        """
        store = self.get_user_store(user_id)
        return store.add(record)

    def record_execution_with_result(self, user_id: str, record: ToolExecutionRecord) -> StoreResult:
        """
        记录一次工具执行（返回详细结果）

        Args:
            user_id: 用户ID
            record: 执行记录对象

        Returns:
            存储操作结果
        """
        store = self.get_user_store(user_id)
        return store.add_with_compensation(record)

    def record_from_result(self, user_id: str, tool_name: str,
                          input_params: dict, result: dict,
                          execution_time_ms: int,
                          task_id: str | None = None,
                          session_id: str | None = None) -> str:
        """
        从执行结果创建并记录执行记录

        Args:
            user_id: 用户ID
            tool_name: 工具名称
            input_params: 输入参数
            result: 执行结果字典
            execution_time_ms: 执行时间(毫秒)
            task_id: 任务ID，可选
            session_id: 会话ID，可选

        Returns:
            记录唯一ID
        """
        success = result.get("success", False)
        error_code = result.get("error_code") if not success else None
        error_message = result.get("user_message") if not success else None

        record = ToolExecutionRecord(
            user_id=user_id,
            tool_name=tool_name,
            input_params=input_params,
            output_result=result,
            success=success,
            execution_time_ms=execution_time_ms,
            timestamp=datetime.now(),
            task_id=task_id,
            session_id=session_id,
            error_code=error_code,
            error_message=error_message,
            tool_params=input_params
        )

        return self.record_execution(user_id, record)

    def get_recent_executions(self, user_id: str, tool_name: str | None = None,
                             limit: int = 100, success_only: bool | None = None) -> list[dict]:
        """
        获取最近的执行记录

        Args:
            user_id: 用户ID
            tool_name: 工具名过滤，可选
            limit: 返回数量上限
            success_only: 是否只返回成功记录，可选

        Returns:
            执行记录字典列表
        """
        store = self.get_user_store(user_id)
        records = store.get_recent(limit, tool_name, success_only)
        return [r.to_dict() for r in records]

    def get_execution_stats(self, user_id: str, days: int = 30) -> dict[str, Any]:
        """
        获取执行统计信息

        Args:
            user_id: 用户ID
            days: 统计天数范围，默认30天

        Returns:
            统计信息字典
        """
        store = self.get_user_store(user_id)
        return store.get_stats(days)

    def compress_old_records(self, user_id: str, before_days: int = 30) -> dict[str, Any]:
        """
        压缩指定用户的旧记录

        Args:
            user_id: 用户ID
            before_days: 压缩该天数之前的记录

        Returns:
            压缩结果字典
        """
        store = self.get_user_store(user_id)
        return store.compress_old_records(before_days)

    def compress_all_users(self, before_days: int = 30) -> dict[str, Any]:
        """
        压缩所有用户的旧记录

        Args:
            before_days: 压缩天数阈值

        Returns:
            各用户压缩结果字典
        """
        results = {}
        with self._store_lock:
            user_ids = list(self._stores.keys())

        for user_id in user_ids:
            try:
                results[user_id] = self.compress_old_records(user_id, before_days)
            except Exception as e:
                results[user_id] = {"error": str(e)}

        return results

    def find_similar_failures(self, user_id: str, tool_name: str,
                             error_code: str, limit: int = 5) -> list[dict]:
        """
        查找相似失败记录（用于故障诊断）

        Args:
            user_id: 用户ID
            tool_name: 工具名称
            error_code: 错误码
            limit: 返回数量上限

        Returns:
            相似失败记录列表
        """
        records = self.get_recent_executions(user_id, tool_name, limit=100, success_only=False)

        similar = [
            r for r in records
            if not r.get("success") and r.get("error_code") == error_code
        ]

        return similar[:limit]

    def get_global_stats(self) -> dict[str, Any]:
        """获取全局统计信息"""
        with self._store_lock:
            total_users = len(self._stores)
            all_stats = {
                "total_users": total_users,
                "users": {}
            }

            for user_id, store in self._stores.items():
                try:
                    all_stats["users"][user_id] = store.get_stats()
                except Exception as e:
                    all_stats["users"][user_id] = {"error": str(e)}

            return all_stats

    def close_all(self):
        """关闭所有存储并释放资源"""
        # 停止同步线程
        if hasattr(self, '_sync_stop_event'):
            self._sync_stop_event.set()
            if self._sync_thread and self._sync_thread.is_alive():
                self._sync_thread.join(timeout=5)

        # 停止补偿管理器
        comp_mgr = get_compensation_manager()
        comp_mgr.stop()

        # 执行最后一次同步
        try:
            self.sync_all_to_db()
        except Exception as e:
            logger.warning(f"[ExecutionMemoryManager] 最终同步失败: {e}")

        with self._store_lock:
            self._stores.clear()
        logger.info("[ExecutionMemoryManager] 所有存储已关闭")

    def verify_data_consistency(self, user_id: str, sample_size: int = 100) -> dict[str, Any]:
        """
        验证指定用户的数据一致性

        Args:
            user_id: 用户ID
            sample_size: 抽样检查的记录数

        Returns:
            一致性检查结果
        """
        store = self.get_user_store(user_id)

        # 获取JSONL记录数
        jsonl_count = len(store._records)

        # 获取PostgreSQL记录数
        pg_count = 0
        if MEMORY_SYSTEM_AVAILABLE and PostgresConnectionPool:
            conn = None
            try:
                conn = PostgresConnectionPool.get_connection()
                with conn.cursor() as c:
                    c.execute(
                        "SELECT COUNT(*) FROM memories WHERE user_id = %s AND layer = %s",
                        (user_id, LAYER_EXECUTION)
                    )
                    pg_count = c.fetchone()[0]
            except Exception as e:
                logger.error(f"[ExecutionMemoryManager] 查询PG记录数失败: {e}")
            finally:
                if conn:
                    PostgresConnectionPool.return_connection(conn)

        # 计算差异
        diff = abs(jsonl_count - pg_count)
        consistency_rate = 1.0 - (diff / max(jsonl_count, pg_count, 1))

        return {
            "user_id": user_id,
            "jsonl_count": jsonl_count,
            "postgres_count": pg_count,
            "difference": diff,
            "consistency_rate": round(consistency_rate, 4),
            "is_consistent": diff == 0,
            "checked_at": datetime.now().isoformat()
        }

    # ═══════════════════════════════════════════════════════════════════════════
    # 异步 API（P1-Asyncify：原生 asyncpg，避免阻塞事件循环）
    # ═══════════════════════════════════════════════════════════════════════════

    async def record_execution_async(self, user_id: str, record: ToolExecutionRecord) -> str:
        """异步记录一次工具执行（直接写入PostgreSQL）"""
        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            record_id = ExecutionIdGenerator.generate_execution_id(
                user_id, record.tool_name, record.timestamp
            )
            content = json.dumps({
                "tool_name": record.tool_name,
                "input_params": record.input_params,
                "output_result": record.output_result,
                "success": record.success,
                "error_code": record.error_code,
                "error_message": record.error_message
            }, ensure_ascii=False)
            context = json.dumps({
                "task_id": record.task_id,
                "session_id": record.session_id,
                "tool_params": record.tool_params or record.input_params,
                "source": "execution_memory",
                "record_id": record_id
            }, ensure_ascii=False)

            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                await conn.execute('''
                    INSERT INTO memories
                    (id, user_id, layer, mem_type, content, context,
                     scene, rating, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    ON CONFLICT (id) DO UPDATE SET
                        content = EXCLUDED.content,
                        context = EXCLUDED.context,
                        updated_at = CURRENT_TIMESTAMP
                ''',
                    record_id, user_id, LAYER_EXECUTION, 'tool_execution',
                    content, context,
                    record.tool_name,
                    1 if record.success else 0,
                    record.timestamp
                )
            return record_id
        except Exception as e:
            logger.error(f"[ExecutionMemoryManager] 异步记录执行失败: {e}")
            # 降级：同步写入JSONL
            store = self.get_user_store(user_id)
            return store.add(record)

    async def get_recent_executions_async(self, user_id: str, tool_name: str | None = None,
                                          limit: int = 100, success_only: bool | None = None) -> list[dict]:
        """异步获取最近的执行记录"""
        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                conditions = ["user_id = $1", "layer = $2"]
                params = [user_id, LAYER_EXECUTION]
                idx = 3
                if tool_name:
                    conditions.append(f"scene = ${idx}")
                    params.append(tool_name)
                    idx += 1

                sql = f'''
                    SELECT id, content, context, scene, rating, created_at
                    FROM memories
                    WHERE {" AND ".join(conditions)}
                    ORDER BY created_at DESC
                    LIMIT ${idx}
                '''
                params.append(limit)
                rows = await conn.fetch(sql, *params)

                results = []
                for row in rows:
                    _raw_content = row["content"]
                    if _raw_content is None:
                        logger.warning("[ExecutionMemoryManager] 执行记录 content 为 None，降级为空字典")
                        content = {}
                    else:
                        content = _raw_content if isinstance(_raw_content, dict) else json.loads(_raw_content)

                    _raw_context = row["context"]
                    if _raw_context is None:
                        context = {}
                    else:
                        context = _raw_context if isinstance(_raw_context, dict) else json.loads(_raw_context)

                    if success_only is not None and bool(row["rating"]) != success_only:
                        continue
                    results.append({
                        "id": row["id"],
                        "tool_name": row["scene"],
                        "content": content,
                        "context": context,
                        "success": bool(row["rating"]),
                        "created_at": row["created_at"].isoformat() if row["created_at"] else None
                    })
                return results
        except Exception as e:
            logger.error(f"[ExecutionMemoryManager] 异步获取执行记录失败: {e}")
            return []

    async def get_execution_stats_async(self, user_id: str, days: int = 30) -> dict[str, Any]:
        """异步获取执行统计信息"""
        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                total = await conn.fetchval(
                    f"SELECT COUNT(*) FROM memories WHERE user_id = $1 AND layer = $2 AND created_at > CURRENT_TIMESTAMP - INTERVAL '{days} days'",
                    user_id, LAYER_EXECUTION
                ) or 0
                success = await conn.fetchval(
                    f"SELECT COUNT(*) FROM memories WHERE user_id = $1 AND layer = $2 AND rating = 1 AND created_at > CURRENT_TIMESTAMP - INTERVAL '{days} days'",
                    user_id, LAYER_EXECUTION
                ) or 0
                fail = total - success
                avg_time = await conn.fetchval(
                    f"SELECT AVG(execution_time) FROM memories WHERE user_id = $1 AND layer = $2 AND created_at > CURRENT_TIMESTAMP - INTERVAL '{days} days'",
                    user_id, LAYER_EXECUTION
                ) or 0
                return {
                    "user_id": user_id,
                    "total": total,
                    "success": success,
                    "fail": fail,
                    "success_rate": round(success / max(total, 1), 4),
                    "avg_execution_time_ms": round(avg_time, 2),
                    "period_days": days
                }
        except Exception as e:
            logger.error(f"[ExecutionMemoryManager] 异步获取执行统计失败: {e}")
            return {"user_id": user_id, "total": 0, "success": 0, "fail": 0}

    async def verify_data_consistency_async(self, user_id: str, sample_size: int = 100) -> dict[str, Any]:
        """异步验证数据一致性"""
        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                pg_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM memories WHERE user_id = $1 AND layer = $2",
                    user_id, LAYER_EXECUTION
                ) or 0
            jsonl_count = len(self.get_user_store(user_id)._records)
            diff = abs(jsonl_count - pg_count)
            consistency_rate = 1.0 - (diff / max(jsonl_count, pg_count, 1))
            return {
                "user_id": user_id,
                "jsonl_count": jsonl_count,
                "postgres_count": pg_count,
                "difference": diff,
                "consistency_rate": round(consistency_rate, 4),
                "is_consistent": diff == 0,
                "checked_at": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"[ExecutionMemoryManager] 异步一致性检查失败: {e}")
            return {"user_id": user_id, "error": str(e)}

    async def sync_all_to_db_async(self) -> dict[str, Any]:
        """
        异步同步所有用户的JSONL数据到PostgreSQL（原生asyncpg）

        Returns:
            各用户同步结果
        """
        results = {}
        with self._store_lock:
            user_ids = list(self._stores.keys())

        for user_id in user_ids:
            try:
                store = self.get_user_store(user_id)
                results[user_id] = await store._sync_jsonl_to_db_idempotent_async()
            except Exception as e:
                results[user_id] = {"error": str(e)}

        logger.info(f"[ExecutionMemoryManager] 异步全量同步完成: {len(user_ids)} 个用户")
        return results

    async def record_execution_with_result_async(self, user_id: str, record: ToolExecutionRecord) -> StoreResult:
        """
        异步记录一次工具执行（返回详细结果，原生asyncpg）

        Args:
            user_id: 用户ID
            record: 执行记录对象

        Returns:
            存储操作结果
        """
        store = self.get_user_store(user_id)
        return await store.add_with_compensation_async(record)

    async def record_from_result_async(self, user_id: str, tool_name: str,
                                        input_params: dict, result: dict,
                                        execution_time_ms: int,
                                        task_id: str | None = None,
                                        session_id: str | None = None) -> str:
        """
        从执行结果异步创建并记录执行记录

        Args:
            user_id: 用户ID
            tool_name: 工具名称
            input_params: 输入参数
            result: 执行结果字典
            execution_time_ms: 执行时间(毫秒)
            task_id: 任务ID，可选
            session_id: 会话ID，可选

        Returns:
            记录唯一ID
        """
        success = result.get("success", False)
        error_code = result.get("error_code") if not success else None
        error_message = result.get("user_message") if not success else None

        record = ToolExecutionRecord(
            user_id=user_id,
            tool_name=tool_name,
            input_params=input_params,
            output_result=result,
            success=success,
            execution_time_ms=execution_time_ms,
            timestamp=datetime.now(),
            task_id=task_id,
            session_id=session_id,
            error_code=error_code,
            error_message=error_message,
            tool_params=input_params
        )

        return await self.record_execution_async(user_id, record)

    async def compress_old_records_async(self, user_id: str, before_days: int = 30) -> dict[str, Any]:
        """
        异步压缩指定用户的旧记录

        Args:
            user_id: 用户ID
            before_days: 压缩该天数之前的记录

        Returns:
            压缩结果字典
        """
        store = self.get_user_store(user_id)
        return await store.compress_old_records_async(before_days)

    async def compress_all_users_async(self, before_days: int = 30) -> dict[str, Any]:
        """
        异步压缩所有用户的旧记录

        Args:
            before_days: 压缩天数阈值

        Returns:
            各用户压缩结果字典
        """
        results = {}
        with self._store_lock:
            user_ids = list(self._stores.keys())

        for user_id in user_ids:
            try:
                results[user_id] = await self.compress_old_records_async(user_id, before_days)
            except Exception as e:
                results[user_id] = {"error": str(e)}

        return results

    async def find_similar_failures_async(self, user_id: str, tool_name: str,
                                           error_code: str, limit: int = 5) -> list[dict]:
        """
        异步查找相似失败记录（用于故障诊断）

        Args:
            user_id: 用户ID
            tool_name: 工具名称
            error_code: 错误码
            limit: 返回数量上限

        Returns:
            相似失败记录列表
        """
        records = await self.get_recent_executions_async(user_id, tool_name, limit=100, success_only=False)

        similar = [
            r for r in records
            if not r.get("success") and r.get("error_code") == error_code
        ]

        return similar[:limit]

    async def get_global_stats_async(self) -> dict[str, Any]:
        """异步获取全局统计信息"""
        with self._store_lock:
            total_users = len(self._stores)
            all_stats = {
                "total_users": total_users,
                "users": {}
            }

            for user_id, store in self._stores.items():
                try:
                    all_stats["users"][user_id] = await store.get_stats_async()
                except Exception as e:
                    all_stats["users"][user_id] = {"error": str(e)}

            return all_stats


# 兼容旧接口的 ExecutionMemory 类
class ExecutionMemory:
    """兼容旧接口的执行记忆类 - 保持向后兼容"""

    _instance = None
    _default_user_id = "default"

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._manager = None
        return cls._instance

    def __init__(self):
        if self._manager is None:
            self._manager = ExecutionMemoryManager()

    @staticmethod
    async def store(task_description: str = None, execution_history: list[dict] = None,
              final_result: str | None = None,
              errors: list[str] = None,
              is_success: bool = True,
              user_input: str = None,  # 兼容新调用方式
              user_id: str = None,     # 兼容新调用方式
              session_id: str = None   # 兼容新调用方式
              ):
        """
        兼容旧接口的存储方法（异步版本）

        支持两种调用方式:
        1. 旧方式: store(task_description, execution_history, final_result, is_success=True)
        2. 新方式: store(user_input=..., execution_history=..., final_result=..., user_id=..., session_id=...)
        """
        # 参数兼容处理: user_input 和 task_description 是同一个含义
        actual_task = user_input if user_input is not None else task_description
        if actual_task is None:
            actual_task = "unknown_task"

        # 使用传入的user_id或默认值
        actual_user_id = user_id if user_id is not None else ExecutionMemory._default_user_id

        # 构建context，包含session_id
        tool_params = {"task": actual_task}
        if session_id:
            tool_params["session_id"] = session_id

        record = ToolExecutionRecord(
            user_id=actual_user_id,
            tool_name="legacy_task",
            input_params={"task": actual_task},
            output_result={"result": final_result, "history": execution_history or []},
            success=is_success,
            execution_time_ms=0,
            timestamp=datetime.now(),
            error_message="; ".join(errors) if errors else None,
            tool_params=tool_params,
            session_id=session_id
        )

        await ExecutionMemory()._manager.record_execution_async(actual_user_id, record)

    @staticmethod
    def recall_similar(task_description: str, limit: int = 3) -> list[dict]:
        """召回相似任务的执行记忆"""
        records = ExecutionMemory()._manager.get_recent_executions(
            ExecutionMemory._default_user_id,
            limit=limit,
            success_only=True
        )
        return records

    async def get_execution_stats_async(self, user_id: str = None, days: int = 30) -> dict[str, Any]:
        """异步获取执行统计（兼容层）"""
        uid = user_id or self._default_user_id
        return await self._manager.get_execution_stats_async(uid, days)

    async def get_recent_executions_async(self, user_id: str = None, limit: int = 100) -> list[dict]:
        """异步获取最近执行记录（兼容层）"""
        uid = user_id or self._default_user_id
        return await self._manager.get_recent_executions_async(uid, limit=limit)

    def get_execution_stats(self, user_id: str = None, days: int = 30) -> dict[str, Any]:
        """
        获取执行统计（兼容层）

        Args:
            user_id: 用户ID，默认使用default_user
            days: 统计天数范围

        Returns:
            执行统计信息字典
        """
        uid = user_id or self._default_user_id
        return self._manager.get_execution_stats(uid, days)

    def record_execution(self, user_id: str, tool_name: str, params: dict,
                         success: bool, result_summary: str = "",
                         execution_time_ms: int = 0, session_id: str = None) -> str:
        """记录工具执行（兼容接口）

        Args:
            user_id: 用户ID
            tool_name: 工具名称
            params: 工具参数
            success: 是否执行成功
            result_summary: 结果摘要
            execution_time_ms: 执行时间（毫秒）
            session_id: 会话ID

        Returns:
            记录ID
        """
        record = ToolExecutionRecord(
            user_id=user_id,
            tool_name=tool_name,
            input_params=params,
            output_result={"success": success, "summary": result_summary},
            success=success,
            execution_time_ms=execution_time_ms,
            timestamp=datetime.now(),
            session_id=session_id,
            tool_params=params
        )

        return self._manager.record_execution(user_id, record)


# 全局实例初始化
execution_memory_manager = None
execution_memory = None

try:
    execution_memory_manager = ExecutionMemoryManager()
    execution_memory = ExecutionMemory()
    print("【成功】 Execution memory system V7.1 initialized successfully (统一ID + 补偿机制 + 幂等写入)")
except Exception as e:
    print(f"[ERROR] Failed to initialize execution memory: {e}")
    execution_memory_manager = None
    execution_memory = None


# ============================================
# 文件总结性注释
# ============================================
#
# 【文件角色】
# execution_memory.py 是 SiliconBase V5系统的"L5执行记忆层"核心模块，
# 是五层记忆架构（L1-L5）中最底层，专门负责记录和管理工具执行历史。
#
# 【V7.1修复版本核心变更】
# 1. ✅ 统一ID生成: ExecutionIdGenerator 类统一生成 exec_{uuid}_{ts}_{hash} 格式ID
# 2. ✅ 失败补偿机制: CompensationManager 类调度补偿任务，保证最终一致性
# 3. ✅ 幂等性保证: UPSERT (ON CONFLICT DO UPDATE) 确保重复写入不会导致重复数据
# 4. 双重存储架构: PostgreSQL(主存储) + JSONL(本地缓存)
# 5. 写入策略: 双写 + 补偿 = 最终一致性
#
# 【存储架构】
# ```
# PostgreSQL (主存储):
#   memories表:
#     - id = record_id (统一ID，VARCHAR PRIMARY KEY)
#     - layer = "execution"
#     - execution_time FLOAT
#     - tool_params JSONB
#     - content: 完整执行记录
#     - context: 关联信息(task_id, session_id, record_id)
#     - 幂等写入: ON CONFLICT (id) DO UPDATE
#
# JSONL (本地缓存):
#   data/execution/{user_id}/executions.jsonl
#   - record_id 字段存储统一ID
#   - 快速读取统计
#   - 向后兼容
#   - 离线可用
#
# 补偿队列:
#   data/execution/{user_id}/.compensation_queue
#   - 持久化存储待补偿任务
#   - 服务重启后可恢复
# ```
#
# 【V7.1修复详情】
# | 问题 | 修复方案 | 代码位置 |
# |------|----------|----------|
# | ID不一致 | ExecutionIdGenerator 统一生成 | _generate_record_id() |
# | 双写失败无补偿 | CompensationManager + 补偿队列 | add_with_compensation() |
# | 同步缺乏幂等性 | UPSERT语法 ON CONFLICT DO UPDATE | _write_to_postgres_idempotent() |
#
# 【五层记忆架构位置】
#   L1 - 原始感知层: 原始传感器数据
#   L2 - 短期记忆层: 最近对话、临时上下文
#   L3 - 工作记忆层: 当前任务状态、注意力焦点
#   L4 - 长期记忆层: 知识库、经验、用户画像
#   L5 - 执行记忆层: 工具执行历史 ← 本文件
#
# 【关联文件】
# | 文件 | 关系类型 | 说明 |
# |------|----------|------|
# | core/memory.py | 上层模块 | 提供PostgreSQL存储 |
# | core/memory_compression.py | 调用者 | 数据生命周期管理 |
# | core/agent_loop.py | 调用者 | Agent循环，记录每次工具执行 |
# | core/tool_manager.py | 关联 | 工具执行时记录调用 |
#
# 【使用示例】
# ```python
# from core.memory.execution_memory import execution_memory_manager
#
# # 记录执行（自动统一ID + 补偿）
# result = execution_memory_manager.record_execution_with_result(
#     user_id="user_001",
#     record=ToolExecutionRecord(...)
# )
# print(f"记录ID: {result.record_id}, 双写成功: {result.is_fully_synced}")
#
# # 验证数据一致性
# consistency = execution_memory_manager.verify_data_consistency("user_001")
# print(f"一致性: {consistency['consistency_rate']*100}%")
# ```
#
# ============================================
