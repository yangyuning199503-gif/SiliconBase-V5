# SiliconBase V5 Source Code

A local-first AI Agent platform with **sovereignty architecture, autonomous perception, and multi-tier memory** — **fully open-source**.

![License](https://img.shields.io/badge/License-MIT-blue.svg)
![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![TypeScript](https://img.shields.io/badge/TypeScript-5.0%2B-blue)
![Last Commit](https://img.shields.io/github/last-commit/yangyuning199503-gif/SiliconBase-V5)
![Repo Size](https://img.shields.io/github/repo-size/yangyuning199503-gif/SiliconBase-V5)

![SiliconBase V5 Main Interface](docs/images/home.png)

SiliconBase V5 is not yet another LLM toolchain. It is a **digital-life framework** that can continuously perceive its environment, manage long-term memory, and act proactively when needed.

Mainstream AI Agent frameworks today (LangChain, AutoGPT, CrewAI, etc.) are essentially tool orchestration layers wrapped around large models. SiliconBase V5 takes a different path: **redesigning the AI runtime environment from the operating-system layer up**.

> This repository is a **complete, runnable source implementation**, including frontend and backend source code, core modules (`core/`), Rust hard-shell extensions (`rust_core/`), and deployment scripts. MIT licensed — free to study, modify, and build upon.

---

## 🧠 Why "Sovereignty Architecture"?

Today's AI Agents have a common flaw: **they make the LLM decide everything**.

The LLM calls tools, the LLM manages memory, the LLM makes decisions. It sounds smart, but it has three hard problems:

1. **LLMs can't remember that much** — context windows are limited; you can't fit complete memory and system state into every prompt.
2. **LLMs are expensive and slow** — Calling a large model for every button press is too much latency and cost.
3. **LLMs have no continuity** — Every conversation feels like the first time; yesterday's experience is reset today.

SiliconBase V5's solution is simple: **let the system itself be in charge, and treat the LLM as just one of the tools it can call**.

- **Consciousness Thread** is the persistent background arbiter: it maintains self-state, performs L1-level input routing, and schedules intrinsic motivations when autonomous mode is enabled.
- **Memory System** is independent of the LLM, with its own storage, retrieval, value evaluation, and promotion mechanisms.
- **Visual Perception System** first scans with rules, and only calls the large model when it encounters something unfamiliar.

### Four-Layer Sovereignty Architecture

| Layer | Responsibility | Analogy |
|---|---|---|
| **L1 Sovereignty Layer** | Initial routing and arbitration of inputs; maintains self-state; participates in motivation scheduling when autonomous mode is on | Prefrontal cortex |
| **L2 Translation Layer** | Compresses human natural language into structured machine-readable intent | Translator |
| **L3 Execution Layer** | Runs the main Agent loop, calls tools, and returns results | Hands and feet |
| **L4 Memory Layer** | Records "who am I, where am I, what have I experienced", and influences the next decision | Autobiographical memory |

This architecture gives the system **true continuity**: it remembers what you taught it yesterday, remembers its own past mistakes, and even adjusts its behavior based on those memories.

### Consciousness Thread Status: Pipeline Connected, Autonomy Controllable

`Consciousness._loop()` is the system's background heartbeat. It has fully connected the closed loop of **"perceive → update state → arbitrate input → execute → feed result back → update narrative"**:

- Each cycle actively pulls perception data such as vision, windows, and processes.
- Routes inputs through `receive_user_input()` at the L1 level.
- Receives execution results through `receive_action_result()` and updates the self-narrative.
- Integrates UKF state estimator, intrinsic motivation, inner monologue, experience bus, and other components.

**Current limitation**: Observer mode is enabled by default (`observer_mode=True`), proactive proposals are off by default (`observer_can_propose=False`), and self-drive is off by default (`self_drive=False`). Therefore, the consciousness thread currently runs mainly as a **background state maintainer and input arbiter**, with minimal proactive intervention in user tasks. This is intentional — stability first, then gradually expand autonomy.

Full details in [`docs/CONSCIOUSNESS_EN.md`](docs/CONSCIOUSNESS_EN.md).

---

## 🧩 Why Split Memory into Five Tiers?

If you only have "short-term memory" and "long-term memory", many scenarios get stuck:

- **Yesterday's experience** is still needed today, but has passed the short-term memory window.
- **Why a particular tool call succeeded or failed** must be recorded separately and not mixed with chat content.

So SiliconBase V5 splits memory into five tiers:

| Tier | Name | Purpose | Analogy |
|---|---|---|---|
| **L1** | Working Memory | Context of the current session | Attention |
| **L2** | Short-Term Memory | Raw records expiring within 1 day | What happened today |
| **L3** | Mid-Term Memory | High-value experiences expiring within 7 days | What I learned this week |
| **L4** | Long-Term Memory | Permanent evolutionary knowledge | Life experience |
| **L5** | Execution Memory | Complete record of every tool call | Muscle memory |

This system **automatically decides what is worth remembering and what should be forgotten**:

- Unified entry point `MemoryManager`: user input, AI replies, and tool execution automatically trigger memory storage.
- ChromaDB-based vector semantic retrieval can find historical experiences with similar meaning but different wording.
- Automatically evaluates memory value: low-value entries expire and are eliminated; high-value ones are promoted to longer-term tiers.
- 50MB total cap per user to prevent unbounded memory growth.

---

## 👁️ Visual Perception: It Learns What It Doesn't Recognize

Traditional desktop AI relies on fixed models to recognize UI, which breaks when the software version or operating system changes.

SiliconBase V5's visual system follows a **"discover → understand → remember → get faster with use"** closed loop:

1. **Discover**: Uses Canny edge detection + contour extraction + morphological filtering to first find regions that "look like something". This step is **purely rule-based and does not call AI**, so it is fast.
2. **Fuse**: Combines results from four sources — ONNX generic object detection, EasyOCR text recognition, UIAutomation control detection, and contour extraction.
3. **Learn**: When encountering unknown elements, automatically crops sub-images and calls a large vision model (such as qwen3-vl:8b) to label them.
4. **Remember**: Labels and features are stored in the vector memory library.
5. **Reuse**: Next time a similar element is seen, it is instantly recognized through four-layer recall: perceptual hash / md5 / LabelCache / vector similarity.

In short: **the more it uses your computer, the more familiar it becomes with your software**.

> ⚠️ Unknown-element learning is disabled by default. Enabling it will call the large vision model (about 20-30 seconds per call); please enable only after confirming the model is available.

---

## 📈 AI-Driven Cryptocurrency Trading Subsystem

SiliconBase V5 includes a complete AI trading framework:

![AI Trading Commander Report](docs/images/trading.png)

- **Executor Abstraction**: Abstract base class `TradeExecutor`, with `SimulationExecutor`, live OKX `OKXExecutor`, and `BinanceExecutor` underneath.
- **AI Trading Sub-Agent**: `TradingSubAgent` runs an async decision loop and decides when to buy and sell.
- **MCP Commander**: `AITradingCommander` is responsible for strategy analysis and task distribution.
- **Real-Time Market Push**: Independent WebSocket on port 8602 pushes prices, positions, signals, and risks to the frontend in real time.
- **OKX Async Client**: `aiohttp` + HMAC signature, with a 5-second cache.

> ⚠️ Currently, OKX live trading close-position, position, account, and balance interfaces are still TODO; the Binance executor is also just a skeleton. It is recommended to experience it with the simulation account first.

---

## 🛠️ Tool System: AI Uses Tools Like Looking Up a Dictionary

A common problem with Agents today: every round of conversation stuffs the parameters of dozens of tools into the prompt. The result is expensive tokens, confused AI, and made-up tool names.

SiliconBase V5 makes the tool manual into a **three-level progressive structure**:

- **L1 Overview Layer**: First see what tool categories exist (input, window, file, system, screen recognition, etc.)
- **L2 Tool Manual Layer**: Then choose which tools are under a category.
- **L3 Tool Detail Layer**: Finally see the parameters, required fields, and examples for a specific tool.

When the AI is uncertain, it can call `get_tool_manual` to look up the manual instead of guessing. The system prompt only injects the **category list + top 3 high-frequency tools per category + a shortlist of 16 common tools** by default, instead of stuffing 100+ tools in at once.

Additional designs to make the AI "make fewer mistakes":

- **Alias Mapping**: Say "截图" (screenshot) and the system maps it to `pixel_capture`; say "打开微信" (open WeChat) and it maps to `launch_app`.
- **Semantic Search**: Finds the most relevant tools based on natural language intent.
- **Gamified Classification**: Tools have levels, rarity, and experience points, laying the data structure for "user level unlocks advanced tools".
- **116 tools loaded at runtime** (including BTC trading tools), with approximately 91 core non-BTC tools.

Full details in [`docs/TOOLS_EN.md`](docs/TOOLS_EN.md).

---

## 🖥️ Desktop Control: Open Software by Saying Its Chinese Name

A lot of work over the past six months has gone into "making AI stably operate the Windows desktop". It's not just a simple `pyautogui` call, but a complete engineering system with **intelligent path lookup, permission verification, process isolation, timeout governance, and safety confirmation**.

### Finding Apps: 8-Level Lookup Chain

When you say "打开微信" (open WeChat), the system searches in this order:

1. Memory paths you taught it before.
2. Vector semantic search of historical records.
3. Windows Registry App Paths.
4. PATH environment variable.
5. Preset common paths.
6. Global View full-disk index.
7. Desktop shortcuts (limited to the first 50 to prevent hanging).
8. Start Menu shortcuts (limited to the first 30).

Most common software is found in milliseconds.

### Specific Problems Solved

- **Anti-misdelete/misinstall**: Automatically identifies and blocks `uninst.exe`, `setup.exe`, and other uninstaller/installer programs.
- **Stable launch of Chinese paths**: Compatible with UTF-8/GBK, normalizes paths, and handles spaces and special characters.
- **Async without blocking**: win32api, OCR, and other blocking calls are bridged through a thread pool so they don't block the AgentLoop.
- **Timeouts really kill**: Tools run in independent processes and are forcibly terminated on timeout, preventing the whole system from crashing.
- **Anti-blue-screen/handle leak**: Screenshots are serialized through `ResourceCoordinator` and GDI resources are released immediately after use.
- **Chinese input without pinyin**: Uses clipboard paste + failure recovery to stably input Chinese.
- **Session permission check**: Before mouse clicks, checks whether the target window belongs to the current user session to prevent cross-session misoperation.
- **High-risk action confirmation**: Process termination, mouse clicks, keyboard input, file deletion, etc. default to popup confirmation; background/non-interactive environments default to rejection.

---

## 🔧 Other Notable Engineering Details

- **Fully Async AgentLoop**: Phase 8 completed single-core async unification; all high-frequency paths are native `async/await`.
- **Rust / PyO3 Hard Shell Layer**: Core protocols, event bus, and conditional evaluation are implemented in Rust; Python handles flexible iteration.
- **Config and Prompt Hot Reload**: Changes to `roles.yaml` take effect automatically without restarting the service.
- **Background Task Unified Governance**: `BackgroundTaskRegistry` manages lifecycle to prevent wild task leaks.
- **Token Budget Management**: Controls AI call costs with intelligent truncation.

---

## 📸 UI Preview

| Login Page | Main Interface | Trading Report |
|---|---|---|
| ![Login Page](docs/images/login.png) | ![Main Interface](docs/images/home.png) | ![Trading Report](docs/images/trading.png) |

---

## 🚧 Project Status

This is a **personal research open-source project**. The code can run directly, but is still being refined.

- Some features are still being improved (see "Known Limitations" below).
- Not recommended for direct production use.
- Forks for study, experimentation, and PRs are welcome.

## 📦 Source Code Overview

```text
SiliconBase_V5/
├── SiliconBase_V5/          # Backend source code (Python / FastAPI)
│   ├── api/                 # HTTP API and WebSocket entrypoints
│   ├── core/                # Core module source code
│   │   ├── agent/           # AgentLoop main loop
│   │   ├── consciousness/   # Consciousness thread and four-layer architecture
│   │   ├── memory/          # L1-L5 memory system
│   │   ├── tool/            # Tool manager
│   │   ├── vision/          # Visual perception
│   │   └── btc_integration/ # AI trading subsystem
│   ├── frontend/            # Frontend source code (React / TypeScript / Vite)
│   ├── rust_core/           # Rust / PyO3 hard-shell extension source code
│   └── scripts/             # Initialization and deployment scripts
├── docs/                    # Architecture and design documents
├── README.md                # This file (Chinese)
├── README_EN.md             # This file (English)
└── LICENSE                  # MIT License
```

**Code Statistics**: Approximately 150,000 lines of source code, mainly Python (backend) + TypeScript (frontend), with a small amount of Rust (core extensions).

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- PostgreSQL 14+
- ChromaDB (optional, for vector memory)

### Windows One-Click Start

```bash
# Quick start (MCP disabled, starts within 10 seconds)
Double-click: 一键部署启动.bat

# Full start (all features enabled)
Double-click: 启动V5-标准版.bat
```

### Command-Line Start

```bash
# Backend
cd SiliconBase_V5
.venv\Scripts\python.exe api\run.py --host 0.0.0.0 --port 8600

# Frontend
cd SiliconBase_V5\frontend
npm run dev
```

---

## 🌐 Access Addresses

| Service | Address | Description |
|---|---|---|
| Frontend | http://localhost:5173 | Web interface |
| API Docs | http://localhost:8600/docs | Swagger docs |
| Health Check | http://localhost:8600/api/health | Service status |
| Main WebSocket | ws://localhost:8600/ws/{user_id} | Real-time chat and tasks |
| Trading WebSocket | ws://localhost:8602/ws/trading/{symbol} | Real-time market/signals |

### Default Login

On first startup, the system generates a random `admin` initial password and saves it to `SiliconBase_V5/data/.initial_password.txt`, and requires the password to be changed after the first login.

---

## 🛡️ Security Notes

- `.env`, database passwords, API keys, and other sensitive information are excluded via `.gitignore` and will not be committed to GitHub.
- Please do not commit `data/.initial_password.txt` to version control.
- Live trading interfaces are still being improved; the simulation account is used by default.

---

## 📁 Project Structure

```text
SiliconBase_V5/
│
├── SiliconBase_V5/          # Main backend code
│   ├── api/                 # FastAPI routes and startup entry
│   ├── core/                # Core modules
│   │   ├── agent/           # Agent main loop
│   │   ├── consciousness/   # Consciousness thread, self-state, narrative
│   │   ├── memory/          # Memory system
│   │   ├── tool/            # Tool management
│   │   ├── vision/          # Visual perception
│   │   ├── btc_integration/ # Cryptocurrency trading
│   │   └── ...
│   ├── frontend/            # React + TypeScript frontend
│   ├── config/              # Configuration files
│   └── rust_core/           # Rust / PyO3 hard-shell layer
│
├── docs/                    # Project documentation
├── data/                    # Runtime data (gitignored)
├── logs/                    # Log directory (gitignored)
└── outputs/                 # Output directory (gitignored)
```

---

## 🛠️ Development

### Tech Stack

- **Backend**: Python 3.11+, FastAPI, Uvicorn, asyncpg
- **Frontend**: React 18, TypeScript, Vite, Tailwind CSS
- **Database**: PostgreSQL, ChromaDB
- **AI Backends**: OpenAI, Anthropic, DeepSeek, Ollama
- **Voice**: Vosk (recognition), Piper / pyttsx3 (synthesis)
- **Rust Extensions**: maturin

### Install Dependencies

```bash
# Backend
cd SiliconBase_V5
pip install -r requirements.txt

# Frontend
cd SiliconBase_V5\frontend
npm install
```

### Environment Configuration

```bash
# Copy environment variable template
copy .env.example .env

# Edit the .env file
- JWT_SECRET_KEY=your-secret-key
- DATABASE_URL=postgresql://user:pass@localhost/dbname
- OPENAI_API_KEY=sk-...
```

---

## ⚠️ Known Limitations

- **Port 8601 deprecated**: WebSocket is now unified on port 8600.
- **SQLite deprecated**: The memory layer now requires PostgreSQL.
- **Unknown-element learning disabled by default**: Must be enabled manually; enabling it will call the large vision model.
- **OKX live trading interfaces still TODO**: Close position, position, account, and balance are TODO; Binance executor is a basic skeleton.
- **Trading WebSocket K-line is currently synthetic data**: Real K-line integration is still under development.

---

## 📄 License

MIT License - see the [LICENSE](LICENSE) file.

---

**Project Version**: v5.0  
**Maintainer**: SiliconBase Team  
**Contact Email**: xiaoyuzueiqiang@foxmail.com
