#!/usr/bin/env python3
"""
平台抽象接口定义

定义所有平台必须实现的能力接口。
"""

import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class PlatformType(Enum):
    """平台类型枚举"""
    WINDOWS = "windows"
    MACOS = "darwin"
    LINUX = "linux"


@dataclass
class ProcessInfo:
    """进程信息"""
    pid: int
    name: str
    status: str
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    create_time: float = 0.0


@dataclass
class WindowInfo:
    """窗口信息"""
    window_id: Any  # 平台相关的窗口句柄
    title: str
    rect: tuple[int, int, int, int]  # left, top, right, bottom
    is_active: bool = False
    is_minimized: bool = False


@dataclass
class Screenshot:
    """截图结果"""
    data: bytes  # PNG/JPG 数据
    width: int
    height: int
    format: str = "png"


# ============================================================================
# 进程管理接口
# ============================================================================

class IProcessManager(ABC):
    """跨平台进程管理接口"""

    @abstractmethod
    def create_process(
        self,
        command: list[str],
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        capture_output: bool = True,
        new_process_group: bool = False
    ) -> subprocess.Popen:
        """
        创建新进程

        Args:
            command: 命令及参数列表
            cwd: 工作目录
            env: 环境变量
            capture_output: 是否捕获输出
            new_process_group: 是否创建新进程组(用于分离子进程)

        Returns:
            subprocess.Popen 对象
        """
        pass

    @abstractmethod
    def terminate_process(self, pid: int, force: bool = False) -> bool:
        """
        终止进程

        Args:
            pid: 进程ID
            force: 是否强制终止

        Returns:
            是否成功终止
        """
        pass

    @abstractmethod
    def send_signal(self, pid: int, signal_type: str) -> bool:
        """
        发送信号

        Args:
            pid: 进程ID
            signal_type: "term", "kill", "interrupt", "break", "stop", "continue"

        Returns:
            是否成功发送
        """
        pass

    @abstractmethod
    def get_processes(self) -> list[ProcessInfo]:
        """获取所有进程列表"""
        pass

    @abstractmethod
    def get_process(self, pid: int) -> ProcessInfo | None:
        """获取指定进程信息"""
        pass

    @abstractmethod
    def is_process_running(self, pid: int) -> bool:
        """检查进程是否运行中"""
        pass


# ============================================================================
# 屏幕捕获接口
# ============================================================================

class IScreenCapture(ABC):
    """跨平台屏幕捕获接口"""

    @abstractmethod
    def capture_fullscreen(self) -> Screenshot:
        """捕获全屏"""
        pass

    @abstractmethod
    def capture_region(self, left: int, top: int, width: int, height: int) -> Screenshot:
        """捕获指定区域"""
        pass

    @abstractmethod
    def capture_window(self, window_id: Any) -> Screenshot | None:
        """捕获指定窗口"""
        pass

    @abstractmethod
    def get_screen_size(self) -> tuple[int, int]:
        """获取屏幕尺寸"""
        pass

    @abstractmethod
    def list_monitors(self) -> list[dict[str, Any]]:
        """获取所有显示器信息"""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """检查截图功能是否可用"""
        pass


# ============================================================================
# 窗口管理接口
# ============================================================================

class IWindowManager(ABC):
    """跨平台窗口管理接口"""

    @abstractmethod
    def list_windows(self) -> list[WindowInfo]:
        """列出所有窗口"""
        pass

    @abstractmethod
    def find_window(self, title_pattern: str) -> WindowInfo | None:
        """根据标题查找窗口"""
        pass

    @abstractmethod
    def activate_window(self, window_id: Any) -> bool:
        """激活窗口(前置)"""
        pass

    @abstractmethod
    def minimize_window(self, window_id: Any) -> bool:
        """最小化窗口"""
        pass

    @abstractmethod
    def maximize_window(self, window_id: Any) -> bool:
        """最大化窗口"""
        pass

    @abstractmethod
    def restore_window(self, window_id: Any) -> bool:
        """恢复窗口"""
        pass

    @abstractmethod
    def get_active_window(self) -> WindowInfo | None:
        """获取当前活动窗口"""
        pass

    @abstractmethod
    def move_window(self, window_id: Any, x: int, y: int, width: int, height: int) -> bool:
        """移动/调整窗口"""
        pass

    @abstractmethod
    def close_window(self, window_id: Any) -> bool:
        """关闭窗口"""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """检查窗口管理功能是否可用"""
        pass


# ============================================================================
# Shell 执行接口
# ============================================================================

class IShellExecutor(ABC):
    """跨平台 Shell 执行接口"""

    @abstractmethod
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
        pass

    @abstractmethod
    def execute_async(
        self,
        command: str | list[str],
        shell: bool = False,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None
    ) -> subprocess.Popen:
        """异步执行，返回进程对象"""
        pass

    @abstractmethod
    def which(self, executable: str) -> str | None:
        """查找可执行文件路径"""
        pass

    @abstractmethod
    def get_shell_type(self) -> str:
        """获取当前 shell 类型"""
        pass

    @abstractmethod
    def script_ext(self) -> str:
        """获取脚本文件扩展名 (.sh 或 .bat)"""
        pass


# ============================================================================
# 系统信息接口
# ============================================================================

class ISystemInfo(ABC):
    """跨平台系统信息接口"""

    @abstractmethod
    def get_platform(self) -> PlatformType:
        """获取平台类型"""
        pass

    @abstractmethod
    def get_os_version(self) -> str:
        """获取操作系统版本"""
        pass

    @abstractmethod
    def get_cpu_info(self) -> dict[str, Any]:
        """获取CPU信息"""
        pass

    @abstractmethod
    def get_memory_info(self) -> dict[str, Any]:
        """获取内存信息"""
        pass

    @abstractmethod
    def get_disk_usage(self, path: str = "/") -> dict[str, Any]:
        """获取磁盘使用情况"""
        pass

    @abstractmethod
    def get_env_separator(self) -> str:
        """获取环境变量分隔符 (; 或 :)"""
        pass
