# SiliconBase V5 — Agent 协作指南

## 项目基本信息

- **语言**: Python 3.10.19
- **虚拟环境**: `E:\SiliconBase_V5\SiliconBase_V5\.venv\Scripts\python.exe`
- **操作系统**: Windows
- **测试框架**: pytest (`pytest-9.0.2`)
- **工作目录**: `E:\SiliconBase_V5\SiliconBase_V5`

## 架构状态（2026-04-19）

当前处于 **Phase 8 单核异步统一化已完成** → 持续优化的阶段。

### 单核异步统一化（Phase 8 已完成）
- **同步版** `_run_agent_loop_impl`: **已删除**（2026-04-19，原 ~2811 行）
- **异步版** `_run_agent_loop_async_impl`: L823-L3361，约 2600 行，**唯一生产入口**
- **`run_agent_loop()`**: 薄包装（~67 行），内部 `asyncio.run(run_agent_loop_async(...))`
- **生产入口** `start_unified.py:187` 已切换为 `run_agent_loop_async()`

### 已完成 async 化模块
| 模块 | 状态 |
|------|------|
| BaseTool 基类 (`run_async` / `_execute_async`) | ✅ 契约已建立，重复定义已清理 |
| Provider 层 (`chat_async`) | ✅ OpenAI/Anthropic 原生异步；Ollama/Custom 桥接 |
| 高频工具 (`_execute_async`) | ✅ visual_understand 真异步；其余显式桥接 |
| ToolHook/VisionHook/VoiceHook/SafetyHook | ✅ 全部注册运行 |
| AsyncMemory (`asyncpg`) | ✅ 原生 async 接口 |
| ContextAssembler | ✅ 同步/异步双入口 |
| intent_handler | ✅ `handle_tool_call_async` |

## 已知环境限制

- **虚拟环境**: 旧 `.venv` 曾指向不存在的 `C:\Users\Administrator\...`，已重建为当前项目级 `.venv`。
- **核心依赖**: `fastapi`, `uvicorn`, `pydantic`, `tiktoken`, `bcrypt`, `python-jose` 等已可导入。
- **PostgreSQL**: `core.config` 已在模块顶部加载项目根目录 `.env`（`override=False`），因此即使直接 `import core.config` 也能读取 `POSTGRES_PASSWORD` / `SILICONBASE_PG_PASSWORD`。
- **可选依赖策略（2026-06-25）**: 不强制安装 `torch` / `cv2` / `pandas` / `bs4` / `pyaudio` 等重型包。所有核心启动路径已改为 try/except 延迟导入或局部导入；缺失时模块仍可导入，相关功能在调用时返回降级/不可用提示。
- **开发依赖**: `ruff`, `pyright`, `mypy`, `pytest`, `pytest-asyncio`, `pytest-cov`, `maturin` 已加入 `requirements-dev.txt`。
- **Rust 硬壳层**: `rust_core/` 已初始化，Windows + MSVC 可正常 `maturin build --release`。
  - `siliconbase_core.evaluate_condition_py()`：已替代 `core/workflow/condition_evaluator_enhanced.py` 中的 `eval()`。
  - `siliconbase_core` protocol 工厂/校验：已在 Rust 实现，`core/protocol.py` 优先调用 Rust 实现并在失败时回退 Python。
  - `siliconbase_core.EventBus`：已在 Rust 实现并暴露为 `EventBus`（subscribe/publish/wildcard/stats），Python 侧回调仍由 Python 处理；`core/sync/event_bus.py` 暂未默认切换，避免影响 43 个依赖文件的异步/过滤器行为。
  - 类型存根：`typings/siliconbase_core.pyi` 已新增，`pyproject.toml` 已配置 `stubPath = "typings"`。

## 全项目清理基线（2026-06-25）

- **ruff**: 全项目 ruff 已清零（`ruff check .` 0 errors）。本轮人工修复了 core/api/tools/sensors/tests 中剩余的 SIM102/SIM103/SIM105/SIM108/SIM117/E701/E741/B023/B025/B030 等债务，并修正了 `core/tool/tool_manager.py` 中 `event_bus.unsubscribe` 的错误调用签名。`pyproject.toml` 的 `per-file-ignores` 仅保留对 `api/**` 的 FastAPI 依赖注入默认参数（B008）、`core/agent/agent_loop.py` 和 `api/cloud_api.py` 的延迟导入（E402）、以及测试目录遗留 API 调用（E402/F821）的抑制；对 `cloud/adapters.py`（B024）、`scripts/service_manager.py` 与部分测试（SIM115）、测试用 `lru_cache`（B019）等场景补加了必要的 `# noqa` 注释。
- **pyright strict 模块**: `core/config.py` 已通过 ruff 全量检查；其余 5 个 strict 模块仍为清理目标。
- **可选依赖延迟化**:
  - `core/consciousness/action_preference_model.py`
  - `core/world_model/world_model.py`
  - `tools/template_match.py`
  - `tools/web_parse.py`
  - `core/btc_integration/tools/new_strategy_tools.py`
  - `core/btc_integration/engine/tools/okx_demo_autopilot.py`
