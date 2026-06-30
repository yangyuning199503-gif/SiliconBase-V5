#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
"""
精简版 Agent Loop - 基于模块化设计
- 支持多轮AI调用，可连续执行多个工具
- 整合语音和文本输入
- 游戏化分层交互（Layer 1/2/3）
- 2026-02-22 重构：拆分为多个职责单一的文件

任务类型定义：
- SIMPLE: 单步任务（查询天气、计算等），无需工具调用
- TOOL_CALL: 单工具调用任务（打开应用、搜索等）
- MULTI_STEP: 多步骤任务（需要规划、执行多个工具）
- CONVERSATION: 纯对话任务（无需工具，直接回答）
"""

import asyncio  # 导入异步IO模块，支持异步操作
import hashlib  # 【P0修复】导入哈希模块用于重复调用防御
import json  # 【P0修复】导入JSON模块用于工具参数哈希
import re  # 导入正则表达式模块，用于文本处理
import threading  # 【线程安全修复】导入线程模块用于锁保护
import time  # 导入时间模块，用于时间戳和延时
import uuid  # 导入UUID模块用于生成唯一标识符
from concurrent.futures import ThreadPoolExecutor  # 【P0-性能修复】导入线程池执行器
from datetime import datetime  # 导入日期时间类
from pathlib import Path  # 导入路径类用于文件操作
from types import SimpleNamespace  # 导入简单命名空间用于动态对象
from typing import Any  # 导入类型注解

from core.diagnostic import (
    diagnostic_except_handler,
    safe_create_task,
)

# AgentLoop 后台线程池（供经验进化等后台任务使用）
_agent_loop_executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix="agent_loop_bg")

# 【跨循环DuplicateGuard】用户级工具结果缓存，用于子代理fallback等跨AgentLoop场景
_user_tool_result_cache: dict[str, dict[str, Any]] = {}
_TOOL_CACHE_TTL_SECONDS = 300  # 5分钟窗口，超过后允许用户主动重复

# 用于在run_agent_loop_async finally块中访问loop_state
_last_loop_state: dict[str, Any] = {}


def _apply_consciousness_directives(
    tool_id: str,
    actual_user_id: str,
    working_memory: Any,
) -> tuple[str, bool]:
    """
    应用来自意识线程的 ConsciousnessDirective。

    Returns:
        (new_tool_id, blocked): blocked=True 表示当前工具被 AVOID_TOOL 阻止。
    """
    try:
        from core.consciousness.Consciousness import get_consciousness
        from core.consciousness.directive_translator import DirectiveType
        from core.tool.tool_manager import tool_manager

        consciousness = get_consciousness(actual_user_id)
        if not consciousness or not hasattr(consciousness, "get_pending_directives"):
            return tool_id, False

        directives = consciousness.get_pending_directives(clear=True)
        if not directives:
            return tool_id, False

        available_tools = {t["id"] for t in tool_manager.list_tools()}
        now = time.monotonic()
        new_tool_id = tool_id

        for d in directives:
            if d["expires_at"] < now:
                continue
            dtype = d["directive_type"]
            target = d.get("target")
            reason = d.get("reason", "")

            if dtype == DirectiveType.FORCE_TOOL.value:
                if target and target in available_tools and target != new_tool_id:
                    logger.info(
                        f"[ConsciousnessDirective] 强制工具: {new_tool_id} -> {target} | {reason}"
                    )
                    new_tool_id = target
                    working_memory.append({
                        "role": "system",
                        "content": f"[意识指令] 强制使用 {target}：{reason}",
                    })
            elif dtype == DirectiveType.AVOID_TOOL.value and target and target == new_tool_id:
                logger.info(f"[ConsciousnessDirective] 阻止工具: {target} | {reason}")
                return new_tool_id, True
        return new_tool_id, False
    except Exception as e:
        logger.debug(f"[AgentLoop] 应用意识指令失败: {e}")
        return tool_id, False


async def shutdown_agent_loop_executor_async(timeout: float = 5.0):
    """关闭AgentLoop后台线程池（供 lifespan shutdown 调用）"""
    global _agent_loop_executor
    try:
        await asyncio.to_thread(_agent_loop_executor.shutdown, wait=True)
        logger.info("[AgentLoop] 后台线程池已关闭")
    except Exception as e:
        logger.error(f"[AgentLoop] 异步关闭线程池失败: {e}")


from core.agent.task_outcome_reporter import (
    report_task_completed,
    report_task_failed,
)
from core.config import config  # 导入全局配置对象
from core.interfaces import SafeDictAccessor  # 导入核心接口类
from core.logger import logger  # 导入日志记录器

# 【魔法数字修复】导入全局常量
try:
    from core.constants import MemoryWeights
except ImportError as e:
    logger.error(f"[AgentLoop] 导入MemoryWeights常量失败: {e}")
    # 定义 fallback 常量值
    class MemoryWeights:
        L2_SEMANTIC = 0.4
        L3_WORKFLOW = 0.3
        L4_EPISODIC = 0.2
        L5_PROCEDURAL = 0.1

# 【重构拆分】从 core.vision.vision_processor 导入视觉相关功能
from core.agent.agent_loop_hooks import HookContext, agent_loop_hooks  # 【Phase 1】Hook 注册机制
from core.agent.hooks.safety_hook import safety_hook  # 【Phase 6】安全审查 Hook
from core.agent.hooks.tool_hook import tool_hook  # 【Phase 3b】工具后处理 Hook
from core.agent.hooks.vision_hook import vision_hook  # 【Phase 3a】视觉验证 Hook
from core.agent.hooks.voice_hook import voice_hook  # 【Phase 6】语音播报 Hook
from core.agent.interrupt_handler import interrupt_handler  # 导入中断处理器

# 【协调层】动作协调器与行为选择器
from core.coordination import get_action_coordinator, get_behavior_selector
from core.coordination.action_coordinator import ActionType
from core.task.completion_analyzer import (
    TaskAnalysisResult,
    check_task_completed,
    get_task_completion_analyzer,
)
from core.task.task_queue import Task  # 导入任务队列系统
from core.utils.text_parser import (
    extract_natural_language,
    extract_thinking_from_response,
    extract_tool_calls_from_response,
    is_action_required,
)

from ..session.runtime_state import get_state_persistence  # 导入运行时状态持久化
from ..sync.realtime_sync import get_realtime_sync_manager  # 导入实时同步管理器
from .pause_confirmation_state_machine import LongTaskState as PausableTaskState  # 重命名为可暂停任务状态

# 【Phase 7】实时干预系统已抽取到 intervention_checker，提供异步接口
# 保留 realtime_intervention 的原始导入，供任务注册/注销使用
try:
    from core.agent.realtime_intervention import realtime_intervention
    from core.intervention.intervention_checker import REALTIME_INTERVENTION_AVAILABLE, intervention_checker
    logger.info("[AgentLoop] 实时干预系统已加载 (intervention_checker)")
except ImportError as e:
    REALTIME_INTERVENTION_AVAILABLE = False
    logger.error(f"[AgentLoop] 实时干预系统导入失败: {e}")

# 【Phase 7】SessionStorage 全链路已抽取到 session_integration，提供异步接口
try:
    from core.session.session_integration import session_integration
    SESSION_MANAGER_AVAILABLE = True
except ImportError as e:
    SESSION_MANAGER_AVAILABLE = False
    logger.error(f"[AgentLoop] SessionIntegration导入失败，session_messages存储将禁用: {e}")

# 【Phase 8】流程透视镜已抽取到 task_planning，提供异步接口
try:
    from core.task.task_planning import (
        request_user_confirmation,
        send_task_breakdown,
        send_tool_chain_planned,
    )
    TASK_PLANNING_AVAILABLE = True
except ImportError as e:
    TASK_PLANNING_AVAILABLE = False
    logger.error(f"[AgentLoop] TaskPlanning导入失败: {e}")

# 【Phase 8】意识系统已抽取到 consciousness_bridge，纯异步接口
try:
    from core.agent.consciousness_bridge import apply_consciousness_analysis
    CONSCIOUSNESS_BRIDGE_AVAILABLE = True
except ImportError as e:
    CONSCIOUSNESS_BRIDGE_AVAILABLE = False
    logger.error(f"[AgentLoop] ConsciousnessBridge导入失败: {e}")

# 导入新模块  # 注释：新拆分出的子模块
from core.agent.voice_strategy import (  # 语音策略【重构拆分】
    VoiceAnnounceStrategy,
)
from core.ai.ai_adapter import call_thinker_async  # AI调用适配器（同步/异步）
from core.intent.intent_handler import intent_handler  # 意图处理器
from core.intent.nlp_intent_parser import (  # NLP意图解析
    AICodeMarker,  # AI代码标记和解析输出
    IntentType,
    ParsedAIOutput,
    ParsedIntent,
    # 获取精准解析器和播报器
    get_intent_parser,  # 获取解析器和意图类型枚举
)
from core.memory.execution_memory import execution_memory  # 执行记忆
from core.memory.working_memory import WorkingMemory  # 工作记忆管理
from core.prompt.context_builder import context_builder  # 上下文构建器
from core.prompt.prompt_builder import prompt_builder  # 提示词构建器

# 【修复】导入重要性评估和关键决策检测
try:
    from core.strategy.importance_engine import ImportanceLevel, calculate_importance
    IMPORTANCE_ENGINE_AVAILABLE = True
except ImportError as e:
    IMPORTANCE_ENGINE_AVAILABLE = False
    calculate_importance = None
    ImportanceLevel = None
    logger.warning(f"[AgentLoop] 重要性评估引擎导入失败，重要性评估将禁用: {e}")

try:
    from core.strategy.key_decision_detector import detect_key_decision
    KEY_DECISION_DETECTOR_AVAILABLE = True
except ImportError as e:
    KEY_DECISION_DETECTOR_AVAILABLE = False
    detect_key_decision = None
    logger.warning(f"[AgentLoop] 关键决策检测器导入失败，关键决策检测将禁用: {e}")

# 【修复】导入AI生命感管理器用于智能播报过滤
try:
    from core.consciousness.life_presence import EventType, get_life_presence_manager, update_ai_state
    LIFE_PRESENCE_AVAILABLE = True
except ImportError as e:
    LIFE_PRESENCE_AVAILABLE = False
    get_life_presence_manager = None
    EventType = None
    update_ai_state = None
    logger.warning(f"[AgentLoop] AI生命感管理器导入失败，智能播报过滤将禁用: {e}")

from core.prompt.smart_prompt_engine import build_smart_context  # 智能提示词引擎

try:
    from core.world_model import (  # 统一从包入口导入世界模型接口
        get_world_model,
        get_world_model_manager,
    )
except Exception:
    get_world_model = None
    get_world_model_manager = None
# 【P1断裂点#3修复】导入进化系统
from core.evolution.evolution import evolution as evolution_manager

# NOTE: MemoryService 写操作（save_chat_turn / save_execution_record）使用 asyncio.create_task
# 抛后台执行，目的是非阻塞/fire-and-forget，而非规避同步 I/O（ChromaDB 已真异步化）。
from core.intent.function_trigger import TriggerType, get_function_trigger  # 功能触发器
from core.memory.memory_service import get_memory_service  # 统一异步记忆入口（替代 memory / AsyncMemory）
from core.memory.memory_trigger import on_user_input_async  # 【Phase 7.2】异步用户输入记忆存储
from core.monitoring.behavior_recognizer import check_behavior_anomaly, get_behavior_recognizer  # 行为识别器
from core.reflector.reflector import Reflector  # 【贝叶斯反思】导入Reflector类
from core.strategy.behavior_analyzer import get_behavior_analyzer  # 行为分析器
from core.task.planner import get_planner  # 任务规划器
from core.traceability import record_tool, set_trace_id  # 【P1-1】信息闭环追踪

# 【P1-交易指挥官事件总线订阅】接收交易报告并注入工作记忆
try:
    from core.sync.event_bus import event_bus as _main_event_bus
except Exception as e:
    logger.warning(f"[AgentLoop] event_bus导入失败: {e}")
    _main_event_bus = None

# 【断点续传第二阶段】导入CheckpointManager
from core.agent.reflection_bridge import run_tool_failure_reflection

# 【阶段锚点修复】导入PhaseAnchorManager

# 【演示学习系统集成】导入演示学习集成模块
try:
    from core.evolution.procedure_learning_integration import (
        get_procedure_learning_integration,
    )
    PROCEDURE_LEARNING_INTEGRATION_AVAILABLE = True
except ImportError as e:
    logger.warning(f"[AgentLoop] 演示学习集成模块不可用: {e}")
    PROCEDURE_LEARNING_INTEGRATION_AVAILABLE = False

# 【Phase 7】幻觉检测器初始化已迁移到 SafetyHook，无需 agent_loop 处理
from core.exceptions import AgentLoopInterrupted  # 【Agent-5】导入经验记录异常和中断异常

# 【Week 2 - TokenBudgetManager集成】导入Token预算管理

# =============================================================================
# 【功能恢复 P0-P1】导入之前拆分但未使用的功能
# =============================================================================

# 4. 世界模型MCTS (P1)
try:
    from core.world_model import get_world_model
    WORLD_MODEL_MCTS_AVAILABLE = True
    logger.info("[功能恢复] 世界模型MCTS已加载")
except ImportError as e:
    WORLD_MODEL_MCTS_AVAILABLE = False
    # 【静默失败修复】功能模块导入失败必须是ERROR级别
    logger.error(f"[功能恢复] 世界模型MCTS导入失败: {e}")


# =============================================================================
# 【重构拆分】已迁移的模块导入
# =============================================================================

# 【重构拆分】core.task.completion_analyzer:
# - TaskType, CompletionScore, TaskAnalysisResult
# - TaskCompletionAnalyzer class
# - TaskCompletionConfig class
# - get_task_completion_analyzer()

# 【重构拆分】core.utils.common:
# - generate_task_id, get_current_user_id
# - is_critical_step, CRITICAL_TOOLS
# - set_voice_for_tts, get_voice_for_tts

# 【重构拆分】core.task.pause_manager:
# - pause_task_with_sync
# - is_long_task, register_long_task_callbacks
from core.task.pause_manager import (
    pause_task_with_sync,
)

# 保留别名以保持向后兼容
# check_task_completed / increment_force_continue_count 在 core.task.completion_analyzer 中直接调用，loop_utils 转发壳已删除


# 【重构拆分】TaskCompletionConfig 已迁移到 core.task.completion_analyzer
# 保留全局配置实例引用（从新模块导入）


# 【贝叶斯反思】Reflector单例实例 - 带错误保护
try:
    reflector = Reflector()
except Exception as e:
    logger.error(f"[AgentLoop] Reflector初始化失败: {e}")
    reflector = None

# 【实时同步管理器】带错误保护初始化，绝不静默失败
try:
    sync = get_realtime_sync_manager()  # 获取实时同步管理器实例（全局）
    if sync is None:
        raise RuntimeError("get_realtime_sync_manager() returned None")
    logger.info("[AgentLoop] RealtimeSyncManager initialized successfully")
except Exception as e:
    logger.critical(f"[AgentLoop] CRITICAL: RealtimeSyncManager初始化失败: {e}")
    # 不静默失败：抛出异常阻止系统继续启动
    raise RuntimeError(f"RealtimeSyncManager initialization failed: {e}") from e
_intent_parser = get_intent_parser()  # 获取意图解析器实例（全局）

# =============================================================================
# 【阶段四优化】语音播报智能策略系统
# =============================================================================
# 【重构拆分】语音策略已迁移到 core.agent.voice_strategy
# 以下保留 agent_loop.py 特定的 speak_ai_reply 实现（包含恢复逻辑）
# =============================================================================

# speak_ai_reply 已迁移到 core/agent/voice_utils.py


# =============================================================================
# 【Phase 2 Week 3 - 任务2】Session消息存储辅助函数
# =============================================================================

# 【重构拆分】_is_valid_uuid() 已迁移到 core.utils.session_utils
# 【重构拆分】_generate_session_title() 已迁移到 core.utils.session_utils

# 【重构拆分】以下函数已迁移到 core.utils.text_parser:
# - extract_thinking_from_response() -> extract_thinking_from_response()
# - _extract_tool_calls_from_response() -> extract_tool_calls_from_response()


# _prepare_response_with_memory_metadata 已迁移到 core/agent/loop_utils.py


# =============================================================================
# 【重构拆分】以下函数已迁移到 core.utils.text_parser:
# - extract_natural_language() -> extract_natural_language()
# - is_action_required() -> is_action_required()


# 【重构拆分】check_task_completed / increment_force_continue_count 在 core.task.completion_analyzer 中直接调用，loop_utils 转发壳已删除


# =============================================================================
# 【重构拆分】以下已迁移:
# - format_memories_as_subconscious() -> core.memory.formatter
# - format_memories_as_list() -> core.memory.formatter
# - escape_user_instruction() -> core.utils.security
# - sanitize_vision_description() -> core.utils.security
# =============================================================================

# =============================================================================
# 【暂停任务修复】带phase_anchors同步的暂停任务函数
# =============================================================================
# =============================================================================
# 【P1-PEP8修复】视觉感知处理函数 - 拆分过长代码块
# =============================================================================
# 【重构拆分】以下函数已迁移到独立模块:
# - pause_task_with_sync -> core.task.pause_manager
# - is_critical_step -> core.utils.common
# - generate_task_id -> core.utils.common
# - get_current_user_id -> core.utils.common
# =============================================================================

# 【Phase 4 权限标签系统】日常模式允许工具列表改为动态获取
# 硬编码列表保留作为兜底（fallback），但优先从权限标签系统获取
# 新增工具只需在 permission_tags.py 中注册 PermissionTag.DAILY_SAFE 即可自动生效

try:
    from core.safety.permission_tags import PermissionTag, get_tools_by_tag
    _DAILY_MODE_DYNAMIC_TOOLS = get_tools_by_tag(PermissionTag.DAILY_SAFE)
except ImportError:
    _DAILY_MODE_DYNAMIC_TOOLS = []

# 兜底：静态列表（与 permission_tags.py 中注册的工具保持一致）
_DAILY_MODE_STATIC_TOOLS = [
    "get_perception",      # 感知获取
    "call_user",           # 呼叫用户
    "memory_search",       # 记忆搜索
    "memory_add",          # 记忆添加
    "memory_list",         # 记忆列表
    "memory_update",       # 记忆更新
    "web_search",          # 网页搜索
    "pixel_capture",       # 截图
    "file_manager",        # 文件管理
    "get_tool_manual",     # 工具手册
    "system_info",         # 系统信息
    "launch_app",          # 启动应用
    "mouse_click",         # 鼠标点击
    "keyboard_input",      # 键盘输入
    "click_text",          # 文字点击
    "pixel_click",         # 像素点击
    "browser_open",        # 打开浏览器
    "web_fetch",           # 网页获取
    "window_action",       # 窗口操作
    "process_start",       # 启动进程
    "visual_understand",   # 视觉理解
    "vision_agent",        # 视觉Agent
    "btc_market_overview", # BTC市场概览
    "btc_status_query",    # BTC交易状态查询
    "btc_get_klines",      # BTC K线数据
    "btc_risk_assessment", # BTC风险评估
]

# 合并动态和静态列表（去重），动态列表优先
def _get_daily_mode_allowed_tools() -> list:
    """获取日常模式允许的工具列表（动态 + 静态兜底）"""
    tools = list(_DAILY_MODE_DYNAMIC_TOOLS) if _DAILY_MODE_DYNAMIC_TOOLS else list(_DAILY_MODE_STATIC_TOOLS)
    # 确保静态列表中的工具也在结果中（防止动态列表缺失时兜底）
    for t in _DAILY_MODE_STATIC_TOOLS:
        if t not in tools:
            tools.append(t)
    return tools

# 向后兼容：DAILY_MODE_ALLOWED_TOOLS 保持为列表
DAILY_MODE_ALLOWED_TOOLS = _get_daily_mode_allowed_tools()



_MAX_WORKING_MEMORY_LEN = 200  # 安全阈值


async def _trim_working_memory_async(working_memory):
    """给 working_memory 增加最大长度限制，防止长任务内存爆炸。
    兼容 list 和 WorkingMemory 对象。
    【Phase 1】统一为原生 async 接口，供异步主循环 await 调用。
    """
    # 获取消息列表
    if hasattr(working_memory, 'get_message_history'):
        # WorkingMemory 对象
        msgs = working_memory.get_message_history()
    elif isinstance(working_memory, list):
        msgs = working_memory
    else:
        return  # 无法处理，跳过

    if len(msgs) > _MAX_WORKING_MEMORY_LEN:
        # 保留系统消息和最近的消息，截断中间历史
        system_msgs = [m for m in msgs if m.get("role") == "system"]
        recent_msgs = msgs[-(_MAX_WORKING_MEMORY_LEN - len(system_msgs)):]
        msgs.clear()
        msgs.extend(system_msgs + recent_msgs)
        # 如果是 WorkingMemory，其内部 _message_history 已通过 msgs 引用直接修改
        # 无需额外赋值


async def run_agent_loop(task: Task,
                   max_rounds: int | None = None,
                   chat_history: list[dict[str, Any]] | None = None,
                   chat_count: int = 0,
                   session_id: str = "console",
                   voice_instance: Any | None = None,
                   mode: str = "daily",
                   user_id: str | None = None,
                   task_id: str | None = None,
                   resume_from_checkpoint: bool = False) -> tuple[str | None, WorkingMemory]:
    """
    ReAct主循环 - 用户级并发控制版本（Phase 1 全异步整改）

    包装函数：获取用户级锁，确保一个用户同时只能有一个AgentLoop运行。
    使用try-finally确保锁在任何情况下都会被释放。

    [Phase 1] 已统一为原生 async 入口，彻底删除 asyncio.run 同步桥接。
    调用方必须 await 本函数。
    """
    # 获取用户ID并申请循环锁
    actual_user_id = user_id if user_id else (session_id if session_id != "console" else "default")
    print(f"[DEBUG-AgentLoop] user_id={user_id}, session_id={session_id}, actual_user_id={actual_user_id}", flush=True)
    stop_event = None
    dialogue_manager_ref = None

    try:
        from core.dialog.dialogue_manager import dialogue_manager
        dialogue_manager_ref = dialogue_manager
        stop_event = await dialogue_manager._acquire_user_loop_lock_async(actual_user_id, reuse_existing=True)
        logger.info(f"[AgentLoop] 用户 {actual_user_id} 的AgentLoop已启动（并发控制）")
    except Exception as e:
        diagnostic_except_handler(e, context="[AgentLoop] 获取用户循环锁失败", logger_instance=logger)
        stop_event = threading.Event()  # 降级处理：创建本地事件

    # 在 try 开头保存锁和干预系统的引用，确保 finally 在任何条件下都能释放
    stop_event_acquired = stop_event is not None
    _realtime_intervention_ref = realtime_intervention if REALTIME_INTERVENTION_AVAILABLE else None
    try:
        # [Phase 1] 原生异步调用，彻底删除 asyncio.run 桥接
        return await run_agent_loop_async(
            task=task,
            max_rounds=max_rounds,
            chat_history=chat_history,
            chat_count=chat_count,
            session_id=session_id,
            db_session_id=None,
            voice_instance=voice_instance,
            mode=mode,
            user_id=user_id,
            stop_event=stop_event,
            task_id=task_id,
            resume_from_checkpoint=resume_from_checkpoint
        )
    finally:
        # 确保在任何条件下都释放锁和注销干预系统
        try:
            if stop_event_acquired and dialogue_manager_ref is not None:
                await dialogue_manager_ref._release_user_loop_lock_async(actual_user_id, stop_event)
        except Exception as e:
            logger.error(f"[AgentLoop] 释放用户循环锁失败 (user_id={actual_user_id}): {e}", exc_info=True)
        try:
            if task_id and _realtime_intervention_ref is not None:
                _realtime_intervention_ref.unregister_task(task_id)
        except Exception as e:
            logger.error(f"[AgentLoop] 注销实时干预任务失败 (task_id={task_id}): {e}", exc_info=True)

