#!/usr/bin/env python3
"""
MemoryTrigger - 记忆自动存储触发器 V1.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【核心职责】
  解决"该存但没存"的问题，建立自动、可靠的记忆存储触发机制

【设计原则】
  1. 不依赖AI自觉性 - 底座强制存储
  2. 不阻塞主流程 - 异步存储
  3. 不重复存储 - 防抖机制
  4. 不遗漏关键节点 - 钩子覆盖

【触发条件】
  - 用户每句话 → 自动存储到L1/L2
  - AI每轮回复 → 自动存储到L1/L2
  - 工具执行结果 → 自动存储到L5
  - 模式切换 → 存储上下文摘要

【架构设计】
  ┌─────────────────────────────────────────┐
  │           MemoryTrigger                 │
  │  ┌─────────┐ ┌─────────┐ ┌─────────┐   │
  │  │ User钩子 │ │ AI钩子  │ │ Tool钩子 │   │
  │  └────┬────┘ └────┬────┘ └────┬────┘   │
  │       └───────────┼───────────┘        │
  │                   ▼                     │
  │         ┌─────────────────┐             │
  │         │  DebounceQueue  │             │
  │         │   (防抖队列)     │             │
  │         └────────┬────────┘             │
  │                  ▼                      │
  │         ┌─────────────────┐             │
  │         │ AsyncMemoryStore│             │
  │         │  (异步存储引擎)  │             │
  │         └────────┬────────┘             │
  │                  ▼                      │
  │         ┌─────────────────┐             │
  │         │  MemoryManager  │             │
  │         │  (统一记忆管理)  │             │
  │         └─────────────────┘             │
  └─────────────────────────────────────────┘

【作者】Agent-Design: 记忆系统自动存储机制
【日期】2026-03-12
"""

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# 配置常量
# ═══════════════════════════════════════════════════════════════════

DEBOUNCE_INTERVAL = 2.0          # 防抖间隔（秒）
BATCH_SIZE = 10                  # 批量存储大小
BATCH_INTERVAL = 5.0             # 批量存储间隔（秒）
MAX_QUEUE_SIZE = 1000            # 最大队列大小
CONTENT_MAX_LENGTH = 5000        # 内容最大长度（截断）


class TriggerType(Enum):
    """触发类型枚举"""
    USER_INPUT = "user_input"          # 用户输入
    AI_RESPONSE = "ai_response"        # AI回复
    TOOL_EXECUTION = "tool_execution"  # 工具执行
    MODE_SWITCH = "mode_switch"        # 模式切换
    CONTEXT_SUMMARY = "context_summary" # 上下文摘要
    MANUAL = "manual"                  # 手动触发


class MemoryLevel(Enum):
    """记忆层级枚举（用于自动存储决策）"""
    L1_WORKING = "working"      # L1: 工作记忆（临时）
    L2_SHORT = "short"          # L2: 短期记忆（24小时）
    L3_MEDIUM = "medium"        # L3: 中期记忆（7天）
    L4_EVOLVE = "evolve"        # L4: 长期记忆（永久）
    L5_EXECUTION = "execution"  # L5: 执行记忆（工具记录）


@dataclass
class TriggerEvent:
    """触发事件数据类"""
    event_id: str
    trigger_type: TriggerType
    user_id: str
    session_id: str
    content: dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    priority: int = 0  # 优先级：0=普通，1=高，2=紧急

    def to_memory_record(self) -> dict[str, Any]:
        """转换为记忆记录格式"""
        return {
            "event_id": self.event_id,
            "trigger_type": self.trigger_type.value,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "content": self.content,
            "timestamp": self.timestamp
        }


@dataclass
class StorageConfig:
    """存储配置"""
    enable_user_input: bool = True      # 启用用户输入存储
    enable_ai_response: bool = True     # 启用AI回复存储
    enable_tool_result: bool = True     # 启用工具结果存储
    enable_mode_switch: bool = True     # 启用模式切换存储
    debounce_interval: float = DEBOUNCE_INTERVAL
    batch_size: int = BATCH_SIZE

    # 内容过滤配置
    min_content_length: int = 2         # 最小内容长度
    max_content_length: int = CONTENT_MAX_LENGTH
    filter_patterns: list[str] = field(default_factory=lambda: [
        "[思考]", "[系统]", "[调试]",  # 过滤系统内部标记
    ])


