#!/usr/bin/env python3
"""
CoreLogicHooks - AgentLoop 核心决策逻辑 Hook 处理器
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
把 agent_loop.py 循环体内硬编码的核心逻辑迁移到 Hook 注册表。

迁移列表：
  1. 干预检查      → before_prompt, priority=100
  2. 感知注入      → before_prompt, priority=95
  3. 视觉感知      → before_prompt, priority=90
  4. 上下文组装    → before_prompt, priority=85
  5. 世界模型预测  → before_tool,   priority=95

使用方式：
    from core.agent.hooks.core_logic_hooks import register_core_logic_hooks
    register_core_logic_hooks(agent_loop_hooks)
"""

import asyncio
import time

from core.agent.agent_loop_hooks import HookContext
from core.logger import logger

# ═══════════════════════════════════════════════════════════════════════════════
# 辅助函数：从 HookContext 提取原始用户指令
# ═══════════════════════════════════════════════════════════════════════════════

def _get_user_instruction(ctx: HookContext) -> str:
    """
    从 HookContext 中提取尽可能原始的用户指令。

    优先级：
      1. ctx.working_memory.goal / user_intent_snapshot（原始意图）
      2. ctx.task.metadata.raw / intent.raw
      3. ctx.task.instruction（若存在）
      4. str(ctx.task)（最后兜底，但会是 Task(...) 字符串，尽量不用）
    """
    text = ""
    wm = getattr(ctx, 'working_memory', None)
    if wm is not None:
        text = getattr(wm, 'goal', '') or getattr(wm, 'user_intent_snapshot', '')

    task = getattr(ctx, 'task', None)
    if not text and task is not None:
        # 某些运行时会将原始用户输入挂在 task._runtime_state.user_instruction
        runtime_state = getattr(task, '_runtime_state', None)
        if runtime_state is not None:
            text = getattr(runtime_state, 'user_instruction', '')
        # 优先尝试任务元数据中的原始输入
        if not text:
            metadata = getattr(task, 'metadata', None) or {}
            if isinstance(metadata, dict):
                text = metadata.get('raw', '') or metadata.get('user_input', '')
        if not text:
            intent = getattr(task, 'intent', None) or {}
            if isinstance(intent, dict):
                text = intent.get('raw', '') or intent.get('text', '')
        if not text:
            text = getattr(task, 'instruction', '')
        if not text:
            text = str(task)

    return text.strip()


# ═══════════════════════════════════════════════════════════════════════════════
# 辅助函数：判断用户输入是否为明确的视觉请求
# ═══════════════════════════════════════════════════════════════════════════════

def _is_explicit_visual_request(user_input: str) -> bool:
    """
    判断用户是否明确要求看屏幕 / 截图 / 找东西。
    用于任务初始阶段（无执行历史）时决定是否允许触发视觉感知。
    """
    if not user_input:
        return False
    explicit_keywords = [
        # 中文
        "看到", "看见", "显示", "展示", "截图", "截屏", "截个图", "截一下图",
        "在哪里", "在哪", "位置", "找到", "定位", "找一下", "找一找",
        "看看", "看一下", "看看屏幕", "看看桌面",
        "屏幕", "桌面", "窗口", "当前页面", "这个页面",
        "识别", "ocr", "提取文字", "读取文字",
        # 英文
        "see", "show me", "screenshot", "capture", "where is", "where are",
        "find", "locate", "position", "screen", "desktop", "window",
        "what do you see", "what can you see", "what is on",
    ]
    lower = user_input.lower()
    return any(kw in lower for kw in explicit_keywords)


# ═══════════════════════════════════════════════════════════════════════════════
# 【V2新增】向量知识注入 Prompt
# ═══════════════════════════════════════════════════════════════════════════════

