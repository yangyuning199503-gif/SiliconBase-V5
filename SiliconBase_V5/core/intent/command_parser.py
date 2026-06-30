#!/usr/bin/env python3                          # 指定Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文字符
"""
命令解析器模块（专门化）

职责：
- 严格命令格式匹配（非自然语言）
- 分层交互命令解析
- 命令与自然语言的优先级处理

设计原则：
1. 命令必须严格匹配格式，避免自然语言误触发
2. 支持分层导航：分类 -> 工具列表 -> 工具详情
3. 命令优先级高于自然语言

命令格式：
- 查看 [分类名] 工具：查看某分类下的工具列表
- 查看工具详情 [工具ID]：查看工具详情
- 返回 / 返回分类 / 返回上一层：返回上一层
"""
import asyncio  # 导入异步IO模块，用于异步处理
import re  # 导入正则表达式模块，用于模式匹配
from collections.abc import Awaitable, Callable  # 导入类型提示
from dataclasses import dataclass, field  # 从dataclasses导入装饰器和字段工厂
from enum import Enum  # 从enum导入枚举基类和auto函数
from typing import Any

from voice.voice_prompts import SystemAnnouncements

# 尝试导入logger，如果失败则使用标准logging   # 注释：logger导入兼容处理
try:                                            # 尝试导入
    from core.logger import logger  # 从core.logger导入logger
except ImportError:                             # 导入失败
    import logging  # 导入标准logging模块
    logger = logging.getLogger(__name__)        # 获取当前模块的logger
    if not logger.handlers:                     # 如果没有处理器
        handler = logging.StreamHandler()       # 创建控制台处理器
        handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))   # 设置格式
        logger.addHandler(handler)              # 添加处理器
        logger.setLevel(logging.DEBUG)


# WebSocket 安全发送辅助函数
async def _safe_send_json(websocket, data: dict) -> bool:
    """安全发送 JSON 数据到 WebSocket"""
    try:
        # 检查 WebSocket 状态 (FastAPI)
        if hasattr(websocket, 'client_state'):
            from starlette.websockets import WebSocketState
            if websocket.client_state == WebSocketState.DISCONNECTED:
                logger.warning(f"[WebSocket] 连接已断开，跳过发送: {data.get('type', 'unknown')}")
                return False
        # 检查 WebSocket 状态 (websockets 库)
        elif hasattr(websocket, 'open'):
            if not websocket.open:
                logger.warning(f"[WebSocket] 连接已断开，跳过发送: {data.get('type', 'unknown')}")
                return False
        elif hasattr(websocket, 'closed'):
            if websocket.closed:
                logger.warning(f"[WebSocket] 连接已关闭，跳过发送: {data.get('type', 'unknown')}")
                return False

        await websocket.send_json(data)
        return True
    except Exception as e:
        logger.warning(f"[WebSocket] 发送失败: {e}")
        return False

          # 设置日志级别为DEBUG


# =============================================================================
# 精准抓取系统 (Precise-Capture)
# =============================================================================

class CapturePatterns:                           # 定义抓取模式类
    """
    精准抓取模式定义

    用于解析AI自然语言输出中的特定标记，触发底座功能。
    支持同时异步处理多个标记。
    """

    PATTERNS = {                                 # 类属性：模式字典
        # 核心交互标记 - 内容限制在单行，遇到标点、下一个标记或行尾时停止   # 注释：核心交互标记
        # 使用更严格的匹配，避免捕获自然语言文本   # 注释：匹配策略
        "call_user": r"\(呼叫用户\)\s*([^\n。！？;]*?)(?=\s*[\(。！？;]|\s*$)",  # 呼叫用户模式
        "find_tool": r"\(查找工具\)\s*([^\n。！？;]*?)(?=\s*[\(。！？;]|\s*$)",  # 查找工具模式
        "evolution_reflection": r"\(进化反思\)\s*([^\n。！？;]*?)(?=\s*[\(。！？;]|\s*$)",  # 反思模式
        "world_model": r"\(世界模型\)\s*([^\n。！？;]*?)(?=\s*[\(。！？;]|\s*$)",  # 世界模型模式
        "vision_analysis": r"\(视觉分析\)\s*([^\n。！？;]*?)(?=\s*[\(。！？;]|\s*$)",  # 视觉分析模式

        # 工具调用标记 - 工具名必需，参数可选（单行，到标点或标记）   # 注释：工具调用标记
        "tool_call": r"\(工具调用:\s*(\w+)\)(?:\s*([^\n\(。！？;]*?))?(?=\s*[\(。！？;]|\s*$)",   # 工具调用模式

        # 长任务控制标记 - 内容在括号内（安全，不会跨标记）   # 注释：长任务控制标记
        "understanding_summary": r"\(提交理解摘要:\s*([^)]+)\)",  # 暂停确认模式
        "resume_execution": r"\(恢复执行\)",  # 恢复任务模式

        # 导航标记                                   # 注释：导航标记
        "navigate_l1": r"\(导航到首页\)",        # 导航到L1模式
        "navigate_l2": r"\(导航到手册\)",        # 导航到L2模式
        "navigate_l3": r"\(导航到工具:\s*(\w+)\)",   # 导航到L3模式

        # 语音控制标记 - 内容在括号内                 # 注释：语音控制标记
        "voice_speak": r"\(语音播报:\s*([^)]+)\)",  # 指定语音内容模式
        "voice_stop": r"\(停止语音\)",          # 停止当前语音模式

        # 界面控制标记 - 内容在括号内                 # 注释：界面控制标记
        "show_notification": r"\(显示通知:\s*([^)]+)\)",  # 显示通知模式
        "update_status": r"\(更新状态:\s*([^)]+)\)",  # 更新状态栏模式
    }


@dataclass                                       # 数据类装饰器
class ParsedAction:                              # 定义解析后的动作数据类
    """
    解析后的动作

    表示从AI响应中解析出的一个标记动作
    """
    action_type: str                            # 实例属性：动作类型（如call_user、find_tool等）
    content: str                                # 实例属性：自然语言内容
    params: dict[str, Any] = field(default_factory=dict)   # 实例属性：附加参数，默认为空字典
    raw_match: str = ""                         # 实例属性：原始匹配文本，默认为空
    position: int = 0                           # 实例属性：在原文中的起始位置，默认为0
    confidence: float = 1.0                     # 实例属性：置信度，默认为1.0


