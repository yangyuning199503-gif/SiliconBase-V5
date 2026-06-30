#!/usr/bin/env python3
"""
BTC 交易工具适配器
将 btc_system_v1 的输出转换为 SiliconBase V5 标准格式

设计原则:
    1. 不改动 btc_system 原有代码
    2. 统一返回值格式
    3. 生成用户友好的消息
    4. 完整的错误处理
"""

from typing import Any


class BTCTradingAdapter:
    """
    BTC 交易结果适配器

    将 btc_system 的原始输出转换为 SiliconBase 标准格式:
    {
        "success": bool,
        "error_code": str or None,
        "error_message": str,
        "user_message": str,  # 给用户看的友好消息
        "data": Any
    }
    """

    @staticmethod
    def adapt_autopilot_result(raw_result: dict[str, Any]) -> dict[str, Any]:
        """
        适配 autopilot 输出

        Args:
            raw_result: btc_system autopilot 的原始输出

        Returns:
            SiliconBase 标准格式的结果
        """
        if not isinstance(raw_result, dict):
            return {
                "success": False,
                "error_code": "INVALID_RESULT_FORMAT",
                "error_message": f"Invalid result type: {type(raw_result)}",
                "user_message": "交易引擎返回了无效的数据格式",
                "data": raw_result
            }

        # 检查是否成功
        is_ok = raw_result.get("ok", False)

        if is_ok:
            return {
                "success": True,
                "error_code": None,
                "error_message": "",
                "user_message": BTCTradingAdapter._generate_success_message(raw_result),
                "data": raw_result
            }
        else:
            error = raw_result.get("error", "未知错误")
            return {
                "success": False,
                "error_code": raw_result.get("error_code", "TRADING_ERROR"),
                "error_message": error,
                "user_message": f"交易执行失败: {error}",
                "data": raw_result
            }

    @staticmethod
    def adapt_price_data(raw_data: dict[str, Any]) -> dict[str, Any]:
        """适配价格查询结果"""
        if not raw_data or "price" not in raw_data:
            return {
                "success": False,
                "error_code": "NO_PRICE_DATA",
                "error_message": "无法获取价格数据",
                "user_message": "暂时无法获取该代币的价格信息，请稍后重试",
                "data": raw_data
            }

        price = raw_data.get("price", 0)
        change_24h = raw_data.get("change_24h", 0)
        symbol = raw_data.get("symbol", "UNKNOWN")

        # 生成趋势 emoji
        trend = "📈" if change_24h > 0 else "📉" if change_24h < 0 else "➡️"

        return {
            "success": True,
            "error_code": None,
            "error_message": "",
            "user_message": (
                f"{symbol} 当前价格: ${price:,.2f}\n"
                f"24h 涨跌: {trend} {change_24h:+.2f}%"
            ),
            "data": raw_data
        }

    @staticmethod
    def adapt_market_overview(raw_data: dict[str, Any]) -> dict[str, Any]:
        """适配市场概览结果"""
        if not raw_data:
            return {
                "success": False,
                "error_code": "NO_MARKET_DATA",
                "error_message": "无法获取市场数据",
                "user_message": "暂时无法获取市场行情，请稍后重试",
                "data": raw_data
            }

        # 构建市场概览消息
        messages = ["📊 市场行情概览\n"]

        # BTC 数据
        btc = raw_data.get("BTC", {})
        if btc:
            btc_price = btc.get("price", 0)
            btc_change = btc.get("change_24h", 0)
            btc_trend = "📈" if btc_change > 0 else "📉"
            messages.append(f"【BTC】${btc_price:,.2f} {btc_trend} {btc_change:+.2f}%")

        # ETH 数据
        eth = raw_data.get("ETH", {})
        if eth:
            eth_price = eth.get("price", 0)
            eth_change = eth.get("change_24h", 0)
            eth_trend = "📈" if eth_change > 0 else "📉"
            messages.append(f"【ETH】${eth_price:,.2f} {eth_trend} {eth_change:+.2f}%")

        # 市场情绪
        sentiment = raw_data.get("sentiment", {})
        if sentiment:
            fear_greed = sentiment.get("fear_greed_index", 50)
            fg_emoji = "😱" if fear_greed < 25 else "😰" if fear_greed < 45 else "😐" if fear_greed < 55 else "😊" if fear_greed < 75 else "🤑"
            messages.append(f"\n市场情绪: {fg_emoji} {fear_greed}/100")

        # 资金费率
        funding = raw_data.get("funding_rate", 0)
        if funding:
            funding_emoji = "🟢" if funding > 0 else "🔴"
            messages.append(f"资金费率: {funding_emoji} {funding:.4f}%")

        return {
            "success": True,
            "error_code": None,
            "error_message": "",
            "user_message": "\n".join(messages),
            "data": raw_data
        }

    @staticmethod
    def adapt_technical_analysis(raw_data: dict[str, Any]) -> dict[str, Any]:
        """适配技术分析结果"""
        if not raw_data or "indicators" not in raw_data:
            return {
                "success": False,
                "error_code": "NO_TA_DATA",
                "error_message": "无法获取技术分析数据",
                "user_message": "技术分析数据暂不可用",
                "data": raw_data
            }

        indicators = raw_data.get("indicators", {})
        symbol = raw_data.get("symbol", "BTC")

        # 解析指标
        rsi = indicators.get("rsi", 50)
        macd_signal = indicators.get("macd_signal", "neutral")
        bb_position = indicators.get("bb_position", "middle")

        # 生成信号解读
        signals = []

        # RSI 解读
        if rsi > 70:
            signals.append(f"RSI({rsi:.1f}): 超买区域，注意回调风险 ⚠️")
        elif rsi < 30:
            signals.append(f"RSI({rsi:.1f}): 超卖区域，可能存在反弹机会 💡")
        else:
            signals.append(f"RSI({rsi:.1f}): 中性区域")

        # MACD 解读
        macd_map = {
            "bullish": "MACD: 金叉形成，动能偏多 📈",
            "bearish": "MACD: 死叉形成，动能偏空 📉",
            "neutral": "MACD: 趋势不明确"
        }
        signals.append(macd_map.get(macd_signal, macd_map["neutral"]))

        # 布林带解读
        bb_map = {
            "upper": "布林带: 价格接近上轨，可能超买",
            "lower": "布林带: 价格接近下轨，可能超卖",
            "middle": "布林带: 价格在中轨附近",
            "breakout_up": "布林带: 向上突破 🚀",
            "breakout_down": "布林带: 向下突破 🔻"
        }
        signals.append(bb_map.get(bb_position, bb_map["middle"]))

        # 综合建议
        if rsi > 70 and macd_signal == "bearish":
            suggestion = "建议: 考虑减仓或做空"
        elif rsi < 30 and macd_signal == "bullish":
            suggestion = "建议: 考虑建仓或加仓"
        else:
            suggestion = "建议: 观望等待明确信号"

        messages = [f"📈 {symbol} 技术分析", ""] + signals + ["", suggestion]

        return {
            "success": True,
            "error_code": None,
            "error_message": "",
            "user_message": "\n".join(messages),
            "data": raw_data
        }

    @staticmethod
    def adapt_account_info(raw_data: dict[str, Any]) -> dict[str, Any]:
        """适配账户信息结果"""
        if not raw_data:
            return {
                "success": False,
                "error_code": "NO_ACCOUNT_DATA",
                "error_message": "无法获取账户信息",
                "user_message": "账户信息获取失败，请检查 API 配置",
                "data": raw_data
            }

        equity = raw_data.get("equity", 0)
        available = raw_data.get("available", 0)
        margin_ratio = raw_data.get("margin_ratio", 0)
        unrealized_pnl = raw_data.get("unrealized_pnl", 0)

        pnl_emoji = "🟢" if unrealized_pnl > 0 else "🔴" if unrealized_pnl < 0 else "⚪"

        messages = [
            "💼 账户概览",
            "",
            f"账户权益: ${equity:,.2f}",
            f"可用余额: ${available:,.2f}",
            f"保证金率: {margin_ratio:.2f}%",
            f"未实现盈亏: {pnl_emoji} ${unrealized_pnl:+.2f}"
        ]

        # 风险提示
        if margin_ratio < 10:
            messages.append("\n⚠️ 警告: 保证金率过低，请注意风险!")

        return {
            "success": True,
            "error_code": None,
            "error_message": "",
            "user_message": "\n".join(messages),
            "data": raw_data
        }

    @staticmethod
    def _generate_success_message(raw_result: dict[str, Any]) -> str:
        """生成成功执行的友好消息"""
        status = raw_result.get("status", "unknown")

        if status == "running":
            return "✅ 交易引擎已启动，正在运行中..."
        elif status == "completed":
            pnl = raw_result.get("pnl", 0)
            pnl_emoji = "🟢" if pnl > 0 else "🔴"
            return f"✅ 交易完成! {pnl_emoji} 盈亏: ${pnl:+.2f}"
        else:
            return f"交易状态: {status}"


# 便捷的全局适配函数
def adapt_btc_result(result_type: str, raw_data: Any) -> dict[str, Any]:
    """
    通用适配函数

    Args:
        result_type: 结果类型 (autopilot, price, market, ta, account)
        raw_data: 原始数据

    Returns:
        适配后的标准格式结果
    """
    adapter = BTCTradingAdapter()

    adapters = {
        "autopilot": adapter.adapt_autopilot_result,
        "price": adapter.adapt_price_data,
        "market": adapter.adapt_market_overview,
        "ta": adapter.adapt_technical_analysis,
        "account": adapter.adapt_account_info,
    }

    adapt_func = adapters.get(result_type, adapter.adapt_autopilot_result)
    return adapt_func(raw_data)
