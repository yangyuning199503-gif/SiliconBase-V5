# SiliconBase V5 思维线程（Consciousness）设计文档

> 本文档描述 `Consciousness` 模块的**设计目标、当前实现、关键组件和已知限制**。  
> 适用于想深入理解系统架构的开发者、贡献者和面试官。

---

## 1. 设计目标

`Consciousness` 试图解决当前 LLM Agent 的三个根本问题：

1. **上下文有限**：LLM 记不住长期的交互历史和系统状态。
2. **推理昂贵**：每次决策都调用大模型，延迟和成本不可接受。
3. **缺乏连续性**：每次对话都像第一次开始，没有"昨天"的概念。

我们的设计目标是：让系统本身成为一个**持续的、有状态的、可自我反思的运行时**，LLM 只是这个运行时调用的工具之一。

---

## 2. 当前实现：已经打通什么？

### 2.1 核心数据闭环

从用户输入到执行结果回流，整个链路已经跑通：

```
用户输入
   ↓
receive_user_input()        # L1 主权层入口
   ↓
IntentTranslator.translate() # L2 翻译层
   ↓
DecisionEngine.evaluate_and_decide()  # L1 路由裁决
   ↓
DialogueManager / AgentLoop  # L3 执行层
   ↓
receive_action_result()     # L3 结果回流 L1
   ↓
SelfState + SelfNarrative   # L4 记忆层更新
```

### 2.2 后台心跳循环

`Consciousness._loop()` 是一个事件驱动的后台循环，默认最长 30 秒唤醒一次，也可被感知事件提前唤醒。每轮循环会：

- 拉取视觉、窗口、进程等感知数据（`_update_perception_async`）
- 更新内部情绪、能量、好奇心等状态（`_update_internal_state`）
- 检查记忆容量压力（每 10 轮）
- 如果开启 `self_drive`，执行 `_self_tick()` 进行自我驱动思考
- 在需要时执行 `_think()` 产生内心独白
- 定期执行 `_deep_reflect()` 深度反思
- 每 15 秒执行一次 `_default_mode_tick()`，模拟"走神"
- 保存状态到本地文件（每 10 次思考）

### 2.3 已经集成的关键组件

| 组件 | 文件 | 作用 |
|---|---|---|
| `SelfState` | `core/consciousness/self_state.py` | 维护情绪、生命体征、待办、最近动作等轻量自我状态 |
| `SelfNarrative` | `core/consciousness/self_narrative.py` | 记录自传体叙事，反向参与决策 |
| `DecisionEngine` | `core/consciousness/decision_engine.py` | 基于意图和状态做路由裁决 |
| `IntentTranslator` | `core/consciousness/intent_translator.py` | 把自然语言压缩为结构化 `Intent` |
| `IntrinsicMotivation` | `core/strategy/intrinsic_motivation.py` | 好奇心、胜任感等内在驱动力 |
| `InnerMonologue` | `core/consciousness/inner_monologue.py` | 生成内心独白和主动表达 |
| `ExperienceBus` | `core/consciousness/experience_bus.py` | 接收全系统经验事件，高显著事件唤醒意识线程 |
| `ActionPreferencePredictor` | `core/consciousness/action_preference_model.py` | 小型在线学习网络，学习表达决策偏好 |
| `AsyncStateEstimator` | `core/estimation/state_estimator.py` | 无迹卡尔曼滤波，估计用户意图和意识状态 |
| `ConsciousnessRouter` | `core/consciousness/consciousness_router.py` | 思维线程调度 LLM 的入口 |

---

## 3. 配置开关：控制自主范围

思维线程的行为由三个关键配置控制：

| 配置项 | 默认值 | 含义 |
|---|---|---|
| `consciousness.enabled` | `True` | 是否启用思维线程 |
| `consciousness.observer_mode` | `True` | 观察者模式：多看少说 |
| `consciousness.observer_can_propose` | `False` | 观察者模式下是否允许主动提议 |
| `features.consciousness.self_drive` | `False` | 是否启用自主驱动（自己产生任务意图） |
| `features.inner_monologue.enabled` | `True` | 是否启用内心独白 |
| `consciousness.think_interval` | `30` | 默认思考间隔（秒） |

