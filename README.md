# SiliconBase V5

> 一个具备**主权架构、多级记忆、视觉感知与自主意识**的本地 AI Agent 平台。

SiliconBase V5 不只是大语言模型的封装，而是一个以**思维线程（Consciousness）**为核心的数字生命体框架。它持续感知桌面环境、管理长期记忆、调用工具、执行交易，并通过语音与 Web 界面与用户交互。

---

## 🌟 核心设计亮点

### 1. 四层主权-翻译-执行-记忆架构

突破传统 "LLM 直接决定一切" 的设计，将系统拆分为四层职责：

| 层级 | 职责 | 核心文件 |
|---|---|---|
| L1 主权层 | 输入裁决与自我状态更新 | `core/consciousness/Consciousness.py` |
| L2 翻译层 | 自然语言压缩为结构化意图 | `core/consciousness/intent_translator.py` |
| L3 执行层 | Agent 循环与工具调用 | `core/agent/agent_loop.py`, `core/dialog/dialogue_manager.py` |
| L4 记忆层 | 自我叙事与状态持久化 | `core/consciousness/self_state.py`, `core/consciousness/self_narrative.py` |

层间通过 `Intent / RoutingDecision / ActionResult` 等标准化数据契约通信，降低模块耦合。

### 2. 单核异步统一化的 AgentLoop

已完成 Phase 8 全链路异步化改造：

- 唯一生产入口为 `run_agent_loop_async()`，统一使用 `async/await`
- `AgentLoopHooks` 注册 `SafetyHook / VisionHook / ToolHook / VoiceHook / CoreLogicHooks`
- 事件总线 `EventBus` + 21 板块注册表 `PlateRegistry` 提供模块化扩展机制
- `PhasePilot` 阶段注册机制支持可插拔的上下文组装 / Prompt 组装 / 工具执行

### 3. L1-L5 五层记忆系统

| 层级 | 名称 | 用途 |
|---|---|---|
| L1 | 工作记忆 | 当前会话上下文 |
| L2 | 短期记忆 | 1 天过期的原始记录 |
| L3 | 中期记忆 | 7 天过期的高价值经验 |
| L4 | 长期/进化记忆 | 永久存储的进化知识 |
| L5 | 执行记忆 | 每次工具执行的完整记录 |

- 统一入口：`MemoryManager` 单例
- 自动触发：`MemoryAutoTrigger` 覆盖用户输入、AI 回复、工具执行、任务事件
- 向量语义检索：基于 `ChromaDB` + `all-MiniLM-L6-v2`
- 价值评估与晋升：`memory_promotion.py` 支持多维评分与自动淘汰
- 容量保障：单条 8192 字符上限，单用户 50MB 总上限

### 4. 类人视觉感知与未知元素学习

- **轮廓感知引擎**：Canny 边缘检测 + 轮廓提取 + 形态过滤，识别纯图形元素
- **四源融合检测器 `RealtimeDetector`**：融合 ONNX 通用检测、EasyOCR、UIAutomation、轮廓提取
- **未知元素学习闭环**：发现未知 UI 元素 → 大视觉模型打标签 → 存入向量记忆库 → 四层召回复用
  - ⚠️ 该功能默认关闭，需手动 `enable_vision_discovery()` 开启
- **结构化视觉快照**：将检测结果渲染为场景分层的自然语言描述，让 LLM 直接理解界面
- **资源自适应降级**：CPU/内存紧张时自动降低感知频率、关闭 OCR
- **全局视野 `Global View`**：维护本地软件/文件库并同步到向量记忆，支持语义搜索

### 5. AI 驱动的加密货币交易子系统

- **执行器抽象**：`TradeExecutor` ABC + `SimulationExecutor` / `OKXExecutor` / `BinanceExecutor`
- **AI 交易子代理**：`TradingSubAgent._trading_cycle()` 异步循环决策
- **MCP 指挥官**：`AITradingCommander` 标准化角色 Prompt，支持量化模式
- **实时行情推送**：独立 8602 端口 WebSocket，推送价格、持仓、信号、风险
- **OKX 异步客户端**：`aiohttp` + HMAC 签名，5 秒缓存
  - ⚠️ OKX 实盘执行器的平仓、持仓、账户、余额接口仍为 TODO；Binance 执行器为基本骨架

### 6. Rust / PyO3 硬壳层

- `rust_core/` 通过 `maturin` 构建为 `siliconbase_core`
- 暴露条件求值、EventBus 等核心能力
- 在关键路径用编译时安全补足 Python 的灵活性

### 7. 配置与 Prompt 热重载

- `core/config.py` 支持配置文件热加载，并对核心命名空间做写保护
- `core/prompt/prompt_builder_v2.py` 通过 `watchdog` 监听 `config/roles.yaml`，修改后自动生效
- `TokenBudgetManager` 提供成本预算与智能截断
- `PromptDebugger` 保存每次 AI 调用的完整 Prompt，便于调试

### 8. 背景任务统一治理

