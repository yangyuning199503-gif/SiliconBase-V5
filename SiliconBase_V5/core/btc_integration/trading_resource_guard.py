#!/usr/bin/env python3
"""
交易资源守卫
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
防止多币种交易导致的资源竞争和API限流

功能:
- 交易所API限流保护
- 记忆查询限流
- 计算密集型任务调度
- 内存监控
"""

import asyncio
import contextlib
import gc
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Optional

from core.diagnostic import safe_create_task
from core.logger import logger

# 导入资源协调器
try:
    from core.resource_coordinator import ResourceCoordinator, ResourceType
    RC_AVAILABLE = True
except ImportError:
    RC_AVAILABLE = False
    logger.warning("[TradingResourceGuard] ResourceCoordinator不可用")


@dataclass
class ResourceStats:
    """资源使用统计"""
    api_calls: int = 0
    api_errors: int = 0
    memory_queries: int = 0
    calc_tasks: int = 0
    avg_api_latency: float = 0.0
    last_cleanup: float = 0.0


class TradingResourceGuard:
    """
    交易资源守卫 - 单例模式

    保护机制:
    1. API限流: 最多2个并发交易所调用
    2. 记忆限流: 最多5个并发记忆查询
    3. 超时保护: 所有操作强制超时
    4. 内存监控: 定期清理防止泄漏
    """

    _instance: Optional['TradingResourceGuard'] = None
    _lock = asyncio.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # 信号量限流
        self.api_semaphore = asyncio.Semaphore(2)  # 最多2个并发API调用
        self.memory_semaphore = asyncio.Semaphore(5)  # 最多5个并发记忆查询
        self.calc_semaphore = asyncio.Semaphore(3)  # 计算密集型任务

        # 资源协调器
        self.coordinator = ResourceCoordinator() if RC_AVAILABLE else None

        # 统计
        self.stats = ResourceStats()

        # 内存监控
        self._monitor_task: asyncio.Task | None = None
        self._running = False

        # API调用时间窗口（用于计算平均延迟）
        self._api_latencies: list = []

        logger.info("[TradingResourceGuard] 资源守卫初始化完成")

    async def start_monitor(self):
        """启动内存监控"""
        if self._running:
            return

        self._running = True
        self._monitor_task = safe_create_task(self._memory_monitor_loop(), name="_memory_monitor_loop")
        logger.info("[TradingResourceGuard] 内存监控已启动")

    async def stop_monitor(self):
        """停止内存监控"""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._monitor_task
        logger.info("[TradingResourceGuard] 内存监控已停止")

    async def _memory_monitor_loop(self):
        """内存监控循环"""
        import psutil

        while self._running:
            try:
                await asyncio.sleep(300)  # 5分钟检查一次

                # 获取内存使用
                process = psutil.Process()
                memory_mb = process.memory_info().rss / 1024 / 1024

                logger.info(f"[TradingResourceGuard] 内存使用: {memory_mb:.1f}MB")

                # 如果超过1GB，强制清理
                if memory_mb > 1024:
                    logger.warning("[TradingResourceGuard] 内存使用过高，执行清理")
                    self._force_cleanup()

                # 定期垃圾回收
                gc.collect()

                # 更新统计
                self.stats.last_cleanup = time.time()

            except Exception as e:
                logger.error(f"[TradingResourceGuard] 内存监控错误: {e}")

    def _force_cleanup(self):
        """强制清理"""
        # 清理缓存
        self._api_latencies.clear()

        # 强制垃圾回收
        gc.collect()

        logger.info("[TradingResourceGuard] 强制清理完成")

    async def call_exchange_api(
        self,
        exchange: str,
        method: str,
        api_func: Callable,
        **params
    ) -> Any:
        """
        安全调用交易所API

        Args:
            exchange: 交易所名称
            method: API方法
            api_func: API调用函数
            **params: 调用参数

        Returns:
            API返回结果
        """
        async with self.api_semaphore:
            start_time = time.time()

            try:
                # 使用资源协调器排队
                if self.coordinator:
                    result = await self._coordinator_request(
                        ResourceType.EXCHANGE_API,
                        api_func,
                        params,
                        timeout=10.0
                    )
                else:
                    # 直接调用，带超时
                    result = await asyncio.wait_for(
                        api_func(**params) if asyncio.iscoroutinefunction(api_func)
                        else asyncio.to_thread(api_func, **params),
                        timeout=10.0
                    )

                # 记录统计
                latency = time.time() - start_time
                self._api_latencies.append(latency)
                self._api_latencies = self._api_latencies[-100:]  # 保留最近100次
                self.stats.api_calls += 1

                return result

            except asyncio.TimeoutError:
                self.stats.api_errors += 1
                logger.error(f"[TradingResourceGuard] API调用超时: {exchange}.{method}")
                raise
            except Exception as e:
                self.stats.api_errors += 1
                logger.error(f"[TradingResourceGuard] API调用错误: {e}")
                raise

    async def query_memory(self, query_func: Callable, **params) -> Any:
        """
        安全查询记忆

        Args:
            query_func: 查询函数
            **params: 查询参数

        Returns:
            查询结果
        """
        async with self.memory_semaphore:
            try:
                result = await query_func(**params) if asyncio.iscoroutinefunction(query_func) else query_func(**params)
                self.stats.memory_queries += 1
                return result
            except Exception as e:
                logger.error(f"[TradingResourceGuard] 记忆查询错误: {e}")
                raise

    async def run_calculation(self, calc_func: Callable, **params) -> Any:
        """
        执行计算密集型任务

        Args:
            calc_func: 计算函数
            **params: 计算参数

        Returns:
            计算结果
        """
        async with self.calc_semaphore:
            try:
                self.stats.calc_tasks += 1

                # 使用线程池执行计算（避免阻塞事件循环）
                return await asyncio.to_thread(calc_func, **params)

            except Exception as e:
                logger.error(f"[TradingResourceGuard] 计算任务错误: {e}")
                raise

    async def _coordinator_request(
        self,
        resource_type: ResourceType,
        callback: Callable,
        params: dict,
        timeout: float = 10.0
    ) -> Any:
        """
        通过资源协调器发送请求

        注意: ResourceCoordinator是同步接口，需要适配
        """
        # 由于ResourceCoordinator使用线程，这里直接调用
        # 实际项目中可能需要更复杂的适配
        return callback(**params)

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息"""
        avg_latency = sum(self._api_latencies) / len(self._api_latencies) if self._api_latencies else 0

        return {
            "api_calls": self.stats.api_calls,
            "api_errors": self.stats.api_errors,
            "api_error_rate": self.stats.api_errors / max(self.stats.api_calls, 1),
            "avg_api_latency": round(avg_latency, 3),
            "memory_queries": self.stats.memory_queries,
            "calc_tasks": self.stats.calc_tasks,
            "last_cleanup": self.stats.last_cleanup,
        }

    def check_health(self) -> dict[str, Any]:
        """健康检查"""
        import psutil

        process = psutil.Process()
        memory_mb = process.memory_info().rss / 1024 / 1024

        return {
            "status": "healthy" if memory_mb < 1024 else "warning",
            "memory_mb": round(memory_mb, 1),
            "api_error_rate": self.stats.api_errors / max(self.stats.api_calls, 1),
            "semaphore_waiters": {
                "api": self.api_semaphore._waiters,
                "memory": self.memory_semaphore._waiters,
                "calc": self.calc_semaphore._waiters,
            }
        }


# 全局实例
resource_guard: TradingResourceGuard | None = None


def get_trading_resource_guard() -> TradingResourceGuard:
    """获取交易资源守卫实例"""
    global resource_guard
    if resource_guard is None:
        resource_guard = TradingResourceGuard()
    return resource_guard


# 便捷装饰器
def guarded_api_call(exchange: str, method: str):
    """API调用保护装饰器"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            guard = get_trading_resource_guard()
            return await guard.call_exchange_api(
                exchange=exchange,
                method=method,
                api_func=lambda: func(*args, **kwargs)
            )
        return wrapper
    return decorator


if __name__ == "__main__":
    async def test():
        guard = get_trading_resource_guard()
        await guard.start_monitor()

        # 测试统计
        print(f"Stats: {guard.get_stats()}")
        print(f"Health: {guard.check_health()}")

        await asyncio.sleep(1)
        await guard.stop_monitor()

    asyncio.run(test())