- **语法错误修复**: `core/vision/safe_screenshot.py` 文件头被批量脚本破坏的 stray `"` 已移除。
- **悬空文件**: 静态分析识别出 751 个无静态导入的候选文件（含脚本、示例、测试、临时文件）。详见 `docs/reports/orphan_candidates.txt` 与 `docs/reports/core_orphans_investigation.md`。**未自动删除任何生产文件**；core/ 下 269 个候选模块排除 `core/btc_integration/engine/*` 独立脚本（219 个）后，剩余 50 个待复核。
  - 已归档 2 个明显悬空的历史文件：`core/agent/phases/intent_phase.py`（占位 phase）、`core/ai_task_scheduler.py`（已弃用的兼容 stub）→ `archive/core_orphans_2026-06-26/`。

## 编码约定

1. **async/await 规范**
   - 新增工具必须同时提供 `_execute_async`（基类默认抛出 `NotImplementedError`）
   - 无法真正异步化的阻塞操作（截图、OCR、UI 自动化）使用 `run_in_executor` 桥接，禁止用 `asyncio.to_thread`（统一风格）
   - Provider 的 `chat_async` 优先使用原生异步 HTTP 客户端（`AsyncOpenAI`, `AsyncAnthropic`），次选 `asyncio.to_thread` 桥接

2. **向后兼容**
   - 同步 `chat()` / `_execute()` / `run()` 方法**绝对不能删除或改变签名**
   - 同步版 `_run_agent_loop_impl` 在 Phase 8 完成前禁止删除

3. **错误处理**
   - 所有工具返回标准化字典：`{"success": bool, "error_code": str, "user_message": str, "data": Any}`
   - `run_async()` 和 `run()` 均内建完整异常捕获，绝不抛出到调用方

4. **导入路径**
   - 使用绝对导入：`from core.safety.safety_guard import ...`（不要省略 `core.`）
   - 测试文件通过 `sys.path.insert(0, os.path.join(PROJECT_ROOT, 'core'))` 处理路径

## 常用命令

```powershell
# 语法校验（修改任何 .py 后必须执行）
E:\SiliconBase_V5\SiliconBase_V5\.venv\Scripts\python.exe -m py_compile <文件路径>

# 运行测试
E:\SiliconBase_V5\SiliconBase_V5\.venv\Scripts\python.exe -m pytest tests/test_xxx.py -v --tb=short

# 全量测试（可能因缺失 PostgreSQL 而部分失败）
E:\SiliconBase_V5\SiliconBase_V5\.venv\Scripts\python.exe -m pytest tests/ -v

# Lint（当前历史代码包袱重，先用于增量检查）
E:\SiliconBase_V5\SiliconBase_V5\.venv\Scripts\ruff.exe check <文件路径>

# 类型检查（当前仅对 pyproject.toml strict 列表执行）
cd E:\SiliconBase_V5\SiliconBase_V5 && .venv\Scripts\pyright.exe <文件路径>

# Rust 硬壳层构建
E:\SiliconBase_V5\SiliconBase_V5\.venv\Scripts\maturin.exe develop --release
E:\SiliconBase_V5\SiliconBase_V5\.venv\Scripts\maturin.exe build --release
```

## 安全注意事项

> ✅ **已修复（2026-06-25）**
>
> `config/global.yaml`、`config/local.yaml` 中的 `auth.default_users` 已删除，`config/system.json` 中的 `auth.default_password` 已置空。
> 启动时 `api/cloud_api.py:_load_users_from_config()` 会生成随机 admin 密码并写入 `data/.initial_password.txt`，同时 `require_password_change=True`。
> 请勿把 `data/.initial_password.txt` 提交到版本控制。

## 文档维护纪律

1. 每次对环境、依赖、构建命令、安全状态做改动后，同步更新本文件。
2. 对 `C:\Users\yang\.kimi\plans\aquaman-phil-coulson-hulk.md` 等计划文件，若发现结论偏差，立即在文末追加复核记录，不准只改记忆不改文档。
3. 所有“待验证/可能不准确”的结论必须在对应文档中用 `⚠️ 待验证` 标出。

## 08 文档坐标

核心战略文档：`E:\SiliconBase_V5\资产报告\08-融合重构与缺陷修复执行地图.md`
- Phase 4（底层工具层真异步化）—— 已完成
- Phase 5（记忆层真异步化）—— 已完成（详见 `09-记忆层真异步化实施方案.md`）
- Phase 6（VoiceHook + SafetyHook）—— 已完成
- Phase 7（悬空模块接入）—— 已完成核心路径
- Phase 8（单核异步统一化 / 删除同步版）—— **已完成（2026-04-19）**
