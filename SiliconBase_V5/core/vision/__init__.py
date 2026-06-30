#!/usr/bin/env python3
"""
Vision 模块 - SiliconBase V5
AI视觉感知和处理模块

从原 core/perception/ 迁移而来
提供AI视觉相关功能：
- 屏幕截图管理
- 屏幕变化检测
- 视觉模型调用
- 视觉缓存管理
- 视觉健康检查
- 桌面监控
"""

import logging

logger = logging.getLogger(__name__)

# 导出主要组件
from .desktop_monitor import DesktopMonitor, get_desktop_monitor
from .global_view_v2 import GlobalViewV2, get_global_view_v2
from .perception_manager import PerceptionManager, get_perception_manager

# 安全截图函数 - 从safe_screenshot导入V3版本
from .safe_screenshot import (
    safe_screenshot_to_numpy,
    safe_screenshot_to_pil,
)
from .screen_change_detector import ScreenChangeDetector
from .screenshot_manager import ScreenshotManager, get_screenshot_manager
from .vision_cache import VisionCache, get_vision_cache
from .vision_health_check import VisionHealthChecker, get_vision_health_check
from .vision_processor import (
    ScreenshotError,
    VisionError,
    VisionModelError,
    VisionTimeoutError,
    call_vision_model_async,
    get_vision_timeout,
    is_vision_enabled,
    set_vision_enabled,
)
from .vision_user_notifier import VisionUserNotifier, get_vision_user_notifier
from .vision_validator import VisionConfigValidator, get_vision_validator
from .visual_analysis_cache import VisualAnalysisCache, get_visual_analysis_cache

# ThreadSafePixelCapture类 - 从safe_screenshot_v2导入
try:
    from .safe_screenshot_v2 import (
        ThreadSafePixelCapture,
        get_safe_capture,
    )
    THREAD_SAFE_PIXEL_CAPTURE_AVAILABLE = True
except ImportError as e:
    logger.error(f"[Vision] ThreadSafePixelCapture导入失败: {e}")
    THREAD_SAFE_PIXEL_CAPTURE_AVAILABLE = False
    ThreadSafePixelCapture = None
    get_safe_capture = None

from .visual_tool_coordinator import (
    VisualToolCoordinator,
    coordinated_ai_vision,
    get_visual_status,
)

__all__ = [
    # 类和函数
    'ScreenshotManager',
    'ScreenChangeDetector',
    'VisionError',
    'ScreenshotError',
    'VisionModelError',
    'VisionTimeoutError',
    'VisionCache',
    'VisionHealthChecker',
    'VisionConfigValidator',
    'VisionUserNotifier',
    'VisualAnalysisCache',
    'DesktopMonitor',
    'GlobalViewV2',
    'PerceptionManager',
    # Getter函数
    'get_screenshot_manager',
    'get_vision_cache',
    'get_vision_health_check',
    'get_vision_validator',
    'get_vision_user_notifier',
    'get_visual_analysis_cache',
    'get_desktop_monitor',
    'get_global_view_v2',
    'get_perception_manager',
    # 线程安全截图
    'safe_screenshot_to_pil',
    'safe_screenshot_to_numpy',
    'ThreadSafePixelCapture',
    'get_safe_capture',
    # 视觉工具协调器
    'VisualToolCoordinator',
    'coordinated_ai_vision',
    'get_visual_status',
    # 工具函数
    'get_vision_timeout',
    'set_vision_enabled',
    'is_vision_enabled',
    'call_vision_model_async',
    # 可用性标志
    'THREAD_SAFE_PIXEL_CAPTURE_AVAILABLE',
]

__version__ = "1.0.0"
