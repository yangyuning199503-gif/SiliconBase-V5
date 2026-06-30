#!/usr/bin/env python3
"""
LoopInitialization - AgentLoop 初始化段提取
"""

import re
import time
import uuid
from dataclasses import dataclass
from typing import Any

from core.agent.agent_loop_hooks import HookContext
from core.agent.agent_runtime import AgentRuntime
from core.config import config
from core.logger import logger
from core.session.state_snapshot import get_snapshot_manager

from ..session.runtime_state import get_state_persistence
from ..sync.realtime_sync import get_realtime_sync_manager

sync = get_realtime_sync_manager()


@dataclass
class LoopInitResult:
    actual_user_id: str
    user_id: str
    voice_instance: Any
    max_rounds: int
    work_mode: str
    user_instruction: str
    user_instruction_for_session: str
    task_type: str
    state: Any
    working_memory: Any
    loop_state: Any
    execution_history: list[dict]
    hook_ctx: Any
    trace_id: str
    precision_parser: Any
    announcer: Any
    session: Any
    pausable_task_sm: Any
    snapshot_manager: Any
    task_state: Any
    start_step: int
    effective_task_id: str
    phase_anchor_manager: Any
    _agent_runtime: AgentRuntime
    smart_context_manager: Any
    smart_context_enabled: bool
    change_detector: Any
    last_vision_description: Any
    vision_cache_timestamp: float
    vision_enabled: bool
    perception_manager: Any
    exploration_engine: Any
    exploration_context: Any
    task_stage: Any
    task_profile: Any
    reflection_context: str
    belief_confidence: float
    strategy_recommendation: str
    progress_tracker: Any
    feature_recovery: Any
    async_user_id: str
    MAX_SAFETY_ROUNDS: int = 100
    SAFETY_WARNING_THRESHOLD: int = 10
    STOP_CHECK_INTERVAL: int = 1
    initial_steps: Any = None
    task_history: list[dict] = None



# 补充导入：从 agent_loop.py 顶部和条件导入块迁移
from core.agent.agent_loop_hooks import agent_loop_hooks
from core.agent.checkpoint_manager import checkpoint_manager
from core.agent.loop_types import LoopState, ProgressTracker
from core.agent.weak_connection_bridge import trigger_weak_connection_async
from core.evolution.exploration_engine import get_exploration_engine
from core.intent.nlp_intent_parser import get_announcer, get_precision_parser
from core.memory.working_memory import WorkingMemory
from core.reflector import reflector
from core.task.planner import get_planner
from core.utils.common import generate_task_id, get_voice_for_tts, set_voice_for_tts

# 条件导入块（与 agent_loop.py 保持一致）
try:
    from core.session.session_integration import session_integration
    SESSION_MANAGER_AVAILABLE = True
except ImportError:
    SESSION_MANAGER_AVAILABLE = False

try:
    from core.task.task_planning import infer_task_steps, send_task_breakdown_async
    TASK_PLANNING_AVAILABLE = True
except ImportError:
    TASK_PLANNING_AVAILABLE = False

try:
    from core.context.smart_context_manager import get_smart_context_manager
    SMART_CONTEXT_AVAILABLE = True
except ImportError:
    SMART_CONTEXT_AVAILABLE = False

try:
    from core.vision.perception_manager import get_perception_manager
    PERCEPTION_MANAGER_AVAILABLE = True
except ImportError:
    PERCEPTION_MANAGER_AVAILABLE = False

try:
    from tools.visual_understand import VisualUnderstand
    VISUAL_UNDERSTAND_AVAILABLE = True
except ImportError:
    VISUAL_UNDERSTAND_AVAILABLE = False

try:
    from core.vision.screen_change_detector import ScreenChangeDetector
    SCREEN_CHANGE_DETECTOR_AVAILABLE = True
except ImportError:
    SCREEN_CHANGE_DETECTOR_AVAILABLE = False

try:
    from core.agent.consciousness_bridge import apply_consciousness_analysis
    CONSCIOUSNESS_BRIDGE_AVAILABLE = True
except ImportError:
    CONSCIOUSNESS_BRIDGE_AVAILABLE = False

from .pause_confirmation_state_machine import PauseConfirmationManager as PausableTaskStateMachine


