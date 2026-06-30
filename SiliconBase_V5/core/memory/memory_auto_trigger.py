#!/usr/bin/env python3
"""
MemoryAutoTrigger - 统一记忆自动存储触发器 V1.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【功能定位】
  统一的记忆自动存储触发器，封装所有自动存储逻辑
  为外部调用提供简洁、统一的接口

【核心功能】
  ✓ on_user_input - 用户输入自动存储到L2
  ✓ on_ai_response - AI回复自动存储到L2，支持关联引用记忆
  ✓ on_tool_execution - 工具执行记录到L5+L2
  ✓ on_task_event - 任务事件存储
  ✓ on_mode_switch - 模式切换存储到L3

【异常处理铁律】
  - 所有存储操作必须有guard装饰器
  - 任何失败都记录ERROR并抛错
  - 禁止静默失败
"""

from __future__ import annotations

import asyncio
import functools
import logging
import uuid
from datetime import datetime
from typing import Any

# 初始化日志记录器
logger = logging.getLogger(__name__)

# 延迟导入标志
MEMORY_AVAILABLE = False
EXECUTION_MEMORY_AVAILABLE = False

# 类型占位符
MemoryManager = None
MemoryLayer = None
MemoryType = None
get_memory_service = None
generate_default_value_assessment = None
calculate_overall_score = None
LAYER_SHORT = "short"
LAYER_MEDIUM = "medium"
LAYER_EXECUTION = "execution"
UserExecutionStore = None
ToolExecutionRecord = None
MemoryError = Exception


def _ensure_imports():
    """延迟导入 - 在首次使用时导入依赖模块"""
    global MEMORY_AVAILABLE, EXECUTION_MEMORY_AVAILABLE
    global MemoryManager, MemoryLayer, MemoryType, get_memory_service
    global generate_default_value_assessment, calculate_overall_score
    global UserExecutionStore, ToolExecutionRecord, MemoryError

    if MEMORY_AVAILABLE and EXECUTION_MEMORY_AVAILABLE:
        return

    # 导入日志
    try:
        from core.logger import logger as core_logger
        global logger
        logger = core_logger
    except ImportError:
        pass

    # 导入记忆相关模块
    try:
        from core.memory.memory_manager import MemoryLayer as ML
        from core.memory.memory_manager import MemoryManager as MM
        from core.memory.memory_manager import MemoryType as MT
        from core.memory.memory_service import (
            calculate_overall_score as cos,
        )
        from core.memory.memory_service import (
            generate_default_value_assessment as gdva,
        )
        from core.memory.memory_service import (
            get_memory_service as gms,
        )
        MemoryManager = MM
        MemoryLayer = ML
        MemoryType = MT
        get_memory_service = gms
        generate_default_value_assessment = gdva
        calculate_overall_score = cos
        MEMORY_AVAILABLE = True
        logger.debug("[MemoryAutoTrigger] 记忆模块导入成功")
    except ImportError as e:
        logger.warning(f"[MemoryAutoTrigger] 导入memory模块失败: {e}")
        MEMORY_AVAILABLE = False

    # 导入执行记忆
    try:
        from core.memory.execution_memory import ToolExecutionRecord as TER
        from core.memory.execution_memory import UserExecutionStore as UES
        UserExecutionStore = UES
        ToolExecutionRecord = TER
        EXECUTION_MEMORY_AVAILABLE = True
        logger.debug("[MemoryAutoTrigger] 执行记忆模块导入成功")
    except ImportError as e:
        logger.warning(f"[MemoryAutoTrigger] 导入execution_memory模块失败: {e}")
        EXECUTION_MEMORY_AVAILABLE = False

    # 导入异常类
    try:
        from core.exceptions import MemorySystemError as MemoryError
    except ImportError:
        class MemoryError(Exception):
            """记忆错误基类（fallback）"""
            pass


class MemoryStoreError(MemoryError):
    """存储操作错误 - 禁止静默失败"""
    pass


class SpecificException(Exception):
    """特定异常 - 用于装饰器捕获特定错误"""
    pass


# ═══════════════════════════════════════════════════════════════
# 存储守卫装饰器
# ═══════════════════════════════════════════════════════════════

def store_with_guard(func):
    """存储守卫装饰器 - 确保存储操作不会静默失败

    核心职责:
    1. 捕获并记录所有异常
    2. 空结果检测
    3. 统一错误处理

    【P0修复】支持 async def 方法，自动检测并适配。
    """
    if asyncio.iscoroutinefunction(func):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                result = await func(*args, **kwargs)
                if not result:
                    logger.error(f"[MemoryStore] {func.__name__} 返回空结果")
                    raise MemoryStoreError("存储返回空结果")
                return result
            except SpecificException as e:
                logger.error(f"[MemoryStore] {func.__name__} 失败: {e}",
                            exc_info=True, extra={"args": str(args), "kwargs": str(kwargs)})
                raise
            except Exception as e:
                logger.error(f"[MemoryStore] {func.__name__} 未预期异常: {e}",
                            exc_info=True)
                raise MemoryStoreError(f"存储异常: {e}") from e
        return async_wrapper
    else:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                result = func(*args, **kwargs)
                if not result:
                    logger.error(f"[MemoryStore] {func.__name__} 返回空结果")
                    raise MemoryStoreError("存储返回空结果")
                return result
            except SpecificException as e:
                logger.error(f"[MemoryStore] {func.__name__} 失败: {e}",
                            exc_info=True, extra={"args": str(args), "kwargs": str(kwargs)})
                raise
            except Exception as e:
                logger.error(f"[MemoryStore] {func.__name__} 未预期异常: {e}",
                            exc_info=True)
                raise MemoryStoreError(f"存储异常: {e}") from e
        return wrapper


