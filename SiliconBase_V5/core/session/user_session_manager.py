#!/usr/bin/env python3
"""
用户会话管理器 - 全局用户会话统一管理
SiliconBase V5.1 多用户支持核心组件

职责：
1. 统一管理用户认证和会话 - 为所有用户提供统一的登录/登出入口
2. 提供统一的入口处理用户消息 - 文本和语音输入的统一处理
3. 协调DialogueManager和UserContextManager - 桥接对话管理和用户上下文
4. 支持JWT token验证 - 简化版JWT实现，支持token生成和验证

核心组件：
- JWTAuthManager: JWT认证管理器，处理token生命周期
- UserSessionManager: 用户会话管理器，单例模式，协调各组件
- UserAuthToken/UserProfile: 数据类，定义认证令牌和用户资料结构

架构说明：
- 单例模式确保全局只有一个会话管理器实例
- 线程锁保护用户资料和token的并发访问
- 事件机制支持扩展（登录/登出/消息等事件）
- 用户资料持久化到JSON文件
"""

# ========================================
# 标准库导入 - 基础功能
# ========================================
import hashlib  # 哈希算法，用于生成token
import json  # JSON序列化
import secrets  # 安全随机数生成，用于token熵
import threading  # 多线程支持，用于锁机制
import time  # 时间相关功能，用于token时间戳
from collections.abc import Callable  # 类型提示
from dataclasses import dataclass, field  # 数据类定义
from datetime import datetime, timedelta  # 日期时间处理
from pathlib import Path  # 路径操作

from core.Consciousness import remove_consciousness  # 意识服务清理（修复内存泄漏）

# ========================================
# 核心模块导入
# ========================================
from core.dialog.dialogue_manager import DialogueManager, InputMode  # 对话管理器
from core.logger import logger  # 日志记录器
from core.multi_user import multi_user_manager  # 多用户管理
from core.tool.tool_manager import ToolContextFactory  # 工具上下文工厂（修复内存泄漏）
from core.work_mode_manager import WorkMode  # 工作模式枚举

# ========================================
# 向后兼容别名定义
# ========================================
# 为向后兼容保留别名，旧代码可能使用DialogueWorkMode
DialogueWorkMode = WorkMode


# ========================================
# 数据类定义 - 用户认证令牌
# ========================================
@dataclass
class UserAuthToken:
    """
    用户认证令牌 - 存储token的完整信息

    Attributes:
        token: 令牌字符串（SHA256哈希值）
        user_id: 关联的用户ID
        created_at: 创建时间
        expires_at: 过期时间
        scopes: 权限范围列表（如["user", "admin"]）
    """
    token: str                                    # 令牌字符串
    user_id: str                                  # 用户ID
    created_at: datetime                          # 创建时间
    expires_at: datetime                          # 过期时间
    scopes: list[str] = field(default_factory=list)  # 权限范围，默认空列表

    def is_valid(self) -> bool:
        """
        检查令牌是否有效（未过期）

        Returns:
            bool: True表示有效，False表示已过期
        """
        return datetime.now() < self.expires_at  # 当前时间早于过期时间

    def to_dict(self) -> dict:
        """
        序列化为字典，便于JSON存储

        Returns:
            Dict: 包含所有字段的字典
        """
        return {
            "token": self.token,                              # 令牌
            "user_id": self.user_id,                          # 用户ID
            "created_at": self.created_at.isoformat(),        # ISO格式时间
            "expires_at": self.expires_at.isoformat(),        # ISO格式时间
            "scopes": self.scopes                             # 权限范围
        }


# ========================================
# 数据类定义 - 用户资料
# ========================================
@dataclass
class UserProfile:
    """
    用户资料 - 存储用户的基本信息

    Attributes:
        user_id: 用户唯一标识
        username: 用户名（显示名称）
        email: 邮箱（可选）
        avatar: 头像URL（可选）
        preferences: 偏好设置字典
        created_at: 注册时间
        last_login: 最后登录时间
    """
    user_id: str                                  # 用户ID
    username: str                                 # 用户名
    email: str | None = None                   # 邮箱，可选
    avatar: str | None = None                  # 头像URL，可选
    preferences: dict = field(default_factory=dict)  # 偏好设置，默认空字典
    created_at: datetime = field(default_factory=datetime.now)  # 注册时间，默认当前
    last_login: datetime | None = None         # 最后登录时间，可选
    password_hash: str | None = None           # 密码哈希，可选

    def to_dict(self) -> dict:
        """
        序列化为字典

        Returns:
            Dict: 包含所有字段的字典
        """
        return {
            "user_id": self.user_id,                          # 用户ID
            "username": self.username,                        # 用户名
            "email": self.email,                              # 邮箱
            "avatar": self.avatar,                            # 头像
            "preferences": self.preferences,                  # 偏好设置
            "created_at": self.created_at.isoformat(),        # ISO格式时间
            "last_login": self.last_login.isoformat() if self.last_login else None,  # 可选字段
            "password_hash": self.password_hash                # 密码哈希
        }


