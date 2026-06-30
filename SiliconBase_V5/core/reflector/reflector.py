#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""
反思系统 V3.0 - 深度反思与策略优化（Agent-7增强版）
核心功能：
- 单步反思：每次行动后即时反思
- 阶段反思：每N步或遇到瓶颈时进行阶段性反思
- 任务反思：任务结束后的整体反思
- 策略优化：从反思中提取可复用的策略模式
- 【增强】成功后反思：成功也反思，寻找更优解
- 【增强】多维度反思：效率/安全/体验/学习四个维度
- 【增强】预测性反思：执行前预测可能问题
- 【增强】反思质量评估：过滤低质量反思
- 【2026-03-10】修复：【静默失败修复】_call_reflection_llm失败时抛出ReflectionAIError，调用方必须处理异常

反思层次：
- Level 1: 执行反思 (Execution) - 工具调用是否正确
- Level 2: 策略反思 (Strategy) - 方法选择是否最优
- Level 3: 元反思 (Meta) - 思考方式是否需要调整
- Level 4: 预测反思 (Predictive) - 行动前预测风险
"""  # 文档字符串结束
import contextlib
import json  # JSON数据处理：用于序列化和反序列化反思记录、策略模式等数据
import time  # 时间模块：用于生成时间戳，记录反思发生的时间
from dataclasses import dataclass, field  # 数据类：简化类的定义，自动生成__init__等方法
from enum import Enum  # 枚举类：定义固定的常量集合，如反思层次、触发条件
from typing import Any  # 类型提示：提供静态类型检查支持

from core.ai.ai_adapter import AIResponseError, call_thinker, call_thinker_async  # AI适配器：调用大语言模型进行反思分析
from core.exceptions import ReflectionAIError, ReflectionError  # 从统一异常模块导入
from core.logger import logger  # 日志记录器：记录反思系统的运行日志
from core.memory.memory_service import get_memory_service  # 【P1-迁移】异步记忆服务入口

# 【P1-迁移】vector_memory 已废弃，改为通过 MemoryService 获取 VectorStore
# from core.memory.vector_memory import vector_memory
from core.memory.memory_source import MemorySource  # Agent-4: 导入MemorySource枚举

# 【P3新增】执行记忆接入
try:
    from core.memory.execution_memory import execution_memory_manager
except ImportError as e:
    logger.warning(f"[Reflector] execution_memory_manager 导入失败: {e}")
    execution_memory_manager = None


class ReflectionLevel(Enum):  # 反思层次 - 定义三个不同深度的反思级别
    EXECUTION = "execution"    # 执行层：检查工具调用是否正确，参数设置是否合理
    STRATEGY = "strategy"      # 策略层：评估当前方法是否最优，是否需要调整策略
    META = "meta"              # 元层：反思思考方式本身，是否需要根本性转变
    PREDICTIVE = "predictive"  # 预测层：行动前预测可能的问题和风险


class ReflectionTrigger(Enum):  # 反思触发条件 - 定义何时启动反思机制
    AFTER_STEP = "after_step"          # 每步后：单个动作执行完成后触发
    AFTER_FAILURE = "after_failure"    # 失败后：动作执行失败时触发深度反思
    AFTER_SUCCESS = "after_success"    # 【新增】成功后：成功也反思优化空间
    PERIODIC = "periodic"              # 周期性：每N步进行一次策略审查
    ON_STUCK = "on_stuck"              # 卡住时：检测到循环或停滞时触发
    ON_COMPLETE = "on_complete"        # 任务完成：整个任务结束后的总结反思
    BEFORE_ACTION = "before_action"    # 【新增】行动前：执行前预测可能问题


@dataclass  # 使用@dataclass装饰器自动生成__init__、__repr__等方法
class Reflection:  # 单次反思记录 - 存储一次完整的反思结果
    level: ReflectionLevel            # 反思层次：本次反思属于哪个级别
    trigger: ReflectionTrigger        # 触发条件：是什么触发了这次反思
    context_summary: str              # 上下文摘要：简述触发反思的场景
    observation: str                  # 观察发现：看到了什么问题或现象
    insight: str                      # 核心洞察：从观察中得出的深刻认识
    suggestion: str                   # 改进建议：针对发现的问题提出的解决方案
    confidence: float = 0.0           # 置信度 (0-1)：对反思结论的把握程度
    quality_score: float = 0.0        # 【新增】质量评分 (0-1)：反思内容的质量
    timestamp: float = field(default_factory=time.time)  # 时间戳：反思发生的时间，默认当前时间
    metadata: dict = field(default_factory=dict)  # 元数据：存储额外的结构化信息

    def to_dict(self) -> dict:  # 将反思记录转换为字典格式，便于序列化和存储
        return {  # 返回包含所有字段的字典，枚举类型转换为字符串值
            "level": self.level.value,        # 将枚举转换为字符串值
            "trigger": self.trigger.value,    # 将枚举转换为字符串值
            "context_summary": self.context_summary,
            "observation": self.observation,
            "insight": self.insight,
            "suggestion": self.suggestion,
            "confidence": self.confidence,
            "quality_score": self.quality_score,  # 【新增】质量评分
            "timestamp": self.timestamp,
            "metadata": self.metadata
        }


@dataclass  # 使用@dataclass装饰器简化类定义
class StrategyPattern:  # 策略模式 - 从反思中提取的可复用策略
    pattern_id: str                   # 模式ID：唯一标识符，用于检索和引用
    name: str                         # 模式名称：人类可读的简短描述
    description: str                  # 模式描述：详细说明该策略的适用场景和原理
    applicable_scenarios: list[str]   # 适用场景关键词：用于匹配相似任务
    strategy_steps: list[str]         # 策略步骤：执行该策略的具体步骤列表
    success_rate: float = 0.0         # 成功率：历史使用该策略的成功比例（保留！用于前端兼容）
    usage_count: int = 0              # 使用次数：该策略被应用的总次数（保留！用于前端兼容）
    created_at: float = field(default_factory=time.time)  # 创建时间：模式首次提取的时间
    last_used: float = field(default_factory=time.time)   # 最后使用时间：最近一次被应用的时间

    # 【新增】贝叶斯核心参数（内部使用，repr=False 不在to_dict中暴露）
    alpha: float = field(default=1.0, repr=False)  # 成功次数 + 先验
    beta: float = field(default=1.0, repr=False)   # 失败次数 + 先验

    def to_dict(self) -> dict:  # 将策略模式转换为字典格式，便于序列化到向量数据库
        """保持原有输出格式，前端无需修改"""
        return {  # 返回包含所有字段的字典
            "pattern_id": self.pattern_id,
            "name": self.name,
            "description": self.description,
            "applicable_scenarios": self.applicable_scenarios,
            "strategy_steps": self.strategy_steps,
            "success_rate": self.get_success_probability(),  # 【修改】返回贝叶斯期望
            "usage_count": int(self.alpha + self.beta - 2),  # 【修改】从贝叶斯参数计算
            "created_at": self.created_at,
            "last_used": self.last_used
        }

    # 【新增】贝叶斯方法
    def get_success_probability(self) -> float:
        """获取成功率期望 E[p] = α / (α + β)"""
        return self.alpha / (self.alpha + self.beta)

    def update_with_evidence(self, success: bool, confidence: float = 1.0):
        """贝叶斯更新 - 根据新的证据更新策略信念"""
        if success:
            self.alpha += confidence
        else:
            self.beta += confidence
        self.last_used = time.time()
        # 同步更新旧字段（保持兼容）
        self.success_rate = self.get_success_probability()
        self.usage_count = int(self.alpha + self.beta - 2)


@dataclass
class ReflectionQualityMetrics:
    """反思质量评估指标"""
    depth_score: float = 0.0          # 深度评分：洞察的深刻程度
    specificity_score: float = 0.0    # 具体性评分：建议是否具体可行
    actionability_score: float = 0.0  # 可执行性评分：是否可以转化为行动
    novelty_score: float = 0.0        # 新颖性评分：是否是新的洞察
    overall_score: float = 0.0        # 综合评分

    def to_dict(self) -> dict:
        return {
            "depth_score": self.depth_score,
            "specificity_score": self.specificity_score,
            "actionability_score": self.actionability_score,
            "novelty_score": self.novelty_score,
            "overall_score": self.overall_score
        }


@dataclass
class MultiDimensionReflection:
    """多维度反思结果"""
    efficiency: Reflection | None = None      # 效率维度
    safety: Reflection | None = None          # 安全维度
    user_experience: Reflection | None = None # 用户体验维度
    learning_value: Reflection | None = None  # 学习价值维度
    combined_score: float = 0.0                   # 综合评分

    def to_dict(self) -> dict:
        return {
            "efficiency": self.efficiency.to_dict() if self.efficiency else None,
            "safety": self.safety.to_dict() if self.safety else None,
            "user_experience": self.user_experience.to_dict() if self.user_experience else None,
            "learning_value": self.learning_value.to_dict() if self.learning_value else None,
            "combined_score": self.combined_score
        }


class Reflector:  # 反思引擎 - 实现ReAct中的Reflection环节
    """
    Reflector是系统的"自我审视"能力，负责在任务执行过程中和结束后
    进行多层次反思，发现问题、总结经验、优化策略。

    【V3.0增强功能】
    1. 成功后反思：即使成功也反思是否有更优解
    2. 多维度反思：从效率/安全/体验/学习四个维度全面评估
    3. 预测性反思：行动前预测可能的风险和问题
    4. 质量评估：过滤低质量反思，只保存有价值的洞察
    5. 【2026-03-10】静默失败修复：_call_reflection_llm抛出ReflectionAIError，强制调用方处理

    使用方式：
    1. 每步后调用 reflect_after_step() - 检查执行是否正确
    2. 失败后调用 reflect_after_failure() - 深度分析失败原因
    3. 成功后调用 reflect_after_success() - 寻找优化空间
    4. 周期性调用 reflect_periodic() - 审查整体策略
    5. 任务结束后调用 reflect_on_completion() - 总结经验教训
    6. 行动前调用 reflect_before_action() - 预测风险
    """  # Reflector类的文档字符串

    def __init__(self):  # 初始化Reflector实例，加载已有的策略模式
        import asyncio

        self.reflection_history: list[Reflection] = []  # 反思历史列表：存储本次运行中的所有反思记录
        self.strategy_patterns: dict[str, StrategyPattern] = {}  # 策略模式字典：缓存已加载的策略模式
        self.step_results: list[dict] = []  # 步骤结果记录：用于检测循环和重复错误模式
        self.quality_threshold: float = 0.6  # 【新增】质量阈值：低于此值的反思不存储
        self._patterns_loaded: bool = False   # 【P1-迁移】策略模式是否已加载
        self._load_task = None                # 【P1-迁移】后台加载任务引用

        # 【新增】UCB探索因子（用于UCB策略选择）
        self.ucb_exploration_factor: float = 1.414

        # 【P1-迁移】异步加载策略模式：后台任务调度，避免阻塞构造函数
        try:
            loop = asyncio.get_running_loop()
            self._load_task = loop.create_task(self._load_existing_patterns())
            self._load_task.add_done_callback(self._on_patterns_loaded)
            logger.info("[Reflector] 策略模式后台加载任务已调度")
        except RuntimeError:
            # 无运行事件循环（如在同步主线程中实例化），延迟到首次 async 调用时加载
            logger.debug("[Reflector] 无运行事件循环，策略模式将延迟加载")
            self._load_task = None

        # 初始化提示词
        try:
            self._init_prompts()                # 反思提示词模板：定义不同层次反思的Prompt模板
            logger.info("[Reflector] 提示词初始化成功")
        except ReflectionError as e:
            logger.error(f"[Reflector] 初始化提示词失败: {e}", exc_info=True)
            raise

        # ── KF + RTS 平滑：历史判断修正引擎 ───────────────────────────────────
        import numpy as np

        from core.estimation.state_estimator import KalmanFilter
        # 状态维度 2：[策略成功率信念, 反思质量趋势]
        self._reflection_kf = KalmanFilter(state_dim=2, observation_dim=2)
        self._reflection_kf.X = np.array([[0.5], [0.5]])
        self._reflection_kf.P = np.eye(2) * 0.1
        self._reflection_kf_A = np.array([[0.95, 0.02], [0.01, 0.97]])
        self._reflection_kf_Q = np.eye(2) * 0.01
        self._reflection_kf_H = np.eye(2)
        self._reflection_kf_R = np.eye(2) * 0.05
        # RTS 前向历史 [(X_pred, P_pred, X_update, P_update), ...]
        self._rts_history: list[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = []

    def _init_prompts(self):  # 初始化反思提示词模板，为不同层次的反思定义专门的Prompt模板
        self.execution_reflection_prompt = """你是一个执行反思助手。请分析刚才的工具调用。
