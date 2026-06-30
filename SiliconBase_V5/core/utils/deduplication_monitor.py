#!/usr/bin/env python3
"""
数据去重监控器 - DeduplicationMonitor

Week 3 数据去重组件 - 监控和统计模块

功能特性:
- 实时监控去重效果
- 内存使用监控
- 命中率统计
- 零静默失败原则：所有错误都记录日志

使用方式:
    monitor = DeduplicationMonitor()
    stats = monitor.get_stats()
    print(f"缓存命中率: {stats['visual_cache_hit_rate']:.2%}")
"""

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from core.config import config
from core.logger import logger
from core.vision.visual_analysis_cache import get_visual_analysis_cache


@dataclass
class CacheMetrics:
    """缓存指标数据类"""
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    errors: int = 0
    last_updated: float = field(default_factory=time.time)

    @property
    def total_requests(self) -> int:
        """总请求数"""
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        """命中率"""
        if self.total_requests == 0:
            return 0.0
        return self.hits / self.total_requests

    @property
    def miss_rate(self) -> float:
        """未命中率"""
        return 1.0 - self.hit_rate


class DeduplicationMonitor:
    """
    去重效果监控器

    职责:
    1. 监控VisualAnalysisCache的运行状态
    2. 收集和统计去重效果数据
    3. 内存使用监控和告警
    4. 生成去重效果报告
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

        # 缓存引用
        self._visual_cache = get_visual_analysis_cache()

        # 配置
        self._enabled = config.get("deduplication.monitoring.enabled", True)
        self._memory_threshold_mb = config.get("deduplication.monitoring.memory_threshold_mb", 200)
        self._hit_rate_alert_threshold = config.get(
            "deduplication.monitoring.hit_rate_alert_threshold", 0.1
        )

        # 指标统计
        self._metrics = CacheMetrics()
        self._metrics_lock = threading.RLock()

        # 历史记录（用于趋势分析）
        self._history: list = []
        self._max_history_size = 100

        # 告警状态
        self._last_memory_alert = 0
        self._memory_alert_cooldown = 300  # 5分钟冷却

        self._initialized = True
        logger.info("[DeduplicationMonitor] 初始化完成")

    def record_hit(self, user_id: str = ""):
        """记录缓存命中"""
        if not self._enabled:
            return

        with self._metrics_lock:
            self._metrics.hits += 1
            self._metrics.last_updated = time.time()

    def record_miss(self, user_id: str = ""):
        """记录缓存未命中"""
        if not self._enabled:
            return

        with self._metrics_lock:
            self._metrics.misses += 1
            self._metrics.last_updated = time.time()

    def record_eviction(self, user_id: str = "", reason: str = ""):
        """记录缓存淘汰"""
        if not self._enabled:
            return

        with self._metrics_lock:
            self._metrics.evictions += 1
            logger.debug(f"[DeduplicationMonitor] 缓存淘汰: user={user_id}, reason={reason}")

    def record_error(self, operation: str, error: str):
        """记录错误"""
        with self._metrics_lock:
            self._metrics.errors += 1
            logger.error(f"[DeduplicationMonitor] 错误: operation={operation}, error={error}")

    def get_visual_cache_stats(self) -> dict[str, Any]:
        """
        获取视觉分析缓存统计

        Returns:
            Dict: 缓存统计信息
        """
        try:
            cache_stats = self._visual_cache.get_stats()

            # 计算内存估算（每个缓存项约10KB估算）
            total_entries = cache_stats.get("total_entries", 0)
            estimated_memory_kb = total_entries * 10
            estimated_memory_mb = estimated_memory_kb / 1024

            return {
                "total_users": cache_stats.get("total_users", 0),
                "total_entries": total_entries,
                "max_users": cache_stats.get("max_users", 100),
                "max_cache_per_user": cache_stats.get("max_cache_per_user", 50),
                "avg_entries_per_user": cache_stats.get("avg_entries_per_user", 0),
                "estimated_memory_kb": estimated_memory_kb,
                "estimated_memory_mb": round(estimated_memory_mb, 2)
            }
        except Exception as e:
            logger.error(f"[DeduplicationMonitor] 获取缓存统计失败: {e}")
            self.record_error("get_visual_cache_stats", str(e))
            return {}

    def get_hit_rate_stats(self) -> dict[str, Any]:
        """
        获取命中率统计

        Returns:
            Dict: 命中率统计
        """
        with self._metrics_lock:
            total = self._metrics.total_requests

            return {
                "hits": self._metrics.hits,
                "misses": self._metrics.misses,
                "total_requests": total,
                "hit_rate": round(self._metrics.hit_rate, 4),
                "hit_rate_percent": f"{self._metrics.hit_rate:.2%}",
                "miss_rate": round(self._metrics.miss_rate, 4),
                "evictions": self._metrics.evictions,
                "errors": self._metrics.errors,
                "last_updated": datetime.fromtimestamp(
                    self._metrics.last_updated
                ).isoformat() if self._metrics.last_updated > 0 else None
            }

    def check_memory_threshold(self) -> dict[str, Any]:
        """
        检查内存使用是否超过阈值

        Returns:
            Dict: 内存检查结果
        """
        cache_stats = self.get_visual_cache_stats()
        memory_mb = cache_stats.get("estimated_memory_mb", 0)

        exceeded = memory_mb > self._memory_threshold_mb

        result = {
            "memory_mb": memory_mb,
            "threshold_mb": self._memory_threshold_mb,
            "exceeded": exceeded,
            "usage_percent": round(memory_mb / self._memory_threshold_mb * 100, 2) if self._memory_threshold_mb > 0 else 0
        }

        # 触发告警（带冷却）
        if exceeded:
            current_time = time.time()
            if current_time - self._last_memory_alert > self._memory_alert_cooldown:
                self._last_memory_alert = current_time
                logger.warning(
                    f"[DeduplicationMonitor] 内存使用告警: "
                    f"{memory_mb:.2f}MB > {self._memory_threshold_mb}MB"
                )
                result["alert_triggered"] = True
            else:
                result["alert_triggered"] = False
        else:
            result["alert_triggered"] = False

        return result

    def get_stats(self) -> dict[str, Any]:
        """
        获取完整的去重监控统计

        Returns:
            Dict: 包含所有监控指标的字典
        """
        try:
            # 基础统计
            hit_stats = self.get_hit_rate_stats()
            cache_stats = self.get_visual_cache_stats()
            memory_check = self.check_memory_threshold()

            # 计算避免的重复调用数
            duplicate_calls_avoided = hit_stats.get("hits", 0)

            # 组装完整统计
            stats = {
                "timestamp": datetime.now().isoformat(),
                "monitor_enabled": self._enabled,
                "visual_cache": {
                    **cache_stats,
                    **hit_stats,
                    "duplicate_calls_avoided": duplicate_calls_avoided,
                    "memory_status": "normal" if not memory_check["exceeded"] else "warning"
                },
                "memory_check": memory_check,
                "config": {
                    "memory_threshold_mb": self._memory_threshold_mb,
                    "hit_rate_alert_threshold": self._hit_rate_alert_threshold
                }
            }

            # 保存到历史记录
            self._add_to_history(stats)

            return stats

        except Exception as e:
            logger.error(f"[DeduplicationMonitor] 获取统计失败: {e}")
            self.record_error("get_stats", str(e))
            return {
                "timestamp": datetime.now().isoformat(),
                "error": str(e),
                "monitor_enabled": self._enabled
            }

    def _add_to_history(self, stats: dict[str, Any]):
        """添加统计到历史记录"""
        with self._metrics_lock:
            self._history.append(stats)
            if len(self._history) > self._max_history_size:
                self._history.pop(0)

    def get_history(self, limit: int = 10) -> list:
        """
        获取历史统计记录

        Args:
            limit: 返回记录数限制

        Returns:
            list: 历史统计记录
        """
        with self._metrics_lock:
            return self._history[-limit:] if limit > 0 else self._history.copy()

    def get_report(self) -> str:
        """
        生成去重效果报告

        Returns:
            str: 格式化的报告文本
        """
        stats = self.get_stats()
        visual = stats.get("visual_cache", {})

        report = f"""
