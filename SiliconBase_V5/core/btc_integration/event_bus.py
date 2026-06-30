#!/usr/bin/env python3
"""
BTC交易事件总线
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
统一的事件分发系统，连接所有BTC交易相关组件

功能:
- 异步事件发布/订阅
- 消息分类（market/position/risk/news/system）
- 历史事件缓存
- 跨组件通信
"""

import asyncio
import contextlib
import json
import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from core.diagnostic import safe_create_task

logger = logging.getLogger(__name__)


class EventType(Enum):
    """事件类型"""
    MARKET_PRICE = "market_price"           # 价格更新
    MARKET_KLINE = "market_kline"           # K线数据
    MARKET_ORDERBOOK = "market_orderbook"   # 订单簿
    MARKET_FUNDING = "market_funding"       # 资金费率

    NEWS_FLASH = "news_flash"               # 快讯
    NEWS_RISK = "news_risk"                 # 风险事件
    NEWS_MACRO = "news_macro"               # 宏观数据
    NEWS_EXCHANGE = "news_exchange"         # 交易所动态

    POSITION_UPDATE = "position_update"     # 持仓更新
    POSITION_OPEN = "position_open"         # 开仓
    POSITION_CLOSE = "position_close"       # 平仓
    ORDER_FILLED = "order_filled"           # 订单成交

    RISK_WARNING = "risk_warning"           # 风险警告
    RISK_CRITICAL = "risk_critical"         # 严重风险
    RISK_CIRCUIT_BREAKER = "risk_circuit_breaker"  # 熔断

    STRATEGY_SIGNAL = "strategy_signal"     # 策略信号
    STRATEGY_CHANGE = "strategy_change"     # 策略切换

    QUANT_SIGNAL = "quant_signal"           # 量化策略信号
    DECISION_PENDING = "decision_pending"   # 待确认决策
    DECISION_CONFIRMED = "decision_confirmed"  # 决策已确认
    DECISION_REJECTED = "decision_rejected"    # 决策已拒绝

    SYSTEM_STATUS = "system_status"         # 系统状态
    SYSTEM_ERROR = "system_error"           # 系统错误
    AI_DECISION = "ai_decision"             # AI决策
    AI_INTERVENTION = "ai_intervention"     # AI干预
    TELEMETRY_BATCH = "telemetry_batch"     # 聚合遥测摘要（AI可见层）


class EventPriority(Enum):
    """事件优先级"""
    CRITICAL = 0    # 关键（熔断、强平）
    HIGH = 1        # 高（风险警告、重大消息）
    NORMAL = 2      # 普通（价格更新、持仓变化）
    LOW = 3         # 低（日志、状态报告）


@dataclass
class TradingEvent:
    """交易事件"""
    event_type: EventType
    data: dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    source: str = "unknown"           # 事件来源
    priority: EventPriority = EventPriority.NORMAL
    symbol: str | None = None      # 相关交易对
    id: str = field(default_factory=lambda: f"evt_{time.time_ns()}")
    # 【治理】链路追踪ID，用于事后审计
    trace_id: str | None = None

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "event_type": self.event_type.value,
            "data": self.data,
            "timestamp": self.timestamp,
            "source": self.source,
            "priority": self.priority.value,
            "symbol": self.symbol,
        }

    def to_json(self) -> str:
        """转换为JSON"""
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)


