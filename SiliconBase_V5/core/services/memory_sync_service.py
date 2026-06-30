#!/usr/bin/env python3
"""
Memory同步服务 - 最终一致性实现
硅基生命底座架构改进
"""

import asyncio
import queue
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from core.logger import logger
from core.memory.memory_service import get_memory_service


class SyncStatus(Enum):
    PENDING = "pending"
    SYNCING = "syncing"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass
class SyncTask:
    """同步任务"""
    task_id: str
    memory_id: str
    user_id: str
    operation: str  # "add", "update", "delete"
    data: dict[str, Any]
    retry_count: int = 0
    max_retries: int = 3


class MemorySyncService:
    """
    Memory同步服务 - 异步同步向量库

    职责：
    1. 维护同步任务队列
    2. 异步将PostgreSQL数据同步到ChromaDB
    3. 处理同步失败的重试
    4. 提供同步状态查询
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

        self._task_queue: queue.Queue[SyncTask] = queue.Queue(maxsize=1000)
        self._sync_status: dict[str, SyncStatus] = {}
        self._running = False
        self._worker_thread: threading.Thread | None = None

        logger.info("[MemorySyncService] 初始化完成")

    def start(self):
        """启动同步服务"""
        if self._running:
            return

        self._running = True
        self._worker_thread = threading.Thread(target=self._sync_worker, daemon=True)
        self._worker_thread.start()
        logger.info("[MemorySyncService] 同步服务已启动")

    def stop(self):
        """停止同步服务"""
        self._running = False
        if self._worker_thread:
            self._worker_thread.join(timeout=5)
        logger.info("[MemorySyncService] 同步服务已停止")

    def add_task(self, memory_id: str, user_id: str, operation: str, data: dict) -> bool:
        """添加同步任务"""
        try:
            task = SyncTask(
                task_id=f"{memory_id}_{int(time.time())}",
                memory_id=memory_id,
                user_id=user_id,
                operation=operation,
                data=data
            )
            self._task_queue.put(task, block=False)
            self._sync_status[memory_id] = SyncStatus.PENDING
            return True
        except queue.Full:
            logger.error(f"[MemorySyncService] 任务队列已满: {memory_id}")
            return False

    def _sync_worker(self):
        """同步工作线程"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        while self._running:
            try:
                task = self._task_queue.get(timeout=1)
                loop.run_until_complete(self._process_sync_task(task))
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"[MemorySyncService] 工作线程异常: {e}")
        loop.close()

    async def _process_sync_task(self, task: SyncTask):
        """处理同步任务"""
        self._sync_status[task.memory_id] = SyncStatus.SYNCING

        try:
            success = await self._sync_to_vector_db(task)

            if success:
                self._sync_status[task.memory_id] = SyncStatus.SUCCESS
                logger.debug(f"[MemorySyncService] 同步成功: {task.memory_id}")
            else:
                raise Exception("同步返回失败")

        except Exception as e:
            logger.warning(f"[MemorySyncService] 同步失败: {task.memory_id}, 错误: {e}")

            if task.retry_count < task.max_retries:
                task.retry_count += 1
                await asyncio.sleep(2 ** task.retry_count)  # 指数退避（协程安全）
                self._task_queue.put(task)
                logger.info(f"[MemorySyncService] 任务重试: {task.memory_id}, 第{task.retry_count}次")
            else:
                self._sync_status[task.memory_id] = SyncStatus.FAILED
                logger.error(f"[MemorySyncService] 同步最终失败: {task.memory_id}")

    async def _sync_to_vector_db(self, task: SyncTask) -> bool:
        """执行实际的向量库同步"""
        try:
            ms = await get_memory_service()

            if task.operation == "add":
                await ms.vector_store.add(
                    collection="memories",
                    text=task.data.get("content", ""),
                    metadata=task.data
                )
            elif task.operation == "delete":
                await ms.vector_store.delete(
                    collection="memories",
                    id=task.memory_id
                )
            elif task.operation == "update":
                await ms.vector_store.delete(
                    collection="memories",
                    id=task.memory_id
                )
                await ms.vector_store.add(
                    collection="memories",
                    text=task.data.get("content", ""),
                    metadata=task.data
                )

            return True
        except Exception as e:
            logger.error(f"[MemorySyncService] 向量库操作失败: {e}")
            return False

    def get_sync_status(self, memory_id: str) -> SyncStatus | None:
        """获取同步状态"""
        return self._sync_status.get(memory_id)

    def is_sync_complete(self, memory_id: str) -> bool:
        """检查是否同步完成"""
        status = self._sync_status.get(memory_id)
        return status in [SyncStatus.SUCCESS, SyncStatus.FAILED]


# 便捷函数
_sync_service = None

def get_memory_sync_service() -> MemorySyncService:
    """获取同步服务单例"""
    global _sync_service
    if _sync_service is None:
        _sync_service = MemorySyncService()
    return _sync_service