async def _run_agent_loop_async_impl(task, max_rounds: int = None,
                                     chat_history: list[dict[str, Any]] | None = None,
                                     chat_count: int = 0, session_id: str = "console",
                                     db_session_id: str | None = None,
                                     voice_instance=None, mode: str = "daily",
                                     user_id: str = None, stop_event: threading.Event = None,
                                     task_id: str | None = None,
                                     resume_from_checkpoint: bool = False,
                                     cancel_event: asyncio.Event = None,
                                     timeout_deadline: float = None) -> tuple[str | None, WorkingMemory]:
    """
    AgentLoop异步版本实际实现函数
    """

    # 获取 dialogue_manager 引用（供本函数内各阶段使用）
    dialogue_manager_ref = None
    try:
        from core.dialog.dialogue_manager import dialogue_manager as dialogue_manager_ref
    except Exception as e:
        logger.error(f"[AgentLoop] 导入 dialogue_manager 失败: {e}", exc_info=True)

    # 【Phase 1】初始化已抽取到 loop_initialization
    from core.agent.loop_initialization import initialize_loop_state
    _init = await initialize_loop_state(
        task=task, max_rounds=max_rounds, chat_history=chat_history,
        chat_count=chat_count, session_id=session_id,
        db_session_id=db_session_id,
        voice_instance=voice_instance, mode=mode, user_id=user_id,
        stop_event=stop_event, task_id=task_id,
        resume_from_checkpoint=resume_from_checkpoint,
    )
    actual_user_id = _init.actual_user_id
    user_id = _init.user_id
    voice_instance = _init.voice_instance
    max_rounds = _init.max_rounds
    work_mode = _init.work_mode
    user_instruction = _init.user_instruction
    user_instruction_for_session = _init.user_instruction_for_session
    task_type = _init.task_type
    state = _init.state
    working_memory = _init.working_memory
    # 【P1-交易指挥官报告注入】将缓存的交易报告注入工作记忆，使主AI能在Prompt中引用
    try:
        cached_entry = AgentLoop._commander_reports.pop(actual_user_id, None)
        cached_report = cached_entry.get("report") if isinstance(cached_entry, dict) else cached_entry
        if cached_report:
            working_memory.update_after_tool(
                "commander_report",
                {"success": True, "report": cached_report, "user_message": "交易指挥官已生成最新报告"}
            )
            logger.info(f"[AgentLoop] 交易报告已注入工作记忆: user={actual_user_id}")
        # 清理超过1小时的旧报告，防止内存泄漏
        now = time.time()
        for uid in list(AgentLoop._commander_reports.keys()):
            report_data = AgentLoop._commander_reports.get(uid, {})
            if isinstance(report_data, dict) and now - report_data.get("cached_at", 0) > 3600:
                AgentLoop._commander_reports.pop(uid, None)
    except Exception as e:
        logger.warning(f"[AgentLoop] 交易报告注入失败(非阻塞): {e}")
    loop_state = _init.loop_state
    execution_history = _init.execution_history
    hook_ctx = _init.hook_ctx

    # 【跨循环DuplicateGuard】恢复近期工具缓存到当前LoopState
    if actual_user_id in _user_tool_result_cache:
        _cached_tools = _user_tool_result_cache[actual_user_id]
        _now = time.time()
        _restored_count = 0
        for _k, _v in list(_cached_tools.items()):
            if _now - _v.get("timestamp", 0) < _TOOL_CACHE_TTL_SECONDS:
                loop_state.processed_tool_calls[_k] = _v
                _restored_count += 1
        if _restored_count:
            logger.info(
                f"[AgentLoop-DuplicateGuard] 为用户 {actual_user_id} 恢复了 {_restored_count} 条近期工具缓存"
            )

    # 保存引用，供外层 finally 块访问
    _last_loop_state[actual_user_id] = loop_state

    # 【协调层】初始化动作协调器与行为选择器的 SystemState 订阅
    try:
        coordinator = get_action_coordinator()
        if not coordinator._subscriptions_setup:
            coordinator.setup_subscriptions()
        selector = get_behavior_selector()
        if not selector._subscriptions_setup:
            selector.setup_subscriptions()
    except Exception as e:
        logger.warning(f"[AgentLoop] 协调层初始化失败(非阻塞): {e}")
    trace_id = _init.trace_id
    # 【P1-1】将 trace_id 注入上下文，供 EventBus / MemoryService 自动读取
    set_trace_id(trace_id)
    precision_parser = _init.precision_parser
    announcer = _init.announcer
    session = _init.session
    pausable_task_sm = _init.pausable_task_sm
    snapshot_manager = _init.snapshot_manager
    task_state = _init.task_state
    start_step = _init.start_step
    effective_task_id = _init.effective_task_id
    phase_anchor_manager = _init.phase_anchor_manager
    # NOTE: async_memory 已完全迁移至 MemoryService，agent_loop 不再读取 LoopInit.async_memory。
    memory_service = await get_memory_service()
    _agent_runtime = _init._agent_runtime
    _agent_runtime._pausable_task_sm = pausable_task_sm
    smart_context_manager = _init.smart_context_manager
    smart_context_enabled = _init.smart_context_enabled
    change_detector = _init.change_detector
    last_vision_description = _init.last_vision_description
    vision_cache_timestamp = _init.vision_cache_timestamp
    vision_enabled = _init.vision_enabled
    initial_steps = _init.initial_steps
    task_history = _init.task_history
    state_persistence = get_state_persistence()
    perception_manager = _init.perception_manager
    exploration_engine = _init.exploration_engine
    exploration_context = _init.exploration_context
    task_stage = _init.task_stage
    task_profile = _init.task_profile
    reflection_context = _init.reflection_context
    belief_confidence = _init.belief_confidence
    strategy_recommendation = _init.strategy_recommendation
    progress_tracker = _init.progress_tracker
    feature_recovery = _init.feature_recovery
    async_user_id = _init.async_user_id
    MAX_SAFETY_ROUNDS = _init.MAX_SAFETY_ROUNDS
    SAFETY_WARNING_THRESHOLD = _init.SAFETY_WARNING_THRESHOLD
    STOP_CHECK_INTERVAL = _init.STOP_CHECK_INTERVAL

    # 【阶段上下文】初始化统一数据通道
    from core.agent.phase_context import PhaseContext
    phase_ctx = PhaseContext(
        task=task,
        working_memory=working_memory,
        loop_state=loop_state,
        session_id=session_id,
        user_id=user_id,
        execution_history=execution_history,
        trace_id=trace_id,
    )

    # 【编排插件】任务开始前：Planner制定任务规划
    task_plan = None
    if user_instruction:
        try:
            planner = get_planner()
            plan_result = await planner.plan_task_async(
                task_description=user_instruction,
                context={"session_id": session_id, "mode": work_mode}
            )
            task_plan = plan_result.get("steps", [])
            if task_plan:
                logger.info(f"[AgentLoop] Planner生成任务规划: {len(task_plan)} 步骤")
                plan_text = "\n".join([f"步骤 {s.get('step', i+1)}: {s.get('action', '')}" for i, s in enumerate(task_plan)])
                working_memory.append({
                    "role": "system",
                    "content": f"【任务规划】请按以下步骤执行:\n{plan_text}"
                })
        except Exception as e:
            diagnostic_except_handler(e, context="[AgentLoop] 任务规划失败", logger_instance=logger)

    # 【轻量聊天短路】若用户输入明显是简单闲聊且尚未执行任何工具，直接 LLM 返回
    # 这是最后一道防线：正常路径应在 DialogueManager 层就被分流到 quick_chat
    if loop_state.round_count == 0 and not execution_history:
        from core.constants import is_simple_chat
        if is_simple_chat(user_instruction):
            logger.info(f"[AgentLoop] 检测到简单聊天输入，执行短路返回: {user_instruction[:40]}")
            try:
                from core.ai.ai_config import AIScene
                # 对时间/日期类查询注入当前时间，避免 LLM 编造
                time_keywords = ["几点", "几点钟", "时间", "日期", "几号", "星期", "礼拜", "天气"]
                has_time_query = any(kw in user_instruction.lower() for kw in time_keywords)
                current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                system_content = (
                    "你是 SiliconBase V5，一个运行在用户本地计算机上的桌面 AI Agent / 硅基生命体基底系统，"
                    "具备屏幕感知、记忆、主动意识、工具执行与任务规划等能力。"
                )
                if has_time_query:
                    system_content += f" 当前时间: {current_time}。"
                system_content += "请简洁直接地回答用户。"
                msgs = [
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": user_instruction}
                ]
                short_reply = await call_thinker_async(msgs, scene=AIScene.CHAT, hard_timeout=15)
                if session and hasattr(session, 'chat_history'):
                    session.chat_history.append({"role": "assistant", "content": short_reply})
                return short_reply, working_memory
            except Exception as e:
                diagnostic_except_handler(e, context="[AgentLoop] 轻量聊天短路失败", logger_instance=logger)
                logger.error(f"[SILENT_FAILURE_BLOCKED] 轻量聊天短路失败，禁止落入主循环: {e}")
                raise RuntimeError(f"轻量聊天短路失败: {e}") from e

    # === 脊髓反射弧：熔断计时与状态初始化 ===
    loop_start_time = time.time()
    final_answer = ""
    _last_hist_len = 0
    _stagnant_rounds = 0

    while loop_state.round_count < MAX_SAFETY_ROUNDS:  # 软性安全限制
        # 【封印3】检查调度器取消信号和绝对超时
        if cancel_event and cancel_event.is_set():
            logger.warning("[AgentLoop] 检测到调度器取消信号，终止循环")
            final_answer = "任务执行已超时，自动终止。"
            break
        if timeout_deadline and time.time() > timeout_deadline:
            logger.warning("[AgentLoop] 到达绝对超时时间，终止循环")
            final_answer = "任务执行时间过长，已自动终止。"
            break

        # 【P1】长任务中断恢复：检查用户插话请求
        if task and task.id and dialogue_manager_ref and actual_user_id:
            try:
                interruption_text = getattr(dialogue_manager_ref, '_interruption_requests', {}).pop(actual_user_id, None)
                if interruption_text:
                    from core.agent.checkpoint_manager import checkpoint_manager
                    logger.info(f"[AgentLoop] 任务 {task.id} 因用户插话暂停，保存检查点")
                    try:
                        await checkpoint_manager.save_checkpoint_async(
                            task_id=task.id,
                            checkpoint_name="用户插话暂停",
                            working_memory=working_memory,
                        )
                    except Exception as e:
                        logger.warning(f"[AgentLoop] 插话保存检查点失败: {e}")
                    try:
                        pause_result = await checkpoint_manager.pause_task(task.id, reason=f"用户插话: {interruption_text[:50]}")
                        logger.info(f"[AgentLoop] 任务 {task.id} 暂停结果: status={pause_result.status if pause_result else None}")
                    except Exception as e:
                        logger.warning(f"[AgentLoop] 插话暂停任务失败: {e}")
                    loop_state.paused = True
                    loop_state.pause_count += 1
                    if dialogue_manager_ref:
                        dialogue_manager_ref._last_paused_task_id[actual_user_id] = task.id
                    final_answer = "[PAUSED]"
                    logger.info(f"[AgentLoop] 任务 {task.id} 因插话返回 [PAUSED]")
                    break
            except Exception as e:
                logger.warning(f"[AgentLoop] 插话暂停检查失败: {e}")

        # === 脊髓反射弧：基于执行状态的硬编码熔断检查 ===
        # 1. 连续工具失败检测（任意连续失败，不限同一工具）
        consecutive_tool_failures = 0
        for h in reversed(execution_history):
            if h.get("success") is False:
                consecutive_tool_failures += 1
            else:
                break

        # 2. 停滞检测：最近2轮是否有新增执行历史
        current_hist_len = len(execution_history)
        if current_hist_len <= _last_hist_len:
            _stagnant_rounds += 1
        else:
            _stagnant_rounds = 0
        _last_hist_len = current_hist_len

        # 3. 熔断条件判定
        circuit_breaker_triggered = False
        circuit_breaker_reason = ""

        if consecutive_tool_failures >= 2:
            circuit_breaker_triggered = True
            circuit_breaker_reason = f"工具连续失败 {consecutive_tool_failures} 次"
        elif _stagnant_rounds >= 2:
            circuit_breaker_triggered = True
            circuit_breaker_reason = f"最近 {_stagnant_rounds} 轮无新工具执行"
        elif (time.time() - loop_start_time) > 120:
            circuit_breaker_triggered = True
            circuit_breaker_reason = "任务运行超过 120 秒"

        if circuit_breaker_triggered:
            logger.error(f"[AgentLoop-CircuitBreaker] 熔断触发: {circuit_breaker_reason}")
            failed_tool = execution_history[-1].get("tool", "未知工具") if execution_history else "未知工具"
            final_answer = f"抱歉，由于 {failed_tool} 暂时不可用，我无法完成此任务。请稍后重试或尝试其他方式。"
            execution_history.append({
                "tool": "circuit_breaker",
                "success": False,
                "reason": circuit_breaker_reason,
                "timestamp": time.time(),
            })
            break

        # before_round 钩子
        try:
            hook_ctx = await agent_loop_hooks.execute_async('before_round', hook_ctx)
        except Exception as e:
            logger.error(f"[AgentLoop] before_round 钩子执行失败: {e}", exc_info=True)

        loop_state.increment_round()  # 增加轮次
        logger.info(f"[Diag] Round start: trace_id={trace_id}, round={loop_state.round_count}")
        logger.info(f"[TRACE] Round {loop_state.round_count} Step 1: 轮次开始 | ts={time.time():.3f}")

        # 【Reflector】周期性策略反思（每5轮自动触发，内部含步数条件判断）
        if reflector is not None:
            try:
                periodic_reflection = await reflector.reflect_periodic(
                    task=user_instruction,
                    steps=execution_history,
                    step_count=loop_state.round_count
                )
                if periodic_reflection:
                    _periodic_suggestion = periodic_reflection.suggestion
                    if _periodic_suggestion:
                        working_memory.append({
                            "role": "system",
                            "content": f"【周期性策略反思】{_periodic_suggestion}"
                        })
                        logger.info(f"[AgentLoop] 周期性策略反思建议已注入: {_periodic_suggestion[:60]}...")
            except Exception as e:
                logger.error(f"[AgentLoop] 周期性策略反思失败: {e}", exc_info=True)

        # 【Reflector】多维度深度反思（每10轮触发一次，成本高需节流）
        if reflector is not None and loop_state.round_count > 0 and loop_state.round_count % 10 == 0:
            try:
                multi_reflection = await reflector.reflect_multi_dimension(
                    task=user_instruction,
                    trajectory=execution_history,
                    context={"round": loop_state.round_count, "user_id": actual_user_id}
                )
                if multi_reflection:
                    _dim_insights = []
                    for _dim in ["efficiency", "safety", "user_experience", "learning"]:
                        _dim_obj = getattr(multi_reflection, _dim, None)
                        if _dim_obj and getattr(_dim_obj, "suggestion", None):
                            _dim_insights.append(f"[{_dim}]{_dim_obj.suggestion}")
                    if _dim_insights:
                        working_memory.append({
                            "role": "system",
                            "content": "【多维度反思】" + "\n".join(_dim_insights)
                        })
                        logger.info(f"[AgentLoop] 多维度反思建议已注入，维度数={len(_dim_insights)}")
            except Exception as e:
                logger.error(f"[AgentLoop] 多维度反思失败: {e}", exc_info=True)

        # 【任务快照】每轮保存当前状态到 DialogueManager，供前台聊天查询进度
        logger.info(f"[TRACE] Round {loop_state.round_count} Step 2: 保存任务快照前 | ts={time.time():.3f}")
        if actual_user_id and dialogue_manager_ref and loop_state.round_count > 0:
            try:
                recent_history = execution_history[-3:] if execution_history else []
                last_result = recent_history[-1].get("result", {}) if recent_history else {}
                last_tool = recent_history[-1].get("tool") if recent_history else None

                # 推断当前步骤描述
                step_desc = ""
                if working_memory and len(working_memory) > 0:
                    last_wm = working_memory[-1]
                    if isinstance(last_wm, dict) and last_wm.get("role") == "assistant":
                        step_desc = last_wm.get("content", "")[:60]

                with dialogue_manager_ref._snapshot_lock:
                    dialogue_manager_ref._user_task_snapshots[actual_user_id] = {
                        "task_id": task.id if task else None,
                        "instruction": user_instruction,
                        "current_round": loop_state.round_count,
                        "max_rounds": MAX_SAFETY_ROUNDS,
                        "step_description": step_desc,
                        "recent_tools": [h.get("tool") for h in recent_history if h.get("tool")],
                        "recent_results": recent_history,
                        "last_tool": last_tool,
                        "last_tool_success": last_result.get("success") if isinstance(last_result, dict) else None,
                        "started_at": task.metadata.get("started_at") if task and hasattr(task, 'metadata') else None,
                        "last_updated": datetime.now().isoformat(),
                    }
            except Exception as e:
                logger.debug(f"[AgentLoop] 保存任务快照失败: {e}")
        logger.info(f"[TRACE] Round {loop_state.round_count} Step 2: 保存任务快照后 | ts={time.time():.3f}")

        # 【Phase 7.2】每轮开始时存储用户输入（fire-and-forget，不阻塞主循环）
        try:
            _task = safe_create_task(on_user_input_async(actual_user_id, session_id, user_instruction), name="on_user_input")
            _task.add_done_callback(
                lambda t: logger.debug("[AgentLoop] 用户输入记忆存储完成")
                if not t.exception()
                else logger.warning(f"[AgentLoop] 用户输入记忆存储失败: {t.exception()}")
            )
        except Exception as e:
            logger.error(f"[AgentLoop] 用户输入记忆存储任务创建失败: {e}", exc_info=True)

        # after_round 钩子
        try:
            hook_ctx = await agent_loop_hooks.execute_async('after_round', hook_ctx)
        except Exception as e:
            logger.error(f"[AgentLoop] after_round 钩子执行失败: {e}", exc_info=True)

        # 【试点】执行已注册的阶段（目前只有intent试点）
        try:
            from core.agent.phase_registry import get_phases
            for name, info in get_phases():
                # 跳过需要特定前置条件的阶段
                if name == 'tool_call' and not phase_ctx.get('parsed_intent'):
                    logger.debug("[PhasePilot] 跳过 %s：无 parsed_intent", name)
                    continue
                if name == 'tool_execution' and not phase_ctx.get('tool_fn'):
                    logger.debug("[PhasePilot] 跳过 %s：无 tool_fn", name)
                    continue
                if name == 'context_assembly' and not phase_ctx.get('runtime'):
                    logger.debug("[PhasePilot] 跳过 %s：无 runtime", name)
                    continue
                await info["handler"](phase_ctx)
        except Exception as e:
            logger.error(f"[AgentLoop] PhasePilot 执行失败: {e}", exc_info=True)
            working_memory.add_system_message(f"阶段执行异常: {str(e)[:100]}")

        # 【新增】每轮结束时截断 working_memory，防止长任务内存爆炸
        await _trim_working_memory_async(working_memory)
        logger.debug(f"[AgentLoop] 当前轮次: {loop_state.round_count}/{MAX_SAFETY_ROUNDS}")  # 记录日志

        # 【断点续传】跳过已执行的步骤
        if start_step > 0 and loop_state.round_count < start_step:
            logger.info("[AgentLoop] skipping already executed step %d", loop_state.round_count)
            sync.emit_event("step_skipped", session_id, {
                "round": loop_state.round_count,
                "reason": "resume_from_checkpoint",
                "start_step": start_step
            })
            continue

        # 【安全提醒】接近上限时提醒AI系统
        remaining_rounds = MAX_SAFETY_ROUNDS - loop_state.round_count
        if remaining_rounds <= SAFETY_WARNING_THRESHOLD and remaining_rounds > 0:
            # 剩余10轮时给AI系统提醒
            warning_msg = f"【系统提醒】循环轮次接近软性安全上限，还剩 {remaining_rounds} 轮。建议尽快总结并返回结果。"
            working_memory.append({"role": "system", "content": warning_msg})
            logger.warning(f"[AgentLoop] [Safety] 接近安全上限，剩余 {remaining_rounds} 轮")

        # 【用户级并发控制】定期检查是否被外部终止
        if stop_event and loop_state.round_count % STOP_CHECK_INTERVAL == 0 and stop_event.is_set():
            logger.warning(f"[AgentLoop] 用户 {async_user_id} 的异步循环被外部终止")
            termination_msg = "任务已被用户终止"
            # 【Phase 6】任务终止语音播报已迁移到 VoiceHook.on_terminate（异步版）
            if config.get("voice.announce.process.task_status", True):
                await agent_loop_hooks.execute_async('on_terminate', hook_ctx)
            sync.emit_event("terminated", session_id, {
                "reason": "user_interrupt",
                "message": termination_msg,
                "user_id": async_user_id
            })
            sync.emit_event("completed", session_id, {
                "success": False,
                "answer": termination_msg,
                "reason": "user_interrupt"
            })
            # 【Phase 1】on_interrupt Hook（异步版本）
            hook_ctx = await agent_loop_hooks.execute_async('on_interrupt', hook_ctx, reason="stop_event")
            return termination_msg, working_memory

        # 【后台任务干预】检查外部暂停请求（由 DialogueManager._handle_task_control 设置）
        if dialogue_manager_ref and actual_user_id:
            try:
                if getattr(dialogue_manager_ref, '_pause_requests', {}).get(actual_user_id):
                    # 触发暂停状态机（复用现有长任务暂停机制）
                    if pausable_task_sm and hasattr(pausable_task_sm, 'state'):
                        # 如果状态机支持 request_pause，调用它
                        if hasattr(pausable_task_sm, 'request_pause'):
                            pausable_task_sm.request_pause()
                            logger.info(f"[AgentLoop] 收到外部暂停请求，任务 {task.id if task else 'unknown'} 将进入暂停")
                        else:
                            # 降级：直接设置一个内部暂停标记，由循环检测
                            logger.info("[AgentLoop] 收到外部暂停请求，任务将在当前轮次后暂停")
                else:
                    # 确保状态机恢复
                    if pausable_task_sm and hasattr(pausable_task_sm, 'current_state') and \
                       pausable_task_sm.current_state == PausableTaskState.PAUSED:
                        pausable_task_sm.resume()
            except Exception as _e:
                diagnostic_except_handler(_e, context="[AgentLoop] 后台任务干预检查失败", logger_instance=logger)

        # 检查中断  # 中断检查
        # 【关键修复】使用模块级导入的 interrupt_handler，而不是被覆盖的 realtime_intervention
        if interrupt_handler.is_interrupted(task.id):  # 有中断
            logger.info("[AgentLoop] 中断结束: 用户中断信号")  # 记录日志
            state_persistence.save(state)  # 保存状态
            # 【Phase 1】on_interrupt Hook（异步版本）
            hook_ctx = await agent_loop_hooks.execute_async('on_interrupt', hook_ctx, reason="interrupt_signal")
            raise AgentLoopInterrupted("[AgentLoop] 用户中断信号触发，循环终止")

        # =============================================================================  # 分隔线
        # 【长任务模式】暂停确认状态机处理  # 长任务处理
        # =============================================================================  # 分隔线
        # 检查是否处于暂停状态  # 状态检查
        if pausable_task_sm.state == PausableTaskState.PAUSED:  # 暂停状态
            # 【修改】去掉旧的 existing_snapshot 判断，始终保存最新状态
            try:
                # 可选：先清理旧快照再保存，避免数据膨胀
                await snapshot_manager.clear_snapshot(task.id)
            except Exception as _tool_trace_e:
                diagnostic_except_handler(_tool_trace_e, context="[AgentLoop] 记录工具执行到trace索引失败", logger_instance=logger)

            try:  # 异常处理
                await snapshot_manager.capture_snapshot(  # 捕获
                    task_id=task.id,  # 任务ID
                    working_memory=working_memory,  # 工作记忆
                    loop_state=loop_state,  # 循环状态
                    chat_history=chat_history or [],  # 聊天历史
                    session_id=session_id,  # 会话ID
                    user_id=user_id,  # 用户ID
                    long_task_sm=pausable_task_sm  # 状态机
                )  # 捕获结束
                logger.info(f"[AgentLoop] [LongTask] 任务 {task.id} 暂停时状态快照已捕获")  # 记录日志
            except Exception as e:  # 捕获异常
                logger.error(f"[AgentLoop] [LongTask] 捕获快照失败: {e}")  # 记录错误

            # 获取暂停提示词（要求AI百分百理解后才能恢复）  # 暂停提示
            pause_prompt = pausable_task_sm.get_pause_prompt()  # 获取提示
            working_memory.append({"role": "system", "content": pause_prompt})  # 添加

            # 【Phase 6】任务暂停语音播报已迁移到 VoiceHook.on_pause（异步版）
            if config.get("voice.announce.process.task_status", True):
                await agent_loop_hooks.execute_async('on_pause', hook_ctx)

            logger.info("[AgentLoop] [LongTask] 任务已暂停，等待AI输出理解摘要")  # 记录日志

        # 检查是否正在等待用户确认  # 等待确认
        elif pausable_task_sm.state == PausableTaskState.AWAITING_REQUIREMENTS:  # 等待需求
            # 等待用户确认状态，添加提示词  # 添加提示
            await_prompt = pausable_task_sm.get_pause_prompt()  # 获取提示
            if await_prompt:  # 有提示
                working_memory.append({"role": "system", "content": await_prompt})  # 添加

            logger.info("[AgentLoop] [LongTask] 等待用户确认理解")  # 记录日志

        # 检查是否准备恢复  # 准备恢复
        elif pausable_task_sm.state == PausableTaskState.READY_TO_RESUME:  # 可恢复
            # 【新增】真正恢复快照到运行时状态
            restored = await snapshot_manager.restore_to_working_memory(task.id, working_memory)
            if restored:
                snapshot = await snapshot_manager.restore_snapshot(task.id)
                if snapshot:
                    # 恢复 loop_state 关键计数器
                    loop_state.round_count = getattr(snapshot, 'loop_round', loop_state.round_count)
                    # 如有 execution_history 也恢复
                    if hasattr(snapshot, 'execution_history'):
                        execution_history.clear()
                        execution_history.extend(snapshot.execution_history)

            # 可以恢复任务  # 恢复
            resume_context = pausable_task_sm.resume(by_user=True)  # 执行恢复
            if resume_context:  # 恢复成功
                resume_prompt = pausable_task_sm.get_resume_prompt(resume_context)  # 获取恢复提示
                working_memory.append({"role": "system", "content": resume_prompt})  # 添加

                # 【Phase 6】任务恢复语音播报已迁移到 VoiceHook.on_resume（异步版）
                if config.get("voice.announce.process.task_status", True):
                    await agent_loop_hooks.execute_async('on_resume', hook_ctx)

                # 发送事件  # 事件
                sync.emit_event("long_task_resumed", session_id, {  # 发送恢复事件
                    "task_id": task.id,  # 任务ID
                    "confirmation_round": resume_context.get("confirmation_round", 0)  # 确认轮次
                })  # 事件结束

                logger.info("[AgentLoop] [LongTask] 任务已恢复")  # 记录日志

        # =============================================================================  # 分隔线
        # 【长任务模式】检测用户确认响应  # 用户确认检测
        # =============================================================================  # 分隔线
        # 当状态机在等待确认时，检查working_memory中最近的用户消息  # 确认检测
        if pausable_task_sm.state == PausableTaskState.AWAITING_REQUIREMENTS:  # 等待确认
            # 获取最近的用户消息  # 获取消息
            last_user_message = None  # 初始化为None
            for msg in reversed(working_memory.messages if hasattr(working_memory, 'messages') else []):  # 逆序遍历
                if msg.get("role") == "user":  # 用户消息
                    last_user_message = msg.get("content", "")  # 获取内容
                    break  # 跳出

            if last_user_message:  # 有用户消息
                # 处理用户确认  # 处理确认
                result = pausable_task_sm.process_user_confirmation(last_user_message)  # 处理

                if result.get("status") == "confirmed":  # 确认成功
                    # 用户确认理解正确  # 确认
                    logger.info("[AgentLoop] [LongTask] 用户确认理解正确，准备恢复")  # 记录日志

                    # 【Phase 6】理解确认语音播报已迁移到 VoiceHook.on_understanding_confirmed（异步版）
                    if config.get("voice.announce.process.task_status", True):
                        await agent_loop_hooks.execute_async('on_understanding_confirmed', hook_ctx)

                    # 发送确认事件  # 事件
                    sync.emit_event("understanding_confirmed", session_id, {  # 发送确认事件
                        "task_id": task.id,  # 任务ID
                        "message": "用户确认理解正确"  # 消息
                    })  # 事件结束

                    # 状态已变为READY_TO_RESUME，下一轮将自动恢复  # 状态变更

                elif result.get("status") in ["rejected", "modified"]:  # 拒绝或修改
                    # 用户拒绝或修改需求  # 处理拒绝
                    logger.info(f"[AgentLoop] [LongTask] 用户{result.get('status')}，需要重新理解")  # 记录日志

                    feedback = result.get("message", "需要重新理解")  # 获取反馈
                    working_memory.append({  # 添加反馈
                        "role": "system",  # 系统角色
                        "content": f"【用户反馈】{feedback}。请重新输出理解摘要。"  # 内容
                    })  # 添加结束

        # ═════════════════════════════════════════════════════════════════════════════
        # 【Phase 8】核心决策逻辑已迁移至 CoreLogicHooks（干预/感知/上下文组装/finalize）
        # 原硬编码块：L913-927 干预检查、L940-996 感知注入、L1003-1009 记忆检索、
        #            L1056-1064 Prompt片段、L1069-1091 PromptFinalizer
        # 现统一通过 before_prompt Hook 链驱动。
        # ═════════════════════════════════════════════════════════════════════════════

        logger.info(f"[TRACE] Round {loop_state.round_count} Step 3: build_smart_context 前 | ts={time.time():.3f}")
        # 使用智能提示词引擎构建上下文
        smart_context = await build_smart_context(
            user_instruction=user_instruction,
            working_memory=working_memory,
            session_id=session_id,
            mode=work_mode
        )
        logger.info(f"[TRACE] Round {loop_state.round_count} Step 3: build_smart_context 后 | ts={time.time():.3f}")

        # 为 Hook 准备 phase_ctx（保留原数据通道）
        phase_ctx.set('runtime', _agent_runtime)
        phase_ctx.set('hooks', agent_loop_hooks)
        phase_ctx.set('user_instruction', user_instruction)
        phase_ctx.set('task_type', task_type)
        phase_ctx.set('exploration_engine', exploration_engine)
        phase_ctx.set('exploration_context', exploration_context)
        phase_ctx.set('reflection_context', reflection_context)
        phase_ctx.set('belief_confidence', belief_confidence)
        phase_ctx.set('strategy_recommendation', strategy_recommendation)
        phase_ctx.set('world_model_manager', get_world_model_manager() if get_world_model_manager is not None else None)
        from core.agent.context_assembler import ContextAssembler
        _phase_assembler = ContextAssembler(_agent_runtime, agent_loop_hooks)
        phase_ctx.set('assembler', _phase_assembler)
        phase_ctx.set('prompt_builder', prompt_builder)  # 【修复】注入 prompt_builder 供 prompt_assembly_bridge 使用

        # =================================================================
        # [语音播报 - 阶段四优化] 使用智能播报策略
        # =================================================================
        estimated_memory_count = 0
        try:
            estimated_memory_count = (
                3 + 3 + 2 + 2
            )
        except Exception as e:
            logger.error(f'[AgentLoop-Async] 智能播报失败: {e}', exc_info=True)

        logger.info(f"[TRACE] Round {loop_state.round_count} Step 4: on_layer_switch hook 前 | ts={time.time():.3f}")
        # 【Phase 6】记忆查询语音播报
        await agent_loop_hooks.execute_async(
            'on_layer_switch', hook_ctx,
            announce_type=VoiceAnnounceStrategy.MEMORY_QUERY,
            memory_count=estimated_memory_count,
            intent=user_instruction[:20],
            layer='memory_retrieval',
            user_id=session_id if session_id != 'console' else 'default',
            is_first_query=getattr(working_memory, '_voice_state', {}).get('_announce_count', 0) == 0
        )
        logger.info(f"[TRACE] Round {loop_state.round_count} Step 4: on_layer_switch hook 后 | ts={time.time():.3f}")

        # 【Phase 8】填充 Hook 上下文并统一触发 before_prompt
        hook_ctx.extra['intervention_checker'] = intervention_checker
        hook_ctx.extra['pausable_task_sm'] = pausable_task_sm
        hook_ctx.extra['state_persistence'] = state_persistence
        hook_ctx.extra['state'] = state
        hook_ctx.extra['perception_manager'] = perception_manager
        hook_ctx.extra['loop_state'] = loop_state
        hook_ctx.extra['execution_history'] = execution_history
        hook_ctx.extra['work_mode'] = work_mode
        hook_ctx.extra['phase_ctx'] = phase_ctx
        hook_ctx.extra['assembler'] = _phase_assembler
        hook_ctx.extra['smart_context'] = smart_context
        # 【Phase 8 修复】experience_context 已外迁至 ContextAssembler / core_logic_hooks
        # 由 before_prompt Hook 链内部生成，不再从主循环传递
        # hook_ctx.extra['experience_context'] = experience_context
        hook_ctx.extra['effective_task_id'] = effective_task_id
        hook_ctx.extra['phase_anchor_manager'] = phase_anchor_manager
        hook_ctx.extra['last_vision_description'] = last_vision_description
        hook_ctx.extra['session_id'] = session_id
        hook_ctx.extra['actual_user_id'] = actual_user_id
        hook_ctx.extra['user_id'] = user_id

        logger.info(f"[TRACE] Round {loop_state.round_count} Step 5: before_prompt hook 前 | ts={time.time():.3f}")
        hook_ctx = await agent_loop_hooks.execute_async('before_prompt', hook_ctx)
        logger.info(f"[TRACE] Round {loop_state.round_count} Step 5: before_prompt hook 后 | ts={time.time():.3f}")

        # 干预信号检查
        if hook_ctx.extra.get('intervention_should_return'):
            return hook_ctx.extra.get('intervention_return_value'), working_memory

        # 读取 Hook 输出
        perception_context = hook_ctx.extra.get('perception_context', '')
        full_system_prompt = hook_ctx.extra.get('full_system_prompt', '')
        budget_report = hook_ctx.extra.get('budget_report')

        # 【诊断】上下文组装检查点
        _memory_meta = hook_ctx.extra.get('memory_metadata', {})
        _ctx_tokens = budget_report.get('total_truncated_tokens', 0) if isinstance(budget_report, dict) else max(1, int(len(full_system_prompt or '') / 2))
        _layers = []
        if '[模块状态]' in (full_system_prompt or ''):
            _layers.append('L0')
        if _memory_meta.get('l1_count', 0):
            _layers.append('L1')
        if _memory_meta.get('l2_count', 0):
            _layers.append('L2')
        if _memory_meta.get('l3_count', 0):
            _layers.append('L3')
        if _memory_meta.get('l4_count', 0):
            _layers.append('L4')
        if 'L5' in (hook_ctx.extra.get('memory_context', '') or ''):
            _layers.append('L5')
        logger.info(f"[Diag] Context: tokens={_ctx_tokens}, layers={','.join(_layers) if _layers else 'none'}")

        # 【调试兜底】如果 PromptFinalizer 未写入，则兜底新建 dump 文件
        if full_system_prompt:
            try:
                _dump_dir = Path(__file__).parent.parent.parent / "data" / "prompt_dumps"
                _dump_dir.mkdir(parents=True, exist_ok=True)
                _ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                _fname = f"prompt_dump_{_ts}_r{loop_state.round_count if loop_state else 0:02d}_loop.txt"
                _dump_path = _dump_dir / _fname
                def _write_dump(
                    dump_path=_dump_path,
                    sys_prompt=full_system_prompt,
                    state=loop_state,
                ):
                    with open(dump_path, "w", encoding="utf-8") as f:
                        f.write("=== SiliconBase V5 - 完整 System Prompt (AgentLoop兜底) ===\n")
                        f.write(f"长度: {len(sys_prompt)} 字符\n")
                        f.write(f"Token 估算: ~{max(1, int(len(sys_prompt) / 2))}\n")
                        f.write(f"时间: {datetime.now().isoformat()}\n")
                        f.write(f"轮次: {state.round_count if state else 'N/A'}\n")
                        f.write("=" * 60 + "\n\n")
                        f.write(sys_prompt)
                await asyncio.to_thread(_write_dump)
            except Exception as _e:
                logger.warning(f"[AgentLoop] 兜底写入提示词 dump 失败: {_e}")

        # ═════════════════════════════════════════════════════════════════════════════

        # ═════════════════════════════════════════════════════════════════════════════

        # 【Phase 7】视觉感知处理已外迁至 vision_processor（异步版）
        # 【修复】简单问答跳过视觉感知，避免无效注入
        # 统一引用 core.constants 关键词库，避免多处定义不一致
        from core.constants import is_simple_chat
        _is_simple_chat = is_simple_chat(user_instruction)

        # 【第一阶段改造 1.1】如果存在实时监控快照，跳过视觉模型调用
        # 快照数据已在后续的 working_memory 注入阶段被读取
        _has_realtime_snapshot = False
        if dialogue_manager_ref and hasattr(dialogue_manager_ref, '_user_task_snapshots'):
            _rt_key = f"{actual_user_id}_realtime"
            _has_realtime_snapshot = _rt_key in dialogue_manager_ref._user_task_snapshots

        if _has_realtime_snapshot:
            logger.debug(
                f"[AgentLoop] 实时监控快照存在，跳过视觉模型调用: user={actual_user_id}"
            )
            # 从快照读取轻量视觉描述，避免下游依赖拿到 None
            _rt_snapshot = dialogue_manager_ref._user_task_snapshots.get(_rt_key, {})
            _dominant_app = _rt_snapshot.get("dominant_app", "unknown")
            _layout_summary = _rt_snapshot.get("layout_summary", "暂无描述")
            last_vision_description = (
                f"[实时监控感知] 当前前台: {_dominant_app}, 画面: {_layout_summary}"
            )
        else:
            logger.debug(f"[AgentLoop] 无实时监控快照，视觉感知由 PerceptionManager 统一处理: '{user_instruction}'")
            last_vision_description = None

        # 【实时监控】注入实时桌面感知到 working_memory
        try:
            from core.dialog.dialogue_manager import dialogue_manager as _dm_ref
            if _dm_ref and hasattr(_dm_ref, '_user_task_snapshots'):
                realtime_key = f"{actual_user_id}_realtime"
                if realtime_key in _dm_ref._user_task_snapshots:
                    realtime_prompt = _dm_ref._build_active_task_status_prompt(actual_user_id)
                    if realtime_prompt:
                        working_memory.append({
                            "role": "system",
                            "content": realtime_prompt
                        })
                        logger.info(
                            f"[AgentLoop] 实时监控文本已注入工作记忆: user={actual_user_id}"
                        )
        except Exception as e:
            logger.error(f"[AgentLoop] 实时监控注入失败: {e}", exc_info=True)

        # 【Phase 8】每轮循环注入意识系统分析（异步版）
        if CONSCIOUSNESS_BRIDGE_AVAILABLE:
            try:
                await apply_consciousness_analysis(
                    working_memory=working_memory,
                    execution_history=execution_history,
                    loop_state=loop_state,
                )
            except Exception as e:
                logger.error(f"[AgentLoop] 意识系统分析注入失败: {e}", exc_info=True)

        # 构建优化的消息上下文  # 消息构建
        messages = await context_builder.build_optimized_context(  # 构建
            system_prompt=full_system_prompt,  # 系统提示词
            working_memory=working_memory,  # 工作记忆
            execution_history=execution_history,  # 执行历史
            current_task=user_instruction,  # 当前任务
            chat_history=chat_history or []  # 聊天历史
        )  # 构建结束

        # =============================================================================  # 分隔线
        # 【PERF-001关键修复】使用异步AI调用，不阻塞事件循环  # 异步调用
        # =============================================================================  # 分隔线
        # 【Phase 6】思考过程播报已迁移到 VoiceHook.before_prompt，由注册表统一驱动

        # 【修复】LLM调用前检查 stop_event，允许用户及时终止循环
        if stop_event and stop_event.is_set():
            logger.warning(f"[AgentLoop] 用户 {async_user_id} 的循环在LLM调用前被终止")
            termination_msg = "任务已被用户终止"
            sync.emit_event("terminated", session_id, {
                "reason": "user_interrupt",
                "message": termination_msg,
                "user_id": async_user_id
            })
            return termination_msg, working_memory

        # 【Phase 7.3】LLM 调用 + 幻觉检测重试闭环（已抽取到 loop_utils）
        from core.agent.loop_utils import call_llm_with_retry
        response = None
        logger.info(f"[TRACE] Round {loop_state.round_count} Step 6: LLM 调用前 | ts={time.time():.3f}")
        try:
            _llm_call_start = time.time()
            logger.info(
                f"[TRACE] AgentLoop Round {loop_state.round_count}: LLM 调用前 "
                f"ts={_llm_call_start:.3f}, messages={len(messages)}"
            )
            response, hook_ctx = await call_llm_with_retry(
                messages=messages,
                hook_ctx=hook_ctx,
                agent_loop_hooks=agent_loop_hooks,
                logger=logger,
                max_retries=1,
                hard_timeout=30,  # 30秒超时，避免本地Ollama加载慢时用户卡死；需要更长时间请用配置覆盖
            )
            _llm_call_end = time.time()
            logger.info(
                f"[TRACE] AgentLoop Round {loop_state.round_count}: LLM 调用后 "
                f"ts={_llm_call_end:.3f}, elapsed={_llm_call_end - _llm_call_start:.3f}s, "
                f"len={len(response) if response else 0}"
            )
            logger.info(f"[TRACE] Round {loop_state.round_count} Step 6: LLM 调用后 | ts={_llm_call_end:.3f}")
            _thinking = getattr(working_memory, 'last_thinking', None) or (extract_thinking_from_response(response) if response else None)
            logger.info(f"[Diag] LLM: len={len(response) if response else 0}, thinking={'yes' if _thinking else 'no'}")
        except Exception as e:
            diagnostic_except_handler(e, context="[AgentLoop] LLM调用异常", logger_instance=logger)
            error_str = str(e)
            # 【零静默失败】AI 没有正常输出结果 = 明确报错 + 抛异常
            is_ai_unavailable = any(kw in error_str for kw in [
                "服务不可用", "不可用", "Connection refused", "ConnectionError",
                "无法连接", "timeout", "超时", "ModelRoutingError", "所有AI模型都不可用"
            ])
            if is_ai_unavailable:
                logger.error(f"[SILENT_FAILURE_BLOCKED] [AgentLoop] AI服务不可用: {error_str}")
            else:
                logger.error(f"[SILENT_FAILURE_BLOCKED] [AgentLoop] LLM调用异常: {e}", exc_info=True)
            sync.emit_event("completed", session_id, {
                "success": False,
                "answer": error_str,
                "reason": "llm_error"
            })
            raise RuntimeError(f"AI调用失败，无法生成响应: {error_str}") from e

        # 【修复】LLM调用后检查 stop_event
        if stop_event and stop_event.is_set():
            logger.warning(f"[AgentLoop] 用户 {async_user_id} 的循环在LLM调用后被终止")
            termination_msg = "任务已被用户终止"
            sync.emit_event("terminated", session_id, {
                "reason": "user_interrupt",
                "message": termination_msg,
                "user_id": async_user_id
            })
            return termination_msg, working_memory

        # 【Phase 6】幻觉检测已迁移到 SafetyHook.after_prompt，由注册表统一驱动（异步版）

        # 【P1-006修复】重置播报标志，为下一轮做准备
        if hasattr(working_memory, '_thinking_announced'):
            working_memory._thinking_announced = False
        # 【日志记录】记录AI原始输出（诊断用）
        logger.info(f"[AgentLoop] AI原始输出: {response[:500] if response else 'None'}")
        if not response:
            error_detail = (
                f"[AgentLoop] AI返回空响应——LLM调用成功但输出为空。user={async_user_id}, "
                f"round={loop_state.round_count}, session={session_id}"
            )
            logger.error(error_detail)
            sync.emit_event("completed", session_id, {
                "success": False,
                "answer": "AI暂时无法处理该指令，请稍后重试。",
                "reason": "ai_empty_response"
            })
            raise RuntimeError(error_detail)

        # ═══════════════════════════════════════════════════════════════
        # 【Phase 7.2】异步版记忆触发（直接 await，无需 run_in_executor 桥接）
        # 同步版在 _run_agent_loop_impl 第 2813-2898 行有完整实现
        # ═══════════════════════════════════════════════════════════════
        try:
            from core.memory.memory_trigger import on_ai_response_async
            thinking_for_trigger = getattr(working_memory, 'last_thinking', None)
            tool_calls_for_trigger = getattr(working_memory, 'last_tool_calls', None)
            # NOTE: on_ai_response_async 已切至 MemoryService.save_chat_turn()。
            # create_task 用于非阻塞调度（fire-and-forget），ChromaDB 已通过 AsyncHttpClient 真异步化。
            async def _bg_on_ai_response(
                text=response,
                thinking=thinking_for_trigger,
                tool_calls=tool_calls_for_trigger,
            ):
                try:
                    result = await on_ai_response_async(
                        user_id=actual_user_id,
                        session_id=session_id if session_id else f"session_{actual_user_id}",
                        text=text,
                        thinking=thinking,
                        tool_calls=tool_calls,
                        metadata={
                            "source": "agent_loop_async",
                            "round": loop_state.round_count,
                            "model_provider": getattr(working_memory, 'current_model_provider', None),
                            "model_name": getattr(working_memory, 'current_model_name', None)
                        }
                    )
                    if result == "failed":
                        logger.error(
                            "[MemoryService] on_ai_response_async 返回 failed——"
                            "MemoryService.save_chat_turn() 执行失败（异常已被 memory_trigger 捕获），"
                            "请检查 upstream 日志定位根因"
                        )
                except Exception:
                    logger.exception(
                        "[MemoryService] on_ai_response_async 后台任务失败——"
                        "MemoryService.save_chat_turn() 执行失败"
                    )

            _task = safe_create_task(_bg_on_ai_response(), name="bg_on_ai_response")
            _task.add_done_callback(
                lambda t: logger.debug("[AgentLoop] AI回复记忆存储完成")
                if not t.exception()
                else logger.warning(f"[AgentLoop] AI回复记忆存储失败: {t.exception()}")
            )
            logger.info(f"[AgentLoop-Async] AI回复记忆存储已调度至后台: user={actual_user_id}, session={session_id}")
        except Exception as trigger_error:
            # 记忆触发失败，记录ERROR但不影响主流程
            logger.error(f"[AgentLoop-Async] 记忆触发失败: {trigger_error}", exc_info=True)

        # ═════════════════════════════════════════════════════════════════════════════
        # 【Phase 7】异步版 Session 消息存储（同步版在 L2629）
        # ═════════════════════════════════════════════════════════════════════════════
        if response and session:
            try:
                thinking_content = extract_thinking_from_response(response)
                tool_calls_info = extract_tool_calls_from_response(response)
                ai_message_metadata = {
                    "source": "agent_loop_async",
                    "round": loop_state.round_count,
                    "model_provider": getattr(working_memory, 'current_model_provider', None),
                    "model_name": getattr(working_memory, 'current_model_name', None),
                }
                ai_message_id = await session_integration.save_messages(
                    session_id=session.id,
                    role="assistant",
                    content=response,
                    thinking=thinking_content,
                    tool_calls=tool_calls_info,
                    metadata=ai_message_metadata,
                )
                if ai_message_id:
                    logger.info(f"[AgentLoop-Async] Session消息存储成功: message_id={ai_message_id}")
                else:
                    logger.error(f"[AgentLoop-Async] AI消息存储失败，session={session.id}")
            except Exception as e:
                diagnostic_except_handler(e, context="[AgentLoop-Async] AI回复存储失败", logger_instance=logger)

        # =============================================================================  # 分隔线
        # 【精准抓取】解析AI输出，分离自然语言和计算机语言  # 精准抓取
        # =============================================================================  # 分隔线
        precision_parsed = ParsedAIOutput(
            marker_type=AICodeMarker.UNKNOWN,
            raw_content=response,
            parsed_data={},
            natural_language="",
            should_speak=False,
        )
        try:
            precision_parsed = await precision_parser.process_and_announce(response, True)
        except Exception as e:
            logger.error(f"[AgentLoop] precision_parser.process_and_announce 失败: {e}", exc_info=True)
        logger.info(  # 记录日志
            f"[Precision] AI输出解析: type={precision_parsed.marker_type.value}, "  # 类型
            f"speak={precision_parsed.should_speak}"  # 是否播报
        )  # 日志结束

        # 发布精准抓取事件  # 事件
        sync.emit_event("precision_parsed", session_id, {  # 发送事件
            "marker_type": precision_parsed.marker_type.value,  # 标记类型
            "natural_language": precision_parsed.natural_language,  # 自然语言
            "parsed_data": precision_parsed.parsed_data  # 解析数据
        })  # 事件结束

        # 保留原有意图解析（兼容现有逻辑）  # 兼容
        parsed = ParsedIntent(
            intent_type=IntentType.UNKNOWN,
            raw_instruction=response,
        )
        try:
            parsed = _intent_parser.parse_ai_response(response)
        except Exception as e:
            logger.error(f"[SILENT_FAILURE_BLOCKED] [AgentLoop] _intent_parser.parse_ai_response 失败: {e}", exc_info=True)
            raise RuntimeError(f"AI输出格式异常，无法解析意图: {e}") from e

        # 提前提取AI的自然语言回复（后续强制修正需要用到）
        ai_reply = extract_natural_language(response)  # 提取

        # 【修复】兜底防御：如果 AI 将 FINAL_ANSWER 放入 tool 字段，修正为最终答案意图
        if parsed.intent_type == IntentType.TOOL_CALL and parsed.target_tool and parsed.target_tool.upper() in ("FINAL_ANSWER", "FINALANSWER"):
            logger.info("[AgentLoop] AI 将 FINAL_ANSWER 放入 tool 字段，修正为最终答案意图")
            parsed = type(parsed)(
                intent_type=IntentType.FINAL_ANSWER,
                raw_instruction=parsed.raw_instruction,
                params=parsed.params,
                natural_language=parsed.natural_language,
                confidence=parsed.confidence
            )

        # 【P1修复】单步工具成功后强制结束循环，避免AI重复调用
        if loop_state.force_final_answer and parsed.intent_type != IntentType.FINAL_ANSWER:
            logger.info("[AgentLoop] 单步工具已成功执行，强制将意图修正为 FINAL_ANSWER")
            parsed = type(parsed)(
                intent_type=IntentType.FINAL_ANSWER,
                raw_instruction=response,
                params={},
                natural_language=ai_reply or "任务已完成",
                confidence=1.0
            )

        logger.debug(f"[AgentLoop] 意图: {parsed.intent_type}, 工具: {parsed.target_tool}")  # 记录日志

        # === 每轮都发送思考事件到前端 ===  # 前端同步
        if ai_reply and ai_reply != "已完成":  # 有有效回复
            sync.emit_event("thinking", session_id, {  # 发送思考事件
                "round": loop_state.round_count,  # 轮次
                "content": ai_reply,  # 内容
                "intent": parsed.intent_type.value  # 意图类型
            })  # 事件结束

        # === 意图分发处理 ===  # 意图分发

        # =============================================================================  # 分隔线
        # 【精准抓取增强】根据解析标记类型处理  # 标记处理
        # =============================================================================  # 分隔线
        precision_marker = precision_parsed.marker_type  # 获取标记类型

        # 如果精准抓取识别到工具调用，使用精准抓取的数据  # 工具调用
        if precision_marker == AICodeMarker.TOOL_CALL and precision_parsed.parsed_data.get("tool"):  # 工具调用标记
            precision_tool = precision_parsed.parsed_data.get("tool")  # 获取工具
            precision_params = precision_parsed.parsed_data.get("params", {})  # 获取参数
            if precision_tool:  # 有工具名
                # 【修复】PrecisionParser 命中但 tool 为 FINAL_ANSWER 时，修正为最终答案意图
                if precision_tool.upper() in ("FINAL_ANSWER", "FINALANSWER"):
                    parsed = type(parsed)(
                        intent_type=IntentType.FINAL_ANSWER,
                        raw_instruction=parsed.raw_instruction,
                        params=parsed.params,
                        natural_language=parsed.natural_language,
                        confidence=parsed.confidence
                    )
                    tool_id = None
                    tool_params = {}
                    logger.info("[Precision] AI 将 FINAL_ANSWER 放入 tool 字段，修正为最终答案意图")
                else:
                    tool_id = precision_tool  # 使用精准抓取的ID
                    tool_params = precision_params  # 使用精准抓取的参数
                    logger.info(f"[Precision] 使用精准抓取的工具调用: {tool_id}")  # 记录日志
            else:  # 无工具名
                tool_id = parsed.target_tool  # 使用原有ID
                tool_params = parsed.params  # 使用原有参数
        else:  # 非工具调用
            tool_id = parsed.target_tool  # 使用原有ID
            tool_params = parsed.params  # 使用原有参数

        # 【修复】识别 LLM 显式任务完成信号 [TASK_COMPLETE]
        # 四重判定：结构化状态门槛取代单一"历史成功"条件
        if "[TASK_COMPLETE]" in response:
            # 第一层：检查是否有成功执行记录
            has_success = any(h.get("success") for h in execution_history)

            # 第二层：计划完成度检查（关键修复）
            plan_completed = True  # 默认完成（无计划时）
            if hasattr(working_memory, 'ai_plan') and working_memory.ai_plan:
                completed_steps = working_memory.ai_plan.get('current_step', 0)
                total_steps = working_memory.ai_plan.get('total_steps', 0)
                if total_steps > 0:
                    plan_completed = completed_steps >= total_steps

            # 第三层：意图一致性检查
            is_tool_call = (
                precision_parsed.marker_type == AICodeMarker.TOOL_CALL or
                parsed.intent_type == IntentType.TOOL_CALL
            )

            # 第四层：无计划且无工具调用的兜底（纯问答场景）
            no_plan_no_tool = (
                not (hasattr(working_memory, 'ai_plan') and working_memory.ai_plan)
                and not is_tool_call
            )

            # 第五层：内容校验。对时间/日期等确定性查询，答案必须包含有效信息格式
            content_valid = True
            time_keywords = ["几点", "几点钟", "时间", "日期", "几号", "星期", "礼拜"]
            user_lower = (user_instruction or "").lower()
            has_time_query = any(kw in user_lower for kw in time_keywords)
            if has_time_query:
                answer_text = parsed.natural_language or response or ""
                # 要求包含日期或时间数字格式
                has_time_format = bool(re.search(r"\d{1,2}:\d{2}|\d{4}-\d{2}-\d{2}|\d{1,2}月\d{1,2}日|星期[一二三四五六日]|礼拜[一二三四五六天]", answer_text))
                if not has_time_format:
                    content_valid = False
                    logger.info(f"[AgentLoop] [TASK_COMPLETE] 被忽略：时间类问题答案缺少时间格式，answer={answer_text[:80]}")

            if ((has_success and plan_completed and not is_tool_call) or no_plan_no_tool) and content_valid:
                logger.info("[AgentLoop] [TASK_COMPLETE] 被接受：任务完成，结束循环")
                parsed = type(parsed)(
                    intent_type=IntentType.FINAL_ANSWER,
                    raw_instruction=response,
                    params=parsed.params,
                    natural_language=parsed.natural_language,
                    confidence=parsed.confidence
                )
            else:
                reason = []
                if not has_success:
                    reason.append("无成功执行记录")
                if not plan_completed:
                    reason.append(f"计划未完成({working_memory.ai_plan.get('current_step', 0)}/{working_memory.ai_plan.get('total_steps', 0)})")
                if is_tool_call:
                    reason.append("检测到工具调用意图")
                logger.info(f"[AgentLoop] [TASK_COMPLETE] 被忽略：{', '.join(reason)}")
                # 向工作记忆注入提示，避免 LLM 每轮重复输出 TASK_COMPLETE
                if not plan_completed and hasattr(working_memory, 'append'):
                    _already_injected = False
                    try:
                        if hasattr(working_memory, 'get_message_history'):
                            msgs = working_memory.get_message_history()
                            if msgs:
                                _last = msgs[-1]
                                if (
                                    isinstance(_last, dict)
                                    and _last.get("role") == "system"
                                    and "不要输出[TASK_COMPLETE]" in _last.get("content", "")
                                ):
                                    _already_injected = True
                    except Exception:
                        pass
                    if not _already_injected:
                        working_memory.append({
                            "role": "system",
                            "content": f"任务计划尚未完成（{working_memory.ai_plan.get('current_step', 0)}/{working_memory.ai_plan.get('total_steps', 0)} 步骤），请继续执行剩余步骤，不要输出[TASK_COMPLETE]。"
                        })

        if parsed.intent_type == IntentType.TOOL_CALL:  # 工具调用意图
            # 播报工具调用（使用精准抓取的播报器）
            announcer.announce_tool_call(tool_id, tool_params)

            print(f"[AgentLoop] [TOOL] 收到工具调用: {tool_id}, 参数: {tool_params}")  # 打印日志

            # 【P0修复】生成 tool_call_id 并检查重复调用防御
            _param_hash = hashlib.md5(json.dumps(tool_params, sort_keys=True, default=str).encode()).hexdigest()[:8]
            tool_call_id = f"call_{loop_state.round_count}_{tool_id}_{_param_hash}"

            # 检查同一轮或近期是否已处理过完全相同的工具调用
            # 【P1修复】key 增加 session_id，防止跨会话误拦截
            _duplicate_key = f"{session_id}:{tool_id}:{_param_hash}"
            if _duplicate_key in loop_state.processed_tool_calls:
                _cached = loop_state.processed_tool_calls[_duplicate_key]
                # 失败缓存（10s TTL）：直接返回上次错误，避免重复踩坑
                if _cached.get("failure"):
                    if time.time() - _cached.get("timestamp", 0) < 10.0:
                        logger.warning(
                            f"[AgentLoop-DuplicateGuard] 检测到近期失败工具调用: {tool_id} (params_hash={_param_hash}), "
                            f"直接返回上次错误结果。"
                        )
                        result = _cached["result"]
                        execution_history.append({
                            "timestamp": time.time(),
                            "tool": tool_id,
                            "params": tool_params,
                            "result": result,
                            "success": False,
                            "tool_call_id": tool_call_id,
                            "duplicate": True,
                        })
                        working_memory.add_tool_result(tool_id, result)
                        working_memory.append({
                            "role": "system",
                            "source": "agent_loop",
                            "content": f"【重复调用防御】工具 {tool_id} 近期已失败，请勿重复调用。"
                        })
                        sync.emit_event("execution_complete", session_id, {
                            "round": loop_state.round_count,
                            "tool": tool_id,
                            "result": result,
                            "duplicate": True,
                        })
                        loop_state.force_final_answer = True
                        continue
                    else:
                        # 过期清理
                        del loop_state.processed_tool_calls[_duplicate_key]
                        _user_tool_result_cache.get(actual_user_id, {}).pop(_duplicate_key, None)
                        _cached = None

                if _cached:
                    logger.warning(
                        f"[AgentLoop-DuplicateGuard] 检测到重复工具调用: {tool_id} (params_hash={_param_hash}), "
                        f"上轮已执行成功，直接返回缓存结果。"
                    )
                # 将缓存结果作为当前轮次结果，避免再次执行
                result = _cached["result"]
                # 直接追加到 execution_history 和 working_memory
                execution_history.append({
                    "timestamp": time.time(),
                    "tool": tool_id,
                    "params": tool_params,
                    "result": result,
                    "success": result.get("success", False),
                    "tool_call_id": tool_call_id,
                    "duplicate": True,
                })
                working_memory.add_tool_result(tool_id, result)
                working_memory.append({
                    "role": "system",
                    "source": "agent_loop",
                    "content": f"【重复调用防御】工具 {tool_id} 已在近期成功执行，请勿重复调用。"
                })
                sync.emit_event("execution_complete", session_id, {
                    "round": loop_state.round_count,
                    "tool": tool_id,
                    "result": result,
                    "duplicate": True,
                })
                # 【P1修复】重复调用直接强制结束，避免无限循环
                logger.warning(f"[AgentLoop] 检测到重复工具调用 {tool_id}，强制结束任务")
                loop_state.force_final_answer = True
                continue  # 跳过本轮后续处理，直接进入下一轮

            # 【第二阶段改造 2.2】GUI 定位坐标预填充
            # 当键鼠工具缺少精确坐标时，自动调用 GUILocator 获取
            if tool_id in ("mouse_click", "double_click", "right_click", "drag_to"):
                has_x = tool_params.get("x") is not None
                has_y = tool_params.get("y") is not None
                if not (has_x and has_y):
                    target = (
                        tool_params.get("target_element")
                        or tool_params.get("target_description")
                        or user_instruction
                    )
                    try:
                        from core.vision.gui_locator import get_gui_locator
                        locator = get_gui_locator()
                        if await locator.health_check():
                            gui_result = await locator.locate(
                                screenshot=None,
                                description=target
                            )
                            if gui_result and gui_result.get("bbox"):
                                bbox = gui_result["bbox"]
                                tool_params["x"] = (bbox[0] + bbox[2]) // 2
                                tool_params["y"] = (bbox[1] + bbox[3]) // 2
                                tool_params["_gui_located"] = True
                                tool_params["_gui_locator_model"] = gui_result.get("model", "unknown")
                                logger.info(
                                    f"[AgentLoop] GUI定位成功: '{target}' -> "
                                    f"({tool_params['x']}, {tool_params['y']})"
                                )
                            else:
                                logger.info(
                                    f"[AgentLoop] GUI定位未找到: '{target}'，"
                                    f"将让工具自行处理或报错"
                                )
                    except Exception as e:
                        logger.debug(f"[AgentLoop] GUI定位失败(非阻塞): {e}")

            # 【ConsciousnessDirective】意识线程指令覆盖/阻止工具选择
            try:
                tool_id, blocked = _apply_consciousness_directives(
                    tool_id,
                    actual_user_id,
                    working_memory,
                )
                if blocked:
                    result = {
                        "success": False,
                        "error": f"工具 {tool_id} 被意识指令阻止",
                        "user_message": "该工具被意识层临时阻止，请选择其他方式。",
                    }
                    execution_history.append({
                        "timestamp": time.time(),
                        "tool": tool_id,
                        "params": tool_params,
                        "result": result,
                        "success": False,
                    })
                    working_memory.add_tool_result(tool_id, result)
                    continue
                if parsed.target_tool != tool_id:
                    parsed.target_tool = tool_id
            except Exception as cd_err:
                logger.debug(f"[AgentLoop] ConsciousnessDirective 处理异常: {cd_err}")

            # 【P0-1修复】日常模式工具限制：允许使用安全的基础工具
            # 【阶段1-修复2】放宽工具限制，增加常用安全工具
            # 【用户反馈修复】增加UI操作工具，支持基本任务执行
            # 【Phase 4 顺手修复 04-条目42】复用模块级常量 DAILY_MODE_ALLOWED_TOOLS

            # 根据模式过滤工具（work_mode是字符串"daily"/"focus"）
            if work_mode == "daily" and tool_id not in DAILY_MODE_ALLOWED_TOOLS:
                logger.warning(f"[P0-1] 日常模式下禁止调用工具: {tool_id}")
                result = {
                    "success": False,
                    "error": f"日常模式下只能使用以下工具: {', '.join(DAILY_MODE_ALLOWED_TOOLS)}",
                    "user_message": "日常模式仅支持感知和呼叫用户功能，如需使用其他工具，请切换到专注模式。"
                }
                # 将结果添加到执行历史和工作记忆中
                execution_history.append({
                    "timestamp": time.time(),
                    "tool": tool_id,
                    "params": tool_params,
                    "result": result,
                    "success": False,
                })
                working_memory.add_tool_result(tool_id, result)
                # 发送执行完成事件到前端
                sync.emit_event("execution_complete", session_id, {
                    "round": loop_state.round_count,
                    "tool": tool_id,
                    "result": result,
                })
                continue  # 跳过后续处理，进入下一轮循环

            # 【修复】最大重试限制：同一工具在同一任务中最多调用 3 次
            tool_call_count = sum(1 for h in execution_history if h.get("tool") == tool_id)
            if tool_call_count >= 3:
                logger.warning(f"[AgentLoop] 工具 {tool_id} 已在本次任务中调用 {tool_call_count} 次，超过上限，跳过执行")
                max_retry_result = {
                    "success": False,
                    "error_code": "TOOL_MAX_RETRIES_EXCEEDED",
                    "user_message": f"工具 {tool_id} 多次调用未成功，已自动停止重试。请使用替代工具或直接给出最佳回答。",
                    "data": None
                }
                execution_history.append({
                    "timestamp": time.time(),
                    "tool": tool_id,
                    "params": tool_params,
                    "result": max_retry_result,
                    "success": False,
                })
                working_memory.add_tool_result(tool_id, max_retry_result)
                sync.emit_event("execution_complete", session_id, {
                    "round": loop_state.round_count,
                    "tool": tool_id,
                    "result": max_retry_result,
                })
                # 【封印1】工具灾难检测：如果这是唯一被调用过的工具，且已耗尽，强制终止
                other_tools_called = any(
                    h.get("tool") != tool_id
                    for h in execution_history
                    if h.get("tool") and h.get("tool") != "circuit_breaker"
                )
                if not other_tools_called:
                    logger.critical(f"[AgentLoop-CircuitBreaker] 工具灾难：唯一可用工具 {tool_id} 已耗尽，强制终止任务")
                    final_answer = f"抱歉，由于 {tool_id} 暂时不可用，我无法完成此任务。请稍后重试或尝试其他方式。"
                    break

                working_memory.append({
                    "role": "system",
                    "content": f"【系统提示】工具 {tool_id} 已连续调用 {tool_call_count} 次且未成功，请使用替代工具或直接给出最佳回答，不要再调用此工具。"
                })
                continue

            # ═════════════════════════════════════════════════════════════════
            # 【功能恢复 P1】高风险工具预测性反思（异步版本）
            # ═════════════════════════════════════════════════════════════════
            if feature_recovery and feature_recovery.should_run_predictive(tool_id):
                try:
                    pred_reflection = await feature_recovery.run_predictive_reflection(
                        tool_name=tool_id,
                        tool_params=tool_params,
                        user_intent=user_instruction
                    )
                    if pred_reflection and hasattr(pred_reflection, 'metadata'):
                        risk_level = pred_reflection.metadata.get("risk_level", "low")
                        if risk_level in ["high", "critical"]:
                            logger.warning(f"[预测性反思-Async] 工具 {tool_id} 风险评估: {risk_level}")
                except Exception as e:
                    logger.debug(f"[预测性反思-Async] 跳过: {e}")

            # 【Phase 8】世界模型预测 + SafetyHook 已迁移至 CoreLogicHooks.before_tool
            hook_ctx = await agent_loop_hooks.execute_async('before_tool', hook_ctx, parsed=parsed)

            # 读取 world_model 预测结果
            wm_prediction_data = hook_ctx.extra.get('wm_prediction_data', {})
            wm_prediction_text = hook_ctx.extra.get('wm_prediction_text', '')

            # 【Phase 6】处理 SafetyHook 安全阻止结果
            if hook_ctx.extra.get('moral_blocked') or hook_ctx.extra.get('safety_blocked'):
                block_reason = hook_ctx.extra.get('moral_reason') or hook_ctx.extra.get('safety_reason', '未知原因')
                blocked_result = hook_ctx.extra.get('moral_blocked_result') or hook_ctx.extra.get('safety_blocked_result', {})
                blocked_tool_id = hook_ctx.extra.get('moral_tool_id', tool_id) or hook_ctx.extra.get('safety_tool_id', tool_id)
                blocked_tool_params = hook_ctx.extra.get('moral_tool_params', tool_params) or hook_ctx.extra.get('safety_tool_params', tool_params)
                block_type = 'moral' if hook_ctx.extra.get('moral_blocked') else 'safety'

                execution_history.append({
                    'timestamp': time.time(),
                    'tool': blocked_tool_id,
                    'params': blocked_tool_params,
                    'result': blocked_result,
                    'success': False,
                    f'blocked_by_{block_type}': True
                })
                working_memory.add_tool_result(blocked_tool_id, blocked_result)

                sync.emit_event('execution_complete', session_id, {
                    'round': loop_state.round_count,
                    'tool': blocked_tool_id,
                    'result': blocked_result,
                    f'blocked_by_{block_type}': True
                })

                working_memory.append({
                    'role': 'system',
                    'content': f'【系统提示】您尝试调用的工具\'{blocked_tool_id}\'被安全检查系统阻止。原因: {block_reason}。请重新评估您的决策，选择更合适的工具或向用户解释无法执行此操作的原因。'
                })
                continue


            # 发送执行事件到前端（包含世界模型预测）  # 发送事件
            print("[AgentLoop] [TOOL] 发送 executing 事件到前端")  # 打印日志
            sync.emit_event("executing", session_id, {  # 发送执行事件
                "round": loop_state.round_count,  # 轮次
                "tool": tool_id,  # 工具ID
                "params": tool_params,  # 参数
                "world_model_prediction": wm_prediction_text  # AI能看到的预测
            })  # 事件结束

            # =============================================================================
            # 【三省六部流程透视镜】发送工具链节点更新
            # =============================================================================
            try:
                sync.emit_event("tool_node_update", session_id, {
                    "node_id": tool_id,
                    "status": "executing",
                    "params": tool_params,
                    "start_time": time.time()
                })
            except Exception as e:
                logger.warning(f"[ThreeViews] 发送工具节点更新失败: {e}")

            # 【三省六部流程透视镜】高风险操作检测和用户确认
            # 定义高风险工具
            HIGH_RISK_TOOLS = ['file_delete', 'delete', 'remove', 'exec', 'eval', 'shell', 'system']
            risk_level = "low"
            if tool_id in HIGH_RISK_TOOLS or any(risk_tool in tool_id.lower() for risk_tool in HIGH_RISK_TOOLS):
                risk_level = "high"
                # 发送用户确认请求
                request_user_confirmation(
                    session_id=session_id,
                    step=f"执行高风险操作: {tool_id}",
                    tool=tool_id,
                    params=tool_params,
                    risk_level="high",
                    timeout=30
                )
                # 注意：这里仅发送请求，实际执行需要等待前端确认
                # 在实际实现中，可能需要暂停循环等待用户确认
                logger.info(f"[ThreeViews] 高风险操作 '{tool_id}' 等待用户确认")

            # 发送工具链规划（更新状态）
            try:
                # 构建工具链
                tool_chain = []
                for idx, hist in enumerate(execution_history):
                    tool_chain.append({
                        "id": hist.get("tool", f"step_{idx}"),
                        "tool": hist.get("tool", ""),
                        "params": hist.get("params", {}),
                        "status": "completed" if hist.get("success") else "failed"
                    })
                # 添加当前执行的工具
                tool_chain.append({
                    "id": tool_id,
                    "tool": tool_id,
                    "params": tool_params,
                    "status": "executing",
                    "world_model_prediction": wm_prediction_text
                })
                send_tool_chain_planned(session_id, tool_chain)
            except Exception as e:
                logger.warning(f"[ThreeViews] 发送工具链规划失败: {e}")

            # 更新任务步骤状态
            try:
                if initial_steps:
                    for step in initial_steps:
                        if step.get("tool") == tool_id and step.get("status") == "pending":
                            step["status"] = "executing"
                            break
                    send_task_breakdown(session_id, user_instruction, initial_steps)
            except Exception as e:
                logger.warning(f"[ThreeViews] 更新任务步骤状态失败: {e}")

            # 如果世界模型有高置信度预测，发送给前端展示  # 高置信度
            if wm_prediction_text:  # 有预测文本
                # 1. 发给前端（现有）  # 前端展示
                sync.emit_event("thinking", session_id, {  # 发送思考事件
                    "content": f"[历史经验] 根据历史经验:\n{wm_prediction_text}",  # 内容
                    "intent": "world_model_prediction",  # 意图类型
                    "is_auxiliary": True  # 辅助标记
                })  # 事件结束

            # 2. ✅ 新增：将结构化预测数据加入AI提示词  # 提示词增强
            if wm_prediction_data:  # 有预测数据
                prediction_text = f"""  # 构建预测文本
【世界模型预测】  # 标题
基于历史经验分析：  # 说明
- 操作成功率: {wm_prediction_data.get('confidence', '未知')}%  # 成功率
- 建议: {wm_prediction_data.get('suggestion', '无')}  # 建议
- 风险提示: {wm_prediction_data.get('risk', '无')}  # 风险

建议：{'谨慎操作' if wm_prediction_data.get('confidence', 100) < 70 else '可以执行'}  # 建议
"""  # 文本结束
                working_memory.append({  # 添加
                    "role": "system",  # 系统角色
                    "content": prediction_text  # 内容
                })  # 添加结束

                # 3. 低成功率时额外警告  # 低成功率警告
                if wm_prediction_data.get('confidence', 100) < 50:  # 成功率低于50%
                    working_memory.append({  # 添加警告
                        "role": "system",  # 系统角色
                        "content": "⚠️ 警告：此操作历史成功率较低，建议寻找替代方案或请求用户确认。"  # 内容
                    })  # 添加结束

            # ========== 【阶段锚点 - 工具执行前】（异步版补齐）==========
            # 同步版在 _run_agent_loop_impl 第 3238-3269 行有完整实现
            should_save_anchor = True
            try:
                from core.tool.tool_manager import tool_manager
                tool_obj = tool_manager.get_tool(parsed.target_tool)
                if tool_obj and hasattr(tool_obj, 'check_params'):
                    tool_obj.check_params(**parsed.params)
            except Exception as param_err:
                should_save_anchor = False
                logger.warning(f"[PhaseAnchor-Async] 工具参数校验失败，跳过保存锚点: {parsed.target_tool}, params={parsed.params}, error={param_err}")

            if should_save_anchor:
                try:
                    await working_memory.save_phase_anchor("tool_execute", {
                        "tool": parsed.target_tool,
                        "params": parsed.params,
                        "step": len(execution_history) + 1
                    })
                except Exception as e:
                    logger.warning(f"[AgentLoop] working_memory.save_phase_anchor 失败: {e}")
                try:
                    await phase_anchor_manager.save(
                        phase="tool_execute",
                        data={
                            "tool": parsed.target_tool,
                            "params": parsed.params,
                            "step": len(execution_history) + 1
                        },
                        user_id=actual_user_id,
                        session_id=session_id,
                        task_id=effective_task_id if 'effective_task_id' in locals() else (task_id or task.id)
                    )
                    logger.debug(f"[PhaseAnchor-Async] 工具执行前锚点已保存: {parsed.target_tool}")
                except Exception as anchor_err:
                    logger.error(f"[PhaseAnchor-Async] 保存锚点到PostgreSQL失败: {anchor_err}", exc_info=True)

            # ═════════════════════════════════════════════════════════════════════════════
            # 【Phase X】before_step Hook：断点步骤开始记录已迁移到 ToolHook
            # ═════════════════════════════════════════════════════════════════════════════
            current_step = len(execution_history) + 1
            step_info = {
                "number": current_step,
                "goal": f"执行第{current_step}步: {tool_id}",
                "tool_id": tool_id,
                "tool_params": tool_params,
                "context": {
                    "working_memory": working_memory.to_dict() if hasattr(working_memory, 'to_dict') else {},
                    "user_instruction": user_instruction,
                }
            }
            hook_ctx.extra["current_step_info"] = step_info
            hook_ctx = await agent_loop_hooks.execute_async('before_step', hook_ctx, step=step_info)

            # 【修复】工具执行前检查中断信号（异步版本）
            if interrupt_handler.is_interrupted(task.id):
                logger.info(f"[AgentLoop] 工具执行前检测到中断信号，任务: {task.id}")
                state_persistence.save(state)
                # 【Phase 1】on_interrupt Hook（异步版本）
                hook_ctx = await agent_loop_hooks.execute_async('on_interrupt', hook_ctx, reason="pre_tool_interrupt")
                raise AgentLoopInterrupted("[AgentLoop] 工具执行前检测到中断信号，循环终止")


            # ═════════════════════════════════════════════════════════════════════════════
            # 【认知闭环】高置信度策略模式检查（来自反思系统 L4 evolve）
            # 在工具执行前，检索已验证的高置信度策略并注入 Prompt
            # ═════════════════════════════════════════════════════════════════════════════
            try:
                # VERIFIED-ASYNC: query_memories 底层使用 asyncpg pool.fetch()，真异步 I/O，可原地 await
                hard_rules = await memory_service.query_memories(
                    user_id=actual_user_id,
                    layer="evolve",
                    mem_type="knowledge",
                    limit=5,
                    min_rating=9,
                )
                for rule in hard_rules:
                    if not isinstance(rule, dict):
                        continue
                    # 只处理 source 为 reflection 的策略
                    if rule.get("source") != "reflection":
                        continue
                    content = rule.get("content", "")
                    if not isinstance(content, str):
                        continue
                    # 解析策略内容（StrategyPattern 存为 JSON）
                    try:
                        rule_data = json.loads(content)
                        applicable_scenarios = rule_data.get("applicable_scenarios", [])
                        strategy_steps = rule_data.get("strategy_steps", [])
                        description = rule_data.get("description", "")
                    except Exception:
                        # 非 JSON，直接用字符串匹配
                        applicable_scenarios = [content]
                        strategy_steps = []
                        description = content

                    # 检查当前工具是否在适用场景中
                    tool_match = any(
                        parsed.target_tool in str(s) for s in applicable_scenarios
                    ) or any(
                        parsed.target_tool in str(s) for s in strategy_steps
                    )

                    if tool_match:
                        steps_str = "\n".join(
                            f"  {i+1}. {s}" for i, s in enumerate(strategy_steps[:5])
                        ) if strategy_steps else ""
                        strategy_msg = (
                            f"[已验证策略 - 置信度{rule.get('rating', 0)}/10] {description}\n"
                            f"{steps_str}\n"
                            f"**此策略来自历史反思验证，执行前请确认符合当前场景。**"
                        )
                        working_memory.append({
                            "role": "system",
                            "content": strategy_msg
                        })
                        logger.info(
                            f"[AgentLoop-Policy] 高置信度策略已注入: "
                            f"工具={parsed.target_tool}, "
                            f"策略={description[:50]}..."
                        )
            except Exception as _strategy_e:
                logger.error(f"[AgentLoop] 策略检查失败: {_strategy_e}", exc_info=True)

            print("[AgentLoop] [TOOL] 调用 intent_handler.handle_tool_call...")  # 打印日志

            # 【P1】言行一致性拦截：语音含暂停用语时，非查看类工具延迟执行
            try:
                from core.runtime import system_state
                current_speech = system_state.get_sync("speech.current_text", "")
                if current_speech and any(word in current_speech for word in ["等等", "让我看看", "等一下", "先别"]):
                    if parsed.target_tool not in ["screenshot", "get_window_info", "visual_understand"]:
                        logger.info(f"[AgentLoop-Consistency] 播报含暂停用语，延迟 {parsed.target_tool} 执行")
                        parsed.params["_delayed_by_speech"] = True
                        # 跳过本轮工具执行，等下一轮确认
                        res = {"result": {"success": False, "error_code": "DELAYED_BY_SPEECH", "user_message": "语音播报中指示暂停，工具执行已延迟"}}
                        # 仍然走协调器注册/完成，保持状态一致性
                        coordinator = get_action_coordinator()
                        if not coordinator._subscriptions_setup:
                            coordinator.setup_subscriptions()
                        await coordinator.register(
                            action_id=f"tool_{parsed.target_tool}_delayed",
                            action_type=ActionType.TOOL,
                            priority=1,
                            payload={"tool": parsed.target_tool, "delayed": True}
                        )
                        await coordinator.complete(f"tool_{parsed.target_tool}_delayed")
                        # 跳过正常工具执行流程
                        pass
                    else:
                        # 查看类工具不受限制，正常执行
                        from core.intent.intent_handler import tool_call_phase
                        phase_ctx.set("parsed_intent", parsed)
                        pass
                else:
                    from core.intent.intent_handler import tool_call_phase
                    phase_ctx.set("parsed_intent", parsed)
                    pass
            except Exception as _consistency_e:
                logger.debug(f"[AgentLoop-Consistency] 拦截检查异常: {_consistency_e}")
                from core.intent.intent_handler import tool_call_phase
                phase_ctx.set("parsed_intent", parsed)

            # 【协调层】工具执行前注册协调器
            # 根据工具ID映射到更细粒度的动作类型，让ActionCoordinator知道是鼠标/键盘/通用工具
            _tool_action_type_map = {
                "mouse_click": ActionType.MOUSE,
                "pixel_click": ActionType.MOUSE,
                "click_text": ActionType.MOUSE,
                "keyboard_input": ActionType.KEYBOARD,
            }
            _mapped_action_type = _tool_action_type_map.get(parsed.target_tool, ActionType.TOOL)
            coordinator = get_action_coordinator()
            if not coordinator._subscriptions_setup:
                coordinator.setup_subscriptions()
            coord_slot = await coordinator.register(
                action_id=f"tool_{parsed.target_tool}",
                action_type=_mapped_action_type,
                priority=3,
                payload={"tool": parsed.target_tool, "params": parsed.params}
            )

            # 【Reflector】行动前预测性反思
            if reflector is not None:
                try:
                    _before_action_reflection = await reflector.reflect_before_action(
                        planned_action={
                            "tool": parsed.target_tool,
                            "params": parsed.params,
                            "description": f"执行工具 {parsed.target_tool}，参数: {json.dumps(parsed.params, ensure_ascii=False, default=str)[:200]}"
                        },
                        context={
                            "task": user_instruction,
                            "round": loop_state.round_count,
                            "execution_history_count": len(execution_history),
                            "user_id": actual_user_id
                        }
                    )
                    if _before_action_reflection and getattr(_before_action_reflection, "suggestion", None):
                        _risk_factors = getattr(_before_action_reflection, "metadata", {}).get("risk_factors", [])
                        if _risk_factors:
                            working_memory.append({
                                "role": "system",
                                "content": f"【行动前反思】风险: {', '.join(str(r) for r in _risk_factors)}；建议: {_before_action_reflection.suggestion}"
                            })
                            logger.info(f"[AgentLoop] 行动前反思建议已注入: tool={parsed.target_tool}")
                except Exception as e:
                    logger.error(f"[AgentLoop] 行动前反思失败: {e}", exc_info=True)

            res = await tool_call_phase(phase_ctx)  # 【Phase 4】异步工具调用入口

            # 【协调层】工具执行完成
            await coordinator.complete(f"tool_{parsed.target_tool}")

            # 【Phase 6 修复】增强层过滤提前注入 _feedback_decision，避免与 ToolHook 双写
            _filter_result = res.get("result", {}) if isinstance(res, dict) else {}
            _feedback_decision = {
                "should_add_to_context": True,
                "formatted_content": None,
                "level": "interactive",
                "used_enhancement": False,
            }
            try:
                from core.consciousness import EventSource, filter_with_enhancement
                _enhanced_decision = await filter_with_enhancement(
                    tool_id=tool_id,
                    result=_filter_result,
                    source=EventSource.AI_EXPLICIT,
                    context={
                        "current_task": user_instruction,
                        "goal": getattr(working_memory, 'goal', ''),
                        "round": loop_state.round_count,
                        "execution_history_count": len(execution_history)
                    },
                    user_id=getattr(working_memory, 'user_id', 'default')
                )
                _feedback_decision["should_add_to_context"] = _enhanced_decision.level != _enhanced_decision.level.SILENT
                _feedback_decision["formatted_content"] = _enhanced_decision.content
                _feedback_decision["level"] = _enhanced_decision.level.value
                _feedback_decision["used_enhancement"] = True
                logger.debug(
                    f"[AgentLoop] 增强层决策: {tool_id} -> "
                    f"{_enhanced_decision.level.value}, 原因: {_enhanced_decision.reason}"
                )
            except Exception as _filter_e:
                diagnostic_except_handler(_filter_e, context="[AgentLoop] 增强层过滤失败", logger_instance=logger)
                try:
                    from core.tool.tool_manager import tool_manager
                    _fb = await tool_manager.format_feedback_for_ai(tool_id, _filter_result, working_memory)
                    _feedback_decision["formatted_content"] = _fb
                except Exception as _fmt_e:
                    diagnostic_except_handler(_fmt_e, context="[AgentLoop] tool_manager.format_feedback_for_ai 失败", logger_instance=logger)
                    _feedback_decision["formatted_content"] = _filter_result.get("user_message", "")
            if isinstance(_filter_result, dict):
                _filter_result["_feedback_decision"] = _feedback_decision
            if isinstance(res, dict) and isinstance(res.get("result"), dict):
                res["result"]["_feedback_decision"] = _feedback_decision

            # 【Phase 6】预填充 extra，供 after_tool 注册链统一读取（异步版）
            hook_ctx.extra["last_tool_id"] = parsed.target_tool
            hook_ctx.extra["vision_enabled"] = vision_enabled
            hook_ctx.extra["change_detector"] = change_detector
            hook_ctx.extra["loop_state"] = loop_state
            hook_ctx.extra["parsed"] = parsed
            hook_ctx.extra["execution_history"] = execution_history
            hook_ctx.extra["reflector"] = reflector
            hook_ctx.extra["state"] = state
            hook_ctx.extra["chat_history"] = chat_history
            hook_ctx.extra["last_response"] = response
            hook_ctx.extra["actual_user_id"] = actual_user_id
            hook_ctx.extra["effective_task_id"] = effective_task_id
            hook_ctx.extra["precision_parsed"] = precision_parsed
            hook_ctx.extra["ai_reply"] = ai_reply
            hook_ctx.extra["initial_steps"] = initial_steps
            hook_ctx.extra["user_instruction"] = user_instruction
            hook_ctx.extra["task_state"] = task_state
            hook_ctx.extra["current_step"] = current_step
            hook_ctx.extra["tool_params"] = tool_params
            proc_learning_integration = get_procedure_learning_integration() if PROCEDURE_LEARNING_INTEGRATION_AVAILABLE else None
            hook_ctx.extra["proc_learning_integration"] = proc_learning_integration
            hook_ctx.extra["voice_instance"] = voice_instance

            # 【Phase 6】after_tool Hook 统一由注册表驱动（异步版）
            # VisionHook / ToolHook / VoiceHook / SafetyHook 均已在模块级注册
            hook_ctx = await agent_loop_hooks.execute_async('after_tool', hook_ctx, tool_result=res)

            # 【防御性编程】检查返回值有效性 - 无效时抛异常，禁止静默处理
            if res is None:
                error_msg = f"[AgentLoop] handle_tool_call 返回 None，task_id={task.id}, session={session_id}"
                logger.error(error_msg)
                raise RuntimeError(error_msg)

            if not isinstance(res, dict) or "result" not in res:
                error_msg = f"[AgentLoop] handle_tool_call 返回结构异常: {type(res)}, task_id={task.id}"
                logger.error(error_msg)
                raise RuntimeError(error_msg)

            result = res["result"]  # 获取结果
            _tool_success = result.get("success", False) if isinstance(result, dict) else False
            _wm_has_tool = any(m.get("role") == "system" and tool_id in str(m.get("content", "")) for m in (working_memory.messages if hasattr(working_memory, 'messages') else []))
            logger.info(f"[Diag] Tool executed: {tool_id} success={_tool_success} wm_added={_wm_has_tool}")

            # 【P1-1】记录工具执行到 trace 索引
            try:
                record_tool(trace_id, tool_id, result.get("success", False) if isinstance(result, dict) else False)
            except Exception as e:
                logger.error(f"[AgentLoop] 记录工具执行trace失败 (tool_id={tool_id}): {e}", exc_info=True)

            # 【P0修复】工具执行后缓存结果，用于重复调用防御
            _param_hash_cache = hashlib.md5(json.dumps(tool_params, sort_keys=True, default=str).encode()).hexdigest()[:8]
            _dup_key_cache = f"{session_id}:{tool_id}:{_param_hash_cache}"
            if result and result.get("success", False):
                loop_state.processed_tool_calls[_dup_key_cache] = {
                    "result": result,
                    "timestamp": time.time(),
                    "round": loop_state.round_count,
                    "failure": False,
                }
                logger.info(f"[AgentLoop-DuplicateGuard] 缓存工具成功结果: {tool_id} (key={_dup_key_cache})")
            elif result:
                # 【P1修复】失败调用也缓存 10s，避免同任务内重复踩坑
                loop_state.processed_tool_calls[_dup_key_cache] = {
                    "result": result,
                    "timestamp": time.time(),
                    "round": loop_state.round_count,
                    "failure": True,
                }
                logger.info(f"[AgentLoop-DuplicateGuard] 缓存工具失败结果(10s TTL): {tool_id} (key={_dup_key_cache})")

            # 【Phase 6 修复】工具反馈（chat_history / working_memory / execution_history）
            # 已由 after_tool Hook 链统一处理，此处不再重复 append。
            # 增强层过滤决策已提前注入 result["_feedback_decision"].

            # 【修复】工具执行后检查中断信号（异步版本）
            if interrupt_handler.is_interrupted(task.id):
                logger.info(f"[AgentLoop] 工具执行后检测到中断信号，任务: {task.id}")
                state_persistence.save(state)
                # 【Phase 1】on_interrupt Hook（异步版本）
                hook_ctx = await agent_loop_hooks.execute_async('on_interrupt', hook_ctx, reason="post_tool_interrupt")
                raise AgentLoopInterrupted("[AgentLoop] 工具执行后检测到中断信号，循环终止")

            # ═════════════════════════════════════════════════════════════════════════════
            # 【Phase X】after_step Hook：断点步骤完成记录已迁移到 ToolHook
            # ═════════════════════════════════════════════════════════════════════════════
            step_info = hook_ctx.extra.get("current_step_info", {})
            hook_ctx = await agent_loop_hooks.execute_async('after_step', hook_ctx, step=step_info, result=result)
            # 使用SafeDictAccessor安全访问工具结果  # 安全访问
            result_accessor = SafeDictAccessor(result)  # 创建访问器
            print(f"[AgentLoop] [TOOL] 工具执行结果: success={result_accessor.get('success')}, message={result_accessor.get('user_message', '')[:50]}")  # 打印结果

            # （execution_history 追加、state 更新、tool_result 事件已由 Phase 3b ToolHook 统一处理）

            # =========================================
            # 【反思系统集成】工具失败/空结果时触发深度反思
            # =========================================
            async def is_empty_result_async(result_data: dict) -> bool:
                """检查结果是否为空或无效"""
                if not result_data:
                    return True
                data = result_data.get("data")
                if data is None:
                    return True
                return bool(isinstance(data, (list, dict, str)) and len(data) == 0)

            # 判断是否需要触发反思：失败或空结果
            tool_failed_async = not result.get("success", False)
            tool_empty_async = await is_empty_result_async(result)

            if tool_failed_async or tool_empty_async:
                try:
                    # 【修复】直接使用模块级别的reflector变量，不要局部导入

                    if reflector is None:
                        logger.error("[AgentLoop] Reflector未初始化，跳过异步工具失败反思")
                        raise Exception("Reflector not initialized")

                    # 【Phase 4】工具失败反思已抽取到 reflection_bridge
                    await run_tool_failure_reflection(
                        reflector=reflector,
                        user_instruction=user_instruction,
                        parsed=parsed,
                        result=result,
                        execution_history=execution_history,
                        working_memory=working_memory,
                        chat_history=chat_history,
                        tool_empty_async=tool_empty_async,
                        tool_failed_async=tool_failed_async,
                    )
                except Exception as e:
                    logger.warning(f"[AgentLoop] 工具失败反思系统调用失败: {e}")
                    working_memory.append({
                        "role": "system",
                        "content": f"工具{parsed.target_tool}执行未成功，请分析原因并尝试其他方法继续完成任务。"
                    })

            # （chat_history 基础反馈追加已由 Phase 3b ToolHook 统一处理）

            # 语音播报工具执行结果  # 语音播报
            # [关键] 检查是否应该继续循环  # 继续检查
            should_continue = res.get("should_continue", True)  # 获取标志

            # 【反思系统集成】如果触发了反思，强制继续循环让AI调整策略
            if getattr(working_memory, 'force_continue', False):
                should_continue = True
                working_memory.force_continue = False  # 重置标志
                logger.info("[AgentLoop] 反思触发，强制继续循环让AI调整策略")

            if not should_continue:  # 不继续
                logger.info("[AgentLoop] 错误结束: 工具处理返回should_continue=False")  # 记录日志
                break  # 跳出循环

            # 【Phase X】反思系统 + 进化引擎已迁移到 ToolHook.after_step

            # （just_executed_tool / last_tool_result 标记、add_tool_result 已由 Phase 3b ToolHook 统一处理）

            # =============================================================================
            # 【SmartContextManager集成】记录步骤完成
            # =============================================================================
            smart_context_step_result = None
            if smart_context_enabled and smart_context_manager:
                try:
                    smart_context_step_result = smart_context_manager.on_step_complete(
                        task_id=effective_task_id,
                        step_number=loop_state.round_count,
                        action=f"执行工具: {parsed.target_tool}",
                        result=result.get("user_message", ""),
                        success=result.get("success", False),
                        tool_name=parsed.target_tool,
                        context={
                            'before': {'tool': parsed.target_tool, 'params': parsed.params},
                            'after': {'success': result.get("success", False), 'result': result}
                        }
                    )

                    # 如果有干预建议，添加到工作记忆
                    if smart_context_step_result.get('intervention'):
                        working_memory.append({
                            "role": "system",
                            "content": f"[系统提醒] {smart_context_step_result['intervention']}"
                        })
                        logger.info("[SmartContext] 已添加干预提醒到工作记忆")

                    # 将 SmartContext 结果传递给 after_step Hook 处理断点保存
                    hook_ctx.extra["smart_context_step_result"] = smart_context_step_result
                    hook_ctx.extra["smart_context_manager"] = smart_context_manager

                except Exception as e:
                    logger.debug(f"[SmartContext] 步骤记录失败: {e}")

            # 【P1断裂点#3修复】记录工具执行到历史用于进化分析
            task_history.append({
                "tool": parsed.target_tool,
                "params": parsed.params if 'parsed' in locals() else {},
                "success": result.get("success", False),
                "task_desc": user_instruction if 'user_instruction' in locals() else "",
                "error_info": result.get("user_message", "") if not result.get("success", False) else ""
            })

            # 【GoalSystem】工具执行后评估是否完成某个 subgoal
            try:
                from core.strategy.goal_system import get_goal_system
                goal_system = get_goal_system()
                active_goal = goal_system.get_top_priority_goal()
                if active_goal and active_goal.subgoals:
                    completed_sg = goal_system.evaluate_tool_subgoal_completion(
                        active_goal,
                        parsed.target_tool,
                        result,
                        user_instruction if 'user_instruction' in locals() else "",
                    )
                    if completed_sg:
                        goal_system.complete_subgoal(active_goal.goal_id, completed_sg.goal_id)
                        logger.info(
                            f"[GoalSystem] subgoal完成: {completed_sg.name} "
                            f"(工具: {parsed.target_tool})"
                        )
            except Exception as sg_err:
                logger.debug(f"[AgentLoop] 目标进度评估失败: {sg_err}")

            # 【P0修复】单步完成工具快速路径：成功后直接结束，避免AI无意义循环
            SINGLE_STEP_TOOLS = {
                "launch_app", "close_app", "kill_process",
                "screenshot", "get_time", "get_date",
                "get_weather", "calculate", "search_web",
                "system_info", "volume_control", "brightness_control",
                "clipboard_read", "clipboard_write",
            }
            is_single_step = parsed.target_tool in SINGLE_STEP_TOOLS

            if is_single_step and result.get("success", False):
                # 检查任务是否包含多步骤关键词
                multi_step_kw = ["并", "和", "然后", "接着", "再", "先", "后", "最后", "以及", "顺便", "一起", "同时", "并且",
                                 "输入", "写入", "填写", "点击", "选择", "保存", "发送", "播放", "打开后", "关闭后", "删除后", "复制后", "粘贴后",
                                 "搜索", "查找", "查询", "多少钱", "告诉我", "说一下", "讲一讲", "介绍"]
                task_lower = (user_instruction or "").lower()
                has_multi_step = any(kw in task_lower for kw in multi_step_kw)

                if not has_multi_step:
                    logger.info(f"[AgentLoop] 单步工具 '{parsed.target_tool}' 成功执行，任务 '{user_instruction}' 无多步骤指示，强制下一轮结束")
                    # 向 working_memory 注入高优先级任务完成提示，引导AI自行输出final_answer
                    working_memory.append({
                        "role": "system",
                        "content": (
                            f"【任务状态】工具 '{parsed.target_tool}' 已成功执行，任务目标已达成。"
                            f"请立即输出 final_answer 总结执行结果，不要再调用任何工具。"
                            f"最终答案格式示例：```json\n{{\"action\": \"final_answer\", \"content\": \"已成功为您完成任务。\"}}\n```"
                        ),
                        "_category": "task_complete",
                        "_overwrite": True,
                    })
                    # 【P1修复】设置强制结束标志，下一轮将意图修正为 FINAL_ANSWER
                    loop_state.force_final_answer = True
                    continue

            # 【Reflector】工具执行后反思（使用 reflect_with_dedup 去重）
            if reflector is not None:
                try:
                    from core.agent.reflection_bridge import reflect_with_dedup
                    reflection = await reflect_with_dedup(
                        reflector=reflector,
                        task=user_instruction,
                        step_info={
                            "tool": parsed.target_tool,
                            "result": result,
                            "success": result.get("success", False) if isinstance(result, dict) else False,
                            "params": parsed.target_tool_params if hasattr(parsed, "tool_params") else {}
                        },
                        trajectory=execution_history[-3:] if len(execution_history) >= 3 else execution_history,
                        reflection_type="general"
                    )
                    if reflection:
                        reflect_result = reflection.to_dict() if hasattr(reflection, 'to_dict') else {}
                        if reflect_result and reflect_result.get("metadata", {}).get("should_retry"):
                            adjust_msg = reflect_result.get("suggestion", "")
                            if adjust_msg:
                                working_memory.append({"role": "system", "content": f"【策略调整】{adjust_msg}"})
                except Exception as e:
                    logger.error(f"[AgentLoop] 步骤反思失败: {e}", exc_info=True)

            # 诊断：轮次总结
            _sensor_len = len(last_vision_description) if last_vision_description else 0
            _ctx_len = len(full_system_prompt) if full_system_prompt else 0
            _tool_count = len([h for h in execution_history if h.get("tool")])
            logger.info(f"[Diag] R{loop_state.round_count} done: sensors={_sensor_len} ctx={_ctx_len} tools={_tool_count} mem=True")

            # 继续下一轮循环（让AI基于工具结果继续思考）  # 继续循环
            continue  # continue

        elif parsed.intent_type == IntentType.FINAL_ANSWER:  # 最终答案
            res = intent_handler.handle_final_answer(parsed, working_memory)  # 处理
            answer = res["answer"]  # 获取答案

            # 【精准抓取】优先使用解析的自然语言  # 优先使用精准抓取
            if precision_parsed.natural_language:  # 有自然语言
                cleaned = precision_parsed.natural_language  # 使用精准抓取的
                logger.info(f"[Precision] 使用精准抓取的自然语言: {cleaned[:50]}...")  # 记录日志
            else:  # 无
                cleaned = extract_natural_language(answer)  # 提取

            # [修复] 多步骤任务检查 - 如果刚执行完工具且任务可能未完成，强制继续  # 任务完成检查
            if getattr(working_memory, 'just_executed_tool', False) and not check_task_completed(working_memory, user_instruction, execution_history):  # 刚执行完工具且未完成
                    logger.info("[AgentLoop] AI返回FINAL_ANSWER但任务未完成，强制继续执行")  # 记录日志
                    working_memory.just_executed_tool = False  # 清除标记
                    # 添加系统提示让AI继续  # 提示继续
                    working_memory.append({  # 添加
                        "role": "system",  # 系统角色
                        "content": f"任务'{user_instruction}'尚未完成，请继续执行剩余步骤。"  # 内容
                    })  # 添加结束
                    continue  # 强制继续

            # 【修复】检查用户请求是否需要执行操作，但AI只是聊天回复而未调用工具
            if not execution_history and is_action_required(user_instruction):
                logger.info("[AgentLoop] 用户请求需要执行操作，但AI返回FINAL_ANSWER，强制要求调用工具")
                working_memory.append({
                    "role": "system",
                    "content": f"用户请求'{user_instruction}'需要执行具体操作。请使用工具调用完成该任务，不要只是文字回复。输出JSON格式的工具调用。"
                })
                continue  # 强制继续循环，要求AI调用工具

            # 【Phase 6】FINAL_ANSWER 语音播报已迁移到 VoiceHook.on_complete（异步版）
            await agent_loop_hooks.execute_async('on_complete', hook_ctx, answer=cleaned)

            logger.info("[AgentLoop] 正常结束: AI返回最终答案，任务完成")  # 记录日志

            # ====== 【目标系统调用】任务成功时更新目标进度 ======  # 目标系统
            try:  # 异常处理
                from core.strategy.goal_system import get_goal_system  # 导入
                goal_system = get_goal_system()  # 获取系统
                active_goal = goal_system.get_top_priority_goal()  # 获取活跃目标
                if active_goal:  # 有目标
                    # 检查用户指令是否与目标描述相关  # 相关性检查
                    goal_keywords = active_goal.description.lower()  # 目标关键词
                    instruction_lower = user_instruction.lower()  # 指令小写
                    # 简单的关键词匹配（可以扩展为更复杂的语义匹配）  # 匹配
                    if any(kw in instruction_lower for kw in goal_keywords.split() if len(kw) > 2):  # 有匹配
                        goal_system.update_progress(active_goal.goal_id, 1.0)  # 更新进度100%（函数接收0-1）
                        logger.info(f"[GoalSystem] 目标 '{active_goal.name}' 进度更新为 100%")  # 记录日志
            except Exception as e:  # 捕获异常
                logger.warning(f"[GoalSystem] 更新目标进度失败（不影响执行）: {e}")  # 记录警告

            # 检查 AI 是否自己写了记忆  # 记忆检查
            ai_wrote_memory = any(  # 检查
                h.get("tool") == "memory_add" and h.get("success", False)  # 记忆添加且成功
                for h in execution_history  # 遍历历史
            )  # 检查结束

            if ai_wrote_memory:  # AI写了记忆
                logger.info("[AgentLoop] AI 已自主记录记忆，底座跳过自动萃取")  # 记录日志
            else:  # AI没写
                # 底座自动萃取存储  # 自动萃取
                try:
                    await execution_memory.store(user_instruction, execution_history,  # 存储
                                                       final_result=answer, is_success=True)  # 参数
                except Exception as e:
                    logger.warning(f"[AgentLoop] 执行记忆存储失败: {e}")

            # 【记忆存储】将对话存储到记忆系统
            try:
                from core.memory.memory_schema import MemoryMetadata

                logger.info(f"[Diag] Memory save: save_chat_turn triggered, trace_id={trace_id}")

                # 存储用户输入 + AI 响应到 MemoryService（后台，避免 ChromaDB 同步 I/O 阻塞事件循环）
                async def _bg_save_chat_turn(session_id: str, role: str, content: str, metadata: MemoryMetadata):
                    try:
                        await memory_service.save_chat_turn(session_id, role, content, metadata)
                    except Exception:
                        logger.exception(
                            "[MemoryService] save_chat_turn 后台任务失败——"
                            "VectorStore.add() 执行失败"
                        )

                has_tools = bool(execution_history and any(h.get("tool") for h in execution_history))

                meta_user = MemoryMetadata(
                    user_id=actual_user_id,
                    source="user_input",
                    content_type="text",
                    payload_summary=user_instruction[:200],
                    raw_payload=json.dumps(
                        {"text": user_instruction, "session_id": session_id, "mode": mode, "has_tool_calls": has_tools},
                        ensure_ascii=False, default=str,
                    ),
                    session_id=session_id,
                )
                _task_save_user = safe_create_task(_bg_save_chat_turn(session_id, "user", user_instruction, meta_user), name="save_user_msg")
                _task_save_user.add_done_callback(
                    lambda t: logger.error(f"[AgentLoop] 用户输入保存任务异常: {t.exception()}") if t.exception() else None
                )

                meta_ai = MemoryMetadata(
                    user_id=actual_user_id,
                    source="ai_response",
                    content_type="text",
                    payload_summary=cleaned[:200],
                    raw_payload=json.dumps(
                        {"text": cleaned, "session_id": session_id, "mode": mode, "has_tool_calls": has_tools},
                        ensure_ascii=False, default=str,
                    ),
                    session_id=session_id,
                )
                _task_save_ai = safe_create_task(_bg_save_chat_turn(session_id, "assistant", cleaned, meta_ai), name="save_ai_msg")
                _task_save_ai.add_done_callback(
                    lambda t: logger.error(f"[AgentLoop] AI响应保存任务异常: {t.exception()}") if t.exception() else None
                )

                # 如果有工具调用，额外存储到L5执行记忆
                if execution_history and any(h.get("tool") for h in execution_history):
                    await execution_memory.store(
                        user_input=user_instruction,
                        execution_history=execution_history,
                        final_result=cleaned,
                        is_success=True,
                        user_id=actual_user_id,
                        session_id=session_id
                    )

                logger.info(f"[Memory] 对话已存储到记忆系统，用户: {actual_user_id}")

            except Exception as e:
                logger.error(f"[AgentLoop] [Memory] 存储对话记忆失败: {e}", exc_info=True)

            # 【游戏化】任务完成获得经验值（已抽取到 gamification_bridge）
            from core.agent.gamification_bridge import update_gamification_async
            await update_gamification_async(
                user_id=user_id,
                session_id=session_id,
                execution_history=execution_history,
                logger_instance=logger,
            )

            # 【贝叶斯反思】任务完成时触发反思，更新策略信念
            try:
                if reflector is not None:
                    reflection, pattern = await reflector.reflect_on_completion(
                        task=user_instruction,
                        trajectory=execution_history,
                        success=True,
                        final_answer=answer
                    )

                    # 提取的策略模式被正确保存，贝叶斯更新在reflect_on_completion内部完成
                    if pattern:
                        logger.info(f"[Bayesian] 策略 {pattern.pattern_id} 信念已更新 - "
                                    f"E[p]={pattern.get_success_probability():.2f}, "
                                    f"α={pattern.alpha:.1f}, β={pattern.beta:.1f}")

                        # 添加贝叶斯调试日志
                        logger.debug(f"[Bayesian] 策略 {pattern.pattern_id} 更新: "
                                     f"α={pattern.alpha:.1f}, β={pattern.beta:.1f}, "
                                     f"E[p]={pattern.get_success_probability():.2f}")
                else:
                    logger.error("[AgentLoop] Reflector未初始化，跳过异步任务完成反思")
            except Exception as e:
                logger.error(f"[AgentLoop] 任务完成反思失败: {e}", exc_info=True)

            # [3-7架构] 记录成功，检查是否进化到L3
            # 【Phase4+ 白皮书修复】exploration_engine.record_success() 不存在，已移除
            # 新架构路径：ExperienceRecorder（已激活）
            try:
                from core.evolution.task_classifier import TaskClassifier
                from core.experience.experience_recorder import ExperienceRecorder, TaskRecord

                classifier = TaskClassifier()
                classification = classifier.classify(user_instruction)
                tools_used = [h.get("tool") for h in execution_history if h.get("tool")]

                recorder = ExperienceRecorder(
                    reflector=reflector,
                    world_model=get_world_model() if get_world_model is not None else None,
                    memory_service=memory_service,
                    classifier=classifier,
                )

                record = TaskRecord(
                    task_id=effective_task_id or session_id or str(uuid.uuid4()),
                    user_id=actual_user_id,
                    instruction=user_instruction,
                    classification=classification,
                    tools_used=tools_used,
                    execution_time=0.0,  # TODO: 补充精确任务计时
                    success=True,
                    final_answer=cleaned,
                    reflection_notes=None,
                )

                logger.info(f"[Diag] Memory save: save_execution_record triggered, trace_id={trace_id}")

                # NOTE: save_execution_record 抛后台执行（fire-and-forget），ChromaDB 已真异步化
                async def _bg_record_experience(
                    recorder=recorder,
                    record=record,
                ):
                    try:
                        await recorder.record(record, execution_history=execution_history)
                    except Exception:
                        logger.exception(
                            "[MemoryService] ExperienceRecorder.record() 后台任务失败——"
                            "save_execution_record 执行失败"
                        )

                _task_exp = safe_create_task(_bg_record_experience(), name="record_experience")
                _task_exp.add_done_callback(
                    lambda t: logger.error(f"[AgentLoop] 经验记录任务异常: {t.exception()}") if t.exception() else None
                )
                logger.info(f"[AgentLoop] ExperienceRecorder 已调度至后台: task={effective_task_id}")
            except Exception as e:
                logger.error(f"[AgentLoop] 经验记录调度失败: {e}", exc_info=True)

            # 【修复队7】任务成功完成后，自动触发记忆进化（已抽取到 auto_evolve_trigger）
            if len(execution_history) > 3:
                try:
                    from core.memory.memory_compression import MemoryCompressor
                    _ = MemoryCompressor()  # 保持原有副作用：实例化即触发检查
                    from core.evolution.auto_evolve_trigger import submit_auto_evolve
                    submit_auto_evolve(
                        execution_history=execution_history,
                        user_instruction=user_instruction,
                        session_id=session_id,
                        executor=_agent_loop_executor,
                        logger=logger,
                    )
                except Exception as e:
                    logger.debug(f"[AgentLoop] 自动记忆进化检查失败: {e}")

            # [Planner] 任务4：在任务结束时清理计划  # 清理计划
            try:  # 异常处理
                if hasattr(working_memory, 'ai_plan_id'):  # 有计划ID
                    planner = get_planner()  # 获取规划器
                    planner.clear_plan(working_memory.ai_plan_id)  # 清理
                    logger.info(f"[Planner] 清理计划: {working_memory.ai_plan_id}")  # 记录日志
            except Exception as e:  # 捕获异常
                logger.debug(f"[Planner] 清理计划失败: {e}")  # 记录调试日志

            # 【Phase X】after_loop Hook：最终断点保存和 SmartContext 关键决策断点均已迁移到 ToolHook

            # 【2026-03-10 关键修复】强制检查AI输出，禁止静默返回空内容
            if not answer or not answer.strip():
                error_msg = f"[AgentLoop] AI生成空回复，task_id={task.id}, session={session_id}"
                logger.error(error_msg)
                raise RuntimeError(error_msg)

            # ═══════════════════════════════════════════════════════════════
            # 【Phase3-Week6-MemoryComponents】异步版本：发送记忆元数据到前端
            # ═══════════════════════════════════════════════════════════════
            try:
                from core.agent.loop_utils import _prepare_response_with_memory_metadata
                memory_response = _prepare_response_with_memory_metadata(
                    response_text=answer,
                    working_memory=working_memory,
                    message_id=None
                )
                sync.emit_event("ai_response_with_memory", session_id, {
                    "response": memory_response,
                    "session_id": session_id,
                    "task_completed": True
                })
                logger.info(f"[AgentLoop-Async] 记忆元数据事件已发送: session={session_id}, "
                           f"memory_count={memory_response.get('memory_count', 0)}")
            except Exception as e:
                logger.error(f"[AgentLoop-Async] 发送记忆元数据事件失败: {e}", exc_info=True)

            sync.emit_event("completed", session_id, {"success": True, "answer": answer})  # 发送完成事件
            state_persistence.delete(task.id)  # 删除状态

            # 【P1断裂点#3修复】任务完成后检查是否需要进化（已抽取到 loop_utils）
            from core.agent.loop_utils import trigger_tool_evolution
            await trigger_tool_evolution(task_history, evolution_manager, logger)

            # ═════════════════════════════════════════════════════════════════
            # 【功能恢复 P0】任务完成时触发记忆晋升评估（异步版本）
            # ═════════════════════════════════════════════════════════════════
            if feature_recovery and feature_recovery.should_run_promotion(loop_state.round_count):
                try:
                    promo_report = await feature_recovery.run_memory_promotion(actual_user_id)
                    if promo_report and promo_report.get("total_promoted", 0) > 0:
                        logger.info(f"[记忆晋升-Async] 任务完成触发: L2→L3={promo_report.get('l2_to_l3', 0)}, L3→L4={promo_report.get('l3_to_l4', 0)}")
                except Exception as e:
                    logger.debug(f"[记忆晋升-Async] 任务完成触发失败: {e}")

            # ═════════════════════════════════════════════════════════════════
            # 【功能恢复 P1】高分任务进行多维度反思（异步版本）
            # ═════════════════════════════════════════════════════════════════
            if feature_recovery:
                try:
                    task_score = 85 if loop_state.consecutive_errors == 0 else 60
                    if feature_recovery.should_run_multi_dimension(task_score, True):
                        reflection = await feature_recovery.run_multi_dimension_reflection(
                            task_description=user_instruction,
                            execution_history=[h.get("action", "") for h in execution_history[-10:]],
                            user_id=actual_user_id
                        )
                except Exception as e:
                    logger.debug(f"[多维度反思-Async] 跳过: {e}")

            # 【Phase 7】异步版 Session 归档
            if session:
                try:
                    await session_integration.finalize_session(
                        session=session,
                        user_instruction=user_instruction_for_session,
                        final_response=answer,
                    )
                except Exception as e:
                    logger.error(f"[SessionIntegration-Async] 归档失败: {e}", exc_info=True)

            # 【Reflector】任务完成后总结性反思
            if reflector is not None:
                try:
                    from core.reflector.reflector import reflect_after_success
                    await reflect_after_success(
                        task=user_instruction,
                        trajectory=execution_history,
                        final_result=answer
                    )
                except Exception as e:
                    logger.error(f"[AgentLoop] 任务完成反思失败: {e}", exc_info=True)

            _sensor_len = len(last_vision_description) if last_vision_description else 0
            _ctx_len = len(full_system_prompt) if full_system_prompt else 0
            _tool_count = len([h for h in execution_history if h.get("tool")])
            logger.info(f"[Diag] R{loop_state.round_count} done: sensors={_sensor_len} ctx={_ctx_len} tools={_tool_count} mem=True")

            # 【ExperienceBus】发布任务完成 outcome
            try:
                await report_task_completed(
                    actual_user_id=actual_user_id,
                    session_id=session_id,
                    task=task,
                    user_instruction=user_instruction,
                    active_goal=None,
                    execution_history=execution_history,
                    loop_start_time=loop_start_time,
                    final_answer=answer,
                )
            except Exception as e:
                logger.debug(f"[AgentLoop] 任务完成 outcome 发布失败: {e}")

            return answer, working_memory  # 返回

        elif parsed.intent_type == IntentType.PLAN:  # 计划意图
            res = intent_handler.handle_plan(parsed, working_memory, session_id, task.id, task.priority)  # 处理
            reply = res["answer"]  # 获取回复

            # 【2026-03-10 关键修复】强制检查AI输出，禁止静默返回空内容
            if not reply or not reply.strip():
                error_msg = f"[AgentLoop] AI生成空回复（PLAN），task_id={task.id}, session={session_id}"
                logger.error(error_msg)
                raise RuntimeError(error_msg)

            # 【Phase 6】PLAN 语音播报已迁移到 VoiceHook.on_plan（异步版）
            await agent_loop_hooks.execute_async('on_plan', hook_ctx, reply=reply)

            # ═══════════════════════════════════════════════════════════════
            # 【Phase3-Week6-MemoryComponents】异步版本：PLAN类型发送记忆元数据
            # ═══════════════════════════════════════════════════════════════
            try:
                from core.agent.loop_utils import _prepare_response_with_memory_metadata
                memory_response = _prepare_response_with_memory_metadata(
                    response_text=reply,
                    working_memory=working_memory,
                    message_id=None
                )
                sync.emit_event("ai_response_with_memory", session_id, {
                    "response": memory_response,
                    "session_id": session_id,
                    "task_completed": True,
                    "intent_type": "PLAN"
                })
                logger.info(f"[AgentLoop-Async] PLAN-记忆元数据事件已发送: session={session_id}")
            except Exception as e:
                logger.error(f"[AgentLoop-Async] PLAN-发送记忆元数据事件失败: {e}", exc_info=True)

            sync.emit_event("completed", session_id, {"success": True, "answer": reply})  # 发送事件
            state_persistence.delete(task.id)  # 删除状态

            # 【P1断裂点#3修复】任务完成后检查是否需要进化（已抽取到 loop_utils）
            from core.agent.loop_utils import trigger_tool_evolution
            await trigger_tool_evolution(task_history, evolution_manager, logger)

            return reply, working_memory  # 返回

        elif parsed.intent_type == IntentType.QUERY_TOOL_LIST:  # 查询工具列表（L1->L2）
            old_stage = working_memory.query_stage  # 记录旧层级

            # [语音播报 - 阶段四优化] 层级切换播报（进入L2）  # 层级切换播报
            await agent_loop_hooks.execute_async(
                'on_layer_switch', hook_ctx,
                announce_type=VoiceAnnounceStrategy.LAYER_SWITCH,
                layer="layer2",
                user_id=session_id if session_id != "console" else "default"
            )  # 播报结束

            res = intent_handler.handle_query_tool_list(parsed, working_memory)  # 处理
            # 注意：intent_handler直接修改working_memory对象，无需重新赋值  # 说明
            # 检查切换次数限制  # 限制检查
            if not working_memory.record_layer_switch(old_stage, "layer2", "QUERY_TOOL_LIST"):  # 超过限制
                reply = f"任务执行异常：层级切换次数超过限制({working_memory.MAX_LAYER_SWITCHES})，请简化指令或检查AI响应"  # 错误消息
                logger.error(f"[AgentLoop] {reply}")  # 记录错误
                await agent_loop_hooks.execute_async('on_error', hook_ctx, error_msg=reply)  # 播报错误
                sync.emit_event("completed", session_id, {"success": False, "answer": reply})  # 发送事件
                state_persistence.delete(task.id)  # 删除状态
                return reply, working_memory  # 返回错误
            continue  # 继续循环

        elif parsed.intent_type == IntentType.QUERY_TOOL_DETAIL:  # 查询工具详情（L2->L3）
            old_stage = working_memory.query_stage  # 记录旧层级

            # [语音播报 - 阶段四优化] 层级切换播报（进入L3）  # 层级切换播报
            await agent_loop_hooks.execute_async(
                'on_layer_switch', hook_ctx,
                announce_type=VoiceAnnounceStrategy.LAYER_SWITCH,
                layer="layer3",
                user_id=session_id if session_id != "console" else "default"
            )  # 播报结束

            res = intent_handler.handle_query_tool_detail(parsed, working_memory)  # 处理
            if not working_memory.record_layer_switch(old_stage, "layer3", "QUERY_TOOL_DETAIL"):  # 超过限制
                reply = f"任务执行异常：层级切换次数超过限制({working_memory.MAX_LAYER_SWITCHES})，请简化指令或检查AI响应"  # 错误消息
                logger.error(f"[AgentLoop] {reply}")  # 记录错误
                await agent_loop_hooks.execute_async('on_error', hook_ctx, error_msg=reply)  # 播报错误
                sync.emit_event("completed", session_id, {"success": False, "answer": reply})  # 发送事件
                state_persistence.delete(task.id)  # 删除状态
                return reply, working_memory  # 返回错误
            continue  # 继续循环

        elif parsed.intent_type == IntentType.BACK_TO_PREV:  # 返回上一级
            old_stage = working_memory.query_stage  # 记录旧层级

            # [语音播报 - 阶段四优化] 返回层级播报  # 返回播报
            target_layer = working_memory.query_stage  # 获取目标层级
            await agent_loop_hooks.execute_async(
                'on_layer_switch', hook_ctx,
                announce_type=VoiceAnnounceStrategy.LAYER_SWITCH,
                layer=target_layer,
                user_id=session_id if session_id != "console" else "default"
            )  # 播报结束

            res = intent_handler.handle_back(parsed, working_memory)  # 处理
            # 检查返回结果是否应该继续循环  # 继续检查
            if not res.get("should_continue", True):  # 不继续
                logger.info("[AgentLoop] handle_back返回should_continue=False，结束循环")  # 记录日志
                break  # 跳出循环
            if not working_memory.record_layer_switch(old_stage, working_memory.query_stage, "BACK_TO_PREV"):  # 超过限制
                reply = f"任务执行异常：层级切换次数超过限制({working_memory.MAX_LAYER_SWITCHES})，请简化指令或检查AI响应"  # 错误消息
                logger.error(f"[AgentLoop] {reply}")  # 记录错误
                await agent_loop_hooks.execute_async('on_error', hook_ctx, error_msg=reply)  # 播报错误
                sync.emit_event("completed", session_id, {"success": False, "answer": reply})  # 发送事件
                state_persistence.delete(task.id)  # 删除状态
                return reply, working_memory  # 返回错误
            continue  # 继续循环

        # ==================== 【AI计算机语言 - 统一通过FunctionTrigger处理】 ====================  # AI计算机语言
        # 共20个计算机语言标记，分5个层次：  # 层次说明
        # 用户交互层: CALL_USER, ASK_USER, WAIT_CONFIRM, NOTIFY_USER  # 第1层
        # 工具查询层: FIND_TOOL, QUERY_TOOL_LIST, QUERY_TOOL_DETAIL  # 第2层
        # 记忆认知层: QUERY_MEMORY, RECORD_MEMORY, DELETE_MEMORY  # 第3层
        # 学习进化层: ENTER_LEARNING, EXECUTE_PLAN, REFLECT, EVOLVE, EVOLVE_MEMORY  # 第4层
        # 预测感知层: WORLD_MODEL_PREDICT, VISION_ANALYZE, BEHAVIOR_ANALYZE  # 第5层
        # 系统控制层: PAUSE_EXECUTION, RESUME_EXECUTION, TERMINATE_TASK, SUBMIT_UNDERSTANDING  # 第6层
        #
        # 【精准抓取增强】同步处理precision_parsed识别的标记  # 精准抓取增强
        elif parsed.intent_type in [  # AI计算机语言意图列表
            # 用户交互层  # Layer 1
            IntentType.CALL_USER, IntentType.ASK_USER, IntentType.WAIT_CONFIRM, IntentType.NOTIFY_USER,
            # 工具查询层  # Layer 2
            IntentType.FIND_TOOL, IntentType.QUERY_TOOL_LIST, IntentType.QUERY_TOOL_DETAIL,
            # 记忆认知层  # Layer 3
            IntentType.QUERY_MEMORY, IntentType.RECORD_MEMORY, IntentType.DELETE_MEMORY,
            # 学习进化层  # Layer 4
            IntentType.ENTER_LEARNING, IntentType.EXECUTE_PLAN, IntentType.REFLECT, IntentType.EVOLVE, IntentType.EVOLVE_MEMORY,
            # 预测感知层  # Layer 5
            IntentType.WORLD_MODEL_PREDICT, IntentType.VISION_ANALYZE, IntentType.BEHAVIOR_ANALYZE,
            # 系统控制层  # Layer 6
            IntentType.PAUSE_EXECUTION, IntentType.RESUME_EXECUTION, IntentType.TERMINATE_TASK,
            IntentType.SUBMIT_UNDERSTANDING,  # 新增：提交理解摘要
        ]:  # 意图列表结束
            # 【精准抓取增强】根据precision_parsed的标记类型优化播报  # 标记优化
            if precision_marker == AICodeMarker.CALL_USER:  # 呼叫用户
                reason = precision_parsed.parsed_data.get("reason", "")  # 获取原因
                if reason and config.get("voice.announce.process.user_assistance", True):  # 播报
                    # 【Phase 6】用户协助语音播报已迁移到 VoiceHook.on_user_assist（异步版）
                    await agent_loop_hooks.execute_async('on_user_assist', hook_ctx, reason=reason)
            elif precision_marker == AICodeMarker.EVOLVE_REFLECT:  # 进化反思
                announcer.announce_evolution("reflect")  # 播报进化
            elif precision_marker == AICodeMarker.WORLD_MODEL:  # 世界模型
                announcer.announce_query("world_model")  # 播报查询
            elif precision_marker == AICodeMarker.VISION_ANALYSIS:  # 视觉分析
                announcer.announce_query("vision")  # 播报查询
            elif precision_marker == AICodeMarker.MEMORY_UPDATE:  # 记忆更新
                announcer.announce_evolution("evolve")  # 播报进化
            # 使用FunctionTrigger统一处理  # 触发器处理
            trigger = get_function_trigger()  # 获取触发器

            # 映射意图类型到触发器类型（20个标记完整映射）  # 类型映射
            trigger_type_map = {  # 映射字典
                # 用户交互层  # Layer 1
                IntentType.CALL_USER: TriggerType.CALL_USER,
                IntentType.ASK_USER: TriggerType.ASK_USER,
                IntentType.WAIT_CONFIRM: TriggerType.WAIT_CONFIRM,
                IntentType.NOTIFY_USER: TriggerType.NOTIFY_USER,
                # 工具查询层  # Layer 2
                IntentType.FIND_TOOL: TriggerType.FIND_TOOL,
                IntentType.QUERY_TOOL_LIST: TriggerType.QUERY_TOOL_LIST,
                IntentType.QUERY_TOOL_DETAIL: TriggerType.QUERY_TOOL_DETAIL,
                # 记忆认知层  # Layer 3
                IntentType.QUERY_MEMORY: TriggerType.QUERY_MEMORY,
                IntentType.RECORD_MEMORY: TriggerType.RECORD_MEMORY,
                IntentType.DELETE_MEMORY: TriggerType.DELETE_MEMORY,
                # 学习进化层  # Layer 4
                IntentType.ENTER_LEARNING: TriggerType.ENTER_LEARNING,
                IntentType.EXECUTE_PLAN: TriggerType.EXECUTE_PLAN,
                IntentType.REFLECT: TriggerType.REFLECT,
                IntentType.EVOLVE: TriggerType.EVOLVE,
                # 预测感知层  # Layer 5
                IntentType.WORLD_MODEL_PREDICT: TriggerType.WORLD_MODEL_PREDICT,
                IntentType.VISION_ANALYZE: TriggerType.VISION_ANALYZE,
                IntentType.BEHAVIOR_ANALYZE: TriggerType.BEHAVIOR_ANALYZE,
                # 系统控制层  # Layer 6
                IntentType.PAUSE_EXECUTION: TriggerType.PAUSE_EXECUTION,
                IntentType.RESUME_EXECUTION: TriggerType.RESUME_EXECUTION,
                IntentType.TERMINATE_TASK: TriggerType.TERMINATE_TASK,
                IntentType.SUBMIT_UNDERSTANDING: TriggerType.SUBMIT_UNDERSTANDING,
            }  # 映射字典结束

            # 【修复队7】处理 EVOLVE_MEMORY 意图（不在FunctionTrigger中）  # 特殊处理
            if parsed.intent_type == IntentType.EVOLVE_MEMORY:  # 记忆进化
                # 触发记忆压缩  # 压缩
                try:  # 异常处理
                    from core.memory.memory_compression import MemoryCompressor  # 导入
                    compressor = MemoryCompressor()  # 创建实例

                    # 压缩短期记忆到中期  # L1->L2
                    compressed = 0  # 计数
                    try:  # 异常处理
                        # 获取当前用户的短期记忆并压缩  # 获取并压缩
                        # 【Phase 5】使用异步记忆层读取短期记忆
                        # VERIFIED-ASYNC: query_memories 底层使用 asyncpg pool.fetch()，真异步 I/O，可原地 await
                        short_term_memories = await memory_service.query_memories(
                            user_id=actual_user_id,
                            layer="short",
                            limit=50,
                            filter_dict={"session_id": session_id},
                        )
                        if short_term_memories:  # 有记忆
                            result = compressor.compress_user_layer(session_id, "L2", short_term_memories)  # 压缩
                            compressed = result.compressed_count  # 获取数量
                            logger.info(f"[AgentLoop] 记忆压缩完成: {compressed} 条")  # 记录日志
                    except Exception as e:  # 捕获异常
                        logger.warning(f"[AgentLoop] 短期记忆压缩失败: {e}")  # 记录警告

                    # 触发进化  # 进化
                    evolved = 0  # 计数
                    try:  # 异常处理
                        # 提交经验到进化服务  # 提交
                        if execution_history:  # 有执行历史
                            steps = [h.get("tool") for h in execution_history if h.get("tool")]
                            all_success = all(h.get("success", False) for h in execution_history)
                            result = evolution_manager.learn_from_execution(
                                task_type="memory_optimization",
                                task_description=user_instruction,
                                approach=str(steps),
                                outcome="success" if all_success else "partial",
                                effectiveness=0.9 if all_success else 0.6,
                                context={"session_id": session_id}
                            )
                            if result:
                                evolved = 1  # 标记
                                logger.info("[AgentLoop] 经验已提交到进化服务")  # 记录日志
                    except Exception as e:  # 捕获异常
                        logger.warning(f"[AgentLoop] 进化服务调用失败: {e}")  # 记录警告

                    # 添加结果到工作记忆  # 添加结果
                    working_memory.append({  # 添加
                        "role": "system",  # 系统角色
                        "content": f"【记忆进化完成】整理了{compressed}条记忆，进化出{evolved}条经验。"  # 内容
                    })  # 添加结束

                    logger.info(f"[AgentLoop] 记忆进化完成: 压缩{compressed}, 进化{evolved}")  # 记录日志

                except Exception as e:  # 捕获异常
                    logger.error(f"[AgentLoop] 记忆进化失败: {e}")  # 记录错误
                    working_memory.append({  # 添加错误信息
                        "role": "system",  # 系统角色
                        "content": "【记忆进化】整理记忆时遇到问题，继续任务。"  # 内容
                    })  # 添加结束

                continue  # 继续循环

            trigger_type = trigger_type_map.get(parsed.intent_type)  # 获取触发器类型
            if trigger_type:  # 有映射
                context = {  # 上下文字典
                    "voice_instance": voice_instance,  # 语音实例
                    "session_id": session_id,  # 会话ID
                    "working_memory": working_memory,  # 工作记忆
                    "user_instruction": user_instruction,  # 用户指令
                    "execution_history": execution_history,  # 执行历史
                    "params": parsed.params  # 参数
                }  # 字典结束
                result = None
                try:
                    result = await trigger.trigger(trigger_type, context)
                except Exception as e:
                    logger.warning(f"[AgentLoop] trigger.trigger 失败: {e}")

                # =============================================================================  # 分隔线
                # 【长任务模式】同步更新长任务状态机  # 长任务状态同步
                # =============================================================================  # 分隔线
                if parsed.intent_type == IntentType.PAUSE_EXECUTION:  # 暂停执行
                    # AI触发了暂停，初始化长任务状态机  # 初始化长任务
                    is_long_task = True  # 标记
                    reason = parsed.params.get("reason", "AI请求暂停")  # 获取原因
                    try:
                        await pausable_task_sm.pause_async(reason=reason, trigger="ai")
                    except Exception as e:
                        logger.warning(f"[AgentLoop] pausable_task_sm.pause 失败: {e}")

                    # 标记任务为长任务  # 标记
                    if hasattr(task, 'metadata'):  # 有元数据
                        task.metadata["is_long_task"] = True  # 设置标志

                    # 保存任务ID到working_memory  # 保存ID
                    working_memory.current_task_id = task.id  # 当前任务ID
                    working_memory.pause_task_id = task.id  # 暂停任务ID
                    working_memory.is_long_task = True  # 长任务标志

                    logger.info(f"[AgentLoop] [PausableTask] 任务 {task.id} 已进入可暂停任务暂停模式")  # 记录日志

                elif parsed.intent_type == IntentType.SUBMIT_UNDERSTANDING:  # 提交理解
                    # AI提交了理解摘要  # 处理理解
                    understanding = parsed.params.get("understanding", "")  # 获取理解
                    if understanding:  # 有内容
                        try:
                            await pausable_task_sm.confirm_ai_understanding_async(understanding)
                        except Exception as e:
                            logger.warning(f"[AgentLoop] pausable_task_sm.confirm_ai_understanding 失败: {e}")
                        logger.info("[AgentLoop] [LongTask] AI提交理解摘要")  # 记录日志

                        # 添加到working_memory  # 添加
                        working_memory.append({  # 添加
                            "role": "system",  # 系统角色
                            "content": f"【理解摘要已提交】\n{understanding}\n\n请等待用户确认..."  # 内容
                        })  # 添加结束

                elif parsed.intent_type == IntentType.RESUME_EXECUTION:  # 恢复执行
                    # AI尝试恢复任务  # 处理恢复
                    # 只有在用户确认后才能真正恢复  # 确认检查
                    if not pausable_task_sm.can_resume():  # 不能恢复
                        logger.warning("[AgentLoop] [LongTask] AI尝试恢复但用户尚未确认")  # 记录警告
                        working_memory.append({  # 添加警告
                            "role": "system",  # 系统角色
                            "content": "⚠️ 【恢复被拒绝】必须获得用户确认后才能恢复任务。请等待用户说'确认'或'正确'。"  # 内容
                        })  # 添加结束
                        # 阻止继续执行  # 阻止
                        continue  # 跳过

                    # 恢复成功，恢复快照到WorkingMemory  # 恢复快照
                    try:  # 异常处理
                        restored = await snapshot_manager.restore_to_working_memory(task.id, working_memory)  # 恢复
                        if restored:  # 成功
                            logger.info(f"[AgentLoop] [PausableTask] 任务 {task.id} WorkingMemory状态已从快照恢复")  # 记录日志
                    except Exception as e:  # 捕获异常
                        logger.error(f"[AgentLoop] [LongTask] 恢复快照失败: {e}")  # 记录错误

                # 检查是否需要退出循环  # 退出检查
                if not result.should_continue:  # 不继续
                    error_msg = result.message  # 获取错误消息
                    logger.error(f"[AgentLoop] {error_msg}")  # 记录错误
                    await agent_loop_hooks.execute_async('on_error', hook_ctx, error_msg=error_msg)  # 播报错误
                    sync.emit_event("completed", session_id, {"success": False, "answer": error_msg})  # 发送事件
                    state_persistence.delete(task.id)  # 删除状态
                    return error_msg, working_memory  # 返回错误

                # 【行为识别 - 基础版】每次AI计算机语言触发后，分析行为  # 行为识别
                try:  # 异常处理
                    behavior_recognizer = get_behavior_recognizer()  # 获取识别器
                    behavior = await behavior_recognizer.analyze(execution_history, user_instruction
                    )  # 分析
                    logger.debug(f"[AgentLoop] 行为分析: {behavior.behavior_type}, 风险: {behavior.risk_level}")  # 记录日志

                    # 检查异常  # 异常检查
                    anomaly = check_behavior_anomaly(execution_history)  # 检查
                    if anomaly:  # 有异常
                        logger.warning(f"[AgentLoop] 行为异常检测: {anomaly}")  # 记录警告
                        working_memory.append({  # 添加警告
                            "role": "system",  # 系统角色
                            "content": f"【系统提示】{anomaly}"  # 内容
                        })  # 添加结束
                except Exception as e:  # 捕获异常
                    logger.debug(f"[AgentLoop] 行为识别失败（不影响执行）: {e}")  # 记录调试日志

                # 【行为分析 - 深度版】使用AIBehaviorAnalyzer进行深度分析  # 深度分析
                if parsed.intent_type == IntentType.BEHAVIOR_ANALYZE:  # 行为分析
                    try:  # 异常处理
                        behavior_analyzer = get_behavior_analyzer()  # 获取分析器

                        # 执行工具使用深度分析  # 深度分析
                        analysis_result = await behavior_analyzer.analyze_tool_usage(
                            execution_history, detailed=True  # 参数
                        )  # 分析结束

                        # 预测下一步行为  # 预测
                        prediction = behavior_analyzer.predict_next_action(  # 预测
                            working_memory, execution_history  # 参数
                        )  # 预测结束

                        logger.info(f"[AgentLoop] 深度行为分析: {analysis_result.summary}")  # 记录日志
                        logger.info(f"[AgentLoop] 行为预测: {prediction.predicted_action} (置信度: {prediction.confidence})")  # 记录日志

                        # 将分析结果添加到工作记忆  # 添加结果
                        working_memory.append({  # 添加分析结果
                            "role": "system",  # 系统角色
                            "content": f"【深度行为分析】{analysis_result.summary}"  # 内容
                        })  # 添加结束

                        if prediction.predicted_tool:  # 有预测工具
                            working_memory.append({  # 添加预测
                                "role": "system",  # 系统角色
                                "content": f"【行为预测】下一步可能调用: {prediction.predicted_tool} (置信度: {prediction.confidence:.2f})"  # 内容
                            })  # 添加结束

                    except Exception as e:  # 捕获异常
                        logger.debug(f"[AgentLoop] 深度行为分析失败（不影响执行）: {e}")  # 记录调试日志

                continue  # 继续循环

        else:  # 未知意图
            # 未知意图，当作最终答案  # 默认处理
            cleaned = extract_natural_language(response)  # 提取
            # 【Phase 6】未知意图语音播报已迁移到 VoiceHook.on_complete
            await agent_loop_hooks.execute_async('on_complete', hook_ctx, answer=cleaned)
            sync.emit_event("completed", session_id, {"success": True, "answer": response})  # 发送事件
            state_persistence.delete(task.id)  # 删除状态

            # ═══════════════════════════════════════════════════════════════
            # 【Phase3-Week6-MemoryComponents】异步版本：未知意图发送记忆元数据
            # ═══════════════════════════════════════════════════════════════
            try:
                from core.agent.loop_utils import _prepare_response_with_memory_metadata
                memory_response = _prepare_response_with_memory_metadata(
                    response_text=response,
                    working_memory=working_memory,
                    message_id=None
                )
                sync.emit_event("ai_response_with_memory", session_id, {
                    "response": memory_response,
                    "session_id": session_id,
                    "task_completed": True,
                    "intent_type": "UNKNOWN"
                })
                logger.info(f"[AgentLoop-Async] UNKNOWN-记忆元数据事件已发送: session={session_id}")
            except Exception as e:
                logger.error(f"[AgentLoop-Async] UNKNOWN-发送记忆元数据事件失败: {e}", exc_info=True)

            # 【2026-03-10 关键修复】强制检查AI输出，禁止静默返回空内容
            if not response or not response.strip():
                error_msg = f"[AgentLoop] AI生成空回复（未知意图），task_id={task.id}, session={session_id}"
                logger.error(error_msg)
                raise RuntimeError(error_msg)

            # 【Phase 7】异步版 Session 归档
            if session:
                try:
                    await session_integration.finalize_session(
                        session=session,
                        user_instruction=user_instruction_for_session,
                        final_response=response,
                    )
                except Exception as e:
                    logger.error(f"[SessionIntegration-Async] 归档失败: {e}", exc_info=True)

            # 【Phase 1】after_loop Hook（异步版本正常结束路径）
            hook_ctx = await agent_loop_hooks.execute_async('after_loop', hook_ctx)
            return response, working_memory  # 返回

    # 【P1】长任务中断恢复：循环因插话而 break，直接返回 [PAUSED]
    if final_answer == "[PAUSED]":
        logger.info(f"[AgentLoop] 任务 {task.id if task else None} 以 [PAUSED] 状态退出循环")
        return final_answer, working_memory

    # 【安全限制】达到软性安全上限后的处理
    # 循环因达到MAX_SAFETY_ROUNDS而结束，返回友好提示
    safety_message = (
        f"⏹️ 任务执行已达到最大轮次限制（{MAX_SAFETY_ROUNDS}轮）。\n"
        f"当前任务可能较为复杂或需要更长时间完成。\n"
        f"💡 建议：您可以重新下达更具体的指令继续任务，或分步骤完成。"
    )

    logger.warning(f"[AgentLoop] [Safety] 达到软性安全上限({MAX_SAFETY_ROUNDS}轮)，循环强制结束")

    # ═════════════════════════════════════════════════════════════════════════════
    # 【断点续传第二阶段】任务达到安全上限时暂停并保存断点（异步版本）
    # ═════════════════════════════════════════════════════════════════════════════
    if task_state:
        # 【关键修复】使用pause_task_with_sync确保phase_anchors同步
        pause_result = await pause_task_with_sync(
            task_state=task_state,
            working_memory=working_memory,
            reason=f"达到软性安全上限({MAX_SAFETY_ROUNDS}轮)",
            session_id=session_id
        )
        if pause_result.get("success"):
            logger.info(f"[Checkpoint] 任务达到安全上限，已暂停并保存断点: {task_state.task_id}")
        else:
            logger.warning(f"[Checkpoint] 暂停任务失败: {pause_result.get('error')}")

    # 【Phase 6】安全限制语音播报标记，由下方统一的 after_loop Hook 驱动（异步版）
    if config.get("voice.announce.process.safety_limit", True):
        hook_ctx.extra["max_rounds_reached"] = True

    # 发送事件到前端
    sync.emit_event("completed", session_id, {
        "success": False,
        "answer": safety_message,
        "reason": "safety_limit_reached",
        "max_rounds": MAX_SAFETY_ROUNDS
    })

    # 【2026-03-10 关键修复】强制检查AI输出，禁止静默返回空内容
    if not safety_message or not safety_message.strip():
        error_msg = f"[AgentLoop] AI生成空回复（安全限制），task_id={task.id}, session={session_id}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    # ═══════════════════════════════════════════════════════════════
    # 【演示学习系统集成】异步版本函数返回前清理资源
    # ═══════════════════════════════════════════════════════════════
    if PROCEDURE_LEARNING_INTEGRATION_AVAILABLE:
        try:
            proc_learning_integration_async = get_procedure_learning_integration()
            proc_learning_integration_async.end_task(session_id)
            logger.info(f"[AgentLoop-Async] [ProcedureLearning] 任务资源已清理: {session_id}")
        except Exception as e:
            logger.warning(f"[AgentLoop-Async] [ProcedureLearning] 清理任务资源失败: {e}")

    # 【Phase 7】异步版 Session 归档（安全限制路径）
    if session:
        try:
            await session_integration.finalize_session(
                session=session,
                user_instruction=user_instruction_for_session,
                final_response=safety_message,
            )
        except Exception as e:
            logger.error(f"[SessionIntegration-Async] 归档失败: {e}", exc_info=True)

    # 【Phase 1】after_loop Hook（异步版本安全限制路径）
    hook_ctx = await agent_loop_hooks.execute_async('after_loop', hook_ctx)
    return safety_message, working_memory  # 返回安全限制提示