class EventBus:
    """
    交易事件总线

    单例模式，全局统一的事件分发中心
    """
    _instance: Optional['EventBus'] = None
    _lock = asyncio.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # 订阅者: {event_type: [(callback, priority_filter, symbol_filter), ...]}
        self._subscribers: dict[EventType, list[tuple]] = {}

        # 历史缓存（用于查询）
        self._history: deque = deque(maxlen=10000)

        # 用户隔离历史缓存（用于AI查询和上下文注入）
        self._history_by_user: dict[str, deque] = {}
        self._per_user_history_limit = 100

        # 运行状态
        self._running = False
        self._event_queue: asyncio.Queue = asyncio.Queue(maxsize=5000)  # 【治理】设限防OOM
        self._dispatch_task: asyncio.Task | None = None

        # 统计
        self._stats = {
            "published": 0,
            "delivered": 0,
            "dropped": 0,
        }

        # 【治理】引用计数：记录启动此总线的组件数，防止被误停
        self._ref_count = 0

        logger.info("[EventBus] 初始化完成")

    async def start(self):
        """启动事件总线

        【治理】全局单例，引用计数管理生命周期。
        只有第一个 start() 真正启动，最后一个 stop() 真正停止。
        """
        self._ref_count += 1
        if self._running:
            logger.debug(f"[EventBus] 引用计数+1 = {self._ref_count}，总线已在运行")
            return
        self._running = True
        self._dispatch_task = safe_create_task(self._dispatch_loop(), name="_dispatch_loop")
        logger.info(f"[EventBus] 已启动 (ref_count={self._ref_count})")

    async def stop(self, caller: str = "unknown"):
        """停止事件总线

        【治理】全局单例，引用计数管理生命周期。
        只有引用计数归零时才真正停止。调用方必须提供 caller 标识。

        Args:
            caller: 调用方标识（如 "trading_subagent_BTC"）
        """
        self._ref_count = max(0, self._ref_count - 1)

        # 检查是否仍有活跃订阅者
        subscriber_count = sum(len(s) for s in self._subscribers.values())

        if self._ref_count > 0:
            logger.warning(
                f"[EventBus] 调用方 '{caller}' 请求停止被忽略: "
                f"ref_count={self._ref_count}, subscribers={subscriber_count}。"
                f"全局总线仍有引用，不得停止。"
            )
            return

        if subscriber_count > 0:
            logger.warning(
                f"[EventBus] 调用方 '{caller}' 请求停止，但仍有 "
                f"{subscriber_count} 个活跃订阅者。继续运行。"
            )
            return

        self._running = False
        if self._dispatch_task:
            self._dispatch_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._dispatch_task
        logger.info(f"[EventBus] 已停止 (caller={caller}, ref_count=0)")

    async def _dispatch_loop(self):
        """事件分发循环"""
        while self._running:
            try:
                event: TradingEvent = await asyncio.wait_for(
                    self._event_queue.get(), timeout=1.0
                )
                await self._dispatch_event(event)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"[EventBus] 分发错误: {e}")

    async def _dispatch_event(self, event: TradingEvent):
        """分发单个事件"""
        # 存入全局历史
        self._history.append(event)

        # 存入用户隔离历史（如果事件包含user_id）
        user_id = event.data.get("user_id")
        if user_id:
            if user_id not in self._history_by_user:
                self._history_by_user[user_id] = deque(maxlen=self._per_user_history_limit)
            self._history_by_user[user_id].append(event)

        # 获取订阅者
        subscribers = self._subscribers.get(event.event_type, [])

        # 并行分发给所有订阅者
        tasks = []
        for callback, priority_filter, symbol_filter in subscribers:
            # 优先级过滤
            if priority_filter is not None and event.priority.value > priority_filter:
                continue
            # 交易对过滤
            if symbol_filter is not None and event.symbol != symbol_filter:
                continue

            tasks.append(self._safe_callback(callback, event))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
            self._stats["delivered"] += len(tasks)

    async def _safe_callback(self, callback: Callable, event: TradingEvent):
        """安全调用回调"""
        try:
            if asyncio.iscoroutinefunction(callback):
                await callback(event)
            else:
                callback(event)
        except Exception as e:
            logger.error(f"[EventBus] 回调错误 ({callback.__name__}): {e}")

    def subscribe(
        self,
        event_type: EventType,
        callback: Callable[[TradingEvent], Any],
        priority_filter: int | None = None,
        symbol_filter: str | None = None
    ) -> Callable:
        """
        订阅事件

        Args:
            event_type: 事件类型
            callback: 回调函数
            priority_filter: 只接收优先级<=此值的事件
            symbol_filter: 只接收此交易对的事件

        Returns:
            unsubscribe函数
        """
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []

        self._subscribers[event_type].append((callback, priority_filter, symbol_filter))
        logger.debug(f"[EventBus] {event_type.value} 新增订阅者: {callback.__name__}")

        def unsubscribe():
            subs = self._subscribers.get(event_type, [])
            self._subscribers[event_type] = [
                s for s in subs if s[0] != callback
            ]

        return unsubscribe

    def publish(self, event: TradingEvent) -> bool:
        """
        发布事件（同步接口，放入队列）

        Args:
            event: 交易事件

        Returns:
            是否成功入队
        """
        if not self._running:
            logger.warning(f"[EventBus] 未启动，事件被丢弃: {event.event_type.value}")
            return False

        try:
            self._event_queue.put_nowait(event)
            self._stats["published"] += 1
            return True
        except asyncio.QueueFull:
            self._stats["dropped"] += 1
            logger.warning("[EventBus] 队列已满，事件被丢弃")
            return False

    async def publish_async(self, event: TradingEvent) -> bool:
        """异步发布事件"""
        if not self._running:
            return False
        await self._event_queue.put(event)
        self._stats["published"] += 1
        return True

    def get_recent_events(
        self,
        event_type: EventType | None = None,
        symbol: str | None = None,
        since: float | None = None,
        limit: int = 100
    ) -> list[TradingEvent]:
        """获取最近事件"""
        result = []
        for event in reversed(self._history):
            if event_type and event.event_type != event_type:
                continue
            if symbol and event.symbol != symbol:
                continue
            if since and event.timestamp < since:
                continue
            result.append(event)
            if len(result) >= limit:
                break
        return result

    def get_stats(self) -> dict:
        """获取统计信息"""
        queue_size = self._event_queue.qsize()
        queue_maxsize = self._event_queue.maxsize
        queue_usage = queue_size / queue_maxsize if queue_maxsize > 0 else 0

        # 【治理】队列使用率超80%时告警
        if queue_usage > 0.8:
            logger.warning(
                f"[EventBus] 队列使用率过高: {queue_usage:.1%} "
                f"({queue_size}/{queue_maxsize})"
            )

        return {
            **self._stats,
            "queue_size": queue_size,
            "queue_maxsize": queue_maxsize,
            "queue_usage": f"{queue_usage:.1%}",
            "history_size": len(self._history),
            "user_history_count": len(self._history_by_user),
            "subscriber_count": sum(len(s) for s in self._subscribers.values()),
            "ref_count": self._ref_count,
        }

    def clear_history(self):
        """清空历史"""
        self._history.clear()
        self._history_by_user.clear()

    # ═══════════════════════════════════════════════════════════════
    # AI 可观测层 — 用户隔离查询接口
    # ═══════════════════════════════════════════════════════════════

    def get_recent_events_by_user(
        self,
        user_id: str,
        limit: int = 20,
        event_types: list[EventType] | None = None,
        since: float | None = None
    ) -> list[TradingEvent]:
        """
        获取指定用户的最近事件（AI查询接口）

        Args:
            user_id: 用户ID
            limit: 返回数量上限
            event_types: 过滤的事件类型列表（None=不过滤）
            since: 时间戳下限（None=不限）

        Returns:
            TradingEvent列表（时间倒序）
        """
        user_history = self._history_by_user.get(user_id)
        if not user_history:
            return []

        result = []
        type_set = set(event_types) if event_types else None

        for event in reversed(user_history):
            if type_set and event.event_type not in type_set:
                continue
            if since and event.timestamp < since:
                continue
            result.append(event)
            if len(result) >= limit:
                break
        return result

    def get_summary(self, user_id: str) -> dict[str, Any]:
        """
        生成用户BTC运行摘要（AI上下文注入接口）

        返回结构化摘要，包含：
        - has_activity: 是否有活跃交易活动
        - active_strategies: 活跃策略列表
        - latest_signal: 最近信号摘要
        - risk_level: 当前风险等级
        - summary_text: 自然语言摘要（100字内）
        """
        user_history = self._history_by_user.get(user_id)
        if not user_history:
            return {
                "has_activity": False,
                "active_strategies": [],
                "latest_signal": None,
                "risk_level": "none",
                "summary_text": "",
                "event_count_30s": 0,
            }

        now = time.time()
        since_30s = now - 30
        since_5min = now - 300

        # 统计30秒内事件数（用于判断是否需要注入上下文）
        events_30s = [e for e in user_history if e.timestamp >= since_30s]
        events_5min = [e for e in user_history if e.timestamp >= since_5min]

        # 活跃策略：从 STRATEGY_CHANGE / STRATEGY_SIGNAL 中提取
        active_strategies = set()
        latest_signal = None
        max_risk_level = "none"

        for event in reversed(events_5min):
            if event.event_type == EventType.STRATEGY_CHANGE:
                strategy = event.data.get("strategy")
                status = event.data.get("status", "unknown")
                if strategy and status in ("started", "running"):
                    active_strategies.add(strategy)
                elif strategy and status in ("stopped", "paused", "error"):
                    active_strategies.discard(strategy)

            elif event.event_type == EventType.STRATEGY_SIGNAL and latest_signal is None:
                latest_signal = {
                    "action": event.data.get("action", "unknown"),
                    "symbol": event.symbol or event.data.get("symbol", "unknown"),
                    "reason": event.data.get("reason", "")[:50],
                    "timestamp": event.timestamp,
                }

            elif event.event_type in (EventType.RISK_WARNING, EventType.RISK_CRITICAL, EventType.RISK_CIRCUIT_BREAKER):
                level = event.data.get("level", "warning")
                if event.event_type == EventType.RISK_CRITICAL or level == "critical":
                    max_risk_level = "critical"
                elif max_risk_level != "critical" and (level == "high" or event.event_type == EventType.RISK_WARNING):
                    max_risk_level = "high"
                elif max_risk_level == "none":
                    max_risk_level = "medium"

        # 生成自然语言摘要
        parts = []
        if active_strategies:
            strategies_text = ", ".join(sorted(active_strategies))
            parts.append(f"策略 {strategies_text} 运行中")
        if latest_signal:
            parts.append(f"最近信号：{latest_signal['symbol']} {latest_signal['action']}")
        if max_risk_level != "none":
            parts.append(f"风险等级：{max_risk_level}")

        summary_text = " | ".join(parts) if parts else ""

        return {
            "has_activity": bool(active_strategies) or bool(events_30s),
            "active_strategies": list(active_strategies),
            "latest_signal": latest_signal,
            "risk_level": max_risk_level,
            "summary_text": summary_text,
            "event_count_30s": len(events_30s),
        }

    def emit_batch(self, user_id: str, events_data: list[dict[str, Any]], source: str = "telemetry"):
        """
        发布聚合遥测批次（降低事件频率，避免轰炸前端和AI）

        Args:
            user_id: 用户ID
            events_data: 聚合的事件数据列表
            source: 事件来源标识
        """
        if not events_data:
            return
        self.publish(TradingEvent(
            event_type=EventType.TELEMETRY_BATCH,
            data={
                "user_id": user_id,
                "batch_size": len(events_data),
                "events": events_data,
            },
            source=source,
            priority=EventPriority.NORMAL,
        ))