=====================================
    数据去重效果报告
=====================================
生成时间: {stats.get('timestamp')}
监控状态: {'启用' if stats.get('monitor_enabled') else '禁用'}

【缓存统计】
- 用户数: {visual.get('total_users', 0)} / {visual.get('max_users', 100)}
- 缓存项数: {visual.get('total_entries', 0)}
- 平均每用户: {visual.get('avg_entries_per_user', 0):.2f}

【命中率统计】
- 命中次数: {visual.get('hits', 0)}
- 未命中次数: {visual.get('misses', 0)}
- 总请求数: {visual.get('total_requests', 0)}
- 命中率: {visual.get('hit_rate_percent', '0.00%')}

【去重效果】
- 避免重复调用: {visual.get('duplicate_calls_avoided', 0)} 次

【内存使用】
- 预估内存: {visual.get('estimated_memory_mb', 0):.2f} MB
- 阈值: {stats.get('config', {}).get('memory_threshold_mb', 200)} MB
- 状态: {visual.get('memory_status', 'unknown')}

=====================================
"""
        return report

    def reset_metrics(self):
        """重置指标统计"""
        with self._metrics_lock:
            self._metrics = CacheMetrics()
            self._history.clear()
            logger.info("[DeduplicationMonitor] 指标已重置")

    def health_check(self) -> dict[str, Any]:
        """
        健康检查

        Returns:
            Dict: 健康状态
        """
        try:
            self.get_visual_cache_stats()
            hit_stats = self.get_hit_rate_stats()
            memory_check = self.check_memory_threshold()

            issues = []

            # 检查内存
            if memory_check.get("exceeded", False):
                issues.append("memory_exceeded")

            # 检查命中率（如果请求数足够多）
            if hit_stats.get("total_requests", 0) > 100:
                hit_rate = hit_stats.get("hit_rate", 0)
                if hit_rate < self._hit_rate_alert_threshold:
                    issues.append(f"low_hit_rate: {hit_rate:.2%}")

            # 检查错误率
            if hit_stats.get("errors", 0) > 10:
                issues.append(f"high_error_count: {hit_stats.get('errors')}")

            return {
                "status": "healthy" if not issues else "warning",
                "issues": issues,
                "timestamp": datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"[DeduplicationMonitor] 健康检查失败: {e}")
            return {
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }


# 便捷函数
def get_deduplication_monitor() -> DeduplicationMonitor:
    """获取去重监控器单例"""
    return DeduplicationMonitor()


def get_deduplication_stats() -> dict[str, Any]:
    """获取去重统计（便捷函数）"""
    return DeduplicationMonitor().get_stats()


def print_deduplication_report():
    """打印去重报告（便捷函数）"""
    print(DeduplicationMonitor().get_report())


# 零静默失败原则：模块加载时记录状态
logger.info("[deduplication_monitor] 模块加载完成，版本: Week 3")
