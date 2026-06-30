"""
意识系统集成模块 - 真正影响决策的实现

核心思路：
1. 通过Prompt Engineering影响AI决策（控制输入）
2. 通过意图解析干预影响决策（控制输出解析）
3. 通过工具选择排序影响决策（控制选项）
4. 通过循环控制影响决策（控制流程）
"""

import logging
import time
from dataclasses import asdict, dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class DecisionType(Enum):
    """决策类型"""
    SUGGESTION = "suggestion"          # 建议（低影响）
    GUIDANCE = "guidance"              # 指导（中影响）
    DIRECTIVE = "directive"            # 指令（高影响）
    OVERRIDE = "override"              # 覆盖（强制）


@dataclass
class ConsciousnessDecision:
    """意识决策封装"""
    decision_type: DecisionType        # 决策类型
    confidence: float                  # 置信度 0-1
    situation_analysis: str            # 情况分析
    recommended_action: str            # 建议行动
    suggested_tool: str | None = None      # 建议工具
    tool_params: dict | None = None        # 工具参数
    should_stop: bool = False          # 是否建议停止
    stop_reason: str | None = None  # 停止原因
    priority_score: float = 1.0        # 优先级分数（用于排序）
    reasoning: str = ""                # 决策理由

    def to_prompt_section(self) -> str:
        """转换为提示词段落"""
        sections = []

        # 根据决策类型调整语气
        if self.decision_type == DecisionType.OVERRIDE:
            sections.append("【系统指令 - 强制执行】")
        elif self.decision_type == DecisionType.DIRECTIVE:
            sections.append("【系统指导 - 强烈建议】")
        elif self.decision_type == DecisionType.GUIDANCE:
            sections.append("【系统建议】")
        else:
            sections.append("【系统思考】")

        sections.append(f"当前状态分析: {self.situation_analysis}")
        sections.append(f"建议行动: {self.recommended_action}")

        if self.suggested_tool:
            sections.append(f"推荐工具: {self.suggested_tool}")

        if self.should_stop:
            sections.append(f"停止建议: {self.stop_reason}")

        sections.append(f"置信度: {self.confidence:.0%}")
        sections.append(f"理由: {self.reasoning}")

        return "\n".join(sections)


class WorkingMemoryInjector:
    """
    工作记忆注入器

    将意识决策以不同优先级注入工作记忆
    """

    def __init__(self):
        self.injection_history: list[dict] = []

    def inject_to_working_memory(
        self,
        working_memory: list[dict],
        decision: ConsciousnessDecision,
        insertion_position: str = "head"  # "head", "before_user", "tail"
    ) -> list[dict]:
        """
        将意识决策注入工作记忆

        Args:
            working_memory: 当前工作记忆（消息列表）
            decision: 意识决策
            insertion_position: 插入位置
                - "head": 插入到最前面（最高优先级）
                - "before_user": 插入到用户消息之前
                - "tail": 插入到最后面（仅供参考）

        Returns:
            修改后的工作记忆
        """
        # 创建意识消息
        consciousness_message = {
            "role": "system",
            "content": decision.to_prompt_section(),
            "name": "consciousness_system",
            "timestamp": time.time(),
            "consciousness_decision": asdict(decision)  # 保留原始数据供后续使用
        }

        # 根据决策类型调整消息呈现方式
        if decision.decision_type == DecisionType.OVERRIDE:
            # 覆盖模式：添加到最前面，并添加特殊标记
            consciousness_message["priority"] = "critical"
            new_memory = [consciousness_message] + working_memory

        elif decision.decision_type == DecisionType.DIRECTIVE:
            # 指令模式：添加到最前面
            consciousness_message["priority"] = "high"
            new_memory = [consciousness_message] + working_memory

        elif insertion_position == "before_user":
            # 找到最后一条用户消息，插入到其后
            new_memory = self._insert_before_last_user(working_memory, consciousness_message)

        elif insertion_position == "tail":
            # 添加到末尾
            new_memory = working_memory + [consciousness_message]

        else:  # "head" 默认
            new_memory = [consciousness_message] + working_memory

        # 记录历史
        self.injection_history.append({
            "timestamp": time.time(),
            "decision_type": decision.decision_type.value,
            "position": insertion_position,
            "content_preview": decision.situation_analysis[:50]
        })

        logger.info(f"[WorkingMemoryInjector] 已注入意识决策: {decision.decision_type.value}, "
                   f"位置: {insertion_position}, 置信度: {decision.confidence}")

        return new_memory

    def _insert_before_last_user(self, memory: list[dict], message: dict) -> list[dict]:
        """在最后一条用户消息之前插入"""
        # 从后往前找最后一条用户消息
        for i in range(len(memory) - 1, -1, -1):
            if memory[i].get("role") == "user":
                # 在这条消息之前插入
                return memory[:i] + [message] + memory[i:]
        # 没找到用户消息，插到开头
        return [message] + memory