# 全局事件总线实例
event_bus = EventBus()


# 便捷函数
def publish_market_price(symbol: str, price: float, source: str = "okx"):
    """发布价格更新"""
    event_bus.publish(TradingEvent(
        event_type=EventType.MARKET_PRICE,
        data={"price": price, "symbol": symbol},
        source=source,
        symbol=symbol,
        priority=EventPriority.NORMAL
    ))


def publish_news_flash(title: str, content: str, tags: list[str], source: str = "blockbeats"):
    """发布快讯"""
    priority = EventPriority.HIGH if "risk" in tags else EventPriority.NORMAL
    event_bus.publish(TradingEvent(
        event_type=EventType.NEWS_FLASH,
        data={"title": title, "content": content, "tags": tags},
        source=source,
        priority=priority
    ))


def publish_position_update(symbol: str, position_data: dict, source: str = "trading", trace_id: str = None):
    """发布持仓更新"""
    event_bus.publish(TradingEvent(
        event_type=EventType.POSITION_UPDATE,
        data=position_data,
        source=source,
        symbol=symbol,
        priority=EventPriority.NORMAL,
        trace_id=trace_id
    ))


def publish_risk_warning(level: str, message: str, data: dict = None, source: str = "risk", trace_id: str = None):
    """发布风险警告"""
    priority_map = {
        "critical": EventPriority.CRITICAL,
        "high": EventPriority.HIGH,
        "medium": EventPriority.NORMAL,
        "low": EventPriority.LOW,
    }
    event_type = EventType.RISK_CRITICAL if level == "critical" else EventType.RISK_WARNING
    event_bus.publish(TradingEvent(
        event_type=event_type,
        data={"level": level, "message": message, **(data or {})},
        source=source,
        priority=priority_map.get(level, EventPriority.NORMAL),
        trace_id=trace_id
    ))


