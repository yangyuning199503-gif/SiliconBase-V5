# SiliconBase V5 思维线程下一阶段实施文档

> **文档性质**: 实施级技术方案  
> **覆盖方向**:  
> 1. ConsciousnessRouter —— 思维线程显式调度 LLM  
> 2. 任务中断与恢复 —— 长任务执行中用户插话的暂停-回应-恢复闭环  
> **版本**: 2026-06-14  
> **基于现状**: 项目已修复 P0 事件驱动、P1 反馈闭环、P1 视觉滥用、P2 表达学习模型接入

---

## 一、背景与前因后果

### 1.1 我们已经走到哪里

经过上一阶段修复，系统已经具备以下能力：

| 能力 | 状态 | 关键文件 |
|---|---|---|
| 事件驱动唤醒 | ✅ 已完成 | `core/consciousness/Consciousness.py` |
| 内心独白默认开启 | ✅ 已完成 | `core/consciousness/Consciousness.py` |
| 简单聊天快速通道 | ✅ 已完成 | `core/dialog/dialogue_manager.py` |
| 视觉模型不滥用 | ✅ 已完成 | `core/vision/perception_manager.py` |
| 弱连接反馈闭环 | ✅ 已完成 | `core/weak_connection/weak_connection.py` |
| 驱动力多源反馈 | ✅ 已完成 | `core/consciousness/Consciousness.py` |
| 表达偏好在线学习 | ✅ 已完成 | `core/consciousness/expression_engine.py` |
| Ollama 模型保持 | ✅ 已完成 | `core/providers/ollama_provider.py` |

### 1.2 还缺什么：从"能响应"到"会调度"

当前系统的问题是：**LLM 很强大，但入口路由还是硬的**。

- `classify_user_input()` 根据关键词决定走快速聊天还是任务模式
- `AgentLoop` 一旦启动，就不会因为用户的新输入而主动暂停
- 思维线程能产生独白、能产生弱连接气泡，但**不能影响 LLM 的调度策略**

这导致两个核心体验缺口：

1. **不会审时度势**：系统能量很低、很焦虑时，仍然会被迫进入完整任务流；用户连续打断时，仍然在跑旧任务。
2. **不会一来一回**：长任务一旦开始，用户只能等它结束或超时，中间没法插话闲聊或改变目标。

### 1.3 核心思路

> **思维线程不是替代 LLM，而是 LLM 的调度器。**

下一阶段要实现两个闭环：

```
用户输入 → ConsciousnessRouter → 决策（快速聊天 / 任务 / 中断 / 延迟）
                              ↓
                          进入对应 LLM 路径
                              ↓
                        执行中产生状态变化
                              ↓
                    思维线程更新动机/情绪/意图
                              ↓
                    影响下一次 ConsciousnessRouter 决策
```

```
长任务执行中 → 用户插话
                  ↓
        任务状态快照保存
                  ↓
        快速回应用户（闲聊/新意图）
                  ↓
        用户说"继续"或新任务结束
                  ↓
        从快照恢复上下文，继续执行
```

---

## 二、总体目标与验收标准

### 2.1 总体目标

1. **ConsciousnessRouter**: 让思维线程能根据内在状态、当前任务状态、用户历史反馈，动态决定用户输入该走哪条 LLM 路径。
2. **任务中断与恢复**: 让 AgentLoop 支持"暂停-插话-恢复"，长任务不再阻塞用户交互。

### 2.2 验收标准

#### ConsciousnessRouter

- [ ] 用户能量低/连续失败时，复杂任务请求被降级为"先聊天确认"或"拆分步骤"
- [ ] 用户连续打断同一任务 2 次后，系统自动暂停原任务并询问用户意图
- [ ] 思维线程的 `latest_monologue` 和 `IntrinsicMotivation` 参与路由决策
- [ ] 新增路由决策日志，可追溯每次输入为什么走某条路径

#### 任务中断与恢复

- [ ] 长任务执行中，用户发送闲聊消息，系统能在 3 秒内回应并保留原任务
- [ ] 用户说"继续"，系统能从断点恢复，不重复已执行步骤
- [ ] 用户发送新任务指令，系统能保存旧任务快照并切换到新任务
- [ ] 前端显示"当前有 N 个后台任务"，并允许查看/恢复/取消

---

## 三、方向 A：ConsciousnessRouter（思维线程调度 LLM）