- `BackgroundTaskRegistry` 统一管理异步任务生命周期
- 交易执行器、子代理、指挥官均使用注册表，避免裸 `asyncio.create_task`

---

## 🏗️ 架构概览

```
用户交互层 (React + TypeScript + Vite)
        ↓
核心调度层 (FastAPI + Uvicorn)
        ↓
认知决策层 (Consciousness / AgentLoop / DialogueManager)
        ↓
工具执行层 (ToolManager / SubAgent / TradingSubAgent)
        ↓
感知监控层 (Vision / WindowMonitor / ResourceMonitor / Global View)
        ↓
基础设施层 (PostgreSQL / ChromaDB / Redis / Rust Core)
```

---

## 🚀 快速开始

### 前置要求

- Python 3.11+
- Node.js 18+
- PostgreSQL 14+
- ChromaDB（可选，用于向量记忆）

### 一键启动（Windows）

```bash
# 快速启动（禁用 MCP，10 秒内启动）
双击: 一键部署启动.bat

# 完整启动（启用所有功能）
双击: 启动V5-标准版.bat
```

### 命令行启动

```bash
# 后端
cd SiliconBase_V5
.venv\Scripts\python.exe api\run.py --host 0.0.0.0 --port 8600

# 前端
cd SiliconBase_V5\frontend
npm run dev
```

---

## 🌐 访问地址

| 服务 | 地址 | 说明 |
|---|---|---|
| 前端界面 | http://localhost:5173 | Web 界面 |
| API 文档 | http://localhost:8600/docs | Swagger 文档 |
| 健康检查 | http://localhost:8600/api/health | 服务状态 |
| 主 WebSocket | ws://localhost:8600/ws/{user_id} | 实时对话与任务 |
| 交易 WebSocket | ws://localhost:8602/ws/trading/{symbol} | 实时行情/信号 |

### 默认登录

首次启动时，系统会生成随机 `admin` 初始密码并保存到 `SiliconBase_V5/data/.initial_password.txt`，同时强制要求首次登录后修改密码。

---

## 🛡️ 安全说明

- `.env`、数据库密码、API Key 等敏感信息已通过 `.gitignore` 排除，不会提交到 GitHub。
- 请勿将 `data/.initial_password.txt` 提交到版本控制。
- OKX 实盘交易相关接口仍在完善中，当前默认走模拟盘模式。

---

## 📁 项目结构

```
SiliconBase_V5/
│
├── SiliconBase_V5/          # 后端主代码
│   ├── api/                 # FastAPI 路由与启动入口
│   ├── core/                # 核心模块
│   │   ├── agent/           # Agent 主循环
│   │   ├── consciousness/   # 意识线程、自我状态、叙事
│   │   ├── memory/          # 记忆系统
│   │   ├── tool/            # 工具管理
│   │   ├── vision/          # 视觉感知
│   │   ├── btc_integration/ # 加密货币交易
│   │   └── ...
│   ├── frontend/            # React + TypeScript 前端
│   ├── config/              # 配置文件
│   └── rust_core/           # Rust / PyO3 硬壳层
│
├── docs/                    # 项目文档
├── data/                    # 运行时数据（已 gitignore）
├── logs/                    # 日志目录（已 gitignore）
└── outputs/                 # 输出目录（已 gitignore）
```

---

## 🔧 开发

### 技术栈

- **后端**：Python 3.11+, FastAPI, SQLAlchemy, Uvicorn, asyncpg
- **前端**：React 18, TypeScript, Vite, Tailwind CSS, Ant Design
- **数据库**：PostgreSQL, ChromaDB
- **AI 后端**：OpenAI, Anthropic, DeepSeek, Ollama
- **语音**：Vosk（识别）, Piper / pyttsx3（合成）
- **构建**：maturin（Rust 扩展）

### 安装依赖

```bash
# 后端
cd SiliconBase_V5
pip install -r requirements.txt

# 前端
cd SiliconBase_V5\frontend
npm install
```

### 环境配置

```bash
# 复制环境变量模板
copy .env.example .env

# 编辑 .env 文件配置
- JWT_SECRET_KEY=your-secret-key
- DATABASE_URL=postgresql://user:pass@localhost/dbname
- OPENAI_API_KEY=sk-...
```

### 常用命令

```bash
# 语法校验
python -m py_compile <文件路径>

# 运行测试
python -m pytest tests/ -v

# Lint
ruff check .

# Rust 硬壳层构建
maturin develop --release
```

---

## ⚠️ 已知限制

- **8601 端口已废弃**：WebSocket 已统一走 8600 端口。
- **SQLite 已废弃**：记忆层强制使用 PostgreSQL。
- **未知元素学习默认关闭**：需手动开启，避免启动即大量调用视觉模型。
- **OKX 实盘接口待完善**：平仓、持仓、账户、余额接口为 TODO；Binance 执行器为基本骨架。
- **交易 WS K 线当前为合成数据**：真实 K 线接入仍在开发中。

---

## 📄 许可证

MIT License - 详见 [LICENSE](LICENSE) 文件

---

**项目版本**: v5.0  
**维护者**: SiliconBase Team
