#!/usr/bin/env python3
"""
BTC 交易 WebSocket 实时数据推送
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
提供交易相关的实时 WebSocket 数据流

功能:
- 实时价格推送
- K线数据更新
- AI交易信号推送
- 持仓变更通知
- 风险告警

WebSocket 路径:
- /ws/trading/{symbol} - 单个币种实时数据
- /ws/trading/all - 所有币种聚合数据
"""

import asyncio
import contextlib
import json
import time

from fastapi import Query, WebSocket, WebSocketDisconnect

from api.trading_api import KLineData, PriceInfo, trading_store
from core.logger import logger

# EventBus 集成
try:
    from core.btc_integration.event_bus import EventPriority, EventType, event_bus
    EVENTBUS_AVAILABLE = True
except ImportError as e:
    EVENTBUS_AVAILABLE = False
    logger.warning(f"[TradingWS] EventBus 不可用: {e}")

# 主事件总线集成（用于 market_data_update 等字符串事件）
try:
    from core.sync.event_bus import event_bus as main_event_bus
    MAIN_EVENTBUS_AVAILABLE = True
except ImportError as e:
    MAIN_EVENTBUS_AVAILABLE = False
    logger.warning(f"[TradingWS] 主事件总线不可用: {e}")


# ═══════════════════════════════════════════════════════════════
# WebSocket 连接管理器
# ═══════════════════════════════════════════════════════════════

class TradingWebSocketManager:
    """
    交易 WebSocket 连接管理器

    管理所有交易相关的 WebSocket 连接，负责:
    - 连接注册/注销
    - 消息广播
    - 订阅管理
    """

    def __init__(self):
        # symbol -> {connection_id -> WebSocket}
        self._symbol_connections: dict[str, dict[str, WebSocket]] = {}

        # connection_id -> {symbols: Set[str], last_ping: float}
        self._connection_info: dict[str, dict] = {}

        # 全局连接 (订阅所有币种)
        self._global_connections: dict[str, WebSocket] = {}

    async def connect_symbol(self, websocket: WebSocket, symbol: str, connection_id: str):
        """连接指定币种的 WebSocket"""
        await websocket.accept()

        symbol = symbol.upper()

        if symbol not in self._symbol_connections:
            self._symbol_connections[symbol] = {}

        self._symbol_connections[symbol][connection_id] = websocket
        self._connection_info[connection_id] = {
            "symbols": {symbol},
            "last_ping": time.time(),
            "type": "symbol"
        }

        logger.info(f"[TradingWS] 新连接: {connection_id} -> {symbol}")

        # 发送连接成功消息
        await self._send_message(websocket, {
            "type": "connected",
            "connection_id": connection_id,
            "symbol": symbol,
            "timestamp": int(time.time())
        })

    async def connect_global(self, websocket: WebSocket, connection_id: str):
        """连接全局 WebSocket (订阅所有币种)"""
        await websocket.accept()

        self._global_connections[connection_id] = websocket
        self._connection_info[connection_id] = {
            "symbols": set(trading_store.symbols.keys()),
            "last_ping": time.time(),
            "type": "global"
        }

        logger.info(f"[TradingWS] 全局连接: {connection_id}")

        await self._send_message(websocket, {
            "type": "connected",
            "connection_id": connection_id,
            "mode": "global",
            "symbols": list(trading_store.symbols.keys()),
            "timestamp": int(time.time())
        })

    def disconnect(self, connection_id: str):
        """断开连接"""
        if connection_id not in self._connection_info:
            return

        info = self._connection_info[connection_id]

        if info["type"] == "symbol":
            for symbol in info["symbols"]:
                if symbol in self._symbol_connections:
                    self._symbol_connections[symbol].pop(connection_id, None)
        else:
            self._global_connections.pop(connection_id, None)

        del self._connection_info[connection_id]
        logger.info(f"[TradingWS] 断开连接: {connection_id}")

    async def broadcast_to_symbol(self, symbol: str, message: dict):
        """向指定币种的所有连接广播消息"""
        symbol = symbol.upper()

        # 发送给订阅该币种的连接
        if symbol in self._symbol_connections:
            disconnected = []
            for conn_id, ws in self._symbol_connections[symbol].items():
                try:
                    await self._send_message(ws, message)
                except Exception:
                    disconnected.append(conn_id)

            # 清理断开的连接
            for conn_id in disconnected:
                self._symbol_connections[symbol].pop(conn_id, None)

        # 发送给全局连接
        disconnected = []
        for conn_id, ws in self._global_connections.items():
            try:
                await self._send_message(ws, message)
            except Exception:
                disconnected.append(conn_id)

        for conn_id in disconnected:
            self._global_connections.pop(conn_id, None)

    async def _send_message(self, websocket: WebSocket, message: dict):
        """发送消息到 WebSocket"""
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.debug(f"[TradingWS] 发送消息失败: {e}")
            raise


