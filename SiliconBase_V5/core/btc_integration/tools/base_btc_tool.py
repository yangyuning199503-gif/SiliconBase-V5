#!/usr/bin/env python3
"""
BTC工具基类
适配V5 BaseTool规范，封装BTCSystemClient调用
"""

from typing import Any

from core.btc_integration.btc_system_client import BTCSystemClient, get_btc_system_client
from core.btc_integration.event_bus import EventPriority, EventType, TradingEvent, event_bus
from core.logger import logger
from core.tool.base_tool import BaseTool


class BaseBTCTool(BaseTool):
    """
    BTC工具基类

    封装BTCSystemClient的调用，提供统一的错误处理和结果格式化
    【新增】自动将关键结果emit到EventBus，让AI和前端可观测
    """

    tool_owner: str = "platform"  # 平台级工具
    category: str = "trading"     # 工具分类
    telemetry_enabled: bool = True  # 是否启用遥测发射

    def __init__(self):
        super().__init__()
        self.tool_id = self.__class__.__name__
        self.name = getattr(self, 'name', self.__class__.__name__)
        self._client: BTCSystemClient | None = None

    @property
    def client(self) -> BTCSystemClient:
        """获取或创建BTC客户端"""
        if self._client is None:
            self._client = get_btc_system_client()
        return self._client

    def _emit_to_eventbus(
        self,
        event_type: EventType,
        data: dict[str, Any],
        priority: EventPriority = EventPriority.NORMAL,
        symbol: str | None = None
    ):
        """
        发射事件到EventBus（AI可观测层）

        子类可在关键决策点调用此方法显式emit事件。
        """
        if not self.telemetry_enabled:
            return
        try:
            event = TradingEvent(
                event_type=event_type,
                data=data,
                source=self.__class__.__name__,
                priority=priority,
                symbol=symbol,
            )
            event_bus.publish(event)
        except Exception as e:
            logger.debug(f"[BaseBTCTool] emit失败（非关键）: {e}")

    def _format_success(self, data: dict[str, Any], message: str = "") -> dict[str, Any]:
        """格式化成功返回，并自动emit STRATEGY_SIGNAL"""
        result = {
            "success": True,
            "error_code": "",
            "error_message": "",
            "user_message": message,
            "data": data
        }
        # 自动发射成功事件（AI可观测）
        if self.telemetry_enabled:
            self._emit_to_eventbus(
                event_type=EventType.STRATEGY_SIGNAL,
                data={
                    "tool_id": getattr(self, "tool_id", "unknown"),
                    "action": "success",
                    "result_summary": message[:100],
                    "data_keys": list(data.keys()) if data else [],
                },
                priority=EventPriority.NORMAL,
                symbol=data.get("symbol") if isinstance(data, dict) else None,
            )
        return result

    def _format_error(self, error_code: str, error_message: str, user_message: str = "") -> dict[str, Any]:
        """格式化错误返回，并自动emit SYSTEM_ERROR"""
        result = {
            "success": False,
            "error_code": error_code,
            "error_message": error_message,
            "user_message": user_message or error_message,
            "data": None
        }
        # 自动发射错误事件（AI可观测）
        if self.telemetry_enabled:
            self._emit_to_eventbus(
                event_type=EventType.SYSTEM_ERROR,
                data={
                    "tool_id": getattr(self, "tool_id", "unknown"),
                    "error_code": error_code,
                    "error_message": error_message[:200],
                },
                priority=EventPriority.HIGH,
            )
        return result
