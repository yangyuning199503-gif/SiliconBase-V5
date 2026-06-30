# SiliconBase V5 全面改造计划 V2
> 基于 2026-06-07 深度排查结果重新对齐
> 原则：删除优先、端对端、不重复造轮子、异步优先

---

## 一、排查结论（与之前报告的偏差修正）

### 1.1 前端：已完成项的验证
| 改造项 | 报告状态 | 实际状态 | 偏差 |
|---|---|---|---|
| MUI 迁移 | ✅ | ✅ 确实已移除 | 无偏差 |
| cytoscape 删除 | ✅ | ✅ 确实已移除 | 无偏差 |
| react-router-dom | ✅ | ✅ 已接入 BrowserRouter | 无偏差 |
| fetchAPI 统一 | ✅ | ⚠️ **做了一半** | `modeStore.ts` 仍用裸 `fetch`；`apiClient.ts` 被 9 个新页面引用 |
| 接口路径修复 | ✅ | ✅ globalView/procedureLearning 已改 | 无偏差 |
| 新增 6 页面 | ✅ | ✅ 已创建 | 无偏差 |
| Build 通过 | ✅ | ✅ 无 TS 错误 | 无偏差 |
| 路由守卫 | ✅ | ⚠️ **有漏洞** | `/login` PublicGuard 只检查 token 存在性，不验证有效性 |

### 1.2 前端：隐藏问题（之前未报告）
1. **Hash 路由残留 5 处**：`App.tsx`、`AppHome.tsx`、`SettingsPage.tsx`、`ToolMarketPage.tsx`、`TopBar.tsx`
2. **App.tsx 不是"保留完整逻辑"，而是完全悬空的 1370 行死代码**：它自建了一套 Provider 树 + AuthGuard + hash 路由，与 `main.tsx`/`router/index.tsx` 零交集
3. **React Query 已安装但零使用**：`@tanstack/react-query@5.74.0` 在 `node_modules` 里，没有任何文件 `import` 它
4. **Provider 嵌套不一致**：`main.tsx` 有 `GlobalErrorHandler > WebSocketProvider > GamificationProvider > RouterProvider`，`RootLayout` 才有 `NotificationProvider`——登录页没有通知能力
5. **Ant Design 未动**：6 个文件仍在用 antd（LifeStatusPanel、PhaseAnchorPanel、ReflectionPanel、TaskControlPanel、TonePreferencePanel、Week5PanelsPage）

### 1.3 后端：已完成项的验证
| 改造项 | 报告状态 | 实际状态 | 偏差 |
|---|---|---|---|
| 路由前缀标准化 | ✅ | ⚠️ **只标准化了 router 级** | `cloud_api.py` 仍直接定义 54 个 `@app.*` 端点（B类硬编码），未收敛到 router |
| system_api.py | ✅ | ✅ 已创建，有 6 个端点 | 无偏差 |
| cost_api /health | ✅ | ✅ 确实已删除 | 无偏差 |
| memory_graph_api 改回 router | ✅ | ✅ 已改回，register_routes 壳还在 | 无偏差 |
| requirements 清理 | ✅ | 未验证 | — |
| 语法检查 | ✅ | 未验证 | — |

### 1.4 后端：隐藏问题（之前未报告）
1. **health 端点泛滥**：5 处（cloud_api 2处、system_api 1处、stats_api 1处、auto_trading_api 1处、sync_api 1处）
2. **status 端点泛滥**：10+ 处，每个子系统一个
3. **cloud_api.py 变量名覆盖**：`features_api.system_router` 和 `system_api.router` 在 `cloud_api.py` 中被先后赋值给同名局部变量 `system_router`，虽都能挂载但极其危险
4. **Fallback 端点埋雷**：`cloud_api.py` 直接定义 `GET /api/tasks`，与 `task_api.py` 的 router 冲突，依赖 FastAPI 注册顺序
5. **world_model_api.py 是内存 random mock**，但路由表里有 `/worldmodel` 页面
6. **39 个 *_api.py 文件**，不是之前说的 58 个，但加上 `cloud_api.py` 直接定义的 54 个端点，实际端点约 426 个

### 1.5 数据层：全新发现
1. **memories 表 DDL 三处不一致**：`layer` 字段有 `VARCHAR(20)` 和 `VARCHAR(50)` 两种定义
2. **cloud_tool_repo 用 SQLite**：`api/cloud_tool_repo.py` 实际使用 `aiosqlite` 操作 `data/cloud_tools.db`，与"强制 PostgreSQL"策略矛盾
3. **global.yaml 明文存测试凭证**：`sk-test-api-key-12345`、`mypassword123`
4. **无 SQLAlchemy ORM**：全部原始 SQL，schema 散落在 10+ 个文件
5. **tasks/executions 遗留表仍在 init_database.py 中被创建**

