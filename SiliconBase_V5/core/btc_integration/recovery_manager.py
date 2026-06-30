#!/usr/bin/env python3
"""
BTC 交易异常恢复管理器

功能:
    - 交易状态持久化
    - 异常中断检测
    - 自动恢复机制
    - 断点续传

恢复场景:
    1. 系统崩溃 - 重启后恢复
    2. 进程被杀 - 检测并提示
    3. 网络中断 - 自动重连
    4. API 故障 - 降级到影子模式
"""

import contextlib
import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class RecoveryState(Enum):
    """恢复状态"""
    HEALTHY = "healthy"           # 健康运行
    INTERRUPTED = "interrupted"   # 中断
    RECOVERING = "recovering"     # 恢复中
    RECOVERED = "recovered"       # 已恢复
    FAILED = "failed"             # 恢复失败


@dataclass
class TradingCheckpoint:
    """交易检查点"""
    checkpoint_id: str
    timestamp: float

    # 交易状态
    symbol: str
    strategy: str
    budget: float
    duration_minutes: int
    elapsed_minutes: float

    # 持仓状态
    positions: dict[str, Any] = field(default_factory=dict)

    # 盈亏状态
    pnl_current: float = 0.0
    pnl_daily: float = 0.0
    trades_count: int = 0

    # 上下文
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TradingCheckpoint":
        return cls(**data)


@dataclass
class RecoveryResult:
    """恢复结果"""
    success: bool
    state: RecoveryState
    message: str
    recovered_checkpoint: TradingCheckpoint | None = None
    recommended_action: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "state": self.state.value,
            "message": self.message,
            "recovered_checkpoint": self.recovered_checkpoint.to_dict() if self.recovered_checkpoint else None,
            "recommended_action": self.recommended_action
        }


