#!/usr/bin/env python3
"""
System Sensors - SiliconBase V5
系统感知和监控模块

从原 perception/ 模块迁移而来
提供系统级的监控和感知功能：
- 进程监控
- 窗口监控
- 资源监控
- 全局视图
- 事件总线
"""

# 导出主要组件
from .bus import bus
from .context_triggers import ContextTriggers, context_triggers
from .global_view import GlobalView, global_view
from .process_monitor import ProcessMonitor, process_monitor
from .resource_monitor import ResourceMonitor, resource_monitor
from .window_monitor import WindowMonitor, window_monitor

__all__ = [
    # 实例（直接使用）
    'process_monitor',
    'window_monitor',
    'resource_monitor',
    'global_view',
    'bus',
    'context_triggers',
    # 类（需要时实例化）
    'ProcessMonitor',
    'WindowMonitor',
    'ResourceMonitor',
    'GlobalView',

    'ContextTriggers',
]

__version__ = "1.0.0"
