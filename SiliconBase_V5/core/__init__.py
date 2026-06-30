#!/usr/bin/env python3
"""
SiliconBase V5 核心模块

【重要说明】
本文件使用条件导入模式，确保即使某些子模块缺失或导入失败，
核心包仍然可以正常初始化。使用 find_spec 预检查提升启动速度。
"""

import logging
from importlib.util import find_spec

_logger = logging.getLogger(__name__)


# ============================================================================
# 第一部分：预检查可选依赖（提升启动速度）
# ============================================================================

def _check_optional_deps():
    """
    预检查可选依赖，使用 find_spec 避免重复导入失败的开销
    """
    deps = {
        # 基础工具
        'dependency_utils': 'core.utils.dependency_utils',
        'runtime_state': 'core.session.runtime_state',
        'risk_level': 'core.safety.risk_level',
        'belief_strategy': 'core.strategy.belief_strategy',
        # 条件导入模块
        'token_budget': 'core.cost.token_budget_manager',
        'sync_service': 'core.sync.sync_service',
        'ai_config': 'core.ai.ai_config',
        'app_mapping': 'core.utils.app_mapping',
        'value_system_v2': 'core.strategy.value_system_v2',
        'importance_engine': 'core.strategy.importance_engine',
        'ast_security_checker': 'core.safety.ast_security_checker',
        'moral_system': 'core.safety.moral_system',
        'user_task_store': 'core.task.user_task_store',
        'user_task_vector_store': 'core.task.user_task_vector_store',
        'phase_anchor': 'core.memory.phase_anchor',
        'state_registry': 'core.session.state_registry',
        'pause_confirmation': 'core.agent.pause_confirmation_state_machine',
        'evolution_enhanced': 'core.evolution.evolution',
        'evolution': 'core.evolution.evolution',
        'long_task_slots': 'core.task.long_task_slots',
        'long_task_context_manager': 'core.task.long_task_context_manager',
        'smart_context_manager': 'core.prompt.smart_context_manager',
        'weekly_report': 'core.reflector.weekly_report_scheduler',
        'key_decision_detector': 'core.strategy.key_decision_detector',
        'life_prompt_injector': 'core.prompt.life_prompt_injector',
        'life_presence': 'core.consciousness.life_presence',
        'procedure_learning_integration': 'core.evolution.procedure_learning_integration',
        'base_tool': 'core.tool.base_tool',
        'error_codes': 'core.utils.error_codes',
        'vector_memory': 'core.memory.vector_memory_compat',
        'task_scheduler': 'core.task.task_scheduler',
        'memory_source': 'core.memory.memory_source',
        'tool_manager': 'core.tool.tool_manager',
    }

    available = {}
    missing = []

    for name, module in deps.items():
        try:
            available[name] = find_spec(module) is not None
            if not available[name]:
                missing.append(name)
        except Exception as e:
            available[name] = False
            missing.append(name)
            _logger.error(f"[Core] 检查依赖失败 {name}: {e}")

    if missing:
        _logger.warning(f"[Core] 以下可选依赖未安装: {', '.join(missing)}")
        _logger.warning("[Core] 部分功能可能不可用，建议安装完整依赖")

    return available


# 执行预检查
OPTIONAL_DEPS = _check_optional_deps()


# ============================================================================
# 第二部分：基础工具（无依赖或依赖简单的模块）
# ============================================================================

# 依赖工具
if OPTIONAL_DEPS.get('dependency_utils'):
    from .utils.dependency_utils import rwlock_dep, watchdog_dep
    DEPENDENCY_UTILS_AVAILABLE = True
else:
    _logger.error("[Core] dependency_utils 不可用")
    DEPENDENCY_UTILS_AVAILABLE = False
    watchdog_dep = None
    rwlock_dep = None

# 运行时状态
if OPTIONAL_DEPS.get('runtime_state'):
    from .session.runtime_state import RuntimeState, get_state_persistence
    RUNTIME_STATE_AVAILABLE = True
else:
    _logger.error("[Core] runtime_state 不可用")
    RUNTIME_STATE_AVAILABLE = False
    RuntimeState = None
    get_state_persistence = None

