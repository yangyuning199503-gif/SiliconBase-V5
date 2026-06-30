#!/usr/bin/env python3
"""
呼叫用户工具 - 让AI主动与用户沟通
"""
import asyncio

from core.base_tool import BaseTool
from core.logger import logger


class CallUser(BaseTool):
    tool_id = "call_user"
    name = "呼叫用户"
    description = "当AI有疑问、需要确认或需要用户介入时，调用此工具。系统会将消息以语音/文字形式通知用户，并等待回复。"
    input_schema = {
        "type": "object",
        "properties": {
            "message": {"type": "string", "description": "要向用户传达的消息"}
        },
        "required": ["message"]
    }

    def _execute(self, **kwargs) -> dict:
        from core.dialog.dialogue_manager import dialogue_manager  # 延迟导入
        message = kwargs.get("message", "")
        if not message:
            return {
                "success": False,
                "error_code": "INVALID_PARAMS",
                "user_message": "消息不能为空",
                "data": None
            }
        try:
            if dialogue_manager.voice:
                dialogue_manager.voice.speak(message)
            else:
                print(f"[AI呼叫用户] {message}")
            logger.info(f"AI呼叫用户: {message}")
            return {
                "success": True,
                "error_code": None,
                "user_message": f"已通知用户：{message}",
                "data": {"message": message}
            }
        except Exception as e:
            return {
                "success": False,
                "error_code": "CALL_FAILED",
                "user_message": f"呼叫用户失败: {e}",
                "data": None
            }
    async def _execute_async(self, **kwargs) -> dict:
        return await asyncio.to_thread(self._execute, **kwargs)