async def run_agent_loop_async(task, max_rounds: int = None, chat_history: list = None,
                               chat_count: int = 0, session_id: str = "console",
                               db_session_id: str | None = None,
                               voice_instance=None, mode: str = "daily",
                               user_id: str = None,
                               task_id: str | None = None,
                               resume_from_checkpoint: bool = False,
                               cancel_event: asyncio.Event = None,
                               timeout_deadline: float = None) -> tuple[str | None, WorkingMemory]:
    """
    ReAct主循环 - 异步版本（用户级并发控制）

    与run_agent_loop功能完全相同，但使用异步AI调用，不阻塞事件循环。
    包装函数：获取用户级锁，确保一个用户同时只能有一个AgentLoop运行。

    Args:
        task: 任务对象
        max_rounds: 最大循环轮数（已废弃，保留参数兼容性）
        chat_history: 聊天历史
        chat_count: 当前对话计数
        session_id: 会话ID
        voice_instance: 语音实例
        mode: 工作模式（daily/focus/trading）
        user_id: 用户ID（用于用户级并发控制，不传则使用session_id）
        task_id: 任务ID（用于断点续传）
        resume_from_checkpoint: 是否从断点恢复

    Returns:
        Tuple[Optional[str], WorkingMemory]: (AI回复, 工作记忆)
    """
    # 【用户级并发控制】获取用户ID并申请循环锁
    actual_user_id = user_id if user_id else (session_id if session_id != "console" else "default")
    stop_event = None
    dialogue_manager_ref = None
    loop_error = None  # 【修复】初始化loop_error，避免正常路径下finally块NameError

    try:
        from core.dialog.dialogue_manager import dialogue_manager
        dialogue_manager_ref = dialogue_manager
        stop_event = await dialogue_manager._acquire_user_loop_lock_async(actual_user_id, reuse_existing=True)
        logger.info(f"[AgentLoop] 用户 {actual_user_id} 的异步AgentLoop已启动（并发控制）")
    except Exception as e:
        diagnostic_except_handler(e, context="[AgentLoop] 获取用户循环锁失败", logger_instance=logger)
        stop_event = threading.Event()  # 降级处理：创建本地事件

    _main_task = asyncio.current_task()
    if task and task.id:
        interrupt_handler.register_task(task.id, _main_task)

    try:
        # 调用实际实现
        return await _run_agent_loop_async_impl(
            task=task,
            max_rounds=max_rounds,
            chat_history=chat_history,
            chat_count=chat_count,
            session_id=session_id,
            db_session_id=db_session_id,
            voice_instance=voice_instance,
            mode=mode,
            user_id=user_id,
            stop_event=stop_event,
            task_id=task_id,
            resume_from_checkpoint=resume_from_checkpoint,
            cancel_event=cancel_event,
            timeout_deadline=timeout_deadline
        )
    except Exception as e:
        # 【零静默失败】主循环任何未捕获异常必须记录、通知前端，并返回错误响应
        diagnostic_except_handler(e, context="[AgentLoop] 主循环异常", logger_instance=logger)
        loop_error = str(e)
        logger.error(f"[SILENT_FAILURE_BLOCKED] AgentLoop主循环异常: {loop_error}", exc_info=True)

        # 向前端发送明确的错误事件，避免用户看到"正在思考..."卡死
        error_message = f"抱歉，处理过程中出现错误：{loop_error[:200]}"
        try:
            from core.sync.realtime_sync import get_realtime_sync_manager
            sync_mgr = get_realtime_sync_manager()
            if sync_mgr:
                await sync_mgr.emit_event_async("error", session_id, {
                    "message": error_message,
                    "error_type": type(e).__name__,
                    "task_id": task.id if task else None,
                })
                logger.info(f"[AgentLoop] 已向前端发送错误事件: session={session_id}")
        except Exception as sync_err:
            logger.error(f"[AgentLoop] 向前端发送错误事件失败: {sync_err}")

        try:
            hook_ctx = HookContext(session_id=session_id, user_id=user_id)
            await agent_loop_hooks.execute_async('on_error', hook_ctx, error_msg=loop_error)
        except Exception as hook_err:
            logger.error(f"[AgentLoop] on_error Hook 执行失败: {hook_err}")

        # 【ExperienceBus】发布任务失败 outcome
        try:
            await report_task_failed(
                actual_user_id=actual_user_id,
                session_id=session_id,
                task=task,
                user_instruction="",
                loop_error=loop_error,
            )
        except Exception as report_err:
            logger.debug(f"[AgentLoop] 任务失败 outcome 发布失败: {report_err}")

        # 返回错误响应而不是抛出，确保外层调用者能正常结束本次请求
        # 返回最小 WorkingMemory 实例而不是 None，避免调用方解包失败/AttributeError
        fallback_wm = WorkingMemory(user_id=actual_user_id)
        fallback_wm.append({
            "role": "system",
            "content": error_message,
            "_category": "agent_loop_error",
        })
        return error_message, fallback_wm
    finally:
        # 【新增】异常退出时保存断点，防止进度丢失
        if task and task.id:
            try:
                from core.agent.checkpoint_manager import checkpoint_manager
                await checkpoint_manager.save_checkpoint(task.id, "异常退出自动保存")
                logger.info(f"[Checkpoint] 异常退出时自动保存断点: {task.id}")
            except Exception as e:
                logger.error(f"[Checkpoint] 异常退出时保存断点失败: {e}")

        # 【Phase 7.1】注销任务关联的 asyncio.Task
        if task and task.id:
            try:
                interrupt_handler.unregister_task(task.id, _main_task)
            except Exception as e:
                logger.debug(f"[AgentLoop] 注销中断处理器任务失败: {e}")

        # 【跨循环DuplicateGuard】保存本次工具缓存，供后续循环复用
        try:
            _ls = _last_loop_state.get(actual_user_id)
            if _ls and _ls.processed_tool_calls:
                _user_tool_result_cache[actual_user_id] = dict(_ls.processed_tool_calls)
                logger.debug(
                    f"[AgentLoop-DuplicateGuard] 已保存 {len(_ls.processed_tool_calls)} 条工具缓存"
                )
        except Exception as e:
            logger.debug(f"[AgentLoop-DuplicateGuard] 保存工具缓存失败: {e}")
        finally:
            _last_loop_state.pop(actual_user_id, None)

        # 【用户级并发控制】确保锁被释放
        if stop_event and dialogue_manager_ref:
            try:
                await dialogue_manager_ref._release_user_loop_lock_async(actual_user_id, stop_event)
                logger.info(f"[AgentLoop] 用户 {actual_user_id} 的异步AgentLoop已结束（并发控制）")
            except Exception as e:
                logger.debug(f"[AgentLoop] 释放用户循环锁失败: {e}")

        # 【ExperienceBus】任务完成/失败 outcome 已在正常/异常路径直接发布，
        # 此处不再通过 event_bus 转发，避免与 AgentLoopExperienceAdapter 重复计数。


