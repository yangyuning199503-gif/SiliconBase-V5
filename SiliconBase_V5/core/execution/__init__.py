"""
执行层 (Execution Layer)
【Week 5-8 架构重构】

职责: 核心ReAct循环执行，不包含干预处理、状态管理等杂项
目标: 将 agent_loop.py 从 8,683 行精简到 <500 行核心逻辑

向后兼容说明:
- 原有导入路径仍然有效 (core.agent.agent_loop)
- 通过适配器模式提供兼容接口
"""

from .agent_runtime import AgentRuntime, RuntimeStatus

__all__ = [
    'AgentRuntime',
    'RuntimeStatus'
]
