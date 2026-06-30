#!/usr/bin/env python3
"""
主动回忆机制 - 让AI主动联想相关记忆
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【核心思想】
  1. 主动触发 - 每次用户输入时主动检索相关记忆
  2. 语义相似度触发 - 基于用户输入与记忆的相似度触发
  3. 智能联想 - 自动关联L2工作记忆、L3经验模式、L4用户画像
  4. 可配置冷却 - 冷却时间可配置，支持不同场景

【触发条件】
  ✓ 用户输入与记忆库相似度 > 阈值
  ✓ 当前任务类型有相关经验记忆
  ✓ 用户明确询问"之前怎么做"
  ✓ AI表达不确定性（保留原有功能）
  ✓ 上下文发生显著变化

【联想机制】
  - L2 工作记忆: 检索与当前输入相关的短期工作记忆
  - L3 经验模式: 检索与当前任务相关的长期经验
  - L4 用户画像: 检索与用户相关的画像信息
"""

import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.logger import logger
from core.memory.memory_service import get_memory_service


async def _search_best_experience(query: str, limit: int = 1) -> list[dict[str, Any]]:
    """搜索最佳经验（异步辅助函数）"""
    ms = await get_memory_service()
    results = await ms.vector_store.search("experience", query, limit=limit)
    return [
        {
            "id": r.id,
            "document": r.document,
            "metadata": r.metadata,
            "similarity": 1.0 - (r.distance or 0.0)
        }
        for r in results
    ]


async def _search_knowledge(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """搜索知识（异步辅助函数）"""
    ms = await get_memory_service()
    results = await ms.vector_store.search("knowledge", query, limit=limit)
    return [
        {
            "id": r.id,
            "document": r.document,
            "metadata": r.metadata,
            "similarity": 1.0 - (r.distance or 0.0)
        }
        for r in results
    ]


from core.evolution.experience_injector import experience_injector


class UncertaintyLevel(Enum):
    """不确定性等级"""
    NONE = 0       # 确定
    LOW = 1        # 轻微不确定
    MEDIUM = 2     # 中等不确定
    HIGH = 3       # 高度不确定


class MemoryLevel(Enum):
    """记忆层级"""
    L2_WORKING = "l2_working"      # 工作记忆（短期）
    L3_EXPERIENCE = "l3_experience" # 经验模式（长期）
    L4_PROFILE = "l4_profile"      # 用户画像（持久）


@dataclass
class ContextState:
    """上下文状态数据类"""
    task_type: str = ""
    keywords: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    user_id: str | None = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_type": self.task_type,
            "keywords": self.keywords,
            "entities": self.entities,
            "user_id": self.user_id,
            "timestamp": self.timestamp
        }


@dataclass
class RecallResult:
    """回忆结果数据类"""
    triggered: bool
    reason: str
    experiences: list[dict[str, Any]] = field(default_factory=list)
    uncertainty_level: UncertaintyLevel = UncertaintyLevel.NONE
    context_change_score: float = 0.0
    similarity_score: float = 0.0
    memory_levels: list[MemoryLevel] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "triggered": self.triggered,
            "reason": self.reason,
            "experience_count": len(self.experiences),
            "uncertainty_level": self.uncertainty_level.name,
            "context_change_score": self.context_change_score,
            "similarity_score": self.similarity_score,
            "memory_levels": [level.value for level in self.memory_levels]
        }


@dataclass
class AssociationResult:
    """联想结果数据类"""
    l2_memories: list[dict[str, Any]] = field(default_factory=list)
    l3_experiences: list[dict[str, Any]] = field(default_factory=list)
    l4_profile_hints: list[dict[str, Any]] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.l2_memories or self.l3_experiences or self.l4_profile_hints)

    def merge(self) -> list[dict[str, Any]]:
        """合并所有层级的记忆"""
        all_memories = []
        for mem in self.l2_memories:
            mem["level"] = MemoryLevel.L2_WORKING.value
            all_memories.append(mem)
        for mem in self.l3_experiences:
            mem["level"] = MemoryLevel.L3_EXPERIENCE.value
            all_memories.append(mem)
        for mem in self.l4_profile_hints:
            mem["level"] = MemoryLevel.L4_PROFILE.value
            all_memories.append(mem)
        return all_memories


