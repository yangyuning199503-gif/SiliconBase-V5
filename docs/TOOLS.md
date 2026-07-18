# SiliconBase V5 工具系统设计文档

> 本文档介绍 SiliconBase V5 的工具系统：分层手册、桌面控制、安全设计和扩展机制。  
> 用大白话解释：为什么这样设计，解决了什么问题。

---

## 1. 为什么工具系统要分层？

### 1.1 普通 Agent 的问题

普通 Agent 的做法是：每轮对话，把所有可用工具的参数都塞进 Prompt，让 LLM 自己选。

问题很明显：

- **Token 爆炸**：100 个工具 × 每个工具 100 字描述 = 1 万字上下文
- **AI 看花眼**：工具太多，AI 容易选错或编造不存在的工具
- **重复劳动**：用户只是问个天气，没必要把"文件删除""进程终止"的参数也告诉 AI

### 1.2 SiliconBase V5 的解法：像查字典一样用工具

把工具手册分成三层，AI 按需下钻：

```
L1 概览层：有哪些分类？
   ↓ 说"查看 [分类]"
L2 手册层：这个分类下有哪些工具？
   ↓ 说"查看 [工具ID] 详情"
L3 详情层：这个工具的参数、必填项、示例是什么？
```

就像你查字典：先查部首，再查页码，最后看释义。不需要把整本字典背下来。

---

## 2. 三层手册的真实实现

### 2.1 L1 概览层

**做什么**：告诉 AI 有哪些工具分类。

**关键代码**：

- `tools/tool_manual.py` 中的 `GetToolCategoriesL1`
- `core/tool/tool_categories.py` 中的 12 种标准分类
- `api/tools_api.py` 中的 `/api/tools/tool-manual/l1`

**示例输出**：

```text
可用工具分类：
- 输入控制（鼠标、键盘）
- 窗口管理（查找、聚焦、操作）
- 文件系统（读写、浏览、管理）
- 应用启动（打开、关闭软件）
- 屏幕识别（截图、OCR、视觉理解）
- 系统信息（进程、硬件、环境）
...

说"查看 应用启动 工具"进入 L2。
```

### 2.2 L2 工具手册层

**做什么**：列出某个分类下的所有工具及其一句话说明。

**关键代码**：

- `tools/tool_manual.py` 中的 `GetToolsByCategoryL2`
- `core/tool/tool_manager.py` 中的 `get_tools_by_category_v2()`
- `api/tools_api.py` 中的 `/api/tools/tool-manual/l2`

**示例输出**：

```text
【应用启动】分类下的工具：
- launch_app：按中文名/别名/路径启动应用
- open_and_focus：打开并聚焦到指定窗口
- list_installed_apps：列出已安装应用
...

说"查看 launch_app 详情"进入 L3。
```

### 2.3 L3 工具详情层

**做什么**：给出具体工具的完整参数、必填项、示例、稀有度、图标。

**关键代码**：

- `tools/tool_manual.py` 中的 `GetToolDetailL3`
- `core/tool/tool_manager.py` 中的 `get_tool_detail()`
- `api/tools_api.py` 中的 `/api/tools/tool-manual/l3`

**示例输出**：

```json
{
  "tool_id": "launch_app",
  "name": "启动应用",
  "description": "按名称或路径启动应用，并等待窗口出现",
  "parameters": {
    "app_name": {"type": "string", "required": true, "description": "应用中文名或英文名"},
    "args": {"type": "string", "required": false, "description": "启动参数"}
  },
  "example": {"app_name": "微信"},
  "rarity": "common",
  "unlock_level": 1
}
```

### 2.4 自然语言切换层

AI 和用户都可以用自然语言切换层级：

- "首页" / "home" → 回到 L1
- "手册" / "manual" → 进入 L2
- "返回" / "back" → 回到上一层
- 直接说工具名 → 进入该工具 L3

**关键代码**：

- `core/prompt/prompt_builder.py` 中的 `handle_layer_command()`
- `core/prompt/prompt_templates.py` 中的 `PromptLayer` 枚举

---

## 3. 减少 Token 的其他设计

### 3.1 默认 Prompt 只给"精华版"

系统 Prompt 不会一次性给出 100 多个工具的完整参数，而是：

