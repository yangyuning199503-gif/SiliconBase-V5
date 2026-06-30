#!/usr/bin/env python3
"""
目标对齐引擎 (GoalAlignmentEngine)

负责理解用户意图并主动确认，确保AI和用户对任务目标达成一致。

核心功能：
1. LLM理解意图（意图、目标、参数、置信度）
2. 置信度评估（基于模糊程度、历史匹配等）
3. 三种决策结果：
   - aligned: 直接执行
   - need_clarification: 返回澄清问题
   - need_confirmation: 返回确认信息

置信度规则：
- confidence >= 0.9: 需要确认（"你的意思是...吗？"）
- confidence >= 0.7: 直接执行
- confidence < 0.7: 需要澄清（"你想做什么？"）

版本历史：
- 2026-03-12: 创建基础实现
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.logger import logger


class AlignmentStatus(Enum):
    """对齐状态枚举"""
    ALIGNED = "aligned"                # 已对齐，直接执行
    NEED_CLARIFICATION = "need_clarification"  # 需要澄清
    NEED_CONFIRMATION = "need_confirmation"    # 需要确认


@dataclass
class Understanding:
    """
    用户意图理解结果

    Attributes:
        intent: 意图类型（如 'open_app', 'search', 'execute_task' 等）
        target: 目标对象（如应用名、搜索关键词等）
        params: 意图相关参数
        confidence: 置信度 (0.0-1.0)
        description: 意图的自然语言描述
        ambiguity_factors: 模糊性因素列表
    """
    intent: str
    target: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    description: str = ""
    ambiguity_factors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "intent": self.intent,
            "target": self.target,
            "params": self.params,
            "confidence": self.confidence,
            "description": self.description,
            "ambiguity_factors": self.ambiguity_factors
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Understanding":
        """从字典创建"""
        return cls(
            intent=data.get("intent", "unknown"),
            target=data.get("target"),
            params=data.get("params", {}),
            confidence=data.get("confidence", 0.0),
            description=data.get("description", ""),
            ambiguity_factors=data.get("ambiguity_factors", [])
        )


@dataclass
class AlignmentResult:
    """
    目标对齐结果

    Attributes:
        status: 对齐状态
        understanding: 意图理解结果
        question: 澄清/确认问题（当需要时）
        options: 选项列表（当需要时）
        suggested_action: 建议执行的动作
        reasoning: 决策理由
    """
    status: AlignmentStatus
    understanding: Understanding
    question: str | None = None
    options: list[str] | None = None
    suggested_action: dict[str, Any] | None = None
    reasoning: str = ""

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "status": self.status.value,
            "understanding": self.understanding.to_dict(),
            "question": self.question,
            "options": self.options,
            "suggested_action": self.suggested_action,
            "reasoning": self.reasoning
        }

    def is_aligned(self) -> bool:
        """是否已对齐（可以直接执行）"""
        return self.status == AlignmentStatus.ALIGNED

    def needs_clarification(self) -> bool:
        """是否需要澄清"""
        return self.status == AlignmentStatus.NEED_CLARIFICATION

    def needs_confirmation(self) -> bool:
        """是否需要确认"""
        return self.status == AlignmentStatus.NEED_CONFIRMATION


class GoalAlignmentEngine:
    """
    目标对齐引擎

    核心流程：
    1. 接收用户输入
    2. LLM理解意图 → Understanding
    3. 置信度评估
    4. 生成对齐结果
    """

    # 置信度阈值配置
    CONFIDENCE_HIGH = 0.9   # 高置信度，但需要确认（防止误操作）
    CONFIDENCE_NORMAL = 0.7  # 正常置信度，直接执行

    def __init__(
        self,
        llm_client: Any | None = None,
        llm_call_func: Callable | None = None,
        timeout_ms: int = 500
    ):
        """
        初始化目标对齐引擎

        Args:
            llm_client: LLM客户端实例（可选）
            llm_call_func: LLM调用函数（可选，优先级高于llm_client）
            timeout_ms: LLM调用超时时间（毫秒）
        """
        self._llm_client = llm_client
        self._llm_call_func = llm_call_func
        self._timeout_ms = timeout_ms

        # 历史意图匹配记录（用于提升置信度）
        self._user_history: dict[str, list[dict]] = {}

        logger.info("[GoalAlignmentEngine] 目标对齐引擎初始化完成")

    def process_input(
        self,
        user_id: str,
        text: str,
        context: dict | None = None
    ) -> AlignmentResult:
        """
        处理用户输入，返回对齐结果

        Args:
            user_id: 用户ID
            text: 用户输入文本
            context: 上下文信息（如历史对话、当前状态等）

        Returns:
            AlignmentResult: 对齐结果
        """
        context = context or {}

        try:
            # 1. LLM理解意图
            understanding = self._llm_understand(text, context)

            # 2. 置信度评估（结合历史匹配）
            adjusted_confidence = self._evaluate_confidence(
                user_id, understanding, context
            )
            understanding.confidence = adjusted_confidence

            # 3. 根据置信度生成结果
            result = self._generate_result(understanding, text)

            logger.info(
                f"[GoalAlignmentEngine] 用户={user_id}, "
                f"意图={understanding.intent}, "
                f"置信度={understanding.confidence:.2f}, "
                f"结果={result.status.value}"
            )

            return result

        except Exception as e:
            # 异常处理：返回保守的澄清结果
            logger.error(f"[GoalAlignmentEngine] 处理失败: {e}")
            return self._fallback_result(text, str(e))

    def _llm_understand(self, text: str, context: dict) -> Understanding:
        """
        使用LLM理解用户意图

        Args:
            text: 用户输入文本
            context: 上下文信息

        Returns:
            Understanding: 意图理解结果
        """
        # 构建提示词
        prompt = self._build_understanding_prompt(text, context)

        # 调用LLM
        start_time = time.time()
        try:
            response = self._call_llm(prompt)
            elapsed_ms = (time.time() - start_time) * 1000

            if elapsed_ms > self._timeout_ms:
                logger.warning(
                    f"[GoalAlignmentEngine] LLM调用超时: {elapsed_ms:.0f}ms"
                )

            # 解析响应
            understanding = self._parse_llm_response(response)
            return understanding

        except Exception as e:
            logger.error(f"[GoalAlignmentEngine] LLM理解失败: {e}")
            # 返回模糊的意图
            return Understanding(
                intent="ambiguous",
                description=text,
                confidence=0.3,
                ambiguity_factors=["llm_error"]
            )

    def _build_understanding_prompt(self, text: str, context: dict) -> str:
        """
        构建意图理解提示词

        Args:
            text: 用户输入文本
            context: 上下文信息

        Returns:
            str: 提示词
        """
        # 获取历史对话（如果有）
        history = context.get("history", [])
        history_str = ""
        if history:
            history_str = "\n历史对话:\n" + "\n".join([
                f"用户: {h.get('user', '')}\nAI: {h.get('ai', '')}"
                for h in history[-3:]  # 最近3轮
            ])

        prompt = f"""你是一个意图理解助手。请分析用户的输入，提取意图、目标和参数。