### 3.1 现状与问题

#### 3.1.1 当前入口分流逻辑

当前用户输入的分流发生在两个地方：

1. **`core/dialog/dialogue_manager.py:1506-1540` 的 `handle_text_input()`**
   - 调用 `classify_user_input()` 分类：simple_chat / task_control / task_status_query / task
   - 简单聊天直接走 `_handle_quick_chat()`
   - 其他进入 `DualModeManager.handle_text()`

2. **`core/dialog/chat_mode_handler.py:1280-1337` 的 `DualModeManager.handle_text()`**
   - 只认 `"聊天:"` / `"对齐:"` 前缀
   - 否则进入 `TaskModeRunner.run()` → `AgentLoop`

#### 3.1.2 当前问题

- 分类是纯规则的，不考虑系统状态。
- 一旦进入 `AgentLoop`，`DialogueManager` 和 `Consciousness` 都失去对流程的控制。
- `IntrinsicMotivation` 的能量/胜任感/好奇心不参与入口决策。

### 3.2 设计思路

在 `DialogueManager.handle_text_input()` 和 `AgentLoop` 入口之间插入一个 `ConsciousnessRouter` 层。

```
用户输入
  ↓
DialogueManager.handle_text_input()
  ↓
classify_user_input() 初分
  ↓
ConsciousnessRouter.suggest_route()
  ├─ 快速聊天 (quick_chat)
  ├─ 直接任务 (direct_task)
  ├─ 中断当前任务 (interrupt_resume)
  ├─ 延迟处理 (defer)
  └─ 对齐确认 (alignment)
  ↓
执行对应路径
```

### 3.3 核心组件

#### 3.3.1 新增 `core/consciousness/consciousness_router.py`

核心类 `ConsciousnessRouter`，职责单一：**根据输入 + 系统状态，返回路由建议**。

```python
class RouteDecision:
    mode: Literal["quick_chat", "direct_task", "interrupt_resume", "defer", "alignment"]
    reason: str                       # 决策原因，用于日志和调试
    confidence: float                 # 决策置信度 0~1
    suggested_timeout: int            # 建议 LLM 超时
    suggested_scene: Optional[str]    # 建议 LLM 场景
    need_vision: bool                 # 是否建议本轮调用视觉
    context_injection: List[Dict]     # 需要注入 AgentLoop 的上下文
```

```python
class ConsciousnessRouter:
    def suggest_route(
        self,
        user_input: str,
        user_id: str = "default",
        session_id: str = "",
        current_task: Optional[Task] = None,
        chat_history: List[Dict] = None,
    ) -> RouteDecision:
        """
        综合考虑以下因素给出路由建议：
        1. 输入分类（classify_user_input）
        2. 内在动机状态（energy / mastery / autonomy / curiosity）
        3. 是否有活跃任务
        4. 最近独白 / 紧急洞察
        5. 用户最近 60 秒打断次数
        """
```

#### 3.3.2 修改 `core/dialog/dialogue_manager.py`

在 `handle_text_input()` 的 `classify_user_input()` 之后、`_handle_quick_chat()` / `_handle_text_task()` 之前，调用 `ConsciousnessRouter.suggest_route()`。

根据返回的 `mode` 分发：

| mode | 处理 |
|---|---|
| quick_chat | 调用 `_handle_quick_chat()` |
| direct_task | 进入 `DualModeManager.handle_text()` |
| interrupt_resume | 先暂停当前任务，再快速回应，然后恢复 |
| defer | 把任务入队延迟执行，先给安抚/说明回复 |
| alignment | 进入对齐模式，先确认用户真实意图 |

### 3.4 数据流

```
用户输入 "帮我写个复杂的自动化脚本"
  ↓
classify_user_input → category="task"
  ↓
ConsciousnessRouter.suggest_route()
  ├─ 读取 IntrinsicMotivation: energy=0.3（低能量）
  ├─ 读取当前是否有任务：有，且已运行 2 分钟
  ├─ 读取最近独白："我有点累，想先歇会儿"
  └─ 决策：mode="alignment", reason="能量低+有进行中任务，先确认是否替换"
  ↓
进入对齐模式："我现在有点累，而且正在做 xxx。你是要我先停下当前任务做脚本吗？"
```

### 3.5 涉及文件与函数

