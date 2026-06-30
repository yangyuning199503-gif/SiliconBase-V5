#!/usr/bin/env python3
"""
交易执行器抽象层
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
支持模拟盘和实盘交易，统一接口

特性:
- 模拟盘: K线真实，交易模拟
- 实盘: 真实交易执行
- 多交易所支持(OKX, Binance)
- 自动根据配置选择执行器

作者: SiliconBase Team
日期: 2026-04-09
"""

import asyncio
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.btc_integration.okx_client import get_okx_client
from core.logger import logger
from core.task.background_task_registry import BackgroundTaskRegistry


class OrderSide(str, Enum):
    """订单方向"""
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    """订单类型"""
    MARKET = "market"
    LIMIT = "limit"


class PositionSide(str, Enum):
    """持仓方向"""
    LONG = "long"
    SHORT = "short"
    NONE = "none"


@dataclass
class Order:
    """订单数据"""
    id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: float | None = None
    leverage: int = 1
    status: str = "pending"
    filled_qty: float = 0.0
    avg_price: float = 0.0
    pnl: float = 0.0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    # 【治理】链路追踪ID，贯穿决策→下单→监控→终态
    trace_id: str = ""
    # 交易所订单ID（接入真实API后填充）
    exchange_order_id: str | None = None
    # 错误信息（下单/查单失败时填充）
    error_message: str | None = None


@dataclass
class Position:
    """持仓数据"""
    symbol: str
    side: PositionSide
    quantity: float
    entry_price: float
    mark_price: float
    leverage: int = 1
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    margin: float = 0.0
    update_time: float = field(default_factory=time.time)


@dataclass
class Account:
    """账户数据"""
    total_equity: float = 0.0
    available_balance: float = 0.0
    margin_balance: float = 0.0
    unrealized_pnl: float = 0.0
    update_time: float = field(default_factory=time.time)


class TradeExecutor(ABC):
    """
    交易执行器抽象基类

    子类需要实现:
    - execute_order: 执行订单
    - close_position: 平仓
    - get_position: 获取持仓
    - get_account: 获取账户信息
    """

    def __init__(self, user_id: str, config: dict[str, Any]):
        self.user_id = user_id
        self.config = config
        self.is_simulation = config.get('mode', 'demo') == 'demo'
        self.exchange_type = config.get('exchange', 'okx')

        # 后台任务注册表（治理：消灭野任务）
        self._task_registry = BackgroundTaskRegistry(f"executor_{user_id}_{self.exchange_type}")
        self._running = True

        logger.info(
            f"[TradeExecutor] 初始化执行器: "
            f"user={user_id}, exchange={self.exchange_type}, "
            f"mode={'模拟盘' if self.is_simulation else '实盘'}"
        )

    @abstractmethod
    async def execute_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        order_type: OrderType = OrderType.MARKET,
        price: float | None = None,
        leverage: int = 1,
        trace_id: str = ""
    ) -> Order:
        """执行订单"""
        pass

    @abstractmethod
    async def close_position(
        self,
        symbol: str,
        quantity: float | None = None
    ) -> Order | None:
        """平仓，quantity为None时全平"""
        pass

    @abstractmethod
    async def get_position(self, symbol: str) -> Position | None:
        """获取持仓信息"""
        pass

    @abstractmethod
    async def get_account(self) -> Account:
        """获取账户信息"""
        pass

    @abstractmethod
    async def get_balance(self, currency: str = "USDT") -> float:
        """获取指定币种余额"""
        pass

    async def get_klines(
        self,
        symbol: str,
        interval: str = "1h",
        limit: int = 500
    ) -> list[dict]:
        """
        获取K线数据 - 模拟盘和实盘都使用真实数据

        子类可以覆盖此方法，但默认使用OKX公共API获取真实数据
        """
        try:
            # 使用公共API获取真实K线数据
            from core.btc_integration.okx_client import get_okx_client
            client = get_okx_client()
            klines = await client.get_klines(symbol, interval, limit)
            return klines
        except Exception as e:
            logger.error(f"[TradeExecutor] 获取K线失败: {e}")
            return []

    async def get_current_price(self, symbol: str) -> float:
        """获取当前价格"""
        try:
            # 统一使用 OKXMarketDataProvider 的缓存，避免与 TradingSubAgent 重复请求
            from core.btc_integration.market_data import get_market_data_provider
            provider = get_market_data_provider()
            price_data = await provider.get_price(symbol)
            return price_data.price if price_data else 0.0
        except Exception as e:
            err_str = str(e)
            if "getaddrinfo" in err_str or "Cannot connect to host" in err_str:
                logger.debug(f"[TradeExecutor] 获取价格失败(网络不可达): {e}")
            else:
                logger.error(f"[TradeExecutor] 获取价格失败: {e}")
            return 0.0

    def _generate_order_id(self) -> str:
        """生成订单ID"""
        return f"{self.exchange_type}_{int(time.time())}_{uuid.uuid4().hex[:8]}"


