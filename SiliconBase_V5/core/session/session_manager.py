#!/usr/bin/env python3
"""
SessionManager - 会话管理核心类
Phase 1 Week 1 - 任务2

提供会话的创建、查询、更新、删除以及消息管理功能。
"""

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from core.logger import logger


class SessionStatus(str, Enum):
    """会话状态枚举"""
    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"


class SessionMode(str, Enum):
    """会话模式枚举 - 匹配数据库约束"""
    DAILY = "daily"
    FOCUS = "focus"
    ANALYSIS = "analysis"
    DEBUG = "debug"


@dataclass
class Session:
    """
    会话数据类

    Attributes:
        id: 会话唯一标识 (UUID字符串)
        user_id: 用户ID
        title: 会话标题
        mode: 会话模式
        status: 会话状态
        metadata: 会话元数据
        message_count: 消息数量
        last_message_at: 最后消息时间
        created_at: 创建时间
        updated_at: 更新时间
        last_message_preview: 最新消息预览（查询时填充）
    """
    id: str
    user_id: str
    title: str | None = None
    mode: str = "daily"
    status: str = "active"
    metadata: dict[str, Any] = field(default_factory=dict)
    message_count: int = 0
    last_message_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_message_preview: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "title": self.title,
            "mode": self.mode,
            "status": self.status,
            "metadata": self.metadata,
            "message_count": self.message_count,
            "last_message_at": self.last_message_at.isoformat() if self.last_message_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "last_message_preview": self.last_message_preview,
        }


@dataclass
class SessionMessage:
    """
    会话消息数据类

    Attributes:
        id: 消息唯一标识 (UUID字符串)
        session_id: 所属会话ID
        role: 消息角色 (user/assistant/system/tool)
        content: 消息内容
        content_type: 内容类型 (text/image/audio/file/mixed)
        metadata: 消息元数据
        tool_calls: 工具调用信息
        thinking: AI思考过程
        memory_id: 关联的L2记忆ID
        created_at: 创建时间
    """
    id: str
    session_id: str
    role: str
    content: str
    content_type: str = "text"
    metadata: dict[str, Any] = field(default_factory=dict)
    tool_calls: dict[str, Any] | None = None
    thinking: str | None = None
    memory_id: str | None = None
    created_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "session_id": self.session_id,
            "role": self.role,
            "content": self.content,
            "content_type": self.content_type,
            "metadata": self.metadata,
            "tool_calls": self.tool_calls,
            "thinking": self.thinking,
            "memory_id": self.memory_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class SessionManagerError(Exception):
    """会话管理器基础异常"""
    pass


class SessionNotFoundError(SessionManagerError):
    """会话不存在异常"""
    pass


class SessionCreateError(SessionManagerError):
    """会话创建异常"""
    pass


class SessionUpdateError(SessionManagerError):
    """会话更新异常"""
    pass


class SessionDeleteError(SessionManagerError):
    """会话删除异常"""
    pass


class MessageAddError(SessionManagerError):
    """消息添加异常"""
    pass