# 全局 WebSocket 管理器实例
trading_ws_manager = TradingWebSocketManager()


# ═══════════════════════════════════════════════════════════════
# WebSocket 处理器
# ═══════════════════════════════════════════════════════════════

async def handle_symbol_websocket(
    websocket: WebSocket,
    symbol: str,
    token: str | None = Query(None)
):
    """
    处理单个币种的 WebSocket 连接

    路径: /ws/trading/{symbol}

    推送内容:
    - price_update: 价格更新 (1秒间隔)
    - kline_update: K线更新
    - trade_signal: AI交易信号
    - position_update: 持仓变更
    - risk_alert: 风险告警

    客户端消息:
    - ping: 心跳
    - subscribe: 订阅额外币种
    - unsubscribe: 取消订阅
    """
    symbol = symbol.upper()
    connection_id = f"{symbol}_{id(websocket)}"

    # 检查币种是否存在
    if symbol not in trading_store.symbols:
        await websocket.accept()
        await websocket.send_json({
            "type": "error",
            "message": f"币种 {symbol} 不存在"
        })
        await websocket.close()
        return

    await trading_ws_manager.connect_symbol(websocket, symbol, connection_id)

    # 【新增】订阅 EventBus AI 决策事件
    event_unsubscribers = []

    if EVENTBUS_AVAILABLE:
        try:
            # 订阅 AI 决策事件
            async def on_ai_decision(event):
                """处理 AI 决策事件"""
                try:
                    event_symbol = event.data.get("symbol")
                    if event_symbol and event_symbol.upper() == symbol:
                        decision_data = event.data.get("decision", {})
                        await websocket.send_json({
                            "type": "trade_signal",
                            "symbol": symbol,
                            "signal": {
                                "action": decision_data.get("action"),
                                "strategy": decision_data.get("strategy"),
                                "confidence": decision_data.get("confidence"),
                                "reason": decision_data.get("reasoning", "")[:100],
                                "timestamp": event.timestamp
                            }
                        })
                        logger.debug(f"[TradingWS] 推送 AI 决策: {symbol}")
                except Exception as e:
                    logger.error(f"[TradingWS] 推送 AI 决策失败: {e}")

            unsub_decision = event_bus.subscribe(
                EventType.AI_DECISION,
                on_ai_decision,
                priority_filter=EventPriority.HIGH.value
            )
            event_unsubscribers.append(unsub_decision)

            # 订阅风险事件
            async def on_risk_event(event):
                """处理风险事件"""
                try:
                    event_symbol = event.data.get("symbol")
                    if event_symbol and event_symbol.upper() == symbol:
                        await websocket.send_json({
                            "type": "risk_alert",
                            "symbol": symbol,
                            "level": event.data.get("level", "warning"),
                            "message": event.data.get("message", ""),
                            "timestamp": event.timestamp
                        })
                        logger.debug(f"[TradingWS] 推送风险告警: {symbol}")
                except Exception as e:
                    logger.error(f"[TradingWS] 推送风险告警失败: {e}")

            unsub_risk = event_bus.subscribe(
                EventType.RISK_WARNING,
                on_risk_event,
                priority_filter=EventPriority.HIGH.value
            )
            event_unsubscribers.append(unsub_risk)

            # 订阅策略信号事件（AI可观测层 → 前端）
            async def on_strategy_signal(event):
                """处理策略信号事件"""
                try:
                    event_symbol = event.data.get("symbol")
                    if event_symbol and event_symbol.upper() == symbol:
                        await websocket.send_json({
                            "type": "strategy_signal",
                            "symbol": symbol,
                            "action": event.data.get("action", "unknown"),
                            "strategy": event.data.get("strategy", ""),
                            "result_summary": event.data.get("result_summary", ""),
                            "timestamp": event.timestamp
                        })
                        logger.debug(f"[TradingWS] 推送策略信号: {symbol}")
                except Exception as e:
                    logger.error(f"[TradingWS] 推送策略信号失败: {e}")

            unsub_strategy = event_bus.subscribe(
                EventType.STRATEGY_SIGNAL,
                on_strategy_signal,
                priority_filter=EventPriority.NORMAL.value
            )
            event_unsubscribers.append(unsub_strategy)

            # 订阅持仓更新事件
            async def on_position_update(event):
                """处理持仓更新事件"""
                try:
                    event_symbol = event.symbol
                    if event_symbol and event_symbol.upper() == symbol:
                        await websocket.send_json({
                            "type": "position_update",
                            "symbol": symbol,
                            "data": event.data,
                            "timestamp": event.timestamp
                        })
                        logger.debug(f"[TradingWS] 推送持仓更新: {symbol}")
                except Exception as e:
                    logger.error(f"[TradingWS] 推送持仓更新失败: {e}")

            unsub_position = event_bus.subscribe(
                EventType.POSITION_UPDATE,
                on_position_update,
                priority_filter=EventPriority.NORMAL.value
            )
            event_unsubscribers.append(unsub_position)

            # 订阅聚合遥测批次（降低频率的摘要推送）
            async def on_telemetry_batch(event):
                """处理聚合遥测批次"""
                try:
                    batch_events = event.data.get("events", [])
                    symbol_related = [
                        e for e in batch_events
                        if e.get("symbol", "").upper() == symbol
                    ]
                    if symbol_related:
                        await websocket.send_json({
                            "type": "batch_update",
                            "symbol": symbol,
                            "batch_size": len(symbol_related),
                            "events": symbol_related,
                            "timestamp": event.timestamp
                        })
                        logger.debug(f"[TradingWS] 推送批次更新: {symbol}, {len(symbol_related)} 条")
                except Exception as e:
                    logger.error(f"[TradingWS] 推送批次更新失败: {e}")

            unsub_batch = event_bus.subscribe(
                EventType.TELEMETRY_BATCH,
                on_telemetry_batch,
                priority_filter=EventPriority.NORMAL.value
            )
            event_unsubscribers.append(unsub_batch)

            # 订阅主事件总线的 market_data_update（来自 TradingSubAgent）
            if MAIN_EVENTBUS_AVAILABLE:
                async def on_market_data_update(event):
                    """处理市场数据更新事件"""
                    try:
                        event_symbol = event.data.get("symbol") if hasattr(event, 'data') else None
                        logger.info(f"[TradingWS] 收到 market_data_update: symbol={event_symbol}, target={symbol}")
                        if event_symbol and event_symbol.upper() == symbol:
                            await websocket.send_json({
                                "type": "market_data_update",
                                "symbol": symbol,
                                "price": event.data.get("price", 0),
                                "change_24h_percent": event.data.get("change_24h_percent", 0),
                                "source": event.data.get("source", "okx"),
                                "timestamp": event.data.get("timestamp", time.time()),
                            })
                            logger.info(f"[TradingWS] 已推送 market_data_update 到 WebSocket: {symbol}")
                    except Exception as e:
                        logger.error(f"[TradingWS] 推送市场数据更新失败: {e}")

                main_event_bus.subscribe("market_data_update", on_market_data_update)
                event_unsubscribers.append(lambda: main_event_bus.unsubscribe("market_data_update", on_market_data_update))

                # 【P3新增】订阅 MCP 调用事件
                async def on_mcp_call_start(event):
                    try:
                        await websocket.send_json({
                            "type": "mcp_call_start",
                            "tool_name": event.data.get("tool_name") if hasattr(event, 'data') else event.get("tool_name"),
                            "symbol": event.data.get("symbol") if hasattr(event, 'data') else event.get("symbol"),
                            "timestamp": event.data.get("timestamp") if hasattr(event, 'data') else event.get("timestamp"),
                        })
                    except Exception as e:
                        logger.debug(f"[TradingWS] 推送 mcp_call_start 失败: {e}")

                main_event_bus.subscribe("mcp_call_start", on_mcp_call_start)
                event_unsubscribers.append(lambda: main_event_bus.unsubscribe("mcp_call_start", on_mcp_call_start))

                async def on_mcp_call_complete(event):
                    try:
                        await websocket.send_json({
                            "type": "mcp_call_complete",
                            "tool_name": event.data.get("tool_name") if hasattr(event, 'data') else event.get("tool_name"),
                            "success": event.data.get("success") if hasattr(event, 'data') else event.get("success"),
                            "duration_ms": event.data.get("duration_ms") if hasattr(event, 'data') else event.get("duration_ms"),
                            "result_summary": event.data.get("result_summary") if hasattr(event, 'data') else event.get("result_summary"),
                            "symbol": event.data.get("symbol") if hasattr(event, 'data') else event.get("symbol"),
                            "timestamp": event.data.get("timestamp") if hasattr(event, 'data') else event.get("timestamp"),
                        })
                    except Exception as e:
                        logger.debug(f"[TradingWS] 推送 mcp_call_complete 失败: {e}")

                main_event_bus.subscribe("mcp_call_complete", on_mcp_call_complete)
                event_unsubscribers.append(lambda: main_event_bus.unsubscribe("mcp_call_complete", on_mcp_call_complete))

                # 【P3新增】订阅指挥官报告事件
                async def on_commander_report(event):
                    try:
                        data = event.data if hasattr(event, 'data') else event
                        await websocket.send_json({
                            "type": "commander_report",
                            "timestamp": data.get("timestamp"),
                            "active_agents": data.get("active_agents"),
                            "total_positions": data.get("total_positions"),
                            "daily_pnl": data.get("daily_pnl"),
                            "risk_exposure": data.get("risk_exposure"),
                            "market_sentiment": data.get("market_sentiment"),
                            "ai_thoughts": data.get("ai_thoughts"),
                        })
                    except Exception as e:
                        logger.debug(f"[TradingWS] 推送 commander_report 失败: {e}")

                main_event_bus.subscribe("commander_report", on_commander_report)
                event_unsubscribers.append(lambda: main_event_bus.unsubscribe("commander_report", on_commander_report))

            logger.info(f"[TradingWS] 已订阅 EventBus 事件: {symbol} (AI_DECISION, RISK_WARNING, STRATEGY_SIGNAL, POSITION_UPDATE, TELEMETRY_BATCH, market_data_update, mcp_call_start, mcp_call_complete, commander_report)")

        except Exception as e:
            logger.error(f"[TradingWS] EventBus 订阅失败: {e}")

    try:
        # 启动数据推送任务
        push_task = asyncio.create_task(
            _push_symbol_data(websocket, symbol, connection_id)
        )

        # 处理客户端消息
        while True:
            try:
                message = await websocket.receive_text()
                data = json.loads(message)
                msg_type = data.get("type", "")

                if msg_type == "ping":
                    await websocket.send_json({"type": "pong", "timestamp": int(time.time())})

                elif msg_type == "set_interval":
                    # 客户端设置K线周期
                    interval = data.get("interval", "1h")
                    # 通知推送任务更新周期
                    push_task.cancel()
                    push_task = asyncio.create_task(
                        _push_symbol_data(websocket, symbol, connection_id, interval)
                    )

                else:
                    logger.debug(f"[TradingWS] 未知消息类型: {msg_type}")

            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.error(f"[TradingWS] 处理消息错误: {e}")

    except Exception as e:
        logger.error(f"[TradingWS] WebSocket 错误: {e}")

    finally:
        push_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await push_task

        # 【新增】取消 EventBus 订阅
        for unsub in event_unsubscribers:
            try:
                unsub()
            except Exception as e:
                logger.debug(f"[TradingWS] 取消订阅失败: {e}")

        trading_ws_manager.disconnect(connection_id)
        logger.info(f"[TradingWS] 连接已清理: {connection_id}")