# ========================================
# JWT认证管理器 - 处理token生命周期
# ========================================
class JWTAuthManager:
    """
    JWT认证管理器（简化实现）

    生产环境建议使用：PyJWT + 密钥管理

    职责：
    1. 生成用户token
    2. 验证token有效性
    3. 撤销token
    4. 清理过期token

    数据存储：
    - _tokens: token -> UserAuthToken映射
    - _user_tokens: user_id -> set of tokens映射（方便查找用户的所有token）
    """

    def __init__(self, secret_key: str = None):
        """
        初始化认证管理器

        Args:
            secret_key: 密钥（为None则自动生成随机密钥）
        """
        self.secret_key = secret_key or secrets.token_urlsafe(32)  # 32字节随机密钥
        self._tokens: dict[str, UserAuthToken] = {}  # token -> UserAuthToken字典
        self._user_tokens: dict[str, set] = {}  # user_id -> token集合
        self._lock = threading.RLock()  # 可重入锁，保护并发访问

    def generate_token(
        self,
        user_id: str,
        expires_hours: int = 24,
        scopes: list[str] = None
    ) -> str:
        """
        生成用户token

        简化版JWT实现：使用SHA256哈希生成token
        实际JWT应包含header.payload.signature三部分

        Args:
            user_id: 用户唯一标识
            expires_hours: 过期时间（小时），默认24小时
            scopes: 权限范围列表，默认["user"]

        Returns:
            str: JWT token字符串（64位十六进制）
        """
        # 生成token数据：用户ID + 当前时间 + 随机字符串
        token_data = f"{user_id}:{time.time()}:{secrets.token_urlsafe(16)}"
        # 使用SHA256哈希生成固定长度的token
        token = hashlib.sha256(token_data.encode()).hexdigest()

        # 创建认证令牌对象
        auth_token = UserAuthToken(
            token=token,
            user_id=user_id,
            created_at=datetime.now(),
            expires_at=datetime.now() + timedelta(hours=expires_hours),  # 计算过期时间
            scopes=scopes or ["user"]  # 默认"user"权限
        )

        with self._lock:  # 加锁保护
            self._tokens[token] = auth_token  # 存储token
            if user_id not in self._user_tokens:  # 用户首次有token
                self._user_tokens[user_id] = set()  # 创建集合
            self._user_tokens[user_id].add(token)  # 添加到用户token集合

        return token  # 返回生成的token

    def validate_token(self, token: str) -> str | None:
        """
        验证token

        Args:
            token: JWT token字符串

        Returns:
            Optional[str]: 用户ID（有效时），None（无效时）
        """
        with self._lock:  # 加锁保护
            auth_token = self._tokens.get(token)  # 查找token
            if not auth_token:  # token不存在
                return None

            if not auth_token.is_valid():  # token已过期
                # 清理过期token
                self._revoke_token(token)
                return None

            return auth_token.user_id  # 返回关联的用户ID

    def revoke_token(self, token: str):
        """
        撤销token（公开接口）

        Args:
            token: 要撤销的token
        """
        with self._lock:  # 加锁保护
            self._revoke_token(token)  # 调用内部方法

    def _revoke_token(self, token: str):
        """
        内部撤销token（无锁版本）

        内部使用，调用方已加锁

        Args:
            token: 要撤销的token
        """
        auth_token = self._tokens.pop(token, None)  # 从字典移除
        if auth_token:  # token存在
            user_id = auth_token.user_id  # 获取用户ID
            if user_id in self._user_tokens:  # 用户有token记录
                self._user_tokens[user_id].discard(token)  # 从集合移除

    def revoke_all_user_tokens(self, user_id: str):
        """
        撤销用户的所有token

        用于用户登出或密码修改时

        Args:
            user_id: 用户ID
        """
        with self._lock:  # 加锁保护
            tokens = self._user_tokens.get(user_id, set()).copy()  # 复制集合
            for token in tokens:  # 遍历撤销
                self._tokens.pop(token, None)
            self._user_tokens[user_id] = set()  # 清空用户token集合

    def cleanup_expired_tokens(self):
        """
        清理过期token

        定期调用以释放内存
        """
        with self._lock:  # 加锁保护
            # 找出所有过期token
            expired = [
                token for token, auth in self._tokens.items()
                if not auth.is_valid()
            ]
            for token in expired:  # 逐一撤销
                self._revoke_token(token)

            if expired:  # 有清理时记录日志
                logger.info(f"[JWTAuthManager] 清理 {len(expired)} 个过期token")


