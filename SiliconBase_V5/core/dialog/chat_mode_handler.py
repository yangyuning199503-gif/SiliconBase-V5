#!/usr/bin/env python3                          # 指定Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文字符
"""
聊天模式处理器 - 支持用户级模式切换
SiliconBase V5.1 多用户支持改造

职责：
1. 处理语音输入的纯对话
2. 理解用户需求
3. 判断是否需要创建任务
4. 无缝切换到任务模式
5. 支持用户级工作模式隔离
"""

import re  # 导入正则表达式模块，用于文本解析
import threading  # 导入线程模块，用于线程安全
import time  # 导入时间模块
import warnings  # 导入警告模块，用于标记废弃方法
from typing import Any  # 从typing导入类型提示

from core.agent.task_mode_runner import TaskModeRunner  # 导入任务模式运行器
from core.ai.ai_adapter import call_thinker_async  # 异步AI调用
from core.diagnostic import safe_create_task
from core.intent.command_parser import CommandType, get_command_parser  # 导入命令解析器
from core.logger import logger  # 导入日志记录器
from core.mode.work_mode_manager import WorkMode  # 导入工作模式管理
from core.session.alignment_state import TRIGGER_LOOP_KEYWORDS, AlignmentStateManager, check_trigger_loop
from core.sync.realtime_sync import get_realtime_sync_manager  # 导入实时同步管理器

# 导入对齐状态管理（P1-002修复：聊天对齐模式）
from voice.voice_prompts import DialogueManagerAnnouncements, SystemAnnouncements


class UserWorkModeManager:                       # 定义用户级工作模式管理器类
    """
    用户级工作模式管理器

    每个用户拥有独立的工作模式状态，模式切换只影响当前用户。
    """

    def __init__(self, user_id: str = "default"):   # 初始化方法
        self.user_id = user_id                   # 实例属性：用户ID
        self._mode = WorkMode.FOCUS              # 实例属性：当前模式，默认为专注模式
        self._mode_configs: dict[WorkMode, dict] = {   # 实例属性：模式配置字典
            WorkMode.DAILY: {                      # 日常模式配置
                "interval": 300,                   # 思考间隔300秒（5分钟）
                "auto_think": True,                # 自动思考开启
                "description": "日常模式：AI连接思维模块，弱连接可主动触发任务"   # 模式描述
            },
            WorkMode.FOCUS: {                      # 专注模式配置
                "interval": 600,                   # 思考间隔600秒（10分钟，频率降低）
                "auto_think": True,                # 自动思考开启
                "description": "专注模式：AI思考优先级最低，不主动触发弱连接"   # 模式描述
            }
        }

    async def switch_mode(self, mode: WorkMode) -> bool:   # 定义切换模式的方法
        """切换工作模式"""                       # 方法文档字符串
        if mode == self._mode:                   # 如果目标模式与当前相同
            return True                          # 直接返回成功

        old_mode = self._mode
        logger.info(f"[UserWorkModeManager] 用户 {self.user_id} 切换模式: {self._mode.value} -> {mode.value}")   # 记录模式切换日志
        self._mode = mode                        # 更新当前模式

        # ═══════════════════════════════════════════════════════════════
        # 【Phase1-Week1集成】MemoryAutoTrigger: 异步存储模式切换事件
        # ═══════════════════════════════════════════════════════════════
        async def _trigger_mode_switch_storage():
            try:
                from core.memory.memory_auto_trigger import MemoryAutoTrigger
                session_id = f"session_{self.user_id}"

                context_data = {
                    "reason": "用户主动切换",
                    "old_mode_config": self._mode_configs.get(old_mode, {}),
                    "new_mode_config": self._mode_configs.get(mode, {})
                }

                await MemoryAutoTrigger.on_mode_switch(
                    user_id=self.user_id,
                    session_id=session_id,
                    from_mode=old_mode.value,
                    to_mode=mode.value,
                    context_data=context_data
                )
                logger.info(f"[MemoryAutoTrigger] 模式切换存储成功: user={self.user_id}, {old_mode.value} -> {mode.value}")
            except Exception as e:
                logger.error(f"[MemoryAutoTrigger] 模式切换存储失败: {e}", exc_info=True)

        safe_create_task(_trigger_mode_switch_storage(), name="_trigger_mode_switch_storage")

        # 触发 Consciousness 调整               # 注释：调整意识模块
        try:                                     # 异常处理块
            from core.consciousness import Consciousness  # 延迟导入意识模块
            consciousness = Consciousness()      # 获取意识实例

            if mode == WorkMode.FOCUS:           # 如果切换到专注模式
                # Focus模式：降低思考频率（10分钟）   # 注释：专注模式配置
                consciousness.set_user_interval(self.user_id, 600)   # 设置思考间隔为10分钟
                consciousness.set_think_priority(10)   # 设置最低优先级
                logger.info(f"[UserWorkModeManager] 用户 {self.user_id} Focus模式：降低思考频率至10分钟，优先级最低")   # 记录日志
            elif mode == WorkMode.DAILY:         # 如果切换到日常模式
                # Daily模式：正常频率（5分钟）         # 注释：日常模式配置
                consciousness.set_user_interval(self.user_id, 300)   # 设置思考间隔为5分钟
                consciousness.set_think_priority(5)   # 设置中等优先级
                logger.info(f"[UserWorkModeManager] 用户 {self.user_id} Daily模式：正常思考频率5分钟，中等优先级")   # 记录日志
        except Exception as e:                   # 调整失败
            logger.debug(f"[UserWorkModeManager] 调整Consciousness失败: {e}")   # 记录调试日志

        return True                              # 返回成功

    def get_current_mode(self) -> WorkMode:      # 定义获取当前模式的方法
        """获取当前模式"""                       # 方法文档字符串
        return self._mode                        # 返回当前模式

    def get_mode_info(self) -> dict:             # 定义获取模式信息的方法
        """获取模式信息"""                       # 方法文档字符串
        cfg = self._mode_configs.get(self._mode, {})   # 获取当前模式配置
        return {                                 # 返回模式信息字典
            "mode": self._mode.value,            # 模式名称
            "description": cfg.get("description", ""),   # 模式描述
            "interval": cfg.get("interval", 0),   # 思考间隔
            "auto_think": cfg.get("auto_think", False)   # 是否自动思考
        }


