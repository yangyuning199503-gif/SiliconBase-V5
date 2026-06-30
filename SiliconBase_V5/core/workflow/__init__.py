#!/usr/bin/env python3
"""
Workflow 模块 - 任务编排与状态管理 V1.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
提供复杂任务的编排、执行和状态管理能力

【核心组件】
1. WorkflowEngine - 工作流引擎
   - 步骤间数据流（变量绑定与传递）
   - 与 LongTaskSlots 深度集成
   - 与 CheckpointManager 断点续传集成
   - 支持用户中途修改

2. WorkflowStateMachine - 动态状态机
   - 完整状态图定义
   - 用户干预支持（暂停、修改、恢复）
   - 状态转换钩子

3. PerceptionFusion - 感知融合中心
   - 统一感知接口（视觉+系统+环境+上下文）
   - 执行结果验证
   - 与现有工具集成

【使用示例】
    # 定义工作流
    from core.workflow import get_workflow_engine, WorkflowDefinition, WorkflowStep, StepStatus

    engine = get_workflow_engine()

    workflow = WorkflowDefinition(
        workflow_id="bitcoin_to_excel",
        name="获取比特币行情并生成Excel",
        steps=[
            WorkflowStep(
                step_id="fetch_data",
                name="获取网页数据",
                tool_id="web_fetch",
                tool_params={"url": "https://example.com"},
                outputs={"result": "$html_raw"},
                step_category="fetch",
                is_critical=True
            ),
            WorkflowStep(
                step_id="parse_data",
                name="解析数据",
                tool_id="web_parse",
                inputs={"html": "$html_raw"},  # 引用上一步输出
                step_category="transform",
                is_critical=True
            )
        ]
    )

    # 注册并执行（Phase 8: 异步入口）
    import asyncio
    engine.create_workflow(workflow)
    execution_id = asyncio.run(engine.execute_workflow(
        workflow_id="bitcoin_to_excel",
        initial_vars={},
        mode="slot"
    ))

    # 查询状态
    status = engine.get_execution_status(execution_id)

    # 用户修改（暂停后）
    engine.modify_execution(execution_id, {
        "modify_params": {"parse_data": {"selector": ".new-price"}},
        "update_variables": {"custom_param": "value"}
    })

    # 恢复执行
    engine.resume_execution(execution_id)
"""

from .perception_fusion import (
    EnvironmentContext,
    ExpectedOutcome,
    PerceptionConfig,
    PerceptionFusion,
    SystemContext,
    TaskContext,
    UnifiedPerceptionContext,
    VerificationResult,
    VisualContext,
    capture_perception,
    get_perception_fusion,
    verify_outcome,
)
from .state_machine import State, StateEvent, WorkflowStateMachine, create_state_machine
from .workflow_engine import (
    ExecutionStatus,
    StepStatus,
    VariableResolver,
    WorkflowDefinition,
    WorkflowEngine,
    WorkflowExecution,
    WorkflowStep,
    get_workflow_engine,
)

# Phase 2 新增组件
from .workflow_executor import (
    ExecutionConfig,
    ProgressPushConfig,  # 【新增】进度推送配置
    StepExecutionResult,
    WorkflowExecutionResult,
    WorkflowExecutor,
    WorkflowProgressBroadcaster,  # 【新增】进度广播器
    get_workflow_executor,
)

try:
    from .events import (
        CheckpointSaved,
        EventBus,
        EventPriority,
        EventType,
        StateChanged,
        StepCompleted,
        StepFailed,
        StepProgress,  # 【新增】步骤进度事件
        StepRetry,
        StepSkipped,
        StepStarted,
        WorkflowCancelled,
        WorkflowCompleted,
        WorkflowEvent,
        WorkflowFailed,
        WorkflowModified,
        WorkflowPaused,
        WorkflowResumed,
        WorkflowStarted,
        get_event_bus,
        publish_event,
    )
    EVENTS_AVAILABLE = True
except ImportError:
    EVENTS_AVAILABLE = False

__version__ = "1.0.0"
__all__ = [
    # 工作流引擎
    'WorkflowEngine',
    'WorkflowDefinition',
    'WorkflowStep',
    'WorkflowExecution',
    'StepStatus',
    'ExecutionStatus',
    'VariableResolver',
    'get_workflow_engine',
    # 状态机
    'WorkflowStateMachine',
    'StateEvent',
    'State',
    'create_state_machine',
    # 感知融合
    'PerceptionFusion',
    'PerceptionConfig',
    'UnifiedPerceptionContext',
    'VisualContext',
    'SystemContext',
    'EnvironmentContext',
    'TaskContext',
    'ExpectedOutcome',
    'VerificationResult',
    'get_perception_fusion',
    'capture_perception',
    'verify_outcome',
    # Phase 2: 工作流执行器
    'WorkflowExecutor',
    'ExecutionConfig',
    'StepExecutionResult',
    'WorkflowExecutionResult',
    'ProgressPushConfig',          # 【新增】进度推送配置
    'WorkflowProgressBroadcaster',  # 【新增】进度广播器
    'get_workflow_executor',
    # Phase 2: 事件系统（如果可用）
    'WorkflowEvent',
    'EventType',
    'EventPriority',
    'WorkflowStarted',
    'WorkflowCompleted',
    'WorkflowFailed',
    'WorkflowCancelled',
    'StepStarted',
    'StepProgress',  # 【新增】步骤进度事件
    'StepCompleted',
    'StepFailed',
    'StepSkipped',
    'StepRetry',
    'WorkflowPaused',
    'WorkflowResumed',
    'WorkflowModified',
    'StateChanged',
    'CheckpointSaved',
    'EventBus',
    'get_event_bus',
    'publish_event',
]
