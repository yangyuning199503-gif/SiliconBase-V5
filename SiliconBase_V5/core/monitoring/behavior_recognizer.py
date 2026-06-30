#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""
AI行为识别器 - 分析AI的工具调用模式和行为特征

这个模块负责分析AI的执行历史，识别AI的行为模式，评估风险等级，
并提供相应的建议动作。它是精准抓取系统的重要组成部分。

使用方法:
    from core.behavior_recognizer import get_behavior_recognizer, AIBehavior, BehaviorType

    recognizer = get_behavior_recognizer()
    behavior = recognizer.analyze(execution_history, user_instruction)
    print(f"行为类型: {behavior.behavior_type}")
    print(f"风险等级: {behavior.risk_level}")
    print(f"建议动作: {behavior.suggested_action}")
"""

import logging  # 导入日志模块
from collections import Counter  # 导入计数器
from dataclasses import dataclass, field  # 导入数据类装饰器
from enum import Enum  # 导入枚举类
from typing import Any  # 导入类型注解

from ..safety.risk_level import RiskLevel  # 导入风险等级枚举

logger = logging.getLogger(__name__)  # 获取当前模块的日志记录器


class BehaviorType(Enum):  # AI行为类型枚举
    """AI行为类型"""  # 类文档字符串
    SIMPLE_EXECUTION = "简单执行型"    # 只使用1个或更少工具
    GOAL_ORIENTED = "目标型"          # 使用2个工具，有明确目标
    EXPLORATORY = "探索型"            # 使用3个或以上不同工具
    REPETITIVE = "重复型"             # 重复调用相同工具
    LOOPING = "循环型"                # 出现循环调用模式
    RISKY = "风险型"                  # 涉及高风险操作
    LEARNING = "学习型"               # 正在学习新工具
    OPTIMAL = "最优型"                # 表现出高效执行模式


@dataclass  # 数据类装饰器
class AIBehavior:  # AI行为特征数据类
    """
    AI行为特征

    Attributes:
        behavior_type: 行为类型（探索型、目标型等）
        tool_usage_pattern: 工具使用模式列表
        risk_level: 风险等级
        suggested_action: 建议动作
        confidence: 行为识别置信度（0-1）
        details: 详细分析信息
    """
    behavior_type: str  # 行为类型字符串
    tool_usage_pattern: list[str]  # 工具使用模式列表
    risk_level: str  # 风险等级字符串
    suggested_action: str  # 建议动作字符串
    confidence: float = 0.0  # 置信度，默认0
    details: dict[str, Any] = field(default_factory=dict)  # 详情字典，默认空


@dataclass  # 数据类装饰器
class BehaviorMetrics:  # 行为指标数据类
    """行为指标"""  # 类文档字符串
    total_tools_used: int = 0          # 使用的工具总数
    unique_tools: int = 0              # 不同工具数量
    tool_diversity: float = 0.0        # 工具多样性指数
    repeat_ratio: float = 0.0          # 重复调用比例
    success_rate: float = 0.0          # 成功率
    avg_execution_time: float = 0.0    # 平均执行时间
    pattern_detected: str | None = None  # 检测到的模式


class BehaviorRecognizer:  # 行为识别器主类
    """
    AI行为识别器

    通过分析AI的执行历史，识别AI的行为模式，评估风险等级，
    并生成相应的建议动作。
    """

    # 高风险工具列表  # 高风险工具集合
    HIGH_RISK_TOOLS = {  # 高风险工具
        'file_delete', 'process_kill', 'system_shutdown',  # 文件删除、结束进程、关机
        'registry_edit', 'network_disconnect', 'data_clear'  # 注册表编辑、断网、数据清除
    }  # 高风险集合结束

    # 中风险工具列表  # 中风险工具集合
    MEDIUM_RISK_TOOLS = {  # 中风险工具
        'file_write', 'clipboard_set', 'window_close',  # 文件写入、剪贴板、关闭窗口
        'keyboard_input', 'mouse_click'  # 键盘输入、鼠标点击
    }  # 中风险集合结束

    def __init__(self):  # 构造函数
        self._behavior_history: list[AIBehavior] = []  # 行为历史列表
        self._max_history_size = 100  # 历史最大长度
        logger.info("[BehaviorRecognizer] 行为识别器已初始化")  # 记录初始化日志

    async def analyze(self, execution_history: list[dict[str, Any]],  # 分析行为
                user_instruction: str) -> AIBehavior:  # 用户指令
        """
        分析AI行为

        Args:
            execution_history: 执行历史记录列表
            user_instruction: 用户原始指令

        Returns:
            AIBehavior: 分析得到的行为特征
        """
        if not execution_history:  # 如果执行历史为空
            return AIBehavior(  # 返回默认行为
                behavior_type=BehaviorType.SIMPLE_EXECUTION.value,  # 简单执行型
                tool_usage_pattern=[],  # 空工具列表
                risk_level=RiskLevel.LOW.value,  # 低风险
                suggested_action="等待用户输入",  # 建议等待
                confidence=1.0  # 置信度100%
            )  # 返回结束

        # 提取工具使用信息  # 数据提取
        tools_used = [h.get("tool") for h in execution_history if h.get("tool")]  # 提取工具
        results = [h.get("result", {}) for h in execution_history]  # 提取结果

        # 计算行为指标  # 指标计算
        metrics = self._calculate_metrics(tools_used, results, execution_history)  # 调用计算方法

        # 判断行为类型  # 类型判断
        behavior_type = self._determine_behavior_type(metrics, tools_used)  # 调用判断方法

        # 计算风险等级  # 风险计算
        risk_level = self._calculate_risk(tools_used, results, metrics)  # 调用计算方法

        # 生成建议  # 建议生成
        suggested_action = self._generate_suggestion(behavior_type, risk_level, metrics)  # 调用生成方法

        # 计算置信度  # 置信度计算
        confidence = self._calculate_confidence(metrics)  # 调用计算方法

        behavior = AIBehavior(  # 创建行为对象
            behavior_type=behavior_type,  # 行为类型
            tool_usage_pattern=tools_used,  # 工具使用模式
            risk_level=risk_level,  # 风险等级
            suggested_action=suggested_action,  # 建议动作
            confidence=confidence,  # 置信度
            details={  # 详情字典
                "metrics": metrics,  # 指标
                "user_instruction": user_instruction,  # 用户指令
                "history_length": len(execution_history)  # 历史长度
            }  # 详情结束
        )  # 创建结束

        # 记录行为历史  # 历史记录
        self._add_to_history(behavior)  # 添加到历史

        logger.info(f"[BehaviorRecognizer] 行为分析: type={behavior_type}, risk={risk_level}")  # 记录日志

        return behavior  # 返回行为对象

    def _calculate_metrics(self, tools: list[str],  # 计算行为指标
                          results: list[dict],  # 结果列表
                          history: list[dict]) -> BehaviorMetrics:  # 执行历史
        """计算行为指标"""  # 方法文档字符串
        metrics = BehaviorMetrics()  # 创建指标对象

        if not tools:  # 如果无工具
            return metrics  # 返回默认指标

        # 基本统计  # 基础统计
        metrics.total_tools_used = len(tools)  # 总工具数
        metrics.unique_tools = len(set(tools))  # 不同工具数

        # 工具多样性（使用Simpson多样性指数）  # 多样性计算
        if metrics.total_tools_used > 0:  # 避免除0
            tool_counts = Counter(tools)  # 统计工具频率
            proportions = [count / metrics.total_tools_used for count in tool_counts.values()]  # 计算比例
            metrics.tool_diversity = 1 - sum(p * p for p in proportions)  # Simpson指数

        # 重复调用比例  # 重复比例计算
        if metrics.total_tools_used > 1:  # 如果有多于1个工具
            tool_counts = Counter(tools)  # 统计频率
            repeats = sum(1 for count in tool_counts.values() if count > 1)  # 统计重复工具数
            metrics.repeat_ratio = repeats / len(tool_counts)  # 计算比例

        # 成功率  # 成功率计算
        if results:  # 如果有结果
            successes = sum(1 for r in results if r.get("success", False))  # 统计成功数
            metrics.success_rate = successes / len(results)  # 计算成功率

        # 检测循环模式  # 模式检测
        metrics.pattern_detected = self._detect_loop_pattern(tools)  # 调用检测方法

        return metrics  # 返回指标

    def _detect_loop_pattern(self, tools: list[str]) -> str | None:  # 检测循环模式
        """检测循环调用模式"""  # 方法文档字符串
        if len(tools) < 4:  # 如果工具数不足
            return None  # 返回None

        # 检测简单循环（A→B→A→B）  # 简单循环检测
        for cycle_len in range(2, min(len(tools) // 2 + 1, 5)):  # 尝试2-4的循环长度
            is_loop = True  # 假设是循环
            for i in range(len(tools) - cycle_len):  # 滑动检查
                if tools[i] != tools[i + cycle_len]:  # 如果不匹配
                    is_loop = False  # 不是循环
                    break  # 跳出
            if is_loop:  # 如果确认是循环
                return f"cycle_{cycle_len}"  # 返回循环类型

        # 检测重复调用同一工具  # 重复检测
        tool_counts = Counter(tools)  # 统计频率
        most_common = tool_counts.most_common(1)[0]  # 获取最频繁的
        if most_common[1] >= 3:  # 如果重复>=3次
            return f"repeated_{most_common[0]}"  # 返回重复类型

        return None  # 无模式返回None

    def _determine_behavior_type(self, metrics: BehaviorMetrics,  # 判断行为类型
                                  tools: list[str]) -> str:  # 工具列表
        """判断行为类型"""  # 方法文档字符串
        # 检查循环模式  # 循环检查
        if metrics.pattern_detected:  # 如果检测到模式
            if metrics.pattern_detected.startswith("cycle"):  # 如果是循环
                return BehaviorType.LOOPING.value  # 返回循环型
            elif metrics.pattern_detected.startswith("repeated"):  # 如果是重复
                return BehaviorType.REPETITIVE.value  # 返回重复型

        # 基于工具数量和多样性判断  # 数量判断
        if metrics.total_tools_used <= 1:  # 如果<=1个工具
            return BehaviorType.SIMPLE_EXECUTION.value  # 返回简单执行型

        if metrics.unique_tools >= 3:  # 如果>=3个不同工具
            return BehaviorType.EXPLORATORY.value  # 返回探索型

        if metrics.total_tools_used == 2:  # 如果=2个工具
            return BehaviorType.GOAL_ORIENTED.value  # 返回目标型

        # 高成功率且低重复率  # 效率判断
        if metrics.success_rate > 0.8 and metrics.repeat_ratio < 0.3:  # 高效低重复
            return BehaviorType.OPTIMAL.value  # 返回最优型

        return BehaviorType.GOAL_ORIENTED.value  # 默认返回目标型

    def _calculate_risk(self, tools: list[str],  # 计算风险等级
                       results: list[dict],  # 结果列表
                       metrics: BehaviorMetrics) -> str:  # 行为指标
        """计算风险等级"""  # 方法文档字符串
        # 检查是否使用了高风险工具  # 高风险检查
        high_risk_count = sum(1 for t in tools if t in self.HIGH_RISK_TOOLS)  # 统计高风险工具
        medium_risk_count = sum(1 for t in tools if t in self.MEDIUM_RISK_TOOLS)  # 统计中风险工具

        # 极高风险：使用多个高风险工具或失败后继续使用  # 极高风险判断
        if high_risk_count >= 2:  # 如果>=2个高风险
            return RiskLevel.CRITICAL.value  # 返回极高风险

        # 高风险：使用了高风险工具或多次失败  # 高风险判断
        failed_count = sum(1 for r in results if not r.get("success", True))  # 统计失败数
        if high_risk_count > 0 or failed_count >= 3:  # 如果有高风险或>=3次失败
            return RiskLevel.HIGH.value  # 返回高风险

        # 中风险：使用了中风险工具或有循环模式  # 中风险判断
        if medium_risk_count > 0 or metrics.pattern_detected:  # 如果有中风险或模式
            return RiskLevel.MEDIUM.value  # 返回中风险

        # 低风险  # 低风险
        return RiskLevel.LOW.value  # 返回低风险

    def _generate_suggestion(self, behavior_type: str,  # 生成建议
                            risk_level: str,  # 风险等级
                            metrics: BehaviorMetrics) -> str:  # 行为指标
        """生成建议动作"""  # 方法文档字符串
        # 根据风险等级生成建议  # 风险建议
        if risk_level == RiskLevel.CRITICAL.value:  # 极高风险
            return "立即暂停执行，需要用户确认后方可继续"  # 建议暂停

        if risk_level == RiskLevel.HIGH.value:  # 高风险
            return "建议启用安全模式，增加确认环节"  # 建议安全模式

        # 根据行为类型生成建议  # 类型建议
        if behavior_type == BehaviorType.LOOPING.value:  # 循环型
            return "检测到循环模式，建议检查任务逻辑或提供更多信息"  # 建议检查逻辑

        if behavior_type == BehaviorType.REPETITIVE.value:  # 重复型
            return "检测到重复调用，建议优化执行策略"  # 建议优化策略

        if behavior_type == BehaviorType.EXPLORATORY.value:  # 探索型
            return "AI正在探索解决方案，建议给予更多执行时间"  # 建议等待

        if behavior_type == BehaviorType.SIMPLE_EXECUTION.value:  # 简单执行型
            return "任务执行正常，可以继续"  # 建议继续

        if behavior_type == BehaviorType.OPTIMAL.value:  # 最优型
            return "执行效率高，建议记录此执行模式"  # 建议记录

        if metrics.success_rate < 0.5:  # 成功率低
            return "执行成功率较低，建议检查工具配置或换一种方式"  # 建议检查

        return "继续执行，保持监控"  # 默认建议

    def _calculate_confidence(self, metrics: BehaviorMetrics) -> float:  # 计算置信度
        """计算行为识别的置信度"""  # 方法文档字符串
        # 基于数据量计算置信度  # 数据量计算
        if metrics.total_tools_used == 0:  # 如果无工具
            return 1.0  # 返回100%

        # 数据越多，置信度越高（但有上限）  # 数据量关系
        confidence = min(0.5 + metrics.total_tools_used * 0.1, 0.95)  # 基础置信度

        # 如果检测到明确模式，增加置信度  # 模式加成
        if metrics.pattern_detected:  # 如果有模式
            confidence = min(confidence + 0.1, 0.95)  # 增加0.1，上限0.95

        return confidence  # 返回置信度

    def _add_to_history(self, behavior: AIBehavior):  # 添加到历史
        """添加行为到历史记录"""  # 方法文档字符串
        self._behavior_history.append(behavior)  # 添加到列表
        if len(self._behavior_history) > self._max_history_size:  # 如果超过最大长度
            self._behavior_history.pop(0)  # 移除最早的

    def get_behavior_history(self, limit: int = 10) -> list[AIBehavior]:  # 获取行为历史
        """获取最近的行为历史"""  # 方法文档字符串
        return self._behavior_history[-limit:]  # 返回最近limit条

    def get_behavior_trends(self) -> dict[str, Any]:  # 获取行为趋势
        """获取行为趋势分析"""  # 方法文档字符串
        if not self._behavior_history:  # 如果无历史
            return {"message": "暂无行为历史"}  # 返回提示

        recent = self._behavior_history[-20:]  # 最近20次

        # 统计行为类型分布  # 类型统计
        type_counts = Counter(b.behavior_type for b in recent)  # 统计类型
        risk_counts = Counter(b.risk_level for b in recent)  # 统计风险

        # 计算平均成功率  # 平均置信度
        avg_confidence = sum(b.confidence for b in recent) / len(recent)  # 计算平均

        return {  # 返回趋势
            "total_records": len(self._behavior_history),  # 总记录数
            "recent_records": len(recent),  # 最近记录数
            "behavior_type_distribution": dict(type_counts),  # 行为类型分布
            "risk_level_distribution": dict(risk_counts),  # 风险等级分布
            "average_confidence": round(avg_confidence, 2),  # 平均置信度（保留2位）
            "trend": "stable" if len(recent) < 5 else self._calculate_trend(recent)  # 趋势判断
        }  # 返回结束

    def _calculate_trend(self, recent: list[AIBehavior]) -> str:  # 计算趋势
        """计算趋势"""  # 方法文档字符串
        # 简单趋势分析  # 分析方法
        first_half = recent[:len(recent)//2]  # 前半段
        second_half = recent[len(recent)//2:]  # 后半段

        first_risk = sum(1 for b in first_half if b.risk_level != RiskLevel.LOW.value)  # 前半段风险数
        second_risk = sum(1 for b in second_half if b.risk_level != RiskLevel.LOW.value)  # 后半段风险数

        if second_risk < first_risk:  # 如果风险减少
            return "improving"  # 返回改进
        elif second_risk > first_risk:  # 如果风险增加
            return "degrading"  # 返回下降
        return "stable"  # 返回稳定

    def check_anomaly(self, execution_history: list[dict[str, Any]]) -> str | None:  # 检查异常
        """检查异常行为"""  # 方法文档字符串
        if len(execution_history) < 3:  # 如果数据不足
            return None  # 返回None

        tools = [h.get("tool") for h in execution_history if h.get("tool")]  # 提取工具

        # 检查异常模式  # 异常检测
        # 1. 快速循环  # 完全循环检测
        if len(tools) >= 6 and tools[-6:] == tools[-12:-6]:  # 如果工具数>=6且完全重复
            return "检测到完全循环，建议立即干预"  # 返回异常

        # 2. 多次失败  # 连续失败检测
        recent_results = [h.get("result", {}) for h in execution_history[-5:]]  # 最近5次结果
        failed_count = sum(1 for r in recent_results if not r.get("success", True))  # 统计失败
        if failed_count >= 4:  # 如果>=4次失败
            return "连续多次失败，建议检查系统状态"  # 返回异常

        # 3. 工具使用过多  # 超限检测
        if len(tools) > 15:  # 如果>15个工具
            return "工具调用次数过多，可能存在循环"  # 返回异常

        return None  # 无异常返回None


# 全局单例  # 全局单例区域
_behavior_recognizer: BehaviorRecognizer | None = None  # 全局识别器实例


def get_behavior_recognizer() -> BehaviorRecognizer:  # 获取识别器函数
    """获取全局BehaviorRecognizer实例"""  # 函数文档字符串
    global _behavior_recognizer  # 引用全局变量
    if _behavior_recognizer is None:  # 如果未创建
        _behavior_recognizer = BehaviorRecognizer()  # 创建实例
    return _behavior_recognizer  # 返回实例


def reset_behavior_recognizer():  # 重置识别器函数
    """重置全局实例（主要用于测试）"""  # 函数文档字符串
    global _behavior_recognizer  # 引用全局变量
    _behavior_recognizer = None  # 重置为None


# 便捷函数  # 便捷函数区域
def analyze_behavior(execution_history: list[dict[str, Any]],  # 分析行为函数
                     user_instruction: str) -> AIBehavior:  # 用户指令
    """
    便捷函数：快速分析AI行为

    Args:
        execution_history: 执行历史记录
        user_instruction: 用户原始指令

    Returns:
        AIBehavior: 行为分析结果
    """
    recognizer = get_behavior_recognizer()  # 获取识别器
    return recognizer.analyze(execution_history, user_instruction)  # 执行分析


def check_behavior_anomaly(execution_history: list[dict[str, Any]]) -> str | None:  # 检查异常函数
    """
    便捷函数：检查行为异常

    Args:
        execution_history: 执行历史记录

    Returns:
        Optional[str]: 异常描述，无异常则返回None
    """
    recognizer = get_behavior_recognizer()  # 获取识别器
    return recognizer.check_anomaly(execution_history)  # 检查异常


# =============================================================================  # 分隔线
# 【文件总结】  # 总结区域标题
# =============================================================================  # 分隔线
# 文件角色：行为识别器，提供基础的行为分类和风险评估  # 角色说明
# 与behavior_analyzer的区别：  # 版本对比
#   - behavior_recognizer: 基础行为分类（8种类型）、风险评估、建议生成  # 区别1
#   - behavior_analyzer: 深度分析（工具模式、决策路径、学习效率、错误模式）  # 区别2
# 核心功能：  # 功能列表
#   1. 行为类型识别 - 识别8种行为类型（简单执行/目标型/探索型/重复型/  # 功能1
#                     循环型/风险型/学习型/最优型）  # 功能1续
#   2. 风险等级评估 - 基于工具风险等级和成功率评估LOW/MEDIUM/HIGH/CRITICAL  # 功能2
#   3. 建议动作生成 - 根据行为类型和风险等级生成针对性建议  # 功能3
#   4. 异常行为检测 - 检测完全循环、连续失败、工具调用过多  # 功能4
#   5. 趋势分析 - 分析风险等级变化趋势（改进/稳定/下降）  # 功能5
# 行为分类规则：  # 分类规则
#   - 简单执行型：使用<=1个工具  # 规则1
#   - 目标型：使用2个工具  # 规则2
#   - 探索型：使用>=3个不同工具  # 规则3
#   - 循环型：检测到A→B→A→B模式  # 规则4
#   - 重复型：同一工具重复>=3次  # 规则5
#   - 最优型：成功率>80%且重复率<30%  # 规则6
# 关联文件：  # 关联说明
#   - core/behavior_analyzer.py: 深度行为分析（本模块的补充）  # 关联1
#   - core/risk_level.py: 风险等级枚举定义  # 关联2
#   - core/agent_loop.py: Agent主循环（调用行为分析）  # 关联3
# 达到效果：  # 效果说明
#   - 快速识别AI当前的行为模式  # 效果1
#   - 及时发现异常行为并预警  # 效果2
#   - 为Agent循环提供风险管控依据  # 效果3
#   - 追踪AI行为演变趋势  # 效果4
# =============================================================================  # 分隔线结束