class SimulationExecutor(TradeExecutor):
    """
    模拟交易执行器

    - K线数据: 真实数据（从OKX获取）
    - 交易执行: 模拟，不调用真实API
    - 持仓/账户: 内存中模拟
    """

    def __init__(self, user_id: str, config: dict[str, Any]):
        super().__init__(user_id, config)

        # 模拟账户数据
        self.initial_balance = 10000.0  # 初始资金 10000 USDT
        self.balance = self.initial_balance
        self.positions: dict[str, Position] = {}
        self.orders: list[Order] = []
        self.trade_history: list[dict] = []

        logger.info(f"[SimulationExecutor] 模拟账户初始化: balance={self.balance} USDT")

    async def execute_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        order_type: OrderType = OrderType.MARKET,
        price: float | None = None,
        leverage: int = 1
    ) -> Order:
        """模拟执行订单"""

        # 获取当前价格
        current_price = price or await self.get_current_price(symbol)

        if current_price <= 0:
            raise ValueError(f"无法获取 {symbol} 当前价格")

        # 计算订单金额
        order_value = quantity * current_price / leverage

        # 检查余额
        if side == OrderSide.BUY and order_value > self.balance:
            raise ValueError(f"余额不足: 需要 {order_value:.2f} USDT, 可用 {self.balance:.2f} USDT")

        # 创建订单
        order = Order(
            id=self._generate_order_id(),
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            leverage=leverage,
            status="filled",
            filled_qty=quantity,
            avg_price=current_price
        )

        # 更新余额
        if side == OrderSide.BUY:
            self.balance -= order_value
        else:
            self.balance += order_value

        # 更新持仓
        await self._update_position(symbol, side, quantity, current_price, leverage)

        # 记录订单
        self.orders.append(order)

        logger.info(
            f"[SimulationExecutor] [user={self.user_id}] 模拟订单执行: "
            f"{symbol} {side.value} {quantity}@{current_price}, "
            f"剩余余额={self.balance:.2f} USDT"
        )

        return order

    async def _update_position(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        price: float,
        leverage: int
    ):
        """更新持仓"""
        pos = self.positions.get(symbol)

        if side == OrderSide.BUY:
            # 开多或加多
            if pos and pos.side == PositionSide.LONG:
                # 加仓
                total_qty = pos.quantity + quantity
                pos.entry_price = (pos.entry_price * pos.quantity + price * quantity) / total_qty
                pos.quantity = total_qty
            else:
                # 新仓或反手
                if pos and pos.side == PositionSide.SHORT:
                    # 先平空仓
                    pnl = (pos.entry_price - price) * pos.quantity
                    self.balance += pnl
                    logger.info(f"[SimulationExecutor] 平空仓盈利: {pnl:.2f} USDT")

                # 开多仓
                self.positions[symbol] = Position(
                    symbol=symbol,
                    side=PositionSide.LONG,
                    quantity=quantity,
                    entry_price=price,
                    mark_price=price,
                    leverage=leverage
                )
        else:
            # 开空或加空
            if pos and pos.side == PositionSide.SHORT:
                # 加仓
                total_qty = pos.quantity + quantity
                pos.entry_price = (pos.entry_price * pos.quantity + price * quantity) / total_qty
                pos.quantity = total_qty
            else:
                # 新仓或反手
                if pos and pos.side == PositionSide.LONG:
                    # 先平多仓
                    pnl = (price - pos.entry_price) * pos.quantity
                    self.balance += pnl
                    logger.info(f"[SimulationExecutor] 平多仓盈利: {pnl:.2f} USDT")

                # 开空仓
                self.positions[symbol] = Position(
                    symbol=symbol,
                    side=PositionSide.SHORT,
                    quantity=quantity,
                    entry_price=price,
                    mark_price=price,
                    leverage=leverage
                )

        # 更新未实现盈亏
        await self._update_unrealized_pnl(symbol)

    async def _update_unrealized_pnl(self, symbol: str):
        """更新未实现盈亏"""
        pos = self.positions.get(symbol)
        if not pos:
            return

        current_price = await self.get_current_price(symbol)
        pos.mark_price = current_price
        pos.update_time = time.time()

        if pos.side == PositionSide.LONG:
            pos.unrealized_pnl = (current_price - pos.entry_price) * pos.quantity
        else:
            pos.unrealized_pnl = (pos.entry_price - current_price) * pos.quantity

    async def close_position(
        self,
        symbol: str,
        quantity: float | None = None
    ) -> Order | None:
        """模拟平仓"""
        pos = self.positions.get(symbol)
        if not pos or pos.side == PositionSide.NONE:
            logger.warning(f"[SimulationExecutor] 无持仓可平: {symbol}")
            return None

        close_qty = quantity or pos.quantity
        current_price = await self.get_current_price(symbol)

        # 计算盈亏
        if pos.side == PositionSide.LONG:
            pnl = (current_price - pos.entry_price) * close_qty
            order_side = OrderSide.SELL
        else:
            pnl = (pos.entry_price - current_price) * close_qty
            order_side = OrderSide.BUY

        # 更新余额
        self.balance += pnl

        # 创建平仓订单
        order = Order(
            id=self._generate_order_id(),
            symbol=symbol,
            side=order_side,
            order_type=OrderType.MARKET,
            quantity=close_qty,
            status="filled",
            filled_qty=close_qty,
            avg_price=current_price,
            pnl=pnl
        )

        # 更新持仓
        if close_qty >= pos.quantity:
            del self.positions[symbol]
        else:
            pos.quantity -= close_qty

        self.orders.append(order)

        logger.info(
            f"[SimulationExecutor] [user={self.user_id}] 模拟平仓: "
            f"{symbol} {close_qty}@{current_price}, 盈亏={pnl:.2f} USDT"
        )

        return order

    async def get_position(self, symbol: str) -> Position | None:
        """获取模拟持仓"""
        pos = self.positions.get(symbol)
        if pos:
            await self._update_unrealized_pnl(symbol)
        return pos

    async def get_account(self) -> Account:
        """获取模拟账户信息"""
        total_unrealized = sum(
            pos.unrealized_pnl for pos in self.positions.values()
        )

        return Account(
            total_equity=self.balance + total_unrealized,
            available_balance=self.balance,
            margin_balance=self.balance * 0.8,  # 模拟保证金
            unrealized_pnl=total_unrealized,
            update_time=time.time()
        )

    async def get_balance(self, currency: str = "USDT") -> float:
        """获取模拟余额"""
        return self.balance

    async def get_positions(self) -> list[dict[str, Any]]:
        """获取所有模拟持仓列表（含最新未实现盈亏）"""
        positions = []
        for symbol, pos in list(self.positions.items()):
            await self._update_unrealized_pnl(symbol)
            positions.append({
                "symbol": pos.symbol,
                "side": pos.side.value,
                "quantity": pos.quantity,
                "entry_price": pos.entry_price,
                "mark_price": pos.mark_price,
                "unrealized_pnl": pos.unrealized_pnl,
                "realized_pnl": pos.realized_pnl,
                "leverage": pos.leverage,
            })
        return positions

    def get_trade_summary(self) -> dict:
        """获取交易摘要（用于展示）"""
        realized_pnl = sum(o.pnl for o in self.orders if o.pnl != 0)
        return {
            "initial_balance": self.initial_balance,
            "current_balance": self.balance,
            "total_pnl": self.balance - self.initial_balance,
            "realized_pnl": realized_pnl,
            "unrealized_pnl": sum(p.unrealized_pnl for p in self.positions.values()),
            "total_trades": len(self.orders),
            "open_positions": len(self.positions)
        }