def _is_likely_single_step(user_instruction: str, chat_history: list) -> bool:
    """轻量启发式，判定是否为单步确定性任务。误判无伤害，仅用于跳过 heavy 组件初始化。"""
    if not user_instruction:
        return False

    # 排除多轮对话（有上下文依赖风险）
    if chat_history and len([m for m in chat_history if m.get("role") == "user"]) > 1:
        return False

    # 排除明显多步骤请求
    multi_step_kw = ["并", "和", "然后", "接着", "先", "再", "之后", "同时", "顺便", "一起"]
    if any(kw in user_instruction for kw in multi_step_kw):
        return False

    # 排除含逗号、顿号、分号等标点分隔的复合命令
    if re.search(r"[，、；,;]\s*\S+", user_instruction):
        return False

    # 排除口语化连动结构（如"帮我打开微信发个消息"）
    if re.search(r"帮我\s*.+?(打开|启动|运行|发|搜|找|写|点)", user_instruction):
        return False

    # 排除"打开/启动/运行 + 应用名 + 动作词"的复合命令
    # 注意："打开"本身是触发词，不作为后续动作词处理
    action_kw = ["搜索", "查找", "输入", "发送", "点击", "播放", "查询"]
    if any(kw in user_instruction for kw in ["打开", "启动", "运行"]) and any(kw in user_instruction for kw in action_kw):
        return False

    # 排除指代词（上下文依赖）
    referential = r"(那个|这个|刚才|上次|之前|上面|下面|它|他|她|它们)"
    if re.search(referential, user_instruction):
        return False

    # 匹配确定性单步工具意图
    single_step_patterns = [
        r"(现在|当前)?\s*(几点|什么时间|日期|星期|几号)",
        r"(天气|气温|温度|下雪|下雨)",
        r"^[\d\s\+\-\*\/\(\)\.\,\%]+=\s*$",
        r"(翻译|translate).*?(成|到|为|英文|中文|日语)",
        r"(截图|截屏|屏幕)",
        r"(系统信息|电脑配置|内存|CPU|磁盘)",
        r"(音量|亮度|声音)",
        r"(复制|粘贴|剪贴板)",
        # 【修复】"打开/启动/运行 + 应用名" 是确定性单步任务，跳过重感知和3轮探索
        # 注意：支持空格分隔的多词英文名，如"打开 Visual Studio Code"
        r"^(打开|启动|运行)\s*(.+?)$",
    ]
    return any(re.search(p, user_instruction) for p in single_step_patterns)