async def _push_symbol_data(
    websocket: WebSocket,
    symbol: str,
    connection_id: str,
    interval: str = "1h"
):
    """
    持续推送币种数据

    推送频率:
    - 价格: 每秒
    - K线: 根据周期 (1m每秒, 1h每分钟等)
    - 持仓: 每5秒
    """
    last_kline_time = 0
    last_position_time = 0

    # 推送初始数据
    await _send_initial_data(websocket, symbol)

    while True:
        try:
            now = time.time()

            # 每秒推送价格
            await _send_price_update(websocket, symbol)

            # 根据周期推送K线
            kline_interval = _get_interval_seconds(interval)
            if now - last_kline_time >= kline_interval:
                await _send_kline_update(websocket, symbol, interval)
                last_kline_time = now

            # 每5秒推送持仓
            if now - last_position_time >= 5:
                await _send_position_update(websocket, symbol)
                last_position_time = now

            await asyncio.sleep(1)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"[TradingWS] 推送数据错误: {e}")
            await asyncio.sleep(1)


async def _send_initial_data(websocket: WebSocket, symbol: str):
    """发送初始数据"""
    # 发送当前价格
    await _send_price_update(websocket, symbol)

    # 发送当前持仓
    await _send_position_update(websocket, symbol)

    # 发送最近交易信号
    await _send_recent_signals(websocket, symbol)


