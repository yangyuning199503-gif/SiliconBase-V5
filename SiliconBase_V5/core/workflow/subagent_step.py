#!/usr/bin/env python3
"""
SubAgentStep - 子代理步骤执行器 V1.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
支持在工作流中执行子代理步骤

【核心特性】
1. 子代理步骤配置管理
2. 模板渲染与上下文传递
3. 流水线执行支持
4. 结果验证与输出提取

【架构位置】
- 位于: core/workflow/subagent_step.py
- 调用方: WorkflowExecutor
- 依赖: SubAgentManager, WorkflowEngine
"""

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

# 导入项目组件
try:
    from core.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger('subagent_step')

# 导入子代理组件
try:
    from core.subagent.manager import PipelineStep, SubAgentManager
    SUBAGENT_AVAILABLE = True
except ImportError as e:
    SUBAGENT_AVAILABLE = False
    logger.warning(f"[SubAgentStep] SubAgentManager 导入失败: {e}")

# 【修复断点1】导入上下文智能搬运系统
try:
    from .context_bridge import ContextIntelligence
    CONTEXT_INTELLIGENCE_AVAILABLE = True
except ImportError as e:
    CONTEXT_INTELLIGENCE_AVAILABLE = False
    logger.warning(f"[SubAgentStep] ContextIntelligence 导入失败: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# 异常定义
# ═══════════════════════════════════════════════════════════════════════════════

class SubAgentExecutionError(Exception):
    """子代理执行错误"""
    pass


class VerificationResult:
    """验证结果"""

    def __init__(self, passed: bool = False, confidence: float = 0.0,
                 verified_by: str = "", concerns: list[str] | None = None):
        self.passed = passed
        self.confidence = confidence
        self.verified_by = verified_by
        self.concerns = concerns or []

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "confidence": self.confidence,
            "verified_by": self.verified_by,
            "concerns": self.concerns
        }


# ═══════════════════════════════════════════════════════════════════════════════
# 子代理步骤配置
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class SubAgentStepConfig:
    """
    子代理步骤配置

    Attributes:
        agent_name: 子代理名称
        task_template: 任务模板（支持 Jinja2 语法）
        pipeline_steps: 自定义流水线步骤列表
        use_pipeline: 是否使用流水线模式
        enable_streaming: 是否启用流式输出
        auto_verify: 是否自动验证结果
        verification_prompt: 自定义验证提示
        timeout: 执行超时时间（秒）
        max_retries: 最大重试次数
        context_passing: 上下文变量映射（目标变量名 -> 源变量名）
    """
    agent_name: str
    task_template: str
    pipeline_steps: list[dict] | None = None
    use_pipeline: bool = True
    enable_streaming: bool = True
    auto_verify: bool = True
    verification_prompt: str | None = None
    timeout: int = 300  # 秒
    max_retries: int = 2
    context_passing: dict[str, str] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════════
# 子代理步骤执行器
# ═══════════════════════════════════════════════════════════════════════════════