class ActiveRecall:
    """
    主动回忆管理器 - 智能触发记忆检索
    """

    # 不确定性关键词映射表
    UNCERTAINTY_PATTERNS = {
        UncertaintyLevel.HIGH: [
            r"不确定", r"不知道", r"不清楚", r"不了解", r"无法确定",
            r"un sure", r"don't know", r"no idea", r"cannot determine",
            r"不确定.*是什么", r"不太明白", r"不理解"
        ],
        UncertaintyLevel.MEDIUM: [
            r"可能", r"也许", r"大概", r"或许", r"应该",
            r"might", r"maybe", r"probably", r"could be", r"seems",
            r"看起来像", r"似乎是", r"可能是"
        ],
        UncertaintyLevel.LOW: [
            r"我觉得", r"我认为", r"我猜", r"我想",
            r"i think", r"i guess", r"i suppose", r"in my opinion"
        ]
    }

    # 上下文变化权重
    CONTEXT_WEIGHTS = {
        "task_type_change": 0.4,
        "keyword_overlap": 0.3,
        "entity_change": 0.3
    }

    # 用户主动询问记忆的关键词
    RECALL_TRIGGER_PATTERNS = [
        r"之前.*怎么.*",
        r"以前.*怎么.*",
        r"上次.*怎么.*",
        r"以前.*做.*",
        r"之前.*做.*",
        r"回忆.*一下",
        r"记得.*吗",
        r"how did.*before",
        r"what did.*last time",
        r"previous.*experience",
        r"last time.*did"
    ]

    def __init__(self,
                 uncertainty_threshold: float = 0.3,
                 context_change_threshold: float = 0.5,
                 similarity_threshold: float = 0.6,
                 max_recall_per_session: int = 10,
                 cooldown_seconds: float = 0.5,
                 enable_proactive: bool = True,
                 enable_association: bool = True):
        """
        初始化主动回忆管理器

        Args:
            uncertainty_threshold: 不确定性触发阈值 (0-1)
            context_change_threshold: 上下文变化触发阈值 (0-1)
            similarity_threshold: 语义相似度触发阈值 (0-1)
            max_recall_per_session: 每个会话最大回忆次数
            cooldown_seconds: 回忆冷却时间（秒），默认0.5秒（可配置）
            enable_proactive: 是否启用主动回忆
            enable_association: 是否启用联想机制
        """
        self.uncertainty_threshold = uncertainty_threshold
        self.context_change_threshold = context_change_threshold
        self.similarity_threshold = similarity_threshold
        self.max_recall_per_session = max_recall_per_session
        self.cooldown_seconds = cooldown_seconds
        self.enable_proactive = enable_proactive
        self.enable_association = enable_association

        # 状态追踪
        self._previous_context: ContextState | None = None
        self._session_recall_count: dict[str, int] = {}
        self._last_recall_time: dict[str, float] = {}
        self._context_history: list[ContextState] = []

        logger.info("[ActiveRecall] 主动回忆机制初始化完成")
        logger.info(f"[ActiveRecall] 配置: 相似度阈值={similarity_threshold}, 冷却={cooldown_seconds}s, 主动={enable_proactive}")

    async def should_recall_memory(self, user_input: str, context: dict[str, Any]) -> tuple[bool, str, float]:
        """
        判断是否应该触发记忆回忆（基于语义相似度）

        这是新的主动触发机制，每次用户输入时调用

        Args:
            user_input: 用户输入文本
            context: 当前上下文信息

        Returns:
            (是否应该触发, 原因, 相似度分数)
        """
        session_id = context.get("session_id", "default")

        # 检查冷却时间
        if not self._check_cooldown(session_id):
            return False, "冷却期内", 0.0

        # 1. 检查用户是否明确询问"之前怎么做"
        if self._is_explicit_recall_request(user_input):
            return True, "用户明确请求回忆历史经验", 1.0

        # 2. 基于语义相似度判断
        try:
            # 查询与当前输入相关的记忆
            query = self._build_recall_query(user_input, context)
            experiences = await _search_best_experience(query, limit=1)

            if experiences and len(experiences) > 0:
                best_match = experiences[0]
                similarity = best_match.get("similarity", 0.0)

                if similarity >= self.similarity_threshold:
                    return True, f"找到相似度{similarity:.2f}的相关记忆", similarity
                elif similarity >= self.similarity_threshold * 0.8:
                    # 接近阈值，记录日志但暂不触发
                    logger.debug(f"[ActiveRecall] 相似度{similarity:.2f}接近阈值，暂不触发")
        except Exception as e:
            # 【静默失败修复】核心功能失败必须是ERROR级别
            logger.error(f"[ActiveRecall] 语义相似度检查失败: {e}", exc_info=True)

        # 3. 检查当前任务类型是否有相关经验
        task_type = context.get("task_type", "")
        if task_type:
            try:
                task_experiences = await _search_best_experience(f"task_type:{task_type}", limit=1)
                if task_experiences and len(task_experiences) > 0:
                    return True, f"任务类型'{task_type}'有相关经验", 0.75
            except Exception as e:
                # 【静默失败修复】不能静默，必须记录ERROR日志
                logger.error(f"[ActiveRecall] 任务类型经验检索失败: {e}", exc_info=True)

        return False, "未达到触发条件", 0.0

    async def should_recall(self, context: dict[str, Any], ai_response: str) -> bool:
        """
        判断是否需要主动回忆（兼容旧接口）

        综合评估以下因素：
        1. AI响应的不确定性水平
        2. 上下文变化程度
        3. 冷却时间和频率限制

        Args:
            context: 当前上下文信息
            ai_response: AI的响应文本

        Returns:
            是否需要触发回忆
        """
        session_id = context.get("session_id", "default")

        # 检查冷却时间
        if not self._check_cooldown(session_id):
            logger.debug("[ActiveRecall] 冷却期内，跳过回忆")
            return False

        # 检查频率限制
        if self._is_rate_limited(session_id):
            logger.debug(f"[ActiveRecall] 会话 {session_id[:8]}... 已达到回忆频率限制")
            return False

        # 1. 检测不确定性
        uncertainty_level = self.detect_uncertainty(ai_response)
        uncertainty_score = uncertainty_level.value / 3.0  # 归一化到 0-1

        # 2. 检测上下文变化
        current_context = self._extract_context_state(context)
        context_change_score = 0.0
        if self._previous_context is not None:
            context_change_score = self.get_context_changes(current_context, self._previous_context)

        # 3. 综合评估
        should_trigger = (
            uncertainty_score >= self.uncertainty_threshold or
            context_change_score >= self.context_change_threshold
        )

        if should_trigger:
            logger.info(
                f"[ActiveRecall] 触发回忆: 不确定性={uncertainty_level.name}, "
                f"上下文变化={context_change_score:.2f}"
            )
            self._update_recall_stats(session_id)
            self._previous_context = current_context
            self._context_history.append(current_context)
            # 保持历史记录不会无限增长
            if len(self._context_history) > 10:
                self._context_history.pop(0)

        return should_trigger

    def detect_uncertainty(self, ai_response: str) -> UncertaintyLevel:
        """
        检测AI响应中的不确定性水平

        Args:
            ai_response: AI的响应文本

        Returns:
            不确定性等级
        """
        if not ai_response:
            return UncertaintyLevel.NONE

        text_lower = ai_response.lower()

        # 按优先级检测（高到低）
        for level in [UncertaintyLevel.HIGH, UncertaintyLevel.MEDIUM, UncertaintyLevel.LOW]:
            for pattern in self.UNCERTAINTY_PATTERNS[level]:
                if re.search(pattern, text_lower, re.IGNORECASE):
                    return level

        # 额外启发式：检测问号数量和犹豫标点
        question_marks = text_lower.count('?') + text_lower.count('？')
        if question_marks >= 2:
            return UncertaintyLevel.MEDIUM

        # 检测省略号
        ellipsis_count = text_lower.count('...') + text_lower.count('。。。')
        if ellipsis_count >= 2:
            return UncertaintyLevel.LOW

        return UncertaintyLevel.NONE

    async def associate_memories(self, user_input: str, context: dict[str, Any]) -> AssociationResult:
        """
        联想机制 - 检索多层级相关记忆

        Args:
            user_input: 用户输入
            context: 上下文信息

        Returns:
            联想结果（包含L2/L3/L4层级的记忆）
        """
        result = AssociationResult()

        if not self.enable_association:
            return result

        try:
            # L2: 检索工作记忆（与当前输入直接相关的短期记忆）
            result.l2_memories = await self._retrieve_l2_working_memory(user_input, context)

            # L3: 检索经验模式（与当前任务相关的长期经验）
            result.l3_experiences = await self._retrieve_l3_experiences(user_input, context)

            # L4: 检索用户画像（与用户相关的持久信息）
            result.l4_profile_hints = await self._retrieve_l4_profile(user_input, context)

            logger.info(
                f"[ActiveRecall] 联想完成: L2={len(result.l2_memories)}, "
                f"L3={len(result.l3_experiences)}, L4={len(result.l4_profile_hints)}"
            )
        except Exception as e:
            logger.error(f"[ActiveRecall] 联想机制失败: {e}")

        return result

    async def _retrieve_l2_working_memory(self, user_input: str, context: dict[str, Any]) -> list[dict[str, Any]]:
        """
        【修复】检索L2工作记忆（短期、当前会话的最近交互）

        修复前：错误地检索了L4长期经验向量库
        修复后：从当前会话WorkingMemory + PostgreSQL短期记忆层获取
        """
        results = []
        user_id = context.get("user_id", "default")
        session_id = context.get("session_id")

        try:
            # 1. 获取当前会话的WorkingMemory（真正的短期工作记忆）
            try:
                from core.agent.working_memory import get_working_memory
                wm = get_working_memory(session_id or user_id)
                if wm and hasattr(wm, 'messages'):
                    # 获取最近5条消息（排除当前输入）
                    recent_messages = wm.messages[-6:-1] if len(wm.messages) > 1 else []
                    for msg in recent_messages:
                        content = msg.get("content", "") if isinstance(msg, dict) else str(msg)
                        if content:
                            results.append({
                                "id": f"wm_{session_id}_{hash(content) & 0xFFFFFFFF}",
                                "document": content[:200],  # 限制长度
                                "metadata": {
                                    "source": "working_memory",
                                    "role": msg.get("role") if isinstance(msg, dict) else "unknown",
                                    "session_id": session_id,
                                    "timestamp": msg.get("timestamp") if isinstance(msg, dict) else time.time()
                                },
                                "similarity": 0.95,  # 当前会话记忆视为高度相关
                                "level": "l2_working"
                            })
            except Exception as e:
                # 【静默失败修复】核心功能失败必须是ERROR级别
                logger.error(f"[ActiveRecall] WorkingMemory获取失败: {e}", exc_info=True)

            # 2. 从PostgreSQL短期记忆层检索（今日对话记录）
            try:
                from core.memory.memory_service import get_memory_service
                ms = await get_memory_service()
                # 查询今日的记忆记录
                import datetime
                today_start = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                short_memories = await ms.query_memories(
                    user_id=user_id,
                    layer="short",
                    limit=3,
                    filter_dict={"since": today_start.isoformat()}
                )
                for mem in short_memories:
                    content = mem.get("content", "")
                    if isinstance(content, dict):
                        text = content.get("text", "") or content.get("content", "")
                    else:
                        text = str(content)

                    if text:
                        results.append({
                            "id": mem.get("id", f"l2_{hash(text) & 0xFFFFFFFF}"),
                            "document": text[:200],
                            "metadata": {
                                "source": "short_term_memory",
                                "layer": "short",
                                "created_at": mem.get("created_at"),
                                "session_id": mem.get("session_id")
                            },
                            "similarity": 0.85,
                            "level": "l2_working"
                        })
            except Exception as e:
                # 【静默失败修复】核心功能失败必须是ERROR级别
                logger.error(f"[ActiveRecall] 短期记忆层检索失败: {e}", exc_info=True)

            # 3. 如果以上都失败，降级到向量检索（保持向后兼容）
            if not results:
                logger.debug("[ActiveRecall] L2从工作记忆获取失败，降级到向量检索")
                memories = await _search_best_experience(user_input, limit=2)
                for m in memories:
                    m["level"] = "l2_working_fallback"
                return memories

            # 限制返回数量
            return results[:5]

        except Exception as e:
            logger.debug(f"[ActiveRecall] L2检索失败: {e}")
            return []

    async def _retrieve_l3_experiences(self, user_input: str, context: dict[str, Any]) -> list[dict[str, Any]]:
        """检索L3经验模式（长期、与任务类型相关）"""
        try:
            task_type = context.get("task_type", "")
            if not task_type:
                task_type = self._infer_task_type(user_input)

            # 构建任务相关的查询
            query_parts = [user_input]
            if task_type:
                query_parts.append(f"task:{task_type}")

            query = " | ".join(query_parts)
            memories = await _search_best_experience(query, limit=3)

            return memories
        except Exception as e:
            logger.debug(f"[ActiveRecall] L3检索失败: {e}")
            return []

    async def _retrieve_l4_profile(self, user_input: str, context: dict[str, Any]) -> list[dict[str, Any]]:
        """检索L4用户画像（与用户相关的持久信息）"""
        try:
            user_id = context.get("user_id")
            if not user_id:
                return []

            # 查询与用户相关的记忆
            query = f"user:{user_id} {user_input}"
            memories = await _search_best_experience(query, limit=2)

            return memories
        except Exception as e:
            logger.debug(f"[ActiveRecall] L4检索失败: {e}")
            return []

    async def trigger_recall(self, task_description: str, context: dict[str, Any]) -> RecallResult:
        """
        触发主动回忆

        Args:
            task_description: 任务描述
            context: 上下文信息

        Returns:
            回忆结果
        """
        try:
            # 使用联想机制检索多层级记忆
            association = await self.associate_memories(task_description, context)

            if not association.is_empty():
                experiences = association.merge()
                memory_levels = []
                if association.l2_memories:
                    memory_levels.append(MemoryLevel.L2_WORKING)
                if association.l3_experiences:
                    memory_levels.append(MemoryLevel.L3_EXPERIENCE)
                if association.l4_profile_hints:
                    memory_levels.append(MemoryLevel.L4_PROFILE)

                avg_similarity = sum(exp.get("similarity", 0) for exp in experiences) / len(experiences)

                reason = f"联想检索到 {len(experiences)} 条记忆 (L2:{len(association.l2_memories)}, L3:{len(association.l3_experiences)}, L4:{len(association.l4_profile_hints)})"

                logger.info(f"[ActiveRecall] 回忆完成: {reason}")

                return RecallResult(
                    triggered=True,
                    reason=reason,
                    experiences=experiences,
                    similarity_score=avg_similarity,
                    memory_levels=memory_levels,
                    context_change_score=self._calculate_context_relevance(context, experiences)
                )

            # 回退：使用向量记忆检索
            query = self._build_recall_query(task_description, context)
            experiences = await _search_best_experience(query, limit=3)

            # 如果没有找到经验，尝试知识检索
            if not experiences:
                knowledge = await _search_knowledge(query, limit=2)
                if knowledge:
                    experiences = [{
                        "id": k.get("id", ""),
                        "document": k.get("document", ""),
                        "metadata": k.get("metadata", {}),
                        "similarity": k.get("similarity", 0.5),
                        "source": "knowledge",
                        "level": MemoryLevel.L3_EXPERIENCE.value
                    } for k in knowledge]

            triggered = len(experiences) > 0
            reason = f"找到 {len(experiences)} 条相关记忆" if triggered else "未找到相关记忆"

            logger.info(f"[ActiveRecall] 回忆完成: {reason}")

            return RecallResult(
                triggered=triggered,
                reason=reason,
                experiences=experiences,
                context_change_score=self._calculate_context_relevance(context, experiences)
            )

        except Exception as e:
            logger.error(f"[ActiveRecall] 回忆触发失败: {e}")
            return RecallResult(
                triggered=False,
                reason=f"检索失败: {str(e)}"
            )

    def get_context_changes(self, current_context: ContextState, previous_context: ContextState) -> float:
        """检测上下文变化程度"""
        if not previous_context:
            return 1.0

        scores = []

        # 1. 任务类型变化
        if current_context.task_type != previous_context.task_type and current_context.task_type and previous_context.task_type:
            scores.append(self.CONTEXT_WEIGHTS["task_type_change"])

        # 2. 关键词重叠度
        if current_context.keywords and previous_context.keywords:
            current_set = set(current_context.keywords)
            previous_set = set(previous_context.keywords)

            if current_set and previous_set:
                overlap = len(current_set & previous_set)
                total = len(current_set | previous_set)
                similarity = overlap / total if total > 0 else 0
                keyword_change = (1 - similarity) * self.CONTEXT_WEIGHTS["keyword_overlap"]
                scores.append(keyword_change)

        # 3. 实体变化
        if current_context.entities and previous_context.entities:
            current_entities = set(current_context.entities)
            previous_entities = set(previous_context.entities)

            if current_entities and previous_entities:
                entity_overlap = len(current_entities & previous_entities)
                entity_total = len(current_entities | previous_entities)
                entity_similarity = entity_overlap / entity_total if entity_total > 0 else 0
                entity_change = (1 - entity_similarity) * self.CONTEXT_WEIGHTS["entity_change"]
                scores.append(entity_change)

        # 时间因素：长时间间隔增加变化分数
        time_diff = current_context.timestamp - previous_context.timestamp
        if time_diff > 300:  # 5分钟以上
            scores.append(min(0.2, time_diff / 3600))

        # 综合分数
        total_score = sum(scores) if scores else 0.0
        return min(1.0, total_score)

    async def inject_if_needed(self, task: str, context: dict[str, Any],
                         ai_response: str, base_prompt: str) -> tuple[str, RecallResult]:
        """
        智能注入 - 如果需要则触发回忆并注入经验

        Args:
            task: 任务描述
            context: 上下文信息
            ai_response: AI响应（用于不确定性检测）
            base_prompt: 基础提示词

        Returns:
            (注入后的提示词, 回忆结果)
        """
        # 首先判断是否需要回忆（新旧两种机制）
        should_trigger_old = await self.should_recall(context, ai_response)
        should_trigger_new, reason_new, similarity = await self.should_recall_memory(task, context)

        should_trigger = should_trigger_old or should_trigger_new

        if not should_trigger:
            return base_prompt, RecallResult(
                triggered=False,
                reason="未达到触发条件",
                uncertainty_level=self.detect_uncertainty(ai_response)
            )

        # 触发回忆
        recall_result = await self.trigger_recall(task, context)

        if not recall_result.triggered or not recall_result.experiences:
            # 没有找到记忆，使用常规经验注入
            enhanced_prompt = await experience_injector.inject_experience(task, base_prompt)
            return enhanced_prompt, recall_result

        # 将回忆结果格式化为提示词增强
        memory_section = self._format_recall_to_prompt(recall_result.experiences)
        enhanced_prompt = base_prompt + "\n\n" + memory_section

        logger.info(
            f"[ActiveRecall] 已注入 {len(recall_result.experiences)} 条记忆到提示词"
        )

        return enhanced_prompt, recall_result

    def _extract_context_state(self, context: dict[str, Any]) -> ContextState:
        """从上下文中提取状态"""
        task = context.get("task", "")
        task_type = context.get("task_type", self._infer_task_type(task))

        # 提取关键词
        keywords = self._extract_keywords(task)

        # 提取实体
        entities = context.get("entities", [])

        # 获取用户ID
        user_id = context.get("user_id")

        return ContextState(
            task_type=task_type,
            keywords=keywords,
            entities=entities,
            user_id=user_id,
            timestamp=time.time()
        )

    def _infer_task_type(self, task: str) -> str:
        """推断任务类型"""
        if not task:
            return "general"

        task_lower = task.lower()

        type_keywords = {
            "code": ["代码", "编程", "program", "code", "function", "class"],
            "file": ["文件", "目录", "folder", "file", "path", "目录"],
            "web": ["网页", "网站", "web", "http", "url", "api"],
            "data": ["数据", "分析", "data", "csv", "json", "database"],
            "search": ["搜索", "查询", "search", "find", "look for"],
            "system": ["系统", "配置", "system", "config", "setting"],
            "conversation": ["聊天", "对话", "chat", "talk", "conversation"]
        }

        for task_type, keywords in type_keywords.items():
            if any(kw in task_lower for kw in keywords):
                return task_type

        return "general"

    def _extract_keywords(self, text: str, max_keywords: int = 5) -> list[str]:
        """提取关键词"""
        if not text:
            return []

        stopwords = {"the", "a", "an", "is", "are", "was", "were", "be", "been",
                     "的", "了", "在", "是", "有", "和", "与", "或", "一个"}

        words = re.findall(r'\b[a-zA-Z]{3,}\b|[\u4e00-\u9fa5]{2,}', text.lower())
        keywords = [w for w in words if w not in stopwords]

        keywords.sort(key=len, reverse=True)
        return keywords[:max_keywords]

    def _build_recall_query(self, task_description: str, context: dict[str, Any]) -> str:
        """构建回忆查询"""
        query_parts = [task_description]

        if "user_intent" in context:
            query_parts.append(f"意图: {context['user_intent']}")

        if "keywords" in context:
            query_parts.append(" ".join(context["keywords"]))

        return " | ".join(query_parts)

    def _format_recall_to_prompt(self, experiences: list[dict[str, Any]]) -> str:
        """将回忆结果格式化为提示词"""
        lines = ["【主动回忆 - 相关历史经验】"]
        lines.append("系统检测到当前任务可能需要以下历史经验参考：\n")

        for i, exp in enumerate(experiences, 1):
            doc = exp.get("document", "")
            similarity = exp.get("similarity", 0)
            level = exp.get("level", "experience")

            parsed = self._parse_experience_doc(doc)

            level_label = {"l2_working": "[工作记忆]", "l3_experience": "[经验模式]",
                          "l4_profile": "[用户画像]", "experience": "[经验]"}.get(level, "[经验]")

            lines.append(f"[{i}] {level_label} 相关度: {similarity:.2f}")
            lines.append(f"    任务: {parsed.get('pattern', '未知')}")
            lines.append(f"    步骤: {parsed.get('steps', '无')}")
            lines.append(f"    结果: {parsed.get('result', '未知')}")
            lines.append("")

        lines.append("【建议】")
        lines.append("• 参考以上历史经验处理当前任务")
        lines.append("• 若经验不适用，请按常规方式处理")

        return "\n".join(lines)

    def _parse_experience_doc(self, doc: str) -> dict[str, str]:
        """解析经验文档"""
        result = {"pattern": "", "steps": "", "result": ""}

        try:
            parts = doc.split("|")
            for part in parts:
                part = part.strip()
                if part.startswith("[Task]"):
                    result["pattern"] = part[6:].strip()
                elif part.startswith("[Steps]"):
                    result["steps"] = part[7:].strip()
                elif part.startswith("[Result]"):
                    result["result"] = part[8:].strip()
        except Exception:
            result["pattern"] = doc[:50] if doc else ""

        return result

    def _is_explicit_recall_request(self, user_input: str) -> bool:
        """检查用户是否明确请求回忆历史经验"""
        text_lower = user_input.lower()
        return any(re.search(pattern, text_lower) for pattern in self.RECALL_TRIGGER_PATTERNS)

    def _check_cooldown(self, session_id: str) -> bool:
        """检查是否在冷却期内"""
        last_time = self._last_recall_time.get(session_id, 0)
        return (time.time() - last_time) >= self.cooldown_seconds

    def _is_rate_limited(self, session_id: str) -> bool:
        """检查是否达到频率限制"""
        count = self._session_recall_count.get(session_id, 0)
        return count >= self.max_recall_per_session

    def _update_recall_stats(self, session_id: str):
        """更新回忆统计"""
        self._session_recall_count[session_id] = \
            self._session_recall_count.get(session_id, 0) + 1
        self._last_recall_time[session_id] = time.time()

    def _calculate_context_relevance(self, context: dict[str, Any],
                                     experiences: list[dict[str, Any]]) -> float:
        """计算上下文与回忆结果的相关性"""
        if not experiences:
            return 0.0

        total_similarity = sum(exp.get("similarity", 0) for exp in experiences)
        return total_similarity / len(experiences)

    def get_recall_stats(self, session_id: str | None = None) -> dict[str, Any]:
        """获取回忆统计信息"""
        if session_id:
            return {
                "session_id": session_id[:8] + "...",
                "recall_count": self._session_recall_count.get(session_id, 0),
                "last_recall": self._last_recall_time.get(session_id, 0),
                "rate_limited": self._is_rate_limited(session_id)
            }

        return {
            "total_sessions": len(self._session_recall_count),
            "total_recalls": sum(self._session_recall_count.values()),
            "context_history_size": len(self._context_history),
            "thresholds": {
                "uncertainty": self.uncertainty_threshold,
                "context_change": self.context_change_threshold,
                "similarity": self.similarity_threshold
            },
            "config": {
                "cooldown_seconds": self.cooldown_seconds,
                "max_recall_per_session": self.max_recall_per_session,
                "enable_proactive": self.enable_proactive,
                "enable_association": self.enable_association
            }
        }

    def reset_session(self, session_id: str):
        """重置会话状态"""
        self._session_recall_count.pop(session_id, None)
        self._last_recall_time.pop(session_id, None)
        logger.debug(f"[ActiveRecall] 重置会话 {session_id[:8]}...")

    def update_config(self, **kwargs):
        """动态更新配置"""
        if "cooldown_seconds" in kwargs:
            self.cooldown_seconds = kwargs["cooldown_seconds"]
        if "similarity_threshold" in kwargs:
            self.similarity_threshold = kwargs["similarity_threshold"]
        if "max_recall_per_session" in kwargs:
            self.max_recall_per_session = kwargs["max_recall_per_session"]
        if "enable_proactive" in kwargs:
            self.enable_proactive = kwargs["enable_proactive"]
        if "enable_association" in kwargs:
            self.enable_association = kwargs["enable_association"]

        logger.info(f"[ActiveRecall] 配置已更新: {kwargs}")


