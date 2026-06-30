#!/usr/bin/env python3
"""
原子工具：连接VPN
"""
import platform
import subprocess

from core.base_tool import BaseTool
from core.error_codes import INVALID_PARAMS, NOT_SUPPORTED, VPN_CONNECT_FAILED, format_error


class VPNConnect(BaseTool):
    tool_id = "vpn_connect"
    name = "连接VPN"
    description = "尝试连接VPN（需预先配置连接）"
    input_schema = {
        "type": "object",
        "properties": {
            "vpn_name": {"type": "string"},
            "username": {"type": "string"},
            "password": {"type": "string"}
        },
        "required": ["vpn_name"]
    }

    async def _execute_async(self, **kwargs) -> dict:
        import asyncio
        system = platform.system()
        if system == "Windows":
            vpn = kwargs.get("vpn_name")
            if not vpn:
                return format_error(INVALID_PARAMS, detail="vpn_name 不能为空")
            user = kwargs.get("username", "")
            pwd = kwargs.get("password", "")
            cmd = ["rasdial", vpn]
            if user and pwd:
                cmd.extend([user, pwd])
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
                if proc.returncode == 0:
                    return {
                        "success": True,
                        "error_code": None,
                        "user_message": f"VPN连接成功: {vpn}",
                        "data": {"vpn": vpn}
                    }
                else:
                    return format_error(VPN_CONNECT_FAILED, detail=stderr.decode("utf-8", errors="replace"))
            except asyncio.TimeoutError:
                return format_error(VPN_CONNECT_FAILED, detail="VPN连接超时")
            except Exception:
                return format_error(VPN_CONNECT_FAILED, detail="执行失败")
        else:
            return format_error(NOT_SUPPORTED)

    def _execute(self, **kwargs) -> dict:
        system = platform.system()
        if system == "Windows":
            vpn = kwargs.get("vpn_name")
            if not vpn:
                return format_error(INVALID_PARAMS, detail="vpn_name 不能为空")
            user = kwargs.get("username", "")
            pwd = kwargs.get("password", "")
            cmd = ["rasdial", vpn]
            if user and pwd:
                cmd.extend([user, pwd])
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                if result.returncode == 0:
                    return {
                        "success": True,
                        "error_code": None,
                        "user_message": f"VPN连接成功: {vpn}",
                        "data": {"vpn": vpn}
                    }
                else:
                    return format_error(VPN_CONNECT_FAILED, detail=result.stderr)
            except Exception:
                return format_error(VPN_CONNECT_FAILED, detail="执行失败")
        else:
            return format_error(NOT_SUPPORTED)