class PreciseCaptureParser:                      # 定义精准抓取解析器类
    """
    精准抓取解析器 (Precise-Capture Parser)

    职责：
    - 抓取AI的自然语言输出
    - 解析特定标记触发底座功能
    - 同时异步处理多个标记

    设计原则：
    1. 标记格式严格定义，避免误触发
    2. 支持多标记同时解析和异步处理
    3. 保持自然语言流畅性（可清理标记）

    标记格式：
    - (呼叫用户) 内容          - 呼叫用户并播报
    - (查找工具) 查询内容       - 触发L2工具查找
    - (工具调用: 工具名) 参数   - 调用指定工具
    - (视觉分析) 分析结果       - 视觉分析结果
    - (提交理解摘要: 内容)      - 长任务暂停确认
    - (恢复执行)               - 确认后恢复任务
    """

    def __init__(self):                          # 初始化方法
        self.patterns = CapturePatterns.PATTERNS   # 实例属性：引用模式字典
        self.compiled_patterns = {                 # 实例属性：编译后的模式字典
            name: re.compile(pattern, re.DOTALL)   # 编译每个正则表达式，使用DOTALL模式
            for name, pattern in self.patterns.items()   # 遍历所有模式
        }
        logger.info("PreciseCaptureParser 初始化完成")   # 记录初始化日志

    def parse(self, ai_response: str) -> list[ParsedAction]:   # 定义解析方法
        """
        解析AI响应，提取所有标记动作

        Args:
            ai_response: AI返回的原始响应文本

        Returns:
            按原文位置排序的动作列表

        Example:
            >>> parser = PreciseCaptureParser()
            >>> actions = parser.parse("(呼叫用户) 请确认 (工具调用: screenshot)")
            >>> len(actions)
            2
        """
        if not ai_response or not isinstance(ai_response, str):   # 检查输入有效性
            return []                                # 无效输入返回空列表

        actions = []                                 # 初始化动作列表

        for action_type, pattern in self.compiled_patterns.items():   # 遍历所有编译后的模式
            matches = pattern.finditer(ai_response)   # 在响应中查找所有匹配
            for match in matches:                    # 遍历所有匹配
                action = self._create_action(action_type, match)   # 创建动作对象
                if action:                           # 如果创建成功
                    actions.append(action)           # 添加到列表

        # 按在原文中的位置排序                         # 注释：排序逻辑
        actions.sort(key=lambda a: a.position)       # 按位置排序

        logger.debug(f"解析完成: 找到 {len(actions)} 个动作")   # 记录调试日志
        return actions                               # 返回动作列表

    def parse_and_clean(self, ai_response: str) -> tuple[list[ParsedAction], str]:   # 定义解析并清理方法
        """
        解析并清理响应

        移除所有标记（保留标记内容），保留纯自然语言文本

        Args:
            ai_response: AI返回的原始响应文本

        Returns:
            (动作列表, 清理后的自然语言文本)

        Example:
            >>> parser = PreciseCaptureParser()
            >>> actions, clean = parser.parse_and_clean("你好(呼叫用户)请确认")
            >>> clean
            '你好请确认'
        """
        actions = self.parse(ai_response)            # 先解析获取动作列表

        # 仅移除标记本身，保留标记后的内容             # 注释：清理策略
        clean_text = ai_response                     # 初始化清理后的文本
        for action in actions:                       # 遍历所有动作
            # 只替换标记部分，保留内容                 # 注释：针对不同动作类型的清理
            if action.action_type == "tool_call":    # 如果是工具调用
                # 工具调用: 替换 (工具调用: tool_name) 部分   # 注释：工具调用特殊处理
                marker = re.search(r"\(工具调用:\s*\w+\)", action.raw_match)   # 查找标记部分
                if marker:                           # 如果找到
                    clean_text = clean_text.replace(marker.group(0), "")   # 替换为空
            elif action.action_type in ["understanding_summary", "voice_speak",
                                         "show_notification", "update_status",
                                         "navigate_l3"]:   # 如果内容在括号内
                # 内容在括号内的标记：移除整个标记       # 注释：整标记移除
                clean_text = clean_text.replace(action.raw_match, "")   # 替换为空
            else:                                    # 其他标记
                # 其他标记：只替换标记头 (标记名)         # 注释：只移除标记头
                marker_pattern = r"\(" + action.action_type.replace("_", "") + r"\)"   # 构建标记模式
                # 特殊情况处理                           # 注释：特殊标记处理
                if action.action_type == "call_user":   # 呼叫用户
                    marker_pattern = r"\(呼叫用户\)"
                elif action.action_type == "find_tool":   # 查找工具
                    marker_pattern = r"\(查找工具\)"
                elif action.action_type == "evolution_reflection":   # 进化反思
                    marker_pattern = r"\(进化反思\)"
                elif action.action_type == "world_model":   # 世界模型
                    marker_pattern = r"\(世界模型\)"
                elif action.action_type == "vision_analysis":   # 视觉分析
                    marker_pattern = r"\(视觉分析\)"
                elif action.action_type == "navigate_l1":   # 导航到首页
                    marker_pattern = r"\(导航到首页\)"
                elif action.action_type == "navigate_l2":   # 导航到手册
                    marker_pattern = r"\(导航到手册\)"
                elif action.action_type == "resume_execution":   # 恢复执行
                    marker_pattern = r"\(恢复执行\)"
                elif action.action_type == "voice_stop":   # 停止语音
                    marker_pattern = r"\(停止语音\)"

                clean_text = re.sub(marker_pattern, "", clean_text, count=1)   # 替换一次

        # 清理多余空白                               # 注释：空白清理
        clean_text = re.sub(r'\s+', ' ', clean_text).strip()   # 将多个空白替换为单个空格

        logger.debug(f"清理完成: 原始 {len(ai_response)} 字符 -> 清理后 {len(clean_text)} 字符")   # 记录日志
        return actions, clean_text                   # 返回动作列表和清理后的文本

    def _create_action(self, action_type: str, match: re.Match) -> ParsedAction | None:   # 定义创建动作的私有方法
        """
        根据匹配结果创建ParsedAction

        Args:
            action_type: 动作类型
            match: 正则匹配结果

        Returns:
            ParsedAction 对象
        """
        groups = match.groups()                      # 获取匹配组
        params = {}                                  # 初始化参数字典
        content = ""                                 # 初始化内容

        # 根据不同动作类型提取参数                     # 注释：类型特定处理
        if action_type == "tool_call":               # 如果是工具调用
            # (工具调用: 工具名) 参数                  # 注释：格式说明
            tool_name = groups[0] if len(groups) > 0 else ""   # 获取工具名
            tool_params = groups[1] if len(groups) > 1 else ""   # 获取工具参数
            params["tool_name"] = tool_name.strip()   # 保存工具名
            params["tool_params"] = tool_params.strip()   # 保存工具参数
            content = tool_params.strip()             # 内容为参数

        elif action_type == "navigate_l3":           # 如果是导航到L3
            # (导航到工具: 工具名)                     # 注释：格式说明
            tool_id = groups[0] if len(groups) > 0 else ""   # 获取工具ID
            params["tool_id"] = tool_id.strip()       # 保存工具ID
            content = f"导航到工具: {tool_id}"         # 构建内容

        elif action_type == "understanding_summary":   # 如果是提交理解摘要
            # (提交理解摘要: 内容)                     # 注释：格式说明
            summary = groups[0] if len(groups) > 0 else ""   # 获取摘要
            params["summary"] = summary.strip()       # 保存摘要
            content = summary.strip()                 # 内容为摘要

        elif action_type in ["voice_speak", "show_notification", "update_status"]:   # 单参数标记
            # 单参数标记                               # 注释：单参数处理
            content = groups[0] if len(groups) > 0 else ""   # 获取内容
            params["text"] = content.strip()          # 保存文本

        else:                                        # 默认处理
            # 默认处理: 单内容参数                     # 注释：默认处理
            content = groups[0] if len(groups) > 0 else ""   # 获取内容
            params["text"] = content.strip()          # 保存文本

        return ParsedAction(                         # 返回ParsedAction对象
            action_type=action_type,                  # 动作类型
            content=content.strip(),                  # 内容
            params=params,                            # 参数
            raw_match=match.group(0),                 # 原始匹配文本
            position=match.start(),                   # 起始位置
            confidence=1.0                            # 置信度
        )

    def has_actions(self, ai_response: str) -> bool:   # 定义检查是否包含动作的方法
        """
        快速检查是否包含任何标记动作

        Args:
            ai_response: AI响应文本

        Returns:
            是否包含标记动作
        """
        return len(self.parse(ai_response)) > 0      # 解析并检查数量

    def get_action_types(self, ai_response: str) -> list[str]:   # 定义获取动作类型的方法
        """
        获取响应中包含的所有动作类型

        Args:
            ai_response: AI响应文本

        Returns:
            动作类型列表（去重）
        """
        actions = self.parse(ai_response)            # 解析获取动作列表
        return list(dict.fromkeys([a.action_type for a in actions]))   # 去重后返回