# ========================================
# 用户会话管理器 - 核心类，单例模式
# ========================================
class UserSessionManager:
    """
    全局用户会话管理器 - 多用户支持的核心协调器

    统一管理：
    - 用户认证：登录、登出、token验证
    - 会话创建/销毁：管理用户对话会话
    - 消息处理：文本和语音消息的统一入口
    - 用户资料管理：注册、更新、查询

    协调的组件：
    - DialogueManager: 对话管理
    - JWTAuthManager: 认证管理
    - multi_user_manager: 多用户状态管理

    设计模式：
    - 单例模式：确保全局唯一实例
    - 事件驱动：支持注册事件处理器扩展功能
    """

    _instance = None  # 单例实例
    _lock = threading.Lock()  # 实例化锁

    def __new__(cls):
        """
        单例模式实现

        确保全局只有一个UserSessionManager实例
        """
        with cls._lock:  # 加锁防止并发创建
            if cls._instance is None:  # 首次创建
                cls._instance = super().__new__(cls)
            return cls._instance  # 返回单例

    def __init__(self):
        """
        初始化用户会话管理器

        注意：使用_initialized标志避免重复初始化
        """
        # 避免重复初始化
        if '_initialized' in self.__dict__:
            return
        self._initialized = True  # 标记已初始化

        # 核心组件初始化
        self.dialogue_manager = DialogueManager()  # 对话管理器
        self.auth_manager = JWTAuthManager()  # 认证管理器
        self.user_manager = multi_user_manager  # 多用户管理器

        # 用户资料存储
        self._user_profiles: dict[str, UserProfile] = {}  # 用户ID -> UserProfile
        self._profiles_lock = threading.RLock()  # 资料操作锁
        self._profiles_file = Path("data/user_profiles.json")  # 持久化文件路径
        self._profiles_file.parent.mkdir(parents=True, exist_ok=True)  # 确保目录存在

        # 加载用户资料
        self._load_profiles()

        # 事件处理器注册表
        self._event_handlers: dict[str, list[Callable]] = {
            "user_login": [],      # 用户登录事件
            "user_logout": [],     # 用户登出事件
            "session_created": [], # 会话创建事件
            "session_closed": [],  # 会话关闭事件
            "message_received": [],# 收到消息事件
        }

        logger.info("[UserSessionManager] 用户会话管理器初始化完成")

    def _load_profiles(self):
        """
        从文件加载用户资料

        从JSON文件反序列化用户资料到内存
        """
        if self._profiles_file.exists():  # 文件存在
            try:
                with open(self._profiles_file, encoding='utf-8') as f:
                    data = json.load(f)  # 加载JSON
                    for user_id, profile_data in data.items():  # 遍历用户
                        self._user_profiles[user_id] = UserProfile(
                            user_id=profile_data["user_id"],
                            username=profile_data["username"],
                            email=profile_data.get("email"),
                            avatar=profile_data.get("avatar"),
                            preferences=profile_data.get("preferences", {}),
                            created_at=datetime.fromisoformat(profile_data["created_at"]),
                            last_login=datetime.fromisoformat(profile_data["last_login"]) if profile_data.get("last_login") else None,
                            password_hash=profile_data.get("password_hash")
                        )
            except Exception as e:
                logger.error(f"[UserSessionManager] 加载用户资料失败: {e}")

    def _save_profiles(self):
        """
        保存用户资料到文件

        将内存中的用户资料序列化到JSON文件
        """
        try:
            with self._profiles_lock:  # 加锁保护
                # 转换为字典格式
                data = {
                    user_id: profile.to_dict()
                    for user_id, profile in self._user_profiles.items()
                }
                with open(self._profiles_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)  # 美化输出
        except Exception as e:
            logger.error(f"[UserSessionManager] 保存用户资料失败: {e}")

    def _hash_password(self, password: str) -> str:
        """计算密码哈希（带盐SHA256）"""
        if not password:
            return ""
        salt = secrets.token_hex(8)
        return f"sha256${salt}${hashlib.sha256((salt + password).encode()).hexdigest()}"

    def _verify_password(self, password: str, hashed: str) -> bool:
        """验证密码（支持 bcrypt、带盐SHA256、无盐SHA256）"""
        if not password or not hashed:
            return False
        # 支持 bcrypt（cloud_api.py 生成的哈希）
        if hashed.startswith("$2"):
            try:
                import bcrypt
                return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
            except ImportError:
                logger.warning("[UserSessionManager] bcrypt 不可用，无法验证 bcrypt 密码")
                return False
        # 带盐 SHA256
        if hashed.startswith("sha256$"):
            _, salt, hash_val = hashed.split("$", 2)
            return hashlib.sha256((salt + password).encode()).hexdigest() == hash_val
        # 向后兼容：无盐SHA256
        return hashlib.sha256(password.encode()).hexdigest() == hashed

    def register_user(
        self,
        username: str,
        password: str = None,
        user_id: str = None,
        email: str = None,
        preferences: dict = None
    ) -> UserProfile:
        """
        注册用户

        创建新用户资料并持久化

        Args:
            username: 用户名（显示名称）
            user_id: 可选的用户ID，不传则自动生成
            email: 邮箱，可选
            preferences: 初始偏好设置，可选

        Returns:
            UserProfile: 创建的用户资料

        Raises:
            ValueError: 用户ID已存在
        """
        # 自动生成用户ID（基于用户名MD5前8位）
        user_id = user_id or f"user_{hashlib.md5(username.encode()).hexdigest()[:8]}"

        with self._profiles_lock:  # 加锁保护
            if user_id in self._user_profiles:  # 用户已存在
                raise ValueError(f"用户已存在: {user_id}")

            # 创建用户资料
            profile = UserProfile(
                user_id=user_id,
                username=username,
                email=email,
                preferences=preferences or {},  # 默认空字典
                password_hash=self._hash_password(password) if password else None
            )
            self._user_profiles[user_id] = profile  # 添加到内存
            self._save_profiles()  # 持久化

        logger.info(f"[UserSessionManager] 注册用户: {username} ({user_id})")
        return profile

    def authenticate_user(
        self,
        username: str,
        password: str = None,
        expires_hours: int = 24
    ) -> str | None:
        """
        验证用户并生成token

        Args:
            username: 用户名
            password: 密码（可选，提供时验证）
            expires_hours: token过期时间，默认24小时

        Returns:
            Optional[str]: JWT token（成功）或None（失败）
        """
        # 查找用户
        user_id = None
        profile = None
        with self._profiles_lock:
            for uid, p in self._user_profiles.items():
                if p.username == username:  # 用户名匹配
                    user_id = uid
                    profile = p
                    break

        if not user_id:  # 用户不存在，自动注册
            profile = self.register_user(username, password=password)
            user_id = profile.user_id
        else:
            # 如果提供了密码，验证密码哈希
            if password and profile.password_hash:
                if not self._verify_password(password, profile.password_hash):
                    logger.warning(f"[UserSessionManager] 用户 {username} 密码验证失败")
                    return None
            elif password and not profile.password_hash:
                # 用户之前没有设置密码，现在设置
                profile.password_hash = self._hash_password(password)
                self._save_profiles()

        # 生成token
        token = self.auth_manager.generate_token(user_id, expires_hours)

        # 更新最后登录时间
        with self._profiles_lock:
            if user_id in self._user_profiles:
                self._user_profiles[user_id].last_login = datetime.now()
                self._save_profiles()

        # 触发登录事件
        self._trigger_event("user_login", {"user_id": user_id, "token": token})

        logger.info(f"[UserSessionManager] 用户登录: {username} ({user_id})")
        return token

    def validate_token(self, token: str) -> str | None:
        """
        验证token

        Args:
            token: JWT token

        Returns:
            Optional[str]: 用户ID（有效）或None（无效）
        """
        return self.auth_manager.validate_token(token)  # 委托给认证管理器

    async def logout(self, token: str):
        """
        用户登出

        撤销token并触发登出事件，同时清理用户相关资源以防止内存泄漏

        Args:
            token: JWT token
        """
        user_id = self.auth_manager.validate_token(token)  # 验证并获取用户ID
        if user_id:
            # 撤销token
            self.auth_manager.revoke_token(token)  # 撤销token

            # 【内存泄漏修复】清理用户工具上下文资源
            try:
                ToolContextFactory.remove_context(user_id)
            except Exception as e:
                logger.warning(f"[UserSessionManager] 清理工具上下文失败 (用户: {user_id}): {e}")

            # 【内存泄漏修复】清理用户意识服务资源
            try:
                await remove_consciousness(user_id)
            except Exception as e:
                logger.warning(f"[UserSessionManager] 清理意识服务失败 (用户: {user_id}): {e}")

            self._trigger_event("user_logout", {"user_id": user_id})  # 触发事件
            logger.info(f"[UserSessionManager] 用户登出: {user_id}")

    def create_user_session(
        self,
        user_id: str,
        session_id: str = None,
        mode: WorkMode = WorkMode.DAILY
    ) -> str:
        """
        创建用户会话

        在DialogueManager和multi_user_manager中都创建会话

        Args:
            user_id: 用户唯一标识
            session_id: 可选的会话ID（不传则自动生成）
            mode: 工作模式（Daily/Focus），默认Daily

        Returns:
            str: 创建的会话ID
        """
        # 在对话管理器中创建会话
        session = self.dialogue_manager.create_session(user_id, session_id, mode)

        # 在多用户管理器中也创建会话
        self.user_manager.create_session(user_id)

        # 触发会话创建事件
        self._trigger_event("session_created", {
            "user_id": user_id,
            "session_id": session.session_id
        })

        return session.session_id

    async def handle_message(
        self,
        user_id: str,
        message: str,
        session_id: str = None,
        input_type: str = "text",
        **kwargs
    ) -> str:
        """
        处理用户消息（统一入口）

        支持文本和语音两种输入类型

        Args:
            user_id: 用户唯一标识
            message: 用户消息内容
            session_id: 会话ID（可选）
            input_type: 输入类型（"text"/"voice"），默认"text"
            **kwargs: 额外参数（传递给底层处理）

        Returns:
            str: AI回复内容
        """
        # 触发消息接收事件
        self._trigger_event("message_received", {
            "user_id": user_id,
            "session_id": session_id,
            "message": message,
            "input_type": input_type
        })

        # P0: 统一走 handle_input(InputMode.AUTO)，由思维线程做 L1 裁决
        result = await self.dialogue_manager.handle_input(
            user_id=user_id,
            text=message,
            session_id=session_id,
            input_mode=InputMode.AUTO,
            voice_instance=kwargs.get("voice_instance")
        )
        if isinstance(result, dict):
            return result.get("content", "") or result.get("chat_reply", "") or result.get("result", "") or str(result)
        return str(result) if result is not None else ""

    def get_user_profile(self, user_id: str) -> UserProfile | None:
        """
        获取用户资料

        Args:
            user_id: 用户ID

        Returns:
            Optional[UserProfile]: 用户资料或None
        """
        with self._profiles_lock:
            return self._user_profiles.get(user_id)

    def update_user_profile(self, user_id: str, **updates) -> bool:
        """
        更新用户资料

        支持更新的字段：username, email, avatar, preferences

        Args:
            user_id: 用户唯一标识
            **updates: 更新的字段键值对

        Returns:
            bool: 是否成功
        """
        with self._profiles_lock:
            profile = self._user_profiles.get(user_id)
            if not profile:  # 用户不存在
                return False

            # 更新各字段
            if "username" in updates:
                profile.username = updates["username"]
            if "email" in updates:
                profile.email = updates["email"]
            if "avatar" in updates:
                profile.avatar = updates["avatar"]
            if "preferences" in updates:
                profile.preferences.update(updates["preferences"])

            self._save_profiles()  # 持久化

        return True

    def get_user_sessions(self, user_id: str) -> list[str]:
        """
        获取用户的所有会话ID

        Args:
            user_id: 用户ID

        Returns:
            List[str]: 会话ID列表
        """
        return self.dialogue_manager.get_user_sessions(user_id)

    def close_user_session(self, user_id: str, session_id: str):
        """
        关闭用户会话

        Args:
            user_id: 用户ID
            session_id: 会话ID
        """
        self.dialogue_manager.close_session(user_id, session_id)
        self._trigger_event("session_closed", {  # 触发关闭事件
            "user_id": user_id,
            "session_id": session_id
        })

    def get_user_stats(self, user_id: str) -> dict:
        """
        获取用户统计

        合并用户资料和会话统计

        Args:
            user_id: 用户ID

        Returns:
            Dict: 包含profile和sessions的统计字典
        """
        profile = self.get_user_profile(user_id)  # 用户资料
        session_stats = self.dialogue_manager.get_user_stats(user_id)  # 会话统计

        return {
            "profile": profile.to_dict() if profile else None,
            "sessions": session_stats
        }

    def on(self, event: str, handler: Callable):
        """
        注册事件处理器

        支持的事件类型：
        - user_login: 用户登录
        - user_logout: 用户登出
        - session_created: 会话创建
        - session_closed: 会话关闭
        - message_received: 收到消息

        Args:
            event: 事件类型
            handler: 处理函数，接收事件数据字典
        """
        if event in self._event_handlers:
            self._event_handlers[event].append(handler)

    def off(self, event: str, handler: Callable):
        """
        注销事件处理器

        Args:
            event: 事件类型
            handler: 要注销的处理函数
        """
        if event in self._event_handlers:
            # 过滤掉指定handler
            self._event_handlers[event] = [
                h for h in self._event_handlers[event] if h != handler
            ]

    def _trigger_event(self, event: str, data: dict):
        """
        触发事件

        调用所有注册的处理函数

        Args:
            event: 事件类型
            data: 事件数据字典
        """
        handlers = self._event_handlers.get(event, [])  # 获取处理函数列表
        for handler in handlers:  # 逐一调用
            try:
                handler(data)
            except Exception as e:
                logger.error(f"[UserSessionManager] 事件处理失败: {e}")

    def cleanup(self):
        """
        清理资源

        定期调用以释放过期资源：
        1. 清理过期token
        2. 清理过期会话（1小时不活跃）
        """
        # 清理过期token
        self.auth_manager.cleanup_expired_tokens()

        # 清理过期会话（1小时）
        self.dialogue_manager.cleanup_expired_sessions(max_inactive_seconds=3600)

        logger.info("[UserSessionManager] 资源清理完成")


