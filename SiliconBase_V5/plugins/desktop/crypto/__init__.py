#!/usr/bin/env python3
"""
crypto插件（币安Testnet模拟盘）：行情查询/限价交易
真实对接币安Testnet，使用 python-binance 库
"""
import json
import os
import time

try:
    from binance.client import Client
    from binance.exceptions import BinanceAPIException, BinanceOrderException
    BINANCE_AVAILABLE = True
except ImportError:
    BINANCE_AVAILABLE = False

from core.config import get_config
from core.utils import init_logger

logger = init_logger("crypto_plugin")

# 读取配置（建议在 global.yaml 或 plugin_config/crypto.yaml 中配置）
CRYPTO_CONFIG = get_config("plugin", "crypto") or {}
BINANCE_CONFIG = CRYPTO_CONFIG.get("binance", {})
TESTNET_API_KEY = BINANCE_CONFIG.get("testnet_api_key", "")
TESTNET_API_SECRET = BINANCE_CONFIG.get("testnet_api_secret", "")
DEFAULT_SYMBOL = CRYPTO_CONFIG.get("default_symbol", "BTCUSDT")
DEFAULT_AMOUNT = CRYPTO_CONFIG.get("default_amount", 0.001)

# 实时数据文件路径
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REAL_TIME_DATA_PATH = os.path.join(BASE_DIR, "data", "crypto_real_time_data.json")


def _write_real_time_data(data: dict):
    """写入实时数据到JSON文件"""
    try:
        os.makedirs(os.path.dirname(REAL_TIME_DATA_PATH), exist_ok=True)
        # 读取原有数据
        if os.path.exists(REAL_TIME_DATA_PATH):
            with open(REAL_TIME_DATA_PATH, encoding="utf-8") as f:
                real_time_data = json.load(f) or {}
        else:
            real_time_data = {}
        real_time_data.update(data)
        real_time_data["update_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(REAL_TIME_DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(real_time_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"写入实时数据失败: {e}")


def _get_client() -> Client | None:
    """获取币安Testnet客户端（带时间校准）"""
    if not BINANCE_AVAILABLE:
        logger.error("python-binance 未安装，请执行：pip install python-binance")
        return None
    if not TESTNET_API_KEY or not TESTNET_API_SECRET:
        logger.error("未配置 Testnet API 密钥")
        return None
    try:
        client = Client(TESTNET_API_KEY, TESTNET_API_SECRET, testnet=True)
        # 获取服务器时间，校准时间偏移
        server_time = client.get_server_time()
        client.timestamp_offset = server_time['serverTime'] - int(time.time() * 1000)
        return client
    except Exception as e:
        logger.error(f"初始化币安客户端失败: {e}")
        return None


# ---------- 插件标准接口 ----------
def plugin_info() -> dict:
    return {
        "plugin_name": "crypto",
        "plugin_version": "1.0.0",
        "plugin_author": "AI_Silicon_Base",
        "plugin_desc": "炒币插件，支持币安Testnet实时行情和限价交易",
        "plugin_type": "desktop",
        "enable": CRYPTO_CONFIG.get("enable", True)
    }


def plugin_init() -> bool:
    """初始化插件"""
    if not plugin_info().get("enable", False):
        logger.info("crypto插件已关闭，跳过初始化")
        return True
    logger.info("crypto插件初始化完成（币安Testnet模式）")
    return True


def plugin_call(action: str = "query", **kwargs) -> dict:
    """插件调用入口"""
    if action == "query":
        return query(**kwargs)
    elif action == "buy":
        return trade("buy", **kwargs)
    elif action == "sell":
        return trade("sell", **kwargs)
    else:
        return {"status": "error", "msg": f"不支持的操作：{action}"}


def query(symbol: str = DEFAULT_SYMBOL) -> dict:
    """获取实时行情"""
    client = _get_client()
    if not client:
        return {"status": "error", "msg": "币安客户端初始化失败"}
    try:
        ticker = client.get_symbol_ticker(symbol=symbol)
        _write_real_time_data({"market_data": ticker, "last_price": float(ticker["price"])})
        return {
            "status": "success",
            "data": ticker,
            "exchange": "binance_testnet",
            "msg": f"查询{symbol}成功"
        }
    except BinanceAPIException as e:
        return {"status": "error", "msg": f"API错误：{e}"}
    except Exception as e:
        return {"status": "error", "msg": f"未知错误：{e}"}


def trade(side: str, symbol: str = DEFAULT_SYMBOL, price: float = None, amount: float = DEFAULT_AMOUNT) -> dict:
    """执行限价交易"""
    if price is None or price <= 0:
        return {"status": "error", "msg": "价格必须大于0"}
    client = _get_client()
    if not client:
        return {"status": "error", "msg": "币安客户端初始化失败"}
    try:
        order = client.create_order(
            symbol=symbol,
            side=side.upper(),
            type=Client.ORDER_TYPE_LIMIT,
            timeInForce=Client.TIME_IN_FORCE_GTC,
            quantity=amount,
            price=str(price)
        )
        # 记录交易到实时数据
        trade_record = {
            "side": side,
            "symbol": symbol,
            "price": price,
            "amount": amount,
            "order_id": order.get("orderId"),
            "status": "success"
        }
        _write_real_time_data({"last_trade": trade_record})
        return {
            "status": "success",
            "data": order,
            "msg": f"{side} {symbol} 成功，订单ID：{order.get('orderId')}"
        }
    except (BinanceAPIException, BinanceOrderException) as e:
        return {"status": "error", "msg": f"交易失败：{e}"}
    except Exception as e:
        return {"status": "error", "msg": f"未知错误：{e}"}


# 兼容旧版调用
def get_realtime_market(symbol: str = DEFAULT_SYMBOL) -> dict:
    result = query(symbol)
    if result["status"] == "success":
        return {
            "symbol": result["data"]["symbol"],
            "price": result["data"]["price"],
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "status": "success"
        }
    else:
        return {"symbol": symbol, "price": "0.00000000", "status": "error", "msg": result["msg"]}


def crypto_trade(func: str, symbol: str = DEFAULT_SYMBOL, price: float = 0.0, amount: float = DEFAULT_AMOUNT) -> dict:
    return trade(func, symbol, price, amount)
