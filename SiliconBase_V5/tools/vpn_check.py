#!/usr/bin/env python3
"""
原子工具：检查VPN状态
"""
import platform

from core.base_tool import BaseTool
from core.error_codes import NOT_SUPPORTED, VPN_CHECK_FAILED, format_error


class VPNCheck(BaseTool):
    tool_id = "vpn_check"
    name = "检查VPN"
    description = "检查系统VPN连接状态"
    input_schema = {"type": "object", "properties": {}}

    async def _execute_async(self, **kwargs) -> dict:
        import asyncio
        system = platform.system()
        if system == "Windows":
            try:
                proc = await asyncio.create_subprocess_exec(
                    "rasdial",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
                output = stdout.decode("utf-8", errors="replace")
                if "已连接" in output or "Connected" in output:
                    return {
                        "success": True,
                        "error_code": None,
                        "user_message": "VPN已连接",
                        "data": {"connected": True}
                    }
                else:
                    return {
                        "success": True,
                        "error_code": None,
                        "user_message": "VPN未连接",
                        "data": {"connected": False}
                    }
            except asyncio.TimeoutError:
                return format_error(VPN_CHECK_FAILED, detail="VPN检查超时")
            except Exception:
                return format_error(VPN_CHECK_FAILED)
        else:
            return format_error(NOT_SUPPORTED)

    async def run(self, **kwargs) -> dict:
        return await self.run_async(**kwargs)
