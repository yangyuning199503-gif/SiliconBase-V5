#!/usr/bin/env python3
"""
子代理运行时
"""

import asyncio
import time
import uuid
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from core.logger import logger
from core.subagent.config import SubAgentConfig

# 【P1修复】导入实时干预系统
try:
    from core.agent.realtime_intervention import ExecutionAdaptation, check_and_apply_intervention
    INTERVENTION_AVAILABLE = True
except ImportError:
    INTERVENTION_AVAILABLE = False
    logger.warning("[SubAgentRuntime] 实时干预系统不可用，子代理将在无干预检查模式下运行")

# 【Week 4】导入智能干预检测器
try:
    from core.agent.smart_intervention_detector import smart_intervention_detector
    SMART_INTERVENTION_AVAILABLE = True
except ImportError:
    SMART_INTERVENTION_AVAILABLE = False
    logger.warning("[SubAgentRuntime] 智能干预检测器不可用")


class SubAgentStatus(Enum):
    """子代理状态"""
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"      # 【Week 1】暂停状态（支持前端干预）
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"  # 【P3修复】重试中状态


class ErrorCategory(Enum):
    """
    【P3修复】错误分类枚举

    用于区分可恢复和不可恢复的错误，指导重试策略
    """
    # 可恢复错误（可以重试）
    NETWORK_ERROR = "network_error"           # 网络连接问题
    API_RATE_LIMIT = "api_rate_limit"         # API限流
    API_TIMEOUT = "api_timeout"               # API超时
    SERVICE_UNAVAILABLE = "service_unavailable"  # 服务暂时不可用
    TEMPORARY_ERROR = "temporary_error"       # 临时性错误

    # 不可恢复错误（不需要重试）
    INVALID_INPUT = "invalid_input"           # 输入无效
    PERMISSION_DENIED = "permission_denied"   # 权限不足
    NOT_FOUND = "not_found"                   # 资源不存在
    VALIDATION_ERROR = "validation_error"     # 验证失败
    CONFIGURATION_ERROR = "configuration_error"  # 配置错误
    UNKNOWN_ERROR = "unknown_error"           # 未知错误


@dataclass
class RetryConfig:
    """
    【P3修复】重试配置

    支持指数退避策略和备用模型降级
    """
    max_retries: int = 3                    # 最大重试次数
    base_delay: float = 2.0                 # 基础延迟（秒）
    max_delay: float = 30.0                 # 最大延迟（秒）
    exponential_base: float = 2.0           # 指数基数
    retryable_errors: list[ErrorCategory] = field(default_factory=lambda: [
        ErrorCategory.NETWORK_ERROR,
        ErrorCategory.API_RATE_LIMIT,
        ErrorCategory.API_TIMEOUT,
        ErrorCategory.SERVICE_UNAVAILABLE,
        ErrorCategory.TEMPORARY_ERROR
    ])
    fallback_models: list[str] = field(default_factory=lambda: [
        "gpt-3.5-turbo",  # 主模型失败后的降级模型
        "claude-instant-1"
    ])


@dataclass
class SubAgentResult:
    """子代理执行结果"""
    status: SubAgentStatus
    output: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    execution_time: float = 0.0
    token_usage: dict[str, int] = field(default_factory=dict)
    error: str | None = None


@dataclass
class StreamEvent:
    """流式执行事件"""
    type: str  # thought, tool_call, tool_result, progress, complete, error, child_delegate
    content: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "content": self.content,
            "data": self.data,
            "timestamp": self.timestamp
        }


class TaskStage(Enum):
    """子任务阶段"""
    PENDING = "pending"
    ANALYZING = "analyzing"
    PLANNING = "planning"
    EXECUTING = "executing"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    FAILED = "failed"


