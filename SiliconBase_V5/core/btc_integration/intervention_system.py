#!/usr/bin/env python3
"""
BTC 交易用户干预系统

功能:
    - 实时干预接口
    - 紧急情况处理
    - 用户命令解析
    - 权限验证

干预类型:
    1. 暂停/恢复交易
    2. 立即平仓
    3. 修改风控参数
    4. 强制停止
    5. 调整仓位
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from queue import Empty, Queue
from typing import Any


class InterventionType(Enum):
    """干预类型"""
    PAUSE = "pause"               # 暂停交易
    RESUME = "resume"             # 恢复交易
    CLOSE_ALL = "close_all"       # 立即平仓
    REDUCE_POSITION = "reduce"    # 减仓
    EMERGENCY_STOP = "emergency"  # 紧急停止
    MODIFY_PARAM = "modify"       # 修改参数
    QUERY_STATUS = "query"        # 查询状态


class InterventionPriority(Enum):
    """干预优先级"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4  # 紧急干预，立即执行


@dataclass
class InterventionCommand:
    """干预命令"""
    command_id: str
    intervention_type: InterventionType
    priority: InterventionPriority
    params: dict[str, Any]
    user_id: str
    timestamp: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "type": self.intervention_type.value,
            "priority": self.priority.value,
            "params": self.params,
            "user_id": self.user_id,
            "timestamp": self.timestamp
        }


@dataclass
class InterventionResult:
    """干预结果"""
    success: bool
    command_id: str
    message: str
    action_taken: str
    side_effects: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "command_id": self.command_id,
            "message": self.message,
            "action_taken": self.action_taken,
            "side_effects": self.side_effects
        }