# 风险等级
if OPTIONAL_DEPS.get('risk_level'):
    from .safety.risk_level import RiskLevel
    RISK_LEVEL_AVAILABLE = True
else:
    _logger.error("[Core] risk_level 不可用")
    RISK_LEVEL_AVAILABLE = False
    RiskLevel = None

# 信念策略
if OPTIONAL_DEPS.get('belief_strategy'):
    from .strategy.belief_strategy import BeliefStrategyPattern, StrategyStatus
    BELIEF_STRATEGY_AVAILABLE = True
else:
    _logger.error("[Core] belief_strategy 不可用")
    BELIEF_STRATEGY_AVAILABLE = False
    BeliefStrategyPattern = None
    StrategyStatus = None


# ============================================================================
# 第三部分：条件导入的子模块（按依赖复杂度排序）
# ============================================================================

# Token 预算管理器 (core/cost/)
if OPTIONAL_DEPS.get('token_budget'):
    from .cost.token_budget_manager import (
        TokenBudgetManager,
        TokenBudgetResult,
        TokenCalculator,
        allocate_category_budget,
        count_tokens,
        get_token_budget_manager,
    )
    TOKEN_BUDGET_MANAGER_AVAILABLE = True
else:
    _logger.error("[Core] TokenBudgetManager 不可用")
    TOKEN_BUDGET_MANAGER_AVAILABLE = False
    TokenBudgetManager = None
    TokenCalculator = None
    TokenBudgetResult = None
    get_token_budget_manager = None
    allocate_category_budget = None
    count_tokens = None

# 同步服务
if OPTIONAL_DEPS.get('sync_service'):
    from .sync.sync_service import (
        CloudSyncAPI,
        ConflictResolution,
        LocalStorageAdapter,
        SyncItem,
        SyncRecord,
        SyncService,
        SyncStatus,
        get_sync_service,
        init_sync_service,
        stop_sync_service,
    )
    SYNC_SERVICE_AVAILABLE = True
else:
    _logger.error("[Core] SyncService 不可用")
    SYNC_SERVICE_AVAILABLE = False
    SyncService = None
    SyncStatus = None
    SyncItem = None
    SyncRecord = None
    ConflictResolution = None
    LocalStorageAdapter = None
    CloudSyncAPI = None
    get_sync_service = None
    init_sync_service = None
    stop_sync_service = None


# ============================================================================
# 第四部分：向后兼容的重新导出
# ============================================================================

# AI 配置模块 (实际在 core/ai/)
if OPTIONAL_DEPS.get('ai_config'):
    from .ai.ai_config import AIScene, ai_config, get_chat_config, get_code_config, get_react_config
    AI_CONFIG_AVAILABLE = True
else:
    _logger.error("[Core] AI配置 不可用")
    AI_CONFIG_AVAILABLE = False
    get_react_config = None
    get_code_config = None
    get_chat_config = None
    AIScene = None
    ai_config = None

# 应用映射 (实际在 core/utils/)
if OPTIONAL_DEPS.get('app_mapping'):
    from .utils.app_mapping import AppMapping, AppMappingManager, get_app_mapping_manager
    APP_MAPPING_AVAILABLE = True
else:
    _logger.error("[Core] 应用映射 不可用")
    APP_MAPPING_AVAILABLE = False
    AppMapping = None
    AppMappingManager = None
    get_app_mapping_manager = None

# 价值系统 V2 (实际在 core/strategy/)
if OPTIONAL_DEPS.get('value_system_v2'):
    from .strategy.value_system_v2 import (
        EmotionalState,
        ValueAssessmentV2,
        ValueDimension,
        ValueSystemV2,
        assess_memory_value_v2,
        value_system_v2,
    )
    VALUE_SYSTEM_V2_AVAILABLE = True
else:
    _logger.error("[Core] 价值系统 不可用")
    VALUE_SYSTEM_V2_AVAILABLE = False
    ValueSystemV2 = None
    ValueAssessmentV2 = None
    ValueDimension = None
    value_system_v2 = None
    assess_memory_value_v2 = None
    EmotionalState = None

# 重要性引擎 (实际在 core/strategy/)
if OPTIONAL_DEPS.get('importance_engine'):
    from .strategy.importance_engine import ImportanceLevel, calculate_importance, get_importance_engine
    IMPORTANCE_ENGINE_AVAILABLE = True