async def _send_price_update(websocket: WebSocket, symbol: str):
    """发送价格更新（真实行情）"""
    # 获取真实行情数据
    from core.btc_integration.market_data import get_market_data_provider
    provider = get_market_data_provider()
    price_data = await provider.get_price(symbol)

    if price_data:
        price_info = PriceInfo(
            symbol=price_data.symbol,
            price=price_data.price,
            change24h=price_data.change_24h,
            change24hPercent=price_data.change_24h_percent,
            high24h=price_data.high_24h,
            low24h=price_data.low_24h,
            volume24h=price_data.volume_24h,
            timestamp=price_data.timestamp
        )
    else:
        # 回退到模拟数据
        base_price = {"BTC": 67234.50, "ETH": 3456.78, "SOL": 145.67}.get(symbol, 100)
        price_info = PriceInfo(
            symbol=symbol,
            price=base_price,
            change24h=0,
            change24hPercent=0,
            high24h=base_price * 1.05,
            low24h=base_price * 0.95,
            volume24h=1234567890,
            timestamp=int(time.time())
        )

    await websocket.send_json({
        "type": "price_update",
        "symbol": symbol,
        "data": price_info.dict()
    })


async def _send_kline_update(websocket: WebSocket, symbol: str, interval: str):
    """发送K线更新"""
    cache_key = f"{symbol}_{interval}"

    # 生成新的K线数据
    if cache_key not in trading_store.klines:
        trading_store.klines[cache_key] = []

    klines = trading_store.klines[cache_key]

    # 生成新的K线
    base_price = {"BTC": 67234.50, "ETH": 3456.78, "SOL": 145.67}.get(symbol, 100)
    change = (hash(f"{symbol}{time.time()}") % 100 - 50) / 1000

    new_kline = KLineData(
        time=int(time.time()),
        open=round(base_price, 2),
        high=round(base_price * (1 + abs(change)), 2),
        low=round(base_price * (1 - abs(change)), 2),
        close=round(base_price * (1 + change), 2),
        volume=float(hash(f"{symbol}{time.time()}") % 1000000)
    )

    klines.append(new_kline)
    if len(klines) > 1000:
        klines.pop(0)

    await websocket.send_json({
        "type": "kline_update",
        "symbol": symbol,
        "interval": interval,
        "data": new_kline.dict()
    })


