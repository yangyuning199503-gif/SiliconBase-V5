#!/usr/bin/env python3
"""
市场行情工具
提供BTC系统相关的市场数据查询
"""

from typing import Any

from core.btc_integration.event_bus import EventPriority, EventType
from core.btc_integration.market_data import get_market_data_provider
from core.logger import logger

from .base_btc_tool import BaseBTCTool


class MarketOverviewTool(BaseBTCTool):
    """市场概览工具"""

    tool_id = "btc_market_overview"
    name = "BTC市场概览"
    description = """
    获取指定币种的市场概览数据，包括：
    - 当前价格
    - 24小时涨跌
    - 24小时最高/最低价
    - 交易量
    - 市场状态判断（波动率）

    支持BTC、ETH、SOL等主流币种。
    """

    input_schema = {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": "币种代码，如 BTC, ETH, SOL",
                "default": "BTC"
            }
        }
    }

    async def _execute_async(self, symbol: str = "BTC", **kwargs) -> dict[str, Any]:
        """异步获取市场概览"""
        try:
            provider = get_market_data_provider()
            price_data = await provider.get_price(symbol)

            if not price_data:
                return self._format_error(
                    "DATA_NOT_AVAILABLE",
                    f"无法获取 {symbol} 的市场数据",
                    "市场数据暂时不可用"
                )

            # 判断市场状态
            market_state = self._judge_market_state(price_data.change_24h_percent)

            # 极端波动时emit风险警告（AI可观测）
            if market_state["state"] in ("extreme_volatility", "high_volatility"):
                self._emit_to_eventbus(
                    event_type=EventType.RISK_WARNING,
                    data={
                        "level": "critical" if market_state["state"] == "extreme_volatility" else "high",
                        "message": f"{symbol} 24h波动率达 {price_data.change_24h_percent:+.2f}%，{market_state['description']}",
                        "change_24h_percent": price_data.change_24h_percent,
                        "price": price_data.price,
                    },
                    priority=EventPriority.CRITICAL if market_state["state"] == "extreme_volatility" else EventPriority.HIGH,
                    symbol=symbol.upper(),
                )

            data = {
                "symbol": price_data.symbol,
                "price": price_data.price,
                "price_formatted": f"${price_data.price:,.2f}",
                "change_24h": price_data.change_24h,
                "change_24h_percent": price_data.change_24h_percent,
                "change_formatted": f"{price_data.change_24h_percent:+.2f}%",
                "high_24h": price_data.high_24h,
                "low_24h": price_data.low_24h,
                "volume_24h": price_data.volume_24h,
                "timestamp": price_data.timestamp,
                "market_state": market_state["state"],
                "market_state_desc": market_state["description"],
                "trend": "up" if price_data.change_24h >= 0 else "down"
            }

            message = f"{symbol} 当前价格 ${price_data.price:,.2f} ({data['change_formatted']}) | 状态: {market_state['description']}"

            return self._format_success(data, message)

        except Exception as e:
            logger.error(f"[MarketOverviewTool] 错误: {e}")
            return self._format_error("EXECUTION_ERROR", str(e))

    async def run(self, symbol: str = "BTC", **kwargs) -> dict[str, Any]:
        return await self.run_async(symbol=symbol, **kwargs)

    def _judge_market_state(self, change_percent: float) -> dict[str, str]:
        """判断市场状态"""
        abs_change = abs(change_percent)
        if abs_change > 10:
            return {"state": "extreme_volatility", "description": "极端波动"}
        elif abs_change > 5:
            return {"state": "high_volatility", "description": "高波动"}
        elif abs_change > 2:
            return {"state": "normal", "description": "正常波动"}
        else:
            return {"state": "low_volatility", "description": "低波动"}

    def _get_mock_price(self, symbol: str):
        """模拟价格数据（备用）"""
        import random
        import time

        from core.btc_integration.market_data import PriceData

        base_prices = {
            "BTC": 67234.50,
            "ETH": 3456.78,
            "SOL": 145.67,
            "BNB": 567.89
        }
        base = base_prices.get(symbol.upper(), 100)
        change = random.uniform(-0.02, 0.02)

        return PriceData(
            symbol=symbol.upper(),
            price=base * (1 + change),
            change_24h=base * change,
            change_24h_percent=change * 100,
            high_24h=base * 1.05,
            low_24h=base * 0.95,
            volume_24h=random.uniform(1e8, 1e10),
            timestamp=int(time.time())
        )


class KLinesTool(BaseBTCTool):
    """K线数据工具"""

    tool_id = "btc_get_klines"
    name = "获取K线数据"
    description = "获取指定币种的K线历史数据，支持多种时间周期"

    input_schema = {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "default": "BTC"
            },
            "interval": {
                "type": "string",
                "enum": ["1m", "5m", "15m", "1h", "4h", "1d"],
                "default": "1h"
            },
            "limit": {
                "type": "integer",
                "default": 100,
                "minimum": 1,
                "maximum": 1000
            }
        }
    }

    async def _execute_async(self,
                 symbol: str = "BTC",
                 interval: str = "1h",
                 limit: int = 100,
                 **kwargs) -> dict[str, Any]:
        """异步获取K线数据"""
        try:
            provider = get_market_data_provider()
            klines = await provider.get_klines(symbol, interval, limit)

            if not klines:
                return self._format_error(
                    "DATA_NOT_AVAILABLE",
                    f"无法获取 {symbol} 的K线数据",
                    "K线数据暂时不可用"
                )

            data = {
                "symbol": symbol.upper(),
                "interval": interval,
                "count": len(klines),
                "klines": [
                    {
                        "time": k.time,
                        "open": k.open,
                        "high": k.high,
                        "low": k.low,
                        "close": k.close,
                        "volume": k.volume
                    }
                    for k in klines
                ]
            }

            message = f"成功获取 {symbol} {interval} K线数据，共 {len(klines)} 条"

            return self._format_success(data, message)

        except Exception as e:
            logger.error(f"[KLinesTool] 错误: {e}")
            return self._format_error("EXECUTION_ERROR", str(e))

    async def run(self,
                  symbol: str = "BTC",
                  interval: str = "1h",
                  limit: int = 100,
                  **kwargs) -> dict[str, Any]:
        return await self.run_async(symbol=symbol, interval=interval, limit=limit, **kwargs)
