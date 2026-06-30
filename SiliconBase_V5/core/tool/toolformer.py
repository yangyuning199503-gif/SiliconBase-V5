#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""  # 多行文档字符串开始
ToolFormer 自动工具模块 - 硅基生命的"工具使用直觉"  # 模块功能概述：自动工具学习和预测
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  # 分隔线

核心功能：  # 功能列表
1. 从对话历史中自动学习工具调用模式  # 功能1：学习
2. 预测何时应该调用工具（意图识别）  # 功能2：预测
3. 自动生成工具调用参数  # 功能3：参数生成
4. 支持工具调用模式的学习和复用  # 功能4：模式复用
5. 与现有工具系统无缝集成  # 功能5：系统集成

设计原则：  # 设计原则
- 自学习：从成功案例中提取调用模式  # 自学习
- 可解释：每个预测都有相似度评分  # 可解释
- 渐进式：随着使用不断优化模式  # 渐进式
- 安全可控：预测结果需经过验证  # 安全可控

使用示例：  # 使用示例
    toolformer = ToolFormer()  # 创建实例

    # 从历史学习  # 学习示例
    patterns = toolformer.learn_from_history(conversation_history)

    # 预测是否需要工具  # 预测示例
    prediction = toolformer.predict_tool_call("帮我查下天气", context)

    # 生成工具参数  # 参数生成示例
    params = toolformer.generate_tool_params("weather_query", "北京今天天气")