class IntentParserInterceptor:
    """
    意图解析拦截器

    在AI响应解析阶段干预，强制执行意识系统的决策
    """

    def __init__(self, consciousness_manager):
        self.consciousness = consciousness_manager
        self.interception_rules = []

    def intercept_parsed_intent(
        self,
        parsed_intent: dict,
        consciousness_decision: ConsciousnessDecision | None = None
    ) -> dict:
        """
        拦截并修改解析后的意图

        Args:
            parsed_intent: AI解析后的意图
            consciousness_decision: 意识决策

        Returns:
            修改后的意图
        """
        if not consciousness_decision:
            return parsed_intent

        modified_intent = parsed_intent.copy()

        # 根据决策类型进行不同级别的干预
        if consciousness_decision.decision_type == DecisionType.OVERRIDE:
            # 强制覆盖：完全替换AI的决策
            if consciousness_decision.suggested_tool:
                modified_intent["tool_call"] = {
                    "tool": consciousness_decision.suggested_tool,
                    "params": consciousness_decision.tool_params or {}
                }
                modified_intent["override_by_consciousness"] = True
                logger.info(f"[IntentParserInterceptor] 强制覆盖工具选择为: "
                           f"{consciousness_decision.suggested_tool}")

            if consciousness_decision.should_stop:
                modified_intent["should_stop"] = True
                modified_intent["stop_reason"] = consciousness_decision.stop_reason

        elif consciousness_decision.decision_type == DecisionType.DIRECTIVE:
            # 指导模式：如果AI没有明确选择，使用意识的建议
            if not parsed_intent.get("tool_call") and consciousness_decision.suggested_tool:
                modified_intent["tool_call"] = {
                    "tool": consciousness_decision.suggested_tool,
                    "params": consciousness_decision.tool_params or {}
                }
                modified_intent["guided_by_consciousness"] = True

        elif consciousness_decision.decision_type == DecisionType.GUIDANCE:
            # 建议模式：添加元数据，让后续处理参考
            modified_intent["consciousness_suggestion"] = {
                "tool": consciousness_decision.suggested_tool,
                "confidence": consciousness_decision.confidence,
                "reasoning": consciousness_decision.reasoning
            }

        return modified_intent


class ToolSelectorRanker:
    """
    工具选择排序器

    根据意识系统的建议调整工具列表顺序，影响AI选择
    """

    def __init__(self):
        self.tool_scores: dict[str, float] = {}

    def rank_tools(
        self,
        available_tools: list[dict],
        consciousness_decision: ConsciousnessDecision | None = None,
        execution_history: list[dict] = None
    ) -> list[dict]:
        """
        对工具进行排序

        Args:
            available_tools: 可用工具列表
            consciousness_decision: 意识决策
            execution_history: 执行历史

        Returns:
            排序后的工具列表
        """
        if not consciousness_decision or not consciousness_decision.suggested_tool:
            return available_tools

        # 为每个工具计算分数
        scored_tools = []
        for tool in available_tools:
            tool_id = tool.get("id", "")
            base_score = 1.0

            # 如果匹配意识建议的工具，大幅提升分数
            if tool_id == consciousness_decision.suggested_tool:
                # 根据决策类型调整提升幅度
                if consciousness_decision.decision_type == DecisionType.OVERRIDE:
                    base_score += 100.0  # 确保排在最前面
                elif consciousness_decision.decision_type == DecisionType.DIRECTIVE:
                    base_score += 10.0 * consciousness_decision.confidence
                else:
                    base_score += 5.0 * consciousness_decision.confidence

            # 惩罚最近失败过的工具
            if execution_history:
                recent_failures = sum(
                    1 for h in execution_history[-3:]
                    if h.get("tool") == tool_id and not h.get("result", {}).get("success", True)
                )
                base_score -= recent_failures * 2.0

            scored_tools.append((tool, base_score))

        # 按分数排序
        scored_tools.sort(key=lambda x: x[1], reverse=True)

        # 记录排序结果
        top_tool = scored_tools[0][0] if scored_tools else None
        if top_tool:
            logger.info(f"[ToolSelectorRanker] 工具排序完成，首选: {top_tool.get('id')}")

        return [tool for tool, _ in scored_tools]