# 全局实例
active_recall = ActiveRecall()


async def check_and_recall(task: str, context: dict[str, Any],
                     ai_response: str) -> RecallResult:
    """便捷函数：检查并触发回忆"""
    if await active_recall.should_recall(context, ai_response):
        return await active_recall.trigger_recall(task, context)

    return RecallResult(
        triggered=False,
        reason="未达到触发阈值",
        uncertainty_level=active_recall.detect_uncertainty(ai_response)
    )


async def inject_with_recall(task: str, context: dict[str, Any],
                       ai_response: str, base_prompt: str) -> str:
    """便捷函数：智能注入（仅返回增强后的提示词）"""
    enhanced_prompt, _ = await active_recall.inject_if_needed(
        task, context, ai_response, base_prompt
    )
    return enhanced_prompt


async def should_recall_memory(user_input: str, context: dict[str, Any]) -> tuple[bool, str, float]:
    """
    便捷函数：判断是否应该触发记忆回忆（基于语义相似度）

    这是新的主动触发入口，每次用户输入时调用

    Args:
        user_input: 用户输入文本
        context: 当前上下文信息

    Returns:
        (是否应该触发, 原因, 相似度分数)
    """
    return await active_recall.should_recall_memory(user_input, context)


async def associate_memories(user_input: str, context: dict[str, Any]) -> AssociationResult:
    """
    便捷函数：触发联想机制检索多层级记忆

    Args:
        user_input: 用户输入
        context: 上下文信息

    Returns:
        联想结果（L2/L3/L4层级的记忆）
    """
    return await active_recall.associate_memories(user_input, context)


