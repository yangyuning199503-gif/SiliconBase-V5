#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""  # 多行文档字符串开始标记
结构化日志 - 单例，输出 JSON 格式  # 模块功能概述：结构化日志系统
2026-02-21 修复：升级为结构化日志，包含 trace_id、session_id 等  # 版本更新说明
"""  # 多行文档字符串结束标记
import json  # 导入JSON模块：用于结构化日志序列化
import logging  # 导入日志模块：Python标准日志库
import os  # 导入操作系统模块：用于目录创建
import sys  # 导入系统模块：用于标准输出流
import threading  # 导入线程模块：用于线程锁和线程本地存储
import traceback  # 导入追踪模块：用于异常堆栈格式化
from datetime import datetime  # 从datetime导入日期时间类：用于时间戳
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler  # 导入日志轮转处理器
from pathlib import Path  # 从pathlib导入路径类：用于日志文件路径处理


def setup_logging(log_dir: str = "logs") -> None:
    """
    [DEPRECATED] 此函数已废弃，请勿使用。

    原因：Logger 单例已在 core/logger.py 中自动完成初始化，
    此函数为孤儿代码，项目中无任何调用点。

    保留目的：防止外部插件/脚本因 ImportError 崩溃。
    如有需要，请使用 from core.logger import logger。

    Args:
        log_dir: 日志目录路径，默认为 "logs"

    Raises:
        RuntimeError: 当日志系统初始化失败时抛出
    """
    import warnings
    warnings.warn(
        "setup_logging() is deprecated. Use 'from core.logger import logger' instead.",
        DeprecationWarning,
        stacklevel=2
    )
    # 创建日志目录
    try:
        os.makedirs(log_dir, exist_ok=True)
    except Exception as e:
        raise RuntimeError(f"[SILENT_FAILURE_BLOCKED] 创建日志目录失败: {e}") from e

    # 获取根日志器
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # 清除现有 StreamHandler（避免重复输出到控制台），保留文件处理器
    for handler in list(root_logger.handlers):
        if isinstance(handler, logging.StreamHandler):
            root_logger.removeHandler(handler)

    try:
        # 主日志 - 按大小轮转（10MB，保留5个）
        file_handler = RotatingFileHandler(
            filename=os.path.join(log_dir, "app.log"),
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(JsonFormatter())
        root_logger.addHandler(file_handler)

        # 错误日志 - 按时间轮转（每天，保留30天）
        error_handler = TimedRotatingFileHandler(
            filename=os.path.join(log_dir, "error.log"),
            when='midnight',
            interval=1,
            backupCount=30,
            encoding='utf-8'
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(JsonFormatter())
        root_logger.addHandler(error_handler)

        # 安全日志 - 按大小轮转（5MB，保留10个）
        security_handler = RotatingFileHandler(
            filename=os.path.join(log_dir, "security.log"),
            maxBytes=5 * 1024 * 1024,
            backupCount=10,
            encoding='utf-8'
        )
        security_handler.setLevel(logging.WARNING)
        security_handler.setFormatter(JsonFormatter())
        root_logger.addHandler(security_handler)

        # 验证日志系统是否正常工作
        root_logger.info("[Logging] 日志系统初始化完成")

    except Exception as e:
        raise RuntimeError(f"[SILENT_FAILURE_BLOCKED] 日志系统初始化失败: {e}") from e


class JsonFormatter(logging.Formatter):  # 定义JSON格式日志格式化器类
    """将日志格式化为 JSON 对象（用于结构化日志收集）"""  # 类文档字符串
    def format(self, record: logging.LogRecord) -> str:  # 定义格式化方法
        log_obj = {  # 构建日志对象字典
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),  # ISO格式时间戳
            "level": record.levelname,  # 日志级别名称
            "name": record.name,  # 日志器名称
            "message": record.getMessage(),  # 日志消息内容
            "module": record.module,  # 模块名
            "funcName": record.funcName,  # 函数名
            "lineno": record.lineno,  # 行号
        }
        if record.exc_info:  # 如果有异常信息
            log_obj["exception"] = traceback.format_exception(*record.exc_info)  # 添加异常堆栈
        # 添加自定义字段（如果有）
        if hasattr(record, "trace_id"):  # 如果有trace_id属性
            log_obj["trace_id"] = record.trace_id  # 添加追踪ID
        if hasattr(record, "session_id"):  # 如果有session_id属性
            log_obj["session_id"] = record.session_id  # 添加会话ID
        if hasattr(record, "extra"):  # 如果有extra属性
            log_obj.update(record.extra)  # 合并额外字段
        return json.dumps(log_obj, ensure_ascii=False)  # 序列化为JSON字符串（支持中文）


class SimpleFormatter(logging.Formatter):  # 定义简单格式日志格式化器类
    """简单格式化的日志（用于控制台，更易读）"""  # 类文档字符串
    def format(self, record: logging.LogRecord) -> str:  # 定义格式化方法
        timestamp = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")  # 格式化时间为HH:MM:SS
        level = record.levelname[0]  # 只取级别首字母 (D, I, W, E)
        return f"[{timestamp}] {level} | {record.getMessage()}"  # 返回格式化字符串


class Logger:  # 定义日志管理器类（单例模式）
    _instance = None  # 类属性：单例实例（初始None）
    _lock = threading.Lock()  # 类属性：线程锁（用于单例创建）
    _local = threading.local()  # 类属性：线程本地存储（用于trace_id/session_id）

    def __new__(cls, name="SiliconBase"):  # 定义创建实例方法
        if cls._instance is None:  # 如果实例不存在
            with cls._lock:  # 获取锁
                # 双重检查锁定
                if cls._instance is None:  # 再次检查（防止竞态）
                    cls._instance = super().__new__(cls)  # 创建实例
                    cls._instance._initialized = False  # 标记未初始化
        return cls._instance  # 返回单例实例

    def __init__(self, name="SiliconBase"):  # 定义初始化方法
        if self._initialized:  # 如果已初始化
            return  # 直接返回（避免重复初始化）
        self._initialized = True  # 标记已初始化

        # 延迟导入 config，避免循环导入问题
        try:  # 尝试导入配置
            from core.config import config  # 导入配置管理器
            level_name = config.get("logging.level", "INFO")  # 获取日志级别配置（默认INFO）
            console_output = config.get("logging.console_output", True)  # 是否输出到控制台（默认是）
            json_format = config.get("logging.json_format", False)  # 是否JSON格式（默认否）
            file_output = config.get("logging.file_output", False)  # 是否输出到文件（默认否）
            log_dir_name = config.get("logging.dir", "logs")  # 日志目录名（默认logs）
        except Exception as e:  # 捕获异常（导入失败）
            # 【零静默失败】配置导入失败必须记录，再使用默认配置
            logging.getLogger(__name__).error(
                f"[SILENT_FAILURE_BLOCKED] core.config 导入失败: {type(e).__name__}: {e}. "
                f"回退到默认日志配置。",
                exc_info=True
            )
            level_name = "INFO"  # 默认日志级别
            console_output = True  # 默认输出到控制台
            json_format = False  # 默认非JSON格式
            file_output = False  # 默认不输出到文件
            log_dir_name = "logs"  # 默认日志目录

        level = getattr(logging, level_name.upper(), logging.INFO)  # 获取日志级别数值

        self.logger = logging.getLogger(name)  # 创建Python日志器实例
        self.logger.setLevel(level)  # 设置日志级别
        self.logger.handlers.clear()  # 清空已有处理器（避免重复）

        # 控制台处理器（使用简单格式，更易读）
        if console_output:  # 如果启用控制台输出
            console = logging.StreamHandler(sys.stdout)  # 创建标准输出处理器
            console.setLevel(level)  # 设置处理器级别
            # 根据配置选择格式：JSON（用于收集）或简单格式（用于开发）
            console.setFormatter(JsonFormatter() if json_format else SimpleFormatter())  # 设置格式化器
            self.logger.addHandler(console)  # 添加处理器

        # 文件处理器（使用轮转配置）
        if file_output:  # 如果启用文件输出
            log_dir = Path(__file__).parent.parent / log_dir_name  # 构建日志目录路径
            try:
                log_dir.mkdir(exist_ok=True)  # 创建目录（如果不存在）

                # 主日志 - 按大小轮转（10MB，保留5个）
                app_handler = RotatingFileHandler(
                    log_dir / "app.log",
                    maxBytes=10 * 1024 * 1024,
                    backupCount=5,
                    encoding='utf-8'
                )
                app_handler.setLevel(level)
                app_handler.setFormatter(JsonFormatter())
                self.logger.addHandler(app_handler)

                # 错误日志 - 按时间轮转（每天，保留30天）
                error_handler = TimedRotatingFileHandler(
                    log_dir / "error.log",
                    when='midnight',
                    interval=1,
                    backupCount=30,
                    encoding='utf-8'
                )
                error_handler.setLevel(logging.ERROR)
                error_handler.setFormatter(JsonFormatter())
                self.logger.addHandler(error_handler)

                # 安全日志 - 按大小轮转（5MB，保留10个）
                security_handler = RotatingFileHandler(
                    log_dir / "security.log",
                    maxBytes=5 * 1024 * 1024,
                    backupCount=10,
                    encoding='utf-8'
                )
                security_handler.setLevel(logging.WARNING)
                security_handler.setFormatter(JsonFormatter())
                self.logger.addHandler(security_handler)

            except Exception as e:
                # 零静默失败：抛出异常
                raise RuntimeError(f"[SILENT_FAILURE_BLOCKED] 日志文件处理器初始化失败: {e}") from e

    def _add_extra(self, kwargs):  # 定义添加额外字段的私有方法
        """添加线程本地变量到 extra"""  # 方法文档字符串
        extra = kwargs.get("extra", {})  # 获取extra字典（默认空字典）
        if hasattr(self._local, "trace_id"):  # 如果线程本地有trace_id
            extra["trace_id"] = self._local.trace_id  # 添加到extra
        if hasattr(self._local, "session_id"):  # 如果线程本地有session_id
            extra["session_id"] = self._local.session_id  # 添加到extra
        kwargs["extra"] = extra  # 更新kwargs
        return kwargs  # 返回更新后的kwargs

    def set_trace_id(self, trace_id: str):  # 定义设置追踪ID方法
        """为当前线程设置 trace_id"""  # 方法文档字符串
        self._local.trace_id = trace_id  # 设置线程本地trace_id

    def set_session_id(self, session_id: str):  # 定义设置会话ID方法
        """为当前线程设置 session_id"""  # 方法文档字符串
        self._local.session_id = session_id  # 设置线程本地session_id

    def debug(self, msg, *args, **kwargs):  # 定义debug日志方法
        self.logger.debug(msg, *args, **self._add_extra(kwargs))  # 调用底层debug方法并添加extra

    def info(self, msg, *args, **kwargs):  # 定义info日志方法
        self.logger.info(msg, *args, **self._add_extra(kwargs))  # 调用底层info方法并添加extra

    def warning(self, msg, *args, **kwargs):  # 定义warning日志方法
        self.logger.warning(msg, *args, **self._add_extra(kwargs))  # 调用底层warning方法并添加extra

    def error(self, msg, *args, **kwargs):  # 定义error日志方法
        self.logger.error(msg, *args, **self._add_extra(kwargs))  # 调用底层error方法并添加extra

    def exception(self, msg, *args, **kwargs):  # 定义exception日志方法
        self.logger.exception(msg, *args, **self._add_extra(kwargs))  # 调用底层exception方法并添加extra


logger = Logger()  # 创建Logger单例实例（全局日志器）


# =============================================================================
# 总结性注释：文件角色、关联关系与核心效果
# =============================================================================
#
# 【文件角色】
# 本文件（logger.py）是 SiliconBase V5 系统的"结构化日志管理器"核心模块。
# 采用单例模式提供统一的日志记录服务，支持结构化JSON日志输出和线程上下文追踪。
# 是系统中所有模块进行日志记录的基础设施。
#
# 【核心职责】
# 1. 日志格式化：提供JsonFormatter（结构化JSON）和SimpleFormatter（可读格式）两种格式
# 2. 日志输出：支持控制台输出和文件轮转输出
# 3. 线程上下文：通过threading.local()存储trace_id和session_id，实现请求追踪
# 4. 配置集成：从core.config读取日志配置（级别、输出方式、格式等）
# 5. 异常记录：自动捕获和格式化异常堆栈信息
#
# 【核心类说明】
# 1. JsonFormatter: JSON格式日志格式化器
#    - 输出结构化JSON，包含timestamp、level、name、message等字段
#    - 支持trace_id、session_id等自定义字段
#    - 自动格式化异常堆栈
#    - 适用于日志收集系统（如ELK）
#
# 2. SimpleFormatter: 简单格式日志格式化器
#    - 输出格式：[HH:MM:SS] L | message
#    - 简洁易读，适用于开发调试
#    - 只显示级别首字母（D/I/W/E）
#
# 3. Logger: 日志管理器（单例）
#    - 使用双重检查锁定实现线程安全单例
#    - 支持通过set_trace_id/set_session_id设置线程上下文
#    - 自动将线程上下文附加到每条日志
#    - 提供debug/info/warning/error/exception五级日志方法
#
# 【配置项】（从core.config读取）
# - logging.level: 日志级别（DEBUG/INFO/WARNING/ERROR，默认INFO）
# - logging.console_output: 是否输出到控制台（默认True）
# - logging.json_format: 控制台是否使用JSON格式（默认False）
# - logging.file_output: 是否输出到文件（默认False）
# - logging.dir: 日志目录名（默认logs）
#
# 【关联文件】
# 1. core/config.py                - 配置管理器
#    * 关系：被Logger.__init__导入，读取日志配置
#    * 交互：获取日志级别、输出方式等配置项
#    * 注意：延迟导入避免循环依赖
#
# 2. 几乎所有其他模块              - 日志使用者
#    * 关系：各模块通过 from core.logger import logger 使用
#    * 交互：调用logger.info/debug/error等方法记录日志
#    * 示例：
#      - core/agent_loop.py: 记录Agent循环状态
#      - core/tool_manager.py: 记录工具调用
#      - core/intent_handler.py: 记录意图处理
#      - core/memory.py: 记录记忆操作
#
# 【使用方式】
# from core.logger import logger  # 导入全局日志器
# logger.info("消息内容")  # 记录信息日志
# logger.error("错误信息")  # 记录错误日志
# logger.set_trace_id("trace_123")  # 设置当前线程追踪ID
# logger.set_session_id("session_456")  # 设置当前线程会话ID
#
# 【达到的效果】
# 1. 统一日志：全系统使用统一的日志格式和输出方式
# 2. 结构化日志：支持JSON格式，便于日志收集和分析
# 3. 请求追踪：通过trace_id和session_id实现跨模块请求追踪
# 4. 线程安全：使用threading.local()保证多线程环境下的上下文隔离
# 5. 灵活配置：通过配置文件控制日志级别和输出方式
# 6. 自动轮转：文件日志支持按大小自动轮转（10MB×5个备份）
# 7. 异常记录：自动捕获和记录完整的异常堆栈信息
#
# 【典型日志输出示例】
# JSON格式：
# {"timestamp": "2026-03-02T12:00:00", "level": "INFO", "name": "SiliconBase",
#  "message": "任务完成", "module": "agent_loop", "funcName": "run",
#  "lineno": 100, "trace_id": "trace_123", "session_id": "session_456"}
#
# 简单格式：
# [12:00:00] I | 任务完成
#
# =============================================================================
