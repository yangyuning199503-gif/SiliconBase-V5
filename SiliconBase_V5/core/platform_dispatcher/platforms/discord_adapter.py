#!/usr/bin/env python3
"""
PlatformDispatcher — Discord 适配器
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SDK: discord.py v2.x（原生 async/await）
职责：通过 Webhook 或 Bot Token 发送消息到 Discord 频道。
约束：
  - 全 async 接口
  - 优先使用 Webhook（轻量、无需维护 Gateway 连接）
  - 异常直接向上抛出
"""

from typing import Any

from core.logger import logger
from core.platform_dispatcher.interfaces import PlatformAdapter


class DiscordAdapter(PlatformAdapter):
    """
    Discord 平台适配器

    支持两种认证方式（按优先级）：
    1. Webhook URL — 推荐，无需 Bot 权限，仅发消息
    2. Bot Token + Channel ID — 需要创建 Discord Bot 并加入服务器

    config 示例：
        {
            "webhook_url": "https://discord.com/api/webhooks/...",
            # 或
            "bot_token": "MTAx...",
            "channel_id": 1234567890123456789,
        }
    """

    def __init__(self, name: str, config: dict[str, Any]) -> None:
        super().__init__(name=name, config=config)
        self._webhook_url: str | None = config.get("webhook_url")
        self._bot_token: str | None = config.get("bot_token")
        self._channel_id: int | None = config.get("channel_id")
        self._client: Any | None = None

    async def send_message(self, content: str, **kwargs) -> dict[str, Any]:
        """
        发送消息到 Discord

        Args:
            content: 消息正文（支持 Markdown 子集）
            **kwargs: 可选透传参数
                - username: Webhook 显示用户名（仅 Webhook 模式）
                - avatar_url: Webhook 头像 URL（仅 Webhook 模式）

        Returns:
            {"platform": "discord", "success": bool, "message_id": str|None, "error": str|None}
        """
        try:
            if self._webhook_url:
                return await self._send_via_webhook(content, **kwargs)
            elif self._bot_token and self._channel_id:
                return await self._send_via_bot(content, **kwargs)
            else:
                raise RuntimeError(
                    "Discord 配置不完整：需要 webhook_url 或 bot_token+channel_id"
                )
        except Exception as e:
            logger.exception(f"[DiscordAdapter] 发送失败: {e}")
            raise

    async def _send_via_webhook(
        self, content: str, **kwargs
    ) -> dict[str, Any]:
        """通过 Discord Webhook 发送消息（HTTP，无需 discord.py 库）"""
        import aiohttp

        payload = {
            "content": content,
            "username": kwargs.get("username", "布道师 AI"),
            "avatar_url": kwargs.get(
                "avatar_url",
                "https://cdn.discordapp.com/embed/avatars/0.png",
            ),
        }

        async with aiohttp.ClientSession() as session, session.post(
            self._webhook_url,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            if resp.status in (200, 204):
                # Webhook 成功时通常不返回 message_id
                return {
                    "platform": "discord",
                    "success": True,
                    "message_id": None,
                    "error": None,
                }
            else:
                text = await resp.text()
                raise RuntimeError(
                    f"Discord Webhook 返回 {resp.status}: {text[:200]}"
                )

    async def _send_via_bot(self, content: str, **kwargs) -> dict[str, Any]:
        """通过 Discord Bot Token 发送消息（需要 discord.py）"""
        try:
            import discord
        except ImportError as e:
            raise RuntimeError(
                "discord.py 未安装，请运行: pip install discord.py"
            ) from e

        # 延迟初始化 discord.Client
        if self._client is None:
            intents = discord.Intents.default()
            intents.message_content = True
            self._client = discord.Client(intents=intents)

        # discord.py v2.x 的 Client 启动是 async 的
        # 这里使用轻量的 HTTP 方式直接调用 Channel.send，避免维护 Gateway
        import aiohttp

        headers = {
            "Authorization": f"Bot {self._bot_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "content": content,
        }

        url = f"https://discord.com/api/v10/channels/{self._channel_id}/messages"

        async with aiohttp.ClientSession(headers=headers) as session, session.post(
            url,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            data = await resp.json()
            if resp.status in (200, 201):
                return {
                    "platform": "discord",
                    "success": True,
                    "message_id": str(data.get("id")),
                    "error": None,
                }
            else:
                raise RuntimeError(
                    f"Discord API 返回 {resp.status}: {data}"
                )

    async def health_check(self) -> bool:
        """验证 Discord 配置是否可用"""
        try:
            if self._webhook_url:
                import aiohttp
                async with aiohttp.ClientSession() as session, session.get(
                    self._webhook_url,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    # Webhook GET 会返回 200 和 Webhook 信息
                    return resp.status == 200
            elif self._bot_token:
                import aiohttp
                headers = {"Authorization": f"Bot {self._bot_token}"}
                async with aiohttp.ClientSession(headers=headers) as session, session.get(
                    "https://discord.com/api/v10/users/@me",
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    return resp.status == 200
            return False
        except Exception as e:
            logger.exception(f"[DiscordAdapter] health_check 失败: {e}")
            return False

    async def close(self) -> None:
        """关闭 discord.Client（如果已创建）"""
        if self._client is not None:
            try:
                await self._client.close()
            except Exception as e:
                logger.warning(f"[DiscordAdapter] 关闭 client 时忽略异常: {e}")
            finally:
                self._client = None
