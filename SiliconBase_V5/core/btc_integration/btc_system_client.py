#!/usr/bin/env python3
"""
BTC System 统一客户端 - V5 Platform集成版

功能:
    - 自动检测btc_system路径（多端）
    - 使用V5 platform层管理进程
    - 统一的状态文件监控
    - 跨平台的启动/停止/暂停控制

使用示例:
    from core.btc_integration.btc_system_client import BTCSystemClient

    client = BTCSystemClient()

    # 启动autopilot
    client.start_autopilot(strategy="stage46_aggressive", duration_minutes=60)

    # 获取状态
    state = client.get_state()
    print(f"Status: {state.get('status')}, PnL: {state.get('pnl_today')}")

    # 停止
    client.stop_autopilot()
"""

import json
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# V5 platform层
from core.platform_adapter import PathResolver, platform_factory, resolve_btc_system_path


@dataclass
class AutopilotState:
    """Autopilot状态数据"""
    status: str = "unknown"
    pid: int | None = None
    version: str = ""
    strategy_name: str = ""
    pnl_today: float = 0.0
    trades_count: int = 0
    positions: dict[str, Any] = field(default_factory=dict)
    coinglass_mode: str = ""
    coinglass_reason: str = ""
    last_update: float | None = None
    error_message: str = ""


