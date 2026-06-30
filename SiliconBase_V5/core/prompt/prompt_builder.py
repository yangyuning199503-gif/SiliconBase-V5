#!/usr/bin/env python3
"""
提示词构建器 - 根据当前层级构建系统提示词

【功能使用边界 - 重要】

你是AI，用户是人类。有些功能你直接用，有些用户通过界面用：

✅ 你直接用的（无需告诉用户）：
- `(查找工具)` - 你快速查工具列表
- `(查询记忆)` - 你查历史经验
- `create_task` - 你创建定时任务（如闹钟、提醒）
- TOOL_CALL调用工具 - 你执行具体操作

✅ 用户通过前端界面用的（你不需要管）：
- 监控面板 - 用户看系统状态
- 记忆管理页面 - 用户手动删改记忆
- 世界模型训练 - 用户启动/停止训练
- AI配置 - 用户设置API Key

⚠️ 共用的（你和用户都能用）：
- 长期任务暂停/恢复
- 查看任务列表

【原则】
- 你能直接做的，直接做，不要问用户"要不要"
- 用户界面是给他看的，不是你用的
- 别让用户去点按钮，你直接输出标记或调用工具

【游戏化三层架构】
- L1: 概览层 - 系统概览和当前状态
- L2: 手册层 - 所有工具的名称和用途列表
- L3: 工具详情层 - 具体工具的详细使用方法
"""

from core.diagnostic import safe_create_task
from core.prompt.prompt_templates import (
    EMPTY_USER_CONTEXT,
    LAYER1_OVERVIEW_TEMPLATE,
    LAYER1_TEMPLATE_MINIMAL,
    LAYER2_MANUAL_TEMPLATE,
    LAYER2_TEMPLATE,
    LAYER3_TEMPLATE,
    LAYER3_TOOL_DETAIL_TEMPLATE,
)
from core.tool.tool_manager import tool_manager

TOOL_NOT_FOUND_TEMPLATE = "工具 '{{tool_id}}' 未找到。请检查工具名称或输入'手册'查看列表。"
CATEGORY_NOT_FOUND_TEMPLATE = "分类 '{{category}}' 不存在。请检查分类名称。"
TOOL_DETAIL_NOT_FOUND_TEMPLATE = "工具详情 '{{tool_id}}' 未找到。"
from enum import Enum

from core.logger import logger
from voice.voice_assistant import get_voice_assistant


class PromptLayer(Enum):
    """提示词层级枚举"""
    L1_OVERVIEW = "L1_OVERVIEW"      # 概览层
    L2_MANUAL = "L2_MANUAL"          # 工具手册层
    L3_TOOL_DETAIL = "L3_TOOL_DETAIL"  # 工具详情层