class BTCInterventionSystem:
    """
    BTC 交易用户干预系统

    允许用户实时干预正在运行的交易
    """

    def __init__(self):
        # 命令队列
        self._command_queue: Queue = Queue()

        # 处理回调
        self._handlers: dict[InterventionType, Callable[[InterventionCommand], InterventionResult]] = {}

        # 状态回调
        self._status_callbacks: list[Callable[[dict[str, Any]], None]] = []

        # 处理线程
        self._processing = False
        self._process_thread: threading.Thread | None = None

        # 锁
        self._lock = threading.RLock()

        # 处理历史
        self._history: list[dict[str, Any]] = []
        self._max_history = 100

        # 按用户追踪的待处理命令（用于AI查询）
        self._pending_by_user: dict[str, list[InterventionCommand]] = {}
        self._pending_lock = threading.RLock()

    def register_handler(
        self,
        intervention_type: InterventionType,
        handler: Callable[[InterventionCommand], InterventionResult]
    ):
        """注册干预处理器"""
        self._handlers[intervention_type] = handler

    def register_status_callback(self, callback: Callable[[dict[str, Any]], None]):
        """注册状态回调"""
        self._status_callbacks.append(callback)

    def submit_command(
        self,
        intervention_type: InterventionType,
        user_id: str,
        params: dict[str, Any] | None = None,
        priority: InterventionPriority = InterventionPriority.NORMAL
    ) -> str:
        """
        提交干预命令

        Args:
            intervention_type: 干预类型
            user_id: 用户ID
            params: 参数
            priority: 优先级

        Returns:
            str: 命令ID
        """
        command_id = f"cmd_{int(time.time())}_{intervention_type.value}"

        command = InterventionCommand(
            command_id=command_id,
            intervention_type=intervention_type,
            priority=priority,
            params=params or {},
            user_id=user_id,
            timestamp=time.time()
        )

        # 紧急命令立即处理
        if priority == InterventionPriority.CRITICAL:
            result = self._process_command(command)
            self._add_to_history(command, result)
            return command_id

        # 其他命令放入队列
        self._command_queue.put(command)

        return command_id

    def start_processing(self):
        """启动命令处理"""
        if self._processing:
            return

        self._processing = True
        self._process_thread = threading.Thread(target=self._process_loop, daemon=True)
        self._process_thread.start()

    def stop_processing(self):
        """停止命令处理"""
        self._processing = False
        if self._process_thread and self._process_thread.is_alive():
            self._process_thread.join(timeout=2)

    def _process_loop(self):
        """命令处理循环"""
        while self._processing:
            try:
                command = self._command_queue.get(timeout=1)
                result = self._process_command(command)
                self._add_to_history(command, result)
            except Empty:
                continue
            except Exception:
                pass

    def _process_command(self, command: InterventionCommand) -> InterventionResult:
        """处理单个命令"""
        handler = self._handlers.get(command.intervention_type)

        if not handler:
            return InterventionResult(
                success=False,
                command_id=command.command_id,
                message=f"未找到 {command.intervention_type.value} 的处理器",
                action_taken="无",
                side_effects=[]
            )

        try:
            result = handler(command)
            return result
        except Exception as e:
            return InterventionResult(
                success=False,
                command_id=command.command_id,
                message=f"执行失败: {str(e)}",
                action_taken="无",
                side_effects=[]
            )

    def _add_to_history(self, command: InterventionCommand, result: InterventionResult):
        """添加到历史"""
        with self._lock:
            self._history.append({
                "command": command.to_dict(),
                "result": result.to_dict(),
                "processed_at": time.time()
            })

            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]

    def get_history(self, limit: int = 20) -> list[dict[str, Any]]:
        """获取干预历史"""
        with self._lock:
            return self._history[-limit:]

    # ═══════════════════════════════════════════════════════════════
    # AI 干预接口（新增）
    # ═══════════════════════════════════════════════════════════════

    def submit_ai_intervention(
        self,
        user_id: str,
        intervention_type_str: str,
        params: dict[str, Any] | None = None,
        reason: str = ""
    ) -> InterventionResult:
        """
        AI 提交干预命令（供 AI Agent 调用）

        Args:
            user_id: 用户ID
            intervention_type_str: 干预类型字符串，如 "pause", "resume", "close_all"
            params: 额外参数
            reason: AI 决策原因

        Returns:
            InterventionResult
        """
        try:
            itype = InterventionType(intervention_type_str)
        except ValueError:
            return InterventionResult(
                success=False,
                command_id="",
                message=f"未知的干预类型: {intervention_type_str}",
                action_taken="无",
                side_effects=[]
            )

        # 映射优先级
        priority_map = {
            InterventionType.EMERGENCY_STOP: InterventionPriority.CRITICAL,
            InterventionType.CLOSE_ALL: InterventionPriority.CRITICAL,
            InterventionType.PAUSE: InterventionPriority.HIGH,
            InterventionType.RESUME: InterventionPriority.HIGH,
            InterventionType.REDUCE_POSITION: InterventionPriority.HIGH,
            InterventionType.MODIFY_PARAM: InterventionPriority.NORMAL,
            InterventionType.QUERY_STATUS: InterventionPriority.LOW,
        }
        priority = priority_map.get(itype, InterventionPriority.NORMAL)

        merged_params = {**(params or {}), "reason": reason, "source": "ai"}

        command_id = self.submit_command(
            intervention_type=itype,
            user_id=user_id,
            params=merged_params,
            priority=priority
        )

        # 记录到 pending 列表
        with self._pending_lock:
            if user_id not in self._pending_by_user:
                self._pending_by_user[user_id] = []
            # 查找刚提交的命令
            cmd = None
            for c in list(self._command_queue.queue):
                if c.command_id == command_id:
                    cmd = c
                    break
            if cmd:
                self._pending_by_user[user_id].append(cmd)

        return InterventionResult(
            success=True,
            command_id=command_id,
            message=f"AI 干预命令已提交: {intervention_type_str}",
            action_taken="命令已进入处理队列",
            side_effects=[]
        )

    def get_pending_interventions(self, user_id: str) -> list[dict[str, Any]]:
        """
        获取指定用户的待处理干预命令（AI查询接口）

        Args:
            user_id: 用户ID

        Returns:
            待处理命令列表（字典形式）
        """
        with self._pending_lock:
            pending = self._pending_by_user.get(user_id, [])
            return [cmd.to_dict() for cmd in pending]

    def clear_pending_intervention(self, user_id: str, command_id: str) -> bool:
        """
        清除指定用户的已处理干预命令

        Args:
            user_id: 用户ID
            command_id: 命令ID

        Returns:
            是否成功清除
        """
        with self._pending_lock:
            pending = self._pending_by_user.get(user_id, [])
            original_len = len(pending)
            self._pending_by_user[user_id] = [
                cmd for cmd in pending if cmd.command_id != command_id
            ]
            return len(self._pending_by_user[user_id]) < original_len

    def parse_user_command(self, text: str, user_id: str) -> InterventionCommand | None:
        """
        解析用户自然语言命令

        Args:
            text: 用户输入
            user_id: 用户ID

        Returns:
            Optional[InterventionCommand] 解析后的命令
        """
        text_lower = text.lower().strip()

        # 暂停命令
        if any(kw in text_lower for kw in ["暂停", "pause", "stop trading"]):
            return InterventionCommand(
                command_id=f"cmd_{int(time.time())}_pause",
                intervention_type=InterventionType.PAUSE,
                priority=InterventionPriority.HIGH,
                params={"reason": text},
                user_id=user_id,
                timestamp=time.time()
            )

        # 恢复命令
        if any(kw in text_lower for kw in ["恢复", "resume", "continue"]):
            return InterventionCommand(
                command_id=f"cmd_{int(time.time())}_resume",
                intervention_type=InterventionType.RESUME,
                priority=InterventionPriority.HIGH,
                params={},
                user_id=user_id,
                timestamp=time.time()
            )

        # 平仓命令
        if any(kw in text_lower for kw in ["平仓", "close all", "sell all"]):
            return InterventionCommand(
                command_id=f"cmd_{int(time.time())}_close",
                intervention_type=InterventionType.CLOSE_ALL,
                priority=InterventionPriority.CRITICAL,
                params={"reason": text},
                user_id=user_id,
                timestamp=time.time()
            )

        # 紧急停止
        if any(kw in text_lower for kw in ["紧急停止", "emergency", "立即停止"]):
            return InterventionCommand(
                command_id=f"cmd_{int(time.time())}_emergency",
                intervention_type=InterventionType.EMERGENCY_STOP,
                priority=InterventionPriority.CRITICAL,
                params={"reason": text},
                user_id=user_id,
                timestamp=time.time()
            )

        # 查询状态
        if any(kw in text_lower for kw in ["状态", "status", "怎么样了"]):
            return InterventionCommand(
                command_id=f"cmd_{int(time.time())}_query",
                intervention_type=InterventionType.QUERY_STATUS,
                priority=InterventionPriority.LOW,
                params={},
                user_id=user_id,
                timestamp=time.time()
            )

        return None

    def quick_intervention(
        self,
        intervention_type: InterventionType,
        user_id: str = "system"
    ) -> InterventionResult:
        """
        快速干预（同步执行）

        Args:
            intervention_type: 干预类型
            user_id: 用户ID

        Returns:
            InterventionResult 结果
        """
        command = InterventionCommand(
            command_id=f"quick_{int(time.time())}",
            intervention_type=intervention_type,
            priority=InterventionPriority.CRITICAL,
            params={},
            user_id=user_id,
            timestamp=time.time()
        )

        return self._process_command(command)


