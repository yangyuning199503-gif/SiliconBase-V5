#!/usr/bin/env python3
"""
Traceability - 信息闭环追踪系统
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【P1-1】trace_id 贯穿信息闭环的核心基础设施。

使用 Python contextvars 实现无侵入传播：
- AgentLoop 入口 set_trace_id() 一次
- EventBus.emit / MemoryService.save_chat_turn 自动读取
- 所有下游模块无需修改调用签名即可获得 trace_id

使用方式：
    from core.traceability import set_trace_id, get_trace_id, trace_info_flow
    set_trace_id("abc123")
    # 后续任何异步/同步代码中：
    tid = get_trace_id()  # -> "abc123"
"""

import contextvars
import json
import time
from datetime import datetime
from typing import Any

from core.logger import logger

# ═══════════════════════════════════════════════════════════════════════════════
# ContextVar：线程+协程安全的上下文变量
# ═══════════════════════════════════════════════════════════════════════════════

_current_trace_id: contextvars.ContextVar[str] = contextvars.ContextVar('current_trace_id', default='')


def set_trace_id(trace_id: str) -> None:
    """设置当前上下文的 trace_id"""
    _current_trace_id.set(trace_id)
    logger.debug(f"[Traceability] trace_id set: {trace_id}")


def get_trace_id() -> str:
    """获取当前上下文的 trace_id（无则返回空字符串）"""
    return _current_trace_id.get()


def clear_trace_id() -> None:
    """清除当前上下文的 trace_id"""
    _current_trace_id.set('')


# ═══════════════════════════════════════════════════════════════════════════════
# 内存索引：trace_id → 事件/记忆ID 映射（用于快速查询）
# ═══════════════════════════════════════════════════════════════════════════════

_trace_index: dict[str, dict[str, Any]] = {}
_TRACE_INDEX_MAX_SIZE = 1000  # 防止内存无限增长


def _ensure_index_entry(trace_id: str) -> dict[str, Any]:
    """确保索引中有该 trace_id 的条目"""
    global _trace_index
    if trace_id not in _trace_index:
        # LRU：超出上限时删除最旧的
        if len(_trace_index) >= _TRACE_INDEX_MAX_SIZE:
            oldest = min(_trace_index, key=lambda k: _trace_index[k].get('created_at', ''))
            del _trace_index[oldest]
        _trace_index[trace_id] = {
            'created_at': datetime.now().isoformat(),
            'events': [],
            'memory_ids': [],
            'tools': [],
            'decisions': [],
        }
    return _trace_index[trace_id]


def record_event(trace_id: str, event_name: str, event_data: Any = None) -> None:
    """记录事件到 trace 索引"""
    if not trace_id:
        return
    entry = _ensure_index_entry(trace_id)
    entry['events'].append({
        'name': event_name,
        'data': event_data,
        'timestamp': datetime.now().isoformat(),
    })
    logger.debug(f"[Traceability] event recorded: {event_name} trace={trace_id}")


def record_memory(trace_id: str, memory_id: str, layer: str = "") -> None:
    """记录记忆ID到 trace 索引"""
    if not trace_id:
        return
    entry = _ensure_index_entry(trace_id)
    entry['memory_ids'].append({
        'id': memory_id,
        'layer': layer,
        'timestamp': datetime.now().isoformat(),
    })
    logger.debug(f"[Traceability] memory recorded: {memory_id} layer={layer} trace={trace_id}")


def record_tool(trace_id: str, tool_name: str, success: bool = True) -> None:
    """记录工具执行到 trace 索引"""
    if not trace_id:
        return
    entry = _ensure_index_entry(trace_id)
    entry['tools'].append({
        'name': tool_name,
        'success': success,
        'timestamp': datetime.now().isoformat(),
    })
    logger.debug(f"[Traceability] tool recorded: {tool_name} success={success} trace={trace_id}")


def record_decision(trace_id: str, decision: str, reasoning: str = "") -> None:
    """记录决策到 trace 索引"""
    if not trace_id:
        return
    entry = _ensure_index_entry(trace_id)
    entry['decisions'].append({
        'decision': decision,
        'reasoning': reasoning,
        'timestamp': datetime.now().isoformat(),
    })
    logger.debug(f"[Traceability] decision recorded: {decision[:30]} trace={trace_id}")