class PromptBuilder:
    """构建分层提示词（基础版）"""

    @staticmethod
    def build_layer1(user_instruction: str, working_memory, known_app_paths: dict = None) -> str:
        """构建第一层提示词：只显示工具分类列表"""
        try:
            categories = tool_manager.get_tool_categories()
            category_list = "\n".join([f"  • {cat} ({len(tools)}个工具)"
                                       for cat, tools in sorted(categories.items())])
        except Exception as e:
            logger.error(f"[PromptBuilder] 获取工具分类失败: {e}")
            category_list = "  (暂时无法获取工具列表)"

        # 【Phase 3】构建已知的应用快捷方式提示词
        known_app_shortcuts = ""
        if known_app_paths:
            shortcuts_lines = ["【🎯 已知的应用路径（从记忆中获取）】"]
            for app_name, path in list(known_app_paths.items())[:10]:  # 最多显示10个
                shortcuts_lines.append(f"• {app_name}: {path}")
            shortcuts_lines.append("这些应用可直接用 launch_app(\"应用名\") 调用，底座会自动使用正确路径。")
            known_app_shortcuts = "\n".join(shortcuts_lines)

        return LAYER1_TEMPLATE_MINIMAL.format(
            user_instruction=user_instruction,
            user_context_block=EMPTY_USER_CONTEXT,
            category_list=category_list,
            status_bar=working_memory.get_status_bar(),
            known_app_shortcuts=known_app_shortcuts
        )

    @staticmethod
    def build_layer2(category: str, working_memory) -> str:
        """构建第二层提示词：按分类显示工具（表格形式）"""
        try:

            tools_by_cat = tool_manager.get_tools_by_category_v2(category)

            if not tools_by_cat or not tools_by_cat.get(category):

                categories = tool_manager.get_tool_categories()
                available = "\n".join([f"  • {cat} ({info.get('count', 0)}个工具)"
                                       for cat, info in categories.items()])
                return CATEGORY_NOT_FOUND_TEMPLATE.format(
                    category=category,
                    available_categories=available
                )


            tools_table = ""
            for cat_name, tools in tools_by_cat.items():
                tools_table += f"\n### {cat_name}\n"
                tools_table += "| 工具ID | 工具名称 | 功能描述 |\n"
                tools_table += "|--------|----------|----------|\n"

                for tool in tools:
                    desc = tool.get('description', '无')[:30]
                    tools_table += f"| {tool['id']:<14} | {tool['name']:<8} | {desc:<28} |\n"

        except Exception as e:
            logger.error(f"[PromptBuilder] 获取分类工具失败: {e}")
            tools_table = "  (暂时无法获取工具列表)"

        return LAYER2_TEMPLATE.format(
            category=category,
            tool_list=tools_table,
            status_bar=working_memory.get_status_bar()
        )

    @staticmethod
    def build_layer3(tool_id: str, working_memory) -> str:
        """构建第三层提示词：工具详情"""
        try:
            detail = tool_manager.get_tool_detail(tool_id)
            if not detail:
                return TOOL_NOT_FOUND_TEMPLATE.format(tool_id=tool_id)


            params_str = ""
            for param_name, param_info in detail["parameters"].items():
                desc = param_info.get("description", "无描述")
                param_type = param_info.get("type", "any")
                params_str += f"  • {param_name} ({param_type}): {desc}\n"

            if not params_str:
                params_str = "  (无参数)"


            required = detail.get("required", [])
            required_str = ", ".join(required) if required else "无"


            example = detail.get("example", {"tool": tool_id, "params": {}})
            import json
            example_str = json.dumps(example, ensure_ascii=False, indent=2)

            example_str = example_str.replace("{", "{{").replace("}", "}}")

            return LAYER3_TEMPLATE.format(
                tool_id=tool_id,
                name=detail["name"],
                description=detail["description"],
                parameters=params_str.rstrip(),
                required=required_str,
                example=example_str,
                status_bar=working_memory.get_status_bar()
            )

        except Exception as e:
            logger.error(f"[PromptBuilder] 获取工具详情失败: {e}")
            return TOOL_NOT_FOUND_TEMPLATE.format(tool_id=tool_id)



