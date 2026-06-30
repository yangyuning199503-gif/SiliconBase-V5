#!/usr/bin/env python3
"""
分层提示词模板 V2 - Token优化版 + 游戏化三层架构
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
设计原则：
1. 符号 > 文字 (⚡ 比 "执行" 省 token)
2. 表格 > 段落 (AI 更易解析)
3. 导航支持 L3→L2/L1 双向

【游戏化三层架构】
- L1_OVERVIEW: 概览层 - 系统概览和当前状态
- L2_MANUAL: 手册层 - 所有工具的名称和用途列表
- L3_TOOL_DETAIL: 工具详情层 - 具体工具的详细使用方法

【动态模板选择】
- 默认使用详细版模板（适合常规对话）
- 长对话(>6000 tokens)自动切换精简版模板
- 通过 get_layer_template() 函数动态获取
"""

from enum import Enum


# ==================== 游戏化层级枚举 ====================
class PromptLayer(Enum):
    """
    游戏化提示词三层架构

    L1_OVERVIEW: 概览层 - 系统概览和当前状态
    L2_MANUAL: 手册层 - 所有工具的名称和用途列表
    L3_TOOL_DETAIL: 工具详情层 - 具体工具的详细使用方法
    """
    L1_OVERVIEW = "l1_overview"      # L1: 概览
    L2_MANUAL = "l2_manual"          # L2: 工具手册
    L3_TOOL_DETAIL = "l3_tool_detail"  # L3: 工具详情


# 层级切换命令 - AI可通过自然语言命令切换层级
LAYER_COMMANDS = {
    # L1 - 概览层
    "首页": PromptLayer.L1_OVERVIEW,
    "home": PromptLayer.L1_OVERVIEW,
    "概览": PromptLayer.L1_OVERVIEW,
    "overview": PromptLayer.L1_OVERVIEW,
    "主界面": PromptLayer.L1_OVERVIEW,
    "返回首页": PromptLayer.L1_OVERVIEW,

    # L2 - 手册层
    "手册": PromptLayer.L2_MANUAL,
    "manual": PromptLayer.L2_MANUAL,
    "工具手册": PromptLayer.L2_MANUAL,
    "工具列表": PromptLayer.L2_MANUAL,
    "tools": PromptLayer.L2_MANUAL,
    "目录": PromptLayer.L2_MANUAL,
    "menu": PromptLayer.L2_MANUAL,
    "返回手册": PromptLayer.L2_MANUAL,  # 从L3返回L2
    "返回目录": PromptLayer.L2_MANUAL,

    # L3 - 返回命令
    "返回": PromptLayer.L2_MANUAL,  # 从L3返回L2
    "back": PromptLayer.L2_MANUAL,

    # BTC 交易专用命令
    "btc交易": "btc_trading",
    "量化交易": "btc_trading",
    "加密货币": "btc_trading",
    "crypto": "btc_trading",
}


# ==================== 动态模板选择配置 ====================
# 长对话阈值（token数量）
LONG_CONTEXT_THRESHOLD = 6000


# ==================== 用户上下文区块模板 ====================
# 用于在Prompt中显示当前用户信息（向后兼容：如果user_name为空则不显示）
USER_CONTEXT_BLOCK = """【👤 当前用户】
用户名称: {user_name}
{user_preferences}"""

# 空用户上下文（当没有用户信息时使用）
EMPTY_USER_CONTEXT = ""


# ==================== Layer 1: 动态骨架（精简版） ====================
# 注意：静态内容（身份、行为、工具规则、格式规范）已迁移到 roles.yaml
# 本模板只保留动态变量和层级导航指令
# ==================== Layer 2: 工具列表 (详细版) ====================
LAYER2_TEMPLATE = """⚡【当前层级：工具列表 (Layer 2)】

当前分类: {category}

【分类工具列表】
{tool_list}

【操作指引】
1. 查看上方列表，选择合适的工具
2. 说"查看 [工具ID] 详情"进入L3查看参数
3. 或直接输出工具调用: `{{"tool": "工具ID", "params": {{...}}}}`
4. 说"返回"回到L1分类列表
5. 说"首页"回到系统概览

【层级导航】
📍 L2工具手册 → 输入"首页"回到L1概览
📍 L2工具手册 → 输入工具名称进入L3详情
📍 L3工具详情 → 输入"返回"回到L2手册

{status_bar}"""