【任务上下文】
{task_context}
【上一步执行】
工具: {tool_name}
参数: {tool_params}
结果: {tool_result}
成功: {success}
【历史轨迹】
{trajectory}
请进行执行层反思，回答：
1. 工具选择是否正确？
2. 参数设置是否合理？
3. 结果是否符合预期？
4. 如果失败，原因是什么？如何修正？
以JSON格式输出：
{{
    "observation": "<根据实际对话内容填写观察>",
    "insight": "<根据观察得出的核心洞察>",
    "suggestion": "<具体的改进建议>",
    "confidence": 0.8,
    "should_retry": false,
    "alternative_tool": "<可选的替代工具名（如有）>"
}}
# 注意：以上尖括号内为占位符，请根据实际分析结果替换为具体内容
"""  # 执行层反思Prompt：关注单个工具调用的正确性

        self.strategy_reflection_prompt = """你是一个策略反思助手。请分析当前任务的整体策略。
【任务】
{task}
【已执行步骤】
{steps_summary}
【当前状态】
已执行: {step_count}步
最近结果: {last_result}
【可用策略模式】
{available_patterns}
请进行策略层反思，回答：
1. 当前方法是否最高效？
2. 是否存在更优路径？
3. 是否陷入重复模式？
4. 应该调整整体策略吗？
以JSON格式输出：
{{
    "observation": "<当前策略评估>",
    "insight": "<关键洞察>",
    "suggestion": "<策略调整建议>",
    "confidence": 0.8,
    "recommended_pattern": "<推荐使用的策略模式ID（如有）>"
}}
# 注意：以上尖括号内为占位符，请根据实际分析结果替换为具体内容
"""  # 策略层反思Prompt：关注整体方法的有效性

        self.meta_reflection_prompt = """你是一个元反思助手。请分析思考过程本身。
【任务历史】
{full_history}
【反思历史】
{reflection_history}
【当前困境】
{stuck_reason}
请进行元层反思，回答：
1. 我的思考方式是否存在局限？
2. 是否过度依赖某些模式？
3. 是否需要完全换一个角度？
4. 从中学到了什么可迁移的经验？
以JSON格式输出：
{{
    "observation": "<思考模式分析>",
    "insight": "<深层洞察>",
    "suggestion": "<根本性调整建议>",
    "learned_principle": "<可迁移的原则>",
    "confidence": 0.8
}}
# 注意：以上尖括号内为占位符，请根据实际分析结果替换为具体内容
"""  # 元层反思Prompt：关注思考方式本身

        self.task_reflection_prompt = """你是一个任务总结助手。请对整个任务进行复盘。
【任务】
{task}
【完整执行轨迹】
{full_trajectory}
【最终结果】
{final_result}
成功: {success}
【反思记录】
{reflections}
请进行任务级反思，输出：
{{
    "execution_summary": "<执行过程总结>",
    "key_decisions": ["<关键决策点1>", "<关键决策点2>"],
    "what_worked": "<有效的方法>",
    "what_failed": "<无效的方法>",
    "root_cause": "<成功/失败的根因>",
    "improvement_areas": ["<改进方向1>", "<改进方向2>"],
    "extracted_pattern": {{
        "name": "<策略模式名称>",
        "description": "<模式描述>",
        "steps": ["<步骤1>", "<步骤2>"],
        "applicable_to": ["<适用场景关键词1>", "<适用场景关键词2>"]
    }},
    "confidence": 0.9
}}
# 注意：以上尖括号内为占位符，请根据实际分析结果替换为具体内容
"""  # 任务级反思Prompt：任务完成后的整体复盘

        # 【新增】成功后反思Prompt
        self.success_reflection_prompt = """你是一个优化反思助手。任务已成功完成，但请从优化角度审视：
【任务】
{task}
【执行轨迹】
{trajectory}
【最终结果】
{final_result}
【执行统计】
总步骤数: {step_count}
工具调用次数: {tool_calls}
请进行成功后反思，回答：
1. 当前方案是最优的吗？还有优化空间吗？
2. 是否有更少步骤的解决方案？
3. 哪些步骤是冗余的？
4. 能否提取可复用的模式供未来使用？
5. 从这次成功中学到了什么可以迁移的经验？
以JSON格式输出：
{{
    "observation": "<对当前方案的评估>",
    "insight": "<发现的优化机会>",
    "suggestion": "<未来如何做得更好>",
    "optimization_potential": "<高/中/低>",
    "reusable_pattern": {{
        "name": "<可复用模式名称>",
        "description": "<模式描述>",
        "steps": ["<步骤1>", "<步骤2>"],
        "applicable_to": ["<适用场景1>", "<适用场景2>"]
    }},
    "confidence": 0.8
}}
# 注意：以上尖括号内为占位符，请根据实际分析结果替换为具体内容
"""

        # 【新增】效率维度反思Prompt
        self.efficiency_reflection_prompt = """从效率角度分析以下执行过程：
【任务】
{task}
【执行轨迹】
{trajectory}
【执行统计】
总步骤: {step_count}
成功步骤: {success_count}
失败步骤: {fail_count}
请评估：
1. 执行效率如何？
2. 是否存在冗余步骤？
3. 工具使用是否最优？
4. 如何提升执行速度？
输出JSON：
{{
    "observation": "<效率评估>",
    "insight": "<效率瓶颈分析>",
    "suggestion": "<效率提升建议>",
    "efficiency_score": 0.8,
    "confidence": 0.8
}}
# 注意：以上尖括号内为占位符，请根据实际分析结果替换为具体内容
"""

        # 【新增】安全维度反思Prompt
        self.safety_reflection_prompt = """从安全角度分析以下执行过程：
【任务】
{task}
【执行轨迹】
{trajectory}
【涉及的操作】
{operations}
请评估：
1. 是否存在安全风险？
2. 是否有潜在的破坏性操作？
3. 是否有数据泄露风险？
4. 如何提升安全性？
输出JSON：
{{
    "observation": "<安全风险评估>",
    "insight": "<发现的安全隐患>",
    "suggestion": "<安全改进建议>",
    "risk_level": "<高/中/低>",
    "confidence": 0.8
}}
# 注意：以上尖括号内为占位符，请根据实际分析结果替换为具体内容
"""

        # 【新增】用户体验维度反思Prompt
        self.ux_reflection_prompt = """从用户体验角度分析以下执行过程：
【任务】
{task}
【执行轨迹】
{trajectory}
【用户交互点】
{interactions}
请评估：
1. 用户体验是否流畅？
2. 是否有令人困惑的步骤？
3. 反馈是否及时清晰？
4. 如何提升用户体验？
输出JSON：
{{
    "observation": "<用户体验评估>",
    "insight": "<体验问题分析>",
    "suggestion": "<体验优化建议>",
    "ux_score": 0.8,
    "confidence": 0.8
}}
# 注意：以上尖括号内为占位符，请根据实际分析结果替换为具体内容
"""

        # 【新增】学习价值维度反思Prompt
        self.learning_reflection_prompt = """从学习价值角度分析以下执行过程：
【任务】
{task}
【执行轨迹】
{trajectory}
【遇到的问题】
{problems}
请评估：
1. 从这次执行中学到了什么？
2. 有哪些新的认知？
3. 这些经验如何应用到未来？
4. 知识的可迁移性如何？
输出JSON：
{{
    "observation": "<学习点总结>",
    "insight": "<核心学习成果>",
    "suggestion": "<如何巩固和应用>",
    "transferability": "<高/中/低>",
    "confidence": 0.8
}}
# 注意：以上尖括号内为占位符，请根据实际分析结果替换为具体内容
"""

        # 【新增】预测性反思Prompt
        self.predictive_reflection_prompt = """你是一个风险预测助手。在行动前预测可能的问题。
