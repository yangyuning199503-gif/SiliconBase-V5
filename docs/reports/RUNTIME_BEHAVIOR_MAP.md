# SiliconBase V5 -- 运行时行为地图

> **生成时间**: 2026-05-15
> **方法**: 基于 AST + 源码静态分析的动态行为推导
> **覆盖范围**: 983 Python 文件，2026 类，12325 函数（2158 async）
> **配套报告**: `COMPLETE_PROJECT_MAP_AND_CALL_CHAIN.md`（静态结构）、`MODULE_INVENTORY_AND_AUDIT_REPORT_20260515.md`（模块清单）

---

## 目录

1. [执行摘要](#1-执行摘要)
2. [核心业务调用链](#2-核心业务调用链)
3. [运行时注册机制](#3-运行时注册机制)
4. [数据流与持久化层](#4-数据流与持久化层)
5. [前端-后端 API 契约](#5-前端-后端-api-契约)
6. [已知运行时问题](#6-已知运行时问题)
7. [附录：原始报告文件](#附录原始报告文件)

---

## 1. 执行摘要

本报告补充静态项目地图，聚焦**运行时行为**：调用链深度追踪、事件/工具/API/Hooks 的动态注册、参数数据流、数据库 Schema 以及前后端 API 契约。

| 维度 | 数量 | 说明 |
|------|------|------|
| 追踪调用深度 | L1 -> L18 | PromptFinalizer 最深达第 18 层 |
| 事件订阅 | 27 处 | 含 EventType.* 及自定义事件 |
| 工具注册 | 101 个 | 目标 135 个，34 个为动态加载 |
| FastAPI 路由 | 414 处 | 覆盖 api/ 及 core/ 内嵌路由 |
| Hook 注册 | 33 处 | Phase + AgentLoop Hooks |
| PostgreSQL 表 | 5 张 | 原始 SQL，无 ORM |
| 前端 API 调用 | ~70 处 | frontend/src/utils/api/ 封装 |

**关键发现**:
- `AgentLoop._run_agent_loop_async_impl()` 是核心执行引擎，驱动 `before_prompt` Hook 链 -> AI 调用 -> 工具执行 -> 状态持久化 的完整闭环。
- `PromptFinalizer.finalize()` 接收 20+ 参数，来源横跨 5+ 模块，参数链极长但存在降级兜底。
- `voice_api.py` 前缀为 `/voice`（无 `/api/v1`），前端调用 `/api/v1/voice/status` 存在版本前缀差异。
- `cloud_api.py` 超过 3000 行，含大量内联 handler 和动态路由，静态分析无法完全覆盖。

---

## 2. 核心业务调用链

### 2.1 入口拓扑总览

用户输入有三个入口：`DialogueManager.handle_input()`、WebSocket `/ws`、API `/api/chat`。
经 `Consciousness.orchestrate_input()` 意图分类后，分为 **chat / task / task_control** 三大分支：
- **chat**: 直接 `call_thinker_async()` -> AI 回复 -> TTS 播报
- **task**: `TaskModeRunner` -> `MasterScheduler.dispatch()` -> `AgentLoop` 核心引擎
- **task_control**: 暂停/继续/取消/重试任务控制



### 2.2 入口 1：DialogueManager.handle_input() + 入口 2：AgentLoop._run_agent_loop_async_impl()

以下完整调用链来自子报告 Agent A（已审核）。


# SiliconBase V5 - 跨文件业务调用栈审计报告

> 审计时间: 2026-05-15  
> 审计范围: 2 个入口函数，至少追踪到第 4 层  
> 边界定义: `ai_client.chat_async()` / `tool_manager.execute()` / `event_bus.emit()`

---

## 入口 1: `dialogue_manager.handle_input()`

**文件**: `core/dialog/dialogue_manager.py:3595`
**方法**: `async def handle_input(self, user_id, text, session_id, input_mode=InputMode.AUTO, voice_instance=None)`

```
入口: dialogue_manager.handle_input()
  参数: user_id, text, session_id, input_mode, voice_instance

  L1: get_consciousness(user_id).orchestrate_input(text, context=intent_context)
      → core/consciousness/Consciousness.py (动态导入)
      参数: text, context={chat_history, session_id}
      说明: 意识线程意图判断（AUTO 模式首选）

  L1-alt: classify_user_input(text, has_active_task=has_active)
      → core/constants.py (fallback 路径)
      参数: text, has_active_task
      说明: 意识线程失败时的本地关键词 fallback

  L1: self.get_or_create_session(user_id, session_id)
      → core/dialog/dialogue_manager.py (同文件)
      参数: user_id, session_id

  ── 分支 A: mode == "chat" ─────────────────────────────────────────────
  L2: self._handle_quick_chat(user_id, text, session_id, voice_instance, active_task_hint)
      → core/dialog/dialogue_manager.py:4179
      参数: user_id, text, session_id, voice_instance, active_task_hint

    L3: self.get_or_create_session(user_id, session_id)
        → core/dialog/dialogue_manager.py (同文件)

    L3: call_thinker_async(messages, scene=AIScene.CHAT, hard_timeout=30)
        → core/ai/ai_adapter.py:716
        参数: messages=[system_prompt + chat_history[-6:] + user_msg], scene=CHAT

      L4: asyncio.to_thread(call_thinker, messages, scene, **kwargs)
          → core/ai/ai_adapter.py:738 (线程桥接)

        L5: call_thinker(messages, scene, **kwargs)
            → core/ai/ai_adapter.py:383
            参数: messages, scene=CHAT, hard_timeout=30

          L6: protocol.build_request(...)
              → core/ai/protocol.py (推断)
              参数: request_type="chat", content, context, model_config

          L6: _ai_client.send_request(req)
              → core/ai/ai_client.py:448 (包装器) → ai_client.py:448 (根目录)
              参数: standard_request Dict
              边界: 调用 Provider Factory 后端 (Ollama/OpenAI 等)

          L6-alt: _ai_client.chat_async(messages, **kwargs)
              → ai_client.py:370
              参数: messages
              边界: 异步 AI 调用入口，run_in_executor 桥接同步 provider.chat()

    L3: get_life_presence_manager().announce(EventType.MILESTONE, response, ...)
        → core/consciousness/life_presence.py (动态导入)
        参数: EventType.MILESTONE, response, data={channel, user_id}
        说明: SmartAnnouncer 决定是否语音播报

    L3: voice.speak(response, wait=False)
        → core/voice/voice_engine.py (推断，通过 _get_voice_instance)
        参数: response, wait=False
        边界: TTS 语音播报

  ── 分支 B: mode == "task" ─────────────────────────────────────────────
  L2: self._handle_text_task(user_id, text, session_id, voice_instance, task_plan, context_flag, mode)
      → core/dialog/dialogue_manager.py:4322
      参数: user_id, text, session_id, voice_instance, task_plan, context_flag, mode

    L3: self._start_realtime_monitor(user_id, session_id)
        → core/dialog/dialogue_manager.py:4477
        参数: user_id, session_id
        说明: mode == "start_monitor" 时进入

      L4: DXGICapture(monitor_index=0, capture_rate=30)
          → core/vision/dxgi_capture.py (动态导入)
          参数: monitor_index=0, capture_rate=30
          边界: 实时桌面捕获

    L3: TaskModeRunner().run(text, session_id, voice, chat_history=session.chat_history)
        → core/dialog/chat_mode_handler.py:1047
        参数: task_description=text, session_id, voice_instance, chat_history

      L4: master_scheduler.dispatch(user_request=task_description, task=task, ...)
          → core/agent/master_scheduler.py:147
          参数: user_request, task, chat_history, session_id, voice_instance, mode, db_session_id

        L5: self._execute_core(task_id, context)
            → core/agent/master_scheduler.py:424
            参数: task_id, context={user_request, task, chat_history, ...}

          L6: self._classify_intent(user_request)
              → core/agent/master_scheduler.py (同文件)
              参数: user_request

          L6: self._run_direct(task, user_request, chat_history, ...)
              → core/agent/master_scheduler.py:568
              参数: task, user_request, chat_history, session_id, voice_instance, mode, user_id, db_session_id

            L7: run_agent_loop_async(task, max_rounds=30, chat_history, ...)
                → core/agent/agent_loop.py:3089
                参数: task, max_rounds=30, chat_history, session_id, voice_instance, mode, user_id

              L8: _run_agent_loop_async_impl(task, max_rounds, chat_history, ...)
                  → core/agent/agent_loop.py:674
                  参数: task, max_rounds, chat_history, chat_count, session_id, db_session_id,
                        voice_instance, mode, user_id, stop_event, task_id, resume_from_checkpoint
                  说明: ★ 入口 2 的实际实现，详见下方完整展开

  ── 分支 C: mode == "task_control" ─────────────────────────────────────
  L2: self._handle_task_control(user_id, control_action, text)
      → core/dialog/dialogue_manager.py:3738
      参数: user_id, control_action, original_text=text
      说明: 暂停/继续/取消/重试任务控制

    L3: self.get_active_background_task(user_id)
        → core/dialog/dialogue_manager.py (同文件)

    L3: self._cancel_background_task(user_id)
        → core/dialog/dialogue_manager.py (同文件)

    L3: self.stop_user_loop(user_id)
        → core/dialog/dialogue_manager.py (同文件)
        参数: user_id
        边界: 终止活跃循环锁
```

---

## 入口 2: `agent_loop._run_agent_loop_async_impl()`

**文件**: `core/agent/agent_loop.py:674`
**方法**: `async def _run_agent_loop_async_impl(task, max_rounds, chat_history, chat_count, session_id, db_session_id, voice_instance, mode, user_id, stop_event, task_id, resume_from_checkpoint)`

```
入口: agent_loop._run_agent_loop_async_impl()
  参数: task, max_rounds, chat_history, chat_count, session_id, db_session_id,
        voice_instance, mode, user_id, stop_event, task_id, resume_from_checkpoint

  L1: initialize_loop_state(task, max_rounds, chat_history, ...)
      → core/agent/loop_initialization.py (动态导入)
      参数: task, max_rounds, chat_history, chat_count, session_id, db_session_id,
            voice_instance, mode, user_id, stop_event, task_id, resume_from_checkpoint
      返回: LoopInitResult (包含 working_memory, loop_state, hook_ctx, 等)

  L1: get_memory_service()
      → core/memory/memory_service.py (推断)
      返回: memory_service (用于后续 query_memories / save_chat_turn)

  L1: get_state_persistence()
      → core/state/state_persistence.py (推断)
      返回: state_persistence

  L2: planner.plan_task_async(task_description=user_instruction, context={session_id, mode})
      → core/agent/planner.py (推断，通过 get_planner())
      参数: task_description, context
      说明: 编排插件制定任务规划

  L2: call_thinker_async(msgs, scene=AIScene.CHAT, hard_timeout=15)
      → core/ai/ai_adapter.py:716
      参数: messages, scene=CHAT, hard_timeout=15
      说明: 轻量聊天短路（简单聊天输入时直接返回）
      边界: → call_thinker → _ai_client.send_request / chat_async (同入口1 L3-L6)

  L2: agent_loop_hooks.execute_async('before_round', hook_ctx)
      → core/agent/agent_loop_hooks.py:198
      参数: 'before_round', hook_ctx

  L2: agent_loop_hooks.execute_async('after_round', hook_ctx)
      → core/agent/agent_loop_hooks.py:198
      参数: 'after_round', hook_ctx

  L2: get_phases() → info["handler"](phase_ctx)
      → core/agent/phase_registry.py (动态导入)
      参数: phase_ctx
      说明: PhasePilot 已注册阶段（intent / tool_call / tool_execution / context_assembly）

  L2: _trim_working_memory_async(working_memory)
      → core/agent/agent_loop.py (同文件，或 loop_utils)
      参数: working_memory

  L2: sync.emit_event("step_skipped", session_id, {...})
      → core/sync/realtime_sync.py:132
      参数: event_type, session_id, data
      边界: event_bus.emit() — 事件总线发布

  L2: build_smart_context(user_instruction, working_memory, session_id, mode)
      → core/agent/context_builder.py (推断)
      参数: user_instruction, working_memory, session_id, mode

  L3: agent_loop_hooks.execute_async('before_prompt', hook_ctx)
      → core/agent/agent_loop_hooks.py:198
      参数: 'before_prompt', hook_ctx
      说明: ★ 核心 Hook 链，按 priority 顺序执行以下业务钩子

    L4: hook_intervention_check(ctx)
        → core/agent/hooks/core_logic_hooks.py:29
        触发时机: before_prompt, priority=100
        参数: ctx (含 intervention_checker, pausable_task_sm, state_persistence, state)
        说明: 实时干预检查，若触发则设置 intervention_should_return

      L5: intervention_checker.check_and_apply_async(task_id, working_memory, ...)
          → core/agent/intervention_handler.py (推断)
          参数: task_id, working_memory, session_id, current_plan, pausable_task_sm, state_persistence, state

    L4: hook_perception_inject(ctx)
        → core/agent/hooks/core_logic_hooks.py:75
        触发时机: before_prompt, priority=95
        参数: ctx (含 perception_manager, loop_state, execution_history, work_mode)
        说明: 感知能力激活与注入

      L5: perception_manager.should_trigger_perception(user_instruction, context)
          → core/perception/perception_manager.py (推断)

      L5: perception_manager.get_perception(user_input, context)
          → core/perception/perception_manager.py (推断)

      L5: perception_manager.format_for_prompt(perception)
          → core/perception/perception_manager.py (推断)

    L4: hook_btc_context_inject(ctx)
        → core/agent/hooks/core_logic_hooks.py:316
        触发时机: before_prompt, priority=88
        参数: ctx (含 user_id)
        说明: BTC 交易状态上下文注入（AI 可观测层）

      L5: event_bus.get_summary(user_id)
          → core/btc_integration/event_bus.py (推断)
          参数: user_id
          边界: event_bus 读取

    L4: hook_context_assembly(ctx)
        → core/agent/hooks/core_logic_hooks.py:202
        触发时机: before_prompt, priority=85
        参数: ctx (含 phase_ctx, assembler, user_instruction, task_type, 等)
        说明: Prompt 上下文组装（记忆检索 + TokenBudget + PromptFinalizer）

      L5: assemble_context_phase(phase_ctx)
          → core/agent/context_assembler.py (推断)
          参数: phase_ctx
          返回: memory_context, memory_metadata

      L5: prepare_prompt_fragments_async(phase_ctx)
          → core/agent/prompt_assembly_bridge.py (推断)
          参数: phase_ctx
          返回: PromptFragments (exploration_enhancement, layer_prompt, three_views_prompt, reflection_section, experience_context, world_model_section)

      L5: prompt_finalizer.finalize_async(...)
          → core/prompt/prompt_finalizer.py:194
          参数: user_id, user_instruction, working_memory, work_mode, effective_task_id,
                phase_anchor_manager, last_vision_description, assembler, smart_context,
                perception_context, memory_context, exploration_enhancement, layer_prompt,
                three_views_prompt, reflection_context, experience_context, world_model_section,
                execution_history, session_id, round_count
          说明: 提示词最终组装

        L6: prompt_finalizer.finalize(...)
            → core/prompt/prompt_finalizer.py:67 (推断，被 finalize_async await)
            参数: 同上

  L3: process_vision_perception_async(...)
      → core/vision/vision_processor.py (动态导入)
      参数: user_instruction, change_detector, last_vision_description,
            vision_cache_timestamp, working_memory, user_id, vision_enabled, loop_state
      说明: 视觉感知处理（在 finalize 之后执行，为下一轮缓存 vision 结果）
      边界: 视觉模型调用

  L3: apply_consciousness_analysis(working_memory, execution_history, loop_state)
      → core/consciousness/consciousness_bridge.py (推断)
      参数: working_memory, execution_history, loop_state
      说明: 意识系统分析注入

  L3: context_builder.build_optimized_context(system_prompt, working_memory, execution_history, current_task, chat_history)
      → core/agent/context_builder.py (推断)
      参数: system_prompt=full_system_prompt, working_memory, execution_history, current_task, chat_history

  L3: call_llm_with_retry(messages, hook_ctx, agent_loop_hooks, logger, max_retries=1)
      → core/agent/loop_utils.py:14
      参数: messages, hook_ctx, agent_loop_hooks, logger, max_retries=1
      说明: LLM 调用 + 幻觉检测重试闭环

    L4: call_thinker_async(messages)
        → core/ai/ai_adapter.py:716
        参数: messages
        边界: → call_thinker → _ai_client.send_request / chat_async (同入口1 L3-L6)

    L4: agent_loop_hooks.execute_async_with_signals('after_prompt', hook_ctx, response=response)
        → core/agent/agent_loop_hooks.py:255
        参数: 'after_prompt', hook_ctx, response
        说明: 幻觉检测 Hook（SafetyHook 等注册于此）

    L4: inject_hallucination_prompt("")
        → core/safety/policy.py (动态导入)
        参数: ""
        说明: 幻觉重试时注入约束提示词

  L3: on_ai_response_async(user_id, session_id, text=response, ...)
      → core/memory/memory_trigger.py (推断)
      参数: user_id, session_id, text, thinking, tool_calls, metadata
      说明: AI 回复记忆存储（fire-and-forget 后台任务）
      边界: MemoryService.save_chat_turn()

  L3: session_integration.save_messages_async(session_id, role="assistant", content=response, ...)
      → core/session/session_integration.py (推断)
      参数: session_id, role, content, thinking, tool_calls, metadata
      边界: Session 消息持久化

  L3: precision_parser.process_and_announce(response, True)
      → core/precision/precision_parser.py (推断)
      参数: response, should_announce=True
      说明: 精准抓取解析

  L3: _intent_parser.parse_ai_response(response)
      → core/intent/intent_parser.py (推断)
      参数: response
      返回: ParsedIntent

  L3: extract_natural_language(response)
      → core/utils/text_parser.py (推断)
      参数: response

  L3: sync.emit_event("thinking", session_id, {...})
      → core/sync/realtime_sync.py:132
      参数: event_type="thinking", session_id, data={round, content, intent}
      边界: event_bus.emit()

  ── 意图分支: TOOL_CALL ────────────────────────────────────────────────
  L3: agent_loop_hooks.execute_async('before_tool', hook_ctx, parsed=parsed)
      → core/agent/agent_loop_hooks.py:198
      参数: 'before_tool', hook_ctx, parsed

    L4: hook_world_model_prediction(ctx, parsed=parsed)
        → core/agent/hooks/core_logic_hooks.py:369
        触发时机: before_tool, priority=95
        参数: ctx, parsed

      L5: world_model_manager.predict_action_outcomes(current_state, actions)
          → core/world_model/world_model_manager.py (推断)
          参数: current_state, actions

  L3: intent_handler.handle_tool_call_async(parsed, working_memory, session_id, task_id)
      → core/intent/intent_handler.py:623
      参数: parsed, working_memory, session_id, task_id

    L4: tool_manager.get_tool(tool_id)
        → core/tool/tool_manager.py (推断)
        参数: tool_id

    L4: tool_manager.execute_tool_async(tool_id, params, timeout, source, task_id, user_id)
        → core/tool/tool_manager.py:2417
        参数: tool_id, params, timeout, source, task_id, user_id
        说明: 异步工具执行统一收口

      L5: async_gateway.execute_async(tool, params, task_id=gateway_task_id, user_id=user_id)
          → core/agent/async_tool_gateway.py:81
          参数: tool, params, task_id, user_id
          边界: AsyncToolGateway — 工具执行边界

  L3: filter_with_enhancement(tool_id, result, source, context, user_id)
      → core/consciousness/filter.py (推断)
      参数: tool_id, result, source=EventSource.AI_EXPLICIT, context, user_id
      说明: 增强层过滤（意识系统）

  L3: agent_loop_hooks.execute_async('after_tool', hook_ctx, tool_result=res)
      → core/agent/agent_loop_hooks.py:198
      参数: 'after_tool', hook_ctx, tool_result
      说明: ToolHook / VoiceHook / SafetyHook 等均注册于此

  L3: run_tool_failure_reflection(reflector, user_instruction, parsed, result, ...)
      → core/agent/reflection_bridge.py (推断)
      参数: reflector, user_instruction, parsed, result, execution_history, working_memory, chat_history, tool_empty_async, tool_failed_async
      说明: 工具失败/空结果时触发深度反思

  L3: smart_context_manager.on_step_complete(task_id, step_number, action, result, success, tool_name, context)
      → core/agent/smart_context_manager.py (推断)
      参数: task_id, step_number, action, result, success, tool_name, context

  L3: checkpoint_manager.save_checkpoint(task.id, "异常退出自动保存")
      → core/agent/checkpoint_manager.py (推断)
      参数: task_id, reason
      说明: finally 块中异常退出时保存断点
```

---

## 边界调用汇总

| 边界类型 | 函数 | 文件 | 说明 |
|---------|------|------|------|
| AI 调用 | `ai_client.chat_async()` | `ai_client.py:370` | 异步 AI 聊天入口 |
| AI 调用 | `ai_client.send_request()` | `ai_client.py:448` | 同步 AI 请求入口（被 call_thinker 使用） |
| 工具执行 | `tool_manager.execute_tool_async()` | `core/tool/tool_manager.py:2417` | 异步工具执行统一收口 |
| 工具执行 | `async_gateway.execute_async()` | `core/agent/async_tool_gateway.py:81` | AsyncToolGateway 执行边界 |
| 事件发布 | `sync.emit_event()` | `core/sync/realtime_sync.py:132` | 实时同步事件总线 |
| 事件发布 | `event_bus.get_summary()` | `core/btc_integration/event_bus.py` | BTC 事件总线读取 |

---

## 追踪说明

- **已追踪深度**: 入口 1 最深达 L8，入口 2 最深达 L6（部分分支达 L5-L6）。
- **动态调用**: `consciousness.orchestrate_input()`、`filter_with_enhancement()` 等通过动态导入加载，实际运行时可能因模块可用性而异。
- **Hook 链**: `before_prompt` 链按 priority 降序执行（100→95→88→85），`before_tool` 链执行世界模型预测。
- **忽略的非业务调用**: `logger.info()`、`print()`、`time.sleep()`、`datetime.now()`、`threading.Thread()`、`hashlib.md5()`、`json.dumps()`、`data.get()`、`field()` 等语法/基础设施噪声已按指令过滤。


---

### 2.3 入口 3：TradingSubAgent._trading_cycle() + 入口 4：MemoryManager.retrieve_memory() + 入口 5：PromptFinalizer.finalize()

以下完整调用链来自子报告 Agent B（已审核）。


# SiliconBase V5 – 跨文件业务调用栈审计报告

> 审计范围：3 个入口函数，每层标注函数名、文件路径、行号、关键参数及外部边界。

---

## 入口 1：TradingSubAgent._trading_cycle()

**文件**: `core/btc_integration/trading_subagent.py:571`  
**职责**: 单个交易周期 — 采集市场数据 → AI 决策 → 执行交易 → 存储记忆

```
入口: trading_subagent._trading_cycle()
  L1: _collect_market_data() → core/btc_integration/trading_subagent.py:1534
      参数: (无)
  L2: get_market_data_provider() → core/btc_integration/market_data.py:299
      参数: (无)
  L3: provider.get_price(symbol) → core/btc_integration/market_data.py:64
      参数: symbol=self.symbol
      边界: OKX API GET /api/v5/market/ticker
  L4: event_bus.emit("market_data_update") → core/sync/event_bus.py:199
      参数: event_name="market_data_update", data={symbol, price, change_24h_percent, source="okx"}
  L5: _make_decision(context) → core/btc_integration/trading_subagent.py:624
      参数: context=TradingContext
  L6: _request_ai_decision(context, market_condition) → core/btc_integration/trading_subagent.py:756
      参数: context=TradingContext, market_condition=MarketCondition
  L7: get_ai_client() → ai_client.py:944
      参数: (无)
  L8: ai_client.chat_async(messages) → ai_client.py:370
      参数: messages=[{"role":"user","content":prompt}]
      边界: LLM Provider (Ollama / OpenAI) via provider.chat()
  L9: _execute_decision(decision, context) → core/btc_integration/trading_subagent.py:1244
      参数: decision=TradingDecision, context=TradingContext
  L10: executor.execute_order(symbol, side, quantity, leverage) → core/btc_integration/trade_executor.py:508
      参数: symbol=self.symbol, side=OrderSide.BUY/SELL, quantity=decision.size, leverage=decision.leverage
  L11: okx_client.create_order(symbol, side, qty, td_mode, ord_type) → core/btc_integration/okx_client.py:204
      参数: symbol, side, qty, td_mode="cross", ord_type="market"
      边界: OKX API POST /api/v5/trade/order
  L12: trading_memory.record_trade(trade) → core/btc_integration/trading_memory.py:132
      参数: trade=TradeRecord(symbol, action, direction, size, price, leverage)
  L13: memory.add_memory(user_id, content, memory_type) → core/memory/memory_manager.py:1467
      参数: user_id="default", content=trade.to_dict(), memory_type="trading"
      边界: PostgreSQL memories table (via PostgresConnectionPool)
  L14: _save_state() → core/btc_integration/trading_subagent.py:1770
      参数: (无)
  L15: write_json(path, data) → core/utils/file_utils.py:36
      参数: path=".runtime/trading_subagent_{symbol}.json", data=state_dict
```

---

## 入口 2：MemoryManager.retrieve_memory()

**文件**: `core/memory/memory_manager.py:1105`  
**职责**: 统一记忆检索 — 缓存查询 → PostgreSQL 查询 → 向量检索 → 返回结果

```
入口: memory_manager.retrieve_memory()
  L1: retrieve_memory(query, layer, mem_type, scene, limit, min_rating, use_vector, use_cache)
      → core/memory/memory_manager.py:1105
      参数: query, layer, mem_type, scene, limit=10, min_rating=-1, use_vector=True, use_cache=True
  L2: MemoryCache.get(user_id, **kwargs) → core/memory/memory_manager.py:214
      参数: user_id="global", cache_key_params={query, layer, mem_type, scene, limit, min_rating, use_vector}
  L3: _get_postgres_memory() → core/memory/memory_manager.py:681
      参数: (无)
  L4: _PostgresMemoryAdapter.get(scene, mem_type, layer, limit, min_rating)
      → core/memory/memory_manager.py:388
      参数: scene, mem_type, layer, limit, min_rating
  L5: PostgresConnectionPool.get_connection() → core/db/connection_pool.py:235
      参数: timeout=10
      边界: PostgreSQL memories table (SELECT ... WHERE user_id='default')
  L6: _get_vector_memory() → core/memory/memory_manager.py:687
      参数: (无)
  L7: VectorStore.search(collection, query, filters, limit) → core/memory/vector_store.py:122
      参数: collection="knowledge", query, limit
      边界: ChromaDB (chromedb.AsyncHttpClient)
  L8: MemoryCache.set(user_id, value, **kwargs) → core/memory/memory_manager.py:239
      参数: user_id="global", value=final_results, cache_key_params
  L9: _trigger_callbacks("on_memory_retrieve", query, final_results)
      → core/memory/memory_manager.py:718
      参数: event="on_memory_retrieve", query, final_results
```

---

## 入口 3：PromptFinalizer.finalize()

**文件**: `core/prompt/prompt_finalizer.py:51`  
**职责**: 提示词最终组装 — 各片段注入 → TokenBudget → 返回 system prompt

```
入口: prompt_finalizer.finalize()
  L1: finalize(user_id, user_instruction, working_memory, assembler, ...)
      → core/prompt/prompt_finalizer.py:51
      参数: user_id, user_instruction, working_memory, assembler, smart_context, perception_context,
            memory_context, exploration_enhancement, layer_prompt, three_views_prompt, reflection_context,
            experience_context, world_model_section, execution_history, session_id, round_count
  L2: _prepare_life_state_context(user_id) → core/prompt/prompt_finalizer.py:246
      参数: user_id
  L3: _prepare_vision_description(last_vision_description) → core/prompt/prompt_finalizer.py:250
      参数: last_vision_description
  L4: sanitize_vision_description(desc) → core/utils/security.py:70
      参数: desc, max_length=2000
  L5: _prepare_phase_context(working_memory, effective_task_id, phase_anchor_manager)
      → core/prompt/prompt_finalizer.py:285
      参数: working_memory, effective_task_id, phase_anchor_manager
  L6: assembler.build_system_prompt_with_budget(...) → core/agent/context_assembler.py:612
      参数: smart_context, perception_context, three_views_prompt, memory_context, exploration_enhancement,
            layer_prompt, reflection_context, vision_description, life_state_context, user_preference_context,
            weak_connection_context, world_model_section, phase_context, execution_history, experience_context,
            working_memory
  L7: prepare_context_components(...) → core/cost/token_budget_integration.py:428
      参数: smart_context, perception_context, three_views_prompt, memory_context, exploration_enhancement,
            layer_prompt, reflection_context, vision_description, life_state_context, user_preference_context,
            weak_connection_context, world_model_section, phase_context, execution_history, experience_context
  L8: build_context_with_budget(context_components, model) → core/cost/token_budget_integration.py:406
      参数: context_components, model="default"
  L9: allocate_budget(key, content, model) → core/cost/token_budget_integration.py:185
      参数: component_key, content, model
  L10: _inject_experience(user_instruction, full_system_prompt) → core/prompt/prompt_finalizer.py:313
      参数: user_instruction, full_system_prompt
  L11: get_experience_injector_v3(enable_tracking=True) → core/evolution/experience_injector.py:1175
      参数: vector_mem=None, enable_tracking=True, refresh=False
  L12: injector.inject_experience(task_description, base_prompt) → core/evolution/experience_injector.py:835
      参数: task_description, base_prompt
  L13: injector.inject(task, base_prompt, context, user_id) → core/evolution/experience_injector.py:756
      参数: task, base_prompt, context=None, user_id="default"
  L14: _search_experiences(task, user_id, limit) → core/evolution/experience_injector.py:897
      参数: task, user_id, limit=success_count*3
  L15: vector_mem.search_experience(task_desc, user_id, only_success, limit)
      → core/memory/vector_memory_compat.py:57
      参数: task_desc, user_id, only_success=True, limit=3
  L16: VectorStore.search_multi(query, collections, n_results) → core/memory/vector_store.py:351
      参数: query, collections=["experience","knowledge"], n_results=limit
      边界: ChromaDB (chromedb.AsyncHttpClient)
  L17: _save_debug_info(...) → core/prompt/prompt_finalizer.py:333
      参数: user_id, session_id, user_instruction, full_system_prompt, smart_context, three_views_prompt,
            memory_context, layer_prompt, exploration_enhancement, phase_context, working_memory
  L18: save_last_prompt(user_id, full_system_prompt, components_data, session_id, query)
      → core/prompt/prompt_debugger.py:89
      参数: user_id, full_system_prompt, components_data, session_id, query
```

---

*报告生成时间: 2026-05-15*  
*审计工具: ReadFile + Grep 源码追踪*


---

## 3. 运行时注册机制

以下完整注册表来自子报告 Agent C（已审核）。


# SiliconBase V5 运行时注册机制审计报告

**扫描范围**: `E:\SiliconBase_V5\SiliconBase_V5`  
**扫描文件数**: 930  
**生成时间**: 2026-05-15  
**排除目录**: `.venv`, `__pycache__`, `node_modules`, `tests`, `scripts`, `backups`, `tmp_test`, `archive`, `frontend`  

## 1. 事件总线订阅

> 共发现 27 处事件订阅（去重后）

| 事件名 | 订阅函数 | 所在文件 | 行号 | 类型（装饰器/直接调用） |
|---|---|---|---|---|
| EventType.AI_DECISION | `on_ai_decision` | api\trading_ws.py | 244 | 直接调用 |
| EventType.RISK_WARNING | `on_risk_event` | api\trading_ws.py | 268 | 直接调用 |
| EventType.STRATEGY_SIGNAL | `on_strategy_signal` | api\trading_ws.py | 293 | 直接调用 |
| EventType.POSITION_UPDATE | `on_position_update` | api\trading_ws.py | 316 | 直接调用 |
| EventType.TELEMETRY_BATCH | `on_telemetry_batch` | api\trading_ws.py | 344 | 直接调用 |
| market_data_update | `on_market_data_update` | api\trading_ws.py | 371 | 直接调用 |
| commander.report | `AgentLoop._on_commander_report` | core\agent\agent_loop.py | 3241 | 直接调用 |
| config_changed | `self._on_config_changed` | core\ai\advanced_model_manager.py | 110 | 直接调用 |
| EventType.AI_DECISION | `self._on_ai_decision` | core\btc_integration\ai_trading_commander.py | 254 | 直接调用 |
| EventType.RISK_WARNING | `self._on_risk_event` | core\btc_integration\ai_trading_commander.py | 255 | 直接调用 |
| EventType.RISK_CRITICAL | `self._on_critical_risk` | core\btc_integration\ai_trading_commander.py | 256 | 直接调用 |
| EventType.NEWS_RISK | `self._on_risk_news` | core\btc_integration\ai_trading_commander.py | 257 | 直接调用 |
| EventType.NEWS_FLASH | `on_news` | core\btc_integration\news_monitor.py | 354 | 直接调用 |
| EventType.NEWS_RISK | `on_news` | core\btc_integration\news_monitor.py | 355 | 直接调用 |
| EventType.RISK_WARNING | `self._on_risk_event` | core\btc_integration\trading_subagent.py | 454 | 直接调用 |
| EventType.RISK_CRITICAL | `self._on_critical_risk` | core\btc_integration\trading_subagent.py | 462 | 直接调用 |
| EventType.AI_INTERVENTION | `self._on_ai_intervention` | core\btc_integration\trading_subagent.py | 470 | 直接调用 |
| EventType.NEWS_FLASH | `self._on_news_event` | core\btc_integration\trading_subagent.py | 478 | 直接调用 |
| config_changed | `self._on_config_changed` | core\cost\cost_manager.py | 205 | 直接调用 |
| task.completed | `on_task_completed` | core\sync\event_bus.py | 16 | 装饰器 |
| consciousness:thought_generated | `_on_consciousness_thought` | core\sync\event_bus.py | 347 | 直接调用 |
| ui:show_proposal | `on_weak_proposal` | core\sync\websocket_server.py | 1112 | 直接调用 |
| MSG_TASK_PROPOSED | `self._on_task_proposed` | core\task\task_event_adapter.py | 75 | 直接调用 |
| MSG_TASK_REQUEST | `self._on_task_proposed` | core\task\task_event_adapter.py | 79 | 直接调用 |
| task:* | `self._on_any_task_event` | core\task\task_event_adapter.py | 83 | 直接调用 |
| config_changed | `self._on_config_changed` | core\tool\tool_manager.py | 779 | 直接调用 |
| context:window_changed | `self._on_window_changed` | core\weak_connection\weak_connection.py | 209 | 直接调用 |

## 2. 工具注册

> 共发现 101 处工具注册（去重后）

| 工具ID | 工具函数/类 | 文件 | 行号 | 参数签名 |
|---|---|---|---|---|
| memory_update | MemoryUpdate | core\memory\memory_update.py | 25 | class MemoryUpdate(BaseTool) |
| example_calculator | ExampleCalculatorTool | plugins\example_plugin.py | 30 | class ExampleCalculatorTool(BaseTool) |
| example_greeting | ExampleGreetingTool | plugins\example_plugin.py | 116 | class ExampleGreetingTool(BaseTool) |
| app_search | AppSearch | tools\app_search.py | 12 | class AppSearch(BaseTool) |
| call_user | CallUser | tools\call_user.py | 9 | class CallUser(BaseTool) |
| click_text | ClickText | tools\click_text.py | 13 | class ClickText(BaseTool) |
| clipboard | Clipboard | tools\clipboard.py | 20 | class Clipboard(BaseTool) |
| clipboard_get | ClipboardGet | tools\clipboard.py | 66 | class ClipboardGet(BaseTool) |
| clipboard_set | ClipboardSet | tools\clipboard.py | 90 | class ClipboardSet(BaseTool) |
| code_generate | CodeGenerate | tools\code_generate.py | 13 | class CodeGenerate(BaseTool) |
| current_time | CurrentTime | tools\current_time.py | 11 | class CurrentTime(BaseTool) |
| delete_user_data | DeleteUserData | tools\delete_user_data.py | 13 | class DeleteUserData(BaseTool) |
| export_data | ExportData | tools\export_data.py | 16 | class ExportData(BaseTool) |
| file_manager | FileManager | tools\file_manager.py | 22 | class FileManager(BaseTool) |
| find_file | FindFile | tools\find_file.py | 13 | class FindFile(BaseTool) |
| list_indexed_files | ListAllFiles | tools\find_file.py | 114 | class ListAllFiles(BaseTool) |
| find_screen_element | FindScreenElement | tools\find_screen_element.py | 29 | class FindScreenElement(BaseTool) |
| get_perception | GetPerception | tools\get_perception.py | 12 | class GetPerception(BaseTool) |
| keyboard_input | KeyboardInput | tools\keyboard_input.py | 80 | class KeyboardInput(BaseTool) |
| launch_app | LaunchApp | tools\launch_app.py | 31 | class LaunchApp(BaseTool) |
| list_installed_apps | ListInstalledApps | tools\list_installed_apps.py | 12 | class ListInstalledApps(BaseTool) |
| create_long_task | CreateLongTask | tools\long_task_tools.py | 21 | class CreateLongTask(BaseTool) |
| pause_long_task | PauseLongTask | tools\long_task_tools.py | 133 | class PauseLongTask(BaseTool) |
| resume_long_task | ResumeLongTask | tools\long_task_tools.py | 192 | class ResumeLongTask(BaseTool) |
| get_long_task_status | GetLongTaskStatus | tools\long_task_tools.py | 258 | class GetLongTaskStatus(BaseTool) |
| cancel_long_task | CancelLongTask | tools\long_task_tools.py | 322 | class CancelLongTask(BaseTool) |
| memory_add | MemoryAdd | tools\memory_add.py | 15 | class MemoryAdd(BaseTool) |
| memory_delete | MemoryDelete | tools\memory_delete.py | 12 | class MemoryDelete(BaseTool) |
| memory_list | MemoryList | tools\memory_list.py | 12 | class MemoryList(BaseTool) |
| memory_search | MemorySearch | tools\memory_search.py | 12 | class MemorySearch(BaseTool) |
| mouse_click | MouseClick | tools\mouse_click.py | 52 | class MouseClick(BaseTool) |
| ocr_text | OCRText | tools\ocr_text.py | 13 | class OCRText(BaseTool) |
| open_and_focus | OpenAndFocus | tools\open_and_focus.py | 21 | class OpenAndFocus(BaseTool) |
| find_and_click | FindAndClick | tools\open_and_focus.py | 140 | class FindAndClick(BaseTool) |
| smart_form_fill | SmartFormFill | tools\open_and_focus.py | 250 | class SmartFormFill(BaseTool) |
| pixel_capture | PixelCapture | tools\pixel_capture.py | 46 | class PixelCapture(BaseTool) |
| pixel_click | PixelClick | tools\pixel_click.py | 15 | class PixelClick(BaseTool) |
| pixel_color | PixelColor | tools\pixel_color.py | 30 | class PixelColor(BaseTool) |
| pixel_monitor | PixelMonitor | tools\pixel_monitor.py | 33 | class PixelMonitor(BaseTool) |
| process_kill | ProcessKill | tools\process_kill.py | 11 | class ProcessKill(BaseTool) |
| process_start | ProcessStart | tools\process_start.py | 211 | class ProcessStart(BaseTool) |
| read_file | ReadFile | tools\read_file.py | 12 | class ReadFile(BaseTool) |
| screen_ocr | ScreenOCR | tools\screen_ocr.py | 25 | class ScreenOCR(BaseTool) |
| shell_execute | ShellExecute | tools\shell_execute.py | 55 | class ShellExecute(BaseTool) |
| delegate_to_subagent | DelegateToSubAgent | tools\subagent_tools.py | 22 | class DelegateToSubAgent(BaseTool) |
| get_subagent_status | GetSubAgentStatus | tools\subagent_tools.py | 129 | class GetSubAgentStatus(BaseTool) |
| intervene_subagent | InterveneSubAgent | tools\subagent_tools.py | 176 | class InterveneSubAgent(BaseTool) |
| list_available_subagents | ListAvailableSubAgents | tools\subagent_tools.py | 271 | class ListAvailableSubAgents(BaseTool) |
| system_info | SystemInfo | tools\system_info.py | 12 | class SystemInfo(BaseTool) |
| create_task | CreateTask | tools\task_tools.py | 30 | class CreateTask(BaseTool) |
| list_tasks | ListTasks | tools\task_tools.py | 332 | class ListTasks(BaseTool) |
| get_task | GetTask | tools\task_tools.py | 391 | class GetTask(BaseTool) |
| cancel_task | CancelTask | tools\task_tools.py | 447 | class CancelTask(BaseTool) |
| template_match | TemplateMatch | tools\template_match.py | 28 | class TemplateMatch(BaseTool) |
| template_record | TemplateRecord | tools\template_record.py | 22 | class TemplateRecord(BaseTool) |
| template_list | TemplateList | tools\template_record.py | 118 | class TemplateList(BaseTool) |
| template_delete | TemplateDelete | tools\template_record.py | 176 | class TemplateDelete(BaseTool) |
| get_tool_manual | GetToolManual | tools\tool_manual.py | 18 | class GetToolManual(BaseTool) |
| get_tool_categories_l1 | GetToolCategoriesL1 | tools\tool_manual.py | 72 | class GetToolCategoriesL1(BaseTool) |
| get_tools_by_category_l2 | GetToolsByCategoryL2 | tools\tool_manual.py | 137 | class GetToolsByCategoryL2(BaseTool) |
| get_tool_detail_l3 | GetToolDetailL3 | tools\tool_manual.py | 241 | class GetToolDetailL3(BaseTool) |
| switch_prompt_layer | SwitchPromptLayer | tools\tool_manual.py | 363 | class SwitchPromptLayer(BaseTool) |
| tron_balance_updater | TronBalanceUpdater | tools\tron_balance_updater.py | 21 | class TronBalanceUpdater(BaseTool) |
| ui_element_detect | UIElementDetect | tools\ui_element_detect.py | 22 | class UIElementDetect(BaseTool) |
| ui_tars | UITarsTool | tools\ui_tars.py | 31 | class UITarsTool(BaseTool) |
| vision_agent | VisionAgentTool | tools\vision_agent.py | 69 | class VisionAgentTool(BaseTool) |
| visual_element_detect | VisualElementDetect | tools\visual_element_detect.py | 36 | class VisualElementDetect(BaseTool) |
| visual_understand | VisualUnderstand | tools\visual_understand.py | 67 | class VisualUnderstand(BaseTool) |
| icon_recognize | IconRecognize | tools\visual_understand.py | 579 | class IconRecognize(BaseTool) |
| vpn_check | VPNCheck | tools\vpn_check.py | 12 | class VPNCheck(BaseTool) |
| vpn_connect | VPNConnect | tools\vpn_connect.py | 12 | class VPNConnect(BaseTool) |
| wait_for_window | WaitForWindow | tools\wait_for_window.py | 6 | class WaitForWindow(BaseTool) |
| web_automation | WebAutomation | tools\web_automation.py | 13 | class WebAutomation(BaseTool) |
| web_fetch | WebFetch | tools\web_fetch.py | 21 | class WebFetch(BaseTool) |
| web_open | WebOpen | tools\web_open.py | 28 | class WebOpen(BaseTool) |
| web_parse | WebParse | tools\web_parse.py | 14 | class WebParse(BaseTool) |
| web_search | WebSearch | tools\web_search.py | 55 | class WebSearch(BaseTool) |
| window_action | WindowAction | tools\window_action.py | 12 | class WindowAction(BaseTool) |
| window_focus | WindowFocus | tools\window_focus.py | 13 | class WindowFocus(BaseTool) |
| window_get | WindowGet | tools\window_get.py | 16 | class WindowGet(BaseTool) |
| window_ocr | WindowOCR | tools\window_ocr.py | 11 | class WindowOCR(BaseTool) |
| window_rect | WindowRect | tools\window_rect.py | 7 | class WindowRect(BaseTool) |
| btc_price_query | BTCPriceQuery | tools\btc_trading\base_tools.py | 39 | class BTCPriceQuery(BaseTool) |
| btc_market_overview | BTCMarketOverview | tools\btc_trading\base_tools.py | 189 | class BTCMarketOverview(BaseTool) |
| btc_technical_analysis | BTCTechnicalAnalysis | tools\btc_trading\base_tools.py | 267 | class BTCTechnicalAnalysis(BaseTool) |
| btc_account_info | BTCAccountInfo | tools\btc_trading\base_tools.py | 374 | class BTCAccountInfo(BaseTool) |
| btc_risk_check | BTCRiskCheck | tools\btc_trading\risk_tools.py | 26 | class BTCRiskCheck(BaseTool) |
| btc_emergency_stop | BTCEmergencyStop | tools\btc_trading\risk_tools.py | 164 | class BTCEmergencyStop(BaseTool) |
| btc_intervention | BTCIntervention | tools\btc_trading\risk_tools.py | 263 | class BTCIntervention(BaseTool) |
| btc_check_recovery | BTCCheckRecovery | tools\btc_trading\risk_tools.py | 358 | class BTCCheckRecovery(BaseTool) |
| btc_recover_trading | BTCRecoverTrading | tools\btc_trading\risk_tools.py | 459 | class BTCRecoverTrading(BaseTool) |
| btc_strategy_selector | BTCStrategySelector | tools\btc_trading\strategy_tools.py | 28 | class BTCStrategySelector(BaseTool) |
| btc_strategy_explain | BTCStrategyExplain | tools\btc_trading\strategy_tools.py | 266 | class BTCStrategyExplain(BaseTool) |
| btc_risk_assessment | BTCRiskAssessment | tools\btc_trading\strategy_tools.py | 365 | class BTCRiskAssessment(BaseTool) |
| btc_launch_autopilot | BTCLaunchAutopilot | tools\btc_trading\trading_tools.py | 30 | class BTCLaunchAutopilot(BaseTool) |
| btc_get_process_status | BTCGetProcessStatus | tools\btc_trading\trading_tools.py | 237 | class BTCGetProcessStatus(BaseTool) |
| btc_stop_autopilot | BTCStopAutopilot | tools\btc_trading\trading_tools.py | 385 | class BTCStopAutopilot(BaseTool) |
| btc_monitor_trading | BTCMonitorTrading | tools\btc_trading\trading_tools.py | 501 | class BTCMonitorTrading(BaseTool) |
| btc_generate_report | BTCGenerateReport | tools\btc_trading\trading_tools.py | 541 | class BTCGenerateReport(BaseTool) |
| btc_confirm_trade | BTCConfirmTrade | tools\btc_trading\trading_tools.py | 613 | class BTCConfirmTrade(BaseTool) |
| btc_execute_trade | BTCExecuteTrade | tools\btc_trading\trading_tools.py | 657 | class BTCExecuteTrade(BaseTool) |

**说明**: 目标为 135 个工具，实际找到 101 个。
缺失原因分析：
- 部分工具通过 `_load_all_tools()` 动态遍历 `tools/` 目录加载，静态代码仅能识别显式定义的 `BaseTool` 子类
- 部分工具可能存放在被排除的目录（如 `tests/`、`backups/`）中
- 部分工具可能通过配置表、数据库或插件市场注册，非静态代码可见
- `tool_manager.register_tool(name=..., func=...)` 形式注册的工具（如 `tool_loader.py`、`plugin_system.py` 中的函数式工具）未完全展开

## 3. FastAPI 路由注册

> 共发现 414 处路由注册（去重后）

| HTTP方法 | 路径 | Handler函数 | 文件 | 行号 |
|---|---|---|---|---|
| GET |  | list_models | api\advanced_models_api.py | 133 |
| GET | /{model_id} | get_model | api\advanced_models_api.py | 158 |
| POST | /{model_id}/enable | enable_model | api\advanced_models_api.py | 181 |
| POST | /{model_id}/disable | disable_model | api\advanced_models_api.py | 203 |
| POST | /{model_id}/deploy | deploy_model | api\advanced_models_api.py | 221 |
| POST | /{model_id}/undeploy | undeploy_model | api\advanced_models_api.py | 256 |
| POST | /{model_id}/download | download_model | api\advanced_models_api.py | 283 |
| GET | /{model_id}/download-progress | download_progress | api\advanced_models_api.py | 349 |
| POST | /{model_id}/load | load_model_endpoint | api\advanced_models_api.py | 395 |
| POST | /{model_id}/unload | unload_model_endpoint | api\advanced_models_api.py | 433 |
| GET | /system/memory | get_memory_status | api\advanced_models_api.py | 455 |
| GET | /providers | get_ai_providers | api\ai_config_api.py | 161 |
| GET | /config | get_ai_config | api\ai_config_api.py | 233 |
| POST | /config | update_ai_config | api\ai_config_api.py | 304 |
| POST | /test | test_ai_config | api\ai_config_api.py | 451 |
| GET | /models | get_ai_models | api\ai_config_api.py | 508 |
| GET | /models/{provider} | get_provider_models | api\ai_config_api.py | 659 |
| GET | /config/vision | get_vision_config_endpoint | api\ai_config_api.py | 681 |
| POST | /config/vision | update_vision_config | api\ai_config_api.py | 778 |
| POST | /test/vision | test_vision_config | api\ai_config_api.py | 889 |
| GET | /api/protected | protected_endpoint | api\auth_utils.py | 236 |
| POST | /start | start_auto_trading | api\auto_trading_api.py | 77 |
| POST | /stop | stop_auto_trading | api\auto_trading_api.py | 130 |
| GET | /status | get_auto_trading_status | api\auto_trading_api.py | 155 |
| POST | /pause | pause_auto_trading | api\auto_trading_api.py | 175 |
| POST | /resume | resume_auto_trading | api\auto_trading_api.py | 198 |
| GET | /logs | get_auto_trading_logs | api\auto_trading_api.py | 221 |
| GET | /stats | get_auto_trading_stats | api\auto_trading_api.py | 252 |
| GET | /sessions | get_session_history | api\auto_trading_api.py | 270 |
| POST | /cleanup | force_cleanup | api\auto_trading_api.py | 289 |
| POST | /restart | restart_auto_trading | api\auto_trading_api.py | 311 |
| GET | /health | health_check | api\auto_trading_api.py | 347 |
| GET | / | root | api\cloud_api.py | 3945 |
| GET | /api/health | health_check | api\cloud_api.py | 3956 |
| GET | /health | health_check_root | api\cloud_api.py | 3973 |
| POST | /api/auth/login | login | api\cloud_api.py | 3988 |
| POST | /api/auth/register | register | api\cloud_api.py | 4063 |
| POST | /api/auth/change-password | change_password | api\cloud_api.py | 4109 |
| POST | /api/auth/refresh | refresh_token | api\cloud_api.py | 4163 |
| POST | /api/auth/logout | logout | api\cloud_api.py | 4193 |
| GET | /api/auth/me | get_current_user_info | api\cloud_api.py | 4219 |
| GET | /api/metrics | metrics_endpoint | api\cloud_api.py | 4254 |
| GET | /api/ready | ready_probe | api\cloud_api.py | 4269 |
| GET | /api/live | live_probe | api\cloud_api.py | 4282 |
| GET | /api/status | get_status | api\cloud_api.py | 4295 |
| GET | /api/modelbus/status | get_modelbus_status | api\cloud_api.py | 4327 |
| POST | /api/chat | chat | api\cloud_api.py | 4378 |
| POST | /api/chat/stream | chat_stream | api\cloud_api.py | 4474 |
| GET | /api/messages/{session_id} | get_messages | api\cloud_api.py | 4558 |
| GET | /api/tasks | list_tasks_fallback | api\cloud_api.py | 4606 |
| GET | /api/tasks/simple | list_tasks_simple | api\cloud_api.py | 4666 |
| GET | /api/stats | get_stats | api\cloud_api.py | 4696 |
| POST | /api/voice/frontend | frontend_voice_input | api\cloud_api.py | 4731 |
| POST | /voice_ptt | voice_ptt | api\cloud_api.py | 4797 |
| POST | /api/voice/ptt | voice_ptt | api\cloud_api.py | 4798 |
| GET | /api/config | get_frontend_config | api\cloud_api.py | 4844 |
| POST | /api/upload | upload_file | api\cloud_api.py | 4912 |
| GET | /api/config/moral-filter | get_moral_filter_config | api\cloud_api.py | 4959 |
| PUT | /api/config/moral-filter | update_moral_filter_config | api\cloud_api.py | 4996 |
| POST | /api/config/moral-filter/reset | reset_moral_filter_config | api\cloud_api.py | 5053 |
| GET | /api/monitoring/states | get_system_states | api\cloud_api.py | 5853 |
| GET | /api/monitoring/states/{container_name} | get_container_state | api\cloud_api.py | 5882 |
| GET | /api/monitoring/registry | get_registry_info | api\cloud_api.py | 5929 |
| GET | /api/screenshots/stats | get_screenshot_stats | api\cloud_api.py | 5963 |
| POST | /api/screenshots/cleanup | cleanup_screenshots | api\cloud_api.py | 5996 |
| GET | /api/screenshots/list | list_screenshots | api\cloud_api.py | 6030 |
| GET | /api/screenshots/view/{filename} | view_screenshot | api\cloud_api.py | 6102 |
| GET | /api/system | get_system_info_simple | api\cloud_api.py | 6159 |
| GET | /api/tasks/metrics | get_task_metrics_simple | api\cloud_api.py | 6222 |
| GET | /api/mcp/status | get_mcp_status | api\cloud_api.py | 6456 |
| POST | /api/mcp/enable | enable_mcp | api\cloud_api.py | 6481 |
| POST | /api/mcp/disable | disable_mcp | api\cloud_api.py | 6533 |
| GET | /api/subagent/list | list_subagents | api\cloud_api.py | 6565 |
| POST | /api/subagent/delegate | delegate_to_subagent | api\cloud_api.py | 6598 |
| POST | /api/agent/intervene | intervene_agent | api\cloud_api.py | 6685 |
| POST | /api/subagents/{runtime_id}/intervene | intervene_subagent | api\cloud_api.py | 6774 |
| GET | /api/subagents/{runtime_id}/status | get_subagent_status | api\cloud_api.py | 6978 |
| GET | /api/ai-status | get_ai_status | api\cloud_api.py | 7219 |
| GET | /api/task-status/{task_id} | get_task_status | api\cloud_api.py | 7253 |
| GET | /api/system/api-registry | get_api_registry | api\cloud_api.py | 7622 |
| GET | / | root | api\cloud_api_minimal.py | 44 |
| POST | /publish | publish_tool_endpoint | api\cloud_tool_repo.py | 1046 |
| GET | /list | get_tool_list_endpoint | api\cloud_tool_repo.py | 1078 |
| GET | /{tool_id}/versions | get_tool_versions_endpoint | api\cloud_tool_repo.py | 1093 |
| GET | /{tool_id}/{version}/download | download_tool_endpoint | api\cloud_tool_repo.py | 1107 |
| GET | /{tool_id}/{version}/detail | get_tool_detail_endpoint | api\cloud_tool_repo.py | 1131 |
| POST | /check-updates | check_updates_endpoint | api\cloud_tool_repo.py | 1148 |
| POST | /{tool_id}/{version}/approve | approve_tool_endpoint | api\cloud_tool_repo.py | 1214 |
| GET | /schema | get_config_schema | api\config_api.py | 38 |
| GET | /yaml | get_config_yaml | api\config_api.py | 70 |
| POST | /yaml | save_config_yaml | api\config_api.py | 111 |
| POST | /reload | reload_config | api\config_api.py | 171 |
| GET | /backups | get_config_backups | api\config_api.py | 212 |
| POST | /restore | restore_config_backup | api\config_api.py | 276 |
| POST |  | update_config | api\config_api.py | 348 |
| GET | /vital-signs | get_current_vital_signs | api\consciousness_api.py | 110 |
| GET | /vital-signs/history | get_vital_signs_history | api\consciousness_api.py | 147 |
| GET | /self-actions | get_self_actions | api\consciousness_api.py | 191 |
| POST | /self-actions/{action_id}/feedback | feedback_self_action | api\consciousness_api.py | 235 |
| GET | /status | get_life_status | api\consciousness_api.py | 283 |
| POST | /update-vital-signs | trigger_vital_signs_update | api\consciousness_api.py | 326 |
| POST | /generate-action | trigger_self_action | api\consciousness_api.py | 359 |
| GET | /status | get_budget_status | api\cost_api.py | 233 |
| GET | /stats | get_usage_stats | api\cost_api.py | 263 |
| GET | /report | get_cost_report | api\cost_api.py | 293 |
| GET | /usage | get_usage_records | api\cost_api.py | 313 |
| POST | /budget | update_budget | api\cost_api.py | 339 |
| GET | /models | get_model_pricing | api\cost_api.py | 368 |
| POST | /count | count_tokens | api\cost_api.py | 396 |
| POST | /count-messages | count_message_tokens | api\cost_api.py | 425 |
| GET | /health | health_check | api\cost_api.py | 571 |
| POST | /subagent | use_subagent | api\dependencies.py | 55 |
| GET | /configs | get_configs | api\exchange_config_api.py | 116 |
| POST | /configs | create_config | api\exchange_config_api.py | 137 |
| PUT | /configs/{config_id} | update_config | api\exchange_config_api.py | 194 |
| DELETE | /configs/{config_id} | delete_config | api\exchange_config_api.py | 233 |
| POST | /configs/{config_id}/validate | validate_config | api\exchange_config_api.py | 260 |
| GET | /mode | get_trading_mode | api\exchange_config_api.py | 286 |
| POST | /configs/{config_id}/activate | activate_config | api\exchange_config_api.py | 331 |
| GET | /exchanges | get_supported_exchanges | api\exchange_config_api.py | 365 |
| GET | /ab-test/report | get_ab_test_report | api\experience_api.py | 103 |
| POST | /ab-test/assign | assign_ab_test_group | api\experience_api.py | 130 |
| POST | /ab-test/outcome | record_ab_test_outcome | api\experience_api.py | 163 |
| GET | /ab-test/recent | get_recent_ab_test_records | api\experience_api.py | 194 |
| GET | /effectiveness/global-stats | get_global_effectiveness_stats | api\experience_api.py | 221 |
| GET | /effectiveness/leaderboard | get_effectiveness_leaderboard | api\experience_api.py | 245 |
| GET | /effectiveness/{experience_id} | get_experience_effectiveness | api\experience_api.py | 277 |
| POST | /effectiveness/track-usage | track_experience_usage | api\experience_api.py | 308 |
| POST | /effectiveness/track-outcome | track_task_outcome | api\experience_api.py | 340 |
| GET | /purge/candidates | get_purge_candidates | api\experience_api.py | 377 |
| POST | /purge/scan | run_purge_scan | api\experience_api.py | 402 |
| POST | /purge/execute | execute_purge | api\experience_api.py | 428 |
| GET | /purge/report | get_purge_report | api\experience_api.py | 470 |
| GET | /dashboard | get_experience_dashboard | api\experience_api.py | 499 |
| GET | /status | get_gamification_status | api\gamification_api.py | 237 |
| GET | /level | get_level_info | api\gamification_api.py | 280 |
| POST | /add-xp | add_experience | api\gamification_api.py | 305 |
| POST | /record-tool-usage | record_tool_usage | api\gamification_api.py | 373 |
| GET | /categories | get_category_unlock_status | api\gamification_api.py | 439 |
| GET | /achievements | get_achievements | api\gamification_api.py | 461 |
| GET | /leaderboard | get_leaderboard | api\gamification_api.py | 562 |
| OPTIONS | /{path:path} | options_handler | api\gamification_api.py | 608 |
| GET | /status | get_scan_status | api\global_view_api.py | 124 |
| GET | /tree | get_file_tree | api\global_view_api.py | 154 |
| GET | /search | search_files | api\global_view_api.py | 200 |
| POST | /scan/start | start_scan | api\global_view_api.py | 248 |
| POST | /scan/stop | stop_scan | api\global_view_api.py | 290 |
| DELETE | /clear | clear_all_data | api\global_view_api.py | 317 |
| GET | /stats | get_stats | api\global_view_api.py | 343 |
| POST | /{session_id}/interrupt | interrupt_session_loop | api\interrupt_api.py | 31 |
| GET | /{session_id}/status | get_session_status | api\interrupt_api.py | 149 |
| GET | /slots | get_all_slots | api\long_task_slots_api.py | 284 |
| GET | /slots/{slot_id} | get_slot_status | api\long_task_slots_api.py | 315 |
| POST | /slots/{slot_id}/create | create_task | api\long_task_slots_api.py | 347 |
| POST | /slots/{slot_id}/pause | pause_task | api\long_task_slots_api.py | 396 |
| POST | /slots/{slot_id}/resume | resume_task | api\long_task_slots_api.py | 471 |
| POST | /slots/{slot_id}/modify | modify_task | api\long_task_slots_api.py | 540 |
| POST | /slots/{slot_id}/stop | stop_task | api\long_task_slots_api.py | 598 |
| POST | /slots/{slot_id}/complete | complete_task | api\long_task_slots_api.py | 640 |
| POST | /slots/{slot_id}/progress | update_progress | api\long_task_slots_api.py | 694 |
| POST | /slots/{slot_id}/understanding | update_ai_understanding | api\long_task_slots_api.py | 753 |
| GET | /slots/{slot_id}/ai-summary | get_slot_summary_for_ai | api\long_task_slots_api.py | 796 |
| GET | /ai-summary | get_all_slots_summary_for_ai | api\long_task_slots_api.py | 836 |
| POST |  | create_memory | api\memory_api.py | 123 |
| GET |  | list_memories | api\memory_api.py | 170 |
| GET | /search | search_memories | api\memory_api.py | 228 |
| POST | /advanced-search | advanced_search | api\memory_api.py | 310 |
| DELETE | /{memory_id} | delete_memory | api\memory_api.py | 374 |
| PUT | /{memory_id} | update_memory | api\memory_api.py | 403 |
| PUT | /{memory_id}/important | mark_memory_important | api\memory_api.py | 440 |
| POST | /batch | create_memories_batch | api\memory_api.py | 472 |
| DELETE | /batch | batch_delete_memories | api\memory_api.py | 522 |
| POST | /evolve | evolve_memories | api\memory_api.py | 558 |
| GET | /evolution-history | get_evolution_history | api\memory_api.py | 609 |
| POST | /filter-by-dimensions | filter_by_dimensions | api\memory_api.py | 644 |
| GET | /filter-by-grades | filter_by_grades | api\memory_api.py | 714 |
| GET | /executions | get_execution_memories | api\memory_api.py | 774 |
| GET | /executions/stats | get_execution_stats | api\memory_api.py | 819 |
| DELETE | /executions/{execution_id} | delete_execution_memory | api\memory_api.py | 852 |
| POST | /executions/batch-delete | batch_delete_executions | api\memory_api.py | 926 |
| GET | /by-session/{session_id} | get_memories_by_session | api\memory_api.py | 1074 |
| GET | /source-stats | get_memory_source_stats | api\memory_api.py | 1177 |
| GET |  | get_graph_root | api\memory_graph_api.py | 405 |
| POST | /node | add_node | api\memory_graph_api.py | 427 |
| POST | /relation | add_relation | api\memory_graph_api.py | 435 |
| GET | /related/{memory_id} | find_related | api\memory_graph_api.py | 446 |
| GET | /path | find_path | api\memory_graph_api.py | 457 |
| GET | /visualization | get_visualization | api\memory_graph_api.py | 465 |
| GET | /stats | get_stats | api\memory_graph_api.py | 474 |
| POST | /discover | auto_discover | api\memory_graph_api.py | 482 |
| GET | /export | export_graph | api\memory_graph_api.py | 490 |
| GET | /memory-sync/stats | get_memory_sync_stats | api\memory_sync_websocket.py | 213 |
| GET | /viz/flow | get_memory_flow | api\memory_visualization_api.py | 223 |
| GET | /viz/graph | get_memory_graph | api\memory_visualization_api.py | 350 |
| GET | /viz/stats | get_memory_stats | api\memory_visualization_api.py | 474 |
| GET | /viz/timeline | get_memory_timeline | api\memory_visualization_api.py | 579 |
| GET | /system | get_system_metrics | api\metrics_api.py | 67 |
| GET | /tasks | get_task_metrics | api\metrics_api.py | 131 |
| GET | /memory | get_memory_metrics | api\metrics_api.py | 230 |
| GET | /reflections | get_reflection_metrics | api\metrics_api.py | 317 |
| GET | /modules | get_modules | api\prompt_api.py | 78 |
| GET | /roles | get_roles | api\prompt_api.py | 106 |
| GET | /default-modules/{role} | get_default_modules | api\prompt_api.py | 126 |
| GET | /user-selection/{user_id} | get_user_selection | api\prompt_api.py | 138 |
| GET | /modules/{module_id}/default | get_module_default_content | api\prompt_api.py | 150 |
| POST | /save-selection | save_selection | api\prompt_api.py | 187 |
| POST | /build | build_prompt | api\prompt_api.py | 203 |
| POST | /preview-module | preview_module | api\prompt_api.py | 231 |
| GET | /reload | reload_config | api\prompt_api.py | 247 |
| GET | /debug/last-prompt | get_last_prompt_api | api\prompt_api.py | 273 |
| GET | /debug/last-prompt-preview | get_last_prompt_preview_api | api\prompt_api.py | 304 |
| POST | /debug/estimate-tokens | estimate_tokens_api | api\prompt_api.py | 334 |
| POST | /modules | save_module | api\prompt_api.py | 363 |
| GET | /user-module-config/{module_id} | get_user_module_config | api\prompt_api.py | 382 |
| DELETE | /user-module-config/{module_id} | delete_user_module_config | api\prompt_api.py | 400 |
| GET | /check-admin | check_admin | api\prompt_api.py | 416 |
| GET | /config-for-frontend | get_config_for_frontend | api\prompt_api.py | 425 |
| GET | /info | get_layer_info | api\prompt_layer_api.py | 113 |
| GET | /l1 | get_layer1 | api\prompt_layer_api.py | 155 |
| GET | /l2 | get_layer2 | api\prompt_layer_api.py | 220 |
| GET | /l3/{tool_id} | get_layer3 | api\prompt_layer_api.py | 298 |
| POST | /switch | switch_layer | api\prompt_layer_api.py | 353 |
| GET | /state | get_layer_state | api\prompt_layer_api.py | 424 |
| GET | /categories | get_categories | api\prompt_layer_api.py | 458 |
| GET | /tools | get_tools_by_category_api | api\prompt_layer_api.py | 485 |
| GET | /{module_id} | get_module_variants | api\prompt_variant_api.py | 167 |
| POST | /{module_id}/switch | switch_variant | api\prompt_variant_api.py | 198 |
| GET | /{module_id}/content | get_variant_content | api\prompt_variant_api.py | 237 |
| GET | /user/{user_id}/selections | get_user_variant_selections | api\prompt_variant_api.py | 278 |
| POST | /{module_id}/save | save_module_content | api\prompt_variant_api.py | 320 |
| POST | /{module_id}/reset | reset_to_default | api\prompt_variant_api.py | 354 |
| GET | /{module_id}/content | get_variant_content_with_custom | api\prompt_variant_api.py | 396 |
| GET | / | root | api\run_no_lifespan.py | 32 |
| GET | / | root | api\run_ultra_minimal.py | 48 |
| GET | /state | get_life_state | api\silicon_life_api.py | 282 |
| POST | /state/refresh | refresh_life_state | api\silicon_life_api.py | 319 |
| GET | /timeline | get_growth_timeline | api\silicon_life_api.py | 359 |
| GET | /memory-pyramid | get_memory_pyramid | api\silicon_life_api.py | 448 |
| GET | /learning-stats | get_learning_stats | api\silicon_life_api.py | 518 |
| GET | /summary | get_growth_summary | api\silicon_life_api.py | 580 |
| OPTIONS | /{path:path} | options_handler | api\silicon_life_api.py | 783 |
| GET | /failures | get_failure_stats | api\stats_api.py | 94 |
| GET | /daily-report | generate_daily_report | api\stats_api.py | 129 |
| POST | /record-failure | record_failure | api\stats_api.py | 148 |
| GET | /health | health_check | api\stats_api.py | 183 |
| POST | /{user_id}/push | push_data | api\sync_api.py | 324 |
| GET | /{user_id}/pull | pull_data | api\sync_api.py | 391 |
| GET | /{user_id}/status | get_sync_status | api\sync_api.py | 443 |
| POST | /{user_id}/resolve | resolve_conflict | api\sync_api.py | 475 |
| GET | /{user_id}/history | get_sync_history | api\sync_api.py | 531 |
| GET | /admin/stats | get_sync_statistics | api\sync_api.py | 583 |
| GET | /health | sync_health_check | api\sync_api.py | 661 |
| POST |  | create_task | api\task_api.py | 329 |
| GET |  | list_tasks | api\task_api.py | 377 |
| GET | /{task_id} | get_task | api\task_api.py | 452 |
| PATCH | /{task_id} | update_task | api\task_api.py | 481 |
| DELETE | /{task_id} | delete_task | api\task_api.py | 523 |
| POST | /{task_id}/complete | complete_task | api\task_api.py | 562 |
| POST | /{task_id}/fail | fail_task | api\task_api.py | 598 |
| POST | /{task_id}/cancel | cancel_task | api\task_api.py | 629 |
| POST | /{task_id}/pause | pause_task | api\task_api.py | 659 |
| POST | /{task_id}/resume | resume_task | api\task_api.py | 727 |
| POST | /{task_id}/archive | archive_task | api\task_api.py | 768 |
| POST | /{task_id}/dependencies | add_dependency | api\task_api.py | 802 |
| DELETE | /{task_id}/dependencies/{depends_on} | remove_dependency | api\task_api.py | 838 |
| GET | /{task_id}/dependencies | get_dependencies | api\task_api.py | 866 |
| GET | /plan/execution | get_execution_plan | api\task_api.py | 897 |
| POST | /{task_id}/compress | compress_task | api\task_api.py | 922 |
| POST | /batch/compress | batch_compress_tasks | api\task_api.py | 953 |
| POST | /search/similar | search_similar_tasks | api\task_api.py | 993 |
| GET | /suggestions/next | suggest_next_tasks | api\task_api.py | 1017 |
| GET | /tree/{root_task_id} | get_task_tree | api\task_api.py | 1041 |
| GET | /stats/overview | get_task_stats | api\task_api.py | 1069 |
| POST | /cleanup | cleanup_old_tasks | api\task_api.py | 1091 |
| GET | /health/check | health_check | api\task_api.py | 1119 |
| GET | /{task_id}/anchors | get_task_anchors | api\task_api.py | 1158 |
| POST | /{task_id}/anchors | create_task_anchor | api\task_api.py | 1172 |
| POST | /{task_id}/anchors/batch | batch_update_task_anchors | api\task_api.py | 1199 |
| PUT | /{task_id}/anchors/{anchor_id} | update_task_anchor | api\task_api.py | 1209 |
| DELETE | /{task_id}/anchors/{anchor_id} | delete_task_anchor | api\task_api.py | 1237 |
| GET | /{task_id}/anchors/{anchor_id}/history | get_task_anchor_history | api\task_api.py | 1251 |
| GET | /{task_id}/progress | get_task_checkpoint_progress | api\task_api.py | 1269 |
| GET | /{task_id}/checkpoints | list_task_checkpoints | api\task_api.py | 1322 |
| POST | /{task_id}/checkpoints | create_task_checkpoint | api\task_api.py | 1365 |
| POST | /feedback | submit_task_feedback | api\template_experiment_api.py | 100 |
| POST | /track-task | track_task_result | api\template_experiment_api.py | 169 |
| GET | /report | get_template_report | api\template_experiment_api.py | 215 |
| GET | /comparison | get_experiment_comparison | api\template_experiment_api.py | 283 |
| POST | /recommendation | get_template_recommendation | api\template_experiment_api.py | 327 |
| GET | /recommendation | get_user_template_recommendation | api\template_experiment_api.py | 380 |
| GET | /weekly-report | get_latest_weekly_report | api\template_experiment_api.py | 425 |
| GET | /weekly-reports | get_all_weekly_reports | api\template_experiment_api.py | 459 |
| POST | /generate-report | generate_weekly_report | api\template_experiment_api.py | 493 |
| POST | /export | export_experiment_data | api\template_experiment_api.py | 532 |
| GET | /templates | get_templates | api\three_views_api.py | 47 |
| GET | /config | get_user_config | api\three_views_api.py | 61 |
| POST | /config | save_user_config | api\three_views_api.py | 82 |
| GET | /preview | preview_three_views | api\three_views_api.py | 115 |
| GET | / | get_tools | api\tools_api.py | 256 |
| POST | /execute | execute_tool | api\tools_api.py | 292 |
| GET | /categories | get_tool_categories | api\tools_api.py | 317 |
| GET | /search | search_tools | api\tools_api.py | 386 |
| GET | /category/{category} | get_tools_by_category | api\tools_api.py | 444 |
| GET | /{tool_id} | get_tool | api\tools_api.py | 480 |
| POST | /{tool_id}/execute | execute_tool_by_id | api\tools_api.py | 529 |
| POST | /validate | validate_tool | api\tools_api.py | 555 |
| GET | /schema/{tool_id} | get_tool_schema | api\tools_api.py | 593 |
| GET | /detail/{tool_id} | get_tool_detail | api\tools_api.py | 621 |
| POST | /test/{tool_id} | test_tool | api\tools_api.py | 649 |
| POST | /toggle/{tool_id} | toggle_tool | api\tools_api.py | 673 |
| POST | /delete/{tool_id} | delete_tool | api\tools_api.py | 694 |
| POST | /register | register_tool | api\tools_api.py | 713 |
| GET | /tool-manual/l1 | get_tool_manual_l1 | api\tools_api.py | 752 |
| GET | /tool-manual/l2/{category} | get_tool_manual_l2 | api\tools_api.py | 807 |
| GET | /tool-manual/l3/{tool_id} | get_tool_manual_l3 | api\tools_api.py | 908 |
| POST | /tool-manual/switch | switch_tool_manual_layer | api\tools_api.py | 1047 |
| POST | /tool-manual/clear-cache | clear_tool_manual_cache | api\tools_api.py | 1206 |
| GET | /tool-manual/cache-status | get_tool_manual_cache_status | api\tools_api.py | 1222 |
| POST | /install | install_tool | api\tool_market_api.py | 97 |
| GET | /task/{task_id} | get_task_status | api\tool_market_api.py | 130 |
| GET | /installed | get_installed_tools | api\tool_market_api.py | 154 |
| POST | /uninstall/{tool_id} | uninstall_tool_endpoint | api\tool_market_api.py | 179 |
| POST | /update/{tool_id} | update_tool_endpoint | api\tool_market_api.py | 198 |
| POST | /check-updates | check_updates_endpoint | api\tool_market_api.py | 219 |
| POST | /auto-update | auto_update_all_endpoint | api\tool_market_api.py | 234 |
| GET | /is-installed/{tool_id} | is_tool_installed | api\tool_market_api.py | 258 |
| GET | /symbols | get_symbols | api\trading_api.py | 204 |
| POST | /symbols | add_symbol | api\trading_api.py | 215 |
| DELETE | /symbols/{symbol} | remove_symbol | api\trading_api.py | 235 |
| GET | /price/{symbol} | get_price | api\trading_api.py | 255 |
| GET | /klines/{symbol} | get_klines | api\trading_api.py | 302 |
| GET | /trades/{symbol} | get_trades | api\trading_api.py | 346 |
| GET | /position/{symbol} | get_position | api\trading_api.py | 373 |
| GET | /account | get_account | api\trading_api.py | 405 |
| POST | /position/close | close_position | api\trading_api.py | 430 |
| GET | /status | get_mode_status | api\trading_mode_api.py | 550 |
| POST | /switch | switch_mode | api\trading_mode_api.py | 606 |
| POST | /auto/start | start_auto_trading | api\trading_mode_api.py | 661 |
| POST | /auto/stop | stop_auto_trading | api\trading_mode_api.py | 684 |
| GET | /auto/status | get_auto_trading_status | api\trading_mode_api.py | 703 |
| POST | /ai/start | start_ai_trading | api\trading_mode_api.py | 728 |
| POST | /ai/stop | stop_ai_trading_api | api\trading_mode_api.py | 765 |
| POST | /ai/pause | pause_ai_trading | api\trading_mode_api.py | 785 |
| POST | /ai/resume | resume_ai_trading | api\trading_mode_api.py | 807 |
| POST | /ai/intervene | ai_intervene | api\trading_mode_api.py | 827 |
| POST | /ai/confirm | confirm_ai_decision | api\trading_mode_api.py | 851 |
| POST | /ai/reject | reject_ai_decision | api\trading_mode_api.py | 908 |
| GET | /ai/pending | get_pending_decisions | api\trading_mode_api.py | 964 |
| GET | /ai/status | get_ai_trading_status | api\trading_mode_api.py | 1008 |
| POST | /manual/order | place_manual_order | api\trading_mode_api.py | 1044 |
| GET | /manual/positions | get_manual_positions | api\trading_mode_api.py | 1103 |
| GET | /prediction | get_trading_prediction | api\trading_mode_api.py | 1160 |
| GET | /announce/config | get_voice_announce_config | api\voice_announce_api.py | 81 |
| POST | /announce/config | update_voice_announce_config | api\voice_announce_api.py | 126 |
| GET | /announce/status | get_voice_announce_status | api\voice_announce_api.py | 174 |
| PATCH | /announce/config | patch_voice_announce_config | api\voice_announce_api.py | 216 |
| POST | /announce | announce_voice | api\voice_api.py | 77 |
| POST | /layer-switch | announce_layer_switch | api\voice_api.py | 122 |
| GET | /status | get_voice_status | api\voice_api.py | 176 |
| POST | /enable | enable_voice | api\voice_api.py | 209 |
| POST | /disable | disable_voice | api\voice_api.py | 229 |
| POST | /stt | speech_to_text | api\voice_api.py | 258 |
| GET | /quick-announce | quick_announce | api\voice_api.py | 349 |
| GET |  | list_workflows | api\workflow_api.py | 337 |
| POST |  | create_workflow | api\workflow_api.py | 374 |
| GET | /{workflow_id} | get_workflow | api\workflow_api.py | 430 |
| DELETE | /{workflow_id} | delete_workflow | api\workflow_api.py | 468 |
| POST | /{workflow_id}/execute | execute_workflow | api\workflow_api.py | 493 |
| GET | /executions/{execution_id} | get_execution_status | api\workflow_api.py | 546 |
| POST | /executions/{execution_id}/pause | pause_execution | api\workflow_api.py | 585 |
| POST | /executions/{execution_id}/resume | resume_execution | api\workflow_api.py | 620 |
| POST | /executions/{execution_id}/modify | modify_execution | api\workflow_api.py | 654 |
| POST | /executions/{execution_id}/cancel | cancel_execution | api\workflow_api.py | 703 |
| GET | /status | get_training_status | api\world_model_api.py | 40 |
| GET | /accuracy | get_prediction_accuracy | api\world_model_api.py | 74 |
| GET | /loss_curve | get_loss_curve | api\world_model_api.py | 106 |
| GET | /task/{task_id} | get_task_status | api\world_model_api.py | 123 |
| POST | /train | start_training | api\world_model_api.py | 142 |
| POST | /stop | stop_training | api\world_model_api.py | 175 |
| POST | /feedback/response | submit_response_feedback | api\routes\rlhf.py | 94 |
| POST | /feedback/task | submit_task_feedback | api\routes\rlhf.py | 165 |
| POST | /experience/usage | record_experience_usage | api\routes\rlhf.py | 229 |
| GET | /stats | get_rlhf_stats | api\routes\rlhf.py | 257 |
| GET | /recent | get_recent_feedback | api\routes\rlhf.py | 293 |
| POST | /admin/export-dpo | export_dpo_dataset | api\routes\rlhf.py | 321 |
| POST | /quick-feedback | quick_feedback | api\routes\rlhf.py | 353 |
| POST | /accept | accept_proposal | api\routes\weak_connection.py | 33 |
| GET | /config | get_config | api\routes\weak_connection.py | 74 |
| POST | /config | update_config | api\routes\weak_connection.py | 81 |
| GET | /status | get_status | api\routes\weak_connection.py | 89 |
| GET | /klines/{symbol} | get_klines | core\btc_integration\api_bridge.py | 760 |
| GET | /status/{symbol} | get_status | core\btc_integration\api_bridge.py | 777 |
| GET | /summary | get_summary | core\btc_integration\api_bridge.py | 792 |
| GET | /health | health_check | core\btc_integration\api_bridge.py | 804 |
| GET | /account | get_account | core\btc_integration\api_bridge.py | 817 |
| POST | /trade | execute_trade | core\btc_integration\api_bridge.py | 831 |
| POST | /close | close_position_endpoint | core\btc_integration\api_bridge.py | 859 |
| POST | /config/switch | switch_config | core\btc_integration\api_bridge.py | 880 |
| GET | / | root | core\btc_integration\start_ai_trading.py | 69 |
| GET | /status | get_status | core\btc_integration\start_ai_trading.py | 76 |
| GET | /report | get_report | core\btc_integration\start_ai_trading.py | 83 |
| GET | /report.md | get_report_md | core\btc_integration\start_ai_trading.py | 90 |
| POST | /intervene | intervene | core\btc_integration\start_ai_trading.py | 97 |
| POST | /start_agent | start_agent | core\btc_integration\start_ai_trading.py | 116 |
| POST | /stop_agent | stop_agent | core\btc_integration\start_ai_trading.py | 125 |
| GET | /events | get_events | core\btc_integration\start_ai_trading.py | 134 |
| POST | /start | start_long_task | core\task\long_task_api.py | 499 |
| POST | /pause | pause_task | core\task\long_task_api.py | 504 |
| POST | /requirements | submit_requirements | core\task\long_task_api.py | 517 |
| POST | /confirm | process_user_confirmation | core\task\long_task_api.py | 522 |
| POST | /resume | resume_task | core\task\long_task_api.py | 527 |
| GET | /{task_id}/status | get_task_status | core\task\long_task_api.py | 535 |
| GET | /active | list_active_tasks | core\task\long_task_api.py | 540 |
| GET | /{task_id}/pause-prompt | get_pause_prompt | core\task\long_task_api.py | 545 |

## 4. Hook 注册

> 共发现 31 处 Hook 注册（去重后）

| Hook名称 | 注册函数 | 所在文件 | 行号 | 优先级 | 触发时机 |
|---|---|---|---|---|---|
| core_logic_hooks | `agent_loop_hooks` | core\agent\agent_loop.py | 3510 | N/A | 核心逻辑Hook批量注册 |
| after_tool | `vision_hook.after_tool_async, priority=20` | core\agent\agent_loop.py | 3470 | N/A | agent_loop_hooks.register() 动态注册 |
| after_tool | `tool_hook.after_tool_async, priority=10` | core\agent\agent_loop.py | 3471 | N/A | agent_loop_hooks.register() 动态注册 |
| after_tool | `voice_hook.after_tool, priority=30` | core\agent\agent_loop.py | 3472 | N/A | agent_loop_hooks.register() 动态注册 |
| before_prompt | `voice_hook.before_prompt, priority=30` | core\agent\agent_loop.py | 3475 | N/A | agent_loop_hooks.register() 动态注册 |
| after_prompt | `safety_hook.after_prompt, priority=50` | core\agent\agent_loop.py | 3476 | N/A | agent_loop_hooks.register() 动态注册 |
| after_prompt | `voice_hook.after_prompt, priority=30` | core\agent\agent_loop.py | 3477 | N/A | agent_loop_hooks.register() 动态注册 |
| before_tool | `safety_hook.before_tool, priority=50` | core\agent\agent_loop.py | 3480 | N/A | agent_loop_hooks.register() 动态注册 |
| after_loop | `tool_hook.after_loop_async, priority=10` | core\agent\agent_loop.py | 3484 | N/A | agent_loop_hooks.register() 动态注册 |
| after_loop | `voice_hook.after_loop, priority=30` | core\agent\agent_loop.py | 3485 | N/A | agent_loop_hooks.register() 动态注册 |
| before_step | `tool_hook.before_step_async, priority=10` | core\agent\agent_loop.py | 3489 | N/A | agent_loop_hooks.register() 动态注册 |
| after_step | `tool_hook.after_step_async, priority=10` | core\agent\agent_loop.py | 3490 | N/A | agent_loop_hooks.register() 动态注册 |
| on_complete | `voice_hook.on_complete, priority=30` | core\agent\agent_loop.py | 3493 | N/A | agent_loop_hooks.register() 动态注册 |
| on_plan | `voice_hook.on_plan, priority=30` | core\agent\agent_loop.py | 3494 | N/A | agent_loop_hooks.register() 动态注册 |
| on_layer_switch | `voice_hook.on_layer_switch, priority=30` | core\agent\agent_loop.py | 3495 | N/A | agent_loop_hooks.register() 动态注册 |
| on_pause | `voice_hook.on_pause, priority=30` | core\agent\agent_loop.py | 3496 | N/A | agent_loop_hooks.register() 动态注册 |
| on_resume | `voice_hook.on_resume, priority=30` | core\agent\agent_loop.py | 3497 | N/A | agent_loop_hooks.register() 动态注册 |
| on_terminate | `voice_hook.on_terminate, priority=30` | core\agent\agent_loop.py | 3498 | N/A | agent_loop_hooks.register() 动态注册 |
| on_user_assist | `voice_hook.on_user_assist, priority=30` | core\agent\agent_loop.py | 3499 | N/A | agent_loop_hooks.register() 动态注册 |
| on_world_model | `voice_hook.on_world_model, priority=30` | core\agent\agent_loop.py | 3500 | N/A | agent_loop_hooks.register() 动态注册 |
| on_understanding_confirmed | `voice_hook.on_understanding_confirmed, priority=30` | core\agent\agent_loop.py | 3501 | N/A | agent_loop_hooks.register() 动态注册 |
| on_error | `voice_hook.on_error, priority=30` | core\agent\agent_loop.py | 3502 | N/A | agent_loop_hooks.register() 动态注册 |
| on_moral_blocked | `voice_hook.on_moral_blocked, priority=30` | core\agent\agent_loop.py | 3503 | N/A | agent_loop_hooks.register() 动态注册 |
| after_tool | `my_after_tool` | core\agent\agent_loop_hooks.py | 31 | N/A | agent_loop_hooks.register() 动态注册 |
| tool_execution | `tool_execution_phase` | core\agent\async_tool_gateway.py | 203 | 3 | 阶段注册 |
| context_assembly | `assemble_context_phase` | core\agent\context_assembler.py | 722 | 1 | 阶段注册 |
| prompt_assembly | `prepare_prompt_fragments_async` | core\agent\prompt_assembly_bridge.py | 140 | 2 | 阶段注册 |
| core_logic_hooks | `agent_loop_hooks` | core\agent\hooks\core_logic_hooks.py | 17 | N/A | 核心逻辑Hook批量注册 |
| core_logic_hooks | `hooks_instance` | core\agent\hooks\core_logic_hooks.py | 456 | N/A | 核心逻辑Hook批量注册 |
| intent | `intent_placeholder` | core\agent\phases\intent_phase.py | 10 | 1 | 阶段注册 |
| tool_call | `tool_call_phase` | core\intent\intent_handler.py | 1437 | 3 | 阶段注册 |


---

## 4. 数据流与持久化层
## 5. 前端-后端 API 契约

以下完整分析来自子报告 Agent D（已审核）。


# SiliconBase V5 代码审计报告 —— 数据流、持久化层与 API 契约

> 审计时间: 2026-05-15
> 审计范围: core/prompt, core/agent, core/btc_integration, core/memory, api/, frontend/src

---

## 一、关键函数的参数数据流

### 1.1 finalize() 参数溯源

**被审计函数**: `PromptFinalizer.finalize()` / `finalize_async()`  
**文件**: `SiliconBase_V5/core/prompt/prompt_finalizer.py` (第51-240行)  
**直接调用者**: `core/agent/hooks/core_logic_hooks.py::hook_context_assemble()` (第282行)

| 参数名 | 类型 | 来源函数 | 来源文件 | 来源行号 | 说明 |
|---|---|---|---|---|---|
| `user_id` | `str` | `AgentLoop._run_agent_loop_async_impl()` | `core/agent/agent_loop.py` | ~1140 | 从 `ctx.user_id` 传入，最初来自会话管理 |
| `user_instruction` | `str` | `AgentLoop._run_agent_loop_async_impl()` | `core/agent/agent_loop.py` | ~1140 | `ctx.task.instruction`，用户原始输入 |
| `working_memory` | `Any` | `AgentLoop._run_agent_loop_async_impl()` | `core/agent/agent_loop.py` | ~1140 | 循环初始化时构造的工作记忆对象 |
| `work_mode` | `str` | `AgentLoop._run_agent_loop_async_impl()` | `core/agent/agent_loop.py` | ~1152 | `ctx.extra['work_mode']`，如 "daily"/"focus" |
| `effective_task_id` | `str` | `AgentLoop._run_agent_loop_async_impl()` | `core/agent/agent_loop.py` | ~1159 | `ctx.extra['effective_task_id']`，当前任务ID |
| `phase_anchor_manager` | `Any` | `AgentLoop._run_agent_loop_async_impl()` | `core/agent/agent_loop.py` | ~1160 | `ctx.extra['phase_anchor_manager']`，阶段锚点管理器 |
| `last_vision_description` | `Optional[str]` | `AgentLoop._run_agent_loop_async_impl()` | `core/agent/agent_loop.py` | ~1161 | `ctx.extra['last_vision_description']`，视觉系统输出 |
| `assembler` | `Any` | `AgentLoop._run_agent_loop_async_impl()` | `core/agent/agent_loop.py` | ~1154 | `ctx.extra['assembler']` = `_phase_assembler`，ContextAssembler实例 |
| `smart_context` | `Dict[str, str]` | `AgentLoop._run_agent_loop_async_impl()` | `core/agent/agent_loop.py` | **1099** | 由 `build_smart_context()` 生成（见 1.2 节） |
| `perception_context` | `str` | `core_logic_hooks.hook_perception_inject()` | `core/agent/hooks/core_logic_hooks.py` | ~129 | 由 `PerceptionManager.format_for_prompt()` 生成（见 1.2 节） |
| `memory_context` | `str` | `core_logic_hooks.hook_context_assemble()` | `core/agent/hooks/core_logic_hooks.py` | ~236 | `await assembler.assemble_memory_context(...)` 返回值 |
| `exploration_enhancement` | `str` | `prepare_prompt_fragments_async()` | `core/agent/prompt_assembly_bridge.py` | ~258 | `_fragments.exploration_enhancement` |
| `layer_prompt` | `str` | `prepare_prompt_fragments_async()` | `core/agent/prompt_assembly_bridge.py` | ~259 | `_fragments.layer_prompt` |
| `three_views_prompt` | `str` | `prepare_prompt_fragments_async()` | `core/agent/prompt_assembly_bridge.py` | ~260 | `_fragments.three_views_prompt`，来自 `ContextAssembler.assemble_three_views()` |
| `reflection_context` | `str` | `prepare_prompt_fragments_async()` | `core/agent/prompt_assembly_bridge.py` | ~261 | `_fragments.reflection_section` |
| `experience_context` | `str` | `prepare_prompt_fragments_async()` | `core/agent/prompt_assembly_bridge.py` | ~262 | `_fragments.experience_context`，来自 `ContextAssembler.assemble_experience_context()` |
| `world_model_section` | `str` | `prepare_prompt_fragments_async()` | `core/agent/prompt_assembly_bridge.py` | ~263 | `_fragments.world_model_section` |
| `execution_history` | `List[Dict]` | `AgentLoop._run_agent_loop_async_impl()` | `core/agent/agent_loop.py` | ~1151 | `ctx.extra['execution_history']`，工具执行历史 |
| `session_id` | `str` | `AgentLoop._run_agent_loop_async_impl()` | `core/agent/agent_loop.py` | ~1162 | `ctx.session_id`，当前会话ID |
| `round_count` | `int` | `AgentLoop._run_agent_loop_async_impl()` | `core/agent/agent_loop.py` | ~280 | `loop_state.round_count`，当前轮次计数 |

**返回值去向**:
- `full_system_prompt` -> `ctx.extra['full_system_prompt']` -> 后续 `ai_client.chat_async()` 消费
- `budget_report` -> `ctx.extra['budget_report']` -> 用于调试/Token审计

---

### 1.2 smart_context 与 perception_context 构造路径

#### smart_context 构造链路

```
AgentLoop._run_agent_loop_async_impl()
  └─> build_smart_context()                       [core/prompt/smart_prompt_engine.py:727]
      └─> SmartPromptEngine.build_smart_context_async()
          [core/prompt/smart_prompt_engine.py:84]
          ├─> _get_user_context_async(session_id)   → 查用户上下文
          ├─> _get_system_context()                 → 系统配置
          └─> MemoryService 检索相关记忆
              → 返回 Dict[str, str] 含 system_prompt/reasoning_framework 等
```

#### perception_context 构造链路

```
AgentLoop._run_agent_loop_async_impl()
  └─> hook_ctx.extra['perception_manager'] = perception_manager
      [core/agent/agent_loop.py:1149]
      
hook_perception_inject() (before_prompt Hook, priority=90)
  [core/agent/hooks/core_logic_hooks.py:84]
  └─> perception_manager.should_trigger_perception(user_instruction, info)
      └─> perception_manager.get_perception(user_input, context)
          [core/vision/perception_manager.py:932]
          └─> 查询桌面感知/环境数据
      └─> perception_manager.format_for_prompt(perception)
          [core/vision/perception_manager.py:1730]
          → 生成格式化字符串 → ctx.extra['perception_context']
```

**特殊注入**: BTC 交易上下文在 `hook_context_assemble()` 中合并到 `perception_context`：
```python
btc_context = ctx.extra.get('btc_context', '')
perception_context = f"{perception_context}\n\n{btc_context}".strip()
```

---

### 1.3 _make_decision() 市场数据流

**被审计函数**: `TradingSubAgent._make_decision()`  
**文件**: `SiliconBase_V5/core/btc_integration/trading_subagent.py` (第624-754行)

**市场数据流入路径**:

| 阶段 | 函数/模块 | 文件 | 行号 | 说明 |
|---|---|---|---|---|
| 1. 数据获取 | `_collect_market_data()` | `trading_subagent.py` | 1534 | 主入口 |
| 2. 行情提供者 | `get_market_data_provider()` | `core/btc_integration/market_data.py` | 48 | OKXMarketDataProvider |
| 3. 实时价格 | `provider.get_price(symbol)` | `market_data.py` | 64 | 调用 OKX REST API `/api/v5/market/ticker` |
| 4. K线数据 | `provider.get_klines(...)` | `market_data.py` | ~120 | 调用 OKX `/api/v5/market/candles` |
| 5. 数据聚合 | `_collect_market_data()` 返回 Dict | `trading_subagent.py` | 1546 | 含 price, change_24h, klines 等 |
| 6. 上下文封装 | `TradingContext(market_data=...)` | `trading_subagent.py` | 598 | 封装为 dataclass |
| 7. 决策入口 | `_make_decision(context)` | `trading_subagent.py` | 609 | 接收 TradingContext |
| 8. 市场分析 | `_analyze_market(market_data)` | `trading_subagent.py` | 628 | 计算 RSI/SMA/趋势/波动率 |
| 9. Prompt 构建 | `_build_decision_prompt(...)` | `trading_subagent.py` | 824 | 将 market_data JSON 注入 prompt |
| 10. AI 决策 | `ai_client.chat_async([{"role":"user","content":prompt}])` | `trading_subagent.py` | 777 | Ollama/qwen3:8b 模型 |

**降级路径**: AI 不可用时 → `_rule_based_decision()` (第898行)

---

### 1.4 retrieve_memory() query 溯源

**被审计函数**: `MemoryManager.retrieve_memory()`  
**文件**: `SiliconBase_V5/core/memory/memory_manager.py` (第1105行)

**query 参数来源矩阵**:

| 调用方文件 | 调用行 | query 值 | 说明 |
|---|---|---|---|
| `core/agent/checkpoint_manager.py` | 1553 | `None` | 按 scene/layer 过滤，无语义查询 |
| `core/memory/checkpoint_memory_bridge.py` | 814 | 动态传入 | 从 checkpoint 查询传入 |
| `core/btc_integration/trading_subagent.py` | 1720 | `json.dumps(context.market_data, default=str)` | 交易决策时将市场数据序列化为查询 |
| `core/btc_integration/trading_memory.py` | 239 | `None` | 按 mem_type=TRADING 过滤 |
| `core/btc_integration/trading_memory.py` | 305 | `None` | 按 mem_type=STRATEGY_EVOLUTION 过滤 |
| `core/btc_integration/trading_memory.py` | 380 | 动态 query | 市场模式匹配时传入 |
| `core/btc_integration/trading_memory.py` | 471 | `None` | 按 mem_type=TRADING_DECISION 过滤 |
| `core/memory/memory_manager.py` (内部) | 1343 | 动态传入 | `query_large_dataset` 批量查询 |
| `core/memory/memory_manager.py` (内部) | 1657 | `None` | 兼容旧 `get()` 接口 |
| `core/memory/memory_manager.py` (内部) | 1691 | `None` | `get_recent_memories` 时间过滤 |
| `core/memory/memory_manager.py` (内部) | 1721 | `None` | `get_high_value_memories` 评分过滤 |
| `core/memory/memory_manager.py` (内部) | 2009 | `"*"` | `compress_memories` 全量扫描 |
| `core/memory/memory_manager.py` (内部) | 2048 | `"*"` | `compress_memories` 分层扫描 |

**关键结论**: `query` 参数并非总是来自用户原始输入。在交易场景中，它由 `market_data` JSON 序列化而来；在记忆维护场景中，它可能是 `"*"` 或 `None`。用户原始输入的转化链路为：
```
用户输入 → AgentLoop.task.instruction → build_smart_context / PerceptionManager
→ 可能作为 query 传入 MemoryManager.retrieve_memory()
```
但 `retrieve_memory()` 的 `query` 主要用于**向量语义检索**（`vector_store.search("knowledge", query, ...)`），若 `query=None` 则跳过向量层，仅查 PostgreSQL。

---

## 二、数据库与持久化层

### 2.1 PostgreSQL 表定义汇总

#### 2.1.1 `memories` —— 核心记忆表

| 字段 | 类型 | 索引 | 所在文件 |
|---|---|---|---|
| `id` | `VARCHAR(64) PRIMARY KEY` | PK | `core/db/connection_pool.py:356` |
| `user_id` | `VARCHAR(64) NOT NULL` | 复合索引 `idx_user_layer`, `idx_user_type` | 同上 |
| `layer` | `VARCHAR(20) NOT NULL` | 复合索引 `idx_user_layer` | 同上 |
| `mem_type` | `VARCHAR(50) NOT NULL` | 复合索引 `idx_user_type` | 同上 |
| `content` | `TEXT NOT NULL` | — | 同上 |
| `scene` | `VARCHAR(255)` | `idx_scene` | 同上 |
| `rating` | `INTEGER DEFAULT 0` | `idx_rating` | 同上 |
| `value_assessment` | `JSONB` (默认值六维评分 C 级) | — | 同上 |
| `context` | `JSONB` | — | 同上 |
| `created_at` | `TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP` | — | 同上 |
| `expire_at` | `TIMESTAMP WITH TIME ZONE` | `idx_expire` | 同上 |
| `compressed` | `INTEGER DEFAULT 0` | — | 同上 |
| `updated_at` | `TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP` | — | 同上 |
| `source` | `VARCHAR(20) DEFAULT 'system'` | — | 同上 (ALTER添加) |
| `creator` | `VARCHAR(20) DEFAULT 'system'` | — | 同上 (ALTER添加) |

**同构定义**: `scripts/init_postgres.py:50`, `scripts/init_database.py:84`

#### 2.1.2 `phase_anchors` —— 阶段锚点表

| 字段 | 类型 | 索引 | 所在文件 |
|---|---|---|---|
| `id` | `VARCHAR(255) PRIMARY KEY` | PK | `core/memory/phase_anchor.py:111` |
| `task_id` | `VARCHAR(255) NOT NULL` | `idx_phase_anchors_task_id` | 同上 |
| `phase` | `VARCHAR(255) NOT NULL` | — | 同上 |
| `user_id` | `VARCHAR(255) DEFAULT 'default'` | `idx_phase_anchors_user_id` | 同上 |
| `session_id` | `VARCHAR(255) DEFAULT ''` | — | 同上 |
| `data` | `JSONB` | — | 同上 |
| `created_at` | `TIMESTAMP DEFAULT CURRENT_TIMESTAMP` | `idx_phase_anchors_created_at` | 同上 |
| `updated_at` | `TIMESTAMP DEFAULT CURRENT_TIMESTAMP` | — | 同上 |

#### 2.1.3 `memory_associations` —— 记忆关联表

| 字段 | 类型 | 索引 | 所在文件 |
|---|---|---|---|
| `id` | `SERIAL PRIMARY KEY` | PK | `core/memory/memory_associations.py:184` |
| `source_mem_id` | `VARCHAR(64) NOT NULL` | `idx_assoc_source` | 同上 |
| `target_mem_id` | `VARCHAR(64) NOT NULL` | `idx_assoc_target` | 同上 |
| `user_id` | `VARCHAR(64) NOT NULL` | `idx_assoc_user` | 同上 |
| `relation_type` | `VARCHAR(50) NOT NULL` | `idx_assoc_type_score` | 同上 |
| `relation_score` | `FLOAT DEFAULT 0.0` | `idx_assoc_type_score` | 同上 |
| `relation_data` | `JSONB DEFAULT '{}'` | — | 同上 |
| `created_at` | `TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP` | `idx_assoc_created` | 同上 |
| **UNIQUE** | `(source_mem_id, target_mem_id, relation_type)` | — | 同上 |

#### 2.1.4 `token_usage` —— Token 消耗记录

| 字段 | 类型 | 索引 | 所在文件 |
|---|---|---|---|
| `id` | `SERIAL PRIMARY KEY` | PK | `core/cost/cost_manager.py:296` |
| `user_id` | `VARCHAR(255) NOT NULL` | `idx_token_usage_user_id` | 同上 |
| `session_id` | `VARCHAR(255)` | — | 同上 |
| `model` | `VARCHAR(100) NOT NULL` | `idx_token_usage_model` | 同上 |
| `input_tokens` | `INTEGER DEFAULT 0` | — | 同上 |
| `output_tokens` | `INTEGER DEFAULT 0` | — | 同上 |
| `total_tokens` | `INTEGER DEFAULT 0` | — | 同上 |
| `input_cost` | `DECIMAL(15,6) DEFAULT 0` | — | 同上 |
| `output_cost` | `DECIMAL(15,6) DEFAULT 0` | — | 同上 |
| `total_cost` | `DECIMAL(15,6) DEFAULT 0` | — | 同上 |
| `request_type` | `VARCHAR(50) DEFAULT 'chat'` | — | 同上 |
| `metadata` | `JSONB` | — | 同上 |
| `created_at` | `TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP` | `idx_token_usage_created_at` | 同上 |

#### 2.1.5 `cost_stats` —— 费用聚合统计

| 字段 | 类型 | 索引 | 所在文件 |
|---|---|---|---|
| `id` | `SERIAL PRIMARY KEY` | PK | `core/cost/cost_manager.py:326` |
| `user_id` | `VARCHAR(255) NOT NULL` | — | 同上 |
| `stat_type` | `VARCHAR(20) NOT NULL` | — | 同上 |
| `stat_date` | `DATE NOT NULL` | — | 同上 |
| `model` | `VARCHAR(100)` | — | 同上 |
| `total_requests` | `INTEGER DEFAULT 0` | — | 同上 |
| `total_input_tokens` | `BIGINT DEFAULT 0` | — | 同上 |
| `total_output_tokens` | `BIGINT DEFAULT 0` | — | 同上 |
| `total_tokens` | `BIGINT DEFAULT 0` | — | 同上 |
| `total_cost` | `DECIMAL(15,6) DEFAULT 0` | — | 同上 |
| `created_at` | `TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP` | — | 同上 |
| `updated_at` | `TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP` | — | 同上 |
| **UNIQUE** | `(user_id, stat_type, stat_date, model)` | — | 同上 |

### 2.2 ORM / Peewee / SQLAlchemy 检查

- **未发现 SQLAlchemy declarative_base() 使用**: 项目采用 **原始 SQL + psycopg2** 直接操作 PostgreSQL，无 SQLAlchemy ORM 层。
- **未发现 Peewee Model**: 同上。
- **向量层**: `core/memory/memory_service.py` 中可能使用 `VectorStore`，但属于向量数据库（如 pgvector/Chroma），非关系型表定义。

---

## 三、前端-后端 API 契约

### 3.1 前端调用层总览

前端主要封装在 `frontend/src/utils/api/` 目录：

| 前端 API 封装文件 | 核心函数 | 底层调用方式 |
|---|---|---|
| `utils/api/core.ts` | `fetchAPI()`, `get/post/put/patch/delete()` | `fetch()` + Bearer Token |
| `utils/auth.ts` | `login()`, `logout()`, `me()`, `register()` | `fetch(buildApiUrl(...))` |
| `utils/apiClient.ts` | 通用 fetch 封装 | `fetch()` |
| `stores/modeStore.ts` | 模式切换 | `fetch()` |
| `stores/tradingStore.ts` | 交易数据获取 | `fetchAPI()` |
| `hooks/useWebSocket.tsx` | WebSocket 统一封装 | `new WebSocket()` |

### 3.2 前后端 API 匹配表（代表性端点）

> 后端路由前缀规则：`cloud_api.py` 中统一 `app.include_router(router, prefix="/api")`，因此前端 `/api/xxx` 对应后端 router 的 `prefix + path`。

| 前端调用点 | HTTP方法 | API路径 | 后端Handler文件 | 后端函数 | 请求DTO | 响应DTO |
|---|---|---|---|---|---|---|
| `auth.ts:107` | POST | `/api/auth/login` | `api/auth_utils.py` | `login()` (动态调用) | 动态 | Token |
| `auth.ts:269` | POST | `/api/auth/logout` | `api/auth_utils.py` | `logout()` | — | — |
| `auth.ts:437` | POST | `/api/auth/change-password` | `api/auth_utils.py` | `change_password()` | — | — |
| `auth.ts:490` | GET | `/api/auth/me` | `api/auth_utils.py` | `me()` | — | UserInfo |
| `stores/modeStore.ts:52` | POST | `/api/mode` | `api/cloud_api.py` (推测) | 动态调用，需运行时确认 | `{mode}` | — |
| `utils/api/session.ts:34` | POST | `/api/sessions` | `api/session_api.py` | `create_session()` | SessionCreate | Session |
| `utils/api/session.ts:78` | GET | `/api/sessions` | `api/session_api.py` | `list_sessions()` | — | SessionList |
| `utils/api/session.ts:107` | GET | `/api/sessions/{id}` | `api/session_api.py` | `get_session()` | — | Session |
| `utils/api/task.ts:142` | POST | `/api/tasks/{id}/pause` | `api/cloud_api.py` | 动态调用，需运行时确认 | — | — |
| `utils/api/task.ts:191` | POST | `/api/tasks/{id}/resume` | `api/cloud_api.py` | 动态调用，需运行时确认 | — | — |
| `utils/api/task.ts:238` | DELETE | `/api/tasks/{id}` | `api/cloud_api.py` / `task_api.py` | 动态调用，需运行时确认 | — | — |
| `utils/api/metrics.ts:56` | GET | `/api/metrics/system` | `api/metrics_api.py` | `get_system_metrics()` | — | SystemMetrics |
| `utils/api/metrics.ts:68` | GET | `/api/metrics/tasks` | `api/metrics_api.py` | `get_task_metrics()` | — | TaskMetrics |
| `utils/api/metrics.ts:80` | GET | `/api/metrics/memory` | `api/metrics_api.py` | `get_memory_metrics()` | — | MemoryMetrics |
| `utils/api/metrics.ts:92` | GET | `/api/metrics/reflections` | `api/metrics_api.py` | `get_reflection_metrics()` | — | ReflectionList |
| `utils/api/worldModel.ts:43` | GET | `/api/world_model/status` | `api/world_model_api.py` | `get_training_status()` | — | TrainingStats |
| `utils/api/worldModel.ts:55` | GET | `/api/world_model/accuracy` | `api/world_model_api.py` | `get_prediction_accuracy()` | — | PredictionAccuracy |
| `utils/api/worldModel.ts:67` | GET | `/api/world_model/loss_curve` | `api/world_model_api.py` | `get_loss_curve()` | — | LossCurvePoint[] |
| `utils/api/worldModel.ts:91` | POST | `/api/world_model/train` | `api/world_model_api.py` | `start_training()` | TrainRequest | — |
| `utils/api/worldModel.ts:105` | POST | `/api/world_model/stop` | `api/world_model_api.py` | `stop_training()` | — | — |
| `utils/api/siliconLife.ts:127` | GET | `/api/life/state` | `api/silicon_life_api.py` | `get_life_state()` | — | LifeState |
| `utils/api/siliconLife.ts:141` | GET | `/api/life/timeline` | `api/silicon_life_api.py` | `get_timeline()` | — | Timeline |
| `utils/api/siliconLife.ts:154` | GET | `/api/life/memory-pyramid` | `api/silicon_life_api.py` | `get_memory_pyramid()` | — | MemoryPyramidData |
| `utils/api/siliconLife.ts:166` | GET | `/api/life/learning-stats` | `api/silicon_life_api.py` | `get_learning_stats()` | — | LearningStats |
| `utils/api/siliconLife.ts:178` | GET | `/api/life/summary` | `api/silicon_life_api.py` | `get_summary()` | — | GrowthSummary |
| `stores/tradingStore.ts:317` | GET | `/api/trading/symbols` | `api/trading_api.py` | `list_symbols()` | — | List[TradingSymbol] |
| `stores/tradingStore.ts:331` | DELETE | `/api/trading/symbols/{symbol}` | `api/trading_api.py` | `delete_symbol()` | — | — |
| `stores/tradingStore.ts:414` | GET | `/api/trading/klines/{symbol}` | `api/trading_api.py` | `get_klines()` | Query: interval, limit | List[KLineData] |
| `stores/tradingStore.ts:450` | GET | `/api/trading/mode/ai/status` | `api/trading_mode_api.py` | `get_ai_status()` | — | AIStatus |
| `stores/tradingStore.ts:466` | GET | `/api/trading/mode/prediction` | `api/trading_mode_api.py` | `get_prediction()` | Query: symbol, action | Prediction |
| `stores/tradingStore.ts:488` | GET | `/api/trading/mode/status` | `api/trading_mode_api.py` | `get_mode_status()` | — | ModeStatus |
| `stores/tradingStore.ts:720` | GET | `/api/trading/mode/manual/positions` | `api/trading_mode_api.py` | `get_manual_positions()` | — | Positions |
| `utils/api/intervention.ts:27` | POST | `/api/sessions/{id}/interrupt` | `api/interrupt_api.py` | `interrupt_session()` | — | — |
| `utils/api/intervention.ts:56` | POST | `/api/tasks/{id}/pause` | `api/cloud_api.py` (推测) | 动态调用，需运行时确认 | — | — |
| `utils/api/intervention.ts:88` | POST | `/api/tasks/{id}/resume` | `api/cloud_api.py` (推测) | 动态调用，需运行时确认 | — | — |
| `utils/api/intervention.ts:120` | POST | `/api/tasks/{id}/cancel` | `api/cloud_api.py` (推测) | 动态调用，需运行时确认 | — | — |
| `utils/api/intervention.ts:148` | POST | `/api/trading/mode/ai/pause` | `api/trading_mode_api.py` | `pause_ai_trading()` | — | — |
| `utils/api/intervention.ts:175` | POST | `/api/trading/mode/ai/resume` | `api/trading_mode_api.py` | `resume_ai_trading()` | — | — |
| `utils/api/intervention.ts:202` | POST | `/api/trading/mode/ai/stop` | `api/trading_mode_api.py` | `stop_ai_trading()` | — | — |
| `utils/api/config.ts:96` | GET | `/api/config` | `api/config_api.py` | `get_config()` | — | ConfigData |
| `utils/api/config.ts:108` | GET | `/api/config/schema` | `api/config_api.py` | `get_config_schema()` | — | ConfigSchema |
| `utils/api/config.ts:133` | POST | `/api/config` | `api/config_api.py` | `update_config()` | ConfigUpdate | Msg |
| `utils/api/config.ts:148` | GET | `/api/config/yaml` | `api/config_api.py` | `get_yaml_config()` | — | YamlConfig |
| `utils/api/config.ts:160` | POST | `/api/config/yaml` | `api/config_api.py` | `update_yaml_config()` | YamlBody | Msg |
| `utils/api/toolMarket.ts:70` | GET | `/api/cloud-tools/list` | `api/cloud_tool_repo.py` | `list_tools()` | Query params | ToolList |
| `utils/api/toolMarket.ts:87` | GET | `/api/cloud-tools/{id}` | `api/cloud_tool_repo.py` | `get_tool()` | — | ToolDetail |
| `utils/api/toolMarket.ts:98` | GET | `/api/cloud-tools/{id}/versions` | `api/cloud_tool_repo.py` | `get_versions()` | — | Versions |
| `utils/api/toolMarket.ts:109` | POST | `/api/tool-market/install` | `api/tool_market_api.py` | `install_tool()` | InstallReq | InstallResp |
| `utils/api/toolMarket.ts:124` | GET | `/api/tool-market/installed` | `api/tool_market_api.py` | `get_installed_tools()` | — | InstalledTool[] |
| `utils/api/toolMarket.ts:135` | POST | `/api/tool-market/uninstall/{id}` | `api/tool_market_api.py` | `uninstall_tool()` | — | boolean |
| `utils/api/toolMarket.ts:144` | POST | `/api/tool-market/check-updates` | `api/tool_market_api.py` | `check_updates()` | — | UpdateInfo[] |
| `utils/api/toolMarket.ts:157` | GET | `/api/tool-market/task/{id}` | `api/tool_market_api.py` | `get_install_task()` | — | TaskStatus |
| `utils/api/toolMarket.ts:167` | GET | `/api/cloud-tools/{id}/{ver}/download` | `api/cloud_tool_repo.py` | `download_tool()` | — | Blob |
| `pages/ToolMarketPage.tsx:102` | GET | `/api/cloud-tools/list?{params}` | `api/cloud_tool_repo.py` | `list_tools()` | Query | ToolList |
| `pages/ToolMarketPage.tsx:118` | GET | `/api/cloud-tools/{id}` | `api/cloud_tool_repo.py` | `get_tool()` | — | ToolDetail |
| `pages/ToolMarketPage.tsx:130` | GET | `/api/cloud-tools/{id}/versions` | `api/cloud_tool_repo.py` | `get_versions()` | — | Versions |
| `pages/ToolMarketPage.tsx:143` | POST | `/api/tool-market/install` | `api/tool_market_api.py` | `install_tool()` | InstallReq | TaskId |
| `pages/ToolMarketPage.tsx:157` | GET | `/api/tool-market/installed` | `api/tool_market_api.py` | `get_installed_tools()` | — | InstalledTool[] |
| `pages/ToolMarketPage.tsx:169` | POST | `/api/tool-market/uninstall/{id}` | `api/tool_market_api.py` | `uninstall_tool()` | — | boolean |
| `pages/ToolMarketPage.tsx:180` | POST | `/api/tool-market/check-updates` | `api/tool_market_api.py` | `check_updates()` | — | UpdateInfo[] |
| `pages/ToolMarketPage.tsx:195` | GET | `/api/tool-market/task/{id}` | `api/tool_market_api.py` | `get_install_task()` | — | TaskStatus |
| `utils/api/reflection.ts:68` | GET | `/api/reflection/status` | `api/cloud_api.py` (推测) | 动态调用，需运行时确认 | — | ReflectionStatus |
| `utils/api/reflection.ts:82` | POST | `/api/reflections/{id}/feedback` | `api/cloud_api.py` (推测) | 动态调用，需运行时确认 | FeedbackReq | Msg |
| `utils/api/reflection.ts:100` | GET | `/api/reflection/config` | `api/cloud_api.py` (推测) | 动态调用，需运行时确认 | — | Config |
| `utils/api/reflection.ts:114` | POST | `/api/reflection/config` | `api/cloud_api.py` (推测) | 动态调用，需运行时确认 | Config | Msg |
| `utils/api/reflection.ts:140` | GET | `/api/reflections` | `api/cloud_api.py` (推测) | 动态调用，需运行时确认 | Query: limit | ReflectionList |
| `utils/api/reflection.ts:154` | GET | `/api/reflections/{id}` | `api/cloud_api.py` (推测) | 动态调用，需运行时确认 | — | ReflectionRecord |
| `hooks/useGamification.tsx:82` | GET | `/api/gamification/status` | `api/gamification_api.py` | `get_status()` | — | GamificationStatus |
| `hooks/useGamification.tsx:100` | GET | `/api/gamification/level` | `api/gamification_api.py` | `get_level()` | — | LevelInfo |
| `hooks/useGamification.tsx:118` | POST | `/api/gamification/add-xp` | `api/gamification_api.py` | `add_xp()` | Query: xp_amount, source | — |
| `components/LifeStatusPanel.tsx:223` | GET | `/api/consciousness/status` | `api/consciousness_api.py` | `get_vital_signs()` | Query: user_id | VitalSigns |
| `components/LifeStatusPanel.tsx:238` | POST | `/api/consciousness/proposals/{id}/respond` | `api/consciousness_api.py` | `feedback_action()` | ActionFeedbackReq | ActionFeedbackResp |
| `components/PromptLayerNavigator.tsx:124` | POST | `/api/voice/announce` | `api/voice_announce_api.py` | `announce()` | VoiceAnnounceReq | — |
| `components/PromptLayerNavigator.tsx:140` | GET | `/api/prompt/layer/l1` | `api/prompt_layer_api.py` | `get_l1_prompt()` | — | PromptLayer |
| `components/PromptLayerNavigator.tsx:184` | GET | `/api/prompt/layer/l2` | `api/prompt_layer_api.py` | `get_l2_prompt()` | Query: tool_id | PromptLayer |
| `components/PromptLayerNavigator.tsx:225` | GET | `/api/prompt/layer/l3/{tool_id}` | `api/prompt_layer_api.py` | `get_l3_prompt()` | — | PromptLayer |
| `components/PromptLayerNavigator.tsx:265` | POST | `/api/prompt/layer/switch` | `api/prompt_layer_api.py` | `switch_layer()` | SwitchReq | — |
| `hooks/useVoiceState.tsx:155` | GET | `/api/v1/voice/status` | `api/voice_api.py` | `get_voice_status()` | — | VoiceStatus |
| `hooks/useSystemStatus.tsx:28` | GET | `/health` (无前缀) | `api/cloud_api.py` | `health_check()` | — | HealthStatus |
| `utils/api/globalView.ts:63` | GET | `/api/global-view/status` | `api/global_view_api.py` | `get_status()` | — | ScanStatus |
| `utils/api/globalView.ts:80` | GET | `/api/global-view/tree` | `api/global_view_api.py` | `get_tree()` | Query: path, depth | FileTree |
| `utils/api/globalView.ts:99` | GET | `/api/global-view/search` | `api/global_view_api.py` | `search()` | Query: q, limit | SearchResult |
| `utils/api/globalView.ts:110` | POST | `/api/global-view/scan/start` | `api/global_view_api.py` | `start_scan()` | — | Msg |
| `utils/api/globalView.ts:124` | POST | `/api/global-view/scan/stop` | `api/global_view_api.py` | `stop_scan()` | — | Msg |
| `utils/api/globalView.ts:137` | POST | `/api/global-view/clear` | `api/global_view_api.py` | `clear_cache()` | — | Msg |
| `utils/api/globalView.ts:150` | GET | `/api/global-view/stats` | `api/global_view_api.py` | `get_stats()` | — | FileStats |
| `utils/api/workflow.ts:228` | GET | `/api/workflows` | `api/workflow_api.py` | `list_workflows()` | — | WorkflowList |
| `utils/api/workflow.ts:251` | POST | `/api/workflows` | `api/workflow_api.py` | `create_workflow()` | WorkflowCreate | CreateResp |
| `utils/api/workflow.ts:282` | GET | `/api/workflows/{id}` | `api/workflow_api.py` | `get_workflow()` | — | WorkflowDetail |
| `utils/api/workflow.ts:310` | POST | `/api/workflows/{id}` | `api/workflow_api.py` | `update_workflow()` | WorkflowUpdate | Msg |
| `utils/api/workflow.ts:346` | POST | `/api/workflows/{id}/execute` | `api/workflow_api.py` | `execute_workflow()` | ExecuteReq | ExecuteResp |
| `utils/api/workflow.ts:380` | GET | `/api/workflows/{id}/status` | `api/workflow_api.py` | `get_execution_status()` | — | ExecutionStatus |
| `utils/api/workflow.ts:457` | POST | `/api/workflows/{id}/pause` | `api/workflow_api.py` | `pause_execution()` | — | ActionResp |
| `utils/api/workflow.ts:491` | POST | `/api/workflows/{id}/resume` | `api/workflow_api.py` | `resume_execution()` | — | ActionResp |
| `utils/api/workflow.ts:528` | POST | `/api/workflows/{id}/cancel` | `api/workflow_api.py` | `cancel_execution()` | — | ActionResp |
| `utils/api/workflow.ts:562` | POST | `/api/workflows/{id}/retry` | `api/workflow_api.py` | `retry_execution()` | — | ActionResp |
| `pages/Week5PanelsPage.tsx:169` | GET | `/api/tasks/{taskId}/anchors` | `api/task_api.py` | 动态调用，需运行时确认 | — | AnchorList |
| `pages/Week5PanelsPage.tsx:170` | POST | `/api/tasks/{taskId}/anchors` | `api/task_api.py` | 动态调用，需运行时确认 | AnchorCreate | — |
| `pages/Week5PanelsPage.tsx:171` | POST | `/api/tasks/{taskId}/continue` | `api/task_api.py` | 动态调用，需运行时确认 | — | — |
| `pages/Week5PanelsPage.tsx:172` | POST | `/api/tasks/{taskId}/rollback` | `api/task_api.py` | 动态调用，需运行时确认 | — | — |
| `pages/SettingsPage.tsx:235` | GET | `/api/tools/` | `api/tools_api.py` | `list_tools()` | — | ToolList |
| `pages/SettingsPage.tsx:691` | POST | `/api/voice/test` | `api/voice_api.py` | `test_ai_config()` (推测) | 动态调用，需运行时确认 | — |
| `utils/api/tonePreference.ts:91` | GET | `/api/users/{userId}/tone-preference` | `api/cloud_api.py` (推测) | 动态调用，需运行时确认 | — | TonePref |
| `utils/api/tonePreference.ts:117` | PUT | `/api/users/{userId}/tone-preference` | `api/cloud_api.py` (推测) | 动态调用，需运行时确认 | TonePref | — |
| `utils/api/tonePreference.ts:135` | POST | `/api/users/{userId}/tone-preference/reset` | `api/cloud_api.py` (推测) | 动态调用，需运行时确认 | — | — |
| `utils/api/tonePreference.ts:151` | GET | `/api/tone-presets` | `api/cloud_api.py` (推测) | 动态调用，需运行时确认 | — | PresetList |
| `utils/api/tonePreference.ts:165` | GET | `/api/tone-presets/{id}` | `api/cloud_api.py` (推测) | 动态调用，需运行时确认 | — | Preset |
| `utils/api/tonePreference.ts:179` | POST | `/api/tone-presets` | `api/cloud_api.py` (推测) | 动态调用，需运行时确认 | PresetCreate | — |
| `utils/api/tonePreference.ts:200` | PUT | `/api/tone-presets/{id}` | `api/cloud_api.py` (推测) | 动态调用，需运行时确认 | PresetUpdate | — |
| `utils/api/tonePreference.ts:218` | DELETE | `/api/tone-presets/{id}` | `api/cloud_api.py` (推测) | 动态调用，需运行时确认 | — | — |
| `utils/api/tonePreference.ts:235` | POST | `/api/tone-preview` | `api/cloud_api.py` (推测) | 动态调用，需运行时确认 | PreviewReq | PreviewResp |
| `utils/api/tonePreference.ts:253` | POST | `/api/tone-analyze` | `api/cloud_api.py` (推测) | 动态调用，需运行时确认 | AnalyzeReq | AnalyzeResp |
| `utils/api/tonePreference.ts:274` | POST | `/api/users/{userId}/tone-preference/apply-preset` | `api/cloud_api.py` (推测) | 动态调用，需运行时确认 | PresetId | — |
| `utils/api/tonePreference.ts:306` | GET | `/api/users/{userId}/tone-history` | `api/cloud_api.py` (推测) | 动态调用，需运行时确认 | Query: limit | History |

### 3.3 WebSocket 端点

| 前端 Hook | WS 路径 | 后端Handler | 说明 |
|---|---|---|---|
| `hooks/useWebSocket.tsx` | `/ws` (推测) | `api/cloud_api.py` | 主对话WebSocket |
| `hooks/useAlignment.ts:108` | `/ws` (推测) | `api/cloud_api.py` | 对齐状态 |
| `hooks/useModeSwitch.tsx:61` | `/ws` (推测) | `api/cloud_api.py` | 模式切换 |
| `hooks/usePerception.ts:58` | `/ws` (推测) | `api/cloud_api.py` | 感知数据 |
| `hooks/useVoiceState.tsx:71` | `/ws` (推测) | `api/cloud_api.py` | 语音状态 |
| `components/ProposalBubble.tsx:13` | `/ws` (推测) | `api/cloud_api.py` | 提案气泡 |
| `api/memory_sync_websocket.py:81` | `/ws/memory-sync` | `api/memory_sync_websocket.py` | 记忆同步 |
| `api/memory_visualization_api.py:642` | `/ws/realtime/{user_id}` | `api/memory_visualization_api.py` | 记忆可视化实时推送 |
| `api/silicon_life_api.py:667` | `/ws/realtime/{user_id}` | `api/silicon_life_api.py` | 硅基生命实时状态 |
| `api/cost_api.py:529` | `/ws/alerts` | `api/cost_api.py` | 费用预警 |
| `api/trading_ws.py` | `/ws/trading/{symbol}` (推测) | `api/trading_ws.py` | 交易数据WebSocket |

### 3.4 未匹配/动态调用标记

以下前端调用路径在静态扫描中**未能直接定位到后端 router 定义**，可能通过 `cloud_api.py` 中的动态注册或内联 handler 处理：

- `/api/mode` —— `stores/modeStore.ts` 调用，后端可能在 `cloud_api.py` 中以 `@app.post("/api/mode")` 或动态注册方式定义
- `/api/tasks/{taskId}/pause`, `/api/tasks/{taskId}/resume`, `/api/tasks/{taskId}/cancel` —— 可能由 `cloud_api.py` 中的 TaskRouter 动态处理
- `/api/reflection/*` —— 静态扫描未在独立 router 文件中找到，可能内联于 `cloud_api.py`
- `/api/tone-presets`, `/api/tone-preview`, `/api/tone-analyze` —— 同上
- `/api/users/{userId}/tone-preference` —— 同上
- `/api/consciousness/*` —— `api/consciousness_api.py` 存在，但前缀可能为 `/api` 或 `/api/consciousness`
- `/api/prompt/layer/*` —— `api/prompt_layer_api.py` 存在，需运行时确认前缀是否为 `/api/prompt/layer` 或 `/api`
- `/api/v1/voice/status` —— `api/voice_api.py` 中 router prefix 可能为 `/voice` 而非 `/v1/voice`，存在版本前缀差异

---

## 四、审计结论与风险标注

1. **PromptFinalizer 参数依赖链极长**: 20+ 参数来自 5+ 个不同上游模块（AgentLoop、ContextAssembler、PerceptionManager、PromptAssemblyBridge、SmartPromptEngine），任何一个上游失败都会通过 `finalize()` 的降级逻辑（fallback_concat）兜底，但降级后可能丢失 TokenBudget 控制。

2. **smart_context 与 perception_context 来源分散**:
   - `smart_context` 来自 `SmartPromptEngine`（`core/prompt/smart_prompt_engine.py`），涉及用户上下文、系统上下文、记忆检索三层调用。
   - `perception_context` 来自 `PerceptionManager`（`core/vision/perception_manager.py`），涉及桌面感知数据查询和格式化。

3. **TradingSubAgent 市场数据链路清晰但有单点**: 全部依赖 OKX API（`market_data.py`），若 OKX 限流或不可用，则 `_collect_market_data()` 返回空/默认值，最终 `_build_decision_prompt()` 中 market_data 为 `{}` 或残缺 JSON。

4. **MemoryManager.retrieve_memory() query 语义不统一**: 交易场景下 query 是 `market_data` JSON，记忆压缩场景下 query 是 `"*"`，并非自然语言查询。向量检索层（`vector_store.search("knowledge", query, ...)`）在这些场景下可能效果不佳或直接被跳过（`query=None` 时不走向量层）。

5. **数据库层无 ORM，全靠原始 SQL**: 表结构散落在 `connection_pool.py`、`phase_anchor.py`、`memory_associations.py`、`cost_manager.py` 等多个文件中，存在**Schema 漂移风险**。例如 `memories` 表有 3 个同构定义，若某处 ALTER 未同步，可能导致初始化不一致。

6. **API 契约存在版本前缀不一致**: 前端部分调用使用 `/api/v1/voice/status`，但后端 `voice_api.py` 的 router prefix 为 `/voice`（通过 `cloud_api.py` 挂载为 `/api/voice`），`/v1/` 层级**静态未找到对应后端定义**，运行时可能由中间件重写或返回 404。

7. **大量动态调用**: `cloud_api.py` 超过 3000 行，包含大量内联 handler 和动态 router 注册，静态分析无法完全覆盖。建议通过运行时 OpenAPI 文档 (`/docs`) 做完整契约校验。

---

*报告结束。*


---

## 6. 已知运行时问题

### 6.1 已修复（今日）

| # | 问题 | 位置 | 修复 |
|---|------|------|------|
| 1 | `ModuleNotFoundError` | `core/safety/safety_framework.py:88` | `from core.three_views_generator` -> `from core.reflector.three_views_generator` |
| 2 | 编码风险 | `core/providers/ollama_provider.py:345-353` | 移除 `latin-1` -> `utf-8` hack |
| 3 | 死代码/错误 await | `core/memory/async_memory.py` | 移除 `MemoryQueryCache` 错误用法 |
| 4 | 缺失 await | `core/memory/memory_manager.py:1227` | 添加 `await` |

### 6.2 待确认/待修复

| # | 问题 | 严重程度 | 说明 |
|---|------|----------|------|
| 1 | **API 版本前缀不匹配** | 中 | 前端 `/api/v1/voice/status` vs 后端 `/voice`（缺 `/v1`），运行时可能 404 |
| 2 | **Schema 漂移风险** | 中 | `memories` 表 3 处同构定义，ALTER 未同步会导致初始化不一致 |
| 3 | **cloud_api.py 动态路由** | 中 | 3000+ 行，大量内联 handler，静态分析无法覆盖，建议运行时 OpenAPI 校验 |
| 4 | **MemoryManager query 语义不统一** | 低 | 交易场景 query 为 JSON，压缩场景为 `"*"`，向量层效果有限 |
| 5 | **OKX API 单点依赖** | 中 | TradingSubAgent 全部依赖 OKX，限流时返回空 market_data |
| 6 | **数据库初始化失败** | 中 | PostgreSQL/Redis 在测试环境连接失败，当前 fallback 到内存模式 |
| 7 | **three_views 已关闭** | 低 | `roles.yaml` + `prompt_assembly_bridge.py` + `prompt_finalizer.py` 三重关闭 |

### 6.3 Hook 链执行顺序确认

`before_prompt` 链按 `priority` 降序执行：

```
priority 100: hook_intervention_check     -> 实时干预检查
priority  95: hook_perception_inject      -> 感知注入
priority  88: hook_btc_context_inject     -> 交易状态注入
priority  85: hook_context_assemble       -> Prompt 组装
              |-> assemble_context_phase()     (memory_context)
              |-> prepare_prompt_fragments_async() (fragments)
              |-> prompt_finalizer.finalize_async() (full_system_prompt)
--------------------------------------------------- AI 调用边界
```

---

## 附录：原始报告文件

| 文件 | 大小 | 内容 |
|------|------|------|
| `tmp_test/agent_a_call_chains.md` | ~20KB | 完整跨文件调用栈（入口 1+2，L1-L8） |
| `tmp_test/agent_b_call_chains.md` | ~4KB | 交易周期 + 记忆检索 + 提示词组装（L9-L18） |
| `tmp_test/agent_c_runtime_registrations.md` | ~50KB | 完整事件/工具/API/Hook 注册表 |
| `tmp_test/agent_d_data_flow_db_frontend.md` | ~36KB | 完整参数溯源 + DB Schema + API 契约 |

> 如需查看原始完整数据（含全部 414 个路由、101 个工具、27 个事件订阅等），请查阅上述原始报告文件。

---

*报告生成完毕。四个子代理（A/B/C/D）产出已全部整合。*