### 1.6 异步架构：全新发现
1. **memory_manager.py 有语法错误**：`asyncio.create_task(await self._check_and_compress(user_id))` — `await` 先于 `create_task`，实际传 `None`
2. **_trading_ws_server_task lifespan 关闭时未取消**
3. **BackgroundTaskRegistry 设计完善但采用率极低**：大量裸 `create_task`
4. **voice 模块 6+ daemon 线程无统一关闭接口**
5. **global_view ThreadPoolExecutor 关闭时未 shutdown**
6. **Unicode 编码崩溃**：`cloud_api.py:2618` 打印 `✅` 时 `gbk` 编码失败，已导致 crash_log3.txt 记录崩溃
7. **app.on_event("startup") 与 lifespan 双重启动 trading ws**

---

## 二、改造原则（重申 + 新增约束）

1. **删除优先于新增**：死代码、悬空文件、重复端点、mock 数据先删
2. **端对端一次对齐**：改前端路由必须同步改后端前缀；改前端页面必须同步改后端 schema
3. **不重复造轮子**：
   - UI 只留 Tailwind + lucide（Ant Design 必须迁，但可分阶段）
   - HTTP 客户端只留 `fetchAPI`（`apiClient.ts` 彻底废弃）
   - 路由只留 `react-router-dom`
   - 任务管理只留 `BackgroundTaskRegistry`
4. **异步优先**：新代码全 async；旧 `threading.Thread` 迁 `asyncio`；同步 IO 用 `asyncio.to_thread`
5. **不修改第三方库**：只能删除/替换/adapter
6. **功能不重复**：已有 `session_api.py` 就别在 `interrupt_api.py` 里再搞一套会话控制；已有 `system_api.py` 就别让每个子系统再搞 `/status`
7. **可验证**：每阶段结束必须能 `npm run build` + `python -m py_compile` + 冒烟测试

---

## 三、四阶段改造方案

### 阶段 0：首页恢复 + 止血（2～3 天）
> 目标：让产品从"不能用"变成"能用"

#### 0.1 首页聊天恢复（端对端：前端）
**问题**：AppHome.tsx 是 46 行占位页，用户登录后看不到聊天界面
**方案**：
- 旧 `App.tsx` 不是"整体迁移"的最佳来源——它包含了自建路由、Provider、AuthGuard 等大量已废弃的包装层
- 正确做法：从 `App.tsx` 的 `AppContent` 中**提取首页专用的状态与 UI**，剥离所有路由/认证/Provider 逻辑，注入新路由体系

**需要提取到 AppHome（新 HomePage）的**：
- WebSocket 消息处理（`lastMessage` switch-case，约 300 行）
- AI 状态管理（`agentStatus`、`isProcessing`、`streamingContent`）
- SessionStore 集成（`currentSessionId`、`messages`、`sendSessionMessage`）
- 思维流（`aiSteps`）+ 执行日志同步
- 消息发送（`handleSendMessage`、`handleSendControl`）
- MemoryPanel 侧边栏
- 首页专属浮动按钮（执行日志切换、ProposalBubble 等）
- 各种指示器（VoiceState、ModeSwitch、Perception、Observer）

**不需要提取的（已在新架构中）**：
- AuthGuard → 路由级已处理
- NotificationProvider → RootLayout 已处理
- WebSocketProvider → main.tsx 已处理
- GamificationProvider → main.tsx 已处理
- 页面切换逻辑（`currentPage` state、`hashchange`）→ react-router 已接管
- 其他页面的 `renderPageContent` case → router 已接管

**文件变更**：
- `frontend/src/AppHome.tsx` → 重写为完整首页（约 400～600 行）
- `frontend/src/App.tsx` → 标记为待删除（或留到阶段 1 再删，做对照）

#### 0.2 清理 Hash 路由残留（端对端：前端）
**文件与修改**：
| 文件 | 当前代码 | 改为 |
|---|---|---|
| `AppHome.tsx:36-37` | `<a href="#/tasks">` | `<Link to="/tasks">` |
| `SettingsPage.tsx:1100,1131` | `window.location.hash = 'aiconfig'` | `navigate('/aiconfig')` |
| `ToolMarketPage.tsx:872` | `window.location.hash = 'tools?tab=custom'` | `navigate('/tools?tab=custom')` |
| `TopBar.tsx:203` | `window.location.hash = 'settings'` | `navigate('/settings')` |