def publish_ai_decision(decision_type: str, decision_data: dict, reasoning: str = "", trace_id: str = None):
    """发布AI决策"""
    event_bus.publish(TradingEvent(
        event_type=EventType.AI_DECISION,
        data={
            "type": decision_type,
            "decision": decision_data,
            "reasoning": reasoning,
            "timestamp": time.time()
        },
        source="ai",
        priority=EventPriority.HIGH,
        trace_id=trace_id
    ))


def publish_ai_intervention(command: str, params: dict = None, reason: str = ""):
    """发布AI干预命令"""
    event_bus.publish(TradingEvent(
        event_type=EventType.AI_INTERVENTION,
        data={
            "command": command,
            "params": params or {},
            "reason": reason,
            "timestamp": time.time()
        },
        source="ai",
        priority=EventPriority.CRITICAL if command in ["emergency_close", "pause"] else EventPriority.HIGH
    ))


def publish_quant_signal(user_id: str, symbol: str, signal_data: dict, source: str = "quant", trace_id: str = None):
    """发布量化策略信号"""
    event_bus.publish(TradingEvent(
        event_type=EventType.QUANT_SIGNAL,
        data={"user_id": user_id, **signal_data},
        source=source,
        symbol=symbol,
        priority=EventPriority.HIGH,
        trace_id=trace_id
    ))