- 给出**工具分类列表**（十几个分类）
- 每个分类只给**前 3 个高频工具**
- 额外给一个**16 个常用工具短名单**
- 最后告诉 AI："不确定就调用 `get_tool_manual` 查手册"

**关键代码**：

- `core/prompt/smart_prompt_engine.py` 中的 `_build_dynamic_tool_summary()`

### 3.2 长对话自动切换精简模板

当上下文超过 6000 token 时，工具手册模板自动切换为精简版，进一步省 token。

**关键代码**：

- `core/prompt/prompt_templates.py` 中的 `get_layer_template(layer, context_size)`

### 3.3 别名映射：降低 AI 拼错概率

AI 不一定记得住 `pixel_capture` 这种英文 ID。系统内置了别名映射：

```python
TOOL_ALIASES = {
    "截图": "pixel_capture",
    "截屏": "pixel_capture",
    "打开": "launch_app",
    "启动": "launch_app",
    "微信": "launch_app",
    "ocr": "screen_ocr",
    ...
}
```

**关键代码**：

- `core/tool/tool_manager.py` 中的 `TOOL_ALIASES`

---

## 4. 桌面控制工具详解

### 4.1 打开应用：8 级查找链

`launch_app` 不是简单执行一个 exe，而是有一套完整的查找链：

| 优先级 | 来源 | 说明 |
|---|---|---|
| 1 | 记忆路径 | 用户之前教过的路径 |
| 2 | 向量语义搜索 | 在历史记忆中搜"微信 路径" |
| 3 | Windows 注册表 App Paths | 官方安装路径 |
| 4 | PATH 环境变量 | 命令行可直接启动的程序 |
| 5 | 预置常见路径 | 如 `C:\Program Files\Tencent\WeChat\WeChat.exe` |
| 6 | Global View 全盘索引 | 本地软件库索引 |
| 7 | 桌面快捷方式 | 限制前 50 个，防止卡死 |
| 8 | 开始菜单快捷方式 | 限制前 30 个 |

**关键代码**：

- `tools/launch_app.py` 中的查找逻辑

### 4.2 防误启动

AI 如果按名称搜到了卸载程序或安装程序，系统会拒绝执行：

- 拦截 `uninst.exe`、`uninstall.exe`、`setup.exe`、`installer.exe`
- 文件名包含"卸载""删除""install""setup" 也会拦截

**关键代码**：

- `tools/launch_app.py` 中的 `_is_uninstaller()`
- `tools/launch_app_v2.py` 中的启动前校验

### 4.3 异步执行不阻塞

Windows API、OCR、截图等都是同步阻塞调用。如果直接在 `async` 函数里调用，会卡住整个 AgentLoop。

SiliconBase V5 的做法：

- 每个工具提供 `_execute_async()`
- 阻塞操作通过 `loop.run_in_executor()` 或 `asyncio.to_thread()` 扔到线程池
- AgentLoop 继续响应用户其他请求

**关键代码**：

- `core/tool/base_tool.py` 中的 `run_async()`
- 各工具中的 `_execute_async()` 实现

### 4.4 超时与进程隔离

工具执行超过 `timeout` 会被强制终止，不会拖垮系统：

- 普通工具用 `multiprocessing.Process` 隔离
- 超时后先 `terminate()`，再 `kill()`
- 所有活跃进程由 `ProcessPool` 统一管理

**关键代码**：

- `core/tool/tool_manager.py` 中的 `_execute_tool_in_thread()`

### 4.5 截图稳定化

高频截图/并发截图曾导致句柄泄漏甚至蓝屏风险。修复方案：

- `ResourceCoordinator` 串行化截图请求
- 用完立刻释放 MSS 实例和 GDI 句柄
- 安全封装在 `core/vision/safe_screenshot.py`

### 4.6 中文输入

模拟键盘无法直接输入中文。解决方案：

- 对无法直接映射的字符，用剪贴板 `Ctrl+V` 粘贴
- 做 3 次重试
- 失败时恢复原始剪贴板内容

**关键代码**：

- `tools/keyboard_input.py` 中的 `_paste_text()`

### 4.7 会话权限校验

鼠标点击前检查目标窗口是否属于当前用户会话，防止跨会话误操作。

**关键代码**：

- `tools/mouse_click.py` 中的 `_is_same_session()`

---

## 5. 安全确认机制

### 5.1 高危工具默认需要确认

