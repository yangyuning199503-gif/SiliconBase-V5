#!/usr/bin/env python3
"""
Agent Loop 适配器
包装 agent_loop 模块，提供标准化接口
"""
import threading
import time
from collections.abc import Callable
from typing import Any

# 导入现有模块（不修改）
from core.agent.agent_loop import run_agent_loop as _original_run_agent_loop
from core.agent.agent_loop import set_voice_for_tts as _original_set_voice_for_tts
from core.agent.agent_loop import speak_ai_reply as _original_speak_ai_reply
from core.interfaces import IAgentLoop, IEventEmitter
from core.memory.working_memory import WorkingMemory

# 导入协议定义
from core.protocol import AgentMessage, create_task_result, create_tool_call


class AgentLoopAdapter(IAgentLoop):
    """
    Agent Loop 适配器类

    包装原有的 run_agent_loop 函数，提供：
    1. 标准化接口实现
    2. 事件发射支持
    3. 消息协议转换

    使用示例:
        adapter = AgentLoopAdapter()
        adapter.set_event_emitter(event_emitter)
        result, memory = adapter.run_agent_loop(task)
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

        self._event_emitter: IEventEmitter | None = None
        self._message_handler: Callable | None = None
        self._execution_history: list[dict[str, Any]] = []
        self._tools_used: list[str] = []

    @property
    def wrapped_instance(self):
        """获取被包装的实例（原始函数）"""
        return _original_run_agent_loop

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

    def run_agent_loop(
        self,
        task: Any,
        max_rounds: int | None = None,
        chat_history: list[dict] | None = None,
        chat_count: int = 0,
        session_id: str = "console",
        voice_instance: Any | None = None,
        mode: str = "daily"
    ) -> tuple[str | None, Any]:
        """
        运行 Agent 主循环（包装版本）

        在原有功能基础上添加了：
        - 事件发射
        - 消息转换
        - 执行统计

        Args:
            task: 任务对象
            max_rounds: 最大循环轮数
            chat_history: 聊天历史
            chat_count: 当前对话计数
            session_id: 会话ID
            voice_instance: 语音实例
            mode: 运行模式

        Returns:
            Tuple[Optional[str], Any]: (结果字符串, 工作记忆对象)
        """
        start_time = time.time()
        self._execution_history = []
        self._tools_used = []

        # 发射任务开始事件
        self._emit_event("task:started", {
            "task_id": getattr(task, 'id', 'unknown'),
            "goal": getattr(task, 'intent', {}).get('raw', ''),
            "session_id": session_id,
            "mode": mode
        })

        try:
            # 调用原始函数
            result, working_memory = _original_run_agent_loop(
                task=task,
                max_rounds=max_rounds,
                chat_history=chat_history,
                chat_count=chat_count,
                session_id=session_id,
                voice_instance=voice_instance,
                mode=mode
            )

            execution_time = time.time() - start_time
            success = result is not None and "异常结束" not in str(result) and "中断信号" not in str(result)

            # 记录执行历史
            self._execution_history.append({
                "timestamp": start_time,
                "success": success,
                "result": result,
                "execution_time": execution_time
            })

            # 发射任务完成事件
            self._emit_event("task:completed", {
                "task_id": getattr(task, 'id', 'unknown'),
                "success": success,
                "result": result,
                "execution_time": execution_time,
                "tools_used": self._tools_used
            })

            # 发送标准化消息
            self._send_task_result_message(
                task_id=getattr(task, 'id', 'unknown'),
                success=success,
                result=result,
                execution_time=execution_time
            )

            return result, working_memory

        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = str(e)

            # 发射任务失败事件
            self._emit_event("task:failed", {
                "task_id": getattr(task, 'id', 'unknown'),
                "error": error_msg,
                "execution_time": execution_time
            })

            # 发送失败消息
            self._send_task_result_message(
                task_id=getattr(task, 'id', 'unknown'),
                success=False,
                result=None,
                execution_time=execution_time,
                error=error_msg
            )

            raise

    def set_voice_for_tts(self, voice: Any) -> None:
        """设置 TTS 语音实例"""
        _original_set_voice_for_tts(voice)
        self._emit_event("voice:set", {"voice_type": type(voice).__name__})

    def speak_ai_reply(self, text: str) -> None:
        """播报 AI 回复"""
        _original_speak_ai_reply(text)
        self._emit_event("voice:speak", {"text_preview": text[:50] if text else ""})

    def emit_tool_call(self, tool_id: str, params: dict, task_id: str, timeout: int = 30) -> None:
        """
        发射工具调用消息

        Args:
            tool_id: 工具ID
            params: 工具参数
            task_id: 任务ID
            timeout: 超时时间
        """
        self._tools_used.append(tool_id)

        message = create_tool_call(
            tool_id=tool_id,
            params=params,
            task_id=task_id,
            timeout=timeout,
            source="agent_loop_adapter"
        )

        self._emit_message(message)

    def get_execution_stats(self) -> dict[str, Any]:
        """
        获取执行统计信息

        Returns:
            Dict: 执行统计
        """
        if not self._execution_history:
            return {
                "total_executions": 0,
                "successful_executions": 0,
                "failed_executions": 0,
                "average_execution_time": 0.0,
                "total_tools_used": 0
            }

        total = len(self._execution_history)
        successful = sum(1 for h in self._execution_history if h.get("success"))
        avg_time = sum(h.get("execution_time", 0) for h in self._execution_history) / total

        return {
            "total_executions": total,
            "successful_executions": successful,
            "failed_executions": total - successful,
            "average_execution_time": avg_time,
            "total_tools_used": len(self._tools_used),
            "unique_tools_used": list(set(self._tools_used))
        }

    def adapt(self, data: Any) -> Any:
        """
        适配数据格式

        将内部数据格式转换为标准化格式

        Args:
            data: 原始数据

        Returns:
            Any: 适配后的数据
        """
        if isinstance(data, WorkingMemory):
            return self._adapt_working_memory(data)
        return data

    def _emit_event(self, event_type: str, data: dict[str, Any]) -> None:
        """内部：发射事件"""
        if self._event_emitter:
            self._event_emitter.emit(event_type, data)

    def _emit_message(self, message: AgentMessage) -> None:
        """内部：发送消息"""
        if self._message_handler:
            self._message_handler(message)

    def _send_task_result_message(
        self,
        task_id: str,
        success: bool,
        result: Any,
        execution_time: float,
        error: str | None = None
    ) -> None:
        """内部：发送任务结果消息"""
        message = create_task_result(
            task_id=task_id,
            success=success,
            result=result,
            tools_used=self._tools_used,
            error=error,
            execution_time=execution_time,
            source="agent_loop_adapter"
        )
        self._emit_message(message)

    def _adapt_working_memory(self, memory: WorkingMemory) -> dict[str, Any]:
        """内部：适配工作记忆对象"""
        return {
            "goal": getattr(memory, 'goal', ''),
            "query_stage": getattr(memory, 'query_stage', ''),
            "current_category": getattr(memory, 'current_category', None),
            "current_tool": getattr(memory, 'current_tool', None),
            "collected_params": getattr(memory, 'collected_params', {}),
            "execution_count": getattr(memory, 'execution_count', 0)
        }


# 全局适配器实例
_agent_loop_adapter: AgentLoopAdapter | None = None


def get_agent_loop_adapter() -> AgentLoopAdapter:
    """
    获取 Agent Loop 适配器单例

    Returns:
        AgentLoopAdapter: 适配器实例
    """
    global _agent_loop_adapter
    if _agent_loop_adapter is None:
        _agent_loop_adapter = AgentLoopAdapter()
    return _agent_loop_adapter
