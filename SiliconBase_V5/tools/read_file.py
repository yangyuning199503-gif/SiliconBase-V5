"""读取文件工具 - 用于读取文本文件内容

功能：读取指定文件的内容，支持分页读取和编码错误处理
"""
import os
from typing import Any

from core.logger import logger
from core.tool.base_tool import BaseTool


class ReadFile(BaseTool):
    """
    读取文件工具类

    用于读取文本文件内容，支持：
    - 指定起始行偏移量(offset)
    - 限制读取行数(limit)
    - 自动处理编码错误
    - 返回文件统计信息（总行数、是否截断等）
    """

    tool_id = "read_file"
    name = "读取文件"
    description = "读取指定文本文件的内容，支持分页读取和编码错误处理"
    version = "1.0.0"
    timeout = 30

    input_schema = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "要读取的文件路径（绝对路径或相对路径）"
            },
            "limit": {
                "type": "integer",
                "description": "最多读取的行数，默认100行",
                "default": 100,
                "minimum": 1,
                "maximum": 10000
            },
            "offset": {
                "type": "integer",
                "description": "起始行偏移量（从0开始），默认0",
                "default": 0,
                "minimum": 0
            }
        },
        "required": ["file_path"]
    }

    output_schema = {
        "type": "object",
        "properties": {
            "success": {"type": "boolean"},
            "error_code": {"type": "string"},
            "user_message": {"type": "string"},
            "data": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "文件内容"},
                    "total_lines": {"type": "integer", "description": "文件总行数"},
                    "lines_read": {"type": "integer", "description": "实际读取行数"},
                    "truncated": {"type": "boolean", "description": "是否被截断"},
                    "offset": {"type": "integer", "description": "起始偏移量"},
                    "limit": {"type": "integer", "description": "限制行数"},
                    "file_path": {"type": "string", "description": "文件路径"},
                    "file_size": {"type": "integer", "description": "文件大小（字节）"}
                }
            }
        }
    }

    def _validate_path(self, file_path: str) -> None:
        """验证路径，防止路径遍历攻击"""
        # 获取允许的基础目录列表
        allowed_base_dirs = [
            os.getcwd(),
            os.path.expanduser("~"),
            # 可以添加其他允许目录
        ]

        # 规范化路径
        real_path = os.path.realpath(file_path)

        # 检查是否在允许目录内
        is_allowed = any(
            real_path.startswith(base_dir)
            for base_dir in allowed_base_dirs
        )

        if not is_allowed:
            error_msg = f"[SECURITY_ERROR] 路径遍历检测：'{file_path}' 不在允许访问的目录内"
            logger.error(error_msg)
            raise PermissionError(error_msg)

    def _execute(self, **kwargs) -> dict[str, Any]:
        """
        执行文件读取操作

        Args:
            file_path: 要读取的文件路径
            limit: 最多读取的行数，默认100
            offset: 起始行偏移量，默认0

        Returns:
            Dict[str, Any]: 包含文件内容、统计信息等的字典
        """
        # 参数校验
        check_result = self.check_params(**kwargs)
        if not check_result["success"]:
            return check_result

        # 获取参数
        file_path = kwargs.get("file_path")
        limit = kwargs.get("limit", 100)
        offset = kwargs.get("offset", 0)

        # 【P0修复】路径遍历验证
        try:
            self._validate_path(file_path)
        except PermissionError as e:
            return {
                "success": False,
                "error_code": "PATH_TRAVERSAL",
                "user_message": str(e),
                "data": None
            }

        # 检查中断
        if self.is_interrupted():
            return {
                "success": False,
                "error_code": "INTERRUPTED",
                "user_message": "工具执行被中断",
                "data": None
            }

        # 检查文件是否存在
        if not os.path.exists(file_path):
            logger.error(f"[ReadFile] 文件不存在: {file_path}")
            return {
                "success": False,
                "error_code": "FILE_NOT_FOUND",
                "user_message": f"文件不存在: {file_path}",
                "data": None
            }

        # 检查是否为文件
        if not os.path.isfile(file_path):
            logger.error(f"[ReadFile] 路径不是文件: {file_path}")
            return {
                "success": False,
                "error_code": "NOT_A_FILE",
                "user_message": f"指定的路径不是文件: {file_path}",
                "data": None
            }

        # 获取文件大小
        try:
            file_size = os.path.getsize(file_path)
        except OSError as e:
            logger.error(f"[ReadFile] 无法获取文件大小: {e}")
            file_size = -1

        # 读取文件内容
        try:
            # 首先读取所有行以获取总行数
            with open(file_path, encoding='utf-8', errors='ignore') as f:
                all_lines = f.readlines()

            total_lines = len(all_lines)

            # 检查中断
            if self.is_interrupted():
                return {
                    "success": False,
                    "error_code": "INTERRUPTED",
                    "user_message": "工具执行被中断",
                    "data": None
                }

            # 计算实际读取范围
            start_line = offset
            end_line = min(offset + limit, total_lines)

            # 检查offset是否超出范围
            if start_line >= total_lines:
                return {
                    "success": True,
                    "error_code": "",
                    "user_message": f"偏移量 {offset} 超出文件总行数 {total_lines}",
                    "data": {
                        "content": "",
                        "total_lines": total_lines,
                        "lines_read": 0,
                        "truncated": False,
                        "offset": offset,
                        "limit": limit,
                        "file_path": file_path,
                        "file_size": file_size
                    }
                }

            # 读取指定范围的行
            selected_lines = all_lines[start_line:end_line]
            content = ''.join(selected_lines)

            # 移除末尾的换行符（如果存在）
            if content.endswith('\n'):
                content = content[:-1]

            lines_read = len(selected_lines)
            truncated = end_line < total_lines

            # 构建返回结果
            result_data = {
                "content": content,
                "total_lines": total_lines,
                "lines_read": lines_read,
                "truncated": truncated,
                "offset": offset,
                "limit": limit,
                "file_path": file_path,
                "file_size": file_size
            }

            # 构建用户消息
            if truncated:
                user_message = f"成功读取文件，共 {lines_read}/{total_lines} 行（已截断）"
            else:
                user_message = f"成功读取文件，共 {lines_read}/{total_lines} 行"

            logger.info(f"[ReadFile] 成功读取文件: {file_path}, 行数: {lines_read}/{total_lines}")

            return {
                "success": True,
                "error_code": "",
                "user_message": user_message,
                "data": result_data
            }

        except PermissionError as e:
            logger.error(f"[ReadFile] 权限不足: {e}")
            return {
                "success": False,
                "error_code": "PERMISSION_DENIED",
                "user_message": f"权限不足，无法读取文件: {file_path}",
                "data": None
            }
        except Exception as e:
            logger.error(f"[ReadFile] 读取文件失败: {e}")
            return {
                "success": False,
                "error_code": "READ_ERROR",
                "user_message": f"读取文件失败: {str(e)}",
                "data": None
            }

    async def _execute_async(self, **kwargs) -> dict[str, Any]:
        """Phase 8 TRUE_ASYNC: 使用 aiofiles 读取文件，零线程池"""
        import aiofiles

        # 参数校验
        check_result = self.check_params(**kwargs)
        if not check_result["success"]:
            return check_result

        file_path = kwargs.get("file_path")
        limit = kwargs.get("limit", 100)
        offset = kwargs.get("offset", 0)

        # 路径遍历验证
        try:
            self._validate_path(file_path)
        except PermissionError as e:
            return {
                "success": False,
                "error_code": "PATH_TRAVERSAL",
                "user_message": str(e),
                "data": None
            }

        # 检查中断
        if self.is_interrupted():
            return {
                "success": False,
                "error_code": "INTERRUPTED",
                "user_message": "工具执行被中断",
                "data": None
            }

        # 检查文件是否存在
        if not os.path.exists(file_path):
            logger.error(f"[ReadFile] 文件不存在: {file_path}")
            return {
                "success": False,
                "error_code": "FILE_NOT_FOUND",
                "user_message": f"文件不存在: {file_path}",
                "data": None
            }

        if not os.path.isfile(file_path):
            logger.error(f"[ReadFile] 路径不是文件: {file_path}")
            return {
                "success": False,
                "error_code": "NOT_A_FILE",
                "user_message": f"指定的路径不是文件: {file_path}",
                "data": None
            }

        try:
            file_size = os.path.getsize(file_path)
        except OSError as e:
            logger.error(f"[ReadFile] 无法获取文件大小: {e}")
            file_size = -1

        # TRUE_ASYNC: 使用 aiofiles 读取
        try:
            async with aiofiles.open(file_path, encoding='utf-8', errors='ignore') as f:
                all_lines = await f.readlines()

            total_lines = len(all_lines)

            if self.is_interrupted():
                return {
                    "success": False,
                    "error_code": "INTERRUPTED",
                    "user_message": "工具执行被中断",
                    "data": None
                }

            start_line = offset
            end_line = min(offset + limit, total_lines)

            if start_line >= total_lines:
                return {
                    "success": True,
                    "error_code": "",
                    "user_message": f"偏移量 {offset} 超出文件总行数 {total_lines}",
                    "data": {
                        "content": "",
                        "total_lines": total_lines,
                        "lines_read": 0,
                        "truncated": False,
                        "offset": offset,
                        "limit": limit,
                        "file_path": file_path,
                        "file_size": file_size
                    }
                }

            selected_lines = all_lines[start_line:end_line]
            content = ''.join(selected_lines)
            if content.endswith('\n'):
                content = content[:-1]

            lines_read = len(selected_lines)
            truncated = end_line < total_lines

            result_data = {
                "content": content,
                "total_lines": total_lines,
                "lines_read": lines_read,
                "truncated": truncated,
                "offset": offset,
                "limit": limit,
                "file_path": file_path,
                "file_size": file_size
            }

            if truncated:
                user_message = f"成功读取文件，共 {lines_read}/{total_lines} 行（已截断）"
            else:
                user_message = f"成功读取文件，共 {lines_read}/{total_lines} 行"

            logger.info(f"[ReadFile] 成功读取文件: {file_path}, 行数: {lines_read}/{total_lines}")

            return {
                "success": True,
                "error_code": "",
                "user_message": user_message,
                "data": result_data
            }

        except PermissionError as e:
            logger.error(f"[ReadFile] 权限不足: {e}")
            return {
                "success": False,
                "error_code": "PERMISSION_DENIED",
                "user_message": f"权限不足，无法读取文件: {file_path}",
                "data": None
            }
        except Exception as e:
            logger.error(f"[ReadFile] 读取文件失败: {e}")
            return {
                "success": False,
                "error_code": "READ_ERROR",
                "user_message": f"读取文件失败: {str(e)}",
                "data": None
            }


