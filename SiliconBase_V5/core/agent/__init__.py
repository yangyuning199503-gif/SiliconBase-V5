"""
Agent 模块
【Week 5-8 架构重构】

向后兼容说明:
- 原有导入路径仍然有效
- 新代码建议使用新架构组件

新架构组件:
- core.execution: 执行层 (AgentRuntime)
- core.orchestration: 编排层 (InterventionCoordinator, ConcurrentTaskScheduler)
  - MasterScheduler 内部已接入 ConcurrentTaskScheduler 作为任务队列与执行引擎
- core.interface: 接口层 (API/WebSocket入口)
- core.perception: 感知层 (输入处理)
- core.safety: 安全层 (安全检测)
"""

# 保持向后兼容的导出
from .agent_loop import run_agent_loop

__all__ = [
    # 向后兼容
    'run_agent_loop',
]
