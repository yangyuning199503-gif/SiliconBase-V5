#!/usr/bin/env python3
"""
AgentLoop Hooks 注册机制
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
为 agent_loop.py 提供可插拔的 Hook 点，逐步将业务逻辑外迁，
避免在 7,000+ 行的单文件中继续堆叠代码。

【设计约束】
- Phase 1 只建立空插槽，不改变现有业务逻辑执行顺序
- 主循环已全部切换至 async 入口（execute_async / execute_async_with_signals）
- 同步入口 execute() / execute_with_signals() 已废弃，将在下一版本删除
- Hook 注册顺序必须显式注释，防止修 A 坏 B

【Hook 点说明】
- before_loop:   进入主循环前（初始化、状态准备）
- before_prompt: Prompt 组装前（上下文注入）
- after_prompt:  LLM 返回后、动作执行前（安全审查、幻觉检测）
- before_tool:   工具调用前（参数校验、权限检查）
- after_tool:    工具调用后（结果解析、视觉验证、语音播报）
- after_loop:    主循环结束后（收尾、状态同步）
- on_interrupt:  检测到中断信号时

【使用示例】
    from core.agent.agent_loop_hooks import agent_loop_hooks, HookContext

    def my_after_tool(ctx: HookContext, tool_result=None) -> HookContext:
        ctx.working_memory.last_tool_result = tool_result
        return ctx

    agent_loop_hooks.register('after_tool', my_after_tool)
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

try:
    from core.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger('agent_loop_hooks')


@dataclass
class HookContext:
    """Hook 共享上下文"""
    task: Any = None
    working_memory: Any = None
    session_id: str = "console"
    user_id: str = "default"
    voice_instance: Any = None
    mode: str = "daily"
    chat_history: list[dict] | None = None
    chat_count: int = 0
    task_id: str | None = None
    runtime: Any = None
    trace_id: str = ""  # 【P1-1】信息闭环追踪ID
    # 扩展字段池，用于 Hook 间传递临时状态
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class HookResult:
    """Hook 执行结果，支持响应替换和信号传递（Phase 7.0 基建）

    设计约束：
    1. 旧 Hook 返回 HookContext 或 None 仍然兼容
    2. 新 Hook 可以返回 HookResult 来传递 should_retry 等信号
    3. execute_with_signals() / execute_async_with_signals() 统一返回 HookResult
    """
    ctx: HookContext
    response: str | None = None
    should_retry: bool = False
    retry_reason: str = ""

    # 便捷属性：兼容旧代码直接访问 ctx 的写法
    @property
    def working_memory(self):
        return self.ctx.working_memory

    @property
    def session_id(self):
        return self.ctx.session_id

    @property
    def user_id(self):
        return self.ctx.user_id


class AgentLoopHooks:
    """
    AgentLoop 全局 Hook 注册器（单例模式）
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self._hooks: dict[str, list[Callable]] = {
            'before_loop': [],
            'before_prompt': [],
            'after_prompt': [],
            'before_tool': [],
            'after_tool': [],
            'after_loop': [],
            'on_interrupt': [],
            # Phase 6 新增：用于语音播报等意图特定 Hook
            'on_complete': [],
            'on_plan': [],
            'on_layer_switch': [],
            'on_pause': [],
            'on_resume': [],
            'on_terminate': [],
            'on_user_assist': [],
            'on_world_model': [],
            'on_understanding_confirmed': [],
            'on_error': [],
            'on_moral_blocked': [],
            # 【Phase X】步骤生命周期 Hook：用于断点续传和 Plan 推进
            'before_step': [],
            'after_step': [],
        }

        logger.info("[AgentLoopHooks] Hook 系统初始化完成")

    def register(self, point: str, handler: Callable, priority: int = 0):
        """
        注册 Hook 处理器

        Args:
            point: Hook 点名称
            handler: 处理函数，签名应为 (ctx, **kwargs) -> ctx | None
            priority: 优先级，数字越大越先执行（默认 0）
        """
        if point not in self._hooks:
            raise ValueError(f"未知 Hook 点: {point}")

        hooks = self._hooks[point]

        # 【修复】防重检查：避免同一 handler 被重复注册导致副作用翻倍
        for _, existing_handler in hooks:
            if existing_handler is handler:
                logger.debug(f"[AgentLoopHooks] {point} 处理器 {handler.__name__} 已存在，跳过重复注册")
                return

        # 按 priority 降序插入
        entry = (priority, handler)
        inserted = False
        for i, (p, _) in enumerate(hooks):
            if priority > p:
                hooks.insert(i, entry)
                inserted = True
                break
        if not inserted:
            hooks.append(entry)

        logger.debug(f"[AgentLoopHooks] 注册 {point} 处理器: {handler.__name__}, priority={priority}")

    async def execute(self, point: str, ctx: HookContext, **kwargs) -> HookContext:
        """
        ⚠️ DEPRECATED (2026-05-06): 同步执行 Hook 链

        Phase 3 改造完成后主循环已全部切换至 execute_async()，
        本方法已无生产调用方，保留仅避免破坏外部调用方，将在下一版本删除。
        """
        import warnings
        warnings.warn(
            "execute() is deprecated since Phase 3. Use execute_async() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        logger.warning(
            "[AgentLoopHooks] execute() 已废弃，请使用 execute_async() 替代"
        )
        import inspect

        for priority, handler in self._hooks.get(point, []):
            try:
                if inspect.iscoroutinefunction(handler):
                    result = await handler(ctx, **kwargs)
                else:
                    result = handler(ctx, **kwargs)
                if result is not None:
                    ctx = result
            except Exception as e:
                logger.warning(f"[AgentLoopHooks] {point} 处理器 {handler.__name__} 执行失败 (priority={priority}): {e}")
        return ctx

    async def execute_async(self, point: str, ctx: HookContext, **kwargs) -> HookContext:
        """
        异步执行 Hook 链

        如果 handler 不是 coroutine，则回退到同步调用。
        """
        import inspect
        hook_count = 0
        for priority, handler in self._hooks.get(point, []):
            try:
                if inspect.iscoroutinefunction(handler):
                    result = await handler(ctx, **kwargs)
                else:
                    result = handler(ctx, **kwargs)
                if result is not None:
                    ctx = result
                hook_count += 1
            except Exception as e:
                logger.warning(f"[AgentLoopHooks] {point} 处理器 {handler.__name__} 异步执行失败 (priority={priority}): {e}")
        # 【ExperienceBus】Hook 执行事件
        try:
            from core.sync.event_bus import event_bus
            event_bus.emit("agent_loop:hook_triggered", {
                "hook_point": point,
                "handler_count": hook_count,
                "session_id": getattr(ctx, 'session_id', ''),
                "timestamp": time.time(),
            })
        except Exception as e:
            logger.error(f"[AgentLoopHooks] 发送钩子执行事件失败: {e}", exc_info=True)
        return ctx

    async def execute_with_signals(self, point: str, ctx: HookContext, **kwargs) -> HookResult:
        """
        ⚠️ DEPRECATED (2026-05-06): 支持信号传递的 Hook 执行（Phase 7.0 基建）

        Phase 3 改造完成后主循环已全部切换至 execute_async_with_signals()，
        本方法已无生产调用方，保留仅避免破坏外部调用方，将在下一版本删除。
        """
        import warnings
        warnings.warn(
            "execute_with_signals() is deprecated since Phase 3. Use execute_async_with_signals() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        logger.warning(
            "[AgentLoopHooks] execute_with_signals() 已废弃，请使用 execute_async_with_signals() 替代"
        )
        import inspect

        result = HookResult(ctx=ctx)

        for priority, handler in self._hooks.get(point, []):
            try:
                if inspect.iscoroutinefunction(handler):
                    handler_result = await handler(result.ctx, **kwargs)
                else:
                    handler_result = handler(result.ctx, **kwargs)

                # 兼容性适配：区分旧 Hook（返回 ctx/None）和新 Hook（返回 HookResult）
                if isinstance(handler_result, HookResult):
                    result = handler_result
                elif handler_result is not None:
                    result.ctx = handler_result

            except Exception as e:
                logger.warning(f"[AgentLoopHooks] {point} 处理器 {handler.__name__} 信号执行失败 (priority={priority}): {e}")

        return result

    async def execute_async_with_signals(self, point: str, ctx: HookContext, **kwargs) -> HookResult:
        """异步版信号传递执行（Phase 7.0 基建）

        同步/异步双版本必须同时修改，否则 agent_loop.py 的异步主循环无法获得重试信号。
        """
        import inspect

        result = HookResult(ctx=ctx)

        for priority, handler in self._hooks.get(point, []):
            try:
                if inspect.iscoroutinefunction(handler):
                    handler_result = await handler(result.ctx, **kwargs)
                else:
                    handler_result = handler(result.ctx, **kwargs)

                # 兼容性适配
                if isinstance(handler_result, HookResult):
                    result = handler_result
                elif handler_result is not None:
                    result.ctx = handler_result

            except Exception as e:
                logger.warning(f"[AgentLoopHooks] {point} 处理器 {handler.__name__} 异步信号执行失败 (priority={priority}): {e}")

        return result

    def clear(self, point: str = None):
        """清空指定或全部 Hook"""
        if point:
            if point in self._hooks:
                self._hooks[point].clear()
        else:
            for p in self._hooks:
                self._hooks[p].clear()

    def list_handlers(self, point: str = None) -> dict[str, list[str]]:
        """列出已注册的处理器（用于调试）"""
        if point:
            return {point: [h.__name__ for _, h in self._hooks.get(point, [])]}
        return {p: [h.__name__ for _, h in handlers] for p, handlers in self._hooks.items()}


# ═══════════════════════════════════════════════════════════════
# 全局实例
# ═══════════════════════════════════════════════════════════════
agent_loop_hooks = AgentLoopHooks()
