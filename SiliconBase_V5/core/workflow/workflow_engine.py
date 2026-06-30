#!/usr/bin/env python3
"""
WorkflowEngine - 工作流引擎 V1.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
负责任务的编排、执行和状态管理

【核心特性】
1. 步骤间数据流（变量绑定与传递）
2. 与 LongTaskSlots 深度集成
3. 与 CheckpointManager 断点续传集成
4. 支持用户中途修改

【架构位置】
- 位于: core/workflow/workflow_engine.py
- 调用方: AgentLoop（工作流模式）、LongTaskSlots、API层
- 依赖: CheckpointManager、ToolManager、PerceptionFusion
"""

import asyncio
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# 导入项目组件
try:
    from core.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger('workflow_engine')

try:
    from core.config import config
except ImportError:
    config = None

try:
    from core.sync.event_bus import event_bus  # 【ExperienceBus】事件总线
except ImportError:
    event_bus = None

# 【Phase 2 增强】变量解析器（自动降级兼容）
try:
    from .variable_resolver_with_fallback import resolve_variable as _resolve_variable_enhanced
    _VARIABLE_RESOLVER_ENHANCED = True
except ImportError:
    _VARIABLE_RESOLVER_ENHANCED = False
    logger.debug("[WorkflowEngine] 变量解析增强模块未安装，使用基础解析")

# 【Phase 2 增强】条件评估器（支持复杂表达式如: a > 0 and b < 10）
try:
    from .condition_evaluator_enhanced import ConditionEvaluator
    logger.debug("[WorkflowEngine] 条件评估增强模块已加载")
except ImportError:
    ConditionEvaluator = None
    logger.debug("[WorkflowEngine] 条件评估增强模块未安装，使用基础解析")


# ═══════════════════════════════════════════════════════════════════════════════
# 枚举定义
# ═══════════════════════════════════════════════════════════════════════════════

class StepStatus(Enum):
    """步骤状态枚举"""
    PENDING = "pending"         # 等待执行
    READY = "ready"             # 就绪（依赖已满足）
    RUNNING = "running"         # 执行中
    COMPLETED = "completed"     # 已完成
    FAILED = "failed"           # 失败
    SKIPPED = "skipped"         # 被跳过
    PAUSED = "paused"           # 暂停（等待用户）
    VERIFYING = "verifying"     # 验证中


