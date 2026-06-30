#!/usr/bin/env python3
"""
POSIX Shell 执行实现 (macOS/Linux)
"""

import os
import shutil
import subprocess
from pathlib import Path

from ..interfaces import IShellExecutor


class PosixShellExecutor(IShellExecutor):
    """POSIX Shell 执行器"""

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

        try:
            result = subprocess.run(
                command,
                shell=shell,
                cwd=str(cwd) if cwd else None,
                env=process_env,
                capture_output=True,
                text=True,
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

        return subprocess.Popen(
            command,
            shell=shell,
            cwd=str(cwd) if cwd else None,
            env=process_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

    def which(self, executable: str) -> str | None:
        """查找可执行文件路径"""
        return shutil.which(executable)

    def get_shell_type(self) -> str:
        """获取当前 shell 类型"""
        shell = os.environ.get('SHELL', '/bin/sh')
        return shell

    def script_ext(self) -> str:
        """获取脚本文件扩展名"""
        return ".sh"