class LoopController:
    """
    循环控制器

    让意识系统直接控制ReAct循环的Stop/Continue决策
    """

    def __init__(self):
        self.loop_state = {
            "round_count": 0,
            "forced_stop": False,
            "forced_continue": False,
            "consciousness_override": False
        }

    def should_stop(
        self,
        consciousness_decision: ConsciousnessDecision | None = None,
        ai_response: dict | None = None,
        execution_history: list[dict] = None,
        max_rounds: int = 10
    ) -> tuple[bool, str]:
        """
        判断是否应停止循环

        Returns:
            (是否停止, 停止原因)
        """
        self.loop_state["round_count"] += 1

        # 1. 检查意识系统的强制停止建议
        if consciousness_decision and consciousness_decision.should_stop:
            if consciousness_decision.confidence > 0.8:
                reason = f"意识系统高置信度建议停止: {consciousness_decision.stop_reason}"
                self.loop_state["forced_stop"] = True
                logger.info(f"[LoopController] {reason}")
                return True, reason
            elif consciousness_decision.confidence > 0.5:
                # 中等置信度，结合AI判断
                if ai_response and ai_response.get("should_stop"):
                    reason = f"意识系统与AI一致建议停止: {consciousness_decision.stop_reason}"
                    return True, reason

        # 2. 检查意识系统的强制继续建议
        if (
            consciousness_decision
            and consciousness_decision.decision_type == DecisionType.DIRECTIVE
            and consciousness_decision.confidence > 0.9
            and not consciousness_decision.should_stop
            and ai_response
            and ai_response.get("should_stop")
        ):
            # 高置信度建议继续，即使AI想停止
            logger.info("[LoopController] AI建议停止，但意识系统高置信度建议继续")
            self.loop_state["forced_continue"] = True
            return False, "意识系统建议继续"

        # 3. 检查最大轮数
        if self.loop_state["round_count"] >= max_rounds:
            return True, f"达到最大轮数限制: {max_rounds}"

        # 4. 默认使用AI的判断
        if ai_response:
            return ai_response.get("should_stop", False), ai_response.get("stop_reason", "AI决定停止")

        return False, "继续执行"


