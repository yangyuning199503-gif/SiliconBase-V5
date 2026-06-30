from collections.abc import Mapping
from typing import Any, TypedDict

class AgentMessage(TypedDict):
    msg_type: str
    source: str
    target: str | None
    payload: Any
    timestamp: float
    trace_id: str

def evaluate_condition_py(
    expression: str, variables: dict[str, Any], step_results: dict[str, Any]
) -> bool: ...

def create_message(
    msg_type: str,
    source: str,
    payload: Any,
    target: str | None = None,
    trace_id: str | None = None,
) -> AgentMessage: ...

def create_task_request(
    goal: str,
    source: str = "user",
    priority: str = "normal",
    context: dict[str, Any] | None = None,
    session_id: str = "default",
    task_id: str | None = None,
) -> AgentMessage: ...

def create_task_result(
    task_id: str,
    success: bool,
    result: Any,
    tools_used: list[str] | None = None,
    error: str | None = None,
    execution_time: float = 0.0,
    source: str = "agent_loop",
) -> AgentMessage: ...

def create_tool_call(
    tool_id: str,
    params: dict[str, Any],
    task_id: str,
    timeout: int = 30,
    source: str = "agent_loop",
) -> AgentMessage: ...

def create_thought(
    content: str,
    source: str = "consciousness",
    emotional_state: dict[str, Any] | None = None,
    trigger: str | None = None,
) -> AgentMessage: ...

def create_reflection_request(
    task_description: str,
    execution_history: list[dict[str, Any]],
    task_id: str | None = None,
    source: str = "consciousness",
) -> AgentMessage: ...

def create_reflection_result(
    reflection_id: str,
    success: bool,
    insights: list[str],
    suggestions: list[str],
    task_id: str | None = None,
    source: str = "reflector",
) -> AgentMessage: ...

def create_evolution_trigger(
    trigger_type: str,
    task_id: str | None = None,
    description: str | None = None,
    report: dict[str, Any] | None = None,
    source: str = "evolution",
) -> AgentMessage: ...

def validate_message(message: dict[str, Any]) -> bool: ...
def generate_trace_id() -> str: ...
def priority_to_number(priority: str) -> int: ...
def number_to_priority(number: int) -> str: ...
def get_message_summary(msg: Mapping[str, Any], max_length: int = 100) -> str: ...

class EventBus:
    def subscribe(self, event_type: str, handler: Any) -> None: ...
    def subscribe_all(self, handler: Any) -> None: ...
    def unsubscribe(self, event_type: str, handler: Any) -> bool: ...
    def publish(self, event_type: str, data: Any) -> bool: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def get_stats(self) -> dict[str, int]: ...
    def clear(self) -> None: ...
