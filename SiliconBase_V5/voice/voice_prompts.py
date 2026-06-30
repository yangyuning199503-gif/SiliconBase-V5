#!/usr/bin/env python3
"""
语音播报文本集中管理模块

将分散在后端各处的硬编码语音播报文本统一收敛到此处，
消除重复、便于维护、支持未来国际化。
"""

# ==================== 工具名称映射 ====================
# 用于将英文工具名转换为中文播报名
# S-4 Fix: 合并 intent_handler.py 中的 27 个条目，统一维护
TOOL_NAME_MAP: dict[str, str] = {
    # GUI 自动化工具（来自 intent_handler.py）
    "mouse_click": "鼠标点击",
    "keyboard_input": "键盘输入",
    "click": "点击",
    "type": "输入",
    "scroll": "滚动",
    "drag": "拖拽",
    "screenshot": "截图",
    "double_click": "双击",
    "right_click": "右键点击",
    "move_to": "移动鼠标",
    "get_position": "获取位置",
    "press": "按键",
    "hotkey": "快捷键",
    "wait": "等待",
    "screen_ocr": "屏幕识别",
    "launch_app": "启动应用",
    "open_app": "打开应用",
    # 文件与系统工具（来自 intent_handler.py）
    "file_read": "读取文件",
    "file_write": "写入文件",
    "copy": "复制",
    "paste": "粘贴",
    "shell": "执行命令",
    "python": "执行Python",
    # 浏览器工具（来自 intent_handler.py）
    "browser_open": "打开浏览器",
    "browser_navigate": "浏览网页",
    # 通用 AI 工具（来自 voice_prompts.py 原映射）
    "search": "搜索",
    "web_search": "网页搜索",
    "code_interpreter": "代码解释器",
    "file_reader": "文件读取",
    "calculator": "计算器",
    "weather": "天气查询",
    "translation": "翻译工具",
    "image_generation": "图像生成",
    "tts": "语音合成",
    "stt": "语音识别",
}

# ==================== 步骤/阶段名称映射 ====================
STEP_NAME_MAP: dict[str, str] = {
    "planning": "任务规划",
    "thinking": "思考中",
    "searching": "信息检索",
    "coding": "代码生成",
    "executing": "执行中",
    "summarizing": "结果汇总",
    "finalizing": "收尾处理",
}

# ==================== 错误关键词映射 ====================
ERROR_KEYWORD_MAP: dict[str, str] = {
    "timeout": "操作超时",
    "network_error": "网络异常",
    "auth_failed": "认证失败",
    "not_found": "未找到",
    "rate_limit": "请求过于频繁",
    "invalid_param": "参数错误",
}

# ==================== 通用系统播报 ====================
class SystemAnnouncements:
    """系统级通用播报"""

    WAKE_WORD_DETECTED = "我在"
    LISTENING = "请说"
    PROCESSING = "正在处理，请稍候"
    QUERYING = "正在查询中，请稍候"
    SEARCHING = "正在搜索相关信息"
    THANKS = "不客气"
    GOODBYE = "再见"
    UNKNOWN_COMMAND = "无法识别的命令，请重试"
    PLEASE_REPEAT = "抱歉，我没听清，请再说一遍"
    NETWORK_ERROR = "网络异常，请检查连接后重试"
    SYSTEM_ERROR = "系统异常，请稍后重试"
    TOOL_NOT_FOUND = "未找到该工具，请检查工具名称"
    CATEGORY_NOT_FOUND = "未找到该分类，请重新选择"
    SWITCHING = "正在切换"
    OPERATION_CANCELLED = "未收到确认，已中止操作"
    CONVERSATION_MODE_ON = "进入对话模式，请直接说话，我会一直倾听。说再见结束对话"
    CONVERSATION_TIMEOUT = "对话模式超时，如需帮助请重新唤醒我"
    CONVERSATION_GOODBYE = "好的，再见，如需帮助随时唤醒我"
    CONVERSATION_REST = "对话轮数较多，让我休息一下，如需帮助请重新唤醒我"


# ==================== 层级导航播报 ====================
class LayerAnnouncements:
    """L1/L2/L3 分层导航播报（语义差异化，避免单调重复）"""

    # L1 概览层
    TO_L1_OVERVIEW = "正在进入工具概览"
    TO_L1_FROM_L2 = "返回概览页"
    TO_L1_FROM_L3 = "返回概览"

    # L2 手册层
    TO_L2_MANUAL = "正在打开工具手册"
    TO_L2_FROM_L1 = "前往手册页"
    TO_L2_FROM_L3 = "返回手册"

    # L3 工具详情层
    TO_L3_TOOL_DETAIL = "正在加载{tool_name}的详情"
    TO_L3_FROM_L1 = "查看工具详情"
    TO_L3_FROM_L2 = "打开工具详情"