# 保持向后兼容：统一为原生 async 入口
async def run_agent_loop_compat(*args, **kwargs):
    """
    ReAct主循环（向后兼容，已统一为异步版本）

    [Phase 1] 已统一为原生 async 入口，删除 asyncio.run 桥接。
    调用方必须 await 本函数。
    注意：在新代码中推荐使用 run_agent_loop 或 run_agent_loop_async。
    """
    return await run_agent_loop(*args, **kwargs)


# =============================================================================
# 【断点续传第二阶段】辅助函数
# =============================================================================
# 【P1修复】AgentLoop 类 - 主入口包装器
# =============================================================================

class AgentLoop:
    """
    AgentLoop 主类 - ReAct执行引擎的入口包装器

    提供标准化的接口来运行Agent主循环，支持：
    - 同步执行：run()
    - 异步执行：run_async()
    - 任务完成分析：analyze_completion()

    使用示例:
        agent = AgentLoop()
        result, memory = agent.run(task, session_id="user_123")
    """

    # 类级交易报告缓存：user_id -> latest_report
    _commander_reports: dict[str, dict] = {}
    _event_bus_subscribed = False
    _consciousness_started = False  # 【P0修复】确保意识核心只启动一次

    def __init__(self):
        """初始化AgentLoop实例"""
        self.analyzer = get_task_completion_analyzer()
        self._execution_count = 0
        # 订阅 commander.report 事件（全局只需一次）
        if not AgentLoop._event_bus_subscribed and _main_event_bus is not None:
            try:
                _main_event_bus.subscribe("commander.report", AgentLoop._on_commander_report)
                AgentLoop._event_bus_subscribed = True
                logger.info("[AgentLoop] 已订阅 commander.report 事件")
            except Exception as e:
                logger.debug(f"[AgentLoop] 订阅 commander.report 失败(非阻塞): {e}")

    @staticmethod
    def _on_commander_report(event):
        """接收交易指挥官报告并缓存"""
        try:
            # EventBus 传递的是 Event 对象; .data 才是原始 dict
            data = event.data if hasattr(event, "data") else event
            user_id = data.get("user_id", "default")
            report = data.get("report", {})
            AgentLoop._commander_reports[user_id] = {
                "report": report,
                "cached_at": time.time()
            }
            logger.info(f"[AgentLoop] 收到交易报告并缓存: user={user_id}")
        except Exception as e:
            logger.debug(f"[AgentLoop] 处理 commander.report 失败(非阻塞): {e}")

    async def run(
        self,
        task: Any,
        max_rounds: int = None,
        chat_history: list[dict] = None,
        chat_count: int = 0,
        session_id: str = "console",
        voice_instance=None,
        mode: str = "daily",
        user_id: str = None,
        task_id: str | None = None,
        resume_from_checkpoint: bool = False,
        workflow_mode: bool = False,
        workflow_execution_id: str | None = None
    ) -> tuple[str | None, Any]:
        """
        运行Agent主循环（已统一为异步版本）

        [Phase 1] 所有对外入口已统一为原生 async，删除同步桥接。
        调用方必须 await 本方法。

        Args:
            task: 任务对象
            max_rounds: 最大循环轮数
            chat_history: 聊天历史
            chat_count: 对话计数
            session_id: 会话ID
            voice_instance: 语音实例
            mode: 工作模式 (daily/focus)
            user_id: 用户ID
            task_id: 任务ID（用于断点续传）
            resume_from_checkpoint: 是否从断点恢复
            workflow_mode: 是否启用工作流模式
            workflow_execution_id: 工作流执行实例ID

        Returns:
            - 非工作流模式: Tuple[Optional[str], Any] (AI回复, 工作记忆对象)
            - 工作流模式: Dict[str, Any] (由 WorkflowExecutor.run_workflow_mode_async 返回)
        """
        self._execution_count += 1

        # 【P0修复】启动意识核心（确保只启动一次）
        # 之前 start_unified.py 的调用可能在初始化阶段失败或被跳过，
        # 在 AgentLoop 首次运行任务时兜底启动，确保思维线程感知、周期性经验提取、视觉主动拉取全部激活
        if not AgentLoop._consciousness_started:
            try:
                from core.consciousness.Consciousness import get_consciousness
                consciousness = get_consciousness()

                async def _start_consciousness():
                    try:
                        await consciousness.start()
                        AgentLoop._consciousness_started = True
                        logger.info("[AgentLoop] 意识核心启动成功")
                    except Exception as ce:
                        logger.error(f"[AgentLoop] 意识核心启动失败: {ce}", exc_info=True)
                        # 【修复】启动失败时重置标志，允许下次重试
                        AgentLoop._consciousness_started = False

                _task_con = safe_create_task(_start_consciousness(), name="start_consciousness")
                _task_con.add_done_callback(
                    lambda t: logger.error(f"[AgentLoop] 意识核心启动任务异常: {t.exception()}") if t.exception() else None
                )
                logger.info("[AgentLoop] 意识核心启动任务已调度")
            except Exception as e:
                logger.error(f"[AgentLoop] 意识核心调度失败: {e}", exc_info=True)

        # 工作流模式：走独立通道，不再硬塞给 run_agent_loop()
        if workflow_mode and workflow_execution_id:
            from core.workflow.workflow_executor import WorkflowExecutor
            executor = WorkflowExecutor()
            return await executor.run_workflow_mode_async(
                execution_id=workflow_execution_id,
                user_id=user_id or "anonymous",
                voice_instance=voice_instance,
                chat_history=chat_history
            )

        return await run_agent_loop(
            task=task,
            max_rounds=max_rounds,
            chat_history=chat_history,
            chat_count=chat_count,
            session_id=session_id,
            voice_instance=voice_instance,
            mode=mode,
            user_id=user_id,
            task_id=task_id,
            resume_from_checkpoint=resume_from_checkpoint
        )

    async def run_async(
        self,
        task: Any,
        max_rounds: int = None,
        chat_history: list[dict] = None,
        chat_count: int = 0,
        session_id: str = "console",
        voice_instance=None,
        mode: str = "daily",
        user_id: str = None,
        task_id: str | None = None,
        resume_from_checkpoint: bool = False,
        workflow_mode: bool = False,
        workflow_execution_id: str | None = None
    ) -> tuple[str | None, Any]:
        """
        运行Agent主循环（异步版本）

        Args:
            task: 任务对象
            max_rounds: 最大循环轮数
            chat_history: 聊天历史
            chat_count: 对话计数
            session_id: 会话ID
            voice_instance: 语音实例
            mode: 工作模式
            user_id: 用户ID
            task_id: 任务ID
            resume_from_checkpoint: 是否从断点恢复
            workflow_mode: 是否启用工作流模式
            workflow_execution_id: 工作流执行实例ID

        Returns:
            - 非工作流模式: Tuple[Optional[str], Any] (AI回复, 工作记忆对象)
            - 工作流模式: Dict[str, Any] (由 WorkflowExecutor.run_workflow_mode 返回)
        """
        self._execution_count += 1

        # 工作流模式：走独立通道，不再硬塞给 run_agent_loop_async()
        if workflow_mode and workflow_execution_id:
            from core.workflow.workflow_executor import WorkflowExecutor
            executor = WorkflowExecutor()
            return await executor.run_workflow_mode_async(
                execution_id=workflow_execution_id,
                user_id=user_id or "anonymous",
                voice_instance=voice_instance,
                chat_history=chat_history
            )

        return await run_agent_loop_async(
            task=task,
            max_rounds=max_rounds,
            chat_history=chat_history,
            chat_count=chat_count,
            session_id=session_id,
            db_session_id=None,
            voice_instance=voice_instance,
            mode=mode,
            user_id=user_id,
            task_id=task_id,
            resume_from_checkpoint=resume_from_checkpoint
        )

    async def process_async(self, prompt: str, max_turns: int = None) -> dict[str, Any]:
        """子代理入口：接收已组装好的 prompt，直接执行主循环。

        解决 SubAgentRuntime._execute_with_loop() 调用不存在的 process_async
        导致子代理回退到模拟执行的问题。

        Args:
            prompt: 子代理已组装好的完整 prompt
            max_turns: 最大循环轮数

        Returns:
            Dict[str, Any]: {"output": str, "data": dict, "token_usage": dict}
        """
        try:
            task = SimpleNamespace(
                description=prompt,
                priority=1,
                id=str(uuid.uuid4()),
                intent={"raw": prompt},  # 【修复】补全intent，避免loop_initialization解析出空指令
            )
            reply, _ = await self.run_async(
                task=task,
                max_rounds=max_turns or 10,
                mode="focus",
            )
            return {
                "output": reply or "",
                "data": {},
                "token_usage": {},
            }
        except Exception as e:
            logger.error(f"[AgentLoop-process_async] 子代理执行失败: {e}")
            return {
                "output": f"[执行错误] {str(e)}",
                "data": {},
                "token_usage": {},
            }

    async def analyze_completion(
        self,
        user_instruction: str,
        execution_history: list[dict],
        working_memory: Any = None,
        chat_history: list[dict] | None = None
    ) -> TaskAnalysisResult:
        """
        分析任务完成状态

        【P1修复】新增方法，使用TaskCompletionAnalyzer进行智能分析
        【Phase 1】统一为原生 async 接口。

        Args:
            user_instruction: 用户指令
            execution_history: 执行历史
            working_memory: 工作记忆对象
            chat_history: 聊天历史

        Returns:
            TaskAnalysisResult: 任务分析结果
        """
        # analyzer.analyze 是纯计算（字符串匹配/列表操作），无需 to_thread
        return self.analyzer.analyze(
            user_instruction=user_instruction,
            execution_history=execution_history,
            working_memory=working_memory,
            chat_history=chat_history
        )

    @property
    def execution_count(self) -> int:
        """获取执行次数统计"""
        return self._execution_count




