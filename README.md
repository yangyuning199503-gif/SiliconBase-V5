# SiliconBase V5

一个具备**主权架构、自主感知和多级记忆**的本地 AI Agent 平台。

![SiliconBase V5 主界面](docs/images/home.png)

SiliconBase V5 不是又一个 LLM 工具链。它是一个能**持续感知环境、管理长期记忆、并在需要时主动行动**的数字生命体框架。

现在主流的 AI Agent 框架（LangChain、AutoGPT、CrewAI 等），本质上都是在大模型外面做工具编排。SiliconBase V5 走了另一条路：**从操作系统层重新设计 AI 的运行环境**。

---

## 🧠 为什么是"主权架构"？

现在的 AI Agent 有个通病：**什么事都丢给 LLM 决定**。

LLM 调用工具、LLM 管理记忆、LLM 做决策。听起来很智能，实际上有三个硬伤：

1. **LLM 记不住那么多东西** — 上下文窗口有限，不可能把完整记忆和系统状态全塞进去
2. **LLM 太贵、太慢** — 每次点个按钮都要调用大模型，延迟和成本都扛不住
3. **LLM 没有连续性** — 每次对话都像第一次见， yesterday 的经验今天 reset 了

SiliconBase V5 的解法很简单：**让系统自己当家，LLM 只是它调用的工具之一**。

- **思维线程（Consciousness）** 才是真正的决策者
- **记忆系统** 独立于 LLM，有自己的存储、检索、价值评估和晋升机制
- **视觉感知系统** 先用规则快速扫描，只在遇到不认识的东西时才请大模型出山

### 四层主权架构

| 层级 | 职责 | 类比 |
|---|---|---|
| **L1 主权层** | 判断这条输入该不该处理、怎么处理，并更新自我状态 | 大脑前额叶 |
| **L2 翻译层** | 把人类的自然语言压缩成机器能看懂的结构化意图 | 翻译官 |
| **L3 执行层** | 跑 Agent 主循环、调用工具、把结果返回来 | 手和脚 |
| **L4 记忆层** | 记录"我是谁、我在哪、我经历了什么"，并反向影响下一次决策 | 自传体记忆 |

这套架构让系统有了**真正的连续性**：它记得你昨天教过它什么，记得自己之前犯过什么错，甚至会基于这些记忆调整自己的行为。

---

## 🧩 为什么记忆要分五层？

如果只有"短期记忆"和"长期记忆"，很多场景会卡住：

- **昨天的经验** 今天还需要，但已经过了短期记忆窗口
- **某次工具调用为什么成功/失败** 必须单独记录，不能和聊天内容混在一起

所以 SiliconBase V5 把记忆拆成了五层：

| 层级 | 名称 | 用途 | 类比 |
|---|---|---|---|
| **L1** | 工作记忆 | 当前会话的上下文 | 注意力 |
| **L2** | 短期记忆 | 1 天内过期的原始记录 | 今天发生的事 |
| **L3** | 中期记忆 | 7 天内过期的高价值经验 | 最近一周学会的东西 |
| **L4** | 长期记忆 | 永久保存的进化知识 | 人生经验 |
| **L5** | 执行记忆 | 每次工具调用的完整记录 | 肌肉记忆 |

这套系统会**自动决定什么值得记住、什么该忘掉**：

- 统一入口 `MemoryManager`，用户输入、AI 回复、工具执行都会自动触发记忆存储
- 基于 `ChromaDB` 的向量语义检索，能搜到"意思相近但措辞不同"的历史经验
- 自动评估记忆价值，低价值的过期淘汰，高价值的自动晋升到更长期层级
- 单用户 50MB 总上限，防止记忆无限膨胀

---

## 👁️ 视觉感知：它不认识的东西，会自己学

传统桌面 AI 靠固定模型识别 UI，换一个软件版本、换一个操作系统可能就废了。

SiliconBase V5 的视觉系统走的是**"发现 → 理解 → 记住 → 越用越快"**的闭环：

