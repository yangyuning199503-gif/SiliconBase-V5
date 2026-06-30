#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""  # 多行文档字符串开始
硬件检测与自动降级策略  # 模块功能概述：检测硬件配置并决定是否降级
"""  # 文档字符串结束
import platform  # 导入平台模块，用于获取操作系统信息
import subprocess  # 导入子进程模块，用于执行系统命令
import threading  # 导入线程模块，用于单例锁

import psutil  # 导入psutil模块，用于获取系统硬件信息

from core.logger import logger  # 导入日志记录器


class HardwareDetector:  # 硬件检测器类
    _instance = None  # 单例模式：类变量，存储唯一实例引用
    _lock = threading.Lock()  # 单例模式：类变量，线程锁

    def __new__(cls):  # 重写__new__方法，实现单例模式
        if cls._instance is None:  # 第一层检查，避免不必要的锁开销
            with cls._lock:  # 获取线程锁
                # 双重检查锁定
                if cls._instance is None:  # 第二层检查，确保只创建一个实例
                    cls._instance = super().__new__(cls)  # 调用父类创建新实例
                    cls._instance._detected = False  # 标记尚未检测
                    cls._instance._spec = {}  # 初始化规格字典
        return cls._instance  # 返回单例实例

    def detect(self):  # 执行硬件检测
        if self._detected:  # 如果已经检测过
            return self._spec  # 直接返回已保存的规格
        self._spec["os"] = platform.system() + " " + platform.release()  # 获取操作系统名称和版本
        self._spec["cpu_count"] = self._get_cpu_count()  # 获取CPU核心数
        self._spec["cpu_name"] = self._get_cpu_name()  # 获取CPU型号名称
        self._spec["ram_gb"] = self._get_ram_gb()  # 获取内存大小（GB）
        self._spec["gpu_name"] = self._get_gpu_name()  # 获取GPU型号名称
        self._spec["is_low_end"] = self._is_low_end()  # 判断是否为低端设备
        self._detected = True  # 标记已检测
        return self._spec  # 返回硬件规格字典

    def _get_cpu_count(self):  # 私有方法：获取CPU逻辑核心数
        return psutil.cpu_count(logical=True)  # 返回逻辑CPU核心数（包含超线程）

    def _get_cpu_name(self):  # 私有方法：获取CPU型号名称
        try:  # 异常处理
            if platform.system() == "Windows":  # 如果是Windows系统
                import winreg  # 导入Windows注册表模块
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,  # 打开注册表键
                                     r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")  # CPU信息路径
                name, _ = winreg.QueryValueEx(key, "ProcessorNameString")  # 查询CPU名称值
                return name  # 返回CPU名称
        except Exception as e:  # 捕获异常
            logger.warning(f"获取CPU名称失败: {e}")  # 记录警告
        return "Unknown"  # 出错返回Unknown

    def _get_ram_gb(self):  # 私有方法：获取内存大小
        return round(psutil.virtual_memory().total / (1024**3), 1)  # 总内存转为GB并保留1位小数

    def _get_gpu_name(self):  # 私有方法：获取GPU型号名称
        try:  # 异常处理
            if platform.system() == "Windows":  # 如果是Windows系统
                output = subprocess.check_output(  # 执行WMIC命令获取显卡信息
                    ["wmic", "path", "win32_VideoController", "get", "name"], text=True  # 获取显卡名称
                )
                lines = output.strip().split("\n")  # 按行分割输出
                if len(lines) >= 2:  # 如果有多行（第一行是标题）
                    return lines[1].strip()  # 返回第二行（第一个显卡名称）
        except Exception as e:  # 捕获异常
            logger.warning(f"获取GPU名称失败: {e}")  # 记录警告
        return "Unknown"  # 出错返回Unknown

    def _is_low_end(self):  # 私有方法：判断是否为低端设备
        spec = self._spec  # 获取规格字典
        cpu = spec.get("cpu_name", "").lower()  # CPU名称转小写
        return (
            spec.get("ram_gb", 16) <= 8  # 如果内存小于等于8GB
            or ("i5" in cpu and "9" not in cpu and "10" not in cpu)  # i5 8代及以下
            or "i3" in cpu or "pentium" in cpu or "celeron" in cpu  # i3/奔腾/赛扬
        )  # 满足任一条件即判定为低端设备


hardware_detector = HardwareDetector()  # 创建全局单例实例


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase V5 系统的"硬件检测器"，负责检测系统硬件配置，
# 并根据检测结果判定是否为低端设备，为系统的自动降级策略提供依据。
#
# 【主要功能】
# 1. 硬件信息检测：CPU型号、核心数、内存大小、GPU型号、操作系统
# 2. 低端设备判定：基于内存和CPU型号自动判定设备等级
# 3. 单例模式：全局唯一实例，避免重复检测
# 4. 延迟检测：首次调用时才执行检测，节省启动时间
#
# 【关联文件】
# - core/adaptive_policy.py       : 动态策略管理器，根据本模块结果调整参数
# - main.py                       : 系统启动时调用detect()获取硬件信息
# - perception/resource_monitor.py : 资源监控，结合硬件信息判断负载
#
# 【核心功能效果】
# 1. 自动降级：检测到低端设备时，自动降低感知频率、关闭高耗功能
# 2. 优化体验：根据硬件能力调整系统行为，确保流畅运行
# 3. 兼容性：支持Windows系统，使用多种方式获取硬件信息
#
# 【低端设备判定标准】
# - 内存 <= 8GB
# - CPU为i5 8代及以下
# - CPU为i3/奔腾/赛扬系列
#
# 【使用场景】
# - 系统启动时检测硬件，调整初始化参数
# - 资源监控模块判断是否需要降频运行
# - UI层根据设备等级调整界面复杂度
# =============================================================================