# after_tool 链：VisionHook -> ToolHook -> VoiceHook
agent_loop_hooks.register('after_tool', vision_hook.after_tool, priority=20)
agent_loop_hooks.register('after_tool', tool_hook.after_tool, priority=10)
agent_loop_hooks.register('after_tool', voice_hook.after_tool, priority=30)

# before_prompt / after_prompt 链：VoiceHook -> SafetyHook
agent_loop_hooks.register('before_prompt', voice_hook.before_prompt, priority=30)
agent_loop_hooks.register('after_prompt', safety_hook.after_prompt, priority=50)
agent_loop_hooks.register('after_prompt', voice_hook.after_prompt, priority=30)

# before_tool 链：SafetyHook（道德检查）
agent_loop_hooks.register('before_tool', safety_hook.before_tool, priority=50)

# after_loop 链：ToolHook -> VoiceHook
# 注意：ToolHook 需在 VoiceHook 之前，确保断点保存先于语音播报
agent_loop_hooks.register('after_loop', tool_hook.after_loop_async, priority=10)
agent_loop_hooks.register('after_loop', voice_hook.after_loop, priority=30)

# before_step / after_step 链：ToolHook（断点续传）
# 注意：ToolHook 需在 SafetyHook 之后、VoiceHook 之前，与 after_tool 的优先级策略一致
agent_loop_hooks.register('before_step', tool_hook.before_step_async, priority=10)
agent_loop_hooks.register('after_step', tool_hook.after_step_async, priority=10)

