#!/usr/bin/env python3
"""
子代理管理器
"""

import asyncio
import threading
import time
from collections.abc import AsyncGenerator
from typing import Any

from core.subagent.config import PRESET_SUBAGENTS, SubAgentConfig
from core.sync.event_bus import event_bus  # 【ExperienceBus】事件总线

# ═══════════════════════════════════════════════════════════════
# Phase4: 子代理Prompt标准化（统一注入，禁止动态拼接）
# ═══════════════════════════════════════════════════════════════
SUBAGENT_PROMPT_PREAMBLE = """【SiliconBase V5 子代理规范】
1. 你是SiliconBase V5系统的专属子代理，必须严格遵守上级Agent（指挥官/主AI）的调度指令
2. 你的所有输出必须结构清晰：先给出结论，再给出推理过程，最后列出关键依据
3. 禁止执行任何可能危害系统安全、泄露用户隐私或违反法律法规的操作
4. 当你的任务涉及交易、资金、敏感数据时，必须二次确认并获得明确授权后方可执行
5. 你的上下文窗口有限，请优先保留与当前任务最相关的信息，自动丢弃过期或低相关度内容
6. 所有工具调用必须通过async接口执行，禁止同步阻塞调用

【角色专属指令】
"""


def _inject_standard_prompt(config: SubAgentConfig) -> SubAgentConfig:
    """为预设子代理注入标准化Prompt前缀"""
    if not config.prompt or SUBAGENT_PROMPT_PREAMBLE in config.prompt:
        return config
    new_prompt = SUBAGENT_PROMPT_PREAMBLE + config.prompt
    # 使用replace创建新实例（dataclass不可变字段安全替换）
    from dataclasses import replace
    return replace(config, prompt=new_prompt)
from core.logger import logger
from core.subagent.runtime import SubAgentResult, SubAgentRuntime, SubAgentStatus

# 【P1修复】导入实时干预系统
try:
    from core.agent.realtime_intervention import ExecutionAdaptation, check_and_apply_intervention
    INTERVENTION_AVAILABLE = True
except ImportError:
    INTERVENTION_AVAILABLE = False

import contextlib
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

# ==================== 【新增】流水线执行相关类 ====================

class PipelineStepType(Enum):
    """流水线步骤类型"""
    SEQUENTIAL = "sequential"  # 顺序执行
    PARALLEL = "parallel"      # 并行执行
    CONDITIONAL = "conditional" # 条件执行


