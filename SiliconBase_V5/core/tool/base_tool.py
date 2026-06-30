#!/usr/bin/env python3                          # 指定Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文字符
"""
原子工具基类 - 所有工具必须继承此类，并遵循统一返回值格式
2026-02-16 修复：增加中断标志和 interrupt() 方法，支持强制终止
2026-03-11 修复：重构run方法，添加统一异常处理和明确错误返回
"""
import asyncio  # 【Phase 4】导入异步IO，支持 run_async 桥接
import contextlib
import threading  # 导入线程模块，用于中断锁
from abc import ABC  # 从abc模块导入ABC基类和abstractmethod装饰器
from typing import Any  # 从typing模块导入类型提示

import jsonschema  # 导入jsonschema库，用于JSON模式验证

from core.logger import logger  # 导入日志记录器
from core.utils.error_codes import INVALID_PARAMS, format_error  # 导入错误格式化函数和错误码


class BaseTool(ABC):                             # 定义抽象基类BaseTool，所有工具必须继承此类
    tool_id: str                                 # 类属性：工具唯一标识符
    name: str                                    # 类属性：工具名称（可读）
    description: str = ""                        # 类属性：工具描述说明
    version: str = "1.0.0"                       # 类属性：工具版本号，默认1.0.0
    input_schema: dict = {}                      # 类属性：输入参数JSON Schema定义
    output_schema: dict = {}                     # 类属性：输出结果JSON Schema定义
    timeout: int = 30                            # 类属性：工具执行超时时间（秒），默认30
    require_confirmation: bool = False           # 类属性：是否需要用户确认，默认False
    require_sandbox: bool = False                # 类属性：是否需要在沙箱中执行，默认False
    enabled: bool = True                         # 类属性：工具是否启用，默认True
    deprecated: bool = False                     # 类属性：工具是否已废弃，默认False
    deprecated_reason: str = ""                  # 类属性：废弃原因说明，默认空字符串
    is_duplicate: bool = False                   # 类属性：是否为重复工具，默认False
    duplicate_of: str = ""                       # 类属性：被哪个工具替代，默认空字符串

    # ========== 云端+本地双版本工具管控架构 ==========
    tool_owner: str = "system"                   # 类属性：工具所有者
                                                 # - "system": 系统内置工具
                                                 # - "user": 用户安装的工具
                                                 # - "custom": 用户自定义工具
                                                 # - "platform": 平台提供的高级工具

    def __init__(self):                          # 初始化方法
        self._interrupted = False                # 实例属性：中断标志，标记是否收到中断信号
        self._interrupt_lock = threading.Lock()  # 实例属性：中断锁，确保线程安全
        self._should_stop = False                # 实例属性：停止标志，用于超时中断
        self._is_running = False                 # 实例属性：运行标志，标记工具是否正在运行

    def _execute(self, **kwargs) -> dict[str, Any]:
        """
        工具同步执行逻辑。子类必须实现 _execute 或 _execute_async。

        Phase 8 TRUE_ASYNC 改造后：
        - 如果子类实现了 _execute_async，同步调用方必须使用 await tool.run_async()
        - _execute 不再桥接 _execute_async，禁止嵌套事件循环

        Returns:
            Dict[str, Any]: 包含以下键的字典：
                - success: bool - 是否执行成功
                - error_code: str - 错误代码（成功时可为None或空字符串）
                - user_message: str - 给用户的消息
                - data: Any - 返回的数据（可选）
        """
        raise NotImplementedError(
            f"工具 {self.tool_id} 未实现 _execute()。"
            f"如果该工具已异步化（有 _execute_async），请在异步上下文中使用 await tool.run_async()。"
        )

    def _normalize_result(self, result) -> dict[str, Any]:
        """
        标准化工具执行结果。

        1. None 检查
        2. 类型检查（必须为 dict）
        3. 补全 success 字段
        4. 补全 error_code 字段
        5. 补全 user_message 字段

        Returns:
            Dict[str, Any]: 标准化后的结果字典
        """
        if result is None:
            logger.error(f"[BaseTool] {self.tool_id} 返回None")
            return {
                "success": False,
                "error_code": "TOOL_RETURNED_NONE",
                "error_message": f"工具{self.tool_id}未返回有效结果",
                "data": None
            }

        if not isinstance(result, dict):
            logger.error(f"[BaseTool] {self.tool_id} 返回类型错误: {type(result)}")
            return {
                "success": False,
                "error_code": "INVALID_RETURN_TYPE",
                "error_message": f"工具{self.tool_id}返回类型错误，期望dict，实际为{type(result).__name__}",
                "data": None
            }

        # 验证必需字段
        if "success" not in result:
            logger.warning(f"[BaseTool] {self.tool_id} 返回结果缺少success字段，自动设置为True")
            result["success"] = True

        # 确保错误结果有error_code
        if not result.get("success") and "error_code" not in result:
            result["error_code"] = "EXECUTION_ERROR"

        # 确保有user_message
        if "user_message" not in result:
            if result.get("success"):
                result["user_message"] = "操作成功"
            else:
                error_msg = result.get("error_message") or result.get("message") or "工具执行失败"
                result["user_message"] = error_msg

        return result

    def _handle_execution_error(self, exc: Exception, is_async: bool = False) -> dict[str, Any]:
        """
        统一处理执行异常并返回标准化错误格式。

        Args:
            exc: 捕获到的异常对象
            is_async: 是否为异步上下文，影响日志前缀

        Returns:
            Dict[str, Any]: 标准化错误结果
        """
        prefix = "async " if is_async else ""

        if isinstance(exc, TypeError):
            logger.error(f"[BaseTool] {self.tool_id} {prefix}参数类型错误: {exc}", exc_info=True)
            return {
                "success": False,
                "error_code": "INVALID_PARAMS",
                "error_message": f"参数类型错误: {str(exc)}",
                "data": None
            }

        if isinstance(exc, ValueError):
            logger.error(f"[BaseTool] {self.tool_id} {prefix}参数值错误: {exc}", exc_info=True)
            return {
                "success": False,
                "error_code": "INVALID_PARAMS",
                "error_message": f"参数值错误: {str(exc)}",
                "data": None
            }

        if isinstance(exc, KeyError):
            logger.error(f"[BaseTool] {self.tool_id} {prefix}缺少必需参数: {exc}", exc_info=True)
            return {
                "success": False,
                "error_code": "MISSING_PARAM",
                "error_message": f"缺少必需参数: {str(exc)}",
                "data": None
            }

        if isinstance(exc, FileNotFoundError):
            logger.error(f"[BaseTool] {self.tool_id} {prefix}文件未找到: {exc}", exc_info=True)
            return {
                "success": False,
                "error_code": "FILE_NOT_FOUND",
                "error_message": f"文件未找到: {str(exc)}",
                "data": None
            }

        if isinstance(exc, PermissionError):
            logger.error(f"[BaseTool] {self.tool_id} {prefix}权限不足: {exc}", exc_info=True)
            return {
                "success": False,
                "error_code": "PERMISSION_DENIED",
                "error_message": f"权限不足: {str(exc)}",
                "data": None
            }

        if isinstance(exc, TimeoutError):
            logger.error(f"[BaseTool] {self.tool_id} {prefix}执行超时: {exc}", exc_info=True)
            return {
                "success": False,
                "error_code": "TOOL_TIMEOUT",
                "error_message": f"工具执行超时: {str(exc)}",
                "data": None
            }

        if isinstance(exc, ConnectionError):
            logger.error(f"[BaseTool] {self.tool_id} {prefix}连接错误: {exc}", exc_info=True)
            return {
                "success": False,
                "error_code": "CONNECTION_ERROR",
                "error_message": f"连接错误: {str(exc)}",
                "data": None
            }

        if isinstance(exc, OSError):
            logger.error(f"[BaseTool] {self.tool_id} {prefix}系统错误: {exc}", exc_info=True)
            return {
                "success": False,
                "error_code": "OS_ERROR",
                "error_message": f"系统错误: {str(exc)}",
                "data": None
            }

        logger.error(f"[BaseTool] {self.tool_id} {prefix}执行异常: {exc}", exc_info=True)
        return {
            "success": False,
            "error_code": "EXECUTION_ERROR",
            "error_message": f"工具执行失败: {str(exc)}",
            "data": None
        }

    def run(self, **kwargs) -> dict[str, Any]:   # 定义run方法，工具执行入口
        """
        工具执行入口 - 统一异常处理和错误返回

        @deprecated: 同步入口已弃用。异步上下文中请使用 await tool.run_async()。
        保留此方法仅用于向后兼容的同步调用方。

        此方法负责：
        1. 调用子类实现的 _execute 方法
        2. 验证返回结果格式
        3. 统一异常捕获和日志记录
        4. 确保返回标准化的错误信息

        契约：
        - 所有异常都被捕获并转换为标准错误返回格式
        - 绝不抛出异常到调用方
        - 所有错误都记录ERROR级别日志

        Returns:
            Dict[str, Any]: 标准化执行结果
        """
        try:
            result = self._execute(**kwargs)
            return self._normalize_result(result)
        except Exception as e:
            return self._handle_execution_error(e)

    async def run_async(self, **kwargs) -> dict[str, Any]:
        """
        异步执行入口 - 统一异常处理和错误返回

        Phase 4 新增：所有新增工具必须同时提供 _execute_async 实现。
        旧工具可逐步迁移；未迁移的工具通过 AsyncToolGateway 桥接。

        【V2新增】UI 操作自动记录（前后截图 + AI 建议）

        Returns:
            Dict[str, Any]: 标准化执行结果
        """
        # 【V2】UI 操作记录：操作前截图
        _before_path = None
        _action_logger = None
        try:
            from core.vision.action_logger import _is_ui_action_tool, get_action_logger
            _action_logger = get_action_logger()
            if _action_logger.is_recording_enabled() and _is_ui_action_tool(self.tool_id):
                _before_path = await _action_logger.before_action(self.tool_id, kwargs)
        except Exception:
            pass

        try:
            result = await self._execute_async(**kwargs)
            normalized = self._normalize_result(result)

            # 【V2】UI 操作记录：操作后截图 + 保存日志（后台执行，不阻塞）
            if _before_path and _action_logger:
                with contextlib.suppress(Exception):
                    asyncio.create_task(
                        _action_logger.after_action(self.tool_id, kwargs, normalized, _before_path)
                    )

            return normalized

        except Exception as e:
            return self._handle_execution_error(e, is_async=True)

    async def _execute_async(self, **kwargs) -> dict[str, Any]:
        """
        异步执行逻辑 - 子类可选择实现。

        默认行为：通过 asyncio.to_thread 委托给同步 _execute()，
        避免在事件循环线程中直接执行阻塞操作。
        inherently 异步的工具（网络、文件IO、子进程等）建议显式重写本方法。

        Returns:
            Dict[str, Any]: 标准化执行结果
        """
        if type(self)._execute is BaseTool._execute:
            raise NotImplementedError(
                f"工具 {self.tool_id} 未实现 _execute() 或 _execute_async()。"
            )
        return await asyncio.to_thread(self._execute, **kwargs)

    def is_interrupted(self) -> bool:            # 定义检查中断状态的方法
        """检查是否收到中断信号"""                 # 方法文档字符串
        with self._interrupt_lock:               # 获取中断锁，确保线程安全
            return self._interrupted             # 返回中断标志值

    def interrupt(self):                         # 定义发送中断信号的方法
        """发送中断信号给此工具"""                 # 方法文档字符串
        with self._interrupt_lock:               # 获取中断锁
            self._interrupted = True             # 设置中断标志为True
        logger.debug(f"工具 {self.tool_id} 收到中断信号")   # 记录调试日志

    def check_params(self, **kwargs) -> dict:    # 定义参数校验方法
        """参数校验，返回统一格式校验结果"""       # 方法文档字符串
        if not self.input_schema:                # 如果没有定义输入模式
            return {"success": True, "error_code": "", "user_message": ""}   # 直接返回成功
        try:                                     # 尝试验证参数
            jsonschema.validate(kwargs, self.input_schema)   # 使用jsonschema验证参数
            return {"success": True, "error_code": "", "user_message": ""}   # 验证通过返回成功
        except jsonschema.ValidationError as e:  # JSON模式验证错误
            return format_error(INVALID_PARAMS, detail=e.message)   # 返回格式化错误
        except Exception as e:                   # 其他异常
            logger.error(f"[BaseTool] {self.tool_id} 参数校验异常: {e}", exc_info=True)
            return format_error(INVALID_PARAMS, detail=str(e))   # 返回格式化错误


