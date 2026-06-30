#!/usr/bin/env python3
"""
BTC 交易进程管理器 V2 - 跨平台版本

使用 core.platform_adapter 抽象层，支持 Windows、macOS、Linux。

重大改进:
1. 跨平台支持 - 使用平台抽象层
2. 更好的错误处理
3. 支持远程 BTC System (通过 SSH/MCP)
4. 更完善的进程生命周期管理
"""

import contextlib
import json
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

# 引入平台抽象层
try:
    from core.platform_adapter import platform_factory
    PLATFORM_AVAILABLE = True
except ImportError:
    PLATFORM_AVAILABLE = False
    print("[BTCProcessManagerV2] 警告: platform 模块不可用，使用兼容模式")


class ProcessStatus(Enum):
    """进程状态枚举"""
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    PAUSING = "pausing"
    PAUSED = "paused"
    RESUMING = "resuming"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"
    CRASHED = "crashed"


@dataclass
class ProcessState:
    """进程状态数据"""
    status: ProcessStatus = ProcessStatus.IDLE
    pid: int | None = None
    start_time: float | None = None
    end_time: float | None = None
    runtime_seconds: float = 0.0
    last_error: str = ""
    restart_count: int = 0

    # 交易状态
    current_position: dict[str, Any] = field(default_factory=dict)
    pnl_today: float = 0.0
    trades_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "pid": self.pid,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "runtime_seconds": self.runtime_seconds,
            "last_error": self.last_error,
            "restart_count": self.restart_count,
            "current_position": self.current_position,
            "pnl_today": self.pnl_today,
            "trades_count": self.trades_count
        }


