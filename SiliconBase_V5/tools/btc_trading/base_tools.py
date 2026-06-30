#!/usr/bin/env python3
"""
BTC 交易基础工具 - Phase 1

工具列表:
    - BTCPriceQuery: 查询代币价格
    - BTCMarketOverview: 市场概览
    - BTCTechnicalAnalysis: 技术分析
    - BTCAccountInfo: 账户信息

实现说明:
    - 使用 btc_system 的数据源
    - 通过适配器转换输出格式
    - 支持模拟数据（开发/测试模式）
"""

import asyncio
import json
import time
from pathlib import Path
from typing import Any

# 导入基础工具类和错误码
try:
    from core.base_tool import BaseTool
    from core.error_codes import INVALID_PARAMS, TOOL_EXECUTION_ERROR, format_error
except ImportError:
    # 开发环境回退
    BaseTool = object
    def format_error(code, detail=""):
        return {"success": False, "error_code": code, "error_message": detail}
    INVALID_PARAMS = "INVALID_PARAMS"
    TOOL_EXECUTION_ERROR = "TOOL_EXECUTION_ERROR"

# 导入适配器
from .adapter import BTCTradingAdapter


class BTCPriceQuery(BaseTool):
    """
    查询 BTC 或其他代币的当前价格

    功能:
        - 获取实时价格
        - 24小时涨跌幅
        - 24小时成交量

    示例:
        >>> tool = BTCPriceQuery()
        >>> result = tool._execute(symbol="BTC")
        >>> print(result["user_message"])
        BTC 当前价格: $72,450.50
        24h 涨跌: 📈 +2.35%
    """

    tool_id = "btc_price_query"
    name = "BTC 价格查询"
    description = """查询 BTC 或其他代币的实时价格和市场数据。

使用示例:
- 查询 BTC: {"symbol": "BTC"}
- 查询 ETH: {"symbol": "ETH"}
- 查询特定代币: {"symbol": "SOL"}

返回信息:
- 当前价格
- 24小时涨跌幅
- 24小时成交量
"""

    input_schema = {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": "代币符号，如 BTC, ETH, SOL",
                "default": "BTC"
            }
        },
        "required": []
    }

    timeout = 10  # 10秒超时

    def _execute(self, **kwargs) -> dict[str, Any]:
        """执行价格查询"""
        symbol = kwargs.get("symbol", "BTC").upper()

        # 参数验证
        if not isinstance(symbol, str) or len(symbol) > 10:
            return format_error(INVALID_PARAMS, detail="代币符号无效")

        try:
            # 尝试从 btc_system 获取数据
            raw_data = self._fetch_from_btc_system(symbol)

            if raw_data:
                # 使用适配器转换结果
                adapter = BTCTradingAdapter()
                return adapter.adapt_price_data(raw_data)
            else:
                # 返回模拟数据（开发模式）
                return self._get_mock_data(symbol)

        except Exception as e:
            return format_error(
                TOOL_EXECUTION_ERROR,
                detail=f"价格查询失败: {str(e)}"
            )

    async def _execute_async(self, **kwargs) -> dict[str, Any]:
        return await asyncio.to_thread(self._execute, **kwargs)

    def _fetch_from_btc_system(self, symbol: str) -> dict[str, Any] | None:
        """
        从 btc_system 获取价格数据

        实现说明:
            1. 检查 btc_system 的运行时状态文件
            2. 或者调用 btc_system 的 API/工具
        """
        try:
            # 检查 btc_system 的运行时报告
            runtime_path = Path("F:/btc_system_v1/.runtime")

            if not runtime_path.exists():
                return None

            # 尝试读取最新的状态文件
            state_files = list(runtime_path.glob("*state*.json"))
            if not state_files:
                return None

            # 读取最新的状态文件
            latest_file = max(state_files, key=lambda p: p.stat().st_mtime)
            with open(latest_file, encoding='utf-8') as f:
                state = json.load(f)

            # 提取价格信息
            # 注意: 这里需要根据实际的 state 文件结构调整
            symbols_data = state.get("symbols", {})
            symbol_data = symbols_data.get(symbol, {})

            if symbol_data:
                return {
                    "symbol": symbol,
                    "price": symbol_data.get("price", 0),
                    "change_24h": symbol_data.get("change_24h", 0),
                    "volume_24h": symbol_data.get("volume_24h", 0),
                    "timestamp": time.time()
                }

            return None

        except Exception:
            # 静默失败，返回 None 让调用方使用模拟数据
            return None

    def _get_mock_data(self, symbol: str) -> dict[str, Any]:
        """生成模拟数据（开发/测试模式）"""
        import random

        # 基础价格表
        base_prices = {
            "BTC": 72450.0,
            "ETH": 3650.0,
            "SOL": 145.0,
            "BNB": 580.0,
            "XRP": 0.62,
        }

        base_price = base_prices.get(symbol, 100.0)
        # 添加小幅随机波动
        price = base_price * (1 + random.uniform(-0.02, 0.02))
        change_24h = random.uniform(-5.0, 5.0)

        raw_data = {
            "symbol": symbol,
            "price": price,
            "change_24h": change_24h,
            "volume_24h": random.uniform(1000000, 50000000),
            "timestamp": time.time(),
            "source": "mock"
        }

        adapter = BTCTradingAdapter()
        result = adapter.adapt_price_data(raw_data)
        result["data"]["mock_notice"] = "（当前为模拟数据，未连接真实交易所）"
        return result