class ExecutionStatus(Enum):
    """执行状态枚举"""
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ═══════════════════════════════════════════════════════════════════════════════
# 数据类定义
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class WorkflowStep:
    """
    工作流步骤定义

    扩展自 task/planner.py 的 PlanStep，增加数据流和状态机支持
    """
    step_id: str = field(default_factory=lambda: f"step_{uuid.uuid4().hex[:8]}")
    name: str = "未命名步骤"
    description: str = ""

    # 工具执行
    tool_id: str = ""
    tool_params: dict[str, Any] = field(default_factory=dict)

    # 【核心】数据流定义
    inputs: dict[str, str] = field(default_factory=dict)
    # {"param_name": "$prev_step.output_field"} 或 {"param_name": "$variable_name"}

    outputs: dict[str, str] = field(default_factory=dict)
    # {"result_key": "alias_name"} - 将结果字段映射到变量名

    output_mapping: dict[str, str] = field(default_factory=dict)
    # 结果字段映射，用于复杂数据结构提取

    # 执行控制
    is_critical: bool = True  # 是否为关键步骤
    step_category: str = "action"  # check, launch, action, transform, verify, save
    execution_mode: str = "sequential"  # sequential, parallel, conditional

    # 条件分支
    condition: str | None = None  # 执行条件，如 "$prev.success == true"
    on_success: str | None = None  # 成功时跳转步骤ID
    on_failure: str | None = None  # 失败时跳转步骤ID

    # 人机协作
    requires_confirmation: bool = False
    confirmation_message: str = ""
    allow_modification: bool = True

    # 超时与重试
    timeout: int = 60  # 秒
    max_retries: int = 3

    # 运行时状态（非序列化）
    status: StepStatus = StepStatus.PENDING
    result: Any = None
    error: str = ""
    retry_count: int = 0
    started_at: float | None = None
    completed_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（用于序列化）"""
        return {
            "step_id": self.step_id,
            "name": self.name,
            "description": self.description,
            "tool_id": self.tool_id,
            "tool_params": self.tool_params,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "output_mapping": self.output_mapping,
            "is_critical": self.is_critical,
            "step_category": self.step_category,
            "execution_mode": self.execution_mode,
            "condition": self.condition,
            "on_success": self.on_success,
            "on_failure": self.on_failure,
            "requires_confirmation": self.requires_confirmation,
            "confirmation_message": self.confirmation_message,
            "allow_modification": self.allow_modification,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "status": self.status.value,
            "error": self.error,
            "retry_count": self.retry_count
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'WorkflowStep':
        """从字典创建实例"""
        step = cls()
        step.step_id = data.get("step_id", step.step_id)
        step.name = data.get("name", step.name)
        step.description = data.get("description", step.description)
        step.tool_id = data.get("tool_id", "")
        step.tool_params = data.get("tool_params", {})
        step.inputs = data.get("inputs", {})
        step.outputs = data.get("outputs", {})
        step.output_mapping = data.get("output_mapping", {})
        step.is_critical = data.get("is_critical", True)
        step.step_category = data.get("step_category", "action")
        step.execution_mode = data.get("execution_mode", "sequential")
        step.condition = data.get("condition")
        step.on_success = data.get("on_success")
        step.on_failure = data.get("on_failure")
        step.requires_confirmation = data.get("requires_confirmation", False)
        step.confirmation_message = data.get("confirmation_message", "")
        step.allow_modification = data.get("allow_modification", True)
        step.timeout = data.get("timeout", 60)
        step.max_retries = data.get("max_retries", 3)
        step.status = StepStatus(data.get("status", "pending"))
        step.error = data.get("error", "")
        step.retry_count = data.get("retry_count", 0)
        return step


@dataclass
class WorkflowDefinition:
    """工作流定义"""
    workflow_id: str = field(default_factory=lambda: f"wf_{uuid.uuid4().hex[:12]}")
    name: str = "未命名工作流"
    description: str = ""
    steps: list[WorkflowStep] = field(default_factory=list)

    # 全局变量定义（带默认值）
    variables: dict[str, Any] = field(default_factory=dict)

    # 执行策略
    execution_strategy: str = "sequential"  # sequential, parallel, adaptive
    max_retries: int = 3
    timeout_per_step: int = 60

    # 感知配置
    perception_config: dict[str, Any] = field(default_factory=lambda: {
        "enable_visual": True,
        "enable_system": False,
        "screenshot_before_step": [],
        "screenshot_after_step": [],
        "verification_required": ["transform", "save"]
    })

    # 元数据
    created_at: float = field(default_factory=time.time)
    created_by: str = "system"
    version: str = "1.0.0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "name": self.name,
            "description": self.description,
            "steps": [s.to_dict() for s in self.steps],
            "variables": self.variables,
            "execution_strategy": self.execution_strategy,
            "max_retries": self.max_retries,
            "timeout_per_step": self.timeout_per_step,
            "perception_config": self.perception_config,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "version": self.version
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'WorkflowDefinition':
        wf = cls()
        wf.workflow_id = data.get("workflow_id", wf.workflow_id)
        wf.name = data.get("name", wf.name)
        wf.description = data.get("description", "")
        wf.steps = [WorkflowStep.from_dict(s) for s in data.get("steps", [])]
        wf.variables = data.get("variables", {})
        wf.execution_strategy = data.get("execution_strategy", "sequential")
        wf.max_retries = data.get("max_retries", 3)
        wf.timeout_per_step = data.get("timeout_per_step", 60)
        wf.perception_config = data.get("perception_config", {})
        wf.created_at = data.get("created_at", time.time())
        wf.created_by = data.get("created_by", "system")
        wf.version = data.get("version", "1.0.0")
        return wf

    def get_step(self, step_id: str) -> WorkflowStep | None:
        """获取指定步骤"""
        for step in self.steps:
            if step.step_id == step_id:
                return step
        return None

    def get_step_index(self, step_id: str) -> int:
        """获取步骤索引"""
        for i, step in enumerate(self.steps):
            if step.step_id == step_id:
                return i
        return -1


@dataclass
class WorkflowExecution:
    """工作流执行实例"""
    execution_id: str = field(default_factory=lambda: f"exec_{uuid.uuid4().hex[:12]}")
    workflow_id: str = ""
    user_id: str = "default"

    # 运行时变量空间
    variables: dict[str, Any] = field(default_factory=dict)

    # 执行状态
    status: ExecutionStatus = ExecutionStatus.PENDING
    current_step_idx: int = 0
    step_results: dict[str, Any] = field(default_factory=dict)

    # 关联ID
    slot_id: int | None = None
    session_id: str | None = None
    task_id: str | None = None

    # 时间戳
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None

    # 修改历史
    modification_history: list[dict[str, Any]] = field(default_factory=list)

    # 运行时属性（非序列化）
    workflow: WorkflowDefinition | None = field(default=None, repr=False)

    def get_progress(self) -> float:
        """获取进度百分比"""
        if not self.workflow or not self.workflow.steps:
            return 0.0
        return (self.current_step_idx / len(self.workflow.steps)) * 100

    def get_current_step(self) -> WorkflowStep | None:
        """获取当前步骤"""
        if not self.workflow:
            return None
        if 0 <= self.current_step_idx < len(self.workflow.steps):
            return self.workflow.steps[self.current_step_idx]
        return None

    def get_pending_steps(self) -> list[WorkflowStep]:
        """获取待执行步骤"""
        if not self.workflow:
            return []
        return [s for s in self.workflow.steps[self.current_step_idx:]
                if s.status == StepStatus.PENDING]

    def skip_step(self, step_id: str) -> bool:
        """跳过指定步骤"""
        step = self.workflow.get_step(step_id) if self.workflow else None
        if step and not step.is_critical:
            step.status = StepStatus.SKIPPED
            logger.info(f"[WorkflowExecution] 跳过步骤: {step_id}")
            return True
        logger.warning(f"[WorkflowExecution] 无法跳过关键步骤: {step_id}")
        return False

    def modify_step_params(self, step_id: str, new_params: dict[str, Any]) -> bool:
        """修改步骤参数"""
        step = self.workflow.get_step(step_id) if self.workflow else None
        if step and step.allow_modification:
            old_params = step.tool_params.copy()
            step.tool_params.update(new_params)
            self.modification_history.append({
                "timestamp": time.time(),
                "action": "modify_params",
                "step_id": step_id,
                "old": old_params,
                "new": step.tool_params.copy()
            })
            logger.info(f"[WorkflowExecution] 修改步骤参数: {step_id}")
            return True
        return False

    def insert_step(self, index: int, step: WorkflowStep) -> bool:
        """插入新步骤"""
        if not self.workflow:
            return False
        self.workflow.steps.insert(index, step)
        self.modification_history.append({
            "timestamp": time.time(),
            "action": "insert_step",
            "index": index,
            "step_id": step.step_id
        })
        logger.info(f"[WorkflowExecution] 插入步骤: {step.step_id} 在位置 {index}")
        return True

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "execution_id": self.execution_id,
            "workflow_id": self.workflow_id,
            "user_id": self.user_id,
            "variables": self.variables,
            "status": self.status.value,
            "current_step_idx": self.current_step_idx,
            "step_results": self.step_results,
            "slot_id": self.slot_id,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "modification_history": self.modification_history
        }


# ═══════════════════════════════════════════════════════════════════════════════
# 变量解析器
# ═══════════════════════════════════════════════════════════════════════════════

class VariableResolver:
    """变量解析器 - 处理步骤间的数据流

    【P2修复】支持数组索引和复杂路径访问
    - $step.items[0].name -> 访问数组元素
    - $step.data.users[0].profile.name -> 嵌套数组访问
    - $step.result?default -> 支持默认值语法
    """

    # 变量引用模式: 支持点分隔路径和数组索引
    # 匹配: $variable, $step.field, $step.items[0].name, $step.data[0][1]
    VAR_PATTERN = re.compile(
        r'\$([a-zA-Z_][a-zA-Z0-9_]*'  # 基础变量名
        r'(?:\[[0-9]+\])*'           # 可选连续数组索引 [0][1]
        r'(?:\.[a-zA-Z_][a-zA-Z0-9_]*(?:\[[0-9]+\])*)*'  # 嵌套字段和数组
        r'(?:\?[^\s}]*)?)'           # 可选默认值 ?default
    )

    @classmethod
    def resolve(cls, value: Any, variables: dict[str, Any],
                step_results: dict[str, Any]) -> Any:
        """
        解析变量引用

        支持格式：
        - $variable_name -> 从全局变量查找
        - $step_id.field -> 从步骤结果查找
        - 嵌套结构中的变量引用
        """
        if isinstance(value, str):
            return cls._resolve_string(value, variables, step_results)
        elif isinstance(value, dict):
            return {k: cls.resolve(v, variables, step_results)
                    for k, v in value.items()}
        elif isinstance(value, list):
            return [cls.resolve(item, variables, step_results) for item in value]
        return value

    @classmethod
    def _resolve_string(cls, value: str, variables: dict[str, Any],
                       step_results: dict[str, Any]) -> Any:
        """解析字符串中的变量引用"""
        # 纯变量引用（整个字符串就是一个变量）
        if value.startswith('$') and len(value) > 1:
            var_path = value[1:]
            # 检查是否有其他字符（不是纯变量）
            if not cls.VAR_PATTERN.fullmatch(value):
                # 混合字符串，需要替换
                return cls._replace_variables(value, variables, step_results)

            # 纯变量引用
            return cls._get_value_by_path(var_path, variables, step_results)

        # 混合字符串，替换所有变量引用
        return cls._replace_variables(value, variables, step_results)

    @classmethod
    def _replace_variables(cls, text: str, variables: dict[str, Any],
                          step_results: dict[str, Any]) -> str:
        """替换字符串中的所有变量引用"""
        def replace_match(match):
            var_path = match.group(1)
            value = cls._get_value_by_path(var_path, variables, step_results)
            return str(value) if value is not None else match.group(0)

        return cls.VAR_PATTERN.sub(replace_match, text)

    @classmethod
    def _get_value_by_path(cls, path: str, variables: dict[str, Any],
                          step_results: dict[str, Any]) -> Any:
        """根据路径获取值 - 【P2修复】支持数组索引和复杂路径

        支持格式:
        - step.field -> 普通字段访问
        - step.items[0] -> 数组索引访问
        - step.items[0].name -> 嵌套数组+字段
        - step.data[0][1] -> 多维数组
        - step.field?default -> 带默认值
        """
        # 处理默认值语法: path?default
        default_value = None
        if '?' in path:
            path, default_value = path.split('?', 1)
            default_value = default_value.strip() or None

        # 解析路径部分（支持字段和数组索引混合）
        import re
        # 匹配: field 或 field[index] 或 [index]
        token_pattern = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)?(?:\[([0-9]+)\])?')
        tokens = []
        pos = 0

        while pos < len(path):
            match = token_pattern.match(path, pos)
            if not match or match.end() == pos:
                break
            field, index = match.groups()
            if field or index is not None:
                tokens.append((field, int(index) if index else None))
            pos = match.end()
            if pos < len(path) and path[pos] == '.':
                pos += 1

        if not tokens:
            return default_value

        # 第一部分：判断是全局变量还是步骤结果
        first_field, first_index = tokens[0]
        if first_field in step_results:
            value = step_results[first_field]
        elif first_field in variables:
            value = variables[first_field]
        else:
            return default_value

        # 应用第一个token的数组索引
        if first_index is not None:
            if isinstance(value, (list, tuple)) and 0 <= first_index < len(value):
                value = value[first_index]
            else:
                return default_value

        # 剩余部分：字段路径和数组索引
        for field, index in tokens[1:]:
            if field and isinstance(value, dict):
                value = value.get(field)
            elif field:
                return default_value

            if index is not None:
                if isinstance(value, (list, tuple)) and 0 <= index < len(value):
                    value = value[index]
                else:
                    return default_value

        return value if value is not None else default_value

    @classmethod
    def extract_outputs(cls, result: Any, output_mapping: dict[str, str],
                       step_id: str) -> dict[str, Any]:
        """
        从结果中提取输出变量

        Args:
            result: 工具执行结果
            output_mapping: {结果字段: 变量名} 映射
            step_id: 当前步骤ID

        Returns:
            {变量名: 值} 字典
        """
        outputs = {}

        # 默认添加步骤结果引用
        outputs[step_id] = result

        if not isinstance(result, dict):
            return outputs

        for src_field, var_name in output_mapping.items():
            value = cls._get_nested_value(result, src_field)
            if value is not None:
                outputs[var_name] = value

        return outputs

    @classmethod
    def _get_nested_value(cls, data: dict, path: str) -> Any:
        """
        获取嵌套字典值（V1.0 + V1.1 增强）

        【三维度集成】
        - AI维度: 支持复杂路径（数组索引、通配符）
        - 用户维度: 自动选择最优解析策略
        - 项目维度: 100%向后兼容

        支持语法:
            - 简单: "step.result" → V1.0
            - 数组: "step.items[0].name" → V1.1
            - 通配: "step.items[*].status" → V1.1
        """
        # 【AI维度】复杂路径使用增强解析
        if _VARIABLE_RESOLVER_ENHANCED and '[' in path:
            try:
                return _resolve_variable_enhanced(path, data)
            except Exception as e:
                # 【用户维度】失败静默降级到 V1.0
                logger.debug(f"[WorkflowEngine] 变量解析增强失败，降级: {e}")

        # 【项目维度】V1.0 基础解析（完全兼容）
        parts = path.split('.')
        value = data
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return None
        return value


# ═══════════════════════════════════════════════════════════════════════════════
# 工作流引擎主类
# ═══════════════════════════════════════════════════════════════════════════════

class WorkflowEngine:
    """工作流引擎 - 核心类"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._initialized = True

        # 存储
        self._workflows: dict[str, WorkflowDefinition] = {}
        self._executions: dict[str, WorkflowExecution] = {}

        # 延迟加载的依赖（避免循环导入）
        self._checkpoint_manager = None
        self._long_task_slots = None
        self._tool_manager = None

        # 锁
        self._lock = threading.RLock()

        logger.info("[WorkflowEngine] 工作流引擎初始化完成")

    def _get_checkpoint_manager(self):
        """延迟加载 CheckpointManager"""
        if self._checkpoint_manager is None:
            try:
                from core.agent.checkpoint_manager import checkpoint_manager
                self._checkpoint_manager = checkpoint_manager
            except ImportError:
                logger.warning("[WorkflowEngine] CheckpointManager 不可用")
        return self._checkpoint_manager

    def _get_long_task_slots(self):
        """延迟加载 LongTaskSlots"""
        if self._long_task_slots is None:
            try:
                from core.task.long_task_slots import get_long_task_slots
                self._long_task_slots = get_long_task_slots()
            except ImportError:
                logger.warning("[WorkflowEngine] LongTaskSlots 不可用")
        return self._long_task_slots

    def _get_tool_manager(self):
        """延迟加载 ToolManager"""
        if self._tool_manager is None:
            try:
                from core.tool.tool_manager import ToolManager
                self._tool_manager = ToolManager()
            except ImportError:
                logger.warning("[WorkflowEngine] ToolManager 不可用")
        return self._tool_manager

    # ═══════════════════════════════════════════════════════════════════════════
    # 工作流定义管理
    # ═══════════════════════════════════════════════════════════════════════════

    def create_workflow(self, definition: WorkflowDefinition) -> str:
        """
        创建工作流定义

        Returns:
            workflow_id: 工作流ID
        """
        with self._lock:
            self._workflows[definition.workflow_id] = definition
            logger.info(f"[WorkflowEngine] 创建工作流: {definition.workflow_id} "
                       f"({definition.name}, {len(definition.steps)} 步骤)")
            return definition.workflow_id

    def get_workflow(self, workflow_id: str) -> WorkflowDefinition | None:
        """获取工作流定义"""
        return self._workflows.get(workflow_id)

    def delete_workflow(self, workflow_id: str) -> bool:
        """删除工作流定义"""
        with self._lock:
            if workflow_id in self._workflows:
                del self._workflows[workflow_id]
                return True
            return False

    def list_workflows(self) -> list[dict[str, Any]]:
        """列出所有工作流"""
        return [
            {
                "workflow_id": wf.workflow_id,
                "name": wf.name,
                "description": wf.description,
                "step_count": len(wf.steps),
                "created_at": wf.created_at
            }
            for wf in self._workflows.values()
        ]

    # ═══════════════════════════════════════════════════════════════════════════
    # 工作流执行
    # ═══════════════════════════════════════════════════════════════════════════

    async def execute_workflow(self, workflow_id: str,
                        initial_vars: dict[str, Any] | None = None,
                        user_id: str = "default",
                        mode: str = "default") -> str:
        """
        执行工作流

        Args:
            workflow_id: 工作流定义ID
            initial_vars: 初始变量
            user_id: 用户ID
            mode: 执行模式 (default/slot/agent_loop)

        Returns:
            execution_id: 执行实例ID
        """
        workflow = self.get_workflow(workflow_id)
        if not workflow:
            raise ValueError(f"工作流不存在: {workflow_id}")

        # 创建执行实例
        execution = WorkflowExecution(
            workflow_id=workflow_id,
            user_id=user_id,
            variables={**workflow.variables, **(initial_vars or {})},
            workflow=workflow,
            status=ExecutionStatus.PENDING
        )

        with self._lock:
            self._executions[execution.execution_id] = execution

        logger.info(f"[WorkflowEngine] 开始执行工作流: {execution.execution_id} "
                   f"(workflow: {workflow_id}, user: {user_id})")

        # 根据模式选择执行方式
        if mode == "slot":
            self._execute_via_slot(execution)
        elif mode == "agent_loop":
            await self._execute_via_agent_loop(execution)
        else:
            # 默认：在当前线程执行（用于测试）
            await self._execute_direct(execution)

        # 【ExperienceBus】工作流执行事件
        try:
            if event_bus:
                event_bus.emit("workflow:step_completed", {
                    "workflow_id": workflow_id,
                    "execution_id": execution.execution_id,
                    "user_id": user_id,
                    "mode": mode,
                    "timestamp": time.time(),
                })
        except Exception:
            pass

        return execution.execution_id

    def _execute_via_slot(self, execution: WorkflowExecution) -> int:
        """
        通过 LongTaskSlots 执行

        Returns:
            slot_id: 分配的槽位ID (1, 2, 3)

        Raises:
            RuntimeError: 没有可用槽位或 LongTaskSlots 不可用
        """
        long_task_slots = self._get_long_task_slots()
        if not long_task_slots:
            raise RuntimeError("LongTaskSlots 不可用")

        # 找到可用槽位 (1, 2, 3)
        slot_id = self._find_available_slot(long_task_slots)
        if slot_id is None:
            raise RuntimeError("没有可用的任务槽位 (1-3)，请先等待其他任务完成")

        # 创建任务配置
        task_config = {
            "task_name": execution.workflow.name,
            "task_type": "workflow",
            "user_requirements": execution.workflow.description,
            "params": {
                "workflow_id": execution.workflow_id,
                "execution_id": execution.execution_id,
                "initial_vars": execution.variables
            },
            "metadata": {
                "workflow_id": execution.workflow_id,
                "execution_id": execution.execution_id,
                "user_id": execution.user_id,
                "mode": "slot"
            }
        }

        # 创建并执行任务
        task_id = long_task_slots.create_task(slot_id, task_config)

        execution.slot_id = slot_id
        execution.task_id = task_id
        execution.status = ExecutionStatus.RUNNING
        execution.started_at = time.time()

        logger.info(f"[WorkflowEngine] 工作流已提交到槽位 {slot_id}, 任务ID: {task_id}")
        return slot_id

    def _find_available_slot(self, long_task_slots) -> int | None:
        """查找可用的槽位 (1, 2, 3)"""
        try:
            # 获取所有槽位状态
            all_slots = long_task_slots.get_all_slots_status_dict()

            # 找到空闲槽位
            for slot_id in [1, 2, 3]:
                slot_key = str(slot_id)
                if slot_key in all_slots:
                    slot_info = all_slots[slot_key]
                    if slot_info.get("status") == "idle":
                        return slot_id
        except Exception as e:
            logger.warning(f"[WorkflowEngine] 查找可用槽位失败: {e}")
            # 备用方案：直接尝试 1, 2, 3
            for slot_id in [1, 2, 3]:
                try:
                    status = long_task_slots.get_slot_status(slot_id)
                    if status is None:
                        return slot_id
                except Exception as e:
                    # [SILENT_FAILURE_BLOCKED] 工作流槽位状态检查失败
                    logger.error(f"[WorkflowEngine] 检查槽位 {slot_id} 状态失败: {e} [SILENT_FAILURE_BLOCKED]")
                    continue

        return None

    async def _execute_via_agent_loop(self, execution: WorkflowExecution):
        """通过 AgentLoop 执行（用于工作流模式）"""
        # 由 WorkflowExecutor 真正驱动工作流执行，连接 AgentLoop/ToolManager/SubAgent
        try:
            from core.workflow.workflow_executor import get_workflow_executor
            executor = get_workflow_executor()
            execution.status = ExecutionStatus.RUNNING
            execution.started_at = time.time()
            result = await executor.run_workflow_mode_async(
                execution_id=execution.execution_id,
                user_id=execution.user_id,
            )
            if not result.get("success", False):
                logger.error(f"[WorkflowEngine] agent_loop 模式执行失败: {result.get('error', '未知错误')}")
                execution.status = ExecutionStatus.FAILED
        except Exception as e:
            logger.error(f"[WorkflowEngine] agent_loop 模式执行异常: {e}", exc_info=True)
            execution.status = ExecutionStatus.FAILED

    async def _execute_direct(self, execution: WorkflowExecution):
        """直接执行（Phase 8 async化）"""
        execution.status = ExecutionStatus.RUNNING
        execution.started_at = time.time()

        try:
            await self._run_execution_steps(execution)
        except Exception as e:
            logger.error(f"[WorkflowEngine] 执行失败: {e}")
            execution.status = ExecutionStatus.FAILED

    async def _run_execution_steps(self, execution: WorkflowExecution):
        """执行步骤（核心逻辑）"""
        workflow = execution.workflow

        while 0 <= execution.current_step_idx < len(workflow.steps):
            step = workflow.steps[execution.current_step_idx]

            # 检查状态
            if execution.status == ExecutionStatus.PAUSED:
                logger.info(f"[WorkflowEngine] 执行暂停: {execution.execution_id}")
                return

            # 检查条件是否满足，不满足则跳过
            if not self._should_execute_step(execution, step):
                logger.info(f"[WorkflowEngine] 条件不满足，跳过步骤: {step.step_id}")
                step.status = StepStatus.SKIPPED
                execution.current_step_idx += 1
                continue

            # 执行步骤（带重试机制）
            await self._execute_step_with_retry(execution, step)

            # 检查步骤结果
            if step.status == StepStatus.FAILED and step.is_critical:
                execution.status = ExecutionStatus.FAILED
                return

            # 根据执行结果决定下一步
            next_idx = self._get_next_step_index(execution, step)
            if next_idx is None:
                # 没有指定跳转，正常进入下一步
                execution.current_step_idx += 1
            elif next_idx < 0 or next_idx >= len(workflow.steps):
                # 跳转到无效位置，结束工作流
                logger.warning(f"[WorkflowEngine] 跳转目标无效: {next_idx}，结束执行")
                execution.current_step_idx = len(workflow.steps)
            else:
                logger.info(f"[WorkflowEngine] 步骤跳转: {step.step_id} -> 步骤 {next_idx}")
                execution.current_step_idx = next_idx

        execution.status = ExecutionStatus.COMPLETED
        execution.completed_at = time.time()
        logger.info(f"[WorkflowEngine] 执行完成: {execution.execution_id}")

    def _should_execute_step(self, execution: WorkflowExecution, step: WorkflowStep) -> bool:
        """
        评估步骤执行条件

        条件表达式格式:
        - "$prev.success == true" - 检查上一步结果
        - "$variable_name != null" - 检查变量是否存在
        - "$step_id.result == value" - 检查特定步骤结果

        支持的操作符: ==, !=, <, >, <=, >=
        支持的值: true, false, null, 数字, 字符串(用引号包裹)

        Args:
            execution: 工作流执行实例
            step: 要评估的步骤

        Returns:
            bool: 条件是否满足，没有条件时返回 True
        """
        if not step.condition:
            return True

        try:
            return self._evaluate_condition(
                step.condition,
                execution.variables,
                execution.step_results
            )
        except Exception as e:
            logger.warning(f"[WorkflowEngine] 条件评估失败 '{step.condition}': {e}")
            # 条件评估失败时，默认允许执行（向后兼容）
            return True

    def _evaluate_condition(self, condition: str, variables: dict[str, Any],
                           step_results: dict[str, Any]) -> bool:
        """
        评估条件表达式

        Args:
            condition: 条件表达式字符串
            variables: 全局变量
            step_results: 步骤结果

        Returns:
            bool: 条件是否满足
        """
        # 尝试使用增强的条件评估器（支持复杂表达式如: a > 0 and b < 10）
        if ConditionEvaluator is not None:
            try:
                result = ConditionEvaluator.evaluate(condition, variables, step_results)
                logger.debug(f"[WorkflowEngine] 使用增强条件评估器: {condition} = {result}")
                return result
            except Exception as e:
                logger.debug(f"[WorkflowEngine] 增强条件评估器失败，回退到基础版本: {e}")

        # 基础条件评估（回退方案）
        return self._evaluate_condition_basic(condition, variables, step_results)

    def _evaluate_condition_basic(self, condition: str, variables: dict[str, Any],
                                   step_results: dict[str, Any]) -> bool:
        """
        基础条件表达式评估（回退方案）
        仅支持简单比较操作符: ==, !=, <, >, <=, >=
        """
        # 支持的比较操作符
        operators = ['==', '!=', '<=', '>=', '<', '>']

        # 查找操作符
        operator = None
        for op in operators:
            if op in condition:
                operator = op
                break

        if not operator:
            # 没有操作符，只检查变量是否存在且为真
            var_value = VariableResolver.resolve(condition, variables, step_results)
            return bool(var_value)

        # 分割左右操作数
        parts = condition.split(operator, 1)
        if len(parts) != 2:
            return False

        left_str = parts[0].strip()
        right_str = parts[1].strip()

        # 解析左操作数（通常是变量引用）
        left_value = VariableResolver.resolve(left_str, variables, step_results)

        # 解析右操作数（可以是变量或字面量）
        if right_str.startswith('$'):
            right_value = VariableResolver.resolve(right_str, variables, step_results)
        else:
            # 字面量解析
            right_value = self._parse_literal(right_str)

        # 执行比较
        try:
            if operator == '==':
                return left_value == right_value
            elif operator == '!=':
                return left_value != right_value
            elif operator in ('<', '>', '<=', '>='):
                # 数值比较
                if left_value is None or right_value is None:
                    return False
                return eval(f"{repr(left_value)} {operator} {repr(right_value)}")
        except Exception as e:
            logger.debug(f"[WorkflowEngine] 比较操作失败: {e}")
            return False

        return False

    def _parse_literal(self, value_str: str) -> Any:
        """
        解析字面量值

        支持: true, false, null, 数字, 字符串
        """
        value_str = value_str.strip()
        lower = value_str.lower()

        # 布尔值
        if lower == 'true':
            return True
        if lower == 'false':
            return False

        # null
        if lower == 'null' or lower == 'none':
            return None

        # 数字
        try:
            if '.' in value_str:
                return float(value_str)
            return int(value_str)
        except ValueError:
            pass

        # 字符串（去除引号）
        if (value_str.startswith('"') and value_str.endswith('"')) or \
           (value_str.startswith("'") and value_str.endswith("'")):
            return value_str[1:-1]

        # 默认返回原字符串
        return value_str

    def _get_next_step_index(self, execution: WorkflowExecution, step: WorkflowStep) -> int | None:
        """
        根据执行结果决定下一步索引

        Args:
            execution: 工作流执行实例
            step: 刚执行的步骤

        Returns:
            Optional[int]: 下一步的索引，None 表示顺序执行
        """
        workflow = execution.workflow
        if not workflow:
            return None

        # 根据步骤状态选择跳转目标
        if step.status == StepStatus.COMPLETED and step.on_success:
            # 成功，检查 on_success
            idx = workflow.get_step_index(step.on_success)
            if idx >= 0:
                return idx
            logger.warning(f"[WorkflowEngine] on_success 目标步骤不存在: {step.on_success}")

        elif step.status == StepStatus.FAILED and step.on_failure:
            # 失败，检查 on_failure
            idx = workflow.get_step_index(step.on_failure)
            if idx >= 0:
                return idx
            logger.warning(f"[WorkflowEngine] on_failure 目标步骤不存在: {step.on_failure}")

        # 没有跳转指定，或目标不存在，返回 None（顺序执行）
        return None

    async def _execute_step_with_retry(self, execution: WorkflowExecution, step: WorkflowStep):
        """
        执行单个步骤（带指数退避重试机制）

        重试策略：
        - 基础延迟从配置读取: config.get("workflow.retry_delay", 2) 秒
        - 指数退避: delay = base_delay * (2^attempt)，最大30秒
        - 重试前重置步骤状态为 PENDING
        - 重试次数用尽后才标记为 FAILED
        """
        # 获取基础延迟配置
        base_delay = 2
        if config:
            base_delay = config.get("workflow.retry_delay", 2)

        max_delay = 30  # 最大延迟30秒

        while step.retry_count <= step.max_retries:
            # 执行单次步骤
            await self._do_step_execution(execution, step)

            # 如果成功或已跳过，直接返回
            if step.status in (StepStatus.COMPLETED, StepStatus.SKIPPED):
                return

            # 检查是否需要重试
            if step.retry_count < step.max_retries:
                step.retry_count += 1

                # 计算指数退避延迟
                delay = min(base_delay * (2 ** (step.retry_count - 1)), max_delay)

                logger.warning(
                    f"[WorkflowEngine] 步骤失败，准备重试: {step.step_id} "
                    f"({step.retry_count}/{step.max_retries})，"
                    f"等待 {delay:.1f} 秒后重试..."
                )

                # 重置步骤状态为 PENDING，准备重试
                step.status = StepStatus.PENDING
                step.error = ""

                # 指数退避延迟（Phase 8: async化）
                import asyncio
                await asyncio.sleep(delay)
            else:
                # 重试次数用尽，标记为最终失败
                logger.error(
                    f"[WorkflowEngine] 步骤重试次数用尽: {step.step_id} "
                    f"({step.max_retries} 次重试后仍然失败)"
                )
                # 【ExperienceBus】步骤失败事件
                try:
                    if event_bus:
                        event_bus.emit("workflow:step_failed", {
                            "workflow_id": execution.workflow_id,
                            "execution_id": execution.execution_id,
                            "step_id": step.step_id,
                            "retry_count": step.retry_count,
                            "timestamp": time.time(),
                        })
                except Exception:
                    pass
                break

    async def _do_step_execution(self, execution: WorkflowExecution, step: WorkflowStep):
        """
        执行单次步骤（无重试逻辑）

        Args:
            execution: 工作流执行实例
            step: 要执行的步骤
        """
        logger.info(f"[WorkflowEngine] 执行步骤: {step.step_id} ({step.name})")

        step.status = StepStatus.RUNNING
        step.started_at = time.time()

        try:
            # 1. 解析输入参数
            resolved_params = VariableResolver.resolve(
                step.tool_params,
                execution.variables,
                execution.step_results
            )

            # 2. 执行工具（Phase 8: async化）
            tool_manager = self._get_tool_manager()
            if tool_manager:
                # 【P1修复】步骤级超时控制，防止工具死锁导致工作流永久挂起
                step_timeout = getattr(step, 'timeout', None) or 60
                result = await asyncio.wait_for(
                    tool_manager.execute_tool_async(step.tool_id, resolved_params),
                    timeout=step_timeout
                )
            else:
                # 测试模式：模拟执行
                result = {"success": True, "data": {"mock": True}}

            step.result = result

            # 3. 处理结果
            if result.get("success"):
                step.status = StepStatus.COMPLETED

                # 提取输出变量
                outputs = VariableResolver.extract_outputs(
                    result, step.output_mapping, step.step_id
                )
                execution.variables.update(outputs)
                execution.step_results[step.step_id] = result

            else:
                step.status = StepStatus.FAILED
                step.error = result.get("error", "未知错误")

            step.completed_at = time.time()

            # 4. 保存检查点
            checkpoint_mgr = self._get_checkpoint_manager()
            if checkpoint_mgr:
                checkpoint_mgr.save_checkpoint(
                    task_id=execution.execution_id,
                    checkpoint_name=f"完成步骤: {step.step_id}"
                )

        except Exception as e:
            logger.error(f"[WorkflowEngine] 步骤执行异常: {e}")
            step.status = StepStatus.FAILED
            step.error = str(e)
            step.completed_at = time.time()

    # ═══════════════════════════════════════════════════════════════════════════
    # 执行状态管理
    # ═══════════════════════════════════════════════════════════════════════════

    def get_execution(self, execution_id: str) -> WorkflowExecution | None:
        """获取执行实例"""
        return self._executions.get(execution_id)

    def get_execution_status(self, execution_id: str) -> dict[str, Any]:
        """
        获取执行状态

        Returns:
            {
                "execution_id": str,
                "status": str,
                "current_step": int,
                "total_steps": int,
                "progress": float,
                "variables": dict,
                "can_modify": bool,
                "modifiable_elements": dict
            }
        """
        execution = self.get_execution(execution_id)
        if not execution:
            return {"error": "执行实例不存在"}

        workflow = execution.workflow
        current_step = execution.get_current_step()

        return {
            "execution_id": execution_id,
            "status": execution.status.value,
            "current_step": execution.current_step_idx,
            "total_steps": len(workflow.steps) if workflow else 0,
            "progress": execution.get_progress(),
            "variables": execution.variables,
            "current_step_info": {
                "step_id": current_step.step_id if current_step else None,
                "name": current_step.name if current_step else None,
                "status": current_step.status.value if current_step else None
            } if current_step else None,
            "can_modify": execution.status in [ExecutionStatus.PAUSED, ExecutionStatus.PENDING],
            "created_at": execution.created_at,
            "started_at": execution.started_at,
            "completed_at": execution.completed_at
        }

    def pause_execution(self, execution_id: str, reason: str = "") -> bool:
        """暂停执行"""
        execution = self.get_execution(execution_id)
        if not execution:
            return False

        if execution.status == ExecutionStatus.RUNNING:
            execution.status = ExecutionStatus.PAUSED
            logger.info(f"[WorkflowEngine] 执行暂停: {execution_id}, 原因: {reason}")

            # 保存检查点
            checkpoint_mgr = self._get_checkpoint_manager()
            if checkpoint_mgr:
                checkpoint_mgr.save_checkpoint(
                    task_id=execution_id,
                    checkpoint_name=f"用户暂停: {reason}"
                )
            return True
        return False

    def resume_execution(self, execution_id: str) -> bool:
        """恢复执行"""
        execution = self.get_execution(execution_id)
        if not execution:
            return False

        if execution.status == ExecutionStatus.PAUSED:
            execution.status = ExecutionStatus.RUNNING
            logger.info(f"[WorkflowEngine] 执行恢复: {execution_id}")
            return True
        return False

    def modify_execution(self, execution_id: str,
                        modifications: dict[str, Any]) -> bool:
        """
        修改执行中的工作流

        modifications: {
            "skip_steps": ["step_id", ...],
            "modify_params": {"step_id": {"param": "value"}},
            "add_steps": [{"index": 0, "step": {...}}],
            "update_variables": {"var": "value"}
        }
        """
        execution = self.get_execution(execution_id)
        if not execution:
            logger.error(f"[WorkflowEngine] 修改失败: 执行实例不存在 {execution_id}")
            return False

        if execution.status not in [ExecutionStatus.PAUSED, ExecutionStatus.PENDING]:
            logger.warning(f"[WorkflowEngine] 修改失败: 执行状态不允许修改 {execution.status}")
            return False

        with self._lock:
            # 跳过步骤
            if "skip_steps" in modifications:
                for step_id in modifications["skip_steps"]:
                    execution.skip_step(step_id)

            # 修改参数
            if "modify_params" in modifications:
                for step_id, params in modifications["modify_params"].items():
                    execution.modify_step_params(step_id, params)

            # 添加步骤
            if "add_steps" in modifications:
                for step_def in modifications["add_steps"]:
                    step = WorkflowStep.from_dict(step_def["step"])
                    execution.insert_step(step_def["index"], step)

            # 更新变量
            if "update_variables" in modifications:
                execution.variables.update(modifications["update_variables"])

        # 保存检查点
        checkpoint_mgr = self._get_checkpoint_manager()
        if checkpoint_mgr:
            checkpoint_mgr.save_checkpoint(
                task_id=execution_id,
                checkpoint_name=f"用户修改: {list(modifications.keys())}"
            )

        logger.info(f"[WorkflowEngine] 执行已修改: {execution_id}")
        return True

    def cancel_execution(self, execution_id: str) -> bool:
        """取消执行"""
        execution = self.get_execution(execution_id)
        if not execution:
            return False

        if execution.status in [ExecutionStatus.PENDING, ExecutionStatus.RUNNING,
                               ExecutionStatus.PAUSED]:
            execution.status = ExecutionStatus.CANCELLED
            logger.info(f"[WorkflowEngine] 执行取消: {execution_id}")
            return True
        return False

    async def create_execution_from_checkpoint(self,
                                               workflow_id: str,
                                               checkpoint_state: dict[str, Any],
                                               user_id: str = "default") -> Any | None:
        """从检查点状态重建工作流执行实例（Phase 7.5）

        在系统重启后，从检查点恢复工作流执行上下文。

        Args:
            workflow_id: 工作流定义ID
            checkpoint_state: 检查点状态字典
            user_id: 用户ID

        Returns:
            重建的 WorkflowExecution 实例，失败则返回 None
        """
        try:
            workflow = self.get_workflow(workflow_id)
            if not workflow:
                logger.error(f"[WorkflowEngine] 无法重建执行实例：工作流不存在 {workflow_id}")
                return None

            execution_id = checkpoint_state.get("execution_id")
            if not execution_id:
                execution_id = f"exec_{uuid.uuid4().hex[:12]}"
                logger.warning(f"[WorkflowEngine] 检查点缺少 execution_id，已生成新ID: {execution_id}")

            # 创建执行实例
            execution = WorkflowExecution(
                execution_id=execution_id,
                workflow_id=workflow_id,
                user_id=user_id,
                workflow=workflow,
                status=ExecutionStatus.PENDING
            )

            # 恢复变量
            if "variables" in checkpoint_state:
                execution.variables = {**workflow.variables, **checkpoint_state["variables"]}

            # 恢复步骤结果
            if "step_results" in checkpoint_state:
                execution.step_results = checkpoint_state["step_results"]

            # 恢复槽位ID
            if "slot_id" in checkpoint_state:
                execution.slot_id = checkpoint_state["slot_id"]

            # 恢复当前步骤索引
            current_step_id = checkpoint_state.get("current_step")
            if current_step_id and workflow.steps:
                for idx, step in enumerate(workflow.steps):
                    if step.step_id == current_step_id:
                        execution.current_step_idx = idx
                        break

            # 恢复状态（如果检查点中保存的是运行中/暂停，重置为待恢复状态）
            status_str = checkpoint_state.get("status", "pending")
            try:
                execution.status = ExecutionStatus(status_str)
            except ValueError:
                execution.status = ExecutionStatus.PENDING

            # 注册到执行表
            with self._lock:
                self._executions[execution.execution_id] = execution

            logger.info(f"[WorkflowEngine] 从检查点重建执行实例: {execution_id} "
                       f"(workflow: {workflow_id}, current_step: {execution.current_step_idx})")
            return execution

        except Exception as e:
            logger.error(f"[WorkflowEngine] 从检查点重建执行实例失败: {e}", exc_info=True)
            return None


# ═══════════════════════════════════════════════════════════════════════════════
# 全局实例
# ═══════════════════════════════════════════════════════════════════════════════

_workflow_engine = None
_engine_lock = threading.Lock()


def get_workflow_engine() -> WorkflowEngine:
    """获取工作流引擎单例"""
    global _workflow_engine
    if _workflow_engine is None:
        with _engine_lock:
            if _workflow_engine is None:
                _workflow_engine = WorkflowEngine()
    return _workflow_engine
