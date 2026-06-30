#!/usr/bin/env python3
"""
文件管理工具 - 合并版
原: file_list.py + file_read.py + file_write.py + file_delete.py
支持: 列表/读取/写入/删除文件
2026-03-11 修复：将run改为_execute，异常处理交由基类统一处理
"""
import asyncio
import os
import shutil
from pathlib import Path

from core.base_tool import BaseTool
from core.error_codes import (
    DELETE_ERROR,
    FILE_NOT_FOUND,
    INVALID_PARAMS,
    PATH_NOT_FOUND,
    READ_ERROR,
    format_error,
)
from core.logger import logger


class FileManager(BaseTool):
    """
    文件管理工具（合并版）
    支持: list列表, read读取, write写入, delete删除
    安全特性: 路径遍历攻击防护

    【云端+本地双版本管控】
    - owner: system (系统内置工具)
    - 在云端模式下正常可用
    """
    tool_id = "file_manager"
    tool_owner = "system"  # 系统内置工具
    name = "文件管理"
    description = "文件操作：列出目录、读取、写入、删除文件"
    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "read", "write", "delete"],
                "description": "操作类型：list列表, read读取, write写入, delete删除"
            },
            "path": {
                "type": "string",
                "description": "文件或目录路径"
            },
            "content": {
                "type": "string",
                "description": "写入内容（write操作时需要）"
            },
            "encoding": {
                "type": "string",
                "default": "utf-8",
                "description": "文件编码"
            },
            "pattern": {
                "type": "string",
                "default": "*",
                "description": "文件匹配模式（list操作时使用）"
            },
            "recursive": {
                "type": "boolean",
                "default": False,
                "description": "是否递归删除目录（delete操作时使用）"
            },
            "confirm_text": {
                "type": "string",
                "description": "删除确认文本，请输入 'DELETE'（delete操作时需要）"
            }
        },
        "required": ["action", "path"]
    }

    def __init__(self):
        super().__init__()
        # 设置允许操作的基础路径（当前工作目录）
        self.base_path = os.path.abspath(os.getcwd())

    def _validate_path(self, user_path: str) -> str:
        """
        验证并规范化路径，防止路径遍历攻击

        Args:
            user_path: 用户提供的相对路径

        Returns:
            str: 规范化后的完整路径

        Raises:
            ValueError: 检测到路径遍历攻击
        """
        # 规范化路径，解析 .. 和 .
        full_path = os.path.normpath(os.path.join(self.base_path, user_path))

        # 确保规范化后的路径在 base_path 内（防止路径遍历）
        base_path_normalized = os.path.normpath(self.base_path)
        if not full_path.startswith(base_path_normalized):
            raise ValueError(f"路径遍历攻击检测: 路径 '{user_path}' 试图访问允许范围之外的目录")

        return full_path

    async def _execute_async(self, **kwargs) -> dict:
        """
        异步执行文件操作 - 显式桥接到线程池

        文件 I/O 操作本质上是同步的，无法在不引入新依赖的情况下真正异步化。
        使用 run_in_executor 将阻塞操作放到线程池中执行，避免阻塞事件循环。
        TODO: 未来可迁移到 aiofiles 实现真正的异步文件操作。
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self._execute(**kwargs))

    def _execute(self, **kwargs) -> dict:
        """执行文件操作 - 异常由基类统一处理"""
        action = kwargs.get("action")
        path = kwargs.get("path") or kwargs.get("file_path")

        if not action:
            return format_error(INVALID_PARAMS, detail="action 不能为空")
        if not path:
            return format_error(INVALID_PARAMS, detail="path 不能为空")

        # 分发到具体方法
        if action == "list":
            return self._list_files(path, kwargs.get("pattern", "*"))
        elif action == "read":
            return self._read_file(path, kwargs.get("encoding", "utf-8"))
        elif action == "write":
            content = kwargs.get("content")
            if content is None:
                return format_error(INVALID_PARAMS, detail="write操作需要content参数")
            return self._write_file(
                path, content,
                kwargs.get("encoding", "utf-8")
            )
        elif action == "delete":
            confirm = kwargs.get("confirm_text")
            if confirm != "DELETE":
                return format_error(
                    INVALID_PARAMS,
                    detail="删除操作需要 confirm_text='DELETE' 确认"
                )
            return self._delete_file(path, kwargs.get("recursive", False))
        else:
            return format_error(INVALID_PARAMS, detail=f"未知操作: {action}")

    def _list_files(self, path: str, pattern: str) -> dict:
        """列出目录文件"""
        validated_path = self._validate_path(path)

        p = Path(validated_path)
        if not p.exists():
            return format_error(PATH_NOT_FOUND, path=path)
        if not p.is_dir():
            return format_error(READ_ERROR, detail="路径不是目录")

        files = []
        for f in p.glob(pattern):
            stat = f.stat()
            files.append({
                "name": f.name,
                "path": str(f),
                "is_dir": f.is_dir(),
                "size": stat.st_size if f.is_file() else 0,
                "modified": stat.st_mtime
            })

        logger.info(f"[FileManager] 列出目录: {path}, 找到 {len(files)} 个文件")
        return {
            "success": True,
            "error_code": None,
            "user_message": f"目录 '{path}' 中共有 {len(files)} 个文件/目录",
            "data": {"files": files}
        }

    def _read_file(self, path: str, encoding: str) -> dict:
        """读取文件内容"""
        validated_path = self._validate_path(path)

        if not os.path.exists(validated_path):
            return format_error(FILE_NOT_FOUND, path=path)

        with open(validated_path, encoding=encoding) as f:
            content = f.read()

        logger.info(f"[FileManager] 读取文件: {path}, 大小: {len(content)} 字符")
        return {
            "success": True,
            "error_code": None,
            "user_message": f"文件 '{path}' 读取成功，共 {len(content)} 字符",
            "data": {"content": content}
        }

    def _write_file(self, path: str, content: str, encoding: str) -> dict:
        """写入文件内容"""
        validated_path = self._validate_path(path)

        os.makedirs(os.path.dirname(validated_path) or ".", exist_ok=True)
        with open(validated_path, "w", encoding=encoding) as f:
            f.write(content)

        logger.info(f"[FileManager] 写入文件: {path}, 大小: {len(content)} 字符")
        return {
            "success": True,
            "error_code": None,
            "user_message": f"文件 '{path}' 写入成功，共 {len(content)} 字符",
            "data": {"message": f"文件已写入: {path}"}
        }

    def _delete_file(self, path: str, recursive: bool) -> dict:
        """删除文件或目录"""
        validated_path = self._validate_path(path)

        if not os.path.exists(validated_path):
            return format_error(PATH_NOT_FOUND, path=path)

        if os.path.isfile(validated_path):
            os.remove(validated_path)
            logger.info(f"[FileManager] 删除文件: {path}")
        elif os.path.isdir(validated_path):
            if recursive:
                shutil.rmtree(validated_path)
                logger.info(f"[FileManager] 递归删除目录: {path}")
            else:
                os.rmdir(validated_path)
                logger.info(f"[FileManager] 删除目录: {path}")
        else:
            return format_error(DELETE_ERROR, detail="不是文件或目录")

        return {
            "success": True,
            "error_code": None,
            "user_message": f"'{path}' 删除成功",
            "data": {"message": f"已删除: {path}"}
        }
