#!/usr/bin/env python3
"""
演示学习系统 (Learning from Demonstration)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

实现从用户演示中学习操作流程，并支持后续自动执行。

核心组件：
1. OperationRecorder - 用户操作录制器
2. ProcedureLibrary - 操作流程库
3. DemonstrationLearner - 演示学习器
4. AdaptiveExecutor - 自适应执行器
5. ProcedureLearningTaskCoordinator - 任务协调器（整合以上所有组件）

使用流程：
1. AI执行任务遇到问题时，调用 coordinator.pause_for_chat() 暂停并询问用户
2. 用户选择"我来演示"，调用 coordinator.start_user_demonstration() 开始录制
3. 用户完成操作，调用 coordinator.stop_user_demonstration() 停止并学习
4. AI保存学习到的流程到流程库
5. 下次相同需求时，从流程库查找并直接执行

快速开始：
    from core.procedure_learning import get_task_coordinator, TaskMode

    # 获取协调器
    coordinator = get_task_coordinator()

    # 开始任务
    session = coordinator.start_task("session_001", "task_001", "定机票去上海")

    # AI执行任务遇到问题，暂停并进入聊天
    coordinator.pause_for_chat("session_001", "需要登录，无法继续")

    # 用户选择演示，开始录制
    coordinator.start_user_demonstration("session_001")

    # 用户操作完成后，停止并学习
    procedure = coordinator.stop_user_demonstration("session_001")

    # 下次同样需求时，查找已有流程
    procedures = coordinator.procedure_library.find_by_intent("定机票")
    if procedures:
        # 执行学习到的流程
        coordinator.execute_learned_procedure("session_002", procedures[0].procedure_id)

作者: AI Assistant
版本: 1.0.0
"""

from .adaptive_executor import AdaptiveExecutor, ExecutionStatus, get_adaptive_executor
from .demonstration_learner import DemonstrationLearner, get_demonstration_learner
from .operation_recorder import OperationRecorder, OperationType, UserOperation, get_operation_recorder
from .procedure_library import Procedure, ProcedureLibrary, ProcedureStep, get_procedure_library
from .task_coordinator import ProcedureLearningTaskCoordinator, TaskMode, TaskSession, get_task_coordinator

__all__ = [
    # 录制
    'OperationRecorder',
    'UserOperation',
    'OperationType',
    'get_operation_recorder',
    # 流程库
    'ProcedureLibrary',
    'Procedure',
    'ProcedureStep',
    'get_procedure_library',
    # 学习
    'DemonstrationLearner',
    'get_demonstration_learner',
    # 执行
    'AdaptiveExecutor',
    'ExecutionStatus',
    'get_adaptive_executor',
    # 协调器
    'ProcedureLearningTaskCoordinator',
    'TaskMode',
    'TaskSession',
    'get_task_coordinator',
]

__version__ = '1.0.0'