class BTCSystemClient:
    """
    BTC System 统一客户端

    通过V5 platform层实现跨平台调用，支持:
    - Windows: CREATE_NEW_PROCESS_GROUP
    - macOS/Linux: preexec_fn=os.setsid
    """

    def __init__(self, btc_system_path: Path | None = None):
        """
        初始化BTC System客户端

        Args:
            btc_system_path: btc_system路径，为None时自动检测
        """
        # 路径解析
        if btc_system_path:
            self.btc_path = Path(btc_system_path).resolve()
        else:
            self.btc_path = resolve_btc_system_path()

        if not self.btc_path:
            raise RuntimeError(
                "BTC System not found. "
                "请确保btc_system位于以下位置之一:\n"
                "  - E:/SiliconBase_V5/SiliconBase_V5/btc_system\n"
                "  - F:/btc_system_v1\n"
                "  - ~/btc_system_v1"
            )

        # 验证路径有效性
        if not (self.btc_path / "config.yml").exists():
            raise RuntimeError(f"无效的BTC System路径: {self.btc_path}")

        # 初始化路径解析器
        self.paths = PathResolver(self.btc_path)

        # 进程管理
        self._process: subprocess.Popen | None = None
        self._process_mgr = platform_factory.get_process_manager()

        # 状态监控
        self._state = AutopilotState()
        self._state_lock = threading.RLock()
        self._monitor_thread: threading.Thread | None = None
        self._monitoring = False

        print(f"[BTCSystemClient] 路径: {self.btc_path}")
        print(f"[BTCSystemClient] 平台: {platform_factory.platform_type.value}")

    # ========================================================================
    # 核心控制方法
    # ========================================================================

    def start_autopilot(
        self,
        strategy: str = "stage46_aggressive",
        duration_minutes: int = 60,
        symbols: list[str] | None = None,
        confirm_demo: bool = True,
        **kwargs
    ) -> bool:
        """
        启动autopilot

        Args:
            strategy: 策略ID
            duration_minutes: 运行时长（分钟）
            symbols: 交易对列表，如 ["btc", "bnb"]
            confirm_demo: 是否确认demo模式
            **kwargs: 额外参数

        Returns:
            是否成功启动
        """
        # 检查是否已在运行
        if self._is_running():
            print("[BTCSystemClient] 警告: autopilot已在运行中")
            return False

        # 构建命令
        cmd = [
            platform_factory.get_python_path() or ("python" if platform_factory.is_windows() else "python3"),
            "-m", "tools.okx_demo_autopilot",
            "--project-dir", str(self.btc_path),
            "--strategy", strategy,
            "--duration", str(duration_minutes),
        ]

        if confirm_demo:
            cmd.append("--confirm-demo")

        if symbols:
            cmd.extend(["--symbols", ",".join(symbols)])

        print(f"[BTCSystemClient] 启动命令: {' '.join(cmd)}")

        try:
            # 使用platform层创建进程
            self._process = self._process_mgr.create_process(
                cmd,
                cwd=self.btc_path,
                capture_output=False,
                new_process_group=True
            )

            # 更新状态
            with self._state_lock:
                self._state.status = "starting"
                self._state.pid = self._process.pid

            # 启动监控线程
            self._start_monitoring()

            print(f"[BTCSystemClient] autopilot已启动 (PID: {self._process.pid})")
            return True

        except Exception as e:
            with self._state_lock:
                self._state.status = "error"
                self._state.error_message = str(e)
            print(f"[BTCSystemClient] 启动失败: {e}")
            return False

    def stop_autopilot(self, timeout: int = 30, force: bool = False) -> bool:
        """
        停止autopilot

        Args:
            timeout: 等待超时（秒）
            force: 是否强制终止

        Returns:
            是否成功停止
        """
        if not self._process:
            print("[BTCSystemClient] 没有运行中的进程")
            return True

        print(f"[BTCSystemClient] 正在停止autopilot (PID: {self._process.pid})...")

        try:
            # 停止监控
            self._stop_monitoring()

            if force:
                # 强制终止
                self._process_mgr.terminate_process(self._process.pid, force=True)
            else:
                # 发送停止信号
                if platform_factory.is_windows():
                    self._process_mgr.send_signal(self._process.pid, "break")
                else:
                    self._process_mgr.send_signal(self._process.pid, "term")

                # 等待进程退出
                try:
                    self._process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    print("[BTCSystemClient] 超时，强制终止")
                    self._process_mgr.terminate_process(self._process.pid, force=True)

            # 清理PID文件
            self._cleanup_pid_file()

            with self._state_lock:
                self._state.status = "stopped"
                self._state.pid = None

            self._process = None
            print("[BTCSystemClient] autopilot已停止")
            return True

        except Exception as e:
            print(f"[BTCSystemClient] 停止失败: {e}")
            return False

    def pause_autopilot(self) -> bool:
        """
        暂停autopilot（保持持仓，暂停新开仓）

        通过写入信号文件通知autopilot暂停

        Returns:
            是否成功暂停
        """
        try:
            signal_file = self.paths.get_runtime_dir() / "pause_signal"
            signal_file.write_text("pause", encoding='utf-8')

            with self._state_lock:
                if self._state.status == "running":
                    self._state.status = "paused"

            print("[BTCSystemClient] 暂停信号已发送")
            return True

        except Exception as e:
            print(f"[BTCSystemClient] 暂停失败: {e}")
            return False

    def resume_autopilot(self) -> bool:
        """
        恢复autopilot

        删除暂停信号文件

        Returns:
            是否成功恢复
        """
        try:
            signal_file = self.paths.get_runtime_dir() / "pause_signal"
            if signal_file.exists():
                signal_file.unlink()

            with self._state_lock:
                if self._state.status == "paused":
                    self._state.status = "running"

            print("[BTCSystemClient] 恢复信号已发送")
            return True

        except Exception as e:
            print(f"[BTCSystemClient] 恢复失败: {e}")
            return False

    # ========================================================================
    # 状态查询方法
    # ========================================================================

    def get_state(self) -> dict[str, Any]:
        """
        获取autopilot当前状态

        从.runtime/状态文件读取

        Returns:
            状态字典
        """
        return self._read_state_file()

    def get_autopilot_state(self) -> AutopilotState:
        """
        获取结构化的autopilot状态

        Returns:
            AutopilotState对象
        """
        with self._state_lock:
            state_data = self._read_state_file()

            self._state.status = state_data.get("status", "unknown")
            self._state.version = state_data.get("version", "")
            self._state.strategy_name = state_data.get("strategy_name", "")
            self._state.coinglass_mode = state_data.get("coinglass_mode", "")
            self._state.coinglass_reason = state_data.get("coinglass_reason", "")
            self._state.last_update = time.time()

            # 提取PnL信息
            exec_report = state_data.get("execution_report", {})
            if exec_report:
                self._state.pnl_today = exec_report.get("pnl_today", 0)
                self._state.positions = exec_report.get("positions", {})

            return AutopilotState(
                status=self._state.status,
                pid=self._state.pid,
                version=self._state.version,
                strategy_name=self._state.strategy_name,
                pnl_today=self._state.pnl_today,
                trades_count=self._state.trades_count,
                positions=self._state.positions.copy(),
                coinglass_mode=self._state.coinglass_mode,
                coinglass_reason=self._state.coinglass_reason,
                last_update=self._state.last_update,
                error_message=self._state.error_message
            )

    def is_running(self) -> bool:
        """
        检查autopilot是否正在运行

        Returns:
            是否运行中
        """
        return self._is_running()

    def get_runtime_report(self) -> Path | None:
        """
        获取运行时报告文件路径

        Returns:
            报告文件Path或None
        """
        report_path = self.paths.get_runtime_dir() / "okx_demo_shadow_exec_latest.json"
        return report_path if report_path.exists() else None

    # ========================================================================
    # 内部方法
    # ========================================================================

    def _is_running(self) -> bool:
        """检查进程是否运行中"""
        if not self._process:
            return False

        # 检查进程是否还在运行
        return self._process.poll() is None

    def _read_state_file(self) -> dict[str, Any]:
        """读取状态文件"""
        state_file = self.paths.get_runtime_dir() / "okx_demo_autopilot_state.json"

        if not state_file.exists():
            return {}

        try:
            with open(state_file, encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"[BTCSystemClient] 读取状态文件失败: {e}")
            return {}

    def _cleanup_pid_file(self):
        """清理PID文件"""
        try:
            pid_file = self.paths.get_runtime_dir() / "okx_demo_autopilot.pid"
            if pid_file.exists():
                pid_file.unlink()
        except Exception:
            pass

    def _start_monitoring(self):
        """启动状态监控线程"""
        if self._monitoring:
            return

        self._monitoring = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    def _stop_monitoring(self):
        """停止状态监控线程"""
        self._monitoring = False
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=2)

    def _monitor_loop(self):
        """状态监控循环"""
        while self._monitoring:
            try:
                if not self._is_running():
                    with self._state_lock:
                        if self._state.status not in ["stopped", "error"]:
                            self._state.status = "stopped"
                    break

                # 定期读取状态
                state_data = self._read_state_file()
                with self._state_lock:
                    if state_data.get("status"):
                        self._state.status = state_data["status"]

            except Exception:
                pass

            time.sleep(5)


