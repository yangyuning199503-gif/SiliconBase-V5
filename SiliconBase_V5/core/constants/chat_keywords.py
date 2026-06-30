"""
聊天与任务分流关键词库 - 统一一处定义，全局引用

设计原则：
- 简单聊天：用户进行寒暄、身份询问、闲聊 — 应走快速 LLM 路径，不进 AgentLoop
- 任务状态查询：用户询问正在执行的任务进度 — 应读取后台任务快照后 LLM 回复
- 任务控制指令：用户干预正在执行的任务 — 应直接操作后台任务，不走 LLM

使用方式：
    from core.constants import is_simple_chat, classify_user_input
    category = classify_user_input("你叫什么名字")
    # -> {"category": "simple_chat", "confidence": 10}
"""

from typing import Any

# ═══════════════════════════════════════════════════════════════
# 简单聊天关键词（轻量 LLM 路径）
# 匹配规则：文本较短 (< 40 字) 且包含任意关键词
# ═══════════════════════════════════════════════════════════════
SIMPLE_CHAT_KEYWORDS = [
    # 问候
    "你好", "您好", "嗨", "哈喽", "hello", "hi", "hey", "在吗", "在嘛",
    # 身份询问
    "你是谁", "你叫", "名字", "介绍", "自我介绍",
    # 能力询问
    "能力", "能做什么", "会做什么", "会干嘛", "help", "帮助",
    "功能", "有什么功能", "可以做什么",
    # 闲聊/礼貌
    "谢谢", "感谢", "不客气", "再见", "拜拜", "goodbye", "bye",
    # 简单确认
    "嗯", "哦", "好的", "ok", "okay", "知道了", "明白",
    # 情绪表达
    "哈哈", "呵呵", "嘿嘿", "可爱", "厉害", "棒",
    # 时间与系统信息查询（应走轻量 LLM 路径，不进 AgentLoop）
    "几点", "几点钟", "时间", "日期", "几号", "星期", "礼拜", "天气",
    # 标点暗示（单独问号且很短）
    # 注：标点单独判断，不放在关键词列表
]

_SIMPLE_CHAT_MAX_LENGTH = 60  # 简单聊天最大文本长度（放宽以覆盖稍长的时间/日期查询）

# ═══════════════════════════════════════════════════════════════
# 强制任务动作关键词（高优先级，遇到即视为任务意图，不被 simple_chat 吞掉）
# ═══════════════════════════════════════════════════════════════
FORCE_TASK_KEYWORDS = [
    "打开", "启动", "运行", "播放", "查询", "搜索", "查找", "发送", "写入",
    "创建", "新建", "删除", "移除", "修改", "编辑", "更新", "设置", "配置",
    "点击", "输入", "填写", "提交", "下载", "上传", "安装", "卸载", "登录",
    "退出", "复制", "粘贴", "剪切", "保存", "打开网页", "访问", "切换到",
    "截图", "截屏", "拍照", "识别", "提取", "读取",
]

# ═══════════════════════════════════════════════════════════════
# 强制视觉触发关键词（高优先级，遇到即要求必须调用视觉感知）
# ═══════════════════════════════════════════════════════════════
FORCE_VISION_KEYWORDS = [
    "截图", "截屏", "截个图", "截一下图", "拍照", "看看屏幕", "看看桌面",
    "看一下屏幕", "看一下桌面", "屏幕", "桌面", "窗口", "当前页面", "这个页面",
    "在哪里", "在哪", "位置", "找到", "定位", "找一下", "找一找",
    "看到", "看见", "显示", "展示", "识别", "ocr", "提取文字", "读取文字",
    "see", "show me", "screenshot", "capture", "where is", "where are",
    "find", "locate", "position", "screen", "desktop", "window",
    "what do you see", "what can you see", "what is on",
]

# ═══════════════════════════════════════════════════════════════
# 任务状态查询关键词（需有活跃后台任务时触发）
# 匹配规则：包含任意关键词，文本长度不限
# ═══════════════════════════════════════════════════════════════
TASK_STATUS_QUERY_KEYWORDS = [
    "怎么样了", "进度", "完成了吗", "好了吗", "结束了吗",
    "还在跑吗", "执行情况", "任务状态", "进行到哪了",
    "结果出来了吗", "有结果了吗", "跑完了吗",
    "怎么样了", "如何了", "什么情况", "状态",
    "多久完成", "还要多久", "还剩多少",
]

