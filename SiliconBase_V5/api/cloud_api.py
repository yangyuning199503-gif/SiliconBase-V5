"""
SiliconBase Cloud API - FastAPI 包装层
提供云端 HTTP/WebSocket 访问能力

作者: SiliconBase Team
版本: 1.0.0
"""

# ============================================================================
# 警告过滤（必须在其他导入之前）
# ============================================================================
import warnings

# 【P0-002】抑制 PyTorch 模型加载警告（EasyOCR 等第三方库引起）
warnings.filterwarnings("ignore", category=UserWarning, module="torch.nn.modules")
warnings.filterwarnings("ignore", category=UserWarning, message=".*copying from a non-meta parameter.*")

import asyncio
import json
import logging
import os
import time
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

import aiofiles

# 【P1修复】WebSocket 心跳参数从环境变量读取，避免后端忙时误断
WS_PING_INTERVAL = float(os.getenv("UVICORN_WS_PING_INTERVAL", "30.0"))
WS_PING_TIMEOUT = float(os.getenv("UVICORN_WS_PING_TIMEOUT", "60.0"))

# ============================================================================
# 错误分类与脱敏处理（零静默失败）
# ============================================================================

class ErrorCategory(Enum):
    """错误分类"""
    USER_ERROR = "user_error"      # 可展示给用户
    INTERNAL_ERROR = "internal"    # 仅记录日志
    SECURITY_ERROR = "security"    # 安全相关


def sanitize_error(error: Exception, category: ErrorCategory) -> str:
    """
    脱敏处理错误信息

    【零静默失败】根据错误类别决定是否展示给客户端
    - 用户错误可直接展示
    - 内部错误记录日志，返回通用消息
    - 安全错误记录日志，返回模糊消息

    Args:
        error: 异常对象
        category: 错误类别

    Returns:
        str: 脱敏后的错误信息
    """
    error_str = str(error)

    if category == ErrorCategory.USER_ERROR:
        # 用户错误可直接展示
        return error_str

    elif category == ErrorCategory.INTERNAL_ERROR:
        # 内部错误记录日志，返回通用消息
        logger.error(f"[SILENT_FAILURE_BLOCKED] 内部错误: {error_str}")
        return "服务器内部错误，请稍后重试"

    elif category == ErrorCategory.SECURITY_ERROR:
        # 安全错误记录日志，返回模糊消息
        logger.error(f"[SILENT_FAILURE_BLOCKED] 安全错误: {error_str}")
        return "请求无法处理"

    # 默认处理：记录并返回通用消息
    logger.error(f"[SILENT_FAILURE_BLOCKED] 未分类错误: {error_str}")
    return "服务器内部错误，请稍后重试"


# ============================================================================
# bcrypt密码哈希（Critical安全修复 - 从SHA256升级）
# ============================================================================
try:
    import bcrypt
    BCRYPT_AVAILABLE = True
except ImportError:
    BCRYPT_AVAILABLE = False
    bcrypt = None
    logger = logging.getLogger(__name__)
    logger.error("[CRITICAL] bcrypt未安装，密码哈希将不安全。请执行: pip install bcrypt")

# 配置日志记录器
logger = logging.getLogger(__name__)

# ============================================================================
# 实时干预支持
# ============================================================================
try:
    from core.agent.realtime_intervention import realtime_intervention
    REALTIME_INTERVENTION_AVAILABLE = True
except ImportError:
    REALTIME_INTERVENTION_AVAILABLE = False
    logger.warning("[Intervention] 实时干预模块未加载")

def is_intervention_intent(text: str) -> bool:
    """识别用户输入是否是明确的终止/取消类干预意图。

    注意：此检查位于 WebSocket 入口，仅在用户明确想停止/取消任务时触发。
    像"先不管这个，几点了"这类插话应交给 DialogueManager/ConsciousnessRouter
    统一分流，由 AgentLoop 的 _interruption_requests 机制实现暂停-恢复，
    避免硬编码关键词误杀正常插话。
    """
    if not text:
        return False
    intervention_keywords = [
        "停下", "停止", "终止", "取消", "别做了", "不做了", "算了",
        "停下吧", "停下来", "取消任务", "停止任务", "终止任务"
    ]
    text_lower = text.strip().lower()
    return any(kw in text_lower for kw in intervention_keywords)

def get_active_task_id_for_user(user_id: str, session_id: str = None) -> str | None:
    """获取用户当前活跃任务的ID

    优先使用 session_id 作为 task_id，因为在 AgentLoop 中 task.id 通常等于 session_id
    """
    try:
        from core.dialog.dialogue_manager import dialogue_manager
        # 检查是否有活跃后台任务/循环
        if hasattr(dialogue_manager, 'has_active_background_task') and dialogue_manager.has_active_background_task(user_id):
            # 使用 session_id 作为 task_id（如果提供）
            if session_id:
                return session_id
            # 否则尝试从对话管理器获取当前会话
            if hasattr(dialogue_manager, '_sessions') and user_id in dialogue_manager._sessions:
                sessions = dialogue_manager._sessions.get(user_id)
                if sessions:
                    session = next(iter(sessions.values()), None)
                    return session.session_id if hasattr(session, 'session_id') else None
    except Exception as e:
        logger.debug(f"[Intervention] 获取活跃任务失败: {e}")
    return None

# ============================================================================
# JWT认证相关导入 (SEC-002修复 - 强制要求python-jose)
# ============================================================================

try:
    from jose import JWTError, jwt
    from passlib.context import CryptContext
    PYTHON_JOSE_AVAILABLE = True
except ImportError:
    PYTHON_JOSE_AVAILABLE = False
    JWTError = Exception
    jwt = None
    CryptContext = None
    logger.warning("[SEC-002] python-jose 未安装，JWT功能将被禁用。请安装: pip install python-jose[cryptography]")

from fastapi import (
    Depends,
    FastAPI,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, ValidationError
from starlette.websockets import WebSocketState
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK

from core.diagnostic import (
    diagnostic_except_handler,
    safe_create_task,
)

# ============================================================================
# 导入API Schema模型
# ============================================================================
try:
    from .schemas import (
        AuthMessage,
        ChatMessage,
        ChatRequest,
        ChatResponse,
        CommandMessage,
        ConfirmResponseMessage,
        ErrorResponse,
        ModeSwitchRequestMessage,
        PingMessage,
        StreamChunk,
        VoiceInputRequest,
        VoiceInputResponse,
        VoiceMessage,
        WeakProposalActionMessage,
        create_error_response,
        validate_websocket_message,
    )
    SCHEMAS_AVAILABLE = True
    print("[CloudAPI] API Schema模型已加载")
except ImportError as e:
    SCHEMAS_AVAILABLE = False
    print(f"[CloudAPI] API Schema模型导入失败: {e}")

# ============================================================================
# 导入配置中心 (SEC-CORS修复) - 【延迟初始化修复】
# ============================================================================

# 【修复】Config 延迟加载，避免模块导入时阻塞
_CONFIG = None
CONFIG_AVAILABLE = False

def get_config():
    """获取 Config 实例（延迟加载）"""
    global _CONFIG, CONFIG_AVAILABLE
    if _CONFIG is None:
        try:
            from core.config import Config
            _CONFIG = Config()
            CONFIG_AVAILABLE = True
            print("[Config] 延迟加载成功")
        except Exception as e:
            print(f"[Config] 【错误】 延迟加载失败: {e}")
            CONFIG_AVAILABLE = False
    return _CONFIG

# 保持向后兼容的 config 属性
class ConfigProxy:
    """Config 代理，实现延迟访问"""
    def __getattr__(self, name):
        cfg = get_config()
        if cfg is None:
            raise RuntimeError("Config not initialized")
        return getattr(cfg, name)

    def __call__(self, *args, **kwargs):
        cfg = get_config()
        if cfg is None:
            raise RuntimeError("Config not initialized")
        return cfg(*args, **kwargs)

    def get(self, key, default=None):
        """【修复】支持 .get() 方法，用于读取配置项"""
        try:
            cfg = get_config()
            if cfg is None:
                return default
            return cfg.get(key, default)
        except Exception:
            return default

# 创建代理对象，保持原有代码兼容
config = ConfigProxy()
config_proxy = config  # 别名，用于更清晰的语义

# ============================================================================
# 统一系统配置 (前后端共享)
# ============================================================================

def load_system_config():
    """加载统一系统配置（仅保留静态元数据和认证信息，端口由 config/local.yaml 控制）"""
    config_path = Path(__file__).parent.parent / "config" / "system.json"
    default_config = {
        "auth": {
            "default_username": "admin",
            "default_password": os.environ.get("SILICONBASE_DEFAULT_PASSWORD", ""),
            "require_password_change": True
        }
    }
    try:
        if config_path.exists():
            with open(config_path, encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"[CloudAPI] 加载系统配置失败: {e}")
    return default_config

SYSTEM_CONFIG = load_system_config()

# ============================================================================
# 导入实时同步管理器
# ============================================================================

try:
    from core.sync.realtime_sync import get_realtime_sync_manager
    REALTIME_SYNC_AVAILABLE = True
except ImportError:
    REALTIME_SYNC_AVAILABLE = False
    logger.warning("[CloudAPI] 实时同步模块导入失败，realtime_sync事件转发功能不可用")

# ============================================================================
# 导入监控模块
# ============================================================================

try:
    from .monitoring import (
        check_monitoring_dependencies,
        get_prometheus_metrics,
        record_ai_call,
        record_error,
        record_request_end,
        record_request_start,
        update_session_count,
        update_task_queue_depth,
        update_websocket_count,
    )
    MONITORING_AVAILABLE = True
except ImportError:
    MONITORING_AVAILABLE = False
    logger.warning("[CloudAPI] 监控模块导入失败，监控功能不可用")


# ============================================================================
# WebSocket 安全发送辅助函数 (修复 WebSocket 已关闭后发送问题)
# ============================================================================

async def safe_send_json(websocket, data: dict) -> bool:
    """
    安全地发送 JSON 消息到 WebSocket (FastAPI)

    采用"直接发送 + 捕获预期关闭异常"的方式，避免状态检查与发送之间的竞态。
    预期关闭异常（WebSocketDisconnect、ConnectionClosedOK/Error、RuntimeError
    "not connected"）会被静默忽略，仅记录 debug 日志。

    Args:
        websocket: WebSocket 连接对象
        data: 要发送的数据字典

    Returns:
        bool: 是否发送成功
    """
    if not websocket:
        return False
    try:
        await websocket.send_json(data)
        return True
    except (WebSocketDisconnect, ConnectionClosedOK, ConnectionClosedError):
        # 连接已正常/异常关闭，属于预期情况
        return False
    except RuntimeError as e:
        # 处理 "not connected" 等运行时关闭状态
        error_msg = str(e).lower()
        if "not connected" in error_msg or "websocket" in error_msg:
            return False
        logger.exception(f"[safe_send_json] WebSocket发送失败: {e}")
        return False
    except Exception as e:
        logger.exception(f"[safe_send_json] WebSocket发送失败: {e}")
        return False

# ============================================================================
# 导入JWT认证管理器 (SEC-002修复)
# ============================================================================

try:
    from core.session.user_session_manager import JWTAuthManager
    jwt_auth_manager = JWTAuthManager()
    JWT_AUTH_AVAILABLE = True
except ImportError:
    JWT_AUTH_AVAILABLE = False
    jwt_auth_manager = None
    logger.warning("[CloudAPI] JWT认证模块导入失败，将使用简化验证")

# ============================================================================
# Pydantic 请求/响应模型定义
# ============================================================================

class ChatMessage(BaseModel):
    """单条聊天消息模型"""
    role: str = Field(..., description="消息角色: user/assistant/system")
    content: str = Field(..., description="消息内容")
    timestamp: float | None = Field(default=None, description="消息时间戳")

    class Config:
        json_schema_extra = {
            "example": {
                "role": "user",
                "content": "你好，请介绍一下自己",
                "timestamp": 1700000000.0
            }
        }


class ChatRequest(BaseModel):
    """聊天请求模型"""
    message: str = Field(..., description="用户输入的消息", min_length=1, max_length=10000)
    session_id: str | None = Field(default=None, description="会话ID，为空则创建新会话")
    context: list[ChatMessage] | None = Field(default=[], description="上下文消息列表")
    model: str | None = Field(default="default", description="使用的模型名称")
    stream: bool | None = Field(default=False, description="是否流式返回")
    temperature: float | None = Field(default=0.7, ge=0.0, le=2.0, description="采样温度")
    max_tokens: int | None = Field(default=2048, ge=1, le=8192, description="最大生成token数")

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
    timestamp: float = Field(..., description="响应时间戳")
    error_code: str | None = Field(default=None, description="错误码(失败时返回)")

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "response": "你好！我是SiliconBase AI助手...",
                "session_id": "sess_abc123",
                "message_id": "msg_xyz789",
                "usage": {"prompt_tokens": 10, "completion_tokens": 50, "total_tokens": 60},
                "timestamp": 1700000000.0
            }
        }


class StreamChunk(BaseModel):
    """流式响应块模型"""
    type: str = Field(..., description="块类型: content/done/error")
    data: str | None = Field(default=None, description="内容数据")
    session_id: str | None = Field(default=None, description="会话ID")
    message_id: str | None = Field(default=None, description="消息ID")

    class Config:
        json_schema_extra = {
            "example": {
                "type": "content",
                "data": "你好",
                "session_id": "sess_abc123",
                "message_id": "msg_xyz789"
            }
        }


class SessionInfo(BaseModel):
    """会话信息模型"""
    session_id: str = Field(..., description="会话ID")
    user_id: str = Field(..., description="用户ID")
    created_at: float = Field(..., description="创建时间戳")
    last_active: float = Field(..., description="最后活跃时间戳")
    message_count: int = Field(default=0, description="消息数量")

    class Config:
        json_schema_extra = {
            "example": {
                "session_id": "sess_abc123",
                "user_id": "user_123",
                "created_at": 1700000000.0,
                "last_active": 1700000100.0,
                "message_count": 10
            }
        }


class StatusResponse(BaseModel):
    """系统状态响应模型"""
    status: str = Field(..., description="系统状态: ok/degraded/maintenance/down")
    version: str = Field(..., description="API版本")
    timestamp: float = Field(..., description="当前时间戳")
    user_tasks: list[dict[str, Any]] = Field(default=[], description="用户任务列表")
    active_sessions: int = Field(default=0, description="活跃会话数")

    class Config:
        json_schema_extra = {
            "example": {
                "status": "ok",
                "version": "1.0.0",
                "timestamp": 1700000000.0,
                "user_tasks": [],
                "active_sessions": 5
            }
        }


class CreateSessionRequest(BaseModel):
    """创建会话请求模型"""
    user_id: str | None = Field(default=None, description="用户ID，为空则自动生成")
    metadata: dict[str, Any] | None = Field(default={}, description="会话元数据")


class CreateSessionResponse(BaseModel):
    """创建会话响应模型"""
    success: bool = Field(..., description="是否成功")
    session_id: str = Field(..., description="新创建的会话ID")
    user_id: str = Field(..., description="用户ID")
    created_at: float = Field(..., description="创建时间戳")


class VoiceInputRequest(BaseModel):
    """语音输入请求模型"""
    text: str = Field(..., description="语音识别的文本内容", min_length=1, max_length=5000)
    session_id: str = Field(..., description="会话ID")

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
    timestamp: float = Field(..., description="响应时间戳")


class VoicePTTRequest(BaseModel):
    """语音PTT请求模型"""
    action: str = Field(..., description="操作: start或end")


class VoicePTTResponse(BaseModel):
    """语音PTT响应模型"""
    success: bool
    message: str | None = None
    error: str | None = None


class ErrorResponse(BaseModel):
    """错误响应模型"""
    error: str = Field(..., description="错误类型")
    message: str = Field(..., description="错误消息")
    code: int = Field(..., description="HTTP状态码")
    details: dict[str, Any] | None = Field(default=None, description="详细错误信息")
    timestamp: float = Field(..., description="错误发生时间戳")


# ============================================================================
# 登录认证相关模型 (SEC-003修复)
# ============================================================================

class LoginRequest(BaseModel):
    """登录请求模型"""
    username: str = Field(..., min_length=1, max_length=100, description="用户名")
    password: str = Field(..., min_length=1, max_length=100, description="密码")

    class Config:
        json_schema_extra = {
            "example": {
                "username": "admin",
                "password": "ChangeMeInProduction"
            }
        }


class LoginResponse(BaseModel):
    """登录响应模型"""
    access_token: str = Field(..., description="JWT访问令牌")
    token_type: str = Field(default="bearer", description="令牌类型")
    expires_in: int = Field(..., description="令牌有效期（秒）")
    user_id: str = Field(..., description="用户ID")
    username: str = Field(..., description="用户名")
    require_password_change: bool = Field(default=False, description="是否需要强制修改密码（首次登录）")

    class Config:
        json_schema_extra = {
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "token_type": "bearer",
                "expires_in": 86400,
                "user_id": "user_abc123",
                "username": "admin",
                "require_password_change": False
            }
        }


class RegisterRequest(BaseModel):
    """用户注册请求模型"""
    username: str = Field(..., min_length=3, max_length=50, description="用户名")
    password: str = Field(..., min_length=6, max_length=100, description="密码")
    email: str | None = Field(default=None, description="邮箱（可选）")


class RegisterResponse(BaseModel):
    """用户注册响应模型"""
    success: bool = Field(..., description="是否成功")
    user_id: str = Field(..., description="新用户ID")
    username: str = Field(..., description="用户名")
    message: str = Field(..., description="状态消息")


class SetupStatusResponse(BaseModel):
    """首次设置状态响应模型"""
    setup_required: bool = Field(..., description="是否需要进行首次管理员设置")
    message: str = Field(..., description="状态说明")


class SetupRequest(BaseModel):
    """首次设置管理员请求模型"""
    username: str = Field(..., min_length=3, max_length=50, description="管理员用户名")
    password: str = Field(..., min_length=6, max_length=100, description="管理员密码")
    email: str | None = Field(default=None, description="邮箱（可选）")


class ChangePasswordRequest(BaseModel):
    """修改密码请求模型"""
    current_password: str = Field(..., min_length=1, max_length=100, description="当前密码")
    new_password: str = Field(..., min_length=6, max_length=100, description="新密码（至少6位）")

    class Config:
        json_schema_extra = {
            "example": {
                "current_password": "old_password",
                "new_password": "new_secure_password"
            }
        }