class ConsciousnessDecisionEngine:
    """
    意识决策引擎

    整合所有决策影响机制，提供统一的决策接口
    """

    def __init__(self, consciousness_manager):
        self.consciousness = consciousness_manager
        self.memory_injector = WorkingMemoryInjector()
        self.intent_interceptor = IntentParserInterceptor(consciousness_manager)
        self.tool_ranker = ToolSelectorRanker()
        self.loop_controller = LoopController()

        # 决策统计
        self.decision_stats = {
            "total_decisions": 0,
            "overrides": 0,
            "directives": 0,
            "guidance": 0,
            "suggestions": 0
        }

    def make_decision(
        self,
        user_instruction: str,
        execution_history: list[dict],
        current_round: int,
        working_memory: list[dict],
        context: dict = None
    ) -> ConsciousnessDecision:
        """
        生成意识决策

        这是从原有意识系统升级的核心方法
        """
        self.decision_stats["total_decisions"] += 1

        # 1. 分析当前情况
        self._analyze_situation(
            user_instruction, execution_history, current_round
        )

        # 2. 检测异常模式
        pattern = self._detect_pattern(execution_history)

        # 3. 根据情况生成决策
        if pattern == "infinite_loop":
            decision = ConsciousnessDecision(
                decision_type=DecisionType.OVERRIDE,
                confidence=0.95,
                situation_analysis="检测到无限循环模式，同一工具重复执行超过3次",
                recommended_action="停止当前任务，报告循环错误",
                should_stop=True,
                stop_reason="检测到无限循环",
                reasoning="重复执行相同工具且无进展，必须强制停止"
            )
            self.decision_stats["overrides"] += 1

        elif pattern == "repeated_failures":
            # 查找替代工具
            alternative_tool = self._find_alternative_tool(
                execution_history[-1].get("tool"), execution_history
            )
            decision = ConsciousnessDecision(
                decision_type=DecisionType.DIRECTIVE,
                confidence=0.85,
                situation_analysis="最近3次执行均失败，需要更换策略",
                recommended_action=f"尝试使用替代工具: {alternative_tool or '其他工具'}",
                suggested_tool=alternative_tool,
                reasoning="同一工具多次失败，建议切换方案"
            )
            self.decision_stats["directives"] += 1

        elif pattern == "task_completion":
            decision = ConsciousnessDecision(
                decision_type=DecisionType.DIRECTIVE,
                confidence=0.9,
                situation_analysis="检测到任务已完成的所有条件",
                recommended_action="停止循环，返回最终结果",
                should_stop=True,
                stop_reason="任务目标已达成",
                reasoning="所有必要步骤已完成，无需继续执行"
            )
            self.decision_stats["directives"] += 1

        else:
            # 正常情况，给出建议
            suggested_tool = self._suggest_tool(user_instruction, execution_history)
            decision = ConsciousnessDecision(
                decision_type=DecisionType.GUIDANCE,
                confidence=0.6,
                situation_analysis="任务进展正常",
                recommended_action=f"继续执行，建议尝试: {suggested_tool or '根据上下文判断'}",
                suggested_tool=suggested_tool,
                reasoning="基于当前上下文和历史执行模式"
            )
            self.decision_stats["guidance"] += 1

        logger.info(f"[ConsciousnessDecisionEngine] 生成决策: {decision.decision_type.value}, "
                   f"置信度: {decision.confidence}, 建议停止: {decision.should_stop}")

        return decision

    def _analyze_situation(
        self,
        user_instruction: str,
        execution_history: list[dict],
        current_round: int
    ) -> dict:
        """分析当前情况"""
        return {
            "steps_executed": len(execution_history),
            "current_round": current_round,
            "last_action_success": execution_history[-1].get("result", {}).get("success", False) if execution_history else None,
            "unique_tools_used": len({h.get("tool") for h in execution_history}) if execution_history else 0
        }

    def _detect_pattern(self, execution_history: list[dict]) -> str | None:
        """检测执行模式"""
        if len(execution_history) < 2:
            return None

        # 检测无限循环：同一工具重复3次以上
        recent_tools = [h.get("tool") for h in execution_history[-3:]]
        if len(set(recent_tools)) == 1 and len(recent_tools) == 3:
            return "infinite_loop"

        # 检测重复失败：最近3次都失败
        recent_results = [h.get("result", {}).get("success", True) for h in execution_history[-3:]]
        if len(recent_results) == 3 and not any(recent_results):
            return "repeated_failures"

        # 检测任务完成
        if len(execution_history) > 0:
            last_result = execution_history[-1].get("result", {})
            if last_result.get("success") and last_result.get("task_complete"):
                return "task_completion"

        return None

    def _find_alternative_tool(self, failed_tool: str, execution_history: list[dict]) -> str | None:
        """查找替代工具"""
        # 工具功能映射表
        alternatives = {
            "web_search": ["browser_open", "web_automation"],
            "file_read": ["file_list", "file_search"],
            "screen_capture": ["pixel_capture", "clipboard_read"],
            # ... 更多映射
        }
        return alternatives.get(failed_tool, ["user_ask"])[0]

    def _suggest_tool(self, user_instruction: str, execution_history: list[dict]) -> str | None:
        """建议工具"""
        # 基于用户指令关键词匹配
        keyword_tools = {
            "搜索": "web_search",
            "打开": "launch_app",
            "文件": "file_read",
            "截图": "screen_capture",
            "点击": "mouse_click",
            "输入": "keyboard_type"
        }

        for keyword, tool in keyword_tools.items():
            if keyword in user_instruction:
                return tool

        return None

    def get_stats(self) -> dict:
        """获取决策统计"""
        return self.decision_stats.copy()


# ═════════════════════════════════════════════════════════════════════════════
# 与现有Agent Loop的集成接口
# ═════════════════════════════════════════════════════════════════════════════

