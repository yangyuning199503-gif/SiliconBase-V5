from dataclasses import dataclass, field
from typing import Any


@dataclass
class PhaseContext:
    """统一阶段上下文——所有外迁阶段只认这个"""
    task: Any = None
    working_memory: list[dict] = field(default_factory=list)
    loop_state: Any = None
    session_id: str = ""
    user_id: str | None = None
    execution_history: list[dict] = field(default_factory=list)
    tool_results: list[Any] = field(default_factory=list)
    trace_id: str = ""  # 【P1-1】信息闭环追踪ID

    def get(self, key: str, default=None):
        return getattr(self, key, default)

    def set(self, key: str, value):
        setattr(self, key, value)