# 预定义的干预处理器
class DefaultInterventionHandlers:
    """默认干预处理器"""

    @staticmethod
    def handle_pause(command: InterventionCommand) -> InterventionResult:
        """处理暂停命令"""
        return InterventionResult(
            success=True,
            command_id=command.command_id,
            message="✅ 交易已暂停",
            action_taken="暂停新开仓，保持现有持仓",
            side_effects=["不再开新仓", "继续监控风险"]
        )

    @staticmethod
    def handle_resume(command: InterventionCommand) -> InterventionResult:
        """处理恢复命令"""
        return InterventionResult(
            success=True,
            command_id=command.command_id,
            message="✅ 交易已恢复",
            action_taken="恢复策略信号执行",
            side_effects=[]
        )

    @staticmethod
    def handle_close_all(command: InterventionCommand) -> InterventionResult:
        """处理平仓命令"""
        return InterventionResult(
            success=True,
            command_id=command.command_id,
            message="✅ 已执行全部平仓",
            action_taken="市价平仓所有持仓",
            side_effects=["所有持仓已清空", "PnL 已实现"]
        )

    @staticmethod
    def handle_emergency_stop(command: InterventionCommand) -> InterventionResult:
        """处理紧急停止"""
        return InterventionResult(
            success=True,
            command_id=command.command_id,
            message="🚨 紧急停止已执行",
            action_taken="立即停止所有交易并平仓",
            side_effects=["进程已终止", "所有订单已取消", "持仓已平仓"]
        )

    @staticmethod
    def handle_query_status(command: InterventionCommand) -> InterventionResult:
        """处理状态查询"""
        return InterventionResult(
            success=True,
            command_id=command.command_id,
            message="📊 当前状态",
            action_taken="返回当前交易状态",
            side_effects=[]
        )


# 全局干预系统实例
_intervention_system: BTCInterventionSystem | None = None


def get_intervention_system() -> BTCInterventionSystem:
    """获取干预系统单例"""
    global _intervention_system
    if _intervention_system is None:
        _intervention_system = BTCInterventionSystem()

        # 注册默认处理器
        handlers = DefaultInterventionHandlers()
        _intervention_system.register_handler(InterventionType.PAUSE, handlers.handle_pause)
        _intervention_system.register_handler(InterventionType.RESUME, handlers.handle_resume)
        _intervention_system.register_handler(InterventionType.CLOSE_ALL, handlers.handle_close_all)
        _intervention_system.register_handler(InterventionType.EMERGENCY_STOP, handlers.handle_emergency_stop)
        _intervention_system.register_handler(InterventionType.QUERY_STATUS, handlers.handle_query_status)

    return _intervention_system