else:
    _logger.error("[Core] 重要性引擎 不可用")
    IMPORTANCE_ENGINE_AVAILABLE = False
    calculate_importance = None
    ImportanceLevel = None
    get_importance_engine = None

# AST 安全检测器 (实际在 core/safety/)
if OPTIONAL_DEPS.get('ast_security_checker'):
    from .safety.ast_security_checker import EnhancedASTChecker, check_code_safety
    AST_SECURITY_CHECKER_AVAILABLE = True
else:
    _logger.error("[Core] AST安全检测器 不可用")
    AST_SECURITY_CHECKER_AVAILABLE = False
    EnhancedASTChecker = None
    check_code_safety = None

# 道德系统 (实际在 core/safety/)
if OPTIONAL_DEPS.get('moral_system'):
    from .safety.moral_system import MoralGuard
    # 为向后兼容提供别名
    MoralSystem = MoralGuard
    # get_moral_system 不存在，设置为 None 保持向后兼容
    get_moral_system = None
    MORAL_SYSTEM_AVAILABLE = True
else:
    _logger.error("[Core] 道德系统 不可用")
    MORAL_SYSTEM_AVAILABLE = False
    get_moral_system = None
    MoralSystem = None
    MoralGuard = None

# 用户任务存储 (实际在 core/task/)
if OPTIONAL_DEPS.get('user_task_store'):
    from .task.user_task_store import TaskStoreManager, UserTaskStore
    # user_task_store 实例不存在，使用类作为替代
    user_task_store = None
    # get_user_task_store 函数不存在
    get_user_task_store = None
    USER_TASK_STORE_AVAILABLE = True
else:
    _logger.error("[Core] 用户任务存储 不可用")
    USER_TASK_STORE_AVAILABLE = False
    user_task_store = None
    get_user_task_store = None
    UserTaskStore = None
    TaskStoreManager = None

# 用户任务向量存储 (实际在 core/task/)
if OPTIONAL_DEPS.get('user_task_vector_store'):
    from .task.user_task_vector_store import (
        TaskVectorStoreManager,
        UserTaskVectorStore,
        get_user_task_vector_store,
        task_vector_store_manager,
    )
    USER_TASK_VECTOR_STORE_AVAILABLE = True
else:
    _logger.error("[Core] 用户任务向量存储 不可用")
    USER_TASK_VECTOR_STORE_AVAILABLE = False
    TaskVectorStoreManager = None
    get_user_task_vector_store = None
    task_vector_store_manager = None
    UserTaskVectorStore = None

# 阶段锚点 (实际在 core/memory/)
if OPTIONAL_DEPS.get('phase_anchor'):
    from .memory.phase_anchor import PhaseAnchorManager, get_phase_anchor_manager, save_anchor
    PHASE_ANCHOR_AVAILABLE = True
else:
    _logger.error("[Core] 阶段锚点 不可用")
    PHASE_ANCHOR_AVAILABLE = False
    save_anchor = None
    get_phase_anchor_manager = None
    PhaseAnchorManager = None

# 状态注册表 (实际在 core/session/)
if OPTIONAL_DEPS.get('state_registry'):
    from .session.state_registry import StateRegistry, get_state_registry, register_state
    STATE_REGISTRY_AVAILABLE = True
else:
    _logger.error("[Core] 状态注册表 不可用")
    STATE_REGISTRY_AVAILABLE = False
    register_state = None
    get_state_registry = None
    StateRegistry = None

# 暂停确认状态机 (实际在 core/agent/)
if OPTIONAL_DEPS.get('pause_confirmation'):
    from .agent.pause_confirmation_state_machine import (
        PauseConfirmationManager,
        PauseConfirmationState,
        get_pause_confirmation_manager,
    )
    PAUSE_CONFIRMATION_AVAILABLE = True
else:
    _logger.error("[Core] 暂停确认状态机 不可用")
    PAUSE_CONFIRMATION_AVAILABLE = False
    get_pause_confirmation_manager = None
    PauseConfirmationManager = None
    PauseConfirmationState = None

