#!/usr/bin/env python3
"""
BTC 交易 RESTful API
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
提供交易相关的 HTTP API 接口

功能:
- 币种管理 (获取/添加/删除)
- 市场数据查询 (价格/K线/深度)
- 交易历史查询
- 持仓和账户信息
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from core.logger import logger

# 创建路由
router = APIRouter(prefix="/trading", tags=["trading"])


# ═══════════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════════

class TradingSymbol(BaseModel):
    """交易币种模型"""
    symbol: str
    base: str
    quote: str = "USDT"
    name: str
    isCustom: bool = False
    enabled: bool = True
    icon: str | None = None

    class Config:
        json_schema_extra = {
            "example": {
                "symbol": "BTC",
                "base": "BTC",
                "quote": "USDT",
                "name": "Bitcoin",
                "isCustom": False,
                "enabled": True
            }
        }


class KLineData(BaseModel):
    """K线数据模型"""
    time: int  # Unix timestamp in seconds
    open: float
    high: float
    low: float
    close: float
    volume: float


class TradeRecord(BaseModel):
    """交易记录模型"""
    id: str
    symbol: str
    action: str  # buy / sell
    price: float
    quantity: float
    total: float
    fee: float
    timestamp: int
    source: str  # ai / manual
    strategy: str | None = None
    pnl: float | None = None


class PositionInfo(BaseModel):
    """持仓信息模型"""
    symbol: str
    side: str  # long / short / none
    quantity: float
    entryPrice: float
    markPrice: float
    unrealizedPnl: float
    realizedPnl: float
    margin: float
    leverage: int
    updateTime: int


class AccountInfo(BaseModel):
    """账户信息模型"""
    totalEquity: float
    availableBalance: float
    marginBalance: float
    unrealizedPnl: float
    updateTime: int


class ClosePositionRequest(BaseModel):
    """平仓请求模型"""
    symbol: str
    side: str = "long"  # long / short
    quantity: float | None = None


class PriceInfo(BaseModel):
    """价格信息模型"""
    symbol: str
    price: float
    change24h: float
    change24hPercent: float
    high24h: float
    low24h: float
    volume24h: float
    timestamp: int


# ═══════════════════════════════════════════════════════════════
# 内存存储 (后续可迁移到数据库)
# ═══════════════════════════════════════════════════════════════

class TradingDataStore:
    """交易数据存储"""

    def __init__(self):
        import asyncio
        # 线程安全锁
        self._lock = asyncio.Lock()

        # 默认币种列表
        self.symbols: dict[str, TradingSymbol] = {
            "BTC": TradingSymbol(
                symbol="BTC", base="BTC", quote="USDT",
                name="Bitcoin", isCustom=False, enabled=True
            ),
            "ETH": TradingSymbol(
                symbol="ETH", base="ETH", quote="USDT",
                name="Ethereum", isCustom=False, enabled=True
            ),
            "SOL": TradingSymbol(
                symbol="SOL", base="SOL", quote="USDT",
                name="Solana", isCustom=False, enabled=True
            ),
        }

        # 模拟K线数据缓存
        self.klines: dict[str, list[KLineData]] = {}

        # 模拟交易历史
        self.trades: list[TradeRecord] = []

        # 模拟持仓
        self.positions: dict[str, PositionInfo] = {}

        # 当前价格
        self.prices: dict[str, PriceInfo] = {}

    async def add_symbol(self, symbol: str, name: str | None = None) -> TradingSymbol:
        """添加币种"""
        async with self._lock:
            if symbol in self.symbols:
                raise ValueError(f"币种 {symbol} 已存在")

            new_symbol = TradingSymbol(
                symbol=symbol,
                base=symbol,
                quote="USDT",
                name=name or symbol,
                isCustom=True,
                enabled=True
            )
            self.symbols[symbol] = new_symbol
            return new_symbol

    async def remove_symbol(self, symbol: str) -> bool:
        """删除币种"""
        async with self._lock:
            if symbol in self.symbols:
                del self.symbols[symbol]
                return True
            return False

    def get_symbol(self, symbol: str) -> TradingSymbol | None:
        """获取币种信息"""
        return self.symbols.get(symbol)

    def get_all_symbols(self) -> list[TradingSymbol]:
        """获取所有币种"""
        return list(self.symbols.values())


# 全局数据存储实例
trading_store = TradingDataStore()


# ═══════════════════════════════════════════════════════════════
# API 路由
# ═══════════════════════════════════════════════════════════════

@router.get("/symbols", response_model=list[TradingSymbol])
async def get_symbols():
    """
    获取所有支持的币种列表

    Returns:
        List[TradingSymbol]: 币种列表
    """
    return trading_store.get_all_symbols()


@router.post("/symbols", response_model=TradingSymbol)
async def add_symbol(symbol: str, name: str | None = None):
    """
    添加自定义币种

    Args:
        symbol: 币种代码 (如 DOGE, SHIB)
        name: 币种名称 (可选)

    Returns:
        TradingSymbol: 新添加的币种信息
    """
    try:
        new_symbol = await trading_store.add_symbol(symbol.upper(), name)
        logger.info(f"[TradingAPI] 添加币种: {symbol}")
        return new_symbol
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/symbols/{symbol}")
async def remove_symbol(symbol: str):
    """
    删除币种

    Args:
        symbol: 币种代码

    Returns:
        dict: 操作结果
    """
    symbol = symbol.upper()
    success = await trading_store.remove_symbol(symbol)
    if success:
        logger.info(f"[TradingAPI] 删除币种: {symbol}")
        return {"success": True, "message": f"币种 {symbol} 已删除"}
    else:
        raise HTTPException(status_code=404, detail=f"币种 {symbol} 不存在")


@router.get("/price/{symbol}", response_model=PriceInfo)
async def get_price(symbol: str):
    """
    获取币种实时价格（接入OKX真实行情）

    Args:
        symbol: 币种代码

    Returns:
        PriceInfo: 价格信息
    """
    symbol = symbol.upper()

    # 检查币种是否存在
    if symbol not in trading_store.symbols:
        raise HTTPException(status_code=404, detail=f"币种 {symbol} 不存在")

    # 获取真实行情数据
    from core.btc_integration.market_data import get_market_data_provider
    provider = get_market_data_provider()
    price_data = await provider.get_price(symbol)

    if price_data:
        return PriceInfo(
            symbol=price_data.symbol,
            price=price_data.price,
            change24h=price_data.change_24h,
            change24hPercent=price_data.change_24h_percent,
            high24h=price_data.high_24h,
            low24h=price_data.low_24h,
            volume24h=price_data.volume_24h,
            timestamp=price_data.timestamp
        )

    # 回退到模拟数据
    return PriceInfo(
        symbol=symbol,
        price=67234.50,
        change24h=1234.50,
        change24hPercent=1.87,
        high24h=68123.00,
        low24h=65432.00,
        volume24h=1234567890,
        timestamp=int(datetime.now().timestamp())
    )


@router.get("/klines/{symbol}", response_model=list[KLineData])
async def get_klines(
    symbol: str,
    interval: str = Query("1h", description="K线周期: 1m, 5m, 15m, 1h, 4h, 1d"),
    limit: int = Query(100, ge=1, le=1000, description="返回条数")
):
    """
    获取K线历史数据（接入OKX真实行情）

    Args:
        symbol: 币种代码
        interval: K线周期
        limit: 返回条数

    Returns:
        List[KLineData]: K线数据列表
    """
    symbol = symbol.upper()

    # 检查币种是否存在，不存在则返回空数组（避免前端报错）
    if symbol not in trading_store.symbols:
        logger.warning(f"[TradingAPI] 币种 {symbol} 不存在，返回空K线数据")
        return []

    # 获取真实K线数据
    from core.btc_integration.market_data import get_market_data_provider
    provider = get_market_data_provider()
    klines_data = await provider.get_klines(symbol, interval, limit)

    # 如果 OKX provider 返回空，尝试调用 V2 引擎作为 fallback
    if not klines_data:
        try:
            from core.btc_integration.api_bridge import TradingAPIBridge
            bridge = TradingAPIBridge()
            v2_result = await bridge.get_klines_with_ai(symbol, interval, limit)
            v2_klines = v2_result.get("klines", [])
            result = []
            for k in v2_klines:
                result.append(KLineData(
                    time=k["time"],
                    open=k["open"],
                    high=k["high"],
                    low=k["low"],
                    close=k["close"],
                    volume=k["volume"]
                ))
            logger.info(f"[TradingAPI] 通过 V2 引擎获取K线: {symbol}")
            return result
        except Exception as e:
            logger.warning(f"[TradingAPI] V2 引擎获取K线失败: {e}")

    # 转换为API模型
    result = []
    for k in klines_data:
        result.append(KLineData(
            time=k.time,
            open=k.open,
            high=k.high,
            low=k.low,
            close=k.close,
            volume=k.volume
        ))

    return result


@router.get("/trades/{symbol}", response_model=list[TradeRecord])
async def get_trades(
    symbol: str,
    limit: int = Query(50, ge=1, le=200)
):
    """
    获取交易历史

    Args:
        symbol: 币种代码
        limit: 返回条数

    Returns:
        List[TradeRecord]: 交易记录列表
    """
    symbol = symbol.upper()

    # 筛选指定币种的交易记录
    symbol_trades = [
        t for t in trading_store.trades
        if t.symbol == symbol
    ]

    # 按时间倒序排列，返回最新N条
    return sorted(symbol_trades, key=lambda x: x.timestamp, reverse=True)[:limit]


@router.get("/position/{symbol}", response_model=PositionInfo)
async def get_position(symbol: str):
    """
    获取持仓信息

    Args:
        symbol: 币种代码

    Returns:
        PositionInfo: 持仓信息
    """
    symbol = symbol.upper()

    # 如果存在持仓，返回持仓信息
    if symbol in trading_store.positions:
        return trading_store.positions[symbol]

    # 返回空仓
    return PositionInfo(
        symbol=symbol,
        side="none",
        quantity=0,
        entryPrice=0,
        markPrice=0,
        unrealizedPnl=0,
        realizedPnl=0,
        margin=0,
        leverage=1,
        updateTime=int(datetime.now().timestamp())
    )


@router.get("/account", response_model=AccountInfo)
async def get_account():
    """
    获取账户信息

    Returns:
        AccountInfo: 账户信息
    """
    # 计算总权益和盈亏
    total_equity = 10000.0
    unrealized_pnl = 0.0

    for pos in trading_store.positions.values():
        total_equity += pos.unrealizedPnl
        unrealized_pnl += pos.unrealizedPnl

    return AccountInfo(
        totalEquity=total_equity,
        availableBalance=8000.0,
        marginBalance=2000.0,
        unrealizedPnl=unrealized_pnl,
        updateTime=int(datetime.now().timestamp())
    )


@router.post("/position/close")
async def close_position(request: ClosePositionRequest):
    """
    平仓指定币种的持仓

    Args:
        request: 平仓请求，包含币种、方向和可选数量

    Returns:
        dict: 操作结果 {success, message, data}
    """
    symbol = request.symbol.upper()

    try:
        # 尝试使用 TradeExecutor 执行真实平仓
        from core.btc_integration.trade_executor import create_default_executor
        executor = create_default_executor("anonymous")
        order = await executor.close_position(symbol=symbol, quantity=request.quantity)

        # 更新本地持仓状态
        if symbol in trading_store.positions:
            del trading_store.positions[symbol]

        logger.info(f"[TradingAPI] 平仓成功: {symbol}")
        return {
            "success": True,
            "message": f"平仓成功: {symbol}",
            "data": {"order_id": order.id if order else None, "symbol": symbol}
        }
    except ImportError:
        # TradeExecutor 不可用，回退到内存操作
        if symbol in trading_store.positions:
            del trading_store.positions[symbol]
        logger.info(f"[TradingAPI] 模拟平仓成功: {symbol}")
        return {
            "success": True,
            "message": f"模拟平仓成功: {symbol}",
            "data": None
        }
    except Exception as e:
        logger.error(f"[TradingAPI] 平仓失败: {e}")
        return {"success": False, "message": f"平仓失败: {str(e)}"}


# ═══════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════

def generate_mock_klines(symbol: str, interval: str, limit: int) -> list[KLineData]:
    """生成模拟K线数据"""
    klines = []
    now = datetime.now()

    # 根据周期确定时间间隔
    interval_minutes = {
        "1m": 1, "5m": 5, "15m": 15,
        "1h": 60, "4h": 240, "1d": 1440
    }.get(interval, 60)

    # 基础价格
    base_price = {"BTC": 67234, "ETH": 3456, "SOL": 145}.get(symbol, 100)

    # 生成历史K线
    price = base_price
    for i in range(limit, 0, -1):
        time_point = now - timedelta(minutes=interval_minutes * i)

        # 随机价格波动
        change = (hash(f"{symbol}{i}") % 100 - 50) / 1000
        open_price = price
        close_price = price * (1 + change)
        high_price = max(open_price, close_price) * (1 + abs(hash(f"{symbol}{i}h") % 100) / 10000)
        low_price = min(open_price, close_price) * (1 - abs(hash(f"{symbol}{i}l") % 100) / 10000)
        volume = abs(hash(f"{symbol}{i}v") % 1000000)

        klines.append(KLineData(
            time=int(time_point.timestamp()),
            open=round(open_price, 2),
            high=round(high_price, 2),
            low=round(low_price, 2),
            close=round(close_price, 2),
            volume=float(volume)
        ))

        price = close_price

    return klines


# ═══════════════════════════════════════════════════════════════
# 初始化一些模拟数据
# ═══════════════════════════════════════════════════════════════

def init_mock_data():
    """初始化模拟数据"""
    # 添加一些模拟交易记录
    now = int(datetime.now().timestamp())
    trading_store.trades = [
        TradeRecord(
            id="trade_001",
            symbol="BTC",
            action="buy",
            price=66234.50,
            quantity=0.015,
            total=993.52,
            fee=0.5,
            timestamp=now - 3600,
            source="ai",
            strategy="Trend Following"
        ),
        TradeRecord(
            id="trade_002",
            symbol="BTC",
            action="sell",
            price=67234.50,
            quantity=0.015,
            total=1008.52,
            fee=0.5,
            timestamp=now - 1800,
            source="ai",
            strategy="Trend Following",
            pnl=15.0
        ),
    ]

    # 添加模拟持仓
    trading_store.positions["BTC"] = PositionInfo(
        symbol="BTC",
        side="long",
        quantity=0.015,
        entryPrice=67234.50,
        markPrice=67345.20,
        unrealizedPnl=12.34,
        realizedPnl=15.0,
        margin=200.0,
        leverage=5,
        updateTime=now
    )


# 初始化
init_mock_data()


# ═══════════════════════════════════════════════════════════════════════════════
# 【文件总结】
# ═══════════════════════════════════════════════════════════════════════════════
#
# 【文件角色】
# 本文件提供 BTC 交易系统的 RESTful API 接口。
# 包括币种管理、市场数据查询、交易历史、持仓和账户信息等功能。
#
# 【在系统中的位置】
# - 位于: SiliconBase_V5/api/trading_api.py
# - 路由前缀: /api/trading
# - 上游调用: 前端页面通过 HTTP 请求调用
# - 下游使用: OKX API (后续集成)
#
# 【关联文件】
# 1. api/trading_ws.py - WebSocket 实时数据推送
# 2. frontend/src/pages/TradingDashboardPage.tsx - 前端交易页面
# 3. frontend/src/stores/tradingStore.ts - 前端状态管理
#
# ═══════════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════
# V2 路由集成（已迁移至 cloud_api.py 直接挂载）
# ═══════════════════════════════════════════════════════════════
# 注：V2 路由（/trading-v2/*）现由 cloud_api.py 直接 app.include_router(..., prefix="/api")
# 挂载，以避免嵌套在 /trading 下产生 /trading/trading-v2/* 的丑陋路径。
# 此处保留注释作为迁移记录。