async def _inject_ui_knowledge_to_prompt(
    current_app: str,
    detected_elements: list[dict],
    user_id: str = "default",
) -> str:
    """
    为当前检测到的元素召回向量库中的语义知识，并格式化为 Prompt 文本。

    召回条件：similarity > 0.80，每轮最多注入 15 个元素，控制 token 消耗。

    Args:
        current_app: 当前前台应用名
        detected_elements: 检测到的元素列表（来自实时监控快照）
        user_id: 用户标识

    Returns:
        格式化后的 Prompt 文本片段，无命中时返回空字符串
    """
    try:
        from core.vision.vision_element_knowledge import query_ui_knowledge
    except Exception as e:
        logger.error(f"[CoreLogicHooks] UI知识库导入失败: {e}", exc_info=True)
        return ""

    if not detected_elements:
        return ""

    knowledge_lines = ["【当前页面已知 UI 元素（来自历史记忆）】"]
    injected_count = 0

    for elem in detected_elements[:15]:
        # 构造查询特征：类型 + 名称 + 应用
        features = (
            f"UI元素: {elem.get('class', '未知')} "
            f"名称: {elem.get('name', elem.get('text', ''))} "
            f"应用: {current_app}"
        )

        try:
            results = await query_ui_knowledge(features=features, user_id=user_id, limit=1)
            if results and results[0].get("similarity", 0) > 0.80:
                k = results[0]
                bbox = elem.get("bbox", [0, 0, 0, 0])
                center = ((bbox[0] + bbox[2]) // 2, (bbox[1] + bbox[3]) // 2) if len(bbox) >= 4 else (0, 0)

                knowledge_lines.append(
                    f"• 【{k.get('element_type', '未知元素')}】"
                    f"  位置: ({center[0]}, {center[1]})"
                    f"  功能: {k.get('function', '未知')}"
                    f"  操作: {k.get('interaction', 'click')}"
                    f"  [记忆置信度: {k.get('similarity', 0):.0%}]"
                )
                injected_count += 1
        except Exception:
            continue

    if injected_count == 0:
        return ""

    knowledge_lines.append(
        "【规则】如需操作上述元素，直接使用 mouse_click(x, y) 到对应中心点，"
        "无需再调用查找工具。历史记忆仅供参考，请以当前屏幕实际状态为准。"
    )
    return "\n".join(knowledge_lines)


# ── 1. 干预检查 ──────────────────────────────────────────────────────────────

async def hook_intervention_check(ctx: HookContext, **kwargs) -> HookContext:
    """
    实时干预检查（原 agent_loop.py:913-927）

    期望 ctx.extra 包含:
        - intervention_checker: 干预检查器实例
        - pausable_task_sm: 可暂停任务状态机
        - state_persistence: 状态持久化
        - state: 运行状态

    输出写入 ctx.extra:
        - intervention_should_return: bool
        - intervention_return_value: Any
    """
    task = ctx.task
    if not task or not task.id:
        return ctx

    intervention_checker = ctx.extra.get('intervention_checker')
    if not intervention_checker:
        return ctx

    try:
        intervention_result = await intervention_checker.check_and_apply_async(
            task_id=task.id,
            working_memory=ctx.working_memory,
            session_id=ctx.session_id,
            current_plan=getattr(ctx.working_memory, 'ai_plan', None),
            pausable_task_sm=ctx.extra.get('pausable_task_sm'),
            state_persistence=ctx.extra.get('state_persistence'),
            state=ctx.extra.get('state'),
        )
        if getattr(intervention_result, 'should_return', False):
            ctx.extra['intervention_should_return'] = True
            ctx.extra['intervention_return_value'] = getattr(
                intervention_result, 'return_value', None
            )
            logger.info("[CoreLogicHook] 干预检查触发 should_return")
    except Exception as e:
        logger.warning(f"[CoreLogicHook-Intervention] 干预检查失败: {e}")

    return ctx


# ── 2. 感知注入 ──────────────────────────────────────────────────────────────

async def hook_perception_inject(ctx: HookContext, tool_result=None, **kwargs) -> HookContext:
    """
    感知能力激活与注入——改为 after_tool 按需触发（失败时才学习）

    设计约束：
      - 工具成功 → 不触发感知，直接返回（会做了不需要看）
      - 工具失败 → 触发感知，看屏幕学习失败原因
      - 感知数据写入 working_memory，供下一轮 LLM 参考
    """
    # 【架构修复】不会才学习：工具成功时不浪费视觉资源
    if tool_result is not None:
        _result_obj = tool_result.get("result") if isinstance(tool_result, dict) else tool_result
        if isinstance(_result_obj, dict) and _result_obj.get("success", False):
            logger.debug("[CoreLogicHook-Perception] 工具执行成功，跳过感知（会才不需要学）")
            return ctx

    perception_manager = ctx.extra.get('perception_manager')
    if perception_manager is None:
        logger.debug("[CoreLogicHook-Perception] perception_manager 不可用，跳过")
        return ctx

    try:
        loop_state = ctx.extra.get('loop_state')
        execution_history = ctx.extra.get('execution_history', [])
        work_mode = ctx.extra.get('work_mode', 'daily')

        user_instruction = _get_user_instruction(ctx)

        # 【P1-修复】简单聊天直接跳过视觉感知，避免"几点了"等纯问答调用视觉模型
        # 正常路径应在 DialogueManager 层就被分流到 quick_chat，这里是兜底防线
        from core.constants import is_simple_chat
        if is_simple_chat(user_instruction):
            logger.info(
                f"[CoreLogicHook-Perception] 简单聊天输入，跳过视觉感知: {user_instruction[:40]}"
            )
            return ctx

        # 【P1-修复】任务最开始的阶段（无执行历史）且用户没有明确要求看屏幕时，
        # 不要调用视觉模型。此时应用/窗口大概率还没打开，截图没有意义，只会浪费
        # 时间和模型资源。等执行了一两步工具后（如已打开应用），再看屏幕找元素。
        # before_prompt hook 调用时 round_count 可能已经是 1，因此用 execution_history
        # 是否为空作为更可靠的"任务刚开始"判断。
        # 【P1-修复】意识线程标记 force_vision 时强制触发视觉感知，不被初始阶段跳过
        context_flag = ctx.extra.get("context_flag")
        force_vision = (context_flag == "force_vision")
        if not execution_history and not _is_explicit_visual_request(user_instruction) and not force_vision:
            logger.info(
                f"[CoreLogicHook-Perception] 任务初始阶段且非明确视觉请求，跳过视觉感知: "
                f"{user_instruction[:40]}"
            )
            return ctx

        perception_context_info = {
            "execution_history": execution_history,
            "round": getattr(loop_state, 'round_count', 0) if loop_state else 0,
            "mode": work_mode
        }

        # 跳过逻辑：after_tool 学习路径中，轮次>1且上一步工具失败时，
        # 跳过本次 before_prompt 感知，避免与 after_tool 感知重复。
        # before_prompt 决策路径中（tool_result is None）不跳过，
        # 因为失败后更需要重新看屏幕来决定下一步。
        should_skip = False
        if tool_result is not None and loop_state and getattr(loop_state, 'round_count', 0) > 1 and execution_history:
            last_exec = execution_history[-1]
            if not last_exec.get("success", True):
                should_skip = True
                logger.debug(
                    f"[CoreLogicHook-Perception] 轮次{loop_state.round_count}>1"
                    f"且上一步工具({last_exec.get('tool','')})失败，跳过感知触发"
                )

        if not should_skip and perception_manager.should_trigger_perception(
            user_instruction, perception_context_info
        ):
            logger.info("[CoreLogicHook-Perception] 感知能力触发，获取感知数据...")
            _pm_start = time.time()
            logger.info(f"[TRACE] hook_perception_inject: get_perception 前 | ts={_pm_start:.3f}")
            # 【P0修复】给感知调用加业务层总超时，防止视觉/OCR/UI线程阻塞拖死整个任务
            _PERCEPTION_BUDGET_SECONDS = float(
                ctx.extra.get('perception_timeout_seconds', 15.0)
            )
            try:
                perception = await asyncio.wait_for(
                    perception_manager.get_perception(
                        user_input=user_instruction,
                        context=perception_context_info
                    ),
                    timeout=_PERCEPTION_BUDGET_SECONDS,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    f"[CoreLogicHook-Perception] 感知获取超时({_PERCEPTION_BUDGET_SECONDS}s)，降级为空感知"
                )
                perception = None
            logger.info(f"[TRACE] hook_perception_inject: get_perception 后 | elapsed={time.time() - _pm_start:.3f}s")
            if perception:
                perception_context = perception_manager.format_for_prompt(perception)

                # 【V2新增】从实时监控快照获取当前元素，注入向量知识
                try:
                    from core.dialog.dialogue_manager import dialogue_manager
                    _actual_user_id = ctx.extra.get('actual_user_id', ctx.user_id)
                    _rt_key = f"{_actual_user_id}_realtime"
                    _snapshot = dialogue_manager._user_task_snapshots.get(_rt_key, {})
                    _detected = _snapshot.get("objects", [])
                    if _detected:
                        _ui_knowledge = await _inject_ui_knowledge_to_prompt(
                            current_app=_snapshot.get("dominant_app", "unknown"),
                            detected_elements=_detected,
                            user_id=_actual_user_id,
                        )
                        if _ui_knowledge:
                            perception_context = f"{perception_context}\n\n{_ui_knowledge}"
                            logger.info(
                                f"[CoreLogicHook-Perception] UI 向量知识已注入，"
                                f"命中 {len([line for line in _ui_knowledge.split(chr(10)) if line.startswith('•')])} 个元素"
                            )
                except Exception as _ui_err:
                    logger.debug(f"[CoreLogicHook-Perception] UI 向量知识注入失败(非阻塞): {_ui_err}")

                ctx.extra['perception_context'] = perception_context
                ctx.working_memory.last_perception = perception
                logger.info(
                    f"[CoreLogicHook-Perception] 感知数据已注入: "
                    f"{perception.perception_type.value}"
                )
            else:
                logger.warning("[CoreLogicHook-Perception] 感知数据获取失败")
        else:
            logger.debug("[CoreLogicHook-Perception] 未触发感知能力")
    except Exception as e:
        logger.error(f"[CoreLogicHook-Perception] 感知能力激活失败: {e}", exc_info=True)
        ctx.extra['perception_context'] = ""

    # 【改造】原始感知数据写入 SystemState，供语音/动作模块直接读取
    try:
        from core.runtime import system_state
        if perception and hasattr(perception, 'perception_type'):
            system_state.set_sync("perception.raw", {
                "type": perception.perception_type.value if hasattr(perception.perception_type, 'value') else str(perception.perception_type),
                "content": getattr(perception, 'content', None),
                "metadata": getattr(perception, 'metadata', {}),
                "timestamp": getattr(perception, 'timestamp', time.time()),
            }, ttl=60)
        if perception_context:
            system_state.set_sync("perception.context_summary", perception_context[:500], ttl=60)
    except Exception:
        pass

    return ctx


# ── 3. 视觉感知 ──────────────────────────────────────────────────────────────

async def hook_vision_perception(ctx: HookContext, **kwargs) -> HookContext:
    """
    视觉感知处理（原 agent_loop.py:1096）

    期望 ctx.extra 包含:
        - change_detector: 变化检测器
        - last_vision_description: Optional[str]
        - vision_cache_timestamp: float
        - vision_enabled: bool
        - loop_state: LoopState 实例
        - actual_user_id: str

    输出写入 ctx.extra:
        - last_vision_description: Optional[str]
        - vision_cache_timestamp: float
    """
    change_detector = ctx.extra.get('change_detector')
    if not change_detector:
        logger.debug("[CoreLogicHook-Vision] change_detector 不可用，跳过")
        return ctx

    try:
        from core.vision.vision_processor import process_vision_perception_async

        user_instruction = _get_user_instruction(ctx)

        last_vision = ctx.extra.get('last_vision_description')
        vision_ts = ctx.extra.get('vision_cache_timestamp', 0)

        last_vision, vision_ts = await process_vision_perception_async(
            user_instruction=user_instruction,
            change_detector=change_detector,
            last_vision_description=last_vision,
            vision_cache_timestamp=vision_ts,
            working_memory=ctx.working_memory,
            user_id=ctx.extra.get('actual_user_id', ctx.user_id),
            vision_enabled=ctx.extra.get('vision_enabled', True),
            loop_state=ctx.extra.get('loop_state'),
        )

        ctx.extra['last_vision_description'] = last_vision
        ctx.extra['vision_cache_timestamp'] = vision_ts
        if last_vision:
            logger.info("[CoreLogicHook-Vision] 视觉感知已更新")
    except Exception as e:
        logger.warning(f"[CoreLogicHook-Vision] 视觉感知失败: {e}")

    return ctx


# ── 4. 上下文组装（记忆检索+TokenBudget） ────────────────────────────────────

async def hook_context_assembly(ctx: HookContext, **kwargs) -> HookContext:
    """
    Prompt 上下文组装（原 agent_loop.py:1003-1009, 1071-1091）

    期望 ctx.extra 包含:
        - phase_ctx: PhaseContext 实例
        - assembler: ContextAssembler 实例
        - user_instruction: str
        - task_type: str
        - exploration_engine: Any
        - exploration_context: Any
        - reflection_context: str
        - belief_confidence: float
        - strategy_recommendation: str
        - world_model_manager: Any
        - perception_context: str
        - smart_context: Dict[str, str]
        - experience_context: str
        - execution_history: List[Dict]
        - session_id: str
        - user_id: str
        - effective_task_id: str
        - phase_anchor_manager: Any
        - last_vision_description: Any

    输出写入 ctx.extra:
        - memory_context: str
        - memory_metadata: Optional[Dict]
        - full_system_prompt: str
        - budget_report: Optional[Dict]
        - exploration_enhancement: str
        - layer_prompt: str
        - three_views_prompt: str
        - reflection_section: str
        - experience_context: str
        - world_model_section: str
    """
    try:
        phase_ctx = ctx.extra.get('phase_ctx')
        assembler = ctx.extra.get('assembler')

        if phase_ctx is None or assembler is None:
            logger.warning("[CoreLogicHook-Context] phase_ctx 或 assembler 缺失，跳过上下文组装")
            return ctx

        # 1. 记忆检索（assemble_context_phase）
        logger.info(f"[TRACE] hook_context_assembly: assemble_context_phase 前 | ts={time.time():.3f}")
        from core.agent.context_assembler import assemble_context_phase
        memory_context, memory_metadata = await assemble_context_phase(phase_ctx)
        logger.info(f"[TRACE] hook_context_assembly: assemble_context_phase 后 | ts={time.time():.3f}")
        ctx.extra['memory_context'] = memory_context
        ctx.extra['memory_metadata'] = memory_metadata
        if memory_metadata:
            ctx.working_memory.last_memory_metadata = memory_metadata

        # 2. Prompt 片段准备（prompt_assembly_bridge）
        logger.info(f"[TRACE] hook_context_assembly: prepare_prompt_fragments_async 前 | ts={time.time():.3f}")
        from core.agent.prompt_assembly_bridge import prepare_prompt_fragments_async
        _fragments = await prepare_prompt_fragments_async(phase_ctx)
        logger.info(f"[TRACE] hook_context_assembly: prepare_prompt_fragments_async 后 | ts={time.time():.3f}")
        ctx.extra['exploration_enhancement'] = _fragments.exploration_enhancement
        ctx.extra['layer_prompt'] = _fragments.layer_prompt
        ctx.extra['three_views_prompt'] = _fragments.three_views_prompt
        ctx.extra['reflection_section'] = _fragments.reflection_section
        ctx.extra['experience_context_out'] = _fragments.experience_context
        ctx.extra['world_model_section'] = _fragments.world_model_section
        ctx.extra['exploration_context_out'] = _fragments.exploration_context

        # 3. 提示词最终组装（PromptFinalizer）
        logger.info(f"[TRACE] hook_context_assembly: prompt_finalizer.finalize_async 前 | ts={time.time():.3f}")
        from core.prompt.prompt_finalizer import prompt_finalizer
        user_instruction = _get_user_instruction(ctx)

        # 【BTC可观测层】将交易上下文合并到感知上下文中
        perception_context = ctx.extra.get('perception_context', '')
        btc_context = ctx.extra.get('btc_context', '')
        if btc_context:
            perception_context = f"{perception_context}\n\n{btc_context}".strip()

        # 获取当前轮次，用于提示词 dump 文件名
        loop_state = ctx.extra.get('loop_state')
        round_count = getattr(loop_state, 'round_count', 0) if loop_state else 0

        full_system_prompt, budget_report = await prompt_finalizer.finalize_async(
            user_id=ctx.user_id,
            user_instruction=user_instruction,
            working_memory=ctx.working_memory,
            work_mode=ctx.extra.get('work_mode', 'daily'),
            effective_task_id=ctx.extra.get('effective_task_id', ''),
            phase_anchor_manager=ctx.extra.get('phase_anchor_manager'),
            last_vision_description=ctx.extra.get('last_vision_description'),
            assembler=assembler,
            smart_context=ctx.extra.get('smart_context', {}),
            perception_context=perception_context,
            memory_context=memory_context,
            exploration_enhancement=_fragments.exploration_enhancement,
            layer_prompt=_fragments.layer_prompt,
            three_views_prompt=_fragments.three_views_prompt,
            reflection_context=_fragments.reflection_section,
            experience_context=_fragments.experience_context,
            world_model_section=_fragments.world_model_section,
            execution_history=ctx.extra.get('execution_history', []),
            session_id=ctx.session_id,
            round_count=round_count,
        )
        logger.info(f"[TRACE] hook_context_assembly: prompt_finalizer.finalize_async 后 | ts={time.time():.3f}")
        ctx.extra['full_system_prompt'] = full_system_prompt
        ctx.extra['budget_report'] = budget_report

        logger.info("[CoreLogicHook-Context] 上下文组装+PromptFinalize 完成")
    except Exception as e:
        logger.error(f"[CoreLogicHook-Context] 上下文组装失败: {e}", exc_info=True)

    return ctx


# ── 5. BTC 交易上下文注入（AI可观测层）────────────────────────────────────────

async def hook_btc_context_inject(ctx: HookContext, **kwargs) -> HookContext:
    """
    BTC 交易状态上下文注入（AI可观测层）

    从 EventBus 获取用户最近的交易活动摘要，在合适的时机注入到
    Agent 的 prompt 上下文中，让 AI 自然感知交易状态。

    设计约束：
        - 仅当最近 30 秒内有新事件时才注入（避免密集轰炸）
        - 摘要控制在 100 字内（避免占用过多 token）
        - 无交易活动时零开销（不注入任何内容）

    注册: before_prompt, priority=80
    输出写入 ctx.extra:
        - btc_context: str  (空字符串表示无活动)
    """
    user_id = ctx.user_id
    if not user_id:
        return ctx

    try:
        from core.btc_integration.event_bus import event_bus
        summary = event_bus.get_summary(user_id)

        if not summary.get("has_activity"):
            ctx.extra['btc_context'] = ""
            return ctx

        # 只有最近30秒内有新事件才注入（避免每轮对话都携带）
        if summary.get("event_count_30s", 0) == 0:
            ctx.extra['btc_context'] = ""
            return ctx

        summary_text = summary.get("summary_text", "")
        if not summary_text:
            ctx.extra['btc_context'] = ""
            return ctx

        # 格式化注入文本（自然语言，100字内）
        btc_context = f"[交易状态] {summary_text}"
        ctx.extra['btc_context'] = btc_context[:120]  # 硬上限120字符

        logger.debug(f"[CoreLogicHook-BTC] 交易上下文已注入: {btc_context[:80]}...")

    except Exception as e:
        logger.debug(f"[CoreLogicHook-BTC] 交易上下文注入失败（非关键）: {e}")
        ctx.extra['btc_context'] = ""

    return ctx


# ── 6. 世界模型预测 ──────────────────────────────────────────────────────────

async def hook_world_model_prediction(ctx: HookContext, **kwargs) -> HookContext:
    """
    世界模型预测（原 agent_loop.py:1329-1370）

    期望 kwargs 包含:
        - parsed: Dict（含 tool, params）

    期望 ctx.extra 包含:
        - execution_history: List[Dict]

    输出写入 ctx.extra:
        - wm_prediction_data: Dict
        - wm_prediction_text: str
    """
    parsed = kwargs.get('parsed', {})
    # 兼容 dict 和 dataclass 对象（如 ParsedIntent）
    if isinstance(parsed, dict):
        tool_id = parsed.get('tool') or parsed.get('tool_id') or parsed.get('target_tool')
        tool_params = parsed.get('params', {})
    else:
        tool_id = getattr(parsed, 'tool', None) or getattr(parsed, 'tool_id', None) or getattr(parsed, 'target_tool', None)
        tool_params = getattr(parsed, 'params', {}) or {}

    if not tool_id:
        return ctx

    try:
        from core.world_model import get_world_model_manager
        world_model_manager = get_world_model_manager()

        user_instruction = _get_user_instruction(ctx)

        execution_history = ctx.extra.get('execution_history', [])

        current_state = {
            'task_context': {
                'goal': user_instruction,
                'task_id': getattr(ctx.task, 'id', None) if ctx.task else None
            },
            'current_tool': tool_id,
            'execution_history': execution_history
        }

        predictions = await world_model_manager.predict_action_outcomes(
            current_state,
            [{'tool_id': tool_id, 'params': tool_params}]
        )

        wm_prediction_text = ""
        wm_prediction_data = {}

        if predictions and predictions.get('predictions'):
            pred = predictions['predictions'][0]
            wm_prediction_data = {
                'confidence': int(pred.get('success_prob', 0) * 100),
                'suggestion': pred.get('recommendation', ''),
                'risk': pred.get('recommendation', '') if pred.get('risk', 0) > 0.5 else '低风险',
                'similar_tasks': len(predictions.get('predictions', []))
            }
            wm_prediction_text = (
                f"【世界模型预测】\n"
                f"  工具: {tool_id}\n"
                f"  成功率: {pred.get('success_prob', 0)*100:.0f}%\n"
                f"  风险: {pred.get('risk', 0)*100:.0f}%\n"
                f"  建议: {pred.get('recommendation', '')}\n"
            )
            if pred.get('risk', 0) > 0.7 and pred.get('confidence', 0) > 0.5:
                logger.warning(
                    f"[CoreLogicHook-WorldModel] 高风险操作检测: {tool_id}, "
                    f"风险={pred['risk']*100:.0f}%"
                )

        ctx.extra['wm_prediction_data'] = wm_prediction_data
        ctx.extra['wm_prediction_text'] = wm_prediction_text
        logger.debug(f"[CoreLogicHook-WorldModel] 预测完成: {tool_id}")
    except Exception as e:
        logger.debug(f"[CoreLogicHook-WorldModel] 预测获取失败: {e}")
        ctx.extra['wm_prediction_data'] = {}
        ctx.extra['wm_prediction_text'] = ""

    return ctx


# ── 注册函数 ─────────────────────────────────────────────────────────────────

def register_core_logic_hooks(hooks_instance):
    """
    注册所有核心逻辑 Hook 处理器到 AgentLoopHooks 实例。

    Args:
        hooks_instance: AgentLoopHooks 实例（即 agent_loop_hooks）
    """
    # before_prompt 链：干预 → 感知 → 上下文组装（含 finalize）
    # 感知在决策前触发，让LLM能看到当前屏幕再选择工具
    hooks_instance.register('before_prompt', hook_intervention_check, priority=100)
    hooks_instance.register('before_prompt', hook_perception_inject, priority=92)
    hooks_instance.register('before_prompt', hook_btc_context_inject, priority=88)
    hooks_instance.register('before_prompt', hook_context_assembly, priority=85)

    # before_tool 链：世界模型预测
    hooks_instance.register('before_tool', hook_world_model_prediction, priority=95)

    # after_tool 链：感知注入（失败时才学习，不会才看屏幕）
    hooks_instance.register('after_tool', hook_perception_inject, priority=15)

    logger.info("[CoreLogicHooks] 核心决策逻辑 Hook 注册完成")
