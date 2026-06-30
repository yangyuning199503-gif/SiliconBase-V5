"""
自我状态 - 思维线程的轻量本地快照

原则：
- 不依赖神经网络，不依赖大模型。
- 只保存"我现在是谁、我在干什么、我上一秒做了什么"。
- 21 个板块的状态不直接读原始日志，而是通过 core.memory.module_state_manager
  已聚合好的模块摘要来更新 plate_status。
- 生命体征/情绪/身份复用 core.consciousness.self_awareness.SelfAwareness。
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

# 板块 ID 与 module_state_manager 中 module_id 的映射
_PLATE_MODULE_MAP = {
    "vision": ["vision.perception"],
    "weak_connection": [],  # 暂无独立模块ID，由事件推断
    "trading": ["trading.system", "trading.commander", "trading.execution", "trading.market_data", "trading.portfolio"],
    "memory": ["memory.manager"],
    "global_view": [],  # 由工具事件推断
    "voice": ["voice.processor"],
    "goal_system": [],
    "reflector": ["consciousness.reflector"],
    "experience": [],
    "evolution": [],
    "world_model": [],
    "safety": [],
    "intervention": [],
    "dialogue": ["session.manager"],
    "task_scheduler": ["task.manager"],
    "mode": [],
    "cost": [],
    "perception": ["sensors.system", "sensors.window", "sensors.process"],
    "inner_monologue": [],
    "intrinsic_motivation": [],
    "consciousness_self": ["consciousness.engine"],
}


@dataclass
class SelfState:
    """意识服务的轻量自我状态。"""

    user_id: str = "default"
    current_main_task: str = "空闲"
    task_progress: dict[str, Any] = field(default_factory=dict)
    last_action: dict[str, Any] = field(default_factory=dict)
    pending_requests: list[dict[str, Any]] = field(default_factory=list)
    resource_budget: dict[str, Any] = field(default_factory=lambda: {
        "llm_calls_used": 0,
        "llm_calls_total": 1000,
        "note": "每日 LLM 调用预算",
    })
    plate_status: dict[str, str] = field(default_factory=dict)
    plate_summaries: dict[str, str] = field(default_factory=dict)
    mode: str = "idle"  # idle / working / reflecting / alerting
    updated_at: float = field(default_factory=time.time)

    # 来自 SelfAwareness 的只读快照
    vitals: dict[str, Any] = field(default_factory=dict)
    emotion: dict[str, Any] = field(default_factory=dict)
    identity: dict[str, Any] = field(default_factory=dict)

    def update_task(self, task: str, progress: dict[str, Any] | None = None) -> None:
        """更新当前主任务与进度。"""
        self.current_main_task = task
        if progress is not None:
            self.task_progress.update(progress)
        self.updated_at = time.time()

    def record_last_action(self, action: str, result: str, details: dict[str, Any] | None = None) -> None:
        """记录上一次动作及结果。"""
        self.last_action = {
            "action": action,
            "result": result,
            "details": details or {},
            "timestamp": time.time(),
        }
        self.updated_at = time.time()

    def push_pending_request(self, source: str, summary: str, priority: int = 5,
                             meta: dict[str, Any] | None = None) -> None:
        """
        新增一条待处理请求/告警。
        source: 来源板块或 "user"
        summary: 一句话摘要
        priority: 1-10，数字越大越紧急
        """
        key = f"{source}:{summary}"
        for req in self.pending_requests:
            if req.get("key") == key:
                req["updated_at"] = time.time()
                req["priority"] = max(req.get("priority", 5), priority)
                return
        self.pending_requests.append({
            "key": key,
            "source": source,
            "summary": summary,
            "priority": priority,
            "meta": meta or {},
            "created_at": time.time(),
            "updated_at": time.time(),
        })
        self.pending_requests.sort(key=lambda r: r.get("priority", 5), reverse=True)
        if len(self.pending_requests) > 20:
            self.pending_requests = self.pending_requests[:20]
        self.updated_at = time.time()

    def pop_pending_request(self, key: str | None = None) -> dict[str, Any] | None:
        """取走并移除一条待处理请求。默认取优先级最高的一条。"""
        if not self.pending_requests:
            return None
        if key:
            for i, req in enumerate(self.pending_requests):
                if req.get("key") == key:
                    return self.pending_requests.pop(i)
            return None
        return self.pending_requests.pop(0)

    def update_from_module_states(self, module_states: list[dict[str, Any]]) -> None:
        """
        根据 module_state_manager 提供的模块摘要更新 plate_status。
        规则：
        - 如果该板块对应模块最近 60 秒有更新 -> active
        - 最近 5 分钟有更新 -> hibernating
        - 否则 -> unknown
        """
        now = time.time()
        # 先按 module_id 聚合最新时间
        module_latest: dict[str, float] = {}
        module_summary: dict[str, str] = {}
        for item in module_states:
            mid = item.get("module_id", "")
            updated = item.get("updated_at", "")
            if not mid or not updated:
                continue
            try:
                ts = self._parse_ts(updated)
            except Exception:
                ts = now
            module_latest[mid] = max(module_latest.get(mid, 0), ts)
            module_summary[mid] = item.get("summary", "")

        for plate_id, module_ids in _PLATE_MODULE_MAP.items():
            latest_ts = 0.0
            summary_parts = []
            for mid in module_ids:
                ts = module_latest.get(mid, 0)
                if ts > latest_ts:
                    latest_ts = ts
                if mid in module_summary:
                    summary_parts.append(f"{mid}: {module_summary[mid]}")

            age = now - latest_ts if latest_ts else float("inf")
            if age < 60:
                status = "active"
            elif age < 300:
                status = "hibernating"
            elif module_ids:
                status = "unknown"
            else:
                status = "unmonitored"
            self.plate_status[plate_id] = status
            if summary_parts:
                self.plate_summaries[plate_id] = " | ".join(summary_parts[:2])
        self.updated_at = time.time()

    def update_from_self_awareness(self, awareness_snapshot: dict[str, Any]) -> None:
        """复用 SelfAwareness 的生命体征/情绪/身份。"""
        self.vitals = awareness_snapshot.get("vitals", {})
        self.emotion = awareness_snapshot.get("emotion", {})
        self.identity = awareness_snapshot.get("identity", {})
        self.updated_at = time.time()

    def set_plate_status(self, plate_id: str, status: str) -> None:
        self.plate_status[plate_id] = status
        self.updated_at = time.time()

    def set_resource_budget(self, used: int | None = None, total: int | None = None,
                            note: str | None = None) -> None:
        if used is not None:
            self.resource_budget["llm_calls_used"] = used
        if total is not None:
            self.resource_budget["llm_calls_total"] = total
        if note is not None:
            self.resource_budget["note"] = note
        self.updated_at = time.time()

    def consume_llm_call(self) -> bool:
        used = self.resource_budget.get("llm_calls_used", 0)
        total = self.resource_budget.get("llm_calls_total", 1000)
        if used >= total:
            return False
        self.resource_budget["llm_calls_used"] = used + 1
        self.updated_at = time.time()
        return True

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.updated_at = time.time()

    def to_snapshot(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_snapshot(cls, data: dict[str, Any]) -> SelfState:
        allowed = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in allowed}
        return cls(**filtered)

    def to_prompt_summary(self) -> str:
        """生成给 LLM 看的精简自我摘要（不包含板块全貌和原始日志）。"""
        lines = [
            f"【当前主任务】{self.current_main_task}",
            f"【模式】{self.mode}",
        ]
        if self.task_progress:
            step = self.task_progress.get("step", "")
            if step:
                lines.append(f"【任务进度】{step}")
        if self.last_action:
            action = self.last_action.get("action", "")
            result = self.last_action.get("result", "")
            if action:
                lines.append(f"【上次动作】{action}，结果：{result}")
        high = [r for r in self.pending_requests if r.get("priority", 5) >= 7]
        if high:
            lines.append("【高优先级待办】")
            for r in high[:3]:
                lines.append(f"- [{r.get('source', '?')}] {r.get('summary', '')}")
        elif self.pending_requests:
            lines.append(f"【待办数量】{len(self.pending_requests)}")
        lines.append(
            f"【今日 LLM 额度】{self.resource_budget.get('llm_calls_used', 0)}/"
            f"{self.resource_budget.get('llm_calls_total', 1000)}"
        )
        if self.emotion.get("mood_description"):
            lines.append(f"【情绪】{self.emotion.get('mood_description')}")
        return "\n".join(lines)

    @staticmethod
    def _parse_ts(ts: str) -> float:
        from datetime import datetime
        try:
            return datetime.fromisoformat(ts).timestamp()
        except Exception:
            # 兼容 float 时间戳
            return float(ts)
