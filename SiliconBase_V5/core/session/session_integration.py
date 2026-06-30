#!/usr/bin/env python3
"""
SessionIntegration - SessionStorage 全链路异步化封装
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
从 agent_loop.py 抽取的 Session 消息存储逻辑，提供同步/异步双入口。

职责：
- 获取或创建 session（UUID 校验、自动回退）
- 消息存储（带重试、指数退避）
- 会话完成归档（标题生成、状态更新）

设计约束：
1. 所有阻塞 I/O 操作均提供 async 版本。
2. SessionManager 不可用时静默降级，禁止抛异常到主循环。
3. 异步版使用 asyncio.to_thread / run_in_executor 桥接同步 DB 调用。
"""

import asyncio
from typing import Any

from core.logger import logger

try:
    from core.session.session_manager import Session, SessionManager, get_session_manager
    from core.utils.session_utils import generate_session_title
    SESSION_MANAGER_AVAILABLE = True
except ImportError as e:
    SESSION_MANAGER_AVAILABLE = False
    logger.error(f"[SessionIntegration] SessionManager 导入失败: {e}")
    SessionManager = Any
    Session = Any


class SessionIntegration:
    """Session 全链路管理器（纯异步接口）"""

    def __init__(self):
        self._session_manager = None

    def _get_manager(self) -> SessionManager | None:
        if not SESSION_MANAGER_AVAILABLE:
            return None
        if self._session_manager is None:
            self._session_manager = get_session_manager()
        return self._session_manager

    async def get_or_create_session(
        self,
        user_id: str,
        session_id: str,
        mode: str = "daily",
        title: str | None = None,
    ) -> Session | None:
        """异步版：直接调用 SessionManager 原生异步方法。"""
        manager = self._get_manager()
        if manager is None:
            return None
        try:
            existing = await manager.get_session(session_id)
            if existing:
                return existing
            return await manager.create_session(
                user_id=user_id,
                title=title or "新对话",
                mode=mode,
                initial_context={"source": "session_integration", "requested_session_id": session_id},
            )
        except Exception as e:
            logger.error(f"[SessionIntegration] 异步 get_or_create_session 失败: {e}")
            return None

    # ═════════════════════════════════════════════════════════════════════════════
    # 消息存储（带重试）
    # ═════════════════════════════════════════════════════════════════════════════
    async def save_messages(
        self,
        session_id: str,
        role: str,
        content: str,
        **kwargs,
    ) -> str | None:
        """异步版：直接调用 SessionManager 原生异步方法。"""
        manager = self._get_manager()
        if manager is None:
            return None
        max_retries = 3
        retry_delay = 0.1
        for attempt in range(max_retries):
            try:
                message_id = await manager.add_message(
                    session_id=session_id,
                    role=role,
                    content=content,
                    **kwargs,
                )
                logger.debug(f"[SessionIntegration] 消息异步存储成功: {message_id}, role={role}")
                return message_id
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(f"[SessionIntegration] 消息异步存储失败(尝试{attempt + 1}/{max_retries}): {e}")
                    await asyncio.sleep(retry_delay * (attempt + 1))
                else:
                    logger.error(f"[SessionIntegration] 消息异步存储最终失败: {e}", exc_info=True)
        return None

    # ═════════════════════════════════════════════════════════════════════════════
    # 会话完成归档
    # ═════════════════════════════════════════════════════════════════════════════
    async def finalize_session(
        self,
        session: Session,
        user_instruction: str,
        final_response: str | None = None,
    ) -> bool:
        """异步版：直接调用 SessionManager 原生异步方法。"""
        manager = self._get_manager()
        if manager is None or session is None:
            return False
        try:
            updates = {"status": "archived"}
            if not session.title or session.title == "新对话":
                if final_response and len(final_response) > 10:
                    reply_summary = final_response[:50].replace("\n", " ")
                    updates["title"] = generate_session_title(
                        f"{user_instruction[:20]} - {reply_summary}", max_length=50
                    )
                else:
                    updates["title"] = generate_session_title(user_instruction)
            # update_session 仍为 sync，但无 DB 操作仅内存更新时可接受；
            # 若需原生 async，后续可添加 update_session_async
            await manager.update_session(session.id, updates)
            logger.info(
                f"[SessionIntegration] Session 异步标记为完成: {session.id}, "
                f"title={updates.get('title', session.title)}"
            )
            return True
        except Exception as e:
            logger.error(f"[SessionIntegration] 异步更新 session 完成状态失败: {e}", exc_info=True)
            return False


    # ═════════════════════════════════════════════════════════════════════════════
    # AI 响应存储 + MemoryAutoTrigger 触发
    # ═════════════════════════════════════════════════════════════════════════════
    async def store_and_trigger_ai_response(
        self,
        session: Any,
        actual_user_id: str,
        response: str,
        working_memory: Any,
        loop_state: Any,
        session_id: str,
    ) -> str | None:
        """异步版：存储 AI 响应到 Session 并触发 MemoryAutoTrigger。

        返回 message_id 或 None（存储失败）。
        任何异常都会被捕获并记录为 ERROR，不会抛出到调用方。
        """
        try:
            from core.utils.text_parser import extract_thinking_from_response, extract_tool_calls_from_response
        except Exception as e:
            logger.error(f"[SessionIntegration] 导入 text_parser 失败: {e}")
            return None

        ai_message_id = None
        try:
            logger.info(f"[SessionIntegration] AI回复存储开始: session={session.id}, user={actual_user_id}")

            thinking_content = extract_thinking_from_response(response)
            tool_calls_info = extract_tool_calls_from_response(response)
            thinking_for_trigger = getattr(working_memory, 'last_thinking', None)
            tool_calls_for_trigger = getattr(working_memory, 'last_tool_calls', None)

            round_count = getattr(loop_state, 'round_count', 0) if loop_state else 0
            ai_message_metadata = {
                "source": "agent_loop",
                "round": round_count,
                "model_provider": getattr(working_memory, 'current_model_provider', None),
                "model_name": getattr(working_memory, 'current_model_name', None),
                "intent_type": None,
                "target_tool": None,
            }

            ai_message_id = await self.save_messages(
                session_id=session.id,
                role="assistant",
                content=response,
                thinking=thinking_content,
                tool_calls=tool_calls_info,
                metadata=ai_message_metadata,
            )

            if not ai_message_id:
                logger.error(f"[SessionIntegration] AI消息存储失败，无法获取message_id，session={session.id}")
                return None

            logger.info(f"[SessionIntegration] Session消息存储成功: message_id={ai_message_id}")

            try:
                from core.memory.memory_auto_trigger import MemoryAutoTrigger
                logger.info(f"[SessionIntegration] MemoryAutoTrigger触发开始: message_id={ai_message_id}")
                await MemoryAutoTrigger.on_ai_response(
                    user_id=actual_user_id,
                    session_id=session_id if session_id else f"session_{actual_user_id}",
                    response=response,
                    thinking=thinking_for_trigger,
                    tool_calls=tool_calls_for_trigger,
                    message_id=ai_message_id,
                    metadata={
                        "source": "agent_loop",
                        "round": round_count,
                        "model_provider": getattr(working_memory, 'current_model_provider', None),
                        "model_name": getattr(working_memory, 'current_model_name', None),
                    },
                )
                logger.info(f"[SessionIntegration] AI回复记忆存储成功: user={actual_user_id}, message_id={ai_message_id}")
            except Exception as trigger_error:
                logger.error(f"[SessionIntegration] MemoryAutoTrigger触发失败: {trigger_error}", exc_info=True)

        except Exception as e:
            logger.error(f"[SessionIntegration] AI回复存储/记忆触发失败: {e}", exc_info=True)

        return ai_message_id

# 全局实例
session_integration = SessionIntegration()