class OKXExecutor(TradeExecutor):
    """
    OKX实盘交易执行器

    - 使用OKX API执行真实交易
    - 需要配置API Key
    """

    def __init__(self, user_id: str, config: dict[str, Any]):
        super().__init__(user_id, config)

        self.api_key = config.get('api_key', '')
        self.api_secret = config.get('api_secret', '')
        self.passphrase = config.get('passphrase', '')
        self.testnet = config.get('testnet', True)

        # 初始化OKX客户端
        self._init_client()

        # 内部订单缓存（key=内部order_id，用于查单时映射到交易所订单号）
        self._orders: dict[str, Order] = {}

    def _init_client(self):
        """初始化OKX客户端"""
        try:
            self._okx_client = get_okx_client()
            if self._okx_client.credentials is None:
                logger.warning("[OKXExecutor] 未配置 OKX 凭证，实盘交易不可用")
            else:
                logger.info("[OKXExecutor] OKX 客户端初始化完成，交易功能可用")
        except Exception as e:
            logger.error(f"[OKXExecutor] 初始化失败: {e}", exc_info=True)
            self._okx_client = None

    async def execute_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        order_type: OrderType = OrderType.MARKET,
        price: float | None = None,
        leverage: int = 1,
        trace_id: str = ""
    ) -> Order:
        """执行真实订单"""
        logger.info(
            f"[OKXExecutor] [user={self.user_id}] [{trace_id}] 执行真实订单: "
            f"{symbol} {side.value} {quantity}"
        )

        # 参数映射：内部枚举 → OKX 字符串
        side_str = "buy" if side == OrderSide.BUY else "sell"

        # 创建内部订单对象
        order = Order(
            id=self._generate_order_id(),
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            leverage=leverage,
            status="submitted",
            filled_qty=0.0,
            trace_id=trace_id
        )

        # 缓存内部订单，供后续查询使用
        self._orders[order.id] = order

        try:
            if self._okx_client is None:
                raise RuntimeError("OKX 客户端未初始化")

            # 调用 OKX API 执行真实下单
            result = await self._okx_client.create_order(
                symbol=symbol,
                side=side_str,
                qty=str(quantity),
                td_mode="cross",
                ord_type="market",
            )

            if result.get("code") == "0" and result.get("data"):
                # 下单成功，提取交易所订单号
                okx_data = result["data"][0]
                order.exchange_order_id = okx_data.get("ordId")
                order.status = "submitted"
                logger.info(
                    f"[OKXExecutor] [{trace_id}] 下单成功 | "
                    f"order_id={order.id} | exchange_order_id={order.exchange_order_id}"
                )
            else:
                # 下单失败
                order.status = "rejected"
                order.error_message = result.get("msg", "unknown error")
                logger.error(
                    f"[OKXExecutor] [{trace_id}] 下单失败 | "
                    f"order_id={order.id} | code={result.get('code')} | msg={order.error_message}"
                )
        except Exception as e:
            order.status = "rejected"
            order.error_message = str(e)
            logger.error(
                f"[OKXExecutor] [{trace_id}] 下单异常 | "
                f"order_id={order.id} | error={e}",
                exc_info=True,
            )

        # 【治理】通过注册表注册订单监控任务，而非裸 create_task
        await self._task_registry.register(
            f"monitor_{order.id}",
            self._monitor_order(order)
        )

        return order

    async def _query_okx_order(self, order_id: str) -> Order | None:
        """
        查询 OKX API 订单状态
        """
        # 获取内部订单对象，以取得交易所订单号和原始symbol
        internal_order = self._orders.get(order_id)
        if not internal_order:
            logger.warning(f"[OKXExecutor] 未找到内部订单记录: order_id={order_id}")
            return None

        if not internal_order.exchange_order_id:
            logger.warning(
                f"[OKXExecutor] 订单无交易所订单号，跳过查询: order_id={order_id}"
            )
            return internal_order  # 返回原对象，不更新状态

        try:
            result = await self._okx_client.query_order(
                symbol=internal_order.symbol,
                ord_id=internal_order.exchange_order_id,
            )

            if result.get("code") == "0" and result.get("data"):
                okx_data = result["data"][0]
                state = okx_data.get("state", "unknown")
                acc_fill_sz = float(okx_data.get("accFillSz", 0) or 0)
                avg_px = float(okx_data.get("avgPx", 0) or 0)

                return Order(
                    id=internal_order.id,
                    symbol=internal_order.symbol,
                    side=internal_order.side,
                    order_type=internal_order.order_type,
                    quantity=internal_order.quantity,
                    price=internal_order.price,
                    leverage=internal_order.leverage,
                    status=self._map_okx_status(state),
                    filled_qty=acc_fill_sz,
                    avg_price=avg_px,
                    pnl=internal_order.pnl,
                    created_at=internal_order.created_at,
                    updated_at=time.time(),
                    trace_id=internal_order.trace_id,
                    exchange_order_id=internal_order.exchange_order_id,
                )
            else:
                logger.warning(
                    f"[OKXExecutor] 查询订单失败: order_id={order_id} | "
                    f"code={result.get('code')} | msg={result.get('msg')}"
                )
                return internal_order  # 返回原对象，不更新状态

        except Exception as e:
            logger.error(
                f"[OKXExecutor] 查询订单异常: order_id={order_id} | error={e}",
                exc_info=True,
            )
            return internal_order  # 返回原对象，不更新状态

    def _map_okx_status(self, okx_state: str) -> str:
        """映射 OKX 订单状态到内部状态"""
        mapping = {
            "live": "submitted",      # 未成交
            "partially_filled": "partial",  # 部分成交
            "filled": "filled",       # 完全成交
            "canceled": "canceled",   # 已取消
            "cancelled": "canceled",  # 已取消（拼写变体）
        }
        return mapping.get(okx_state, "unknown")

    async def _monitor_order(
        self,
        order: Order,
        max_attempts: int = 60,
        interval: float = 1.0
    ):
        """
        监控订单成交状态（完整生命周期）

        【治理】此方法是交易安全核心，必须实现完整的订单状态追踪。
        禁止直接假设全部成交。

        Args:
            order: 要监控的订单
            max_attempts: 最大轮询次数（默认60次 ≈ 60秒）
            interval: 轮询间隔（秒）
        """
        start_time = time.time()
        last_status = order.status
        trace_id = order.trace_id or f"mon_{order.id}"

        logger.info(
            f"[OKXExecutor] [{trace_id}] 开始监控订单 | "
            f"order_id={order.id} | symbol={order.symbol} | "
            f"side={order.side.value} | qty={order.quantity}"
        )

        for attempt in range(max_attempts):
            if not self._running:
                logger.warning(
                    f"[OKXExecutor] [{trace_id}] 执行器已停止，终止订单监控"
                )
                return

            try:
                okx_order = await self._query_okx_order(order.id)

                if okx_order and okx_order.status != last_status:
                    elapsed = time.time() - start_time
                    logger.info(
                        f"[OKXExecutor] [{trace_id}] 订单状态变更 | "
                        f"order_id={order.id} | {last_status} -> {okx_order.status} | "
                        f"filled={okx_order.filled_qty}/{okx_order.quantity} | "
                        f"avg_price={okx_order.avg_price:.2f} | "
                        f"elapsed={elapsed:.1f}s"
                    )
                    last_status = okx_order.status
                    order.status = okx_order.status
                    order.filled_qty = okx_order.filled_qty
                    order.avg_price = okx_order.avg_price
                    order.updated_at = time.time()

                # 终态判断
                if okx_order and okx_order.status in ("filled", "canceled", "rejected"):
                    total_elapsed = time.time() - start_time
                    logger.info(
                        f"[OKXExecutor] [{trace_id}] 订单终态 | "
                        f"order_id={order.id} | status={okx_order.status} | "
                        f"final_filled={okx_order.filled_qty}/{okx_order.quantity} | "
                        f"final_avg_price={okx_order.avg_price:.2f} | "
                        f"total_elapsed={total_elapsed:.1f}s"
                    )
                    return

            except Exception as e:
                logger.error(
                    f"[OKXExecutor] [{trace_id}] 订单监控异常 | "
                    f"order_id={order.id} | attempt={attempt}/{max_attempts} | error={e}"
                )

            await asyncio.sleep(interval)

        # 超时
        logger.warning(
            f"[OKXExecutor] [{trace_id}] 订单监控超时 | "
            f"order_id={order.id} | attempts={max_attempts} | "
            f"last_status={order.status}"
        )
        order.status = "timeout"

    async def close_position(
        self,
        symbol: str,
        quantity: float | None = None
    ) -> Order | None:
        """真实平仓"""
        logger.info(f"[OKXExecutor] [user={self.user_id}] 执行真实平仓: {symbol}")

        # TODO: 调用OKX API平仓
        # 暂时返回模拟订单
        pos = await self.get_position(symbol)
        if not pos:
            return None

        close_qty = quantity or pos.quantity
        await self.get_current_price(symbol)

        order_side = OrderSide.SELL if pos.side == PositionSide.LONG else OrderSide.BUY

        order = Order(
            id=self._generate_order_id(),
            symbol=symbol,
            side=order_side,
            order_type=OrderType.MARKET,
            quantity=close_qty,
            status="submitted"
        )

        # 【治理】通过注册表注册订单监控任务
        await self._task_registry.register(
            f"monitor_{order.id}",
            self._monitor_order(order)
        )

        return order

    async def get_position(self, symbol: str) -> Position | None:
        """获取真实持仓"""
        # TODO: 调用OKX API获取持仓
        logger.debug(f"[OKXExecutor] 获取持仓: {symbol}")
        return None

    async def get_account(self) -> Account:
        """获取真实账户信息"""
        # TODO: 调用OKX API获取账户
        return Account()

    async def get_balance(self, currency: str = "USDT") -> float:
        """获取真实余额"""
        # TODO: 调用OKX API获取余额
        return 0.0


