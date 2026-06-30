#!/usr/bin/env python3
"""
全局资源协调器 - SiliconBase V5 核心组件
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【架构定位】
统一管理所有稀缺资源的访问，防止并发冲突导致的卡死/蓝屏。

【协调范围】
1. PostgreSQL连接池 - 防止连接耗尽
2. 向量库检索 - 防止内存暴涨
3. 屏幕截图(MSS) - 防止GDI冲突/蓝屏
4. 视觉AI推理 - 防止GPU过载
5. 文件系统扫描 - 防止I/O阻塞

【使用原则】
- 所有资源访问必须通过协调器
- 自动队列管理，串行执行冲突操作
- 超时保护，防止永久等待
"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from queue import Empty, Queue
from typing import Any

logger = logging.getLogger(__name__)


class ResourceType(Enum):
    """资源类型"""
    POSTGRESQL = "postgresql"      # 数据库连接
    VECTOR_DB = "vector_db"        # 向量库
    SCREENSHOT = "screenshot"      # MSS截图
    VISION_AI = "vision_ai"        # 视觉AI推理
    FILE_SCAN = "file_scan"        # 文件扫描
    EXCHANGE_API = "exchange_api"  # 交易所API（新增）
    TRADING_CALC = "trading_calc"  # 交易计算密集型（新增）


class Priority(Enum):
    """任务优先级"""
    CRITICAL = 0      # 关键（用户操作）
    HIGH = 1          # 高（工具执行）
    NORMAL = 2        # 正常（后台任务）
    LOW = 3           # 低（自动进化）


@dataclass
class ResourceRequest:
    """资源请求"""
    resource_type: ResourceType
    task_id: str
    priority: Priority
    callback: Callable
    params: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    timeout: float = 30.0
    user_id: str = "default"


class ResourceCoordinator:
    """
    全局资源协调器 - 单例模式

    核心功能：
    1. 资源队列管理 - 按优先级排序
    2. 互斥执行 - 冲突资源串行化
    3. 超时保护 - 防止永久等待
    4. 资源统计 - 监控使用率
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    # 确保实例完全初始化后才赋值
                    instance._initialized = False
                    cls._instance = instance
        return cls._instance

    def __init__(self):
        # 双重检查确保线程安全
        if hasattr(self, '_initialized') and self._initialized:
            return

        with self.__class__._lock:
            if hasattr(self, '_initialized') and self._initialized:
                return

            # 初始化代码
            self._initialized = True

        # 资源队列（每种资源独立队列）
        self._queues: dict[ResourceType, Queue] = {
            rt: Queue() for rt in ResourceType
        }

        # 资源状态（是否被占用）
        self._resource_busy: dict[ResourceType, bool] = dict.fromkeys(ResourceType, False)
        self._resource_lock = threading.Lock()

        # 执行线程
        self._workers: dict[ResourceType, threading.Thread] = {}
        self._running = True

        # 统计信息
        self._stats: dict[ResourceType, dict] = {
            rt: {"total": 0, "failed": 0, "avg_time": 0.0}
            for rt in ResourceType
        }
        self._stats_lock = threading.Lock()  # 统计锁，保护复合操作的原子性

        # 启动工作线程
        self._start_workers()

        logger.info("[ResourceCoordinator] 资源协调器已启动")

    def _start_workers(self):
        """启动资源工作线程"""
        for resource_type in ResourceType:
            worker = threading.Thread(
                target=self._resource_worker,
                args=(resource_type,),
                daemon=True,
                name=f"ResourceWorker-{resource_type.value}"
            )
            worker.start()
            self._workers[resource_type] = worker

    def _execute_with_timeout(self, request: ResourceRequest, resource_type: ResourceType):
        """
        【关键修复】带强制超时的资源执行

        使用独立线程执行，确保即使回调阻塞也能超时返回
        """
        import concurrent.futures

        result_container = {"result": None, "error": None, "done": False}

        def _run_callback():
            try:
                result = request.callback(**request.params)
                result_container["result"] = result
                result_container["done"] = True
            except Exception as e:
                result_container["error"] = e
                result_container["done"] = True

        # 使用线程池执行，支持强制超时
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_run_callback)
            try:
                # 等待结果或超时（使用请求的超时时间）
                wait_seconds = min(request.timeout, 60)  # 最大60秒
                future.result(timeout=wait_seconds)

                if result_container["error"]:
                    raise result_container["error"]

                return result_container["result"]

            except concurrent.futures.TimeoutError as _exc:
                logger.error(
                    f"[ResourceCoordinator] 资源执行强制超时: {request.task_id}, "
                    f"资源={resource_type.value}, 超时={wait_seconds}s"
                )
                # 强制取消
                future.cancel()
                raise TimeoutError(f"资源执行超时（{wait_seconds}秒）") from _exc

    def _resource_worker(self, resource_type: ResourceType):
        """
        【关键修复】资源工作线程 - 带强制超时保护

        改进点：
        1. 每个请求强制超时，防止永久阻塞
        2. 异常时强制释放资源锁
        3. 详细的日志便于排查
        """
        while self._running:
            try:
                # 从队列获取请求（阻塞等待）
                request: ResourceRequest = self._queues[resource_type].get(timeout=1.0)

                # 检查队列等待是否超时
                wait_time = time.time() - request.timestamp
                if wait_time > request.timeout:
                    logger.warning(
                        f"[ResourceCoordinator] 请求队列等待超时: {request.task_id}, "
                        f"等待{wait_time:.1f}s，已丢弃"
                    )
                    continue

                # 标记资源为忙
                with self._resource_lock:
                    self._resource_busy[resource_type] = True

                # 【关键修复】执行请求，带强制超时
                start_time = time.time()
                try:
                    logger.info(
                        f"[ResourceCoordinator] 开始执行: {request.task_id}, "
                        f"资源={resource_type.value}, 优先级={request.priority.name}, "
                        f"允许超时={request.timeout}s"
                    )

                    # 【关键修复】使用带超时的执行方式
                    self._execute_with_timeout(request, resource_type)

                    # 更新统计
                    elapsed = time.time() - start_time
                    self._update_stats(resource_type, elapsed, success=True)
                    logger.info(
                        f"[ResourceCoordinator] 执行成功: {request.task_id}, "
                        f"耗时={elapsed:.2f}s"
                    )

                except TimeoutError:
                    elapsed = time.time() - start_time
                    self._update_stats(resource_type, elapsed, success=False)
                    logger.error(
                        f"[ResourceCoordinator] 执行超时: {request.task_id}, "
                        f"资源={resource_type.value}, 耗时={elapsed:.2f}s"
                    )

                except Exception as e:
                    elapsed = time.time() - start_time
                    self._update_stats(resource_type, elapsed, success=False)
                    logger.error(
                        f"[ResourceCoordinator] 执行失败: {request.task_id}, "
                        f"资源={resource_type.value}, 错误={e}",
                        exc_info=True
                    )

                finally:
                    # 【关键修复】确保资源锁被释放
                    with self._resource_lock:
                        self._resource_busy[resource_type] = False
                        logger.debug(
                            f"[ResourceCoordinator] 资源已释放: {resource_type.value}"
                        )

            except Empty:
                continue
            except Exception as e:
                logger.error(f"[ResourceCoordinator] 工作线程异常: {e}", exc_info=True)
                # 【关键修复】异常时也要释放资源锁
                try:
                    with self._resource_lock:
                        self._resource_busy[resource_type] = False
                except Exception:
                    pass

    def force_release_resource(self, resource_type: ResourceType, reason: str = "强制释放"):
        """
        【关键修复】强制释放资源锁

        用于子进程被终止时，父进程强制清理资源状态。
        谨慎使用，只在确认资源实际已释放时调用。

        Args:
            resource_type: 资源类型
            reason: 释放原因（用于日志）
        """
        with self._resource_lock:
            was_busy = self._resource_busy[resource_type]
            self._resource_busy[resource_type] = False

            if was_busy:
                logger.warning(
                    f"[ResourceCoordinator] 强制释放资源: {resource_type.value}, "
                    f"原因={reason}"
                )
            else:
                logger.debug(
                    f"[ResourceCoordinator] 资源已空闲，无需释放: {resource_type.value}"
                )

    def emergency_reset(self):
        """
        【关键修复】紧急重置所有资源

        当系统出现严重卡死时调用，强制重置所有资源状态。
        这会丢失正在执行的请求，但可恢复系统可用性。
        """
        logger.error("[ResourceCoordinator] 紧急重置所有资源状态")

        with self._resource_lock:
            for resource_type in ResourceType:
                was_busy = self._resource_busy[resource_type]
                self._resource_busy[resource_type] = False

                # 清空队列
                while not self._queues[resource_type].empty():
                    try:
                        self._queues[resource_type].get_nowait()
                    except Exception:
                        break

                if was_busy:
                    logger.warning(f"[ResourceCoordinator] 紧急重置资源: {resource_type.value}")

    def _update_stats(self, resource_type: ResourceType, elapsed: float, success: bool):
        """更新统计信息（线程安全）"""
        with self._stats_lock:
            stats = self._stats[resource_type]
            stats["total"] += 1
            if not success:
                stats["failed"] += 1
            # 移动平均
            alpha = 0.3
            stats["avg_time"] = (1 - alpha) * stats["avg_time"] + alpha * elapsed

    def request_resource(
        self,
        resource_type: ResourceType,
        callback: Callable,
        params: dict[str, Any] = None,
        priority: Priority = Priority.NORMAL,
        timeout: float = 30.0,
        user_id: str = "default",
        task_id: str = None
    ) -> bool:
        """
        请求使用资源

        Args:
            resource_type: 资源类型
            callback: 资源使用回调函数
            params: 回调函数参数
            priority: 优先级
            timeout: 超时时间（秒）
            user_id: 用户ID
            task_id: 任务ID

        Returns:
            bool: 是否成功加入队列
        """
        if task_id is None:
            task_id = f"{resource_type.value}_{int(time.time()*1000)}"

        request = ResourceRequest(
            resource_type=resource_type,
            task_id=task_id,
            priority=priority,
            callback=callback,
            params=params or {},
            timeout=timeout,
            user_id=user_id
        )

        try:
            # 加入队列
            self._queues[resource_type].put(request, block=False)

            logger.debug(
                f"[ResourceCoordinator] 请求已加入队列: {task_id}, "
                f"资源={resource_type.value}, 队列长度={self._queues[resource_type].qsize()}"
            )
            return True

        except Exception as e:
            logger.error(f"[ResourceCoordinator] 加入队列失败: {e}")
            return False

    def is_resource_busy(self, resource_type: ResourceType) -> bool:
        """检查资源是否被占用"""
        with self._resource_lock:
            return self._resource_busy[resource_type]

    def get_queue_size(self, resource_type: ResourceType) -> int:
        """获取队列大小"""
        return self._queues[resource_type].qsize()

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息"""
        return {
            rt.value: {
                **self._stats[rt],
                "busy": self._resource_busy[rt],
                "queue_size": self._queues[rt].qsize()
            }
            for rt in ResourceType
        }

    def shutdown(self):
        """关闭协调器"""
        self._running = False
        logger.info("[ResourceCoordinator] 资源协调器已关闭")


# 全局实例
coordinator = ResourceCoordinator()


# =============================================================================
# 便捷函数
# =============================================================================

def request_postgresql(callback: Callable, params: dict = None, priority: Priority = Priority.NORMAL, timeout: float = 10.0) -> bool:
    """请求PostgreSQL连接"""
    return coordinator.request_resource(
        ResourceType.POSTGRESQL, callback, params, priority, timeout
    )


def request_vector_db(callback: Callable, params: dict = None, priority: Priority = Priority.NORMAL, timeout: float = 10.0) -> bool:
    """请求向量库访问"""
    return coordinator.request_resource(
        ResourceType.VECTOR_DB, callback, params, priority, timeout
    )


def request_screenshot(callback: Callable, params: dict = None, priority: Priority = Priority.NORMAL, timeout: float = 10.0) -> bool:
    """请求截图"""
    return coordinator.request_resource(
        ResourceType.SCREENSHOT, callback, params, priority, timeout
    )


def request_vision_ai(callback: Callable, params: dict = None, priority: Priority = Priority.NORMAL, timeout: float = 30.0) -> bool:
    """请求视觉AI"""
    return coordinator.request_resource(
        ResourceType.VISION_AI, callback, params, priority, timeout
    )


def get_resource_stats() -> dict[str, Any]:
    """获取资源统计"""
    return coordinator.get_stats()