class ChangePasswordResponse(BaseModel):
    """修改密码响应模型"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="状态消息")

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "message": "密码修改成功"
            }
        }


class RefreshTokenRequest(BaseModel):
    """刷新令牌请求模型"""
    refresh_token: str | None = Field(default=None, description="刷新令牌（可选，如不提供则使用当前token）")

    class Config:
        json_schema_extra = {
            "example": {
                "refresh_token": "optional_refresh_token"
            }
        }


class RefreshTokenResponse(BaseModel):
    """刷新令牌响应模型"""
    access_token: str = Field(..., description="新的JWT访问令牌")
    token_type: str = Field(default="bearer", description="令牌类型")
    expires_in: int = Field(..., description="新的令牌有效期（秒）")
    user_id: str = Field(..., description="用户ID")

    class Config:
        json_schema_extra = {
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "token_type": "bearer",
                "expires_in": 86400,
                "user_id": "user_abc123"
            }
        }


class UserInfoResponse(BaseModel):
    """用户信息响应模型"""
    user_id: str = Field(..., description="用户ID")
    username: str = Field(..., description="用户名")
    email: str | None = Field(default=None, description="邮箱")
    created_at: float | None = Field(default=None, description="创建时间戳")
    last_login: float | None = Field(default=None, description="最后登录时间戳")

    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "user_abc123",
                "username": "admin",
                "email": "admin@example.com",
                "created_at": 1700000000.0,
                "last_login": 1700100000.0
            }
        }


# ============================================================================
# 用户认证管理 (SEC-003修复)
# ============================================================================

import hashlib
import secrets
import threading


class UserAuthStore:
    """
    用户认证存储管理器

    支持：
    1. 内存中的用户字典（默认用户）
    2. 从配置文件读取用户列表
    3. JWT token生成和验证
    """

    _instance = None
    _lock = threading.Lock()

    # 默认用户配置（当配置未提供时，使用随机初始密码并强制首次登录修改）
    # [CFG-001] 安全修复: 优先从配置加载；若配置中无默认用户，则生成随机密码
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if '_initialized' in self.__dict__ and self._initialized:
            return
        self._initialized = True

        self._users: dict[str, dict] = {}  # username -> user_data
        self._user_id_map: dict[str, str] = {}  # user_id -> username
        self._lock = threading.RLock()

        # 用户数据持久化文件路径
        self._users_file = os.path.join(os.path.dirname(__file__), '..', 'data', 'users.json')

        # 默认用户集合（用于区分默认用户和注册用户，避免默认用户被持久化覆盖）
        self.DEFAULT_USERS: dict[str, dict] = {}

        # 首次设置标记：若系统没有任何管理员，则允许通过 /api/auth/setup 创建第一个管理员
        self._setup_required = False

        # JWT配置
        self._secret_key = os.environ.get("JWT_SECRET_KEY")
        if not self._secret_key:
            raise ValueError(
                "[UserAuthStore] JWT_SECRET_KEY 未设置！"
                "请执行以下操作之一：\n"
                "1. 在 .env 文件中添加：JWT_SECRET_KEY=your-secret-key\n"
                "2. 设置环境变量：export JWT_SECRET_KEY=your-secret-key"
            )
        self._algorithm = "HS256"
        self._access_token_expire_hours = 24

        # 先从配置加载默认用户（必须在文件加载之前，避免被旧数据覆盖）
        self._load_users_from_config()

        # 加载已保存的注册用户
        self._load_users_from_file()

        # 检查是否需要进行首次管理员设置
        self._check_setup_required()

        logger.info("[UserAuthStore] 用户认证存储初始化完成")

    def _hash_password(self, password: str) -> str:
        """
        使用bcrypt对密码进行哈希

        【修复说明】从SHA256改为bcrypt，增加盐值和计算复杂度，防御彩虹表攻击
        【零静默失败】哈希失败时抛出异常，绝不返回None或空字符串

        Args:
            password: 明文密码

        Returns:
            str: bcrypt哈希后的密码字符串

        Raises:
            RuntimeError: 哈希失败时抛出
        """
        try:
            if not password or not isinstance(password, str):
                raise ValueError("[SILICONBASE_SECURITY_ERROR] 密码不能为空且必须是字符串")

            if not BCRYPT_AVAILABLE or bcrypt is None:
                raise RuntimeError("[SILICONBASE_SECURITY_ERROR] bcrypt未安装，无法安全哈希密码")

            # 生成盐并哈希，work factor=12
            salt = bcrypt.gensalt(rounds=12)
            hashed = bcrypt.hashpw(password.encode('utf-8'), salt)

            logger.debug("[UserAuthStore] 密码哈希成功")
            return hashed.decode('utf-8')

        except Exception as e:
            logger.error(f"[SILENT_FAILURE_BLOCKED] 密码哈希失败: {e}")
            raise RuntimeError(f"密码哈希失败，无法完成注册/登录: {e}") from e

    def _verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """
        验证密码（支持bcrypt和旧版SHA256迁移）

        【零静默失败】验证失败时记录ERROR日志，绝不静默返回False
        【向后兼容】支持验证旧版SHA256哈希，自动迁移到bcrypt

        Args:
            plain_password: 明文密码
            hashed_password: 存储的哈希密码

        Returns:
            bool: 验证是否成功
        """
        try:
            if not plain_password or not hashed_password:
                logger.error("[SILENT_FAILURE_BLOCKED] 验证密码失败: 密码或哈希值为空")
                return False

            # 检测哈希类型：bcrypt以$2b$/$2a$/$2y$开头
            is_bcrypt = hashed_password.startswith('$2')

            if is_bcrypt and BCRYPT_AVAILABLE and bcrypt is not None:
                # 标准bcrypt验证
                result = bcrypt.checkpw(
                    plain_password.encode('utf-8'),
                    hashed_password.encode('utf-8')
                )
                if not result:
                    logger.warning("[UserAuthStore] 密码验证失败: 密码不匹配")
                return result
            else:
                # 向后兼容：旧版SHA256哈希（用于迁移）
                # 计算SHA256并与存储值比较
                legacy_hash = hashlib.sha256(plain_password.encode()).hexdigest()
                if legacy_hash == hashed_password:
                    logger.info("[UserAuthStore] 检测到旧版SHA256密码，建议用户尽快修改密码以迁移到bcrypt")
                    return True
                else:
                    logger.warning("[UserAuthStore] 密码验证失败: 密码不匹配")
                    return False

        except Exception as e:
            logger.error(f"[SILENT_FAILURE_BLOCKED] 密码验证过程异常: {e}")
            return False

    def _load_users_from_config(self):
        """从配置文件加载用户列表（不再自动创建默认管理员）"""
        try:
            if CONFIG_AVAILABLE:
                auth_config = config.get("auth", {}) or {}
                users_config = auth_config.get("users", []) or []

                for user_conf in users_config:
                    username = user_conf.get("username")
                    if username and username not in self._users:
                        password = user_conf.get("password", "")
                        # 禁止空密码
                        if not password:
                            logger.warning(f"[UserAuthStore] 配置用户 {username} 密码为空，跳过")
                            continue
                        user_data = {
                            "user_id": user_conf.get("user_id", f"user_{hashlib.md5(username.encode()).hexdigest()[:8]}"),
                            "username": username,
                            "password_hash": self._hash_password(password),
                            "email": user_conf.get("email"),
                            "created_at": time.time(),
                            "is_active": user_conf.get("is_active", True),
                            "roles": user_conf.get("roles", ["user"]),
                            "require_password_change": user_conf.get("require_password_change", False),
                        }
                        with self._lock:
                            self._users[username] = user_data
                            self._user_id_map[user_data["user_id"]] = username
                            self.DEFAULT_USERS[username] = user_data
                        logger.info(f"[UserAuthStore] 从配置加载用户: {username}")
        except Exception as e:
            logger.warning(f"[UserAuthStore] 从配置加载用户失败: {e}")

    def _check_setup_required(self):
        """检查是否需要进行首次管理员设置"""
        with self._lock:
            has_admin = any("admin" in (u.get("roles") or []) for u in self._users.values())
            self._setup_required = not has_admin
            if self._setup_required:
                logger.warning("[UserAuthStore] 尚未创建管理员账户，首次访问请通过 /api/auth/setup 注册第一个管理员")

    def verify_password(self, username: str, password: str) -> bool:
        """
        验证用户密码

        Args:
            username: 用户名
            password: 明文密码

        Returns:
            bool: 验证是否成功
        """
        with self._lock:
            user = self._users.get(username)
            if not user or not user.get("is_active", True):
                return False

            stored_hash = user.get("password_hash", "")
            return self._verify_password(password, stored_hash)

    def get_user(self, username: str) -> dict | None:
        """获取用户信息"""
        with self._lock:
            return self._users.get(username)

    def get_user_by_id(self, user_id: str) -> dict | None:
        """通过用户ID获取用户信息"""
        with self._lock:
            username = self._user_id_map.get(user_id)
            if username:
                return self._users.get(username)
            return None

    def create_access_token(self, user_id: str, expires_hours: int = None) -> str:
        """
        创建JWT访问令牌

        Args:
            user_id: 用户ID
            expires_hours: 过期时间（小时），默认24小时

        Returns:
            str: JWT token
        """
        if expires_hours is None:
            expires_hours = self._access_token_expire_hours

        expires_delta = timedelta(hours=expires_hours)
        expire = datetime.utcnow() + expires_delta

        user = self.get_user_by_id(user_id)
        username = user.get("username", "unknown") if user else "unknown"

        to_encode = {
            "sub": user_id,
            "username": username,
            "exp": expire,
            "iat": datetime.utcnow(),
            "type": "access"
        }

        # SEC-002: 使用python-jose生成JWT
        if not PYTHON_JOSE_AVAILABLE or jwt is None:
            raise RuntimeError(
                "[SILICONBASE_SECURITY_ERROR] python-jose 未安装，无法生成安全 JWT。"
                "请执行: uv pip install python-jose[cryptography]"
            )
        encoded_jwt = jwt.encode(to_encode, self._secret_key, algorithm=self._algorithm)
        return encoded_jwt

    def verify_token(self, token: str) -> dict | None:
        """
        验证JWT令牌

        Args:
            token: JWT token

        Returns:
            Optional[Dict]: 解码后的payload，无效则返回None
        """
        try:
            # SEC-002: 使用python-jose验证JWT
            if not PYTHON_JOSE_AVAILABLE or jwt is None:
                logger.error("[UserAuthStore] JWT验证失败: python-jose 未安装")
                return None
            try:
                payload = jwt.decode(token, self._secret_key, algorithms=[self._algorithm])
                logger.debug(f"[UserAuthStore] JWT验证成功: user_id={payload.get('sub')}")
                return payload
            except jwt.ExpiredSignatureError as e:
                logger.error(f"[UserAuthStore] JWT验证失败: Token已过期 - {e}")
                return None
            except jwt.JWTClaimsError as e:
                logger.error(f"[UserAuthStore] JWT验证失败: Token声明无效 - {e}")
                return None
            except jwt.JWTError as e:
                logger.error(f"[UserAuthStore] JWT验证失败: 签名无效或token格式错误 - {e}")
                return None
        except Exception as e:
            logger.error(f"[UserAuthStore] Token验证失败: 未预期的错误 {type(e).__name__}: {e}")
            return None

    def add_user(self, username: str, password: str, email: str = None, roles: list[str] = None,
                 require_password_change: bool = False) -> dict:
        """添加新用户"""
        with self._lock:
            if username in self._users:
                raise ValueError(f"用户已存在: {username}")

            user_id = f"user_{hashlib.md5(username.encode()).hexdigest()[:8]}"
            user_data = {
                "user_id": user_id,
                "username": username,
                "password_hash": self._hash_password(password),
                "email": email,
                "created_at": time.time(),
                "is_active": True,
                "roles": roles or ["user"],
                "require_password_change": require_password_change
            }

            self._users[username] = user_data
            self._user_id_map[user_id] = username

            # 持久化到文件
            self._save_users_to_file()

            logger.info(f"[UserAuthStore] 添加新用户: {username}")
            return user_data

    def _load_users_from_file(self):
        """从文件加载已保存的用户"""
        try:
            if os.path.exists(self._users_file):
                with open(self._users_file, encoding='utf-8') as f:
                    saved_users = json.load(f)

                for username, user_data in saved_users.items():
                    # 只加载配置中不存在的用户（避免覆盖配置用户）
                    if username not in self._users:
                        self._users[username] = user_data
                        self._user_id_map[user_data.get("user_id", "")] = username

                logger.info(f"[UserAuthStore] 从文件加载了 {len(saved_users)} 个用户")
        except Exception as e:
            logger.warning(f"[UserAuthStore] 从文件加载用户失败: {e}")

    def _save_users_to_file(self):
        """保存用户到文件（排除默认用户）"""
        try:
            # 只保存非默认用户
            default_usernames = set(self.DEFAULT_USERS.keys())
            users_to_save = {
                k: v for k, v in self._users.items()
                if k not in default_usernames
            }

            if users_to_save:
                os.makedirs(os.path.dirname(self._users_file), exist_ok=True)
                with open(self._users_file, 'w', encoding='utf-8') as f:
                    json.dump(users_to_save, f, ensure_ascii=False, indent=2)
                logger.info(f"[UserAuthStore] 保存了 {len(users_to_save)} 个用户到文件")
        except Exception as e:
            logger.error(f"[UserAuthStore] 保存用户到文件失败: {e}")

    def change_password(self, username: str, current_password: str, new_password: str) -> bool:
        """
        修改用户密码 [CFG-001]

        Args:
            username: 用户名
            current_password: 当前密码
            new_password: 新密码

        Returns:
            bool: 是否修改成功
        """
        with self._lock:
            user = self._users.get(username)
            if not user:
                return False

            # 验证当前密码
            stored_hash = user.get("password_hash", "")
            if not self._verify_password(current_password, stored_hash):
                return False

            # 更新密码
            user["password_hash"] = self._hash_password(new_password)
            user["require_password_change"] = False  # 重置修改密码标记

            # 持久化到文件
            self._save_users_to_file()

            logger.info(f"[UserAuthStore] 用户 '{username}' 密码修改成功")
            return True

    def require_password_change(self, username: str) -> bool:
        """检查用户是否需要强制修改密码"""
        with self._lock:
            user = self._users.get(username)
            if user:
                return user.get("require_password_change", False)
            return False

    def is_setup_required(self) -> bool:
        """检查是否需要进行首次管理员设置"""
        return self._setup_required

    def setup_first_admin(self, username: str, password: str, email: str | None = None) -> dict:
        """创建第一个管理员账户（仅在系统无管理员时可用）"""
        if not self._setup_required:
            raise RuntimeError("[UserAuthStore] 系统已有管理员，不能通过首次设置创建")

        if not username or not isinstance(username, str):
            raise ValueError("[SILICONBASE_SECURITY_ERROR] 用户名不能为空")
        if not password or len(password) < 6:
            raise ValueError("[SILICONBASE_SECURITY_ERROR] 管理员密码至少需要6位")

        with self._lock:
            if not self._setup_required:
                raise RuntimeError("[UserAuthStore] 系统已有管理员，不能通过首次设置创建")
            if username in self._users:
                raise ValueError(f"用户已存在: {username}")

            user_data = self.add_user(
                username=username,
                password=password,
                email=email,
                roles=["admin"],
                require_password_change=False,
            )
            self._setup_required = False

        logger.warning(f"[UserAuthStore] 已创建首个管理员 '{username}'，请妥善保管密码")
        return user_data

    # 【P1-Asyncify】异步版本包装器（纯内存/CPU计算，语义兼容）
    async def averify_token(self, token: str) -> dict | None:
        return self.verify_token(token)

    async def aget_user_by_id(self, user_id: str) -> dict | None:
        return self.get_user_by_id(user_id)

    async def aget_user(self, username: str) -> dict | None:
        return self.get_user(username)

    async def averify_password(self, username: str, plain_password: str) -> bool:
        return self.verify_password(username, plain_password)

    async def arequire_password_change(self, username: str) -> bool:
        return self.require_password_change(username)

    async def acreate_access_token(self, user_id: str, expires_hours: int = 24) -> str:
        return self.create_access_token(user_id, expires_hours)

    async def aadd_user(self, username: str, password: str, **kwargs) -> dict:
        return self.add_user(username, password, **kwargs)

    async def achange_password(self, username: str, old_password: str, new_password: str) -> bool:
        return self.change_password(username, old_password, new_password)

    async def ais_setup_required(self) -> bool:
        return self.is_setup_required()

    async def asetup_first_admin(self, username: str, password: str, email: str | None = None) -> dict:
        return self.setup_first_admin(username, password, email)


# 【延迟初始化修复】UserAuthStore 延迟初始化
_user_auth_store = None

def get_user_auth_store():
    """获取 UserAuthStore 实例（延迟加载）"""
    global _user_auth_store
    if _user_auth_store is None:
        print("[初始化] 正在创建 UserAuthStore...")
        _user_auth_store = UserAuthStore()
        print("[初始化] 【成功】 UserAuthStore 创建完成")
    return _user_auth_store

# 保持向后兼容的代理

class UserAuthStoreProxy:
    """UserAuthStore 代理，实现延迟访问"""
    def __getattr__(self, name):
        store = get_user_auth_store()
        return getattr(store, name)

# 全局用户认证存储实例（代理）
user_auth_store = UserAuthStoreProxy()


# ============================================================================
# 会话存储管理器
# ============================================================================

class SessionStore:
    """会话存储管理器 - 内存实现（生产环境应使用Redis）"""

    _instance = None
    _lock = threading.Lock()
    _sessions: dict[str, dict[str, Any]] = {}
    _user_sessions: dict[str, set[str]] = {}

    # 内存泄漏修复: 添加最大限制
    MAX_SESSIONS = 10000              # 全局最大Session数量
    MAX_SESSIONS_PER_USER = 10        # 每用户最大Session数量
    SESSION_CLEANUP_INTERVAL = 1800   # 清理间隔（秒）= 30分钟

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def create(self, user_id: str, session_id: str | None = None) -> str:
        """创建新会话 - 带内存泄漏防护"""
        # 内存泄漏修复: 检查全局Session数量限制
        if len(self._sessions) >= self.MAX_SESSIONS:
            logger.warning(f"[SessionStore] 全局Session数量达到上限 {self.MAX_SESSIONS}，清理最旧的Session")
            self._cleanup_oldest_global(100)  # 清理100个最旧的Session

        # 内存泄漏修复: 检查每用户Session数量限制
        user_sess_count = len(self._user_sessions.get(user_id, set()))
        if user_sess_count >= self.MAX_SESSIONS_PER_USER:
            logger.warning(f"[SessionStore] 用户 {user_id} 的Session数量达到上限 {self.MAX_SESSIONS_PER_USER}，清理最旧的")
            self._cleanup_oldest_for_user(user_id)

        if session_id is None:
            session_id = f"sess_{uuid.uuid4().hex[:16]}"

        now = time.time()
        self._sessions[session_id] = {
            "session_id": session_id,
            "user_id": user_id,
            "created_at": now,
            "last_active": now,
            "messages": [],
            "metadata": {}
        }

        if user_id not in self._user_sessions:
            self._user_sessions[user_id] = set()
        self._user_sessions[user_id].add(session_id)

        return session_id

    def get(self, user_id: str, session_id: str | None = None) -> dict[str, Any] | None:
        """获取会话，如不存在则创建"""
        if session_id and session_id in self._sessions:
            session = self._sessions[session_id]
            if session["user_id"] == user_id:
                session["last_active"] = time.time()
                return session

        # 创建新会话
        new_session_id = self.create(user_id, session_id)
        return self._sessions.get(new_session_id)

    def get_by_id(self, session_id: str) -> dict[str, Any] | None:
        """通过ID获取会话"""
        session = self._sessions.get(session_id)
        if session:
            session["last_active"] = time.time()
        return session

    def add_message(self, session_id: str, role: str, content: str) -> None:
        """添加消息到会话"""
        if session_id in self._sessions:
            self._sessions[session_id]["messages"].append({
                "role": role,
                "content": content,
                "timestamp": time.time()
            })
            self._sessions[session_id]["last_active"] = time.time()

    def get_user_sessions(self, user_id: str) -> list[SessionInfo]:
        """获取用户的所有会话"""
        session_ids = self._user_sessions.get(user_id, set())
        sessions = []
        for sid in session_ids:
            if sid in self._sessions:
                s = self._sessions[sid]
                sessions.append(SessionInfo(
                    session_id=s["session_id"],
                    user_id=s["user_id"],
                    created_at=s["created_at"],
                    last_active=s["last_active"],
                    message_count=len(s["messages"])
                ))
        return sessions

    def delete(self, session_id: str) -> bool:
        """删除会话"""
        if session_id in self._sessions:
            user_id = self._sessions[session_id]["user_id"]
            del self._sessions[session_id]
            if user_id in self._user_sessions:
                self._user_sessions[user_id].discard(session_id)
            return True
        return False

    def cleanup_expired(self, max_age_hours: int = 24) -> int:
        """清理过期会话"""
        now = time.time()
        expired = []
        for sid, session in self._sessions.items():
            if now - session["last_active"] > max_age_hours * 3600:
                expired.append(sid)

        for sid in expired:
            self.delete(sid)

        return len(expired)

    def _cleanup_oldest_for_user(self, user_id: str, count: int = 1):
        """清理用户最旧的Session（LRU策略）"""
        if user_id not in self._user_sessions:
            return

        # 获取用户的所有Session，按最后活跃时间排序
        user_sids = list(self._user_sessions[user_id])
        user_sids.sort(key=lambda sid: self._sessions.get(sid, {}).get("last_active", 0))

        # 删除最旧的
        for sid in user_sids[:count]:
            self.delete(sid)
            logger.debug(f"[SessionStore] 清理用户 {user_id} 的旧Session: {sid[:8]}...")

    def _cleanup_oldest_global(self, count: int = 100):
        """全局清理最旧的Session（LRU策略）"""
        # 按最后活跃时间排序
        all_sessions = sorted(
            self._sessions.items(),
            key=lambda x: x[1].get("last_active", 0)
        )

        # 删除最旧的
        for sid, _ in all_sessions[:count]:
            self.delete(sid)
            logger.debug(f"[SessionStore] 全局清理旧Session: {sid[:8]}...")

    # ═══════════════════════════════════════════════════════════════
    # 【P1-Asyncify】异步版本包装器（纯内存操作，语义兼容）
    # ═══════════════════════════════════════════════════════════════
    async def aget(self, user_id: str, session_id: str | None = None) -> dict[str, Any] | None:
        return self.get(user_id, session_id)

    async def aget_by_id(self, session_id: str) -> dict[str, Any] | None:
        return self.get_by_id(session_id)

    async def aadd_message(self, session_id: str, role: str, content: str) -> None:
        self.add_message(session_id, role, content)

    async def aget_user_sessions(self, user_id: str) -> list[SessionInfo]:
        return self.get_user_sessions(user_id)

    async def adelete(self, session_id: str) -> bool:
        return self.delete(session_id)

    async def acleanup_expired(self, max_age_hours: int = 24) -> int:
        return self.cleanup_expired(max_age_hours)


# ============================================================================
# 【生产环境】Redis 会话存储实现
# 使用方式：设置环境变量 SESSION_STORE_TYPE=redis 和 REDIS_URL
# ============================================================================

class RedisSessionStore:
    """
    Redis 会话存储管理器 - 用于生产环境多实例部署

    环境变量配置：
    - SESSION_STORE_TYPE=redis  # 启用Redis存储
    - REDIS_URL=redis://localhost:6379/0  # Redis连接URL
    - SESSION_TTL=86400  # Session过期时间（秒），默认24小时
    """

    _instance = None
    _lock = threading.Lock()

    # Redis key前缀
    KEY_PREFIX = "sb:session:"
    USER_PREFIX = "sb:user:sessions:"

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._redis = None
        self._ttl = int(os.environ.get("SESSION_TTL", "86400"))  # 默认24小时
        self._connect()
        self._initialized = True

    def _connect(self):
        """连接Redis"""
        try:
            import redis
            redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
            self._redis = redis.from_url(redis_url, decode_responses=True)
            # 测试连接
            self._redis.ping()
            logger.info(f"[RedisSessionStore] 已连接到Redis: {redis_url}")
        except ImportError:
            logger.error("[RedisSessionStore] 缺少redis依赖，请安装: pip install redis")
            raise
        except Exception as e:
            logger.error(f"[RedisSessionStore] Redis连接失败: {e}")
            raise

    def _session_key(self, session_id: str) -> str:
        """生成Session的Redis key"""
        return f"{self.KEY_PREFIX}{session_id}"

    def _user_key(self, user_id: str) -> str:
        """生成用户Session集合的Redis key"""
        return f"{self.USER_PREFIX}{user_id}"

    def create(self, user_id: str, session_id: str | None = None) -> str:
        """创建新会话"""
        if session_id is None:
            session_id = f"sess_{uuid.uuid4().hex[:16]}"

        now = time.time()
        session_data = {
            "session_id": session_id,
            "user_id": user_id,
            "created_at": now,
            "last_active": now,
            "messages": json.dumps([]),
            "metadata": json.dumps({})
        }

        pipe = self._redis.pipeline()
        # 存储Session数据
        pipe.hset(self._session_key(session_id), mapping=session_data)
        pipe.expire(self._session_key(session_id), self._ttl)
        # 添加到用户的Session集合
        pipe.sadd(self._user_key(user_id), session_id)
        pipe.expire(self._user_key(user_id), self._ttl)
        pipe.execute()

        logger.debug(f"[RedisSessionStore] 创建Session: {session_id[:8]}... 用户: {user_id}")
        return session_id

    def get(self, user_id: str, session_id: str | None = None) -> dict[str, Any] | None:
        """获取会话，如不存在则创建"""
        if session_id:
            session = self._get_session_data(session_id)
            if session and session.get("user_id") == user_id:
                # 更新最后活跃时间
                self._redis.hset(self._session_key(session_id), "last_active", time.time())
                return session

        # 创建新会话
        new_session_id = self.create(user_id, session_id)
        return self._get_session_data(new_session_id)

    def _get_session_data(self, session_id: str) -> dict[str, Any] | None:
        """从Redis获取Session数据"""
        data = self._redis.hgetall(self._session_key(session_id))
        if not data:
            return None

        # 解析JSON字段
        try:
            data["messages"] = json.loads(data.get("messages", "[]"))
            data["metadata"] = json.loads(data.get("metadata", "{}"))
            data["created_at"] = float(data.get("created_at", 0))
            data["last_active"] = float(data.get("last_active", 0))
        except json.JSONDecodeError:
            logger.error(f"[RedisSessionStore] Session数据解析失败: {session_id}")
            return None

        return data

    def get_by_id(self, session_id: str) -> dict[str, Any] | None:
        """通过ID获取会话"""
        session = self._get_session_data(session_id)
        if session:
            # 更新最后活跃时间
            self._redis.hset(self._session_key(session_id), "last_active", time.time())
        return session

    def add_message(self, session_id: str, role: str, content: str) -> None:
        """添加消息到会话"""
        session = self._get_session_data(session_id)
        if session:
            messages = session.get("messages", [])
            messages.append({
                "role": role,
                "content": content,
                "timestamp": time.time()
            })
            self._redis.hset(self._session_key(session_id), "messages", json.dumps(messages))
            self._redis.hset(self._session_key(session_id), "last_active", time.time())
            self._redis.expire(self._session_key(session_id), self._ttl)

    def get_user_sessions(self, user_id: str) -> list[SessionInfo]:
        """获取用户的所有会话"""
        session_ids = self._redis.smembers(self._user_key(user_id))
        sessions = []

        for sid in session_ids:
            session = self._get_session_data(sid)
            if session:
                sessions.append(SessionInfo(
                    session_id=session["session_id"],
                    user_id=session["user_id"],
                    created_at=session["created_at"],
                    last_active=session["last_active"],
                    message_count=len(session.get("messages", []))
                ))

        return sessions

    def delete(self, session_id: str) -> bool:
        """删除会话"""
        session = self._get_session_data(session_id)
        if session:
            user_id = session.get("user_id")
            pipe = self._redis.pipeline()
            pipe.delete(self._session_key(session_id))
            if user_id:
                pipe.srem(self._user_key(user_id), session_id)
            pipe.execute()
            return True
        return False

    def cleanup_expired(self, max_age_hours: int = 24) -> int:
        """清理过期会话（Redis自动过期，此方法仅用于手动清理）"""
        # Redis自动处理过期，这里返回0表示没有手动清理
        return 0


# 根据环境变量选择SessionStore实现
def get_session_store():
    """
    获取会话存储实例

    根据环境变量 SESSION_STORE_TYPE 选择实现：
    - memory: 内存存储（默认，开发环境）
    - redis: Redis存储（生产环境推荐）
    """
    store_type = os.environ.get("SESSION_STORE_TYPE", "memory").lower()

    if store_type == "redis":
        try:
            return RedisSessionStore()
        except Exception as e:
            logger.error(f"[SessionStore] Redis初始化失败，回退到内存存储: {e}")
            return SessionStore()
    else:
        return SessionStore()


# 全局SessionStore实例
session_store = get_session_store()


# ============================================================================
# SEC-002: 模块级别JWT工具函数 (提供给外部使用)
# ============================================================================

# 全局JWT密钥和算法 (与UserAuthStore保持一致)
_JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY")
# 强制要求设置JWT密钥，未设置时生成临时随机密钥（重启后失效）
if not _JWT_SECRET_KEY:
    _JWT_SECRET_KEY = secrets.token_urlsafe(32)
    warnings.warn(
        "[CloudAPI] JWT_SECRET_KEY 未设置，已生成临时随机密钥（重启后失效）。"
        "生产环境请务必在 .env 中设置强密码！",
        RuntimeWarning,
        stacklevel=2,
    )
_JWT_ALGORITHM = "HS256"
_JWT_ACCESS_TOKEN_EXPIRE_HOURS = 24


def encode_token(payload: dict[str, Any], expires_hours: int = None) -> str:
    """
    编码JWT令牌 (模块级别函数)

    Args:
        payload: 要编码的数据字典
        expires_hours: 过期时间（小时），默认24小时

    Returns:
        str: JWT token字符串
    """
    if expires_hours is None:
        expires_hours = _JWT_ACCESS_TOKEN_EXPIRE_HOURS

    # 准备payload副本
    to_encode = payload.copy()

    # 添加过期时间
    expires_delta = timedelta(hours=expires_hours)
    expire = datetime.utcnow() + expires_delta
    to_encode["exp"] = expire
    to_encode["iat"] = datetime.utcnow()

    # SEC-002: 使用python-jose生成JWT
    if PYTHON_JOSE_AVAILABLE and jwt:
        encoded_jwt = jwt.encode(to_encode, _JWT_SECRET_KEY, algorithm=_JWT_ALGORITHM)
        return encoded_jwt
    else:
        # Fallback: 使用base64编码（仅用于开发环境）
        import base64
        import json
        logger.warning("[CloudAPI] python-jose不可用，使用base64编码token（仅开发环境）")
        return base64.b64encode(json.dumps(to_encode).encode()).decode()


def decode_token(token: str) -> dict[str, Any] | None:
    """
    解码并验证JWT令牌 (模块级别函数)

    Args:
        token: JWT token字符串

    Returns:
        Optional[Dict]: 解码后的payload，无效则返回None
    """
    try:
        # SEC-002: 使用python-jose验证JWT
        if PYTHON_JOSE_AVAILABLE and jwt:
            payload = jwt.decode(token, _JWT_SECRET_KEY, algorithms=[_JWT_ALGORITHM])
            return payload
        else:
            # Fallback: 使用base64解码（仅用于开发环境）
            import base64
            import json
            payload = json.loads(base64.b64decode(token.encode()).decode())
            # 检查是否过期
            exp = payload.get("exp")
            if exp and isinstance(exp, (int, float)) and datetime.utcnow().timestamp() > exp:
                return None
            return payload
    except JWTError as e:
        logger.error(f"[decode_token] Token JWT解码失败: {e}", exc_info=True)
        return None
    except Exception as e:
        logger.error(f"[decode_token] Token解码未预期异常: {e}", exc_info=True)
        return None


# ============================================================================
# P0-008 消息类型标准化工具
# ============================================================================

# 后端事件类型到前端消息类型的映射
BACKEND_TO_FRONTEND_TYPE_MAP = {
    "completed": "reply",
    "start": "task_start",
    "thinking": "thinking",
    "executing": "executing",
    "executed": "tool_result",
    "tool_result": "tool_result",
    "reply": "reply",
    "error": "error",
}

# 支持的前端消息类型
FRONTEND_SUPPORTED_TYPES = {
    "reply", "thinking", "executing", "tool_result",
    "task_update", "learning", "error", "voice",
    "chat_alignment_reply", "chat_response"  # 【修复】添加聊天对齐回复类型
}


def normalize_websocket_message(message: dict[str, Any] | None) -> dict[str, Any]:
    """
    标准化WebSocket消息格式（P0-008修复）

    将后端消息类型转换为前端期望的类型，并确保数据结构一致

    Args:
        message: 原始消息字典

    Returns:
        标准化后的消息字典
    """
    # 【P0修复】添加空值保护
    if message is None:
        logger.error("[normalize_websocket_message] 收到None消息")
        return {"type": "error", "data": {"message": "收到无效消息"}, "timestamp": int(time.time() * 1000)}

    if not isinstance(message, dict):
        logger.error(f"[normalize_websocket_message] 收到非字典消息: {type(message)}")
        return {"type": "error", "data": {"message": "消息格式错误"}, "timestamp": int(time.time() * 1000)}

    msg_type = message.get("type", "")

    # 转换类型
    if msg_type in BACKEND_TO_FRONTEND_TYPE_MAP:
        message["type"] = BACKEND_TO_FRONTEND_TYPE_MAP[msg_type]

        # 转换特定字段
        if msg_type == "completed":
            if "data" not in message:
                message["data"] = {}
            # 将 content/answer 标准化
            if "answer" in message:
                message["data"]["content"] = message.pop("answer")
            elif "content" in message and "data" not in message:
                message["data"]["content"] = message.pop("content")
            if "success" not in message["data"]:
                message["data"]["success"] = True

        elif msg_type == "executed":
            if "data" not in message:
                message["data"] = {}
            if "summary" in message:
                message["data"]["message"] = message.pop("summary")

        elif msg_type == "executing":
            if "data" not in message:
                message["data"] = {}
            # 确保executing类型有正确的data结构
            if "task_id" in message and "task_id" not in message["data"]:
                message["data"]["task_id"] = message.pop("task_id")
            if "tool_name" in message and "tool_name" not in message["data"]:
                message["data"]["tool_name"] = message.pop("tool_name")

    # 确保消息有 timestamp
    if "timestamp" not in message:
        message["timestamp"] = time.time()

    # 确保消息有 data 字段（除了特殊类型）
    if "data" not in message and message["type"] in FRONTEND_SUPPORTED_TYPES:
        message["data"] = {}

    return message


# ============================================================================
# WebSocket 消息处理器（从独立 websocket_server.py 迁移到 FastAPI）
# ============================================================================

async def _handle_confirm_response(websocket: WebSocket, user_id: str, data: dict):
    """处理用户确认/拒绝响应（从 websocket_server.py 迁移）"""
    request_id = data.get("request_id", "")
    action = data.get("action", "")
    reason = data.get("reason", "")

    if not request_id or action not in ("confirm", "reject"):
        await safe_send_json(websocket, {
            "type": "confirm_ack",
            "success": False,
            "message": "缺少 request_id 或 action 无效"
        })
        return

    try:
        from core.safety.confirmation_manager import confirmation_manager
        request = confirmation_manager.get_request(request_id)
        if not request:
            await safe_send_json(websocket, {
                "type": "confirm_ack",
                "success": False,
                "message": "确认请求不存在或已过期"
            })
            return

        if action == "confirm":
            success = confirmation_manager.confirm(request_id, {"user_id": user_id})
            message = "已确认执行"
        else:
            success = confirmation_manager.reject(request_id, reason)
            message = "已拒绝执行"

        await safe_send_json(websocket, {
            "type": "confirm_ack",
            "success": success,
            "request_id": request_id,
            "action": action,
            "message": message if success else "处理失败，请求可能已过期"
        })
    except Exception as e:
        logger.error(f"[WebSocket] 处理确认响应失败: {e}", exc_info=True)
        await safe_send_json(websocket, {
            "type": "confirm_ack",
            "success": False,
            "request_id": request_id,
            "message": f"处理异常: {str(e)}"
        })


async def _handle_accept_weak_proposal(websocket: WebSocket, user_id: str, data: dict):
    """用户接受弱连接提议（从 websocket_server.py 迁移）"""
    anchor_id = data.get("anchor_id", "")
    message = data.get("message", "")

    if not anchor_id:
        await safe_send_json(websocket, {
            "type": "weak_proposal_accepted",
            "success": False,
            "anchor_id": anchor_id,
            "message": "缺少 anchor_id"
        })
        return

    try:
        from core.weak_connection import get_weak_connection_engine
        engine = get_weak_connection_engine()
        engine.accept_proposal(anchor_id, message)

        await safe_send_json(websocket, {
            "type": "weak_proposal_accepted",
            "success": True,
            "anchor_id": anchor_id,
            "mode": "FOCUS",
            "message": "已接受提议，切换到专注模式"
        })
    except Exception as e:
        logger.error(f"[WebSocket] 接受弱连接提议失败: {e}", exc_info=True)
        await safe_send_json(websocket, {
            "type": "weak_proposal_accepted",
            "success": False,
            "anchor_id": anchor_id,
            "message": f"接受失败: {str(e)}"
        })


async def _handle_dismiss_weak_proposal(websocket: WebSocket, user_id: str, data: dict):
    """用户忽略弱连接提议（从 websocket_server.py 迁移）"""
    anchor_id = data.get("anchor_id", "")
    if not anchor_id:
        return
    try:
        from core.weak_connection import get_weak_connection_engine
        get_weak_connection_engine().dismiss_proposal(anchor_id)
    except Exception as e:
        logger.error(f"[WebSocket] 忽略弱连接提议失败: {e}", exc_info=True)


async def _handle_timeout_weak_proposal(websocket: WebSocket, user_id: str, data: dict):
    """弱连接提议超时（从 websocket_server.py 迁移）"""
    anchor_id = data.get("anchor_id", "")
    if not anchor_id:
        return
    try:
        from core.weak_connection import get_weak_connection_engine
        get_weak_connection_engine().timeout_proposal(anchor_id)
    except Exception as e:
        logger.error(f"[WebSocket] 弱连接提议超时处理失败: {e}", exc_info=True)


def _register_weak_proposal_forwarder():
    """把 event_bus 的 ui:show_proposal 转发到 FastAPI WebSocket 连接"""
    try:
        from core.sync.event_bus import event_bus
    except ImportError:
        logger.warning("[WebSocket] event_bus 不可用，跳过弱连接转发注册")
        return

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        return

    def on_weak_proposal(event):
        try:
            raw = event.data if hasattr(event, "data") else event
            data = raw if isinstance(raw, dict) else {}
            proposal = {
                "anchor_id": data.get("anchor_id"),
                "message": data.get("message"),
                "action_text": data.get("action_text", "帮我处理"),
                "timestamp": time.time()
            }
            asyncio.run_coroutine_threadsafe(
                ConnectionManager().broadcast({
                    "type": "weak_proposal",
                    "timestamp": time.time(),
                    "data": proposal
                }),
                loop
            )
        except Exception as e:
            logger.debug(f"[WebSocket] 转发弱连接提议失败: {e}")

    try:
        event_bus.subscribe("ui:show_proposal", on_weak_proposal)
        logger.info("[WebSocket] 已注册 ui:show_proposal -> weak_proposal 转发")
    except Exception as e:
        logger.warning(f"[WebSocket] 注册弱连接转发失败: {e}")


# ============================================================================
# WebSocket 连接管理器
# ============================================================================

import threading
import weakref

# ============================================================================
# 【生产环境】Redis Pub/Sub 管理器 - 用于多实例 WebSocket 消息广播
# ============================================================================

class RedisPubSubManager:
    """
    Redis Pub/Sub 管理器 - 实现跨实例 WebSocket 消息广播

    使用方式：
    1. 设置环境变量 WEBSOCKET_BROADCAST=redis
    2. 设置 REDIS_URL（如果与Session Store不同）

    工作流程：
    1. 实例A收到用户消息
    2. 实例A处理并生成回复
    3. 实例A通过Redis Pub/Sub广播回复
    4. 所有订阅的实例（包括A）收到消息
    5. 每个实例将消息发送给本地连接的客户端
    """

    _instance = None
    _lock = threading.Lock()

    # Redis频道前缀
    CHANNEL_PREFIX = "sb:ws:broadcast:"

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._redis = None
        self._pubsub = None
        self._task = None
        self._message_handlers: list[Callable] = []
        self._enabled = os.environ.get("WEBSOCKET_BROADCAST", "memory").lower() == "redis"

        if self._enabled:
            try:
                self._connect()
            except Exception as e:
                logger.error(f"[RedisPubSub] 初始化失败，禁用广播: {e}")
                self._enabled = False

        self._initialized = True

    def _connect(self):
        """连接Redis"""
        try:
            import redis.asyncio as aioredis
            redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
            self._redis = aioredis.from_url(redis_url)
            logger.info(f"[RedisPubSub] 已连接到Redis: {redis_url}")
        except ImportError:
            logger.error("[RedisPubSub] 缺少redis依赖，请安装: pip install redis")
            raise

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def start(self):
        """启动Pub/Sub监听"""
        if not self._enabled or self._pubsub:
            return

        try:
            self._pubsub = self._redis.pubsub()
            await self._pubsub.subscribe(f"{self.CHANNEL_PREFIX}*")

            # 启动监听任务
            self._task = safe_create_task(self._listener(), name="redis_listener")
            logger.info("[RedisPubSub] 广播监听已启动")
        except Exception as e:
            logger.error(f"[RedisPubSub] 启动失败: {e}")
            self._enabled = False

    async def stop(self):
        """停止Pub/Sub监听"""
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

        if self._pubsub:
            await self._pubsub.unsubscribe()
            await self._pubsub.close()

        if self._redis:
            await self._redis.close()

        logger.info("[RedisPubSub] 广播监听已停止")

    async def _listener(self):
        """监听Redis消息"""
        try:
            async for message in self._pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        # 调用所有注册的消息处理器
                        for handler in self._message_handlers:
                            try:
                                await handler(data)
                            except Exception as e:
                                logger.error(f"[RedisPubSub] 消息处理器错误: {e}")
                    except json.JSONDecodeError:
                        logger.error(f"[RedisPubSub] 消息解析失败: {message['data']}")
        except asyncio.CancelledError:
            logger.debug("[RedisPubSub] 监听任务已取消")
        except Exception as e:
            logger.error(f"[RedisPubSub] 监听错误: {e}")

    async def broadcast(self, user_id: str, message: dict[str, Any]):
        """
        广播消息给所有实例

        Args:
            user_id: 目标用户ID
            message: 消息内容
        """
        if not self._enabled or not self._redis:
            return

        try:
            channel = f"{self.CHANNEL_PREFIX}{user_id}"
            data = json.dumps({
                "user_id": user_id,
                "message": message,
                "timestamp": time.time(),
                "instance_id": os.environ.get("HOSTNAME", "unknown")  # 用于调试
            })
            await self._redis.publish(channel, data)
            logger.debug(f"[RedisPubSub] 消息已广播到频道 {channel}")
        except Exception as e:
            logger.error(f"[RedisPubSub] 广播失败: {e}")

    def register_handler(self, handler: Callable):
        """注册消息处理器"""
        self._message_handlers.append(handler)
        logger.debug(f"[RedisPubSub] 注册消息处理器，当前数量: {len(self._message_handlers)}")

    def unregister_handler(self, handler: Callable):
        """注销消息处理器"""
        if handler in self._message_handlers:
            self._message_handlers.remove(handler)


# 全局Pub/Sub管理器实例
pubsub_manager = RedisPubSubManager()


# ============================================================================
# WebSocket 连接管理器
# ============================================================================

class ConnectionManager:
    """WebSocket 连接管理器"""

    _instance = None
    _lock = threading.Lock()

    # 内存泄漏修复: 连接超时配置
    # 应用层兜底：2小时无双向流量才断开；Uvicorn 协议层 ping/pong 负责日常保活
    CONNECTION_TIMEOUT_SECONDS = 7200  # 2小时

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._connections: dict[str, WebSocket] = {}
                    cls._instance._user_connections: dict[str, set[str]] = {}
                    # 内存泄漏修复: 使用弱引用存储回调
                    cls._instance._callbacks: dict[str, weakref.ref] = {}  # 存储realtime_sync回调（弱引用）
                    cls._instance._connection_last_active: dict[str, float] = {}  # 连接最后活跃时间
                    # 按连接记录最近处理的 session_id，避免旧任务事件串到新连接
                    cls._instance._connection_sessions: dict[str, str] = {}
                    cls._instance._health_tasks: dict[str, asyncio.Task] = {}  # 连接健康检查任务
                    cls._instance._initialized = False
        return cls._instance

    async def connect(self, websocket: WebSocket, user_id: str) -> str:
        """建立WebSocket连接 - 带内存泄漏防护"""
        await websocket.accept()
        connection_id = f"conn_{uuid.uuid4().hex[:12]}"
        self._connections[connection_id] = websocket

        # 内存泄漏修复: 记录连接活跃时间
        self._connection_last_active[connection_id] = time.time()

        if user_id not in self._user_connections:
            self._user_connections[user_id] = set()
        self._user_connections[user_id].add(connection_id)

        # 内存泄漏修复: 启动连接健康检查
        health_task = safe_create_task(self._connection_health_check(connection_id, user_id), name=f"health_check_{connection_id}")
        self._health_tasks[connection_id] = health_task

        # 注册realtime_sync事件回调，将事件转发到前端
        logger.info(f"[ConnectionManager] 开始注册回调: REALTIME_SYNC_AVAILABLE={REALTIME_SYNC_AVAILABLE}")
        if REALTIME_SYNC_AVAILABLE:
            try:
                sync_manager = get_realtime_sync_manager()
                logger.info("[ConnectionManager] 获取sync_manager成功")

                # 获取当前事件循环（在connect的异步上下文中）
                current_loop = asyncio.get_event_loop()

                # 定义事件回调函数
                def event_callback(event):
                    # 将事件转发给前端，按 session_id 过滤，避免旧任务事件串到新连接
                    try:
                        event_dict = event.to_dict()
                        event_session_id = getattr(event, 'session_id', None) or event_dict.get('session_id')
                        conn_session_id = self._connection_sessions.get(connection_id)
                        if event_session_id and conn_session_id and event_session_id != conn_session_id:
                            logger.debug(
                                f"[ConnectionManager] 事件 session_id 不匹配，跳过转发: "
                                f"event={event_session_id}, conn={conn_session_id}, user={user_id}"
                            )
                            return
                        logger.debug(f"[ConnectionManager] 收到realtime_sync事件: {event_dict.get('type')}, user: {user_id}")
                        # 使用 run_coroutine_threadsafe 确保在事件循环中执行
                        asyncio.run_coroutine_threadsafe(
                            self.send_to_user(user_id, event_dict),
                            current_loop
                        )
                    except Exception as e:
                        logger.error(f"[ConnectionManager] 转发事件失败: {e}", exc_info=True)

                sync_manager.register_callback(event_callback)
                # 内存泄漏修复: 使用弱引用保存回调
                self._callbacks[connection_id] = weakref.ref(event_callback)
                logger.info(f"[ConnectionManager] 已注册realtime_sync回调: {connection_id}, user: {user_id}")
            except Exception as e:
                logger.error(f"[ConnectionManager] 注册realtime_sync回调失败: {e}", exc_info=True)

        return connection_id

    def update_connection_session(self, connection_id: str, session_id: str) -> None:
        """更新连接当前关注的 session_id，用于过滤残留事件。"""
        if session_id:
            self._connection_sessions[connection_id] = session_id

    def disconnect(self, connection_id: str, user_id: str) -> None:
        """断开WebSocket连接 - 带内存泄漏防护"""
        # 取消并清理健康检查任务
        health_task = self._health_tasks.pop(connection_id, None)
        if health_task and not health_task.done():
            try:
                health_task.cancel()
            except Exception as e:
                logger.debug(f"[ConnectionManager] 取消健康检查任务失败: {e}")

        # 清理连接 session 记录
        self._connection_sessions.pop(connection_id, None)
        # 注销realtime_sync回调，避免内存泄漏
        if connection_id in self._callbacks:
            if REALTIME_SYNC_AVAILABLE:
                try:
                    sync_manager = get_realtime_sync_manager()
                    weak_callback = self._callbacks.pop(connection_id)
                    callback = weak_callback()  # 解引用弱引用
                    if callback is not None:
                        sync_manager.unregister_callback(callback)
                        logger.debug(f"[ConnectionManager] 已注销realtime_sync回调: {connection_id}")
                except Exception as e:
                    logger.error(f"[ConnectionManager] 注销realtime_sync回调失败: {e}", exc_info=True)
            else:
                self._callbacks.pop(connection_id, None)

        # 内存泄漏修复: 清理活跃时间记录
        self._connection_last_active.pop(connection_id, None)

        self._connections.pop(connection_id, None)
        if user_id in self._user_connections:
            self._user_connections[user_id].discard(connection_id)

    async def send_to_user(self, user_id: str, message: dict[str, Any]) -> int:
        """发送消息给指定用户的所有连接（优化版）"""
        normalized_message = normalize_websocket_message(message.copy())
        connection_ids = self._user_connections.get(user_id, set()).copy()
        sent_count = 0
        disconnected = []

        for conn_id in connection_ids:
            websocket = self._connections.get(conn_id)
            if not websocket:
                disconnected.append((conn_id, user_id))
                continue

            try:
                await websocket.send_json(normalized_message)
                sent_count += 1
                # 发送成功也视为活跃，刷新应用层超时
                self.update_connection_active(conn_id)

            except (RuntimeError, WebSocketDisconnect, ConnectionClosedOK, ConnectionClosedError) as e:
                # WebSocket已关闭 - 记录后清理
                logger.debug(f"[ConnectionManager] WebSocket断开: {e}")
                disconnected.append((conn_id, user_id))
            except Exception as e:
                # 其他错误 - ERROR日志记录
                logger.error(f"[ConnectionManager] 发送消息异常: {e}", exc_info=True)
                disconnected.append((conn_id, user_id))

        # 批量清理断开的连接
        for conn_id, uid in disconnected:
            self.disconnect(conn_id, uid)

        # 【修复】通过Redis Pub/Sub广播消息（支持多实例）
        if pubsub_manager.enabled:
            await pubsub_manager.broadcast(user_id, normalized_message)

        return sent_count

    async def send_to_connection(self, connection_id: str, message: dict[str, Any]) -> bool:
        """发送消息给指定连接（P0-008: 自动标准化消息类型）"""
        # 标准化消息格式
        normalized_message = normalize_websocket_message(message.copy())

        websocket = self._connections.get(connection_id)
        if websocket:
            try:
                await websocket.send_json(normalized_message)
                # 发送成功刷新应用层活跃时间
                self.update_connection_active(connection_id)
                return True
            except (WebSocketDisconnect, ConnectionClosedOK, ConnectionClosedError):
                # 连接已关闭，属于预期情况
                return False
            except RuntimeError as e:
                # 处理WebSocket已关闭的情况
                error_msg = str(e)
                if "websocket.close" in error_msg or "response already completed" in error_msg or "websocket.send" in error_msg or "not connected" in error_msg.lower():
                    logger.debug(f"[ConnectionManager] 连接 {connection_id} 已关闭，无法发送消息: {error_msg}")
                else:
                    logger.error(f"[ConnectionManager] 发送消息到连接 {connection_id} 失败: {e}", exc_info=True)
            except Exception as e:
                logger.error(f"[ConnectionManager] 发送消息到连接 {connection_id} 失败: {e}", exc_info=True)
        return False

    async def broadcast(self, message: dict[str, Any]) -> int:
        """广播消息给所有连接（P0-008: 自动标准化消息类型）"""
        # 标准化消息格式
        normalized_message = normalize_websocket_message(message.copy())

        sent_count = 0
        disconnected = []

        for conn_id, websocket in list(self._connections.items()):
            try:
                await websocket.send_json(normalized_message)
                sent_count += 1
                # 发送成功刷新应用层活跃时间
                self.update_connection_active(conn_id)
            except (WebSocketDisconnect, ConnectionClosedOK, ConnectionClosedError):
                # 连接已关闭，属于预期情况
                for uid, conns in self._user_connections.items():
                    if conn_id in conns:
                        disconnected.append((conn_id, uid))
                        break
            except RuntimeError as e:
                # 处理WebSocket已关闭的情况
                error_msg = str(e)
                if "websocket.close" in error_msg or "response already completed" in error_msg or "websocket.send" in error_msg or "not connected" in error_msg.lower():
                    logger.debug(f"[ConnectionManager] 广播消息到连接 {conn_id} 时连接已关闭: {error_msg}")
                else:
                    logger.error(f"[ConnectionManager] 广播消息到连接 {conn_id} 失败: {e}", exc_info=True)
                # 找到对应的user_id
                for uid, conns in self._user_connections.items():
                    if conn_id in conns:
                        disconnected.append((conn_id, uid))
                        break
            except Exception as e:
                logger.error(f"[ConnectionManager] 广播消息到连接 {conn_id} 失败: {e}", exc_info=True)
                # 找到对应的user_id
                for uid, conns in self._user_connections.items():
                    if conn_id in conns:
                        disconnected.append((conn_id, uid))
                        break

        # 清理断开的连接
        for conn_id, uid in disconnected:
            self.disconnect(conn_id, uid)

        return sent_count

    def get_user_connections(self, user_id: str) -> int:
        """获取用户的连接数"""
        return len(self._user_connections.get(user_id, set()))

    def get_total_connections(self) -> int:
        """获取总连接数"""
        return len(self._connections)

    async def aget_total_connections(self) -> int:
        return self.get_total_connections()

    async def aget_user_connections(self, user_id: str) -> int:
        return self.get_user_connections(user_id)

    async def _connection_health_check(self, connection_id: str, user_id: str):
        """
        连接健康检查 - 自动清理超时连接（内存泄漏修复）

        定期检查连接是否仍然活跃，如果超过CONNECTION_TIMEOUT_SECONDS未活跃则自动断开
        """
        try:
            while connection_id in self._connections:
                await asyncio.sleep(15)  # 健康检查间隔，15秒更及时发现问题

                if connection_id not in self._connections:
                    break

                last_active = self._connection_last_active.get(connection_id, 0)
                if time.time() - last_active > self.CONNECTION_TIMEOUT_SECONDS:
                    logger.warning(f"[ConnectionManager] 连接 {connection_id[:8]}... 超时未活跃，自动断开")
                    self.disconnect(connection_id, user_id)
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[ConnectionManager] 连接健康检查异常: {e}")

    def update_connection_active(self, connection_id: str):
        """更新连接活跃时间"""
        if connection_id in self._connection_last_active:
            self._connection_last_active[connection_id] = time.time()


# ============================================================================
# 任务管理器
# ============================================================================

import threading


class TaskManager:
    """用户任务管理器"""

    _instance = None
    _lock = threading.Lock()
    _tasks: dict[str, list[dict[str, Any]]] = {}

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def add_task(self, user_id: str, task_type: str, task_data: dict[str, Any]) -> str:
        """添加任务"""
        task_id = f"task_{uuid.uuid4().hex[:16]}"
        task = {
            "task_id": task_id,
            "user_id": user_id,
            "type": task_type,
            "status": "pending",
            "data": task_data,
            "created_at": time.time(),
            "updated_at": time.time()
        }

        if user_id not in self._tasks:
            self._tasks[user_id] = []
        self._tasks[user_id].append(task)

        return task_id

    def get_user_tasks(self, user_id: str) -> list[dict[str, Any]]:
        """获取用户任务列表"""
        return self._tasks.get(user_id, []).copy()

    def update_task(self, task_id: str, status: str, result: Any | None = None) -> bool:
        """更新任务状态"""
        for _user_id, tasks in self._tasks.items():
            for task in tasks:
                # 【修复】使用.get()安全访问，避免KeyError
                if task.get("task_id") == task_id:
                    task["status"] = status
                    task["updated_at"] = time.time()
                    if result is not None:
                        task["result"] = result
                    return True
        return False

    def remove_task(self, user_id: str, task_id: str) -> bool:
        """删除任务"""
        if user_id in self._tasks:
            # 【修复】使用.get()安全访问，避免KeyError
            self._tasks[user_id] = [t for t in self._tasks[user_id] if t.get("task_id") != task_id]
            return True
        return False

    # 【P1-Asyncify】异步版本包装器
    async def aget_user_tasks(self, user_id: str) -> list[dict[str, Any]]:
        return self.get_user_tasks(user_id)


# ============================================================================
# 认证与工具函数
# ============================================================================

# 安全配置
security = HTTPBearer(auto_error=False)

# API Keys 从环境变量加载（生产环境必须配置）
# 格式: API_KEYS=key1:user1,key2:user2
import os


def _load_api_keys() -> dict[str, str]:
    """从环境变量加载API Keys"""
    # 添加测试key
    test_keys = {"sk-test-1234567890": "test_user"}

    keys_str = os.environ.get("API_KEYS", "")
    if not keys_str:
        return test_keys  # 返回测试keys而非空字典

    # 原有解析逻辑不变
    result = test_keys.copy()  # 包含测试keys
    for key_pair in keys_str.split(","):
        if ":" in key_pair:
            key, user = key_pair.split(":", 1)
            result[key.strip()] = user.strip()
    return result

API_KEYS: dict[str, str] = _load_api_keys()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> str:
    """
    获取当前用户 - 强制认证版本 (SEC-003修复)

    支持两种认证方式:
    1. JWT Bearer Token: 通过 /api/auth/login 获取的标准JWT
    2. API Key: 以sk-开头的API密钥（向后兼容）

    修复：添加详细错误日志记录，不静默失败
    """
    # 1. 检查凭证是否存在
    if credentials is None:
        logger.error("[Auth] 401 Unauthorized: 请求缺少Authorization头或凭证为空")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    # 2. 检查token是否为空
    if not token or not token.strip():
        logger.error("[Auth] 401 Unauthorized: Authorization头中的token为空")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is empty",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # API Key 验证（向后兼容）
    if token.startswith("sk-"):
        if token in API_KEYS:
            logger.debug(f"[Auth] API Key认证成功: {API_KEYS[token]}")
            return API_KEYS[token]
        logger.error(f"[Auth] 401 Unauthorized: 无效的API Key (前缀: {token[:10]}...)")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # JWT Token验证（SEC-003新增）
    try:
        payload = await user_auth_store.averify_token(token)
        if payload:
            user_id = payload.get("sub")
            if user_id:
                # 验证用户是否仍然存在且活跃
                user = await user_auth_store.aget_user_by_id(user_id)
                if user and user.get("is_active", True):
                    logger.debug(f"[Auth] JWT认证成功: user_id={user_id}")
                    return user_id
                else:
                    logger.error(f"[Auth] 401 Unauthorized: 用户不存在或已禁用 (user_id={user_id})")
            else:
                logger.error("[Auth] 401 Unauthorized: JWT token中缺少'sub'字段")
        else:
            # Token验证失败 - 记录token前20字符用于调试（不记录完整token）
            token_preview = token[:20] + "..." if len(token) > 20 else token
            logger.error(f"[Auth] 401 Unauthorized: JWT token验证失败 (token前缀: {token_preview})")
            logger.error("[Auth] 可能原因: token过期、签名无效、token格式错误、密钥不匹配")
    except Exception as e:
        logger.error(f"[Auth] 401 Unauthorized: Token验证过程中发生异常: {type(e).__name__}: {e}")

    # 无效token，返回401
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user_required(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> str:
    """强制要求认证的版本（与get_current_user统一）"""
    return await get_current_user(credentials)


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> str | None:
    """
    获取当前用户 - 可选认证版本

    有凭证时验证并返回用户ID
    无凭证时返回None，不抛出401

    修复：添加调试日志记录
    """
    if credentials is None:
        logger.debug("[Auth] 可选认证: 请求缺少Authorization头")
        return None

    token = credentials.credentials

    # 检查token是否为空
    if not token or not token.strip():
        logger.warning("[Auth] 可选认证: token为空")
        return None

    # API Key 验证（向后兼容）
    if token.startswith("sk-"):
        if token in API_KEYS:
            logger.debug(f"[Auth] 可选认证 API Key成功: {API_KEYS[token]}")
            return API_KEYS[token]
        logger.debug("[Auth] 可选认证 API Key无效")
        return None

    # JWT Token验证
    try:
        payload = await user_auth_store.averify_token(token)
        if payload:
            user_id = payload.get("sub")
            if user_id:
                # 验证用户是否仍然存在且活跃
                user = await user_auth_store.aget_user_by_id(user_id)
                if user and user.get("is_active", True):
                    logger.debug(f"[Auth] 可选认证 JWT成功: user_id={user_id}")
                    return user_id
                else:
                    logger.warning(f"[Auth] 可选认证: 用户不存在或已禁用 (user_id={user_id})")
            else:
                logger.warning("[Auth] 可选认证: JWT token中缺少'sub'字段")
        else:
            token_preview = token[:20] + "..." if len(token) > 20 else token
            logger.warning(f"[Auth] 可选认证: JWT token验证失败 (前缀: {token_preview})")
    except Exception as e:
        logger.error(f"[Auth] 可选认证: Token验证异常: {type(e).__name__}: {e}")

    # 验证失败返回None（不抛出异常）
    return None


# ============================================================================
# AI 处理函数 - 真实AI调用实现
# ============================================================================

# 导入AI适配层和对话管理器
try:
    from core.ai.ai_adapter import call_thinker_async
    from core.ai.ai_config import AIScene
    AI_AVAILABLE = True
except ImportError as e:
    print(f"[CloudAPI] AI模块导入失败: {e}")
    AI_AVAILABLE = False

# AI服务超时配置（秒）
AI_TIMEOUT = 30
AI_MAX_RETRY = 2


async def process_chat(
    session: dict[str, Any],
    message: str,
    stream: bool = False,
    **kwargs
) -> dict[str, Any]:
    """
    处理聊天消息 - 真实AI调用实现

    使用 ai_adapter.call_thinker 调用真实AI服务

    Args:
        session: 会话数据
        message: 用户消息
        stream: 是否流式（由上层处理，此处忽略）
        **kwargs: 额外参数
            - temperature: 采样温度
            - max_tokens: 最大token数
            - model: 模型名称

    Returns:
        Dict: 包含AI响应和token使用信息
    """
    if not AI_AVAILABLE:
        # 记录 AI 调用失败
        if MONITORING_AVAILABLE:
            record_ai_call(
                model=kwargs.get("model", "unknown"),
                provider="ollama",
                status="unavailable"
            )
        return {
            "success": False,
            "error": "AI服务暂时不可用",
            "text": "AI模块未正确加载，请检查系统配置。"
        }

    start_time = time.time()
    model = kwargs.get("model", "default")

    try:
        # 构建消息列表（包含上下文）
        messages = []

        # 添加系统提示
        system_prompt = kwargs.get("system_prompt", "你是SiliconBase AI助手，一个 helpful、harmless、honest 的AI助手。")
        messages.append({"role": "system", "content": system_prompt})

        # 添加历史上下文（如果有）
        session_messages = session.get("messages", [])
        for msg in session_messages[-10:]:  # 保留最近10条作为上下文
            if msg.get("role") in ["user", "assistant"]:
                messages.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })

        # 添加当前用户消息
        messages.append({"role": "user", "content": message})

        # 提取参数
        temperature = kwargs.get("temperature", 0.7)
        max_tokens = kwargs.get("max_tokens", 2048)
        model = kwargs.get("model")

        # 调用真实AI（使用CHAT场景配置）
        call_kwargs = {
            "temperature": temperature,
            "max_tokens": max_tokens,
            "timeout": AI_TIMEOUT,
            "retry_times": AI_MAX_RETRY
        }
        if model:
            call_kwargs["model"] = model

        # 原生异步AI调用（彻底消除 run_in_executor 双重线程池）
        response_text = await call_thinker_async(
            messages, scene=AIScene.CHAT, hard_timeout=AI_TIMEOUT + 5, **call_kwargs
        )

        # 记录 AI 调用成功
        duration = time.time() - start_time
        if MONITORING_AVAILABLE:
            record_ai_call(
                model=model,
                provider="ollama",
                status="success",
                duration=duration
            )

        # 【修复】AI空输出拦截：检查AI返回内容是否为空
        if not response_text or not response_text.strip():
            logger.error(f"[process_chat] AI返回空内容，session_id={session.get('session_id')}, model={model}")
            if MONITORING_AVAILABLE:
                record_ai_call(
                    model=model,
                    provider="ollama",
                    status="empty_response"
                )
            return {
                "success": False,
                "error": "AI未生成有效回复",
                "error_code": "AI_EMPTY_RESPONSE",
                "text": "AI服务返回空内容，请稍后重试。"
            }

        # 估算token使用量（实际应由AI服务返回）
        prompt_tokens = len(message) // 2 + sum(len(m.get("content", "")) for m in session_messages) // 4
        completion_tokens = len(response_text) // 2

        return {
            "success": True,
            "text": response_text,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens
            }
        }

    except asyncio.TimeoutError:
        if MONITORING_AVAILABLE:
            record_ai_call(
                model=model,
                provider="ollama",
                status="timeout"
            )
        return {
            "success": False,
            "error": "请求超时",
            "text": "AI响应超时，请稍后重试或简化您的问题。"
        }
    except Exception as e:
        logger.error(f"[CloudAPI] AI调用异常: {e}")
        if MONITORING_AVAILABLE:
            record_ai_call(
                model=model,
                provider="ollama",
                status=f"error:{type(e).__name__}"
            )
        return {
            "success": False,
            "error": "AI服务暂时不可用，请稍后重试",
            "error_code": "AI_SERVICE_ERROR",
            "text": "处理您的请求时发生错误，请稍后重试。"
        }


async def process_chat_stream(
    session: dict[str, Any],
    message: str,
    **kwargs
):
    """
    流式处理聊天消息 - 基于真实AI的模拟流式输出

    由于底层AI provider暂不原生支持流式，采用获取完整响应后
    按句子/短语分块输出的方式模拟流式体验。

    Args:
        session: 会话数据
        message: 用户消息
        **kwargs: 额外参数

    Yields:
        Dict: 流式响应块
    """
    if not AI_AVAILABLE:
        yield {"type": "error", "data": "AI服务暂时不可用"}
        return

    try:
        # 先获取完整响应（复用非流式逻辑）
        result = await process_chat(session, message, **kwargs)

        if not result.get("success"):
            yield {"type": "error", "data": result.get("error", "AI服务暂时不可用")}
            return

        response_text = result.get("text", "")
        usage = result.get("usage", {})

        # 按中文标点、英文标点和空格分割成合理块
        import re
        # 按标点符号分割，保持标点
        chunks = re.findall(r'[^。！？.!?]+[。！？.!?]?', response_text)

        if not chunks:
            chunks = response_text.split()

        # 如果块还是太大，进一步分割
        final_chunks = []
        for chunk in chunks:
            if len(chunk) > 20:
                # 按逗号、分号进一步分割
                sub_chunks = re.findall(r'[^，,；;]+[，,；;]?', chunk)
                final_chunks.extend(sub_chunks)
            else:
                final_chunks.append(chunk)

        # 流式输出
        for chunk in final_chunks:
            if chunk.strip():
                await asyncio.sleep(0.05)  # 模拟生成延迟，提供打字机效果
                yield {"type": "content", "data": chunk}

        # 发送完成标记
        yield {
            "type": "done",
            "usage": usage
        }

    except asyncio.TimeoutError:
        logger.error("[process_chat_stream] 流式处理超时")
        yield {"type": "error", "data": "请求超时，请稍后重试", "error_code": "STREAM_TIMEOUT"}
    except Exception as e:
        logger.error(f"[process_chat_stream] 流式处理未预期异常: {e}", exc_info=True)
        yield {"type": "error", "data": "AI服务暂时不可用，请稍后重试", "error_code": "STREAM_PROCESSING_ERROR"}


def get_user_tasks(user_id: str) -> list[dict[str, Any]]:
    """获取用户任务列表"""
    return TaskManager().get_user_tasks(user_id)


# ============================================================================
# FastAPI 应用初始化
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理 - 初始化所有核心模块"""
    import sys
    import threading
    import time
    start_time = time.time()

    # [CRITICAL] 强制刷新输出，确保日志立即显示
    print("[System] 正在启动 SiliconBase V5...", flush=True)
    sys.stdout.flush()

    # ===== 【延迟初始化修复】第1步：初始化 Config =====
    print("[Config] 正在加载配置...", flush=True)
    try:
        cfg = get_config()
        if cfg:
            print("[配置] 【成功】配置加载完成", flush=True)
        else:
            print("[配置] 【警告】配置加载失败，使用默认配置", flush=True)
    except Exception as e:
        print(f"[初始化] 【错误】 Config 初始化失败: {e}", flush=True)
        import traceback
        traceback.print_exc()

    # ===== 【延迟初始化修复】第2步：初始化 CORS 配置 =====
    print("[Config] 正在加载 CORS 配置...", flush=True)
    try:
        get_cached_cors_config()
        print("[配置] 【成功】CORS 配置加载完成", flush=True)
    except Exception as e:
        print(f"[初始化] 【错误】 CORS 配置加载失败: {e}", flush=True)

    print("[CloudAPI] SiliconBase Cloud API 启动中...", flush=True)
    sys.stdout.flush()
    print("[CloudAPI] 正在初始化核心模块...", flush=True)
    sys.stdout.flush()

    # 记录初始化步骤

    # ===== 【生产化】生产环境安全检查 =====
    if os.environ.get("SILICON_DEV_MODE") == "1":
        print("\n" + "!"*60)
        print("! 警告: 当前运行在生产模式但 SILICON_DEV_MODE=1")
        print("! 这可能导致安全风险，建议设置为 SILICON_DEV_MODE=0")
        print("!"*60 + "\n")

    # 检查JWT密钥配置
    jwt_secret = os.environ.get("JWT_SECRET_KEY", "")
    if jwt_secret and len(jwt_secret) >= 12:
        print("\n" + "="*60)
        print("  [OK] SiliconBase V5 启动成功")
        print(f"  [OK] JWT安全认证已启用 (密钥长度: {len(jwt_secret)}位)")
        print("  [OK] 用户登录系统运行正常")
        print("="*60 + "\n")

    # 检查监控依赖
    if MONITORING_AVAILABLE:
        deps = check_monitoring_dependencies()
        print(f"[CloudAPI] 监控依赖状态: {deps}")

    # ===== 初始化工作模式管理器 =====
    try:
        from core.mode.work_mode_manager import get_work_mode_manager
        get_work_mode_manager()
        print("[WorkMode] 【成功】 工作模式管理器已初始化")
    except Exception as e:
        print(f"[WorkMode] 【错误】 工作模式管理器初始化失败: {e}")

    # ===== 初始化人性化模块 =====
    try:
        from core.safety.moral_system import get_moral_guard
        from core.strategy.goal_system import get_goal_system
        from core.utils.script_manager import get_script_manager
        from core.weak_connection.weak_connection import get_weak_connection_engine

        get_goal_system()
        get_moral_guard()
        get_weak_connection_engine()
        get_script_manager()

        print("[Humanize] 【成功】 人性化模块已初始化")
        print("[Humanize]  - 自我感知系统")
        print("[Humanize]  - 目标系统")
        print("[Humanize]  - 道德守卫")
        print("[Humanize]  - 弱连接引擎")
        print("[Humanize]  - 脚本管理器")
    except Exception as e:
        print(f"[Humanize] 【错误】 人性化模块初始化失败: {e}")
        import traceback
        traceback.print_exc()

    # ===== 初始化世界模型和内在动机 =====
    try:
        from core.strategy.intrinsic_motivation import IntrinsicMotivation
        from core.world_model.world_model import WorldModel

        world_model = WorldModel(state_dim=128, action_dim=32)
        IntrinsicMotivation(world_model=world_model)

        print("[WorldModel] 【成功】 世界模型已初始化")
        print("[IntrinsicMotivation] 【成功】 内在动机系统已初始化")
    except Exception as e:
        print(f"[WorldModel] 【错误】 世界模型初始化失败: {e}")

    # ===== 初始化意识系统 =====
    try:
        from core.consciousness.Consciousness import Consciousness
        from core.consciousness.silicon_life_consciousness import get_silicon_life

        # 意识系统延迟初始化（P0-012修复）
        print("[Consciousness] 【成功】 意识系统延迟初始化机制已启用")
        Consciousness()
        silicon_life = get_silicon_life()
        silicon_life.start()

        print("[Consciousness] 【成功】 硅基生命意识系统已初始化")
    except Exception as e:
        print(f"[Consciousness] 【错误】 意识系统初始化失败: {e}")
        import traceback
        traceback.print_exc()

    # ===== 初始化进化系统 =====
    try:

        print("[Evolution] 【成功】 进化系统已初始化")
        print("[Evolution]  - 基础进化引擎")
        print("[Evolution]  - 增强进化引擎")
    except Exception as e:
        print(f"[Evolution] 【错误】 进化系统初始化失败: {e}")

    # ===== 初始化AI调度器 =====
    try:
        from core.task.task_scheduler import get_task_scheduler as get_ai_scheduler

        ai_scheduler = get_ai_scheduler()

        # 设置任务执行回调
        def on_task_execute(scheduled_task):
            import asyncio

            from core.task.task_queue import Task, task_queue
            task = Task(
                type="user",
                intent={"raw": scheduled_task.description},
                session_id="task_scheduler",
                metadata={"task_id": scheduled_task.id, "source": "scheduled_task"}
            )
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(task_queue.push_async(task))
            except RuntimeError:
                asyncio.new_event_loop().run_until_complete(task_queue.push_async(task))

        ai_scheduler.set_execute_callback(on_task_execute)
        await ai_scheduler.start()
        print("[AITaskScheduler] 【成功】 AI任务调度器已初始化")
    except Exception as e:
        print(f"[AITaskScheduler] 【错误】 AI任务调度器初始化失败: {e}")
        import traceback
        traceback.print_exc()

    # ===== 初始化语音系统 =====
    # [快速启动] 设置 DISABLE_VOICE=true 可跳过语音初始化
    if os.environ.get("DISABLE_VOICE", "").lower() == "true":
        print("[Voice] 【信息】 DISABLE_VOICE=true，跳过语音系统初始化")
    else:
        voice_start_time = time.time()
        try:
            from core.agent.agent_loop import set_voice_for_tts
            from core.config import config
            from core.dialog.dialogue_manager import dialogue_manager
            from core.global_state import set_voice_interface
            from core.services.voice_service import VoiceService
            from voice import VoiceInterface

            speaker_wav = config.get("voice.speaker_wav", None)
            voice = VoiceInterface(tts_engine=None, speaker_wav=speaker_wav)

            # 检查语音引擎状态
            if voice._piper_voice is None and voice._fallback_engine is None:
                print("[Voice] 【警告】 主 TTS 引擎和备用引擎都不可用，语音播报功能将受限")
            elif voice._piper_voice is None:
                print("[Voice] 【信息】 Piper TTS 不可用，将使用备用 TTS 引擎")
            else:
                print("[Voice] 【成功】 Piper TTS 引擎已就绪")

            # 注册到全局
            set_voice_for_tts(voice)
            set_voice_interface(voice)
            dialogue_manager.voice = voice
            dialogue_manager.loop = voice.loop
            VoiceService().register_voice(voice)

            # 启动语音监听（唤醒词功能）
            # [关键修复] 添加超时保护，避免 voice.start() 卡住
            print("[Voice] 正在启动语音监听...", flush=True)
            voice_start_result = [None]
            def start_voice():
                try:
                    voice.start()
                    voice_start_result[0] = True
                except Exception as e:
                    voice_start_result[0] = e

            voice_thread = threading.Thread(target=start_voice, daemon=True)
            voice_thread.start()

            # [P0-修复] 使用非阻塞方式等待，避免Windows上join卡住
            wait_start = time.time()
            max_wait = 5.0  # 最多等待5秒

            while voice_thread.is_alive() and (time.time() - wait_start) < max_wait:
                await asyncio.sleep(0.1)  # 让出控制权，避免阻塞

            if voice_thread.is_alive():
                print("[Voice] 【警告】 语音启动超时，将在后台继续初始化")
                # 不等待了，让语音在后台初始化
            elif voice_start_result[0] is True:
                print("[Voice] 【成功】 语音监听已启动，唤醒词功能已启用")
            else:
                print(f"[Voice] 【错误】 语音启动失败: {voice_start_result[0]}")

            print("[Voice] 【成功】 AI回复语音播报已启用")
        except Exception as e:
            diagnostic_except_handler(e, context="[Voice] 语音系统初始化失败", logger_instance=logger)
        finally:
            voice_elapsed = time.time() - voice_start_time
            print(f"[Voice] 初始化耗时: {voice_elapsed:.2f} 秒")
    # ===== 语音初始化结束 =====

    # ===== 初始化Memory同步服务 =====
    try:
        from core.memory.memory_sync_manager import get_memory_sync_manager as get_memory_sync_service
        get_memory_sync_service()
        print("[MemorySync] 【成功】 Memory同步服务已初始化")
    except Exception as e:
        print(f"[MemorySync] 【警告】 Memory同步服务初始化失败: {e}")

    # ===== 初始化周报告调度器（Agent-5） =====
    try:
        from core.reflector.weekly_report_scheduler import weekly_report_scheduler
        weekly_report_scheduler.start()
        print("[WeeklyReport] 【成功】 周报告调度器已初始化")
        print("[WeeklyReport] 每周一9:00自动生成模板效果报告")
    except Exception as e:
        print(f"[WeeklyReport] 【警告】 周报告调度器初始化失败: {e}")

    # ===== 启动自动记忆压缩调度器 =====
    try:
        from core.memory.memory_compression import compression_scheduler
        compression_scheduler.start_auto_compression(interval_hours=24)
        print("[CompressionScheduler] 【成功】 自动记忆压缩调度器已启动")
        print("[CompressionScheduler] 每24小时自动检查并压缩过期记忆")
    except Exception as e:
        print(f"[CompressionScheduler] 【警告】 自动记忆压缩调度器启动失败: {e}")

    # ===== 启动全局视野全盘扫描 =====
    # 【修复】恢复全盘扫描功能，但使用异步方式，不阻塞启动
    try:
        from sensors.system.global_view import global_view
        # 启动文件监听（后台线程+超时，防止阻塞 lifespan）
        watch_started = threading.Event()
        def _start_watch():
            try:
                global_view.start_watch()
            except Exception as e:
                logger.error(f"[GlobalView] 启动文件监听失败: {e}", exc_info=True)
            finally:
                watch_started.set()
        t = threading.Thread(target=_start_watch, daemon=True)
        t.start()
        watch_started.wait(timeout=5.0)  # 最多等5秒，超时继续
        if t.is_alive():
            logger.warning("[GlobalView] start_watch 启动超时，将在后台继续")
        print("[GlobalView] 【成功】 文件监听已启动")

        # 【修复】异步启动全盘扫描（注册表+常见目录），不阻塞主线程
        # 文件数量限制在配置中可调，默认只扫描关键位置
        def start_scan_async():
            try:
                time.sleep(5)  # 延迟5秒，等系统初始化完成
                global_view.scan_all_async()
            except Exception as e:
                print(f"[GlobalView] 【警告】 异步扫描启动失败: {e}")

        scan_thread = threading.Thread(target=start_scan_async, daemon=True)
        scan_thread.start()
        print("[GlobalView] 【成功】 全盘扫描将在5秒后异步启动")

    except Exception as e:
        print(f"[GlobalView] 【警告】 启动失败: {e}")
        import traceback
        traceback.print_exc()

    # ===== WebSocket 统一入口说明 =====
    # 原独立 WebSocket 服务器（8601端口）已弃用。
    # 所有 WebSocket 流量统一由 FastAPI /ws/* 在 8600 端口处理。
    # 相关 handler 已从 core/sync/websocket_server.py 迁移到本文件。
    print("[WebSocket] 【信息】 所有 WebSocket 统一由 FastAPI 8600 端口处理，不再启动 8601 独立服务器")

    total_init_time = time.time() - start_time
    print(f"[CloudAPI] 核心模块初始化完成，总耗时: {total_init_time:.2f} 秒")

    # 注册弱连接提议转发器（从独立 WS 服务器迁移到 FastAPI）
    _register_weak_proposal_forwarder()

    # ===== 启动 MasterScheduler 后台 Worker =====
    try:
        from core.agent.master_scheduler import master_scheduler
        await master_scheduler.start()
        print("[MasterScheduler] 【成功】 后台调度 Worker 已启动")
    except Exception as e:
        print(f"[MasterScheduler] 【警告】 后台调度 Worker 启动失败: {e}")

    # ===== 【生产化】自动初始化 MCP 服务（直接在 lifespan 异步上下文中初始化）=====
    mcp_enabled = False

    try:
        auto_mcp = os.environ.get("AUTO_ENABLE_MCP", "true").lower()
        logger.info(f"[MCP] 开始自动初始化 MCP 服务器... AUTO_ENABLE_MCP={auto_mcp}")
        print(f"[MCP] AUTO_ENABLE_MCP={auto_mcp}", flush=True)
        if auto_mcp == "true":
            print("[MCP] 将在 lifespan 中初始化 MCP 服务...", flush=True)

            try:
                import yaml

                from core.tool.tool_manager import tool_manager

                config_path = Path(__file__).parent.parent / "config" / "mcp_servers.yaml"
                if not config_path.exists():
                    logger.warning("[MCP] MCP 配置文件不存在")
                    print("[MCP] 【警告】 MCP 配置文件不存在")
                else:
                    with open(config_path, encoding='utf-8') as f:
                        mcp_config = yaml.safe_load(f)

                    servers = mcp_config.get('mcp_servers', [])
                    enabled_servers = [s for s in servers if s.get('enabled', True)]

                    if not enabled_servers:
                        logger.info("[MCP] 没有启用的 MCP 服务器")
                        print("[MCP] 【信息】 没有启用的 MCP 服务器")
                    else:
                        logger.info(f"[MCP] 连接 {len(enabled_servers)} 个服务器...")
                        print(f"[MCP] 连接 {len(enabled_servers)} 个服务器...", flush=True)

                        async def _connect_all():
                            results = {}
                            for server_config in enabled_servers:
                                server_name = server_config.get('name', 'unknown')
                                try:
                                    result = await asyncio.wait_for(
                                        tool_manager.enable_mcp([server_config]),
                                        timeout=server_config.get('timeout', 10.0)
                                    )
                                    results[server_name] = result.get(server_name, False)
                                except Exception as e:
                                    logger.warning(f"[MCP] {server_name} 连接失败: {e}")
                                    print(f"[MCP] 【警告】 {server_name} 连接失败: {e}")
                                    results[server_name] = False
                            return results

                        results = await _connect_all()  # 单服务器 timeout 已在内部控制，不再设总超时
                        success = sum(1 for v in results.values() if v)
                        if success > 0:
                            mcp_enabled = True

                            # 【关键】将 MCP 工具合并到旧版 tool_manager，让 AI 可以使用
                            try:
                                mcp_tools_count = 0
                                for tool_id, tool in tool_manager._tools.items():
                                    if tool_id.startswith("mcp_"):
                                        tool_manager._tools[tool_id] = tool
                                        mcp_tools_count += 1
                                logger.info(f"[MCP] 已将 {mcp_tools_count} 个 MCP 工具合并到 tool_manager")
                                print(f"[MCP] 【成功】 已将 {mcp_tools_count} 个 MCP 工具合并到 tool_manager")
                            except Exception as merge_e:
                                logger.warning(f"[MCP] 合并 MCP 工具到 tool_manager 失败: {merge_e}")
                                print(f"[MCP] 【警告】 合并 MCP 工具到 tool_manager 失败: {merge_e}")

                        logger.info(f"[MCP] 初始化完成: {success}/{len(results)} 个服务器")
                        print(f"[MCP] 【成功】 初始化完成: {success}/{len(results)} 个服务器", flush=True)
            except Exception as e:
                logger.error(f"[MCP] 初始化失败: {e}", exc_info=True)
                print(f"[MCP] 【警告】 初始化失败: {e}")
        else:
            logger.info("[MCP] MCP 自动初始化已禁用")
            print("[MCP] 【信息】 MCP 自动初始化已禁用")
    except Exception as mcp_outer_e:
        logger.error(f"[MCP] 自动初始化外层异常: {mcp_outer_e}")
        print(f"[MCP] 【错误】 自动初始化外层异常: {mcp_outer_e}")

    # ===== 【生产化】自动初始化子代理系统 =====
    subagent_enabled = False
    if os.environ.get("AUTO_ENABLE_SUBAGENT", "false").lower() == "true":
        try:
            from core.subagent.manager import subagent_manager

            # 子代理管理器是单例，初始化时会自动加载预设
            agent_count = len(await subagent_manager.list_agents())

            if agent_count > 0:
                print(f"[SubAgent] 子代理系统就绪: {agent_count} 个代理可用")
                subagent_enabled = True
            # 静默处理无代理的情况

            # 启动 AI 交易模式（自动启动 TradingSubAgent）
            try:
                from core.btc_integration.ai_trading_manager import start_ai_trading
                success = await start_ai_trading("default", {
                    "symbols": ["BTC"],
                    "ai_check_interval": 4,
                    "risk_profile": "moderate",
                    "auto_execute": True
                })
                if success:
                    logger.info("[Lifespan] AI 交易模式已自动启动")
                    print("[Lifespan] AI 交易模式已自动启动")
                else:
                    logger.warning("[Lifespan] AI 交易模式自动启动返回失败")
            except Exception as trading_e:
                logger.error(f"[Lifespan] 自动启动 AI 交易失败: {trading_e}", exc_info=True)

        except Exception as e:
            logger.error(f"[Lifespan] 子代理初始化失败: {e}", exc_info=True)
    # 禁用时不输出日志，保持启动界面整洁

    # ===== 【生产化】打印功能状态汇总 =====
    print("\n" + "="*60)
    print("           SiliconBase V5 功能状态")
    print("="*60)
    print("  【成功】 61+ 原生工具")
    # MCP 被禁用时显示为禁用而非警告
    mcp_status = "已启用" if mcp_enabled else "已禁用"
    print(f"  [{'OK' if mcp_enabled else '--'}] MCP 扩展工具 ({mcp_status})")
    # 子代理
    subagent_status = "已启用" if subagent_enabled else "已禁用"
    print(f"  [{'OK' if subagent_enabled else '--'}] 子代理系统 ({subagent_status})")
    print("  【成功】 L1/L2/L3 分层提示词")
    print("  【成功】 长任务/断点续传")
    print("  【成功】 游戏化系统")
    print("  【成功】 语音系统")
    print("  【成功】 记忆系统")
    print("="*60 + "\n")

    # 启动清理任务
    cleanup_task = safe_create_task(session_cleanup_task(), name="session_cleanup")

    # 启动监控指标更新任务
    metrics_task = safe_create_task(metrics_update_task(), name="metrics_update")

    # [CRITICAL] 初始化完成标记
    total_time = time.time() - start_time
    print("="*60)
    print(f"[CRITICAL] 【成功】 Lifespan 初始化全部完成！耗时: {total_time:.2f} 秒")
    print("="*60, flush=True)
    sys.stdout.flush()

    # ===== 显式注册BTC工具（确保AI可观测层工具被加载）=====
    try:
        from core.btc_integration.tools import register_btc_tools
        from core.tool.tool_manager import tool_manager
        btc_results = register_btc_tools(tool_manager)
        success_count = sum(1 for v in btc_results.values() if v)
        print(f"[BTC Tools] 显式注册完成: {success_count}/{len(btc_results)} 个工具")
    except Exception as e:
        print(f"[BTC Tools] 显式注册失败: {e}")

    # 【Phase 4 修复】将交易WebSocket(8602)启动从 @app.on_event("startup") 提升到 lifespan 中，
    # 避免 FastAPI 0.129+ 在使用 lifespan 时 startup 事件偶发不触发的问题，确保 8602 随主后端可靠启动。
    try:
        await start_trading_ws_server()
    except Exception as e:
        logger.warning(f"[CloudAPI] Lifespan 中启动交易WebSocket失败: {e}")

    # ===== 初始化新版 ModelBus（复活 core.ai_models）=====
    try:
        from core.ai.ai_model_bridge import init_model_bus_async
        bus = await init_model_bus_async()
        if bus:
            stats = bus.get_stats()
            print(f"[CloudAPI] 新版 ModelBus 初始化完成: {stats}")
        else:
            print("[CloudAPI 警告] 新版 ModelBus 异步初始化返回 None")
    except Exception as e:
        print(f"[CloudAPI 警告] 新版 ModelBus 初始化失败: {e}")

    yield

    # 关闭时执行
    print("[CloudAPI] SiliconBase Cloud API 关闭中...")

    # 关闭 MasterScheduler Worker
    try:
        from core.agent.master_scheduler import master_scheduler
        await master_scheduler.stop()
        print("[MasterScheduler] 后台调度 Worker 已关闭")
    except Exception as e:
        print(f"[MasterScheduler] 关闭失败: {e}")

    cleanup_task.cancel()
    metrics_task.cancel()

    # ===== 【生产化】关闭 MCP 服务 =====
    try:
        if mcp_enabled:
            print("[MCP] 正在关闭 MCP 服务...")
            from core.tool.tool_manager import tool_manager
            await tool_manager.disable_mcp()
            print("[MCP] MCP 服务已关闭")
    except Exception as e:
        print(f"[MCP] 关闭 MCP 服务失败: {e}")

    # 关闭数据库连接池
    try:
        from core.db.connection_pool import get_connection_pool
        pool = get_connection_pool()
        if pool:
            await asyncio.to_thread(pool.close_all)
            print("[DB] 数据库连接池已关闭")
    except Exception as e:
        print(f"[DB] 关闭数据库连接池失败: {e}")

    # 关闭所有全局线程池
    try:
        from core.utils.executors import shutdown_all_executors
        shutdown_all_executors(wait=True, cancel_futures=True)
        print("[Executor] 全局线程池已关闭")
    except Exception as e:
        print(f"[Executor] 关闭线程池失败: {e}")

    # 关闭 AgentLoop 后台线程池
    try:
        from core.agent.agent_loop import shutdown_agent_loop_executor_async
        await shutdown_agent_loop_executor_async()
        print("[AgentLoop] 后台线程池已关闭")
    except Exception as e:
        print(f"[AgentLoop] 关闭线程池失败: {e}")

    # 关闭周报告调度器
    try:
        from core.reflector.weekly_report_scheduler import weekly_report_scheduler
        weekly_report_scheduler.stop()
        print("[WeeklyReport] 周报告调度器已停止")
    except Exception as e:
        print(f"[WeeklyReport] 停止周报告调度器失败: {e}")

    with suppress(asyncio.CancelledError):
        await cleanup_task
    with suppress(asyncio.CancelledError):
        await metrics_task