# Phase 6 新增意图/状态特定 Hook：VoiceHook
agent_loop_hooks.register('on_complete', voice_hook.on_complete, priority=30)
agent_loop_hooks.register('on_plan', voice_hook.on_plan, priority=30)
agent_loop_hooks.register('on_layer_switch', voice_hook.on_layer_switch, priority=30)
agent_loop_hooks.register('on_pause', voice_hook.on_pause, priority=30)
agent_loop_hooks.register('on_resume', voice_hook.on_resume, priority=30)
agent_loop_hooks.register('on_terminate', voice_hook.on_terminate, priority=30)
agent_loop_hooks.register('on_user_assist', voice_hook.on_user_assist, priority=30)
agent_loop_hooks.register('on_world_model', voice_hook.on_world_model, priority=30)
agent_loop_hooks.register('on_understanding_confirmed', voice_hook.on_understanding_confirmed, priority=30)
agent_loop_hooks.register('on_error', voice_hook.on_error, priority=30)
agent_loop_hooks.register('on_moral_blocked', voice_hook.on_moral_blocked, priority=30)

logger.info("[AgentLoop] Phase 6 Hook 注册完成")

# 【Phase 8】注册核心决策逻辑 Hook（干预/感知/上下文组装/世界模型）
try:
    from core.agent.hooks.core_logic_hooks import register_core_logic_hooks
    register_core_logic_hooks(agent_loop_hooks)
    logger.info("[AgentLoop] Phase 8 CoreLogicHooks 注册完成")
