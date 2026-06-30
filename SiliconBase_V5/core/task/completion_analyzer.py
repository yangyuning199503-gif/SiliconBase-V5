#!/usr/bin/env python3
"""
Task Completion Analyzer - SiliconBase V5
[Refactored] Migrated from agent_loop.py

Responsibilities:
- Analyze task completion using intent classification + context analysis
- Support multiple task types: single_action, multi_step, continuous, conditional
- Multi-dimensional scoring: intent, steps, results, satisfaction
- Backward compatible keyword fallback
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any

from core.config import config
from core.logger import logger

# 【P2 改造】RetryPolicy 接入
try:
    from core.task.retry_policy import AnalysisResult as RetryAnalysisResult
    from core.task.retry_policy import RetryPolicy
    _V2_RETRY_AVAILABLE = True
except ImportError:
    _V2_RETRY_AVAILABLE = False
    RetryPolicy = None
    RetryAnalysisResult = None


def _is_v2_task_retry_enabled() -> bool:
    """检查 v2_task_retry Feature Flag 是否开启"""
    if not _V2_RETRY_AVAILABLE:
        return False
    try:
        return config.is_feature_enabled("v2_task_retry")
    except Exception:
        return False


# =============================================================================
# Enums and Dataclasses
# =============================================================================

class TaskType(Enum):
    """Task type enumeration"""
    SINGLE_ACTION = auto()   # Single action task
    MULTI_STEP = auto()      # Multi-step task
    CONTINUOUS = auto()      # Continuous task (e.g., monitoring)
    CONDITIONAL = auto()     # Conditional task (if-then structure)
    CONVERSATION = auto()    # Pure conversation task


@dataclass
class CompletionScore:
    """Task completion score"""
    intent_analysis: float = 0.0      # User intent completion (0-1)
    step_completion: float = 0.0      # Step completion (0-1)
    result_validation: float = 0.0    # Result validity (0-1)
    user_satisfaction: float = 0.0    # User satisfaction (0-1)
    overall: float = 0.0              # Overall score (0-1)

    def calculate_overall(self, weights: dict[str, float] = None) -> float:
        """Calculate overall score"""
        if weights is None:
            weights = {
                "intent_analysis": 0.35,
                "step_completion": 0.30,
                "result_validation": 0.25,
                "user_satisfaction": 0.10
            }
        self.overall = (
            self.intent_analysis * weights["intent_analysis"] +
            self.step_completion * weights["step_completion"] +
            self.result_validation * weights["result_validation"] +
            self.user_satisfaction * weights["user_satisfaction"]
        )
        return self.overall


@dataclass
class TaskAnalysisResult:
    """Task analysis result"""
    task_type: TaskType = TaskType.SINGLE_ACTION
    confidence: float = 0.0           # Confidence (0-1)
    is_completed: bool = False
    scores: CompletionScore = field(default_factory=CompletionScore)
    reasoning: str = ""               # Reasoning explanation
    suggested_action: str = ""        # Suggested action


@dataclass
class TaskCompletionConfig:
    """
    Task completion detection configuration

    Loaded from config file, supports dynamic tuning
    """
    # Force continue limit
    max_force_continue: int = field(default_factory=lambda: config.get("task_completion.max_force_continue", 2))

    # Substantive result check
    substantive_result_min_length: int = field(default_factory=lambda: config.get("task_completion.content_substantial_threshold", 50))
    enable_substantive_result_check: bool = field(default_factory=lambda: config.get("task_completion.enable_substantive_result_check", True))

    # Keyword configuration
    multi_step_indicators: list[str] | None = None
    action_verbs_explicit: list[str] | None = None
    conservative_action_verbs: list[str] | None = None

    # Logging configuration
    enable_detailed_logging: bool = field(default_factory=lambda: config.get("task_completion.enable_detailed_logging", True))
    max_history_length: int = field(default_factory=lambda: config.get("task_completion.max_history_length", 20))

    def __post_init__(self):
        """Initialize default values from config"""
        if self.multi_step_indicators is None:
            self.multi_step_indicators = config.get(
                "task_completion.multi_step_indicators",
                ["然后", "接着", "再", "先", "后", "最后", "以及", "顺便", "一起", "同时", "并且"]
            )

        if self.action_verbs_explicit is None:
            self.action_verbs_explicit = config.get(
                "task_completion.action_verbs_explicit",
                ["输入", "写入", "填写", "点击", "选择", "保存", "发送", "播放", "删除", "复制", "粘贴"]
            )

        if self.conservative_action_verbs is None:
            self.conservative_action_verbs = config.get(
                "task_completion.conservative_action_verbs",
                ["输入", "写入", "填写", "点击", "保存", "发送"]
            )

        # Ensure mutable copies
        self.multi_step_indicators = list(self.multi_step_indicators)
        self.action_verbs_explicit = list(self.action_verbs_explicit)
        self.conservative_action_verbs = list(self.conservative_action_verbs)

    def reload_from_config(self) -> bool:
        """Reload configuration from file"""
        try:
            self.max_force_continue = config.get("task_completion.max_force_continue", 2)
            self.substantive_result_min_length = config.get("task_completion.content_substantial_threshold", 50)
            self.enable_substantive_result_check = config.get("task_completion.enable_substantive_result_check", True)
            self.multi_step_indicators = list(config.get(
                "task_completion.multi_step_indicators",
                self.multi_step_indicators
            ))
            self.action_verbs_explicit = list(config.get(
                "task_completion.action_verbs_explicit",
                self.action_verbs_explicit
            ))
            self.conservative_action_verbs = list(config.get(
                "task_completion.conservative_action_verbs",
                self.conservative_action_verbs
            ))
            self.enable_detailed_logging = config.get("task_completion.enable_detailed_logging", True)
            self.max_history_length = config.get("task_completion.max_history_length", 20)
            logger.info("[TaskCompletionConfig] Configuration reloaded from file")
            return True
        except Exception as e:
            logger.error(f"[TaskCompletionConfig] Failed to reload config: {e}")
            return False

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        import copy
        return {
            "max_force_continue": self.max_force_continue,
            "substantive_result_min_length": self.substantive_result_min_length,
            "enable_substantive_result_check": self.enable_substantive_result_check,
            "multi_step_indicators": copy.copy(self.multi_step_indicators),
            "action_verbs_explicit": copy.copy(self.action_verbs_explicit),
            "conservative_action_verbs": copy.copy(self.conservative_action_verbs),
            "enable_detailed_logging": self.enable_detailed_logging,
            "max_history_length": self.max_history_length,
        }


# Global config instance
task_completion_config = TaskCompletionConfig()


# =============================================================================
# Task Completion Analyzer Class
# =============================================================================

class TaskCompletionAnalyzer:
    """
    Intelligent task completion analyzer

    Uses intent classification + context analysis to detect task completion,
    replacing simple keyword matching.
    """

    # Single action task keywords (no multi-step needed)
    # 【注意】不要添加"打开"、"启动"等词，会导致AI说"打开成功"时误判为单步任务
    SINGLE_ACTION_KEYWORDS = [
        "查天气", "查时间", "查日期", "计算器", "计算",
        "翻译", "转换", "换算", "生成", "创建文件",
        "截图", "当前", "今天", "现在"
    ]

    # Multi-step indicators
    MULTI_STEP_KEYWORDS = [
        "然后", "接着", "再", "先", "后", "最后", "以及",
        "顺便", "一起", "同时", "并且", "之后", "之前",
        "第一步", "第二步", "第三步", "步骤", "流程",
        "完成...再", "做完...然后", "打开...输入", "搜索...复制"
    ]

    # Continuous task indicators
    CONTINUOUS_KEYWORDS = [
        "监控", "监听", "追踪", "跟踪", "实时", "一直",
        "持续", "每隔", "定时", "轮询", "等待",
        "直到", "当...时", "一旦...就"
    ]

    # Conditional task indicators
    CONDITIONAL_KEYWORDS = [
        "如果", "假如", "假设", "要是", "若", "条件是",
        "取决于", "根据", "视情况而定", "按情况",
        "成功则", "失败则", "否则", "不然"
    ]

    # User satisfaction keywords
    SATISFACTION_KEYWORDS = {
        "positive": ["谢谢", "感谢", "太好了", "完美", "不错", "可以", "好", "行"],
        "negative": ["不对", "错了", "不行", "不对", "重新", "还没好", "继续"]
    }

    def __init__(self):
        self.config = self._load_config()

    def _load_config(self) -> dict:
        """Load configuration from config file"""
        return {
            "completion_threshold": config.get("task_completion.analyzer.completion_threshold", 0.75),
            "high_confidence_threshold": config.get("task_completion.analyzer.high_confidence", 0.85),
            "low_confidence_threshold": config.get("task_completion.analyzer.low_confidence", 0.50),
            "enable_keyword_fallback": config.get("task_completion.analyzer.enable_keyword_fallback", True),
            "min_steps_for_multistep": config.get("task_completion.analyzer.min_steps", 2),
        }

    def analyze_task_type(self, user_instruction: str) -> TaskType:
        """Analyze task type"""
        instruction_lower = user_instruction.lower()

        # Check conditional tasks
        for keyword in self.CONDITIONAL_KEYWORDS:
            if keyword in instruction_lower:
                return TaskType.CONDITIONAL

        # Check continuous tasks
        for keyword in self.CONTINUOUS_KEYWORDS:
            if keyword in instruction_lower:
                return TaskType.CONTINUOUS

        # Check multi-step tasks
        multi_step_count = sum(1 for k in self.MULTI_STEP_KEYWORDS if k in instruction_lower)
        if multi_step_count >= 2 or ("先" in instruction_lower and "然后" in instruction_lower):
            return TaskType.MULTI_STEP

        # Check single action tasks
        for keyword in self.SINGLE_ACTION_KEYWORDS:
            if keyword in instruction_lower:
                return TaskType.SINGLE_ACTION

        # Default to single action
        return TaskType.SINGLE_ACTION

    def analyze_intent_completion(
        self,
        user_instruction: str,
        execution_history: list[dict],
        working_memory: Any
    ) -> tuple[float, str]:
        """
        Analyze if user intent is completed

        Returns:
            (completion_score, reasoning)
        """
        task_type = self.analyze_task_type(user_instruction)
        user_instruction.lower()

        # Extract user intent keywords
        intent_keywords = self._extract_intent_keywords(user_instruction)

        # Extract executed actions from history
        executed_actions = [
            h.get("tool", "") for h in execution_history
            if h.get("tool") and h.get("success", False)
        ]

        # Check intent match
        matched_intents = 0
        for keyword in intent_keywords:
            # Check in executed tools
            for action in executed_actions:
                if keyword in action.lower() or action in keyword:
                    matched_intents += 1
                    break
            # Check in execution history
            for hist in execution_history:
                result = hist.get("result", {})
                result_str = str(result).lower()
                if keyword in result_str:
                    matched_intents += 1
                    break

        if not intent_keywords:
            # No clear intent keywords, judge based on execution history
            if executed_actions:
                return 0.70, "No clear intent keywords, but tool execution records exist"
            return 0.30, "No clear intent and no execution records"

        intent_score = matched_intents / len(intent_keywords)

        # Adjust score based on task type
        if task_type == TaskType.SINGLE_ACTION and executed_actions:
            intent_score = max(intent_score, 0.80)  # Single action task completes once

        reasoning = f"Intent keyword match: {matched_intents}/{len(intent_keywords)}"
        return min(intent_score, 1.0), reasoning

    def analyze_step_completion(
        self,
        user_instruction: str,
        execution_history: list[dict],
        working_memory: Any
    ) -> tuple[float, str]:
        """
        Analyze step completion

        Returns:
            (completion_score, reasoning)
        """
        task_type = self.analyze_task_type(user_instruction)

        # Get planned steps (if any)
        planned_steps = []
        if hasattr(working_memory, 'ai_plan') and working_memory.ai_plan:
            plan = working_memory.ai_plan
            planned_steps = plan.get("steps", [])
            current_step = plan.get("current_step", 0)
            total_steps = len(planned_steps)

            if total_steps > 0:
                # Calculate based on plan progress
                completed_steps = sum(
                    1 for i, s in enumerate(planned_steps)
                    if i < current_step and s.get("status") == "completed"
                )
                step_score = completed_steps / total_steps
                reasoning = f"Plan steps completed: {completed_steps}/{total_steps}"
                return step_score, reasoning

        # No plan, estimate based on execution history
        executed_count = len([h for h in execution_history if h.get("success", False)])

        # Estimate expected steps based on task type
        expected_steps = self._estimate_expected_steps(task_type, user_instruction)

        if expected_steps <= 1:
            # Single step task
            if executed_count >= 1:
                return 1.0, "Single step task completed"
            return 0.0, "Single step task not executed"

        # Multi-step task
        step_score = min(executed_count / expected_steps, 1.0)
        reasoning = f"Executed steps: {executed_count}/{expected_steps}"
        return step_score, reasoning

    def analyze_result_validation(
        self,
        execution_history: list[dict]
    ) -> tuple[float, str]:
        """
        Analyze result validity

        Returns:
            (validity_score, reasoning)
        """
        if not execution_history:
            return 0.0, "No execution history"

        # Check last few results
        recent_history = execution_history[-3:] if len(execution_history) >= 3 else execution_history

        valid_results = 0
        total_results = 0
        has_substantive_content = False

        for hist in recent_history:
            result = hist.get("result", {})
            total_results += 1

            # Check success
            if result.get("success", False):
                valid_results += 1

                # Check substantive content
                content = result.get("data", "") or result.get("content", "") or result.get("result", "")
                content_str = str(content)
                if len(content_str) > 50:  # Has substantive result
                    has_substantive_content = True
            else:
                # Check if expected failure (e.g., file not found)
                error_msg = result.get("error", "").lower()
                if any(e in error_msg for e in ["not found", "不存在", "未找到", "找不到"]):
                    valid_results += 0.5  # Partially valid

        if total_results == 0:
            return 0.0, "No valid results"

        base_score = valid_results / total_results

        # Bonus for substantive content
        if has_substantive_content:
            base_score = min(base_score + 0.15, 1.0)
            reasoning = f"Valid results with substantive content: {valid_results}/{total_results}"
        else:
            reasoning = f"Result validity: {valid_results}/{total_results}"

        return base_score, reasoning

    def analyze_user_satisfaction(
        self,
        user_instruction: str,
        chat_history: list[dict] | None = None
    ) -> tuple[float, str]:
        """
        Analyze user satisfaction

        Returns:
            (satisfaction_score, reasoning)
        """
        if not chat_history:
            # No chat history, return neutral score
            return 0.50, "No chat history, neutral assessment"

        # Check recent user feedback
        recent_user_msgs = [
            msg.get("content", "")
            for msg in chat_history[-5:]
            if msg.get("role") == "user"
        ]

        if not recent_user_msgs:
            return 0.50, "No user feedback messages"

        # Analyze last user message
        last_msg = recent_user_msgs[-1].lower()

        # Check positive feedback
        positive_count = sum(1 for k in self.SATISFACTION_KEYWORDS["positive"] if k in last_msg)
        # Check negative feedback
        negative_count = sum(1 for k in self.SATISFACTION_KEYWORDS["negative"] if k in last_msg)

        if positive_count > 0 and negative_count == 0:
            return 0.85, "User expressed positive feedback"
        elif negative_count > 0:
            return 0.25, "User expressed negative feedback, may not be satisfied"
        elif "?" in last_msg or "？" in last_msg:
            return 0.60, "User has questions, may need further help"
        else:
            return 0.50, "User feedback neutral"

    def analyze(
        self,
        user_instruction: str,
        execution_history: list[dict],
        working_memory: Any,
        chat_history: list[dict] | None = None
    ) -> TaskAnalysisResult:
        """
        Execute complete task completion analysis

        Returns:
            TaskAnalysisResult: Analysis result
        """
        result = TaskAnalysisResult()

        # 1. Analyze task type
        result.task_type = self.analyze_task_type(user_instruction)

        # 2. Calculate dimension scores
        result.scores.intent_analysis, intent_reasoning = self.analyze_intent_completion(
            user_instruction, execution_history, working_memory
        )

        result.scores.step_completion, step_reasoning = self.analyze_step_completion(
            user_instruction, execution_history, working_memory
        )

        result.scores.result_validation, result_reasoning = self.analyze_result_validation(
            execution_history
        )

        result.scores.user_satisfaction, satisfaction_reasoning = self.analyze_user_satisfaction(
            user_instruction, chat_history
        )

        # 3. Calculate overall score
        overall_score = result.scores.calculate_overall()
        result.confidence = overall_score

        # 4. Determine if completed
        threshold = self.config["completion_threshold"]
        result.is_completed = overall_score >= threshold

        # 5. Generate reasoning
        result.reasoning = (
            f"Task type: {result.task_type.name}, "
            f"Intent: {result.scores.intent_analysis:.2f}({intent_reasoning}), "
            f"Steps: {result.scores.step_completion:.2f}({step_reasoning}), "
            f"Results: {result.scores.result_validation:.2f}({result_reasoning}), "
            f"Satisfaction: {result.scores.user_satisfaction:.2f}({satisfaction_reasoning})"
        )

        # 6. Suggest action
        if result.is_completed:
            result.suggested_action = "Task completed, can return FINAL_ANSWER"
        elif result.scores.step_completion < 0.5:
            result.suggested_action = "Continue executing remaining steps"
        elif result.scores.result_validation < 0.5:
            result.suggested_action = "Validate current results, may need retry"
        else:
            result.suggested_action = "Continue monitoring task progress"

        return result

    def _extract_intent_keywords(self, instruction: str) -> list[str]:
        """Extract intent keywords from user instruction"""
        # Remove stop words
        stop_words = {"请", "帮我", "给我", "我想要", "能不能", "可以", "一下"}
        words = []

        # Simple tokenization and keyword extraction
        for phrase in instruction.split("。"):
            for part in phrase.split("，"):
                part = part.strip()
                if part and part not in stop_words:
                    # Extract verb+noun combinations
                    words.append(part)

        return words[:5]  # Return at most 5 keywords

    def _estimate_expected_steps(self, task_type: TaskType, instruction: str) -> int:
        """Estimate expected number of steps"""
        if task_type == TaskType.SINGLE_ACTION:
            return 1
        elif task_type == TaskType.MULTI_STEP:
            # Estimate based on keyword count
            multi_step_count = sum(1 for k in self.MULTI_STEP_KEYWORDS if k in instruction)
            return min(max(multi_step_count, 2), 5)
        elif task_type == TaskType.CONDITIONAL:
            return 2  # Conditional tasks usually at least 2 steps
        elif task_type == TaskType.CONTINUOUS:
            return 3  # Continuous tasks at least 3 steps
        return 1

    def keyword_fallback_check(
        self,
        user_instruction: str,
        execution_history: list[dict]
    ) -> bool | None:
        """
        Original keyword matching fallback check

        Returns:
            True=completed, False=not completed, None=cannot determine
        """
        if not self.config["enable_keyword_fallback"]:
            return None

        instruction_lower = user_instruction.lower()
        tool_count = len([h for h in execution_history if h.get("tool")])

        # Simple keyword check (only as last fallback)
        strong_multi_step = ["先", "然后", "接着", "再", "最后"]

        if tool_count <= 1:
            for keyword in strong_multi_step:
                if keyword in instruction_lower:
                    return False  # Likely multi-step but not completed

        return None  # Cannot determine, let upper layer decide


# =============================================================================
# Global Instance and Helper Functions
# =============================================================================

_task_completion_analyzer: TaskCompletionAnalyzer | None = None


def get_task_completion_analyzer() -> TaskCompletionAnalyzer:
    """Get task completion analyzer singleton"""
    global _task_completion_analyzer
    if _task_completion_analyzer is None:
        _task_completion_analyzer = TaskCompletionAnalyzer()
    return _task_completion_analyzer


def _analyze_task_pure(
    user_instruction: str,
    execution_history: list,
    working_memory,
    chat_history: list[dict] | None = None,
) -> tuple[TaskAnalysisResult, dict]:
    """
    纯函数：分析任务完成状态，不修改任何外部状态。

    将 check_task_completed 中的分析逻辑提取为纯函数，
    所有状态修改（force_continue_count、task_check_history）由调用方负责。

    Returns:
        (analysis_result, task_check_record)
    """
    task_check_record = {
        "timestamp": datetime.now().isoformat(),
        "user_instruction": user_instruction[:50],
        "execution_count": len(execution_history),
    }

    # Phase 0: 快速判断（工具失败）
    if execution_history:
        last_execution = execution_history[-1]
        result = last_execution.get("result", {})
        if result.get("success") is False:
            task_check_record["decision"] = "tool_failed"
            task_check_record["reason"] = f"tool_failed({result.get('error_code')})"
            analysis = TaskAnalysisResult(
                is_completed=False,
                confidence=0.0,
                reasoning="工具执行失败",
            )
            return analysis, task_check_record

    # Phase 3: 智能分析
    analyzer = get_task_completion_analyzer()
    analysis_result = analyzer.analyze(
        user_instruction=user_instruction,
        execution_history=execution_history,
        working_memory=working_memory,
        chat_history=chat_history
    )

    # Phase 4: 决策
    cfg = analyzer.config

    # 4.1 High confidence completion
    if analysis_result.is_completed and analysis_result.confidence >= cfg["high_confidence_threshold"]:
        task_check_record["decision"] = "completed_high_confidence"
        task_check_record["reason"] = analysis_result.reasoning
        task_check_record["confidence"] = analysis_result.confidence
        return analysis_result, task_check_record

    # 4.2 Low confidence force continue
    if not analysis_result.is_completed and analysis_result.confidence < cfg["low_confidence_threshold"]:
        task_check_record["decision"] = "allow_ai_judgment_low_confidence"
        task_check_record["reason"] = analysis_result.reasoning
        task_check_record["confidence"] = analysis_result.confidence
        return analysis_result, task_check_record

    # 4.3 Not completed (medium confidence)
    if not analysis_result.is_completed:
        task_check_record["decision"] = "force_continue_analyzer"
        task_check_record["reason"] = analysis_result.reasoning
        task_check_record["confidence"] = analysis_result.confidence
        task_check_record["suggested_action"] = analysis_result.suggested_action
        return analysis_result, task_check_record

    # 4.4 Completed but medium confidence (fallback to keyword check)
    if analysis_result.is_completed and analysis_result.confidence < cfg["high_confidence_threshold"]:
        keyword_result = analyzer.keyword_fallback_check(user_instruction, execution_history)

        if keyword_result is False:
            task_check_record["decision"] = "force_continue_keyword_fallback"
            task_check_record["reason"] = "analyzer_says_complete_but_keywords_disagree"
            task_check_record["analyzer_confidence"] = analysis_result.confidence
            return analysis_result, task_check_record
        elif keyword_result is True:
            task_check_record["decision"] = "completed_keyword_confirmed"
            task_check_record["reason"] = analysis_result.reasoning
            task_check_record["analyzer_confidence"] = analysis_result.confidence
            return analysis_result, task_check_record

    # 4.5 Default trust analyzer result
    task_check_record["decision"] = "analyzer_decision"
    task_check_record["reason"] = analysis_result.reasoning
    task_check_record["confidence"] = analysis_result.confidence
    task_check_record["is_completed"] = analysis_result.is_completed
    return analysis_result, task_check_record


def check_task_completed(
    working_memory,
    user_instruction: str,
    execution_history: list,
    chat_history: list[dict] | None = None,
    retry_policy: Any | None = None,
    current_round: int = 0,
) -> bool:
    """
    [P1 Fix] Intelligent task completion detection

    【关键修复】优先使用客观验证结果（视觉验证），而非复杂的意图分析
    如果视觉验证成功，直接认为任务完成，不再强制 AI 继续

    Args:
        working_memory: Working memory object
        user_instruction: User instruction
        execution_history: Execution history
        chat_history: Optional chat history for user satisfaction analysis

    Returns:
        True = completed (allow FINAL_ANSWER), False = need to continue
    """
    # ═════════════════════════════════════════════════════════════════════════════
    # V2 路径：纯函数 + RetryPolicy（零副作用）
    # ═════════════════════════════════════════════════════════════════════════════
    if _is_v2_task_retry_enabled() and RetryPolicy is not None:
        # 纯函数分析（不修改任何外部状态）
        analysis_result, task_check_record = _analyze_task_pure(
            user_instruction, execution_history, working_memory, chat_history
        )

        # 获取或创建 RetryPolicy
        policy = retry_policy
        if policy is None:
            # 从 working_memory 读取旧计数初始化（只读，不写入 working_memory）
            old_count = getattr(working_memory, '_force_continue_count', 0)
            policy = RetryPolicy(max_force_continues=task_completion_config.max_force_continue)
            policy.force_continue_count = old_count

        # 转换为 RetryPolicy 需要的 AnalysisResult
        retry_analysis = RetryAnalysisResult(
            is_completed=analysis_result.is_completed,
            confidence=analysis_result.confidence,
            reasoning=analysis_result.reasoning,
            details={
                "task_type": analysis_result.task_type.name,
                "suggested_action": analysis_result.suggested_action,
                "task_check_record": task_check_record,
            }
        )

        # RetryPolicy 决策（状态绑定到 policy 实例，不修改 working_memory）
        decision = policy.decide(retry_analysis, current_round)
        policy.record_decision(decision)

        logger.info(
            f"[TaskCheck-V2] RetryPolicy decision: {decision.action}, "
            f"reason={decision.reason}, "
            f"force_continue={decision.force_continue_count}/{decision.max_force_continues}"
        )

        # 映射为 bool，保持接口兼容
        # complete → True
        # continue / abort / yield → False（当前 agent_loop 只处理 bool，后续改造 agent_loop 时可处理 abort/yield）
        return decision.action == "complete"

    # ═════════════════════════════════════════════════════════════════════════════
    # V1 路径：保留旧逻辑（含副作用，修改 working_memory）
    # ═════════════════════════════════════════════════════════════════════════════
    # ========== [Phase 0: Quick decision based on objective evidence] ==========
    if execution_history:
        last_execution = execution_history[-1]
        result = last_execution.get("result", {})

        # 0.1 工具明确失败 = 这一步未完成
        if result.get("success") is False:
            logger.info(f"[TaskCheck] ❌ 工具执行失败({result.get('error_code')})，当前步骤未完成")
            return False

        # 0.2 视觉验证成功 = 这一步的实际效果已确认（不直接return True）
        visual_verification = result.get("data", {}).get("visual_verification")
        if visual_verification and visual_verification.get("status") == "verified":
            logger.info(f"[TaskCheck] ✅ 视觉验证成功，当前步骤完成: {visual_verification.get('description', '')[:50]}...")

    # ========== [Phase 1: Initialize and counter management] ==========
    force_continue_count = getattr(working_memory, '_force_continue_count', 0)

    task_check_record = {
        "timestamp": datetime.now().isoformat(),
        "user_instruction": user_instruction[:50],
        "execution_count": len(execution_history),
        "force_continue_count_before": force_continue_count
    }

    # ========== [Phase 2: Force continue limit check] ==========
    if force_continue_count >= task_completion_config.max_force_continue:
        logger.info(f"[TaskCheck] AI has been forced to continue {force_continue_count} times, trusting AI judgment")
        task_check_record["decision"] = "allow_ai_judgment"
        task_check_record["reason"] = f"force_continue_limit_reached({force_continue_count})"
        _update_task_check_history(working_memory, task_check_record)
        return True

    # ========== [Phase 3: Smart analysis with TaskCompletionAnalyzer] ==========
    analyzer = get_task_completion_analyzer()
    analysis_result = analyzer.analyze(
        user_instruction=user_instruction,
        execution_history=execution_history,
        working_memory=working_memory,
        chat_history=chat_history
    )

    # Log detailed analysis
    logger.info(f"[TaskCheck] Task type: {analysis_result.task_type.name}, "
                f"Confidence: {analysis_result.confidence:.2f}, "
                f"Intent: {analysis_result.scores.intent_analysis:.2f}, "
                f"Steps: {analysis_result.scores.step_completion:.2f}, "
                f"Results: {analysis_result.scores.result_validation:.2f}, "
                f"Satisfaction: {analysis_result.scores.user_satisfaction:.2f}")
    logger.info(f"[TaskCheck] Reasoning: {analysis_result.reasoning}")

    # ========== [Phase 4: Decision based on analysis] ==========

    # 4.1 High confidence completion
    if analysis_result.is_completed and analysis_result.confidence >= analyzer.config["high_confidence_threshold"]:
        logger.info(f"[TaskCheck] High confidence({analysis_result.confidence:.2f}) task completed")
        task_check_record["decision"] = "completed_high_confidence"
        task_check_record["reason"] = analysis_result.reasoning
        task_check_record["confidence"] = analysis_result.confidence
        _update_task_check_history(working_memory, task_check_record)
        return True

    # 4.2 Low confidence force continue
    if not analysis_result.is_completed and analysis_result.confidence < analyzer.config["low_confidence_threshold"]:
        logger.info(f"[TaskCheck] Low confidence({analysis_result.confidence:.2f}), trusting AI judgment")
        task_check_record["decision"] = "allow_ai_judgment_low_confidence"
        task_check_record["reason"] = analysis_result.reasoning
        task_check_record["confidence"] = analysis_result.confidence
        _update_task_check_history(working_memory, task_check_record)
        return True

    # 4.3 Not completed (medium confidence)
    if not analysis_result.is_completed:
        logger.info(f"[TaskCheck] Analysis shows task not completed: {analysis_result.suggested_action}")
        increment_force_continue_count(working_memory)
        task_check_record["decision"] = "force_continue_analyzer"
        task_check_record["reason"] = analysis_result.reasoning
        task_check_record["confidence"] = analysis_result.confidence
        task_check_record["suggested_action"] = analysis_result.suggested_action
        _update_task_check_history(working_memory, task_check_record)
        return False

    # 4.4 Completed but medium confidence (fallback to keyword check)
    if analysis_result.is_completed and analysis_result.confidence < analyzer.config["high_confidence_threshold"]:
        logger.info("[TaskCheck] Analyzer says complete but medium confidence, keyword fallback check")

        keyword_result = analyzer.keyword_fallback_check(user_instruction, execution_history)

        if keyword_result is False:
            logger.info("[TaskCheck] Keyword fallback check says task not completed")
            increment_force_continue_count(working_memory)
            task_check_record["decision"] = "force_continue_keyword_fallback"
            task_check_record["reason"] = "analyzer_says_complete_but_keywords_disagree"
            task_check_record["analyzer_confidence"] = analysis_result.confidence
            _update_task_check_history(working_memory, task_check_record)
            return False
        elif keyword_result is True:
            logger.info("[TaskCheck] Keyword fallback check confirms task completed")
            task_check_record["decision"] = "completed_keyword_confirmed"
            task_check_record["reason"] = analysis_result.reasoning
            task_check_record["analyzer_confidence"] = analysis_result.confidence
            _update_task_check_history(working_memory, task_check_record)
            return True

    # 4.5 Default trust analyzer result
    logger.info(f"[TaskCheck] Trusting analyzer, task {'completed' if analysis_result.is_completed else 'not completed'}")
    task_check_record["decision"] = "analyzer_decision"
    task_check_record["reason"] = analysis_result.reasoning
    task_check_record["confidence"] = analysis_result.confidence
    task_check_record["is_completed"] = analysis_result.is_completed
    _update_task_check_history(working_memory, task_check_record)

    if not analysis_result.is_completed:
        increment_force_continue_count(working_memory)

    return analysis_result.is_completed


def increment_force_continue_count(working_memory):
    """Increment force continue counter"""
    current_count = getattr(working_memory, '_force_continue_count', 0)
    working_memory._force_continue_count = current_count + 1
    logger.info(f"[TaskCheck] Force continue counter: {current_count} -> {current_count + 1}")


def _update_task_check_history(working_memory, record: dict):
    """Update task check history"""
    history = getattr(working_memory, '_task_check_history', [])
    history.append(record)
    # Limit history length
    if len(history) > task_completion_config.max_history_length:
        history.pop(0)
    working_memory._task_check_history = history
    logger.info(f"[TaskCheck] Decision record: {record.get('decision')}, Reason: {record.get('reason')}")


__all__ = [
    "TaskType",
    "CompletionScore",
    "TaskAnalysisResult",
    "TaskCompletionConfig",
    "task_completion_config",
    "TaskCompletionAnalyzer",
    "get_task_completion_analyzer",
    "check_task_completed",
    "increment_force_continue_count",
]
