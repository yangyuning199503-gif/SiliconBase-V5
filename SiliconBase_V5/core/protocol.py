#!/usr/bin/env python3
"""
标准化消息协议定义
用于模块间的标准化通信
"""
import time
import uuid
from enum import Enum
from typing import Any, TypedDict, cast


class MessageType(Enum):
    """消息类型枚举"""
    TASK_REQUEST = "task:request"
    TASK_RESULT = "task:result"
    TASK_FAILED = "task:failed"
    TOOL_CALL = "tool:call"
    TOOL_RESULT = "tool:result"
    THOUGHT_GENERATED = "consciousness:thought"
    REFLECTION_REQUEST = "reflection:request"
    REFLECTION_RESULT = "reflection:result"
    EVOLUTION_TRIGGER = "evolution:trigger"
    STATE_CHANGE = "state:change"


class AgentMessage(TypedDict):
    """标准化代理消息格式"""
    msg_type: str
    source: str
    target: str | None
    payload: Any
    timestamp: float
    trace_id: str


class TaskRequestPayload(TypedDict):
    """任务请求载荷"""
    task_id: str
    goal: str
    priority: str
    context: dict[str, Any]
    source: str
    session_id: str


class TaskResultPayload(TypedDict):
    """任务结果载荷"""
    task_id: str
    success: bool
    result: Any
    execution_time: float
    tools_used: list[str]
    error: str | None


class ToolCallPayload(TypedDict):
    """工具调用载荷"""
    tool_id: str
    params: dict[str, Any]
    task_id: str
    timeout: int


class ToolResultPayload(TypedDict):
    """工具结果载荷"""
    tool_id: str
    task_id: str
    success: bool
    result: Any
    error: str | None
    execution_time: float


class ThoughtPayload(TypedDict):
    """思考生成载荷"""
    thought_id: str
    content: str
    source: str
    emotional_state: dict[str, Any] | None
    trigger: str | None


class ReflectionPayload(TypedDict):
    """反思请求/结果载荷"""
    reflection_id: str
    task_id: str | None
    task_description: str
    execution_history: list[dict[str, Any]]
    success: bool | None
    insights: list[str] | None
    suggestions: list[str] | None


class EvolutionPayload(TypedDict):
    """进化触发载荷"""
    trigger_type: str
    task_id: str | None
    description: str | None
    report: dict[str, Any] | None


class StateChangePayload(TypedDict):
    """状态变更载荷"""
    state_type: str
    old_value: Any
    new_value: Any
    reason: str | None


# ==================== 消息工厂函数 ====================

def create_message(
    msg_type: MessageType | str,
    source: str,
    payload: Any,
    target: str | None = None,
    trace_id: str | None = None
) -> AgentMessage:
    """
    创建标准化消息

    Args:
        msg_type: 消息类型（枚举或字符串）
        source: 消息来源模块
        payload: 消息载荷
        target: 目标模块（可选）
        trace_id: 追踪ID（可选，自动生成）

    Returns:
        AgentMessage: 标准化消息对象
    """
    msg_type_value = msg_type.value if isinstance(msg_type, Enum) else msg_type
    return AgentMessage(
        msg_type=msg_type_value,
        source=source,
        target=target,
        payload=payload,
        timestamp=time.time(),
        trace_id=trace_id or str(uuid.uuid4())
    )


def create_task_request(
    goal: str,
    source: str = "user",
    priority: str = "normal",
    context: dict[str, Any] | None = None,
    session_id: str = "default",
    task_id: str | None = None
) -> AgentMessage:
    """创建任务请求消息"""
    payload = TaskRequestPayload(
        task_id=task_id or str(uuid.uuid4()),
        goal=goal,
        priority=priority,
        context=context or {},
        source=source,
        session_id=session_id
    )
    return create_message(MessageType.TASK_REQUEST, source, payload)


def create_task_result(
    task_id: str,
    success: bool,
    result: Any,
    tools_used: list[str] | None = None,
    error: str | None = None,
    execution_time: float = 0.0,
    source: str = "agent_loop"
) -> AgentMessage:
    """创建任务结果消息"""
    payload = TaskResultPayload(
        task_id=task_id,
        success=success,
        result=result,
        execution_time=execution_time,
        tools_used=tools_used or [],
        error=error
    )
    return create_message(MessageType.TASK_RESULT, source, payload)


def create_tool_call(
    tool_id: str,
    params: dict[str, Any],
    task_id: str,
    timeout: int = 30,
    source: str = "agent_loop"
) -> AgentMessage:
    """创建工具调用消息"""
    payload = ToolCallPayload(
        tool_id=tool_id,
        params=params,
        task_id=task_id,
        timeout=timeout
    )
    return create_message(MessageType.TOOL_CALL, source, payload, target="tool_manager")


