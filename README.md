# SiliconBase V5

> AI 智能体开发与测试平台

---

## 🚀 项目简介

**SiliconBase V5** 是一个 AI 智能体开发与测试平台，提供完整的智能体生命周期管理、测试和监控能力。

### 核心特性

- 🤖 **多代理协作** - 支持多 Agent 协同工作
- 🧠 **记忆系统** - L1-L5 多级记忆存储架构
- 🔄 **双模式运行** - 支持 Observer 和 Manual 两种模式
- 🛠️ **工具系统** - 完整的工具注册和调用链
- 📊 **可视化监控** - 实时状态监控和数据可视化
- 🔊 **语音交互** - 支持语音输入和播报
- 📝 **提示系统** - 动态提示模板和热重载
- 🎯 **道德规则** - 内置道德审查模块
- 🔧 **子代理系统** - 支持子代理任务分发

---

## 📁 项目结构

```
SiliconBase_V5/
│
├── SiliconBase_V5/          # 后端主代码
│   ├── api/                 # API 模块 (FastAPI)
│   │   ├── run.py           # 服务启动入口
│   │   ├── cloud_api.py     # 主 API 路由
│   │   ├── auth_utils.py    # 认证工具
│   │   └── ...              # 其他 API 模块
│   │
│   ├── core/                # 核心模块
│   │   ├── agent_loop.py    # Agent 主循环
│   │   ├── memory.py        # 记忆系统
│   │   ├── tool_manager.py  # 工具管理
│   │   ├── moral_rules/     # 道德规则
│   │   └── subagent/        # 子代理系统
│   │
│   ├── frontend/            # 前端代码 (React + Vite)
│   ├── config/              # 配置文件
│   ├── models/              # 数据模型
│   └── .venv/               # Python 虚拟环境
│
├── docs/                    # 项目文档
├── tests/                   # 测试代码
├── data/                    # 数据目录
├── logs/                    # 日志目录
└── outputs/                 # 输出目录
```

---

## 🚦 快速开始

### 前置要求

- Python 3.11+
- Node.js 18+
- PostgreSQL 14+ (可选，支持 SQLite)

### 一键启动（推荐）

```bash
# 快速启动（禁用 MCP，10秒内启动）
双击: 一键部署启动.bat

# 完整启动（启用所有功能）
双击: 启动V5-标准版.bat
```

### 分别启动

```bash
# 仅启动后端
双击: 启动后端.bat

# 仅启动前端
双击: 启动前端.bat
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
|------|------|------|
| 前端界面 | http://localhost:5173 | Web 界面 |
| API 文档 | http://localhost:8600/docs | Swagger 文档 |
| 健康检查 | http://localhost:8600/api/health | 服务状态 |
| WebSocket | ws://localhost:8601/ws/{user_id} | 实时通信 |

### 默认登录

> ⚠️ **已知风险**：当前 `config/global.yaml` 和 `config/local.yaml` 中仍写死默认账号 `admin/admin123`（以及 `user/user123`）。这意味着首次启动后可以直接用弱密码登录，**存在严重安全风险**。
>
> 正确行为（修复后）：若配置中未提供默认用户，系统会为 `admin` 生成随机初始密码并保存到 `SiliconBase_V5/data/.initial_password.txt`，且首次登录会强制要求修改密码。
>
> 在修复完成前，请勿将当前配置部署到任何非完全隔离环境。

---

## 🧪 测试

```bash
# 运行所有测试
python -m pytest tests/ -v

# 运行特定测试
python tests\test_xxx.py
```

---

## 🔧 开发

### 技术栈

- **后端**: Python 3.11+, FastAPI, SQLAlchemy, Uvicorn
- **前端**: React 18, TypeScript, Vite, Tailwind CSS, Ant Design
- **数据库**: PostgreSQL / SQLite, ChromaDB (向量库)
- **AI**: 支持 OpenAI, DeepSeek, Ollama 等多种模型

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

## 📚 文档导航

| 文档 | 说明 |
|------|------|
| [启动说明.md](启动说明.md) | 详细启动指南 |
| [docs/README.md](docs/README.md) | 完整文档导航 |
| [docs/reports/INDEX.md](docs/reports/INDEX.md) | 报告索引 |

---

## 🛡️ 核心模块

| 模块 | 说明 | 路径 |
|------|------|------|
| Agent 循环 | 智能体主循环逻辑 | `core/agent_loop.py` |
| 记忆系统 | L1-L5 多级记忆存储 | `core/memory.py` |
| 工具管理 | 工具注册与调用 | `core/tool_manager.py` |
| 道德规则 | 内容安全审查 | `core/moral_rules/` |
| 子代理 | 任务分发执行 | `core/subagent/` |
| 提示模板 | 动态提示管理 | `templates/` |

---

## 🤝 贡献

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送分支 (`git push origin feature/AmazingFeature`)
5. 创建 Pull Request

---

## 📄 许可证

MIT License - 详见 [LICENSE](LICENSE) 文件

---

**项目版本**: v5.0  
**维护者**: SiliconBase Team