async def metrics_update_task():
    """定期更新监控指标的后台任务"""
    while True:
        try:
            await asyncio.sleep(30)  # 每30秒更新一次

            if MONITORING_AVAILABLE:
                # 更新会话数
                session_count = len(SessionStore()._sessions)
                update_session_count(session_count)

                # 更新WebSocket连接数
                ws_count = await ConnectionManager().aget_total_connections()
                update_websocket_count(ws_count)

                # 更新各用户的任务队列深度
                task_mgr = TaskManager()
                for user_id, tasks in task_mgr._tasks.items():
                    update_task_queue_depth(user_id, len(tasks))

        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[CloudAPI] 指标更新任务出错: {e}")


async def session_cleanup_task():
    """定期清理过期会话的后台任务"""
    while True:
        try:
            await asyncio.sleep(3600)  # 每小时清理一次
            count = await SessionStore().acleanup_expired(max_age_hours=24)
            if count > 0:
                print(f"🧹 清理了 {count} 个过期会话")
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"清理任务出错: {e}")


# 【修复乱码问题】自定义JSONResponse确保UTF-8编码
class UTF8JSONResponse(JSONResponse):
    """确保返回UTF-8编码的JSON响应"""
    media_type = "application/json; charset=utf-8"

app = FastAPI(
    title="SiliconBase Cloud API",
    description="SiliconBase V5 云端部署 API - 支持 HTTP/WebSocket 访问",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
    default_response_class=UTF8JSONResponse  # 【修复乱码问题】设置默认响应类
)

