#!/usr/bin/env python3
"""
进程守护器 - Process Guardian
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
监控交易进程健康状态，实现崩溃自动重启

功能:
- 监控交易进程健康状态
- 崩溃后自动重启（带指数退避）
- 记录重启历史
- 连续失败达到阈值后停止重启
- 支持健康检查回调

作者: SiliconBase V5 AI Agent
日期: 2026-04-09
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from core.btc_integration.process_manager_v2 import ProcessStatus
from core.logger import logger


class GuardianStatus(Enum):
    """守护器状态"""
    IDLE = "idle"                 # 空闲
    WATCHING = "watching"         # 监控中
    RESTARTING = "restarting"     # 重启中
    FAILED = "failed"             # 失败（达到最大重启次数）
    STOPPED = "stopped"           # 已停止


@dataclass
class RestartRecord:
    """重启记录"""
    timestamp: datetime
    reason: str
    success: bool
    error_message: str = ""


@dataclass
class GuardianStats:
    """守护器统计"""
    watch_start_time: datetime | None = None
    total_restarts: int = 0
    consecutive_failures: int = 0
    last_restart_time: datetime | None = None
    restart_records: list[RestartRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "watch_start_time": self.watch_start_time.isoformat() if self.watch_start_time else None,
            "total_restarts": self.total_restarts,
            "consecutive_failures": self.consecutive_failures,
            "last_restart_time": self.last_restart_time.isoformat() if self.last_restart_time else None,
            "restart_history_count": len(self.restart_records)
        }


class ProcessGuardian:
    """
    进程守护器

    使用示例:
        guardian = ProcessGuardian(
            max_restarts=5,
            restart_delay=30
        )

        # 开始监控
        await guardian.watch_process(
            process_getter=lambda: process_manager,
            health_checker=lambda pm: pm.get_state().status == "running",
            restart_callback=lambda: process_manager.start()
        )

        # 停止监控
        await guardian.stop()
    """

    def __init__(
        self,
        max_restarts: int = 5,
        restart_delay: int = 30,
        exponential_backoff: bool = True,
        max_backoff_delay: int = 300  # 最大退避延迟5分钟
    ):
        """
        初始化进程守护器

        Args:
            max_restarts: 最大重启次数
            restart_delay: 基础重启延迟（秒）
            exponential_backoff: 是否使用指数退避
            max_backoff_delay: 最大退避延迟（秒）
        """
        self.max_restarts = max_restarts
        self.base_restart_delay = restart_delay
        self.exponential_backoff = exponential_backoff
        self.max_backoff_delay = max_backoff_delay

        self._status = GuardianStatus.IDLE
        self._status_lock = threading.RLock()

        # 监控控制
        self._watching = False
        self._watch_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        # 回调函数
        self._process_getter: Callable[[], Any] | None = None
        self._health_checker: Callable[[Any], bool] | None = None
        self._restart_callback: Callable[[], bool] | None = None
        self._on_failure: Callable[[str], None] | None = None

        # 统计
        self._stats = GuardianStats()

        # 配置
        self._check_interval = 10  # 健康检查间隔（秒）

        self._log_prefix = "[ProcessGuardian]"

    def _log(self, level: str, message: str):
        """记录日志"""
        log_func = getattr(logger, level, logger.info)
        log_func(f"{self._log_prefix} {message}")

    @property
    def status(self) -> GuardianStatus:
        """获取当前状态"""
        with self._status_lock:
            return self._status

    def _set_status(self, status: GuardianStatus):
        """设置状态"""
        with self._status_lock:
            old_status = self._status
            self._status = status
            if old_status != status:
                self._log("info", f"状态变更: {old_status.value} -> {status.value}")

    @property
    def stats(self) -> GuardianStats:
        """获取统计信息"""
        return self._stats

    # ═══════════════════════════════════════════════════════════════
    # 核心控制方法
    # ═══════════════════════════════════════════════════════════════

    async def watch_process(
        self,
        process_getter: Callable[[], Any],
        health_checker: Callable[[Any], bool],
        restart_callback: Callable[[], bool],
        on_failure: Callable[[str], None] | None = None
    ) -> bool:
        """
        开始监控进程

        Args:
            process_getter: 获取进程对象的函数
            health_checker: 健康检查函数，返回True表示健康
            restart_callback: 重启回调函数，返回True表示重启成功
            on_failure: 最终失败时的回调函数

        Returns:
            bool: 是否成功启动监控
        """
        if self._watching:
            self._log("warning", "守护器已在运行中")
            return False

        self._log("info", f"启动进程守护: max_restarts={self.max_restarts}")

        # 保存回调
        self._process_getter = process_getter
        self._health_checker = health_checker
        self._restart_callback = restart_callback
        self._on_failure = on_failure

        # 重置状态
        self._stop_event.clear()
        self._stats = GuardianStats()
        self._stats.watch_start_time = datetime.now()

        # 启动监控线程
        self._watching = True
        self._set_status(GuardianStatus.WATCHING)

        self._watch_thread = threading.Thread(
            target=self._watch_loop,
            daemon=True,
            name="ProcessGuardian"
        )
        self._watch_thread.start()

        return True

    async def stop(self) -> bool:
        """
        停止监控

        Returns:
            bool: 是否成功停止
        """
        if not self._watching:
            return True

        self._log("info", "停止进程守护")

        self._stop_event.set()
        self._watching = False

        if self._watch_thread and self._watch_thread.is_alive():
            self._watch_thread.join(timeout=5)

        self._set_status(GuardianStatus.STOPPED)
        return True

    def force_restart(self) -> bool:
        """
        强制立即重启

        Returns:
            bool: 是否成功触发重启
        """
        if not self._watching:
            self._log("warning", "守护器未运行，无法重启")
            return False

        self._log("info", "强制重启触发")

        # 在新线程中执行重启，避免阻塞
        restart_thread = threading.Thread(
            target=self._do_restart,
            args=("强制重启",),
            daemon=True
        )
        restart_thread.start()

        return True

    # ═══════════════════════════════════════════════════════════════
    # 监控循环
    # ═══════════════════════════════════════════════════════════════

    def _watch_loop(self):
        """监控循环（在独立线程中运行）"""
        self._log("info", "监控循环启动")

        consecutive_unhealthy = 0

        while self._watching and not self._stop_event.is_set():
            try:
                # 检查进程健康状态
                is_healthy = self._check_process_health()

                if is_healthy:
                    consecutive_unhealthy = 0
                else:
                    consecutive_unhealthy += 1
                    self._log("warning", f"进程不健康计数: {consecutive_unhealthy}")

                    # 连续3次检查不健康才认为进程异常
                    if consecutive_unhealthy >= 3:
                        self._log("error", "进程检测为异常，触发重启")
                        self._do_restart("进程不健康")
                        consecutive_unhealthy = 0

                # 等待下一次检查
                if self._stop_event.wait(self._check_interval):
                    break

            except Exception as e:
                self._log("error", f"监控循环异常: {e}")
                time.sleep(5)  # 异常后等待5秒再试

        self._log("info", "监控循环结束")
        self._watching = False

    def _check_process_health(self) -> bool:
        """检查进程健康状态"""
        try:
            if not self._process_getter or not self._health_checker:
                return False

            process = self._process_getter()
            if process is None:
                return False

            return self._health_checker(process)

        except Exception as e:
            self._log("error", f"健康检查异常: {e}")
            return False

    def _do_restart(self, reason: str):
        """
        执行重启

        Args:
            reason: 重启原因
        """
        with self._status_lock:
            if self._status == GuardianStatus.RESTARTING:
                self._log("warning", "正在重启中，跳过重复请求")
                return

            self._set_status(GuardianStatus.RESTARTING)

        # 检查是否超过最大重启次数
        if self._stats.consecutive_failures >= self.max_restarts:
            self._log("error", f"连续失败{self._stats.consecutive_failures}次，超过最大限制{self.max_restarts}")
            self._handle_final_failure(f"达到最大重启次数限制: {self.max_restarts}")
            return

        # 计算退避延迟
        delay = self._calculate_backoff_delay()
        self._log("info", f"{delay}秒后尝试重启 (原因: {reason})")

        time.sleep(delay)

        try:
            # 执行重启回调
            if self._restart_callback:
                success = self._restart_callback()

                # 记录重启结果
                record = RestartRecord(
                    timestamp=datetime.now(),
                    reason=reason,
                    success=success
                )
                self._stats.restart_records.append(record)
                self._stats.total_restarts += 1
                self._stats.last_restart_time = datetime.now()

                if success:
                    self._log("info", "重启成功")
                    self._stats.consecutive_failures = 0
                    self._set_status(GuardianStatus.WATCHING)
                else:
                    self._log("error", "重启失败")
                    self._stats.consecutive_failures += 1

                    # 检查是否需要最终失败处理
                    if self._stats.consecutive_failures >= self.max_restarts:
                        self._handle_final_failure(f"重启失败{self._stats.consecutive_failures}次")
                    else:
                        # 再次尝试重启
                        self._do_restart(f"上次重启失败，第{self._stats.consecutive_failures}次重试")
            else:
                self._log("error", "未设置重启回调")
                self._handle_final_failure("未配置重启回调")

        except Exception as e:
            self._log("error", f"重启异常: {e}")
            self._stats.consecutive_failures += 1

            record = RestartRecord(
                timestamp=datetime.now(),
                reason=reason,
                success=False,
                error_message=str(e)
            )
            self._stats.restart_records.append(record)

            # 检查是否需要最终失败处理
            if self._stats.consecutive_failures >= self.max_restarts:
                self._handle_final_failure(f"重启异常: {e}")

    def _calculate_backoff_delay(self) -> int:
        """计算退避延迟"""
        if not self.exponential_backoff:
            return self.base_restart_delay

        # 指数退避: delay = base * (2 ^ failures)
        delay = self.base_restart_delay * (2 ** self._stats.consecutive_failures)
        return min(delay, self.max_backoff_delay)

    def _handle_final_failure(self, reason: str):
        """处理最终失败"""
        self._log("error", f"最终失败: {reason}")
        self._set_status(GuardianStatus.FAILED)

        if self._on_failure:
            try:
                self._on_failure(reason)
            except Exception as e:
                self._log("error", f"失败回调异常: {e}")

    # ═══════════════════════════════════════════════════════════════
    # 查询接口
    # ═══════════════════════════════════════════════════════════════

    def get_status(self) -> dict[str, Any]:
        """获取完整状态"""
        return {
            "status": self.status.value,
            "stats": self.stats.to_dict(),
            "config": {
                "max_restarts": self.max_restarts,
                "restart_delay": self.base_restart_delay,
                "exponential_backoff": self.exponential_backoff
            },
            "is_watching": self._watching
        }

    def get_restart_history(self, limit: int = 10) -> list[dict[str, Any]]:
        """获取重启历史"""
        records = self._stats.restart_records[-limit:]
        return [
            {
                "timestamp": r.timestamp.isoformat(),
                "reason": r.reason,
                "success": r.success,
                "error": r.error_message
            }
            for r in records
        ]


# ═══════════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════════

def create_guardian_for_process_manager(
    process_manager,
    max_restarts: int = 5,
    restart_delay: int = 30
) -> ProcessGuardian:
    """
    为ProcessManager创建守护器

    Args:
        process_manager: BTCProcessManager实例
        max_restarts: 最大重启次数
        restart_delay: 重启延迟

    Returns:
        ProcessGuardian: 配置好的守护器
    """
    guardian = ProcessGuardian(
        max_restarts=max_restarts,
        restart_delay=restart_delay
    )

    # 配置回调
    async def watch():
        await guardian.watch_process(
            process_getter=lambda: process_manager,
            health_checker=lambda pm: pm.get_state().status == ProcessStatus.RUNNING,
            restart_callback=lambda: process_manager.start(
                strategy=process_manager._last_strategy if hasattr(process_manager, '_last_strategy') else "stage46_aggressive",
                duration_minutes=55
            ),
            on_failure=lambda reason: logger.error(f"进程守护最终失败: {reason}")
        )

    # 保存watch函数到guardian实例，方便外部调用
    guardian.start_watching = watch

    return guardian
