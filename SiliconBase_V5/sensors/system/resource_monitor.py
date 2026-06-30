#!/usr/bin/env python3
"""
资源监控与自动降级 - V5.1 改造版
修复版：使用可重启线程
"""
import threading
import time

import psutil

from core.logger import logger
from core.strategy.adaptive_policy import adaptive_policy
from sensors.system.restartable import RestartableThread


class ResourceMonitor:
    _instance = None
    _creation_lock = threading.Lock()
    _thread = None
    _running = False

    def __new__(cls):
        if cls._instance is None:
            with cls._creation_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = RestartableThread(target=self._run, name="ResourceMonitor", daemon=True)
        self._thread.start()
        logger.info("资源监控已启动")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.stop()
            # 移除 self._thread.join()

    def _run(self):
        last_low_flag = None
        cpu_high_count = 0
        while self._running:
            try:
                mem = psutil.virtual_memory()
                cpu = psutil.cpu_percent(interval=1)
                is_low_memory = mem.total < 8 * 1024**3
                if cpu > 70:
                    cpu_high_count += 1
                else:
                    cpu_high_count = max(0, cpu_high_count - 1)
                should_low = is_low_memory or cpu_high_count > 3
                if should_low != last_low_flag:
                    adaptive_policy.apply_low_memory_mode(should_low)
                    last_low_flag = should_low
                    logger.info(f"资源监控: {'低资源模式' if should_low else '正常模式'} (内存:{mem.percent}% CPU:{cpu}%)")
                time.sleep(5)
            except Exception as e:
                logger.error(f"资源监控异常: {e}")
                time.sleep(5)


resource_monitor = ResourceMonitor()
