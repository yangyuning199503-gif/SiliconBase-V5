#!/usr/bin/env python3
"""
Evolution 适配器
包装 evolution 模块，添加事件监听功能
"""
import contextlib
import threading
import time
from collections.abc import Callable
from typing import Any

# 导入现有模块（不修改）
from core.evolution.evolution import EvolutionEngine as _OriginalEvolutionEngine
from core.evolution.evolution import ExperienceManager as _OriginalExperienceManager
from core.evolution.evolution import evolution as _original_evolution
from core.interfaces import IEventEmitter, IEvolutionEngine, IExperienceManager

# 经验萃取系统已废弃（experience_extractor.py 已删除），
# 此处保留注释作为历史标记。如需注入能力，使用 core.evolution.experience_injector.get_experience_injector_v3()
# 导入协议定义
from core.protocol import AgentMessage, create_evolution_trigger


class EvolutionAdapter(IEvolutionEngine):
    """
    Evolution 适配器类

    包装原有的 EvolutionEngine，提供：
    1. 标准化接口实现
    2. 事件监听和发射
    3. 经验管理增强

    使用示例:
        adapter = EvolutionAdapter()
        adapter.set_event_emitter(event_emitter)
        adapter.on_reflection_report(report, task)
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        """单例模式（线程安全）"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if '_initialized' in self.__dict__:
            return
        self._initialized = True

        # 保存原始实例引用
        self._original = _original_evolution

        self._event_emitter: IEventEmitter | None = None
        self._message_handler: Callable | None = None
        self._listeners: list[Callable] = []
        self._reflection_history: list[dict[str, Any]] = []

    @property
    def wrapped_instance(self) -> _OriginalEvolutionEngine:
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

    def add_listener(self, listener: Callable[[str, dict], None]) -> None:
        """
        添加事件监听器

        Args:
            listener: 监听器函数，接收 (event_type, data)
        """
        self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[str, dict], None]) -> None:
        """
        移除事件监听器

        Args:
            listener: 监听器函数
        """
        if listener in self._listeners:
            self._listeners.remove(listener)

    def extract_success_pattern(self, task_history: list[dict]) -> dict[str, Any]:
        """
        从成功任务中提取可复用模式

        Args:
            task_history: 任务历史

        Returns:
            Dict: 提取的模式
        """
        result = self._original.extract_success_pattern(task_history)

        # 发射事件
        self._emit_event("evolution:pattern_extracted", {
            "task_count": len(task_history),
            "pattern": result
        })

        return result

    def on_reflection_report(self, report: dict[str, Any], task: Any) -> None:
        """
        统一处理反思报告

        Args:
            report: 反思报告
            task: 任务对象
        """
        # 记录到历史
        self._reflection_history.append({
            "timestamp": time.time(),
            "report": report,
            "task_id": getattr(task, 'id', 'unknown')
        })

        # 发射事件
        self._emit_event("evolution:reflection_received", {
            "task_id": getattr(task, 'id', 'unknown'),
            "need_new_tool": report.get("need_new_tool", False),
            "has_description": bool(report.get("new_tool_description"))
        })

        # 发送进化触发消息
        if report.get("need_new_tool"):
            message = create_evolution_trigger(
                trigger_type="reflection",
                task_id=getattr(task, 'id', 'unknown'),
                description=report.get("new_tool_description"),
                report=report,
                source="evolution_adapter"
            )
            self._emit_message(message)

        # 调用原始方法
        self._original.on_reflection_report(report, task)

    def on_success_reflection(self, report: dict[str, Any], task: Any) -> None:
        """
        成功反思处理

        Args:
            report: 反思报告
            task: 任务对象
        """
        user_instruction = report.get("task", "")
        steps = report.get("steps", [])

        # 发射事件
        self._emit_event("evolution:success_reflection", {
            "task_id": getattr(task, 'id', 'unknown'),
            "task_desc": user_instruction,
            "step_count": len(steps)
        })

        # 发送进化触发消息
        message = create_evolution_trigger(
            trigger_type="success",
            task_id=getattr(task, 'id', 'unknown'),
            description=user_instruction,
            report=report,
            source="evolution_adapter"
        )
        self._emit_message(message)

        # 调用原始方法
        self._original.on_success_reflection(report, task)

    def on_failure_reflection(self, report: dict[str, Any], task: Any) -> None:
        """
        失败反思处理

        Args:
            report: 反思报告
            task: 任务对象
        """
        user_instruction = report.get("task", "")
        error = report.get("error", "未知错误")

        # 发射事件
        self._emit_event("evolution:failure_reflection", {
            "task_id": getattr(task, 'id', 'unknown'),
            "task_desc": user_instruction,
            "error": error
        })

        # 发送进化触发消息
        message = create_evolution_trigger(
            trigger_type="failure",
            task_id=getattr(task, 'id', 'unknown'),
            description=user_instruction,
            report=report,
            source="evolution_adapter"
        )
        self._emit_message(message)

        # 调用原始方法
        self._original.on_failure_reflection(report, task)

    def adapt(self, data: Any) -> Any:
        """
        适配数据格式

        Args:
            data: 原始数据

        Returns:
            Any: 适配后的数据
        """
        return data

    def extract_experience(self, task: str, history: list[dict]) -> dict | None:
        """
        【已废弃】经验萃取功能已随 experience_extractor.py 删除而关闭。

        原逻辑为硬编码模板生成，无真实内容分析价值。
        如需经验注入能力，使用 core.evolution.experience_injector.get_experience_injector_v3()。
        """
        return None

    def _get_or_create_strategy_pattern(self, pattern: Any, task: str) -> str:
        """
        【新增】获取或创建对应的策略模式ID

        关联萃取的经验模式与Reflector的策略模式系统

        Args:
            pattern: 萃取的经验模式
            task: 任务描述

        Returns:
            策略模式ID
        """
        try:
            from core.reflector.reflector import StrategyPattern, reflector

            # 检查是否已存在匹配的策略模式
            for pattern_id, existing_pattern in reflector.strategy_patterns.items():
                # 基于名称相似度匹配
                if existing_pattern.name == pattern.pattern_type or \
                   pattern.pattern_type in existing_pattern.description:
                    return pattern_id

            # 创建新的策略模式
            new_pattern_id = f"pattern_exp_{pattern.pattern_id}_{int(time.time())}"
            strategy_pattern = StrategyPattern(
                pattern_id=new_pattern_id,
                name=pattern.pattern_type,
                description=f"Extracted from experience: {pattern.trigger_condition}",
                applicable_scenarios=[task[:50], pattern.trigger_condition],
                strategy_steps=[pattern.action_template],
                success_rate=pattern.success_rate,
                usage_count=pattern.source_count,
                created_at=time.time(),
                last_used=time.time()
            )

            # 注册到Reflector
            reflector.strategy_patterns[new_pattern_id] = strategy_pattern

            return new_pattern_id

        except Exception as e:
            logger = __import__('logging').getLogger(__name__)
            logger.debug(f"[EvolutionAdapter] 创建策略模式关联失败: {e}")
            # 返回原始pattern_id作为fallback
            return pattern.pattern_id

    def store_experience(self, experience: dict) -> bool:
        """
        【增强版】存储萃取的经验到记忆库

        将萃取的模式保存到L3长期记忆

        Args:
            experience: 经验数据（来自extract_experience）

        Returns:
            是否成功
        """
        # experience_extractor.py 已删除，本方法已废弃
        return False

    def get_experience_injector(self) -> Any:
        """
        获取增强版经验注入器

        Returns:
            ExperienceInjectorV3 实例
        """
        from core.evolution.experience_injector import get_experience_injector_v3
        return get_experience_injector_v3(
            enable_tracking=True
        )

    def get_reflection_stats(self) -> dict[str, Any]:
        """
        获取反思统计信息

        Returns:
            Dict: 统计信息
        """
        if not self._reflection_history:
            return {
                "total_reflections": 0,
                "new_tool_requests": 0
            }

        total = len(self._reflection_history)
        new_tool_requests = sum(
            1 for h in self._reflection_history
            if h.get("report", {}).get("need_new_tool", False)
        )

        return {
            "total_reflections": total,
            "new_tool_requests": new_tool_requests,
            "history": self._reflection_history[-10:]  # 最近10条
        }

    def _emit_event(self, event_type: str, data: dict[str, Any]) -> None:
        """内部：发射事件"""
        if self._event_emitter:
            self._event_emitter.emit(event_type, data)

        # 通知监听器
        for listener in self._listeners:
            with contextlib.suppress(Exception):
                listener(event_type, data)  # 避免监听器异常影响主流程

    def _emit_message(self, message: AgentMessage) -> None:
        """内部：发送消息"""
        if self._message_handler:
            self._message_handler(message)