def create_thought(
    content: str,
    source: str = "consciousness",
    emotional_state: dict[str, Any] | None = None,
    trigger: str | None = None
) -> AgentMessage:
    """创建思考生成消息"""
    payload = ThoughtPayload(
        thought_id=str(uuid.uuid4()),
        content=content,
        source=source,
        emotional_state=emotional_state,
        trigger=trigger
    )
    return create_message(MessageType.THOUGHT_GENERATED, source, payload)


def create_reflection_request(
    task_description: str,
    execution_history: list[dict[str, Any]],
    task_id: str | None = None,
    source: str = "consciousness"
) -> AgentMessage:
    """创建反思请求消息"""
    payload = ReflectionPayload(
        reflection_id=str(uuid.uuid4()),
        task_id=task_id,
        task_description=task_description,
        execution_history=execution_history,
        success=None,
        insights=None,
        suggestions=None
    )
    return create_message(MessageType.REFLECTION_REQUEST, source, payload)


def create_reflection_result(
    reflection_id: str,
    success: bool,
    insights: list[str],
    suggestions: list[str],
    task_id: str | None = None,
    source: str = "reflector"
) -> AgentMessage:
    """创建反思结果消息"""
    payload = ReflectionPayload(
        reflection_id=reflection_id,
        task_id=task_id,
        task_description="",
        execution_history=[],
        success=success,
        insights=insights,
        suggestions=suggestions
    )
    return create_message(MessageType.REFLECTION_RESULT, source, payload)


def create_evolution_trigger(
    trigger_type: str,
    task_id: str | None = None,
    description: str | None = None,
    report: dict[str, Any] | None = None,
    source: str = "evolution"
) -> AgentMessage:
    """创建进化触发消息"""
    payload = EvolutionPayload(
        trigger_type=trigger_type,
        task_id=task_id,
        description=description,
        report=report
    )
    return create_message(MessageType.EVOLUTION_TRIGGER, source, payload)


# ==================== 消息验证函数 ====================

def validate_message(message: dict[str, Any]) -> bool:
    """
    验证消息格式是否有效

    Args:
        message: 待验证的消息字典

    Returns:
        bool: 是否有效
    """
    required_fields = ["msg_type", "source", "payload", "timestamp", "trace_id"]
    return all(field in message for field in required_fields)


def get_message_type(message: AgentMessage) -> MessageType | None:
    """
    获取消息类型枚举

    Args:
        message: 消息对象

    Returns:
        MessageType: 消息类型枚举，无效则返回None
    """
    try:
        return MessageType(message["msg_type"])
    except ValueError:
        return None


# ============================================================================
# 向后兼容别名（兼容 V6 改造中的导入）
# ============================================================================

MSG_TASK_REQUEST = MessageType.TASK_REQUEST.value
MSG_TASK_RESULT = MessageType.TASK_RESULT.value
MSG_TASK_FAILED = MessageType.TASK_FAILED.value
MSG_TOOL_CALL = MessageType.TOOL_CALL.value
MSG_TOOL_RESULT = MessageType.TOOL_RESULT.value
MSG_TASK_PROPOSED = "internal:task_proposed"
MSG_TASK_ACCEPTED = "internal:task_accepted"
MSG_TASK_REJECTED = "internal:task_rejected"
MSG_TASK_STARTED = "task:started"
MSG_TASK_PROGRESS = "task:progress"
MSG_TASK_CANCELLED = "task:cancelled"
MSG_REFLECTION_REQUEST = MessageType.REFLECTION_REQUEST.value
MSG_REFLECTION_RESULT = MessageType.REFLECTION_RESULT.value
MSG_REFLECTION_INSIGHT = "reflection:insight"
MSG_EVOLUTION_LEARN = "evolution:learn"
MSG_EVOLUTION_NEW_SKILL = "evolution:new_skill"
MSG_EVOLUTION_PATTERN = "evolution:pattern"
MSG_TOOL_CALLED = "tool:called"
MSG_TOOL_REGISTERED = "tool:registered"
MSG_TOOL_FAILED = "tool:failed"
MSG_SYSTEM_STATE = "system:state"
MSG_SYSTEM_ERROR = "system:error"
MSG_SYSTEM_CONFIG_CHANGE = "system:config_change"

MSG_PLATE_COMMAND = "plate:command"
MSG_USER_EXPRESSION = "consciousness:user_expression"
MSG_SELF_STATE_UPDATED = "consciousness:self_state_updated"

build_message = create_message
is_valid_message = validate_message


def generate_trace_id() -> str:
    """生成唯一追踪ID"""
    return str(uuid.uuid4())


PRIORITY_MAP = {
    "high": 1,
    "normal": 2,
    "low": 3
}

PRIORITY_REVERSE_MAP = {v: k for k, v in PRIORITY_MAP.items()}