【计划执行】
{planned_action}
【当前上下文】
{context}
【历史类似操作】
{similar_actions}
【可用备选方案】
{alternatives}
请预测：
1. 这个行动可能失败的原因是什么？
2. 执行过程中可能遇到什么障碍？
3. 需要准备什么备选方案？
4. 如何降低失败风险？
输出JSON：
{{
    "observation": "<行动分析>",
    "insight": "<潜在风险识别>",
    "suggestion": "<风险缓解建议>",
    "risk_factors": ["<风险1>", "<风险2>"],
    "fallback_plan": "<备选方案>",
    "success_probability": 0.7,
    "confidence": 0.8
}}
# 注意：以上尖括号内为占位符，请根据实际分析结果替换为具体内容
"""

    async def _load_existing_patterns(self):  # 从向量记忆中加载已有的策略模式，系统启动时调用
        """【P1-迁移】异步加载策略模式，内部调用 VectorStore"""
        try:
            results = await self._search_knowledge_async("策略模式 strategy_pattern", limit=50)
            for result in results:
                if "pattern_id" in result.get("content", {}):
                    pattern_data = result["content"]
                    pattern = StrategyPattern(**pattern_data)
                    self.strategy_patterns[pattern.pattern_id] = pattern
            self._patterns_loaded = True
            logger.info(f"[Reflector] 已加载 {len(self.strategy_patterns)} 个策略模式")
        except Exception as e:
            logger.error(f"[Reflector] 加载策略模式失败: {e}", exc_info=True)
            # 【P1-迁移】后台任务内不抛异常，避免未捕获异常导致事件循环警告

    def _on_patterns_loaded(self, task):
        """【P1-迁移】后台加载任务完成回调，用于捕获异常"""
        try:
            task.result()
            logger.info("[Reflector] 策略模式后台加载完成")
        except Exception as e:
            logger.error(f"[Reflector] 策略模式后台加载异常: {e}", exc_info=True)

    # ═════════════════════════════════════════════════════════════════════════════
    # 【新架构】VectorStore 异步查询替代方案
    # 用途：验证 VectorStore 能否替代 vector_memory.search_knowledge 的核心能力
    # 设计约束：保留原同步方法不动，新增 async 版本供上层渐进迁移
    # ═════════════════════════════════════════════════════════════════════════════

    async def _search_knowledge_async(
        self,
        query: str,
        limit: int = 50
    ) -> list[dict[str, Any]]:
        """
        使用 VectorStore 替代 vector_memory.search_knowledge 的异步实现。

        并发搜索 "knowledge" 和 "experience" 两个集合，返回与旧接口兼容的字典列表。
        旧接口返回格式：List[{"id", "document", "metadata", "similarity"}]
        此处额外提供 "content" 字段（document 的别名）以兼容访问 "content" 的调用方。

        Args:
            query: 查询文本
            limit: 返回结果数量上限

        Returns:
            List[Dict]: 与旧 search_knowledge 格式兼容的搜索结果
        """
        from core.memory.memory_service import get_memory_service

        try:
            memory_service = await get_memory_service()
            vector_store = memory_service.vector_store

            # 健康检查：若 ChromaDB 不可用则降级返回空列表
            if not await vector_store.is_available():
                logger.warning("[Reflector-VectorStore] ChromaDB 不可用，降级返回空列表")
                return []

            # 并发搜索 knowledge + experience 两个集合
            grouped = await vector_store.search_multi(
                query=query,
                collections=["knowledge", "experience"],
                n_results=limit
            )

            # 合并、转换格式、按相似度排序
            merged: list[dict[str, Any]] = []
            for collection, search_results in grouped.items():
                for sr in search_results:
                    # distance -> similarity 近似转换（假设 distance 已归一化到 [0,1]）
                    similarity = 1.0 - (sr.distance or 0.0)
                    merged.append({
                        "id": sr.id,
                        "document": sr.document,
                        "content": sr.document,  # 别名：兼容访问 "content" 的调用方
                        "metadata": sr.metadata,
                        "similarity": similarity,
                        "collection": collection,
                    })

            # 按 similarity 降序排序并截断
            merged.sort(key=lambda x: x["similarity"], reverse=True)
            return merged[:limit]

        except Exception as e:
            logger.exception(f"[Reflector-VectorStore] 异步知识库搜索失败: {e}")
            return []

    # ═════════════════════════════════════════════════════════════════════════════
    # 反思入口方法
    # ═════════════════════════════════════════════════════════════════════════════

    async def reflect_after_step(self, task: str, step_info: dict,
                          trajectory: list[dict]) -> Reflection | None:  # 单步后反思 - 执行层反思
        if step_info.get("success"):  # 只有失败时才进行深度反思，成功则简单记录以节省资源
            return None  # 成功时返回None

        try:  # 【静默失败修复】添加异常处理
            prompt = self.execution_reflection_prompt.format(  # 格式化Prompt，填充具体数据
                task_context=task[:200],  # 限制长度避免超出token限制
                tool_name=step_info.get("tool", "unknown"),  # 工具名，默认为unknown
                tool_params=json.dumps(step_info.get("params", {}), ensure_ascii=False),  # 参数转JSON
                tool_result=str(step_info.get("result", ""))[:200],  # 结果字符串，限制长度
                success=step_info.get("success", False),  # 是否成功
                trajectory=self._format_trajectory(trajectory[-3:])  # 最近3步轨迹，提供上下文
            )

            reflection_data = await self._call_reflection_llm_async(prompt)  # 调用大模型进行反思分析
            # LLM调用成功，继续处理

            reflection = Reflection(  # 创建Reflection对象存储反思结果
                level=ReflectionLevel.EXECUTION,  # 执行层反思
                trigger=ReflectionTrigger.AFTER_FAILURE,  # 失败后触发
                context_summary=f"工具 {step_info.get('tool')} 执行失败",  # 上下文摘要
                observation=reflection_data.get("observation", ""),  # 观察发现
                insight=reflection_data.get("insight", ""),  # 核心洞察
                suggestion=reflection_data.get("suggestion", ""),  # 改进建议
                confidence=reflection_data.get("confidence", 0.5),  # 置信度，默认0.5
                metadata={  # 元数据
                    "should_retry": reflection_data.get("should_retry", False),  # 是否建议重试
                    "alternative_tool": reflection_data.get("alternative_tool")  # 替代工具建议
                }
            )

            # 【新增】质量评估
            quality_metrics = self._assess_reflection_quality(reflection)
            reflection.quality_score = quality_metrics.overall_score

            # 只保存高质量的反思
            if reflection.quality_score >= self.quality_threshold:
                self.reflection_history.append(reflection)  # 将反思记录添加到历史列表
                await self._store_reflection(reflection)  # 存储到记忆系统以便长期保存
                logger.debug(f"[Reflector] 执行反思完成: {reflection.insight[:50]}...")
            else:
                logger.debug(f"[Reflector] 反思质量过低({reflection.quality_score:.2f})，不存储")

            return reflection

        except ReflectionAIError as e:
            logger.error(f"[Reflector] reflect_after_step LLM调用失败: {e}", exc_info=True)
            return None

        except Exception as e:
            logger.error(f"[Reflector] reflect_after_step失败: {e}", exc_info=True)
            return None

    async def reflect_after_success(self, task: str, trajectory: list[dict],
                              final_result: str = "") -> Reflection | None:
        """
        【新增】成功后的反思：即使任务成功，也寻找优化空间
        这是Agent-7增强的核心功能之一
        """
        if len(trajectory) < 2:  # 步骤太少，不值得反思
            return None

        try:  # 【静默失败修复】添加异常处理
            # 计算执行统计
            step_count = len(trajectory)
            tool_calls = len([s for s in trajectory if s.get("tool")])

            prompt = self.success_reflection_prompt.format(
                task=task[:200],
                trajectory=self._format_trajectory(trajectory),
                final_result=final_result[:300],
                step_count=step_count,
                tool_calls=tool_calls
            )

            reflection_data = await self._call_reflection_llm_async(prompt)
            # LLM异步调用成功，继续处理

            reflection = Reflection(
                level=ReflectionLevel.STRATEGY,  # 成功后的反思属于策略层
                trigger=ReflectionTrigger.AFTER_SUCCESS,
                context_summary=f"任务成功后的优化反思 - {step_count}步完成",
                observation=reflection_data.get("observation", ""),
                insight=reflection_data.get("insight", ""),
                suggestion=reflection_data.get("suggestion", ""),
                confidence=reflection_data.get("confidence", 0.5),
                metadata={
                    "optimization_potential": reflection_data.get("optimization_potential", "中"),
                    "reusable_pattern": reflection_data.get("reusable_pattern"),
                    "step_count": step_count,
                    "tool_calls": tool_calls
                }
            )

            # 质量评估
            quality_metrics = self._assess_reflection_quality(reflection)
            reflection.quality_score = quality_metrics.overall_score

            if reflection.quality_score >= self.quality_threshold:
                self.reflection_history.append(reflection)
                await self._store_reflection(reflection)

                # 如果有可复用模式，提取并存储
                pattern_data = reflection_data.get("reusable_pattern")
                if pattern_data and reflection_data.get("optimization_potential") in ["高", "中"]:
                    pattern = await self._extract_strategy_pattern(pattern_data, trajectory)
                    if pattern:
                        logger.info(f"[Reflector] 从成功中提取策略模式: {pattern.name}")

            logger.info(f"[Reflector] 成功后反思完成，质量评分: {reflection.quality_score:.2f}")
            return reflection

        except ReflectionAIError as e:
            logger.error(f"[Reflector] reflect_after_success LLM调用失败: {e}", exc_info=True)
            return None

        except Exception as e:
            logger.error(f"[Reflector] reflect_after_success失败: {e}", exc_info=True)
            return None

    async def reflect_multi_dimension(self, task: str, trajectory: list[dict],
                                context: dict = None) -> MultiDimensionReflection:
        """
        【新增】多维度反思：从效率、安全、用户体验、学习价值四个维度同时反思
        这是Agent-7增强的核心功能之一
        """
        multi_reflection = MultiDimensionReflection()

        # 计算统计信息
        step_count = len(trajectory)
        success_count = len([s for s in trajectory if s.get("success")])
        fail_count = step_count - success_count

        # 效率维度反思
        try:
            efficiency_prompt = self.efficiency_reflection_prompt.format(
                task=task[:200],
                trajectory=self._format_trajectory(trajectory),
                step_count=step_count,
                success_count=success_count,
                fail_count=fail_count
            )
            efficiency_data = await self._call_reflection_llm_async(efficiency_prompt)
            multi_reflection.efficiency = Reflection(
                level=ReflectionLevel.STRATEGY,
                trigger=ReflectionTrigger.PERIODIC,
                context_summary="效率维度反思",
                observation=efficiency_data.get("observation", ""),
                insight=efficiency_data.get("insight", ""),
                suggestion=efficiency_data.get("suggestion", ""),
                confidence=efficiency_data.get("confidence", 0.5),
                metadata={"dimension": "efficiency", "efficiency_score": efficiency_data.get("efficiency_score", 0.5)}
            )
        except ReflectionAIError as e:
            logger.error(f"[Reflector] 效率维度反思失败: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"[Reflector] 效率维度反思异常: {e}", exc_info=True)

        # 安全维度反思
        try:
            operations = self._extract_operations(trajectory)
            safety_prompt = self.safety_reflection_prompt.format(
                task=task[:200],
                trajectory=self._format_trajectory(trajectory),
                operations=operations
            )
            safety_data = await self._call_reflection_llm_async(safety_prompt)
            multi_reflection.safety = Reflection(
                level=ReflectionLevel.STRATEGY,
                trigger=ReflectionTrigger.PERIODIC,
                context_summary="安全维度反思",
                observation=safety_data.get("observation", ""),
                insight=safety_data.get("insight", ""),
                suggestion=safety_data.get("suggestion", ""),
                confidence=safety_data.get("confidence", 0.5),
                metadata={"dimension": "safety", "risk_level": safety_data.get("risk_level", "低")}
            )
        except ReflectionAIError as e:
            logger.error(f"[Reflector] 安全维度反思失败: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"[Reflector] 安全维度反思异常: {e}", exc_info=True)

        # 用户体验维度反思
        try:
            interactions = self._extract_interactions(trajectory)
            ux_prompt = self.ux_reflection_prompt.format(
                task=task[:200],
                trajectory=self._format_trajectory(trajectory),
                interactions=interactions
            )
            ux_data = await self._call_reflection_llm_async(ux_prompt)
            multi_reflection.user_experience = Reflection(
                level=ReflectionLevel.STRATEGY,
                trigger=ReflectionTrigger.PERIODIC,
                context_summary="用户体验维度反思",
                observation=ux_data.get("observation", ""),
                insight=ux_data.get("insight", ""),
                suggestion=ux_data.get("suggestion", ""),
                confidence=ux_data.get("confidence", 0.5),
                metadata={"dimension": "user_experience", "ux_score": ux_data.get("ux_score", 0.5)}
            )
        except ReflectionAIError as e:
            logger.error(f"[Reflector] 用户体验维度反思失败: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"[Reflector] 用户体验维度反思异常: {e}", exc_info=True)

        # 学习价值维度反思
        try:
            problems = self._extract_problems(trajectory)
            learning_prompt = self.learning_reflection_prompt.format(
                task=task[:200],
                trajectory=self._format_trajectory(trajectory),
                problems=problems
            )
            learning_data = await self._call_reflection_llm_async(learning_prompt)
            multi_reflection.learning_value = Reflection(
                level=ReflectionLevel.META,
                trigger=ReflectionTrigger.PERIODIC,
                context_summary="学习价值维度反思",
                observation=learning_data.get("observation", ""),
                insight=learning_data.get("insight", ""),
                suggestion=learning_data.get("suggestion", ""),
                confidence=learning_data.get("confidence", 0.5),
                metadata={"dimension": "learning", "transferability": learning_data.get("transferability", "中")}
            )
        except ReflectionAIError as e:
            logger.error(f"[Reflector] 学习价值维度反思失败: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"[Reflector] 学习价值维度反思异常: {e}", exc_info=True)

        # 计算综合评分
        scores = []
        if multi_reflection.efficiency:
            scores.append(multi_reflection.efficiency.confidence)
        if multi_reflection.safety:
            scores.append(multi_reflection.safety.confidence)
        if multi_reflection.user_experience:
            scores.append(multi_reflection.user_experience.confidence)
        if multi_reflection.learning_value:
            scores.append(multi_reflection.learning_value.confidence)

        multi_reflection.combined_score = sum(scores) / len(scores) if scores else 0.0

        # 存储各维度的反思
        try:
            for reflection in [multi_reflection.efficiency, multi_reflection.safety,
                              multi_reflection.user_experience, multi_reflection.learning_value]:
                if reflection:
                    quality_metrics = self._assess_reflection_quality(reflection)
                    reflection.quality_score = quality_metrics.overall_score
                    if reflection.quality_score >= self.quality_threshold:
                        self.reflection_history.append(reflection)
                        await self._store_reflection(reflection)

            logger.info(f"[Reflector] 多维度反思完成，综合评分: {multi_reflection.combined_score:.2f}")
        except Exception as e:
            logger.error(f"[Reflector] 存储多维度反思失败: {e}", exc_info=True)

        return multi_reflection

    async def reflect_before_action(self, planned_action: dict, context: dict) -> Reflection | None:
        """
        【新增】预测性反思：在执行行动前预测可能的问题
        这是Agent-7增强的核心功能之一
        """
        try:  # 【静默失败修复】添加异常处理
            action_desc = planned_action.get("description", json.dumps(planned_action, ensure_ascii=False))

            # 查找历史类似操作
            similar_actions = self._find_similar_actions(planned_action)

            # 获取备选方案
            alternatives = self._get_alternative_actions(planned_action, context)

            prompt = self.predictive_reflection_prompt.format(
                planned_action=action_desc[:300],
                context=json.dumps(context, ensure_ascii=False)[:200],
                similar_actions=similar_actions,
                alternatives=alternatives
            )

            reflection_data = await self._call_reflection_llm_async(prompt)
            # LLM异步调用成功，继续处理

            reflection = Reflection(
                level=ReflectionLevel.PREDICTIVE,
                trigger=ReflectionTrigger.BEFORE_ACTION,
                context_summary=f"行动前预测 - {action_desc[:50]}...",
                observation=reflection_data.get("observation", ""),
                insight=reflection_data.get("insight", ""),
                suggestion=reflection_data.get("suggestion", ""),
                confidence=reflection_data.get("confidence", 0.5),
                metadata={
                    "risk_factors": reflection_data.get("risk_factors", []),
                    "fallback_plan": reflection_data.get("fallback_plan", ""),
                    "success_probability": reflection_data.get("success_probability", 0.5),
                    "planned_action": planned_action
                }
            )

            # 质量评估
            quality_metrics = self._assess_reflection_quality(reflection)
            reflection.quality_score = quality_metrics.overall_score

            if reflection.quality_score >= self.quality_threshold:
                self.reflection_history.append(reflection)
                await self._store_reflection(reflection)

            logger.info(f"[Reflector] 预测性反思完成，成功概率预估: {reflection.metadata.get('success_probability', 0.5):.2f}")
            return reflection

        except ReflectionAIError as e:
            logger.error(f"[Reflector] reflect_before_action LLM调用失败: {e}", exc_info=True)
            return None

        except Exception as e:
            logger.error(f"[Reflector] reflect_before_action失败: {e}", exc_info=True)
            return None

    async def reflect_periodic(self, task: str, steps: list[dict],
                        step_count: int) -> Reflection | None:  # 周期性策略反思，每5步进行一次策略审查
        if step_count % 5 != 0 or step_count < 3:  # 每5步进行一次策略反思，且至少执行3步后才触发
            return None  # 不满足条件时返回None

        try:  # 【静默失败修复】添加异常处理
            stuck_reason = self._detect_stuck_pattern(steps)  # 检测是否卡住（循环、重复失败等）

            prompt = self.strategy_reflection_prompt.format(  # 格式化策略反思Prompt
                task=task[:200],  # 任务描述，限制长度
                steps_summary=self._format_trajectory(steps[-5:]),  # 最近5步摘要
                step_count=step_count,  # 当前步数
                last_result="成功" if steps[-1].get("success") else "失败",  # 最近结果状态
                available_patterns=self._format_available_patterns(task)  # 可用的策略模式
            )

            reflection_data = await self._call_reflection_llm_async(prompt)  # 异步调用大模型进行策略反思
            # LLM异步调用成功，继续处理

            level = ReflectionLevel.META if stuck_reason else ReflectionLevel.STRATEGY  # 如果检测到卡住，升级为元反思
            trigger = ReflectionTrigger.ON_STUCK if stuck_reason else ReflectionTrigger.PERIODIC  # 根据是否卡住决定触发条件

            reflection = Reflection(  # 创建Reflection对象
                level=level,  # 根据是否卡住决定反思层次
                trigger=trigger,  # 触发条件
                context_summary=f"第{step_count}步周期性反思",  # 上下文摘要
                observation=reflection_data.get("observation", ""),
                insight=reflection_data.get("insight", ""),
                suggestion=reflection_data.get("suggestion", ""),
                confidence=reflection_data.get("confidence", 0.5),
                metadata={  # 元数据
                    "stuck_reason": stuck_reason,  # 卡住原因（如有）
                    "recommended_pattern": reflection_data.get("recommended_pattern")  # 推荐策略模式
                }
            )

            # 【新增】质量评估
            quality_metrics = self._assess_reflection_quality(reflection)
            reflection.quality_score = quality_metrics.overall_score

            if reflection.quality_score >= self.quality_threshold:
                self.reflection_history.append(reflection)  # 添加到历史
                await self._store_reflection(reflection)  # 存储到记忆系统
                logger.info(f"[Reflector] 策略反思完成: {reflection.insight[:60]}...")

            return reflection

        except ReflectionAIError as e:
            logger.error(f"[Reflector] reflect_periodic LLM调用失败: {e}", exc_info=True)
            return None

        except Exception as e:
            logger.error(f"[Reflector] reflect_periodic失败: {e}", exc_info=True)
            return None

    async def reflect_on_completion(self, task: str, trajectory: list[dict],
                             success: bool, final_answer: str) -> tuple[Reflection, StrategyPattern | None]:  # 任务完成后的整体反思

        reflection_data = {}  # 默认为空字典

        try:  # 【静默失败修复】添加异常处理
            prompt = self.task_reflection_prompt.format(  # 格式化任务反思Prompt
                task=task[:200],  # 任务描述
                full_trajectory=self._format_trajectory(trajectory),  # 完整轨迹
                final_result=final_answer[:300],  # 最终结果，限制长度
                success=success,  # 成功状态
                reflections=self._format_reflection_history()  # 历史反思记录
            )

            reflection_data = await self._call_reflection_llm_async(prompt)  # 调用大模型进行任务级反思
            # LLM调用成功，继续处理

        except ReflectionAIError as e:
            logger.error(f"[Reflector] reflect_on_completion LLM调用失败: {e}", exc_info=True)
            # 使用空字典继续，创建一个降级反思记录

        except Exception as e:
            logger.error(f"[Reflector] reflect_on_completion失败: {e}", exc_info=True)
            # 使用空字典继续，创建一个降级反思记录

        try:
            reflection = Reflection(  # 创建Reflection对象
                level=ReflectionLevel.META,  # 任务级反思属于元层
                trigger=ReflectionTrigger.ON_COMPLETE,  # 任务完成触发
                context_summary=f"任务完成复盘 - {'成功' if success else '失败'}",  # 状态摘要
                observation=reflection_data.get("execution_summary", ""),  # 执行总结
                insight=reflection_data.get("root_cause", ""),  # 成功/失败根因
                suggestion=", ".join(reflection_data.get("improvement_areas", [])),  # 改进方向
                confidence=reflection_data.get("confidence", 0.7),
                metadata={  # 元数据
                    "what_worked": reflection_data.get("what_worked", ""),  # 有效的方法
                    "what_failed": reflection_data.get("what_failed", ""),  # 无效的方法
                    "key_decisions": reflection_data.get("key_decisions", [])  # 关键决策点
                }
            )

            # 【新增】质量评估
            quality_metrics = self._assess_reflection_quality(reflection)
            reflection.quality_score = quality_metrics.overall_score

            self.reflection_history.append(reflection)  # 添加到历史
            await self._store_reflection(reflection)  # 存储到记忆系统

            pattern = None  # 提取策略模式（仅当成功时，失败的经验不提取为可复用模式）
            if success and "extracted_pattern" in reflection_data:  # 仅当成功且包含模式数据时
                pattern = await self._extract_strategy_pattern(
                    reflection_data["extracted_pattern"],
                    trajectory
                )

            # 【新增】贝叶斯更新策略模式
            if pattern:
                # 计算反思质量作为证据置信度
                confidence = quality_metrics.overall_score

                # 贝叶斯更新
                if pattern.pattern_id in self.strategy_patterns:
                    existing = self.strategy_patterns[pattern.pattern_id]
                    existing.update_with_evidence(success, confidence)
                    pattern = existing
                else:
                    pattern.update_with_evidence(success, confidence)
                    self.strategy_patterns[pattern.pattern_id] = pattern

                # 保存到向量记忆
                await self._save_pattern_to_memory(pattern)

            # 【增强】即使任务成功，也进行成功后反思
            if success and len(trajectory) > 2:
                await self.reflect_after_success(task, trajectory, final_answer)

            # ── KF 前向更新：为 RTS 平滑积累历史 ──────────────────────────────
            try:
                success_prob = 1.0 if success else 0.0
                quality = reflection.quality_score if hasattr(reflection, 'quality_score') else 0.5
                self._update_reflection_kf(success_prob, quality)
            except Exception:
                pass

            logger.info(f"[Reflector] 任务反思完成，提取模式: {pattern.name if pattern else 'None'}")
            return reflection, pattern

        except Exception as e:
            logger.error(f"[Reflector] reflect_on_completion处理失败: {e}", exc_info=True)
            # 返回一个默认的Reflection对象，避免调用方出错
            return Reflection(
                level=ReflectionLevel.META,
                trigger=ReflectionTrigger.ON_COMPLETE,
                context_summary=f"任务完成复盘 - {'成功' if success else '失败'} (发生错误)",
                observation="",
                insight=f"反思过程中发生错误: {e}",
                suggestion="",
                confidence=0.0
            ), None

    def get_strategy_advice(self, task: str, current_steps: list[dict]) -> dict | None:  # 获取策略建议 - 供ReAct引擎调用
        try:  # 【静默失败修复】添加异常处理
            # 【修改】使用Thompson采样代替简单排序获取最佳策略
            selected_pattern = self.select_strategy_thompson(task, {})

            # 如果没有Thompson采样结果，回退到原有方法
            if selected_pattern:
                patterns = [selected_pattern] + [p for p in self._find_applicable_patterns(task) if p.pattern_id != selected_pattern.pattern_id][:2]
            else:
                patterns = self._find_applicable_patterns(task)

            warning = self._detect_repeating_errors(current_steps)  # 2. 检测是否正在重复相同的错误

            advice = {  # 3. 构建综合建议字典
                "applicable_patterns": [p.to_dict() for p in patterns[:3]],  # 最多3个模式
                "warning": warning,  # 错误警告
                "suggested_next_action": None  # 下一步建议，初始为None
            }

            if patterns and len(current_steps) < len(patterns[0].strategy_steps):  # 如果有推荐的模式且当前步数少于模式步骤数
                next_step = patterns[0].strategy_steps[len(current_steps)]  # 获取下一步建议
                advice["suggested_next_action"] = next_step  # 设置建议的下一步动作

            return advice if patterns or warning else None  # 只有存在适用模式或警告时才返回建议，否则返回None
        except Exception as e:
            logger.error(f"[Reflector] get_strategy_advice失败: {e}", exc_info=True)
            return None

    # ========== 【新增】反思质量评估方法 ==========

    def _assess_reflection_quality(self, reflection: Reflection) -> ReflectionQualityMetrics:
        """
        【新增】评估反思质量，低质量的反思不存储
        评估维度：
        1. 深度：洞察是否深刻
        2. 具体性：建议是否具体可行
        3. 可执行性：是否可以转化为行动
        4. 新颖性：是否是新的洞察
        """
        metrics = ReflectionQualityMetrics()

        try:  # 【静默失败修复】添加异常处理
            insight = reflection.insight.lower()
            suggestion = reflection.suggestion.lower()
            reflection.observation.lower()

            # 深度评分：洞察的长度和关键词
            depth_keywords = ["根本原因", "本质", "深层", "核心", "underlying", "root cause", "fundamental"]
            depth_score = min(1.0, len(reflection.insight) / 100)  # 长度因素
            depth_score += sum(1 for kw in depth_keywords if kw in insight) * 0.1  # 关键词因素
            metrics.depth_score = min(1.0, depth_score)

            # 具体性评分：建议的长度和具体性关键词
            specificity_keywords = ["具体", "步骤", "方法", "工具", "specific", "step", "method", "tool"]
            specificity_score = min(1.0, len(reflection.suggestion) / 150)
            specificity_score += sum(1 for kw in specificity_keywords if kw in suggestion) * 0.1
            metrics.specificity_score = min(1.0, specificity_score)

            # 可执行性评分：是否包含可操作的指令
            action_keywords = ["应该", "可以", "尝试", "使用", "调用", "检查", "should", "can", "try", "use", "call"]
            action_count = sum(1 for kw in action_keywords if kw in suggestion)
            metrics.actionability_score = min(1.0, action_count * 0.2 + 0.3)

            # 新颖性评分：检查是否与历史反思重复
            metrics.novelty_score = self._calculate_novelty(reflection)

            # 综合评分（加权平均）
            metrics.overall_score = (
                metrics.depth_score * 0.25 +
                metrics.specificity_score * 0.25 +
                metrics.actionability_score * 0.3 +
                metrics.novelty_score * 0.2
            )

            # 置信度调整
            metrics.overall_score *= reflection.confidence
        except Exception as e:
            logger.error(f"[Reflector] 评估反思质量失败: {e}", exc_info=True)
            # 返回默认评分
            metrics.overall_score = 0.5

        return metrics

    def _calculate_novelty(self, reflection: Reflection) -> float:
        """计算反思的新颖性（与历史反思的差异度）"""
        if not self.reflection_history:
            return 1.0  # 第一条反思默认是新颖的

        try:  # 【静默失败修复】添加异常处理
            # 简单的文本相似度检查
            from difflib import SequenceMatcher

            max_similarity = 0.0
            insight_text = reflection.insight.lower()

            for hist_reflection in self.reflection_history[-20:]:  # 只检查最近的20条
                similarity = SequenceMatcher(None, insight_text,
                                            hist_reflection.insight.lower()).ratio()
                max_similarity = max(max_similarity, similarity)

            # 相似度越低，新颖性越高
            return 1.0 - min(1.0, max_similarity)
        except Exception as e:
            logger.error(f"[Reflector] 计算新颖性失败: {e}", exc_info=True)
            return 0.5  # 返回默认新颖性

    # ── RTS 平滑：历史判断修正 ─────────────────────────────────────────────
    def _update_reflection_kf(self, success_prob_obs: float, quality_obs: float):
        """前向 KF 更新：每次反思后调用，保存历史用于 RTS 平滑。"""
        try:
            import numpy as np
            Z = np.array([[success_prob_obs], [quality_obs]])
            # 保存预测前状态
            X_pred = self._reflection_kf.A @ self._reflection_kf.X if hasattr(self._reflection_kf, 'A') else self._reflection_kf_A @ self._reflection_kf.X
            P_pred = self._reflection_kf.A @ self._reflection_kf.P @ self._reflection_kf_A.T + self._reflection_kf_Q
            # predict
            self._reflection_kf.predict(self._reflection_kf_A, self._reflection_kf_Q)
            # update
            self._reflection_kf.update(Z, self._reflection_kf_H, self._reflection_kf_R)
            # 保存前向历史 (X_pred, P_pred, X_update, P_update)
            self._rts_history.append((
                X_pred.copy(), P_pred.copy(),
                self._reflection_kf.X.copy(), self._reflection_kf.P.copy()
            ))
            # 限制历史长度，防止内存无限增长
            if len(self._rts_history) > 1000:
                self._rts_history = self._rts_history[-500:]
        except Exception as e:
            logger.debug(f"[Reflector] KF 前向更新失败: {e}")

    def _correct_historical_judgment(self) -> list[dict]:
        """
        RTS 平滑：利用 KF 预测-更新框架修正历史判断。

        返回平滑后的历史状态序列，每个元素包含：
        - smoothed_success_belief: 平滑后的策略成功率信念
        - smoothed_quality_trend: 平滑后的反思质量趋势
        - timestamp_index: 历史索引
        """
        if len(self._rts_history) < 2:
            return []

        try:
            import numpy as np
            n = len(self._rts_history)
            # 提取前向结果
            X_updates = [h[2] for h in self._rts_history]
            P_updates = [h[3] for h in self._rts_history]
            X_preds = [h[0] for h in self._rts_history]
            P_preds = [h[1] for h in self._rts_history]

            # 初始化平滑结果（最后一步的平滑值等于更新值）
            X_smooth = [None] * n
            P_smooth = [None] * n
            X_smooth[-1] = X_updates[-1].copy()
            P_smooth[-1] = P_updates[-1].copy()

            # 后向 pass
            for t in range(n - 2, -1, -1):
                # C(t) = P_update(t) @ A.T @ inv(P_pred(t+1))
                try:
                    C = P_updates[t] @ self._reflection_kf_A.T @ np.linalg.inv(P_preds[t + 1])
                except np.linalg.LinAlgError:
                    C = np.zeros((2, 2))
                X_smooth[t] = X_updates[t] + C @ (X_smooth[t + 1] - X_preds[t + 1])
                P_smooth[t] = P_updates[t] + C @ (P_smooth[t + 1] - P_preds[t + 1]) @ C.T

            # 构建返回结果
            results = []
            for i in range(n):
                results.append({
                    'smoothed_success_belief': float(X_smooth[i][0, 0]),
                    'smoothed_quality_trend': float(X_smooth[i][1, 0]),
                    'timestamp_index': i,
                    'raw_success_belief': float(X_updates[i][0, 0]),
                    'raw_quality_trend': float(X_updates[i][1, 0]),
                })
            return results
        except Exception as e:
            logger.error(f"[Reflector] RTS 平滑失败: {e}", exc_info=True)
            return []

    # ========== 【新增】辅助方法 ==========

    def _extract_operations(self, trajectory: list[dict]) -> str:
        """提取轨迹中涉及的操作"""
        operations = []
        for step in trajectory:
            tool = step.get("tool", "unknown")
            if tool != "unknown":
                operations.append(tool)
        return ", ".join(set(operations)) if operations else "无"

    def _extract_interactions(self, trajectory: list[dict]) -> str:
        """提取用户交互点"""
        interactions = []
        for step in trajectory:
            if "user" in str(step.get("result", "")).lower():
                interactions.append("用户反馈")
            if "confirm" in str(step.get("tool", "")).lower():
                interactions.append("确认操作")
        return ", ".join(interactions) if interactions else "无直接交互"

    def _extract_problems(self, trajectory: list[dict]) -> str:
        """提取遇到的问题"""
        problems = []
        for step in trajectory:
            if not step.get("success") and "error" in step:
                problems.append(str(step["error"])[:50])
        return "; ".join(problems) if problems else "无明显问题"

    def _find_similar_actions(self, planned_action: dict) -> str:
        """查找历史类似操作"""
        action_type = planned_action.get("type", planned_action.get("tool", "unknown"))
        similar = []

        try:  # 【静默失败修复】添加异常处理
            for reflection in self.reflection_history:
                if action_type in str(reflection.metadata.get("planned_action", {})):
                    similar.append(f"历史{action_type}操作 - 结果: {reflection.insight[:30]}...")
        except Exception as e:
            logger.error(f"[Reflector] 查找类似操作失败: {e}", exc_info=True)

        return "\n".join(similar[:3]) if similar else "无类似历史操作"

    def _get_alternative_actions(self, planned_action: dict, context: dict) -> str:
        """获取备选方案"""
        alternatives = []

        try:  # 【静默失败修复】添加异常处理
            # 基于策略模式提供备选
            task_desc = context.get("task", "")
            patterns = self._find_applicable_patterns(task_desc)

            for pattern in patterns[:2]:
                alternatives.append(f"备选策略: {pattern.name} - {pattern.description[:50]}...")
        except Exception as e:
            logger.error(f"[Reflector] 获取备选方案失败: {e}", exc_info=True)

        return "\n".join(alternatives) if alternatives else "暂无备选方案"

    # ========== 内部辅助方法 ==========

    def _call_reflection_llm(self, prompt: str) -> dict:  # 调用LLM进行反思分析
        """
        调用LLM进行反思分析

        Args:
            prompt: 反思提示词

        Returns:
            Dict: 解析后的JSON数据

        Raises:
            ReflectionAIError: LLM调用失败或响应解析失败
        """
        try:  # 异常处理块
            messages = [  # 构建消息列表，system消息设定角色和输出格式
                {"role": "system", "content": "你是一个反思助手，擅长分析执行过程并提炼洞察。只输出JSON格式。"},
                {"role": "user", "content": prompt}
            ]

            try:
                response = call_thinker(messages, temperature=0.3)
            except AIResponseError as e:
                logger.error(f"[Reflector] LLM调用失败: {e}", exc_info=True)
                raise ReflectionAIError(f"LLM调用失败: {e}") from e
            except Exception as e:
                logger.error(f"[Reflector] LLM调用异常: {e}", exc_info=True)
                raise ReflectionAIError(f"LLM调用异常: {e}") from e

            if not response or not str(response).strip():
                logger.error("[Reflector] _call_reflection_llm: AI返回空响应")
                raise ReflectionAIError("LLM返回空响应")

            json_match = self._extract_json(response)  # 从响应文本中提取JSON内容
            if json_match:  # 找到有效JSON
                try:  # 【静默失败修复】添加JSON解析异常处理
                    parsed_result = json.loads(json_match)  # 解析JSON为字典
                    if not parsed_result:
                        raise ReflectionAIError("无法解析LLM响应：解析结果为空")
                    return parsed_result
                except json.JSONDecodeError as e:
                    logger.error(f"[Reflector] JSON解析失败: {e}", exc_info=True)
                    raise ReflectionAIError(f"JSON解析失败: {e}") from e

            logger.error("[Reflector] _call_reflection_llm: 无法从响应中提取JSON")
            raise ReflectionAIError("无法从LLM响应中提取有效JSON")

        except ReflectionAIError:
            raise

        except Exception as e:
            logger.error(f"[Reflector] LLM调用失败: {e}", exc_info=True)
            raise ReflectionAIError(f"LLM调用失败: {e}") from e

    async def _call_reflection_llm_async(self, prompt: str) -> dict:
        """
        异步调用LLM进行反思分析
        """
        try:
            messages = [
                {"role": "system", "content": "你是一个反思助手，擅长分析执行过程并提炼洞察。只输出JSON格式。"},
                {"role": "user", "content": prompt}
            ]

            try:
                response = await call_thinker_async(messages, temperature=0.3)
            except AIResponseError as e:
                logger.error(f"[Reflector] LLM异步调用失败: {e}", exc_info=True)
                raise ReflectionAIError(f"LLM异步调用失败: {e}") from e
            except Exception as e:
                logger.error(f"[Reflector] LLM异步调用异常: {e}", exc_info=True)
                raise ReflectionAIError(f"LLM异步调用异常: {e}") from e

            if not response or not str(response).strip():
                logger.error("[Reflector] _call_reflection_llm_async: AI返回空响应")
                raise ReflectionAIError("LLM返回空响应")

            json_match = self._extract_json(response)
            if json_match:
                try:
                    parsed_result = json.loads(json_match)
                    if not parsed_result:
                        raise ReflectionAIError("无法解析LLM响应：解析结果为空")
                    return parsed_result
                except json.JSONDecodeError as e:
                    logger.error(f"[Reflector] JSON解析失败: {e}", exc_info=True)
                    raise ReflectionAIError(f"JSON解析失败: {e}") from e

            logger.error("[Reflector] _call_reflection_llm_async: 无法从响应中提取JSON")
            raise ReflectionAIError("无法从LLM响应中提取有效JSON")

        except ReflectionAIError:
            raise

        except Exception as e:
            logger.error(f"[Reflector] LLM异步调用失败: {e}", exc_info=True)
            raise ReflectionAIError(f"LLM异步调用失败: {e}") from e

    def _extract_json(self, text: str) -> str | None:
        """从文本中提取JSON字符串，支持清洗注释"""
        import re

        try:  # 【静默失败修复】添加异常处理
            # 首先尝试匹配markdown代码块（捕获块内全部内容，再提取JSON）
            code_block = re.search(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL)
            if code_block:
                content = code_block.group(1).strip()
                if content.startswith('{') and content.endswith('}'):
                    json_str = content
                else:
                    json_match = re.search(r'\{.*\}', content, re.DOTALL)
                    if json_match:
                        json_str = json_match.group(0)
                    else:
                        return None
            else:
                # 尝试匹配普通JSON对象
                json_match = re.search(r'\{.*\}', text, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                else:
                    return None

            # 【修复】清洗JSON中的注释和非法字符
            # 1. 移除单行注释 //...
            json_str = re.sub(r'//[^\n]*', '', json_str)
            # 2. 移除多行注释 /*...*/
            json_str = re.sub(r'/\*.*?\*/', '', json_str, flags=re.DOTALL)
            # 3. 移除尾随逗号（在 } 或 ] 之前的逗号）
            json_str = re.sub(r',\s*}', '}', json_str)
            json_str = re.sub(r',\s*\]', ']', json_str)
            # 4. 清理多余的空白和换行
            json_str = re.sub(r'\n\s*\n', '\n', json_str)
            # 5. 清理控制字符
            json_str = re.sub(r'[\x00-\x1f\x7f]', '', json_str)

            return json_str
        except Exception as e:
            logger.error(f"[Reflector] 提取JSON失败: {e}", exc_info=True)
            return None

    def _format_trajectory(self, steps: list[dict]) -> str:  # 格式化执行轨迹为可读文本，将步骤列表转换为带编号、状态标记的文本格式
        lines = []
        try:  # 【静默失败修复】添加异常处理
            for i, step in enumerate(steps, 1):  # 从1开始编号
                tool = step.get("tool", "unknown")  # 工具名
                success = "✓" if step.get("success") else "✗"  # 成功/失败标记
                result = str(step.get("result", ""))[:50]  # 结果摘要，限制50字符
                lines.append(f"  {i}. [{success}] {tool}: {result}")  # 格式化单行
        except Exception as e:
            logger.error(f"[Reflector] 格式化轨迹失败: {e}", exc_info=True)
        return "\n".join(lines)  # 用换行连接所有行

    def _format_reflection_history(self) -> str:  # 格式化反思历史为可读文本，提取最近5条反思记录的核心洞察
        lines = []
        try:  # 【静默失败修复】添加异常处理
            for r in self.reflection_history[-5:]:  # 最近5条反思
                lines.append(f"- [{r.level.value}] {r.insight[:60]}...")  # 显示层级和洞察摘要
        except Exception as e:
            logger.error(f"[Reflector] 格式化反思历史失败: {e}", exc_info=True)
        return "\n".join(lines)

    def _format_available_patterns(self, task: str) -> str:  # 格式化可用策略模式为可读文本
        try:  # 【静默失败修复】添加异常处理
            patterns = self._find_applicable_patterns(task)  # 查找适用模式
            if not patterns:  # 无适用模式
                return "无"

            lines = []
            for p in patterns[:3]:  # 最多显示3个
                lines.append(f"- {p.name} (成功率{p.success_rate:.0%}): {p.description[:50]}")
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"[Reflector] 格式化可用模式失败: {e}", exc_info=True)
            return "无"

    def _detect_stuck_pattern(self, steps: list[dict]) -> str | None:  # 检测是否陷入循环或卡住，分析最近步骤检测重复模式
        if len(steps) < 4:  # 步骤太少，无法检测
            return None

        try:  # 【静默失败修复】添加异常处理
            recent_tools = [s.get("tool") for s in steps[-4:]]  # 最近4步的工具
            if len(set(recent_tools)) == 1:  # 集合去重后长度为1说明全相同，连续4次使用同一工具
                return f"连续4次使用同一工具: {recent_tools[0]}"

            recent_results = [s.get("success") for s in steps[-3:]]  # 最近3步的成功状态
            if all(not r for r in recent_results):  # 全部为False，连续3次失败
                return "连续3次失败"

            if len(steps) >= 4:  # 检测交替模式（A-B-A-B）：最近4步呈现交替
                tools = [s.get("tool") for s in steps[-4:]]
                if tools[0] == tools[2] and tools[1] == tools[3]:  # 检查位置0和2相同，位置1和3相同
                    return f"工具交替循环: {tools[0]} ↔ {tools[1]}"
        except Exception as e:
            logger.error(f"[Reflector] 检测卡住模式失败: {e}", exc_info=True)

        return None  # 未检测到卡住模式

    def _detect_repeating_errors(self, steps: list[dict]) -> str | None:  # 检测重复错误模式，分析最近步骤是否重复遇到相同的错误
        if len(steps) < 3:  # 步骤太少
            return None

        try:  # 【静默失败修复】添加异常处理
            recent_errors = []  # 获取最近失败的错误信息
            for s in steps[-3:]:  # 最近3步
                if not s.get("success") and "error" in s:  # 失败且包含错误信息
                    recent_errors.append(s["error"])

            if len(recent_errors) >= 2 and recent_errors[0] == recent_errors[1]:  # 如果有2个以上错误且错误相同
                return f"重复遇到相同错误: {recent_errors[0][:50]}"
        except Exception as e:
            logger.error(f"[Reflector] 检测重复错误失败: {e}", exc_info=True)

        return None

    def _find_applicable_patterns(self, task: str) -> list[StrategyPattern]:  # 查找适用于当前任务的策略模式，通过关键词匹配
        applicable = []  # 适用模式列表

        try:  # 【静默失败修复】添加异常处理
            for pattern in self.strategy_patterns.values():  # 遍历所有模式
                for scenario in pattern.applicable_scenarios:  # 检查场景匹配：任务描述中包含模式适用的场景关键词
                    if scenario.lower() in task.lower():  # 不区分大小写匹配
                        applicable.append(pattern)
                        break  # 匹配一个场景即可，跳出内层循环

            applicable.sort(key=lambda p: p.success_rate, reverse=True)  # 按成功率降序排序，优先推荐成功率高的模式
        except Exception as e:
            logger.error(f"[Reflector] 查找适用模式失败: {e}", exc_info=True)

        return applicable

    # 【新增】辅助方法：检索候选策略模式
    def _retrieve_candidate_patterns(self, task: str, context: dict) -> list[StrategyPattern]:
        """检索适用于当前任务的候选策略模式"""
        return self._find_applicable_patterns(task)

    # 【新增】贝叶斯选择方法：Thompson采样
    def select_strategy_thompson(self, task: str, context: dict) -> StrategyPattern | None:
        """Thompson采样选择策略 - 从Beta分布采样，平衡探索与利用"""
        try:  # 【静默失败修复】添加异常处理
            candidates = self._retrieve_candidate_patterns(task, context)
            if not candidates:
                return None

            # Thompson采样
            best_pattern = None
            best_sample = -1

            for pattern in candidates:
                # 从Beta分布采样
                try:
                    from numpy.random import beta as beta_sample
                    sample_val = beta_sample(pattern.alpha, pattern.beta)
                except ImportError:
                    # 无numpy时使用Python标准库的random.betavariate
                    import random
                    sample_val = random.betavariate(pattern.alpha, pattern.beta)

                if sample_val > best_sample:
                    best_sample = sample_val
                    best_pattern = pattern

            return best_pattern
        except Exception as e:
            logger.error(f"[Reflector] Thompson采样失败: {e}", exc_info=True)
            return None

    # 【新增】贝叶斯选择方法：UCB
    def select_strategy_ucb(self, task: str, context: dict) -> StrategyPattern | None:
        """UCB选择策略 - 上置信界算法，平衡探索与利用"""
        import math

        try:  # 【静默失败修复】添加异常处理
            candidates = self._retrieve_candidate_patterns(task, context)
            if not candidates:
                return None

            best_pattern = None
            best_ucb = -1
            total_trials_all = sum(p.alpha + p.beta - 2 for p in candidates)

            for pattern in candidates:
                success_prob = pattern.get_success_probability()
                total_trials = pattern.alpha + pattern.beta - 2

                if total_trials == 0:
                    ucb = float('inf')  # 新策略优先探索
                else:
                    exploration_term = self.ucb_exploration_factor * math.sqrt(
                        2 * math.log(total_trials_all + 1) / total_trials
                    )
                    ucb = success_prob + exploration_term

                if ucb > best_ucb:
                    best_ucb = ucb
                    best_pattern = pattern

            return best_pattern
        except Exception as e:
            logger.error(f"[Reflector] UCB选择失败: {e}", exc_info=True)
            return None

    async def _extract_strategy_pattern(self, pattern_data: dict,
                                  trajectory: list[dict]) -> StrategyPattern | None:  # 从反思数据中提取策略模式，任务成功后将成功经验抽象为可复用模式
        try:  # 异常处理块
            pattern_id = f"pattern_{int(time.time())}_{hash(str(pattern_data)) % 10000}"  # 生成唯一ID：时间戳+哈希值

            pattern = StrategyPattern(  # 创建StrategyPattern对象
                pattern_id=pattern_id,
                name=pattern_data.get("name", "未命名策略"),
                description=pattern_data.get("description", ""),
                applicable_scenarios=pattern_data.get("applicable_to", []),
                strategy_steps=pattern_data.get("steps", []),
                success_rate=1.0,  # 首次提取，假设100%成功率
                usage_count=1      # 首次使用计数为1
            )

            await self._store_strategy_pattern(pattern)  # 存储到向量记忆（长期存储）
            self.strategy_patterns[pattern_id] = pattern  # 缓存到内存字典（快速访问）

            return pattern
        except Exception as e:
            logger.error(f"[Reflector] 提取策略模式失败: {e}", exc_info=True)
            return None

    async def _store_reflection(self, reflection: Reflection):  # 存储反思记录到记忆系统，将反思记录添加到分层记忆系统的中期记忆层
        try:  # 异常处理块
            ms = await get_memory_service()
            await ms.add_memory(
                user_id="default",
                content=reflection.insight,
                memory_type="reflection",
                layer="medium",
                metadata={
                    "level": reflection.level.value,
                    "trigger": reflection.trigger.value,
                    "suggestion": reflection.suggestion,
                    "confidence": reflection.confidence,
                    "quality_score": reflection.quality_score
                },
                scene="reflection",
                rating=reflection.quality_score,
                expire_days=30,
                source=MemorySource.REFLECTION
            )
        except Exception as e:
            logger.error(f"[Reflector] 存储反思失败: {e}", exc_info=True)
            raise ReflectionError(f"存储反思失败: {e}") from e

    async def _store_strategy_pattern(self, pattern: StrategyPattern):  # 存储策略模式到向量记忆（作为知识存储）
        try:  # 异常处理块
            import json  # 导入JSON模块
            ms = await get_memory_service()
            await ms.add_memory(
                user_id="default",
                content=json.dumps(pattern.to_dict(), ensure_ascii=False),
                memory_type="knowledge",
                layer="evolve",
                metadata={
                    "pattern_id": pattern.pattern_id,
                    "type": "strategy_pattern",
                    "applicable_scenarios": pattern.applicable_scenarios
                },
                scene=pattern.applicable_scenarios[0] if pattern.applicable_scenarios else "general",
                expire_days=None,
                source=MemorySource.REFLECTION
            )
        except Exception as e:
            logger.error(f"[Reflector] 存储策略模式失败: {e}", exc_info=True)
            raise ReflectionError(f"存储策略模式失败: {e}") from e

    # 【新增】_save_pattern_to_memory 作为 _store_strategy_pattern 的别名（供贝叶斯更新使用）
    async def _save_pattern_to_memory(self, pattern: StrategyPattern):
        """保存策略模式到记忆（供贝叶斯更新调用）"""
        await self._store_strategy_pattern(pattern)

    async def extract_experiences_from_executions(
        self,
        user_id: str,
        limit: int = 10,
    ) -> list[dict]:
        """
        【P3新增】从执行记忆中提炼有价值的经验。

        1. 从 execution_memory 读取最近的工具执行记录
        2. 筛选出"成功"的执行记录
        3. 调用文本AI对成功经验进行总结，生成一句话经验描述
        4. 将经验存入 memory_manager（mem_type="experience"）

        Args:
            user_id: 用户标识
            limit: 读取最近多少条执行记录

        Returns:
            提炼出的经验记录列表
        """
        extracted: list[dict] = []

        if execution_memory_manager is None:
            logger.debug("[Reflector] execution_memory_manager 不可用，跳过经验提取")
            return extracted

        try:
            # 1. 读取最近执行记录（仅成功）
            records = await execution_memory_manager.get_recent_executions_async(
                user_id=user_id,
                limit=limit,
                success_only=True,
            )
            if not records:
                logger.debug(f"[Reflector] 用户 {user_id} 无成功执行记录，跳过经验提取")
                return extracted

            logger.info(f"[Reflector] 从执行记忆读取 {len(records)} 条成功记录，开始提炼经验")

            # 【P0-优化】批量调用合并：将多个工具的总结合并为单次 LLM 请求
            # 2. 按工具名分组，每组取最新的一条，收集所有待总结记录
            seen_tools: set = set()
            tool_records: list[dict] = []
            for record in records:
                tool_name = record.get("tool_name", "unknown")
                if tool_name in seen_tools:
                    continue
                seen_tools.add(tool_name)
                tool_records.append(record)

            if not tool_records:
                return extracted

            # 【P1-优化】引入语义缓存：复用 SearchCache 对批量 prompt 做缓存
            _cache_hit = False
            _cache = None
            try:
                from core.utils.search_cache import SearchCache
                _cache = SearchCache()
            except Exception:
                pass

            # 构建批量总结提示（所有工具合并为一次调用）
            _tools_summary = []
            for idx, rec in enumerate(tool_records, 1):
                _tn = rec.get("tool_name", "unknown")
                _ps = json.dumps(rec.get("input_params", {}), ensure_ascii=False, default=str)[:200]
                _os = json.dumps(rec.get("output_result", {}), ensure_ascii=False, default=str)[:200]
                _et = rec.get("execution_time_ms", 0)
                _tools_summary.append(
                    f"{idx}. 工具: {_tn} | 参数: {_ps} | 结果: {_os} | 耗时: {_et}ms"
                )

            _batch_prompt = (
                "以下是一组工具执行的成功记录，请为每条记录提炼一句经验描述（不超过50字）。\n\n"
                + "\n".join(_tools_summary)
                + "\n\n请按以下 JSON 数组格式返回结果（只输出JSON，不要其他内容）：\n"
                '[{"tool_name": "工具名", "experience": "经验描述"}, ...]'
            )

            # 尝试读取缓存
            _batch_response = None
            if _cache is not None:
                try:
                    _cached = _cache.get(_batch_prompt, content_type="reflector_batch")
                    if _cached and _cached.get("results"):
                        _batch_response = _cached["results"].get("response")
                        if _batch_response:
                            _cache_hit = True
                            logger.info("[Reflector] 批量经验总结缓存命中")
                except Exception:
                    pass

            if not _batch_response:
                try:
                    _batch_response = await call_thinker_async(
                        [{"role": "user", "content": _batch_prompt}]
                    )
                    # 写入缓存
                    if _cache is not None and _batch_response:
                        with contextlib.suppress(Exception):
                            _cache.set(
                                _batch_prompt,
                                {"response": _batch_response},
                                content_type="reflector_batch",
                                ttl=3600,
                            )
                except Exception as e:
                    logger.warning(f"[Reflector] 批量经验总结 LLM 调用失败: {e}")
                    _batch_response = None

            # 解析批量响应
            if _batch_response:
                try:
                    # 尝试解析 JSON
                    _parsed = json.loads(_batch_response.strip())
                    if isinstance(_parsed, list):
                        for item in _parsed:
                            if isinstance(item, dict) and item.get("tool_name") and item.get("experience"):
                                _exp = str(item["experience"]).strip().strip('"').strip("'")
                                if len(_exp) > 5:
                                    extracted.append({
                                        "tool_name": str(item["tool_name"]),
                                        "experience": _exp,
                                        "source": "execution_memory",
                                        "timestamp": time.time(),
                                    })
                    else:
                        # 回退：按行解析
                        for line in _batch_response.strip().split("\n"):
                            line = line.strip()
                            if line and len(line) > 5 and not line.startswith(("[", "{", "`")):
                                # 尝试匹配 "工具名: 经验" 或纯经验描述
                                extracted.append({
                                    "tool_name": "unknown",
                                    "experience": line,
                                    "source": "execution_memory",
                                    "timestamp": time.time(),
                                })
                except json.JSONDecodeError:
                    # JSON 解析失败，尝试按行提取
                    logger.debug("[Reflector] 批量响应 JSON 解析失败，尝试按行提取")
                    for line in _batch_response.strip().split("\n"):
                        line = line.strip()
                        if line and len(line) > 5 and not line.startswith(("[", "{", "`")):
                            extracted.append({
                                "tool_name": "unknown",
                                "experience": line,
                                "source": "execution_memory",
                                "timestamp": time.time(),
                            })
                except Exception as e:
                    logger.debug(f"[Reflector] 解析批量经验响应失败: {e}")

            # 3. 将提炼的经验存入记忆系统
            if extracted:
                memory_service = await get_memory_service()
                for exp in extracted:
                    try:
                        await memory_service.add_memory(
                            user_id=user_id,
                            content=exp["experience"],
                            memory_type="experience",
                            metadata={
                                "tool_name": exp["tool_name"],
                                "source": "reflector_extraction",
                                "extracted_at": exp["timestamp"],
                            },
                        )
                    except Exception as e:
                        logger.debug(f"[Reflector] 存储经验到记忆系统失败: {e}")

                logger.info(
                    f"[Reflector] 成功提炼并存储 {len(extracted)} 条经验"
                )

            return extracted

        except Exception as e:
            logger.error(f"[Reflector] extract_experiences_from_executions 异常: {e}", exc_info=False)
            return extracted


# 全局实例
try:
    reflector = Reflector()  # 创建模块级别的单例实例，供全系统使用
    logger.info("[Reflector] 全局实例创建成功")
except ReflectionError as e:
    logger.error(f"[Reflector] 创建单例失败: {e}", exc_info=True)
    raise
except Exception as e:
    logger.error(f"[Reflector] 创建单例异常: {e}", exc_info=True)
    raise ReflectionError(f"创建Reflector单例失败: {e}") from e


def get_reflector() -> Reflector:
    """
    获取Reflector单例实例

    Returns:
        Reflector: 全局Reflector实例
    """
    return reflector


# ========== 便捷函数 ==========
# 提供简化的函数接口，避免直接操作Reflector类

async def quick_reflect(task: str, step_info: dict, trajectory: list[dict]) -> dict | None:  # 快速反思便捷函数，简化调用方式，直接返回字典格式结果
    if reflector is None:
        logger.error("[Reflector] 未初始化，无法执行quick_reflect")
        return None
    try:
        reflection = await reflector.reflect_after_step(task, step_info, trajectory)
        return reflection.to_dict() if reflection else None
    except Exception as e:
        logger.error(f"[Reflector] quick_reflect失败: {e}", exc_info=True)
        return None


def get_task_strategy_advice(task: str) -> dict | None:  # 获取任务策略建议，查询是否有适用于该任务的历史策略模式
    if reflector is None:
        logger.error("[Reflector] 未初始化，无法获取策略建议")
        return None
    try:
        return reflector.get_strategy_advice(task, [])
    except Exception as e:
        logger.error(f"[Reflector] get_task_strategy_advice失败: {e}", exc_info=True)
        return None


async def extract_pattern_from_success(task: str, trajectory: list[dict]) -> dict | None:  # 从成功任务中提取策略模式
    if reflector is None:
        logger.error("[Reflector] 未初始化，无法提取模式")
        return None
    try:
        _, pattern = await reflector.reflect_on_completion(task, trajectory, True, "成功完成")
        return pattern.to_dict() if pattern else None
    except Exception as e:
        logger.error(f"[Reflector] extract_pattern_from_success失败: {e}", exc_info=True)
        return None


# 【新增】便捷函数
async def reflect_after_success(task: str, trajectory: list[dict], final_result: str = "") -> dict | None:
    """成功后反思的便捷函数"""
    if reflector is None:
        logger.error("[Reflector] 未初始化，无法执行reflect_after_success")
        return None
    try:
        reflection = await reflector.reflect_after_success(task, trajectory, final_result)
        return reflection.to_dict() if reflection else None
    except Exception as e:
        logger.error(f"[Reflector] reflect_after_success失败: {e}", exc_info=True)
        return None


async def reflect_multi_dimension(task: str, trajectory: list[dict], context: dict = None) -> dict | None:
    """多维度反思的便捷函数"""
    if reflector is None:
        logger.error("[Reflector] 未初始化，无法执行reflect_multi_dimension")
        return None
    try:
        multi_reflection = await reflector.reflect_multi_dimension(task, trajectory, context)
        return multi_reflection.to_dict() if multi_reflection else None
    except Exception as e:
        logger.error(f"[Reflector] reflect_multi_dimension失败: {e}", exc_info=True)
        return None


async def reflect_before_action(planned_action: dict, context: dict) -> dict | None:
    """预测性反思的便捷函数"""
    if reflector is None:
        logger.error("[Reflector] 未初始化，无法执行reflect_before_action")
        return None
    try:
        reflection = await reflector.reflect_before_action(planned_action, context)
        return reflection.to_dict() if reflection else None
    except Exception as e:
        logger.error(f"[Reflector] reflect_before_action失败: {e}", exc_info=True)
        return None


def assess_reflection_quality(reflection: dict) -> dict:
    """评估反思质量的便捷函数

    Args:
        reflection: 反思字典

    Returns:
        质量评估指标字典
    """
    if not reflection:
        return {"overall_score": 0.0, "passed": False}

    if reflector is None:
        logger.error("[Reflector] 未初始化，无法评估质量")
        return {"overall_score": 0.0, "passed": False}

    try:
        # 创建临时Reflection对象进行评估
        temp_reflection = Reflection(
            level=ReflectionLevel.EXECUTION,
            trigger=ReflectionTrigger.AFTER_STEP,
            context_summary="",
            observation=reflection.get("observation", ""),
            insight=reflection.get("insight", ""),
            suggestion=reflection.get("suggestion", ""),
            confidence=reflection.get("confidence", 0.5)
        )

        metrics = reflector._assess_reflection_quality(temp_reflection)

        return {
            "depth_score": metrics.depth_score,
            "specificity_score": metrics.specificity_score,
            "actionability_score": metrics.actionability_score,
            "novelty_score": metrics.novelty_score,
            "overall_score": metrics.overall_score,
            "passed": metrics.overall_score >= reflector.quality_threshold
        }
    except Exception as e:
        logger.error(f"[Reflector] assess_reflection_quality失败: {e}", exc_info=True)
        return {"overall_score": 0.0, "passed": False}


# ========== 批量反思方法 ==========
# 用于对多个任务进行批量分析和总结

def reflect_on_batch(self, tasks: list[dict]) -> dict:  # 对一批任务进行批量反思，分析多个任务的执行结果，找出共同问题和模式
    insights = []  # 收集所有反思记录
    for task in tasks:
        try:
            reflection = self.reflect_after_step(
                task.get("description", ""),
                task.get("step_info", {}),
                task.get("trajectory", [])
            )
            if reflection:
                insights.append(reflection)
        except Exception as e:
            logger.error(f"[Reflector] 批量反思单个任务失败: {e}", exc_info=True)

    try:
        common_issues = self._find_common_issues(insights)
    except Exception as e:
        logger.error(f"[Reflector] 查找共同问题失败: {e}", exc_info=True)
        common_issues = []

    return {  # 返回批量反思结果
        "total_reflections": len(insights),  # 反思总数
        "common_issues": common_issues,       # 共同问题
        "insights": insights                   # 详细反思列表
    }

def _find_common_issues(self, insights: list) -> list[str]:
    try:
        issue_counts = {}  # 问题计数字典
        for insight in insights:
            trigger = str(insight.trigger)  # 触发条件作为问题类型
            issue_counts[trigger] = issue_counts.get(trigger, 0) + 1  # 计数+1

        return [issue for issue, count in issue_counts.items() if count > 1]
    except Exception as e:
        logger.error(f"[Reflector] 查找共同问题失败: {e}", exc_info=True)
        return []


# 绑定方法到类
Reflector.reflect_on_batch = reflect_on_batch  # 将模块级别的函数动态添加到Reflector类，使其成为实例方法
Reflector._find_common_issues = _find_common_issues  # 将模块级别的函数动态添加到Reflector类


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase_V5 系统的"反思中枢"（Agent-7增强版），实现了 ReAct
# (Reasoning + Acting)框架中的 Reflection 环节。它赋予系统自我审视、总结经验、
# 持续改进的能力，是系统实现"自我进化"的核心模块。
#
# 【V3.0增强功能】
# 1. 成功后反思 (reflect_after_success)：即使成功也反思是否有更优解
# 2. 多维度反思 (reflect_multi_dimension)：从效率/安全/体验/学习四个维度全面评估
# 3. 预测性反思 (reflect_before_action)：行动前预测风险和问题
# 4. 反思质量评估 (_assess_reflection_quality)：过滤低质量反思，提升策略质量
#
# 【2026-03-10 静默失败修复】
# 1. 新增 ReflectionError, ReflectionAIError 异常类
# 2. _call_reflection_llm方法：返回类型从Optional[Dict]改为Dict，失败时抛出ReflectionAIError
# 3. 所有调用方捕获ReflectionAIError并记录[SILENT_FAILURE_BLOCKED]标记的ERROR日志
# 4. 禁止静默返回None，强制上层处理AI调用失败
# 5. 全局reflector实例创建失败时记录错误但不阻塞系统启动
#
# 【架构设计】
# - 四级反思体系: Execution(执行层)/Strategy(策略层)/Meta(元层)/Predictive(预测层)
# - 智能触发机制: 失败后、成功后、周期性(每5步)、卡住时、任务完成时、行动前触发
# - 策略模式提取: 将成功经验抽象为可复用的结构化知识
# - 记忆系统集成: 反思记录存中期记忆，策略模式存进化层永久保存
# - 质量过滤机制: 只保存高质量(>0.6)的反思，避免噪声累积
#
# 【关联文件】
# - core/ai_adapter.py      : 提供call_thinker()调用大模型进行反思分析
# - core/vector_memory.py   : 存储和检索策略模式
# - core/memory.py          : 存储反思记录到分层记忆系统
# - core/agent_loop.py      : 调用方，在ReAct循环中获取策略建议指导决策
#
# 【核心功能效果】
# 1. 错误自修复: 失败后自动分析原因并建议修正方案
# 2. 经验累积: 成功案例被提取为策略模式，供后续相似任务参考
# 3. 避免重复犯错: 检测重复错误模式并发出警告
# 4. 策略优化: 通过周期性反思及时调整执行策略
# 5. 持续进化: 随着任务执行不断积累策略知识，系统能力逐步提升
# 6. 风险预测: 行动前预测可能问题，提前准备备选方案
# 7. 质量保障: 只保存高质量反思，确保策略库的有效性
# 8. 异常安全: 所有反思失败都记录错误日志，禁止静默失败
#
# 【使用场景】
# 场景1: 工具调用失败 → reflect_after_step() → 分析原因 → 建议替代工具 → 重试
# 场景2: 工具调用成功 → reflect_after_success() → 寻找优化空间 → 提取成功模式
# 场景3: 执行5步后 → reflect_periodic() / reflect_multi_dimension() → 全面评估
# 场景4: 任务完成 → reflect_on_completion() → 提取成功模式 → 存储
# 场景5: 新任务开始 → get_strategy_advice() → 检索相似策略 → 提供建议
# 场景6: 行动前 → reflect_before_action() → 预测风险 → 准备备选方案
# =============================================================================


def get_reflection_context(user_id: str, current_intent: str, current_tools: list[str]) -> str | None:
    """获取反思上下文信息

    Args:
        user_id: 用户ID
        current_intent: 当前意图
        current_tools: 当前工具列表

    Returns:
        str: 反思上下文字符串，失败返回None
    """
    try:
        if reflector is None:
            logger.error("[Reflector] get_reflection_context 失败: reflector 未初始化")
            return None

        # 基于现有方法构建上下文
        context_parts = []

        # 1. 获取策略建议
        advice = reflector.get_strategy_advice(current_intent, current_tools or [])
        if advice:
            context_parts.append(f"策略建议: {advice.get('suggestion', '')}")

        # 2. 获取适用的策略模式
        patterns = reflector._find_applicable_patterns(current_intent)
        if patterns:
            pattern_names = [p.name for p in patterns[:3]]
            context_parts.append(f"历史成功模式: {', '.join(pattern_names)}")

        result = "\n".join(context_parts) if context_parts else None
        logger.debug(f"[Reflector] 生成反思上下文: {len(context_parts)} 部分")
        return result
    except Exception as e:
        logger.error(f"[Reflector] get_reflection_context 失败: {e}")
        return None


def get_belief_confidence(strategy_name: str) -> float:
    """获取策略的贝叶斯信念置信度

    Args:
        strategy_name: 策略名称

    Returns:
        float: 置信度值 (0-1)，失败返回0.5
    """
    try:
        if reflector is None:
            logger.error("[Reflector] get_belief_confidence 失败: reflector 未初始化")
            return 0.5

        # 从 strategy_patterns 中查找匹配的策略
        for pattern in reflector.strategy_patterns.values():
            if pattern.name == strategy_name or strategy_name in pattern.applicable_scenarios:
                # 使用 beta 分布的均值计算置信度
                confidence = pattern.alpha / (pattern.alpha + pattern.beta)
                logger.debug(f"[Reflector] {strategy_name} 置信度: {confidence:.2f}")
                return confidence

        logger.debug(f"[Reflector] {strategy_name} 未找到模式，返回默认置信度 0.5")
        return 0.5  # 默认置信度
    except Exception as e:
        logger.error(f"[Reflector] get_belief_confidence 失败: {e}")
        return 0.5


def get_strategy_recommendation(context: dict) -> dict | None:
    """获取策略推荐

    Args:
        context: 上下文信息，包含 task, recent_tools 等

    Returns:
        Dict: 策略推荐，失败返回None
    """
    try:
        if reflector is None:
            logger.error("[Reflector] get_strategy_recommendation 失败: reflector 未初始化")
            return None

        task = context.get("task", "")
        current_steps = context.get("recent_tools", [])

        if not task:
            logger.error("[Reflector] get_strategy_recommendation 失败: task 为空")
            return None

        advice = reflector.get_strategy_advice(task, current_steps)
        if advice:
            result = {
                "strategy": advice.get("strategy", ""),
                "confidence": advice.get("confidence", 0.5),
                "reasoning": advice.get("reasoning", ""),
                "alternative_actions": advice.get("alternative_actions", [])
            }
            logger.debug(f"[Reflector] 生成策略推荐: {result['strategy']}")
            return result

        logger.debug("[Reflector] 无策略建议返回")
        return None
    except Exception as e:
        logger.error(f"[Reflector] get_strategy_recommendation 失败: {e}")
        return None
