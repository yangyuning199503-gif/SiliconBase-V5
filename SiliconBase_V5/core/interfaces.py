#!/usr/bin/env python3  # 指定Python解释器路径
# 声明使用UTF-8编码，支持中文
"""  # 文档字符串开始
核心接口契约定义  # 模块功能描述
使用TypedDict和Protocol，不破坏原有调用流程  # 技术类型说明
解决隐式依赖导致的运行时错误  # 核心问题解决
"""  # 文档字符串结束

from collections.abc import Callable
from typing import (  # 导入类型工具
    Any,
    Protocol,
    TypedDict,
    runtime_checkable,
)

# ============================================================================  # 分隔线注释
# 工具相关接口  # 模块分区说明
# ============================================================================  # 分隔线结束

class ToolResult(TypedDict):  # 定义工具结果类型字典
    """  # 类文档字符串开始
    工具调用结果接口  # 功能描述

    契约：tool_manager.call_tool() 必须返回此格式  # 接口契约说明
    解决：intent_handler 对 tool_manager 返回格式的隐式依赖  # 解决的问题
    """  # 类文档字符串结束
    success: bool  # 操作成功标志
    data: Any  # 返回数据
    error_code: str | None  # 错误码（可选）
    user_message: str  # 用户友好的消息
    duration: float  # 执行耗时


class ToolInfo(TypedDict):  # 定义工具信息类型字典
    """工具信息接口"""  # 类文档字符串
    tool_id: str  # 工具唯一标识
    name: str  # 工具名称
    description: str  # 工具描述
    category: str  # 工具分类
    risk_level: str  # 风险等级
    parameters: dict[str, Any]  # 参数定义


# ============================================================================  # 分隔线注释
# 意图解析相关接口  # 模块分区说明
# ============================================================================  # 分隔线结束

class ParsedIntent(TypedDict):  # 定义解析意图类型字典
    """  # 类文档字符串开始
    意图解析结果接口  # 功能描述

    契约：intent_handler.handle() 必须返回此格式  # 接口契约说明
    解决：agent_loop 对 intent_handler 返回格式的隐式依赖  # 解决的问题
    """  # 类文档字符串结束
    intent_type: str  # 意图类型: "tool_call", "final_answer", "plan", "clarify", "call_user"
    target_tool: str | None  # 目标工具ID（可选）
    params: dict[str, Any]  # 工具参数
    confidence: float  # 置信度
    raw_instruction: str  # 原始指令
    steps: list[dict[str, Any]] | None  # 用于plan意图的步骤列表（可选）
    reason: str | None  # 用于call_user意图的原因（可选）


# ============================================================================  # 分隔线注释
# WorkingMemory 协议  # 模块分区说明
# ============================================================================  # 分隔线结束

class WorkingMemoryProtocol(Protocol):  # 定义WorkingMemory协议类
    """  # 类文档字符串开始
    WorkingMemory必须实现的接口  # 功能描述

    解决：各处对WorkingMemory属性的隐式假设  # 解决的问题
    """  # 类文档字符串结束
    # 核心属性  # 注释标识属性区域
    query_stage: str  # 查询阶段: "L1_OVERVIEW", "L2_MANUAL", "L3_TOOL_DETAIL"
    current_category: str | None  # 当前工具分类（可选）
    current_tool: str | None  # 当前工具ID（可选）
    ai_plan_id: str | None  # AI计划ID（可选）
    ai_plan: dict[str, Any] | None  # AI计划内容（可选）

    # 方法  # 注释标识方法区域
    def append(self, message: dict[str, str]) -> None:  # 定义添加消息方法
        """添加消息"""
        ...  # 协议方法省略实现

    def update_after_tool(self, tool_id: str, success: bool, summary: str) -> None:  # 定义工具执行后更新方法
        """更新状态"""
        ...  # 协议方法省略实现

    def record_layer_switch(self, from_stage: str, to_stage: str, reason: str) -> bool:  # 定义层级切换记录方法
        """记录层级切换"""
        ...  # 协议方法省略实现


# ============================================================================  # 分隔线注释
# WebSocket消息接口  # 模块分区说明
# ============================================================================  # 分隔线结束