class LayeredPromptBuilder:
    """
    游戏化分层提示词构建器

    支持L1/L2/L3三层切换，AI可通过自然语言命令切换层级

    使用示例:
        builder = LayeredPromptBuilder()
        builder.set_voice(voice_instance)


        layer, prompt = builder.handle_layer_command("手册")


        layer, prompt = builder.handle_layer_command("截图工具")

    """

    def __init__(self):
        self.current_layer = PromptLayer.L1_OVERVIEW
        self.current_tool = None
        self.voice = None
        self._work_mode = "normal"
        self._memory_status = "正常"
        self._voice_assistant = None

    def set_voice(self, voice_instance):
        """设置语音实例用于播报"""
        self.voice = voice_instance

        if self._voice_assistant is None:
            self._voice_assistant = get_voice_assistant(voice_instance)
        else:
            self._voice_assistant.set_voice_interface(voice_instance)

    def set_work_mode(self, mode: str):
        """设置工作模式"""
        self._work_mode = mode

    def set_memory_status(self, status: str):
        """设置记忆库状态"""
        self._memory_status = status

    def handle_layer_command(self, command: str) -> tuple:
        """
        处理层级切换命令

        Args:
            command: AI输入的命令（如"手册"、"截图工具"、"首页"）

        Returns:
            (新层级, 提示词内容)
        """
        if not command:
            return self.current_layer, self._build_current_layer_prompt()

        command_clean = command.strip().lower()


        if command_clean in ["首页", "home", "overview", "概览", "主界面", "返回首页"]:
            return self._switch_to_layer(PromptLayer.L1_OVERVIEW)

        elif command_clean in ["手册", "manual", "工具手册", "工具列表", "tools", "目录", "menu", "返回手册", "返回目录"]:
            return self._switch_to_layer(PromptLayer.L2_MANUAL)

        elif command_clean in ["返回", "back"]:
            if self.current_layer == PromptLayer.L3_TOOL_DETAIL:
                return self._switch_to_layer(PromptLayer.L2_MANUAL)
            elif self.current_layer == PromptLayer.L2_MANUAL:
                return self._switch_to_layer(PromptLayer.L1_OVERVIEW)

        elif self._is_tool_name(command_clean):

            return self._switch_to_tool_detail(command_clean)


        return self.current_layer, self._build_current_layer_prompt()

    def _switch_to_layer(self, layer: PromptLayer) -> tuple:
        """切换到指定层级"""
        old_layer = self.current_layer
        self.current_layer = layer

        # 修复：使用asyncio创建任务
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                safe_create_task(self._announce_layer_switch(layer, from_layer=old_layer), name="_announce_layer_switch")
            else:
                loop.run_until_complete(self._announce_layer_switch(layer, from_layer=old_layer))
        except Exception as e:
            logger.debug(f"[LayeredPromptBuilder] 语音播报失败: {e}")

        self.current_tool = None

        return layer, self._build_current_layer_prompt()

    def _switch_to_tool_detail(self, tool_name: str) -> tuple:
        """切换到工具详情层"""
        old_layer = self.current_layer
        self.current_layer = PromptLayer.L3_TOOL_DETAIL
        self.current_tool = tool_name


        from_layer_str = self._get_layer_str(old_layer)
        if self._voice_assistant:
            self._voice_assistant.announce_l3_tool_detail(tool_name, from_layer=from_layer_str)
        elif self.voice:
            self.voice.speak(f"正在查询{tool_name}的使用方法，请稍后...", is_system=True)

        return PromptLayer.L3_TOOL_DETAIL, self._build_tool_detail_prompt(tool_name)

    def _get_layer_str(self, layer: PromptLayer) -> str:
        """将 PromptLayer 转换为字符串标识"""
        if layer == PromptLayer.L1_OVERVIEW:
            return 'l1'
        elif layer == PromptLayer.L2_MANUAL:
            return 'l2'
        elif layer == PromptLayer.L3_TOOL_DETAIL:
            return 'l3'
        return None

    async def _announce_layer_switch(self, layer: PromptLayer, from_layer: PromptLayer = None):
        """
        播报层级切换

        【异步方式】不阻塞主流程，语音失败静默处理
        """
        if not self.voice and not self._voice_assistant:
            return

        from_layer_str = self._get_layer_str(from_layer)

        try:
            if self._voice_assistant:
                if layer == PromptLayer.L1_OVERVIEW:
                    self._voice_assistant.announce_l1_overview(from_layer=from_layer_str)
                elif layer == PromptLayer.L2_MANUAL:
                    self._voice_assistant.announce_l2_manual(from_layer=from_layer_str)
                elif layer == PromptLayer.L3_TOOL_DETAIL and self.current_tool:
                    self._voice_assistant.announce_l3_tool_detail(self.current_tool, from_layer=from_layer_str)
            elif self.voice:
                announcements = {
                    PromptLayer.L1_OVERVIEW: "正在查询中，请稍后",
                    PromptLayer.L2_MANUAL: "正在查询中，请稍后",
                    PromptLayer.L3_TOOL_DETAIL: "正在查询中，请稍后"
                }

                announcement = announcements.get(layer, "正在查询中，请稍后")
                # 异步调用，不阻塞主流程
                import asyncio
                if hasattr(self.voice, 'speak_async'):
                    safe_create_task(self.voice.speak_async(announcement, is_system=True), name="speak_async")
                else:
                    # 同步调用但使用线程池避免阻塞
                    asyncio.create_task(asyncio.to_thread(
                        self.voice.speak, announcement, is_system=True, wait=False
                    ))
        except Exception as e:
            # 静默处理，不影响功能
            logger.debug(f"[LayeredPromptBuilder] 语音播报失败（静默处理）: {e}")

    def _build_current_layer_prompt(self) -> str:
        """构建当前层级的提示词"""
        if self.current_layer == PromptLayer.L1_OVERVIEW:
            return self._build_l1_overview()
        elif self.current_layer == PromptLayer.L2_MANUAL:
            return self._build_l2_manual()
        elif self.current_layer == PromptLayer.L3_TOOL_DETAIL:
            return self._build_l3_tool_detail()
        return ""

    def _build_l1_overview(self) -> str:
        """构建L1概览层"""
        try:
            all_tools = tool_manager.list_tools()
            len(all_tools)
        except Exception as e:
            logger.error(f"[LayeredPromptBuilder] 获取工具数量失败: {e}")

        # 获取分类列表
        try:
            categories = tool_manager.get_tool_categories(use_functional=True)
            category_list_items = []
            for cat_name, info in sorted(categories.items()):
                count = info.get('count', 0)
                category_list_items.append(f"  • {cat_name} ({count}个工具)")
            category_list = "\n".join(category_list_items)
        except Exception as e:
            logger.error(f"[LayeredPromptBuilder] 获取分类列表失败: {e}")
            category_list = "  (暂时无法获取分类列表)"

        return LAYER1_OVERVIEW_TEMPLATE.format(
            user_instruction="（等待用户输入）",
            user_context_block=EMPTY_USER_CONTEXT,
            category_list=category_list,
            status_bar="当前层级: L1概览 | 输入'手册'查看工具列表",
            known_app_shortcuts=""
        )

    def _build_l2_manual(self) -> str:
        """构建L2工具手册层"""
        try:
            all_tools = tool_manager.list_tools()

            tool_list_items = []
            for tool in all_tools[:30]:
                tool_id = tool.get('id', 'unknown')
                tool_name = tool.get('name', '未知')
                tool_desc = tool.get('description', '无描述')

                if len(tool_desc) > 40:
                    tool_desc = tool_desc[:37] + "..."
                tool_list_items.append(f"• {tool_id}: {tool_name} - {tool_desc}")

            tool_list = "\n".join(tool_list_items)
            len(all_tools)

        except Exception as e:
            logger.error(f"[LayeredPromptBuilder] 获取工具列表失败: {e}")
            tool_list = "  (暂时无法获取工具列表)"

        return LAYER2_MANUAL_TEMPLATE.format(
            category="所有分类",
            tool_list=tool_list,
            status_bar="当前层级: L2手册 | 输入工具名查看详情 | 输入'首页'返回"
        )

    def _build_l3_tool_detail(self) -> str:
        """构建L3工具详情层"""
        if not self.current_tool:
            return "请先选择工具"

        return self._build_tool_detail_prompt(self.current_tool)

    def _build_tool_detail_prompt(self, tool_name: str) -> str:
        """构建指定工具的详情提示词"""
        try:
            detail = tool_manager.get_tool_detail(tool_name)
            if not detail:
                return TOOL_DETAIL_NOT_FOUND_TEMPLATE.format(tool_name=tool_name)


            params_str = ""
            parameters = detail.get("parameters", {})
            if parameters:
                for param_name, param_info in parameters.items():
                    if isinstance(param_info, dict):
                        desc = param_info.get("description", "无描述")
                        param_type = param_info.get("type", "any")
                        required = "必填" if param_info.get("required", False) else "可选"
                        params_str += f"  • {param_name} ({param_type}, {required}): {desc}\n"
                    else:
                        params_str += f"  • {param_name}: {param_info}\n"
            else:
                params_str = "  (该工具无需参数)"


            examples_str = ""
            example = detail.get("example")
            if example:
                import json
                examples_str = f"```json\n{json.dumps(example, ensure_ascii=False, indent=2)}\n```"
            else:
                examples_str = "  暂无使用示例"

            return LAYER3_TOOL_DETAIL_TEMPLATE.format(
                tool_name=detail.get("name", tool_name),
                tool_description=detail.get("description", "无描述"),
                tool_params=params_str.rstrip(),
                tool_examples=examples_str,
                status_bar=f"当前层级: L3详情 | 工具: {tool_name} | 输入'返回'回到L2"
            )

        except Exception as e:
            logger.error(f"[LayeredPromptBuilder] 获取工具详情失败: {e}")
            return TOOL_DETAIL_NOT_FOUND_TEMPLATE.format(tool_name=tool_name)

    def _is_tool_name(self, command: str) -> bool:
        """检查是否是工具名称"""
        try:
            tool = tool_manager.get_tool(command)
            return tool is not None
        except Exception:
            return False

    def get_current_layer(self) -> PromptLayer:
        """获取当前层级"""
        return self.current_layer

    def get_current_tool(self) -> str:
        """获取当前选中的工具"""
        return self.current_tool

    def is_layer_command(self, text: str) -> bool:
        """
        识别AI是否要切换层级

        Args:
            text: AI输入的文本

        Returns:
            bool: 是否是层级切换命令
        """
        if not text:
            return False

        text_lower = text.lower().strip()


        layer_keywords = {
            "l1": ["首页", "home", "overview", "概览", "主界面", "返回首页"],
            "l2": ["手册", "manual", "工具手册", "工具列表", "tools", "目录", "menu", "返回手册", "返回目录"],
            "l3_return": ["返回", "back"],
        }

        for _layer, keywords in layer_keywords.items():
            if any(kw.lower() in text_lower for kw in keywords):
                return True


        return bool(self._is_tool_name(text_lower))



