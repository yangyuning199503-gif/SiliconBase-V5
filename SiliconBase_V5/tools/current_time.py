#!/usr/bin/env python3
"""
原子工具：获取当前时间
2026-03-11 修复：将run改为_execute，异常处理交由基类统一处理
"""
import asyncio
from datetime import datetime

from core.base_tool import BaseTool


class CurrentTime(BaseTool):
    tool_id = "current_time"
    name = "当前时间"
    description = "获取当前系统日期和时间，包括年月日时分秒和星期"
    input_schema = {
        "type": "object",
        "properties": {},
        "required": []
    }
    timeout = 5  # 快速执行

    def _execute(self, **kwargs) -> dict:
        """获取当前时间 - 异常由基类统一处理"""
        now = datetime.now()
        return {
            "success": True,
            "error_code": None,
            "user_message": f"当前时间: {now.strftime('%Y年%m月%d日 %H:%M:%S')}",
            "data": {
                "datetime": now.isoformat(),
                "date": now.strftime("%Y年%m月%d日"),
                "time": now.strftime("%H:%M:%S"),
                "weekday": now.strftime("%A"),
                "timestamp": int(now.timestamp())
            }
        }

    async def _execute_async(self, **kwargs) -> dict:
        return await asyncio.to_thread(self._execute, **kwargs)