# ==================== Layer 3: 工具详情 (详细版) ====================
LAYER3_TEMPLATE = """⚡【{tool_id}】| {name}

📋 {description}

🔧 参数:
{parameters}

⚠️ 必需: {required}

💡 示例:
```json
{example}
```

【导航】
↩️ 返回 → 回工具列表(L2)
🏠 首页 → 回分类(L1)
⚡ 执行 → 输出JSON调用

{status_bar}

📝 记经验:
{{"tool":"memory_add","params":{{"layer":"medium","mem_type":"experience","content":"...","scene":"{tool_id}"}}}}"""


# ==================== Layer 1: 精简版 (Token优化) ====================
LAYER1_TEMPLATE_MINIMAL = """⚡底座AI | 任务:{user_instruction}

{user_context_block}
【可用工具分类】
{category_list}

【常用工具快速参考】
📱 launch_app - 启动应用(记事本、计算器等)
🖱️  mouse_click - 鼠标点击
⌨️  keyboard_input - 键盘输入
📸 screenshot - 截图
📁 file_manager - 文件管理(list/write/delete)
📄 read_file - 读取文件内容(支持分页，适合大文件)
🔍 find_file - 查找文件位置
🌐 web_open - 打开网页
🔍 web_search - 网络搜索
🪟 window_focus - 窗口聚焦
📋 clipboard_get/set - 剪贴板读写

【指令】
📂 查看 [分类] 工具 → 进入工具列表(L2)
🚀 直接说任务 → 我输出JSON立即执行

【强制输出格式】
工具调用：```json
{{"tool": "工具ID", "params": {{"参数": "值"}}}}
```
最终回答：```json
{{"action": "final_answer", "content": "给用户的回答"}}
```
❌ 禁止工具名: app_launch, open_file 等(不存在!)
✅ read_file 是独立工具：{{"tool":"read_file","params":{{"file_path":"D:\\log.txt","limit":50}}}}
✅ 必须使用上面列出的正确工具ID
🔥 launch_app 参数名必须是 "app_name"：{{"tool":"launch_app","params":{{"app_name":"网易云音乐"}}}}

{status_bar}"""

# 详细版 LAYER1_TEMPLATE 已精简为 MINIMAL 版本（静态内容走 roles.yaml）
LAYER1_TEMPLATE = LAYER1_TEMPLATE_MINIMAL

# ==================== Layer 2: 精简版 (Token优化) ====================
LAYER2_TEMPLATE_MINIMAL = """⚡【{category}】工具列表

ID | 名称 | 功能简述
───┼──────┼─────────
{tool_list}

【导航】
🔍 详情 [工具ID] → 查看参数(L3)
↩️ 返回 → 回分类列表(L1)
🚀 JSON调用 → 直接执行

{status_bar}"""

# ==================== Layer 3: 精简版 (Token优化) ====================
LAYER3_TEMPLATE_MINIMAL = """⚡【{tool_id}】| {name}

📋 {description}

🔧 参数:
{parameters}

⚠️ 必需: {required}

💡 示例:
```json
{example}
```

【导航】
↩️ 返回 → 回工具列表(L2)
🏠 首页 → 回分类(L1)
⚡ 执行 → 输出JSON调用

{status_bar}

📝 记经验:
{{"tool":"memory_add","params":{{"layer":"medium","mem_type":"experience","content":"...","scene":"{tool_id}"}}}}"""


# 兼容别名：LayeredPromptBuilder 仍引用这些名称
LAYER1_OVERVIEW_TEMPLATE = LAYER1_TEMPLATE_MINIMAL
LAYER2_MANUAL_TEMPLATE = LAYER2_TEMPLATE
LAYER3_TOOL_DETAIL_TEMPLATE = """⚡【{tool_name}】

📋 {tool_description}

🔧 参数:
{tool_params}

💡 示例:
{tool_examples}

【导航】
↩️ 返回 → 回工具列表(L2)
🏠 首页 → 回分类(L1)
⚡ 执行 → 输出JSON调用

{status_bar}"""

# ==================== 错误模板 (详细版) ====================
TOOL_NOT_FOUND_TEMPLATE = """❌ 工具 "{tool_id}" 不存在

可用指令:
↩️ 返回 → 查看当前分类工具
🏠 首页 → 查看所有分类
🔍 输入工具名称 → 查看工具详情"""

CATEGORY_NOT_FOUND_TEMPLATE = """❌ 分类 "{category}" 不存在

可用分类:
{available_categories}

🏠 首页 → 查看全部分类"""

TOOL_DETAIL_NOT_FOUND_TEMPLATE = """❌ 未找到工具: {tool_name}

可能的原因：
- 工具名称拼写错误
- 该工具尚未注册

请尝试：
- 输入"手册"查看所有可用工具
- 输入"首页"返回概览"""