class ActionDispatcher:                          # 定义动作异步分发器类
    """
    动作异步分发器 (Action Dispatcher)

    职责：
    - 异步分发所有解析出的动作
    - 管理动作处理器
    - 协调语音系统、提示词导航器、工具系统

    使用示例:
        >>> dispatcher = ActionDispatcher()
        >>> await dispatcher.dispatch(actions, context={
        ...     "voice_processor": voice,
        ...     "prompt_navigator": navigator,
        ...     "websocket": ws
        ... })
    """

    def __init__(self):                          # 初始化方法
        # 内置处理器映射                           # 注释：内置处理器
        self.handlers: dict[str, Callable[[ParsedAction, dict], Awaitable[None]]] = {   # 处理器字典
            "call_user": self._handle_call_user,   # 呼叫用户处理器
            "find_tool": self._handle_find_tool,   # 查找工具处理器
            "tool_call": self._handle_tool_call,   # 工具调用处理器
            "evolution_reflection": self._handle_reflection,   # 反思处理器
            "world_model": self._handle_world_model,   # 世界模型处理器
            "vision_analysis": self._handle_vision,   # 视觉分析处理器
            "understanding_summary": self._handle_summary,   # 摘要处理器
            "resume_execution": self._handle_resume,   # 恢复执行处理器
            "navigate_l1": self._handle_navigate_l1,   # 导航L1处理器
            "navigate_l2": self._handle_navigate_l2,   # 导航L2处理器
            "navigate_l3": self._handle_navigate_l3,   # 导航L3处理器
            "voice_speak": self._handle_voice_speak,   # 语音播报处理器
            "voice_stop": self._handle_voice_stop,   # 停止语音处理器
            "show_notification": self._handle_notification,   # 显示通知处理器
            "update_status": self._handle_status_update,   # 更新状态处理器
        }
        # 自定义处理器（可由外部注册）               # 注释：自定义处理器
        self.custom_handlers: dict[str, Callable] = {}   # 自定义处理器字典
        logger.info("ActionDispatcher 初始化完成")   # 记录日志

    def register_handler(self, action_type: str,
                        handler: Callable[[ParsedAction, dict], Awaitable[None]]):   # 定义注册处理器的方法
        """
        注册自定义动作处理器

        Args:
            action_type: 动作类型
            handler: 异步处理函数

        Example:
            >>> async def my_handler(action, context):
            ...     print(f"处理: {action.content}")
            >>> dispatcher.register_handler("my_action", my_handler)
        """
        self.custom_handlers[action_type] = handler   # 保存到自定义处理器字典
        logger.debug(f"注册自定义处理器: {action_type}")   # 记录日志

    async def dispatch(self, actions: list[ParsedAction], context: dict[str, Any]):   # 定义分发方法
        """
        异步分发所有动作

        并行执行所有动作处理器，等待全部完成

        Args:
            actions: 解析出的动作列表
            context: 执行上下文，包含 voice_processor, prompt_navigator 等

        Returns:
            执行结果列表
        """
        if not actions:                              # 如果动作列表为空
            return []                                # 返回空列表

        tasks = []                                   # 初始化任务列表
        task_info = []                               # 用于记录哪个任务对应哪个动作

        for action in actions:                       # 遍历所有动作
            # 优先使用自定义处理器                     # 注释：处理器选择优先级
            handler = self.custom_handlers.get(action.action_type)   # 查找自定义处理器
            if not handler:                          # 如果没有自定义处理器
                handler = self.handlers.get(action.action_type)   # 使用内置处理器

            if handler:                              # 如果找到处理器
                task = asyncio.create_task(          # 创建异步任务
                    self._execute_handler(handler, action, context),   # 执行处理器
                    name=f"action_{action.action_type}"   # 任务名称
                )
                tasks.append(task)                   # 添加到任务列表
                task_info.append(action.action_type)   # 记录动作类型
            else:                                    # 未找到处理器
                logger.warning(f"未找到动作处理器: {action.action_type}")   # 记录警告

        if not tasks:                                # 如果没有任务
            return []                                # 返回空列表

        logger.info(f"开始分发 {len(tasks)} 个动作: {task_info}")   # 记录日志

        # 等待所有任务完成，捕获异常但不中断           # 注释：任务等待策略
        results = await asyncio.gather(*tasks, return_exceptions=True)   # 并行执行

        # 处理结果和异常                             # 注释：结果处理
        for _i, (action_type, result) in enumerate(zip(task_info, results, strict=False)):   # 遍历结果
            if isinstance(result, Exception):        # 如果是异常
                logger.error(f"动作执行失败 [{action_type}]: {result}")   # 记录错误
            else:                                    # 执行成功
                logger.debug(f"动作执行成功 [{action_type}]")   # 记录调试

        return results                               # 返回结果列表

    async def dispatch_single(self, action: ParsedAction, context: dict[str, Any]):   # 定义分发单个动作的方法
        """
        分发单个动作

        Args:
            action: 单个解析动作
            context: 执行上下文

        Returns:
            执行结果
        """
        handler = self.custom_handlers.get(action.action_type) or \
                  self.handlers.get(action.action_type)   # 查找处理器

        if not handler:                              # 未找到处理器
            logger.warning(f"未找到动作处理器: {action.action_type}")   # 记录警告
            return None                              # 返回None

        return await self._execute_handler(handler, action, context)   # 执行并返回结果

    async def _execute_handler(self, handler, action: ParsedAction, context: dict):   # 定义执行处理器的私有方法
        """执行处理器并捕获异常"""                   # 方法文档字符串
        try:                                         # 异常处理块
            return await handler(action, context)    # 执行处理器
        except Exception as e:                       # 捕获异常
            logger.error(f"处理器异常 [{action.action_type}]: {e}")   # 记录错误
            raise                                    # 重新抛出

    # ==================== 内置处理器 ====================   # 注释：内置处理器区域

    async def _handle_call_user(self, action: ParsedAction, context: dict):   # 定义呼叫用户处理器
        """
        处理用户呼叫

        - 语音播报
        - 前端显示通知
        """
        voice_text = action.content                  # 获取语音文本

        # 1. 语音播报                                # 注释：步骤1
        voice_processor = context.get("voice_processor")   # 获取语音处理器
        if voice_processor:                          # 如果存在
            try:                                     # 异常处理
                await voice_processor.speak(voice_text)   # 语音播报
                logger.debug(f"语音播报: {voice_text[:50]}...")   # 记录日志
            except Exception as e:                   # 播报失败
                logger.error(f"语音播报失败: {e}")   # 记录错误

        # 2. 前端WebSocket通知                       # 注释：步骤2
        websocket = context.get("websocket")         # 获取WebSocket
        if websocket:                                # 如果存在
            try:                                     # 异常处理
                await _safe_send_json(websocket, {          # 发送JSON消息
                    "type": "call_user",             # 消息类型
                    "message": voice_text,           # 消息内容
                    "timestamp": asyncio.get_event_loop().time()   # 时间戳
                })
            except Exception as e:                   # 发送失败
                logger.error(f"WebSocket发送失败: {e}")   # 记录错误

        # 3. 系统通知                                # 注释：步骤3
        notification_mgr = context.get("notification_manager")   # 获取通知管理器
        if notification_mgr:                         # 如果存在
            await notification_mgr.show(f"AI请求: {voice_text}")   # 显示通知

    async def _handle_find_tool(self, action: ParsedAction, context: dict):   # 定义查找工具处理器
        """
        处理工具查找

        - 触发L2导航（工具手册）
        - 语音反馈
        """
        # 1. 触发L2导航                              # 注释：步骤1
        navigator = context.get("prompt_navigator")   # 获取导航器
        if navigator:                                # 如果存在
            try:                                     # 异常处理
                await navigator.navigate_to_l2()     # 导航到L2
                logger.debug("导航到L2（工具手册）")   # 记录日志
            except Exception as e:                   # 导航失败
                logger.error(f"导航失败: {e}")       # 记录错误

        # 2. 语音反馈                                # 注释：步骤2
        voice_processor = context.get("voice_processor")   # 获取语音处理器
        if voice_processor:                          # 如果存在
            await voice_processor.speak(SystemAnnouncements.QUERYING)   # 语音播报

        # 3. 发送查找请求到后端                      # 注释：步骤3
        query = action.content or action.params.get("text", "")   # 获取查询内容
        backend = context.get("backend_client")      # 获取后端客户端
        if backend and query:                        # 如果存在且查询不为空
            try:                                     # 异常处理
                await backend.search_tools(query)    # 搜索工具
            except Exception as e:                   # 搜索失败
                logger.error(f"工具搜索失败: {e}")   # 记录错误

    async def _handle_tool_call(self, action: ParsedAction, context: dict):   # 定义工具调用处理器
        """
        处理工具调用

        - 调用指定工具
        - 传递参数
        """
        tool_name = action.params.get("tool_name", "")   # 获取工具名
        tool_params = action.params.get("tool_params", "")   # 获取工具参数

        logger.info(f"工具调用: {tool_name}({tool_params})")   # 记录日志

        # 获取工具管理器                             # 注释：获取工具管理器
        tool_manager = context.get("tool_manager")   # 获取工具管理器
        if tool_manager:                             # 如果存在
            try:                                     # 异常处理
                result = await tool_manager.execute_tool(tool_name, tool_params)   # 执行工具

                # 发送结果到前端                       # 注释：发送结果
                websocket = context.get("websocket")   # 获取WebSocket
                if websocket:                        # 如果存在
                    await _safe_send_json(websocket, {      # 发送JSON消息
                        "type": "tool_result",       # 消息类型
                        "tool": tool_name,           # 工具名
                        "result": result             # 执行结果
                    })
            except Exception as e:                   # 执行失败
                logger.error(f"工具调用失败 [{tool_name}]: {e}")   # 记录错误

                # 发送错误到前端                       # 注释：发送错误
                websocket = context.get("websocket")   # 获取WebSocket
                if websocket:                        # 如果存在
                    await _safe_send_json(websocket, {      # 发送JSON消息
                        "type": "tool_error",        # 消息类型
                        "tool": tool_name,           # 工具名
                        "error": str(e)              # 错误信息
                    })

    async def _handle_reflection(self, action: ParsedAction, context: dict):   # 定义反思处理器
        """
        处理进化反思

        - 记录反思内容到进化模块
        - 可选：触发模型微调流程
        """
        reflection_content = action.content          # 获取反思内容

        # 获取进化管理器                             # 注释：获取进化管理器
        evolution_mgr = context.get("evolution_manager")   # 获取进化管理器
        if evolution_mgr:                            # 如果存在
            try:                                     # 异常处理
                await evolution_mgr.record_reflection(reflection_content)   # 记录反思
                logger.debug(f"记录反思: {reflection_content[:100]}...")   # 记录日志
            except Exception as e:                   # 记录失败
                logger.error(f"反思记录失败: {e}")   # 记录错误

    async def _handle_world_model(self, action: ParsedAction, context: dict):   # 定义世界模型处理器
        """
        处理世界模型更新

        - 更新用户偏好
        - 更新环境状态
        """
        model_update = action.content                # 获取模型更新内容

        # 获取世界模型管理器                         # 注释：获取世界模型管理器
        world_model = context.get("world_model")     # 获取世界模型
        if world_model:                              # 如果存在
            try:                                     # 异常处理
                await world_model.update_from_text(model_update)   # 更新模型
                logger.debug(f"世界模型更新: {model_update[:100]}...")   # 记录日志
            except Exception as e:                   # 更新失败
                logger.error(f"世界模型更新失败: {e}")   # 记录错误

    async def _handle_vision(self, action: ParsedAction, context: dict):   # 定义视觉分析处理器
        """
        处理视觉分析结果

        - 记录视觉分析
        - 触发后续动作（如需要）
        """
        analysis = action.content                    # 获取分析结果

        # 发送视觉分析到前端                         # 注释：发送到前端
        websocket = context.get("websocket")         # 获取WebSocket
        if websocket:                                # 如果存在
            try:                                     # 异常处理
                await _safe_send_json(websocket, {          # 发送JSON消息
                    "type": "vision_analysis",       # 消息类型
                    "analysis": analysis             # 分析结果
                })
            except Exception as e:                   # 发送失败
                logger.error(f"视觉分析发送失败: {e}")   # 记录错误

        # 可选：语音播报简要结果                     # 注释：语音播报
        voice_processor = context.get("voice_processor")   # 获取语音处理器
        if voice_processor and len(analysis) < 100:   # 如果存在且内容较短
            await voice_processor.speak(analysis)    # 语音播报

    async def _handle_summary(self, action: ParsedAction, context: dict):   # 定义摘要处理器
        """
        处理理解摘要（长任务暂停确认）

        - 显示摘要给用用户
        - 等待用户确认
        - 暂停任务执行
        """
        summary = action.params.get("summary", action.content)   # 获取摘要

        logger.info(f"长任务暂停，等待确认: {summary[:100]}...")   # 记录日志

        # 1. 发送到前端显示确认对话框                  # 注释：步骤1
        websocket = context.get("websocket")         # 获取WebSocket
        if websocket:                                # 如果存在
            try:                                     # 异常处理
                await _safe_send_json(websocket, {          # 发送JSON消息
                    "type": "pause_for_confirmation",   # 消息类型
                    "summary": summary,              # 摘要内容
                    "actions": ["确认继续", "修改需求", "取消任务"]   # 可选操作
                })
            except Exception as e:                   # 发送失败
                logger.error(f"确认请求发送失败: {e}")   # 记录错误

        # 2. 语音播报摘要                            # 注释：步骤2
        voice_processor = context.get("voice_processor")   # 获取语音处理器
        if voice_processor:                          # 如果存在
            await voice_processor.speak(f"请确认理解是否正确: {summary[:200]}")   # 播报

        # 3. 设置任务暂停状态                        # 注释：步骤3
        task_manager = context.get("task_manager")   # 获取任务管理器
        if task_manager:                             # 如果存在
            await task_manager.pause_current(summary)   # 暂停当前任务

    async def _handle_resume(self, action: ParsedAction, context: dict):   # 定义恢复执行处理器
        """
        处理恢复执行

        - 恢复暂停的任务
        """
        logger.info("恢复任务执行")                  # 记录日志

        task_manager = context.get("task_manager")   # 获取任务管理器
        if task_manager:                             # 如果存在
            try:                                     # 异常处理
                await task_manager.resume_current()   # 恢复当前任务
            except Exception as e:                   # 恢复失败
                logger.error(f"任务恢复失败: {e}")   # 记录错误

        # 通知前端                                   # 注释：通知前端
        websocket = context.get("websocket")         # 获取WebSocket
        if websocket:                                # 如果存在
            await _safe_send_json(websocket, {              # 发送JSON消息
                "type": "task_resumed"               # 消息类型
            })

    async def _handle_navigate_l1(self, action: ParsedAction, context: dict):   # 定义导航L1处理器
        """导航到首页 (L1)"""                       # 方法文档字符串
        navigator = context.get("prompt_navigator")   # 获取导航器
        if navigator:                                # 如果存在
            try:                                     # 异常处理
                await navigator.navigate_to_l1()     # 导航到L1
                logger.debug("导航到L1（首页）")       # 记录日志
            except Exception as e:                   # 导航失败
                logger.error(f"导航到L1失败: {e}")   # 记录错误

    async def _handle_navigate_l2(self, action: ParsedAction, context: dict):   # 定义导航L2处理器
        """导航到手册 (L2)"""                       # 方法文档字符串
        navigator = context.get("prompt_navigator")   # 获取导航器
        if navigator:                                # 如果存在
            try:                                     # 异常处理
                await navigator.navigate_to_l2()     # 导航到L2
                logger.debug("导航到L2（工具手册）")   # 记录日志
            except Exception as e:                   # 导航失败
                logger.error(f"导航到L2失败: {e}")   # 记录错误

    async def _handle_navigate_l3(self, action: ParsedAction, context: dict):   # 定义导航L3处理器
        """导航到具体工具 (L3)"""                   # 方法文档字符串
        tool_id = action.params.get("tool_id", "")   # 获取工具ID
        navigator = context.get("prompt_navigator")   # 获取导航器
        if navigator and tool_id:                    # 如果存在且工具ID不为空
            try:                                     # 异常处理
                await navigator.navigate_to_l3(tool_id)   # 导航到L3
                logger.debug(f"导航到L3（工具: {tool_id}）")   # 记录日志
            except Exception as e:                   # 导航失败
                logger.error(f"导航到L3失败: {e}")   # 记录错误

    async def _handle_voice_speak(self, action: ParsedAction, context: dict):   # 定义语音播报处理器
        """处理语音播报指令"""                     # 方法文档字符串
        text = action.params.get("text", action.content)   # 获取文本
        voice_processor = context.get("voice_processor")   # 获取语音处理器
        if voice_processor and text:                 # 如果存在且文本不为空
            try:                                     # 异常处理
                await voice_processor.speak(text)    # 语音播报
            except Exception as e:                   # 播报失败
                logger.error(f"语音播报失败: {e}")   # 记录错误

    async def _handle_voice_stop(self, action: ParsedAction, context: dict):   # 定义停止语音处理器
        """处理停止语音指令"""                     # 方法文档字符串
        voice_processor = context.get("voice_processor")   # 获取语音处理器
        if voice_processor:                          # 如果存在
            try:                                     # 异常处理
                await voice_processor.stop()         # 停止语音
            except Exception as e:                   # 停止失败
                logger.error(f"停止语音失败: {e}")   # 记录错误

    async def _handle_notification(self, action: ParsedAction, context: dict):   # 定义显示通知处理器
        """处理显示通知指令"""                     # 方法文档字符串
        text = action.params.get("text", action.content)   # 获取文本
        notification_mgr = context.get("notification_manager")   # 获取通知管理器
        if notification_mgr and text:                # 如果存在且文本不为空
            try:                                     # 异常处理
                await notification_mgr.show(text)    # 显示通知
            except Exception as e:                   # 显示失败
                logger.error(f"显示通知失败: {e}")   # 记录错误

    async def _handle_status_update(self, action: ParsedAction, context: dict):   # 定义更新状态处理器
        """处理状态更新指令"""                     # 方法文档字符串
        text = action.params.get("text", action.content)   # 获取文本
        websocket = context.get("websocket")         # 获取WebSocket
        if websocket and text:                       # 如果存在且文本不为空
            try:                                     # 异常处理
                await _safe_send_json(websocket, {          # 发送JSON消息
                    "type": "status_update",         # 消息类型
                    "status": text                   # 状态文本
                })
            except Exception as e:                   # 更新失败
                logger.error(f"状态更新失败: {e}")   # 记录错误