# 进化系统 (已合并到 core/evolution/evolution.py)
# 注: evolution_enhanced.py 和 evolution_service.py 已归档到 archive/fixes/
if OPTIONAL_DEPS.get('evolution'):
    from .evolution.evolution import (
        EnhancedEvolutionEngine,
        EvolutionEngine,
        enhanced_evolution,
        evolution,
        get_enhanced_evolution_engine,
        get_evolution_engine,
        get_experience_for_task,
    )
    EVOLUTION_AVAILABLE = True
    EVOLUTION_ENHANCED_AVAILABLE = True
else:
    _logger.error("[Core] 进化系统 不可用")
    EVOLUTION_AVAILABLE = False
    EVOLUTION_ENHANCED_AVAILABLE = False
    EvolutionEngine = None
    EnhancedEvolutionEngine = None
    evolution = None
    enhanced_evolution = None
    get_evolution_engine = None
    get_enhanced_evolution_engine = None
    get_experience_for_task = None

# 长任务槽位 (实际在 core/task/)
if OPTIONAL_DEPS.get('long_task_slots'):
    from .task.long_task_slots import LongTaskSlots
    LONG_TASK_SLOTS_AVAILABLE = True
else:
    _logger.error("[Core] 长任务槽位 不可用")
    LONG_TASK_SLOTS_AVAILABLE = False
    LongTaskSlots = None

# 长任务上下文管理器 (实际在 core/task/)
if OPTIONAL_DEPS.get('long_task_context_manager'):
    from .task.long_task_context_manager import LongTaskContextManager
    LONG_TASK_CONTEXT_MANAGER_AVAILABLE = True
else:
    _logger.error("[Core] 长任务上下文管理器 不可用")
    LONG_TASK_CONTEXT_MANAGER_AVAILABLE = False
    LongTaskContextManager = None

# 智能上下文管理器 (实际在 core/prompt/)
if OPTIONAL_DEPS.get('smart_context_manager'):
    from .prompt.smart_context_manager import SmartContextManager
    SMART_CONTEXT_MANAGER_AVAILABLE = True
else:
    _logger.error("[Core] 智能上下文管理器 不可用")
    SMART_CONTEXT_MANAGER_AVAILABLE = False
    SmartContextManager = None

# 周报调度器 (实际在 core/reflector/)
if OPTIONAL_DEPS.get('weekly_report'):
    from .reflector.weekly_report_scheduler import WeeklyReport
    WEEKLY_REPORT_AVAILABLE = True
else:
    _logger.error("[Core] 周报调度器 不可用")
    WEEKLY_REPORT_AVAILABLE = False
    WeeklyReport = None

# 关键决策检测器 (实际在 core/strategy/)
if OPTIONAL_DEPS.get('key_decision_detector'):
    from .strategy.key_decision_detector import (
        DecisionPoint,
        KeyDecisionDetector,
        detect_key_decision,
        get_key_decision_detector,
    )
    KEY_DECISION_DETECTOR_AVAILABLE = True
else:
    _logger.error("[Core] 关键决策检测器 不可用")
    KEY_DECISION_DETECTOR_AVAILABLE = False
    detect_key_decision = None
    KeyDecisionDetector = None
    DecisionPoint = None
    get_key_decision_detector = None

# 硅基生命提示注入器 (实际在 core/prompt/)
if OPTIONAL_DEPS.get('life_prompt_injector'):
    from .prompt.life_prompt_injector import LifePromptInjector, get_life_prompt_injector, inject_life_state_to_prompt
    # 为向后兼容提供别名
    inject_life_prompt = inject_life_state_to_prompt
    LIFE_PROMPT_INJECTOR_AVAILABLE = True
else:
    _logger.error("[Core] 硅基生命提示注入器 不可用")
    LIFE_PROMPT_INJECTOR_AVAILABLE = False
    LifePromptInjector = None
    inject_life_prompt = None
    get_life_prompt_injector = None

# 硅基生命存在感管理器 (实际在 core/consciousness/)
if OPTIONAL_DEPS.get('life_presence'):
    from .consciousness.life_presence import EventType, get_life_presence_manager, update_ai_state
    LIFE_PRESENCE_AVAILABLE = True
else:
    _logger.error("[Core] 硅基生命存在感管理器 不可用")
    LIFE_PRESENCE_AVAILABLE = False
    get_life_presence_manager = None
    EventType = None
    update_ai_state = None

