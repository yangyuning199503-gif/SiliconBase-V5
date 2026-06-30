#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""
AI行为分析器 - 深度分析AI的行为模式和学习趋势

这是一个高级行为分析模块，提供更深入的AI行为分析能力：
- 工具使用模式深度挖掘
- AI决策路径分析
- 学习效率评估
- 行为预测

使用方法:
    from core.behavior_analyzer import get_behavior_analyzer, AIBehaviorAnalyzer

    analyzer = get_behavior_analyzer()
    analysis = analyzer.analyze_tool_usage(execution_history)
    prediction = analyzer.predict_next_action(working_memory, execution_history)
"""

import logging  # 导入日志模块
import time  # 导入时间模块
from collections import Counter, defaultdict  # 导入计数器和默认字典
from dataclasses import dataclass  # 导入数据类装饰器
from datetime import datetime  # 导入日期时间类
from enum import Enum  # 导入枚举类
from typing import Any  # 导入类型注解

logger = logging.getLogger(__name__)  # 获取当前模块的日志记录器


class AnalysisType(Enum):  # 分析类型枚举
    """分析类型"""  # 类文档字符串
    TOOL_USAGE = "工具使用分析"  # 工具使用模式分析
    DECISION_PATH = "决策路径分析"  # 决策路径追踪分析
    LEARNING_EFFICIENCY = "学习效率分析"  # 学习效率评估
    ERROR_PATTERN = "错误模式分析"  # 错误模式识别
    INTENT_EVOLUTION = "意图演化分析"  # 意图演化追踪


class BehaviorTrend(Enum):  # 行为趋势枚举
    """行为趋势"""  # 类文档字符串
    IMPROVING = "持续改进"  # 性能持续提升
    STABLE = "稳定执行"  # 性能保持稳定
    DECLINING = "性能下降"  # 性能出现下降
    EXPLORING = "积极探索"  # 积极探索新工具
    STRUGGLING = "遇到困难"  # 执行遇到困难


@dataclass  # 数据类装饰器
class ToolUsagePattern:  # 工具使用模式数据类
    """工具使用模式"""  # 类文档字符串
    tool_id: str  # 工具ID
    frequency: int  # 使用频率
    success_rate: float  # 成功率
    avg_execution_time: float  # 平均执行时间
    common_params: dict[str, Any]  # 常用参数
    time_distribution: list[float]  # 使用时间的分布


@dataclass  # 数据类装饰器
class DecisionNode:  # 决策节点数据类
    """决策节点"""  # 类文档字符串
    step: int  # 步骤序号
    intent_type: str  # 意图类型
    tool_called: str | None  # 调用的工具（可能为None）
    context: dict[str, Any]  # 上下文信息
    outcome: str  # 结果（success/failure）
    alternatives: list[str]  # 可能的替代选择


@dataclass  # 数据类装饰器
class LearningMetrics:  # 学习指标数据类
    """学习指标"""  # 类文档字符串
    new_tools_learned: int  # 新学习的工具数
    mistake_rate: float  # 错误率
    adaptation_speed: float  # 适应新任务的速度
    skill_retention: float   # 技能保持率
    improvement_rate: float  # 改进速度


@dataclass  # 数据类装饰器
class BehaviorAnalysisResult:  # 行为分析结果数据类
    """行为分析结果"""  # 类文档字符串
    analysis_type: AnalysisType  # 分析类型
    timestamp: float  # 时间戳
    summary: str  # 摘要
    details: dict[str, Any]  # 详细信息
    recommendations: list[str]  # 建议列表
    confidence: float  # 置信度


@dataclass  # 数据类装饰器
class ActionPrediction:  # 行为预测结果数据类
    """行为预测结果"""  # 类文档字符串
    predicted_action: str  # 预测的动作
    predicted_tool: str | None  # 预测的工具（可能为None）
    confidence: float  # 置信度
    alternatives: list[tuple[str, float]]  # 备选动作及其概率
    reasoning: str  # 推理说明


class AIBehaviorAnalyzer:  # AI行为分析器主类
    """
    AI行为分析器

    提供深度的AI行为分析，包括：
    1. 工具使用模式分析
    2. 决策路径追踪
    3. 学习效率评估
    4. 错误模式识别
    5. 下一步行为预测
    """

    def __init__(self):  # 构造函数
        self._analysis_history: list[BehaviorAnalysisResult] = []  # 分析历史记录列表
        self._tool_usage_stats: dict[str, ToolUsagePattern] = {}  # 工具使用统计字典
        self._decision_paths: list[list[DecisionNode]] = []  # 决策路径列表
        self._error_patterns: list[dict[str, Any]] = []  # 错误模式列表
        self._learning_history: list[LearningMetrics] = []  # 学习历史列表
        self._max_history_size = 100  # 历史记录最大长度

        # 工具关系图：工具A -> [工具B, 工具C] 表示使用A后可能使用B或C  # 工具转换图
        self._tool_transition_graph: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))  # 嵌套默认字典

        logger.info("[AIBehaviorAnalyzer] AI行为分析器已初始化")  # 记录初始化日志

    async def analyze_tool_usage(self, execution_history: list[dict[str, Any]],  # 分析工具使用
                          detailed: bool = False) -> BehaviorAnalysisResult:  # 详细分析标志
        """
        分析AI的工具使用模式

        Args:
            execution_history: 执行历史记录
            detailed: 是否进行详细分析

        Returns:
            BehaviorAnalysisResult: 工具使用分析结果
        """
        if not execution_history:  # 如果执行历史为空
            return BehaviorAnalysisResult(  # 返回空结果
                analysis_type=AnalysisType.TOOL_USAGE,  # 分析类型
                timestamp=time.time(),  # 当前时间戳
                summary="暂无执行历史",  # 摘要
                details={},  # 空详情
                recommendations=["开始执行任务以收集行为数据"],  # 建议
                confidence=1.0  # 置信度100%
            )  # 返回结束

        # 提取工具调用记录  # 数据预处理
        tool_calls = [(h.get("tool"), h.get("result", {}), h.get("timestamp", 0))  # 提取元组
                      for h in execution_history if h.get("tool")]  # 只保留有工具的记录

        # 统计工具使用频率  # 频率统计
        tool_frequency = Counter(t[0] for t in tool_calls)  # 使用Counter统计

        # 计算每个工具的成功率  # 成功率计算
        tool_success = defaultdict(lambda: {"success": 0, "total": 0})  # 默认字典
        for tool_id, result, _ in tool_calls:  # 遍历工具调用
            tool_success[tool_id]["total"] += 1  # 总数+1
            if result.get("success", False):  # 如果成功
                tool_success[tool_id]["success"] += 1  # 成功数+1

        # 分析工具调用序列  # 序列分析
        sequences = self._extract_tool_sequences(tool_calls)  # 提取序列

        # 更新工具转换图  # 转换图更新
        self._update_transition_graph(tool_calls)  # 调用更新方法

        # 识别高频模式  # 模式识别
        frequent_patterns = self._find_frequent_patterns(sequences)  # 查找频繁模式

        # 计算工具多样性  # 多样性计算
        diversity = self._calculate_diversity(tool_frequency)  # 计算多样性指数

        details = {  # 详情字典
            "total_calls": len(tool_calls),  # 总调用次数
            "unique_tools": len(tool_frequency),  # 不同工具数
            "tool_frequency": dict(tool_frequency),  # 频率字典
            "tool_success_rates": {  # 成功率字典
                tool: stats["success"] / stats["total"]  # 计算成功率
                for tool, stats in tool_success.items()  # 遍历统计
            },  # 成功率结束
            "frequent_sequences": frequent_patterns,  # 频繁序列
            "diversity_index": diversity,  # 多样性指数
        }  # 详情结束

        # 详细分析  # 详细模式
        if detailed:  # 如果需要详细分析
            details["temporal_patterns"] = self._analyze_temporal_patterns(tool_calls)  # 时间模式
            details["param_usage"] = self._analyze_param_patterns(execution_history)  # 参数使用模式

        # 生成建议  # 建议生成
        recommendations = self._generate_tool_recommendations(details)  # 调用生成方法

        # 构建摘要  # 摘要构建
        top_tools = tool_frequency.most_common(3)  # 获取前3个常用工具
        summary = f"共使用{len(tool_frequency)}种工具，调用{len(tool_calls)}次，最常用: {', '.join(f'{t[0]}({t[1]}次)' for t in top_tools)}"  # 格式化摘要

        result = BehaviorAnalysisResult(  # 创建结果对象
            analysis_type=AnalysisType.TOOL_USAGE,  # 分析类型
            timestamp=time.time(),  # 时间戳
            summary=summary,  # 摘要
            details=details,  # 详情
            recommendations=recommendations,  # 建议
            confidence=min(0.5 + len(tool_calls) * 0.05, 0.95)  # 基于数据量计算置信度，上限0.95
        )  # 创建结束

        self._add_to_history(result)  # 添加到历史
        logger.info(f"[AIBehaviorAnalyzer] 工具使用分析完成: {summary}")  # 记录日志

        return result  # 返回结果

    def analyze_decision_path(self, execution_history: list[dict[str, Any]],  # 分析决策路径
                             user_instruction: str) -> list[DecisionNode]:  # 用户指令
        """
        分析AI的决策路径

        Args:
            execution_history: 执行历史记录
            user_instruction: 用户原始指令

        Returns:
            List[DecisionNode]: 决策路径节点列表
        """
        decision_path = []  # 决策路径列表

        for i, record in enumerate(execution_history):  # 遍历执行历史
            node = DecisionNode(  # 创建决策节点
                step=i + 1,  # 步骤序号（从1开始）
                intent_type=record.get("intent_type", "UNKNOWN"),  # 意图类型
                tool_called=record.get("tool"),  # 调用的工具
                context={  # 上下文信息
                    "params": record.get("params", {}),  # 参数
                    "user_instruction": user_instruction,  # 用户指令
                    "stage": record.get("stage", "unknown")  # 阶段
                },  # 上下文结束
                outcome="success" if record.get("result", {}).get("success", False) else "failure",  # 结果
                alternatives=[]  # 备选方案（可扩展）
            )  # 节点创建结束
            decision_path.append(node)  # 添加到路径

        self._decision_paths.append(decision_path)  # 添加到历史
        if len(self._decision_paths) > self._max_history_size:  # 如果超过最大长度
            self._decision_paths.pop(0)  # 移除最早的记录

        return decision_path  # 返回决策路径

    def predict_next_action(self, working_memory: Any,  # 预测下一步行为
                           execution_history: list[dict[str, Any]]) -> ActionPrediction:  # 执行历史
        """
        预测AI下一步可能的行为

        Args:
            working_memory: 工作记忆对象
            execution_history: 执行历史记录

        Returns:
            ActionPrediction: 行为预测结果
        """
        if not execution_history:  # 如果执行历史为空
            return ActionPrediction(  # 返回默认预测
                predicted_action="等待用户输入",  # 预测动作
                predicted_tool=None,  # 无预测工具
                confidence=0.5,  # 置信度50%
                alternatives=[("开始分析任务", 0.3), ("请求更多信息", 0.2)],  # 备选方案
                reasoning="没有执行历史，无法预测"  # 推理说明
            )  # 返回结束

        # 获取最近的工具调用  # 最近工具
        recent_tools = [h.get("tool") for h in execution_history[-3:] if h.get("tool")]  # 最近3个工具
        last_tool = recent_tools[-1] if recent_tools else None  # 最后一个工具

        # 基于转换图预测  # 转换图预测
        predictions = []  # 预测列表
        if last_tool and last_tool in self._tool_transition_graph:  # 如果有转换记录
            transitions = self._tool_transition_graph[last_tool]  # 获取转换统计
            total = sum(transitions.values())  # 计算总数
            if total > 0:  # 如果有转换数据
                for next_tool, count in transitions.most_common(3):  # 取前3个
                    prob = count / total  # 计算概率
                    predictions.append((next_tool, prob))  # 添加到预测列表

        # 基于任务阶段预测  # 阶段预测
        stage = getattr(working_memory, 'query_stage', 'layer1')  # 获取当前阶段
        goal = getattr(working_memory, 'goal', '')  # 获取目标

        # 分析当前目标关键词  # 关键词提取
        self._extract_goal_keywords(goal)  # 提取目标关键词

        # 构建推理说明  # 推理构建
        reasoning_parts = []  # 推理片段列表
        if last_tool:  # 如果有上一个工具
            reasoning_parts.append(f"上一步使用了{last_tool}")  # 添加上一步信息
        if predictions:  # 如果有预测
            reasoning_parts.append(f"历史数据显示接下来常用: {predictions[0][0]}")  # 添加预测信息
        if stage != 'layer1':  # 如果不是初始阶段
            reasoning_parts.append(f"当前处于{stage}阶段")  # 添加阶段信息

        reasoning = "。".join(reasoning_parts) if reasoning_parts else "基于任务目标进行预测"  # 连接推理

        # 选择最高概率的预测  # 选择预测
        if predictions:  # 如果有预测结果
            predicted_tool = predictions[0][0]  # 选择概率最高的
            confidence = predictions[0][1]  # 置信度为概率
            alternatives = predictions[1:]  # 备选为其余选项
        else:  # 无预测结果
            predicted_tool = None  # 无预测工具
            confidence = 0.3  # 低置信度
            alternatives = []  # 无备选

        return ActionPrediction(  # 返回预测结果
            predicted_action=f"调用{predicted_tool}" if predicted_tool else "返回最终结果",  # 预测动作
            predicted_tool=predicted_tool,  # 预测工具
            confidence=confidence,  # 置信度
            alternatives=alternatives,  # 备选方案
            reasoning=reasoning  # 推理说明
        )  # 返回结束

    def analyze_learning_efficiency(self, execution_history: list[dict[str, Any]],  # 分析学习效率
                                    task_completion_times: list[float] = None) -> LearningMetrics:  # 任务完成时间
        """
        分析AI的学习效率

        Args:
            execution_history: 执行历史记录
            task_completion_times: 任务完成时间列表

        Returns:
            LearningMetrics: 学习指标
        """
        if not execution_history:  # 如果执行历史为空
            return LearningMetrics(  # 返回默认指标
                new_tools_learned=0,  # 0个新工具
                mistake_rate=0.0,  # 0%错误率
                adaptation_speed=0.0,  # 0适应速度
                skill_retention=0.0,  # 0技能保持
                improvement_rate=0.0  # 0改进速度
            )  # 返回结束

        # 统计新工具学习  # 新工具统计
        all_tools = set()  # 已见工具集合
        new_tools_per_session = []  # 新工具列表
        for h in execution_history:  # 遍历执行历史
            tool = h.get("tool")  # 获取工具
            if tool and tool not in all_tools:  # 如果是新工具
                all_tools.add(tool)  # 添加到已见集合
                new_tools_per_session.append(tool)  # 添加到新工具列表

        # 计算错误率  # 错误率计算
        results = [h.get("result", {}) for h in execution_history]  # 获取所有结果
        failures = sum(1 for r in results if not r.get("success", True))  # 统计失败数
        mistake_rate = failures / len(results) if results else 0.0  # 计算错误率

        # 计算改进速度（基于任务完成时间趋势）  # 改进速度计算
        improvement_rate = 0.0  # 默认0
        if task_completion_times and len(task_completion_times) >= 2:  # 如果有足够数据
            # 简单线性趋势  # 趋势计算
            first_half = sum(task_completion_times[:len(task_completion_times)//2])  # 前半段平均
            second_half = sum(task_completion_times[len(task_completion_times)//2:])  # 后半段平均
            if first_half > 0:  # 避免除0
                improvement_rate = (first_half - second_half) / first_half  # 计算改进率

        # 适应速度：基于错误恢复时间  # 适应速度计算
        adaptation_speed = self._calculate_adaptation_speed(execution_history)  # 调用计算方法

        # 技能保持率：成功工具的重复使用比例  # 技能保持率计算
        successful_tools = set()  # 成功工具集合
        repeated_successful = 0  # 重复成功计数
        for h in execution_history:  # 遍历执行历史
            tool = h.get("tool")  # 获取工具
            success = h.get("result", {}).get("success", False)  # 获取成功状态
            if tool and success:  # 如果成功
                if tool in successful_tools:  # 如果已存在（重复）
                    repeated_successful += 1  # 重复计数+1
                successful_tools.add(tool)  # 添加到集合
        skill_retention = repeated_successful / len(successful_tools) if successful_tools else 0.0  # 计算保持率

        metrics = LearningMetrics(  # 创建指标对象
            new_tools_learned=len(new_tools_per_session),  # 新工具数
            mistake_rate=mistake_rate,  # 错误率
            adaptation_speed=adaptation_speed,  # 适应速度
            skill_retention=skill_retention,  # 技能保持率
            improvement_rate=improvement_rate  # 改进速度
        )  # 创建结束

        self._learning_history.append(metrics)  # 添加到学习历史

        return metrics  # 返回指标

    def analyze_error_patterns(self, execution_history: list[dict[str, Any]]) -> BehaviorAnalysisResult:  # 分析错误模式
        """
        分析错误模式

        Args:
            execution_history: 执行历史记录

        Returns:
            BehaviorAnalysisResult: 错误模式分析结果
        """
        if not execution_history:  # 如果执行历史为空
            return BehaviorAnalysisResult(  # 返回默认结果
                analysis_type=AnalysisType.ERROR_PATTERN,  # 分析类型
                timestamp=time.time(),  # 时间戳
                summary="暂无执行历史",  # 摘要
                details={},  # 空详情
                recommendations=["继续执行任务以收集错误数据"],  # 建议
                confidence=1.0  # 置信度100%
            )  # 返回结束

        # 收集错误记录  # 错误收集
        errors = []  # 错误列表
        for i, h in enumerate(execution_history):  # 遍历执行历史
            result = h.get("result", {})  # 获取结果
            if not result.get("success", True):  # 如果失败
                errors.append({  # 添加错误记录
                    "step": i + 1,  # 步骤
                    "tool": h.get("tool"),  # 工具
                    "error_code": result.get("error_code", "UNKNOWN"),  # 错误代码
                    "error_message": result.get("user_message", ""),  # 错误消息
                    "params": h.get("params", {})  # 参数
                })  # 添加结束

        if not errors:  # 如果没有错误
            return BehaviorAnalysisResult(  # 返回良好结果
                analysis_type=AnalysisType.ERROR_PATTERN,  # 分析类型
                timestamp=time.time(),  # 时间戳
                summary="未检测到错误，执行良好",  # 摘要
                details={"total_errors": 0},  # 详情
                recommendations=["保持当前执行策略"],  # 建议
                confidence=1.0  # 置信度100%
            )  # 返回结束

        # 错误类型统计  # 类型统计
        error_types = Counter(e["error_code"] for e in errors)  # 统计错误类型
        error_tools = Counter(e["tool"] for e in errors)  # 统计错误工具

        # 识别错误模式  # 模式识别
        patterns = []  # 模式列表

        # 模式1: 连续相同错误  # 重复错误模式
        for error_code, count in error_types.items():  # 遍历错误类型
            if count >= 3:  # 如果重复>=3次
                patterns.append(f"重复错误'{error_code}'出现{count}次")  # 添加模式

        # 模式2: 特定工具频繁出错  # 工具错误模式
        for tool, count in error_tools.items():  # 遍历工具
            tool_calls = sum(1 for h in execution_history if h.get("tool") == tool)  # 统计调用次数
            if tool_calls > 0 and count / tool_calls > 0.5:  # 如果错误率>50%
                patterns.append(f"工具'{tool}'错误率过高({count}/{tool_calls})")  # 添加模式

        details = {  # 详情字典
            "total_errors": len(errors),  # 总错误数
            "error_types": dict(error_types),  # 错误类型分布
            "error_tools": dict(error_tools),  # 错误工具分布
            "patterns": patterns,  # 识别到的模式
            "error_rate": len(errors) / len(execution_history)  # 错误率
        }  # 详情结束

        # 生成建议  # 建议生成
        recommendations = []  # 建议列表
        if "TIMEOUT" in error_types:  # 如果有超时错误
            recommendations.append("增加工具执行的超时时间")  # 建议1
        if "TOOL_NOT_FOUND" in error_types:  # 如果有工具未找到错误
            recommendations.append("检查工具配置，确保所有工具已正确安装")  # 建议2
        if patterns:  # 如果有识别到模式
            recommendations.append("建议针对高频错误工具进行专项学习")  # 建议3

        summary = f"检测到{len(errors)}个错误，主要类型: {', '.join(f'{k}({v}次)' for k, v in error_types.most_common(3))}"  # 摘要

        result = BehaviorAnalysisResult(  # 创建结果对象
            analysis_type=AnalysisType.ERROR_PATTERN,  # 分析类型
            timestamp=time.time(),  # 时间戳
            summary=summary,  # 摘要
            details=details,  # 详情
            recommendations=recommendations,  # 建议
            confidence=min(0.5 + len(errors) * 0.1, 0.95)  # 基于错误数计算置信度
        )  # 创建结束

        self._add_to_history(result)  # 添加到历史
        self._error_patterns.append(details)  # 添加到错误模式

        logger.info(f"[AIBehaviorAnalyzer] 错误模式分析完成: {summary}")  # 记录日志

        return result  # 返回结果

    def get_behavior_trend(self, window_size: int = 10) -> BehaviorTrend:  # 获取行为趋势
        """
        获取行为趋势

        Args:
            window_size: 分析窗口大小

        Returns:
            BehaviorTrend: 行为趋势
        """
        if len(self._learning_history) < window_size:  # 如果历史不足
            return BehaviorTrend.EXPLORING  # 返回探索状态

        recent = self._learning_history[-window_size:]  # 获取最近窗口

        # 计算趋势指标  # 指标计算
        mistake_rates = [m.mistake_rate for m in recent]  # 错误率列表
        improvement_rates = [m.improvement_rate for m in recent]  # 改进率列表

        # 错误率下降  # 改进判断
        if mistake_rates[-1] < mistake_rates[0] * 0.8:  # 如果错误率明显下降
            return BehaviorTrend.IMPROVING  # 返回持续改进

        # 改进速度为正  # 改进判断2
        if sum(improvement_rates) > 0:  # 如果总改进率为正
            return BehaviorTrend.IMPROVING  # 返回持续改进

        # 错误率稳定  # 稳定判断
        if abs(mistake_rates[-1] - mistake_rates[0]) < 0.1:  # 如果错误率变化<10%
            return BehaviorTrend.STABLE  # 返回稳定执行

        # 错误率上升  # 下降判断
        if mistake_rates[-1] > mistake_rates[0] * 1.2:  # 如果错误率明显上升
            return BehaviorTrend.DECLINING  # 返回性能下降

        # 探索新工具  # 探索判断
        new_tools = sum(m.new_tools_learned for m in recent)  # 统计新工具数
        if new_tools > window_size * 0.5:  # 如果新工具数>窗口大小的一半
            return BehaviorTrend.EXPLORING  # 返回积极探索

        return BehaviorTrend.STABLE  # 默认返回稳定

    def generate_behavior_report(self) -> dict[str, Any]:  # 生成行为报告
        """
        生成完整的行为分析报告

        Returns:
            Dict: 行为分析报告
        """
        if not self._analysis_history:  # 如果无分析历史
            return {"message": "暂无分析数据"}  # 返回提示

        # 统计各类分析的数量  # 类型统计
        type_counts = Counter(a.analysis_type for a in self._analysis_history)  # 统计类型

        # 获取趋势  # 趋势获取
        trend = self.get_behavior_trend()  # 获取当前趋势

        # 汇总建议  # 建议汇总
        all_recommendations = []  # 所有建议列表
        for analysis in self._analysis_history[-10:]:  # 最近10次分析
            all_recommendations.extend(analysis.recommendations)  # 添加建议

        # 去重  # 去重处理
        unique_recommendations = list(set(all_recommendations))  # 去重

        return {  # 返回报告
            "generated_at": datetime.now().isoformat(),  # 生成时间
            "total_analyses": len(self._analysis_history),  # 总分析次数
            "analysis_types": {t.value: c for t, c in type_counts.items()},  # 分析类型分布
            "current_trend": trend.value,  # 当前趋势
            "recommendations": unique_recommendations[:10],  # 建议列表（限制10条）
            "learning_progress": self._get_learning_progress(),  # 学习进度
        }  # 返回结束

    # =============== 辅助方法 ===============  # 辅助方法区域

    def _extract_tool_sequences(self, tool_calls: list[tuple]) -> list[list[str]]:  # 提取工具序列
        """提取工具调用序列"""  # 方法文档字符串
        sequences = []  # 序列列表
        current_seq = []  # 当前序列

        for tool_id, _, _ in tool_calls:  # 遍历工具调用
            if not current_seq or current_seq[-1] != tool_id:  # 如果不重复
                current_seq.append(tool_id)  # 添加到当前序列

        # 提取固定长度的序列  # 固定长度提取
        for length in [2, 3]:  # 提取2步和3步序列
            for i in range(len(current_seq) - length + 1):  # 滑动窗口
                sequences.append(current_seq[i:i+length])  # 添加子序列

        return sequences  # 返回序列列表

    def _update_transition_graph(self, tool_calls: list[tuple]):  # 更新转换图
        """更新工具转换图"""  # 方法文档字符串
        for i in range(len(tool_calls) - 1):  # 遍历（除了最后一个）
            current_tool = tool_calls[i][0]  # 当前工具
            next_tool = tool_calls[i + 1][0]  # 下一个工具
            if current_tool and next_tool:  # 如果都有效
                self._tool_transition_graph[current_tool][next_tool] += 1  # 转换计数+1

    def _find_frequent_patterns(self, sequences: list[list[str]]) -> list[dict[str, Any]]:  # 查找频繁模式
        """查找频繁出现的序列模式"""  # 方法文档字符串
        pattern_counts = Counter(tuple(seq) for seq in sequences)  # 统计模式频率
        frequent = []  # 频繁模式列表

        for pattern, count in pattern_counts.most_common(5):  # 取前5个
            if count >= 2:  # 至少出现2次
                frequent.append({  # 添加模式
                    "pattern": list(pattern),  # 模式序列
                    "frequency": count,  # 频率
                    "support": count / len(sequences) if sequences else 0  # 支持度
                })  # 添加结束

        return frequent  # 返回频繁模式

    def _calculate_diversity(self, tool_frequency: Counter) -> float:  # 计算多样性
        """计算工具多样性指数（Simpson指数）"""  # 方法文档字符串
        total = sum(tool_frequency.values())  # 总使用次数
        if total == 0:  # 如果为0
            return 0.0  # 返回0

        proportions = [count / total for count in tool_frequency.values()]  # 计算比例
        return 1 - sum(p * p for p in proportions)  # 计算Simpson指数

    def _analyze_temporal_patterns(self, tool_calls: list[tuple]) -> dict[str, Any]:  # 分析时间模式
        """分析时间模式"""  # 方法文档字符串
        if len(tool_calls) < 2:  # 如果数据不足
            return {}  # 返回空

        intervals = []  # 间隔列表
        for i in range(1, len(tool_calls)):  # 从第二个开始
            interval = tool_calls[i][2] - tool_calls[i-1][2]  # 计算间隔
            intervals.append(interval)  # 添加到列表

        return {  # 返回统计
            "avg_interval": sum(intervals) / len(intervals) if intervals else 0,  # 平均间隔
            "max_interval": max(intervals) if intervals else 0,  # 最大间隔
            "min_interval": min(intervals) if intervals else 0,  # 最小间隔
        }  # 返回结束

    def _analyze_param_patterns(self, execution_history: list[dict[str, Any]]) -> dict[str, Any]:  # 分析参数模式
        """分析参数使用模式"""  # 方法文档字符串
        param_usage = defaultdict(lambda: defaultdict(int))  # 默认字典

        for h in execution_history:  # 遍历执行历史
            tool_id = h.get("tool")  # 获取工具ID
            params = h.get("params", {})  # 获取参数
            if tool_id and params:  # 如果有效
                for key in params:  # 遍历参数名
                    param_usage[tool_id][key] += 1  # 计数+1

        return dict(param_usage)  # 返回字典

    def _generate_tool_recommendations(self, details: dict[str, Any]) -> list[str]:  # 生成工具建议
        """生成工具使用建议"""  # 方法文档字符串
        recommendations = []  # 建议列表

        # 基于多样性  # 多样性建议
        if details.get("diversity_index", 0) < 0.3:  # 如果多样性低
            recommendations.append("工具使用较为单一，建议探索更多工具组合")  # 建议1

        # 基于成功率  # 成功率建议
        success_rates = details.get("tool_success_rates", {})  # 获取成功率
        low_success_tools = [tool for tool, rate in success_rates.items() if rate < 0.5]  # 筛选低成功率
        if low_success_tools:  # 如果有
            recommendations.append(f"工具{', '.join(low_success_tools)}成功率较低，需要学习优化")  # 建议2

        # 基于高频模式  # 模式建议
        frequent_sequences = details.get("frequent_sequences", [])  # 获取频繁序列
        if len(frequent_sequences) >= 3:  # 如果有足够多
            recommendations.append("检测到稳定的工具调用模式，建议记录为经验")  # 建议3

        return recommendations if recommendations else ["工具使用模式正常"]  # 返回建议或默认值

    def _extract_goal_keywords(self, goal: str) -> list[str]:  # 提取目标关键词
        """提取目标关键词"""  # 方法文档字符串
        keywords = []  # 关键词列表
        action_words = ["打开", "搜索", "创建", "编辑", "删除", "查询", "分析"]  # 动作词
        for word in action_words:  # 遍历动作词
            if word in goal:  # 如果包含
                keywords.append(word)  # 添加到列表
        return keywords  # 返回关键词

    def _calculate_adaptation_speed(self, execution_history: list[dict[str, Any]]) -> float:  # 计算适应速度
        """计算适应速度"""  # 方法文档字符串
        # 简化计算：基于错误恢复的平均时间  # 计算方法
        error_recovery_times = []  # 恢复时间列表
        last_error_time = None  # 上次错误时间

        for h in execution_history:  # 遍历执行历史
            result = h.get("result", {})  # 获取结果
            timestamp = h.get("timestamp", 0)  # 获取时间戳

            if not result.get("success", True):  # 如果失败
                last_error_time = timestamp  # 记录错误时间
            elif last_error_time:  # 如果成功且之前有错误
                recovery_time = timestamp - last_error_time  # 计算恢复时间
                error_recovery_times.append(recovery_time)  # 添加到列表
                last_error_time = None  # 重置

        if error_recovery_times:  # 如果有恢复时间
            avg_recovery = sum(error_recovery_times) / len(error_recovery_times)  # 计算平均
            # 归一化到0-1范围（假设正常恢复时间在5秒内）  # 归一化
            return max(0, 1 - avg_recovery / 5)  # 返回适应速度

        return 0.5  # 默认值

    def _add_to_history(self, result: BehaviorAnalysisResult):  # 添加到历史
        """添加分析结果到历史"""  # 方法文档字符串
        self._analysis_history.append(result)  # 添加到列表
        if len(self._analysis_history) > self._max_history_size:  # 如果超过最大长度
            self._analysis_history.pop(0)  # 移除最早的

    def _get_learning_progress(self) -> dict[str, Any]:  # 获取学习进度
        """获取学习进度"""  # 方法文档字符串
        if not self._learning_history:  # 如果无历史
            return {"status": "未开始"}  # 返回状态

        recent = self._learning_history[-10:]  # 最近10次
        return {  # 返回进度
            "total_sessions": len(self._learning_history),  # 总会话数
            "avg_mistake_rate": sum(m.mistake_rate for m in recent) / len(recent),  # 平均错误率
            "avg_adaptation_speed": sum(m.adaptation_speed for m in recent) / len(recent),  # 平均适应速度
            "total_new_tools": sum(m.new_tools_learned for m in self._learning_history),  # 总新工具数
        }  # 返回结束


# =============== 全局单例 ===============  # 全局单例区域

_behavior_analyzer: AIBehaviorAnalyzer | None = None  # 全局分析器实例


def get_behavior_analyzer() -> AIBehaviorAnalyzer:  # 获取分析器函数
    """获取全局AIBehaviorAnalyzer实例"""  # 函数文档字符串
    global _behavior_analyzer  # 引用全局变量
    if _behavior_analyzer is None:  # 如果未创建
        _behavior_analyzer = AIBehaviorAnalyzer()  # 创建实例
    return _behavior_analyzer  # 返回实例


def reset_behavior_analyzer():  # 重置分析器函数
    """重置全局实例（主要用于测试）"""  # 函数文档字符串
    global _behavior_analyzer  # 引用全局变量
    _behavior_analyzer = None  # 重置为None


# =============== 便捷函数 ===============  # 便捷函数区域

def quick_analyze(execution_history: list[dict[str, Any]]) -> dict[str, Any]:  # 快速分析函数
    """
    快速分析函数

    Args:
        execution_history: 执行历史记录

    Returns:
        Dict: 简化版分析结果
    """
    analyzer = get_behavior_analyzer()  # 获取分析器
    result = analyzer.analyze_tool_usage(execution_history)  # 执行分析
    return {  # 返回简化结果
        "summary": result.summary,  # 摘要
        "recommendations": result.recommendations,  # 建议
        "confidence": result.confidence  # 置信度
    }  # 返回结束


def predict_next(working_memory: Any, execution_history: list[dict[str, Any]]) -> str:  # 预测函数
    """
    快速预测函数

    Args:
        working_memory: 工作记忆对象
        execution_history: 执行历史记录

    Returns:
        str: 预测的下一步动作
    """
    analyzer = get_behavior_analyzer()  # 获取分析器
    prediction = analyzer.predict_next_action(working_memory, execution_history)  # 执行预测
    return prediction.predicted_action  # 返回预测动作


# =============================================================================  # 分隔线
# 【文件总结】  # 总结区域标题
# =============================================================================  # 分隔线
# 文件角色：AI行为分析器，提供深度的AI行为模式分析和学习评估  # 角色说明
# 核心功能：  # 功能列表
#   1. 工具使用分析 - 统计频率、成功率、多样性，识别频繁模式  # 功能1
#   2. 决策路径分析 - 追踪AI的决策过程，记录决策节点  # 功能2
#   3. 行为预测 - 基于工具转换图预测下一步可能的行为  # 功能3
#   4. 学习效率评估 - 计算新工具学习、错误率、适应速度、技能保持率  # 功能4
#   5. 错误模式识别 - 识别重复错误、工具错误率过高、异常模式  # 功能5
#   6. 趋势分析 - 判断AI处于改进/稳定/下降/探索/困难状态  # 功能6
# 核心算法：  # 算法说明
#   - Simpson多样性指数：计算工具使用多样性  # 算法1
#   - 工具转换图：记录工具A之后使用工具B的概率  # 算法2
#   - 频繁序列挖掘：识别常用的工具调用序列  # 算法3
#   - 错误恢复时间：计算从错误到成功的平均时间  # 算法4
# 关联文件：  # 关联说明
#   - core/behavior_recognizer.py: 行为识别器（基础行为分类）  # 关联1
#   - core/risk_level.py: 风险等级（趋势分析引用）  # 关联2
#   - core/agent_loop.py: Agent主循环（提供execution_history）  # 关联3
# 达到效果：  # 效果说明
#   - 量化AI的学习能力和执行效率  # 效果1
#   - 识别AI的行为模式和改进空间  # 效果2
#   - 预测AI下一步行为，优化任务规划  # 效果3
#   - 为AI自我改进提供数据支持  # 效果4
# =============================================================================  # 分隔线结束