# =============================================================================
# 层级切换命令统一 (P2-005)
# =============================================================================

# 统一定义所有层级切换命令
LAYER_COMMANDS = {
    'to_l1': ['首页', 'home', '回到首页', '返回首页', 'main'],
    'to_l2': ['手册', 'manual', '工具手册', '查看手册', '目录'],
    'to_l3': ['详情', 'detail', '查看详情', '详情页'],
    'back': ['返回', 'back', '上一级', '后退', '返回上级', '..'],
    'help': ['帮助', 'help', '说明', '?', 'h']
}


def parse_layer_command(user_input: str) -> str | None:
    """
    解析层级切换命令，返回动作或None

    统一的层级命令解析器，支持中英文命令别名。

    Args:
        user_input: 用户输入文本

    Returns:
        动作字符串(to_l1/to_l2/to_l3/back/help) 或 None

    Examples:
        >>> parse_layer_command("首页")
        'to_l1'
        >>> parse_layer_command("back")
        'back'
        >>> parse_layer_command("手册")
        'to_l2'
        >>> parse_layer_command("你好")
        None
    """
    if not user_input or not isinstance(user_input, str):
        return None

    user_input = user_input.strip().lower()

    for action, commands in LAYER_COMMANDS.items():
        if user_input in [c.lower() for c in commands]:
            return action
    return None