async def _send_position_update(websocket: WebSocket, symbol: str):
    """发送持仓更新"""
    if symbol in trading_store.positions:
        position = trading_store.positions[symbol]

        # 更新未实现盈亏
        base_price = {"BTC": 67234.50, "ETH": 3456.78, "SOL": 145.67}.get(symbol, 100)
        price_change = (hash(f"{symbol}{time.time()}") % 100 - 50) / 10
        current_price = base_price + price_change

        if position.side == "long":
            position.unrealizedPnl = (current_price - position.entryPrice) * position.quantity
            position.markPrice = current_price

        await websocket.send_json({
            "type": "position_update",
            "symbol": symbol,
            "data": position.dict()
        })


async def _send_recent_signals(websocket: WebSocket, symbol: str):
    """发送最近的交易信号"""
    # 模拟AI交易信号
    signals = [
        {
            "type": "trade_signal",
            "symbol": symbol,
            "signal": {
                "action": "buy",
                "price": 67234.50,
                "quantity": 0.015,
                "strategy": "Trend Following",
                "confidence": 0.87,
                "reason": "突破均线，趋势向上",
                "timestamp": int(time.time()) - 3600
            }
        },
        {
            "type": "trade_execution",
            "symbol": symbol,
            "trade": {
                "id": f"trade_{int(time.time())}",
                "action": "buy",
                "price": 67234.50,
                "quantity": 0.015,
                "total": 1008.52,
                "fee": 0.5,
                "timestamp": int(time.time()) - 3600,
                "pnl": None
            }
        }
    ]

    for signal in signals:
        await websocket.send_json(signal)


