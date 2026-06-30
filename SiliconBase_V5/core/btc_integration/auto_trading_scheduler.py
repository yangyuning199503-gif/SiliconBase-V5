#!/usr/bin/env python3
"""
24小时自动交易调度器
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
实现AI加密货币交易的全自动24小时运行

核心功能:
- 每小时触发市场分析和策略选择
- 根据风险等级自动决策是否交易
- 自动续约机制（会话到期前启动新会话）
- 熔断后自动恢复
- 完整的日志记录和状态监控

作者: SiliconBase V5 AI Agent
日期: 2026-04-09
"""

import asyncio
import gc
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from core.diagnostic import safe_create_task

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger
    APSCHEDULER_AVAILABLE = True
except ImportError:
    APSCHEDULER_AVAILABLE = False

from core.config import config
from core.logger import logger

# 导入BTC相关模块
from .process_manager import BTCProcessManager, get_btc_process_manager
from .risk_monitor import BTCRiskMonitor, get_risk_monitor
from .strategy_analyzer import StrategyAnalyzer, get_strategy_analyzer


class AutoTradingStatus(Enum):
    """自动交易状态"""
    STOPPED = "stopped"           # 已停止
    STARTING = "starting"         # 启动中
    RUNNING = "running"           # 运行中
    PAUSED = "paused"             # 已暂停（用户手动）
    HALTED = "halted"             # 已熔断（风险触发）
    RECOVERING = "recovering"     # 恢复中
    ERROR = "error"               # 错误状态


@dataclass
class TradingSession:
    """交易会话记录"""
    session_id: str
    start_time: datetime
    end_time: datetime | None = None
    symbol: str = "BTC"
    strategy: str = ""
    budget: float = 1000.0
    pnl: float = 0.0
    status: str = "running"
    risk_events: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "symbol": self.symbol,
            "strategy": self.strategy,
            "budget": self.budget,
            "pnl": self.pnl,
            "status": self.status,
            "risk_events": self.risk_events
        }


@dataclass
class AutoTradingStats:
    """自动交易统计"""
    total_sessions: int = 0
    total_pnl: float = 0.0
    max_drawdown: float = 0.0
    win_count: int = 0
    loss_count: int = 0
    start_time: datetime | None = None
    uptime_hours: float = 0.0
    restart_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_sessions": self.total_sessions,
            "total_pnl": round(self.total_pnl, 2),
            "max_drawdown": round(self.max_drawdown, 2),
            "win_count": self.win_count,
            "loss_count": self.loss_count,
            "win_rate": round(self.win_count / max(self.total_sessions, 1), 2),
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "uptime_hours": round(self.uptime_hours, 2),
            "restart_count": self.restart_count
        }