class ConsciousnessEnabledAgentLoop:
    """
    启用意识系统的Agent Loop包装器

    展示如何在现有Agent Loop中集成意识决策
    """

    def __init__(self, agent_loop_instance, consciousness_manager):
        self.agent_loop = agent_loop_instance
        self.consciousness = consciousness_manager
        self.decision_engine = ConsciousnessDecisionEngine(consciousness_manager)

        # 覆盖agent_loop的方法
        self._original_build_prompt = agent_loop_instance.build_prompt
        self._original_parse_response = agent_loop_instance.parse_response
        self._original_should_stop = getattr(agent_loop_instance, 'should_stop', None)

    def enhanced_build_prompt(self, working_memory: list[dict], **kwargs) -> str:
        """
        增强的提示词构建

        在构建提示词前，先获取意识决策并注入工作记忆
        """
        # 1. 获取当前上下文
        execution_history = kwargs.get('execution_history', [])
        current_round = kwargs.get('current_round', 0)
        user_instruction = kwargs.get('user_instruction', '')

        # 2. 生成意识决策
        decision = self.decision_engine.make_decision(
            user_instruction=user_instruction,
            execution_history=execution_history,
            current_round=current_round,
            working_memory=working_memory,
            context=kwargs.get('context', {})
        )

        # 3. 根据决策类型决定注入方式
        if decision.decision_type in [DecisionType.OVERRIDE, DecisionType.DIRECTIVE]:
            # 高影响决策：插入到工作记忆最前面
            enhanced_memory = self.decision_engine.memory_injector.inject_to_working_memory(
                working_memory, decision, insertion_position="head"
            )
        else:
            # 低影响决策：插入到用户消息之前
            enhanced_memory = self.decision_engine.memory_injector.inject_to_working_memory(
                working_memory, decision, insertion_position="before_user"
            )

        # 4. 如果有建议工具，调整可用工具列表
        if decision.suggested_tool:
            available_tools = kwargs.get('available_tools', [])
            ranked_tools = self.decision_engine.tool_ranker.rank_tools(
                available_tools, decision, execution_history
            )
            kwargs['available_tools'] = ranked_tools

        # 5. 调用原方法构建提示词
        return self._original_build_prompt(enhanced_memory, **kwargs)

    def enhanced_parse_response(self, response: str, **kwargs) -> dict:
        """
        增强的响应解析

        在解析后，根据意识决策进行干预
        """
        # 1. 调用原方法解析
        parsed = self._original_parse_response(response, **kwargs)

        # 2. 获取当前意识决策（从kwargs或重新生成）
        consciousness_decision = kwargs.get('consciousness_decision')

        # 3. 拦截并修改解析结果
        modified = self.decision_engine.intent_interceptor.intercept_parsed_intent(
            parsed, consciousness_decision
        )

        return modified

    def enhanced_should_stop(self, **kwargs) -> tuple[bool, str]:
        """
        增强的停止判断

        让意识系统参与Stop/Continue决策
        """
        # 获取AI的停止建议
        ai_response = kwargs.get('ai_response', {})

        # 获取意识决策
        consciousness_decision = kwargs.get('consciousness_decision')

        # 让循环控制器做决定
        should_stop, reason = self.decision_engine.loop_controller.should_stop(
            consciousness_decision=consciousness_decision,
            ai_response=ai_response,
            execution_history=kwargs.get('execution_history', []),
            max_rounds=kwargs.get('max_rounds', 10)
        )

        return should_stop, reason


def integrate_consciousness_to_agent_loop(agent_loop_instance, consciousness_manager):
    """
    将意识系统集成到现有Agent Loop的快捷函数

    使用示例：
        from core.agent.agent_loop import AgentLoop
        from core.Consciousness import get_consciousness_manager
        from core.consciousness.consciousness_integration import integrate_consciousness_to_agent_loop

        agent_loop = AgentLoop()
        consciousness = get_consciousness_manager()

        # 集成意识系统
        integrate_consciousness_to_agent_loop(agent_loop, consciousness)
    """
    enhancer = ConsciousnessEnabledAgentLoop(agent_loop_instance, consciousness_manager)

    # 替换方法
    agent_loop_instance.build_prompt = enhancer.enhanced_build_prompt
    agent_loop_instance.parse_response = enhancer.enhanced_parse_response
    agent_loop_instance.should_stop = enhancer.enhanced_should_stop

    # 保存原始方法供调试
    agent_loop_instance._original_methods = {
        'build_prompt': enhancer._original_build_prompt,
        'parse_response': enhancer._original_parse_response,
        'should_stop': enhancer._original_should_stop
    }

    # 添加获取决策统计的方法
    agent_loop_instance.get_consciousness_stats = enhancer.decision_engine.get_stats

    logger.info("[ConsciousnessIntegration] 意识系统已成功集成到Agent Loop")

    return agent_loop_instance
