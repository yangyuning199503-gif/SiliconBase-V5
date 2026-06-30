#!/usr/bin/env python3
"""
原子工具：结束进程（高危）
"""
import asyncio

import psutil

from core.base_tool import BaseTool
from core.error_codes import FILE_NOT_FOUND, TOOL_EXECUTION_ERROR, format_error


class ProcessKill(BaseTool):
    tool_id = "process_kill"
    name = "结束进程"
    description = "终止指定进程（高危）"
    input_schema = {
        "type": "object",
        "properties": {
            "pid": {"type": "integer"},
            "name": {"type": "string"}
        },
        "oneOf": [{"required": ["pid"]}, {"required": ["name"]}]
    }
    require_confirmation = True

    def _execute(self, **kwargs) -> dict:
        try:
            if "pid" in kwargs:
                proc = psutil.Process(kwargs["pid"])
                proc.terminate()
                return {
                    "success": True,
                    "error_code": None,
                    "user_message": f"进程 {kwargs['pid']} 已终止",
                    "data": {"killed_pid": kwargs["pid"]}
                }
            else:
                killed = []
                for proc in psutil.process_iter(['pid', 'name']):
                    if proc.info['name'] and proc.info['name'].lower() == kwargs["name"].lower():
                        proc.terminate()
                        killed.append(proc.info['pid'])
                user_msg = f"已终止 {len(killed)} 个进程" if killed else f"未找到进程 '{kwargs['name']}'"
                return {
                    "success": True,
                    "error_code": None,
                    "user_message": user_msg,
                    "data": {"killed_pids": killed}
                }
        except psutil.NoSuchProcess:
            return format_error(FILE_NOT_FOUND, path=f"PID:{kwargs.get('pid')}")
        except Exception as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=str(e))
    async def _execute_async(self, **kwargs) -> dict:
        return await asyncio.to_thread(self._execute, **kwargs)
