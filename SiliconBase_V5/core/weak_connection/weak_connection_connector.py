#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""  # 多行文档字符串开始
弱连接连接器 - 连接感知层到弱连接引擎  # 模块功能概述：感知层与弱连接引擎的桥梁
订阅perception bus，转换事件格式  # 核心职责：事件订阅和格式转换
"""  # 文档字符串结束

from core.logger import logger  # 从日志模块导入日志记录器
from core.weak_connection.weak_connection import get_weak_connection_engine  # 导入弱连接引擎获取函数


class WeakConnectionConnector:  # 定义弱连接连接器类，作为感知层和弱连接引擎的桥梁
    """
    弱连接连接器
    订阅感知层事件，转换为弱连接引擎可用的格式
    """

    _instance = None  # 单例模式：类变量

    def __new__(cls):  # 重写__new__实现单例模式
        if cls._instance is None:  # 如果实例不存在
            cls._instance = super().__new__(cls)  # 创建实例
        return cls._instance  # 返回单例

    def __init__(self):  # 初始化方法
        if hasattr(self, '_initialized'):  # 如果已初始化
            return  # 直接返回
        self._initialized = False  # 初始化标志为False（表示尚未启动）
        self._subscribed = False  # 订阅标志为False

    def start(self):  # 启动连接器的方法
        """启动连接器，订阅感知层事件"""
        if self._initialized:  # 如果已经启动
            return  # 直接返回

        try:  # 异常捕获
            from sensors.system.bus import bus  # 从感知模块导入感知总线

            # 订阅感知总线
            bus.subscribe(self._on_perception_data)  # 注册感知数据回调
            self._subscribed = True  # 标记为已订阅

            logger.info("[WeakConnectionConnector] 已订阅感知层事件")  # 记录日志
            self._initialized = True  # 标记为已初始化

        except Exception as e:  # 捕获异常
            logger.error(f"[WeakConnectionConnector] 启动失败: {e}")  # 记录错误

    async def _on_perception_data(self, data):  # 处理感知数据的回调方法
        """
        感知数据回调
        将PerceptionData转换为ContextEvent
        """
        try:  # 异常捕获
            # 只处理窗口相关事件
            if data.source != "window":  # 如果数据来源不是窗口
                return  # 直接返回

            content = data.content  # 获取数据内容
            windows = content.get("windows", [])  # 获取窗口列表
            if not windows:  # 如果窗口列表为空
                return  # 直接返回

            # 获取最前面的窗口
            active_window = windows[0]  # 取第一个窗口（最前面的窗口）
            title = active_window.get("title", "")  # 获取窗口标题
            window_class = active_window.get("class", "")  # 获取窗口类名

            if not title:  # 如果标题为空
                return  # 直接返回

            # 提取关键词
            keywords = self._extract_keywords(title)  # 从标题提取关键词

            # 创建上下文事件
            from sensors.system.context_triggers import ContextEvent, ContextType  # 导入事件类

            event = ContextEvent(  # 创建ContextEvent对象
                type=ContextType.WINDOW_FOCUSED,  # 事件类型：窗口聚焦
                timestamp=data.timestamp,  # 时间戳
                source="window_monitor",  # 来源
                keywords=keywords,  # 关键词列表
                raw_data={  # 原始数据
                    "window_title": title,  # 窗口标题
                    "window_class": window_class,  # 窗口类名
                    "app_name": self._extract_app_name(title, window_class)  # 应用名称
                }
            )

            # 发送给弱连接引擎
            weak_engine = get_weak_connection_engine()  # 获取弱连接引擎实例
            await weak_engine.on_context_event(event)  # 传递事件给引擎

        except Exception as e:  # 捕获异常
            logger.debug(f"[WeakConnectionConnector] 处理感知数据失败: {e}")  # 记录调试日志

    def _extract_keywords(self, title: str) -> list:  # 从标题提取关键词的私有方法
        """提取关键词"""
        keywords = []  # 初始化关键词列表
        title_lower = title.lower()  # 转为小写

        keyword_map = {  # 关键词映射表（类别 -> 关键词列表）
            "报表": ["报表", "统计", "数据", "分析"],  # 报表相关
            "代码": ["代码", "编程", "开发", "vscode", "pycharm"],  # 代码相关
            "文档": ["文档", "word", "写作"],  # 文档相关
            "表格": ["表格", "excel", "sheet"],  # 表格相关
            "PPT": ["ppt", "演示", "powerpoint"],  # PPT相关
        }

        for category, words in keyword_map.items():  # 遍历关键词映射
            if any(w in title_lower for w in words):  # 如果标题包含任一关键词
                keywords.append(category)  # 添加类别到关键词列表

        return keywords  # 返回关键词列表

    def _extract_app_name(self, title: str, window_class: str) -> str:  # 提取应用名称的私有方法
        """提取应用名称"""
        app_map = {  # 应用标识映射表
            "excel": "Excel",  # Excel
            "winword": "Word",  # Word
            "powerpnt": "PowerPoint",  # PowerPoint
            "chrome": "Chrome",  # Chrome
            "code": "VSCode",  # VSCode
        }

        class_lower = window_class.lower()  # 类名转小写
        title_lower = title.lower()  # 标题转小写

        for key, name in app_map.items():  # 遍历应用映射
            if key in class_lower or key in title_lower:  # 如果类名或标题包含标识
                return name  # 返回应用名称

        # 从标题提取（通常是最后一部分）
        if " - " in title:  # 如果标题包含" - "分隔符
            return title.split(" - ")[-1].strip()  # 返回最后一部分作为应用名

        return "应用"  # 默认返回"应用"


# 全局实例
_connector = None  # 初始化全局连接器实例变量为None

def get_weak_connection_connector() -> WeakConnectionConnector:  # 获取连接器实例的函数
    """获取连接器实例"""  # 函数文档字符串
    global _connector  # 声明使用全局变量
    if _connector is None:  # 如果实例尚未创建
        _connector = WeakConnectionConnector()  # 创建连接器实例
    return _connector  # 返回全局实例

def start_weak_connection():  # 启动弱连接系统的便捷函数
    """启动弱连接系统"""  # 函数文档字符串
    connector = get_weak_connection_connector()  # 获取连接器实例
    connector.start()  # 启动连接器

# ═══════════════════════════════════════════════════════════════════════════════
# 【文件总结】
# ═══════════════════════════════════════════════════════════════════════════════
#
# 【文件角色】
# 本文件(weak_connection_connector.py)是SiliconBase V5核心模块中的弱连接连接器。
# 它作为感知层(perception)和弱连接引擎之间的桥梁，负责订阅感知事件、
# 转换事件格式，并将转换后的事件传递给弱连接引擎处理。
#
# 【在系统中的位置】
# - 位于: SiliconBase_V5/core/weak_connection_connector.py
# - 上游调用: perception.bus（感知总线推送事件）
# - 下游传递: weak_connection.py/weak_connection_v2.py（弱连接引擎）
#
# 【关联文件】
# 1. perception/bus.py - 感知总线，推送窗口变化等事件
# 2. perception/context_triggers.py - 上下文事件定义
# 3. core/weak_connection.py - 弱连接引擎V1
# 4. core/weak_connection_v2.py - 弱连接引擎V2
# 5. core/logger.py - 日志记录
#
# 【核心功能】
# 1. 事件订阅: 订阅感知总线的事件流
# 2. 事件过滤: 只处理窗口相关事件，忽略其他感知数据
# 3. 关键词提取: 从窗口标题提取关键词（报表、代码、文档等类别）
# 4. 应用识别: 识别用户正在使用的应用程序
# 5. 格式转换: 将PerceptionData转换为ContextEvent
# 6. 事件转发: 将转换后的事件传递给弱连接引擎
#
# 【达到的效果】
# 1. 解耦设计: 感知层和弱连接引擎解耦，通过连接器通信
# 2. 灵活扩展: 支持不同的弱连接引擎版本（V1/V2）
# 3. 智能识别: 自动识别用户场景（Excel、代码编辑器等）
# 4. 低侵入: 只处理窗口事件，不影响其他感知数据流
# 5. 单例模式: 确保系统中只有一个连接器实例
#
# 【使用示例】
#   # 启动弱连接系统（通常在系统初始化时调用）
#   start_weak_connection()
#
#   # 或手动获取连接器并启动
#   connector = get_weak_connection_connector()
#   connector.start()
#
# ═══════════════════════════════════════════════════════════════════════════════