def is_layer_command(user_input: str) -> bool:
    """
    检查输入是否为层级切换命令

    Args:
        user_input: 用户输入文本

    Returns:
        是否为层级命令
    """
    return parse_layer_command(user_input) is not None


def get_layer_command_help() -> str:
    """
    获取层级命令帮助文本

    Returns:
        帮助文本
    """
    return """
【层级导航命令】

首页导航:
  首页, home, 回到首页, 返回首页, main
  → 返回L1首页

手册导航:
  手册, manual, 工具手册, 查看手册, 目录
  → 进入L2工具手册

详情导航:
  详情, detail, 查看详情, 详情页
  → 进入L3工具详情

返回操作:
  返回, back, 上一级, 后退, 返回上级, ..
  → 返回上一层级

帮助:
  帮助, help, 说明, ?, h
  → 显示帮助信息
"""


# =============================================================================
# 便捷函数和单例
# =============================================================================

_precise_capture_parser: PreciseCaptureParser | None = None   # 模块级变量：解析器单例
_action_dispatcher: ActionDispatcher | None = None   # 模块级变量：分发器单例


def get_precise_capture_parser() -> PreciseCaptureParser:   # 定义获取解析器的函数
    """获取精准抓取解析器单例"""                   # 函数文档字符串
    global _precise_capture_parser                 # 声明全局变量
    if _precise_capture_parser is None:            # 如果单例不存在
        _precise_capture_parser = PreciseCaptureParser()   # 创建实例
    return _precise_capture_parser                 # 返回单例


def get_action_dispatcher() -> ActionDispatcher:   # 定义获取分发器的函数
    """获取动作分发器单例"""                     # 函数文档字符串
    global _action_dispatcher                      # 声明全局变量
    if _action_dispatcher is None:                 # 如果单例不存在
        _action_dispatcher = ActionDispatcher()    # 创建实例
    return _action_dispatcher                      # 返回单例


async def parse_and_dispatch(ai_response: str, context: dict[str, Any]) -> tuple[list[ParsedAction], str]:   # 定义便捷函数
    """
    便捷函数：解析并分发AI响应

    Args:
        ai_response: AI原始响应
        context: 执行上下文

    Returns:
        (动作列表, 清理后的文本)

    Example:
        >>> actions, clean = await parse_and_dispatch(ai_response, {
        ...     "voice_processor": voice,
        ...     "websocket": ws
        ... })
    """
    parser = get_precise_capture_parser()        # 获取解析器
    dispatcher = get_action_dispatcher()         # 获取分发器

    actions, clean_text = parser.parse_and_clean(ai_response)   # 解析并清理

    if actions:                                  # 如果有动作
        await dispatcher.dispatch(actions, context)   # 分发执行

    return actions, clean_text                   # 返回结果


# =============================================================================
# 原有命令解析器代码（保持不变）
# =============================================================================


class CommandType(Enum):                         # 定义命令类型枚举
    """命令类型枚举"""                           # 类文档字符串
    UNKNOWN = "unknown"                          # 未知命令
    # 分层导航命令                               # 注释：分层导航命令
    QUERY_TOOL_LIST = "query_tool_list"          # 查看分类工具列表
    QUERY_TOOL_DETAIL = "query_tool_detail"      # 查看工具详情
    BACK_TO_PREV = "back_to_prev"                # 返回上一层
    NAVIGATE_TO_L1 = "navigate_to_l1"            # 导航到首页(L1)
    NAVIGATE_TO_L2 = "navigate_to_l2"            # 导航到手册(L2)
    # 系统命令                                   # 注释：系统命令
    HELP = "help"                                # 帮助
    EXIT = "exit"                                # 退出
    CLEAR = "clear"                              # 清空


@dataclass                                       # 数据类装饰器
class ParsedCommand:                             # 定义解析后的命令数据类
    """解析后的命令结构"""                       # 类文档字符串
    command_type: CommandType                    # 实例属性：命令类型
    raw_input: str                               # 实例属性：原始输入
    params: dict[str, Any] = field(default_factory=dict)   # 实例属性：参数，默认为空字典
    confidence: float = 0.0                      # 实例属性：置信度，默认为0
    is_strict_match: bool = True                 # 实例属性：是否为严格匹配，默认为True


