#!/usr/bin/env python3
"""
ToolHook - 工具调用后处理钩子（完整版）
V5/V6 融合重构 - Phase 3b 补全

职责：完整封装工具调用后的后处理逻辑，统一同步/异步双版本。
包含：
- 基础后处理（execution_history、state、tool_result 事件、chat_history 反馈、状态标记）
- Agent-5 经验值记录
- MemoryTrigger 自动存储
- 阶段锚点（PhaseAnchor）
- 自动截图验证（AutoVerify）
- 三省六部流程透视镜（tool_node_update）
- AI 自然语言 reply 事件
- 演示学习系统失败暂停（ProcedureLearning）

设计约束：
1. 不接管控制流（不直接 break/return），只更新上下文状态和发送事件。
2. `tool_result` / `tool_node_update` / `reply` / `experience_gained` / `task_breakdown`
   等事件格式必须与旧版 100% 兼容。
3. 异步入口中所有阻塞调用均使用 `asyncio.get_running_loop().run_in_executor()` 包装。
"""

import asyncio
import json
import time
from typing import Any

from core.logger import logger

try:
    from core.utils.common import is_critical_step
except ImportError:
    def is_critical_step(tool_name: str, critical_tools=None) -> bool:
        return False

try:
    from core.agent.agent_loop_hooks import HookContext
except ImportError:
    HookContext = Any

try:
    from core.consciousness.tool_feedback_enhanced import report_reaction
    _REPORT_REACTION_AVAILABLE = True
except ImportError:
    _REPORT_REACTION_AVAILABLE = False

try:
    from core.config import config
    USE_ENHANCED_FILTER = getattr(config, 'USE_ENHANCED_FILTER', False)
except Exception as e:
    import logging
    logging.getLogger(__name__).error(
        f"[SILENT_FAILURE_BLOCKED] ToolHook 配置导入失败: {e}", exc_info=True
    )
    USE_ENHANCED_FILTER = False