# 演示学习集成 (实际在 core/evolution/)
if OPTIONAL_DEPS.get('procedure_learning_integration'):
    from .evolution.procedure_learning_integration import (
        ProcedureLearningIntegration,
        get_procedure_learning_integration,
    )
    PROCEDURE_LEARNING_INTEGRATION_AVAILABLE = True
else:
    _logger.error("[Core] 演示学习集成 不可用")
    PROCEDURE_LEARNING_INTEGRATION_AVAILABLE = False
    ProcedureLearningIntegration = None
    get_procedure_learning_integration = None


# ============================================================================
# 第五部分：为 tools/ 目录下的工具提供向后兼容的重新导出
# ============================================================================

# 基础工具类 (实际在 core/tool/)
if OPTIONAL_DEPS.get('base_tool'):
    from .tool.base_tool import BaseTool
    BASE_TOOL_AVAILABLE = True
else:
    _logger.error("[Core] BaseTool 不可用")
    BASE_TOOL_AVAILABLE = False
    BaseTool = None

# 错误码 (实际在 core/utils/)
if OPTIONAL_DEPS.get('error_codes'):
    from .utils.error_codes import INVALID_PARAMS, TOOL_ELEMENT_NOT_FOUND, TOOL_EXECUTION_ERROR, ErrorCode, format_error
    ERROR_CODES_AVAILABLE = True
else:
    _logger.error("[Core] error_codes 不可用")
    ERROR_CODES_AVAILABLE = False
    format_error = None
    TOOL_EXECUTION_ERROR = None
    INVALID_PARAMS = None
    TOOL_ELEMENT_NOT_FOUND = None
    ErrorCode = None

# 向量记忆 (实际在 core/memory/)
if OPTIONAL_DEPS.get('vector_memory'):
    from .memory.vector_memory_compat import vector_memory
    VECTOR_MEMORY_EXPORT_AVAILABLE = True
else:
    _logger.error("[Core] vector_memory 不可用")
    VECTOR_MEMORY_EXPORT_AVAILABLE = False
    vector_memory = None

# AI任务调度器 (实际在 core/task/)
if OPTIONAL_DEPS.get('task_scheduler'):
    from .task.task_scheduler import get_task_scheduler as get_ai_scheduler
    AI_TASK_SCHEDULER_AVAILABLE = True
else:
    _logger.error("[Core] task_scheduler 不可用")
    AI_TASK_SCHEDULER_AVAILABLE = False
    get_ai_scheduler = None

# 记忆来源 (实际在 core/memory/)
if OPTIONAL_DEPS.get('memory_source'):
    from .memory.memory_source import MemorySource
    MEMORY_SOURCE_AVAILABLE = True
else:
    _logger.error("[Core] memory_source 不可用")
    MEMORY_SOURCE_AVAILABLE = False
    MemorySource = None

# 工具管理器 (实际在 core/tool/)
if OPTIONAL_DEPS.get('tool_manager'):
    from .tool.tool_manager import ToolManager, tool_manager
    TOOL_MANAGER_EXPORT_AVAILABLE = True
else:
    _logger.error("[Core] tool_manager 不可用")
    TOOL_MANAGER_EXPORT_AVAILABLE = False
    tool_manager = None
    ToolManager = None


# ============================================================================
# __all__ 定义 - 列出所有导出的名称
# ============================================================================