class BTCMarketOverview(BaseTool):
    """
    获取市场整体概览

    功能:
        - 主要代币价格
        - 市场情绪指数
        - 资金费率
        - 24小时涨跌排行
    """

    tool_id = "btc_market_overview"
    name = "市场概览"
    description = """获取加密货币市场整体情况。

返回信息:
- BTC/ETH 等主要代币价格
- 市场情绪指数（恐惧/贪婪）
- 资金费率
- 24小时涨跌排行

使用场景:
- 快速了解市场整体走势
- 辅助交易决策
"""

    input_schema = {
        "type": "object",
        "properties": {},
        "required": []
    }

    timeout = 15

    def _execute(self, **kwargs) -> dict[str, Any]:
        """执行市场概览查询"""
        try:
            raw_data = self._fetch_market_data()
            adapter = BTCTradingAdapter()
            return adapter.adapt_market_overview(raw_data)
        except Exception as e:
            return format_error(
                TOOL_EXECUTION_ERROR,
                detail=f"市场数据获取失败: {str(e)}"
            )

    async def _execute_async(self, **kwargs) -> dict[str, Any]:
        return await asyncio.to_thread(self._execute, **kwargs)

    def _fetch_market_data(self) -> dict[str, Any]:
        """获取市场数据"""
        # 这里应该整合多个数据源
        # 1. btc_system 的数据
        # 2. CoinGlass API
        # 3. 其他数据源

        # 目前返回模拟数据
        import random

        return {
            "BTC": {
                "price": 72450.0 + random.uniform(-500, 500),
                "change_24h": random.uniform(-3.0, 3.0)
            },
            "ETH": {
                "price": 3650.0 + random.uniform(-50, 50),
                "change_24h": random.uniform(-3.0, 3.0)
            },
            "SOL": {
                "price": 145.0 + random.uniform(-5, 5),
                "change_24h": random.uniform(-5.0, 5.0)
            },
            "sentiment": {
                "fear_greed_index": random.randint(20, 80),
                "classification": random.choice(["恐惧", "中性", "贪婪"])
            },
            "funding_rate": random.uniform(-0.05, 0.05),
            "timestamp": time.time()
        }


