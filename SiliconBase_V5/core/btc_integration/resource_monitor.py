#!/usr/bin/env python3
"""
资源监控器 - Resource Monitor
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
监控系统资源使用情况，防止内存泄漏和资源耗尽

功能:
- 监控内存使用率
- 监控文件句柄数
- 监控线程数
- 定期强制垃圾回收
- 超过阈值时清理历史数据

作者: SiliconBase V5 AI Agent
日期: 2026-04-09
"""

import contextlib
import gc
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from core.logger import logger

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


class ResourceAlertLevel(Enum):
    """资源警报级别"""
    NORMAL = "normal"       # 正常
    WARNING = "warning"     # 警告
    CRITICAL = "critical"   # 严重


@dataclass
class ResourceSnapshot:
    """资源快照"""
    timestamp: datetime
    memory_percent: float
    memory_used_mb: float
    memory_available_mb: float
    cpu_percent: float
    thread_count: int
    file_handles: int
    gc_objects: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "memory_percent": round(self.memory_percent, 2),
            "memory_used_mb": round(self.memory_used_mb, 2),
            "memory_available_mb": round(self.memory_available_mb, 2),
            "cpu_percent": round(self.cpu_percent, 2),
            "thread_count": self.thread_count,
            "file_handles": self.file_handles,
            "gc_objects": self.gc_objects
        }


@dataclass
class ResourceThresholds:
    """资源阈值配置"""
    memory_warning: float = 70.0      # 内存警告阈值 (%)
    memory_critical: float = 85.0     # 内存严重阈值 (%)
    file_handles_warning: int = 500   # 文件句柄警告
    file_handles_critical: int = 1000 # 文件句柄严重
    thread_warning: int = 50          # 线程数警告
    thread_critical: int = 100        # 线程数严重