# ═══════════════════════════════════════════════════════════════════
# 防抖队列
# ═══════════════════════════════════════════════════════════════════

class DebounceQueue:
    """
    防抖队列 - 防止短时间内重复存储

    原理：
    - 相同session+type的内容在一定时间内只存储最新版本
    - 使用哈希去重，避免存储重复内容
    """

    def __init__(self, debounce_interval: float = DEBOUNCE_INTERVAL):
        self._debounce_interval = debounce_interval
        self._pending: dict[str, TriggerEvent] = {}
        self._last_hash: dict[str, str] = {}
        self._lock = threading.RLock()
        self._last_flush = time.time()

    def _make_key(self, event: TriggerEvent) -> str:
        """生成防抖键"""
        return f"{event.user_id}:{event.session_id}:{event.trigger_type.value}"

    def _make_hash(self, content: dict) -> str:
        """生成内容哈希（用于去重）"""
        # 简单哈希：取content的关键字段
        if isinstance(content, dict):
            key_fields = []
            for k in ['text', 'content', 'message', 'result', 'tool_name']:
                if k in content:
                    v = content[k]
                    if isinstance(v, str):
                        key_fields.append(v[:50])  # 取前50字符
                    elif isinstance(v, dict):
                        key_fields.append(json.dumps(v, sort_keys=True)[:50])
            return hash(tuple(key_fields)) % 10000000
        return hash(str(content)) % 10000000

    def add(self, event: TriggerEvent) -> bool:
        """
        添加事件到防抖队列（已废弃，保留结构避免破坏导入）

        Returns:
            bool: True表示新事件被接受
        """
        return True

    def put(self, event: TriggerEvent) -> None:
        """已废弃：同步路径不再执行记忆写入"""
        pass

    def flush(self) -> list[TriggerEvent]:
        """刷新队列，返回待处理事件（已废弃，保留结构避免破坏导入）"""
        return []

    def get_pending_count(self) -> int:
        """获取待处理事件数（已废弃，保留结构避免破坏导入）"""
        return 0


# ═══════════════════════════════════════════════════════════════════
# 内容格式化器
# ═══════════════════════════════════════════════════════════════════

class ContentFormatter:
    """
    内容格式化器 - 统一不同来源内容的存储格式
    """

    @staticmethod
    def format_user_input(text: str, metadata: dict = None) -> dict[str, Any]:
        """
        格式化用户输入

        存储格式：
        {
            "type": "user_input",
            "text": "用户原始输入",
            "intent": "意图分类",
            "entities": ["实体1", "实体2"],
            "timestamp": 1234567890
        }
        """
        return {
            "type": "user_input",
            "text": ContentFormatter._truncate(text),
            "intent": metadata.get("intent") if metadata else None,
            "entities": metadata.get("entities", []) if metadata else [],
            "metadata": metadata or {}
        }

    @staticmethod
    def format_ai_response(text: str, metadata: dict = None) -> dict[str, Any]:
        """
        格式化AI回复

        存储格式：
        {
            "type": "ai_response",
            "text": "AI回复内容",
            "thinking": "思考过程（如果有）",
            "action": "执行的动作",
            "reply_to_user": "给用户的回复",
            "timestamp": 1234567890
        }
        """
        # 尝试提取结构化内容
        thinking = ""
        action = ""
        reply = text

        if metadata:
            thinking = metadata.get("thinking", "")
            action = metadata.get("action", "")
            reply = metadata.get("reply_to_user", text)

        return {
            "type": "ai_response",
            "text": ContentFormatter._truncate(text),
            "thinking": ContentFormatter._truncate(thinking, 1000),
            "action": action,
            "reply_to_user": ContentFormatter._truncate(reply),
            "metadata": metadata or {}
        }

    @staticmethod
    def format_tool_result(
        tool_name: str,
        params: dict,
        result: dict,
        execution_time_ms: int = 0
    ) -> dict[str, Any]:
        """
        格式化工具执行结果

        存储格式：
        {
            "type": "tool_execution",
            "tool_name": "工具名",
            "params": {...},
            "success": true/false,
            "result_summary": "结果摘要",
            "execution_time_ms": 123
        }
        """
        success = result.get("success", False) if isinstance(result, dict) else False
        message = result.get("user_message", "") if isinstance(result, dict) else str(result)

        return {
            "type": "tool_execution",
            "tool_name": tool_name,
            "params": params,
            "success": success,
            "result_summary": ContentFormatter._truncate(message, 500),
            "execution_time_ms": execution_time_ms
        }

    @staticmethod
    def format_mode_switch(
        from_mode: str,
        to_mode: str,
        context_summary: str = ""
    ) -> dict[str, Any]:
        """
        格式化模式切换

        存储格式：
        {
            "type": "mode_switch",
            "from_mode": "daily",
            "to_mode": "focus",
            "context_summary": "上下文摘要"
        }
        """
        return {
            "type": "mode_switch",
            "from_mode": from_mode,
            "to_mode": to_mode,
            "context_summary": ContentFormatter._truncate(context_summary, 1000)
        }

    @staticmethod
    def _truncate(text: str, max_length: int = CONTENT_MAX_LENGTH) -> str:
        """截断过长文本"""
        if not text:
            return ""
        if len(text) <= max_length:
            return text
        return text[:max_length] + f"...[截断，原长度{len(text)}]"