#### 0.3 apiClient.ts 引用迁移（端对端：前端）
**问题**：9 个新页面仍引用已弃用的 `apiClient.ts`（`fetchWithAuth`）
**涉及文件**：
- `pages/SettingsPage.tsx`
- `pages/FeaturesPage.tsx`
- `pages/SessionsPage.tsx`
- `pages/ReflectionsPage.tsx`
- `pages/WorkflowsPage.tsx`
- `pages/MemoryGraphPage.tsx`
- `pages/CostsPage.tsx`
- `components/trading/*.tsx`

**方案**：把这些文件中的 `fetchWithAuth` 调用全部替换为 `fetchAPI`，统一错误处理。

#### 0.4 modeStore.ts 裸 fetch 整改（端对端：前端）
**问题**：`switchMode` 和 `fetchCurrentMode` 用裸 `fetch`，无 401 处理、无超时
**方案**：改为 `fetchAPI('/api/system/mode', ...)` 和 `fetchAPI('/api/system/mode', { method: 'POST' })`
**后端配合**：`system_api.py` 已提供 `/api/system/mode`，无需新增端点，只需确认返回格式与前端期望一致。

#### 0.5 后端 Unicode 崩溃止血（端对端：后端）
**问题**：`cloud_api.py:2618` 打印 `✅` 导致 `UnicodeEncodeError: 'gbk' codec can't encode character '\u2705'`
**方案**：
- 立即修复：所有 lifespan 中的 `print(f"✅ ...")` 改为 `print(f"[OK] ...")` 或使用 ASCII 安全字符
- 或设置 `PYTHONIOENCODING=utf-8`
- 这是**单字符修复，零风险**，但必须先做，否则服务启动即崩溃

#### 0.6 memory_manager.py 语法错误修复（端对端：后端）
**问题**：`asyncio.create_task(await self._check_and_compress(user_id))`
**正确写法**：`asyncio.create_task(self._check_and_compress(user_id))`
**风险**：当前代码运行时传 `None` 给 `create_task`，会在后台抛 `TypeError`，但可能因 fire-and-forget 被静默吞掉

#### 0.7 统一 health 入口（端对端：后端）
**问题**：5 个 health 端点分散在各处
**方案（删除优先）**：
- 保留 `system_api.py: GET /api/system/health`（统一入口）
- 删除 `cloud_api.py` 的 `GET /api/health` 和 `GET /health`
- 删除 `stats_api.py` 的 `GET /api/stats/health`
- 删除 `auto_trading_api.py` 的 `GET /api/auto-trading/health`
- 删除 `sync_api.py` 的 `GET /api/sync/health`
- **如果**某些外部监控硬依赖 `/api/health`，改为 307 重定向到 `/api/system/health`

#### 0.8 验收标准
- [ ] 登录后 `/` 能看到聊天界面，能发消息，能收到 WebSocket 回复
- [ ] 页面间切换无 hash 路由（URL 无 `#`）
- [ ] `npm run build` 通过
- [ ] `python -m py_compile api/cloud_api.py` 通过
- [ ] `python -m py_compile core/memory/memory_manager.py` 通过
- [ ] `GET /api/system/health` 返回 200

---

### 阶段 1：接口对齐 + 子系统合并（3～4 天）
> 目标：前后端能通，删除冗余端点和文件

#### 1.1 cloud_api.py 硬编码端点收敛（端对端：后端 → 前端）
**问题**：cloud_api.py 直接定义 54 个 `@app.*` 端点，与 router 体系并存
**方案**：分批迁移到对应 router，或删除

**第一批（认证相关）**：
- `POST /api/auth/login` → `session_api.py`（已有 `/api/sessions/login` 或类似？需确认）
- `POST /api/auth/register` → `session_api.py`
- `POST /api/auth/change-password` → `session_api.py`
- `POST /api/auth/refresh` → `session_api.py`
- `POST /api/auth/logout` → `session_api.py`
- `GET /api/auth/me` → `session_api.py`

**第二批（聊天/消息）**：
- `POST /api/chat` → 新建 `chat_api.py` 或并入 `session_api.py`
- `POST /api/chat/stream` → 同上
- `GET /api/messages/{session_id}` → `session_api.py`

**第三批（直接删除或重定向）**：
- `GET /api/health` → 307 到 `/api/system/health`
- `GET /api/status` → 307 到 `/api/system/status`
- `GET /api/ready` → 307 到 `/api/system/ready`
- `GET /api/live` → 307 到 `/api/system/live`
- `GET /api/system` → 与 `system_api.py` 冲突，删除或合并
- `GET /api/tasks`（Fallback）→ 删除，依赖 `task_api.py`
- `GET /api/tasks/simple` → 检查是否被调用，如无调用则删除
- `GET /api/stats` → 检查是否被调用，如无则删除
- `GET /api/modelbus/status` → 移入 `system_api.py`
- `GET /api/ai-status` → 移入 `system_api.py`
- `GET /api/task-status/{task_id}` → 移入 `task_api.py`
- `GET /api/system/api-registry` → 保留或移入 `system_api.py`