# ═══════════════════════════════════════════════════════════════
# 任务控制指令关键词（直接操作后台任务）
# 匹配规则：包含任意关键词，优先于状态查询
# ═══════════════════════════════════════════════════════════════
TASK_CONTROL_KEYWORDS = {
    "pause": ["暂停", "等一下", "等等", "停一下", "先停", "暂停任务"],
    "resume": ["继续", "恢复", "接着做", "继续任务", "往下做"],
    "cancel": ["取消", "停止", "终止", "别做了", "结束任务", "不做了", "算了"],
    "retry": ["重试", "再来一次", "重新做", "换个方法", "换一种方式"],
}

# ═══════════════════════════════════════════════════════════════
# 实时监控关键词
# ═══════════════════════════════════════════════════════════════
REALTIME_MONITOR_START_KEYWORDS = [
    "盯着屏幕", "实时监控", "帮我看着", "监控屏幕", "盯着桌面",
    "帮我盯", "看着屏幕", "盯着", "实时监控",
]

REALTIME_MONITOR_STOP_KEYWORDS = [
    "停止监控", "不用盯着了", "关闭监控", "停止盯着", "取消监控",
    "不用看着了", "结束监控",
]

# 潜在监控意图关键词（第二道关口，用于触发 LLM 二次确认）
POTENTIAL_MONITOR_KEYWORDS = [
    "屏幕", "桌面", "画面", "显示", "出现", "看着", "盯着",
    "监控", "监视", "留意", "注意", "变化", "动静", "情况",
]


# ═══════════════════════════════════════════════════════════════
# 分类函数
# ═══════════════════════════════════════════════════════════════

def is_simple_chat(text: str) -> bool:
    """
    判断是否为简单聊天输入。

    规则：文本较短 (< 40 字) 且包含任意简单聊天关键词。
    纯问号文本（如 "?"、"？"）且长度 <= 10 也视为简单聊天。

    显式任务动作词或视觉触发词会强制按任务/视觉处理，不会被误判为闲聊。
    """
    if not text or not isinstance(text, str):
        return False

    text_stripped = text.strip()
    if not text_stripped:
        return False

    text_lower = text_stripped.lower()

    # 纯问号（很短）
    if len(text_stripped) <= 10 and text_stripped.strip("?？") == "":
        return True

    # 【修复】能力/身份/模块询问：即使文本较长也走 quick_chat，避免被误分进任务或交易 Commander
    capability_query_markers = [
        "你是谁", "你是什么", "你能做什么", "你会什么", "你有什么功能",
        "介绍一下", "siliconbase", "硅基生命", "面向桌面", "ai agent",
        "功能模块", "支持什么", "可以做什么", "有哪些能力", "核心能力",
        "真的假的", "是不是真的", "对吗", "是不是", "你怎么看"
    ]
    if any(m in text_lower for m in capability_query_markers) and \
       not any(kw in text_lower for kw in FORCE_TASK_KEYWORDS) and \
       not any(kw in text_lower for kw in FORCE_VISION_KEYWORDS):
        # 但明确动作/视觉请求除外：如果用户说"打开 xxx 模块"，仍按任务处理
        return True

    # 长度检查 + 关键词检查
    if len(text_stripped) > _SIMPLE_CHAT_MAX_LENGTH:
        return False

    # 显式动作词/视觉词：不应走闲聊快速通道
    if any(kw in text_lower for kw in FORCE_TASK_KEYWORDS):
        return False
    if any(kw in text_lower for kw in FORCE_VISION_KEYWORDS):
        return False

    return any(kw in text_lower for kw in SIMPLE_CHAT_KEYWORDS)


def is_task_status_query(text: str) -> bool:
    """判断是否为任务状态查询。"""
    if not text or not isinstance(text, str):
        return False
    text_lower = text.lower().strip()
    return any(kw in text_lower for kw in TASK_STATUS_QUERY_KEYWORDS)


def is_task_control_command(text: str) -> str | None:
    """
    判断是否为任务控制指令。

    Returns:
        控制类型字符串 ("pause"/"resume"/"cancel"/"retry") 或 None
    """
    if not text or not isinstance(text, str):
        return None
    text_lower = text.lower().strip()

    for command_type, keywords in TASK_CONTROL_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return command_type
    return None


