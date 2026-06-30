#!/usr/bin/env python3
"""
增强功能统一降级框架
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

设计原则（Phase 2 规则）：
1. 统一代码风格 - 遵循项目现有规范
2. 函数调用正确 - 显式参数，不用隐式全局状态
3. 返回值规范 - Optional[T] 表示可空
4. 空保护不静默 - 空值前记录 warning
5. 不竞争资源 - RLock 保护共享数据
6. 不引入新bug - 独立文件，隔离风险
7. 实例复用 - 单例模式
8. 线程池安全 - 统一管理

使用示例:
    @with_fallback("perception_semantic")
    def should_trigger_semantic(user_input: str, context: Dict) -> Optional[TriggerDecision]:
        # V1.1 增强实现
        ...

    # V1.0 基础实现
    def should_trigger_base(user_input: str, context: Dict) -> TriggerDecision:
        ...
"""

import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from functools import wraps
from typing import Any, Optional, TypeVar


# 延迟导入避免循环依赖
def _get_logger():
    try:
        from core.logger import logger
        return logger
    except ImportError:
        import logging
        return logging.getLogger('enhancement_fallback')


T = TypeVar('T')


class FallbackReason(Enum):
    """降级原因枚举"""
    DISABLED = "disabled"           # 功能被禁用
    EXCEPTION = "exception"         # 异常触发
    TIMEOUT = "timeout"             # 超时触发
    INVALID_RESULT = "invalid"      # 结果无效
    RESOURCE_UNAVAILABLE = "resource"  # 资源不可用


@dataclass
class FallbackStats:
    """降级统计数据"""
    feature_name: str
    total_calls: int = 0
    enhanced_calls: int = 0
    fallback_calls: int = 0
    last_fallback_reason: str | None = None
    last_fallback_time: float | None = None
    avg_enhanced_latency_ms: float = 0.0

    def record_call(self, used_enhanced: bool, latency_ms: float = 0.0):
        """记录调用"""
        self.total_calls += 1
        if used_enhanced:
            self.enhanced_calls += 1
            # 更新平均延迟
            n = self.enhanced_calls
            self.avg_enhanced_latency_ms = (
                (self.avg_enhanced_latency_ms * (n - 1) + latency_ms) / n
                if n > 0 else latency_ms
            )
        else:
            self.fallback_calls += 1

    def record_fallback(self, reason: FallbackReason):
        """记录降级"""
        self.last_fallback_reason = reason.value
        self.last_fallback_time = time.time()

    @property
    def fallback_rate(self) -> float:
        """降级率"""
        if self.total_calls == 0:
            return 0.0
        return self.fallback_calls / self.total_calls


class FallbackStatsManager:
    """
    降级统计管理器

    【线程安全】使用 RLock 保护统计数据
    【单例模式】全局唯一实例
    """

    _instance: Optional['FallbackStatsManager'] = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        self._initialized = True

        # 线程锁保护统计数据
        self._lock = threading.RLock()
        self._stats: dict[str, FallbackStats] = {}

        _get_logger().info("[FallbackStatsManager] 初始化完成")

    def get_stats(self, feature_name: str) -> FallbackStats:
        """
        获取功能统计

        【线程安全】自动创建统计对象
        """
        with self._lock:
            if feature_name not in self._stats:
                self._stats[feature_name] = FallbackStats(feature_name=feature_name)
            return self._stats[feature_name]

    def get_all_stats(self) -> dict[str, dict[str, Any]]:
        """获取所有统计"""
        with self._lock:
            return {
                name: {
                    "total_calls": s.total_calls,
                    "enhanced_calls": s.enhanced_calls,
                    "fallback_calls": s.fallback_calls,
                    "fallback_rate": s.fallback_rate,
                    "last_fallback_reason": s.last_fallback_reason,
                    "avg_latency_ms": round(s.avg_enhanced_latency_ms, 2)
                }
                for name, s in self._stats.items()
            }


# 全局统计管理器
_stats_manager: FallbackStatsManager | None = None
_stats_manager_lock = threading.Lock()


def get_stats_manager() -> FallbackStatsManager:
    """获取统计管理器（线程安全）"""
    global _stats_manager
    if _stats_manager is None:
        with _stats_manager_lock:
            if _stats_manager is None:
                _stats_manager = FallbackStatsManager()
    return _stats_manager


def with_fallback(
    feature_name: str,
    timeout_ms: int | None = None,
    default_on_error: Any | None = None
):
    """
    降级装饰器

    【规则遵守】
    1. 显式参数传递 - feature_name, timeout_ms
    2. 返回值规范 - 返回 Optional[T] 或 default_on_error
    3. 空保护不静默 - 降级时记录 warning
    4. 线程安全 - 使用 stats_manager 记录统计

    Args:
        feature_name: 功能名称（用于统计和开关控制）
        timeout_ms: 超时时间（毫秒），None 表示不超时
        default_on_error: 增强失败时的默认值

    Returns:
        装饰器函数

    Usage:
        @with_fallback("perception_semantic", timeout_ms=500)
        def should_trigger_semantic(user_input: str) -> Optional[TriggerDecision]:
            ...
    """
    def decorator(enhanced_func: Callable[..., T]) -> Callable[..., T | None]:
        @wraps(enhanced_func)
        def wrapper(*args, **kwargs) -> T | None:
            logger = _get_logger()
            stats = get_stats_manager().get_stats(feature_name)

            # 检查功能开关
            env_var = f"ENABLE_{feature_name.upper()}"
            if os.environ.get(env_var, "true").lower() != "true":
                logger.debug(f"[{feature_name}] 功能被禁用，跳过增强")
                stats.record_fallback(FallbackReason.DISABLED)
                return default_on_error

            # 尝试增强功能
            start_time = time.time()
            try:
                # 超时控制
                if timeout_ms is not None:
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                        future = executor.submit(enhanced_func, *args, **kwargs)
                        try:
                            result = future.result(timeout=timeout_ms / 1000.0)
                        except concurrent.futures.TimeoutError:
                            stats.record_fallback(FallbackReason.TIMEOUT)
                            logger.warning(
                                f"[{feature_name}] 增强功能超时 ({timeout_ms}ms)，降级"
                            )
                            return default_on_error
                else:
                    result = enhanced_func(*args, **kwargs)

                # 检查结果有效性
                if result is None:
                    stats.record_fallback(FallbackReason.INVALID_RESULT)
                    logger.warning(f"[{feature_name}] 增强返回 None，降级")
                    return default_on_error

                # 成功
                latency_ms = (time.time() - start_time) * 1000
                stats.record_call(used_enhanced=True, latency_ms=latency_ms)
                return result

            except Exception as e:
                # 异常降级
                stats.record_fallback(FallbackReason.EXCEPTION)
                logger.warning(
                    f"[{feature_name}] 增强功能异常: {e}，降级",
                    exc_info=False  # 不打印完整堆栈，避免日志污染
                )
                return default_on_error

        # 附加统计信息获取方法
        wrapper.get_stats = lambda: get_stats_manager().get_stats(feature_name)
        return wrapper
    return decorator


def get_enhancement_stats() -> dict[str, Any]:
    """
    获取所有增强功能统计

    【规则遵守】返回值规范，返回完整统计数据
    """
    return get_stats_manager().get_all_stats()


# =============================================================================
# 兼容性别名（保持代码一致性）
# =============================================================================

EnhancementFallback = with_fallback  # 类名风格别名


__all__ = [
    'with_fallback',
    'EnhancementFallback',
    'FallbackReason',
    'FallbackStats',
    'get_enhancement_stats',
    'get_stats_manager',
]
