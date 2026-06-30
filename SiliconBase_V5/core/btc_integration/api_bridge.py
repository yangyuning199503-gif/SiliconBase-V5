#!/usr/bin/env python3
"""
交易 API 桥接层
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
桥接 Smart Quant Engine V2 和前端 Trading Dashboard

职责:
1. 聚合 OKX 行情 + V2 AI 分析
2. 提供 REST API 供前端调用
3. 统一数据格式

作者: SiliconBase Team
日期: 2026-04-09
"""

import statistics
import time
from enum import Enum
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from core.logger import logger

# 用户认证
try:
    from api.cloud_api import get_current_user_optional
    AUTH_AVAILABLE = True
except ImportError:
    AUTH_AVAILABLE = False
    logger.warning("[APIBridge] 用户认证模块不可用")

# 交易所配置
try:
    from api.exchange_config_api import get_exchange_config_manager
    EXCHANGE_CONFIG_AVAILABLE = True
except ImportError:
    EXCHANGE_CONFIG_AVAILABLE = False
    logger.warning("[APIBridge] 交易所配置模块不可用")

# V2 引擎
try:
    from core.btc_integration.smart_quant_engine import MarketContext, create_smart_quant_engine
    from core.btc_integration.user_trading_manager import get_user_commander, get_user_trading_manager
    SMART_QUANT_AVAILABLE = True
except ImportError as e:
    SMART_QUANT_AVAILABLE = False
    logger.warning(f"[APIBridge] Smart Quant V2 不可用: {e}")

# OKX 客户端
try:
    from core.btc_integration.okx_client import get_okx_client
    OKX_AVAILABLE = True
except ImportError as e:
    OKX_AVAILABLE = False
    logger.warning(f"[APIBridge] OKX 客户端不可用: {e}")

# 智能集成
try:
    from core.btc_integration.intelligence_integration import get_trading_intelligence
    INTELLIGENCE_AVAILABLE = True
except ImportError as e:
    INTELLIGENCE_AVAILABLE = False
    logger.warning(f"[APIBridge] 智能集成不可用: {e}")


# ═══════════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════════

class TimeInterval(str, Enum):
    """时间周期枚举"""
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"


class KLineData(BaseModel):
    """K线数据模型"""
    time: int = Field(..., description="Unix时间戳(秒)")
    open: float = Field(..., description="开盘价")
    high: float = Field(..., description="最高价")
    low: float = Field(..., description="最低价")
    close: float = Field(..., description="收盘价")
    volume: float = Field(..., description="成交量")


class AISignalMarker(BaseModel):
    """AI信号标记"""
    time: int = Field(..., description="时间戳")
    price: float = Field(..., description="价格")
    type: str = Field(..., description="信号类型: buy, sell, hold")
    strategy: str = Field(..., description="策略名称")
    confidence: float = Field(..., description="置信度 0-1")
    reasoning: str = Field(..., description="推理简述")


class WorldModelPrediction(BaseModel):
    """World Model预测结果"""
    success_probability: float = Field(0.5, description="成功概率 0-1")
    expected_pnl: float = Field(0.0, description="预期收益")
    risk_score: float = Field(0.5, description="风险评分 0-1")
    confidence: float = Field(0.5, description="预测置信度")
    recommended_action: str = Field("monitor", description="建议行动")


class TradingStatus(BaseModel):
    """交易状态响应"""
    symbol: str = Field(..., description="币种")
    is_running: bool = Field(False, description="是否运行中")
    quant_mode: str = Field("none", description="量化模式: v2_smart/v1_simple/none")
    current_strategy: str | None = Field(None, description="当前策略")
    strategy_confidence: float = Field(0.0, description="策略置信度")
    position_side: str | None = Field(None, description="持仓方向: long/short/none")
    position_size: float = Field(0.0, description="持仓数量")
    entry_price: float = Field(0.0, description="入场价格")
    mark_price: float = Field(0.0, description="标记价格")
    unrealized_pnl: float = Field(0.0, description="未实现盈亏")
    realized_pnl: float = Field(0.0, description="已实现盈亏")
    last_signal: AISignalMarker | None = Field(None, description="最后信号")
    world_model_prediction: WorldModelPrediction | None = Field(None, description="World Model预测")
    update_time: int = Field(0, description="更新时间戳")


