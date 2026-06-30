#!/usr/bin/env python3
"""
PlatformDispatcher — 统一调度器
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
职责：并发分发消息到多个平台，支持失败重试与异常上报。
约束：
  - 全 async，禁止同步阻塞
  - 异常不静默，logger.exception 记录后向上抛出
  - 通过 async_event_bus 订阅 AI 回复事件
"""

import asyncio
from typing import Any

from core.logger import logger
from core.platform_dispatcher.interfaces import PlatformAdapter
from core.platform_dispatcher.registry import PlatformRegistry


class PlatformDispatcher:
    """
    平台消息统一调度器

    使用示例：
        dispatcher = PlatformDispatcher(["discord", "telegram"])
        await dispatcher.initialize()
        results = await dispatcher.dispatch("Hello World")
        await dispatcher.close()
    """

    DEFAULT_RETRY_TIMES = 2
    DEFAULT_RETRY_DELAY = 1.0

    def __init__(
        self,
        platform_names: list[str] | None = None,
        configs: dict[str, dict[str, Any]] | None = None,
        retry_times: int = DEFAULT_RETRY_TIMES,
        retry_delay: float = DEFAULT_RETRY_DELAY,
    ) -> None:
        """
        Args:
            platform_names: 启用的平台列表，None 表示全部已注册平台
            configs: 各平台配置字典，key 为平台名，value 为配置 dict
            retry_times: 单平台失败重试次数（默认 2）
            retry_delay: 重试间隔秒数（默认 1.0）
        """
        self.platform_names = platform_names or PlatformRegistry.list_platforms()
        self.configs = configs or {}
        self.retry_times = retry_times
        self.retry_delay = retry_delay

        self._adapters: dict[str, PlatformAdapter] = {}
        self._initialized = False

    async def initialize(self) -> None:
        """初始化所有平台适配器实例"""
        if self._initialized:
            return

        for name in self.platform_names:
            adapter_class = PlatformRegistry.get(name)
            if adapter_class is None:
                logger.warning(f"[PlatformDispatcher] 平台 '{name}' 未注册，跳过")
                continue

            cfg = self.configs.get(name, {})
            try:
                adapter = adapter_class(name=name, config=cfg)
                self._adapters[name] = adapter
                logger.info(f"[PlatformDispatcher] 初始化适配器: {name}")
            except Exception:
                logger.exception(
                    f"[PlatformDispatcher] 适配器 {name} 初始化失败"
                )
                raise

        self._initialized = True

    async def dispatch(
        self,
        content: str,
        platforms: list[str] | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """
        并发分发消息到多个平台

        Args:
            content: 消息正文
            platforms: 指定目标平台，None 表示全部已初始化平台
            **kwargs: 透传给各平台 send_message 的额外参数

        Returns:
            Dict[str, Any]: 各平台发送结果
                {
                    "discord": {"success": True, "message_id": "123"},
                    "telegram": {"success": False, "error": "..."},
                }
        """
        if not self._initialized:
            raise RuntimeError(
                "Dispatcher 未初始化，请先调用 initialize()"
            )

        targets = platforms or list(self._adapters.keys())
        if not targets:
            logger.warning("[PlatformDispatcher] 没有可用的目标平台")
            return {}

        tasks = [
            self._send_with_retry(self._adapters[name], content, **kwargs)
            for name in targets
            if name in self._adapters
        ]

        # 并发执行，异常由 _send_with_retry 内部捕获并记录
        results_list = await asyncio.gather(*tasks, return_exceptions=True)

        results: dict[str, Any] = {}
        for name, res in zip(targets, results_list, strict=False):
            if isinstance(res, Exception):
                logger.exception(
                    f"[PlatformDispatcher] 平台 {name} 分发异常: {res}"
                )
                results[name] = {
                    "platform": name,
                    "success": False,
                    "error": str(res),
                }
            else:
                results[name] = res

        success_count = sum(1 for r in results.values() if r.get("success"))
        logger.info(
            f"[PlatformDispatcher] 分发完成: {success_count}/{len(targets)} 成功"
        )
        return results

    async def _send_with_retry(
        self,
        adapter: PlatformAdapter,
        content: str,
        **kwargs,
    ) -> dict[str, Any]:
        """
        带重试的发送逻辑

        失败时会按 retry_times / retry_delay 进行指数退避重试。
        最后一次失败仍抛出异常，由 dispatch 的 gather 统一处理。
        """
        last_error: Exception | None = None

        for attempt in range(self.retry_times + 1):
            try:
                result = await adapter.send_message(content, **kwargs)
                if result.get("success"):
                    return result
                # 如果 adapter 返回 success=False 但没有抛异常，也视为失败
                last_error = RuntimeError(
                    result.get("error", "send_message 返回失败")
                )
            except Exception as e:
                last_error = e
                logger.exception(
                    f"[PlatformDispatcher] {adapter.name} 发送失败 "
                    f"(attempt {attempt + 1}/{self.retry_times + 1}): {e}"
                )

            if attempt < self.retry_times:
                delay = self.retry_delay * (2 ** attempt)
                logger.info(
                    f"[PlatformDispatcher] {adapter.name} 将在 {delay:.1f}s 后重试"
                )
                await asyncio.sleep(delay)

        # 所有重试耗尽
        raise last_error or RuntimeError(f"{adapter.name} 发送失败且重试耗尽")

    async def health_check_all(self) -> dict[str, bool]:
        """并发检查所有已初始化平台的健康状态"""
        if not self._initialized:
            raise RuntimeError("Dispatcher 未初始化")

        async def _check(name: str, adapter: PlatformAdapter) -> tuple:
            try:
                ok = await adapter.health_check()
                return name, ok
            except Exception as e:
                logger.exception(
                    f"[PlatformDispatcher] {name} health_check 异常: {e}"
                )
                return name, False

        results = await asyncio.gather(
            *[_check(n, a) for n, a in self._adapters.items()]
        )
        return dict(results)

    async def close(self) -> None:
        """关闭所有适配器，释放资源"""
        for name, adapter in self._adapters.items():
            try:
                await adapter.close()
                logger.info(f"[PlatformDispatcher] 已关闭适配器: {name}")
            except Exception as e:
                logger.exception(
                    f"[PlatformDispatcher] 关闭适配器 {name} 失败: {e}"
                )
        self._adapters.clear()
        self._initialized = False


# ═══════════════════════════════════════════════════════════════════════════════
# 与 async_event_bus 的集成：自动订阅 AI 回复事件
# ═══════════════════════════════════════════════════════════════════════════════

async def _on_ai_response(event_type: str, data: dict[str, Any]) -> None:
    """
    事件总线回调：当 AI 产生最终回复时，自动分发到多平台

    订阅的事件类型："ai.response.final"
    期望 data 结构：
        {
            "content": str,           # 回复正文
            "platforms": [str],       # 可选，指定目标平台
            "session_id": str,        # 可选
            "user_id": str,           # 可选
        }
    """
    from core.config import config

    content = data.get("content")
    if not content:
        logger.warning("[PlatformDispatcher] 收到 ai.response.final 但 content 为空")
        return

    # 从配置读取默认启用的平台
    enabled = config.get("platform_dispatcher.enabled_platforms", [])
    if not enabled:
        return

    dispatcher = PlatformDispatcher(platform_names=enabled)
    try:
        await dispatcher.initialize()
        await dispatcher.dispatch(
            content=content,
            platforms=data.get("platforms"),
        )
    except Exception as e:
        logger.exception(f"[PlatformDispatcher] 事件分发失败: {e}")
    finally:
        await dispatcher.close()


def register_event_bus_handlers() -> None:
    """
    将 PlatformDispatcher 注册到 AsyncEventBus

    在应用启动时调用一次即可。
    """
    try:
        from core.sync.async_event_bus import get_event_bus
        bus = get_event_bus()
        bus.subscribe("ai.response.final", _on_ai_response)
        logger.info("[PlatformDispatcher] 已注册 ai.response.final 事件监听器")
    except Exception as e:
        logger.exception(f"[PlatformDispatcher] 注册事件监听器失败: {e}")