class ResourceMonitor:
    """
    资源监控器

    使用示例:
        monitor = ResourceMonitor(
            max_memory_percent=80,
            cleanup_interval=3600
        )

        # 启动监控
        monitor.start_monitoring()

        # 稍后停止
        monitor.stop_monitoring()
    """

    def __init__(
        self,
        max_memory_percent: float = 80.0,
        max_file_handles: int = 1000,
        cleanup_interval: int = 3600,  # 1小时
        check_interval: int = 60,      # 1分钟检查一次
        auto_gc: bool = True
    ):
        """
        初始化资源监控器

        Args:
            max_memory_percent: 内存使用率阈值
            max_file_handles: 文件句柄阈值
            cleanup_interval: 清理间隔（秒）
            check_interval: 检查间隔（秒）
            auto_gc: 是否自动垃圾回收
        """
        self.max_memory_percent = max_memory_percent
        self.max_file_handles = max_file_handles
        self.cleanup_interval = cleanup_interval
        self.check_interval = check_interval
        self.auto_gc = auto_gc

        self._thresholds = ResourceThresholds()

        # 监控控制
        self._monitoring = False
        self._monitor_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        # 快照历史
        self._snapshots: list[ResourceSnapshot] = []
        self._max_snapshots = 1440  # 保留24小时（每分钟一个）

        # 警报回调
        self._alert_callbacks: list[Callable[[ResourceAlertLevel, str, dict], None]] = []

        # 上次清理时间
        self._last_cleanup = datetime.now()

        # 进程信息（缓存）
        self._process = None
        if PSUTIL_AVAILABLE:
            with contextlib.suppress(Exception):
                self._process = psutil.Process(os.getpid())

        self._log_prefix = "[ResourceMonitor]"

    def _log(self, level: str, message: str):
        """记录日志"""
        log_func = getattr(logger, level, logger.info)
        log_func(f"{self._log_prefix} {message}")

    # ═══════════════════════════════════════════════════════════════
    # 核心控制方法
    # ═══════════════════════════════════════════════════════════════

    def start_monitoring(self) -> bool:
        """
        启动资源监控

        Returns:
            bool: 是否成功启动
        """
        if self._monitoring:
            self._log("warning", "监控已在运行中")
            return False

        self._log("info", "启动资源监控")

        self._stop_event.clear()
        self._monitoring = True

        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="ResourceMonitor"
        )
        self._monitor_thread.start()

        return True

    def stop_monitoring(self) -> bool:
        """
        停止资源监控

        Returns:
            bool: 是否成功停止
        """
        if not self._monitoring:
            return True

        self._log("info", "停止资源监控")

        self._stop_event.set()
        self._monitoring = False

        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=5)

        return True

    def register_alert_callback(self, callback: Callable[[ResourceAlertLevel, str, dict], None]):
        """注册警报回调"""
        self._alert_callbacks.append(callback)

    # ═══════════════════════════════════════════════════════════════
    # 监控循环
    # ═══════════════════════════════════════════════════════════════

    def _monitor_loop(self):
        """监控循环"""
        self._log("info", "监控循环启动")

        while self._monitoring and not self._stop_event.is_set():
            try:
                # 采集资源快照
                snapshot = self._collect_snapshot()
                if snapshot:
                    self._snapshots.append(snapshot)

                    # 限制历史记录数量
                    if len(self._snapshots) > self._max_snapshots:
                        self._snapshots = self._snapshots[-self._max_snapshots:]

                    # 检查阈值
                    self._check_thresholds(snapshot)

                # 检查是否需要清理
                if self._should_cleanup():
                    self._cleanup_resources()

                # 等待下一次检查
                if self._stop_event.wait(self.check_interval):
                    break

            except Exception as e:
                self._log("error", f"监控循环异常: {e}")
                time.sleep(5)

        self._log("info", "监控循环结束")
        self._monitoring = False

    def _collect_snapshot(self) -> ResourceSnapshot | None:
        """采集资源快照"""
        try:
            # 内存信息
            if PSUTIL_AVAILABLE and self._process:
                memory_info = self._process.memory_info()
                memory_percent = self._process.memory_percent()
                memory_used_mb = memory_info.rss / 1024 / 1024

                # 系统内存
                system_memory = psutil.virtual_memory()
                memory_available_mb = system_memory.available / 1024 / 1024

                # CPU
                cpu_percent = self._process.cpu_percent(interval=0.1)

                # 线程数
                thread_count = self._process.num_threads()

                # 文件句柄（近似值）
                try:
                    file_handles = len(self._process.open_files())
                except Exception:
                    file_handles = 0
            else:
                # 使用sys和gc获取基本信息
                memory_percent = 0.0
                memory_used_mb = 0.0
                memory_available_mb = 0.0
                cpu_percent = 0.0
                thread_count = threading.active_count()
                file_handles = 0

            # GC对象数
            gc_objects = len(gc.get_objects())

            return ResourceSnapshot(
                timestamp=datetime.now(),
                memory_percent=memory_percent,
                memory_used_mb=memory_used_mb,
                memory_available_mb=memory_available_mb,
                cpu_percent=cpu_percent,
                thread_count=thread_count,
                file_handles=file_handles,
                gc_objects=gc_objects
            )

        except Exception as e:
            self._log("error", f"采集快照失败: {e}")
            return None

    def _check_thresholds(self, snapshot: ResourceSnapshot):
        """检查阈值"""
        # 内存检查
        if snapshot.memory_percent >= self._thresholds.memory_critical:
            self._trigger_alert(
                ResourceAlertLevel.CRITICAL,
                f"内存使用率严重: {snapshot.memory_percent:.1f}%",
                {"memory_percent": snapshot.memory_percent}
            )
        elif snapshot.memory_percent >= self._thresholds.memory_warning:
            self._trigger_alert(
                ResourceAlertLevel.WARNING,
                f"内存使用率警告: {snapshot.memory_percent:.1f}%",
                {"memory_percent": snapshot.memory_percent}
            )

        # 文件句柄检查
        if snapshot.file_handles >= self._thresholds.file_handles_critical:
            self._trigger_alert(
                ResourceAlertLevel.CRITICAL,
                f"文件句柄严重: {snapshot.file_handles}",
                {"file_handles": snapshot.file_handles}
            )
        elif snapshot.file_handles >= self._thresholds.file_handles_warning:
            self._trigger_alert(
                ResourceAlertLevel.WARNING,
                f"文件句柄警告: {snapshot.file_handles}",
                {"file_handles": snapshot.file_handles}
            )

        # 线程数检查
        if snapshot.thread_count >= self._thresholds.thread_critical:
            self._trigger_alert(
                ResourceAlertLevel.CRITICAL,
                f"线程数严重: {snapshot.thread_count}",
                {"thread_count": snapshot.thread_count}
            )
        elif snapshot.thread_count >= self._thresholds.thread_warning:
            self._trigger_alert(
                ResourceAlertLevel.WARNING,
                f"线程数警告: {snapshot.thread_count}",
                {"thread_count": snapshot.thread_count}
            )

    def _trigger_alert(self, level: ResourceAlertLevel, message: str, data: dict):
        """触发警报"""
        self._log("warning" if level == ResourceAlertLevel.WARNING else "error", message)

        for callback in self._alert_callbacks:
            try:
                callback(level, message, data)
            except Exception as e:
                self._log("error", f"警报回调异常: {e}")

    # ═══════════════════════════════════════════════════════════════
    # 资源清理
    # ═══════════════════════════════════════════════════════════════

    def _should_cleanup(self) -> bool:
        """检查是否需要清理"""
        elapsed = (datetime.now() - self._last_cleanup).total_seconds()
        return elapsed >= self.cleanup_interval

    def _cleanup_resources(self):
        """清理资源"""
        self._log("info", "执行资源清理...")

        try:
            # 1. 强制垃圾回收
            if self.auto_gc:
                gc.collect()
                self._log("info", "垃圾回收完成")

            # 2. 清理旧快照（只保留最近12小时）
            cutoff = datetime.now() - timedelta(hours=12)
            old_count = len(self._snapshots)
            self._snapshots = [
                s for s in self._snapshots
                if s.timestamp > cutoff
            ]
            new_count = len(self._snapshots)
            if old_count != new_count:
                self._log("info", f"清理旧快照: {old_count - new_count} 个")

            # 3. 如果内存仍然很高，尝试更激进的清理
            if PSUTIL_AVAILABLE and self._process:
                memory_percent = self._process.memory_percent()
                if memory_percent > self.max_memory_percent:
                    self._aggressive_cleanup()

            self._last_cleanup = datetime.now()
            self._log("info", "资源清理完成")

        except Exception as e:
            self._log("error", f"资源清理异常: {e}")

    def _aggressive_cleanup(self):
        """激进的清理策略"""
        self._log("warning", "执行激进清理...")

        try:
            # 1. 多次GC
            for _ in range(3):
                gc.collect()

            # 2. 清空更多历史数据
            if len(self._snapshots) > 60:  # 只保留最近1小时
                self._snapshots = self._snapshots[-60:]

            self._log("info", "激进清理完成")

        except Exception as e:
            self._log("error", f"激进清理异常: {e}")

    def force_cleanup(self) -> dict[str, Any]:
        """
        强制立即清理

        Returns:
            Dict: 清理结果
        """
        self._log("info", "强制清理触发")

        before = self._collect_snapshot()
        self._cleanup_resources()
        after = self._collect_snapshot()

        result = {
            "before": before.to_dict() if before else None,
            "after": after.to_dict() if after else None,
            "snapshots_cleaned": len(self._snapshots) < self._max_snapshots
        }

        if before and after:
            memory_diff = before.memory_used_mb - after.memory_used_mb
            result["memory_freed_mb"] = round(memory_diff, 2)

        return result

    # ═══════════════════════════════════════════════════════════════
    # 查询接口
    # ═══════════════════════════════════════════════════════════════

    def get_current_status(self) -> dict[str, Any]:
        """获取当前资源状态"""
        snapshot = self._collect_snapshot()

        if not snapshot:
            return {"error": "无法采集资源信息"}

        # 计算趋势
        trend = self._calculate_trend()

        return {
            "current": snapshot.to_dict(),
            "trend": trend,
            "thresholds": {
                "memory_warning": self._thresholds.memory_warning,
                "memory_critical": self._thresholds.memory_critical,
                "file_handles_warning": self._thresholds.file_handles_warning,
                "file_handles_critical": self._thresholds.file_handles_critical
            },
            "is_monitoring": self._monitoring
        }

    def _calculate_trend(self) -> dict[str, str]:
        """计算资源使用趋势"""
        if len(self._snapshots) < 10:
            return {"memory": "unknown", "threads": "unknown"}

        recent = self._snapshots[-10:]
        older = self._snapshots[-20:-10] if len(self._snapshots) >= 20 else self._snapshots[:10]

        # 内存趋势
        recent_memory = sum(s.memory_percent for s in recent) / len(recent)
        older_memory = sum(s.memory_percent for s in older) / len(older)

        memory_diff = recent_memory - older_memory
        if memory_diff > 5:
            memory_trend = "increasing"
        elif memory_diff < -5:
            memory_trend = "decreasing"
        else:
            memory_trend = "stable"

        # 线程趋势
        recent_threads = sum(s.thread_count for s in recent) / len(recent)
        older_threads = sum(s.thread_count for s in older) / len(older)

        thread_diff = recent_threads - older_threads
        if thread_diff > 5:
            thread_trend = "increasing"
        elif thread_diff < -5:
            thread_trend = "decreasing"
        else:
            thread_trend = "stable"

        return {
            "memory": memory_trend,
            "memory_change": round(memory_diff, 2),
            "threads": thread_trend,
            "thread_change": round(thread_diff, 2)
        }

    def get_history(self, hours: int = 1) -> list[dict[str, Any]]:
        """获取历史快照"""
        cutoff = datetime.now() - timedelta(hours=hours)
        snapshots = [s for s in self._snapshots if s.timestamp > cutoff]
        return [s.to_dict() for s in snapshots]


# ═══════════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════════

def create_default_monitor() -> ResourceMonitor:
    """创建默认配置的监控器"""
    return ResourceMonitor(
        max_memory_percent=80.0,
        max_file_handles=1000,
        cleanup_interval=3600,  # 1小时
        check_interval=60,      # 1分钟
        auto_gc=True
    )