# =============================================================================
# 【文件总结性注释】
# =============================================================================
#
# 【文件角色】
# tools/read_file.py 是 SiliconBase V5 项目的 "读取文件" 工具模块。
#
# 核心定位：
#   - 提供文本文件读取功能
#   - 支持分页读取（offset + limit）
#   - 自动处理编码错误（utf-8 with ignore）
#   - 返回详细的文件统计信息
#
# 主要职责：
#   1. 读取文本文件内容
#   2. 支持指定起始行和读取行数限制
#   3. 处理编码错误，确保读取不中断
#   4. 返回文件统计信息（总行数、是否截断、文件大小等）
#
# -----------------------------------------------------------------------------
#
# 【关联文件】
#
# 1. 依赖的模块（本文件导入）：
#    - core.tool.base_tool.BaseTool
#      * 工具基类，提供统一的工具接口
#
#    - core.logger
#      * 提供日志记录功能
#
# 2. 依赖方（使用本工具）：
#    - core/tool_manager.py
#      * 工具管理器，注册和管理所有工具
#
# -----------------------------------------------------------------------------
#
# 【使用示例】
#
# 1. 直接使用工具：
#    from tools.read_file import ReadFile
#
#    tool = ReadFile()
#    result = tool.run(file_path="/path/to/file.txt", limit=50, offset=0)
#
#    if result["success"]:
#        print(result["data"]["content"])
#        print(f"总行数: {result['data']['total_lines']}")
#        print(f"是否截断: {result['data']['truncated']}")
#    else:
#        print(f"错误: {result['user_message']}")
#
# 2. 通过工具管理器使用：
#    from core.tool_manager import tool_manager
#
#    result = tool_manager.execute("read_file", file_path="test.txt")
#
# -----------------------------------------------------------------------------
#
# 【设计原则】
#
# 1. 编码容错：
#    - 使用 encoding='utf-8', errors='ignore' 处理编码错误
#    - 确保即使文件包含非法字符也能读取
#
# 2. 内存安全：
#    - 限制单次读取的最大行数（10000行）
#    - 支持分页读取，避免大文件导致内存溢出
#
# 3. 信息丰富：
#    - 返回总行数、实际读取行数、是否截断等信息
#    - 便于调用者了解文件状态和分页情况
#
# =============================================================================