class KLinesWithAIResponse(BaseModel):
    """带AI分析的K线响应"""
    symbol: str = Field(..., description="币种")
    interval: str = Field(..., description="时间周期")
    klines: list[KLineData] = Field(..., description="K线数据")
    ai_markers: list[AISignalMarker] = Field([], description="AI信号标记")
    last_update: int = Field(..., description="最后更新时间")


class TradingSummary(BaseModel):
    """交易摘要"""
    total_symbols: int = Field(0, description="监控币种数")
    active_agents: int = Field(0, description="活跃代理数")
    total_positions: int = Field(0, description="持仓数量")
    total_unrealized_pnl: float = Field(0.0, description="总未实现盈亏")
    total_realized_pnl: float = Field(0.0, description="总已实现盈亏")
    quant_mode: str = Field("none", description="量化模式")
    intelligence_status: dict = Field({}, description="智能系统状态")


class AccountInfo(BaseModel):
    """账户信息"""
    user_id: str = Field(..., description="用户ID")
    mode: str = Field(..., description="交易模式: 模拟盘/实盘")
    exchange: str = Field(..., description="交易所")
    total_equity: float = Field(0.0, description="总权益")
    available_balance: float = Field(0.0, description="可用余额")
    unrealized_pnl: float = Field(0.0, description="未实现盈亏")
    position: dict | None = Field(None, description="当前持仓")
    # 模拟盘特有字段
    initial_balance: float | None = Field(None, description="初始资金")
    current_balance: float | None = Field(None, description="当前余额")
    total_pnl: float | None = Field(None, description="总盈亏")
    total_trades: int | None = Field(None, description="总交易次数")


class TradeRequest(BaseModel):
    """交易请求"""
    symbol: str = Field(..., description="交易对")
    side: str = Field(..., description="方向: buy/sell")
    quantity: float = Field(..., gt=0, description="数量")
    order_type: str = Field("market", description="订单类型: market/limit")
    price: float | None = Field(None, description="限价单价格")
    leverage: int = Field(1, ge=1, le=100, description="杠杆倍数")


class TradeResponse(BaseModel):
    """交易响应"""
    success: bool = Field(..., description="是否成功")
    order_id: str | None = Field(None, description="订单ID")
    symbol: str | None = Field(None, description="交易对")
    side: str | None = Field(None, description="方向")
    quantity: float | None = Field(None, description="数量")
    price: float | None = Field(None, description="成交价格")
    status: str | None = Field(None, description="订单状态")
    is_simulation: bool = Field(True, description="是否为模拟交易")
    error: str | None = Field(None, description="错误信息")


# ═══════════════════════════════════════════════════════════════
# API 桥接器
# ═══════════════════════════════════════════════════════════════

