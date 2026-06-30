#!/usr/bin/env python3
"""
组合工具：打开应用并聚焦
封装常用工作流：launch_app → wait → window_focus

使用场景：
- "打开微信"
- "启动浏览器"
- "打开记事本并准备输入"

对比原子工具：
- 原子：launch_app → window_get → window_focus（3步）
- 组合：open_and_focus（1步）
"""
import asyncio

from core.base_tool import BaseTool
from core.error_codes import TOOL_EXECUTION_ERROR, format_error


class OpenAndFocus(BaseTool):
    """
    组合工具：打开应用并聚焦窗口

    示例：
      open_and_focus(app_name="微信")
      open_and_focus(app_name="chrome", wait_time=3)
    """
    tool_id = "open_and_focus"
    name = "打开并聚焦"
    description = """打开应用程序并等待窗口出现，然后聚焦窗口。

适用场景：
- 启动应用后需要立即操作
- 需要确保窗口在前台
- 避免手动处理等待和聚焦步骤

示例：
  - 打开微信：open_and_focus(app_name="微信")
  - 打开浏览器并等待：open_and_focus(app_name="chrome", wait_time=5)
  - 指定窗口标题：open_and_focus(app_name="notepad", window_title="无标题")

底层调用：launch_app → wait → window_get → window_focus
"""
    input_schema = {
        "type": "object",
        "properties": {
            "app_name": {
                "type": "string",
                "description": "应用名称（如'微信'、'chrome'、'notepad'）"
            },
            "wait_time": {
                "type": "number",
                "default": 2,
                "description": "等待窗口出现的时间（秒），默认2秒"
            },
            "window_title": {
                "type": "string",
                "description": "可选，指定窗口标题关键词（用于多窗口应用）"
            }
        },
        "required": ["app_name"]
    }

    async def run(self, **kwargs) -> dict:
        return await self.run_async(**kwargs)

    async def _execute_async(self, **kwargs) -> dict:
        import asyncio

        # 延迟导入避免循环导入
        from core.tool_manager import tool_manager

        app_name = kwargs.get("app_name")
        wait_time = kwargs.get("wait_time", 2)
        window_title = kwargs.get("window_title")

        try:
            # Step 1: 启动应用
            launch_tool = tool_manager.get_tool("launch_app")
            if not launch_tool:
                return format_error(TOOL_EXECUTION_ERROR, detail="launch_app 工具不可用")

            result = await launch_tool.run(app_name=app_name)
            if not result.get("success"):
                return result  # 启动失败直接返回

            # Step 2: 等待窗口出现
            await asyncio.sleep(wait_time)

            # Step 3: 查找窗口
            window_tool = tool_manager.get_tool("window_get")
            if not window_tool:
                return format_error(TOOL_EXECUTION_ERROR, detail="window_get 工具不可用")

            # 如果有指定标题，用标题匹配
            search_title = window_title or app_name
            result = window_tool.run(app_name=search_title)

            if not result.get("success"):
                # 窗口可能还没出现，再试一次
                await asyncio.sleep(1)
                result = window_tool.run(app_name=search_title)

            if not result.get("success"):
                # 窗口仍未找到，但应用已启动
                user_msg = f"{app_name} 已启动，但窗口未找到（可能需要更长的 wait_time）"
                return {
                    "success": True,  # 部分成功
                    "error_code": None,
                    "user_message": user_msg,
                    "data": {
                        "launched": True,
                        "focused": False
                    }
                }

            hwnd = result["data"]["hwnd"]

            # Step 4: 聚焦窗口
            focus_tool = tool_manager.get_tool("window_focus")
            if focus_tool:
                await focus_tool.run(hwnd=hwnd)

            return {
                "success": True,
                "error_code": None,
                "user_message": f"{app_name} 已启动并聚焦",
                "data": {
                    "launched": True,
                    "focused": True,
                    "hwnd": hwnd,
                    "window_title": result["data"].get("title", "")
                }
            }

        except Exception as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=f"打开并聚焦失败: {str(e)}")