class ChatModeHandler:                           # 定义聊天模式处理器类
    """
    聊天模式处理器

    职责：
    1. 处理语音输入的纯对话
    2. 理解用户需求
    3. 判断是否需要创建任务
    4. 无缝切换到任务模式
    5. 支持语音输入的聊天对齐需求
    """

    # 提示词：纯聊天模式，严格区分任务指令         # 类属性注释
    CHAT_SYSTEM_PROMPT = """你是 SiliconBase AI 助手，正在与用户进行语音对话。   # 系统提示词定义

【当前模式：纯聊天模式】                         # 提示词：模式说明
- **这是语音对话，只是聊天，不执行任何操作**     # 提示词：强调纯聊天
- **禁止调用工具**，禁止创建任务                 # 提示词：禁止工具调用
- 用自然、友好、简短的方式回复                   # 提示词：回复风格

【任务识别规则 - 严格模式】                       # 提示词：任务识别规则
只有用户明确说"打开XX"、"执行XX"、"开始XX任务"时，才输出任务标记。   # 提示词：触发条件
以下情况**绝对不要**输出任务标记：               # 提示词：非任务场景
- 问候语（你好、在吗、可以听到吗）→ 正常聊天回复   # 场景1：问候语
- 闲聊（今天天气、新闻、笑话）→ 正常聊天回复     # 场景2：闲聊
- 提问（什么是XX、为什么XX、XX工具是哪个）→ 正常聊天回复  # 场景3：提问（包括工具查询）
- 工具信息查询（"怎么使用XX"、"XX工具在哪里"）→ 回答工具信息或引导查看手册  # 场景4：工具查询
- 模糊需求（帮我看看、处理一下）→ 追问具体需求，不要直接创建任务   # 场景5：模糊需求

【输出格式】                                     # 提示词：输出格式
正常情况：直接回复自然语言，不要任何标记。         # 正常回复格式

只有在用户明确说"打开/执行/开始XX"时，在回复末尾添加：   # 任务标记格式
[CREATE_TASK: 具体任务描述]

【示例】                                         # 提示词：示例
用户："可以听到吗"                               # 示例1输入
你："可以的，我听得很清楚。有什么可以帮你的吗？"   # 示例1回复
（无标记，纯聊天）                               # 示例1说明

用户："今天天气怎么样"                           # 示例2输入
你："我需要查一下天气信息，请问你在哪个城市？"     # 示例2回复
（无标记，纯聊天）                               # 示例2说明

用户："打开应用的工具是哪个？"                   # 示例3输入（工具查询）
你："打开应用的工具是 'launch_app'，你可以在工具手册中查看详情。输入'手册'可以查看所有工具。"  # 示例3回复
（无标记，这是信息查询，不是执行任务）           # 示例3说明

用户："怎么使用截图工具？"                       # 示例4输入（工具查询）
你："截图工具是 'screenshot'，可以截取屏幕。输入'查看工具详情 screenshot'查看具体用法。"  # 示例4回复
（无标记，这是信息查询）                         # 示例4说明

用户："打开微信"                                 # 示例5输入
你："好的，我来帮你打开微信。"                   # 示例5回复
[CREATE_TASK: 打开微信]                          # 示例5任务标记
（明确指令，才创建任务）                         # 示例5说明

【重要】                                         # 提示词：重要提示
- 语音对话以聊天为主，不要让用户感觉太机械       # 提示1
- 宁可不创建任务，也不要误判创建任务             # 提示2
- 回复要简洁，适合语音播报（2-3句话）"""         # 提示3

    def __init__(self, user_id: str = "default"):   # 初始化方法
        self.user_id = user_id                   # 实例属性：用户ID
        self.chat_history = []                   # 实例属性：聊天历史列表
        self.command_parser = get_command_parser()   # 实例属性：命令解析器实例
        # 分层导航状态                             # 注释：导航状态
        self.navigation_state = {                # 实例属性：导航状态字典
            "current_layer": "root",             # 当前层级：root/category/tool_detail
            "current_category": None,            # 当前分类
            "current_tool": None,                # 当前工具
        }
        # P1-002修复：对齐状态管理器（语音输入聊天对齐模式）
        self._alignment_manager = AlignmentStateManager()

    def _should_enter_task_mode(self, text: str, intent: dict) -> bool:   # 定义判断是否进入任务模式的方法
        """
        判断是否进入任务模式的决策逻辑：

        触发条件（满足任一）：
        1. 明确任务意图：包含"打开"、"执行"、"运行"、"创建"等动词
        2. 工具调用需求：AI判断需要调用外部工具
        3. 多步骤需求：AI判断需要多个步骤完成
        4. 用户明确指令：用户说"进入任务模式"

        不触发条件（满足任一）：
        1. 纯聊天：问候、闲聊、情感交流
        2. 信息查询：只需回答，无需操作
        3. 用户明确说"普通模式"
        """
        pass  # 实际逻辑在 _handle_chat 中通过 AI 响应解析实现

    async def handle(self, user_input: str, session_id: str, voice_instance=None) -> tuple[str, bool, str | None]:   # 定义主处理方法
        """
        处理聊天输入（增强版）

        支持分层交互命令：
        1. 先检查是否为命令（最高优先级）
        2. 如果是命令，处理分层导航
        3. 如果不是命令，进入AI聊天模式

        Returns:
            (response, needs_task, task_description)
            - response: 给用户的自然语言回复
            - needs_task: 是否需要创建任务
            - task_description: 任务描述（如果需要）
        """
        # 1. 首先检查是否为分层交互命令（最高优先级）   # 注释：步骤1
        cmd = self.command_parser.parse(user_input)   # 解析用户输入是否为命令
        if cmd:                                      # 如果是命令
            response = self._handle_command(cmd, voice_instance)   # 处理命令
            # 【修复】发送AI回复到前端显示
            self._send_chat_response(session_id, response, is_command=True)
            # 分层命令不创建任务，直接返回             # 命令不创建任务
            return response, False, None             # 返回命令处理结果

        # 2. 检查是否看起来像命令但格式错误             # 注释：步骤2
        if self.command_parser._looks_like_command(user_input):   # 检查是否像命令
            suggestion = self.command_parser.get_help_text()   # 获取帮助文本
            response = f'输入的命令格式不正确。\n{suggestion}'   # 构建错误提示
            if voice_instance:                       # 如果有语音实例
                voice_instance.speak(DialogueManagerAnnouncements.COMMAND_FORMAT_ERROR)   # 语音播报
            return response, False, None             # 返回错误提示

        # 3. 进入AI聊天模式（非命令）                   # 注释：步骤3
        clean_response, needs_task, task_desc = await self._handle_chat(self.user_id, user_input, voice_instance, session_id)   # 处理聊天
        # 【修复】发送AI回复到前端显示
        self._send_chat_response(session_id, clean_response, is_command=False)
        return clean_response, needs_task, task_desc

    def _announce_layer_switch(self, voice_instance, target_layer: str):
        """
        【新增】播报层级切换提示

        Args:
            voice_instance: 语音实例
            target_layer: 目标层级 (L1/L2/L3)
        """
        if not voice_instance:
            return

        try:
            # 异步播报，不阻塞主流程
            voice_instance.speak(SystemAnnouncements.QUERYING, is_system=True, wait=False)
            logger.debug(f"[ChatModeHandler] 播报层级切换: {target_layer}")
        except Exception as e:
            # 静默处理，不影响功能
            logger.debug(f"[ChatModeHandler] 语音播报失败（静默处理）: {e}")

    def _handle_command(self, cmd, voice_instance=None) -> str:   # 定义处理命令的私有方法
        """
        处理分层交互命令

        支持：
        - QUERY_TOOL_LIST: 查看分类工具列表 (L1->L2)
        - QUERY_TOOL_DETAIL: 查看工具详情 (L2->L3)
        - BACK_TO_PREV: 返回上一层 (L3->L2 或 L2->L1)
        - NAVIGATE_TO_L1: 导航到首页 (P0-3修复)
        - NAVIGATE_TO_L2: 导航到手册 (P0-3修复)
        - HELP: 显示帮助
        - CLEAR: 清空历史

        【语音播报】L1/L2/L3切换时播报"正在查询中，请稍后"
        """
        from core.tool.tool_manager import tool_manager  # 延迟导入工具管理器

        # 获取当前层级用于判断切换方向
        old_layer = self.navigation_state.get("current_layer", "root")

        if cmd.command_type == CommandType.QUERY_TOOL_LIST:   # 查询工具列表命令 (L1->L2)
            category = cmd.params.get("category", "")   # 获取分类参数

            # 【语音播报】L1->L2切换
            if voice_instance and old_layer == "root":
                self._announce_layer_switch(voice_instance, "L1->L2")

            tools = tool_manager.get_tools_by_category(category)   # 获取分类下工具

            if not tools:                            # 如果没有工具
                response = f'分类 "{category}" 下没有找到工具。\n可用分类：输入类、控制类、查询类、系统类'   # 返回提示
            else:                                    # 有工具
                tool_list = "\n".join([f"  • {t.name}: {t.description}" for t in tools[:10]])   # 构建工具列表
                response = f'【{category}】下的工具：\n{tool_list}\n\n查看详情请输入：查看工具详情 [工具ID]'   # 构建回复

            self.navigation_state["current_layer"] = "category"   # 更新导航层级
            self.navigation_state["current_category"] = category   # 更新当前分类

        elif cmd.command_type == CommandType.QUERY_TOOL_DETAIL:   # 查询工具详情命令 (L2->L3)
            tool_id = cmd.params.get("tool_id", "")   # 获取工具ID

            # 【语音播报】L2->L3切换
            if voice_instance:
                self._announce_layer_switch(voice_instance, "L2->L3")

            tool = tool_manager.get_tool(tool_id)    # 获取工具

            if not tool:                             # 工具不存在
                response = f'未找到工具 "{tool_id}"。'   # 返回错误
            else:                                    # 工具存在
                params_info = "\n".join([f"    - {p.name} ({p.type}): {p.description}"
                                         for p in tool.parameters]) if tool.parameters else "    无参数"   # 构建参数信息
                response = f'''【{tool.name}】工具详情：
描述：{tool.description}
参数：
{params_info}

返回上一层请输入：返回'''                       # 构建详情回复

            self.navigation_state["current_layer"] = "tool_detail"   # 更新导航层级
            self.navigation_state["current_tool"] = tool_id   # 更新当前工具

        elif cmd.command_type == CommandType.NAVIGATE_TO_L1:   # 【P0-3修复】导航到首页(L1)
            # 【语音播报】导航到L1
            if voice_instance:
                self._announce_layer_switch(voice_instance, "L1")

            self.navigation_state["current_layer"] = "root"
            self.navigation_state["current_category"] = None
            self.navigation_state["current_tool"] = None
            response = '【首页 - SiliconBase AI 助手】\n\n可用命令：\n• 手册 - 查看工具手册\n• 查看 [分类] 工具 - 查看分类工具\n• 帮助 - 显示帮助信息'

        elif cmd.command_type == CommandType.NAVIGATE_TO_L2:   # 【P0-3修复】导航到手册(L2)
            # 【语音播报】导航到L2
            if voice_instance:
                self._announce_layer_switch(voice_instance, "L2")

            # 获取所有工具分类
            try:
                categories = tool_manager.get_categories() if hasattr(tool_manager, 'get_categories') else ["输入类", "控制类", "查询类", "系统类"]
                if not categories:
                    categories = ["输入类", "控制类", "查询类", "系统类"]

                # 构建分类列表
                category_list = "\n".join([f"  • {cat}" for cat in categories])

                response = f'''【工具手册 - L2】

工具分类：
{category_list}

查看分类工具请输入：查看 [分类名] 工具
例如：查看 输入类 工具

查看工具详情请输入：查看工具详情 [工具ID]
返回首页请输入：首页'''

                self.navigation_state["current_layer"] = "l2_manual"
                self.navigation_state["current_category"] = None
            except Exception as e:
                logger.warning(f"[ChatModeHandler] 获取工具分类失败: {e}")
                # 使用默认分类
                response = '''【工具手册 - L2】

工具分类：
  • 输入类
  • 控制类
  • 查询类
  • 系统类

查看分类工具请输入：查看 [分类名] 工具
返回首页请输入：首页'''
                self.navigation_state["current_layer"] = "l2_manual"

        elif cmd.command_type == CommandType.BACK_TO_PREV:   # 返回上一层命令
            current = self.navigation_state["current_layer"]   # 获取当前层级
            if current == "tool_detail":             # 如果在工具详情层 (L3->L2)
                # 【语音播报】L3->L2切换
                if voice_instance:
                    self._announce_layer_switch(voice_instance, "L3->L2")

                # 从工具详情返回到分类                 # 注释：返回逻辑
                category = self.navigation_state.get("current_category")   # 获取当前分类
                if category:                         # 如果有分类
                    self.navigation_state["current_layer"] = "category"   # 更新层级
                    self.navigation_state["current_tool"] = None   # 清空工具
                    # 重新显示分类工具列表             # 注释：重新显示列表
                    tools = tool_manager.get_tools_by_category(category)   # 获取工具
                    tool_list = "\n".join([f"  • {t.name}: {t.description}" for t in tools[:10]])   # 构建列表
                    response = f'返回到【{category}】分类。\n{tool_list}'   # 构建回复
                else:                                # 无分类
                    self.navigation_state["current_layer"] = "root"   # 回到根层
                    response = '已返回到主菜单。可用命令：查看 [分类名] 工具、帮助'   # 构建回复
            elif current == "category":              # 如果在分类层 (L2->L1)
                # 【语音播报】L2->L1切换
                if voice_instance:
                    self._announce_layer_switch(voice_instance, "L2->L1")

                self.navigation_state["current_layer"] = "root"   # 回到根层
                self.navigation_state["current_category"] = None   # 清空分类
                response = '已返回到主菜单。可用命令：查看 [分类名] 工具、帮助'   # 构建回复
            else:                                    # 已经在根层
                response = '已经在主菜单了。可用命令：查看 [分类名] 工具、帮助'   # 构建回复

        elif cmd.command_type == CommandType.HELP:   # 帮助命令
            response = self.command_parser.get_help_text()   # 获取帮助文本

        elif cmd.command_type == CommandType.CLEAR:   # 清空历史命令
            self.chat_history.clear()                # 清空聊天历史
            response = '对话历史已清空。'              # 返回提示

        else:                                        # 未知命令类型
            response = f'未知命令类型：{cmd.command_type.value}'   # 返回错误

        # 播报回复（语音模式）- 【修复】播报完整内容
        if voice_instance and response:              # 如果有语音实例和回复
            try:
                voice_instance.speak(response, wait=False)         # 语音播报完整内容
            except Exception as e:
                logger.debug(f"[ChatModeHandler] 语音播报失败（静默处理）: {e}")

        return response                              # 返回回复

    def _emit_execution_event(self, session_id: str, event_type: str, content: str, **kwargs):
        """
        【新增】发送执行事件到前端，用于填充执行日志

        Args:
            session_id: 会话ID
            event_type: 事件类型 (thinking, executing, tool_result, error)
            content: 事件内容
            **kwargs: 额外数据
        """
        if not session_id:
            return

        try:
            sync = get_realtime_sync_manager()
            data = {"content": content, **kwargs}
            sync.emit_event(event_type, session_id, data)
            logger.debug(f"[ChatModeHandler] 发送执行事件: {event_type}, {content[:50]}...")
        except Exception as e:
            logger.debug(f"[ChatModeHandler] 发送执行事件失败: {e}")

    async def _handle_chat(self, user_id: str, user_input: str, voice_instance=None, session_id: str = None) -> tuple[str, bool, str | None]:   # 定义处理聊天的私有方法
        """
        处理普通聊天（AI模式）

        原handle方法的聊天逻辑

        Args:
            user_id: 用户ID
            user_input: 用户输入
            voice_instance: 语音实例
            session_id: 会话ID（用于发送前端显示）
        """
        # 【新增】发送开始思考事件
        self._emit_execution_event(session_id, "thinking", "正在理解您的意图...", step="understanding")

        # 构建消息                                   # 注释：构建消息列表
        messages = [                                 # 初始化消息列表
            {"role": "system", "content": self.CHAT_SYSTEM_PROMPT},   # 系统提示词
            *self.chat_history[-20:],                # 最近10轮对话历史（原来3轮太少）
            {"role": "user", "content": user_input}   # 用户当前输入
        ]

        # [修复] 调用AI，增加异常处理和超时保护         # 注释：修复说明
        try:                                         # 异常处理块
            # 【新增】发送AI调用事件
            self._emit_execution_event(session_id, "thinking", f"AI思考中... 历史消息: {len(self.chat_history)//2}轮", step="ai_thinking")

            # 使用CHAT场景配置，更短的超时时间         # 注释：使用CHAT场景
            from core.ai.ai_config import AIScene  # 延迟导入场景枚举
            response = await call_thinker_async(messages, scene=AIScene.CHAT, hard_timeout=60)   # 调用AI

            # 【新增】发送AI响应完成事件
            if response:
                self._emit_execution_event(session_id, "thinking", "AI响应生成完成", step="ai_complete")
        except Exception as e:                       # 调用异常
            logger.error(f"[ChatModeHandler] AI调用异常: {e}")   # 记录错误
            # 【新增】发送错误事件
            self._emit_execution_event(session_id, "error", f"AI调用失败: {str(e)[:100]}")
            response = None                          # 响应设为None

        # [修复] 更友好的超时提示                     # 注释：超时处理
        if not response:                             # 如果没有响应（超时或失败）
            timeout_reply = "抱歉，我思考的时间有点长，请稍后再试或换一种方式提问。"   # 超时回复
            if voice_instance:                       # 如果有语音实例
                voice_instance.speak(DialogueManagerAnnouncements.THINKING_TIMEOUT, is_system=True)   # 语音播报
            return timeout_reply, False, None        # 返回超时回复

        # 解析回复：提取CREATE_TASK标记               # 注释：解析响应
        clean_response, needs_task, task_desc = self._parse_response(response)   # 解析响应

        # 更新聊天历史                               # 注释：更新历史
        self.chat_history.append({"role": "user", "content": user_input})   # 添加用户消息
        self.chat_history.append({"role": "assistant", "content": clean_response})   # 添加助手消息

        # 限制历史长度                               # 注释：限制历史
        if len(self.chat_history) > 20:              # 如果超过20条
            self.chat_history = self.chat_history[-20:]   # 保留最近20条

        # 播报回复（语音模式）                         # 注释：语音播报
        if voice_instance and clean_response:        # 如果有语音实例和回复
            voice_instance.speak(clean_response)     # 语音播报

        return clean_response, needs_task, task_desc   # 返回处理结果

    def _parse_response(self, response: str) -> tuple[str, bool, str | None]:   # 定义解析响应的私有方法
        """
        解析AI回复
        提取 [CREATE_TASK: xxx] 标记
        """
        # 匹配 CREATE_TASK 标记                       # 注释：正则匹配
        pattern = r'\[CREATE_TASK:\s*(.+?)\]'        # 定义正则模式
        match = re.search(pattern, response, re.IGNORECASE)   # 搜索匹配

        if match:                                    # 如果匹配到
            task_desc = match.group(1).strip()       # 提取任务描述
            # 移除标记后的干净回复                     # 注释：清理回复
            clean_response = re.sub(pattern, '', response, flags=re.IGNORECASE).strip()   # 移除标记
            return clean_response, True, task_desc   # 返回清理后的回复和任务信息

        return response.strip(), False, None         # 无标记，返回原回复

    def _send_chat_response(self, session_id: str, response: str, is_command: bool = False):
        """
        【修复】发送聊天回复到前端显示

        Args:
            session_id: 会话ID
            response: AI回复内容
            is_command: 是否为命令响应
        """
        if not session_id or not response:
            return

        try:
            sync = get_realtime_sync_manager()
            # 【关键修复】使用chat_alignment_reply类型，前端App.tsx能正确处理
            # 之前使用chat_response类型，前端switch case中没有处理，导致消息被忽略
            sync.emit_event("chat_alignment_reply", session_id, {
                "content": response,
                "is_command": is_command,
                "timestamp": time.time()
            })
            logger.debug(f"[ChatModeHandler] 发送聊天回复到前端: {response[:50]}...")
        except Exception as e:
            logger.warning(f"[ChatModeHandler] 发送前端显示失败: {e}")

    def clear_history(self):                         # 定义清空历史的方法
        """清空聊天历史"""                           # 方法文档字符串
        self.chat_history = []                       # 清空聊天历史列表
        self.navigation_state = {                    # 重置导航状态
            "current_layer": "root",                 # 回到根层
            "current_category": None,                # 清空分类
            "current_tool": None,                    # 清空工具
        }

    async def handle_voice(self, user_input: str, session_id: str, voice_instance=None) -> dict:
        """
        处理语音输入的聊天对齐需求

        【已废弃】此方法不强制经过聊天对齐流程，请使用 handle_voice_input

        专门用于语音唤醒和前端语音输入，与AI聊天确认需求
        返回结构化结果，包含是否需要触发任务

        Args:
            user_input: 用户语音输入（已识别为文本）
            session_id: 会话ID
            voice_instance: 语音实例，用于播报

        Returns:
            dict: {
                "should_trigger_task": bool,
                "task_description": str,
                "chat_reply": str,
                "success": bool
            }

        Deprecated: 请使用 handle_voice_input 替代，强制进入聊天对齐模式
        """
        warnings.warn(
            "ChatModeHandler.handle_voice is deprecated, use handle_voice_input instead",
            DeprecationWarning,
            stacklevel=2
        )
        logger.info(f"[ChatModeHandler] 处理语音输入: {user_input[:50]}...")

        try:
            chat_reply, needs_task, task_desc = await self.handle(
                user_input, session_id, voice_instance
            )

            return {
                "success": True,
                "should_trigger_task": needs_task,
                "task_description": task_desc,
                "chat_reply": chat_reply
            }

        except Exception as e:
            logger.error(f"[ChatModeHandler] 处理语音输入异常: {e}")
            error_msg = "抱歉，处理您的语音输入时出现问题，请重试。"
            if voice_instance:
                voice_instance.speak(error_msg)
            return {
                "success": False,
                "should_trigger_task": False,
                "task_description": None,
                "chat_reply": error_msg
            }

    # =============================================================================
    # P1-002修复：语音输入聊天对齐模式新方法
    # =============================================================================

    async def handle_voice_input(self, user_id: str, voice_text: str, session_id: str = None) -> dict:
        """
        处理语音输入 - P1-002增强版：智能意图分类

        流程：
        1. 【新增】意图分类：明确指令/模糊需求/闲聊
        2. 明确指令（如"打开网易云音乐"）：直接确认对齐，进入任务执行
        3. 模糊需求：进入聊天对齐模式，最多确认一次
        4. 闲聊：纯聊天回复，不进入任务模式

        Args:
            user_id: 用户ID
            voice_text: 语音转文字内容
            session_id: 会话ID

        Returns:
            Dict: 对齐处理结果
                - type: "alignment_confirmed" | "alignment_ongoing" | "alignment_error"
                - message: 状态消息
                - ai_response: AI回复内容
                - next_step: "enter_task_loop" | "continue_alignment"
        """
        # ═══════════════════════════════════════════════════════════════
        # 【MemoryTrigger】自动存储用户输入 - 解决"该存但没存"问题
        # ═══════════════════════════════════════════════════════════════
        actual_session_id = session_id or f"session_{user_id}"
        try:
            from core.memory.memory_trigger import on_user_input
            on_user_input(
                user_id=user_id,
                session_id=actual_session_id,
                text=voice_text,
                metadata={"source": "voice_input", "handler": "chat_mode"}
            )
            logger.debug(f"[ChatModeHandler] 用户输入已触发存储: {voice_text[:50]}...")
        except Exception as e:
            # 存储失败不阻断主流程
            logger.warning(f"[ChatModeHandler] 用户输入存储失败（非阻塞）: {e}")

        # 【修复】导入意图分类函数
        from core.alignment_state import classify_voice_intent

        alignment_mgr = self._alignment_manager

        # 检查是否已在对齐模式
        existing_alignment = alignment_mgr.get_alignment(user_id)

        if existing_alignment and not existing_alignment.is_confirmed:
            # 继续对齐对话
            existing_alignment.add_turn("user", voice_text)

            # 构建对齐提示词（继续对话）
            prompt = self._build_alignment_prompt_continue(existing_alignment, voice_text)
        else:
            # 【修复】意图分类检测 - 明确指令直接执行，不进入反复确认流程
            intent_type = await classify_voice_intent(voice_text)

            if intent_type == "direct_task":
                # 明确任务指令（如"打开网易云音乐"）
                logger.info(f"[ChatModeHandler] 检测到明确任务指令: {voice_text[:50]}...")

                # 创建对齐状态并立即确认
                alignment = alignment_mgr.create_alignment(user_id, voice_text)
                alignment.add_turn("user", voice_text)

                # 记录需求到记忆
                await self._save_requirement_to_memory(user_id, voice_text)

                # 立即确认对齐，直接进入任务执行
                confirmation_msg = f"好的，我来{voice_text}"
                alignment.confirm(confirmation_msg)

                # 保存到聊天历史
                self.chat_history.append({"role": "user", "content": voice_text})
                self.chat_history.append({"role": "assistant", "content": confirmation_msg})

                return {
                    "type": "alignment_confirmed",
                    "message": "检测到明确指令，直接执行任务",
                    "user_requirement": voice_text,
                    "ai_understanding": confirmation_msg,
                    "ai_response": confirmation_msg,  # 兼容字段
                    "next_step": "enter_task_loop",
                    "direct_execution": True  # 标记为直接执行
                }

            # 创建新的对齐状态（模糊需求或闲聊）
            alignment = alignment_mgr.create_alignment(user_id, voice_text)
            alignment.add_turn("user", voice_text)

            # 记录需求到记忆
            await self._save_requirement_to_memory(user_id, voice_text)

            # 根据意图类型选择提示词
            if intent_type == "ambiguous":
                prompt = self._build_alignment_prompt_quick(alignment)  # 快速对齐（最多一轮）
            else:
                prompt = self._build_alignment_prompt_chat(alignment)   # 纯聊天模式

        # 发送给AI
        try:
            from core.ai.ai_adapter import call_thinker_async
            from core.ai.ai_config import AIScene
            ai_response = await call_thinker_async(
                [{"role": "user", "content": prompt}],
                scene=AIScene.CHAT,
                hard_timeout=60
            )
        except Exception as e:
            logger.error(f"[ChatModeHandler] AI调用异常: {e}")
            return {
                "type": "alignment_error",
                "message": f"AI处理异常: {str(e)}",
                "next_step": "retry"
            }

        # 记录AI回复
        alignment = alignment_mgr.get_alignment(user_id)
        if alignment:
            alignment.add_turn("assistant", ai_response)

        # ═══════════════════════════════════════════════════════════════
        # 【MemoryTrigger】自动存储AI回复
        # ═══════════════════════════════════════════════════════════════
        try:
            from core.memory.memory_trigger import on_ai_response
            # 提取意图类型作为metadata
            ai_metadata = {"source": "chat_mode"}
            if 'intent_type' in locals():
                ai_metadata["intent_type"] = intent_type

            on_ai_response(
                user_id=user_id,
                session_id=actual_session_id,
                text=ai_response,
                metadata=ai_metadata
            )
            logger.debug(f"[ChatModeHandler] AI回复已触发存储: {ai_response[:50]}...")
        except Exception as e:
            logger.warning(f"[ChatModeHandler] AI回复存储失败（非阻塞）: {e}")

        # 保存到普通聊天历史
        self.chat_history.append({"role": "user", "content": voice_text})
        self.chat_history.append({"role": "assistant", "content": ai_response})
        if len(self.chat_history) > 20:
            self.chat_history = self.chat_history[-20:]

        # 检查是否触发进入循环
        if check_trigger_loop(ai_response):
            # AI触发进入循环
            alignment_mgr.confirm_alignment(user_id, ai_response)

            return {
                "type": "alignment_confirmed",
                "message": "需求已对齐，进入任务循环",
                "user_requirement": alignment.original_input if alignment else voice_text,
                "ai_understanding": ai_response,
                "ai_response": ai_response,
                "next_step": "enter_task_loop"
            }
        else:
            # 继续对齐
            return {
                "type": "alignment_ongoing",
                "message": "继续对齐需求",
                "ai_response": ai_response,
                "hint": f"说'{TRIGGER_LOOP_KEYWORDS[0]}'或确认需求后进入执行",
                "next_step": "continue_alignment"
            }

    def _build_alignment_prompt_new(self, alignment) -> str:
        """构建新的对齐提示词（包含普通聊天历史）"""
        # 【修复】包含普通聊天历史，保持上下文连贯
        chat_history_str = ""
        if self.chat_history:
            recent_history = self.chat_history[-20:]  # 最近10轮对话（原来3轮太少）
            chat_history_str = "\\n".join([
                f"{msg['role']}: {msg['content']}"
                for msg in recent_history
            ])

        context_section = f"""
【之前的对话历史】
{chat_history_str}

""" if chat_history_str else ""

        return f"""用户通过语音输入了需求，当前处于【需求对齐模式】。
{context_section}用户原始输入: {alignment.original_input}

你需要：
1. 理解用户的需求（结合之前的对话历史）
2. 向用户复述你的理解，确认是否正确
3. 如果用户提到"你刚才说的"、"之前的"等，要联系上文理解
4. 询问用户是否有补充或修改
5. 当用户确认理解正确后，说"开始执行"进入任务循环

重要：
- 不要立即执行工具调用
- 先确保你完全理解用户需求（结合上下文）
- 只有用户确认后才说"开始执行"
- 如果用户的问题是对之前对话的追问，要承接上文回答

当前是对齐过程的第1轮对话。
"""

    def _build_alignment_prompt_continue(self, alignment, user_input: str) -> str:
        """构建继续对齐的提示词（包含普通聊天历史）"""
        # 对齐模式的历史
        alignment_history_str = "\\n".join([
            f"{turn['role']}: {turn['content']}"
            for turn in alignment.conversation_history[-10:]  # 最近5轮对齐对话
        ])

        # 【修复】也包含普通聊天历史
        chat_history_str = ""
        if self.chat_history:
            recent_chat = self.chat_history[-20:]  # 最近10轮普通聊天
            chat_history_str = "\\n".join([
                f"{msg['role']}: {msg['content']}"
                for msg in recent_chat
            ])

        context_section = f"""
【之前的普通聊天】
{chat_history_str}

""" if chat_history_str else ""

        return f"""继续需求对齐模式。
{context_section}【当前对齐对话】
{alignment_history_str}

用户最新输入: {user_input}

继续对齐需求。当你确认完全理解后，说"开始执行"进入任务循环。
注意：如果用户提到之前的对话内容，要结合上下文理解。
"""

    def _build_alignment_prompt_quick(self, alignment) -> str:
        """
        构建快速对齐提示词（最多一轮确认）

        用于模糊需求，快速确认后立即执行，避免反复询问。
        """
        chat_history_str = ""
        if self.chat_history:
            recent_history = self.chat_history[-20:]
            chat_history_str = "\\n".join([
                f"{msg['role']}: {msg['content']}"
                for msg in recent_history
            ])

        context_section = f"""
【之前的对话历史】
{chat_history_str}

""" if chat_history_str else ""

        return f"""用户通过语音输入了需求，当前处于【快速确认模式】。
{context_section}用户原始输入: {alignment.original_input}

你需要：
1. 快速理解用户的核心需求（结合上下文）
2. 简要复述你的理解（1句话）
3. **立即说"开始执行"进入任务循环，不要多次询问**

重要：
- 这是快速确认模式，**最多确认一次**
- 不要问"您当前使用的设备是..."这类问题
- 如果有缺失信息，先执行再反馈，或者使用默认设置
- 用户说"确定"、"是的"、"没错"等即表示确认

当前是第1轮对话，确认后立即执行。
"""

    def _build_alignment_prompt_chat(self, alignment) -> str:
        """
        构建纯聊天模式提示词

        用于闲聊场景，不进入任务执行。
        """
        chat_history_str = ""
        if self.chat_history:
            recent_history = self.chat_history[-20:]
            chat_history_str = "\\n".join([
                f"{msg['role']}: {msg['content']}"
                for msg in recent_history
            ])

        context_section = f"""
【之前的对话历史】
{chat_history_str}

""" if chat_history_str else ""

        return f"""用户通过语音与你聊天。
{context_section}用户输入: {alignment.original_input}

你需要：
1. 用自然、友好的方式回复
2. 这是纯聊天，**不要执行任何操作**
3. 如果用户提到想执行任务，引导他们说明确指令如"打开XX"
4. 回复要简洁，适合语音播报（2-3句话）

【输出规则】
- 正常聊天：直接回复，不要任何标记
- 只有用户明确说"打开/执行/开始XX"时，在回复末尾添加：[CREATE_TASK: 具体任务]
"""

    async def _save_requirement_to_memory(self, user_id: str, requirement: str):
        """保存需求到用户记忆（大纲第5条要求）"""
        try:
            from core.memory.memory_manager import get_memory_manager
            memory_mgr = await get_memory_manager()

            await memory_mgr.add_memory(
                user_id=user_id,
                content=f"用户需求（语音）: {requirement}",
                memory_type="requirement",
                metadata={
                    "source": "voice_input",
                    "status": "pending_alignment"
                }
            )
        except Exception as e:
            logger.warning(f"[ChatModeHandler] 保存需求到记忆失败: {e}")

    def clear_alignment_state(self, user_id: str):
        """清除用户的对齐状态"""
        self._alignment_manager.clear_alignment(user_id)

    def is_in_alignment_mode(self, user_id: str) -> bool:
        """检查用户是否在对齐模式"""
        return self._alignment_manager.is_in_alignment(user_id)




