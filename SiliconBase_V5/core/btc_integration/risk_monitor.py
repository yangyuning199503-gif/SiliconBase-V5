#!/usr/bin/env python3
"""
BTC 交易风险监控系统

功能:
    - 实时监控交易风险
    - 触发风险阈值时自动干预
    - 异常情况检测和处理
    - 熔断机制

风控层级:
    L1: 账户级风控 (总权益、保证金率)
    L2: 仓位级风控 (单个仓位亏损、持仓时间)
    L3: 策略级风控 (策略失效、连续亏损)
    L4: 市场级风控 (黑天鹅、极端波动)
"""

import contextlib
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np

from core.estimation.state_estimator import KalmanFilter


class RiskLevel(Enum):
    """风险等级"""
    LOW = "low"           # 低风险，正常交易
    MEDIUM = "medium"     # 中风险，警告
    HIGH = "high"         # 高风险，限制交易
    CRITICAL = "critical" # 极高风险，强制平仓


class RiskEventType(Enum):
    """风险事件类型"""
    # 账户级
    MARGIN_LOW = "margin_low"           # 保证金率低
    EQUITY_DROP = "equity_drop"         # 权益大幅回撤

    # 仓位级
    POSITION_LOSS = "position_loss"     # 持仓亏损过大
    POSITION_TIMEOUT = "position_timeout"  # 持仓时间过长

    # 策略级
    STRATEGY_FAIL = "strategy_fail"     # 策略连续亏损
    SIGNAL_STALE = "signal_stale"       # 信号失效

    # 市场级
    BLACK_SWAN = "black_swan"           # 黑天鹅事件
    HIGH_VOLATILITY = "high_volatility" # 极端波动
    LIQUIDATION_RISK = "liquidation_risk"  # 清算风险

    # 系统级
    CONNECTION_LOST = "connection_lost" # 连接中断
    API_ERROR = "api_error"             # API 错误


@dataclass
class RiskThreshold:
    """风险阈值配置"""
    # 账户级
    min_margin_ratio: float = 10.0  # 最低保证金率 %
    max_daily_loss_pct: float = 5.0  # 最大日回撤 %
    max_total_loss_pct: float = 20.0  # 最大总回撤 %

    # 仓位级
    max_position_loss_pct: float = 3.0  # 单个仓位最大亏损 %
    max_position_hold_hours: float = 24.0  # 最大持仓时间（小时）

    # 策略级
    max_consecutive_losses: int = 3  # 最大连续亏损次数
    strategy_timeout_minutes: int = 30  # 策略信号超时（分钟）

    # 市场级
    max_volatility_pct: float = 10.0  # 最大可接受波动率 %
    liquidation_proximity_pct: float = 20.0  # 强平距离 %

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_margin_ratio": self.min_margin_ratio,
            "max_daily_loss_pct": self.max_daily_loss_pct,
            "max_total_loss_pct": self.max_total_loss_pct,
            "max_position_loss_pct": self.max_position_loss_pct,
            "max_position_hold_hours": self.max_position_hold_hours,
            "max_consecutive_losses": self.max_consecutive_losses,
            "strategy_timeout_minutes": self.strategy_timeout_minutes,
            "max_volatility_pct": self.max_volatility_pct,
            "liquidation_proximity_pct": self.liquidation_proximity_pct,
        }


@dataclass
class RiskEvent:
    """风险事件"""
    event_type: RiskEventType
    level: RiskLevel
    message: str
    timestamp: float
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type.value,
            "level": self.level.value,
            "message": self.message,
            "timestamp": self.timestamp,
            "data": self.data
        }


@dataclass
class RiskAssessment:
    """风险评估结果"""
    overall_level: RiskLevel
    score: float  # 0-100, 越高越危险
    events: list[RiskEvent]
    recommendations: list[str]
    should_halt: bool  # 是否应停止交易
    should_reduce: bool  # 是否应减仓

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_level": self.overall_level.value,
            "score": round(self.score, 2),
            "events": [e.to_dict() for e in self.events],
            "recommendations": self.recommendations,
            "should_halt": self.should_halt,
            "should_reduce": self.should_reduce
        }