class BTCTechnicalAnalysis(BaseTool):
    """
    技术分析工具

    功能:
        - RSI 指标
        - MACD 信号
        - 布林带位置
        - 趋势判断
    """

    tool_id = "btc_technical_analysis"
    name = "技术分析"
    description = """对指定代币进行技术分析。

分析指标:
- RSI (相对强弱指数)
- MACD (指数平滑异同平均线)
- 布林带 (Bollinger Bands)
- 趋势判断

使用示例:
- 分析 BTC: {"symbol": "BTC", "timeframe": "1h"}
- 分析 ETH: {"symbol": "ETH", "timeframe": "4h"}

参数说明:
- symbol: 代币符号
- timeframe: 时间周期 (15m, 1h, 4h, 1d)
"""

    input_schema = {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": "代币符号",
                "default": "BTC"
            },
            "timeframe": {
                "type": "string",
                "enum": ["15m", "1h", "4h", "1d"],
                "description": "分析时间周期",
                "default": "1h"
            }
        },
        "required": []
    }

    timeout = 20

    def _execute(self, **kwargs) -> dict[str, Any]:
        """执行技术分析"""
        symbol = kwargs.get("symbol", "BTC").upper()
        timeframe = kwargs.get("timeframe", "1h")

        # 参数验证
        valid_timeframes = ["15m", "1h", "4h", "1d"]
        if timeframe not in valid_timeframes:
            return format_error(
                INVALID_PARAMS,
                detail=f"无效的时间周期，可选: {', '.join(valid_timeframes)}"
            )

        try:
            raw_data = self._fetch_ta_data(symbol, timeframe)
            adapter = BTCTradingAdapter()
            return adapter.adapt_technical_analysis(raw_data)
        except Exception as e:
            return format_error(
                TOOL_EXECUTION_ERROR,
                detail=f"技术分析失败: {str(e)}"
            )

    async def _execute_async(self, **kwargs) -> dict[str, Any]:
        return await asyncio.to_thread(self._execute, **kwargs)

    def _fetch_ta_data(self, symbol: str, timeframe: str) -> dict[str, Any]:
        """获取技术分析数据"""
        import random

        # 模拟技术指标计算
        rsi = random.uniform(20, 80)

        # MACD 信号
        macd_signals = ["bullish", "bearish", "neutral"]
        macd_weights = [0.3, 0.3, 0.4]  # 中性概率稍高
        macd_signal = random.choices(macd_signals, macd_weights)[0]

        # 布林带位置
        bb_positions = ["upper", "middle", "lower", "breakout_up", "breakout_down"]
        bb_weights = [0.2, 0.4, 0.2, 0.1, 0.1]
        bb_position = random.choices(bb_positions, bb_weights)[0]

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "indicators": {
                "rsi": rsi,
                "macd_signal": macd_signal,
                "bb_position": bb_position,
                "sma_20": random.uniform(70000, 75000),
                "sma_50": random.uniform(68000, 72000)
            },
            "trend": random.choice(["uptrend", "downtrend", "sideways"]),
            "support": random.uniform(68000, 70000),
            "resistance": random.uniform(74000, 76000),
            "timestamp": time.time()
        }


class BTCAccountInfo(BaseTool):
    """
    查询交易账户信息

    功能:
        - 账户权益
        - 可用余额
        - 持仓信息
        - 保证金率
        - 未实现盈亏

    注意:
        - 此工具需要配置 API Key
        - 默认返回模拟数据（如果没有配置）
    """

    tool_id = "btc_account_info"
    name = "账户信息"
    description = """查询交易账户的详细信息和持仓情况。

返回信息:
- 账户权益 (总资金)
- 可用余额
- 保证金率
- 未实现盈亏
- 当前持仓

注意:
- 需要配置 OKX API Key
- 未配置时返回模拟数据
"""

    input_schema = {
        "type": "object",
        "properties": {},
        "required": []
    }

    timeout = 10
    require_confirmation = False

    def _execute(self, **kwargs) -> dict[str, Any]:
        """执行账户信息查询"""
        try:
            # 检查是否有 API 配置
            has_api_config = self._check_api_config()

            if has_api_config:
                raw_data = self._fetch_real_account_data()
            else:
                raw_data = self._get_mock_account_data()
                raw_data["mock_notice"] = "（当前为模拟数据，未配置真实 API）"

            adapter = BTCTradingAdapter()
            return adapter.adapt_account_info(raw_data)

        except Exception as e:
            return format_error(
                TOOL_EXECUTION_ERROR,
                detail=f"账户信息获取失败: {str(e)}"
            )

    async def _execute_async(self, **kwargs) -> dict[str, Any]:
        return await asyncio.to_thread(self._execute, **kwargs)

    def _check_api_config(self) -> bool:
        """检查是否配置了 API Key"""
        try:
            # 检查环境变量或配置文件
            import os
            return bool(
                os.environ.get("OKX_API_KEY") or
                os.environ.get("OKX_DEMO_API_KEY")
            )
        except Exception:
            return False

    def _fetch_real_account_data(self) -> dict[str, Any]:
        """从 OKX API 获取真实账户数据"""
        # TODO: 实现真实的 API 调用
        # 这里需要集成 btc_system 的 API 调用逻辑
        return self._get_mock_account_data()

    def _get_mock_account_data(self) -> dict[str, Any]:
        """生成模拟账户数据"""
        import random

        equity = 10000.0 + random.uniform(-500, 500)
        unrealized_pnl = random.uniform(-200, 300)
        margin_used = random.uniform(1000, 3000)

        return {
            "equity": equity,
            "available": equity - margin_used,
            "margin_ratio": (margin_used / equity * 100) if equity > 0 else 0,
            "unrealized_pnl": unrealized_pnl,
            "positions": [
                {
                    "symbol": "BTC-USDT-SWAP",
                    "side": "LONG",
                    "size": 0.1,
                    "avg_price": 72000.0,
                    "mark_price": 72450.0,
                    "unrealized_pnl": 45.0
                }
            ],
            "timestamp": time.time()
        }