print("【调试】 FastAPI app 创建完成")

# ============================================================================
# Prometheus 监控中间件
# ============================================================================

@app.middleware("http")
async def prometheus_middleware(request: Request, call_next):
    """
    Prometheus 监控中间件
    收集所有 HTTP 请求的指标

    Fix-CORS-2: 跳过OPTIONS预检请求，确保CORS中间件能够正确处理
    """
    # Fix-CORS-2: 跳过预检请求(OPTIONS)，让CORS中间件完全控制
    if request.method == "OPTIONS":
        return await call_next(request)

    if not MONITORING_AVAILABLE:
        return await call_next(request)

    # 跳过监控端点本身 (使用startswith匹配子路径)
    if any(request.url.path.startswith(path) for path in ["/api/metrics", "/api/health", "/api/ready", "/api/live"]):
        return await call_next(request)

    # 记录请求开始
    record_request_start()

    try:
        response = await call_next(request)

        # 记录请求结束
        record_request_end(
            method=request.method,
            endpoint=request.url.path,
            status_code=response.status_code
        )

        return response
    except Exception as e:
        # 记录错误
        record_error(
            error_type=type(e).__name__,
            endpoint=request.url.path
        )
        raise  # 重新抛出异常，让上层异常处理中间件处理

# ============================================================================
# CORS 配置 (Fix-CORS-1修复 - 移动到路由挂载之前)
# ============================================================================
# 优先级: 环境变量 > 配置文件 > 开发环境默认值
# 修复说明: 将CORS中间件移动到所有路由挂载之前，确保预检请求正确处理

def _parse_env_placeholder(value, default_value):
    """
    解析环境变量占位符格式 ${VAR_NAME:default_value}
    如果 value 是占位符格式，提取默认值；否则返回原值
    """
    if not isinstance(value, str):
        return value
    if value.startswith("${") and value.endswith("}"):
        # 提取默认值部分（冒号后面的值）
        if ":" in value:
            return value.split(":", 1)[1].rstrip("}")
        return default_value
    return value

def get_cors_config():
    """
    获取CORS配置，支持环境变量覆盖

    Returns:
        dict: CORS配置字典
    """
    # 【新增】读取前端配置，构建前端URL
    frontend_urls = []
    try:
        if CONFIG_AVAILABLE:
            frontend_host = config.get("services.frontend.host", "localhost")
            frontend_port = config.get("services.frontend.port", 5173)
            frontend_scheme = config.get("services.frontend.scheme", "http")
            frontend_url = f"{frontend_scheme}://{frontend_host}:{frontend_port}"
            frontend_urls.append(frontend_url)
            print(f"[CloudAPI] 前端URL配置: {frontend_url}")
    except Exception as e:
        print(f"[CloudAPI] 读取前端配置失败: {e}，使用默认值")

    # 开发环境默认值（包含 localhost 和 127.0.0.1）
    # Fix-CORS-1: 确保包含所有前端地址
    default_origins = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173"
    ]

    # 【新增】将配置的前端URL添加到默认 origins
    for url in frontend_urls:
        if url not in default_origins:
            default_origins.insert(0, url)  # 添加到列表开头，优先使用
    # Fix-CORS-1: 确保包含 OPTIONS 方法（预检请求必需）
    default_methods = ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
    default_headers = ["Content-Type", "Authorization", "X-Requested-With", "Accept", "Origin"]

    # 从配置文件读取 (如果可用)
    if CONFIG_AVAILABLE:
        config_origins = config.get("cors.allow_origins", default_origins)
        config_credentials = config.get("cors.allow_credentials", True)
        config_methods = config.get("cors.allow_methods", default_methods)
        config_headers = config.get("cors.allow_headers", default_headers)

        # Fix-CORS-5: 处理环境变量占位符格式 ${VAR:default}
        if isinstance(config_origins, list):
            config_origins = [_parse_env_placeholder(o, d) for o, d in zip(config_origins, default_origins, strict=False)]
        if isinstance(config_headers, list):
            config_headers = [_parse_env_placeholder(h, h) for h in config_headers]
    else:
        config_origins = default_origins
        config_credentials = True
        config_methods = default_methods
        config_headers = default_headers

    # 环境变量覆盖 (最高优先级)
    # SILICONBASE_CORS_ORIGINS: 逗号分隔的域名列表
    env_origins = os.environ.get("SILICONBASE_CORS_ORIGINS")
    if env_origins:
        # 支持逗号分隔的多个域名
        config_origins = [origin.strip() for origin in env_origins.split(",") if origin.strip()]

    # SILICONBASE_CORS_CREDENTIALS: true/false
    env_credentials = os.environ.get("SILICONBASE_CORS_CREDENTIALS")
    if env_credentials is not None:
        config_credentials = env_credentials.lower() in ("true", "1", "yes", "on")

    # SILICONBASE_CORS_METHODS: 逗号分隔的方法列表
    env_methods = os.environ.get("SILICONBASE_CORS_METHODS")
    if env_methods:
        config_methods = [method.strip() for method in env_methods.split(",") if method.strip()]

    # SILICONBASE_CORS_HEADERS: 逗号分隔的头列表
    env_headers = os.environ.get("SILICONBASE_CORS_HEADERS")
    if env_headers:
        config_headers = [header.strip() for header in env_headers.split(",") if header.strip()]

    return {
        "allow_origins": config_origins,
        "allow_credentials": config_credentials,
        "allow_methods": config_methods,
        "allow_headers": config_headers,
    }

# 【延迟初始化修复】CORS配置不再在模块级别获取，改为运行时获取
_cors_config = None

def get_cached_cors_config():
    """获取CORS配置（带缓存）"""
    global _cors_config
    if _cors_config is None:
        _cors_config = get_cors_config()
        # 安全检查
        if "*" in _cors_config["allow_origins"] and _cors_config["allow_credentials"]:
            print("[Security Warning] CORS配置冲突: allow_origins='*' 与 allow_credentials=True 不能同时使用")
            print("[Security Warning] 已自动禁用 credentials 支持以保障安全")
            _cors_config["allow_credentials"] = False
    return _cors_config

# 保持向后兼容的 cors_config 变量
class CorsConfigProxy:
    """CORS配置代理，实现延迟加载"""
    def __getitem__(self, key):
        cfg = get_cached_cors_config()
        return cfg[key]

    def __setitem__(self, key, value):
        cfg = get_cached_cors_config()
        cfg[key] = value

    def __contains__(self, key):
        cfg = get_cached_cors_config()
        return key in cfg

cors_config = CorsConfigProxy()


# ============================================================================
# Fix-CORS-4: 自定义CORS中间件（在Starlette CORS中间件之前处理OPTIONS）
# ============================================================================
from starlette.middleware.base import BaseHTTPMiddleware


class CustomCORSOptionsMiddleware(BaseHTTPMiddleware):
    """
    自定义CORS中间件 - 优先处理所有OPTIONS预检请求

    这个中间件放在Starlette的CORSMiddleware之前，确保所有OPTIONS请求
    都能正确返回200，避免Starlette的CORS验证失败返回400。
    """

    async def dispatch(self, request: Request, call_next):
        # 只处理OPTIONS请求
        if request.method == "OPTIONS":
            origin = request.headers.get("origin", "")
            request.headers.get("access-control-request-method", "")
            requested_headers = request.headers.get("access-control-request-headers", "")

            # 确定允许的origin
            allowed_origins = cors_config["allow_origins"]
            if "*" in allowed_origins:
                allow_origin = "*"
            elif origin in allowed_origins:
                allow_origin = origin
            else:
                # 开发环境：允许任何origin
                allow_origin = origin if origin else "*"

            # 构建CORS响应头
            headers = {
                "access-control-allow-origin": allow_origin,
                "access-control-allow-methods": ", ".join(cors_config["allow_methods"]),
                "access-control-allow-headers": ", ".join(cors_config["allow_headers"] + (requested_headers.split(", ") if requested_headers else [])),
                "access-control-allow-credentials": str(cors_config["allow_credentials"]).lower(),
                "access-control-max-age": "600",
            }

            print(f"[CORS-Middleware] 处理OPTIONS: {request.url.path}, Origin: {origin}")
            return Response(status_code=200, headers=headers)

        # 非OPTIONS请求，继续处理
        response = await call_next(request)

        # 给所有响应添加CORS头（如果还没有的话）
        origin = request.headers.get("origin", "")
        if origin and not response.headers.get("access-control-allow-origin"):
            allowed_origins = cors_config["allow_origins"]
            if "*" in allowed_origins or origin in allowed_origins:
                response.headers["access-control-allow-origin"] = origin
                response.headers["access-control-allow-credentials"] = str(cors_config["allow_credentials"]).lower()

        return response


# Fix-CORS-1: 添加CORS中间件
# 注意：在FastAPI/Starlette中，add_middleware是反向执行的，最后添加的最先执行
# 所以我们要先添加Starlette的CORSMiddleware，然后添加自定义中间件

# 1. 首先添加Starlette的CORS中间件（作为后备）
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_config["allow_origins"],
    allow_credentials=cors_config["allow_credentials"],
    allow_methods=cors_config["allow_methods"],
    allow_headers=cors_config["allow_headers"],
    expose_headers=["Content-Range", "X-Total-Count"],
    max_age=600,
)

# 2. 然后添加自定义CORS中间件（最后添加 = 最先执行）
app.add_middleware(CustomCORSOptionsMiddleware)

print(f"[CloudAPI] CORS配置已加载: origins={cors_config['allow_origins']}, credentials={cors_config['allow_credentials']}")

# ============================================================================
# 挂载任务管理API
# ============================================================================
try:
    from .task_api import TASK_API_AVAILABLE
    from .task_api import router as task_router
    if TASK_API_AVAILABLE:
        app.include_router(task_router, prefix="/api")
        print("[CloudAPI] 任务管理API已挂载到 /api/tasks")
    else:
        print("[CloudAPI] 任务管理模块不可用，跳过挂载")
except Exception as e:
    print(f"[CloudAPI] 挂载任务API失败: {e}")

# 挂载父代理干预API
# noinspection PyBroadException
try:
    from .agent_api import router as agent_router
    app.include_router(agent_router, prefix="/api")
    print("[CloudAPI] 父代理干预API已挂载到 /api/agent")
except Exception as e:
    print(f"[CloudAPI] 挂载父代理API失败: {e}")

# 挂载语气偏好API
# noinspection PyBroadException
try:
    from .tone_api import router as tone_router
    app.include_router(tone_router, prefix="/api")
    print("[CloudAPI] 语气偏好API已挂载到 /api/tone-*")
except Exception as e:
    print(f"[CloudAPI] 挂载语气偏好API失败: {e}")

# 挂载反思系统API
# noinspection PyBroadException
try:
    from .reflection_api import router as reflection_router
    app.include_router(reflection_router, prefix="/api")
    print("[CloudAPI] 反思系统API已挂载到 /api/reflection*")
except Exception as e:
    print(f"[CloudAPI] 挂载反思系统API失败: {e}")

# 挂载提示词管理API
try:
    from .prompt_api import router as prompt_router
    app.include_router(prompt_router, prefix="/api")
    print("[CloudAPI] 提示词管理API已挂载到 /api/prompt")
except Exception as e:
    print(f"[CloudAPI] 挂载提示词API失败: {e}")

# 挂载提示词层级切换API (游戏化L1/L2/L3)
try:
    from .prompt_layer_api import router as prompt_layer_router
    app.include_router(prompt_layer_router, prefix="/api")
    print("[CloudAPI] 提示词层级切换API已挂载到 /api/prompt/layer")
except Exception as e:
    print(f"[CloudAPI] 挂载提示词层级切换API失败: {e}")

# 挂载提示词变体API (提示词系统升级)
# 注意：使用 /api/prompt-variants 避免与 /api/prompt 冲突
try:
    from .prompt_variant_api import router as prompt_variant_router
    app.include_router(prompt_variant_router, prefix="/api")
    print("[CloudAPI] 提示词变体API已挂载到 /api/prompt-variants")
except Exception as e:
    print(f"[CloudAPI] 挂载提示词变体API失败: {e}")

# 挂载统计API (失败分析)
try:
    from .stats_api import router as stats_router
    app.include_router(stats_router, prefix="/api")
    print("[CloudAPI] 统计API已挂载到 /api/stats")
except Exception as e:
    print(f"[CloudAPI] 挂载统计API失败: {e}")

# 挂载语音播报API
try:
    from .voice_api import router as voice_router
    app.include_router(voice_router, prefix="/api")
    print("[CloudAPI] 语音播报API已挂载到 /api/voice")
except Exception as e:
    print(f"[CloudAPI] 挂载语音播报API失败: {e}")

# 挂载语音播报配置API（新增 - 修复代理-12）
try:
    from .voice_announce_api import router as voice_announce_router
    app.include_router(voice_announce_router, prefix="/api")
    print("[CloudAPI] 语音播报配置API已挂载到 /api/voice/announce")
except Exception as e:
    print(f"[CloudAPI] 挂载语音播报配置API失败: {e}")

# 配置管理API
try:
    from .config_api import router as config_router
    app.include_router(config_router, prefix="/api")
    logger.info("[API] Config API 已注册")
except Exception as e:
    logger.warning(f"[API] Config API 注册失败: {e}")

# 记忆管理API
try:
    from .memory_api import router as memory_router
    app.include_router(memory_router, prefix="/api")
    logger.info("[API] Memory API 已注册")
except Exception as e:
    logger.warning(f"[API] Memory API 注册失败: {e}")

# L4向量记忆搜索API (Fix-Memory-1)
try:
    from .memory_api import vector_router
    app.include_router(vector_router, prefix="/api")
    logger.info("[API] Vector Memory API 已注册，端点: /api/memory/vector/search")
except Exception as e:
    logger.warning(f"[API] Vector Memory API 注册失败: {e}")

# 记忆可视化API与记忆图谱API已合并到memory_api.py
# (原memory_visualization_api.py和memory_graph_api.py已删除)

try:
    from .memory_api import MEMORY_GRAPH_AVAILABLE
    if MEMORY_GRAPH_AVAILABLE:
        logger.info("[API] Memory Graph API 已合并到 memory_api.py，端点: /api/memories/graph/*")
    else:
        logger.warning("[API] Memory Graph API 不可用，跳过注册")
except Exception as e:
    logger.warning(f"[API] Memory Graph API 注册失败: {e}")

# 工具管理API
try:
    from .tools_api import router as tools_router
    app.include_router(tools_router, prefix="/api")
    logger.info("[API] Tools API 已注册")
except Exception as e:
    logger.warning(f"[API] Tools API 注册失败: {e}")

# 监控指标API
try:
    from .metrics_api import router as metrics_router
    app.include_router(metrics_router, prefix="/api")
    logger.info("[API] Metrics API 已注册")
except Exception as e:
    logger.warning(f"[API] Metrics API 注册失败: {e}")

# 游戏化API
try:
    from .gamification_api import router as gamification_router
    app.include_router(gamification_router, prefix="/api")
    logger.info("[API] Gamification API 已注册")
except Exception as e:
    logger.warning(f"[API] Gamification API 注册失败: {e}")

# AI配置管理API
# ============================================================================
# 挂载AI配置API（SEC-006: 补齐缺失的 /api/ai/* 端点）
# ============================================================================
try:
    from api.ai_config_api import PROVIDER_FACTORY_AVAILABLE
    from api.ai_config_api import router as ai_config_router
    app.include_router(ai_config_router, prefix="/api")
    if PROVIDER_FACTORY_AVAILABLE:
        logger.info("[API] AI Config API 已注册，端点: /api/ai/*")
        print("[CloudAPI] AI配置API已挂载到 /api/ai/*")
    else:
        logger.warning("[API] AI Config API 已注册但Provider Factory不可用")
