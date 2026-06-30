#!/usr/bin/env python3  # 指定Python解释器路径
# 声明UTF-8编码支持中文
"""
DPI 缩放适配工具 - 集中管理
"""
import ctypes  # 导入ctypes模块，用于调用Windows API

from core.logger import logger  # 从core.logger导入logger实例


def get_dpi_for_window(hwnd=None):  # 定义获取DPI函数
    """获取指定窗口的 DPI，若无窗口则获取主显示器 DPI"""  # 函数文档字符串
    try:  # 尝试执行
        if hwnd:  # 如果提供了窗口句柄
            dpi = ctypes.windll.user32.GetDpiForWindow(hwnd)  # 调用Windows API获取窗口DPI
        else:  # 如果没有提供窗口句柄
            # 获取主显示器 DPI  # 注释说明获取主显示器DPI
            dc = ctypes.windll.user32.GetDC(0)  # 获取屏幕设备上下文
            dpi = ctypes.windll.gdi32.GetDeviceCaps(dc, 88)  # 获取LOGPIXELSX值（水平DPI）
            ctypes.windll.user32.ReleaseDC(0, dc)  # 释放设备上下文
        return dpi  # 返回DPI值
    except Exception as e:  # 捕获所有异常
        logger.warning(f"获取DPI失败: {e}，使用默认值96")  # 记录警告日志
        return 96  # 默认 96 DPI（Windows标准DPI）

def scale_coordinate(x, y, from_dpi=96, to_dpi=96):  # 定义坐标缩放函数
    """坐标缩放，默认不缩放"""  # 函数文档字符串
    if from_dpi == to_dpi:  # 如果源DPI和目标DPI相同
        return x, y  # 直接返回原坐标，无需缩放
    scale = to_dpi / from_dpi  # 计算缩放比例
    return int(x * scale), int(y * scale)  # 应用缩放并返回整数坐标


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase V5 系统的"DPI缩放适配工具"，解决高DPI显示器（如4K屏、
# 缩放比例125%/150%/200%）下的坐标转换问题，确保UI自动化操作的准确性。
#
# 【设计特点】
# 1. Windows原生API：直接调用user32.dll和gdi32.dll获取系统DPI信息
# 2. 双模式支持：支持获取指定窗口DPI或主显示器DPI
# 3. 坐标转换：提供基于DPI比例的坐标缩放函数
# 4. 容错设计：API调用失败时返回标准96 DPI，避免系统崩溃
# 5. 轻量级：仅依赖标准库ctypes，无第三方依赖
#
# 【关联文件】
# - tools/element_locator.py     : 使用DPI缩放转换屏幕坐标
# - tools/mouse_controller.py    : 使用DPI缩放确保鼠标点击位置准确
# - perception/screen_capture.py : 获取屏幕DPI以计算截图比例
# - core/logger.py               : 记录DPI获取失败等警告信息
#
# 【核心功能效果】
# 1. 高DPI适配：自动检测系统DPI设置，适配125%/150%/200%等缩放比例
# 2. 坐标精确：确保在不同DPI设置下的UI操作坐标准确
# 3. 窗口级DPI：支持获取特定窗口的DPI（适用于多显示器不同DPI场景）
# 4. 向后兼容：在API不可用时返回标准96 DPI，保证基本功能
#
# 【使用示例】
# from core.dpi import get_dpi_for_window, scale_coordinate
#
# # 获取当前窗口DPI
# dpi = get_dpi_for_window(hwnd)
#
# # 将逻辑坐标转换为物理坐标
# physical_x, physical_y = scale_coordinate(x, y, from_dpi=96, to_dpi=dpi)
#
# # 将物理坐标转回逻辑坐标
# logical_x, logical_y = scale_coordinate(x, y, from_dpi=dpi, to_dpi=96)
# =============================================================================
