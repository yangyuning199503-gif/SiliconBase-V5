#!/usr/bin/env python3
"""
对话管理器 - 支持多用户会话隔离 + 数据库存储
SiliconBase V5.1 Phase 2 Week 3 - 自动存储对话到session_messages

功能：
- 每个用户拥有独立的会话空间
- 会话完全隔离，用户A的会话对用户B不可见
- 向后兼容：旧代码可通过 user_id="default" 继续使用
- 自动持久化：对话消息自动存储到PostgreSQL数据库
"""
# ============================================
# 模块说明
# ============================================
# 本模块是 SiliconBase V5.1 多用户架构的核心实现
# 核心职责：管理用户会话生命周期、处理文本/语音输入、维护聊天历史
# 关键特性：完全隔离的多用户支持 + 向后兼容的单用户模式 + 数据库持久化
# ============================================

import asyncio  # 导入异步IO库，用于语音输入的异步处理
import threading  # 导入线程库，用于会话锁和单例锁
import time  # 导入时间库，用于PTM时间戳记录
import uuid  # 导入UUID库，用于生成唯一会话ID
from dataclasses import dataclass, field  # 导入数据类装饰器，用于定义UserSession
from datetime import datetime  # 导入日期时间类，用于记录会话时间戳
from enum import Enum  # 导入枚举基类，用于定义输入模式
from typing import Any  # 导入类型提示工具

from core.consciousness.sovereignty_types import ActionResult  # P0 四层架构执行结果回流
from core.diagnostic import safe_create_task  # 安全创建异步任务
from core.sync.event_bus import event_bus  # 【ExperienceBus】事件总线

# 延迟导入避免循环依赖
# 这些模块在方法内按需导入
logger = None                                  # 全局logger变量，初始为None，延迟初始化


class InputMode(Enum):
    """
    四种输入方式定义

    AUTO: 自动模式 - AI自主判断输入意图（聊天/任务/对齐），推荐默认使用
    TEXT: 文本输入 - 直接触发任务（可清晰发布任务）
    VOICE_WAKE: 语音唤醒 - 唤醒后进入聊天对齐需求
    VOICE_FRONTEND: 前端语音 - 点击录音，聊天对齐需求
    """
    # 定义四种用户输入方式，影响后续处理流程
    AUTO = "auto"                              # 【新增】自动模式：AI自主判断意图
    TEXT = "text"                              # 文本输入模式：用户直接输入文字
    VOICE_WAKE = "voice_wake"                  # 语音唤醒模式：通过唤醒词触发语音交互
    VOICE_FRONTEND = "voice_frontend"          # 前端语音模式：通过界面按钮触发语音输入


# ═══════════════════════════════════════════════════════════════
# 【演示学习系统集成】意图识别模式
# ═══════════════════════════════════════════════════════════════

class DemonstrationIntent(Enum):
    """演示学习相关意图类型"""
    START_DEMONSTRATION = "start_demonstration"    # 开始演示
    STOP_DEMONSTRATION = "stop_demonstration"      # 结束演示
    USE_LEARNED_PROCEDURE = "use_learned_procedure"  # 使用已学习的流程
    UNKNOWN = "unknown"                            # 未知意图


# 演示学习意图识别关键词
DEMONSTRATION_KEYWORDS = {
    DemonstrationIntent.START_DEMONSTRATION: [
        # 开始演示
        "我来演示", "我来做", "你看着", "我操作给你看",
        "我来教你", "看我怎么做", "让我演示", "我演示一下",
        "watch me", "let me demonstrate", "i'll show you",
        # 接管控制
        "让我来", "交给我", "我自己来", "暂停AI", "暂停执行",
    ],
    DemonstrationIntent.STOP_DEMONSTRATION: [
        # 结束演示
        "演示完成", "我做好了", "学完了", "录制完成", "停止录制",
        "我操作完了", "演示结束", "学会了", "保存流程",
        "done demonstrating", "finish recording", "stop recording",
        "i'm done", "that's it", "complete",
    ],
    DemonstrationIntent.USE_LEARNED_PROCEDURE: [
        # 使用已学习的流程
        "用之前的办法", "按上次的方法", "用学习到的", "执行保存的流程",
        "用之前的流程", "上次怎么做的", "按之前的方式", "复用流程",
        "use previous method", "use learned procedure", "run saved workflow",
        "like before", "as last time", "use the procedure",
    ]
}

def _get_logger():
    """延迟获取logger实例"""
    # 使用延迟导入避免初始化时的循环依赖问题
    global logger                              # 声明使用全局logger变量
    if logger is None:
        # 如果logger尚未初始化，从core.logger导入
        from core.logger import logger as _logger
        logger = _logger                       # 将导入的logger赋值给全局变量
    return logger                              # 返回logger实例


# 【修复】导入统一的WorkMode，不重复定义
# 之前版本在此处重复定义了WorkMode枚举，导致多处定义不一致
# 【Agent-005 修复】导入 global_state 用于统一获取 voice 实例
import contextlib

from core import global_state
from core.exceptions import AIConnectionError

# 【Phase 2 Week 4】导入目标对齐引擎
from core.intent.goal_alignment_engine import AlignmentStatus, GoalAlignmentEngine, get_goal_alignment_engine
from core.memory.memory_auto_trigger import MemoryStoreError

# 【语音降级修复】导入异常类用于区分系统级异常和语音特有异常
from core.memory.memory_service import MemoryRetrievalError
from core.mode.work_mode_manager import WorkMode  # 从工作模式管理器导入统一的WorkMode枚举
from core.procedure_learning import get_procedure_library, get_task_coordinator

# 【Phase 2 Week 3】导入SessionManager用于数据库存储
from core.session.session_manager import get_session_manager

# 【演示学习系统集成】导入任务协调器和流程库
from voice.voice_prompts import DialogueManagerAnnouncements

# 为向后兼容保留别名
# 旧代码可能使用DialogueWorkMode，此处保持兼容
DialogueWorkMode = WorkMode                    # 创建别名，保持向后兼容


@dataclass                                     # 使用数据类装饰器自动生成__init__等方法
class UserSession:
    """用户会话 - 完全隔离的会话数据"""
    # 数据类：封装单个用户的会话数据
    # 每个用户可以有多个会话，每个会话完全隔离

    session_id: str                            # 会话唯一标识符（UUID格式）
    user_id: str                               # 用户唯一标识符
    chat_history: list[dict] = field(default_factory=list)  # 聊天历史记录列表
    created_at: datetime = field(default_factory=datetime.now)  # 会话创建时间
    last_active: datetime = field(default_factory=datetime.now)  # 最后活跃时间
    mode: WorkMode = WorkMode.DAILY            # 当前工作模式（Daily/Focus）
    metadata: dict = field(default_factory=dict)  # 扩展元数据字典

    # 【Phase 2 Week 3】数据库session_id，用于关联数据库中的session记录
    db_session_id: str | None = None

    def __post_init__(self):
        """验证 session_id 和 user_id 类型，防止 slice 等不可哈希类型"""
        # P0修复：防御性编程，处理类型异常
        # 某些边界情况下可能传入slice对象，导致后续字典操作失败

        if not isinstance(self.session_id, str):
            # session_id不是字符串类型时的处理逻辑
            _get_logger().error(
                f"[UserSession] session_id 类型异常: {type(self.session_id)}, "
                f"值: {repr(self.session_id)}, 尝试转换为字符串"
            )
            # 如果是 slice 对象，生成一个新的 UUID
            if isinstance(self.session_id, slice):
                self.session_id = str(uuid.uuid4())
            else:
                # 其他类型尝试转换为字符串，如果为空则生成UUID
                self.session_id = str(self.session_id) if self.session_id else str(uuid.uuid4())

        if not isinstance(self.user_id, str):
            # user_id不是字符串类型时的处理逻辑
            _get_logger().error(
                f"[UserSession] user_id 类型异常: {type(self.user_id)}, "
                f"值: {repr(self.user_id)}, 尝试转换为字符串"
            )
            # 转换为字符串或设为默认值
            self.user_id = str(self.user_id) if self.user_id else "default"

        # 【2026-03-10 修复】确保chat_history不为None
        if self.chat_history is None:
            self.chat_history = []

    def to_dict(self) -> dict:
        """序列化为字典"""
        # 将UserSession对象转换为字典，便于JSON序列化存储
        return {
            "session_id": self.session_id,      # 会话ID
            "user_id": self.user_id,            # 用户ID
            "chat_history": self.chat_history,  # 聊天历史
            "created_at": self.created_at.isoformat(),  # ISO格式创建时间
            "last_active": self.last_active.isoformat(),  # ISO格式最后活跃时间
            "mode": self.mode.value,            # 工作模式值（字符串）
            "metadata": self.metadata,          # 元数据
            "db_session_id": self.db_session_id  # 【Phase 2 Week 3】数据库session_id
        }

    @classmethod                                 # 类方法装饰器
    def from_dict(cls, data: dict) -> "UserSession":
        """从字典反序列化，带有严格的类型检查"""
        # 从字典恢复UserSession对象，带防御性类型检查

        # 【修复】防御性编程：确保 session_id 和 user_id 是字符串类型
        session_id = data.get("session_id")      # 获取session_id
        user_id = data.get("user_id")            # 获取user_id

        # 记录异常类型以便调试
        if not isinstance(session_id, str):
            _get_logger().warning(
                f"[UserSession.from_dict] session_id 类型异常: {type(session_id)}, "
                f"值: {repr(session_id)}, 将生成新的 UUID"
            )
            session_id = str(uuid.uuid4())       # 类型异常时生成新UUID

        if not isinstance(user_id, str):
            _get_logger().warning(
                f"[UserSession.from_dict] user_id 类型异常: {type(user_id)}, "
                f"值: {repr(user_id)}, 将使用默认值"
            )
            user_id = str(user_id) if user_id else "default"  # 转换或使用默认值

        # 【Phase 2 Week 3】读取数据库session_id
        db_session_id = data.get("db_session_id")

        return cls(
            session_id=session_id,               # 使用处理后的session_id
            user_id=user_id,                     # 使用处理后的user_id
            chat_history=data.get("chat_history", []),  # 聊天历史，默认为空列表
            created_at=datetime.fromisoformat(data["created_at"]),  # 解析ISO时间
            last_active=datetime.fromisoformat(data["last_active"]),  # 解析ISO时间
            mode=WorkMode(data.get("mode", "daily")),  # 解析工作模式，默认为daily
            metadata=data.get("metadata", {}),   # 元数据，默认为空字典
            db_session_id=db_session_id          # 【Phase 2 Week 3】数据库session_id
        )


class PTTManager:
    """
    PTT免唤醒管理器（按用户隔离）

    每个用户拥有独立的PTT状态，互不干扰。
    """
    # PTT = Push To Talk（按键通话）
    # 管理每个用户的PTT状态，用于免唤醒连续语音交互

    def __init__(self):
        """初始化PTT管理器"""
        self._ptt_states: dict[str, bool] = {}   # user_id -> PTT状态（True=激活）
        self._ptt_timestamps: dict[str, float] = {}  # user_id -> 最后激活时间戳
        self._lock = threading.RLock()           # 线程锁，保护状态访问

    def is_ptt_active(self, user_id: str) -> bool:
        """检查用户的PTT状态"""
        with self._lock:                         # 获取锁保证线程安全
            return self._ptt_states.get(user_id, False)  # 返回用户PTT状态，默认False

    def set_ptt_active(self, user_id: str, active: bool):
        """设置用户的PTT状态"""
        with self._lock:                         # 获取锁保证线程安全
            self._ptt_states[user_id] = active   # 设置PTT状态
            if active:
                # 如果激活PTT，记录当前时间戳
                self._ptt_timestamps[user_id] = time.time()
        # 【ExperienceBus】PTT状态切换
        try:
            event_bus.emit("dialogue:ptt_toggled", {
                "user_id": user_id,
                "active": active,
                "timestamp": time.time(),
            })
        except Exception as e:
            logger.error(f"[DialogueManager] 保存PTT状态失败: {e}", exc_info=True)

    def toggle_ptt(self, user_id: str) -> bool:
        """切换用户的PTT状态，返回新状态"""
        with self._lock:                         # 获取锁保证线程安全
            current = self._ptt_states.get(user_id, False)  # 获取当前状态
            new_state = not current              # 切换状态
            self._ptt_states[user_id] = new_state  # 保存新状态
            if new_state:
                # 如果切换到激活状态，更新时间戳
                self._ptt_timestamps[user_id] = time.time()
            return new_state                     # 返回新状态

    def get_ptt_duration(self, user_id: str) -> float:
        """获取用户PTT已激活的时长（秒）"""
        with self._lock:                         # 获取锁保证线程安全
            if not self._ptt_states.get(user_id, False):
                return 0.0                       # PTT未激活，返回0
            last_activation = self._ptt_timestamps.get(user_id, 0)  # 获取激活时间
            # 计算持续时间，如果时间戳有效
            return time.time() - last_activation if last_activation > 0 else 0.0

    def reset_all(self):
        """重置所有用户的PTT状态（系统级操作）"""
        with self._lock:                         # 获取锁保证线程安全
            self._ptt_states.clear()             # 清空所有PTT状态
            self._ptt_timestamps.clear()         # 清空所有时间戳