def _get_interval_seconds(interval: str) -> int:
    """获取K线周期对应的秒数"""
    intervals = {
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "1h": 3600,
        "4h": 14400,
        "1d": 86400
    }
    return intervals.get(interval, 3600)


# ═══════════════════════════════════════════════════════════════
# 外部调用接口
# ═══════════════════════════════════════════════════════════════

async def broadcast_trade_signal(symbol: str, signal: dict):
    """
    广播 AI 交易信号

    由 AI 策略模块调用，当产生交易信号时推送给所有订阅者

    Args:
        symbol: 币种代码
        signal: 交易信号数据
    """
    await trading_ws_manager.broadcast_to_symbol(symbol, {
        "type": "trade_signal",
        "symbol": symbol,
        "signal": signal
    })


async def broadcast_trade_execution(symbol: str, trade: dict):
    """
    广播交易执行通知

    当交易实际执行后调用

    Args:
        symbol: 币种代码
        trade: 交易执行数据
    """
    await trading_ws_manager.broadcast_to_symbol(symbol, {
        "type": "trade_execution",
        "symbol": symbol,
        "trade": trade
    })


async def broadcast_risk_alert(symbol: str | None, level: str, message: str, data: dict = None):
    """
    广播风险告警

    Args:
        symbol: 币种代码 (可选，全局告警时为null)
        level: 告警级别 (warning / critical)
        message: 告警消息
        data: 附加数据
    """
    alert = {
        "type": "risk_alert",
        "level": level,
        "message": message,
        "timestamp": int(time.time())
    }

    if symbol:
        alert["symbol"] = symbol
    if data:
        alert["data"] = data

    if symbol:
        await trading_ws_manager.broadcast_to_symbol(symbol, alert)
    else:
        # 广播给所有连接
        for sym in trading_store.symbols:
            await trading_ws_manager.broadcast_to_symbol(sym, alert)


# ═══════════════════════════════════════════════════════════════════════════════
# 【文件总结】
# ═══════════════════════════════════════════════════════════════════════════════
#
# 【文件角色】
# 本文件提供 BTC 交易系统的 WebSocket 实时数据推送功能。
# 包括价格更新、K线数据、AI交易信号、持仓变更等实时推送。
#
# 【在系统中的位置】
# - 位于: SiliconBase_V5/api/trading_ws.py
# - WebSocket 路径: /ws/trading/{symbol}
# - 上游调用: 前端页面通过 WebSocket 连接
# - 下游使用: AI策略模块调用广播接口推送信号
#
# 【关联文件】
# 1. api/trading_api.py - REST API 接口
# 2. api/cloud_api.py - FastAPI 主应用 (需要注册路由)
# 3. frontend/src/pages/TradingDashboardPage.tsx - 前端交易页面
#
# 【推送消息类型】
# - price_update: 价格更新 (1秒)
# - kline_update: K线更新 (根据周期)
# - trade_signal: AI交易信号 (实时)
# - trade_execution: 交易执行 (实时)
# - position_update: 持仓变更 (5秒)
# - risk_alert: 风险告警 (实时)
#
# ═══════════════════════════════════════════════════════════════════════════════