#### 1.2 Memory 子系统合并（端对端：后端 → 前端）
**当前**：4 个文件（memory_api、memory_visualization_api、memory_graph_api、memory_sync_websocket）
**目标**：保留 `memory_api.py` 为主，迁入其他能力，统一前缀 `/api/memories`

**新路径规划**：
```
/api/memories                  # CRUD（已有）
/api/memories/search           # 向量搜索（从 memory_api 的 vector_router 迁入）
/api/memories/viz/flow         # 从 memory_visualization_api
/api/memories/viz/stats        # 从 memory_visualization_api
/api/memories/viz/timeline     # 从 memory_visualization_api
/api/memories/graph/nodes      # 从 memory_graph_api
/api/memories/graph/relations  # 从 memory_graph_api
/api/memories/graph/path       # 从 memory_graph_api
/api/memories/graph/visualization # 从 memory_graph_api
/api/memories/graph/stats      # 从 memory_graph_api
/api/memories/graph/discover   # 从 memory_graph_api
/api/memories/graph/export     # 从 memory_graph_api
/ws/memories                   # WebSocket（保留 memory_sync_websocket，但改前缀）
```

**注意**：
- `memory_api.py` 当前 prefix 是 `/memories`，`memory_visualization_api.py` 是 `/memory`，`memory_graph_api.py` 是 `/memory/graph`
- 统一为 `/memories` 后，前端 `utils/api/memory.ts` 需要同步改路径
- 旧路径返回 307 重定向（过渡期 1 个迭代）

#### 1.3 Task 子系统合并（端对端：后端 → 前端）
**当前**：4 个文件（task_api、long_task_slots_api、workflow_api、procedure_learning_api）
**目标**：保留 `task_api.py` 为主，迁入其他能力，统一前缀 `/api/tasks`

**新路径规划**：
```
/api/tasks                     # 通用任务 CRUD（已有）
/api/tasks/{task_id}/...       # 通用任务操作（已有）
/api/tasks/slots/{slot_id}/... # 从 long_task_slots_api
/api/tasks/workflows/{id}/...  # 从 workflow_api
/api/tasks/workflows/{id}/executions/... # 从 workflow_api
/api/tasks/procedures/...      # 从 procedure_learning_api
/api/tasks/procedures/recordings/start   # 从 procedure_learning_api
```

**interrupt_api.py 处理**：
- 当前 prefix `/sessions`，与 `session_api.py` 共享前缀
- 端点：`POST /api/sessions/{session_id}/interrupt`、`GET /api/sessions/{session_id}/status`
- **建议**：迁入 `session_api.py`，因为中断是"会话控制"而非"任务控制"

#### 1.4 status 端点收敛（端对端：后端）
**当前**：10+ 个子系统各自实现 `/status`
**方案**：
- 保留各子系统的 `/status` 作为**详细状态**（如 `/api/tasks/status`、`api/costs/status`）
- 新增 `system_api.py` 的 `GET /api/system/status` 作为**聚合状态**，调用各子系统状态后汇总
- 或：删除分散的 `/status`，只留 `system_api.py` 统一入口
- **推荐后者**（删除优先）：前端统一调 `/api/system/status`，后端在内部聚合

#### 1.5 features_api.py system_router 清理（端对端：后端）
**当前**：`features_api.py` 里有两个 router：`features_router`（prefix `/features`）和 `system_router`（无 prefix，被 mount 到 `/api`）
**方案**：
- `system_router` 的 `GET /mode` 和 `POST /mode` 迁入 `system_api.py`
- 删除 `features_api.py` 中的 `system_router`
- `cloud_api.py` 不再单独 `include_router(system_router)`

#### 1.6 world_model_api.py 处理（端对端：后端 → 前端）
**当前**：全部基于内存 random，mock 数据
**方案**：
- **短期**：标记所有端点为 deprecated，返回 `503 Service Unavailable` + `{"warning": "世界模型正在重构"}`
- **中期**：如果有真实训练 pipeline，接入真实数据
- **长期**：删除 mock 端点
- 前端 `/worldmodel` 页面暂时保留，但显示"重构中"提示

