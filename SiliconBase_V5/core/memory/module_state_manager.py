#!/usr/bin/env python3
"""
模块状态管理器 V2 — 全局自动采集
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
零侵入：不需要修改任何现有模块代码。
采集来源：
  1. EventBus 所有事件 → 通配订阅，自动推断模块+压缩摘要
  2. 工具执行结果 → ToolHook 自动解析更新
  3. 手动更新 → 各模块仍可主动调用 update_module_state()

使用方式：
  # 手动更新（可选，自动采集已覆盖大部分场景）
  from core.memory.module_state_manager import update_module_state
  await update_module_state("trading.auto_trader", "策略=网格 BTC/USDT | 状态=等待API Key验证")

  # 检索相关模块状态（ContextAssembler 自动调用）
  from core.memory.module_state_manager import search_module_states
  states = await search_module_states("用户想查交易记录", limit=5)
"""

import asyncio
import time
from datetime import datetime
from typing import Any

from core.logger import logger
from core.sync.event_bus import EventPriority, event_bus

MODULE_STATE_COLLECTION = "module_states"

# 跟踪后台 module_state 更新任务，避免事件循环关闭时产生 "Task was destroyed but it is pending!"
_module_state_tasks: set[asyncio.Task] = set()


def _spawn_module_state_task(module_id: str, summary: str) -> None:
    """启动一个受跟踪的 module_state 后台更新任务"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(update_module_state(module_id, summary))
    _module_state_tasks.add(task)
    task.add_done_callback(_module_state_tasks.discard)


async def shutdown_module_state_manager() -> None:
    """取消并等待所有未完成的 module_state 更新任务"""
    pending = [t for t in _module_state_tasks if not t.done()]
    for t in pending:
        t.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    _module_state_tasks.clear()

# 内存缓存：VectorStore 未就绪时不丢失状态
_module_state_cache: dict[str, dict[str, Any]] = {}
_MODULE_CACHE_MAX_SIZE = 100  # LRU 上限


def _set_cache(module_id: str, data: dict[str, Any]) -> None:
    """带 LRU 的缓存写入"""
    global _module_state_cache
    # 超出上限时删除最旧的条目
    if len(_module_state_cache) >= _MODULE_CACHE_MAX_SIZE and module_id not in _module_state_cache:
        oldest_key = min(_module_state_cache, key=lambda k: _module_state_cache[k].get("updated_at", ""))
        del _module_state_cache[oldest_key]
    _module_state_cache[module_id] = data

# ═══════════════════════════════════════════════════════════════════════════════
# 事件名 → 模块 ID 映射表（覆盖项目中已知的事件模式）
# ═══════════════════════════════════════════════════════════════════════════════

_EVENT_MODULE_MAP = {
    # AI / 模型
    "model_download_start": "ai.model_manager",
    "model_download_complete": "ai.model_manager",
    "model_download_progress": "ai.model_manager",
    "model_loaded": "ai.model_manager",
    "model_unloaded": "ai.model_manager",
    # 交易
    "commander_report": "trading.commander",
    "commander.notification": "trading.commander",
    "commander.report": "trading.commander",
    "mcp_call_start": "trading.commander",
    "mcp_call_complete": "trading.commander",
    "market_data_update": "trading.market_data",
    "order_placed": "trading.execution",
    "order_filled": "trading.execution",
    "position_changed": "trading.portfolio",
    # 配置
    "config_changed": "config.manager",
    "user_config_changed": "config.manager",
    "user_prompt_module_changed": "prompt.manager",
    # 意识
    "consciousness:thought_generated": "consciousness.engine",
    "consciousness:state_changed": "consciousness.engine",
    "MSG_TASK_PROPOSED": "consciousness.engine",
    "MSG_REFLECTION_REQUEST": "consciousness.reflector",
    # 任务
    "task.completed": "task.manager",
    "task.created": "task.manager",
    "task.failed": "task.manager",
    # 记忆
    "memory.saved": "memory.manager",
    "memory.recalled": "memory.manager",
    "memory.compressed": "memory.manager",
    # 会话
    "session.started": "session.manager",
    "session.ended": "session.manager",
    # 工具
    "tool.executed": "tool.manager",
    "tool.failed": "tool.manager",
    # 工作流
    "workflow.step_complete": "workflow.executor",
    "workflow.failed": "workflow.executor",
    # 感知
    "perception.data": "sensors.system",
    "window.changed": "sensors.window",
    "process.alert": "sensors.process",
}


def _infer_module_from_event(event_name: str, source: str = "") -> str | None:
    """
    根据事件名推断模块 ID。
    先查映射表，再按前缀规则推断，最后回退到 source。
    """
    # 1. 精确匹配
    if event_name in _EVENT_MODULE_MAP:
        return _EVENT_MODULE_MAP[event_name]

    # 2. 前缀规则
    name_lower = event_name.lower()
    if "trading" in name_lower or "btc" in name_lower or "order" in name_lower:
        return "trading.system"
    if "memory" in name_lower:
        return "memory.manager"
    if "config" in name_lower:
        return "config.manager"
    if "consciousness" in name_lower or "thought" in name_lower:
        return "consciousness.engine"
    if "task" in name_lower:
        return "task.manager"
    if "session" in name_lower:
        return "session.manager"
    if "prompt" in name_lower:
        return "prompt.manager"
    if "workflow" in name_lower:
        return "workflow.executor"
    if "model" in name_lower or "ai." in name_lower:
        return "ai.model_manager"
    if "tool" in name_lower:
        return "tool.manager"
    if "vision" in name_lower or "screen" in name_lower or "pixel" in name_lower:
        return "vision.perception"
    if "voice" in name_lower:
        return "voice.processor"

    # 3. 回退到 source
    if source:
        return source.replace(".", "_").replace("/", "_")

    # 4. 未知事件，按顶级命名空间归类，避免动态 ID 导致 module_id 爆炸
    top_ns = event_name.split(':')[0].split('.')[0].split('_')[0]
    if top_ns:
        return f"event.{top_ns}"
    return "event.unknown"


def _auto_summarize(event_name: str, event_data: Any) -> str:
    """
    从任意事件数据中提取 ≤100 字的状态摘要。
    处理 dict / str / list / 其他 等多种格式。
    """
    # 1. dict 类型：提取关键字段
    if isinstance(event_data, dict):
        # 优先字段（按重要性排序）
        for key in ("summary", "status", "state", "result", "message",
                    "content", "data", "description", "error", "tool_name"):
            if key in event_data and event_data[key] is not None:
                val = str(event_data[key])
                if val:
                    return val[:100] if len(val) <= 100 else val[:97] + "..."

        # 无关键字段，取前 3 个键值对
        items = []
        for k, v in list(event_data.items())[:3]:
            v_str = str(v)
            if len(v_str) > 30:
                v_str = v_str[:27] + "..."
            items.append(f"{k}={v_str}")
        summary = ", ".join(items)
        return summary[:100] if len(summary) <= 100 else summary[:97] + "..."

    # 2. list 类型：取前 2 个元素
    if isinstance(event_data, list):
        items = [str(x)[:40] for x in event_data[:2]]
        summary = f"[{len(event_data)}项] " + " | ".join(items)
        return summary[:100] if len(summary) <= 100 else summary[:97] + "..."

    # 3. 字符串：直接使用
    if isinstance(event_data, str):
        return event_data[:100] if len(event_data) <= 100 else event_data[:97] + "..."

    # 4. 其他：转字符串
    s = str(event_data)
    return s[:100] if len(s) <= 100 else s[:97] + "..."


# ═══════════════════════════════════════════════════════════════════════════════
# VectorStore 接口
# ═══════════════════════════════════════════════════════════════════════════════

async def _get_vector_store():
    """获取 VectorStore 实例（复用 MemoryService 的延迟初始化）"""
    from core.memory.memory_service import get_memory_service
    memory_service = await get_memory_service()
    return memory_service.vector_store


def _build_vector_text(module_id: str, summary: str) -> str:
    """构建用于向量化的文本"""
    return f"{module_id} {summary}"


# ═══════════════════════════════════════════════════════════════════════════════
# 公开 API
# ═══════════════════════════════════════════════════════════════════════════════

async def update_module_state(module_id: str, summary: str) -> str | None:
    """
    更新模块状态摘要（手动调用或自动采集器调用）。

    Args:
        module_id: 模块唯一标识，如 "trading.auto_trader"
        summary: ≤100 字的状态摘要

    Returns:
        记录 ID 或 None（VectorStore 未就绪时仅缓存，不失败）
    """
    global _module_state_cache
    _module_state_cache[module_id] = {
        "summary": summary,
        "updated_at": datetime.now().isoformat(),
    }

    try:
        store = await _get_vector_store()
        vector_text = _build_vector_text(module_id, summary)
        metadata = {
            "module_id": module_id,
            "updated_at": datetime.now().isoformat(),
            "summary": summary,
        }
        return await store.upsert(
            collection=MODULE_STATE_COLLECTION,
            doc_id=module_id,
            text=vector_text,
            metadata=metadata,
        )
    except Exception as e:
        logger.debug(
            f"[ModuleStateManager] VectorStore 写入失败（已缓存至内存）: {e}"
        )
        return None


def get_module_state_cache_snapshot() -> dict[str, dict[str, Any]]:
    """返回当前内存中的模块状态缓存副本（供自我意识读取）。"""
    return dict(_module_state_cache)


def get_recent_module_states(limit: int = 20) -> list[dict[str, Any]]:
    """按时间倒序返回最近的模块状态摘要。"""
    items = sorted(
        _module_state_cache.items(),
        key=lambda x: x[1].get("updated_at", ""),
        reverse=True,
    )[:limit]
    return [
        {"module_id": mid, "summary": data.get("summary", ""), "updated_at": data.get("updated_at", "")}
        for mid, data in items
    ]


async def search_module_states(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """
    语义搜索模块状态。

    Args:
        query: 用户输入或任务描述
        limit: 最多返回几条

    Returns:
        模块状态字典列表，每项含 module_id, summary, updated_at, distance
        内存缓存中的最新状态会覆盖 VectorStore 中的旧状态
    """
    global _module_state_cache

    results: list[dict[str, Any]] = []

    # 1. 从 VectorStore 搜索
    try:
        store = await _get_vector_store()
        store_results = await store.search(
            collection=MODULE_STATE_COLLECTION,
            query=query,
            limit=limit,
        )
        for r in store_results:
            if not r.metadata:
                continue
            module_id = r.metadata.get("module_id", r.id)
            # 内存缓存优先
            cached = _module_state_cache.get(module_id)
            if cached:
                results.append({
                    "module_id": module_id,
                    "summary": cached["summary"],
                    "updated_at": cached["updated_at"],
                    "distance": r.distance,
                })
            else:
                results.append({
                    "module_id": module_id,
                    "summary": r.metadata.get("summary", r.document),
                    "updated_at": r.metadata.get("updated_at", ""),
                    "distance": r.distance,
                })
    except Exception as e:
        logger.debug(f"[ModuleStateManager] VectorStore 搜索失败: {e}")

    # 2. VectorStore 失败或未返回足够结果时，回退到内存缓存扫描
    if not results and _module_state_cache:
        cached_items = sorted(
            _module_state_cache.items(),
            key=lambda x: x[1].get("updated_at", ""),
            reverse=True,
        )[:limit]
        for module_id, data in cached_items:
            results.append({
                "module_id": module_id,
                "summary": data["summary"],
                "updated_at": data["updated_at"],
                "distance": None,
            })

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# 自动状态采集器 — 全局覆盖核心
# ═══════════════════════════════════════════════════════════════════════════════

class AutoStateCollector:
    """
    自动状态采集器
    订阅 EventBus 所有事件，智能提取模块状态摘要。
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._subscribe()
        logger.info("[AutoStateCollector] 全局自动状态采集器已启动")

    def _subscribe(self):
        """通配订阅所有 EventBus 事件"""
        try:
            event_bus.on_all(
                self._on_any_event,
                priority=EventPriority.LOW,  # 低优先级，不影响其他处理器
            )
        except Exception as e:
            logger.warning(f"[AutoStateCollector] EventBus 订阅失败: {e}")

    def _on_any_event(self, event):
        """处理所有事件：推断模块 → 提取摘要 → 更新状态（带防抖）"""
        # 跳过模块状态更新事件本身（避免循环）
        if event.name == "module.state_update":
            return

        # 推断模块 ID
        module_id = _infer_module_from_event(event.name, getattr(event, "source", ""))
        if not module_id:
            return

        # 防抖：同一 module 5 秒内只更新一次
        now = time.time()
        last_update = _module_state_cache.get(module_id, {}).get("_event_update_ts", 0)
        if now - last_update < 5:
            return

        # 提取摘要
        summary = _auto_summarize(event.name, event.data)
        if not summary:
            return

        # 添加事件名前缀，让摘要更有上下文
        full_summary = f"[{event.name}] {summary}"
        if len(full_summary) > 100:
            full_summary = full_summary[:97] + "..."

        # 记录防抖时间戳
        _set_cache(module_id, {
            "summary": full_summary,
            "updated_at": datetime.now().isoformat(),
            "_event_update_ts": now,
        })

        # fire-and-forget 异步更新（受跟踪，避免 pending task 泄漏）
        _spawn_module_state_task(module_id, full_summary)