async def save_decision(user_id: str, query: str, decision: str, reasoning: str = "", trace_id: str = "", memory_service=None) -> str | None:
    """
    【P1-2】将 AI 决策过程保存到 VectorStore 的 decisions collection。

    Args:
        user_id: 用户ID
        query: 用户输入/查询
        decision: 决策结论（如选择的工具、回答摘要）
        reasoning: 推理过程/思考链
        trace_id: 追踪ID
        memory_service: MemoryService 实例（由调用方传入，打破循环依赖）

    Returns:
        保存的决策记录 ID，或 None（保存失败时）
    """
    doc_id = None
    try:
        if memory_service is not None:
            from core.memory.memory_schema import MemoryMetadata

            # 构建可向量化的文本：查询 + 决策 + 推理
            vector_text = f"用户请求: {query}\n决策: {decision}\n推理: {reasoning}"[:500]

            # 【修复】使用扁平 dict 元数据，避免 MemoryMetadata 校验失败
            # ChromaDB 要求值为 str/int/float/bool，禁止嵌套 dict
            metadata = {
                "user_id": user_id,
                "source": "reflection",
                "content_type": "text",
                "payload_summary": decision[:200],
                "raw_payload": json.dumps({
                    "query": query,
                    "decision": decision,
                    "reasoning": reasoning,
                    "trace_id": trace_id,
                }, ensure_ascii=False, default=str),
                "tags": "decision,reflection",
                "round_index": -1,
                "tool_id": "",
                "task_id": "",
                "session_id": "",
                "timestamp": time.time(),
            }

            doc_id = await memory_service.vector_store.add("decisions", vector_text, metadata)
            logger.info(f"[DecisionStore] 决策已保存: {doc_id}, user={user_id}")

        # 同时记录到 trace 索引
        if trace_id:
            record_decision(trace_id, decision, reasoning)

        return doc_id
    except Exception as e:
        logger.debug(f"[DecisionStore] 保存决策失败: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# 查询接口
# ═══════════════════════════════════════════════════════════════════════════════

async def trace_info_flow(trace_id: str, memory_service=None) -> dict[str, Any] | None:
    """
    查询指定 trace_id 的完整信息流转路径。

    【CRIT-1 修复】优先查内存索引，无则回查持久化存储：
    1. VectorStore decisions collection（决策记录）
    2. PostgreSQL memories 表（trace_id 在 metadata.context 中）

    Args:
        trace_id: 追踪ID
        memory_service: MemoryService 实例（由调用方传入，打破循环依赖）

    Returns:
        {
            "trace_id": "...",
            "created_at": "...",
            "events": [...],
            "memory_ids": [...],
            "tools": [...],
            "decisions": [...],
        }
        或 None（trace_id 不存在且持久化也未找到）
    """
    global _trace_index
    entry = _trace_index.get(trace_id)

    # 如果内存中有，直接返回
    if entry:
        return {
            "trace_id": trace_id,
            "created_at": entry.get('created_at'),
            "events": entry.get('events', []),
            "memory_ids": entry.get('memory_ids', []),
            "tools": entry.get('tools', []),
            "decisions": entry.get('decisions', []),
        }

    # 内存中没有，尝试回查持久化存储
    persistent_decisions = []
    persistent_memories = []

    try:
        # 1. 回查 VectorStore decisions collection
        if memory_service is not None and hasattr(memory_service, 'vector_store') and memory_service.vector_store:
            try:
                results = await memory_service.vector_store.search(
                    "decisions", trace_id, limit=10
                )
                for r in results:
                    if not r.metadata:
                        continue
                    ctx = r.metadata.get("context", {}) or {}
                    if ctx.get("trace_id") == trace_id:
                        persistent_decisions.append({
                            "decision": ctx.get("decision", ""),
                            "reasoning": ctx.get("reasoning", ""),
                            "timestamp": ctx.get("timestamp", ""),
                        })
            except Exception as e:
                logger.debug(f"[Traceability] VectorStore decisions 回查失败: {e}")

        # 2. 回查 PostgreSQL memories 表（context JSONB 中存了 trace_id）
        try:
            from core.memory.postgres_pool import AsyncPostgresPool
            pool = await AsyncPostgresPool.get_pool()
            rows = await pool.fetch(
                """
                SELECT id, layer, content, context, created_at
                FROM memories
                WHERE context::jsonb->>'trace_id' = $1
                ORDER BY created_at DESC
                LIMIT 20
                """,
                trace_id,
            )
            for row in rows:
                persistent_memories.append({
                    "id": row["id"],
                    "layer": row["layer"],
                    "content": str(row["content"])[:100],
                    "timestamp": row["created_at"].isoformat() if hasattr(row["created_at"], 'isoformat') else str(row["created_at"]),
                })
        except Exception as e:
            logger.debug(f"[Traceability] PostgreSQL memories 回查失败: {e}")

    except Exception as e:
        logger.debug(f"[Traceability] 持久化回查整体失败: {e}")

    # 如果持久化也未找到任何数据，返回 None
    if not persistent_decisions and not persistent_memories:
        return None

    # 从持久化数据重建索引条目（方便后续内存查询）
    _trace_index[trace_id] = {
        'created_at': datetime.now().isoformat(),
        'events': [],
        'memory_ids': persistent_memories,
        'tools': [],
        'decisions': persistent_decisions,
    }

    return {
        "trace_id": trace_id,
        "created_at": _trace_index[trace_id]['created_at'],
        "events": [],
        "memory_ids": persistent_memories,
        "tools": [],
        "decisions": persistent_decisions,
    }


def get_recent_traces(limit: int = 20) -> list[dict[str, Any]]:
    """获取最近的 trace 列表（按创建时间倒序）"""
    global _trace_index
    sorted_items = sorted(
        _trace_index.items(),
        key=lambda x: x[1].get('created_at', ''),
        reverse=True
    )[:limit]
    return [
        {
            "trace_id": tid,
            "created_at": info.get('created_at'),
            "event_count": len(info.get('events', [])),
            "memory_count": len(info.get('memory_ids', [])),
            "tool_count": len(info.get('tools', [])),
            "decision_count": len(info.get('decisions', [])),
        }
        for tid, info in sorted_items
    ]