# =============================================================================
# 便捷函数
# =============================================================================

def get_btc_system_client(btc_system_path: Path | None = None) -> BTCSystemClient:
    """
    获取BTC System客户端单例

    Args:
        btc_system_path: btc_system路径

    Returns:
        BTCSystemClient实例
    """
    return BTCSystemClient(btc_system_path)


def quick_start(
    strategy: str = "stage46_aggressive",
    duration_minutes: int = 60,
    symbols: list[str] | None = None
) -> BTCSystemClient:
    """
    快速启动autopilot

    Args:
        strategy: 策略ID
        duration_minutes: 运行时长
        symbols: 交易对列表

    Returns:
        BTCSystemClient实例
    """
    client = BTCSystemClient()
    client.start_autopilot(
        strategy=strategy,
        duration_minutes=duration_minutes,
        symbols=symbols
    )
    return client


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase V5 与 btc_system 之间的统一客户端，通过V5 platform层
# 实现跨平台的进程管理和状态监控。
#
# 【核心功能】
# 1. 路径自动检测：支持多端btc_system路径检测
# 2. 进程管理：使用V5 platform_factory管理进程生命周期
# 3. 状态监控：读取.runtime/状态文件，提供实时状态
# 4. 跨平台控制：start/stop/pause/resume 统一接口
#
# 【使用场景】
# - process_manager_v2.py: 调用本客户端管理btc_system
# - Workflow: 通过本客户端启动/监控交易
# - CLI工具: 直接调用进行手动控制
#
# 【关联文件】
# - core/platform/: V5平台抽象层
# - core/btc_integration/process_manager_v2.py: 主要调用方
# - btc_system/tools/okx_demo_autopilot.py: 被管理进程
#
# =============================================================================