class BinanceExecutor(TradeExecutor):
    """
    币安实盘交易执行器

    - 使用币安API执行真实交易
    - 需要配置API Key
    """

    def __init__(self, user_id: str, config: dict[str, Any]):
        super().__init__(user_id, config)

        self.api_key = config.get('api_key', '')
        self.api_secret = config.get('api_secret', '')
        self.testnet = config.get('testnet', True)

        logger.info(f"[BinanceExecutor] 初始化币安客户端: testnet={self.testnet}")

    async def execute_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        order_type: OrderType = OrderType.MARKET,
        price: float | None = None,
        leverage: int = 1,
        trace_id: str = ""
    ) -> Order:
        """执行真实订单"""
        logger.info(
            f"[BinanceExecutor] [user={self.user_id}] [{trace_id}] 执行真实订单: "
            f"{symbol} {side.value} {quantity}"
        )

        # TODO: 调用币安API
        await self.get_current_price(symbol)

        return Order(
            id=self._generate_order_id(),
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            status="submitted",
            trace_id=trace_id
        )

    async def close_position(
        self,
        symbol: str,
        quantity: float | None = None
    ) -> Order | None:
        """真实平仓"""
        logger.info(f"[BinanceExecutor] [user={self.user_id}] 执行真实平仓: {symbol}")
        return None

    async def get_position(self, symbol: str) -> Position | None:
        """获取真实持仓"""
        return None

    async def get_account(self) -> Account:
        """获取真实账户信息"""
        return Account()

    async def get_balance(self, currency: str = "USDT") -> float:
        """获取真实余额"""
        return 0.0


# ═══════════════════════════════════════════════════════════════
# 执行器工厂
# ═══════════════════════════════════════════════════════════════

def create_executor(user_id: str, config: dict[str, Any]) -> TradeExecutor:
    """
    创建交易执行器

    根据配置自动选择合适的执行器:
    - mode=demo -> SimulationExecutor
    - mode=live, exchange=okx -> OKXExecutor
    - mode=live, exchange=binance -> BinanceExecutor
    """
    mode = config.get('mode', 'demo')
    exchange = config.get('exchange', 'okx')

    if mode == 'demo':
        return SimulationExecutor(user_id, config)

    # 实盘模式
    if exchange == 'okx':
        return OKXExecutor(user_id, config)
    elif exchange == 'binance':
        return BinanceExecutor(user_id, config)
    else:
        raise ValueError(f"不支持的交易所: {exchange}")


def create_default_executor(user_id: str) -> TradeExecutor:
    """
    创建默认模拟执行器

    当用户没有配置时，自动创建模拟执行器
    """
    default_config = {
        'mode': 'demo',
        'exchange': 'okx',
        'name': '默认模拟账户'
    }
    return SimulationExecutor(user_id, default_config)
