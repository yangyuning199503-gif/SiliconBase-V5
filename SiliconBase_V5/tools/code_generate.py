#!/usr/bin/env python3
"""
原子工具：代码生成（调用火山Ark或本地Ollama）
"""
import asyncio

from core.ai_adapter import generate_code_async
from core.base_tool import BaseTool
from core.error_codes import CODE_GEN_FAILED, INVALID_PARAMS, format_error
from tools.file_manager import FileManager


class CodeGenerate(BaseTool):
    tool_id = "code_generate"
    name = "代码生成"
    description = "根据需求生成/修复Python代码"
    input_schema = {
        "type": "object",
        "properties": {
            "instruction": {"type": "string"},
            "target_file": {"type": "string"}
        },
        "required": ["instruction"]
    }

    def _execute(self, **kwargs) -> dict:
        instruction = kwargs.get("instruction")
        if not instruction:
            return format_error(INVALID_PARAMS, detail="instruction 不能为空")
        target = kwargs.get("target_file", "")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            code, error = loop.run_until_complete(generate_code_async(instruction))
        finally:
            loop.close()
        if error:
            return format_error(CODE_GEN_FAILED, detail=error)
        if target:
            try:
                target = FileManager()._validate_path(target)
                with open(target, "w", encoding="utf-8") as f:
                    f.write(code)
                return {
                    "success": True,
                    "error_code": None,
                    "user_message": f"代码已生成并保存到 {target}",
                    "data": {"file": target, "code": code[:200]}
                }
            except Exception as e:
                return format_error(CODE_GEN_FAILED, detail=f"写入文件失败: {str(e)}")
        else:
            return {
                "success": True,
                "error_code": None,
                "user_message": f"代码生成成功，共 {len(code)} 字符",
                "data": {"code": code}
                }

    async def _execute_async(self, **kwargs) -> dict:
        """Phase 8 TRUE_ASYNC: 直接 await generate_code_async，零嵌套事件循环"""
        import aiofiles

        instruction = kwargs.get("instruction")
        if not instruction:
            return format_error(INVALID_PARAMS, detail="instruction 不能为空")
        target = kwargs.get("target_file", "")

        code, error = await generate_code_async(instruction)
        if error:
            return format_error(CODE_GEN_FAILED, detail=error)

        if target:
            try:
                target = FileManager()._validate_path(target)
                async with aiofiles.open(target, "w", encoding="utf-8") as f:
                    await f.write(code)
                return {
                    "success": True,
                    "error_code": None,
                    "user_message": f"代码已生成并保存到 {target}",
                    "data": {"file": target, "code": code[:200]}
                }
            except Exception as e:
                return format_error(CODE_GEN_FAILED, detail=f"写入文件失败: {str(e)}")
        else:
            return {
                "success": True,
                "error_code": None,
                "user_message": f"代码生成成功，共 {len(code)} 字符",
                "data": {"code": code}
            }