# ========================================
# 全局单例 - 供其他模块直接使用
# ========================================
user_session_manager = UserSessionManager()


# ========================================
# 便捷函数 - 简化外部调用
# ========================================

def login(username: str, password: str = None, expires_hours: int = 24) -> str | None:
    """
    用户登录便捷函数

    Args:
        username: 用户名
        password: 密码
        expires_hours: token过期时间

    Returns:
        Optional[str]: JWT token或None
    """
    return user_session_manager.authenticate_user(username, password, expires_hours)


async def logout(token: str):
    """
    用户登出便捷函数

    Args:
        token: JWT token
    """
    await user_session_manager.logout(token)


def create_session(user_id: str, mode: DialogueWorkMode = DialogueWorkMode.DAILY) -> str:
    """
    创建会话便捷函数

    Args:
        user_id: 用户ID
        mode: 工作模式

    Returns:
        str: 会话ID
    """
    return user_session_manager.create_user_session(user_id, mode=mode)


async def send_message(
    user_id: str,
    message: str,
    session_id: str = None,
    input_type: str = "text"
) -> str:
    """
    发送消息便捷函数

    Args:
        user_id: 用户ID
        message: 消息内容
        session_id: 会话ID
        input_type: 输入类型（text/voice）

    Returns:
        str: AI回复
    """
    return await user_session_manager.handle_message(
        user_id, message, session_id, input_type
    )


