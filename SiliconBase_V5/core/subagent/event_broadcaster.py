#!/usr/bin/env python3
"""
SubAgent事件广播器

用于将SubAgent的流式执行事件广播到前端WebSocket
集成到现有的长任务系统中
"""

import json
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from core.logger import logger


class SubAgentEventType(Enum):
    """事件类型"""
    STREAM_EVENT = "subagent_stream"
    AGENT_TREE_UPDATE = "agent_tree_update"
    PIPELINE_STATUS = "pipeline_status"
    LONGTASK_SUBAGENT_INFO = "longtask_subagent_info"


@dataclass
class StreamEvent:
    """流式事件"""
    type: str  # thought, tool_call, tool_result, progress, child_delegate, complete, error, paused, resumed
    content: str
    data: dict[str, Any]
    timestamp: float
    runtime_id: str | None = None
    agent_name: str | None = None


@dataclass
class AgentNode:
    """代理节点"""
    runtime_id: str
    name: str
    description: str | None
    status: str  # pending, running, completed, failed, cancelled
    stage: str | None
    progress: int | None
    children: list['AgentNode']
    parent_runtime_id: str | None = None
    start_time: float | None = None
    end_time: float | None = None
    metadata: dict[str, Any] | None = None


@dataclass
class AgentTree:
    """代理树"""
    root: AgentNode
    total_nodes: int
    max_depth: int


@dataclass
class PipelineStep:
    """流水线步骤"""
    step_id: str
    agent_name: str
    task: str
    step_type: str  # sequential, parallel, conditional
    status: str  # pending, running, completed, failed, skipped, paused
    condition: str | None
    depends_on: list[str]
    on_complete: str | None
    runtime_id: str | None = None
    output: str | None = None
    error: str | None = None
    start_time: float | None = None
    end_time: float | None = None
    progress: int | None = None


@dataclass
class Pipeline:
    """流水线"""
    pipeline_id: str
    name: str
    description: str | None
    steps: list[PipelineStep]
    context: dict[str, Any] | None
    created_at: float