class BTCRiskMonitor:
    """
    BTC 交易风险监控器

    实时监控交易风险，触发干预措施
    """

    def __init__(self, thresholds: RiskThreshold | None = None):
        self.thresholds = thresholds or RiskThreshold()

        # 状态跟踪
        self._account_state: dict[str, Any] = {}
        self._position_states: dict[str, dict[str, Any]] = {}
        self._strategy_states: dict[str, dict[str, Any]] = {}
        self._market_state: dict[str, Any] = {}

        # 历史记录
        self._loss_history: list[float] = []
        self._max_history_size = 50

        # 回调函数
        self._event_callbacks: list[Callable[[RiskEvent], None]] = []
        self._intervention_callbacks: list[Callable[[RiskEvent, str], None]] = []

        # 监控线程
        self._monitoring = False
        self._monitor_thread: threading.Thread | None = None

        # 锁
        self._lock = threading.RLock()

        # ── KF：风险趋势平滑（LeJEPA 状态推断引擎接入）────────────────────
        self._risk_kf = KalmanFilter(state_dim=2, observation_dim=1)
        # 状态: [pnl均值, pnl趋势]
        self._risk_kf.X = np.array([[0.0], [0.0]])
        self._risk_kf.P = np.eye(2)
        self._risk_kf_A = np.array([[1.0, 1.0], [0.0, 1.0]])  # 恒定趋势模型
        self._risk_kf_Q = np.eye(2) * 0.001
        self._risk_kf_H = np.array([[1.0, 0.0]])
        self._risk_kf_R = np.eye(1) * 0.5

    def register_event_callback(self, callback: Callable[[RiskEvent], None]):
        """注册风险事件回调"""
        self._event_callbacks.append(callback)

    def register_intervention_callback(self, callback: Callable[[RiskEvent, str], None]):
        """注册干预回调"""
        self._intervention_callbacks.append(callback)

    def _trigger_event(self, event: RiskEvent):
        """触发风险事件"""
        for callback in self._event_callbacks:
            with contextlib.suppress(Exception):
                callback(event)

    def _trigger_intervention(self, event: RiskEvent, action: str):
        """触发干预"""
        for callback in self._intervention_callbacks:
            with contextlib.suppress(Exception):
                callback(event, action)

    def update_account_state(self, state: dict[str, Any]):
        """更新账户状态"""
        with self._lock:
            self._account_state = state.copy()

    def update_position_state(self, symbol: str, state: dict[str, Any]):
        """更新仓位状态"""
        with self._lock:
            self._position_states[symbol] = state.copy()

    def update_strategy_state(self, strategy_id: str, state: dict[str, Any]):
        """更新策略状态"""
        with self._lock:
            self._strategy_states[strategy_id] = state.copy()

    def update_market_state(self, state: dict[str, Any]):
        """更新市场状态"""
        with self._lock:
            self._market_state = state.copy()

    def record_trade_result(self, pnl: float):
        """记录交易结果"""
        with self._lock:
            self._loss_history.append(pnl)
            if len(self._loss_history) > self._max_history_size:
                self._loss_history = self._loss_history[-self._max_history_size:]

            # KF 平滑：追踪 PnL 均值与趋势
            try:
                self._risk_kf.predict(self._risk_kf_A, self._risk_kf_Q)
                Z = np.array([[pnl]])
                self._risk_kf.update(Z, self._risk_kf_H, self._risk_kf_R)
            except Exception:
                pass  # KF 失败不影响主风控

    def assess_risk(self) -> RiskAssessment:
        """
        执行风险评估

        Returns:
            RiskAssessment 评估结果
        """
        events: list[RiskEvent] = []

        with self._lock:
            # 1. 账户级风险评估
            account_events = self._check_account_risk()
            events.extend(account_events)

            # 2. 仓位级风险评估
            position_events = self._check_position_risk()
            events.extend(position_events)

            # 3. 策略级风险评估
            strategy_events = self._check_strategy_risk()
            events.extend(strategy_events)

            # 4. 市场级风险评估
            market_events = self._check_market_risk()
            events.extend(market_events)

        # 确定总体风险等级
        overall_level = self._determine_overall_level(events)

        # 计算风险分数
        score = self._calculate_risk_score(events)

        # 生成建议
        recommendations = self._generate_recommendations(events, overall_level)

        # 确定干预措施
        should_halt = overall_level in [RiskLevel.CRITICAL, RiskLevel.HIGH]
        should_reduce = overall_level in [RiskLevel.HIGH, RiskLevel.MEDIUM]

        return RiskAssessment(
            overall_level=overall_level,
            score=score,
            events=events,
            recommendations=recommendations,
            should_halt=should_halt,
            should_reduce=should_reduce
        )

    def _check_account_risk(self) -> list[RiskEvent]:
        """检查账户级风险"""
        events = []

        if not self._account_state:
            return events

        # 检查保证金率
        margin_ratio = self._account_state.get("margin_ratio", 100)
        if margin_ratio < self.thresholds.min_margin_ratio:
            events.append(RiskEvent(
                event_type=RiskEventType.MARGIN_LOW,
                level=RiskLevel.CRITICAL,
                message=f"保证金率过低: {margin_ratio:.2f}% (阈值: {self.thresholds.min_margin_ratio}%)",
                timestamp=time.time(),
                data={"margin_ratio": margin_ratio, "threshold": self.thresholds.min_margin_ratio}
            ))

        # 检查日回撤
        daily_pnl_pct = self._account_state.get("daily_pnl_pct", 0)
        if daily_pnl_pct < -self.thresholds.max_daily_loss_pct:
            events.append(RiskEvent(
                event_type=RiskEventType.EQUITY_DROP,
                level=RiskLevel.HIGH,
                message=f"日回撤过大: {daily_pnl_pct:.2f}%",
                timestamp=time.time(),
                data={"daily_pnl_pct": daily_pnl_pct}
            ))

        return events

    def _check_position_risk(self) -> list[RiskEvent]:
        """检查仓位级风险"""
        events = []

        for symbol, position in self._position_states.items():
            # 检查持仓亏损
            unrealized_pnl_pct = position.get("unrealized_pnl_pct", 0)
            if unrealized_pnl_pct < -self.thresholds.max_position_loss_pct:
                events.append(RiskEvent(
                    event_type=RiskEventType.POSITION_LOSS,
                    level=RiskLevel.HIGH,
                    message=f"{symbol} 持仓亏损过大: {unrealized_pnl_pct:.2f}%",
                    timestamp=time.time(),
                    data={"symbol": symbol, "loss_pct": unrealized_pnl_pct}
                ))

            # 检查持仓时间
            hold_hours = position.get("hold_hours", 0)
            if hold_hours > self.thresholds.max_position_hold_hours:
                events.append(RiskEvent(
                    event_type=RiskEventType.POSITION_TIMEOUT,
                    level=RiskLevel.MEDIUM,
                    message=f"{symbol} 持仓时间过长: {hold_hours:.1f}小时",
                    timestamp=time.time(),
                    data={"symbol": symbol, "hold_hours": hold_hours}
                ))

        return events

    def _check_strategy_risk(self) -> list[RiskEvent]:
        """检查策略级风险"""
        events = []

        # 检查连续亏损
        recent_losses = [pnl for pnl in self._loss_history[-5:] if pnl < 0]
        if len(recent_losses) >= self.thresholds.max_consecutive_losses:
            events.append(RiskEvent(
                event_type=RiskEventType.STRATEGY_FAIL,
                level=RiskLevel.HIGH,
                message=f"连续亏损 {len(recent_losses)} 次，策略可能失效",
                timestamp=time.time(),
                data={"consecutive_losses": len(recent_losses)}
            ))

        # 检查策略信号超时
        for strategy_id, state in self._strategy_states.items():
            last_signal_time = state.get("last_signal_time", 0)
            elapsed_minutes = (time.time() - last_signal_time) / 60
            if elapsed_minutes > self.thresholds.strategy_timeout_minutes:
                events.append(RiskEvent(
                    event_type=RiskEventType.SIGNAL_STALE,
                    level=RiskLevel.MEDIUM,
                    message=f"{strategy_id} 信号超时: {elapsed_minutes:.0f}分钟未更新",
                    timestamp=time.time(),
                    data={"strategy_id": strategy_id, "elapsed_minutes": elapsed_minutes}
                ))

        return events

    def _check_market_risk(self) -> list[RiskEvent]:
        """检查市场级风险"""
        events = []

        if not self._market_state:
            return events

        # 检查波动率
        volatility = self._market_state.get("volatility_24h", 0)
        if volatility > self.thresholds.max_volatility_pct:
            events.append(RiskEvent(
                event_type=RiskEventType.HIGH_VOLATILITY,
                level=RiskLevel.HIGH,
                message=f"市场波动率过高: {volatility:.2f}%",
                timestamp=time.time(),
                data={"volatility": volatility}
            ))

        # 检查黑天鹅事件（价格瞬间大幅波动）
        price_change_1h = self._market_state.get("price_change_1h", 0)
        if abs(price_change_1h) > 10:  # 1小时涨跌超过10%
            events.append(RiskEvent(
                event_type=RiskEventType.BLACK_SWAN,
                level=RiskLevel.CRITICAL,
                message=f"检测到极端价格变动: {price_change_1h:+.2f}%/小时",
                timestamp=time.time(),
                data={"price_change_1h": price_change_1h}
            ))

        return events

    def _check_kf_risk_trend(self) -> list[RiskEvent]:
        """KF 趋势风险：检测 PnL 均值与趋势的系统性恶化"""
        events = []

        try:
            kf_state = self._risk_kf.get_state().flatten()
            pnl_mean = float(kf_state[0])
            pnl_trend = float(kf_state[1])

            # 策略级：平均亏损且趋势加速恶化
            if pnl_mean < -0.05 and pnl_trend < -0.03:
                events.append(RiskEvent(
                    event_type=RiskEventType.STRATEGY_FAIL,
                    level=RiskLevel.HIGH,
                    message=f"KF趋势告警：策略平均盈亏 {pnl_mean:.3f}，趋势加速恶化 {pnl_trend:.3f}",
                    timestamp=time.time(),
                    data={"kf_pnl_mean": pnl_mean, "kf_pnl_trend": pnl_trend}
                ))

            # 仓位级：盈利趋势逆转（从盈利转为亏损加速）
            elif len(self._loss_history) >= 5 and pnl_trend < -0.05:
                recent = self._loss_history[-5:]
                if sum(1 for x in recent if x < 0) >= 3:
                    events.append(RiskEvent(
                        event_type=RiskEventType.POSITION_LOSS,
                        level=RiskLevel.MEDIUM,
                        message=f"KF趋势告警：近期连续亏损，趋势斜率 {pnl_trend:.3f}",
                        timestamp=time.time(),
                        data={"kf_pnl_trend": pnl_trend, "recent_losses": recent}
                    ))
        except Exception:
            pass  # KF 状态读取失败不影响主风控

        return events

    def _determine_overall_level(self, events: list[RiskEvent]) -> RiskLevel:
        """确定总体风险等级"""
        if not events:
            return RiskLevel.LOW

        # 取最高风险等级
        level_priority = {
            RiskLevel.CRITICAL: 4,
            RiskLevel.HIGH: 3,
            RiskLevel.MEDIUM: 2,
            RiskLevel.LOW: 1
        }

        max_level = RiskLevel.LOW
        for event in events:
            if level_priority[event.level] > level_priority[max_level]:
                max_level = event.level

        return max_level

    def _calculate_risk_score(self, events: list[RiskEvent]) -> float:
        """计算风险分数 (0-100)"""
        if not events:
            return 0.0

        # 根据事件等级加权
        level_scores = {
            RiskLevel.CRITICAL: 25,
            RiskLevel.HIGH: 15,
            RiskLevel.MEDIUM: 8,
            RiskLevel.LOW: 3
        }

        total_score = sum(level_scores[e.level] for e in events)
        return min(100, total_score)

    def _generate_recommendations(
        self,
        events: list[RiskEvent],
        overall_level: RiskLevel
    ) -> list[str]:
        """生成风控建议"""
        recommendations = []

        if overall_level == RiskLevel.CRITICAL:
            recommendations.append("🚨 立即平仓并停止所有交易")
            recommendations.append("📢 通知用户紧急情况")
        elif overall_level == RiskLevel.HIGH:
            recommendations.append("⚠️ 暂停新开仓，考虑减仓")
            recommendations.append("📊 密切关注市场变化")
        elif overall_level == RiskLevel.MEDIUM:
            recommendations.append("⚡ 降低仓位，收紧止损")
            recommendations.append("👀 提高监控频率")
        else:
            recommendations.append("✅ 风险可控，正常交易")

        # 针对具体事件的建议
        for event in events:
            if event.event_type == RiskEventType.MARGIN_LOW:
                recommendations.append("💰 追加保证金或减少杠杆")
            elif event.event_type == RiskEventType.POSITION_LOSS:
                recommendations.append("🛑 检查持仓，考虑止损")
            elif event.event_type == RiskEventType.STRATEGY_FAIL:
                recommendations.append("🔄 暂停策略，重新评估")

        return recommendations

    def start_monitoring(self, interval: int = 5):
        """启动持续监控"""
        if self._monitoring:
            return

        self._monitoring = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            args=(interval,),
            daemon=True
        )
        self._monitor_thread.start()

    def stop_monitoring(self):
        """停止监控"""
        self._monitoring = False
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=2)

    def _monitor_loop(self, interval: int):
        """监控循环"""
        while self._monitoring:
            try:
                assessment = self.assess_risk()

                # 触发所有风险事件
                for event in assessment.events:
                    self._trigger_event(event)

                    # 根据风险等级触发干预
                    if event.level in [RiskLevel.CRITICAL, RiskLevel.HIGH]:
                        if event.level == RiskLevel.CRITICAL:
                            self._trigger_intervention(event, "HALT")
                        else:
                            self._trigger_intervention(event, "REDUCE")

            except Exception:
                pass

            time.sleep(interval)

    # ═══════════════════════════════════════════════════════════════
    # 自动恢复相关方法（24小时交易新增）
    # ═══════════════════════════════════════════════════════════════

    def should_resume_trading(
        self,
        last_halt_time: float | None = None,
        cooldown_minutes: int = 30
    ) -> bool:
        """
        判断是否可以恢复交易

        Args:
            last_halt_time: 上次熔断时间戳（None表示不检查冷却时间）
            cooldown_minutes: 冷却时间（分钟）

        Returns:
            bool: 是否可以恢复交易
        """
        # 1. 检查冷却时间
        if last_halt_time is not None:
            elapsed_minutes = (time.time() - last_halt_time) / 60
            if elapsed_minutes < cooldown_minutes:
                return False

        # 2. 重新评估当前风险
        assessment = self.assess_risk()

        # 3. 只有低风险才能恢复
        if assessment.overall_level in [RiskLevel.CRITICAL, RiskLevel.HIGH]:
            return False

        # 4. 检查风险趋势
        trend = self.get_risk_trend()
        return trend != "increasing"

    def get_risk_trend(self, window: int = 10) -> str:
        """
        获取风险趋势

        Args:
            window: 计算趋势的历史窗口大小

        Returns:
            str: "increasing" | "decreasing" | "stable"
        """
        # 简化实现：基于最近几次评估结果
        # 实际项目中可以保存历史风险评估结果

        # 检查最近的亏损记录
        if len(self._loss_history) < window:
            return "stable"

        recent = self._loss_history[-window:]
        negative_count = sum(1 for pnl in recent if pnl < 0)

        # 如果最近大部分交易亏损，认为风险趋势上升
        if negative_count > window * 0.6:
            return "increasing"
        elif negative_count < window * 0.3:
            return "decreasing"

        return "stable"

    def get_recovery_recommendations(self) -> list[str]:
        """获取恢复交易的建议"""
        assessment = self.assess_risk()
        recommendations = []

        if assessment.overall_level == RiskLevel.LOW:
            recommendations.append("✅ 风险较低，可以恢复交易")
            recommendations.append("💡 建议从小仓位开始")
        elif assessment.overall_level == RiskLevel.MEDIUM:
            recommendations.append("⚠️ 风险中等，谨慎恢复")
            recommendations.append("💡 建议降低仓位，选择低风险策略")
        else:
            recommendations.append("🚫 风险仍然较高，不建议恢复")
            recommendations.append("💡 等待风险进一步降低")

        # 根据具体风险事件给出建议
        for event in assessment.events:
            if event.level in [RiskLevel.CRITICAL, RiskLevel.HIGH]:
                recommendations.append(f"⚠️ 仍需关注: {event.message}")

        return recommendations

    def is_safe_to_trade(self, max_risk_level: RiskLevel = RiskLevel.MEDIUM) -> bool:
        """
        判断是否适合交易

        Args:
            max_risk_level: 允许的最大风险等级

        Returns:
            bool: 是否适合交易
        """
        assessment = self.assess_risk()

        # 风险等级权重
        level_weights = {
            RiskLevel.LOW: 1,
            RiskLevel.MEDIUM: 2,
            RiskLevel.HIGH: 3,
            RiskLevel.CRITICAL: 4
        }

        current_weight = level_weights.get(assessment.overall_level, 2)
        max_weight = level_weights.get(max_risk_level, 2)

        return current_weight <= max_weight


# 全局监控器实例
_risk_monitor: BTCRiskMonitor | None = None


def get_risk_monitor(thresholds: RiskThreshold | None = None) -> BTCRiskMonitor:
    """获取风险监控器单例"""
    global _risk_monitor
    if _risk_monitor is None:
        _risk_monitor = BTCRiskMonitor(thresholds)
    return _risk_monitor