以下工具默认 `require_confirmation = True`：

- `mouse_click`（鼠标点击）
- `keyboard_input`（键盘输入）
- `process_kill`（结束进程）
- `file_manager` 的删除操作

### 5.2 确认流程

1. 检查工具是否标记为需要确认
2. 检查全局配置白名单
3. 弹窗或命令行询问用户
4. 批处理模式 / 非交互终端默认**拒绝**

**关键代码**：

- `core/tool/tool_manager.py` 中的确认逻辑

### 5.3 命令注入防护

- `process_start`、`shell_execute` 禁止 `;&|`、反引号、`$()` 等注入字符
- `core/safety/command_whitelist.py` 统一维护命令白名单

---

## 6. 游戏化分类

每个工具和分类都有游戏化元数据：

| 字段 | 含义 |
|---|---|
| `unlock_level` | 用户需要达到多少级才能解锁 |
| `xp_value` | 使用一次获得多少经验 |
| `rarity` | 稀有度：common / rare / epic / legendary |
| `icon` | 图标 |
| `color` | 分类颜色 |

这为未来"用户等级越高，能用的工具越多"打下了基础。

**关键代码**：

- `core/tool/tool_categories.py` 中的 `CategoryMeta` 和 `ToolInfo`

---

## 7. 工具数量与分类

| 口径 | 数量 |
|---|---|
| 运行时加载的唯一工具 | 116 个 |
| 其中 BTC 交易相关 | 约 25 个 |
| 核心非 BTC 工具 | 约 91 个 |
| 8 大功能分类覆盖 | 76 个 |
| 未进入 8 大分类的（BTC、组合工具等） | 约 40 个 |

> 注：之前 README 中若提到"84 个工具"已不准确，建议以"运行时 116 个唯一工具（含 BTC）"或"核心 91 个工具"为准。

---

## 8. 扩展机制

### 8.1 云工具市场

- `core/tool/tool_market_client.py`：本地客户端，浏览/下载/安装/更新
- `api/cloud_tool_repo.py`：云端仓库服务，发布/审核/版本管理
- 支持签名验证和安全扫描

### 8.2 MCP 路由

`core/tool/tool_router.py` 统一调度原生工具和 MCP 工具，未来可接入标准 MCP 生态。

---

## 9. 总结

SiliconBase V5 的工具系统不是简单的"给 AI 一堆工具让他自己选"，而是：

> **把工具做成一本有目录、有索引、有安全机制的字典，让 AI 按需查阅，而不是一次性背诵。**

同时，桌面控制工具解决了大量真实工程问题：中文路径、异步不卡死、超时治理、权限校验、高危确认。这些才是这半年真正沉淀下来的价值。

---

## 10. 关键文件索引

| 文件 | 说明 |
|---|---|
| `SiliconBase_V5/core/tool/tool_manager.py` | 工具管理器核心 |
| `SiliconBase_V5/core/tool/base_tool.py` | 工具基类 |
| `SiliconBase_V5/core/tool/tool_categories.py` | 分类与游戏化元数据 |
| `SiliconBase_V5/tools/tool_manual.py` | L1/L2/L3 手册工具 |
| `SiliconBase_V5/tools/launch_app.py` | 启动应用 |
| `SiliconBase_V5/tools/mouse_click.py` | 鼠标点击 |
| `SiliconBase_V5/tools/keyboard_input.py` | 键盘输入 |
| `SiliconBase_V5/core/prompt/smart_prompt_engine.py` | 动态工具摘要 |
| `SiliconBase_V5/core/prompt/prompt_templates.py` | 分层 Prompt 模板 |
| `SiliconBase_V5/core/vision/safe_screenshot.py` | 安全截图封装 |
| `SiliconBase_V5/core/safety/command_whitelist.py` | 命令白名单 |
| `SiliconBase_V5/api/tools_api.py` | 工具手册 HTTP API |
| `SiliconBase_V5/api/cloud_tool_repo.py` | 云端工具仓库 |
| `SiliconBase_V5/core/tool/tool_market_client.py` | 本地工具市场客户端 |
| `SiliconBase_V5/core/tool/tool_router.py` | MCP 工具路由 |

---

**最后更新时间**: 2026-07-18  
**维护者**: SiliconBase Team  
**联系邮箱**: xiaoyuzueiqiang@foxmail.com