class WebSocketMessage(TypedDict):  # 定义WebSocket消息类型字典
    """  # 类文档字符串开始
    WebSocket消息契约  # 功能描述

    解决：cloud_api对WebSocket消息格式的隐式假设  # 解决的问题
    """  # 类文档字符串结束
    type: str  # 消息类型: "chat", "voice", "command", "pause", "resume"
    message: str | None  # 消息内容（可选）
    session_id: str | None  # 会话ID（可选）
    timestamp: str | None  # 时间戳（可选）
    metadata: dict[str, Any] | None  # 元数据（可选）


class ChatMessage(TypedDict):  # 定义聊天消息类型字典
    """聊天消息格式"""  # 类文档字符串
    role: str  # 角色: "user", "assistant", "system"
    content: str  # 消息内容
    timestamp: str | None  # 时间戳（可选）


# ============================================================================  # 分隔线注释
# 任务相关接口  # 模块分区说明
# ============================================================================  # 分隔线结束

class TaskInfo(TypedDict):  # 定义任务信息类型字典
    """任务信息接口"""  # 类文档字符串
    task_id: str  # 任务唯一标识
    type: str  # 任务类型
    description: str  # 任务描述
    status: str  # 任务状态
    intent: dict[str, Any]  # 意图信息
    session_id: str  # 会话ID
    user_id: str  # 用户ID


class TaskResult(TypedDict):  # 定义任务结果类型字典
    """任务执行结果接口"""  # 类文档字符串
    success: bool  # 是否成功
    result: Any  # 执行结果
    error: str | None  # 错误信息（可选）
    execution_time: float  # 执行耗时
    steps_executed: int  # 执行步骤数


# ============================================================================  # 分隔线注释
# 事件相关接口  # 模块分区说明
# ============================================================================  # 分隔线结束

class EventData(TypedDict):  # 定义事件数据类型字典
    """事件数据接口"""  # 类文档字符串
    event_type: str  # 事件类型
    timestamp: float  # 时间戳
    source: str  # 事件来源
    payload: dict[str, Any]  # 事件载荷


# ============================================================================  # 分隔线注释
# 安全字典访问包装器  # 模块分区说明
# ============================================================================  # 分隔线结束

class SafeDictAccessor:  # 定义安全字典访问包装器类
    """  # 类文档字符串开始
    安全字典访问包装器  # 功能描述

    解决：直接字典访问导致的KeyError  # 解决的问题
    使用：替代 result["key"] 为 accessor.get("key")  # 使用建议
    """  # 类文档字符串结束

    def __init__(self, data: Any, path: str = "root"):  # 初始化方法
        self._data = data  # 存储被包装的数据
        self._path = path  # 存储当前路径（用于错误提示）

    def get(self, key: str, default=None) -> Any:  # 定义安全获取方法
        """安全获取字段"""  # 方法文档字符串
        if not isinstance(self._data, dict):  # 检查数据是否为字典
            print(f"[SafeDict] 访问失败 {self._path}: 期望dict，实际为 {type(self._data)}")  # 打印错误信息
            return default  # 返回默认值
        return self._data.get(key, default)  # 安全获取字典值

    def require(self, key: str, error_message: str = None) -> Any:  # 定义必需获取方法
        """  # 方法文档字符串开始
        必须存在的字段  # 功能描述
        不存在则抛出明确异常  # 行为说明

        Args:  # 参数说明
            key: 键名  # 参数描述
            error_message: 自定义错误消息  # 参数描述
        """  # 方法文档字符串结束
        value = self.get(key)  # 尝试获取值
        if value is None:  # 如果值为None
            msg = error_message if error_message else f"缺少必需字段: {self._path}.{key}"  # 构建错误消息
            raise KeyError(msg)  # 抛出KeyError异常
        return value  # 返回值

    def __getitem__(self, key: str) -> "SafeDictAccessor":  # 定义索引访问方法
        """链式访问"""  # 方法文档字符串
        value = self.get(key, {})  # 获取值，默认为空字典
        return SafeDictAccessor(value, f"{self._path}.{key}")  # 返回新的包装器实例


# ============================================================================  # 分隔线注释
# 验证函数  # 模块分区说明
# ============================================================================  # 分隔线结束