#### 1.7 前端路径同步（端对端：前端）
**涉及文件**：
- `utils/api/memory.ts`：改 `/api/memory/...` → `/api/memories/...`
- `utils/api/task.ts`：改 `/api/long-tasks/...` → `/api/tasks/slots/...`；改 `/api/workflows/...` → `/api/tasks/workflows/...`
- `utils/api/procedureLearning.ts`：已改为 `/api/procedures/...`，如果 task 合并则需再改
- `utils/api/session.ts`：确认 interrupt 端点路径

#### 1.8 验收标准
- [ ] API 文件数量从 39 个降到 ≤ 32 个（合并 memory* 3→1，task* 3→1，interrupt→session）
- [ ] `cloud_api.py` 中 `@app.*` 端点从 54 个降到 ≤ 20 个
- [ ] 旧端点返回 307 到新端点
- [ ] 前端所有 `fetchAPI` 调用路径与新端点对齐
- [ ] `npm run build` 通过
- [ ] 后端 AST 检查通过

---

### 阶段 2：数据层收敛 + 异步架构整改（4～5 天）
> 目标：PG 为唯一真相源，消除阻塞风险

#### 2.1 连接池统一（端对端：后端）
**当前**：`PostgresConnectionPool`（psycopg2，同步）+ `AsyncPostgresPool`（asyncpg，异步）混用
**方案**：
- **新代码强制使用 `AsyncPostgresPool`**
- **旧同步代码**：如果是异步上下文调用，用 `asyncio.to_thread()` 桥接；如果是同步工具脚本，保留 `PostgresConnectionPool`
- **迁移优先级**：
  1. `core/memory/execution_memory.py`：`_write_to_postgres_idempotent` → 改为 async，调用 `AsyncPostgresPool`
  2. `core/memory/memory.py`：`get_by_id()` 同步方法 → 改为 async 或加 `asyncio.to_thread`
  3. `core/db/connection_pool.py`：`PostgresConnectionPool` → 保留但标记 `@deprecated`，禁止新业务使用

#### 2.2 memories 表 DDL 统一（端对端：后端）
**当前**：三处定义不一致（`layer VARCHAR(20)` vs `VARCHAR(50)`）
**方案**：
- 以 `core/db/connection_pool.py` 的 DDL 为准（最宽：`VARCHAR(50/100/100)`）
- 统一 `scripts/init_database.py` 和 `scripts/init_postgres.py`
- 如果现有表字段较窄，写 ALTER TABLE 脚本扩宽

#### 2.3 JSONL 双写取消（端对端：后端）
**当前**：
- `execution_memory.py`：PG + JSONL 双写
- `session_persistence.py`：Redis + JSONL 双写
**方案**：
- **阶段 2 先取消 JSONL 双写**：删除 `_write_jsonl()` 调用，只保留 PG/Redis
- 物理 JSONL 文件保留（作为历史归档），不再写入新数据
- 后续阶段 3 再处理归档和清理

#### 2.4 cloud_tool_repo SQLite → PG 迁移（端对端：后端）
**当前**：`api/cloud_tool_repo.py` 用 `aiosqlite` 操作 `data/cloud_tools.db`
**方案**：
- 新建 `cloud_tools` PG 表（或复用已有表）
- `cloud_tool_repo.py` 改为使用 `AsyncPostgresPool`
- 一次性迁移脚本：读取 SQLite → 写入 PG → 标记 `migrated=true`
- 删除 `data/cloud_tools.db`

#### 2.5 global.yaml 只读化（端对端：后端）
**当前**：`Config.set()` 直接写 `global.yaml`，且文件内有明文测试凭证
**方案**：
- `global.yaml` 改为**只读模板**（删除 `test_key_*` 和 `test_sensitive`）
- `Config.set()` 改为写入 PG `system_settings` 表
- 启动时从 `global.yaml` 读取默认值，从 PG 读取覆盖值
- 敏感配置（密码、API key）走环境变量，不走 YAML

#### 2.6 线程迁移（端对端：后端）
**当前**：lifespan 中 `threading.Thread` 启动 4 类后台任务
**方案**：

| 当前实现 | 改为 | 状态管理 |
|---|---|---|
| 语音 init 线程 | `asyncio.create_task()` + `BackgroundTaskRegistry.register()` | lifespan 退出时 cancel |
| global_view 扫描线程 | `asyncio.create_task()` | lifespan 退出时 cancel |
| WebSocket server (8601) 线程 | `asyncio.create_task()` | lifespan 退出时 cancel |
| global_view ThreadPoolExecutor | `asyncio.get_running_loop().run_in_executor()` 或专用 executor | lifespan 退出时 shutdown |

