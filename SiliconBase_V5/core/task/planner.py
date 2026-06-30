#!/usr/bin/env python3
"""
任务规划器 - 核心实现 V2.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️ TODO (2026-05-06): 待迁移至新架构

本模块仍有以下生产调用方，暂无法删除：
- core/agent/agent_loop.py — planner.clear_plan()
- core/agent/loop_initialization.py — planner.get_plan_summary()
- core/agent/hooks/tool_hook.py — planner.update_step_status() / get_next_executable_steps() / is_plan_complete()
- core/intent/function_trigger.py — planner.create_plan() / get_plan_summary()

需在 TaskService 或等效新模块中重建规划能力后，逐步迁移上述调用方。
"""

import re
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

try:
    from core.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger('planner')


class StepStatus(Enum):
    """步骤状态枚举"""
    PENDING = "pending"     # 等待中
    READY = "ready"         # 就绪
    RUNNING = "running"     # 运行中
    COMPLETED = "completed" # 已完成
    FAILED = "failed"       # 失败
    SKIPPED = "skipped"     # 跳过


@dataclass
class PlanStep:
    """计划步骤数据类"""
    description: str
    step_id: str = field(default_factory=lambda: f"step_{uuid.uuid4().hex[:8]}")
    status: StepStatus = StepStatus.PENDING
    dependencies: list[str] = field(default_factory=list)
    estimated_time: int = 0  # 估计时间（秒）
    result: Any = None
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    # 【新增】工具调用相关
    tool_id: str | None = None  # 关联的工具ID
    tool_params: dict[str, Any] = field(default_factory=dict)  # 工具参数
    requires_confirmation: bool = False  # 是否需要用户确认
    confirmation_message: str = ""  # 确认消息

    # 【新增】关键步骤标记 - 用于智能任务完成判断
    is_critical: bool = True  # 是否为关键步骤（默认True保持兼容）
    step_category: str = "action"  # 步骤类别: check, launch, action, verify, wait, cleanup

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "step_id": self.step_id,
            "description": self.description,
            "status": self.status.value,
            "dependencies": self.dependencies,
            "estimated_time": self.estimated_time,
            "result": self.result,
            "error": self.error,
            "metadata": self.metadata,
            "tool_id": self.tool_id,
            "tool_params": self.tool_params,
            "requires_confirmation": self.requires_confirmation,
            "confirmation_message": self.confirmation_message,
            "is_critical": self.is_critical,
            "step_category": self.step_category
        }


@dataclass
class TaskPlan:
    """任务计划数据类"""
    task_id: str
    task_description: str
    steps: list[PlanStep] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    current_step_index: int = 0

    # 【新增】上下文信息
    context: dict[str, Any] = field(default_factory=dict)
    original_intent: str = ""  # 原始意图
    execution_strategy: str = "sequential"  # 执行策略：sequential/parallel/adaptive

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "task_id": self.task_id,
            "task_description": self.task_description,
            "steps": [s.to_dict() for s in self.steps],
            "created_at": self.created_at,
            "current_step_index": self.current_step_index,
            "context": self.context,
            "original_intent": self.original_intent,
            "execution_strategy": self.execution_strategy,
            "progress": self.get_progress()
        }

    def get_next_ready_step(self) -> PlanStep | None:
        """获取下一个就绪的步骤"""
        completed_ids = {s.step_id for s in self.steps if s.status == StepStatus.COMPLETED}

        for step in self.steps:
            if step.status == StepStatus.PENDING and all(dep in completed_ids for dep in step.dependencies):
                # 检查依赖
                step.status = StepStatus.READY
                return step

        return None

    def get_progress(self) -> float:
        """获取计划进度 (0-100)"""
        if not self.steps:
            return 100.0

        completed = sum(1 for s in self.steps if s.status in [StepStatus.COMPLETED, StepStatus.SKIPPED])
        return (completed / len(self.steps)) * 100.0

    def get_current_step(self) -> PlanStep | None:
        """获取当前正在执行的步骤"""
        if 0 <= self.current_step_index < len(self.steps):
            return self.steps[self.current_step_index]
        return None