def priority_to_number(priority: str) -> int:
    """
    将字符串优先级转换为数值
    high -> 1, normal -> 2, low -> 3
    """
    return PRIORITY_MAP.get(priority.lower(), 2)


def number_to_priority(number: int) -> str:
    """
    将数值优先级转换为字符串
    1 -> high, 2 -> normal, 3 -> low
    """
    return PRIORITY_REVERSE_MAP.get(number, "normal")


def get_message_summary(msg: AgentMessage, max_length: int = 100) -> str:
    """
    获取消息摘要（用于日志记录）

    Args:
        msg: 标准消息
        max_length: 摘要最大长度

    Returns:
        消息摘要字符串
    """
    msg_type = msg.get("msg_type", "unknown")
    source = msg.get("source", "unknown")
    trace_id = msg.get("trace_id", "no-trace")[:8]

    payload = msg.get("payload", {})
    if isinstance(payload, dict):
        payload_dict = cast(dict[str, Any], payload)
        if "goal" in payload_dict:
            content = str(payload_dict["goal"])[:max_length]
        elif "task_id" in payload_dict:
            content = f"task:{payload_dict['task_id'][:8]}"
        elif "result" in payload_dict:
            content = str(payload_dict["result"])[:max_length]
        else:
            content = str(payload_dict)[:max_length]
    else:
        content = str(payload)[:max_length]

    return f"[{msg_type}] from:{source} trace:{trace_id} - {content}"


# ============================================================================
# Rust 硬壳层接入：优先使用 Rust 实现，失败时保持 Python 回退
# ============================================================================
try:
    from siliconbase_core import (
        create_evolution_trigger as _rust_create_evolution_trigger,
    )
    from siliconbase_core import (
        create_message as _rust_create_message,
    )
    from siliconbase_core import (
        create_reflection_request as _rust_create_reflection_request,
    )
    from siliconbase_core import (
        create_reflection_result as _rust_create_reflection_result,
    )
    from siliconbase_core import (
        create_task_request as _rust_create_task_request,
    )
    from siliconbase_core import (
        create_task_result as _rust_create_task_result,
    )
    from siliconbase_core import (
        create_thought as _rust_create_thought,
    )
    from siliconbase_core import (
        create_tool_call as _rust_create_tool_call,
    )
    from siliconbase_core import (
        generate_trace_id as _rust_generate_trace_id,
    )
    from siliconbase_core import (
        get_message_summary as _rust_get_message_summary,
    )
    from siliconbase_core import (
        number_to_priority as _rust_number_to_priority,
    )
    from siliconbase_core import (
        priority_to_number as _rust_priority_to_number,
    )
    from siliconbase_core import (
        validate_message as _rust_validate_message,
    )

    def create_message(  # type: ignore[misc]
        msg_type: MessageType | str,
        source: str,
        payload: Any,
        target: str | None = None,
        trace_id: str | None = None
    ) -> AgentMessage:
        msg_type_value = msg_type.value if isinstance(msg_type, Enum) else msg_type
        return _rust_create_message(msg_type_value, source, payload, target, trace_id)

    def create_task_request(  # type: ignore[misc]
        goal: str,
        source: str = "user",
        priority: str = "normal",
        context: dict[str, Any] | None = None,
        session_id: str = "default",
        task_id: str | None = None
    ) -> AgentMessage:
        return _rust_create_task_request(
            goal, source, priority, context or {}, session_id, task_id
        )

    def create_task_result(  # type: ignore[misc]
        task_id: str,
        success: bool,
        result: Any,
        tools_used: list[str] | None = None,
        error: str | None = None,
        execution_time: float = 0.0,
        source: str = "agent_loop"
    ) -> AgentMessage:
        return _rust_create_task_result(
            task_id, success, result, tools_used or [], error, execution_time, source
        )

    def create_tool_call(  # type: ignore[misc]
        tool_id: str,
        params: dict[str, Any],
        task_id: str,
        timeout: int = 30,
        source: str = "agent_loop"
    ) -> AgentMessage:
        return _rust_create_tool_call(tool_id, params, task_id, timeout, source)

    def create_thought(  # type: ignore[misc]
        content: str,
        source: str = "consciousness",
        emotional_state: dict[str, Any] | None = None,
        trigger: str | None = None
    ) -> AgentMessage:
        return _rust_create_thought(content, source, emotional_state, trigger)

    def create_reflection_request(  # type: ignore[misc]
        task_description: str,
        execution_history: list[dict[str, Any]],
        task_id: str | None = None,
        source: str = "consciousness"
    ) -> AgentMessage:
        return _rust_create_reflection_request(
            task_description, execution_history, task_id, source
        )

    def create_reflection_result(  # type: ignore[misc]
        reflection_id: str,
        success: bool,
        insights: list[str],
        suggestions: list[str],
        task_id: str | None = None,
        source: str = "reflector"
    ) -> AgentMessage:
        return _rust_create_reflection_result(
            reflection_id, success, insights, suggestions, task_id, source
        )

    def create_evolution_trigger(  # type: ignore[misc]
        trigger_type: str,
        task_id: str | None = None,
        description: str | None = None,
        report: dict[str, Any] | None = None,
        source: str = "evolution"
    ) -> AgentMessage:
        return _rust_create_evolution_trigger(
            trigger_type, task_id, description, report, source
        )

    validate_message = _rust_validate_message
    generate_trace_id = _rust_generate_trace_id
    priority_to_number = _rust_priority_to_number
    number_to_priority = _rust_number_to_priority

    def get_message_summary(  # type: ignore[misc]
        msg: AgentMessage, max_length: int = 100
    ) -> str:
        return _rust_get_message_summary(msg, max_length)

    build_message = create_message
    is_valid_message = validate_message
