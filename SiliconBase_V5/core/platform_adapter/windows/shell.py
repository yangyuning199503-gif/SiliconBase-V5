#!/usr/bin/env python3
"""
Windows Shell 执行实现
"""

import os
import shutil
import subprocess
from pathlib import Path

from ..interfaces import IShellExecutor


class WindowsShellExecutor(IShellExecutor):
    """Windows Shell 执行器"""

    def execute(
        self,
        command: str | list[str],
        shell: bool = False,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        timeout: int | None = None
    ) -> tuple[bool, str, str, int]:
        """
        执行命令

        Returns:
            (success, stdout, stderr, return_code)
        """
        # 合并环境变量
        process_env = os.environ.copy()
        if env:
            process_env.update(env)

        # Windows 下默认使用 shell=True 来支持 .bat 和命令
        if not shell and isinstance(command, str):
            shell = True

        try:
            # 使用 GBK 编码处理中文
            result = subprocess.run(
                command,
                shell=shell,
                cwd=str(cwd) if cwd else None,
                env=process_env,
                capture_output=True,
                text=True,
                encoding='utf-8',  # Windows 10+ 支持 UTF-8
                errors='replace',
                timeout=timeout
            )

            success = result.returncode == 0
            return (
                success,
                result.stdout,
                result.stderr,
                result.returncode
            )

        except subprocess.TimeoutExpired as e:
            return (False, e.stdout or "", e.stderr or "", -1)
        except Exception as e:
            return (False, "", str(e), -1)

    def execute_async(
        self,
        command: str | list[str],
        shell: bool = False,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None
    ) -> subprocess.Popen:
        """异步执行，返回进程对象"""
        process_env = os.environ.copy()
        if env:
            process_env.update(env)

        if not shell and isinstance(command, str):
            shell = True

        return subprocess.Popen(
            command,
            shell=shell,
            cwd=str(cwd) if cwd else None,
            env=process_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace'
        )

    def which(self, executable: str) -> str | None:
        """查找可执行文件路径"""
        return shutil.which(executable)

    def get_shell_type(self) -> str:
        """获取当前 shell 类型"""
        # Windows 上通常使用 cmd 或 PowerShell
        comspec = os.environ.get('COMSPEC', 'cmd.exe')
        if 'powershell' in comspec.lower() or 'pwsh' in comspec.lower():
            return "powershell"
        return "cmd"

    def script_ext(self) -> str:
        """获取脚本文件扩展名"""
        return ".bat"

    def find_powershell(self) -> str | None:
        """查找 PowerShell 路径"""
        # 尝试 PowerShell Core (pwsh)
        pwsh = shutil.which("pwsh")
        if pwsh:
            return pwsh

        # 尝试 Windows PowerShell
        ps_path = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
        if os.path.exists(ps_path):
            return ps_path

        return shutil.which("powershell")
