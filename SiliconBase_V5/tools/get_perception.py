#!/usr/bin/env python3
"""
感知查询工具 - 供AI获取当前环境信息
"""
import asyncio

import psutil

from core.base_tool import BaseTool
from sensors.system.bus import bus


class GetPerception(BaseTool):
    tool_id = "get_perception"
    name = "获取环境感知"
    description = "查询当前环境信息，包括活跃窗口、高CPU/内存进程、系统摘要等。"
    input_schema = {
        "type": "object",
        "properties": {},
        "required": []
    }

    def _execute(self, **kwargs) -> dict:
        return self._do_execute(**kwargs)

    async def _execute_async(self, **kwargs) -> dict:
        """Phase 8: 异步入口 — psutil 系统调用通过 run_in_executor 桥接，避免阻塞事件循环"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self._do_execute(**kwargs))

    def _do_execute(self, **kwargs) -> dict:
        """实际执行逻辑（同步实现，供 _execute 和 _execute_async 复用）"""
        # 获取感知摘要（来自 bus）
        summary = bus.get_summary()
        # 获取最近的感知数据
        recent = bus.get_latest(seconds=2.0)
        active_window = ""
        cpu_processes = []
        mem_processes = []
        for d in recent:
            if d.source == "window" and d.content.get("windows"):
                windows = d.content["windows"]
                if windows:
                    active_window = windows[0].get("title", "")[:100]
            if d.source == "process":
                name = d.content.get("name", "")
                cpu = d.content.get("cpu", 0)
                mem = d.content.get("memory", 0)
                if cpu > 10:
                    cpu_processes.append(f"{name}({cpu}%)")
                if mem > 10:
                    mem_processes.append(f"{name}({mem}%)")
        # 获取系统信息
        cpu_percent = psutil.cpu_percent(interval=0.5)
        mem_percent = psutil.virtual_memory().percent
        disk_percent = psutil.disk_usage('/').percent

        data = {
            "active_window": active_window,
            "high_cpu_processes": cpu_processes[:5],
            "high_memory_processes": mem_processes[:5],
            "system_cpu": cpu_percent,
            "system_memory": mem_percent,
            "system_disk": disk_percent,
            "summary": summary
        }
        return {
            "success": True,
            "error_code": None,
            "user_message": f"当前环境：{summary}",
            "data": data
        }
