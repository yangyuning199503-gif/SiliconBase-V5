# SiliconBase V5 Tool System Design Document

> This document introduces the SiliconBase V5 tool system: layered manual, desktop control, safety design, and extension mechanisms.  
> Explained in plain language: why it is designed this way and what problems it solves.

---

## 1. Why Does the Tool System Need Layers?

### 1.1 The Problem with Ordinary Agents

The ordinary Agent approach is: every round of conversation, stuff the parameters of all available tools into the prompt and let the LLM choose.

The problems are obvious:

- **Token explosion**: 100 tools × 100 characters of description per tool = 10,000 characters of context.
- **AI gets confused**: Too many tools; the AI is prone to choosing wrong or making up non-existent tools.
- **Redundant work**: If the user just asks about the weather, there is no need to tell the AI the parameters for "file deletion" or "process termination".

### 1.2 SiliconBase V5's Solution: Use Tools Like Looking Up a Dictionary

The tool manual is divided into three layers, and the AI drills down as needed:

```
L1 Overview Layer: What categories exist?
   ↓ Say "view [category]"
L2 Manual Layer: What tools are under this category?
   ↓ Say "view details of [toolID]"
L3 Detail Layer: What are the parameters, required fields, and examples of this tool?
```

Just like looking up a dictionary: first find the radical, then the page number, then the definition. There is no need to memorize the whole dictionary.

---

## 2. Real Implementation of the Three-Layer Manual

### 2.1 L1 Overview Layer

**What it does**: Tells the AI what tool categories exist.

**Key code**:

- `GetToolCategoriesL1` in `tools/tool_manual.py`
- 12 standard categories in `core/tool/tool_categories.py`
- `/api/tools/tool-manual/l1` in `api/tools_api.py`

**Example output**:

```text
Available tool categories:
- Input Control (mouse, keyboard)
- Window Management (find, focus, operate)
- File System (read/write, browse, manage)
- App Launch (open/close software)
- Screen Recognition (screenshot, OCR, visual understanding)
- System Info (process, hardware, environment)
...

Say "view App Launch tools" to enter L2.
```

### 2.2 L2 Tool Manual Layer

**What it does**: Lists all tools under a category and a one-sentence description of each.

**Key code**:

- `GetToolsByCategoryL2` in `tools/tool_manual.py`
- `get_tools_by_category_v2()` in `core/tool/tool_manager.py`
- `/api/tools/tool-manual/l2` in `api/tools_api.py`

**Example output**:

```text
Tools under [App Launch]:
- launch_app: Launch app by Chinese name/alias/path
- open_and_focus: Open and focus a specified window
- list_installed_apps: List installed applications
...

Say "view launch_app details" to enter L3.
```

### 2.3 L3 Tool Detail Layer

**What it does**: Gives the complete parameters, required fields, examples, rarity, and icon for a specific tool.

**Key code**:

- `GetToolDetailL3` in `tools/tool_manual.py`
- `get_tool_detail()` in `core/tool/tool_manager.py`
- `/api/tools/tool-manual/l3` in `api/tools_api.py`

**Example output**:

```json
{
  "tool_id": "launch_app",
  "name": "Launch Application",
  "description": "Launch an application by name or path, and wait for the window to appear",
  "parameters": {
    "app_name": {"type": "string", "required": true, "description": "Application Chinese name or English name"},
    "args": {"type": "string", "required": false, "description": "Launch arguments"}
  },
  "example": {"app_name": "WeChat"},
  "rarity": "common",
  "unlock_level": 1
}
```

### 2.4 Natural Language Layer Switching

Both the AI and the user can switch layers using natural language:

- "首页" / "home" → back to L1
- "手册" / "manual" → enter L2
- "返回" / "back" → back to the previous layer
- Directly say the tool name → enter L3 for that tool

**Key code**:

- `handle_layer_command()` in `core/prompt/prompt_builder.py`
- `PromptLayer` enum in `core/prompt/prompt_templates.py`

---

## 3. Other Designs to Reduce Tokens

### 3.1 Default Prompt Only Gives the "Essentials"

The system prompt does not dump the full parameters of 100+ tools at once. Instead:

- Gives the **tool category list** (about a dozen categories)
- Gives only the **top 3 high-frequency tools** per category
- Additionally gives a **shortlist of 16 common tools**
- Finally tells the AI: "If unsure, call `get_tool_manual` to look it up"

**Key code**:

- `_build_dynamic_tool_summary()` in `core/prompt/smart_prompt_engine.py`

### 3.2 Long Conversations Auto-Switch to Concise Templates

When context exceeds 6000 tokens, the tool manual template automatically switches to a concise version to further save tokens.

**Key code**:

- `get_layer_template(layer, context_size)` in `core/prompt/prompt_templates.py`

### 3.3 Alias Mapping: Reducing AI Spelling Errors

The AI may not remember English IDs like `pixel_capture`. The system has built-in alias mapping:

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

**Key code**:

- `TOOL_ALIASES` in `core/tool/tool_manager.py`

---

## 4. Desktop Control Tools in Detail

### 4.1 Opening Apps: 8-Level Lookup Chain

`launch_app` is not simply executing an exe; it has a complete lookup chain:

| Priority | Source | Description |
|---|---|---|
| 1 | Memory path | Path previously taught by the user |
| 2 | Vector semantic search | Search history memory for "WeChat path" |
| 3 | Windows Registry App Paths | Official installation path |
| 4 | PATH environment variable | Programs directly launchable from command line |
| 5 | Preset common paths | e.g. `C:\Program Files\Tencent\WeChat\WeChat.exe` |
| 6 | Global View full-disk index | Local software library index |
| 7 | Desktop shortcuts | Limited to first 50 to prevent hanging |
| 8 | Start Menu shortcuts | Limited to first 30 |

**Key code**:

- Lookup logic in `tools/launch_app.py`

### 4.2 Anti-Mislaunch

If the AI finds an uninstaller or installer by name, the system refuses to execute:

- Blocks `uninst.exe`, `uninstall.exe`, `setup.exe`, `installer.exe`
- Filenames containing "卸载", "删除", "install", or "setup" are also blocked

**Key code**:

- `_is_uninstaller()` in `tools/launch_app.py`
- Pre-launch validation in `tools/launch_app_v2.py`

### 4.3 Async Execution Without Blocking

Windows API, OCR, screenshots, etc. are synchronous blocking calls. If called directly inside an `async` function, the entire AgentLoop would freeze.

SiliconBase V5's approach:

- Each tool provides `_execute_async()`
- Blocking operations are thrown to a thread pool via `loop.run_in_executor()` or `asyncio.to_thread()`
- AgentLoop continues responding to other user requests

**Key code**:

- `run_async()` in `core/tool/base_tool.py`
- `_execute_async()` implementations in each tool

### 4.4 Timeout and Process Isolation

Tool execution that exceeds `timeout` is forcibly terminated and will not crash the system:

- Ordinary tools are isolated using `multiprocessing.Process`
- After timeout, `terminate()` is called first, then `kill()`
- All active processes are uniformly managed by `ProcessPool`

**Key code**:

- `_execute_tool_in_thread()` in `core/tool/tool_manager.py`

### 4.5 Screenshot Stabilization

High-frequency/concurrent screenshots once caused handle leaks and even blue-screen risks. The fix:

- `ResourceCoordinator` serializes screenshot requests
- MSS instances and GDI handles are released immediately after use
- Safety wrapper in `core/vision/safe_screenshot.py`

### 4.6 Chinese Input

Simulated keyboards cannot directly input Chinese. The solution:

- For characters that cannot be directly mapped, use clipboard `Ctrl+V` paste
- 3 retries
- Restore original clipboard content on failure

**Key code**:

- `_paste_text()` in `tools/keyboard_input.py`

### 4.7 Session Permission Check

Before mouse clicks, check whether the target window belongs to the current user session to prevent cross-session misoperation.

**Key code**:

- `_is_same_session()` in `tools/mouse_click.py`

---

## 5. Safety Confirmation Mechanism

### 5.1 High-Risk Tools Require Confirmation by Default

The following tools have `require_confirmation = True` by default:

