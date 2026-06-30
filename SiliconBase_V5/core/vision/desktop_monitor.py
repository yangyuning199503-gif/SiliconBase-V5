#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""
桌面监控中枢 - 把屏幕变成"摄像头"

功能：
- 区域内容监控（文字变化检测）
- 颜色状态监控（血条、进度条等）
- 窗口状态监控（应用切换检测）
- 模板存在性监控（图标出现/消失）

相比真实摄像头的优势：
- 零延迟（直接读取帧缓冲）
- 零带宽（本地处理）
- 高精度（像素级精确）

使用场景：
- 游戏辅助（血条监控、技能CD）
- 自动化办公（表单填写监控）
- 软件测试（UI状态检测）
- 防沉迷（应用使用时长统计）
"""

import json  # 导入JSON模块，用于历史记录存储
import threading  # 导入线程模块，用于后台监控
import time  # 导入时间模块，用于时间戳和间隔控制
from collections.abc import Callable  # 从typing导入类型注解
from dataclasses import dataclass  # 从dataclasses导入数据类装饰器
from enum import Enum  # 从enum导入枚举类
from pathlib import Path  # 从pathlib导入Path类

from core.logger import logger  # 导入日志记录器
from core.tool.tool_manager import tool_manager  # 导入工具管理器


class MonitorType(Enum):  # 监控类型枚举类
    TEXT = "text"           # 文字内容变化
    COLOR = "color"         # 颜色变化
    TEMPLATE = "template"   # 模板出现/消失
    WINDOW = "window"       # 窗口变化


@dataclass  # 数据类装饰器
class MonitorRule:  # 监控规则数据类
    """监控规则"""  # 类文档字符串
    rule_id: str  # 规则唯一ID
    name: str  # 规则名称
    monitor_type: MonitorType  # 监控类型
    region: list[int]          # 监控区域 [left, top, width, height]
    check_interval: float = 1.0  # 检查间隔（秒）

    # 触发条件
    condition: str = "changed"  # 触发条件：changed/appeared/disappeared/match
    target_value: str = ""      # 目标值（文字/颜色/模板名）

    # 回调
    on_trigger: Callable | None = None  # 触发时的回调函数

    # 状态
    enabled: bool = True  # 是否启用
    last_value: str = ""  # 上次检测到的值
    trigger_count: int = 0  # 触发次数计数
    last_trigger_time: float = 0  # 上次触发时间戳


class DesktopMonitor:  # 桌面监控器类
    """
    桌面监控中枢 - 把屏幕当摄像头用
    """  # 类文档字符串

    def __init__(self):  # 初始化方法
        self.rules: dict[str, MonitorRule] = {}  # 存储所有监控规则的字典
        self._running = False  # 监控循环运行标志
        self._thread: threading.Thread | None = None  # 监控线程
        self._lock = threading.Lock()  # 线程锁，保护规则字典

        # 历史记录
        self.history_file = Path("data/desktop_monitor_history.json")  # 历史记录文件路径
        self.history = self._load_history()  # 加载历史记录

    def _load_history(self) -> list[dict]:  # 私有方法：加载历史记录
        """加载历史记录"""  # 方法文档字符串
        if self.history_file.exists():  # 如果历史文件存在
            try:  # 异常处理
                with open(self.history_file, encoding='utf-8') as f:  # 打开文件
                    return json.load(f)  # 解析JSON并返回
            except Exception as e:  # 捕获异常
                logger.error(f"[DesktopMonitor] 加载历史记录失败: {e}")  # 记录错误
        return []  # 文件不存在或出错时返回空列表

    def _save_history(self):  # 私有方法：保存历史记录
        """保存历史记录"""  # 方法文档字符串
        self.history_file.parent.mkdir(parents=True, exist_ok=True)  # 确保目录存在
        with open(self.history_file, 'w', encoding='utf-8') as f:  # 打开文件写入
            json.dump(self.history[-1000:], f, ensure_ascii=False, indent=2)  # 只保留最近1000条

    def add_text_monitor(self, name: str, region: list[int],
                        target_text: str = "", interval: float = 1.0) -> str:
        """
        添加文字内容监控

        Args:
            name: 监控名称
            region: 监控区域 [left, top, width, height]
            target_text: 目标文字（空字符串=检测任何变化）
            interval: 检查间隔

        Returns:
            rule_id: 规则ID
        """  # 方法文档字符串
        rule_id = f"text_{int(time.time())}_{hash(name) % 1000}"  # 生成唯一规则ID

        rule = MonitorRule(  # 创建监控规则对象
            rule_id=rule_id,  # 规则ID
            name=name,  # 规则名称
            monitor_type=MonitorType.TEXT,  # 类型为文字监控
            region=region,  # 监控区域
            check_interval=interval,  # 检查间隔
            condition="match" if target_text else "changed",  # 有条件则为匹配模式，否则变化模式
            target_value=target_text  # 目标文字
        )

        with self._lock:  # 获取锁，保证线程安全
            self.rules[rule_id] = rule  # 添加到规则字典

        logger.info(f"[DesktopMonitor] 添加文字监控: {name} ({rule_id})")  # 记录日志
        return rule_id  # 返回规则ID

    def add_color_monitor(self, name: str, x: int, y: int,
                         target_color: list[int], tolerance: int = 10,
                         interval: float = 0.5) -> str:
        """
        添加颜色监控（适合血条、进度条、状态灯）

        Args:
            name: 监控名称
            x, y: 像素坐标
            target_color: 目标RGB颜色 [R, G, B]
            tolerance: 容差
            interval: 检查间隔（可高频）
        """  # 方法文档字符串
        rule_id = f"color_{int(time.time())}_{hash(name) % 1000}"  # 生成唯一规则ID

        rule = MonitorRule(  # 创建监控规则对象
            rule_id=rule_id,  # 规则ID
            name=name,  # 规则名称
            monitor_type=MonitorType.COLOR,  # 类型为颜色监控
            region=[x, y, 1, 1],  # 单像素区域
            check_interval=interval,  # 检查间隔
            condition="match",  # 匹配模式
            target_value=str(target_color)  # 目标颜色值（转为字符串存储）
        )

        with self._lock:  # 获取锁，保证线程安全
            self.rules[rule_id] = rule  # 添加到规则字典

        logger.info(f"[DesktopMonitor] 添加颜色监控: {name} at ({x},{y})")  # 记录日志
        return rule_id  # 返回规则ID

    def add_template_monitor(self, name: str, template_path: str,
                            region: list[int] | None = None,
                            interval: float = 1.0) -> str:
        """
        添加模板监控（图标出现/消失检测）

        Args:
            name: 监控名称
            template_path: 模板图片路径
            region: 搜索区域（None=全屏）
            interval: 检查间隔
        """  # 方法文档字符串
        rule_id = f"template_{int(time.time())}_{hash(name) % 1000}"  # 生成唯一规则ID

        rule = MonitorRule(  # 创建监控规则对象
            rule_id=rule_id,  # 规则ID
            name=name,  # 规则名称
            monitor_type=MonitorType.TEMPLATE,  # 类型为模板监控
            region=region or [0, 0, 3840, 2160],  # 默认全屏4K分辨率
            check_interval=interval,  # 检查间隔
            condition="appeared",  # 检测出现
            target_value=template_path  # 模板图片路径
        )

        with self._lock:  # 获取锁，保证线程安全
            self.rules[rule_id] = rule  # 添加到规则字典

        logger.info(f"[DesktopMonitor] 添加模板监控: {name}")  # 记录日志
        return rule_id  # 返回规则ID

    def add_window_monitor(self, name: str, window_title_keyword: str) -> str:
        """
        添加窗口监控（应用切换检测）

        Args:
            name: 监控名称
            window_title_keyword: 窗口标题关键词
        """  # 方法文档字符串
        rule_id = f"window_{int(time.time())}_{hash(name) % 1000}"  # 生成唯一规则ID

        rule = MonitorRule(  # 创建监控规则对象
            rule_id=rule_id,  # 规则ID
            name=name,  # 规则名称
            monitor_type=MonitorType.WINDOW,  # 类型为窗口监控
            region=[],  # 窗口监控不需要区域
            check_interval=1.0,  # 检查间隔1秒
            condition="match",  # 匹配模式
            target_value=window_title_keyword  # 窗口标题关键词
        )

        with self._lock:  # 获取锁，保证线程安全
            self.rules[rule_id] = rule  # 添加到规则字典

        logger.info(f"[DesktopMonitor] 添加窗口监控: {name}")  # 记录日志
        return rule_id  # 返回规则ID

    def start(self):  # 启动监控线程
        """启动监控线程"""  # 方法文档字符串
        if self._running:  # 如果已经在运行
            return  # 直接返回

        self._running = True  # 设置运行标志
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)  # 创建后台线程
        self._thread.start()  # 启动线程
        logger.info("[DesktopMonitor] 监控线程已启动")  # 记录日志

    def stop(self):  # 停止监控线程
        """停止监控线程"""  # 方法文档字符串
        self._running = False  # 清除运行标志
        if self._thread:  # 如果线程存在
            self._thread.join(timeout=5)  # 等待线程结束（最多5秒）
        logger.info("[DesktopMonitor] 监控线程已停止")  # 记录日志

    def _monitor_loop(self):  # 监控主循环（线程入口）
        """监控主循环"""  # 方法文档字符串
        while self._running:  # 循环直到停止
            with self._lock:  # 获取锁
                rules = list(self.rules.values())  # 复制规则列表

            for rule in rules:  # 遍历所有规则
                if not rule.enabled:  # 如果规则被禁用
                    continue  # 跳过

                try:  # 异常处理
                    self._check_rule(rule)  # 检查该规则
                except Exception as e:  # 捕获异常
                    logger.error(f"[DesktopMonitor] 规则 {rule.name} 检查失败: {e}")  # 记录错误

                # 间隔检查，避免CPU占满
                time.sleep(rule.check_interval / len(rules) if rules else 0.1)

    def _check_rule(self, rule: MonitorRule):  # 检查单个规则
        """检查单个规则"""  # 方法文档字符串
        current_time = time.time()  # 获取当前时间戳

        if rule.monitor_type == MonitorType.TEXT:  # 如果是文字监控
            current_value = self._get_text(rule.region)  # 获取区域文字
        elif rule.monitor_type == MonitorType.COLOR:  # 如果是颜色监控
            current_value = self._get_color(rule.region[0], rule.region[1])  # 获取像素颜色
        elif rule.monitor_type == MonitorType.TEMPLATE:  # 如果是模板监控
            current_value = self._check_template(rule.target_value, rule.region)  # 检查模板
        elif rule.monitor_type == MonitorType.WINDOW:  # 如果是窗口监控
            current_value = self._get_active_window()  # 获取活动窗口标题
        else:  # 未知类型
            return  # 直接返回

        # 检测触发条件
        triggered = False  # 触发标志

        if rule.condition == "changed":  # 变化触发
            triggered = current_value != rule.last_value and rule.last_value != ""  # 值变化且不是首次
        elif rule.condition == "match":  # 匹配触发
            triggered = rule.target_value.lower() in current_value.lower()  # 包含目标值
        elif rule.condition == "appeared":  # 出现触发
            triggered = current_value and not rule.last_value  # 从无到有
        elif rule.condition == "disappeared":  # 消失触发
            triggered = not current_value and rule.last_value  # 从有到无

        # 更新状态
        rule.last_value = current_value  # 保存当前值

        if triggered:  # 如果触发
            rule.trigger_count += 1  # 增加触发计数
            rule.last_trigger_time = current_time  # 记录触发时间

            # 记录历史
            self.history.append({  # 添加到历史列表
                "timestamp": current_time,  # 时间戳
                "rule_id": rule.rule_id,  # 规则ID
                "rule_name": rule.name,  # 规则名称
                "type": rule.monitor_type.value,  # 监控类型
                "value": current_value  # 触发时的值
            })

            if len(self.history) % 10 == 0:  # 每10条记录保存一次
                self._save_history()  # 保存历史

            # 执行回调
            if rule.on_trigger:  # 如果设置了回调
                try:  # 异常处理
                    rule.on_trigger(rule, current_value)  # 执行回调函数
                except Exception as e:  # 捕获异常
                    logger.error(f"[DesktopMonitor] 回调执行失败: {e}")  # 记录错误

            logger.info(f"[DesktopMonitor] 触发: {rule.name} -> {current_value[:50]}")  # 记录触发

    def _get_text(self, region: list[int]) -> str:  # 获取区域文字（OCR）
        """获取区域文字"""  # 方法文档字符串
        try:  # 异常处理
            ocr_tool = tool_manager.get_tool("screen_ocr")  # 获取OCR工具
            if ocr_tool:  # 如果工具存在
                result = ocr_tool.run(  # 执行OCR
                    left=region[0], top=region[1],  # 区域左上角
                    width=region[2], height=region[3]  # 区域宽高
                )
                if result.get("success"):  # 如果成功
                    return result["data"].get("text", "")  # 返回识别的文字
        except Exception as e:  # 捕获异常
            logger.error(f"[DesktopMonitor] 获取区域文字失败: {e}")  # 记录错误
        return ""  # 出错返回空字符串

    def _get_color(self, x: int, y: int) -> str:  # 获取像素颜色
        """获取像素颜色"""  # 方法文档字符串
        try:  # 异常处理
            color_tool = tool_manager.get_tool("pixel_color")  # 获取颜色工具
            if color_tool:  # 如果工具存在
                result = color_tool.run(action="get", x=x, y=y)  # 执行获取颜色
                if result.get("success"):  # 如果成功
                    data = result["data"]  # 获取数据
                    return str(data.get("rgb", ""))  # 返回RGB颜色值
        except Exception as e:  # 捕获异常
            logger.error(f"[DesktopMonitor] 获取像素颜色失败: {e}")  # 记录错误
        return ""  # 出错返回空字符串

    def _check_template(self, template_path: str, region: list[int]) -> str:  # 检查模板是否存在
        """检查模板是否存在"""  # 方法文档字符串
        try:  # 异常处理
            match_tool = tool_manager.get_tool("template_match")  # 获取模板匹配工具
            if match_tool:  # 如果工具存在
                result = match_tool.run(  # 执行模板匹配
                    template_path=template_path,  # 模板路径
                    region=region,  # 搜索区域
                    threshold=0.75  # 匹配阈值
                )
                return "found" if result.get("success") else ""  # 返回found或空
        except Exception as e:  # 捕获异常
            logger.error(f"[DesktopMonitor] 检查模板失败: {e}")  # 记录错误
        return ""  # 出错返回空字符串

    def _get_active_window(self) -> str:  # 获取当前活动窗口标题
        """获取当前活动窗口标题"""  # 方法文档字符串
        try:  # 异常处理
            import win32gui  # 导入Windows GUI模块
            hwnd = win32gui.GetForegroundWindow()  # 获取前台窗口句柄
            return win32gui.GetWindowText(hwnd)  # 获取窗口标题
        except Exception as e:  # 捕获异常
            logger.error(f"[DesktopMonitor] 获取活动窗口失败: {e}")  # 记录错误
        return ""  # 出错返回空字符串

    def list_rules(self) -> list[dict]:  # 列出所有规则
        """列出所有规则"""  # 方法文档字符串
        with self._lock:  # 获取锁
            return [  # 返回规则信息列表
                {
                    "id": r.rule_id,  # 规则ID
                    "name": r.name,  # 规则名称
                    "type": r.monitor_type.value,  # 监控类型
                    "enabled": r.enabled,  # 是否启用
                    "trigger_count": r.trigger_count,  # 触发次数
                    "last_value": r.last_value[:50] if r.last_value else ""  # 上次值（截断）
                }
                for r in self.rules.values()  # 遍历所有规则
            ]

    def remove_rule(self, rule_id: str):  # 删除规则
        """删除规则"""  # 方法文档字符串
        with self._lock:  # 获取锁
            if rule_id in self.rules:  # 如果规则存在
                del self.rules[rule_id]  # 删除规则
                logger.info(f"[DesktopMonitor] 删除规则: {rule_id}")  # 记录日志

    def enable_rule(self, rule_id: str, enabled: bool = True):  # 启用/禁用规则
        """启用/禁用规则"""  # 方法文档字符串
        with self._lock:  # 获取锁
            if rule_id in self.rules:  # 如果规则存在
                self.rules[rule_id].enabled = enabled  # 设置启用状态

    def get_system_load(self) -> dict:  # 获取系统负载信息
        """获取系统负载信息"""  # 方法文档字符串
        import psutil  # 导入psutil模块
        return {  # 返回系统负载字典
            "cpu_percent": psutil.cpu_percent(interval=0.1),  # CPU使用率
            "memory_percent": psutil.virtual_memory().percent,  # 内存使用率
            "disk_usage": psutil.disk_usage('/').percent,  # 磁盘使用率
            "timestamp": time.time()  # 时间戳
        }

    def should_throttle(self, threshold: float = 80.0) -> bool:  # 判断是否需要限流
        """判断是否需要限流（系统负载过高）"""  # 方法文档字符串
        load = self.get_system_load()  # 获取系统负载
        return load["cpu_percent"] > threshold or load["memory_percent"] > threshold  # 检查是否超过阈值


# 全局实例
desktop_monitor = DesktopMonitor()  # 创建全局单例实例


def get_desktop_monitor() -> DesktopMonitor:
    """
    获取桌面监控器实例

    Returns:
        DesktopMonitor: 桌面监控器实例
    """
    return desktop_monitor


# 便捷函数
def watch_text(name: str, region: list[int], target: str = "", interval: float = 1.0) -> str:  # 监控文字变化
    """监控文字变化"""  # 函数文档字符串
    return desktop_monitor.add_text_monitor(name, region, target, interval)  # 调用管理器方法


def watch_color(name: str, x: int, y: int, color: list[int], tolerance: int = 10) -> str:  # 监控颜色变化
    """监控颜色变化"""  # 函数文档字符串
    return desktop_monitor.add_color_monitor(name, x, y, color, tolerance)  # 调用管理器方法


def watch_template(name: str, template: str, region: list[int] = None) -> str:  # 监控模板出现
    """监控模板出现"""  # 函数文档字符串
    return desktop_monitor.add_template_monitor(name, template, region)  # 调用管理器方法


def watch_window(name: str, keyword: str) -> str:  # 监控窗口变化
    """监控窗口变化"""  # 函数文档字符串
    return desktop_monitor.add_window_monitor(name, keyword)  # 调用管理器方法


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase V5 系统的"桌面监控中枢"，将屏幕视为摄像头，提供
# 像素级精确的屏幕状态监控能力。
#
# 【主要功能】
# 1. 文字监控：通过OCR检测屏幕区域文字变化
# 2. 颜色监控：检测特定像素颜色变化（适合血条、进度条）
# 3. 模板监控：检测图标/图片在屏幕上的出现/消失
# 4. 窗口监控：检测活动窗口变化
# 5. 触发回调：支持自定义回调函数响应监控事件
#
# 【关联文件】
# - core/tool_manager.py        : 工具管理器，提供OCR、颜色、模板匹配工具
# - tools/screen_ocr.py         : 屏幕OCR工具
# - tools/pixel_color.py        : 像素颜色获取工具
# - tools/template_match.py     : 模板匹配工具
# - data/desktop_monitor_history.json : 监控历史记录文件
#
# 【核心功能效果】
# 1. 零延迟监控：直接读取屏幕缓冲，无摄像头延迟
# 2. 像素级精度：可精确监控单个像素颜色
# 3. 多种触发模式：支持变化触发、匹配触发、出现/消失触发
# 4. 历史记录：自动保存触发历史，支持后续分析
# 5. 线程安全：使用锁保护共享数据
#
# 【使用场景】
# - 游戏辅助：监控血条、技能CD、游戏状态
# - 自动化测试：检测UI元素出现/消失，验证界面状态
# - 办公自动化：监控表单填写进度，检测弹窗提示
# - 防沉迷监控：统计应用使用时长
#
# 【监控类型对比】
# - TEXT: 适合监控文字提示、状态信息变化
# - COLOR: 适合监控血条、进度条、状态灯
# - TEMPLATE: 适合监控图标、按钮出现/消失
# - WINDOW: 适合监控应用切换、窗口焦点变化
# =============================================================================