class ExperienceAdapter(IExperienceManager):
    """
    ExperienceManager 适配器

    提供标准化的经验管理接口
    """

    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if '_initialized' in self.__dict__:
            return
        self._initialized = True

        self._event_emitter: IEventEmitter | None = None

    def set_event_emitter(self, emitter: IEventEmitter) -> None:
        """设置事件发射器"""
        self._event_emitter = emitter

    def store(
        self,
        task_desc: str,
        steps: list[str],
        success: bool,
        error_info: str = ""
    ) -> None:
        """
        存储经验

        Args:
            task_desc: 任务描述
            steps: 执行步骤
            success: 是否成功
            error_info: 错误信息
        """
        # 调用原始方法
        _OriginalExperienceManager.store(task_desc, steps, success, error_info)

        # 发射事件
        if self._event_emitter:
            self._event_emitter.emit("experience:stored", {
                "task_desc": task_desc,
                "success": success,
                "step_count": len(steps)
            })

    def retrieve(self, task_desc: str) -> dict[str, Any] | None:
        """
        调取经验

        Args:
            task_desc: 任务描述

        Returns:
            Optional[Dict]: 经验数据
        """
        result = _OriginalExperienceManager.retrieve(task_desc)

        # 发射事件
        if self._event_emitter:
            self._event_emitter.emit("experience:retrieved", {
                "task_desc": task_desc,
                "found": result is not None,
                "type": result.get("type") if result else None
            })

        return result

    def adapt(self, data: Any) -> Any:
        """适配数据格式"""
        return data


# 全局适配器实例
_evolution_adapter: EvolutionAdapter | None = None
_experience_adapter: ExperienceAdapter | None = None


def get_evolution_adapter() -> EvolutionAdapter:
    """
    获取 Evolution 适配器单例

    Returns:
        EvolutionAdapter: 适配器实例
    """
    global _evolution_adapter
    if _evolution_adapter is None:
        _evolution_adapter = EvolutionAdapter()
    return _evolution_adapter


def get_experience_adapter() -> ExperienceAdapter:
    """
    获取 Experience 适配器单例

    Returns:
        ExperienceAdapter: 适配器实例
    """
    global _experience_adapter
    if _experience_adapter is None:
        _experience_adapter = ExperienceAdapter()
    return _experience_adapter


def get_evolution_engine() -> EvolutionAdapter:
    """
    获取 Evolution 引擎单例（与旧版接口兼容）

    这是get_evolution_adapter的别名，用于与旧代码兼容

    Returns:
        EvolutionAdapter: 适配器实例
    """
    return get_evolution_adapter()
