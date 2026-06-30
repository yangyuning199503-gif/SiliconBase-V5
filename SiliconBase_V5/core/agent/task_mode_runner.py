#!/usr/bin/env python3
"""任务模式运行器 - 从 chat_mode_handler 迁移以打破循环导入"""

from typing import Any

from core.logger import logger
from core.task.task_queue import Task


def _notify_work_start():                        # 定义通知工作开始的函数
    """通知意识线程进入工作模式"""               # 函数文档字符串
    try:                                         # 异常处理块
        from core.consciousness.Consciousness import Consciousness  # 延迟导入意识模块
        consciousness = Consciousness._instance   # 获取意识单例实例
        if consciousness:                        # 如果实例存在
            consciousness.on_work_start()        # 调用工作开始回调
    except Exception as e:                            # 捕获所有异常
        logger.error(f"[TaskModeRunner] 通知工作开始失败: {e}", exc_info=True)


def _notify_work_end():                          # 定义通知工作结束的函数
    """通知意识线程退出工作模式"""               # 函数文档字符串
    try:                                         # 异常处理块
        from core.consciousness.Consciousness import Consciousness  # 延迟导入意识模块
        consciousness = Consciousness._instance   # 获取意识单例实例
        if consciousness:                        # 如果实例存在
            consciousness.on_work_end()          # 调用工作结束回调
    except Exception as e:                            # 捕获所有异常
        logger.error(f"[TaskModeRunner] 通知工作结束失败: {e}", exc_info=True)

