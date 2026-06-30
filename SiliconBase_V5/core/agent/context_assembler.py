"""
ContextAssembler - Prompt 上下文组装器
V5/V6 融合重构 - Phase 2a

职责：将记忆检索、TokenBudget 等上下文碎片组装成最终 system prompt。
同步/异步双入口，业务逻辑以同步版为准。

同步/异步语义统一决策记录（Phase 2a）：
1. L1 检索：统一使用同步版逻辑（limit=10，仅查当前 session）。异步版原先分两次查询（session内+session外）的扩展逻辑废弃，避免重复查询。
2. L2/L3 检索：统一使用 `memory.retrieve_memories()` 智能检索接口。异步版原先使用的 `MemoryQuery + query_advanced` 废弃，降低接口差异。
3. L4 向量检索：统一使用同步版逻辑（仅 round_count<=1 时执行，ThreadPoolExecutor+3秒超时，limit=1）。异步版原先缺少的轮次限制和超时保护补齐。
4. 异常处理：统一使用同步版策略（`MemoryRetrievalError` 及通用异常均 raise），异步版原先静默吞掉异常的策略废弃，确保问题可感知。
5. TokenBudget：异步版通过调用 `build_system_prompt_with_budget()` 自动获得与同步版一致的预算控制能力，禁止在主循环体里直接复制逻辑。
"""

import datetime
import time
from typing import Any

from core.agent.phase_context import PhaseContext
from core.agent.phase_registry import register_phase

# TokenBudget 相关导入
from core.cost.token_budget_integration import (
    build_context_with_budget,
    prepare_context_components,
)
from core.logger import logger
from core.memory.execution_memory import execution_memory
from core.memory.formatter import format_memories_as_subconscious

# 记忆相关导入
from core.memory.memory_service import MemoryRetrievalError
from core.reflector.three_views_generator import get_three_views_generator


