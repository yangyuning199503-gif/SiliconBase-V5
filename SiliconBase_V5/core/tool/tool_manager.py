#!/usr/bin/env python3
"""
工具管理器 V6.2 - 支持按用户隔离执行上下文
2026-02-22 修复：修复线程池泄漏，统一返回值格式，完善错误处理
2026-02-22 增强：register_tool_from_code 添加沙箱测试，原子化注册
2026-02-26 新增：集成L5执行记忆记录，所有工具调用自动记录到执行记忆
2026-02-26 重构：支持按用户隔离执行上下文（审计日志、失败计数等）
2026-02-26 修复(THREAD-001)：使用multiprocessing替代threading，解决僵尸线程问题
"""
# ========================================
# 标准库导入 - 用于动态导入、类型检查、系统操作等
# ========================================
import ast  # 抽象语法树，用于代码安全分析
import asyncio  # 异步IO支持，用于 async/await
import concurrent.futures  # 线程池执行器，用于异步执行
import importlib  # 动态导入模块，用于加载工具类
import inspect  # 检查活动对象的模块，用于获取类源代码
import multiprocessing as mp  # 多进程支持，用于隔离工具执行
import os  # 操作系统接口，用于文件路径操作
import sys  # 系统相关的参数和函数
import tempfile  # 临时文件创建，用于原子化保存
import threading  # 多线程支持，用于锁机制
import time  # 时间相关功能，用于性能计时
import weakref  # 弱引用，用于进程池自动清理
from dataclasses import dataclass, field  # 数据类定义
from pathlib import Path  # 面向对象的路径操作
from typing import Any

# ========================================
# 核心接口导入 - 工具结果和验证
# ========================================
from core.interfaces import ToolResult  # 工具结果接口和验证器
from core.logger import logger

# ========================================
# 基础工具类导入 - 所有工具的基类
# ========================================
from core.tool.base_tool import BaseTool  # 工具基类，定义工具标准接口

# ========================================
# 延迟导入变量 - 避免循环依赖问题
# ========================================
_config = None    # 配置对象缓存，延迟初始化避免循环导入
_logger = None    # 日志对象缓存，延迟初始化避免循环导入

def _get_config():
    """延迟获取config实例 - 解决循环依赖问题"""
    global _config  # 声明使用全局变量
    if _config is None:  # 检查是否已初始化
        from core.config import config  # 延迟导入配置模块
        _config = config  # 缓存配置实例
    return _config  # 返回配置实例

def _get_logger():
    """延迟获取logger实例 - 解决循环依赖问题"""
    global _logger  # 声明使用全局变量
    if _logger is None:  # 检查是否已初始化
        from core.logger import logger  # 延迟导入日志模块
        _logger = logger  # 缓存日志实例
    return _logger  # 返回日志实例

# ========================================
# 错误码和策略导入 - 错误处理和权限控制
# ========================================
from core.sync.event_bus import event_bus  # 事件总线，用于发布工具执行事件
from core.task.task_queue import task_queue  # 任务队列，获取当前任务上下文
from core.utils.error_codes import (
    TOOL_EXECUTION_ERROR,
    TOOL_NOT_FOUND,
    TOOL_TIMEOUT,  # 参数错误码
    format_error,  # 工具相关错误码
)

from ..safety.ast_security_checker import check_code_safety  # AST代码安全检查
from ..strategy.policy import check_tool_allowed, is_protected_path, is_protected_process  # 权限检查策略

try:
    from core.world_model.world_model import get_world_model  # 世界模型，记录执行观察
except Exception:
    get_world_model = None
from core.tool.tool_categories import tool_categories  # 工具分类管理

# ========================================
# 工具分类配置（用于AI层展示）
# ========================================
# 【修复队8】8个功能分类 - 优化AI选工具体验
# 按功能将工具分组，便于前端展示和AI理解
TOOL_CATEGORIES = {
    "⏰ 定时任务": {
        "description": "定时任务、提醒、计划管理（闹钟型，到点执行）",
        "tools": ["create_task", "list_tasks", "get_task", "cancel_task"]
    },
    "⏳ 长期任务面板": {
        "description": "3槽位长期任务管理（可暂停/恢复/进度追踪）",
        "tools": ["create_long_task", "pause_long_task", "resume_long_task",
                 "get_long_task_status", "cancel_long_task"]
    },
    "🤖 子代理": {
        "description": "子代理委派和干预（代码审查/测试/研究/架构等）",
        "tools": ["delegate_to_subagent", "get_subagent_status", "intervene_subagent",
                 "list_available_subagents"]
    },
    "📁 文件操作": {
        "description": "文件读写、目录管理",
        "tools": ["file_manager", "read_file", "browse_dir", "export_data", "delete_user_data"]
    },
    "🔧 系统控制": {
        "description": "系统设置、进程管理、信息查询",
        "tools": ["system_info", "process_kill", "process_start", "current_time",
                 "list_installed_apps", "app_search"]
    },
    "🌐 网络通信": {
        "description": "网页搜索、HTTP请求、网络自动化",
        "tools": ["web_search", "web_open", "web_fetch", "web_parse", "web_automation",
                 "web_content_extractor"]
    },
    "📊 数据处理": {
        "description": "剪贴板、数据导入导出、格式转换",
        "tools": ["clipboard", "clipboard_get", "clipboard_set", "export_data",
                 "tron_balance_updater", "call_user"]
    },
    "🎵 媒体处理": {
        "description": "截图、OCR、视觉识别、屏幕监控",
        "tools": ["pixel_capture", "pixel_monitor", "pixel_click", "pixel_color",
                 "screen_ocr", "window_ocr", "ocr_text", "find_screen_element",
                 "template_match", "template_record", "visual_understand", "icon_recognize",
                 "get_perception", "vision_agent", "ui_tars"]
    },
    "💻 代码开发": {
        "description": "代码生成、命令执行",
        "tools": ["code_generate", "shell_execute"]
    },
    "🔐 安全工具": {
        "description": "VPN连接、安全检查、隐私保护",
        "tools": ["vpn_connect", "vpn_check"]
    },
    "🚀 应用操作": {
        "description": "启动应用、窗口管理、自动化操作",
        "tools": ["launch_app", "open_and_focus", "wait_for_window", "window_focus",
                 "window_get", "window_action", "window_rect", "window_ocr"]
    },
    "⌨️ 输入控制": {
        "description": "模拟键盘、鼠标、点击操作",
        "tools": ["keyboard_input", "mouse_click", "click_text", "pixel_click"]
    },
    "🧠 记忆管理": {
        "description": "记忆存储、搜索、更新、删除",
        "tools": ["memory_add", "memory_search", "memory_list", "memory_update", "memory_delete"]
    },
    "📖 工具手册": {
        "description": "L1/L2/L3层级导航、工具查询",
        "tools": ["get_tool_manual", "get_tool_categories_l1", "get_tools_by_category_l2",
                 "get_tool_detail_l3", "switch_prompt_layer"]
    },
}

# ========================================
# 向后兼容：保留旧的AI分类映射
# ========================================
TOOL_CATEGORIES_AI = {
    "定时任务": TOOL_CATEGORIES["⏰ 定时任务"]["tools"],  # 从TOOL_CATEGORIES引用
    "长期任务": TOOL_CATEGORIES["⏳ 长期任务面板"]["tools"],  # 3槽位长期任务
    "子代理": TOOL_CATEGORIES["🤖 子代理"]["tools"],  # 子代理委派
    "文件操作": TOOL_CATEGORIES["📁 文件操作"]["tools"],
    "系统控制": TOOL_CATEGORIES["🔧 系统控制"]["tools"],
    "应用操作": [  # 应用相关操作工具
        "launch_app", "app_search", "window_focus", "window_get",
        "window_action", "wait_for_window"
    ],
    "输入控制": [  # 用户输入模拟工具
        "keyboard_input", "mouse_click", "click_text", "pixel_click"
    ],
    "屏幕识别": TOOL_CATEGORIES["🎵 媒体处理"]["tools"],  # 引用媒体处理分类
    "网络通信": TOOL_CATEGORIES["🌐 网络通信"]["tools"],
    "记忆管理": [  # 记忆系统相关工具
        "memory_add", "memory_search", "memory_update", "memory_delete"
    ],
    "数据处理": TOOL_CATEGORIES["📊 数据处理"]["tools"],
    "通信通知": ["call_user", "vpn_connect", "vpn_check"],  # 通信相关
    "代码生成": TOOL_CATEGORIES["💻 代码开发"]["tools"],
}

# ========================================
# AI用 vs 用户用 功能边界定义
# ========================================
# 定义哪些功能由AI直接调用，哪些由用户界面使用
FUNCTION_BOUNDARY = {
    # AI直接用的（触发器或TOOL_CALL）
    "ai_only": [
        "create_task",      # AI直接创建定时任务
        "list_tasks",       # AI查看任务
        "memory_search",    # AI查询记忆（标记方式）
        "recall_memory",    # AI回忆记忆
        "tool_call",        # AI调用工具
    ],
    # 用户通过前端界面用的
    "user_only": [
        "dashboard",        # 监控面板（纯查看）
        "world_model",      # 世界模型训练界面
        "aiconfig",         # AI配置界面
        "settings",         # 系统设置
    ],
    # 共用的
    "shared": [
        "tasks",            # 任务列表（AI创建/用户查看）
        "memory",           # 记忆管理（AI查询/用户管理）
        "tools",            # 工具列表
        "pause_task",       # 暂停任务
        "resume_task",      # 恢复任务
    ]
}

# ========================================
# L5执行记忆导入（延迟导入避免循环依赖）
# ========================================
_execution_memory_manager = None  # L5执行记忆管理器缓存

def _get_execution_memory():
    """获取L5执行记忆管理器（延迟初始化）"""
    global _execution_memory_manager  # 声明使用全局变量
    if _execution_memory_manager is None:  # 检查是否已初始化
        try:
            from core.memory.execution_memory import execution_memory_manager  # 延迟导入
            _execution_memory_manager = execution_memory_manager  # 缓存实例
        except Exception as e:  # 捕获导入失败异常
            _get_logger().error(f"[SILENT_FAILURE_BLOCKED][ToolManager] L5执行记忆初始化失败: {e}", exc_info=True)  # 记录错误
            _execution_memory_manager = None  # 设置为None表示未初始化
    return _execution_memory_manager  # 返回管理器实例


# ========================================
# 工具进程工作函数 - 在子进程中执行工具
# ========================================
def _tool_process_worker(tool_module: str, tool_class_name: str, params: dict,
                         result_queue):
    """
    工具进程工作函数 - 在子进程中执行工具

    【THREAD-001修复】
    此函数在模块级别定义，可以被multiprocessing正确序列化
    通过导入模块和类名在子进程中重建工具实例，避免pickle限制

    【连接池保护】纯工具在子进程中执行，不访问PostgreSQL
    连接池采用延迟初始化，只有真正执行SQL时才会创建连接

    Args:
        tool_module: 工具模块路径（如 "tools.file_manager"）
        tool_class_name: 工具类名（如 "FileManagerTool"）
        params: 执行参数字典
        result_queue:  multiprocessing.Queue 结果队列，用于返回执行结果
    """
    try:
        # 在子进程中导入模块并创建工具实例
        # 子进程需要重新导入模块，因为父进程的导入不会自动继承
        module = importlib.import_module(tool_module)  # 动态导入模块
        tool_class = getattr(module, tool_class_name)  # 从模块获取类
        tool = tool_class()  # 实例化工具

        # 执行工具 - 调用工具的run方法
        result = tool.run(**params)  # 解包参数字典传递给run方法
        result_queue.put({"result": result})  # 将结果放入队列

    except Exception as e:  # 捕获所有异常
        import logging  # 在子进程中导入日志模块
        logging.exception(f"[THREAD-001] 工具进程执行异常: {e}")  # 记录异常详情
        result_queue.put({"_worker_error": True, "error": str(e)})  # 返回错误信息


# ========================================
# 确认对话框 - 安全回退实现
# ========================================
# 尝试导入确认对话框，如不存在则使用安全回退实现
try:
    from ui.confirm_dialog import confirm_dialog  # 尝试从UI模块导入
except ImportError:  # 导入失败时使用回退实现
    def confirm_dialog(message: str, title: str = "确认") -> bool:
        """
        命令行模式下的确认对话框 - 安全回退实现
        默认拒绝高危操作，需要用户显式确认

        Args:
            message: 确认消息内容
            title: 对话框标题

        Returns:
            bool: 用户是否确认，True表示允许执行
        """
        import os  # 导入os模块用于环境变量检查

        # 记录安全确认请求
        _get_logger().warning(f"\n[安全确认] {message}")
        _get_logger().warning("命令行模式：高危操作需要显式确认 (yes/no)")

        # 检查环境变量：批处理模式或自动确认标志
        if os.environ.get('SILICONBASE_BATCH_MODE') == '1':
            # 批处理模式下自动拒绝，防止无人值守时执行高危操作
            _get_logger().warning("[SECURITY] 批处理模式：自动拒绝高危操作")
            return False

        if os.environ.get('SILICONBASE_AUTO_CONFIRM') == '1':
            # 自动确认模式下强制允许（需谨慎使用）
            _get_logger().warning("[SECURITY] 警告：通过环境变量强制允许操作")
            return True

        try:
            # 检查是否为交互式终端
            import sys
            if not sys.stdin.isatty():  # 非交互式终端（如管道输入）
                _get_logger().warning("[SECURITY] 非交互式环境，自动拒绝高危操作")
                return False

            # 获取用户输入
            response = input("确认执行? (yes/no): ").strip().lower()  # 读取用户输入
            confirmed = response in ('yes', 'y', '是', '确认')  # 判断确认

            if not confirmed:
                _get_logger().info("用户拒绝了操作")  # 记录拒绝
            return confirmed  # 返回确认结果

        except EOFError:  # 文件结束错误（无输入）
            _get_logger().warning("[SECURITY] 输入中断，自动拒绝高危操作")
            return False
        except KeyboardInterrupt:  # Ctrl+C中断
            # 重新抛出，允许用户通过Ctrl+C中断程序
            raise
        except Exception as e:  # 其他异常
            _get_logger().error(f"[SILENT_FAILURE_BLOCKED][SECURITY] 确认对话框异常: {e}", exc_info=True)
            return False  # 安全原则：异常时默认拒绝


# ========================================
# THREAD-001 修复：进程池管理
# ========================================
class ProcessPool:
    """
    进程池管理器 - 管理工具执行进程，防止进程泄漏

    【THREAD-001修复】
    - 统一管理所有工具执行进程
    - 超时后强制终止进程
    - 定期清理僵尸进程

    【连接池保护】
    - 限制最大并发进程数，避免子进程创建过多数据库连接
    """

    _instance = None  # 单例实例
    _lock = threading.Lock()  # 实例化锁，确保线程安全

    # 【连接池保护】最大并发进程数，防止子进程耗尽PostgreSQL连接池
    MAX_CONCURRENT_PROCESSES = 4

    def __new__(cls):
        """单例模式实现 - 确保全局只有一个实例"""
        if cls._instance is None:  # 检查是否已创建
            with cls._lock:  # 加锁防止并发创建
                if cls._instance is None:  # 双重检查
                    cls._instance = super().__new__(cls)  # 创建实例
        return cls._instance  # 返回单例

    def __init__(self):
        """初始化进程池管理器"""
        if getattr(self, '_initialized', False):  # 检查是否已初始化
            return  # 避免重复初始化
        self._initialized = True  # 标记已初始化
        # 使用弱引用字典存储活跃进程，自动清理已结束的进程
        self._active_processes: dict[str, weakref.ref] = {}  # 任务ID -> 进程弱引用
        self._process_lock = threading.RLock()  # 进程字典操作锁
        self._cleanup_interval = 60  # 清理间隔(秒)
        self._last_cleanup = time.time()  # 上次清理时间
        # 【连接池保护】信号量限制并发进程数
        self._process_semaphore = threading.Semaphore(self.MAX_CONCURRENT_PROCESSES)

    def register_process(self, task_id: str, process: mp.Process):
        """
        注册进程到进程池

        Args:
            task_id: 任务唯一标识
            process: multiprocessing.Process实例
        """
        with self._process_lock:  # 加锁保护字典操作
            self._active_processes[task_id] = weakref.ref(process)  # 存储弱引用
            self._cleanup_if_needed()  # 按需清理

    def unregister_process(self, task_id: str):
        """
        从进程池注销进程

        Args:
            task_id: 任务唯一标识
        """
        with self._process_lock:  # 加锁保护
            if task_id in self._active_processes:  # 检查是否存在
                del self._active_processes[task_id]  # 删除记录

    def terminate_process(self, task_id: str):
        """
        强制终止指定进程

        Args:
            task_id: 任务唯一标识
        """
        with self._process_lock:  # 加锁保护
            if task_id in self._active_processes:  # 检查是否存在
                process_ref = self._active_processes[task_id]  # 获取弱引用
                process = process_ref() if process_ref else None  # 解引用
                if process and process.is_alive():  # 进程仍在运行
                    try:
                        process.terminate()  # 发送终止信号
                        # 等待进程终止
                        process.join(timeout=2)  # 最多等待2秒
                        # 如果仍未终止，强制杀死
                        if process.is_alive():
                            process.kill()  # 强制杀死
                            process.join(timeout=1)  # 再等待1秒
                        _get_logger().warning(f"[ProcessPool] 强制终止进程: {task_id}")
                    except Exception as e:
                        _get_logger().error(f"[SILENT_FAILURE_BLOCKED][ProcessPool] 终止进程失败 {task_id}: {e}", exc_info=True)
                self.unregister_process(task_id)  # 从字典移除

    def cleanup_finished(self):
        """清理已结束的进程"""
        with self._process_lock:  # 加锁保护
            finished = []  # 记录已结束的进程ID
            for task_id, process_ref in list(self._active_processes.items()):  # 遍历副本
                process = process_ref() if process_ref else None  # 解引用
                if process is None or not process.is_alive():  # 已结束
                    finished.append(task_id)  # 加入待清理列表
            for task_id in finished:  # 清理已结束进程
                del self._active_processes[task_id]  # 删除记录
            if finished:  # 有清理发生时记录日志
                _get_logger().debug(f"[ProcessPool] 清理 {len(finished)} 个已结束进程")

    def _cleanup_if_needed(self):
        """按需清理 - 超过清理间隔时触发清理"""
        if time.time() - self._last_cleanup > self._cleanup_interval:  # 检查间隔
            self.cleanup_finished()  # 执行清理
            self._last_cleanup = time.time()  # 更新清理时间

    def get_active_count(self) -> int:
        """
        获取活跃进程数

        Returns:
            int: 当前活跃进程数量
        """
        with self._process_lock:  # 加锁保护
            self.cleanup_finished()  # 先清理
            return len(self._active_processes)  # 返回数量

    def terminate_all(self):
        """终止所有活跃进程（用于程序退出）"""
        with self._process_lock:  # 加锁保护
            for _task_id, process_ref in list(self._active_processes.items()):  # 遍历
                process = process_ref() if process_ref else None  # 解引用
                if process and process.is_alive():  # 仍在运行
                    try:
                        process.terminate()  # 终止
                        process.join(timeout=1)  # 等待1秒
                    except Exception as e:
                        logger = _get_logger()
                        logger.error(f"[SILENT_FAILURE_BLOCKED] 进程终止失败，尝试强制kill: {e}", exc_info=True)
                        try:
                            process.kill()
                            process.join(timeout=2)
                        except Exception as e2:
                            logger.error(f"[SILENT_FAILURE_BLOCKED] 强制kill也失败: {e2}", exc_info=True)
            self._active_processes.clear()  # 清空字典


# 全局进程池实例 - 单例模式
_process_pool = ProcessPool()


# ========================================
# 子进程工作函数（备用）
# ========================================
def _execute_tool_worker(tool_class_name: str, tool_module: str,
                         params: dict, result_queue: mp.Queue,
                         error_queue: mp.Queue):
    """
    子进程工作函数 - 在独立进程中执行工具

    【THREAD-001修复】
    此函数在模块级别定义，可以被multiprocessing正确pickle

    Args:
        tool_class_name: 工具类名（如 "ScreenshotTool"）
        tool_module: 工具模块路径（如 "tools.screenshot"）
        params: 执行参数字典
        result_queue: multiprocessing.Queue 成功结果队列
        error_queue: multiprocessing.Queue 错误队列
    """
    try:
        # 动态导入工具类
        module = importlib.import_module(tool_module)  # 导入模块
        tool_class = getattr(module, tool_class_name)  # 获取类
        tool = tool_class()  # 实例化

        # 执行工具
        result = tool.run(**params)  # 调用run方法
        result_queue.put({"success": True, "result": result})  # 放入成功队列
    except Exception as e:  # 捕获所有异常
        error_queue.put({"success": False, "error": str(e)})  # 放入错误队列