def get_auto_state_collector() -> AutoStateCollector:
    """获取自动状态采集器单例"""
    return AutoStateCollector()


# ═══════════════════════════════════════════════════════════════════════════════
# 工具执行后自动更新（供 ToolHook 调用）
# ═══════════════════════════════════════════════════════════════════════════════

_TOOL_MODULE_PREFIX_MAP = [
    ("trading_", "trading.execution"),
    ("btc_", "trading.market_data"),
    ("order_", "trading.execution"),
    ("position_", "trading.portfolio"),
    ("memory_", "memory.manager"),
    ("pixel_", "vision.perception"),
    ("screen_", "vision.perception"),
    ("visual_", "vision.perception"),
    ("ocr_", "vision.perception"),
    ("system_", "sensors.system"),
    ("window_", "sensors.system"),
    ("process_", "sensors.system"),
    ("voice_", "voice.processor"),
    ("config_", "config.manager"),
    ("prompt_", "prompt.manager"),
    ("task_", "task.manager"),
    ("workflow_", "workflow.executor"),
    ("cloud_", "cloud.api"),
]


def _infer_module_from_tool(tool_id: str) -> str:
    """根据工具名推断模块 ID"""
    for prefix, module_id in _TOOL_MODULE_PREFIX_MAP:
        if tool_id.startswith(prefix):
            return module_id
    # 特殊工具名
    if tool_id in ("get_price", "market_data", "get_ticker"):
        return "trading.market_data"
    if tool_id in ("launch_app", "click_element", "type_text"):
        return "system.automation"
    return f"tool.{tool_id}"


