#!/usr/bin/env python3
"""
交易记忆辅助模块
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
封装交易相关的记忆操作，复用主AI的MemoryManager

功能:
- 交易记录存取
- 策略效果统计
- 用户画像管理
- 市场模式识别
"""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from core.logger import logger

# 导入记忆系统
try:
    from core.memory.memory_manager import (
        MemoryLayer,
        MemoryManager,
        MemoryType,
        memory_manager,
    )
    MEMORY_AVAILABLE = True
except ImportError:
    MEMORY_AVAILABLE = False
    logger.warning("[TradingMemory] MemoryManager不可用")


@dataclass
class TradeRecord:
    """交易记录"""
    symbol: str
    action: str  # open_long, open_short, close, hold
    direction: str | None  # long, short
    size: float
    price: float
    leverage: int
    pnl: float | None = None
    pnl_percent: float | None = None
    strategy: str = ""
    reasoning: str = ""
    visual_state: str | None = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "action": self.action,
            "direction": self.direction,
            "size": self.size,
            "price": self.price,
            "leverage": self.leverage,
            "pnl": self.pnl,
            "pnl_percent": self.pnl_percent,
            "strategy": self.strategy,
            "reasoning": self.reasoning,
            "visual_state": self.visual_state,
            "timestamp": self.timestamp,
            "datetime": datetime.fromtimestamp(self.timestamp).isoformat(),
        }


@dataclass
class StrategyMetrics:
    """策略效果指标"""
    strategy_id: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    avg_profit: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": self.win_rate,
            "avg_profit": self.avg_profit,
            "avg_loss": self.avg_loss,
            "profit_factor": self.profit_factor,
            "max_drawdown": self.max_drawdown,
            "sharpe_ratio": self.sharpe_ratio,
            "updated_at": self.updated_at,
        }