class ChatModeHandlerManager:                    # 定义聊天模式处理器管理器类
    """
    聊天模式处理器管理器

    按用户管理ChatModeHandler实例，实现用户隔离。
    """

    def __init__(self):                          # 初始化方法
        self._handlers: dict[str, ChatModeHandler] = {}   # 实例属性：用户处理器字典
        self._lock = threading.Lock()            # 实例属性：线程锁

    def get_handler(self, user_id: str = "default") -> ChatModeHandler:   # 定义获取处理器的方法
        """获取用户的聊天模式处理器"""             # 方法文档字符串
        with self._lock:                         # 获取线程锁
            if user_id not in self._handlers:    # 如果用户没有处理器
                self._handlers[user_id] = ChatModeHandler(user_id=user_id)   # 创建新处理器
            return self._handlers[user_id]       # 返回处理器

    def clear_handler(self, user_id: str):       # 定义清除处理器的方法
        """清除用户的处理器"""                     # 方法文档字符串
        with self._lock:                         # 获取线程锁
            if user_id in self._handlers:        # 如果用户有处理器
                del self._handlers[user_id]      # 删除处理器

    def clear_all(self):                         # 定义清除所有处理器的方法
        """清除所有处理器"""                       # 方法文档字符串
        with self._lock:                         # 获取线程锁
            self._handlers.clear()               # 清空处理器字典


