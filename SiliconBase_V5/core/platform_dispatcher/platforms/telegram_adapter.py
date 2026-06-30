#!/usr/bin/env python3
"""
PlatformDispatcher — Telegram 适配器
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SDK: python-telegram-bot v20+（原生 async/await）
职责：通过 Bot Token 发送消息到 Telegram 频道/群组/用户。
约束：
  - 全 async 接口
  - 直接使用 telegram.Bot 的异步 HTTP API，无需 Application/Updater
  - 异常直接向上抛出
"""

from typing import Any

from core.logger import logger
from core.platform_dispatcher.interfaces import PlatformAdapter


class TelegramAdapter(PlatformAdapter):
    """
    Telegram 平台适配器

    通过 Bot Token 调用 Telegram Bot API 发送消息。
    支持 MarkdownV2 / HTML 解析模式。

    config 示例：
        {
            "bot_token": "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
            "chat_id": "-1001234567890",   # 频道/群组 ID，或用户 ID
            "parse_mode": "MarkdownV2",    # 可选: MarkdownV2 / HTML / None
        }
    """

    def __init__(self, name: str, config: dict[str, Any]) -> None:
        super().__init__(name=name, config=config)
        self._bot_token: str | None = config.get("bot_token")
        self._chat_id: str | None = config.get("chat_id")
        self._parse_mode: str | None = config.get("parse_mode", "MarkdownV2")
        self._bot: Any | None = None

    def _get_bot(self) -> Any:
        """延迟初始化 telegram.Bot"""
        if self._bot is None:
            try:
                from telegram import Bot
            except ImportError as e:
                raise RuntimeError(
                    "python-telegram-bot 未安装，"
                    "请运行: pip install python-telegram-bot>=20.0"
                ) from e

            if not self._bot_token:
                raise RuntimeError("Telegram 配置缺少 bot_token")

            self._bot = Bot(token=self._bot_token)
        return self._bot

    async def send_message(self, content: str, **kwargs) -> dict[str, Any]:
        """
        发送消息到 Telegram

        Args:
            content: 消息正文
            **kwargs: 可选透传参数
                - chat_id: 覆盖默认 chat_id
                - parse_mode: 覆盖默认 parse_mode
                - disable_notification: 是否静默发送
                - reply_to_message_id: 回复某条消息

        Returns:
            {"platform": "telegram", "success": bool, "message_id": str|None, "error": str|None}
        """
        try:
            bot = self._get_bot()
            chat_id = kwargs.get("chat_id", self._chat_id)
            if not chat_id:
                raise RuntimeError("Telegram 配置缺少 chat_id")

            parse_mode = kwargs.get("parse_mode", self._parse_mode)
            disable_notification = kwargs.get("disable_notification", False)
            reply_to_message_id = kwargs.get("reply_to_message_id")

            # python-telegram-bot v20+ 的 send_message 是 async
            message = await bot.send_message(
                chat_id=chat_id,
                text=content,
                parse_mode=parse_mode,
                disable_notification=disable_notification,
                reply_to_message_id=reply_to_message_id,
            )

            return {
                "platform": "telegram",
                "success": True,
                "message_id": str(message.message_id),
                "error": None,
            }
        except Exception as e:
            logger.exception(f"[TelegramAdapter] 发送失败: {e}")
            raise

    async def health_check(self) -> bool:
        """验证 Bot Token 是否有效"""
        try:
            bot = self._get_bot()
            me = await bot.get_me()
            return me is not None and me.id is not None
        except Exception as e:
            logger.exception(f"[TelegramAdapter] health_check 失败: {e}")
            return False

    async def close(self) -> None:
        """关闭 Bot 的 HTTP 会话"""
        if self._bot is not None:
            try:
                await self._bot.shutdown()
            except Exception as e:
                logger.warning(f"[TelegramAdapter] 关闭 bot 时忽略异常: {e}")
            finally:
                self._bot = None