# ========================================
# 工具执行上下文 - 按用户隔离
# ========================================
@dataclass
class ToolExecutionContext:
    """
    工具执行上下文 - 按用户隔离的执行状态

    每个用户拥有独立的：
    - 审计日志：记录用户的所有工具调用历史
    - 失败计数：追踪工具失败次数用于技能生成
    - 执行统计：汇总用户的工具使用统计

    Attributes:
        user_id: 用户唯一标识
        _audit_log: 审计日志列表
        _failure_counts: 各工具失败次数计数器
        _failure_threshold: 触发技能生成的失败阈值
        _execution_stats: 执行统计数据
        _lock: 线程锁，保护共享数据
    """
    user_id: str  # 用户ID，用于标识上下文归属
    _audit_log: list[dict] = field(default_factory=list)  # 审计日志，默认空列表
    _failure_counts: dict[str, int] = field(default_factory=dict)  # 失败计数，默认空字典
    _failure_threshold: int = 2  # 失败阈值，超过则触发技能生成
    _execution_stats: dict[str, Any] = field(default_factory=lambda: {
        "total_calls": 0,      # 总调用次数
        "success_calls": 0,    # 成功调用次数
        "failed_calls": 0,     # 失败调用次数
        "total_duration": 0.0, # 总执行耗时
        "tools_used": set()    # 使用过的工具集合
    })
    _lock: threading.RLock = field(default_factory=threading.RLock)  # 可重入锁

    def record_audit(self, entry: dict):
        """
        记录审计日志

        Args:
            entry: 审计日志条目字典，包含tool_id/params/success等字段
        """
        with self._lock:  # 加锁保护
            self._audit_log.append(entry)  # 添加到日志列表
            # 限制审计日志大小，防止内存无限增长
            if len(self._audit_log) > 10000:  # 超过10000条时
                self._audit_log = self._audit_log[-5000:]  # 保留后5000条

            # 更新统计数据
            self._execution_stats["total_calls"] += 1  # 总调用数+1
            if entry.get("success"):  # 执行成功
                self._execution_stats["success_calls"] += 1  # 成功数+1
            else:  # 执行失败
                self._execution_stats["failed_calls"] += 1  # 失败数+1
            self._execution_stats["total_duration"] += entry.get("duration", 0)  # 累加耗时
            self._execution_stats["tools_used"].add(entry.get("tool_id", "unknown"))  # 记录工具

    def record_failure(self, tool_id: str) -> bool:
        """
        记录工具失败

        Args:
            tool_id: 失败的工具ID

        Returns:
            bool: 是否超过失败阈值，True表示需要生成技能
        """
        with self._lock:  # 加锁保护
            self._failure_counts[tool_id] = self._failure_counts.get(tool_id, 0) + 1  # 计数+1
            return self._failure_counts[tool_id] >= self._failure_threshold  # 检查阈值

    def reset_failure(self, tool_id: str):
        """
        重置失败计数

        Args:
            tool_id: 要重置的工具ID
        """
        with self._lock:  # 加锁保护
            if tool_id in self._failure_counts:  # 存在则删除
                del self._failure_counts[tool_id]

    def get_audit_log(self, limit: int = 100) -> list[dict]:
        """
        获取审计日志

        Args:
            limit: 返回条目数量限制，默认100

        Returns:
            List[dict]: 最近的审计日志条目列表
        """
        with self._lock:  # 加锁保护
            return self._audit_log[-limit:]  # 返回后limit条

    def clear_audit_log(self):
        """清空审计日志"""
        with self._lock:  # 加锁保护
            self._audit_log.clear()  # 清空列表

    def get_stats(self) -> dict[str, Any]:
        """
        获取执行统计

        Returns:
            Dict[str, Any]: 执行统计信息，包含调用次数、成功率等
        """
        with self._lock:  # 加锁保护
            stats = self._execution_stats.copy()  # 复制统计数据
            stats["tools_used"] = list(stats["tools_used"])  # 集合转列表（JSON序列化）
            stats["failure_counts"] = self._failure_counts.copy()  # 复制失败计数
            return stats


# ========================================
# 工具执行上下文工厂 - 管理所有用户的上下文
# ========================================
class ToolContextFactory:
    """
    工具执行上下文工厂 - 管理所有用户的执行上下文

    使用方式：
        context = ToolContextFactory.get_context("user_001")
        context.record_audit({...})
    """

    _contexts: dict[str, ToolExecutionContext] = {}  # 用户ID -> 上下文字典
    _lock = threading.RLock()  # 工厂操作锁

    @classmethod
    def get_context(cls, user_id: str) -> ToolExecutionContext:
        """
        获取或创建用户的执行上下文

        Args:
            user_id: 用户唯一标识

        Returns:
            ToolExecutionContext: 用户执行上下文
        """
        with cls._lock:  # 加锁保护
            if user_id not in cls._contexts:  # 用户上下文不存在
                cls._contexts[user_id] = ToolExecutionContext(user_id=user_id)  # 创建新上下文
                _get_logger().debug(f"[ToolContextFactory] 创建用户执行上下文: {user_id}")
            return cls._contexts[user_id]  # 返回用户上下文

    @classmethod
    def remove_context(cls, user_id: str):
        """
        移除用户执行上下文（用户登出时调用）

        Args:
            user_id: 用户唯一标识
        """
        with cls._lock:  # 加锁保护
            if user_id in cls._contexts:  # 存在则删除
                del cls._contexts[user_id]
                _get_logger().info(f"[ToolContextFactory] 移除用户执行上下文: {user_id}")

    @classmethod
    def get_all_contexts(cls) -> dict[str, ToolExecutionContext]:
        """
        获取所有执行上下文（用于管理）

        Returns:
            Dict[str, ToolExecutionContext]: 所有用户的上下文副本
        """
        with cls._lock:  # 加锁保护
            return cls._contexts.copy()  # 返回副本

    @classmethod
    def get_global_stats(cls) -> dict[str, Any]:
        """
        获取全局统计

        Returns:
            Dict[str, Any]: 全局统计信息，包含用户总数、总调用次数等
        """
        with cls._lock:  # 加锁保护
            total_calls = 0  # 总调用次数
            total_users = len(cls._contexts)  # 用户总数
            all_tools = set()  # 所有使用过的工具

            for ctx in cls._contexts.values():  # 遍历所有用户上下文
                stats = ctx.get_stats()
                total_calls += stats["total_calls"]  # 累加调用次数
                all_tools.update(stats.get("tools_used", []))  # 合并工具集合

            return {
                "total_users": total_users,        # 用户总数
                "total_calls": total_calls,        # 总调用次数
                "unique_tools_used": len(all_tools),  # 使用的不同工具数量
                "active_contexts": list(cls._contexts.keys())  # 活跃用户列表
            }

    @classmethod
    def clear_all(cls):
        """清空所有上下文（用于测试）"""
        with cls._lock:  # 加锁保护
            cls._contexts.clear()  # 清空字典