def validate_tool_result(result: Any) -> ToolResult:  # 定义工具结果验证函数
    """  # 函数文档字符串开始
    验证工具调用结果格式  # 功能描述

    在模块边界调用，确保格式正确  # 使用建议
    """  # 函数文档字符串结束
    if not isinstance(result, dict):  # 检查结果是否为字典
        raise ValueError(f"ToolResult必须是字典，实际为{type(result)}")  # 抛出类型错误

    required_fields = ["success", "data", "error_code", "user_message", "duration"]  # 定义必需字段列表
    for field in required_fields:  # 遍历所有必需字段
        if field not in result:  # 如果字段缺少
            # 填充默认值 # 注释说明默认值填充
            if field == "success":  # success字段
                result["success"] = True  # 默认True
            elif field == "error_code":  # error_code字段
                result["error_code"] = None  # 默认None
            elif field == "user_message":  # user_message字段
                result["user_message"] = "执行完成"  # 默认完成消息
            elif field == "duration":  # duration字段
                result["duration"] = 0.0  # 默认0.0

    return result  # type: ignore  # 返回验证后的结果（忽略类型检查）


def validate_parsed_intent(intent: Any) -> ParsedIntent:  # 定义意图验证函数
    """验证意图解析结果格式"""  # 函数文档字符串
    if not isinstance(intent, dict):  # 检查数据是否为字典
        raise ValueError(f"ParsedIntent必须是字典，实际为{type(intent)}")  # 抛出类型错误

    required_fields = ["intent_type", "target_tool", "params", "confidence", "raw_instruction"]  # 必需字段
    for field in required_fields:  # 遍历必需字段
        if field not in intent:  # 如果字段缺少
            if field == "params":  # params字段
                intent["params"] = {}  # 默认空字典
            elif field == "confidence":  # confidence字段
                intent["confidence"] = 0.0  # 默认0.0
            elif field == "target_tool":  # target_tool字段
                intent["target_tool"] = None  # 默认None

    return intent  # type: ignore  # 返回验证后的结果（忽略类型检查）


# ============================================================================  # 分隔线注释
# 便捷类型别名  # 模块分区说明
# ============================================================================  # 分隔线结束

# 用于handler返回的统一格式  # 注释说明类型别名用途
HandlerResult = dict[str, Any]  # 定义处理器结果类型别名

# 执行历史记录条目  # 注释说明类型别名用途
ExecutionHistoryEntry = dict[str, Any]  # 定义执行历史记录条目类型别名

# 工具参数  # 注释说明类型别名用途
ToolParams = dict[str, Any]  # 定义工具参数类型别名

# 通用的JSON兼容类型  # 注释说明类型别名用途
JSONValue = str | int | float | bool | None | dict[str, Any] | list[Any]  # 定义JSON值类型别名


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase V5 系统的"接口契约中心"，使用Python的类型提示机制
# （TypedDict、Protocol）定义模块间通信的数据结构和行为协议，解决隐式
# 依赖导致的运行时错误。
#
# 【设计特点】
# 1. 结构化类型：使用TypedDict定义字典结构，提供IDE自动补全和类型检查
# 2. 协议抽象：使用Protocol定义接口契约，支持鸭子类型和结构子类型
# 3. 安全访问：提供SafeDictAccessor包装器，避免KeyError导致的崩溃
# 4. 验证函数：提供validate_*函数，在模块边界进行数据格式校验
# 5. 类型别名：提供便捷的类型别名，简化代码中的类型注解
#
# 【关联文件】
# - core/tool_manager.py         : 返回ToolResult结构
# - core/intent_handler.py       : 返回ParsedIntent结构
# - core/working_memory.py       : 实现WorkingMemoryProtocol
# - core/cloud_api.py            : 使用WebSocketMessage结构
# - core/agent_loop.py           : 消费各接口定义的数据结构
#
# 【核心功能效果】
# 1. 契约明确：模块间的数据格式通过类型定义明确化，减少隐式假设
# 2. 早期错误发现：通过类型检查在开发阶段发现接口不匹配问题
# 3. 自动补全：IDE可以根据类型定义提供属性和方法的自动补全
# 4. 文档即代码：类型定义本身就是接口文档，保持文档与代码同步
# 5. 安全降级：SafeDictAccessor提供安全的字典访问，优雅处理缺少字段
#
# 【使用示例】
# from core.interfaces import ToolResult, ParsedIntent, SafeDictAccessor
#
# # 定义函数返回类型
# def call_tool(tool_id: str, params: Dict) -> ToolResult:
#     return {"success": True, "data": None, ...}
#
# # 安全访问嵌套字典
# accessor = SafeDictAccessor(result)
# value = accessor["nested"]["key"].get("field", "default")
#
# # 验证数据格式
# validated = validate_tool_result(raw_result)
# =============================================================================


