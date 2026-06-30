#!/usr/bin/env python3
"""
Windows 进程管理实现

使用 psutil 和 subprocess 实现跨进程管理。
"""

import os
import subprocess
from pathlib import Path

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    print("[WindowsProcess] 警告: psutil 未安装，进程管理功能受限")

import contextlib

from ..interfaces import IProcessManager, ProcessInfo


class WindowsProcessManager(IProcessManager):
    """Windows 进程管理器"""

    def __init__(self):
        self._use_psutil = PSUTIL_AVAILABLE

    def create_process(
        self,
        command: list[str],
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        capture_output: bool = True,
        new_process_group: bool = False
    ) -> subprocess.Popen:
        """
        创建 Windows 进程

        Args:
            command: 命令及参数列表
            cwd: 工作目录
            env: 环境变量
            capture_output: 是否捕获输出
            new_process_group: 是否创建新进程组(用于分离子进程)
        """
        # Windows 特有的创建标志
        creationflags = 0
        if new_process_group:
            creationflags |= subprocess.CREATE_NEW_PROCESS_GROUP

        # 合并环境变量
        process_env = os.environ.copy()
        if env:
            process_env.update(env)

        # 启动进程
        process = subprocess.Popen(
            command,
            cwd=str(cwd) if cwd else None,
            env=process_env,
            stdout=subprocess.PIPE if capture_output else None,
            stderr=subprocess.PIPE if capture_output else None,
            text=True,
            creationflags=creationflags
        )

        return process

    def terminate_process(self, pid: int, force: bool = False) -> bool:
        """
        终止 Windows 进程

        Args:
            pid: 进程ID
            force: 是否强制终止
        """
        if self._use_psutil:
            try:
                process = psutil.Process(pid)
                if force:
                    process.kill()  # SIGKILL 等效
                else:
                    process.terminate()  # SIGTERM 等效
                return True
            except psutil.NoSuchProcess:
                return False
            except Exception as e:
                print(f"[WindowsProcess] 终止进程失败: {e}")
                return False
        else:
            # 备用方案：使用 taskkill
            try:
                cmd = ['taskkill', '/F' if force else '/T', '/PID', str(pid)]
                subprocess.run(cmd, check=True, capture_output=True)
                return True
            except subprocess.CalledProcessError:
                return False

    def send_signal(self, pid: int, signal_type: str) -> bool:
        """
        发送 Windows 信号

        Args:
            pid: 进程ID
            signal_type: "term", "kill", "interrupt", "break", "stop", "continue"
        """
        try:
            if signal_type == "break":
                # Windows 特有的 CTRL_BREAK
                import ctypes
                kernel = ctypes.windll.kernel32
                # 1 = CTRL_BREAK_EVENT
                result = kernel.GenerateConsoleCtrlEvent(1, pid)
                return result != 0

            elif signal_type in ("term", "interrupt"):
                return self.terminate_process(pid, force=False)

            elif signal_type == "kill":
                return self.terminate_process(pid, force=True)

            elif signal_type == "stop":
                # Windows 暂停进程
                if self._use_psutil:
                    p = psutil.Process(pid)
                    p.suspend()
                    return True

            elif signal_type == "continue":
                # Windows 恢复进程
                if self._use_psutil:
                    p = psutil.Process(pid)
                    p.resume()
                    return True

            return False

        except Exception as e:
            print(f"[WindowsProcess] 发送信号失败: {e}")
            return False

    def get_processes(self) -> list[ProcessInfo]:
        """获取 Windows 进程列表"""
        processes = []

        if not self._use_psutil:
            return processes

        for proc in psutil.process_iter(['pid', 'name', 'status', 'cpu_percent',
                                          'memory_percent', 'create_time']):
            with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                processes.append(ProcessInfo(
                    pid=proc.info['pid'],
                    name=proc.info['name'] or "Unknown",
                    status=str(proc.info['status']) if proc.info['status'] else "unknown",
                    cpu_percent=proc.info['cpu_percent'] or 0.0,
                    memory_percent=proc.info['memory_percent'] or 0.0,
                    create_time=proc.info['create_time'] or 0.0
                ))

        return processes

    def get_process(self, pid: int) -> ProcessInfo | None:
        """获取指定进程信息"""
        if not self._use_psutil:
            return None

        try:
            proc = psutil.Process(pid)
            return ProcessInfo(
                pid=proc.pid,
                name=proc.name(),
                status=str(proc.status()),
                cpu_percent=proc.cpu_percent(),
                memory_percent=proc.memory_percent(),
                create_time=proc.create_time()
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None

    def is_process_running(self, pid: int) -> bool:
        """检查进程是否运行中"""
        if self._use_psutil:
            try:
                process = psutil.Process(pid)
                return process.is_running()
            except psutil.NoSuchProcess:
                return False
        else:
            # 备用方案
            try:
                subprocess.run(['tasklist', '/FI', f'PID eq {pid}'],
                             check=True, capture_output=True)
                return True
            except subprocess.CalledProcessError:
                return False