# ═══════════════════════════════════════════════════════════════════
# 存储决策器
# ═══════════════════════════════════════════════════════════════════

class StorageDecider:
    """
    存储决策器 - 决定存储到什么层级

    决策逻辑：
    - 用户输入 → L2短期记忆（保留24小时）
    - AI回复 → L2短期记忆（保留24小时）
    - 工具执行 → L5执行记忆（永久保留）
    - 模式切换 → L3中期记忆（保留7天）
    - 重要交互 → L4长期记忆（永久保留）
    """

    # 触发类型到默认层级的映射
    DEFAULT_LEVEL_MAP = {
        TriggerType.USER_INPUT: MemoryLevel.L2_SHORT,
        TriggerType.AI_RESPONSE: MemoryLevel.L2_SHORT,
        TriggerType.TOOL_EXECUTION: MemoryLevel.L5_EXECUTION,
        TriggerType.MODE_SWITCH: MemoryLevel.L3_MEDIUM,
        TriggerType.CONTEXT_SUMMARY: MemoryLevel.L3_MEDIUM,
        TriggerType.MANUAL: MemoryLevel.L2_SHORT,
    }

    @classmethod
    def decide_level(
        cls,
        trigger_type: TriggerType,
        content: dict,
        context: dict = None
    ) -> MemoryLevel:
        """
        决定存储层级

        Args:
            trigger_type: 触发类型
            content: 内容
            context: 上下文信息（如对话轮数、用户情绪等）

        Returns:
            MemoryLevel: 存储层级
        """
        # 基础层级
        level = cls.DEFAULT_LEVEL_MAP.get(trigger_type, MemoryLevel.L2_SHORT)

        # 根据内容重要性调整
        if cls._is_important(content, context) and level == MemoryLevel.L2_SHORT:
            # 重要内容升级到L3
            level = MemoryLevel.L3_MEDIUM

        if cls._is_critical(content, context):
            # 关键内容升级到L4
            level = MemoryLevel.L4_EVOLVE

        return level

    @staticmethod
    def _is_important(content: dict, context: dict = None) -> bool:
        """判断内容是否重要"""
        # 检查关键词
        text = str(content)
        important_keywords = ["错误", "失败", "成功", "重要", "关键", "记住"]
        return any(kw in text for kw in important_keywords)

    @staticmethod
    def _is_critical(content: dict, context: dict = None) -> bool:
        """判断内容是否关键"""
        # 检查是否包含关键标记
        if context:
            if context.get("is_critical_step"):
                return True
            if context.get("round_count", 0) > 10:
                # 长对话的关键节点
                return True
        return False


# ═══════════════════════════════════════════════════════════════════
# 主类：MemoryTrigger
# ═══════════════════════════════════════════════════════════════════

