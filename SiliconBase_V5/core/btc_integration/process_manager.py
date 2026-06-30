#!/usr/bin/env python3
"""
BTC 交易进程管理器

功能:
    - 管理 btc_system autopilot 进程
    - 进程间通信（文件监控）
    - 状态监控和日志收集
    - 进程生命周期管理（启动/停止/重启）

架构:
    ┌─────────────────────────────────────────┐
    │          BTCProcessManager              │
    ├─────────────────────────────────────────┤
    │  ┌─────────┐  ┌─────────────────────┐  │
    │  │ Process │  │ FileMonitor         │  │
    │  │ Handler │  │ (状态文件监控)       │  │
    │  └────┬────┘  └──────────┬──────────┘  │
    │       └───────────────────┘             │
    │  ┌─────────┐  ┌─────────────────────┐  │
    │  │ Logger  │  │ StateManager        │  │
    │  │ Capture │  │ (状态机管理)         │  │
    │  └─────────┘  └─────────────────────┘  │
    └─────────────────────────────────────────┘
"""

import contextlib
import json
import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


class ProcessStatus(Enum):
    """进程状态枚举"""
    IDLE = "idle"           # 空闲
    STARTING = "starting"   # 启动中
    RUNNING = "running"     # 运行中
    STOPPING = "stopping"   # 停止中
    STOPPED = "stopped"     # 已停止
    ERROR = "error"         # 错误
    CRASHED = "crashed"     # 崩溃


@dataclass
class ProcessState:
    """进程状态数据"""
    status: ProcessStatus
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
    """
    文件状态监控器

    通过监控 btc_system 生成的状态文件获取实时数据
    """

    def __init__(self, runtime_dir: str, callback: Callable | None = None):
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
                pass  # 静默处理文件读取错误

            time.sleep(2)  # 每 2 秒检查一次

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

        # 读取策略状态
        strategy_state = self._read_json_file("okx_demo_strategy_pnl_state.json")
        if strategy_state:
            state["strategy"] = strategy_state

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


class BTCProcessManager:
    """
    BTC 交易进程管理器

    管理 btc_system autopilot 进程的生命周期
    """

    def __init__(self, btc_system_path: str = None):
        # 优先使用项目内部路径，否则回退到U盘路径
        if btc_system_path is None:
            internal_path = Path(__file__).parent / "engine"
            btc_system_path = str(internal_path) if internal_path.exists() else "F:/btc_system_v1"  # 回退到U盘
        self.btc_system_path = Path(btc_system_path)
        self.runtime_dir = self.btc_system_path / ".runtime"

        # 进程状态
        self._state = ProcessState(status=ProcessStatus.IDLE)
        self._state_lock = threading.RLock()

        # 子进程
        self._process: subprocess.Popen | None = None

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

    def _on_state_update(self, state: dict[str, Any]):
        """状态更新回调"""
        # 更新内部状态
        autopilot = state.get("autopilot", {})
        if autopilot:
            with self._state_lock:
                # 更新持仓
                self._state.current_position = autopilot.get("positions", {})
                # 更新盈亏
                self._state.pnl_today = autopilot.get("pnl_today", 0)

        # 触发事件
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
            **kwargs: 其他参数

        Returns:
            bool: 是否成功启动
        """
        with self._state_lock:
            if self._state.status in [ProcessStatus.RUNNING, ProcessStatus.STARTING]:
                return False  # 已经在运行

            self._state.status = ProcessStatus.STARTING

        try:
            # 准备环境变量
            env = os.environ.copy()
            env["BTC_STRATEGY"] = strategy
            env["BTC_DURATION"] = str(duration_minutes)
            if symbols:
                env["BTC_SYMBOLS"] = ",".join(symbols)

            # 构建启动命令
            # 使用 btc_system 的 autopilot
            cmd = [
                "python",
                str(self.btc_system_path / "tools" / "okx_demo_runner.py"),
                "--strategy", strategy,
                "--duration", str(duration_minutes)
            ]

            # 启动进程
            self._process = subprocess.Popen(
                cmd,
                cwd=str(self.btc_system_path),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
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

            # 启动日志收集
            self._start_log_capture()

            self._trigger_event("started", {"pid": self._process.pid})
            return True

        except Exception as e:
            with self._state_lock:
                self._state.status = ProcessStatus.ERROR
                self._state.last_error = str(e)
            self._trigger_event("error", {"message": str(e)})
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
                return True  # 已经停止

            self._state.status = ProcessStatus.STOPPING

        try:
            # 停止文件监控
            self._file_monitor.stop()

            if self._process:
                # 发送终止信号
                if os.name == 'nt':
                    self._process.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    self._process.send_signal(signal.SIGTERM)

                # 等待进程退出
                try:
                    self._process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    # 强制终止
                    self._process.kill()
                    self._process.wait()

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
        # 通过写入信号文件通知 autopilot 暂停
        signal_file = self.runtime_dir / "pause_signal"
        try:
            signal_file.write_text("pause", encoding='utf-8')
            self._trigger_event("paused", {})
            return True
        except Exception:
            return False

    def resume(self) -> bool:
        """恢复交易"""
        signal_file = self.runtime_dir / "pause_signal"
        try:
            if signal_file.exists():
                signal_file.unlink()
            self._trigger_event("resumed", {})
            return True
        except Exception:
            return False

    def _start_log_capture(self):
        """启动日志收集"""
        if not self._process:
            return

        def capture_stdout():
            if self._process and self._process.stdout:
                for line in self._process.stdout:
                    self._add_log(line.strip())

        def capture_stderr():
            if self._process and self._process.stderr:
                for line in self._process.stderr:
                    self._add_log(f"[ERROR] {line.strip()}")

        threading.Thread(target=capture_stdout, daemon=True).start()
        threading.Thread(target=capture_stderr, daemon=True).start()

    def _add_log(self, message: str):
        """添加日志"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._logs.append(f"[{timestamp}] {message}")
        if len(self._logs) > self._max_logs:
            self._logs = self._logs[-self._max_logs:]

    def get_logs(self, tail: int = 100) -> list[str]:
        """获取日志"""
        return self._logs[-tail:]

    def get_report(self) -> dict[str, Any]:
        """生成运行报告"""
        state = self.get_state()
        file_state = self._file_monitor.get_current_state()

        return {
            "status": state.status.value,
            "pid": state.pid,
            "runtime_seconds": state.runtime_seconds,
            "pnl_today": state.pnl_today,
            "trades_count": state.trades_count,
            "current_position": state.current_position,
            "restart_count": state.restart_count,
            "last_error": state.last_error,
            "autopilot_state": file_state.get("autopilot", {}),
            "logs_tail": self.get_logs(50)
        }


# 全局管理器实例
_process_manager: BTCProcessManager | None = None


def get_btc_process_manager(btc_system_path: str = "F:/btc_system_v1") -> BTCProcessManager:
    """获取进程管理器单例"""
    global _process_manager
    if _process_manager is None:
        _process_manager = BTCProcessManager(btc_system_path)
    return _process_manager