# ========================================
# 工具管理器主类 - 核心组件
# ========================================
class ToolManager:
    """
    工具管理器 - 单例模式，线程安全

    【2026-02-26 重构说明】
    - 工具注册仍然是全局的（工具代码是共享的）
    - 但执行上下文按用户隔离（审计日志、失败计数等）
    - 通过 ToolContextFactory 管理用户执行上下文

    主要职责：
    1. 工具加载和管理（从tools目录自动加载）
    2. 工具执行和调度（支持超时、隔离）
    3. 权限检查和安全控制
    4. 审计日志和执行记忆
    5. 工具分类和发现
    """

    _instance = None  # 单例实例
    _lock = threading.Lock()  # 实例化锁
    _rw_lock = threading.RLock()  # 读写锁，保护工具字典

    # 【P1修复】工具调用DuplicateGuard：覆盖非AgentLoop路径（HTTP、workflow、fast path等）
    _tool_dedup_cache: dict[str, dict[str, Any]] = {}  # key -> {result, timestamp, success}
    _dedup_lock = threading.Lock()
    _DEDUP_TTL_SECONDS = 300  # 成功调用5分钟内去重
    _DEDUP_FAILURE_TTL_SECONDS = 10  # 失败调用10s内去重

    # 类级别共享线程池，避免频繁创建销毁
    _executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=8,                    # 最大8个工作线程
        thread_name_prefix="tool_exec_"   # 线程名前缀
    )

    # 沙箱测试超时时间（秒）
    SANDBOX_TIMEOUT = 5

    def __new__(cls):
        """单例模式实现"""
        if cls._instance is None:  # 检查是否已创建
            with cls._lock:  # 加锁
                if cls._instance is None:  # 双重检查
                    cls._instance = super().__new__(cls)  # 创建实例
        return cls._instance  # 返回单例

    # 【连接池保护】需要访问记忆系统的工具列表 - 这些工具使用线程模式执行
    # 其他工具使用子进程模式执行，避免创建数据库连接
    MEMORY_TOOLS = {
        'memory_add',      # 添加记忆
        'memory_search',   # 搜索记忆
        'memory_update',   # 更新记忆
        'memory_list',     # 列出记忆
        'memory_delete',   # 删除记忆
        'launch_app',      # 启动应用（会记录到记忆）
    }

    def __init__(self):
        """初始化工具管理器"""
        if getattr(self, '_initialized', False):  # 检查是否已初始化
            return  # 避免重复初始化
        self._initialized = True  # 标记已初始化

        # 工具字典：tool_id -> BaseTool实例
        self._tools: dict[str, BaseTool] = {}

        # 【保留】向后兼容的全局审计日志（新代码应使用用户隔离的上下文）
        self._audit_log: list[dict] = []

        # 【保留】向后兼容的全局失败计数（新代码应使用用户隔离的上下文）
        self._failure_counts = {}
        self._failure_threshold = 2  # 失败阈值

        # 加载所有工具
        self._load_all_tools()

        # 订阅配置变更事件，支持动态更新
        event_bus.subscribe("config_changed", self._on_config_changed)
        self._config_subscription = True  # 标记已订阅

        # 【MCP 支持】委托给 ToolRouter
        self._tool_router = None
        try:
            from core.tool.tool_router import ToolRouter
            self._tool_router = ToolRouter()
        except Exception as e:
            _get_logger().warning(f"[ToolManager] ToolRouter 初始化失败（非关键）: {e}")

        _get_logger().info("[ToolManager] 初始化完成（支持用户隔离执行上下文）")
        _get_logger().info(f"[ToolManager] 记忆工具列表: {self.MEMORY_TOOLS}")

    @property
    def tools(self) -> dict[str, BaseTool]:
        """
        获取所有工具的只读字典（用于API访问）

        Returns:
            Dict[str, BaseTool]: 工具ID到工具实例的映射字典
        """
        with self._rw_lock:
            return self._tools.copy()

    def _load_all_tools(self):
        """加载tools目录及BTC引擎tools目录下所有工具类"""
        import importlib.util  # 用于从文件路径导入模块

        loaded_count = 0  # 加载计数器
        deprecated_count = 0  # 废弃工具计数器

        # ===== 扫描 core/tools/ =====
        tools_dir = Path(__file__).parent.parent.parent / "tools"
        # 【优雅修复】已知不是 BaseTool 的辅助模块，跳过扫描避免 WARNING
        SKIP_NON_TOOL_FILES = {
            "apply_pixel_capture_fix",
            "clipboard_core",
            "manage_admin",
            "migrate_software_info_id",
            "repair_venv",
            "test_memory_six_dimensions_simple",
            "web_content_extractor",
            "web_proxy_utils",
        }
        if tools_dir.exists():
            # 扫描 tools/ 和 tools/generated/
            patterns = ["*.py", "generated/*.py"]
            for pattern in patterns:
                for py_file in tools_dir.glob(pattern):
                    if py_file.stem.startswith("_"):
                        continue  # 跳过私有文件
                    if py_file.stem in SKIP_NON_TOOL_FILES:
                        continue  # 跳过已知辅助模块

                    # 构建模块名
                    if "generated" in str(py_file.relative_to(tools_dir)):
                        module_name = f"tools.generated.{py_file.stem}"
                    else:
                        module_name = f"tools.{py_file.stem}"

                    try:
                        module = importlib.import_module(module_name)  # 导入模块
                        importlib.reload(module)  # 重新加载（支持热更新）
                        found = False
                        for attr_name in dir(module):  # 遍历模块所有属性
                            attr = getattr(module, attr_name)
                            # 检查是否为BaseTool的子类（排除BaseTool本身）
                            if (inspect.isclass(attr) and
                                    issubclass(attr, BaseTool) and
                                    attr != BaseTool):
                                found = True
                                tool = attr()  # 实例化工具
                                # 检查工具是否实现了 _execute 或 _execute_async
                                has_execute = hasattr(tool, '_execute') and callable(getattr(tool, '_execute', None))
                                has_execute_async = hasattr(tool, '_execute_async') and callable(getattr(tool, '_execute_async', None))
                                # 排除 BaseTool 自身的默认实现（未重写的 _execute 会抛 NotImplementedError）
                                is_base_execute = getattr(tool._execute, '__qualname__', '').startswith('BaseTool._execute')
                                if not has_execute_async and (not has_execute or is_base_execute):
                                    _get_logger().warning(f"[ToolManager] 跳过注册：工具 {getattr(tool, 'tool_id', attr_name)} 未实现 _execute 或 _execute_async")
                                    continue
                                # 检查工具是否标记为废弃
                                if getattr(tool, 'deprecated', False):
                                    deprecated_reason = getattr(tool, 'deprecated_reason', '无说明')
                                    _get_logger().warning(f"[ToolManager] 加载废弃工具: {tool.tool_id} - {deprecated_reason}")
                                    deprecated_count += 1
                                with self._rw_lock:  # 加锁保护
                                    self._tools[tool.tool_id] = tool  # 注册到字典
                                loaded_count += 1
                                _get_logger().debug(f"加载工具: {tool.tool_id}")
                        if not found:
                            _get_logger().warning(f"[ToolManager] 文件 {py_file.name} 未找到有效的 BaseTool 子类，跳过")
                    except Exception as e:
                        _get_logger().error(f"[SILENT_FAILURE_BLOCKED] 加载工具 {py_file.name} 失败: {e}", exc_info=True)
        else:
            _get_logger().warning(f"tools/ 目录不存在 ({tools_dir})，跳过工具加载")

        # ===== 扫描 tools/btc_trading/ =====
        btc_tools_pkg_dir = Path(__file__).parent.parent.parent / "tools" / "btc_trading"
        if btc_tools_pkg_dir.exists():
            for py_file in btc_tools_pkg_dir.glob("*.py"):
                if py_file.stem.startswith("_"):
                    continue
                module_name = f"tools.btc_trading.{py_file.stem}"
                try:
                    module = importlib.import_module(module_name)
                    importlib.reload(module)
                    found = False
                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)
                        if (inspect.isclass(attr) and
                                issubclass(attr, BaseTool) and
                                attr != BaseTool):
                            found = True
                            tool = attr()
                            if getattr(tool, 'deprecated', False):
                                deprecated_reason = getattr(tool, 'deprecated_reason', '无说明')
                                _get_logger().warning(f"[ToolManager] 加载废弃工具: {tool.tool_id} - {deprecated_reason}")
                                deprecated_count += 1
                            with self._rw_lock:
                                self._tools[tool.tool_id] = tool
                            loaded_count += 1
                            _get_logger().debug(f"加载工具: {tool.tool_id}")
                    if not found:
                        _get_logger().debug(f"[ToolManager] BTC交易工具文件 {py_file.name} 未找到有效的 BaseTool 子类，跳过")
                except (Exception, SystemExit) as e:
                    _get_logger().error(f"[SILENT_FAILURE_BLOCKED] 加载BTC交易工具 {py_file.name} 失败: {e}", exc_info=True)

        # ===== 扫描 core/btc_integration/tools/ =====
        btc_integration_tools_dir = Path(__file__).parent.parent.parent / "core" / "btc_integration" / "tools"
        if btc_integration_tools_dir.exists():
            for py_file in btc_integration_tools_dir.glob("*.py"):
                if py_file.stem.startswith("_"):
                    continue
                module_name = f"core.btc_integration.tools.{py_file.stem}"
                try:
                    module = importlib.import_module(module_name)
                    importlib.reload(module)
                    found = False
                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)
                        if (inspect.isclass(attr) and
                                issubclass(attr, BaseTool) and
                                attr != BaseTool):
                            found = True
                            tool = attr()
                            if getattr(tool, 'deprecated', False):
                                deprecated_reason = getattr(tool, 'deprecated_reason', '无说明')
                                _get_logger().warning(f"[ToolManager] 加载废弃工具: {tool.tool_id} - {deprecated_reason}")
                                deprecated_count += 1
                            with self._rw_lock:
                                tool._source = "btc_integration"
                                self._tools[tool.tool_id] = tool
                            loaded_count += 1
                            _get_logger().debug(f"加载工具: {tool.tool_id}")
                    if not found:
                        _get_logger().warning(f"[ToolManager] BTC集成工具文件 {py_file.name} 未找到有效的 BaseTool 子类，跳过")
                except (Exception, SystemExit) as e:
                    _get_logger().error(f"[SILENT_FAILURE_BLOCKED] 加载BTC集成工具 {py_file.name} 失败: {e}", exc_info=True)

        # ===== 扫描 core/btc_integration/engine/tools/ =====
        btc_tools_dir = Path(__file__).parent.parent.parent / "core" / "btc_integration" / "engine" / "tools"
        if btc_tools_dir.exists():
            # 【优雅修复】如果目录包含 .toolignore，则跳过整个目录的扫描
            # 该目录下是量化研究脚本（非 BaseTool），扫描会产生 200+ 条 WARNING
            if (btc_tools_dir / ".toolignore").exists():
                _get_logger().info(f"[ToolManager] 目录 {btc_tools_dir.name} 包含 .toolignore，跳过扫描")
                # 仍需把 engine/src 加入 sys.path，供其他模块内部引用
                _btc_src_path = str(btc_tools_dir.parent / "src")
                _btc_engine_path = str(btc_tools_dir.parent)
                if _btc_src_path not in sys.path:
                    sys.path.insert(0, _btc_src_path)
                if _btc_engine_path not in sys.path:
                    sys.path.insert(0, _btc_engine_path)
            else:
                # 【P0修复】将 engine/src 和 engine 目录加入 sys.path，使 BTC 工具内部导入可解析
                _btc_src_path = str(btc_tools_dir.parent / "src")
                _btc_engine_path = str(btc_tools_dir.parent)
                if _btc_src_path not in sys.path:
                    sys.path.insert(0, _btc_src_path)
                if _btc_engine_path not in sys.path:
                    sys.path.insert(0, _btc_engine_path)

                for py_file in btc_tools_dir.glob("*.py"):
                    if py_file.stem.startswith("_"):
                        continue  # 跳过私有文件

                    module_name = f"btc_integration.engine.tools.{py_file.stem}"

                    try:
                        spec = importlib.util.spec_from_file_location(module_name, py_file)
                        if spec is None or spec.loader is None:
                            _get_logger().warning(f"[ToolManager] 无法为 {py_file.name} 创建模块规范，跳过")
                            continue
                        module = importlib.util.module_from_spec(spec)
                        module.__package__ = "core.btc_integration.engine.tools"
                        sys.modules[module_name] = module
                        spec.loader.exec_module(module)

                        found = False
                        for attr_name in dir(module):
                            attr = getattr(module, attr_name)
                            if (inspect.isclass(attr) and
                                    issubclass(attr, BaseTool) and
                                    attr != BaseTool):
                                found = True
                                tool = attr()
                                if getattr(tool, 'deprecated', False):
                                    deprecated_reason = getattr(tool, 'deprecated_reason', '无说明')
                                    _get_logger().warning(f"[ToolManager] 加载废弃工具: {tool.tool_id} - {deprecated_reason}")
                                    deprecated_count += 1
                                with self._rw_lock:
                                    tool._source = "btc_engine"
                                    self._tools[tool.tool_id] = tool
                                loaded_count += 1
                                _get_logger().debug(f"加载工具: {tool.tool_id}")
                        if not found:
                            _get_logger().warning(f"[ToolManager] BTC工具文件 {py_file.name} 未找到有效的 BaseTool 子类，跳过")
                    except (ModuleNotFoundError, ImportError, SystemExit) as e:
                        # 【P0修复】BTC 工具依赖的底层模块（src/backtest/ 等）不存在，降级为 DEBUG 避免刷屏
                        _get_logger().debug(f"[ToolManager] BTC工具 {py_file.name} 依赖缺失，已静默跳过: {e}")
                    except Exception as e:
                        _get_logger().error(f"[SILENT_FAILURE_BLOCKED] 加载BTC工具 {py_file.name} 失败: {e}", exc_info=True)
        else:
            _get_logger().warning(f"BTC tools/ 目录不存在 ({btc_tools_dir})，跳过BTC工具加载")

        _get_logger().info(f"[ToolManager] 共加载 {loaded_count} 个工具，其中 {deprecated_count} 个废弃工具")

    def _on_config_changed(self, new_config):
        """配置变更回调 - 响应配置更新事件"""
        _get_logger().info("[ToolManager] 配置已变更，重新加载工具白名单等")
        with self._rw_lock:  # 加锁保护
            pass  # 预留：根据新配置更新工具白名单

    def shutdown(self):
        """关闭工具管理器：取消事件订阅并关闭线程池"""
        _get_logger().info("[ToolManager] 正在关闭，取消事件订阅...")
        try:
            event_bus.unsubscribe("config_changed", self._on_config_changed)  # 取消订阅
        except Exception as e:
            _get_logger().error(f"[SILENT_FAILURE_BLOCKED][ToolManager] 取消订阅失败: {e}", exc_info=True)
        try:
            if ToolManager._executor:
                ToolManager._executor.shutdown(wait=True)
                # 【架构红线】atexit 阶段禁止使用 logger，使用 print
                print("[ToolManager] 线程池已关闭", file=sys.stderr)
        except Exception as e:
            _get_logger().error(f"[SILENT_FAILURE_BLOCKED][ToolManager] 关闭线程池失败: {e}", exc_info=True)
        _get_logger().info("[ToolManager] 事件订阅已清理完成")

    # ========================================
    # 工具别名映射 - AI常用错误名称映射到正确ID
    # ========================================
    TOOL_ALIASES = {
        # 常见错误映射 - 帮助AI正确使用工具
        "app_launch": "launch_app",
        "open_app": "launch_app",
        "start_app": "launch_app",
        "run_app": "launch_app",
        "execute_app": "launch_app",
        "start_program": "launch_app",
        "file": "file_manager",
        # "read_file": "file_manager",  # 【修复】read_file是独立工具，支持分页读取
        "view_file": "read_file",
        "open_file": "read_file",
        "cat_file": "read_file",
        "write_file": "file_manager",
        "delete_file": "file_manager",
        "list_files": "file_manager",
        "mouse": "mouse_click",
        "click": "mouse_click",
        "click_mouse": "mouse_click",
        "mouse_press": "mouse_click",
        "left_click": "mouse_click",
        "right_click": "mouse_click",
        "keyboard": "keyboard_input",
        "type": "keyboard_input",
        "type_text": "keyboard_input",
        "input_text": "keyboard_input",
        "press_key": "keyboard_input",
        "send_keys": "keyboard_input",
        "screenshot": "pixel_capture",
        "capture_screen": "pixel_capture",
        "grab_screen": "pixel_capture",
        "screen_grab": "pixel_capture",
        "window": "window_get",
        "get_window": "window_get",
        "focus_window": "window_focus",
        "focus": "window_focus",
        "activate_window": "window_focus",
        "bring_to_front": "window_focus",
        "memory": "memory_add",
        "add_memory": "memory_add",
        "remember": "memory_add",
        "save_memory": "memory_add",
        "store_memory": "memory_add",
        "create_memory": "memory_add",
        "recall": "memory_search",
        # === Shell/终端相关 ===
        "shell": "shell_execute",
        "terminal": "shell_execute",
        "bash": "shell_execute",
        "cmd": "shell_execute",
        "powershell": "shell_execute",
        "执行命令": "shell_execute",
        "运行命令": "shell_execute",
        "终端": "shell_execute",
        "命令行": "shell_execute",
        "web": "web_open",
        "open_web": "web_open",
        "browser": "web_open",
        "open_url": "web_open",
        "navigate_to": "web_open",
        "goto_url": "web_open",
        "search": "web_search",
        "google": "web_search",
        "search_web": "web_search",
        "internet_search": "web_search",
        "google_search": "web_search",
        "process": "process_start",
        "kill_process": "process_kill",
        "clipboard": "clipboard",
        "clipboard_get": "clipboard_get",
        "clipboard_set": "clipboard_set",
        "copy": "clipboard_set",
        "paste": "clipboard_get",
        "get_clipboard": "clipboard_get",
        "read_clipboard": "clipboard_get",
        "set_clipboard": "clipboard_set",
        "write_clipboard": "clipboard_set",
        "ocr": "screen_ocr",
        "recognize_text": "screen_ocr",
        "read_screen": "screen_ocr",
        "text_recognition": "screen_ocr",
        "click_text": "click_text",
        "find_text": "click_text",
        "system": "system_info",
        "info": "system_info",
        "system_status": "system_info",
        "computer_info": "system_info",
        "pc_info": "system_info",
        "ask": "get_tool_manual",
        "inquire": "get_tool_manual",
        "ask_tools": "get_tool_manual",
        "template": "template_match",
        "match_template": "template_match",
        "pixel": "pixel_color",
        "get_pixel": "pixel_color",
        "click_pixel": "pixel_click",
        "wait": "wait_for_window",
        "wait_window": "wait_for_window",
        "visual": "visual_understand",
        "understand": "visual_understand",
        "analyze_screen": "visual_understand",
        "screen_analysis": "visual_understand",
        "icon": "icon_recognize",
        "recognize_icon": "icon_recognize",
        "code": "code_generate",
        "generate_code": "code_generate",
        "vpn": "vpn_connect",
        "connect_vpn": "vpn_connect",
        "tron": "tron_balance_updater",
        "balance": "tron_balance_updater",
        "export": "export_data",
        "delete_data": "delete_user_data",
        "manual": "get_tool_manual",
        "help_tool": "get_tool_manual",
        "call": "call_user",
        "notify": "call_user",
        "perception": "get_perception",
        "see": "get_perception",
        "find_element": "find_screen_element",
        "element": "find_screen_element",
        "locate_element": "find_screen_element",
        "find_file": "find_file",
        "search_file": "find_file",
        "locate_file": "find_file",
        "lookup_file": "find_file",
        "capture": "pixel_capture",
        "monitor": "pixel_monitor",
        "form": "smart_form_fill",
        "fill_form": "smart_form_fill",
        "click_smart": "find_and_click",
        "smart_click": "find_and_click",
        "fetch": "web_fetch",
        "http": "web_fetch",
        "parse": "web_parse",
        "scrape": "web_parse",
        "auto_web": "web_automation",
        "web_automation": "web_automation",
        "browser_auto": "web_automation",
        "real_browser": "web_automation",
        "playwright": "web_automation",
        "浏览器自动化": "web_automation",
        "自动浏览器": "web_automation",
        "真实浏览器": "web_automation",
        "window_action": "window_action",
        "action_window": "window_action",
        "window_rect": "window_rect",
        "get_rect": "window_rect",
        "window_ocr": "window_ocr",
        "ocr_window": "window_ocr",
        "app_search": "app_search",
        "search_app": "app_search",
        "update_memory": "memory_update",
        "search_memory": "memory_search",
        "find_memory": "memory_search",
        "query_memory": "memory_search",
        "delete_memory": "memory_delete",
        "remove_memory": "memory_delete",
        "replace_memory": "memory_replace",
        "list_memory": "memory_list",
        "show_memories": "memory_list",
        "get_memories": "memory_list",
        "list_memories": "memory_list",
        # === 浏览目录相关 ===
        "browse_directory": "browse_dir",
        "浏览文件夹": "browse_dir",
        "打开文件夹": "browse_dir",
        "dir_browse": "browse_dir",
        # === 定时任务相关（闹钟型）===
        "创建定时任务": "create_task",
        "新建定时任务": "create_task",
        "添加定时任务": "create_task",
        "定时任务": "create_task",
        "定时执行": "create_task",
        "自动执行": "create_task",
        "定时提醒": "create_task",
        "循环任务": "create_task",
        "周期性任务": "create_task",
        "每天执行": "create_task",
        "每小时执行": "create_task",
        "new_task": "create_task",
        "add_task": "create_task",
        "schedule_task": "create_task",
        "cron_job": "create_task",
        "timer": "create_task",
        "reminder": "create_task",
        "闹钟": "create_task",
        # === 长期任务相关（3槽位面板）===
        "创建长期任务": "create_long_task",
        "新建长期任务": "create_long_task",
        "添加长期任务": "create_long_task",
        "长期任务": "create_long_task",
        "可暂停任务": "create_long_task",
        "复杂任务": "create_long_task",
        "长时间运行": "create_long_task",
        "渐进式任务": "create_long_task",
        "需要暂停": "create_long_task",
        "长时间任务": "create_long_task",
        "3槽位任务": "create_long_task",
        "long_task": "create_long_task",
        "pausable_task": "create_long_task",
        "complex_task": "create_long_task",
        "暂停长期任务": "pause_long_task",
        "恢复长期任务": "resume_long_task",
        "取消长期任务": "cancel_long_task",
        "长期任务状态": "get_long_task_status",
        "查询长期任务": "get_long_task_status",
        # === 子代理相关 ===
        "委派子代理": "delegate_to_subagent",
        "调用子代理": "delegate_to_subagent",
        "子代理": "delegate_to_subagent",
        "创建子代理": "delegate_to_subagent",
        "分配子代理": "delegate_to_subagent",
        "delegate": "delegate_to_subagent",
        "subagent": "delegate_to_subagent",
        "子代理状态": "get_subagent_status",
        "干预子代理": "intervene_subagent",
        "暂停子代理": "intervene_subagent",
        "取消子代理": "intervene_subagent",
        "可用子代理": "list_available_subagents",
        "列出子代理": "list_available_subagents",
        "代码审查": "delegate_to_subagent",
        "安全审计": "delegate_to_subagent",
        "性能优化": "delegate_to_subagent",
        "删除任务": "delete_task",
        "移除任务": "delete_task",
        "remove_task": "delete_task",
        "del_task": "delete_task",
        "获取任务": "get_task",
        "查询任务": "get_task",
        "查看任务": "get_task",
        "query_task": "get_task",
        "任务列表": "list_tasks",
        "列出任务": "list_tasks",
        "所有任务": "list_tasks",
        "all_tasks": "list_tasks",
        "tasks": "list_tasks",
        "更新任务": "update_task",
        "修改任务": "update_task",
        "编辑任务": "update_task",
        "edit_task": "update_task",
        "modify_task": "update_task",
        # === 时间相关 ===
        "当前时间": "current_time",
        "现在时间": "current_time",
        "获取时间": "current_time",
        "时间": "current_time",
        "time_now": "current_time",
        "get_time": "current_time",
        # === 工具手册相关 ===
        "工具分类": "get_tool_categories_l1",
        "工具类别": "get_tool_categories_l1",
        "tool_categories": "get_tool_categories_l1",
        "工具详情": "get_tool_detail_l3",
        "工具说明": "get_tool_detail_l3",
        "tool_detail": "get_tool_detail_l3",
        "按分类获取工具": "get_tools_by_category_l2",
        "分类工具": "get_tools_by_category_l2",
        "tools_by_category": "get_tools_by_category_l2",
        "切换提示层": "switch_prompt_layer",
        "切换层级": "switch_prompt_layer",
        "switch_layer": "switch_prompt_layer",
        # === 文件搜索相关 ===
        "索引文件列表": "list_indexed_files",
        "已索引文件": "list_indexed_files",
        "indexed_files": "list_indexed_files",
        # === 应用相关 ===
        "已安装应用": "list_installed_apps",
        "应用列表": "list_installed_apps",
        "程序列表": "list_installed_apps",
        "installed_apps": "list_installed_apps",
        "applications": "list_installed_apps",
        "programs": "list_installed_apps",
        # === OCR文字识别相关 ===
        "文字识别": "ocr_text",
        "识别文字": "ocr_text",
        "提取文字": "ocr_text",
        "文字提取": "ocr_text",
        "text_ocr": "ocr_text",
        "extract_text": "ocr_text",
        # === 窗口操作相关 ===
        "打开并聚焦": "open_and_focus",
        "open_focus": "open_and_focus",
        "启动并聚焦": "open_and_focus",
        "launch_and_focus": "open_and_focus",
        # === 模板相关 ===
        "删除模板": "template_delete",
        "移除模板": "template_delete",
        "remove_template": "template_delete",
        "模板列表": "template_list",
        "列出模板": "template_list",
        "templates": "template_list",
        "录制模板": "template_record",
        "记录模板": "template_record",
        "record_template": "template_record",
        # === AI智能体相关 ===
        "UI智能体": "ui_tars",
        "ui_agent": "ui_tars",
        "界面智能": "ui_tars",
        "界面代理": "ui_tars",
        "视觉智能体": "vision_agent",
        "vision_ai": "vision_agent",
        "图像理解智能体": "vision_agent",
        "视觉代理": "vision_agent",
        # === VPN相关 ===
        "VPN检查": "vpn_check",
        "检查VPN": "vpn_check",
        "vpn_status": "vpn_check",
        "check_vpn": "vpn_check",
    }

    # ═══════════════════════════════════════════════════════════════
    # MCP 支持（委托给 ToolRouter）
    # ═══════════════════════════════════════════════════════════════

    async def enable_mcp(self, configs: list[dict]) -> dict[str, bool]:
        """
        启用 MCP 支持

        委托给 ToolRouter 处理 MCP 服务器连接。
        """
        if self._tool_router is None:
            try:
                from core.tool.tool_router import ToolRouter
                self._tool_router = ToolRouter()
            except Exception as e:
                _get_logger().error(f"[ToolManager] ToolRouter 初始化失败: {e}")
                return {}

        return await self._tool_router.enable_mcp(configs)

    def is_mcp_enabled(self) -> bool:
        """检查 MCP 是否已启用"""
        if self._tool_router is None:
            return False
        return self._tool_router._mcp_enabled

    def get_mcp_status(self) -> dict[str, Any]:
        """获取 MCP 状态"""
        if self._tool_router is None:
            return {
                "enabled": False,
                "servers": [],
                "tools_count": 0,
                "servers_detail": []
            }

        try:
            mcp_tools = list(self._tool_router._mcp_tools.keys()) if hasattr(self._tool_router, '_mcp_tools') else []
            return {
                "enabled": self._tool_router._mcp_enabled,
                "servers": list(self._tool_router.connections.keys()) if hasattr(self._tool_router, 'connections') else [],
                "tools_count": len(mcp_tools),
                "servers_detail": []
            }
        except Exception as e:
            _get_logger().error(f"[ToolManager] 获取 MCP 状态失败: {e}")
            return {
                "enabled": False,
                "servers": [],
                "tools_count": 0,
                "servers_detail": []
            }

    def get_mcp_tools(self) -> dict[str, Any]:
        """获取所有 MCP 工具"""
        if self._tool_router is None:
            return {}
        return self._tool_router._mcp_tools if hasattr(self._tool_router, '_mcp_tools') else {}

    async def disable_mcp(self) -> None:
        """禁用 MCP 支持"""
        if self._tool_router is None:
            return
        await self._tool_router.disable_mcp()

    # ═══════════════════════════════════════════════════════════════

    def get_tool(self, tool_id: str) -> BaseTool | None:
        """
        获取指定工具实例（支持别名）

        Args:
            tool_id: 工具ID或别名

        Returns:
            Optional[BaseTool]: 工具实例，不存在返回None
        """
        with self._rw_lock:  # 加锁保护
            tool = self._tools.get(tool_id)  # 尝试直接获取
            if tool:
                return tool  # 找到直接返回
            if tool_id in self.TOOL_ALIASES:  # 检查别名映射
                real_id = self.TOOL_ALIASES[tool_id]
                _get_logger().debug(f"[ToolManager] 工具别名映射: {tool_id} -> {real_id}")
                return self._tools.get(real_id)  # 返回映射的工具
            return None  # 未找到

    def get_categories(self) -> dict[str, list[dict]]:
        """
        获取按类别分组的工具列表

        Returns:
            Dict[str, List[dict]]: 分类名 -> 工具信息列表
        """
        with self._rw_lock:  # 加锁保护
            categories = {}  # 结果字典
            for tid, t in self._tools.items():  # 遍历所有工具
                category = getattr(t, 'category', '其他')  # 获取分类，默认"其他"
                if category not in categories:
                    categories[category] = []  # 初始化分类列表
                categories[category].append({  # 添加工具信息
                    "id": tid,
                    "name": t.name,
                    "description": getattr(t, "description", "")
                })
            return categories

    def list_tools(self) -> list[dict]:
        """
        返回所有工具的详细信息（不区分模式）

        Returns:
            List[dict]: 工具详细信息列表
        """
        with self._rw_lock:  # 加锁保护
            result = []
            for tid, t in self._tools.items():  # 遍历所有工具
                params_desc = []  # 参数描述列表
                if t.input_schema and t.input_schema.get("properties"):
                    required = t.input_schema.get("required", [])  # 必需参数列表
                    for pname, pinfo in t.input_schema["properties"].items():
                        req_flag = "（必需）" if pname in required else "（可选）"  # 是否必需
                        ptype = pinfo.get("type", "any")  # 参数类型
                        if "enum" in pinfo:
                            ptype = f"枚举值: {pinfo['enum']}"  # 枚举类型特殊显示
                        default = pinfo.get("default")  # 默认值
                        default_str = f"，默认值: {default}" if default is not None else ""
                        desc = pinfo.get("description", "")  # 参数描述
                        params_desc.append(f"    - `{pname}` ({ptype}) {req_flag}{default_str}：{desc}".strip())
                if not params_desc:
                    params_desc = ["    无参数"]  # 无参数时的占位
                result.append({  # 添加工具完整信息
                    "id": tid,
                    "name": t.name,
                    "description": getattr(t, "description", ""),
                    "parameters": "\n".join(params_desc),
                    "returns": getattr(t, 'output_schema', {}),  # 输出模式
                    "is_duplicate": getattr(t, 'is_duplicate', False),
                    "duplicate_of": getattr(t, 'duplicate_of', '')
                })
            return result

    def list_tools_structured(self, mode: str = None) -> list[dict]:
        """
        返回工具的详细信息，包括参数结构（从 input_schema 解析）。

        Args:
            mode: 运行模式，用于过滤白名单工具

        Returns:
            List[dict]: 结构化工具信息列表
        """
        with self._rw_lock:  # 加锁保护
            tools = []
            for tid, t in self._tools.items():  # 遍历所有工具
                if mode:  # 指定了模式，需要过滤
                    whitelist = _get_config().get(f"mode.{mode}.tool_whitelist", [])
                    if whitelist and tid not in whitelist:  # 不在白名单中
                        continue  # 跳过

                params = []
                if t.input_schema and "properties" in t.input_schema:
                    required = t.input_schema.get("required", [])  # 必需参数
                    for pname, pinfo in t.input_schema["properties"].items():
                        param = {
                            "name": pname,
                            "type": pinfo.get("type", "any"),
                            "description": pinfo.get("description", ""),
                            "required": pname in required,
                        }
                        if "enum" in pinfo:
                            param["enum"] = pinfo["enum"]  # 添加枚举值
                        if "default" in pinfo:
                            param["default"] = pinfo["default"]  # 添加默认值
                        params.append(param)

                tools.append({  # 添加结构化信息
                    "id": tid,
                    "name": t.name,
                    "description": getattr(t, "description", ""),
                    "params": params,
                    "output_schema": t.output_schema,
                    "timeout": t.timeout,
                    "require_confirmation": t.require_confirmation,
                    "is_duplicate": getattr(t, 'is_duplicate', False),
                    "duplicate_of": getattr(t, 'duplicate_of', '')
                })
            return tools

    def list_tools_for_mode(self, mode: str) -> list[dict]:
        """
        返回指定模式允许的工具列表（根据配置文件中的白名单过滤）

        Args:
            mode: 运行模式（如 "secure", "standard"）

        Returns:
            List[dict]: 该模式下允许的工具列表
        """
        whitelist = _get_config().get(f"mode.{mode}.tool_whitelist", [])
        all_tools = self.list_tools()  # 获取所有工具
        if not whitelist:  # 白名单为空，返回全部
            return all_tools
        filtered = [t for t in all_tools if t['id'] in whitelist]  # 过滤
        return filtered

    def build_compact_tool_list(self, tools=None, mode: str = None):
        """
        为AI生成完整的工具清单（可指定模式过滤）

        Args:
            tools: 工具列表（为None则自动获取）
            mode: 运行模式过滤

        Returns:
            str: 格式化的工具清单文本
        """
        if tools is None:  # 未提供工具列表
            tools = self.list_tools_for_mode(mode) if mode else self.list_tools()  # 按模式或获取全部
        if not tools:  # 无可用工具
            return "【可用工具清单】当前无可用工具。"
        lines = ["【可用工具清单】", f"当前共 {len(tools)} 个工具：\n"]  # 标题
        for t in tools:  # 遍历工具
            lines.append(f"🔧 **{t['id']}** - {t['name']}")
            lines.append(f"   描述：{t['description']}")
            lines.append(f"   参数：\n{t['parameters']}")
        return "\n".join(lines)

    def _resolve_variables(
        self,
        params: dict,
        context: dict,
        depth: int = 0,
        max_depth: int = 10,
        visited: set = None
    ) -> dict:
        """
        递归替换参数中的变量引用（以 $ 开头的字符串）

        支持嵌套对象和数组，防止循环引用和无限递归。

        Args:
            params: 需要解析变量的参数字典
            context: 变量上下文（包含可替换的变量值）
            depth: 当前递归深度（内部使用）
            max_depth: 最大允许递归深度，默认10
            visited: 已访问对象ID集合（用于检测循环引用，内部使用）

        Returns:
            解析后的参数字典

        Raises:
            RecursionError: 当递归深度超过max_depth或检测到循环引用时
        """
        # 初始化visited集合（只在顶层调用时创建）
        if visited is None:
            visited = set()

        # 检查递归深度
        if depth > max_depth:
            raise RecursionError(
                f"变量解析递归深度超过限制 (depth={depth}, max_depth={max_depth}). "
                f"可能存在过度嵌套的参数结构。"
            )

        # 检查循环引用（使用id()比较对象身份）
        params_id = id(params)
        if params_id in visited:
            raise RecursionError(
                f"检测到循环引用: 对象 {type(params).__name__} (id={params_id}) 被重复访问。 "
                f"请检查参数中是否存在循环嵌套。"
            )

        # 将当前对象加入已访问集合
        visited.add(params_id)

        try:
            resolved = {}
            for key, value in params.items():
                if isinstance(value, str) and value.startswith('$'):
                    # 变量引用，从上下文中解析
                    parts = value[1:].split('.')  # 按点分割路径
                    cur = context
                    for part in parts:
                        if isinstance(cur, dict):
                            cur = cur.get(part)  # 继续深入
                        else:
                            cur = None  # 路径中断
                            break
                    resolved[key] = cur  # 解析结果
                elif isinstance(value, dict):
                    # 嵌套字典，递归解析
                    resolved[key] = self._resolve_variables(
                        value, context, depth + 1, max_depth, visited
                    )
                elif isinstance(value, list):
                    # 列表，递归解析其中的字典
                    resolved[key] = [
                        self._resolve_variables(v, context, depth + 1, max_depth, visited)
                        if isinstance(v, dict) else v
                        for v in value
                    ]
                else:
                    resolved[key] = value  # 其他类型直接保留
            return resolved
        finally:
            # 清理已访问集合（避免影响其他分支）
            visited.discard(params_id)

    def _get_current_task_context(self) -> dict:
        """
        获取当前任务的上下文信息（用于世界模型）

        Returns:
            dict: 任务上下文信息
        """
        try:
            current_task = task_queue.current_task()  # 获取当前任务
            if current_task:
                return {
                    "task_id": current_task.id,
                    "task_type": current_task.task_type,
                    "intent": getattr(current_task, "intent", None),
                    "step": getattr(current_task, "current_step", 0),
                    "total_steps": getattr(current_task, "total_steps", 0)
                }
        except Exception as e:
            _get_logger().error(f"[SILENT_FAILURE_BLOCKED][ToolManager] 获取当前任务上下文失败: {e}", exc_info=True)
        return {}  # 无任务时返回空

    def _get_user_id_from_context(self) -> str:
        """
        从当前任务上下文中获取用户ID

        Returns:
            str: 用户ID，如果无法获取则返回 "default"
        """
        try:
            current_task = task_queue.current_task()  # 获取当前任务
            if current_task:
                user_id = getattr(current_task, "user_id", None)  # 获取user_id属性
                if user_id:
                    return user_id  # 返回用户ID
        except Exception as e:
            _get_logger().error(f"[SILENT_FAILURE_BLOCKED][ToolManager] 获取任务信息失败: {e}", exc_info=True)
        return "default"  # 默认用户ID

    def _get_session_id_from_context(self) -> str:
        """
        从当前任务上下文中获取会话ID

        Returns:
            str: 会话ID，如果无法获取则返回用户ID或 "default"
        """
        try:
            current_task = task_queue.current_task()
            if current_task:
                session_id = getattr(current_task, "session_id", None)
                if session_id:
                    return session_id
                user_id = getattr(current_task, "user_id", None)
                if user_id:
                    return user_id
        except Exception as e:
            _get_logger().debug(f"[ToolManager] 获取会话ID失败: {e}")
        return "default"

    def _build_dedup_key(self, session_id: str, tool_id: str, params: dict[str, Any]) -> str:
        """构建DuplicateGuard缓存key"""
        import hashlib
        import json
        _param_hash = hashlib.md5(json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()[:8]
        return f"{session_id}:{tool_id}:{_param_hash}"

    def _check_dedup_cache(self, key: str) -> dict[str, Any] | None:
        """检查去重缓存，命中且未过期则返回结果，否则返回None"""
        with self._dedup_lock:
            cached = self._tool_dedup_cache.get(key)
            if not cached:
                return None
            age = time.time() - cached.get("timestamp", 0)
            ttl = self._DEDUP_FAILURE_TTL_SECONDS if cached.get("failure") else self._DEDUP_TTL_SECONDS
            if age > ttl:
                self._tool_dedup_cache.pop(key, None)
                return None
            return cached

    def _cache_dedup_result(self, key: str, result: dict[str, Any]):
        """写入去重缓存"""
        success = bool(result and result.get("success", False))
        with self._dedup_lock:
            self._tool_dedup_cache[key] = {
                "result": result,
                "timestamp": time.time(),
                "success": success,
                "failure": not success,
            }

    def _build_result(self, success: bool, data: Any = None, error_code: str = None,
                      user_message: str = None, duration: float = None) -> dict:
        """
        构建统一的返回结果格式

        Args:
            success: 是否成功
            data: 返回数据
            error_code: 错误代码
            user_message: 用户可见消息
            duration: 执行耗时（秒）

        Returns:
            dict: 标准化结果字典
        """
        result = {
            "success": success,
            "data": data,
            "error_code": error_code or ("" if success else "UNKNOWN_ERROR"),
            "user_message": user_message or ("操作成功" if success else "操作失败"),
            "duration": round(duration, 3) if duration is not None else 0.0
        }
        return result

    # ========================================
    # 工具链建议映射 - 错误码到建议列表的映射
    # ========================================
    TOOL_CHAIN_SUGGESTIONS = {
        # 应用相关错误
        "APP_NOT_FOUND": [
            "建议: 使用 list_installed_apps 查看已安装的应用列表",
            "建议: 使用 app_search 搜索应用名称",
            "建议: 尝试使用应用的英文名或完整路径",
            "建议: 确认应用是否已正确安装"
        ],
        # 文件相关错误
        "FILE_NOT_FOUND": [
            "建议: 使用 file_manager 查看当前目录下的文件",
            "建议: 使用 file_manager 逐级浏览目录结构",
            "建议: 检查文件路径是否正确，注意大小写敏感",
            "建议: 尝试使用绝对路径而非相对路径"
        ],
        "FILE_EXISTS": [
            "建议: 如需覆盖，先使用 file_manager 删除旧文件",
            "建议: 更换文件名或使用 file_manager 查看现有文件"
        ],
        "PATH_NOT_FOUND": [
            "建议: 使用 file_manager 检查目录是否存在",
            "建议: 先创建父目录再执行操作"
        ],
        # 权限相关错误
        "PERMISSION_DENIED": [
            "建议: 该操作需要管理员权限，询问用户是否以管理员身份运行",
            "建议: 尝试修改文件/目录的权限设置",
            "建议: 更换到有权限的目录进行操作"
        ],
        "PROTECTED_PATH": [
            "建议: 系统路径受保护，选择用户目录进行操作",
            "建议: 使用系统提供的标准用户目录（如Documents、Desktop等）"
        ],
        "PROTECTED_PROCESS": [
            "建议: 系统进程受保护，无法终止",
            "建议: 如需终止，请用户手动操作"
        ],
        # 参数相关错误
        "INVALID_PARAMS": [
            "建议: 检查工具参数是否符合schema要求",
            "建议: 查看工具的input_schema获取参数说明",
            "建议: 确保所有必需参数都已提供",
            "建议: 检查参数类型是否正确（字符串vs数字）"
        ],
        # 超时相关错误
        "TOOL_TIMEOUT": [
            "建议: 目标应用/窗口可能未响应，尝试等待后重试",
            "建议: 检查目标状态，确认是否可以正常交互",
            "建议: 尝试增加超时时间",
            "建议: 如果是网络操作，检查网络连接状态"
        ],
        "QUEUE_TIMEOUT": [
            "建议: 工具执行结果获取超时，可能是进程异常",
            "建议: 稍后重试或检查系统资源使用情况"
        ],
        # 工具相关错误
        "TOOL_NOT_FOUND": [
            "建议: 检查工具名称拼写是否正确",
            "建议: 使用 list_tools 查看所有可用工具",
            "建议: 查看工具别名映射（如 'read_file' -> 'file_read'）"
        ],
        "TOOL_EXECUTION_ERROR": [
            "建议: 工具执行异常，检查环境依赖是否完整",
            "建议: 查看详细错误信息，确定具体失败原因",
            "建议: 尝试简化操作步骤，分步执行"
        ],
        # 进程相关错误
        "PROCESS_NOT_FOUND": [
            "建议: 使用 process_list 查看所有运行中的进程",
            "建议: 确认进程名称是否正确（注意.exe后缀）"
        ],
        # 窗口相关错误
        "WINDOW_NOT_FOUND": [
            "建议: 使用 window_get 或 window_list 查看可用窗口",
            "建议: 确认窗口标题关键词是否正确",
            "建议: 尝试使用 launch_app 先启动应用"
        ],
        # 网络相关错误
        "NETWORK_ERROR": [
            "建议: 检查网络连接状态",
            "建议: 尝试使用其他URL或稍后重试",
            "建议: 检查目标网站是否可访问"
        ],
        "URL_ERROR": [
            "建议: 检查URL格式是否正确（需要http://或https://）",
            "建议: 尝试更换协议（http vs https）"
        ],
        # 搜索相关错误
        "SEARCH_NO_RESULTS": [
            "建议: 尝试使用更通用的关键词",
            "建议: 尝试使用英文关键词",
            "建议: 检查搜索范围是否正确"
        ],
        # 记忆相关错误
        "MEMORY_NOT_FOUND": [
            "建议: 使用 memory_search 搜索相关记忆",
            "建议: 尝试使用更宽泛的关键词",
            "建议: 确认记忆是否已创建"
        ],
        # 截图/OCR相关错误
        "SCREENSHOT_FAILED": [
            "建议: 检查屏幕是否处于锁定状态",
            "建议: 尝试重新执行截图操作",
            "建议: 检查是否有足够的磁盘空间"
        ],
        "OCR_FAILED": [
            "建议: 检查截图区域是否包含可识别文本",
            "建议: 尝试调整截图区域",
            "建议: 确认OCR服务是否正常运行"
        ],
        # 通用取消错误
        "USER_CANCELLED": [
            "建议: 用户取消了操作，询问用户原因",
            "建议: 提供替代方案给用户选择"
        ],
        "CANCELLED": [
            "建议: 操作被取消，尝试重新执行",
            "建议: 检查取消原因后再决定下一步"
        ],
    }

    # 空结果时的工具特定建议
    EMPTY_RESULT_SUGGESTIONS = {
        "list_installed_apps": [
            "说明: 未找到已安装应用，可能原因：",
            "  - 应用扫描功能需要特定权限",
            "  - 系统应用目录访问受限",
            "建议: 尝试直接使用 launch_app 启动已知应用",
            "建议: 询问用户应用的具体路径"
        ],
        "app_search": [
            "说明: 未找到匹配的应用，可能原因：",
            "  - 应用名称拼写错误",
            "  - 应用使用英文名而非中文名",
            "  - 应用未安装",
            "建议: 尝试使用英文名搜索",
            "建议: 使用 list_installed_apps 查看所有应用"
        ],
        "file_manager": [
            "说明: 目录为空或不存在，可能原因：",
            "  - 目录确实没有文件",
            "  - 路径拼写错误",
            "  - 没有权限查看该目录",
            "建议: 检查路径拼写",
            "建议: 使用 file_manager 查看父目录"
        ],
        "process_list": [
            "说明: 未找到匹配的进程，可能原因：",
            "  - 进程名称拼写错误",
            "  - 进程尚未启动",
            "  - 进程已结束",
            "建议: 尝试使用部分名称匹配",
            "建议: 先使用 process_list 不带参数查看所有进程"
        ],
        "window_get": [
            "说明: 未找到匹配的窗口，可能原因：",
            "  - 窗口标题关键词不匹配",
            "  - 应用尚未启动",
            "  - 窗口被最小化到托盘",
            "建议: 使用 launch_app 先启动应用",
            "建议: 尝试使用更通用的窗口标题关键词"
        ],
        "memory_search": [
            "说明: 未找到相关记忆，可能原因：",
            "  - 记忆库为空",
            "  - 搜索关键词过于具体",
            "  - 相关记忆被删除",
            "建议: 尝试使用更宽泛的关键词",
            "建议: 使用 memory_list 查看所有记忆"
        ],
        "recall_memory": [
            "说明: 未找到相关记忆，可能原因：",
            "  - 记忆库为空",
            "  - 搜索关键词过于具体",
            "  - 相关记忆被删除",
            "建议: 尝试使用更宽泛的关键词",
            "建议: 使用 memory_list 查看所有记忆"
        ],
        "list_tasks": [
            "说明: 当前没有任务，可能原因：",
            "  - 任务队列为空",
            "  - 任务已完成或已取消",
            "建议: 使用 create_task 创建新任务"
        ],
        "web_search": [
            "说明: 搜索未返回结果，可能原因：",
            "  - 关键词过于具体",
            "  - 网络连接问题",
            "  - 搜索引擎限制",
            "建议: 尝试使用更通用的关键词",
            "建议: 检查网络连接后重试"
        ],
    }

    # 常用工具失败后的策略建议
    TOOL_FAILURE_STRATEGIES = {
        "launch_app": [
            "策略: 尝试使用应用的完整路径启动",
            "策略: 检查应用是否需要管理员权限",
            "策略: 尝试使用 window_focus 激活已运行的实例"
        ],
        "file_read": [
            "策略: 确认文件路径是否正确",
            "策略: 检查文件编码格式",
            "策略: 尝试读取其他文件测试"
        ],
        "file_write": [
            "策略: 确认目录是否存在，不存在则先创建",
            "策略: 检查磁盘空间是否充足",
            "策略: 确认是否有写入权限"
        ],
        "mouse_click": [
            "策略: 确认坐标是否在屏幕范围内",
            "策略: 尝试先使用 screenshot 查看当前屏幕",
            "策略: 如果目标在特定窗口内，先使用 window_focus 激活窗口"
        ],
        "keyboard_input": [
            "策略: 确认目标窗口已获取焦点",
            "策略: 如果是特殊按键，使用正确的按键名称",
            "策略: 对于中文输入，可能需要先切换到中文输入法"
        ],
        "pixel_capture": [
            "策略: 检查屏幕是否处于锁定状态",
            "策略: 确认截图区域坐标有效",
            "策略: 检查保存路径是否有写入权限"
        ],
        "web_open": [
            "策略: 确认URL格式正确",
            "策略: 检查是否需要特定的浏览器",
            "策略: 尝试使用 web_fetch 直接获取内容"
        ],
        "memory_add": [
            "策略: 检查记忆内容是否为空",
            "策略: 确认标签格式正确（列表格式）",
            "策略: 尝试简化记忆内容后重试"
        ],
        "create_task": [
            "策略: trigger_type必须是'once'(一次性)、'interval'(间隔)或'cron'(定时)",
            "策略: once类型使用delay_seconds(延迟秒数)或execute_at(ISO格式时间如'2026-04-10T08:00:00')",
            "策略: interval类型必须使用interval_seconds指定间隔秒数(如300表示5分钟)",
            "策略: cron类型必须使用cron_expression(如'0 8 * * *'表示每天8点，'*/5 * * * *'表示每5分钟)",
            "策略: 如需定时执行工具，提供tool_to_execute(工具ID)和tool_params(参数对象)",
            "策略: 示例: {name:'备份', description:'每日备份', trigger_type:'cron', cron_expression:'0 2 * * *', tool_to_execute:'backup_data'}",
            "策略: 【注意】这是定时任务（闹钟型），如需可暂停的长任务请用create_long_task"
        ],
        "create_long_task": [
            "策略: slot_id必须是1、2或3（3槽位面板）",
            "策略: task_name是任务名称，task_type是任务类型标识",
            "策略: user_requirements描述用户需求（恢复时需要AI确认理解）",
            "策略: 长期任务支持暂停/恢复、进度追踪、断点续传",
            "策略: 创建后可用pause_long_task暂停，resume_long_task恢复",
            "策略: 示例: {slot_id:1, task_name:'大数据分析', task_type:'data_analysis', user_requirements:'分析销售数据并生成报告'}"
        ],
        "delegate_to_subagent": [
            "策略: agent_type必须是: code_reviewer(代码审查)、tester(测试)、researcher(研究)、planner(架构)、security_auditor(安全)、performance_optimizer(性能)",
            "策略: task是任务描述，context是额外上下文",
            "策略: async_mode为true时异步执行，需后续查询状态；false时同步等待结果",
            "策略: 复杂任务可委派给子代理，主AI继续处理其他工作",
            "策略: 示例: {agent_type:'code_reviewer', task:'审查这段Python代码的质量', context:{code:'...'}}"
        ],
    }

    async def format_feedback_for_ai(self, tool_name: str, result: dict, context: dict = None) -> str:
        """
        将工具结果格式化为AI能理解的"身体感觉"

        【2026-03-09 增强版】底座反馈系统增强
        让工具执行后的反馈更清晰，像"身体感觉"一样可感知：
        - 成功时：不仅说"成功"，还要说"我看到..."
        - 失败时：不仅说"失败"，还要说"我尝试了...但..."
        - 不确定时：明确告诉AI"我不确定..."
        - 【新增】空结果时：标记为警告并提供替代建议

        Args:
            tool_name: 工具名称
            result: 工具执行结果字典，包含 success/data/error_code/user_message 等字段
            context: 额外上下文信息（可选），可以是字典或WorkingMemory对象

        Returns:
            str: 格式化的反馈消息，供AI理解
        """
        # 【修复】处理WorkingMemory对象：转换为字典或使用getattr安全访问
        if context is not None and not isinstance(context, dict):
            context = context.__dict__ if hasattr(context, '__dict__') else {}  # 转换为字典或使用空字典

        if not isinstance(result, dict):
            return f"【工具执行反馈】{tool_name}: 返回结果格式异常，无法解析"

        success = result.get("success", False)
        error_code = result.get("error_code")
        user_message = result.get("user_message", "")
        data = result.get("data", {}) or {}
        duration = result.get("duration", 0)

        # 检查是否为"成功但空结果"的情况
        is_empty_success = False
        empty_reason = None
        if success:
            is_empty_success, empty_reason = self._check_empty_result(tool_name, data)

        # 如果是成功但空结果，降级为警告
        if is_empty_success:
            return self._format_empty_warning(tool_name, user_message, data, empty_reason, duration)

        if success:
            # === 成功反馈：描述具体看到的效果 ===
            feedback_parts = [f"【工具执行成功】{tool_name}"]

            # 基础消息
            if user_message:
                feedback_parts.append(f": {user_message}")

            # 根据工具类型添加具体观察到的情况
            observations = []

            # 1. 窗口相关反馈（launch_app, window_get等）
            if "window" in data and isinstance(data["window"], dict):
                window = data["window"]
                title = window.get("title", "未知窗口")
                hwnd = window.get("hwnd")
                abnormal = window.get("abnormal", False)
                if abnormal:
                    observations.append(f"⚠️ 警告：窗口'{title}'可能是异常窗口（卸载/修复程序）")
                else:
                    observations.append(f"✓ 窗口'{title}'已就绪（句柄:{hwnd}）")

            # 2. 进程相关反馈
            if "pid" in data:
                pid = data["pid"]
                observations.append(f"✓ 进程已启动（PID:{pid}）")

            # 3. 文件相关反馈（file_write, file_read等）
            if "path" in data or "filepath" in data:
                path = data.get("path") or data.get("filepath")
                if isinstance(path, str):
                    observations.append(f"✓ 文件操作路径: {path}")

            if "content" in data and isinstance(data["content"], str):
                content_len = len(data["content"])
                preview = data["content"][:50] + "..." if content_len > 50 else data["content"]
                observations.append(f"✓ 内容长度: {content_len}字符，预览: {preview}")

            if "files" in data and isinstance(data["files"], list):
                file_count = len(data["files"])
                observations.append(f"✓ 找到{file_count}个文件/目录")

            # 4. 列表结果反馈 - 增强显示
            if "apps" in data and isinstance(data["apps"], list):
                app_count = len(data["apps"])
                observations.append(f"✓ 找到{app_count}个应用")
                if app_count > 0 and app_count <= 10:
                    # 显示前几个应用名称
                    app_names = [app.get("name", "未知") for app in data["apps"][:5]]
                    observations.append(f"  包括: {', '.join(app_names)}{' 等' if app_count > 5 else ''}")

            if "processes" in data and isinstance(data["processes"], list):
                proc_count = len(data["processes"])
                observations.append(f"✓ 找到{proc_count}个进程")

            if "windows" in data and isinstance(data["windows"], list):
                win_count = len(data["windows"])
                observations.append(f"✓ 找到{win_count}个窗口")

            if "tasks" in data and isinstance(data["tasks"], list):
                task_count = len(data["tasks"])
                observations.append(f"✓ 找到{task_count}个任务")

            if "memories" in data and isinstance(data["memories"], list):
                mem_count = len(data["memories"])
                observations.append(f"✓ 找到{mem_count}条相关记忆")

            # 5. 截图相关反馈
            if "filepath" in data and isinstance(data.get("filepath"), str) and ("screenshot" in tool_name.lower() or "截图" in tool_name):
                observations.append(f"✓ 截图已保存: {data['filepath']}")

            # 6. 验证状态
            if "verification" in data:
                verification = data["verification"]
                if verification == "verified":
                    observations.append("✓ 操作效果已验证确认")
                elif verification == "unverified":
                    observations.append("⚠️ 操作效果未经验证")
                elif isinstance(verification, dict):
                    confidence = verification.get("confidence", 0)
                    if confidence >= 0.8:
                        observations.append(f"✓ 验证置信度: {confidence:.0%}")
                    elif confidence >= 0.5:
                        observations.append(f"⚠️ 验证置信度较低: {confidence:.0%}")
                    else:
                        observations.append(f"❌ 验证置信度很低: {confidence:.0%}")

            # 7. 搜索/查询结果数量
            if "results" in data and isinstance(data["results"], list):
                result_count = len(data["results"])
                observations.append(f"✓ 返回{result_count}条结果")

            if "matches" in data and isinstance(data["matches"], list):
                match_count = len(data["matches"])
                observations.append(f"✓ 找到{match_count}个匹配")

            # 8. 耗时信息（如果超过1秒）
            if duration and duration > 1:
                observations.append(f"⏱ 执行耗时: {duration:.2f}秒")

            # 组合反馈
            if observations:
                feedback_parts.append("\n我观察到:\n" + "\n".join(f"  {obs}" for obs in observations))

            return "".join(feedback_parts)

        else:
            # === 失败反馈：描述尝试过程和失败原因 ===
            feedback_parts = [f"【工具执行失败】{tool_name}"]

            if user_message:
                feedback_parts.append(f": {user_message}")

            # 错误分析和建议
            suggestions = []

            if error_code:
                feedback_parts.append(f"\n错误码: {error_code}")

                # 从工具链建议映射获取建议
                if error_code in self.TOOL_CHAIN_SUGGESTIONS:
                    suggestions.extend(self.TOOL_CHAIN_SUGGESTIONS[error_code])
                else:
                    # 默认建议
                    suggestions.append(f"建议: 遇到{error_code}错误，可以尝试其他方法或询问用户")

            # 添加工具特定的失败策略建议
            if tool_name in self.TOOL_FAILURE_STRATEGIES:
                suggestions.append(f"\n【{tool_name}专项策略】")
                suggestions.extend(self.TOOL_FAILURE_STRATEGIES[tool_name])

            # 如果有data，显示相关信息
            if data and isinstance(data, dict):
                if "detail" in data:
                    suggestions.append(f"\n详细信息: {data['detail']}")
                if "suggestion" in data:
                    suggestions.append(f"工具建议: {data['suggestion']}")

            # 添加通用建议
            if not suggestions:
                suggestions.append("建议: 可以尝试其他方法完成此任务，或询问用户更多信息")

            if suggestions:
                feedback_parts.append("\n" + "\n".join(f"  • {s}" for s in suggestions))

            # 添加上下文提示
            if context:
                if context.get("retry_count", 0) > 0:
                    feedback_parts.append(f"\n⚠️ 这是第{context['retry_count']}次重试")
                if context.get("previous_tool"):
                    feedback_parts.append(f"\n上一步使用了: {context['previous_tool']}")

            return "".join(feedback_parts)

    def _check_empty_result(self, tool_name: str, data: dict) -> tuple:
        """
        检查结果是否为"成功但空"

        Args:
            tool_name: 工具名称
            data: 结果数据

        Returns:
            tuple: (是否为空, 原因描述)
        """
        if not isinstance(data, dict):
            return False, None

        # 检查各种可能的空列表情况
        list_fields = ["apps", "files", "processes", "windows",
                      "tasks", "memories", "results", "matches", "items"]

        for field_name in list_fields:
            if field_name in data and isinstance(data[field_name], list) and len(data[field_name]) == 0:
                return True, f"返回的{self._get_field_name(field_name)}列表为空"

        # 特殊检查 list_installed_apps
        if tool_name == "list_installed_apps" and "apps" in data and (not data["apps"] or len(data.get("apps", [])) == 0):
            return True, "未扫描到任何已安装应用"

        # 特殊检查 app_search
        if tool_name == "app_search" and "apps" in data and (not data["apps"] or len(data.get("apps", [])) == 0):
            return True, "未找到匹配的应用"

        # 检查搜索结果
        if tool_name == "web_search" and "results" in data and (not data["results"] or len(data.get("results", [])) == 0):
            return True, "搜索未返回结果"

        # 检查记忆搜索
        if tool_name in ["memory_search"]:
            memories = data.get("memories") or data.get("results") or data.get("matches")
            if isinstance(memories, list) and len(memories) == 0:
                return True, "未找到相关记忆"

        return False, None

    def _get_field_name(self, field: str) -> str:
        """获取字段的中文名称"""
        names = {
            "apps": "应用",
            "files": "文件",
            "processes": "进程",
            "windows": "窗口",
            "tasks": "任务",
            "memories": "记忆",
            "results": "结果",
            "matches": "匹配",
            "items": "项目"
        }
        return names.get(field, field)

    def _format_empty_warning(self, tool_name: str, user_message: str,
                               data: dict, reason: str, duration: float) -> str:
        """
        格式化"成功但空结果"的警告反馈

        Args:
            tool_name: 工具名称
            user_message: 用户消息
            data: 结果数据
            reason: 空结果原因
            duration: 执行耗时

        Returns:
            str: 格式化的警告消息
        """
        feedback_parts = [f"【工具执行警告】{tool_name}"]

        if user_message:
            feedback_parts.append(f": {user_message}")

        feedback_parts.append(f"\n⚠️ {reason}")

        # 添加工具特定的空结果建议
        suggestions = []

        # 从 EMPTY_RESULT_SUGGESTIONS 获取特定建议
        if tool_name in self.EMPTY_RESULT_SUGGESTIONS:
            suggestions.extend(self.EMPTY_RESULT_SUGGESTIONS[tool_name])
        else:
            # 通用空结果建议
            suggestions.extend([
                "建议: 尝试调整查询条件或参数",
                "建议: 确认目标是否存在",
                "建议: 检查是否有权限访问相关资源"
            ])

        # 添加相关工具建议
        related_tools = self._get_related_tools_for_empty(tool_name)
        if related_tools:
            suggestions.append("\n您可以尝试以下工具:")
            for tool_desc in related_tools:
                suggestions.append(f"  - {tool_desc}")

        feedback_parts.append("\n" + "\n".join(suggestions))

        if duration and duration > 1:
            feedback_parts.append(f"\n⏱ 执行耗时: {duration:.2f}秒")

        return "".join(feedback_parts)

    def _get_related_tools_for_empty(self, tool_name: str) -> list:
        """
        获取针对空结果的相关工具建议

        Args:
            tool_name: 当前工具名称

        Returns:
            list: 相关工具描述列表
        """
        related_map = {
            "list_installed_apps": [
                "app_search: 搜索特定应用",
                "launch_app: 直接尝试启动应用"
            ],
            "app_search": [
                "list_installed_apps: 列出所有应用",
                "launch_app: 使用完整路径启动"
            ],
            "file_list": [
                "file_list: 查看父目录",
                "file_read: 如果是文件则读取内容"
            ],
            "process_list": [
                "process_list: 不带参数查看所有进程",
                "system_info: 查看系统运行状态"
            ],
            "window_get": [
                "launch_app: 启动应用",
                "screenshot: 查看当前屏幕"
            ],
            "memory_search": [
                "memory_list: 查看所有记忆",
                "memory_add: 添加新记忆"
            ],
            "list_tasks": [
                "create_task: 创建定时任务(支持once/interval/cron三种触发方式)",
                "create_long_task: 创建3槽位长期任务(可暂停/恢复/进度追踪)",
                "delegate_to_subagent: 委派任务给子代理执行",
                "get_task: 查看特定任务状态"
            ],
            "web_search": [
                "web_open: 直接打开已知URL",
                "web_fetch: 获取特定页面内容"
            ],
        }
        return related_map.get(tool_name, [])

    def _sanitize_params_for_audit(self, params: dict) -> dict:
        """
        脱敏敏感参数，用于审计日志记录

        识别并隐藏密码、token等敏感信息，防止泄露。

        Args:
            params: 原始参数字典

        Returns:
            dict: 脱敏后的参数
        """
        if not isinstance(params, dict):  # 非字典直接返回
            return params

        # 敏感关键词列表
        SENSITIVE_KEYS = [
            'password', 'passwd', 'pwd', 'token', 'secret', 'key', 'api_key',
            'auth', 'authorization', 'credential', 'credentials', 'private',
            'private_key', 'access_token', 'refresh_token', 'session',
            'cookie', 'csrf', 'xsrf', 'nonce', 'signature', 'encrypt',
            'decrypt', 'cipher', 'plaintext'
        ]

        def should_redact(key: str) -> bool:
            """检查键名是否敏感"""
            key_lower = key.lower()
            return any(sensitive in key_lower for sensitive in SENSITIVE_KEYS)

        def sanitize_value(key: str, value: Any) -> Any:
            """对值进行脱敏处理"""
            if should_redact(key):  # 键名敏感
                if isinstance(value, str):
                    return f"***REDACTED(len={len(value)})***"  # 字符串脱敏
                elif isinstance(value, (int, float)):
                    return "***REDACTED(num)***"  # 数字脱敏
                else:
                    return "***REDACTED***"  # 其他类型脱敏

            # 长字符串截断显示
            if isinstance(value, str) and len(value) > 100:
                return value[:50] + "..." + value[-20:] + f" (len={len(value)})"

            # 嵌套字典递归脱敏
            if isinstance(value, dict):
                return {k: sanitize_value(k, v) for k, v in value.items()}

            # 列表中的字典递归脱敏
            if isinstance(value, list):
                return [sanitize_value("", item) if isinstance(item, (dict, list)) else item
                        for item in value]

            return value  # 其他类型直接返回

        return {k: sanitize_value(k, v) for k, v in params.items()}


    async def execute_tool(self, tool_id: str,
                     params: dict[str, Any] | None = None,
                     timeout: int | None = None,
                     source: str = "user",
                     user_id: str | None = None) -> dict[str, Any]:
        """
        执行工具（兼容旧版API）

        【修复】添加此方法以兼容 api_handlers.py 的调用
        实际上是 call_tool 的包装，确保有统一的超时机制

        Args:
            tool_id: 工具ID
            params: 工具参数（可选，默认空字典）
            timeout: 超时时间（秒，可选，默认30秒）
            source: 调用来源

        Returns:
            工具执行结果字典
        """
        if params is None:  # 参数为None时使用空字典
            params = {}

        # 如果指定了超时，临时修改工具的超时设置
        tool = self.get_tool(tool_id)  # 获取工具实例
        if tool and timeout is not None:  # 指定了超时时间
            original_timeout = getattr(tool, 'timeout', 30)  # 保存原始超时
            tool.timeout = timeout  # 设置临时超时
            try:
                result = await self.call_tool(tool_id, params, source=source, user_id=user_id)  # 执行
            finally:
                tool.timeout = original_timeout  # 恢复原始超时
            return result

        return await self.call_tool(tool_id, params, source=source, user_id=user_id)  # 正常执行

    async def execute_tool_async(self, tool_id: str,
                                 params: dict[str, Any] | None = None,
                                 timeout: int | None = None,
                                 source: str = "user",
                                 task_id: str | None = None,
                                 user_id: str | None = None) -> dict[str, Any]:
        """
        异步执行工具入口（Phase 4 新增）。

        核心原则：
        - 所有工具异步执行统一收口到 AsyncToolGateway，获得取消追踪和超时保护
        - 已实现 _execute_async 的走 gateway.execute_async() 包装原生 async 函数
        - 未实现的走 gateway.execute() 桥接到同步 execute_tool()
        """
        if params is None:
            params = {}

        tool = self.get_tool(tool_id)
        if tool is None:
            return {"success": False, "error_code": "TOOL_NOT_FOUND", "user_message": f"工具 {tool_id} 不存在", "data": None}

        from core.agent.async_tool_gateway import async_gateway
        gateway_task_id = task_id or f"tool_{tool_id}_{id(self)}_{time.time()}"

        # 优先检测工具是否已实现原生 async 接口
        # 用 type(tool)._execute_async 判断子类是否真正重写了 _execute_async，
        # 而不是仅仅继承了 BaseTool 的默认实现（会抛 NotImplementedError）。
        has_real_async = type(tool)._execute_async is not BaseTool._execute_async
        if has_real_async:
            try:
                # 临时修改超时（与同步版行为一致）
                if tool and timeout is not None:
                    original_timeout = getattr(tool, 'timeout', 30)
                    tool.timeout = timeout
                    try:
                        return await async_gateway.execute_async(
                            task_id=gateway_task_id,
                            async_fn=tool.run_async,
                            **params,
                            timeout=timeout
                        )
                    finally:
                        tool.timeout = original_timeout
                return await async_gateway.execute_async(
                    task_id=gateway_task_id,
                    async_fn=tool.run_async,
                    **params,
                    timeout=timeout
                )
            except NotImplementedError:
                # 工具声明了 run_async 但尚未真正实现，降级到同步桥接
                _get_logger().warning(
                    f"[ASYNC-DEBT] {tool_id} 声明了 run_async 但未实现 _execute_async，"
                    f"降级到 AsyncToolGateway.execute()"
                )
            except Exception as e:
                _get_logger().error(
                    f"[ToolManager] 工具 {tool_id} 原生 async 执行异常: {e}",
                    exc_info=True
                )
                return {
                    "success": False,
                    "error_code": "EXECUTION_ERROR",
                    "user_message": f"工具异步执行失败: {str(e)}",
                    "data": None
                }

        # 未改造工具直接异步执行（call_tool/execute_tool 已全面异步化）
        _get_logger().warning(
            f"[ASYNC-DEBT] {tool_id} 暂无原生 async 实现，直接 await execute_tool()"
        )
        if timeout is not None:
            return await asyncio.wait_for(
                self.execute_tool(tool_id, params, timeout=timeout, source=source, user_id=user_id),
                timeout=timeout
            )
        return await self.execute_tool(tool_id, params, source=source, user_id=user_id)

    async def call_tool(self, tool_id: str,
                  params: dict[str, Any],
                  source: str = "user",
                  user_id: str | None = None) -> ToolResult:
        """
        调用工具，统一返回格式，自动补全缺失字段，并记录审计日志

        【2026-02-26 更新】
        - 支持按用户隔离执行上下文
        - 新增 user_id 参数，如未提供则从任务上下文获取

        执行流程：
        1. 权限检查 - 检查工具是否允许执行
        2. 获取工具实例 - 支持别名映射
        3. 解析变量引用 - 替换 $ 开头的变量
        4. 高危工具确认 - 弹窗确认高危操作
        5. 保护路径/进程检查 - 防止误删系统文件
        6. 参数校验 - 校验参数是否符合schema
        7. 执行工具 - 在子进程中执行
        8. 标准化结果 - 确保返回格式统一
        9. 失败追踪与技能生成 - 失败多次时生成技能
        10. 世界模型记录 - 记录执行观察
        11. L5执行记忆记录 - 记录到长期记忆

        Args:
            tool_id: 工具ID
            params: 工具参数
            source: 调用来源 (user/reflection)
            user_id: 用户ID（可选，用于隔离执行上下文）

        Returns:
            ToolResult: 工具调用结果，包含success/data/error_code/user_message/duration

        契约：
            - 此方法返回的格式必须符合 ToolResult 接口定义
            - 调用方可以安全地访问 result["success"], result["data"] 等字段
            - 如需安全访问，可使用 SafeDictAccessor 包装结果
        """
        start_time = time.time()  # 记录开始时间

        # 获取用户ID
        if user_id is None:
            user_id = self._get_user_id_from_context()  # 从任务上下文获取

        # 获取会话ID（用于DuplicateGuard）
        _session_id = self._get_session_id_from_context()

        # 获取用户执行上下文
        user_context = ToolContextFactory.get_context(user_id)

        _get_logger().debug(f"[ToolManager] 调用工具: {tool_id}, source={source}, user={user_id}")

        # 初始化审计日志条目
        audit_entry = {
            "tool_id": tool_id,
            "params": self._sanitize_params_for_audit(params) if params else {},  # 脱敏参数
            "source": source,
            "user_id": user_id,
            "timestamp": start_time,
            "success": None,
            "error_code": None,
            "duration": None
        }

        def record_audit(success: bool, error_code: str = None, duration: float = None):
            """记录审计日志的内部函数"""
            audit_entry.update({  # 更新审计条目
                "success": success,
                "error_code": error_code,
                "duration": duration
            })
            # 记录到用户上下文
            user_context.record_audit(audit_entry)
            # 【向后兼容】同时记录到全局审计日志
            self._audit_log.append(audit_entry)
            if len(self._audit_log) > 10000:  # 限制全局日志大小
                self._audit_log = self._audit_log[-5000:]

        # ========== 1. 权限检查 ==========
        allowed, reason = await check_tool_allowed(tool_id, source)  # 检查权限
        if not allowed:  # 权限被拒绝
            duration = time.time() - start_time  # 计算耗时
            result = self._build_result(
                success=False,
                error_code="PERMISSION_DENIED",
                user_message=f"安全策略阻止该操作: {reason}",
                duration=duration
            )
            record_audit(False, "PERMISSION_DENIED", duration)  # 记录审计
            return result

        # ========== 2. 获取工具实例（支持别名映射）==========
        tool = self.get_tool(tool_id)  # 获取工具

        if not tool:  # 工具不存在
            duration = time.time() - start_time
            result = format_error(TOOL_NOT_FOUND)  # 返回工具未找到错误
            result["duration"] = duration
            record_audit(False, "TOOL_NOT_FOUND", duration)
            return result

        # ========== 3. 解析变量引用 ==========
        current_task = task_queue.current_task()  # 获取当前任务
        if current_task and hasattr(current_task, "execution_context"):
            try:
                params = self._resolve_variables(params, current_task.execution_context)  # 解析变量
            except Exception as e:
                _get_logger().error(f"[SILENT_FAILURE_BLOCKED] 变量解析失败: {e}", exc_info=True)  # 解析失败不影响主流程

        # ========== 3.5 DuplicateGuard 去重检查（覆盖非AgentLoop路径）==========
        _dedup_key = self._build_dedup_key(_session_id, tool_id, params)
        _cached_dedup = self._check_dedup_cache(_dedup_key)
        if _cached_dedup:
            _cached_result = _cached_dedup.get("result")
            _get_logger().warning(
                f"[ToolManager-DuplicateGuard] 命中缓存，直接返回结果: {tool_id} (key={_dedup_key})"
            )
            if isinstance(_cached_result, dict):
                _cached_result = dict(_cached_result)
                _cached_result["duplicate"] = True
            return _cached_result

        # ========== 4. 高危工具用户确认 ==========
        if tool.require_confirmation:  # 工具需要确认
            require_conf_list = _get_config().get("tools.require_confirmation", [])
            if tool_id in require_conf_list and not confirm_dialog(  # 在高危列表中
                f"即将执行高危操作：{tool.name}\n\n是否确认？",
                title="安全确认"
            ):
                duration = time.time() - start_time
                result = self._build_result(
                    success=False,
                    error_code="USER_CANCELLED",
                    user_message="用户取消操作",
                    duration=duration
                )
                record_audit(False, "USER_CANCELLED", duration)
                return result

        # ========== 5. 保护路径/进程检查 ==========
        if tool_id in ["file_delete", "file_write", "file_move"]:  # 文件操作工具
            path = params.get("path", "")
            if is_protected_path(path):  # 受保护路径
                duration = time.time() - start_time
                result = self._build_result(
                    success=False,
                    error_code="PROTECTED_PATH",
                    user_message=f"禁止操作受保护的路径: {path}",
                    duration=duration
                )
                record_audit(False, "PROTECTED_PATH", duration)
                return result

        if tool_id == "process_kill":  # 进程终止工具
            proc_name = params.get("name", "")
            if is_protected_process(proc_name):  # 受保护进程
                duration = time.time() - start_time
                result = self._build_result(
                    success=False,
                    error_code="PROTECTED_PROCESS",
                    user_message=f"禁止终止受保护的进程: {proc_name}",
                    duration=duration
                )
                record_audit(False, "PROTECTED_PROCESS", duration)
                return result

        # ========== 6. 参数校验 ==========
        check_res = tool.check_params(**params)  # 校验参数
        if not check_res.get("success"):  # 校验失败
            duration = time.time() - start_time
            error_code = check_res.get("error_code", "INVALID_PARAMS")
            user_message = check_res.get("user_message", "参数校验失败")
            result = self._build_result(
                success=False,
                error_code=error_code,
                user_message=user_message,
                duration=duration
            )
            record_audit(False, error_code, duration)
            return result

        # ========== 6.5 言行一致反射弧检查 ==========
        try:
            from core.runtime import system_state
            is_speaking = system_state.get_sync("speech.is_speaking", False)
            current_text = system_state.get_sync("speech.current_text", "")
            vision_alert = system_state.get_sync("vision.alert")

            # 如果语音在说"等等/让我看看/等一下"，延迟执行
            if is_speaking and any(word in current_text for word in ["等等", "让我看看", "等一下", "先别"]) and tool_id not in ["screenshot", "get_window_info", "visual_understand"]:
                logger.info(f"[ToolManager-Consistency] {tool_id} 因语音含暂停用语被延迟")
                return self._build_result(
                    success=False,
                    error_code="DELAYED_BY_SPEECH",
                    user_message="语音播报中指示暂停，工具执行已延迟",
                    duration=0.0
                )

            # 如果有视觉告警，非紧急工具延迟
            if vision_alert and tool_id not in ["screenshot", "get_window_info", "click_alert", "dismiss_dialog"]:
                alert_level = vision_alert.get("level", "L1") if isinstance(vision_alert, dict) else "L1"
                if alert_level in ("L2", "L3", "CRITICAL"):
                    logger.info(f"[ToolManager-Consistency] {tool_id} 因视觉告警({alert_level})被延迟")
                    return self._build_result(
                        success=False,
                        error_code="DELAYED_BY_VISION",
                        user_message=f"视觉告警({alert_level})未处理，工具执行已延迟",
                        duration=0.0
                    )
        except Exception:
            pass

        # ========== 7. 执行工具 ==========
        timeout = getattr(tool, 'timeout', 30)  # 获取工具超时设置
        task_id = current_task.id if current_task else "unknown"  # 任务ID

        # 反射弧：执行开始前写状态
        try:
            from core.runtime import system_state
            system_state.set_sync("action.current_tool", tool_id)
            system_state.set_sync("action.status", "running")
            system_state.set_sync("action.params", str(params)[:200])
        except Exception:
            pass

        print(f"[DEBUG] 即将执行工具: {tool_id}, timeout={timeout}")
        # 在子进程中执行工具（线程池桥接，避免阻塞事件循环）
        raw_result = await asyncio.to_thread(
            self._execute_tool_in_process, tool, tool_id, params, timeout, task_id
        )

        # 反射弧：执行完成后写状态
        try:
            from core.runtime import system_state
            system_state.set_sync("action.status", "completed" if (isinstance(raw_result, dict) and not raw_result.get("_execution_error")) else "failed")
            if isinstance(raw_result, dict) and raw_result.get("_execution_error"):
                system_state.set_sync("action.last_error", raw_result.get("error_code", "UNKNOWN"))
        except Exception:
            pass
        print(f"[DEBUG] 工具执行完成: {tool_id}, result_type={type(raw_result)}, has_error={isinstance(raw_result, dict) and raw_result.get('_execution_error')}")

        # 检查执行错误
        if isinstance(raw_result, dict) and raw_result.get("_execution_error"):
            error_type = raw_result.get("error_code")
            duration = time.time() - start_time
            if error_type == "TOOL_TIMEOUT":  # 超时错误
                result = format_error(TOOL_TIMEOUT, detail=raw_result.get("message"))
            elif error_type == "CANCELLED":  # 取消错误
                result = self._build_result(
                    success=False,
                    error_code="CANCELLED",
                    user_message="工具执行被取消",
                    duration=duration
                )
            else:  # 其他执行错误
                result = format_error(TOOL_EXECUTION_ERROR, detail=raw_result.get("message"))
            result["duration"] = duration
            record_audit(False, error_type or "EXECUTION_ERROR", duration)
            return result

        # ========== 8. 标准化返回结果 ==========
        duration = time.time() - start_time  # 计算总耗时

        # 【修复】确保结果是字典，并记录错误
        if not isinstance(raw_result, dict):
            logger.error(f"[ToolManager] {tool_id} 返回非字典结果: {type(raw_result)}")
            raw_result = {
                "success": False,
                "error_code": "INVALID_RETURN_TYPE",
                "user_message": f"工具返回格式错误: {type(raw_result).__name__}",
                "data": {"raw": str(raw_result)[:200]}
            }

        # 【修复】检查子进程执行错误标记
        if raw_result.get("_execution_error"):
            error_msg = raw_result.get("error", "子进程执行错误")
            logger.error(f"[ToolManager] {tool_id} 子进程执行错误: {error_msg}")
            # 确保标记为失败
            raw_result["success"] = False
            if "error_code" not in raw_result or not raw_result["error_code"]:
                raw_result["error_code"] = "EXECUTION_ERROR"
            if "user_message" not in raw_result or not raw_result["user_message"]:
                raw_result["user_message"] = f"工具执行失败: {error_msg}"
        elif "success" not in raw_result:
            # 正常路径：如果没有 success 字段，默认为 True
            raw_result["success"] = True
        if "error_code" not in raw_result:
            raw_result["error_code"] = None
        if "user_message" not in raw_result:
            if raw_result.get("success"):
                raw_result["user_message"] = "操作成功"
            else:
                raw_result["user_message"] = raw_result.get("message", "工具执行失败")
        if "data" not in raw_result:
            raw_result["data"] = None
        raw_result["duration"] = round(duration, 3)  # 添加耗时字段

        record_audit(
            raw_result.get("success", False),
            raw_result.get("error_code"),
            duration
        )

        # ========== 失败追踪与技能生成 ==========
        if not raw_result.get("success"):  # 执行失败
            tool_id = tool.tool_id
            exceeded = user_context.record_failure(tool_id)  # 记录失败

            # 【向后兼容】同时更新全局失败计数
            self._failure_counts[tool_id] = self._failure_counts.get(tool_id, 0) + 1

            if exceeded:  # 超过失败阈值
                try:
                    from core.evolution.skill_generator import try_generate_skill  # 尝试生成技能
                    generated = await try_generate_skill(
                        task=f"修复 {tool_id} 的失败",
                        history=[{"tool": tool_id, "result": raw_result}]
                    )
                    if generated:  # 技能生成成功
                        _get_logger().info(f"[SkillGenerator] 生成新技能: {generated.get('name')}")
                        user_context.reset_failure(tool_id)  # 重置失败计数
                        self._failure_counts[tool_id] = 0
                except Exception as e:
                    _get_logger().error(f"[SILENT_FAILURE_BLOCKED][SkillGenerator] 技能生成失败: {e}", exc_info=True)
        else:  # 执行成功
            user_context.reset_failure(tool.tool_id)  # 重置失败计数
            if tool.tool_id in self._failure_counts:
                del self._failure_counts[tool.tool_id]

        # 发射工具执行完成事件
        try:
            event_bus.emit("tool:executed", {
                "tool_id": tool_id,
                "params": params,
                "success": raw_result.get("success", False),
                "result": raw_result.get("data"),
                "error_code": raw_result.get("error_code"),
                "duration": duration,
                "timestamp": time.time(),
                "source": source,
                "user_id": user_id
            })
        except Exception as e:
            _get_logger().error(f"[SILENT_FAILURE_BLOCKED][ToolManager] 事件发射失败: {e}", exc_info=True)  # 失败不影响主流程

        # ========== 9. 世界模型记录 ==========
        try:
            if get_world_model is None:
                raise RuntimeError("world_model 不可用")
            wm = get_world_model()  # 获取世界模型
            if wm:  # 世界模型可用
                await wm.record_observation(
                    tool_id=tool_id,
                    params=params,
                    result=raw_result,
                    source=source,
                    duration=duration,
                    context=self._get_current_task_context()
                )
        except Exception as e:
            _get_logger().error(f"[SILENT_FAILURE_BLOCKED] 世界模型记录观察失败: {e}", exc_info=True)  # 失败不影响主流程

        # ========== 10. L5执行记忆记录 ==========
        try:
            await self._record_l5_execution(
                user_id=user_id,
                tool_id=tool_id,
                params=params,
                result=raw_result,
                execution_time_ms=int(duration * 1000),  # 转换为毫秒
                source=source
            )
        except Exception as e:
            _get_logger().error(f"[SILENT_FAILURE_BLOCKED][ToolManager] L5执行记忆记录失败: {e}", exc_info=True)  # 失败不影响主流程

        # ========== 11. 工具反馈过滤 ==========
        # 【2026-04-09 新增】根据工具类型和结果决定反馈级别
        try:
            from core.consciousness.tool_feedback_manager import tool_feedback_manager

            should_add_to_context, formatted_feedback = await tool_feedback_manager.process_tool_result(
                tool_id=tool_id,
                result=raw_result,
                user_id=user_id or "default"
            )

            # 将过滤决策存入结果元数据（供AgentLoop使用）
            raw_result["_feedback_decision"] = {
                "should_add_to_context": should_add_to_context,
                "formatted_content": formatted_feedback,
                "tool_id": tool_id,
                "timestamp": time.time()
            }

            _get_logger().debug(
                f"[ToolManager] 反馈过滤完成: {tool_id}, "
                f"should_add_to_context={should_add_to_context}"
            )

        except Exception as e:
            # 过滤失败不应影响工具执行，记录日志并默认使用完整反馈
            _get_logger().warning(
                f"[SILENT_FAILURE_BLOCKED] 工具反馈过滤失败: {e}, tool_id={tool_id}",
                exc_info=True
            )
            # 回退：允许添加到上下文，使用默认格式化
            raw_result["_feedback_decision"] = {
                "should_add_to_context": True,
                "formatted_content": None,  # AgentLoop将使用 format_feedback_for_ai
                "tool_id": tool_id,
                "timestamp": time.time(),
                "fallback": True
            }

        # 【P1修复】缓存工具执行结果，供DuplicateGuard复用
        try:
            self._cache_dedup_result(_dedup_key, raw_result)
        except Exception as e:
            _get_logger().debug(f"[ToolManager-DuplicateGuard] 缓存结果失败: {e}")

        return raw_result  # 返回执行结果

    async def _record_l5_execution(self, user_id: str, tool_id: str, params: dict,
                            result: dict, execution_time_ms: int,
                            source: str = "user"):
        """
        记录L5执行记忆

        Args:
            user_id: 用户ID
            tool_id: 工具ID
            params: 执行参数
            result: 执行结果
            execution_time_ms: 执行时间（毫秒）
            source: 调用来源
        """
        execution_memory = _get_execution_memory()  # 获取执行记忆管理器
        if not execution_memory:  # 未初始化则跳过
            return

        task_id = None
        session_id = None

        try:
            current_task = task_queue.current_task()  # 获取当前任务
            if current_task:
                task_id = getattr(current_task, "id", None)
                session_id = getattr(current_task, "session_id", None)
        except Exception as e:
            _get_logger().error(f"[SILENT_FAILURE_BLOCKED][ToolManager] 获取任务信息失败: {e}", exc_info=True)

        safe_params = self._sanitize_params_for_audit(params)  # 脱敏参数

        execution_memory.record_from_result(
            user_id=user_id,
            tool_name=tool_id,
            input_params=safe_params,
            result=result,
            execution_time_ms=execution_time_ms,
            task_id=task_id,
            session_id=session_id
        )

        _get_logger().debug(f"[L5执行记忆] 记录 {tool_id} 执行，用户: {user_id}, 耗时: {execution_time_ms}ms")

    def register_tool(self, tool: BaseTool, persist: bool = False):
        """
        注册工具到管理器

        Args:
            tool: 工具实例
            persist: 是否持久化到文件
        """
        with self._rw_lock:  # 加锁保护
            self._tools[tool.tool_id] = tool  # 添加到工具字典
        if persist:  # 需要持久化
            self._save_tool_code_atomic(tool)  # 原子化保存
        _get_logger().info(f"工具热注册成功: {tool.tool_id}")

    def hot_register_tool(self, tool_path: str) -> bool:
        """
        热注册新工具（无需重启系统）

        支持从文件路径动态加载并注册工具到 _tools。
        供插件系统、工具市场等场景统一调用。

        Args:
            tool_path: 工具文件路径（.py 文件）

        Returns:
            bool: 是否注册成功
        """
        import importlib.util
        from pathlib import Path

        try:
            tool_file = Path(tool_path)
            if not tool_file.exists():
                _get_logger().error(f"[ToolManager] 热注册失败: 文件不存在 {tool_path}")
                return False

            module_name = tool_file.stem
            spec = importlib.util.spec_from_file_location(module_name, tool_path)
            if not spec or not spec.loader:
                _get_logger().error(f"[ToolManager] 热注册失败: 无法创建模块规范 {tool_path}")
                return False

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            tool_class = None
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type) and
                    issubclass(attr, BaseTool) and
                    attr != BaseTool):
                    tool_class = attr
                    break

            if not tool_class:
                _get_logger().error(f"[ToolManager] 热注册失败: 未找到BaseTool子类 {tool_path}")
                return False

            tool = tool_class()

            if not hasattr(tool, 'tool_id') or not tool.tool_id:
                _get_logger().error("[ToolManager] 热注册失败: 工具缺少tool_id")
                return False

            self.register_tool(tool, persist=False)
            _get_logger().info(f"[ToolManager] 热注册工具成功: {tool.tool_id} ({tool.name})")
            return True

        except Exception as e:
            _get_logger().error(f"[ToolManager] 热注册失败: {e}", exc_info=True)
            return False

    def _save_tool_code_atomic(self, tool: BaseTool):
        """
        原子保存工具代码（临时文件 + 重命名）

        使用原子写入防止写入过程中断导致文件损坏。

        Args:
            tool: 工具实例
        """
        try:
            gen_dir = Path(__file__).parent.parent / "tools" / "generated"  # 目标目录
            gen_dir.mkdir(exist_ok=True, parents=True)  # 确保目录存在
            source = inspect.getsource(tool.__class__)  # 获取工具类源代码
            header = "# -*- coding: utf-8 -*-\nfrom core.tool.base_tool import BaseTool\n\n"  # 文件头
            final_code = header + source  # 组合最终代码
            final_path = gen_dir / f"{tool.tool_id}.py"  # 目标文件路径

            # 先写入临时文件
            with tempfile.NamedTemporaryFile(
                'w', encoding='utf-8', dir=gen_dir, delete=False, suffix='.tmp'
            ) as tf:
                tf.write(final_code)
                temp_path = tf.name  # 临时文件路径

            # 原子重命名（操作系统保证原子性）
            os.replace(temp_path, final_path)
            _get_logger().info(f"工具代码已原子持久化: {final_path}")
        except Exception as e:
            _get_logger().error(f"[SILENT_FAILURE_BLOCKED] 保存工具代码失败: {e}", exc_info=True)
            raise

    def _sandbox_test(self, code: str, tool_class_name: str) -> tuple:
        """
        在沙箱环境中测试工具代码

        限制 builtins，只允许安全的操作。

        Args:
            code: 工具代码字符串
            tool_class_name: 工具类名

        Returns:
            tuple: (是否成功, 错误信息, 工具实例)
        """
        try:
            # 限制可用的内置函数，只允许安全的操作
            sandbox_globals = {
                "__builtins__": {
                    "True": True, "False": False, "None": None,
                    "str": str, "int": int, "float": float, "bool": bool,
                    "list": list, "dict": dict, "tuple": tuple, "set": set,
                    "len": len, "range": range, "enumerate": enumerate,
                    "zip": zip, "map": map, "filter": filter,
                    "print": lambda *args, **kwargs: None,  # 禁用打印
                }
            }

            sandbox_globals["BaseTool"] = BaseTool  # 注入BaseTool

            compiled = compile(code, '<sandbox>', 'exec')  # 编译代码
            exec(compiled, sandbox_globals)  # 在沙箱中执行

            # 查找工具类
            tool_class = None
            for obj in sandbox_globals.values():
                if (isinstance(obj, type) and
                    issubclass(obj, BaseTool) and
                    obj != BaseTool and
                    obj.__name__ == tool_class_name):  # 类名匹配
                    tool_class = obj
                    break

            if not tool_class:
                return False, "沙箱测试中未找到有效的 BaseTool 子类", None

            instance = tool_class()  # 实例化

            # 检查必要属性
            required_attrs = ['tool_id', 'name', 'description', 'run']
            for attr in required_attrs:
                if not hasattr(instance, attr):
                    return False, f"工具实例缺少必要属性: {attr}", None

            # 检查tool_id有效性
            if not isinstance(instance.tool_id, str) or not instance.tool_id:
                return False, "tool_id 必须是有效的非空字符串", None

            return True, None, instance  # 沙箱测试通过

        except SyntaxError as e:  # 语法错误
            return False, f"沙箱测试语法错误: {e}", None
        except Exception as e:  # 其他异常
            return False, f"沙箱测试异常: {e}", None

    def register_tool_from_code(self, code: str, skip_sandbox: bool = False) -> dict:
        """
        从代码动态注册工具（增强安全版本）

        安全检查流程：
        1. 语法解析 - 确保代码可解析
        2. AST检查 - 只允许导入和类定义
        3. 继承检查 - 必须继承BaseTool
        4. 安全扫描 - 检查危险操作
        5. 沙箱测试 - 在受限环境执行
        6. 工具ID验证 - 格式和唯一性检查
        7. 注册和持久化

        Args:
            code: 工具代码字符串
            skip_sandbox: 是否跳过沙箱测试（危险，仅测试使用）

        Returns:
            dict: 注册结果，包含success/tool_id/warnings等
        """
        warnings = []  # 警告信息列表
        start_time = time.time()  # 计时开始

        # 1. 语法解析
        try:
            tree = ast.parse(code)  # 解析为AST
        except SyntaxError as e:  # 语法错误
            return {
                "success": False,
                "error": f"语法错误: {e}",
                "warnings": warnings
            }
        except Exception as e:
            _get_logger().error(f"[SILENT_FAILURE_BLOCKED] 代码解析异常: {e}", exc_info=True)
            return {
                "success": False,
                "error": f"代码解析失败: {str(e)}",
                "warnings": warnings
            }

        # 2. AST检查 - 只允许特定的节点类型
        allowed_nodes = (ast.Import, ast.ImportFrom, ast.ClassDef, ast.Expr)
        tool_class_name = None

        for node in tree.body:  # 遍历顶层节点
            if not isinstance(node, allowed_nodes):
                return {
                    "success": False,
                    "error": f"禁止顶级代码: {type(node).__name__}，仅允许导入和类定义",
                    "warnings": warnings
                }
            if isinstance(node, ast.ClassDef):  # 类定义
                has_base_tool = False
                for base in node.bases:
                    if isinstance(base, ast.Name) and base.id == "BaseTool":
                        has_base_tool = True
                        tool_class_name = node.name  # 记录类名
                        break
                if not has_base_tool:
                    return {
                        "success": False,
                        "error": f"类 {node.name} 必须继承 BaseTool",
                        "warnings": warnings
                    }

        if not tool_class_name:  # 未找到工具类
            return {
                "success": False,
                "error": "未找到继承 BaseTool 的类定义",
                "warnings": warnings
            }

        # 3. 代码安全扫描
        is_safe, reason = check_code_safety(code)
        if not is_safe:
            return {
                "success": False,
                "error": f"代码包含危险操作: {reason}",
                "warnings": warnings
            }

        # 4. 危险模式检查
        dangerous_patterns = [
            'os.system', 'os.popen', 'os.exec', 'os.spawn',
            'subprocess.call', 'subprocess.run', 'subprocess.Popen',
            'eval(', 'exec(', 'compile(',
            '__import__', 'importlib', 'ctypes', 'sys.modules',
            'open(', 'file(',
            'socket', 'urllib', 'requests',
            'pickle.loads', 'yaml.load',
        ]
        code_lower = code.lower()
        for pattern in dangerous_patterns:
            if pattern.lower() in code_lower:
                return {
                    "success": False,
                    "error": f"代码包含禁止的调用: {pattern}",
                    "warnings": ["检测到潜在危险操作"]
                }

        warnings.append("危险调用检查通过")

        # 5. 沙箱测试
        if not skip_sandbox:
            sandbox_success, sandbox_error, sandbox_instance = self._sandbox_test(
                code, tool_class_name
            )
            if not sandbox_success:
                return {
                    "success": False,
                    "error": f"沙箱测试失败: {sandbox_error}",
                    "warnings": warnings
                }
            warnings.append("沙箱测试通过")
            tool_id = sandbox_instance.tool_id  # 获取工具ID
        else:
            warnings.append("跳过了沙箱测试")
            tool_id = None

        # 6. 正式注册
        try:
            # 安全的内置函数集合
            safe_builtins = {
                'True': True, 'False': False, 'None': None,
                'str': str, 'int': int, 'float': float, 'bool': bool,
                'list': list, 'dict': dict, 'tuple': tuple, 'set': set,
                'len': len, 'range': range, 'enumerate': enumerate,
                'zip': zip, 'map': map, 'filter': filter,
                'sum': sum, 'min': min, 'max': max, 'abs': abs,
                'round': round, 'pow': pow, 'divmod': divmod,
                'isinstance': isinstance, 'issubclass': issubclass,
                'hasattr': hasattr, 'getattr': getattr, 'setattr': setattr,
                'type': type, 'super': super, 'property': property,
                'staticmethod': staticmethod, 'classmethod': classmethod,
                'Exception': Exception, 'BaseException': BaseException,
            }

            exec_globals = {"__builtins__": safe_builtins}
            exec_globals["BaseTool"] = BaseTool  # 注入BaseTool

            exec(code, exec_globals)  # 执行代码

            # 查找工具类
            tool_classes = [
                v for v in exec_globals.values()
                if isinstance(v, type) and issubclass(v, BaseTool) and v != BaseTool
            ]

            if not tool_classes:
                return {
                    "success": False,
                    "error": "未找到有效的 BaseTool 子类",
                    "warnings": warnings
                }

            tool_class = tool_classes[0]

            # 验证工具ID
            tool_id = None
            try:
                temp_instance = tool_class()  # 临时实例化获取ID
                tool_id = temp_instance.tool_id
                if not isinstance(tool_id, str) or not tool_id:  # 无效ID
                    return {
                        "success": False,
                        "error": "tool_id必须是有效的非空字符串",
                        "warnings": warnings
                    }
                import re
                # 工具ID格式：小写字母开头，只含小写字母数字下划线
                if not re.match(r'^[a-z][a-z0-9_]*$', tool_id):
                    return {
                        "success": False,
                        "error": f"tool_id格式非法: {tool_id}，必须为小写字母开头，仅包含小写字母、数字、下划线",
                        "warnings": warnings
                    }
            except Exception as e:
                _get_logger().error(f"[SILENT_FAILURE_BLOCKED] 验证工具ID失败: {e}", exc_info=True)
                return {
                    "success": False,
                    "error": f"验证工具ID失败: {e}",
                    "warnings": warnings
                }

            # 检查ID是否已存在
            if tool_id in self._tools:
                return {
                    "success": False,
                    "error": f"工具ID已存在: {tool_id}",
                    "warnings": warnings
                }

            # 注册工具并持久化
            self.register_tool(temp_instance, persist=True)

            duration = time.time() - start_time
            _get_logger().info(f"[ToolManager] 动态注册工具成功: {tool_id}, 耗时: {duration:.3f}s")

            return {
                "success": True,
                "tool_id": tool_id,
                "warnings": warnings + ["已通过安全沙箱验证"]
            }

        except (NameError, TypeError, AttributeError) as e:
            _get_logger().error(f"[SILENT_FAILURE_BLOCKED] 工具类实例化失败: {e}", exc_info=True)
            return {
                "success": False,
                "error": f"工具类实例化失败: {str(e)}",
                "warnings": warnings
            }
        except Exception as e:
            _get_logger().error(f"[SILENT_FAILURE_BLOCKED] 动态注册工具异常: {e}", exc_info=True)
            return {
                "success": False,
                "error": f"注册异常: {str(e)}",
                "warnings": warnings
            }

    def unregister_tool(self, tool_id: str) -> bool:
        """
        注销工具

        Args:
            tool_id: 工具ID

        Returns:
            bool: 是否成功注销
        """
        with self._rw_lock:  # 加锁保护
            if tool_id in self._tools:  # 工具存在
                del self._tools[tool_id]  # 删除
                _get_logger().info(f"工具已注销: {tool_id}")
                return True
        return False  # 工具不存在

    # ========================================
    # 云端+本地双版本工具管控架构
    # ========================================

    def get_tool_info(self, tool_id: str, user_id: str = None) -> dict:
        """
        获取工具完整信息，包含权限计算

        根据部署模式计算工具的执行权限：
        - local(本地模式): 用户拥有最高权限，所有工具都可执行
        - cloud(云端模式): 平台管控，废弃工具不可执行
        - hybrid(混合模式): 根据具体策略决定

        Args:
            tool_id: 工具ID
            user_id: 用户ID（可选）

        Returns:
            dict: 工具完整信息，包含执行权限
            {
                "id": str,                    # 工具ID
                "name": str,                  # 工具名称
                "description": str,           # 工具描述
                "owner": str,                 # 工具所有者 (system/user/custom/platform)
                "deprecated": bool,           # 是否废弃
                "deprecated_reason": str,     # 废弃原因
                "duplicate_of": str,          # 替代工具ID
                "executable": bool,           # 是否可执行（根据部署模式计算）
                "exec_restriction": str|None, # 执行限制原因（如有）
                "warning": str|None           # 警告信息
            }
        """
        tool = self._tools.get(tool_id)
        if not tool:
            return None

        # 获取部署模式（支持动态配置）
        deploy_mode = _get_config().get_deploy_mode()

        # 基础信息（所有模式都返回）
        base_info = {
            "id": tool_id,
            "name": tool.name,
            "description": getattr(tool, "description", ""),
            "owner": getattr(tool, 'tool_owner', 'system'),
            "deprecated": getattr(tool, 'deprecated', False),
            "deprecated_reason": getattr(tool, 'deprecated_reason', ''),
            "duplicate_of": getattr(tool, 'duplicate_of', ''),
        }

        # 根据部署模式计算执行权限
        if deploy_mode == "local":
            # 本地模式：用户拥有最高权限
            base_info.update({
                "executable": True,  # 哪怕废弃也能执行
                "exec_restriction": None,
                "warning": tool.deprecated and f"⚠️ 此工具已废弃：{tool.deprecated_reason}" or None
            })
        elif deploy_mode == "cloud":
            # 云端模式：平台管控
            executable, restriction = self._check_cloud_execution_permission(tool)
            base_info.update({
                "executable": executable,
                "exec_restriction": restriction,
                "warning": self._get_cloud_warning(tool, restriction)
            })
        elif deploy_mode == "hybrid":
            # 混合模式：用户自定义工具可执行，系统废弃工具受限
            owner = getattr(tool, 'tool_owner', 'system')
            is_deprecated = getattr(tool, 'deprecated', False)

            if owner == "custom" or not is_deprecated:
                base_info.update({
                    "executable": True,
                    "exec_restriction": None,
                    "warning": tool.deprecated and f"⚠️ 此工具已废弃：{tool.deprecated_reason}" or None
                })
            else:
                restriction = self._get_restriction_reason(tool)
                base_info.update({
                    "executable": False,
                    "exec_restriction": restriction,
                    "warning": self._get_cloud_warning(tool, restriction)
                })
        else:
            # 未知模式，使用保守策略
            base_info.update({
                "executable": False,
                "exec_restriction": f"未知的部署模式: {deploy_mode}",
                "warning": "系统配置异常，请联系管理员"
            })

        return base_info

    def _check_cloud_execution_permission(self, tool) -> tuple:
        """
        云端模式下检查工具执行权限

        Args:
            tool: 工具实例

        Returns:
            tuple: (是否可执行, 限制原因)
        """
        owner = getattr(tool, 'tool_owner', 'system')
        is_deprecated = getattr(tool, 'deprecated', False)

        # 用户自定义工具始终可执行
        if owner == "custom":
            return True, None

        # 已废弃工具不可执行
        if is_deprecated:
            reason = self._get_restriction_reason(tool)
            return False, reason

        # 其他工具可执行
        return True, None

    def _get_restriction_reason(self, tool) -> str:
        """
        获取工具执行限制原因

        Args:
            tool: 工具实例

        Returns:
            str: 限制原因说明
        """
        if getattr(tool, 'deprecated', False):
            duplicate_of = getattr(tool, 'duplicate_of', '')
            if duplicate_of:
                return f"此工具已废弃，请使用替代工具: {duplicate_of}"
            return f"此工具已废弃: {tool.deprecated_reason}"

        if not getattr(tool, 'enabled', True):
            return "此工具已被禁用"

        return "当前部署模式下不可执行此工具"

    def _get_cloud_warning(self, tool, restriction: str = None) -> str:
        """
        获取云端模式下的警告信息

        Args:
            tool: 工具实例
            restriction: 限制原因

        Returns:
            str: 警告信息
        """
        warnings = []

        if getattr(tool, 'deprecated', False):
            duplicate_of = getattr(tool, 'duplicate_of', '')
            if duplicate_of:
                warnings.append(f"⚠️ 此工具已废弃，请使用 '{duplicate_of}' 替代")
            else:
                warnings.append(f"⚠️ 此工具已废弃: {tool.deprecated_reason}")

        if restriction:
            warnings.append(f"🚫 {restriction}")

        return " | ".join(warnings) if warnings else None

    def get_tools_by_owner(self, owner: str) -> list[dict]:
        """
        根据所有者获取工具列表

        Args:
            owner: 工具所有者 (system/user/custom/platform)

        Returns:
            List[dict]: 该所有者的工具列表
        """
        with self._rw_lock:
            result = []
            for tool_id, tool in self._tools.items():
                if getattr(tool, 'tool_owner', 'system') == owner:
                    result.append(self.get_tool_info(tool_id))
            return result

    def get_all_tools_with_permission(self, user_id: str = None) -> list[dict]:
        """
        获取所有工具及其权限信息

        Args:
            user_id: 用户ID（可选）

        Returns:
            List[dict]: 所有工具的完整信息（含权限）
        """
        with self._rw_lock:
            return [self.get_tool_info(tool_id, user_id)
                    for tool_id in self._tools]

    def build_tool_awareness_prompt(self) -> str:
        """
        构建工具感知提示词

        Returns:
            str: 格式化的工具列表
        """
        with self._rw_lock:
            tools = self.list_tools()  # 获取工具列表
            return self.build_compact_tool_list(tools)  # 构建提示词


    def _execute_tool_in_process(self, tool, tool_id: str, params: dict,
                                   timeout: int, task_id: str) -> dict:
        """
        执行工具，根据工具类型选择执行模式

        【连接池保护】
        - 记忆工具（MEMORY_TOOLS）：使用线程模式，共享主进程的数据库连接池
        - 其他工具：使用子进程模式，隔离执行，不创建数据库连接

        Args:
            tool: 工具实例
            tool_id: 工具ID
            params: 执行参数
            timeout: 超时时间(秒)
            task_id: 任务ID

        Returns:
            工具执行结果，或包含_error_code的错误字典
        """
        # 【连接池保护】根据工具类型选择执行模式
        if tool_id in self.MEMORY_TOOLS:
            # 记忆工具使用线程模式，需要访问共享的数据库连接池
            _get_logger().debug(f"[ToolManager] {tool_id} 使用线程模式（需要记忆访问）")
            return self._execute_tool_in_thread_mode(tool, tool_id, params, timeout, task_id)
        else:
            # 其他工具使用子进程模式，隔离执行，不创建数据库连接
            _get_logger().debug(f"[ToolManager] {tool_id} 使用子进程模式（隔离执行）")
            return self._execute_tool_in_thread(tool, tool_id, params, timeout, task_id)

    def _execute_tool_in_thread(self, tool, tool_id: str, params: dict,
                                 timeout: int, task_id: str) -> dict:
        """
        在子进程中执行工具，支持真正的超时终止

        【THREAD-001修复】
        使用multiprocessing.Process替代threading.Thread，
        超时后调用terminate()强制终止进程，防止僵尸线程累积。

        【TIMEOUT-001修复】
        - 确保默认30秒超时
        - 防止multiprocessing.Manager阻塞主线程
        - 添加全面的异常处理

        Args:
            tool: 工具实例
            tool_id: 工具ID
            params: 执行参数
            timeout: 超时时间(秒)，默认30秒
            task_id: 任务ID

        Returns:
            工具执行结果，或包含_error_code的错误字典
        """
        # 【TIMEOUT-001】确保合理的超时时间
        # 【关键修复】视觉工具需要更长超时（因为包含截图+AI推理）
        if timeout is None or timeout <= 0:
            timeout = 60 if tool_id in ["visual_understand", "icon_recognize", "screen_ocr"] else 30  # 视觉工具60秒，默认30秒

        # 【关键修复】视觉工具最小超时保护
        if tool_id in ["visual_understand", "icon_recognize", "screen_ocr"] and timeout < 45:
            _get_logger().warning(f"[ToolManager] 视觉工具 {tool_id} 超时时间 {timeout}秒 过短，调整为 60秒")
            timeout = 60

        # 最大超时时间限制，防止资源占用过久
        max_timeout = 300  # 5分钟
        if timeout > max_timeout:
            _get_logger().warning(f"[ToolManager] 工具 {tool_id} 超时时间 {timeout}秒 超过最大限制，调整为 {max_timeout}秒")
            timeout = max_timeout

        print(f"[DEBUG] _execute_tool_in_thread: {tool_id}, params={params}, timeout={timeout}")

        # 获取工具的类信息，用于子进程中重建
        tool_class = tool.__class__
        tool_class_name = tool_class.__name__
        tool_module = tool_class.__module__

        # 【修复】P0-001: 初始化Manager和Queue变量，确保finally块中可以访问
        manager = None
        result_queue = None
        process = None

        # 【TIMEOUT-001】创建结果队列（使用Manager.Queue支持跨进程）
        # 使用超时机制防止Manager启动阻塞主线程
        try:
            from multiprocessing import Manager

            def timeout_handler(signum, frame):
                raise TimeoutError("Manager启动超时")

            # Windows不支持signal.SIGALRM，使用带超时的轮询
            manager_start_time = time.time()
            manager = Manager()  # 创建Manager
            # 快速检查Manager是否响应
            if time.time() - manager_start_time > 5:
                _get_logger().warning(f"[ToolManager] Manager启动较慢: {time.time() - manager_start_time:.2f}秒")

            result_queue = manager.Queue()  # 创建队列
        except TimeoutError as e:
            _get_logger().error(f"[TIMEOUT-001] 创建Manager超时: {e}，回退到线程模式")
            return self._execute_tool_in_thread_fallback(tool, tool_id, params, timeout, task_id)
        except Exception as e:
            _get_logger().error(f"[SILENT_FAILURE_BLOCKED][THREAD-001] 创建Manager失败: {e}，回退到线程模式", exc_info=True)
            return self._execute_tool_in_thread_fallback(tool, tool_id, params, timeout, task_id)

        # 【连接池保护】等待信号量，限制并发进程数
        # 防止子进程创建过多数据库连接导致PostgreSQL连接池耗尽
        semaphore_acquired = False
        try:
            semaphore_acquired = _process_pool._process_semaphore.acquire(timeout=30)
            if not semaphore_acquired:
                _get_logger().warning(f"[连接池保护] 工具 {tool_id} 等待并发槽位超时，当前并发数已达上限")
                return {"_execution_error": True, "error_code": "RESOURCE_BUSY",
                        "message": "系统繁忙，请稍后重试"}
        except Exception as e:
            _get_logger().error(f"[SILENT_FAILURE_BLOCKED][连接池保护] 获取信号量失败: {e}", exc_info=True)
            return {"_execution_error": True, "error_code": "RESOURCE_ERROR",
                    "message": "获取执行资源失败"}

        # 【TIMEOUT-001】创建并启动子进程
        try:
            process = mp.Process(
                target=_tool_process_worker,
                args=(tool_module, tool_class_name, params, result_queue),
                name=f"tool_{tool_id}_{str(task_id)[:8]}"
            )

            # 注册到进程池
            _process_pool.register_process(task_id, process)
        except Exception as e:
            _get_logger().error(f"[SILENT_FAILURE_BLOCKED][TIMEOUT-001] 创建工具进程失败 {tool_id}: {e}", exc_info=True)
            # 【连接池保护】释放信号量
            if semaphore_acquired:
                _process_pool._process_semaphore.release()
            return {"_execution_error": True, "error_code": "PROCESS_CREATION_ERROR",
                    "message": f"创建工具进程失败: {e}"}

        try:
            print(f"[DEBUG] 启动工具进程: {tool_id}")
            process.start()  # 启动进程
            print(f"[DEBUG] 等待工具进程完成: {tool_id}, timeout={timeout}")

            # 等待进程完成，带超时
            process.join(timeout=timeout)

            print(f"[DEBUG] 工具进程结束: {tool_id}, is_alive={process.is_alive()}")

            # 检查是否超时
            if process.is_alive():
                # 【THREAD-001修复】强制终止进程
                _get_logger().error(f"[THREAD-001] 工具 {tool_id} 执行超时（{timeout}秒），强制终止进程")
                _process_pool.terminate_process(task_id)
                return {"_execution_error": True, "error_code": "TOOL_TIMEOUT",
                        "message": f"工具执行超过 {timeout} 秒"}

            # 【TIMEOUT-001】从队列获取结果，添加超时防止永久阻塞
            try:
                # 检查结果队列，带超时防止阻塞
                import queue
                try:
                    # 使用超时等待结果，防止无限阻塞
                    result_data = result_queue.get(timeout=5)
                except queue.Empty:
                    _get_logger().error(f"[TIMEOUT-001] 工具 {tool_id} 结果队列超时")
                    return {"_execution_error": True, "error_code": "QUEUE_TIMEOUT",
                            "message": "获取工具执行结果超时"}

                if result_data.get("_worker_error"):  # 工作进程出错
                    error_msg = result_data.get("error", "未知错误")
                    print(f"[DEBUG] 工具执行异常: {tool_id}, error={error_msg}")
                    return {"_execution_error": True, "error_code": "TOOL_EXECUTION_ERROR",
                            "message": error_msg}

                if "result" in result_data:
                    print(f"[DEBUG] 工具执行成功: {tool_id}")
                    return result_data["result"]  # 返回执行结果

                print(f"[DEBUG] 工具未返回结果: {tool_id}")
                return {"_execution_error": True, "error_code": "NO_RESULT",
                        "message": "工具未返回结果"}

            except Exception as e:
                _get_logger().error(f"[SILENT_FAILURE_BLOCKED][THREAD-001] 获取结果失败: {e}", exc_info=True)
                return {"_execution_error": True, "error_code": "RESULT_ERROR",
                        "message": f"获取执行结果失败: {e}"}

        except Exception as e:
            _get_logger().error(f"[SILENT_FAILURE_BLOCKED][THREAD-001] 执行工具进程失败: {e}", exc_info=True)
            return {"_execution_error": True, "error_code": "EXECUTION_ERROR",
                    "message": f"工具执行失败: {e}"}
        finally:
            # 从进程池注销
            _process_pool.unregister_process(task_id)

            # 【TIMEOUT-001】确保进程已终止
            process_terminated = False
            if process is not None and process.is_alive():
                try:
                    process.terminate()  # 发送终止信号
                    process.join(timeout=1)  # 等待1秒
                    if process.is_alive():
                        process.kill()  # 强制杀死
                        _get_logger().warning(f"[ToolManager] 工具 {tool_id} 进程强制杀死")
                    process_terminated = True
                except Exception as e:
                    _get_logger().error(f"[SILENT_FAILURE_BLOCKED][ToolManager] 进程终止失败: {e}", exc_info=True)  # 记录终止失败

            # 【关键修复】如果子进程被强制终止，清理可能泄漏的资源
            if process_terminated and tool_id in ["visual_understand", "icon_recognize", "screen_ocr", "pixel_capture"]:
                try:
                    from core.resource_coordinator import ResourceType, coordinator
                    # 强制释放截图资源
                    coordinator.force_release_resource(ResourceType.SCREENSHOT, f"子进程被终止: {tool_id}")
                    _get_logger().info(f"[ToolManager] 已强制释放截图资源: {tool_id}")
                except Exception as e:
                    _get_logger().error(f"[ToolManager] 清理资源失败: {e}")

            # 【修复】P0-001: 关闭Manager资源，防止资源泄漏
            if manager is not None:
                try:
                    manager.shutdown()  # 关闭Manager
                except Exception as e:
                    _get_logger().error(f"[SILENT_FAILURE_BLOCKED][ToolManager] Manager shutdown失败: {e}", exc_info=True)  # 失败不影响主流程

            # 【连接池保护】释放信号量，允许新的子进程创建
            if semaphore_acquired:
                try:
                    _process_pool._process_semaphore.release()
                except Exception as e:
                    _get_logger().error(f"[SILENT_FAILURE_BLOCKED][连接池保护] 释放信号量失败: {e}", exc_info=True)

    def _execute_tool_in_thread_mode(self, tool, tool_id: str, params: dict,
                                      timeout: int, task_id: str) -> dict:
        """
        在线程中执行工具（用于需要访问记忆的工具）

        【连接池保护】
        记忆工具（如 memory_add, launch_app 等）需要访问 PostgreSQL，
        使用线程模式共享主进程的数据库连接池，避免子进程创建独立连接池。

        Args:
            tool: 工具实例
            tool_id: 工具ID
            params: 执行参数
            timeout: 超时时间(秒)
            task_id: 任务ID

        Returns:
            工具执行结果或错误字典
        """
        import threading

        # 确保超时时间有效
        if timeout is None or timeout <= 0:
            timeout = 30

        _get_logger().debug(f"[ToolManager] 线程模式执行: {tool_id}, timeout={timeout}")

        result_container = {}
        exception_container = {}
        is_completed = threading.Event()

        def tool_runner():
            """工具执行线程"""
            try:
                result = tool.run(**params)
                result_container['result'] = result
            except Exception as e:
                exception_container['error'] = str(e)
                _get_logger().error(f"[SILENT_FAILURE_BLOCKED][ToolManager] 工具 {tool_id} 线程模式执行异常: {e}", exc_info=True)
            finally:
                is_completed.set()

        thread = threading.Thread(
            target=tool_runner,
            name=f"tool_mem_{tool_id}_{str(task_id)[:8]}",
            daemon=True
        )

        try:
            thread.start()
            completed = is_completed.wait(timeout=timeout)

            if not completed or thread.is_alive():
                _get_logger().error(f"[ToolManager] 记忆工具 {tool_id} 执行超时（{timeout}秒）")
                try:
                    if hasattr(tool, 'interrupt'):
                        tool.interrupt()
                except Exception as e:
                    _get_logger().error(f"[SILENT_FAILURE_BLOCKED][ToolManager] 中断工具 {tool_id} 失败: {e}", exc_info=True)
                return {"_execution_error": True, "error_code": "TOOL_TIMEOUT",
                        "message": f"工具执行超过 {timeout} 秒"}

            if 'error' in exception_container:
                return {"_execution_error": True, "error_code": "TOOL_EXECUTION_ERROR",
                        "message": exception_container['error']}

            if 'result' in result_container:
                return result_container['result']

            return {"_execution_error": True, "error_code": "NO_RESULT",
                    "message": "工具未返回结果"}

        except Exception as e:
            _get_logger().error(f"[SILENT_FAILURE_BLOCKED][ToolManager] 线程模式执行失败: {e}", exc_info=True)
            return {"_execution_error": True, "error_code": "THREAD_EXECUTION_ERROR",
                    "message": f"线程执行失败: {e}"}

    def _execute_tool_in_thread_fallback(self, tool, tool_id: str, params: dict,
                                          timeout: int, task_id: str) -> dict:
        """
        线程模式回退（当multiprocessing失败时使用）

        【THREAD-001】不推荐，仅作为紧急回退
        线程无法真正终止，存在僵尸线程风险。

        【TIMEOUT-001修复】
        - 确保超时时间有效
        - 增强异常处理
        - 防止线程泄漏

        Args:
            tool: 工具实例
            tool_id: 工具ID
            params: 执行参数
            timeout: 超时时间(秒)
            task_id: 任务ID

        Returns:
            工具执行结果或错误字典
        """
        import threading

        # 确保超时时间有效
        if timeout is None or timeout <= 0:
            timeout = 30

        print(f"[DEBUG] _execute_tool_in_thread_fallback: {tool_id}, timeout={timeout}")

        result_container = {}  # 结果容器
        exception_container = {}  # 异常容器
        is_completed = threading.Event()  # 完成事件

        def tool_runner():
            """工具执行线程"""
            try:
                result = tool.run(**params)  # 执行工具
                result_container['result'] = result  # 存储结果
            except Exception as e:
                exception_container['error'] = str(e)  # 存储异常
                _get_logger().error(f"[SILENT_FAILURE_BLOCKED] 工具 {tool_id} 回退模式执行异常: {e}", exc_info=True)
            finally:
                is_completed.set()  # 标记完成

        thread = threading.Thread(
            target=tool_runner,
            name=f"tool_{tool_id}_{str(task_id)[:8]}",
            daemon=True  # 设置为守护线程，防止主线程退出时阻塞
        )

        try:
            thread.start()  # 启动线程
            # 使用Event等待，支持更早的退出检测
            completed = is_completed.wait(timeout=timeout)

            if not completed or thread.is_alive():  # 超时
                _get_logger().error(f"[TIMEOUT-001] 工具 {tool_id} 执行超时（{timeout}秒）[回退模式]")
                # 尝试中断工具执行
                try:
                    if hasattr(tool, 'interrupt'):
                        tool.interrupt()  # 调用工具的中断方法
                except Exception as e:
                    _get_logger().error(f"[SILENT_FAILURE_BLOCKED] 中断工具 {tool_id} 失败: {e}", exc_info=True)
                return {"_execution_error": True, "error_code": "TOOL_TIMEOUT",
                        "message": f"工具执行超过 {timeout} 秒"}

            if 'error' in exception_container:  # 执行异常
                return {"_execution_error": True, "error_code": "TOOL_EXECUTION_ERROR",
                        "message": exception_container['error']}

            if 'result' in result_container:
                return result_container['result']  # 返回结果
            else:
                return {"_execution_error": True, "error_code": "NO_RESULT",
                        "message": "工具未返回结果"}

        except Exception as e:
            _get_logger().error(f"[SILENT_FAILURE_BLOCKED][TIMEOUT-001] 执行工具线程失败: {e}", exc_info=True)
            return {"_execution_error": True, "error_code": "EXECUTION_ERROR",
                    "message": f"工具执行失败: {e}"}

    # ==================== 用户隔离的审计日志接口 ====================

    def get_audit_log(self, user_id: str = None, limit: int = 100) -> list[dict]:
        """
        获取审计日志

        Args:
            user_id: 用户ID（为None则返回全局审计日志）
            limit: 返回数量

        Returns:
            List[dict]: 审计日志条目列表
        """
        if user_id:
            context = ToolContextFactory.get_context(user_id)
            return context.get_audit_log(limit)
        return self._audit_log[-limit:]  # 返回全局日志

    def clear_audit_log(self, user_id: str = None):
        """
        清空审计日志

        Args:
            user_id: 用户ID（为None则清空全局审计日志）
        """
        if user_id:
            context = ToolContextFactory.get_context(user_id)
            context.clear_audit_log()
        else:
            self._audit_log.clear()
        _get_logger().info(f"[ToolManager] 审计日志已清空 (user={user_id})")

    def get_user_execution_stats(self, user_id: str) -> dict[str, Any]:
        """
        获取用户执行统计

        Args:
            user_id: 用户ID

        Returns:
            Dict[str, Any]: 执行统计信息
        """
        context = ToolContextFactory.get_context(user_id)
        return context.get_stats()

    def get_global_execution_stats(self) -> dict[str, Any]:
        """获取全局执行统计"""
        return ToolContextFactory.get_global_stats()

    # ==================== 分层交互支持方法（游戏化）====================

    def get_tool_categories(self, use_functional: bool = True) -> dict:
        """
        返回工具分类字典

        Args:
            use_functional: True使用8功能分类，False使用12游戏化分类

        Returns:
            dict: 分类信息字典
        """
        if use_functional:
            # 【修复队8】使用8个功能分类
            result = {}
            for cat_name, cat_info in TOOL_CATEGORIES.items():
                tool_ids = cat_info.get("tools", [])  # 分类中的工具ID
                tools_in_category = []
                with self._rw_lock:
                    for tid in tool_ids:
                        if tid in self._tools:  # 工具存在
                            tools_in_category.append(tid)

                result[cat_name] = {
                    "description": cat_info.get("description", ""),
                    "icon": cat_name.split()[0],  # 提取emoji图标
                    "tools": tools_in_category,
                    "count": len(tools_in_category)
                }
            return result
        else:
            # 使用游戏化12分类（向后兼容）
            tools_info = []
            with self._rw_lock:
                for tid, tool in self._tools.items():
                    tools_info.append({
                        "id": tid,
                        "name": tool.name,
                        "description": getattr(tool, "description", "")
                    })

            categorized = tool_categories.categorize_tools(tools_info)

            result = {}
            all_categories = tool_categories.get_all_categories()

            for category_name, tool_ids in categorized.items():
                meta = all_categories.get(category_name, {})
                result[category_name] = {
                    "description": meta.get("description", ""),
                    "icon": meta.get("icon", "🔧"),
                    "unlock_level": meta.get("unlock_level", 1),
                    "xp_bonus": meta.get("xp_bonus", 0),
                    "color": meta.get("color", "#808080"),
                    "tools": tool_ids
                }

            return result

    def get_tools_by_category(self, category: str, include_metadata: bool = False) -> list:
        """
        返回指定分类下的工具列表
        支持8功能分类和12游戏化分类

        Args:
            category: 分类名称
            include_metadata: 是否包含游戏化元数据

        Returns:
            list: 工具信息列表
        """
        # 先尝试8功能分类
        if category in TOOL_CATEGORIES:
            tool_ids = TOOL_CATEGORIES[category].get("tools", [])
            result = []
            with self._rw_lock:
                for tid in tool_ids:
                    if tid not in self._tools:
                        continue

                    tool = self._tools[tid]
                    tool_info = {
                        "id": tid,
                        "name": tool.name,
                        "description": getattr(tool, "description", "")
                    }
                    result.append(tool_info)
            return result

        # 回退到游戏化分类
        categories = self.get_tool_categories(use_functional=False)
        category_data = categories.get(category, {})
        tool_ids = category_data.get("tools", [])

        result = []
        with self._rw_lock:
            for tid in tool_ids:
                if tid not in self._tools:
                    continue

                tool = self._tools[tid]
                tool_info = {
                    "id": tid,
                    "name": tool.name
                }

                if include_metadata:
                    full_info = tool_categories.build_tool_info(
                        tool_id=tid,
                        tool_name=tool.name,
                        tool_description=getattr(tool, "description", ""),
                        input_schema=tool.input_schema,
                        output_schema=getattr(tool, 'output_schema', {}),
                        timeout=getattr(tool, 'timeout', 30)
                    )
                    tool_info.update({
                        "description": getattr(tool, "description", ""),
                        "xp_value": full_info.xp_value,
                        "unlock_level": full_info.unlock_level,
                        "rarity": full_info.rarity,
                        "category": full_info.category,
                        "icon": tool_categories.get_category_meta(
                            tool_categories.get_category_by_name(full_info.category)
                        ).icon if tool_categories.get_category_by_name(full_info.category) else "🔧"
                    })

                result.append(tool_info)

        return result

    def get_tool_category(self, tool_id: str) -> str:
        """
        获取工具所属分类（8功能分类）

        Args:
            tool_id: 工具ID

        Returns:
            str: 分类名称，未找到返回"其他"
        """
        for cat_name, cat_info in TOOL_CATEGORIES.items():
            if tool_id in cat_info.get("tools", []):
                return cat_name
        return "其他"

    def get_tools_by_category_v2(self, category: str = None) -> dict:
        """
        按分类获取工具（新版8分类）

        Args:
            category: 分类名，None则返回所有分类

        Returns:
            Dict[分类名, List[工具]]
        """
        if category:
            cat_info = TOOL_CATEGORIES.get(category, {})
            tool_ids = cat_info.get("tools", [])
            tools_list = []
            with self._rw_lock:
                for tid in tool_ids:
                    if tid in self._tools:
                        tool = self._tools[tid]
                        tools_list.append({
                            "id": tid,
                            "name": tool.name,
                            "description": getattr(tool, "description", "")
                        })
            return {category: tools_list}

        # 返回所有分类
        result = {}
        for cat_name, cat_info in TOOL_CATEGORIES.items():
            tool_ids = cat_info.get("tools", [])
            tools_list = []
            with self._rw_lock:
                for tid in tool_ids:
                    if tid in self._tools:
                        tool = self._tools[tid]
                        tools_list.append({
                            "id": tid,
                            "name": tool.name,
                            "description": getattr(tool, "description", "")
                        })
            result[cat_name] = tools_list
        return result

    def get_tools_by_ai_category(self, category: str) -> list[BaseTool]:
        """
        按AI层分类获取工具

        Args:
            category: 分类名称（如"任务管理"、"文件操作"等）

        Returns:
            List[BaseTool]: 该分类下的工具实例列表

        支持的分类：
        - 任务管理: 创建、列出、暂停、恢复任务
        - 文件操作: 文件读写管理
        - 系统控制: 系统信息和进程控制
        - 应用操作: 应用启动和窗口管理
        - 输入控制: 键盘鼠标操作
        - 屏幕识别: 截图、OCR、元素定位
        - 网络通信: 网页操作和网络请求
        - 记忆管理: 记忆存储和检索
        - 数据处理: 剪贴板、数据导出
        - 通信通知: 通知和VPN
        - 代码生成: 代码生成工具
        """
        tool_ids = TOOL_CATEGORIES_AI.get(category, [])
        result = []
        with self._rw_lock:
            for tid in tool_ids:
                if tid in self._tools:
                    result.append(self._tools[tid])
        return result

    def get_ai_category_list(self) -> dict[str, list[dict]]:
        """
        获取AI层分类的工具列表（仅ID和名称）

        Returns:
            {
                "任务管理": [{"id": "...", "name": "..."}, ...],
                "文件操作": [...],
                ...
            }
        """
        result = {}
        with self._rw_lock:
            for category, tool_ids in TOOL_CATEGORIES_AI.items():
                tools = []
                for tid in tool_ids:
                    if tid in self._tools:
                        tool = self._tools[tid]
                        tools.append({
                            "id": tid,
                            "name": tool.name,
                            "description": getattr(tool, "description", "")
                        })
                if tools:
                    result[category] = tools
        return result

    def build_categorized_tool_list_for_ai(self) -> str:
        """
        为AI生成按分类组织的工具清单

        Returns:
            格式化的工具列表字符串，按分类组织
        """
        lines = ["【可用工具清单 - 按分类】", ""]

        categorized = self.get_ai_category_list()
        total_tools = sum(len(tools) for tools in categorized.values())

        lines.append(f"当前共 {total_tools} 个工具，分 {len(categorized)} 类：\n")

        for category, tools in categorized.items():
            lines.append(f"\n📁 **{category}** ({len(tools)}个)")
            for tool in tools:
                lines.append(f"  🔧 `{tool['id']}` - {tool['name']}")
                lines.append(f"     {tool['description'][:50]}...")

        # 添加功能边界说明
        lines.append("\n\n【功能使用边界】")
        lines.append("✅ AI直接用: create_task, TOOL_CALL调用")
        lines.append("✅ 用户界面用: 监控面板、世界模型训练")
        lines.append("⚠️ 共用: 任务暂停/恢复、查看任务")

        return "\n".join(lines)

    def get_tool_detail(self, tool_id: str) -> dict:
        """
        返回单个工具的完整信息，支持游戏化展示

        Args:
            tool_id: 工具ID

        Returns:
            dict: 工具详细信息，包含游戏化元数据
        """
        tool = self.get_tool(tool_id)
        if not tool:
            return None

        with self._rw_lock:
            tool_info = tool_categories.build_tool_info(
                tool_id=tool.tool_id,
                tool_name=tool.name,
                tool_description=getattr(tool, "description", ""),
                input_schema=tool.input_schema,
                output_schema=getattr(tool, 'output_schema', {}),
                timeout=getattr(tool, 'timeout', 30)
            )

            category_enum = tool_categories.get_category_by_name(tool_info.category)
            category_meta = tool_categories.get_category_meta(category_enum) if category_enum else None

            rarity_config = tool_categories.TOOL_RARITY_CONFIG.get(
                tool_info.rarity,
                tool_categories.TOOL_RARITY_CONFIG["common"]
            )

            return {
                "id": tool.tool_id,
                "name": tool.name,
                "description": getattr(tool, "description", ""),
                "parameters": tool_info.parameters,
                "required": tool_info.required,
                "example": tool_info.example,
                "category": tool_info.category,
                "xp_value": tool_info.xp_value,
                "unlock_level": tool_info.unlock_level,
                "rarity": tool_info.rarity,
                "icon": category_meta.icon if category_meta else "🔧",
                "color": rarity_config.get("color", "#9E9E9E")
            }

    def get_category_progress(self, user_level: int = 1) -> dict:
        """
        获取分类解锁进度（游戏化）

        Args:
            user_level: 用户当前等级

        Returns:
            dict: 解锁进度信息
        """
        return tool_categories.get_category_progress(user_level)

    def search_tools(self, query: str, include_metadata: bool = False) -> list:
        """
        搜索工具

        Args:
            query: 搜索关键词
            include_metadata: 是否包含完整元数据

        Returns:
            list: 匹配的工具列表
        """
        tools_info = []
        with self._rw_lock:
            for tid, tool in self._tools.items():
                tools_info.append({
                    "id": tid,
                    "name": tool.name,
                    "description": getattr(tool, "description", "")
                })

        # 构建工具信息对象
        tool_info_objects = [
            tool_categories.build_tool_info(
                t["id"], t["name"], t["description"], {}
            ) for t in tools_info
        ]

        # 执行搜索
        results = tool_categories.search_tools(tool_info_objects, query)

        if not include_metadata:
            return [{"id": r.id, "name": r.name} for r in results]

        return [
            {
                "id": r.id,
                "name": r.name,
                "description": getattr(r, "description", ""),
                "category": r.category,
                "xp_value": r.xp_value,
                "rarity": r.rarity
            }
            for r in results
        ]

    # ========================================
    # 语义搜索工具方法
    # ========================================

    async def search_tools_by_semantic(self, query: str, top_k: int = 5, user_id: str = "default") -> list[dict]:
        """
        【新增】语义搜索工具

        利用向量内存进行语义相似度搜索，根据查询意图找到最相关的工具。

        例如：
        - query="打开程序" → 返回 launch_app, process_start...
        - query="搜索文件" → 返回 file_search, find_screen_element...
        - query="输入文字" → 返回 keyboard_input...

        Args:
            query: 查询语句，描述需要执行的操作
            top_k: 返回最相似的top_k个工具，默认5个
            user_id: 用户ID，用于隔离向量存储，默认"default"

        Returns:
            List[dict]: 工具信息列表，每个工具包含完整信息
            每个结果包含：id, name, description, parameters, similarity
        """
        try:
            from core.memory.memory_service import get_memory_service

            ms = await get_memory_service()

            # 1. 获取所有工具
            all_tools = self.list_tools()

            if not all_tools:
                _get_logger().warning("[ToolManager] 语义搜索: 没有可用的工具")
                return []

            # 2. 将工具描述存入向量库（使用knowledge集合）
            tool_texts = []
            tool_metadatas = []

            for tool in all_tools:
                # 构建语义描述：包含ID、名称、描述和参数信息
                desc_parts = [f"{tool['id']}: {tool['name']} - {tool['description']}"]

                # 参数也加入描述，增强语义
                params = tool.get('parameters', '')
                if params and params != "无参数":
                    # 提取参数名和描述，限制长度
                    param_text = params.replace('\n', ' ').replace('    - ', '')[:200]
                    desc_parts.append(f"参数: {param_text}")

                full_desc = ' '.join(desc_parts)
                tool_texts.append(full_desc)
                tool_metadatas.append({
                    "tool_id": tool['id'],
                    "tool_name": tool['name'],
                    "tool_data": tool  # 存储完整工具信息
                })

            # 批量存储到向量库（使用临时集合名称 "tool_index"）
            collection_name = "tool_index"
            # 先清除旧的工具索引（避免重复）
            try:
                await ms.vector_store.delete_collection(collection_name)
            except Exception as e:
                _get_logger().warning(f"[ToolManager] 清理旧工具索引失败（可能集合不存在）: {e}")

            # 添加新的工具描述到向量库
            await ms.vector_store.add_batch(
                collection=collection_name,
                texts=tool_texts,
                metadatas=tool_metadatas
            )

            # 3. 执行语义检索
            search_results = await ms.vector_store.search(
                collection=collection_name,
                query=query,
                limit=top_k
            )

            # 4. 解析结果，返回工具信息
            results = []
            for result in search_results:
                metadata = result.metadata or {}
                tool_data = metadata.get("tool_data", {})

                if tool_data:
                    results.append({
                        "id": tool_data.get("id", ""),
                        "name": tool_data.get("name", ""),
                        "description": tool_data.get("description", ""),
                        "parameters": tool_data.get("parameters", ""),
                        "returns": tool_data.get("returns", {}),
                        "similarity": round(1.0 - (result.distance or 0.0), 4)
                    })

            _get_logger().info(f"[ToolManager] 语义搜索 '{query}' 返回 {len(results)} 个工具")
            return results

        except ImportError as e:
            _get_logger().error(f"[SILENT_FAILURE_BLOCKED][ToolManager] 向量内存模块导入失败: {e}", exc_info=True)
            # 降级到普通关键词搜索
            return self.search_tools(query, include_metadata=True)[:top_k]
        except Exception as e:
            _get_logger().error(f"[SILENT_FAILURE_BLOCKED][ToolManager] 语义搜索失败: {e}", exc_info=True)
            # 降级到普通关键词搜索
            return self.search_tools(query, include_metadata=True)[:top_k]

    async def get_tools_by_semantic_category(self, category: str, top_k: int = 5, user_id: str = "default") -> list[dict]:
        """
        根据功能类别语义搜索工具

        使用语义搜索获取特定类别的工具，支持的类别包括：
        - "system": 系统控制相关工具
        - "file": 文件操作相关工具
        - "ui": UI交互相关工具（鼠标、键盘、窗口）
        - "web": 网络通信相关工具
        - "memory": 记忆管理相关工具
        - "app": 应用操作相关工具
        - "search": 搜索相关工具
        - "input": 输入控制相关工具

        Args:
            category: 功能类别
            top_k: 返回结果数量
            user_id: 用户ID

        Returns:
            List[dict]: 工具信息列表
        """
        # 类别到语义查询的映射
        category_queries = {
            "system": "system control operation process info",
            "file": "file folder directory read write manage",
            "ui": "UI window click mouse keyboard screen element",
            "web": "web browser url http search fetch",
            "memory": "memory recall remember store knowledge",
            "app": "application launch start program open",
            "search": "search find query lookup locate",
            "input": "input type keyboard text enter write",
            "screen": "screenshot capture screen ocr recognize",
            "task": "task schedule create reminder timer cron interval periodic daily hourly automation longtask longterm pausable subagent delegate"
        }

        # 获取对应类别的语义查询
        query = category_queries.get(category.lower(), f"{category} operation tool")

        return await self.search_tools_by_semantic(query=query, top_k=top_k, user_id=user_id)

    async def find_tool_for_intent(self, intent: str, user_id: str = "default") -> dict | None:
        """
        根据用户意图找到最合适的工具

        这是语义搜索的便捷封装，返回最匹配的一个工具。

        Args:
            intent: 用户意图描述，如"我想截屏"、"帮我打开计算器"
            user_id: 用户ID

        Returns:
            Optional[dict]: 最匹配的工具信息，如果没有找到返回None
        """
        results = await self.search_tools_by_semantic(query=intent, top_k=1, user_id=user_id)

        if results:
            best_match = results[0]
            # 如果相似度太低，返回None
            if best_match.get("similarity", 0) < 0.3:
                _get_logger().warning(f"[ToolManager] 意图匹配置信度太低: {best_match.get('similarity')}")
                return None
            return best_match

        return None

    def register_generated_skill(self, skill_code: str, skill_name: str):
        """
        注册生成的技能

        Args:
            skill_code: 技能代码
            skill_name: 技能名称

        Returns:
            bool: 是否注册成功
        """
        try:
            from ..safety.ast_security_checker import check_code_safety
            is_safe, reason = check_code_safety(skill_code)
            if not is_safe:
                _get_logger().warning(f"[SkillGenerator] 技能安全检查失败: {reason}")
                return False

            exec(skill_code, {"BaseTool": BaseTool, "tool_manager": self})
            _get_logger().info(f"[SkillGenerator] 技能 {skill_name} 注册成功")
            return True
        except Exception as e:
            _get_logger().error(f"[SILENT_FAILURE_BLOCKED][SkillGenerator] 技能注册失败: {e}", exc_info=True)
            return False