class TradingMemoryHelper:
    """
    交易记忆辅助类

    复用主AI的MemoryManager，统一管理交易相关记忆
    """

    def __init__(self, user_id: str = "default"):
        self.user_id = user_id
        self.memory: MemoryManager | None = None

        if MEMORY_AVAILABLE:
            try:
                self.memory = memory_manager
                logger.info("[TradingMemory] 已连接到记忆系统")
            except Exception as e:
                logger.error(f"[TradingMemory] 连接记忆系统失败: {e}")

        # 本地缓存（减少记忆查询）
        self._cache: dict[str, Any] = {}
        self._cache_ttl = 60  # 60秒缓存
        self._cache_time: dict[str, float] = {}

    def _is_cache_valid(self, key: str) -> bool:
        """检查缓存是否有效"""
        if key not in self._cache:
            return False
        return not time.time() - self._cache_time.get(key, 0) > self._cache_ttl

    async def record_trade(self, trade: TradeRecord) -> bool:
        """
        记录交易

        Args:
            trade: 交易记录

        Returns:
            是否成功
        """
        if not self.memory:
            logger.warning("[TradingMemory] 记忆系统不可用，跳过记录")
            return False

        try:
            # L3中期记忆：交易记录（改为MEDIUM避免1天后过期）
            await self.memory.add_memory(
                layer=MemoryLayer.MEDIUM,
                mem_type=MemoryType.TRADING,
                content=trade.to_dict(),
                user_id=self.user_id,
                context={
                    "symbol": trade.symbol,
                    "action": trade.action,
                    "strategy": trade.strategy,
                }
            )

            # 更新缓存
            cache_key = f"recent_trades_{trade.symbol}"
            if self._is_cache_valid(cache_key):
                self._cache[cache_key].insert(0, trade.to_dict())
                self._cache[cache_key] = self._cache[cache_key][:100]  # 保留100条

            logger.debug(f"[TradingMemory] 记录交易: {trade.symbol} {trade.action}")
            return True

        except Exception as e:
            logger.error(f"[TradingMemory] 记录交易失败: {e}")
            return False

    async def record_decision(
        self,
        symbol: str,
        decision: str,
        reasoning: str,
        context: dict = None
    ) -> bool:
        """
        记录AI决策过程

        Args:
            symbol: 交易对
            decision: 决策内容
            reasoning: 决策理由
            context: 上下文信息
        """
        if not self.memory:
            return False

        try:
            await self.memory.add_memory(
                layer=MemoryLayer.MEDIUM,
                mem_type=MemoryType.TRADING_DECISION,
                content={
                    "symbol": symbol,
                    "decision": decision,
                    "reasoning": reasoning,
                    "context": context or {},
                    "timestamp": time.time(),
                },
                user_id=self.user_id,
            )
            return True
        except Exception as e:
            logger.error(f"[TradingMemory] 记录决策失败: {e}")
            return False

    async def get_recent_trades(
        self,
        symbol: str,
        limit: int = 10
    ) -> list[dict]:
        """
        获取最近交易记录

        Args:
            symbol: 交易对
            limit: 数量限制

        Returns:
            交易记录列表
        """
        cache_key = f"recent_trades_{symbol}"
        if self._is_cache_valid(cache_key):
            return self._cache[cache_key][:limit]

        if not self.memory:
            return []

        try:
            results = await self.memory.retrieve_memory(
                query=None,
                mem_type=MemoryType.TRADING,
                limit=limit,
            )

            trades = [r.get('content') for r in results if isinstance(r.get('content'), dict)]

            # 更新缓存
            self._cache[cache_key] = trades
            self._cache_time[cache_key] = time.time()

            return trades

        except Exception as e:
            logger.error(f"[TradingMemory] 查询交易记录失败: {e}")
            return []

    async def update_strategy_metrics(
        self,
        strategy_id: str,
        metrics: StrategyMetrics
    ) -> bool:
        """
        更新策略效果指标

        Args:
            strategy_id: 策略ID
            metrics: 效果指标
        """
        if not self.memory:
            return False

        try:
            await self.memory.add_memory(
                layer=MemoryLayer.EVOLVE,  # L4长期记忆
                mem_type=MemoryType.STRATEGY_EVOLUTION,
                content=metrics.to_dict(),
                user_id=self.user_id,
                context={"strategy_id": strategy_id},
            )
            return True
        except Exception as e:
            logger.error(f"[TradingMemory] 更新策略指标失败: {e}")
            return False

    async def get_strategy_metrics(
        self,
        strategy_id: str
    ) -> StrategyMetrics | None:
        """
        获取策略效果指标

        Args:
            strategy_id: 策略ID

        Returns:
            效果指标
        """
        if not self.memory:
            return None

        try:
            results = await self.memory.retrieve_memory(
                query=None,
                mem_type=MemoryType.STRATEGY_EVOLUTION,
                limit=1,
            )

            if results:
                data = results[0].get('content')
                return StrategyMetrics(**data)
            return None

        except Exception as e:
            logger.error(f"[TradingMemory] 查询策略指标失败: {e}")
            return None

    async def record_market_pattern(
        self,
        pattern_name: str,
        description: str,
        symbols: list[str],
        success_rate: float = 0.0
    ) -> bool:
        """
        记录市场模式

        Args:
            pattern_name: 模式名称
            description: 模式描述
            symbols: 适用币种
            success_rate: 历史成功率
        """
        if not self.memory:
            return False

        try:
            await self.memory.add_memory(
                layer=MemoryLayer.EVOLVE,
                mem_type=MemoryType.MARKET_PATTERN,
                content={
                    "pattern_name": pattern_name,
                    "description": description,
                    "symbols": symbols,
                    "success_rate": success_rate,
                    "timestamp": time.time(),
                },
                user_id=self.user_id,
            )
            return True
        except Exception as e:
            logger.error(f"[TradingMemory] 记录市场模式失败: {e}")
            return False

    async def get_similar_patterns(
        self,
        query: str,
        limit: int = 5
    ) -> list[dict]:
        """
        查询相似市场模式

        Args:
            query: 查询描述
            limit: 数量限制

        Returns:
            模式列表
        """
        if not self.memory:
            return []

        try:
            # 使用向量检索
            results = await self.memory.retrieve_memory(
                query=query,
                mem_type=MemoryType.MARKET_PATTERN,
                limit=limit,
                use_vector=True,
            )

            return [r.get('content') for r in results if isinstance(r.get('content'), dict)]

        except Exception as e:
            logger.error(f"[TradingMemory] 查询市场模式失败: {e}")
            return []

    async def get_user_trading_profile(self) -> dict:
        """
        获取用户交易画像

        Returns:
            用户画像数据
        """
        # 查询所有交易记录
        all_trades = []
        for symbol in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            trades = await self.get_recent_trades(symbol, limit=100)
            all_trades.extend(trades)

        if not all_trades:
            return {
                "risk_preference": "moderate",
                "preferred_symbols": ["BTC", "ETH"],
                "avg_trade_size": 0.0,
                "avg_leverage": 1,
                "total_trades": 0,
            }

        # 计算统计
        total_trades = len(all_trades)
        winning_trades = sum(1 for t in all_trades if (t.get("pnl") or 0) > 0)

        avg_size = sum(t.get("size", 0) for t in all_trades) / total_trades
        avg_leverage = sum(t.get("leverage", 1) for t in all_trades) / total_trades

        # 推断风险偏好
        if avg_leverage > 10:
            risk = "aggressive"
        elif avg_leverage > 5:
            risk = "moderate_aggressive"
        elif avg_leverage > 2:
            risk = "moderate"
        else:
            risk = "conservative"

        # 统计偏好币种
        symbol_counts = {}
        for t in all_trades:
            s = t.get("symbol", "")
            symbol_counts[s] = symbol_counts.get(s, 0) + 1
        preferred = sorted(symbol_counts.keys(), key=lambda x: symbol_counts[x], reverse=True)[:3]

        return {
            "risk_preference": risk,
            "win_rate": winning_trades / total_trades if total_trades > 0 else 0,
            "avg_trade_size": avg_size,
            "avg_leverage": avg_leverage,
            "total_trades": total_trades,
            "preferred_symbols": preferred,
        }

    async def get_recent_decisions(
        self,
        symbol: str | None = None,
        limit: int = 10
    ) -> list[dict]:
        """
        获取最近决策记录

        Args:
            symbol: 交易对筛选
            limit: 数量限制

        Returns:
            决策记录列表
        """
        if not self.memory:
            return []

        try:
            filters = {}
            if symbol:
                filters["symbol"] = symbol

            results = await self.memory.retrieve_memory(
                query=None,
                mem_type=MemoryType.TRADING_DECISION,
                limit=limit,
            )

            return [r.get('content') for r in results if isinstance(r.get('content'), dict)]

        except Exception as e:
            logger.error(f"[TradingMemory] 查询决策记录失败: {e}")
            return []


# 全局实例
trading_memory: TradingMemoryHelper | None = None


def get_trading_memory(user_id: str = "default") -> TradingMemoryHelper:
    """获取交易记忆辅助实例"""
    global trading_memory
    if trading_memory is None:
        trading_memory = TradingMemoryHelper(user_id=user_id)
    return trading_memory


if __name__ == "__main__":
    async def test():
        tm = get_trading_memory()

        # 记录测试交易
        trade = TradeRecord(
            symbol="BTC",
            action="open_long",
            direction="long",
            size=0.1,
            price=65000.0,
            leverage=5,
            strategy="trend_following",
            reasoning="突破阻力位",
        )

        await tm.record_trade(trade)

        # 查询
        trades = await tm.get_recent_trades("BTC", limit=5)
        print(f"Recent trades: {len(trades)}")

        # 用户画像
        profile = await tm.get_user_trading_profile()
        print(f"Profile: {profile}")

    import asyncio
    asyncio.run(test())