class FileStateMonitor:
    """文件状态监控器 - 跨平台"""

    def __init__(self, runtime_dir: Path, callback: Callable | None = None):
        self.runtime_dir = Path(runtime_dir)
        self.callback = callback
        self._monitoring = False
        self._monitor_thread: threading.Thread | None = None
        self._last_modified = 0
        self._current_state: dict[str, Any] = {}

    def start(self):
        """启动监控"""
        if self._monitoring:
            return

        self._monitoring = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    def stop(self):
        """停止监控"""
        self._monitoring = False
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=2)

    def _monitor_loop(self):
        """监控循环"""
        while self._monitoring:
            try:
                state = self._read_state_files()
                if state != self._current_state:
                    self._current_state = state
                    if self.callback:
                        self.callback(state)
            except Exception:
                pass

            time.sleep(2)

    def _read_state_files(self) -> dict[str, Any]:
        """读取状态文件"""
        state = {
            "timestamp": time.time(),
            "autopilot": {},
            "positions": {},
            "pnl": {}
        }

        if not self.runtime_dir.exists():
            return state

        # 读取 autopilot 状态
        autopilot_state = self._read_json_file("okx_demo_autopilot_state.json")
        if autopilot_state:
            state["autopilot"] = autopilot_state

        # 读取 PnL 状态
        pnl_state = self._read_json_file("okx_demo_pnl_baseline.json")
        if pnl_state:
            state["pnl"] = pnl_state

        return state

    def _read_json_file(self, filename: str) -> dict[str, Any] | None:
        """读取 JSON 文件"""
        filepath = self.runtime_dir / filename
        if not filepath.exists():
            return None

        try:
            with open(filepath, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None

    def get_current_state(self) -> dict[str, Any]:
        """获取当前状态"""
        return self._current_state.copy()


class BTCProcessManagerV2:
    """
    BTC 交易进程管理器 V2 - 跨平台版本

    支持:
    - 本地 BTC System (Windows/macOS/Linux)
    - 远程 BTC System (通过 SSH/MCP)
    """

    def __init__(self, btc_system_path: str | None = None, remote_host: str | None = None):
        """
        初始化进程管理器

        Args:
            btc_system_path: BTC System 本地路径
            remote_host: 远程主机 (可选，格式: user@host)
        """
        self.remote_host = remote_host

        # 本地路径设置
        if btc_system_path is None:
            # 尝试自动检测路径
            btc_system_path = self._auto_detect_btc_path()

        self.btc_system_path = Path(btc_system_path) if btc_system_path else None

        if self.btc_system_path:
            self.runtime_dir = self.btc_system_path / ".runtime"
        else:
            self.runtime_dir = Path(".runtime")

        # 进程状态
        self._state = ProcessState()
        self._state_lock = threading.RLock()

        # 进程对象
        self._process: Any | None = None

        # 文件监控
        self._file_monitor = FileStateMonitor(
            runtime_dir=self.runtime_dir,
            callback=self._on_state_update
        )

        # 日志收集
        self._logs: list[str] = []
        self._max_logs = 1000

        # 事件回调
        self._event_callbacks: list[Callable[[str, dict], None]] = []

        # 平台进程管理器
        self._platform_process = None
        if PLATFORM_AVAILABLE:
            self._platform_process = platform_factory.get_process_manager()

    def _auto_detect_btc_path(self) -> str | None:
        """自动检测 BTC System 路径"""
        # 常见路径列表
        possible_paths = [
            # Windows
            r"F:\btc_system_v1",
            r"C:\btc_system_v1",
            r"D:\btc_system_v1",
            r"E:\btc_system_v1",
            # macOS/Linux (通过WSL/远程)
            "/home/user/btc_system_v1",
            "/opt/btc_system_v1",
            "~/btc_system_v1",
        ]

        for path in possible_paths:
            expanded = Path(path).expanduser()
            if expanded.exists() and (expanded / "config.yml").exists():
                print(f"[BTCProcessManagerV2] 自动检测到 BTC System: {expanded}")
                return str(expanded)

        return None

    def _on_state_update(self, state: dict[str, Any]):
        """状态更新回调"""
        autopilot = state.get("autopilot", {})
        if autopilot:
            with self._state_lock:
                self._state.current_position = autopilot.get("positions", {})
                self._state.pnl_today = autopilot.get("pnl_today", 0)

        self._trigger_event("state_update", state)

    def _trigger_event(self, event_type: str, data: dict[str, Any]):
        """触发事件"""
        for callback in self._event_callbacks:
            with contextlib.suppress(Exception):
                callback(event_type, data)

    def register_event_callback(self, callback: Callable[[str, dict], None]):
        """注册事件回调"""
        self._event_callbacks.append(callback)

    def get_state(self) -> ProcessState:
        """获取当前状态"""
        with self._state_lock:
            # 更新运行时间
            if self._state.start_time and self._state.status == ProcessStatus.RUNNING:
                self._state.runtime_seconds = time.time() - self._state.start_time

            # 返回副本
            return ProcessState(
                status=self._state.status,
                pid=self._state.pid,
                start_time=self._state.start_time,
                end_time=self._state.end_time,
                runtime_seconds=self._state.runtime_seconds,
                last_error=self._state.last_error,
                restart_count=self._state.restart_count,
                current_position=self._state.current_position.copy(),
                pnl_today=self._state.pnl_today,
                trades_count=self._state.trades_count
            )

    def start(
        self,
        strategy: str = "stage46_aggressive",
        duration_minutes: int = 60,
        symbols: list[str] | None = None,
        **kwargs
    ) -> bool:
        """
        启动交易进程

        Args:
            strategy: 策略 ID
            duration_minutes: 运行时长（分钟）
            symbols: 交易标的列表

        Returns:
            bool: 是否成功启动
        """
        if self.remote_host:
            return self._start_remote(strategy, duration_minutes, symbols, **kwargs)
        else:
            return self._start_local(strategy, duration_minutes, symbols, **kwargs)

    def _start_local(
        self,
        strategy: str,
        duration_minutes: int,
        symbols: list[str] | None,
        **kwargs
    ) -> bool:
        """启动本地进程"""
        with self._state_lock:
            if self._state.status in [ProcessStatus.RUNNING, ProcessStatus.STARTING]:
                print("[BTCProcessManagerV2] 已经在运行中")
                return False

            self._state.status = ProcessStatus.STARTING

        try:
            # 准备环境变量
            env = os.environ.copy()
            env["BTC_STRATEGY"] = strategy
            env["BTC_DURATION"] = str(duration_minutes)
            if symbols:
                env["BTC_SYMBOLS"] = ",".join(symbols)

            # 构建启动命令
            if platform_factory.is_windows():
                # Windows: 直接运行 Python
                cmd = [
                    "python",
                    str(self.btc_system_path / "tools" / "okx_demo_runner.py"),
                    "--strategy", strategy,
                    "--duration", str(duration_minutes)
                ]
            else:
                # macOS/Linux: 使用 .sh 脚本或 Python
                script_path = self.btc_system_path / "start_okx_demo.sh"
                if script_path.exists():
                    cmd = ["bash", str(script_path)]
                else:
                    cmd = [
                        "python3",
                        str(self.btc_system_path / "tools" / "okx_demo_runner.py"),
                        "--strategy", strategy,
                        "--duration", str(duration_minutes)
                    ]

            print(f"[BTCProcessManagerV2] 启动命令: {' '.join(cmd)}")

            # 使用平台抽象层创建进程
            if self._platform_process:
                self._process = self._platform_process.create_process(
                    cmd,
                    cwd=self.btc_system_path,
                    env=env,
                    capture_output=True,
                    new_process_group=True
                )
            else:
                # 兼容模式
                import subprocess
                creationflags = 0
                if os.name == 'nt':
                    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

                self._process = subprocess.Popen(
                    cmd,
                    cwd=str(self.btc_system_path),
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    creationflags=creationflags
                )

            # 等待进程启动
            time.sleep(2)

            if self._process.poll() is not None:
                # 进程已退出
                stdout, stderr = self._process.communicate()
                error_msg = stderr or stdout or "进程启动失败"
                with self._state_lock:
                    self._state.status = ProcessStatus.ERROR
                    self._state.last_error = error_msg
                self._trigger_event("error", {"message": error_msg})
                return False

            # 启动成功
            with self._state_lock:
                self._state.status = ProcessStatus.RUNNING
                self._state.pid = self._process.pid
                self._state.start_time = time.time()
                self._state.end_time = None

            # 启动文件监控
            self._file_monitor.start()

            self._trigger_event("started", {"pid": self._process.pid})
            return True

        except Exception as e:
            with self._state_lock:
                self._state.status = ProcessStatus.ERROR
                self._state.last_error = str(e)
            self._trigger_event("error", {"message": str(e)})
            return False

    def _start_remote(self, strategy: str, duration_minutes: int, symbols: list[str] | None, **kwargs) -> bool:
        """启动远程进程 (通过 SSH)"""
        # TODO: 实现 SSH 远程启动
        print(f"[BTCProcessManagerV2] 远程启动暂未实现: {self.remote_host}")
        return False

    def stop(self, timeout: int = 30) -> bool:
        """
        停止交易进程

        Args:
            timeout: 等待超时（秒）

        Returns:
            bool: 是否成功停止
        """
        with self._state_lock:
            if self._state.status not in [ProcessStatus.RUNNING, ProcessStatus.STARTING]:
                return True

            self._state.status = ProcessStatus.STOPPING

        try:
            # 停止文件监控
            self._file_monitor.stop()

            if self._process:
                # 使用平台抽象层停止进程
                if self._platform_process and self._process.pid:
                    # 先尝试优雅停止
                    if platform_factory.is_windows():
                        self._platform_process.send_signal(self._process.pid, "break")
                    else:
                        self._platform_process.send_signal(self._process.pid, "term")

                    # 等待进程退出
                    try:
                        self._process.wait(timeout=timeout)
                    except Exception:
                        # 强制终止
                        self._platform_process.terminate_process(self._process.pid, force=True)
                else:
                    # 兼容模式
                    import signal
                    if os.name == 'nt':
                        self._process.send_signal(signal.CTRL_BREAK_EVENT)
                    else:
                        self._process.terminate()

                    try:
                        self._process.wait(timeout=timeout)
                    except Exception:
                        self._process.kill()

            with self._state_lock:
                self._state.status = ProcessStatus.STOPPED
                self._state.end_time = time.time()
                if self._state.start_time:
                    self._state.runtime_seconds = self._state.end_time - self._state.start_time

            self._trigger_event("stopped", {})
            return True

        except Exception as e:
            with self._state_lock:
                self._state.status = ProcessStatus.ERROR
                self._state.last_error = str(e)
            return False

    def pause(self) -> bool:
        """暂停交易（保持持仓，暂停新开仓）"""
        signal_file = self.runtime_dir / "pause_signal"
        try:
            signal_file.write_text("pause", encoding='utf-8')
            with self._state_lock:
                self._state.status = ProcessStatus.PAUSED
            return True
        except Exception as e:
            print(f"[BTCProcessManagerV2] 暂停失败: {e}")
            return False

    def resume(self) -> bool:
        """恢复交易"""
        signal_file = self.runtime_dir / "pause_signal"
        try:
            if signal_file.exists():
                signal_file.unlink()
            with self._state_lock:
                if self._state.status == ProcessStatus.PAUSED:
                    self._state.status = ProcessStatus.RUNNING
            return True
        except Exception as e:
            print(f"[BTCProcessManagerV2] 恢复失败: {e}")
            return False

    def get_report(self) -> dict[str, Any]:
        """获取运行报告"""
        state = self.get_state()
        file_state = self._file_monitor.get_current_state()

        return {
            "status": state.status.value,
            "pid": state.pid,
            "runtime_seconds": state.runtime_seconds,
            "pnl_today": state.pnl_today,
            "trades_count": state.trades_count,
            "current_position": state.current_position,
            "last_error": state.last_error,
            "autopilot_state": file_state.get("autopilot", {}),
            "pnl_state": file_state.get("pnl", {})
        }


# 全局实例
_btc_process_manager: BTCProcessManagerV2 | None = None


def get_btc_process_manager(btc_path: str | None = None) -> BTCProcessManagerV2:
    """获取 BTC 进程管理器实例（单例）"""
    global _btc_process_manager
    if _btc_process_manager is None:
        _btc_process_manager = BTCProcessManagerV2(btc_path)
    return _btc_process_manager


# =============================================================================
# 新版本: 使用 BTCSystemClient 的进程管理器
# =============================================================================

from core.btc_integration.btc_system_client import get_btc_system_client


class BTCProcessManagerV3:
    """
    BTC 进程管理器 V3 - 基于 BTCSystemClient

    使用V5 platform层实现跨平台进程管理
    """

    def __init__(self, btc_system_path: str | None = None):
        """
        初始化进程管理器

        Args:
            btc_system_path: btc_system路径，为None时自动检测
        """
        self.client = get_btc_system_client(
            Path(btc_system_path) if btc_system_path else None
        )
        print(f"[BTCProcessManagerV3] 初始化完成: {self.client.btc_path}")

    def start(
        self,
        strategy: str = "stage46_aggressive",
        duration_minutes: int = 60,
        symbols: list[str] | None = None,
        **kwargs
    ) -> bool:
        """
        启动autopilot

        Args:
            strategy: 策略ID
            duration_minutes: 运行时长（分钟）
            symbols: 交易标的列表

        Returns:
            是否成功启动
        """
        return self.client.start_autopilot(
            strategy=strategy,
            duration_minutes=duration_minutes,
            symbols=symbols,
            confirm_demo=True
        )

    def stop(self, timeout: int = 30) -> bool:
        """
        停止autopilot

        Args:
            timeout: 等待超时（秒）

        Returns:
            是否成功停止
        """
        return self.client.stop_autopilot(timeout=timeout)

    def pause(self) -> bool:
        """暂停交易"""
        return self.client.pause_autopilot()

    def resume(self) -> bool:
        """恢复交易"""
        return self.client.resume_autopilot()

    def get_state(self) -> dict[str, Any]:
        """获取当前状态"""
        return self.client.get_state()

    def get_report(self) -> dict[str, Any]:
        """获取运行报告"""
        state = self.client.get_autopilot_state()
        return {
            "status": state.status,
            "pid": state.pid,
            "version": state.version,
            "strategy_name": state.strategy_name,
            "pnl_today": state.pnl_today,
            "trades_count": state.trades_count,
            "positions": state.positions,
            "coinglass_mode": state.coinglass_mode,
            "coinglass_reason": state.coinglass_reason,
            "last_update": state.last_update,
            "btc_system_path": str(self.client.btc_path)
        }


def get_btc_process_manager_v3(btc_path: str | None = None) -> BTCProcessManagerV3:
    """获取基于BTCSystemClient的进程管理器"""
    return BTCProcessManagerV3(btc_path)
