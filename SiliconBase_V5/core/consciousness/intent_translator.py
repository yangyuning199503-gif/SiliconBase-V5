"""
混合意图解析器 (IntentTranslator)

L2 翻译层：把自然语言压成结构化 Intent。
- FastPath：本地规则引擎（否定词库、高频直达表、引用语境检测、现有关键词分类器）。
- SlowPath：LLM 严格 JSON 输出，输入只给：用户句 + SelfState 快照（3行） + 最近3条叙事摘要。

原则：只做翻译，不做判断。输出必须带置信度和风险标记。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from core.ai.ai_adapter import call_thinker_async
from core.ai.ai_config import AIScene
from core.consciousness.sovereignty_types import Intent

try:
    from core.constants import classify_user_input
except Exception:
    classify_user_input = None

try:
    from core.logger import logger
except Exception:
    logger = logging.getLogger(__name__)


# 否定词库：出现在任务关键词附近时，触发风险标记
NEGATION_WORDS = [
    "别", "不要", "千万别", "禁止", "不能", "不许", "别打开", "别执行",
    "别启动", "别播放", "别调用", "no", "don't", "never", "stop"
]

# 引用/举例/讨论语境标记
EXAMPLE_MARKERS = [
    "比如", "例如", "假设", "举例来说", "打个比方", "想象一下",
    " quote", "引用", "代码如下", "```", "'", '"'
]

# 高频直达表：常见低复杂度查询，直接出 Intent
_DIRECT_INTENT_PATTERNS = [
    (r"^(现在|当前|目前).*?(几点|时间)", "chat", "low", "neutral", 0.98, {"topic": "time"}),
    (r"^(你好|您好|嗨|hello|hi)\s*[!！]?$", "chat", "low", "neutral", 0.98, {"topic": "greeting"}),
    (r"^(再见|拜拜|bye|goodbye)\s*[!！]?$", "chat", "low", "neutral", 0.98, {"topic": "farewell"}),
    (r"(你是谁|你能做什么|你会什么|你有什么功能|介绍一下自己|你的能力)", "chat", "low", "neutral", 0.95, {"topic": "self_intro"}),
]


@dataclass
class TranslatorConfig:
    """解析器配置。"""
    slow_path_model: str = "qwen3:8b"
    slow_path_timeout: int = 10
    confidence_threshold: float = 0.7
    max_input_length_for_chat: int = 80


class IntentTranslator:
    """混合意图解析器。"""

    def __init__(self, user_id: str, config: TranslatorConfig | None = None):
        self.user_id = user_id
        self.config = config or TranslatorConfig()
        # 本地意图缓存：用户历史成功解析的 Intent，支持精确/子串匹配
        self._intent_cache: list[dict[str, Any]] = []
        self._cache_max_size = 200

    async def translate(
        self,
        text: str,
        self_state_summary: str = "",
        narrative_summary: str = "",
        has_active_task: bool = False,
    ) -> Intent:
        """
        主入口：先 FastPath，再 SlowPath，最后兜底。
        """
        text_stripped = text.strip()
        if not text_stripped:
            return Intent(
                intent_type="chat", complexity="low", confidence=1.0,
                raw_input=text, meta={"reason": "empty_input"},
            )

        # 1. FastPath：规则引擎
        fast = self._fast_path(text_stripped, has_active_task)
        if fast is not None:
            fast.raw_input = text
            logger.debug(f"[IntentTranslator] FastPath 命中: {fast.to_dict()}")
            return fast

        # 2. FastPath：本地意图缓存匹配（精确/子串）
        cached = self._match_cached_intent(text_stripped)
        if cached is not None:
            cached.raw_input = text
            cached.confidence = min(0.95, cached.confidence + 0.1)
            logger.debug(f"[IntentTranslator] 缓存命中: {cached.to_dict()}")
            return cached

        # 3. SlowPath：LLM 压缩为 JSON
        slow = await self._slow_path(text_stripped, self_state_summary, narrative_summary)
        slow.raw_input = text
        logger.debug(f"[IntentTranslator] SlowPath 结果: {slow.to_dict()}")

        # 记录到缓存
        self._cache_intent(text_stripped, slow)
        return slow

    def _fast_path(self, text: str, has_active_task: bool) -> Intent | None:
        """本地规则引擎。"""
        # 1. 高频直达表
        for pattern, itype, comp, sent, conf, meta in _DIRECT_INTENT_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                intent = Intent(
                    intent_type=itype, complexity=comp, sentiment=sent,
                    confidence=conf, meta=dict(meta),
                )
                if self._has_negation_near_task(text):
                    intent.risk_flags.append("negation_detected")
                    intent.confidence = 0.6
                return intent

        # 2. 引用/举例/代码块语境
        is_example_context = self._is_example_context(text)

        # 3. 复用现有关键词分类器
        if classify_user_input is not None:
            classification = classify_user_input(text, has_active_task=has_active_task)
            category = classification.get("category", "task")
            confidence = classification.get("confidence", 5) / 10.0
            force_vision = classification.get("force_vision", False)
            control_type = classification.get("control_type")

            intent = self._classification_to_intent(category, control_type, force_vision)
            intent.confidence = confidence
            intent.meta["classification"] = classification

            if len(text) <= self.config.max_input_length_for_chat and category not in (
                "task", "direct_task", "start_monitor", "potential_monitor", "task_control", "force_vision"
            ):
                intent.intent_type = "chat"
                intent.complexity = "low"

            if self._has_negation_near_task(text):
                intent.risk_flags.append("negation_detected")
                intent.confidence *= 0.8
            if is_example_context:
                intent.risk_flags.append("example_context")
                intent.confidence *= 0.9
                intent.intent_type = "chat"
                intent.complexity = "low"

            if intent.confidence >= self.config.confidence_threshold:
                return intent

        return None

    def _match_cached_intent(self, text: str) -> Intent | None:
        """精确或子串匹配历史意图缓存。"""
        for item in self._intent_cache:
            cached_text = item.get("text", "")
            if text == cached_text or text in cached_text or cached_text in text:
                intent = item.get("intent")
                if isinstance(intent, Intent):
                    return Intent(
                        intent_type=intent.intent_type,
                        complexity=intent.complexity,
                        sentiment=intent.sentiment,
                        target_plate=intent.target_plate,
                        risk_flags=list(intent.risk_flags),
                        confidence=intent.confidence,
                        meta=dict(intent.meta),
                    )
        return None

    def _cache_intent(self, text: str, intent: Intent) -> None:
        self._intent_cache.append({"text": text, "intent": intent})
        if len(self._intent_cache) > self._cache_max_size:
            self._intent_cache = self._intent_cache[-self._cache_max_size:]

    async def _slow_path(
        self, text: str, self_state_summary: str, narrative_summary: str
    ) -> Intent:
        """LLM 严格 JSON 输出。只给裁剪后的上下文。"""
        schema = {
            "intent_type": "chat|task|control|query",
            "complexity": "low|medium|high",
            "sentiment": "neutral|urgent|negative",
            "target_plate": "null 或板块ID",
            "risk_flags": ["negation_detected", "ambiguous", "example_context", "none"],
            "confidence": "0.0-1.0",
        }

        prompt = (
            "你是意图翻译官，只做一件事：把用户输入翻译成下面的 JSON。\n"
            "禁止推理、禁止解释、禁止回答用户问题。\n"
            "只输出合法 JSON，不要 Markdown 代码块。\n\n"
            f"JSON Schema: {json.dumps(schema, ensure_ascii=False)}\n\n"
            "上下文（仅参考，不准展开）：\n"
            f"[自我状态]\n{self_state_summary[:180]}\n\n"
            f"[最近叙事]\n{narrative_summary[:180]}\n\n"
            f"[用户输入]\n{text}\n\n"
            "输出："
        )

        messages = [
            {"role": "system", "content": "你只输出 JSON 格式的意图翻译结果。"},
            {"role": "user", "content": prompt},
        ]

        try:
            response = await call_thinker_async(
                messages,
                scene=AIScene.CODE,
                hard_timeout=self.config.slow_path_timeout,
                model=self.config.slow_path_model,
            )
            return self._parse_llm_intent(response, text)
        except Exception as e:
            logger.warning(f"[IntentTranslator] SlowPath LLM 失败: {e}")
            return self._fallback_intent(text, reason=f"llm_error:{e}")

    def _parse_llm_intent(self, response: str, text: str) -> Intent:
        """解析 LLM JSON 输出。"""
        cleaned = response.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning(f"[IntentTranslator] LLM 输出非 JSON: {response[:200]}")
            return self._fallback_intent(text, reason="json_parse_error")

        intent_type = data.get("intent_type", "chat")
        if intent_type not in ("chat", "task", "control", "query"):
            intent_type = "chat"

        complexity = data.get("complexity", "medium")
        if complexity not in ("low", "medium", "high"):
            complexity = "medium"

        sentiment = data.get("sentiment", "neutral")
        if sentiment not in ("neutral", "urgent", "negative"):
            sentiment = "neutral"

        target_plate = data.get("target_plate")
        if target_plate in (None, "null", ""):
            target_plate = None

        risk_flags = data.get("risk_flags", [])
        if isinstance(risk_flags, str):
            risk_flags = [risk_flags]
        risk_flags = [f for f in risk_flags if f and f != "none"]

        confidence = float(data.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))

        return Intent(
            intent_type=intent_type,
            complexity=complexity,
            sentiment=sentiment,
            target_plate=target_plate,
            risk_flags=risk_flags,
            confidence=confidence,
            meta={"source": "slow_path", "raw_llm": data},
        )

    def _fallback_intent(self, text: str, reason: str = "fallback") -> Intent:
        return Intent(
            intent_type="chat",
            complexity="low",
            sentiment="neutral",
            risk_flags=["ambiguous"],
            confidence=0.5,
            meta={"reason": reason},
        )

    @staticmethod
    def _has_negation_near_task(text: str, window: int = 8) -> bool:
        """检测任务关键词附近是否出现否定词。"""
        lower = text.lower()
        task_markers = [
            "打开", "启动", "执行", "运行", "开始", "播放", "发送", "关闭",
            "停止", "暂停", "取消", "删除", "下单", "交易", "买", "卖",
            "open", "start", "run", "execute", "play", "send", "stop", "cancel", "buy", "sell",
        ]
        for neg in NEGATION_WORDS:
            for idx in [m.start() for m in re.finditer(re.escape(neg), lower)]:
                window_text = text[max(0, idx - window): idx + window + len(neg)]
                if any(tm in window_text for tm in task_markers):
                    return True
        return False

    @staticmethod
    def _is_example_context(text: str) -> bool:
        """检测是否是举例/引用/代码讨论语境。"""
        if "```" in text:
            return True
        if re.search(r"['\"].{3,}['\"]", text):
            return True
        return any(marker in text for marker in EXAMPLE_MARKERS)

    @staticmethod
    def _classification_to_intent(category: str, control_type: str | None, force_vision: bool) -> Intent:
        """把旧关键词分类结果映射为新 Intent 结构。"""
        if category == "simple_chat":
            return Intent(intent_type="chat", complexity="low", sentiment="neutral")
        if category == "task_status_query":
            return Intent(intent_type="query", complexity="low", sentiment="neutral", meta={"topic": "task_status"})
        if category == "task_control":
            return Intent(
                intent_type="control",
                complexity="low",
                sentiment="neutral",
                meta={"control_type": control_type},
            )
        if category == "start_monitor":
            return Intent(intent_type="control", complexity="low", sentiment="neutral", target_plate="vision", meta={"action": "start_monitor"})
        if category == "stop_monitor":
            return Intent(intent_type="control", complexity="low", sentiment="neutral", target_plate="vision", meta={"action": "stop_monitor"})
        if category == "potential_monitor":
            return Intent(intent_type="control", complexity="medium", sentiment="neutral", target_plate="vision", meta={"action": "confirm_monitor"})
        if force_vision or category == "force_vision":
            return Intent(intent_type="task", complexity="medium", sentiment="neutral", meta={"force_vision": True})
        return Intent(intent_type="task", complexity="medium", sentiment="neutral")
