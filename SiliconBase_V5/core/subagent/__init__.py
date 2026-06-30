#!/usr/bin/env python3
"""
子代理系统

支持任务委派和并行执行
"""

from core.subagent.config import PRESET_SUBAGENTS, SubAgentConfig, SubAgentType
from core.subagent.feedback_aggregator import (
    SubAgentEvent,
    SubAgentEventType,
    SubAgentFeedbackAggregator,
    SubAgentTask,
    get_feedback_aggregator,
    register_subagent_websocket,
    unregister_subagent_websocket,
)
from core.subagent.manager import SubAgentManager, subagent_manager
from core.subagent.runtime import SubAgentResult, SubAgentRuntime, SubAgentStatus

__all__ = [
    'SubAgentManager',
    'subagent_manager',
    'SubAgentConfig',
    'PRESET_SUBAGENTS',
    'SubAgentType',
    'SubAgentRuntime',
    'SubAgentResult',
    'SubAgentStatus',
    'SubAgentFeedbackAggregator',
    'SubAgentEvent',
    'SubAgentTask',
    'SubAgentEventType',
    'get_feedback_aggregator',
    'register_subagent_websocket',
    'unregister_subagent_websocket',
    'delegate',
    'parallel_delegate',
    'sequential_delegate'
]


# 便捷函数
async def delegate(agent_name: str, task: str, parent_context: dict = None, child_context: dict = None) -> SubAgentResult:
    """快捷委派函数"""
    return await subagent_manager.delegate(agent_name, task, parent_context, child_context)


async def parallel_delegate(tasks: list) -> list:
    """快捷并行委派"""
    return await subagent_manager.parallel_delegate(tasks)


async def sequential_delegate(tasks: list) -> list:
    """快捷顺序委派"""
    return await subagent_manager.sequential_delegate(tasks)