class SubAgentEventBroadcaster:
    """
    SubAgent事件广播器

    单例模式，用于收集和广播SubAgent执行事件
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

        # WebSocket连接管理 {slot_id: [websocket, ...]}
        self._connections: dict[int, list[Any]] = {}

        # 运行时到槽位的映射 {runtime_id: slot_id}
        self._runtime_slot_map: dict[str, int] = {}

        # 事件缓存 {slot_id: [events]}
        self._event_cache: dict[int, list[StreamEvent]] = {}

        # 代理树缓存 {slot_id: AgentTree}
        self._agent_tree_cache: dict[int, AgentTree] = {}

        # 流水线缓存 {slot_id: Pipeline}
        self._pipeline_cache: dict[int, Pipeline] = {}

        logger.info("[SubAgentEventBroadcaster] 事件广播器初始化完成")

    def register_connection(self, slot_id: int, websocket: Any):
        """注册WebSocket连接"""
        if slot_id not in self._connections:
            self._connections[slot_id] = []
        self._connections[slot_id].append(websocket)
        logger.debug(f"[SubAgentEventBroadcaster] 槽位 {slot_id} 注册WebSocket连接，当前连接数: {len(self._connections[slot_id])}")

    def unregister_connection(self, slot_id: int, websocket: Any):
        """注销WebSocket连接"""
        if slot_id in self._connections and websocket in self._connections[slot_id]:
            self._connections[slot_id].remove(websocket)
            logger.debug(f"[SubAgentEventBroadcaster] 槽位 {slot_id} 注销WebSocket连接")

    def associate_runtime_with_slot(self, runtime_id: str, slot_id: int):
        """关联运行时与槽位"""
        self._runtime_slot_map[runtime_id] = slot_id
        logger.debug(f"[SubAgentEventBroadcaster] 运行时 {runtime_id} 关联到槽位 {slot_id}")

    def get_slot_id_for_runtime(self, runtime_id: str) -> int | None:
        """获取运行时对应的槽位ID"""
        return self._runtime_slot_map.get(runtime_id)

    async def broadcast_event(self, slot_id: int, event_type: SubAgentEventType, data: dict[str, Any]):
        """广播事件到指定槽位的所有连接"""
        if slot_id not in self._connections:
            return

        message = {
            "type": event_type.value,
            "data": data,
            "timestamp": time.time()
        }

        # 发送给所有连接的客户端
        disconnected = []
        for ws in self._connections[slot_id]:
            try:
                if hasattr(ws, 'send_json'):
                    await ws.send_json(message)
                elif hasattr(ws, 'send'):
                    await ws.send(json.dumps(message))
            except Exception as e:
                logger.warning(f"[SubAgentEventBroadcaster] 发送消息失败: {e}")
                disconnected.append(ws)

        # 清理断开的连接
        for ws in disconnected:
            self.unregister_connection(slot_id, ws)

    async def broadcast_stream_event(self, runtime_id: str, event: StreamEvent):
        """广播流式事件"""
        slot_id = self.get_slot_id_for_runtime(runtime_id)
        if slot_id is None:
            return

        # 缓存事件
        if slot_id not in self._event_cache:
            self._event_cache[slot_id] = []
        self._event_cache[slot_id].append(event)

        # 限制缓存大小
        if len(self._event_cache[slot_id]) > 1000:
            self._event_cache[slot_id] = self._event_cache[slot_id][-500:]

        # 广播
        await self.broadcast_event(
            slot_id,
            SubAgentEventType.STREAM_EVENT,
            {
                "slot_id": slot_id,
                "event": {
                    "type": event.type,
                    "content": event.content,
                    "data": event.data,
                    "timestamp": event.timestamp,
                    "runtime_id": event.runtime_id,
                    "agent_name": event.agent_name
                }
            }
        )

    async def broadcast_agent_tree(self, slot_id: int, tree: AgentTree):
        """广播代理树更新"""
        self._agent_tree_cache[slot_id] = tree

        await self.broadcast_event(
            slot_id,
            SubAgentEventType.AGENT_TREE_UPDATE,
            {
                "slot_id": slot_id,
                "tree": {
                    "root": self._serialize_agent_node(tree.root),
                    "total_nodes": tree.total_nodes,
                    "max_depth": tree.max_depth
                }
            }
        )

    def _serialize_agent_node(self, node: AgentNode) -> dict[str, Any]:
        """序列化代理节点"""
        return {
            "runtime_id": node.runtime_id,
            "name": node.name,
            "description": node.description,
            "status": node.status,
            "stage": node.stage,
            "progress": node.progress,
            "children": [self._serialize_agent_node(child) for child in node.children],
            "parent_runtime_id": node.parent_runtime_id,
            "start_time": node.start_time,
            "end_time": node.end_time,
            "metadata": node.metadata
        }

    async def broadcast_pipeline_status(self, slot_id: int, pipeline: Pipeline, current_step_id: str | None = None):
        """广播流水线状态"""
        self._pipeline_cache[slot_id] = pipeline

        await self.broadcast_event(
            slot_id,
            SubAgentEventType.PIPELINE_STATUS,
            {
                "slot_id": slot_id,
                "pipeline": {
                    "pipeline_id": pipeline.pipeline_id,
                    "name": pipeline.name,
                    "description": pipeline.description,
                    "steps": [
                        {
                            "step_id": step.step_id,
                            "agent_name": step.agent_name,
                            "task": step.task,
                            "step_type": step.step_type,
                            "status": step.status,
                            "condition": step.condition,
                            "depends_on": step.depends_on,
                            "on_complete": step.on_complete,
                            "runtime_id": step.runtime_id,
                            "output": step.output,
                            "error": step.error,
                            "start_time": step.start_time,
                            "end_time": step.end_time,
                            "progress": step.progress
                        }
                        for step in pipeline.steps
                    ],
                    "context": pipeline.context,
                    "created_at": pipeline.created_at
                },
                "current_step": current_step_id
            }
        )

    def get_cached_events(self, slot_id: int, limit: int = 100) -> list[StreamEvent]:
        """获取缓存的事件"""
        events = self._event_cache.get(slot_id, [])
        return events[-limit:]

    def get_cached_agent_tree(self, slot_id: int) -> AgentTree | None:
        """获取缓存的代理树"""
        return self._agent_tree_cache.get(slot_id)

    def get_cached_pipeline(self, slot_id: int) -> Pipeline | None:
        """获取缓存的流水线"""
        return self._pipeline_cache.get(slot_id)

    def clear_slot_cache(self, slot_id: int):
        """清理槽位缓存"""
        if slot_id in self._event_cache:
            del self._event_cache[slot_id]
        if slot_id in self._agent_tree_cache:
            del self._agent_tree_cache[slot_id]
        if slot_id in self._pipeline_cache:
            del self._pipeline_cache[slot_id]

        # 清理运行时映射
        runtimes_to_remove = [
            runtime_id for runtime_id, sid in self._runtime_slot_map.items()
            if sid == slot_id
        ]
        for runtime_id in runtimes_to_remove:
            del self._runtime_slot_map[runtime_id]

        logger.debug(f"[SubAgentEventBroadcaster] 清理槽位 {slot_id} 的缓存")


# 全局实例
event_broadcaster = SubAgentEventBroadcaster()


# ==================== 辅助函数 ====================

def create_stream_event(
    event_type: str,
    content: str,
    runtime_id: str | None = None,
    agent_name: str | None = None,
    data: dict[str, Any] | None = None
) -> StreamEvent:
    """创建流式事件"""
    return StreamEvent(
        type=event_type,
        content=content,
        data=data or {},
        timestamp=time.time(),
        runtime_id=runtime_id,
        agent_name=agent_name
    )


async def broadcast_to_slot(slot_id: int, event_type: str, content: str, **kwargs):
    """
    便捷函数：广播事件到指定槽位

    使用示例:
        await broadcast_to_slot(1, "thought", "正在分析代码...", runtime_id="rt_001", agent_name="planner")
    """
    broadcaster = SubAgentEventBroadcaster()

    event = create_stream_event(
        event_type=event_type,
        content=content,
        runtime_id=kwargs.get('runtime_id'),
        agent_name=kwargs.get('agent_name'),
        data=kwargs.get('data', {})
    )

    await broadcaster.broadcast_stream_event(
        event.runtime_id or f"unknown_{slot_id}",
        event
    )


# ==================== 与SubAgentRuntime集成 ====================

class WebSocketStreamHandler:
    """
    WebSocket流式处理器

    用于在SubAgentRuntime流式执行时推送事件
    """

    def __init__(self, slot_id: int, runtime_id: str, agent_name: str):
        self.slot_id = slot_id
        self.runtime_id = runtime_id
        self.agent_name = agent_name
        self.broadcaster = SubAgentEventBroadcaster()

    async def on_event(self, event_type: str, content: str, data: dict[str, Any] | None = None):
        """处理事件"""
        event = create_stream_event(
            event_type=event_type,
            content=content,
            runtime_id=self.runtime_id,
            agent_name=self.agent_name,
            data=data or {}
        )
        await self.broadcaster.broadcast_stream_event(self.runtime_id, event)

    async def on_thought(self, content: str):
        """思考事件"""
        await self.on_event("thought", content)

    async def on_tool_call(self, tool: str, params: dict[str, Any]):
        """工具调用事件"""
        await self.on_event("tool_call", f"调用工具: {tool}", {"tool": tool, "params": params})

    async def on_tool_result(self, tool: str, result: Any):
        """工具结果事件"""
        await self.on_event("tool_result", f"工具 {tool} 执行完成", {"tool": tool, "result": result})

    async def on_progress(self, progress: int, message: str = ""):
        """进度事件"""
        await self.on_event("progress", message or f"进度 {progress}%", {"progress": progress})

    async def on_child_delegate(self, child_runtime_id: str, task: str):
        """子代理委派事件"""
        await self.on_event("child_delegate", f"委派给子代理: {task}", {"child_runtime_id": child_runtime_id})

    async def on_complete(self, output: str):
        """完成事件"""
        await self.on_event("complete", output)

    async def on_error(self, error: str):
        """错误事件"""
        await self.on_event("error", error, {"error": error})

    async def on_paused(self, reason: str = ""):
        """暂停事件"""
        await self.on_event("paused", reason or "任务已暂停", {"reason": reason})

    async def on_resumed(self):
        """恢复事件"""
        await self.on_event("resumed", "任务已恢复")
