"""
目录浏览工具 - BrowseDir
用于递归扫描目录并以树状结构展示内容
"""
import asyncio
import os
from pathlib import Path
from typing import Any

from core.logger import logger
from core.tool.base_tool import BaseTool


class BrowseDir(BaseTool):
    """
    目录浏览工具
    递归扫描目录并以树状结构展示内容，支持深度限制
    """
    tool_id = "browse_dir"
    name = "浏览目录"
    description = "递归扫描目录并以树状结构展示内容，支持深度限制和文件过滤"
    version = "1.0.0"

    # 关键文件扩展名列表
    KEY_EXTENSIONS = {
        '.py', '.js', '.ts', '.jsx', '.tsx', '.json', '.md', '.txt',
        '.exe', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf',
        '.html', '.htm', '.css', '.scss', '.less', '.xml', '.csv',
        '.sh', '.bat', '.ps1', '.cpp', '.c', '.h', '.hpp', '.java',
        '.go', '.rs', '.php', '.rb', '.swift', '.kt', '.sql', '.log'
    }

    input_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "要浏览的目录路径"
            },
            "depth": {
                "type": "integer",
                "default": 1,
                "minimum": 0,
                "maximum": 10,
                "description": "递归深度，默认为1，最大为10"
            },
            "show_files": {
                "type": "boolean",
                "default": True,
                "description": "是否显示文件，默认为True"
            }
        },
        "required": ["path"]
    }

    output_schema = {
        "type": "object",
        "properties": {
            "tree": {
                "type": "string",
                "description": "树状结构文本"
            }
        }
    }

    def __init__(self):
        super().__init__()

    def _is_key_file(self, filename: str) -> bool:
        """判断是否为关键文件"""
        _, ext = os.path.splitext(filename.lower())
        return ext in self.KEY_EXTENSIONS

    def _scan_directory(self, dir_path: Path, current_depth: int, max_depth: int,
                        show_files: bool, prefix: str = "") -> list[str]:
        """
        递归扫描目录

        Args:
            dir_path: 当前目录路径
            current_depth: 当前深度
            max_depth: 最大深度
            show_files: 是否显示文件
            prefix: 前缀字符串

        Returns:
            List[str]: 树状结构的行列表
        """
        lines = []

        if current_depth > max_depth:
            return lines

        try:
            entries = sorted(dir_path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        except PermissionError:
            lines.append(f"{prefix}[权限不足]")
            return lines
        except OSError as e:
            lines.append(f"{prefix}[错误: {e}]")
            return lines

        # 过滤条目
        filtered_entries = []
        for entry in entries:
            if entry.is_dir():
                # 跳过隐藏目录和特殊目录
                if entry.name.startswith('.') or entry.name in ['__pycache__', 'node_modules', '.venv', 'venv']:
                    continue
                filtered_entries.append(entry)
            elif show_files:
                # 只显示关键文件
                if self._is_key_file(entry.name):
                    filtered_entries.append(entry)

        total = len(filtered_entries)

        for i, entry in enumerate(filtered_entries):
            is_last = i == total - 1
            connector = "└── " if is_last else "├── "

            if entry.is_dir():
                lines.append(f"{prefix}{connector}{entry.name}/")
                next_prefix = prefix + ("    " if is_last else "│   ")
                lines.extend(self._scan_directory(
                    entry, current_depth + 1, max_depth, show_files, next_prefix
                ))
            else:
                lines.append(f"{prefix}{connector}{entry.name}")

        return lines

    def _execute(self, **kwargs) -> dict[str, Any]:
        """
        执行目录浏览

        Args:
            path: 目录路径
            depth: 递归深度（默认1）
            show_files: 是否显示文件（默认True）

        Returns:
            Dict[str, Any]: 包含树状结构的结果
        """
        # 参数校验
        check_result = self.check_params(**kwargs)
        if not check_result["success"]:
            return check_result

        path = kwargs.get("path")
        depth = kwargs.get("depth", 1)
        show_files = kwargs.get("show_files", True)

        # 检查中断
        if self.is_interrupted():
            return {
                "success": False,
                "error_code": "INTERRUPTED",
                "user_message": "浏览操作被中断",
                "data": None
            }

        # 验证路径
        dir_path = Path(path).expanduser().resolve()

        if not dir_path.exists():
            logger.error(f"[BrowseDir] 路径不存在: {path}")
            return {
                "success": False,
                "error_code": "PATH_NOT_FOUND",
                "user_message": f"路径不存在: {path}",
                "data": None
            }

        if not dir_path.is_dir():
            logger.error(f"[BrowseDir] 路径不是目录: {path}")
            return {
                "success": False,
                "error_code": "NOT_A_DIRECTORY",
                "user_message": f"路径不是目录: {path}",
                "data": None
            }

        # 生成树状结构
        tree_lines = [f"{dir_path.name}/"]
        tree_lines.extend(self._scan_directory(dir_path, 1, depth, show_files))

        tree_text = "\n".join(tree_lines)

        logger.info(f"[BrowseDir] 浏览目录: {path}, 深度: {depth}")

        return {
            "success": True,
            "error_code": None,
            "user_message": f"目录 '{path}' 浏览完成",
            "data": {
                "tree": tree_text,
                "path": str(dir_path),
                "depth": depth
            }
        }

    async def _execute_async(self, **kwargs) -> dict[str, Any]:
        return await asyncio.to_thread(self._execute, **kwargs)