用户输入: "{text}"{history_str}

请以下面的JSON格式返回分析结果：
{{
    "intent": "意图类型，可选值: open_app, search, execute_task, ask_question, chat, ambiguous, unknown",
    "target": "目标对象，如应用名、搜索关键词等（可为空）",
    "params": {{}},
    "confidence": 0.0-1.0,
    "description": "意图的自然语言描述",
    "ambiguity_factors": ["模糊因素1", "模糊因素2"]
}}

注意：
1. confidence表示你对理解用户意图的置信度
2. 如果输入模糊，intent设为"ambiguous"，ambiguity_factors列出模糊点
3. 只返回JSON，不要其他内容"""

        return prompt

    def _call_llm(self, prompt: str) -> str:
        """
        调用LLM获取响应

        Args:
            prompt: 提示词

        Returns:
            str: LLM响应
        """
        # 优先使用自定义调用函数
        if self._llm_call_func:
            return self._llm_call_func(prompt)

        # 使用AIClient
        if self._llm_client:
            messages = [{"role": "user", "content": prompt}]
            return self._llm_client.chat(messages, max_tokens=512, temperature=0.1)

        # 尝试获取默认客户端
        try:
            from ai_client import get_default_client
            client = get_default_client()
            messages = [{"role": "user", "content": prompt}]
            return client.chat(messages, max_tokens=512, temperature=0.1)
        except Exception as e:
            logger.error(f"[GoalAlignmentEngine] 获取LLM客户端失败: {e}")
            raise

    def _parse_llm_response(self, response: str) -> Understanding:
        """
        解析LLM响应为Understanding对象

        Args:
            response: LLM响应文本

        Returns:
            Understanding: 解析后的理解结果
        """
        if not response:
            return Understanding(
                intent="unknown",
                confidence=0.0,
                description="空响应",
                ambiguity_factors=["empty_response"]
            )

        # 尝试提取JSON
        json_str = response

        # 处理markdown代码块
        if "```json" in response:
            json_str = response.split("```json")[1].split("```")[0].strip()
        elif "```" in response:
            json_str = response.split("```")[1].split("```")[0].strip()

        try:
            data = json.loads(json_str)
            return Understanding.from_dict(data)
        except json.JSONDecodeError as e:
            logger.warning(f"[GoalAlignmentEngine] JSON解析失败: {e}, 响应: {response[:200]}")
            # 回退：从文本中提取信息
            return self._fallback_parse(response)

    def _fallback_parse(self, text: str) -> Understanding:
        """
        回退解析方法（当JSON解析失败时使用）

        Args:
            text: LLM响应文本

        Returns:
            Understanding: 解析结果
        """
        # 简单的关键词匹配
        intent = "unknown"
        if "open" in text.lower() or "打开" in text:
            intent = "open_app"
        elif "search" in text.lower() or "搜索" in text:
            intent = "search"
        elif "ambiguous" in text.lower() or "模糊" in text:
            intent = "ambiguous"

        return Understanding(
            intent=intent,
            description=text[:200],
            confidence=0.5,
            ambiguity_factors=["parse_error"]
        )

    def _evaluate_confidence(
        self,
        user_id: str,
        understanding: Understanding,
        context: dict
    ) -> float:
        """
        评估并调整置信度

        基于：
        1. LLM返回的基础置信度
        2. 模糊因素
        3. 历史匹配

        Args:
            user_id: 用户ID
            understanding: 意图理解结果
            context: 上下文信息

        Returns:
            float: 调整后的置信度
        """
        base_confidence = understanding.confidence

        # 1. 模糊因素扣分
        ambiguity_penalty = len(understanding.ambiguity_factors) * 0.1
        adjusted = base_confidence - ambiguity_penalty

        # 2. 检查必要字段
        if understanding.intent in ["open_app", "search", "execute_task"] and not understanding.target:
            adjusted -= 0.2  # 缺少目标扣分

        # 3. 历史匹配加分
        if user_id in self._user_history:
            history = self._user_history[user_id]
            for record in history[-5:]:  # 最近5条
                if record.get("intent") == understanding.intent:
                    adjusted += 0.05  # 匹配历史意图加分

        # 4. 边界限制
        adjusted = max(0.0, min(1.0, adjusted))

        return adjusted

    def _generate_result(
        self,
        understanding: Understanding,
        original_text: str
    ) -> AlignmentResult:
        """
        根据理解结果生成对齐结果

        Args:
            understanding: 意图理解结果
            original_text: 原始用户输入

        Returns:
            AlignmentResult: 对齐结果
        """
        confidence = understanding.confidence

        # 规则1: 高置信度（>=0.9）需要确认（防止误操作）
        if confidence >= self.CONFIDENCE_HIGH:
            question, options = self._generate_confirmation(understanding)
            return AlignmentResult(
                status=AlignmentStatus.NEED_CONFIRMATION,
                understanding=understanding,
                question=question,
                options=options,
                suggested_action=self._build_action(understanding),
                reasoning=f"高置信度({confidence:.2f})，但涉及具体操作，需要用户确认"
            )

        # 规则2: 正常置信度（>=0.7）直接执行
        if confidence >= self.CONFIDENCE_NORMAL:
            return AlignmentResult(
                status=AlignmentStatus.ALIGNED,
                understanding=understanding,
                suggested_action=self._build_action(understanding),
                reasoning=f"置信度足够({confidence:.2f})，可以直接执行"
            )

        # 规则3: 低置信度（<0.7）需要澄清
        question, options = self._generate_clarification(understanding, original_text)
        return AlignmentResult(
            status=AlignmentStatus.NEED_CLARIFICATION,
            understanding=understanding,
            question=question,
            options=options,
            reasoning=f"置信度不足({confidence:.2f})，需要用户澄清"
        )

    def _generate_confirmation(
        self,
        understanding: Understanding
    ) -> tuple[str, list[str]]:
        """
        生成确认问题

        Args:
            understanding: 意图理解结果

        Returns:
            tuple: (问题, 选项列表)
        """
        intent_name = self._get_intent_name(understanding.intent)
        target = understanding.target or ""

        question = f"你的意思是{intent_name}『{target}』吗？" if target else f"你的意思是{intent_name}吗？"

        options = ["是的", "不是"]

        return question, options

    def _generate_clarification(
        self,
        understanding: Understanding,
        original_text: str
    ) -> tuple[str, list[str]]:
        """
        生成澄清问题

        Args:
            understanding: 意图理解结果
            original_text: 原始用户输入

        Returns:
            tuple: (问题, 选项列表)
        """
        intent = understanding.intent
        intent_name = self._get_intent_name(intent)

        # 完全模糊的情况
        if intent == "ambiguous" or intent == "unknown":
            question = "你想让我帮你做什么？"
            options = ["打开应用", "搜索信息", "执行任务", "随便聊聊"]
        # 缺少目标
        elif not understanding.target:
            question = f"你想{intent_name}什么？"
            options = []
        # 有具体意图但不确定
        else:
            question = f"你的意思是{understanding.description}吗？"
            options = ["是的", "不是", "重新描述"]

        return question, options

    def _get_intent_name(self, intent: str) -> str:
        """
        获取意图的中文名称

        Args:
            intent: 意图类型

        Returns:
            str: 中文名称
        """
        intent_names = {
            "open_app": "打开",
            "search": "搜索",
            "execute_task": "执行",
            "ask_question": "询问",
            "chat": "聊天",
            "ambiguous": "做某事",
            "unknown": "做某事"
        }
        return intent_names.get(intent, intent)

    def _build_action(self, understanding: Understanding) -> dict[str, Any] | None:
        """
        构建建议执行的动作

        Args:
            understanding: 意图理解结果

        Returns:
            Optional[Dict]: 动作描述
        """
        if understanding.intent in ["ambiguous", "unknown", "chat"]:
            return None

        return {
            "type": understanding.intent,
            "target": understanding.target,
            "params": understanding.params
        }

    def _fallback_result(self, text: str, error: str) -> AlignmentResult:
        """
        生成回退结果（当处理失败时使用）

        Args:
            text: 用户输入
            error: 错误信息

        Returns:
            AlignmentResult: 保守的澄清结果
        """
        understanding = Understanding(
            intent="unknown",
            description=text,
            confidence=0.0,
            ambiguity_factors=["system_error", error]
        )

        return AlignmentResult(
            status=AlignmentStatus.NEED_CLARIFICATION,
            understanding=understanding,
            question="你想让我帮你做什么？",
            options=["打开应用", "搜索信息", "执行任务", "随便聊聊"],
            reasoning=f"处理异常，返回保守结果: {error}"
        )

    def record_history(self, user_id: str, understanding: Understanding, accepted: bool):
        """
        记录用户意图历史（用于后续提升置信度）

        Args:
            user_id: 用户ID
            understanding: 意图理解结果
            accepted: 用户是否接受
        """
        if user_id not in self._user_history:
            self._user_history[user_id] = []

        self._user_history[user_id].append({
            "intent": understanding.intent,
            "target": understanding.target,
            "accepted": accepted,
            "timestamp": time.time()
        })

        # 限制历史记录数量
        if len(self._user_history[user_id]) > 50:
            self._user_history[user_id] = self._user_history[user_id][-50:]

    def clear_history(self, user_id: str | None = None):
        """
        清除用户历史记录

        Args:
            user_id: 用户ID，None表示清除所有
        """
        if user_id is None:
            self._user_history.clear()
            logger.info("[GoalAlignmentEngine] 清除所有用户历史")
        elif user_id in self._user_history:
            del self._user_history[user_id]
            logger.info(f"[GoalAlignmentEngine] 清除用户历史: {user_id}")


# 全局实例
goal_alignment_engine = GoalAlignmentEngine()


def get_goal_alignment_engine() -> GoalAlignmentEngine:
    """
    获取目标对齐引擎全局实例

    Returns:
        GoalAlignmentEngine: 目标对齐引擎实例
    """
    return goal_alignment_engine


# 为DialogueManager兼容性添加的方法
GoalAlignmentEngine.set_history_provider = lambda self, provider: None
GoalAlignmentEngine.complete_alignment = lambda self, user_id: None


__all__ = [
    "GoalAlignmentEngine",
    "goal_alignment_engine",
    "get_goal_alignment_engine",
    "AlignmentResult",
    "AlignmentStatus",
    "Understanding"
]


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase V5 系统的"目标对齐引擎"，负责理解用户意图并主动确认。
#
# 【核心功能】
# 1. 意图理解：使用LLM提取意图、目标、参数
# 2. 置信度评估：基于模糊程度、历史匹配等调整置信度
# 3. 对齐决策：
#    - confidence >= 0.9: 需要确认（防止误操作）
#    - confidence >= 0.7: 直接执行
#    - confidence < 0.7: 需要澄清
# 4. 澄清/确认问题生成：根据情况生成合适的问题
#
# 【置信度规则】
# - 高置信度(>=0.9): "你的意思是...吗？"
# - 正常置信度(>=0.7): 直接执行
# - 低置信度(<0.7): "你想做什么？"
#
# 【异常处理】
# - LLM调用失败返回保守的澄清结果
# - 不阻塞对话流程
# - 所有异常都记录ERROR日志
#
# 【关联文件】
# - ai_client.py: LLM调用
# - core/logger.py: 日志记录
# =============================================================================
