#!/usr/bin/env python3
"""
原子工具：模板录制
快速录制屏幕区域作为模板，供template_match使用

使用场景：
1. 让AI学习新的图标位置
2. 创建可复用的UI元素模板
3. 训练AI识别特定界面元素
"""

import asyncio
import contextlib
import time
from pathlib import Path

from PIL import Image

from core.base_tool import BaseTool
from core.error_codes import INVALID_PARAMS, TOOL_EXECUTION_ERROR, format_error
from core.vision.safe_screenshot import safe_screenshot_to_pil


class TemplateRecord(BaseTool):
    """
    模板录制工具
    """
    tool_id = "template_record"
    name = "录制模板"
    description = "录制屏幕区域作为模板图片，用于后续的模板匹配"
    input_schema = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "模板名称（如'wechat_icon','submit_button'）"
            },
            "region": {
                "type": "array",
                "items": {"type": "integer"},
                "minItems": 4,
                "maxItems": 4,
                "description": "录制区域 [left, top, width, height]"
            },
            "delay": {
                "type": "integer",
                "default": 3,
                "description": "截图延迟（秒），给你时间准备界面"
            },
            "description": {
                "type": "string",
                "description": "模板描述（可选）"
            }
        },
        "required": ["name", "region"]
    }

    def _execute(self, **kwargs) -> dict:
        name = kwargs.get("name")
        region = kwargs.get("region")
        delay = kwargs.get("delay", 3)
        description = kwargs.get("description", "")

        if not name:
            return format_error(INVALID_PARAMS, detail="name 不能为空")

        if not region or len(region) != 4:
            return format_error(INVALID_PARAMS, detail="region 必须是 [left, top, width, height]")

        try:
            # 确保templates目录存在
            templates_dir = Path("templates")
            templates_dir.mkdir(exist_ok=True)

            # 延迟截图
            if delay > 0:
                print(f"[{delay}秒后开始录制...]")
                time.sleep(delay)

            # 截图 - 【蓝屏修复】使用线程安全截图
            left, top, width, height = region
            monitor_region = {
                "left": left,
                "top": top,
                "width": width,
                "height": height
            }
            img = safe_screenshot_to_pil(monitor=1, region=monitor_region)

            if img is None:
                return format_error(TOOL_EXECUTION_ERROR, detail="截图失败")

            # 保存
            filename = f"{name}.png"
            filepath = templates_dir / filename
            img.save(filepath, "PNG")

            # 保存描述文件
            if description:
                desc_file = templates_dir / f"{name}.txt"
                with open(desc_file, 'w', encoding='utf-8') as f:
                    f.write(description)

            return {
                "success": True,
                "error_code": None,
                "user_message": f"模板已保存: {filepath}",
                "data": {
                    "name": name,
                    "filepath": str(filepath),
                    "size": [width, height],
                    "description": description
                }
            }

        except Exception as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=f"录制失败: {str(e)}")

    async def _execute_async(self, **kwargs) -> dict:
        return await asyncio.to_thread(self._execute, **kwargs)


class TemplateList(BaseTool):
    """
    列出所有已录制的模板
    """
    tool_id = "template_list"
    name = "列出模板"
    description = "列出所有可用的模板图片"
    input_schema = {
        "type": "object",
        "properties": {}
    }

    def _execute(self, **kwargs) -> dict:
        templates_dir = Path("templates")
        if not templates_dir.exists():
            return {
                "success": True,
                "error_code": None,
                "user_message": "暂无模板",
                "data": {"templates": [], "count": 0}
            }

        templates = []
        for png_file in templates_dir.glob("*.png"):
            name = png_file.stem
            desc_file = png_file.with_suffix('.txt')
            description = ""
            if desc_file.exists():
                with contextlib.suppress(Exception):
                    description = desc_file.read_text(encoding='utf-8').strip()

            # 获取图片尺寸
            try:
                with Image.open(png_file) as img:
                    size = img.size
            except Exception:
                size = [0, 0]

            templates.append({
                "name": name,
                "file": str(png_file),
                "size": size,
                "description": description
            })

        return {
            "success": True,
            "error_code": None,
            "user_message": f"共 {len(templates)} 个模板",
            "data": {
                "templates": templates,
                "count": len(templates)
            }
        }

    async def _execute_async(self, **kwargs) -> dict:
        return await asyncio.to_thread(self._execute, **kwargs)


class TemplateDelete(BaseTool):
    """
    删除模板
    """
    tool_id = "template_delete"
    name = "删除模板"
    description = "删除指定的模板图片"
    input_schema = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "模板名称"
            }
        },
        "required": ["name"]
    }

    def _execute(self, **kwargs) -> dict:
        name = kwargs.get("name")
        templates_dir = Path("templates")

        png_file = templates_dir / f"{name}.png"
        txt_file = templates_dir / f"{name}.txt"

        deleted = []
        if png_file.exists():
            png_file.unlink()
            deleted.append(str(png_file))

        if txt_file.exists():
            txt_file.unlink()
            deleted.append(str(txt_file))

        if deleted:
            return {
                "success": True,
                "error_code": None,
                "user_message": f"已删除模板: {name}",
                "data": {"deleted": deleted}
            }
        else:
            return format_error(
                TOOL_EXECUTION_ERROR,
                detail=f"模板不存在: {name}"
            )

    async def _execute_async(self, **kwargs) -> dict:
        return await asyncio.to_thread(self._execute, **kwargs)
