#!/usr/bin/env python3
"""
原子工具：执行Shell命令

安全说明：
- 使用白名单机制限制可执行命令
- 危险字符过滤
- 超时控制
- 返回stdout/stderr/returncode
"""
import asyncio
import os
import re
import shutil
import subprocess
from typing import Any

from core.base_tool import BaseTool
from core.error_codes import INVALID_PARAMS, TOOL_EXECUTION_ERROR, format_error

# 【治理】统一命令白名单：从 core.safety.command_whitelist 获取
# 不再在此文件中维护独立的白名单列表
try:
    from core.safety.command_whitelist import get_commands_for_scope
    ALLOWED_COMMANDS = get_commands_for_scope("shell_execute")
except ImportError:
    # 兜底：如果统一白名单模块未加载，使用精简默认列表
    ALLOWED_COMMANDS = {
        'python', 'python3', 'node', 'npm', 'git', 'docker',
        'cmd', 'powershell', 'bash',
        'ping', 'ipconfig', 'ls', 'cat', 'grep', 'curl', 'wget',
        'echo', 'exit', 'clear',
    }

# 危险字符模式
DANGEROUS_CHARS = re.compile(r'[;&|`$(){}[\]\\<>!]')

# 危险命令模式（完全禁止）
DANGEROUS_PATTERNS = [
    r'rm\s+-rf\s+/',
    r'format\s+',
    r'del\s+/[fq]',
    r'rmdir\s+/[sq]',
    r':\(\)\s*\{\s*:\|:\}&',
    r'>\s*/dev/null',
    r'2>&1',
    r'\|\s*sh',
    r'\|\s*bash',
    r'\|\s*cmd',
    r'\|\s*powershell',
]