class SubAgentStepExecutor:
    """
    子代理步骤执行器

    职责:
    1. 准备子代理输入（模板渲染+上下文）
    2. 调用子代理流水线
    3. 流式输出转发到槽位
    4. 结果验证（AI+人工）
    5. 提取结构化输出

    【修复断点1】集成 ContextIntelligence 实现智能上下文搬运
    """

    def __init__(
        self,
        subagent_manager: Optional['SubAgentManager'] = None,
        long_task_slots: Any | None = None,
        verification_agent: Any | None = None,
        context_intelligence: Optional['ContextIntelligence'] = None
    ):
        """
        初始化子代理步骤执行器

        Args:
            subagent_manager: 子代理管理器实例
            long_task_slots: 长任务槽位实例
            verification_agent: 验证代理实例
            context_intelligence: 上下文智能搬运系统（新增）
        """
        self.subagent_manager = subagent_manager
        self.long_task_slots = long_task_slots
        self.verification_agent = verification_agent

        # 【修复断点1】初始化或延迟加载 ContextIntelligence
        self._context_intelligence = context_intelligence

        logger.info("[SubAgentStepExecutor] 子代理步骤执行器初始化完成")

    def _get_context_intelligence(self) -> Optional['ContextIntelligence']:
        """【修复断点1】延迟加载 ContextIntelligence"""
        if self._context_intelligence is None and CONTEXT_INTELLIGENCE_AVAILABLE:
            try:
                # 尝试从配置加载
                from core.config import config

                from .context_bridge import ContextIntelligence
                ci_config = {
                    "enable_memory": config.get("workflow.subagent.context.enable_memory", True),
                    "enable_perception": config.get("workflow.subagent.context.perception_on_critical", True),
                    "memory_query_limit": config.get("workflow.subagent.context.memory_query_limit", 5),
                    "memory_min_importance": config.get("workflow.subagent.context.memory_min_importance", 0.5),
                    "history_patterns_limit": config.get("workflow.subagent.context.history_patterns_limit", 3)
                }
                self._context_intelligence = ContextIntelligence(config=ci_config)
                logger.info("[SubAgentStepExecutor] ContextIntelligence 延迟加载成功")
            except Exception as e:
                logger.warning(f"[SubAgentStepExecutor] ContextIntelligence 初始化失败: {e}")
        return self._context_intelligence

    def _parse_subagent_config(self, step: Any) -> SubAgentStepConfig:
        """
        从工作流步骤解析子代理配置

        Args:
            step: 工作流步骤定义

        Returns:
            SubAgentStepConfig: 子代理步骤配置
        """
        # 从步骤的工具参数中提取配置
        tool_params = getattr(step, 'tool_params', {}) or {}

        return SubAgentStepConfig(
            agent_name=tool_params.get('agent_name', 'code_assistant'),
            task_template=tool_params.get('task_template', '{{task}}'),
            pipeline_steps=tool_params.get('pipeline_steps'),
            use_pipeline=tool_params.get('use_pipeline', True),
            enable_streaming=tool_params.get('enable_streaming', True),
            auto_verify=tool_params.get('auto_verify', True),
            verification_prompt=tool_params.get('verification_prompt'),
            timeout=tool_params.get('timeout', 300),
            max_retries=tool_params.get('max_retries', 2),
            context_passing=tool_params.get('context_passing', {})
        )

    def _render_template(self, template: str, variables: dict[str, Any]) -> str:
        """
        渲染任务模板

        支持简单的变量替换: {{variable_name}}

        Args:
            template: 模板字符串
            variables: 变量字典

        Returns:
            str: 渲染后的字符串
        """
        try:
            # 简单的 Jinja2 风格模板渲染
            result = template
            for key, value in variables.items():
                placeholder = f"{{{{{key}}}}}"
                if placeholder in result:
                    result = result.replace(placeholder, str(value))

            # 处理嵌套变量访问: {{step_result.output}}
            pattern = r'\{\{([^}]+)\}\}'
            def replace_var(match):
                var_path = match.group(1).strip()
                parts = var_path.split('.')
                current = variables
                for part in parts:
                    if isinstance(current, dict) and part in current:
                        current = current[part]
                    else:
                        return match.group(0)  # 保留原样
                return str(current)

            result = re.sub(pattern, replace_var, result)
            return result

        except Exception as e:
            logger.warning(f"[SubAgentStepExecutor] 模板渲染失败: {e}, 使用原始模板")
            return template

    def _build_context(
        self,
        execution_context: Any,
        config: SubAgentStepConfig,
        step: Any = None,
        step_index: int = 0,
        user_id: str = "default"
    ) -> dict[str, Any]:
        """
        构建子代理上下文

        【修复断点1】优先使用 ContextIntelligence 准备智能上下文：
        - 自动关联相关记忆
        - 关键步骤感知注入
        - 历史成功模式
        - 前序步骤摘要

        如果 ContextIntelligence 不可用，则回退到基础上下文

        Args:
            execution_context: 执行上下文
            config: 子代理步骤配置
            step: 当前步骤（新增，用于智能上下文）
            step_index: 步骤索引（新增）
            user_id: 用户ID（新增）

        Returns:
            Dict[str, Any]: 上下文字典
        """
        # 【修复断点1】尝试使用 ContextIntelligence 准备智能上下文
        context_intel = self._get_context_intelligence()
        if context_intel and step is not None:
            try:
                import asyncio
                # 异步准备智能上下文
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # 如果在运行的事件循环中，创建新任务
                    future = asyncio.ensure_future(
                        context_intel.prepare_step_context(
                            execution=execution_context,
                            step=step,
                            step_index=step_index,
                            user_id=user_id
                        )
                    )
                    # 等待结果（使用短的超时）
                    step_context = loop.run_until_complete(
                        asyncio.wait_for(future, timeout=5.0)
                    )
                else:
                    step_context = loop.run_until_complete(
                        context_intel.prepare_step_context(
                            execution=execution_context,
                            step=step,
                            step_index=step_index,
                            user_id=user_id
                        )
                    )

                # 将 StepContext 转换为字典
                if step_context:
                    smart_context = {
                        "workflow_variables": step_context.variables,
                        "step_results": step_context.step_results,
                        "execution_id": step_context.execution_id,
                        "step_id": step_context.step_id,
                        "step_name": step_context.step_name,
                        # 【关键】智能上下文增强
                        "related_memories": [m.to_dict() for m in step_context.related_memories] if step_context.related_memories else [],
                        "memory_summary": step_context.memory_summary,
                        "historical_patterns": [p.to_dict() for p in step_context.historical_patterns] if step_context.historical_patterns else [],
                        "environment_state": step_context.environment_state,
                        "previous_summary": step_context.previous_summary,
                        "_context_source": "intelligent"  # 标记上下文来源
                    }

                    # 过滤空值
                    smart_context = {k: v for k, v in smart_context.items() if v is not None and v != []}

                    logger.info(f"[SubAgentStepExecutor] 使用智能上下文: {len(smart_context.get('related_memories', []))} 条记忆, "
                               f"{len(smart_context.get('historical_patterns', []))} 个模式")
                    return smart_context

            except Exception as e:
                logger.warning(f"[SubAgentStepExecutor] 智能上下文准备失败，回退到基础上下文: {e}")

        # 基础上下文（回退方案）
        variables = getattr(execution_context, 'variables', {}) or {}
        step_results = getattr(execution_context, 'step_results', {}) or {}
        workflow_id = getattr(execution_context, 'workflow_id', '')
        execution_id = getattr(execution_context, 'execution_id', '')

        context = {
            "workflow_variables": variables,
            "step_results": step_results,
            "workflow_id": workflow_id,
            "execution_id": execution_id,
            "_context_source": "basic"  # 标记为基础上下文
        }

        # 添加上下文变量映射
        for target_key, source_var in config.context_passing.items():
            if source_var in variables:
                context[target_key] = variables[source_var]

        return context

    async def execute(
        self,
        step: Any,
        execution_context: Any,
        slot_id: int | None = None,
        voice_instance: Any | None = None
    ) -> dict[str, Any]:
        """
        执行子代理步骤

        Args:
            step: 工作流步骤定义
            execution_context: 执行上下文（包含变量、历史结果）
            slot_id: 槽位ID，用于WebSocket广播
            voice_instance: 语音实例

        Returns:
            Dict[str, Any]: 执行结果字典
        """
        if not SUBAGENT_AVAILABLE:
            return {
                "success": False,
                "error": "SubAgentManager 不可用",
                "output": ""
            }

        if not self.subagent_manager:
            return {
                "success": False,
                "error": "SubAgentManager 未初始化",
                "output": ""
            }

        start_time = time.time()
        config = self._parse_subagent_config(step)

        try:
            # 1. 渲染任务模板
            variables = getattr(execution_context, 'variables', {}) or {}
            task = self._render_template(config.task_template, variables)
            logger.info(f"[SubAgentStepExecutor] 执行任务: {task[:50]}...")

            # 2. 构建上下文（【修复断点1】使用智能上下文搬运）
            # 获取步骤索引和用户ID
            step_index = getattr(execution_context, 'current_step_idx', 0)
            user_id = getattr(execution_context, 'user_id', 'default')

            context = self._build_context(
                execution_context=execution_context,
                config=config,
                step=step,
                step_index=step_index,
                user_id=user_id
            )

            # 3. 准备流水线步骤
            if config.pipeline_steps:
                pipeline_steps = [
                    PipelineStep(**s) for s in config.pipeline_steps
                ]
            else:
                pipeline_steps = [PipelineStep(
                    agent_name=config.agent_name,
                    task=task
                )]

            # 4. 执行子代理流水线
            output_chunks = []
            final_output = None

            async for event in self.subagent_manager.run_pipeline(
                steps=pipeline_steps,
                initial_context=context,
                stream=config.enable_streaming,
                slot_id=slot_id
            ):
                # 收集输出
                event_type = getattr(event, 'type', '')
                event_content = getattr(event, 'content', '')
                event_data = getattr(event, 'data', {}) or {}

                if event_type == "complete":
                    final_output = event_content or event_data.get("output")
                elif event_type in ["thought", "tool_call", "progress"]:
                    output_chunks.append({
                        "type": event_type,
                        "content": event_content,
                        "data": event_data
                    })

            if not final_output:
                raise SubAgentExecutionError("子代理未返回结果")

            # 5. 结果验证
            verification_result = None
            if config.auto_verify:
                verification_result = await self._verify_result(
                    final_output,
                    step,
                    config,
                    execution_context
                )

            # 6. 提取结构化输出
            outputs = getattr(step, 'outputs', {}) or {}
            output_mapping = getattr(step, 'output_mapping', {}) or {}
            structured_outputs = self._extract_outputs(
                final_output,
                outputs,
                output_mapping
            )

            execution_time = time.time() - start_time

            return {
                "success": verification_result.passed if verification_result else True,
                "output": final_output,
                "structured_outputs": structured_outputs,
                "verification": verification_result.to_dict() if verification_result else None,
                "context_updates": self._extract_context_updates(final_output),
                "execution_metadata": {
                    "agent_name": config.agent_name,
                    "chunks_count": len(output_chunks),
                    "slot_id": slot_id,
                    "execution_time": execution_time
                }
            }

        except Exception as e:
            logger.error(f"[SubAgentStepExecutor] 执行失败: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "output": ""
            }

    async def _verify_result(
        self,
        output: str,
        step: Any,
        config: SubAgentStepConfig,
        execution_context: Any
    ) -> VerificationResult | None:
        """
        验证子代理结果

        【融合增强】双重验证：
        1. AI自动验证（快速）
        2. 人工确认（重要步骤）

        Args:
            output: 子代理输出
            step: 工作流步骤
            config: 子代理配置
            execution_context: 执行上下文

        Returns:
            VerificationResult: 验证结果
        """
        # 简单验证：检查结果是否为空或错误
        if not output or output.strip() == "":
            return VerificationResult(
                passed=False,
                confidence=0.0,
                verified_by="failed",
                concerns=["输出为空"]
            )

        # 检查是否包含错误关键词
        error_keywords = ['error', 'exception', 'failed', '失败', '错误']
        if any(keyword in output.lower() for keyword in error_keywords):
            return VerificationResult(
                passed=False,
                confidence=0.5,
                verified_by="failed",
                concerns=["输出可能包含错误信息"]
            )

        # 如果有验证代理，使用AI验证
        if self.verification_agent:
            try:
                ai_verification = await self._ai_verify(
                    output, step, config.verification_prompt
                )

                if ai_verification.confidence >= 0.9:
                    return VerificationResult(
                        passed=True,
                        confidence=ai_verification.confidence,
                        verified_by="ai_auto",
                        concerns=ai_verification.concerns
                    )
                elif ai_verification.confidence >= 0.7:
                    return VerificationResult(
                        passed=None,  # 待确认
                        confidence=ai_verification.confidence,
                        verified_by="pending_human",
                        concerns=ai_verification.concerns
                    )
            except Exception as e:
                logger.warning(f"[SubAgentStepExecutor] AI验证失败: {e}")

        # 默认通过
        return VerificationResult(
            passed=True,
            confidence=0.8,
            verified_by="auto",
            concerns=[]
        )

    async def _ai_verify(
        self,
        output: str,
        step: Any,
        verification_prompt: str | None
    ) -> 'VerificationResult':
        """
        AI自动验证结果

        Args:
            output: 子代理输出
            step: 工作流步骤
            verification_prompt: 验证提示

        Returns:
            VerificationResult: AI验证结果
        """
        # 简化实现，实际应该调用LLM进行验证
        # 这里返回一个中等置信度的结果
        return VerificationResult(
            passed=True,
            confidence=0.85,
            verified_by="ai",
            concerns=[]
        )

    def _extract_outputs(
        self,
        output: str,
        outputs: dict[str, str],
        output_mapping: dict[str, str]
    ) -> dict[str, Any]:
        """
        提取结构化输出

        Args:
            output: 原始输出字符串
            outputs: 输出定义
            output_mapping: 输出映射

        Returns:
            Dict[str, Any]: 结构化输出
        """
        result = {}

        try:
            # 尝试解析JSON
            if output.strip().startswith('{') or output.strip().startswith('['):
                parsed = json.loads(output)
                if isinstance(parsed, dict):
                    for key, alias in output_mapping.items():
                        if key in parsed:
                            result[alias] = parsed[key]
                    # 如果没有映射，保存整个对象
                    if not result:
                        result = parsed
        except json.JSONDecodeError:
            pass

        # 如果无法解析为JSON，保存原始输出
        if not result:
            result = {"raw_output": output}

        return result

    def _extract_context_updates(self, output: str) -> dict[str, Any]:
        """
        从输出中提取上下文更新

        Args:
            output: 子代理输出

        Returns:
            Dict[str, Any]: 上下文更新
        """
        updates = {}

        try:
            # 尝试解析JSON提取关键信息
            if output.strip().startswith('{') or output.strip().startswith('['):
                parsed = json.loads(output)
                if isinstance(parsed, dict):
                    # 提取常见的上下文更新字段
                    for key in ['summary', 'result', 'status', 'next_action']:
                        if key in parsed:
                            updates[key] = parsed[key]
        except json.JSONDecodeError:
            pass

        return updates


# ═══════════════════════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════════════════════

def get_subagent_step_executor(
    subagent_manager: SubAgentManager | None = None,
    long_task_slots: Any | None = None
) -> SubAgentStepExecutor:
    """
    获取子代理步骤执行器实例

    Args:
        subagent_manager: 子代理管理器实例
        long_task_slots: 长任务槽位实例

    Returns:
        SubAgentStepExecutor: 子代理步骤执行器
    """
    return SubAgentStepExecutor(
        subagent_manager=subagent_manager,
        long_task_slots=long_task_slots
    )