| 文件 | 函数/类 | 改动方式 |
|---|---|---|
| `core/consciousness/consciousness_router.py` | 新增 `ConsciousnessRouter`, `RouteDecision` | 新增文件 |
| `core/consciousness/Consciousness.py` | 新增 `get_router()` 工厂方法；`_update_internal_state()` 把生命状态同步到 router | 修改 |
| `core/consciousness/__init__.py` | 导出 `ConsciousnessRouter`, `RouteDecision` | 修改 |
| `core/dialog/dialogue_manager.py` | `handle_text_input()` 集成 router | 修改 |
| `core/dialog/chat_mode_handler.py` | `DualModeManager.handle_text()` 接收 router 建议 | 可选修改 |
| `core/agent/agent_loop.py` | `run_agent_loop()` 接收 `route_decision` 参数，调整初始行为 | 可选修改 |

### 3.6 新增字段/接口

#### 3.6.1 新增数据结构

```python
# core/consciousness/consciousness_router.py

from dataclasses import dataclass, field
from typing import Literal, List, Dict, Optional

@dataclass
class RouteDecision:
    mode: Literal["quick_chat", "direct_task", "interrupt_resume", "defer", "alignment"]
    reason: str = ""
    confidence: float = 0.5
    suggested_timeout: int = 30
    suggested_scene: Optional[str] = None
    need_vision: bool = False
    context_injection: List[Dict] = field(default_factory=list)
    pause_current_task: bool = False
    resume_after: Optional[int] = None   # 秒，defer 模式下多久后恢复
```

#### 3.6.2 ConsciousnessService 新增方法

```python
# core/consciousness/Consciousness.py

class ConsciousnessService:
    def __init__(self, ...):
        ...
        self._router = ConsciousnessRouter(
            user_id=self.user_id,
            intrinsic_motivation=self.intrinsic_motivation,
            consciousness=self,  # 用于读取最近独白、紧急洞察
        )

    def get_router(self) -> "ConsciousnessRouter":
        return self._router
```

### 3.7 代码风格

- 保持与项目一致：使用 dataclass、类型注解、`Optional`、`Literal`。
- 错误处理：所有外部调用包 `try/except`，失败时降级到 `direct_task`。
- 日志：每个路由决策必须记录 `mode`, `reason`, `confidence`。
- 配置化：关键阈值（能量阈值、打断次数阈值）从 `config` 读取。

### 3.8 第三方库依赖

**不引入新库**。只用已有：

- `core.config.config`
- `core.strategy.intrinsic_motivation`
- `core.consciousness.Consciousness`
- `core.constants.chat_keywords.classify_user_input`
- 标准库 `dataclasses`, `typing`

---

## 四、方向 B：任务中断与恢复

### 4.1 现状与问题

#### 4.1.1 已有基础设施

项目已经有状态快照机制：

- `core/session/state_snapshot.py` —— `TaskStateSnapshot`, `StateSnapshotManager`
- `core/agent/loop_types.py` —— `LoopState`
- `core/agent/loop_initialization.py` —— 初始化 `LoopState`, `WorkingMemory`
- `core/task/task_queue.py` —— `Task`, `TaskQueue`

#### 4.1.2 当前问题

- `state_snapshot.py` 的恢复逻辑主要服务于"程序崩溃/重启后恢复"，不是"用户插话后恢复"。
- `AgentLoop` 没有"暂停"语义，只有"终止"和"完成"。
- `TaskQueue` 不支持任务的"挂起"状态，只有 pending / running / done / failed。
- 用户插话时，旧任务继续在后台跑，导致并发冲突或资源争用。

### 4.2 设计思路

引入"任务状态机"扩展：

```
Task 状态:
  pending → running → paused → running → completed
                     ↓
                  cancelled
```

在 `AgentLoop` 主循环中增加"可暂停检查点"：

1. 每轮 LLM 调用前检查 `pause_requested` 标志
2. 如果被请求暂停：
   - 保存当前 `LoopState`
   - 保存 `WorkingMemory`
   - 保存 `execution_history`
   - 把任务状态改为 `paused`
   - 返回暂停信息给 `DialogueManager`
3. `DialogueManager` 处理完用户插话后，可以：
   - 恢复旧任务（用户说"继续"）
   - 取消旧任务（用户给出新任务）

### 4.3 核心组件

#### 4.3.1 新增 `core/task/task_pause_manager.py`

