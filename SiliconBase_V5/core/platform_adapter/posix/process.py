#!/usr/bin/env python3
"""
POSIX 进程管理实现 (macOS/Linux)

使用 psutil 和 subprocess 实现跨进程管理。
"""

import os
import signal
import subprocess
from pathlib import Path

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    print("[PosixProcess] 警告: psutil 未安装，进程管理功能受限")

import contextlib

from ..interfaces import IProcessManager, ProcessInfo


class PosixProcessManager(IProcessManager):
    """POSIX 进程管理器 (macOS/Linux 通用)"""

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
        创建 POSIX 进程

        Args:
            command: 命令及参数列表
            cwd: 工作目录
            env: 环境变量
            capture_output: 是否捕获输出
            new_process_group: 是否创建新进程组
        """
        # POSIX 使用 preexec_fn 创建新进程组
        preexec_fn = os.setsid if new_process_group else None

        # 合并环境变量
        process_env = os.environ.copy()
        if env:
            process_env.update(env)

        process = subprocess.Popen(
            command,
            cwd=str(cwd) if cwd else None,
            env=process_env,
            stdout=subprocess.PIPE if capture_output else None,
            stderr=subprocess.PIPE if capture_output else None,
            text=True,
            preexec_fn=preexec_fn
        )

        return process

    def terminate_process(self, pid: int, force: bool = False) -> bool:
        """
        终止 POSIX 进程

        Args:
            pid: 进程ID
            force: 是否强制终止 (SIGKILL vs SIGTERM)
        """
        if self._use_psutil:
            try:
                process = psutil.Process(pid)
                if force:
                    process.kill()  # SIGKILL
                else:
                    process.terminate()  # SIGTERM
                return True
            except psutil.NoSuchProcess:
                return False
            except Exception as e:
                print(f"[PosixProcess] 终止进程失败: {e}")
                return False
        else:
            # 备用方案：使用 kill 命令
            try:
                sig = signal.SIGKILL if force else signal.SIGTERM
                os.kill(pid, sig)
                return True
            except ProcessLookupError:
                return False

    def send_signal(self, pid: int, signal_type: str) -> bool:
        """
        发送 POSIX 信号

        Args:
            pid: 进程ID
            signal_type: "term", "kill", "interrupt", "stop", "continue"
        """
        signal_map = {
            "term": signal.SIGTERM,
            "kill": signal.SIGKILL,
            "interrupt": signal.SIGINT,
            "stop": signal.SIGSTOP,
            "continue": signal.SIGCONT,
            "hup": signal.SIGHUP,
            "usr1": signal.SIGUSR1 if hasattr(signal, 'SIGUSR1') else None,
            "usr2": signal.SIGUSR2 if hasattr(signal, 'SIGUSR2') else None,
        }

        sig = signal_map.get(signal_type)
        if sig is None:
            print(f"[PosixProcess] 未知信号类型: {signal_type}")
            return False

        try:
            os.kill(pid, sig)
            return True
        except ProcessLookupError:
            return False
        except Exception as e:
            print(f"[PosixProcess] 发送信号失败: {e}")
            return False

    def get_processes(self) -> list[ProcessInfo]:
        """获取 POSIX 进程列表"""
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
                os.kill(pid, 0)  # 信号 0 用于检测进程是否存在
                return True
            except ProcessLookupError:
                return False