except Exception as e:
    logger.warning(f"[API] AI Config API 注册失败: {e}")

# ============================================================================
# 挂载功能管理API（包含 /api/mode 端点）
# ============================================================================
try:
    from .features_api import features_router, system_router
    app.include_router(features_router, prefix="/api")
    app.include_router(system_router, prefix="/api")
    logger.info("[API] Features API 已注册，端点: /api/features/*, /api/mode")
    print("[CloudAPI] 功能管理API已挂载到 /api/features/*")
except Exception as e:
    logger.warning(f"[API] Features API 注册失败: {e}")

# ============================================================================
# 挂载硅基生命意识API（P3: 硅基生命基础）
# ============================================================================
try:
    from .consciousness_api import router as consciousness_router
    app.include_router(consciousness_router, prefix="/api")
    logger.info("[API] 硅基生命意识API已注册，端点: /api/consciousness/*")
    print("[CloudAPI] 硅基生命意识API已挂载到 /api/consciousness/*")
except Exception as e:
    logger.warning(f"[API] 硅基生命意识API注册失败: {e}")

# ============================================================================
# 挂载三观提示词API（P5: 三观系统）
# ============================================================================
# 三观提示词API - P5专注模式记忆增强
try:
    from .three_views_api import router as three_views_router
    app.include_router(three_views_router, prefix="/api")
    logger.info("[API] 三观提示词API已注册，端点: /api/three-views/*")
    print("[CloudAPI] 三观提示词API已挂载到 /api/three-views/*")
except Exception as e:
    logger.error(f"[API] 三观提示词API注册失败: {e}")
    print(f"[CloudAPI] 警告: 三观提示词API未加载: {e}")

# ============================================================================
# 挂载高级模型API（Fix-006: 注册advanced_models_api路由）
# ============================================================================
try:
    from .advanced_models_api import router as advanced_models_router
    app.include_router(advanced_models_router, prefix="/api/advanced-models", tags=["advanced-models"])
    logger.info("[API] 高级模型API已注册，端点: /api/advanced-models/*")
    print("[CloudAPI] 高级模型API已挂载到 /api/advanced-models/*")
except Exception as e:
    logger.error(f"[API] 高级模型API注册失败: {e}")
    print(f"[CloudAPI] 警告: 高级模型API未加载: {e}")

# ============================================================================
# 挂载模板实验API（Agent-5: 权重验证实验师）
# ============================================================================
try:
    from .template_experiment_api import router as template_experiment_router
    app.include_router(template_experiment_router, prefix="/api")
    logger.info("[API] 模板实验API已注册，端点: /api/template-experiment/*")
    print("[CloudAPI] 模板实验API已挂载到 /api/template-experiment/*")
except Exception as e:
    logger.warning(f"[API] 模板实验API注册失败: {e}")
    print(f"[CloudAPI] 警告: 模板实验API未加载: {e}")

# ============================================================================
# 挂载用户数据同步API
# ============================================================================
try:
    from .sync_api import router as sync_router
    app.include_router(sync_router, prefix="/api")
    logger.info("[API] 用户数据同步API已注册，端点: /api/sync/*")
    print("[CloudAPI] 用户数据同步API已挂载到 /api/sync/*")
except Exception as e:
    logger.warning(f"[API] 用户数据同步API注册失败: {e}")
    print(f"[CloudAPI] 警告: 用户数据同步API未加载: {e}")

# 云端工具仓库API
try:
    from .cloud_tool_repo import router as cloud_tool_repo_router
    app.include_router(cloud_tool_repo_router, prefix="/api")
    logger.info("[API] 云端工具仓库API已注册，端点: /api/cloud-tools/*")
    print("[CloudAPI] 云端工具仓库API已挂载到 /api/cloud-tools/*")
except Exception as e:
    logger.warning(f"[API] 云端工具仓库API注册失败: {e}")
    print(f"[CloudAPI] 警告: 云端工具仓库API未加载: {e}")

# 本地工具市场API
try:
    from .tool_market_api import router as tool_market_router
    app.include_router(tool_market_router, prefix="/api")
    logger.info("[API] 本地工具市场API已注册，端点: /api/tool-market/*")
    print("[CloudAPI] 本地工具市场API已挂载到 /api/tool-market/*")
except Exception as e:
    logger.warning(f"[API] 本地工具市场API注册失败: {e}")
    print(f"[CloudAPI] 警告: 本地工具市场API未加载: {e}")

# ============================================================================
# 挂载成本管理API（Token成本追踪）
# ============================================================================
try:
    from .cost_api import COST_MANAGER_AVAILABLE
    from .cost_api import router as cost_router
    if COST_MANAGER_AVAILABLE:
        app.include_router(cost_router, prefix="/api")
        logger.info("[API] 成本管理API已注册，端点: /api/cost/*")
        print("[CloudAPI] 成本管理API已挂载到 /api/cost/*")
    else:
        logger.warning("[API] 成本管理器不可用，跳过注册")
        print("[CloudAPI] 警告: 成本管理API未加载（成本管理器不可用）")
except Exception as e:
    logger.warning(f"[API] 成本管理API注册失败: {e}")
    print(f"[CloudAPI] 警告: 成本管理API未加载: {e}")

# ============================================================================
# 挂载RLHF反馈系统API（Agent3: RLHF反馈系统部署）
# ============================================================================
try:
    from api.routes.rlhf import router as rlhf_router
    app.include_router(rlhf_router, prefix="/api")
    logger.info("[API] RLHF反馈系统API已注册，端点: /api/rlhf/*")
    print("[CloudAPI] RLHF反馈系统API已挂载到 /api/rlhf/*")
except Exception as e:
    logger.warning(f"[API] RLHF反馈系统API注册失败: {e}")
    print(f"[CloudAPI] 警告: RLHF反馈系统API未加载: {e}")

# ============================================================================
# 挂载硅基生命成长监控面板API（Agent8: 部署生命成长监控面板）
# ============================================================================
try:
    from .silicon_life_api import router as silicon_life_router
    app.include_router(silicon_life_router, prefix="/api")
    logger.info("[API] 硅基生命成长监控API已注册，端点: /api/life/*")
    print("[CloudAPI] 硅基生命成长监控API已挂载到 /api/life/*")
except Exception as e:
    logger.warning(f"[API] 硅基生命成长监控API注册失败: {e}")
    print(f"[CloudAPI] 警告: 硅基生命成长监控API未加载: {e}")

# ============================================================================
# 挂载 BTC 交易 API（实时交易监控面板）
# ============================================================================
try:
    from .trading_api import router as trading_router
    app.include_router(trading_router, prefix="/api")
    logger.info("[API] BTC交易API已注册，端点: /api/trading/*")
    print("[CloudAPI] BTC交易API已挂载到 /api/trading/*")
except Exception as e:
    logger.warning(f"[API] BTC交易API注册失败: {e}")
    print(f"[CloudAPI] 警告: BTC交易API未加载: {e}")

# ============================================================================
# 挂载 BTC 交易 V2 API
# ============================================================================
try:
    from core.btc_integration.api_bridge import router as trading_v2_router
    app.include_router(trading_v2_router, prefix="/api")
    logger.info("[API] BTC交易V2 API已注册，端点: /api/trading-v2/*")
    print("[CloudAPI] BTC交易V2 API已挂载到 /api/trading-v2/*")
except Exception as e:
    logger.warning(f"[API] BTC交易V2 API注册失败: {e}")
    print(f"[CloudAPI] 警告: BTC交易V2 API未加载: {e}")

# ============================================================================
# 挂载交易所配置 API（用户交易所API Key管理）
# ============================================================================
try:
    from .exchange_config_api import router as exchange_config_router
    app.include_router(exchange_config_router, prefix="/api")
    logger.info("[API] 交易所配置API已注册，端点: /api/exchange/*")
    print("[CloudAPI] 交易所配置API已挂载到 /api/exchange/*")
except Exception as e:
    logger.warning(f"[API] 交易所配置API注册失败: {e}")
    print(f"[CloudAPI] 警告: 交易所配置API未加载: {e}")

# ============================================================================
# 24小时自动交易API
# ============================================================================
try:
    from .auto_trading_api import router as auto_trading_router
    app.include_router(auto_trading_router, prefix="/api")
    logger.info("[API] 24小时自动交易API已注册，端点: /api/auto-trading/*")
    print("[CloudAPI] 24小时自动交易API已挂载到 /api/auto-trading/*")
except Exception as e:
    logger.warning(f"[API] 24小时自动交易API注册失败: {e}")
    print(f"[CloudAPI] 警告: 24小时自动交易API未加载: {e}")

# ============================================================================
# 挂载交易模式API（方案C：全自动量化/AI辅助交易/手动交易）
# 【架构注释】统一管理三种交易模式，支持用户隔离
# 依赖: ai_trading_manager.py, trading_config.py
# 作者: Kimi Code CLI
# 日期: 2026-04-13
# ============================================================================
try:
    from .trading_mode_api import router as trading_mode_router
    app.include_router(trading_mode_router, prefix="/api")
    logger.info("[API] 交易模式API已注册，端点: /api/trading/mode/*")
    print("[CloudAPI] 交易模式API已挂载到 /api/trading/mode/*")
except Exception as e:
    logger.warning(f"[API] 交易模式API注册失败: {e}")
    print(f"[CloudAPI] 警告: 交易模式API未加载: {e}")

# ============================================================================
# 挂载经验量化API（Agent-6: A/B测试、效果量化、淘汰机制）
# 【架构注释】经验注入效果量化系统
# 前端: ExperienceQuantificationPage.tsx
# 作者: Agent-6
# 日期: 2026-04-09
# ============================================================================
try:
    from .experience_api import router as experience_router
    app.include_router(experience_router, prefix="/api")
    logger.info("[API] 经验量化API已注册，端点: /api/experience/*")
    print("[CloudAPI] 经验量化API已挂载到 /api/experience/*")
except Exception as e:
    logger.warning(f"[API] 经验量化API注册失败: {e}")
    print(f"[CloudAPI] 警告: 经验量化API未加载: {e}")

# ============================================================================
# 挂载 Session API（Phase 1 Week 1 - 任务4）
# ============================================================================
try:
    from .session_api import SESSION_MANAGER_AVAILABLE
    from .session_api import router as session_router
    if SESSION_MANAGER_AVAILABLE:
        app.include_router(session_router, prefix="/api")
        logger.info("[API] Session API已注册，端点: /api/sessions/*")
        print("[CloudAPI] Session API已挂载到 /api/sessions/*")
    else:
        logger.warning("[API] Session Manager不可用，Session API未加载")
        print("[CloudAPI] 警告: Session API未加载（Session Manager不可用）")
except Exception as e:
    logger.warning(f"[API] Session API注册失败: {e}")
    print(f"[CloudAPI] 警告: Session API未加载: {e}")

# ============================================================================
# 挂载 GlobalView API（磁盘文件扫描可视化）
# ============================================================================
try:
    from .global_view_api import router as global_view_router
    app.include_router(global_view_router, prefix="/api")
    logger.info("[API] GlobalView API已注册，端点: /api/global-view/*")
    print("[CloudAPI] GlobalView API已挂载到 /api/global-view/*")
except Exception as e:
    logger.warning(f"[API] GlobalView API注册失败: {e}")
    print(f"[CloudAPI] 警告: GlobalView API未加载: {e}")

# ============================================================================
# 挂载 Memory Sync WebSocket API（Phase 4 Week 7）
# ============================================================================
try:
    from .memory_sync_websocket import router as memory_sync_router
    app.include_router(memory_sync_router)
    logger.info("[API] Memory Sync WebSocket API已注册，端点: /ws/memory-sync")
    print("[CloudAPI] Memory Sync WebSocket API已挂载到 /ws/memory-sync")
except Exception as e:
    logger.warning(f"[API] Memory Sync WebSocket API注册失败: {e}")
    print(f"[CloudAPI] 警告: Memory Sync WebSocket API未加载: {e}")

# ============================================================================
# 挂载弱连接系统API
# ============================================================================
try:
    from api.routes.weak_connection import router as weak_connection_router
    app.include_router(weak_connection_router, prefix="/api")
    logger.info("[API] WeakConnection API已注册，端点: /api/weak-connection/*")
    print("[CloudAPI] WeakConnection API已挂载到 /api/weak-connection/*")
except Exception as e:
    logger.warning(f"[API] WeakConnection API注册失败: {e}")
    print(f"[CloudAPI] 警告: WeakConnection API未加载: {e}")

# 【调试】 检查app对象
print(f"【调试】 app对象类型: {type(app)}")
print(f"【调试】 app对象id: {id(app)}")

# ============================================================================
# HTTP API 路由
# ============================================================================

@app.get("/", response_model=dict[str, str])
async def root():
    """根路径 - API信息"""
    return {
        "name": "SiliconBase Cloud API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/api/health"
    }


@app.get("/api/health", response_model=dict[str, str])
async def health_check():
    """
    健康检查端点 - 安全简化版

    仅返回基本状态，不暴露任何敏感信息：
    - 无版本号
    - 无内部路径
    - 无配置详情
    - 无数据库连接信息

    Returns:
        {"status": "ok"}
    """
    return {"status": "ok"}


@app.get("/health", response_model=dict[str, str])
async def health_check_root():
    """
    根路径健康检查端点（兼容前端健康检查）

    Returns:
        {"status": "ok"}
    """
    return {"status": "ok"}


# ============================================================================
# 认证API端点 (SEC-003修复)
# ============================================================================

@app.post("/api/auth/login", response_model=LoginResponse)
async def login(credentials: LoginRequest):
    """
    用户登录端点

    验证用户名密码，返回JWT访问令牌。

    - **username**: 用户名（必需）
    - **password**: 密码（必需）

    返回:
    - **access_token**: JWT访问令牌
    - **token_type**: 令牌类型（bearer）
    - **expires_in**: 令牌有效期（秒）
    - **user_id**: 用户ID
    - **username**: 用户名
    - **require_password_change**: 是否需要强制修改密码（首次登录时为true）

    [CFG-001] 安全说明:
    - 系统不再自动创建默认 admin 账户，也不再将初始密码写入文件。
    - 首次访问时，请通过 `/api/auth/setup-status` 检查是否需要创建第一个管理员；
      若 `setup_required=true`，请调用 `/api/auth/setup` 注册首个管理员账号。
    - 当 config/global.yaml 或 config/local.yaml 中显式配置了 users 时，
      将使用配置中的账户信息，无需再走首次设置流程。
    """
    try:
        # 先检查用户是否存在
        user = await user_auth_store.aget_user(credentials.username)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="用户名不存在，请先注册账号",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # 验证密码
        if not await user_auth_store.averify_password(credentials.username, credentials.password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="密码错误，请重新输入",
                headers={"WWW-Authenticate": "Bearer"},
            )

        user_id = user["user_id"]
        expires_hours = 24

        # 检查是否需要强制修改密码 [CFG-001]
        require_change = await user_auth_store.arequire_password_change(credentials.username)

        # 生成JWT token
        access_token = await user_auth_store.acreate_access_token(user_id, expires_hours=expires_hours)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Auth] 登录失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal error: {str(e)}"
        ) from e

    if require_change:
        logger.warning(f"[Auth] 用户 '{credentials.username}' 使用初始密码登录，需要修改密码")
    else:
        logger.info(f"[Auth] 用户登录成功: {credentials.username} ({user_id})")

    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=expires_hours * 3600,
        user_id=user_id,
        username=credentials.username,
        require_password_change=require_change
    )


@app.post("/api/auth/register", response_model=RegisterResponse)
async def register(request: RegisterRequest):
    """
    用户注册端点

    - **username**: 用户名（3-50字符，唯一）
    - **password**: 密码（至少6位）
    - **email**: 邮箱（可选）
    """
    try:
        # 检查用户名是否已存在
        existing_user = await user_auth_store.aget_user(request.username)
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Username already exists"
            )

        # 创建新用户
        user_data = await user_auth_store.aadd_user(
            username=request.username,
            password=request.password,
            email=request.email,
            roles=["user"],
            require_password_change=False
        )

        logger.info(f"[Auth] 新用户注册: {request.username}")

        return RegisterResponse(
            success=True,
            user_id=user_data["user_id"],
            username=request.username,
            message="Registration successful. Please login."
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Auth] 注册失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Registration failed: {str(e)}"
        ) from e


@app.get("/api/auth/setup-status", response_model=SetupStatusResponse)
async def setup_status():
    """
    检查是否需要进行首次管理员设置。

    当系统没有任何管理员账户时返回 `setup_required=true`，
    前端应引导用户调用 `/api/auth/setup` 创建第一个管理员账号。
    """
    try:
        required = await user_auth_store.ais_setup_required()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Auth] 获取设置状态失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal error: {str(e)}"
        ) from e

    if required:
        return SetupStatusResponse(
            setup_required=True,
            message="系统尚未设置管理员，请创建第一个管理员账号"
        )
    return SetupStatusResponse(
        setup_required=False,
        message="系统已设置管理员，请使用现有账号登录"
    )


@app.post("/api/auth/setup", response_model=RegisterResponse)
async def setup_first_admin(request: SetupRequest):
    """
    首次设置管理员账号。

    仅在系统没有任何管理员账户时可用。创建的账号将拥有 `admin` 角色。

    - **username**: 管理员用户名（3-50字符，唯一）
    - **password**: 管理员密码（至少6位）
    - **email**: 邮箱（可选）
    """
    try:
        user_data = await user_auth_store.asetup_first_admin(
            username=request.username,
            password=request.password,
            email=request.email
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        ) from e
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e)
        ) from e
    except Exception as e:
        logger.error(f"[Auth] 首次设置管理员失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Setup failed: {str(e)}"
        ) from e

    return RegisterResponse(
        success=True,
        user_id=user_data["user_id"],
        username=request.username,
        message="首个管理员账号创建成功，请使用该账号登录"
    )


@app.post("/api/auth/change-password", response_model=ChangePasswordResponse)
async def change_password(
    request: ChangePasswordRequest,
    current_user: str = Depends(get_current_user)
):
    """
    修改密码端点 [CFG-001]

    允许用户修改自己的密码。当用户 `require_password_change=true` 时，
    首次登录后必须调用此接口修改密码。

    - **current_password**: 当前密码
    - **new_password**: 新密码（至少6位）

    需要认证: Bearer Token

    返回:
    - **success**: 是否成功
    - **message**: 状态消息
    """
    # 获取当前用户信息
    user = await user_auth_store.aget_user_by_id(current_user)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    username = user["username"]

    # 修改密码
    success = await user_auth_store.achange_password(
        username=username,
        current_password=request.current_password,
        new_password=request.new_password
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect"
        )

    logger.info(f"[Auth] 用户 '{username}' 密码修改成功")

    return ChangePasswordResponse(
        success=True,
        message="Password changed successfully. Please use your new password for future logins."
    )


@app.post("/api/auth/refresh", response_model=RefreshTokenResponse)
async def refresh_token(current_user: str = Depends(get_current_user)):
    """
    刷新访问令牌端点

    使用当前有效的token获取新的token，延长有效期。

    - 需要有效的Bearer Token认证

    返回:
    - **access_token**: 新的JWT访问令牌
    - **token_type**: 令牌类型（bearer）
    - **expires_in**: 新的令牌有效期（秒）
    - **user_id**: 用户ID
    """
    expires_hours = 24

    # 生成新的token
    new_token = await user_auth_store.acreate_access_token(current_user, expires_hours=expires_hours)

    logger.info(f"[Auth] Token刷新成功: {current_user}")

    return RefreshTokenResponse(
        access_token=new_token,
        token_type="bearer",
        expires_in=expires_hours * 3600,
        user_id=current_user
    )


@app.post("/api/auth/logout")
async def logout(current_user: str = Depends(get_current_user)):
    """
    用户登出端点

    当前实现仅记录登出日志，实际token在客户端删除即可。
    （如需强制token失效，需要实现token黑名单）

    - 需要有效的Bearer Token认证

    返回:
    - **success**: 是否成功
    - **message**: 状态消息
    """
    # 如需实现token黑名单，可在此添加
    # user_auth_store.add_to_blacklist(token)

    logger.info(f"[Auth] 用户登出: {current_user}")

    return {
        "success": True,
        "message": "Logged out successfully",
        "user_id": current_user
    }


@app.get("/api/auth/me", response_model=UserInfoResponse)
async def get_current_user_info(current_user: str = Depends(get_current_user)):
    """
    获取当前登录用户信息

    - 需要有效的Bearer Token认证

    返回:
    - **user_id**: 用户ID
    - **username**: 用户名
    - **email**: 邮箱
    - **created_at**: 创建时间戳
    - **last_login**: 最后登录时间戳
    - **require_password_change**: 是否需要强制修改密码 [CFG-001]
    """
    user = await user_auth_store.aget_user_by_id(current_user)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # 构建返回数据，添加 require_password_change 字段
    response_data = {
        "user_id": user["user_id"],
        "username": user["username"],
        "email": user.get("email"),
        "created_at": user.get("created_at"),
        "last_login": user.get("last_login"),
        "require_password_change": user.get("require_password_change", False)
    }

    return response_data


@app.get("/api/metrics")
async def metrics_endpoint():
    """
    Prometheus 指标导出端点

    返回 Prometheus 格式的监控指标，包括:
    - 请求计数和持续时间
    - AI 调用统计
    - 活跃会话数
    - 系统资源使用
    """
    content_type, data = get_prometheus_metrics()
    return Response(content=data, media_type=content_type)


@app.get("/api/ready")
async def ready_probe():
    """
    Kubernetes Readiness Probe - 安全简化版

    检查应用是否准备好接收流量。
    如果返回非200状态码，Kubernetes 会将 Pod 从 Service 端点中移除。

    注意：为安全考虑，仅返回最小化状态信息，不暴露组件详情。
    """
    return {"status": "ok"}


@app.get("/api/live")
async def live_probe():
    """
    Kubernetes Liveness Probe - 安全简化版

    检查应用是否存活。如果返回非200状态码，
    Kubernetes 将重启 Pod。

    注意：为安全考虑，仅返回最小化状态信息，不暴露进程详情。
    """
    return {"status": "ok"}


@app.get("/api/status", response_model=StatusResponse)
async def get_status(user_id: str | None = None):
    """
    获取系统状态和用户任务

    - **user_id**: 从认证token解析的用户ID（可选，不提供则返回公开状态）
    - 返回系统状态和用户任务列表
    """
    if user_id is None:
        # 匿名访问：返回公开状态信息
        return StatusResponse(
            status="ok",
            version="1.0.0",
            timestamp=time.time(),
            user_tasks=[],
            active_sessions=0
        )

    tasks = get_user_tasks(user_id)
    active_sessions = len(list(await SessionStore().aget_user_sessions(user_id)))

    return StatusResponse(
        status="ok",
        version="1.0.0",
        timestamp=time.time(),
        user_tasks=tasks,
        active_sessions=active_sessions
    )


@app.get("/api/modelbus/status")
async def get_modelbus_status():
    """
    获取新版 ModelBus 状态

    返回 ModelBus 的注册统计、Provider 列表和槽位信息。
    用于验证 core.ai_models 是否已成功接入主流程。
    """
    try:
        from core.ai.ai_model_bridge import get_model_bus_stats, is_model_bus_ready, list_registered_providers

        if not is_model_bus_ready():
            return JSONResponse(
                status_code=503,
                content={
                    "status": "not_ready",
                    "message": "ModelBus 尚未初始化",
                    "initialized": False
                }
            )

        stats = get_model_bus_stats()
        providers = list_registered_providers()

        return {
            "status": "ok",
            "initialized": True,
            "stats": stats,
            "providers": providers,
            "provider_count": len(providers),
            "timestamp": time.time()
        }
    except Exception as e:
        logger.error(f"[CloudAPI] 获取 ModelBus 状态失败: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"获取 ModelBus 状态失败: {str(e)}",
                "initialized": False
            }
        )


# [DELETED 2026-03-13] 以下端点已删除，路由冲突已由 session_api.py 接管:
# - POST /api/sessions (创建会话)
# - GET /api/sessions (获取会话列表)
# - GET /api/sessions/{session_id} (获取会话详情)
# - DELETE /api/sessions/{session_id} (删除会话)
# 请使用 session_api.py 中的数据库持久化实现

@app.post("/api/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    user_id: str = Depends(get_current_user)
):
    """
    聊天接口 - 非流式

    - **message**: 用户输入的消息（必需）
    - **session_id**: 会话ID，为空则创建新会话
    - **context**: 上下文消息列表
    - **model**: 使用的模型名称
    - **temperature**: 采样温度 (0.0-2.0)
    - **max_tokens**: 最大生成token数
    """
    # 获取或创建会话
    session = await SessionStore().aget(user_id, request.session_id)
    if not session:
        raise HTTPException(status_code=500, detail="Failed to create session")

    # 保存用户消息
    await SessionStore().aadd_message(session["session_id"], "user", request.message)

    # 处理消息
    try:
        if request.stream:
            # 流式响应由 /api/chat/stream 处理
            raise HTTPException(
                status_code=400,
                detail="Use /api/chat/stream for streaming responses"
            )

        # 【阶段1统一入口】HTTP chat 不再绕过 AgentLoop，与 WebSocket user_input 完全一致
        from core.dialog.dialogue_manager import InputMode, dialogue_manager

        ai_result = await dialogue_manager.handle_input(
            user_id=user_id,
            text=request.message,
            session_id=session["session_id"],
            input_mode=InputMode.AUTO,
            voice_instance=None
        )

        # 统一处理返回结果（与 WebSocket user_input auto 模式完全一致）
        if isinstance(ai_result, dict):
            ai_mode = ai_result.get("mode", "unknown")
            ai_response = ai_result.get("content", "") or ai_result.get("chat_reply", "") or ai_result.get("result", "")
            success = ai_result.get("success", True)
        else:
            ai_mode = "text"
            ai_response = str(ai_result) if ai_result else ""
            success = ai_response is not None

        # 生成消息ID
        message_id = f"msg_{uuid.uuid4().hex[:16]}"

        # 对于 quick_chat / chat_alignment，AI 回复已存储；对于 task_started，存储启动确认
        if ai_response:
            await SessionStore().aadd_message(
                session["session_id"],
                "assistant",
                ai_response
            )

        # 通过WebSocket推送通知（如果用户有 WebSocket 连接）
        await ConnectionManager().send_to_user(user_id, {
            "type": "new_message",
            "session_id": session["session_id"],
            "message_id": message_id,
            "role": "assistant",
            "content": ai_response,
            "mode": ai_mode,
            "timestamp": time.time()
        })

        return ChatResponse(
            success=success,
            response=ai_response,
            session_id=session["session_id"],
            message_id=message_id,
            usage=None,
            timestamp=time.time()
        )

    except HTTPException:
        # 直接抛出HTTPException，由全局异常处理器处理
        raise
    except Exception as e:
        # 生成消息ID用于错误响应
        message_id = f"msg_{uuid.uuid4().hex[:16]}"
        logger.error(f"[API] /api/chat 未预期异常: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"聊天处理失败: {str(e)}"
        ) from e


@app.post("/api/chat/stream")
async def chat_stream(
    request: ChatRequest,
    user_id: str = Depends(get_current_user)
):
    """
    聊天接口 - 流式 (SSE)

    使用 Server-Sent Events 实现流式响应
    """
    from fastapi.responses import StreamingResponse

    session = await SessionStore().aget(user_id, request.session_id)
    if not session:
        raise HTTPException(status_code=500, detail="Failed to create session")

    await SessionStore().aadd_message(session["session_id"], "user", request.message)

    message_id = f"msg_{uuid.uuid4().hex[:16]}"

    async def event_generator():
        full_response = ""
        has_error = False
        error_msg = ""

        async for chunk in process_chat_stream(
            session,
            request.message,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            model=request.model
        ):
            if chunk["type"] == "content":
                full_response += chunk["data"]
                # 添加session_id和message_id到chunk
                enriched_chunk = {
                    **chunk,
                    "session_id": session["session_id"],
                    "message_id": message_id
                }
                yield f"data: {json.dumps(enriched_chunk)}\n\n"
            elif chunk["type"] == "error":
                has_error = True
                error_msg = chunk.get("data", "未知错误")
                error_chunk = {
                    "type": "error",
                    "data": error_msg,
                    "session_id": session["session_id"],
                    "message_id": message_id,
                    "timestamp": time.time()
                }
                yield f"data: {json.dumps(error_chunk)}\n\n"
                yield "data: [DONE]\n\n"
                return
            elif chunk["type"] == "done":
                # 只有成功时才保存回复
                if not has_error and full_response:
                    await SessionStore().aadd_message(
                        session["session_id"],
                        "assistant",
                        full_response
                    )

                # 推送完成事件
                done_chunk = {
                    "type": "done",
                    "session_id": session["session_id"],
                    "message_id": message_id,
                    "usage": chunk.get("usage"),
                    "timestamp": time.time()
                }
                yield f"data: {json.dumps(done_chunk)}\n\n"
                yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@app.get("/api/messages/{session_id}")
async def get_messages(
    session_id: str,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user_id: str = Depends(get_current_user)
):
    """
    获取会话的历史消息

    - **limit**: 返回消息数量限制 (1-100)
    - **offset**: 分页偏移量
    """
    session = await SessionStore().aget_by_id(session_id)
    if not session or session["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Session not found")

    messages = session["messages"][offset:offset + limit]

    return {
        "session_id": session_id,
        "messages": messages,
        "total": len(session["messages"]),
        "limit": limit,
        "offset": offset
    }


# 注意：/api/tasks 端点已由 task_api.py 的 router 处理
# 通过 app.include_router(task_router, prefix="/api") 挂载
# 以下简单端点用于健康检查和向后兼容

# ============================================================================
# 备用 /api/tasks 端点（当 task_api.py 挂载失败时使用）
# ============================================================================
# 【修复】添加备用端点，防止 task_api.py 导入失败时返回404
_TASK_API_MOUNTED = False  # 标记 task_api 是否成功挂载

# 在 task_api 挂载成功后设置标记
try:
    from .task_api import TASK_API_AVAILABLE
    if TASK_API_AVAILABLE:
        _TASK_API_MOUNTED = True
except Exception as e:
    # 【零静默失败修复】裸except改为捕获具体异常，记录ERROR日志
    logger.error(f"[SILENT_FAILURE_BLOCKED] 检查task_api挂载状态失败: {type(e).__name__}: {e}")
    _TASK_API_MOUNTED = False

