#!/usr/bin/env python3
"""
平台工厂 - 自动检测平台并创建对应实现

使用方法:
    from core.platform_adapter import platform_factory

    # 获取当前平台类型
    if platform_factory.is_windows():
        print("Running on Windows")

    # 获取进程管理器
    process_mgr = platform_factory.get_process_manager()
    process_mgr.terminate_process(pid)
"""

import platform as pf
from typing import Optional

from .interfaces import IProcessManager, IScreenCapture, IShellExecutor, ISystemInfo, IWindowManager, PlatformType


class PlatformFactory:
    """平台工厂 - 单例模式"""

    _instance: Optional['PlatformFactory'] = None
    _platform_type: PlatformType | None = None

    # 缓存的实现实例
    _process_manager: IProcessManager | None = None
    _screen_capture: IScreenCapture | None = None
    _window_manager: IWindowManager | None = None
    _shell_executor: IShellExecutor | None = None
    _system_info: ISystemInfo | None = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._detect_platform()
        return cls._instance

    def _detect_platform(self):
        """自动检测当前平台"""
        system = pf.system().lower()

        if system == "windows" or system == "win32":
            self._platform_type = PlatformType.WINDOWS
        elif system == "darwin":
            self._platform_type = PlatformType.MACOS
        elif system == "linux":
            self._platform_type = PlatformType.LINUX
        else:
            # 默认尝试 POSIX 方式
            print(f"[Platform] 未知操作系统 '{system}'，尝试使用 POSIX 兼容模式")
            self._platform_type = PlatformType.LINUX

        print(f"[Platform] 检测到平台: {self._platform_type.value}")

    @property
    def platform_type(self) -> PlatformType:
        """获取当前平台类型"""
        return self._platform_type

    def is_windows(self) -> bool:
        """是否为 Windows 平台"""
        return self._platform_type == PlatformType.WINDOWS

    def is_macos(self) -> bool:
        """是否为 macOS 平台"""
        return self._platform_type == PlatformType.MACOS

    def is_linux(self) -> bool:
        """是否为 Linux 平台"""
        return self._platform_type == PlatformType.LINUX

    def is_posix(self) -> bool:
        """是否为 POSIX 兼容平台 (macOS/Linux)"""
        return self._platform_type in (PlatformType.MACOS, PlatformType.LINUX)

    # =======================================================================
    # 懒加载获取各平台实现
    # =======================================================================

    def get_process_manager(self) -> IProcessManager:
        """获取进程管理器"""
        if self._process_manager is None:
            try:
                if self.is_windows():
                    from .windows.process import WindowsProcessManager
                    self._process_manager = WindowsProcessManager()
                else:
                    from .posix.process import PosixProcessManager
                    self._process_manager = PosixProcessManager()
            except Exception as e:
                print(f"[Platform] 进程管理器初始化失败: {e}")
                raise
        return self._process_manager

    def get_screen_capture(self) -> IScreenCapture:
        """获取屏幕捕获器"""
        if self._screen_capture is None:
            try:
                # MSS 支持所有平台
                from .universal.mss_capture import MSSScreenCapture
                self._screen_capture = MSSScreenCapture()
            except Exception as e:
                print(f"[Platform] 屏幕捕获器初始化失败: {e}")
                # 返回空实现
                from .universal.null_capture import NullScreenCapture
                self._screen_capture = NullScreenCapture()
        return self._screen_capture

    def get_window_manager(self) -> IWindowManager:
        """获取窗口管理器"""
        if self._window_manager is None:
            try:
                if self.is_windows():
                    from .windows.window import WindowsWindowManager
                    self._window_manager = WindowsWindowManager()
                elif self.is_macos():
                    from .macos.window import MacOSWindowManager
                    self._window_manager = MacOSWindowManager()
                else:
                    from .linux.window import LinuxWindowManager
                    self._window_manager = LinuxWindowManager()
            except Exception as e:
                print(f"[Platform] 窗口管理器初始化失败: {e}")
                # 返回空实现
                from .universal.null_window import NullWindowManager
                self._window_manager = NullWindowManager()
        return self._window_manager

    def get_shell_executor(self) -> IShellExecutor:
        """获取 Shell 执行器"""
        if self._shell_executor is None:
            try:
                if self.is_windows():
                    from .windows.shell import WindowsShellExecutor
                    self._shell_executor = WindowsShellExecutor()
                else:
                    from .posix.shell import PosixShellExecutor
                    self._shell_executor = PosixShellExecutor()
            except Exception as e:
                print(f"[Platform] Shell 执行器初始化失败: {e}")
                raise
        return self._shell_executor

    def get_system_info(self) -> ISystemInfo:
        """获取系统信息"""
        if self._system_info is None:
            try:
                if self.is_windows():
                    from .windows.system import WindowsSystemInfo
                    self._system_info = WindowsSystemInfo()
                else:
                    from .posix.system import PosixSystemInfo
                    self._system_info = PosixSystemInfo()
            except Exception as e:
                print(f"[Platform] 系统信息初始化失败: {e}")
                raise
        return self._system_info


# 全局工厂实例
platform_factory = PlatformFactory()