# ==================== 对话/工作流播报 ====================
class DialogueAnnouncements:
    """对话管理与工作流播报"""

    INTENT_UNDERSTOOD = "收到"
    TOOL_SELECTED = "已选择{tool_name}"
    TOOL_EXECUTING = "正在执行{tool_name}"
    TOOL_SUCCESS = "{tool_name}执行完毕"
    TOOL_FAILED = "{tool_name}执行失败"
    MORAL_REJECTED = "操作被拒绝：{reason}"
    RISK_CONFIRM = "准备{reason}，请说确认以继续"
    RISK_FINAL_WARNING = "即将{reason}，还有10秒时间取消"
    TOOL_EXEC_SUCCESS = "{friendly_name}已完成"
    TOOL_EXEC_FAILED = "{friendly_name}执行失败，请稍后重试"
    STEP_PROGRESS = "正在进行{step_name}"
    WORKFLOW_STEP = "正在执行第{step_num}步，共{total_steps}步{step_name}"
    MULTI_STEP_START = "该任务需要多个步骤，现在开始第一步"
    MULTI_STEP_CONTINUE = "继续下一步"
    MULTI_STEP_FINISH = "全部步骤已完成"


# ==================== 前端交互播报 ====================
class FrontendAnnouncements:
    """前端事件触发的播报（如设置变更、模式切换）"""

    VOICE_ENABLED = "语音助手已开启"
    VOICE_DISABLED = "语音助手已关闭"
    WAKE_MODE_CHANGED = "唤醒模式已切换"
    VOLUME_CHANGED = "音量已调整"
    SPEED_CHANGED = "语速已调整"
    SETTINGS_SAVED = "设置已保存"
    OFFLINE_MODE = "当前处于离线模式"
    ONLINE_MODE = "已恢复在线"


# ==================== 查询/进化播报 ====================
class QueryAnnouncements:
    """查询与进化状态播报"""

    QUERY_TOOL = "正在查询工具手册"
    QUERY_MEMORY = "正在查询记忆库"
    QUERY_LAYER = "正在查询中"
    QUERY_VISION = "正在分析视觉内容"
    QUERY_WORLD_MODEL = "正在预测场景"
    EVOLUTION_REFLECT = "正在反思执行过程"
    EVOLUTION_EVOLVE = "正在整理和进化记忆"
    EVOLUTION_LEARN = "正在学习新技能"
    PROCESSING = "正在处理"
    EXEC_DONE = "执行完成"
    EXEC_FAILED = "执行失败"


# ==================== 对话管理播报 ====================
class DialogueManagerAnnouncements:
    """对话管理器专用播报"""

    VOICE_MODE_ERROR = "语音模式异常，已切换到文本模式"
    DEMO_START = "好的，请开始您的演示，我会记录您的操作"
    NO_LEARNED_FLOW = "没有找到已学习的流程，请先进行演示"
    MULTIPLE_FLOWS = "找到多个可用流程，请指定要使用的流程"
    RESPONSE_TIMEOUT = "抱歉，系统响应超时，请稍后重试"
    VISION_UNAVAILABLE = "视觉服务暂时不可用，正在使用其他方式处理"
    NETWORK_ISSUE = "网络连接有问题，请检查服务状态"
    REQUEST_ERROR = "抱歉，处理您的请求时出现问题，请稍后重试"
    NOT_UNDERSTOOD = "我不太明白你的意思，能再说一遍吗"
    TASK_START = "好的，开始执行任务"
    UNDERSTANDING = "正在理解您的需求，请稍候"
    COMMAND_FORMAT_ERROR = "命令格式不正确，请查看帮助信息"
    THINKING_TIMEOUT = "思考超时，请稍后再试"
    TASK_PAUSED = "任务已暂停"
    TASK_RESUMED = "任务已恢复"
    TASK_TERMINATED = "任务已终止"
    TASK_PAUSE_CONFIRM = "任务已暂停，需要确认理解"
    FOCUS_MODE_ON = "已进入专注模式，AI将降低主动干扰"
    FOCUS_MODE_OFF = "已回到日常模式"
    DAILY_MODE = "进入日常模式"


# ==================== 便捷访问字典（兼容旧代码）====================
ANNOUNCEMENTS: dict[str, str] = {
    # L1
    "to_l1_overview": LayerAnnouncements.TO_L1_OVERVIEW,
    "to_l1_from_l2": LayerAnnouncements.TO_L1_FROM_L2,
    "to_l1_from_l3": LayerAnnouncements.TO_L1_FROM_L3,
    # L2
    "to_l2_manual": LayerAnnouncements.TO_L2_MANUAL,
    "to_l2_from_l1": LayerAnnouncements.TO_L2_FROM_L1,
    "to_l2_from_l3": LayerAnnouncements.TO_L2_FROM_L3,
    # L3
    "to_l3_tool_detail": LayerAnnouncements.TO_L3_TOOL_DETAIL,
    "to_l3_from_l1": LayerAnnouncements.TO_L3_FROM_L1,
    "to_l3_from_l2": LayerAnnouncements.TO_L3_FROM_L2,
    # 通用
    "querying": SystemAnnouncements.QUERYING,
    "processing": SystemAnnouncements.PROCESSING,
    "switching": SystemAnnouncements.SWITCHING,
    # 错误/提示
    "tool_not_found": SystemAnnouncements.TOOL_NOT_FOUND,
    "category_not_found": SystemAnnouncements.CATEGORY_NOT_FOUND,
    "invalid_command": SystemAnnouncements.UNKNOWN_COMMAND,
}