# ============================================================================
# AgentLoop 适配器接口
# ============================================================================

@runtime_checkable
class IAgentLoop(Protocol):
    """
    AgentLoop适配器接口协议

    契约：agent_loop_adapter.AgentLoopAdapter 必须实现此接口
    解决：agent_loop_adapter 对 IAgentLoop 接口的依赖
    """

    def run_agent_loop(
        self,
        task: Any,
        max_rounds: int | None = None,
        chat_history: list[dict] | None = None,
        chat_count: int = 0,
        session_id: str = "console",
        voice_instance: Any | None = None,
        mode: str = "daily"
    ) -> tuple[str | None, Any]:
        """
        运行 Agent 主循环

        Args:
            task: 任务描述
            max_rounds: 最大循环轮数（可选）
            chat_history: 聊天历史（可选）
            chat_count: 当前聊天轮数
            session_id: 会话ID
            voice_instance: 语音实例（可选）
            mode: 运行模式，"daily" 或 "focus"

        Returns:
            Tuple[结果字符串, WorkingMemory]: 执行结果和记忆状态
        """
        ...

    def set_event_emitter(self, emitter: 'IEventEmitter') -> None:
        """设置事件发射器"""
        ...

    def set_message_handler(self, handler: Callable[[Any], None]) -> None:
        """设置消息处理器"""
        ...

    @property
    def wrapped_instance(self) -> Any:
        """获取被包装的实例"""
        ...


@runtime_checkable
class IEventEmitter(Protocol):
    """
    事件发射器接口协议

    契约：事件发射器必须实现此接口
    解决：agent_loop_adapter 对 IEventEmitter 接口的依赖
    """

    def emit(self, event_type: str, data: dict[str, Any]) -> None:
        """
        发射事件

        Args:
            event_type: 事件类型
            data: 事件数据
        """
        ...


# ============================================================================
# 使用示例
# ============================================================================
#
# # 实现IAgentLoop接口
# class MyAgentLoop:
#     def run_agent_loop(self, task, max_rounds=None, ...):
#         # 实现逻辑
#         return result, memory
#
#     def set_event_emitter(self, emitter):
#         self._emitter = emitter
#
#     @property
#     def wrapped_instance(self):
#         return self
#
# # 实现IEventEmitter接口
# class MyEventEmitter:
#     def emit(self, event_type, data):
#         print(f"Event: {event_type}, Data: {data}")
# =============================================================================


# ============================================================================
# Evolution 适配器接口
# ============================================================================

@runtime_checkable
class IEvolutionEngine(Protocol):
    """
    EvolutionEngine 适配器接口协议

    契约：evolution_adapter.EvolutionAdapter 必须实现此接口
    解决：evolution_adapter 对 IEvolutionEngine 接口的依赖
    """

    def extract_success_pattern(self, task: str, execution_result: dict[str, Any]) -> dict[str, Any] | None:
        """从成功执行中提取模式"""
        ...

    def store_experience(self, experience: dict[str, Any]) -> bool:
        """存储经验"""
        ...

    def retrieve_experience(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """检索相关经验"""
        ...

    def set_event_emitter(self, emitter: 'IEventEmitter') -> None:
        """设置事件发射器"""
        ...


@runtime_checkable
class IExperienceManager(Protocol):
    """
    ExperienceManager 适配器接口协议

    契约：evolution_adapter.ExperienceAdapter 必须实现此接口
    解决：evolution_adapter 对 IExperienceManager 接口的依赖
    """

    def store(self, experience: dict[str, Any]) -> bool:
        """存储经验"""
        ...

    def retrieve(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """检索经验"""
        ...

    def get_injector(self) -> Any:
        """获取经验注入器"""
        ...

    def set_event_emitter(self, emitter: 'IEventEmitter') -> None:
        """设置事件发射器"""
        ...


# ============================================================================
# Consciousness 适配器接口
# ============================================================================

@runtime_checkable
class IConsciousness(Protocol):
    """
    Consciousness 适配器接口协议

    解决：consciousness_adapter 对 IConsciousness 接口的依赖
    """

    def think(self, context: dict[str, Any]) -> str | None:
        """思考方法"""
        ...

    def generate_goal(self, context: dict[str, Any]) -> dict[str, Any] | None:
        """生成目标"""
        ...

    def set_event_emitter(self, emitter: 'IEventEmitter') -> None:
        """设置事件发射器"""
        ...