except Exception as e:
    logger.warning(f"[AgentLoop] Phase 8 CoreLogicHooks 注册失败: {e}")

# =============================================================================  # 分隔线
# 文件角色总结  # 总结开始
# =============================================================================  # 分隔线
#
# 【核心定位】  # 核心定位
# 本文件是 SiliconBase V5 系统的"Agent主循环"，是整个AI助手的核心执行引擎。  # 定位说明
# 采用ReAct（Reasoning + Acting）架构，实现多轮AI调用、工具执行、记忆检索的闭环。  # 架构说明
#
# 【主要功能模块】  # 功能模块
# 1. 语音播报智能策略（VoicePreferences/VoiceAnnounceStrategy）：  # 模块1
#    - 用户可配置播报间隔、启用状态、智能模式  # 功能1-1
#    - 基于时间间隔、意图变化、记忆数量、层级切换的智能播报决策  # 功能1-2
#    - 避免重复冗余播报，提升用户体验  # 功能1-3
#
# 2. ReAct主循环（run_agent_loop/run_agent_loop_async）：  # 模块2
#    - 同步和异步双版本，解决高并发阻塞问题（PERF-001）  # 功能2-1
#    - 无限循环直到AI返回FINAL_ANSWER或用户中断，AI拥有完全自主权  # 功能2-2
#    - 支持多步骤任务执行，自动检查任务完成状态  # 功能2-3
#
# 3. 三层记忆路由（L1/L2/L3/L4/L5）：  # 模块3
#    - L1短期记忆：最近30轮对话历史  # 功能3-1
#    - L2中期记忆：今日相关经验  # 功能3-2
#    - L3长期记忆：通用策略和萃取模式  # 功能3-3
#    - L4向量经验：语义检索相关经验  # 功能3-4
#    - L5执行统计：工具成功率统计  # 功能3-5
#
# 4. 游戏化分层交互（Layer 1/2/3）：  # 模块4
#    - Layer 1: 意图识别层，确定任务类型  # 功能4-1
#    - Layer 2: 工具查询层，查询可用工具列表  # 功能4-2
#    - Layer 3: 工具详情层，获取具体工具参数  # 功能4-3
#    - 支持层级切换次数限制，防止无限循环  # 功能4-4
#
# 5. 精准抓取（Precision Parser）：  # 模块5
#    - 分离AI输出中的自然语言和计算机语言  # 功能5-1
#    - 识别20种AI计算机语言标记  # 功能5-2
#    - 智能决定何时播报自然语言  # 功能5-3
#
# 6. 长任务模式（Long Task Mode）：  # 模块6
#    - 支持任务暂停、状态快照、恢复执行  # 功能6-1
#    - AI需提交理解摘要，用户确认后才能恢复  # 功能6-2
#    - 保障长时间任务的可靠性和用户控制  # 功能6-3
#
# 7. AI计算机语言（20个标记，6个层次）：  # 模块7
#    - 用户交互层：CALL_USER, ASK_USER, WAIT_CONFIRM, NOTIFY_USER  # 层次1
#    - 工具查询层：FIND_TOOL, QUERY_TOOL_LIST, QUERY_TOOL_DETAIL  # 层次2
#    - 记忆认知层：QUERY_MEMORY, RECORD_MEMORY, DELETE_MEMORY  # 层次3
#    - 学习进化层：ENTER_LEARNING, EXECUTE_PLAN, REFLECT, EVOLVE, EVOLVE_MEMORY  # 层次4
#    - 预测感知层：WORLD_MODEL_PREDICT, VISION_ANALYZE, BEHAVIOR_ANALYZE  # 层次5
#    - 系统控制层：PAUSE_EXECUTION, RESUME_EXECUTION, TERMINATE_TASK, SUBMIT_UNDERSTANDING  # 层次6
#
# =============================================================================
# 向后兼容再导出
# =============================================================================
# 这些符号原先由本模块隐式暴露，外部活跃代码仍通过
# `from core.agent.agent_loop import ...` 引用，因此保留再导出。
from core.agent.voice_utils import speak_ai_reply  # noqa: F401
from core.utils.common import set_voice_for_tts  # noqa: F401