class ShellExecute(BaseTool):
    tool_id = "shell_execute"
    name = "执行Shell命令"
    description = "执行终端命令并返回输出结果（支持Windows CMD/PowerShell和Unix Bash，自动进行命令转换）"
    input_schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "要执行的命令"
            },
            "cwd": {
                "type": "string",
                "description": "工作目录（可选，默认为当前目录）"
            },
            "timeout": {
                "type": "integer",
                "description": "超时时间（秒），默认30秒，最大300秒",
                "default": 30,
                "minimum": 1,
                "maximum": 300
            },
            "shell": {
                "type": "string",
                "enum": ["auto", "cmd", "powershell", "bash"],
                "description": "使用的shell，auto自动检测",
                "default": "auto"
            }
        },
        "required": ["command"]
    }

    def _execute(self, **kwargs) -> dict[str, Any]:
        command = kwargs.get("command", "").strip()
        cwd = kwargs.get("cwd")
        timeout = kwargs.get("timeout", 30)
        shell = kwargs.get("shell", "auto")

        # 参数验证
        if not command:
            return format_error(INVALID_PARAMS, detail="命令不能为空")

        if timeout < 1 or timeout > 300:
            return format_error(INVALID_PARAMS, detail="超时时间必须在1-300秒之间")

        # 安全检查
        is_safe, error_msg = self._security_check(command)
        if not is_safe:
            return format_error(TOOL_EXECUTION_ERROR, detail=f"安全检查失败: {error_msg}")

        # 执行命令
        try:
            return self._execute_command(command, cwd, timeout, shell)
        except Exception as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=f"执行失败: {str(e)}")

    async def _execute_async(self, **kwargs) -> dict[str, Any]:
        """Phase 8 TRUE_ASYNC: 使用 asyncio.create_subprocess_exec，零线程池"""
        command = kwargs.get("command", "").strip()
        cwd = kwargs.get("cwd")
        timeout = kwargs.get("timeout", 30)
        shell = kwargs.get("shell", "auto")

        # 参数验证
        if not command:
            return format_error(INVALID_PARAMS, detail="命令不能为空")

        if timeout < 1 or timeout > 300:
            return format_error(INVALID_PARAMS, detail="超时时间必须在1-300秒之间")

        # 安全检查
        is_safe, error_msg = self._security_check(command)
        if not is_safe:
            return format_error(TOOL_EXECUTION_ERROR, detail=f"安全检查失败: {error_msg}")

        # 执行命令
        try:
            return await self._execute_command_async(command, cwd, timeout, shell)
        except Exception as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=f"执行失败: {str(e)}")

    async def _execute_command_async(
        self,
        command: str,
        cwd: str | None,
        timeout: int,
        shell: str,
    ) -> dict[str, Any]:
        """异步执行命令（TRUE_ASYNC）"""
        is_windows = os.name == 'nt'

        # 自动检测shell
        if shell == "auto":
            if is_windows:
                shell = "powershell" if shutil.which("powershell") else "cmd"
            else:
                shell = "bash" if shutil.which("bash") else "sh"

        # 构建执行参数
        if is_windows:
            if shell == "powershell":
                cmd_list = ['powershell', '-Command', self._unix_to_powershell(command)]
            else:
                cmd_list = ['cmd', '/c', self._unix_to_cmd(command)]
        else:
            cmd_list = [shell, '-c', command]

        # 验证工作目录
        if cwd and not os.path.isdir(cwd):
            return format_error(INVALID_PARAMS, detail=f"工作目录不存在: {cwd}")

        # TRUE_ASYNC: 使用 asyncio.create_subprocess_exec
        try:
            proc = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    *cmd_list,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                ),
                timeout=timeout,
            )
            stdout_b, stderr_b = await proc.communicate()

            stdout = stdout_b.decode('utf-8', errors='replace') if stdout_b else ""
            stderr = stderr_b.decode('utf-8', errors='replace') if stderr_b else ""

            success = proc.returncode == 0
            return {
                "success": success,
                "error_code": None if success else "COMMAND_FAILED",
                "user_message": f"命令执行{'成功' if success else '失败'} (返回码: {proc.returncode})",
                "data": {
                    "stdout": stdout,
                    "stderr": stderr,
                    "returncode": proc.returncode,
                    "command": command,
                    "shell": shell
                }
            }

        except asyncio.TimeoutError:
            return format_error(TOOL_EXECUTION_ERROR, detail=f"命令执行超时（{timeout}秒）")
        except FileNotFoundError as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=f"找不到命令: {e}")
        except Exception as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=f"执行错误: {str(e)}")

    def _security_check(self, command: str) -> tuple[bool, str]:
        """安全检查"""
        # 检查危险命令模式
        for pattern in DANGEROUS_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return False, f"命令包含危险模式: {pattern}"

        # 检查危险字符
        if DANGEROUS_CHARS.search(command):
            # 如果包含危险字符，检查是否是白名单命令
            cmd_parts = command.split()
            if not cmd_parts:
                return False, "空命令"

            base_cmd = cmd_parts[0].lower()
            if base_cmd not in ALLOWED_COMMANDS:
                return False, f"命令 '{base_cmd}' 不在白名单中"

        return True, ""

    def _execute_command(
        self,
        command: str,
        cwd: str | None,
        timeout: int,
        shell: str
    ) -> dict[str, Any]:
        """执行命令"""
        is_windows = os.name == 'nt'

        # 自动检测shell
        if shell == "auto":
            if is_windows:
                shell = "powershell" if shutil.which("powershell") else "cmd"
            else:
                shell = "bash" if shutil.which("bash") else "sh"

        # 构建执行参数
        if is_windows:
            if shell == "powershell":
                cmd_list = ['powershell', '-Command', self._unix_to_powershell(command)]
            else:
                cmd_list = ['cmd', '/c', self._unix_to_cmd(command)]
        else:
            # Unix/Linux/Mac
            cmd_list = [shell, '-c', command]

        # 验证工作目录
        if cwd and not os.path.isdir(cwd):
            return format_error(INVALID_PARAMS, detail=f"工作目录不存在: {cwd}")

        # 执行
        try:
            result = subprocess.run(
                cmd_list,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
                shell=False  # 使用列表形式，防止注入
            )

            success = result.returncode == 0
            return {
                "success": success,
                "error_code": None if success else "COMMAND_FAILED",
                "user_message": f"命令执行{'成功' if success else '失败'} (返回码: {result.returncode})",
                "data": {
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "returncode": result.returncode,
                    "command": command,
                    "shell": shell
                }
            }

        except subprocess.TimeoutExpired:
            return format_error(TOOL_EXECUTION_ERROR, detail=f"命令执行超时（{timeout}秒）")
        except FileNotFoundError as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=f"找不到命令: {e}")
        except Exception as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=f"执行错误: {str(e)}")

    def _unix_to_powershell(self, command: str) -> str:
        """将Unix命令转换为PowerShell"""
        translations = {
            r'\bls\b': 'Get-ChildItem',
            r'\bcat\b': 'Get-Content',
            r'\brm\b': 'Remove-Item',
            r'\bcp\b': 'Copy-Item',
            r'\bmv\b': 'Move-Item',
            r'\bmkdir\b': 'New-Item -ItemType Directory',
            r'\btouch\b': 'New-Item',
            r'\bgrep\b': 'Select-String',
            r'\bpwd\b': 'Get-Location',
            r'\becho\b': 'Write-Output',
            r'\bfind\b': 'Get-ChildItem -Recurse',
        }

        result = command
        for unix_cmd, ps_cmd in translations.items():
            result = re.sub(unix_cmd, ps_cmd, result)

        return result

    def _unix_to_cmd(self, command: str) -> str:
        """将Unix命令转换为CMD"""
        translations = {
            r'\bls\b': 'dir',
            r'\bcat\b': 'type',
            r'\brm\b': 'del',
            r'\bcp\b': 'copy',
            r'\bmv\b': 'move',
            r'\bmkdir\b': 'mkdir',
            r'\bpwd\b': 'cd',
            r'\becho\b': 'echo',
            r'\bgrep\b': 'findstr',
            r'\bclear\b': 'cls',
        }

        result = command
        for unix_cmd, cmd_cmd in translations.items():
            result = re.sub(unix_cmd, cmd_cmd, result)

        return result