def update_module_state_from_tool(tool_id: str, result: Any) -> None:
    """
    工具执行后自动更新模块状态（供 ToolHook 调用）。
    同步入口，内部转异步任务，不阻塞 ToolHook。
    """
    module_id = _infer_module_from_tool(tool_id)

    # 防抖：同一 module 5 秒内跳过
    now = time.time()
    last = _module_state_cache.get(module_id, {}).get("_tool_update_ts", 0)
    if now - last < 5:
        return

    # 提取执行结果摘要
    success = False
    data_str = ""
    if isinstance(result, dict):
        success = result.get("success", False)
        for key in ("result", "data", "output", "message", "content"):
            if key in result and result[key] is not None:
                val = str(result[key])
                if val:
                    data_str = val[:40] + "..." if len(val) > 40 else val
                    break
        if not data_str and "error" in result:
            err = str(result["error"])
            data_str = f"错误:{err[:30]}" if len(err) > 30 else f"错误:{err}"
    else:
        data_str = str(result)[:40]

    status = "成功" if success else "失败"
    summary = f"工具={tool_id} | 结果={status}"
    if data_str:
        summary += f" | {data_str}"
    if len(summary) > 100:
        summary = summary[:97] + "..."

    # 记录防抖时间戳
    _set_cache(module_id, {
        "summary": summary,
        "updated_at": datetime.now().isoformat(),
        "_tool_update_ts": now,
    })

    # fire-and-forget 异步更新（受跟踪，避免 pending task 泄漏）
    _spawn_module_state_task(module_id, summary)


# ═══════════════════════════════════════════════════════════════════════════════
# 初始化：启动自动采集器
# ═══════════════════════════════════════════════════════════════════════════════

# 导入时自动启动（单例，无副作用）
_auto_collector = get_auto_state_collector()