# 【关联文件】  # 关联文件
# - core/ai_adapter.py          : AI调用适配器（同步/异步）  # 关联1
# - core/working_memory.py      : 工作记忆管理  # 关联2
# - core/intent_handler.py      : 意图处理器  # 关联3
# - core/nlp_intent_parser.py   : NLP意图解析和精准抓取  # 关联4
# - core/memory.py              : 记忆系统  # 关联5
# - core/vector_memory.py       : 向量记忆（L4）  # 关联6
# - core/execution_memory.py    : 执行记忆（L5）  # 关联7
# - core/planner.py             : 任务规划器  # 关联8
# - core/world_model.py         : 世界模型预测  # 关联9
# - core/reflector.py           : 反思系统  # 关联10
# - core/evolution.py           : 进化引擎  # 关联11
# - core/function_trigger.py    : 功能触发器  # 关联12
# - core/pause_confirmation_state_machine.py : 长任务状态机  # 关联13
# - core/state_snapshot.py      : 状态快照管理  # 关联14
#
# 【核心效果】  # 核心效果
# 1. 自主决策：AI拥有完全自主权决定任务何时完成，无需硬编码限制  # 效果1
# 2. 多轮执行：支持复杂多步骤任务，AI可连续调用多个工具完成目标  # 效果2
# 3. 记忆增强：五层记忆系统为AI提供丰富的上下文和历史经验  # 效果3
# 4. 智能交互：语音播报策略避免打扰，精准抓取分离人机语言  # 效果4
# 5. 长任务支持：任务可暂停、恢复，保障可靠性和用户控制  # 效果5
# 6. 持续学习：探索引擎、反思系统、进化引擎形成学习闭环  # 效果6
# 7. 高并发支持：异步版本解决阻塞问题，支持多用户同时交互  # 效果7
#
# 【使用场景】  # 使用场景
# - 日常对话：简单问答、闲聊、信息查询  # 场景1
# - 单步任务：打开应用、查询天气、设置提醒  # 场景2
# - 多步任务：写文档并保存、搜索并整理信息、批量处理文件  # 场景3
# - 长任务：数据迁移、批量转换、长时间监控任务  # 场景4
# - 学习进化：任务执行后自动萃取经验，提升后续执行效率  # 场景5
# ═════════════════════════════════════════════════════════════════════════════
# 【Phase 6】Hook 统一注册：将已有和新 Hook 统一挂到 agent_loop_hooks 注册表
# ═════════════════════════════════════════════════════════════════════════════
# 说明：
# - 从 Phase 6 开始，ToolHook / VisionHook / VoiceHook / SafetyHook 全部通过
#   agent_loop_hooks 注册表驱动，不再在 agent_loop.py 中显式硬编码调用。
# - 只注册 async 入口。同步入口 execute() / execute_with_signals() 已在 Phase 3 废弃，
#   当前全部通过 execute_async() / execute_async_with_signals() 直接 await。
# - 注册顺序（priority 降序执行）：
#   SafetyHook(50) 优先级最高，确保安全和幻觉检测最先执行。
#   VoiceHook(30) 在业务 Hook 之后，负责播报。
#   VisionHook(20) -> ToolHook(10) 与原先显式调用顺序保持一致。
# ═════════════════════════════════════════════════════════════════════════════
