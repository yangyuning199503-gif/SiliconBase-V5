#!/usr/bin/env python3
"""
原子工具：获取系统信息
"""
import platform

import psutil

from core.base_tool import BaseTool
from core.error_codes import TOOL_EXECUTION_ERROR, format_error


class SystemInfo(BaseTool):
    tool_id = "system_info"
    name = "系统信息"
    description = "获取CPU、内存、磁盘使用率"
    input_schema = {"type": "object", "properties": {}}

    async def _execute_async(self, **kwargs) -> dict:
        """异步执行：将同步 _execute 桥接到线程池，避免阻塞事件循环。"""
        import asyncio
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self._execute(**kwargs))

    def _execute(self, **kwargs) -> dict:
        try:
            cpu = psutil.cpu_percent(interval=0.5)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            return {
                "success": True,
                "error_code": None,
                "user_message": f"系统信息获取成功 - CPU: {cpu}%, 内存: {mem.percent}%",
                "data": {
                    "os": platform.platform(),
                    "cpu_percent": cpu,
                    "cpu_count": psutil.cpu_count(),
                    "memory_percent": mem.percent,
                    "memory_total_gb": round(mem.total / (1024**3), 2),
                    "memory_used_gb": round(mem.used / (1024**3), 2),
                    "disk_percent": disk.percent,
                    "disk_total_gb": round(disk.total / (1024**3), 2),
                    "disk_free_gb": round(disk.free / (1024**3), 2)
                }
            }
        except Exception as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=str(e))
