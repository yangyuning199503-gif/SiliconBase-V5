#!/usr/bin/env python3
"""
交易系统日志工具
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
提供统一的日志格式，包含用户隔离信息

作者: SiliconBase Team
日期: 2026-04-09
"""


from core.logger import logger


class TradingLogger:
    """
    交易系统日志器

    统一日志格式: [模块名] [user={user_id}] [symbol={symbol}] 消息
    """

    def __init__(self, module_name: str):
        self.module_name = module_name

    def _format_message(self, message: str, user_id: str | None = None, symbol: str | None = None, **kwargs) -> str:
        """格式化日志消息"""
        parts = [f"[{self.module_name}]"]

        if user_id:
            parts.append(f"[user={user_id}]")

        if symbol:
            parts.append(f"[symbol={symbol}]")

        # 添加其他上下文
        for key, value in kwargs.items():
            if value is not None:
                parts.append(f"[{key}={value}]")

        parts.append(message)
        return " ".join(parts)

    def info(self, message: str, user_id: str | None = None, symbol: str | None = None, **kwargs):
        """输出 INFO 级别日志"""
        logger.info(self._format_message(message, user_id, symbol, **kwargs))

    def warning(self, message: str, user_id: str | None = None, symbol: str | None = None, **kwargs):
        """输出 WARNING 级别日志"""
        logger.warning(self._format_message(message, user_id, symbol, **kwargs))

    def error(self, message: str, user_id: str | None = None, symbol: str | None = None, **kwargs):
        """输出 ERROR 级别日志"""
        logger.error(self._format_message(message, user_id, symbol, **kwargs))

    def debug(self, message: str, user_id: str | None = None, symbol: str | None = None, **kwargs):
        """输出 DEBUG 级别日志"""
        logger.debug(self._format_message(message, user_id, symbol, **kwargs))

    def critical(self, message: str, user_id: str | None = None, symbol: str | None = None, **kwargs):
        """输出 CRITICAL 级别日志"""
        logger.critical(self._format_message(message, user_id, symbol, **kwargs))


# 全局日志器实例
_trading_logger: TradingLogger | None = None


def get_trading_logger() -> TradingLogger:
    """获取交易系统日志器"""
    global _trading_logger
    if _trading_logger is None:
        _trading_logger = TradingLogger("Trading")
    return _trading_logger


# 快捷函数
def log_info(message: str, user_id: str | None = None, symbol: str | None = None, **kwargs):
    """快捷 INFO 日志"""
    get_trading_logger().info(message, user_id, symbol, **kwargs)


def log_warning(message: str, user_id: str | None = None, symbol: str | None = None, **kwargs):
    """快捷 WARNING 日志"""
    get_trading_logger().warning(message, user_id, symbol, **kwargs)


def log_error(message: str, user_id: str | None = None, symbol: str | None = None, **kwargs):
    """快捷 ERROR 日志"""
    get_trading_logger().error(message, user_id, symbol, **kwargs)


def log_debug(message: str, user_id: str | None = None, symbol: str | None = None, **kwargs):
    """快捷 DEBUG 日志"""
    get_trading_logger().debug(message, user_id, symbol, **kwargs)


class LogContext:
    """
    日志上下文管理器

    用法:
        with LogContext(user_id="user123", symbol="BTC"):
            # 这里的日志会自动包含 user_id 和 symbol
            trading_log.info("交易执行成功")
    """

    _context = {}

    def __init__(self, user_id: str | None = None, symbol: str | None = None, **kwargs):
        self.user_id = user_id
        self.symbol = symbol
        self.extra = kwargs
        self.previous_context = {}

    def __enter__(self):
        self.previous_context = LogContext._context.copy()
        LogContext._context.update({
            'user_id': self.user_id,
            'symbol': self.symbol,
            **self.extra
        })
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        LogContext._context = self.previous_context
        return False

    @classmethod
    def get_current_context(cls) -> dict:
        """获取当前日志上下文"""
        return cls._context.copy()


# 带上下文的日志函数
def ctx_log_info(message: str, **kwargs):
    """使用上下文的 INFO 日志"""
    context = LogContext.get_current_context()
    context.update(kwargs)
    get_trading_logger().info(message, **context)


def ctx_log_warning(message: str, **kwargs):
    """使用上下文的 WARNING 日志"""
    context = LogContext.get_current_context()
    context.update(kwargs)
    get_trading_logger().warning(message, **context)


def ctx_log_error(message: str, **kwargs):
    """使用上下文的 ERROR 日志"""
    context = LogContext.get_current_context()
    context.update(kwargs)
    get_trading_logger().error(message, **context)
