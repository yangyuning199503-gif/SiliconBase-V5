#!/usr/bin/env python3
"""
DistributionController — 分发控制器
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
职责：桥接 ContentStrategyEngine 与 PlatformDispatcher，
      实现"质量门禁 → 平台适配 → 多平台分发 → 记忆记录"完整链路。

设计约束：
  - 全 async
  - 异常内部捕获，不阻塞主循环
  - 分发结果持久化到执行记忆（MemoryService.save_execution_record）
"""

import json
from typing import Any

from core.logger import logger

try:
    from core.strategy.content_strategy_engine import ContentStrategyEngine
    _CSE_AVAILABLE = True
except ImportError:
    _CSE_AVAILABLE = False
    ContentStrategyEngine = None

try:
    from core.platform_dispatcher.dispatcher import PlatformDispatcher
    _PD_AVAILABLE = True
except ImportError:
    _PD_AVAILABLE = False
    PlatformDispatcher = None

try:
    from core.memory.memory_schema import MemoryMetadata
    from core.memory.memory_service import get_memory_service
    _MEMORY_AVAILABLE = True
except ImportError:
    _MEMORY_AVAILABLE = False
    get_memory_service = None
    MemoryMetadata = None


class DistributionController:
    """
    分发控制器 —— 策略性分发的统一入口。
    """

    def __init__(self, enabled_platforms: list[str] | None = None) -> None:
        """
        Args:
            enabled_platforms: 启用的平台列表，None 则从配置读取
        """
        self.enabled_platforms = enabled_platforms
        self._engine: ContentStrategyEngine | None = None
        self._dispatcher: PlatformDispatcher | None = None

    async def _get_engine(self) -> ContentStrategyEngine | None:
        if self._engine is None and _CSE_AVAILABLE:
            self._engine = ContentStrategyEngine()
        return self._engine

    async def _get_dispatcher(self) -> PlatformDispatcher | None:
        if self._dispatcher is None and _PD_AVAILABLE:
            platforms = self.enabled_platforms
            if platforms is None:
                from core.config import config
                platforms = config.get("platform_dispatcher.enabled_platforms", [])
            self._dispatcher = PlatformDispatcher(platform_names=platforms)
            await self._dispatcher.initialize()
        return self._dispatcher

    async def handle_ai_response(
        self,
        content: str,
        enabled_platforms: list[str] | None = None,
        session_id: str = "",
        user_id: str = "",
    ) -> dict[str, Any]:
        """
        处理 AI 响应：质量门禁 → 平台适配 → 分发 → 记录记忆。

        Args:
            content: AI 生成的原始内容
            enabled_platforms: 指定目标平台，None 使用初始化时的平台列表
            session_id: 会话 ID（用于记忆记录）
            user_id: 用户 ID（用于记忆记录）

        Returns:
            Dict[str, Any]: 分发结果汇总
                {
                    "success": bool,
                    "platforms": List[str],
                    "results": Dict[str, Any],
                    "adapted_contents": Dict[str, str],
                    "record_id": Optional[str],
                }
        """
        if not content:
            logger.warning("[DistributionController] 内容为空，跳过分发")
            return {"success": False, "error": "content_empty"}

        platforms = enabled_platforms or self.enabled_platforms
        if platforms is None:
            from core.config import config
            platforms = config.get("platform_dispatcher.enabled_platforms", [])

        if not platforms:
            logger.warning("[DistributionController] 无目标平台，跳过分发")
            return {"success": False, "error": "no_platforms"}

        engine = await self._get_engine()
        dispatcher = await self._get_dispatcher()

        if engine is None:
            logger.error("[DistributionController] ContentStrategyEngine 不可用")
            return {"success": False, "error": "engine_unavailable"}

        if dispatcher is None:
            logger.error("[DistributionController] PlatformDispatcher 不可用")
            return {"success": False, "error": "dispatcher_unavailable"}

        # ── 1. 质量门禁 + 平台适配 ───────────────────────────────────────────────
        adapted_contents: dict[str, str] = {}
        passed_platforms: list[str] = []

        for platform in platforms:
            try:
                if await engine.should_distribute(content, platform):
                    adapted = await engine.adapt_message(content, platform)
                    adapted_contents[platform] = adapted
                    passed_platforms.append(platform)
                    logger.info(
                        f"[DistributionController] {platform} 通过门禁并适配完成"
                    )
                else:
                    logger.info(
                        f"[DistributionController] {platform} 未通过质量门禁，跳过"
                    )
            except Exception as e:
                logger.exception(
                    f"[DistributionController] {platform} 策略处理异常，跳过: {e}"
                )

        if not passed_platforms:
            logger.warning("[DistributionController] 所有平台均未通过质量门禁")
            return {
                "success": False,
                "error": "all_platforms_blocked",
                "platforms": platforms,
            }

        # ── 2. 多平台并发分发 ────────────────────────────────────────────────────
        try:
            dispatch_results = await dispatcher.dispatch(
                content=content,
                platforms=passed_platforms,
            )
        except Exception as e:
            logger.exception(f"[DistributionController] 分发失败: {e}")
            dispatch_results = {}

        # ── 3. 结果聚合 ──────────────────────────────────────────────────────────
        success_count = sum(
            1
            for r in dispatch_results.values()
            if isinstance(r, dict) and r.get("success")
        )
        overall_success = success_count > 0

        result_summary = {
            "success": overall_success,
            "platforms": passed_platforms,
            "results": dispatch_results,
            "adapted_contents": adapted_contents,
            "record_id": None,
        }

        # ── 4. 记录执行记忆 ──────────────────────────────────────────────────────
        if _MEMORY_AVAILABLE:
            try:
                record_id = await self._save_execution_record(
                    content=content,
                    platforms=passed_platforms,
                    dispatch_results=dispatch_results,
                    session_id=session_id,
                    user_id=user_id,
                )
                result_summary["record_id"] = record_id
            except Exception as e:
                logger.exception(
                    f"[DistributionController] 执行记忆保存失败（非阻塞）: {e}"
                )

        return result_summary

    async def _save_execution_record(
        self,
        content: str,
        platforms: list[str],
        dispatch_results: dict[str, Any],
        session_id: str,
        user_id: str,
    ) -> str | None:
        """保存分发执行记录到记忆层"""
        if MemoryMetadata is None or get_memory_service is None:
            return None

        memory_service = await get_memory_service()

        payload = {
            "type": "distribution",
            "original_content": content[:500],
            "target_platforms": platforms,
            "dispatch_results": {
                k: {
                    "success": v.get("success", False) if isinstance(v, dict) else False,
                    "error": v.get("error", "") if isinstance(v, dict) else str(v),
                }
                for k, v in dispatch_results.items()
            },
        }
        payload_json = json.dumps(payload, ensure_ascii=False)

        metadata = MemoryMetadata(
            user_id=user_id or "anonymous",
            source="tool_execution",
            content_type="json",
            payload_summary=f"内容分发到 {', '.join(platforms)}",
            raw_payload=payload_json,
            session_id=session_id,
            tool_id="distribution_controller",
        )

        return await memory_service.save_execution_record(payload_json, metadata)

    async def close(self) -> None:
        """释放资源，关闭 Dispatcher"""
        if self._dispatcher:
            try:
                await self._dispatcher.close()
            except Exception as e:
                logger.exception(
                    f"[DistributionController] 关闭 dispatcher 失败: {e}"
                )
            finally:
                self._dispatcher = None


# ═══════════════════════════════════════════════════════════════════════════════
# 便捷函数：单次分发入口
# ═══════════════════════════════════════════════════════════════════════════════

async def handle_ai_response(
    content: str,
    enabled_platforms: list[str] | None = None,
    session_id: str = "",
    user_id: str = "",
) -> dict[str, Any]:
    """
    单次分发便捷入口。

    使用示例：
        result = await handle_ai_response("Hello World", ["discord", "telegram"])
    """
    controller = DistributionController(enabled_platforms=enabled_platforms)
    try:
        return await controller.handle_ai_response(
            content=content,
            enabled_platforms=enabled_platforms,
            session_id=session_id,
            user_id=user_id,
        )
    finally:
        await controller.close()
