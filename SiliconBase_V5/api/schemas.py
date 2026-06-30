"""
SiliconBase V5 API Schema - Pydantic模型定义
提供WebSocket和API消息的格式验证

作者: SiliconBase Team
版本: 1.0.0
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, validator

from core.task.task_status import TaskStatus

# ============================================================================
# WebSocket消息类型枚举
# ============================================================================

class MessageType(str, Enum):
    """WebSocket消息类型"""
    CHAT = "chat"           # 聊天消息
    VOICE = "voice"         # 语音消息
    COMMAND = "command"     # 命令消息
    PAUSE = "pause"         # 暂停任务
    RESUME = "resume"       # 恢复任务
    STATUS = "status"       # 状态更新
    PING = "ping"           # 心跳
    PONG = "pong"           # 心跳响应
    AUTH = "auth"           # 认证消息
    USER_INPUT = "user_input"  # 用户输入
    CONFIRM_RESPONSE = "confirm_response"  # 确认响应
    MODE_SWITCH_REQUEST = "mode_switch_request"  # 模式切换请求
    ACCEPT_WEAK_PROPOSAL = "accept_weak_proposal"  # 接受弱连接提议
    DISMISS_WEAK_PROPOSAL = "dismiss_weak_proposal"  # 忽略弱连接提议
    TIMEOUT_WEAK_PROPOSAL = "timeout_weak_proposal"  # 弱连接提议超时


class ChatRole(str, Enum):
    """聊天消息角色"""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class SystemStatus(str, Enum):
    """系统状态"""
    OK = "ok"
    DEGRADED = "degraded"
    MAINTENANCE = "maintenance"
    DOWN = "down"


# ============================================================================
# WebSocket消息模型
# ============================================================================

class WebSocketMessage(BaseModel):
    """
    WebSocket消息契约

    所有WebSocket消息必须符合此格式
    """
    type: MessageType = Field(..., description="消息类型")
    message: str | None = Field(None, description="消息内容")
    session_id: str | None = Field(None, description="会话ID")
    timestamp: str | float | None = Field(
        default_factory=lambda: datetime.now().isoformat(),
        description="时间戳"
    )
    metadata: dict[str, Any] | None = Field(None, description="附加元数据")

    @validator('type', pre=True)
    def validate_type(cls, v):
        """验证消息类型"""
        if isinstance(v, str):
            try:
                return MessageType(v)
            except ValueError as _exc:
                raise ValueError(f"无效的消息类型: {v}. 允许的值为: {[t.value for t in MessageType]}") from _exc
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "type": "chat",
                "message": "你好",
                "session_id": "sess_abc123",
                "timestamp": "2024-01-01T00:00:00",
                "metadata": {}
            }
        }


class ChatMessage(BaseModel):
    """聊天消息格式"""
    role: ChatRole = Field(..., description="角色: user/assistant/system")
    content: str = Field(..., min_length=1, max_length=50000, description="消息内容")
    timestamp: str | float | None = Field(
        default_factory=lambda: datetime.now().isoformat(),
        description="时间戳"
    )

    @validator('role', pre=True)
    def validate_role(cls, v):
        """验证角色"""
        if isinstance(v, str):
            try:
                return ChatRole(v)
            except ValueError as _exc:
                allowed = [r.value for r in ChatRole]
                raise ValueError(f"角色必须是其中之一: {allowed}, 得到: {v}") from _exc
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "role": "user",
                "content": "你好，请介绍一下自己",
                "timestamp": "2024-01-01T00:00:00"
            }
        }


class VoiceMessage(BaseModel):
    """语音消息格式"""
    type: str = Field(default="voice", description="消息类型")
    audio_data: str = Field(..., min_length=1, description="Base64编码的音频数据")
    session_id: str = Field(..., min_length=1, description="会话ID")
    timestamp: str | float | None = Field(
        default_factory=lambda: datetime.now().isoformat(),
        description="时间戳"
    )
    format: str | None = Field(default="wav", description="音频格式")
    sample_rate: int | None = Field(default=16000, ge=8000, le=48000, description="采样率")

    @validator('type')
    def validate_type(cls, v):
        """确保类型为voice"""
        if v != "voice":
            raise ValueError(f"语音消息类型必须是 'voice', 得到: {v}")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "type": "voice",
                "audio_data": "base64_encoded_audio_data...",
                "session_id": "sess_abc123",
                "timestamp": "2024-01-01T00:00:00",
                "format": "wav",
                "sample_rate": 16000
            }
        }


class CommandMessage(BaseModel):
    """命令消息格式"""
    type: str = Field(default="command", description="消息类型")
    command: str = Field(..., min_length=1, max_length=100, description="命令名称")
    params: dict[str, Any] | None = Field(default_factory=dict, description="命令参数")
    session_id: str = Field(..., min_length=1, description="会话ID")
    command_id: str | None = Field(None, description="命令ID")

    @validator('type')
    def validate_type(cls, v):
        """确保类型为command"""
        if v != "command":
            raise ValueError(f"命令消息类型必须是 'command', 得到: {v}")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "type": "command",
                "command": "create_task",
                "params": {"name": "示例任务"},
                "session_id": "sess_abc123",
                "command_id": "cmd_001"
            }
        }


class AuthMessage(BaseModel):
    """认证消息格式"""
    type: str = Field(default="auth", description="消息类型")
    token: str = Field(..., min_length=1, description="认证令牌")
    user_id: str | None = Field(None, description="用户ID")

    @validator('type')
    def validate_type(cls, v):
        """确保类型为auth"""
        if v != "auth":
            raise ValueError(f"认证消息类型必须是 'auth', 得到: {v}")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "type": "auth",
                "token": "sk-test-1234567890",
                "user_id": "user_test_1"
            }
        }


class UserInputMessage(BaseModel):
    """用户输入消息格式"""
    type: str = Field(default="user_input", description="消息类型")
    content: str = Field(..., min_length=1, max_length=10000, description="输入内容")
    session_id: str | None = Field(None, description="会话ID")

    @validator('type')
    def validate_type(cls, v):
        """确保类型为user_input"""
        if v != "user_input":
            raise ValueError(f"用户输入消息类型必须是 'user_input', 得到: {v}")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "type": "user_input",
                "content": "帮我创建一个任务",
                "session_id": "sess_abc123"
            }
        }


class ConfirmResponseMessage(BaseModel):
    """确认响应消息格式"""
    type: str = Field(default="confirm_response", description="消息类型")
    request_id: str = Field(..., min_length=1, description="确认请求ID")
    action: str = Field(..., description="操作: confirm/reject")
    reason: str | None = Field(None, max_length=1000, description="拒绝原因")

    @validator('type')
    def validate_type(cls, v):
        """确保类型为confirm_response"""
        if v != "confirm_response":
            raise ValueError(f"确认响应消息类型必须是 'confirm_response', 得到: {v}")
        return v

    @validator('action')
    def validate_action(cls, v):
        """验证action值"""
        if v not in ["confirm", "reject"]:
            raise ValueError(f"action必须是 'confirm' 或 'reject', 得到: {v}")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "type": "confirm_response",
                "request_id": "req_abc123",
                "action": "confirm",
                "reason": None
            }
        }


class ModeSwitchRequestMessage(BaseModel):
    """模式切换请求消息格式"""
    type: str = Field(default="mode_switch_request", description="消息类型")
    target_mode: str = Field(..., min_length=1, description="目标模式: daily/focus，兼容 chat/task")
    reason: str | None = Field(default="", description="切换原因")

    @validator('type')
    def validate_type(cls, v):
        """确保类型为mode_switch_request"""
        if v != "mode_switch_request":
            raise ValueError(f"模式切换请求类型必须是 'mode_switch_request', 得到: {v}")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "type": "mode_switch_request",
                "target_mode": "focus",
                "reason": "开始专注工作"
            }
        }


class WeakProposalActionMessage(BaseModel):
    """弱连接提议操作消息格式（接受/忽略/超时）"""
    type: str = Field(..., description="消息类型")
    anchor_id: str = Field(..., min_length=1, description="锚点ID")
    message: str | None = Field(default="", description="附加消息（接受时可用）")

    @validator('type')
    def validate_type(cls, v):
        """确保类型为允许的弱连接操作"""
        allowed = {"accept_weak_proposal", "dismiss_weak_proposal", "timeout_weak_proposal"}
        if v not in allowed:
            raise ValueError(f"弱连接操作类型必须是 {allowed}, 得到: {v}")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "type": "accept_weak_proposal",
                "anchor_id": "anc_abc123",
                "message": "帮我处理"
            }
        }


class PingMessage(BaseModel):
    """心跳消息格式"""
    type: str = Field(default="ping", description="消息类型")
    timestamp: str | float | None = Field(
        default_factory=lambda: datetime.now().timestamp(),
        description="时间戳"
    )

    @validator('type')
    def validate_type(cls, v):
        """确保类型为ping"""
        if v != "ping":
            raise ValueError(f"心跳消息类型必须是 'ping', 得到: {v}")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "type": "ping",
                "timestamp": 1700000000.0
            }
        }


# ============================================================================
# API请求/响应模型
# ============================================================================

class TaskCreateRequest(BaseModel):
    """创建任务请求"""
    description: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="任务描述"
    )
    task_type: str | None = Field(default="simple", description="任务类型")
    priority: int | None = Field(
        default=2,
        ge=1,
        le=5,
        description="优先级 1-5"
    )
    metadata: dict[str, Any] | None = Field(default=None, description="附加元数据")
    user_id: str | None = Field(default=None, description="用户ID")

    class Config:
        json_schema_extra = {
            "example": {
                "description": "创建一个新文件",
                "task_type": "simple",
                "priority": 2,
                "metadata": {},
                "user_id": "user_test_1"
            }
        }


class TaskResponse(BaseModel):
    """任务响应"""
    task_id: str = Field(..., description="任务ID")
    status: TaskStatus = Field(..., description="任务状态")
    description: str = Field(..., description="任务描述")
    created_at: str | float = Field(..., description="创建时间")
    completed_at: str | float | None = Field(None, description="完成时间")
    result: Any | None = Field(None, description="执行结果")
    user_id: str | None = Field(None, description="用户ID")

    @validator('status', pre=True)
    def validate_status(cls, v):
        """验证状态"""
        if isinstance(v, str):
            try:
                return TaskStatus(v)
            except ValueError as _exc:
                raise ValueError(f"无效的任务状态: {v}") from _exc
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "task_id": "task_abc123",
                "status": "pending",
                "description": "创建一个新文件",
                "created_at": "2024-01-01T00:00:00",
                "completed_at": None,
                "result": None,
                "user_id": "user_test_1"
            }
        }


class SessionCreateRequest(BaseModel):
    """创建会话请求"""
    user_id: str | None = Field(default="default", description="用户ID")
    metadata: dict[str, Any] | None = Field(default=None, description="会话元数据")

    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "user_test_1",
                "metadata": {"source": "web", "language": "zh-CN"}
            }
        }


class SessionResponse(BaseModel):
    """会话响应"""
    session_id: str = Field(..., description="会话ID")
    user_id: str = Field(..., description="用户ID")
    created_at: str | float = Field(..., description="创建时间")
    status: str = Field(default="active", description="会话状态")
    last_active: str | float | None = Field(None, description="最后活跃时间")
    message_count: int | None = Field(default=0, ge=0, description="消息数量")

    class Config:
        json_schema_extra = {
            "example": {
                "session_id": "sess_abc123",
                "user_id": "user_test_1",
                "created_at": "2024-01-01T00:00:00",
                "status": "active",
                "last_active": "2024-01-01T00:00:00",
                "message_count": 0
            }
        }


class ChatRequest(BaseModel):
    """聊天请求模型"""
    message: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="用户输入的消息"
    )
    session_id: str | None = Field(default=None, description="会话ID，为空则创建新会话")
    context: list[ChatMessage] | None = Field(default_factory=list, description="上下文消息列表")
    model: str | None = Field(default="default", description="使用的模型名称")
    stream: bool | None = Field(default=False, description="是否流式返回")
    temperature: float | None = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="采样温度"
    )
    max_tokens: int | None = Field(
        default=2048,
        ge=1,
        le=8192,
        description="最大生成token数"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "message": "你好，请介绍一下自己",
                "session_id": "sess_abc123",
                "context": [],
                "model": "default",
                "stream": False,
                "temperature": 0.7,
                "max_tokens": 2048
            }
        }


class ChatResponse(BaseModel):
    """聊天响应模型"""
    success: bool = Field(..., description="是否成功")
    response: str = Field(..., description="AI回复内容")
    session_id: str = Field(..., description="会话ID")
    message_id: str = Field(..., description="消息ID")
    usage: dict[str, int] | None = Field(default=None, description="Token使用情况")
    timestamp: str | float = Field(..., description="响应时间戳")
    error_code: str | None = Field(default=None, description="错误码(失败时返回)")

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "response": "你好！我是SiliconBase AI助手...",
                "session_id": "sess_abc123",
                "message_id": "msg_xyz789",
                "usage": {"prompt_tokens": 10, "completion_tokens": 50, "total_tokens": 60},
                "timestamp": "2024-01-01T00:00:00"
            }
        }


class StreamChunk(BaseModel):
    """流式响应块模型"""
    type: str = Field(..., description="块类型: content/done/error")
    data: str | None = Field(default=None, description="内容数据")
    session_id: str | None = Field(default=None, description="会话ID")
    message_id: str | None = Field(default=None, description="消息ID")
    timestamp: str | float | None = Field(None, description="时间戳")

    @validator('type')
    def validate_type(cls, v):
        """验证类型"""
        allowed = ["content", "done", "error", "stream_start", "stream_chunk", "stream_end"]
        if v not in allowed:
            raise ValueError(f"类型必须是其中之一: {allowed}, 得到: {v}")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "type": "content",
                "data": "你好",
                "session_id": "sess_abc123",
                "message_id": "msg_xyz789"
            }
        }


# ============================================================================
# 监控相关模型
# ============================================================================

class SystemStatusResponse(BaseModel):
    """系统状态响应"""
    status: SystemStatus = Field(..., description="系统状态")
    timestamp: str | float = Field(..., description="时间戳")
    version: str = Field(..., description="系统版本")
    uptime: float = Field(..., ge=0, description="运行时间（秒）")
    components: dict[str, Any] = Field(..., description="组件状态")

    @validator('status', pre=True)
    def validate_status(cls, v):
        """验证状态"""
        if isinstance(v, str):
            try:
                return SystemStatus(v)
            except ValueError as _exc:
                raise ValueError(f"无效的系统状态: {v}") from _exc
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "status": "ok",
                "timestamp": "2024-01-01T00:00:00",
                "version": "1.0.0",
                "uptime": 3600.0,
                "components": {"database": "ok", "ai_service": "ok"}
            }
        }


class StateContainerInfo(BaseModel):
    """状态容器信息"""
    name: str = Field(..., min_length=1, description="容器名称")
    description: str = Field(..., description="描述")
    last_updated: str | float = Field(..., description="最后更新时间")
    update_count: int = Field(..., ge=0, description="更新次数")

    class Config:
        json_schema_extra = {
            "example": {
                "name": "task_states",
                "description": "任务状态容器",
                "last_updated": "2024-01-01T00:00:00",
                "update_count": 100
            }
        }


class MonitoringDataResponse(BaseModel):
    """监控数据响应"""
    registry_info: dict[str, Any] = Field(..., description="注册表信息")
    states: dict[str, dict[str, Any]] = Field(..., description="状态数据")
    timestamp: str | float = Field(..., description="时间戳")

    class Config:
        json_schema_extra = {
            "example": {
                "registry_info": {"version": "1.0.0"},
                "states": {},
                "timestamp": "2024-01-01T00:00:00"
            }
        }


class HealthCheckResponse(BaseModel):
    """健康检查响应"""
    status: str = Field(..., description="健康状态")
    timestamp: str | float = Field(..., description="时间戳")
    version: str | None = Field(None, description="版本")
    services: dict[str, Any] | None = Field(None, description="服务状态")

    class Config:
        json_schema_extra = {
            "example": {
                "status": "healthy",
                "timestamp": "2024-01-01T00:00:00",
                "version": "1.0.0",
                "services": {"database": "ok", "redis": "ok"}
            }
        }


# ============================================================================
# 错误响应模型
# ============================================================================

class ErrorResponse(BaseModel):
    """错误响应模型"""
    error: str = Field(..., description="错误类型")
    message: str = Field(..., description="错误消息")
    code: int = Field(..., ge=100, le=599, description="HTTP状态码或错误码")
    details: dict[str, Any] | None = Field(default=None, description="详细错误信息")
    timestamp: str | float = Field(..., description="错误发生时间戳")

    class Config:
        json_schema_extra = {
            "example": {
                "error": "ValidationError",
                "message": "请求参数验证失败",
                "code": 400,
                "details": {"field": "message", "error": "不能为空"},
                "timestamp": "2024-01-01T00:00:00"
            }
        }


class WebSocketErrorResponse(BaseModel):
    """WebSocket错误响应"""
    type: str = Field(default="error", description="消息类型")
    message: str = Field(..., description="错误消息")
    code: str | None = Field(None, description="错误码")
    timestamp: str | float | None = Field(
        default_factory=lambda: datetime.now().timestamp(),
        description="时间戳"
    )
    details: dict[str, Any] | None = Field(None, description="详细错误信息")

    class Config:
        json_schema_extra = {
            "example": {
                "type": "error",
                "message": "消息格式错误",
                "code": "VALIDATION_ERROR",
                "timestamp": 1700000000.0,
                "details": {}
            }
        }


# ============================================================================
# 语音相关模型
# ============================================================================

class VoiceInputRequest(BaseModel):
    """语音输入请求模型"""
    text: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="语音识别的文本内容"
    )
    session_id: str = Field(..., min_length=1, description="会话ID")

    class Config:
        json_schema_extra = {
            "example": {
                "text": "帮我打开微信",
                "session_id": "sess_abc123"
            }
        }


class VoiceInputResponse(BaseModel):
    """语音输入响应模型"""
    success: bool = Field(..., description="是否成功")
    result: dict[str, Any] = Field(..., description="处理结果")
    mode: str = Field(..., description="处理模式: chat_alignment/task")
    session_id: str = Field(..., description="会话ID")
    timestamp: str | float = Field(..., description="响应时间戳")

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "result": {"text": "好的，我来帮你"},
                "mode": "chat_alignment",
                "session_id": "sess_abc123",
                "timestamp": "2024-01-01T00:00:00"
            }
        }


# ============================================================================
# 验证函数
# ============================================================================

def validate_websocket_message(data: dict[str, Any]) -> WebSocketMessage:
    """
    验证WebSocket消息

    在接收WebSocket消息时调用，确保格式正确

    Args:
        data: 原始消息字典

    Returns:
        WebSocketMessage: 验证后的消息对象

    Raises:
        ValidationError: 验证失败
    """
    return WebSocketMessage(**data)


def validate_chat_message(data: dict[str, Any]) -> ChatMessage:
    """验证聊天消息"""
    return ChatMessage(**data)


def validate_voice_message(data: dict[str, Any]) -> VoiceMessage:
    """验证语音消息"""
    return VoiceMessage(**data)


def validate_command_message(data: dict[str, Any]) -> CommandMessage:
    """验证命令消息"""
    return CommandMessage(**data)


def validate_auth_message(data: dict[str, Any]) -> AuthMessage:
    """验证认证消息"""
    return AuthMessage(**data)


def validate_user_input_message(data: dict[str, Any]) -> UserInputMessage:
    """验证用户输入消息"""
    return UserInputMessage(**data)


def validate_confirm_response_message(data: dict[str, Any]) -> ConfirmResponseMessage:
    """验证确认响应消息"""
    return ConfirmResponseMessage(**data)


def validate_ping_message(data: dict[str, Any]) -> PingMessage:
    """验证心跳消息"""
    return PingMessage(**data)


def validate_message_by_type(data: dict[str, Any]) -> BaseModel:
    """
    根据消息类型自动选择验证器

    Args:
        data: 原始消息字典

    Returns:
        BaseModel: 验证后的消息对象

    Raises:
        ValidationError: 验证失败
        ValueError: 未知消息类型
    """
    msg_type = data.get("type", "unknown")

    validators = {
        "chat": validate_chat_message,
        "voice": validate_voice_message,
        "command": validate_command_message,
        "auth": validate_auth_message,
        "user_input": validate_user_input_message,
        "confirm_response": validate_confirm_response_message,
        "mode_switch_request": lambda d: ModeSwitchRequestMessage(**d),
        "accept_weak_proposal": lambda d: WeakProposalActionMessage(**d),
        "dismiss_weak_proposal": lambda d: WeakProposalActionMessage(**d),
        "timeout_weak_proposal": lambda d: WeakProposalActionMessage(**d),
        "ping": validate_ping_message,
    }

    if msg_type in validators:
        return validators[msg_type](data)
    else:
        # 对于未知类型，使用通用验证
        return validate_websocket_message(data)


def create_error_response(message: str, code: str | None = None, details: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    创建WebSocket错误响应

    Args:
        message: 错误消息
        code: 错误码
        details: 详细错误信息

    Returns:
        Dict: 错误响应字典，格式为 {"type": "error", "timestamp": ..., "data": {"message": ..., "code": ..., "details": ...}}
    """
    return {
        "type": "error",
        "timestamp": datetime.now().timestamp(),
        "data": {
            "message": message,
            **({"code": code} if code else {}),
            **({"details": details} if details else {})
        }
    }