# =============================================================================
# 【文件总结性注释】
# =============================================================================
#
# 【文件角色】
# core/base_tool.py 是 SiliconBase V5 项目的 "原子工具基类" 模块，位于 core 目录下。
#
# 核心定位：
#   - 所有工具的抽象基类，定义工具的通用接口和行为规范
#   - 提供统一的工具返回值格式
#   - 支持工具执行中断机制
#   - 提供参数自动校验功能
#
# 主要职责：
#   1. 定义工具接口：抽象方法 _execute() 是所有工具必须实现的核心逻辑
#   2. run()方法提供统一异常处理：捕获所有异常并返回标准化错误格式
#   3. 规范返回值格式：强制要求返回包含 success/error_code/user_message/data 的字典
#   4. 中断控制：提供 interrupt() 和 is_interrupted() 方法支持任务中断
#   5. 参数校验：提供 check_params() 方法基于 JSON Schema 自动验证参数
#
# -----------------------------------------------------------------------------
#
# 【关联文件】
#
# 1. 依赖的模块（本文件导入）：
#    - core.logger
#      * 提供日志记录功能
#      * 在异常时记录错误详情
#
#    - core.error_codes
#      * 提供 format_error() 函数格式化错误
#      * 提供 INVALID_PARAMS 错误码常量
#
# 2. 依赖方（继承/使用本文件）：
#    - 所有具体的工具类
#      * 如 FileTool、WebTool、SystemTool 等
#      * 必须继承 BaseTool 并实现 _execute() 方法
#
#    - core/tool_manager.py
#      * 管理所有工具实例
#      * 调用工具的 check_params() 进行参数校验
#      * 调用工具的 interrupt() 方法中断执行
#      * 调用工具的 run() 方法执行工具
#
# -----------------------------------------------------------------------------
#
# 【类属性说明】
#
# tool_id (str)：
#   - 工具的唯一标识符
#   - 用于在工具管理器中查找和调用工具
#
# name (str)：
#   - 工具的人类可读名称
#   - 用于前端展示和日志记录
#
# description (str)：
#   - 工具的功能描述
#   - 帮助用户和AI理解工具的用途
#
# version (str)：
#   - 工具的版本号
#   - 默认 "1.0.0"
#
# input_schema (Dict)：
#   - JSON Schema 格式的输入参数定义
#   - 用于自动校验输入参数
#   - 示例：{"type": "object", "properties": {"path": {"type": "string"}}}
#
# output_schema (Dict)：
#   - JSON Schema 格式的输出结果定义
#   - 用于验证返回结果格式
#
# timeout (int)：
#   - 工具执行超时时间（秒）
#   - 默认 30 秒
#
# require_confirmation (bool)：
#   - 是否需要用户确认后执行
#   - 用于高风险工具，如删除文件
#
# require_sandbox (bool)：
#   - 是否需要在沙箱环境中执行
#   - 用于隔离潜在危险的工具
#
# -----------------------------------------------------------------------------
#
# 【返回值格式】
#
# 所有工具必须返回以下格式的字典：
# {
#     "success": bool,           # 是否执行成功
#     "error_code": str,         # 错误代码（成功可为空）
#     "user_message": str,       # 给用户的消息（成功或失败提示）
#     "data": Any                # 返回的数据（可选）
# }
#
# 成功示例：
# {
#     "success": True,
#     "error_code": "",
#     "user_message": "文件读取成功",
#     "data": {"content": "文件内容..."}
# }
#
# 失败示例：
# {
#     "success": False,
#     "error_code": "FILE_NOT_FOUND",
#     "user_message": "文件不存在：/path/to/file",
#     "data": None
# }
#
# -----------------------------------------------------------------------------
#
# 【中断机制】
#
# 工具支持被中断的机制：
#
# 1. 在工具实现中检查中断：
#    def _execute(self, **kwargs):
#        for item in long_list:
#            if self.is_interrupted():          # 检查是否收到中断
#                return {
#                    "success": False,
#                    "error_code": "INTERRUPTED",
#                    "user_message": "工具执行被中断",
#                    "data": None
#                }
#            # 执行操作...
#
# 2. 外部中断工具：
#    tool = SomeTool()
#    # 在另一个线程或信号处理中
#    tool.interrupt()                           # 发送中断信号
#
# 这种机制用于：
#   - 任务超时中断
#   - 用户手动取消
#   - 系统关闭时优雅停止
#
# -----------------------------------------------------------------------------
#
# 【使用示例】
#
# 1. 定义新工具：
#    from core.tool.base_tool import BaseTool
#
#    class MyTool(BaseTool):
#        tool_id = "my_tool"
#        name = "我的工具"
#        description = "这是一个示例工具"
#        input_schema = {
#            "type": "object",
#            "properties": {
#                "param1": {"type": "string"}
#            },
#            "required": ["param1"]
#        }
#
#        def _execute(self, **kwargs):
#            # 参数校验
#            check_result = self.check_params(**kwargs)
#            if not check_result["success"]:
#                return check_result
#
#            # 执行逻辑（无需try-except，由run方法统一处理）
#            param1 = kwargs.get("param1")
#
#            # 检查中断
#            if self.is_interrupted():
#                return {
#                    "success": False,
#                    "error_code": "INTERRUPTED",
#                    "user_message": "执行被中断"
#                }
#
#            # 返回结果
#            return {
#                "success": True,
#                "error_code": "",
#                "user_message": "执行成功",
#                "data": {"result": param1.upper()}
#            }
#
# 2. 使用工具：
#    tool = MyTool()
#    result = tool.run(param1="hello")
#    print(result["user_message"])
#
# -----------------------------------------------------------------------------
#
# 【设计原则】
#
# 1. 抽象基类：
#    - 使用 ABC 和 @abstractmethod 强制子类实现 _execute()
#    - 确保所有工具都有统一的接口
#
# 2. 统一异常处理：
#    - run()方法捕获所有异常，绝不抛出到调用方
#    - 所有异常都记录ERROR级别日志
#    - 返回标准化的错误格式
#
# 3. 类型安全：
#    - 使用类型提示明确参数和返回值类型
#    - 便于静态检查和IDE提示
#
# 4. 线程安全：
#    - 使用 threading.Lock 保护中断标志
#    - 支持多线程环境下安全中断
#
# 5. 参数校验：
#    - 使用 JSON Schema 声明参数格式
#    - 自动校验，减少重复代码
#
# =============================================================================