class TaskModeRunner:                            # 定义任务模式运行器类
    """
    任务模式运行器

    职责：
    1. 运行任务循环（底座 -> AI -> 工具 -> AI -> ...）
    2. 只输出AI的自然语言回复
    3. 直到任务完成或AI喊停
    """

    # 提示词：任务模式，强制回复                   # 类属性注释
    TASK_SYSTEM_PROMPT_BASE = """你是 SiliconBase AI 助手，当前正在**执行任务模式**。   # 系统提示词定义

【当前状态】                                     # 提示词：状态说明
- 你正在执行具体任务：{task_description}         # 当前任务
- 你可以调用工具来完成任务                       # 工具调用权限
- 每执行一步，你需要向用户说明你在做什么         # 执行反馈

【回复规则】                                     # 提示词：回复规则
1. **每次收到消息后必须回复**，哪怕是"正在处理"   # 规则1
2. 使用自然语言告诉用户你在做什么                 # 规则2
3. 如果需要调用工具，在JSON中指定                 # 规则3
4. 任务完成后输出 [TASK_COMPLETE] 标记           # 规则4

【输出格式】                                     # 提示词：输出格式
{{
    "thinking": "我在思考...",
    "action": "call_tool",
    "tool": "tool_name",
    "params": {{}},
    "reply_to_user": "我正在打开QQ音乐..."
}}

或任务完成时：
{{
    "thinking": "任务完成",
    "action": "complete",
    "reply_to_user": "已成功打开QQ音乐并开始播放稻香",
    "complete_marker": "[TASK_COMPLETE]"
}}"""

    def __init__(self):                          # 初始化方法
        from core.agent.agent_loop import run_agent_loop_async  # Phase 8: 异步入口
        self.run_agent_loop = run_agent_loop_async     # 保存异步函数引用

    async def run(self, task_description: str, session_id: str, voice_instance=None, chat_history=None, mode: str = None, db_session_id: str | None = None, user_id: str | None = None, context_flag: str | None = None):   # Phase 8: async 入口
        """
        运行任务直到完成

        流程：
        1. 通知意识线程进入工作模式（暂停弱连接）
        2. 创建Task
        3. 进入run_agent_loop
        4. 只展示AI的自然语言回复
        5. 直到收到TASK_COMPLETE或达到最大轮数
        6. 通知意识线程退出工作模式

        Args:
            mode: 工作模式，默认从work_mode_manager获取当前模式
            context_flag: 意识线程传入的上下文标记，如 "force_vision"
        """
        # 【修复】获取当前实际工作模式
        if mode is None:
            try:
                # 【修复】使用 dual_mode_manager 获取用户隔离的模式
                from core.dialog.chat_mode_handler import dual_mode_manager
                user_mode_mgr = dual_mode_manager.get_mode_manager(session_id)
                current_mode = user_mode_mgr.get_current_mode()
                mode = current_mode.value  # "daily" 或 "focus"
                logger.info(f"[TaskModeRunner] 使用用户工作模式: {mode}")
            except Exception as e:
                logger.warning(f"[TaskModeRunner] 获取用户工作模式失败，使用默认focus: {e}")
                mode = "focus"  # 默认使用专注模式

        # 通知进入工作模式                           # 注释：步骤1
        _notify_work_start()                         # 调用通知函数

        try:                                         # 异常处理块
            # 创建任务                               # 注释：步骤2
            task = Task(                              # 创建任务对象
                type="user",                          # 任务类型为用户任务
                intent={"raw": task_description},     # 任务意图
                session_id=session_id,                # 会话ID
                user_id=user_id or "default_user",    # 【修复】正确设置任务归属用户
                metadata={                            # 元数据
                    "source": "voice_chat_transition",   # 标记来自聊天模式转换
                    "original_chat": True,             # 标记原始聊天
                    "db_session_id": db_session_id,     # 【P0-2】数据库session_id透传
                    "context_flag": context_flag        # 意识线程上下文标记透传
                }
            )

            # 【MasterScheduler 接入】通过主调度器路由，替代裸奔调用
            from core.agent.master_scheduler import master_scheduler
            result = await master_scheduler.dispatch(
                user_request=task_description,
                task=task,
                chat_history=chat_history or [],
                chat_count=0,
                session_id=session_id,
                voice_instance=voice_instance,
                mode=mode,
                db_session_id=db_session_id,
                user_id=user_id,
                context_flag=context_flag,
            )
            if not result.success:
                logger.error("[ChatModeHandler] MasterScheduler dispatch failed: %s", result.error)
                raise RuntimeError(f"调度失败: {result.error}")
            return result.final_answer
        finally:                                     # 最终执行块
            # 通知退出工作模式（无论成功或失败）       # 注释：步骤6
            _notify_work_end()                       # 调用通知函数

    async def run_with_tools(self, task_description: str, session_id: str, voice_instance=None, mode: str = None, db_session_id: str | None = None, user_id: str | None = None) -> dict[str, Any]:
        """
        运行任务直到完成，收集工具调用信息

        【P0-032 修复】WebSocket工具调用信息丢失修复

        流程：
        1. 通知意识线程进入工作模式（暂停弱连接）
        2. 创建Task
        3. 进入run_agent_loop
        4. 通过事件监听器收集工具调用信息
        5. 返回包含AI回复和工具调用信息的结果

        Args:
            mode: 工作模式，默认从work_mode_manager获取当前模式

        Returns:
            Dict[str, Any]: 包含以下字段的字典
                - content (str): AI回复内容
                - tool_calls (List[Dict]): 工具调用列表
        """
        from core.sync.realtime_sync import get_realtime_sync_manager

        # 获取同步管理器用于监听事件
        sync_manager = get_realtime_sync_manager()
        tool_calls: list[dict[str, Any]] = []

        # 定义事件回调函数来收集工具调用信息
        def on_tool_result(event_data: dict[str, Any]):
            """收集工具结果事件"""
            tool_calls.append({
                "tool": event_data.get("tool", ""),
                "success": event_data.get("success", False),
                "message": event_data.get("message", ""),
                "data": event_data.get("data", {}),
                "round": event_data.get("round", 0)
            })

        # 注册临时事件监听器（如果支持）
        # 注意：由于当前emit_event是单向推送，我们通过检查会话事件历史来获取工具调用

        # 【修复】获取当前实际工作模式
        if mode is None:
            try:
                from core.work_mode_manager import get_work_mode_manager
                work_mode_mgr = get_work_mode_manager()
                current_mode = work_mode_mgr.get_current_mode()
                mode = current_mode.value  # "daily" 或 "focus"
                logger.info(f"[TaskModeRunner] run_with_tools 使用当前工作模式: {mode}")
            except Exception as e:
                logger.warning(f"[TaskModeRunner] run_with_tools 获取工作模式失败，使用默认focus: {e}")
                mode = "focus"  # 默认使用专注模式

        # 清空该会话的历史事件（避免获取旧数据）
        if hasattr(sync_manager, '_session_events'):
            sync_manager._session_events.pop(session_id, None)

        # 通知进入工作模式
        _notify_work_start()

        try:
            # 创建任务
            task = Task(
                type="user",
                intent={"raw": task_description},
                session_id=session_id,
                user_id=user_id or "default_user",    # 【修复】正确设置任务归属用户
                metadata={
                    "source": "websocket_api",
                    "collect_tools": True,
                    "db_session_id": db_session_id      # 【P0-2】数据库session_id透传
                }
            )

            # 【MasterScheduler 接入】通过主调度器路由，替代裸奔调用
            from core.agent.master_scheduler import master_scheduler
            result = await master_scheduler.dispatch(
                user_request=task_description,
                task=task,
                chat_history=[],
                chat_count=0,
                session_id=session_id,
                voice_instance=voice_instance,
                mode=mode,
                db_session_id=db_session_id,
                user_id=user_id,
            )
            if not result.success:
                logger.error("[ChatModeHandler] run_with_tools dispatch failed: %s", result.error)
                raise RuntimeError(f"调度失败: {result.error}")

            final_answer = result.final_answer

            # 从同步管理器获取该会话的事件历史来提取工具调用
            if hasattr(sync_manager, '_session_events'):
                session_events = sync_manager._session_events.get(session_id, [])
                for event in session_events:
                    if hasattr(event, 'event_type') and event.event_type == "tool_result":
                        event_data = event.data if hasattr(event, 'data') else {}
                        tool_calls.append({
                            "tool": event_data.get("tool", ""),
                            "success": event_data.get("success", False),
                            "message": event_data.get("message", ""),
                            "data": event_data.get("data", {}),
                            "round": event_data.get("round", 0)
                        })

            return {
                "content": final_answer or "任务执行完成",
                "tool_calls": tool_calls
            }
        finally:
            # 通知退出工作模式
            _notify_work_end()