# 类别名，用于兼容
RecallMemory = ActiveRecall

# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase V5 系统的"主动回忆机制"，通过语义相似度和联想机制，
# 实现每次用户输入时的主动记忆检索，提升AI任务处理的准确性和连贯性。
#
# 【核心思想】
# 1. 主动触发: 每次用户输入时主动检索相关记忆
# 2. 语义相似度: 基于用户输入与记忆的相似度触发
# 3. 联想机制: 自动关联L2工作记忆、L3经验模式、L4用户画像
# 4. 可配置冷却: 冷却时间可配置，默认0.5秒
#
# 【核心类说明】
# - UncertaintyLevel: 不确定性等级枚举（NONE/LOW/MEDIUM/HIGH）
# - MemoryLevel: 记忆层级枚举（L2_WORKING/L3_EXPERIENCE/L4_PROFILE）
# - ContextState: 上下文状态数据类
# - RecallResult: 回忆结果数据类
# - AssociationResult: 联想结果数据类
# - ActiveRecall: 主动回忆管理器主类
#
# 【新增功能】
# 1. should_recall_memory(): 基于语义相似度判断触发
# 2. associate_memories(): 多层级联想检索
# 3. _retrieve_l2_working_memory(): L2工作记忆检索
# 4. _retrieve_l3_experiences(): L3经验模式检索
# 5. _retrieve_l4_profile(): L4用户画像检索
# 6. _is_explicit_recall_request(): 检测用户明确回忆请求
# 7. update_config(): 动态更新配置
#
# 【触发条件】
# - 用户输入与记忆库相似度 > 阈值 (默认0.6)
# - 用户明确询问"之前怎么做"
# - 当前任务类型有相关经验记忆
# - AI表达不确定性（保留原有功能）
# - 上下文发生显著变化
#
# 【使用场景】
# - 每次用户输入时主动检索相关记忆
# - 多层级联想（工作记忆、经验模式、用户画像）
# - 动态配置冷却时间和触发阈值
# =============================================================================
