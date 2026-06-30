#!/usr/bin/env python3
"""
Consciousness 适配器
包装 Consciousness 模块，添加事件发射功能
"""
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

# 导入现有模块（不修改）
from core.Consciousness import Consciousness as _OriginalConsciousness
from core.interfaces import IConsciousness, IEventEmitter

# 导入协议定义
from core.protocol import AgentMessage, create_thought


class ConsciousnessAdapter(IConsciousness):
    """
    Consciousness 适配器类

    包装原有的 Consciousness 类，提供：
    1. 标准化接口实现
    2. 事件发射支持
    3. 思考消息生成

    使用示例:
        adapter = ConsciousnessAdapter()
        adapter.set_event_emitter(event_emitter)
        adapter.start()
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        """单例模式（线程安全）"""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        intrinsic_motivation=None,
        world_model=None
    ):
        if '_initialized' in self.__dict__:  # 使用__dict__避免触发__getattr__
            return
        self._initialized = True

        # 创建原始实例（内部使用）
        self._original = _OriginalConsciousness(
            intrinsic_motivation=intrinsic_motivation,
            world_model=world_model
        )

        self._event_emitter: IEventEmitter | None = None
        self._message_handler: Callable[[AgentMessage], None] | None = None
        self._thought_listeners: list[Callable[[str], None]] = []
        self._thought_history: list[dict[str, Any]] = []

        # 包装原始 _think 方法
        self._original_think = self._original._think
        self._original._think = self._wrapped_think

        # 包装原始 _deep_reflect 方法
        self._original_deep_reflect = self._original._deep_reflect
        self._original._deep_reflect = self._wrapped_deep_reflect

    @property
    def wrapped_instance(self) -> _OriginalConsciousness:
        """获取被包装的原实例"""
        return self._original

    def set_event_emitter(self, emitter: IEventEmitter) -> None:
        """
        设置事件发射器

        Args:
            emitter: 事件发射器实例
        """
        self._event_emitter = emitter

    def set_message_handler(self, handler: Callable[[AgentMessage], None]) -> None:
        """
        设置消息处理器

        Args:
            handler: 消息处理函数
        """
        self._message_handler = handler

    def add_thought_listener(self, listener: Callable[[str], None]) -> None:
        """
        添加思考监听器

        Args:
            listener: 监听器函数，接收思考内容
        """
        self._thought_listeners.append(listener)

    def remove_thought_listener(self, listener: Callable[[str], None]) -> None:
        """
        移除思考监听器

        Args:
            listener: 监听器函数
        """
        if listener in self._thought_listeners:
            self._thought_listeners.remove(listener)

    def start(self) -> None:
        """启动意识线程"""
        self._original.start()

        self._emit_event("consciousness:started", {
            "timestamp": time.time(),
            "think_interval": self._original._think_interval
        })

    def stop(self) -> None:
        """停止意识线程"""
        self._original.stop()

        self._emit_event("consciousness:stopped", {
            "timestamp": time.time(),
            "thought_count": len(self._thought_history)
        })

    def get_internal_state(self) -> dict[str, Any]:
        """
        获取内部状态

        Returns:
            Dict: 内部状态
        """
        state = self._original.get_internal_state()

        # 添加适配器特有的统计信息
        state["adapter_stats"] = {
            "recorded_thoughts": len(self._thought_history),
            "listener_count": len(self._thought_listeners)
        }

        return state

    def adjust_think_interval(self, system_load: dict[str, float]) -> None:
        """
        根据系统负载调整思考频率

        Args:
            system_load: 系统负载信息
        """
        old_interval = self._original._think_interval

        self._original.adjust_think_interval(system_load)

        new_interval = self._original._think_interval

        # 发射事件
        if old_interval != new_interval:
            self._emit_event("consciousness:interval_adjusted", {
                "old_interval": old_interval,
                "new_interval": new_interval,
                "system_load": system_load
            })

    def get_thinking_stats(self) -> dict[str, Any]:
        """
        获取思考统计信息

        Returns:
            Dict: 统计信息
        """
        original_stats = self._original.get_thinking_stats()

        # 合并适配器统计
        original_stats["recorded_thoughts"] = len(self._thought_history)
        original_stats["recent_thoughts"] = [
            t["content"] for t in self._thought_history[-5:]
        ]

        return original_stats

    def emit_thought(self, content: str, trigger: str | None = None) -> None:
        """
        发射思考消息

        Args:
            content: 思考内容
            trigger: 触发源
        """
        # 获取情感状态
        emotional_state = self._original.get_internal_state().get("emotional_state")

        message = create_thought(
            content=content,
            source="consciousness_adapter",
            emotional_state=emotional_state,
            trigger=trigger
        )

        self._emit_message(message)

    def adapt(self, data: Any) -> Any:
        """
        适配数据格式

        Args:
            data: 原始数据

        Returns:
            Any: 适配后的数据
        """
        return data

    def _wrapped_think(self):
        """包装的思考方法"""
        # 调用原始方法
        self._original_think()

        # 获取最近的思考
        if self._original._thought_history:
            recent_thought = self._original._thought_history[-1]
            content = recent_thought.get("content", "")
            mode = recent_thought.get("mode", "default")

            # 记录到历史
            self._thought_history.append({
                "timestamp": time.time(),
                "content": content,
                "mode": mode
            })

            # 限制历史大小
            if len(self._thought_history) > 100:
                self._thought_history = self._thought_history[-100:]

            # 发射思考事件
            self._emit_event("consciousness:thought", {
                "content": content[:100] + "..." if len(content) > 100 else content,
                "mode": mode,
                "timestamp": time.time()
            })

            # 发射思考消息
            self.emit_thought(content, trigger=f"mode:{mode}")

            # 通知监听器
            logger = logging.getLogger(__name__)
            for listener in self._thought_listeners:
                try:
                    listener(content)
                except Exception as e:
                    logger.error(f"[SILENT_FAILURE_BLOCKED] 思考监听器通知失败: {e}")

    def _wrapped_deep_reflect(self):
        """包装的深度反思方法"""
        # 发射反思开始事件
        self._emit_event("consciousness:deep_reflect_started", {
            "timestamp": time.time()
        })

        # 调用原始方法
        self._original_deep_reflect()

        # 发射反思完成事件
        self._emit_event("consciousness:deep_reflect_completed", {
            "timestamp": time.time()
        })

    def _emit_event(self, event_type: str, data: dict[str, Any]) -> None:
        """内部：发射事件"""
        if self._event_emitter:
            self._event_emitter.emit(event_type, data)

    def _emit_message(self, message: AgentMessage) -> None:
        """内部：发送消息"""
        if self._message_handler:
            self._message_handler(message)

    # 代理其他属性访问到原始实例
    def __getattr__(self, name: str) -> Any:
        """代理未定义的属性到原始实例"""
        if name in ('_original', '_initialized', '_event_emitter', '_message_handler'):
            raise AttributeError(name)
        if self._original is None:
            raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")
        return getattr(self._original, name)


# 全局适配器实例
_consciousness_adapter: ConsciousnessAdapter | None = None


def get_consciousness_adapter(
    intrinsic_motivation=None,
    world_model=None,
    force_new: bool = False
) -> ConsciousnessAdapter:
    """
    获取 Consciousness 适配器单例

    Args:
        intrinsic_motivation: 内在动机实例（首次创建时需要）
        world_model: 世界模型实例（首次创建时需要）
        force_new: 是否强制创建新实例

    Returns:
        ConsciousnessAdapter: 适配器实例
    """
    global _consciousness_adapter

    if force_new or _consciousness_adapter is None:
        _consciousness_adapter = ConsciousnessAdapter(
            intrinsic_motivation=intrinsic_motivation,
            world_model=world_model
        )

    return _consciousness_adapter