def publish_decision_pending(user_id: str, pending_id: str, decision: dict, context: dict, source: str = "ai", trace_id: str = None):
    """发布待确认决策"""
    event_bus.publish(TradingEvent(
        event_type=EventType.DECISION_PENDING,
        data={"user_id": user_id, "pending_id": pending_id, "decision": decision, "context": context},
        source=source,
        priority=EventPriority.HIGH,
        trace_id=trace_id
    ))


def publish_decision_confirmed(user_id: str, pending_id: str, source: str = "user"):
    """发布决策已确认"""
    event_bus.publish(TradingEvent(
        event_type=EventType.DECISION_CONFIRMED,
        data={"user_id": user_id, "pending_id": pending_id},
        source=source,
        priority=EventPriority.NORMAL
    ))


def publish_decision_rejected(user_id: str, pending_id: str, source: str = "user"):
    """发布决策已拒绝"""
    event_bus.publish(TradingEvent(
        event_type=EventType.DECISION_REJECTED,
        data={"user_id": user_id, "pending_id": pending_id},
        source=source,
        priority=EventPriority.NORMAL
    ))


# 测试代码
if __name__ == "__main__":
    async def test():
        bus = EventBus()
        await bus.start()

        received = []

        def on_price(event: TradingEvent):
            received.append(f"价格: {event.data['price']}")
            print(f"收到价格: {event.data}")

        def on_news(event: TradingEvent):
            received.append(f"新闻: {event.data['title']}")
            print(f"收到新闻: {event.data}")

        bus.subscribe(EventType.MARKET_PRICE, on_price)
        bus.subscribe(EventType.NEWS_FLASH, on_news)

        # 发布测试事件
        publish_market_price("BTC", 65000.0)
        publish_news_flash("测试新闻", "内容", ["test"])
        publish_risk_warning("high", "测试风险")

        await asyncio.sleep(0.5)

        print(f"\n统计: {bus.get_stats()}")
        print(f"收到事件: {received}")

        await bus.stop()

    asyncio.run(test())
