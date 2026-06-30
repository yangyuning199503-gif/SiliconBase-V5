#!/usr/bin/env python3
"""
PlatformDispatcher — 平台适配器抽象接口
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
职责：定义所有多平台分发适配器必须实现的契约。
约束：
  - 全 async 接口，禁止同步阻塞
  - 异常必须向上抛出，禁止静默吞掉
"""

from abc import ABC, abstractmethod
from typing import Any


class PlatformAdapter(ABC):
    """
    平台适配器抽象基类

    所有外部平台（Discord、Telegram、Twitter 等）的适配器必须继承本类，
    并实现 send_message / health_check / close 三个核心方法。
    """

    def __init__(self, name: str, config: dict[str, Any]) -> None:
        """
        Args:
            name: 平台标识名（如 "discord"、"telegram"）
            config: 平台配置字典（Token、Webhook URL 等）
        """
        self.name = name
        self.config = config

    @abstractmethod
    async def send_message(self, content: str, **kwargs) -> dict[str, Any]:
        """
        发送消息到目标平台

        Args:
            content: 消息正文（纯文本或 Markdown）
            **kwargs: 平台特定参数（如 channel_id、chat_id、reply_to 等）

        Returns:
            Dict: 发送结果元数据
                {
                    "platform": str,
                    "success": bool,
                    "message_id": Optional[str],
                    "error": Optional[str],
                }

        Raises:
            任何底层异常必须直接抛出，由 Dispatcher 的 retry 机制处理
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """
        检查平台连接/认证是否可用

        Returns:
            bool: True 表示健康，False 表示不可用
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """
        关闭连接并释放资源

        在 Dispatcher 生命周期结束或平台被注销时调用。
        必须幂等（多次调用不报错）。
        """
        ...