class FindAndClick(BaseTool):
    """
    组合工具：查找图标并点击

    示例：
      find_and_click(template="wechat_icon.png")
      find_and_click(template="submit_button.png", region=[0, 0, 800, 600])
    """
    tool_id = "find_and_click"
    name = "查找并点击"
    description = """在屏幕上查找指定图标/模板，找到后自动点击。

适用场景：
- 点击"确定"、"提交"等按钮
- 点击应用图标
- 在复杂界面中找到特定元素

前提条件：
- 需要先用 template_record 录制模板图片

示例：
  - 点击微信图标：find_and_click(template="wechat_icon.png")
  - 在指定区域搜索：find_and_click(template="ok_button.png", region=[100, 100, 400, 300])
  - 点击坐标：find_and_click(template="close_btn.png")  # 自动点击中心点

底层调用：template_match → mouse_click
"""
    input_schema = {
        "type": "object",
        "properties": {
            "template": {
                "type": "string",
                "description": "模板图片文件名（如'wechat_icon.png'），必须先在templates/目录下录制"
            },
            "region": {
                "type": "array",
                "items": {"type": "integer"},
                "minItems": 4,
                "maxItems": 4,
                "description": "可选，搜索区域 [left, top, width, height]"
            },
            "threshold": {
                "type": "number",
                "default": 0.8,
                "description": "匹配阈值（0-1），越高越严格"
            }
        },
        "required": ["template"]
    }

    def _execute(self, **kwargs) -> dict:
        from core.tool_manager import tool_manager

        template = kwargs.get("template")
        region = kwargs.get("region")
        threshold = kwargs.get("threshold", 0.8)

        try:
            # Step 1: 查找模板
            match_tool = tool_manager.get_tool("template_match")
            if not match_tool:
                return format_error(TOOL_EXECUTION_ERROR, detail="template_match 工具不可用")

            template_path = template if template.endswith('.png') else f"{template}.png"
            result = match_tool.run(
                template_path=template_path,
                region=region,
                threshold=threshold
            )

            if not result.get("success"):
                return {
                    "success": False,
                    "error_code": "ELEMENT_NOT_FOUND",
                    "user_message": f"未找到模板: {template}",
                    "data": None
                }

            # 获取匹配位置的中心点
            match_data = result["data"]["best_match"]
            x = match_data["center"]["x"]
            y = match_data["center"]["y"]
            confidence = match_data["confidence"]

            # Step 2: 点击
            click_tool = tool_manager.get_tool("mouse_click")
            if not click_tool:
                return format_error(TOOL_EXECUTION_ERROR, detail="mouse_click 工具不可用")

            click_result = click_tool.run(x=x, y=y)

            if click_result.get("success"):
                return {
                    "success": True,
                    "error_code": None,
                    "user_message": f"已点击 {template}（置信度: {confidence:.2f}）",
                    "data": {
                        "clicked": True,
                        "position": {"x": x, "y": y},
                        "confidence": confidence,
                        "template": template
                    }
                }
            else:
                return click_result

        except Exception as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=f"查找并点击失败: {str(e)}")

    async def _execute_async(self, **kwargs) -> dict:
        return await asyncio.to_thread(self._execute, **kwargs)


class SmartFormFill(BaseTool):
    """
    组合工具：智能表单填写

    示例：
      smart_form_fill(fields=[
          {"label": "用户名", "value": "admin"},
          {"label": "密码", "value": "123456"}
      ])
    """
    tool_id = "smart_form_fill"
    name = "智能填表"
    description = """自动识别表单字段并填写内容。

适用场景：
- 登录表单填写
- 搜索框输入
- 配置页面填写

工作原理：
1. OCR识别屏幕上的表单标签（如"用户名"、"密码"）
2. 找到对应的输入框位置
3. 点击输入框并输入内容
4. 自动跳转到下一个字段

示例：
  - 登录：smart_form_fill(fields=[
      {"label": "用户名", "value": "admin"},
      {"label": "密码", "value": "123456"}
    ])
  - 搜索：smart_form_fill(fields=[{"label": "搜索", "value": "天气预报"}])

底层调用：screen_ocr → click_text → keyboard_input（循环）
"""
    input_schema = {
        "type": "object",
        "properties": {
            "fields": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string", "description": "字段标签（如'用户名'）"},
                        "value": {"type": "string", "description": "要填入的值"}
                    },
                    "required": ["label", "value"]
                },
                "description": "字段列表"
            },
            "submit": {
                "type": "boolean",
                "default": True,
                "description": "是否自动点击提交/确定按钮"
            }
        },
        "required": ["fields"]
    }

    def _execute(self, **kwargs) -> dict:
        from core.tool_manager import tool_manager

        fields = kwargs.get("fields", [])
        submit = kwargs.get("submit", True)

        if not fields:
            return format_error(TOOL_EXECUTION_ERROR, detail="fields 不能为空")

        results = []

        try:
            for field in fields:
                label = field.get("label")
                value = field.get("value")

                # Step 1: 点击字段标签（找到输入框）
                # 实际实现需要更复杂的逻辑：找到标签附近的输入框
                # 这里简化为直接点击标签下方的位置
                click_tool = tool_manager.get_tool("click_text")
                if click_tool:
                    click_result = click_tool.run(text=label)
                    if not click_result.get("success"):
                        results.append({"field": label, "status": "label_not_found"})
                        continue

                # Step 2: 输入内容
                input_tool = tool_manager.get_tool("keyboard_input")
                if input_tool:
                    input_tool.run(text=value)
                    results.append({"field": label, "status": "filled", "value": value[:10] + "..." if len(value) > 10 else value})

            # Step 3: 点击提交（如果需要）
            if submit:
                # 尝试点击"确定"、"提交"、"登录"等
                for submit_text in ["确定", "提交", "登录", "保存", "下一步"]:
                    click_tool = tool_manager.get_tool("click_text")
                    result = click_tool.run(text=submit_text)
                    if result.get("success"):
                        results.append({"action": "submit", "button": submit_text})
                        break

            filled_count = len([r for r in results if r.get("status") == "filled"])
            return {
                "success": True,
                "error_code": None,
                "user_message": f"表单填写完成，成功填写 {filled_count} 个字段",
                "data": {
                    "filled_count": filled_count,
                    "details": results
                }
            }

        except Exception as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=f"填表失败: {str(e)}")

    async def _execute_async(self, **kwargs) -> dict:
        return await asyncio.to_thread(self._execute, **kwargs)
