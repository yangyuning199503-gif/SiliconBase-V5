#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""  # 多行文档字符串开始
自然语言意图解析器（重构版）  # 模块标题
- 优先解析结构化 JSON 协议  # 功能1
- 支持工具调用、最终答案、计划  # 功能2
- 失败时回退到自然语言关键词匹配（加强正则边界）  # 功能3
2026-02-21 修复：增强正则边界，增加语义二次确认  # 版本历史1
2026-02-28 新增：精准抓取解析器（PrecisionParser）- 纽带功能  # 版本历史2
"""  # 多行文档字符串结束
import contextlib  # 导入上下文管理工具
import json  # 导入JSON模块
import re  # 导入正则表达式模块
from dataclasses import dataclass, field  # 从dataclasses导入数据类装饰器和字段函数
from enum import Enum  # 从enum导入枚举类
from typing import Any  # 从typing导入类型注解

from core.intent.command_parser import CommandType, ParsedCommand, get_command_parser  # 导入命令解析器
from core.logger import logger  # 导入日志记录器
from core.utils.app_mapping import get_app_mapping_manager  # 导入应用映射管理器

# =============================================================================  # 分隔线
# 【精准抓取】AI输出标记类型定义  # 精准抓取标题
# =============================================================================  # 分隔线

class AICodeMarker(Enum):  # 定义AI输出标记类型枚举类
    """  # 类文档字符串开始
    AI输出的计算机语言标记类型  # 类标题
    用于精准抓取AI的特定输出 - 这是纽带功能的核心  # 核心功能说明

    功能连接：  # 功能连接说明
    1. 用户体验（听到自然语言）  # 连接1
    2. AI使用工具（被识别到位）  # 连接2
    3. 反馈给AI的结果（需要被抓取）  # 连接3
    """  # 类文档字符串结束
    # 任务相关  # 任务相关注释
    TOOL_CALL = "tool_call"           # 工具调用标记  # 枚举值1
    FINAL_ANSWER = "final_answer"     # 最终答案标记  # 枚举值2
    TASK_COMPLETE = "task_complete"   # 任务完成标记  # 枚举值3

    # 进化与反思  # 进化反思注释
    EVOLVE_REFLECT = "evolve_reflect" # 进化反思标记  # 枚举值4
    MEMORY_UPDATE = "memory_update"   # 记忆更新标记  # 枚举值5

    # 世界模型  # 世界模型注释
    WORLD_MODEL = "world_model"       # 世界模型更新标记  # 枚举值6
    SCENE_ANALYSIS = "scene_analysis" # 场景分析标记  # 枚举值7

    # 视觉  # 视觉注释
    VISION_ANALYSIS = "vision_analysis"  # 视觉分析标记  # 枚举值8
    SCREEN_UNDERSTAND = "screen_understand"  # 屏幕理解标记  # 枚举值9

    # 交互  # 交互注释
    CALL_USER = "call_user"           # 呼叫用户标记  # 枚举值10
    ASK_CLARIFY = "ask_clarify"       # 请求澄清标记  # 枚举值11

    # 提示词层级  # 层级注释
    LAYER_SWITCH = "layer_switch"     # 层级切换标记  # 枚举值12
    TOOL_QUERY = "tool_query"         # 查询工具标记  # 枚举值13

    # 计划执行  # 计划注释
    PLAN_STEP = "plan_step"           # 计划步骤标记  # 枚举值14
    PLAN_COMPLETE = "plan_complete"   # 计划完成标记  # 枚举值15

    # 默认  # 默认注释
    UNKNOWN = "unknown"               # 未知类型标记  # 枚举值16


@dataclass  # 使用数据类装饰器
class ParsedAIOutput:  # 定义解析后的AI输出数据类
    """  # 类文档字符串开始
    解析后的AI输出 - 精准抓取的结果  # 类标题

    包含：  # 包含字段说明
    - marker_type: 标记类型（决定如何处理）  # 字段1说明
    - raw_content: 原始AI输出  # 字段2说明
    - parsed_data: 解析后的结构化数据  # 字段3说明
    - natural_language: 自然语言部分（用于语音播报给用户）  # 字段4说明
    - should_speak: 是否应该语音播报  # 字段5说明
    """  # 类文档字符串结束
    marker_type: AICodeMarker  # 标记类型字段
    raw_content: str  # 原始内容字段
    parsed_data: dict[str, Any]  # 解析后的结构化数据字段
    natural_language: str  # 自然语言部分（用于语音播报）字段
    should_speak: bool     # 是否应该语音播报字段

    def to_dict(self) -> dict[str, Any]:  # 定义转换为字典方法
        """转换为字典格式"""  # 方法文档字符串
        return {  # 返回字典
            "marker_type": self.marker_type.value,  # 标记类型值
            "raw_content": self.raw_content,  # 原始内容
            "parsed_data": self.parsed_data,  # 解析数据
            "natural_language": self.natural_language,  # 自然语言
            "should_speak": self.should_speak  # 是否播报
        }  # 字典结束


@dataclass   # 使用数据类装饰器
class ToolCallData:  # 定义工具调用数据结构类
    """工具调用数据结构"""  # 类文档字符串
    tool_name: str  # 工具名称字段
    params: dict[str, Any]  # 参数字段
    call_id: str | None = None  # 调用ID字段，默认None

    def to_dict(self) -> dict[str, Any]:  # 定义转换为字典方法
        """转换为字典"""  # 方法文档字符串
        return {  # 返回字典
            "tool": self.tool_name,  # 工具名称
            "params": self.params,  # 参数
            "call_id": self.call_id  # 调用ID
        }  # 字典结束


@dataclass  # 使用数据类装饰器
class EvolveReflectData:  # 定义进化反思数据结构类
    """进化反思数据结构"""  # 类文档字符串
    reflection_type: str  # 反思类型字段 "learning", "optimization", "error_analysis"
    insights: list[str]  # 洞察列表字段
    suggestions: list[str]  # 建议列表字段
    confidence: float = 0.0  # 置信度字段，默认0.0

    def to_dict(self) -> dict[str, Any]:  # 定义转换为字典方法
        """转换为字典"""  # 方法文档字符串
        return {  # 返回字典
            "type": self.reflection_type,  # 类型
            "insights": self.insights,  # 洞察
            "suggestions": self.suggestions,  # 建议
            "confidence": self.confidence  # 置信度
        }  # 字典结束


@dataclass  # 使用数据类装饰器
class WorldModelData:  # 定义世界模型数据结构类
    """世界模型数据结构"""  # 类文档字符串
    observation: str  # 观察字段
    prediction: str  # 预测字段
    confidence: float  # 置信度字段
    suggested_action: str | None = None  # 建议动作字段，默认None

    def to_dict(self) -> dict[str, Any]:  # 定义转换为字典方法
        """转换为字典"""  # 方法文档字符串
        return {  # 返回字典
            "observation": self.observation,  # 观察
            "prediction": self.prediction,  # 预测
            "confidence": self.confidence,  # 置信度
            "suggested_action": self.suggested_action  # 建议动作
        }  # 字典结束


@dataclass  # 使用数据类装饰器
class VisionAnalysisData:  # 定义视觉分析数据结构类
    """视觉分析数据结构"""  # 类文档字符串
    objects_detected: list[str]  # 检测到的物体列表字段
    scene_description: str  # 场景描述字段
    text_recognized: list[str] | None = None  # 识别到的文本列表字段，默认None
    ui_elements: list[dict] | None = None  # UI元素列表字段，默认None

    def to_dict(self) -> dict[str, Any]:  # 定义转换为字典方法
        """转换为字典"""  # 方法文档字符串
        return {  # 返回字典
            "objects": self.objects_detected,  # 物体
            "scene": self.scene_description,  # 场景
            "text": self.text_recognized,  # 文本
            "ui_elements": self.ui_elements  # UI元素
        }  # 字典结束


@dataclass  # 使用数据类装饰器
class CallUserData:  # 定义呼叫用户数据结构类
    """呼叫用户数据结构"""  # 类文档字符串
    reason: str  # 原因字段
    urgency: str = "normal"  # 紧急程度字段，默认"normal" ("low", "normal", "high")
    expected_response: str | None = None  # 期望响应字段，默认None

    def to_dict(self) -> dict[str, Any]:  # 定义转换为字典方法
        """转换为字典"""  # 方法文档字符串
        return {  # 返回字典
            "reason": self.reason,  # 原因
            "urgency": self.urgency,  # 紧急程度
            "expected_response": self.expected_response  # 期望响应
        }  # 字典结束


@dataclass  # 使用数据类装饰器
class LayerSwitchData:  # 定义层级切换数据结构类
    """层级切换数据结构"""  # 类文档字符串
    target_layer: str  # 目标层级字段 "L1", "L2", "L3"
    reason: str  # 原因字段
    context: dict | None = None  # 上下文字段，默认None

    def to_dict(self) -> dict[str, Any]:  # 定义转换为字典方法
        """转换为字典"""  # 方法文档字符串
        return {  # 返回字典
            "target_layer": self.target_layer,  # 目标层级
            "reason": self.reason,  # 原因
            "context": self.context  # 上下文
        }  # 字典结束


class IntentType(Enum):  # 定义意图类型枚举类
    UNKNOWN = "未知"  # 未知意图  # 枚举值1
    OPEN_WEBSITE = "打开网页"  # 打开网页意图  # 枚举值2
    OPEN_APP = "打开应用"  # 打开应用意图  # 枚举值3
    SEARCH = "搜索查询"  # 搜索查询意图  # 枚举值4
    SYSTEM_CONTROL = "系统控制"  # 系统控制意图  # 枚举值5
    QUERY_INFO = "信息查询"  # 信息查询意图  # 枚举值6
    OFFICE_ASSIST = "办公辅助"  # 办公辅助意图  # 枚举值7
    CLOSE_APP = "关闭应用"  # 关闭应用意图  # 枚举值8
    ADJUST_VOLUME = "调节音量"  # 调节音量意图  # 枚举值9
    TAKE_SCREENSHOT = "截图"  # 截图意图  # 枚举值10
    # 协议意图  # 协议意图注释
    TOOL_CALL = "工具调用"  # 工具调用意图  # 枚举值11
    FINAL_ANSWER = "最终答案"  # 最终答案意图  # 枚举值12
    PLAN = "计划"  # 计划意图  # 枚举值13
    # 分层交互命令  # 分层交互注释
    QUERY_TOOL_LIST = "查询工具列表"  # 查询工具列表意图  # 枚举值14
    QUERY_TOOL_DETAIL = "查询工具详情"  # 查询工具详情意图  # 枚举值15
    BACK_TO_PREV = "返回上一层"  # 返回上一层意图  # 枚举值16
    # AI计算机语言（L1L2L3提示词系统）- 共19个标记  # AI计算机语言注释
    # 用户交互层  # 用户交互层注释
    CALL_USER = "呼叫用户"  # 呼叫用户意图  # 枚举值17
    ASK_USER = "询问用户"  # 询问用户意图  # 枚举值18
    WAIT_CONFIRM = "等待确认"  # 等待确认意图  # 枚举值19
    NOTIFY_USER = "通知用户"  # 通知用户意图  # 枚举值20
    # 工具查询层  # 工具查询层注释
    FIND_TOOL = "查找工具"  # 查找工具意图  # 枚举值21
    # 记忆认知层  # 记忆认知层注释
    QUERY_MEMORY = "查询记忆"  # 查询记忆意图  # 枚举值22
    RECORD_MEMORY = "记录记忆"  # 记录记忆意图  # 枚举值23
    DELETE_MEMORY = "删除记忆"  # 删除记忆意图  # 枚举值24
    # 学习进化层  # 学习进化层注释
    ENTER_LEARNING = "进入学习"  # 进入学习意图  # 枚举值25
    EXECUTE_PLAN = "执行计划"  # 执行计划意图  # 枚举值26
    REFLECT = "反思"  # 反思意图  # 枚举值27
    EVOLVE = "进化"  # 进化意图  # 枚举值28
    EVOLVE_MEMORY = "进化记忆"  # 进化记忆意图  # 枚举值29
    # 预测感知层  # 预测感知层注释
    WORLD_MODEL_PREDICT = "世界模型预测"  # 世界模型预测意图  # 枚举值30
    VISION_ANALYZE = "视觉识别"  # 视觉识别意图  # 枚举值31
    BEHAVIOR_ANALYZE = "行为分析"  # 行为分析意图  # 枚举值32
    # 系统控制层  # 系统控制层注释
    PAUSE_EXECUTION = "暂停执行"  # 暂停执行意图  # 枚举值33
    RESUME_EXECUTION = "恢复执行"  # 恢复执行意图  # 枚举值34
    TERMINATE_TASK = "终止任务"  # 终止任务意图  # 枚举值35
    SUBMIT_UNDERSTANDING = "提交理解摘要"  # 提交理解摘要意图（用于暂停确认流程）  # 枚举值36


@dataclass  # 使用数据类装饰器
class ParsedIntent:  # 定义解析后的意图数据类
    intent_type: IntentType  # 意图类型字段
    raw_instruction: str  # 原始指令字段
    target_app: str = ""  # 目标应用字段，默认空字符串
    target_url: str = ""  # 目标URL字段，默认空字符串
    search_keyword: str = ""  # 搜索关键词字段，默认空字符串
    operation: str = ""  # 操作字段，默认空字符串
    params: dict = field(default_factory=dict)  # 参数字段，默认空字典
    confidence: float = 0.0  # 置信度字段，默认0.0
    # 工具调用专用  # 工具调用注释
    target_tool: str = ""  # 目标工具字段，默认空字符串
    # 计划专用  # 计划注释
    steps: list = field(default_factory=list)  # 步骤列表字段，默认空列表
    natural_language: str = ""  # AI的自然语言回复


class NLPIntentParser:  # 定义NLP意图解析器类
    """  # 类文档字符串开始
    意图解析器，优先解析结构化 JSON 协议，失败时回退到自然语言匹配。  # 类说明
    """  # 类文档字符串结束

    # 工具动作关键词映射（用于自然语言回退）  # 关键词映射注释
    ACTION_KEYWORDS = {  # 动作关键词字典
        "click_text": ["点击", "点一下", "按下", "单击", "左键点击"],  # 点击动作关键词  # 关键词1
        "mouse_click": ["鼠标点击", "右键点击"],  # 鼠标点击关键词  # 关键词2
        "keyboard_input": ["输入", "键入", "打出", "写入", "粘贴"],  # 键盘输入关键词  # 关键词3
        "launch_app": ["打开", "启动", "运行", "开启", "执行"],  # 启动应用关键词  # 关键词4
        "web_search": ["搜索", "查一下", "百度一下", "谷歌一下"],  # 网络搜索关键词  # 关键词5
        "web_open": ["访问", "浏览", "进入网页", "打开网站"],  # 打开网页关键词  # 关键词6
        "window_focus": ["激活窗口", "切换到", "置前", "聚焦"],  # 窗口聚焦关键词  # 关键词7
        "window_get": ["查找窗口", "列出窗口", "枚举窗口"],  # 获取窗口关键词  # 关键词8
        "screen_ocr": ["识别屏幕", "提取文字", "OCR"],  # 屏幕OCR关键词  # 关键词9
        "screenshot": ["截图", "截屏", "屏幕截图"],  # 截图关键词  # 关键词10
        "file_read": ["读取文件", "打开文件"],  # 读取文件关键词  # 关键词11
        "file_write": ["写入文件", "保存文件"],  # 写入文件关键词  # 关键词12
        "file_list": ["列出目录", "查看文件列表"],  # 列出目录关键词  # 关键词13
        "process_kill": ["结束进程", "终止进程"],  # 结束进程关键词  # 关键词14
        "process_start": ["启动进程", "运行程序"],  # 启动进程关键词  # 关键词15
        "system_info": ["系统信息", "硬件信息", "CPU", "内存"],  # 系统信息关键词  # 关键词16
        "clipboard_get": ["获取剪贴板", "读取剪贴板"],  # 获取剪贴板关键词  # 关键词17
        "clipboard_set": ["设置剪贴板", "写入剪贴板"],  # 设置剪贴板关键词  # 关键词18
        "wait_for_window": ["等待窗口"],  # 等待窗口关键词  # 关键词19
        "window_rect": ["获取窗口区域"],  # 窗口区域关键词  # 关键词20
        "window_ocr": ["窗口文字识别"],  # 窗口OCR关键词  # 关键词21
        "window_action": ["窗口操作"],  # 窗口操作关键词  # 关键词22
        "app_search": ["应用内搜索"],  # 应用内搜索关键词  # 关键词23
        "code_generate": ["生成代码"],  # 生成代码关键词  # 关键词24
    }  # 关键词字典结束

    # 自然语言解析模式（加强正则边界，使用 \b 边界）  # 参数模式注释
    PARAM_PATTERNS = {  # 参数模式字典
        "text": r'[""]([^""]+)[""]|[\'\']([^\'\']+)[\'\']|(?<=输入)\s+([^，。\s]+)|(?<=点击)\s+([^，。\s]+)',  # 文本参数模式  # 模式1
        "url": r'https?://[^\s]+',  # URL参数模式  # 模式2
        "app_name": r'(?<=打开)\s+([^，。\s]+)',  # 应用名称参数模式  # 模式3
        "keyword": r'(?<=搜索)\s+([^，。\s]+)',  # 关键词参数模式  # 模式4
        "path": r'路径[：:]\s*([^\s]+)',  # 路径参数模式  # 模式5
        "x": r'x[：:]\s*(\d+)',  # x坐标参数模式  # 模式6
        "y": r'y[：:]\s*(\d+)',  # y坐标参数模式  # 模式7
        "hwnd": r'hwnd[：:]\s*(\d+)',  # 窗口句柄参数模式  # 模式8
    }  # 参数字典结束

    COMPOSITE_PATTERNS = [  # 复合模式列表
        r"(?:打开|启动|进入|访问|浏览)?\s*(.+?)\s*(?:查|搜|搜索|查询|找)\s*(.+)",  # 复合模式1：打开XX搜索XX
        r"(?:在|去)?\s*(.+?)\s*(?:里|里面|上|上面)?\s*(?:查|搜|搜索|查询|找)\s*(.+)",  # 复合模式2：在XX里搜索XX
        r"(?:用|使用)?\s*(.+?)\s*(?:查|搜|搜索|查询|找)\s*(.+)",  # 复合模式3：用XX搜索XX
    ]  # 复合模式列表结束

    SYSTEM_CONTROL_KEYWORDS = {  # 系统控制关键词字典
        "volume_up": ["调大音量", "增大音量", "音量调大", "声音大点"],  # 增大音量关键词  # 控制词1
        "volume_down": ["调小音量", "减小音量", "音量调小", "声音小点"],  # 减小音量关键词  # 控制词2
        "mute": ["静音", "关闭声音"],  # 静音关键词  # 控制词3
        "brightness_up": ["调亮", "亮度调高", "亮一点"],  # 增加亮度关键词  # 控制词4
        "brightness_down": ["调暗", "亮度调低", "暗一点"],  # 降低亮度关键词  # 控制词5
        "shutdown": ["关机", "关闭电脑"],  # 关机关键词  # 控制词6
        "restart": ["重启", "重新启动"],  # 重启关键词  # 控制词7
        "sleep": ["睡眠", "休眠"],  # 睡眠关键词  # 控制词8
        "lock": ["锁屏", "锁定"],  # 锁屏关键词  # 控制词9
        "screenshot": ["截图", "截屏"],  # 截图关键词  # 控制词10
        "record": ["录屏", "录制"],  # 录制关键词  # 控制词11
        "close_app": ["关闭应用", "退出程序", "关闭窗口"],  # 关闭应用关键词  # 控制词12
    }  # 系统控制字典结束

    INFO_QUERY_KEYWORDS = {  # 信息查询关键词字典
        "price": ["多少钱", "价格", "售价", "报价"],  # 价格查询关键词  # 查询词1
        "weather": ["天气", "气温", "温度"],  # 天气查询关键词  # 查询词2
        "time": ["时间", "几点", "日期", "星期"],  # 时间查询关键词  # 查询词3
        "ticket": ["车票", "机票", "火车票"],  # 票务查询关键词  # 查询词4
    }  # 信息查询字典结束

    def __init__(self):  # 初始化方法
        self.app_manager = get_app_mapping_manager()  # 获取应用映射管理器实例

    def parse(self, instruction: str) -> ParsedIntent:  # 解析用户指令方法
        """解析用户输入的指令（自然语言）"""  # 方法文档字符串
        instruction = instruction.strip()  # 去除指令首尾空白
        if not instruction:  # 如果指令为空
            return ParsedIntent(IntentType.UNKNOWN, instruction, confidence=0.0)  # 返回未知意图

        # 1. 复合指令  # 复合指令注释
        composite = self._parse_composite(instruction)  # 尝试解析为复合指令
        if composite:  # 如果解析成功
            return composite  # 返回复合指令解析结果

        # 2. 系统控制  # 系统控制注释
        system = self._parse_system_control(instruction)  # 尝试解析为系统控制指令
        if system:  # 如果解析成功
            return system  # 返回系统控制解析结果

        # 3. 信息查询  # 信息查询注释
        query = self._parse_info_query(instruction)  # 尝试解析为信息查询指令
        if query:  # 如果解析成功
            return query  # 返回信息查询解析结果

        # 4. 打开应用/网站  # 打开应用注释
        open_cmd = self._parse_open(instruction)  # 尝试解析为打开指令
        if open_cmd:  # 如果解析成功
            return open_cmd  # 返回打开指令解析结果

        # 5. 搜索指令  # 搜索注释
        search = self._parse_search(instruction)  # 尝试解析为搜索指令
        if search:  # 如果解析成功
            return search  # 返回搜索指令解析结果

        # 如果仍未识别，进行 AI 二次确认（可选，避免误判）  # AI确认注释
        # 这里仅当置信度低于阈值时调用，但为了简化，我们返回 UNKNOWN  # 简化注释
        return ParsedIntent(IntentType.UNKNOWN, instruction, confidence=0.0)  # 返回未知意图

    def parse_ai_response(self, text: str) -> ParsedIntent:  # 解析AI响应方法
        """  # 方法文档字符串开始
        解析AI的响应  # 方法标题
        优先级：JSON > 命令 > 自然语言  # 解析优先级
        """  # 方法文档字符串结束
        text = text.strip()  # 去除文本首尾空白
        if not text:  # 如果文本为空
            return ParsedIntent(IntentType.UNKNOWN, text, confidence=0.0)  # 返回未知意图

        # 1. 尝试解析为JSON（工具调用）  # JSON解析注释
        cleaned_text = self._extract_json_from_markdown(text)  # 从Markdown中提取JSON
        json_parsed = self._parse_as_json(cleaned_text)  # 尝试解析为JSON
        if json_parsed:  # 如果JSON解析成功
            return json_parsed  # 返回JSON解析结果

        # 2. 尝试解析为命令（分层导航）- 使用专门的命令解析器  # 命令解析注释
        cmd_parsed = self._parse_as_command(text)  # 尝试解析为命令
        if cmd_parsed:  # 如果命令解析成功
            return cmd_parsed  # 返回命令解析结果

        # 3. 解析AI计算机语言（L1L2L3提示词系统）  # AI语言解析注释
        ai_lang_parsed = self._parse_ai_computer_language(text)  # 尝试解析AI计算机语言
        if ai_lang_parsed:  # 如果AI语言解析成功
            return ai_lang_parsed  # 返回AI语言解析结果

        # 4. JSON和命令解析失败，回退到自然语言解析  # 自然语言回退注释
        return self._parse_as_natural_language(text)  # 回退到自然语言解析

    def parse_user_input(self, text: str) -> ParsedIntent:  # 解析用户输入方法
        """  # 方法文档字符串开始
        解析用户输入（带命令优先级处理）  # 方法标题

        解析优先级：  # 优先级说明
        1. 分层交互命令（最高优先级，严格匹配）  # 优先级1
        2. 复合指令（打开XX搜索XX）  # 优先级2
        3. 系统控制命令  # 优先级3
        4. 信息查询  # 优先级4
        5. 打开应用/网站  # 优先级5
        6. 搜索指令  # 优先级6
        7. 自然语言（最低优先级）  # 优先级7

        Args:  # 参数说明
            text: 用户输入文本  # 参数

        Returns:  # 返回值说明
            ParsedIntent: 解析后的意图  # 返回类型
        """  # 方法文档字符串结束
        text = text.strip()  # 去除文本首尾空白
        if not text:  # 如果文本为空
            return ParsedIntent(IntentType.UNKNOWN, text, confidence=0.0)  # 返回未知意图

        # 1. 首先尝试解析为命令（最高优先级）  # 命令解析注释
        cmd = get_command_parser().parse(text)  # 使用命令解析器解析
        if cmd:  # 如果解析成功
            return self._convert_command_to_intent(cmd)  # 转换为意图并返回

        # 2. 复合指令  # 复合指令注释
        composite = self._parse_composite(text)  # 尝试解析复合指令
        if composite:  # 如果解析成功
            return composite  # 返回复合指令结果

        # 3. 系统控制  # 系统控制注释
        system = self._parse_system_control(text)  # 尝试解析系统控制
        if system:  # 如果解析成功
            return system  # 返回系统控制结果

        # 4. 信息查询  # 信息查询注释
        query = self._parse_info_query(text)  # 尝试解析信息查询
        if query:  # 如果解析成功
            return query  # 返回信息查询结果

        # 5. 打开应用/网站  # 打开应用注释
        open_cmd = self._parse_open(text)  # 尝试解析打开指令
        if open_cmd:  # 如果解析成功
            return open_cmd  # 返回打开指令结果

        # 6. 搜索指令  # 搜索注释
        search = self._parse_search(text)  # 尝试解析搜索指令
        if search:  # 如果解析成功
            return search  # 返回搜索指令结果

        # 7. 无法识别，返回 UNKNOWN  # 未知意图注释
        return ParsedIntent(IntentType.UNKNOWN, text, confidence=0.0)  # 返回未知意图

    def _convert_command_to_intent(self, cmd: ParsedCommand) -> ParsedIntent:  # 转换命令到意图方法
        """将命令解析结果转换为意图"""  # 方法文档字符串
        intent_type_map = {  # 意图类型映射字典
            CommandType.QUERY_TOOL_LIST: IntentType.QUERY_TOOL_LIST,  # 查询工具列表映射
            CommandType.QUERY_TOOL_DETAIL: IntentType.QUERY_TOOL_DETAIL,  # 查询工具详情映射
            CommandType.BACK_TO_PREV: IntentType.BACK_TO_PREV,  # 返回上一层映射
        }  # 映射字典结束

        intent_type = intent_type_map.get(  # 获取对应的意图类型
            cmd.command_type,   # 命令类型
            IntentType.UNKNOWN  # 默认未知
        )  # 获取结束

        return ParsedIntent(  # 返回解析后的意图
            intent_type=intent_type,  # 意图类型
            raw_instruction=cmd.raw_input,  # 原始输入
            params=cmd.params.copy(),  # 参数副本
            confidence=cmd.confidence  # 置信度
        )  # 返回结束

    def _extract_json_from_markdown(self, text: str) -> str:  # 从Markdown提取JSON方法
        """从可能的 Markdown 代码块中提取 JSON 字符串"""  # 方法文档字符串
        match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)  # 匹配Markdown代码块
        if match:  # 如果匹配成功
            return match.group(1).strip()  # 返回提取的JSON字符串
        return text  # 没有代码块，返回原文本

    def _parse_as_json(self, text: str) -> ParsedIntent | None:  # 解析为JSON方法
        """尝试将文本解析为 JSON 协议 - 增强版支持更多格式"""
        import re

        # 【修复1】首先尝试从Markdown代码块提取JSON
        original_text = text
        code_block_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
        if code_block_match:
            text = code_block_match.group(1).strip()

        # 【修复2】如果不是JSON格式，尝试查找第一个JSON对象
        if not (text.startswith('{') and text.endswith('}')):
            # 查找第一个 { 和匹配的 }
            start = text.find('{')
            if start != -1:
                # 找到匹配的}
                brace_count = 0
                end = start
                for i, char in enumerate(text[start:]):
                    if char == '{':
                        brace_count += 1
                    elif char == '}':
                        brace_count -= 1
                        if brace_count == 0:
                            end = start + i
                            break
                if end > start:
                    text = text[start:end+1]
            else:
                return None

        # 【修复3】尝试解析JSON
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # 尝试修复常见的JSON格式错误
            try:
                # 去除可能的尾部逗号
                fixed_text = re.sub(r',(\s*[}\]])', r'\1', text)
                data = json.loads(fixed_text)
            except (json.JSONDecodeError, ValueError, TypeError) as e:
                logger.error(f"[NLPIntentParser] JSON修复解析失败: {e}", exc_info=True)
                return None

        if not isinstance(data, dict):
            return None

        # 【修复4】支持更多变体格式
        action = data.get('action', '').lower()
        # 支持多种工具字段名
        tool = (data.get('tool') or
                data.get('tool_id') or
                data.get('tool_name') or
                data.get('function') or
                data.get('name'))

        # 【修复】如果 tool 字段的内容是特殊标记而非真实工具，不要误判为 TOOL_CALL
        if tool and tool.upper() in ("FINAL_ANSWER", "FINALANSWER", "ANSWER"):
            # 兼容 AI 把 final_answer 填进 tool 字段的情况
            content = (data.get("params", {}).get("answer", "") or
                       data.get("params", {}).get("content", "") or
                       data.get("content", "") or
                       data.get("answer", "") or
                       data.get("message", "") or
                       original_text)
            return ParsedIntent(
                intent_type=IntentType.FINAL_ANSWER,
                raw_instruction=original_text,
                params={"content": content},
                natural_language=content,
                confidence=0.95
            )

        # 【修复5】如果有tool字段，无论是否有action都认为是工具调用
        if tool:
            # 支持多种参数字段名
            params = (data.get('params', {}) or
                     data.get('parameters', {}) or
                     data.get('args', {}) or
                     data.get('arguments', {}))
            if not isinstance(params, dict):
                params = {}

            # 提取自然语言回复（支持多个字段名）
            natural_lang = (data.get("reply_to_user") or
                           data.get("message") or
                           data.get("content") or
                           data.get("response") or "")

            return ParsedIntent(
                intent_type=IntentType.TOOL_CALL,
                raw_instruction=original_text,
                target_tool=tool,
                params=params,
                natural_language=natural_lang,
                confidence=0.95
            )

        if action in ('call_tool', 'call', 'execute', 'run') and tool:
            params = data.get('params', {})
            if not isinstance(params, dict):
                params = {}
            return ParsedIntent(
                intent_type=IntentType.TOOL_CALL,
                raw_instruction=original_text,
                target_tool=tool,
                params=params,
                natural_language=data.get("reply_to_user", ""),
                confidence=0.95
            )

        if action == 'final_answer' and 'content' in data:  # 如果是最终答案动作
            return ParsedIntent(  # 返回最终答案意图
                intent_type=IntentType.FINAL_ANSWER,  # 最终答案类型
                raw_instruction=text,  # 原始指令
                params={'content': data['content']},  # 内容参数
                confidence=0.95  # 高置信度
            )  # 返回结束

        if action == 'complete':  # 【修复】处理action="complete"
            return ParsedIntent(  # 返回最终答案意图
                intent_type=IntentType.FINAL_ANSWER,  # 最终答案类型
                raw_instruction=text,  # 原始指令
                natural_language=data.get('reply_to_user', ''),  # 提取自然语言回复
                params={'content': data.get('content', '')},  # 内容参数
                confidence=0.95  # 高置信度
            )  # 返回结束

        if action == 'plan' and 'steps' in data:  # 如果是计划动作
            steps = []  # 步骤列表
            for step_data in data['steps']:  # 遍历步骤数据
                if isinstance(step_data, str):  # 如果是字符串
                    step_intent = self.parse_ai_response(step_data)  # 解析步骤
                    steps.append(step_intent)  # 添加到步骤列表
                elif isinstance(step_data, dict):  # 如果是字典
                    step_intent = self.parse_ai_response(json.dumps(step_data, ensure_ascii=False))  # 转为JSON解析
                    steps.append(step_intent)  # 添加到步骤列表
            return ParsedIntent(  # 返回计划意图
                intent_type=IntentType.PLAN,  # 计划类型
                raw_instruction=text,  # 原始指令
                steps=steps,  # 步骤列表
                confidence=0.9  # 置信度
            )  # 返回结束

        if 'plan' in data:  # 如果包含plan字段
            plan = data['plan']  # 获取计划
            if isinstance(plan, list):  # 如果是列表
                steps = []  # 步骤列表
                for item in plan:  # 遍历计划项
                    if isinstance(item, str):  # 如果是字符串
                        steps.append(self.parse_ai_response(item))  # 解析并添加
                    elif isinstance(item, dict):  # 如果是字典
                        steps.append(self.parse_ai_response(json.dumps(item, ensure_ascii=False)))  # 解析并添加
                return ParsedIntent(IntentType.PLAN, text, steps=steps, confidence=0.8)  # 返回计划意图
            elif isinstance(plan, dict) and 'sub_tasks' in plan:  # 如果是带子任务的字典
                steps = []  # 步骤列表
                for task in plan['sub_tasks']:  # 遍历子任务
                    if isinstance(task, dict):  # 如果是字典
                        step_text = task.get('description') or task.get('action') or ''  # 获取步骤文本
                        if step_text:  # 如果不为空
                            steps.append(self.parse_ai_response(step_text))  # 解析并添加
                return ParsedIntent(IntentType.PLAN, text, steps=steps, confidence=0.8)  # 返回计划意图

        # 【修复】反思JSON（observation/insight/suggestion/reflection/analysis）应识别为FINAL_ANSWER
        if any(k in data for k in ("observation", "insight", "suggestion", "reflection", "analysis")):
            content = (data.get("observation") or
                       data.get("insight") or
                       data.get("suggestion") or
                       data.get("reflection") or
                       data.get("analysis") or
                       data.get("summary", "") or
                       original_text)
            # 将内容合并为一个友好的最终答案
            if isinstance(content, dict):
                content = json.dumps(content, ensure_ascii=False)
            elif not isinstance(content, str):
                content = str(content)
            return ParsedIntent(
                intent_type=IntentType.FINAL_ANSWER,
                raw_instruction=original_text,
                params={"content": content},
                natural_language=content,
                confidence=0.85
            )

        return None  # 无法识别，返回None

    def _parse_as_command(self, text: str) -> ParsedIntent | None:  # 解析为命令方法
        """  # 方法文档字符串开始
        解析分层交互命令  # 方法标题
        命令格式严格匹配，避免自然语言误触发  # 方法说明
        """  # 方法文档字符串结束
        # 1. 匹配 "查看 [分类名] 工具"  # 匹配规则1
        pattern_layer2 = r'查看[\s　]*([^\s　]+?)[\s　]*工具'  # 层级2模式
        match = re.search(pattern_layer2, text)  # 搜索匹配
        if match:  # 如果匹配成功
            category = match.group(1).strip()  # 提取分类名
            return ParsedIntent(  # 返回查询工具列表意图
                intent_type=IntentType.QUERY_TOOL_LIST,  # 查询工具列表类型
                raw_instruction=text,  # 原始指令
                params={"category": category},  # 分类参数
                confidence=0.95  # 高置信度
            )  # 返回结束

        # 2. 匹配 "查看工具详情 [工具ID]"  # 匹配规则2
        pattern_layer3 = r'查看工具详情[\s　]*([a-zA-Z0-9_]+)'  # 层级3模式
        match = re.search(pattern_layer3, text)  # 搜索匹配
        if match:  # 如果匹配成功
            tool_id = match.group(1).strip()  # 提取工具ID
            return ParsedIntent(  # 返回查询工具详情意图
                intent_type=IntentType.QUERY_TOOL_DETAIL,  # 查询工具详情类型
                raw_instruction=text,  # 原始指令
                params={"tool_id": tool_id},  # 工具ID参数
                confidence=0.95  # 高置信度
            )  # 返回结束

        # 3. 匹配 "返回" 相关命令  # 匹配规则3
        pattern_back = r'返回(?:分类|上一层)?'  # 返回模式
        if re.match(pattern_back, text):  # 如果匹配成功
            return ParsedIntent(  # 返回返回上一层意图
                intent_type=IntentType.BACK_TO_PREV,  # 返回上一层类型
                raw_instruction=text,  # 原始指令
                confidence=0.95  # 高置信度
            )  # 返回结束

        return None  # 没有匹配到命令，返回None

    def _parse_ai_computer_language(self, text: str) -> ParsedIntent | None:  # 解析AI计算机语言方法
        """  # 方法文档字符串开始
        解析AI计算机语言（L1L2L3提示词系统）  # 方法标题
        共19个计算机语言标记，分5个层次：  # 标记数量说明

        用户交互层: 呼叫用户、询问用户、等待确认、通知用户  # 层次1
        工具查询层: 查找工具  # 层次2
        记忆认知层: 查询记忆、记录记忆、删除记忆  # 层次3
        学习进化层: 进入学习、执行计划、反思、进化  # 层次4
        预测感知层: 世界模型预测、视觉识别、行为分析  # 层次5
        系统控制层: 暂停执行、恢复执行、终止任务  # 层次6
        """  # 方法文档字符串结束
        # ========== 用户交互层 ==========  # 用户交互层分隔线
        # 1. 匹配 (呼叫用户)  # 匹配标记1
        if re.search(r'\(\s*呼叫用户\s*\)', text):  # 搜索呼叫用户标记
            return ParsedIntent(  # 返回呼叫用户意图
                intent_type=IntentType.CALL_USER,  # 呼叫用户类型
                raw_instruction=text,  # 原始指令
                params={"action": "call_user"},  # 动作参数
                confidence=0.95  # 高置信度
            )  # 返回结束

        # 2. 匹配 (询问用户)  # 匹配标记2
        if re.search(r'\(\s*询问用户\s*\)', text):  # 搜索询问用户标记
            return ParsedIntent(  # 返回询问用户意图
                intent_type=IntentType.ASK_USER,  # 询问用户类型
                raw_instruction=text,  # 原始指令
                params={"action": "ask_user"},  # 动作参数
                confidence=0.95  # 高置信度
            )  # 返回结束

        # 3. 匹配 (等待确认)  # 匹配标记3
        if re.search(r'\(\s*等待确认\s*\)', text):  # 搜索等待确认标记
            return ParsedIntent(  # 返回等待确认意图
                intent_type=IntentType.WAIT_CONFIRM,  # 等待确认类型
                raw_instruction=text,  # 原始指令
                params={"action": "wait_confirm"},  # 动作参数
                confidence=0.95  # 高置信度
            )  # 返回结束

        # 4. 匹配 (通知用户) - 新增  # 匹配标记4
        notify_match = re.search(r'\(\s*通知用户[:：]\s*([^)]+)\)', text)  # 搜索带内容通知用户标记
        if notify_match:  # 如果匹配成功
            message = notify_match.group(1).strip()  # 提取消息内容
            return ParsedIntent(  # 返回通知用户意图
                intent_type=IntentType.NOTIFY_USER,  # 通知用户类型
                raw_instruction=text,  # 原始指令
                params={"action": "notify_user", "message": message},  # 动作和消息参数
                confidence=0.95  # 高置信度
            )  # 返回结束
        if re.search(r'\(\s*通知用户\s*\)', text):  # 搜索不带内容的通知用户标记
            return ParsedIntent(  # 返回通知用户意图
                intent_type=IntentType.NOTIFY_USER,  # 通知用户类型
                raw_instruction=text,  # 原始指令
                params={"action": "notify_user"},  # 动作参数
                confidence=0.95  # 高置信度
            )  # 返回结束

        # ========== 工具查询层 ==========  # 工具查询层分隔线
        # 5. 匹配 (查找工具)  # 匹配标记5
        if re.search(r'\(\s*查找工具\s*\)', text):  # 搜索查找工具标记
            return ParsedIntent(  # 返回查找工具意图
                intent_type=IntentType.FIND_TOOL,  # 查找工具类型
                raw_instruction=text,  # 原始指令
                params={"action": "find_tool"},  # 动作参数
                confidence=0.95  # 高置信度
            )  # 返回结束

        # ========== 记忆认知层 ==========  # 记忆认知层分隔线
        # 6. 匹配 (查询记忆)  # 匹配标记6
        if re.search(r'\(\s*查询记忆\s*\)', text):  # 搜索查询记忆标记
            return ParsedIntent(  # 返回查询记忆意图
                intent_type=IntentType.QUERY_MEMORY,  # 查询记忆类型
                raw_instruction=text,  # 原始指令
                params={"action": "query_memory"},  # 动作参数
                confidence=0.95  # 高置信度
            )  # 返回结束

        # 7. 匹配 (记录记忆) - 新增  # 匹配标记7
        record_match = re.search(r'\(\s*记录记忆[:：]\s*([^)]+)\)', text)  # 搜索带内容记录记忆标记
        if record_match:  # 如果匹配成功
            content = record_match.group(1).strip()  # 提取内容
            return ParsedIntent(  # 返回记录记忆意图
                intent_type=IntentType.RECORD_MEMORY,  # 记录记忆类型
                raw_instruction=text,  # 原始指令
                params={"action": "record_memory", "content": content},  # 动作和内容参数
                confidence=0.95  # 高置信度
            )  # 返回结束
        if re.search(r'\(\s*记录记忆\s*\)', text):  # 搜索不带内容的记录记忆标记
            return ParsedIntent(  # 返回记录记忆意图
                intent_type=IntentType.RECORD_MEMORY,  # 记录记忆类型
                raw_instruction=text,  # 原始指令
                params={"action": "record_memory"},  # 动作参数
                confidence=0.95  # 高置信度
            )  # 返回结束

        # 8. 匹配 (删除记忆) - 新增  # 匹配标记8
        delete_match = re.search(r'\(\s*删除记忆[:：]\s*([^)]+)\)', text)  # 搜索带内容删除记忆标记
        if delete_match:  # 如果匹配成功
            memory_id = delete_match.group(1).strip()  # 提取记忆ID
            return ParsedIntent(  # 返回删除记忆意图
                intent_type=IntentType.DELETE_MEMORY,  # 删除记忆类型
                raw_instruction=text,  # 原始指令
                params={"action": "delete_memory", "memory_id": memory_id},  # 动作和ID参数
                confidence=0.95  # 高置信度
            )  # 返回结束
        if re.search(r'\(\s*删除记忆\s*\)', text):  # 搜索不带内容的删除记忆标记
            return ParsedIntent(  # 返回删除记忆意图
                intent_type=IntentType.DELETE_MEMORY,  # 删除记忆类型
                raw_instruction=text,  # 原始指令
                params={"action": "delete_memory"},  # 动作参数
                confidence=0.95  # 高置信度
            )  # 返回结束

        # ========== 学习进化层 ==========  # 学习进化层分隔线
        # 9. 匹配 (进入学习)  # 匹配标记9
        if re.search(r'\(\s*进入学习\s*\)', text):  # 搜索进入学习标记
            return ParsedIntent(  # 返回进入学习意图
                intent_type=IntentType.ENTER_LEARNING,  # 进入学习类型
                raw_instruction=text,  # 原始指令
                params={"action": "enter_learning"},  # 动作参数
                confidence=0.95  # 高置信度
            )  # 返回结束

        # 10. 匹配 (执行计划)  # 匹配标记10
        if re.search(r'\(\s*执行计划\s*\)', text):  # 搜索执行计划标记
            return ParsedIntent(  # 返回执行计划意图
                intent_type=IntentType.EXECUTE_PLAN,  # 执行计划类型
                raw_instruction=text,  # 原始指令
                params={"action": "execute_plan"},  # 动作参数
                confidence=0.95  # 高置信度
            )  # 返回结束

        # 11. 匹配 (反思)  # 匹配标记11
        if re.search(r'\(\s*反思\s*\)', text):  # 搜索反思标记
            return ParsedIntent(  # 返回反思意图
                intent_type=IntentType.REFLECT,  # 反思类型
                raw_instruction=text,  # 原始指令
                params={"action": "reflect"},  # 动作参数
                confidence=0.95  # 高置信度
            )  # 返回结束

        # 12. 匹配 (进化)  # 匹配标记12
        if re.search(r'\(\s*进化\s*\)', text):  # 搜索进化标记
            return ParsedIntent(  # 返回进化意图
                intent_type=IntentType.EVOLVE,  # 进化类型
                raw_instruction=text,  # 原始指令
                params={"action": "evolve"},  # 动作参数
                confidence=0.95  # 高置信度
            )  # 返回结束

        # 12.5 匹配 (进化记忆)  # 匹配标记12.5
        if re.search(r'\(\s*进化记忆\s*\)', text):  # 搜索进化记忆标记
            return ParsedIntent(  # 返回进化记忆意图
                intent_type=IntentType.EVOLVE_MEMORY,  # 进化记忆类型
                raw_instruction=text,  # 原始指令
                params={"action": "evolve_memory"},  # 动作参数
                confidence=0.95  # 高置信度
            )  # 返回结束

        # ========== 预测感知层 ==========  # 预测感知层分隔线
        # 13. 匹配 (世界模型预测)  # 匹配标记13
        if re.search(r'\(\s*世界模型预测\s*\)', text):  # 搜索世界模型预测标记
            return ParsedIntent(  # 返回世界模型预测意图
                intent_type=IntentType.WORLD_MODEL_PREDICT,  # 世界模型预测类型
                raw_instruction=text,  # 原始指令
                params={"action": "world_model_predict"},  # 动作参数
                confidence=0.95  # 高置信度
            )  # 返回结束

        # 14. 匹配 (视觉识别)  # 匹配标记14
        if re.search(r'\(\s*视觉识别\s*\)', text):  # 搜索视觉识别标记
            return ParsedIntent(  # 返回视觉识别意图
                intent_type=IntentType.VISION_ANALYZE,  # 视觉识别类型
                raw_instruction=text,  # 原始指令
                params={"action": "vision_analyze"},  # 动作参数
                confidence=0.95  # 高置信度
            )  # 返回结束

        # 15. 匹配 (行为分析) - 新增  # 匹配标记15
        if re.search(r'\(\s*行为分析\s*\)', text):  # 搜索行为分析标记
            return ParsedIntent(  # 返回行为分析意图
                intent_type=IntentType.BEHAVIOR_ANALYZE,  # 行为分析类型
                raw_instruction=text,  # 原始指令
                params={"action": "behavior_analyze"},  # 动作参数
                confidence=0.95  # 高置信度
            )  # 返回结束

        # ========== 系统控制层 ==========  # 系统控制层分隔线
        # 16. 匹配 (暂停执行) - 新增  # 匹配标记16
        pause_match = re.search(r'\(\s*暂停执行[:：]\s*([^)]+)\)', text)  # 搜索带原因暂停执行标记
        if pause_match:  # 如果匹配成功
            reason = pause_match.group(1).strip()  # 提取原因
            return ParsedIntent(  # 返回暂停执行意图
                intent_type=IntentType.PAUSE_EXECUTION,  # 暂停执行类型
                raw_instruction=text,  # 原始指令
                params={"action": "pause_execution", "reason": reason},  # 动作和原因参数
                confidence=0.95  # 高置信度
            )  # 返回结束
        if re.search(r'\(\s*暂停执行\s*\)', text):  # 搜索不带原因的暂停执行标记
            return ParsedIntent(  # 返回暂停执行意图
                intent_type=IntentType.PAUSE_EXECUTION,  # 暂停执行类型
                raw_instruction=text,  # 原始指令
                params={"action": "pause_execution"},  # 动作参数
                confidence=0.95  # 高置信度
            )  # 返回结束

        # 17. 匹配 (恢复执行) - 新增  # 匹配标记17
        if re.search(r'\(\s*恢复执行\s*\)', text):  # 搜索恢复执行标记
            return ParsedIntent(  # 返回恢复执行意图
                intent_type=IntentType.RESUME_EXECUTION,  # 恢复执行类型
                raw_instruction=text,  # 原始指令
                params={"action": "resume_execution"},  # 动作参数
                confidence=0.95  # 高置信度
            )  # 返回结束

        # 18. 匹配 (终止任务) - 新增  # 匹配标记18
        terminate_match = re.search(r'\(\s*终止任务[:：]\s*([^)]+)\)', text)  # 搜索带原因终止任务标记
        if terminate_match:  # 如果匹配成功
            reason = terminate_match.group(1).strip()  # 提取原因
            return ParsedIntent(  # 返回终止任务意图
                intent_type=IntentType.TERMINATE_TASK,  # 终止任务类型
                raw_instruction=text,  # 原始指令
                params={"action": "terminate_task", "reason": reason},  # 动作和原因参数
                confidence=0.95  # 高置信度
            )  # 返回结束
        if re.search(r'\(\s*终止任务\s*\)', text):  # 搜索不带原因的终止任务标记
            return ParsedIntent(  # 返回终止任务意图
                intent_type=IntentType.TERMINATE_TASK,  # 终止任务类型
                raw_instruction=text,  # 原始指令
                params={"action": "terminate_task"},  # 动作参数
                confidence=0.95  # 高置信度
            )  # 返回结束

        # 19. 匹配 (提交理解摘要) - 新增（用于暂停确认流程）  # 匹配标记19
        understanding_match = re.search(r'\(\s*提交理解摘要[:：]?\s*\|?\s*([^)]+)\)', text, re.DOTALL)  # 搜索提交理解摘要标记
        if understanding_match:  # 如果匹配成功
            understanding = understanding_match.group(1).strip()  # 提取理解内容
            return ParsedIntent(  # 返回提交理解摘要意图
                intent_type=IntentType.SUBMIT_UNDERSTANDING,  # 提交理解摘要类型
                raw_instruction=text,  # 原始指令
                params={"action": "submit_understanding", "understanding": understanding},  # 动作和理解参数
                confidence=0.95  # 高置信度
            )  # 返回结束
        if re.search(r'\(\s*提交理解摘要\s*\)', text):  # 搜索不带内容的提交理解摘要标记
            return ParsedIntent(  # 返回提交理解摘要意图
                intent_type=IntentType.SUBMIT_UNDERSTANDING,  # 提交理解摘要类型
                raw_instruction=text,  # 原始指令
                params={"action": "submit_understanding"},  # 动作参数
                confidence=0.95  # 高置信度
            )  # 返回结束

        return None  # 没有匹配到任何AI计算机语言，返回None

    def _parse_as_natural_language(self, text: str) -> ParsedIntent:  # 解析为自然语言方法
        """自然语言解析（加强正则边界）"""  # 方法文档字符串
        # 优先检查明确的开头和包含关键词（任务指令）  # 优先检查注释

        # 强意图信号：用户明确说"打开"、"搜索"等动词  # 强意图注释
        strong_intent_patterns = [  # 强意图模式列表
            (r'打开\s*(.+?)(?:的|并|，|。|$)', 'launch_app', 'app_name'),  # 打开应用模式  # 模式1
            (r'启动\s*(.+?)(?:的|并|，|。|$)', 'launch_app', 'app_name'),  # 启动应用模式  # 模式2
            (r'搜索\s*["「]?(.*?)["」]?(?:的|并|，|。|$)', 'web_search', 'query'),  # 搜索模式  # 模式3
            (r'查找\s*["「]?(.*?)["」]?(?:的|并|，|。|$)', 'web_search', 'query'),  # 查找模式  # 模式4
            (r'点击\s*["「]?(.*?)["」]?(?:的|并|，|。|$)', 'click_text', 'text'),  # 点击模式  # 模式5
            (r'输入\s*["「]?(.*?)["」]?(?:的|并|，|。|$)', 'keyboard_input', 'text'),  # 输入模式  # 模式6
        ]  # 强意图模式列表结束

        for pattern, tool_id, param_name in strong_intent_patterns:  # 遍历强意图模式
            match = re.search(pattern, text)  # 搜索匹配
            if match:  # 如果匹配成功
                param_value = match.group(1).strip()  # 提取参数值
                if param_value:  # 如果参数值不为空
                    # 【修复】LLM 输出包含显式完成标记 [TASK_COMPLETE] 时，优先视为最终答案
                    # 避免将 LLM 的总结语（如"已成功为您打开XX"）误判为新的工具调用指令
                    if "[TASK_COMPLETE]" in text:
                        return ParsedIntent(
                            intent_type=IntentType.FINAL_ANSWER,
                            raw_instruction=text,
                            confidence=0.9
                        )
                    return ParsedIntent(  # 返回工具调用意图
                        intent_type=IntentType.TOOL_CALL,  # 工具调用类型
                        raw_instruction=text,  # 原始指令
                        target_tool=tool_id,  # 目标工具
                        params={param_name: param_value},  # 参数字典
                        confidence=0.9  # 高置信度
                    )  # 返回结束

        # 如果很短且没有工具关键词，可能是最终答案  # 最终答案判断注释
        if len(text) < 30 and not any(kw in text for kwlist in self.ACTION_KEYWORDS.values() for kw in kwlist):  # 文本短且无工具关键词
            return ParsedIntent(IntentType.FINAL_ANSWER, text, confidence=0.8)  # 返回最终答案意图

        # 尝试解析为计划（包含步骤编号）  # 计划解析注释
        steps = self._parse_plan(text)  # 尝试解析计划
        if steps:  # 如果解析出步骤
            return ParsedIntent(IntentType.PLAN, text, steps=steps, confidence=0.9)  # 返回计划意图

        # 尝试匹配工具调用（使用加强的正则）  # 工具匹配注释
        best_tool = None  # 最佳工具ID
        best_params = {}  # 最佳参数
        best_score = 0.0  # 最佳得分

        for tool_id, keywords in self.ACTION_KEYWORDS.items():  # 遍历所有工具关键词
            for kw in keywords:  # 遍历每个关键词
                # 使用 \b 边界匹配，避免部分匹配（如"点击"不应匹配"点击率"）  # 边界匹配注释
                pattern = r'\b' + re.escape(kw) + r'\b'  # 构建带边界的模式
                if re.search(pattern, text):  # 如果匹配成功
                    score = len(kw) / len(text) if len(text) > 0 else 0.5  # 计算得分（关键词越长得分越高）
                    if score > best_score:  # 如果得分更高
                        best_score = score  # 更新最佳得分
                        best_tool = tool_id  # 更新最佳工具
                        best_params = self._extract_params(text, tool_id)  # 提取参数

        if best_tool and best_score > 0.3:  # 如果有匹配工具且得分超过阈值
            # 特殊处理某些工具  # 特殊处理注释
            if best_tool == "click_text" and "text" not in best_params:  # 点击文本但无文本参数
                match = re.search(r'点击\s*["“]?([^"”]+)["”]?', text)  # 尝试提取文本
                if match:  # 如果匹配成功
                    best_params["text"] = match.group(1).strip()  # 提取文本参数
            if best_tool == "keyboard_input" and "text" not in best_params:  # 键盘输入但无文本参数
                match = re.search(r'输入\s*["“]([^"”]+)["”]', text)  # 尝试提取文本
                if not match:  # 如果没匹配到带引号的
                    match = re.search(r'输入\s*([^，。\s]+)', text)  # 尝试提取无引号文本
                if match:  # 如果匹配成功
                    best_params["text"] = match.group(1).strip()  # 提取文本参数
            if best_tool == "web_search" and "query" not in best_params:  # 网络搜索但无关键词参数
                match = re.search(r'搜索\s*["“]?([^"”]+)["”]?', text)  # 尝试提取关键词
                if match:  # 如果匹配成功
                    best_params["query"] = match.group(1).strip()  # 提取关键词参数
            return ParsedIntent(  # 返回工具调用意图
                intent_type=IntentType.TOOL_CALL,  # 工具调用类型
                raw_instruction=text,  # 原始指令
                target_tool=best_tool,  # 目标工具
                params=best_params,  # 参数
                confidence=best_score  # 置信度为得分
            )  # 返回结束

        # 默认作为最终答案  # 默认处理注释
        return ParsedIntent(IntentType.FINAL_ANSWER, text, confidence=0.5)  # 返回最终答案意图（低置信度）

    def _parse_plan(self, text: str) -> list:  # 解析计划方法
        plan_keywords = ["步骤", "计划", "step", "plan", "执行方案"]  # 计划关键词列表
        if not any(kw in text.lower() for kw in plan_keywords):  # 如果没有计划关键词
            return None  # 返回None

        lines = text.strip().split('\n')  # 按行分割文本
        steps = []  # 步骤列表
        step_pattern = r'^(\d+\.|\-|\*)\s*(.+)$'  # 步骤模式（序号、横线、星号开头）
        for line in lines:  # 遍历每一行
            line = line.strip()  # 去除首尾空白
            if not line:  # 如果为空行
                continue  # 跳过
            match = re.match(step_pattern, line)  # 匹配步骤模式
            if match:  # 如果匹配成功
                step_text = match.group(2).strip()  # 提取步骤文本
                step_intent = self.parse_ai_response(step_text)  # 递归解析步骤
                if step_intent.intent_type != IntentType.UNKNOWN:  # 如果不是未知意图
                    steps.append(step_intent)  # 添加到步骤列表
        return steps if steps else None  # 返回步骤列表（如果为空则返回None）

    def _extract_params(self, text: str, tool_id: str) -> dict:  # 提取参数方法
        params = {}  # 参数字典
        x_match = re.search(r'x[：:]\s*(\d+)', text)  # 匹配x坐标
        y_match = re.search(r'y[：:]\s*(\d+)', text)  # 匹配y坐标
        if x_match and y_match:  # 如果都匹配成功
            params["x"] = int(x_match.group(1))  # 提取x坐标
            params["y"] = int(y_match.group(1))  # 提取y坐标
        hwnd_match = re.search(r'hwnd[：:]\s*(\d+)', text)  # 匹配窗口句柄
        if hwnd_match:  # 如果匹配成功
            params["hwnd"] = int(hwnd_match.group(1))  # 提取窗口句柄
        if "右键" in text or "右击" in text:  # 如果包含右键关键词
            params["button"] = "right"  # 设置按钮为右键
        return params  # 返回参数字典

    def _parse_composite(self, instruction: str) -> ParsedIntent | None:  # 解析复合指令方法
        for pattern in self.COMPOSITE_PATTERNS:  # 遍历复合模式
            match = re.search(pattern, instruction)  # 搜索匹配
            if match:  # 如果匹配成功
                app_query = match.group(1).strip()  # 提取应用查询
                keyword = match.group(2).strip()  # 提取关键词
                app_mapping = self.app_manager.find_app(app_query)  # 查找应用映射
                if app_mapping:  # 如果找到应用
                    search_url = self.app_manager.get_search_url(app_mapping.name, keyword)  # 获取搜索URL
                    if search_url:  # 如果获取到URL
                        return ParsedIntent(  # 返回打开网页意图
                            intent_type=IntentType.OPEN_WEBSITE,  # 打开网页类型
                            raw_instruction=instruction,  # 原始指令
                            target_app=app_mapping.name,  # 目标应用
                            target_url=search_url,  # 目标URL
                            search_keyword=keyword,  # 搜索关键词
                            confidence=0.95  # 高置信度
                        )  # 返回结束
        return None  # 返回None

    def _parse_system_control(self, instruction: str) -> ParsedIntent | None:  # 解析系统控制方法
        inst_lower = instruction.lower()  # 转为小写
        for op, keywords in self.SYSTEM_CONTROL_KEYWORDS.items():  # 遍历系统控制关键词
            for kw in keywords:  # 遍历每个关键词
                if kw in inst_lower:  # 如果匹配成功
                    return ParsedIntent(  # 返回系统控制意图
                        intent_type=IntentType.SYSTEM_CONTROL,  # 系统控制类型
                        raw_instruction=instruction,  # 原始指令
                        operation=op,  # 操作
                        confidence=0.9  # 高置信度
                    )  # 返回结束
        return None  # 返回None

    def _parse_info_query(self, instruction: str) -> ParsedIntent | None:  # 解析信息查询方法
        inst_lower = instruction.lower()  # 转为小写
        if any(kw in inst_lower for kw in self.INFO_QUERY_KEYWORDS["price"]):  # 如果包含价格关键词
            return ParsedIntent(IntentType.QUERY_INFO, instruction, operation="price_query", confidence=0.85)  # 返回价格查询意图
        if any(kw in inst_lower for kw in self.INFO_QUERY_KEYWORDS["weather"]):  # 如果包含天气关键词
            return ParsedIntent(IntentType.QUERY_INFO, instruction, operation="weather_query", confidence=0.85)  # 返回天气查询意图
        if any(kw in inst_lower for kw in self.INFO_QUERY_KEYWORDS["time"]):  # 如果包含时间关键词
            return ParsedIntent(IntentType.QUERY_INFO, instruction, operation="time_query", confidence=0.9)  # 返回时间查询意图
        return None  # 返回None

    def _parse_open(self, instruction: str) -> ParsedIntent | None:  # 解析打开指令方法
        open_keywords = ["打开", "启动", "运行", "开启", "进入", "访问", "浏览", "去", "上", "帮我打开", "请打开"]  # 打开关键词列表
        inst_lower = instruction.lower()  # 转为小写
        if not any(kw in inst_lower for kw in open_keywords):  # 如果不包含打开关键词
            return None  # 返回None
        for kw in open_keywords:  # 遍历关键词
            if kw in inst_lower:  # 如果匹配
                idx = inst_lower.find(kw) + len(kw)  # 计算关键词后的位置
                remaining = instruction[idx:].strip()  # 提取剩余文本
                remaining = re.sub(r'^[的\s]+', '', remaining)  # 去除"的"和空格
                app_mapping = self.app_manager.find_app(remaining)  # 查找应用
                if app_mapping:  # 如果找到应用
                    if app_mapping.win_path:  # 如果有Windows路径
                        return ParsedIntent(  # 返回打开应用意图
                            intent_type=IntentType.OPEN_APP,  # 打开应用类型
                            raw_instruction=instruction,  # 原始指令
                            target_app=app_mapping.name,  # 目标应用
                            params={"win_path": app_mapping.win_path},  # Windows路径参数
                            confidence=0.9  # 高置信度
                        )  # 返回结束
                    else:  # 否则打开网页
                        url = self.app_manager.get_app_url(app_mapping.name)  # 获取应用URL
                        return ParsedIntent(  # 返回打开网页意图
                            intent_type=IntentType.OPEN_WEBSITE,  # 打开网页类型
                            raw_instruction=instruction,  # 原始指令
                            target_app=app_mapping.name,  # 目标应用
                            target_url=url or "",  # 目标URL
                            params={},  # 空参数
                            confidence=0.9  # 高置信度
                        )  # 返回结束
                else:  # 如果未找到应用映射
                    if re.match(r'^[a-zA-Z0-9\-]+\.[a-zA-Z]{2,}', remaining):  # 如果是域名格式
                        return ParsedIntent(IntentType.OPEN_WEBSITE, instruction, target_app=remaining, confidence=0.6)  # 返回打开网页意图
                    else:  # 否则当作应用打开
                        return ParsedIntent(IntentType.OPEN_APP, instruction, target_app=remaining, confidence=0.5)  # 返回打开应用意图
        return None  # 返回None

    def _parse_search(self, instruction: str) -> ParsedIntent | None:  # 解析搜索指令方法
        search_keywords = ["查", "查询", "搜", "搜索", "找", "查找"]  # 搜索关键词列表
        inst_lower = instruction.lower()  # 转为小写
        if not any(kw in inst_lower for kw in search_keywords):  # 如果不包含搜索关键词
            return None  # 返回None
        for kw in search_keywords:  # 遍历关键词
            if kw in inst_lower:  # 如果匹配
                idx = inst_lower.find(kw) + len(kw)  # 计算关键词后的位置
                keyword = instruction[idx:].strip()  # 提取关键词
                keyword = re.sub(r'^[的\s]+', '', keyword)  # 去除"的"和空格
                return ParsedIntent(  # 返回搜索意图
                    intent_type=IntentType.SEARCH,  # 搜索类型
                    raw_instruction=instruction,  # 原始指令
                    search_keyword=keyword,  # 搜索关键词
                    target_app="百度",  # 目标应用（百度）
                    target_url=f"https://www.baidu.com/s?wd={keyword}",  # 百度搜索URL
                    confidence=0.8  # 置信度
                )  # 返回结束
        return None  # 返回None


# =============================================================================  # 分隔线
# 【精准抓取】PrecisionParser - 纽带功能核心实现  # 精准抓取标题
# =============================================================================  # 分隔线

class PrecisionParser:  # 定义精准抓取解析器类
    """  # 类文档字符串开始
    精准抓取解析器 - 纽带功能  # 类标题

    连接：  # 连接说明
    1. 用户体验（抓取AI的自然语言 → 语音播报给用户）  # 连接1
    2. AI使用工具（抓取AI的计算机语言 → 执行对应操作）  # 连接2
    3. 执行结果反馈（抓取工具结果 → 反馈给AI）  # 连接3

    设计原则：  # 设计原则
    - 精准识别AI输出的各种标记类型  # 原则1
    - 分离自然语言和计算机语言  # 原则2
    - 支持语音播报和事件发布  # 原则3
    """  # 类文档字符串结束

    # 标记模式定义 - 使用代码块格式  # 标记模式注释
    # [2026-03-11 FIX] Added support for emoji marker format:
    #   💭 思考: ... / 📝 计划: ... / ⚡ 行动: ```json {...} ```
    MARKER_PATTERNS = {  # 标记模式字典
        AICodeMarker.TOOL_CALL: [  # 工具调用模式列表
            r"```tool\n(.*?)\n```",  # Markdown代码块格式  # 模式1
            r"<tool>(.*?)</tool>",  # XML标签格式  # 模式2
            r'"action"\s*:\s*"call_tool"',  # JSON格式  # 模式3
            r"⚡\s*行动[：:]\s*```(?:json)?\s*(\{.*?\})\s*```",  # Emoji action marker  # 模式4 [NEW]
            r"⚡\s*行动[：:]\s*(\{.*?\})",  # Emoji action without code block  # 模式5 [NEW]
        ],  # 工具调用模式列表结束
        AICodeMarker.FINAL_ANSWER: [  # 最终答案模式列表
            r"```final\n(.*?)\n```",  # Markdown代码块格式  # 模式1
            r"<final>(.*?)</final>",  # XML标签格式  # 模式2
            r'"action"\s*:\s*"final_answer"',  # JSON格式  # 模式3
        ],  # 最终答案模式列表结束
        AICodeMarker.EVOLVE_REFLECT: [  # 进化反思模式列表
            r"```evolve\n(.*?)\n```",  # Markdown代码块格式  # 模式1
            r"<evolve>(.*?)</evolve>",  # XML标签格式  # 模式2
            r"\(\s*反思\s*\)",  # 括号标记格式  # 模式3
            r"\(\s*进化\s*\)",  # 括号标记格式  # 模式4
        ],  # 进化反思模式列表结束
        AICodeMarker.WORLD_MODEL: [  # 世界模型模式列表
            r"```world\n(.*?)\n```",  # Markdown代码块格式  # 模式1
            r"<world>(.*?)</world>",  # XML标签格式  # 模式2
            r"\(\s*世界模型预测\s*\)",  # 括号标记格式  # 模式3
        ],  # 世界模型模式列表结束
        AICodeMarker.VISION_ANALYSIS: [  # 视觉分析模式列表
            r"```vision\n(.*?)\n```",  # Markdown代码块格式  # 模式1
            r"<vision>(.*?)</vision>",  # XML标签格式  # 模式2
            r"\(\s*视觉识别\s*\)",  # 括号标记格式  # 模式3
        ],  # 视觉分析模式列表结束
        AICodeMarker.CALL_USER: [  # 呼叫用户模式列表
            r"```call_user\n(.*?)\n```",  # Markdown代码块格式  # 模式1
            r"<call_user>(.*?)</call_user>",  # XML标签格式  # 模式2
            r"\(\s*呼叫用户\s*\)",  # 括号标记格式  # 模式3
        ],  # 呼叫用户模式列表结束
        AICodeMarker.ASK_CLARIFY: [  # 请求澄清模式列表
            r"```clarify\n(.*?)\n```",  # Markdown代码块格式  # 模式1
            r"<clarify>(.*?)</clarify>",  # XML标签格式  # 模式2
            r"\(\s*询问用户\s*\)",  # 括号标记格式  # 模式3
        ],  # 请求澄清模式列表结束
        AICodeMarker.LAYER_SWITCH: [  # 层级切换模式列表
            r"```layer\n(.*?)\n```",  # Markdown代码块格式  # 模式1
            r"<layer>(.*?)</layer>",  # XML标签格式  # 模式2
        ],  # 层级切换模式列表结束
        AICodeMarker.MEMORY_UPDATE: [  # 记忆更新模式列表
            r"```memory\n(.*?)\n```",  # Markdown代码块格式  # 模式1
            r"<memory>(.*?)</memory>",  # XML标签格式  # 模式2
            r"\(\s*记录记忆\s*\)",  # 括号标记格式  # 模式3
        ],  # 记忆更新模式列表结束
        AICodeMarker.TASK_COMPLETE: [  # 任务完成模式列表
            r"```complete\n(.*?)\n```",  # Markdown代码块格式  # 模式1
            r"<complete>(.*?)</complete>",  # XML标签格式  # 模式2
        ],  # 任务完成模式列表结束
    }  # 标记模式字典结束

    # 优先级顺序（越靠前优先级越高）  # 优先级注释
    MARKER_PRIORITY = [  # 标记优先级列表
        AICodeMarker.TOOL_CALL,  # 工具调用优先级1
        AICodeMarker.FINAL_ANSWER,  # 最终答案优先级2
        AICodeMarker.TASK_COMPLETE,  # 任务完成优先级3
        AICodeMarker.CALL_USER,  # 呼叫用户优先级4
        AICodeMarker.ASK_CLARIFY,  # 请求澄清优先级5
        AICodeMarker.EVOLVE_REFLECT,  # 进化反思优先级6
        AICodeMarker.WORLD_MODEL,  # 世界模型优先级7
        AICodeMarker.VISION_ANALYSIS,  # 视觉分析优先级8
        AICodeMarker.MEMORY_UPDATE,  # 记忆更新优先级9
        AICodeMarker.LAYER_SWITCH,  # 层级切换优先级10
    ]  # 标记优先级列表结束

    def __init__(self, voice_instance=None):  # 初始化方法
        """  # 方法文档字符串开始
        初始化精准抓取解析器  # 方法标题

        Args:  # 参数说明
            voice_instance: 语音实例，用于播报自然语言  # 参数
        """  # 方法文档字符串结束
        self.voice = voice_instance  # 设置语音实例
        self._event_bus = None  # 初始化事件总线为None
        self._last_parsed = None  # 初始化上一次解析结果为None

    def _get_event_bus(self):  # 获取事件总线方法
        """延迟加载事件总线"""  # 方法文档字符串
        if self._event_bus is None:  # 如果事件总线为None
            try:  # 尝试导入
                from core.sync.event_bus import event_bus  # 导入事件总线
                self._event_bus = event_bus  # 设置事件总线
            except ImportError:  # 导入失败
                logger.warning("[PrecisionParser] 事件总线不可用")  # 记录警告
        return self._event_bus  # 返回事件总线

    def parse_ai_output(self, ai_output: str) -> ParsedAIOutput:  # 解析AI输出方法
        """  # 方法文档字符串开始
        解析AI输出，分离自然语言和计算机语言  # 方法标题

        Args:  # 参数说明
            ai_output: AI的原始输出  # 参数

        Returns:  # 返回值说明
            ParsedAIOutput: 解析后的结构化数据  # 返回类型
        """  # 方法文档字符串结束
        if not ai_output:  # 如果AI输出为空
            return ParsedAIOutput(  # 返回空解析结果
                marker_type=AICodeMarker.UNKNOWN,  # 未知类型
                raw_content="",  # 空内容
                parsed_data={},  # 空数据
                natural_language="",  # 空自然语言
                should_speak=False  # 不播报
            )  # 返回结束

        # 1. 提取所有标记内容  # 步骤1注释
        markers = self._extract_markers(ai_output)  # 提取标记

        # 2. 确定主要标记类型  # 步骤2注释
        primary_marker = self._determine_primary_marker(markers)  # 确定主要标记

        # 【封印2】建议文本语义过滤：防止AI解释性/建议性文本被误判为工具调用
        if primary_marker == AICodeMarker.TOOL_CALL:
            explicit_tool_markers = [
                r"⚡\s*行动[：:]",
                r"```tool\s*\n",
                r"<tool>",
                r'"action"\s*:\s*"call_tool"',
            ]
            has_explicit_tool = any(re.search(p, ai_output) for p in explicit_tool_markers)

            suggestion_patterns = [
                r"【系统反思】", r"【系统提示】", r"【建议】",
                r"建议[：:]", r"建议您", r"请尝试", r"您可以",
                r"由于当前无法", r"当前无法直接调用", r"请使用替代工具",
                r"若需帮助.*请提供", r"请确认.*是否正确",
            ]
            suggestion_score = sum(1 for p in suggestion_patterns if re.search(p, ai_output))

            # 有建议特征且无明确工具调用标记 → 修正为FINAL_ANSWER
            if suggestion_score >= 2 and not has_explicit_tool:
                logger.info(f"[PrecisionParser-SuggestionFilter] 建议文本被误判为TOOL_CALL（得分{suggestion_score}），修正为FINAL_ANSWER")
                primary_marker = AICodeMarker.FINAL_ANSWER
                markers = {}  # 清空标记，防止后续解析出工具调用

        # 3. 提取自然语言部分（去除标记后的内容）  # 步骤3注释
        natural_lang = self._extract_natural_language(ai_output, markers)  # 提取自然语言

        # 【日志记录】记录解析前后的AI输出（诊断用）
        logger.info(f"[PrecisionParser] 解析前AI输出: {ai_output[:300]}")
        logger.info(f"[PrecisionParser] 解析后自然语言: {natural_lang[:300]}")

        # 4. 解析标记数据为结构化格式  # 步骤4注释
        parsed_data = self._parse_marker_data(primary_marker, markers, ai_output)  # 解析标记数据

        result = ParsedAIOutput(  # 创建解析结果
            marker_type=primary_marker,  # 标记类型
            raw_content=ai_output,  # 原始内容
            parsed_data=parsed_data,  # 解析数据
            natural_language=natural_lang,  # 自然语言
            should_speak=len(natural_lang.strip()) > 3  # 自然语言长度大于3才播报
        )  # 结果创建结束

        self._last_parsed = result  # 缓存结果
        return result  # 返回结果

    async def process_and_announce(self, ai_output: str, auto_speak: bool = True) -> ParsedAIOutput:  # 处理并播报方法
        """  # 方法文档字符串开始
        解析AI输出并播报自然语言部分  # 方法标题

        Args:  # 参数说明
            ai_output: AI的原始输出  # 参数1
            auto_speak: 是否自动播报  # 参数2

        Returns:  # 返回值说明
            ParsedAIOutput: 解析结果  # 返回类型
        """  # 方法文档字符串结束
        result = self.parse_ai_output(ai_output)  # 解析AI输出

        # 播报自然语言部分  # 播报注释
        if auto_speak and result.should_speak and self.voice:  # 如果需要自动播报且应该播报且有语音实例
            self._announce_natural_language(result)  # 播报自然语言

        # 发布解析事件  # 事件发布注释
        event_bus = self._get_event_bus()  # 获取事件总线
        if event_bus:  # 如果事件总线存在
            event_bus.emit("ai:output_parsed", {  # 发布事件
                "marker_type": result.marker_type.value,  # 标记类型
                "parsed_data": result.parsed_data,  # 解析数据
                "natural_language": result.natural_language,  # 自然语言
                "should_speak": result.should_speak  # 是否播报
            })  # 事件发布结束

        return result  # 返回结果

    def _extract_markers(self, text: str) -> dict[AICodeMarker, list[str]]:  # 提取标记方法
        """  # 方法文档字符串开始
        提取所有标记内容  # 方法标题

        Args:  # 参数说明
            text: AI输出文本  # 参数

        Returns:  # 返回值说明
            Dict[AICodeMarker, List[str]]: 标记类型到匹配内容的映射  # 返回类型
        """  # 方法文档字符串结束
        markers = {}  # 标记字典

        for marker_type, patterns in self.MARKER_PATTERNS.items():  # 遍历所有标记类型和模式
            matches = []  # 匹配列表
            for pattern in patterns:  # 遍历模式
                try:  # 尝试匹配
                    found = re.findall(pattern, text, re.DOTALL | re.IGNORECASE)  # 查找所有匹配
                    if found:  # 如果找到匹配
                        matches.extend(found)  # 添加到匹配列表
                except re.error as e:  # 正则错误
                    logger.debug(f"[PrecisionParser] 正则错误: {e}")  # 记录调试日志

            if matches:  # 如果有匹配
                markers[marker_type] = matches  # 添加到标记字典

        return markers  # 返回标记字典

    def _extract_natural_language(self, text: str, markers: dict[AICodeMarker, list[str]]) -> str:  # 提取自然语言方法
        """  # 方法文档字符串开始
        提取自然语言部分（去除所有标记）  # 方法标题

        Args:  # 参数说明
            text: 原始文本  # 参数1
            markers: 已提取的标记  # 参数2

        Returns:  # 返回值说明
            str: 自然语言部分  # 返回类型
        """  # 方法文档字符串结束
        cleaned = text  # 复制原文本

        # 移除所有代码块标记  # 移除标记注释
        for patterns in self.MARKER_PATTERNS.values():  # 遍历所有模式
            for pattern in patterns:  # 遍历每个模式
                with contextlib.suppress(re.error):  # 忽略正则错误
                    cleaned = re.sub(pattern, "", cleaned, flags=re.DOTALL | re.IGNORECASE)  # 替换为空

        # 【修复】移除JSON格式的内容（包括reply_to_user、action等）
        # 清理代码块中的JSON
        cleaned = re.sub(r'```json\s*[\s\S]*?```', '', cleaned)
        cleaned = re.sub(r'```[\s\S]*?```', '', cleaned)
        # 清理包含reply_to_user的JSON
        cleaned = re.sub(r'\{[^{}]*"reply_to_user"[^{}]*\}', '', cleaned)
        # 清理包含action的JSON
        cleaned = re.sub(r'\{[^{}]*"action"[^{}]*\}', '', cleaned)
        # 清理嵌套JSON（递归5层）
        for _ in range(5):
            new_cleaned = re.sub(r'\{[^{}]*\}', '', cleaned)
            if new_cleaned == cleaned:
                break
            cleaned = new_cleaned

        # [2026-03-11 FIX] 清理 💭思考 / 📝计划 / ⚡行动 标记
        cleaned = re.sub(r'💭\s*思考[：:]\s*', '', cleaned)  # 移除思考标记
        cleaned = re.sub(r'📝\s*计划[：:]\s*', '', cleaned)  # 移除计划标记
        cleaned = re.sub(r'⚡\s*行动[：:]\s*', '', cleaned)  # 移除行动标记

        # 清理多余空行和空格  # 清理注释
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)  # 将3个以上换行替换为2个
        cleaned = re.sub(r'\s{2,}', ' ', cleaned)  # 将2个以上空格替换为1个

        return cleaned.strip()  # 返回清理后的文本

    def _determine_primary_marker(self, markers: dict[AICodeMarker, list[str]]) -> AICodeMarker:  # 确定主要标记方法
        """  # 方法文档字符串开始
        确定主要标记类型（按优先级顺序）  # 方法标题

        Args:  # 参数说明
            markers: 已提取的标记  # 参数

        Returns:  # 返回值说明
            AICodeMarker: 主要标记类型  # 返回类型
        """  # 方法文档字符串结束
        for marker in self.MARKER_PRIORITY:  # 按优先级遍历
            if marker in markers:  # 如果标记存在
                return marker  # 返回该标记

        return AICodeMarker.UNKNOWN  # 返回未知类型

    def _parse_marker_data(self, marker_type: AICodeMarker,  # 解析标记数据方法
                          markers: dict[AICodeMarker, list[str]],  # 参数2
                          raw_text: str) -> dict[str, Any]:  # 参数3
        """  # 方法文档字符串开始
        解析标记数据为结构化格式  # 方法标题

        Args:  # 参数说明
            marker_type: 标记类型  # 参数1
            markers: 已提取的标记  # 参数2
            raw_text: 原始文本  # 参数3

        Returns:  # 返回值说明
            Dict: 解析后的结构化数据  # 返回类型
        """  # 方法文档字符串结束
        data = {}  # 数据字典

        try:  # 尝试解析
            if marker_type == AICodeMarker.TOOL_CALL:  # 如果是工具调用
                content = markers.get(marker_type, [""])[0] if markers.get(marker_type) else ""  # 获取内容
                # 尝试解析JSON  # JSON解析注释
                try:  # 尝试
                    if isinstance(content, str):  # 如果是字符串
                        json_data = json.loads(content)  # 解析JSON
                        data["tool"] = json_data.get("tool", "")  # 提取工具
                        data["params"] = json_data.get("params", {})  # 提取参数
                    else:  # 否则
                        data["raw"] = content  # 保存原始内容
                except json.JSONDecodeError:  # JSON解析错误
                    # 尝试从raw_text中提取工具调用  # 备用提取注释
                    data.update(self._extract_tool_call_from_json(raw_text))  # 提取工具调用
                    if not data:  # 如果没有提取到
                        data["raw"] = content  # 保存原始内容

            elif marker_type == AICodeMarker.FINAL_ANSWER:  # 如果是最终答案
                content = markers.get(marker_type, [""])[0] if markers.get(marker_type) else ""  # 获取内容
                try:  # 尝试解析JSON
                    if isinstance(content, str):  # 如果是字符串
                        json_data = json.loads(content)  # 解析JSON
                        data["content"] = json_data.get("content", content)  # 提取内容
                    else:  # 否则
                        data["content"] = content  # 保存内容
                except json.JSONDecodeError:  # JSON解析错误
                    data["content"] = content  # 保存内容

            elif marker_type == AICodeMarker.CALL_USER:  # 如果是呼叫用户
                content = markers.get(marker_type, [""])[0] if markers.get(marker_type) else ""  # 获取内容
                data["reason"] = content.strip() if isinstance(content, str) else ""  # 提取原因
                data["urgency"] = "normal"  # 设置紧急程度

            elif marker_type == AICodeMarker.ASK_CLARIFY:  # 如果是请求澄清
                content = markers.get(marker_type, [""])[0] if markers.get(marker_type) else ""  # 获取内容
                data["question"] = content.strip() if isinstance(content, str) else ""  # 提取问题

            elif marker_type == AICodeMarker.LAYER_SWITCH:  # 如果是层级切换
                content = markers.get(marker_type, [""])[0] if markers.get(marker_type) else ""  # 获取内容
                data["target_layer"] = content.strip() if isinstance(content, str) else ""  # 提取目标层级
                data["reason"] = "AI请求层级切换"  # 设置原因

            elif marker_type == AICodeMarker.EVOLVE_REFLECT:  # 如果是进化反思
                data["type"] = "reflection"  # 设置类型
                data["insights"] = []  # 初始化洞察列表

            elif marker_type == AICodeMarker.WORLD_MODEL:  # 如果是世界模型
                data["type"] = "world_model"  # 设置类型

            elif marker_type == AICodeMarker.VISION_ANALYSIS:  # 如果是视觉分析
                data["type"] = "vision"  # 设置类型

            else:  # 其他类型
                data["type"] = marker_type.value  # 设置类型值

        except Exception as e:  # 捕获异常
            logger.debug(f"[PrecisionParser] 解析标记数据失败: {e}")  # 记录调试日志
            data["parse_error"] = str(e)  # 保存错误信息

        return data  # 返回数据

    def _extract_tool_call_from_json(self, text: str) -> dict[str, Any]:  # 从JSON提取工具调用方法
        """  # 方法文档字符串开始
        从文本中提取JSON格式的工具调用（支持嵌套JSON）  # 方法标题

        Args:  # 参数说明
            text: 原始文本  # 参数

        Returns:  # 返回值说明
            Dict: 工具调用数据  # 返回类型
        """  # 方法文档字符串结束
        try:  # 尝试提取
            # [2026-03-11 FIX] 优先查找 ⚡ 行动: ```json {...} ``` 格式
            action_match = re.search(r'⚡\s*行动[：:]\s*```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
            if action_match:
                json_str = action_match.group(1)
                data = json.loads(json_str)
                return {
                    "tool": data.get("tool", ""),
                    "params": data.get("params", {})
                }

            # [2026-03-11 FIX] 查找 ⚡ 行动: {...} 格式（无代码块）
            action_match2 = re.search(r'⚡\s*行动[：:]\s*(\{.*?\})(?:\n|$)', text, re.DOTALL)
            if action_match2:
                json_str = action_match2.group(1)
                # 尝试解析，可能需要处理嵌套
                try:
                    data = json.loads(json_str)
                    return {
                        "tool": data.get("tool", ""),
                        "params": data.get("params", {})
                    }
                except json.JSONDecodeError:
                    # 可能是截断的JSON，尝试提取工具名
                    tool_match = re.search(r'"tool"\s*:\s*"([^"]+)"', json_str)
                    if tool_match:
                        return {"tool": tool_match.group(1), "params": {}}

            # 查找包含 "tool" 和 "params" 的完整JSON对象（支持嵌套）
            # 使用递归匹配来处理嵌套JSON
            json_pattern = r'\{(?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*\}'
            for match in re.finditer(json_pattern, text):
                try:
                    json_str = match.group()
                    if '"tool"' in json_str:
                        data = json.loads(json_str)
                        if "tool" in data:
                            return {
                                "tool": data.get("tool", ""),
                                "params": data.get("params", {})
                            }
                except (json.JSONDecodeError, Exception):
                    continue

            # 查找简化格式 {"action": "call_tool", ...}  # 简化格式查找注释
            match = re.search(r'\{[^{}]*"action"\s*:\s*"call_tool"[^{}]*\}', text)  # 匹配简化格式
            if match:  # 如果匹配成功
                data = json.loads(match.group())  # 解析JSON
                return {  # 返回工具调用数据
                    "tool": data.get("tool", ""),  # 工具
                    "params": data.get("params", {})  # 参数
                }  # 返回结束
        except (json.JSONDecodeError, Exception):  # JSON解析错误或异常
            pass  # 忽略错误

        return {}  # 返回空字典

    def _announce_natural_language(self, parsed: ParsedAIOutput):  # 播报自然语言方法
        """  # 方法文档字符串开始
        播报自然语言部分  # 方法标题

        Args:  # 参数说明
            parsed: 解析结果  # 参数
        """  # 方法文档字符串结束
        if not self.voice or not parsed.natural_language:  # 如果没有语音实例或没有自然语言
            return  # 直接返回

        natural_lang = parsed.natural_language  # 获取自然语言

        # 根据标记类型调整播报内容  # 调整播报注释
        if parsed.marker_type == AICodeMarker.TOOL_CALL:  # 如果是工具调用
            tool_name = parsed.parsed_data.get("tool", "")  # 获取工具名
            if tool_name:  # 如果有工具名
                natural_lang = f"正在使用{tool_name}工具"  # 调整为工具播报

        elif parsed.marker_type == AICodeMarker.FINAL_ANSWER:  # 如果是最终答案
            # 最终答案直接使用自然语言  # 直接使用注释
            pass  # 不修改

        elif parsed.marker_type == AICodeMarker.CALL_USER:  # 如果是呼叫用户
            reason = parsed.parsed_data.get("reason", "")  # 获取原因
            if reason:  # 如果有原因
                natural_lang = f"需要您协助: {reason}"  # 调整为协助播报

        # 限制播报长度  # 长度限制注释
        if len(natural_lang) > 100:  # 如果超过100字符
            natural_lang = natural_lang[:97] + "..."  # 截断并添加省略号

        # 执行播报  # 播报执行注释
        try:  # 尝试播报
            self.voice.speak(natural_lang, is_system=True, wait=False)  # 播报自然语言
            logger.debug(f"[PrecisionParser] 语音播报: {natural_lang}")  # 记录调试日志
        except Exception as e:  # 捕获异常
            logger.debug(f"[PrecisionParser] 播报失败: {e}")  # 记录调试日志

    def extract_tool_result_for_ai(self, tool_name: str, result: dict[str, Any]) -> str:  # 提取工具结果方法
        """  # 方法文档字符串开始
        提取工具执行结果，格式化为AI可理解的格式  # 方法标题

        Args:  # 参数说明
            tool_name: 工具名称  # 参数1
            result: 工具执行结果  # 参数2

        Returns:  # 返回值说明
            str: 格式化后的结果文本  # 返回类型
        """  # 方法文档字符串结束
        success = result.get("success", False)  # 获取成功标志
        message = result.get("user_message", "")  # 获取用户消息
        data = result.get("data", {})  # 获取数据

        status = "✓ 成功" if success else "✗ 失败"

        result_text = f"【工具执行结果】{tool_name} {status}\n"  # 构建结果文本

        if message:  # 如果有消息
            result_text += f"消息: {message}\n"  # 添加消息

        if data:  # 如果有数据
            result_text += f"数据: {json.dumps(data, ensure_ascii=False, indent=2)}\n"  # 添加数据

        return result_text  # 返回结果文本

    def get_last_parsed(self) -> ParsedAIOutput | None:  # 获取上一次解析结果方法
        """获取上一次解析结果"""  # 方法文档字符串
        return self._last_parsed  # 返回上一次解析结果

    def update_voice_instance(self, voice_instance):  # 更新语音实例方法
        """更新语音实例"""  # 方法文档字符串
        self.voice = voice_instance  # 更新语音实例


# =============================================================================  # 分隔线
# 【自然语言播报器】播报规则封装  # 自然语言播报器标题
# =============================================================================  # 分隔线

class NaturalLanguageAnnouncer:  # 定义自然语言播报器类
    """  # 类文档字符串开始
    自然语言播报规则 - 封装各种播报场景  # 类标题

    功能：  # 功能说明
    - 将AI的计算机语言转换为自然语言播报给用户  # 功能1
    - 统一的播报风格和长度控制  # 功能2
    """  # 类文档字符串结束

    def __init__(self, voice_instance=None):  # 初始化方法
        self.voice = voice_instance  # 设置语音实例
        self._last_announce_time = 0  # 初始化上次播报时间
        self._min_announce_interval = 3  # 最小播报间隔（秒）

    def set_voice(self, voice_instance):  # 设置语音实例方法
        """设置语音实例"""  # 方法文档字符串
        self.voice = voice_instance  # 更新语音实例

    def _should_announce(self) -> bool:  # 是否应该播报方法
        """检查是否应该播报（控制播报频率）"""  # 方法文档字符串
        import time  # 导入时间模块
        current_time = time.time()  # 获取当前时间
        if current_time - self._last_announce_time < self._min_announce_interval:  # 如果间隔小于最小间隔
            return False  # 返回False
        self._last_announce_time = current_time  # 更新上次播报时间
        return True  # 返回True

    def announce_tool_call(self, tool_name: str, params: dict, wait: bool = False):  # 播报工具调用方法
        """  # 方法文档字符串开始
        播报工具调用（自然语言）  # 方法标题

        Args:  # 参数说明
            tool_name: 工具名称  # 参数1
            params: 工具参数  # 参数2
            wait: 是否等待播报完成  # 参数3
        """  # 方法文档字符串结束
        if not self.voice or not self._should_announce():  # 如果没有语音实例或不应该播报
            return  # 直接返回

        # 【改进】工具名称映射到自然语言 - 更全面的映射表
        tool_names = {
            # 应用控制
            "launch_app": "启动应用",
            "close_app": "关闭应用",
            "mouse_click": "鼠标点击",
            "mouse_move": "鼠标移动",
            "keyboard_input": "键盘输入",
            "window_focus": "窗口聚焦",

            # 信息获取
            "web_search": "网络搜索",
            "screenshot": "截图",
            "screen_ocr": "屏幕识别",
            "get_clipboard": "获取剪贴板",

            # 文件操作
            "file_read": "读取文件",
            "file_write": "写入文件",
            "file_list": "浏览文件",
            "file_delete": "删除文件",

            # AI内部工具 - 不播报或换成人话
            "FINAL_ANSWER": None,  # 内部状态，不播报
            "final_answer": None,
            "SWITCH_MODE": None,   # 内部状态，不播报
            "switch_mode": None,
            "WAIT_USER_INPUT": None,  # 等待用户，不播报
            "wait_user_input": None,

            # 系统工具
            "code_generate": "生成代码",
            "code_execute": "执行代码",
            "code_review": "审查代码",
            " planner": "制定计划",
            "memory_query": "查询记忆",
            "memory_save": "保存记忆",

            # 未知工具默认处理
        }

        natural_name = tool_names.get(tool_name)

        # 【改进】内部工具不播报，未知工具使用简化描述
        if natural_name is None:
            # 内部状态工具，跳过播报
            return
        elif natural_name == tool_name:
            # 未知工具，使用简化描述避免技术术语
            from voice.voice_prompts import QueryAnnouncements
            message = QueryAnnouncements.PROCESSING
        else:
            # 已知工具，使用自然语言
            from voice.voice_prompts import QueryAnnouncements
            message = f"正在{natural_name}"

        try:  # 尝试播报
            self.voice.speak(message, is_system=True, wait=wait)  # 播报消息
        except Exception as e:  # 捕获异常
            logger.debug(f"[Announcer] 播报失败: {e}")  # 记录调试日志

    def announce_progress(self, step: int, total: int, description: str = ""):  # 播报进度方法
        """  # 方法文档字符串开始
        播报进度  # 方法标题

        Args:  # 参数说明
            step: 当前步骤  # 参数1
            total: 总步骤  # 参数2
            description: 步骤描述  # 参数3
        """  # 方法文档字符串结束
        if not self.voice or not self._should_announce():  # 如果没有语音实例或不应该播报
            return  # 直接返回

        messages = [  # 播报消息列表
            f"执行第{step}步，共{total}步",  # 消息1
            f"进度: {step}/{total}",  # 消息2
            f"正在进行第{step}步",  # 消息3
        ]  # 消息列表结束

        message = messages[step % len(messages)]  # 循环选择消息
        if description:  # 如果有描述
            message += f"，{description[:20]}"  # 添加描述（限制20字）

        try:  # 尝试播报
            self.voice.speak(message, is_system=True, wait=False)  # 播报消息
        except Exception as e:  # 捕获异常
            logger.debug(f"[Announcer] 播报失败: {e}")  # 记录调试日志

    def announce_query(self, query_type: str):  # 播报查询方法
        """  # 方法文档字符串开始
        播报查询状态  # 方法标题

        Args:  # 参数说明
            query_type: 查询类型  # 参数
        """  # 方法文档字符串结束
        if not self.voice:  # 如果没有语音实例
            return  # 直接返回

        from voice.voice_prompts import QueryAnnouncements
        messages = {  # 查询类型消息字典
            "tool": QueryAnnouncements.QUERY_TOOL,  # 工具查询  # 消息1
            "memory": QueryAnnouncements.QUERY_MEMORY,  # 记忆查询  # 消息2
            "layer": QueryAnnouncements.QUERY_LAYER,  # 层级查询  # 消息3
            "vision": QueryAnnouncements.QUERY_VISION,  # 视觉分析  # 消息4
            "world_model": QueryAnnouncements.QUERY_WORLD_MODEL,  # 世界模型  # 消息5
        }  # 消息字典结束

        message = messages.get(query_type, QueryAnnouncements.QUERY_LAYER)  # 获取对应消息

        try:  # 尝试播报
            self.voice.speak(message, is_system=True, wait=False)  # 播报消息
        except Exception as e:  # 捕获异常
            logger.debug(f"[Announcer] 播报失败: {e}")  # 记录调试日志

    def announce_result(self, success: bool, message: str = ""):  # 播报结果方法
        """  # 方法文档字符串开始
        播报执行结果  # 方法标题

        Args:  # 参数说明
            success: 是否成功  # 参数1
            message: 结果消息  # 参数2
        """  # 方法文档字符串结束
        if not self.voice:  # 如果没有语音实例
            return  # 直接返回

        from voice.voice_prompts import QueryAnnouncements
        if success:  # 如果成功
            msg = QueryAnnouncements.EXEC_DONE if not message else f"完成，{message[:20]}"  # 成功消息
        else:  # 否则
            msg = QueryAnnouncements.EXEC_FAILED if not message else f"失败，{message[:20]}"  # 失败消息

        try:  # 尝试播报
            self.voice.speak(msg, is_system=True, wait=False)  # 播报消息
        except Exception as e:  # 捕获异常
            logger.debug(f"[Announcer] 播报失败: {e}")  # 记录调试日志

    def announce_evolution(self, action: str = "reflect"):  # 播报进化方法
        """  # 方法文档字符串开始
        播报进化/反思状态  # 方法标题

        Args:  # 参数说明
            action: 动作类型 ("reflect", "evolve", "learn")  # 参数
        """  # 方法文档字符串结束
        if not self.voice:  # 如果没有语音实例
            return  # 直接返回

        from voice.voice_prompts import QueryAnnouncements
        messages = {  # 动作类型消息字典
            "reflect": QueryAnnouncements.EVOLUTION_REFLECT,  # 反思  # 消息1
            "evolve": QueryAnnouncements.EVOLUTION_EVOLVE,  # 进化  # 消息2
            "learn": QueryAnnouncements.EVOLUTION_LEARN,  # 学习  # 消息3
        }  # 消息字典结束

        message = messages.get(action, QueryAnnouncements.PROCESSING)  # 获取对应消息

        try:  # 尝试播报
            self.voice.speak(message, is_system=True, wait=False)  # 播报消息
        except Exception as e:  # 捕获异常
            logger.debug(f"[Announcer] 播报失败: {e}")  # 记录调试日志


# =============================================================================  # 分隔线
# 全局解析器单例  # 全局单例标题
# =============================================================================  # 分隔线

_intent_parser = None  # 意图解析器单例
_precision_parser = None  # 精准抓取解析器单例
_announcer = None  # 播报器单例


def get_intent_parser() -> NLPIntentParser:  # 获取意图解析器函数
    """获取意图解析器单例"""  # 函数文档字符串
    global _intent_parser  # 声明全局变量
    if _intent_parser is None:  # 如果单例为None
        _intent_parser = NLPIntentParser()  # 创建实例
    return _intent_parser  # 返回单例


def get_precision_parser(voice_instance=None) -> PrecisionParser:  # 获取精准抓取解析器函数
    """  # 函数文档字符串开始
    获取精准抓取解析器单例  # 函数标题

    Args:  # 参数说明
        voice_instance: 可选的语音实例  # 参数

    Returns:  # 返回值说明
        PrecisionParser: 精准抓取解析器实例  # 返回类型
    """  # 函数文档字符串结束
    global _precision_parser  # 声明全局变量
    if _precision_parser is None:  # 如果单例为None
        _precision_parser = PrecisionParser(voice_instance)  # 创建实例
    elif voice_instance is not None:  # 如果提供了语音实例
        _precision_parser.update_voice_instance(voice_instance)  # 更新语音实例
    return _precision_parser  # 返回单例


def get_announcer(voice_instance=None) -> NaturalLanguageAnnouncer:  # 获取播报器函数
    """  # 函数文档字符串开始
    获取自然语言播报器单例  # 函数标题

    Args:  # 参数说明
        voice_instance: 可选的语音实例  # 参数

    Returns:  # 返回值说明
        NaturalLanguageAnnouncer: 播报器实例  # 返回类型
    """  # 函数文档字符串结束
    global _announcer  # 声明全局变量
    if _announcer is None:  # 如果单例为None
        _announcer = NaturalLanguageAnnouncer(voice_instance)  # 创建实例
    elif voice_instance is not None:  # 如果提供了语音实例
        _announcer.set_voice(voice_instance)  # 设置语音实例
    return _announcer  # 返回单例


def reset_precision_parser():  # 重置精准抓取解析器函数
    """重置精准抓取解析器（用于测试）"""  # 函数文档字符串
    global _precision_parser  # 声明全局变量
    _precision_parser = None  # 重置为None


async def parse_ai_output_with_precision(ai_output: str, voice_instance=None, auto_speak: bool = True) -> ParsedAIOutput:  # 便捷函数
    """  # 函数文档字符串开始
    便捷函数：使用精准抓取解析AI输出  # 函数标题

    Args:  # 参数说明
        ai_output: AI的原始输出  # 参数1
        voice_instance: 语音实例  # 参数2
        auto_speak: 是否自动播报  # 参数3

    Returns:  # 返回值说明
        ParsedAIOutput: 解析结果  # 返回类型
    """  # 函数文档字符串结束
    parser = get_precision_parser(voice_instance)  # 获取解析器
    return await parser.process_and_announce(ai_output, auto_speak)  # 处理并返回结果


# =============================================================================
# 总结性注释：文件角色、关联关系与核心效果
# =============================================================================
#
# 【文件角色】
# 本文件（nlp_intent_parser.py）是 SiliconBase V5 系统的"自然语言意图解析中心"，
# 负责将用户的自然语言输入和AI的结构化输出解析为可执行的意图。
# 是连接用户、AI和系统功能的核心纽带。
#
# 【核心定位】
# - 意图理解引擎：将人类语言转换为机器可理解的结构化意图
# - AI输出解析器：解析AI的计算机语言（JSON、标记、命令）
# - 精准抓取器：分离AI输出中的自然语言和计算机语言（纽带功能）
# - 语音播报器：将系统状态转换为自然语言播报给用户
#
# 【核心类说明】
# 1. AICodeMarker(Enum): AI输出的计算机语言标记类型
#    - 16种标记类型：TOOL_CALL, FINAL_ANSWER, EVOLVE_REFLECT, WORLD_MODEL等
#    - 用于精准识别AI的特定输出
#
# 2. ParsedAIOutput(dataclass): 解析后的AI输出
#    - marker_type: 标记类型
#    - natural_language: 自然语言部分（用于语音播报）
#    - parsed_data: 结构化数据（用于执行）
#    - should_speak: 是否播报
#
# 3. IntentType(Enum): 意图类型枚举
#    - 36种意图：从OPEN_WEBSITE到SUBMIT_UNDERSTANDING
#    - 涵盖用户交互、工具查询、记忆认知、学习进化、预测感知、系统控制
#
# 4. NLPIntentParser: NLP意图解析器主类
#    - parse(): 解析用户输入（自然语言）
#    - parse_ai_response(): 解析AI响应（JSON > 命令 > AI语言 > 自然语言）
#    - 关键词匹配、正则提取、复合指令解析
#
# 5. PrecisionParser: 精准抓取解析器（纽带功能核心）
#    - parse_ai_output(): 解析AI输出，分离自然语言和计算机语言
#    - process_and_announce(): 解析并播报自然语言
#    - 标记优先级处理、事件发布、工具结果格式化
#
# 6. NaturalLanguageAnnouncer: 自然语言播报器
#    - announce_tool_call(): 播报工具调用
#    - announce_progress(): 播报进度
#    - announce_result(): 播报结果
#    - announce_evolution(): 播报进化状态
#
# 【AI计算机语言（L1L2L3提示词系统）- 19个标记】
# 用户交互层（4个）: 呼叫用户、询问用户、等待确认、通知用户
# 工具查询层（1个）: 查找工具
# 记忆认知层（3个）: 查询记忆、记录记忆、删除记忆
# 学习进化层（5个）: 进入学习、执行计划、反思、进化、进化记忆
# 预测感知层（3个）: 世界模型预测、视觉识别、行为分析
# 系统控制层（3个）: 暂停执行、恢复执行、终止任务
#
# 【关联文件】
# 1. core/app_mapping.py                - 应用映射管理
#    * 关系：NLPIntentParser使用其查找应用
#
# 2. core/ai_adapter.py                 - AI适配器
#    * 关系：可能用于AI二次确认
#
# 3. core/command_parser.py             - 命令解析器
#    * 关系：NLPIntentParser调用其解析分层命令
#
# 4. core/event_bus.py                  - 事件总线
#    * 关系：PrecisionParser发布解析事件
#
# 5. core/logger.py                     - 日志系统
#    * 关系：记录解析日志
#
# 【解析流程】
# User Input -> NLPIntentParser.parse()
#     |
#     +---> 复合指令解析
#     +---> 系统控制解析
#     +---> 信息查询解析
#     +---> 打开应用/网站解析
#     +---> 搜索指令解析
#     +---> 自然语言回退
#
# AI Output -> NLPIntentParser.parse_ai_response()
#     |
#     +---> JSON协议解析（工具调用、最终答案、计划）
#     +---> 分层命令解析
#     +---> AI计算机语言解析（19个标记）
#     +---> 自然语言回退
#
# 【精准抓取流程】
# AI Output -> PrecisionParser.parse_ai_output()
#     |
#     +---> _extract_markers() 提取所有标记
#     +---> _determine_primary_marker() 确定主要标记
#     +---> _extract_natural_language() 提取自然语言
#     +---> _parse_marker_data() 解析标记数据
#     +---> 返回 ParsedAIOutput
#
# 【达到的效果】
# 1. 多层级解析：支持JSON、命令、AI语言、自然语言四层解析
# 2. 精准抓取：准确分离AI的自然语言和计算机语言
# 3. 语音播报：将系统状态以自然语言播报给用户
# 4. 意图丰富：36种意图类型覆盖各种场景
# 5. 容错机制：解析失败时回退到自然语言
# 6. 事件驱动：通过事件总线与其他模块通信
# 7. 纽带功能：连接用户、AI、工具执行三大环节
#
# 【使用场景】
# - 用户说"打开Chrome搜索天气" -> 解析为复合指令
# - AI输出工具调用JSON -> 解析为TOOL_CALL意图
# - AI输出"(反思)刚才的步骤可以优化" -> 解析为REFLECT意图
# - AI输出包含自然语言和代码块 -> 精准分离并播报
#
# =============================================================================