class MemoryTrigger:
    """
    记忆自动存储触发器 - 单例模式

    使用示例：
    ```python
    trigger = MemoryTrigger()

    # 方式1: 使用便捷方法
    trigger.on_user_input(user_id, session_id, "打开微信")
    trigger.on_ai_response(user_id, session_id, "好的，我来打开微信")
    trigger.on_tool_execution(user_id, session_id, "launch_app", params, result)

    # 方式2: 使用统一入口
    trigger.trigger(TriggerType.USER_INPUT, user_id, session_id, content)
    ```
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, config: StorageConfig = None):
        if self._initialized:
            return
        self._initialized = True

        self._config = config or StorageConfig()
        self._debounce_queue = DebounceQueue(self._config.debounce_interval)
        self._formatter = ContentFormatter()
        self._decider = StorageDecider()

        # 存储引擎（延迟加载）
        self._async_store = None
        self._memory_manager = None

        # 后台工作线程
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._stop_event = threading.Event()
        self._worker_thread.start()

        # 统计
        self._stats = {
            "triggered": 0,
            "debounced": 0,
            "stored": 0,
            "failed": 0
        }
        self._stats_lock = threading.Lock()

        logger.info("[MemoryTrigger] 记忆自动存储触发器初始化完成")

    def _get_memory_manager(self):
        """获取记忆管理器（延迟加载）"""
        if self._memory_manager is None:
            try:
                from core.memory.memory_manager import memory_manager
                self._memory_manager = memory_manager
            except ImportError:
                logger.error("[MemoryTrigger] 无法导入记忆管理器")
                self._memory_manager = None
        return self._memory_manager

    # ═══════════════════════════════════════════════════════════════
    # 公共API：便捷触发方法
    # ═══════════════════════════════════════════════════════════════

    def on_user_input(
        self,
        user_id: str,
        session_id: str,
        text: str,
        metadata: dict = None
    ) -> str:
        """
        用户输入触发

        调用位置：chat_mode_handler.py handle_voice_input 方法

        Args:
            user_id: 用户ID
            session_id: 会话ID
            text: 用户输入文本
            metadata: 额外元数据（如意图识别结果）

        Returns:
            str: 事件ID
        """
        if not self._config.enable_user_input:
            return ""

        content = self._formatter.format_user_input(text, metadata)
        return self.trigger(TriggerType.USER_INPUT, user_id, session_id, content)

    def on_ai_response(
        self,
        user_id: str,
        session_id: str,
        text: str,
        metadata: dict = None
    ) -> str:
        """
        AI回复触发

        调用位置：agent_loop.py AI响应处理后

        Args:
            user_id: 用户ID
            session_id: 会话ID
            text: AI回复文本
            metadata: 额外元数据（如thinking、action等）

        Returns:
            str: 事件ID
        """
        if not self._config.enable_ai_response:
            return ""

        content = self._formatter.format_ai_response(text, metadata)
        return self.trigger(TriggerType.AI_RESPONSE, user_id, session_id, content)

    def on_tool_execution(
        self,
        user_id: str,
        session_id: str,
        tool_name: str,
        params: dict,
        result: dict,
        execution_time_ms: int = 0
    ) -> str:
        """
        工具执行触发

        调用位置：tool_manager.py execute_tool 方法

        Args:
            user_id: 用户ID
            session_id: 会话ID
            tool_name: 工具名称
            params: 工具参数
            result: 执行结果
            execution_time_ms: 执行耗时（毫秒）

        Returns:
            str: 事件ID
        """
        if not self._config.enable_tool_result:
            return ""

        content = self._formatter.format_tool_result(
            tool_name, params, result, execution_time_ms
        )
        return self.trigger(TriggerType.TOOL_EXECUTION, user_id, session_id, content)

    def on_mode_switch(
        self,
        user_id: str,
        session_id: str,
        from_mode: str,
        to_mode: str,
        context_summary: str = ""
    ) -> str:
        """
        模式切换触发

        调用位置：chat_mode_handler.py switch_mode 方法

        Args:
            user_id: 用户ID
            session_id: 会话ID
            from_mode: 原模式
            to_mode: 新模式
            context_summary: 上下文摘要

        Returns:
            str: 事件ID
        """
        if not self._config.enable_mode_switch:
            return ""

        content = self._formatter.format_mode_switch(from_mode, to_mode, context_summary)
        return self.trigger(TriggerType.MODE_SWITCH, user_id, session_id, content)

    def on_interaction_pair(
        self,
        user_id: str,
        session_id: str,
        user_input: str,
        ai_response: str,
        metadata: dict = None
    ) -> tuple:
        """
        交互对触发（用户输入+AI回复）

        用于更高效地存储一轮对话

        Args:
            user_id: 用户ID
            session_id: 会话ID
            user_input: 用户输入
            ai_response: AI回复
            metadata: 元数据

        Returns:
            tuple: (user_event_id, ai_event_id)
        """
        user_id_evt = self.on_user_input(user_id, session_id, user_input, metadata)
        ai_id_evt = self.on_ai_response(user_id, session_id, ai_response, metadata)
        return user_id_evt, ai_id_evt

    # ═══════════════════════════════════════════════════════════════
    # 核心方法
    # ═══════════════════════════════════════════════════════════════

    def trigger(
        self,
        trigger_type: TriggerType,
        user_id: str,
        session_id: str,
        content: dict[str, Any],
        priority: int = 0
    ) -> str:
        """
        统一触发入口

        Args:
            trigger_type: 触发类型
            user_id: 用户ID
            session_id: 会话ID
            content: 内容
            priority: 优先级

        Returns:
            str: 事件ID
        """
        event_id = str(uuid.uuid4())

        event = TriggerEvent(
            event_id=event_id,
            trigger_type=trigger_type,
            user_id=user_id,
            session_id=session_id,
            content=content,
            priority=priority
        )

        # 添加到防抖队列
        if self._debounce_queue.add(event):
            with self._stats_lock:
                self._stats["triggered"] += 1
            logger.debug(f"[MemoryTrigger] 事件已加入队列: {event_id} ({trigger_type.value})")
        else:
            with self._stats_lock:
                self._stats["debounced"] += 1
            logger.debug(f"[MemoryTrigger] 事件被防抖过滤: {event_id}")

        return event_id

    def _worker_loop(self):
        """后台工作线程（已废弃，同步路径不再执行记忆写入）"""
        return  # 终止同步后台线程，所有写入走异步路径 MemoryService

    def _process_batch(self, events: list[TriggerEvent]):
        """批量处理事件"""
        for event in events:
            try:
                self._store_event(event)
                with self._stats_lock:
                    self._stats["stored"] += 1
            except Exception as e:
                logger.error(f"[MemoryTrigger] 存储事件失败 {event.event_id}: {e}")
                with self._stats_lock:
                    self._stats["failed"] += 1

    def _store_event(self, event: TriggerEvent):
        """存储单个事件到记忆系统"""
        # 决定存储层级
        level = self._decider.decide_level(event.trigger_type, event.content)

        # 准备存储内容
        mem_content = {
            "trigger_type": event.trigger_type.value,
            **event.content
        }

        # 选择存储方式
        if event.trigger_type == TriggerType.TOOL_EXECUTION:
            # 工具执行使用L5执行记忆
            self._store_to_l5(event, mem_content)
        else:
            # 其他使用统一记忆管理器
            self._store_to_memory_manager(event, level, mem_content)

    def _store_to_memory_manager(
        self,
        event: TriggerEvent,
        level: MemoryLevel,
        content: dict
    ):
        """存储到统一记忆管理器"""
        mm = self._get_memory_manager()
        if mm is None:
            logger.warning("[MemoryTrigger] 记忆管理器不可用")
            return

        # 映射到MemoryManager的层级
        layer_map = {
            MemoryLevel.L1_WORKING: "working",
            MemoryLevel.L2_SHORT: "short",
            MemoryLevel.L3_MEDIUM: "medium",
            MemoryLevel.L4_EVOLVE: "evolve",
        }

        layer = layer_map.get(level, "short")

        # 异步存储
        try:
            from core.memory.memory_source import MemorySource

            mem_id = mm.store_memory(
                layer=layer,
                mem_type=event.trigger_type.value,
                content=content,
                context={
                    "session_id": event.session_id,
                    "source": MemorySource.SYSTEM.value,
                    "trigger_event_id": event.event_id
                },
                scene=f"auto_{event.trigger_type.value}",
                rating=1 if event.priority > 0 else 0,
                sync_vector=False  # 异步存储不立即同步向量
            )

            logger.debug(f"[MemoryTrigger] 存储成功: {mem_id[:8]}... (layer={layer})")

        except Exception as e:
            logger.error(f"[MemoryTrigger] 存储到记忆管理器失败: {e}")

    def _store_to_l5(self, event: TriggerEvent, content: dict):
        """存储到L5执行记忆"""
        try:
            from core.memory.execution_memory import execution_memory

            # 提取工具执行信息
            tool_name = content.get("tool_name", "unknown")
            params = content.get("params", {})
            success = content.get("success", False)
            execution_time_ms = content.get("execution_time_ms", 0)

            execution_memory.record_execution(
                user_id=event.user_id,
                tool_name=tool_name,
                params=params,
                success=success,
                result_summary=content.get("result_summary", ""),
                execution_time_ms=execution_time_ms,
                session_id=event.session_id
            )

            logger.debug(f"[MemoryTrigger] L5存储成功: {tool_name}")

        except Exception as e:
            logger.error(f"[MemoryTrigger] 存储到L5失败: {e}")

    # ═══════════════════════════════════════════════════════════════
    # 管理和监控接口
    # ═══════════════════════════════════════════════════════════════

    def get_stats(self) -> dict[str, int]:
        """获取统计信息"""
        with self._stats_lock:
            return dict(self._stats)

    def set_config(self, config: StorageConfig):
        """更新配置"""
        self._config = config
        logger.info("[MemoryTrigger] 配置已更新")

    def flush_now(self) -> int:
        """立即刷新所有待处理事件"""
        events = self._debounce_queue.flush()
        if events:
            self._process_batch(events)
        return len(events)

    def stop(self):
        """停止触发器"""
        logger.info("[MemoryTrigger] 正在停止...")
        self._stop_event.set()

        # 刷新剩余事件
        self.flush_now()

        # 等待线程结束
        self._worker_thread.join(timeout=5.0)
        logger.info("[MemoryTrigger] 已停止")


# ═══════════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════════

def get_memory_trigger() -> MemoryTrigger:
    """获取MemoryTrigger单例实例"""
    return MemoryTrigger()


def on_user_input(user_id: str, session_id: str, text: str, metadata: dict = None) -> str:
    """便捷函数：用户输入触发"""
    return get_memory_trigger().on_user_input(user_id, session_id, text, metadata)


def on_ai_response(user_id: str, session_id: str, text: str, metadata: dict = None) -> str:
    """便捷函数：AI回复触发"""
    return get_memory_trigger().on_ai_response(user_id, session_id, text, metadata)


def on_tool_execution(
    user_id: str,
    session_id: str,
    tool_name: str,
    params: dict,
    result: dict,
    execution_time_ms: int = 0
) -> str:
    """便捷函数：工具执行触发"""
    return get_memory_trigger().on_tool_execution(
        user_id, session_id, tool_name, params, result, execution_time_ms
    )





def on_mode_switch(
    user_id: str,
    session_id: str,
    from_mode: str,
    to_mode: str,
    context_summary: str = ""
) -> str:
    """便捷函数：模式切换触发"""
    return get_memory_trigger().on_mode_switch(
        user_id, session_id, from_mode, to_mode, context_summary
    )


# 全局实例


# ═══════════════════════════════════════════════════════════════════
# Phase 7.2 新增：异步模块级函数（供异步版 agent_loop 使用）
# 设计约束：
#   1. 保留同步函数不变，避免破坏现有调用方
#   2. 异步函数直接调用 AsyncMemory.save()，不走后台线程队列
#   3. 同步/异步双路径并行，Phase 8 统一后再合并
# ═══════════════════════════════════════════════════════════════════

async def on_user_input_async(user_id: str, session_id: str, text: str, metadata: dict = None) -> str:
    """异步模块级函数：用户输入触发（Phase 7.2）——已切至 MemoryService"""
    try:
        import json

        from core.memory.memory_schema import MemoryMetadata
        from core.memory.memory_service import get_memory_service

        memory_service = await get_memory_service()
        meta = MemoryMetadata(
            user_id=user_id,
            source="user_input",
            content_type="text",
            payload_summary=text[:200],
            raw_payload=json.dumps({"text": text, "session_id": session_id, **(metadata or {})}, ensure_ascii=False, default=str),
            session_id=session_id,
        )
        await memory_service.save_chat_turn(session_id=session_id, role="user", content=text, metadata=meta)
        return "stored"
    except Exception as e:
        import logging
        error_msg = str(e)
        if "All connection attempts failed" in error_msg:
            logging.getLogger(__name__).warning(f"[MemoryTrigger-Async] PostgreSQL不可达，降级跳过用户输入存储: {e}")
            return "skipped"
        logging.getLogger(__name__).warning(f"[MemoryTrigger-Async] 用户输入存储失败: {e}")
        return "failed"


async def on_ai_response_async(
    user_id: str,
    session_id: str,
    text: str,
    thinking: str = None,
    tool_calls: list = None,
    message_id: str = None,
    metadata: dict = None,
) -> str:
    """异步模块级函数：AI回复触发（Phase 7.2）——已切至 MemoryService"""
    try:
        import json

        from core.memory.memory_schema import MemoryMetadata
        from core.memory.memory_service import get_memory_service

        memory_service = await get_memory_service()
        payload = {"text": text, "user_id": user_id, "session_id": session_id}
        if thinking:
            payload["thinking"] = thinking
        if tool_calls:
            payload["tool_calls"] = tool_calls
        if message_id:
            payload["message_id"] = message_id

        meta = MemoryMetadata(
            user_id=user_id,
            source="ai_response",
            content_type="text",
            payload_summary=text[:200],
            raw_payload=json.dumps({**payload, **(metadata or {})}, ensure_ascii=False, default=str),
            session_id=session_id,
            round_index=metadata.get("round") if metadata else None,
        )
        await memory_service.save_chat_turn(session_id=session_id, role="assistant", content=text, metadata=meta)
        return "stored"
    except Exception as e:
        import logging
        error_msg = str(e)
        if "All connection attempts failed" in error_msg:
            logging.getLogger(__name__).warning(f"[MemoryTrigger-Async] PostgreSQL不可达，降级跳过AI回复存储: {e}")
            return "skipped"
        logging.getLogger(__name__).warning(f"[MemoryTrigger-Async] AI回复存储失败: {e}")
        return "failed"


async def on_tool_execution_async(
    user_id: str,
    session_id: str,
    tool_name: str,
    params: dict,
    result: dict,
    execution_time_ms: int = 0,
    metadata: dict = None,
) -> str:
    """异步模块级函数：工具执行触发（Phase 7.2）——已切至 MemoryService"""
    try:
        import json

        from core.memory.memory_schema import MemoryMetadata
        from core.memory.memory_service import get_memory_service

        memory_service = await get_memory_service()
        instruction = f"Tool: {tool_name} | Params: {json.dumps(params, ensure_ascii=False, default=str)}"
        meta = MemoryMetadata(
            user_id=user_id,
            source="tool_execution",
            content_type="tool_result",
            payload_summary=instruction[:200],
            raw_payload=json.dumps({
                "tool_name": tool_name,
                "params": params,
                "result": result,
                "execution_time_ms": execution_time_ms,
                "session_id": session_id,
                **(metadata or {}),
            }, ensure_ascii=False, default=str),
            session_id=session_id,
        )
        await memory_service.save_execution_record(instruction=instruction, metadata=meta)
        return "stored"
    except Exception as e:
        import logging
        error_msg = str(e)
        if "All connection attempts failed" in error_msg:
            logging.getLogger(__name__).warning(f"[MemoryTrigger-Async] PostgreSQL不可达，降级跳过工具执行存储: {e}")
            return "skipped"
        logging.getLogger(__name__).warning(f"[MemoryTrigger-Async] 工具执行存储失败: {e}")
        return "failed"


memory_trigger = MemoryTrigger()


# ═══════════════════════════════════════════════════════════════════
# 单元测试
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("测试 MemoryTrigger...")

    trigger = MemoryTrigger()

    # 测试用户输入
    evt1 = trigger.on_user_input("user_001", "session_001", "打开微信")
    print(f"用户输入事件: {evt1}")

    # 测试AI回复
    evt2 = trigger.on_ai_response("user_001", "session_001", "好的，我来打开微信")
    print(f"AI回复事件: {evt2}")

    # 测试工具执行
    evt3 = trigger.on_tool_execution(
        "user_001", "session_001",
        "launch_app",
        {"app_name": "微信"},
        {"success": True, "user_message": "已打开微信"},
        500
    )
    print(f"工具执行事件: {evt3}")

    # 测试防抖（相同内容应该被过滤）
    evt4 = trigger.on_user_input("user_001", "session_001", "打开微信")
    print(f"重复输入事件（应被过滤）: {evt4}")

    # 等待刷新
    time.sleep(3)

    # 获取统计
    stats = trigger.get_stats()
    print(f"统计: {stats}")

    print("✓ 测试完成")