**具体修改**：
- `cloud_api.py` lifespan 中：`threading.Thread(target=voice.start)` → `asyncio.create_task(async_voice_start())`
- `global_view.start_watch()` 当前是同步阻塞调用，需确认是否有 async 版本，如无则 `asyncio.to_thread()`
- `start_websocket_server_in_thread()` → `asyncio.create_task(start_websocket_server_async())`
- `_trading_ws_server_task` → lifespan 退出时 `cancel()` + `await`

#### 2.7 裸 create_task 治理（端对端：后端）
**方案**：
- 所有 `asyncio.create_task()` 必须经过 `BackgroundTaskRegistry`
- 如果没有返回值需求：`registry.register(task, name="xxx")`
- 如果有返回值需求：用 `asyncio.gather()` 或 `add_done_callback`
- 禁止裸 `create_task` 传播异常

#### 2.8 outbox 表引入（端对端：后端）
**问题**：跨存储双写（PG + Chroma + Redis）无分布式事务
**方案**：
- 新建 `outbox` 表：
  ```sql
  CREATE TABLE outbox (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    topic VARCHAR(50) NOT NULL,        -- 'vector_index', 'redis_sync', 'file_archive'
    payload JSONB NOT NULL,
    status VARCHAR(20) DEFAULT 'pending', -- pending / processing / completed / failed
    retry_count INT DEFAULT 0,
    max_retries INT DEFAULT 3,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    processed_at TIMESTAMPTZ
  );
  CREATE INDEX idx_outbox_status ON outbox(status, created_at);
  ```
- `MemoryService.save_chat_turn()` 只写 PG `memories`
- 向量索引改为：写 PG 成功后，插入 `outbox(topic='vector_index')`
- 后台 worker（`asyncio.create_task` 循环）消费 outbox，完成 ChromaDB 索引
- 失败时重试，超过 `max_retries` 标记 `failed` 并告警

#### 2.9 验收标准
- [ ] 新环境启动时只创建一套 schema（`init_database.py` 删除 `tasks`/`executions` 遗留表）
- [ ] `outbox` 表创建成功
- [ ] 后台任务全部通过 `BackgroundTaskRegistry` 管理
- [ ] lifespan 退出时所有任务正确 cancel
- [ ] 无 `threading.Thread` 在 lifespan 中启动
- [ ] `global.yaml` 不再被写入

---

### 阶段 3：前端轮询治理 + UI 统一（3～4 天）
> 目标：消灭 30+ 处 setInterval，统一 UI 组件

#### 3.1 React Query 接入（端对端：前端）
**当前**：已安装 `@tanstack/react-query@5.74.0`，零使用
**方案**：
- `main.tsx` 包裹 `QueryClientProvider`
- 定义 `queryClient` 全局实例，配置默认 `staleTime: 30000`, `refetchOnWindowFocus: true`
- 将高频轮询页面分批迁移：

| 页面 | 当前轮询 | React Query 方案 |
|---|---|---|
| TasksPage | `setInterval(fetchTasks, 5000)` | `useQuery({ queryKey: ['tasks'], queryFn: fetchTasks, refetchInterval: 5000 })` |
| DashboardPage | `setInterval(fetchDashboard, 5000)` | `useQuery({ queryKey: ['dashboard'], refetchInterval: 5000 })` |
| TradingDashboardPage | 多组件各搞一套 | 统一 `useQuery` + `useMutation` |
| SiliconLifeMonitorPage | `setInterval(fetchLifeStatus, 30000)` | `useQuery({ queryKey: ['lifeStatus'], refetchInterval: 30000 })` |
| GlobalViewPage | `setInterval(fetchScanStatus, ?)` | `useQuery({ queryKey: ['scanStatus'], refetchInterval: 5000 })` |

**注意**：
- WebSocket 推送的数据（如 AI 状态、聊天消息）**不走 React Query**，保持 WebSocket 实时性
- 轮询数据（任务列表、监控指标）**走 React Query**
- `useWebSocket.tsx` 中的心跳 `setInterval` 保留（这是协议级心跳，不是业务轮询）

#### 3.2 通用 UI 组件基建（端对端：前端）
**新建文件**：
- `src/components/ui/Loading.tsx`：统一加载动画（旋转圆圈 + 文字）
- `src/components/ui/EmptyState.tsx`：空状态（图标 + 标题 + 描述 + 可选操作按钮）
- `src/components/ui/ErrorState.tsx`：错误状态（图标 + 错误信息 + 重试按钮）
- `src/components/ui/PageLayout.tsx`：页面布局（标题栏 + 内容区 + 可选操作区）
- `src/components/ui/PageHeader.tsx`：页头（面包屑 + 标题 + 右侧操作）