class CommandParser:                             # 定义命令解析器类
    """
    专门化的命令解析器

    特点：
    1. 严格命令匹配，避免自然语言误触发
    2. 支持正则和精确匹配两种模式
    3. 分层导航命令支持
    """

    # 命令模式定义 (正则表达式)                    # 类属性注释
    COMMAND_PATTERNS = {                         # 命令模式字典
        # 分层导航命令                             # 注释：分层导航命令
        CommandType.QUERY_TOOL_LIST: [           # 查询工具列表命令模式
            r'^查看\s*([\w\u4e00-\u9fa5]+?)\s*工具\s*$',  # "查看输入类工具"
            r'^\s*list\s+tools\s+(\w+)\s*$',      # "list tools input"
            r'^\s*tools\s+in\s+(\w+)\s*$',        # "tools in input"
        ],
        CommandType.QUERY_TOOL_DETAIL: [         # 查询工具详情命令模式
            r'^查看工具详情\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*$',  # "查看工具详情 keyboard_input"
            r'^\s*tool\s+info\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*$',  # "tool info keyboard_input"
            r'^\s*detail\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*$',   # "detail keyboard_input"
        ],
        CommandType.BACK_TO_PREV: [              # 返回上一层命令模式
            r'^\s*返回\s*$',                      # "返回"
            r'^\s*返回上一层\s*$',                # "返回上一层"
            r'^\s*返回分类\s*$',                  # "返回分类"
            r'^\s*back\s*$',                      # "back"
            r'^\s*back\s+to\s+prev\s*$',          # "back to prev"
            r'^\s*\.{2,}\s*$',                    # ".."
            r'^\s*首页\s*$',                      # "首页" -> L3直接回L1
            r'^\s*home\s*$',                      # "home" -> L3直接回L1
        ],
        # 系统命令                                 # 注释：系统命令
        CommandType.HELP: [                      # 帮助命令模式
            r'^\s*帮助\s*$',
            r'^\s*help\s*$',
            r'^\s*\?\s*$',
        ],
        CommandType.EXIT: [                      # 退出命令模式
            r'^\s*退出\s*$',
            r'^\s*exit\s*$',
            r'^\s*quit\s*$',
            r'^\s*bye\s*$',
        ],
        CommandType.CLEAR: [                     # 清空命令模式
            r'^\s*清空\s*$',
            r'^\s*clear\s*$',
            r'^\s*cls\s*$',
        ],
    }

    # 精确匹配命令（优先级最高）                   # 类属性注释
    EXACT_COMMANDS: dict[str, tuple[CommandType, dict[str, Any]]] = {   # 精确命令字典
        # 返回命令                                 # 注释：返回命令
        "返回": (CommandType.BACK_TO_PREV, {}),   # 返回
        "返回上一层": (CommandType.BACK_TO_PREV, {}),   # 返回上一层
        "返回分类": (CommandType.BACK_TO_PREV, {}),   # 返回分类
        "back": (CommandType.BACK_TO_PREV, {}),   # back
        "b": (CommandType.BACK_TO_PREV, {}),      # b
        "..": (CommandType.BACK_TO_PREV, {}),     # ..
        # L3直接回L1                               # 注释：L3直接回L1
        "首页": (CommandType.NAVIGATE_TO_L1, {}),   # 首页
        "home": (CommandType.NAVIGATE_TO_L1, {}),   # home
        # L2导航（手册）                             # 注释：导航到L2
        "手册": (CommandType.NAVIGATE_TO_L2, {}),   # 手册
        "manual": (CommandType.NAVIGATE_TO_L2, {}),   # manual
        "工具手册": (CommandType.NAVIGATE_TO_L2, {}),   # 工具手册
        "查看手册": (CommandType.NAVIGATE_TO_L2, {}),   # 查看手册
        "目录": (CommandType.NAVIGATE_TO_L2, {}),   # 目录
        # 帮助命令                                 # 注释：帮助命令
        "帮助": (CommandType.HELP, {}),           # 帮助
        "help": (CommandType.HELP, {}),           # help
        "?": (CommandType.HELP, {}),              # ?
        "h": (CommandType.HELP, {}),              # h
        # 退出命令                                 # 注释：退出命令
        "退出": (CommandType.EXIT, {}),           # 退出
        "exit": (CommandType.EXIT, {}),           # exit
        "quit": (CommandType.EXIT, {}),           # quit
        "q": (CommandType.EXIT, {}),              # q
        # 清空命令                                 # 注释：清空命令
        "清空": (CommandType.CLEAR, {}),          # 清空
        "clear": (CommandType.CLEAR, {}),         # clear
        "cls": (CommandType.CLEAR, {}),           # cls
    }

    def __init__(self):                          # 初始化方法
        # 预编译正则表达式以提高性能                 # 注释：预编译正则
        self._compiled_patterns: dict[CommandType, list[re.Pattern]] = {}   # 编译后的模式字典
        self._compile_patterns()                   # 编译所有模式

    def _compile_patterns(self):                   # 定义编译模式的私有方法
        """预编译所有正则表达式"""                   # 方法文档字符串
        for cmd_type, patterns in self.COMMAND_PATTERNS.items():   # 遍历所有命令类型
            self._compiled_patterns[cmd_type] = [   # 编译该类型的所有模式
                re.compile(p, re.IGNORECASE | re.UNICODE) for p in patterns   # 忽略大小写，支持Unicode
            ]

    def parse(self, text: str) -> ParsedCommand | None:   # 定义解析方法
        """
        解析输入文本为命令

        解析优先级：
        1. 精确匹配（最高优先级）
        2. 正则模式匹配
        3. 不是命令 -> 返回 None

        Args:
            text: 输入文本

        Returns:
            ParsedCommand 或 None（如果不是命令）
        """
        if not text or not isinstance(text, str):   # 检查输入有效性
            return None                              # 无效输入返回None

        text = text.strip()                          # 去除首尾空白
        if not text:                                 # 如果为空
            return None                              # 返回None

        # 1. 尝试精确匹配（最高优先级）                # 注释：步骤1
        exact_result = self._try_exact_match(text)   # 尝试精确匹配
        if exact_result:                             # 如果匹配成功
            logger.debug(f"命令精确匹配: {text} -> {exact_result.command_type.value}")   # 记录日志
            return exact_result                      # 返回结果

        # 2. 尝试正则模式匹配                          # 注释：步骤2
        pattern_result = self._try_pattern_match(text)   # 尝试模式匹配
        if pattern_result:                           # 如果匹配成功
            logger.debug(f"命令模式匹配: {text} -> {pattern_result.command_type.value}")   # 记录日志
            return pattern_result                    # 返回结果

        # 3. 不是命令                                  # 注释：不是命令
        return None                                  # 返回None

    def _try_exact_match(self, text: str) -> ParsedCommand | None:   # 定义精确匹配的私有方法
        """尝试精确匹配命令"""                       # 方法文档字符串
        # 完全匹配                                   # 注释：完全匹配
        if text in self.EXACT_COMMANDS:              # 如果在精确命令字典中
            cmd_type, params = self.EXACT_COMMANDS[text]   # 获取命令类型和参数
            return ParsedCommand(                    # 返回ParsedCommand
                command_type=cmd_type,                # 命令类型
                raw_input=text,                       # 原始输入
                params=params.copy(),                 # 复制参数
                confidence=1.0,                       # 置信度1.0
                is_strict_match=True                  # 严格匹配
            )

        # 小写匹配（不区分大小写）                     # 注释：小写匹配
        text_lower = text.lower()                    # 转为小写
        if text_lower in self.EXACT_COMMANDS:        # 如果在精确命令字典中
            cmd_type, params = self.EXACT_COMMANDS[text_lower]   # 获取命令类型和参数
            return ParsedCommand(                    # 返回ParsedCommand
                command_type=cmd_type,                # 命令类型
                raw_input=text,                       # 原始输入
                params=params.copy(),                 # 复制参数
                confidence=1.0,                       # 置信度1.0
                is_strict_match=True                  # 严格匹配
            )

        return None                                  # 未匹配返回None

    def _try_pattern_match(self, text: str) -> ParsedCommand | None:   # 定义模式匹配的私有方法
        """尝试正则模式匹配命令"""                   # 方法文档字符串
        for cmd_type, patterns in self._compiled_patterns.items():   # 遍历所有编译后的模式
            for pattern in patterns:                 # 遍历该类型的所有模式
                match = pattern.match(text)          # 尝试匹配
                if match:                            # 如果匹配成功
                    params = self._extract_params(cmd_type, match, text)   # 提取参数
                    return ParsedCommand(            # 返回ParsedCommand
                        command_type=cmd_type,        # 命令类型
                        raw_input=text,               # 原始输入
                        params=params,                # 参数
                        confidence=0.95,              # 置信度0.95
                        is_strict_match=True          # 严格匹配
                    )
        return None                                  # 未匹配返回None

    def _extract_params(self, cmd_type: CommandType,
                        match: re.Match,
                        text: str) -> dict[str, Any]:   # 定义提取参数的私有方法
        """根据命令类型提取参数"""                   # 方法文档字符串
        params = {}                                  # 初始化参数字典
        groups = match.groups()                      # 获取匹配组

        if cmd_type == CommandType.QUERY_TOOL_LIST:   # 如果是查询工具列表
            # 提取分类名称                           # 注释：提取分类
            if groups:                               # 如果有匹配组
                params["category"] = groups[0].strip()   # 保存分类名称

        elif cmd_type == CommandType.QUERY_TOOL_DETAIL:   # 如果是查询工具详情
            # 提取工具ID                             # 注释：提取工具ID
            if groups:                               # 如果有匹配组
                params["tool_id"] = groups[0].strip()   # 保存工具ID

        elif cmd_type == CommandType.BACK_TO_PREV:   # 如果是返回上一层
            # 检查是否是返回首页                     # 注释：检查返回首页
            text_lower = text.lower().strip()        # 转为小写
            if text_lower in ["首页", "home"]:       # 如果是首页命令
                params["target"] = "home"            # 设置目标为home
            else:                                    # 否则
                params["target"] = "prev"            # 设置目标为prev

        return params                                # 返回参数字典

    def is_command(self, text: str) -> bool:         # 定义检查是否为命令的方法
        """                                         # 方法文档字符串开始
        快速检查文本是否为命令（不返回详细结果）       # 方法功能

        用于优先级判断：如果返回 True，则优先作为命令处理   # 用途说明
        """                                         # 方法文档字符串结束
        return self.parse(text) is not None          # 解析并检查是否不为None

    def parse_with_priority(self, text: str) -> tuple[ParsedCommand | None, str]:   # 定义带优先级的解析方法
        """                                         # 方法文档字符串开始
        带优先级处理的解析                           # 方法功能

        Returns:                                    # 返回值说明
            (ParsedCommand 或 None, 处理建议)         # 返回元组
            处理建议: "command" | "natural_language" | "ambiguous"   # 建议值
        """                                         # 方法文档字符串结束
        cmd = self.parse(text)                       # 解析命令
        if cmd:                                      # 如果解析成功
            return cmd, "command"                    # 返回命令和建议"command"

        # 检查是否可能是命令但格式不正确               # 注释：检查模糊命令
        if self._looks_like_command(text):           # 如果看起来像命令
            return None, "ambiguous"                 # 返回None和建议"ambiguous"

        return None, "natural_language"              # 返回None和建议"natural_language"

    def _looks_like_command(self, text: str) -> bool:   # 定义检查是否像命令的私有方法
        """检查文本是否看起来像命令（用于模糊匹配提示）"""   # 方法文档字符串
        command_like_prefixes = [                    # 命令样前缀列表
            "查看", "list", "tool", "detail", "返回", "back",
            "帮助", "help", "退出", "exit", "清空", "clear"
        ]
        text_lower = text.lower().strip()            # 转为小写并去除空白
        return any(text_lower.startswith(prefix.lower()) for prefix in command_like_prefixes)                                 # 未匹配返回False

    def get_help_text(self) -> str:                  # 定义获取帮助文本的方法
        """获取帮助文本"""                           # 方法文档字符串
        return """                                   # 返回帮助文本
【可用命令】                                     # 标题

分层导航命令：                                   # 分类标题
  查看 [分类名] 工具    - 查看某分类下的工具列表 (L1→L2)   # 命令1
  查看工具详情 [工具ID] - 查看工具详情 (L2→L3)     # 命令2
  返回 / back / ..      - 返回上一层               # 命令3
  首页 / home           - 直接返回分类列表(L1)     # 命令4

系统命令：                                       # 分类标题
  帮助 / help / ?       - 显示帮助               # 命令5
  清空 / clear / cls    - 清空对话               # 命令6
  退出 / exit / quit    - 退出程序               # 命令7

示例：                                           # 示例标题
  查看输入类工具                                   # 示例1
  查看工具详情 keyboard_input                      # 示例2
  返回      (L3→L2 或 L2→L1)                      # 示例3
  首页      (L3直接→L1)                           # 示例4
"""