class Planner:
    """
    任务规划器 V2.0

    将任务分解为可执行的步骤序列，支持工具调用集成。

    单例模式实现。
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """初始化规划器"""
        if self._initialized:
            return
        self._initialized = True

        # 计划存储: task_id -> TaskPlan
        self._plans: dict[str, TaskPlan] = {}

        # 【新增】任务模板库
        self._task_templates: dict[str, dict] = self._load_task_templates()

        # 【新增】步骤执行回调
        self._step_executor: Callable | None = None

        # 锁
        self._lock = threading.RLock()

        logger.info("[Planner] 任务规划器 V2.0 初始化完成")

    def _load_task_templates(self) -> dict[str, dict]:
        """【新增】加载任务模板库"""
        return {
            "play_music": {
                # 【修复】收紧正则：要求明确的播放/收听意图，排除纯"打开XX音乐"的应用启动场景
                "pattern": r"(播放|听).*?(音乐|歌曲|歌)",
                "steps": [
                    {"phase": "prepare", "action": "ensure_app_running", "params": {"app": "{app_name}"}},
                    {"phase": "ui", "action": "focus_app_window", "params": {"app": "{app_name}"}},
                    {"phase": "ui", "action": "find_and_click", "params": {"target": "搜索框"}},
                    {"phase": "input", "action": "input_text", "params": {"text": "{song_name}"}},
                    {"phase": "input", "action": "press_key", "params": {"key": "return"}},
                    {"phase": "wait", "action": "wait", "params": {"seconds": 1}},
                    {"phase": "ui", "action": "find_and_click", "params": {"target": "{song_name}", "fallback": "第一首歌"}}
                ]
            },
            "launch_app": {
                # 【修复】放宽正则：匹配"打开/启动/运行 + 应用名"，避免"打开网易云音乐"被误判为播放音乐
                "pattern": r"^(打开|启动|运行)\s+(.+?)(?:\s+应用|\s+软件|\s+程序)?$",
                "steps": [
                    {"phase": "check", "action": "check_app_installed", "params": {"app": "{app_name}"}, "is_critical": False, "step_category": "check"},
                    {"phase": "launch", "action": "launch_app", "params": {"app_name": "{app_name}"}, "is_critical": True, "step_category": "launch"},
                    {"phase": "verify", "action": "verify_window_appears", "params": {"app_name": "{app_name}", "timeout": 10}, "is_critical": False, "step_category": "verify"}
                ]
            },
            "search_and_open": {
                "pattern": r"(搜索|查找).*?(然后|接着|再).*?(打开|点击)",
                "steps": [
                    {"phase": "search", "action": "find_screen_element", "params": {"description": "{search_target}"}},
                    {"phase": "click", "action": "mouse_click", "params": {"element": "$prev_result"}},
                    {"phase": "verify", "action": "verify_result", "params": {"expected": "{expected_result}"}}
                ]
            },
            # ═══════════════════════════════════════════════════
            # 【BTC交易】量化交易专用模板
            # ═══════════════════════════════════════════════════
            "btc_autopilot": {
                "pattern": r"(BTC|btc|比特币|量化|交易|策略|自动).*?(交易|量化|自动|策略|启动|运行)",
                "steps": [
                    {
                        "phase": "analysis",
                        "action": "btc_market_overview",
                        "params": {"symbol": "{symbol|BTC}"},
                        "is_critical": False,
                        "step_category": "check"
                    },
                    {
                        "phase": "strategy",
                        "action": "btc_strategy_selector",
                        "params": {
                            "symbol": "{symbol|BTC}",
                            "risk_tolerance": "{risk|medium}",
                            "budget": "{budget|1000}"
                        },
                        "is_critical": True,
                        "step_category": "planning"
                    },
                    {
                        "phase": "risk",
                        "action": "btc_risk_assessment",
                        "params": {
                            "symbol": "{symbol|BTC}",
                            "account_equity": "{budget|1000}"
                        },
                        "is_critical": True,
                        "step_category": "check"
                    },
                    {
                        "phase": "confirm",
                        "action": "btc_confirm_trade",
                        "params": {},
                        "is_critical": True,
                        "step_category": "verify",
                        "requires_confirmation": True,
                        "confirmation_message": "请确认BTC自动交易计划：标的={symbol} 预算={budget} 时长={duration}分钟"
                    },
                    {
                        "phase": "launch",
                        "action": "btc_launch_autopilot",
                        "params": {
                            "symbol": "{symbol|BTC}",
                            "budget": "{budget|1000}",
                            "duration_minutes": "{duration|60}",
                            "strategy": "{strategy|stage46_aggressive}"
                        },
                        "is_critical": True,
                        "step_category": "action",
                        "timeout": 60
                    },
                    {
                        "phase": "monitor",
                        "action": "btc_monitor_trading",
                        "params": {"process_id": "$launch.process_id"},
                        "is_critical": False,
                        "step_category": "check",
                        "execution_mode": "parallel",
                        "timeout": 300
                    },
                    {
                        "phase": "report",
                        "action": "btc_generate_report",
                        "params": {"process_id": "$launch.process_id"},
                        "is_critical": False,
                        "step_category": "verify"
                    }
                ]
            },
            "btc_quick_trade": {
                "pattern": r"(买入|卖出|做多|做空|buy|sell).*?(BTC|ETH|SOL|比特币|以太坊|索拉纳)",
                "steps": [
                    {
                        "phase": "check_price",
                        "action": "btc_price_query",
                        "params": {"symbol": "{symbol}"}
                    },
                    {
                        "phase": "risk_check",
                        "action": "btc_risk_assessment",
                        "params": {"symbol": "{symbol}"}
                    },
                    {
                        "phase": "confirm",
                        "action": "btc_confirm_trade",
                        "params": {},
                        "requires_confirmation": True,
                        "confirmation_message": "确认{side} {amount} USDT的{symbol}?"
                    },
                    {
                        "phase": "execute",
                        "action": "btc_execute_trade",
                        "params": {
                            "symbol": "{symbol}",
                            "side": "{side}",
                            "amount": "{amount}"
                        },
                        "timeout": 30
                    }
                ]
            }
        }

    # ═══════════════════════════════════════════════════════════════
    # 【新增】agent_loop 期望的方法
    # ═══════════════════════════════════════════════════════════════

    def create_plan(self, goal: str, context: dict[str, Any] = None) -> str:
        """
        【新增】创建计划（agent_loop期望的方法）

        Args:
            goal: 任务目标
            context: 上下文信息（可包含visual_description等）

        Returns:
            计划ID
        """
        context = context or {}
        plan = self.plan_task(goal, context)

        # 保存额外上下文
        with self._lock:
            if plan.task_id in self._plans:
                self._plans[plan.task_id].context = context
                self._plans[plan.task_id].original_intent = goal

        logger.info(f"[Planner] 创建计划: {goal} -> {plan.task_id}")
        return plan.task_id

    def get_plan_summary(self, task_id: str) -> dict[str, Any] | None:
        """
        【新增】获取计划摘要（被多处调用）

        Args:
            task_id: 任务ID

        Returns:
            计划摘要字典
        """
        plan = self._plans.get(task_id)
        if not plan:
            return None

        completed = sum(1 for s in plan.steps if s.status == StepStatus.COMPLETED)
        failed = sum(1 for s in plan.steps if s.status == StepStatus.FAILED)
        pending = sum(1 for s in plan.steps if s.status == StepStatus.PENDING)

        return {
            "goal": plan.task_description,
            "task_id": task_id,
            "total_steps": len(plan.steps),
            "completed_steps": completed,
            "failed_steps": failed,
            "pending_steps": pending,
            "progress": plan.get_progress(),
            "current_step": plan.current_step_index,
            "is_complete": plan.get_progress() >= 100,
            "has_failures": failed > 0
        }

    def get_plan_steps(self, task_id: str) -> list[dict[str, Any]]:
        """
        【新增】获取计划步骤列表（被多处调用）

        Args:
            task_id: 任务ID

        Returns:
            步骤字典列表
        """
        plan = self._plans.get(task_id)
        if not plan:
            return []
        return [step.to_dict() for step in plan.steps]

    def clear_plan(self, task_id: str) -> bool:
        """
        【新增】清理计划（被多处调用）

        Args:
            task_id: 任务ID

        Returns:
            是否成功
        """
        with self._lock:
            if task_id in self._plans:
                del self._plans[task_id]
                logger.info(f"[Planner] 清理计划: {task_id}")
                return True
        return False

    def get_next_executable_steps(self, task_id: str, count: int = 1) -> list[dict[str, Any]]:
        """
        【新增】获取下一个可执行的步骤（被多处调用）

        Args:
            task_id: 任务ID
            count: 获取步骤数量

        Returns:
            可执行步骤列表
        """
        plan = self._plans.get(task_id)
        if not plan:
            return []

        ready_steps = []
        completed_ids = {s.step_id for s in plan.steps if s.status == StepStatus.COMPLETED}

        for step in plan.steps:
            if step.status in [StepStatus.PENDING, StepStatus.READY] and all(dep in completed_ids for dep in step.dependencies):
                # 检查依赖是否满足
                step.status = StepStatus.READY
                ready_steps.append(step.to_dict())
                if len(ready_steps) >= count:
                    break

        return ready_steps

    def advance_step(self, task_id: str, step_id: str = None) -> dict[str, Any] | None:
        """
        【新增】推进到下一步

        Args:
            task_id: 任务ID
            step_id: 当前步骤ID（可选，默认推进当前步骤）

        Returns:
            下一个步骤
        """
        with self._lock:
            plan = self._plans.get(task_id)
            if not plan:
                return None

            if step_id:
                # 找到指定步骤并标记完成
                for i, step in enumerate(plan.steps):
                    if step.step_id == step_id:
                        step.status = StepStatus.COMPLETED
                        plan.current_step_index = i + 1
                        break
            else:
                # 推进当前步骤
                current = plan.get_current_step()
                if current:
                    current.status = StepStatus.COMPLETED
                    plan.current_step_index += 1

            # 获取下一个就绪步骤
            next_step = plan.get_next_ready_step()
            return next_step.to_dict() if next_step else None

    def mark_step_executing(self, task_id: str, step_id: str) -> bool:
        """
        【新增】标记步骤为执行中

        Args:
            task_id: 任务ID
            step_id: 步骤ID

        Returns:
            是否成功
        """
        with self._lock:
            plan = self._plans.get(task_id)
            if not plan:
                return False

            for step in plan.steps:
                if step.step_id == step_id:
                    step.status = StepStatus.RUNNING
                    return True
            return False

    def mark_step_result(self, task_id: str, step_id: str,
                         success: bool, result: Any = None, error: str = "") -> bool:
        """
        【新增】标记步骤执行结果

        Args:
            task_id: 任务ID
            step_id: 步骤ID
            success: 是否成功
            result: 执行结果
            error: 错误信息

        Returns:
            是否成功
        """
        with self._lock:
            plan = self._plans.get(task_id)
            if not plan:
                return False

            for step in plan.steps:
                if step.step_id == step_id:
                    step.status = StepStatus.COMPLETED if success else StepStatus.FAILED
                    step.result = result
                    step.error = error
                    logger.info(f"[Planner] 步骤结果: {step_id} -> {'成功' if success else '失败'}")
                    return True
            return False

    def get_step_by_id(self, task_id: str, step_id: str) -> dict[str, Any] | None:
        """
        【新增】获取指定步骤

        Args:
            task_id: 任务ID
            step_id: 步骤ID

        Returns:
            步骤字典
        """
        plan = self._plans.get(task_id)
        if not plan:
            return None

        for step in plan.steps:
            if step.step_id == step_id:
                return step.to_dict()
        return None

    # ═══════════════════════════════════════════════════════════════
    # 原有方法（向后兼容）
    # ═══════════════════════════════════════════════════════════════

    def plan_task(self, task_description: str, context: dict[str, Any] = None) -> TaskPlan:
        """
        为任务创建计划（增强版）

        Args:
            task_description: 任务描述
            context: 上下文信息（可包含visual_description）

        Returns:
            任务计划
        """
        task_id = f"task_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        context = context or {}

        # 【增强】使用智能分解（优先Procedure Learning）
        steps = self._decompose_task_intelligent(task_description, context, task_id)

        plan = TaskPlan(
            task_id=task_id,
            task_description=task_description,
            steps=steps,
            context=context,
            original_intent=task_description
        )

        with self._lock:
            self._plans[task_id] = plan

        logger.info(f"[Planner] 创建计划: {task_description} ({len(steps)} 步骤)")
        return plan

    async def plan_task_async(self, task_description: str, context: dict[str, Any] = None) -> dict[str, Any]:
        """异步版本的任务规划（为AgentLoop提供异步接口）"""
        plan = self.plan_task(task_description=task_description, context=context)
        return plan.to_dict()

    def _decompose_task(self, task_description: str, context: dict[str, Any] = None) -> list[PlanStep]:
        """
        【保留】基础任务分解（向后兼容）
        """
        return self._decompose_task_enhanced(task_description, context)

    def _decompose_task_intelligent(self, task_description: str, context: dict[str, Any] = None, task_id: str = None) -> list[PlanStep]:
        """
        【新增】智能任务分解 - 优先使用Procedure Learning

        1. 先查 Procedure Learning（已有学习流程）
        2. 没有再动态分解（基于实际可用工具）
        3. 保存新生成的流程到 Procedure Learning

        Args:
            task_description: 任务描述
            context: 上下文信息
            task_id: 任务ID

        Returns:
            PlanStep列表
        """
        context = context or {}

        # 1. 尝试获取学习到的流程
        try:
            from core.evolution.procedure_learning_integration import get_procedure_learning_integration

            pl = get_procedure_learning_integration()

            if pl and pl.is_available():
                # 使用任务描述查找学习到的流程
                # 注意：需要使用session_id来查找，这里用task_id作为session_id
                session_id = task_id or f"session_{int(time.time())}_{uuid.uuid4().hex[:6]}"
                learned_steps = pl.get_learned_procedure_steps(session_id)

                if learned_steps and len(learned_steps) > 0:
                    logger.info(f"[Planner] 使用学习到的流程: {len(learned_steps)} 步骤")
                    steps = self._convert_learned_to_plan_steps(learned_steps)
                    # 标记来源为学习到的流程
                    for step in steps:
                        step.metadata['source'] = 'learned'
                    return steps
        except Exception as e:
            logger.debug(f"[Planner] Procedure Learning不可用，降级到动态分解: {e}")

        # 2. 没有学习流程，使用动态分解
        logger.info("[Planner] 无学习流程，使用动态分解")
        steps = self._decompose_task_enhanced(task_description, context)

        # 标记来源为动态生成
        for step in steps:
            if 'source' not in step.metadata:
                step.metadata['source'] = 'generated'

        # 3. 【可选】保存到 Procedure Learning（供下次使用）
        # 注意：这里可以保存生成的步骤，但需要在执行成功后由外部调用保存
        # 目前仅记录日志，实际保存由 agent_loop 或其他组件在执行成功后触发

        return steps

    def _get_available_tools_description(self) -> list[dict[str, Any]]:
        """
        【新增】获取可用工具列表描述

        Returns:
            可用工具列表，每个工具包含id、name、description等信息
        """
        try:
            from core.tool.tool_manager import tool_manager

            tools = tool_manager.list_tools()
            # 格式化为简洁的描述格式
            tool_descriptions = []
            for tool in tools:
                if isinstance(tool, dict):
                    tool_descriptions.append({
                        "tool_id": tool.get("id") or tool.get("name"),
                        "name": tool.get("name", ""),
                        "description": tool.get("description", ""),
                        "parameters": tool.get("parameters", [])
                    })
                else:
                    # 处理Tool对象
                    tool_descriptions.append({
                        "tool_id": getattr(tool, 'id', getattr(tool, 'name', str(tool))),
                        "name": getattr(tool, 'name', ""),
                        "description": getattr(tool, 'description', ""),
                        "parameters": getattr(tool, 'parameters', [])
                    })
            return tool_descriptions
        except Exception as e:
            logger.debug(f"[Planner] 获取工具列表失败: {e}")
            # 返回默认工具列表作为fallback
            return [
                {"tool_id": "launch_app", "name": "启动应用", "description": "启动指定应用程序"},
                {"tool_id": "mouse_click", "name": "鼠标点击", "description": "在指定位置点击鼠标"},
                {"tool_id": "keyboard_input", "name": "键盘输入", "description": "输入文本或按键"},
                {"tool_id": "find_screen_element", "name": "查找屏幕元素", "description": "在屏幕上查找指定元素"},
                {"tool_id": "web_search", "name": "网页搜索", "description": "搜索网页信息"},
                {"tool_id": "screenshot", "name": "截图", "description": "截取屏幕图像"},
                {"tool_id": "file_manager", "name": "文件管理", "description": "文件读写操作"},
            ]

    def _convert_learned_to_plan_steps(self, learned_steps: list[dict]) -> list[PlanStep]:
        """
        【新增】将学习到的流程步骤转换为 PlanStep 对象

        Args:
            learned_steps: 从Procedure Learning获取的步骤列表

        Returns:
            PlanStep对象列表
        """
        steps = []
        prev_step_id = None

        for i, step_data in enumerate(learned_steps):
            # 提取步骤信息（支持多种字段名）
            description = step_data.get('description', step_data.get('desc', f'步骤{i+1}'))
            tool_id = step_data.get('tool_id') or step_data.get('tool_name')
            tool_params = step_data.get('tool_params') or step_data.get('params', {})

            # 创建PlanStep
            step = PlanStep(
                description=description,
                tool_id=tool_id,
                tool_params=tool_params if isinstance(tool_params, dict) else {},
                metadata={
                    'source': 'learned',
                    'step_number': step_data.get('step_number', i + 1),
                    'original_data': step_data
                }
            )

            # 设置顺序依赖（除第一步外都依赖前一步）
            if prev_step_id:
                step.dependencies = [prev_step_id]

            steps.append(step)
            prev_step_id = step.step_id

        logger.debug(f"[Planner] 转换了 {len(steps)} 个学习步骤到 PlanStep")
        return steps

    def save_learned_procedure(self, task_description: str, steps: list[PlanStep], success: bool = True) -> bool:
        """
        【新增】保存执行成功的流程到 Procedure Learning

        由外部组件（如agent_loop）在任务成功完成后调用

        Args:
            task_description: 任务描述
            steps: 执行的步骤列表
            success: 是否执行成功

        Returns:
            是否保存成功
        """
        try:
            from core.evolution.procedure_learning_integration import get_procedure_learning_integration

            pl = get_procedure_learning_integration()
            if not pl or not pl.is_available():
                logger.debug("[Planner] Procedure Learning不可用，跳过保存")
                return False

            # 转换PlanStep为学习系统格式
            procedure_steps = []
            for i, step in enumerate(steps):
                procedure_steps.append({
                    "step_number": i + 1,
                    "description": step.description,
                    "tool_name": step.tool_id,
                    "tool_params": step.tool_params,
                    "success": step.status == StepStatus.COMPLETED
                })

            # 保存到Procedure Learning
            # 注意：这里调用procedure_library直接保存，绕过coordinator的演示录制流程
            if hasattr(pl, '_procedure_library') and pl._procedure_library:
                procedure = pl._procedure_library.create_procedure(
                    name=task_description[:50],  # 限制长度
                    intent=task_description,
                    steps=procedure_steps
                )
                logger.info(f"[Planner] 已保存学习流程: {procedure.procedure_id if procedure else 'unknown'}")
                return procedure is not None

            return False

        except Exception as e:
            logger.debug(f"[Planner] 保存学习流程失败: {e}")
            return False

    def _decompose_task_enhanced(self, task_description: str, context: dict[str, Any] = None) -> list[PlanStep]:
        """
        【增强】智能任务分解

        基于模板匹配和上下文进行任务分解
        """
        steps = []
        context = context or {}
        task_lower = task_description.lower()
        context.get("visual_description", "")

        # 尝试匹配任务模板
        for template_name, template in self._task_templates.items():
            pattern = template.get("pattern", "")
            if pattern and re.search(pattern, task_lower):
                logger.info(f"[Planner] 匹配任务模板: {template_name}")
                steps = self._build_steps_from_template(template, task_description, context)
                if steps:
                    return steps

        # 基于关键词的智能分解
        # 【修复】优先判断明确的"打开/启动/运行"意图，避免包含"音乐"二字的应用启动指令被误判为播放音乐
        if any(kw in task_lower for kw in ["打开", "启动", "运行"]):
            # 【修复】"打开音乐/歌曲/歌"且没有明确应用名时，优先走播放音乐流程
            music_kw = ["音乐", "歌曲", "歌"]
            has_music_kw = any(kw in task_lower for kw in music_kw)
            app_name = self._extract_app_name(task_description)
            if has_music_kw and app_name == "应用":
                steps = self._build_play_music_steps(task_description, context)
            # 【修复】复合命令（打开+后续动作）不走简单的启动应用，避免计划退化
            elif any(kw in task_lower for kw in ["播放", "发送", "搜索", "查找", "输入", "填写", "点击"]):
                steps = self._build_generic_steps(task_description, context)
            else:
                steps = self._build_launch_app_steps(task_description, context)
        elif any(kw in task_lower for kw in ["播放", "听", "音乐", "歌曲", "歌"]):
            steps = self._build_play_music_steps(task_description, context)
        elif any(kw in task_lower for kw in ["搜索", "查找", "查询"]):
            steps = self._build_search_steps(task_description, context)
        elif any(kw in task_lower for kw in ["点击", "输入", "填写", "选择"]):
            steps = self._build_ui_interaction_steps(task_description, context)
        elif any(kw in task_lower for kw in ["整理", "处理", "修改", "编辑"]):
            steps = self._build_file_processing_steps(task_description, context)
        else:
            # 通用步骤
            steps = self._build_generic_steps(task_description, context)

        return steps

    def _build_steps_from_template(self, template: dict, task_description: str, context: dict) -> list[PlanStep]:
        """【新增】从模板构建步骤"""
        steps = []
        template_steps = template.get("steps", [])

        # 提取参数
        params = self._extract_params(task_description, context)

        prev_step_id = None
        for tmpl_step in template_steps:
            step = PlanStep(
                description=tmpl_step.get("action", "执行操作"),
                metadata={
                    "phase": tmpl_step.get("phase", "execute"),
                    "action": tmpl_step.get("action"),
                    "template": True
                },
                is_critical=tmpl_step.get("is_critical", True),  # 【新增】传递关键步骤标记
                step_category=tmpl_step.get("step_category", "action")  # 【新增】传递步骤类别
            )

            # 设置工具ID
            action = tmpl_step.get("action", "")
            if action == "launch_app":
                step.tool_id = "launch_app"
                step.tool_params = {"app_name": params.get("app_name", "应用")}
            elif action == "check_app_installed":
                step.tool_id = "check_app_installed"
                step.tool_params = {"app": tmpl_step.get("params", {}).get("app", params.get("app_name", "应用"))}
            elif action == "verify_window_appears":
                step.tool_id = "window_get"
                step.tool_params = {
                    "title": tmpl_step.get("params", {}).get("app_name", params.get("app_name", "应用")),
                    "timeout": tmpl_step.get("params", {}).get("timeout", 10)
                }
            elif action == "find_and_click":
                step.tool_id = "find_screen_element"
                step.tool_params = {"description": tmpl_step.get("params", {}).get("target", "目标")}
            elif action == "input_text":
                step.tool_id = "keyboard_input"
                step.tool_params = {"text": params.get("text", "")}
            elif action == "press_key":
                step.tool_id = "keyboard_input"
                step.tool_params = {"key": tmpl_step.get("params", {}).get("key", "return")}
            elif action == "wait":
                step.metadata["wait_seconds"] = tmpl_step.get("params", {}).get("seconds", 1)

            # 设置依赖
            if prev_step_id:
                step.dependencies = [prev_step_id]

            steps.append(step)
            prev_step_id = step.step_id

        return steps

    def _build_play_music_steps(self, task_description: str, context: dict) -> list[PlanStep]:
        """【新增】构建播放音乐的步骤"""
        steps = []

        # 提取歌曲名和应用
        song_name = self._extract_song_name(task_description)
        app_name = context.get("preferred_music_app", "网易云音乐")

        # 步骤1: 检查应用
        step1 = PlanStep(
            description=f"检查{app_name}是否可用",
            metadata={"phase": "check", "app": app_name}
        )
        steps.append(step1)

        # 步骤2: 启动应用
        step2 = PlanStep(
            description=f"启动{app_name}",
            dependencies=[step1.step_id],
            tool_id="launch_app",
            tool_params={"app_name": app_name},
            metadata={"phase": "launch"}
        )
        steps.append(step2)

        # 步骤3: 等待窗口
        step3 = PlanStep(
            description=f"等待{app_name}窗口出现",
            dependencies=[step2.step_id],
            metadata={"phase": "wait", "wait_seconds": 3}
        )
        steps.append(step3)

        # 步骤4: 查找搜索框
        step4 = PlanStep(
            description="查找搜索框",
            dependencies=[step3.step_id],
            tool_id="find_screen_element",
            tool_params={"description": "搜索框"},
            metadata={"phase": "ui"}
        )
        steps.append(step4)

        # 步骤5: 点击搜索框
        step5 = PlanStep(
            description="点击搜索框",
            dependencies=[step4.step_id],
            tool_id="mouse_click",
            tool_params={"element": "$find_screen_element_result"},
            metadata={"phase": "ui"}
        )
        steps.append(step5)

        # 步骤6: 输入歌曲名
        step6 = PlanStep(
            description=f"输入歌曲名'{song_name}'",
            dependencies=[step5.step_id],
            tool_id="keyboard_input",
            tool_params={"text": song_name},
            metadata={"phase": "input"}
        )
        steps.append(step6)

        # 步骤7: 按回车搜索
        step7 = PlanStep(
            description="按下回车搜索",
            dependencies=[step6.step_id],
            tool_id="keyboard_input",
            tool_params={"key": "return"},
            metadata={"phase": "input"}
        )
        steps.append(step7)

        # 步骤8: 等待结果
        step8 = PlanStep(
            description="等待搜索结果",
            dependencies=[step7.step_id],
            metadata={"phase": "wait", "wait_seconds": 2}
        )
        steps.append(step8)

        # 步骤9: 点击歌曲
        step9 = PlanStep(
            description=f"点击歌曲'{song_name}'",
            dependencies=[step8.step_id],
            tool_id="find_screen_element",
            tool_params={"description": song_name},
            metadata={"phase": "ui", "fallback": "点击第一首结果"}
        )
        steps.append(step9)

        return steps

    def _build_launch_app_steps(self, task_description: str, context: dict) -> list[PlanStep]:
        """【新增】构建启动应用的步骤"""
        steps = []

        # 提取应用名
        app_name = self._extract_app_name(task_description)

        # 步骤1: 启动应用
        step1 = PlanStep(
            description=f"启动{app_name}",
            tool_id="launch_app",
            tool_params={"app_name": app_name},
            metadata={"phase": "launch"}
        )
        steps.append(step1)

        # 步骤2: 验证窗口
        step2 = PlanStep(
            description=f"验证{app_name}窗口出现",
            dependencies=[step1.step_id],
            tool_id="window_get",
            tool_params={"title": app_name},
            metadata={"phase": "verify", "timeout": 10}
        )
        steps.append(step2)

        return steps

    def _build_search_steps(self, task_description: str, context: dict) -> list[PlanStep]:
        """【新增】构建搜索任务的步骤"""
        steps = []
        search_target = self._extract_search_target(task_description)

        step1 = PlanStep(
            description=f"搜索'{search_target}'",
            tool_id="web_search",
            tool_params={"query": search_target},
            metadata={"phase": "search"}
        )
        steps.append(step1)

        return steps

    def _build_ui_interaction_steps(self, task_description: str, context: dict) -> list[PlanStep]:
        """【新增】构建UI交互的步骤"""
        steps = []

        # 提取目标元素
        target = self._extract_ui_target(task_description)

        step1 = PlanStep(
            description=f"查找元素'{target}'",
            tool_id="find_screen_element",
            tool_params={"description": target},
            metadata={"phase": "ui"}
        )
        steps.append(step1)

        step2 = PlanStep(
            description=f"点击元素'{target}'",
            dependencies=[step1.step_id],
            tool_id="mouse_click",
            tool_params={"element": "$find_screen_element_result"},
            metadata={"phase": "ui"}
        )
        steps.append(step2)

        return steps

    def _build_file_processing_steps(self, task_description: str, context: dict) -> list[PlanStep]:
        """【新增】构建文件处理步骤"""
        steps = []

        step1 = PlanStep(
            description="分析文件需求",
            metadata={"phase": "analyze"}
        )
        steps.append(step1)

        step2 = PlanStep(
            description="查找目标文件",
            dependencies=[step1.step_id],
            tool_id="file_manager",
            tool_params={"action": "list"},
            metadata={"phase": "search"}
        )
        steps.append(step2)

        step3 = PlanStep(
            description="执行文件操作",
            dependencies=[step2.step_id],
            metadata={"phase": "execute"}
        )
        steps.append(step3)

        return steps

    def _build_generic_steps(self, task_description: str, context: dict) -> list[PlanStep]:
        """【新增】构建通用步骤"""
        steps = []

        step1 = PlanStep(
            description="分析任务需求",
            metadata={"phase": "analyze"}
        )
        steps.append(step1)

        step2 = PlanStep(
            description="制定执行方案",
            dependencies=[step1.step_id],
            metadata={"phase": "plan"}
        )
        steps.append(step2)

        step3 = PlanStep(
            description="执行主要操作",
            dependencies=[step2.step_id],
            metadata={"phase": "execute"}
        )
        steps.append(step3)

        step4 = PlanStep(
            description="验证执行结果",
            dependencies=[step3.step_id],
            metadata={"phase": "verify"}
        )
        steps.append(step4)

        return steps

    def _extract_params(self, task_description: str, context: dict) -> dict[str, Any]:
        """【新增】提取任务参数"""
        params = {
            "app_name": self._extract_app_name(task_description),
            "song_name": self._extract_song_name(task_description),
            "text": self._extract_text_input(task_description),
            "search_target": self._extract_search_target(task_description)
        }

        # 合并上下文参数
        params.update(context.get("params", {}))
        return params

    def _extract_app_name(self, text: str) -> str:
        """【新增】提取应用名"""
        # 常见应用别名映射
        app_aliases = {
            "网易云": "网易云音乐",
            "网易云音乐": "网易云音乐",
            "cloudmusic": "网易云音乐",
            "qq音乐": "QQ音乐",
            "qq": "QQ",
            "微信": "微信",
            "wechat": "微信",
            "浏览器": "浏览器",
            "chrome": "Chrome",
            "edge": "Edge",
            "记事本": "记事本",
            "notepad": "记事本",
            "计算器": "计算器",
            "calc": "计算器"
        }

        text_lower = text.lower()

        # 尝试匹配别名
        for alias, real_name in app_aliases.items():
            if alias in text_lower:
                return real_name

        # 通用提取：在"打开/启动"后面的词（支持空格分隔的多词英文名）
        match = re.search(r"(?:打开|启动|运行)\s*(.+?)(?:\s+应用|\s+软件|\s+程序|，|。|,|;|；|$)", text)
        if match:
            return match.group(1).strip()

        return "应用"

    def _extract_song_name(self, text: str) -> str:
        """【新增】提取歌曲名"""
        # 匹配"播放XXX"、"听XXX歌"等模式
        patterns = [
            r"播放\s*['\"]?(.+?)['\"]?\s*(?:这首歌|的歌|歌)?",
            r"听\s*['\"]?(.+?)['\"]?\s*(?:这首歌|的歌|歌)?",
            r"打开\s*['\"]?(.+?)['\"]?\s*来听",
            r"放\s*['\"]?(.+?)['\"]?\s*(?:这首歌|的歌|歌)?"
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                song = match.group(1).strip()
                # 移除常见后缀
                for suffix in ["这首歌", "的歌", "歌", "吧", "嘛"]:
                    if song.endswith(suffix):
                        song = song[:-len(suffix)].strip()
                return song

        return ""

    def _extract_text_input(self, text: str) -> str:
        """【新增】提取输入文本"""
        # 匹配"输入XXX"、"填写XXX"等模式
        patterns = [
            r"输入\s*['\"]?(.+?)['\"]?",
            r"填写\s*['\"]?(.+?)['\"]?",
            r"写入\s*['\"]?(.+?)['\"]?"
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1).strip()

        return ""

    def _extract_search_target(self, text: str) -> str:
        """【新增】提取搜索目标"""
        patterns = [
            r"搜索\s*['\"]?(.+?)['\"]?",
            r"查找\s*['\"]?(.+?)['\"]?",
            r"查询\s*['\"]?(.+?)['\"]?"
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1).strip()

        return ""

    def _extract_ui_target(self, text: str) -> str:
        """【新增】提取UI目标"""
        patterns = [
            r"点击\s*['\"]?(.+?)['\"]?",
            r"选择\s*['\"]?(.+?)['\"]?",
            r"找到\s*['\"]?(.+?)['\"]?"
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1).strip()

        return "目标"

    # ═══════════════════════════════════════════════════════════════
    # 原有方法（向后兼容）
    # ═══════════════════════════════════════════════════════════════

    def get_plan(self, task_id: str) -> TaskPlan | None:
        """获取计划（原有方法）"""
        return self._plans.get(task_id)

    def update_step_status(self, task_id: str, step_id: str, status: StepStatus,
                          result: Any = None, error: str = "") -> bool:
        """
        更新步骤状态（原有方法）

        支持通过 step_id（字符串）或 step_index（整数）更新
        """
        with self._lock:
            plan = self._plans.get(task_id)
            if not plan:
                return False

            # 支持按索引更新（整数）
            if isinstance(step_id, int):
                if 0 <= step_id < len(plan.steps):
                    step = plan.steps[step_id]
                    step.status = status
                    step.result = result
                    step.error = error
                    logger.debug(f"[Planner] 步骤状态更新: 索引{step_id} -> {status.value}")
                    return True
                return False

            # 按 step_id 更新（字符串）
            for step in plan.steps:
                if step.step_id == step_id:
                    step.status = status
                    step.result = result
                    step.error = error
                    logger.debug(f"[Planner] 步骤状态更新: {step_id} -> {status.value}")
                    return True

            return False

    def is_plan_complete(self, task_id: str) -> bool:
        """检查计划是否完成（原有方法）"""
        plan = self._plans.get(task_id)
        if not plan:
            return False

        return all(s.status in [StepStatus.COMPLETED, StepStatus.SKIPPED] for s in plan.steps)

    def get_stats(self) -> dict[str, int]:
        """获取统计信息（原有方法）"""
        return {
            "total_plans": len(self._plans)
        }

    def clear(self):
        """清空所有计划（原有方法）"""
        with self._lock:
            self._plans.clear()
            logger.info("[Planner] 所有计划已清空")


# ═══════════════════════════════════════════════════════════════
# 计划推进（从 agent_loop.py 抽取）
# ═══════════════════════════════════════════════════════════════

def advance_plan(working_memory: Any, result: dict[str, Any]) -> None:
    """【已废弃】工具执行后推进计划状态。

    逻辑已迁移到 core.agent.hooks.tool_hook.ToolHook.after_step_async()。
    保留此函数仅作向后兼容，新代码不应调用。
    """
    import warnings
    warnings.warn(
        "advance_plan() is deprecated. Plan advancement is now handled by ToolHook.after_step_async().",
        DeprecationWarning,
        stacklevel=2
    )
    # [Planner] 更新步骤状态并获取下一步
    try:
        planner = get_planner()
        if hasattr(working_memory, 'ai_plan_id') and result.get("success"):
            current_step_idx = getattr(working_memory, 'current_step_index', 0)
            planner.update_step_status(
                working_memory.ai_plan_id,
                current_step_idx,
                StepStatus.COMPLETED,
                result=result
            )
            logger.info(f"[Planner] 步骤 {current_step_idx} 标记为完成")

            next_steps = planner.get_next_executable_steps(working_memory.ai_plan_id)
            if next_steps:
                logger.info(f"[Planner] 下一步可执行: {next_steps[0].description}")
            elif planner.is_plan_complete(working_memory.ai_plan_id):
                logger.info("[Planner] 计划全部完成")
        elif hasattr(working_memory, 'ai_plan_id') and not result.get("success"):
            current_step_idx = getattr(working_memory, 'current_step_index', 0)
            planner.update_step_status(
                working_memory.ai_plan_id,
                current_step_idx,
                StepStatus.FAILED,
                error=result.get('user_message', '执行失败')
            )
            logger.warning(f"[Planner] 步骤 {current_step_idx} 标记为失败")
            working_memory.append({
                "role": "system",
                "content": f"步骤{current_step_idx+1}执行失败，请尝试其他方法完成该步骤。"
            })
    except Exception as e:
        logger.warning(f"[Planner] 步骤状态更新失败: {e}")

    # [连接修复] AI设计的计划推进
    if hasattr(working_memory, 'ai_plan') and working_memory.ai_plan:
        try:
            plan = working_memory.ai_plan
            current_step = plan.get("current_step", 0)
            steps = plan.get("steps", [])
            plan["current_step"] = current_step + 1
            next_step_idx = plan["current_step"]
            logger.info(f"[AgentLoop] AI计划步骤 {current_step+1}/{len(steps)} 完成")

            if next_step_idx < len(steps):
                next_step = steps[next_step_idx]
                step_desc = next_step.get("description", f"步骤{next_step_idx+1}")
                logger.info(f"[AgentLoop] 提示AI执行计划第{next_step_idx+1}步: {step_desc}")
                working_memory.append({
                    "role": "system",
                    "content": f"【计划执行】第{next_step_idx+1}步共{len(steps)}步: {step_desc}。请输出工具调用执行此步骤。"
                })
            else:
                logger.info(f"[AgentLoop] AI计划全部完成，共 {len(steps)} 步")
                working_memory.append({
                    "role": "system",
                    "content": f"【计划完成】所有{len(steps)}个步骤已执行完毕，请返回 FINAL_ANSWER 总结结果。"
                })
                working_memory.ai_plan = None
        except Exception as e:
            logger.warning(f"[AgentLoop] AI计划推进失败: {e}")


# ═══════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════

def get_planner() -> Planner:
    """获取规划器实例"""
    return Planner()


__all__ = [
    'Planner',
    'get_planner',
    'StepStatus',
    'PlanStep',
    'TaskPlan',
    'advance_plan',
]