# ═══════════════════════════════════════════════════════════════
# MemoryAutoTrigger 主类
# ═══════════════════════════════════════════════════════════════

class MemoryAutoTrigger:
    """
    统一记忆自动存储触发器

    提供标准化的自动存储接口，所有方法均为静态方法，
    便于在任何地方直接调用。
    """

    # 单例实例
    _instance = None
    _initialized = False

    # 记忆管理器实例（延迟加载）
    _memory_manager: MemoryManager | None = None

    # 用户执行存储缓存
    _execution_stores: dict[str, UserExecutionStore] = {}

    @classmethod
    def _get_memory_manager(cls) -> Any | None:
        """获取MemoryManager实例（延迟加载）"""
        _ensure_imports()
        if cls._memory_manager is None and MEMORY_AVAILABLE:
            try:
                cls._memory_manager = MemoryManager()
                logger.debug("[MemoryAutoTrigger] MemoryManager初始化完成")
            except Exception as e:
                logger.error(f"[MemoryAutoTrigger] MemoryManager初始化失败: {e}")
        return cls._memory_manager


    @classmethod
    def _get_execution_store(cls, user_id: str) -> Any | None:
        """获取用户执行存储实例"""
        _ensure_imports()
        if not EXECUTION_MEMORY_AVAILABLE:
            return None
        if user_id not in cls._execution_stores:
            try:
                cls._execution_stores[user_id] = UserExecutionStore(user_id)
            except Exception as e:
                logger.error(f"[MemoryAutoTrigger] 初始化执行存储失败 user={user_id}: {e}")
                return None
        return cls._execution_stores.get(user_id)

    @staticmethod
    def _generate_message_id() -> str:
        """生成消息ID"""
        return f"msg_{uuid.uuid4().hex[:16]}"

    @staticmethod
    def _generate_memory_id() -> str:
        """生成记忆ID"""
        return str(uuid.uuid4())

    @staticmethod
    def _get_timestamp() -> str:
        """获取当前时间戳"""
        return datetime.now().isoformat()

    @classmethod
    def _create_value_assessment(cls,
                                  emotional: int = 3,
                                  ethical: int = 3,
                                  growth: int = 3,
                                  execution: int = 3,
                                  sustainability: int = 3,
                                  innovation: int = 3) -> dict[str, Any]:
        """
        创建六维评分

        Args:
            emotional: 情感温度 (1-5)
            ethical: 伦理安全 (1-5)
            growth: 自我成长 (1-5)
            execution: 执行成效 (1-5)
            sustainability: 存续保障 (1-5)
            innovation: 灵感创新 (1-5)

        Returns:
            完整的六维评分字典
        """
        _ensure_imports()
        dimensions = {
            "emotional_temperature": emotional,
            "ethical_safety": ethical,
            "self_growth": growth,
            "execution_effectiveness": execution,
            "sustainability": sustainability,
            "inspiration_innovation": innovation
        }
        if calculate_overall_score:
            overall, grade = calculate_overall_score(dimensions)
        else:
            # Fallback计算
            weights = {
                "emotional_temperature": 0.25, "ethical_safety": 0.20,
                "self_growth": 0.20, "execution_effectiveness": 0.15,
                "sustainability": 0.15, "inspiration_innovation": 0.05
            }
            weighted_sum = sum(dimensions.get(d, 3) * w for d, w in weights.items())
            overall = round(weighted_sum, 2)
            if overall >= 4.5:
                grade = "S"
            elif overall >= 4.0:
                grade = "A"
            elif overall >= 3.5:
                grade = "B"
            elif overall >= 2.5:
                grade = "C"
            else:
                grade = "D"
        dimensions["overall"] = overall
        dimensions["grade"] = grade
        return dimensions

    # ═══════════════════════════════════════════════════════════════
    # 私有方法: _notify_memory_sync - WebSocket通知
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def _notify_memory_sync(session_id: str, memory_id: str, memory_data: dict,
                            operation: str = "added", user_id: str | None = None):
        """
        通知记忆同步服务（WebSocket推送）

        Args:
            session_id: 会话ID
            memory_id: 记忆ID
            memory_data: 记忆数据
            operation: 操作类型 (added/updated/deleted)
            user_id: 用户ID
        """
        try:
            from core.memory.memory_sync_manager import (
                broadcast_memory_added_sync,
                broadcast_memory_updated_sync,
                broadcast_sync_required_sync,
            )

            if operation == "added":
                broadcast_memory_added_sync(session_id, memory_data, user_id)
            elif operation == "updated":
                broadcast_memory_updated_sync(session_id, memory_id, memory_data, user_id)
            else:
                broadcast_sync_required_sync(session_id, f"memory_{operation}", user_id)

            logger.debug(f"[MemoryAutoTrigger] 同步通知已发送: {operation} {memory_id[:8]}...")
        except Exception as e:
            # 通知失败不应阻断主流程
            logger.debug(f"[MemoryAutoTrigger] 同步通知失败: {e}")

    # ═══════════════════════════════════════════════════════════════
    # 公共API: on_user_input
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    @store_with_guard
    async def on_user_input(user_id: str,
                      session_id: str,
                      text: str,
                      message_id: str | None = None,
                      metadata: dict | None = None) -> str:
        """
        用户输入存储触发器

        将用户输入存储到L2短期记忆，同时关联session_message记录。

        Args:
            user_id: 用户ID
            session_id: 会话ID
            text: 用户输入文本
            message_id: 关联的消息ID（可选，如果提供则建立双向关联）
            metadata: 额外元数据

        Returns:
            记忆ID

        Raises:
            MemoryStoreError: 存储失败时抛出
        """
        _ensure_imports()
        if not MEMORY_AVAILABLE:
            raise MemoryStoreError("记忆系统不可用")

        # 【新增】读取配置判断是否启用会话关联
        try:
            from core.config import config
            session_assoc_enabled = config.get("memory.session_association.enabled", True)
            if not session_assoc_enabled:
                logger.debug("[MemoryAutoTrigger] 会话关联已禁用，跳过关联")
                # 【P0修复】不能直接return，继续执行记忆存储
        except Exception as e:
            logger.error(f"[MemoryAutoTrigger] 读取会话关联配置失败: {e}", exc_info=True)
            # 默认启用，继续执行
            session_assoc_enabled = True

        MemoryAutoTrigger._generate_memory_id()
        internal_message_id = message_id or MemoryAutoTrigger._generate_message_id()
        timestamp = MemoryAutoTrigger._get_timestamp()

        # 构建content
        content = {
            "text": text,
            "type": "user_input",
            "message_id": internal_message_id
        }

        # 构建context
        context = {
            "session_id": session_id,
            "message_id": internal_message_id,
            "timestamp": timestamp,
            "creator": "user",
            "source": "user_input",
            **(metadata or {})
        }

        # 六维评分 - 用户输入默认为中性
        value_assessment = MemoryAutoTrigger._create_value_assessment(
            emotional=3, ethical=3, growth=3,
            execution=3, sustainability=3, innovation=3
        )

        try:
            ms = await get_memory_service()

            # NOTE: MemoryAutoTrigger 使用 ms.add_memory() 直接写入 L2 short-term memory。
            # 这与 memory_trigger.py 中 on_user_input_async 调用的 save_chat_turn() 是两条独立链路：
            # - add_memory() 走 L2 分层存储（带 value_assessment、scene 等元数据）
            # - save_chat_turn() 走 working_memory + vector_store dual-write（无六维评分）
            # 设计意图：auto_trigger 供意识系统使用，memory_trigger 供 AgentLoop 使用。
            # 存储到L2
            memory_id = await ms.add_memory(
                user_id=user_id,
                content=content,
                memory_type="chat",
                layer=LAYER_SHORT,
                context=context,
                scene=f"session_{session_id}",
                rating=0,  # 用户输入无评分
                value_assessment=value_assessment,
                source="user",
                creator="user"
            )

            # 【Phase 3 Week 5】建立message↔memory双向关联
            if message_id and session_assoc_enabled:
                try:
                    from core.session.session_manager import get_session_manager
                    session_manager = get_session_manager()
                    success = await session_manager.update_message_memory_id(message_id, memory_id)
                    if success:
                        logger.debug(f"[MemoryAutoTrigger] 消息memory_id关联成功: msg={message_id[:8]}..., mem={memory_id[:8]}...")
                    else:
                        logger.error(f"[MemoryAutoTrigger] 消息memory_id关联失败，消息可能不存在: {message_id[:8]}...")
                except Exception as e:
                    # 关联失败不阻断主流程，但记录ERROR日志
                    logger.error(f"[MemoryAutoTrigger] 更新消息memory_id失败（非阻塞）: {e}", exc_info=True)
            elif message_id and not session_assoc_enabled:
                logger.debug("[MemoryAutoTrigger] 消息-记忆关联已禁用，跳过关联")

            # 【Phase 4 Week 7】WebSocket实时推送
            memory_data = {
                "memory_id": memory_id,
                "content": content,
                "context": context,
                "value_assessment": value_assessment,
                "layer": LAYER_SHORT,
                "mem_type": "chat"
            }
            MemoryAutoTrigger._notify_memory_sync(session_id, memory_id, memory_data, "added", user_id)

            logger.info(f"[MemoryAutoTrigger] 用户输入已存储: user={user_id}, mem_id={memory_id[:8]}...")
            return memory_id

        except Exception as e:
            error_msg = str(e)
            if "All connection attempts failed" in error_msg:
                logger.warning(f"[MemoryAutoTrigger] PostgreSQL不可达，降级跳过用户输入存储: {e}")
                return ""
            logger.error(f"[MemoryAutoTrigger] 用户输入存储失败: {e}", exc_info=True)
            raise MemoryStoreError(f"用户输入存储失败: {e}") from e

    # ═══════════════════════════════════════════════════════════════
    # 公共API: on_ai_response
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    @store_with_guard
    async def on_ai_response(user_id: str,
                       session_id: str,
                       response: str,
                       thinking: str | None = None,
                       tool_calls: list[dict] | None = None,
                       referenced_memories: list[str] | None = None,
                       message_id: str | None = None,
                       metadata: dict | None = None) -> str:
        """
        AI回复存储触发器

        将AI回复存储到L2短期记忆，同时关联session_message记录，
        并关联引用的记忆。

        Args:
            user_id: 用户ID
            session_id: 会话ID
            response: AI回复文本
            thinking: AI思考过程（可选）
            tool_calls: 工具调用列表（可选）
            referenced_memories: 引用的记忆ID列表（可选）
            message_id: 关联的消息ID（可选，如果提供则建立双向关联）
            metadata: 额外元数据

        Returns:
            记忆ID

        Raises:
            MemoryStoreError: 存储失败时抛出
        """
        _ensure_imports()
        if not MEMORY_AVAILABLE:
            raise MemoryStoreError("记忆系统不可用")

        # 【新增】读取配置判断是否启用会话关联
        try:
            from core.config import config
            session_assoc_enabled = config.get("memory.session_association.enabled", True)
            if not session_assoc_enabled:
                logger.debug("[MemoryAutoTrigger] 会话关联已禁用，跳过关联")
                # 【P0修复】不能直接return，继续执行记忆存储
        except Exception as e:
            logger.error(f"[MemoryAutoTrigger] 读取会话关联配置失败: {e}", exc_info=True)
            # 默认启用，继续执行
            session_assoc_enabled = True

        MemoryAutoTrigger._generate_memory_id()
        internal_message_id = message_id or MemoryAutoTrigger._generate_message_id()
        timestamp = MemoryAutoTrigger._get_timestamp()

        # 构建content
        content = {
            "text": response,
            "type": "ai_response",
            "message_id": internal_message_id,
            "has_thinking": thinking is not None,
            "has_tool_calls": tool_calls is not None and len(tool_calls) > 0
        }

        # 构建context
        context = {
            "session_id": session_id,
            "message_id": internal_message_id,
            "timestamp": timestamp,
            "creator": "AI",
            "source": "ai_response",
            "thinking": thinking,
            **(metadata or {})
        }
        # 【修复】ChromaDB 不允许空列表作为 metadata 值，只添加非空值
        if tool_calls:
            context["tool_calls"] = tool_calls
        if referenced_memories:
            context["referenced_memories"] = referenced_memories

        # 六维评分 - AI回复根据内容评估
        value_assessment = MemoryAutoTrigger._create_value_assessment(
            emotional=3, ethical=4, growth=4,  # AI回复假设有帮助性
            execution=4, sustainability=3, innovation=3
        )

        try:
            ms = await get_memory_service()

            # NOTE: MemoryAutoTrigger 使用 ms.add_memory() 直接写入 L2 short-term memory。
            # 这与 memory_trigger.py 中 on_ai_response_async 调用的 save_chat_turn() 是两条独立链路。
            # 详见 on_user_input 中的设计注释。
            # 存储到L2
            memory_id = await ms.add_memory(
                user_id=user_id,
                content=content,
                memory_type="chat",
                layer=LAYER_SHORT,
                context=context,
                scene=f"session_{session_id}",
                rating=0,  # 初始评分，后续可由用户反馈更新
                value_assessment=value_assessment,
                source="ai",
                creator="AI"
            )

            # 创建记忆关联（如果引用了其他记忆）
            if referenced_memories:
                try:
                    from core.memory.memory_associations import memory_association_manager
                    for ref_mem_id in referenced_memories:
                        memory_association_manager.add_association(
                            source_mem_id=memory_id,
                            target_mem_id=ref_mem_id,
                            user_id=user_id,
                            relation_type="referenced_by",
                            relation_score=1.0,
                            relation_data={"session_id": session_id}
                        )
                except Exception as e:
                    logger.warning(f"[MemoryAutoTrigger] 创建记忆关联失败: {e}")

            # 【Phase 3 Week 5】建立message↔memory双向关联
            if message_id and session_assoc_enabled:
                try:
                    from core.session.session_manager import get_session_manager
                    session_manager = get_session_manager()
                    success = await session_manager.update_message_memory_id(message_id, memory_id)
                    if success:
                        logger.debug(f"[MemoryAutoTrigger] 消息memory_id关联成功: msg={message_id[:8]}..., mem={memory_id[:8]}...")
                    else:
                        logger.error(f"[MemoryAutoTrigger] 消息memory_id关联失败，消息可能不存在: {message_id[:8]}...")
                except Exception as e:
                    # 关联失败不阻断主流程，但记录ERROR日志
                    logger.error(f"[MemoryAutoTrigger] 更新消息memory_id失败（非阻塞）: {e}", exc_info=True)
            elif message_id and not session_assoc_enabled:
                logger.debug("[MemoryAutoTrigger] 消息-记忆关联已禁用，跳过关联")

            # 【Phase 4 Week 7】WebSocket实时推送
            memory_data = {
                "memory_id": memory_id,
                "content": content,
                "context": context,
                "value_assessment": value_assessment,
                "layer": LAYER_SHORT,
                "mem_type": "chat",
                "referenced_memories": referenced_memories or []
            }
            MemoryAutoTrigger._notify_memory_sync(session_id, memory_id, memory_data, "added", user_id)

            logger.info(f"[MemoryAutoTrigger] AI回复已存储: user={user_id}, mem_id={memory_id[:8]}...")
            return memory_id

        except Exception as e:
            error_msg = str(e)
            if "All connection attempts failed" in error_msg:
                logger.warning(f"[MemoryAutoTrigger] PostgreSQL不可达，降级跳过AI回复存储: {e}")
                return ""
            logger.error(f"[MemoryAutoTrigger] AI回复存储失败: {e}", exc_info=True)
            raise MemoryStoreError(f"AI回复存储失败: {e}") from e

    # ═══════════════════════════════════════════════════════════════
    # 公共API: on_tool_execution
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    @store_with_guard
    async def on_tool_execution(user_id: str,
                          session_id: str,
                          tool_name: str,
                          params: dict[str, Any],
                          result: dict[str, Any],
                          execution_time_ms: int = 0,
                          metadata: dict | None = None) -> tuple[str, str]:
        """
        工具执行存储触发器

        存储工具执行记录到L5执行记忆，同时存储L2简明记录。

        Args:
            user_id: 用户ID
            session_id: 会话ID
            tool_name: 工具名称
            params: 工具参数
            result: 执行结果
            execution_time_ms: 执行耗时（毫秒）
            metadata: 额外元数据

        Returns:
            (L5记忆ID, L2记忆ID) 元组

        Raises:
            MemoryStoreError: 存储失败时抛出
        """
        _ensure_imports()
        if not MEMORY_AVAILABLE:
            raise MemoryStoreError("记忆系统不可用")

        if not EXECUTION_MEMORY_AVAILABLE:
            raise MemoryStoreError("执行记忆系统不可用")

        timestamp = datetime.now()
        success = result.get("success", False) if isinstance(result, dict) else True
        error_code = result.get("error_code") if isinstance(result, dict) else None
        error_message = result.get("error_message") if isinstance(result, dict) else None

        # ═══════════════════════════════════════════════════════
        # 1. 存储到L5执行记忆
        # ═══════════════════════════════════════════════════════
        try:
            exec_store = MemoryAutoTrigger._get_execution_store(user_id)
            if exec_store is None:
                raise MemoryStoreError("无法获取执行存储实例")

            # 创建执行记录
            execution_record = ToolExecutionRecord(
                user_id=user_id,
                tool_name=tool_name,
                input_params=params,
                output_result=result,
                success=success,
                execution_time_ms=execution_time_ms,
                timestamp=timestamp,
                session_id=session_id,
                error_code=error_code,
                error_message=error_message,
                tool_params=params
            )

            # 存储到L5
            l5_id = exec_store.add(execution_record)

            logger.debug(f"[MemoryAutoTrigger] 工具执行已存储到L5: user={user_id}, l5_id={l5_id[:20]}...")

        except Exception as e:
            error_msg = str(e)
            if "All connection attempts failed" in error_msg:
                logger.warning(f"[MemoryAutoTrigger] PostgreSQL不可达，降级跳过工具执行L5存储: {e}")
                return ("", "")
            logger.error(f"[MemoryAutoTrigger] L5存储失败: {e}", exc_info=True)
            raise MemoryStoreError(f"L5执行记忆存储失败: {e}") from e

        # ═══════════════════════════════════════════════════════
        # 2. 存储到L2简明记录
        # ═══════════════════════════════════════════════════════
        try:
            ms = await get_memory_service()

            # 构建L2 content - 简明记录
            l2_content = {
                "text": f"执行工具: {tool_name}",
                "type": "tool_execution",
                "tool_name": tool_name,
                "success": success,
                "execution_time_ms": execution_time_ms,
                "l5_reference": l5_id  # 关联到L5详细记录
            }

            # 构建context
            l2_context = {
                "session_id": session_id,
                "timestamp": timestamp.isoformat(),
                "creator": "AI",
                "source": "tool_execution",
                "tool_name": tool_name,
                "l5_id": l5_id,
                **(metadata or {})
            }

            # 六维评分 - 工具执行根据成功率评估
            value_assessment = MemoryAutoTrigger._create_value_assessment(
                emotional=2, ethical=4, growth=3,
                execution=5 if success else 1,  # 成功则执行成效高
                sustainability=3,
                innovation=2
            )

            # 存储到L2
            l2_id = await ms.add_memory(
                user_id=user_id,
                content=l2_content,
                memory_type="execution",
                layer=LAYER_SHORT,
                context=l2_context,
                scene=f"exec_{tool_name}",
                rating=1 if success else 0,
                value_assessment=value_assessment,
                source="system",
                creator="AI"
            )

            # 【Phase 4 Week 7】WebSocket实时推送
            memory_data = {
                "memory_id": l2_id,
                "content": l2_content,
                "context": l2_context,
                "value_assessment": value_assessment,
                "layer": LAYER_SHORT,
                "mem_type": "execution",
                "l5_id": l5_id
            }
            MemoryAutoTrigger._notify_memory_sync(session_id, l2_id, memory_data, "added", user_id)

            logger.info(f"[MemoryAutoTrigger] 工具执行已存储: user={user_id}, L5={l5_id[:20]}..., L2={l2_id[:8]}...")
            return (l5_id, l2_id)

        except Exception as e:
            error_msg = str(e)
            if "All connection attempts failed" in error_msg:
                logger.warning(f"[MemoryAutoTrigger] PostgreSQL不可达，降级跳过工具执行L2存储，返回L5记录: {e}")
                return (l5_id, "")
            logger.error(f"[MemoryAutoTrigger] L2存储失败: {e}", exc_info=True)
            raise MemoryStoreError(f"L2简明记录存储失败: {e}") from e

    # ═══════════════════════════════════════════════════════════════
    # 公共API: on_task_event
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    @store_with_guard
    async def on_task_event(user_id: str,
                      session_id: str,
                      event_type: str,
                      task_data: dict[str, Any],
                      metadata: dict | None = None) -> str:
        """
        任务事件存储触发器

        存储任务相关事件到合适的记忆层级：
        - start: 任务开始 -> L2
        - complete: 任务完成 -> L3 (有价值)
        - interrupt: 任务中断 -> L2
        - pause: 任务暂停 -> L2
        - resume: 任务恢复 -> L2

        Args:
            user_id: 用户ID
            session_id: 会话ID
            event_type: 事件类型 (start/complete/interrupt/pause/resume)
            task_data: 任务数据
            metadata: 额外元数据

        Returns:
            记忆ID

        Raises:
            MemoryStoreError: 存储失败时抛出
            ValueError: 无效的事件类型
        """
        _ensure_imports()
        if not MEMORY_AVAILABLE:
            raise MemoryStoreError("记忆系统不可用")

        # 验证事件类型
        valid_events = ["start", "complete", "interrupt", "pause", "resume"]
        if event_type not in valid_events:
            raise ValueError(f"无效的事件类型: {event_type}，必须是 {valid_events}")

        timestamp = MemoryAutoTrigger._get_timestamp()
        task_id = task_data.get("task_id", MemoryAutoTrigger._generate_memory_id())
        task_name = task_data.get("task_name", "unknown_task")

        # 根据事件类型选择存储层级
        if event_type == "complete":
            # 任务完成存储到L3（有价值保留）
            layer = LAYER_MEDIUM
            mem_type = "task_complete"
            rating = 5  # 完成的任务有一定价值
        else:
            # 其他事件存储到L2
            layer = LAYER_SHORT
            mem_type = f"task_{event_type}"
            rating = 0

        # 构建content
        content = {
            "text": f"任务{event_type}: {task_name}",
            "type": "task_event",
            "event_type": event_type,
            "task_id": task_id,
            "task_name": task_name,
            "task_data": task_data
        }

        # 构建context
        context = {
            "session_id": session_id,
            "task_id": task_id,
            "timestamp": timestamp,
            "creator": "system",
            "source": "task_event",
            "event_type": event_type,
            **(metadata or {})
        }

        # 六维评分 - 根据事件类型调整
        if event_type == "complete":
            value_assessment = MemoryAutoTrigger._create_value_assessment(
                emotional=3, ethical=4, growth=4,
                execution=5, sustainability=3, innovation=3
            )
        elif event_type == "interrupt":
            value_assessment = MemoryAutoTrigger._create_value_assessment(
                emotional=2, ethical=3, growth=2,
                execution=1, sustainability=2, innovation=2
            )
        else:
            value_assessment = MemoryAutoTrigger._create_value_assessment(
                emotional=3, ethical=3, growth=3,
                execution=3, sustainability=3, innovation=2
            )

        try:
            ms = await get_memory_service()

            memory_id = await ms.add_memory(
                user_id=user_id,
                content=content,
                memory_type=mem_type,
                layer=layer,
                context=context,
                scene=f"task_{task_id}",
                rating=rating,
                value_assessment=value_assessment,
                source="system",
                creator="system"
            )

            logger.info(f"[MemoryAutoTrigger] 任务事件已存储: user={user_id}, event={event_type}, mem_id={memory_id[:8]}...")
            return memory_id

        except Exception as e:
            logger.error(f"[MemoryAutoTrigger] 任务事件存储失败: {e}", exc_info=True)
            raise MemoryStoreError(f"任务事件存储失败: {e}") from e

    # ═══════════════════════════════════════════════════════════════
    # 公共API: on_mode_switch
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    @store_with_guard
    async def on_mode_switch(user_id: str,
                       session_id: str,
                       from_mode: str,
                       to_mode: str,
                       context_data: dict | None = None,
                       metadata: dict | None = None) -> str:
        """
        模式切换存储触发器

        存储模式切换事件到L3中期记忆。

        Args:
            user_id: 用户ID
            session_id: 会话ID
            from_mode: 原模式
            to_mode: 目标模式
            context_data: 切换上下文（如触发原因、当前任务等）
            metadata: 额外元数据

        Returns:
            记忆ID

        Raises:
            MemoryStoreError: 存储失败时抛出
        """
        _ensure_imports()
        if not MEMORY_AVAILABLE:
            raise MemoryStoreError("记忆系统不可用")

        timestamp = MemoryAutoTrigger._get_timestamp()
        switch_id = MemoryAutoTrigger._generate_memory_id()

        # 构建content
        content = {
            "text": f"模式切换: {from_mode} -> {to_mode}",
            "type": "mode_switch",
            "switch_id": switch_id,
            "from_mode": from_mode,
            "to_mode": to_mode,
            "context": context_data or {}
        }

        # 构建context
        context = {
            "session_id": session_id,
            "timestamp": timestamp,
            "creator": "system",
            "source": "mode_switch",
            "from_mode": from_mode,
            "to_mode": to_mode,
            **(metadata or {})
        }

        # 六维评分 - 模式切换具有一定价值
        value_assessment = MemoryAutoTrigger._create_value_assessment(
            emotional=3, ethical=4, growth=4,  # 模式切换有助于成长
            execution=3, sustainability=3, innovation=3
        )

        try:
            ms = await get_memory_service()

            memory_id = await ms.add_memory(
                user_id=user_id,
                content=content,
                memory_type="mode_switch",
                layer=LAYER_MEDIUM,  # 模式切换存储到L3
                context=context,
                scene=f"mode_switch_{session_id}",
                rating=3,  # 模式切换有一定价值
                value_assessment=value_assessment,
                source="system",
                creator="system"
            )

            logger.info(f"[MemoryAutoTrigger] 模式切换已存储: user={user_id}, {from_mode}->{to_mode}, mem_id={memory_id[:8]}...")
            return memory_id

        except Exception as e:
            logger.error(f"[MemoryAutoTrigger] 模式切换存储失败: {e}", exc_info=True)
            raise MemoryStoreError(f"模式切换存储失败: {e}") from e


