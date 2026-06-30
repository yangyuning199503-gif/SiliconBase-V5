#!/usr/bin/env python3
"""
可重启线程基类 - 修复感知模块线程无法停止/重启的问题
2026-02-16 修复：增加异常重启次数限制和冷却时间
2026-02-21 修复：join 超时后强制标记停止并记录警告
"""
import contextlib
import threading
import time
from collections.abc import Callable

from core.logger import logger


class RestartableThread:
    def __init__(self, target: Callable, name: str = "", daemon: bool = True):
        self._target = target
        self._name = name
        self._daemon = daemon
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._fail_count = 0
        self._max_failures = 5
        self._cooldown_base = 1  # 初始冷却1秒
        self._max_cooldown = 30  # 最大冷却30秒

    def start(self):
        """启动线程"""
        with self._lock:
            if self._thread and self._thread.is_alive():
                logger.warning(f"线程 {self._name} 已在运行，无需重复启动")
                return
            self._stop_event.clear()
            def wrapped_target():
                try:
                    self._target()
                except Exception as e:
                    logger.error(f"线程 {self._name} 执行异常: {e}", exc_info=True)
                    self._fail_count += 1
                    if self._fail_count <= self._max_failures:
                        cooldown = min(self._cooldown_base * (2 ** (self._fail_count - 1)), self._max_cooldown)
                        logger.info(f"线程 {self._name} 将在 {cooldown} 秒后重启 (失败 {self._fail_count}/{self._max_failures})")
                        time.sleep(cooldown)
                        if not self._stop_event.is_set():
                            self.start()
                    else:
                        logger.error(f"线程 {self._name} 连续失败 {self._max_failures} 次，停止自动重启")
                else:
                    self._fail_count = 0

            self._thread = threading.Thread(
                target=wrapped_target,
                name=self._name,
                daemon=self._daemon
            )
            self._thread.start()
            logger.info(f"线程 {self._name} 已启动")

    def stop(self, timeout: float = 2.0):
        """停止线程"""
        with self._lock:
            self._stop_event.set()
            if self._thread and self._thread.is_alive():
                with contextlib.suppress(RuntimeError):
                    self._thread.join(timeout=timeout)
                if self._thread.is_alive():
                    logger.warning(f"线程 {self._name} 停止超时，强制终止（可能资源泄漏）")
                self._thread = None
            self._fail_count = 0
            logger.info(f"线程 {self._name} 已停止")

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stop_event.is_set()

    def is_stopped(self) -> bool:
        return self._stop_event.is_set()