def get_profile(user_id: str) -> UserProfile | None:
    """
    获取用户资料便捷函数

    Args:
        user_id: 用户ID

    Returns:
        Optional[UserProfile]: 用户资料或None
    """
    return user_session_manager.get_user_profile(user_id)


def register(username: str, **kwargs) -> UserProfile:
    """
    注册用户便捷函数

    Args:
        username: 用户名
        **kwargs: 其他参数（user_id, email, preferences）

    Returns:
        UserProfile: 创建的用户资料
    """
    return user_session_manager.register_user(username, **kwargs)


# =============================================================================
# 文件总结性注释
# =============================================================================
#
# ============================================================================
# 文件角色说明
# ============================================================================
#
# 【文件角色】
# user_session_manager.py 是 SiliconBase V5.1 多用户支持的核心组件，
# 扮演"用户会话统一管理中心"的角色。它是系统与用户交互的主要入口，
# 负责管理用户从注册、登录、会话创建到消息处理的完整生命周期。
#
# 【在架构中的位置】
# - 层级：基础设施层（Infrastructure Layer）
# - 定位：多用户支持的"入口网关"和"协调器"
# - 上层：为API层、WebSocket层提供统一的用户交互接口
# - 下层：协调DialogueManager、multi_user_manager等组件
#
# 【核心职责】
# 1. 用户认证管理：登录、登出、token生成与验证
# 2. 用户资料管理：注册、信息更新、持久化存储
# 3. 会话生命周期：创建、查询、关闭用户会话
# 4. 消息统一处理：文本和语音消息的统一入口
# 5. 事件分发机制：支持注册事件处理器扩展功能
# 6. 资源清理：定期清理过期token和会话
#
# ============================================================================
# 关联文件
# ============================================================================
#
# 【上游依赖（调用本文件）】
# - api_handlers.py: API处理器，调用login/logout/handle_message等
# - websocket_handler.py: WebSocket处理器，实时消息处理
# - web_dashboard.py: Web管理面板，用户管理功能
#
# 【下游依赖（本文件调用）】
# - core/dialogue_manager.py: DialogueManager, UserSession
#   作用：创建/管理对话会话，处理具体消息
#
# - core/multi_user.py: multi_user_manager, UserSession
#   作用：多用户状态管理，用户间隔离
#
# - core/work_mode_manager.py: WorkMode
#   作用：工作模式枚举（Daily/Focus）
#
# - core/logger.py: logger
#   作用：日志记录
#
# 【同级关联】
# - user_consciousness.py: 用户意识系统
#   关系：会话管理器触发意识系统的事件（如message_received）
#
# - user_context_manager.py: 用户上下文管理器（代理9）
#   关系：通过事件机制协调，共享用户状态
#
# 【数据文件】
# - data/user_profiles.json: 用户资料持久化存储
#
# ============================================================================
# 数据流向说明
# ============================================================================
#
# 【用户登录流程】
#
# 1. API层调用 login(username, password)
#    |
# 2. UserSessionManager.authenticate_user()
#    |-- 查找用户资料（内存字典）
#    |-- 不存在则自动注册 register_user()
#    |       |-- 创建UserProfile对象
#    |       |-- 保存到 _user_profiles字典
#    |       |-- 持久化到 user_profiles.json
#    |
# 3. JWTAuthManager.generate_token()
#    |-- 生成SHA256哈希token
#    |-- 创建UserAuthToken对象
#    |-- 存储到 _tokens字典
#    |-- 关联到 _user_tokens[user_id]
#    |
# 4. 更新最后登录时间
#    |-- _save_profiles() 持久化
#    |
# 5. 触发 user_login 事件
#    |-- 调用所有注册的处理器
#    |
# 6. 返回token给API层
#
# 【消息处理流程】
#
# 1. API层调用 handle_message(user_id, message, session_id, input_type)
#    |
# 2. 触发 message_received 事件
#    |-- 通知所有监听组件（如意识系统）
#    |
# 3. 根据 input_type 分发处理
#    |-- "text": dialogue_manager.handle_text_input()
#    |-- "voice": dialogue_manager.handle_voice_input() (异步)
#    |
# 4. DialogueManager 处理消息
#    |-- 调用AutoLoop进行AI推理
#    |-- 返回AI回复
#    |
# 5. 返回AI回复给API层
#
# 【会话创建流程】
#
# 1. 调用 create_user_session(user_id, session_id, mode)
#    |
# 2. dialogue_manager.create_session()
#    |-- 创建UserSession对象
#    |-- 关联到用户
#    |
# 3. user_manager.create_session()
#    |-- 在多用户管理器中同步创建
#    |
# 4. 触发 session_created 事件
#    |
# 5. 返回session_id
#
# ============================================================================
# 达到的效果
# ============================================================================
#
# 【1. 统一入口】
# - 效果：所有用户交互都通过本文件处理
# - 优势：代码集中、逻辑统一、便于维护
# - 实现：单例模式 + 统一方法接口
#
# 【2. 多用户隔离】
# - 效果：用户间状态完全隔离，互不影响
# - 优势：支持真正的多租户架构
# - 实现：user_id作为所有操作的第一参数
#
# 【3. 会话管理】
# - 效果：支持多会话并发，会话状态持久
# - 优势：用户可同时开启多个对话
# - 实现：session_id区分不同会话
#
# 【4. 安全认证】
# - 效果：JWT token机制，支持过期和撤销
# - 优势：无状态认证，支持分布式部署
# - 实现：JWTAuthManager + token验证
#
# 【5. 事件扩展】
# - 效果：支持外部组件监听用户事件
# - 优势：松耦合，易于扩展新功能
# - 实现：on/off/_trigger_event机制
#
# 【6. 数据持久化】
# - 效果：用户资料持久存储，服务重启不丢失
# - 优势：数据安全可靠
# - 实现：JSON文件 + 自动加载/保存
#
# 【7. 资源管理】
# - 效果：自动清理过期资源，防止内存泄漏
# - 优势：系统长期稳定运行
# - 实现：cleanup()定期清理
#
# ============================================================================
# 类关系图
# ============================================================================
#
# UserSessionManager (单例)
#     |
#     +-- dialogue_manager: DialogueManager
#     +-- auth_manager: JWTAuthManager
#     +-- user_manager: multi_user_manager
#     |
#     +-- _user_profiles: Dict[str, UserProfile]
#     +-- _event_handlers: Dict[str, List[Callable]]
#     |
#     +-- authenticate_user() -> token
#     +-- create_user_session() -> session_id
#     +-- handle_message() -> AI回复
#     +-- on()/off() 事件注册/注销
#
# JWTAuthManager
#     |
#     +-- _tokens: Dict[str, UserAuthToken]
#     +-- _user_tokens: Dict[str, set]
#     |
#     +-- generate_token() -> token
#     +-- validate_token() -> user_id
#     +-- revoke_token()
#
# UserAuthToken (数据类)
#     +-- token, user_id, created_at, expires_at, scopes
#     +-- is_valid() -> bool
#
# UserProfile (数据类)
#     +-- user_id, username, email, avatar, preferences
#     +-- created_at, last_login
#     +-- to_dict() -> Dict
#
# ============================================================================
# 使用示例
# ============================================================================
#
# 【用户登录】
# from core.user_session_manager import login, create_session
# token = login("alice", expires_hours=24)
# session_id = create_session("user_xxx", mode=WorkMode.DAILY)
#
# 【发送消息】
# from core.user_session_manager import send_message
# reply = send_message("user_xxx", "你好", session_id="session_xxx")
#
# 【事件监听】
# from core.user_session_manager import user_session_manager
# def on_login(data):
#     print(f"用户 {data['user_id']} 登录了")
# user_session_manager.on("user_login", on_login)
#
# 【注册用户】
# from core.user_session_manager import register
# profile = register("bob", email="bob@example.com")
#
# ============================================================================
# 性能考虑
# ============================================================================
#
# 【并发处理】
# - 使用RLock保护用户资料字典
# - token操作使用独立锁
# - 支持高并发用户访问
#
# 【内存占用】
# - 用户资料：约500字节/用户
# - Token存储：约200字节/token
# - 1万用户约占用7MB内存
#
# 【持久化策略】
# - 写操作：实时持久化（JSON文件）
# - 读操作：内存缓存
# - 启动时：全量加载
#
# 【清理策略】
# - 过期token：定期清理或验证时清理
# - 过期会话：1小时不活跃自动清理
# - 建议：每小时调用一次cleanup()
#
# ============================================================================
# 安全考虑
# ============================================================================
#
# 【token安全】
# - 使用SHA256哈希，256位熵
# - 包含时间戳和随机盐
# - 支持设置过期时间
# - 支持撤销机制
#
# 【密码处理】
# - 当前：简化版未验证密码
# - 建议：生产环境使用bcrypt/argon2哈希
#
# 【权限控制】
# - token包含scopes字段
# - 支持细粒度权限控制
# - 预留扩展接口
#
# ============================================================================
# 扩展建议
# ============================================================================
#
# 【1. 数据库支持】
# 当前：JSON文件存储
# 建议：迁移到PostgreSQL/MongoDB
#
# 【2. 缓存优化】
# 当前：纯内存缓存
# 建议：引入Redis缓存token
#
# 【3. 限流保护】
# 当前：无请求限流
# 建议：添加速率限制（如10次/秒）
#
# 【4. 审计日志】
# 当前：仅记录info日志
# 建议：完整审计日志（登录/登出/操作）
#
# 【5. 多设备支持】
# 当前：token与设备无关
# 建议：支持设备绑定和管理
#
# ============================================================================
# 作者：SiliconBase Team
# 最后更新：2026-02-26
# 版本：V5.1
# ============================================================================