def is_start_monitor_command(text: str) -> bool:
    """判断是否为启动实时监控指令。"""
    if not text or not isinstance(text, str):
        return False
    text_lower = text.lower().strip()
    return any(kw in text_lower for kw in REALTIME_MONITOR_START_KEYWORDS)


def is_stop_monitor_command(text: str) -> bool:
    """判断是否为停止实时监控指令。"""
    if not text or not isinstance(text, str):
        return False
    text_lower = text.lower().strip()
    return any(kw in text_lower for kw in REALTIME_MONITOR_STOP_KEYWORDS)


def is_potential_monitor_command(text: str) -> bool:
    """判断是否为潜在的监控意图（需 LLM 二次确认）。"""
    if not text or not isinstance(text, str):
        return False
    text_lower = text.lower().strip()
    return any(kw in text_lower for kw in POTENTIAL_MONITOR_KEYWORDS)


def classify_user_input(text: str, has_active_task: bool = False) -> dict[str, Any]:
    """
    统一分类用户输入。

    Args:
        text: 用户输入文本
        has_active_task: 是否有正在执行的后台任务

    Returns:
        {
            "category": "simple_chat" | "task_control" | "task_status_query" | "task",
            "confidence": 1-10,
            "control_type": "pause" | "resume" | "cancel" | "retry" | None,
            "reason": "分类原因说明"
        }
    """
    if not text or not isinstance(text, str):
        return {
            "category": "task",
            "confidence": 0,
            "control_type": None,
            "reason": "空输入，默认按任务处理"
        }

    text_stripped = text.strip()
    if not text_stripped:
        return {
            "category": "task",
            "confidence": 0,
            "control_type": None,
            "reason": "空输入"
        }

    text_lower = text_stripped.lower()

    # 0. 最高优先级：强制视觉触发词（必须在任务中触发视觉感知）
    if any(kw in text_lower for kw in FORCE_VISION_KEYWORDS):
        return {
            "category": "task",
            "confidence": 9,
            "control_type": None,
            "reason": "匹配到强制视觉触发词，按任务处理并必须调用视觉感知",
            "force_vision": True
        }

    # 0.5 次高优先级：强制任务动作词
    if any(kw in text_lower for kw in FORCE_TASK_KEYWORDS):
        return {
            "category": "task",
            "confidence": 9,
            "control_type": None,
            "reason": "匹配到明确任务动作关键词，按任务处理"
        }

    # 1. 最高优先级：任务控制指令（无论是否有活跃任务都识别）
    control_type = is_task_control_command(text_stripped)
    if control_type:
        return {
            "category": "task_control",
            "confidence": 9,
            "control_type": control_type,
            "reason": f"匹配到任务控制指令: {control_type}"
        }

    # 1.5 停止实时监控指令（优先于状态查询）
    if is_stop_monitor_command(text_stripped):
        return {
            "category": "stop_monitor",
            "confidence": 9,
            "control_type": None,
            "reason": "匹配到停止实时监控关键词"
        }

    # 2. 有活跃任务时：状态查询
    if has_active_task and is_task_status_query(text_stripped):
        return {
            "category": "task_status_query",
            "confidence": 8,
            "control_type": None,
            "reason": "有活跃任务且匹配状态查询关键词"
        }

    # 3. 启动实时监控指令
    if is_start_monitor_command(text_stripped):
        return {
            "category": "start_monitor",
            "confidence": 9,
            "control_type": None,
            "reason": "匹配到启动实时监控关键词"
        }

    # 4. 潜在监控意图（第二道关口，触发 LLM 二次确认）
    if is_potential_monitor_command(text_stripped):
        return {
            "category": "potential_monitor",
            "confidence": 6,
            "control_type": None,
            "reason": "包含屏幕相关词汇，需 LLM 二次确认是否为监控意图"
        }

    # 5. 简单聊天
    if is_simple_chat(text_stripped):
        return {
            "category": "simple_chat",
            "confidence": 8,
            "control_type": None,
            "reason": "短文本且匹配简单聊天关键词"
        }

    # 6. 默认：新任务
    return {
        "category": "task",
        "confidence": 5,
        "control_type": None,
        "reason": "未匹配聊天/控制关键词，按任务处理"
    }