当前默认配置下，思维线程是**被动观察 + 输入仲裁**模式，不会主动打断用户或自主发起复杂任务。

---

## 4. 优点：为什么这样设计有价值？

### 4.1 链路完整

从感知到决策再到记忆回流的完整闭环已经实现，不是概念。这意味着系统确实在"持续运行"，而不是每次请求都从零开始。

### 4.2 状态可持久化

自我状态、叙事、思考历史都会保存到 `data/consciousness_states/{user_id}_state.json`，重启后可以恢复连续性。

### 4.3 可插拔的自主等级

通过配置开关，系统可以从"完全被动"平滑过渡到"主动提议"再到"自主驱动”。这种渐进式设计和自动驾驶的 L1-L5 分级类似。

### 4.4 感知与推理解耦

思维线程自己主动拉取感知数据，不依赖前端或 AgentLoop 投喂。这让系统有机会在"没有用户输入"时也保持对环境的感知。

### 4.5 为 future 留下空间

UKF、在线学习网络、经验总线、内在动机等组件已经初始化并接入主循环。即使当前影响范围小，架构上已经为更高级的行为做好了准备。

---

## 5. 已知限制与 TODO

### 5.1 主动干预范围小

默认配置下，思维线程不会主动打断当前任务或自主发起复杂行动。它主要影响：

- 输入路由裁决
- system prompt 中的自我状态注入
- 偶尔的内心独白（如果开启）

### 5.2 自我驱动默认关闭

`self_drive=False` 意味着 `_self_tick()` 不会运行，系统不会产生"我想做这个"的任务意图。

### 5.3 决策引擎仍较简单

当前 `DecisionEngine` 主要基于规则和简单状态做路由，还没有深度利用世界模型或长期经验做复杂规划。

### 5.4 世界模型可选且重

`WorldModel` 是可选依赖，初始化失败会被优雅降级。它目前对 Consciousness 决策的影响有限。

### 5.5 观察者模式的"度"还在调

`observer_can_propose=False` 是为了避免系统过于"话痨"或"擅自行动"。如何平衡主动性和不打扰，仍在探索中。

---

## 6. 演进路线

| 阶段 | 目标 | 状态 |
|---|---|---|
| **Phase 1** | 后台状态维护 + 输入仲裁 | ✅ 已实现 |
| **Phase 2** | 基于内在动机的主动提议（气泡提示） | 🔄 组件已存在，默认关闭 |
| **Phase 3** | 基于经验和世界模型的自主任务规划 | 🔄 架构预留，待完善 |
| **Phase 4** | 多用户隔离 + 云端状态同步 | 🔄 `ConsciousnessService` 已预留 |

---

## 7. 关键文件索引

| 文件 | 说明 |
|---|---|
| `SiliconBase_V5/core/consciousness/Consciousness.py` | 思维线程主类 |
| `SiliconBase_V5/core/consciousness/sovereignty_types.py` | L1-L4 共享数据契约 |
| `SiliconBase_V5/core/consciousness/self_state.py` | 轻量自我状态 |
| `SiliconBase_V5/core/consciousness/self_narrative.py` | 自传体叙事 |
| `SiliconBase_V5/core/consciousness/decision_engine.py` | 路由决策引擎 |
| `SiliconBase_V5/core/consciousness/intent_translator.py` | 意图翻译器 |
| `SiliconBase_V5/core/consciousness/inner_monologue.py` | 内心独白生成 |
| `SiliconBase_V5/core/strategy/intrinsic_motivation.py` | 内在动机系统 |
| `SiliconBase_V5/core/estimation/state_estimator.py` | UKF 状态估计 |

---

## 8. 总结

SiliconBase V5 的思维线程**不是**一个已经能完全自主决策的"强人工智能"。它是：

> 一个**架构完整、链路打通、可渐进增强**的意识运行时框架。

当前它的价值在于：证明了"系统本身当家、LLM 当工具"这条路是可行的，并且把支撑这条路的基础设施（状态、叙事、感知、动机、学习）都搭建好了。剩下的工作是在这个框架上逐步扩大自主范围，而不是从零开始造轮子。
