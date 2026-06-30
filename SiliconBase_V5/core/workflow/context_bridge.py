#!/usr/bin/env python3
"""
ContextBridge - 上下文智能搬运系统 V1.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
自动关联相关记忆、关键步骤感知注入、历史成功模式检索、跨步骤上下文传递优化

【核心特性】
1. 自动关联相关记忆 - 基于语义相似度检索长期记忆
2. 关键步骤感知注入 - 智能判断关键步骤并捕获环境感知
3. 历史成功模式检索 - 查询类似任务的成功执行模式
4. 跨步骤上下文传递 - 优化步骤间的上下文传递

【架构位置】
- 位于: core/workflow/context_bridge.py
- 调用方: WorkflowExecutor、SubAgentStep
- 依赖: WorkingMemory、VectorMemoryManager、PerceptionFusion
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

# 导入项目组件
try:
    from core.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger('context_bridge')

# 类型导入（避免循环依赖）
try:
    from core.workflow.workflow_engine import WorkflowExecution, WorkflowStep
except ImportError:
    WorkflowStep = Any
    WorkflowExecution = Any

try:
    from core.workflow.perception_fusion import PerceptionFusion, UnifiedPerceptionContext
except ImportError:
    PerceptionFusion = Any
    UnifiedPerceptionContext = Any

try:
    from core.memory.working_memory import WorkingMemory
except ImportError:
    WorkingMemory = Any

try:
    from core.memory.vector_store import SearchResult
except ImportError:
    SearchResult = Any

# 【P1-迁移】vector_memory 已废弃，改为通过 MemoryService 获取 VectorStore
# try:
#     from core.memory.vector_memory import VectorMemoryManager, SearchResult
# except ImportError:
#     VectorMemoryManager = Any
#     SearchResult = Any
VectorMemoryManager = Any  # 兼容旧签名，避免类型未定义


# ═══════════════════════════════════════════════════════════════════════════════
# 数据类定义
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class RelatedMemory:
    """相关记忆数据类"""
    memory_id: str
    content: str
    memory_type: str  # experience, knowledge, pattern
    similarity: float
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "memory_id": self.memory_id,
            "content": self.content[:200] + "..." if len(self.content) > 200 else self.content,
            "memory_type": self.memory_type,
            "similarity": round(self.similarity, 4),
            "metadata": self.metadata,
            "timestamp": self.timestamp
        }


@dataclass
class HistoricalPattern:
    """历史成功模式数据类"""
    pattern_id: str
    pattern_type: str
    description: str
    success_rate: float
    usage_count: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "pattern_id": self.pattern_id,
            "pattern_type": self.pattern_type,
            "description": self.description[:200] + "..." if len(self.description) > 200 else self.description,
            "success_rate": round(self.success_rate, 2),
            "usage_count": self.usage_count,
            "metadata": self.metadata
        }


@dataclass
class StepContext:
    """步骤上下文数据类"""
    execution_id: str
    step_id: str
    step_name: str
    step_index: int
    variables: dict[str, Any] = field(default_factory=dict)
    step_results: dict[str, Any] = field(default_factory=dict)
    related_memories: list[RelatedMemory] = field(default_factory=list)
    memory_summary: str = ""
    perception: dict[str, Any] | None = None
    environment_state: str | None = None
    historical_patterns: list[HistoricalPattern] = field(default_factory=list)
    previous_summary: str | None = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "execution_id": self.execution_id,
            "step_id": self.step_id,
            "step_name": self.step_name,
            "step_index": self.step_index,
            "variables": self.variables,
            "step_results": dict(list(self.step_results.items())[-5:]),  # 最近5个结果
            "related_memories": [m.to_dict() for m in self.related_memories],
            "memory_summary": self.memory_summary,
            "perception": self.perception,
            "environment_state": self.environment_state,
            "historical_patterns": [p.to_dict() for p in self.historical_patterns],
            "previous_summary": self.previous_summary,
            "timestamp": self.timestamp
        }


# ═══════════════════════════════════════════════════════════════════════════════
# 上下文智能搬运系统主类
# ═══════════════════════════════════════════════════════════════════════════════

class ContextIntelligence:
    """
    上下文智能搬运系统

    职责：
    1. 自动关联相关记忆
    2. 关键步骤感知注入
    3. 历史成功模式检索
    4. 跨步骤上下文传递优化

    使用示例：
        context_intel = ContextIntelligence(
            working_memory=wm,
            vector_memory_manager=vmm,
            perception_fusion=pf
        )

        context = await context_intel.prepare_step_context(
            execution=workflow_execution,
            step=current_step,
            step_index=3,
            user_id="user_123"
        )
    """

    # 关键步骤类别定义
    CRITICAL_CATEGORIES = ["launch", "save", "transform", "ui", "verify"]

    # 默认配置
    DEFAULT_CONFIG = {
        "memory_query_limit": 5,
        "memory_min_similarity": 0.5,
        "pattern_query_limit": 3,
        "pattern_min_importance": 0.7,
        "enable_perception": True,
        "perception_timeout": 30,
        "max_memory_results": 3,
        "max_pattern_results": 3
    }

    def __init__(
        self,
        working_memory: WorkingMemory | None = None,
        vector_memory_manager: VectorMemoryManager | None = None,
        perception_fusion: PerceptionFusion | None = None,
        config: dict[str, Any] | None = None
    ):
        """
        初始化上下文智能搬运系统

        Args:
            working_memory: 工作记忆实例（短期记忆）
            vector_memory_manager: 向量记忆管理器（长期记忆）
            perception_fusion: 感知融合中心
            config: 配置字典（可选）
        """
        self.working_memory = working_memory
        # 【P1-迁移】vector_memory 已废弃，改为在方法内部通过 MemoryService 获取
        # self.vector_memory = vector_memory_manager
        self.vector_memory = None  # 兼容旧代码的检查逻辑
        self.perception = perception_fusion
        self.config = {**self.DEFAULT_CONFIG, **(config or {})}

        # 缓存相关
        self._memory_cache: dict[str, tuple[list[RelatedMemory], float]] = {}
        self._cache_ttl = 60  # 缓存60秒

        logger.info("[ContextIntelligence] 上下文智能搬运系统初始化完成")

    async def prepare_step_context(
        self,
        execution: WorkflowExecution,
        step: WorkflowStep,
        step_index: int,
        user_id: str = "default"
    ) -> StepContext:
        """
        准备步骤执行上下文

        【融合增强】自动注入：
        - 相关记忆
        - 感知信息
        - 历史模式

        Args:
            execution: 工作流执行实例
            step: 当前步骤
            step_index: 步骤索引
            user_id: 用户ID

        Returns:
            StepContext: 完整的步骤上下文
        """
        start_time = time.time()

        try:
            # 获取执行ID和步骤ID
            execution_id = getattr(execution, 'execution_id', str(id(execution)))
            step_id = getattr(step, 'step_id', str(id(step)))
            step_name = getattr(step, 'name', '未命名步骤')

            logger.info(f"[ContextIntelligence] 准备步骤上下文: {step_name} (index={step_index})")

            # 创建基础上下文
            context = StepContext(
                execution_id=execution_id,
                step_id=step_id,
                step_name=step_name,
                step_index=step_index
            )

            # 1. 基础变量（原有）
            context.variables = getattr(execution, 'variables', {})
            context.step_results = getattr(execution, 'step_results', {})

            # 2. 【新增】智能关联长期记忆
            try:
                related_memories = await self._query_related_memories(step, execution, user_id)
                if related_memories:
                    context.related_memories = related_memories
                    context.memory_summary = self._summarize_memories(related_memories)
                    logger.debug(f"[ContextIntelligence] 关联 {len(related_memories)} 条相关记忆")
            except Exception as e:
                logger.warning(f"[ContextIntelligence] 查询相关记忆失败: {e}")

            # 3. 【新增】关键步骤感知注入
            if self.config["enable_perception"] and self._is_critical_step(step):
                try:
                    perception = await self._capture_step_perception(step)
                    if perception:
                        context.perception = perception
                        context.environment_state = perception.get("description", "")
                        logger.debug("[ContextIntelligence] 已捕获关键步骤感知")
                except Exception as e:
                    logger.warning(f"[ContextIntelligence] 感知捕获失败: {e}")

            # 4. 【新增】历史成功模式
            try:
                patterns = await self._query_historical_patterns(step, user_id)
                if patterns:
                    context.historical_patterns = patterns
                    logger.debug(f"[ContextIntelligence] 检索到 {len(patterns)} 个历史模式")
            except Exception as e:
                logger.warning(f"[ContextIntelligence] 查询历史模式失败: {e}")

            # 5. 【新增】前序关键步骤结果摘要
            if step_index > 0:
                try:
                    context.previous_summary = self._summarize_previous_steps(
                        execution, step_index
                    )
                except Exception as e:
                    logger.warning(f"[ContextIntelligence] 生成前序摘要失败: {e}")

            elapsed = time.time() - start_time
            logger.info(f"[ContextIntelligence] 上下文准备完成，耗时: {elapsed:.3f}s")

            return context

        except Exception as e:
            logger.error(f"[ContextIntelligence] 准备步骤上下文失败: {e}")
            # 返回最小化的上下文
            return StepContext(
                execution_id=getattr(execution, 'execution_id', 'unknown'),
                step_id=getattr(step, 'step_id', 'unknown'),
                step_name=getattr(step, 'name', '未命名步骤'),
                step_index=step_index
            )

    async def _query_related_memories(
        self,
        step: WorkflowStep,
        execution: WorkflowExecution,
        user_id: str = "default"
    ) -> list[RelatedMemory]:
        """
        查询与当前步骤相关的长期记忆

        基于步骤名称、描述、工具ID等构建查询，从长期记忆中检索相关记忆。

        Args:
            step: 当前步骤
            execution: 工作流执行实例
            user_id: 用户ID

        Returns:
            List[RelatedMemory]: 相关记忆列表
        """
        # 构建查询文本
        query_parts = [getattr(step, 'name', '')]

        description = getattr(step, 'description', None)
        if description:
            query_parts.append(description)

        tool_id = getattr(step, 'tool_id', None)
        if tool_id:
            query_parts.append(tool_id)

        # 尝试获取子代理信息
        subagent = getattr(step, 'subagent', None)
        if subagent:
            query_parts.append(str(subagent))

        query = " ".join(filter(None, query_parts))
        if not query.strip():
            logger.debug("[ContextIntelligence] 查询文本为空，跳过记忆查询")
            return []

        try:
            # 检查缓存
            cache_key = f"{user_id}:{hash(query)}"
            if cache_key in self._memory_cache:
                cached_memories, cache_time = self._memory_cache[cache_key]
                if time.time() - cache_time < self._cache_ttl:
                    logger.debug("[ContextIntelligence] 使用缓存的记忆查询结果")
                    return cached_memories

            from core.memory.memory_service import get_memory_service
            memory_service = await get_memory_service()
            vector_store = memory_service.vector_store

            if not await vector_store.is_available():
                logger.debug("[ContextIntelligence] VectorStore 不可用，跳过记忆查询")
                return []

            # 查询多个集合
            memories = []
            collections = ["experience", "knowledge", "execution"]

            for collection in collections:
                try:
                    results = await vector_store.search(
                        collection=collection,
                        query=query,
                        limit=self.config["memory_query_limit"]
                    )

                    for result in results:
                        similarity = 1.0 - (result.distance or 0.0)
                        if similarity >= self.config["memory_min_similarity"]:
                            memory = RelatedMemory(
                                memory_id=result.id,
                                content=result.document,
                                memory_type=collection,
                                similarity=similarity,
                                metadata=result.metadata or {}
                            )
                            memories.append(memory)

                except Exception as e:
                    logger.debug(f"[ContextIntelligence] 查询集合 {collection} 失败: {e}")
                    continue

            # 按相似度排序并限制数量
            memories.sort(key=lambda m: m.similarity, reverse=True)
            memories = memories[:self.config["max_memory_results"]]

            # 更新缓存
            self._memory_cache[cache_key] = (memories, time.time())

            return memories

        except Exception as e:
            logger.warning(f"[ContextIntelligence] 查询相关记忆异常: {e}")
            return []

    def _is_critical_step(self, step: WorkflowStep) -> bool:
        """
        判断是否为关键步骤（需要感知）

        关键步骤包括：
        - 启动类步骤（launch）
        - 保存类步骤（save）
        - 转换类步骤（transform）
        - UI交互类步骤（ui）
        - 验证类步骤（包含verify关键字）

        Args:
            step: 工作流步骤

        Returns:
            bool: 是否为关键步骤
        """
        # 获取步骤类别
        category = getattr(step, 'step_category', None) or getattr(step, 'category', 'action')
        name = getattr(step, 'name', '').lower()

        # 检查类别
        if category in self.CRITICAL_CATEGORIES:
            return True

        # 检查元数据标记
        metadata = getattr(step, 'metadata', {}) or {}
        if metadata.get('critical', False):
            return True

        # 检查名称中包含验证关键字
        if 'verify' in name or '验证' in name or '检查' in name:
            return True

        # 检查是否为关键步骤标记
        return bool(getattr(step, 'is_critical', False))

    async def _capture_step_perception(
        self,
        step: WorkflowStep
    ) -> dict[str, Any] | None:
        """
        捕获步骤执行环境感知

        使用 PerceptionFusion 捕获当前步骤的执行环境感知信息。

        Args:
            step: 工作流步骤

        Returns:
            Optional[Dict[str, Any]]: 感知数据字典，失败返回None
        """
        if not self.perception:
            logger.debug("[ContextIntelligence] 感知融合中心未配置，跳过感知捕获")
            return None

        try:
            # 获取步骤类别和名称
            category = getattr(step, 'step_category', 'action') or getattr(step, 'category', 'action')
            name = getattr(step, 'name', '未命名步骤')

            # 使用 asyncio.wait_for 添加超时控制
            # 注意：这里假设 perception 有 capture_for_step 方法
            if hasattr(self.perception, 'capture_for_step'):
                perception_context = await asyncio.wait_for(
                    self._run_perception_capture(category, name),
                    timeout=self.config["perception_timeout"]
                )

                if perception_context:
                    return perception_context.to_dict() if hasattr(perception_context, 'to_dict') else perception_context
            else:
                # 降级：使用普通 capture 方法
                if hasattr(self.perception, 'capture'):
                    perception_context = await self.perception.capture()
                    return perception_context.to_dict() if hasattr(perception_context, 'to_dict') else {}

        except asyncio.TimeoutError:
            logger.warning(f"[ContextIntelligence] 感知捕获超时 ({self.config['perception_timeout']}s)")
        except Exception as e:
            logger.warning(f"[ContextIntelligence] 感知捕获失败: {e}")

        return None

    async def _run_perception_capture(self, category: str, name: str) -> Any:
        """
        运行感知捕获

        Args:
            category: 步骤类别
            name: 步骤名称

        Returns:
            Any: 感知上下文
        """
        return await self.perception.capture_for_step(
            step_category=category,
            step_goal=name
        )

    async def _query_historical_patterns(
        self,
        step: WorkflowStep,
        user_id: str = "default"
    ) -> list[HistoricalPattern]:
        """
        查询历史成功模式

        检索与当前步骤类型相似的历史成功执行模式。

        Args:
            step: 工作流步骤
            user_id: 用户ID

        Returns:
            List[HistoricalPattern]: 历史模式列表
        """
        try:
            from core.memory.memory_service import get_memory_service
            memory_service = await get_memory_service()
            vector_store = memory_service.vector_store

            if not await vector_store.is_available():
                logger.debug("[ContextIntelligence] VectorStore 不可用，跳过模式查询")
                return []
        except Exception as e:
            logger.debug(f"[ContextIntelligence] 获取 VectorStore 失败，跳过模式查询: {e}")
            return []

        # 构建查询
        tool_id = getattr(step, 'tool_id', None)
        subagent = getattr(step, 'subagent', None)
        name = getattr(step, 'name', '')

        query_parts = []
        if tool_id:
            query_parts.append(f"{tool_id} success pattern")
        if subagent:
            query_parts.append(f"{subagent} success pattern")
        if not query_parts:
            query_parts.append(f"{name} success pattern")

        query = " ".join(query_parts)

        try:
            # 查询经验集合中的成功模式
            results = await vector_store.search(
                collection="experience",
                query=query,
                limit=self.config["pattern_query_limit"]
            )

            patterns = []
            for result in results:
                # 计算重要性分数
                importance = result.metadata.get('importance', 0.5) if result.metadata else 0.5

                if importance >= self.config["pattern_min_importance"]:
                    pattern = HistoricalPattern(
                        pattern_id=result.id,
                        pattern_type=result.metadata.get('pattern_type', 'general') if result.metadata else 'general',
                        description=result.document,
                        success_rate=result.metadata.get('success_rate', 0.8) if result.metadata else 0.8,
                        usage_count=result.metadata.get('usage_count', 1) if result.metadata else 1,
                        metadata=result.metadata or {}
                    )
                    patterns.append(pattern)

            # 限制数量
            patterns = patterns[:self.config["max_pattern_results"]]

            return patterns

        except Exception as e:
            logger.warning(f"[ContextIntelligence] 查询历史模式失败: {e}")
            return []

    def _summarize_memories(self, memories: list[RelatedMemory]) -> str:
        """
        总结相关记忆

        将相关记忆列表总结为简洁的文本描述。

        Args:
            memories: 相关记忆列表

        Returns:
            str: 记忆摘要
        """
        if not memories:
            return ""

        summaries = []
        for memory in memories[:2]:  # 只取前2个
            content = memory.content[:100] + "..." if len(memory.content) > 100 else memory.content
            summaries.append(f"[{memory.memory_type}] {content}")

        return " | ".join(summaries)

    def _summarize_previous_steps(
        self,
        execution: WorkflowExecution,
        current_index: int,
        max_steps: int = 3
    ) -> str:
        """
        总结前序关键步骤

        提取当前步骤之前的关键步骤执行结果摘要。

        Args:
            execution: 工作流执行实例
            current_index: 当前步骤索引
            max_steps: 最大总结步骤数

        Returns:
            str: 前序步骤摘要
        """
        try:
            # 获取步骤结果
            step_results = getattr(execution, 'step_results', {})
            if not step_results:
                return ""

            # 获取最近的步骤结果
            summaries = []
            result_items = list(step_results.items())

            # 取最近的几个结果
            for key, value in result_items[-max_steps:]:
                success = value.get('success', False) if isinstance(value, dict) else False
                status = "✓" if success else "✗"

                # 提取简要信息
                if isinstance(value, dict):
                    msg = value.get('message', value.get('error', '无详细信息'))
                else:
                    msg = str(value)[:50]

                summaries.append(f"{status} {key}: {msg[:30]}...")

            return " → ".join(summaries) if summaries else ""

        except Exception as e:
            logger.debug(f"[ContextIntelligence] 总结前序步骤失败: {e}")
            return ""

    def clear_cache(self) -> int:
        """
        清空记忆查询缓存

        Returns:
            int: 清空的缓存条目数
        """
        count = len(self._memory_cache)
        self._memory_cache.clear()
        logger.info(f"[ContextIntelligence] 已清空 {count} 条缓存")
        return count

    def get_stats(self) -> dict[str, Any]:
        """
        获取统计信息

        Returns:
            Dict: 统计信息字典
        """
        return {
            "cache_size": len(self._memory_cache),
            "config": self.config,
            "components": {
                "working_memory": self.working_memory is not None,
                "vector_memory": self.vector_memory is not None,
                "perception": self.perception is not None
            }
        }


# ═══════════════════════════════════════════════════════════════════════════════
# 便捷函数和工厂方法
# ═══════════════════════════════════════════════════════════════════════════════

_context_intelligence_instance: ContextIntelligence | None = None


def get_context_intelligence(
    working_memory: WorkingMemory | None = None,
    vector_memory_manager: VectorMemoryManager | None = None,
    perception_fusion: PerceptionFusion | None = None,
    config: dict[str, Any] | None = None
) -> ContextIntelligence:
    """
    获取 ContextIntelligence 单例实例

    Args:
        working_memory: 工作记忆实例
        vector_memory_manager: 向量记忆管理器
        perception_fusion: 感知融合中心
        config: 配置字典

    Returns:
        ContextIntelligence: 单例实例
    """
    global _context_intelligence_instance

    if _context_intelligence_instance is None:
        _context_intelligence_instance = ContextIntelligence(
            working_memory=working_memory,
            vector_memory_manager=vector_memory_manager,
            perception_fusion=perception_fusion,
            config=config
        )

    return _context_intelligence_instance


def reset_context_intelligence():
    """重置 ContextIntelligence 单例"""
    global _context_intelligence_instance
    _context_intelligence_instance = None
    logger.info("[ContextIntelligence] 单例已重置")


# ═══════════════════════════════════════════════════════════════════════════════
# 文件角色总结
# ═══════════════════════════════════════════════════════════════════════════════
#
# 【核心定位】
# 本文件是 SiliconBase V5 系统的"上下文智能搬运系统"，负责在工作流执行过程中
# 自动关联相关记忆、注入感知信息、检索历史成功模式，实现智能化的上下文管理。
#
# 【架构设计】
# - 自动记忆关联: 基于语义相似度从长期记忆中检索相关信息
# - 智能感知注入: 关键步骤自动捕获环境感知
# - 历史模式检索: 查询类似任务的成功执行模式
# - 上下文传递优化: 跨步骤传递关键信息和执行摘要
#
# 【关联文件】
# - core/workflow/workflow_engine.py     : 工作流引擎，调用 ContextIntelligence
# - core/workflow/perception_fusion.py   : 感知融合中心，提供感知数据
# - core/memory/working_memory.py        : 工作记忆，短期状态存储
# - core/memory/vector_memory.py         : 向量记忆，长期语义检索
#
# 【核心功能效果】
# 1. 记忆关联: 自动关联与当前步骤相关的历史记忆
# 2. 感知注入: 关键步骤自动捕获和注入环境感知
# 3. 模式复用: 检索历史成功模式指导当前执行
# 4. 上下文传递: 优化步骤间的上下文传递，避免信息丢失
# 5. 缓存优化: 记忆查询结果缓存，提高性能
#
# 【使用场景】
# - 多步骤工作流: 在工作流执行中自动准备步骤上下文
# - 长任务执行: 关联历史经验，提高长任务执行成功率
# - 关键步骤决策: 关键步骤获取环境感知，辅助决策
# - 模式学习: 从历史执行中提取成功模式，指导后续执行
# ═══════════════════════════════════════════════════════════════════════════════