class TradingAPIBridge:
    """
    交易 API 桥接器

    单例模式实现，桥接 V2 引擎和前端。
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self.quant_engine: Any | None = None
        self.okx_client: Any | None = None
        self.intelligence: Any | None = None

        # 缓存
        self._klines_cache: dict[str, tuple[list, float]] = {}
        self._cache_ttl = 5  # 5秒缓存

        self._initialize()

    def _initialize(self):
        """延迟初始化"""
        if SMART_QUANT_AVAILABLE:
            try:
                self.quant_engine = create_smart_quant_engine()
                logger.info("[TradingAPIBridge] Smart Quant V2 已连接")
            except Exception as e:
                logger.error(f"[TradingAPIBridge] Smart Quant 初始化失败: {e}")

        if OKX_AVAILABLE:
            try:
                self.okx_client = get_okx_client()
                logger.info("[TradingAPIBridge] OKX 客户端已连接")
            except Exception as e:
                logger.error(f"[TradingAPIBridge] OKX 客户端初始化失败: {e}")

        if INTELLIGENCE_AVAILABLE:
            try:
                self.intelligence = get_trading_intelligence()
                logger.info("[TradingAPIBridge] 智能集成已连接")
            except Exception as e:
                logger.error(f"[TradingAPIBridge] 智能集成初始化失败: {e}")

        logger.info("[TradingAPIBridge] 初始化完成")

    async def get_klines_with_ai(
        self,
        symbol: str,
        interval: str = "1h",
        limit: int = 500
    ) -> dict[str, Any]:
        """
        获取 K 线数据 + AI 分析

        前端调用: GET /api/trading-v2/klines/{symbol}?interval=1h
        """
        # 检查缓存
        cache_key = f"{symbol}_{interval}"
        if cache_key in self._klines_cache:
            cached_data, cached_time = self._klines_cache[cache_key]
            if time.time() - cached_time < self._cache_ttl:
                logger.debug(f"[TradingAPIBridge] 返回缓存K线: {symbol}")
                return cached_data

        if not OKX_AVAILABLE or not self.okx_client:
            raise HTTPException(503, "OKX 客户端不可用")

        try:
            # 1. 从 OKX 获取真实 K 线
            klines_raw = await self.okx_client.get_klines(symbol, interval, limit)

            if not klines_raw or len(klines_raw) < 20:
                logger.warning(f"[TradingAPIBridge] K线数据不足: {symbol}")
                raise HTTPException(404, f"无法获取 {symbol} 的K线数据")

            # 2. V2 引擎分析
            ai_markers = []
            world_model_pred = None

            if self.quant_engine and SMART_QUANT_AVAILABLE and len(klines_raw) >= 20:
                try:
                    # 构建市场上下文
                    recent_klines = klines_raw[-100:]
                    ctx = self._build_market_context(recent_klines, symbol)

                    # 获取决策
                    decision = self.quant_engine.select_strategy(ctx)

                    # 生成信号标记
                    ai_markers = [{
                        "time": int(klines_raw[-1][0]),
                        "price": float(klines_raw[-1][4]),
                        "type": decision.action if hasattr(decision, 'action') else "hold",
                        "strategy": str(decision.strategy.value if hasattr(decision.strategy, 'value') else decision.strategy),
                        "confidence": float(decision.confidence) if hasattr(decision, 'confidence') else 0.5,
                        "reasoning": str(decision.reasoning[:200]) if hasattr(decision, 'reasoning') else ""
                    }]

                    # World Model 预测
                    if self.intelligence and INTELLIGENCE_AVAILABLE:
                        prediction = await self.intelligence.predict_trade_outcome(decision, ctx)
                        if prediction:
                            world_model_pred = {
                                "success_probability": prediction.success_probability,
                                "expected_pnl": prediction.expected_pnl,
                                "risk_score": prediction.risk_score,
                                "confidence": prediction.confidence,
                                "recommended_action": prediction.recommended_action
                            }

                except Exception as e:
                    logger.error(f"[TradingAPIBridge] AI分析失败: {e}")

            # 3. 格式化返回
            klines_formatted = [
                {
                    "time": int(k[0]),
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5])
                }
                for k in klines_raw
            ]

            result = {
                "symbol": symbol,
                "interval": interval,
                "klines": klines_formatted,
                "ai_markers": ai_markers,
                "world_model_prediction": world_model_pred,
                "last_update": int(time.time())
            }

            # 更新缓存
            self._klines_cache[cache_key] = (result, time.time())

            return result

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[TradingAPIBridge] 获取K线失败: {e}")
            raise HTTPException(500, f"获取K线数据失败: {str(e)}") from e

    async def get_trading_status(self, symbol: str, user_id: str | None = None) -> dict[str, Any]:
        """
        获取交易状态

        【用户隔离】每个用户看到自己有权限的交易状态

        前端调用: GET /api/trading-v2/status/{symbol}
        """
        # 记录用户访问
        if user_id:
            logger.info(f"[TradingAPIBridge] [user={user_id}] 获取交易状态: {symbol}")

        commander = None
        try:
            if SMART_QUANT_AVAILABLE:
                commander = await get_user_commander(user_id or "anonymous")
        except Exception as e:
            logger.warning(f"[TradingAPIBridge] 获取Commander失败: {e}")

        if not commander:
            return {
                "symbol": symbol,
                "is_running": False,
                "quant_mode": "none",
                "current_strategy": None,
                "strategy_confidence": 0.0,
                "position_side": None,
                "position_size": 0.0,
                "entry_price": 0.0,
                "mark_price": 0.0,
                "unrealized_pnl": 0.0,
                "realized_pnl": 0.0,
                "last_signal": None,
                "world_model_prediction": None,
                "update_time": int(time.time())
            }

        # 获取子代理状态
        subagent = commander.subagents.get(symbol)

        if not subagent:
            return {
                "symbol": symbol,
                "is_running": False,
                "quant_mode": commander.quant_mode,
                "current_strategy": None,
                "strategy_confidence": 0.0,
                "position_side": None,
                "position_size": 0.0,
                "entry_price": 0.0,
                "mark_price": 0.0,
                "unrealized_pnl": 0.0,
                "realized_pnl": 0.0,
                "last_signal": None,
                "world_model_prediction": None,
                "update_time": int(time.time())
            }

        # 格式化最后信号
        last_signal = None
        if subagent.decision_history:
            last = subagent.decision_history[-1]
            last_signal = {
                "time": int(time.time()),
                "price": subagent.current_position.get("mark_price", 0.0) if subagent.current_position else 0.0,
                "type": last.get("action", "hold"),
                "strategy": last.get("strategy", "unknown"),
                "confidence": last.get("confidence", 0.0),
                "reasoning": last.get("reasoning", "")[:200]
            }

        return {
            "symbol": symbol,
            "is_running": subagent._running and not subagent._paused,
            "quant_mode": commander.quant_mode,
            "current_strategy": subagent.decision_history[-1].get("strategy") if subagent.decision_history else None,
            "strategy_confidence": subagent.decision_history[-1].get("confidence", 0.0) if subagent.decision_history else 0.0,
            "position_side": subagent.current_position.get("side") if subagent.current_position else None,
            "position_size": subagent.current_position.get("size", 0.0) if subagent.current_position else 0.0,
            "entry_price": subagent.current_position.get("entry_price", 0.0) if subagent.current_position else 0.0,
            "mark_price": subagent.current_position.get("mark_price", 0.0) if subagent.current_position else 0.0,
            "unrealized_pnl": subagent.current_position.get("unrealized_pnl", 0.0) if subagent.current_position else 0.0,
            "realized_pnl": subagent.current_position.get("realized_pnl", 0.0) if subagent.current_position else 0.0,
            "last_signal": last_signal,
            "world_model_prediction": subagent.decision_history[-1].get("world_model_prediction") if subagent.decision_history else None,
            "update_time": int(time.time())
        }

    async def get_trading_summary(self, user_id: str | None = None) -> dict[str, Any]:
        """
        获取交易摘要

        【用户隔离】每个用户看到自己有权限的交易摘要

        前端调用: GET /api/trading-v2/summary
        """
        # 记录用户访问
        if user_id:
            logger.info(f"[TradingAPIBridge] [user={user_id}] 获取交易摘要")

        commander = None
        try:
            if SMART_QUANT_AVAILABLE:
                commander = await get_user_commander(user_id or "anonymous")
        except Exception as e:
            logger.warning(f"[TradingAPIBridge] 获取Commander失败: {e}")

        if not commander:
            return {
                "total_symbols": 0,
                "active_agents": 0,
                "total_positions": 0,
                "total_unrealized_pnl": 0.0,
                "total_realized_pnl": 0.0,
                "quant_mode": "none",
                "intelligence_status": self.intelligence.get_intelligence_status() if self.intelligence else {}
            }

        # 统计
        active_count = sum(1 for a in commander.subagents.values() if a._running)
        total_positions = sum(1 for a in commander.subagents.values() if a.current_position is not None)

        total_unrealized = sum(
            a.current_position.get("unrealized_pnl", 0.0)
            for a in commander.subagents.values()
            if a.current_position
        )

        total_realized = sum(
            a.current_position.get("realized_pnl", 0.0)
            for a in commander.subagents.values()
            if a.current_position
        )

        return {
            "total_symbols": len(commander.symbols),
            "active_agents": active_count,
            "total_positions": total_positions,
            "total_unrealized_pnl": total_unrealized,
            "total_realized_pnl": total_realized,
            "quant_mode": commander.quant_mode,
            "intelligence_status": self.intelligence.get_intelligence_status() if self.intelligence else {}
        }

    def _build_market_context(self, klines: list, symbol: str) -> Any:
        """从 K 线构建市场上下文"""
        if not klines:
            return None

        closes = [float(k[4]) for k in klines]
        highs = [float(k[2]) for k in klines]
        lows = [float(k[3]) for k in klines]

        # 计算趋势
        trend = "sideways"
        if len(closes) >= 20:
            if closes[-1] > closes[-20] * 1.05:
                trend = "up"
            elif closes[-1] < closes[-20] * 0.95:
                trend = "down"

        # 构建上下文
        if SMART_QUANT_AVAILABLE:
            return MarketContext(
                symbol=symbol,
                timestamp=time.time(),
                price=closes[-1],
                price_change_24h=(closes[-1] / closes[0] - 1) * 100 if closes else 0.0,
                volume_24h=0.0,
                rsi=50.0,
                macd_signal="neutral",
                trend=trend,
                trend_strength=abs(closes[-1] / closes[-20] - 1) if len(closes) >= 20 else 0.0,
                support_levels=[min(lows[-20:])] if lows else [],
                resistance_levels=[max(highs[-20:])] if highs else [],
                recent_news=[],
                fear_greed_index=50,
                funding_rate=0.0,
                open_interest_change=0.0,
                social_sentiment="neutral",
                exchange_inflow=0.0,
                exchange_outflow=0.0,
                whale_movement="neutral",
                network_activity="normal",
                btc_dominance=0.5,
                eth_btc_ratio=0.05,
                usdt_premium=0.0,
                global_market_sentiment="neutral"
            )
        return None

    def _calc_volatility(self, prices: list[float]) -> float:
        """计算波动率 (标准差年化)"""
        if len(prices) < 2:
            return 0.0

        try:
            returns = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices))]
            return statistics.stdev(returns) * 100 if len(returns) > 1 else 0.0
        except Exception:
            return 0.0

    async def _get_user_exchange_config(self, user_id: str) -> dict | None:
        """
        获取用户的交易所配置

        如果没有配置或配置无效，返回 None（将使用默认模拟执行器）
        """
        if not EXCHANGE_CONFIG_AVAILABLE or not user_id:
            return None

        try:
            config_manager = get_exchange_config_manager()
            from core.btc_integration.exchange_config import ExchangeType
            active_config = config_manager.get_active_config(user_id, ExchangeType.OKX)

            if not active_config:
                return None

            # 解密配置
            decrypted = config_manager.decrypt_for_use(active_config)

            return {
                'id': str(active_config.id),
                'exchange': decrypted.exchange_type.value if hasattr(decrypted.exchange_type, 'value') else str(decrypted.exchange_type),
                'mode': decrypted.trading_mode.value if hasattr(decrypted.trading_mode, 'value') else str(decrypted.trading_mode),
                'api_key': decrypted.api_key,
                'api_secret': decrypted.api_secret,
                'passphrase': decrypted.passphrase,
                'testnet': decrypted.testnet,
                'name': decrypted.name
            }
        except Exception as e:
            logger.error(f"[TradingAPIBridge] 获取用户配置失败: {e}")
            return None

    async def get_account_info(self, user_id: str) -> dict[str, Any]:
        """
        获取用户账户信息

        前端调用: GET /api/trading-v2/account
        """
        logger.info(f"[TradingAPIBridge] [user={user_id}] 获取账户信息")

        if not SMART_QUANT_AVAILABLE:
            raise HTTPException(503, "Smart Quant 引擎不可用")

        try:
            # 获取用户配置
            exchange_config = await self._get_user_exchange_config(user_id)

            # 获取用户指挥官
            commander = await get_user_commander(user_id, exchange_config)

            # 获取账户信息
            account_info = await commander.get_account_info()

            if "error" in account_info:
                raise HTTPException(500, account_info["error"])

            return account_info

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[TradingAPIBridge] 获取账户信息失败: {e}")
            raise HTTPException(500, f"获取账户信息失败: {str(e)}") from e

    async def execute_trade(
        self,
        user_id: str,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        price: float | None = None,
        leverage: int = 1
    ) -> dict[str, Any]:
        """
        执行交易

        前端调用: POST /api/trading-v2/trade
        """
        logger.info(
            f"[TradingAPIBridge] [user={user_id}] 执行交易: "
            f"{symbol} {side} {quantity}"
        )

        if not SMART_QUANT_AVAILABLE:
            raise HTTPException(503, "Smart Quant 引擎不可用")

        try:
            # 获取用户配置
            exchange_config = await self._get_user_exchange_config(user_id)

            # 验证实盘交易权限
            if exchange_config and exchange_config.get('mode') == 'live':
                # 实盘交易需要额外验证
                logger.warning(
                    f"[TradingAPIBridge] [user={user_id}] 实盘交易请求: "
                    f"{symbol} {side} {quantity}"
                )

            # 获取用户指挥官
            commander = await get_user_commander(user_id, exchange_config)

            # 执行交易
            result = await commander.execute_trade(
                symbol=symbol,
                side=side,
                quantity=quantity,
                order_type=order_type,
                price=price,
                leverage=leverage
            )

            return result

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[TradingAPIBridge] 交易执行失败: {e}")
            raise HTTPException(500, f"交易执行失败: {str(e)}") from e

    async def close_position(
        self,
        user_id: str,
        symbol: str,
        quantity: float | None = None
    ) -> dict[str, Any]:
        """
        平仓

        前端调用: POST /api/trading-v2/close
        """
        logger.info(f"[TradingAPIBridge] [user={user_id}] 平仓: {symbol}")

        if not SMART_QUANT_AVAILABLE:
            raise HTTPException(503, "Smart Quant 引擎不可用")

        try:
            # 获取用户配置
            exchange_config = await self._get_user_exchange_config(user_id)

            # 获取用户指挥官
            commander = await get_user_commander(user_id, exchange_config)

            # 执行平仓
            result = await commander.close_position(symbol, quantity)

            return result

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[TradingAPIBridge] 平仓失败: {e}")
            raise HTTPException(500, f"平仓失败: {str(e)}") from e


# ═══════════════════════════════════════════════════════════════
# 全局实例
# ═══════════════════════════════════════════════════════════════

_api_bridge_instance: TradingAPIBridge | None = None


def get_api_bridge() -> TradingAPIBridge:
    """获取 API 桥接器实例（单例）"""
    global _api_bridge_instance
    if _api_bridge_instance is None:
        _api_bridge_instance = TradingAPIBridge()
    return _api_bridge_instance


def reset_api_bridge():
    """重置 API 桥接器（主要用于测试）"""
    global _api_bridge_instance
    _api_bridge_instance = None
    logger.info("[TradingAPIBridge] 已重置")


# ═══════════════════════════════════════════════════════════════
# FastAPI 路由
# ═══════════════════════════════════════════════════════════════

router = APIRouter(prefix="/trading-v2", tags=["trading_v2"])

# 获取当前用户的依赖
async def get_user_id(credentials = None):
    """获取当前用户ID，未登录返回 None"""
    if AUTH_AVAILABLE:
        try:
            return await get_current_user_optional(credentials)
        except Exception:
            return None
    return None


@router.get("/klines/{symbol}", response_model=KLinesWithAIResponse)
async def get_klines(
    symbol: str,
    interval: TimeInterval = Query(TimeInterval.H1, description="时间周期"),
    limit: int = Query(500, ge=1, le=1000, description="返回条数"),
    user_id: str | None = None
):
    """
    获取带 AI 分析的 K 线数据

    【用户隔离】数据是公开的，但会记录用户访问日志
    """
    bridge = get_api_bridge()
    logger.info(f"[APIBridge] 用户 {user_id or 'anonymous'} 请求 K线: {symbol}")
    return await bridge.get_klines_with_ai(symbol, interval.value, limit)


@router.get("/status/{symbol}", response_model=TradingStatus)
async def get_status(
    symbol: str,
    user_id: str | None = None
):
    """
    获取交易状态

    【用户隔离】返回用户专属的交易状态
    """
    bridge = get_api_bridge()
    logger.info(f"[APIBridge] 用户 {user_id or 'anonymous'} 请求状态: {symbol}")
    return await bridge.get_trading_status(symbol, user_id)


@router.get("/summary", response_model=TradingSummary)
async def get_summary(user_id: str | None = None):
    """
    获取交易摘要

    【用户隔离】返回用户专属的交易摘要
    """
    bridge = get_api_bridge()
    logger.info(f"[APIBridge] 用户 {user_id or 'anonymous'} 请求摘要")
    return await bridge.get_trading_summary(user_id)


@router.get("/health")
async def health_check():
    """健康检查（无需认证）"""
    return {
        "status": "ok",
        "smart_quant_available": SMART_QUANT_AVAILABLE,
        "okx_available": OKX_AVAILABLE,
        "intelligence_available": INTELLIGENCE_AVAILABLE,
        "timestamp": int(time.time())
    }


@router.get("/account", response_model=AccountInfo)
async def get_account(user_id: str | None = None):
    """
    获取账户信息

    【用户隔离】返回用户专属的账户信息
    - 模拟盘：虚拟账户信息
    - 实盘：真实交易所账户信息
    """
    bridge = get_api_bridge()
    logger.info(f"[APIBridge] 用户 {user_id or 'anonymous'} 请求账户信息")
    return await bridge.get_account_info(user_id or "anonymous")


@router.post("/trade", response_model=TradeResponse)
async def execute_trade(
    request: TradeRequest,
    user_id: str | None = None
):
    """
    执行交易

    【用户隔离】执行用户专属的交易操作
    - 模拟盘：模拟执行，无真实资金风险
    - 实盘：真实资金交易
    """
    bridge = get_api_bridge()
    logger.info(
        f"[APIBridge] 用户 {user_id or 'anonymous'} 执行交易: "
        f"{request.symbol} {request.side} {request.quantity}"
    )
    return await bridge.execute_trade(
        user_id=user_id or "anonymous",
        symbol=request.symbol,
        side=request.side,
        quantity=request.quantity,
        order_type=request.order_type,
        price=request.price,
        leverage=request.leverage
    )


@router.post("/close", response_model=TradeResponse)
async def close_position_endpoint(
    symbol: str,
    quantity: float | None = None,
    user_id: str | None = None
):
    """
    平仓

    【用户隔离】关闭用户专属的持仓
    - quantity为None时全平
    """
    bridge = get_api_bridge()
    logger.info(f"[APIBridge] 用户 {user_id or 'anonymous'} 平仓: {symbol}")
    return await bridge.close_position(
        user_id=user_id or "anonymous",
        symbol=symbol,
        quantity=quantity
    )


@router.post("/config/switch")
async def switch_config(
    config_id: str | None = None,
    user_id: str | None = None
):
    """
    切换交易配置

    用于切换模拟盘/实盘或更换交易所配置
    """
    if not SMART_QUANT_AVAILABLE:
        raise HTTPException(503, "Smart Quant 引擎不可用")

    try:
        manager = get_user_trading_manager()

        if config_id:
            # 获取指定配置
            if not EXCHANGE_CONFIG_AVAILABLE:
                raise HTTPException(503, "交易所配置模块不可用")

            config_manager = get_exchange_config_manager()
            configs = config_manager.get_user_configs(user_id or "anonymous")
            target_config = None

            for cfg in configs:
                if str(cfg.id) == config_id:
                    target_config = config_manager.decrypt_for_use(cfg)
                    break

            if not target_config:
                raise HTTPException(404, "配置不存在")

            exchange_config = {
                'id': str(target_config.id),
                'exchange': target_config.exchange_type.value if hasattr(target_config.exchange_type, 'value') else str(target_config.exchange_type),
                'mode': target_config.trading_mode.value if hasattr(target_config.trading_mode, 'value') else str(target_config.trading_mode),
                'api_key': target_config.api_key,
                'api_secret': target_config.api_secret,
                'passphrase': target_config.passphrase,
                'testnet': target_config.testnet,
                'name': target_config.name
            }
        else:
            # 切换到默认模拟配置
            exchange_config = None

        # 切换配置
        await manager.switch_config(user_id or "anonymous", exchange_config)

        return {
            "success": True,
            "user_id": user_id or "anonymous",
            "mode": "模拟盘" if not exchange_config or exchange_config.get('mode') == 'demo' else "实盘",
            "config_id": config_id
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[APIBridge] 切换配置失败: {e}")
        raise HTTPException(500, f"切换配置失败: {str(e)}") from e
