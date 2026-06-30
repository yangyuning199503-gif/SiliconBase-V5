#!/usr/bin/env python3
"""
进程监控常驻线程
修复版：使用可重启线程
"""
import threading
import time

import psutil

from core.logger import logger
from core.strategy.adaptive_policy import adaptive_policy
from sensors.system.bus import PerceptionData, bus
from sensors.system.restartable import RestartableThread


class ProcessMonitor:
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
        self._thread = RestartableThread(target=self._run, name="ProcessMonitor", daemon=True)
        self._thread.start()
        logger.info("进程监控已启动")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.stop()
            # 无需额外 join，RestartableThread.stop() 已处理等待和超时

    def _run(self):
        while self._running:
            interval = adaptive_policy.get("perception.process.interval", 1)
            try:
                for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'status']):
                    try:
                        pinfo = proc.info
                        if pinfo['cpu_percent'] is not None and pinfo['cpu_percent'] > 0.1:
                            data = PerceptionData(
                                source="process",
                                timestamp=time.time(),
                                confidence=0.9,
                                content={
                                    "pid": pinfo['pid'],
                                    "name": pinfo['name'],
                                    "cpu": round(pinfo['cpu_percent'], 1),
                                    "memory": round(pinfo['memory_percent'], 1),
                                    "status": pinfo['status']
                                }
                            )
                            bus.publish(data)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
            except Exception as e:
                logger.error(f"进程监控异常: {e}")
                # 异常由 RestartableThread 捕获并自动重启
            time.sleep(interval)


# 创建全局单例实例
process_monitor = ProcessMonitor()