prompt_builder = PromptBuilder()
layered_prompt_builder = LayeredPromptBuilder()



def get_layered_prompt_builder() -> LayeredPromptBuilder:
    """获取分层提示词构建器实例"""
    return layered_prompt_builder


def is_layer_command(text: str) -> bool:
    """
    识别AI是否要切换层级

    Args:
        text: AI输入的文本

    Returns:
        bool: 是否是层级切换命令
    """
    return layered_prompt_builder.is_layer_command(text)


def handle_layer_command(command: str, voice_instance=None) -> tuple:
    """
    处理层级切换命令

    Args:
        command: AI输入的命令
        voice_instance: 语音实例（用于播报）

    Returns:
        (新层级, 提示词内容)
    """
    if voice_instance:
        layered_prompt_builder.set_voice(voice_instance)
    return layered_prompt_builder.handle_layer_command(command)






try:
    from core.prompt.prompt_navigator import NavigationCommands, PromptNavigator, get_navigator, is_navigation_command
    from core.prompt.prompt_navigator import handle_navigation as navigator_handle_navigation
except ImportError:

    PromptNavigator = None
    NavigationCommands = None
    get_navigator = None
    is_navigation_command = None
    navigator_handle_navigation = None
    logger.warning("[PromptBuilder] 无法从 prompt_navigator 导入，请检查文件是否存在")


# =============================================================================

# =============================================================================
#




#







#





#




#




#





#









#




#



#



#



#



#



#





#


#



#







#






#









#






#


#     |

#     |

#     |

#     |

#     |

#
# =============================================================================