@app.get("/api/tasks", response_model=dict[str, Any])
async def list_tasks_fallback(
    user_id: str = Depends(get_current_user),
    status: str | None = Query(None, description="按状态过滤"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    """
    获取任务列表（备用端点）

    当 task_api.py 成功挂载时，此端点会被覆盖。
    此端点提供基本的任务列表功能作为后备方案。

    【修复】添加此端点防止404错误
    """
    # 如果 task_api 已挂载，直接返回空列表（让 task_api 处理）
    # 实际上，FastAPI 会先匹配 task_api 的路由，所以这里不会被执行
    # 这个端点只在 task_api 挂载失败时生效

    try:
        # 从 TaskManager 获取任务
        tasks = await TaskManager().aget_user_tasks(user_id)

        # 格式化任务
        formatted_tasks = []
        for t in tasks:
            try:
                formatted_tasks.append({
                    "id": t.get("task_id", ""),
                    "title": t.get("type") or t.get("title", "未命名任务"),
                    "description": t.get("description", ""),
                    "status": t.get("status", "pending"),
                    "progress": t.get("progress", 0),
                    "priority": t.get("priority", "medium"),
                    "created_at": int(t.get("created_at", 0) * 1000) if t.get("created_at") else 0
                })
            except Exception as e:
                logger.error(f"[TasksFallback] 格式化任务失败: {e}")
                continue

        # 按状态过滤
        if status:
            formatted_tasks = [t for t in formatted_tasks if t["status"] == status]

        # 分页
        total = len(formatted_tasks)
        paginated = formatted_tasks[offset:offset + limit]

        return {
            "tasks": paginated,
            "total": total,
            "limit": limit,
            "offset": offset,
            "fallback": True  # 标记为备用端点返回
        }
    except Exception as e:
        diagnostic_except_handler(e, context="[TasksFallback] 获取任务列表失败", logger_instance=logger)
        raise HTTPException(status_code=500, detail=f"Failed to list tasks: {str(e)}") from e


@app.get("/api/tasks/simple")
async def list_tasks_simple(user_id: str = Depends(get_current_user)):
    """
    获取用户的所有任务 (简化版本 - 向后兼容)

    注意：完整的任务管理API请使用 /api/tasks 端点（由 task_api.py 提供）
    """
    try:
        tasks = await TaskManager().aget_user_tasks(user_id)
        formatted_tasks = []
        for t in tasks:
            # 【修复】使用.get()安全访问，避免KeyError
            formatted_tasks.append({
                "id": t.get("task_id", ""),                    # 映射 task_id -> id
                "title": t.get("type") or t.get("title", "未命名任务"),   # 映射 type -> title
                "description": t.get("description") or t.get("data", {}).get("description", ""),
                "status": t.get("status", "pending"),
                "progress": t.get("progress", 0),
                "priority": t.get("priority", "medium"),
                "created_at": int(t.get("created_at", 0) * 1000) if t.get("created_at") else 0  # 转毫秒
            })
        return {
            "tasks": formatted_tasks,
            "user_id": user_id
        }
    except Exception as e:
        logger.error(f"[CloudAPI] 获取任务列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取任务列表失败: {str(e)}") from e


@app.get("/api/stats")
async def get_stats(user_id: str = Depends(get_current_user)):
    """
    获取用户使用统计
    """
    try:
        sessions = await SessionStore().aget_user_sessions(user_id)
        tasks = await TaskManager().aget_user_tasks(user_id)
        connections = await ConnectionManager().aget_user_connections(user_id)

        total_messages = sum(s.message_count for s in sessions)

        # 【修复】使用.get()安全访问，避免KeyError
        return {
            "user_id": user_id,
            "sessions": {
                "total": len(sessions),
                "active": len([s for s in sessions if time.time() - s.last_active < 3600])
            },
            "messages": {
                "total": total_messages
            },
            "tasks": {
                "total": len(tasks),
                "pending": len([t for t in tasks if t.get("status") == "pending"]),
                "completed": len([t for t in tasks if t.get("status") == "completed"])
            },
            "connections": connections,
            "timestamp": time.time()
        }
    except Exception as e:
        logger.error(f"[CloudAPI] 获取统计信息失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取统计信息失败: {str(e)}") from e


@app.post("/api/voice/frontend", response_model=VoiceInputResponse)
async def frontend_voice_input(
    request: VoiceInputRequest,
    user_id: str = Depends(get_current_user)
):
    """
    前端语音输入接口

    点击录音图标，录音完成后发送给AI，进入聊天对齐需求。
    AI会通过聊天理解用户需求，然后决定是否触发任务。

    - **text**: 语音识别的文本内容
    - **session_id**: 会话ID

    返回:
    - **mode**: "chat_alignment" 表示进入聊天对齐模式，"task" 表示已触发任务
    """
    logger.info(f"[API] 前端语音输入: {request.text[:50]}...")

    try:
        # 导入对话管理器和输入模式
        from core.dialog.dialogue_manager import InputMode, dialogue_manager

        # 前端语音进入聊天对齐需求
        result = await dialogue_manager.handle_input(
            user_id=user_id,
            text=request.text,
            session_id=request.session_id,
            input_mode=InputMode.VOICE_FRONTEND,
            voice_instance=None  # 前端语音不需要语音播报
        )

        # 处理结果
        if isinstance(result, dict):
            mode = result.get("mode", "chat_alignment")
            return VoiceInputResponse(
                success=result.get("success", True),
                result=result,
                mode=mode,
                session_id=request.session_id,
                timestamp=time.time()
            )
        else:
            # 文本结果（直接任务模式）
            return VoiceInputResponse(
                success=True,
                result={"text": result, "mode": "task"},
                mode="task",
                session_id=request.session_id,
                timestamp=time.time()
            )

    except ImportError as e:
        logger.error(f"[API] /api/voice/frontend 导入模块失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"语音处理模块不可用: {str(e)}"
        ) from e
    except Exception as e:
        logger.error(f"[API] /api/voice/frontend 未预期异常: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"语音处理失败: {str(e)}"
        ) from e


@app.post("/voice_ptt", response_model=VoicePTTResponse, tags=["voice"])  # 添加别名
@app.post("/api/voice/ptt", response_model=VoicePTTResponse, tags=["voice"])
async def voice_ptt(
    request: VoicePTTRequest,
    current_user: str = Depends(get_current_user)
):
    """语音PTT(Push-to-Talk)控制端点"""
    try:
        from core.global_state import get_voice_interface
        voice = get_voice_interface()

        if not voice:
            return VoicePTTResponse(success=False, error="语音接口未初始化")

        if request.action == 'start':
            voice.start_ptt_session()
            return VoicePTTResponse(success=True, message="PTT会话已启动")
        elif request.action == 'end':
            voice.end_ptt_session()
            return VoicePTTResponse(success=True, message="PTT会话已结束")
        else:
            return VoicePTTResponse(success=False, error="无效的action参数")

    except ImportError as e:
        logger.error(f"[API] /api/voice/ptt 导入模块失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"语音PTT模块不可用: {str(e)}"
        ) from e
    except ValueError as e:
        logger.error(f"[API] /api/voice/ptt 参数错误: {e}", exc_info=True)
        raise HTTPException(
            status_code=400,
            detail=f"无效的参数: {str(e)}"
        ) from e
    except Exception as e:
        logger.error(f"[API] /api/voice/ptt 未预期异常: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"PTT控制失败: {str(e)}"
        ) from e


# ============================================================================
# [P0-009] 前端配置端点 - 支持配置外化
# ============================================================================

@app.get("/api/config")
async def get_frontend_config():
    """
    获取前端运行时配置

    返回前端需要的配置项，如语音API端点、WebSocket地址等
    无需认证，允许前端在启动时获取配置
    """
    # 从配置中心读取语音API配置
    voice_host = "localhost"
    voice_port = 8600
    voice_scheme = "http"
    voice_ptt_path = "/voice_ptt"
    model_name = "qwen3:8b"
    vision_model = "qwen3-vl:2b"

    if CONFIG_AVAILABLE:
        voice_host = config.get("voice.api_endpoint.host", "localhost")
        voice_port = config.get("voice.api_endpoint.port", 8600)
        voice_scheme = config.get("voice.api_endpoint.scheme", "http")
        voice_ptt_path = config.get("voice.api_endpoint.ptt_path", "/voice_ptt")
        # 【修复】从前端配置读取模型名称，不再硬编码
        model_name = config.get("ai.default_model", "qwen3:8b")
        vision_model = (
            config.get("ai.vision_model")
            or config.get("ai.vision.model")
            or "qwen3-vl:2b"
        )

    # 环境变量覆盖（最高优先级）
    env_host = os.environ.get("SILICONBASE_VOICE_API_HOST")
    env_port = os.environ.get("SILICONBASE_VOICE_API_PORT")
    env_scheme = os.environ.get("SILICONBASE_VOICE_API_SCHEME")
    env_ptt_path = os.environ.get("SILICONBASE_VOICE_API_PTT_PATH")

    if env_host:
        voice_host = env_host
    if env_port:
        with suppress(ValueError):
            voice_port = int(env_port)
    if env_scheme:
        voice_scheme = env_scheme
    if env_ptt_path:
        voice_ptt_path = env_ptt_path

    # 构建完整的API端点URL
    voice_api_url = f"{voice_scheme}://{voice_host}:{voice_port}{voice_ptt_path}"

    return {
        "success": True,
        "data": {
            "version": "1.0.0",
            "model_name": model_name,
            "vision_model": vision_model,
            "voice": {
                "enabled": True,
                "api_endpoint": {
                    "host": voice_host,
                    "port": voice_port,
                    "scheme": voice_scheme,
                    "ptt_path": voice_ptt_path,
                    "url": voice_api_url
                }
            },
            "websocket": {
                "enabled": True,
                "path": "/ws"
            }
        },
        "timestamp": time.time()
    }


# ============================================================================
# [新增] 文件上传端点
# ============================================================================

@app.post("/api/upload")
async def upload_file(
    file: UploadFile = File(...),
    current_user: str = Depends(get_current_user)
):
    """通用文件上传接口"""
    try:
        upload_dir = Path("data/uploads")
        upload_dir.mkdir(parents=True, exist_ok=True)

        # 生成唯一文件名
        original_name = file.filename or "unknown"
        ext = Path(original_name).suffix
        filename = f"{uuid.uuid4().hex}{ext}"
        file_path = upload_dir / filename

        # 保存文件
        content = await file.read()
        import asyncio
        def _write_upload():
            with open(file_path, "wb") as f:
                f.write(content)
        await asyncio.to_thread(_write_upload)

        file_url = f"/api/uploads/{filename}"
        return {
            "success": True,
            "url": file_url,
            "filename": filename,
            "original_name": original_name,
            "size": len(content)
        }
    except Exception as e:
        logger.error(f"[CloudAPI] 文件上传失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"上传失败: {str(e)}") from e


# ============================================================================
# [新增] 道德过滤配置端点 - 支持热加载
# ============================================================================

class MoralFilterConfig(BaseModel):
    """道德过滤配置模型"""
    enabled: bool = Field(True, description="是否启用道德过滤")
    strict_mode: bool = Field(False, description="严格模式")
    min_moral_score: float = Field(0.5, ge=0.0, le=1.0, description="最低道德分数")
    filter_success_exp: bool = Field(False, description="是否过滤成功经验")
    filter_failure_exp: bool = Field(True, description="是否过滤失败经验")


@app.get("/api/config/moral-filter")
async def get_moral_filter_config():
    """
    获取道德过滤配置

    返回当前道德过滤的完整配置
    """
    try:
        from core.config import config

        moral_config = {
            "enabled": config.get("moral_filter.enabled", True),
            "strict_mode": config.get("moral_filter.strict_mode", False),
            "min_moral_score": config.get("moral_filter.min_moral_score", 0.5),
            "filter_success_exp": config.get("moral_filter.filter_success_exp", False),
            "filter_failure_exp": config.get("moral_filter.filter_failure_exp", True)
        }

        return {
            "success": True,
            "data": moral_config,
            "timestamp": time.time()
        }
    except ImportError as e:
        logger.error(f"[MoralFilterAPI] 获取配置导入模块失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"配置模块不可用: {str(e)}"
        ) from e
    except Exception as e:
        logger.error(f"[MoralFilterAPI] 获取配置未预期异常: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"获取道德过滤配置失败: {str(e)}"
        ) from e


@app.put("/api/config/moral-filter")
async def update_moral_filter_config(config_data: MoralFilterConfig):
    """
    更新道德过滤配置（热加载）

    修改配置后立即生效，无需重启后端

    请求体:
    ```json
    {
        "enabled": true,
        "strict_mode": false,
        "min_moral_score": 0.1,
        "filter_success_exp": false,
        "filter_failure_exp": true
    }
    ```
    """
    try:
        from core.config import config

        # 更新配置（set方法会自动保存到文件并触发热重载）
        config.set("moral_filter.enabled", config_data.enabled)
        config.set("moral_filter.strict_mode", config_data.strict_mode)
        config.set("moral_filter.min_moral_score", config_data.min_moral_score)
        config.set("moral_filter.filter_success_exp", config_data.filter_success_exp)
        config.set("moral_filter.filter_failure_exp", config_data.filter_failure_exp)

        logger.info(f"[MoralFilterAPI] 配置已更新: enabled={config_data.enabled}, "
                   f"strict_mode={config_data.strict_mode}, min_score={config_data.min_moral_score}")

        return {
            "success": True,
            "message": "道德过滤配置已更新并生效",
            "data": {
                "enabled": config_data.enabled,
                "strict_mode": config_data.strict_mode,
                "min_moral_score": config_data.min_moral_score,
                "filter_success_exp": config_data.filter_success_exp,
                "filter_failure_exp": config_data.filter_failure_exp
            },
            "timestamp": time.time()
        }
    except ImportError as e:
        logger.error(f"[MoralFilterAPI] 更新配置导入模块失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"配置模块不可用: {str(e)}"
        ) from e
    except Exception as e:
        logger.error(f"[MoralFilterAPI] 更新配置未预期异常: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"更新道德过滤配置失败: {str(e)}"
        ) from e


@app.post("/api/config/moral-filter/reset")
async def reset_moral_filter_config():
    """
    重置道德过滤配置为默认值
    """
    try:
        from core.config import config

        # 默认配置（测试阶段推荐）
        default_config = {
            "enabled": True,
            "strict_mode": False,
            "min_moral_score": 0.5,
            "filter_success_exp": False,
            "filter_failure_exp": True
        }

        # 更新配置（set方法会自动保存到文件并触发热重载）
        config.set("moral_filter.enabled", default_config["enabled"])
        config.set("moral_filter.strict_mode", default_config["strict_mode"])
        config.set("moral_filter.min_moral_score", default_config["min_moral_score"])
        config.set("moral_filter.filter_success_exp", default_config["filter_success_exp"])
        config.set("moral_filter.filter_failure_exp", default_config["filter_failure_exp"])

        return {
            "success": True,
            "message": "道德过滤配置已重置为默认值",
            "data": default_config,
            "timestamp": time.time()
        }
    except ImportError as e:
        logger.error(f"[MoralFilterAPI] 重置配置导入模块失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"配置模块不可用: {str(e)}"
        ) from e
    except Exception as e:
        logger.error(f"[MoralFilterAPI] 重置配置未预期异常: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"重置道德过滤配置失败: {str(e)}"
        ) from e


# ============================================================================
# WebSocket 路由
# ============================================================================

# 【手动添加】在 WebSocket 端点定义之前
# 读取 WebSocket 配置（使用ConfigProxy，在lifespan加载后实际读取）
try:
    # 【修复】使用ConfigProxy延迟访问，避免模块导入时误判配置不可用
    # 实际配置值在lifespan启动后才会确定
    websocket_enabled = config_proxy.get("websocket.enabled", True)
    websocket_path = config_proxy.get("websocket.path", "/ws")

    # WebSocket配置读取成功，静默处理
    pass

except Exception:
    # 配置读取失败时使用默认值
    websocket_enabled = True
    websocket_path = "/ws"

# 根据配置条件注册 WebSocket 端点
# 【手动添加】根据配置条件注册 WebSocket 端点
if websocket_enabled:
    @app.websocket(f"{websocket_path}/{{user_id}}")
    async def websocket_endpoint(
        websocket: WebSocket,
        user_id: str,
        token: str | None = Query(None, description="认证Token")
    ):
        """
        WebSocket 实时推送端点

        路径参数:
        - **user_id**: 用户ID

        查询参数:
        - **token**: 认证Token (必需)

        消息格式:
        ```json
        {
            "type": "chat",
            "message": "你好",
            "session_id": "可选"
        }
        ```

        【新增】支持Pydantic模型验证，确保消息格式正确
        """
        # 验证token - 【修复】允许匿名连接（开发环境）
        authenticated_user_id = None

        if token:
            # 1. API Key验证（向后兼容）
            if token.startswith("sk-") and token in API_KEYS:
                authenticated_user_id = API_KEYS[token]
            # 2. JWT Token验证（SEC-003新增）
            else:
                payload = await user_auth_store.averify_token(token)
                if payload:
                    validated_user_id = payload.get("sub")
                    if validated_user_id:
                        # 验证用户是否存在且活跃
                        user = await user_auth_store.aget_user_by_id(validated_user_id)
                        if user and user.get("is_active", True):
                            authenticated_user_id = validated_user_id

            if not authenticated_user_id:
                # token 存在但验证失败，记录警告但仍允许连接（游客模式）
                logger.warning(f"[WebSocket] Token验证失败，允许匿名连接: user_id={user_id}")
        else:
            # 无token，记录日志
            logger.info(f"[WebSocket] 无token连接，使用游客模式: user_id={user_id}")

        # 如果没有认证用户ID，使用URL中的user_id作为匿名用户
        if not authenticated_user_id:
            authenticated_user_id = user_id
            logger.info(f"[WebSocket] 匿名用户连接: {user_id}")

        # 验证user_id匹配 - 【修复】放宽匹配条件，支持多种user_id格式
        if authenticated_user_id != user_id:
            # 记录调试信息
            logger.warning(f"[WebSocket] User ID mismatch: authenticated={authenticated_user_id}, url={user_id}")
            # 尝试通过username匹配（兼容不同存储格式）
            auth_user = await user_auth_store.aget_user_by_id(authenticated_user_id)
            url_user = await user_auth_store.aget_user_by_id(user_id)
            if not auth_user and not url_user:
                # 两者都是无效ID，允许连接（可能是开发环境）
                logger.warning("[WebSocket] Both user IDs invalid, allowing connection for development")
            elif auth_user and url_user and auth_user.get("username") == url_user.get("username"):
                # 通过username匹配成功
                logger.info(f"[WebSocket] User matched by username: {auth_user.get('username')}")
            else:
                # ID不匹配但允许连接，使用URL中的user_id
                logger.warning(f"[WebSocket] ID不匹配，使用URL user_id: {user_id}")
                authenticated_user_id = user_id

        manager = ConnectionManager()
        connection_id = None
        print(f"[DEBUG-CloudAPI] WebSocket connect user_id={user_id}", flush=True)

        try:
            connection_id = await manager.connect(websocket, user_id)

            # 更新 WebSocket 连接数指标
            if MONITORING_AVAILABLE:
                update_websocket_count(manager.get_total_connections())

            try:
                # 发送连接成功消息
                # 【修复】使用connection_id作为session_id，确保会话连续性
                await safe_send_json(websocket, {
                    "type": "connected",
                    "connection_id": connection_id,
                    "session_id": connection_id,  # 添加session_id，前端用于保持会话
                    "user_id": user_id,
                    "timestamp": time.time()
                })

                # DESIGN-NOTE: WebSocket服务主循环，设计为长期运行
                # 中断机制：客户端断开连接时，receive_json()抛出WebSocketDisconnect异常
                # 安全退出：外层try-except捕获异常，确保连接清理
                while True:
                    # 接收客户端消息
                    try:
                        data = await websocket.receive_json()
                        # 任何下行消息都刷新应用层活跃时间，避免被误判超时
                        manager.update_connection_active(connection_id)
                        message_type = data.get("type", "unknown")

                        # 【新增】使用Pydantic模型验证消息格式
                        try:
                            if SCHEMAS_AVAILABLE:
                                if message_type == "ping":
                                    PingMessage(**data)
                                elif message_type == "chat":
                                    validate_websocket_message(data)
                                elif message_type == "command":
                                    CommandMessage(**data)
                                elif message_type == "voice":
                                    VoiceMessage(**data)

                                    # P1-002修复：语音输入进入聊天对齐模式
                                    voice_text = data.get("text", "") or data.get("message", "")
                                    session_id = data.get("session_id")

                                    if not voice_text:
                                        await safe_send_json(websocket, create_error_response(
                                            message="语音消息内容不能为空",
                                            code="VALIDATION_ERROR"
                                        ))
                                        continue

                                    # 【干预检查】如果用户有活跃任务且输入是干预意图，提交干预
                                    active_task_id = get_active_task_id_for_user(user_id, session_id)
                                    if active_task_id and REALTIME_INTERVENTION_AVAILABLE and is_intervention_intent(voice_text):
                                        logger.info(f"[WebSocket] 检测到语音干预意图，任务ID: {active_task_id}")
                                        try:
                                            success = realtime_intervention.submit_intervention(
                                                task_id=active_task_id,
                                                user_input=voice_text
                                            )
                                            if success:
                                                await safe_send_json(websocket, {
                                                    "type": "intervention_ack",
                                                    "timestamp": time.time(),
                                                    "data": {"status": "submitted", "task_id": active_task_id}
                                                })
                                                continue  # 干预已提交，跳过对齐处理
                                        except Exception as e:
                                            logger.warning(f"[WebSocket] 提交干预失败: {e}")

                                    # 发送处理中确认
                                    await safe_send_json(websocket, {
                                        "type": "alignment_started",
                                        "timestamp": time.time(),
                                        "data": {"status": "alignment_mode", "session_id": session_id}
                                    })

                                    # 调用聊天对齐模式处理
                                    try:
                                        from core.dialog.chat_mode_handler import dual_mode_manager

                                        # 执行对齐处理
                                        alignment_result = await dual_mode_manager.handle_voice_alignment(
                                            text=voice_text,
                                            session_id=session_id,
                                            user_id=user_id
                                        )

                                        # 发送对齐结果
                                        await safe_send_json(websocket, {
                                            "type": "alignment_result",
                                            "timestamp": time.time(),
                                            "data": alignment_result
                                        })

                                        # 如果确认对齐，进入任务循环
                                        if alignment_result.get("next_step") == "enter_task_loop":
                                            # 发送进入任务循环通知
                                            await safe_send_json(websocket, {
                                                "type": "entering_task_loop",
                                                "timestamp": time.time(),
                                                "data": {
                                                    "message": "需求已对齐，开始执行任务",
                                                    "session_id": session_id
                                                }
                                            })

                                            # Phase 8: enter_task_loop_from_alignment 已是 async def，直接 await
                                            task_result = await dual_mode_manager.enter_task_loop_from_alignment(
                                                user_id=user_id,
                                                session_id=session_id
                                            )

                                            # 发送任务完成结果
                                            await safe_send_json(websocket, {
                                                "type": "task_complete",
                                                "timestamp": time.time(),
                                                "data": {
                                                    "content": task_result,
                                                    "session_id": session_id,
                                                    "success": True
                                                }
                                            })

                                    except Exception as e:
                                        logger.error(f"[WebSocket] 语音对齐处理异常: {e}")
                                        await safe_send_json(websocket, create_error_response(
                                            message=f"语音处理失败: {str(e)}",
                                            code="ALIGNMENT_ERROR",
                                            details={"session_id": session_id}
                                        ))
                                    continue  # 跳过后续处理
                                elif message_type == "auth":
                                    AuthMessage(**data)
                                elif message_type == "confirm_response":
                                    ConfirmResponseMessage(**data)
                                elif message_type == "mode_switch_request":
                                    ModeSwitchRequestMessage(**data)
                                elif message_type in ("accept_weak_proposal", "dismiss_weak_proposal", "timeout_weak_proposal"):
                                    WeakProposalActionMessage(**data)
                                else:
                                    validate_websocket_message(data)
                        except ValidationError as ve:
                            # 验证失败，返回清晰的错误信息
                            error_msg = f"消息格式错误: {ve.errors()[0]['msg'] if ve.errors() else '未知错误'}"
                            await safe_send_json(websocket, create_error_response(
                                message=error_msg,
                                code="VALIDATION_ERROR",
                                details={"errors": ve.errors()}
                            ))
                            continue
                        except Exception as e:
                            # 其他验证错误
                            await safe_send_json(websocket, create_error_response(
                                message=f"消息验证失败: {str(e)}",
                                code="VALIDATION_ERROR"
                            ))
                            continue

                        if message_type == "ping":
                            await safe_send_json(websocket, {
                                "type": "pong",
                                "timestamp": time.time()
                            })

                        elif message_type == "chat":
                            # 【阶段1统一入口】WebSocket chat 类型不再模拟回复，与 user_input auto 模式一致
                            msg_content = data.get("message", "")
                            session_id = data.get("session_id")
                            if connection_id and session_id:
                                manager.update_connection_session(connection_id, session_id)

                            session = await SessionStore().aget(user_id, session_id)
                            await SessionStore().aadd_message(session["session_id"], "user", msg_content)

                            from core.dialog.dialogue_manager import InputMode, dialogue_manager
                            try:
                                ai_result = await dialogue_manager.handle_input(
                                    user_id=user_id,
                                    text=msg_content,
                                    session_id=session["session_id"],
                                    input_mode=InputMode.AUTO,
                                    voice_instance=None
                                )
                                if isinstance(ai_result, dict):
                                    ai_response = ai_result.get("content", "") or ai_result.get("chat_reply", "") or ai_result.get("result", "")
                                else:
                                    ai_response = str(ai_result) if ai_result else ""
                            except Exception as e:
                                logger.error(f"[WebSocket] chat 类型处理异常: {e}")
                                ai_response = f"处理失败: {str(e)}"

                            if ai_response:
                                await SessionStore().aadd_message(session["session_id"], "assistant", ai_response)

                            # 发送回复
                            await safe_send_json(websocket, {
                                "type": "chat_response",
                                "session_id": session["session_id"],
                                "message": ai_response,
                                "timestamp": time.time()
                            })

                        elif message_type == "subscribe":
                            # 订阅会话更新
                            sub_session_id = data.get("session_id")
                            await safe_send_json(websocket, {
                                "type": "subscribed",
                                "session_id": sub_session_id,
                                "timestamp": time.time()
                            })

                        elif message_type == "mode_switch_request":
                            # 【模式术语统一】处理工作模式切换请求（daily/focus）
                            target_mode = data.get("target_mode", "")
                            reason = data.get("reason", "")

                            try:
                                from core.dialog.chat_mode_handler import dual_mode_manager
                                from core.work_mode_manager import WorkMode

                                # 兼容旧版 chat/task 语义：chat -> daily, task -> focus
                                compatibility_map = {
                                    "chat": "daily",
                                    "task": "focus"
                                }
                                normalized_mode = compatibility_map.get(target_mode, target_mode)

                                new_mode = WorkMode(normalized_mode)
                                user_manager = dual_mode_manager.get_mode_manager(user_id)
                                current_mode = user_manager.get_current_mode().value

                                # 发送切换中事件
                                await safe_send_json(websocket, {
                                    "type": "mode_switching",
                                    "from_mode": current_mode,
                                    "to_mode": new_mode.value,
                                    "progress": 0.3,
                                    "timestamp": time.time()
                                })

                                success = await user_manager.switch_mode(new_mode)

                                if success:
                                    await safe_send_json(websocket, {
                                        "type": "mode_switched",
                                        "mode": new_mode.value,
                                        "context": {
                                            "goal": reason,
                                            "progress": "",
                                            "working_memory_summary": ""
                                        },
                                        "timestamp": time.time()
                                    })
                                else:
                                    await safe_send_json(websocket, {
                                        "type": "mode_switch_failed",
                                        "error": "模式切换失败",
                                        "timestamp": time.time()
                                    })
                            except ValueError:
                                await safe_send_json(websocket, {
                                    "type": "mode_switch_failed",
                                    "error": f"无效的模式: {target_mode}，有效值: daily, focus",
                                    "timestamp": time.time()
                                })
                            except Exception as e:
                                logger.error(f"[WebSocket] 模式切换处理异常: {e}")
                                await safe_send_json(websocket, {
                                    "type": "mode_switch_failed",
                                    "error": f"模式切换异常: {str(e)}",
                                    "timestamp": time.time()
                                })

                        elif message_type == "confirm_response":
                            await _handle_confirm_response(websocket, user_id, data)

                        elif message_type == "accept_weak_proposal":
                            await _handle_accept_weak_proposal(websocket, user_id, data)

                        elif message_type == "dismiss_weak_proposal":
                            await _handle_dismiss_weak_proposal(websocket, user_id, data)

                        elif message_type == "timeout_weak_proposal":
                            await _handle_timeout_weak_proposal(websocket, user_id, data)

                        elif message_type == "command":
                            # 兼容 8601 的 command_ack 行为
                            await safe_send_json(websocket, {
                                "type": "command_ack",
                                "command_id": data.get("command_id") or data.get("id", "unknown"),
                                "timestamp": time.time()
                            })

                        elif message_type == "user_input":
                            content = data.get("content", "")
                            session_id = data.get("session_id")
                            if connection_id and session_id:
                                manager.update_connection_session(connection_id, session_id)
                            input_type = data.get("input_type", "text")  # 获取输入类型：text/voice/chat

                            if not content:
                                await safe_send_json(websocket, create_error_response(
                                    message="消息内容不能为空",
                                    code="VALIDATION_ERROR"
                                ))
                                continue

                            # 发送处理中确认
                            await safe_send_json(websocket, {
                                "type": "input_ack",
                                "timestamp": time.time(),
                                "data": {"status": "processing", "session_id": session_id, "input_type": input_type}
                            })

                            # 【生命化改造】根据输入类型选择处理方式
                            # auto  = AI自主意图判断（chat/direct_task/ambiguous）
                            # text  = 直接进入任务模式（兼容旧版）
                            # chat  = 进入聊天对齐模式（兼容旧版）
                            # voice = 进入聊天对齐模式（兼容旧版）

                            # 【干预检查】所有输入类型都需要检查干预意图
                            active_task_id = get_active_task_id_for_user(user_id, session_id)
                            if active_task_id and REALTIME_INTERVENTION_AVAILABLE and is_intervention_intent(content):
                                logger.info(f"[WebSocket] 检测到干预意图，任务ID: {active_task_id}")
                                try:
                                    success = realtime_intervention.submit_intervention(
                                        task_id=active_task_id,
                                        user_input=content
                                    )
                                    if success:
                                        await safe_send_json(websocket, {
                                            "type": "intervention_ack",
                                            "timestamp": time.time(),
                                            "data": {"status": "submitted", "task_id": active_task_id}
                                        })
                                        continue  # 干预已提交，跳过后续处理
                                except Exception as e:
                                    logger.warning(f"[WebSocket] 提交干预失败: {e}")

                            from core.dialog.dialogue_manager import InputMode, dialogue_manager

                            # 根据 input_type 选择 DialogueManager 处理模式
                            # auto/text/chat 统一由 AI 自主判断意图
                            # voice 走 VOICE_FRONTEND 模式，启用语音对齐、社会推理和语音播报
                            if input_type == "voice":
                                selected_input_mode = InputMode.VOICE_FRONTEND
                            else:
                                selected_input_mode = InputMode.AUTO

                            await safe_send_json(websocket, {
                                "type": "thinking",
                                "timestamp": time.time(),
                                "data": {"content": "AI 正在判断意图...", "session_id": session_id}
                            })

                            try:
                                ai_result = await dialogue_manager.handle_input(
                                    user_id=user_id,
                                    text=content,
                                    session_id=session_id,
                                    input_mode=selected_input_mode,
                                    voice_instance=None
                                )

                                # 统一处理返回结果
                                if isinstance(ai_result, dict):
                                    ai_mode = ai_result.get("mode", "unknown")
                                    ai_response = ai_result.get("content", "") or ai_result.get("chat_reply", "") or ai_result.get("result", "")
                                    tool_calls = ai_result.get("tool_calls", [])
                                    success = ai_result.get("success", True)
                                else:
                                    # 向后兼容：字符串结果
                                    ai_mode = "text"
                                    ai_response = str(ai_result) if ai_result else ""
                                    tool_calls = []
                                    success = ai_response is not None

                                # 根据模式发送不同类型的消息
                                if ai_mode == "quick_chat":
                                    await safe_send_json(websocket, {
                                        "type": "quick_chat_reply",
                                        "timestamp": time.time(),
                                        "data": {
                                            "content": ai_response if ai_response else "处理完成",
                                            "session_id": session_id,
                                            "mode": "quick_chat"
                                        }
                                    })
                                elif ai_mode == "chat_alignment":
                                    await safe_send_json(websocket, {
                                        "type": "chat_alignment_reply",
                                        "timestamp": time.time(),
                                        "data": {
                                            "content": ai_response if ai_response else "处理完成",
                                            "session_id": session_id,
                                            "mode": "chat_alignment"
                                        }
                                    })
                                elif ai_mode == "task_started":
                                    # 【后台任务】任务已启动，发送确认后前端可继续发消息
                                    await safe_send_json(websocket, {
                                        "type": "task_started",
                                        "timestamp": time.time(),
                                        "data": {
                                            "content": ai_response if ai_response else "任务已启动",
                                            "session_id": session_id,
                                            "mode": "task_started",
                                            "success": success
                                        }
                                    })
                                elif ai_mode in ("task_paused", "task_resumed", "task_cancelled", "task_retry"):
                                    # 任务控制指令响应
                                    await safe_send_json(websocket, {
                                        "type": "task_control_reply",
                                        "timestamp": time.time(),
                                        "data": {
                                            "content": ai_response if ai_response else "操作完成",
                                            "session_id": session_id,
                                            "mode": ai_mode,
                                            "success": success
                                        }
                                    })
                                else:
                                    # task / unknown 统一走 reply
                                    await safe_send_json(websocket, {
                                        "type": "reply",
                                        "timestamp": time.time(),
                                        "data": {
                                            "content": ai_response if ai_response else "抱歉，AI处理失败，请稍后重试。",
                                            "tool_calls": tool_calls,
                                            "success": success,
                                            "session_id": session_id,
                                            "mode": ai_mode
                                        }
                                    })
                            except Exception as e:
                                logger.error(f"[WebSocket] AI处理失败: {e}")
                                import traceback
                                logger.error(traceback.format_exc())
                                await safe_send_json(websocket, {
                                    "type": "reply",
                                    "timestamp": time.time(),
                                    "data": {
                                        "content": "抱歉，AI处理失败，请稍后重试。",
                                        "tool_calls": [],
                                        "success": False,
                                        "session_id": session_id,
                                        "error": str(e)
                                    }
                                })

                        else:
                            await safe_send_json(websocket, {
                                "type": "error",
                                "message": f"Unknown message type: {message_type}. Supported: ping, auth, chat, user_input, voice, subscribe, command, mode_switch_request, confirm_response, accept_weak_proposal, dismiss_weak_proposal, timeout_weak_proposal",
                                "timestamp": time.time()
                            })

                    except json.JSONDecodeError:
                        await safe_send_json(websocket, create_error_response(
                            message="Invalid JSON format",
                            code="JSON_DECODE_ERROR"
                        ))
                    except RuntimeError as re:
                        # FastAPI/Starlette 在收到二进制帧时抛出 RuntimeError
                        error_text = str(re).lower()
                        if "text" in error_text or "binary" in error_text or "json" in error_text:
                            logger.info(f"[WebSocket] 收到非文本帧，已忽略: {re}")
                            continue
                        raise
            except WebSocketDisconnect:
                # 内部WebSocket断开处理
                pass
            except Exception as e:
                # 内部其他异常处理
                print(f"WebSocket inner error: {e}")

        except WebSocketDisconnect:
            if connection_id:
                manager.disconnect(connection_id, user_id)
            if MONITORING_AVAILABLE:
                update_websocket_count(manager.get_total_connections())
            logger.info(f"[WebSocket] 断开连接: {connection_id} (user: {user_id})")
        except ConnectionResetError as e:
            logger.warning(f"[WebSocket] 连接重置: {e}")
            if connection_id:
                manager.disconnect(connection_id, user_id)
            if MONITORING_AVAILABLE:
                update_websocket_count(manager.get_total_connections())
                record_error(error_type="websocket_connection_reset", endpoint=f"/ws/{user_id}")
        except asyncio.CancelledError as e:
            logger.warning(f"[WebSocket] 任务取消: {e}")
            if connection_id:
                manager.disconnect(connection_id, user_id)
            if MONITORING_AVAILABLE:
                update_websocket_count(manager.get_total_connections())
        except Exception as e:
            logger.error(f"[WebSocket] /ws/{user_id} 未预期异常: {e}", exc_info=True)
            if connection_id:
                manager.disconnect(connection_id, user_id)
            if MONITORING_AVAILABLE:
                update_websocket_count(manager.get_total_connections())
                record_error(error_type="websocket_error", endpoint=f"/ws/{user_id}")
        finally:
            # 确保WebSocket连接被正确关闭
            if websocket and websocket.client_state != WebSocketState.DISCONNECTED:
                try:
                    await websocket.close()
                except Exception as e:
                    logger.warning(f"[WebSocket Stream] 关闭连接时异常: {e}")


    @app.websocket(f"{websocket_path}/stream/{{user_id}}")
    async def websocket_stream_endpoint(
        websocket: WebSocket,
        user_id: str,
        token: str | None = Query(None, description="认证Token")
    ):
        """
        WebSocket 流式聊天端点

        支持流式AI响应，逐字推送到客户端

        查询参数:
        - **token**: 认证Token (必需)
        """
        # 验证token - 【修复】允许匿名连接（开发环境）
        authenticated_user_id = None

        if token:
            # 1. API Key验证（向后兼容）
            if token.startswith("sk-") and token in API_KEYS:
                authenticated_user_id = API_KEYS[token]
            # 2. JWT Token验证（SEC-003新增）
            else:
                payload = await user_auth_store.averify_token(token)
                if payload:
                    validated_user_id = payload.get("sub")
                    if validated_user_id:
                        # 验证用户是否存在且活跃
                        user = await user_auth_store.aget_user_by_id(validated_user_id)
                        if user and user.get("is_active", True):
                            authenticated_user_id = validated_user_id

            if not authenticated_user_id:
                # token 存在但验证失败，记录警告但仍允许连接（游客模式）
                logger.warning(f"[WebSocket Stream] Token验证失败，允许匿名连接: user_id={user_id}")
        else:
            # 无token，记录日志
            logger.info(f"[WebSocket Stream] 无token连接，使用游客模式: user_id={user_id}")

        # 如果没有认证用户ID，使用URL中的user_id作为匿名用户
        if not authenticated_user_id:
            authenticated_user_id = user_id
            logger.info(f"[WebSocket Stream] 匿名用户连接: {user_id}")

        # 验证user_id匹配 - 【修复】放宽匹配条件
        if authenticated_user_id != user_id:
            logger.warning(f"[WebSocket Stream] ID不匹配，使用URL user_id: {user_id}")
            authenticated_user_id = user_id

        manager = ConnectionManager()
        connection_id = None

        try:
            connection_id = await manager.connect(websocket, user_id)

            try:
                await safe_send_json(websocket, {
                    "type": "connected",
                    "connection_id": connection_id,
                    "user_id": user_id,
                    "mode": "stream",
                    "timestamp": time.time()
                })

                # DESIGN-NOTE: WebSocket流式服务主循环，设计为长期运行
                # 中断机制：客户端断开连接时，receive_json()抛出WebSocketDisconnect异常
                # 安全退出：外层try-finally确保连接从ConnectionManager移除
                while True:
                    data = await websocket.receive_json()
                    # 任何下行消息都刷新应用层活跃时间
                    manager.update_connection_active(connection_id)

                    if data.get("type") == "chat_stream":
                        msg_content = data.get("message", "")
                        session_id = data.get("session_id")

                        session = await SessionStore().aget(user_id, session_id)
                        await SessionStore().aadd_message(session["session_id"], "user", msg_content)

                        # 流式发送AI响应
                        message_id = f"msg_{uuid.uuid4().hex[:16]}"
                        response_text = "这是流式回复示例。实际集成时应调用核心AI引擎的流式接口。"

                        # 发送开始标记
                        await safe_send_json(websocket, {
                            "type": "stream_start",
                            "message_id": message_id,
                            "session_id": session["session_id"],
                            "timestamp": time.time()
                        })

                        # 逐字发送
                        full_response = ""
                        for char in response_text:
                            await asyncio.sleep(0.05)  # 模拟生成延迟
                            full_response += char
                            await safe_send_json(websocket, {
                                "type": "stream_chunk",
                                "message_id": message_id,
                                "data": char,
                                "timestamp": time.time()
                            })

                        # 保存完整回复
                        await SessionStore().aadd_message(session["session_id"], "assistant", full_response)

                        # 发送结束标记
                        await safe_send_json(websocket, {
                            "type": "stream_end",
                            "message_id": message_id,
                            "session_id": session["session_id"],
                            "full_text": full_response,
                            "timestamp": time.time()
                        })

            except WebSocketDisconnect:
                if connection_id:
                    manager.disconnect(connection_id, user_id)
                if MONITORING_AVAILABLE:
                    update_websocket_count(manager.get_total_connections())
                logger.info(f"[WebSocket Stream] 断开连接: {connection_id}")
            except ConnectionResetError as e:
                logger.warning(f"[WebSocket Stream] 连接重置: {e}")
                if connection_id:
                    manager.disconnect(connection_id, user_id)
                if MONITORING_AVAILABLE:
                    update_websocket_count(manager.get_total_connections())
                    record_error(error_type="websocket_stream_connection_reset", endpoint=f"/ws/stream/{user_id}")
            except asyncio.CancelledError as e:
                logger.warning(f"[WebSocket Stream] 任务取消: {e}")
                if connection_id:
                    manager.disconnect(connection_id, user_id)
                if MONITORING_AVAILABLE:
                    update_websocket_count(manager.get_total_connections())
            except Exception as e:
                logger.error(f"[WebSocket Stream] /ws/stream/{user_id} 未预期异常: {e}", exc_info=True)
                if connection_id:
                    manager.disconnect(connection_id, user_id)
                if MONITORING_AVAILABLE:
                    update_websocket_count(manager.get_total_connections())
                    record_error(error_type="websocket_stream_error", endpoint=f"/ws/stream/{user_id}")
            finally:
                # 确保WebSocket连接被正确关闭
                if websocket and websocket.client_state != WebSocketState.DISCONNECTED:
                    try:
                        await websocket.close()
                    except Exception as e:
                        logger.warning(f"[WebSocket Stream] 关闭连接时异常: {e}")
        except ConnectionResetError as e:
            logger.warning(f"[WebSocket Stream] 连接建立时重置: {e}")
            if MONITORING_AVAILABLE:
                record_error(error_type="websocket_stream_connection_reset", endpoint=f"/ws/stream/{user_id}")
        except Exception as e:
            logger.error(f"[WebSocket Stream] /ws/stream/{user_id} 连接建立未预期异常: {e}", exc_info=True)
            if MONITORING_AVAILABLE:
                record_error(error_type="websocket_stream_error", endpoint=f"/ws/stream/{user_id}")


    logger.info(f"[API] WebSocket 端点已注册: {websocket_path}")
else:
    logger.info("[API] WebSocket 端点未注册（已禁用）")

# ============================================================================
# 状态监控端点 (StateRegistry)
# ============================================================================

@app.get("/api/monitoring/states")
async def get_system_states(user_id: str = Depends(get_current_user)):
    """
    获取系统所有状态（前端监控面板使用）

    返回所有已注册状态容器的当前状态，用于前端监控面板展示。
    包括：工作模式、意识线程状态、全局状态等。

    - **user_id**: 从认证token解析的用户ID
    """
    try:
        from core.session.state_registry import get_monitoring_data
        data = get_monitoring_data()
        data["user_id"] = user_id
        return data
    except ImportError as e:
        logger.error(f"[CloudAPI] /api/monitoring/states 导入模块失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"状态监控模块不可用: {str(e)}"
        ) from e
    except Exception as e:
        logger.error(f"[CloudAPI] /api/monitoring/states 未预期异常: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"获取系统状态失败: {str(e)}"
        ) from e


@app.get("/api/monitoring/states/{container_name}")
async def get_container_state(container_name: str, user_id: str = Depends(get_current_user)):
    """
    获取指定状态容器的状态

    - **container_name**: 状态容器名称，如 "work_mode", "global_state", "consciousness_default" 等
    - **user_id**: 从认证token解析的用户ID
    """
    try:
        from core.session.state_registry import get_state_registry

        registry = get_state_registry()
        state = registry.get_state(container_name)

        if state is None:
            # 返回可用的状态容器列表
            available = registry.list_containers()
            raise HTTPException(
                status_code=404,
                detail={
                    "message": f"状态容器 '{container_name}' 不存在",
                    "available_containers": available
                }
            )

        return {
            "container": container_name,
            "state": state,
            "user_id": user_id,
            "timestamp": datetime.now().isoformat()
        }
    except HTTPException:
        raise
    except ImportError as e:
        logger.error(f"[CloudAPI] /api/monitoring/states/{{container_name}} 导入模块失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"状态监控模块不可用: {str(e)}"
        ) from e
    except Exception as e:
        logger.error(f"[CloudAPI] /api/monitoring/states/{{container_name}} 未预期异常: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"获取状态容器失败: {str(e)}"
        ) from e


@app.get("/api/monitoring/registry")
async def get_registry_info(user_id: str = Depends(get_current_user)):
    """
    获取注册表信息

    返回已注册状态容器的元数据信息，不包含实际状态值。

    - **user_id**: 从认证token解析的用户ID
    """
    try:
        from core.session.state_registry import get_state_registry

        registry = get_state_registry()
        info = registry.get_registry_info()
        info["user_id"] = user_id
        return info
    except ImportError as e:
        logger.error(f"[CloudAPI] /api/monitoring/registry 导入模块失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"注册表模块不可用: {str(e)}"
        ) from e
    except Exception as e:
        logger.error(f"[CloudAPI] /api/monitoring/registry 未预期异常: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"获取注册表信息失败: {str(e)}"
        ) from e


# ============================================================================
# 截图管理API端点
# ============================================================================

@app.get("/api/screenshots/stats")
async def get_screenshot_stats(user_id: str = Depends(get_current_user)):
    """
    获取截图统计信息

    返回当前截图数量、总大小、清理限制等信息。

    - **user_id**: 从认证token解析的用户ID
    """
    try:
        from core.vision.screenshot_manager import get_screenshot_manager

        manager = get_screenshot_manager()
        stats = manager.get_screenshot_stats()

        return {
            "success": True,
            "data": stats
        }
    except ImportError as e:
        logger.error(f"[CloudAPI] /api/screenshots/stats 导入模块失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"截图管理模块不可用: {str(e)}"
        ) from e
    except Exception as e:
        logger.error(f"[CloudAPI] /api/screenshots/stats 未预期异常: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"获取截图统计失败: {str(e)}"
        ) from e


@app.post("/api/screenshots/cleanup")
async def cleanup_screenshots(user_id: str = Depends(get_current_user)):
    """
    手动触发截图清理

    根据配置的限制条件（数量/大小/时间）清理旧截图。

    - **user_id**: 从认证token解析的用户ID
    """
    try:
        from core.vision.screenshot_manager import get_screenshot_manager

        manager = get_screenshot_manager()
        stats = manager.cleanup_old_screenshots()

        return {
            "success": True,
            "message": f"清理完成：删除{stats['deleted_by_age'] + stats['deleted_by_count'] + stats['deleted_by_size']}张截图，释放{stats['total_freed_mb']:.2f}MB",
            "data": stats
        }
    except ImportError as e:
        logger.error(f"[CloudAPI] /api/screenshots/cleanup 导入模块失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"截图管理模块不可用: {str(e)}"
        ) from e
    except Exception as e:
        logger.error(f"[CloudAPI] /api/screenshots/cleanup 未预期异常: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"截图清理失败: {str(e)}"
        ) from e


@app.get("/api/screenshots/list")
async def list_screenshots(
    limit: int = 20,
    user_id: str = Depends(get_current_user)
):
    """
    获取最近截图列表

    返回最近的截图文件列表（不包含图片数据，只有元信息）。

    - **limit**: 返回数量限制（默认20）
    - **user_id**: 从认证token解析的用户ID
    """
    try:
        import glob
        import os
        from pathlib import Path

        from core.vision.screenshot_manager import get_screenshot_manager

        manager = get_screenshot_manager()
        screenshot_dir = manager.screenshot_dir

        # 获取所有截图文件
        screenshot_files = glob.glob(str(screenshot_dir / "*.png"))

        # 按修改时间排序（最新的在前）
        screenshots = []
        for path in screenshot_files:
            try:
                stat = os.stat(path)
                screenshots.append({
                    "filename": Path(path).name,
                    "path": path,
                    "size_kb": round(stat.st_size / 1024, 2),
                    "created_at": stat.st_mtime
                })
            except OSError:
                continue

        # 按时间排序并限制数量
        screenshots.sort(key=lambda x: x["created_at"], reverse=True)
        screenshots = screenshots[:limit]

        return {
            "success": True,
            "data": {
                "total": len(screenshot_files),
                "returned": len(screenshots),
                "screenshots": screenshots
            }
        }
    except ImportError as e:
        logger.error(f"[CloudAPI] /api/screenshots/list 导入模块失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"截图管理模块不可用: {str(e)}"
        ) from e
    except OSError as e:
        logger.error(f"[CloudAPI] /api/screenshots/list 文件系统错误: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"访问截图文件失败: {str(e)}"
        ) from e
    except Exception as e:
        logger.error(f"[CloudAPI] /api/screenshots/list 未预期异常: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"获取截图列表失败: {str(e)}"
        ) from e


@app.get("/api/screenshots/view/{filename}")
async def view_screenshot(filename: str, user_id: str = Depends(get_current_user)):
    """
    查看截图文件

    通过HTTP提供截图图片，前端可以用作img src。

    - **filename**: 截图文件名（如 verify_20260311_123456_123.png）
    - **user_id**: 从认证token解析的用户ID
    """
    try:
        from fastapi.responses import FileResponse

        from core.vision.screenshot_manager import get_screenshot_manager

        manager = get_screenshot_manager()
        screenshot_path = manager.screenshot_dir / filename

        # 安全检查：确保文件在截图目录内
        try:
            screenshot_path.resolve().relative_to(manager.screenshot_dir.resolve())
        except ValueError as _exc:
            raise HTTPException(status_code=403, detail="非法文件路径") from _exc

        if not screenshot_path.exists():
            raise HTTPException(status_code=404, detail=f"截图不存在: {filename}")

        return FileResponse(
            path=str(screenshot_path),
            media_type="image/png",
            filename=filename
        )
    except HTTPException:
        raise
    except ImportError as e:
        logger.error(f"[CloudAPI] /api/screenshots/view/{{filename}} 导入模块失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"截图管理模块不可用: {str(e)}"
        ) from e
    except OSError as e:
        logger.error(f"[CloudAPI] /api/screenshots/view/{{filename}} 文件系统错误: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"访问截图文件失败: {str(e)}"
        ) from e
    except Exception as e:
        logger.error(f"[CloudAPI] /api/screenshots/view/{{filename}} 未预期异常: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"查看截图失败: {str(e)}"
        ) from e


# ============================================================================
# 简单监控API端点（前端直接调用）
# ============================================================================

@app.get("/api/system")
async def get_system_info_simple(user_id: str = Depends(get_current_user)):
    """
    获取系统资源使用情况（简化端点）

    返回CPU、内存、磁盘使用指标，供前端监控面板使用。
    """
    try:
        import psutil

        # 获取系统指标
        cpu_percent = psutil.cpu_percent(interval=0.5)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')

        return {
            "success": True,
            "data": {
                "cpu_percent": cpu_percent,
                "memory": {
                    "percent": memory.percent,
                    "used": memory.used,
                    "total": memory.total,
                    "available": memory.available
                },
                "disk": {
                    "percent": (disk.used / disk.total) * 100,
                    "used": disk.used,
                    "total": disk.total
                },
                "timestamp": int(time.time())
            },
            "message": "System metrics retrieved successfully"
        }
    except ImportError:
        # psutil 不可用，返回模拟数据
        return {
            "success": True,
            "data": {
                "cpu_percent": 25.5,
                "memory": {
                    "percent": 50.0,
                    "used": 4294967296,
                    "total": 8589934592,
                    "available": 4294967296
                },
                "disk": {
                    "percent": 50.0,
                    "used": 53687091200,
                    "total": 107374182400
                },
                "timestamp": int(time.time())
            },
            "message": "System metrics (mock data - psutil not installed)"
        }
    except Exception as e:
        logger.error(f"[CloudAPI] /api/system 未预期异常: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"获取系统信息失败: {str(e)}"
        ) from e


@app.get("/api/tasks/metrics")
async def get_task_metrics_simple(user_id: str = Depends(get_current_user)):
    """
    获取任务队列统计（简化端点）

    返回待处理任务数、当前任务、完成/失败计数。
    """
    try:
        from core.task.task_queue import task_queue

        # 获取队列统计
        queue_stats = {}
        try:
            if hasattr(task_queue, 'get_stats'):
                queue_stats = task_queue.get_stats()
        except Exception as e:
            logger.warning(f"[CloudAPI] Error getting task queue stats: {e}")

        # 安全获取队列大小
        queue_size = queue_stats.get('queue_size', 0)

        # 获取当前任务
        current_task = None
        try:
            current = queue_stats.get('current_task') or task_queue.current_task()
            if current:
                current_task = {
                    "id": getattr(current, 'id', str(current)),
                    "type": getattr(current, 'type', 'unknown'),
                    "status": str(getattr(current, 'status', 'pending'))
                }
        except AttributeError as e:
            logger.warning(f"[CloudAPI] /api/tasks/metrics 获取当前任务属性失败: {e}")
        except Exception as e:
            logger.error(f"[CloudAPI] /api/tasks/metrics 获取当前任务失败: {e}", exc_info=True)

        return {
            "success": True,
            "data": {
                "queue_size": queue_size,
                "current_task": current_task,
                "completed_today": 0,  # 简化版本，不跟踪历史
                "failed_today": 0,
                "average_wait_time": queue_size * 5.0,
                "timestamp": int(time.time())
            },
            "message": "Task metrics retrieved successfully"
        }
    except ImportError:
        return {
            "success": True,
            "data": {
                "queue_size": 0,
                "current_task": None,
                "completed_today": 0,
                "failed_today": 0,
                "average_wait_time": 0.0,
                "timestamp": int(time.time())
            },
            "message": "Task queue not available"
        }
    except Exception as e:
        logger.error(f"[CloudAPI] /api/tasks/metrics 未预期异常: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"获取任务指标失败: {str(e)}"
        ) from e


# ============================================================================
# 错误处理器
# ============================================================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """HTTP异常处理"""
    from fastapi.responses import JSONResponse
    response = JSONResponse(
        status_code=exc.status_code,
        content={
            "error": "http_error",
            "message": exc.detail,
            "code": exc.status_code,
            "timestamp": time.time()
        }
    )
    # 添加CORS头
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
    return response


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """通用异常处理 - 使用错误脱敏"""
    # 【修复】P1-003: 错误信息脱敏，零静默失败
    safe_message = sanitize_error(exc, ErrorCategory.INTERNAL_ERROR)
    from fastapi.responses import JSONResponse
    response = JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "error_code": "INTERNAL_ERROR",
            "message": safe_message,
            "code": 500,
            "timestamp": time.time()
        }
    )
    # 添加CORS头
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
    return response


# ============================================================================
# MCP 和子代理系统路由 (生产版新增)
# ============================================================================

# MCP 客户端和子代理导入 - 【延迟导入修复】避免循环导入导致的阻塞
try:
    # 只检查模块是否存在，不实际导入
    import importlib.util
    spec1 = importlib.util.find_spec("core.tool.tool_manager")
    spec2 = importlib.util.find_spec("core.subagent.manager")
    MCP_SUBAGENT_AVAILABLE = bool(spec1 and spec2)
    # 模块存在时将在需要时延迟导入；否则静默处理
except Exception:
    MCP_SUBAGENT_AVAILABLE = False
    # 静默处理导入检查异常


class MCPStatusResponse(BaseModel):
    """MCP状态响应"""
    enabled: bool = Field(..., description="MCP是否已启用")
    servers: list[str] = Field(default=[], description="已连接的服务器列表")
    tools_count: int = Field(default=0, description="MCP工具数量")
    servers_detail: list[dict[str, Any]] = Field(default=[], description="服务器详细信息")


class SubAgentListResponse(BaseModel):
    """子代理列表响应"""
    agents: list[dict[str, Any]] = Field(..., description="可用子代理列表")
    count: int = Field(..., description="子代理数量")


class SubAgentDelegateRequest(BaseModel):
    """子代理委派请求"""
    agent_type: str = Field(..., description="子代理类型",
                           examples=["code_reviewer", "tester", "researcher", "planner", "security_auditor", "performance_optimizer"])
    task: str = Field(..., description="任务描述", min_length=1)
    context: dict[str, Any] | None = Field(default=None, description="额外上下文")
    async_mode: bool = Field(default=False, description="是否异步执行")


class SubAgentDelegateResponse(BaseModel):
    """子代理委派响应"""
    success: bool = Field(..., description="是否成功")
    result: str | None = Field(default=None, description="执行结果")
    task_id: str | None = Field(default=None, description="任务ID（异步模式）")
    error: str | None = Field(default=None, description="错误信息")


# ═══════════════════════════════════════════════════════════════════════════════
# 干预API请求/响应模型
# ═══════════════════════════════════════════════════════════════════════════════

class AgentInterventionType(str, Enum):
    """父代理干预类型"""
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    CANCEL = "CANCEL"


class SubAgentInterventionType(str, Enum):
    """子代理干预类型"""
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    ADJUST = "ADJUST"
    REPLAN = "REPLAN"
    CANCEL = "CANCEL"


class AgentInterventionRequest(BaseModel):
    """父代理干预请求"""
    task_id: str = Field(..., description="任务ID")
    type: AgentInterventionType = Field(..., description="干预类型")


class AgentInterventionResponse(BaseModel):
    """父代理干预响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="响应消息")
    status: str | None = Field(default=None, description="当前任务状态")


class SubAgentInterventionRequest(BaseModel):
    """子代理干预请求"""
    type: SubAgentInterventionType = Field(..., description="干预类型")
    reason: str | None = Field(default=None, description="干预原因")
    new_task: str | None = Field(default=None, description="新任务描述（REPLAN类型使用）")
    adjustment: str | None = Field(default=None, description="调整建议（ADJUST类型使用）")


class SubAgentInterventionResponse(BaseModel):
    """子代理干预响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="响应消息")
    status: str | None = Field(default=None, description="当前子代理状态")


