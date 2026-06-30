#!/usr/bin/env python3
"""
PlatformDispatcher — 多平台消息分发模块
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
全异步、可扩展的多平台消息分发基础设施。

使用示例：
    from core.platform_dispatcher import PlatformDispatcher, PlatformRegistry
    from core.platform_dispatcher.platforms.discord_adapter import DiscordAdapter
    from core.platform_dispatcher.platforms.telegram_adapter import TelegramAdapter

    # 注册平台
    PlatformRegistry.register("discord", DiscordAdapter)
    PlatformRegistry.register("telegram", TelegramAdapter)

    # 初始化并分发
    dispatcher = PlatformDispatcher(
        platform_names=["discord", "telegram"],
        configs={
            "discord": {"webhook_url": "https://..."},
            "telegram": {"bot_token": "123:ABC", "chat_id": "-100..."},
        }
    )
    await dispatcher.initialize()
    results = await dispatcher.dispatch("Hello from SiliconBase!")
    await dispatcher.close()
"""

from core.platform_dispatcher.dispatcher import (
    PlatformDispatcher,
    register_event_bus_handlers,
)
from core.platform_dispatcher.interfaces import PlatformAdapter
from core.platform_dispatcher.registry import PlatformRegistry

__all__ = [
    "PlatformAdapter",
    "PlatformRegistry",
    "PlatformDispatcher",
    "register_event_bus_handlers",
]