async def initialize_loop_state(
    task, max_rounds, chat_history, chat_count, session_id,
    db_session_id,
    voice_instance, mode, user_id, stop_event, task_id,
    resume_from_checkpoint,
) -> LoopInitResult:
    """初始化 AgentLoop 运行时的所有状态。"""

    # 【重构更新】_voice_for_tts 已迁移到 core.utils.common
    actual_user_id = user_id if user_id else (session_id if session_id != "console" else "default")

    # [修复] 增强 voice_instance 同步机制，确保 speak_ai_reply 能正常工作  # 修复说明
    # 【并发修复-BUG-003】使用导入的线程安全函数操作全局变量
    if voice_instance is not None:  # 有语音实例
        existing_voice = get_voice_for_tts()
        if existing_voice is None:  # 全局为空
            set_voice_for_tts(voice_instance)  # 同步到全局
            print("[AgentLoop] [FIX] 同步 voice_instance 到 _voice_for_tts")  # 打印日志
        elif existing_voice is not voice_instance:  # 不同
            # [修复] 如果传入的实例与全局不同，更新全局变量  # 更新
            set_voice_for_tts(voice_instance)  # 更新全局
            print("[AgentLoop] [FIX] 更新 _voice_for_tts 为新的 voice_instance")  # 打印日志
    else:  # 无语音实例
        # [修复] 如果 voice_instance 为 None，尝试从全局恢复  # 恢复
        existing_voice = get_voice_for_tts()
        if existing_voice is not None:  # 全局有值
            voice_instance = existing_voice  # 恢复
            print("[AgentLoop] [FIX] 从全局变量恢复 voice_instance")  # 打印日志
        else:  # 全局也为空
            # [修复] 尝试从 dialogue_manager 恢复  # 尝试恢复
            try:  # 异常处理
                from core.dialog.dialogue_manager import dialogue_manager  # 导入
                if dialogue_manager.voice is not None:  # 有voice
                    voice_instance = dialogue_manager.voice  # 恢复
                    set_voice_for_tts(voice_instance)  # 同步到全局
                    print("[AgentLoop] [FIX] 从 dialogue_manager 恢复 voice_instance")  # 打印日志
            except Exception as e:  # 捕获异常
                print(f"[AgentLoop] [WARN] 无法从 dialogue_manager 恢复 voice: {e}")  # 打印警告

    # =============================================================================  # 分隔线
    # 【精准抓取初始化】初始化解析器和播报器  # 精准抓取初始化
    # =============================================================================  # 分隔线
    precision_parser = get_precision_parser(voice_instance)  # 获取精准解析器
    announcer = get_announcer(voice_instance)  # 获取播报器
    logger.info("[AgentLoop] 精准抓取解析器初始化完成")  # 记录日志

    if max_rounds is None:  # 未指定轮数
        max_rounds = config.get("agent.max_rounds", 15)  # 从配置获取

    # 根据mode参数设置工作模式上下文（用于提示词策略调整）  # 模式设置
    work_mode = mode  # 使用传入的mode作为默认值

    # 【修复】从 dual_mode_manager 获取用户实际模式，覆盖传入的参数
    try:
        from core.dialog.chat_mode_handler import dual_mode_manager
        user_mode_mgr = dual_mode_manager.get_mode_manager(actual_user_id)
        actual_mode = user_mode_mgr.get_current_mode()
        work_mode = actual_mode.value  # "daily" 或 "focus"
        if work_mode != mode:
            logger.info(f"[AgentLoop] 模式同步: 传入={mode}, 实际={work_mode}")
    except Exception as e:
        logger.warning(f"[AgentLoop] 获取用户实际模式失败，使用传入值: {e}")

    # ====== 【任务开始日志】输出清晰的任务信息 ======  # 任务开始日志
    # 【修复】使用 actual_user_id 作为用户ID，不要覆盖传入的 user_id 为 session_id
    task_type = getattr(task, 'type', 'unknown')  # 获取任务类型
    # 【静默失败阻断】安全获取intent
    _intent_5585 = getattr(task, 'intent', None) or {}
    task_desc = getattr(task, 'description', '') or _intent_5585.get('raw', '')[:50]  # 获取描述
    logger.info(f"[TaskStart] 任务类型: {task_type}, 描述: {task_desc}")  # 记录
    logger.info(f"[TaskStart] 用户: {actual_user_id}, 会话: {session_id}")  # 记录
    logger.info(f"[TaskStart] 预期结束条件: 返回FINAL_ANSWER或达到{max_rounds}轮")  # 记录

    # 初始化运行时状态  # 状态初始化
    state_persistence = get_state_persistence()  # 获取持久化
    if not hasattr(task, "_runtime_state"):  # 无运行时状态
        saved = state_persistence.load(task.id)  # 加载保存的状态
        if saved:  # 有保存的状态
            task._runtime_state = saved  # 恢复
        else:  # 无保存状态
            from core.session.runtime_state import RuntimeState  # 导入
            # 【静默失败阻断】安全获取intent
            _intent_5600 = getattr(task, 'intent', None) or {}
            task._runtime_state = RuntimeState(  # 创建新状态
                task_id=task.id,  # 任务ID
                user_instruction=_intent_5600.get("raw", "")  # 用户指令
            )  # 创建结束

    state = task._runtime_state  # 获取状态引用
    # 【静默失败阻断】安全获取intent
    _intent_5604 = getattr(task, 'intent', None) or {}
    user_instruction = _intent_5604.get("raw", "")  # 获取指令
    user_instruction_for_session = user_instruction

    # ═══════════════════════════════════════════════════════════════
    # 【Phase 7】异步版 SessionStorage 初始化（同步版在 L846）
    # ═══════════════════════════════════════════════════════════════
    session = None
    if SESSION_MANAGER_AVAILABLE:
        try:
            from core.utils.session_utils import generate_session_title
            session_title = generate_session_title(user_instruction_for_session)
            # 【P0-2】复用 DialogueManager 已创建的数据库 session，避免重复创建
            _session_query_id = db_session_id if db_session_id else (session_id if session_id != "console" else "")
            if db_session_id:
                logger.info(f"[SessionIntegration-Async] 使用 DialogueManager 提供的 db_session_id 查询: {db_session_id}")
            session = await session_integration.get_or_create_session(
                user_id=actual_user_id,
                session_id=_session_query_id,
                mode=mode,
                title=session_title,
            )
            if session:
                logger.info(f"[SessionIntegration-Async] Session准备就绪: {session.id}")
                if user_instruction_for_session:
                    await session_integration.save_messages(
                        session_id=session.id,
                        role="user",
                        content=user_instruction_for_session,
                        metadata={
                            "source": "agent_loop_async_init",
                            "task_type": task_type,
                            "mode": mode,
                            "task_id": task.id if hasattr(task, 'id') else None,
                        },
                    )
            else:
                logger.warning("[SessionIntegration-Async] Session获取/创建失败")
        except Exception as e:
            logger.error(f"[SessionIntegration-Async] Session初始化失败: {e}", exc_info=True)
            session = None

    # ═══════════════════════════════════════════════════════════════
    # 【Phase 7.2】异步版 memory_trigger 调用（原生 async 入口）
    # 同步版在 _run_agent_loop_impl 第 1098 行仍调用同步 on_user_input
    # 异步版使用 on_user_input_async，避免调用方显式 run_in_executor
    # ═══════════════════════════════════════════════════════════════
    if user_instruction:
        try:
            from core.memory.memory_trigger import on_user_input_async
            await on_user_input_async(
                user_id=actual_user_id,
                session_id=session_id,
                text=user_instruction,
                metadata={
                    "task_type": task_type,
                    "source": "agent_loop_async",
                    "mode": work_mode,
                    "task_id": task.id if hasattr(task, 'id') else None
                }
            )
            logger.debug(f"[AgentLoop-Async] 用户指令已触发存储: {user_instruction[:50]}...")
        except Exception as e:
            logger.warning(f"[AgentLoop-Async] 用户指令存储失败（非阻塞）: {e}")

    # =============================================================================  # 分隔线
    # 【长任务模式】初始化暂停确认状态机和快照管理器  # 长任务初始化
    # =============================================================================  # 分隔线
    pausable_task_sm = PausableTaskStateMachine()  # 创建状态机
    snapshot_manager = get_snapshot_manager()  # 获取快照管理器
    # 【静默失败阻断】hasattr无法检测None
    _metadata = getattr(task, 'metadata', None) or {}
    is_long_task = _metadata.get("is_long_task", False)  # 检查是否长任务

    # 如果是长任务，注册状态变更回调  # 回调注册
    if is_long_task:  # 是长任务
        def on_state_change(old_state, new_state):  # 定义回调
            logger.info(f"[LongTask] 状态变更: {old_state.name} -> {new_state.name}")  # 记录
            sync.emit_event("long_task_state_change", session_id, {  # 发送事件
                "old_state": old_state.name,  # 旧状态
                "new_state": new_state.name  # 新状态
            })  # 事件结束
        pausable_task_sm.register_state_change_callback(on_state_change)  # 注册回调
        logger.info(f"[LongTask] 任务 {task.id} 已标记为长任务")  # 记录日志

    sync.emit_event("start", session_id, {"instruction": user_instruction})  # 发送开始事件

    # 【Phase 8】三省六部流程透视镜（异步版）
    initial_steps = None
    if TASK_PLANNING_AVAILABLE:
        initial_steps = infer_task_steps(user_instruction)
        await send_task_breakdown_async(session_id, user_instruction, initial_steps)

    # ═════════════════════════════════════════════════════════════════════════════
    # 【断点续传第二阶段】任务初始化 - 支持从断点恢复（异步版本）
    # ═════════════════════════════════════════════════════════════════════════════
    task_state = None  # 任务执行状态
    start_step = 1  # 起始步骤（默认从头开始）

    if resume_from_checkpoint and task_id:
        # 从断点恢复
        effective_task_id = task_id  # 【修复】断点续传路径也定义 effective_task_id
        task_state = None
        try:
            # 【修复】如果 DialogueManager 已经提前恢复过 checkpoint 状态（状态为 RUNNING），
            # 直接使用内存中的状态，避免重复调用 resume_task_async 导致 "状态为 running，无法恢复"
            if task_id in checkpoint_manager._tasks:
                task_state = checkpoint_manager._tasks[task_id]
                logger.info(f"[Checkpoint] 使用内存中已恢复的任务状态: {task_id}, status={task_state.status}")
            else:
                task_state = await checkpoint_manager.resume_task_async(task_id)
        except Exception as e:
            logger.error(f"[AgentLoop] checkpoint_manager.resume_task_async 失败: {e}", exc_info=True)
            raise RuntimeError(f"从断点恢复任务 {task_id} 失败: {e}") from e
        if task_state:
            # 【修复】resume_task_async 内部已处理 can_resume 检查，此处不再二次检查
            # 避免因 RUNNING 状态（崩溃恢复场景）被误判为不可恢复
            logger.info(f"[Checkpoint] 从断点恢复任务 {task_id}，当前步骤: {task_state.current_step_number}")
            # 恢复工作记忆
            if "working_memory" in task_state.global_context:
                # 【修复BUG-4】使用 from_dict_full 恢复完整 working_memory（含 _message_history）
                state.working_memory = WorkingMemory.from_dict_full(task_state.global_context["working_memory"])
            else:
                state.working_memory = WorkingMemory(goal=user_instruction)
            start_step = task_state.get_resume_step_number()
        else:
            logger.warning(f"[Checkpoint] 无法恢复任务 {task_id}，将从头开始")
            start_step = 1
            task_state = None
    else:
        # 创建新任务
        start_step = 1
        effective_task_id = task_id or task.id if hasattr(task, 'id') else generate_task_id()
        task_state = None
        # 【修复】识别任务执行路径（task_queue vs WebSocket直接调用）
        execution_path = "direct"
        if task and hasattr(task, 'metadata') and isinstance(task.metadata, dict):
            execution_path = task.metadata.get("execution_path", "direct")
        try:
            task_state = await checkpoint_manager.create_task_async(
                task_id=effective_task_id,
                user_id=actual_user_id,  # 【修复】统一使用已计算的 actual_user_id
                total_steps=max_rounds if max_rounds else 100,  # 预估总步骤
                global_context={
                    "user_instruction": user_instruction,
                    "execution_path": execution_path
                }
            )
        except Exception as e:
            logger.warning(f"[AgentLoop] checkpoint_manager.create_task_async 失败: {e}")
        logger.info(f"[Checkpoint] 创建新任务 {effective_task_id}")

    # 初始化工作记忆
    if not hasattr(state, "working_memory") or state.working_memory is None:
        state.working_memory = WorkingMemory(goal=user_instruction)
    working_memory = state.working_memory  # 获取引用

    # ═══════════════════════════════════════════════════════════════
    # 【PhaseAnchor】异步版补齐：任务开始时保存阶段锚点
    # 同步版在 _run_agent_loop_impl 第 1369-1382 行有完整实现
    # ═══════════════════════════════════════════════════════════════
    try:
        from core.memory.phase_anchor import get_phase_anchor_manager
        phase_anchor_manager = get_phase_anchor_manager()
        await working_memory.save_phase_anchor("init", {"event": "任务开始", "instruction": user_instruction[:100]})
        _anchor_task_id = effective_task_id if 'effective_task_id' in locals() else (task_id or (task.id if hasattr(task, 'id') else None))
        await phase_anchor_manager.save(
            phase="init",
            data={"event": "任务开始", "instruction": user_instruction[:100]},
            user_id=actual_user_id,
            session_id=session_id,
            task_id=_anchor_task_id
        )
        logger.info(f"[PhaseAnchor-Async] 任务初始化，原始意图已保存: {user_instruction[:50]}...")
    except Exception as e:
        logger.error(f"[PhaseAnchor-Async] 保存阶段锚点失败: {e}", exc_info=True)

    # 【Phase 1】初始化 Runtime 和 HookContext（异步版本）
    _agent_runtime = AgentRuntime(
        session_id=session_id,
        user_id=user_id,
        mode=mode,
        voice_instance=voice_instance,
        chat_history=chat_history,
        chat_count=chat_count,
        task_id=task_id,
        max_rounds=max_rounds,
        stop_event=stop_event,
    )
    # 【P1-1】生成全局 trace_id，贯穿本次任务的信息闭环
    trace_id = str(uuid.uuid4())[:16]
    logger.info(f"[TraceID] 生成追踪ID: {trace_id}, 用户: {actual_user_id}, 任务: {task.id if task else 'N/A'}")

    hook_ctx = HookContext(
        task=task,
        working_memory=working_memory,
        session_id=session_id,
        user_id=actual_user_id,
        voice_instance=voice_instance,
        mode=mode,
        chat_history=chat_history,
        chat_count=chat_count,
        task_id=task_id,
        runtime=_agent_runtime,
        trace_id=trace_id,
    )
    # 透传意识线程的上下文标记（如 force_vision），供 Hook 链感知
    if task and hasattr(task, "metadata") and task.metadata:
        hook_ctx.extra["context_flag"] = task.metadata.get("context_flag")
    else:
        hook_ctx.extra["context_flag"] = None

    # =============================================================================
    # 【SmartContextManager集成】初始化智能上下文管理
    # =============================================================================
    smart_context_manager = None
    smart_context_enabled = False
    if SMART_CONTEXT_AVAILABLE:
        try:
            smart_context_manager = get_smart_context_manager()
            # 【静默失败阻断】使用已获取的_metadata
            constraints = _metadata.get("constraints", []) if _metadata else []
            smart_context_manager.initialize_task(
                task_id=effective_task_id,
                goal=user_instruction,
                constraints=constraints,
                user_id=actual_user_id
            )
            smart_context_enabled = True
            logger.info(f"[SmartContext] 任务 {effective_task_id} 已初始化智能上下文管理")
        except Exception as e:
            logger.warning(f"[SmartContext] 初始化失败: {e}")

    # ═════════════════════════════════════════════════════════════════════════════
    # 【P0-1 快速路径】单步任务提前判定，跳过 heavy 组件初始化
    # ═════════════════════════════════════════════════════════════════════════════
    is_fast_path = _is_likely_single_step(user_instruction, chat_history)
    if is_fast_path:
        logger.info(f"[FastPath] 判定为单步任务: '{user_instruction[:50]}...'，跳过感知/视觉/探索初始化")

    # =============================================================================
    # 【视觉感知初始化】异步版本
    # =============================================================================
    change_detector = None
    last_vision_description = None
    vision_cache_timestamp = 0
    vision_enabled = False

    if not is_fast_path:  # 【P0-1】fast path 跳过视觉模型初始化
        # 【P1-PEP8修复】检查视觉模型是否可用（使用顶部导入）
        if VISUAL_UNDERSTAND_AVAILABLE:
            try:
                # 检查降级状态，避免重复实例化探测
                if not VisualUnderstand.is_degraded():
                    vision_enabled = True
                    logger.info("[Vision] ✅ 异步版视觉模型已启用")
                else:
                    logger.warning("[Vision] ❌ 异步版视觉模型处于降级状态")
            except Exception as e:
                logger.warning(f"[Vision] ❌ 异步版视觉模型初始化失败: {e}")
                logger.warning("[Vision] 如需启用视觉感知，请在global.yaml中配置 ai.vision 节点")
        else:
            logger.info("[Vision] 异步版视觉模型不可用（VisualUnderstand导入失败）")

        # 初始化变化检测器
        if SCREEN_CHANGE_DETECTOR_AVAILABLE and vision_enabled:
            threshold = config.get("vision.change_threshold", 5)
            change_detector = ScreenChangeDetector(threshold=threshold)
            logger.info(f"[AgentLoop] 异步版屏幕变化检测已启用 (threshold={threshold})")

    # ═════════════════════════════════════════════════════════════════════════════
    # 【Phase 2 Week 3 - 任务2】初始化PerceptionManager（异步版本）
    # ═════════════════════════════════════════════════════════════════════════════
    perception_manager = None

    if not is_fast_path and PERCEPTION_MANAGER_AVAILABLE:  # 【P0-1】fast path 跳过感知管理器初始化
        try:
            perception_manager = get_perception_manager(
                user_id=actual_user_id,
                session_id=session_id
            )
            logger.info(f"[PerceptionManager] 异步版感知管理器已初始化: user={actual_user_id}")
        except Exception as e:
            logger.error(f"[PerceptionManager] 异步版初始化失败: {e}")
            perception_manager = None

    # 记录对话计数和工作模式到工作记忆（供提示词构建使用）  # 记录元信息
    working_memory.chat_count = chat_count  # 对话计数
    working_memory.mode = work_mode  # 工作模式

    # [Planner] 任务2：添加计划摘要到提示词  # Planner集成
    if not resume_from_checkpoint:  # 【修复】断点续传时跳过，避免 system 消息重复叠加
        try:  # 异常处理
            if hasattr(working_memory, 'ai_plan_id'):  # 有计划ID
                planner = get_planner()  # 获取规划器
                plan_summary = planner.get_plan_summary(working_memory.ai_plan_id)  # 获取摘要
                if plan_summary and plan_summary.get('total_steps', 0) > 0:  # 有步骤
                    working_memory.append({  # 添加
                        "role": "system",  # 系统角色
                        "content": f"[计划摘要] 共{plan_summary.get('total_steps', 0)}步，目标: {plan_summary.get('goal', '')}"  # 内容
                    })  # 添加结束
                    logger.info(f"[Planner] 注入计划摘要: {plan_summary.get('goal', '')}")  # 记录日志
        except Exception as e:  # 捕获异常
            logger.debug(f"[Planner] 添加计划摘要失败（不影响执行）: {e}")  # 记录调试日志

    # ====== 【目标系统调用】添加当前目标到工作记忆 ======  # 目标系统
    if not resume_from_checkpoint:  # 【修复】断点续传时跳过，避免 system 消息重复叠加
        try:  # 异常处理
            from core.strategy.goal_system import get_goal_system  # 导入
            goal_system = get_goal_system()  # 获取系统
            active_goal = goal_system.get_top_priority_goal()  # 获取活跃目标
            if active_goal:  # 有目标
                working_memory.append({  # 添加
                    "role": "system",  # 系统角色
                    "content": f"[当前目标] {active_goal.description}（优先级: {active_goal.priority}）"  # 内容
                })  # 添加结束
                logger.info(f"[GoalSystem] 注入活跃目标到工作记忆: {active_goal.description}")  # 记录日志
        except Exception as e:  # 捕获异常
            logger.warning(f"[GoalSystem] 获取活跃目标失败（不影响执行）: {e}")  # 记录警告

    # 根据对话计数调整策略（高轮数对话可能需要更激进的提示词）  # 策略调整
    if chat_count > 10:  # 高对话计数
        logger.debug(f"[AgentLoop] 高对话计数会话: {chat_count}轮，启用记忆增强策略")  # 记录日志

    # [3-7架构] 初始化探索引擎，获取任务阶段  # 3-7架构
    exploration_engine = get_exploration_engine()  # 获取引擎
    task_stage, task_profile = exploration_engine.get_task_stage(user_instruction)  # 获取阶段
    exploration_context = None  # 探索上下文

    if not is_fast_path and task_stage.value == "unknown":  # 【P0-1】fast path 跳过探索
        # 全新任务，开始3轮探索  # 开始探索
        exploration_context = exploration_engine.start_exploration(user_instruction, session_id)  # 启动
        logger.info(f"[3-7架构] 开始3轮探索: {user_instruction}")  # 记录日志
    elif task_stage.value in ["known", "mastered"]:  # 已知任务
        # 已知任务，使用经验  # 使用经验
        logger.info(f"[3-7架构] 使用已有经验: {user_instruction} (执行{task_profile.attempt_count}次)")  # 记录日志

    # 在工作记忆中记录探索状态  # 记录探索状态
    working_memory.exploration_round = 0  # 轮次初始化为0
    working_memory.task_stage = task_stage.value  # 记录阶段

    # ═════════════════════════════════════════════════════════════════════════════
    # 【P0断裂点#2修复】反思结果实时回流到提示词（异步版本初始化）
    # ═════════════════════════════════════════════════════════════════════════════
    reflection_context = ""
    belief_confidence = 0.5
    strategy_recommendation = ""

    try:
        if reflector is not None:
            from core.reflector import get_reflection_context, get_strategy_recommendation

            reflection_context = get_reflection_context(
                user_id=actual_user_id,
                current_intent=user_instruction,
                current_tools=[]  # 初始为空，后续轮次会更新
            )

            strategy_recommendation = get_strategy_recommendation({
                "task": user_instruction,
                "step_count": 0,
                "recent_tools": []
            })

            if reflection_context:
                logger.info(f"[ReflectionFlow-Async] 反思上下文已初始化: {len(reflection_context)}字符")
        else:
            logger.debug("[AgentLoop-Async] Reflector未初始化，跳过反思结果回流")
    except Exception as e:
        logger.warning(f"[AgentLoop-Async] 反思结果回流初始化失败: {e}")

    # 初始化循环控制  # 循环控制初始化
    loop_state = LoopState()  # 创建循环状态
    loop_state.max_rounds = max_rounds  # 最大轮数
    loop_state.start_time = time.time()  # 开始时间

    # 【新增】如果是恢复任务，恢复核心计数器
    if resume_from_checkpoint and task_state and start_step > 0:
        loop_state.round_count = start_step - 1  # 确保下一轮 increment 后正确对齐
        # 如有 chat_count 等也需恢复
        if hasattr(task_state, 'chat_count'):
            loop_state.chat_count = task_state.chat_count

    progress_tracker = ProgressTracker()  # 进度跟踪器
    if resume_from_checkpoint and task_state and getattr(task_state, 'steps', None):
        execution_history = [
            {"tool": step.tool_name, "params": step.tool_params, "result": step.output_result}
            for step in task_state.steps[:start_step]
        ]
    else:
        execution_history = []  # 执行历史

    # 【Phase 8】意识系统已抽取到 consciousness_bridge（纯异步版）
    if CONSCIOUSNESS_BRIDGE_AVAILABLE:
        await apply_consciousness_analysis(
            working_memory=working_memory,
            execution_history=execution_history,
            loop_state=loop_state,
        )

    # ═════════════════════════════════════════════════════════════════════════════
    # 【功能恢复 P0-P1】初始化功能恢复集成器（异步版本）
    # ═════════════════════════════════════════════════════════════════════════════
    feature_recovery = None
    try:
        from core.agent.loop_types import FeatureRecoveryIntegration
        feature_recovery = FeatureRecoveryIntegration()
        logger.info("[功能恢复-Async] 集成器已初始化")
    except Exception as e:
        logger.debug(f"[功能恢复-Async] 集成器初始化失败: {e}")
        feature_recovery = None

    # 【安全限制】软性安全上限 - 保持AI自主权的同时防止无限循环
    MAX_SAFETY_ROUNDS = 100  # 软性安全上限（AI在100轮内有完全自主权）
    SAFETY_WARNING_THRESHOLD = 10  # 接近上限提醒阈值（剩余10轮时提醒）

    # 【用户级并发控制】检查间隔（每多少轮检查一次终止信号）
    # 【修复】从3轮改为1轮，提高中断响应速度
    STOP_CHECK_INTERVAL = 1

    # 确定用户ID（用于并发控制检查）
    async_user_id = user_id if user_id else (session_id if session_id != "console" else "default")
    print(f"[DEBUG-LoopInit] user_id={user_id}, session_id={session_id}, async_user_id={async_user_id}", flush=True)

    # ═════════════════════════════════════════════════════════════════════════════
    # 【断点续传第二阶段】在循环开始前保存初始断点（异步版本）
    # ═════════════════════════════════════════════════════════════════════════════
    if task_state:
        try:
            await checkpoint_manager.save_checkpoint_async(
                task_id=task_state.task_id,
                checkpoint_name="任务开始",
                working_memory=working_memory  # 【修复BUG-2】传入 working_memory 确保保存到断点
            )
            logger.info(f"[Checkpoint] 已保存初始断点: {task_state.task_id}")
        except Exception as e:
            logger.warning(f"[Checkpoint] 保存初始断点失败: {e}")

    # ═════════════════════════════════════════════════════════════════════════════
    # 【Phase 7】弱连接触发已外迁至 weak_connection_bridge（异步版）
    await trigger_weak_connection_async(
        work_mode=work_mode,
        working_memory=working_memory,
    )

    # 主循环  # 主循环开始
    # 【修复】添加软性安全上限，保持AI在100轮内的完全自主权
    # 【Phase 1】before_loop Hook（异步版本）
    hook_ctx = await agent_loop_hooks.execute_async('before_loop', hook_ctx)

    return LoopInitResult(
        actual_user_id=actual_user_id,
        user_id=user_id,
        voice_instance=voice_instance,
        max_rounds=max_rounds,
        work_mode=work_mode,
        user_instruction=user_instruction,
        user_instruction_for_session=user_instruction_for_session,
        task_type=task_type,
        state=state,
        working_memory=working_memory,
        loop_state=loop_state,
        execution_history=execution_history,
        hook_ctx=hook_ctx,
        trace_id=trace_id,
        precision_parser=precision_parser,
        announcer=announcer,
        session=session,
        pausable_task_sm=pausable_task_sm,
        snapshot_manager=snapshot_manager,
        task_state=task_state,
        start_step=start_step,
        effective_task_id=effective_task_id,
        phase_anchor_manager=phase_anchor_manager,
        _agent_runtime=_agent_runtime,
        smart_context_manager=smart_context_manager,
        smart_context_enabled=smart_context_enabled,
        change_detector=change_detector,
        last_vision_description=last_vision_description,
        vision_cache_timestamp=vision_cache_timestamp,
        vision_enabled=vision_enabled,
        perception_manager=perception_manager,
        exploration_engine=exploration_engine,
        exploration_context=exploration_context,
        task_stage=task_stage,
        task_profile=task_profile,
        reflection_context=reflection_context,
        belief_confidence=belief_confidence,
        strategy_recommendation=strategy_recommendation,
        progress_tracker=progress_tracker,
        feature_recovery=feature_recovery,
        async_user_id=async_user_id,
        MAX_SAFETY_ROUNDS=MAX_SAFETY_ROUNDS,
        SAFETY_WARNING_THRESHOLD=SAFETY_WARNING_THRESHOLD,
        STOP_CHECK_INTERVAL=STOP_CHECK_INTERVAL,
        initial_steps=initial_steps,
        task_history=[
            {
                "tool": step.tool_name,
                "params": step.tool_params or {},
                "success": step.success if step.success is not None else False,
                "task_desc": step.step_goal or "",
                "error_info": step.error_message or ""
            }
            for step in task_state.steps[:start_step]
        ] if (resume_from_checkpoint and task_state and getattr(task_state, 'steps', None)) else [],
    )