class ContextAssembler:
    """Prompt 上下文组装器

    统一异步入口 assemble_memory_context()（同步版已删除），
    以及 build_system_prompt_with_budget() 统一封装 TokenBudget 调用。
    """

    def __init__(self, runtime: Any | None = None, hooks: Any | None = None):
        self.runtime = runtime
        self.hooks = hooks

    # ═════════════════════════════════════════════════════════════════════════════
    # 记忆检索 - 异步版（当前底层无真正异步实现，保留 async 入口供未来扩展）
    # ═════════════════════════════════════════════════════════════════════════════
    async def assemble_memory_context(
        self,
        task: Any,
        working_memory: Any,
        session_id: str,
        user_id: str,
        loop_state: Any,
        execution_history: list[dict[str, Any]] | None = None,
    ) -> tuple[str, dict]:
        """组装记忆上下文（L1-L5 检索）。同步版已删除，统一为单一异步入口。"""
        from core.memory.memory_service import get_memory_service
        memory_service = await get_memory_service()

        memory_context = ""
        metadata = {}

        # 【L0 模块状态】提取用户指令
        user_instruction = ""
        try:
            if task and hasattr(task, '_runtime_state'):
                user_instruction = getattr(task._runtime_state, 'user_instruction', '')
            if not user_instruction and task and hasattr(task, 'intent'):
                intent = getattr(task, 'intent', None) or {}
                if isinstance(intent, dict):
                    user_instruction = intent.get('raw', '')
        except Exception as e:
            logger.error(f"[ContextAssembler] 获取用户指令失败: {e}", exc_info=True)

        try:
            # 【HIGH-3】L0 模块状态：语义召回相关模块的实时摘要（移至 L1 之前，独立 try-except）
            l0_module_states = ""
            try:
                if user_instruction:
                    from core.memory.module_state_manager import search_module_states
                    states = await search_module_states(user_instruction, limit=5)
                    if states:
                        state_lines = []
                        for s in states:
                            module_id = s.get('module_id', '')
                            summary = s.get('summary', '')
                            if module_id and summary:
                                state_lines.append(f"{module_id}:{summary}")
                        if state_lines:
                            l0_module_states = "[模块状态]" + "; ".join(state_lines)
                            logger.info(f"[ContextAssembler] L0 模块状态召回: {len(state_lines)}个模块")
                            logger.debug(f"[Diag] L0 module state retrieved: {len(state_lines)} modules")
                        else:
                            logger.debug("[Diag] L0 module state: none retrieved")
            except Exception as e:
                logger.debug(f"[ContextAssembler] L0 模块状态检索失败: {e}")
                logger.debug(f"[Diag] L0 module state retrieval failed: {e}")

            # L1 短期记忆
            # VERIFIED-ASYNC: query_memories 使用 asyncpg，真异步 I/O
            l1_memories = await memory_service.query_memories(
                user_id=user_id,
                layer="short",
                limit=10,
                filter_dict={"session_id": session_id},
            )

            # L2 中期记忆：智能检索
            try:
                # ASYNC-DEBT: L2 仍走 AsyncMemory 语义检索，待替换为 MemoryService.retrieve_context
                l2_memories = await memory_service.query_memories(
                    user_id=user_id,
                    mem_type="experience",
                    limit=5,
                )
                logger.info(f"[ContextAssembler] L2智能检索成功: {len(l2_memories)}条")
            except MemoryRetrievalError as e:
                logger.warning(f"[ContextAssembler] L2 检索失败，降级为空列表: {e}")
                l2_memories = []

            # L3 长期记忆：智能检索
            try:
                # ASYNC-DEBT: L3 仍走 AsyncMemory 语义检索，待替换为 MemoryService.retrieve_context
                l3_memories = await memory_service.query_memories(
                    user_id=user_id,
                    mem_type="knowledge",
                    limit=3,
                )
                logger.info(f"[ContextAssembler] L3智能检索成功: {len(l3_memories)}条")
            except MemoryRetrievalError as e:
                logger.warning(f"[ContextAssembler] L3 检索失败，降级为空列表: {e}")
                l3_memories = []

            # L5 执行统计
            l5_stats_summary = ""
            try:
                uid = user_id if user_id != "console" else "default_user"
                l5_stats = await execution_memory.get_execution_stats_async(uid, days=7)
                if l5_stats:
                    tool_stats = l5_stats.get("tool_stats", {})
                    if tool_stats:
                        top_tools = sorted(
                            tool_stats.items(),
                            key=lambda x: x[1].get("count", 0),
                            reverse=True,
                        )[:3]
                        l5_stats_summary = "; ".join([
                            f"{tool[0]}:{tool[1].get('success_rate', 0):.0%}"
                            for tool in top_tools
                        ])
            except Exception as e:
                logger.warning(f"[ContextAssembler] L5统计获取失败: {e}")

            # 【P1-2】L5 决策历史：从 decisions collection 检索过去类似任务的决策
            l5_decisions = ""
            try:
                if user_instruction and hasattr(memory_service, 'vector_store') and memory_service.vector_store:
                    decision_results = await memory_service.vector_store.search(
                        "decisions", user_instruction, limit=3
                    )
                    if decision_results:
                        decision_lines = []
                        for r in decision_results[:3]:
                            if not r.metadata:
                                continue
                            ctx = r.metadata.get("context", {}) or {}
                            q = ctx.get("query", "")
                            d = ctx.get("decision", "")
                            reason = ctx.get("reasoning", "")
                            if d:
                                line = f"过去遇到'{q[:30]}...'时，决策: {d}"
                                if reason:
                                    line += f" | 思考: {reason[:40]}"
                                decision_lines.append(line)
                        if decision_lines:
                            l5_decisions = "├─ L5决策(" + str(len(decision_lines)) + "条): " + " | ".join(decision_lines)
                            logger.info(f"[ContextAssembler] L5 决策历史召回: {len(decision_lines)}条")
            except Exception as e:
                logger.debug(f"[ContextAssembler] L5决策历史检索失败: {e}")

            # 构建记忆上下文
            memory_parts = []
            uid = user_id if user_id != "console" else "default_user"

            # L1：优先从 L5 执行记忆读取近期关键操作，回退到对话摘要
            l1_display = ""

            # 尝试从 L5 读取当前 session 的最近工具执行记录
            session_executions = []
            try:
                recent_execs = await execution_memory.get_recent_executions_async(uid, limit=10)
                if recent_execs:
                    session_executions = [
                        r for r in recent_execs
                        if r.get("session_id") == session_id
                    ][:3]
            except Exception as e:
                logger.debug(f"[ContextAssembler] L5执行记忆读取失败: {e}")

            # RuleManager 学习规则检索（L5决策历史之后插入）
            learned_rules: list[dict[str, Any]] = []
            try:
                if user_instruction:
                    from core.strategy.goal_system import get_goal_system
                    from core.strategy.rule_manager import RuleManager
                    rule_manager = RuleManager()
                    _rule_history = execution_history if execution_history else session_executions
                    recent_tool_names = [
                        (h.get("tool") or h.get("tool_name", ""))
                        for h in _rule_history
                        if (h.get("tool") or h.get("tool_name"))
                    ]
                    active_goal = get_goal_system().get_top_priority_goal()
                    goal_text = ""
                    if active_goal and hasattr(active_goal, "description"):
                        goal_text = str(active_goal.description)[:80]
                    query_parts = [user_instruction]
                    if recent_tool_names:
                        query_parts.append(f"tools: {','.join(recent_tool_names[:3])}")
                    if goal_text:
                        query_parts.append(f"goal: {goal_text}")
                    query = " | ".join(query_parts)
                    rules = await rule_manager.search_rules(query, limit=3)
                    learned_rules = [
                        r for r in rules
                        if r.get("confidence", 0.0) >= 0.65
                    ][:3]
                    if learned_rules:
                        logger.info(f"[ContextAssembler] 学习规则召回: {len(learned_rules)}条")
            except Exception as e:
                logger.debug(f"[ContextAssembler] 学习规则检索失败: {e}")

            if session_executions:
                # 【P1改造】L1短期记忆改为操作事件流：AI知道做过什么、为什么做、结果如何
                exec_lines = ["【近期操作】"]
                for r in session_executions:
                    # 时间戳格式化
                    ts_raw = r.get("timestamp")
                    time_str = "未知"
                    try:
                        if isinstance(ts_raw, str):
                            ts_dt = datetime.fromisoformat(ts_raw)
                            time_str = ts_dt.strftime("%H:%M:%S")
                        elif isinstance(ts_raw, datetime):
                            time_str = ts_raw.strftime("%H:%M:%S")
                        elif isinstance(ts_raw, (int, float)):
                            time_str = datetime.fromtimestamp(ts_raw).strftime("%H:%M:%S")
                    except Exception as e:
                        logger.error(f"[ContextAssembler] 时间格式化失败 (ts_raw={ts_raw}): {e}", exc_info=True)

                    tool_name = r.get("tool_name", "unknown")

                    # 简化参数表示
                    params = r.get("input_params", {})
                    if params and isinstance(params, dict):
                        param_items = []
                        for k, v in list(params.items())[:2]:
                            v_str = str(v)
                            if len(v_str) > 20:
                                v_str = v_str[:20] + "..."
                            param_items.append(f'{k}="{v_str}"' if isinstance(v, str) else f'{k}={v_str}')
                        param_str = ", ".join(param_items)
                    else:
                        param_str = ""

                    # 结果格式化（成功时尝试提取返回值，失败时显示错误）
                    success = r.get("success", False)
                    if success:
                        result_str = "成功"
                        output = r.get("output_result", {})
                        if isinstance(output, dict):
                            for key in ("result", "value", "price", "data", "text", "content", "output"):
                                if key in output and output[key] is not None:
                                    val_str = str(output[key])
                                    if len(val_str) > 30:
                                        val_str = val_str[:30] + "..."
                                    result_str += f"，返回{val_str}"
                                    break
                        elif isinstance(output, str) and output:
                            val_str = output[:30] + "..." if len(output) > 30 else output
                            result_str += f"，返回{val_str}"
                    else:
                        err = r.get("error_message") or r.get("error_code") or "失败"
                        err_str = str(err)
                        if len(err_str) > 30:
                            err_str = err_str[:30] + "..."
                        result_str = f"失败({err_str})"

                    # 原因推断（启发式，根据工具类型和上下文）
                    reason = "用户请求"
                    if tool_name.startswith(("btc_", "get_price", "market_data", "trading_")):
                        reason = "交易循环"
                    elif tool_name in ("pixel_capture", "ocr_text", "screen_ocr", "visual_understand"):
                        reason = "自动验证"
                    elif tool_name in ("system_info", "window_get", "process_start", "process_kill"):
                        reason = "系统监控"
                    elif tool_name in ("memory_add", "memory_search", "memory_list"):
                        reason = "记忆管理"

                    line = f'{time_str} | {tool_name}({param_str}) → {result_str} | 原因:{reason}'
                    exec_lines.append(line)

                l1_display = "\n".join(exec_lines)
            elif l1_memories:
                user_msgs = [m for m in l1_memories if m.get("role") == "user"]
                ai_msgs = [m for m in l1_memories if m.get("role") == "assistant"]
                recent_msgs = l1_memories[:6]
                l1_summary = []
                for m in recent_msgs:
                    role = "U" if m.get("role") == "user" else "A"
                    raw_content = m.get("content", "")
                    if isinstance(raw_content, str):
                        content = raw_content[:30]
                        content_full = raw_content
                    elif raw_content is None:
                        content = ""
                        content_full = ""
                        logger.warning("[ContextAssembler] L1记忆content为None")
                    else:
                        try:
                            content = str(raw_content)[:30]
                            content_full = str(raw_content)
                            logger.info(f"[ContextAssembler] L1记忆content非字符串, 已转换: {type(raw_content).__name__}")
                        except Exception as e:
                            content = "[内容异常]"
                            content_full = "[内容异常]"
                            logger.error(f"[ContextAssembler] L1记忆content转换失败: {e}")
                    l1_summary.append(f"[{role}] {content}{'...' if len(content_full) > 30 else ''}")
                l1_display = f"L1短期({len(user_msgs)}U/{len(ai_msgs)}A轮): " + " | ".join(l1_summary)

            if l0_module_states:
                memory_parts.append(f"┌─ {l0_module_states}")

            if l1_display:
                memory_parts.append(f"┌─ {l1_display}")

            # L2
            if l2_memories:
                l2_summary = []
                for m in l2_memories[:3]:
                    raw_content = m.get("content", "")
                    if isinstance(raw_content, str):
                        content = raw_content[:40]
                        content_full = raw_content
                    elif raw_content is None:
                        content = ""
                        content_full = ""
                        logger.warning("[ContextAssembler] L2记忆content为None")
                    else:
                        try:
                            content = str(raw_content)[:40]
                            content_full = str(raw_content)
                            logger.info(f"[ContextAssembler] L2记忆content非字符串, 已转换: {type(raw_content).__name__}")
                        except Exception as e:
                            content = "[内容异常]"
                            content_full = "[内容异常]"
                            logger.error(f"[ContextAssembler] L2记忆content转换失败: {e}")
                    l2_summary.append(content + ('...' if len(content_full) > 40 else ''))
                memory_parts.append("├─ L2今日(" + str(len(l2_memories)) + "条): " + " | ".join(l2_summary))

            # L3
            if l3_memories:
                l3_summary = []
                for m in l3_memories[:2]:
                    raw_content = m.get("content", "")
                    if isinstance(raw_content, str):
                        content = raw_content
                    elif raw_content is None:
                        content = ""
                        logger.warning("[ContextAssembler] L3记忆content为None")
                    else:
                        try:
                            content = str(raw_content)
                            logger.info(f"[ContextAssembler] L3记忆content非字符串, 已转换: {type(raw_content).__name__}")
                        except Exception as e:
                            content = "[内容异常]"
                            logger.error(f"[ContextAssembler] L3记忆content转换失败: {e}")
                    mem_type = m.get("type", "unknown")
                    prefix = "[萃取]" if mem_type == "extracted_pattern" else ""
                    display = prefix + content[:50] + ('...' if len(content) > 50 else '')
                    l3_summary.append(display)
                memory_parts.append("├─ L3策略(" + str(len(l3_memories)) + "条): " + " | ".join(l3_summary))

            # L5
            if l5_stats_summary:
                memory_parts.append(f"├─ L5统计: {l5_stats_summary}")

            # 【P1-2】L5 决策历史
            if l5_decisions:
                memory_parts.append(l5_decisions)

            # 学习规则（置信度>=0.65，最多3条）
            if learned_rules:
                rule_lines = [
                    f"{r.get('condition', '')} → {r.get('action', '')} [{r.get('confidence', 0.0):.0%}]"
                    for r in learned_rules
                ]
                memory_parts.append(f"├─ 规则({len(rule_lines)}条): " + " | ".join(rule_lines))

            # L4 经验记忆（PG 查询替代向量搜索，已删除 to_thread 桥接）
            # ASYNC-DEBT: 原 vector_memory.search_experience 语义检索待替换为 MemoryService.retrieve_context
            l4_memories = []
            l4_results = []
            round_count = getattr(loop_state, "round_count", 0) if loop_state else 0
            # === 改造：每5轮检索一次 L4，长任务强制检索 ===
            should_query_l4 = (round_count <= 1) or (round_count % 5 == 0)
            if should_query_l4:
                try:
                    l4_results = await memory_service.query_memories(
                        user_id=user_id,
                        layer="evolve",
                        limit=5,  # 从2条增加到5条
                    )
                    if l4_results:
                        for r in l4_results[:5]:
                            content = r.get("content", "")
                            if isinstance(content, dict):
                                content = content.get("text", str(content))
                            prefix = "✓ "
                            display = content[:200] + "..." if len(content) > 200 else content
                            l4_memories.append(f"{prefix}{display}")
                except Exception as e:
                    logger.warning(f"[ContextAssembler] L4经验记忆检索失败: {e}")
            else:
                logger.debug(f"[ContextAssembler] 轮次{round_count}，跳过L4检索（每5轮触发）")

            if l4_memories:
                memory_parts.append(
                    "└─ L4向量(" + str(len(l4_results)) + "条): " + " | ".join(
                        [m[:60] + '...' if len(m) > 60 else m for m in l4_memories]
                    )
                )

            # 保存记忆元数据
            try:
                metadata = {
                    "l1_count": len(l1_memories) if l1_memories else 0,
                    "l2_count": len(l2_memories) if l2_memories else 0,
                    "l3_count": len(l3_memories) if l3_memories else 0,
                    "l4_count": len(l4_results) if l4_results else 0,
                    "l1_ids": [m.get("id") for m in l1_memories if m.get("id")] if l1_memories else [],
                    "l2_ids": [m.get("id") for m in l2_memories if m.get("id")] if l2_memories else [],
                    "l3_ids": [m.get("id") for m in l3_memories if m.get("id")] if l3_memories else [],
                    "l4_ids": [r.get("id") for r in l4_results if r.get("id")] if l4_results else [],
                    "l1_types": list({m.get("mem_type", "chat") for m in l1_memories}) if l1_memories else [],
                    "l2_types": list({m.get("mem_type", "experience") for m in l2_memories}) if l2_memories else [],
                    "l3_types": list({m.get("mem_type", "strategy") for m in l3_memories}) if l3_memories else [],
                    "l4_types": list({r.get("metadata", {}).get("type", "experience") for r in l4_results}) if l4_results else [],
                    "timestamp": time.time(),
                }
                logger.info(
                    f"[ContextAssembler] 记忆元数据已保存: "
                    f"L1={metadata['l1_count']}, L2={metadata['l2_count']}, "
                    f"L3={metadata['l3_count']}, L4={metadata['l4_count']}"
                )
            except Exception as e:
                logger.error(f"[ContextAssembler] 保存记忆元数据失败: {e}", exc_info=True)
                metadata = {}

            # 根据工作模式选择格式化方式
            current_mode = getattr(working_memory, "mode", "daily")
            if current_mode == "focus":
                all_memories = []
                for m in (l1_memories[:3] if l1_memories else []):
                    all_memories.append({"content": m.get("content", ""), "mem_type": "chat", "source": "L1"})
                for m in (l2_memories[:2] if l2_memories else []):
                    all_memories.append({"content": m.get("content", ""), "mem_type": m.get("mem_type", "experience"), "source": "L2"})
                for m in (l3_memories[:2] if l3_memories else []):
                    all_memories.append({"content": m.get("content", ""), "mem_type": m.get("mem_type", "knowledge"), "source": "L3"})
                for m in (l4_results[:2] if l4_results else []):
                    all_memories.append({"content": m.get("content", ""), "mem_type": "experience", "source": "L4"})
                memory_context = format_memories_as_subconscious(all_memories, mode="focus")
                if memory_context:
                    logger.debug(f"[ContextAssembler] 专注模式-潜意识记忆流: {len(all_memories)}条记忆")
            elif memory_parts:
                memory_context = "【记忆上下文】\n" + "\n".join(memory_parts)
                logger.debug(
                    f"[ContextAssembler] 记忆检索: "
                    f"L1={len(l1_memories)}, L2={len(l2_memories)}, L3={len(l3_memories)}, "
                    f"L4={len(l4_memories)}, L5={'有' if l5_stats_summary else '无'}"
                )
            else:
                memory_context = ""

            # === 新增：注入全局背景（从 L4 evolve 层提取）===
            try:
                global_ctx = await self._extract_global_context(user_id)
                if any(global_ctx.values()):
                    global_section = (
                        f"【全局背景】\n"
                        f"项目目标: {global_ctx['project_goal'] or '未设定'}\n"
                        f"历史决策: {global_ctx['historical_major_decisions'] or '无'}\n"
                        f"用户偏好: {global_ctx['user_long_term_preference'] or '暂无'}"
                    )
                    memory_context = global_section + "\n\n" + memory_context if memory_context else global_section
            except Exception as e:
                logger.debug(f"[ContextAssembler] 全局背景提取失败: {e}")

            # 追加交易上下文（来自加密货币指挥官AI）
            try:
                trading_context = await self.assemble_trading_context(user_id)
                if trading_context:
                    if memory_context:
                        memory_context += "\n\n" + trading_context
                    else:
                        memory_context = trading_context
                    logger.debug(f"[ContextAssembler] 交易上下文已追加: {trading_context[:50]}...")
            except Exception as e:
                logger.error(f"[ContextAssembler] 交易上下文追加失败: {e}", exc_info=True)

        except MemoryRetrievalError:
            raise
        except Exception as e:
            logger.error(f"[ContextAssembler] 记忆检索未知错误: {e}", exc_info=True)
            raise MemoryRetrievalError(f"获取上下文记忆失败: {e}") from e

        return memory_context, metadata

    async def _extract_global_context(self, user_id: str) -> dict[str, str]:
        """【新增】从 L4 evolve 层提取全局背景：项目定位、长期目标、重大决策"""
        global_context = {
            "project_goal": "",
            "user_long_term_preference": "",
            "historical_major_decisions": ""
        }
        try:
            from core.memory.memory_service import get_memory_service
            memory_service = await get_memory_service()
            global_memories = await memory_service.query_memories(
                user_id=user_id,
                layer="evolve",
                limit=10,
            )
            goals = []
            decisions = []
            preferences = []
            for mem in global_memories:
                content = str(mem.get("content", ""))
                mem.get("tags", []) or []
                if any(kw in content for kw in ["项目目标", "核心使命", "长期目标"]):
                    goals.append(content[:100])
                elif any(kw in content for kw in ["重大决策", "关键选择", "战略调整"]):
                    decisions.append(content[:100])
                elif any(kw in content for kw in ["用户偏好", "习惯", "常用"]):
                    preferences.append(content[:100])
            global_context["project_goal"] = " | ".join(goals[:3])
            global_context["historical_major_decisions"] = " | ".join(decisions[:3])
            global_context["user_long_term_preference"] = " | ".join(preferences[:3])
        except Exception as e:
            logger.debug(f"[ContextAssembler] 全局背景提取失败: {e}")
        return global_context

    # ═════════════════════════════════════════════════════════════════════════════
    # Phase 2b：三观 + 反思 + 经验注入上下文组装
    # ═════════════════════════════════════════════════════════════════════════════
    async def assemble_three_views(
        self,
        task: Any,
        user_id: str,
        working_memory: Any,
        user_instruction: str,
        task_type: str,
    ) -> str:
        """组装三观提示词，包含 working_memory 缓存机制。"""
        three_views_prompt = ""
        try:
            three_views_generator = get_three_views_generator(user_id)

            action_context = None
            if task and hasattr(task, 'tool_calls') and task.tool_calls:
                action_context = {
                    "action_type": task.tool_calls[-1].tool,
                    "action_params": getattr(task.tool_calls[-1], 'params', {})
                }

            if not hasattr(working_memory, '_three_views_cache'):
                working_memory._three_views_cache = {}

            cache_key = f"{user_id}_{hash(str(three_views_generator.user_config))}"

            if cache_key not in working_memory._three_views_cache:
                three_views_prompt = three_views_generator.generate_all(
                    action_context=action_context,
                    task_context={"task": user_instruction, "task_type": task_type},
                    perception_context=None
                )
                working_memory._three_views_cache[cache_key] = three_views_prompt
                logger.debug(f"[ContextAssembler-ThreeViews] 三观提示词已生成并缓存，用户: {user_id}")
            else:
                three_views_prompt = working_memory._three_views_cache[cache_key]
                logger.debug(f"[ContextAssembler-ThreeViews] 使用缓存的三观提示词，用户: {user_id}")
        except Exception as e:
            logger.warning(f"[ContextAssembler-ThreeViews] 生成三观提示词失败: {e}")
        return three_views_prompt

    async def assemble_reflection_context(
        self,
        reflection_context: str,
        belief_confidence: float,
        strategy_recommendation: str,
        user_id: str = "default",
    ) -> str:
        """组装反思上下文（包含贝叶斯信念更新），并检索已验证策略模式。"""
        # === 从 L4 evolve 检索高置信度策略模式 ===
        strategy_patterns_section = ""
        high_conf_count = 0
        try:
            from core.memory.memory_service import get_memory_service
            ms = await get_memory_service()
            patterns = await ms.query_memories(
                user_id="default",
                layer="evolve",
                mem_type="knowledge",
                limit=5,
                min_rating=7,
            )
            if patterns:
                high_conf_patterns = []
                for p in patterns:
                    if not isinstance(p, dict):
                        continue
                    # 过滤 source 为 reflection 且 rating >= 7 的
                    if p.get("source") == "reflection" and p.get("rating", 0) >= 7:
                        high_conf_patterns.append(p)

                if high_conf_patterns:
                    high_conf_count = len(high_conf_patterns)
                    strategy_patterns_section = "\n### 已验证策略模式（来自反思系统，必须优先参考）\n"
                    for p in high_conf_patterns[:3]:
                        content = p.get("content", "")
                        desc = content
                        if isinstance(content, str):
                            try:
                                import json
                                content_data = json.loads(content)
                                desc = content_data.get("description", content)
                            except Exception as e:
                                logger.error(f"[ContextAssembler] 策略模式内容JSON解析失败: {e}", exc_info=True)
                        strategy_patterns_section += f"- [置信度{p.get('rating', 0)}/10] {desc}\n"
        except Exception as e:
            logger.debug(f"[ContextAssembler-Reflection] 策略模式检索失败: {e}")

        if not reflection_context and not strategy_patterns_section:
            return ""
        reflection_section = f"""### 实时经验反馈（来自反思系统）
{reflection_context}
{strategy_patterns_section}
### 贝叶斯信念更新（当前策略置信度）
- 当前工具选择策略置信度: {belief_confidence:.2f}
- 推荐策略调整: {strategy_recommendation}

**重要**: 如果反思标记某操作 previously_failed，请先检查条件再执行。
"""
        logger.info(f"[ContextAssembler-Reflection] 反思结果已准备，置信度: {belief_confidence:.2f}, 策略模式: {high_conf_count}条")
        return reflection_section

    async def assemble_experience_context(self, task_description: str = "") -> str:
        """组装经验注入上下文（从记忆层检索真实经验）。"""
        experience_context = ""
        try:
            # 从 L4 evolve 检索相关经验
            from core.memory.memory_service import get_memory_service
            ms = await get_memory_service()
            experiences = await ms.query_memories(
                user_id="default",
                layer="evolve",
                mem_type="experience",
                limit=3,
                min_rating=6,
            )
            if experiences:
                experience_context = "### 历史经验参考\n"
                for exp in experiences:
                    if not isinstance(exp, dict):
                        continue
                    content = exp.get("content", "")
                    desc = content
                    if isinstance(content, str):
                        try:
                            import json
                            content_data = json.loads(content)
                            desc = content_data.get("description", content)
                        except Exception as e:
                            logger.error(f"[ContextAssembler] 经验内容JSON解析失败: {e}", exc_info=True)
                    rating = exp.get("rating", 0)
                    experience_context += f"- [评分{rating}] {desc}\n"
            else:
                experience_context = "[经验注入] 暂无相关经验"
        except Exception as e:
            logger.debug(f"[ContextAssembler-Experience] 经验检索失败: {e}")
            experience_context = "[经验注入] 经验检索暂不可用"
        return experience_context

    async def assemble_realtime_perception(self, user_id: str = "default") -> str | None:
        """组装实时桌面感知上下文。

        从 DialogueManager 的 _user_task_snapshots 中读取实时监控数据，
        格式化为 Prompt 文本返回。如果没有实时监控数据，返回 None。
        """
        try:
            from core.dialog.dialogue_manager import dialogue_manager
            realtime_key = f"{user_id}_realtime"
            snapshot = dialogue_manager._user_task_snapshots.get(realtime_key)
            if not snapshot:
                return None
            timestamp = snapshot.get("timestamp", 0)
            from datetime import datetime
            time_str = datetime.fromtimestamp(timestamp).strftime("%H:%M:%S") if timestamp else "未知"
            layout_summary = snapshot.get("layout_summary", "暂无描述")
            objects = snapshot.get("objects", [])
            objects_text = "\n".join([
                f"  - {obj.get('class', '未知')}: 置信度{obj.get('confidence', 0):.0%}"
                for obj in objects
            ]) if objects else "  （未检测到显著元素）"
            return (
                f"【屏幕实时状态】\n"
                f"最近分析时间：{time_str}\n"
                f"画面内容：{layout_summary}\n"
                f"检测到以下元素：\n{objects_text}"
            )
        except Exception as e:
            logger.debug(f"[ContextAssembler] 实时感知组装失败: {e}")
            return None

    async def assemble_trading_context(self, user_id: str = "default") -> str:
        """组装交易上下文，让主AI感知指挥官AI的活动。

        从主记忆层 L4 evolve 检索最近的交易记录（mem_type="trading"），
        与 ai_trading_commander.py 推送端对齐（layer="evolve", expire_days=None）。
        解包 trading_memory.py 多包装的一层，格式化为交易摘要。
        """
        trading_context = ""
        try:
            from core.memory.memory_service import get_memory_service
            ms = await get_memory_service()
            trades = await ms.query_memories(
                user_id=user_id,
                layer="evolve",
                mem_type="trading",
                limit=5,
            )
            if trades:
                trading_lines = []
                for trade in trades:
                    if not isinstance(trade, dict):
                        continue
                    content = trade.get("content", {})
                    # 解包 trading_memory.py 多包装的一层 {"text": <原始数据>, "memory_type": "general"}
                    actual = content.get("text", content) if isinstance(content, dict) else content

                    if isinstance(actual, dict):
                        symbol = actual.get("symbol", "Unknown")
                        action = actual.get("action", "Unknown")
                        pnl = actual.get("pnl", "N/A")
                        trading_lines.append(f"- [{symbol}] {action}, 盈亏: {pnl}")
                    elif isinstance(actual, str):
                        trading_lines.append(f"- {actual[:50]}")

                if trading_lines:
                    trading_context = "### 近期交易活动（来自加密货币指挥官）\n" + "\n".join(trading_lines)
        except Exception as e:
            logger.debug(f"[ContextAssembler-Trading] 交易上下文检索失败: {e}")
        return trading_context

    # ═════════════════════════════════════════════════════════════════════════════
    # TokenBudget 封装
    # ═════════════════════════════════════════════════════════════════════════════
    def build_system_prompt_with_budget(
        self,
        smart_context: dict[str, str],
        perception_context: str,
        three_views_prompt: str,
        memory_context: str,
        exploration_enhancement: str,
        layer_prompt: str,
        reflection_context: str,
        vision_description: str,
        life_state_context: str,
        user_preference_context: str,
        weak_connection_context: str,
        world_model_section: str,
        phase_context: str,
        execution_history: list[dict],
        experience_context: str = "",
        working_memory: Any | None = None,
    ) -> tuple[str, dict | None]:
        """封装 TokenBudget 的完整调用链路，统一同步/异步双版本的 Prompt 最终组装。

        内部调用 prepare_context_components + build_context_with_budget，
        失败时自动降级为字符串拼接。返回 (full_system_prompt, budget_report_or_none)。

        异步版通过调用此方法自动获得 TokenBudget 能力，禁止在主循环体里直接补齐逻辑。
        """
        budget_report = None
        full_system_prompt = ""

        try:
            context_components = prepare_context_components(
                smart_context=smart_context,
                perception_context=perception_context,
                three_views_prompt=three_views_prompt,
                memory_context=memory_context,
                exploration_enhancement=exploration_enhancement,
                layer_prompt=layer_prompt,
                reflection_context=reflection_context,
                vision_description=vision_description,
                life_state_context=life_state_context,
                user_preference_context=user_preference_context,
                weak_connection_context=weak_connection_context,
                world_model_section=world_model_section,
                phase_context=phase_context,
                execution_history=execution_history,
                experience_context=experience_context,
            )

            full_system_prompt, budget_report = build_context_with_budget(
                context_components=context_components,
                model="default",
            )

            if budget_report and budget_report.allocations:
                logger.info(
                    f"[ContextAssembler-TokenBudget] 上下文构建完成: "
                    f"原始Token={budget_report.total_original_tokens}, "
                    f"截断后Token={budget_report.total_truncated_tokens}, "
                    f"截断次数={sum(1 for a in budget_report.allocations if a.was_truncated)}"
                )

                if working_memory is not None:
                    working_memory.last_token_budget_report = budget_report.to_dict()

            if budget_report and budget_report.errors:
                for error in budget_report.errors:
                    logger.error(f"[ContextAssembler-TokenBudget] 预算控制错误: {error}")

        except Exception as e:
            logger.error(f"[ContextAssembler-TokenBudget] Token预算控制失败，降级到原有方式: {e}", exc_info=True)

            full_system_prompt = smart_context.get("system_prompt", "")

            if perception_context:
                full_system_prompt += "\n\n" + perception_context
            if three_views_prompt:
                full_system_prompt = three_views_prompt + "\n\n" + full_system_prompt
            if memory_context:
                full_system_prompt += "\n\n" + memory_context
            if reflection_context:
                full_system_prompt += "\n\n" + reflection_context
            if exploration_enhancement:
                full_system_prompt += "\n\n" + exploration_enhancement
            if layer_prompt:
                full_system_prompt += "\n\n" + layer_prompt
            if experience_context:
                full_system_prompt += "\n\n" + experience_context
            full_system_prompt += "\n\n" + smart_context.get("reasoning_framework", "")
            if vision_description:
                full_system_prompt += "\n\n" + vision_description
            if life_state_context:
                full_system_prompt += "\n\n" + life_state_context
            if user_preference_context:
                full_system_prompt += "\n\n" + user_preference_context
            if weak_connection_context:
                full_system_prompt += "\n\n" + weak_connection_context
            if world_model_section:
                full_system_prompt += "\n\n" + world_model_section
            if execution_history:
                try:
                    from core.prompt.context_builder import context_compressor
                    exec_summary = context_compressor._summarize_execution(execution_history)
                    if exec_summary:
                        full_system_prompt += "\n\n[执行摘要] " + exec_summary
                except Exception as e:
                    logger.error(f"[ContextAssembler] 执行摘要压缩失败: {e}", exc_info=True)
            if phase_context:
                full_system_prompt += "\n\n" + phase_context

        return full_system_prompt, budget_report.to_dict() if budget_report else None


# 全局实例
context_assembler = ContextAssembler()


async def assemble_context_phase(ctx: PhaseContext):
    """阶段包装：从 phase_ctx 取参，调用 assemble_memory_context"""
    assembler = ContextAssembler(ctx.get("runtime"), ctx.get("hooks"))
    return await assembler.assemble_memory_context(
        task=ctx.task,
        working_memory=ctx.working_memory,
        session_id=ctx.session_id,
        user_id=ctx.user_id,
        loop_state=ctx.loop_state,
        execution_history=ctx.execution_history,
    )


register_phase("context_assembly", assemble_context_phase, order=1)