1. **发现**：用 Canny 边缘检测 + 轮廓提取 + 形态过滤，先找出画面里"像个东西"的区域。这一步**纯规则，不调用 AI**，所以很快。
2. **融合**：把四个来源的结果拼起来 — ONNX 通用物体检测、EasyOCR 文字识别、UIAutomation 控件检测、轮廓提取
3. **学习**：遇到不认识的元素，自动裁剪子图，调用大视觉模型（如 qwen3-vl:8b）打标签
4. **记忆**：标签和特征存入向量记忆库
5. **复用**：下次再见到同类元素，通过感知哈希 / md5 / LabelCache / 向量相似度四层召回，**瞬间识别**

简单说：**它越用你的电脑，越熟悉你的软件**。

> ⚠️ 未知元素学习默认是关闭的。开启后会调用大视觉模型（单次约 20-30 秒），建议在确认模型可用后再打开。

---

## 📈 AI 驱动的加密货币交易子系统

SiliconBase V5 内置了一套完整的 AI 交易框架：

![AI 交易指挥官报告](docs/images/trading.png)

- **执行器抽象**：抽象基类 `TradeExecutor`，下面有模拟盘 `SimulationExecutor`、OKX 实盘 `OKXExecutor`、币安 `BinanceExecutor`
- **AI 交易子代理**：`TradingSubAgent` 跑异步决策循环，自己决定什么时候买、什么时候卖
- **MCP 指挥官**：`AITradingCommander` 负责策略分析和任务分发
- **实时行情推送**：独立 8602 端口 WebSocket，把价格、持仓、信号、风险实时推送到前端
- **OKX 异步客户端**：`aiohttp` + HMAC 签名，5 秒缓存

> ⚠️ 目前 OKX 实盘的平仓、持仓、账户、余额接口还在 TODO；Binance 执行器也还只是个骨架。建议先用模拟盘体验。

---

## 🔧 其他值得说的工程细节

- **全异步 AgentLoop**：Phase 8 已完成单核异步统一化，所有高频路径都是原生 `async/await`
- **Rust / PyO3 硬壳层**：核心协议、事件总线、条件求值用 Rust 实现，Python 负责灵活迭代
- **配置和 Prompt 热重载**：改 `roles.yaml` 不用重启服务，改完自动生效
- **背景任务统一治理**：用 `BackgroundTaskRegistry` 管生命周期，避免野任务泄漏
- **Token 预算管理**：控制 AI 调用成本，自动做智能截断

---

## 🚀 快速开始

### 前置要求

- Python 3.11+
- Node.js 18+
- PostgreSQL 14+
- ChromaDB（可选，向量记忆用）

### Windows 一键启动

```bash
# 快速启动（禁用 MCP，10 秒内启动）
双击: 一键部署启动.bat

# 完整启动（启用所有功能）
双击: 启动V5-标准版.bat
```

### 界面预览

| 登录页 | 主界面 | 交易报告 |
|---|---|---|
| ![登录页](docs/images/login.png) | ![主界面](docs/images/home.png) | ![交易报告](docs/images/trading.png) |

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

- `.env`、数据库密码、API Key 等敏感信息已通过 `.gitignore` 排除，不会提交到 GitHub
- 请勿把 `data/.initial_password.txt` 提交到版本控制
- 实盘交易接口仍在完善，当前默认使用模拟盘

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

## 🛠️ 开发

### 技术栈

- **后端**：Python 3.11+, FastAPI, Uvicorn, asyncpg
- **前端**：React 18, TypeScript, Vite, Tailwind CSS
- **数据库**：PostgreSQL, ChromaDB
- **AI 后端**：OpenAI, Anthropic, DeepSeek, Ollama
- **语音**：Vosk（识别）, Piper / pyttsx3（合成）
- **Rust 扩展**：maturin

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

---

## ⚠️ 已知限制

- **8601 端口已废弃**：WebSocket 已统一走 8600 端口
- **SQLite 已废弃**：记忆层强制使用 PostgreSQL
- **未知元素学习默认关闭**：需手动开启，开启后会调用大视觉模型
- **OKX 实盘接口待完善**：平仓、持仓、账户、余额为 TODO；Binance 执行器为基本骨架
- **交易 WS K 线当前为合成数据**：真实 K 线接入仍在开发中

---

## 📄 许可证

MIT License - 详见 [LICENSE](LICENSE) 文件

---

**项目版本**: v5.0  
**维护者**: SiliconBase Team