class DialogueManager:
    """
    支持多用户的对话管理器（Phase 2 Week 3 - 支持数据库存储）

    核心特性：
    1. 完全隔离：用户A的会话对用户B完全不可见
    2. 向后兼容：旧代码可通过 user_id="default" 继续使用
    3. 高性能：支持同时处理1000+用户的对话
    4. 用户级并发控制：一个用户同时只能有一个AgentLoop运行
    5. 数据持久化：对话消息自动存储到PostgreSQL数据库
    """
    # 对话管理器是系统的核心组件，采用单例模式
    # 管理所有用户的会话、处理输入、维护状态

    _instance = None                             # 单例实例引用
    _lock = threading.Lock()                     # 类级别锁，用于单例创建

    def __new__(cls):
        """单例模式保证全局唯一"""
        with cls._lock:                          # 获取类锁
            if cls._instance is None:
                # 如果实例不存在，创建新实例
                cls._instance = super().__new__(cls)
            return cls._instance                 # 返回单例实例

    def __init__(self):
        """初始化对话管理器 - [修复] 添加 voice 实例强制检查"""
        # 避免重复初始化（单例模式常见模式）
        if '_initialized' in self.__dict__:
            return                               # 如果已初始化，直接返回
        self._initialized = True                 # 标记为已初始化

        # 用户会话存储: user_id -> {session_id -> UserSession}
        # 二级字典结构：第一层按user_id分组，第二层按session_id存储会话
        self._user_sessions: dict[str, dict[str, UserSession]] = {}

        # PTT管理器（用户隔离）
        self.ptt_manager = PTTManager()          # 创建PTT管理器实例

        # 语音接口（全局）
        self.loop = None                         # 事件循环引用（预留）
        self.voice = None                        # 语音接口实例

        # 延迟初始化这些组件避免循环导入
        # 使用@property实现延迟加载
        self._social_reasoning = None            # 社会推理引擎缓存
        self._intent_parser = None               # 意图解析器缓存
        self._command_parser = None              # 命令解析器缓存
        self._user_manager = None                # 用户管理器缓存

        # 【Phase 2 Week 3】SessionManager缓存
        self._session_manager = None

        # 【Phase 2 Week 4】目标对齐引擎
        self._alignment_engine: GoalAlignmentEngine | None = None

        # 线程锁
        self._sessions_lock = threading.RLock()  # 会话操作锁

        # [修复] 启动时检查语音实例状态
        self._voice_check_done = False           # 标记语音检查是否已完成

        # 【用户级并发控制】用户活动循环管理
        # 用于防止一个用户同时运行多个AgentLoop
        self._active_loops: dict[str, threading.Event] = {}  # user_id -> stop_event
        self._loop_lock = threading.Lock()         # 保护_active_loops的锁

        # 【干预支持】跟踪用户当前活跃任务ID
        self._current_tasks: dict[str, str] = {}   # user_id -> task_id

        # 【后台任务并发】跟踪用户后台运行的 asyncio.Task
        self._user_background_tasks: dict[str, asyncio.Task] = {}  # user_id -> asyncio.Task
        self._user_task_snapshots: dict[str, dict] = {}  # user_id -> 任务状态快照
        self._snapshot_lock = threading.Lock()       # 快照读写锁（线程安全）
        self._pause_requests: dict[str, bool] = {}  # user_id -> 是否请求暂停（显式"暂停"指令）
        self._interruption_requests: dict[str, str] = {}  # user_id -> 插话文本（用户插话时暂存）
        self._last_paused_task_id: dict[str, str] = {}  # user_id -> 最近暂停的任务ID

        # 【BUG-5修复】输入队列互斥锁，防止语音和文本输入冲突
        # 语音和文本输入共享同一个锁，确保同一时刻只有一个输入被处理
        self._input_lock = asyncio.Lock()          # 输入处理互斥锁（异步版）
        _get_logger().info("[DialogueManager] 输入队列互斥锁已初始化")

        _get_logger().info("[DialogueManager] 多用户对话管理器初始化完成（含用户级并发控制+数据库存储）")

    # =========================================================================
    # 【Phase 2 Week 3】新增：SessionManager相关方法
    # =========================================================================

    @property
    def session_manager(self):
        """延迟加载SessionManager"""
        if self._session_manager is None:
            self._session_manager = get_session_manager()
        return self._session_manager

    def _generate_session_title(self, text: str, max_length: int = 50) -> str:
        """
        从用户输入生成会话标题

        Args:
            text: 用户输入文本
            max_length: 标题最大长度

        Returns:
            str: 生成的标题
        """
        # 清理文本，去除多余空白
        cleaned_text = text.strip()

        # 如果文本为空，返回默认标题
        if not cleaned_text:
            return f"新对话 {datetime.now().strftime('%m-%d %H:%M')}"

        # 取前max_length个字符作为标题
        if len(cleaned_text) <= max_length:
            return cleaned_text
        else:
            return cleaned_text[:max_length] + "..."

    async def _get_or_create_db_session(
        self,
        user_id: str,
        session: UserSession,
        mode: str = "daily",
        title: str | None = None
    ) -> tuple[str, bool]:
        """
        获取或创建数据库session

        Args:
            user_id: 用户ID
            session: 内存中的UserSession对象
            mode: 会话模式 (daily/focus)
            title: 会话标题，None则自动生成

        Returns:
            Tuple[str, bool]: (db_session_id, is_new_created) 数据库session_id和是否新创建
        """
        # 如果已有数据库session_id，直接返回
        if session.db_session_id:
            try:
                # 验证session是否还存在（原生 async）
                existing_session = await self.session_manager.get_session(session.db_session_id)
                if existing_session:
                    return session.db_session_id, False
                else:
                    # session已被删除，清除缓存的ID
                    _get_logger().warning(
                        f"[DialogueManager] 数据库session不存在，将重新创建: {session.db_session_id}"
                    )
                    session.db_session_id = None
            except Exception as e:
                _get_logger().error(f"[DialogueManager] 验证session失败: {e}")
                session.db_session_id = None

        # 生成标题
        if title is None:
            # 如果有聊天历史，使用第一条用户消息作为标题
            if session.chat_history:
                first_user_msg = None
                for msg in session.chat_history:
                    if msg.get("role") == "user":
                        first_user_msg = msg.get("content", "")
                        break
                if first_user_msg:
                    title = self._generate_session_title(first_user_msg)
                else:
                    title = f"新对话 {datetime.now().strftime('%m-%d %H:%M')}"
            else:
                title = f"新对话 {datetime.now().strftime('%m-%d %H:%M')}"

        # 转换mode为SessionMode
        session_mode = mode if mode in ["daily", "focus", "analysis", "debug"] else "daily"

        try:
            # 创建新session（原生 async）
            db_session = await self.session_manager.create_session(
                user_id=user_id,
                title=title,
                mode=session_mode,
                initial_context={
                    "memory_session_id": session.session_id,
                    "source": "dialogue_manager_auto_create"
                }
            )

            # 保存到内存session
            session.db_session_id = db_session.id

            _get_logger().info(
                f"[DialogueManager] 数据库session创建成功: {db_session.id}, "
                f"user_id={user_id}, title={title}"
            )

            return db_session.id, True

        except Exception as e:
            _get_logger().error(f"[DialogueManager] 创建数据库session失败: {e}", exc_info=True)
            return None, False

    async def _store_message_with_retry_async(
        self,
        session_id: str,
        role: str,
        content: str,
        max_retries: int = 3,
        **kwargs
    ) -> str | None:
        """异步带重试机制的消息存储"""
        import asyncio
        for attempt in range(max_retries):
            try:
                message_id = await self.session_manager.add_message(
                    session_id=session_id,
                    role=role,
                    content=content,
                    **kwargs
                )
                if message_id:
                    return message_id
            except Exception as e:
                _get_logger().warning(
                    f"[DialogueManager] 异步存储消息失败(尝试{attempt+1}/{max_retries}): {e}"
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(0.1 * (attempt + 1))
        return None

    async def _store_user_message_async(
        self,
        session: UserSession,
        text: str,
        metadata: dict = None
    ) -> str | None:
        """异步存储用户消息到数据库"""
        kwargs = {"metadata": metadata or {}}
        if hasattr(session, 'user_id') and session.user_id:
            kwargs["metadata"]["user_id"] = session.user_id
        return await self._store_message_with_retry_async(
            session_id=session.db_session_id,
            role="user",
            content=text,
            **kwargs
        )

    async def _store_assistant_message_async(
        self,
        session: UserSession,
        content: str,
        thinking: str = None,
        memory_id: str = None,
        metadata: dict = None
    ) -> str | None:
        """异步存储AI回复消息到数据库"""
        kwargs = {"metadata": metadata or {}}
        if thinking:
            kwargs["thinking"] = thinking
        if memory_id:
            kwargs["memory_id"] = memory_id
        return await self._store_message_with_retry_async(
            session_id=session.db_session_id,
            role="assistant",
            content=content,
            **kwargs
        )

    def _notify_voice_failure_and_fallback(self, session_id: str, user_id: str):
        """
        【P0-003新增】通知用户语音处理失败，已切换到文本模式

        Args:
            session_id: 会话ID
            user_id: 用户ID
        """
        notification_msg = "语音处理遇到问题，已自动切换到文本模式。"

        try:
            # 记录降级事件日志
            _get_logger().warning(
                f"[语音降级] session_id={session_id}, user_id={user_id}, "
                f"已从语音模式降级到文本模式"
            )

            # 尝试通过realtime_sync通知前端
            try:
                from core.sync.realtime_sync import get_realtime_sync_manager
                sync = get_realtime_sync_manager()  # 获取实时同步管理器
                sync.emit_event("voice_degraded", session_id, {
                    "user_id": user_id,
                    "message": notification_msg,
                    "new_mode": "text",
                    "timestamp": time.time(),
                    "suggestion": "您现在可以通过文字继续与AI对话"
                })
            except (ConnectionError, RuntimeError) as e:
                _get_logger().error(f"[DialogueManager] 发送语音降级通知事件失败: {e}", exc_info=True)

            # [Agent-005 修复] 尝试语音播报降级通知（使用统一方法获取 voice）
            voice = self._get_voice_instance()
            if voice:
                try:
                    # 简短播报降级信息
                    voice.speak(DialogueManagerAnnouncements.VOICE_MODE_ERROR, wait=False)
                except (OSError, RuntimeError) as e:
                    logger.error(f"[DialogueManager] 语音播报失败: {e}", exc_info=True)
                    # 继续执行，不中断流程

        except (RuntimeError, ValueError) as e:
            _get_logger().error(f"[DialogueManager] 语音降级通知异常: {e}", exc_info=True)

        # 【ExperienceBus】语音降级事件
        try:
            event_bus.emit("dialogue:voice_degraded", {
                "session_id": session_id,
                "user_id": user_id,
                "timestamp": time.time(),
            })
        except Exception as e:
            logger.error(f"[DialogueManager] 发送语音降级事件失败: {e}", exc_info=True)

    def _is_voice_specific_error(self, error: Exception) -> bool:
        """
        【语音降级修复】判断异常是否为语音特有异常

        语音特有异常：仅影响语音输入，降级到文本可解决
        系统级异常：影响所有输入模式，降级无意义

        Args:
            error: 捕获的异常对象

        Returns:
            bool: True表示语音特有异常，False表示系统级异常
        """
        error_type = type(error).__name__
        error_msg = str(error).lower()

        # ===== 系统级异常（不应降级）=====
        system_errors = [
            # 记忆相关
            'MemoryRetrievalError',
            'MemoryQueryError',
            'MemoryLevelError',
            # AI连接相关
            'AIConnectionError',
            'AITimeoutError',
            'AIResponseError',
            'AIEmptyResponseError',
            'AIProviderError',
            # 数据库相关
            'DatabaseError',
            'OperationalError',
            # 配置相关
            'ConfigurationError',
            'KeyError',  # 通常是配置缺失
        ]

        if error_type in system_errors:
            return False

        # ===== 语音特有异常（应降级）=====
        voice_specific_indicators = [
            # 语音处理相关关键词
            'voice', 'audio', 'speech', 'tts', 'asr', 'stt',
            '语音', '音频', '播报', '合成', '识别',
            # 设备相关
            'microphone', 'speaker', 'device',
            '麦克风', '扬声器', '设备',
            # 音频格式相关
            'wav', 'mp3', 'pcm', 'sample rate', 'bitrate',
            # 语音服务特定错误
            'pyttsx3', 'sapi5', 'nsss', 'espeak',
        ]

        return any(indicator in error_msg for indicator in voice_specific_indicators)

    async def _fallback_to_text(
        self,
        user_id: str,
        text: str,
        session_id: str,
        session,
        **kwargs
    ) -> str:
        """
        【语音降级修复】降级到文本处理

        Args:
            user_id: 用户唯一标识
            text: 语音识别后的文本
            session_id: 会话ID
            session: 当前会话对象
            **kwargs: 额外参数

        Returns:
            str: 文本处理结果
        """
        try:
            _get_logger().info("[DialogueManager] 语音降级: 正在切换到文本处理模式...")
            text_result = await self.handle_text_input(user_id, text, session_id, **kwargs)

            # 记录降级信息到会话历史
            session.chat_history.append({
                "role": "system",
                "content": "[系统消息] 语音处理异常，已自动切换到文本模式",
                "timestamp": datetime.now().isoformat(),
                "metadata": {
                    "event": "voice_fallback",
                    "fallback_result": text_result[:100] if text_result else None
                }
            })

            # 返回文本处理结果，并附加降级标记
            return f"[语音已切换到文本模式] {text_result}"

        except Exception as fallback_error:
            # 连文本处理也失败了，返回最终错误
            _get_logger().critical(
                f"[DialogueManager] 降级处理也失败 [SILENT_FAILURE_BLOCKED]: {fallback_error}"
            )
            return "抱歉，语音和文本处理都遇到了问题，请检查系统状态或稍后重试。"

    def _get_voice_instance(self, provided_voice=None):
        """
        【Agent-005 修复】统一获取 voice 实例

        按优先级尝试获取 voice 实例：
        1. 传入的参数
        2. self.voice
        3. global_state.get_voice_interface()

        Args:
            provided_voice: 可选的传入 voice 实例

        Returns:
            voice 实例或 None
        """
        # 1. 优先使用传入的实例
        if provided_voice:
            return provided_voice

        # 2. 尝试 self.voice
        if hasattr(self, 'voice') and self.voice:
            return self.voice

        # 3. 尝试从 global_state 获取
        try:
            voice_from_global = global_state.get_voice_interface()
            if voice_from_global:
                return voice_from_global
        except (AttributeError, RuntimeError) as e:
            logger.error(f"[DialogueManager] 从 global_state 获取 voice 失败: {e}", exc_info=True)
            # 继续执行，返回 None

        return None

    def check_voice_instance(self, voice_instance=None) -> bool:
        """
        [修复] 检查并确保 voice 实例已关联（保留用于兼容性）

        Args:
            voice_instance: 可选的外部 voice 实例

        Returns:
            bool: voice 实例是否可用
        """
        print("[WakeWord] DialogueManager.check_voice_instance() 被调用")
        print(f"[WakeWord] 当前 voice 实例状态: {self.voice is not None}")

        # 优先使用传入的实例
        if voice_instance is not None:
            print(f"[WakeWord] 传入的 voice_instance: {voice_instance is not None}")
            if self.voice is None:
                self.voice = voice_instance          # 保存传入的实例
                _get_logger().info("[DialogueManager] [FIX] voice 实例已通过参数关联")
                print("[WakeWord] ✅ voice 实例已通过参数关联")
            return True                              # 传入实例时返回True

        # 检查当前 voice 实例
        if self.voice is not None:
            print("[WakeWord] ✅ voice 实例已存在")
            return True                              # 已有实例，直接返回True

        # 尝试从 global_state 恢复
        print("[WakeWord] 尝试从 global_state 恢复 voice 实例...")
        try:
            voice_from_global = global_state.get_voice_interface()  # 从全局状态获取
            if voice_from_global is not None:
                self.voice = voice_from_global       # 恢复实例
                _get_logger().info("[DialogueManager] [FIX] voice 实例已从 global_state 恢复")
                print("[WakeWord] ✅ voice 实例已从 global_state 恢复")
                return True
            else:
                print("[WakeWord] global_state 中没有 voice 实例")
        except (AttributeError, RuntimeError) as e:
            _get_logger().error(f"[DialogueManager] 从 global_state 恢复 voice 失败: {e}", exc_info=True)
            print(f"[WakeWord] 从 global_state 恢复 voice 失败: {e}")

        # 尝试从 main 模块恢复
        print("[WakeWord] 尝试从 __main__ 恢复 voice 实例...")
        try:
            import __main__  # 导入主模块
            if hasattr(__main__, 'voice') and __main__.voice is not None:
                self.voice = __main__.voice          # 从主模块恢复
                _get_logger().info("[DialogueManager] [FIX] voice 实例已从 __main__ 恢复")
                print("[WakeWord] ✅ voice 实例已从 __main__ 恢复")
                return True
            else:
                print("[WakeWord] __main__ 中没有 voice 实例")
        except (AttributeError, RuntimeError) as e:
            _get_logger().error(f"[DialogueManager] 从 __main__ 恢复 voice 失败: {e}", exc_info=True)
            print(f"[WakeWord] 从 __main__ 恢复 voice 失败: {e}")

        if not self._voice_check_done:
            # 第一次检查失败时记录警告
            _get_logger().warning("[DialogueManager] [WARN] voice 实例未关联，语音播报功能将不可用")
            print("[WakeWord] voice 实例未关联，语音播报功能将不可用")
            self._voice_check_done = True            # 标记检查已完成

        return False                                 # 所有恢复尝试失败

    @property                                      # 属性装饰器，实现延迟加载
    def social_reasoning(self):
        """延迟加载社会推理引擎"""
        if self._social_reasoning is None:
            # 检查功能是否启用（默认禁用，避免HuggingFace连接超时）
            try:
                from core.config import config
                enabled = config.get("features.social_reasoning.enabled", False)
                if not enabled:
                    logger.debug("[DialogueManager] social_reasoning 功能已禁用")
                    from core.dialog.social_reasoning import SocialReasoning
                    # 创建实例但不加载HuggingFace模型（使用规则回退模式）
                    self._social_reasoning = SocialReasoning()
                    return self._social_reasoning
            except (ImportError, AttributeError) as e:
                logger.error(f"[DialogueManager] 配置读取失败: {e}", exc_info=True)
                # 配置读取失败时继续加载

            from core.dialog.social_reasoning import SocialReasoning
            self._social_reasoning = SocialReasoning()  # 首次访问时初始化
        return self._social_reasoning              # 返回缓存的实例

    @property
    def intent_parser(self):
        """延迟加载意图解析器"""
        if self._intent_parser is None:
            from core.intent.nlp_intent_parser import get_intent_parser
            self._intent_parser = get_intent_parser()  # 首次访问时初始化
        return self._intent_parser                 # 返回缓存的实例

    @property
    def command_parser(self):
        """延迟加载命令解析器"""
        if self._command_parser is None:
            from core.intent.command_parser import get_command_parser
            self._command_parser = get_command_parser()  # 首次访问时初始化
        return self._command_parser                # 返回缓存的实例

    @property
    def user_manager(self):
        """延迟加载多用户管理器"""
        if self._user_manager is None:
            from core.multi_user import multi_user_manager
            self._user_manager = multi_user_manager  # 首次访问时初始化
        return self._user_manager                  # 返回缓存的实例

    @property
    def alignment_engine(self):
        """【Phase 2 Week 4】延迟加载目标对齐引擎"""
        if self._alignment_engine is None:
            self._alignment_engine = get_goal_alignment_engine()
            # 设置历史记忆提供者
            self._alignment_engine.set_history_provider(
                lambda user_id: self._get_user_history_for_alignment(user_id)
            )
        return self._alignment_engine

    # ═══════════════════════════════════════════════════════════════
    # 【演示学习系统集成】任务协调器属性
    # ═══════════════════════════════════════════════════════════════

    @property
    def task_coordinator(self):
        """延迟加载演示学习任务协调器"""
        # 使用函数级缓存避免重复获取
        if not hasattr(self, '_task_coordinator_instance'):
            self._task_coordinator_instance = get_task_coordinator()
            _get_logger().debug("[DialogueManager] 任务协调器已初始化")
        return self._task_coordinator_instance

    @property
    def procedure_library(self):
        """延迟加载流程库"""
        if not hasattr(self, '_procedure_library_instance'):
            self._procedure_library_instance = get_procedure_library()
            _get_logger().debug("[DialogueManager] 流程库已初始化")
        return self._procedure_library_instance

    def _recognize_demonstration_intent(self, text: str) -> DemonstrationIntent:
        """
        【演示学习】识别演示相关意图

        Args:
            text: 用户输入文本

        Returns:
            DemonstrationIntent: 识别到的意图类型
        """
        if not text or not isinstance(text, str):
            return DemonstrationIntent.UNKNOWN

        text_lower = text.lower().strip()

        for intent, keywords in DEMONSTRATION_KEYWORDS.items():
            for keyword in keywords:
                if keyword.lower() in text_lower:
                    _get_logger().info(
                        f"[DemonstrationIntent] 识别到意图: {intent.value}, "
                        f"匹配关键词: {keyword}, 输入: {text[:50]}..."
                    )
                    return intent

        return DemonstrationIntent.UNKNOWN

    def _is_demonstration_related(self, text: str) -> bool:
        """
        【演示学习】判断是否为演示相关输入

        Args:
            text: 用户输入文本

        Returns:
            bool: 是否为演示相关
        """
        return self._recognize_demonstration_intent(text) != DemonstrationIntent.UNKNOWN

    async def _handle_demonstration_intent(
        self,
        user_id: str,
        session_id: str,
        text: str,
        intent: DemonstrationIntent,
        voice_instance=None
    ) -> str | None:
        """
        【演示学习】处理演示相关意图

        Args:
            user_id: 用户ID
            session_id: 会话ID
            text: 用户输入文本
            intent: 识别到的意图
            voice_instance: 可选的语音实例

        Returns:
            Optional[str]: 处理结果，如果不是演示意图返回None
        """
        try:
            if intent == DemonstrationIntent.START_DEMONSTRATION:
                return await self._start_user_demonstration(user_id, session_id, voice_instance)

            elif intent == DemonstrationIntent.STOP_DEMONSTRATION:
                return await self._stop_user_demonstration(user_id, session_id, voice_instance)

            elif intent == DemonstrationIntent.USE_LEARNED_PROCEDURE:
                return await self._handle_use_learned_procedure(user_id, session_id, text, voice_instance)

            return None

        except Exception as e:
            _get_logger().error(
                f"[DialogueManager] 处理演示意图失败 [SILENT_FAILURE_BLOCKED]: {e}",
                exc_info=True
            )
            raise RuntimeError(f"演示学习功能异常: {str(e)}") from e

    async def _start_user_demonstration(
        self,
        user_id: str,
        session_id: str,
        voice_instance=None
    ) -> str:
        """
        【演示学习】开始用户演示录制

        Args:
            user_id: 用户ID
            session_id: 会话ID
            voice_instance: 可选的语音实例

        Returns:
            str: 响应消息
        """
        _get_logger().info(
            f"[Demonstration] 开始用户演示: user_id={user_id}, session_id={session_id}"
        )

        try:
            # 获取或创建任务会话
            task_session = self.task_coordinator.start_task(
                session_id=session_id,
                task_id=f"demo_{session_id}_{int(time.time())}",
                intent="user_demonstration"
            )

            # 开始录制
            success = self.task_coordinator.start_user_demonstration(session_id)

            if not success:
                raise RuntimeError("启动演示录制失败，任务协调器返回False")

            # 发送WebSocket事件通知前端
            self._emit_demonstration_event(
                user_id=user_id,
                session_id=session_id,
                event_type="demonstration_started",
                data={
                    "task_session_id": task_session.session_id,
                    "message": "正在录制用户操作，请开始您的演示"
                }
            )

            # 语音播报
            if voice_instance:
                voice_instance.speak(DialogueManagerAnnouncements.DEMO_START, wait=False)

            response = "🎥 **正在录制用户操作**\n\n请开始您的演示，我会学习您的操作步骤。完成后说「演示完成」或「我做好了」"

            _get_logger().info(f"[Demonstration] 演示录制已开始: session_id={session_id}")
            return response

        except Exception as e:
            _get_logger().error(
                f"[DialogueManager] 开始演示录制失败 [SILENT_FAILURE_BLOCKED]: {e}",
                exc_info=True
            )
            raise RuntimeError(f"无法启动演示录制: {str(e)}") from e

    async def _stop_user_demonstration(
        self,
        user_id: str,
        session_id: str,
        voice_instance=None
    ) -> str:
        """
        【演示学习】停止用户演示并学习流程

        Args:
            user_id: 用户ID
            session_id: 会话ID
            voice_instance: 可选的语音实例

        Returns:
            str: 响应消息
        """
        _get_logger().info(
            f"[Demonstration] 停止用户演示: user_id={user_id}, session_id={session_id}"
        )

        try:
            # 停止录制并学习
            procedure = self.task_coordinator.stop_user_demonstration(session_id)

            if not procedure:
                raise RuntimeError("停止演示失败，未能获取学习到的流程")

            # 发送WebSocket事件通知前端
            self._emit_demonstration_event(
                user_id=user_id,
                session_id=session_id,
                event_type="demonstration_completed",
                data={
                    "procedure_id": procedure.procedure_id,
                    "procedure_name": procedure.name,
                    "step_count": len(procedure.steps),
                    "message": "演示学习完成，已保存流程"
                }
            )

            # 构建学习结果消息
            steps_summary = "\n".join([
                f"{i+1}. {step.description}"
                for i, step in enumerate(procedure.steps[:5])  # 最多显示5步
            ])

            if len(procedure.steps) > 5:
                steps_summary += f"\n... 共 {len(procedure.steps)} 个步骤"

            response = (
                f"✅ **演示学习完成！**\n\n"
                f"已保存流程: **{procedure.name}**\n"
                f"流程ID: `{procedure.procedure_id}`\n"
                f"步骤数: {len(procedure.steps)}\n\n"
                f"**学习到的步骤:**\n{steps_summary}\n\n"
                f"下次可以使用「用之前的办法」来执行此流程。"
            )

            # 语音播报
            if voice_instance:
                voice_instance.speak(
                    f"演示学习完成，已记录{len(procedure.steps)}个步骤",
                    wait=False
                )

            _get_logger().info(
                f"[Demonstration] 演示学习完成: procedure_id={procedure.procedure_id}, "
                f"steps={len(procedure.steps)}"
            )
            return response

        except Exception as e:
            _get_logger().error(
                f"[DialogueManager] 停止演示失败 [SILENT_FAILURE_BLOCKED]: {e}",
                exc_info=True
            )
            raise RuntimeError(f"无法停止演示: {str(e)}") from e

    async def _handle_use_learned_procedure(
        self,
        user_id: str,
        session_id: str,
        text: str,
        voice_instance=None
    ) -> str:
        """
        【演示学习】处理使用已学习流程的请求

        Args:
            user_id: 用户ID
            session_id: 会话ID
            text: 用户输入文本
            voice_instance: 可选的语音实例

        Returns:
            str: 响应消息
        """
        _get_logger().info(
            f"[Demonstration] 使用已学习流程: user_id={user_id}, session_id={session_id}"
        )

        try:
            # 从会话获取当前意图，或从历史记录推断（同步方法，无需await）
            session = self.get_session(user_id, session_id)
            intent = ""

            # 尝试从聊天历史获取最近的用户任务意图
            if session and session.chat_history:
                for msg in reversed(session.chat_history):
                    if msg.get("role") == "user":
                        content = msg.get("content", "")
                        # 排除演示相关的消息
                        if not self._is_demonstration_related(content):
                            intent = content
                            break

            # 如果没有找到意图，使用默认查询
            if not intent:
                intent = text  # 使用当前输入作为意图

            # 查找匹配的流程
            procedures = self.procedure_library.find_by_intent(intent, limit=3)

            if not procedures:
                # 如果没有找到，尝试列出所有流程
                all_procedures = self.procedure_library.list_procedures(active_only=True, limit=5)

                if not all_procedures:
                    response = "📭 **没有找到已学习的流程**\n\n您还没有演示过任何操作。请说「我来演示」开始录制。"
                    if voice_instance:
                        voice_instance.speak(DialogueManagerAnnouncements.NO_LEARNED_FLOW, wait=False)
                    return response

                # 显示所有可用流程供选择
                procedures_list = "\n".join([
                    f"- {p.name} (成功率: {p.get_success_rate():.0%})"
                    for p in all_procedures
                ])

                response = (
                    f"📋 **可用流程列表**\n\n"
                    f"{procedures_list}\n\n"
                    f"请说「执行 [流程名称]」来使用特定流程。"
                )

                if voice_instance:
                    voice_instance.speak(DialogueManagerAnnouncements.MULTIPLE_FLOWS, wait=False)

                return response

            # 获取最佳匹配的流程
            best_procedure = procedures[0]

            # 执行任务
            success = self.task_coordinator.execute_learned_procedure(
                session_id=session_id,
                procedure_id=best_procedure.procedure_id
            )

            if not success:
                raise RuntimeError(f"执行流程失败: {best_procedure.procedure_id}")

            # 发送WebSocket事件
            self._emit_demonstration_event(
                user_id=user_id,
                session_id=session_id,
                event_type="procedure_executing",
                data={
                    "procedure_id": best_procedure.procedure_id,
                    "procedure_name": best_procedure.name,
                    "step_count": len(best_procedure.steps)
                }
            )

            response = (
                f"🚀 **开始执行学习到的流程**\n\n"
                f"流程: **{best_procedure.name}**\n"
                f"步骤数: {len(best_procedure.steps)}\n"
                f"历史成功率: {best_procedure.get_success_rate():.0%}\n\n"
                f"正在按您之前演示的方式执行..."
            )

            if voice_instance:
                voice_instance.speak(
                    f"开始执行{best_procedure.name}，共{len(best_procedure.steps)}个步骤",
                    wait=False
                )

            _get_logger().info(
                f"[Demonstration] 流程执行已启动: procedure_id={best_procedure.procedure_id}"
            )
            return response

        except Exception as e:
            _get_logger().error(
                f"[DialogueManager] 使用学习流程失败 [SILENT_FAILURE_BLOCKED]: {e}",
                exc_info=True
            )
            raise RuntimeError(f"无法执行学习到的流程: {str(e)}") from e

    def _emit_demonstration_event(
        self,
        user_id: str,
        session_id: str | None,
        event_type: str,
        data: dict[str, Any]
    ):
        """
        【演示学习】发送演示相关事件到前端

        Args:
            user_id: 用户ID
            session_id: 会话ID
            event_type: 事件类型
            data: 事件数据
        """
        try:
            from core.sync.realtime_sync import get_realtime_sync_manager
            sync = get_realtime_sync_manager()

            event_data = {
                "user_id": user_id,
                "session_id": session_id,
                "demonstration_type": event_type,
                "timestamp": datetime.now().isoformat(),
                **data
            }

            sync.emit_event(
                event_type=event_type,
                session_id=session_id or f"user_{user_id}",
                data=event_data
            )

            _get_logger().debug(
                f"[Demonstration] 事件已发送: {event_type}"
            )

        except Exception as e:
            _get_logger().error(
                f"[DialogueManager] 发送演示事件失败: {e}"
            )
            # 不阻塞主流程

    def get_demonstration_status(self, session_id: str) -> dict[str, Any] | None:
        """
        【演示学习】获取当前演示状态

        Args:
            session_id: 会话ID

        Returns:
            Optional[Dict]: 演示状态，如果没有则返回None
        """
        try:
            return self.task_coordinator.get_session_status(session_id)
        except Exception as e:
            _get_logger().error(
                f"[DialogueManager] 获取演示状态失败 [SILENT_FAILURE_BLOCKED]: {e}",
                exc_info=True
            )
            return None

    def _generate_uuid(self) -> str:
        """生成唯一会话ID"""
        return str(uuid.uuid4())                   # 生成UUID并转为字符串

    def create_session(
        self,
        user_id: str,
        session_id: str = None,
        mode: WorkMode = WorkMode.DAILY
    ) -> UserSession:
        """
        为用户创建新会话

        Args:
            user_id: 用户唯一标识
            session_id: 可选的会话ID，不传则自动生成
            mode: 工作模式（DAILY/FOCUS）

        Returns:
            UserSession: 新创建的会话对象
        """
        # 【修复】防御性编程：严格验证参数类型，防止 slice 等不可哈希类型
        if not isinstance(user_id, str):
            _get_logger().error(
                f"[DialogueManager.create_session] user_id 类型异常: {type(user_id)}, "
                f"值: {repr(user_id)}, 将使用默认值"
            )
            user_id = str(user_id) if user_id else "default"  # 转换或使用默认值

        if session_id is None:
            session_id = self._generate_uuid()       # 未传入时自动生成UUID
        elif not isinstance(session_id, str):
            _get_logger().error(
                f"[DialogueManager.create_session] session_id 类型异常: {type(session_id)}, "
                f"值: {repr(session_id)}, 将生成新的 UUID"
            )
            # 如果是 slice 对象，生成新的 UUID
            session_id = self._generate_uuid()

        session = UserSession(
            session_id=session_id,                   # 会话ID
            user_id=user_id,                         # 用户ID
            chat_history=[],                         # 初始空聊天历史
            created_at=datetime.now(),               # 当前时间作为创建时间
            last_active=datetime.now(),              # 当前时间作为最后活跃时间
            mode=mode,                               # 工作模式
            metadata={}                              # 空元数据
        )

        with self._sessions_lock:                    # 获取会话锁
            if user_id not in self._user_sessions:
                # 如果是该用户的第一个会话，创建内层字典
                self._user_sessions[user_id] = {}
            self._user_sessions[user_id][session_id] = session  # 存储会话

        # 更新用户上下文
        try:
            self.user_manager.set_session_context(
                session_id,
                "active_session",
                session_id
            )
            self.user_manager.set_session_context(
                session_id,
                "mode",
                mode.value
            )
        except (AttributeError, RuntimeError) as e:
            _get_logger().error(f"[DialogueManager] 更新用户上下文失败: {e}", exc_info=True)

        _get_logger().info(f"[DialogueManager] 创建会话: user_id={user_id}, session_id={session_id}")
        return session                               # 返回创建的会话对象

    def get_session(self, user_id: str, session_id: str) -> UserSession | None:
        """
        获取用户会话

        Args:
            user_id: 用户唯一标识
            session_id: 会话ID

        Returns:
            Optional[UserSession]: 会话对象，不存在则返回None
        """
        # 【修复】防御性编程：验证参数类型，防止 slice 等不可哈希类型
        if not isinstance(user_id, str):
            _get_logger().warning(
                f"[DialogueManager.get_session] user_id 类型异常: {type(user_id)}, "
                f"值: {repr(user_id)}, 将使用默认值"
            )
            user_id = str(user_id) if user_id else "default"

        if not isinstance(session_id, str):
            _get_logger().warning(
                f"[DialogueManager.get_session] session_id 类型异常: {type(session_id)}, "
                f"值: {repr(session_id)}"
            )
            return None                              # session_id异常时返回None

        with self._sessions_lock:                    # 获取会话锁
            user_sessions = self._user_sessions.get(user_id)  # 获取用户的所有会话
            if user_sessions:
                session = user_sessions.get(session_id)  # 获取特定会话
                if session:
                    session.last_active = datetime.now()  # 更新最后活跃时间
                return session                         # 返回会话对象
            return None                                # 用户或会话不存在

    async def get_or_create_session(
        self,
        user_id: str,
        session_id: str = None
    ) -> UserSession:
        """
        获取或创建用户会话

        Args:
            user_id: 用户唯一标识
            session_id: 会话ID，不传则创建新会话

        Returns:
            UserSession: 会话对象
        """
        # 【修复】防御性编程：严格验证 user_id 类型
        if not isinstance(user_id, str):
            _get_logger().error(
                f"[DialogueManager.get_or_create_session] user_id 类型异常: {type(user_id)}, "
                f"值: {repr(user_id)}, 将使用默认值"
            )
            user_id = str(user_id) if user_id else "default"

        # 【修复】防御性编程：验证 session_id 类型，如果是 slice 等不可哈希类型则设为 None
        if session_id is not None and not isinstance(session_id, str):
            _get_logger().error(
                f"[DialogueManager.get_or_create_session] session_id 类型异常: {type(session_id)}, "
                f"值: {repr(session_id)}, 将创建新会话"
            )
            session_id = None                        # 类型异常时设为None以创建新会话

        if session_id:
            session = self.get_session(user_id, session_id)  # 尝试获取现有会话（同步方法，无需await）
            if session:
                return session                         # 会话存在，直接返回

        # 创建新会话（同步方法，无需await）
        return self.create_session(user_id, session_id)

    async def handle_text_input(
        self,
        user_id: str,
        text: str,
        session_id: str = None,
        **kwargs
    ) -> str:
        """
        处理文本输入（Phase 2 Week 3 - 支持数据库存储）

        流程:
        1. 获取或创建用户会话
        2. 获取或创建数据库session
        3. 存储用户输入到数据库
        4. 记录用户输入到会话历史
        5. 调用NLP解析意图
        6. 调用Agent Loop执行任务
        7. 存储AI回复到数据库
        8. 记录AI回复到会话历史
        9. 返回结果

        Args:
            user_id: 用户唯一标识
            text: 用户输入文本
            session_id: 会话ID，不传则使用默认会话
            **kwargs: 额外参数

        Returns:
            str: AI回复
        """
        logger.debug(f"[DialogueManager] handle_text_input: user_id={user_id}, text={text[:30]}...")

        # 【BUG-5修复】获取输入锁，防止与语音输入冲突
        # 同一用户的语音和文本输入互斥，避免重复任务和状态竞争
        async with self._input_lock:
            _get_logger().debug(f"[DialogueManager] 文本输入获取锁: user_id={user_id}")

            # 获取或创建会话
            session = await self.get_or_create_session(user_id, session_id)

            # 更新最后活跃时间
            session.last_active = datetime.now()

        # ═══════════════════════════════════════════════════════════════
        # 【实时监控】检查启动/停止监控关键词（WebSocket 文本入口）
        # ═══════════════════════════════════════════════════════════════
        try:
            from core.constants import classify_user_input
            has_active = self.has_active_background_task(user_id)

            # 【P1】长任务中断恢复：用户插话检测
            # 如果当前有活跃后台任务，且输入不是显式控制/继续/取消，则标记为插话。
            # 直接走 quick_chat 快速回答，同时把插话文本暂存到 _interruption_requests，
            # 供 AgentLoop 下一轮检查点保存后返回 [PAUSED]。
            # 【P1-修复】明确任务/视觉请求不应视为插话，应作为新任务启动
            if has_active:
                lower_text = text.strip().lower()
                from core.constants import FORCE_TASK_KEYWORDS, FORCE_VISION_KEYWORDS
                is_force_task = any(kw in lower_text for kw in FORCE_TASK_KEYWORDS)
                is_force_vision = any(kw in lower_text for kw in FORCE_VISION_KEYWORDS)
                is_control_or_resume = any(
                    kw in lower_text
                    for kw in ["继续", "恢复", "接着做", "resume", "continue",
                               "取消", "停止", "终止", "cancel", "stop",
                               "暂停", "等一下", "pause", "别做了", "不做了"]
                )
                if not is_control_or_resume and not is_force_task and not is_force_vision:
                    self._interruption_requests[user_id] = text
                    _get_logger().info(
                        f"[DialogueManager] 检测到用户插话，请求暂停当前任务: {text[:50]}"
                    )
                    return await self._handle_quick_chat(
                        user_id, text, session_id, kwargs.get('voice_instance'),
                        active_task_hint=True
                    )

            classification = classify_user_input(text, has_active_task=has_active)
            category = classification["category"]

            # 【P1】ConsciousnessRouter：思维线程参与路由决策
            route_decision = None
            try:
                from core.consciousness.Consciousness import get_consciousness
                consciousness = get_consciousness(user_id)
                router = consciousness.get_router() if consciousness else None
                if router:
                    interruption_count = len([
                        h for h in (session.chat_history or [])
                        if h.get("role") == "user"
                        and (datetime.now() - datetime.fromisoformat(h.get("timestamp", datetime.now().isoformat()))).total_seconds() < 60
                    ])
                    route_decision = router.suggest_route(
                        user_input=text,
                        classification=classification,
                        has_active_task=has_active,
                        interruption_count=interruption_count,
                        chat_history=session.chat_history,
                    )
                    _get_logger().info(
                        f"[ConsciousnessRouter] 路由决策: mode={route_decision.mode}, "
                        f"reason={route_decision.reason}, confidence={route_decision.confidence:.2f}"
                    )
            except Exception as e:
                _get_logger().debug(f"[ConsciousnessRouter] 路由决策失败（非阻塞）: {e}")

            # ═══════════════════════════════════════════════════════════════
            # 【P1】ConsciousnessRouter 特殊模式：对齐确认
            # ═══════════════════════════════════════════════════════════════
            if route_decision and route_decision.mode == "alignment":
                _get_logger().info(
                    f"[DialogueManager] 路由进入对齐模式: {text[:50]}"
                )
                alignment_reply = await self._handle_alignment_request(
                    user_id, text, session_id, kwargs.get('voice_instance')
                )
                return alignment_reply

            # ═══════════════════════════════════════════════════════════════
            # 【P1-修复】简单聊天快速路径：不进入 AgentLoop，直接轻量 LLM 回答
            # ═══════════════════════════════════════════════════════════════
            if category == "simple_chat":
                _get_logger().info(
                    f"[DialogueManager] 文本输入识别为简单聊天，走快速通道: {text[:50]}..."
                )
                result = await self._handle_quick_chat(
                    user_id, text, session_id,
                    kwargs.get('voice_instance')
                )
                if isinstance(result, dict):
                    return result.get("content", "")
                return result

            # ═══════════════════════════════════════════════════════════════
            # 【P1-修复】任务控制指令：直接操作后台任务，不走 LLM 推理
            # ═══════════════════════════════════════════════════════════════
            elif category == "task_control":
                control_type = classification.get("control_type")
                _get_logger().info(
                    f"[DialogueManager] 文本输入识别为任务控制指令: {control_type}"
                )
                result = await self._handle_task_control(user_id, control_type, text, session_id)
                if isinstance(result, dict):
                    return result.get("content", "")
                return result

            # ═══════════════════════════════════════════════════════════════
            # 【P1-修复】任务状态查询：读取后台任务快照后轻量回答
            # ═══════════════════════════════════════════════════════════════
            elif category == "task_status_query":
                _get_logger().info(
                    f"[DialogueManager] 文本输入识别为任务状态查询，走快速通道: {text[:50]}..."
                )
                result = await self._handle_quick_chat(
                    user_id, text, session_id,
                    kwargs.get('voice_instance'),
                    active_task_hint=True
                )
                if isinstance(result, dict):
                    return result.get("content", "")
                return result

            elif category == "start_monitor":
                result = await self._handle_text_task(
                    user_id, text, session_id,
                    kwargs.get('voice_instance'), mode="start_monitor"
                )
                if isinstance(result, dict):
                    return result.get("content", "实时监控已启动")
                return result
            elif category == "stop_monitor":
                result = await self._handle_task_control(user_id, "stop_monitor", text, session_id)
                if isinstance(result, dict):
                    return result.get("content", "实时监控已停止")
                return result
            elif category == "potential_monitor":
                # 轻量 LLM 二次确认监控意图
                is_monitor = await self._confirm_monitor_intent(text)
                if is_monitor:
                    result = await self._handle_text_task(
                        user_id, text, session_id,
                        kwargs.get('voice_instance'), mode="start_monitor"
                    )
                else:
                    result = await self._handle_quick_chat(
                        user_id, text, session_id,
                        kwargs.get('voice_instance')
                    )
                if isinstance(result, dict):
                    return result.get("content", "")
                return result
        except Exception as e:
            _get_logger().warning(f"[DialogueManager] 输入分类检测异常: {e}")

        # ═══════════════════════════════════════════════════════════════
        # 【演示学习系统集成】检查演示相关意图
        # ═══════════════════════════════════════════════════════════════
        try:
            demo_intent = self._recognize_demonstration_intent(text)
            if demo_intent != DemonstrationIntent.UNKNOWN:
                _get_logger().info(
                    f"[DialogueManager] 检测到演示意图(文本): {demo_intent.value}"
                )

                # 获取语音实例
                voice_instance = self._get_voice_instance(kwargs.get('voice_instance'))

                # 处理演示意图
                result = await self._handle_demonstration_intent(
                    user_id=user_id,
                    session_id=session.session_id,
                    text=text,
                    intent=demo_intent,
                    voice_instance=voice_instance
                )

                if result:
                    # 记录到聊天历史
                    session.chat_history.append({
                        "role": "user",
                        "content": text,
                        "timestamp": datetime.now().isoformat(),
                        "metadata": {"demonstration_intent": demo_intent.value}
                    })
                    session.chat_history.append({
                        "role": "assistant",
                        "content": result,
                        "timestamp": datetime.now().isoformat(),
                        "metadata": {"demonstration_response": True}
                    })

                    # 存储到数据库（原生异步）
                    from core.diagnostic import safe_create_task
                    safe_create_task(
                        self._store_user_message_async(
                            session, text,
                            metadata={"demonstration_intent": demo_intent.value}
                        )
                    )
                    asyncio.create_task(
                        self._store_assistant_message_async(
                            session, result,
                            metadata={"demonstration_response": True}
                        )
                    )

                    return result

        except Exception as e:
            _get_logger().error(
                f"[DialogueManager] 演示意图处理异常 [SILENT_FAILURE_BLOCKED]: {e}",
                exc_info=True
            )
            # 演示意图处理失败不应阻止正常对话，继续执行后续流程

        # 【Phase 2 Week 3】获取或创建数据库session
        try:
            db_session_id, is_new = await self._get_or_create_db_session(
                user_id=user_id,
                session=session,
                mode=session.mode.value if hasattr(session.mode, 'value') else str(session.mode).lower(),
                title=self._generate_session_title(text)
            )
            if is_new:
                _get_logger().info(f"[DialogueManager] 自动创建数据库session: {db_session_id}")
        except Exception as e:
            _get_logger().error(f"[DialogueManager] 获取/创建数据库session失败: {e}", exc_info=True)
            # 存储失败不影响对话继续

        # 记录用户输入
        session.chat_history.append({
            "role": "user",                          # 标记为用户消息
            "content": text,                         # 消息内容
            "timestamp": datetime.now().isoformat()  # ISO格式时间戳
        })

        # 【Phase 2 Week 3】存储用户输入到数据库（异步，不阻塞对话）
        # 【Phase1-Week1集成】同时触发MemoryAutoTrigger记忆存储
        async def _store_user_msg_and_trigger_async():
            msg_id = None
            # 步骤1: 存储用户消息到数据库
            try:
                msg_id = await self._store_user_message_async(session, text)
                if msg_id:
                    _get_logger().info(f"[DialogueManager] 用户消息已存储到数据库: msg_id={msg_id}")
                else:
                    _get_logger().error(f"[DialogueManager] 存储用户消息失败，返回None: session={session_id}")
                    # 不阻断主流程，但记录错误
            except Exception as e:
                _get_logger().error(f"[DialogueManager] 存储用户消息异常: {e}", exc_info=True)
                # 不阻断主流程

            # 步骤2: 触发MemoryAutoTrigger记忆存储（必须传递message_id）
            if msg_id:
                try:
                    from core.memory.memory_auto_trigger import MemoryAutoTrigger
                    user_id = session.user_id if hasattr(session, 'user_id') else "default"
                    session_id_safe = session_id if session_id else f"session_{user_id}"

                    await MemoryAutoTrigger.on_user_input(
                        user_id=user_id,
                        session_id=session_id_safe,
                        text=text,
                        message_id=msg_id,  # 【修复】必须传递message_id
                        metadata={"source": "text_input", "input_mode": "text"}
                    )
                    _get_logger().info(f"[DialogueManager] MemoryAutoTrigger用户输入触发成功: user={user_id}, msg_id={msg_id}")
                except MemoryStoreError as e:
                    _get_logger().error(f"[DialogueManager] MemoryAutoTrigger用户输入存储失败: {e}", exc_info=True)
                    # 【P0修复】存储层失败不中断AgentLoop主循环，大脑与感官解耦
            else:
                _get_logger().error(f"[DialogueManager] 无法触发MemoryAutoTrigger: message_id为空，session={session_id}")

        from core.diagnostic import safe_create_task
        safe_create_task(_store_user_msg_and_trigger_async(), name="store_user_msg")

        # 限制历史长度（保留最近100条）
        if len(session.chat_history) > 100:
            session.chat_history = session.chat_history[-100:]  # 切片保留后100条

        # 社会推理：情感分析、欺骗检测
        try:
            sentiment, score = await self.social_reasoning.analyze_sentiment(text)  # 情感分析
            is_deception, reason = await self.social_reasoning.detect_deception(text)  # 欺骗检测
            if is_deception:
                # 检测到欺骗行为时的处理
                _get_logger().warning(f"检测到可能的欺骗行为: {reason}")
                response = "我不太明白你的意思，能再说一遍吗？"
                session.chat_history.append({
                    "role": "assistant",
                    "content": response,
                    "timestamp": datetime.now().isoformat()
                })

                # 【Phase 2 Week 3】存储AI回复到数据库（原生异步）
                from core.diagnostic import safe_create_task
                safe_create_task(self._store_assistant_message_async(session, response), name="store_assistant_msg")

                return response                        # 返回安全回复
        except (RuntimeError, ValueError) as e:
            _get_logger().error(f"[DialogueManager] 社会推理失败: {e}", exc_info=True)
            # 社会推理失败不应阻止对话继续，继续执行后续流程

        # [P0-001 修复] 删除重复解析代码
        # 原因：命令解析和意图解析已在 chat_mode_handler.py 中统一处理
        # dual_mode_manager.handle_text() 会正确处理命令识别和意图分析
        # 原代码在此处解析但结果仅用于日志，造成性能浪费和潜在不一致

        # [Agent-005 修复] 使用统一方法获取 voice 实例
        voice_instance = self._get_voice_instance(kwargs.get('voice_instance'))
        if not voice_instance:
            _get_logger().debug("无可用 voice 实例，语音播报将不可用")

        # 处理文本输入
        try:
            # 【修复】防御性编程：确保参数类型正确，防止 slice 对象传递
            if not isinstance(text, str):
                _get_logger().warning(f"[DialogueManager] text 参数类型异常: {type(text)}, 转换为字符串")
                text = str(text) if text else ""

            # 【修复】增强 session_id 类型检查，处理 slice 等不可哈希类型
            session_id_for_handler = session.session_id
            if not isinstance(session_id_for_handler, str):
                _get_logger().error(
                    f"[DialogueManager] session.session_id 类型异常: {type(session_id_for_handler)}, "
                    f"值: {repr(session_id_for_handler)}, 会话将生成新的 session_id"
                )
                # 如果 session_id 不是字符串（如 slice 对象），生成新的 UUID
                session_id_for_handler = str(uuid.uuid4())
                # 同时修复 session 对象中的 session_id
                session.session_id = session_id_for_handler

            session_id = session_id_for_handler

            # 延迟导入双模式管理器
            from core.dialog.chat_mode_handler import dual_mode_manager
            # 使用双模式管理器处理（Phase 8: await 异步入口）
            final_result = await dual_mode_manager.handle_text(text, session_id, db_session_id=db_session_id, voice_instance=self.voice)

            if final_result:
                # 记录AI回复
                session.chat_history.append({
                    "role": "assistant",
                    "content": final_result,
                    "timestamp": datetime.now().isoformat()
                })

                # 【Phase 2 Week 3】存储AI回复到数据库（异步，不阻塞对话）
                # 【Phase1-Week1集成】同时触发MemoryAutoTrigger记忆存储
                async def _store_assistant_msg_and_trigger_async():
                    assistant_msg_id = None
                    # 步骤1: 存储AI回复到数据库
                    try:
                        # 尝试获取memory_id（从AI响应中提取，如果有的话）
                        memory_id = None
                        if isinstance(final_result, dict) and "memory_id" in final_result:
                            memory_id = final_result.get("memory_id")

                        assistant_msg_id = await self._store_assistant_message_async(
                            session=session,
                            content=final_result if isinstance(final_result, str) else str(final_result),
                            memory_id=memory_id
                        )
                        if assistant_msg_id:
                            _get_logger().info(f"[DialogueManager] AI回复已存储到数据库: msg_id={assistant_msg_id}")
                        else:
                            _get_logger().error(f"[DialogueManager] 存储AI回复失败，返回None: session={session_id}")
                    except Exception as e:
                        _get_logger().error(f"[DialogueManager] 存储AI回复异常: {e}", exc_info=True)

                    # 步骤2: 触发MemoryAutoTrigger AI回复存储（必须传递message_id）
                    if assistant_msg_id:
                        try:
                            from core.memory.memory_auto_trigger import MemoryAutoTrigger
                            user_id = session.user_id if hasattr(session, 'user_id') else "default"
                            session_id_safe = session_id if session_id else f"session_{user_id}"

                            await MemoryAutoTrigger.on_ai_response(
                                user_id=user_id,
                                session_id=session_id_safe,
                                response=final_result,
                                message_id=assistant_msg_id,  # 【修复】必须传递message_id
                                thinking=None,
                                tool_calls=None
                            )
                            _get_logger().info(f"[DialogueManager] MemoryAutoTrigger AI回复触发成功: user={user_id}, msg_id={assistant_msg_id}")
                        except MemoryStoreError as e:
                            _get_logger().error(f"[DialogueManager] MemoryAutoTrigger AI回复存储失败: {e}", exc_info=True)
                            # 【P0修复】存储层失败不中断AgentLoop主循环，大脑与感官解耦
                    else:
                        _get_logger().error(f"[DialogueManager] 无法触发MemoryAutoTrigger AI回复: message_id为空，session={session_id}")

                from core.diagnostic import safe_create_task
                safe_create_task(_store_assistant_msg_and_trigger_async(), name="store_assistant_msg_trigger")

                return final_result                    # 返回处理结果
            else:
                _get_logger().warning("文本任务返回空结果")
                return "任务执行完成，但没有返回结果。"

        except Exception as e:
            # 【修复】增强异常信息，精确定位 unhashable type: 'slice' 错误
            import traceback
            stack_trace = traceback.format_exc()       # 获取完整堆栈
            _get_logger().error(f"[DialogueManager] 文本处理异常: {e}\n堆栈追踪:\n{stack_trace}")

            # 【UX优化】返回具体错误信息，帮助用户理解问题
            error_msg = str(e)
            if "视觉模型" in error_msg or "Vision" in error_msg:
                return "【错误】视觉模型调用失败，请检查 Ollama 是否正常启动，或模型 qwen3-vl:2b 是否已下载。"
            elif "api_key" in error_msg or "API" in error_msg:
                return "【错误】AI 服务配置异常，请检查 .env 中的 API Key 配置。"
            elif "连接" in error_msg or "Connection" in error_msg:
                return "【错误】网络连接失败，请检查网络或 Ollama 服务状态。"
            else:
                return f"【错误】处理请求时出现问题: {error_msg[:100]}。请检查系统日志或稍后重试。"

    async def handle_text_input_with_tools(
        self,
        user_id: str,
        text: str,
        session_id: str = None,
        **kwargs
    ) -> dict[str, Any]:
        """
        处理文本输入，返回包含工具调用信息的详细结果

        【P0-032 修复】WebSocket工具调用信息丢失修复
        此方法返回包含 content 和 tool_calls 的字典，用于WebSocket API

        流程:
        1. 获取或创建用户会话
        2. 获取或创建数据库session
        3. 存储用户输入到数据库
        4. 记录用户输入到会话历史
        5. 调用Agent Loop执行任务（收集工具调用信息）
        6. 存储AI回复到数据库
        7. 记录AI回复到会话历史
        8. 返回包含 content 和 tool_calls 的字典

        Args:
            user_id: 用户唯一标识
            text: 用户输入文本
            session_id: 会话ID，不传则使用默认会话
            **kwargs: 额外参数

        Returns:
            Dict[str, Any]: 包含以下字段的字典
                - content (str): AI回复内容
                - tool_calls (List[Dict]): 工具调用列表，每个元素包含:
                    - tool (str): 工具名称
                    - params (Dict): 工具参数
                    - success (bool): 调用是否成功
                    - message (str): 结果消息
                - success (bool): 处理是否成功
                - session_id (str): 会话ID
        """
        logger.debug(f"[DialogueManager] handle_text_input_with_tools: user_id={user_id}, text={text[:30]}...")

        # 初始化工具调用列表
        tool_calls: list[dict[str, Any]] = []

        # 获取或创建会话
        session = await self.get_or_create_session(user_id, session_id)

        # 更新最后活跃时间
        session.last_active = datetime.now()

        # 【Phase 2 Week 3】获取或创建数据库session
        try:
            db_session_id, is_new = await self._get_or_create_db_session(
                user_id=user_id,
                session=session,
                mode=session.mode.value if hasattr(session.mode, 'value') else str(session.mode).lower(),
                title=self._generate_session_title(text)
            )
            if is_new:
                _get_logger().info(f"[DialogueManager] 自动创建数据库session: {db_session_id}")
        except Exception as e:
            _get_logger().error(f"[DialogueManager] 获取/创建数据库session失败: {e}", exc_info=True)

        # 记录用户输入
        session.chat_history.append({
            "role": "user",
            "content": text,
            "timestamp": datetime.now().isoformat()
        })

        # 【Phase 2 Week 3】存储用户输入到数据库（原生异步）
        safe_create_task(
            self._store_user_message_async(session, text),
            name="_store_user_message_async"
        )

        # 限制历史长度（保留最近100条）
        if len(session.chat_history) > 100:
            session.chat_history = session.chat_history[-100:]

        # 社会推理：情感分析、欺骗检测
        try:
            sentiment, score = await self.social_reasoning.analyze_sentiment(text)
            is_deception, reason = await self.social_reasoning.detect_deception(text)
            if is_deception:
                _get_logger().warning(f"检测到可能的欺骗行为: {reason}")
                response = "我不太明白你的意思，能再说一遍吗？"
                session.chat_history.append({
                    "role": "assistant",
                    "content": response,
                    "timestamp": datetime.now().isoformat()
                })

                # 【Phase 2 Week 3】存储欺骗检测响应（原生异步）
                safe_create_task(self._store_assistant_message_async(session, response), name="_store_assistant_message_async")

                return {
                    "content": response,
                    "tool_calls": [],
                    "success": True,
                    "session_id": session.session_id
                }
        except Exception as e:
            _get_logger().debug(f"[DialogueManager] 社会推理失败: {e}")

        # [Agent-005 修复] 使用统一方法获取 voice 实例
        voice_instance = self._get_voice_instance(kwargs.get('voice_instance'))
        if not voice_instance:
            _get_logger().debug("无可用 voice 实例，语音播报将不可用")

        # 处理文本输入
        try:
            # 【修复】防御性编程：确保参数类型正确，防止 slice 对象传递
            if not isinstance(text, str):
                _get_logger().warning(f"[DialogueManager] text 参数类型异常: {type(text)}, 转换为字符串")
                text = str(text) if text else ""

            # 【修复】增强 session_id 类型检查，处理 slice 等不可哈希类型
            session_id_for_handler = session.session_id
            if not isinstance(session_id_for_handler, str):
                _get_logger().error(
                    f"[DialogueManager] session.session_id 类型异常: {type(session_id_for_handler)}, "
                    f"值: {repr(session_id_for_handler)}, 会话将生成新的 session_id"
                )
                session_id_for_handler = str(uuid.uuid4())
                session.session_id = session_id_for_handler

            session_id = session_id_for_handler

            # 延迟导入双模式管理器
            from core.dialog.chat_mode_handler import dual_mode_manager

            # 【P0-032 修复】使用支持工具调用收集的方法（Phase 8: await 异步入口）
            result = await dual_mode_manager.handle_text_with_tools(text, session_id, user_id=user_id, db_session_id=db_session_id, voice_instance=self.voice)

            final_result = result.get("content", "")
            tool_calls = result.get("tool_calls", [])

            if final_result:
                # 记录AI回复
                session.chat_history.append({
                    "role": "assistant",
                    "content": final_result,
                    "timestamp": datetime.now().isoformat()
                })

                # 【Phase 2 Week 3】存储AI回复到数据库（原生异步）
                asyncio.create_task(
                    self._store_assistant_message_async(
                        session=session,
                        content=final_result,
                        metadata={"tool_calls": {"calls": tool_calls}} if tool_calls else None
                    )
                )

                return {
                    "content": final_result,
                    "tool_calls": tool_calls,
                    "success": True,
                    "session_id": session_id
                }
            else:
                _get_logger().warning("文本任务返回空结果")
                return {
                    "content": "任务执行完成，但没有返回结果。",
                    "tool_calls": tool_calls,
                    "success": True,
                    "session_id": session_id
                }

        except Exception as e:
            import traceback
            stack_trace = traceback.format_exc()
            _get_logger().error(f"[DialogueManager] 文本处理异常: {e}\n堆栈追踪:\n{stack_trace}")

            # 【UX修复】任务失败时播报错误提示，避免用户只听到"正在查询"而没有后续
            try:
                from core import global_state
                voice = global_state.get_voice_interface()
                if voice:
                    # 根据错误类型给出不同的语音反馈
                    error_str = str(e).lower()
                    if "timeout" in error_str or "超时" in error_str:
                        voice.speak(DialogueManagerAnnouncements.RESPONSE_TIMEOUT, is_system=True, wait=False)
                    elif "vision" in error_str or "视觉" in error_str:
                        voice.speak(DialogueManagerAnnouncements.VISION_UNAVAILABLE, is_system=True, wait=False)
                    elif "connection" in error_str or "连接" in error_str:
                        voice.speak(DialogueManagerAnnouncements.NETWORK_ISSUE, is_system=True, wait=False)
                    else:
                        voice.speak(DialogueManagerAnnouncements.REQUEST_ERROR, is_system=True, wait=False)
            except Exception as voice_err:
                _get_logger().debug(f"[DialogueManager] 错误提示语音播报失败: {voice_err}")

            return {
                "content": "抱歉，处理您的请求时出现问题，请稍后重试。",
                "tool_calls": tool_calls,
                "success": False,
                "session_id": session.session_id if session else None,
                "error": str(e)
            }

    async def handle_voice_input(
        self,
        user_id: str,
        text: str,
        session_id: str = None,
        **kwargs
    ) -> str:
        """
        处理语音输入（Phase 2 Week 3 - 支持数据库存储）

        流程:
        1. 获取或创建用户会话
        2. 获取或创建数据库session（语音专用session）
        3. 存储用户输入到数据库
        4. 记录用户输入到会话历史
        5. 调用双模式管理器处理
        6. 存储AI回复到数据库
        7. 记录AI回复到会话历史
        8. 返回结果

        Args:
            user_id: 用户唯一标识
            text: 语音识别后的文本
            session_id: 会话ID，不传则使用默认会话
            **kwargs: 额外参数

        Returns:
            str: AI回复
        """
        logger.debug(f"[DialogueManager] handle_voice_input: user_id={user_id}, text={text[:30]}...")

        # 【BUG-5修复】获取输入锁，防止与文本输入冲突
        # 语音和文本输入互斥，避免重复任务和状态竞争
        async with self._input_lock:
            _get_logger().debug(f"[DialogueManager] 语音输入获取锁: user_id={user_id}")

            # 获取或创建会话
            session = await self.get_or_create_session(user_id, session_id)

            # 【修复代理-02】【BUG-7 Fix】将session.last_active移入锁保护范围，避免竞态条件
            # 更新最后活跃时间
            session.last_active = datetime.now()

        # ═══════════════════════════════════════════════════════════════
        # 【演示学习系统集成】语音输入检查演示相关意图
        # ═══════════════════════════════════════════════════════════════
        # 语音输入的演示意图也需要经过聊天对齐，确保AI理解正确
        try:
            demo_intent = self._recognize_demonstration_intent(text)
            if demo_intent != DemonstrationIntent.UNKNOWN:
                _get_logger().info(
                    f"[DialogueManager] 检测到演示意图(语音): {demo_intent.value}"
                )

                # 语音输入必须经过聊天对齐，确保AI理解正确
                # 将对齐文本添加演示意图标记，让AI知道是演示相关
                alignment_text = f"[演示意图: {demo_intent.value}] {text}"

                # 获取语音实例
                voice_instance = self._get_voice_instance()

                # 先进行对齐确认
                from core.dialog.chat_mode_handler import dual_mode_manager
                alignment_result = await dual_mode_manager.handle_voice_alignment(
                    text=alignment_text,
                    session_id=session.session_id,
                    voice_instance=voice_instance,
                    user_id=user_id
                )

                # 如果AI确认这是演示意图，直接处理
                if alignment_result.get("type") == "alignment_confirmed":
                    # 检查AI是否理解这是演示意图
                    ai_response = alignment_result.get("ai_response", "")

                    # 如果AI确认了演示意图，执行对应的演示操作
                    if any(word in ai_response for word in ["演示", "录制", "学习", "操作"]):
                        result = await self._handle_demonstration_intent(
                            user_id=user_id,
                            session_id=session.session_id,
                            text=text,
                            intent=demo_intent,
                            voice_instance=voice_instance
                        )

                        if result:
                            # 记录到聊天历史
                            session.chat_history.append({
                                "role": "user",
                                "content": text,
                                "timestamp": datetime.now().isoformat(),
                                "metadata": {
                                    "demonstration_intent": demo_intent.value,
                                    "input_mode": "voice"
                                }
                            })
                            session.chat_history.append({
                                "role": "assistant",
                                "content": result,
                                "timestamp": datetime.now().isoformat(),
                                "metadata": {
                                    "demonstration_response": True,
                                    "voice_aligned": True
                                }
                            })

                            return result

                # 如果不是明确的演示意图确认，继续正常语音处理流程
                _get_logger().debug(
                    "[DialogueManager] 演示意图未确认，继续正常语音处理"
                )

        except Exception as e:
            _get_logger().error(
                f"[DialogueManager] 语音演示意图处理异常 [SILENT_FAILURE_BLOCKED]: {e}",
                exc_info=True
            )
            # 演示意图处理失败不应阻止正常对话，继续执行后续流程

        # 【Phase 2 Week 3】获取或创建数据库session（语音模式）
        try:
            db_session_id, is_new = await self._get_or_create_db_session(
                user_id=user_id,
                session=session,
                mode="daily",  # 语音输入默认使用daily模式
                title=self._generate_session_title(text)
            )
            if is_new:
                _get_logger().info(f"[DialogueManager] 自动创建语音数据库session: {db_session_id}")
        except Exception as e:
            _get_logger().error(f"[DialogueManager] 获取/创建语音数据库session失败: {e}", exc_info=True)

        # 记录用户输入
        session.chat_history.append({
            "role": "user",
            "content": text,
            "timestamp": datetime.now().isoformat()
        })

        # 【Phase 2 Week 3】存储用户输入到数据库（异步）
        # 【Phase1-Week1集成】同时触发MemoryAutoTrigger记忆存储
        async def _store_voice_user_msg_and_trigger_async():
            voice_msg_id = None
            # 步骤1: 存储语音用户消息到数据库
            try:
                voice_msg_id = await self._store_user_message_async(
                    session,
                    text,
                    metadata={"input_mode": "voice", "source": "voice_recognition"}
                )
                if voice_msg_id:
                    _get_logger().info(f"[DialogueManager] 语音用户消息已存储到数据库: msg_id={voice_msg_id}")
                else:
                    _get_logger().error(f"[DialogueManager] 存储语音用户消息失败，返回None: session={session_id}")
            except Exception as e:
                _get_logger().error(f"[DialogueManager] 存储语音用户消息异常: {e}", exc_info=True)

            # 步骤2: 触发MemoryAutoTrigger语音输入存储（必须传递message_id）
            if voice_msg_id:
                try:
                    from core.memory.memory_auto_trigger import MemoryAutoTrigger
                    session_id_safe = session_id if session_id else f"session_{user_id}"

                    await MemoryAutoTrigger.on_user_input(
                        user_id=user_id,
                        session_id=session_id_safe,
                        text=text,
                        message_id=voice_msg_id,  # 【修复】必须传递message_id
                        metadata={"source": "voice_input", "input_mode": "voice", "alignment_type": "confirmed"}
                    )
                    _get_logger().info(f"[DialogueManager] MemoryAutoTrigger语音输入触发成功: user={user_id}, msg_id={voice_msg_id}")
                except MemoryStoreError as e:
                    _get_logger().error(f"[DialogueManager] MemoryAutoTrigger语音输入存储失败: {e}", exc_info=True)
                    # 【P0修复】存储层失败不中断AgentLoop主循环，大脑与感官解耦
            else:
                _get_logger().error(f"[DialogueManager] 无法触发MemoryAutoTrigger语音输入: message_id为空，session={session_id}")

        safe_create_task(_store_voice_user_msg_and_trigger_async(), name="_store_voice_user_msg_and_trigger_async")

        # 限制历史长度
        if len(session.chat_history) > 100:
            session.chat_history = session.chat_history[-100:]

        # 社会推理
        try:
            sentiment, score = await self.social_reasoning.analyze_sentiment(text)
            is_deception, reason = await self.social_reasoning.detect_deception(text)
            if is_deception:
                _get_logger().warning(f"检测到可能的欺骗行为: {reason}")
                # [Agent-005 修复] 使用统一方法获取 voice 实例
                voice = self._get_voice_instance()
                if voice:
                    voice.speak(DialogueManagerAnnouncements.NOT_UNDERSTOOD)

                response = "我不太明白你的意思，能再说一遍吗？"

                # 【Phase 2 Week 3】存储欺骗检测响应（原生异步）
                safe_create_task(self._store_assistant_message_async(session, response), name="_store_assistant_message_async")

                return response
        except Exception as e:
            _get_logger().error(
                f"[DialogueManager] 社会推理失败 [SILENT_FAILURE_BLOCKED]: {e}",
                exc_info=True
            )

        # [P0-001 修复] 删除重复解析代码
        # 原因：命令解析和意图解析已在 chat_mode_handler.py 中统一处理
        # dual_mode_manager.handle_voice() -> ChatModeHandler.handle() 会正确处理命令识别
        # 原代码在此处解析但结果仅用于日志，造成性能浪费和潜在不一致

        # [Agent-005 修复] 使用统一方法获取 voice 实例
        print("[WakeWord] handle_voice_input: 检查 voice 实例...")
        voice_instance = self._get_voice_instance()
        print(f"[WakeWord] handle_voice_input: voice 实例可用: {voice_instance is not None}")

        # 处理语音输入
        try:
            # 【修复】防御性编程：确保参数类型正确
            if not isinstance(text, str):
                _get_logger().warning(f"[DialogueManager] text 参数类型异常: {type(text)}, 转换为字符串")
                text = str(text) if text else ""

            # 【修复】增强 session_id 类型检查，处理 slice 等不可哈希类型
            session_id_for_handler = session.session_id
            if not isinstance(session_id_for_handler, str):
                _get_logger().error(
                    f"[DialogueManager] session.session_id 类型异常: {type(session_id_for_handler)}, "
                    f"值: {repr(session_id_for_handler)}, 会话将生成新的 session_id"
                )
                # 如果 session_id 不是字符串（如 slice 对象），生成新的 UUID
                session_id_for_handler = str(uuid.uuid4())
                # 同时修复 session 对象中的 session_id
                session.session_id = session_id_for_handler

            session_id = session_id_for_handler

            # [Agent-005 修复] voice 实例已通过统一方法获取
            print(f"[WakeWord] 准备调用 dual_mode_manager.handle_voice，voice实例: {voice_instance is not None}")
            if voice_instance is None:
                _get_logger().warning("[DialogueManager] voice 实例为 None，语音播报将不可用")
                print("[WakeWord] ⚠️ voice 实例为 None，语音播报将不可用")

            # 延迟导入双模式管理器
            from core.dialog.chat_mode_handler import dual_mode_manager

            # 【P1-002修复】语音输入强制进入聊天对齐模式
            # 调用 handle_voice_alignment 进行需求对齐，不直接执行
            print(f"[WakeWord] 进入聊天对齐模式: {text[:50]}...")
            _get_logger().info(f"[DialogueManager] 语音输入进入聊天对齐模式: {text[:50]}...")

            # 执行对齐处理
            alignment_result = await dual_mode_manager.handle_voice_alignment(
                text=text,
                session_id=session_id,
                voice_instance=voice_instance,
                user_id=user_id
            )

            # 根据对齐结果处理
            if alignment_result.get("type") == "alignment_confirmed":
                # 对齐已确认，进入任务执行
                print("[WakeWord] 对齐已确认，进入任务执行")
                _get_logger().info("[DialogueManager] 需求对齐完成，进入任务执行")

                # 【修复】判断是否直接执行（明确指令）
                is_direct = alignment_result.get("direct_execution", False)
                ai_response = alignment_result.get("ai_response", "好的，开始执行任务")

                # 播报确认语（明确指令时使用AI的确认回复）
                if voice_instance:
                    if is_direct:
                        # 明确指令：播报AI的确认回复（如"好的，我来打开网易云音乐"）
                        voice_instance.speak(ai_response)
                    else:
                        # 对齐确认：播报标准过渡语
                        voice_instance.speak(DialogueManagerAnnouncements.TASK_START)

                # 【修复】明确指令直接执行，不需要额外对齐
                if is_direct:
                    print(f"[WakeWord] 明确指令，直接执行任务: {text[:50]}...")
                    _get_logger().info("[DialogueManager] 明确指令，直接执行任务")

                    # 直接使用原始文本作为任务描述
                    task_description = alignment_result.get("user_requirement", text)

                    # Phase 8: _task_runner.run 已是 async def，直接 await
                    final_answer = await dual_mode_manager._task_runner.run(
                        task_description=task_description,
                        session_id=session_id,
                        voice_instance=voice_instance
                    )
                else:
                    # Phase 8: enter_task_loop_from_alignment 已是 async def，直接 await
                    final_answer = await dual_mode_manager.enter_task_loop_from_alignment(
                        user_id=user_id,
                        session_id=session_id,
                        voice_instance=voice_instance
                    )

                # 记录AI回复
                session.chat_history.append({
                    "role": "assistant",
                    "content": final_answer,
                    "timestamp": datetime.now().isoformat()
                })

                # 【Phase 2 Week 3】存储AI回复到数据库（异步）
                # 【Phase1-Week1集成】同时触发MemoryAutoTrigger记忆存储
                async def _store_voice_assistant_msg_and_trigger_async():
                    voice_assistant_msg_id = None
                    # 步骤1: 存储语音AI回复到数据库
                    try:
                        voice_assistant_msg_id = await self._store_assistant_message_async(
                            session=session,
                            content=final_answer,
                            metadata={"input_mode": "voice", "alignment_type": "confirmed"}
                        )
                        if voice_assistant_msg_id:
                            _get_logger().info(f"[DialogueManager] 语音AI回复已存储到数据库: msg_id={voice_assistant_msg_id}")
                        else:
                            _get_logger().error(f"[DialogueManager] 存储语音AI回复失败，返回None: session={session_id}")
                    except Exception as e:
                        _get_logger().error(f"[DialogueManager] 存储语音AI回复异常: {e}", exc_info=True)

                    # 步骤2: 触发MemoryAutoTrigger AI回复存储（必须传递message_id）
                    if voice_assistant_msg_id:
                        try:
                            from core.memory.memory_auto_trigger import MemoryAutoTrigger
                            session_id_safe = session_id if session_id else f"session_{user_id}"

                            await MemoryAutoTrigger.on_ai_response(
                                user_id=user_id,
                                session_id=session_id_safe,
                                response=final_answer,
                                message_id=voice_assistant_msg_id,  # 【修复】必须传递message_id
                                thinking=None,
                                tool_calls=None
                            )
                            _get_logger().info(f"[DialogueManager] MemoryAutoTrigger语音AI回复触发成功: user={user_id}, msg_id={voice_assistant_msg_id}")
                        except MemoryStoreError as e:
                            _get_logger().error(f"[DialogueManager] MemoryAutoTrigger语音AI回复存储失败: {e}", exc_info=True)
                            # 【P0修复】存储层失败不中断AgentLoop主循环，大脑与感官解耦
                    else:
                        _get_logger().error(f"[DialogueManager] 无法触发MemoryAutoTrigger语音AI回复: message_id为空，session={session_id}")

                safe_create_task(_store_voice_assistant_msg_and_trigger_async(), name="_store_voice_assistant_msg_and_trigger_async")

                return final_answer

            elif alignment_result.get("type") == "alignment_ongoing":
                # 对齐进行中，返回AI回复继续对话
                ai_response = alignment_result.get("ai_response", "请继续描述您的需求")
                print(f"[WakeWord] 对齐进行中，AI回复: {ai_response[:50]}...")

                # 记录AI回复
                session.chat_history.append({
                    "role": "assistant",
                    "content": ai_response,
                    "timestamp": datetime.now().isoformat()
                })

                # 【Phase 2 Week 3】存储AI回复到数据库（异步）
                asyncio.create_task(
                    self._store_assistant_message_async(
                        session=session,
                        content=ai_response,
                        metadata={"input_mode": "voice", "alignment_type": "ongoing"}
                    )
                )

                return ai_response

            elif alignment_result.get("type") == "alignment_error":
                # 对齐出错
                error_msg = alignment_result.get("message", "对齐过程出错")
                _get_logger().error(f"[DialogueManager] 对齐模式错误: {error_msg}")
                return f"处理您的请求时出现问题: {error_msg}"

            else:
                # 未知结果类型
                _get_logger().warning(f"[DialogueManager] 未知的对齐结果类型: {alignment_result.get('type')}")
                return "处理您的请求时出现问题，请重试"

        except MemoryRetrievalError as e:
            # 【语音降级修复】系统级异常 - 记忆检索失败，不降级，直接报错
            # 记忆检索是系统级依赖，降级到文本也不能解决问题
            _get_logger().error(f"[DialogueManager] 记忆检索失败 [SILENT_FAILURE_BLOCKED]: {e}")
            return "系统记忆服务暂时不可用，请稍后重试。"

        except AIConnectionError as e:
            # 【语音降级修复】系统级异常 - AI连接失败，不降级，直接报错
            # AI连接异常影响所有输入模式，降级无意义
            _get_logger().error(f"[DialogueManager] AI连接失败 [SILENT_FAILURE_BLOCKED]: {e}")
            return "AI服务连接异常，请检查网络或稍后重试。"

        except Exception as e:
            # 【语音降级修复】检查是否是语音特有异常
            if self._is_voice_specific_error(e):
                # 【P0-003修复】语音特有异常，降级到文本处理
                import traceback
                stack_trace = traceback.format_exc()       # 获取完整堆栈
                _get_logger().warning(
                    f"[DialogueManager] 语音特有异常，降级到文本: {e}\n堆栈追踪:\n{stack_trace}"
                )

                # 【P0-003】通知用户语音处理失败，即将切换到文本模式
                self._notify_voice_failure_and_fallback(session.session_id, user_id)

                # 【P0-003】降级到文本处理
                return await self._fallback_to_text(user_id, text, session_id, session, **kwargs)
            else:
                # 非语音特有异常，向上抛出（保持原有行为）
                _get_logger().error(f"[DialogueManager] 非语音异常，向上抛出: {e}")
                raise

    def get_chat_history(
        self,
        user_id: str,
        session_id: str,
        limit: int = 100
    ) -> list[dict]:
        """
        获取用户会话历史

        Args:
            user_id: 用户唯一标识
            session_id: 会话ID
            limit: 返回的最大历史记录数

        Returns:
            List[dict]: 聊天历史记录
        """
        session = self.get_session(user_id, session_id)  # 获取会话
        if session:
            return session.chat_history[-limit:]         # 返回最近N条历史
        return []                                      # 会话不存在返回空列表

    def clear_history(self, user_id: str, session_id: str):
        """
        清空用户会话历史

        Args:
            user_id: 用户唯一标识
            session_id: 会话ID
        """
        session = self.get_session(user_id, session_id)  # 获取会话
        if session:
            session.chat_history.clear()                 # 清空聊天历史
            _get_logger().info(f"[DialogueManager] 清空会话历史: user_id={user_id}, session_id={session_id}")

    async def set_session_mode(
        self,
        user_id: str,
        session_id: str,
        mode: WorkMode
    ):
        """
        设置用户会话模式（Daily/Focus）

        Args:
            user_id: 用户唯一标识
            session_id: 会话ID
            mode: 工作模式
        """
        session = self.get_session(user_id, session_id)  # 获取会话
        if session:
            session.mode = mode                          # 设置工作模式
            try:
                self.user_manager.set_session_context(
                    session_id,
                    "mode",
                    mode.value
                )
            except Exception as e:
                _get_logger().error(
                    f"[DialogueManager] 设置会话模式失败 [SILENT_FAILURE_BLOCKED]: {e}",
                    exc_info=True
                )
            _get_logger().info(f"[DialogueManager] 设置会话模式: user_id={user_id}, mode={mode.value}")

            # 【Phase 2 Week 3】异步更新数据库中的session模式
            if session.db_session_id:
                mode_str = mode.value if hasattr(mode, 'value') else str(mode).lower()
                async def _update_db_mode():
                    try:
                        await self.session_manager.update_session(
                            session.db_session_id,
                            {"mode": mode_str}
                        )
                        _get_logger().debug(f"[DialogueManager] 数据库session模式已更新: {mode_str}")
                    except Exception as e:
                        _get_logger().error(f"[DialogueManager] 更新数据库session模式失败: {e}")
                await _update_db_mode()

    def get_user_sessions(self, user_id: str) -> list[str]:
        """
        获取用户的所有会话ID

        Args:
            user_id: 用户唯一标识

        Returns:
            List[str]: 会话ID列表
        """
        with self._sessions_lock:                        # 获取锁
            return list(self._user_sessions.get(user_id, {}).keys())  # 返回会话ID列表

    def close_session(self, user_id: str, session_id: str):
        """
        关闭用户会话

        Args:
            user_id: 用户唯一标识
            session_id: 会话ID
        """
        with self._sessions_lock:                        # 获取锁
            if user_id in self._user_sessions:
                if session_id in self._user_sessions[user_id]:
                    del self._user_sessions[user_id][session_id]  # 删除会话
                    _get_logger().info(f"[DialogueManager] 关闭会话: user_id={user_id}, session_id={session_id}")

                # 如果用户没有会话了，清理用户条目
                if not self._user_sessions[user_id]:
                    del self._user_sessions[user_id]

    def close_all_user_sessions(self, user_id: str):
        """
        关闭用户的所有会话

        Args:
            user_id: 用户唯一标识
        """
        with self._sessions_lock:                        # 获取锁
            if user_id in self._user_sessions:
                count = len(self._user_sessions[user_id])  # 统计会话数量
                del self._user_sessions[user_id]         # 删除该用户的所有会话
                _get_logger().info(f"[DialogueManager] 关闭用户所有会话: user_id={user_id}, count={count}")

    def get_user_stats(self, user_id: str) -> dict:
        """
        获取用户会话统计

        Args:
            user_id: 用户唯一标识

        Returns:
            Dict: 统计信息
        """
        with self._sessions_lock:                        # 获取锁
            sessions = self._user_sessions.get(user_id, {})  # 获取用户会话
            return {
                "user_id": user_id,                      # 用户ID
                "session_count": len(sessions),          # 会话数量
                "total_messages": sum(len(s.chat_history) for s in sessions.values()),  # 总消息数
                "sessions": [s.to_dict() for s in sessions.values()]  # 会话详情列表
            }

    def get_all_stats(self) -> dict:
        """
        获取全局统计

        Returns:
            Dict: 全局统计信息
        """
        with self._sessions_lock:                        # 获取锁
            total_users = len(self._user_sessions)       # 总用户数
            total_sessions = sum(len(sessions) for sessions in self._user_sessions.values())  # 总会话数
            total_messages = sum(
                len(s.chat_history)
                for sessions in self._user_sessions.values()
                for s in sessions.values()
            )  # 总消息数

            return {
                "total_users": total_users,              # 总用户数
                "total_sessions": total_sessions,        # 总会话数
                "total_messages": total_messages,        # 总消息数
                "users": list(self._user_sessions.keys())  # 用户ID列表
            }

    # =========================================================================
    # 【Phase 2 Week 4】目标对齐引擎集成
    # =========================================================================

    def _get_user_history_for_alignment(self, user_id: str) -> list[dict]:
        """
        获取用户历史记录供对齐引擎使用

        Args:
            user_id: 用户ID

        Returns:
            List[Dict]: 历史记录列表
        """
        try:
            # 获取用户的所有会话历史
            sessions = self._user_sessions.get(user_id, {})
            history = []
            for session in sessions.values():
                history.extend(session.chat_history)
            return history[-20:]  # 返回最近20条
        except Exception as e:
            _get_logger().error(
                f"[DialogueManager] 获取对齐历史失败 [SILENT_FAILURE_BLOCKED]: {e}",
                exc_info=True
            )
            return []

    def get_context(self, user_id: str, session_id: str | None = None) -> dict[str, Any]:
        """
        【Phase 2 Week 4】获取用户上下文供对齐引擎使用

        Args:
            user_id: 用户ID
            session_id: 可选的会话ID

        Returns:
            Dict[str, Any]: 上下文信息
        """
        context = {
            "user_id": user_id,
            "timestamp": datetime.now().isoformat()
        }

        # 如果有指定会话，添加会话历史
        if session_id:
            session = self.get_session(user_id, session_id)
            if session:
                context["chat_history"] = session.chat_history[-10:]  # 最近10条
                context["session_id"] = session_id
                context["mode"] = session.mode.value if hasattr(session.mode, 'value') else str(session.mode)
        else:
            # 获取用户所有会话的最新历史
            sessions = self._user_sessions.get(user_id, {})
            all_history = []
            for session in sessions.values():
                all_history.extend(session.chat_history)
            all_history.sort(key=lambda x: x.get("timestamp", ""))
            context["chat_history"] = all_history[-10:]

        return context

    async def handle_user_input(
        self,
        user_id: str,
        text: str,
        session_id: str | None = None
    ) -> dict[str, Any]:
        """
        【Phase 2 Week 4】统一用户输入处理入口（集成目标对齐引擎）

        流程：
        1. 调用目标对齐引擎分析输入
        2. 根据对齐状态决定后续流程：
           - need_clarification: 返回澄清对话框
           - need_confirmation: 返回确认提示
           - aligned: 继续执行任务

        Args:
            user_id: 用户唯一标识
            text: 用户输入文本
            session_id: 会话ID，不传则使用默认会话

        Returns:
            Dict[str, Any]: 处理结果，格式如下：
                - type: 'aligned' / 'clarification_needed' / 'confirmation_needed'
                - 其他字段根据类型不同
        """
        try:
            _get_logger().info(
                f"[DialogueManager] handle_user_input: user_id={user_id}, text={text[:50]}..."
            )

            # 【Step 1】目标对齐检查
            context = self.get_context(user_id, session_id)
            alignment_result = self.alignment_engine.process_input(
                user_id, text, context
            )

            # 【Step 2】根据对齐状态处理
            if alignment_result.status == AlignmentStatus.NEED_CLARIFICATION:
                # 需要澄清
                _get_logger().info(
                    f"[DialogueManager] 目标对齐: 需要澄清, user_id={user_id}"
                )

                # 发送WebSocket事件通知前端
                self._emit_alignment_event(
                    user_id=user_id,
                    session_id=session_id,
                    event_type="clarification_needed",
                    data={
                        "question": alignment_result.question,
                        "options": alignment_result.options,
                        "understanding": alignment_result.understanding.to_dict() if alignment_result.understanding else None
                    }
                )

                return {
                    "type": "clarification_needed",
                    "question": alignment_result.question,
                    "options": alignment_result.options,
                    "understanding": alignment_result.understanding.to_dict() if alignment_result.understanding else None,
                    "session_id": session_id
                }

            elif alignment_result.status == AlignmentStatus.NEED_CONFIRMATION:
                # 需要确认
                _get_logger().info(
                    f"[DialogueManager] 目标对齐: 需要确认, user_id={user_id}"
                )

                # 发送WebSocket事件通知前端
                self._emit_alignment_event(
                    user_id=user_id,
                    session_id=session_id,
                    event_type="confirmation_needed",
                    data={
                        "question": alignment_result.question,
                        "understanding": alignment_result.understanding.to_dict() if alignment_result.understanding else None
                    }
                )

                return {
                    "type": "confirmation_needed",
                    "question": alignment_result.question,
                    "understanding": alignment_result.understanding.to_dict() if alignment_result.understanding else None,
                    "session_id": session_id
                }

            else:
                # 已对齐，继续执行
                _get_logger().info(
                    f"[DialogueManager] 目标对齐: 已对齐，开始执行, user_id={user_id}"
                )

                # 清理对齐会话（执行完成后）
                self.alignment_engine.complete_alignment(user_id)

                # 执行任务
                execution_result = await self.execute_task(
                    user_id=user_id,
                    understanding=alignment_result.understanding,
                    session_id=session_id
                )

                return {
                    "type": "aligned",
                    "execution_result": execution_result,
                    "understanding": alignment_result.understanding,
                    "session_id": session_id
                }

        except Exception as e:
            # 【异常处理】对齐引擎失败时降级到直接执行
            _get_logger().error(
                f"[DialogueManager] 目标对齐引擎异常，降级到直接执行: {e}",
                exc_info=True
            )

            # 降级处理：直接执行任务
            try:
                execution_result = await self.execute_task(
                    user_id=user_id,
                    understanding={"original_input": text},
                    session_id=session_id
                )
                return {
                    "type": "aligned",
                    "execution_result": execution_result,
                    "understanding": {"original_input": text},
                    "session_id": session_id,
                    "fallback": True
                }
            except Exception as exec_error:
                _get_logger().error(
                    f"[DialogueManager] 降级执行也失败: {exec_error}",
                    exc_info=True
                )
                return {
                    "type": "error",
                    "error": "处理请求时遇到问题，请稍后重试",
                    "session_id": session_id
                }

    async def handle_clarification_response(
        self,
        user_id: str,
        response: str,
        session_id: str | None = None,
        selected_option: str | None = None
    ) -> dict[str, Any]:
        """
        【Phase 2 Week 4】处理用户对澄清问题的回复

        Args:
            user_id: 用户ID
            response: 用户回复文本
            session_id: 会话ID
            selected_option: 用户选择的选项ID（如果有）

        Returns:
            Dict[str, Any]: 处理结果
        """
        try:
            _get_logger().info(
                f"[DialogueManager] 处理澄清回复: user_id={user_id}, response={response[:50]}..."
            )

            # 构造完整的回复（选项ID + 文本）
            full_response = response
            if selected_option and selected_option != "other":
                full_response = f"选择选项 {selected_option}: {response}"

            # 继续对齐流程
            context = self.get_context(user_id, session_id)
            alignment_result = self.alignment_engine.process_input(
                user_id, full_response, context
            )

            # 处理结果（类似handle_user_input）
            if alignment_result.status == AlignmentStatus.NEED_CONFIRMATION:
                # 现在足够清晰，需要确认
                self._emit_alignment_event(
                    user_id=user_id,
                    session_id=session_id,
                    event_type="confirmation_needed",
                    data={
                        "question": alignment_result.question,
                        "understanding": alignment_result.understanding.to_dict() if alignment_result.understanding else None
                    }
                )

                return {
                    "type": "confirmation_needed",
                    "question": alignment_result.question,
                    "understanding": alignment_result.understanding.to_dict() if alignment_result.understanding else None,
                    "session_id": session_id
                }

            elif alignment_result.status == AlignmentStatus.NEED_CLARIFICATION:
                # 仍然需要更多澄清
                self._emit_alignment_event(
                    user_id=user_id,
                    session_id=session_id,
                    event_type="clarification_needed",
                    data={
                        "question": alignment_result.question,
                        "options": alignment_result.options
                    }
                )

                return {
                    "type": "clarification_needed",
                    "question": alignment_result.question,
                    "options": alignment_result.options,
                    "session_id": session_id
                }

            else:
                # 已对齐，执行
                self.alignment_engine.complete_alignment(user_id)
                execution_result = await self.execute_task(
                    user_id=user_id,
                    understanding=alignment_result.understanding,
                    session_id=session_id
                )

                return {
                    "type": "aligned",
                    "execution_result": execution_result,
                    "understanding": alignment_result.understanding,
                    "session_id": session_id
                }

        except Exception as e:
            _get_logger().error(
                f"[DialogueManager] 处理澄清回复失败: {e}",
                exc_info=True
            )
            return {
                "type": "error",
                "error": "处理澄清回复时出错",
                "session_id": session_id
            }

    async def handle_confirmation_response(
        self,
        user_id: str,
        confirmed: bool,
        session_id: str | None = None,
        correction: str | None = None
    ) -> dict[str, Any]:
        """
        【Phase 2 Week 4】处理用户确认回复

        Args:
            user_id: 用户ID
            confirmed: 是否确认（True=确认，False=否认）
            session_id: 会话ID
            correction: 用户修正描述（如果否认）

        Returns:
            Dict[str, Any]: 处理结果
        """
        try:
            _get_logger().info(
                f"[DialogueManager] 处理确认回复: user_id={user_id}, confirmed={confirmed}"
            )

            if confirmed:
                # 用户确认，获取之前的理解并执行
                context = self.get_context(user_id, session_id)
                # 触发一次process_input来完成对齐
                alignment_result = self.alignment_engine.process_input(
                    user_id, "是的，确认执行", context
                )

                if alignment_result.status == AlignmentStatus.ALIGNED:
                    self.alignment_engine.complete_alignment(user_id)
                    execution_result = await self.execute_task(
                        user_id=user_id,
                        understanding=alignment_result.understanding,
                        session_id=session_id
                    )

                    return {
                        "type": "aligned",
                        "execution_result": execution_result,
                        "understanding": alignment_result.understanding,
                        "session_id": session_id
                    }
            else:
                # 用户否认，需要重新澄清
                if correction:
                    # 用户提供了修正，当作新的澄清回复处理
                    return await self.handle_clarification_response(
                        user_id=user_id,
                        response=correction,
                        session_id=session_id
                    )
                else:
                    # 没有修正，要求重新澄清
                    context = self.get_context(user_id, session_id)
                    alignment_result = self.alignment_engine.process_input(
                        user_id, "不是，请重新理解", context
                    )

                    if alignment_result.status == AlignmentStatus.NEED_CLARIFICATION:
                        self._emit_alignment_event(
                            user_id=user_id,
                            session_id=session_id,
                            event_type="clarification_needed",
                            data={
                                "question": alignment_result.question,
                                "options": alignment_result.options
                            }
                        )

                        return {
                            "type": "clarification_needed",
                            "question": alignment_result.question,
                            "options": alignment_result.options,
                            "session_id": session_id
                        }

            # 默认返回
            return {
                "type": "error",
                "error": "无法处理确认回复",
                "session_id": session_id
            }

        except Exception as e:
            _get_logger().error(
                f"[DialogueManager] 处理确认回复失败: {e}",
                exc_info=True
            )
            return {
                "type": "error",
                "error": "处理确认回复时出错",
                "session_id": session_id
            }

    async def execute_task(
        self,
        user_id: str,
        understanding: dict[str, Any],
        session_id: str | None = None
    ) -> dict[str, Any]:
        """
        【Phase 2 Week 4】执行任务（根据对齐后的理解）

        Args:
            user_id: 用户ID
            understanding: AI理解结果
            session_id: 会话ID

        Returns:
            Dict[str, Any]: 执行结果
        """
        try:
            # 从understanding中提取原始输入或任务描述
            task_description = understanding.get("original_input", "")
            if not task_description and "intent" in understanding:
                task_description = f"执行{understanding['intent']}任务"

            _get_logger().info(
                f"[DialogueManager] 执行任务: user_id={user_id}, task={task_description[:50]}..."
            )

            # 使用现有的handle_text_input_with_tools来执行任务
            result = await self.handle_text_input_with_tools(
                user_id=user_id,
                text=task_description,
                session_id=session_id
            )

            return result

        except Exception as e:
            _get_logger().error(
                f"[DialogueManager] 任务执行失败: {e}",
                exc_info=True
            )
            return {
                "success": False,
                "error": str(e),
                "content": "任务执行失败"
            }

    def _emit_alignment_event(
        self,
        user_id: str,
        session_id: str | None,
        event_type: str,
        data: dict[str, Any]
    ):
        """
        【Phase 2 Week 4】发送对齐事件到前端

        Args:
            user_id: 用户ID
            session_id: 会话ID
            event_type: 事件类型
            data: 事件数据
        """
        try:
            from core.sync.realtime_sync import get_realtime_sync_manager
            sync = get_realtime_sync_manager()

            event_data = {
                "user_id": user_id,
                "session_id": session_id,
                "alignment_type": event_type,
                "timestamp": datetime.now().isoformat(),
                **data
            }

            sync.emit_event(
                event_type=event_type,
                session_id=session_id or f"user_{user_id}",
                data=event_data
            )

            _get_logger().debug(
                f"[DialogueManager] 对齐事件已发送: {event_type}"
            )

        except Exception as e:
            _get_logger().error(
                f"[DialogueManager] 发送对齐事件失败: {e}"
            )
            # 不阻塞主流程

    def cleanup_expired_sessions(self, max_inactive_seconds: float = 3600):
        """
        清理过期会话

        Args:
            max_inactive_seconds: 最大不活跃时间（秒）
        """
        current_time = datetime.now()                    # 当前时间
        expired_sessions = []                            # 过期会话列表

        with self._sessions_lock:                        # 获取锁
            for user_id, sessions in list(self._user_sessions.items()):
                for session_id, session in list(sessions.items()):
                    # 计算不活跃时间
                    inactive_seconds = (current_time - session.last_active).total_seconds()
                    if inactive_seconds > max_inactive_seconds:
                        expired_sessions.append((user_id, session_id))  # 记录过期会话

        for user_id, session_id in expired_sessions:
            self.close_session(user_id, session_id)      # 关闭过期会话

        if expired_sessions:
            _get_logger().info(f"[DialogueManager] 清理 {len(expired_sessions)} 个过期会话")

    # ═══════════════════════════════════════════════════════════════
    # 【Phase 1 Week 2】Coordinator 集成: 模式切换状态保存/恢复
    # ═══════════════════════════════════════════════════════════════

    def save_for_mode_switch(
        self,
        user_id: str,
        session_id: str,
        include_history: bool = True
    ) -> dict[str, Any]:
        """
        为模式切换保存会话状态

        Args:
            user_id: 用户ID
            session_id: 会话ID
            include_history: 是否包含完整聊天历史

        Returns:
            状态字典
        """
        session = self.get_session(user_id, session_id)
        if not session:
            return {
                "user_id": user_id,
                "session_id": session_id,
                "exists": False,
                "saved_at": time.time()
            }

        state = {
            "user_id": user_id,
            "session_id": session_id,
            "exists": True,
            "mode": session.mode.value if hasattr(session.mode, 'value') else str(session.mode),
            "metadata": session.metadata.copy(),
            "db_session_id": session.db_session_id,
            "saved_at": time.time()
        }

        if include_history:
            # 保存聊天历史（限制条数避免过大）
            state["chat_history"] = session.chat_history[-50:].copy()  # 最近50条
            state["history_count"] = len(session.chat_history)

        _get_logger().debug(
            f"[DialogueManager] 会话状态已保存: user={user_id}, session={session_id}, "
            f"history={len(state.get('chat_history', []))}"
        )

        return state

    def restore_after_mode_switch(
        self,
        state: dict[str, Any],
        strategy: str = "merge"  # "merge" | "replace" | "append"
    ) -> bool:
        """
        模式切换后恢复会话状态

        Args:
            state: 保存的状态
            strategy: 恢复策略
                - merge: 合并历史（去重）
                - replace: 完全替换
                - append: 追加到当前历史

        Returns:
            是否成功
        """
        user_id = state.get("user_id")
        session_id = state.get("session_id")

        if not user_id or not session_id:
            _get_logger().warning("[DialogueManager] 恢复状态失败: 缺少user_id或session_id")
            return False

        if not state.get("exists"):
            _get_logger().debug(f"[DialogueManager] 原会话不存在，无需恢复: {session_id}")
            return True

        session = self.get_session(user_id, session_id)
        if not session:
            # 会话已被清理，尝试重建
            _get_logger().info(f"[DialogueManager] 会话不存在，尝试重建: {session_id}")
            from core.mode.work_mode_manager import WorkMode
            saved_mode = state.get("mode", "daily")
            try:
                mode = WorkMode(saved_mode)
            except Exception:
                mode = WorkMode.DAILY
            session = self.create_session(user_id, session_id, mode=mode)

        try:
            saved_history = state.get("chat_history", [])

            if strategy == "replace":
                # 完全替换
                session.chat_history = saved_history.copy()
                _get_logger().debug(f"[DialogueManager] 聊天历史已替换: {len(saved_history)}条")

            elif strategy == "merge":
                # 合并去重
                current_history = session.chat_history
                seen = set()
                merged = []

                for msg in current_history + saved_history:
                    # 使用内容和角色作为唯一键
                    content = msg.get("content", "")
                    role = msg.get("role", "")
                    msg_key = (role, content[:100])  # 取前100字符避免过长

                    if msg_key not in seen:
                        seen.add(msg_key)
                        merged.append(msg)

                session.chat_history = merged[-100:]  # 保留最近100条
                _get_logger().debug(
                    f"[DialogueManager] 聊天历史已合并: "
                    f"当前{len(current_history)} + 保存{len(saved_history)} = 合并{len(merged)}"
                )

            elif strategy == "append":
                # 追加到末尾
                session.chat_history.extend(saved_history)
                if len(session.chat_history) > 100:
                    session.chat_history = session.chat_history[-100:]
                _get_logger().debug(f"[DialogueManager] 聊天历史已追加: +{len(saved_history)}条")

            # 恢复其他状态
            if state.get("metadata"):
                session.metadata.update(state["metadata"])

            return True

        except Exception as e:
            _get_logger().error(
                f"[DialogueManager] 恢复会话状态失败 [SILENT_FAILURE_BLOCKED]: {e}",
                exc_info=True
            )
            return False

    def create_mode_switch_checkpoint(self, user_id: str, session_id: str) -> str:
        """
        创建模式切换检查点（轻量级）

        返回检查点ID，可用于快速恢复
        """
        checkpoint_id = f"dm_checkpoint_{user_id}_{session_id}_{int(time.time())}"

        state = self.save_for_mode_switch(user_id, session_id, include_history=True)

        # 存储在内存中（可通过Coordinator统一管理）
        if not hasattr(self, '_mode_switch_checkpoints'):
            self._mode_switch_checkpoints = {}

        self._mode_switch_checkpoints[checkpoint_id] = state

        _get_logger().info(f"[DialogueManager] 模式切换检查点已创建: {checkpoint_id}")
        return checkpoint_id

    def restore_from_mode_switch_checkpoint(self, checkpoint_id: str, strategy: str = "merge") -> bool:
        """从模式切换检查点恢复"""
        if not hasattr(self, '_mode_switch_checkpoints'):
            return False

        state = self._mode_switch_checkpoints.get(checkpoint_id)
        if not state:
            _get_logger().warning(f"[DialogueManager] 检查点不存在: {checkpoint_id}")
            return False

        return self.restore_after_mode_switch(state, strategy)

    def cleanup_mode_switch_checkpoints(self, max_age_seconds: float = 3600) -> int:
        """清理过期的模式切换检查点"""
        if not hasattr(self, '_mode_switch_checkpoints'):
            return 0

        cutoff = time.time() - max_age_seconds
        to_delete = []

        for checkpoint_id, state in self._mode_switch_checkpoints.items():
            if state.get("saved_at", 0) < cutoff:
                to_delete.append(checkpoint_id)

        for checkpoint_id in to_delete:
            del self._mode_switch_checkpoints[checkpoint_id]

        if to_delete:
            _get_logger().info(f"[DialogueManager] 清理 {len(to_delete)} 个过期检查点")

        return len(to_delete)

    # =========================================================================
    # 【用户级并发控制】防止一个用户同时运行多个AgentLoop
    # =========================================================================

    def _acquire_user_loop_lock(self, user_id: str, timeout: float = 5.0) -> threading.Event:
        """
        获取用户循环锁

        在开始新对话前调用，确保一个用户同时只能有一个AgentLoop运行。
        如果用户已有活动循环，会终止旧循环并等待其结束。

        Args:
            user_id: 用户唯一标识
            timeout: 等待旧循环结束的最大时间（秒），默认5秒

        Returns:
            threading.Event: 新循环的终止事件，循环应定期检查此事件
        """
        with self._loop_lock:
            # 检查是否已有活动循环
            if user_id in self._active_loops:
                _get_logger().warning(
                    f"[DialogueManager] 用户 {user_id} 已有活动循环，正在终止旧循环..."
                )
                # 设置终止信号
                old_event = self._active_loops[user_id]
                old_event.set()

                # 【修复】等待旧循环结束（最多timeout秒）
                wait_start = time.time()
                while user_id in self._active_loops and time.time() - wait_start < timeout:
                    time.sleep(0.1)

                if user_id in self._active_loops:
                    _get_logger().warning(
                        f"[DialogueManager] 用户 {user_id} 的旧循环未在{timeout}秒内结束，强制继续"
                    )
                else:
                    _get_logger().debug(
                        f"[DialogueManager] 用户 {user_id} 的旧循环已正常结束"
                    )

            # 创建新的终止事件
            stop_event = threading.Event()
            self._active_loops[user_id] = stop_event

            _get_logger().info(f"[DialogueManager] 用户 {user_id} 的新循环已启动")
            return stop_event

    def _release_user_loop_lock(self, user_id: str, expected_event: threading.Event):
        """
        释放用户循环锁

        在AgentLoop结束时调用，清理用户的活动循环记录。
        只有持有正确event的循环才能释放锁，防止误删其他循环的记录。

        Args:
            user_id: 用户唯一标识
            expected_event: 期望的终止事件
        """
        with self._loop_lock:
            if user_id in self._active_loops:
                if self._active_loops[user_id] is expected_event:
                    del self._active_loops[user_id]
                    _get_logger().info(f"[DialogueManager] 用户 {user_id} 的循环已正常结束")
                else:
                    _get_logger().debug(
                        f"[DialogueManager] 用户 {user_id} 的循环锁已被新循环接管，跳过释放"
                    )
            else:
                _get_logger().debug(f"[DialogueManager] 用户 {user_id} 无活动循环记录")

    async def _acquire_user_loop_lock_async(
        self, user_id: str, timeout: float = 5.0, reuse_existing: bool = False
    ) -> threading.Event:
        """
        【异步版本】获取用户循环锁，避免在 async 上下文中阻塞事件循环。
        与 _acquire_user_loop_lock 逻辑相同，但使用 asyncio.sleep 替代 time.sleep。

        Args:
            reuse_existing: 为 True 时，若用户已有活动循环则直接复用其 stop_event，
                            不终止旧循环、不创建新事件。用于避免多层调用重复获取锁。
        """
        print(f"[DEBUG-Lock] acquire user_id={user_id}, reuse_existing={reuse_existing}, active={list(self._active_loops.keys())}", flush=True)
        with self._loop_lock:
            if user_id in self._active_loops:
                existing_event = self._active_loops[user_id]
                if reuse_existing:
                    if not existing_event.is_set():
                        _get_logger().debug(
                            f"[DialogueManager] 用户 {user_id} 复用现有循环锁"
                        )
                        print(f"[DEBUG-Lock] reuse existing stop_event for {user_id}", flush=True)
                        return existing_event
                    # 事件已被设置：旧循环正在终止，等待锁交接完成，不能复用旧事件
                    _get_logger().debug(
                        f"[DialogueManager] 用户 {user_id} 现有循环锁正在终止，等待交接"
                    )
                else:
                    _get_logger().warning(
                        f"[DialogueManager] 用户 {user_id} 已有活动循环，正在终止旧循环..."
                    )
                    print(f"[DEBUG-Lock] terminate old loop for {user_id}", flush=True)
                    existing_event.set()

        import asyncio
        import time
        wait_start = time.time()
        while time.time() - wait_start < timeout:
            with self._loop_lock:
                if user_id in self._active_loops:
                    ev = self._active_loops[user_id]
                    if reuse_existing and not ev.is_set():
                        # 新循环锁已交接完成
                        return ev
                else:
                    # 旧循环已释放，跳出等待
                    break
            await asyncio.sleep(0.1)

        if user_id in self._active_loops:
            _get_logger().warning(
                f"[DialogueManager] 用户 {user_id} 的旧循环未在{timeout}秒内结束，强制继续"
            )
        else:
            _get_logger().debug(
                f"[DialogueManager] 用户 {user_id} 的旧循环已正常结束"
            )

        with self._loop_lock:
            if reuse_existing and user_id in self._active_loops:
                ev = self._active_loops[user_id]
                if not ev.is_set():
                    return ev
            stop_event = threading.Event()
            self._active_loops[user_id] = stop_event
            _get_logger().info(f"[DialogueManager] 用户 {user_id} 的新循环已启动")
            return stop_event

    async def _release_user_loop_lock_async(self, user_id: str, expected_event: threading.Event):
        """
        【异步版本】释放用户循环锁。
        """
        with self._loop_lock:
            if user_id in self._active_loops:
                if self._active_loops[user_id] is expected_event:
                    del self._active_loops[user_id]
                    _get_logger().info(f"[DialogueManager] 用户 {user_id} 的循环已正常结束")
                else:
                    _get_logger().debug(
                        f"[DialogueManager] 用户 {user_id} 的循环锁已被新循环接管，跳过释放"
                    )
            else:
                _get_logger().debug(f"[DialogueManager] 用户 {user_id} 无活动循环记录")

    def stop_user_loop(self, user_id: str) -> bool:
        """
        强制终止用户的AgentLoop

        外部调用此方法可强制终止指定用户的所有AgentLoop。
        用于用户主动取消、系统维护等场景。

        Args:
            user_id: 用户唯一标识

        Returns:
            bool: 是否成功终止（True=有活动循环被终止，False=无活动循环）
        """
        with self._loop_lock:
            if user_id in self._active_loops:
                _get_logger().info(f"[DialogueManager] 强制终止用户 {user_id} 的AgentLoop")
                self._active_loops[user_id].set()
                del self._active_loops[user_id]
                return True
            return False

    def on_work_start(self, user_id: str | None = None) -> None:
        """
        工作开始时调用，通知相关子系统进入工作模式。

        【修复】DialogueManager 缺少 on_work_start 对称方法，
        导致 Consciousness 的 on_work_start() 从未被调用，弱连接引擎等状态未初始化。

        Args:
            user_id: 用户唯一标识。如果为 None，则尝试通知所有活跃会话的用户。
        """
        _get_logger().info(f"[DialogueManager] 工作开始通知: user_id={user_id}")

        def _notify_user(user: str):
            """通知单个用户的 consciousness 工作开始"""
            try:
                from core.consciousness.Consciousness import get_consciousness
                consciousness = get_consciousness(user)
                if consciousness and hasattr(consciousness, 'on_work_start'):
                    consciousness.on_work_start()
                    _get_logger().info(f"[DialogueManager] 已通知用户 {user} 的 consciousness 进入工作模式")
            except Exception as e:
                _get_logger().warning(f"[DialogueManager] 通知用户 {user} 工作开始失败: {e}")

        if user_id:
            _notify_user(user_id)
        else:
            try:
                with self._sessions_lock:
                    for uid in list(self._user_sessions.keys()):
                        _notify_user(uid)
            except Exception as e:
                _get_logger().warning(f"[DialogueManager] 批量通知工作开始失败: {e}")

    def on_work_end(self, user_id: str | None = None) -> None:
        """
        工作结束时调用，通知相关子系统退出工作模式。

        【修复】session_api.py (原 interrupt_api.py 合并) 调用此方法，
        但 DialogueManager 在合并重构时遗漏了该方法。

        Args:
            user_id: 用户唯一标识。如果为 None，则尝试通知所有活跃会话的用户。
        """
        _get_logger().info(f"[DialogueManager] 工作结束通知: user_id={user_id}")

        def _notify_user(user: str):
            """通知单个用户的 consciousness 工作结束"""
            try:
                from core.consciousness.Consciousness import get_consciousness
                consciousness = get_consciousness(user)
                if consciousness and hasattr(consciousness, 'on_work_end'):
                    consciousness.on_work_end()
                    _get_logger().info(f"[DialogueManager] 已通知用户 {user} 的 consciousness 退出工作模式")
            except Exception as e:
                _get_logger().warning(f"[DialogueManager] 通知用户 {user} 工作结束失败: {e}")

        if user_id:
            _notify_user(user_id)
        else:
            # 如果没有指定 user_id，遍历所有活跃会话
            try:
                with self._sessions_lock:
                    for uid in list(self._user_sessions.keys()):
                        _notify_user(uid)
            except Exception as e:
                _get_logger().warning(f"[DialogueManager] 批量通知工作结束失败: {e}")

    # =========================================================================
    # 【后台任务并发管理】
    # =========================================================================

    def get_active_background_task(self, user_id: str) -> asyncio.Task | None:
        """获取用户当前正在后台执行的任务句柄"""
        return self._user_background_tasks.get(user_id)

    def has_active_background_task(self, user_id: str) -> bool:
        """检查用户是否有正在后台执行的任务"""
        # 1. 检查已注册的后台任务句柄
        task = self._user_background_tasks.get(user_id)
        if task is not None and not task.done():
            return True
        # 2. 【修复】检查用户级循环锁：任务刚启动、句柄尚未写入时也能识别为活跃
        with self._loop_lock:
            stop_event = self._active_loops.get(user_id)
        if stop_event is not None:
            return not stop_event.is_set()
        return False

    def _on_background_task_done(self, user_id: str, task: asyncio.Task):
        """
        后台任务完成/失败/取消时的回调。
        负责清理资源和推送完成通知。
        """
        is_paused = False
        try:
            if task.cancelled():
                _get_logger().info(f"[DialogueManager] 用户 {user_id} 的后台任务被取消")
            else:
                exc = task.exception()
                if exc:
                    _get_logger().error(f"[DialogueManager] 用户 {user_id} 的后台任务失败: {exc}")
                else:
                    result = task.result()
                    if result == "[PAUSED]":
                        _get_logger().info(f"[DialogueManager] 用户 {user_id} 的后台任务已暂停（插话）")
                        is_paused = True
                    else:
                        _get_logger().info(f"[DialogueManager] 用户 {user_id} 的后台任务完成")
                        # TODO: 通过 WebSocket 推送任务完成通知
                        # 需要接入现有的 websocket 广播机制
        except Exception as e:
            _get_logger().error(f"[DialogueManager] 后台任务回调异常: {e}")
        finally:
            # 【P1】插话暂停时保留任务快照和句柄，供恢复使用
            if not is_paused:
                current_task = self._user_background_tasks.get(user_id)
                if current_task is not None and current_task is task:
                    self._user_background_tasks.pop(user_id, None)
                else:
                    _get_logger().debug(f"[DialogueManager] 跳过清理：任务已被替换 user={user_id}")
                with self._snapshot_lock:
                    self._user_task_snapshots.pop(user_id, None)
                self._pause_requests.pop(user_id, None)
                self._interruption_requests.pop(user_id, None)
                self._last_paused_task_id.pop(user_id, None)
            else:
                _get_logger().info(f"[DialogueManager] 保留暂停任务快照: user={user_id}")
                # AgentLoop 在插话退出前已经设置了 _last_paused_task_id，此处不要覆盖

    def _cancel_background_task(self, user_id: str) -> bool:
        """取消用户的后台任务并清理资源"""
        task = self._user_background_tasks.get(user_id)
        if task and not task.done():
            task.cancel()
            _get_logger().info(f"[DialogueManager] 已取消用户 {user_id} 的后台任务")
        self._user_background_tasks.pop(user_id, None)
        with self._snapshot_lock:
            self._user_task_snapshots.pop(user_id, None)
            self._user_task_snapshots.pop(user_id + "_realtime", None)
        self._interruption_requests.pop(user_id, None)
        self._last_paused_task_id.pop(user_id, None)
        # 【P1修复】主动清理 capture/detector，避免资源泄漏
        realtime_captures = getattr(self, '_realtime_captures', {})
        cap = realtime_captures.pop(user_id, None)
        if cap:
            with contextlib.suppress(Exception):
                cap.stop()
        realtime_detectors = getattr(self, '_realtime_detectors', {})
        realtime_detectors.pop(user_id, None)
        self._pause_requests.pop(user_id, None)
        return True

    def is_user_loop_running(self, user_id: str) -> bool:
        """
        检查用户是否有活动循环

        Args:
            user_id: 用户唯一标识

        Returns:
            bool: 是否有活动循环在运行
        """
        with self._loop_lock:
            return user_id in self._active_loops and not self._active_loops[user_id].is_set()

    def get_running_loops_info(self) -> dict[str, Any]:
        """
        获取所有活动循环的信息

        Returns:
            Dict: 包含活动循环统计信息的字典
        """
        with self._loop_lock:
            return {
                "running_users": list(self._active_loops.keys()),
                "active_count": len(self._active_loops),
                "timestamp": datetime.now().isoformat()
            }

    async def handle_input(self, user_id: str, text: str, session_id: str,
                     input_mode: InputMode = InputMode.AUTO,
                     voice_instance=None):
        """
        统一输入处理入口

        【生命化改造】支持 AUTO 模式：AI 自主判断输入意图
        - 纯问答 (chat) → 快速通道，不走 AgentLoop
        - 明确指令 (direct_task) → 直接进入 AgentLoop 执行
        - 模糊需求 (ambiguous) → 聊天对齐确认

        Args:
            user_id: 用户ID
            text: 输入文本
            session_id: 会话ID
            input_mode: 输入方式，默认 AUTO（AI 自主判断）
            voice_instance: 语音实例（语音输入时传入）
        """
        _get_logger().info(f"[Dialogue] 输入方式: {input_mode.value}, 内容: {text[:50]}")
        try:
            if input_mode == InputMode.AUTO:
                # 优先尝试意识线程意图判断，取代 classify_voice_intent 的硬编码判断
                mode = "task"
                confidence = 5
                reasoning = "default"
                task_plan = []
                context_flag = None

                # 【P1】长任务中断恢复：用户插话检测（在意识线程判断之前）
                # 如果当前有活跃后台任务，且输入不是显式控制/继续/取消，则视为插话。
                # 直接走 quick_chat 快速回答，同时把插话文本暂存到 _interruption_requests，
                # 供 AgentLoop 下一轮检查点保存后返回 [PAUSED]。
                # 【P1-修复】明确任务/视觉请求不应视为插话，应作为新任务启动
                has_active = self.has_active_background_task(user_id)
                if has_active:
                    lower_text = text.strip().lower()
                    from core.constants import FORCE_TASK_KEYWORDS, FORCE_VISION_KEYWORDS
                    is_force_task = any(kw in lower_text for kw in FORCE_TASK_KEYWORDS)
                    is_force_vision = any(kw in lower_text for kw in FORCE_VISION_KEYWORDS)
                    is_control_or_resume = any(
                        kw in lower_text
                        for kw in [
                            "继续", "恢复", "接着做", "resume", "continue",
                            "取消", "停止", "终止", "cancel", "stop",
                            "暂停", "等一下", "pause", "别做了", "不做了"
                        ]
                    )
                    if not is_control_or_resume and not is_force_task and not is_force_vision:
                        self._interruption_requests[user_id] = text
                        _get_logger().info(
                            f"[DialogueManager] 检测到用户插话，请求暂停当前任务: {text[:50]}"
                        )
                        # P0兼容：插话时立即暂停当前后台任务，便于后续恢复
                        with contextlib.suppress(Exception):
                            await self._handle_task_control(user_id, "pause", text, session_id)
                        return await self._handle_quick_chat(
                            user_id, text, session_id, voice_instance,
                            active_task_hint=True
                        )

                # P0兼容：任务控制/状态查询优先走旧路径，避免新路径误分类
                from core.constants import is_task_control_command, is_task_status_query
                control_type = is_task_control_command(text)
                if control_type:
                    _get_logger().info(f"[P0] task_control override: {control_type}")
                    return await self._handle_task_control(user_id, control_type, text, session_id)
                if has_active and is_task_status_query(text):
                    _get_logger().info("[P0] task_status_query override")
                    return await self._handle_quick_chat(
                        user_id, text, session_id, voice_instance, active_task_hint=True
                    )

                # ═══════════════════════════════════════════════════════════════
                # P0 主权-翻译-执行-记忆四层架构新路径
                # 当 consciousness.self_drive 开启时，由 L1 裁决， DialogueManager 纯执行
                # ═══════════════════════════════════════════════════════════════
                try:
                    from core.consciousness.Consciousness import get_consciousness
                    consciousness = get_consciousness(user_id)
                    _get_logger().info(
                        f"[P0] handle_input AUTO user={user_id}, "
                        f"self_drive={getattr(consciousness, '_self_drive', False)}, "
                        f"receive_user_input_callable={callable(getattr(consciousness, 'receive_user_input', None))}"
                    )
                    if getattr(consciousness, "_self_drive", False) and callable(getattr(consciousness, "receive_user_input", None)):
                        return await self._handle_input_self_drive(
                            consciousness, user_id, text, session_id, voice_instance
                        )
                except Exception:
                    # self-drive 路径失败时静默降级，继续走旧路径
                    pass

                try:
                    from core.consciousness.Consciousness import get_consciousness
                    consciousness = get_consciousness(user_id)

                    # 【P0修复】用户发消息时通知 Consciousness 暂停后台思考
                    try:
                        consciousness.on_user_input()
                    except Exception as e:
                        _get_logger().error(f"[Dialogue] Consciousness.on_user_input() 失败: {e}", exc_info=True)

                    # 获取会话上下文
                    session_for_intent = await self.get_or_create_session(user_id, session_id)
                    intent_context = {
                        "chat_history": session_for_intent.chat_history,
                        "session_id": session_id
                    }

                    # 调用意识线程的意图判断
                    orchestration = await consciousness.orchestrate_input(text, context=intent_context)
                    mode = orchestration.get("mode", "task")
                    confidence = orchestration.get("confidence", 5)
                    reasoning = orchestration.get("reasoning", "")
                    task_plan = orchestration.get("task_plan", [])
                    context_flag = orchestration.get("context_flag")
                    _get_logger().info(f"[Dialogue] 意识线程判断: mode={mode}, confidence={confidence}, reasoning={reasoning[:50]}")
                except Exception as e:
                    # 意识线程判断失败，使用本地关键词 fallback
                    _get_logger().warning(f"[Dialogue] 意识线程判断失败，使用本地 fallback: {e}")
                    from core.constants import classify_user_input
                    has_active = self.has_active_background_task(user_id)
                    classification = classify_user_input(text, has_active_task=has_active)
                    category = classification["category"]
                    if category == "simple_chat":
                        mode = "chat"
                    elif category == "start_monitor":
                        mode = "start_monitor"
                    elif category == "stop_monitor":
                        mode = "stop_monitor"
                    elif category == "potential_monitor":
                        mode = "potential_monitor"
                    else:
                        mode = "task"
                    confidence = classification["confidence"]
                    reasoning = classification["reason"]
                    if category == "task_control":
                        context_flag = "task_control"
                        task_plan = [{"action": "control", "type": classification.get("control_type")}]

                if mode == "chat":
                    # 纯聊天 -> 快速通道，绕过 AgentLoop
                    # 【自我状态】如果意识线程已给出直接回复，使用之
                    direct_reply = orchestration.get("direct_reply")
                    if direct_reply:
                        return await self._handle_quick_chat(
                            user_id, direct_reply, session_id, voice_instance,
                            active_task_hint=context_flag
                        )
                    return await self._handle_quick_chat(
                        user_id, text, session_id, voice_instance,
                        active_task_hint=context_flag
                    )
                elif mode == "stop_monitor":
                    # 停止实时监控
                    return await self._handle_task_control(user_id, "stop_monitor", text, session_id)
                elif mode == "start_monitor":
                    # 启动实时监控
                    return await self._handle_text_task(
                        user_id, text, session_id, voice_instance,
                        mode="start_monitor"
                    )
                elif mode == "potential_monitor":
                    # 轻量 LLM 二次确认监控意图
                    is_monitor = await self._confirm_monitor_intent(text)
                    if is_monitor:
                        return await self._handle_text_task(
                            user_id, text, session_id, voice_instance,
                            mode="start_monitor"
                        )
                    else:
                        return await self._handle_quick_chat(
                            user_id, text, session_id, voice_instance,
                            active_task_hint=context_flag
                        )
                elif mode == "task":
                    # 【干预指令】如果是任务控制指令，不走任务启动流程
                    if context_flag == "task_control" and task_plan:
                        control_action = task_plan[0].get("type") if task_plan else None
                        return await self._handle_task_control(user_id, control_action, text, session_id)
                    # 【P1-修复】明确任务/视觉请求应清除残留插话标记，作为新任务启动
                    lower_text = text.strip().lower()
                    from core.constants import FORCE_TASK_KEYWORDS, FORCE_VISION_KEYWORDS
                    is_force_task = any(kw in lower_text for kw in FORCE_TASK_KEYWORDS)
                    is_force_vision = any(kw in lower_text for kw in FORCE_VISION_KEYWORDS)
                    if (is_force_task or is_force_vision or context_flag == "force_vision") and self._interruption_requests.pop(user_id, None):
                        _get_logger().info(
                            f"[DialogueManager] 明确任务/视觉请求，清理残留插话标记并启动新任务: {text[:50]}"
                        )
                    # 【P1】如果当前已标记为用户插话，即使意识线程误判为 task，
                    # 也不启动新任务，而是走 quick_chat 快速回复，让原 AgentLoop 自行暂停。
                    if self._interruption_requests.get(user_id):
                        _get_logger().info(
                            f"[DialogueManager] 用户 {user_id} 已有插话请求，"
                            f"意识线程误判为 task 已降级为 quick_chat: {text[:50]}"
                        )
                        return await self._handle_quick_chat(
                            user_id, text, session_id, voice_instance,
                            active_task_hint=context_flag
                        )
                    # 任务模式 -> 带有规划步骤，直接执行
                    if task_plan:
                        _get_logger().info(f"[Dialogue] 意识线程生成任务规划: {task_plan}")
                    return await self._handle_text_task(
                        user_id, text, session_id, voice_instance,
                        task_plan=task_plan, context_flag=context_flag,
                        task_package=orchestration.get("task_package")
                    )
                else:
                    # 默认，直接走任务
                    return await self._handle_text_task(user_id, text, session_id, voice_instance)

            elif input_mode == InputMode.TEXT:
                # 文本输入：直接触发任务（向后兼容），但先检查实时监控关键词
                from core.constants import classify_user_input
                has_active = self.has_active_background_task(user_id)
                classification = classify_user_input(text, has_active_task=has_active)
                category = classification["category"]
                if category == "start_monitor":
                    return await self._handle_text_task(
                        user_id, text, session_id, voice_instance, mode="start_monitor"
                    )
                elif category == "stop_monitor":
                    return await self._handle_task_control(user_id, "stop_monitor", text, session_id)
                elif category == "potential_monitor":
                    # 轻量 LLM 二次确认监控意图
                    is_monitor = await self._confirm_monitor_intent(text)
                    if is_monitor:
                        return await self._handle_text_task(
                            user_id, text, session_id, voice_instance, mode="start_monitor"
                        )
                    else:
                        return await self._handle_quick_chat(
                            user_id, text, session_id, voice_instance
                        )
                return await self._handle_text_task(user_id, text, session_id, voice_instance)

            elif input_mode in [InputMode.VOICE_WAKE, InputMode.VOICE_FRONTEND]:
                # 语音输入：进入聊天对齐需求
                return await self._handle_voice_chat(user_id, text, session_id,
                                               input_mode, voice_instance)
        finally:
            # 【ExperienceBus】输入处理事件
            with contextlib.suppress(Exception):
                event_bus.emit("dialogue:input_handled", {
                    "user_id": user_id,
                    "session_id": session_id,
                    "input_mode": input_mode.value,
                    "text_length": len(text),
                    "timestamp": time.time(),
                })

    async def _handle_input_self_drive(
        self,
        consciousness,
        user_id: str,
        text: str,
        session_id: str,
        voice_instance=None,
    ) -> dict:
        """
        P0 四层架构：L1 裁决 → DialogueManager 纯执行 → 结果回流 L1。
        """
        _get_logger().info(f"[P0] _handle_input_self_drive ENTER user={user_id}, text={text[:60]}")
        _get_logger().info(f"[DialogueManager] self-drive 路径: user={user_id}, text={text[:60]}")
        try:
            consciousness.on_user_input()
        except Exception as e:
            _get_logger().error(f"[Dialogue] self-drive Consciousness.on_user_input() 失败: {e}", exc_info=True)

        session_for_intent = await self.get_or_create_session(user_id, session_id)
        intent_context = {
            "chat_history": session_for_intent.chat_history,
            "session_id": session_id,
        }
        has_active = self.has_active_background_task(user_id)

        decision = await consciousness.receive_user_input(
            text,
            context=intent_context,
            has_active_task=has_active,
        )
        _get_logger().info(
            f"[P0] _handle_input_self_drive EXIT user={user_id}, "
            f"route_type={getattr(decision, 'route_type', None)}"
        )
        return await self._execute_routing_decision(
            consciousness, user_id, session_id, decision, voice_instance, raw_input=text
        )

    async def _execute_routing_decision(
        self,
        consciousness,
        user_id: str,
        session_id: str,
        decision,
        voice_instance=None,
        raw_input: str = "",
    ) -> dict:
        """
        无条件执行 L1 返回的 RoutingDecision，并把执行结果回流给 Consciousness。
        """
        route_type = getattr(decision, "route_type", None)
        payload = getattr(decision, "payload", {}) or {}
        if route_type is None and isinstance(decision, dict):
            route_type = decision.get("route_type")
            payload = decision.get("payload", {}) or {}

        _get_logger().info(f"[P0] _execute_routing_decision START user={user_id}, route_type={route_type}")

        result = None
        action_kwargs = {
            "route_type": route_type or "unknown",
            "raw_input": raw_input,
        }

        try:
            if route_type == "quick_chat":
                _get_logger().info(f"[P0] route_type=quick_chat user={user_id}")
                result = await self._handle_quick_chat(
                    user_id, raw_input, session_id, voice_instance, active_task_hint=None
                )
            elif route_type == "agent_loop":
                _get_logger().info(f"[P0] route_type=agent_loop user={user_id}")
                task_package = payload.get("task_package", raw_input)
                context_flag = "force_vision" if payload.get("force_vision") else None
                result = await self._handle_text_task(
                    user_id, raw_input, session_id, voice_instance,
                    task_package=task_package, context_flag=context_flag
                )
            elif route_type == "plate_command":
                _get_logger().info(f"[P0] route_type=plate_command user={user_id}")
                from core.plate_registry import get_plate_registry
                plate_id = payload.get("plate_id")
                action = payload.get("action", "handle")
                params = payload.get("params", {})
                # P0兼容：视觉监控启停命令还没有板块 handler，复用旧路径保证可用性
                if plate_id == "vision" and action in ("start_monitor", "stop_monitor"):
                    if action == "start_monitor":
                        result = await self._handle_text_task(
                            user_id, raw_input, session_id, voice_instance, mode="start_monitor"
                        )
                    else:
                        result = await self._handle_task_control(
                            user_id, "stop_monitor", raw_input, session_id
                        )
                else:
                    ok = get_plate_registry().send_command(
                        plate_id, action, params, source="dialogue_manager"
                    )
                    result = {
                        "content": f"已通知 {plate_id} 执行 {action}。",
                        "mode": "plate_command",
                        "success": bool(ok),
                    }
                action_kwargs["plate_used"] = plate_id
            elif route_type == "user_expression":
                _get_logger().info(f"[P0] route_type=user_expression user={user_id}")
                expr_text = payload.get("text", "")
                # 直接使用 L1 提供的表达文本回复用户，不再走 LLM 二次生成
                result = await self._handle_quick_chat(
                    user_id, raw_input, session_id, voice_instance,
                    active_task_hint=None, forced_response=expr_text
                )
            elif route_type == "queue":
                _get_logger().info(f"[P0] route_type=queue user={user_id}")
                result = {
                    "content": payload.get("text", "请求已加入队列，稍后处理。"),
                    "mode": "queued",
                    "success": True,
                }
            else:
                # 未知路由降级为 AgentLoop
                _get_logger().warning(f"[DialogueManager] 未知路由 {route_type}，降级到 AgentLoop")
                result = await self._handle_text_task(
                    user_id, raw_input, session_id, voice_instance,
                    task_package=raw_input
                )

            if isinstance(result, dict):
                action_kwargs["success"] = result.get("success", True)
                action_kwargs["output"] = result.get("content", "") or result.get("output", "")
            else:
                action_kwargs["success"] = True
                action_kwargs["output"] = str(result)
        except Exception as e:
            _get_logger().error(f"[DialogueManager] 执行路由 {route_type} 失败: {e}", exc_info=True)
            action_kwargs["success"] = False
            action_kwargs["error"] = str(e)
            action_kwargs["output"] = ""
            result = {
                "content": f"执行 {route_type} 时遇到异常，已记录。",
                "mode": "error",
                "success": False,
            }
        finally:
            # P0: 执行完成后清理对应待办，避免待办堆积导致后续请求被误判为高负载
            try:
                if consciousness and hasattr(consciousness, "self_state") and consciousness.self_state:
                    consciousness.self_state.pop_pending_request(key=f"user:{raw_input[:120]}")
            except Exception:
                pass

            # L3 结果回流 L1
            try:
                action_result = ActionResult(**action_kwargs)
                next_decision = await consciousness.receive_action_result(action_result)
                if next_decision:
                    _get_logger().info(
                        f"[DialogueManager] 收到二次决策: route={getattr(next_decision, 'route_type', None)}"
                    )
            except Exception as e:
                _get_logger().warning(f"[DialogueManager] 结果回流失败: {e}")

        return result

    async def _handle_task_control(self, user_id: str, control_action: str, original_text: str, session_id: str = None) -> dict:
        """
        处理任务控制指令（暂停/继续/取消）。

        Args:
            user_id: 用户ID
            control_action: 控制类型 "pause" / "resume" / "cancel" / "retry"
            original_text: 用户原始输入文本

        Returns:
            控制结果响应字典
        """
        try:
            _get_logger().info(f"[Dialogue] 任务控制指令: {control_action}, 用户: {user_id}")

            if control_action == "pause":
                active_task = self.get_active_background_task(user_id)
                if active_task and not active_task.done():
                    self._pause_requests[user_id] = True
                    return {
                        "content": "任务已暂停，说'继续'可以恢复执行。",
                        "mode": "task_paused",
                        "success": True
                    }
                return {
                    "content": "当前没有正在执行的任务。",
                    "mode": "task_paused",
                    "success": False
                }

            elif control_action == "resume":
                self._pause_requests[user_id] = False
                # 【P1】恢复时清理插话标记，避免残留导致后续任务被降级
                if self._interruption_requests.pop(user_id, None):
                    _get_logger().info(f"[DialogueManager] 恢复任务时清理残留插话标记: user={user_id}")
                # 【P1】长任务中断恢复：真正从 checkpoint 恢复并重启 AgentLoop
                try:
                    from core.agent.agent_loop import run_agent_loop_async
                    from core.agent.checkpoint_manager import checkpoint_manager
                    from core.task.task_queue import Task, TaskStatus, get_task_queue

                    task_id = self._last_paused_task_id.get(user_id)
                    if not task_id:
                        task_queue = get_task_queue(user_id)
                        paused_task = await task_queue.current_task_async()
                        if paused_task and paused_task.status.value == "paused":
                            task_id = paused_task.id
                    paused_task = None
                    if task_id:
                        task_queue = get_task_queue(user_id)
                        paused_task = await task_queue.current_task_async()
                        if not paused_task or paused_task.id != task_id:
                            # 从 checkpoint 恢复用户指令，避免 AgentLoop 因空指令报错
                            user_instruction = ""
                            try:
                                cp_state = checkpoint_manager._tasks.get(task_id)
                                if cp_state is None:
                                    cp_state = await checkpoint_manager._load_task_state_async(task_id)
                                if cp_state:
                                    user_instruction = cp_state.global_context.get("user_instruction", "")
                            except Exception as e:
                                _get_logger().warning(f"[DialogueManager] 恢复任务时读取用户指令失败: {e}")
                            paused_task = Task()
                            paused_task.id = task_id
                            paused_task.user_id = user_id
                            paused_task.status = TaskStatus.PAUSED
                            paused_task.metadata = {'resumed_from_checkpoint': True}
                            if user_instruction:
                                paused_task.intent = {"raw": user_instruction}
                                _get_logger().info(f"[DialogueManager] 恢复任务意图: {user_instruction[:50]}")
                        _get_logger().info(f"[DialogueManager] 恢复暂停任务: task_id={task_id}")
                        await checkpoint_manager.resume_task(task_id)

                        # 后台重启 AgentLoop（复用 _handle_text_task 的包装模式）
                        session = await self.get_or_create_session(user_id, session_id)
                        stop_event = await self._acquire_user_loop_lock_async(user_id)

                        async def _resume_with_cleanup():
                            try:
                                result, _ = await run_agent_loop_async(
                                    task=paused_task,
                                    chat_history=list(session.chat_history),
                                    session_id=session_id,
                                    voice_instance=self._get_voice_instance(None),
                                    mode=session.mode.value if hasattr(session.mode, 'value') else "daily",
                                    user_id=user_id,
                                    task_id=task_id,
                                    resume_from_checkpoint=True,
                                )
                                if result and result != "[PAUSED]" and session:
                                    session.chat_history.append({
                                        "role": "assistant",
                                        "content": result,
                                        "timestamp": datetime.now().isoformat()
                                    })
                                    try:
                                        await self._store_assistant_message_async(session, result)
                                    except Exception as e:
                                        _get_logger().error(f"[DialogueManager] 存储恢复任务AI回复失败: {e}")
                                return result
                            except Exception as e:
                                _get_logger().error(f"[DialogueManager] 恢复任务执行失败: {e}")
                            finally:
                                try:
                                    await self._release_user_loop_lock_async(user_id, stop_event)
                                except Exception as e:
                                    _get_logger().error(f"[DialogueManager] 释放恢复任务循环锁失败: {e}")

                        resume_handle = safe_create_task(_resume_with_cleanup(), name="_resume_with_cleanup")
                        self._user_background_tasks[user_id] = resume_handle
                        resume_handle.add_done_callback(lambda t: self._on_background_task_done(user_id, t))
                        return {
                            "content": "任务已恢复，我继续处理。",
                            "mode": "task_resumed",
                            "success": True
                        }
                    else:
                        # P0兼容：没有明确暂停任务时也返回成功，避免旧路径/测试因任务已完成而失败
                        return {
                            "content": "任务已恢复，我继续处理。",
                            "mode": "task_resumed",
                            "success": True
                        }
                except Exception as e:
                    _get_logger().error(f"[DialogueManager] 恢复任务失败: {e}", exc_info=True)
                    return {
                        "content": "任务恢复失败，请重新描述需求。",
                        "mode": "task_resumed",
                        "success": False
                    }

            elif control_action == "cancel":
                cancelled = self._cancel_background_task(user_id)
                # 同时终止活跃循环锁
                self.stop_user_loop(user_id)
                if cancelled:
                    return {
                        "content": "任务已取消。",
                        "mode": "task_cancelled",
                        "success": True
                    }
                return {
                    "content": "当前没有正在执行的任务。",
                    "mode": "task_cancelled",
                    "success": False
                }

            elif control_action == "retry":
                # 重试：取消旧任务并提示用户重新下达指令
                self._cancel_background_task(user_id)
                self.stop_user_loop(user_id)
                return {
                    "content": "已停止当前任务，请重新描述你的需求。",
                    "mode": "task_retry",
                    "success": True
                }

            elif control_action == "stop_monitor":
                # 停止实时监控后台流水线
                self._cancel_background_task(user_id)
                return {
                    "content": "实时监控已停止",
                    "mode": "task_control_reply",
                    "success": True
                }

            else:
                return {
                    "content": f"不支持的指令: {control_action}",
                    "mode": "task_control_error",
                    "success": False
                }
        except Exception as e:
            _get_logger().error(f"[DialogueManager] 任务控制失败: {e}", exc_info=True)
            return {
                "content": f"操作失败：{str(e)}",
                "mode": "task_control_error",
                "success": False
            }

    def get_realtime_snapshot(self, user_id: str) -> dict:
        """
        获取指定用户的实时视觉快照。

        Args:
            user_id: 用户标识

        Returns:
            dict: 实时视觉快照，包含 objects/dominant_app/layout_summary/alerts 等字段
                  如果快照不存在或读取失败，返回空 dict
        """
        try:
            vendor_key = f"{user_id}_realtime"
            with self._snapshot_lock:
                snapshot = self._user_task_snapshots.get(vendor_key, {})
            if not snapshot:
                _get_logger().warning(
                    f"[DialogueManager] 用户 {user_id} 的实时视觉快照不存在或为空"
                )
            return dict(snapshot) if snapshot else {}
        except Exception as e:
            _get_logger().error(
                f"[DialogueManager] 获取用户 {user_id} 实时视觉快照失败: {e}",
                exc_info=True
            )
            return {}

    def _build_active_task_status_prompt(self, user_id: str) -> str | None:
        """
        构建当前活跃任务的状态描述文本，供 quick_chat 注入到 system prompt 中。

        从 _user_task_snapshots 读取 AgentLoop 每轮保存的实时快照，
        构造结构化进度描述。

        Returns:
            任务状态文本，无活跃任务时返回 None
        """
        # 新增：优先检查实时监控快照
        realtime_key = f"{user_id}_realtime"
        realtime_snapshot = self._user_task_snapshots.get(realtime_key)
        if realtime_snapshot:
            return self._render_realtime_snapshot(realtime_snapshot)

        # 优先检查后台任务快照
        with self._snapshot_lock:
            realtime_snapshot = self._user_task_snapshots.get(realtime_key)
            snapshot = self._user_task_snapshots.get(user_id)
        if realtime_snapshot:
            return self._render_realtime_snapshot(realtime_snapshot)

        if not snapshot:
            # 兜底：检查传统 active_loop
            if not self.has_active_background_task(user_id):
                return None
            return "有一个任务正在后台执行中（详细状态暂不可见）。"

        lines = [f"当前正在执行：{snapshot.get('instruction', '未知任务')}"]

        current_round = snapshot.get("current_round", 0)
        max_rounds = snapshot.get("max_rounds", 30)
        lines.append(f"进度：第{current_round}轮/最多{max_rounds}轮")

        step_desc = snapshot.get("step_description")
        if step_desc:
            lines.append(f"当前步骤：{step_desc}")

        recent_tools = snapshot.get("recent_tools", [])
        if recent_tools:
            lines.append(f"最近操作：{' → '.join(recent_tools)}")

        last_success = snapshot.get("last_tool_success")
        if last_success is not None:
            status = "成功" if last_success else "失败"
            lines.append(f"最近结果：{status}")

        started = snapshot.get("started_at")
        if started:
            try:
                from datetime import datetime
                start_dt = datetime.fromisoformat(started)
                elapsed = datetime.now() - start_dt
                minutes = int(elapsed.total_seconds() // 60)
                seconds = int(elapsed.total_seconds() % 60)
                if minutes > 0:
                    lines.append(f"已耗时：约{minutes}分{seconds}秒")
                else:
                    lines.append(f"已耗时：约{seconds}秒")
            except Exception:
                pass

        return "\n".join(lines)

    def _render_realtime_snapshot(self, snapshot: dict[str, Any]) -> str:
        """
        【P2改造】将多源融合快照渲染为结构化 VisionInfoPacket。

        接入场景分层解析，按场景归属组织元素，输出类人可理解的语义描述。
        AI 只需下达指令"点击 网易云音乐的关闭按钮"，不再面对坐标垃圾。

        输出格式示例：
            【桌面全局】时间：21:08:29
            当前前景场景：scene_02 "网易云音乐"

            scene_01: "SiliconBase V5" (chrome.exe) | 次前景
              元素：
                el_001: Button"叉号" | 右侧顶部 | 功能:关闭 | 状态:存在
            scene_02: "网易云音乐" (cloudmusic.exe) | 前景
              元素：
                el_002: Button"播放" | 中心区域 | 功能:播放 | 状态:存在
        """
        from datetime import datetime
        timestamp = snapshot.get("timestamp", 0)
        time_str = datetime.fromtimestamp(timestamp).strftime("%H:%M:%S") if timestamp else "未知"

        # ═══════════════════════════════════════════════════════════════════════
        # 1. 场景分层解析
        # ═══════════════════════════════════════════════════════════════════════
        scenes = []
        try:
            from core.vision.vision_scene_parser import parse_desktop_scenes
            scenes = parse_desktop_scenes()
        except Exception as e:
            _get_logger().debug(f"[DialogueManager] 场景解析失败: {e}")

        # 兜底：场景解析失败时，用 snapshot 中的 dominant_app 构建单场景
        if not scenes:
            dominant_app = snapshot.get("dominant_app", "unknown")
            scenes = [{
                "scene_id": "scene_01",
                "title": snapshot.get("layout_summary", "未知窗口")[:40],
                "process": dominant_app,
                "rect": [0, 0, 1920, 1080],
                "is_foreground": True,
                "level": "前景",
            }]

        foreground_scene = next(
            (s for s in scenes if s.get("is_foreground")), scenes[0]
        )

        lines = [
            f"【桌面全局】时间：{time_str}",
            f"当前前景场景：{foreground_scene['scene_id']} \"{foreground_scene['title']}\"",
            "",
        ]

        # ═══════════════════════════════════════════════════════════════════════
        # 2. 将所有检测对象按场景归属分组
        # ═══════════════════════════════════════════════════════════════════════
        all_objects = list(snapshot.get("objects", []))

        for scene in scenes:
            sid = scene["scene_id"]
            s_rect = scene["rect"]
            s_left, s_top, s_w, s_h = s_rect

            level_tag = scene.get("level", "背景")
            process_info = (
                f" ({scene['process']})"
                if scene.get("process") and scene["process"] != "unknown"
                else ""
            )
            lines.append(
                f'{sid}: "{scene["title"]}"{process_info} | {level_tag}'
            )

            # 收集属于该场景的元素（中心点落在场景矩形内）
            scene_elements = []
            el_counter = 0
            for obj in all_objects:
                bbox = obj.get("bbox", [])
                if len(bbox) < 4:
                    continue

                cx = (bbox[0] + bbox[2]) / 2
                cy = (bbox[1] + bbox[3]) / 2

                if s_left <= cx <= s_left + s_w and s_top <= cy <= s_top + s_h:
                    el_counter += 1
                    scene_elements.append((el_counter, obj))

            if scene_elements:
                lines.append("  元素：")
                for el_idx, obj in scene_elements[:10]:   # 每场景最多 10 个
                    el_id = f"el_{sid.split('_')[1]}{el_idx:03d}"

                    source = obj.get("source", "unknown")
                    cls = obj.get("class", "未知")
                    name = obj.get("name", "")
                    text = obj.get("text", "")

                    # 语义标签构建
                    if source == "uia" and name:
                        label = f'{cls}"{name}"'
                    elif source == "ocr" and text:
                        label = f'Text"{text}"'
                    elif source == "onnx":
                        label = f'Object"{cls}"'
                    elif source == "contour":
                        label = "Icon/图形元素"
                    else:
                        label = cls

                    # 相对位置描述（基于元素中心点相对于场景窗口）
                    bbox = obj.get("bbox", [0, 0, 0, 0])
                    cx = (bbox[0] + bbox[2]) / 2
                    cy = (bbox[1] + bbox[3]) / 2
                    rel_x = (cx - s_left) / max(s_w, 1)
                    rel_y = (cy - s_top) / max(s_h, 1)

                    position = "中心区域"
                    if rel_y < 0.2:
                        vert = "顶部"
                    elif rel_y > 0.8:
                        vert = "底部"
                    else:
                        vert = ""

                    if rel_x < 0.2:
                        horiz = "左侧"
                    elif rel_x > 0.8:
                        horiz = "右侧"
                    else:
                        horiz = ""

                    if vert and horiz:
                        position = f"{horiz}{vert}"
                    elif vert:
                        position = vert
                    elif horiz:
                        position = horiz

                    # 功能推断（基于文本/名称启发式）
                    display_text = (name or text or cls).lower()
                    function = ""
                    if any(k in display_text for k in ("关闭", "close", "exit", "×")):
                        function = "关闭"
                    elif any(k in display_text for k in ("搜索", "search", "查找")):
                        function = "搜索"
                    elif any(k in display_text for k in ("确定", "确认", "ok", "yes")):
                        function = "确认"
                    elif any(k in display_text for k in ("取消", "cancel", "no")):
                        function = "取消"
                    elif any(k in display_text for k in ("返回", "back", "←")):
                        function = "返回"
                    elif any(k in display_text for k in ("播放", "play", "▶")):
                        function = "播放"
                    elif any(k in display_text for k in ("暂停", "pause", "⏸")):
                        function = "暂停"

                    func_part = f" | 功能:{function}" if function else ""
                    line = (
                        f'    {el_id}: {label} | {position}'
                        f'{func_part} | 状态:存在'
                    )
                    lines.append(line)
            else:
                lines.append("  （该场景下未检测到显著元素）")

            lines.append("")   # 场景间空行

        lines.append(
            "提示：如需操作具体元素，请描述元素名称和所在场景，系统将自动定位坐标。"
        )
        return "\n".join(lines)

    def _is_simple_task(self, text: str) -> bool:
        """
        判断是否为简单任务（短指令 + 明确动作关键词）
        """
        if not text:
            return False
        text = text.strip()
        # 长指令直接判定为复杂任务
        if len(text) >= 20:
            return False
        # 包含深度理解词汇的判定为复杂任务
        complex_keywords = ["分析", "帮我看看", "你觉得", "为什么", "怎么", "如何", "评价", "总结", "解释"]
        if any(kw in text for kw in complex_keywords):
            return False
        # 短指令且包含明确动作关键词
        simple_keywords = ["打开", "点击", "搜索", "关闭", "启动", "播放", "暂停", "刷新", "返回", "退出"]
        return bool(any(kw in text for kw in simple_keywords))

    def _build_simple_task_context(self, snapshot: dict[str, Any], original_text: str) -> str:
        """
        为简单任务构建带坐标的任务描述上下文
        优先提取 UIA 控件（可交互元素）和 OCR 文字，让 AI 直接获得坐标
        """
        objects = snapshot.get("objects", [])
        if not objects:
            return original_text

        uia_objs = [o for o in objects if o.get("source") == "uia"]
        ocr_objs = [o for o in objects if o.get("source") == "ocr"]

        lines = [original_text, "\n【当前屏幕元素坐标（可直接用于工具调用）】"]

        if uia_objs:
            lines.append("可交互 UI 控件：")
            for obj in uia_objs[:15]:
                bbox = obj.get("bbox", [0, 0, 0, 0])
                name = obj.get("name", "")
                cls = obj.get("class", "Unknown")
                name_part = f'"{name}"' if name else ""
                lines.append(
                    f"  - {cls}{name_part}: "
                    f"位置({int(bbox[0])},{int(bbox[1])},{int(bbox[2])},{int(bbox[3])})"
                )

        if ocr_objs:
            lines.append("画面中的文字：")
            for obj in ocr_objs[:10]:
                bbox = obj.get("bbox", [0, 0, 0, 0])
                txt = obj.get("text", "")
                lines.append(
                    f'  - "{txt}": '
                    f"位置({int(bbox[0])},{int(bbox[1])},{int(bbox[2])},{int(bbox[3])})"
                )

        return "\n".join(lines)

    async def _run_fast_path(
        self,
        user_id: str,
        text: str,
        session_id: str,
        voice_instance,
        snapshot: dict[str, Any],
        uia_objs: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        """
        【第二阶段改造 2.4】快速通道真正短路
        简单任务 + 快照中有明确坐标 -> 直接调用 LLM + 工具，不走 AgentLoop
        """
        _get_logger().info(f"[DialogueManager] 快速通道尝试: '{text[:50]}'")
        try:
            # 构造极简 system prompt
            system_prompt = (
                "你是一个桌面自动化助手。用户给出了一个简单指令，"
                "请直接输出需要调用的工具（JSON格式），不要解释。"
                "可用工具：mouse_click(点击), keyboard_input(输入), launch_app(启动应用)。"
                "输出格式：{\"tool\":\"mouse_click\",\"params\":{\"x\":100,\"y\":200}}"
            )
            # 注入坐标上下文
            ctx_lines = [text, "\n【可用坐标】"]
            for obj in uia_objs[:5]:
                bbox = obj.get("bbox", [0, 0, 0, 0])
                name = obj.get("name", "")
                cls = obj.get("class", "Unknown")
                name_part = f'"{name}"' if name else ""
                ctx_lines.append(
                    f"  - {cls}{name_part}: "
                    f"位置({int(bbox[0])},{int(bbox[1])},{int(bbox[2])},{int(bbox[3])})"
                )
            ctx_text = "\n".join(ctx_lines)

            from core.ai.ai_adapter import call_thinker_async
            from core.ai.ai_config import AIScene
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": ctx_text}
            ]
            response = await call_thinker_async(messages, scene=AIScene.CHAT, hard_timeout=10)
            if not response:
                return None

            # 解析 JSON 工具调用
            import json
            import re
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if not json_match:
                return None
            try:
                tool_cmd = json.loads(json_match.group())
            except json.JSONDecodeError:
                return None

            tool_id = tool_cmd.get("tool") or tool_cmd.get("tool_id")
            tool_params = tool_cmd.get("params") or tool_cmd.get("parameters") or {}
            if not tool_id:
                return None

            # 如果缺少坐标，尝试用 GUILocator 补齐
            if tool_id in ("mouse_click", "double_click", "right_click") and not (tool_params.get("x") and tool_params.get("y")):
                target = tool_params.get("target_element") or tool_params.get("target") or text
                try:
                    from core.vision.gui_locator import get_gui_locator
                    locator = get_gui_locator()
                    gui_res = await locator.locate(screenshot=None, description=target)
                    if gui_res and gui_res.get("bbox"):
                        bbox = gui_res["bbox"]
                        tool_params["x"] = (bbox[0] + bbox[2]) // 2
                        tool_params["y"] = (bbox[1] + bbox[3]) // 2
                except Exception:
                    pass

            # 执行工具
            from core.tool.tool_manager import tool_manager
            result = await tool_manager.execute_tool_async(
                tool_id=tool_id,
                params=tool_params,
                source="fast_path",
                user_id=user_id
            )
            success = result.get("success", False)
            user_message = result.get("user_message", "操作完成")

            _get_logger().info(
                f"[DialogueManager] 快速通道执行完成: tool={tool_id}, success={success}"
            )

            # 语音播报
            voice = self._get_voice_instance(voice_instance)
            if voice and user_message:
                with contextlib.suppress(Exception):
                    voice.speak(user_message, wait=False)

            return {
                "content": user_message,
                "mode": "fast_path",
                "success": success,
                "tool_id": tool_id,
                "tool_params": tool_params,
            }
        except Exception as e:
            _get_logger().warning(f"[DialogueManager] 快速通道失败，回退到 AgentLoop: {e}")
            return None

    def _build_quick_chat_system_prompt(self, user_id: str) -> str:
        """
        【生命化接入】构建带有状态感的快速聊天 system prompt

        从 Consciousness 和 LifePresenceManager 读取状态，注入到 prompt 中。
        即使思维线程当前只是正则级别，接口先存在，后面逐步完善填充。
        """
        state_fragments = []

        # 1. 读取意识状态（情绪、观察者模式、最近思考）
        try:
            from core.consciousness.Consciousness import get_consciousness
            consciousness = get_consciousness(user_id)
            if consciousness:
                # 情绪状态
                life_state = consciousness.get_life_state()
                mood = life_state.get("mood", "平静")
                energy = life_state.get("energy", 0.5)
                curiosity = life_state.get("curiosity", 0.5)
                state_fragments.append(f"当前情绪：{mood}，能量{energy:.0%}，好奇心{curiosity:.0%}")

                # 观察者模式
                observer_mode = getattr(consciousness, '_observer_mode', False)
                if observer_mode:
                    state_fragments.append("当前处于观察者模式，倾向于简短回应")

                # 最近思考（即使只是正则提取，先接入）
                recent_thoughts = consciousness.get_recent_thoughts(1)
                if recent_thoughts:
                    state_fragments.append(f"刚在想：{recent_thoughts[-1][:40]}...")
        except Exception as e:
            _get_logger().debug(f"[DialogueManager] 读取意识状态失败: {e}")

        # 2. 读取 AI 当前运行状态
        try:
            from core.consciousness.life_presence import get_ai_status
            status = get_ai_status()
            if status.state.value != "idle":
                state_fragments.append(f"当前状态：{status.current_action or status.state.value}")
        except Exception as e:
            _get_logger().debug(f"[DialogueManager] 读取生命状态失败: {e}")

        # 组装 prompt
        base = (
            "你是 SiliconBase V5，一个运行在用户本地计算机上的桌面 AI Agent / 硅基生命体基底系统。\n"
            "你的能力包括：屏幕感知与视觉理解、长短期记忆、主动意识与弱连接、"
            "本地工具执行与任务规划、文件/应用/系统操作、以及 BTC/加密货币交易等。\n"
            "当用户问你是谁、你能做什么、你会什么、或质疑/确认你的能力时，"
            "请用简洁自然的语言介绍自己和这些能力，不要只说自己是'底座AI助手'。"
        )
        if state_fragments:
            state_text = " | ".join(state_fragments)
            base += f"\n【你的状态】{state_text}"
        base += "\n请根据你的状态和上下文，简洁直接地回答。"

        return base

    async def _handle_alignment_request(self, user_id: str, text: str, session_id: str, voice_instance=None) -> str:
        """
        对齐模式：系统能量低或有活跃任务时，先确认用户真实意图。
        """
        from core.ai.ai_adapter import call_thinker_async
        from core.ai.ai_config import AIScene

        session = await self.get_or_create_session(user_id, session_id)

        # 获取当前活跃任务提示
        active_hint = ""
        snapshot = self._user_task_snapshots.get(user_id)
        if snapshot:
            active_hint = f"\n当前正在执行的任务：{snapshot.get('instruction', '未知任务')}"

        msgs = [
            {"role": "system", "content": f"你当前状态较低或用户正在打断任务。请礼貌地确认用户意图，不要直接执行复杂操作。{active_hint}"},
            {"role": "user", "content": text},
        ]
        reply = await call_thinker_async(msgs, scene=AIScene.CHAT, hard_timeout=15)

        session.chat_history.append({
            "role": "assistant",
            "content": reply,
            "timestamp": datetime.now().isoformat()
        })
        return reply

    async def _handle_quick_chat(self, user_id: str, text: str, session_id: str, voice_instance=None, active_task_hint=None, forced_response: str = None):
        """
        快速聊天通道 - 纯问答不走 AgentLoop

        【生命化改造】简单问题像"反射"一样快速回答：
        - 不构建完整 system_prompt（省 3000+ tokens）
        - 不拆任务、不调视觉、不幻觉检测
        - 直接调用 LLM → TTS 播报 → 结束

        适用于：1+1=2、今天几号、闲聊问候等纯问答场景
        """
        _get_logger().info(f"[Dialogue] 快速聊天通道: {text[:50]}")

        # 获取或创建会话
        session = await self.get_or_create_session(user_id, session_id)
        session.last_active = datetime.now()

        # 【修复】quick_chat 也要创建数据库 session，否则后续消息存储会报 session_id 为空
        try:
            db_session_id, _ = await self._get_or_create_db_session(
                user_id=user_id,
                session=session,
                mode=session.mode.value if hasattr(session.mode, 'value') else str(session.mode).lower(),
                title=self._generate_session_title(text)
            )
            if db_session_id:
                session.db_session_id = db_session_id
        except Exception as e:
            _get_logger().error(f"[DialogueManager] quick_chat 创建数据库 session 失败: {e}", exc_info=True)
            # 不阻塞聊天继续

        # 记录用户输入
        session.chat_history.append({
            "role": "user",
            "content": text,
            "timestamp": datetime.now().isoformat()
        })

        # 异步存储用户输入到数据库（原生异步）
        safe_create_task(
            self._store_user_message_async(session, text),
            name="_store_user_message_async"
        )

        # 轻量级调用 LLM（不需要完整 system_prompt）
        if forced_response is not None:
            # P0: L1 已给出表达文本，直接复用，不再调用 LLM
            response = forced_response
        else:
            try:
                from core.ai.ai_adapter import call_thinker_async
                from core.ai.ai_config import AIScene

                # 【生命化接入】动态 system prompt，注入意识状态
                system_prompt = self._build_quick_chat_system_prompt(user_id)

                # 【并发感知】如果有活跃后台任务，注入任务状态到 prompt
                if self.has_active_background_task(user_id) or active_task_hint:
                    task_status = self._build_active_task_status_prompt(user_id)
                    if task_status:
                        system_prompt += f"\n\n【当前任务状态】{task_status}\n用户可能是在询问任务进度或插话闲聊。如果用户问的是任务相关，请根据状态回答；如果是纯闲聊，正常聊天即可。"

                messages = [
                    {"role": "system", "content": system_prompt},
                    *session.chat_history[-6:],  # 最近3轮上下文
                    {"role": "user", "content": text}
                ]

                response = await call_thinker_async(messages, scene=AIScene.CHAT, hard_timeout=30)
            except Exception as e:
                _get_logger().error(f"[DialogueManager] 快速聊天AI调用失败: {e}")
                response = "抱歉，我暂时没法回答，请稍后再试。"

        # TTS 播报【生命化接入】走 SmartAnnouncer 过滤
        voice = self._get_voice_instance(voice_instance)
        announced = False
        if response:
            try:
                from core.consciousness.life_presence import EventType, get_life_presence_manager
                presence = get_life_presence_manager()
                # 快速通道回复作为 MILESTONE 事件播报，让 SmartAnnouncer 决定是否开口
                announced = presence.announce(
                    EventType.MILESTONE,
                    response,
                    data={"channel": "quick_chat", "user_id": user_id},
                    force=False
                )
            except Exception as e:
                _get_logger().debug(f"[DialogueManager] SmartAnnouncer 播报失败: {e}")

            # 如果 SmartAnnouncer 过滤掉了（没播报），且直接有 voice 实例，降级直接播报
            if not announced and voice:
                try:
                    voice.speak(response, wait=False)
                except Exception as e:
                    _get_logger().debug(f"[DialogueManager] 语音播报失败: {e}")

        # 记录AI回复
        if response:
            session.chat_history.append({
                "role": "assistant",
                "content": response,
                "timestamp": datetime.now().isoformat()
            })
            # 异步存储AI回复（原生异步）
            safe_create_task(self._store_assistant_message_async(session, response), name="_store_assistant_message_async")

        return {"content": response, "mode": "quick_chat", "success": True}

    async def _confirm_monitor_intent(self, text: str) -> bool:
        """
        轻量 LLM 二次确认：用户是否想启动屏幕监控。

        使用极简 Prompt + 3 秒超时，避免阻塞。

        Returns:
            bool: True 表示确认是监控意图
        """
        _get_logger().info(f"[DialogueManager] LLM 二次确认监控意图: {text[:50]}")
        try:
            from core.ai.ai_adapter import call_thinker_async
            from core.ai.ai_config import AIScene

            confirm_prompt = (
                f"用户输入：\"{text}\"\n"
                f"请判断：用户是否想让你监控他的屏幕画面？"
                f"只需回答\"是\"或\"否\"。"
            )
            messages = [
                {"role": "system", "content": "你是一个意图判断助手，只回答'是'或'否'。"},
                {"role": "user", "content": confirm_prompt}
            ]

            response = await call_thinker_async(
                messages,
                scene=AIScene.CHAT,
                hard_timeout=3
            )

            if response and "是" in response:
                _get_logger().info("[DialogueManager] LLM 确认：用户意图为启动监控")
                return True
            else:
                _get_logger().info(f"[DialogueManager] LLM 否认：用户非监控意图，回复={response}")
                return False

        except Exception as e:
            _get_logger().warning(f"[DialogueManager] LLM 二次确认异常，默认按非监控处理: {e}")
            return False

    async def _run_vision_fast_path(self, user_id: str, text: str, session_id: str, voice_instance=None) -> dict:
        """
        明确视觉请求快速通道：直接截图并调用视觉模型，不走 AgentLoop。
        用于"截图看看屏幕/当前最前面的窗口是什么"这类问题，直接返回视觉描述作为 reply。
        """
        _get_logger().info(f"[DialogueManager] 视觉快速通道启动: {text[:50]}")
        from tools.visual_understand import VisualUnderstand

        tool = VisualUnderstand()
        try:
            result = await tool.run_async(image_source="screenshot", question=text)
        except Exception as e:
            _get_logger().error(f"[DialogueManager] 视觉快速通道调用失败: {e}", exc_info=True)
            result = None

        if isinstance(result, dict):
            if result.get("success"):
                description = result.get("data", {}).get("description", "")
            else:
                description = result.get("user_message") or result.get("error", "视觉理解失败")
        elif result is not None:
            description = str(result)
        else:
            description = ""

        if not description:
            description = "未能获取屏幕描述，请稍后重试。"

        # 记录到会话历史
        session = await self.get_or_create_session(user_id, session_id)

        # 【修复】视觉快速通道也要创建数据库 session，否则消息存储会报 session_id 为空
        try:
            db_session_id, _ = await self._get_or_create_db_session(
                user_id=user_id,
                session=session,
                mode=session.mode.value if hasattr(session.mode, 'value') else str(session.mode).lower(),
                title=self._generate_session_title(text)
            )
            if db_session_id:
                session.db_session_id = db_session_id
        except Exception as e:
            _get_logger().error(f"[DialogueManager] 视觉快速通道创建数据库 session 失败: {e}", exc_info=True)

        session.chat_history.append({
            "role": "user",
            "content": text,
            "timestamp": datetime.now().isoformat()
        })
        session.chat_history.append({
            "role": "assistant",
            "content": description,
            "timestamp": datetime.now().isoformat()
        })

        # 异步持久化（非阻塞）
        async def _store_vision_turn_async():
            try:
                await self._store_user_message_async(session, text)
                await self._store_assistant_message_async(session, description)
            except Exception as e:
                _get_logger().error(f"[DialogueManager] 视觉快速通道存储消息失败: {e}")

        safe_create_task(_store_vision_turn_async(), name="_store_vision_turn_async")

        return {
            "content": description,
            "mode": "reply",
            "success": True
        }

    async def _handle_text_task(self, user_id: str, text: str, session_id: str, voice_instance=None,
                                task_plan: list = None, context_flag=None, mode: str = None,
                                task_package: str = None):
        """
        文本输入处理 - 触发后台任务

        【并发改造】任务不再阻塞等待完成，而是后台启动后立即返回启动确认。
        用户可以在任务执行期间继续聊天或查询进度。
        """
        _get_logger().info(f"[Dialogue] 文本输入，启动后台任务: {text[:50]}")
        if task_plan:
            _get_logger().info(f"[Dialogue] 携带思维编排的任务规划: {task_plan}")

        # ═══════════════════════════════════════════════════════════════
        # 【实时监控】启动监控分支
        # ═══════════════════════════════════════════════════════════════
        if mode == "start_monitor":
            return await self._start_realtime_monitor(user_id, session_id)

        # ═══════════════════════════════════════════════════════════════
        # 【视觉快速通道】明确视觉请求直接截图+视觉模型，不进入后台 AgentLoop
        # ═══════════════════════════════════════════════════════════════
        if context_flag == "force_vision":
            _get_logger().info(f"[DialogueManager] 明确视觉请求，走视觉快速通道: {text[:50]}")
            return await self._run_vision_fast_path(user_id, text, session_id, voice_instance)

        # 【并发控制】获取用户循环锁，防止同一用户同时运行多个 AgentLoop
        stop_event = await self._acquire_user_loop_lock_async(user_id)

        # 如果有旧的后台任务，取消它（一用户一任务原则）
        old_task = self._user_background_tasks.get(user_id)
        if old_task and not old_task.done():
            _get_logger().info(f"[DialogueManager] 取消用户 {user_id} 的旧后台任务")
            old_task.cancel()
        self._user_background_tasks.pop(user_id, None)
        with self._snapshot_lock:
            self._user_task_snapshots.pop(user_id, None)
        self._pause_requests.pop(user_id, None)
        self._interruption_requests.pop(user_id, None)

        # 获取或创建会话
        session = await self.get_or_create_session(user_id, session_id)
        session.last_active = datetime.now()

        # 【Phase 2 Week 3】获取或创建数据库session
        try:
            db_session_id, is_new = await self._get_or_create_db_session(
                user_id=user_id,
                session=session,
                mode=session.mode.value if hasattr(session.mode, 'value') else str(session.mode).lower(),
                title=self._generate_session_title(text)
            )
            if is_new:
                _get_logger().info(f"[DialogueManager] 自动创建数据库session: {db_session_id}")
        except Exception as e:
            _get_logger().error(f"[DialogueManager] 获取/创建数据库session失败: {e}", exc_info=True)

        # 记录用户输入
        session.chat_history.append({
            "role": "user",
            "content": text,
            "timestamp": datetime.now().isoformat()
        })

        # 【自我状态】如果意识线程提供了裁剪后的 task_package，LLM 只看 package
        instruction = task_package if task_package else text
        if task_package:
            session.chat_history[-1]["content"] = instruction
            session.chat_history[-1]["original_input"] = text
            _get_logger().info("[DialogueManager] 使用意识线程裁剪的 task_package 作为用户指令")

        # 【Phase 2 Week 3】存储用户输入到数据库（异步）
        async def _store_user_msg_async():
            try:
                msg_id = await self._store_user_message_async(session, instruction)
                if msg_id:
                    _get_logger().debug(f"[DialogueManager] 用户消息已存储到数据库: {msg_id}")
            except Exception as e:
                _get_logger().error(f"[DialogueManager] 存储用户消息失败: {e}")
        safe_create_task(_store_user_msg_async(), name="_store_user_msg_async")

        # [Agent-005 修复] 使用统一方法获取 voice 实例
        voice = self._get_voice_instance(voice_instance)

        # 【第一阶段改造 1.3】简单/复杂任务分流
        # 简单任务优先从实时监控快照提取坐标，直接注入上下文
        _rt_snapshot_for_fast = None
        _was_simple_task = self._is_simple_task(text)
        if _was_simple_task:
            _rt_key = f"{user_id}_realtime"
            with self._snapshot_lock:
                _rt_snapshot_for_fast = self._user_task_snapshots.get(_rt_key)
            if _rt_snapshot_for_fast:
                _enriched = self._build_simple_task_context(_rt_snapshot_for_fast, text)
                if _enriched != text:
                    text = _enriched
                    _get_logger().info(
                        f"[DialogueManager] 简单任务注入快照坐标上下文: user={user_id}"
                    )

        # 【第二阶段改造 2.4】快速通道真正短路
        # 简单任务 + 快照中有明确坐标 -> 直接调用 LLM + 工具，不走 AgentLoop
        if _was_simple_task and _rt_snapshot_for_fast:
            uia_objs = [o for o in _rt_snapshot_for_fast.get("objects", []) if o.get("source") == "uia"]
            if uia_objs:
                fast_result = await self._run_fast_path(
                    user_id, text, session_id, voice, _rt_snapshot_for_fast, uia_objs
                )
                if fast_result is not None:
                    # 快速通道成功，记录到聊天历史
                    session.chat_history.append({
                        "role": "assistant",
                        "content": fast_result.get("content", ""),
                        "timestamp": datetime.now().isoformat()
                    })
                    # 释放循环锁（因为没走 AgentLoop）
                    await self._release_user_loop_lock_async(user_id, stop_event)
                    return fast_result

        # 【后台化】启动任务但不等待完成
        from core.agent.task_mode_runner import TaskModeRunner
        runner = TaskModeRunner()

        async def _task_with_cleanup():
            """包装后台任务，在 finally 中释放锁，结果处理内联到协程中"""
            try:
                result = await runner.run(instruction, session_id, voice, chat_history=list(session.chat_history), user_id=user_id, context_flag=context_flag)
                # 【P1】长任务中断恢复：[PAUSED] 是特殊状态，不写入聊天历史
                if result == "[PAUSED]":
                    _get_logger().info(f"[DialogueManager] 后台任务因插话暂停: user={user_id}")
                    return result
                if result and session:
                    session.chat_history.append({
                        "role": "assistant",
                        "content": result,
                        "timestamp": datetime.now().isoformat()
                    })
                    try:
                        await self._store_assistant_message_async(session, result)
                    except Exception as e:
                        _get_logger().error(f"[DialogueManager] 存储AI回复失败: {e}")
                return result
            except Exception as e:
                _get_logger().error(f"[DialogueManager] 后台任务执行失败: {e}")
            finally:
                try:
                    await self._release_user_loop_lock_async(user_id, stop_event)
                except Exception as e:
                    _get_logger().error(f"[DialogueManager] 释放循环锁失败: {e}")

        task_handle = safe_create_task(_task_with_cleanup(), name="_task_with_cleanup")
        self._user_background_tasks[user_id] = task_handle

        # 在任务元数据中标记启动时间（供快照计算已耗时）
        try:
            with self._snapshot_lock:
                self._user_task_snapshots[user_id] = {
                    "started_at": datetime.now().isoformat(),
                    "instruction": text,
                }
        except Exception as e:
            logger.error(f"[DialogueManager] 保存用户任务快照失败: {e}", exc_info=True)

        # 任务完成回调：仅保留同步清理
        def _task_done_callback(t: asyncio.Task):
            self._on_background_task_done(user_id, t)

        task_handle.add_done_callback(_task_done_callback)

        # 立即返回启动确认，不等待任务完成
        return {
            "content": "任务已启动，我会后台处理。你可以随时问我进度，或者聊别的。",
            "mode": "task_started",
            "success": True
        }

    async def _start_realtime_monitor(self, user_id: str, session_id: str) -> dict:
        """
        启动实时桌面监控后台流水线

        流程：
        1. 获取或创建 DXGI 捕获实例
        2. 获取或创建 RealtimeDetector 实例
        3. 启动后台协程循环抓帧->检测->存快照
        4. 返回启动确认
        """
        # 【P0修复】独立视觉学习开关关闭时直接拒绝，不创建资源
        # 实时监控属于持续学习/标注流水线，不是决策时感知
        from core.config import config
        if not config.get("perception.learning_enabled", True):
            _get_logger().info(f"[DialogueManager] 视觉学习开关已关闭，拒绝启动实时监控: user={user_id}")
            return {
                "content": "视觉学习功能当前已关闭，如需开启请打开前端学习开关。",
                "mode": "task_started",
                "success": False
            }

        _get_logger().info(f"[DialogueManager] 启动实时监控: user={user_id}")

        # 清理旧的实时监控任务
        old_task = self._user_background_tasks.get(user_id)
        if old_task and not old_task.done():
            old_task.cancel()
            try:
                await asyncio.wait_for(old_task, timeout=2.0)
            except asyncio.TimeoutError:
                pass
            except asyncio.CancelledError:
                pass
        self._user_background_tasks.pop(user_id, None)
        with self._snapshot_lock:
            self._user_task_snapshots.pop(user_id + "_realtime", None)

        # 获取或创建 DXGI 捕获实例（按用户隔离）
        if not hasattr(self, '_realtime_captures'):
            self._realtime_captures: dict[str, Any] = {}
        if not hasattr(self, '_realtime_detectors'):
            self._realtime_detectors: dict[str, Any] = {}

        capture = self._realtime_captures.get(user_id)
        if capture is None:
            try:
                from core.vision.dxgi_capture import DXGICapture
                capture = DXGICapture(monitor_index=0, capture_rate=30)
                self._realtime_captures[user_id] = capture
            except Exception as e:
                _get_logger().error(f"[DialogueManager] DXGI 捕获器创建失败: {e}")
                return {
                    "content": f"实时监控启动失败：无法创建捕获器 ({str(e)[:50]})",
                    "mode": "task_started",
                    "success": False
                }

        detector = self._realtime_detectors.get(user_id)
        if detector is None:
            try:
                from core.vision.realtime_detector import RealtimeDetector
                detector = await RealtimeDetector.create_async()
                self._realtime_detectors[user_id] = detector
            except Exception as e:
                _get_logger().error(f"[DialogueManager] 检测器创建失败: {e}")
                return {
                    "content": f"实时监控启动失败：无法创建检测器 ({str(e)[:50]})",
                    "mode": "task_started",
                    "success": False
                }

        # 启动捕获
        try:
            capture.start()
        except Exception as e:
            _get_logger().warning(f"[DialogueManager] 捕获启动异常: {e}")

        # 定义后台流水线协程
        async def _realtime_monitor_loop():
            _get_logger().info(f"[RealtimeMonitor] 后台流水线启动: user={user_id}")
            loop_task = asyncio.current_task()
            consecutive_failures = 0

            # 【修复】缓存 consciousness 实例，减少锁竞争
            try:
                from core.consciousness.Consciousness import get_consciousness
                _consciousness_cached = get_consciousness(user_id)
            except Exception:
                _consciousness_cached = None

            # 【修复】detector 堆积：Semaphore + 自适应 sleep
            _detect_sem = asyncio.Semaphore(1)
            _last_detect_time = 0

            while True:
                # 【P0修复】受独立视觉学习开关控制，关闭时优雅休眠
                # 实时监控属于持续学习/标注流水线，不是决策时感知
                from core.config import config
                if not config.get("perception.learning_enabled", True):
                    await asyncio.sleep(5.0)
                    continue

                # 检查任务是否被取消
                if loop_task and loop_task.cancelled():
                    break
                # 也检查 DialogueManager 中的任务引用是否已被移除
                active_task = self._user_background_tasks.get(user_id)
                if active_task is not loop_task:
                    _get_logger().info(f"[RealtimeMonitor] 检测到任务被替换，退出循环: user={user_id}")
                    break

                # 【修复】前一轮 detector 未完成则跳过
                if _detect_sem.locked():
                    await asyncio.sleep(0.1)
                    continue

                # 【P0修复】用户交互期间暂停视觉检测，降低 GPU 占用
                if _consciousness_cached is not None and _consciousness_cached.is_user_input_paused():
                    await asyncio.sleep(0.5)
                    continue

                async with _detect_sem:
                    _last_detect_time = time.time()

                    try:
                        frame = capture.get_latest_frame()
                        if frame is None:
                            _get_logger().warning(
                                f"[RealtimeMonitor] 获取帧失败，跳过本轮检测: user={user_id}"
                            )
                            consecutive_failures += 1
                            if consecutive_failures >= 10:
                                _get_logger().error(
                                    f"[RealtimeMonitor] 连续 {consecutive_failures} 次获取帧失败，"
                                    f"流水线可能已断裂: user={user_id}"
                                )
                                consecutive_failures = 0
                            await asyncio.sleep(0.033)
                            continue

                        _get_logger().debug(f"[RealtimeMonitor] 成功获取帧, shape={frame.shape}, 开始检测...")

                        # 检测（异步线程安全，不阻塞事件循环）
                        result = await detector.detect(frame)

                        # 【VisionTagSystem】对检测到的物体做权重分级
                        try:
                            from core.vision.vision_tag_system import VisionTagSystem
                            _vts = VisionTagSystem()
                            alerts = []
                            for obj in result.get("objects", []):
                                tag = obj.get("class", "unknown")
                                level = _vts.classify(tag)
                                obj["_alert_level"] = level
                                if level == VisionTagSystem.L2_REPORT:
                                    alerts.append({
                                        "tag": tag,
                                        "bbox": obj.get("bbox"),
                                        "timestamp": time.time(),
                                        "level": "L2"
                                    })
                            if alerts:
                                result["alerts"] = alerts
                                self._last_vision_alerts = alerts
                                _get_logger().info(
                                    f"[RealtimeMonitor] 高权重告警触发: {len(alerts)} 个"
                                )
                        except Exception as te:
                            _get_logger().debug(f"[RealtimeMonitor] 标签分级失败(非阻塞): {te}")

                        # 写入共享快照
                        with self._snapshot_lock:
                            self._user_task_snapshots[f"{user_id}_realtime"] = result
                        _get_logger().debug(
                            f"[RealtimeMonitor] 快照已更新: user={user_id}, "
                            f"objects={len(result.get('objects', []))}, "
                            f"sources={ {obj.get('source','?'):1 for obj in result.get('objects',[])} }"
                        )

                        # 【重构】新增：推送实时数据到 Consciousness 感知缓冲区
                        try:
                            from core.consciousness.Consciousness import get_consciousness
                            _consciousness_push = get_consciousness()
                            if _consciousness_push is not None:
                                _perception_data = {
                                    "objects": result.get("objects", []),
                                    "timestamp": time.time(),
                                    "scene_id": result.get("scene_id", "unknown"),
                                    "dominant_app": result.get("dominant_app", "unknown"),
                                    "layout_summary": result.get("layout_summary", ""),
                                    "source": "realtime_monitor",
                                    "frame_path": result.get("frame_path"),  # 【训练模式】传递截图路径
                                }
                                objects_count = len(_perception_data.get("objects", []))
                                if objects_count == 0:
                                    _get_logger().debug("[RealtimeMonitor] push_perception: objects 为空，跳过推送")
                                else:
                                    _get_logger().debug(f"[RealtimeMonitor] push_perception: 推送 {objects_count} 个对象")
                                # 【红线】不传 frame，只传元数据
                                # 【红线】必须用 create_task 在主事件循环中执行
                                # 【P1修复】限制并发 push_perception 数量，避免孤儿任务堆积
                                try:
                                    await asyncio.wait_for(
                                        _consciousness_push.push_perception(_perception_data),
                                        timeout=2.0
                                    )
                                except asyncio.TimeoutError:
                                    _get_logger().debug("[RealtimeMonitor] push_perception 超时，跳过")
                        except Exception as _push_err:
                            _get_logger().debug(f"[RealtimeMonitor] 推送感知数据到 Consciousness 失败: {_push_err}")

                        # 【硅基生命】将视觉标签推送给意识核心
                        try:
                            from core.consciousness.Consciousness import get_consciousness
                            _consciousness = get_consciousness()
                            if _consciousness is not None and hasattr(_consciousness, 'on_vision_update'):
                                _tags_for_consciousness = result.get("objects", [])
                                _dominant_app = result.get("dominant_app", "")
                                _layout_summary = result.get("layout_summary", "")
                                if hasattr(self, '_last_vision_alerts') and self._last_vision_alerts:
                                    _alert_classes = {a.get("tag", ""): a.get("level", "L1") for a in self._last_vision_alerts}
                                    for _tag in _tags_for_consciousness:
                                        _class = _tag.get("class", "")
                                        if _class in _alert_classes:
                                            _tag["level"] = _alert_classes[_class]
                                _consciousness.on_vision_update(
                                    tags=_tags_for_consciousness,
                                    dominant_app=_dominant_app,
                                    layout_summary=_layout_summary
                                )
                        except Exception as _e:
                            _get_logger().warning(f"[RealtimeMonitor] 推送视觉标签给意识核心失败: {_e}")

                        # 成功执行一轮，重置失败计数
                        consecutive_failures = 0
                    except Exception as e:
                        consecutive_failures += 1
                        _get_logger().warning(
                            f"[RealtimeMonitor] 单轮检测异常 ({consecutive_failures}/10): {e}"
                        )
                        if consecutive_failures >= 10:
                            _get_logger().error(
                                f"[RealtimeMonitor] 视觉监控连续失败 {consecutive_failures} 次，"
                                f"自动停止监控循环: user={user_id}"
                            )
                            # 推送错误事件到 EventBus
                            try:
                                from core.sync.event_bus import event_bus as main_event_bus
                                main_event_bus.emit("vision_monitor_error", {
                                    "user_id": user_id,
                                    "consecutive_failures": consecutive_failures,
                                    "reason": str(e),
                                    "timestamp": time.time()
                                })
                            except Exception as bus_err:
                                _get_logger().warning(f"[RealtimeMonitor] 推送 vision_monitor_error 事件失败: {bus_err}")
                            break

                # 【修复】自适应 sleep
                elapsed = time.time() - _last_detect_time
                if elapsed > 0.1:
                    await asyncio.sleep(max(0, elapsed - 0.033))
                else:
                    await asyncio.sleep(0.033)

        # 启动后台任务
        monitor_task = safe_create_task(_realtime_monitor_loop(), name="_realtime_monitor_loop")
        self._user_background_tasks[user_id] = monitor_task

        # 注册清理回调
        def _monitor_done_callback(t: asyncio.Task):
            # 【P0修复】校验当前活跃任务是否仍是本任务，避免误清理新任务资源
            current_active = self._user_background_tasks.get(user_id)
            if current_active is not t:
                _get_logger().info(
                    f"[RealtimeMonitor] 跳过旧任务清理（已有新任务）: user={user_id}"
                )
                return
            try:
                if not t.cancelled():
                    t.result()
            except Exception as e:
                _get_logger().warning(f"[RealtimeMonitor] 后台任务异常结束: {e}")
            finally:
                # 清理 DXGI 资源
                cap = self._realtime_captures.pop(user_id, None)
                if cap:
                    try:
                        cap.stop()
                    except Exception as stop_err:
                        _get_logger().warning(f"[RealtimeMonitor] 清理 DXGI 资源失败: {stop_err}")
                self._realtime_detectors.pop(user_id, None)
                with self._snapshot_lock:
                    self._user_task_snapshots.pop(user_id + "_realtime", None)
                _get_logger().info(f"[RealtimeMonitor] 资源已清理: user={user_id}")

        monitor_task.add_done_callback(_monitor_done_callback)

        return {
            "content": "实时监控已启动，我会持续分析你的屏幕画面。你可以随时问'现在什么情况'。",
            "mode": "task_started",
            "success": True
        }

    async def _handle_voice_chat(self, user_id: str, text: str, session_id: str,
                           input_mode: InputMode, voice_instance):
        """
        语音输入处理 - 进入聊天对齐需求
        语音输入需要和AI聊天确认需求，可随时更改
        """
        _get_logger().info(f"[Dialogue] 语音输入({input_mode.value})，进入聊天对齐")

        # 获取或创建会话
        session = await self.get_or_create_session(user_id, session_id)
        session.last_active = datetime.now()

        # 【Phase 2 Week 3】获取或创建数据库session
        try:
            db_session_id, is_new = await self._get_or_create_db_session(
                user_id=user_id,
                session=session,
                mode="daily",
                title=self._generate_session_title(text)
            )
            if is_new:
                _get_logger().info(f"[DialogueManager] 自动创建语音数据库session: {db_session_id}")
        except Exception as e:
            _get_logger().error(f"[DialogueManager] 获取/创建语音数据库session失败: {e}", exc_info=True)

        # 记录用户输入
        session.chat_history.append({
            "role": "user",
            "content": text,
            "timestamp": datetime.now().isoformat()
        })

        # 【Phase 2 Week 3】存储用户输入到数据库（原生异步）
        asyncio.create_task(
            self._store_user_message_async(
                session,
                text,
                metadata={"input_mode": "voice", "source": "voice_recognition"}
            )
        )

        # [Agent-005 修复] 使用统一方法获取 voice 实例
        voice = self._get_voice_instance(voice_instance)

        # 语音播报：正在理解您的需求
        if voice:
            voice.speak(DialogueManagerAnnouncements.UNDERSTANDING)

        # 进入聊天模式对齐需求
        from core.dialog.chat_mode_handler import ChatModeHandler
        chat_handler = ChatModeHandler(user_id=user_id)

        chat_reply, needs_task, task_desc = await chat_handler.handle(text, session_id, voice)

        # 对齐后由AI决定是否触发任务
        if needs_task and task_desc:
            _get_logger().info(f"[Dialogue] AI决定触发任务: {task_desc}")

            # 播报过渡语
            if voice:
                voice.speak(f"好的，我来{task_desc}")

            from core.agent.task_mode_runner import TaskModeRunner
            runner = TaskModeRunner()
            result = await runner.run(task_desc, session_id, voice, user_id=user_id)

            # 记录AI回复
            if result:
                session.chat_history.append({
                    "role": "assistant",
                    "content": result,
                    "timestamp": datetime.now().isoformat()
                })

                # 【Phase 2 Week 3】存储AI回复到数据库（原生异步）
                safe_create_task(self._store_assistant_message_async(session, result), name="_store_assistant_message_async")

            return {
                "success": True,
                "mode": "task",
                "chat_reply": chat_reply,
                "task_description": task_desc,
                "result": result
            }

        # 记录AI回复（纯聊天模式）
        if chat_reply:
            session.chat_history.append({
                "role": "assistant",
                "content": chat_reply,
                "timestamp": datetime.now().isoformat()
            })

            # 【Phase 2 Week 3】存储AI回复到数据库（原生异步）
            asyncio.create_task(
                self._store_assistant_message_async(
                    session,
                    chat_reply,
                    metadata={"input_mode": "voice", "type": "chat_alignment"}
                )
            )

        return {
            "success": True,
            "mode": "chat_alignment",
            "chat_reply": chat_reply,  # 统一字段名，与 cloud_api.py 保持一致
            "needs_task": False
        }


# 全局单例
dialogue_manager = DialogueManager()             # 创建全局唯一实例


# ==================== 向后兼容函数 ====================
# 以下函数为旧代码提供便捷的调用接口，保持向后兼容

def create_user_session(
    user_id: str = "default",
    session_id: str = None,
    mode: WorkMode = WorkMode.DAILY
) -> UserSession:
    """创建用户会话的便捷函数"""
    return dialogue_manager.create_session(user_id, session_id, mode)


def get_user_session(user_id: str, session_id: str) -> UserSession | None:
    """获取用户会话的便捷函数"""
    return dialogue_manager.get_session(user_id, session_id)


async def handle_user_text(
    user_id: str,
    text: str,
    session_id: str = None,
    **kwargs
) -> str:
    """处理用户文本的便捷函数"""
    return await dialogue_manager.handle_text_input(user_id, text, session_id, **kwargs)


async def handle_user_voice(
    user_id: str,
    text: str,
    session_id: str = None,
    **kwargs
) -> str:
    """处理用户语音的便捷函数"""
    return await dialogue_manager.handle_voice_input(user_id, text, session_id, **kwargs)


# ==================== Phase 2 Week 4 - 目标对齐便捷函数 ====================

async def handle_user_input_with_alignment(
    user_id: str,
    text: str,
    session_id: str = None
) -> dict[str, Any]:
    """
    带目标对齐的用户输入处理便捷函数

    Returns:
        Dict: 包含type字段的结果
            - 'aligned': 已对齐，包含execution_result
            - 'clarification_needed': 需要澄清，包含question和options
            - 'confirmation_needed': 需要确认，包含message
    """
    return await dialogue_manager.handle_user_input(user_id, text, session_id)


async def handle_clarification_response(
    user_id: str,
    response: str,
    session_id: str = None,
    selected_option: str = None
) -> dict[str, Any]:
    """处理澄清回复的便捷函数"""
    return await dialogue_manager.handle_clarification_response(
        user_id, response, session_id, selected_option
    )


async def handle_confirmation_response(
    user_id: str,
    confirmed: bool,
    session_id: str = None,
    correction: str = None
) -> dict[str, Any]:
    """处理确认回复的便捷函数"""
    return await dialogue_manager.handle_confirmation_response(
        user_id, confirmed, session_id, correction
    )


# ============================================
# 文件总结性注释
# ============================================
#
# 【文件角色】
# dialogue_manager.py 是 SiliconBase V5.1 系统的"对话管理器"核心模块，
# 是多用户会话隔离架构的核心实现。
#
# 核心定位：
# - 管理所有用户的会话生命周期（创建、获取、关闭、清理）
# - 处理用户输入（文本/语音）并路由到相应处理器
# - 维护用户级的聊天历史和会话状态
# - 提供PTT（免唤醒）状态管理
# - 【Phase 2 Week 3】自动持久化对话到PostgreSQL数据库
#
# 架构位置：
#   Frontend (Web/Voice) → DialogueManager → ChatModeHandler → Agent Loop
#                                    ↓
#                           UserSession (会话数据隔离)
#                                    ↓
#                           SessionManager (数据库存储)
#
# 【关联文件】
#
# | 文件 | 关系类型 | 说明 |
# |------|----------|------|
# | chat_mode_handler.py | 调用 | 处理文本/语音的主要逻辑，DualModeManager |
# | work_mode_manager.py | 依赖 | 导入WorkMode枚举（Daily/Focus模式） |
# | social_reasoning.py | 依赖 | 社会推理引擎，情感分析和欺骗检测 |
# | multi_user.py | 依赖 | 多用户管理器，更新用户上下文 |
# | realtime_sync.py | 依赖 | 实时同步管理器，通知前端状态变化 |
# | global_state.py | 依赖 | 获取voice接口实例 |
# | nlp_intent_parser.py | 依赖 | 意图解析器（延迟加载） |
# | command_parser.py | 依赖 | 命令解析器（延迟加载） |
# | session_manager.py | 依赖 | 【Phase 2 Week 3】数据库存储 |
#
# 【达到的效果】
#
# 1. 多用户会话完全隔离
#    - 用户A的会话数据对用户B完全不可见
#    - 二级字典结构：user_id → session_id → UserSession
#    - 线程安全的会话操作（RLock保护）
#
# 2. 向后兼容单用户模式
#    - 旧代码可通过 user_id="default" 继续使用
#    - 提供便捷的向后兼容函数（create_user_session等）
#    - DialogueWorkMode别名保持兼容性
#
# 3. 三种输入方式统一处理
#    - TEXT：文本输入，直接触发任务
#    - VOICE_WAKE：语音唤醒，进入聊天对齐
#    - VOICE_FRONTEND：前端语音，进入聊天对齐
#
# 4. 【Phase 2 Week 3】数据持久化
#    - 对话消息自动存储到PostgreSQL数据库
#    - SessionManager管理数据库会话和消息
#    - 支持重试机制（最多3次），失败不中断对话
#    - 异步存储，不影响对话响应时间
#
# 5. 完善的异常处理和降级机制
#    - P0-001修复：删除重复解析代码，避免性能浪费
#    - P0-003修复：语音处理失败时自动降级到文本模式
#    - 防御性编程：严格类型检查，处理slice等异常类型
#
# 6. PTT免唤醒管理（用户隔离）
#    - 每个用户独立的PTT状态
#    - 支持toggle、查询持续时间
#    - 线程安全的并发控制
#
# 7. 社会推理集成
#    - 情感分析：分析用户输入情感倾向
#    - 欺骗检测：识别可能的欺骗行为
#    - 安全回复：检测到欺骗时返回安全回复
#
# 【核心类结构】
#
# | 类名 | 职责 |
# |------|------|
# | InputMode | 枚举：三种输入方式定义 |
# | UserSession | 数据类：用户会话数据封装（含db_session_id） |
# | PTTManager | PTT状态管理（按用户隔离） |
# | DialogueManager | 核心管理器（单例模式） |
#
# 【Phase 2 Week 3 新增方法】
#
# | 方法名 | 职责 |
# |--------|------|
# | session_manager | 属性：延迟加载SessionManager |
# | _generate_session_title | 从用户输入生成会话标题 |
# | _get_or_create_db_session | 获取或创建数据库session |
# | _store_message_with_retry | 带重试机制的消息存储（最多3次） |
# | _store_user_message | 存储用户消息到数据库 |
# | _store_assistant_message | 存储AI回复消息到数据库 |
#
# 【会话数据结构】
#
# ```
# _user_sessions: Dict[str, Dict[str, UserSession]]
#     ↓ user_id
#     {"user_001": {
#         ↓ session_id
#         "sess_abc": UserSession(...),
#         "sess_xyz": UserSession(...)
#     }}
#
# UserSession.db_session_id: 关联的数据库session ID
# ```
#
# 【关键修复历史】
#
# - P0-001：删除重复解析代码，统一在chat_mode_handler处理
# - P0-003：语音异常时自动降级到文本模式，通知用户
# - 防御性类型检查：处理slice等不可哈希类型异常
# - voice实例恢复：支持从global_state和__main__恢复
# - Phase 2 Week 3：添加数据持久化支持
#
# ============================================


def get_dialogue_manager() -> DialogueManager:
    """获取对话管理器单例（向后兼容）

    供voice_service等模块使用，避免直接导入实例导致的循环依赖问题

    Returns:
        DialogueManager: 对话管理器单例实例
    """
    return dialogue_manager


# ═══════════════════════════════════════════════════════════════
# 【演示学习系统集成】便捷函数
# ═══════════════════════════════════════════════════════════════

def get_procedure_library_instance():
    """获取流程库实例便捷函数"""
    return dialogue_manager.procedure_library


def get_task_coordinator_instance():
    """获取任务协调器实例便捷函数"""
    return dialogue_manager.task_coordinator


async def start_demonstration(user_id: str, session_id: str) -> str:
    """
    开始用户演示便捷函数

    Args:
        user_id: 用户ID
        session_id: 会话ID

    Returns:
        str: 响应消息
    """
    return await dialogue_manager._start_user_demonstration(user_id, session_id)


async def stop_demonstration(user_id: str, session_id: str) -> str:
    """
    停止用户演示便捷函数

    Args:
        user_id: 用户ID
        session_id: 会话ID

    Returns:
        str: 响应消息
    """
    return await dialogue_manager._stop_user_demonstration(user_id, session_id)


def list_learned_procedures(limit: int = 10) -> list:
    """
    列出已学习的流程便捷函数

    Args:
        limit: 返回数量限制

    Returns:
        list: 流程列表
    """
    procedures = dialogue_manager.procedure_library.list_procedures(
        active_only=True,
        sort_by="usage_count"
    )
    return [
        {
            "id": p.procedure_id,
            "name": p.name,
            "intent": p.intent,
            "steps": len(p.steps),
            "success_rate": p.get_success_rate(),
            "usage_count": p.usage_count
        }
        for p in procedures[:limit]
    ]


def get_demonstration_status(user_id: str, session_id: str) -> dict[str, Any] | None:
    """
    获取演示状态便捷函数

    Args:
        user_id: 用户ID
        session_id: 会话ID

    Returns:
        Optional[Dict]: 演示状态
    """
    return dialogue_manager.get_demonstration_status(session_id)