class SubAgentRuntime:
    """
    子代理运行时 - 增强版（支持父子关系 + 流式事件）

    为子代理创建独立的执行环境
    """

    def __init__(self, config: SubAgentConfig, parent_context: dict | None = None, parent_runtime: Optional['SubAgentRuntime'] = None):
        self.config = config
        self.parent_context = parent_context or {}
        self.runtime_id = str(uuid.uuid4())[:8]

        # 【新增】父子关系
        self.parent = parent_runtime  # 父代理引用
        self.children: list[SubAgentRuntime] = []  # 子代理列表
        self.task_stage = TaskStage.PENDING  # 当前任务阶段

        # 如果指定了父运行时，将自己添加到父的children列表
        if parent_runtime:
            parent_runtime.children.append(self)
            logger.debug(f"[SubAgentRuntime] {self.runtime_id} 成为 {parent_runtime.runtime_id} 的子代理")

        # 执行状态
        self.status = SubAgentStatus.PENDING
        self.start_time: float | None = None
        self.end_time: float | None = None

        # 【P0修复】当前运行的asyncio.Task，用于真正取消执行
        self._current_task: asyncio.Task | None = None

        # 模拟 AgentLoop（实际项目中应注入真实的 AgentLoop）
        self._agent_loop = None

        # 【Week 1】进度和当前步骤（用于状态API）
        self.progress: float | None = None
        self.current_step: str | None = None

        # 【Week 3】子代理干预事件队列
        self._child_interventions: list[dict[str, Any]] = []
        self._on_child_intervention: Callable[[dict[str, Any]], None] | None = None

        logger.debug(f"[SubAgentRuntime] 创建运行时: {config.name} ({self.runtime_id})")

    def _get_agent_loop(self):
        """获取或创建 AgentLoop 实例"""
        if self._agent_loop is None:
            try:
                # 延迟导入避免循环依赖
                from core.agent.agent_loop import AgentLoop
                self._agent_loop = AgentLoop()

                # 配置工具白名单
                if self.config.allowed_tools and hasattr(self._agent_loop, 'set_tool_whitelist'):
                    # 设置工具白名单
                    self._agent_loop.set_tool_whitelist(self.config.allowed_tools)

                # 配置模型
                if self.config.model and hasattr(self._agent_loop, 'set_model'):
                    self._agent_loop.set_model(self.config.model)

            except Exception as e:
                logger.error(f"[SubAgentRuntime] 创建 AgentLoop 失败: {e}")
                raise

        return self._agent_loop

    async def run(self, task: str, context: dict | None = None) -> SubAgentResult:
        """
        【P0修复】运行子代理 - 支持真正的取消机制

        核心改进：
        1. 将执行逻辑包装在asyncio.Task中，支持cancel()真正取消
        2. 正确处理asyncio.CancelledError
        3. 保持原有的干预检查、重试、错误处理逻辑

        Args:
            task: 任务描述
            context: 额外上下文

        Returns:
            SubAgentResult: 执行结果
        """
        self.start_time = time.time()
        self.status = SubAgentStatus.RUNNING

        # 【Week 1】注册到全局运行时注册表（支持API干预）
        self._register_to_api()

        # 【Week 4】注册到智能干预检测器
        if SMART_INTERVENTION_AVAILABLE:
            smart_intervention_detector.register_runtime(
                runtime_id=self.runtime_id,
                task_description=task,
                parent_task_id=getattr(self.parent, 'runtime_id', None) if self.parent else None
            )

        # 初始化重试配置
        retry_config = RetryConfig()
        original_model = self.config.model

        # 【关键修复】创建asyncio.Task来包装执行逻辑
        # 这样cancel()方法可以通过task.cancel()真正中断执行
        self._current_task = asyncio.create_task(
            self._run_with_intervention_and_retry(task, context, retry_config, original_model)
        )

        try:
            # 等待任务完成，同时允许被取消
            result = await self._current_task
            return result

        except asyncio.CancelledError:
            # 【关键修复】处理取消信号
            logger.info(f"[SubAgentRuntime] {self.config.name} 执行被取消")
            self.status = SubAgentStatus.CANCELLED
            self.end_time = time.time()

            # 恢复原始模型
            self.config.model = original_model

            return SubAgentResult(
                status=SubAgentStatus.CANCELLED,
                output="",
                error="执行被用户取消",
                execution_time=self.end_time - self.start_time if self.start_time else 0
            )

        finally:
            # 清理任务引用
            self._current_task = None
            # 【Week 1】从全局注册表注销
            self._unregister_from_api()
            # 【Week 4】从智能干预检测器注销
            if SMART_INTERVENTION_AVAILABLE:
                smart_intervention_detector.unregister_runtime(self.runtime_id)

    async def _run_with_intervention_and_retry(
        self,
        task: str,
        context: dict | None,
        retry_config: RetryConfig,
        original_model: str
    ) -> SubAgentResult:
        """
        【P0修复】内部执行方法，包含干预检查、重试、错误处理

        这个方法会被包装在asyncio.Task中，以支持真正的取消
        """
        last_error = None
        attempt = 0

        while attempt <= retry_config.max_retries:
            try:
                # 【P1修复】检查是否有实时干预（每轮执行前检查）
                if INTERVENTION_AVAILABLE and self.status == SubAgentStatus.RUNNING:
                    try:
                        has_intervention, adaptation_type, details = check_and_apply_intervention(
                            task_id=self.runtime_id,
                            current_working_memory=[{"role": "user", "content": task}],
                            current_plan=None
                        )

                        if has_intervention:
                            logger.info(f"[SubAgentRuntime] {self.config.name} 收到干预: {adaptation_type}")

                            # 【Week 3】通知父代理干预事件
                            await self._notify_parent_intervention(adaptation_type, details)

                            # 处理不同类型的干预
                            if adaptation_type == ExecutionAdaptation.PAUSE.name:
                                self.status = SubAgentStatus.PAUSED
                                # 发送暂停事件
                                if self.event_broadcaster:
                                    await self.event_broadcaster.on_paused(details.get("reason", ""))

                                # 等待恢复（通过外部调用resume恢复）
                                wait_count = 0
                                max_wait = 3600  # 最大等待1小时
                                while self.status == SubAgentStatus.PAUSED and wait_count < max_wait:
                                    # 【P0修复】使用短睡眠周期，更快响应取消
                                    await asyncio.sleep(0.5)
                                    wait_count += 0.5

                                    # 检查是否被取消
                                    if self.status == SubAgentStatus.CANCELLED:
                                        raise asyncio.CancelledError()

                                    # 重新检查干预（可能收到恢复指令）
                                    has_intervention, new_adaptation, new_details = check_and_apply_intervention(
                                        task_id=self.runtime_id,
                                        current_working_memory=[],
                                        current_plan=None
                                    )
                                    if new_adaptation == ExecutionAdaptation.CONTINUE.name:
                                        self.status = SubAgentStatus.RUNNING
                                        break

                                if self.status == SubAgentStatus.PAUSED:
                                    # 超时，取消执行
                                    self.status = SubAgentStatus.CANCELLED
                                    return SubAgentResult(
                                        status=self.status,
                                        output="",
                                        error="执行被暂停且超时取消"
                                    )

                            elif adaptation_type == ExecutionAdaptation.REPLAN.name:
                                # 重新规划：修改任务描述
                                new_task = details.get("new_task") or details.get("reason", "")
                                if new_task:
                                    logger.info(f"[SubAgentRuntime] {self.config.name} 重新规划任务: {new_task[:100]}...")
                                    task = new_task
                                    # 重置重试计数
                                    attempt = 0
                                    self.config.model = original_model

                            elif adaptation_type == ExecutionAdaptation.ADJUST_APPROACH.name:
                                # 调整方法：添加额外上下文
                                adjustment = details.get("adjustment") or details.get("reason", "")
                                if adjustment:
                                    logger.info(f"[SubAgentRuntime] {self.config.name} 调整方法: {adjustment[:100]}...")
                                    if context is None:
                                        context = {}
                                    context["intervention_adjustment"] = adjustment

                            elif adaptation_type == ExecutionAdaptation.ABORT.name:
                                # 中止执行
                                logger.info(f"[SubAgentRuntime] {self.config.name} 收到中止指令")
                                self.status = SubAgentStatus.CANCELLED
                                return SubAgentResult(
                                    status=self.status,
                                    output="",
                                    error="执行被用户中止"
                                )

                    except Exception as e:
                        # 干预检查失败不应阻断正常执行
                        logger.debug(f"[SubAgentRuntime] 干预检查失败: {e}")

                # 【Week 4】记录执行轮次（用于智能干预检测）
                if SMART_INTERVENTION_AVAILABLE:
                    smart_intervention_detector.record_round(
                        runtime_id=self.runtime_id,
                        round_data={"attempt": attempt, "task": task[:100]}
                    )

                # 构建完整提示词
                full_prompt = self._build_prompt(task, context)

                # 执行（带超时）
                result = await asyncio.wait_for(
                    self._execute_with_loop(full_prompt),
                    timeout=self.config.timeout
                )

                self.status = SubAgentStatus.COMPLETED
                self.end_time = time.time()

                # 【P3修复】恢复原始模型
                self.config.model = original_model

                return SubAgentResult(
                    status=self.status,
                    output=result.get("output", ""),
                    data=result.get("data", {}),
                    execution_time=self.end_time - self.start_time,
                    token_usage=result.get("token_usage", {})
                )

            except asyncio.TimeoutError as e:
                error_category = ErrorCategory.API_TIMEOUT
                last_error = e

                # 【P3修复】判断是否可重试
                if attempt < retry_config.max_retries and error_category in retry_config.retryable_errors:
                    attempt += 1
                    delay = self._calculate_retry_delay(attempt, retry_config)

                    logger.warning(
                        f"[SubAgentRuntime] {self.config.name} 执行超时，"
                        f"第{attempt}次重试，等待{delay:.1f}秒..."
                    )

                    self.status = SubAgentStatus.RETRYING
                    await asyncio.sleep(delay)

                    # 【P3修复】尝试降级到备用模型
                    if attempt >= 2 and retry_config.fallback_models:
                        await self._try_fallback_model(retry_config, attempt)
                else:
                    # 不可恢复或重试次数用尽
                    break

            except asyncio.CancelledError:
                # 【P0修复】重新抛出取消信号，让外层正确处理
                logger.info(f"[SubAgentRuntime] {self.config.name} 收到取消信号，停止重试")
                raise

            except Exception as e:
                # 【P3修复】分类错误
                error_category = self._classify_error(e)
                last_error = e

                logger.error(
                    f"[SubAgentRuntime] {self.config.name} 执行失败: {e} "
                    f"(分类: {error_category.value})"
                )

                # 判断是否可重试
                if attempt < retry_config.max_retries and error_category in retry_config.retryable_errors:
                    attempt += 1
                    delay = self._calculate_retry_delay(attempt, retry_config)

                    logger.warning(
                        f"[SubAgentRuntime] {self.config.name} 遇到可恢复错误，"
                        f"第{attempt}次重试，等待{delay:.1f}秒..."
                    )

                    self.status = SubAgentStatus.RETRYING
                    await asyncio.sleep(delay)

                    # 【P3修复】尝试降级到备用模型
                    if attempt >= 2 and retry_config.fallback_models:
                        await self._try_fallback_model(retry_config, attempt)
                else:
                    # 不可恢复错误或重试次数用尽
                    break

        # 【P3修复】所有重试失败，返回最终错误
        self.status = SubAgentStatus.FAILED
        self.end_time = time.time()

        # 恢复原始模型
        self.config.model = original_model

        # 构建详细错误信息
        error_msg = str(last_error) if last_error else "未知错误"
        if attempt > 0:
            error_msg = f"{error_msg} (重试{attempt}次后仍然失败)"

        return SubAgentResult(
            status=self.status,
            output="",
            error=error_msg,
            execution_time=time.time() - self.start_time if self.start_time else 0
        )

    def _classify_error(self, error: Exception) -> ErrorCategory:
        """
        【P3修复】错误分类器

        根据错误类型和消息内容判断错误类别

        Args:
            error: 异常对象

        Returns:
            ErrorCategory: 错误分类
        """
        error_msg = str(error).lower()

        # 网络相关错误
        if any(kw in error_msg for kw in ["connection", "network", "timeout", "timed out"]):
            if "rate limit" in error_msg or "too many requests" in error_msg:
                return ErrorCategory.API_RATE_LIMIT
            return ErrorCategory.NETWORK_ERROR

        # API相关错误
        if any(kw in error_msg for kw in ["api error", "service unavailable", "503", "502", "504"]):
            return ErrorCategory.SERVICE_UNAVAILABLE

        # 权限错误
        if any(kw in error_msg for kw in ["permission", "unauthorized", "forbidden", "403"]):
            return ErrorCategory.PERMISSION_DENIED

        # 资源不存在
        if any(kw in error_msg for kw in ["not found", "404", "does not exist"]):
            return ErrorCategory.NOT_FOUND

        # 验证错误
        if any(kw in error_msg for kw in ["validation", "invalid", "bad request", "400"]):
            return ErrorCategory.VALIDATION_ERROR

        # 配置错误
        if any(kw in error_msg for kw in ["configuration", "config", "setup"]):
            return ErrorCategory.CONFIGURATION_ERROR

        return ErrorCategory.UNKNOWN_ERROR

    def _calculate_retry_delay(self, attempt: int, config: RetryConfig) -> float:
        """
        【P3修复】计算指数退避延迟

        Args:
            attempt: 当前重试次数（从1开始）
            config: 重试配置

        Returns:
            float: 延迟时间（秒）
        """
        delay = config.base_delay * (config.exponential_base ** (attempt - 1))
        return min(delay, config.max_delay)

    async def _try_fallback_model(self, config: RetryConfig, attempt: int):
        """
        【P3修复】尝试降级到备用模型

        Args:
            config: 重试配置
            attempt: 当前重试次数
        """
        if not config.fallback_models:
            return

        # 选择备用模型（根据重试次数轮询）
        fallback_index = (attempt - 2) % len(config.fallback_models)
        fallback_model = config.fallback_models[fallback_index]

        logger.info(
            f"[SubAgentRuntime] {self.config.name} 降级到备用模型: "
            f"{self.config.model} -> {fallback_model}"
        )

        self.config.model = fallback_model

        # 重新初始化AgentLoop以使用新模型
        self._agent_loop = None
        try:
            await self._get_agent_loop()
        except Exception as e:
            logger.warning(f"[SubAgentRuntime] 备用模型初始化失败: {e}")

    def _build_prompt(self, task: str, context: dict | None) -> str:
        """构建完整提示词"""
        parts = []

        # 系统提示词
        parts.append(f"<system>\n{self.config.prompt}\n</system>")

        # 继承的父上下文
        if self.config.inherit_parent_context and self.parent_context:
            parent_info = self.parent_context.get("summary", "")
            if parent_info:
                parts.append(f"<parent_context>\n{parent_info}\n</parent_context>")

        # 可用工具说明
        tools_info = self._get_tools_info()
        if tools_info:
            parts.append(f"<available_tools>\n{tools_info}\n</available_tools>")

        # 任务
        parts.append(f"<task>\n{task}\n</task>")

        # 额外上下文
        if context:
            for key, value in context.items():
                if isinstance(value, str):
                    parts.append(f"<{key}>\n{value}\n</{key}>")

        return "\n\n".join(parts)

    def _get_tools_info(self) -> str:
        """获取可用工具信息"""
        if not self.config.allowed_tools:
            return "所有工具可用"

        tools_desc = []
        for tool_id in self.config.allowed_tools:
            try:
                from core.tool.tool_router import tool_router
                tool = tool_router.get_tool(tool_id)
                if tool:
                    tools_desc.append(f"- {tool_id}: {tool.description}")
            except Exception:
                tools_desc.append(f"- {tool_id}")

        return "\n".join(tools_desc) if tools_desc else "无可用工具"

    async def _execute_with_loop(self, prompt: str) -> dict[str, Any]:
        """使用 AgentLoop 执行"""
        agent_loop = self._get_agent_loop()

        # 检查 AgentLoop 是否有异步处理方法
        if hasattr(agent_loop, 'process_async'):
            result = await agent_loop.process_async(
                prompt=prompt,
                max_turns=self.config.max_turns
            )
        elif hasattr(agent_loop, 'process'):
            # 同步方法包装
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(
                    agent_loop.process,
                    prompt=prompt,
                    max_turns=self.config.max_turns
                )
                result = await asyncio.wrap_future(future)
        else:
            # 模拟执行（测试用）
            logger.warning("[SubAgentRuntime] AgentLoop 未提供处理方法，使用模拟执行")
            result = {
                "output": f"[模拟执行] 任务: {prompt[:50]}...",
                "data": {},
                "token_usage": {}
            }

        return result

    async def stream(self, task: str, context: dict | None = None) -> AsyncGenerator[str, None]:
        """
        流式执行

        Yields:
            执行过程中的输出片段
        """
        self.start_time = time.time()
        self.status = SubAgentStatus.RUNNING

        full_prompt = self._build_prompt(task, context)

        try:
            agent_loop = self._get_agent_loop()

            if hasattr(agent_loop, 'process_stream'):
                async for chunk in agent_loop.process_stream(
                    prompt=full_prompt,
                    max_turns=self.config.max_turns
                ):
                    yield chunk
            else:
                # 非流式执行，一次性返回
                result = await self._execute_with_loop(full_prompt)
                yield result.get("output", "")

            self.status = SubAgentStatus.COMPLETED

        except Exception as e:
            self.status = SubAgentStatus.FAILED
            logger.error(f"[SubAgentRuntime] 流式执行失败: {e}")
            yield f"[错误: {e}]"

        finally:
            self.end_time = time.time()

    def cancel(self):
        """
        【P0修复】真正取消执行

        不再只是设置状态标志，而是调用asyncio.Task.cancel()来中断执行
        """
        if self.status in (SubAgentStatus.RUNNING, SubAgentStatus.PAUSED):
            self.status = SubAgentStatus.CANCELLED

            # 【关键修复】如果有正在运行的任务，真正取消它
            if self._current_task and not self._current_task.done():
                self._current_task.cancel()
                logger.info(f"[SubAgentRuntime] 已发送取消信号: {self.runtime_id}")
            else:
                logger.info(f"[SubAgentRuntime] 取消执行（无活动任务）: {self.runtime_id}")

    # ==================== 【Week 1】API干预支持 ====================

    def _register_to_api(self):
        """
        【Week 1】注册到API可访问的注册表

        使前端可以通过API干预此子代理
        """
        try:
            # 使用延迟导入避免循环依赖
            from api.cloud_api import _register_subagent_runtime
            _register_subagent_runtime(self.runtime_id, self)
            logger.debug(f"[SubAgentRuntime] 已注册到API: {self.runtime_id}")
        except ImportError:
            # API模块可能不可用（如单元测试环境）
            logger.debug(f"[SubAgentRuntime] API注册跳过（模块不可用）: {self.runtime_id}")
        except Exception as e:
            logger.warning(f"[SubAgentRuntime] API注册失败: {e}")

    def _unregister_from_api(self):
        """
        【Week 1】从API注册表注销

        清理API干预注册
        """
        try:
            from api.cloud_api import _unregister_subagent_runtime
            _unregister_subagent_runtime(self.runtime_id)
            logger.debug(f"[SubAgentRuntime] 已从API注销: {self.runtime_id}")
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"[SubAgentRuntime] API注销失败: {e}")

    # ==================== 【新增】父子关系支持 ====================

    # ==================== 【Week 3】父代理通知支持 ====================

    async def _notify_parent_intervention(self, intervention_type: str, details: dict[str, Any]):
        """
        【Week 3】通知父代理干预事件

        当子代理收到干预时，通知父代理以便父代理做出响应。
        父代理可以选择：
        - 继续监控其他子代理
        - 调整整体策略
        - 干预其他子代理

        Args:
            intervention_type: 干预类型 (PAUSE, REPLAN, ADJUST_APPROACH, ABORT)
            details: 干预详情
        """
        if not self.parent:
            return  # 没有父代理，无需通知

        try:
            # 构建干预通知
            notification = {
                "type": "child_intervention",
                "child_id": self.runtime_id,
                "child_name": self.config.name,
                "intervention_type": intervention_type,
                "reason": details.get("reason", ""),
                "timestamp": time.time(),
                "details": details
            }

            # 方式1: 通过父代理的上下文注入系统消息
            if hasattr(self.parent, '_child_interventions'):
                # 父代理有专门的干预队列
                self.parent._child_interventions.append(notification)
            elif hasattr(self.parent, 'parent_context'):
                # 通过父上下文传递（间接方式）
                if 'child_interventions' not in self.parent.parent_context:
                    self.parent.parent_context['child_interventions'] = []
                self.parent.parent_context['child_interventions'].append(notification)

            # 方式2: 通过实时干预系统通知（如果父代理有活跃任务）
            if INTERVENTION_AVAILABLE:
                try:
                    from core.agent.realtime_intervention import realtime_intervention
                    parent_runtime_id = getattr(self.parent, 'runtime_id', None)
                    if parent_runtime_id and realtime_intervention.get_task_memory(parent_runtime_id):
                        # 父代理有活跃任务，通过干预系统通知
                        reason = f"【子代理干预】{self.config.name} 收到 {intervention_type}"
                        if details.get("reason"):
                            reason += f": {details['reason']}"

                        realtime_intervention.submit_intervention(
                            task_id=parent_runtime_id,
                            user_input=reason
                        )
                        logger.info(f"[SubAgentRuntime] 已通过干预系统通知父代理: {self.parent.runtime_id}")
                except Exception as e:
                    logger.debug(f"[SubAgentRuntime] 通过干预系统通知父代理失败: {e}")

            # 方式3: 触发事件回调（如果父代理注册了监听器）
            if hasattr(self.parent, '_on_child_intervention'):
                try:
                    await self.parent._on_child_intervention(notification)
                except Exception as e:
                    logger.error(f"[SubAgentRuntime] 父代理干预回调失败: {e}")

            logger.info(f"[SubAgentRuntime] {self.config.name} 已通知父代理干预: {intervention_type}")

        except Exception as e:
            logger.error(f"[SubAgentRuntime] 通知父代理干预失败: {e}")

    # ==================== 【Week 3】干预事件处理（供父代理使用） ====================

    def get_child_interventions(self, clear: bool = True) -> list[dict[str, Any]]:
        """
        【Week 3】获取子代理的干预事件

        供父代理调用，获取子代理的干预通知。

        Args:
            clear: 获取后是否清空队列

        Returns:
            干预事件列表
        """
        interventions = self._child_interventions.copy()
        if clear:
            self._child_interventions.clear()
        return interventions

    def has_child_interventions(self) -> bool:
        """【Week 3】检查是否有子代理干预事件"""
        return len(self._child_interventions) > 0

    def register_child_intervention_callback(self, callback: Callable[[dict[str, Any]], None]):
        """
        【Week 3】注册子代理干预回调

        当子代理收到干预时，会调用此回调。

        Args:
            callback: 回调函数，接收干预通知字典
        """
        self._on_child_intervention = callback

    async def delegate_to_child(self, child_config: SubAgentConfig, task: str, context: dict | None = None) -> 'SubAgentRuntime':
        """
        委派给子代理

        核心方法：创建子代理并建立父子关系

        Args:
            child_config: 子代理配置
            task: 任务描述
            context: 额外上下文

        Returns:
            SubAgentRuntime: 创建的子运行时
        """
        # 创建子运行时，传入self作为parent_runtime
        child = SubAgentRuntime(
            config=child_config,
            parent_context=self._get_merged_context(context),
            parent_runtime=self  # 关键：建立父子关系
        )

        child.task_stage = TaskStage.PENDING
        logger.info(f"[SubAgentRuntime] {self.config.name} 委派任务给子代理 {child_config.name}")

        return child

    def _get_merged_context(self, additional_context: dict | None = None) -> dict:
        """
        获取合并上下文（继承父上下文）

        上下文继承链：父上下文 → 自己的parent_context → additional_context
        """
        merged = {}

        # 1. 首先继承父代理的完整上下文
        if self.parent:
            merged.update(self.parent._get_merged_context())

        # 2. 添加自己的parent_context
        if self.parent_context:
            merged.update(self.parent_context)

        # 3. 添加额外的上下文
        if additional_context:
            merged.update(additional_context)

        # 4. 添加运行时元信息
        merged["runtime_id"] = self.runtime_id
        merged["parent_runtime_id"] = self.parent.runtime_id if self.parent else None
        merged["agent_name"] = self.config.name

        return merged

    def get_child_tree(self) -> dict[str, Any]:
        """获取子代理树结构"""
        return {
            "runtime_id": self.runtime_id,
            "name": self.config.name,
            "status": self.status.value,
            "stage": self.task_stage.value,
            "children": [child.get_child_tree() for child in self.children]
        }

    async def run_with_stream_events(self, task: str, context: dict | None = None, slot_id: int | None = None) -> AsyncGenerator[StreamEvent, None]:
        """
        运行并产生流式事件

        产生的事件类型：
        - thought: AI思考过程
        - tool_call: 准备调用工具
        - tool_result: 工具执行结果
        - progress: 进度更新
        - child_delegate: 委派给子代理
        - complete: 任务完成
        - error: 错误

        Args:
            task: 任务描述
            context: 上下文
            slot_id: 长任务槽位ID（用于WebSocket广播）
        """
        self.start_time = time.time()
        self.status = SubAgentStatus.RUNNING
        self.task_stage = TaskStage.ANALYZING

        # 注册到事件广播器
        broadcaster = None
        if slot_id is not None:
            try:
                from core.subagent.event_broadcaster import SubAgentEventBroadcaster
                broadcaster = SubAgentEventBroadcaster()
                broadcaster.associate_runtime_with_slot(self.runtime_id, slot_id)
            except ImportError:
                pass

        async def yield_and_broadcast(event: StreamEvent):
            """产生事件并广播到WebSocket"""
            # 添加运行时信息
            event.runtime_id = self.runtime_id
            event.agent_name = self.config.name

            # 广播到WebSocket
            if broadcaster and slot_id is not None:
                try:
                    await broadcaster.broadcast_stream_event(self.runtime_id, event)
                except Exception as e:
                    logger.debug(f"[SubAgentRuntime] 广播事件失败: {e}")

            yield event

        try:
            # 1. 分析阶段
            async for event in yield_and_broadcast(StreamEvent(
                type="thought",
                content=f"[{self.config.name}] 正在分析任务: {task[:100]}...",
                data={"stage": "analyzing", "agent": self.config.name}
            )):
                yield event

            # 构建提示词
            full_prompt = self._build_prompt(task, context)

            # 2. 规划阶段
            self.task_stage = TaskStage.PLANNING
            async for event in yield_and_broadcast(StreamEvent(
                type="thought",
                content=f"[{self.config.name}] 规划执行步骤...",
                data={"stage": "planning"}
            )):
                yield event

            # 3. 执行阶段
            self.task_stage = TaskStage.EXECUTING
            async for event in yield_and_broadcast(StreamEvent(
                type="tool_call",
                content="调用AgentLoop执行",
                data={"tool": "agent_loop", "prompt_length": len(full_prompt)}
            )):
                yield event

            # 实际执行
            result = await self._execute_with_loop(full_prompt)

            async for event in yield_and_broadcast(StreamEvent(
                type="tool_result",
                content="AgentLoop执行完成",
                data={"output_length": len(result.get("output", ""))}
            )):
                yield event

            # 4. 审查阶段（如果有代码）
            if self._contains_code(result.get("output", "")):
                self.task_stage = TaskStage.REVIEWING
                async for event in yield_and_broadcast(StreamEvent(
                    type="thought",
                    content="检测到代码，建议进行代码审查",
                    data={"stage": "reviewing", "has_code": True}
                )):
                    yield event

            # 5. 完成
            self.status = SubAgentStatus.COMPLETED
            self.task_stage = TaskStage.COMPLETED
            self.end_time = time.time()

            async for event in yield_and_broadcast(StreamEvent(
                type="complete",
                content=result.get("output", ""),
                data={
                    "status": "completed",
                    "execution_time": self.end_time - self.start_time,
                    "token_usage": result.get("token_usage", {})
                }
            )):
                yield event

        except Exception as e:
            self.status = SubAgentStatus.FAILED
            self.task_stage = TaskStage.FAILED
            self.end_time = time.time()

            logger.error(f"[SubAgentRuntime] 流式执行失败: {e}")
            async for event in yield_and_broadcast(StreamEvent(
                type="error",
                content=str(e),
                data={"error_type": type(e).__name__}
            )):
                yield event

    def _contains_code(self, output: str) -> bool:
        """检查输出是否包含代码"""
        code_indicators = [
            "```", "def ", "class ", "import ", "from ",
            "function", "const ", "let ", "var ", "=>"
        ]
        return any(indicator in output for indicator in code_indicators)

    # ==================== 【新增】流式执行增强 ====================

    async def stream_enhanced(self, task: str, context: dict | None = None) -> AsyncGenerator[StreamEvent, None]:
        """
        增强版流式执行 - 支持更丰富的事件类型
        """
        async for event in self.run_with_stream_events(task, context):
            yield event
