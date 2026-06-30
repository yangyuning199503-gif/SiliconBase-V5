#!/usr/bin/env python3
"""
AgentRuntime - 运行时状态容器
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
将 agent_loop.py 中频繁传递的参数 bundle 封装为单一对象，
减少函数签名爆炸，并为后续 ContextAssembler 提供统一入口。

【设计约束】
- Phase 1 只建立容器，不替换现有函数签名
- 字段必须与 run_agent_loop() / _run_agent_loop_impl() 的参数一一对应

【字段说明】
- session_id / user_id / mode: 基础上下文
- voice_instance: 语音实例（用于播报）
- chat_history / chat_count: 对话历史
- task_id: 任务ID（断点续传）
- max_rounds: 最大轮数
- stop_event: 中断信号事件
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentRuntime:
    """AgentLoop 运行时状态容器"""

    session_id: str = "console"
    user_id: str | None = None
    mode: str = "daily"
    voice_instance: Any | None = None
    chat_history: list[dict] | None = None
    chat_count: int = 0
    task_id: str | None = None
    max_rounds: int | None = None
    stop_event: Any | None = None

    # 扩展字段池，供 Hook 和子模块使用
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def actual_user_id(self) -> str:
        """获取实际用户ID（降级逻辑与 agent_loop.py 保持一致）"""
        if self.user_id:
            return self.user_id
        if self.session_id and self.session_id != "console":
            return self.session_id
        return "default"
