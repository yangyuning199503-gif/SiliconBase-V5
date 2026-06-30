#!/usr/bin/env python3
"""
记忆元数据 Schema（MemorySchema）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
白皮书模块：记忆层的 Pydantic Schema 定义
职责：所有写入向量/关系型记忆的数据必须通过此 Schema 校验
原则：禁止裸 Dict[str, Any]，禁止嵌套结构
"""

import json
import time
from typing import Literal

from pydantic import BaseModel, Field


class MemoryMetadata(BaseModel):
    """
    记忆元数据 Schema——所有写入记忆系统的数据必须通过此校验

    设计约束：
    - 扁平字典，禁止嵌套结构（ChromaDB 兼容性）
    - raw_payload 必须是 json.dumps 后的字符串
    - payload_summary 限制 200 字以内，用于搜索结果展示
    """
    user_id: str
    source: Literal[
        "user_input", "ai_response", "tool_execution",
        "reflection", "perception", "plan", "checkpoint"
    ]
    task_id: str | None = None
    session_id: str | None = None
    timestamp: float = Field(default_factory=time.time)
    content_type: Literal["text", "json", "tool_result", "image_desc", "plan"]
    payload_summary: str            # 人类可读摘要（搜索结果展示用）
    raw_payload: str                # json.dumps 后的原始数据（扁平化）
    tags: list[str] = Field(default_factory=list)
    round_index: int | None = None   # AgentLoop 轮次索引
    tool_id: str | None = None       # 工具执行记忆时填充

    @classmethod
    def from_tool_result(
        cls,
        tool_id: str,
        result: dict,
        **kwargs
    ) -> "MemoryMetadata":
        """工厂方法：从工具执行结果构造标准化元数据"""
        return cls(
            source="tool_execution",
            content_type="tool_result",
            payload_summary=result.get("user_message", "")[:200],
            raw_payload=json.dumps(result, ensure_ascii=False, default=str),
            tool_id=tool_id,
            **kwargs
        )

    def to_chroma_metadata(self) -> dict:
        """
        转换为 ChromaDB 可接受的扁平元数据字典

        ChromaDB 限制：值只能是 str/int/float/bool，禁止嵌套 dict/list
        """
        return {
            "user_id": self.user_id,
            "source": self.source,
            "task_id": self.task_id or "",
            "session_id": self.session_id or "",
            "timestamp": self.timestamp,
            "content_type": self.content_type,
            "payload_summary": self.payload_summary,
            "tags": ",".join(self.tags),
            "round_index": self.round_index if self.round_index is not None else -1,
            "tool_id": self.tool_id or "",
        }


class MemoryFilter(BaseModel):
    """
    记忆过滤条件 Schema——用于 VectorStore.search() 的过滤

    设计约束：
    - 所有字段可选
    - 必须提供 to_chroma_where() 转换为 ChromaDB where 子句
    """
    source: str | None = None
    content_type: str | None = None
    task_id: str | None = None
    session_id: str | None = None
    tags: list[str] | None = None
    tool_id: str | None = None
    round_index: int | None = None

    def to_chroma_where(self) -> dict | None:
        """转换为 ChromaDB where 子句字典，扁平化，无嵌套"""
        clauses = {}
        if self.source is not None:
            clauses["source"] = {"$eq": self.source}
        if self.content_type is not None:
            clauses["content_type"] = {"$eq": self.content_type}
        if self.task_id is not None:
            clauses["task_id"] = {"$eq": self.task_id}
        if self.session_id is not None:
            clauses["session_id"] = {"$eq": self.session_id}
        if self.tool_id is not None:
            clauses["tool_id"] = {"$eq": self.tool_id}
        if self.round_index is not None:
            clauses["round_index"] = {"$eq": self.round_index}
        if self.tags is not None and len(self.tags) > 0:
            # ChromaDB 不支持数组 contains，用 tags 字符串匹配
            clauses["tags"] = {"$contains": self.tags[0]}
        return clauses if clauses else None