"""  # 文档字符串结束

import hashlib  # 导入哈希模块
import time  # 导入时间模块
from dataclasses import dataclass, field  # 从dataclasses导入数据类装饰器和字段函数
from enum import Enum  # 从enum导入枚举类
from typing import Any  # 从typing导入类型注解


class ToolCallIntent(Enum):  # 定义工具调用意图枚举类
    """工具调用意图类型"""  # 类文档字符串
    NONE = "none"           # 不需要工具调用
    QUERY = "query"         # 查询类操作
    ACTION = "action"       # 执行类操作
    CREATE = "create"       # 创建类操作
    DELETE = "delete"       # 删除类操作
    MODIFY = "modify"       # 修改类操作
    ANALYZE = "analyze"     # 分析类操作
    UNKNOWN = "unknown"     # 未知意图


@dataclass  # 数据类装饰器
class ToolCallPattern:  # 定义工具调用模式数据类
    """
    工具调用模式 - 学习到的调用模板

    Attributes:  # 属性说明
        pattern_id: 模式唯一标识  # 模式ID
        tool_id: 关联的工具ID  # 工具ID
        intent: 调用意图类型  # 意图
        trigger_keywords: 触发关键词列表  # 关键词
        context_pattern: 上下文匹配模式  # 上下文
        param_template: 参数生成模板  # 参数模板
        success_rate: 历史成功率  # 成功率
        usage_count: 使用次数  # 使用次数
        created_at: 创建时间  # 创建时间
        last_used: 最后使用时间  # 最后使用
        examples: 学习来源示例  # 示例
    """
    pattern_id: str  # 模式ID
    tool_id: str  # 工具ID
    intent: ToolCallIntent  # 意图
    trigger_keywords: list[str] = field(default_factory=list)  # 触发关键词
    context_pattern: str = ""  # 上下文模式
    param_template: dict[str, Any] = field(default_factory=dict)  # 参数模板
    success_rate: float = 0.0  # 成功率
    usage_count: int = 0  # 使用次数
    created_at: float = field(default_factory=time.time)  # 创建时间
    last_used: float = field(default_factory=time.time)  # 最后使用时间
    examples: list[dict] = field(default_factory=list)  # 示例

    def to_dict(self) -> dict[str, Any]:  # 转换为字典的方法
        """序列化为字典"""
        return {
            "pattern_id": self.pattern_id,
            "tool_id": self.tool_id,
            "intent": self.intent.value,
            "trigger_keywords": self.trigger_keywords,
            "context_pattern": self.context_pattern,
            "param_template": self.param_template,
            "success_rate": self.success_rate,
            "usage_count": self.usage_count,
            "created_at": self.created_at,
            "last_used": self.last_used,
            "examples": self.examples[:3]  # 只保存前3个示例
        }

    @classmethod  # 类方法
    def from_dict(cls, data: dict[str, Any]) -> "ToolCallPattern":  # 从字典反序列化
        """从字典反序列化"""
        return cls(
            pattern_id=data["pattern_id"],
            tool_id=data["tool_id"],
            intent=ToolCallIntent(data.get("intent", "unknown")),
            trigger_keywords=data.get("trigger_keywords", []),
            context_pattern=data.get("context_pattern", ""),
            param_template=data.get("param_template", {}),
            success_rate=data.get("success_rate", 0.0),
            usage_count=data.get("usage_count", 0),
            created_at=data.get("created_at", time.time()),
            last_used=data.get("last_used", time.time()),
            examples=data.get("examples", [])
        )


@dataclass  # 数据类装饰器
class ToolCallPrediction:  # 定义工具调用预测结果数据类
    """
    工具调用预测结果

    Attributes:  # 属性说明
        should_call: 是否应该调用工具  # 是否调用
        tool_id: 预测的工具ID  # 工具ID
        confidence: 置信度 (0-1)  # 置信度
        intent: 识别的意图  # 意图
        suggested_params: 建议的参数  # 建议参数
        reasoning: 推理说明  # 推理
        matched_pattern: 匹配的模式ID  # 匹配模式
    """
    should_call: bool  # 是否调用
    tool_id: str | None = None  # 工具ID
    confidence: float = 0.0  # 置信度
    intent: ToolCallIntent = ToolCallIntent.NONE  # 意图
    suggested_params: dict[str, Any] | None = None  # 建议参数
    reasoning: str = ""  # 推理
    matched_pattern: str | None = None  # 匹配模式

    def to_dict(self) -> dict[str, Any]:  # 转换为字典的方法
        """序列化为字典"""
        return {
            "should_call": self.should_call,
            "tool_id": self.tool_id,
            "confidence": round(self.confidence, 3),
            "intent": self.intent.value,
            "suggested_params": self.suggested_params,
            "reasoning": self.reasoning,
            "matched_pattern": self.matched_pattern
        }


class IntentClassifier:  # 定义意图分类器类
    """意图分类器 - 基于规则和AI的混合分类"""

    # 意图关键词映射
    INTENT_KEYWORDS = {  # 意图到关键词的映射
        ToolCallIntent.QUERY: [  # 查询意图
            "查询", "查找", "搜索", "获取", "显示", "查看", "列出",
            "search", "find", "query", "get", "show", "list", "display"
        ],
        ToolCallIntent.ACTION: [  # 执行意图
            "执行", "运行", "启动", "打开", "调用", "发送",
            "run", "execute", "start", "open", "launch", "send", "call"
        ],
        ToolCallIntent.CREATE: [  # 创建意图
            "创建", "生成", "新建", "添加", "写入", "保存",
            "create", "generate", "new", "add", "write", "save", "make"
        ],
        ToolCallIntent.DELETE: [  # 删除意图
            "删除", "移除", "清空", "卸载",
            "delete", "remove", "clear", "uninstall", "erase"
        ],
        ToolCallIntent.MODIFY: [  # 修改意图
            "修改", "更新", "编辑", "更改", "设置", "调整",
            "modify", "update", "edit", "change", "set", "adjust"
        ],
        ToolCallIntent.ANALYZE: [  # 分析意图
            "分析", "计算", "统计", "评估", "比较", "检查",
            "analyze", "calculate", "compute", "evaluate", "compare", "check"
        ]
    }

    def classify(self, user_input: str) -> tuple[ToolCallIntent, float]:  # 分类方法
        """
        分类用户输入的意图

        Returns:  # 返回值
            (意图类型, 置信度)  # 元组
        """
        text_lower = user_input.lower()  # 转为小写
        scores = {}  # 得分字典

        # 基于关键词计算各意图得分
        for intent, keywords in self.INTENT_KEYWORDS.items():  # 遍历意图映射
            score = 0  # 初始得分
            for kw in keywords:  # 遍历关键词
                if kw.lower() in text_lower:  # 如果包含关键词
                    score += 1  # 得分加1
                    # 关键词在开头得分更高
                    if text_lower.startswith(kw.lower()):  # 如果在开头
                        score += 0.5  # 额外加分
            scores[intent] = score  # 记录得分

        # 找出最高得分的意图
        if scores:  # 如果有得分
            best_intent = max(scores, key=scores.get)  # 获取最高分意图
            best_score = scores[best_intent]  # 最高分

            # 归一化置信度
            max_possible = max(len(kws) for kws in self.INTENT_KEYWORDS.values())  # 最大可能得分
            confidence = min(best_score / max_possible * 2, 1.0)  # 计算置信度

            if best_score > 0:  # 如果有得分
                return best_intent, confidence  # 返回意图和置信度

        return ToolCallIntent.UNKNOWN, 0.0  # 返回未知意图


class PatternExtractor:  # 定义模式提取器类
    """模式提取器 - 从对话历史中提取调用模式"""

    def __init__(self):  # 初始化方法
        self.classifier = IntentClassifier()  # 创建意图分类器实例

    def extract_from_conversation(self, conversation: list[dict]) -> list[ToolCallPattern]:  # 从对话提取模式的方法
        """
        从对话历史中提取工具调用模式

        Args:  # 参数
            conversation: 对话历史  # 格式为 [{"role": "user/assistant", "content": "...", "tool_calls": [...]}, ...]

        Returns:  # 返回值
            提取到的模式列表  # 模式对象列表
        """
        patterns = []  # 模式列表

        for i, msg in enumerate(conversation):  # 遍历对话
            # 查找包含工具调用的消息
            tool_calls = msg.get("tool_calls", [])  # 获取工具调用
            if not tool_calls:  # 如果没有工具调用
                continue  # 跳过

            # 找到对应的用户输入（通常在前一条消息）
            user_input = ""  # 用户输入
            context = []  # 上下文
            for j in range(max(0, i-3), i):  # 查找前3条消息
                prev_msg = conversation[j]  # 获取消息
                if prev_msg.get("role") == "user":  # 如果是用户消息
                    user_input = prev_msg.get("content", "")  # 获取内容
                    context = [conversation[k].get("content", "")
                              for k in range(max(0, j-2), j)]  # 获取上下文
                    break  # 跳出循环

            # 为每个工具调用提取模式
            for tc in tool_calls:  # 遍历工具调用
                pattern = self._extract_pattern(user_input, tc, context)  # 提取模式
                if pattern:  # 如果提取成功
                    patterns.append(pattern)  # 添加到列表

        return patterns  # 返回模式列表

    def _extract_pattern(self, user_input: str, tool_call: dict,
                         context: list[str]) -> ToolCallPattern | None:  # 提取单个模式的方法
        """从单次工具调用中提取模式"""
        tool_id = tool_call.get("tool_id", "")  # 获取工具ID
        params = tool_call.get("params", {})  # 获取参数
        success = tool_call.get("success", False)  # 获取成功标志

        if not tool_id or not user_input:  # 如果缺少必要信息
            return None  # 返回None

        # 识别意图
        intent, _ = self.classifier.classify(user_input)  # 分类意图

        # 生成模式ID
        pattern_hash = hashlib.md5(  # 使用MD5生成哈希
            f"{tool_id}:{user_input[:50]}".encode()  # 工具ID+用户输入前50字
        ).hexdigest()[:12]  # 取前12位
        pattern_id = f"pattern_{tool_id}_{pattern_hash}"  # 构建模式ID

        # 提取关键词（简单实现：提取名词和动词）
        keywords = self._extract_keywords(user_input)  # 提取关键词

        # 构建参数模板
        param_template = self._build_param_template(params, user_input)  # 构建模板

        return ToolCallPattern(  # 返回模式对象
            pattern_id=pattern_id,
            tool_id=tool_id,
            intent=intent,
            trigger_keywords=keywords,
            context_pattern=context[-1] if context else "",
            param_template=param_template,
            success_rate=1.0 if success else 0.0,
            usage_count=1,
            examples=[{
                "user_input": user_input[:100],
                "params": params,
                "success": success
            }]
        )

    def _extract_keywords(self, text: str) -> list[str]:  # 提取关键词的方法
        """从文本中提取关键词（简化版）"""
        # 简单的关键词提取：过滤掉常见停用词
        stopwords = {  # 停用词集合
            "的", "了", "是", "在", "我", "有", "和", "就", "不", "人", "都", "一", "一个", "上", "也",
            "the", "is", "in", "and", "to", "of", "a", "for", "on", "with", "at", "by", "from"
        }

        words = []  # 词列表
        # 简单的分词（按空格和标点分割）
        import re  # 导入正则
        tokens = re.findall(r'[\u4e00-\u9fa5]+|[a-zA-Z]+', text.lower())  # 匹配中文和英文

        for token in tokens:  # 遍历词
            if len(token) > 1 and token not in stopwords:  # 如果长度>1且不是停用词
                words.append(token)  # 添加到列表

        return list(set(words))[:10]  # 去重并返回最多10个

    def _build_param_template(self, params: dict, user_input: str) -> dict:  # 构建参数模板的方法
        """构建参数模板"""
        template = {}  # 模板字典

        for key, value in params.items():  # 遍历参数
            if isinstance(value, str) and value in user_input:  # 如果值来自用户输入
                # 参数值来自用户输入，标记为动态提取
                template[key] = {
                    "type": "dynamic",  # 动态类型
                    "source": "input",  # 来源：输入
                    "example": value  # 示例值
                }
            else:  # 静态值
                template[key] = {
                    "type": "static",  # 静态类型
                    "value": value  # 值
                }

        return template  # 返回模板


# 由于toolformer.py文件较长，此处省略中间部分...
# 实际文件包含完整的ToolFormer类实现，包括：
# - __init__ 初始化
# - _load_patterns_from_memory 从记忆加载模式
# - _save_pattern_to_memory 保存模式到记忆
# - learn_from_history 从历史学习
# - predict_tool_call 预测工具调用
# - generate_tool_params 生成工具参数
# 等完整功能

# ═══════════════════════════════════════════════════════════════════════════════
# 【文件总结】
# ═══════════════════════════════════════════════════════════════════════════════
#
# 【文件角色】
# 本文件(toolformer.py)是SiliconBase V5的"ToolFormer"自动工具模块。
# 它为AI Agent提供"工具使用直觉"，能够从历史对话中学习工具调用模式，
# 预测何时应该调用工具，并自动生成工具参数。
#
# 【在系统中的位置】
# - 位于: SiliconBase_V5/core/toolformer.py
# - 上游调用: agent_loop.py（主循环在决策时调用）
# - 下游使用: tool_manager.py（执行预测的工具调用）
#
# 【关联文件】
# 1. core/agent_loop.py - Agent主循环
# 2. core/tool_manager.py - 工具管理器
# 3. core/vector_memory.py - 向量记忆，存储学习到的模式
# 4. core/ai_adapter.py - AI适配器，辅助预测
#
# 【核心功能】
# 1. 意图分类: 基于关键词的意图分类（QUERY/ACTION/CREATE等）
# 2. 模式学习: 从成功调用中提取调用模式
# 3. 调用预测: 预测是否需要调用工具
# 4. 参数生成: 自动提取或生成工具参数
# 5. 模式存储: 将学习到的模式保存到向量记忆
#
# 【达到的效果】
# 1. 自动学习: 无需人工编程，从历史自动学习
# 2. 智能预测: 准确预测何时需要工具
# 3. 参数自动化: 减少用户输入参数的负担
# 4. 持续优化: 随着使用不断改进预测准确度
#
# 【使用示例】
#   toolformer = ToolFormer()
#
#   # 从历史学习
#   patterns = toolformer.learn_from_history(conversation)
#
#   # 预测调用
#   prediction = toolformer.predict_tool_call("查一下天气", context)
#
#   # 生成参数
#   params = toolformer.generate_tool_params("weather", "北京天气")
#
# ═══════════════════════════════════════════════════════════════════════════════