```python
class TaskPauseManager:
    """管理被暂停的任务快照。"""

    async def pause_task(self, task_id: str, loop_state, working_memory, execution_history) -> TaskSnapshot:
        """暂停任务并保存快照。"""

    async def resume_task(self, task_id: str) -> Optional[TaskSnapshot]:
        """恢复任务，返回快照。"""

    async def cancel_paused_task(self, task_id: str) -> bool:
        """取消已暂停任务。"""

    def list_paused_tasks(self, user_id: str) -> List[TaskSnapshot]:
        """列出某用户所有暂停任务。"""
```

#### 4.3.2 修改 `core/task/task_queue.py`

增加任务状态 `paused`：

```python
class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
```

#### 4.3.3 修改 `core/agent/agent_loop.py`

在 `while loop_state.round_count < MAX_SAFETY_ROUNDS:` 循环开头增加：

```python
# 检查是否被请求暂停
if self._pause_requested(task_id):
    logger.info(f"[AgentLoop] 任务 {task_id} 被请求暂停")
    await task_pause_manager.pause_task(
        task_id=task_id,
        loop_state=loop_state,
        working_memory=working_memory,
        execution_history=execution_history,
    )
    return "PAUSED", working_memory
```

#### 4.3.4 修改 `core/dialog/dialogue_manager.py`

新增 `_handle_interruption()`：

```python
async def _handle_interruption(
    self,
    user_id: str,
    text: str,
    session_id: str,
    voice_instance=None
) -> str:
    """
    处理用户插话：
    1. 暂停当前活跃任务
    2. 根据输入决定是闲聊回应还是切换到新任务
    3. 返回回应文本
    """
```

### 4.4 数据流

```
用户发送"帮我查个资料" → AgentLoop 开始长任务
            ↓
用户又发送"先别管这个，几点了"
            ↓
DialogueManager._handle_interruption()
  ├─ 请求当前活跃任务暂停
  ├─ AgentLoop 保存快照，返回 PAUSED
  ├─ 快速回答"2026-06-14 20:00"
  └─ 询问"要继续之前的查资料任务吗？"
            ↓
用户说"继续"
            ↓
TaskPauseManager.resume_task(task_id)
  ├─ 从快照恢复 LoopState / WorkingMemory / execution_history
  ├─ 创建新 Task，标记为 resume_from_checkpoint
  └─ 重新进入 AgentLoop，从断点继续
```

### 4.5 涉及文件与函数

| 文件 | 函数/类 | 改动方式 |
|---|---|---|
| `core/task/task_pause_manager.py` | 新增 `TaskPauseManager`, `TaskSnapshot` | 新增文件 |
| `core/task/task_queue.py` | `TaskStatus` 增加 `PAUSED`；`pause_async()`, `resume_async()` | 修改 |
| `core/agent/agent_loop.py` | `run_agent_loop()` / `_run_agent_loop_async_impl()` 增加暂停检查点 | 修改 |
| `core/agent/loop_types.py` | `LoopState` 增加 `paused`, `pause_count`, `original_task_id` | 修改 |
| `core/session/state_snapshot.py` | 复用 `TaskStateSnapshot`；新增 `save_user_pause_snapshot()` | 修改 |
| `core/dialog/dialogue_manager.py` | 新增 `_handle_interruption()`；`handle_text_input()` 检测插话 | 修改 |
| `core/dialog/chat_mode_handler.py` | 接收暂停状态，恢复任务时调用 | 可选修改 |

### 4.6 新增字段/接口

#### 4.6.1 新增数据结构

```python
# core/task/task_pause_manager.py

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from datetime import datetime

@dataclass
class TaskSnapshot:
    task_id: str
    user_id: str
    session_id: str
    instruction: str
    loop_state_dict: Dict[str, Any]
    working_memory_state: Dict[str, Any]
    execution_history: List[Dict]
    paused_at: datetime = field(default_factory=datetime.now)
    pause_count: int = 0
```

#### 4.6.2 Task 状态扩展

```python
# core/task/task_queue.py

class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
```

#### 4.6.3 LoopState 扩展

```python
# core/agent/loop_types.py

@dataclass
class LoopState:
    ...
    paused: bool = False
    pause_count: int = 0
    original_task_id: Optional[str] = None
    resumed_from_checkpoint: bool = False
```

### 4.7 代码风格