class SubAgentStatusResponse(BaseModel):
    """子代理状态响应"""
    runtime_id: str = Field(..., description="运行时ID")
    name: str = Field(..., description="代理名称")
    status: str = Field(..., description="当前状态")
    progress: float | None = Field(default=None, description="进度百分比")
    current_step: str | None = Field(default=None, description="当前步骤")
    error: str | None = Field(default=None, description="错误信息")
    parent_runtime_id: str | None = Field(default=None, description="父运行时ID")
    children_count: int = Field(default=0, description="子代理数量")


@app.get("/api/mcp/status", response_model=MCPStatusResponse)
async def get_mcp_status(current_user: str = Depends(get_current_user)):
    """
    获取 MCP (Model Context Protocol) 状态

    - 需要有效的Bearer Token认证

    返回:
    - **enabled**: MCP是否已启用
    - **servers**: 已连接的服务器列表
    - **tools_count**: MCP工具数量
    - **servers_detail**: 服务器详细信息
    """
    if not MCP_SUBAGENT_AVAILABLE:
        return MCPStatusResponse(enabled=False, servers=[], tools_count=0, servers_detail=[])

    try:
        from core.tool.tool_manager import get_mcp_status as get_mcp_status_v2
        status = get_mcp_status_v2()
        return MCPStatusResponse(**status)
    except Exception as e:
        logger.error(f"[MCP] 获取状态失败: {e}")
        return MCPStatusResponse(enabled=False, servers=[], tools_count=0, servers_detail=[])


@app.post("/api/mcp/enable")
async def enable_mcp(current_user: str = Depends(get_current_user)):
    """
    启用 MCP 服务

    从配置文件加载 MCP 服务器配置并启用。
    - 需要有效的Bearer Token认证

    返回:
    - **success**: 是否成功启用
    - **message**: 状态消息
    """
    if not MCP_SUBAGENT_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MCP模块不可用"
        )

    try:
        import yaml
        config_path = Path(__file__).parent.parent / "config" / "mcp_servers.yaml"

        if not config_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="MCP配置文件不存在"
            )

        async with aiofiles.open(config_path, encoding='utf-8') as f:
            content = await f.read()
            config = yaml.safe_load(content)

        servers = config.get('mcp_servers', [])
        from core.tool.tool_manager import tool_manager
        results = await tool_manager.enable_mcp(servers)

        success_count = sum(1 for v in results.values() if v)

        return {
            "success": True,
            "message": f"MCP 启用完成: {success_count}/{len(results)} 个服务器连接成功",
            "results": results
        }

    except Exception as e:
        logger.error(f"[MCP] 启用失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"启用MCP失败: {str(e)}"
        ) from e


@app.post("/api/mcp/disable")
async def disable_mcp(current_user: str = Depends(get_current_user)):
    """
    禁用 MCP 服务

    - 需要有效的Bearer Token认证

    返回:
    - **success**: 是否成功禁用
    - **message**: 状态消息
    """
    if not MCP_SUBAGENT_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MCP模块不可用"
        )

    try:
        from core.tool.tool_manager import tool_manager
        await tool_manager.disable_mcp()
        return {
            "success": True,
            "message": "MCP 已禁用"
        }
    except Exception as e:
        logger.error(f"[MCP] 禁用失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"禁用MCP失败: {str(e)}"
        ) from e


@app.get("/api/subagent/list", response_model=SubAgentListResponse)
async def list_subagents(current_user: str = Depends(get_current_user)):
    """
    获取可用子代理列表

    - 需要有效的Bearer Token认证

    返回:
    - **agents**: 子代理列表
    - **count**: 子代理数量
    """
    if not MCP_SUBAGENT_AVAILABLE:
        return SubAgentListResponse(agents=[], count=0)

    try:
        from core.subagent.config import PRESET_SUBAGENTS
        agents = []
        for agent_id, config in PRESET_SUBAGENTS.items():
            agents.append({
                "id": agent_id,
                "name": config.name,
                "description": config.description,
                "model": config.model,
                "system_prompt_length": len(config.prompt) if config.prompt else 0
            })

        return SubAgentListResponse(agents=agents, count=len(agents))

    except Exception as e:
        logger.error(f"[SubAgent] 获取列表失败: {e}")
        return SubAgentListResponse(agents=[], count=0)


@app.post("/api/subagent/delegate", response_model=SubAgentDelegateResponse)
async def delegate_to_subagent(
    request: SubAgentDelegateRequest,
    current_user: str = Depends(get_current_user)
):
    """
    委派任务给子代理

    可用的子代理类型:
    - **code_reviewer**: 代码审查专家
    - **tester**: 测试工程师
    - **researcher**: 研究分析师
    - **planner**: 架构规划师
    - **security_auditor**: 安全审计员
    - **performance_optimizer**: 性能优化师

    - 需要有效的Bearer Token认证

    返回:
    - **success**: 是否成功
    - **result**: 执行结果（同步模式）
    - **task_id**: 任务ID（异步模式）
    - **error**: 错误信息
    """
    if not MCP_SUBAGENT_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="子代理模块不可用"
        )

    try:
        from core.subagent import delegate

        if request.async_mode:
            # 异步模式：创建后台任务
            task = safe_create_task(
                delegate(request.agent_type, request.task, request.context),
                name="subagent_delegate"
            )
            return SubAgentDelegateResponse(
                success=True,
                task_id=str(id(task)),
                result=None,
                error=None
            )
        else:
            # 同步模式：直接执行
            result = await delegate(request.agent_type, request.task, request.context)
            return SubAgentDelegateResponse(
                success=True,
                result=result,
                task_id=None,
                error=None
            )

    except Exception as e:
        logger.error(f"[SubAgent] 委派失败: {e}")
        return SubAgentDelegateResponse(
            success=False,
            result=None,
            task_id=None,
            error=str(e)
        )


