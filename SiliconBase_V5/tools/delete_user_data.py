#!/usr/bin/env python3
"""
原子工具：删除用户数据
清空记忆库、日志等（配置保留）
"""
import asyncio
import shutil
from pathlib import Path

from core.base_tool import BaseTool
from core.error_codes import TOOL_EXECUTION_ERROR, format_error


class DeleteUserData(BaseTool):
    tool_id = "delete_user_data"
    name = "删除用户数据"
    description = "清空所有用户数据（记忆库、日志），但保留配置和工具"
    input_schema = {
        "type": "object",
        "properties": {
            "confirm_text": {"type": "string", "description": "请输入 'DELETE' 确认"}
        },
        "required": ["confirm_text"]
    }
    require_confirmation = True

    def _execute(self, **kwargs):
        confirm = kwargs.get("confirm_text")
        if confirm != "DELETE":
            return {
                "success": False,
                "error_code": "INVALID_CONFIRMATION",
                "user_message": "确认文本错误，请输入 'DELETE' 以确认删除",
                "data": None
            }

        base_dir = Path(__file__).parent.parent
        data_dir = base_dir / "data"
        logs_dir = base_dir / "logs"

        try:
            # 清空 data 目录（保留目录本身）
            if data_dir.exists():
                for item in data_dir.iterdir():
                    if item.is_dir():
                        shutil.rmtree(item)
                    else:
                        item.unlink()

            # 清空 logs 目录
            if logs_dir.exists():
                for item in logs_dir.iterdir():
                    if item.is_dir():
                        shutil.rmtree(item)
                    else:
                        item.unlink()

            return {
                "success": True,
                "error_code": None,
                "user_message": "所有用户数据已清空",
                "data": {"cleared": True}
            }
        except Exception as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=str(e))
    async def _execute_async(self, **kwargs) -> dict:
        return await asyncio.to_thread(self._execute, **kwargs)