- 快照持久化优先使用 PostgreSQL（项目已有 `MemoryManager` / `ExecutionMemory`），内存只保留最近 5 个。
- 所有暂停/恢复操作必须记录日志：`task_id`, `pause_count`, `instruction_truncated`。
- 快照中包含 `pause_count`，用于限制无限暂停循环（超过 3 次自动转为失败）。
- 与 `state_snapshot.py` 保持兼容，不破坏现有断点续传逻辑。

### 4.8 第三方库依赖

**不引入新库**。复用已有：

- `core.session.state_snapshot`
- `core.memory.execution_memory`（用于持久化快照）
- `core.task.task_queue`
- `core.agent.loop_types`
- 标准库 `dataclasses`, `datetime`

---

## 五、实施顺序与风险

### 5.1 推荐实施顺序

```
第 1 周：任务中断与恢复（方向 B）
  - 因为方向 B 直接解决"长任务卡死、无法插话"的痛点
  - 依赖文件相对集中：task_queue / agent_loop / state_snapshot / dialogue_manager

第 2-3 周：ConsciousnessRouter（方向 A）
  - 在方向 B 完成后，router 可以利用"任务可暂停"能力做更复杂的调度
  - 依赖文件：consciousness / dialogue_manager / chat_mode_handler

第 4 周：联调与验收
  - 长任务中用户插话 → 快速聊天 → 继续任务
  - 系统焦虑/低能量时主动降级任务为对齐模式
```

### 5.2 主要风险

| 风险 | 影响 | 缓解措施 |
|---|---|---|
| `AgentLoop` 暂停点引入死锁 | 任务卡死 | 只在 LLM 调用前检查，避免在工具执行中暂停 |
| 快照恢复后上下文丢失 | 任务重复执行 | 保存完整 `LoopState` + `execution_history` + `WorkingMemory` |
| Router 误判导致用户输入被错误降级 | 体验下降 | 保留 `classify_user_input` 硬规则作为上限保护 |
| Ollama 显存不足 | 模型被挤出 | 已设置 keep_alive，如仍不足可降级视觉模型到 qwen3-vl:2b |

### 5.3 关键配置项建议

建议新增到 `core/config/global.yaml`：

```yaml
consciousness:
  router:
    enabled: true
    low_energy_threshold: 0.3
    max_interruptions_before_pause: 2
    defer_timeout_seconds: 60

ollama:
  keep_alive_seconds: 1800

task:
  pause:
    enabled: true
    max_pause_count: 3
    snapshot_ttl_hours: 24
```

---

## 六、附录：关键代码片段

### 6.1 当前 `DialogueManager.handle_text_input` 分流区域

```python
# core/dialog/dialogue_manager.py:1506-1540

try:
    from core.constants import classify_user_input
    has_active = self.has_active_background_task(user_id)
    classification = classify_user_input(text, has_active_task=has_active)
    category = classification["category"]
    
    if category == "simple_chat":
        # ... 快速聊天
    elif category == "task_control":
        # ... 任务控制
    elif category == "task_status_query":
        # ... 状态查询
    # ...
```

**插入点**：`classify_user_input()` 之后，`_handle_quick_chat()` / `_handle_text_task()` 之前。

### 6.2 当前 `AgentLoop` 主循环结构

```python
# core/agent/agent_loop.py:868+

while loop_state.round_count < MAX_SAFETY_ROUNDS:
    # 检查调度器取消信号和绝对超时
    if cancel_event and cancel_event.is_set():
        ...
    if timeout_deadline and time.time() > timeout_deadline:
        ...
    
    # 熔断检查
    ...
    
    # ← 此处是插入"暂停检查点"的最佳位置
```

### 6.3 当前 `state_snapshot.py` 已有接口

```python
# core/session/state_snapshot.py

class TaskStateSnapshot:
    task_id: str
    working_memory_state: Dict[str, Any]
    loop_state: Dict[str, Any]
    chat_history: List[Dict]
    timestamp: float
```

可直接复用，只需增加 `pause_count` 和 `user_id` 字段。

---

## 七、结论

下一阶段的核心是**把思维线程从"旁观者"变成"调度者"**。

- **ConsciousnessRouter** 解决"什么时候该用什么模型、走什么路径"的问题。
- **任务中断与恢复** 解决"长任务执行中如何保持对话连续性"的问题。

两个方向都不需要引入新模型或新第三方库，完全基于现有架构扩展。先实现任务中断恢复，再叠加 ConsciousnessRouter，是最稳妥的路径。