- `mouse_click` (mouse click)
- `keyboard_input` (keyboard input)
- `process_kill` (kill process)
- Delete operations in `file_manager`

### 5.2 Confirmation Flow

1. Check whether the tool is marked as requiring confirmation
2. Check the global configuration whitelist
3. Pop up a dialog or ask via command line
4. Batch mode / non-interactive terminal defaults to **reject**

**Key code**:

- Confirmation logic in `core/tool/tool_manager.py`

### 5.3 Command Injection Protection

- `process_start`, `shell_execute` forbid injection characters such as `;&|`, backticks, `$()`
- `core/safety/command_whitelist.py` uniformly maintains the command whitelist

---

## 6. Gamified Classification

Each tool and category has gamified metadata:

| Field | Meaning |
|---|---|
| `unlock_level` | User level required to unlock |
| `xp_value` | Experience gained per use |
| `rarity` | Rarity: common / rare / epic / legendary |
| `icon` | Icon |
| `color` | Category color |

This lays the foundation for the future "the higher the user level, the more tools are available".

**Key code**:

- `CategoryMeta` and `ToolInfo` in `core/tool/tool_categories.py`

---

## 7. Tool Count and Categories

| Metric | Count |
|---|---|
| Unique tools loaded at runtime | 116 |
| BTC trading related | ~25 |
| Core non-BTC tools | ~91 |
| Covered by 8 major functional categories | 76 |
| Not in the 8 major categories (BTC, combo tools, etc.) | ~40 |

> Note: If the README previously mentioned "84 tools", that is no longer accurate. It is recommended to use "116 unique tools loaded at runtime (including BTC)" or "91 core tools".

---

## 8. Extension Mechanisms

### 8.1 Cloud Tool Marketplace

- `core/tool/tool_market_client.py`: Local client for browsing/downloading/installing/updating
- `api/cloud_tool_repo.py`: Cloud repository service for publishing/reviewing/version management
- Supports signature verification and security scanning

### 8.2 MCP Routing

`core/tool/tool_router.py` uniformly dispatches native tools and MCP tools, and can connect to the standard MCP ecosystem in the future.

---

## 9. Summary

The SiliconBase V5 tool system is not simply "give the AI a bunch of tools and let it choose". Instead:

> **It makes tools into a dictionary with a table of contents, an index, and safety mechanisms, so the AI looks up what it needs instead of memorizing everything at once.**

At the same time, the desktop control tools solve a large number of real engineering problems: Chinese paths, async without blocking, timeout governance, permission checks, and high-risk confirmation. These are the real value accumulated over the past six months.

---

## 10. Key File Index

| File | Description |
|---|---|
| `SiliconBase_V5/core/tool/tool_manager.py` | Core tool manager |
| `SiliconBase_V5/core/tool/base_tool.py` | Tool base class |
| `SiliconBase_V5/core/tool/tool_categories.py` | Categories and gamified metadata |
| `SiliconBase_V5/tools/tool_manual.py` | L1/L2/L3 manual tools |
| `SiliconBase_V5/tools/launch_app.py` | Launch application |
| `SiliconBase_V5/tools/mouse_click.py` | Mouse click |
| `SiliconBase_V5/tools/keyboard_input.py` | Keyboard input |
| `SiliconBase_V5/core/prompt/smart_prompt_engine.py` | Dynamic tool summary |
| `SiliconBase_V5/core/prompt/prompt_templates.py` | Layered prompt templates |
| `SiliconBase_V5/core/vision/safe_screenshot.py` | Safe screenshot wrapper |
| `SiliconBase_V5/core/safety/command_whitelist.py` | Command whitelist |
| `SiliconBase_V5/api/tools_api.py` | Tool manual HTTP API |
| `SiliconBase_V5/api/cloud_tool_repo.py` | Cloud tool repository |
| `SiliconBase_V5/core/tool/tool_market_client.py` | Local tool marketplace client |
| `SiliconBase_V5/core/tool/tool_router.py` | MCP tool routing |

---

**Last Updated**: 2026-07-18  
**Maintainer**: SiliconBase Team  
**Contact Email**: xiaoyuzueiqiang@foxmail.com
