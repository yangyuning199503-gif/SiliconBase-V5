#!/usr/bin/env python3
"""
PromptFinalizer - 提示词最终组装器
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
从 agent_loop.py 抽取的提示词后处理逻辑。

职责：
- 准备额外上下文片段（生命体征、视觉、偏好、弱连接、阶段锚点）
- 调用 ContextAssembler.build_system_prompt_with_budget() 组装完整提示词
- 后处理注入生命体征
- 后处理注入经验
- 保存提示词调试信息

设计约束：
1. 同步/异步双入口。
2. 任何步骤失败均降级，禁止阻断主循环。
3. 参数较多但语义内聚——这是"提示词最终确定"的完整链路。
"""

from pathlib import Path
from typing import Any

from core.logger import logger

_LIFE_INJECTOR_AVAILABLE = True

try:
    from core.prompt.prompt_debugger import save_last_prompt
    _PROMPT_DEBUGGER_AVAILABLE = True
except ImportError:
    _PROMPT_DEBUGGER_AVAILABLE = False

try:
    from core.evolution.experience_injector import get_experience_injector_v3
    _EXPERIENCE_INJECTOR_AVAILABLE = True
except ImportError:
    _EXPERIENCE_INJECTOR_AVAILABLE = False


class PromptFinalizer:
    """提示词最终组装器"""

    async def finalize(
        self,
        *,
        user_id: str,
        user_instruction: str,
        working_memory: Any,
        work_mode: str,
        effective_task_id: str,
        phase_anchor_manager: Any,
        last_vision_description: str | None,
        assembler: Any,
        smart_context: dict[str, str],
        perception_context: str,
        memory_context: str,
        exploration_enhancement: str,
        layer_prompt: str,
        three_views_prompt: str,
        reflection_context: str,
        experience_context: str,
        world_model_section: str,
        execution_history: list[dict],
        session_id: str,
        round_count: int = 0,
    ) -> tuple[str, dict | None]:
        """
        同步版：最终确定 system prompt。

        Returns:
            (full_system_prompt, budget_report_or_none)
        """
        # ── 1. 准备额外上下文 ────────────────────────────────────────────────
        life_state_context = self._prepare_life_state_context(user_id)
        vision_description = self._prepare_vision_description(last_vision_description)
        user_preference_context = self._prepare_user_preference_context(working_memory)
        weak_connection_context = self._prepare_weak_connection_context(work_mode)
        phase_context = self._prepare_phase_context(working_memory, effective_task_id, phase_anchor_manager)

        # ── 2. TokenBudget 组装 ──────────────────────────────────────────────
        try:
            full_system_prompt, budget_report = assembler.build_system_prompt_with_budget(
                smart_context=smart_context,
                perception_context=perception_context,
                three_views_prompt=three_views_prompt,
                memory_context=memory_context,
                exploration_enhancement=exploration_enhancement,
                layer_prompt=layer_prompt,
                reflection_context=reflection_context,
                vision_description=vision_description,
                life_state_context=life_state_context,
                user_preference_context=user_preference_context,
                weak_connection_context=weak_connection_context,
                world_model_section=world_model_section,
                phase_context=phase_context,
                execution_history=execution_history,
                experience_context=experience_context,
                working_memory=working_memory,
            )
        except Exception as e:
            logger.error(f"[PromptFinalizer] build_system_prompt_with_budget 失败: {e}", exc_info=True)
            # 降级：简单拼接
            full_system_prompt = self._fallback_concat(
                smart_context, perception_context, three_views_prompt, memory_context,
                layer_prompt, reflection_context, vision_description, life_state_context,
                world_model_section, phase_context, experience_context,
            )
            budget_report = None

        # ── 3. 经验注入 ──────────────────────────────────────────────────────
        full_system_prompt = await self._inject_experience(user_instruction, full_system_prompt)

        # ── 5. 保存调试信息 ──────────────────────────────────────────────────
        self._save_debug_info(
            user_id=user_id,
            session_id=session_id,
            user_instruction=user_instruction,
            full_system_prompt=full_system_prompt,
            smart_context=smart_context,
            three_views_prompt=three_views_prompt,
            memory_context=memory_context,
            layer_prompt=layer_prompt,
            exploration_enhancement=exploration_enhancement,
            phase_context=phase_context,
            working_memory=working_memory,
        )

        # 【调试输出】每次新建文件保存完整 system_prompt，供开发者审查历史
        try:
            dump_dir = Path(__file__).parent.parent.parent / "data" / "prompt_dumps"
            dump_dir.mkdir(parents=True, exist_ok=True)

            ts = __import__('datetime').datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            fname = f"prompt_dump_{ts}_r{round_count:02d}.txt"
            dump_path = dump_dir / fname

            import asyncio
            def _write_prompt_dump():
                with open(dump_path, "w", encoding="utf-8") as f:
                    f.write("=== SiliconBase V5 - 完整 System Prompt ===\n")
                    f.write(f"长度: {len(full_system_prompt)} 字符\n")
                    f.write(f"Token 估算: ~{max(1, int(len(full_system_prompt) / 2))}\n")
                    f.write(f"时间: {__import__('datetime').datetime.now().isoformat()}\n")
                    f.write(f"轮次: {round_count}\n")
                    f.write("=" * 60 + "\n\n")
                    f.write(full_system_prompt)
                    # 【止血-诊断】追加TokenBudget截断报告，让用户看到哪里被压缩
                    if budget_report:
                        f.write("\n\n")
                        f.write("=" * 60 + "\n")
                        f.write("【TokenBudget 截断诊断报告】\n")
                        f.write("=" * 60 + "\n")
                        if isinstance(budget_report, dict):
                            allocations = budget_report.get("allocations", [])
                            total_orig = budget_report.get("total_original_tokens", 0)
                            total_trunc = budget_report.get("total_truncated_tokens", 0)
                            f.write(f"原始Token总计: {total_orig}\n")
                            f.write(f"截断后Token总计: {total_trunc}\n")
                            f.write(f"截断次数: {sum(1 for a in allocations if a.get('was_truncated'))}\n")
                            f.write("-" * 40 + "\n")
                            for alloc in allocations:
                                cat = alloc.get("category", "unknown")
                                orig = alloc.get("original_length", 0)
                                trunc = alloc.get("truncated_length", 0)
                                bgt = alloc.get("budget", 0)
                                flag = " [截断!]" if alloc.get("was_truncated") else ""
                                f.write(f"  {cat}: {orig}→{trunc} / 预算{bgt}{flag}\n")
                            errors = budget_report.get("errors", [])
                            if errors:
                                f.write("-" * 40 + "\n")
                                f.write("错误:\n")
                                for err in errors:
                                    f.write(f"  - {err}\n")
                        else:
                            f.write(f"报告类型: {type(budget_report).__name__}\n")
                            f.write(f"报告内容: {str(budget_report)[:500]}\n")
            await asyncio.to_thread(_write_prompt_dump)

            # 自动清理：只保留最近 30 个 dump 文件
            _MAX_PROMPT_DUMPS = 30
            all_dumps = sorted(dump_dir.glob("prompt_dump_*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
            for old_file in all_dumps[_MAX_PROMPT_DUMPS:]:
                old_file.unlink(missing_ok=True)

        except Exception as e:
            logger.warning(f"[PromptFinalizer] 保存提示词 dump 失败: {e}")
        return full_system_prompt, budget_report

    async def finalize_async(
        self,
        *,
        user_id: str,
        user_instruction: str,
        working_memory: Any,
        work_mode: str,
        effective_task_id: str,
        phase_anchor_manager: Any,
        last_vision_description: str | None,
        assembler: Any,
        smart_context: dict[str, str],
        perception_context: str,
        memory_context: str,
        exploration_enhancement: str,
        layer_prompt: str,
        three_views_prompt: str,
        reflection_context: str,
        experience_context: str,
        world_model_section: str,
        execution_history: list[dict],
        session_id: str,
        round_count: int = 0,
    ) -> tuple[str, dict | None]:
        """异步版：直接调用 async finalize。"""
        return await self.finalize(
            user_id=user_id,
            user_instruction=user_instruction,
            working_memory=working_memory,
            work_mode=work_mode,
            effective_task_id=effective_task_id,
            phase_anchor_manager=phase_anchor_manager,
            last_vision_description=last_vision_description,
            assembler=assembler,
            smart_context=smart_context,
            perception_context=perception_context,
            memory_context=memory_context,
            exploration_enhancement=exploration_enhancement,
            layer_prompt=layer_prompt,
            three_views_prompt=three_views_prompt,
            reflection_context=reflection_context,
            experience_context=experience_context,
            world_model_section=world_model_section,
            execution_history=execution_history,
            session_id=session_id,
            round_count=round_count,
        )

    # ═════════════════════════════════════════════════════════════════════════════
    # 内部方法：上下文准备
    # ═════════════════════════════════════════════════════════════════════════════

    def _prepare_life_state_context(self, user_id: str) -> str:
        """准备生命状态上下文。尝试注入，失败时降级为空字符串。"""
        if not _LIFE_INJECTOR_AVAILABLE:
            return ""
        try:
            # 【修复】尝试调用生命体征注入，失败时优雅降级而非静默忽略
            from core.prompt.life_prompt_injector import inject_life_state_to_prompt
            life_state = inject_life_state_to_prompt("", user_id)
            # inject_life_state_to_prompt 返回 life_state + "\n\n" + base_prompt
            # 当 base_prompt 为空时，返回 life_state + "\n\n"
            return life_state.strip() if life_state else ""
        except Exception as e:
            # 降级：生命体征不可用时不阻断主循环，但记录日志
            logger.debug(f"[PromptFinalizer] 生命体征注入失败，降级为空: {e}")
            return ""

    def _prepare_vision_description(self, last_vision_description: str | None) -> str:
        if not last_vision_description:
            return ""
        try:
            from core.utils.security import sanitize_vision_description
            safe = sanitize_vision_description(last_vision_description)
            return f"【屏幕状态】{safe}"
        except Exception as e:
            logger.error(f"[SECURITY] 视觉描述清理失败: {e}")
            return ""

    def _prepare_user_preference_context(self, working_memory: Any) -> str:
        try:
            if hasattr(working_memory, 'user_context') and working_memory.user_context:
                pref = working_memory.user_context.get('preferences', {})
                style = pref.get('communication_style')
                if style == 'formal':
                    return "用户使用正式语气，请用敬语回应。"
                elif style == 'casual':
                    return "用户使用随意语气，可以用轻松的方式回应。"
        except Exception as e:
            logger.debug(f"[PromptFinalizer] 用户偏好上下文准备失败: {e}")
        return ""

    def _prepare_weak_connection_context(self, work_mode: str) -> str:
        if work_mode != "daily":
            return ""
        try:
            from datetime import datetime
            if datetime.now().hour == 18:
                return "【弱连接触发】工作时间即将结束，建议生成今日总结"
        except Exception as e:
            logger.debug(f"[PromptFinalizer] 弱连接上下文准备失败: {e}")
        return ""

    def _prepare_phase_context(
        self,
        working_memory: Any,
        effective_task_id: str,
        phase_anchor_manager: Any,
    ) -> str:
        try:
            memory_ctx = working_memory.get_context_for_prompt()
        except Exception as e:
            logger.error(f"[PromptFinalizer] 从内存获取阶段上下文失败: {e}", exc_info=True)
            return ""

        postgres_ctx = ""
        if effective_task_id and phase_anchor_manager is not None:
            try:
                summary = phase_anchor_manager.get_summary(effective_task_id)
                if summary:
                    postgres_ctx = f"\n[PostgreSQL阶段锚点]\n{summary}"
                    logger.debug(f"[PromptFinalizer] 已从PostgreSQL加载阶段锚点: {effective_task_id}")
            except Exception as e:
                logger.error(f"[PromptFinalizer] 从PostgreSQL获取阶段锚点失败: {e}", exc_info=True)

        return memory_ctx + postgres_ctx

    # ═════════════════════════════════════════════════════════════════════════════
    # 内部方法：经验注入
    # ═════════════════════════════════════════════════════════════════════════════

    async def _inject_experience(self, user_instruction: str, full_system_prompt: str) -> str:
        if _EXPERIENCE_INJECTOR_AVAILABLE:
            try:
                injector = get_experience_injector_v3(
                    enable_tracking=True,
                )
                return await injector.inject_experience(user_instruction, full_system_prompt)
            except Exception as e:
                logger.warning(f"[PromptFinalizer] 增强经验注入失败，回退到基础版本: {e}")
        try:
            from core.evolution.experience_injector import inject_experience_to_prompt
            return await inject_experience_to_prompt(user_instruction, full_system_prompt)
        except Exception as e:
            logger.warning(f"[PromptFinalizer] 基础经验注入失败: {e}")
        return full_system_prompt

    # ═════════════════════════════════════════════════════════════════════════════
    # 内部方法：调试信息保存
    # ═════════════════════════════════════════════════════════════════════════════

    def _save_debug_info(
        self,
        user_id: str,
        session_id: str,
        user_instruction: str,
        full_system_prompt: str,
        smart_context: dict[str, str],
        three_views_prompt: str,
        memory_context: str,
        layer_prompt: str,
        exploration_enhancement: str,
        phase_context: str,
        working_memory: Any,
    ) -> None:
        if not _PROMPT_DEBUGGER_AVAILABLE:
            return
        try:
            save_last_prompt(
                user_id=user_id,
                full_system_prompt=full_system_prompt,
                components_data={
                    "base_prompt": smart_context.get("system_prompt", ""),
                    "three_views": three_views_prompt,
                    "memory": memory_context or "",
                    "experience": "经验已通过注入器自动嵌入",
                    "layer": layer_prompt or "",
                    "reasoning": smart_context.get("reasoning_framework", ""),
                    "exploration": exploration_enhancement or "",
                    "phase_context": phase_context,
                    "user_personalization": (
                        "已根据用户偏好调整语气"
                        if hasattr(working_memory, 'user_context') and working_memory.user_context
                        else ""
                    ),
                },
                session_id=session_id,
                query=user_instruction,
            )
            logger.debug(f"[PromptFinalizer] 已保存完整提示词供调试，用户: {user_id}")
        except Exception as e:
            logger.debug(f"[PromptFinalizer] 保存提示词调试信息失败: {e}")

    # ═════════════════════════════════════════════════════════════════════════════
    # 内部方法：降级拼接
    # ═════════════════════════════════════════════════════════════════════════════

    def _fallback_concat(self, *parts) -> str:
        """TokenBudget 失败时的降级拼接。"""
        result_parts = []
        for p in parts:
            if isinstance(p, str) and p.strip():
                result_parts.append(p.strip())
            elif isinstance(p, dict):
                result_parts.append(p.get("system_prompt", "").strip())
        return "\n\n".join(result_parts)


# 全局实例
prompt_finalizer = PromptFinalizer()