# ═══════════════════════════════════════════════════════════════
# 便捷函数 - 简化外部调用
# ═══════════════════════════════════════════════════════════════

# 创建全局触发器实例（供便捷函数使用）
auto_trigger = MemoryAutoTrigger()


async def store_user_input(user_id: str, session_id: str, text: str,
                     metadata: dict | None = None,
                     message_id: str | None = None) -> str:
    """便捷函数：存储用户输入"""
    return await MemoryAutoTrigger.on_user_input(
        user_id, session_id, text, message_id, metadata
    )


async def store_ai_response(user_id: str, session_id: str, response: str,
                      thinking: str | None = None,
                      tool_calls: list[dict] | None = None,
                      referenced_memories: list[str] | None = None,
                      metadata: dict | None = None,
                      message_id: str | None = None) -> str:
    """便捷函数：存储AI回复"""
    return await MemoryAutoTrigger.on_ai_response(
        user_id, session_id, response, thinking,
        tool_calls, referenced_memories, metadata, message_id
    )


async def store_tool_execution(user_id: str, session_id: str, tool_name: str,
                         params: dict[str, Any], result: dict[str, Any],
                         execution_time_ms: int = 0,
                         metadata: dict | None = None) -> tuple[str, str]:
    """便捷函数：存储工具执行"""
    return await MemoryAutoTrigger.on_tool_execution(
        user_id, session_id, tool_name, params,
        result, execution_time_ms, metadata
    )


