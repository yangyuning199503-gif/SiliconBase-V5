"""
自我叙事日志 - 只存"我做了什么"的流水账

不存原始板块日志，只存粗粒度的动作与结果。
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

DEFAULT_MAX_ENTRIES = 200
DATA_DIR = Path("core/data/self_narrative")


@dataclass
class NarrativeEntry:
    timestamp: float
    entry: str
    action: str
    result: str
    plates_involved: list[str]
    meta: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NarrativeEntry:
        return cls(
            timestamp=data.get("timestamp", 0.0),
            entry=data.get("entry", ""),
            action=data.get("action", ""),
            result=data.get("result", ""),
            plates_involved=data.get("plates_involved", []),
            meta=data.get("meta", {}),
        )


class SelfNarrativeLog:
    """按用户隔离的自我叙事日志，内存缓存 + jsonl 持久化。"""

    def __init__(self, user_id: str, max_entries: int = DEFAULT_MAX_ENTRIES):
        self.user_id = user_id
        self.max_entries = max_entries
        self._entries: list[NarrativeEntry] = []
        self._file_path = DATA_DIR / f"{user_id}.jsonl"
        self._load()

    def _load(self) -> None:
        if not self._file_path.exists():
            return
        try:
            with self._file_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        self._entries.append(NarrativeEntry.from_dict(data))
                    except json.JSONDecodeError:
                        continue
            # 只保留最近 max_entries
            if len(self._entries) > self.max_entries:
                self._entries = self._entries[-self.max_entries:]
        except Exception:
            pass

    def _persist(self) -> None:
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with self._file_path.open("w", encoding="utf-8") as f:
                for e in self._entries:
                    f.write(json.dumps(e.to_dict(), ensure_ascii=False) + "\n")
        except Exception:
            pass

    def append(self, entry: str, action: str, result: str = "",
               plates_involved: list[str] | None = None,
               meta: dict[str, Any] | None = None) -> NarrativeEntry:
        """追加一条叙事。"""
        item = NarrativeEntry(
            timestamp=time.time(),
            entry=entry,
            action=action,
            result=result,
            plates_involved=plates_involved or [],
            meta=meta or {},
        )
        self._entries.append(item)
        if len(self._entries) > self.max_entries:
            self._entries = self._entries[-self.max_entries:]
        self._persist()
        return item

    def recent(self, n: int = 5) -> list[NarrativeEntry]:
        return self._entries[-n:]

    def recent_text(self, n: int = 5) -> str:
        lines = []
        for e in self.recent(n):
            t = time.strftime("%m-%d %H:%M", time.localtime(e.timestamp))
            lines.append(f"[{t}] {e.entry}")
        return "\n".join(lines) if lines else "（暂无近期自我叙事）"

    def to_prompt_lines(self, n: int = 5) -> list[dict[str, str]]:
        """转成可在 prompt 中使用的 system message 行列表。"""
        lines = []
        for e in self.recent(n):
            t = time.strftime("%m-%d %H:%M", time.localtime(e.timestamp))
            lines.append({"role": "system", "content": f"[自我叙事 {t}] {e.entry}"})
        return lines

    def all_entries(self) -> list[NarrativeEntry]:
        return list(self._entries)

    def clear(self) -> None:
        self._entries.clear()
        self._persist()
