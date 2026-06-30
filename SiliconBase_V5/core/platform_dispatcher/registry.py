#!/usr/bin/env python3
"""
PlatformDispatcher — 平台注册表
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
职责：管理所有平台适配器的注册与发现。
约束：
  - 线程安全（类级别锁）
  - 延迟导入，避免模块加载时触发 heavy init
"""

import threading

from core.logger import logger
from core.platform_dispatcher.interfaces import PlatformAdapter


class PlatformRegistry:
    """
    平台适配器注册表（单例模式）

    使用示例：
        from core.platform_dispatcher.registry import PlatformRegistry
        from core.platform_dispatcher.platforms.discord_adapter import DiscordAdapter

        PlatformRegistry.register("discord", DiscordAdapter)
        adapter_class = PlatformRegistry.get("discord")
    """

    _adapters: dict[str, type[PlatformAdapter]] = {}
    _lock = threading.Lock()

    @classmethod
    def register(
        cls,
        name: str,
        adapter_class: type[PlatformAdapter],
        force: bool = False,
    ) -> None:
        """
        注册平台适配器

        Args:
            name: 平台标识名
            adapter_class: 适配器类（必须继承 PlatformAdapter）
            force: 是否强制覆盖已有注册

        Raises:
            ValueError: 名称已被注册且 force=False
            TypeError: adapter_class 不是 PlatformAdapter 的子类
        """
        if not issubclass(adapter_class, PlatformAdapter):
            raise TypeError(
                f"adapter_class 必须继承 PlatformAdapter，"
                f"got {adapter_class.__name__}"
            )

        with cls._lock:
            if name in cls._adapters and not force:
                raise ValueError(
                    f"平台 '{name}' 已注册为 {cls._adapters[name].__name__}，"
                    f"使用 force=True 覆盖"
                )
            cls._adapters[name] = adapter_class
            logger.info(f"[PlatformRegistry] 注册平台适配器: {name}")

    @classmethod
    def get(cls, name: str) -> type[PlatformAdapter] | None:
        """
        获取已注册的适配器类

        Args:
            name: 平台标识名

        Returns:
            Type[PlatformAdapter] 或 None
        """
        with cls._lock:
            return cls._adapters.get(name)

    @classmethod
    def list_platforms(cls) -> list[str]:
        """返回所有已注册的平台名称列表"""
        with cls._lock:
            return list(cls._adapters.keys())

    @classmethod
    def unregister(cls, name: str) -> bool:
        """
        注销平台适配器

        Returns:
            bool: 是否成功移除
        """
        with cls._lock:
            if name in cls._adapters:
                del cls._adapters[name]
                logger.info(f"[PlatformRegistry] 注销平台适配器: {name}")
                return True
            return False

    @classmethod
    def clear(cls) -> None:
        """清空所有注册（主要用于测试）"""
        with cls._lock:
            cls._adapters.clear()
            logger.info("[PlatformRegistry] 已清空所有注册")