class AutoTradingScheduler:
    """
    24小时自动交易调度器

    使用示例:
        scheduler = AutoTradingScheduler()
        await scheduler.start_24h_trading(
            symbol="BTC",
            budget=1000,
            risk_tolerance="medium"
        )

        # 稍后停止
        await scheduler.stop()
    """

    def __init__(self):
        self._status = AutoTradingStatus.STOPPED
        self._status_lock = threading.RLock()

        # APScheduler
        self._scheduler: AsyncIOScheduler | None = None

        # 交易管理器
        self._process_manager: BTCProcessManager | None = None
        self._risk_monitor: BTCRiskMonitor | None = None
        self._strategy_analyzer: StrategyAnalyzer | None = None

        # 当前会话
        self._current_session: TradingSession | None = None
        self._session_history: list[TradingSession] = []
        self._session_lock = threading.RLock()

        # 统计
        self._stats = AutoTradingStats()

        # 配置
        self._config = self._load_config()

        # 熔断控制
        self._circuit_breaker_triggered = False
        self._circuit_breaker_time: datetime | None = None
        self._cooldown_minutes = self._config.get("circuit_breaker", {}).get("cooldown_minutes", 30)

        # 自动续约
        self._renewal_job_id: str | None = None

        # 日志
        self._logs: list[dict[str, Any]] = []
        self._max_logs = 1000

        # 事件回调
        self._event_callbacks: list[Callable[[str, dict], None]] = []

    def _load_config(self) -> dict[str, Any]:
        """加载自动交易配置"""
        try:
            # 从全局配置读取
            btc_config = config.get("btc_auto_trading", {})
            return btc_config
        except Exception as e:
            logger.warning(f"[AutoTradingScheduler] 加载配置失败，使用默认: {e}")
            return {
                "interval_minutes": 60,
                "auto_confirm": True,
                "max_session_duration": 55,
                "auto_renew": True,
                "circuit_breaker": {
                    "cooldown_minutes": 30,
                    "recovery_check_interval": 5
                },
                "guardian": {
                    "enabled": True,
                    "max_restarts": 5,
                    "restart_delay": 30
                }
            }

    def _log(self, level: str, message: str, data: dict = None):
        """记录日志"""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "level": level,
            "message": message,
            "data": data or {}
        }
        self._logs.append(log_entry)

        # 限制日志数量
        if len(self._logs) > self._max_logs:
            self._logs = self._logs[-self._max_logs:]

        # 输出到系统日志
        log_func = getattr(logger, level, logger.info)
        log_func(f"[AutoTradingScheduler] {message}")

    def _trigger_event(self, event_type: str, data: dict):
        """触发事件"""
        for callback in self._event_callbacks:
            try:
                callback(event_type, data)
            except Exception as e:
                self._log("error", f"事件回调失败: {e}")

    def register_event_callback(self, callback: Callable[[str, dict], None]):
        """注册事件回调"""
        self._event_callbacks.append(callback)

    # ═══════════════════════════════════════════════════════════════
    # 状态管理
    # ═══════════════════════════════════════════════════════════════

    @property
    def status(self) -> AutoTradingStatus:
        """获取当前状态"""
        with self._status_lock:
            return self._status

    def _set_status(self, status: AutoTradingStatus):
        """设置状态"""
        with self._status_lock:
            old_status = self._status
            self._status = status
            self._log("info", f"状态变更: {old_status.value} -> {status.value}")
            self._trigger_event("status_changed", {
                "old": old_status.value,
                "new": status.value
            })

    def is_running(self) -> bool:
        """检查是否正在运行"""
        return self.status == AutoTradingStatus.RUNNING

    def is_paused(self) -> bool:
        """检查是否已暂停"""
        return self.status == AutoTradingStatus.PAUSED

    def is_halted(self) -> bool:
        """检查是否已熔断"""
        return self.status == AutoTradingStatus.HALTED

    # ═══════════════════════════════════════════════════════════════
    # 核心控制方法
    # ═══════════════════════════════════════════════════════════════

    async def start_24h_trading(
        self,
        symbol: str = "BTC",
        budget: float = 1000.0,
        risk_tolerance: str = "medium",
        strategy: str | None = None
    ) -> bool:
        """
        启动24小时自动交易

        Args:
            symbol: 交易标的（BTC/ETH/SOL）
            budget: 预算金额（USDT）
            risk_tolerance: 风险偏好（low/medium/high）
            strategy: 指定策略（None则自动选择）

        Returns:
            bool: 是否成功启动
        """
        if not APSCHEDULER_AVAILABLE:
            self._log("error", "APScheduler不可用，无法启动自动交易")
            return False

        with self._status_lock:
            if self._status in [AutoTradingStatus.RUNNING, AutoTradingStatus.STARTING]:
                self._log("warning", "自动交易已在运行中")
                return False

            self._set_status(AutoTradingStatus.STARTING)

        try:
            self._log("info", f"启动24小时自动交易: {symbol}, 预算: ${budget}")

            # 初始化组件
            self._process_manager = get_btc_process_manager()
            self._risk_monitor = get_risk_monitor()
            self._strategy_analyzer = get_strategy_analyzer()

            # 注册风险事件回调
            self._risk_monitor.register_event_callback(self._on_risk_event)
            self._risk_monitor.register_intervention_callback(self._on_intervention)

            # 初始化统计
            self._stats.start_time = datetime.now()

            # 启动APScheduler
            self._scheduler = AsyncIOScheduler()

            # 添加定时交易任务（每小时）
            self._scheduler.add_job(
                self._trading_cycle,
                trigger=CronTrigger(minute=0),  # 每小时的第0分钟
                id="trading_cycle",
                replace_existing=True,
                max_instances=1  # 防止并发执行
            )

            # 添加风险检查任务（每5分钟）
            self._scheduler.add_job(
                self._risk_check_cycle,
                trigger=IntervalTrigger(minutes=5),
                id="risk_check",
                replace_existing=True
            )

            # 添加自动续约检查（每分钟）
            if self._config.get("auto_renew", True):
                self._scheduler.add_job(
                    self._auto_renew_check,
                    trigger=IntervalTrigger(minutes=1),
                    id="auto_renew",
                    replace_existing=True
                )

            # 添加资源清理任务（每小时）
            self._scheduler.add_job(
                self._cleanup_resources,
                trigger=IntervalTrigger(hours=1),
                id="cleanup",
                replace_existing=True
            )

            # 启动调度器
            self._scheduler.start()

            # 立即执行一次交易周期
            safe_create_task(self._trading_cycle(), name="_trading_cycle")

            self._set_status(AutoTradingStatus.RUNNING)
            self._log("info", "24小时自动交易已启动")

            return True

        except Exception as e:
            self._log("error", f"启动失败: {e}")
            self._set_status(AutoTradingStatus.ERROR)
            return False

    async def stop(self) -> bool:
        """
        停止自动交易

        Returns:
            bool: 是否成功停止
        """
        with self._status_lock:
            if self._status == AutoTradingStatus.STOPPED:
                return True

        self._log("info", "正在停止自动交易...")

        try:
            # 停止当前交易进程
            if self._current_session:
                await self._stop_current_session()

            # 停止调度器
            if self._scheduler:
                self._scheduler.shutdown(wait=False)
                self._scheduler = None

            # 更新统计
            if self._stats.start_time:
                uptime = datetime.now() - self._stats.start_time
                self._stats.uptime_hours = uptime.total_seconds() / 3600

            self._set_status(AutoTradingStatus.STOPPED)
            self._log("info", "自动交易已停止")

            return True

        except Exception as e:
            self._log("error", f"停止失败: {e}")
            return False

    async def pause(self) -> bool:
        """
        暂停自动交易（保持持仓）

        Returns:
            bool: 是否成功暂停
        """
        if self.status != AutoTradingStatus.RUNNING:
            self._log("warning", "只有运行中才能暂停")
            return False

        self._log("info", "暂停自动交易")

        # 暂停当前进程
        if self._process_manager:
            self._process_manager.pause()

        # 暂停调度器任务
        if self._scheduler:
            for job in self._scheduler.get_jobs():
                job.pause()

        self._set_status(AutoTradingStatus.PAUSED)
        return True

    async def resume(self) -> bool:
        """
        恢复自动交易

        Returns:
            bool: 是否成功恢复
        """
        if self.status not in [AutoTradingStatus.PAUSED, AutoTradingStatus.HALTED]:
            self._log("warning", "非暂停/熔断状态，无法恢复")
            return False

        self._log("info", "恢复自动交易")

        # 恢复进程
        if self._process_manager:
            self._process_manager.resume()

        # 恢复调度器任务
        if self._scheduler:
            for job in self._scheduler.get_jobs():
                job.resume()

        self._circuit_breaker_triggered = False
        self._circuit_breaker_time = None

        self._set_status(AutoTradingStatus.RUNNING)
        return True

    # ═══════════════════════════════════════════════════════════════
    # 交易周期
    # ═══════════════════════════════════════════════════════════════

    async def _trading_cycle(self):
        """
        单次交易周期
        每小时执行一次
        """
        if self.status != AutoTradingStatus.RUNNING:
            return

        self._log("info", "=== 开始交易周期 ===")

        try:
            # 1. 检查熔断状态
            if self._circuit_breaker_triggered and not self._check_circuit_breaker_recovery():
                self._log("info", "熔断中，跳过本次交易周期")
                return

            # 2. 市场分析
            self._log("info", "执行市场分析...")
            market_condition = await self._analyze_market()

            # 3. 策略选择
            self._log("info", "选择交易策略...")
            strategy_rec = await self._select_strategy(market_condition)

            # 4. 风险评估
            self._log("info", "评估风险...")
            risk_assessment = self._risk_monitor.assess_risk()

            if risk_assessment.should_halt:
                self._log("warning", f"风险过高，触发熔断: {risk_assessment.overall_level.value}")
                await self._trigger_circuit_breaker(risk_assessment)
                return

            # 5. 决策是否交易
            if not self._should_trade(market_condition, risk_assessment):
                self._log("info", "当前市场条件不适合交易，跳过")
                return

            # 6. 启动交易会话
            await self._start_trading_session(strategy_rec)

        except Exception as e:
            self._log("error", f"交易周期异常: {e}")
            self._trigger_event("cycle_error", {"error": str(e)})

    async def _analyze_market(self) -> dict[str, Any]:
        """分析市场环境"""
        try:
            # 使用策略分析器获取市场状态
            market_state = self._strategy_analyzer.analyze_market("BTC")
            return market_state.to_dict() if hasattr(market_state, 'to_dict') else market_state
        except Exception as e:
            self._log("error", f"市场分析失败: {e}")
            return {"trend": "unknown", "volatility": "medium"}

    async def _select_strategy(self, market_condition: dict) -> dict[str, Any]:
        """选择交易策略"""
        try:
            recommendation = self._strategy_analyzer.recommend_strategy(market_condition)
            return recommendation.to_dict() if hasattr(recommendation, 'to_dict') else recommendation
        except Exception as e:
            self._log("error", f"策略选择失败: {e}")
            return {
                "primary_strategy": {"id": "stage46_aggressive", "name": "趋势跟踪"},
                "confidence": 0.5
            }

    def _should_trade(self, market_condition: dict, risk_assessment: Any) -> bool:
        """决策是否应该交易"""
        # 风险检查
        if risk_assessment.should_halt:
            return False

        # 市场条件检查
        trend = market_condition.get("trend", "unknown")
        volatility = market_condition.get("volatility", "medium")

        # 不明确的市场不交易
        if trend == "unknown":
            return False

        # 极高波动不交易
        return volatility != "extreme"

    # ═══════════════════════════════════════════════════════════════
    # 会话管理
    # ═══════════════════════════════════════════════════════════════

    async def _start_trading_session(self, strategy_rec: dict):
        """启动交易会话"""
        # 如果已有运行中的会话，先停止
        if self._current_session and self._current_session.status == "running":
            self._log("info", "已有运行中的会话，跳过启动")
            return

        session_id = f"auto_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        strategy = strategy_rec.get("primary_strategy", {})
        strategy_id = strategy.get("id", "stage46_aggressive")

        self._log("info", f"启动交易会话: {session_id}, 策略: {strategy_id}")

        # 创建会话记录
        session = TradingSession(
            session_id=session_id,
            start_time=datetime.now(),
            symbol="BTC",
            strategy=strategy_id,
            budget=self._config.get("budget", 1000.0)
        )

        with self._session_lock:
            self._current_session = session

        # 启动交易进程
        try:
            success = self._process_manager.start(
                strategy=strategy_id,
                duration_minutes=self._config.get("max_session_duration", 55)
            )

            if success:
                self._stats.total_sessions += 1
                self._trigger_event("session_started", session.to_dict())
                self._log("info", f"交易会话启动成功: {session_id}")
            else:
                session.status = "failed"
                self._log("error", f"交易会话启动失败: {session_id}")

        except Exception as e:
            session.status = "error"
            self._log("error", f"启动交易会话异常: {e}")

    async def _stop_current_session(self):
        """停止当前会话"""
        if not self._current_session:
            return

        session_id = self._current_session.session_id
        self._log("info", f"停止交易会话: {session_id}")

        try:
            # 停止进程
            if self._process_manager:
                self._process_manager.stop(timeout=30)

            # 更新会话状态
            with self._session_lock:
                self._current_session.end_time = datetime.now()
                self._current_session.status = "stopped"

                # 保存到历史
                self._session_history.append(self._current_session)

                # 限制历史记录数量
                if len(self._session_history) > 100:
                    self._session_history = self._session_history[-100:]

                self._current_session = None

            self._trigger_event("session_stopped", {"session_id": session_id})

        except Exception as e:
            self._log("error", f"停止会话异常: {e}")

    # ═══════════════════════════════════════════════════════════════
    # 自动续约
    # ═══════════════════════════════════════════════════════════════

    async def _auto_renew_check(self):
        """检查是否需要自动续约"""
        if not self._current_session or self.status != AutoTradingStatus.RUNNING:
            return

        try:
            # 获取进程状态
            process_state = self._process_manager.get_state()
            runtime = process_state.runtime_seconds / 60  # 转换为分钟
            max_duration = self._config.get("max_session_duration", 55)

            # 提前5分钟续约
            if runtime >= (max_duration - 5):
                self._log("info", f"会话即将到期 ({runtime:.1f}分钟)，启动续约")

                # 停止当前会话
                await self._stop_current_session()

                # 等待几秒确保清理完成
                await asyncio.sleep(3)

                # 触发新的交易周期
                await self._trading_cycle()

        except Exception as e:
            self._log("error", f"自动续约检查异常: {e}")

    # ═══════════════════════════════════════════════════════════════
    # 风险管理和熔断
    # ═══════════════════════════════════════════════════════════════

    async def _risk_check_cycle(self):
        """风险检查周期"""
        if self.status != AutoTradingStatus.RUNNING:
            return

        try:
            risk_assessment = self._risk_monitor.assess_risk()

            # 记录风险事件
            if risk_assessment.events:
                for event in risk_assessment.events:
                    self._log("warning", f"风险事件: {event.message}")

                    if self._current_session:
                        with self._session_lock:
                            self._current_session.risk_events.append(event.to_dict())

            # 检查是否需要熔断
            if risk_assessment.should_halt and not self._circuit_breaker_triggered:
                await self._trigger_circuit_breaker(risk_assessment)

        except Exception as e:
            self._log("error", f"风险检查异常: {e}")

    async def _trigger_circuit_breaker(self, risk_assessment: Any):
        """触发熔断"""
        self._circuit_breaker_triggered = True
        self._circuit_breaker_time = datetime.now()

        self._log("warning", f"触发熔断: {risk_assessment.overall_level.value}")

        # 停止当前交易
        if self._current_session:
            await self._stop_current_session()

        self._set_status(AutoTradingStatus.HALTED)

        self._trigger_event("circuit_breaker", {
            "level": risk_assessment.overall_level.value,
            "score": risk_assessment.score,
            "recommendations": risk_assessment.recommendations
        })

    def _check_circuit_breaker_recovery(self) -> bool:
        """检查熔断是否可以恢复"""
        if not self._circuit_breaker_triggered or not self._circuit_breaker_time:
            return True

        elapsed = (datetime.now() - self._circuit_breaker_time).total_seconds() / 60

        if elapsed >= self._cooldown_minutes:
            # 重新评估风险
            risk_assessment = self._risk_monitor.assess_risk()

            if not risk_assessment.should_halt:
                self._log("info", "风险降低，自动恢复交易")
                safe_create_task(self.resume(), name="resume")
                return True

        return False

    def _on_risk_event(self, event: Any):
        """风险事件回调"""
        self._log("warning", f"风险事件: {event.message}")

    def _on_intervention(self, event: Any, action: str):
        """干预回调"""
        self._log("warning", f"干预执行: {action} - {event.message}")

    # ═══════════════════════════════════════════════════════════════
    # 资源管理
    # ═══════════════════════════════════════════════════════════════

    async def _cleanup_resources(self):
        """清理资源"""
        self._log("info", "执行资源清理...")

        try:
            # 强制垃圾回收
            gc.collect()

            # 清理过期日志
            cutoff = datetime.now() - timedelta(hours=24)
            self._logs = [
                log for log in self._logs
                if datetime.fromisoformat(log["timestamp"]) > cutoff
            ]

            self._log("info", "资源清理完成")

        except Exception as e:
            self._log("error", f"资源清理异常: {e}")

    # ═══════════════════════════════════════════════════════════════
    # 查询接口
    # ═══════════════════════════════════════════════════════════════

    def get_status(self) -> dict[str, Any]:
        """获取完整状态"""
        return {
            "status": self.status.value,
            "current_session": self._current_session.to_dict() if self._current_session else None,
            "stats": self._stats.to_dict(),
            "circuit_breaker": {
                "triggered": self._circuit_breaker_triggered,
                "since": self._circuit_breaker_time.isoformat() if self._circuit_breaker_time else None
            },
            "config": {
                "interval_minutes": self._config.get("interval_minutes", 60),
                "auto_renew": self._config.get("auto_renew", True)
            }
        }

    def get_logs(self, limit: int = 100) -> list[dict]:
        """获取日志"""
        return self._logs[-limit:]

    def get_session_history(self) -> list[dict]:
        """获取会话历史"""
        return [s.to_dict() for s in self._session_history]


# ═══════════════════════════════════════════════════════════════════
# 全局实例
# ═══════════════════════════════════════════════════════════════════

_auto_trading_scheduler: AutoTradingScheduler | None = None
_scheduler_lock = threading.Lock()


def get_auto_trading_scheduler() -> AutoTradingScheduler:
    """获取自动交易调度器单例"""
    global _auto_trading_scheduler
    if _auto_trading_scheduler is None:
        with _scheduler_lock:
            if _auto_trading_scheduler is None:
                _auto_trading_scheduler = AutoTradingScheduler()
    return _auto_trading_scheduler
