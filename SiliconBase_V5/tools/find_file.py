#!/usr/bin/env python3
"""
原子工具：查找文件位置
基于 global_view 的文件索引，AI可以查询任何文件的位置
"""
import asyncio
import os

from core.base_tool import BaseTool
from core.error_codes import FILE_NOT_FOUND, INVALID_PARAMS, format_error
from core.logger import logger


class FindFile(BaseTool):
    """
    查找文件工具 - 查询全盘扫描记录的文件位置

    使用场景:
    - AI写代码时需要知道某个程序的位置
    - 用户问"我的XXX文件在哪"
    - 查找特定类型的文件（如所有Python文件）
    """
    tool_id = "find_file"
    tool_owner = "system"
    name = "查找文件"
    description = "根据文件名或关键词查找文件在磁盘上的位置。支持模糊搜索，可以查找可执行文件、代码文件、文档等。"
    input_schema = {
        "type": "object",
        "properties": {
            "keyword": {
                "type": "string",
                "description": "文件名或关键词，如 'cloudmusic', 'mhxy', 'python', '*.py'"
            },
            "file_type": {
                "type": "string",
                "description": "文件类型过滤，可选值: executable(可执行文件), code(代码), document(文档), media(媒体), script(脚本), all(全部)",
                "enum": ["executable", "code", "document", "media", "script", "archive", "other", "all"]
            },
            "limit": {
                "type": "integer",
                "description": "返回结果数量，默认10",
                "default": 10
            }
        },
        "required": ["keyword"]
    }

    def _execute(self, **kwargs) -> dict:
        """执行文件查找"""
        keyword = kwargs.get("keyword", "").strip()
        file_type = kwargs.get("file_type", "all")
        limit = kwargs.get("limit", 10)

        if not keyword:
            return format_error(INVALID_PARAMS, detail="keyword参数不能为空")

        # file_type为all时设为None
        if file_type == "all":
            file_type = None

        try:
            # 延迟导入避免循环依赖
            from sensors.system.global_view import global_view

            # 查询文件索引
            results = global_view.search_files(
                keyword=keyword,
                file_type=file_type,
                user_id=kwargs.get("user_id", "default"),
                limit=limit
            )

            if not results:
                return {
                    "success": False,
                    "error_code": "FILE_NOT_FOUND",
                    "user_message": f"没找到包含 '{keyword}' 的文件。可能原因：\n1. 文件还未被全盘扫描收录\n2. 关键词不准确\n3. 文件在未被扫描的磁盘",
                    "data": None
                }

            # 格式化结果
            formatted_results = []
            for r in results:
                size_mb = r['file_size'] / (1024*1024) if r['file_size'] else 0
                formatted_results.append({
                    "file_name": r['file_name'],
                    "file_path": r['file_path'],
                    "size_mb": round(size_mb, 2),
                    "file_type": r['file_type'],
                    "is_executable": r['is_executable']
                })

            # 构建用户友好的消息
            if len(formatted_results) == 1:
                user_msg = f"找到文件: {formatted_results[0]['file_path']}"
            else:
                user_msg = f"找到 {len(formatted_results)} 个匹配的文件"

            return {
                "success": True,
                "error_code": None,
                "user_message": user_msg,
                "data": {
                    "keyword": keyword,
                    "count": len(formatted_results),
                    "files": formatted_results
                }
            }

        except Exception as e:
            logger.error(f"[FindFile] 查找文件失败: {e}")
            return format_error(FILE_NOT_FOUND, detail=str(e))

    async def _execute_async(self, **kwargs) -> dict:
        return await asyncio.to_thread(self._execute, **kwargs)


class ListAllFiles(BaseTool):
    """
    列出所有已索引的文件（用于调试和概览）
    """
    tool_id = "list_indexed_files"
    tool_owner = "system"
    name = "列出已索引文件"
    description = "列出全盘扫描已记录的所有文件，可按类型过滤"
    input_schema = {
        "type": "object",
        "properties": {
            "file_type": {
                "type": "string",
                "description": "文件类型过滤",
                "enum": ["executable", "code", "document", "media", "script", "all"]
            },
            "limit": {
                "type": "integer",
                "default": 50
            }
        }
    }

    def _execute(self, **kwargs) -> dict:
        """列出已索引的文件"""
        file_type = kwargs.get("file_type")
        limit = kwargs.get("limit", 50)

        if file_type == "all":
            file_type = None

        try:
            from sensors.system.global_view import global_view
            results = global_view.search_files("", file_type=file_type, limit=limit)

            return {
                "success": True,
                "user_message": f"已索引 {len(results)} 个文件",
                "data": {
                    "count": len(results),
                    "files": results
                }
            }
        except Exception as e:
            return format_error(FILE_NOT_FOUND, detail=str(e))

    async def _execute_async(self, **kwargs) -> dict:
        return await asyncio.to_thread(self._execute, **kwargs)


# 快捷函数供代码直接使用
def find_executable(name: str) -> str:
    """
    查找可执行文件的完整路径

    Args:
        name: 程序名，如 'cloudmusic', 'mhxy'

    Returns:
        完整路径或空字符串
    """
    try:
        from sensors.system.global_view import global_view
        results = global_view.search_files(name, file_type="executable", limit=5)

        for r in results:
            if r['is_executable'] and os.path.exists(r['file_path']):
                return r['file_path']
        return ""
    except Exception:
        return ""
