#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""
工具分类管理模块 V1.0
支持游戏化分层交互的工具分类系统

功能：
1. 工具自动分类（基于工具ID、名称、描述关键词）
2. 分类层级管理
3. 工具搜索和过滤
4. 游戏化元数据支持（解锁等级、经验值、图标等）
"""  # 模块文档字符串：说明模块功能和版本

# ===== 导入模块 =====
import threading  # 导入threading模块：提供线程锁用于实现单例模式的线程安全
from dataclasses import dataclass, field  # 从dataclasses导入：dataclass装饰器用于简化类定义、field用于定义默认值
from enum import Enum  # 从enum导入Enum类：用于定义工具分类枚举
from typing import (  # 从typing模块导入类型注解：Dict字典、List列表、Optional可选、Any任意类型、Set集合
    Any,
)


# ===== 工具分类枚举 =====
class ToolCategory(Enum):  # 定义工具分类枚举类：继承自Enum，定义12种标准工具分类
    """标准工具分类枚举"""  # 类文档字符串：说明这是一个标准工具分类枚举
    INPUT = "输入类"           # 枚举值：输入类，对应键盘、鼠标输入操作
    WINDOW = "窗口类"          # 枚举值：窗口类，对应窗口管理和操作
    FILE = "文件类"            # 枚举值：文件类，对应文件读写和管理
    WEB = "网页类"             # 枚举值：网页类，对应网页/网络操作
    MEMORY = "记忆类"          # 枚举值：记忆类，对应记忆存储/检索
    SYSTEM = "系统类"          # 枚举值：系统类，对应系统信息/控制
    SCREEN = "屏幕识别类"       # 枚举值：屏幕识别类，对应OCR、截图、视觉
    APP = "应用启动类"          # 枚举值：应用启动类，对应应用启动/管理
    AUTOMATION = "自动化类"     # 枚举值：自动化类，对应自动化工作流
    DATA = "数据处理类"         # 枚举值：数据处理类，对应数据导入/导出/处理
    COMMUNICATION = "通信类"    # 枚举值：通信类，对应通信/通知
    OTHER = "其他"             # 枚举值：其他，对应未分类工具


# ===== 分类元数据数据类 =====
@dataclass  # 使用@dataclass装饰器：自动生成__init__、__repr__、__eq__等方法
class CategoryMeta:  # 定义分类元数据类：存储每个工具分类的元信息
    """分类元数据"""  # 类文档字符串：说明这是分类的元数据
    name: str  # 字段：分类名称，类型str，显示用的中文名（如"输入类"）
    description: str  # 字段：分类描述，类型str，功能说明文字
    icon: str = "🔧"  # 字段：图标，类型str，默认"🔧"，用于游戏化显示的emoji图标
    unlock_level: int = 1  # 字段：解锁等级，类型int，默认1，用户达到此等级可使用该分类
    xp_bonus: int = 0      # 字段：经验加成，类型int，默认0，使用此类工具获得的额外经验
    color: str = "#808080" # 字段：UI颜色，类型str，默认"#808080"，分类在前端显示的颜色（十六进制）
    keywords: list[str] = field(default_factory=list)  # 字段：关键词列表，类型List[str]，默认空列表，用于自动分类匹配


# ===== 工具信息数据类 =====
@dataclass  # 使用@dataclass装饰器：简化类定义，自动生成构造函数等
class ToolInfo:  # 定义工具信息数据类：封装单个工具的完整信息
    """工具信息数据结构"""  # 类文档字符串：说明这是工具信息的数据结构
    # 基础信息字段
    id: str  # 字段：工具ID，类型str，唯一标识符
    name: str  # 字段：工具名称，类型str，人类可读的名称
    description: str  # 字段：工具描述，类型str，功能说明
    category: str  # 字段：所属分类，类型str，分类的名称（如"输入类"）
    # 参数相关字段
    parameters: dict[str, Any] = field(default_factory=dict)  # 字段：参数定义，类型Dict[str, Any]，默认空字典，工具的参数schema
    required: list[str] = field(default_factory=list)  # 字段：必填参数，类型List[str]，默认空列表，必需参数名列表
    example: dict[str, Any] = field(default_factory=dict)  # 字段：调用示例，类型Dict[str, Any]，默认空字典，工具调用示例
    # 游戏化字段
    xp_value: int = 10           # 字段：经验值，类型int，默认10，使用此工具获得的经验值
    unlock_level: int = 1        # 字段：解锁等级，类型int，默认1，用户等级要求
    rarity: str = "common"       # 字段：稀有度，类型str，默认"common"，可选值：common(普通)、rare(稀有)、epic(史诗)、legendary(传说)
    cooldown: int = 0            # 字段：冷却时间，类型int，默认0秒，再次使用的等待时间
    daily_limit: int = -1        # 字段：每日限制，类型int，默认-1表示无限制
    tags: list[str] = field(default_factory=list)  # 字段：标签列表，类型List[str]，默认空列表，用于搜索和过滤


# ===== 工具分类管理器类 =====
class ToolCategories:  # 定义工具分类管理器类：核心组件，统一管理工具分类
    """
    工具分类管理器

    单例模式，统一管理所有工具分类相关操作
    """  # 类文档字符串：说明这是工具分类管理器，使用单例模式

    # 类变量：单例相关
    _instance = None  # 类变量：单例实例引用，初始为None
    _lock = threading.Lock()  # 类变量：线程锁，用于单例创建的线程安全

    # 类变量：分类元数据定义，每个分类的详细配置字典
    CATEGORY_META = {  # 字典：键是ToolCategory枚举，值是CategoryMeta对象
        ToolCategory.INPUT: CategoryMeta(  # 键：INPUT枚举；值：输入类的CategoryMeta配置
            name="输入类",  # 参数：分类显示名称
            description="模拟键盘输入和鼠标操作",  # 参数：功能描述
            icon="⌨️",  # 参数：emoji图标
            unlock_level=1,  # 参数：等级1解锁（新手可用）
            xp_bonus=5,  # 参数：使用获得5点经验加成
            color="#4CAF50",  # 参数：绿色
            keywords=["keyboard", "mouse", "click", "input", "type", "press", "hotkey"]  # 参数：自动分类关键词列表
        ),  # INPUT配置结束
        ToolCategory.WINDOW: CategoryMeta(  # 键：WINDOW枚举；值：窗口类的CategoryMeta配置
            name="窗口类",  # 参数：分类显示名称
            description="窗口管理和操作",  # 参数：功能描述
            icon="🪟",  # 参数：emoji图标
            unlock_level=1,  # 参数：等级1解锁
            xp_bonus=3,  # 参数：3点经验加成
            color="#2196F3",  # 参数：蓝色
            keywords=["window", "focus", "minimize", "maximize", "resize", "hwnd", "rect"]  # 参数：关键词列表
        ),  # WINDOW配置结束
        ToolCategory.FILE: CategoryMeta(  # 键：FILE枚举；值：文件类的CategoryMeta配置
            name="文件类",  # 参数：分类显示名称
            description="文件读写和管理操作",  # 参数：功能描述
            icon="📁",  # 参数：emoji图标
            unlock_level=1,  # 参数：等级1解锁
            xp_bonus=5,  # 参数：5点经验加成
            color="#FF9800",  # 参数：橙色
            keywords=["file", "read", "write", "delete", "copy", "move", "directory", "folder"]  # 参数：关键词列表
        ),  # FILE配置结束
        ToolCategory.WEB: CategoryMeta(  # 键：WEB枚举；值：网页类的CategoryMeta配置
            name="网页类",  # 参数：分类显示名称
            description="网页浏览和网络请求",  # 参数：功能描述
            icon="🌐",  # 参数：emoji图标
            unlock_level=2,  # 参数：等级2解锁（需要一定经验）
            xp_bonus=8,  # 参数：较高经验值8点
            color="#9C27B0",  # 参数：紫色
            keywords=["web", "browser", "http", "url", "page", "fetch", "search", "automation"]  # 参数：关键词列表
        ),  # WEB配置结束
        ToolCategory.MEMORY: CategoryMeta(  # 键：MEMORY枚举；值：记忆类的CategoryMeta配置
            name="记忆类",  # 参数：分类显示名称
            description="记忆存储、检索和管理",  # 参数：功能描述
            icon="🧠",  # 参数：emoji图标
            unlock_level=1,  # 参数：等级1解锁
            xp_bonus=3,  # 参数：3点经验加成
            color="#E91E63",  # 参数：粉色
            keywords=["memory", "remember", "store", "search_memory"]  # 参数：关键词列表
        ),  # MEMORY配置结束
        ToolCategory.SYSTEM: CategoryMeta(  # 键：SYSTEM枚举；值：系统类的CategoryMeta配置
            name="系统类",  # 参数：分类显示名称
            description="系统信息和控制",  # 参数：功能描述
            icon="⚙️",  # 参数：emoji图标
            unlock_level=1,  # 参数：等级1解锁
            xp_bonus=5,  # 参数：5点经验加成
            color="#607D8B",  # 参数：蓝灰色
            keywords=["system", "info", "cpu", "memory_usage", "disk", "process", "kill"]  # 参数：关键词列表
        ),  # SYSTEM配置结束
        ToolCategory.SCREEN: CategoryMeta(  # 键：SCREEN枚举；值：屏幕识别类的CategoryMeta配置
            name="屏幕识别类",  # 参数：分类显示名称
            description="屏幕截图、OCR和元素定位",  # 参数：功能描述
            icon="👁️",  # 参数：emoji图标
            unlock_level=2,  # 参数：等级2解锁
            xp_bonus=10,  # 参数：高经验值10点（高级功能）
            color="#00BCD4",  # 参数：青色
            keywords=["ocr", "screen", "screenshot", "find_element", "locate", "pixel", "template", "visual"]  # 参数：关键词列表
        ),  # SCREEN配置结束
        ToolCategory.APP: CategoryMeta(  # 键：APP枚举；值：应用启动类的CategoryMeta配置
            name="应用启动类",  # 参数：分类显示名称
            description="应用启动和搜索",  # 参数：功能描述
            icon="🚀",  # 参数：emoji图标
            unlock_level=1,  # 参数：等级1解锁
            xp_bonus=3,  # 参数：3点经验加成
            color="#8BC34A",  # 参数：浅绿色
            keywords=["app", "launch", "start", "open", "run", "search"]  # 参数：关键词列表
        ),  # APP配置结束
        ToolCategory.AUTOMATION: CategoryMeta(  # 键：AUTOMATION枚举；值：自动化类的CategoryMeta配置
            name="自动化类",  # 参数：分类显示名称
            description="自动化任务和脚本",  # 参数：功能描述
            icon="🤖",  # 参数：emoji图标
            unlock_level=3,  # 参数：等级3解锁（高级用户）
            xp_bonus=15,  # 参数：最高经验值15点
            color="#FF5722",  # 参数：深橙色
            keywords=["task", "automation", "script", "code_generate", "wait"]  # 参数：关键词列表
        ),  # AUTOMATION配置结束
        ToolCategory.DATA: CategoryMeta(  # 键：DATA枚举；值：数据处理类的CategoryMeta配置
            name="数据处理类",  # 参数：分类显示名称
            description="数据导入、导出和处理",  # 参数：功能描述
            icon="📊",  # 参数：emoji图标
            unlock_level=2,  # 参数：等级2解锁
            xp_bonus=8,  # 参数：8点经验加成
            color="#3F51B5",  # 参数：靛蓝色
            keywords=["export", "data", "clipboard", "backup", "tron", "balance"]  # 参数：关键词列表
        ),  # DATA配置结束
        ToolCategory.COMMUNICATION: CategoryMeta(  # 键：COMMUNICATION枚举；值：通信类的CategoryMeta配置
            name="通信类",  # 参数：分类显示名称
            description="通信和通知功能",  # 参数：功能描述
            icon="📡",  # 参数：emoji图标
            unlock_level=2,  # 参数：等级2解锁
            xp_bonus=5,  # 参数：5点经验加成
            color="#009688",  # 参数：蓝绿色
            keywords=["call", "notify", "message", "vpn"]  # 参数：关键词列表
        ),  # COMMUNICATION配置结束
        ToolCategory.OTHER: CategoryMeta(  # 键：OTHER枚举；值：其他类的CategoryMeta配置
            name="其他",  # 参数：分类显示名称
            description="其他未分类工具",  # 参数：功能描述
            icon="📦",  # 参数：emoji图标
            unlock_level=1,  # 参数：等级1解锁
            xp_bonus=1,  # 参数：最低经验值1点
            color="#9E9E9E",  # 参数：灰色
            keywords=[]  # 参数：无特定关键词，空列表
        ),  # OTHER配置结束
    }  # CATEGORY_META字典结束

    # 类变量：工具ID到分类的特定映射（覆盖关键词匹配），优先使用此映射
    TOOL_ID_CATEGORY_MAP = {  # 字典：键是工具ID字符串，值是ToolCategory枚举
        # 输入类工具映射
        "keyboard_input": ToolCategory.INPUT,  # 映射：keyboard_input工具 → INPUT分类
        "mouse_click": ToolCategory.INPUT,  # 映射：mouse_click工具 → INPUT分类
        "pixel_click": ToolCategory.INPUT,  # 映射：pixel_click工具 → INPUT分类
        "click_text": ToolCategory.INPUT,  # 映射：click_text工具 → INPUT分类

        # 窗口类工具映射
        "window_focus": ToolCategory.WINDOW,  # 映射：window_focus工具 → WINDOW分类
        "window_get": ToolCategory.WINDOW,  # 映射：window_get工具 → WINDOW分类
        "window_action": ToolCategory.WINDOW,  # 映射：window_action工具 → WINDOW分类
        "window_rect": ToolCategory.WINDOW,  # 映射：window_rect工具 → WINDOW分类
        "wait_for_window": ToolCategory.WINDOW,  # 映射：wait_for_window工具 → WINDOW分类
        "open_and_focus": ToolCategory.WINDOW,  # 映射：open_and_focus工具 → WINDOW分类

        # 文件类工具映射
        "file_manager": ToolCategory.FILE,  # 映射：file_manager工具 → FILE分类

        # 网页类工具映射
        "web_open": ToolCategory.WEB,  # 映射：web_open工具 → WEB分类
        "web_search": ToolCategory.WEB,  # 映射：web_search工具 → WEB分类
        "web_fetch": ToolCategory.WEB,  # 映射：web_fetch工具 → WEB分类
        "web_parse": ToolCategory.WEB,  # 映射：web_parse工具 → WEB分类
        "web_automation": ToolCategory.WEB,  # 映射：web_automation工具 → WEB分类

        # 记忆类工具映射
        "memory_add": ToolCategory.MEMORY,  # 映射：memory_add工具 → MEMORY分类
        "memory_update": ToolCategory.MEMORY,  # 映射：memory_update工具 → MEMORY分类
        "memory_search": ToolCategory.MEMORY,  # 映射：memory_search工具 → MEMORY分类
        "memory_delete": ToolCategory.MEMORY,  # 映射：memory_delete工具 → MEMORY分类
        "memory_list": ToolCategory.MEMORY,  # 映射：memory_list工具 → MEMORY分类
        "delete_user_data": ToolCategory.MEMORY,  # 映射：delete_user_data工具 → MEMORY分类

        # 系统类工具映射
        "system_info": ToolCategory.SYSTEM,  # 映射：system_info工具 → SYSTEM分类
        "process_kill": ToolCategory.SYSTEM,  # 映射：process_kill工具 → SYSTEM分类
        "process_start": ToolCategory.SYSTEM,  # 映射：process_start工具 → SYSTEM分类

        # 屏幕识别类工具映射
        "pixel_capture": ToolCategory.SCREEN,  # 映射：pixel_capture工具 → SCREEN分类
        "screen_ocr": ToolCategory.SCREEN,  # 映射：screen_ocr工具 → SCREEN分类
        "window_ocr": ToolCategory.SCREEN,  # 映射：window_ocr工具 → SCREEN分类
        "ocr_text": ToolCategory.SCREEN,  # 映射：ocr_text工具 → SCREEN分类
        "find_screen_element": ToolCategory.SCREEN,  # 映射：find_screen_element工具 → SCREEN分类
        "template_match": ToolCategory.SCREEN,  # 映射：template_match工具 → SCREEN分类
        "template_record": ToolCategory.SCREEN,  # 映射：template_record工具 → SCREEN分类
        "pixel_color": ToolCategory.SCREEN,  # 映射：pixel_color工具 → SCREEN分类
        "pixel_monitor": ToolCategory.SCREEN,  # 映射：pixel_monitor工具 → SCREEN分类
        "visual_understand": ToolCategory.SCREEN,  # 映射：visual_understand工具 → SCREEN分类
        "get_perception": ToolCategory.SCREEN,  # 映射：get_perception工具 → SCREEN分类

        # 应用启动类工具映射
        "launch_app": ToolCategory.APP,  # 映射：launch_app工具 → APP分类
        "app_search": ToolCategory.APP,  # 映射：app_search工具 → APP分类

        # 自动化类工具映射
        "task_tools": ToolCategory.AUTOMATION,  # 映射：task_tools工具 → AUTOMATION分类
        "code_generate": ToolCategory.AUTOMATION,  # 映射：code_generate工具 → AUTOMATION分类

        # 数据处理类工具映射
        "export_data": ToolCategory.DATA,  # 映射：export_data工具 → DATA分类
        "clipboard": ToolCategory.DATA,  # 映射：clipboard工具 → DATA分类
        "clipboard_get": ToolCategory.DATA,  # 映射：clipboard_get工具 → DATA分类
        "clipboard_set": ToolCategory.DATA,  # 映射：clipboard_set工具 → DATA分类
        "tron_balance_updater": ToolCategory.DATA,  # 映射：tron_balance_updater工具 → DATA分类

        # 通信类工具映射
        "call_user": ToolCategory.COMMUNICATION,  # 映射：call_user工具 → COMMUNICATION分类
        "vpn_connect": ToolCategory.COMMUNICATION,  # 映射：vpn_connect工具 → COMMUNICATION分类
        "vpn_check": ToolCategory.COMMUNICATION,  # 映射：vpn_check工具 → COMMUNICATION分类

        # 工具手册类工具映射
        "get_tool_manual": ToolCategory.OTHER,
        "get_tool_categories_l1": ToolCategory.OTHER,
        "get_tools_by_category_l2": ToolCategory.OTHER,
        "get_tool_detail_l3": ToolCategory.OTHER,
        "switch_prompt_layer": ToolCategory.OTHER,
    }  # TOOL_ID_CATEGORY_MAP字典结束

    # 类变量：工具稀有度和经验值配置，游戏化系统设计
    TOOL_RARITY_CONFIG = {  # 字典：键是稀有度字符串，值是配置字典
        # 普通工具配置
        "common": {  # 键：common（普通）
            "xp_value": 10,  # 值：10点经验
            "color": "#9E9E9E",  # 值：灰色
            "unlock_level": 1  # 值：等级1解锁
        },  # common配置结束
        # 稀有工具配置
        "rare": {  # 键：rare（稀有）
            "xp_value": 25,  # 值：25点经验
            "color": "#2196F3",  # 值：蓝色
            "unlock_level": 2  # 值：等级2解锁
        },  # rare配置结束
        # 史诗工具配置
        "epic": {  # 键：epic（史诗）
            "xp_value": 50,  # 值：50点经验
            "color": "#9C27B0",  # 值：紫色
            "unlock_level": 3  # 值：等级3解锁
        },  # epic配置结束
        # 传说工具配置
        "legendary": {  # 键：legendary（传说）
            "xp_value": 100,  # 值：100点经验
            "color": "#FF9800",  # 值：橙色
            "unlock_level": 5  # 值：等级5解锁
        }  # legendary配置结束
    }  # TOOL_RARITY_CONFIG字典结束

    # ===== 单例模式实现 =====
    def __new__(cls):  # 重写__new__方法：实现单例模式，确保只有一个实例
        if cls._instance is None:  # 条件判断：检查实例是否已存在，如果是None则创建
            with cls._lock:  # 上下文管理器：获取线程锁，确保线程安全
                if cls._instance is None:  # 双重检查：再次确认实例不存在（防止多线程竞争）
                    cls._instance = super().__new__(cls)  # 调用父类__new__：创建实例对象
                    cls._instance._initialized = False  # 实例属性：标记实例为未初始化状态
        return cls._instance  # 返回语句：返回单例实例（已存在或新创建的）

    # ===== 初始化方法 =====
    def __init__(self):  # 定义初始化方法：设置实例属性
        if self._initialized:  # 条件判断：检查是否已初始化
            return  # 如果已初始化，直接返回，避免重复初始化
        self._initialized = True  # 实例属性：标记为已初始化
        self._rw_lock = threading.RLock()  # 实例属性：创建读写锁，用于保护工具缓存的线程安全
        self._tool_cache: dict[str, ToolInfo] = {}  # 实例属性：工具缓存字典，键是工具ID，值是ToolInfo对象

    # ===== 工具分类方法 =====
    def classify_tool(self, tool_id: str, tool_name: str = "", tool_description: str = "") -> ToolCategory:  # 定义自动分类方法
        """
        根据工具ID、名称和描述自动分类

        Args:
            tool_id: 工具ID字符串
            tool_name: 工具名称字符串（可选，默认空字符串）
            tool_description: 工具描述字符串（可选，默认空字符串）

        Returns:
            ToolCategory 分类枚举值
        """  # 方法文档字符串：说明方法功能、参数和返回值
        # 步骤1：首先检查特定映射（优先级最高）
        if tool_id in self.TOOL_ID_CATEGORY_MAP:  # 条件判断：检查工具ID是否在TOOL_ID_CATEGORY_MAP字典中
            return self.TOOL_ID_CATEGORY_MAP[tool_id]  # 如果在映射中，直接返回映射的分类（最高优先级）

        # 步骤2：否则使用关键词匹配进行分类
        search_text = f"{tool_id} {tool_name} {tool_description}".lower()  # 字符串拼接：组合ID、名称、描述，并转小写便于匹配

        best_category = ToolCategory.OTHER  # 变量初始化：默认分类为OTHER（其他），作为兜底选项
        max_matches = 0  # 变量初始化：最大匹配数初始为0

        # 步骤3：遍历所有分类进行关键词匹配
        for category, meta in self.CATEGORY_META.items():  # for循环：遍历CATEGORY_META字典，category是枚举键，meta是CategoryMeta值
            if category == ToolCategory.OTHER:  # 条件判断：跳过OTHER分类（作为默认选项，不参与匹配竞争）
                continue  # 跳过当前迭代，进入下一个分类
            # 统计关键词匹配数：对meta.keywords列表中每个关键词kw，检查是否出现在search_text中，返回匹配的总数
            matches = sum(1 for kw in meta.keywords if kw.lower() in search_text)  # 生成器表达式：统计匹配的关键词数量
            if matches > max_matches:  # 条件判断：如果当前分类的匹配数大于之前的最大值
                max_matches = matches  # 更新最大值：将当前匹配数设为新的最大值
                best_category = category  # 更新最佳分类：将当前分类设为最佳匹配
        # for循环结束

        return best_category  # 返回语句：返回最佳匹配的分类（如果没有匹配到，返回OTHER）

    # ===== 获取分类元数据方法 =====
    def get_category_meta(self, category: ToolCategory) -> CategoryMeta:  # 定义获取分类元数据方法
        """获取分类元数据"""  # 方法文档字符串
        # 从CATEGORY_META字典获取元数据，如果找不到返回OTHER分类的元数据作为默认值
        return self.CATEGORY_META.get(category, self.CATEGORY_META[ToolCategory.OTHER])  # 字典get方法：获取分类元数据，带默认值

    # ===== 根据名称获取分类方法 =====
    def get_category_by_name(self, name: str) -> ToolCategory | None:  # 定义根据名称获取分类方法
        """根据分类名称获取枚举"""  # 方法文档字符串
        for cat in ToolCategory:  # for循环：遍历ToolCategory枚举的所有成员
            if cat.value == name:  # 条件判断：检查枚举值（中文名）是否与传入的名称匹配
                return cat  # 如果匹配，返回该枚举成员
        return None  # 如果遍历完都没有匹配，返回None表示未找到

    # ===== 获取所有分类信息方法 =====
    def get_all_categories(self) -> dict[str, dict[str, Any]]:  # 定义获取所有分类信息方法
        """
        获取所有分类信息

        Returns:
            字典：键是分类名，值是包含description、icon、unlock_level等字段的字典
        """  # 方法文档字符串
        result = {}  # 变量初始化：创建空字典用于存储结果
        for _category, meta in self.CATEGORY_META.items():  # for循环：遍历所有分类元数据
            result[meta.name] = {  # 字典赋值：以分类名称为键，构建分类信息字典
                "description": meta.description,  # 字段：分类描述
                "icon": meta.icon,  # 字段：图标
                "unlock_level": meta.unlock_level,  # 字段：解锁等级
                "xp_bonus": meta.xp_bonus,  # 字段：经验加成
                "color": meta.color,  # 字段：UI颜色
                "tools": []  # 字段：工具列表，初始为空列表
            }  # 内层字典结束
        # for循环结束
        return result  # 返回结果字典

    # ===== 批量分类工具方法 =====
    def categorize_tools(self, tools: list[dict[str, Any]]) -> dict[str, list[str]]:  # 定义批量分类工具方法
        """
        批量分类工具

        Args:
            tools: 工具列表，每个元素是包含id、name、description的字典

        Returns:
            字典：键是分类名，值是该分类下的工具ID列表
        """  # 方法文档字符串
        # 初始化分类字典：为每个ToolCategory创建一个空列表
        categories = {cat.value: [] for cat in ToolCategory}  # 字典推导式：键是分类值（中文名），值是空列表

        for tool in tools:  # for循环：遍历传入的工具列表
            tool_id = tool.get("id", "")  # 获取工具ID：从字典获取"id"字段，如果不存在返回空字符串
            tool_name = tool.get("name", "")  # 获取工具名称：从字典获取"name"字段，如果不存在返回空字符串
            tool_desc = tool.get("description", "")  # 获取工具描述：从字典获取"description"字段，如果不存在返回空字符串

            category = self.classify_tool(tool_id, tool_name, tool_desc)  # 调用classify_tool方法：自动分类工具
            categories[category.value].append(tool_id)  # 将工具ID添加到对应分类的列表中
        # for循环结束

        # 过滤空分类：只返回非空的分类（有工具的分类）
        return {k: v for k, v in categories.items() if v}  # 字典推导式：过滤掉值为空列表的项

    # ===== 获取工具稀有度方法 =====
    def get_tool_rarity(self, tool_id: str) -> str:  # 定义获取工具稀有度方法
        """根据工具ID判断稀有度"""  # 方法文档字符串
        # 定义稀有工具列表：高价值工具标记为rare
        rare_tools = [  # 列表：包含稀有工具的ID
            "code_generate",  # 代码生成工具
            "web_automation",  # 网页自动化工具
            "visual_understand",  # 视觉理解工具
            "tron_balance_updater",  # TRON余额更新工具
            "task_tools"  # 任务工具
        ]  # rare_tools列表结束
        # 定义史诗工具列表：更高价值的工具
        epic_tools = ["vpn_connect", "delete_user_data"]  # 列表：包含史诗工具的ID

        # 判断并返回稀有度
        if tool_id in epic_tools:  # 条件判断：检查工具ID是否在史诗工具列表中
            return "epic"  # 如果在，返回"epic"（史诗）
        elif tool_id in rare_tools:  # 条件判断：检查工具ID是否在稀有工具列表中
            return "rare"  # 如果在，返回"rare"（稀有）
        else:  # 其他情况
            return "common"  # 返回"common"（普通），作为默认值

    # ===== 构建工具信息对象方法 =====
    def build_tool_info(  # 定义构建工具信息对象方法
        self,  # 实例方法参数：self
        tool_id: str,  # 参数：工具ID字符串
        tool_name: str,  # 参数：工具名称字符串
        tool_description: str,  # 参数：工具描述字符串
        input_schema: dict[str, Any],  # 参数：输入参数模式字典（JSON Schema格式）
        output_schema: dict[str, Any] = None,  # 参数：输出模式字典，可选，默认None
        timeout: int = 30  # 参数：超时时间秒数，可选，默认30秒
    ) -> ToolInfo:  # 返回类型：ToolInfo对象
        """
        构建完整的工具信息对象

        Args:
            tool_id: 工具唯一标识符
            tool_name: 工具显示名称
            tool_description: 工具功能描述
            input_schema: 输入参数的JSON Schema定义
            output_schema: 输出格式的JSON Schema定义（可选）
            timeout: 工具执行超时时间（秒）

        Returns:
            ToolInfo 完整工具信息对象
        """  # 方法文档字符串
        # 步骤1：自动分类工具
        category = self.classify_tool(tool_id, tool_name, tool_description)  # 调用classify_tool：获取工具分类
        # 步骤2：获取工具稀有度
        rarity = self.get_tool_rarity(tool_id)  # 调用get_tool_rarity：获取稀有度字符串
        # 步骤3：获取稀有度配置
        rarity_config = self.TOOL_RARITY_CONFIG.get(rarity, self.TOOL_RARITY_CONFIG["common"])  # 获取配置，默认common

        # 步骤4：构建示例参数
        example_params = {}  # 变量初始化：创建空字典存储示例参数
        # 从input_schema获取参数定义
        properties = input_schema.get("properties", {}) if input_schema else {}  # 条件表达式：获取properties字段，如果没有或input_schema为None则返回空字典
        # 从input_schema获取必填参数列表
        required = input_schema.get("required", []) if input_schema else []  # 条件表达式：获取required字段，如果没有则返回空列表

        # 遍历参数定义，为每个参数生成示例值
        for param_name, param_info in properties.items():  # for循环：遍历properties字典，param_name是参数名，param_info是参数定义
            # 获取参数类型，如果param_info是字典则取"type"字段，否则默认为"string"
            param_type = param_info.get("type", "string") if isinstance(param_info, dict) else "string"  # 条件表达式：安全获取参数类型
            # 根据参数类型生成对应的示例值，用于展示工具调用示例
            if param_type == "string":  # 条件判断：字符串类型
                example_params[param_name] = f"示例_{param_name}"  # 生成示例值：格式为"示例_参数名"
            elif param_type == "integer":  # 条件判断：整数类型
                example_params[param_name] = 100  # 生成示例值：使用100作为示例整数
            elif param_type == "number":  # 条件判断：浮点数类型
                example_params[param_name] = 1.5  # 生成示例值：使用1.5作为示例浮点数
            elif param_type == "boolean":  # 条件判断：布尔类型
                example_params[param_name] = True  # 生成示例值：使用True作为示例布尔值
            elif param_type == "array":  # 条件判断：数组类型
                example_params[param_name] = []  # 生成示例值：使用空列表作为示例数组
            elif param_type == "object":  # 条件判断：对象类型
                example_params[param_name] = {}  # 生成示例值：使用空字典作为示例对象
            else:  # 其他未知类型
                example_params[param_name] = None  # 生成示例值：使用None作为默认值
        # for循环结束

        # 步骤5：创建并返回ToolInfo对象
        return ToolInfo(  # 返回语句：创建ToolInfo实例
            id=tool_id,  # 参数赋值：工具ID
            name=tool_name,  # 参数赋值：工具名称
            description=tool_description,  # 参数赋值：工具描述
            category=category.value,  # 参数赋值：分类名称（枚举值转字符串）
            parameters=properties,  # 参数赋值：参数定义
            required=required,  # 参数赋值：必填参数列表
            example={  # 参数赋值：调用示例字典
                "tool": tool_id,  # 示例字段：工具ID
                "params": example_params  # 示例字段：示例参数
            },  # example字典结束
            xp_value=rarity_config["xp_value"],  # 参数赋值：经验值（从稀有度配置获取）
            unlock_level=rarity_config["unlock_level"],  # 参数赋值：解锁等级（从稀有度配置获取）
            rarity=rarity,  # 参数赋值：稀有度字符串
            tags=[category.value]  # 参数赋值：标签列表，包含分类名
        )  # ToolInfo构造结束

    # ===== 根据用户等级过滤工具方法 =====
    def filter_tools_by_level(  # 定义根据用户等级过滤工具方法
        self,  # 实例方法参数：self
        tools: list[ToolInfo],  # 参数：工具列表，元素类型ToolInfo
        user_level: int  # 参数：用户当前等级，整数
    ) -> list[ToolInfo]:  # 返回类型：过滤后的ToolInfo列表
        """
        根据用户等级过滤可使用的工具

        Args:
            tools: ToolInfo工具对象列表
            user_level: 用户当前等级（整数）

        Returns:
            过滤后的ToolInfo列表（只包含已解锁的工具）
        """  # 方法文档字符串
        # 使用列表推导式过滤：只保留unlock_level小于等于user_level的工具
        return [t for t in tools if t.unlock_level <= user_level]  # 列表推导式：条件过滤，t表示每个工具对象

    # ===== 搜索工具方法 =====
    def search_tools(  # 定义搜索工具方法
        self,  # 实例方法参数：self
        tools: list[ToolInfo],  # 参数：工具列表，要搜索的范围
        query: str,  # 参数：搜索关键词字符串
        search_in_description: bool = True  # 参数：是否在描述中搜索，可选，默认True
    ) -> list[ToolInfo]:  # 返回类型：匹配的ToolInfo列表
        """
        搜索工具

        Args:
            tools: ToolInfo工具对象列表（搜索范围）
            query: 搜索关键词
            search_in_description: 是否在描述中搜索（默认True）

        Returns:
            匹配关键词的工具列表
        """  # 方法文档字符串
        query = query.lower()  # 字符串方法：将查询词转小写，实现不区分大小写的搜索
        results = []  # 变量初始化：创建空列表存储搜索结果

        for tool in tools:  # for循环：遍历工具列表
            # 检查条件1：工具ID或名称是否包含查询词
            if query in tool.id.lower() or query in tool.name.lower() or search_in_description and query in tool.description.lower() or any(query in tag.lower() for tag in tool.tags):  # 条件判断：检查ID或名称（都转小写）
                results.append(tool)  # 如果匹配，将工具添加到结果列表
        # for循环结束

        return results  # 返回搜索结果列表

    # ===== 获取已解锁分类方法 =====
    def get_unlocked_categories(self, user_level: int) -> list[str]:  # 定义获取已解锁分类方法
        """
        获取用户已解锁的分类列表

        Args:
            user_level: 用户当前等级（整数）

        Returns:
            已解锁的分类名称列表（字符串列表）
        """  # 方法文档字符串
        unlocked = []  # 变量初始化：创建空列表存储已解锁分类
        for _category, meta in self.CATEGORY_META.items():  # for循环：遍历分类元数据
            if meta.unlock_level <= user_level:  # 条件判断：检查分类的解锁等级是否小于等于用户等级
                unlocked.append(meta.name)  # 如果已解锁，将分类名称添加到列表
        # for循环结束
        return unlocked  # 返回已解锁分类名称列表

    # ===== 获取分类解锁进度方法 =====
    def get_category_progress(self, user_level: int) -> dict[str, Any]:  # 定义获取分类解锁进度方法
        """
        获取分类解锁进度（游戏化）

        Args:
            user_level: 用户当前等级

        Returns:
            字典包含：
            - unlocked: 已解锁分类列表
            - locked: 锁定分类列表
            - next_unlock: 下一个可解锁的分类信息
            - total_categories: 总分类数
            - unlocked_count: 已解锁数量
        """  # 方法文档字符串
        unlocked = []  # 变量初始化：已解锁分类列表
        locked = []  # 变量初始化：锁定分类列表
        next_unlock = None  # 变量初始化：下一个解锁信息，初始为None
        min_level_for_locked = float('inf')  # 变量初始化：锁定分类中的最小等级，初始为无穷大

        for _category, meta in self.CATEGORY_META.items():  # for循环：遍历所有分类
            if meta.unlock_level <= user_level:  # 条件判断：如果分类解锁等级小于等于用户等级
                # 已解锁，添加到unlocked列表
                unlocked.append({  # 字典：包含分类的基本信息
                    "name": meta.name,  # 字段：分类名称
                    "icon": meta.icon,  # 字段：图标
                    "xp_bonus": meta.xp_bonus  # 字段：经验加成
                })  # append结束
            else:  # 否则，分类处于锁定状态
                # 锁定，添加到locked列表
                locked.append({  # 字典：包含分类的基本信息和解锁要求
                    "name": meta.name,  # 字段：分类名称
                    "icon": meta.icon,  # 字段：图标
                    "required_level": meta.unlock_level  # 字段：需要的解锁等级
                })  # append结束
                # 检查是否是最低等级的锁定分类（即下一个可以解锁的）
                if meta.unlock_level < min_level_for_locked:  # 条件判断：如果当前锁定分类的等级比之前记录的更低
                    min_level_for_locked = meta.unlock_level  # 更新最小等级记录
                    next_unlock = {  # 创建下一个解锁信息字典
                        "category": meta.name,  # 字段：分类名称
                        "required_level": meta.unlock_level  # 字段：需要的等级
                    }  # next_unlock字典结束
            # if-else结束
        # for循环结束

        # 构建并返回结果字典
        return {  # 返回字典：包含完整的解锁进度信息
            "unlocked": unlocked,  # 字段：已解锁分类列表
            "locked": locked,  # 字段：锁定分类列表
            "next_unlock": next_unlock,  # 字段：下一个可解锁的分类
            "total_categories": len(self.CATEGORY_META),  # 字段：总分类数（使用len计算）
            "unlocked_count": len(unlocked)  # 字段：已解锁数量（使用len计算）
        }  # 返回字典结束


# ===== 功能分类定义（用于AI层展示） =====
# 这些分类用于前端L1/L2/L3层级展示，与ToolCategory枚举保持对应关系
FUNCTIONAL_CATEGORIES = {
    "📋 任务管理": {
        "description": "定时任务、提醒、计划管理",
        "tools": ["create_task", "list_tasks", "get_task", "update_task", "delete_task"],
        "category_enum": ToolCategory.AUTOMATION,
    },
    "📁 文件操作": {
        "description": "文件读写、目录管理、导入导出",
        "tools": ["file_manager", "export_data", "delete_user_data"],
        "category_enum": ToolCategory.FILE,
    },
    "🔧 系统控制": {
        "description": "系统设置、进程管理、信息查询",
        "tools": ["system_info", "process_kill", "process_start", "current_time",
                 "list_installed_apps", "app_search"],
        "category_enum": ToolCategory.SYSTEM,
    },
    "🌐 网络通信": {
        "description": "网页搜索、HTTP请求、网络自动化",
        "tools": ["web_search", "web_open", "web_fetch", "web_parse", "web_automation"],
        "category_enum": ToolCategory.WEB,
    },
    "📊 数据处理": {
        "description": "剪贴板、数据导入导出、格式转换",
        "tools": ["clipboard", "clipboard_get", "clipboard_set", "export_data",
                 "tron_balance_updater", "call_user"],
        "category_enum": ToolCategory.DATA,
    },
    "🎵 媒体处理": {
        "description": "截图、OCR、视觉识别、屏幕监控",
        "tools": ["pixel_capture", "pixel_monitor", "pixel_click", "pixel_color",
                 "screen_ocr", "window_ocr", "ocr_text", "find_screen_element",
                 "template_match", "template_record", "template_list", "template_delete",
                 "visual_understand", "icon_recognize", "get_perception",
                 "vision_agent", "ui_tars"],
        "category_enum": ToolCategory.SCREEN,
    },
    "💻 代码开发": {
        "description": "代码生成、开发辅助",
        "tools": ["code_generate"],
        "category_enum": ToolCategory.AUTOMATION,
    },
    "🔐 安全工具": {
        "description": "VPN连接、安全检查、隐私保护",
        "tools": ["vpn_connect", "vpn_check"],
        "category_enum": ToolCategory.COMMUNICATION,
    },
    "🚀 应用操作": {
        "description": "启动应用、窗口管理、自动化操作",
        "tools": ["launch_app", "open_and_focus", "find_and_click", "smart_form_fill",
                 "wait_for_window", "window_focus", "window_get", "window_action",
                 "window_rect", "window_ocr"],
        "category_enum": ToolCategory.APP,
    },
    "⌨️ 输入控制": {
        "description": "模拟键盘、鼠标、点击操作",
        "tools": ["keyboard_input", "mouse_click", "click_text", "pixel_click"],
        "category_enum": ToolCategory.INPUT,
    },
    "🧠 记忆管理": {
        "description": "记忆存储、搜索、更新、删除",
        "tools": ["memory_add", "memory_search", "memory_list", "memory_update", "memory_delete"],
        "category_enum": ToolCategory.MEMORY,
    },
    "📖 工具手册": {
        "description": "L1/L2/L3层级导航、工具查询",
        "tools": ["get_tool_manual", "get_tool_categories_l1", "get_tools_by_category_l2",
                 "get_tool_detail_l3", "switch_prompt_layer"],
        "category_enum": ToolCategory.OTHER,
    },
}


def get_functional_categories() -> dict[str, dict[str, Any]]:
    """
    获取功能分类定义（用于AI层展示）

    Returns:
        Dict[str, Dict[str, Any]]: 功能分类字典，键是分类显示名称，值包含描述和工具列表
    """
    return FUNCTIONAL_CATEGORIES.copy()


def get_functional_category_for_tool(tool_id: str) -> str | None:
    """
    根据工具ID获取其所属的功能分类名称

    Args:
        tool_id: 工具ID

    Returns:
        Optional[str]: 功能分类名称，未找到返回None
    """
    for category_name, category_info in FUNCTIONAL_CATEGORIES.items():
        if tool_id in category_info.get("tools", []):
            return category_name
    return None


def get_tool_category_mapping() -> dict[str, str]:
    """
    获取工具ID到功能分类名称的映射

    Returns:
        Dict[str, str]: 工具ID -> 功能分类名称
    """
    mapping = {}
    for category_name, category_info in FUNCTIONAL_CATEGORIES.items():
        for tool_id in category_info.get("tools", []):
            mapping[tool_id] = category_name
    return mapping


# ===== 全局单例实例 =====
# 创建模块级单例实例，供全系统使用
tool_categories = ToolCategories()  # 实例化ToolCategories类，创建单例对象


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase_V5 系统的"工具分类管理模块"，提供工具自动分类、
# 游戏化元数据管理和分类层级管理功能。是工具系统的核心支撑组件。
#
# 【架构设计】
# - ToolCategory: 工具分类枚举，定义12种标准分类（INPUT/WINDOW/FILE等）
# - CategoryMeta: 分类元数据数据类，包含游戏化属性（unlock_level/xp_bonus/icon/color）
# - ToolInfo: 工具信息数据类，封装工具完整信息和游戏化字段（rarity/xp_value/tags）
# - ToolCategories: 工具分类管理器（单例模式），统一管理分类相关操作
#
# 【12种标准分类】
# - 等级1解锁（新手）: INPUT(输入类)、WINDOW(窗口类)、FILE(文件类)、MEMORY(记忆类)、
#                      SYSTEM(系统类)、APP(应用启动类)、OTHER(其他)
# - 等级2解锁（进阶）: WEB(网页类)、SCREEN(屏幕识别类)、DATA(数据处理类)、COMMUNICATION(通信类)
# - 等级3解锁（高级）: AUTOMATION(自动化类)
#
# 【游戏化系统】
# - 稀有度分级: common(普通10xp) / rare(稀有25xp) / epic(史诗50xp) / legendary(传说100xp)
# - 解锁等级: 1 / 2 / 3 / 5
# - 分类经验加成: 使用特定分类工具获得额外经验（如INPUT类+5xp）
# - 进度追踪: get_category_progress()显示已解锁、锁定、下一个解锁目标
#
# 【关键类变量】
# - CATEGORY_META: Dict[ToolCategory, CategoryMeta] - 12种分类的详细配置
# - TOOL_ID_CATEGORY_MAP: Dict[str, ToolCategory] - 工具ID到分类的特定映射
# - TOOL_RARITY_CONFIG: Dict[str, Dict] - 稀有度配置（经验值/颜色/解锁等级）
#
# 【关联文件】
# - core/tool_manager.py      : 调用classify_tool()进行工具分类
# - core/tool_registry.py     : 使用build_tool_info()构建工具信息
# - ui/components/tool_ui.py  : 使用get_category_meta()获取图标/颜色渲染UI
# - api/tool_api.py           : 调用get_unlocked_categories()等提供接口
#
# 【核心方法数据流向】
# classify_tool(): tool_id → TOOL_ID_CATEGORY_MAP检查 → 关键词匹配 → ToolCategory
# build_tool_info(): input_schema + classify_tool() + get_tool_rarity() → ToolInfo
# categorize_tools(): List[Dict] → 遍历classify_tool() → Dict[分类名, List[tool_id]]
# filter_tools_by_level(): List[ToolInfo] + user_level → 过滤unlock_level → 可用工具
# search_tools(): List[ToolInfo] + query → ID/名称/描述/标签匹配 → 匹配结果
# get_category_progress(): user_level → 遍历CATEGORY_META → 解锁进度字典
#
# 【使用场景】
# 场景1: 工具注册 → classify_tool(tool_id, name, desc) → 自动确定分类
# 场景2: 构建工具信息 → build_tool_info(id, name, schema) → 完整ToolInfo对象
# 场景3: UI展示 → get_category_meta(category) → 获取图标/颜色/描述
# 场景4: 用户升级 → get_category_progress(level) → 显示解锁进度和下一个目标
# 场景5: 工具列表 → filter_tools_by_level(tools, user_level) → 显示可用工具
# 场景6: 搜索工具 → search_tools(tools, "关键词") → 匹配的工具列表
# 场景7: 批量分类 → categorize_tools(tools_list) → 按分类组织的工具
# =============================================================================