class DualModeManager:                           # 定义双模式管理器类
    """
    双模式管理器（支持用户隔离）

    统一入口：
    - 语音输入 -> ChatMode -> (需要时) -> TaskMode
    - 文本输入 -> TaskMode (直接进入)

    每个用户拥有独立的模式状态和处理历史。
    """

    def __init__(self):                          # 初始化方法
        self._chat_handlers = ChatModeHandlerManager()   # 实例属性：聊天处理器管理器
        self._task_runner = TaskModeRunner()     # 实例属性：任务模式运行器
        self._user_mode_managers: dict[str, UserWorkModeManager] = {}   # 实例属性：用户模式管理器字典
        self._lock = threading.Lock()            # 实例属性：线程锁

    def get_mode_manager(self, user_id: str = "default") -> UserWorkModeManager:   # 定义获取模式管理器的方法
        """获取用户的模式管理器"""                 # 方法文档字符串
        with self._lock:                         # 获取线程锁
            if user_id not in self._user_mode_managers:   # 如果用户没有模式管理器
                self._user_mode_managers[user_id] = UserWorkModeManager(user_id)   # 创建新模式管理器
            return self._user_mode_managers[user_id]   # 返回模式管理器

    async def switch_mode(self, user_id: str, mode: WorkMode):   # 定义切换模式的方法
        """为用户切换模式"""                       # 方法文档字符串
        manager = self.get_mode_manager(user_id)   # 获取用户的模式管理器
        await manager.switch_mode(mode)                # 切换模式

        # 触发 Consciousness 调整                 # 注释：调整意识模块
        try:                                     # 异常处理块
            from core.consciousness import Consciousness  # 延迟导入意识模块
            consciousness = Consciousness()      # 获取意识实例

            if mode == WorkMode.FOCUS:           # 如果切换到专注模式
                # Focus模式：降低思考频率（10分钟），优先级最低   # 注释：专注模式配置
                consciousness.set_user_interval(user_id, 600)   # 设置10分钟间隔
                consciousness.set_think_priority(10)   # 设置最低优先级
                logger.info(f"[DualModeManager] 用户 {user_id} Focus模式：思考间隔10分钟，优先级最低")   # 记录日志
            else:                                # 日常模式
                # Daily模式：正常频率（5分钟），中等优先级       # 注释：日常模式配置
                consciousness.set_user_interval(user_id, 300)   # 设置5分钟间隔
                consciousness.set_think_priority(5)   # 设置中等优先级
                logger.info(f"[DualModeManager] 用户 {user_id} Daily模式：思考间隔5分钟，中等优先级")   # 记录日志
        except Exception as e:                   # 调整失败
            logger.debug(f"[DualModeManager] 调整Consciousness失败: {e}")   # 记录调试日志

    def get_user_mode(self, user_id: str = "default") -> WorkMode:   # 定义获取用户模式的方法
        """获取用户当前模式"""                     # 方法文档字符串
        manager = self.get_mode_manager(user_id)   # 获取模式管理器
        return manager.get_current_mode()        # 返回当前模式

    async def handle_voice(                       # 定义处理语音的方法（异步版本）
        self,
        text: str,
        session_id: str,
        voice_instance=None,
        user_id: str = "default"
    ) -> str:
        """
        处理语音输入（异步版本）

        【已废弃】此方法不强制经过聊天对齐流程，请使用 handle_voice_alignment

        流程：
        1. 先进聊天模式理解需求
        2. 如果需要执行任务 -> 自动切换到任务模式
        3. 返回最终结果

        Deprecated: 请使用 handle_voice_alignment 替代，强制进入聊天对齐模式
        """
        # 发出废弃警告
        warnings.warn(
            "handle_voice is deprecated, use handle_voice_alignment instead",
            DeprecationWarning,
            stacklevel=2
        )
        # 获取用户的聊天处理器                       # 注释：获取处理器
        chat_handler = self._chat_handlers.get_handler(user_id)   # 获取处理器

        # 第一步：聊天模式理解需求
        chat_reply, needs_task, task_desc = await chat_handler.handle(text, session_id, voice_instance)

        if not needs_task:                           # 如果不需要任务
            # 纯聊天，不需要执行任务                 # 注释：纯聊天
            return chat_reply                        # 返回聊天回复

        # 第二步：需要执行任务，切换到任务模式         # 注释：步骤2
        logger.info(f"聊天模式识别到任务，切换到任务模式: {task_desc}")   # 记录日志

        # 播报过渡语                                 # 注释：语音播报
        if voice_instance:                           # 如果有语音实例
            voice_instance.speak(f"好的，我来{task_desc}")   # 播报过渡语

        # 运行任务
        final_result = await self._task_runner.run(
            task_description=task_desc,               # 任务描述
            session_id=session_id,                    # 会话ID
            voice_instance=voice_instance,            # 语音实例
            user_id=user_id,                          # 用户ID
        )

        return final_result                          # 返回最终结果

    # =============================================================================
    # P1-002修复：语音输入聊天对齐模式新方法
    # =============================================================================

    async def handle_voice_alignment(
        self,
        text: str,
        session_id: str,
        voice_instance=None,
        user_id: str = "default"
    ) -> dict:
        """
        处理语音输入 - P1-002：聊天对齐模式

        语音输入先进入聊天对齐模式，AI说"开始执行"才进入循环

        Args:
            text: 语音识别的文本
            session_id: 会话ID
            voice_instance: 语音实例
            user_id: 用户ID

        Returns:
            Dict: 对齐结果
                - type: "alignment_confirmed" | "alignment_ongoing" | "alignment_error"
                - message: 状态描述
                - ai_response: AI回复内容
                - next_step: "enter_task_loop" | "continue_alignment"
                - user_requirement: 用户原始需求（确认对齐后）
                - ai_understanding: AI理解（确认对齐后）
        """
        logger.info(f"[DualModeManager] P1-002 语音对齐模式: {text[:50]}...")

        # 获取用户的聊天处理器
        chat_handler = self._chat_handlers.get_handler(user_id)

        # 调用对齐处理（语音输入必须经过聊天对齐）
        result = await chat_handler.handle_voice_input(
            user_id=user_id,
            voice_text=text,
            session_id=session_id
        )

        # 如果确认对齐，语音播报过渡语
        if result.get("type") == "alignment_confirmed" and voice_instance:
            voice_instance.speak(DialogueManagerAnnouncements.TASK_START)

        return result

    async def enter_task_loop_from_alignment(
        self,
        user_id: str,
        session_id: str,
        voice_instance=None,
        db_session_id: str | None = None
    ) -> str:
        """
        从对齐模式进入任务循环

        在AI确认对齐后调用此方法进入实际的任务执行循环

        Args:
            user_id: 用户ID
            session_id: 会话ID
            voice_instance: 语音实例

        Returns:
            str: 任务执行结果
        """
        chat_handler = self._chat_handlers.get_handler(user_id)

        # 获取对齐状态中的用户原始需求
        alignment_mgr = chat_handler._alignment_manager
        alignment = alignment_mgr.get_alignment(user_id)

        if not alignment or not alignment.is_confirmed:
            logger.error(f"[DualModeManager] 尝试进入任务循环但对齐未完成: {user_id}")
            return "错误：需求尚未对齐，请先完成对齐对话"

        # 使用AI的理解作为任务描述
        task_description = alignment.ai_understanding or alignment.original_input

        logger.info(f"[DualModeManager] 对齐完成，进入任务循环: {task_description[:50]}...")

        # 【记忆存储修复】模式切换前保存对话历史和对齐状态
        try:
            from core.memory.memory_manager import MemoryLayer, get_memory_manager
            memory_mgr = get_memory_manager()

            def save_alignment_state():
                try:
                    # 构建对话历史摘要
                    chat_history_summary = "\n".join([
                        f"{turn['role']}: {turn['content'][:100]}..."
                        for turn in alignment.conversation_history[-5:]  # 最近5轮
                    ]) if alignment.conversation_history else "无对话历史"

                    memory_mgr.record_interaction(
                        user_input=alignment.original_input,
                        ai_response=alignment.ai_understanding or "对齐完成，进入任务执行",
                        layer=MemoryLayer.SHORT,
                        metadata={
                            "source": "mode_transition",
                            "session_id": session_id,
                            "transition_type": "chat_to_task",
                            "alignment_status": "confirmed",
                            "conversation_turns": len(alignment.conversation_history),
                            "chat_history_summary": chat_history_summary,
                            "user_id": user_id
                        },
                        session_id=session_id
                    )
                    logger.debug(f"[Memory] 模式切换状态已存储: {session_id}")
                except Exception as e:
                    logger.warning(f"[Memory] 存储模式切换状态失败: {e}")

            # 异步执行，不阻塞模式切换
            threading.Thread(target=save_alignment_state, daemon=True).start()
        except Exception as e:
            logger.debug(f"[Memory] 模式切换记忆存储初始化失败: {e}")

        try:
            # 获取对齐对话历史
            chat_history = alignment.conversation_history if alignment else []

            # 运行任务循环
            final_result = await self._task_runner.run(
                task_description=task_description,
                session_id=session_id,
                voice_instance=voice_instance,
                chat_history=chat_history,
                db_session_id=db_session_id,
                user_id=user_id,
            )

            # 任务完成后清除对齐状态
            chat_handler.clear_alignment_state(user_id)

            return final_result

        except Exception as e:
            logger.error(f"[DualModeManager] 任务循环执行异常: {e}")
            # 出错也清除对齐状态，避免卡死
            chat_handler.clear_alignment_state(user_id)
            return f"任务执行失败: {str(e)}"

    async def handle_text(self, text: str, session_id: str, user_id: str = "default", db_session_id: str | None = None, voice_instance=None) -> str:   # Phase 8: async 入口
        """
        处理文本输入

        【P1-002修复】支持文本输入进入聊天对齐模式
        流程：
        1. 检查输入是否以"聊天:"或"对齐:"开头
        2. 如果是，进入聊天对齐模式
        3. 否则，直接进入任务模式

        使用方法：
        - 输入"聊天:你的问题"进入聊天对齐模式
        - 输入"对齐:你的需求"进入聊天对齐模式
        - 直接输入则保持原有行为（直接进入任务模式）
        """
        # 使用传入的 voice 实例，避免循环导入 dialogue_manager
        if voice_instance is None:
            voice_instance = None

        # 【P1-002修复】检查是否以"聊天:"或"对齐:"开头，进入聊天对齐模式
        stripped_text = text.strip()

        # 【P1-修复】简单聊天兜底快速通道：避免从其他入口进入时走入完整任务流
        from core.constants import is_simple_chat
        if is_simple_chat(stripped_text):
            logger.info(
                f"[DualModeManager] 文本输入识别为简单聊天，走快速通道: {stripped_text[:50]}..."
            )
            try:
                from core.dialog.dialogue_manager import get_dialogue_manager
                dm = get_dialogue_manager()
                return await dm._handle_quick_chat(
                    user_id, stripped_text, session_id, voice_instance
                )
            except Exception as e:
                logger.warning(
                    f"[DualModeManager] 快速聊天通道异常，回退到任务模式: {e}"
                )

        if stripped_text.startswith(("聊天:", "对齐:")):
            try:
                # 移除前缀，获取实际输入
                prefix_length = 3  # "聊天:" 或 "对齐:" 的长度
                actual_text = stripped_text[prefix_length:].strip()

                if not actual_text:
                    return "请输入内容，例如：\"聊天:帮我查一下今天的天气\""

                logger.info(f"[DualModeManager] 文本输入进入对齐模式: {actual_text[:50]}...")

                # 获取用户的聊天处理器
                chat_handler = self._chat_handlers.get_handler(user_id)

                # 进入聊天对齐模式（复用语音对齐的处理逻辑）
                result = await chat_handler.handle_voice_input(
                    user_id=user_id,
                    voice_text=actual_text,
                    session_id=session_id
                )

                # 根据对齐结果返回相应消息
                result_type = result.get("type")

                if result_type == "alignment_confirmed":
                    # 对齐已确认，自动进入任务循环
                    return await self.enter_task_loop_from_alignment(
                        user_id=user_id,
                        session_id=session_id,
                        voice_instance=voice_instance
                    )
                elif result_type == "alignment_ongoing":
                    # 继续对齐对话
                    ai_response = result.get("ai_response", "")
                    return f"【需求对齐模式】\n\n{ai_response}\n\n💡 提示：AI说\"开始执行\"后会自动进入任务执行"
                elif result_type == "alignment_error":
                    # 对齐过程出错
                    error_msg = result.get("message", "未知错误")
                    logger.error(f"[DualModeManager] 对齐模式错误: {error_msg}")
                    return f"【对齐模式错误】\n{error_msg}\n\n请重试或直接进入任务模式。"
                else:
                    # 未知结果类型，返回原始结果
                    return f"【对齐模式】\n{str(result)}"

            except Exception as e:
                logger.error(f"[DualModeManager] 文本对齐模式异常: {e}")
                # 出错时回退到原有行为（直接进入任务模式）
                # 保持向后兼容：不因为对齐模式的错误而影响原有功能

        # 原有逻辑：直接进入任务模式（Phase 8: await 异步入口）
        final_result = await self._task_runner.run(
            task_description=text,
            session_id=session_id,
            voice_instance=voice_instance,
            db_session_id=db_session_id,
            user_id=user_id,
        )
        return final_result

    async def handle_text_with_tools(self, text: str, session_id: str, user_id: str = "default", db_session_id: str | None = None, voice_instance=None) -> dict[str, Any]:
        """
        处理文本输入，返回包含工具调用信息的结果

        【P0-032 修复】WebSocket工具调用信息丢失修复

        流程：直接进入任务模式，收集工具调用信息

        Args:
            text: 用户输入文本
            session_id: 会话ID
            user_id: 用户ID

        Returns:
            Dict[str, Any]: 包含以下字段的字典
                - content (str): AI回复内容
                - tool_calls (List[Dict]): 工具调用列表
        """
        # 使用传入的 voice 实例，避免循环导入 dialogue_manager
        if voice_instance is None:
            voice_instance = None

        # 使用支持工具调用收集的run方法（Phase 8: await 异步入口）
        result = await self._task_runner.run_with_tools(
            task_description=text,
            session_id=session_id,
            voice_instance=voice_instance,
            db_session_id=db_session_id,
            user_id=user_id,
        )
        return result

    def clear_user_handler(self, user_id: str):    # 定义清除用户处理器的方法
        """清除用户的聊天处理器"""                 # 方法文档字符串
        self._chat_handlers.clear_handler(user_id)   # 清除处理器

    def get_user_stats(self, user_id: str = "default") -> dict:   # 定义获取用户统计的方法
        """获取用户统计"""                         # 方法文档字符串
        mode_manager = self.get_mode_manager(user_id)   # 获取模式管理器
        return {                                     # 返回统计信息
            "user_id": user_id,                      # 用户ID
            "current_mode": mode_manager.get_current_mode().value,   # 当前模式
            "mode_info": mode_manager.get_mode_info()   # 模式信息
        }


# 全局单例                                       # 注释：全局单例
dual_mode_manager = DualModeManager()            # 创建双模式管理器全局单例


# ==================== 便捷函数 ====================   # 注释：便捷函数区域

async def switch_user_mode(user_id: str, mode: WorkMode):   # 定义切换用户模式的便捷函数
    """切换用户模式的便捷函数"""                 # 函数文档字符串
    await dual_mode_manager.switch_mode(user_id, mode)   # 调用管理器切换模式


def get_user_mode(user_id: str = "default") -> WorkMode:   # 定义获取用户模式的便捷函数
    """获取用户模式的便捷函数"""                 # 函数文档字符串
    return dual_mode_manager.get_user_mode(user_id)   # 调用管理器获取模式