**迁移目标**：
- 所有新页面（CostsPage、FeaturesPage、WorkflowsPage 等）已使用各自 loading，改为通用组件
- 旧页面（TasksPage、DashboardPage 等）逐步替换

#### 3.3 Ant Design 迁移计划（端对端：前端）
**当前**：6 个文件使用 antd
**策略**：
- **短期（阶段 3）**：保留 antd 依赖，但做暗色主题适配（当前页面在暗色背景下 antd 组件可能刺眼）
- **长期（阶段 4 或下一迭代）**：完全迁移到 Tailwind

**具体迁移**：
| 组件 | antd 用法 | Tailwind 替换方案 |
|---|---|---|
| Button | `antd Button` | 自建 `<Button variant="primary/ghost/danger">` |
| Card | `antd Card` | `div className="rounded-xl border border-white/10 bg-slate-900/50"` |
| Badge | `antd Badge` | 自建 `<Badge status="success/error/warning">` |
| Timeline | `antd Timeline` | 自建时间轴组件或直接用 `div` 列表 |
| Progress | `antd Progress` | 自建进度条或保留 antd 的 Progress（如果其他都已迁，单独保留一个组件不划算） |
| Tag | `antd Tag` | `span className="px-2 py-0.5 rounded-full bg-cyan-500/20 text-cyan-400 text-xs"` |
| Empty | `antd Empty` | `<EmptyState />` |
| Spin | `antd Spin` | `<Loading />` |
| Alert | `antd Alert` | 自建 `<Alert variant="info/success/warning/error">` |
| Modal | `antd Modal` | 自建 `<Modal>` 或 `Dialog` |
| message | `antd message` | 通知系统已存在（`useNotifications`），直接替换 |
| Slider | `antd Slider` | 自建或保留（仅 TonePreferencePanel 用） |
| Tooltip | `antd Tooltip` | 自建或保留（使用面较广） |

**结论**：antd 的 `Tooltip`、`Slider`、`Modal` 使用面较广且自建成本高，**阶段 3 先保留这三个**，其余全部替换。阶段 4 再考虑是否彻底删除 antd。

#### 3.4 验收标准
- [ ] React Query 覆盖 ≥ 50% 的轮询场景
- [ ] 通用 UI 组件覆盖全部新增页面
- [ ] `npm run build` 通过
- [ ] 暗色主题下 antd 组件不刺眼（或已迁移）

---

## 四、删除清单（按阶段）

### 阶段 0 删除
| 文件/代码 | 原因 |
|---|---|
| `frontend/src/App.tsx`（确认后） | 完全悬空的 1370 行遗留组件 |
| `frontend/src/AppHome.tsx` 占位内容 | 被完整首页替换 |
| `cloud_api.py` 中的 `print("✅ ...")` | Unicode 崩溃 |
| `cloud_api.py` 的 `GET /api/health`（可选保留 307） | 重复 |
| `cloud_api.py` 的 `GET /health` | 重复 |

### 阶段 1 删除
| 文件/代码 | 原因 |
|---|---|
| `api/memory_visualization_api.py` | 合并到 memory_api |
| `api/memory_graph_api.py` | 合并到 memory_api |
| `api/long_task_slots_api.py` | 合并到 task_api |
| `api/workflow_api.py` | 合并到 task_api |
| `api/procedure_learning_api.py` | 合并到 task_api |
| `api/interrupt_api.py` | 合并到 session_api |
| `api/world_model_api.py`（或标记 deprecated） | 全 mock |
| `api/cloud_api_minimal.py` | 测试文件，移到 tests/ |
| `api/run_minimal_test.py` | 测试文件，移到 tests/ |
| `features_api.py` 的 `system_router` | 能力迁入 system_api |
| `stats_api.py` 的 `GET /api/stats/health` | 重复 |
| `auto_trading_api.py` 的 `GET /api/auto-trading/health` | 重复 |
| `sync_api.py` 的 `GET /api/sync/health` | 重复 |
| `cloud_api.py` 中已迁移的 `@app.*` 端点 | 收敛到 router |

### 阶段 2 删除
| 文件/代码 | 原因 |
|---|---|
| `scripts/init_database.py` 中的 `tasks`/`executions` 建表 | 遗留表 |
| `core/memory/execution_memory.py` 中的 JSONL 写入 | 双写取消 |
| `core/session/session_persistence.py` 中的 JSONL 写入 | 双写取消 |
| `data/cloud_tools.db` | 迁移到 PG |
| `data/memory/*.db` | 遗留 SQLite |
| `global.yaml` 中的 `test_key_*` / `test_sensitive` | 明文凭证 |
| `PostgresConnectionPool` 新业务引用 | 统一 asyncpg |

