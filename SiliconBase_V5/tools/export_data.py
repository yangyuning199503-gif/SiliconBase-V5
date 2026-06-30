#!/usr/bin/env python3
"""
原子工具：导出用户数据
导出记忆库、配置、日志等，打包为 ZIP 文件
"""
import asyncio
import os
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from core.base_tool import BaseTool
from core.error_codes import TOOL_EXECUTION_ERROR, format_error


class ExportData(BaseTool):
    tool_id = "export_data"
    name = "导出用户数据"
    description = "导出所有用户数据（记忆库、配置、日志）为 ZIP 文件，保存到桌面"
    input_schema = {
        "type": "object",
        "properties": {
            "include_logs": {"type": "boolean", "default": True},
            "include_memory": {"type": "boolean", "default": True},
            "include_config": {"type": "boolean", "default": True},
            "include_tools": {"type": "boolean", "default": False}
        }
    }
    require_confirmation = True

    def _execute(self, **kwargs):
        include_logs = kwargs.get("include_logs", True)
        include_memory = kwargs.get("include_memory", True)
        include_config = kwargs.get("include_config", True)
        include_tools = kwargs.get("include_tools", False)

        base_dir = Path(__file__).parent.parent
        data_dir = base_dir / "data"
        logs_dir = base_dir / "logs"
        config_dir = base_dir / "config"
        tools_dir = base_dir / "tools"

        desktop = Path.home() / "Desktop"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_name = f"siliconbase_export_{timestamp}.zip"
        zip_path = desktop / zip_name

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_path = Path(tmpdir)

                # 收集文件
                if include_memory and data_dir.exists():
                    for item in data_dir.rglob("*"):
                        if item.is_file():
                            rel_path = item.relative_to(data_dir)
                            dest = tmp_path / "data" / rel_path
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            dest.write_bytes(item.read_bytes())

                if include_logs and logs_dir.exists():
                    for item in logs_dir.rglob("*"):
                        if item.is_file():
                            rel_path = item.relative_to(logs_dir)
                            dest = tmp_path / "logs" / rel_path
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            dest.write_bytes(item.read_bytes())

                if include_config and config_dir.exists():
                    for item in config_dir.rglob("*.yaml"):
                        if item.is_file():
                            rel_path = item.relative_to(config_dir)
                            dest = tmp_path / "config" / rel_path
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            dest.write_bytes(item.read_bytes())

                if include_tools and tools_dir.exists():
                    for item in tools_dir.rglob("*.py"):
                        if item.is_file() and item.name != "__init__.py":
                            rel_path = item.relative_to(tools_dir)
                            dest = tmp_path / "tools" / rel_path
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            dest.write_bytes(item.read_bytes())

                # 创建 ZIP
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for root, _dirs, files in os.walk(tmp_path):
                        for file in files:
                            full_path = os.path.join(root, file)
                            arcname = os.path.relpath(full_path, tmp_path)
                            zf.write(full_path, arcname)

            return {
                "success": True,
                "error_code": None,
                "user_message": f"数据已导出到桌面: {zip_name}",
                "data": {
                    "file_path": str(zip_path),
                    "file_size": os.path.getsize(zip_path)
                }
            }
        except Exception as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=str(e))
    async def _execute_async(self, **kwargs) -> dict:
        return await asyncio.to_thread(self._execute, **kwargs)