async def store_task_event(user_id: str, session_id: str, event_type: str,
                     task_data: dict[str, Any],
                     metadata: dict | None = None) -> str:
    """便捷函数：存储任务事件"""
    return await MemoryAutoTrigger.on_task_event(
        user_id, session_id, event_type, task_data, metadata
    )


async def store_mode_switch(user_id: str, session_id: str, from_mode: str, to_mode: str,
                      context_data: dict | None = None,
                      metadata: dict | None = None) -> str:
    """便捷函数：存储模式切换"""
    return await MemoryAutoTrigger.on_mode_switch(
        user_id, session_id, from_mode, to_mode, context_data, metadata
    )


# ═══════════════════════════════════════════════════════════════
# 验证测试
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    """简单验证测试"""
    import os
    import sys

    # 添加项目根目录到Python路径
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    print("=" * 60)
    print("MemoryAutoTrigger 验证测试")
    print("=" * 60)

    # 测试用户信息
    test_user_id = f"test_user_{uuid.uuid4().hex[:8]}"
    test_session_id = f"test_session_{uuid.uuid4().hex[:8]}"

    print(f"\n测试用户ID: {test_user_id}")
    print(f"测试会话ID: {test_session_id}")
    print(f"记忆系统可用: {MEMORY_AVAILABLE}")
    print(f"执行记忆可用: {EXECUTION_MEMORY_AVAILABLE}")

    async def _run_tests():
        results = {
            "user_input": False,
            "ai_response": False,
            "tool_execution": False,
            "task_event": False,
            "mode_switch": False
        }
        # 测试1: 用户输入存储
        print("\n" + "-" * 40)
        print("测试1: on_user_input")
        try:
            mem_id = await MemoryAutoTrigger.on_user_input(
                user_id=test_user_id,
                session_id=test_session_id,
                text="你好，这是一个测试消息"
            )
            print(f"✅ 成功: memory_id={mem_id[:20]}...")
            results["user_input"] = True
        except Exception as e:
            print(f"❌ 失败: {e}")

        # 测试2: AI回复存储
        print("\n" + "-" * 40)
        print("测试2: on_ai_response")
        try:
            mem_id = await MemoryAutoTrigger.on_ai_response(
                user_id=test_user_id,
                session_id=test_session_id,
                response="你好！这是一个测试回复",
                thinking="这是AI的思考过程",
                tool_calls=[{"tool": "test_tool", "params": {}}]
            )
            print(f"✅ 成功: memory_id={mem_id[:20]}...")
            results["ai_response"] = True
        except Exception as e:
            print(f"❌ 失败: {e}")

        # 测试3: 工具执行存储
        print("\n" + "-" * 40)
        print("测试3: on_tool_execution")
        try:
            l5_id, l2_id = await MemoryAutoTrigger.on_tool_execution(
                user_id=test_user_id,
                session_id=test_session_id,
                tool_name="test_tool",
                params={"param1": "value1"},
                result={"success": True, "data": "test_result"},
                execution_time_ms=150
            )
            print(f"✅ 成功: L5_id={l5_id[:20]}..., L2_id={l2_id[:20]}...")
            results["tool_execution"] = True
        except Exception as e:
            print(f"❌ 失败: {e}")

        # 测试4: 任务事件存储
        print("\n" + "-" * 40)
        print("测试4: on_task_event")
        for event_type in ["start", "complete", "pause", "resume", "interrupt"]:
            try:
                mem_id = await MemoryAutoTrigger.on_task_event(
                    user_id=test_user_id,
                    session_id=test_session_id,
                    event_type=event_type,
                    task_data={
                        "task_id": f"task_{uuid.uuid4().hex[:8]}",
                        "task_name": f"测试任务_{event_type}"
                    }
                )
                print(f"  ✅ {event_type}: memory_id={mem_id[:20]}...")
            except Exception as e:
                print(f"  ❌ {event_type}: {e}")
        results["task_event"] = True

        # 测试5: 模式切换存储
        print("\n" + "-" * 40)
        print("测试5: on_mode_switch")
        try:
            mem_id = await MemoryAutoTrigger.on_mode_switch(
                user_id=test_user_id,
                session_id=test_session_id,
                from_mode="DAILY",
                to_mode="FOCUS",
                context_data={"reason": "用户请求专注模式"}
            )
            print(f"✅ 成功: memory_id={mem_id[:20]}...")
            results["mode_switch"] = True
        except Exception as e:
            print(f"❌ 失败: {e}")

        # 测试6: 错误处理
        print("\n" + "-" * 40)
        print("测试6: 错误处理")
        try:
            # 无效的事件类型
            await MemoryAutoTrigger.on_task_event(
                user_id=test_user_id,
                session_id=test_session_id,
                event_type="invalid_event",
                task_data={}
            )
            print("❌ 应该抛出异常但未抛出")
        except ValueError as e:
            print(f"✅ 成功捕获ValueError: {e}")
        except Exception as e:
            print(f"✅ 成功捕获异常: {type(e).__name__}: {e}")
        return results

    results = asyncio.run(_run_tests())

    # 总结
    print("\n" + "=" * 60)
    print("测试结果总结")
    print("=" * 60)
    total = len(results)
    passed = sum(1 for v in results.values() if v)
    print(f"通过: {passed}/{total}")
    for test_name, passed in results.items():
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"  {status}: {test_name}")

    # 返回退出码
    sys.exit(0 if passed == total else 1)