# ========================================
# 全局实例 - 单例模式
# ========================================
tool_manager = ToolManager()


# ========================================
# 便捷函数 - 简化调用
# ========================================
def get_tool_manager() -> ToolManager:
    """获取工具管理器实例"""
    return tool_manager


def get_mcp_status() -> dict[str, Any]:
    """
    获取 MCP 状态（模块级便捷函数）

    供 api/cloud_api.py 等模块使用。
    """
    return tool_manager.get_mcp_status()


def get_tool_context(user_id: str) -> ToolExecutionContext:
    """
    获取用户工具执行上下文

    Args:
        user_id: 用户ID

    Returns:
        ToolExecutionContext: 用户执行上下文
    """
    return ToolContextFactory.get_context(user_id)


def remove_tool_context(user_id: str):
    """
    移除用户工具执行上下文（用户登出时调用）

    Args:
        user_id: 用户ID
    """
    ToolContextFactory.remove_context(user_id)


async def call_tool_for_user(user_id: str, tool_id: str, params: dict,
                       source: str = "user") -> dict:
    """
    为指定用户调用工具

    Args:
        user_id: 用户ID
        tool_id: 工具ID
        params: 工具参数
        source: 调用来源

    Returns:
        dict: 工具执行结果
    """
    return await tool_manager.call_tool(tool_id, params, source, user_id)