except Exception:
    pass


# ============================================================================
# 从根目录 protocol.py 迁移的类（TASK-FIX-PROTO-001）
# 用于解决 ai_adapter.py 等模块的导入问题
# ============================================================================

class ChatMessage:
    """聊天消息类 - 用于AI对话上下文"""

    def __init__(self, role: str, content: str):
        self.role = role
        self.content = content

    def to_dict(self) -> dict[str, str]:
        """转换为字典格式"""
        return {"role": self.role, "content": self.content}


class BaseProtocol:
    """基础协议类 - 请求构建和响应解析"""

    @staticmethod
    def generate_request_id() -> str:
        """生成唯一请求ID"""
        return str(uuid.uuid4())

    @staticmethod
    def build_request(
        request_type: str,
        content: str,
        context: list[ChatMessage],
        model_name: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        timeout: int = 30,
        retry_times: int = 2
    ) -> dict[str, Any]:
        """构建标准化请求"""
        if model_name is None:
            try:
                from core.config import config
                raw_model: Any = cast(Any, config).get("ai.default_model", "qwen3:8b")
                model_name = cast(str | None, raw_model)
            except ImportError:
                model_name = "qwen3:8b"

        limited_context = context[-3:] if len(context) > 3 else context
        context_dict = [msg.to_dict() for msg in limited_context]

        return {
            "request_id": BaseProtocol.generate_request_id(),
            "type": request_type,
            "content": content,
            "context": context_dict,
            "model_config": {
                "model_name": model_name,
                "temperature": temperature,
                "max_tokens": max_tokens
            },
            "callback_info": {
                "timeout": timeout,
                "retry_times": retry_times
            }
        }

    @staticmethod
    def parse_response(raw_response: str, request_id: str) -> dict[str, Any]:
        """解析响应"""
        import json

        try:
            response_json: Any = json.loads(raw_response)

            if isinstance(response_json, list):
                response_list = cast(list[Any], response_json)
                if len(response_list) > 0 and isinstance(response_list[0], dict):
                    first_item = cast(dict[str, Any], response_list[0])
                    return {
                        "request_id": request_id,
                        "type": first_item.get("type", "chat"),
                        "content": first_item.get("content", str(response_list)),
                        "success": True,
                        "error_msg": ""
                    }
                return {
                    "request_id": request_id,
                    "type": "chat",
                    "content": str(response_list),
                    "success": True,
                    "error_msg": ""
                }

            content = raw_response

            if isinstance(response_json, dict):
                response_data = cast(dict[str, Any], response_json)

                if "content" in response_data and response_data["content"]:
                    content = response_data["content"]
                elif "message" in response_data and response_data["message"]:
                    content = response_data["message"]
                elif "observation" in response_data:
                    insight = response_data.get("insight", "")
                    suggestion = response_data.get("suggestion", "")
                    observation = response_data["observation"]
                    if insight and suggestion:
                        content = f"观察: {observation}\n洞察: {insight}\n建议: {suggestion}"
                    elif insight:
                        content = f"观察: {observation}\n洞察: {insight}"
                    elif suggestion:
                        content = f"观察: {observation}\n建议: {suggestion}"
                    else:
                        content = f"观察: {observation}"
                else:
                    meaningful_fields: dict[str, Any] = {
                        k: v for k, v in response_data.items()
                        if v and k not in ("action", "type")
                    }
                    if meaningful_fields:
                        content = json.dumps(meaningful_fields, ensure_ascii=False)

                return {
                    "request_id": request_id,
                    "type": response_data.get("type", response_data.get("action", "chat")),
                    "content": content,
                    "success": True,
                    "error_msg": ""
                }

            return {
                "request_id": request_id,
                "type": "chat",
                "content": raw_response,
                "success": True,
                "error_msg": ""
            }
        except json.JSONDecodeError:
            return {
                "request_id": request_id,
                "type": "chat",
                "content": raw_response,
                "success": True,
                "error_msg": ""
            }
