#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""
动态策略管理器 - 运行时参数自适应（如感知频率、OCR开关）
与静态配置完全分离，不持久化，重启后恢复默认
"""
from threading import Lock  # 从threading模块导入Lock类，用于线程安全锁
from typing import Any  # 从typing模块导入类型注解：Dict字典类型和Any任意类型


class AdaptivePolicy:  # 定义自适应策略管理器类
    _instance = None  # 单例模式：类变量，存储唯一实例引用
    _lock = Lock()  # 单例模式：类变量，线程锁，确保多线程下只创建一个实例

    def __new__(cls):  # 重写__new__方法，控制实例创建过程（单例模式核心）
        with cls._lock:  # 获取线程锁，保证线程安全
            if cls._instance is None:  # 检查实例是否已存在
                cls._instance = super().__new__(cls)  # 调用父类创建新实例
                cls._instance._initialized = False  # 标记实例尚未初始化
        return cls._instance  # 返回单例实例

    def __init__(self):  # 初始化方法
        if self._initialized:  # 检查实例是否已初始化（防止重复初始化）
            return  # 已初始化则直接返回，跳过重复初始化
        self._initialized = True  # 标记为已初始化
        # 从静态配置加载默认值（但独立存储）  # 注释说明配置来源
        from core.config import config  # 导入静态配置模块
        self._params = {  # 初始化参数字典，存储动态配置
            "perception": {  # 感知模块配置
                "process": {"interval": config.get("perception.process.interval", 1)},  # 进程感知间隔，默认1秒
                "window": {"interval": config.get("perception.window.interval", 1)},  # 窗口感知间隔，默认1秒
                "screen": {  # 屏幕感知配置
                    "fps": config.get("perception.screen.fps", 15),  # 屏幕捕获帧率，默认15fps
                    "ocr_enabled": config.get("perception.screen.ocr_enabled", False)  # OCR功能开关，默认关闭
                },  # screen配置结束
            },  # perception配置结束
            "ocr_enabled": config.get("perception.screen.ocr_enabled", False),  # 全局OCR开关，默认关闭
        }  # 参数字典定义结束
        self._lock = Lock()  # 实例锁，用于保护_params的线程安全访问

    def get(self, key: str, default=None):  # 获取参数方法，支持点号路径访问
        """获取动态参数，支持点号分隔"""  # 方法文档字符串
        with self._lock:  # 获取锁，保证线程安全
            keys = key.split(".")  # 将点号分隔的字符串拆分为键列表
            value = self._params  # 从根参数开始遍历
            for k in keys:  # 逐级遍历键
                if isinstance(value, dict):  # 检查当前值是否为字典
                    value = value.get(k)  # 获取下一级值
                else:  # 如果不是字典，无法继续深入
                    return default  # 返回默认值
            return value if value is not None else default  # 返回找到的值或默认值

    def set(self, key: str, value: Any):  # 设置参数方法，支持点号路径
        """设置动态参数"""  # 方法文档字符串
        with self._lock:  # 获取锁，保证线程安全
            keys = key.split(".")  # 拆分键路径
            target = self._params  # 从根开始定位
            for k in keys[:-1]:  # 遍历到倒数第二个键，创建中间层级
                if k not in target:  # 如果键不存在
                    target[k] = {}  # 创建空字典作为中间节点
                target = target[k]  # 移动到下一级
            target[keys[-1]] = value  # 在最终位置设置值

    def apply_low_memory_mode(self, enable: bool):  # 应用低资源模式
        """应用低资源模式（包括内存和CPU降级）"""  # 方法文档字符串
        if enable:  # 如果启用低资源模式
            self.set("perception.process.interval", 3)  # 降低进程感知频率，改为3秒
            self.set("perception.window.interval", 3)  # 降低窗口感知频率，改为3秒
            self.set("perception.screen.fps", 5)  # 降低屏幕捕获帧率，改为5fps
            self.set("perception.screen.ocr_enabled", False)  # 关闭屏幕OCR
            self.set("ocr_enabled", False)  # 关闭全局OCR
        else:  # 如果禁用低资源模式（恢复正常）
            # 恢复默认（从静态配置重新读取）  # 注释说明恢复逻辑
            from core.config import config  # 导入静态配置
            self.set("perception.process.interval", config.get("perception.process.interval", 1))  # 恢复进程感知间隔
            self.set("perception.window.interval", config.get("perception.window.interval", 1))  # 恢复窗口感知间隔
            self.set("perception.screen.fps", config.get("perception.screen.fps", 15))  # 恢复屏幕帧率
            self.set("perception.screen.ocr_enabled", config.get("perception.screen.ocr_enabled", False))  # 恢复OCR设置
            self.set("ocr_enabled", config.get("perception.screen.ocr_enabled", False))  # 恢复全局OCR

    def reset_to_default(self):  # 重置所有参数为默认值
        """重置所有动态参数为静态默认值"""  # 方法文档字符串
        from core.config import config  # 导入静态配置
        with self._lock:  # 获取锁，保证线程安全
            self._params = {  # 重新初始化参数字典
                "perception": {  # 感知模块配置
                    "process": {"interval": config.get("perception.process.interval", 1)},  # 恢复进程感知间隔
                    "window": {"interval": config.get("perception.window.interval", 1)},  # 恢复窗口感知间隔
                    "screen": {  # 屏幕感知配置
                        "fps": config.get("perception.screen.fps", 15),  # 恢复屏幕帧率
                        "ocr_enabled": config.get("perception.screen.ocr_enabled", False)  # 恢复OCR设置
                    },  # screen配置结束
                },  # perception配置结束
                "ocr_enabled": config.get("perception.screen.ocr_enabled", False),  # 恢复全局OCR
            }  # 参数字典重置完成


adaptive_policy = AdaptivePolicy()  # 创建全局单例实例，供其他模块直接使用


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase V5 系统的"动态策略管理器"，负责在运行时自适应调整
# 各类感知参数（如屏幕捕获FPS、OCR开关、感知间隔等），实现性能与资源
# 占用的动态平衡。
#
# 【与静态配置的关系】
# - core/config.py  : 提供静态默认值，持久化存储，重启后保持不变
# - 本文件(adaptive_policy): 运行时动态覆盖，内存存储，重启后恢复默认
# 这种分离设计允许系统在运行过程中根据实际负载灵活调整，而不影响配置文件
#
# 【关联文件】
# - main.py                        : 系统启动时调用 reset_to_default() 初始化
# - perception/resource_monitor.py : 监控系统资源，自动触发低资源模式切换
# - perception/process_monitor.py  : 读取动态参数，调整进程感知频率
# - core/config.py                 : 提供静态配置默认值
#
# 【核心功能效果】
# 1. 低资源模式自动降级: 当内存<8GB或CPU持续高负载时，自动降低感知频率、
#    关闭OCR功能，确保系统在资源紧张时仍能正常运行
# 2. 运行时参数热更新: 无需重启即可调整各类感知参数，支持外部干预
# 3. 线程安全访问: 使用Lock保证多线程环境下的参数读写安全
# 4. 单例模式: 全局唯一实例，确保策略一致性
#
# 【使用场景】
# - 低配设备(如8GB内存以下)自动进入低资源模式，避免系统卡顿
# - 用户可通过API或界面手动调整OCR等功能的开关状态
# - 系统根据实时负载动态优化感知频率，平衡性能与资源占用
# =============================================================================