async def safe_call_tool(tool_id: str, params: dict = None, timeout: int = 30) -> dict:
    """
    安全调用工具（带超时保护）

    【TIMEOUT-001修复】
    供 super_tools.py 等内部模块使用，确保所有工具调用都有超时保护，
    防止因直接调用 tool.run() 导致的阻塞问题。

    Args:
        tool_id: 工具ID
        params: 工具参数（可选，默认空字典）
        timeout: 超时时间（秒，默认30秒）

    Returns:
        dict: 工具执行结果字典，包含 success 字段

    示例:
        result = await safe_call_tool("screenshot", {}, timeout=10)
        if result.get("success"):
            data = result.get("data")
    """
    if params is None:
        params = {}

    try:
        return await tool_manager.execute_tool(
            tool_id=tool_id,
            params=params,
            timeout=timeout,
            source="internal"
        )
    except Exception as e:
        _get_logger().error(f"[SILENT_FAILURE_BLOCKED][safe_call_tool] 调用工具 {tool_id} 异常: {e}", exc_info=True)
        from core.utils.error_codes import TOOL_EXECUTION_ERROR, format_error
        return format_error(TOOL_EXECUTION_ERROR, detail=f"工具调用异常: {str(e)}")


# ========================================
# 应用退出时清理资源
# ========================================
import atexit