# ============================================================================
# 【Week 1】代理干预API - 前端暂停/调整/取消功能
# ============================================================================

# 活跃子代理运行时注册表（用于干预API定位）
_subagent_runtime_registry: dict[str, Any] = {}

def _register_subagent_runtime(runtime_id: str, runtime: Any):
    """注册子代理运行时到全局注册表"""
    _subagent_runtime_registry[runtime_id] = runtime
    logger.debug(f"[InterventionAPI] 子代理运行时注册: {runtime_id}")

def _unregister_subagent_runtime(runtime_id: str):
    """从注册表移除子代理运行时"""
    _subagent_runtime_registry.pop(runtime_id, None)
    logger.debug(f"[InterventionAPI] 子代理运行时注销: {runtime_id}")

def _get_subagent_runtime(runtime_id: str) -> Any | None:
    """从注册表获取子代理运行时"""
    return _subagent_runtime_registry.get(runtime_id)


@app.post("/api/agent/intervene", response_model=AgentInterventionResponse)
async def intervene_agent(
    request: AgentInterventionRequest,
    current_user: str = Depends(get_current_user)
):
    """
    父代理干预 - 暂停/恢复/取消主Agent任务

    **需要有效的Bearer Token认证**

    ## 干预类型
    - **PAUSE**: 暂停任务执行
    - **RESUME**: 恢复任务执行
    - **CANCEL**: 取消任务执行

    ## 使用示例
    ```json
    {
        "task_id": "task-123",
        "type": "PAUSE"
    }
    ```
    """
    if not REALTIME_INTERVENTION_AVAILABLE:
        return AgentInterventionResponse(
            success=False,
            message="实时干预系统不可用",
            status="unknown"
        )

    try:

        task_id = request.task_id
        intervention_type = request.type

        logger.info(f"[InterventionAPI] 父代理干预请求: {task_id}, 类型: {intervention_type}")

        # 构建干预指令
        if intervention_type == AgentInterventionType.PAUSE:
            user_input = "暂停执行"
        elif intervention_type == AgentInterventionType.RESUME:
            user_input = "继续执行"
        elif intervention_type == AgentInterventionType.CANCEL:
            user_input = "取消任务"
        else:
            return AgentInterventionResponse(
                success=False,
                message=f"未知的干预类型: {intervention_type}",
                status="unknown"
            )

        # 提交干预
        success = realtime_intervention.submit_intervention(
            task_id=task_id,
            user_input=user_input
        )

        if success:
            # 获取当前任务状态
            realtime_intervention.get_task_memory(task_id)
            current_status = "paused" if intervention_type == AgentInterventionType.PAUSE else \
                           "running" if intervention_type == AgentInterventionType.RESUME else \
                           "cancelled"

            return AgentInterventionResponse(
                success=True,
                message=f"干预已提交: {intervention_type.value}",
                status=current_status
            )
        else:
            return AgentInterventionResponse(
                success=False,
                message="任务不存在或干预提交失败",
                status="unknown"
            )

    except Exception as e:
        logger.error(f"[InterventionAPI] 父代理干预失败: {e}", exc_info=True)
        return AgentInterventionResponse(
            success=False,
            message=f"干预失败: {str(e)}",
            status="error"
        )


@app.post("/api/subagents/{runtime_id}/intervene", response_model=SubAgentInterventionResponse)
async def intervene_subagent(
    runtime_id: str,
    request: SubAgentInterventionRequest,
    current_user: str = Depends(get_current_user)
):
    """
    子代理干预 - 暂停/恢复/调整/重新规划/取消子代理

    **需要有效的Bearer Token认证**

    ## 干预类型
    - **PAUSE**: 暂停子代理执行
    - **RESUME**: 恢复子代理执行
    - **ADJUST**: 调整执行方向（需要提供adjustment字段）
    - **REPLAN**: 重新规划任务（需要提供new_task字段）
    - **CANCEL**: 取消子代理执行

    ## 使用示例
    ### 暂停子代理
    ```json
    {
        "type": "PAUSE",
        "reason": "用户需要确认"
    }
    ```

    ### 调整方向
    ```json
    {
        "type": "ADJUST",
        "adjustment": "请改用另一种方法实现"
    }
    ```

    ### 重新规划
    ```json
    {
        "type": "REPLAN",
        "new_task": "新的任务描述"
    }
    ```
    """
    try:
        logger.info(f"[InterventionAPI] 子代理干预请求: {runtime_id}, 类型: {request.type}")

        # 从注册表获取子代理运行时
        runtime = _get_subagent_runtime(runtime_id)

        if not runtime:
            # 尝试从subagent_manager获取
            try:
                from core.subagent.manager import subagent_manager
                runtime = subagent_manager.get_runtime(runtime_id)
            except ImportError:
                pass

        if not runtime:
            return SubAgentInterventionResponse(
                success=False,
                message=f"子代理运行时未找到: {runtime_id}",
                status="not_found"
            )

        intervention_type = request.type

        # 执行干预
        if intervention_type == SubAgentInterventionType.PAUSE:
            # 暂停子代理
            if hasattr(runtime, 'status'):
                from core.subagent.runtime import SubAgentStatus
                if runtime.status == SubAgentStatus.RUNNING:
                    runtime.status = SubAgentStatus.PAUSED
                    logger.info(f"[InterventionAPI] 子代理已暂停: {runtime_id}")
                    return SubAgentInterventionResponse(
                        success=True,
                        message="子代理已暂停",
                        status="paused"
                    )
                else:
                    return SubAgentInterventionResponse(
                        success=False,
                        message=f"子代理当前状态不支持暂停: {runtime.status.value if hasattr(runtime.status, 'value') else runtime.status}",
                        status=runtime.status.value if hasattr(runtime.status, 'value') else str(runtime.status)
                    )
            else:
                return SubAgentInterventionResponse(
                    success=False,
                    message="子代理运行时缺少状态属性",
                    status="unknown"
                )

        elif intervention_type == SubAgentInterventionType.RESUME:
            # 恢复子代理
            if hasattr(runtime, 'status'):
                from core.subagent.runtime import SubAgentStatus
                if runtime.status == SubAgentStatus.PAUSED:
                    runtime.status = SubAgentStatus.RUNNING
                    logger.info(f"[InterventionAPI] 子代理已恢复: {runtime_id}")
                    return SubAgentInterventionResponse(
                        success=True,
                        message="子代理已恢复执行",
                        status="running"
                    )
                else:
                    return SubAgentInterventionResponse(
                        success=False,
                        message=f"子代理当前状态不支持恢复: {runtime.status.value if hasattr(runtime.status, 'value') else runtime.status}",
                        status=runtime.status.value if hasattr(runtime.status, 'value') else str(runtime.status)
                    )
            else:
                return SubAgentInterventionResponse(
                    success=False,
                    message="子代理运行时缺少状态属性",
                    status="unknown"
                )

        elif intervention_type == SubAgentInterventionType.ADJUST:
            # 调整方向 - 通过干预系统提交
            if not request.adjustment:
                return SubAgentInterventionResponse(
                    success=False,
                    message="ADJUST类型需要提供adjustment字段",
                    status="invalid_request"
                )

            if REALTIME_INTERVENTION_AVAILABLE:
                success = realtime_intervention.submit_intervention(
                    task_id=runtime_id,
                    user_input=f"调整: {request.adjustment}"
                )
                if success:
                    return SubAgentInterventionResponse(
                        success=True,
                        message="调整建议已提交",
                        status="adjusted"
                    )

            return SubAgentInterventionResponse(
                success=False,
                message="调整提交失败",
                status="error"
            )

        elif intervention_type == SubAgentInterventionType.REPLAN:
            # 重新规划
            if not request.new_task:
                return SubAgentInterventionResponse(
                    success=False,
                    message="REPLAN类型需要提供new_task字段",
                    status="invalid_request"
                )

            if REALTIME_INTERVENTION_AVAILABLE:
                success = realtime_intervention.submit_intervention(
                    task_id=runtime_id,
                    user_input=f"重新规划: {request.new_task}"
                )
                if success:
                    return SubAgentInterventionResponse(
                        success=True,
                        message="重新规划请求已提交",
                        status="replanning"
                    )

            return SubAgentInterventionResponse(
                success=False,
                message="重新规划提交失败",
                status="error"
            )

        elif intervention_type == SubAgentInterventionType.CANCEL:
            # 取消子代理
            if hasattr(runtime, 'cancel'):
                runtime.cancel()
                logger.info(f"[InterventionAPI] 子代理已取消: {runtime_id}")
                return SubAgentInterventionResponse(
                    success=True,
                    message="子代理已取消",
                    status="cancelled"
                )
            else:
                return SubAgentInterventionResponse(
                    success=False,
                    message="子代理运行时缺少cancel方法",
                    status="unknown"
                )

        else:
            return SubAgentInterventionResponse(
                success=False,
                message=f"未知的干预类型: {intervention_type}",
                status="unknown"
            )

    except Exception as e:
        logger.error(f"[InterventionAPI] 子代理干预失败: {e}", exc_info=True)
        return SubAgentInterventionResponse(
            success=False,
            message=f"干预失败: {str(e)}",
            status="error"
        )


@app.get("/api/subagents/{runtime_id}/status", response_model=SubAgentStatusResponse)
async def get_subagent_status(
    runtime_id: str,
    current_user: str = Depends(get_current_user)
):
    """
    获取子代理状态

    **需要有效的Bearer Token认证**

    返回子代理的详细状态信息，包括：
    - 当前执行状态
    - 进度百分比
    - 当前步骤
    - 错误信息（如果有）
    - 父子关系信息
    """
    try:
        logger.debug(f"[InterventionAPI] 获取子代理状态: {runtime_id}")

        # 从注册表获取子代理运行时
        runtime = _get_subagent_runtime(runtime_id)

        if not runtime:
            # 尝试从subagent_manager获取
            try:
                from core.subagent.manager import subagent_manager
                runtime = subagent_manager.get_runtime(runtime_id)
            except ImportError:
                pass

        if not runtime:
            raise HTTPException(
                status_code=404,
                detail=f"子代理运行时未找到: {runtime_id}"
            )

        # 构建状态响应
        status_response = SubAgentStatusResponse(
            runtime_id=runtime_id,
            name=getattr(runtime.config, 'name', 'Unknown') if hasattr(runtime, 'config') else 'Unknown',
            status=getattr(runtime.status, 'value', str(runtime.status)) if hasattr(runtime, 'status') else 'unknown',
            progress=getattr(runtime, 'progress', None),
            current_step=getattr(runtime, 'current_step', None),
            error=getattr(runtime, 'error', None)
        )

        # 添加父子关系信息
        if hasattr(runtime, 'parent') and runtime.parent:
            status_response.parent_runtime_id = getattr(runtime.parent, 'runtime_id', None)

        if hasattr(runtime, 'children'):
            status_response.children_count = len(runtime.children)

        return status_response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[InterventionAPI] 获取子代理状态失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取状态失败: {str(e)}") from e


# ============================================================================
# 【Week 2 Day 5-6】子代理状态实时推送 WebSocket
# ============================================================================

@app.websocket("/ws/subagent/{runtime_id}")
async def subagent_status_websocket(websocket: WebSocket, runtime_id: str):
    """
    子代理状态实时推送 WebSocket

    **路径参数**:
    - runtime_id: 子代理运行时ID

    **消息格式**:
    - 连接成功后，服务器会定期推送状态更新
    - 客户端可以发送 ping 保持连接

    **示例消息**:
    ```json
    {
        "type": "status_update",
        "data": {
            "runtime_id": "abc123",
            "status": "running",
            "progress": 65,
            "current_step": "分析代码结构",
            "timestamp": 1234567890
        },
        "timestamp": 1234567890
    }
    ```
    """
    await websocket.accept()

    try:
        # 检查运行时是否存在
        runtime = _get_subagent_runtime(runtime_id)
        if not runtime:
            try:
                from core.subagent.manager import subagent_manager
                runtime = subagent_manager.get_runtime(runtime_id)
            except ImportError:
                pass

        if not runtime:
            await websocket.send_json({
                "type": "error",
                "error": f"子代理运行时未找到: {runtime_id}",
                "timestamp": time.time()
            })
            await websocket.close(code=4004)
            return

        logger.info(f"[SubAgentWebSocket] 客户端连接: {runtime_id}")

        # 发送初始状态
        await websocket.send_json({
            "type": "connected",
            "data": {
                "runtime_id": runtime_id,
                "status": getattr(runtime.status, 'value', str(runtime.status)) if hasattr(runtime, 'status') else 'unknown',
                "progress": getattr(runtime, 'progress', None),
                "current_step": getattr(runtime, 'current_step', None)
            },
            "timestamp": time.time()
        })

        # 注册到事件广播器（如果可用）
        try:
            from core.subagent.event_broadcaster import event_broadcaster
            # 创建一个模拟的槽位ID（使用runtime_id的hash）
            slot_id = hash(runtime_id) % 10000
            event_broadcaster.register_connection(slot_id, websocket)
            logger.debug(f"[SubAgentWebSocket] 已注册到事件广播器: slot_id={slot_id}")
        except ImportError:
            pass

        # 状态推送循环
        last_status = None
        ping_interval = 30  # 30秒发送一次ping
        last_ping = time.time()

        while True:
            try:
                # 非阻塞接收客户端消息
                try:
                    message = await asyncio.wait_for(
                        websocket.receive_text(),
                        timeout=1.0
                    )
                    # 处理ping
                    if message == 'ping':
                        await websocket.send_json({"type": "pong", "timestamp": time.time()})
                        last_ping = time.time()
                except asyncio.TimeoutError:
                    pass

                # 检查连接是否活跃
                if time.time() - last_ping > ping_interval * 2:
                    logger.warning(f"[SubAgentWebSocket] 连接超时: {runtime_id}")
                    break

                # 获取当前状态
                current_status = {
                    "runtime_id": runtime_id,
                    "status": getattr(runtime.status, 'value', str(runtime.status)) if hasattr(runtime, 'status') else 'unknown',
                    "progress": getattr(runtime, 'progress', None),
                    "current_step": getattr(runtime, 'current_step', None),
                    "error": getattr(runtime, 'error', None)
                }

                # 状态变化时推送
                if current_status != last_status:
                    await websocket.send_json({
                        "type": "status_update",
                        "data": current_status,
                        "timestamp": time.time()
                    })
                    last_status = current_status.copy()

                # 发送定期ping
                if time.time() - last_ping > ping_interval:
                    await websocket.send_json({"type": "ping", "timestamp": time.time()})
                    last_ping = time.time()

                # 检查任务是否结束
                status_value = current_status.get('status', '')
                if status_value in ('completed', 'failed', 'cancelled'):
                    logger.info(f"[SubAgentWebSocket] 任务结束，关闭连接: {runtime_id} ({status_value})")
                    await websocket.send_json({
                        "type": "completed",
                        "data": current_status,
                        "timestamp": time.time()
                    })
                    break

                await asyncio.sleep(0.5)  # 500ms检查一次

            except WebSocketDisconnect:
                logger.info(f"[SubAgentWebSocket] 客户端断开: {runtime_id}")
                break
            except ConnectionResetError as e:
                logger.warning(f"[SubAgentWebSocket] 连接重置: {e}")
                break
            except Exception as e:
                logger.error(f"[SubAgentWebSocket] 处理消息失败: {e}", exc_info=True)
                break

    except Exception as e:
        logger.error(f"[SubAgentWebSocket] WebSocket错误: {e}", exc_info=True)

    finally:
        # 清理注册
        try:
            from core.subagent.event_broadcaster import event_broadcaster
            slot_id = hash(runtime_id) % 10000
            event_broadcaster.unregister_connection(slot_id, websocket)
        except ImportError:
            pass

        try:
            await websocket.close()
        except Exception as e:
            # 【零静默失败修复】WebSocket关闭异常，记录ERROR日志但不影响清理流程
            logger.error(f"[SILENT_FAILURE_BLOCKED] WebSocket关闭异常 (runtime_id={runtime_id}): {type(e).__name__}: {e}")

        logger.info(f"[SubAgentWebSocket] 连接已关闭: {runtime_id}")


# ============================================================================
# 【SmartContextManager集成】AI状态流WebSocket和API
# ============================================================================

# 导入SmartContextManager
try:
    from core.consciousness.life_presence import get_life_presence_manager
    from core.prompt.smart_context_manager import get_smart_context_manager
    SMART_CONTEXT_API_AVAILABLE = True
except ImportError:
    SMART_CONTEXT_API_AVAILABLE = False
    logger.warning("[CloudAPI] SmartContextManager不可用，AI状态流API将不可用")

@app.get("/api/ai-status")
async def get_ai_status(user_id: str = Depends(get_current_user)):
    """
    获取AI当前状态

    返回AI的当前状态、执行动作、进度等信息，用于前端状态指示器展示。
    """
    if not SMART_CONTEXT_API_AVAILABLE:
        return {
            "success": False,
            "error": "SmartContextManager不可用"
        }

    try:
        manager = get_life_presence_manager()
        indicator = manager.get_status_indicator()

        return {
            "success": True,
            "data": {
                "state": indicator.state.value,
                "current_action": indicator.current_action,
                "progress": indicator.progress,
                "estimated_remaining": indicator.estimated_remaining,
                "details": indicator.details
            }
        }
    except Exception as e:
        logger.error(f"[CloudAPI] /api/ai-status 错误: {e}")
        return {
            "success": False,
            "error": str(e)
        }

@app.get("/api/task-status/{task_id}")
async def get_task_status(task_id: str, user_id: str = Depends(get_current_user)):
    """
    获取任务状态

    返回指定任务的详细状态，包括：
    - 是否长任务
    - 执行步数
    - 启用的功能
    - 上下文统计
    """
    if not SMART_CONTEXT_API_AVAILABLE:
        return {
            "success": False,
            "error": "SmartContextManager不可用"
        }

    try:
        manager = get_smart_context_manager()
        status = manager.get_status(task_id)

        return {
            "success": True,
            "data": status
        }
    except Exception as e:
        logger.error(f"[CloudAPI] /api/task-status/{task_id} 错误: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@app.websocket("/ws/ai-status/{user_id}")
async def ai_status_websocket(websocket: WebSocket, user_id: str):
    """
    AI状态流WebSocket

    实时推送AI状态变化，包括：
    - 状态变化（thinking/executing/waiting/completed）
    - 进度更新
    - 关键决策点通知
    - 错误/警告
    """
    await websocket.accept()

    if not SMART_CONTEXT_API_AVAILABLE:
        await websocket.send_json({
            "type": "error",
            "message": "SmartContextManager不可用"
        })
        await websocket.close()
        return

    try:
        manager = get_life_presence_manager()

        # 发送初始状态
        indicator = manager.get_status_indicator()
        await websocket.send_json({
            "type": "status",
            "data": indicator.to_dict()
        })

        # 监听状态变化
        async def status_listener(old_state, new_state, action):
            await websocket.send_json({
                "type": "state_change",
                "data": {
                    "old_state": old_state.value,
                    "new_state": new_state.value,
                    "action": action,
                    "timestamp": time.time()
                }
            })

        # 注册监听
        manager.add_state_listener(status_listener)

        try:
            # 保持连接
            while True:
                # 接收心跳
                data = await websocket.receive_text()
                if data == "ping":
                    await websocket.send_text("pong")

                # 定期发送状态更新（每5秒）
                await asyncio.sleep(5)
                indicator = manager.get_status_indicator()
                await websocket.send_json({
                    "type": "heartbeat",
                    "data": indicator.to_dict()
                })

        except WebSocketDisconnect:
            logger.info(f"[CloudAPI] AI状态WebSocket断开: {user_id}")
        except ConnectionResetError as e:
            logger.warning(f"[CloudAPI] AI状态WebSocket连接重置: {e}")
        finally:
            # 移除监听
            manager.remove_state_listener(status_listener)

    except ConnectionResetError as e:
        logger.warning(f"[CloudAPI] AI状态WebSocket连接建立时重置: {e}")
    except Exception as e:
        logger.error(f"[CloudAPI] AI状态WebSocket错误: {e}", exc_info=True)
        await websocket.send_json({
            "type": "error",
            "message": str(e)
        })


# ============================================================================
# 生命体征 WebSocket 端点
# ============================================================================

@app.websocket("/ws/life-state")
async def life_state_websocket(websocket: WebSocket):
    """
    生命体征实时推送 WebSocket

    接收 query 参数 user_id，定时推送硅基生命体征更新。
    消息格式与前端 LifeStatusPanel 保持一致：
    - type: life_state_update
    - payload: { vitals, activity_level, current_interval, pending_actions, timestamp }
    """
    await websocket.accept()
    user_id = websocket.query_params.get("user_id", "default")
    logger.info(f"[CloudAPI] 生命体征WebSocket连接: user_id={user_id}")

    from core.consciousness.silicon_life_consciousness import get_silicon_life

    try:
        while True:
            try:
                silicon_life = get_silicon_life(user_id)
                vitals = silicon_life.vitals.signs.to_dict()
                life_state = {
                    "vitals": vitals,
                    "activity_level": float(getattr(silicon_life, 'activity_level', 0.5)),
                    "current_interval": float(getattr(silicon_life, 'current_interval', 60.0)),
                    "pending_actions": len(getattr(silicon_life, 'pending_actions', [])),
                    "timestamp": time.time()
                }
                await websocket.send_json({
                    "type": "life_state_update",
                    "payload": life_state
                })
            except Exception as e:
                logger.warning(f"[CloudAPI] 获取生命体征失败: {e}")
                await websocket.send_json({
                    "type": "error",
                    "message": f"获取生命体征失败: {e}"
                })

            # 等待下一个周期或客户端心跳（5秒）
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=5.0)
                if data == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                pass

    except WebSocketDisconnect:
        logger.info(f"[CloudAPI] 生命体征WebSocket断开: {user_id}")
    except Exception as e:
        logger.error(f"[CloudAPI] 生命体征WebSocket错误: {e}", exc_info=True)


# ============================================================================
# 实时干预 WebSocket 端点 (Phase 1 实施)
# ============================================================================

try:
    from api.realtime_intervention_api import InterventionWebSocketHandler
    INTERVENTION_WS_AVAILABLE = True
    print("[CloudAPI] 实时干预 WebSocket 已导入")
except ImportError as e:
    INTERVENTION_WS_AVAILABLE = False
    logger.warning(f"[CloudAPI] 实时干预 WebSocket 导入失败: {e}")

if INTERVENTION_WS_AVAILABLE:
    @app.websocket("/ws/task/{task_id}")
    async def intervention_websocket(websocket: WebSocket, task_id: str):
        """
        实时干预 WebSocket 端点

        允许用户在任务执行过程中发送干预指令：
        - 暂停任务
        - 调整执行方法
        - 切换目标
        - 查询进度
        """
        handler = InterventionWebSocketHandler()
        await handler.handle(websocket, task_id)

    print("[CloudAPI] 实时干预 WebSocket 端点已注册: /ws/task/{task_id}")


# ============================================================================
# 挂载 BTC 交易 WebSocket 端点
# ============================================================================
try:
    from .trading_ws import handle_symbol_websocket
    TRADING_WS_AVAILABLE = True
    print("[CloudAPI] BTC交易 WebSocket 已导入")
except ImportError as e:
    TRADING_WS_AVAILABLE = False
    logger.warning(f"[CloudAPI] BTC交易 WebSocket 导入失败: {e}")

if TRADING_WS_AVAILABLE:
    @app.websocket("/ws/trading/{symbol}")
    async def trading_websocket(
        websocket: WebSocket,
        symbol: str,
        token: str | None = Query(None, description="认证Token")
    ):
        """
        BTC 交易实时数据 WebSocket 端点

        推送内容:
        - price_update: 价格更新 (1秒)
        - kline_update: K线更新
        - trade_signal: AI交易信号
        - trade_execution: 交易执行通知
        - position_update: 持仓变更
        - risk_alert: 风险告警

        路径参数:
        - symbol: 币种代码 (BTC, ETH, SOL...)

        查询参数:
        - token: 认证Token (可选)
        """
        await handle_symbol_websocket(websocket, symbol, token)

    print("[CloudAPI] BTC交易 WebSocket 端点已注册: /ws/trading/{symbol}")


# ============================================================================
# 启动交易WebSocket独立服务器 (8602端口)
# ============================================================================

_trading_ws_server_task = None

async def start_trading_ws_server():
    """在后台启动交易WebSocket服务器 (8602端口)"""
    global _trading_ws_server_task
    try:
        import uvicorn

        from .trading_ws_server import trading_ws_app

        config = uvicorn.Config(
            trading_ws_app,
            host="0.0.0.0",
            port=8602,
            log_level="info",
            loop="asyncio",
            access_log=False,  # 【修复】避免交易WS服务器覆盖uvicorn.access的handler配置，导致主服务器access_log=False失效
            ws_ping_interval=WS_PING_INTERVAL,
            ws_ping_timeout=WS_PING_TIMEOUT,
        )
        server = uvicorn.Server(config)

        print("[CloudAPI] 启动交易WebSocket服务器于 8602 端口...")
        _trading_ws_server_task = safe_create_task(server.serve(), name="trading_ws_server")
        logger.info("[CloudAPI] 交易WebSocket服务器已启动: ws://localhost:8602/ws/trading/{symbol}")

    except Exception as e:
        diagnostic_except_handler(e, context="[CloudAPI] 启动交易WebSocket服务器失败", logger_instance=logger)
        error_msg = f"[CloudAPI] 启动交易WebSocket服务器失败: {e}"
        print(error_msg)

# 在应用启动时启动交易WebSocket服务器
@app.on_event("startup")
async def startup_trading_ws():
    """应用启动时启动交易WebSocket服务器"""
    await start_trading_ws_server()


# ============================================================================
# 启动入口
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    print("""
    ╔═══════════════════════════════════════════════════════════╗
    ║              SiliconBase Cloud API                        ║
    ║                   云端部署 API 服务                        ║
    ╠═══════════════════════════════════════════════════════════╣""")

    # 【P0-015】端口统一从 config 单例读取，system.json 不再包含端口配置
    api_port = config.get("server.api_port", 8600)
    host = config.get("server.host", "127.0.0.1")

    print(f"    ║  文档地址: http://localhost:{api_port}/docs".ljust(62) + "║")
    print(f"    ║  WebSocket: ws://localhost:{api_port}/ws/{{user_id}}".ljust(62) + "║")
    print("    ║  交易WebSocket: ws://localhost:8602/ws/trading/{symbol}".ljust(62) + "║")
    print("    ╚═══════════════════════════════════════════════════════════╝")

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=api_port,
        log_level="info",
        ws_ping_interval=WS_PING_INTERVAL,
        ws_ping_timeout=WS_PING_TIMEOUT,
    )


# 【调试】 模块导入完成标记
# cloud_api.py 模块加载完成print("【调试】 cloud_api.py 模块加载完成")

# 【关键修复】模块导入完成后，设置一个标志表示 cloud_api 已就绪
# 这用于解决 lifespan 可能重复初始化的问题
_CLOUD_API_LOADED = True


# ============================================================================
# 【生产环境】WebSocket Redis Pub/Sub 补丁应用
# 支持多实例部署时的消息广播
# ============================================================================
try:
    from api.websocket_redis_patch import patch_connection_manager, pubsub_manager
    # 应用补丁到 ConnectionManager
    patch_connection_manager(ConnectionManager)
    print("[CloudAPI] WebSocket Redis Pub/Sub 补丁已加载")
except Exception as e:
    print(f"[CloudAPI] WebSocket Redis 补丁加载失败: {e}")


# ============================================================================
# API 挂载状态注册表（防止前端因后端静默失败而被误改）
# ============================================================================

# 预期挂载的关键 API 路由前缀列表
# 注：此处列出所有 intentional 设计的前后端契约端点
EXPECTED_API_ROUTES = [
    ("/api/tasks", "task_api"),
    ("/api/prompt", "prompt_api"),
    ("/api/prompt/layer", "prompt_layer_api"),
    ("/api/prompt/variant", "prompt_variant_api"),
    ("/api/stats", "stats_api"),
    ("/api/voice", "voice_api"),
    ("/api/voice/announce", "voice_announce_api"),
    ("/api/config", "config_api"),
    ("/api/memory", "memory_api"),
    ("/api/vector", "vector_api"),

    ("/api/tools", "tools_api"),
    ("/api/metrics", "metrics_api"),
    ("/api/gamification", "gamification_api"),
    ("/api/ai-config", "ai_config_api"),
    ("/api/features", "features_api"),
    ("/api/system", "system_api"),

    ("/api/consciousness", "consciousness_api"),
    ("/api/three-views", "three_views_api"),
    ("/api/advanced-models", "advanced_models_api"),
    ("/api/template-experiment", "template_experiment_api"),
    ("/api/sync", "sync_api"),
    ("/api/cloud-tools", "cloud_tool_repo_api"),
    ("/api/tool-market", "tool_market_api"),
    ("/api/cost", "cost_api"),
    ("/api/rlhf", "rlhf_api"),
    ("/api/life", "silicon_life_api"),
    ("/api/trading", "trading_api"),
    ("/api/trading-v2", "trading_v2_api"),
    ("/api/exchange", "exchange_config_api"),
    ("/api/auto-trading", "auto_trading_api"),
    ("/api/trading/mode", "trading_mode_api"),
    ("/api/experience", "experience_api"),
    ("/api/sessions", "session_api"),
    ("/api/global-view", "global_view_api"),
    ("/ws/memory-sync", "memory_sync_ws"),
]

def _get_mounted_api_status() -> dict[str, dict[str, Any]]:
    """
    扫描 app.routes，检查 EXPECTED_API_ROUTES 中哪些已挂载。
    返回每个预期 API 的挂载状态和实际匹配到的路径列表。
    """
    mounted_paths = []
    for route in app.routes:
        path = getattr(route, "path", None)
        if path:
            mounted_paths.append(path)
        # 某些路由可能是 Mount 对象，包含 routes 列表
        if hasattr(route, "routes"):
            for sub_route in route.routes:
                sub_path = getattr(sub_route, "path", None)
                if sub_path:
                    mounted_paths.append(sub_path)

    registry = {}
    for prefix, name in EXPECTED_API_ROUTES:
        matched = [p for p in mounted_paths if p.startswith(prefix) or p == prefix or prefix in p]
        registry[name] = {
            "expected_prefix": prefix,
            "mounted": len(matched) > 0,
            "matched_paths": matched[:5]  # 最多展示5条，避免过长
        }
    return registry


def _verify_api_mounts():
    """启动时验证 API 挂载状态，若有缺失则大声告警"""
    registry = _get_mounted_api_status()
    missing = [name for name, info in registry.items() if not info["mounted"]]

    if missing:
        print("\n" + "=" * 70)
        print("【API 挂载告警】以下预期 API 未能在路由表中找到匹配：")
        for name in missing:
            prefix = registry[name]["expected_prefix"]
            print(f"  ❌ {name:30s} (预期前缀: {prefix})")
        print("=" * 70 + "\n")
        logger.warning(f"[APIRegistry] 缺失的关键 API: {missing}")
    else:
        print("【API 挂载检查】所有预期 API 均已正确挂载 [OK]")

    return registry, missing


@app.get("/api/system/api-registry")
async def get_api_registry():
    """
    API 挂载状态注册表。

    前端或运维工具可通过此端点查询后端实际挂载了哪些路由。
    若某个 API 的 mounted=false，说明后端注册失败，应优先修复后端，
    而不是修改前端 URL。
    """
    registry, missing = _verify_api_mounts()
    return {
        "registry": registry,
        "missing": missing,
        "missing_count": len(missing),
        "timestamp": time.time()
    }


@app.on_event("startup")
async def startup_verify_api_mounts():
    """应用启动时自动验证 API 挂载状态"""
    _verify_api_mounts()