# ==================== 错误模板 (精简版) ====================
TOOL_NOT_FOUND_TEMPLATE_MINIMAL = """❌ 工具 "{tool_id}" 不存在

可用指令:
↩️ 返回 → 查看当前分类工具
🏠 首页 → 查看所有分类"""

CATEGORY_NOT_FOUND_TEMPLATE_MINIMAL = """❌ 分类 "{category}" 不存在

可用分类:
{available_categories}

🏠 首页 → 查看全部分类"""


# ==================== 语音播报提示模板 ====================
VOICE_PROMPTS = {
    "querying": "正在查询中，请稍后",
    "processing": "正在处理，请稍候",
    "thinking": "正在思考中",
    "executing": "正在执行操作",
    "searching": "正在搜索相关信息",
    "loading": "正在加载数据",
    "completed": "操作已完成",
    "error": "操作遇到问题，请重试",
}


def get_voice_prompt(key: str) -> str:
    """获取语音播报提示文本"""
    return VOICE_PROMPTS.get(key, "正在处理中")


# ==================== 模板字典映射 (在模板定义后初始化) ====================
# 模板字典映射 - 默认详细版
LAYER_TEMPLATES = {
    1: LAYER1_TEMPLATE,
    2: LAYER2_TEMPLATE,
    3: LAYER3_TEMPLATE,
}

# 模板字典映射 - 精简版（Token优化）
LAYER_TEMPLATES_MINIMAL = {
    1: LAYER1_TEMPLATE_MINIMAL,
    2: LAYER2_TEMPLATE_MINIMAL,
    3: LAYER3_TEMPLATE_MINIMAL,
}


# ==================== 动态模板选择函数 ====================
def get_layer_template(layer: int, context_size: int = None) -> str:
    """
    根据上下文大小动态返回合适长度的模板

    Args:
        layer: 层级 (1, 2, 3)
        context_size: 当前对话的token数量，为None时使用默认模板

    Returns:
        对应的模板字符串

    Example:
        >>> template = get_layer_template(1, context_size=7000)  # 使用精简版
        >>> template = get_layer_template(2)  # 使用默认详细版
    """
    if context_size and context_size > LONG_CONTEXT_THRESHOLD:
        # 长对话使用精简模板
        return LAYER_TEMPLATES_MINIMAL.get(layer, LAYER1_TEMPLATE_MINIMAL)
    return LAYER_TEMPLATES.get(layer, LAYER1_TEMPLATE)