### 阶段 3 删除
| 文件/代码 | 原因 |
|---|---|
| 30+ 处 `setInterval`（业务轮询） | React Query 替代 |
| `apiClient.ts`（确认所有引用迁移后） | 已弃用 |
| `antd` 中已替换的组件引用 | UI 统一 |

---

## 五、风险与缓解

| 风险 | 缓解 |
|---|---|
| 首页迁移引入 Provider 嵌套问题 | 从旧 App.tsx 只提取"纯逻辑"和"纯 UI"，不提取 Provider/AuthGuard/路由 |
| 合并 API 文件导致旧端点 404 | 旧端点保留 307 重定向 1 个迭代 |
| 取消 JSONL 双写后文件不再更新 | 保留历史文件只读，新数据只走 PG |
| React Query 替代 setInterval 后行为变化 | 保持相同 refetchInterval，先对齐再优化 |
| thread 迁 asyncio 导致语音/global_view 异常 | 每个迁移单独测试，保留 fallback 分支 |
| cloud_tool_repo SQLite→PG 迁移失败 | 一次性脚本，失败可回滚到 SQLite |
| memories DDL 不一致导致新环境建表冲突 | 统一以最宽字段为准，现有环境 ALTER TABLE |

---

## 六、实施顺序建议

**第 1 天**：
- 0.5 Unicode 崩溃修复（30 分钟）
- 0.6 memory_manager.py 语法修复（30 分钟）
- 0.1 首页恢复（核心，4～6 小时）

**第 2 天**：
- 0.2 Hash 路由清理（2 小时）
- 0.3 apiClient.ts 引用迁移（3 小时）
- 0.4 modeStore.ts 整改（1 小时）
- 0.7 health 统一（1 小时）
- 冒烟测试

**第 3～4 天（阶段 1）**：
- cloud_api.py 端点收敛（分批）
- Memory 子系统合并
- Task 子系统合并
- 前端路径同步
- 冒烟测试

**第 5～7 天（阶段 2）**：
- 连接池统一（高优先级）
- JSONL 双写取消
- cloud_tool_repo SQLite→PG
- global.yaml 只读化
- thread 迁 asyncio
- outbox 表

**第 8～10 天（阶段 3）**：
- React Query 接入
- 轮询迁移
- UI 组件基建
- Ant Design 部分迁移

---

## 七、必须立即决定的两个问题

### 问题 1：首页恢复的策略选择
**选项 A（保守）**：从旧 App.tsx 提取 `AppContent` 中的首页逻辑，剥离 Provider/路由后塞入 `AppHome.tsx`。风险：可能带入旧习惯（如 `window.dispatchEvent` 全局事件）。
**选项 B（重构）**：只提取状态逻辑（WebSocket 处理、消息发送），UI 层重新组装（用现有 `MessageList`、`InputArea`、`MainCanvas`）。风险：工作量大，可能引入新 bug。

**建议选 A**：旧逻辑已经跑通过，只需剥离包装层。Provider 嵌套问题通过"不在 AppHome 中再套 Provider"解决（依赖 main.tsx + RootLayout 已有的 Provider）。

### 问题 2：Ant Design 的处理策略
**选项 A（阶段 3 全删）**：6 个文件全部重写为 Tailwind。风险：工作量大（约 800～1200 行组件代码），可能拖慢阶段 3。
**选项 B（阶段 3 适配暗色，阶段 4 再删）**：先让 antd 在暗色主题下能看（配置 antd ConfigProvider theme="dark"），降低用户视觉不适。风险：保留 antd 依赖，包体积稍大。

**建议选 B**：Ant Design 在阶段 0～2 完全不阻塞功能，视觉问题可以通过暗色主题配置快速缓解。

---

## 八、验收总标准

- [ ] `/` 首页能聊天（WebSocket 消息收发正常）
- [ ] 所有页面通过 path 路由访问，URL 无 `#`
- [ ] 没有页面直接返回 404（接口前缀对齐）
- [ ] API 文件数量 ≤ 32 个（现 39 个）
- [ ] cloud_api.py 直接端点 ≤ 20 个（现 54 个）
- [ ] 前端只有一个 `fetchAPI` 实现被使用
- [ ] React Query 覆盖 ≥ 50% 轮询
- [ ] 后台任务全部通过 `BackgroundTaskRegistry` 管理
- [ ] 无 `threading.Thread` 在 lifespan 中启动
- [ ] `global.yaml` 只读，敏感配置走环境变量
- [ ] `npm run build` 通过
- [ ] 后端 AST 检查全部通过
- [ ] 冒烟测试：登录 → 聊天 → 切页面 → 调接口 → 退出，全流程无报错