atexit.register(tool_manager.shutdown)  # 注册退出清理函数


# =============================================================================
# 文件总结性注释
# =============================================================================
#
# ============================================================================
# 文件角色说明
# ============================================================================
#
# 【文件角色】
# tool_manager.py 是 SiliconBase V5 系统的核心组件之一，扮演"工具中枢"的角色。
# 它是整个系统与外部工具交互的唯一入口，负责工具的生命周期管理、安全执行、
# 权限控制和执行追踪。
#
# 【核心职责】
# 1. 工具注册与管理：从 tools/ 目录自动加载工具类，维护工具实例字典
# 2. 工具执行调度：通过子进程隔离执行工具，支持超时强制终止
# 3. 安全控制：权限检查、高危操作确认、代码安全扫描
# 4. 用户隔离：按用户隔离执行上下文（审计日志、失败计数、执行统计）
# 5. 动态注册：支持从代码字符串动态注册工具（带安全沙箱验证）
# 6. 分类管理：8功能分类 + 12游戏化分类，支持AI选工具
# 7. 执行记忆：集成L5执行记忆，自动记录工具调用历史
# 8. 事件发布：通过事件总线发布工具执行事件，供其他组件订阅
#
# ============================================================================
# 关联文件
# ============================================================================
#
# 【上游依赖（调用本文件）】
# - api_handlers.py: API处理器，通过execute_tool/call_tool调用工具
# - super_tools.py: 超级工具，使用safe_call_tool安全调用
# - reflection.py: 反思模块，调用工具进行验证
#
# 【下游依赖（本文件调用）】
# - core/base_tool.py: BaseTool基类，所有工具的父类
# - core/interfaces.py: ToolResult接口定义
# - core/error_codes.py: 错误码定义和格式化
# - core/policy.py: 权限策略检查
# - core/task_queue.py: 任务队列，获取当前任务上下文
# - core/event_bus.py: 事件总线，发布执行事件
# - core/world_model.py: 世界模型，记录执行观察
# - core/execution_memory.py: L5执行记忆管理
# - core/ast_security_checker.py: AST代码安全扫描
# - core/tool_categories.py: 工具分类管理
# - tools/*.py: 具体工具实现
#
# 【配置文件】
# - config.yaml: 工具白名单、超时设置、高危工具列表
#
# ============================================================================
# 达到的效果
# ============================================================================
#
# 【安全性】
# 1. 权限控制：基于source的检查，限制AI/用户的工具访问权限
# 2. 高危确认：关键操作（删除文件、终止进程）需要用户显式确认
# 3. 保护路径：禁止操作系统关键目录（Windows、Program Files等）
# 4. 沙箱验证：动态注册工具时，在受限环境验证代码安全性
# 5. 参数脱敏：审计日志中自动隐藏密码、token等敏感信息
#
# 【可靠性】
# 1. 超时保护：所有工具执行都有超时限制，防止无限阻塞
# 2. 进程隔离：使用multiprocessing隔离执行，超时强制终止
# 3. 错误处理：统一的错误码和错误消息格式
# 4. 失败追踪：记录工具失败次数，超过阈值自动生成修复技能
#
# 【可扩展性】
# 1. 动态注册：支持运行时从代码注册新工具
# 2. 热更新：支持重新加载工具代码
# 3. 分类管理：灵活的工具分类体系，便于前端展示
# 4. 事件驱动：通过事件总线解耦与其他组件的交互
#
# 【可追溯性】
# 1. 审计日志：记录每次工具调用的参数、结果、耗时
# 2. 执行记忆：L5级别长期记忆，支持经验复用
# 3. 世界模型：记录执行观察，支持反思学习
# 4. 用户隔离：每个用户有独立的执行历史和统计
#
# 【性能】
# 1. 线程池：类级别共享线程池，避免频繁创建销毁
# 2. 延迟导入：解决循环依赖，按需初始化
# 3. 缓存机制：工具实例缓存，配置对象缓存
# 4. 进程池管理：自动清理僵尸进程，防止资源泄漏
#
# ============================================================================
# 重要修复记录
# ============================================================================
#
# 【THREAD-001修复】2026-02-26
# - 问题：线程模式下工具超时无法真正终止，导致僵尸线程累积
# - 方案：使用multiprocessing.Process替代threading.Thread
# - 效果：超时后可强制terminate()终止进程
#
# 【TIMEOUT-001修复】2026-02-26
# - 问题：multiprocessing.Manager启动可能阻塞主线程
# - 方案：添加Manager启动超时检测，失败时回退到线程模式
# - 效果：提高系统健壮性，避免卡死
#
# 【用户隔离重构】2026-02-26
# - 问题：审计日志、失败计数等状态全局共享，多用户冲突
# - 方案：引入ToolExecutionContext和ToolContextFactory
# - 效果：每个用户有独立的执行上下文
#
# ============================================================================
# 使用建议
# ============================================================================
#
# 【内部模块调用】
# 推荐使用 safe_call_tool() 函数，它提供统一的超时保护：
#     result = safe_call_tool("screenshot", {"region": "full"}, timeout=10)
#
# 【API层调用】
# 使用 tool_manager.call_tool() 或 tool_manager.execute_tool()：
#     result = tool_manager.call_tool("file_read", {"path": "test.txt"}, user_id="user_001")
#
# 【动态注册工具】
# 使用 register_tool_from_code()，自动进行安全验证：
#     result = tool_manager.register_tool_from_code(code_string)
#
# ============================================================================
# 作者：SiliconBase Team
# 最后更新：2026-02-26
# 版本：V6.2
# ============================================================================