class SessionManager:
    """
    会话管理器

    提供完整的会话生命周期管理和消息操作功能。
    所有数据库操作使用连接池，确保资源正确释放。

    依赖表结构（任务1创建）：
    - sessions: 会话主表
    - session_messages: 会话消息表
    """

    def __init__(self):
        """初始化会话管理器"""
        self.logger = logger
        self.logger.info("[SessionManager] 初始化完成")

    def _generate_uuid(self) -> str:
        """生成UUID字符串"""
        return str(uuid.uuid4())

    async def update_message_memory_id(
        self,
        message_id: str,
        memory_id: str
    ) -> bool:
        """
        异步更新消息关联的记忆ID（使用 asyncpg）

        Args:
            message_id: 消息ID
            memory_id: 记忆ID

        Returns:
            bool: 是否更新成功

        Note:
            同步版本 update_message_memory_id 保留用于同步调用方
        """
        if not message_id:
            self.logger.warning("[SessionManager] update_message_memory_id_async被调用时message_id为空")
            return False
        if not memory_id:
            self.logger.warning("[SessionManager] update_message_memory_id_async被调用时memory_id为空")
            return False

        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    UPDATE session_messages
                    SET memory_id = $1
                    WHERE id = $2
                    RETURNING id
                    """,
                    memory_id, message_id
                )
                if row:
                    self.logger.debug(
                        f"[SessionManager] 消息memory_id更新成功: "
                        f"message_id={message_id}, memory_id={memory_id}"
                    )
                    return True
                else:
                    self.logger.warning(
                        f"[SessionManager] 更新消息memory_id失败，消息不存在: "
                        f"message_id={message_id}"
                    )
                    return False
        except Exception as e:
            self.logger.error(
                f"[SessionManager] 更新消息memory_id失败: "
                f"message_id={message_id}, memory_id={memory_id}, error={e}",
                exc_info=True
            )
            return False

    # ============================================================================
    # 异步 API（原生 asyncpg，避免阻塞事件循环）
    # ============================================================================

    async def create_session(
        self,
        user_id: str,
        title: str | None = None,
        mode: str = "daily",
        initial_context: dict[str, Any] | None = None
    ) -> Session:
        """创建新会话"""
        if not user_id:
            raise ValueError("user_id不能为空")
        valid_modes = [m.value for m in SessionMode]
        if mode not in valid_modes:
            raise ValueError(f"无效的mode: {mode}，允许的值为: {valid_modes}")

        session_id = self._generate_uuid()
        now = datetime.now()
        metadata = initial_context or {}

        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO sessions
                    (id, user_id, title, mode, status, metadata,
                     message_count, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    RETURNING id, user_id, title, mode, status, metadata,
                              message_count, last_message_at, created_at, updated_at
                    """,
                    session_id, user_id, title, mode, "active",
                    json.dumps(metadata), 0, now, now
                )
                session = Session(
                    id=str(row["id"]),
                    user_id=row["user_id"],
                    title=row["title"],
                    mode=row["mode"],
                    status=row["status"],
                    metadata=row["metadata"] if isinstance(row["metadata"], dict) else (json.loads(row["metadata"]) if row["metadata"] else {}),
                    message_count=row["message_count"],
                    last_message_at=row["last_message_at"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
                self.logger.info(
                    f"[SessionManager] 会话创建成功: {session_id}, user_id={user_id}, mode={mode}"
                )
                return session
        except Exception as e:
            self.logger.error(
                f"[SessionManager] 创建会话失败: user_id={user_id}, error={e}",
                exc_info=True
            )
            raise SessionCreateError(f"创建会话失败: {e}") from e

    async def get_session(self, session_id: str) -> Session | None:
        """获取单个会话"""
        if not session_id:
            self.logger.warning("[SessionManager] get_session_async被调用时session_id为空")
            return None

        # 入口校验：session_id 必须是合法 UUID
        try:
            uuid.UUID(session_id)
        except ValueError:
            self.logger.warning(f"[SessionManager] get_session_async 收到非法 UUID session_id={session_id}，返回 None")
            return None

        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT id, user_id, title, mode, status, metadata,
                           message_count, last_message_at, created_at, updated_at
                    FROM sessions
                    WHERE id = $1 AND status != 'deleted'
                    """,
                    session_id
                )
                if not row:
                    return None

                last_preview = None
                last_msg = await conn.fetchrow(
                    """
                    SELECT content FROM session_messages
                    WHERE session_id = $1 ORDER BY created_at DESC LIMIT 1
                    """,
                    session_id
                )
                if last_msg and last_msg["content"]:
                    content = last_msg["content"]
                    last_preview = content[:100] + "..." if len(content) > 100 else content

                return Session(
                    id=str(row["id"]),
                    user_id=row["user_id"],
                    title=row["title"],
                    mode=row["mode"],
                    status=row["status"],
                    metadata=row["metadata"] if isinstance(row["metadata"], dict) else (json.loads(row["metadata"]) if row["metadata"] else {}),
                    message_count=row["message_count"],
                    last_message_at=row["last_message_at"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    last_message_preview=last_preview,
                )
        except Exception as e:
            self.logger.error(
                f"[SessionManager] 获取会话失败: session_id={session_id}, error={e}",
                exc_info=True
            )
            raise SessionManagerError(f"异步获取会话时发生错误: {e}") from e

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        **kwargs
    ) -> str:
        """添加消息到会话"""
        if not session_id:
            raise ValueError("session_id不能为空")
        if not role:
            raise ValueError("role不能为空")
        if not content:
            raise ValueError("content不能为空")

        valid_roles = ["user", "assistant", "system", "tool"]
        if role not in valid_roles:
            raise ValueError(f"无效的role: {role}，允许的值为: {valid_roles}")

        message_id = self._generate_uuid()
        now = datetime.now()
        metadata = kwargs.get("metadata", {})
        content_type = kwargs.get("content_type", "text")
        tool_calls = kwargs.get("tool_calls")
        thinking = kwargs.get("thinking")
        memory_id = kwargs.get("memory_id")

        valid_content_types = ["text", "image", "audio", "file", "mixed"]
        if content_type not in valid_content_types:
            raise ValueError(f"无效的content_type: {content_type}，允许的值为: {valid_content_types}")

        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                # 检查会话是否存在
                sess = await conn.fetchrow(
                    "SELECT id FROM sessions WHERE id = $1 AND status != 'deleted'",
                    session_id
                )
                if not sess:
                    raise SessionNotFoundError(f"会话不存在: {session_id}")

                await conn.execute(
                    """
                    INSERT INTO session_messages
                    (id, session_id, role, content, content_type, metadata,
                     tool_calls, thinking, memory_id, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    """,
                    message_id, session_id, role, content, content_type,
                    json.dumps(metadata),
                    json.dumps(tool_calls) if tool_calls else None,
                    thinking,
                    memory_id,
                    now
                )
                await conn.execute(
                    """
                    UPDATE sessions
                    SET last_message_at = $1, message_count = message_count + 1
                    WHERE id = $2
                    """,
                    now, session_id
                )
                self.logger.debug(
                    f"[SessionManager] 消息添加成功: message_id={message_id}, session_id={session_id}, role={role}"
                )
                return message_id
        except SessionNotFoundError:
            raise
        except Exception as e:
            self.logger.error(
                f"[SessionManager] 添加消息失败: session_id={session_id}, error={e}",
                exc_info=True
            )
            raise MessageAddError(f"添加消息时发生错误: {e}") from e

    async def get_messages(
        self,
        session_id: str,
        limit: int = 50,
        before_id: str | None = None
    ) -> tuple[bool, str | None, list[SessionMessage]]:
        """分页获取会话消息"""
        if not session_id:
            raise ValueError("session_id不能为空")

        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                sess = await conn.fetchrow(
                    "SELECT id FROM sessions WHERE id = $1",
                    session_id
                )
                if not sess:
                    raise SessionNotFoundError(f"会话不存在: {session_id}")

                params = [session_id]
                where_clause = "session_id = $1"
                param_idx = 2

                if before_id:
                    cursor_row = await conn.fetchrow(
                        "SELECT created_at FROM session_messages WHERE id = $1",
                        before_id
                    )
                    if cursor_row:
                        where_clause += f" AND created_at < ${param_idx}"
                        params.append(cursor_row["created_at"])
                        param_idx += 1

                rows = await conn.fetch(
                    f"""
                    SELECT id, session_id, role, content, content_type, metadata,
                           tool_calls, thinking, memory_id, created_at
                    FROM session_messages
                    WHERE {where_clause}
                    ORDER BY created_at DESC
                    LIMIT ${param_idx}
                    """,
                    *params, limit + 1
                )

                has_more = len(rows) > limit
                if has_more:
                    rows = rows[:limit]

                messages = []
                for row in rows:
                    msg = SessionMessage(
                        id=str(row["id"]),
                        session_id=str(row["session_id"]),
                        role=row["role"],
                        content=row["content"],
                        content_type=row["content_type"],
                        metadata=row["metadata"] if isinstance(row["metadata"], dict) else (json.loads(row["metadata"]) if row["metadata"] else {}),
                        tool_calls=row["tool_calls"] if isinstance(row["tool_calls"], dict) else (json.loads(row["tool_calls"]) if row["tool_calls"] else None),
                        thinking=row["thinking"],
                        memory_id=str(row["memory_id"]) if row["memory_id"] else None,
                        created_at=row["created_at"],
                    )
                    messages.append(msg)

                next_cursor = messages[-1].id if has_more and messages else None
                return has_more, next_cursor, messages
        except SessionNotFoundError:
            raise
        except Exception as e:
            self.logger.error(
                f"[SessionManager] 获取消息失败: session_id={session_id}, error={e}",
                exc_info=True
            )
            raise SessionManagerError(f"获取消息时发生错误: {e}") from e

    async def list_sessions(
        self,
        user_id: str,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None
    ) -> tuple[int, list[Session]]:
        """分页获取用户会话列表"""
        if not user_id:
            raise ValueError("user_id不能为空")
        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                where_clause = "user_id = $1 AND status != 'deleted'"
                params = [user_id]
                param_idx = 2
                if status:
                    where_clause += f" AND status = ${param_idx}"
                    params.append(status)
                    param_idx += 1
                total_row = await conn.fetchrow(
                    f"SELECT COUNT(*) FROM sessions WHERE {where_clause}",
                    *params
                )
                total = total_row["count"]
                rows = await conn.fetch(
                    f"""
                    SELECT id, user_id, title, mode, status, metadata,
                           message_count, last_message_at, created_at, updated_at
                    FROM sessions
                    WHERE {where_clause}
                    ORDER BY updated_at DESC
                    LIMIT ${param_idx} OFFSET ${param_idx + 1}
                    """,
                    *params, limit, offset
                )
                sessions = []
                for row in rows:
                    sessions.append(Session(
                        id=str(row["id"]),
                        user_id=row["user_id"],
                        title=row["title"],
                        mode=row["mode"],
                        status=row["status"],
                        metadata=row["metadata"] if isinstance(row["metadata"], dict) else (json.loads(row["metadata"]) if row["metadata"] else {}),
                        message_count=row["message_count"],
                        last_message_at=row["last_message_at"],
                        created_at=row["created_at"],
                        updated_at=row["updated_at"],
                    ))
                return total, sessions
        except Exception as e:
            self.logger.error(f"[SessionManager] 获取会话列表失败: {e}", exc_info=True)
            raise SessionManagerError(f"获取会话列表时发生错误: {e}") from e

    async def update_session(
        self,
        session_id: str,
        updates: dict[str, Any]
    ) -> Session:
        """更新会话信息"""
        if not session_id:
            raise ValueError("session_id不能为空")
        if not updates:
            raise ValueError("updates不能为空")
        allowed_fields = {"title", "status", "mode", "metadata"}
        update_fields = {k: v for k, v in updates.items() if k in allowed_fields}
        if not update_fields:
            raise ValueError(f"updates中没有有效的更新字段，允许的字段: {allowed_fields}")
        if "mode" in update_fields:
            valid_modes = [m.value for m in SessionMode]
            if update_fields["mode"] not in valid_modes:
                raise ValueError(f"无效的mode: {update_fields['mode']}")
        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                exists = await conn.fetchrow(
                    "SELECT id FROM sessions WHERE id = $1 AND status != 'deleted'",
                    session_id
                )
                if not exists:
                    raise SessionNotFoundError(f"会话不存在: {session_id}")
                set_clauses = []
                params = []
                param_idx = 1
                for field_name, value in update_fields.items():
                    if field_name == "metadata" and isinstance(value, dict):
                        set_clauses.append(f"{field_name} = ${param_idx}")
                        params.append(json.dumps(value))
                    else:
                        set_clauses.append(f"{field_name} = ${param_idx}")
                        params.append(value)
                    param_idx += 1
                params.append(session_id)
                row = await conn.fetchrow(
                    f"""
                    UPDATE sessions
                    SET {', '.join(set_clauses)}
                    WHERE id = ${param_idx}
                    RETURNING id, user_id, title, mode, status, metadata,
                              message_count, last_message_at, created_at, updated_at
                    """,
                    *params
                )
                return Session(
                    id=str(row["id"]),
                    user_id=row["user_id"],
                    title=row["title"],
                    mode=row["mode"],
                    status=row["status"],
                    metadata=row["metadata"] if isinstance(row["metadata"], dict) else (json.loads(row["metadata"]) if row["metadata"] else {}),
                    message_count=row["message_count"],
                    last_message_at=row["last_message_at"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
        except SessionNotFoundError:
            raise
        except Exception as e:
            self.logger.error(f"[SessionManager] 更新会话失败: {e}", exc_info=True)
            raise SessionUpdateError(f"更新会话时发生错误: {e}") from e

    async def delete_session(self, session_id: str) -> int:
        """删除会话（级联删除消息）"""
        if not session_id:
            raise ValueError("session_id不能为空")
        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            async with pool.acquire() as conn:
                exists = await conn.fetchrow(
                    "SELECT id FROM sessions WHERE id = $1 AND status != 'deleted'",
                    session_id
                )
                if not exists:
                    raise SessionNotFoundError(f"会话不存在: {session_id}")
                count_row = await conn.fetchrow(
                    "SELECT COUNT(*) FROM session_messages WHERE session_id = $1",
                    session_id
                )
                message_count = count_row["count"]
                await conn.execute(
                    "DELETE FROM sessions WHERE id = $1",
                    session_id
                )
                self.logger.info(f"[SessionManager] 删除会话成功: {session_id}, messages={message_count}")
                return message_count
        except SessionNotFoundError:
            raise
        except Exception as e:
            self.logger.error(f"[SessionManager] 异步删除会话失败: {e}", exc_info=True)
            raise SessionDeleteError(f"删除会话时发生错误: {e}") from e




# ============================================================================
# 便捷函数（模块级别）
# ============================================================================

_session_manager: SessionManager | None = None


def get_session_manager() -> SessionManager:
    """获取SessionManager单例"""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager


async def create_session(
    user_id: str,
    title: str | None = None,
    mode: str = "daily",
    initial_context: dict[str, Any] | None = None
) -> Session:
    """便捷函数：创建会话"""
    return await get_session_manager().create_session(user_id, title, mode, initial_context)


async def get_session(session_id: str) -> Session | None:
    """便捷函数：获取会话"""
    return await get_session_manager().get_session(session_id)


async def list_sessions(
    user_id: str,
    limit: int = 20,
    offset: int = 0,
    status: str | None = None
) -> tuple[int, list[Session]]:
    """便捷函数：获取会话列表"""
    return await get_session_manager().list_sessions(user_id, limit, offset, status)


async def update_session(session_id: str, updates: dict[str, Any]) -> Session:
    """便捷函数：更新会话"""
    return await get_session_manager().update_session(session_id, updates)


async def delete_session(session_id: str) -> int:
    """便捷函数：删除会话"""
    return await get_session_manager().delete_session(session_id)


async def add_message(
    session_id: str,
    role: str,
    content: str,
    **kwargs
) -> str:
    """便捷函数：添加消息"""
    return await get_session_manager().add_message(session_id, role, content, **kwargs)


async def get_messages(
    session_id: str,
    limit: int = 50,
    before_id: str | None = None
) -> tuple[bool, str | None, list[SessionMessage]]:
    """便捷函数：获取消息"""
    return await get_session_manager().get_messages(session_id, limit, before_id)


async def update_message_memory_id(message_id: str, memory_id: str) -> bool:
    """便捷函数：更新消息关联的记忆ID"""
    return await get_session_manager().update_message_memory_id(message_id, memory_id)


# ============================================================================
# 单元测试
# ============================================================================

async def _run_tests():
    import sys
    print("=" * 60)
    print("SessionManager 单元测试")
    print("=" * 60)
    TEST_USER_ID = "test_user_001"
    manager = SessionManager()
    test_session_id = None
    try:
        print("\n[测试1] 创建会话...")
        session = await manager.create_session(
            user_id=TEST_USER_ID, title="测试会话", mode="daily", initial_context={"test": True}
        )
        test_session_id = session.id
        print(f"✓ 会话创建成功: {session.id}")
        print("\n[测试2] 添加消息...")
        msg1_id = await manager.add_message(
            session_id=test_session_id, role="user", content="你好，这是一个测试消息", metadata={"source": "test"}
        )
        print(f"✓ 消息1添加成功: {msg1_id}")
        msg2_id = await manager.add_message(
            session_id=test_session_id, role="assistant", content="收到，测试消息已记录"
        )
        print(f"✓ 消息2添加成功: {msg2_id}")
        print("\n[测试3] 获取会话...")
        session = await manager.get_session(test_session_id)
        print(f"✓ 会话获取成功, message_count: {session.message_count}")
        print("\n[测试4] 获取消息...")
        has_more, next_cursor, messages = await manager.get_messages(session_id=test_session_id, limit=10)
        print(f"✓ 消息获取成功, count: {len(messages)}")
        print("\n[测试5] 更新会话...")
        updated = await manager.update_session(session_id=test_session_id, updates={"title": "更新后的标题", "status": "archived"})
        print(f"✓ 会话更新成功, title: {updated.title}")
        print("\n[测试6] 获取会话列表...")
        total, sessions = await manager.list_sessions(user_id=TEST_USER_ID, limit=10)
        print(f"✓ 会话列表获取成功, total: {total}")
        print("\n[测试7] 删除会话...")
        deleted_count = await manager.delete_session(test_session_id)
        print(f"✓ 会话删除成功, deleted_messages: {deleted_count}")
        print("\n[测试8] 验证删除...")
        deleted_session = await manager.get_session(test_session_id)
        if deleted_session is None:
            print("✓ 会话已正确删除")
        else:
            print("✗ 会话仍然存在")
            sys.exit(1)
        print("\n" + "=" * 60)
        print("✅ 所有测试通过！")
        print("=" * 60)
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        if test_session_id:
            try:
                await manager.delete_session(test_session_id)
                print(f"  (已清理测试会话: {test_session_id})")
            except Exception:
                pass

if __name__ == "__main__":
    import asyncio
    asyncio.run(_run_tests())