__all__ = [
    # 预检查
    "OPTIONAL_DEPS",
    # 基础工具
    "watchdog_dep", "rwlock_dep", "DEPENDENCY_UTILS_AVAILABLE",
    "RuntimeState", "get_state_persistence", "RUNTIME_STATE_AVAILABLE",
    "RiskLevel", "RISK_LEVEL_AVAILABLE",
    "BeliefStrategyPattern", "StrategyStatus", "BELIEF_STRATEGY_AVAILABLE",
    # TokenBudgetManager
    "TokenBudgetManager", "TokenCalculator", "TokenBudgetResult",
    "get_token_budget_manager", "allocate_category_budget", "count_tokens",
    "TOKEN_BUDGET_MANAGER_AVAILABLE",
    # 同步服务
    "SyncService", "SyncStatus", "SyncItem", "SyncRecord",
    "ConflictResolution", "LocalStorageAdapter", "CloudSyncAPI",
    "get_sync_service", "init_sync_service", "stop_sync_service",
    "SYNC_SERVICE_AVAILABLE",
    # AI 配置
    "get_react_config", "get_code_config", "get_chat_config",
    "AIScene", "ai_config", "AI_CONFIG_AVAILABLE",
    # 应用映射
    "AppMapping", "AppMappingManager", "get_app_mapping_manager", "APP_MAPPING_AVAILABLE",
    # 价值系统
    "ValueSystemV2", "ValueAssessmentV2", "ValueDimension",
    "value_system_v2", "assess_memory_value_v2", "EmotionalState", "VALUE_SYSTEM_V2_AVAILABLE",
    # 重要性引擎
    "calculate_importance", "ImportanceLevel", "get_importance_engine", "IMPORTANCE_ENGINE_AVAILABLE",
    # AST安全检测
    "EnhancedASTChecker", "check_code_safety", "AST_SECURITY_CHECKER_AVAILABLE",
    # 道德系统
    "get_moral_system", "MoralSystem", "MORAL_SYSTEM_AVAILABLE",
    # 用户任务存储
    "user_task_store", "get_user_task_store", "USER_TASK_STORE_AVAILABLE",
    # 用户任务向量存储
    "TaskVectorStoreManager", "get_user_task_vector_store",
    "task_vector_store_manager", "UserTaskVectorStore", "USER_TASK_VECTOR_STORE_AVAILABLE",
    # 阶段锚点
    "save_anchor", "get_phase_anchor_manager", "PhaseAnchorManager", "PHASE_ANCHOR_AVAILABLE",
    # 状态注册表
    "register_state", "get_state_registry", "StateRegistry", "STATE_REGISTRY_AVAILABLE",
    # 暂停确认状态机
    "get_pause_confirmation_manager", "PauseConfirmationManager",
    "PauseConfirmationState", "PAUSE_CONFIRMATION_AVAILABLE",
    # 进化系统
    "EnhancedEvolutionEngine", "enhanced_evolution", "get_enhanced_evolution_engine",
    "EVOLUTION_ENHANCED_AVAILABLE", "evolution", "EVOLUTION_AVAILABLE",
    # 长任务
    "LongTaskSlots", "LONG_TASK_SLOTS_AVAILABLE",
    "LongTaskContextManager", "LONG_TASK_CONTEXT_MANAGER_AVAILABLE",
    # 智能上下文管理器
    "SmartContextManager", "SMART_CONTEXT_MANAGER_AVAILABLE",
    # 周报调度器
    "WeeklyReport", "WEEKLY_REPORT_AVAILABLE",
    # 关键决策检测器
    "detect_key_decision", "KeyDecisionDetector", "DecisionPoint", "get_key_decision_detector", "KEY_DECISION_DETECTOR_AVAILABLE",
    # 硅基生命提示注入器
    "LifePromptInjector", "inject_life_prompt", "get_life_prompt_injector", "LIFE_PROMPT_INJECTOR_AVAILABLE",
    # 硅基生命存在感管理器
    "get_life_presence_manager", "EventType", "update_ai_state", "LIFE_PRESENCE_AVAILABLE",
    # 演示学习集成
    "ProcedureLearningIntegration", "get_procedure_learning_integration", "PROCEDURE_LEARNING_INTEGRATION_AVAILABLE",
    # 工具模块（为 tools/ 目录下的工具提供向后兼容）
    "BaseTool", "BASE_TOOL_AVAILABLE",
    "format_error", "TOOL_EXECUTION_ERROR", "INVALID_PARAMS", "TOOL_ELEMENT_NOT_FOUND", "ErrorCode", "ERROR_CODES_AVAILABLE",
    "vector_memory", "VECTOR_MEMORY_EXPORT_AVAILABLE",
    "get_ai_scheduler", "AI_TASK_SCHEDULER_AVAILABLE",
    "MemorySource", "MEMORY_SOURCE_AVAILABLE",
    "tool_manager", "ToolManager", "TOOL_MANAGER_EXPORT_AVAILABLE",
]