class CommandPriorityHandler:                    # 定义命令优先级处理器类
    """                                         # 类文档字符串开始
    命令优先级处理器                             # 类标题

    处理命令与自然语言的优先级关系                 # 类功能
    """                                         # 类文档字符串结束

    def __init__(self):                          # 初始化方法
        self.parser = CommandParser()            # 实例属性：创建命令解析器

    def process_input(self, text: str) -> dict[str, Any]:   # 定义处理输入的方法
        """                                         # 方法文档字符串开始
        处理用户输入，确定是命令还是自然语言         # 方法功能

        Returns:                                    # 返回值说明
            {                                         # 返回字典
                "type": "command" | "natural_language" | "ambiguous",   # 类型
                "command": ParsedCommand or None,     # 命令对象
                "original_text": str,                 # 原始文本
                "suggestion": str  # 给用户建议       # 建议
            }
        """                                         # 方法文档字符串结束
        # 1. 首先尝试解析为命令                      # 注释：步骤1
        cmd = self.parser.parse(text)                # 解析命令
        if cmd:                                      # 如果解析成功
            return {                                 # 返回结果
                "type": "command",                   # 类型为command
                "command": cmd,                      # 命令对象
                "original_text": text,               # 原始文本
                "suggestion": ""                     # 无建议
            }

        # 2. 检查是否是模糊的命令                      # 注释：步骤2
        if self.parser._looks_like_command(text):    # 如果看起来像命令
            return {                                 # 返回结果
                "type": "ambiguous",                 # 类型为ambiguous
                "command": None,                     # 无命令对象
                "original_text": text,               # 原始文本
                "suggestion": f'"{text}" 看起来像命令但格式不正确。可用命令：查看 [分类] 工具、返回、帮助'   # 建议
            }

        # 3. 作为自然语言处理                          # 注释：步骤3
        return {                                     # 返回结果
            "type": "natural_language",              # 类型为natural_language
            "command": None,                         # 无命令对象
            "original_text": text,                   # 原始文本
            "suggestion": ""                         # 无建议
        }


# 全局单例                                       # 注释：全局单例区域
_command_parser: CommandParser | None = None   # 模块级变量：命令解析器单例
_priority_handler: CommandPriorityHandler | None = None   # 模块级变量：优先级处理器单例


def get_command_parser() -> CommandParser:         # 定义获取命令解析器的函数
    """获取命令解析器单例"""                       # 函数文档字符串
    global _command_parser                         # 声明全局变量
    if _command_parser is None:                    # 如果单例不存在
        _command_parser = CommandParser()          # 创建实例
    return _command_parser                         # 返回单例


def get_priority_handler() -> CommandPriorityHandler:   # 定义获取优先级处理器的函数
    """获取优先级处理器单例"""                     # 函数文档字符串
    global _priority_handler                       # 声明全局变量
    if _priority_handler is None:                  # 如果单例不存在
        _priority_handler = CommandPriorityHandler()   # 创建实例
    return _priority_handler                       # 返回单例


def parse_command(text: str) -> ParsedCommand | None:   # 定义解析命令的便捷函数
    """便捷函数：解析命令"""                       # 函数文档字符串
    return get_command_parser().parse(text)        # 调用解析器解析


def is_command(text: str) -> bool:                 # 定义检查是否为命令的便捷函数
    """便捷函数：检查是否为命令"""                 # 函数文档字符串
    return get_command_parser().is_command(text)   # 调用解析器检查


# 测试代码                                       # 注释：测试代码区域
if __name__ == "__main__":                       # 如果是主程序
    import asyncio  # 导入asyncio

    print("=" * 60)                              # 打印分隔线
    print("命令解析器测试 (Command Parser)")       # 打印标题
    print("=" * 60)                              # 打印分隔线

    parser = CommandParser()                     # 创建命令解析器

    test_cases = [                               # 测试用例列表
        # 有效命令                                 # 注释：有效命令
        ("查看输入类工具", True),                  # 测试用例1
        ("查看工具详情 keyboard_input", True),     # 测试用例2
        ("返回", True),                            # 测试用例3
        ("返回上一层", True),                      # 测试用例4
        ("back", True),                            # 测试用例5
        ("..", True),                              # 测试用例6
        ("帮助", True),                            # 测试用例7
        ("help", True),                            # 测试用例8
        ("退出", True),                            # 测试用例9
        ("exit", True),                            # 测试用例10
        # 非命令（自然语言）                         # 注释：非命令
        ("你好", False),                           # 测试用例11
        ("请帮我打开微信", False),                 # 测试用例12
        ("今天天气怎么样", False),                 # 测试用例13
        ("查看一下这个功能", False),               # 测试用例14
        ("", False),                               # 测试用例15
    ]

    print("\n[严格命令解析测试]\n")                # 打印标题
    for text, expected_is_cmd in test_cases:     # 遍历测试用例
        result = parser.parse(text)                # 解析命令
        is_cmd = result is not None                # 检查是否为命令
        status = "OK" if is_cmd == expected_is_cmd else "FAIL"   # 确定状态
        print(f"[{status}] 输入: '{text}'")        # 打印结果
        if result:                                 # 如果有结果
            print(f"   解析为: {result.command_type.value}, 参数: {result.params}")   # 打印详情
        else:                                      # 无结果
            print("   不是命令")                    # 打印说明
        print()                                    # 空行

    # 精准抓取系统测试                             # 注释：精准抓取测试
    print("=" * 60)                              # 打印分隔线
    print("精准抓取系统测试 (Precise-Capture)")     # 打印标题
    print("=" * 60)                              # 打印分隔线

    capture_parser = PreciseCaptureParser()      # 创建精准抓取解析器

    # 测试用例：多标记混合响应                     # 注释：测试用例
    test_responses = [                           # 测试响应列表
        # 测试用例 1: 多标记混合                     # 注释：测试用例1
        """
        我需要截图来查看当前界面。(工具调用: screenshot)
        哦，我看到了一个登录按钮。(视觉分析: 登录界面，包含用户名和密码输入框)
        但是我现在找不到自动登录工具。(呼叫用户) 请问您记得密码吗？
        (查找工具) 我需要查看工具手册中是否有相关工具。
        """,

        # 测试用例 2: 长任务暂停确认                 # 注释：测试用例2
        """
        我将为您完成这个复杂任务，需要多个步骤。
        (提交理解摘要: 任务目标是自动登录系统，步骤包括：1.打开浏览器 2.输入用户名密码 3.点击登录)
        请确认我的理解是否正确。
        """,

        # 测试用例 3: 导航标记                       # 注释：测试用例3
        """
        好的，让我为您查找工具。(导航到手册) 正在进入工具手册页面。
        (查找工具) 搜索自动化相关工具。
        """,

        # 测试用例 4: 进化反思                       # 注释：测试用例4
        """
        任务已完成。(进化反思: 本次任务执行效率可以优化，下次可直接使用快捷键代替鼠标操作)
        (世界模型) 用户偏好已更新：更喜欢使用键盘快捷键。
        """,

        # 测试用例 5: 纯自然语言                     # 注释：测试用例5
        """
        您好！我是您的AI助手，很高兴为您服务。
        请问今天有什么我可以帮助您的吗？
        """,
    ]

    print("\n[标记解析测试]\n")                    # 打印标题

    for i, response in enumerate(test_responses, 1):   # 遍历测试响应
        print(f"--- Test Case {i} ---")            # 打印测试用例编号
        print(f"原始响应: {response[:80]}...")      # 打印原始响应

        # 解析动作                                 # 注释：解析
        actions = capture_parser.parse(response)     # 解析动作
        action_types = [a.action_type for a in actions]   # 获取动作类型

        # 解析并清理                               # 注释：清理
        actions, clean_text = capture_parser.parse_and_clean(response)   # 解析并清理

        print(f"检测到标记: {action_types if action_types else 'None'}")   # 打印检测到的标记
        print(f"清理后文本: {clean_text[:80]}...")   # 打印清理后文本
        print()                                    # 空行

    # 异步分发器测试                               # 注释：分发器测试
    print("=" * 60)                              # 打印分隔线
    print("动作分发器测试 (Action Dispatcher)")     # 打印标题
    print("=" * 60)                              # 打印分隔线

    async def test_dispatcher():                   # 定义异步测试函数
        dispatcher = ActionDispatcher()            # 创建分发器

        # 模拟上下文                               # 注释：模拟上下文
        class MockVoiceProcessor:                  # 模拟语音处理器
            async def speak(self, text):           # 模拟播报
                print(f"  [语音] {text[:50]}...")   # 打印
            async def stop(self):                  # 模拟停止
                print("  [语音] 停止")              # 打印

        class MockNavigator:                       # 模拟导航器
            async def navigate_to_l1(self):        # 模拟导航L1
                print("  [导航] -> L1 (首页)")      # 打印
            async def navigate_to_l2(self):        # 模拟导航L2
                print("  [导航] -> L2 (手册)")      # 打印
            async def navigate_to_l3(self, tool_id):   # 模拟导航L3
                print(f"  [导航] -> L3 (工具: {tool_id})")   # 打印

        class MockWebSocket:                       # 模拟WebSocket
            async def send_json(self, data):       # 模拟发送JSON
                print(f"  [WebSocket] {data['type']}")   # 打印

        context = {                                  # 构建上下文
            "voice_processor": MockVoiceProcessor(),   # 语音处理器
            "prompt_navigator": MockNavigator(),    # 导航器
            "websocket": MockWebSocket(),           # WebSocket
        }

        # 测试多标记同时分发                         # 注释：测试分发
        test_response = """
        (呼叫用户) 请确认操作
        (查找工具) 搜索自动化工具
        (工具调用: screenshot)
        (导航到手册)
        """

        print("\n[异步分发测试]")                  # 打印标题
        print(f"测试响应: {test_response.strip()}")   # 打印测试响应
        print("\n执行结果:")                       # 打印标题

        actions, clean_text = capture_parser.parse_and_clean(test_response)   # 解析并清理
        await dispatcher.dispatch(actions, context)   # 分发执行

        print(f"\n清理后文本: '{clean_text}'")     # 打印清理后文本

    # 【规则7整改】使用new_event_loop替代asyncio.run，避免嵌套问题
    _test_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_test_loop)
    try:
        _test_loop.run_until_complete(test_dispatcher())
    finally:
        _test_loop.close()

    print("\n" + "=" * 60)                       # 打印分隔线
    print("All tests completed!")                  # 打印完成信息
    print("=" * 60)                              # 打印分隔线