class PipelineStepStatus(Enum):
    """流水线步骤状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    PAUSED = "paused"


@dataclass
class PipelineStep:
    """流水线步骤定义"""
    agent_name: str
    task: str
    step_type: PipelineStepType = PipelineStepType.SEQUENTIAL
    status: PipelineStepStatus = PipelineStepStatus.PENDING
    condition: str | None = None  # 条件表达式
    depends_on: list[str] = field(default_factory=list)  # 依赖的步骤ID
    step_id: str | None = None
    on_complete: str | None = None  # 完成后触发的动作

    # 运行时信息
    runtime_id: str | None = None
    output: str | None = None
    error: str | None = None
    start_time: float | None = None
    end_time: float | None = None
    progress: int | None = None

    def __post_init__(self):
        if self.step_id is None:
            self.step_id = f"step_{id(self)}"


@dataclass
class PipelineEvent:
    """流水线事件"""
    step: str
    runtime_id: str
    type: str
    content: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class PipelineResult:
    """流水线执行结果"""
    success: bool
    results: list[SubAgentResult]
    execution_time: float
    step_results: dict[str, SubAgentResult] = field(default_factory=dict)


# ==================== 【新增】Windows兼容工具适配器 ====================

class CrossPlatformToolAdapter:
    """
    跨平台工具适配器 - Windows兼容实现

    替代Unix工具：find, grep, bash
    """

    def __init__(self):
        self.is_windows = os.name == 'nt'
        self.shell = self._detect_shell()

    def _detect_shell(self) -> str:
        """检测可用的shell"""
        if os.name == 'nt':
            import shutil
            if shutil.which('powershell'):
                return 'powershell'
            return 'cmd'
        else:
            import shutil
            if shutil.which('bash'):
                return 'bash'
            return 'sh'

    # ========== 文件操作适配 ==========

    async def find_files(self, pattern: str, path: str = ".", file_type: str | None = None) -> list[dict[str, Any]]:
        """
        跨平台文件查找（异步版本）

        Unix: find . -name "*.py" -type f
        Windows: 使用 pathlib
        【Phase 2】使用 asyncio.to_thread 避免磁盘 IO 阻塞事件循环。
        """
        return await asyncio.to_thread(self._find_files_sync, pattern, path, file_type)

    def _find_files_sync(self, pattern: str, path: str, file_type: str | None) -> list[dict[str, Any]]:
        """find_files 的同步实现（在 to_thread 中执行）"""
        results = []
        root = Path(path).resolve()
        try:
            for file_path in root.rglob(pattern):
                if file_type == 'f' and not file_path.is_file():
                    continue
                if file_type == 'd' and not file_path.is_dir():
                    continue
                stat = file_path.stat()
                results.append({
                    "path": str(file_path),
                    "name": file_path.name,
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                    "is_file": file_path.is_file(),
                    "is_dir": file_path.is_dir()
                })
        except Exception as e:
            logger.error(f"[CrossPlatformToolAdapter] 文件查找失败: {e}")
        return results

    async def grep_content(self, pattern: str, path: str = ".", file_pattern: str = "*") -> list[dict[str, Any]]:
        """
        跨平台内容搜索（异步版本）

        Unix: grep -r "pattern" . --include="*.py"
        Windows: Python re模块实现
        【Phase 2】使用 asyncio.to_thread 避免磁盘 IO 阻塞事件循环。
        """
        return await asyncio.to_thread(self._grep_content_sync, pattern, path, file_pattern)

    def _grep_content_sync(self, pattern: str, path: str, file_pattern: str) -> list[dict[str, Any]]:
        """grep_content 的同步实现（在 to_thread 中执行）"""
        results = []
        try:
            regex = re.compile(pattern, re.IGNORECASE)
            root = Path(path).resolve()
            for file_path in root.rglob(file_pattern):
                if not file_path.is_file():
                    continue
                if file_path.stat().st_size > 10 * 1024 * 1024:  # >10MB
                    continue
                try:
                    content = file_path.read_text(encoding='utf-8', errors='ignore')
                    lines = content.split('\n')
                    for line_num, line in enumerate(lines, 1):
                        if regex.search(line):
                            results.append({
                                "file": str(file_path),
                                "line": line_num,
                                "content": line.strip(),
                                "context": self._get_context(lines, line_num)
                            })
                except Exception:
                    continue
        except Exception as e:
            logger.error(f"[CrossPlatformToolAdapter] 内容搜索失败: {e}")
        return results

    def _get_context(self, lines: list[str], line_num: int, context_lines: int = 2) -> list[str]:
        """获取代码上下文（同步辅助方法，在 to_thread 中调用）"""
        start = max(0, line_num - context_lines - 1)
        end = min(len(lines), line_num + context_lines)
        return lines[start:end]

    async def read_file(self, path: str, offset: int = 0, limit: int = 100) -> str:
        """读取文件内容（异步版本）
        【Phase 2】使用 asyncio.to_thread 避免磁盘 IO 阻塞事件循环。
        """
        return await asyncio.to_thread(self._read_file_sync, path, offset, limit)

    def _read_file_sync(self, path: str, offset: int, limit: int) -> str:
        """read_file 的同步实现（在 to_thread 中执行）"""
        file_path = Path(path)
        if not file_path.exists():
            return f"[Error: File not found: {path}]"
        try:
            content = file_path.read_text(encoding='utf-8', errors='ignore')
            lines = content.split('\n')
            return '\n'.join(lines[offset:offset+limit])
        except Exception as e:
            return f"[Error reading file: {e}]"

    def _unix_to_powershell(self, command: str) -> str:
        """将Unix命令转换为PowerShell"""
        translations = {
            r'\bls\b': 'Get-ChildItem',
            r'\bcat\b': 'Get-Content',
            r'\brm\b': 'Remove-Item',
            r'\bcp\b': 'Copy-Item',
            r'\bmv\b': 'Move-Item',
            r'\bmkdir\b': 'New-Item -ItemType Directory',
            r'\btouch\b': 'New-Item',
            r'\bgrep\b': 'Select-String',
            r'\bpwd\b': 'Get-Location',
            r'\becho\b': 'Write-Output',
            r'\bfind\b': 'Get-ChildItem -Recurse',
        }

        result = command
        for unix_cmd, ps_cmd in translations.items():
            result = re.sub(unix_cmd, ps_cmd, result)

        return result

    def _unix_to_cmd(self, command: str) -> str:
        """将Unix命令转换为CMD"""
        translations = {
            r'\bls\b': 'dir',
            r'\bcat\b': 'type',
            r'\brm\b': 'del',
            r'\bcp\b': 'copy',
            r'\bmv\b': 'move',
            r'\bmkdir\b': 'mkdir',
            r'\bpwd\b': 'cd',
            r'\becho\b': 'echo',
        }

        result = command
        for unix_cmd, cmd_cmd in translations.items():
            result = re.sub(unix_cmd, cmd_cmd, result)

        return result


# ==================== 子代理管理器（增强版） ====================

class SubAgentManager:
    """
    子代理管理器 - 增强版（支持流水线编排 + Windows兼容）

    管理子代理的注册、创建和委派
    """

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

        # 注册的配置
        self._configs: dict[str, SubAgentConfig] = {}

        # 活跃的运行时
        self._runtimes: dict[str, SubAgentRuntime] = {}

        # 【新增】跨平台工具适配器
        self.tool_adapter = CrossPlatformToolAdapter()

        # 【新增】流水线执行状态
        self._pipeline_executions: dict[str, PipelineResult] = {}

        # 加载预设（同步内联，避免在 __init__ 中调用 async 方法）
        for name, config in PRESET_SUBAGENTS.items():
            self._configs[name] = _inject_standard_prompt(config)
            logger.debug(f"[SubAgentManager] 加载预设: {name}")

        logger.info("[SubAgentManager] 子代理管理器初始化完成（增强版）")

    async def load_presets_async(self):
        """异步加载预设配置（供外部异步初始化使用）"""
        for name, config in PRESET_SUBAGENTS.items():
            self._configs[name] = _inject_standard_prompt(config)
            logger.debug(f"[SubAgentManager] 异步加载预设: {name}")

    async def register(self, config: SubAgentConfig):
        """注册子代理配置（异步版本）"""
        self._configs[config.name] = config
        logger.info(f"[SubAgentManager] 注册子代理: {config.name}")

    async def unregister(self, name: str) -> bool:
        """注销子代理（异步版本）"""
        if name in self._configs:
            del self._configs[name]
            logger.info(f"[SubAgentManager] 注销子代理: {name}")
            return True
        return False

    async def get_config(self, name: str) -> SubAgentConfig | None:
        """获取配置（异步版本）"""
        return self._configs.get(name)

    async def list_agents(self) -> list[dict[str, Any]]:
        """列出所有可用的子代理（异步版本）"""
        return [
            {
                "name": name,
                "description": config.description,
                "allowed_tools_count": len(config.allowed_tools),
                "model": config.model,
                "timeout": config.timeout,
                "parallel_safe": config.parallel_safe
            }
            for name, config in self._configs.items()
        ]

    async def is_registered(self, name: str) -> bool:
        """检查是否已注册（异步版本）"""
        return name in self._configs

    async def delegate(
        self,
        agent_name: str,
        task: str,
        parent_context: dict | None = None,
        child_context: dict | None = None
    ) -> SubAgentResult:
        """
        委派任务给子代理

        Args:
            agent_name: 子代理名称
            task: 任务描述
            parent_context: 父上下文
            child_context: 额外子上下文

        Returns:
            SubAgentResult: 执行结果
        """
        config = await self.get_config(agent_name)
        if not config:
            logger.error(f"[SubAgentManager] 未找到子代理配置: {agent_name}")
            return SubAgentResult(
                status=SubAgentStatus.FAILED,
                output="",
                error=f"未找到子代理配置: {agent_name}"
            )

        # 创建运行时
        runtime = SubAgentRuntime(config, parent_context)
        self._runtimes[runtime.runtime_id] = runtime

        try:
            # 执行
            logger.info(f"[SubAgentManager] 开始委派任务给 {agent_name}: {task[:50]}...")
            result = await runtime.run(task, child_context)

            logger.info(f"[SubAgentManager] 任务完成: {agent_name}, 状态: {result.status.value}")
            # 【ExperienceBus】子代理委派事件
            with contextlib.suppress(Exception):
                event_bus.emit("subagent:delegated", {
                    "agent_name": agent_name,
                    "status": result.status.value,
                    "timestamp": time.time(),
                })
            return result

        except Exception as e:
            logger.error(f"[SubAgentManager] 委派异常: {e}")
            # 【ExperienceBus】子代理失败事件
            with contextlib.suppress(Exception):
                event_bus.emit("subagent:delegated", {
                    "agent_name": agent_name,
                    "status": "FAILED",
                    "error": str(e),
                    "timestamp": time.time(),
                })
            return SubAgentResult(
                status=SubAgentStatus.FAILED,
                output="",
                error=str(e)
            )

        finally:
            # 清理
            if runtime.runtime_id in self._runtimes:
                del self._runtimes[runtime.runtime_id]

    async def parallel_delegate(
        self,
        tasks: list[tuple]
    ) -> list[SubAgentResult]:
        """
        并行委派多个任务

        Args:
            tasks: [(agent_name, task, parent_context, child_context), ...]

        Returns:
            List[SubAgentResult]: 结果列表
        """
        async def run_single(task_info):
            try:
                if len(task_info) >= 4:
                    agent_name, task, parent_context, child_context = task_info
                elif len(task_info) == 3:
                    agent_name, task, parent_context = task_info
                    child_context = None
                else:
                    agent_name, task = task_info
                    parent_context = None
                    child_context = None

                return await self.delegate(
                    agent_name, task, parent_context, child_context
                )
            except Exception as e:
                logger.error(f"[SubAgentManager] 并行任务执行失败: {e}")
                return SubAgentResult(
                    status=SubAgentStatus.FAILED,
                    output="",
                    error=str(e)
                )

        # 并发执行
        logger.info(f"[SubAgentManager] 开始并行执行 {len(tasks)} 个任务")
        coroutines = [run_single(task_info) for task_info in tasks]
        results = await asyncio.gather(*coroutines, return_exceptions=True)

        # 处理异常
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"[SubAgentManager] 任务 {i} 异常: {result}")
                processed_results.append(SubAgentResult(
                    status=SubAgentStatus.FAILED,
                    output="",
                    error=str(result)
                ))
            else:
                processed_results.append(result)

        success_count = sum(1 for r in processed_results if r.status == SubAgentStatus.COMPLETED)
        logger.info(f"[SubAgentManager] 并行执行完成: {success_count}/{len(tasks)} 成功")
        # 【ExperienceBus】流水线完成事件
        with contextlib.suppress(Exception):
            event_bus.emit("subagent:pipeline_completed", {
                "total_tasks": len(tasks),
                "success_count": success_count,
                "timestamp": time.time(),
            })

        return processed_results

    async def sequential_delegate(
        self,
        tasks: list[tuple]
    ) -> list[SubAgentResult]:
        """
        顺序委派多个任务（前一个结果传递给后一个）

        Args:
            tasks: [(agent_name, task_or_builder), ...]
                   task_or_builder 可以是字符串或函数
        """
        results = []
        previous_result = None

        logger.info(f"[SubAgentManager] 开始顺序执行 {len(tasks)} 个任务")

        for i, task_def in enumerate(tasks):
            try:
                if isinstance(task_def, tuple) and len(task_def) >= 2:
                    agent_name = task_def[0]
                    task_builder = task_def[1]
                else:
                    logger.error(f"[SubAgentManager] 无效的任务定义: {task_def}")
                    continue

                # 构建任务
                if callable(task_builder):
                    try:
                        task = task_builder(previous_result)
                    except Exception as e:
                        logger.error(f"[SubAgentManager] 任务构建器失败: {e}")
                        task = str(task_builder)
                else:
                    task = str(task_builder)

                # 构建上下文（包含前一个结果）
                context = {}
                if previous_result:
                    context["previous_output"] = previous_result.output
                    context["previous_data"] = previous_result.data

                # 执行
                logger.info(f"[SubAgentManager] 顺序执行步骤 {i+1}/{len(tasks)}: {agent_name}")
                result = await self.delegate(agent_name, task, None, context)

                results.append(result)
                previous_result = result

                # 如果失败，停止链式执行
                if result.status != SubAgentStatus.COMPLETED:
                    logger.warning(f"[SubAgentManager] 任务链中断于步骤 {i+1}: {agent_name} 失败")
                    break

            except Exception as e:
                logger.error(f"[SubAgentManager] 顺序执行步骤 {i+1} 异常: {e}")
                results.append(SubAgentResult(
                    status=SubAgentStatus.FAILED,
                    output="",
                    error=str(e)
                ))
                break

        logger.info(f"[SubAgentManager] 顺序执行完成: {len(results)}/{len(tasks)} 步骤")
        return results

    async def get_active_runtimes(self) -> dict[str, SubAgentRuntime]:
        """获取当前活跃的运行时（异步版本）"""
        return dict(self._runtimes)

    async def cancel_runtime(self, runtime_id: str) -> bool:
        """取消指定运行时（异步版本）"""
        if runtime_id in self._runtimes:
            self._runtimes[runtime_id].cancel()
            return True
        return False

    async def get_stats(self) -> dict[str, Any]:
        """获取统计信息（异步版本）"""
        return {
            "registered_agents": len(self._configs),
            "active_runtimes": len(self._runtimes),
            "preset_agents": list(PRESET_SUBAGENTS.keys())
        }

    # ==================== 【新增】父子关系委派 ====================

    async def delegate_with_parent(
        self,
        agent_name: str,
        task: str,
        parent_context: dict | None = None,
        parent_runtime: SubAgentRuntime | None = None
    ) -> SubAgentResult:
        """
        带父子关系的委派

        Args:
            agent_name: 子代理名称
            task: 任务描述
            parent_context: 父上下文
            parent_runtime: 父运行时（可选）

        Returns:
            SubAgentResult: 执行结果
        """
        config = await self.get_config(agent_name)
        if not config:
            logger.error(f"[SubAgentManager] 未找到子代理配置: {agent_name}")
            return SubAgentResult(
                status=SubAgentStatus.FAILED,
                output="",
                error=f"未找到子代理配置: {agent_name}"
            )

        # 创建运行时，传入父运行时
        runtime = SubAgentRuntime(config, parent_context, parent_runtime)
        self._runtimes[runtime.runtime_id] = runtime

        try:
            logger.info(f"[SubAgentManager] 父子委派: {agent_name} (父: {parent_runtime.runtime_id if parent_runtime else 'None'})")
            result = await runtime.run(task)
            return result

        finally:
            if runtime.runtime_id in self._runtimes:
                del self._runtimes[runtime.runtime_id]

    # ==================== 【新增】流水线编排 ====================

    async def run_pipeline(
        self,
        steps: list[PipelineStep],
        initial_context: dict[str, Any],
        stream: bool = True,
        slot_id: int | None = None,
        pipeline_name: str = "SubAgent流水线"
    ) -> AsyncGenerator[PipelineEvent, None]:
        """
        执行SubAgent流水线

        支持：顺序执行、并行执行、条件执行、依赖管理

        Args:
            steps: 流水线步骤列表
            initial_context: 初始上下文
            stream: 是否流式返回
            slot_id: 长任务槽位ID（用于WebSocket广播）
            pipeline_name: 流水线名称

        Yields:
            PipelineEvent: 流水线事件
        """
        import time
        start_time = time.time()
        context = initial_context.copy()
        executed_steps: dict[str, SubAgentResult] = {}

        # 初始化广播器
        broadcaster = None
        if slot_id is not None:
            try:
                from core.subagent.event_broadcaster import SubAgentEventBroadcaster
                broadcaster = SubAgentEventBroadcaster()
            except ImportError:
                pass

        # 创建流水线对象
        pipeline_id = f"pipeline_{int(time.time())}"

        async def broadcast_pipeline_status(current_step_id: str | None = None):
            """广播流水线状态"""
            if broadcaster and slot_id is not None:
                try:
                    from core.subagent.event_broadcaster import Pipeline as BPipeline
                    from core.subagent.event_broadcaster import PipelineStep as BPipelineStep
                    pipeline = BPipeline(
                        pipeline_id=pipeline_id,
                        name=pipeline_name,
                        description="自动编排的SubAgent流水线",
                        steps=[
                            BPipelineStep(
                                step_id=step.step_id,
                                agent_name=step.agent_name,
                                task=step.task,
                                step_type=step.step_type.value,
                                status=step.status.value if hasattr(step.status, 'value') else step.status,
                                condition=step.condition,
                                depends_on=step.depends_on,
                                on_complete=step.on_complete,
                                runtime_id=step.runtime_id,
                                output=step.output,
                                error=step.error,
                                start_time=step.start_time,
                                end_time=step.end_time,
                                progress=step.progress
                            )
                            for step in steps
                        ],
                        context=context,
                        created_at=start_time
                    )
                    await broadcaster.broadcast_pipeline_status(slot_id, pipeline, current_step_id)
                except Exception as e:
                    logger.debug(f"[SubAgentManager] 广播流水线状态失败: {e}")

        for step in steps:
            # 【P1修复】步骤级干预检查
            if INTERVENTION_AVAILABLE:
                try:
                    has_intervention, adaptation_type, details = check_and_apply_intervention(
                        task_id=f"{slot_id}_{step.step_id}",
                        current_working_memory=[{"role": "system", "content": f"执行流水线步骤: {step.agent_name}"}],
                        current_plan=None
                    )

                    if has_intervention:
                        logger.info(f"[SubAgentManager] 步骤 {step.step_id} 收到干预: {adaptation_type}")

                        if adaptation_type == ExecutionAdaptation.PAUSE.name:
                            step.status = PipelineStepStatus.PAUSED
                            await broadcast_pipeline_status(step.step_id)
                            yield PipelineEvent(
                                step=step.step_id,
                                runtime_id="",
                                type="pipeline_intervened",
                                content=f"步骤 {step.agent_name} 被暂停",
                                data={"intervention_type": "PAUSE", "reason": details.get("reason", "")}
                            )
                            # 暂停等待恢复（简单实现：跳过此步骤）
                            continue

                        elif adaptation_type == ExecutionAdaptation.SKIP.name:
                            step.status = PipelineStepStatus.SKIPPED
                            step.end_time = time.time()
                            await broadcast_pipeline_status(step.step_id)
                            yield PipelineEvent(
                                step=step.step_id,
                                runtime_id="",
                                type="step_skipped",
                                content=f"步骤 {step.agent_name} 被跳过",
                                data={"intervention_type": "SKIP", "reason": details.get("reason", "")}
                            )
                            continue

                        elif adaptation_type == ExecutionAdaptation.ABORT.name:
                            yield PipelineEvent(
                                step=step.step_id,
                                runtime_id="",
                                type="pipeline_aborted",
                                content="流水线被中止",
                                data={"intervention_type": "ABORT", "reason": details.get("reason", "")}
                            )
                            return

                except Exception as e:
                    logger.debug(f"[SubAgentManager] 步骤干预检查失败: {e}")

            # 更新步骤状态为运行中
            step.status = PipelineStepStatus.RUNNING
            step.start_time = time.time()
            await broadcast_pipeline_status(step.step_id)

            yield PipelineEvent(
                step=step.step_id,
                runtime_id="",
                type="step_started",
                content=f"开始执行步骤: {step.agent_name}",
                data={"agent": step.agent_name, "step_type": step.step_type.value}
            )

            # 检查依赖是否满足
            if step.depends_on:
                missing_deps = [d for d in step.depends_on if d not in executed_steps]
                if missing_deps:
                    step.status = PipelineStepStatus.FAILED
                    step.end_time = time.time()
                    await broadcast_pipeline_status()
                    yield PipelineEvent(
                        step=step.step_id,
                        runtime_id="",
                        type="error",
                        content=f"依赖步骤未完成: {missing_deps}",
                        data={"missing_dependencies": missing_deps}
                    )
                    continue

            # 检查条件
            if step.condition and not await self._evaluate_condition(step.condition, context):
                step.status = PipelineStepStatus.SKIPPED
                step.end_time = time.time()
                await broadcast_pipeline_status()
                yield PipelineEvent(
                    step=step.step_id,
                    runtime_id="",
                    type="skipped",
                    content=f"条件不满足: {step.condition}",
                    data={"condition": step.condition}
                )
                continue

            # 创建运行时
            config = await self.get_config(step.agent_name)
            if not config:
                step.status = PipelineStepStatus.FAILED
                step.end_time = time.time()
                await broadcast_pipeline_status()
                yield PipelineEvent(
                    step=step.step_id,
                    runtime_id="",
                    type="error",
                    content=f"未找到子代理: {step.agent_name}",
                    data={"agent_name": step.agent_name}
                )
                continue

            # 构建任务（支持模板变量）
            task = await self._render_template(step.task, context)

            # 流式执行
            if stream and hasattr(SubAgentRuntime, 'run_with_stream_events'):
                runtime = SubAgentRuntime(config, context)
                self._runtimes[runtime.runtime_id] = runtime
                step.runtime_id = runtime.runtime_id

                try:
                    full_output = []
                    async for event in runtime.run_with_stream_events(task, context, slot_id=slot_id):
                        yield PipelineEvent(
                            step=step.step_id,
                            runtime_id=runtime.runtime_id,
                            type=event.type,
                            content=event.content,
                            data={**event.data, "agent": step.agent_name}
                        )

                        if event.type == "complete":
                            full_output.append(event.content)

                        # 更新进度
                        if event.type == "progress" and event.data.get("progress"):
                            step.progress = event.data["progress"]
                            await broadcast_pipeline_status(step.step_id)

                        # 检查是否需要暂停
                        if event.type == "paused":
                            step.status = PipelineStepStatus.PAUSED
                            await broadcast_pipeline_status(step.step_id)
                            # 暂停流水线，等待恢复
                            yield PipelineEvent(
                                step=step.step_id,
                                runtime_id=runtime.runtime_id,
                                type="pipeline_paused",
                                content="流水线已暂停，等待用户确认",
                                data={"pause_reason": event.data.get("reason")}
                            )
                            return

                    # 步骤完成
                    step.status = PipelineStepStatus.COMPLETED
                    step.end_time = time.time()
                    step.output = "\n".join(full_output)
                    step.progress = 100
                    await broadcast_pipeline_status()

                    # 保存结果到上下文
                    result = SubAgentResult(
                        status=SubAgentStatus.COMPLETED,
                        output="\n".join(full_output),
                        data={"step_id": step.step_id}
                    )
                    executed_steps[step.step_id] = result
                    context[f"{step.agent_name}_result"] = result.output
                    context[f"{step.step_id}_result"] = result.output

                    yield PipelineEvent(
                        step=step.step_id,
                        runtime_id=runtime.runtime_id,
                        type="step_completed",
                        content=f"步骤 {step.agent_name} 完成",
                        data={"agent": step.agent_name, "output": step.output[:200]}
                    )

                except Exception as e:
                    step.status = PipelineStepStatus.FAILED
                    step.end_time = time.time()
                    step.error = str(e)
                    await broadcast_pipeline_status()
                    logger.error(f"[SubAgentManager] 步骤 {step.step_id} 执行失败: {e}")

                finally:
                    if runtime.runtime_id in self._runtimes:
                        del self._runtimes[runtime.runtime_id]
            else:
                # 非流式执行
                try:
                    result = await self.delegate(step.agent_name, task, context)
                    executed_steps[step.step_id] = result
                    context[f"{step.agent_name}_result"] = result.output
                    context[f"{step.step_id}_result"] = result.output

                    if result.status == SubAgentStatus.COMPLETED:
                        step.status = PipelineStepStatus.COMPLETED
                        step.output = result.output
                        step.progress = 100
                    else:
                        step.status = PipelineStepStatus.FAILED
                        step.error = result.error

                    step.end_time = time.time()
                    await broadcast_pipeline_status()

                    yield PipelineEvent(
                        step=step.step_id,
                        runtime_id="",
                        type="step_completed",
                        content=result.output,
                        data={"agent": step.agent_name, "status": result.status.value}
                    )
                except Exception as e:
                    step.status = PipelineStepStatus.FAILED
                    step.end_time = time.time()
                    step.error = str(e)
                    await broadcast_pipeline_status()
                    logger.error(f"[SubAgentManager] 步骤 {step.step_id} 执行失败: {e}")

        # 流水线完成
        execution_time = time.time() - start_time
        yield PipelineEvent(
            step="pipeline",
            runtime_id="",
            type="pipeline_complete",
            content=f"流水线执行完成，共 {len(steps)} 步",
            data={
                "total_steps": len(steps),
                "executed_steps": len(executed_steps),
                "execution_time": execution_time
            }
        )

    async def _evaluate_condition(self, condition: str, context: dict[str, Any]) -> bool:
        """评估条件表达式（异步版本）"""
        try:
            # 简单条件评估：检查上下文中是否有该键且值为真
            if condition in context:
                return bool(context[condition])

            # 支持简单的比较表达式
            if "==" in condition:
                left, right = condition.split("==", 1)
                left_val = context.get(left.strip(), left.strip())
                right_val = right.strip().strip('"\'')
                return str(left_val) == right_val

            return True
        except Exception as e:
            logger.warning(f"[SubAgentManager] 条件评估失败: {e}")
            return True

    async def _render_template(self, template: str, context: dict[str, Any]) -> str:
        """渲染任务模板（异步版本）"""
        import re

        def replace_var(match):
            var_name = match.group(1)
            return str(context.get(var_name, match.group(0)))

        return re.sub(r'\{\{(\w+)\}\}', replace_var, template)

    async def run_code_pipeline(
        self,
        user_request: str,
        file_context: str | None = None,
        stream: bool = True,
        slot_id: int | None = None
    ) -> AsyncGenerator[PipelineEvent, None]:
        """
        代码场景专用流水线

        自动编排：planner → code_generator → code_reviewer → tester
        """
        steps = [
            PipelineStep(
                agent_name="planner",
                task=f"规划代码实现: {user_request}",
                step_id="plan"
            ),
            PipelineStep(
                agent_name="code_generator",
                task=f"根据规划生成代码: {user_request}\n规划结果: {{planner_result}}",
                step_id="generate",
                depends_on=["plan"]
            ),
            PipelineStep(
                agent_name="code_reviewer",
                task="审查生成的代码\n代码: {code_generator_result}",
                step_id="review",
                depends_on=["generate"]
            ),
            PipelineStep(
                agent_name="tester",
                task="为审查通过的代码生成测试\n代码: {code_generator_result}\n审查意见: {code_reviewer_result}",
                step_id="test",
                depends_on=["review"],
                condition="code_reviewer_result"
            ),
        ]

        context = {
            "user_request": user_request,
            "file_context": file_context or "",
            "timestamp": time.time()
        }

        async for event in self.run_pipeline(steps, context, stream, slot_id=slot_id, pipeline_name="代码生成流水线"):
            yield event

    # ==================== 【新增】Windows兼容工具方法 ====================

    async def execute_with_windows_compat(
        self,
        tool_name: str,
        params: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Windows兼容的工具执行

        Args:
            tool_name: 工具名称
            params: 工具参数

        Returns:
            Dict: 工具执行结果
        """
        if tool_name == "file_search":
            return {
                "success": True,
                "results": self.tool_adapter.find_files(
                    pattern=params.get("pattern", "*"),
                    path=params.get("path", "."),
                    file_type=params.get("file_type")
                )
            }

        elif tool_name == "content_search":
            return {
                "success": True,
                "results": self.tool_adapter.grep_content(
                    pattern=params.get("pattern", ""),
                    path=params.get("path", "."),
                    file_pattern=params.get("file_pattern", "*")
                )
            }

        elif tool_name == "file_read":
            content = self.tool_adapter.read_file(
                path=params.get("path", ""),
                offset=params.get("offset", 0),
                limit=params.get("limit", 100)
            )
            return {"success": not content.startswith("[Error"), "content": content}

        else:
            return {"success": False, "error": f"未知工具: {tool_name}"}

    async def get_tool_adapter(self) -> CrossPlatformToolAdapter:
        """获取工具适配器（异步版本）"""
        return self.tool_adapter

    # ==================== 【Week 3】子代理干预通知管理 ====================

    async def get_runtime(self, runtime_id: str) -> SubAgentRuntime | None:
        """
        【Week 3】获取运行时实例（异步版本）

        Args:
            runtime_id: 运行时ID

        Returns:
            SubAgentRuntime: 运行时实例，如果不存在则返回None
        """
        return self._runtimes.get(runtime_id)

    async def get_child_interventions_for_task(self, task_id: str | None) -> list[dict[str, Any]]:
        """
        【Week 3】获取任务关联的子代理干预事件（异步版本）

        遍历所有活跃的运行时，收集其子代理的干预事件。

        Args:
            task_id: 任务ID（父代理的任务ID）

        Returns:
            干预事件列表
        """
        interventions = []

        if not task_id:
            return interventions

        try:
            # 遍历所有活跃的运行时
            for _runtime_id, runtime in self._runtimes.items():
                # 检查该运行时是否有父代理
                parent = getattr(runtime, 'parent', None)
                if parent:
                    parent_task_id = getattr(parent, 'runtime_id', None)

                    # 如果父代理的任务ID匹配且有干预事件
                    if parent_task_id == task_id and hasattr(runtime, 'has_child_interventions') and runtime.has_child_interventions():
                        # 获取干预事件（不清除，因为可能还有其他地方需要）
                        child_interventions = runtime.get_child_interventions(clear=False)
                        for intervention in child_interventions:
                            interventions.append({
                                "child_id": runtime.runtime_id,
                                "child_name": runtime.config.name if runtime.config else "Unknown",
                                "parent_task_id": task_id,
                                **intervention
                            })

            if interventions:
                logger.info(f"[SubAgentManager] 任务 {task_id} 收集到 {len(interventions)} 个子代理干预事件")

        except Exception as e:
            logger.error(f"[SubAgentManager] 获取子代理干预事件失败: {e}")

        return interventions

    async def clear_child_interventions(self, runtime_id: str) -> bool:
        """
        【Week 3】清除子代理的干预事件（异步版本）

        Args:
            runtime_id: 子代理运行时ID

        Returns:
            是否成功清除
        """
        try:
            runtime = self._runtimes.get(runtime_id)
            if runtime and hasattr(runtime, '_child_interventions'):
                runtime._child_interventions.clear()
                return True
        except Exception as e:
            logger.error(f"[SubAgentManager] 清除干预事件失败: {e}")
        return False


# 全局实例
subagent_manager = SubAgentManager()