class BTCRecoveryManager:
    """
    BTC 交易恢复管理器

    管理交易状态的持久化和恢复
    """

    def __init__(self, checkpoint_dir: str = "data/btc_checkpoints"):
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

        # 当前检查点
        self._current_checkpoint: TradingCheckpoint | None = None

        # 恢复回调
        self._recovery_callbacks: list[Callable[[RecoveryResult], None]] = []

        # 状态文件
        self._state_file = self.checkpoint_dir / "trading_state.json"

    def register_recovery_callback(self, callback: Callable[[RecoveryResult], None]):
        """注册恢复回调"""
        self._recovery_callbacks.append(callback)

    def _trigger_recovery_callback(self, result: RecoveryResult):
        """触发恢复回调"""
        for callback in self._recovery_callbacks:
            with contextlib.suppress(Exception):
                callback(result)

    def create_checkpoint(
        self,
        symbol: str,
        strategy: str,
        budget: float,
        duration_minutes: int,
        elapsed_minutes: float,
        positions: dict[str, Any],
        pnl_current: float = 0.0,
        pnl_daily: float = 0.0,
        trades_count: int = 0,
        context: dict[str, Any] | None = None
    ) -> TradingCheckpoint:
        """
        创建检查点

        Args:
            symbol: 交易标的
            strategy: 策略ID
            budget: 预算
            duration_minutes: 总时长
            elapsed_minutes: 已运行时长
            positions: 持仓状态
            pnl_current: 当前盈亏
            pnl_daily: 日盈亏
            trades_count: 交易次数
            context: 额外上下文

        Returns:
            TradingCheckpoint 检查点
        """
        checkpoint = TradingCheckpoint(
            checkpoint_id=f"cp_{int(time.time())}_{symbol}",
            timestamp=time.time(),
            symbol=symbol,
            strategy=strategy,
            budget=budget,
            duration_minutes=duration_minutes,
            elapsed_minutes=elapsed_minutes,
            positions=positions.copy(),
            pnl_current=pnl_current,
            pnl_daily=pnl_daily,
            trades_count=trades_count,
            context=context or {}
        )

        self._current_checkpoint = checkpoint
        self._save_checkpoint(checkpoint)
        self._save_state("running", checkpoint.checkpoint_id)

        return checkpoint

    def _save_checkpoint(self, checkpoint: TradingCheckpoint):
        """保存检查点到文件"""
        checkpoint_file = self.checkpoint_dir / f"{checkpoint.checkpoint_id}.json"
        with open(checkpoint_file, 'w', encoding='utf-8') as f:
            json.dump(checkpoint.to_dict(), f, ensure_ascii=False, indent=2)

    def _save_state(self, state: str, checkpoint_id: str):
        """保存状态"""
        state_data = {
            "state": state,
            "checkpoint_id": checkpoint_id,
            "timestamp": time.time()
        }
        with open(self._state_file, 'w', encoding='utf-8') as f:
            json.dump(state_data, f, ensure_ascii=False, indent=2)

    def load_latest_checkpoint(self) -> TradingCheckpoint | None:
        """加载最新的检查点"""
        # 获取所有检查点文件
        checkpoint_files = list(self.checkpoint_dir.glob("cp_*.json"))

        if not checkpoint_files:
            return None

        # 按修改时间排序，取最新的
        latest_file = max(checkpoint_files, key=lambda p: p.stat().st_mtime)

        try:
            with open(latest_file, encoding='utf-8') as f:
                data = json.load(f)
            return TradingCheckpoint.from_dict(data)
        except Exception:
            return None

    def check_interruption(self) -> bool:
        """
        检查是否发生过中断

        Returns:
            bool: 是否中断
        """
        if not self._state_file.exists():
            return False

        try:
            with open(self._state_file, encoding='utf-8') as f:
                state_data = json.load(f)

            state = state_data.get("state", "")
            return state == "running"
        except Exception:
            return False

    def attempt_recovery(self) -> RecoveryResult:
        """
        尝试恢复交易

        Returns:
            RecoveryResult 恢复结果
        """
        # 检查是否有中断
        if not self.check_interruption():
            return RecoveryResult(
                success=True,
                state=RecoveryState.HEALTHY,
                message="没有检测到中断，无需恢复"
            )

        # 加载检查点
        checkpoint = self.load_latest_checkpoint()

        if not checkpoint:
            self._save_state("failed", "")
            return RecoveryResult(
                success=False,
                state=RecoveryState.FAILED,
                message="无法加载检查点，恢复失败",
                recommended_action="建议重新开始交易，或联系技术支持"
            )

        # 检查检查点是否过期（超过24小时）
        elapsed_since_checkpoint = (time.time() - checkpoint.timestamp) / 3600
        if elapsed_since_checkpoint > 24:
            self._save_state("failed", checkpoint.checkpoint_id)
            return RecoveryResult(
                success=False,
                state=RecoveryState.FAILED,
                message=f"检查点已过期 ({elapsed_since_checkpoint:.1f}小时前)",
                recovered_checkpoint=checkpoint,
                recommended_action="检查点过期，建议重新开始交易"
            )

        # 检查剩余时间
        remaining_minutes = checkpoint.duration_minutes - checkpoint.elapsed_minutes
        if remaining_minutes <= 0:
            self._save_state("completed", checkpoint.checkpoint_id)
            return RecoveryResult(
                success=True,
                state=RecoveryState.RECOVERED,
                message="交易时间已完成，无需恢复",
                recovered_checkpoint=checkpoint,
                recommended_action="查看最终交易报告"
            )

        # 可以恢复
        self._current_checkpoint = checkpoint
        self._save_state("recovering", checkpoint.checkpoint_id)

        result = RecoveryResult(
            success=True,
            state=RecoveryState.RECOVERING,
            message=f"检测到中断的交易，可以恢复\n"
                    f"标的: {checkpoint.symbol}\n"
                    f"策略: {checkpoint.strategy}\n"
                    f"已运行: {checkpoint.elapsed_minutes:.0f}分钟\n"
                    f"剩余: {remaining_minutes:.0f}分钟\n"
                    f"当前盈亏: ${checkpoint.pnl_current:+.2f}",
            recovered_checkpoint=checkpoint,
            recommended_action="确认是否恢复交易"
        )

        self._trigger_recovery_callback(result)
        return result

    def confirm_recovery(self, continue_trading: bool) -> RecoveryResult:
        """
        确认恢复

        Args:
            continue_trading: 是否继续交易

        Returns:
            RecoveryResult 结果
        """
        if not self._current_checkpoint:
            return RecoveryResult(
                success=False,
                state=RecoveryState.FAILED,
                message="没有可恢复的检查点"
            )

        if continue_trading:
            self._save_state("running", self._current_checkpoint.checkpoint_id)
            return RecoveryResult(
                success=True,
                state=RecoveryState.RECOVERED,
                message="交易已恢复，继续运行",
                recovered_checkpoint=self._current_checkpoint,
                recommended_action="监控交易状态"
            )
        else:
            self._save_state("cancelled", self._current_checkpoint.checkpoint_id)
            return RecoveryResult(
                success=True,
                state=RecoveryState.FAILED,
                message="用户取消恢复",
                recovered_checkpoint=self._current_checkpoint,
                recommended_action="可以查看历史报告或重新开始"
            )

    def mark_completed(self):
        """标记交易完成"""
        if self._current_checkpoint:
            self._save_state("completed", self._current_checkpoint.checkpoint_id)

        # 清理旧检查点（保留最近10个）
        self._cleanup_old_checkpoints(keep=10)

    def _cleanup_old_checkpoints(self, keep: int = 10):
        """清理旧检查点"""
        checkpoint_files = list(self.checkpoint_dir.glob("cp_*.json"))

        if len(checkpoint_files) <= keep:
            return

        # 按修改时间排序
        checkpoint_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        # 删除旧的
        for old_file in checkpoint_files[keep:]:
            with contextlib.suppress(BaseException):
                old_file.unlink()

    def get_recovery_summary(self) -> dict[str, Any]:
        """获取恢复摘要"""
        summary = {
            "can_recover": False,
            "checkpoint_count": 0,
            "latest_checkpoint": None,
            "state": "unknown"
        }

        # 统计检查点
        checkpoint_files = list(self.checkpoint_dir.glob("cp_*.json"))
        summary["checkpoint_count"] = len(checkpoint_files)

        # 检查状态
        if self._state_file.exists():
            try:
                with open(self._state_file, encoding='utf-8') as f:
                    state_data = json.load(f)
                summary["state"] = state_data.get("state", "unknown")

                if state_data.get("state") == "running":
                    summary["can_recover"] = True
            except Exception:
                pass

        # 最新检查点信息
        latest = self.load_latest_checkpoint()
        if latest:
            summary["latest_checkpoint"] = {
                "id": latest.checkpoint_id,
                "symbol": latest.symbol,
                "timestamp": latest.timestamp,
                "elapsed_minutes": latest.elapsed_minutes,
                "pnl_current": latest.pnl_current
            }

        return summary


# 全局恢复管理器实例
_recovery_manager: BTCRecoveryManager | None = None


def get_recovery_manager(checkpoint_dir: str = "data/btc_checkpoints") -> BTCRecoveryManager:
    """获取恢复管理器单例"""
    global _recovery_manager
    if _recovery_manager is None:
        _recovery_manager = BTCRecoveryManager(checkpoint_dir)
    return _recovery_manager