# =============================================================================
# 【文件总结性注释】
# =============================================================================
#
# 【文件角色】
# core/command_parser.py 是 SiliconBase V5 项目的 "命令解析器模块"，位于 core 目录下。
#
# 核心定位：
#   - 提供双重解析能力：用户输入命令解析 + AI响应标记解析
#   - 实现严格命令格式匹配，避免自然语言误触发
#   - 支持分层交互命令解析（L1->L2->L3导航）
#   - 提供异步动作分发系统
#
# 主要职责：
#   1. 用户命令解析：解析用户输入的严格格式命令
#   2. AI响应解析：解析AI输出中的功能标记
#   3. 动作分发：异步执行解析出的动作
#   4. 命令优先级处理：区分命令和自然语言
#
# -----------------------------------------------------------------------------
#
# 【两大子系统】
#
# 1. PreciseCapture 系统（AI响应解析）：
#    - PreciseCaptureParser: 解析AI响应中的标记
#    - ActionDispatcher: 异步分发执行动作
#    - 支持的标记类型：
#      * call_user - 呼叫用户
#      * find_tool - 查找工具
#      * tool_call - 工具调用
#      * vision_analysis - 视觉分析
#      * evolution_reflection - 进化反思
#      * world_model - 世界模型
#      * understanding_summary - 理解摘要（暂停确认）
#      * resume_execution - 恢复执行
#      * navigate_l1/l2/l3 - 分层导航
#      * voice_speak/stop - 语音控制
#      * show_notification/update_status - 界面控制
#
# 2. CommandParser 系统（用户输入解析）：
#    - CommandParser: 解析用户输入的命令
#    - CommandPriorityHandler: 处理命令优先级
#    - 支持的命令类型：
#      * QUERY_TOOL_LIST - 查看分类工具列表
#      * QUERY_TOOL_DETAIL - 查看工具详情
#      * BACK_TO_PREV - 返回上一层
#      * HELP - 显示帮助
#      * EXIT - 退出
#      * CLEAR - 清空
#
# -----------------------------------------------------------------------------
#
# 【关联文件】
#
# 1. 依赖的模块（本文件导入）：
#    - core.logger
#      * 提供日志记录功能
#      * 兼容处理：导入失败时使用标准logging
#
# 2. 依赖方（使用本文件）：
#    - core.chat_mode_handler
#      * 使用 CommandParser 解析用户命令
#      * 使用 PreciseCaptureParser 解析AI响应
#
#    - agent_loop / 底座系统
#      * 使用 ActionDispatcher 分发动作
#
# -----------------------------------------------------------------------------
#
# 【解析策略】
#
# 1. 命令解析优先级：
#    - 精确匹配（最高优先级，confidence=1.0）
#    - 正则模式匹配（confidence=0.95）
#    - 不是命令 -> 返回None
#
# 2. 模糊命令检测：
#    - 检查是否以特定前缀开头
#    - 用于给用户格式提示
#
# 3. 标记解析策略：
#    - 使用正则表达式匹配
#    - 支持多标记同时存在
#    - 按位置排序处理
#
# -----------------------------------------------------------------------------
#
# 【达到的效果】
#
# 1. 严格命令匹配：
#    - 避免自然语言误触发命令
#    - 必须严格匹配预定义格式
#    - 中英文命令支持
#
# 2. 分层导航支持：
#    - L1（首页）-> L2（分类）-> L3（工具详情）
#    - 支持返回操作
#    - 支持跨层跳转
#
# 3. 异步动作分发：
#    - 并行执行多个动作
#    - 异常隔离不影响其他动作
#    - 支持自定义处理器注册
#
# 4. 文本清理：
#    - 移除标记保留自然语言
#    - 保持回复流畅性
#
# -----------------------------------------------------------------------------
#
# 【使用示例】
#
# 1. 解析用户命令：
#    from core.intent.command_parser import get_command_parser
#    parser = get_command_parser()
#    cmd = parser.parse("查看输入类工具")
#    if cmd:
#        print(f"命令类型: {cmd.command_type.value}")
#
# 2. 解析AI响应：
#    from core.intent.command_parser import get_precise_capture_parser
#    parser = get_precise_capture_parser()
#    actions = parser.parse("(呼叫用户) 请确认 (工具调用: screenshot)")
#
# 3. 解析并分发：
#    from core.intent.command_parser import parse_and_dispatch
#    actions, clean = await parse_and_dispatch(ai_response, context={
#        "voice_processor": voice,
#        "websocket": ws
#    })
#
# 4. 注册自定义处理器：
#    dispatcher = get_action_dispatcher()
#    dispatcher.register_handler("my_action", my_handler)
#
# -----------------------------------------------------------------------------
#
# 【设计原则】
#
# 1. 严格匹配优先：
#    - 精确匹配优先于正则匹配
#    - 避免自然语言误触发
#
# 2. 可扩展性：
#    - 支持自定义动作处理器
#    - 模式字典可扩展
#
# 3. 异步处理：
#    - 动作并行执行
#    - 不阻塞主流程
#
# 4. 错误隔离：
#    - 单个动作失败不影响其他动作
#    - 详细错误日志
#
# =============================================================================