class ToolHook:
    """工具后处理 Hook（完整版）"""

    # ═════════════════════════════════════════════════════════════════════════════
    # 统一异步入口（Phase 3：已删除旧版，所有调用走 async）
    # ═════════════════════════════════════════════════════════════════════════════
    async def after_tool(self, ctx: HookContext, tool_result: dict | None = None) -> HookContext:
        """异步入口：逻辑与同步版保持一致，阻塞调用包装在 run_in_executor 中。"""
        if ctx is None:
            return ctx

        res = tool_result or {}
        result = res.get("result", {}) if isinstance(res, dict) else {}

        working_memory = getattr(ctx, "working_memory", None)
        session_id = getattr(ctx, "session_id", "")
        extra = getattr(ctx, "extra", {}) or {}

        parsed = extra.get("parsed")
        tool_id = getattr(parsed, "target_tool", "") if parsed else ""
        tool_params = getattr(parsed, "params", {}) if parsed else {}

        loop_state = extra.get("loop_state")
        round_count = getattr(loop_state, "round_count", 0) if loop_state else 0

        execution_history = extra.get("execution_history", [])
        state = extra.get("state")
        chat_history = extra.get("chat_history")
        response = extra.get("last_response", "")
        actual_user_id = extra.get("actual_user_id", "")
        effective_task_id = extra.get("effective_task_id", "")
        precision_parsed = extra.get("precision_parsed")
        ai_reply = extra.get("ai_reply", "")
        initial_steps = extra.get("initial_steps", [])
        user_instruction = extra.get("user_instruction", "")
        proc_learning = extra.get("proc_learning_integration")
        voice_instance = extra.get("voice_instance")

        # 【零静默失败】原始工具结果必须保留，供后续排查和 LLM 感知
        if working_memory is not None and isinstance(res, dict):
            try:
                if not hasattr(working_memory, 'raw_tool_results'):
                    working_memory.raw_tool_results = []
                working_memory.raw_tool_results.append({
                    "tool": tool_id,
                    "result": res,
                    "timestamp": time.time()
                })
                # 限制大小，避免无限增长
                if len(working_memory.raw_tool_results) > 100:
                    working_memory.raw_tool_results = working_memory.raw_tool_results[-100:]
            except Exception as e:
                logger.error(f"[ToolHook] 保存原始工具结果失败: {e}", exc_info=True)

        try:
            tool_execution_time_ms = self._calc_execution_time_ms(working_memory)
            loop = asyncio.get_running_loop()

            # 1. 基础后处理（异步包装 state 和 add_tool_result）
            await self._basic_post_process_async(
                ctx=ctx,
                working_memory=working_memory,
                session_id=session_id,
                tool_id=tool_id,
                tool_params=tool_params,
                result=result,
                res=res,
                round_count=round_count,
                execution_history=execution_history,
                state=state,
                chat_history=chat_history,
                response=response,
                loop=loop,
                tool_execution_time_ms=tool_execution_time_ms,
            )

            # 2. 经验值记录（纯内存计算，无需线程池）
            await self._record_experience(
                actual_user_id,
                tool_id,
                result,
                tool_execution_time_ms,
                session_id,
            )

            # 3. MemoryTrigger
            # 【Phase 5】使用 AsyncMemory 原生异步保存
            await self._trigger_memory_async(
                actual_user_id,
                session_id,
                tool_id,
                tool_params,
                result,
                tool_execution_time_ms,
            )

            # 4. 阶段锚点
            # 【Phase 5】使用 AsyncMemory 原生异步保存
            await self._save_phase_anchor_async(
                working_memory,
                tool_id,
                result,
                actual_user_id,
                session_id,
                effective_task_id,
            )

            # 5. 自动截图验证（使用底层原生 async 接口，无需调用方重复 to_thread）
            visual_verification_result = extra.get("visual_verification_result")
            await self._auto_screenshot_verify_async(
                working_memory,
                session_id,
                tool_id,
                result,
                round_count,
                visual_verification_result,
            )

            # 6. 三省六部流程透视镜
            await self._emit_tool_node_update(
                working_memory=working_memory,
                session_id=session_id,
                tool_id=tool_id,
                result=result,
                user_instruction=user_instruction,
                initial_steps=initial_steps,
            )

            # 7. AI 自然语言 reply 事件
            await self._emit_ai_reply(
                working_memory=working_memory,
                session_id=session_id,
                chat_history=chat_history,
                precision_parsed=precision_parsed,
                parsed=parsed,
                tool_id=tool_id,
                result=result,
                ai_reply=ai_reply,
            )

            # 8. 工具反馈增强（Phase 7 从 agent_loop 抽取到 ToolHook）
            self._enhance_tool_feedback(
                tool_id=tool_id,
                result=result,
                round_count=round_count,
                user_instruction=user_instruction,
                actual_user_id=actual_user_id,
            )

            # 9. 演示学习系统失败暂停
            self._handle_procedure_learning_failure(
                working_memory=working_memory,
                session_id=session_id,
                tool_id=tool_id,
                result=result,
                proc_learning=proc_learning,
                voice_instance=voice_instance,
            )

            # 【全局自动采集】工具执行后自动更新模块状态
            from core.memory.module_state_manager import update_module_state_from_tool
            update_module_state_from_tool(tool_id, result)

            return ctx
        except Exception as e:
            # 【零静默失败】工具后处理异常必须 ERROR 级别记录，确保 AI 和开发者能看到
            logger.error(
                f"[ToolHook] after_tool 处理失败 (tool={tool_id}, session={session_id}): {e}",
                exc_info=True
            )
            # 尝试把原始结果写入 working_memory，让 LLM 至少能看到工具返回
            if working_memory is not None and isinstance(res, dict):
                try:
                    if not hasattr(working_memory, 'last_raw_tool_result'):
                        working_memory.last_raw_tool_result = {}
                    working_memory.last_raw_tool_result[tool_id] = res
                except Exception as inner_e:
                    logger.error(f"[ToolHook] 应急保存原始工具结果失败: {inner_e}", exc_info=True)
            raise

    # ═════════════════════════════════════════════════════════════════════════════
    # 内部辅助方法
    # ═════════════════════════════════════════════════════════════════════════════
    def _calc_execution_time_ms(self, working_memory: Any) -> int:
        return int(
            (time.time() - getattr(working_memory, '_tool_start_time', time.time())) * 1000
        )

    async def _basic_post_process(
        self,
        ctx: HookContext,
        working_memory: Any,
        session_id: str,
        tool_id: str,
        tool_params: dict,
        result: dict,
        res: dict,
        round_count: int,
        execution_history: list,
        state: Any,
        chat_history: list | None,
        response: str,
    ) -> None:
        # 计算工具执行耗时（后续事件和反馈需要）
        tool_execution_time_ms = self._calc_execution_time_ms(working_memory)

        # execution_history 追加
        if execution_history is not None:
            execution_history.append({
                "timestamp": time.time(),
                "tool": tool_id,
                "params": tool_params,
                "result": result,
                "success": result.get("success", False),
                "ai_response": response,
            })
            # 上限保护：避免线性累积导致 token 膨胀
            MAX_EXEC_HISTORY = 20
            if len(execution_history) > MAX_EXEC_HISTORY:
                execution_history[:] = execution_history[-MAX_EXEC_HISTORY:]

        # state 更新
        if state is not None:
            try:
                state.update_after_tool(
                    tool_id,
                    result.get("success", False),
                    result.get("user_message", "")[:30],
                )
            except Exception as e:
                logger.warning(f"[ToolHook] state.update_after_tool 失败: {e}")

        # tool_result 事件
        try:
            from core.sync.realtime_sync import get_realtime_sync_manager
            sync = get_realtime_sync_manager()
            success = result.get("success", False)
            user_message = result.get("user_message", "")
            await sync.emit_event_async("tool_result", session_id, {
                "round": round_count,
                "tool": tool_id,
                "success": success,
                "message": user_message,
                "summary": user_message[:200] if success else None,
                "data": result.get("data", {}),
                "params": tool_params,
                "error": (result.get("error") or user_message) if not success else None,
                "execution_time_ms": tool_execution_time_ms,
            })
        except Exception as e:
            logger.error(f"[ToolHook] 发送 tool_result 事件失败: {e}")

        # chat_history 基础反馈（仅当没有增强层决策时）
        if chat_history is not None and isinstance(result, dict):
            if "_feedback_decision" in result:
                # 【Phase 6 修复】使用主循环预注入的增强层过滤决策
                fd = result["_feedback_decision"]
                if fd.get("should_add_to_context", True):
                    feedback_msg = fd.get("formatted_content") or fd.get("content") or f"【工具结果】{tool_id}: {'成功' if result.get('success') else '失败'} - {result.get('user_message', '')}"
                    chat_history.append({"role": "user", "content": feedback_msg})
                    if working_memory is not None:
                        working_memory.append({
                            "role": "system",
                            "source": "tool_hook",
                            "_category": "tool_result",
                            "content": f"[工具执行结果] {feedback_msg[:200]}"
                        })
            else:
                feedback_msg = f"【工具结果】{tool_id}: {'成功' if result.get('success') else '失败'} - {result.get('user_message', '')}"
                chat_history.append({"role": "user", "content": feedback_msg})
                if working_memory is not None:
                    working_memory.append({
                        "role": "system",
                        "source": "tool_hook",
                        "_category": "tool_result",
                        "content": f"[工具执行结果] {feedback_msg[:200]}"
                    })

        # should_continue 标志
        ctx.extra["should_continue"] = res.get("should_continue", True)

        # 状态标记与 add_tool_result
        if working_memory is not None:
            working_memory.just_executed_tool = True
            working_memory.last_tool_result = result
            try:
                working_memory.add_tool_result(tool_id, result)
            except Exception as e:
                logger.warning(f"[ToolHook] add_tool_result 失败: {e}")

    async def _basic_post_process_async(
        self,
        ctx: HookContext,
        working_memory: Any,
        session_id: str,
        tool_id: str,
        tool_params: dict,
        result: dict,
        res: dict,
        round_count: int,
        execution_history: list,
        state: Any,
        chat_history: list | None,
        response: str,
        loop: asyncio.AbstractEventLoop,
        tool_execution_time_ms: int = 0,
    ) -> None:
        if execution_history is not None:
            execution_history.append({
                "timestamp": time.time(),
                "tool": tool_id,
                "params": tool_params,
                "result": result,
                "success": result.get("success", False),
                "ai_response": response,
            })
            # 上限保护：避免线性累积导致 token 膨胀
            MAX_EXEC_HISTORY = 20
            if len(execution_history) > MAX_EXEC_HISTORY:
                execution_history[:] = execution_history[-MAX_EXEC_HISTORY:]

        if state is not None:
            try:
                state.update_after_tool(
                    tool_id,
                    result.get("success", False),
                    result.get("user_message", "")[:30],
                )
            except Exception as e:
                logger.warning(f"[ToolHook-Async] state.update_after_tool 失败: {e}")

        try:
            from core.sync.realtime_sync import get_realtime_sync_manager
            sync = get_realtime_sync_manager()
            await sync.emit_event_async("tool_result", session_id, {
                "round": round_count,
                "tool": tool_id,
                "success": result.get("success", False),
                "message": result.get("user_message", ""),
                "data": result.get("data", {}),
            })
        except Exception as e:
            logger.error(f"[ToolHook-Async] 发送 tool_result 事件失败: {e}")

        if chat_history is not None and isinstance(result, dict):
            if "_feedback_decision" in result:
                # 【Phase 6 修复】使用主循环预注入的增强层过滤决策
                fd = result["_feedback_decision"]
                if fd.get("should_add_to_context", True):
                    feedback_msg = fd.get("formatted_content") or fd.get("content") or f"【工具结果】{tool_id}: {'成功' if result.get('success') else '失败'} - {result.get('user_message', '')}"
                    chat_history.append({"role": "user", "content": feedback_msg})
                    if working_memory is not None:
                        working_memory.append({
                            "role": "system",
                            "source": "tool_hook",
                            "_category": "tool_result",
                            "content": f"[工具执行结果] {feedback_msg[:200]}"
                        })
            else:
                feedback_msg = f"【工具结果】{tool_id}: {'成功' if result.get('success') else '失败'} - {result.get('user_message', '')}"
                chat_history.append({"role": "user", "content": feedback_msg})
                if working_memory is not None:
                    working_memory.append({
                        "role": "system",
                        "source": "tool_hook",
                        "_category": "tool_result",
                        "content": f"[工具执行结果] {feedback_msg[:200]}"
                    })

        ctx.extra["should_continue"] = res.get("should_continue", True)

        if working_memory is not None:
            working_memory.just_executed_tool = True
            working_memory.last_tool_result = result
            try:
                # 【修复】add_tool_result 是纯内存操作，无需 run_in_executor。
                # 在线程池中执行会导致与主循环的 working_memory 访问产生竞态。
                working_memory.add_tool_result(tool_id, result)
            except Exception as e:
                logger.warning(f"[ToolHook-Async] add_tool_result 失败: {e}")

    async def _record_experience(
        self,
        actual_user_id: str,
        tool_id: str,
        result: dict,
        tool_execution_time_ms: int,
        session_id: str,
    ) -> None:
        try:
            from core.evolution.experience_injector import get_experience_injector_v3

            experience_injector = get_experience_injector_v3()
            xp_gained = experience_injector.record_tool_experience(
                user_id=actual_user_id,
                tool_name=tool_id,
                success=result.get("success", False),
                execution_time_ms=tool_execution_time_ms,
            )

            from core.sync.realtime_sync import get_realtime_sync_manager
            sync = get_realtime_sync_manager()
            await sync.emit_event_async("experience_gained", session_id, {
                "tool": tool_id,
                "xp": xp_gained,
                "success": result.get("success", False),
                "execution_time_ms": tool_execution_time_ms,
                "user_id": actual_user_id,
            })
            logger.info(f"[ToolHook] [OK] 用户 {actual_user_id} 获得经验值: {xp_gained} XP (工具: {tool_id})")
        except Exception as e:
            logger.error(f"[ToolHook] [FAIL] 记录经验失败: {e}", exc_info=True)

    def _trigger_memory(
        self,
        actual_user_id: str,
        session_id: str,
        tool_id: str,
        tool_params: dict,
        result: dict,
        tool_execution_time_ms: int,
    ) -> None:
        try:
            from core.memory.memory_trigger import on_tool_execution
            on_tool_execution(
                user_id=actual_user_id,
                session_id=session_id,
                tool_name=tool_id,
                params=tool_params,
                result=result,
                execution_time_ms=tool_execution_time_ms,
            )
            logger.debug(f"[ToolHook] 工具执行已触发存储: {tool_id}")
        except Exception as e:
            logger.warning(f"[ToolHook] 工具执行存储失败（非阻塞）: {e}")

    async def _trigger_memory_async(
        self,
        actual_user_id: str,
        session_id: str,
        tool_id: str,
        tool_params: dict,
        result: dict,
        tool_execution_time_ms: int,
    ) -> None:
        try:
            from core.memory.memory_schema import MemoryMetadata
            from core.memory.memory_service import get_memory_service
            memory_service = await get_memory_service()

            success = result.get("success", False) if isinstance(result, dict) else False
            message = result.get("user_message", "") if isinstance(result, dict) else str(result)
            if len(message) > 500:
                message = message[:500]

            content = {
                "type": "tool_execution",
                "tool_name": tool_id,
                "params": tool_params,
                "success": success,
                "result_summary": message,
                "execution_time_ms": tool_execution_time_ms,
            }
            content_json = json.dumps(content, ensure_ascii=False)

            metadata = MemoryMetadata(
                user_id=actual_user_id or "anonymous",
                source="tool_execution",
                content_type="json",
                payload_summary=f"工具执行: {tool_id}",
                raw_payload=content_json,
                session_id=session_id,
                tool_id=tool_id,
            )

            # PG 写入 + 向量索引（双写，保持旧行为 sync_vector=True 语义）
            await memory_service.save_memory(
                user_id=actual_user_id or "anonymous",
                layer="execution",
                mem_type="tool_execution",
                content=content_json,
                metadata=metadata,
                context={"session_id": session_id},
            )
            await memory_service.save_execution_record(content_json, metadata)
            logger.debug(f"[ToolHook] 工具执行已触发异步存储: {tool_id}")
        except Exception as e:
            logger.warning(f"[ToolHook] 工具执行异步存储失败（非阻塞）: {e}")

    async def _save_phase_anchor(
        self,
        working_memory: Any,
        tool_id: str,
        result: dict,
        actual_user_id: str,
        session_id: str,
        effective_task_id: str,
    ) -> None:
        if working_memory is None:
            return
        try:
            await working_memory.save_phase_anchor("tool_complete", {
                "tool": tool_id,
                "success": result.get("success", False),
                "message": result.get("user_message", "")[:50],
            })
        except Exception as e:
            logger.debug(f"[ToolHook] 内存阶段锚点保存失败: {e}")

        try:
            # 延迟导入，避免循环依赖
            import core.agent.agent_loop as agent_loop_module
            pam = getattr(agent_loop_module, 'phase_anchor_manager', None)
            if pam is None:
                logger.debug("[ToolHook] phase_anchor_manager 未初始化，跳过 PostgreSQL 锚点保存")
                return
            pam.save(
                phase="tool_complete",
                data={
                    "tool": tool_id,
                    "success": result.get("success", False),
                    "message": result.get("user_message", "")[:50],
                },
                user_id=actual_user_id,
                session_id=session_id,
                task_id=effective_task_id,
            )
            logger.debug(f"[ToolHook] 工具执行后锚点已保存到PostgreSQL: {tool_id}")
        except Exception as e:
            logger.error(f"[ToolHook] 保存工具执行后锚点到PostgreSQL失败: {e}", exc_info=True)

    async def _save_phase_anchor_async(
        self,
        working_memory: Any,
        tool_id: str,
        result: dict,
        actual_user_id: str,
        session_id: str,
        effective_task_id: str,
    ) -> None:
        if working_memory is None:
            return
        try:
            await working_memory.save_phase_anchor("tool_complete", {
                "tool": tool_id,
                "success": result.get("success", False),
                "message": result.get("user_message", "")[:50],
            })
        except Exception as e:
            logger.debug(f"[ToolHook] 内存阶段锚点保存失败: {e}")

        try:
            from core.memory.memory_schema import MemoryMetadata
            from core.memory.memory_service import get_memory_service
            memory_service = await get_memory_service()

            anchor_content = {
                "phase": "tool_complete",
                "tool": tool_id,
                "success": result.get("success", False),
                "message": result.get("user_message", "")[:50],
            }
            content_json = json.dumps(anchor_content, ensure_ascii=False)

            metadata = MemoryMetadata(
                user_id=actual_user_id or "anonymous",
                source="checkpoint",
                content_type="json",
                payload_summary="阶段锚点: tool_complete",
                raw_payload=content_json,
                session_id=session_id,
                task_id=effective_task_id,
            )

            await memory_service.save_chat_turn(
                session_id=session_id,
                role="system",
                content=content_json,
                metadata=metadata,
            )
            logger.debug(f"[ToolHook] 工具执行后锚点已异步保存到记忆层: {tool_id}")
        except Exception as e:
            logger.error(f"[ToolHook] 保存工具执行后锚点到异步记忆层失败: {e}", exc_info=True)

    async def _auto_screenshot_verify_async(
        self,
        working_memory: Any,
        session_id: str,
        tool_id: str,
        result: dict,
        round_count: int,
        visual_verification_result: dict | None,
    ) -> None:
        if not result.get("success"):
            return

        verification_required_tools = [
            "mouse_click", "keyboard_input", "click_text", "pixel_click",
            "launch_app", "window_action", "find_and_click", "smart_form_fill",
            "web_open", "open_and_focus",
        ]
        if tool_id not in verification_required_tools:
            return

        logger.info(f"[ToolHook] 工具 {tool_id} 执行成功，准备自动截图验证...")
        try:
            from core.vision.safe_screenshot_v2 import ThreadSafePixelCapture
            from core.vision.screenshot_manager import get_screenshot_manager

            capture_tool = ThreadSafePixelCapture()
            screenshot_mgr = get_screenshot_manager()
            save_path = screenshot_mgr.get_auto_verify_path()

            verify_result = await capture_tool.capture_to_file_async(
                filepath=str(save_path),
                monitor=1,
            )

            if verify_result.get("success"):
                screenshot_path = str(save_path)
                screenshot_filename = save_path.name

                try:
                    from core.config import config
                    api_port = config.get("services.api.port", 8600)
                    api_host = config.get("services.api.host", "localhost")
                    screenshot_url = f"http://{api_host}:{api_port}/api/screenshots/view/{screenshot_filename}"
                except Exception as e:
                    logger.error(f"[ToolHook] 获取截图URL配置失败: {e}", exc_info=True)
                    screenshot_url = f"/api/screenshots/view/{screenshot_filename}"

                cleanup_stats = await screenshot_mgr.cleanup_old_screenshots_async()

                ocr_text = ""
                try:
                    from tools.screen_ocr import ScreenOCR
                    ocr_tool = ScreenOCR()
                    ocr_result = await ocr_tool.run_async(
                        image_path=screenshot_path,
                        return_positions=False,
                    )
                    if ocr_result.get("success"):
                        ocr_text = ocr_result.get("data", {}).get("text", "")
                        if len(ocr_text) > 500:
                            ocr_text = ocr_text[:500] + "..."
                except Exception as ocr_err:
                    logger.debug(f"[ToolHook] OCR识别失败: {ocr_err}")

                verify_msg = f"[自动验证] 操作后截图已保存: {screenshot_filename}"
                if ocr_text:
                    verify_msg += f"\n[屏幕内容识别] {ocr_text}"
                if visual_verification_result:
                    verify_msg += f"\n[视觉分析] {visual_verification_result.get('description', '无')[:200]}"
                if cleanup_stats.get("deleted_by_age", 0) > 0:
                    verify_msg += f"\n[已清理{cleanup_stats['deleted_by_age']}张过期截图]"

                if working_memory is not None:
                    working_memory.add_tool_result("pixel_capture", {
                        "success": True,
                        "user_message": verify_msg,
                        "data": {
                            "path": screenshot_url,
                            "filename": screenshot_filename,
                            "local_path": screenshot_path,
                            "auto_verify": True,
                            "cleanup": cleanup_stats,
                            "ocr_text": ocr_text,
                            "visual_verification": visual_verification_result,
                        }
                    })

                logger.info(f"[ToolHook] 自动截图验证完成: {screenshot_filename}, OCR: {len(ocr_text)}字符")

                from core.sync.realtime_sync import get_realtime_sync_manager
                sync = get_realtime_sync_manager()
                await sync.emit_event_async("tool_result", session_id, {
                    "round": round_count,
                    "tool": "pixel_capture",
                    "success": True,
                    "message": f"自动验证截图: {screenshot_filename}",
                    "data": {
                        "path": screenshot_url,
                        "filename": screenshot_filename,
                        "auto_verify": True,
                        "cleanup": cleanup_stats,
                        "ocr_text": ocr_text,
                        "visual_verification": visual_verification_result,
                    },
                    "auto_triggered": True,
                })
            else:
                logger.warning(f"[ToolHook] 自动截图失败: {verify_result.get('user_message', '')}")
        except Exception as e:
            logger.error(f"[ToolHook] 自动验证异常: {e}")

    async def _emit_tool_node_update(
        self,
        working_memory: Any,
        session_id: str,
        tool_id: str,
        result: dict,
        user_instruction: str,
        initial_steps: list,
    ) -> None:
        try:
            execution_time_ms = int(
                (time.time() - getattr(working_memory, '_tool_start_time', time.time())) * 1000
            )
            from core.sync.realtime_sync import get_realtime_sync_manager
            sync = get_realtime_sync_manager()
            await sync.emit_event_async("tool_node_update", session_id, {
                "node_id": tool_id,
                "status": "completed" if result.get("success") else "failed",
                "result": {
                    "success": result.get("success", False),
                    "message": result.get("user_message", ""),
                    "data": result.get("data", {}),
                },
                "execution_time": execution_time_ms,
            })

            if initial_steps:
                for step in initial_steps:
                    if step.get("tool") == tool_id:
                        step["status"] = "completed" if result.get("success") else "failed"
                        break
                await sync.emit_event_async("task_breakdown", session_id, {
                    "instruction": user_instruction,
                    "steps": initial_steps,
                })
                logger.info(f"[ToolHook] 任务拆解已发送: {len(initial_steps)} 步骤")
        except Exception as e:
            logger.warning(f"[ToolHook] 更新工具节点状态失败: {e}")

    async def _emit_ai_reply(
        self,
        working_memory: Any,
        session_id: str,
        chat_history: list | None,
        precision_parsed: Any,
        parsed: Any,
        tool_id: str,
        result: dict,
        ai_reply: str,
    ) -> None:
        try:
            ai_natural_lang = (
                getattr(precision_parsed, 'natural_language', None) or
                getattr(parsed, 'natural_language', None) or
                ai_reply
            )

            if ai_natural_lang and ai_natural_lang != "已完成":
                ai_response_msg = ai_natural_lang
            else:
                if result.get("success"):
                    ai_response_msg = f"已为您执行{tool_id}操作，{result.get('user_message', '执行成功')}。"
                else:
                    ai_response_msg = f"{tool_id}操作遇到问题：{result.get('user_message', '执行失败')}。"

            from core.sync.realtime_sync import get_realtime_sync_manager
            sync = get_realtime_sync_manager()
            await sync.emit_event_async("reply", session_id, {
                "content": ai_response_msg,
                "agent": "底座",
            })
            logger.info(f"[ToolHook] reply事件已发送: {ai_response_msg[:50]}...")

            if chat_history is None:
                chat_history = []
            chat_history.append({
                "role": "assistant",
                "content": ai_response_msg,
                "timestamp": time.time(),
            })
        except Exception as e:
            logger.warning(f"[ToolHook] 发送AI回复失败: {e}")

    def _handle_procedure_learning_failure(
        self,
        working_memory: Any,
        session_id: str,
        tool_id: str,
        result: dict,
        proc_learning: Any,
        voice_instance: Any = None,
    ) -> None:
        if result.get("success") or proc_learning is None or not proc_learning.is_available():
            return
        try:
            failure_reason = result.get('user_message', '未知错误')
            should_pause, pause_message = proc_learning.check_and_handle_tool_failure(
                session_id=session_id,
                tool_name=tool_id,
                failure_reason=failure_reason,
            )
            if should_pause and pause_message and working_memory is not None:
                working_memory.append({
                    "role": "system",
                    "content": f"【任务暂停】{pause_message}"
                })
                if voice_instance:
                    try:
                        voice_instance.speak(
                            "我遇到了一些问题，需要您的帮助。请查看屏幕上的选项。",
                            is_system=True,
                            wait=False,
                            priority=2
                        )
                    except Exception as voice_err:
                        logger.debug(f"[ToolHook] 语音播报暂停提示失败: {voice_err}")
                logger.info(f"[ToolHook] [ProcedureLearning] 任务已暂停，等待用户选择: {session_id}")
        except Exception as e:
            logger.error(f"[ToolHook] [ProcedureLearning] 处理工具失败异常: {e}")

    def _enhance_tool_feedback(
        self,
        tool_id: str,
        result: dict,
        round_count: int,
        user_instruction: str,
        actual_user_id: str,
    ) -> None:
        """
        工具反馈增强（Phase 7 从 agent_loop 抽取到 ToolHook）。

        在工具执行完成后立即上报反应，供增强学习层积累数据。
        不依赖 AI 响应后的启发式分析，简化闭环。
        """
        if not USE_ENHANCED_FILTER or not _REPORT_REACTION_AVAILABLE:
            return

        try:
            reaction = "used" if result.get("success") else "confused"
            context = {
                "current_task": user_instruction,
                "round": round_count,
                "success": result.get("success", False),
                "message": result.get("user_message", "")[:100],
            }
            report_reaction(
                tool_id=tool_id,
                context=context,
                reaction=reaction,
                user_id=actual_user_id or "default",
            )
            logger.debug(f"[ToolHook] 工具反馈增强已上报: {tool_id} -> {reaction}")
        except Exception as e:
            logger.error(f"[ToolHook] 工具反馈增强失败: {e}", exc_info=True)

    # ═════════════════════════════════════════════════════════════════════════════
    # 【Phase X】步骤生命周期 Hook：断点续传从 agent_loop 迁移到此处
    # ═════════════════════════════════════════════════════════════════════════════

    async def before_step_async(self, ctx: HookContext, **kwargs) -> HookContext:
        """步骤开始前：记录 checkpoint start_step"""
        extra = getattr(ctx, "extra", {}) or {}
        task_state = extra.get("task_state")
        step_info = kwargs.get("step")

        if task_state and step_info:
            try:
                from core.agent.checkpoint_manager import checkpoint_manager
                await checkpoint_manager.start_step_async(
                    task_id=task_state.task_id,
                    step_number=step_info.get("number", 0),
                    step_goal=step_info.get("goal", ""),
                    input_context=step_info.get("context", {})
                )
            except Exception as e:
                logger.warning(f"[ToolHook] start_step 失败: {e}")
        return ctx

    async def after_step_async(self, ctx: HookContext, **kwargs) -> HookContext:
        """步骤完成后：记录 checkpoint complete_step + 关键步骤保存断点"""
        extra = getattr(ctx, "extra", {}) or {}
        task_state = extra.get("task_state")
        step_info = kwargs.get("step")
        result = kwargs.get("result")

        if task_state and step_info:
            try:
                from core.agent.checkpoint_manager import checkpoint_manager
                await checkpoint_manager.complete_step_async(
                    task_id=task_state.task_id,
                    step_number=step_info.get("number", 0),
                    tool_name=step_info.get("tool_id", ""),
                    tool_params=step_info.get("tool_params", {}),
                    output_result=result,
                    success=result.get("success", False) if result else False
                )
                # 关键步骤保存断点（与原 agent_loop.py 逻辑一致）
                if result and result.get("success") and is_critical_step(step_info.get("tool_id", "")):
                    await checkpoint_manager.save_checkpoint_async(
                        task_id=task_state.task_id,
                        checkpoint_name=f"完成{step_info.get('tool_id', '')}"
                    )
                    logger.debug(f"[ToolHook] 已保存关键步骤断点: {step_info.get('tool_id', '')}")
            except Exception as e:
                logger.warning(f"[ToolHook] complete_step 失败: {e}")

        # [Planner] 更新步骤状态并推进AI计划（从 agent_loop.py 迁移到 after_step Hook）
        try:
            from core.task.planner import StepStatus, get_planner
            working_memory = getattr(ctx, "working_memory", None)
            if working_memory and hasattr(working_memory, 'ai_plan_id'):
                planner = get_planner()
                current_step_idx = getattr(working_memory, 'current_step_index', 0)
                if result and result.get("success"):
                    planner.update_step_status(
                        working_memory.ai_plan_id,
                        current_step_idx,
                        StepStatus.COMPLETED,
                        result=result
                    )
                    logger.info(f"[Planner] 步骤 {current_step_idx} 标记为完成")
                    # 【修复】同步更新 working_memory.ai_plan['current_step']，供 AgentLoop 任务完成判定使用
                    if working_memory and hasattr(working_memory, 'ai_plan') and working_memory.ai_plan:
                        current_step = working_memory.ai_plan.get('current_step', 0)
                        total_steps = working_memory.ai_plan.get('total_steps', 0)
                        if total_steps > 0 and current_step < total_steps:
                            working_memory.ai_plan['current_step'] = current_step + 1
                            logger.info(f"[ToolHook] 计划步骤推进：{current_step} -> {current_step + 1}/{total_steps}")
                        # 注入下一步系统提示（从废弃的 advance_plan 迁移）
                        next_step_idx = working_memory.ai_plan['current_step']
                        steps = working_memory.ai_plan.get('steps', [])
                        if next_step_idx < len(steps):
                            next_step = steps[next_step_idx]
                            step_desc = next_step.get('description', f'步骤{next_step_idx+1}')
                            logger.info(f"[ToolHook] 提示AI执行计划第{next_step_idx+1}步: {step_desc}")
                            working_memory.append({
                                "role": "system",
                                "content": f"【计划执行】第{next_step_idx+1}步共{len(steps)}步: {step_desc}。请输出工具调用执行此步骤。"
                            })
                        else:
                            logger.info(f"[ToolHook] AI计划全部完成，共 {len(steps)} 步")
                            working_memory.append({
                                "role": "system",
                                "content": f"【计划完成】所有{len(steps)}个步骤已执行完毕，请返回 FINAL_ANSWER 总结结果。"
                            })
                            working_memory.ai_plan = None
                    next_steps = planner.get_next_executable_steps(working_memory.ai_plan_id)
                    if next_steps:
                        logger.info(f"[Planner] 下一步可执行: {next_steps[0].description}")
                    elif planner.is_plan_complete(working_memory.ai_plan_id):
                        logger.info("[Planner] 计划全部完成")
                else:
                    planner.update_step_status(
                        working_memory.ai_plan_id,
                        current_step_idx,
                        StepStatus.FAILED,
                        error=result.get('user_message', '执行失败') if result else '执行失败'
                    )
                    logger.warning(f"[Planner] 步骤 {current_step_idx} 标记为失败")
                    if hasattr(working_memory, 'append'):
                        working_memory.append({
                            "role": "system",
                            "content": f"步骤{current_step_idx+1}执行失败，请尝试其他方法完成该步骤。"
                        })
        except Exception as e:
            logger.warning(f"[Planner] 步骤状态更新失败: {e}")

        # [SmartContext] 关键决策断点保存（从 agent_loop.py 迁移到 after_step Hook）
        try:
            smart_context_step_result = extra.get("smart_context_step_result")
            smart_context_manager = extra.get("smart_context_manager")
            effective_task_id = extra.get("effective_task_id")
            loop_state = extra.get("loop_state")
            if smart_context_step_result and smart_context_manager and effective_task_id:
                round_count = getattr(loop_state, "round_count", 0) if loop_state else 0
                if smart_context_step_result.get('is_key_decision') or smart_context_manager.should_save_checkpoint(
                    effective_task_id, round_count
                ):
                    await checkpoint_manager.save_checkpoint_async(
                        task_id=effective_task_id,
                        checkpoint_name=f"步骤{round_count}-关键决策"
                    )
                    logger.info(f"[SmartContext] 已保存关键检查点: 步骤{round_count}")
        except Exception as e:
            logger.warning(f"[SmartContext] 保存检查点失败: {e}")

        # [全局连接] 反思系统 - ReAct反思循环（从 agent_loop.py 迁移到 after_step Hook）
        try:
            reflector = extra.get("reflector")
            user_instruction = extra.get("user_instruction")
            parsed = extra.get("parsed")
            result = kwargs.get("result")
            execution_history = extra.get("execution_history", [])
            working_memory = getattr(ctx, "working_memory", None)
            if reflector and user_instruction and parsed and working_memory:
                from core.agent.reflection_bridge import run_react_reflection
                await run_react_reflection(
                    reflector=reflector,
                    user_instruction=user_instruction,
                    parsed=parsed,
                    result=result,
                    execution_history=execution_history,
                    working_memory=working_memory,
                )
        except Exception as e:
            logger.warning(f"[ToolHook] run_react_reflection 失败: {e}")

        # [全局连接] 进化引擎 - 自动萃取经验（从 agent_loop.py 迁移到 after_step Hook）
        try:
            result = kwargs.get("result")
            execution_history = extra.get("execution_history", [])
            user_instruction = extra.get("user_instruction")
            if result and result.get("success") and len(execution_history) >= 2 and user_instruction:
                from core.evolution.evolution import get_evolution_engine
                evolution = get_evolution_engine()
                experience = evolution.extract_experience(
                    task=user_instruction,
                    history=execution_history
                )
                if experience:
                    evolution.store_experience(experience)
                    logger.info("[ToolHook] 进化引擎萃取经验成功")
        except Exception as e:
            logger.debug(f"[ToolHook] 进化引擎调用失败（不影响执行）: {e}")
        return ctx

    async def after_loop_async(self, ctx: HookContext, **kwargs) -> HookContext:
        """循环结束后：保存最终断点"""
        extra = getattr(ctx, "extra", {}) or {}
        task_state = extra.get("task_state")
        if task_state:
            try:
                from core.agent.checkpoint_manager import checkpoint_manager
                await checkpoint_manager.save_checkpoint_async(
                    task_id=task_state.task_id,
                    checkpoint_name="任务完成"
                )
                logger.info(f"[Checkpoint] 任务完成，已保存最终断点: {task_state.task_id}")
            except Exception as e:
                logger.warning(f"[Checkpoint] 保存最终断点失败: {e}")
        return ctx


# 全局实例
tool_hook = ToolHook()