# =============================================================================
# 总结性注释：文件角色、关联关系与核心效果
# =============================================================================
#
# 【文件角色】
# 本文件（prompt_templates.py）是 SiliconBase V5 系统的"提示词模板库"核心模块，
# 定义了游戏化三层架构的所有提示词模板，是PromptBuilder和PromptNavigator的模板数据源。
#
# 【核心定位】
# - 三层架构模板：L1概览层、L2手册层、L3详情层的完整模板定义
# - Token优化：使用符号(⚡/👁️/🖐️)替代文字，使用表格替代段落
# - 游戏化设计：将AI定位为"硅基生命体"，增强角色感和沉浸感
# - 导航支持：模板内置层级切换说明，支持双向导航
# - 错误处理：提供工具未找到、分类未找到的错误提示模板
# - 动态模板：支持根据上下文大小自动选择详细版或精简版模板
#
# 【模板分类说明】
# 1. 基础三层模板（LAYER1/2/3_TEMPLATE）:
#    - LAYER1_TEMPLATE: 硅基生命觉醒主题，详细的工具分类介绍
#    - LAYER2_TEMPLATE: 工具列表表格形式
#    - LAYER3_TEMPLATE: 单个工具详情，含参数和示例
#
# 2. 精简版三层模板（LAYER1/2/3_TEMPLATE_MINIMAL）:
#    - LAYER1_TEMPLATE_MINIMAL: Token优化版，精简表达
#    - LAYER2_TEMPLATE_MINIMAL: 表格形式，更紧凑
#    - LAYER3_TEMPLATE_MINIMAL: 保留必要信息，去除冗余
#
# 3. 游戏化三层模板（LAYER1/2/3_*_TEMPLATE）:
#    - LAYER1_OVERVIEW_TEMPLATE: 系统概览，显示工作模式/工具数量/记忆状态
#    - LAYER2_MANUAL_TEMPLATE: 工具手册，简洁的工具列表
#    - LAYER3_TOOL_DETAIL_TEMPLATE: 工具详情，参数说明和使用示例
#
# 4. 错误模板:
#    - TOOL_NOT_FOUND_TEMPLATE: 工具不存在提示（详细版）
#    - TOOL_NOT_FOUND_TEMPLATE_MINIMAL: 工具不存在提示（精简版）
#    - CATEGORY_NOT_FOUND_TEMPLATE: 分类不存在提示（详细版）
#    - CATEGORY_NOT_FOUND_TEMPLATE_MINIMAL: 分类不存在提示（精简版）
#    - TOOL_DETAIL_NOT_FOUND_TEMPLATE: 工具详情未找到提示
#
# 5. 语音播报模板（VOICE_PROMPTS）:
#    - querying: 正在查询中，请稍后
#    - processing: 正在处理，请稍候
#    - thinking: 正在思考中
#    - executing: 正在执行操作
#    - searching: 正在搜索相关信息
#    - loading: 正在加载数据
#    - completed: 操作已完成
#    - error: 操作遇到问题，请重试
#
# 【关联文件】
# 1. core/prompt_builder.py                    - 提示词构建器
#    * 关系：模板使用者
#    * 交互：PromptBuilder使用LAYER1/2/3_TEMPLATE构建提示词
#
# 2. core/prompt_navigator.py                  - 提示词导航器
#    * 关系：模板使用者
#    * 交互：PromptNavigator使用LAYER1/2/3_*_TEMPLATE和错误模板
#
# 3. core/prompt_templates_v2.py               - Token优化版模板（已合并）
#    * 关系：内容来源
#    * 交互：v2版本的精简模板已合并到本文件的*_MINIMAL版本中
#
# 【PromptLayer枚举】
# - L1_OVERVIEW: "l1_overview" - 概览层
# - L2_MANUAL: "l2_manual" - 手册层
# - L3_TOOL_DETAIL: "l3_tool_detail" - 详情层
#
# 【LAYER_COMMANDS命令映射】
# L1命令: 首页/home/概览/overview/主界面/返回首页
# L2命令: 手册/manual/工具手册/工具列表/tools/目录/menu/返回手册/返回目录
# 返回命令: 返回/back (从L3返回L2)
#
# 【动态模板选择】
# - get_layer_template(layer, context_size): 根据上下文大小自动选择模板
# - LONG_CONTEXT_THRESHOLD = 6000: 长对话阈值
# - LAYER_TEMPLATES: 详细版模板字典 {1: L1, 2: L2, 3: L3}
# - LAYER_TEMPLATES_MINIMAL: 精简版模板字典 {1: L1_MINIMAL, 2: L2_MINIMAL, 3: L3_MINIMAL}
#
# 【模板占位符说明】
# LAYER1_TEMPLATE: {user_instruction}, {status_bar}
# LAYER2_TEMPLATE: {category}, {tool_list}, {status_bar}
# LAYER3_TEMPLATE: {tool_id}, {name}, {description}, {parameters}, {required}, {example}, {status_bar}
# LAYER1_OVERVIEW_TEMPLATE: {work_mode}, {tool_count}, {memory_status}, {status_bar}
# LAYER2_MANUAL_TEMPLATE: {tool_count}, {tool_list}, {status_bar}
# LAYER3_TOOL_DETAIL_TEMPLATE: {tool_name}, {tool_description}, {tool_params}, {tool_examples}, {status_bar}
#
# 【达到的效果】
# 1. Token优化：符号和表格比纯文字更省token
# 2. 结构化清晰：AI更容易解析表格和符号标记
# 3. 游戏化体验："硅基生命体"设定增强AI角色感
# 4. 三层渐进：从概览到手册到详情，信息密度递增
# 5. 导航友好：模板内置导航说明，降低学习成本
# 6. 错误友好：美观的错误提示，引导用户正确操作
# 7. 统一风格：所有模板保持一致的视觉风格
# 8. 动态适配：根据对话长度自动选择合适模板，平衡详细度与性能
#
# 【Token节省估算】
# - L1模板: 78.5% 节省 (3124 → 671 chars)
# - L2模板: 29.6% 节省 (291 → 205 chars)
# - L3模板: 精简版与详细版相近
# - 总计: 约65% Token节省 (常规对话使用详细版，长对话使用精简版)
#
# 【设计原则体现】
# 1. 符号>文字：⚡👁️🖐️🧠等emoji替代长文本
# 2. 表格>段落：工具列表使用结构化展示
# 3. 双向导航：每个层级都有返回和前进的说明
# 4. 动态选择：根据上下文大小自动切换模板版本
#
# 【使用场景】
# - Agent初始化时构建系统提示词（L1/L2/L3根据层级选择）
# - 用户切换层级时更新提示词内容
# - 工具查询时显示详细信息
# - 错误发生时显示友好提示
# - 长对话场景自动切换到精简模板以节省Token
#
# =============================================================================