# ============================================================================
# 导出所有模型
# ============================================================================

__all__ = [
    # 枚举类型
    "MessageType",
    "ChatRole",
    "TaskStatus",
    "SystemStatus",

    # WebSocket消息模型
    "WebSocketMessage",
    "ChatMessage",
    "VoiceMessage",
    "CommandMessage",
    "AuthMessage",
    "UserInputMessage",
    "ConfirmResponseMessage",
    "ModeSwitchRequestMessage",
    "WeakProposalActionMessage",
    "PingMessage",

    # API请求/响应模型
    "TaskCreateRequest",
    "TaskResponse",
    "SessionCreateRequest",
    "SessionResponse",
    "ChatRequest",
    "ChatResponse",
    "StreamChunk",

    # 监控模型
    "SystemStatusResponse",
    "StateContainerInfo",
    "MonitoringDataResponse",
    "HealthCheckResponse",

    # 错误模型
    "ErrorResponse",
    "WebSocketErrorResponse",

    # 语音模型
    "VoiceInputRequest",
    "VoiceInputResponse",

    # 验证函数
    "validate_websocket_message",
    "validate_chat_message",
    "validate_voice_message",
    "validate_command_message",
    "validate_auth_message",
    "validate_user_input_message",
    "validate_confirm_response_message",
    "validate_ping_message",
    "validate_message_by_type",
    "create_error_response",
]
